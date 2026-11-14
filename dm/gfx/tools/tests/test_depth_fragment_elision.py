"""Prove constant-colour-only SPIR-V and depth/query parity without an FS."""
import ctypes
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from dm.gfx.tools.tests.test_depth_pass_optimizations import function
from dm.tools.tests.test_cave_query_gpu import VERT, FRAG

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / 'dm/gfx/vk_android'
PURE = '#version 450\nlayout(location=0)out vec4 color;void main(){color=vec4(1);}'


class DepthFragmentElision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.tmp.name)
        subprocess.run([shutil.which('cc'), '-shared', '-fPIC', '-O2',
                        str(VK / 'vka_spvpatch.c'), '-o', str(cls.d / 'proof.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.d / 'proof.so'))
        cls.proof = cls.lib.vka_spv_constant_colour_only
        cls.proof.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t]
        cls.proof.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, stage='frag'):
        p = self.d / ('test.' + stage)
        p.write_text(source)
        out = str(p) + '.spv'
        subprocess.run([shutil.which('glslangValidator'), '-V', '--target-env', 'vulkan1.1',
                        '-S', stage, '-o', out, str(p)], check=True, capture_output=True)
        return Path(out).read_bytes()

    def check(self, data):
        self.assertEqual(len(data) % 4, 0)
        a = (ctypes.c_uint32 * (len(data) // 4)).from_buffer_copy(data)
        return self.proof(a, len(a))

    def test_constant_only_proof_rejects_semantic_changes_and_malformed_input(self):
        self.assertTrue(self.check(self.compile(PURE)))
        # Component stores and an unused support UBO match the captured game's
        # actual translated constant-white fragment module's instruction shape.
        component = '''#version 450
layout(set=0,binding=0)uniform Support{vec4 unused;}support_buffer;
layout(location=0)out vec4 c;
void main(){c.x=1;c.y=1;c.z=1;c.w=1;}'''
        pure = self.compile(component)
        self.assertTrue(self.check(pure))
        unsafe = [FRAG,
                  PURE.replace('color=vec4(1);', 'discard;'),
                  PURE.replace('color=vec4(1);', 'gl_FragDepth=0.5;color=vec4(1);'),
                  PURE.replace('color=vec4(1);', 'gl_SampleMask[0]=1;color=vec4(1);'),
                  PURE.replace('layout(location=0)out', 'layout(early_fragment_tests)in;layout(location=0)out'),
                  PURE.replace('void main()', 'layout(constant_id=0)const float x=1;void main()').replace('vec4(1)', 'vec4(x)'),
                  PURE.replace('void main()', 'layout(set=0,binding=0)buffer B{uint x;}b;void main()').replace('color=vec4(1);', 'atomicAdd(b.x,1);color=vec4(1);'),
                  PURE.replace('void main()', 'layout(set=0,binding=0)uniform sampler2D t;void main()').replace('vec4(1)', 'texture(t,vec2(0))')]
        for source in unsafe:
            with self.subTest(source=source):
                self.assertFalse(self.check(self.compile(source)))
        self.assertFalse(self.check(self.compile(VERT, 'vert')))
        # Every truncated prefix, invalid header/bound, zero or oversized
        # instruction length, and unknown body opcode falls back safely.
        for n in range(0, len(pure), 4):
            self.assertFalse(self.check(pure[:n]))
        words = list(struct.unpack('<' + 'I' * (len(pure)//4), pure))
        for ix, value in ((0, 0), (3, 0), (3, 1048577), (5, 0), (5, 0xffff0000)):
            changed = words.copy(); changed[ix] = value
            self.assertFalse(self.check(struct.pack('<' + 'I'*len(changed), *changed)))
        i = 5
        while i < len(words):
            n, op = words[i] >> 16, words[i] & 65535
            if op in (62, 65):
                changed = words.copy(); changed[i] = n << 16 | 65535
                self.assertFalse(self.check(struct.pack('<' + 'I'*len(changed), *changed)))
            i += n

    @unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN') == '1', 'real Vulkan ICD required')
    def test_gpu_depth_colour_and_precise_query_parity_without_fragment_stage(self):
        tex = (VK / 'vka_tex.c').read_text()
        (self.d / 'attachment_parts.inc').write_text(
            function(tex, 'void vka_attachment_write_barrier_at(') + '\n' +
            function(tex, 'void vka_attachment_parts_barrier_at('))
        env = dict(os.environ)
        for name, stage, source in [('CAVE_VERT', 'vert', VERT), ('CAVE_FRAG', 'frag', FRAG),
                                    ('CAVE_PURE_FRAG', 'frag', PURE)]:
            p = self.d / (name + '.spv'); p.write_bytes(self.compile(source, stage)); env[name] = str(p)
        exe = self.d / 'depth-no-fs'
        build = subprocess.run([shutil.which('cc'), '-O2', '-DVKA_NDSR_PURE', '-DVKA_DEPTH_NO_FS_TEST',
                                '-I', str(self.d), '-I', str(ROOT/'dm/third_party/vulkan-headers/include'),
                                '-I', str(VK), str(VK/'selftest/depth_pass_gpu.c'), str(VK/'vka_ndsr.c'),
                                '-ldl', '-lm', '-o', str(exe)], capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stderr)
        run = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('Validation Error', run.stdout + run.stderr)
        self.assertEqual(run.stdout.count('192 precise queries exact'), 14, run.stdout)
        print(run.stdout)


if __name__ == '__main__':
    unittest.main()
