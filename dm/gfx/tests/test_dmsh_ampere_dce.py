#!/usr/bin/env python3
"""Dead-code removal around an instruction with several results (dmsh_xlate, arch sm86): a producer one of whose results is still read keeps its sources. Ryujinx's
Optimizer.RemoveNode followed a producer as soon as one of its results lost its last use, so the producer stayed in the block while its sources lost their uses, and the next
pass deleted the instructions that feed it (docs/reference/shaders.md#dead-code-removal-dropped-the-inputs-of-a-producer-with-several-results). Zelda: Ocarina of Time's
NDVE / NDSR compute shaders lost 45 of 46 HMMAs with their LDSM and MOVM loads this way (4f41ccf24f163e0d: its last HMMA writes R16 and R17, and R17 is never read); Mario
Kart World's DrivePassShaderDefault lost the coordinate of an image load whose second component is not read. The encodings are the games' with clean control bits (no
scoreboard waits or barriers). Needs DMSH_TEST_XLATE (the translator) like the other translator tests; the checks read the SPIR-V itself, no other tool."""
import json, os, struct, subprocess, tempfile, unittest
from pathlib import Path


def inst(hi, lo): return struct.pack('<QQ', lo, hi)


EXIT = inst(0x000fea0003800000, 0x000000000000794d)
S2R_TID_X = lambda rd: inst(0x000fe20000002100, rd << 16 | 0x7919)   # S2R Rd, SR_TID.X


def mov(rd, value): return inst(0x000fc60000000f00, value << 32 | rd << 16 | 0x7802)   # MOV Rd, imm32
def mov_r(rd, rb): return inst(0x000fe20000000f00, rb << 32 | rd << 16 | 0x7202)   # MOV Rd, Rb
def lds(rd, offset): return inst(0x000fe20000000800, offset << 40 | 0xff << 24 | rd << 16 | 0x7984)   # LDS.U32 Rd, [RZ + offset]
def sts(offset, rb): return inst(0x000fe80000000800, offset << 40 | rb << 32 | 0xff << 24 | 0x7388)   # STS.U32 [RZ + offset], Rb
def movm(rd, ra): return inst(0x000fe20000000000, ra << 24 | rd << 16 | 0x723a)   # MOVM.16.MT88 Rd, Ra (4f41ccf24f163e0d +0xad0)


LDSM_4 = lambda rd, ra: inst(0x000fe20000000200, ra << 24 | rd << 16 | 0x783b)   # LDSM.16.M88.4 Rd, [Ra] (4f41ccf24f163e0d +0xac0): Rd..Rd+3
HMMA = inst(0x000fe20000000810, 0x000000181c10723c)   # HMMA.16816.F16 R16, R28, R24, R16 (4f41ccf24f163e0d +0x15b0): writes R16 and R17
# SULD.P.3D.RG R8, [R2] on the image whose handle is word 12 of c0 (image slot 1): writes R8 and R9. 3D, as a 2D image's coordinates go through the resolution scale helper, a call,
# which keeps them (calls have side effects)
SULD_3D_RG = inst(0x000fe20000000300, 0xa0000c0002087b97)

# SPIR-V opcodes and storage classes the checks read
OP_NAME, OP_FUNCTION, OP_FUNCTION_END, OP_FUNCTION_CALL, OP_VARIABLE, OP_LOAD, OP_STORE = 5, 54, 56, 57, 59, 61, 62
OP_ACCESS_CHAINS = (65, 66, 67, 70)   # OpAccessChain, OpInBoundsAccessChain, OpPtrAccessChain, OpInBoundsPtrAccessChain
WORKGROUP, FUNCTION = 4, 7


