#!/usr/bin/env python3
# A pipeline cache written by a Switch 2 emulator derived from Eden / yuzu (the "yuzucach" file: Lichii's vulkan.fork-v53.bin, Eden NX2's vulkan.bin), read as data: which of
# a profile's shader keys its recorded pipelines used, which stages they drew together, and what the emulator learnt about each shader while drawing (the texture type and pixel
# format behind each binding, a compute program's workgroup and shared memory). Such caches are user-provided local data (players share them): nothing of them goes into the
# repository, only tables of our own keys made from them (android/SHADERS.md, Pipeline caches of other emulators).
#
# File format (little-endian; Lichii nx2 src/video_core/renderer_vulkan/vk_pipeline_cache.cpp SerializePipeline, src/video_core/shader_environment.cpp FileEnvironment::Serialize):
#   "yuzucach", u32 version (53: the Lichii fork; 18: Eden NX2's own); then entries to the end of the file, with no count and no index
#   Entry: u32 environment count, the environments, then the raw pipeline key. Compute (the first environment's stage is 5): ComputePipelineCacheKey, 24 bytes (u64 unique hash,
#     u32 shared memory, u32[3] workgroup). Graphics: GraphicsPipelineCacheKey, 1,056 bytes (u64 unique hash x 6 by Maxwell program slot, then the 1,008-byte FixedPipelineState:
#     +48 raw1 (topology bits 24..27, msaa 28..31), +52 raw2 (depth enabled bit 5, depth format bits 6..10), +56 colour formats u8 x 8, +64 driver id, +68 driver version,
#     +120 dynamic state, +128 blending attachments u32 x 8 (enable bit 30), +160 vertex attributes ...)
#   Environment: u64 counts of code bytes, texture types, pixel formats, cbuf values, storage pointers (v53 only), cbuf replacements; u32 local memory, texture bound buffer,
#     start address, cached lowest, cached highest, viewport transform state, stage (0 VertexB 1 TessCtl 2 TessEval 3 Geometry 4 Fragment 5 Compute 6 VertexA 7 Task 8 Mesh);
#     the code; the tables {u32 handle, u32 TextureType}, {u32 handle, u32 TexturePixelFormat}, {u64 bank << 32 | offset, u32 value} (bit 63 set: a pointer-table entry),
#     {u64 key, u8 is pointer} (v53), {u64 key, u32 replacement}; then for compute u32[3] workgroup and u32 shared memory (the launch's allocation, rounded up to 256 bytes:
#     not the program's declared value), for the others the 0x50-byte SPH, a geometry stage u32[8] passthrough mask after it, task and mesh (v53) u32[3] mesh registers and
#     a 0x50-byte mesh primitive header (read past, not used: on Zelda's cache the task and mesh environments' registers are set, the header is non-zero in 10 of 2,765 mesh ones)
#   A handle is the texture handle the shader read from its constant buffer, and the tables do not say where it read it. The binding is placed by a heuristic: the places in
#     the cbuf value table that hold the same value (c2's handle table first, 0x20 + 8 slot, numbered as the translator numbers its answer table's slots, dmsh_xlate/Program.cs
#     Slot), so another constant that happens to equal a handle can add a wrong place
#   Code: an NX2 environment holds Eden's lowering of the Ampere program to Maxwell, not the game's code, as u64 words: the first 0x50 bytes of the game's 0x80-byte SPH (zeros
#     for compute), the lowered instructions (a 0 scheduling word at every 32-byte boundary), one 0 word, then the NEDENMAP section: one u64 per native instruction i, the byte
#     offset of i's first lowered instruction, then u64 N, then u64 0x50414d4e4544454e ("NEDENMAP"). N stops at the EXIT before the program's closing self-branch, with or
#     without that branch
# Matching to our keys: the native code is not in the cache, so its hash is not either. A program's candidates are the package records of its stage with the same signature (graphics:
#   the first 0x50 bytes of the code area, its SPH; compute: the workgroup at control +0x58) whose EXIT + self-branch ends at N or N - 1. Several candidates are told apart at the
#   native instructions where they differ: the one whose 32-bit immediate (forms 2 / 4) or constant buffer operand (forms 3 / 5) is in that instruction's lowered instructions (the
#   NEDENMAP gives their range; an instruction lowered to nothing, an empty range, is left out) wins. The one candidate or the winner is then checked over its own operand
#   instructions (those with such an operand and a lowered range): with at least AGREE_MIN of them, at least AGREE_FRAC must have their operand in their lowered range.
#   "exact": one candidate or one winner that passes; "weak": one that does not (the package's record has the program's shape, not its operands: most likely a program the
#   package does not hold); "same": candidates whose native instructions are equal over the N the cache saw: on Zelda's cache almost all (421 of 424) are records with
#   byte-identical code areas that differ only in the control section's first 0x48 bytes (the part the key hashes), the other 3 differ after instruction N; "tie": they differ
#   only in operands this does not compare (registers, predicates, offsets); "none": no candidate (a program the package does not hold, or one without a NEDENMAP)
# Usage: eden_cache.py info <cache>                                      the counts of the file
#        eden_cache.py keys|pairs|facts <cache> --game <id> --pkg <shader package dir> -o <file> [--exact]
#        eden_cache.py all <cache> --game <id> --pkg <shader package dir> --out <dir> [--exact]
#   keys: shader_seen.tsv's rows (key, stage; then the pipelines that used it and how it matched): candidates of "weak", "same" and "tie" programs too, unless --exact
#   pairs: the VertexB / pixel pairs of the graphics pipelines with no tessellation or geometry stage whose stages all matched exactly, in pso_pairs.tsv's two columns (a
#     pipeline with a VertexA too still pairs its VertexB; the summary counts them)
#   facts: shader_facts.tsv's rows (texture types by slot, image formats, compute local size) for exactly matched programs; not the shared memory, which the cache has only as
#     the launch's allocation (facts_detail.tsv's "launch" rows, shared_alloc); facts_detail.tsv (with "all") lists every binding seen
#   all: keys.tsv, pairs.tsv, pipelines.tsv (each distinct pipeline: its key for each stage, va vb hs ds gs ts ms ps cs, a summary of its state, how often it was recorded),
#     facts.tsv, facts_detail.tsv, summary.txt
#   The package is the shader_split.py output the profile's shader_map.tsv was made from (<id>_build/shader/pkg); the summary compares with the profile's tables
import argparse, ast, collections, hashlib, json, mmap, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPLIT = os.path.join(HERE, '../gfx/tools/shader_split.py')
MAGIC, MAP_MAGIC = b'yuzucach', 0x50414d4e4544454e
VERSIONS = {53: (6, True), 18: (5, False)}   # version → (u64 table counts, task / mesh tail): the fork added the storage pointer table and the mesh environments
GFX_KEY, CS_KEY = 1056, 24
STAGE = {0: 'vs', 1: 'hs', 2: 'ds', 3: 'gs', 4: 'ps', 5: 'cs', 6: 'vs', 7: 'ts', 8: 'ms'}   # Shader::Stage → our package's stage (VertexA is a vertex program)
SLOT = {0: 'vb', 1: 'hs', 2: 'ds', 3: 'gs', 4: 'ps', 5: 'cs', 6: 'va', 7: 'ts', 8: 'ms'}    # Shader::Stage → the pipeline's stage column (VertexA and VertexB apart)
COLS = ('va', 'vb', 'hs', 'ds', 'gs', 'ts', 'ms', 'ps', 'cs')                               # pipelines.tsv's stage columns, in pipeline order
AGREE_MIN, AGREE_FRAC = 4, 0.5   # a match's operand check: from 4 operand instructions on, at least half of them must agree with their lowered range
STAGE_NAME = {'vs': 'vertex', 'hs': 'hull', 'ds': 'domain', 'gs': 'geometry', 'ps': 'pixel', 'cs': 'compute', 'ts': 'task', 'ms': 'mesh'}   # shader_map.tsv column 3
TEX_TYPE = ['1d', '1darray', '2d', '2darray', '3d', 'cube', 'cubearray', 'buffer', '2d']   # Shader::TextureType → the answer table's names (Color2DRect samples as 2D)
# VideoCore::Surface::PixelFormat in order (the pixel format table holds its values cast to Shader::TexturePixelFormat, whose own list lacks ETC2 / EAC: the same in Lichii nx2 and Eden NX2)
PIXFMT = ('A8B8G8R8_UNORM A8B8G8R8_SNORM A8B8G8R8_SINT A8B8G8R8_UINT R5G6B5_UNORM B5G6R5_UNORM A1R5G5B5_UNORM A2B10G10R10_UNORM A2B10G10R10_UINT A2R10G10B10_UNORM '
          'A1B5G5R5_UNORM A5B5G5R1_UNORM R8_UNORM R8_SNORM R8_SINT R8_UINT R16G16B16A16_FLOAT R16G16B16A16_UNORM R16G16B16A16_SNORM R16G16B16A16_SINT R16G16B16A16_UINT '
          'B10G11R11_FLOAT R32G32B32A32_UINT BC1_RGBA_UNORM BC2_UNORM BC3_UNORM BC4_UNORM BC4_SNORM BC5_UNORM BC5_SNORM BC7_UNORM BC6H_UFLOAT BC6H_SFLOAT '
          'ASTC_2D_4X4_UNORM B8G8R8A8_UNORM R32G32B32A32_FLOAT R32G32B32A32_SINT R32G32_FLOAT R32G32_SINT R32_FLOAT R16_FLOAT R16_UNORM R16_SNORM R16_UINT R16_SINT '
          'R16G16_UNORM R16G16_FLOAT R16G16_UINT R16G16_SINT R16G16_SNORM R32G32B32_FLOAT A8B8G8R8_SRGB R8G8_UNORM R8G8_SNORM R8G8_SINT R8G8_UINT R32G32_UINT '
          'R16G16B16X16_FLOAT R32_UINT R32_SINT ASTC_2D_8X8_UNORM ASTC_2D_8X5_UNORM ASTC_2D_5X4_UNORM B8G8R8A8_SRGB BC1_RGBA_SRGB BC2_SRGB BC3_SRGB BC7_SRGB '
          'A4B4G4R4_UNORM G4R4_UNORM ASTC_2D_4X4_SRGB ASTC_2D_8X8_SRGB ASTC_2D_8X5_SRGB ASTC_2D_5X4_SRGB ASTC_2D_5X5_UNORM ASTC_2D_5X5_SRGB ASTC_2D_10X8_UNORM '
          'ASTC_2D_10X8_SRGB ASTC_2D_6X6_UNORM ASTC_2D_6X6_SRGB ASTC_2D_10X6_UNORM ASTC_2D_10X6_SRGB ASTC_2D_10X5_UNORM ASTC_2D_10X5_SRGB ASTC_2D_10X10_UNORM '
          'ASTC_2D_10X10_SRGB ASTC_2D_12X10_UNORM ASTC_2D_12X10_SRGB ASTC_2D_12X12_UNORM ASTC_2D_12X12_SRGB ASTC_2D_8X6_UNORM ASTC_2D_8X6_SRGB ASTC_2D_6X5_UNORM '
          'ASTC_2D_6X5_SRGB E5B9G9R9_FLOAT ETC2_RGB_UNORM ETC2_RGBA_UNORM ETC2_RGB_PTA_UNORM ETC2_RGB_SRGB ETC2_RGBA_SRGB ETC2_RGB_PTA_SRGB EAC_R11_UNORM EAC_R11_SNORM '
          'EAC_R11G11_UNORM EAC_R11G11_SNORM D32_FLOAT D16_UNORM X8_D24_UNORM S8_UINT D24_UNORM_S8_UINT S8_UINT_D24_UNORM D32_FLOAT_S8_UINT').split()
