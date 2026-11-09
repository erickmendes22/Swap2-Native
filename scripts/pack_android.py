#!/usr/bin/env python3
# A pack for the Android launcher (android/app) from a dumped game folder (the layout scripts/pack_dump.py reads: base/, updates/<version>/, dlc/).
# The pack holds what the host needs beside the game files and nothing the phone can read from the game folder itself:
#   <module>.patched.bin, <module>.fixups.tsv, <module>.gates.tsv and the rewriter's other tables, for every module of the profile, rewritten with patch_nso.py --target android
#   game.tsv     the profile the host was built with (for reference: the host has it compiled in)
#   pack.tsv     what the launcher reads: title ID, version, build IDs, and the RomFS and DLC folders relative to the game folder; the shader library's path in the pack
#   shaders/v-<DMSH_VK_CHAIN>/dmsh_vk.lib, inputs.tsv   the game's shaders as SPIR-V for the Vulkan replay (dm/gfx/tools/vk_android_build.py; android/SHADERS.md), the library
#                of this source tree's version: an up-to-date one in the shader cache is copied, else it is built from the Switch shader package
#   build_src.sha256, rewrite_<module>.log
# The RomFS is not in the pack (the app gives the host <game folder>/<romfs> as DM_ROMFS) and neither is anything else of the dump but the rewritten code.
# The game may be a NUP file instead of a folder (android/NUP.md): its packages are read in place (pack_dump.scan, dm/tools/nup.py), the modules and the RomFS are
# named `<name>.nup:update/<version>/...` (or `:base/...`), the DLC `<name>.nup:addon/<title ID>/romfs`, and pack.tsv's paths are relative to the folder holding the file.
# Writes <game folder>/../<title ID>-work/android-pack/ unless --out names another folder. A repeat run keeps modules whose inputs are unchanged.
# Needs Python with Capstone 5 and lz4 (pyproject.toml, dependency group android-pack). Packs are for the user's own phone: never commit or share one.
# The shader library: <work>/android-shaders/lib/v-<V>/ is reused when its inputs.tsv names this game and its profile's current inputs (a full build writes it last);
# otherwise it is built there from <work>/android-shaders/pkg (shader_split.py's output, as dmsh_build.py takes) by vk_android_build.py, which needs Python 3.14 (or
# backports.zstd), the .NET 10 runtime and spirv-val: --shader-python names that Python (default: the first of python3.14 / python3 on PATH that has zstd). About 10 minutes
# on DKB with -J 12. Without a package (the default folder or --shader-pkg) the dump is split into it first (split_shaders), and the split must hold every shader of the
# profile's shader_map.tsv; vk_android_build.py reads each shader from the package by its key, so a package of another split (base, update and DLC RomFS together) builds the
# same library and one that lacks a shader stops the build. --no-shaders leaves them out.
# --in-process (the phone's packer, android/ONDEVICE.md: an app may not start programs, and its process must not fork): the rewriter runs in this Python, one module after the other
# (runpy, with DM_REWRITE_J=1), and the shader library is not built here (it must be current in the cache, or --no-shaders).
# Each module is rewritten into <out>/.rewrite-<module>/ and moved into the pack when complete, its <module>.android.key last (a module without its key is
# unfinished: the launcher refuses it, the next run rewrites it). Libraries of other versions in the pack's shaders/ are kept.
# --code-only rewrites the modules and stops (pack.tsv, game.tsv and the shaders untouched); --keep-code packs without rewriting (the phone's two steps).
# --mods DIR (default: the environment's DM_MODS_DIR; the phone's <Switch2>/Mods): exefs patches (dm/tools/exefs_patches.py: <DIR>/<title ID>/<mod>/exefs/<build ID>.ips
# or .pchtxt) are applied to each module they are for before it is rewritten; their digest is part of the module's key, so a changed set of mods rewrites that module only.
# Usage: pack_android.py <game folder | .nup file> [--version N] [--out DIR] [-j N] [--shader-cache DIR] [--shader-pkg DIR] [--shader-python PY] [-J N] [--no-shaders] [--code-only | --keep-code] [--in-process] [--mods DIR]   (exit 1 on error)
import argparse, hashlib, os, re, runpy, shutil, subprocess, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts')); sys.path.insert(0, str(REPO / 'dm/games'))
import pack_dump
import game
sys.path.insert(0, str(REPO / 'dm/gfx/tools'))
import dmsh_chain
sys.path.insert(0, str(REPO / 'dm/tools'))
import exefs_patches

REWRITER = ('patch_nso.py', 'nso.py', 'nso_code.py', 'nso_asm.py', 'nso_match.py', 'sdk_patches.py', 'ue_cvar.py', 'ue_malloc.py', 'ue_region.py', 'loader_census.py')
FORMAT = 2   # pack.tsv format; the launcher refuses another. 2: the pack carries game_profile.tsv (game.py runtime), which Swap2-Native's one host reads at start


