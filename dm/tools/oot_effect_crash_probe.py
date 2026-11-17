#!/usr/bin/env python3
"""Inspect only the user's active Ocarina update for safe, *non-destructive* FPS fixes.

Reports the two crash instructions and effect parameter fields from game-owned
NUP files. No NUP content, shader binaries or game executable code is exported.
This avoids speculative guest instruction patches on a possibly different build.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import romfs
import nso
from gsys_dynres import Byml, CONTAINERS

# Verified crash PCs from v131072 user logs (main module memory offsets).
SITES = ((0x47a924, 'CreateShadowPrePass disabled: SIGSEGV addr 0x308'),
         (0xdbea1c, 'CreateDof/CreateBloom disabled: SIGSEGV addr 0x12c8'))
WORDS = ('ssao', 'ssoccl', 'alchemy', 'shadowpre', 'dof', 'bloom', 'blur',
         'occlusion', 'shadow', 'sample')


def original_exefs(romfs_root):
    marker = '/romfs'
    if '.nup:update/' in romfs_root and romfs_root.endswith(marker):
        return romfs_root[:-len(marker)] + '/exefs/main'
    if '.nup:base/romfs' in romfs_root:
        return romfs_root.replace('/romfs', '/exefs/main')
    if romfs_root.endswith('/romfs'):
        return romfs_root[:-len(marker)] + '/exefs/main'
    raise ValueError('unsupported RomFS reference; expected NUP update/<version>/romfs')


def validate_module(module):
    bid = module.build_id.hex()
    if not bid.startswith('e0f3ccfa'):
        raise ValueError('main build mismatch (' + bid[:16] + '), crash offsets not valid')
    for pc, _ in SITES:
        if pc + 4 > module.text_end:
            raise ValueError('crash PC is outside the validated executable text')
    return bid


def crash_disassembly(module, stdout=print):
    """Show a narrow bounded instruction window, no proprietary game binary."""
    bid = validate_module(module)
    try:
        import capstone
    except ImportError as e:
        raise RuntimeError('capstone required for disassembly') from e
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    stdout('Executable build: %s; text: %#x' % (bid, module.text_end))
    for pc, what in SITES:
        stdout('CRASH %s at main+%#x:' % (what, pc))
        start = pc - 0x70
        block = bytes(module.image[start:pc + 0x40])
        for inst in md.disasm(block, start):
            mark = '>>' if inst.address == pc else '  '
            stdout(' %s main+%08x %-8s %s' % (mark, inst.address, inst.mnemonic, inst.op_str))
        # Also show nearby branches with their destinations for xref tracing.
        found = []
        begin = max(0, pc - 0x2000)
        for ins in md.disasm(bytes(module.image[begin:pc+0x40]), begin):
            if ins.mnemonic not in ('b', 'bl', 'cbz', 'cbnz', 'tbz', 'tbnz'):
                continue
            if ('#0x%x' % pc in ins.op_str.lower() or
                    '#%d' % pc in ins.op_str or
                    ('#0x%x' % (pc & ~3)) in ins.op_str.lower()):
                found.append('%#x %s %s' % (ins.address, ins.mnemonic, ins.op_str))
        stdout(' direct xrefs: %s' % ('; '.join(found[-8:]) or '(none in preceding 8 KiB)'))


def inspect_effect_params(root, stdout=print):
    """Read-only BYML scalar survey; only effect-relevant names are printed."""
    names = [
        'gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml',
    ]
    directory = root.rstrip('/\\') + '/gsys/ModelSceneShadowParam'
    try:
        with romfs.scandir(directory) as entries:
            names += ['gsys/ModelSceneShadowParam/' + e.name for e in entries
                      if e.is_file() and e.name.endswith('.bgyml')]
    except OSError as e:
        stdout('ModelSceneShadowParam directory not readable: ' + str(e))
    for name in names[:26]:
        file_path = root.rstrip('/\\') + '/' + name
        try:
            with romfs.open(file_path, 'rb') as f:
                blob = f.read(2 * 1024 * 1024 + 1)
            if not 12 < len(blob) <= 2 * 1024 * 1024:
                raise ValueError('BYML unexpected size')
            by = Byml(blob, 0)
            if by.root <= 0:
                raise ValueError('BYML missing root')
            visited, printed = set(), [0]
            stdout('PARAMS ' + name)
            def walk(node, path, level):
                if level > 16 or node in visited or node < 0 or node + 4 > len(blob):
                    return
                visited.add(node)
                for key, kind, word in by.items(node):
                    full = path + '/' + key
                    if word < 0 or word + 4 > len(blob):
                        continue
                    if kind in CONTAINERS:
                        walk(by.u32(word), full, level + 1)
                    elif printed[0] < 60 and any(w in full.lower() for w in WORDS):
                        if kind == 0xd2:
                            value = struct.unpack_from(by.e + 'f', blob, word)[0]
                        elif kind in (0xd0, 0xd1, 0xd3):
                            value = struct.unpack_from(by.e + 'i', blob, word)[0]
                        else:
                            continue
                        stdout('  %s: %s (type %#x, file+%#x)' % (full, value, kind, word))
                        printed[0] += 1
            walk(by.root, '', 0)
        except (OSError, ValueError, IndexError, struct.error) as e:
            stdout('PARAM_ERROR ' + name + ': ' + str(e))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--romfs', required=True, help='active update RomFS (NUP or extracted)')
    p.add_argument('--params-only', action='store_true', help='inspect BYML without reading the game executable')
    a = p.parse_args(argv)
    try:
        if not a.params_only:
            path = original_exefs(a.romfs)
            with romfs.open(path, 'rb') as f:
                data = f.read(256 * 1024 * 1024 + 1)
            if len(data) > 256 * 1024 * 1024:
                raise ValueError('executable exceeds safety cap')
            crash_disassembly(nso.load(data, 'Ocarina main'))
        inspect_effect_params(a.romfs)
    except (OSError, ValueError, IndexError, struct.error, RuntimeError) as e:
        print('oot_effect_crash_probe: ' + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
