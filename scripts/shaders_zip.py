#!/usr/bin/env python3
"""A game's translated Android shader library as a shaders zip, the computer's side of the launcher's Import shaders… (android/SHADERS.md "Shader zips"):
translate on the computer (scripts/pack_android.py, vk_android_build.py), carry the zip to the phone (Switch2/Shaders or Download), and the phone translates none.

    python3 scripts/shaders_zip.py <library folder v-<V>> [--out DIR] [--pack DIR]

<library folder>: a v-<V> folder with dmsh_vk.lib (and its inputs.tsv): <work>/android-shaders/lib/v-<V> or <pack>/shaders/v-<V>. --pack: the pack folder made
from the same dump (its pack.tsv gives the game version for the zip's name and the build rows). --out: where the zip goes (default: beside the library folder).
The zip is the launcher's own layout (ShaderZip.java): STORED, manifest.tsv, inputs.tsv, dmsh_vk.lib in that order, named
swap2-shaders-<title ID>-<game version>-v-<V>.zip; written as <name>.partial, read back (names, order, sizes, SHA-256), then renamed. A zip of the same library
already there is kept. Only a phone app of the same shader version (DMSH_VK_CHAIN) imports it. Exits non-zero on any error.
"""
import argparse
import datetime
import hashlib
import os
import re
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAGIC, VERSION, HEADER = 0x4B56534D, 1, 128   # dm/gfx/nvn/dmsh_abi_vk.h DMSH_VK_LIB_MAGIC, DMSH_VK_LIB_VERSION, DMSH_VK_HEADER_SIZE
ENTRY, BIND, MOD = 64, 24, 16
LIB, INPUTS, MANIFEST = 'dmsh_vk.lib', 'inputs.tsv', 'manifest.tsv'
CHUNK = 1 << 20


class Error(Exception):
    pass


def text(h, off, n):
    return h[off:off + n].split(b'\0', 1)[0].decode('ascii', errors='replace')


def header(lib):
    """The library's header fields (dmsh_vk_header), checked: magic, format, the tables and the blob inside the file"""
    size = lib.stat().st_size
    with lib.open('rb') as f: h = f.read(HEADER)
    if len(h) < HEADER: raise Error(f'{lib} is {len(h)} bytes: not a shader library')
    magic, version = struct.unpack_from('<II', h, 0)
    if magic != MAGIC or version != VERSION: raise Error(f'{lib} is not a shader library this app reads (magic {magic:#x}, format {version})')
    ec, eo, bc, bo, mc, mo, blob_off, blob_size = struct.unpack_from('<IIIIIIQQ', h, 72)
    abi = text(h, 116, 12)
    r = {'chain': text(h, 8, 16), 'vk_chain': text(h, 24, 16), 'game': text(h, 40, 16), 'inputs': text(h, 56, 16), 'abi': abi if re.fullmatch('[0-9a-f]{12}', abi) else '',
         'entries': ec, 'size': size}
    for count, off, sz in ((ec, eo, ENTRY), (bc, bo, BIND), (mc, mo, MOD)):
        if count and (off < HEADER or off + count * sz > size): raise Error(f'{lib}: a table lies outside the file (cut short?)')
    if blob_off < HEADER or blob_off + blob_size > size: raise Error(f'{lib}: its blob lies outside the file (cut short?)')
    return r


def rows(data):
    out = {}
    for line in data.decode('utf-8', errors='replace').splitlines():
        if '\t' in line and not line.startswith('#'):
            k, v = line.split('\t', 1)
            out.setdefault(k, []).append(v.strip())
    return out


def one(r, k):
    return (r.get(k) or [''])[0]


def clean(s):
    return re.sub(r'[^0-9A-Za-z._-]', '_', s)


def game_name(title_id, pack_rows):
    if one(pack_rows, 'name'): return one(pack_rows, 'name')
    try:
        for line in (REPO / 'dm/games' / title_id / 'game.tsv').read_text(encoding='utf-8').splitlines():
            c = line.split('\t')
            if len(c) > 1 and c[0].strip() == 'name': return c[1].strip()
    except OSError:
        pass
    return title_id


def made_by():
    try:
        c = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True, timeout=20).stdout.strip()
        if c: return 'mac:' + c
    except (OSError, subprocess.SubprocessError):
        pass
    return 'computer'


def xlate_source():
    try:
        sys.path.insert(0, str(REPO / 'dm/gfx/tools'))
        import dmsh_chain   # noqa: E402 (the repository's tools)
        return dmsh_chain.xlate_source_sha()
    except Exception:   # informational only
        return ''


def digest(path):
    sha, crc = hashlib.sha256(), 0
    with path.open('rb') as f:
        while b := f.read(CHUNK):
            sha.update(b)
            crc = zlib.crc32(b, crc)
    return sha.hexdigest(), crc


def same_zip(z, sha, size):
    """Whether a zip already there holds this library (its manifest's SHA-256 and size)"""
    try:
        with zipfile.ZipFile(z) as zf:
            m = rows(zf.read(MANIFEST))
            return one(m, 'kind') == 'swap2-shaders' and one(m, 'lib_sha256') == sha and one(m, 'lib_size') == str(size) and zf.getinfo(LIB).file_size == size
    except (OSError, KeyError, zipfile.BadZipFile):
        return False


def free_name(out, name):
    f, base, k = out / name, name[:-4], 2
    while f.exists() or Path(str(f) + '.partial').exists():
        f, k = out / f'{base}-{k}.zip', k + 1
    return f


