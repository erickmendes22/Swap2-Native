"""Read-only mesh payloads: exact GPU output, zero/short inputs and fallback.

Software timings describe this fixture, never Android FPS.
"""
import ctypes as C
import json
import os
from pathlib import Path
import statistics
import struct
import subprocess
import unittest
from unittest.mock import patch
import test_memu_coalesced_readback as memu
from test_memu_coalesced_readback import U32, ROOT, instructions


class DirectPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        memu.CoalescedReadback.setUpClass()
        cls.h = memu.CoalescedReadback()

    @classmethod
    def tearDownClass(cls):
        memu.CoalescedReadback.tearDownClass()

    def convert(self, words, enabled, coalesced=0):
        with patch.dict(os.environ, DM_VK_MEMU_DIRECT_PAYLOAD="2" if enabled else "0"):
            return self.h.convert(words, coalesced)

    def test_qualified_or_escaped_payload_retains_original(self):
        words = list(memu.CoalescedReadback.fixtures['MESH_TRI'])
        payload = next(a[1] for o, a in instructions(words) if o == 59 and a[2] == 5402)
        pointers = {a[1] for o, a in instructions(words) if o == 65 and a[2] == payload}
        self.assertNotEqual(self.convert(words, 0)[1], self.convert(words, 1)[1])
        i = 5
        while i < len(words):
            n, op = words[i] >> 16, words[i] & 65535
            if op == 61 and words[i+3] in pointers:
                # Volatile load: the optimizer must not reinterpret qualifiers.
                qualified = words[:i] + [(n+1)<<16|op] + words[i+1:i+n] + [1] + words[i+n:]
                self.assertEqual(self.convert(qualified, 0)[1], self.convert(qualified, 1)[1])
                # Unknown pointer escape, conservatively rejected as a whole.
                escaped = words[:i] + [4<<16|83, words[i+1], words[3], words[i+3]] + words[i:]
                escaped[3] += 1
                self.assertEqual(self.convert(escaped, 0)[1], self.convert(escaped, 1)[1])
                break
            i += n
        else:
            self.fail('fixture did not contain payload loads')

    def test_production_threshold_is_large_only(self):
        words = memu.CoalescedReadback.fixtures['MESH_TRI']
        with patch.dict(os.environ, DM_VK_MEMU_DIRECT_PAYLOAD='1'):
            small = self.h.convert(words, 0)[1]
        self.assertEqual(small, self.convert(words, 0)[1])

    @unittest.skipUnless(os.environ.get('MEMU_TEST_VULKAN') == '1', 'requires Vulkan ICD')
    def test_exact_gpu_outputs_and_copy_elimination(self):
        runner = memu.CoalescedReadback.work/'payload-dispatch'
        subprocess.run([memu.CoalescedReadback.cc, '-O1', '-Wall', '-Wextra', '-Werror', '-I',
                        str(ROOT/'dm/third_party/vulkan-headers/include'),
                        str(ROOT/'dm/host/tests/t_android_memu_dispatch.c'),
                        '-Wl,-l:libvulkan.so.1', '-o', str(runner)], check=True)
        source = (ROOT/'dm/host/tests/memu/mesh_tri.spvasm').read_text()
        for width in (8, 64, 1024):
            asm=memu.CoalescedReadback.work/'payload.spvasm'; spv=memu.CoalescedReadback.work/'payload.spv'
            asm.write_text(source.replace('%uint_8 = OpConstant %uint 8', f'%uint_8 = OpConstant %uint {width}'))
            subprocess.run(['spirv-as','--target-env','vulkan1.3',str(asm),'-o',str(spv)],check=True)
            words=list(struct.unpack(f'<{spv.stat().st_size//4}I',spv.read_bytes()))
            for coalesced in (0, 1):
                layout, baseline, _ = self.convert(words, 0, coalesced)
                _, direct, _ = self.convert(words, 1, coalesced)
                self.assertEqual(layout.payload_words,width)
                self.assertNotEqual(direct,baseline)
                if width == 1024: self.assertLess(len(direct),len(baseline))
                # Exactly the emulation's payload barrier disappears; guest barriers stay.
                count=lambda module,op: sum(o==op for o,a in instructions(module))
                self.assertEqual(count(baseline,224)-count(direct,224),1)
                for kind,mod in [('baseline',baseline),('direct',direct)]:
                    memu.CoalescedReadback.write_words(memu.CoalescedReadback.work/f'{kind}.spv',mod)
                    subprocess.run(['spirv-val','--target-env','vulkan1.3',str(memu.CoalescedReadback.work/f'{kind}.spv')],check=True)
                for task,wt in ((False,0),(True,0),(True,2),(True,width)):
                    rec=(U32*32)();memu.CoalescedReadback.lib.vka_memu_rec_mesh(C.byref(layout),rec)
                    rec[12],rec[21],rec[24]=7,3 if task else 0,4
                    rec[13]|=1 if task else 0
                    rec[14],rec[22],rec[23]=wt,128,64
                    rec[25]=layout.vw*layout.max_v*4+128+3*max(wt,1)
                    rec[26]=rec[25]+rec[15]*4
                    initial=[0x7fc12345]*(rec[26]+rec[16]*4+1024)
                    initial[64:67]=[0,2,2] # empty middle task / duplicate prefix
                    for t in range(3):
                        for k in range(wt):initial[128+t*wt+k]=100+t if k==1 else min(k,9)
                    memu.CoalescedReadback.write_words(memu.CoalescedReadback.work/'rec.bin',rec)
                    memu.CoalescedReadback.write_words(memu.CoalescedReadback.work/'arena.bin',initial)
                    outputs={};times={'baseline':[],'direct':[]}
                    for round_i in range(3):
                        for kind in (('baseline','direct') if round_i%2==0 else ('direct','baseline')):
                            out=memu.CoalescedReadback.work/f'{kind}.out'
                            proc=subprocess.run([str(runner),str(memu.CoalescedReadback.work/f'{kind}.spv'),
                                str(memu.CoalescedReadback.work/'rec.bin'),str(memu.CoalescedReadback.work/'arena.bin'),str(out),'2','2','1'],
                                env=dict(os.environ,MEMU_TEST_REPEATS='16'),capture_output=True,text=True)
                            self.assertEqual(proc.returncode,0,proc.stderr+proc.stdout)
                            outputs[kind]=out.read_bytes()
                            times[kind].append(json.loads(proc.stdout.splitlines()[-1])['gpu_ns_per_dispatch'])
                    self.assertEqual(outputs['baseline'],outputs['direct'],(width,coalesced,task,wt))
                    arena=struct.unpack(f'<{len(outputs["direct"])//4}I',outputs['direct'])
                    y=rec[25]+(layout.max_v if coalesced else 1)
                    expected=100.0 if task and wt>1 else 0.0
                    self.assertEqual(arena[y],struct.unpack('<I',struct.pack('<f',expected))[0])
                    print(f'payload={width} planes={coalesced} task={task} wt={wt}: direct/full '
                          f'{statistics.median(times["direct"])/statistics.median(times["baseline"]):.3f}; '
                          'complete arena exact (software Vulkan, not phone FPS)')
