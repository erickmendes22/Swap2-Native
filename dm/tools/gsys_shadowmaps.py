#!/usr/bin/env python3
"""Inspect and, only with verified named fields, reduce Ocarina's gsys shadow maps.

Game resources are NOT included in this repository. This program reads the
owner's RomFS without modifying it and writes a separate DM_ROMFS_OVERLAY file.
Until a real ModelSceneConfigParam/Main is inspected, the exact size fields,
whether they are hashed BYML fields and their offsets are NOT known: refuse
patching when they cannot be identified unambiguously.

Examples:
  python3 dm/tools/gsys_shadowmaps.py --romfs "/path/to/romfs" --inspect
  python3 dm/tools/gsys_shadowmaps.py --pack-file Bootup.Nin_Ounce_NVN2.pack.zs \
      --dict-file ZsDic.pack.zs --inspect
  python3 dm/tools/gsys_shadowmaps.py --romfs "/path/to/romfs" \
      --dynamic 512 --static 2048 --out /tmp/oot_shadow_overlay

If shadow parameters are in a different pack, use --pack; inspect reports
candidate .bgyml names. Never patch all 1024/4096 words indiscriminately.
"""
import argparse
import os
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gsys_dynres as g  # noqa: E402
import romfs  # noqa: E402

ID = '0400486024DEC000'
PACK = 'Pack/Bootup.Nin_Ounce_NVN2.pack.zs'
DIC = 'Pack/ZsDic.pack.zs'
NUMERIC = (0xd1, 0xd2, 0xd3)
NAMED_SIZE = re.compile(r'(size|width|height|resolution)', re.I)


def all_values(byml):
    """Yield (path, name, type, offset, value), including hash-key containers.
    A cycle/invalid-pointer guard is mandatory for game-controlled input.
    """
    seen = set()

    def walk(node, parents, depth):
        if depth > 64 or node in seen:
            return
        if node < 0 or byml.base + node + 4 > len(byml.b):
            raise g.Error('invalid BYML node offset')
        seen.add(node)
        for name, kind, off in byml.items(node):
            path = '/'.join(parents + [name])
            if kind in g.CONTAINERS:
                walk(byml.u32(off), parents + [name], depth + 1)
            elif kind in NUMERIC:
                if off + 4 > len(byml.b):
                    raise g.Error('scalar out of BYML bounds')
                fmt = ('f' if kind == 0xd2 else 'i' if kind == 0xd1 else 'I')
                value = struct.unpack_from(byml.e + fmt, byml.b, off)[0]
                yield_value.append((path, name, kind, off, value))
    yield_value = []
    walk(byml.root, [], 0)
    return yield_value


def inspect_pack(raw, log=print):
    files = g.sarc_files(raw)
    matches = [(name, o, n) for name, (o, n) in files.items()
               if 'ModelSceneConfigParam' in name and name.endswith('.bgyml')]
    if not matches:
        names = sorted(x for x in files if 'Shadow' in x or 'ModelScene' in x)
        raise g.Error('No ModelSceneConfigParam .bgyml in this pack; related entries: '
                      + (', '.join(names[:16]) or '(none)') + '. Find the pack holding gsys/ModelSceneConfigParam/Main.')
    result = []
    for name, off, length in matches:
        log('%s (pack+0x%x; %d bytes)' % (name, off, length))
        by = g.Byml(raw, off)
        for path, field, kind, loc, value in all_values(by):
            if 'shadow' in path.lower():
                log('  %s = %s (type=%02x, pack+0x%x)' % (path, value, kind, loc))
                result.append((name, path, field, kind, loc, value))
    if not result:
        raise g.Error('ModelSceneConfigParam has no visible named shadow subtree. '
                      'Hash-keyed paths must be mapped before editing; do not guess offsets.')
    return result