def stored(name):
    i = zipfile.ZipInfo(name, date_time=datetime.datetime.now().timetuple()[:6])
    i.compress_type = zipfile.ZIP_STORED
    return i


def make(lib_dir, out, pack):
    lib_dir = Path(lib_dir).resolve()
    lib = lib_dir / LIB
    if not lib_dir.name.startswith('v-') or not lib.is_file(): raise Error(f'{lib_dir} is not a library folder (v-<version> with {LIB})')
    v = lib_dir.name[2:]
    h = header(lib)
    if h['vk_chain'] != v: raise Error(f'{lib} is of version {h["vk_chain"]}, its folder says {v}')
    if not re.fullmatch('[0-9A-F]{16}', h['game']): raise Error(f'{lib} names the title {h["game"]!r}')
    st = lib_dir / INPUTS
    inputs = st.read_bytes() if st.is_file() else \
        f'# the game and the profile inputs this library was built from (dm/gfx/tools/dmsh_chain.py inputs)\ngame\t{h["game"]}\ninputs\t{h["inputs"]}\n'.encode()
    s = rows(inputs)
    if one(s, 'game').upper() != h['game'] or one(s, 'inputs') != h['inputs']:
        raise Error(f'{st} names {one(s, "game")} {one(s, "inputs")}, the library {h["game"]} {h["inputs"]}')
    pk = {}
    if pack:
        p = Path(pack) / 'pack.tsv'
        if not p.is_file(): raise Error(f'{pack} has no pack.tsv')
        pk = rows(p.read_bytes())
        if one(pk, 'title_id').upper() != h['game']: raise Error(f'{p} is of {one(pk, "title_id")}, the library of {h["game"]}')
    game_version = one(pk, 'version')
    print(f'shaders_zip: hashing {lib} ({h["size"]:,} bytes, {h["entries"]:,} shaders)', flush=True)
    sha, crc = digest(lib)
    m = [('format', '1'), ('kind', 'swap2-shaders'), ('title_id', h['game']), ('name', game_name(h['game'], pk)), ('game_version', game_version)]
    m += [('build', b) for b in pk.get('build', [])]
    m += [('library_version', v), ('abi', h['abi']), ('chain', h['chain']), ('inputs', h['inputs']), ('shaders', str(h['entries'])), ('lib_size', str(h['size'])),
          ('lib_sha256', sha), ('inputs_sha256', hashlib.sha256(inputs).hexdigest()), ('app', made_by()), ('packer', one(pk, 'packer')), ('xlate_source', xlate_source()),
          ('made', datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))]
    manifest = ('# a game\'s translated shaders (android/SHADERS.md "Shader zips"): Import shaders… in the game\'s Options takes it\n'
                + ''.join(k + '\t' + re.sub(r'[\t\r\n]', ' ', x) + '\n' for k, x in m)).encode('utf-8')
    out = Path(out).resolve() if out else lib_dir.parent
    out.mkdir(parents=True, exist_ok=True)
    name = f'swap2-shaders-{clean(h["game"])}-{clean(game_version or "any")}-v-{clean(v)}.zip'
    if same_zip(out / name, sha, h['size']):
        print(f'shaders_zip: {out / name} is already there with the same library: kept')
        return out / name
    z = free_name(out, name)
    tmp = Path(str(z) + '.partial')
    try:
        with open(tmp, 'wb') as fo:
            with zipfile.ZipFile(fo, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:
                zf.writestr(stored(MANIFEST), manifest)
                zf.writestr(stored(INPUTS), inputs)
                info = stored(LIB)
                info.file_size = h['size']
                with lib.open('rb') as src, zf.open(info, 'w', force_zip64=h['size'] >= 0xFFFFFFFF) as dst:
                    while b := src.read(CHUNK): dst.write(b)
            fo.flush()
            os.fsync(fo.fileno())
        # read back: the launcher's names, order and method, the library's size, CRC and SHA-256
        with zipfile.ZipFile(tmp) as zf:
            infos = zf.infolist()
            if [i.filename for i in infos] != [MANIFEST, INPUTS, LIB] or any(i.compress_type != zipfile.ZIP_STORED for i in infos):
                raise Error(f'{tmp}: not the layout the launcher reads ({[i.filename for i in infos]})')
            li = zf.getinfo(LIB)
            if li.file_size != h['size'] or li.CRC != crc: raise Error(f'{tmp}: the library entry does not match {lib}')
            back = hashlib.sha256()
            with zf.open(LIB) as f:
                while b := f.read(CHUNK): back.update(b)
            if back.hexdigest() != sha: raise Error(f'{tmp}: the library read back is not {lib}')
        os.replace(tmp, z)
    finally:
        if tmp.exists(): tmp.unlink()
    print(f'shaders_zip: wrote {z} ({z.stat().st_size:,} bytes; {h["entries"]:,} shaders, version {v}), read back. On the phone: put it in Switch2/Shaders (or Download), '
          f'then the game\'s Options > Import shaders... (an app with shader version {v})')
    return z


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('lib_dir', help='the library folder, v-<version> with dmsh_vk.lib')
    ap.add_argument('--out', help='where the zip goes (default: beside the library folder)')
    ap.add_argument('--pack', help='the pack folder made from the same dump (its pack.tsv: the game version and builds)')
    a = ap.parse_args()
    try:
        make(a.lib_dir, a.out, a.pack)
    except (Error, OSError, zipfile.BadZipFile) as e:
        print(f'[RED] shaders_zip: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