class Error(Exception): pass


# The rewrite key, <module>.android.key: SHA-256 over name\0bytes of the REWRITER files (and exefs_patches.py when the module has exefs patches), the module, the
# profile's patches.py (when there is one), every other dm/games/*/patches.py that names the module's build ID (patch_nso.py loads them all, and a build another
# game ships, a shared sdk or movie module, may have its CUTS / OBS / FRAME_STEP there; hashed under its repository path), and the only part of game.tsv the
# rewriter reads: its build rows (patch_nso.py reads them for a module whose build has no CUTS), normalized by build_rows and hashed under the name ROWS. Then
# ' target=android' and, with exefs patches, ' mods=<their digest>'. The rest of game.tsv is the host's (ndsr_input, scene_scale_palette, window size, ...):
# a change there must not make the code stale and rewrite main on the phone.
# A key of the earlier formula (v1: the whole game.tsv, no other patches.py) counts as current when no other patches.py names the build and the game.tsv it
# hashed is the profile's, or the pack's copy (<pack>/game.tsv, written after the rewrite) whose build rows are the profile's: the key proves the copy is the
# file it was made with, and the rows the rewrite read are the same. upgrade_keys writes such a key in the current formula before the copy is replaced.
# The launcher computes the same keys (RewriteKey.java; dm/tools/tests/test_android_rewritekey.py runs both).
ROWS = 'game.tsv build rows'
BUILD_ROW_TEXT = frozenset(range(0x20, 0x7f)) | {0x09}


def build_rows(b):
    """game.tsv's build rows, bytes in, bytes out: each line (split at \\n, one trailing \\r dropped) of printable ASCII and tabs whose first cell is `build`,
    its cells stripped of spaces and joined by tabs, one a line. patch_nso.py splits with str.splitlines and strips each cell with str.strip, which also break
    at \\r, \\x0b, \\x0c, \\x1c-\\x1e, \\x85, U+2028/9 and strip Unicode spaces: a line holding `build` and any byte outside printable ASCII and tabs is kept
    whole, as it is, so two tables that differ for the rewriter never come out the same here (RewriteKey.buildRows does the same)"""
    rows = []
    for line in b.split(b'\n'):
        if line.endswith(b'\r'): line = line[:-1]
        if not all(c in BUILD_ROW_TEXT for c in line):
            if b'build' in line: rows.append(line + b'\n')
            continue
        c = [x.strip(b' ') for x in line.split(b'\t')]
        if c[0] == b'build': rows.append(b'\t'.join(c) + b'\n')
    return b''.join(rows)


def part(h, name, b): h.update(name.encode() + b'\0' + b)


def other_patches(g, data):
    """[(repository path, bytes)] of the dm/games/*/patches.py other than the profile's that name the module's build ID (its NSO header +0x40, 32 hex digits)"""
    bid = data[0x40:0x50].hex().encode() if data[:4] == b'NSO0' and len(data) >= 0x60 else None
    own = os.path.realpath(g.dir / 'patches.py')
    out = []
    for p in sorted((REPO / 'dm/games').glob('*/patches.py'), key=lambda p: f'dm/games/{p.parent.name}/patches.py'):   # by the name hashed, as RewriteKey's TreeMap
        if bid is None or os.path.realpath(p) == own: continue
        b = p.read_bytes()
        if bid in b: out.append((f'dm/games/{p.parent.name}/patches.py', b))
    return out


def rewrite_keys(src, g, mods=(), pack=None, xp=None):
    """Every key that counts as the current rewriter's for the module, rewrite_key's first: the current formula, then (when no other patches.py names the build)
    the v1 key with the profile's game.tsv, and with pack/game.tsv when pack names a pack folder whose copy has the profile's build rows (RewriteKey.keys).
    mods: exefs_patches.find's [(label, path)]; xp: whether exefs_patches.py is hashed (default: when there are mods) and suffix as rewrite_key's"""
    if xp is None: xp = bool(mods)
    h = hashlib.sha256()
    for f in REWRITER: part(h, f, (REPO / 'dm/tools' / f).read_bytes())
    if xp: part(h, 'exefs_patches.py', (REPO / 'dm/tools/exefs_patches.py').read_bytes())
    data = src.read_bytes(); part(h, src.name, data)
    pp = g.dir / 'patches.py'
    if pp.is_file(): part(h, 'patches.py', pp.read_bytes())
    gt = (g.dir / 'game.tsv').read_bytes()
    others = other_patches(g, data)
    cur = h.copy()
    for name, b in others: part(cur, name, b)
    part(cur, ROWS, build_rows(gt))
    hs = [cur]
    if not others:
        tails = [gt]
        pg = pack / 'game.tsv' if pack is not None else None
        if pg is not None and pg.is_file() and (pb := pg.read_bytes()) != gt and build_rows(pb) == build_rows(gt): tails.append(pb)
        for b in tails: t = h.copy(); part(t, 'game.tsv', b); hs.append(t)
    suffix = ' target=android' + (f' mods={exefs_patches.digest(mods)}' if mods else '')
    return [t.hexdigest() + suffix for t in hs]


