#!/usr/bin/env python3
"""Fail-closed SSAO cost experiment from the player's active update's named BYML fields.

Unlike CreateSsocclusion=0, this retains the original SSAO allocations and
shadow-prepass output. Only a verified per-scene alchemy sample-pair integer
may be changed. No candidate => error, NEVER a fake successful patch.
"""
import os
import struct

from gsys_dynres import Byml, CONTAINERS, D_INT
import romfs

DIRECTORY = 'gsys/ModelSceneShadowParam'
KEY = 'AlchemySamplePairNum'  # exact field in user's NUP v131072 diagnostics
SOURCE_PAIRS = (3, 5)  # Both observed in the actual v131072 per-scene SSAO files.
TRIAL_PAIRS = 2
MAX_FILE = 2 * 1024 * 1024


class Error(ValueError):
    pass


def patch_byml(source):
    """Return (patched bytes, number of scalars), never editing unrelated BYML bytes."""
    if not 20 < len(source) <= MAX_FILE:
        raise Error('SSAO parameter file size invalid')
    raw = bytearray(source)
    by = Byml(raw, 0)
    if by.e != '<' or not 0 < by.root < len(raw) - 4:
        raise Error('unsupported SSAO parameter BYML endian/root')
    locations, visited = [], set()

    def visit(node, depth, in_ssao=False):
        if depth > 24 or node in visited:
            return
        if node < 0 or node + 4 > len(raw):
            raise Error('SSAO BYML node out of bounds')
        visited.add(node)
        for name, kind, word in by.items(node):
            if word < 0 or word + 4 > len(raw):
                raise Error('SSAO BYML scalar out of bounds')
            if name == KEY and in_ssao:
                if kind != D_INT:
                    raise Error('unexpected SSAO sample-pair field type')
                actual = struct.unpack_from('<i', raw, word)[0]
                if actual in SOURCE_PAIRS:
                    locations.append((word, actual))
                elif actual == TRIAL_PAIRS:
                    pass   # scene is already at the safe 2-pair target; leave unchanged
                else:
                    raise Error('unexpected original SSAO sample-pair count: %d' % actual)
            elif kind in CONTAINERS:
                visit(by.u32(word), depth + 1, in_ssao or name == 'SSAO')

    visit(by.root, 0)
    if len({word for word, _old in locations}) != len(locations):
        raise Error('duplicate SSAO scalar offset')
    for word, _old in locations:
        struct.pack_into('<i', raw, word, TRIAL_PAIRS)
    differing = {i for i, (a, b) in enumerate(zip(source, raw)) if a != b}
    allowed = {i for o, _old in locations for i in range(o, o + 4)}
    if (locations and (not differing or not differing <= allowed)) or (not locations and differing):
        raise Error('SSAO patch modified unknown bytes')
    return bytes(raw), len(locations)


def generate(root, out, log=print):
    """Discover the per-scene graphics settings in the active NUP; write only if validated."""
    root = root.rstrip('/\\')
    folder = root + '/' + DIRECTORY
    matched = []
    try:
        with romfs.scandir(folder) as entries:
            names = sorted(e.name for e in entries if e.is_file() and e.name.endswith('.bgyml'))
    except OSError as e:
        raise Error('SSAO model-scene configuration folder unavailable: ' + str(e)) from e
    if not names or len(names) > 128:
        raise Error('unrecognized SSAO model-scene configuration layout')
    for name in names:
        stage = os.path.join(out, DIRECTORY, name)
        if os.path.isfile(stage):
            # Preserve a previously generated DOF/Bloom edit in this same BYML.
            with open(stage, 'rb') as f:
                original = f.read(MAX_FILE + 1)
        else:
            with romfs.open(folder + '/' + name, 'rb') as f:
                original = f.read(MAX_FILE + 1)
        patched, num = patch_byml(original)
        if num:
            matched.append((name, patched, num))
    if not matched:
        raise Error('no SSAO/AlchemySamplePairNum 3 or 5 found to reduce; no patch written')
    # Only now commit the files; the Android preparer works in a private .tmp
    # folder and publishes an overlay only after the generator succeeds.
    for name, patched, num in matched:
        target = os.path.join(out, DIRECTORY, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(patched)
        log('SSAO sample pairs: %s reduced %d field%s (allowed originals 3 or 5, target %d)' %
            (name, num, '' if num == 1 else 's', TRIAL_PAIRS))
    return sum(n for _, _, n in matched)
