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


def generate(romfs_root, output_dir, log=print):
    """Search only graphics-param .bgyml assets in player's selected RomFS."""
    root = romfs_root.rstrip('/\\')
    inspected = 0
    matched = []
    for group in SEARCH_ROOTS:
        folder = root + '/' + group
        try:
            iterator = romfs.walk(folder)
            for dirname, _dirs, filenames in iterator:
                for filename in filenames:
                    if not filename.endswith('.bgyml'):
                        continue
                    rel = (dirname + '/' + filename)[len(root) + 1:]
                    # Do not edit UI/gameplay materials or arbitrary unrelated assets.
                    if not any(x in rel.lower() for x in ('env', 'bloom', 'dof', 'post', 'modelscene')):
                        continue
                    inspected += 1
                    if inspected > 3000:
                        raise Error('too many post parameter files; unsafe to guess')
                    with romfs.open(root + '/' + rel, 'rb') as f:
                        buf = f.read(MAX_FILE + 1)
                    try:
                        after, categories = patch_byml(buf)
                    except (ValueError, IndexError, struct.error):
                        continue  # not a recognized graphics BYML
                    if categories:
                        matched.append((rel, after, categories))
        except OSError:
            continue
    families = set().union(*(cat for _, _, cat in matched)) if matched else set()
    if families != {'bloom', 'dof'}:
        raise Error('post effect commands not independently identified in this update '
                    '(found: %s; required bloom+dof). No unsafe Create flags disabled.' %
                    (', '.join(sorted(families)) or 'none'))
    for rel, buf, categories in matched:
        path = os.path.join(output_dir, *rel.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(buf)
        log('effect %s: resource retained, control parameters adjusted: %s' %
            ('/'.join(sorted(categories)), rel))
    return len(matched)