def module(spv):
    """{'unstored': Function variables loaded and never stored (no initializer, never passed to a call or indexed), 'calls': {callee name: count},
    'workgroup_loads': loads through a Workgroup variable in each function, by function name}"""
    w = struct.unpack(f'<{len(spv) // 4}I', spv)
    names, fvars, init, stored, loaded, wg, chains = {}, set(), set(), set(), set(), set(), {}
    calls, wgl, fn = {}, {}, None
    calls_raw = []
    i = 5
    while i < len(w):
        n, op = w[i] >> 16, w[i] & 0xffff
        a = w[i + 1:i + n]
        if op == OP_NAME: names[a[0]] = bytes(b for x in a[1:] for b in struct.pack('<I', x)).split(b'\0')[0].decode()
        elif op == OP_FUNCTION: fn = a[1]
        elif op == OP_FUNCTION_END: fn = None
        elif op == OP_VARIABLE:
            if a[2] == FUNCTION:
                fvars.add(a[1])
                if len(a) > 3: init.add(a[1])
            elif a[2] == WORKGROUP: wg.add(a[1])
        elif op in OP_ACCESS_CHAINS:
            chains[a[1]] = a[2]; stored.add(a[2])
        elif op == OP_LOAD:
            loaded.add(a[2])
            base = chains.get(a[2], a[2])
            if base in wg: wgl[fn] = wgl.get(fn, 0) + 1
        elif op == OP_STORE: stored.add(a[0])
        elif op == OP_FUNCTION_CALL:
            calls_raw.append(a[2]); stored.update(a[3:])
        i += n
    for c in calls_raw: calls[names.get(c, c)] = calls.get(names.get(c, c), 0) + 1
    return dict(unstored=sorted(v for v in fvars & loaded if v not in stored and v not in init), calls=calls,
                workgroup_loads={names.get(f, f): k for f, k in wgl.items()})


@unittest.skipUnless(os.environ.get('DMSH_TEST_XLATE'), 'set DMSH_TEST_XLATE to the offline translator')
class SeveralResults(unittest.TestCase):
    def translate(self, code):
        with tempfile.TemporaryDirectory(prefix='ampere_dce_') as d:
            work = Path(d); (work / 'k.bin').write_bytes(code + EXIT)
            # c0 layout (QueryAmpereComputeC0Layout): no uniform or storage buffers, 3 texture handles from 0x10, image handles from 0x28 (word 12 = image slot 1), 0x40 bytes
            job = [dict(key='k', stage='cs', arch='sm86', code=str(work / 'k.bin'), tex={}, img={}, attr={}, fout={}, local=[32, 1, 1], debug=True, nvn2_cs=[0, 0, 3, 0x40, 0],
                        shared=0x400)]
            (work / 'jobs.json').write_text(json.dumps(job))
            r = subprocess.run([os.environ['DMSH_TEST_XLATE'], str(work / 'jobs.json'), d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((work / 'k.spv').exists(), r.stdout + r.stderr)
            return module((work / 'k.spv').read_bytes())

    def hmma_shader(self):
        # A through MOVM from four LDS words, B from LDSM (R24, R25 of R24..R27), C from two LDS words; the HMMA's R17 is never read, only R16 is stored
        return self.translate(mov(34, 0x40) + LDSM_4(24, 34) + b''.join(lds(12 + i, 0x100 + 4 * i) for i in range(4)) +
                              movm(28, 12) + movm(30, 13) + movm(29, 14) + movm(31, 15) + lds(16, 0x200) + lds(17, 0x204) + HMMA + sts(0x300, 16))

    def test_hmma_keeps_its_operands(self):
        m = self.hmma_shader()
        self.assertEqual(m['unstored'], [], m)   # with the old rule its 10 operands were Function variables nothing stored (the phone: random values, or NaN)
        self.assertEqual(sum(v for k, v in m['calls'].items() if 'hmma' in str(k)), 1, m)

    def test_hmma_producers_kept(self):   # the six LDS words and LDSM's two matrices that are read (R24, R25); the old rule kept none of them
        m = self.hmma_shader()
        main = sum(v for k, v in m['workgroup_loads'].items() if 'hmma' not in str(k))
        self.assertEqual(main, 6 + 2, m)

    def test_image_load_keeps_its_coordinate(self):
        # R2 = thread x, R3 = R4 = 0: SULD.P.3D.RG R8, [R2]; R9 only feeds a MOV whose result is never read, R8 is stored. Removing the MOV took R9's last use, and the old rule
        # then dropped the load's sources: the coordinate's S2R was deleted and the load read a variable nothing stored
        m = self.translate(S2R_TID_X(2) + mov(3, 0) + mov(4, 0) + SULD_3D_RG + mov_r(6, 9) + sts(0x20, 8))
        self.assertEqual(m['unstored'], [], m)


if __name__ == '__main__':
    unittest.main()