def rewrite_key(src, g, mods=()):
    """The key a module rewritten now carries (rewrite_keys' first). A module without mods has no ' mods=' part, and exefs_patches.py is not in its hash"""
    return rewrite_keys(src, g, mods)[0]


def upgrade_keys(srcs, out, g):
    """Each module's key that counts as current (rewrite_keys with the pack's game.tsv) in an earlier formula is written in the current one (by rename), so the pack
    stays current when its copy of game.tsv is replaced (--keep-code, which reads no mods: the key's own ' mods=' part is kept, the launcher compares it). Other keys
    are left as they are"""
    for m, src in srcs.items():
        kf = out / f'{m}.android.key'
        if not kf.is_file(): continue
        have = kf.read_text().strip(); digest, _, suffix = have.partition(' ')
        keys = [k.partition(' ')[0] for k in rewrite_keys(src, g, pack=out, xp=' mods=' in have)]
        if digest in keys[1:] and suffix.startswith('target=android'):
            tmp = out / f'{m}.android.key.tmp'; tmp.write_text(keys[0] + ' ' + suffix + '\n'); os.replace(tmp, kf)
            print(f'  {m}: key brought to the current formula (same rewrite)')


def nso_build_id(path):   # the module's build ID (NSO header +0x40), as the profile's build rows name it
    b = path.read_bytes()[:0x60]
    if b[:4] != b'NSO0': raise Error(f'{path}: not an NSO')
    return b[0x40:0x50].hex()


def run_in_process(script, args, env, log):
    """script run as `python3 script args` would run it, in this process: its sys.argv, env added to os.environ, stdout and stderr to the file log;
    everything put back after it (the modules it imported from outside the standard library are dropped, so the next run starts afresh). → its exit code"""
    saved = (sys.argv, list(sys.path), dict(os.environ), set(sys.modules), sys.stdout, sys.stderr, os.getcwd())
    code = 0
    with open(log, 'w', buffering=1, encoding='utf-8', errors='backslashreplace') as f:
        sys.stdout = sys.stderr = f
        try:
            os.environ.update(env); sys.argv = [str(script)] + [str(a) for a in args]; sys.path.insert(0, str(Path(script).parent))
            runpy.run_path(str(script), run_name='__main__')
        except SystemExit as e:
            if e.code is None: code = 0
            elif isinstance(e.code, int): code = e.code
            else: print(e.code, file=f); code = 1
        except BaseException:
            import traceback; traceback.print_exc(); code = 1
        finally:
            argv, path, environ, mods, so, se, cwd = saved
            sys.argv, sys.path[:], sys.stdout, sys.stderr = argv, path, so, se
            os.environ.clear(); os.environ.update(environ); os.chdir(cwd)
            std = os.path.realpath(sys.base_prefix) + os.sep
            for m in set(sys.modules) - mods:
                if not os.path.realpath(getattr(sys.modules.get(m), '__file__', None) or '').startswith(std): sys.modules.pop(m, None)
    return code


def staging(out, m):   # where a module is rewritten before it goes into the pack (inside it: same file system, so the swap is renames)
    return out / f'.rewrite-{m}'


def swap_in(out, m, key):
    """A module's rewritten files from staging(out, m) into out, each by rename, then its key file, written last and also by rename. The old key went
    before the rewrite started, so a pack stopped at any point has either the old module with no key, a mix with no key, or the new module with its key:
    a module without its key is one the launcher refuses (PackCheck) and the next run rewrites"""
    st = staging(out, m)
    for f in sorted(st.iterdir()): os.replace(f, out / f.name)
    st.rmdir()
    tmp = out / f'{m}.android.key.tmp'; tmp.write_text(key + '\n'); os.replace(tmp, out / f'{m}.android.key')


def rewriter_src(src, out, m, mods=()):
    """The file patch_nso.py reads for module m: src itself, or for a module in a NUP package (`game.nup:update/<v>/exefs/main`) a copy in the pack's
    .nup-src/<module>/ under the module's own name. The rewriter then reads a plain file, so its files (REWRITER, rewrite_key) are the same for a NUP
    file and a folder, and a pack made from either keeps the other's rewritten modules. With exefs patches (mods) the copy is the patched module
    (exefs_patches.apply: before the rewriter, so a code cave's svc and timer reads become gates too), and each file is listed with its records"""
    if '.nup:' not in str(src) and not mods: return src
    d = out / '.nup-src' / m; d.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    if mods:
        data, report = exefs_patches.apply(data, mods, m)
        for label, n, w in report: print(f'  {m}: exefs patch {label}: {n} records, {w} bytes', flush=True)
    f = d / src.name; f.write_bytes(data); return f


