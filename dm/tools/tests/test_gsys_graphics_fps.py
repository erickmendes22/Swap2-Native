"""Synthetic BYML regression: each FPS A/B profile edits ONLY named game switches."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gsys_shadow as graphics

KEYS = [
    ('DepthShadowTexHeight', 0xd1, 1024),
    ('DepthShadowTexWidth', 0xd1, 1024),
    ('StaticSdwWidth', 0xd1, 4096),
    ('OcclusionQueryNum', 0xd1, 4096),
    ('CubemapMaxShapeNum', 0xd3, 4096),
    ('DepthShadowCascadeNum0', 0xd1, 3),
    ('CreateSsocclusion', 0xd0, 1),
    ('CreateShadowPrePass', 0xd0, 1),
    ('CreateDof', 0xd0, 1),
    ('CreateBloom', 0xd0, 1),
]


def make_main(values=None):
    values = values or {}
    root = 0x400
    b = bytearray(2048)
    struct.pack_into('<2sHIII', b, 0, b'YB', 7, 0x20, 0, root)
    b[0x20:0x24] = bytes((0xc2, len(KEYS), 0, 0))
    off = 0x20 + 4 + (len(KEYS) + 1) * 4
    for i, (key, _kind, _value) in enumerate(KEYS):
        struct.pack_into('<I', b, 0x24 + i * 4, off - 0x20)
        kb = key.encode()
        b[off:off+len(kb)] = kb
        off += len(kb) + 1
    b[root:root+4] = bytes((0xc1, len(KEYS), 0, 0))
    for i, (name, kind, value) in enumerate(KEYS):
        at = root + 4 + i * 8
        b[at + 3] = kind
        b[at] = i
        struct.pack_into('<i', b, at + 4, values.get(name, value))
    return bytes(b)


class GraphicsPatches(unittest.TestCase):
    def test_each_profile_only_changes_expected_named_word(self):
        raw = make_main()
        profiles = {
            1: {'DepthShadowCascadeNum0': 2},
            2: {'DepthShadowCascadeNum0': 1},
            3: {'CreateSsocclusion': 0},
            4: {'CreateShadowPrePass': 0},
            5: {'CreateDof': 0, 'CreateBloom': 0},
        }
        for effect, selected in profiles.items():
            with self.subTest(effect=effect):
                patched = graphics.patch(raw, 0, effect)
                self.assertEqual(len(patched), len(raw))
                expected = bytearray(raw)
                for i, (name, typ, value) in enumerate(KEYS):
                    if name in selected:
                        struct.pack_into('<i', expected, 0x404 + i * 8 + 4, selected[name])
                self.assertEqual(patched, expected)
                self.assertTrue(any(x != y for x, y in zip(raw, patched)))

    def test_maps_and_fps_patch_are_merged_into_one_file(self):
        raw = make_main()
        combined = graphics.patch(raw, 2, 3)
        self.assertEqual(struct.unpack_from('<i', combined, 0x408)[0], 256)
        self.assertEqual(struct.unpack_from('<i', combined, 0x410)[0], 256)
        self.assertEqual(struct.unpack_from('<i', combined, 0x418)[0], 1024)
        self.assertEqual(struct.unpack_from('<i', combined, 0x430)[0], 3)
        self.assertEqual(struct.unpack_from('<i', combined, 0x438)[0], 0)
        self.assertEqual(struct.unpack_from('<i', combined, 0x440)[0], 1)
        self.assertEqual(combined[0x420:0x430], raw[0x420:0x430])

    def test_multiple_effects_are_applied_in_one_overlay(self):
        raw = make_main()
        mask = 1 | 4 | 8 | 16  # cascade 3->2, SSAO, prepass, DOF + Bloom
        patched = graphics.patch(raw, 0, effect_mask=mask)
        expected = bytearray(raw)
        values = {'DepthShadowCascadeNum0': 2, 'CreateSsocclusion': 0,
                  'CreateShadowPrePass': 0, 'CreateDof': 0, 'CreateBloom': 0}
        for i, (name, _kind, _value) in enumerate(KEYS):
            if name in values:
                struct.pack_into('<i', expected, 0x404 + i * 8 + 4, values[name])
        self.assertEqual(patched, bytes(expected))
        self.assertEqual(graphics.patch(raw, 0, effect_mask=16)[0x44c:0x454],
                         bytes(expected)[0x44c:0x454])

    def test_mask_cannot_combine_incompatible_cascades(self):
        for mask in (-1, 3, 7, 31, 32):
            with self.subTest(mask=mask), self.assertRaises(graphics.Error):
                graphics.patch(make_main(), 0, effect_mask=mask)
        with self.assertRaises(graphics.Error):
            graphics.patch(make_main({'CreateDof': 0}), 0, effect_mask=16)

    def test_reject_malformed_and_unknown_update(self):
        raw = make_main()
        for effect, field, value in [
            (1, 'DepthShadowCascadeNum0', 4),
            (3, 'CreateSsocclusion', 0),
            (4, 'CreateShadowPrePass', 0),
            (5, 'CreateBloom', 0),
        ]:
            with self.subTest(effect=effect):
                with self.assertRaises(graphics.Error):
                    graphics.patch(make_main({field: value}), 0, effect)
        with self.assertRaises(graphics.Error):
            graphics.patch(raw, 0, 0)
        with self.assertRaises(graphics.Error):
            graphics.patch(raw, 0, 6)
        with self.assertRaises(graphics.Error):
            graphics.patch(raw, 3, 1)
        with self.assertRaises(graphics.Error):
            graphics.patch(make_main({'DepthShadowTexWidth': 512}), 1, 1)
        corrupt = bytearray(raw)
        corrupt[0x404 + 6 * 8 + 3] = 0xd1
        with self.assertRaises(graphics.Error):
            graphics.patch(bytes(corrupt), 0, 3)


if __name__ == '__main__':
    unittest.main()