def pixfmt(v): return PIXFMT[v] if 0 <= v < len(PIXFMT) else f'format{v}'
def is_int(name): return name.endswith(('_UINT', '_SINT')) and not name.startswith('D')   # what a shader reads as integers (a depth-stencil format samples its depth)
# Image formats by the translator's names (Ryujinx TextureFormat, the answer table's "img" "fmt"), for the formats an image is likely to have
RYU_FMT = {'R8_UNORM': 'R8Unorm', 'R8_SNORM': 'R8Snorm', 'R8_UINT': 'R8Uint', 'R8_SINT': 'R8Sint', 'R16_FLOAT': 'R16Float', 'R16_UNORM': 'R16Unorm', 'R16_SNORM': 'R16Snorm',
           'R16_UINT': 'R16Uint', 'R16_SINT': 'R16Sint', 'R32_FLOAT': 'R32Float', 'R32_UINT': 'R32Uint', 'R32_SINT': 'R32Sint', 'R8G8_UNORM': 'R8G8Unorm', 'R8G8_SNORM': 'R8G8Snorm',
           'R8G8_UINT': 'R8G8Uint', 'R8G8_SINT': 'R8G8Sint', 'R16G16_FLOAT': 'R16G16Float', 'R16G16_UNORM': 'R16G16Unorm', 'R16G16_SNORM': 'R16G16Snorm', 'R16G16_UINT': 'R16G16Uint',
           'R16G16_SINT': 'R16G16Sint', 'R32G32_FLOAT': 'R32G32Float', 'R32G32_UINT': 'R32G32Uint', 'R32G32_SINT': 'R32G32Sint', 'A8B8G8R8_UNORM': 'R8G8B8A8Unorm',
           'A8B8G8R8_SNORM': 'R8G8B8A8Snorm', 'A8B8G8R8_UINT': 'R8G8B8A8Uint', 'A8B8G8R8_SINT': 'R8G8B8A8Sint', 'R16G16B16A16_FLOAT': 'R16G16B16A16Float',
           'R16G16B16A16_UNORM': 'R16G16B16A16Unorm', 'R16G16B16A16_SNORM': 'R16G16B16A16Snorm', 'R16G16B16A16_UINT': 'R16G16B16A16Uint', 'R16G16B16A16_SINT': 'R16G16B16A16Sint',
           'R32G32B32A32_FLOAT': 'R32G32B32A32Float', 'R32G32B32A32_UINT': 'R32G32B32A32Uint', 'R32G32B32A32_SINT': 'R32G32B32A32Sint', 'A2B10G10R10_UNORM': 'R10G10B10A2Unorm',
           'A2B10G10R10_UINT': 'R10G10B10A2Uint', 'B10G11R11_FLOAT': 'R11G11B10Float'}
