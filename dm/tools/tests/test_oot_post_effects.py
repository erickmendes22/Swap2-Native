"""DOF/Bloom opt-in source control trial never disables required resources."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oot_post_effects as post


def source(bloom=0.25, dof=0.75):
    keys = ['BloomIntensity', 'DofIntensity', 'CreateBloom', 'CreateDof', 'ShadowPrePassUseRawDepth']
    b = bytearray(512)
    struct.pack_into('<2sHIII', b, 0, b'YB', 7, 0x20, 0, 0x100)
    b[0x20:0x24] = bytes((0xc2, len(keys), 0, 0))
    off = 0x24 + 4 * (len(keys) + 1)
    for i, name in enumerate(keys):
        struct.pack_into('<I', b, 0x24 + i * 4, off - 0x20)
        v = name.encode()
        b[off:off + len(v)] = v
        off += len(v) + 1
    b[0x100:0x104] = bytes((0xc1, len(keys), 0, 0))
    for i, (kind, val) in enumerate([(0xd2, bloom), (0xd2, dof),
                                      (0xd0, 1), (0xd0, 1), (0xd0, 0)]):
        at = 0x104 + i * 8
        b[at] = i; b[at+3] = kind
        struct.pack_into('<f' if kind == 0xd2 else '<i', b, at + 4, val)
    return bytes(b)


class PostPreservesAssets(unittest.TestCase):
    def test_both_render_resources_stay_created(self):
        before = source()
        after, found = post.patch_byml(before)
        self.assertEqual(found, {'bloom', 'dof'})
        self.assertEqual(struct.unpack_from('<f', after, 0x108)[0], 0.0)
        self.assertEqual(struct.unpack_from('<f', after, 0x110)[0], 0.0)
        for i in (2, 3, 4):
            at = 0x108 + i * 8
            self.assertEqual(after[at:at+4], before[at:at+4])

    def test_overlay_written_only_after_identifying_both_effects(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'root'
            resource = root / 'gsys' / 'ModelSceneEnvParam' / 'Main.bgyml'
            resource.parent.mkdir(parents=True)
            resource.write_bytes(source())
            target = Path(d) / 'stage'
            count = post.generate(str(root), str(target), lambda _: None)
            self.assertEqual(count, 1)
            overlay = target / resource.relative_to(root)
            self.assertTrue(overlay.is_file())
            self.assertEqual(post.patch_byml(overlay.read_bytes())[1], set())
            self.assertEqual(resource.read_bytes(), source())

    def test_incomplete_effects_do_not_publish_any_overlay(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'root'
            resource = root / 'gsys' / 'ModelSceneEnvParam' / 'Main.bgyml'
            resource.parent.mkdir(parents=True)
            resource.write_bytes(source(bloom=0.0, dof=0.8))
            target = Path(d) / 'stage'
            with self.assertRaises(post.Error):
                post.generate(str(root), str(target), lambda _: None)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
