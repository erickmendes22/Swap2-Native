#!/usr/bin/env python3
"""Produce a separate Ocarina shadow RomFS overlay from the active NUP/version.

Never modifies the player's NUP. Only three verified BYML root integer values
may change; unsupported updates fail closed instead of using stale base data.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import romfs
from gsys_dynres import Byml, D_INT

MAIN = 'gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml'
EXPECTED = {'DepthShadowTexWidth': 1024, 'DepthShadowTexHeight': 1024,
            'StaticSdwWidth': 4096}
PROFILES = {1: (512, 2048), 2: (256, 1024)}
MAX_BYML = 2 * 1024 * 1024


class Error(Exception):
    pass


def patch(source, profile):
    if profile not in PROFILES:
        raise Error('invalid shadow profile')
    if not 20 <= len(source) <= MAX_BYML:
        raise Error('Main BYML size not accepted')
    raw = bytearray(source)
    by = Byml(raw, 0)
    if by.e != '<' or by.root <= 0 or by.root + 4 > len(raw) or raw[by.root] != 0xc1:
        raise Error('Main BYML root must be a little-endian named dictionary')
    entries = by.items(by.root)
    words = {}
    for name, typ, word in entries:
        if name not in EXPECTED:
            continue
        if name in words:
            raise Error('duplicate shadow field: ' + name)
        if typ != D_INT or word < 0 or word + 4 > len(raw):
            raise Error('wrong type/offset for ' + name)
        if struct.unpack_from('<i', raw, word)[0] != EXPECTED[name]:
            raise Error('unexpected original value for ' + name)
        words[name] = word
    if set(words) != set(EXPECTED):
        raise Error('Main BYML does not contain all three verified shadow fields')
    dyn, stat = PROFILES[profile]
    for name, target in (('DepthShadowTexWidth', dyn),
                         ('DepthShadowTexHeight', dyn), ('StaticSdwWidth', stat)):
        struct.pack_into('<i', raw, words[name], target)
    allow = {word + k for word in words.values() for k in range(4)}
    differences = [i for i, (a, b) in enumerate(zip(source, raw)) if a != b]
    if not differences or any(i not in allow for i in differences):
        raise Error('unexpected bytes changed')
    return bytes(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--romfs', required=True, help='active RomFS, including update/<version>/romfs')
    ap.add_argument('--profile', type=int, choices=sorted(PROFILES), required=True)
    ap.add_argument('--out', required=True, help='new RomFS overlay directory')
    args = ap.parse_args(argv)
    try:
        src = args.romfs.rstrip('/\\') + '/' + MAIN
        with romfs.open(src, 'rb') as f:
            original = f.read(MAX_BYML + 1)
        updated = patch(original, args.profile)
        target = os.path.join(args.out, *MAIN.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(updated)
        with open(target, 'rb') as f:
            if f.read() != updated:
                raise Error('written overlay did not verify')
        print('gsys_shadow: profile %d: %s -> %s (%d bytes; 3 shadow fields only)' %
              (args.profile, src, target, len(updated)))
        return 0
    except (Error, OSError, ValueError, IndexError, struct.error) as e:
        print('gsys_shadow: %s' % e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