# c2's handle table, as the translator numbers it (dmsh_xlate/Program.cs: TexBase, ImgBase, ImgSlots, SepTexBase, SepTexSlot0, SampBase)
TEX_BASE, IMG_BASE, IMG_SLOTS, SEPTEX_BASE, SEPTEX_SLOT0, SAMP_BASE = 0x20, 0x120, 8, 0x168, 128, 0x568
EXIT_OP, BRA_OP = 0x94d, 0x947   # the low 12 bits of an Ampere EXIT / BRA


def red(msg): sys.exit('[RED] ' + msg)


# ---------- The cache file ----------
class Env:
    """One environment: its stage (our package's) and its Shader::Stage, the code's place in the file, its SHA-1, its first 0x50 bytes and NEDENMAP count (None without
    one), the tables, a compute program's workgroup and shared memory allocation"""
    __slots__ = ('stage', 'sst', 'code_off', 'code_size', 'sha', 'head', 'nmap', 'tex', 'pix', 'cbuf', 'wg', 'smem')

    def __init__(self, sst, code_off, code, tex, pix, cbuf, wg=None, smem=None):
        self.stage, self.sst, self.code_off, self.code_size = STAGE[sst], sst, code_off, len(code)
        self.sha, self.head, self.nmap = hashlib.sha1(code).digest(), code[:0x50], None
        if len(code) >= 16 and struct.unpack_from('<Q', code, len(code) - 8)[0] == MAP_MAGIC:
            n = struct.unpack_from('<Q', code, len(code) - 16)[0]
            if n + 2 <= len(code) // 8: self.nmap = n
        self.tex, self.pix, self.cbuf, self.wg, self.smem = tex, pix, cbuf, wg, smem


def read_entries(path):
    """The cache's entries, one at a time (the file is read as a stream): yields (entry offset, [Env], raw pipeline key). An Env keeps the code's place in the file, its SHA-1,
    its first 0x50 bytes and the NEDENMAP count (None without one), not the code"""
    size = os.path.getsize(path)
    with open(path, 'rb', buffering=1 << 22) as f:
        def rd(n):
            b = f.read(n)
            if len(b) != n: red(f'{path}: cut short at {f.tell():#x} ({n} bytes wanted, {len(b)} there)')
            return b
        h = f.read(12)
        if len(h) != 12 or h[:8] != MAGIC: red(f'{path}: not a yuzu / Eden pipeline cache (no "yuzucach" header)')
        ver = struct.unpack_from('<I', h, 8)[0]
        if ver not in VERSIONS: red(f'{path}: cache version {ver}, this reader knows {", ".join(map(str, sorted(VERSIONS)))}')
        ncounts, mesh_tail = VERSIONS[ver]
        yield ver
        while f.tell() < size:
            off = f.tell()
            nenv = struct.unpack('<I', rd(4))[0]
            if not 1 <= nenv <= 6: red(f'{path}: entry at {off:#x} has {nenv} environments (1 to 6 expected): a layout this reader does not know')
            envs = []
            for _ in range(nenv):
                counts = struct.unpack(f'<{ncounts}Q', rd(8 * ncounts))
                cs, ntt, npf, ncb = counts[:4]; nsp = counts[4] if ncounts == 6 else 0; ncr = counts[-1]
                if cs % 8 or cs > size or max(ntt, npf, ncb, nsp, ncr) > size: red(f'{path}: entry at {off:#x}: impossible counts {counts}')
                st = struct.unpack('<7I', rd(28))[6]
                if st not in STAGE: red(f'{path}: entry at {off:#x}: stage {st}')
                code_off = f.tell(); code = rd(cs)
                tex = list(struct.iter_unpack('<II', rd(8 * ntt))) if ntt else []
                pix = list(struct.iter_unpack('<II', rd(8 * npf))) if npf else []
                cbuf = list(struct.iter_unpack('<QI', rd(12 * ncb))) if ncb else []
                if nsp: rd(9 * nsp)
                if ncr: rd(12 * ncr)
                wg = smem = None
                if st == 5: x, y, z, smem = struct.unpack('<4I', rd(16)); wg = (x, y, z)
                else:
                    rd(0x50)
                    if st == 3: rd(32)
                    if st in (7, 8) and mesh_tail: rd(12 + 0x50)
                envs.append(Env(st, code_off, code, tex, pix, cbuf, wg, smem))
                del code
            key = rd(CS_KEY if envs[0].stage == 'cs' else GFX_KEY)
            yield off, envs, key


