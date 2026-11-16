#!/usr/bin/env python3
"""Resource-preserving scene post effects experiment for Ocarina v131072.

The old CreateDof=0/CreateBloom=0 pair crashes in original game code at
main+0xdbea1c because a required object is absent. NEVER edit those creation
flags. Instead try disabling per-effect commands *after* the objects exist,
using exact typed named properties. If the game build has no such properties
as ordinary RomFS BYML files, fail without publishing the overlay. Never
pretend the effect was disabled or the GPU workload reduced.
"""
import os
import struct

from gsys_dynres import Byml, CONTAINERS, D_FLOAT
import romfs

MAX_FILE = 2 * 1024 * 1024
# Restrict resource discovery to known graphics parameter namespaces.
SEARCH_ROOTS = (
    'agl',
    'gsys',
    'System/GameGraphics',
)
BLOOM_GROUPS = ('Bloom', 'BloomParam', 'BloomSettings')
DOF_GROUPS = ('Dof', 'DOF', 'DepthOfField', 'DepthOfFieldParam', 'DofParam')
# Classify only exact BYML field names and types, never substring matching.
# The game owns its render targets; values are effect commands, not the flags
# that allocate targets. Source values are validated against finite bounds.
BLOOM_FLOATS = ('BloomIntensity', 'BloomStrength')
DOF_FLOATS = ('DofIntensity', 'DofStrength', 'DofBlurRadius', 'DepthOfFieldIntensity')


class Error(ValueError):
    pass


def patch_byml(source):
    """Return (new bytes, modified effect tags), without touching any other data."""
    if not 20 <= len(source) <= MAX_FILE:
        raise Error('post-effect BYML size invalid')
    raw = bytearray(source)
    by = Byml(raw, 0)
    if by.e != '<' or not 0 < by.root < len(raw) - 4:
        raise Error('post-effect BYML must be LE with a valid root')
    visited, changes, categories = set(), {}, set()

    def walk(node, parents=(), depth=0):
        if node in visited or depth > 24:
            return
        if not 0 <= node <= len(raw) - 4:
            raise Error('post-effect node outside BYML')
        visited.add(node)
        for name, kind, word in by.items(node):
            if not 0 <= word <= len(raw) - 4:
                raise Error('post-effect scalar outside BYML')
            family = 'bloom' if name in BLOOM_FLOATS else 'dof' if name in DOF_FLOATS else ''
            if family and kind == D_FLOAT:
                value = struct.unpack_from('<f', raw, word)[0]
                if not (0.0 < value <= 100.0):
                    continue
                changes[word] = struct.pack('<f', 0.0)
                categories.add(family)
            elif (name == 'IsEnable' and kind == 0xd0 and
                  parents and parents[-1] in BLOOM_GROUPS + DOF_GROUPS):
                original = struct.unpack_from('<i', raw, word)[0]
                if original == 1:
                    changes[word] = struct.pack('<i', 0)
                    categories.add('bloom' if parents[-1] in BLOOM_GROUPS else 'dof')
            elif kind in CONTAINERS:
                walk(by.u32(word), parents + (name,), depth + 1)

    walk(by.root)
    for word, patched in changes.items():
        raw[word:word + 4] = patched
    changed_bytes = {i for i, (a,b) in enumerate(zip(source, raw)) if a != b}
    allowed = {i for off in changes for i in range(off, off + 4)}
    if changed_bytes - allowed:
        raise Error('post-effect data outside selected fields altered')
    return bytes(raw), categories


