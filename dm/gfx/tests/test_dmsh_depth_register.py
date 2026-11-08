#!/usr/bin/env python3
"""The register a pixel shader's depth output comes from (dmsh_xlate, arch sm86, stage ps): the colour outputs take four registers for each render target with any
component enabled in the SPH's OmapTargets (word 18), whatever its mask, and the depth (OmapDepth, word 19 bit 1) is the register after the next one: 4 x (enabled
targets) + 1. Ryujinx's GetDepthRegister counted components (PopCount(OmapTargets) + 1), which is that only when every enabled target writes all four: with 0x10f
(RT0 RGBA, RT2 R) gl_FragDepth read R6 instead of R9 (docs/reference/shaders.md#a-pixel-shader-with-partial-colour-masks-wrote-the-wrong-depth). Each program moves
i + 0.5 into Ri for every register the outputs can read, so the constant stored to gl_FragDepth names the register. Needs DMSH_TEST_XLATE (the translator) like the other
translator tests; SPIRV_VAL (default spirv-val on PATH) validates the modules when present."""
import json, os, shutil, struct, subprocess, tempfile, unittest
from pathlib import Path


def inst(hi, lo): return struct.pack('<QQ', lo, hi)


EXIT = inst(0x000fea0003800000, 0x000000000000794d)
def mov(rd, value): return inst(0x000fc60000000f00, value << 32 | rd << 16 | 0x7802)   # MOV Rd, imm32
def fbits(f): return struct.unpack('<I', struct.pack('<f', f))[0]


def sph(omap_targets, depth=True):
    """a pixel shader's 0x80-byte SPH: type 2, version 3, stage 5 (fragment), no inputs; word 18 the colour components written, word 19 bit 1 the depth"""
    w = [0] * 32
    w[0] = 2 | 3 << 5 | 5 << 10
    w[18] = omap_targets
    w[19] = 2 if depth else 0
    return struct.pack('<32I', *w)


REGS = 34   # R0..R33: the most eight targets and the depth read
def program(omap_targets): return sph(omap_targets) + b''.join(mov(r, fbits(r + 0.5)) for r in range(REGS)) + EXIT


OP_DECORATE, OP_CONSTANT, OP_VARIABLE, OP_LOAD, OP_STORE, OP_ACCESS_CHAIN, OP_COPY_OBJECT, OP_BITCAST, OP_EXECUTION_MODE = 71, 43, 59, 61, 62, 65, 83, 124, 16
DEC_BUILTIN, BUILTIN_FRAG_DEPTH, MODE_DEPTH_REPLACING = 11, 22, 12


def depth_values(spv):
    """→ the constants stored to the FragDepth variable (as floats), following loads of Function variables (each to its stores), copies and bitcasts; and the execution modes"""
    w = struct.unpack(f'<{len(spv) // 4}I', spv)
    insts, i = [], 5
    while i < len(w):
        n = w[i] >> 16
        insts.append((w[i] & 0xffff, list(w[i + 1:i + n])))
        i += max(1, n)
    depth = {a[0] for op, a in insts if op == OP_DECORATE and a[1:3] == [DEC_BUILTIN, BUILTIN_FRAG_DEPTH]}
    consts = {a[1]: a[2] for op, a in insts if op == OP_CONSTANT and len(a) == 3}
    defs = {a[1]: (op, a) for op, a in insts if op in (OP_LOAD, OP_COPY_OBJECT, OP_BITCAST, OP_ACCESS_CHAIN)}
    stores = {}
    for op, a in insts:
        if op == OP_STORE: stores.setdefault(a[0], []).append(a[1])

    def resolve(v, seen=()):
        if v in consts: return {consts[v]}
        if v in seen or v not in defs: return {None}
        op, a = defs[v]
        if op == OP_LOAD: return set().union(*(resolve(s, seen + (v,)) for s in stores.get(a[2], [None])))
        return resolve(a[2], seen + (v,))

    pointers = depth | {a[1] for op, a in insts if op == OP_ACCESS_CHAIN and a[2] in depth}
    found = set()
    for p in pointers:
        for s in stores.get(p, []): found |= resolve(s)
    modes = {a[1] for op, a in insts if op == OP_EXECUTION_MODE}
    return {None if b is None else struct.unpack('<f', struct.pack('<I', b))[0] for b in found}, modes


VAL = os.environ.get('SPIRV_VAL') or shutil.which('spirv-val')


@unittest.skipUnless(os.environ.get('DMSH_TEST_XLATE'), 'set DMSH_TEST_XLATE to the offline translator')
class DepthRegister(unittest.TestCase):
    def translate(self, omap_targets, **job):
        with tempfile.TemporaryDirectory(prefix='depth_register_') as d:
            work = Path(d); (work / 'k.bin').write_bytes(program(omap_targets))
            j = dict(key='k', stage='ps', arch='sm86', code=str(work / 'k.bin'), tex={}, img={}, attr={}, fout={str(t): 'float' for t in range(8)}, debug=False, reduced=True,
                     subgroup_size=64, ssbo_align=64, gs_passthrough=False)
            j.update(job)
            (work / 'jobs.json').write_text(json.dumps([j]))
            r = subprocess.run([os.environ['DMSH_TEST_XLATE'], str(work / 'jobs.json'), d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            if VAL:
                v = subprocess.run([VAL, '--target-env', 'vulkan1.3', str(work / 'k.spv')], capture_output=True, text=True)
                self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
            return depth_values((work / 'k.spv').read_bytes())

    # OmapTargets → the depth register: the masks Zelda: Ocarina of Time's pixel shaders that write depth use, and full ones (where the old count was right)
    CASES = [(0x10f, 9), (0x3f, 9), (0x100, 5), (0x30, 5), (0x1, 5), (0x0, 1), (0xf, 5), (0xff, 9), (0xf0f0, 9), (0x1111_1111, 33), (0xffff_ffff, 33)]

    def test_depth_after_whole_targets(self):
        for mask, reg in self.CASES:
            with self.subTest(omap_targets=hex(mask)):
                values, modes = self.translate(mask)
                self.assertEqual(values, {reg + 0.5}, f'gl_FragDepth should read R{reg}')
                self.assertIn(MODE_DEPTH_REPLACING, modes)

    def test_debug_translation(self):   # DebugMode (the libraries' setting) leaves the temporaries in; the stored value is still R9's
        values, _ = self.translate(0x10f, debug=True)
        self.assertEqual(values, {9.5})


if __name__ == '__main__':
    unittest.main()
