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
    3: (),  # preserve SSAO allocation; patch its verified sample count in scene BYMLs
    # Keep CreateShadowPrePass=1: false leaves x20+0xd08 null and causes SIGSEGV.
    # Raw depth is a supported renderer input route; whether it saves GPU work
    # on this game's scenes needs actual Adreno measurement.
    4: (('ShadowPrePassUseRawDepth', D_BOOL, 0, 1),),
    # Keep CreateDof/Bloom=1: false leaves x20+0x1a58 null and crashes.
    # Tune the scene's own post-effect commands, never their constructors.
    5: (),
}


class Error(Exception):
    pass


def effect_ids(mask):
    """Decode independent effect bits and reject conflicting cascade choices."""
    if mask < 0 or mask > 31 or (mask & 3) == 3:
        raise Error('invalid effect mask or incompatible 3->2 / 3->1 cascades')
    return [i for i in range(1, 6) if mask & (1 << (i - 1))]


def patch(source, profile, effect=0, effects_mask=None):
    mask = (1 << (effect - 1)) if effects_mask is None and effect else (effects_mask or 0)
    selected = effect_ids(mask)
    if profile not in MAPS or (profile == 0 and not selected):
        raise Error('invalid or empty graphics patch profile')
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
    for e in selected:
        for name, kind, original, target in EFFECTS[e]:
            if name in changes:
                raise Error('two patches modify the same graphics field: ' + name)
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
    if (not differences and not any(e in (3, 5) for e in selected)) or any(i not in allowed for i in differences):
        raise Error('unexpected bytes changed')
    return bytes(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--romfs', required=True, help='RomFS of active update, including .nup:update/<version>/romfs')
    ap.add_argument('--profile', type=int, choices=sorted(MAPS), required=True, help='shadow map profile 0/1/2')
    ap.add_argument('--effect', type=int, choices=sorted(EFFECTS), default=0,
                    help='legacy single FPS patch 0..5; do not mix with --effects-mask')
    ap.add_argument('--effects-mask', type=int, default=None,
                    help='combined bits: 1=cascade 3->2, 2=cascade 3->1, 4=SSAO, 8=prepass, 16=post')
    ap.add_argument('--out', required=True, help='new RomFS overlay directory')
    args = ap.parse_args(argv)
    try:
        if args.effects_mask is not None and args.effect != 0:
            raise Error('use --effects-mask OR --effect, not both')
        mask = (1 << (args.effect - 1)) if args.effects_mask is None and args.effect else (args.effects_mask or 0)
        selected = effect_ids(mask)
        if args.profile not in MAPS or (args.profile == 0 and not selected):
            raise Error('empty graphics patch')
        src = args.romfs.rstrip('/\\') + '/' + MAIN
        with romfs.open(src, 'rb') as f:
            original = f.read(MAX_BYML + 1)
        # Merge into the same staged overlay. When SSAO and post-effect
        # experiments share a scene BYML, the later pass must read from stage.
        if 5 in selected:
            from oot_post_effects import generate as generate_post, Error as PostError
            try:
                count = generate_post(args.romfs, args.out)
            except PostError as exc:
                raise Error(str(exc)) from exc
            print('Post effects still allocated; %d validated source settings modified' % count)
        if 3 in selected:
            from oot_ssao_samples import generate, Error as SsaoError
            try:
                sample_count = generate(args.romfs, args.out)
            except SsaoError as exc:
                raise Error(str(exc)) from exc
            print('SSAO resources preserved; reduced %d validated sample-pair field(s)' % sample_count)
        updated = patch(original, args.profile, effects_mask=mask)
        target = os.path.join(args.out, *MAIN.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(updated)
        with open(target, 'rb') as f:
            if f.read() != updated:
                raise Error('written overlay did not verify')
        differing = sum(x != y for x, y in zip(original, updated))
        print('gsys_graphics: shadow %d, FPS mask %d (effects %s): %s -> %s (%d changed bytes)' %
              (args.profile, mask, selected, src, target, differing))
        return 0
    except (Error, OSError, ValueError, IndexError, struct.error) as e:
        print('gsys_graphics: %s' % e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
