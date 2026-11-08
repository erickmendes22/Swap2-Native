#!/usr/bin/env python3
"""Exefs patches (mods): IPS, IPS32 and IPSwitch .pchtxt files applied to a code module's image before the rewriter reads it (scripts/pack_android.py).
The files are selected and applied as the Switch's mod loaders do (Atmosphere's exefs_patches, yuzu and Eden's load/<title ID>/<mod>/exefs):
  · Layout, under a mods folder: <mods>/<title ID>/<mod>/exefs/<files> (yuzu / Eden), and <mods>/<title ID>/exefs_patches/<mod>/<files> (Atmosphere's
    exefs_patches/<mod>, under the title's folder here). The title folder and the exefs folder are matched in any case. A mod folder whose name starts with '-'
    is disabled (rename it to turn it off). Mods are applied in the order of their names, and each mod's files in the order of theirs.
  · A .ips file is for the module whose build ID its name is: the name up to its first '.', 1..64 hex digits in any case, padded with zeros to 64, equals the
    module's whole 0x20-byte build ID (a name of 40 digits, a 20-byte GNU build ID, matches a module whose last 12 bytes are zero). A .pchtxt file is for the
    build ID of its @nsobid- line, matched the same way.
  · Offsets: an IPS offset counts from the start of the NSO file's 0x100-byte header, so module offset = IPS offset - 0x100; bytes that fall in the header
    are ignored (both loaders restore it). A .pchtxt offset is that IPS offset minus its @flag offset_shift (default 0, as in the reference parsers; most files
    say `@flag offset_shift 0x100` and give module offsets).
  · Bounds: a write must lie inside one segment as Horizon maps it: text and ro up to their last page (the page tail past a segment's size is mapped with it,
    and mods put code caves there), data up to the end of bss. A write past those is an Error, never a partial patch; a write that crosses a segment boundary
    too. A segment grows to cover what was written into its page tail or into bss (the rewriter then sees that code: a code cave's svc and mrs cntpct_el0
    become host gates like the module's own).
  · IPS: 'PATCH', records of a 24-bit offset, a 16-bit size and the bytes, or size 0 and a 16-bit count and one byte (RLE), then 'EOF' (the optional 3-byte
    truncation size after it has no meaning for a module and is ignored). IPS32: 'IPS32', 32-bit offsets, 'EEOF'. A file without its end marker is an Error.
  · .pchtxt (IPSwitch, as Eden's parser reads it): lines, leading space and comments ('/' or '#' outside quotes, to the end of the line) removed;
    @nsobid-<hex>, @enabled / @disabled (each starts a patch; lines of a disabled one are skipped, lines before any are ignored), @flag offset_shift <n>
    (C notation: 0x100, 256), @stop (ends the file); other @ lines (@flag print_values, @little-endian, @big-endian) change nothing here, as there (the
    reference parsers' hex bytes are in file order either way). A patch line is '<hex offset> <hex bytes>' or '<hex offset> "string"' (also single quotes;
    escapes \\a \\b \\e \\f \\n \\r \\t \\v, any other escaped character as itself; no terminating zero is added).
The digest of a module's patch files (digest) goes into its pack key, so adding, removing, disabling or changing a mod rewrites that module only; the
launcher computes the same (android/app/src/main/java/dev/nxnative/android/ExefsMods.java: same selection, same order, same digest).
Usage on its own: exefs_patches.py <mods folder> <title ID> <module (NSO)> [<out NSO>]   (lists the module's patches; with <out NSO>, writes the patched module)"""
import hashlib, re, struct, sys
from pathlib import Path
from typing import NamedTuple
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nso

HEADER = 0x100   # the NSO header, which IPS offsets count
PAGE = 0x1000
EXTS = ('.ips', '.pchtxt')


class Error(ValueError):
    pass


class Record(NamedTuple):
    offset: int   # from the start of the NSO header (IPS convention)
    data: bytes