def generate(romfs_root, output_dir, log=print, scene_pack=None):
    """Edit AGL PMAA and/or BYML post params in RomFS, including SARC Bootup.

    The pack is read from the scene-resolution overlay if present, so an
    independent DOF/Bloom overlay never destroys a prepared 720p render scale.
    All candidates are staged in memory; both types must be identified before
    any file is published.
    """
    import oot_agl_pmaa as pmaa
    from gsys_dynres import (ZSTD_MAGIC, zsdic, decompress, compress,
                              sarc_files, frame_info)
    root = romfs_root.rstrip('/\\')
    matched = []
    categories = set()
    inspected = 0
    pmaa_found = []
    error_notes = []

    def effect_of(name):
        lower = name.lower()
        for suffix, family in (('.baglblm', 'bloom'), ('.bagldof', 'dof')):
            if lower.endswith(suffix):
                return family
        return None

    def try_pmaa(data, family, label):
        try:
            updated, n = pmaa.patch(data, family)
            if n:
                categories.add(family)
                log('AGL post resource preserved: %s, %s: %d typed controls changed' %
                    (family, label, n))
            return updated, n
        except pmaa.Error as e:
            error_notes.append('%s: %s' % (label, e))
            return data, 0

    # 1. Loose parameter files (BYML and AGL PMAA).
    for group in SEARCH_ROOTS:
        folder = root + '/' + group
        try:
            for dirname, _dirs, filenames in romfs.walk(folder):
                for filename in filenames:
                    family = effect_of(filename)
                    is_byml = filename.endswith('.bgyml')
                    if not family and not is_byml: continue
                    rel = (dirname + '/' + filename)[len(root) + 1:]
                    if is_byml and not any(x in rel.lower() for x in
                                           ('env', 'bloom', 'dof', 'post', 'modelscene')):
                        continue
                    inspected += 1
                    if inspected > 4000:
                        raise Error('too many effect configuration files')
                    with romfs.open(root + '/' + rel, 'rb') as fi:
                        buf = fi.read(MAX_FILE + 1)
                    if family:
                        updated, n = try_pmaa(buf, family, rel)
                        if n: matched.append((rel, updated))
                    else:
                        try:
                            updated, families = patch_byml(buf)
                        except (ValueError, IndexError, struct.error):
                            continue
                        if families:
                            categories.update(families)
                            matched.append((rel, updated))
        except OSError as e:
            error_notes.append('directory %s: %s' % (group, e))

    # 2. The game may place AGL PMAA in Bootup.Nin_Ounce_NVN2.pack.zs;
    # previously these files were not scanned at all.
    pack_name = 'Pack/Bootup.Nin_Ounce_NVN2.pack.zs'
    pack_result = None
    if categories != {'bloom', 'dof'}:
        try:
            if scene_pack:
                with open(scene_pack, 'rb') as fi:
                    compressed = fi.read(256 * 1024 * 1024 + 1)
                if not compressed:
                    raise Error('scene overlay pack empty')
            else:
                with romfs.open(root + '/' + pack_name, 'rb') as fi:
                    compressed = fi.read(256 * 1024 * 1024 + 1)
            if len(compressed) > 256 * 1024 * 1024:
                raise Error('Bootup pack exceeds bounded size')
            with romfs.open(root + '/Pack/ZsDic.pack.zs', 'rb') as fi:
                dictionary = zsdic(fi.read(64 * 1024 * 1024 + 1))
            declared_size, did, checksum = frame_info(compressed)
            if declared_size is not None and declared_size > 256 * 1024 * 1024:
                raise Error('expanded Bootup pack exceeds bounded size')
            raw = decompress(compressed, dictionary)
            if len(raw) > 256 * 1024 * 1024:
                raise Error('expanded Bootup pack too large')
            entries = sarc_files(raw)
            changed = bytearray(raw)
            named = [name for name in entries if effect_of(name)]
            log('Bootup AGL PMAA candidates: %d' % len(named))
            modified = 0
            for name in sorted(named):
                family = effect_of(name)
                if family in categories: continue
                offset, length = entries[name]
                if offset < 0 or length < 0 or offset + length > len(raw):
                    raise Error('SARC PMAA bounds invalid')
                piece = bytes(raw[offset:offset+length])
                after, n = try_pmaa(piece, family, 'Bootup:' + name)
                if n:
                    if len(after) != len(piece):
                        raise Error('SARC effect size changed')
                    changed[offset:offset+length] = after
                    modified += n
                    pmaa_found.append(name)
            if modified:
                result = compress(bytes(changed), dictionary, 19, checksum, did != 0)
                unpacked = decompress(result, dictionary)
                size2, did2, check2 = frame_info(result)
                if (unpacked != bytes(changed) or
                        size2 != len(changed) or did2 != did or check2 != checksum):
                    raise Error('Bootup AGL PMAA roundtrip failed')
                # No other SARC entry is edited, even when an existing scene
                # overlay pack was the source.
                for name, (offset, length) in entries.items():
                    if name not in pmaa_found and changed[offset:offset+length] != raw[offset:offset+length]:
                        raise Error('an unrelated SARC entry changed')
                pack_result = (pack_name, result)
        except (OSError, Error, ValueError, IndexError, struct.error) as e:
            error_notes.append('Bootup: ' + str(e))

    if categories != {'bloom', 'dof'}:
        raise Error('post effect controls not identified for both Bloom and DOF '
                    '(found: %s). Checked .bgyml + loose/packed .baglblm/.bagldof. '
                    'No unsafe Create flags changed. Details: %s' %
                    (','.join(sorted(categories)) or 'none',
                     '; '.join(error_notes[-5:]) or 'no matching parameter resources'))

    # Defer writes until *both* effects are identified; SceneService only
    # publishes the overlay when the full packer run returns success.
    for rel, buf in matched + ([pack_result] if pack_result else []):
        dest = os.path.join(output_dir, *rel.split('/'))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as fi: fi.write(buf)
    return len(matched) + (1 if pack_result else 0)