def gfx_state(key):
    """A summary of a graphics key's FixedPipelineState: topology, msaa mode, depth format (-1 without depth), colour formats (hex of the 8 bytes), blending enable mask"""
    raw1, raw2 = struct.unpack_from('<II', key, 48)
    att = struct.unpack_from('<8I', key, 128)
    return ((raw1 >> 24) & 15, (raw1 >> 28) & 15, (raw2 >> 6) & 31 if (raw2 >> 5) & 1 else -1, key[56:64].hex(), sum(1 << i for i, a in enumerate(att) if (a >> 30) & 1))


def binding_of(k):
    """Where a cbuf entry's key points, as an answer table slot (an int: c2's texture table, 128 + n for separate texture n) or 'c<bank>+<offset>' elsewhere"""
    bank, off = (k >> 32) & 0x7fffffff, k & 0xffffffff
    if bank == 2 and off % 8 == 0:
        if TEX_BASE <= off < SEPTEX_BASE: return (off - TEX_BASE) // 8
        if SEPTEX_BASE <= off < SAMP_BASE: return SEPTEX_SLOT0 + (off - SEPTEX_BASE) // 8
    return f'c{bank}+{off:#x}'


def env_bindings(e):
    """[(binding, texture type, pixel format or None)] of an environment: each texture handle it read, placed by a heuristic at the cbuf value table's entries that hold the
    same value (c2's handle table first; the tables do not record where the handle was read)"""
    at = collections.defaultdict(list)
    for k, v in e.cbuf:
        if not k >> 63: at[v].append(k)
    pf, out = dict(e.pix), []
    for h, t in e.tex:
        bs = sorted({binding_of(k) for k in at.get(h, ())}, key=str)
        slots = [b for b in bs if isinstance(b, int)]
        for b in slots or bs or ['?']: out.append((b, t, pf.get(h)))
    return out


class Program:
    """A distinct program (by code SHA-1): its first environment's place and signature, and what all its environments recorded: bindings → texture types / pixel
    formats (counts), (workgroup, shared memory) → count"""
    __slots__ = ('idx', 'stage', 'code_off', 'code_size', 'head', 'nmap', 'wg', 'envs', 'tex', 'pix', 'local')

    def __init__(self, idx, e):
        self.idx, self.stage, self.code_off, self.code_size, self.head, self.nmap, self.wg = idx, e.stage, e.code_off, e.code_size, e.head, e.nmap, e.wg
        self.envs, self.tex, self.pix, self.local = 0, collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter), collections.Counter()


class Cache:
    """One pass over a cache: its distinct programs (by code SHA-1) with what their environments recorded, its pipelines, and the counts 'info' prints"""
    def __init__(self, path):
        self.path = path
        self.progs, self.order = {}, []
        self.pipes = collections.Counter()   # (kind, ((Shader::Stage, program index), ...), state summary) → entries
        self.n = collections.Counter(); self.stage_sets = collections.Counter(); self.env_stage = collections.Counter()
        self.tex_types = collections.Counter(); self.flags = collections.Counter(); self.drivers = collections.Counter(); self.topo = collections.Counter()
        keys = set()
        it = read_entries(path)
        self.version = next(it)
        for _off, envs, key in it:   # pyright: ignore[reportGeneralTypeIssues]  # read_entries yields the version, then (offset, environments, key) entries
            ids = []
            for e in envs:
                self.env_stage[SLOT[e.sst]] += 1; self.n['tables texture types'] += len(e.tex); self.n['tables pixel formats'] += len(e.pix); self.n['tables cbuf values'] += len(e.cbuf)
                if e.nmap is None: self.n['environments without a NEDENMAP'] += 1
                for _, t in e.tex: self.tex_types[t] += 1
                p = self.progs.get(e.sha)
                if p is None:
                    p = self.progs[e.sha] = Program(len(self.order), e); self.order.append(p)
                p.envs += 1
                if e.wg is not None: p.local[(e.wg, e.smem)] += 1
                for b, t, f in env_bindings(e):
                    p.tex[b][t] += 1
                    if f is not None: p.pix[b][f] += 1
                ids.append((e.sst, p.idx))
            keys.add(key)
            st = tuple(SLOT[e.sst] for e in envs)
            self.stage_sets[st] += 1
            if len(set(st)) != len(st): self.n['entries with a stage twice'] += 1   # (pipelines.tsv keeps the last one: warned in the summary)
            if st[0] == 'cs': self.n['entries compute'] += 1; self.pipes[('c', tuple(ids), struct.unpack_from('<4I', key, 8))] += 1
            else:
                self.n['entries graphics'] += 1
                s = gfx_state(key); self.pipes[('g', tuple(ids), s)] += 1; self.topo[s[0]] += 1
                raw1 = struct.unpack_from('<I', key, 48)[0]
                self.flags[tuple((raw1 >> b) & 1 for b in range(8))] += 1
                self.drivers[struct.unpack_from('<II', key, 64)] += 1
        self.n['entries'] = self.n['entries graphics'] + self.n['entries compute']
        self.n['distinct pipeline keys'] = len(keys)
        self.n['distinct stage sets'] = len({ids for _, ids, _ in self.pipes})

    def info(self):
        n, o = self.n, []
        o.append(f'{self.path}: version {self.version}, {n["entries"]:,} entries ({n["entries graphics"]:,} graphics, {n["entries compute"]:,} compute), '
                 f'{n["distinct pipeline keys"]:,} distinct keys, {n["distinct stage sets"]:,} distinct stage sets')
        o.append('stages per entry: ' + ', '.join(f'{"+".join(k)} {v:,}' for k, v in self.stage_sets.most_common()))
        o.append(f'environments: {sum(self.env_stage.values()):,} (' + ', '.join(f'{k} {v:,}' for k, v in self.env_stage.most_common()) + f'), {n["environments without a NEDENMAP"]:,} without a NEDENMAP')
        if n['entries with a stage twice']: o.append(f'[RED] {n["entries with a stage twice"]:,} entries have a stage twice (pipelines.tsv shows the last of them)')
        ps = collections.Counter(p.stage for p in self.order)
        o.append(f'distinct programs: {len(self.order):,} (' + ', '.join(f'{k} {v:,}' for k, v in ps.most_common()) + ')')
        o.append(f'tables: {n["tables texture types"]:,} texture types (' + ', '.join(f'{TEX_TYPE[k] if k < len(TEX_TYPE) else k} {v:,}' for k, v in self.tex_types.most_common())
                 + f'), {n["tables pixel formats"]:,} pixel formats, {n["tables cbuf values"]:,} cbuf values')
        if self.flags:
            fl = ('EDS1', 'EDS2', 'EDS2 logic op', 'EDS3 blend', 'EDS3 enables', 'dynamic vertex input', 'xfb', 'ndc -1..1')
            o.append('graphics keys recorded with: ' + '; '.join(f'{v:,} keys: ' + (', '.join(fl[i] for i, b in enumerate(k) if b) or 'none') for k, v in self.flags.most_common(3)))
            o.append('driver id / version: ' + ', '.join(f'{d} / {ver:#x} {c:,}' for (d, ver), c in self.drivers.most_common()) + '; topology codes: ' + ', '.join(f'{k} {v:,}' for k, v in self.topo.most_common()))
        return '\n'.join(o)