def parse_ips(b, name='patch'):
    """[Record] of an IPS ('PATCH' … 'EOF') or IPS32 ('IPS32' … 'EEOF') file's bytes"""
    if b[:5] == b'IPS32': width, end = 4, b'EEOF'
    elif b[:5] == b'PATCH': width, end = 3, b'EOF'
    else: raise Error(f'{name}: not an IPS or IPS32 file (magic {bytes(b[:5])!r})')
    out, at = [], 5
    while True:
        if at + width > len(b): raise Error(f'{name}: no {end.decode()} marker (the file ends at {len(b):#x}): cut short or damaged')
        if b[at:at + width] == end: return out
        off = int.from_bytes(b[at:at + width], 'big'); at += width
        if at + 2 > len(b): raise Error(f'{name}: the record at file offset {at - width:#x} is cut short')
        size = int.from_bytes(b[at:at + 2], 'big'); at += 2
        if size == 0:   # RLE: a count and one byte
            if at + 3 > len(b): raise Error(f'{name}: the RLE record at file offset {at - width - 2:#x} is cut short')
            count = int.from_bytes(b[at:at + 2], 'big'); out.append(Record(off, bytes([b[at + 2]]) * count)); at += 3
        else:
            if at + size > len(b): raise Error(f'{name}: the record at file offset {at - width - 2:#x} has {size} bytes, past the end of the file')
            out.append(Record(off, bytes(b[at:at + size]))); at += size


def lines(b):
    """A text file's lines (bytes as Latin-1, split at \\n and \\r), as the IPSwitch parsers take them"""
    return re.split(r'[\r\n]', b.decode('latin-1'))


def pchtxt_build_id(b):
    """The build ID (64 hex digits, lowercase) a .pchtxt file is for: the hex digits after '@nsobid-' of its last @n… line before any @s… line (@stop),
    padded with zeros; None without one. ExefsMods.pchtxtBuildId reads it the same way"""
    bid = None
    for raw in lines(b):
        ln = strip_line(raw)
        if len(ln) <= 2 or ln[0] != '@': continue
        if ln[1] in 'sS': break
        if ln[1] in 'nN': bid = pad(re.match(r'[0-9a-fA-F]*', ln[8:]).group())
    return bid


def pad(h):
    return (h.lower() + '0' * 64)[:64]


def strip_line(s):
    """A .pchtxt line without its leading space and its comment ('/' or '#' outside quotes), and without trailing space"""
    s = s.lstrip(' \t\v\f'); quote, i, end = '', 0, 0
    while i < len(s):
        c = s[i]
        if c in ' \t\v\f': i += 1; continue
        if not quote and c in '/#': break
        if c in '"\'': quote = '' if quote == c else (quote or c); i += 1
        elif c == '\\' and i + 1 < len(s): i += 2
        else: i += 1
        end = i
    return s[:end]


