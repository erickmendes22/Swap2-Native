#!/usr/bin/env python3
"""Testable Ocarina RomFS graphics patches on the active NUP update's own BYML.

Each FPS candidate changes the work selected by the game instead of changing
shadow-map dimensions. All candidates are opt-in and independent for A/B tests.
Unknown field layouts/values fail closed. The user's NUP is never modified.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import romfs
from gsys_dynres import Byml, D_INT

MAIN = 'gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml'
MAX_BYML = 2 * 1024 * 1024
D_BOOL = 0xD0
# 0 = original map sizes; retained previous shadow-map profiles for old users.
MAPS = {0: None, 1: (512, 2048), 2: (256, 1024)}
ORIGINAL_MAPS = {'DepthShadowTexWidth': 1024,
                 'DepthShadowTexHeight': 1024,
                 'StaticSdwWidth': 4096}
# Each effect is an isolated performance EXPERIMENT, not a claimed FPS gain.
# (name, BYML scalar type, expected original value, trial value)
EFFECTS = {
    0: (),
    1: (('DepthShadowCascadeNum0', D_INT, 3, 2),),
    2: (('DepthShadowCascadeNum0', D_INT, 3, 1),),
    3: (('CreateSsocclusion', D_BOOL, 1, 0),),
    4: (('CreateShadowPrePass', D_BOOL, 1, 0),),
    5: (('CreateDof', D_BOOL, 1, 0), ('CreateBloom', D_BOOL, 1, 0)),
}


class Error(Exception):
    pass


def selected_effects(mask):
    """0..31: two shadow-cascade choices are exclusive; all other effects stack."""
    if mask < 0 or mask > 31 or (mask & 3) == 3:
        raise Error('invalid FPS mask: cascading 3->2 and 3->1 cannot be combined')
    return [i for i in range(1, 6) if mask & (1 << (i - 1))]


def patch(source, profile, effect=0, effect_mask=None):
    if profile not in MAPS or effect not in EFFECTS or (profile == 0 and not effect and not effect_mask):
        raise Error('invalid or empty graphics patch profile')
    effects = [effect] if effect_mask is None else selected_effects(effect_mask)
    if not 20 <= len(source) <= MAX_BYML:
        raise Error('Main BYML size not accepted')
    raw = bytearray(source)
    by = Byml(raw, 0)
    if by.e != '<' or by.root <= 0 or by.root + 4 > len(raw) or raw[by.root] != 0xC1:
        raise Error('Main BYML root must be a little-endian named dictionary')
    changes = {}
    if profile:
        dyn, static = MAPS[profile]
        for name, target in (('DepthShadowTexWidth', dyn),
                             ('DepthShadowTexHeight', dyn),
                             ('StaticSdwWidth', static)):
            changes[name] = (D_INT, ORIGINAL_MAPS[name], target)
    for chosen_effect in effects:
        for name, kind, original, target in EFFECTS[chosen_effect]:
            if name in changes:
                raise Error('conflicting FPS effects on ' + name)
            changes[name] = (kind, original, target)
    words = {}
    for name, kind, word in by.items(by.root):
        if name not in changes:
            continue
        if name in words:
            raise Error('duplicate BYML field: ' + name)
        expected_kind, expected_value, target = changes[name]
        if kind != expected_kind or word < 0 or word + 4 > len(raw):
            raise Error('wrong BYML scalar type/offset for ' + name)
        if struct.unpack_from('<i', raw, word)[0] != expected_value:
            raise Error('unexpected original value for ' + name)
        words[name] = word
    if set(words) != set(changes):
        raise Error('missing expected graphics fields: ' + ', '.join(sorted(set(changes) - set(words))))
    for name, (_kind, _original, target) in changes.items():
        struct.pack_into('<i', raw, words[name], target)
    allowed = {word + k for word in words.values() for k in range(4)}
    differences = [i for i, (a, b) in enumerate(zip(source, raw)) if a != b]
    if not differences or any(i not in allowed for i in differences):
        raise Error('unexpected bytes changed')
    return bytes(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--romfs', required=True, help='RomFS of active update, including .nup:update/<version>/romfs')
    ap.add_argument('--profile', type=int, choices=sorted(MAPS), required=True, help='shadow map profile 0/1/2')
    ap.add_argument('--effect', type=int, choices=sorted(EFFECTS), default=0, help='legacy single effect 0..5')
    ap.add_argument('--effect-mask', type=int, default=None,
                    help='0..31 bitmask: 1 cascade2, 2 cascade1, 4 SSAO, 8 shadow prepass, 16 DOF+bloom')
    ap.add_argument('--out', required=True, help='new RomFS overlay directory')
    args = ap.parse_args(argv)
    try:
        src = args.romfs.rstrip('/\\') + '/' + MAIN
        with romfs.open(src, 'rb') as f:
            original = f.read(MAX_BYML + 1)
        updated = patch(original, args.profile, args.effect, args.effect_mask)
        target = os.path.join(args.out, *MAIN.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(updated)
        with open(target, 'rb') as f:
            if f.read() != updated:
                raise Error('written overlay did not verify')
        differing = sum(x != y for x, y in zip(original, updated))
        print('gsys_graphics: shadow %d, FPS patch %d: %s -> %s (%d scalar fields; %d changed bytes)' %
              (args.profile, args.effect, src, target,
               (3 if args.profile else 0) + sum(len(EFFECTS[e]) for e in
                 ([args.effect] if args.effect_mask is None else selected_effects(args.effect_mask))), differing))
        return 0
    except (Error, OSError, ValueError, IndexError, struct.error) as e:
        print('gsys_graphics: %s' % e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
