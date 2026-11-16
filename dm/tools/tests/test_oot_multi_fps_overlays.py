"""Real filesystem integration: combine four independent FPS experiments in one overlay."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gsys_shadow
from tests.test_gsys_graphics_fps import make_main

FIELDS = [
    ('SSAO', 0xc1, 0x300),
    ('BloomIntensity', 0xd2, 0.25),
    ('DofIntensity', 0xd2, 0.8),
    ('CreateBloom', 0xd0, 1),
    ('CreateDof', 0xd0, 1),
    ('CreateSsocclusion', 0xd0, 1),
    ('CreateShadowPrePass', 0xd0, 1),
    ('AlchemySamplePairNum', 0xd1, 3),
]


def combined_scene():
    b = bytearray(2048)
    struct.pack_into('<2sHIII', b, 0, b'YB', 7, 0x20, 0, 0x200)
    b[0x20:0x24] = bytes((0xc2, len(FIELDS), 0, 0))
    off = 0x24 + (len(FIELDS) + 1) * 4
    for i, (name, _kind, _val) in enumerate(FIELDS):
        struct.pack_into('<I', b, 0x24 + i * 4, off - 0x20)
        txt = name.encode()
        b[off:off + len(txt)] = txt
        off += len(txt) + 1
    b[0x200:0x204] = bytes((0xc1, 7, 0, 0))
    for i, (name, kind, val) in enumerate(FIELDS[:7]):
        at = 0x204 + 8 * i
        b[at] = i
        b[at + 3] = kind
        struct.pack_into('<f' if kind == 0xd2 else '<I', b, at + 4, val)
    b[0x300:0x304] = bytes((0xc1, 1, 0, 0))
    b[0x304] = 7
    b[0x307] = 0xd1
    struct.pack_into('<i', b, 0x308, 3)
    return bytes(b)


class MultiPatchIntegration(unittest.TestCase):
    def test_real_staged_overlay_keeps_every_independent_edit(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root) / 'romfs'
            main = base / gsys_shadow.MAIN
            scene = base / 'gsys/ModelSceneShadowParam/Scene.gsys__ModelSceneShadowParam.bgyml'
            main.parent.mkdir(parents=True)
            scene.parent.mkdir(parents=True)
            main.write_bytes(make_main())
            scene.write_bytes(combined_scene())
            out = Path(root) / 'stage'
            # cascade 3->2 + SSAO samples + raw-depth shadow + DOF/Bloom controls
            result = gsys_shadow.main(['--romfs', str(base), '--profile', '0',
                                       '--effects-mask', str(1 | 4 | 8 | 16),
                                       '--out', str(out)])
            self.assertEqual(result, 0)
            # The source NUP-equivalent RomFS is never changed.
            self.assertEqual(scene.read_bytes(), combined_scene())
            self.assertEqual(main.read_bytes(), make_main())
            new_scene = (out / scene.relative_to(base)).read_bytes()
            new_main = (out / main.relative_to(base)).read_bytes()
            self.assertEqual(struct.unpack_from('<i', new_scene, 0x308)[0], 2)
            self.assertEqual(struct.unpack_from('<f', new_scene, 0x214)[0], 0.0)
            self.assertEqual(struct.unpack_from('<f', new_scene, 0x21c)[0], 0.0)
            self.assertEqual(struct.unpack_from('<i', new_scene, 0x224)[0], 1)
            self.assertEqual(struct.unpack_from('<i', new_scene, 0x22c)[0], 1)
            self.assertEqual(struct.unpack_from('<i', new_main, 0x430)[0], 2)
            self.assertEqual(struct.unpack_from('<i', new_main, 0x458)[0], 1)

    def test_conflicting_cascades_do_not_publish_overlay(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / 'overlay'
            self.assertEqual(gsys_shadow.main(['--romfs', root, '--profile', '0',
                         '--effects-mask', '3', '--out', str(out)]), 1)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