ESC = {'a': '\a', 'b': '\b', 'e': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v'}


def parse_pchtxt(b, name='patch'):
    """(build ID or None, [Record]) of an IPSwitch .pchtxt file's bytes: the records of its enabled patches, offsets plus offset_shift (IPS convention)"""
    shift, enabled, out, warn = 0, None, [], []
    for n, raw in enumerate(lines(b), 1):
        ln = strip_line(raw)
        if not ln: continue
        if ln[0] == '@' and len(ln) > 2:
            k = ln[1].lower()
            if k == 's': break
            if k == 'e': enabled = True
            elif k == 'd': enabled = False
            elif k == 'f' and ln.lower().startswith('@flag offset_shift'):
                try: shift = int(ln[19:].strip(), 0)
                except ValueError: raise Error(f'{name}:{n}: offset_shift {ln[19:].strip()!r} is not a number') from None
            continue
        if enabled is None: warn.append(n); continue
        m = re.match(r'([0-9a-fA-F]+)', ln)
        if not m: raise Error(f'{name}:{n}: {ln!r} is not "<hex offset> <hex bytes>" nor "<hex offset> \\"string\\""')
        off = int(m.group(1), 16) + shift
        q = next((i for i, c in enumerate(ln) if c in '"\''), None)
        if q is not None:
            j, s = q + 1, ''
            while j < len(ln) and ln[j] != ln[q]:
                if ln[j] == '\\' and j + 1 < len(ln): s += ESC.get(ln[j + 1], ln[j + 1]); j += 2
                else: s += ln[j]; j += 1
            data = s.encode('latin-1')
        else:
            tok = re.split(r'[ \t]', ln); h = tok[-1]
            if len(tok) < 2 or not re.fullmatch(r'(?:[0-9a-fA-F]{2})+', h): raise Error(f'{name}:{n}: {ln!r}: the bytes are not an even number of hex digits')
            data = bytes.fromhex(h)
        if enabled: out.append(Record(off, data))
    if warn: print(f'  {name}: lines {", ".join(map(str, warn[:8]))}{"…" if len(warn) > 8 else ""} come before any @enabled or @disabled: ignored, as IPSwitch ignores them')
    return pchtxt_build_id(b), out


def parse(path, data=None):
    """[Record] of a patch file by its extension"""
    data = Path(path).read_bytes() if data is None else data
    if Path(path).suffix.lower() == '.ips': return parse_ips(data, str(path))
    return parse_pchtxt(data, str(path))[1]


def child(d, name):
    """d's subfolder called name in any case (the first by name when several are), or None"""
    try: c = sorted((p for p in d.iterdir() if p.is_dir() and p.name.lower() == name.lower()), key=lambda p: p.name)
    except OSError: return None
    return c[0] if c else None


def mod_dirs(root, title_id):
    """[(label, folder of patch files)] for the title, in order: <mod>/exefs for each mod, and exefs_patches/<mod> (Atmosphere) in the same order of names"""
    t = child(Path(root), title_id) if root and Path(root).is_dir() else None
    if t is None: return []
    out = []
    for m in sorted((p for p in t.iterdir() if p.is_dir()), key=lambda p: p.name):
        if m.name.startswith('-'): continue
        if m.name.lower() == 'exefs_patches':
            out += [(f'{m.name}/{a.name}', a) for a in sorted((p for p in m.iterdir() if p.is_dir()), key=lambda p: p.name) if not a.name.startswith('-')]
        elif (e := child(m, 'exefs')) is not None:
            out.append((f'{m.name}/{e.name}', e))
    return out


def find(root, title_id, build_id):
    """[(label, path)] of the patch files for a module of build_id (bytes, 0x20; or its hex) under the mods folder root, in the order they apply"""
    want = pad(build_id.hex() if isinstance(build_id, (bytes, bytearray)) else build_id)
    out = []
    for label, d in mod_dirs(root, title_id):
        # A name that starts with '.' is skipped (a hidden file, macOS's ._ companions; Path('.pchtxt').suffix is '', which ExefsMods.ext would not agree with)
        for f in sorted((p for p in d.iterdir() if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in EXTS), key=lambda p: p.name):
            if f.suffix.lower() == '.ips':
                stem = f.name.split('.')[0]
                if not re.fullmatch(r'[0-9a-fA-F]{1,64}', stem) or pad(stem) != want: continue
            elif pchtxt_build_id(f.read_bytes()) != want: continue
            out.append((f'{label}/{f.name}', f))
    return out


def digest(files):
    """SHA-256 (hex) of the patch files: label, length and bytes of each, in order (ExefsMods.digest)"""
    h = hashlib.sha256()
    for label, f in files:
        b = Path(f).read_bytes()
        h.update(label.encode('utf-8') + b'\0' + str(len(b)).encode() + b'\0' + b)
    return h.hexdigest()


def layout(hdr, name='module'):
    """((memory offset, size) of text, ro and data, bss size) from an NSO header (its first 0x40 bytes)"""
    if len(hdr) < 0x40 or hdr[:4] != b'NSO0': raise Error(f'{name}: exefs patches apply to an NSO (an NRO is loaded at run time and has none)')
    return tuple(struct.unpack_from('<III', hdr, 0x10 + 0x10 * i)[1:] for i in range(3)), struct.unpack_from('<I', hdr, 0x3c)[0]


def spans(segments, bss):
    """[(start, limit)] a write may fill, by segment: text and ro up to their last page (not into the next segment), data up to the end of bss"""
    (t, ts), (r, rs), (d, ds) = segments
    up = lambda x: (x + PAGE - 1) & ~(PAGE - 1)
    return [(t, min(up(t + ts), r)), (r, min(up(r + rs), d)), (d, d + ds + bss)]


def plan(hdr, files, name='module'):
    """What the patch files write into the module whose NSO header is hdr: [(label, records, [(segment, module offset, bytes)])], in order. Every write is
    checked against the module's segments here (spans), so a mod for another build stops the rewrite before anything of the pack is changed"""
    segs, bss = layout(hdr, name)
    sp, out = spans(segs, bss), []
    for label, f in files:
        recs, writes = parse(f), []
        for r in recs:
            a, b = r.offset - HEADER, r.offset - HEADER + len(r.data)
            if b <= 0: continue   # all in the header, which the loaders keep
            d = r.data[-a:] if a < 0 else r.data
            a = max(a, 0)
            seg = next((i for i, (s, e) in enumerate(sp) if s <= a < e), None)
            if seg is None or b > sp[seg][1]:
                where = ', '.join(f'{n} {s:#x}..{e:#x}' for n, (s, e) in zip(nso.NAMES, sp))
                raise Error(f'{label}: the record at {r.offset:#x} ({len(r.data)} bytes) writes {name}+{a:#x}..{b:#x}, '
                            + ('across a segment\'s end' if seg is not None else 'outside the module') + f' ({where}): is it for another build?')
            writes.append((seg, a, d))
        out.append((label, len(recs), writes))
    return out


def apply(data, files, name='module'):
    """The NSO file's bytes data with the patch files applied → (the patched module as an NSO file, [(label, records, bytes written)]). The NSO keeps its
    build ID and layout; its segments are stored uncompressed, with their hashes, and grow to cover writes into a page tail or bss"""
    p = plan(data[:HEADER], files, name)
    try: m = nso.load(data, name)
    except nso.Error as e: raise Error(str(e)) from None
    img, grow, report = bytearray(m.image), [sz for _, sz in m.segments], []
    for label, n, writes in p:
        for seg, a, d in writes:
            b = a + len(d)
            if b > len(img): img.extend(bytes(b - len(img)))
            img[a:b] = d
            grow[seg] = max(grow[seg], b - m.segments[seg][0])
        report.append((label, n, sum(len(d) for _, _, d in writes)))
    # The module as an NSO again: the header kept (build ID, module name, ro extents), segments uncompressed and checked by their SHA-256 (flags bits 3..5)
    hdr = bytearray(data[:HEADER])
    name_off, name_size = struct.unpack_from('<I', hdr, 0x1c)[0], struct.unpack_from('<I', hdr, 0x2c)[0]
    mname = bytes(data[name_off:name_off + name_size]) if name_size and name_off + name_size <= len(data) else b''
    struct.pack_into('<I', hdr, 0xc, 0x38)
    struct.pack_into('<I', hdr, 0x1c, HEADER); struct.pack_into('<I', hdr, 0x2c, len(mname))
    body, fo = bytearray(mname), HEADER + len(mname)
    for i, ((mo, _), sz) in enumerate(zip(m.segments, grow)):
        seg = bytes(img[mo:mo + sz])
        struct.pack_into('<III', hdr, 0x10 + 0x10 * i, fo, mo, sz); struct.pack_into('<I', hdr, 0x60 + 4 * i, sz)
        hdr[0xa0 + 0x20 * i:0xc0 + 0x20 * i] = hashlib.sha256(seg).digest()
        body += seg; fo += sz
    d_end_old, d_end = m.segments[2][0] + m.segments[2][1], m.segments[2][0] + grow[2]
    struct.pack_into('<I', hdr, 0x3c, max(0, d_end_old + m.bss - d_end))
    return bytes(hdr + body), report




def main():
    if len(sys.argv) not in (4, 5): sys.exit('usage: exefs_patches.py <mods folder> <title ID> <module (NSO)> [<out NSO>]')
    root, tid, src = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    try:
        data = src.read_bytes()
        files = find(root, tid, layout(data, str(src)) and data[0x40:0x60])
        if not files: print(f'{src}: no exefs patches for its build in {root}/{tid}'); return
        out, report = apply(data, files, src.name)
        for label, n, w in report: print(f'{label}: {n} records, {w} bytes')
        print('digest', digest(files))
        if len(sys.argv) == 5: Path(sys.argv[4]).write_bytes(out)
    except (Error, nso.Error, OSError) as e: sys.exit(f'[RED] {e}')


if __name__ == '__main__':
    main()
