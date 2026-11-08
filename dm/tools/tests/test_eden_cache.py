"""eden_cache.py on synthetic data: a yuzucach file (v53 with NEDENMAP sections, and v18), a small NVN2 shader package and a profile. No emulator cache or
game files: the cache, the package and the profile are built here. Checks the reader's counts (the geometry and mesh tails too), the matcher's exact / weak / same /
tie / none outcomes, the operand step that tells two candidates apart (and leaves out an instruction lowered to nothing), the slot a texture handle is placed at
(the image range and its img fact), the stage columns of a pipeline with VertexA and tessellation / geometry stages, and the output tables."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import eden_cache as ec

CTL_MAGIC = bytes.fromhex('34127698')
EXIT = struct.pack('<4I', 0x94d, 0, 0, 0)
BRA = struct.pack('<4I', 0x947, 0, 0, 0)


def ins(w0, w1=0): return struct.pack('<4I', w0, w1, 0, 0)


def ctl(wg=(0, 0, 0), tag=0):
    c = bytearray(0x100); c[:4] = CTL_MAGIC; c[4:8] = b'\xc9\0\0\0'; c[0x30:0x34] = b'\xd8\0\0\0'
    struct.pack_into('<3I', c, 0x58, *wg); struct.pack_into('<I', c, 0x80, tag)   # (+0x80 is past the key's 0x48 bytes)
    return bytes(c)


def key(c, code): return hashlib.sha256(c[:0x30] + bytes(4) + c[0x34:0x48] + code).hexdigest()[:16]


def sph(tag): return bytes([tag]) * 0x50 + bytes(0x30)   # a 0x80-byte SPH whose first 0x50 bytes are the signature


def record(c, code): return b'BTCDBTCD' + bytes(0x20) + struct.pack('<2I', len(c), len(code)) + bytes(8) + code + c


def lowered(head, words, nmap):
    """Eden's code: the head, lowered instruction words, a 0 word, then NEDENMAP (the byte offset of each native instruction's first lowered word)"""
    w = list(struct.unpack('<10Q', head.ljust(0x50, b'\0'))) + list(words) + [0]
    return struct.pack(f'<{len(w)}Q', *w) + struct.pack(f'<{len(nmap) + 2}Q', *nmap, len(nmap), ec.MAP_MAGIC)


def env(stage, code, tex=(), pix=(), cbuf=(), wg=None, smem=0, version=53):
    """An environment with its stage's tail: compute workgroup and shared memory, else the SPH, a geometry stage's 32-byte passthrough mask, v53 task / mesh registers and
    header (non-zero here, as Zelda's cache has them)"""
    counts = [len(code), len(tex), len(pix), len(cbuf)] + ([0] if version == 53 else []) + [0]
    b = struct.pack(f'<{len(counts)}Q', *counts) + struct.pack('<7I', 0, 2, 0, 0, 0, 0, stage) + code
    b += b''.join(struct.pack('<II', *t) for t in tex) + b''.join(struct.pack('<II', *t) for t in pix) + b''.join(struct.pack('<QI', *t) for t in cbuf)
    if stage == 5: assert wg is not None, 'a compute environment takes its workgroup'; return b + struct.pack('<4I', *wg, smem)
    b += bytes(0x50)
    if stage == 3: b += b'\xff' * 32
    if stage in (7, 8) and version == 53: b += struct.pack('<3I', 32, 1, 1) + b'\x07' * 0x50
    return b


def entry(*envs, k=None): return struct.pack('<I', len(envs)) + b''.join(envs) + (k if k is not None else gfx_key())


def write_profile(root, keys, pairs=(), facts=()):
    prof = Path(root) / 'prof' / '0400000000000000'; prof.mkdir(parents=True)
    (prof / 'game.tsv').write_text('title_id\t0400000000000000\n')
    rows = [f'{n[:2]}_shader.bin\t{i}\t{ec.STAGE_NAME[n[:2]]}\t{k}\tsynthetic' for i, (n, k) in enumerate(keys.items())]
    (prof / 'shader_map.tsv').write_text('# synthetic\npackage\tindex\tstage\tdm_ctl_sha16\tsource\n' + '\n'.join(rows) + '\n')
    (prof / 'shader_pairs.tsv').write_text('# synthetic\n' + ''.join(f'{v}\t{p}\n' for v, p in pairs))
    (prof / 'shader_facts.tsv').write_text('# synthetic\n' + ''.join(f'{k}\t{f}\n' for k, f in facts))
    return str(prof)


def gfx_key(topology=4):
    k = bytearray(ec.GFX_KEY); struct.pack_into('<I', k, 48, 0x01 | 0x02 | (topology << 24)); k[56] = 0xd5; struct.pack_into('<II', k, 64, 4, 0x98960000)
    struct.pack_into('<I', k, 128, 1 << 30); return bytes(k)


class Fixture:
    """A package with: one vertex program, two pixel programs that differ in one immediate (told apart by the lowered code), two pixel programs equal over the
    captured range (they differ after the closing branch), one compute program; and a cache whose pipelines use them, plus a mesh program the package does not have"""
    def __init__(self, root):
        self.root = Path(root); pkg = self.root / 'pkg'; pkg.mkdir()
        self.vs_code = sph(1) + ins(0x424, 7) + EXIT + BRA
        self.ps_a = sph(2) + ins(0x424, 0x1234) + ins(0x0) + EXIT + BRA
        self.ps_b = sph(2) + ins(0x424, 0x5678) + ins(0x0) + EXIT + BRA
        self.ps_c = sph(3) + EXIT + BRA + ins(0x1)
        self.ps_d = sph(3) + EXIT + BRA + ins(0x2)
        self.cs_code = ins(0x424, 9) + EXIT + BRA
        c0 = ctl(); ccs = ctl((64, 1, 1))
        self.k = {n: key(c0, code) for n, code in (('vs', self.vs_code), ('ps_a', self.ps_a), ('ps_b', self.ps_b), ('ps_c', self.ps_c), ('ps_d', self.ps_d))}
        self.k['cs'] = key(ccs, self.cs_code)
        (pkg / 'vs_shader.bin').write_bytes(record(c0, self.vs_code))
        (pkg / 'ps_shader.bin').write_bytes(record(c0, self.ps_a) + record(c0, self.ps_b) + record(c0, self.ps_c) + record(c0, self.ps_d))
        (pkg / 'cs_shader.bin').write_bytes(record(ccs, self.cs_code))
        self.pkg = str(pkg)
        self.profile = write_profile(self.root, self.k, pairs=[(self.k['vs'], self.k['ps_b'])], facts=[(self.k['cs'], '{"local":[64,1,1],"shared":16}')])
        h = 0x1020037a
        vs = env(0, lowered(self.vs_code[:0x50], [7 << 20, 0], [80, 88]))
        ps = env(4, lowered(self.ps_a[:0x50], [0x1234 << 20, 0, 0], [80, 88, 96]), tex=[(h, 3)], pix=[(h, 0)], cbuf=[((2 << 32) | 0x28, h)])
        ps2 = env(4, lowered(self.ps_c[:0x50], [0], [80]))
        cs = env(5, lowered(bytes(0x50), [9 << 20, 0], [80, 88]), wg=(64, 1, 1), smem=256)   # the launch's allocation: 16 bytes declared, rounded up to 256
        ms = env(8, lowered(bytes([9]) * 0x50, [0], [80]))
        entries = [entry(vs, ps), entry(vs, ps, k=gfx_key(0)), entry(vs, ps2), entry(cs, k=struct.pack('<QI3I', 1, 256, 64, 1, 1)), entry(ms, ps)]
        self.cache = str(self.root / 'vulkan.fork-v53.bin')
        Path(self.cache).write_bytes(ec.MAGIC + struct.pack('<I', 53) + b''.join(entries))


class Fixture2:
    """The other stages and outcomes: a VertexA + VertexB pipeline, tessellation and geometry pipelines (the geometry stage's 32-byte tail), a tie, an instruction lowered
    to nothing, a single candidate whose operands do not agree (weak) and one whose do, a compute program launched with another workgroup (no candidate), an image slot"""
    def __init__(self, root):
        self.root = Path(root); pkg = self.root / 'pkg'; pkg.mkdir()
        c0, ccs = ctl(), ctl((64, 1, 1))
        four = b''.join(ins(0x424, 0x100 + j) for j in range(4))
        code = {'vs_b': sph(0x11) + ins(0x424, 7) + EXIT + BRA, 'vs_a': sph(0x12) + ins(0x424, 8) + EXIT + BRA, 'ps_x': sph(0x13) + ins(0x424, 5) + EXIT + BRA,
                'hs': sph(0x14) + EXIT + BRA, 'ds': sph(0x15) + EXIT + BRA, 'gs': sph(0x16) + EXIT + BRA,
                'ps_t1': sph(0x17) + ins(0x424, 0x1111) + EXIT + BRA, 'ps_t2': sph(0x17) + ins(0x424, 0x2222) + EXIT + BRA,
                'ps_e1': sph(0x18) + ins(0x424, 0xaaaa) + ins(0x424, 0xbbbb) + EXIT + BRA, 'ps_e2': sph(0x18) + ins(0x424, 0xbbbb) + ins(0x424, 0xbbbb) + EXIT + BRA,
                'ps_w': sph(0x19) + four + EXIT + BRA, 'ps_g': sph(0x1a) + four + EXIT + BRA, 'cs': ins(0x424, 9) + EXIT + BRA}
        self.code = code
        self.k = {n: key(ccs if n == 'cs' else c0, c) for n, c in code.items()}
        files = {}
        for n, c in code.items(): files.setdefault(n[:2], b''); files[n[:2]] += record(ccs if n == 'cs' else c0, c)
        for st, b in files.items(): (pkg / f'{st}_shader.bin').write_bytes(b)
        self.pkg = str(pkg)
        self.profile = write_profile(self.root, self.k, facts=[(self.k['cs'], '{"local":[64,1,1],"shared":0}')])
        h, hi = 0x2030, 0x4050
        r32f = ec.PIXFMT.index('R32_FLOAT')
        vb = env(0, lowered(code['vs_b'][:0x50], [7 << 20, 0], [80, 88]))
        va = env(6, lowered(code['vs_a'][:0x50], [8 << 20, 0], [80, 88]))
        ps = env(4, lowered(code['ps_x'][:0x50], [5 << 20, 0], [80, 88]), tex=[(h, 2), (hi, 2)], pix=[(h, 0), (hi, r32f)],
                 cbuf=[((2 << 32) | 0x20, h), ((2 << 32) | ec.IMG_BASE, hi)])   # slot 0, and slot 32: image 0
        hs, ds = env(1, lowered(code['hs'][:0x50], [0], [80])), env(2, lowered(code['ds'][:0x50], [0], [80]))
        gs = env(3, lowered(code['gs'][:0x50], [0], [80]))
        pt = env(4, lowered(code['ps_t1'][:0x50], [0x3333 << 20, 0], [80, 88]))   # neither 0x1111 nor 0x2222 in the lowered word
        # ps_e: instruction 0 lowered to nothing (the map's first two offsets are equal); instruction 1's word carries 0xbbbb, which only ps_e2's instruction 0 has
        pe = env(4, lowered(code['ps_e1'][:0x50], [0xbbbb << 20, 0], [80, 80, 88]))
        pw = env(4, lowered(code['ps_w'][:0x50], [(0x900 + j) << 20 for j in range(4)] + [0], [80, 88, 96, 104, 112]))   # other immediates: weak
        pg = env(4, lowered(code['ps_g'][:0x50], [(0x100 + j) << 20 for j in range(4)] + [0], [80, 88, 96, 104, 112]))
        cs64 = env(5, lowered(bytes(0x50), [9 << 20, 0], [80, 88]), wg=(64, 1, 1), smem=0)
        cs32 = env(5, lowered(bytes(0x50), [9 << 20, 0, 0], [80, 88]), wg=(32, 1, 1), smem=0)   # (other lowered code: its own program)
        entries = [entry(va, vb, ps), entry(vb, hs, ds, ps), entry(vb, gs, ps), entry(vb, pt), entry(vb, pe), entry(vb, pw), entry(vb, pg),
                   entry(cs64, k=struct.pack('<QI3I', 1, 0, 64, 1, 1)), entry(cs32, k=struct.pack('<QI3I', 2, 0, 32, 1, 1))]
        self.cache = str(self.root / 'vulkan.fork-v53.bin')
        Path(self.cache).write_bytes(ec.MAGIC + struct.pack('<I', 53) + b''.join(entries))


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out): rc = ec.main(list(argv))
    return rc, out.getvalue()