def rewrite(py, srcs, out, jobs, g, in_process=False, mods=None):
    """patch_nso.py --target android on each module into out (each its own <module>.* files); a module whose key file matches is kept. Each module is
    rewritten into a staging folder and swapped in when it is complete (swap_in), so a run stopped part way never leaves new code with old tables.
    in_process: each in this process (run_in_process) with one worker, one module after the other. mods: module → its exefs patches (rewrite_key, rewriter_src)"""
    mods = mods or {}
    env = dict(os.environ, DM_GAME=g.id, DM_REWRITE_J=str(max(1, (os.cpu_count() or 4) // max(1, len(srcs)))))
    todo = {}
    for m, src in srcs.items():
        keys = rewrite_keys(src, g, mods.get(m, ()), out); key = keys[0]; kf = out / f'{m}.android.key'
        if (out / f'{m}.patched.bin').is_file() and kf.is_file() and (have := kf.read_text().strip()) in keys:   # the current key, or an earlier formula's of the same rewrite
            if have != key: tmp = out / f'{m}.android.key.tmp'; tmp.write_text(key + '\n'); os.replace(tmp, kf)   # its key in the current formula (upgrade_keys)
            print(f'  {m}: unchanged, kept'); continue
        todo[m] = (src, key)
    for m in todo: (out / f'{m}.android.key').unlink(missing_ok=True)   # every module to rewrite is unfinished from here on: no mix of old and new modules passes
    if in_process:
        for m, (src, key) in todo.items():
            kf = out / f'{m}.android.key'; kf.unlink(missing_ok=True)
            shutil.rmtree(staging(out, m), ignore_errors=True)
            print(f'  {m}: rewriting {src} (in process)', flush=True)
            t0 = time.monotonic()
            rc = run_in_process(REPO / 'dm/tools/patch_nso.py', [str(rewriter_src(src, out, m, mods.get(m, ()))), staging(out, m), m, '--target', 'android'], {'DM_GAME': g.id, 'DM_REWRITE_J': '1'}, out / f'rewrite_{m}.log')
            if rc:
                tail = (out / f'rewrite_{m}.log').read_text(errors='replace').splitlines()[-20:]
                raise Error(f'patch_nso.py exit code {rc} on {m}:\n' + '\n'.join(tail))
            swap_in(out, m, key)
            print(f'  {m}: done ({time.monotonic() - t0:.1f} s)', flush=True)
        return
    procs = {}
    try:
        pending = list(todo)
        while pending or procs:
            while pending and len(procs) < jobs:
                m = pending.pop(0); kf = out / f'{m}.android.key'; kf.unlink(missing_ok=True); shutil.rmtree(staging(out, m), ignore_errors=True)
                print(f'  {m}: rewriting {todo[m][0]}', flush=True)
                log = open(out / f'rewrite_{m}.log', 'w')
                procs[m] = (subprocess.Popen([py, str(REPO / 'dm/tools/patch_nso.py'), str(rewriter_src(todo[m][0], out, m, mods.get(m, ()))), str(staging(out, m)), m, '--target', 'android'], env=env, stdout=log, stderr=subprocess.STDOUT), log)
            for m in list(procs):
                p, log = procs[m]
                if p.poll() is None: continue
                log.close(); del procs[m]
                if p.returncode:
                    tail = (out / f'rewrite_{m}.log').read_text(errors='replace').splitlines()[-20:]
                    raise Error(f'patch_nso.py exit code {p.returncode} on {m}:\n' + '\n'.join(tail))
                swap_in(out, m, todo[m][1])
                print(f'  {m}: done', flush=True)
            if procs: time.sleep(0.2)
    finally:
        for p, log in procs.values():
            if p.poll() is None: p.terminate(); p.wait()
            log.close()


VK_BUILD = REPO / 'dm/gfx/tools/vk_android_build.py'
SPLIT = REPO / 'dm/gfx/tools/shader_split.py'
VK_LIB, VK_PREFIX = 'dmsh_vk.lib', 'v-'   # dmsh_abi_vk.h DMSH_VK_LIB_FILE / DMSH_VK_DIR_PREFIX


def vk_chain():   # DMSH_VK_CHAIN of this source tree, as the host is compiled with (dm/gfx/nvn/dmsh_chain_vk.h)
    import re
    m = re.search(r'#define DMSH_VK_CHAIN "([0-9a-f]+)"', (REPO / 'dm/gfx/nvn/dmsh_chain_vk.h').read_text())
    if not m: raise Error('dm/gfx/nvn/dmsh_chain_vk.h has no DMSH_VK_CHAIN')
    return m.group(1)


def shader_python(want, split=False):
    """A Python that can run vk_android_build.py (zstd: Python 3.14's compression.zstd or backports.zstd), or with split shader_split.py (zstd and lz4; this one first)"""
    cands = [want] if want else ([sys.executable] if split else []) + [shutil.which('python3.14'), shutil.which('python3'), sys.executable]
    test = 'import sys\ntry: from compression import zstd\nexcept ImportError: from backports import zstd' + ('\nimport lz4.block' if split else '')
    for py in filter(None, cands):
        r = subprocess.run([py, '-c', test], capture_output=True)
        if r.returncode == 0: return py
    raise Error(f'no Python with zstd{" and lz4" if split else ""} for {"shader_split.py" if split else "vk_android_build.py"} among {", ".join(filter(None, cands))}: '
                'use the environment of android/README.md or pass --shader-python')


def lib_stamp(lib_dir):
    """{'game', 'inputs'} of a library directory: its inputs.tsv, else the library's own header (game and inputs fields, dmsh_abi_vk.h), which a library copied
    without its inputs.tsv still carries"""
    st = dmsh_chain.read_stamp(str(lib_dir))
    if st: return st
    try: h = (lib_dir / VK_LIB).open('rb').read(72)
    except OSError: return {}
    return {'game': h[40:56].rstrip(b'\0').decode(errors='replace'), 'inputs': h[56:72].rstrip(b'\0').decode(errors='replace')} if len(h) == 72 else {}


def library_current(lib_dir, g):
    """True when lib_dir holds a finished full library of this game and its profile's current inputs"""
    st = lib_stamp(lib_dir)
    return (lib_dir / VK_LIB).is_file() and st.get('game') == g.id and st.get('inputs') == dmsh_chain.inputs(g)


def map_keys(path):
    """The keys of a shader_map.tsv (column 4 of its package rows)"""
    with open(path) as f: return {c[3] for c in (l.rstrip('\n').split('\t') for l in f) if len(c) > 4 and c[0].endswith('.bin')}


def split_shaders(a, g, vdir, pkg):
    """The Switch shader package from the dump, as the phone's split step makes it (the version's romfs and main, android/app PackService "split"): shader_split.py into
    <pkg> (written beside it, then renamed, so a stopped split leaves no half package). Its tables go beside the package. The library is the profile's (its shader_map.tsv
    decides what is built, and vk_android_build.py finds each of its shaders in the package by key), so the split must hold every shader of the profile's map: one that
    lacks any (a dump of another version, or incomplete) stops here"""
    py = shader_python(a.shader_python, split=True)
    tmp = pkg.with_name(pkg.name + '.tmp'); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    rom = pack_dump.romfs_of(vdir) or vdir / 'romfs'
    print(f'shaders: splitting the shaders out of {rom} into {pkg} with {py} (a few minutes)', flush=True)
    env = dict(os.environ, DM_GAME=g.id)
    r = subprocess.run([py, str(SPLIT), str(rom), str(vdir / 'exefs' / 'main'), str(tmp / 'pkg'),
                        *[str(tmp / f) for f in ('shader_map.tsv', 'shader_facts.tsv', 'shader_pairs.tsv', 'pso_pairs.tsv')]], env=env)
    if r.returncode: raise Error(f'shader_split.py exit code {r.returncode}')
    if (g.dir / 'shader_map.tsv').is_file():
        want, have = map_keys(g.dir / 'shader_map.tsv'), map_keys(tmp / 'shader_map.tsv')
        if missing := sorted(want - have):
            raise Error(f'the dump\'s shaders lack {len(missing)} of the {len(want)} in the profile\'s shader_map.tsv (e.g. {", ".join(missing[:3])}): the dump is of another version '
                        f'or incomplete, and the profile\'s shader library cannot be built from it (the split is in {tmp})')
        for f in ('shader_map.tsv', 'shader_facts.tsv', 'shader_pairs.tsv'):
            if (g.dir / f).is_file() and (g.dir / f).read_bytes() != (tmp / f).read_bytes():
                print(f'shaders: the dump\'s {f} differs from the profile\'s ({len(have - want)} shaders more); the library is the profile\'s, its shaders found in the package by key')
    shutil.rmtree(pkg, ignore_errors=True); (tmp / 'pkg').rename(pkg)
    for f in tmp.iterdir(): f.replace(pkg.with_name(f.name))
    tmp.rmdir()


def pack_shaders(a, g, work, out, vdir):
    """shaders/v-<V>/ in the pack: an up-to-date library from the cache (built there first when it is missing or stale, from the shader package, split from the dump
    first when there is none and --shader-pkg names none). → the library path in the pack, or None"""
    v = vk_chain(); name = VK_PREFIX + v
    cache = (a.shader_cache or work / 'android-shaders' / 'lib').resolve(); lib = cache / name
    dst = out / 'shaders' / name
    if not library_current(lib, g):
        if a.in_process: raise Error(f'no current shader library {lib}: --in-process does not build one yet (vk_android_build.py starts the translator and spirv-val as programs); --no-shaders packs without')
        pkg = (a.shader_pkg or work / 'android-shaders' / 'pkg').resolve()
        if not pkg.is_dir(): split_shaders(a, g, vdir, pkg)   # also into a --shader-pkg folder that is not there yet
        py = shader_python(a.shader_python)
        print(f'shaders: building the Vulkan library {lib} from {pkg} with {py} (J={a.J}; about 10 minutes on DKB)', flush=True)
        (work / 'android-shaders' / 'work').mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, DM_GAME=g.id, J=str(a.J), WORK=str(work / 'android-shaders' / 'work'))
        # The Ocarina-specific shader_GMEM fast path is selected at translation
        # time, never in the running Vulkan driver; other games retain the
        # unchanged memory-pool binary search. The shader_* profile row is
        # included in dmsh_chain.inputs, so caches distinguish this build.
        fast = g.get('shader_gmem_fast', '0')
        if fast not in ('0', '1'):
            raise Error(f'{g.id}: shader_gmem_fast must be 0 or 1')
        env['DMSH_GMEM_FAST1'] = fast
        r = subprocess.run([py, str(VK_BUILD), '--target', 'vulkan', str(pkg), str(cache)], env=env)
        if r.returncode: raise Error(f'vk_android_build.py exit code {r.returncode} (a package that lacks the profile\'s shaders stops it: delete {pkg} and the split runs again)')
        if not library_current(lib, g): raise Error(f'vk_android_build.py finished but {lib} is not a full library of {g.id} with the current inputs')
    else: print(f'shaders: {lib} is current (game {g.id}, inputs {dmsh_chain.inputs(g)})')
    dst.mkdir(parents=True, exist_ok=True)
    if not (lib / dmsh_chain.STAMP).is_file():   # a library copied without its stamp: written from its header (library_current took it from there)
        st = lib_stamp(lib); dmsh_chain.write_stamp(str(lib), st['game'], st['inputs'])
    for f in (VK_LIB, dmsh_chain.STAMP):
        s_, d_ = lib / f, dst / f
        if d_.is_file() and d_.stat().st_size == s_.stat().st_size and d_.stat().st_mtime_ns == s_.stat().st_mtime_ns: continue
        tmp = d_.with_name(f + '.partial'); shutil.copy2(s_, tmp); tmp.rename(d_)
    others = sorted(o.name for o in (out / 'shaders').iterdir() if o.name != name and o.name.startswith(VK_PREFIX) and o.is_dir())
    if others:   # kept: another APK (the test and the play app, an older build) may load one of them from this pack; delete by hand to save the space
        print(f'shaders: kept the libraries of other versions in {out / "shaders"}: {", ".join(others)} (about 350 MB each)')
    return dst / VK_LIB


def commit():   # the packer's commit; DM_PACKER_COMMIT when the repository's tool has none (the phone: no git there, the app passes the commit it was built from)
    try: r = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True).stdout.strip()
    except OSError: r = ''
    return r or os.environ.get('DM_PACKER_COMMIT') or 'unknown'


def main():
    ap = argparse.ArgumentParser(description='Pack a dumped game for the Android launcher: its code modules rewritten with --target android, no RomFS')
    ap.add_argument('game', type=Path, help='the game folder (base/exefs, base/romfs or an update\'s romfs, updates/<version>/, dlc/), or a .nup file')
    ap.add_argument('--version', type=int, help='the update version to pack (default: the newest in updates/; 0 = the base game)')
    ap.add_argument('--out', type=Path, help='the pack folder (default: <game folder>/../<title ID>-work/android-pack)')
    ap.add_argument('-j', type=int, default=2, help='modules rewritten at once (default 2)')
    ap.add_argument('--shader-cache', type=Path, help='the folder of Vulkan shader libraries v-<V>/ (default: <title ID>-work/android-shaders/lib)')
    ap.add_argument('--shader-pkg', type=Path, help='the Switch shader package to build the library from, split from the dump into it when it is not there (default: <title ID>-work/android-shaders/pkg)')
    ap.add_argument('--shader-python', help='the Python 3.14 (or one with backports.zstd) that runs vk_android_build.py')
    ap.add_argument('-J', type=int, default=8, help='shaders translated at once when the library is built (default 8)')
    ap.add_argument('--no-shaders', action='store_true', help='make the pack without the shader library')
    ap.add_argument('--code-only', action='store_true', help='only rewrite the modules (the phone\'s rewrite step): pack.tsv, game.tsv and the shaders stay as they are')
    ap.add_argument('--keep-code', action='store_true', help='do not rewrite: the pack\'s modules must be there with their key files (the phone\'s pack step)')
    ap.add_argument('--in-process', action='store_true', help='run the rewriter in this process, no subprocesses (the phone\'s packer); the shader library must be current or left out')
    ap.add_argument('--mods', type=Path, default=os.environ.get('DM_MODS_DIR') or None, help='the mods folder: <DIR>/<title ID>/<mod>/exefs/<build ID>.ips or .pchtxt, applied before the rewrite (default: DM_MODS_DIR)')
    a = ap.parse_args()
    folder = a.game.resolve()
    try:
        try: import capstone, lz4.block   # noqa: F401  (patch_nso.py needs both; checked here so a missing one fails before any work)
        except ImportError as e: raise Error(f'{e.name} is missing in {sys.executable}: see android/README.md for the environment') from None
        if capstone.cs_version()[0] != 5: raise Error(f'Capstone {capstone.__version__}: the rewriter needs Capstone 5')
        app, vers, dlc = pack_dump.scan(folder)
        try: g = game.load(f'{app:016X}')
        except SystemExit: raise Error(f'no profile dm/games/{app:016X}: the Android pack needs one (build_ipa_from_nsp.py makes a provisional one)') from None
        ver = a.version if a.version is not None else max(vers, default=0)
        if ver and ver not in vers: raise Error(f'no updates/{ver} (have: {", ".join(map(str, sorted(vers))) or "none"})')
        vdir = pack_dump.version_dir(folder, vers, ver)
        exe, romfs = vdir / 'exefs', pack_dump.romfs_of(vdir)   # (romfs/, or a romfs.bin image: pack_dump.romfs_of)
        if not (exe / 'main.npdm').is_file() or romfs is None: raise Error(f'{vdir}: no exefs/main.npdm and romfs (a folder, or romfs.bin)')
        if (pid := pack_dump.program_id(exe / 'main.npdm')) != app: raise Error(f'{vdir}: program ID {pid:016X}, the base is {app:016X}')
        mods = g.words('modules')
        srcs = {m: exe / m for m in mods}
        if missing := [m for m in mods if not srcs[m].is_file()]: raise Error(f'{exe}: no {", ".join(missing)} (the profile\'s modules are {" ".join(mods)})')
        out = (a.out or folder.parent / f'{app:016X}-work' / 'android-pack').resolve()
        try: out.relative_to(REPO); raise Error(f'{out} is inside the repository: packs never go there')
        except ValueError: pass
        out.mkdir(parents=True, exist_ok=True)
        ids = {m: nso_build_id(srcs[m]) for m in mods}
        known = {m: i for v in g.builds().values() for m, i in v.items() if m != 'display'}
        print(f'{app:016X} {g.get("name", "?")} version {ver}: {vdir}', flush=True)
        for m in mods:
            if known.get(m) and known[m] != ids[m]: print(f'[RED] {m} build {ids[m]} is not the profile\'s build {known[m]}: build-gated cuts do not apply')
        # Exefs patches (mods) for each module's whole build ID, listed and checked against its segments here, before any key goes (exefs_patches.plan: a mod
        # for another build stops the run with the pack as it was), and applied to the modules that are rewritten (rewriter_src); --keep-code rewrites nothing
        patches = {}
        for m in (mods if a.mods and not a.keep_code and exefs_patches.mod_dirs(a.mods, f'{app:016X}') else ()):   # no folder for the title: nothing to read
            hdr = srcs[m].read_bytes()[:0x100]   # (a module in a .nup file is no plain file to open)
            if f := exefs_patches.find(a.mods, f'{app:016X}', hdr[0x40:0x60]):
                print(f'  {m}: exefs patches from {a.mods}: ' + ', '.join(label for label, _ in f), flush=True)
                exefs_patches.plan(hdr, f, m); patches[m] = f
        if a.keep_code:
            if missing := [m for m in mods if not (out / f'{m}.patched.bin').is_file() or not (out / f'{m}.android.key').is_file()]:
                raise Error(f'--keep-code: {out} has no complete {", ".join(missing)} (patched.bin and its key): rewrite first')
            upgrade_keys(srcs, out, g)   # before the copy below replaces the game.tsv an earlier key was made with (a rewrite run does it in rewrite)
            print('  modules kept as they are (--keep-code)')
        else:
            try: rewrite(sys.executable, srcs, out, max(1, a.j), g, a.in_process, patches)
            finally: shutil.rmtree(out / '.nup-src', ignore_errors=True)   # the module copies a NUP game's rewrite read (rewriter_src)
        if a.code_only:
            # Android Prepare runs --code-only before --keep-code.
            # A fresh pack does not have game_profile.tsv yet.
            if g.id == '0400486024DEC000':
                rt_path = out / 'game_profile.tsv'
                if rt_path.is_file():
                    rt = rt_path.read_text(encoding='utf-8')
                else:
                    sysres = pack_dump.system_resource(exe / 'main.npdm')
                    cmask, ideal = pack_dump.thread_info(exe / 'main.npdm')
                    rt = game.runtime(g)
                    for row, value in (('SYS_RESOURCE', sysres), ('CORE_MASK', cmask), ('IDEAL_CORE', ideal)):
                        pat = rf'^{row}\t[0-9]+$'
                        if len(re.findall(pat, rt, re.M)) != 1:
                            raise Error(f'Ocarina: no unique {row} in runtime profile')
                        rt = re.sub(pat, row + '\t' + str(value), rt, count=1, flags=re.M)
                new = rt
                for row, value in (('FPS_TARGET', '60'), ('FPS_HOLD', '0')):
                    pat = rf'^{row}\t[0-9]+$'
                    if len(re.findall(pat, new, re.M)) != 1:
                        raise Error(f'Ocarina: no unique {row} in runtime profile')
                    new = re.sub(pat, row + '\t' + value, new, count=1, flags=re.M)
                if not rt_path.is_file() or new != rt:
                    tmp = rt_path.with_name(rt_path.name + '.timing-partial')
                    tmp.write_text(new, encoding='utf-8', newline='\n')
                    tmp.replace(rt_path)
                    print('Ocarina: runtime profile prepared (FPS_TARGET=60 FPS_HOLD=0)', flush=True)
            print(f'done: the modules in {out} (--code-only: pack.tsv and the shaders unchanged)')
            return
        shutil.copyfile(g.dir / 'game.tsv', out / 'game.tsv')
        # The system resource is the packed version's NPDM's, as the kernel takes it on hardware (the host answers GetInfo 16 with it; non-zero turns on the SDK's virtual
        # address memory): a profile key that disagrees is a wrong guess (Zelda: Ocarina of Time's said 0 while its NPDM declares 48 MB, and the SDK's VammManager was null)
        sysres, prof = pack_dump.system_resource(exe / 'main.npdm'), int(g.get('sys_resource', '0x2000000'), 0)
        if sysres != prof: print(f'[RED] the profile\'s sys_resource {prof:#x} is not the NPDM\'s {sysres:#x}: the pack takes the NPDM\'s (check the profile\'s memory layout: mem_alias holds virtual address memory)')
        # The cores are the NPDM's too (its ThreadInfo: the core mask GetInfo(CoreMask) answers, and META's ideal core): a Switch 2 application has six (0x3f), and libraries
        # size their thread pools and per-core arrays by that mask (docs/reference/threads.md, "The process's cores")
        cmask, ideal = pack_dump.thread_info(exe / 'main.npdm')
        pmask, pideal = int(g.get('core_mask', '0x7'), 0), int(g.get('ideal_core', '0'), 0)
        if (cmask, ideal) != (pmask, pideal): print(f'[RED] the profile\'s core_mask {pmask:#x} / ideal_core {pideal} are not the NPDM\'s {cmask:#x} / {ideal}: the pack takes the NPDM\'s')
        rt = game.runtime(g)
        for row in ('SYS_RESOURCE', 'CORE_MASK', 'IDEAL_CORE'):
            if not re.search(rf'^{row}\t', rt, re.M): raise Error(f'game.runtime wrote no {row} row')
        for row, v in (('SYS_RESOURCE', sysres), ('CORE_MASK', cmask), ('IDEAL_CORE', ideal)): rt = re.sub(rf'^{row}\t\d+$', f'{row}\t{v}', rt, flags=re.M)
        (out / 'game_profile.tsv').write_text(rt, encoding='utf-8', newline='\n')   # the profile the host reads at start (dm/host/rt/game_rt.c)
        shaders = None if a.no_shaders else pack_shaders(a, g, folder.parent / f'{app:016X}-work', out, vdir)
        top = folder.parent if pack_dump.nup.is_nup(folder) else folder   # a NUP file's paths are `<name>.nup:<package>/...`, relative to its folder
        rel = lambda p: p.relative_to(top).as_posix()
        rows = [('format', str(FORMAT)), ('title_id', f'{app:016X}'), ('name', g.get('name', '')), ('version', str(ver)), ('target', 'android'),
                ('modules', ' '.join(mods)), *[('build', f'{m}={ids[m]}') for m in mods], ('romfs', rel(romfs)),
                *[('aoc', f'{tid - app - 0x1000}\t{rel(p)}') for tid, p in sorted(dlc.items())],
                *([('shaders', shaders.relative_to(out).as_posix())] if shaders else []), ('packer', commit())]
        tmp = out / 'pack.tsv.partial'
        tmp.write_text(''.join(f'{k}\t{v}\n' for k, v in rows)); tmp.rename(out / 'pack.tsv')
        size = sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    except (Error, pack_dump.Error, exefs_patches.Error) as e: sys.exit(f'[RED] {e}')
    print(f'done: {out} ({size / 2**20:.1f} MiB); RomFS {rel(romfs)} and {len(dlc)} DLC stay in the game folder')


if __name__ == '__main__':
    main()