# ---------- Our shader package ----------
def borrow_key(key_skip):
    """skey(ctl, code) and nvn2_ctl of shader_split.py (with the profile's shader_key_skip), taken from its source by name, so the key stays one copy (as vk_android_build.py does)"""
    fns_want, consts_want = ('nvn2_ctl', 'ctl_len', 'key_ctl', 'is_ref', 'skey'), ('NVN2_KEY_CTL', 'CTL_MAGIC', 'CODE_REF')
    with open(SPLIT, encoding='utf-8') as f: tree = ast.parse(f.read(), SPLIT)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in fns_want}
    consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, (ast.Name, ast.Tuple)) and
              {e.id for e in (t.elts if isinstance(t, ast.Tuple) else [t]) if isinstance(e, ast.Name)} & set(consts_want) for t in n.targets)]
    if len(fns) != len(fns_want): red(f'{SPLIT} no longer defines {", ".join(sorted(set(fns_want) - set(fns)))}: eden_cache.py takes them from there')
    ns = {'struct': struct, 'hashlib': hashlib, 'KEY_SKIP': key_skip}
    exec(compile(ast.Module(body=[*consts, *(fns[n] for n in fns_want)], type_ignores=[]), SPLIT, 'exec'), ns)
    return ns['skey'], ns['nvn2_ctl']


def exit_ends(code, base):
    """The instruction counts at which a native program may end: i and i + 1 for each EXIT followed by a BRA at instruction i (the closing self-branch)"""
    n = (len(code) - base) // 16
    if n < 2: return set()
    ops = memoryview(code[base:base + 16 * n]).cast('I')[::4]
    out, prev = set(), 0
    for i, w in enumerate(ops):
        op = w & 0xfff
        if op == BRA_OP and prev == EXIT_OP: out.update((i, i + 1))
        prev = op
    return out


class Package:
    """The records of a shader_split.py package (NVN2 ones: a code area with the 0x80-byte SPH, or a compute code area, and a version 0xc9 control section), by key, and the
    index the matcher looks candidates up in: (stage, signature, instruction count) → keys"""
    def __init__(self, pkg_dir, skey, nvn2_ctl):
        self.rec, self.index, self.skipped, self.maps = {}, collections.defaultdict(list), 0, []
        names = sorted(n for n in os.listdir(pkg_dir) if n.endswith('.bin') and n.split('_')[0] in STAGE_NAME)
        if not names: red(f'{pkg_dir}: no package files (<stage>_<group>.bin, shader_split.py)')
        for name in names:
            stage = name.split('_')[0]
            f = open(os.path.join(pkg_dir, name), 'rb')
            if not os.fstat(f.fileno()).st_size: f.close(); continue
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ); f.close(); self.maps.append(mm)
            pos = mm.find(b'BTCDBTCD')
            while pos >= 0:
                tl, cl = struct.unpack_from('<2I', mm, pos + 0x28)
                at = pos + 0x38
                code, ctl = mm[at:at + cl], mm[at + cl:at + cl + tl]
                pos = mm.find(b'BTCDBTCD', at + cl + tl)
                if not nvn2_ctl(ctl) or len(ctl) < 0x64: self.skipped += 1; continue
                key = skey(ctl, code)
                if key in self.rec: continue
                base = 0 if stage == 'cs' else 0x80
                sig = struct.unpack_from('<3I', ctl, 0x58) if stage == 'cs' else code[:0x50]
                self.rec[key] = (stage, mm, at + base, cl - base)   # the native instructions' place in the mapping (read again only for the candidates the matcher compares)
                for n in exit_ends(code, base): self.index[(stage, sig, n)].append(key)

    def close(self):
        for mm in self.maps: mm.close()
        self.maps, self.rec = [], {}

    def code(self, key):
        """A record's whole code area (with the SPH)"""
        stage, mm, at, n = self.rec[key]
        base = 0 if stage == 'cs' else 0x80
        return mm[at - base:at + n]

    def native(self, key, i):
        _stage, mm, at, n = self.rec[key]
        return mm[at + 16 * i:at + 16 * i + 16] if 16 * i + 16 <= n else b''


# ---------- Matching ----------
def lowered_tokens(words):
    """The operand values the lowered (Maxwell) instructions carry: 32-bit immediates, constant buffer bank / offset (both encodings), 19-bit floats and 20-bit signed immediates"""
    t = set()
    for w in words:
        t.add(('i32', (w >> 20) & 0xffffffff))
        t.add(('cb', (w >> 34) & 0x1f, ((w >> 20) & 0x3fff) * 4))
        t.add(('cb', (w >> 36) & 0x1f, (w >> 20) & 0xffff))
        t.add(('f19', (w >> 20) & 0x7ffff, (w >> 56) & 1))
        v = ((w >> 20) & 0x7ffff) | (((w >> 56) & 1) << 19)
        t.add(('s20', v - (1 << 20) if v & (1 << 19) else v))
    return t


def native_tokens(ins):
    """The same values of a native (Ampere) instruction: its 32-bit immediate (forms 2 and 4) or its constant buffer operand (forms 3 and 5)"""
    if len(ins) < 8: return set()
    w0, w1 = struct.unpack_from('<2I', ins)
    form, t = (w0 >> 9) & 7, set()
    if form in (2, 4):
        t.add(('i32', w1)); t.add(('f19', (w1 >> 12) & 0x7ffff, w1 >> 31))
        sv = w1 - (1 << 32) if w1 >> 31 else w1
        if -(1 << 19) <= sv < (1 << 19): t.add(('s20', sv))
    if form in (3, 5): t.add(('cb', (w1 >> 22) & 0x1f, ((w1 >> 8) & 0x3fff) * 4))
    return t