def rows(path): return [ln.split('\t') for ln in Path(path).read_text().splitlines() if ln and not ln.startswith('#')]


def matched(f):
    skey, nvn2 = ec.borrow_key((0, 0))
    pkg = ec.Package(f.pkg, skey, nvn2)
    cache = ec.Cache(f.cache)
    try: return cache, pkg, ec.match(cache, pkg), set(pkg.rec)
    finally: pkg.close()


class EdenCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.f = Fixture(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def test_info_counts(self):
        rc, out = run('info', self.f.cache)
        self.assertEqual(rc, 0)
        self.assertIn('version 53, 5 entries (4 graphics, 1 compute), 3 distinct keys', out)
        self.assertIn('distinct programs: 5', out)
        self.assertIn('0 without a NEDENMAP', out)
        self.assertIn('3 texture types (2darray 3)', out)

    def test_match(self):
        cache, _pkg, m, keys = matched(self.f)
        self.assertEqual(keys, set(self.f.k.values()))   # the borrowed key is the key shader_split.py makes
        got = {cache.order[i].stage + ('' if ks else '?'): (ks, how) for i, (ks, how) in m.items() if how != 'same'}
        self.assertEqual(got['vs'], ((self.f.k['vs'],), 'exact'))
        self.assertEqual(got['cs'], ((self.f.k['cs'],), 'exact'))
        self.assertEqual(got['ms?'], ((), 'none'))
        self.assertEqual(got['ps'], ((self.f.k['ps_a'],), 'exact'))   # the immediate 0x1234 is in the lowered word, 0x5678 is not
        same = [ks for ks, how in m.values() if how == 'same']
        self.assertEqual(same, [tuple(sorted((self.f.k['ps_c'], self.f.k['ps_d'])))])

    def test_all_outputs(self):
        out = os.path.join(self.tmp.name, 'out')
        rc, text = run('all', self.f.cache, '--game', self.f.profile, '--pkg', self.f.pkg, '--out', out)
        self.assertEqual(rc, 0)
        k = self.f.k
        keys = {r[0]: r for r in rows(os.path.join(out, 'keys.tsv')) if r[0] != 'key'}
        self.assertEqual(set(keys), {k['vs'], k['ps_a'], k['ps_c'], k['ps_d'], k['cs']})
        self.assertEqual(keys[k['vs']][1:], ['vertex', '3', 'exact'])
        self.assertEqual(keys[k['ps_a']][1:], ['pixel', '3', 'exact'])
        self.assertEqual(keys[k['ps_c']][3], 'candidate')
        self.assertEqual(rows(os.path.join(out, 'pairs.tsv')), [[k['vs'], k['ps_a']]])
        facts = {r[0]: json.loads(r[1]) for r in rows(os.path.join(out, 'facts.tsv'))}
        self.assertEqual(facts[k['ps_a']], {'tex': {'1': '2darray'}})   # c2 + 0x28: slot 1
        self.assertEqual(facts[k['cs']], {'local': [64, 1, 1]})   # no shared: the cache has the launch's allocation only
        det = [r for r in rows(os.path.join(out, 'facts_detail.tsv')) if r[0] in (k['ps_a'], k['cs'])]
        self.assertEqual(det, sorted([[k['ps_a'], 'pixel', '1', '2darray', 'A8B8G8R8_UNORM', 'float', '3'],
                                      [k['cs'], 'compute', 'launch', 'local=64,1,1', 'shared_alloc=256', '-', '1']]))
        pipes = rows(os.path.join(out, 'pipelines.tsv'))
        self.assertEqual(pipes[0], ['kind', 'va', 'vb', 'hs', 'ds', 'gs', 'ts', 'ms', 'ps', 'cs', 'state', 'entries'])
        self.assertIn(['graphics', '-', k['vs'], '-', '-', '-', '-', '-', k['ps_a'], '-', '4 0 -1 d500000000000000 1', '1'], pipes)
        self.assertIn(['graphics', '-', '-', '-', '-', '-', '-', '?', k['ps_a'], '-', '4 0 -1 d500000000000000 1', '1'], pipes)
        self.assertIn(['compute', '-', '-', '-', '-', '-', '-', '-', '-', k['cs'], 'shared_alloc 256 local 64 1 1', '1'], pipes)
        self.assertIn('pairs: 1 vertex / pixel pairs, 1 not in the profile', text)
        self.assertIn('local differs in 0; shared_alloc is the profile\'s shared rounded up to 256 in 1 of 1 launches', text)
        self.assertIn('the profile has texture types for 0 of them (0 slots compared, 0 differ)', text)
        self.assertIn('same: 0 of 1 have candidates with byte-identical code areas', text)   # ps_c / ps_d differ after the closing branch
        self.assertIn('5 of the 5 keys are in its shader_map.tsv (6 keys)', text)

    def test_exact_keys(self):
        o = os.path.join(self.tmp.name, 'keys.tsv')
        run('keys', self.f.cache, '--game', self.f.profile, '--pkg', self.f.pkg, '-o', o, '--exact')
        self.assertEqual({r[3] for r in rows(o) if r[0] != 'key'}, {'exact'})

    def test_v18(self):
        code = struct.pack('<12Q', *range(12))   # Eden's own cache for a Maxwell game: no NEDENMAP
        p = os.path.join(self.tmp.name, 'vulkan.bin')
        Path(p).write_bytes(ec.MAGIC + struct.pack('<I', 18) + struct.pack('<I', 2) + env(0, code, version=18) + env(4, code, version=18) + gfx_key())
        rc, out = run('info', p)
        self.assertIn('version 18, 1 entries', out)
        self.assertIn('2 without a NEDENMAP', out)

    def test_cut_file(self):
        d = Path(self.f.cache).read_bytes()
        Path(self.f.cache).write_bytes(d[:-100])
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stdout(io.StringIO()): ec.main(['info', self.f.cache])
        self.assertIn('[RED]', str(e.exception))
        Path(self.f.cache).write_bytes(b'notacache' + d[9:])
        with self.assertRaises(SystemExit) as e: ec.main(['info', self.f.cache])
        self.assertIn('yuzucach', str(e.exception))


class EdenCacheStagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.f = Fixture2(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def test_info_tails(self):
        rc, out = run('info', self.f.cache)   # the geometry stage's 32 bytes are read past: every entry after it is read
        self.assertEqual(rc, 0)
        self.assertIn('9 entries (7 graphics, 2 compute)', out)
        self.assertIn('va+vb+ps 1', out); self.assertIn('vb+hs+ds+ps 1', out); self.assertIn('vb+gs+ps 1', out)

    def test_outcomes(self):
        cache, _pkg, m, keys = matched(self.f)
        self.assertEqual(keys, set(self.f.k.values()))
        name = {v: n for n, v in self.f.k.items()}
        got = {tuple(sorted(name[k] for k in ks)): how for ks, how in m.values() if ks}
        self.assertEqual(got[('ps_t1', 'ps_t2')], 'tie')   # neither immediate is in the lowered word
        self.assertEqual(got[('ps_e1', 'ps_e2')], 'tie')   # instruction 0 is lowered to nothing: left out, not read from instruction 1's word (which would pick ps_e2)
        self.assertEqual(got[('ps_w',)], 'weak')   # one candidate, 1 of its 5 operand instructions agrees (the EXIT)
        self.assertEqual(got[('ps_g',)], 'exact')
        for n in ('vs_a', 'vs_b', 'ps_x', 'hs', 'ds', 'gs', 'cs'): self.assertEqual(got[(n,)], 'exact', n)
        nones = [cache.order[i] for i, (ks, how) in m.items() if how == 'none']
        self.assertEqual([(p.stage, p.wg) for p in nones], [('cs', (32, 1, 1))])   # the package's compute record has workgroup 64

    def test_outputs(self):
        out = os.path.join(self.tmp.name, 'out')
        rc, text = run('all', self.f.cache, '--game', self.f.profile, '--pkg', self.f.pkg, '--out', out)
        self.assertEqual(rc, 0)
        k = self.f.k
        st = '4 0 -1 d500000000000000 1'
        pipes = rows(os.path.join(out, 'pipelines.tsv'))
        self.assertIn(['graphics', k['vs_a'], k['vs_b'], '-', '-', '-', '-', '-', k['ps_x'], '-', st, '1'], pipes)   # VertexA and VertexB apart
        self.assertIn(['graphics', '-', k['vs_b'], k['hs'], k['ds'], '-', '-', '-', k['ps_x'], '-', st, '1'], pipes)
        self.assertIn(['graphics', '-', k['vs_b'], '-', '-', k['gs'], '-', '-', k['ps_x'], '-', st, '1'], pipes)
        self.assertIn(['graphics', '-', k['vs_b'], '-', '-', '-', '-', '-', '?', '-', st, '1'], pipes)   # the weak pixel shader is not exact
        # Pairs: VertexB with the pixel shader, not through a tessellation or geometry stage, every stage exact
        self.assertEqual(sorted(rows(os.path.join(out, 'pairs.tsv'))), sorted([[k['vs_b'], k['ps_x']], [k['vs_b'], k['ps_g']]]))
        self.assertIn('with a tessellation or geometry stage (no pair) 2', text)
        self.assertIn('with a VertexA (paired by their VertexB) 1', text)
        self.assertIn('pipeline stages (entries): va 1, vb 7, hs 1, ds 1, gs 1, ps 7, cs 2', text)
        self.assertIn('ps: 5 programs: exact 2, weak 1, tie 2', text)
        facts = {r[0]: json.loads(r[1]) for r in rows(os.path.join(out, 'facts.tsv'))}
        self.assertEqual(facts[k['ps_x']], {'tex': {'0': '2d', '32': '2d'}, 'img': {'0': {'fmt': 'R32Float', 'type': '2d'}}})
        self.assertNotIn(k['ps_w'], facts)
        keys = {r[0]: r[3] for r in rows(os.path.join(out, 'keys.tsv')) if r[0] != 'key'}
        self.assertEqual(keys[k['ps_w']], 'candidate')


if __name__ == '__main__':
    unittest.main()