def select_fields(rows, dynamic=None, static=None):
    """Permit changing ONLY uniquely identified shadow-map dimension fields.
    Whitelist deliberately rejects #hash names until their semantic key is
    established against the user's exact v131072 game asset.
    """
    changes = {}
    targets = [('dynamic', dynamic, 1024, 'createdepthshadow'),
               ('static', static, 4096, 'createstaticdepthshadow')]
    for label, chosen, old, part in targets:
        if chosen is None:
            continue
        if chosen not in (256, 512, 1024, 2048, 4096) or chosen >= old:
            raise g.Error('%s target must be an exact smaller power-of-two map size' % label)
        candidates = [row for row in rows
                      if part in row[1].lower()
                      and not (label == 'dynamic' and 'createstaticdepthshadow' in row[1].lower())
                      and NAMED_SIZE.search(row[2])
                      and not row[2].startswith('#')
                      and row[3] in (0xd1, 0xd3)
                      and row[5] == old]
        if not 1 <= len(candidates) <= 12:
            raise g.Error('%s shadow dimensions are not uniquely proven: got %d named %dx%d values. '
                          'Inspect the real game pack before enabling a patch.'
                          % (label, len(candidates), old, old))
        # A second, unrelated size in the same subtree is a reason to stop.
        other = [row for row in rows
                 if part in row[1].lower()
                 and NAMED_SIZE.search(row[2])
                 and row[3] in (0xd1, 0xd3)
                 and row[5] != old]
        if other:
            raise g.Error('%s shadow subtree has other size values; refusing partial change: %s'
                          % (label, other[:4]))
        for _, path, _, kind, offset, _ in candidates:
            if offset in changes:
                raise g.Error('two shadow groups share a BYML offset')
            changes[offset] = (kind, chosen, path)
    if not changes:
        raise g.Error('no shadow sizes requested')
    return changes


def patch_raw(raw, changes):
    patched = bytearray(raw)
    for offset, (kind, size, _path) in changes.items():
        struct.pack_into('<I' if raw[6:8] == b'\xff\xfe' else '<I', patched, offset, size)
        # For these OOT packs, BYML is little-endian (YB); reject ambiguous
        # endian before calling patch_raw in the CLI.
    diff = {i for i, (a, b) in enumerate(zip(raw, patched)) if a != b}
    allowed = {i for off in changes for i in range(off, off + 4)}
    if len(raw) != len(patched) or not diff or not diff <= allowed:
        raise g.Error('modified bytes outside the validated shadow size fields')
    return bytes(patched)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--romfs', help='directory/image/NUP containing your own RomFS')
    parser.add_argument('--pack', default=PACK, help='romfs-relative pack to inspect')
    parser.add_argument('--zsdic', default=DIC, help='romfs-relative ZsDic pack')
    parser.add_argument('--pack-file', help='standalone compressed .pack.zs')
    parser.add_argument('--dict-file', help='standalone ZsDic.pack.zs or pack.zsdic')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--dynamic', type=int, help='dynamic shadow size (candidate 512)')
    parser.add_argument('--static', type=int, help='static shadow size (candidate 2048)')
    parser.add_argument('--out', help='separate overlay folder; original game data remains untouched')
    args = parser.parse_args(argv)
    try:
        if not args.romfs and not (args.pack_file and args.dict_file):
            raise g.Error('provide --romfs or both --pack-file and --dict-file')
        if (args.dynamic is not None or args.static is not None) and not args.out:
            raise g.Error('--out required to write a patch')
        if not args.inspect and args.dynamic is None and args.static is None:
            args.inspect = True
        if args.pack_file:
            packed = Path(args.pack_file).read_bytes()
            dicraw = Path(args.dict_file).read_bytes()
        else:
            root = args.romfs.rstrip('/\\')
            with romfs.open(root + '/' + args.pack, 'rb') as f:
                packed = f.read()
            with romfs.open(root + '/' + args.zsdic, 'rb') as f:
                dicraw = f.read()
        dic = g.zsdic(dicraw)
        expected_size, did, checksum = g.frame_info(packed)
        raw = g.decompress(packed, dic)
        if expected_size is not None and len(raw) != expected_size:
            raise g.Error('decompressed size mismatch')
        rows = inspect_pack(raw)
        if args.dynamic is None and args.static is None:
            return 0
        files = g.sarc_files(raw)
        names = [name for name in files if 'ModelSceneConfigParam' in name and name.endswith('.bgyml')]
        for name in names:
            off, _ = files[name]
            if g.Byml(raw, off).e != '<':
                raise g.Error('non-little-endian BYML: refuse this patch until verified')
        changes = select_fields(rows, args.dynamic, args.static)
        for offset, (_, size, name) in changes.items():
            print('PATCH confirmed %s -> %d (pack+0x%x)' % (name, size, offset))
        edited = patch_raw(raw, changes)
        new_frame = g.compress(edited, dic, 19, checksum, did != 0)
        size2, id2, _ = g.frame_info(new_frame)
        if size2 != len(raw) or id2 != did or g.decompress(new_frame, dic) != edited:
            raise g.Error('recompression/roundtrip failed')
        target = Path(args.out).joinpath(*args.pack.split('/'))
        if target.exists():
            raise g.Error('refusing overwrite of existing overlay: %s' % target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new_frame)
        print('Overlay created: %s (%d edited shadow size fields)' % (target, len(changes)))
        return 0
    except (g.Error, OSError, ValueError, struct.error, IndexError) as e:
        print('gsys_shadowmaps: ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