def match(cache, pkg):
    """Each program of the cache → (our keys, how): how is 'exact', 'weak', 'same', 'tie' or 'none' (the file header)"""
    out = {}
    with open(cache.path, 'rb') as f:
        for p in cache.order:
            if p.nmap is None: out[p.idx] = ((), 'none'); continue
            sig = p.wg if p.stage == 'cs' else p.head
            cands = sorted(set(pkg.index.get((p.stage, sig, p.nmap), ())))
            if not cands: out[p.idx] = ((), 'none'); continue
            n = p.nmap
            diff = [i for i in range(n) if len({pkg.native(k, i) for k in cands}) > 1] if len(cands) > 1 else []
            if len(cands) > 1 and not diff: out[p.idx] = (tuple(cands), 'same'); continue
            f.seek(p.code_off); code = f.read(p.code_size)
            words = struct.unpack(f'<{len(code) // 8}Q', code)
            start = len(words) - 2 - n; amap = words[start:start + n]
            lts = {}

            def lowered_at(i, lts=lts, amap=amap, words=words, start=start, n=n):   # (this program's: bound here)
                """The operand values of native instruction i's lowered range; None for an empty range (an instruction lowered to nothing, or a map step that goes back)"""
                if i not in lts:
                    lo = max(amap[i] // 8, 10); hi = min(amap[i + 1] // 8 if i + 1 < n else start - 1, start - 1)
                    lts[i] = lowered_tokens(words[lo:hi]) if hi > lo else None
                return lts[i]
            win = tuple(cands)
            if diff:
                score = [0] * len(cands)
                for i in diff:
                    lt = lowered_at(i)
                    if lt is None: continue
                    for j, k in enumerate(cands):
                        if native_tokens(pkg.native(k, i)) & lt: score[j] += 1
                best = max(score); win = tuple(k for k, s in zip(cands, score) if s == best)
                if len(win) > 1: out[p.idx] = (win, 'tie'); continue
            # The one candidate (or the winner) over its own operand instructions: the record has the program's SPH / workgroup and length, its operands must agree too
            agree = total = 0
            for i in range(n):
                nt = native_tokens(pkg.native(win[0], i))   # pyright: ignore[reportGeneralTypeIssues]  # win is never empty: cands is not, and best is one of the scores
                if not nt: continue
                lt = lowered_at(i)
                if lt is None: continue
                total += 1; agree += bool(nt & lt)
            out[p.idx] = (win, 'exact' if total < AGREE_MIN or agree >= AGREE_FRAC * total else 'weak')
    return out


# ---------- Outputs ----------
def read_rows(path, cols=None):
    if not os.path.isfile(path): return []
    with open(path, encoding='utf-8') as f: rows = [ln.rstrip('\n').split('\t') for ln in f if ln.strip() and not ln.startswith('#')]
    return [r for r in rows if cols is None or len(r) >= cols]


class Result:
    def __init__(self, cache, pkg, m, game, exact_only):
        self.cache, self.pkg, self.m, self.game, self.exact_only = cache, pkg, m, game, exact_only
        self.uses = collections.Counter()   # key → pipelines (entries) that used it
        for (_kind, ids, _s), c in cache.pipes.items():
            for _sst, i in ids:
                ks, how = m[i]
                if how == 'exact' or (how != 'none' and not exact_only):
                    for k in ks: self.uses[k] += c
        exact = {ks[0] for ks, how in m.values() if how == 'exact'}
        self.how = {k: 'exact' if k in exact else 'candidate' for k in self.uses}

    def key_of(self, i):
        ks, how = self.m[i]
        return ks[0] if how == 'exact' else None

    def keys_tsv(self):
        o = ['# The shader keys (column 4 of shader_map.tsv) an emulator\'s pipeline cache recorded (dm/tools/eden_cache.py, from a user-provided cache; nothing of the cache is here). '
             'Rows: key<TAB>stage<TAB>pipelines that used it<TAB>exact or candidate (one of the programs the cache cannot tell apart, or a weak match)',
             'key\tstage\tpipelines\tmatch']
        for k in sorted(self.uses): o.append(f'{k}\t{STAGE_NAME[self.pkg.rec[k][0]]}\t{self.uses[k]}\t{self.how[k]}')
        return '\n'.join(o) + '\n'

    @staticmethod
    def columns(ids):
        """A pipeline's program index by stage column (va vb hs ds gs ts ms ps cs; the last one when an entry has a stage twice)"""
        return {SLOT[sst]: i for sst, i in ids}

    def pairs(self):
        """(VertexB key, pixel key) → entries, for the graphics pipelines without a tessellation or geometry stage (their vertex outputs do not reach the pixel shader)
        whose stages all matched exactly; and the counts of what was left out or noted"""
        out, note = collections.Counter(), collections.Counter()
        for (kind, ids, _s), c in self.cache.pipes.items():
            if kind != 'g': continue
            col = self.columns(ids)
            if 'vb' not in col or 'ps' not in col: continue
            if {'hs', 'ds', 'gs'} & set(col): note['with a tessellation or geometry stage (no pair)'] += c; continue
            if any(self.key_of(i) is None for _sst, i in ids): continue
            if 'va' in col: note['with a VertexA (paired by their VertexB)'] += c
            out[(self.key_of(col['vb']), self.key_of(col['ps']))] += c
        return out, note

    def pairs_tsv(self):
        pr, _ = self.pairs()
        o = [f'# VertexB / pixel shader pairs of the graphics pipelines an emulator\'s pipeline cache recorded, without a tessellation or geometry stage and every stage matched '
             f'exactly (dm/tools/eden_cache.py): {len(pr):,} pairs, pso_pairs.tsv\'s columns: vertex key <TAB> pixel key']
        o += [f'{v}\t{p}' for v, p in sorted(pr)]
        return '\n'.join(o) + '\n'

    def pipelines_tsv(self):
        o = ['# Every distinct pipeline of the cache (dm/tools/eden_cache.py): its key for each stage (va VertexA, vb VertexB, hs ds gs, ts ms task and mesh, ps, cs; "?" a stage '
             'not matched exactly, "-" none) and a summary of its fixed state: graphics Maxwell topology, msaa mode, depth format (-1 none), the 8 colour format bytes, the '
             'blending enable mask; compute shared memory allocation and workgroup. Then how many entries had it',
             'kind\t' + '\t'.join(COLS) + '\tstate\tentries']
        rows = []
        for (kind, ids, s), c in self.cache.pipes.items():
            col = {st: self.key_of(i) or '?' for st, i in self.columns(ids).items()}
            state = ' '.join(map(str, s)) if kind == 'g' else f'shared_alloc {s[0]} local {s[1]} {s[2]} {s[3]}'
            rows.append(f'{"graphics" if kind == "g" else "compute"}\t' + '\t'.join(col.get(st, '-') for st in COLS) + f'\t{state}\t{c}')
        return '\n'.join(o + sorted(rows)) + '\n'

    def facts(self):
        """key → (answer table facts, [binding rows], [launch rows]) for every exactly matched program: texture types by slot (a slot seen with one type), image formats,
        compute local size (one workgroup seen); a compute program's launches as (workgroup, shared memory allocation, environments), for the detail table only"""
        out = {}
        for p in self.cache.order:
            k = self.key_of(p.idx)
            if k is None: continue
            f, det = {}, []
            for b, types in sorted(p.tex.items(), key=lambda x: str(x[0])):
                fmts = p.pix.get(b, collections.Counter())
                names = sorted({pixfmt(x) for x in fmts})
                integer = sorted({is_int(x) for x in names})
                det.append((k, STAGE_NAME[p.stage], str(b), ','.join(TEX_TYPE[t] if t < len(TEX_TYPE) else str(t) for t in sorted(types)), ','.join(names) or '-',
                            {(): '-', (False,): 'float', (True,): 'int'}.get(tuple(integer), 'mixed'), sum(types.values())))
                if isinstance(b, int) and len(types) == 1 and next(iter(types)) < len(TEX_TYPE):
                    f.setdefault('tex', {})[str(b)] = TEX_TYPE[next(iter(types))]
                    off = TEX_BASE + 8 * b
                    if IMG_BASE <= off < IMG_BASE + 8 * IMG_SLOTS and len(names) == 1 and names[0] in RYU_FMT:
                        f.setdefault('img', {})[str((off - IMG_BASE) // 8)] = {'fmt': RYU_FMT[names[0]], 'type': TEX_TYPE[next(iter(types))]}
            # The shared memory stays out of the facts: the cache has the launch's allocation (rounded up to 256 bytes), not what the control section declares
            if p.stage == 'cs' and len({wg for wg, _ in p.local}) == 1: f['local'] = list(next(iter(p.local))[0])
            launch = [(wg, smem, n) for (wg, smem), n in sorted(p.local.items())]
            out[k] = (f, det, launch)
        return out

    def facts_tsv(self, facts):
        o = ['# Answer table rows (shader_facts.tsv\'s format: key <TAB> fact JSON) of what an emulator\'s pipeline cache recorded about each exactly matched shader (dm/tools/eden_cache.py): '
             'the texture type behind each c2 slot it read, image formats, compute local size (not the shared memory: the cache has only the launch\'s allocation, facts_detail.tsv)']
        o += [k + '\t' + json.dumps(f, sort_keys=True, separators=(',', ':')) for k, (f, _, _) in sorted(facts.items()) if f]
        return '\n'.join(o) + '\n'

    def facts_detail_tsv(self, facts):
        o = ['# Every binding an exactly matched shader read in the recorded pipelines (dm/tools/eden_cache.py): the slot of c2\'s handle table (the answer table\'s numbering), or c<bank>+<offset> '
             'where the handle was elsewhere, "?" not found in its constant buffers (placed by matching the handle\'s value in the cbuf value table: a heuristic); the texture types and '
             'pixel formats the emulator saw there, whether those read as integers, and how many environments read it. A compute shader\'s "launch" rows: the workgroup in types\' '
             'place and the launch\'s shared memory allocation (shared_alloc, rounded up to 256 bytes by the emulator: not the program\'s declared value) in formats\' place',
             'key\tstage\tbinding\ttypes\tformats\tinteger\tenvironments']
        for k, (_f, det, launch) in sorted(facts.items()):
            o += ['\t'.join(map(str, r)) for r in det]
            o += [f'{k}\tcompute\tlaunch\tlocal={",".join(map(str, wg))}\tshared_alloc={smem}\t-\t{n}' for wg, smem, n in launch]
        return '\n'.join(o) + '\n'

    def summary(self, facts=None):
        c, o = self.cache, [self.cache.info(), '']
        by = collections.Counter((c.order[i].stage, how) for i, (_ks, how) in self.m.items())
        o.append(f'package: {len(self.pkg.rec):,} NVN2 records' + (f' ({self.pkg.skipped:,} other records skipped)' if self.pkg.skipped else ''))
        for st in sorted({s for s, _ in by}):
            tot = sum(v for (s, _), v in by.items() if s == st)
            o.append(f'  {st}: {tot:,} programs: ' + ', '.join(f'{h} {by[(st, h)]:,}' for h in ('exact', 'weak', 'same', 'tie', 'none') if by[(st, h)]))
        same = [ks for ks, how in self.m.values() if how == 'same']
        if same:
            ident = sum(1 for ks in same if len({self.pkg.code(k) for k in ks}) == 1)
            o.append(f'same: {ident:,} of {len(same):,} have candidates with byte-identical code areas (they differ only in the control section), {len(same) - ident:,} differ after instruction N')
        exact = {ks[0] for ks, how in self.m.values() if how == 'exact'}
        cand = {k for ks, how in self.m.values() if how in ('weak', 'same', 'tie') for k in ks}
        np_ = len(c.order); ne = sum(1 for _, how in self.m.values() if how == 'exact'); nc = sum(1 for _, how in self.m.values() if how != 'none')
        o.append(f'programs: {ne:,} of {np_:,} matched exactly ({100 * ne / max(np_, 1):.1f}%), {nc:,} with candidates ({100 * nc / max(np_, 1):.1f}%)')
        o.append(f'our keys: {len(exact):,} exact of {len(self.pkg.rec):,} in the package ({100 * len(exact) / max(len(self.pkg.rec), 1):.1f}%), {len(exact | cand):,} with the candidates; '
                 f'keys.tsv has {len(self.uses):,} rows' + (' (exact only)' if self.exact_only else ''))
        dup = len(exact) != ne
        if dup: o.append(f'[RED] {ne - len(exact)} programs matched a key another program matched too')
        pst, distinct = collections.Counter(), collections.Counter()
        for (_kind, ids, _s), n in c.pipes.items():
            hs = [self.m[i][1] for _sst, i in ids]
            k = 'every stage exact' if all(h == 'exact' for h in hs) else 'a stage not matched' if 'none' in hs else 'every stage matched, some ambiguous or weak'
            pst[k] += n; distinct[k] += 1
        o.append('pipelines (entries): ' + ', '.join(f'{k} {v:,}' for k, v in pst.most_common()))
        o.append(f'pipelines (distinct, {len(c.pipes):,}): ' + ', '.join(f'{k} {v:,}' for k, v in distinct.most_common()))
        stages = collections.Counter()
        for (_kind, ids, _s), n in c.pipes.items():
            for sst, _i in ids: stages[SLOT[sst]] += n
        o.append('pipeline stages (entries): ' + ', '.join(f'{st} {stages[st]:,}' for st in COLS if stages[st]))
        pr, note = self.pairs()
        if note: o.append('pairs: graphics pipelines (entries) ' + ', '.join(f'{k} {v:,}' for k, v in note.most_common()))
        if self.game is not None:
            mp = {r[3] for r in read_rows(str(self.game.table('shader_map.tsv')), 4) if r[0] != 'package'}
            o.append(f'profile {self.game.id}: {len(set(self.uses) & mp):,} of the {len(self.uses):,} keys are in its shader_map.tsv ({len(mp):,} keys)')
            have = set()
            for t in ('shader_pairs.tsv', 'pso_pairs.tsv'): have |= {(r[0], r[1]) for r in read_rows(str(self.game.table(t)), 2)}
            o.append(f'pairs: {len(pr):,} vertex / pixel pairs, {len(set(pr) - have):,} not in the profile\'s shader_pairs.tsv + pso_pairs.tsv ({len(have):,} pairs)')
            if facts is not None:
                prof = {r[0]: json.loads(r[1]) for r in read_rows(str(self.game.table('shader_facts.tsv')), 2)}
                both = [k for k, (f, _, _) in facts.items() if k in prof and f]
                dl = sum(1 for k in both if 'local' in facts[k][0] and prof[k].get('local') not in (None, facts[k][0]['local']))
                # shared_alloc against the profile's declared shared memory: the allocation is that rounded up to 256 bytes
                sa = [(smem, prof[k]['shared']) for k, (_f, _d, launch) in facts.items() if k in prof and 'shared' in prof[k] for _wg, smem, _n in launch]
                sa_eq = sum(1 for a, s in sa if a == -(-s // 256) * 256)
                cmp_t = [(t, prof[k]['tex'].get(s)) for k in both if prof[k].get('tex') for s, t in facts[k][0].get('tex', {}).items()]
                dt = sum(1 for t, pt in cmp_t if pt not in (None, t))
                withtex = [k for k, (f, _, _) in facts.items() if f.get('tex')]
                arr = sum(1 for k in withtex if any(t != '2d' for t in facts[k][0]['tex'].values()))
                ints = collections.Counter(r[5] for _k, (_f, det, _l) in facts.items() for r in det)
                outside = sum(1 for _k, (_f, det, _l) in facts.items() for r in det if not r[2].isdigit())
                ptex = sum(1 for k in withtex if prof.get(k, {}).get('tex'))
                o.append(f'facts: {sum(1 for f, _, _ in facts.values() if f):,} keys with facts, {len(both):,} of them in the profile\'s shader_facts.tsv ({len(prof):,} rows): '
                         f'local differs in {dl:,}; shared_alloc is the profile\'s shared rounded up to 256 in {sa_eq:,} of {len(sa):,} launches; '
                         f'{len(withtex):,} keys with texture types ({arr:,} with a type other than 2d), the profile has texture types for {ptex:,} of them '
                         f'({len(cmp_t):,} slots compared, {dt:,} differ); bindings read as integers {ints.get("int", 0):,}, float {ints.get("float", 0):,}, '
                         f'mixed {ints.get("mixed", 0):,}; {outside:,} bindings outside c2\'s table (no answer table slot)')
        return '\n'.join(o) + '\n'


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f: f.write(text)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Read an Eden / yuzu derived pipeline cache (yuzucach) as tables of a profile\'s shader keys (see the file header)')
    ap.add_argument('cmd', choices=('info', 'keys', 'pairs', 'facts', 'all'))
    ap.add_argument('cache')
    ap.add_argument('--game', help='the profile (base game title ID)')
    ap.add_argument('--pkg', help='the shader package directory shader_split.py wrote (<id>_build/shader/pkg)')
    ap.add_argument('-o', '--output', help='the output file (keys, pairs, facts)')
    ap.add_argument('--out', help='the output directory (all)')
    ap.add_argument('--exact', action='store_true', help='keys: only exactly matched keys, not the candidates of ambiguous programs')
    a = ap.parse_args(argv)
    if not os.path.isfile(a.cache): red(f'{a.cache}: no such file')
    if a.cmd == 'info':
        print(Cache(a.cache).info()); return 0
    if not a.game or not a.pkg: red(f'{a.cmd} needs --game <id> and --pkg <shader package dir>')
    if a.cmd == 'all' and not a.out: red('all needs --out <dir>')
    if a.cmd != 'all' and not a.output: red(f'{a.cmd} needs -o <file>')
    sys.path.insert(0, os.path.join(HERE, '../games')); import game as _game
    g = _game.load(a.game)
    skip = tuple(int(x, 0) for x in g.get('shader_key_skip', '0+0').split('+'))
    skey, nvn2 = borrow_key(skip)
    pkg = Package(a.pkg, skey, nvn2)
    cache = Cache(a.cache)
    try: res = Result(cache, pkg, match(cache, pkg), g, a.exact); return write_outputs(a, res)
    finally: pkg.close()


def write_outputs(a, res):
    fa = None
    if a.cmd == 'keys': write(a.output, res.keys_tsv())
    elif a.cmd == 'pairs': write(a.output, res.pairs_tsv())
    elif a.cmd == 'facts':
        fa = res.facts(); write(a.output, res.facts_tsv(fa))
    else:
        fa = res.facts()
        for name, text in (('keys.tsv', res.keys_tsv()), ('pairs.tsv', res.pairs_tsv()), ('pipelines.tsv', res.pipelines_tsv()), ('facts.tsv', res.facts_tsv(fa)),
                           ('facts_detail.tsv', res.facts_detail_tsv(fa))):
            write(os.path.join(a.out, name), text)
        s = res.summary(fa); write(os.path.join(a.out, 'summary.txt'), s); print(s, end='')
        return 0
    print(res.summary(fa), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
