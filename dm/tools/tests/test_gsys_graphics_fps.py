"""Synthetic BYML regression: A/B patches change only validated fields; SSAO retains resources."""
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
    ('ShadowPrePassUseRawDepth', 0xd0, 0),
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
            4: {'ShadowPrePassUseRawDepth': 1},
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
        self.assertEqual(struct.unpack_from('<i', combined, 0x438)[0], 1)
        self.assertEqual(struct.unpack_from('<i', combined, 0x440)[0], 1)
        self.assertEqual(combined[0x420:0x430], raw[0x420:0x430])

    def test_combined_effects_modify_independent_fields_only(self):
        raw = make_main()
        # 3->2 cascades + SSAO sample reduction (separate scene file)
        # + depth input pre-pass + Bloom/DOF controls (separate scene).
        for mask, cascade, raw_depth in (
            (1 | 4, 2, 0),
            (2 | 8, 1, 1),
            (1 | 4 | 8 | 16, 2, 1),
            (2 | 4 | 8 | 16, 1, 1),
        ):
            with self.subTest(mask=mask):
                out = graphics.patch(raw, 0, effects_mask=mask)
                self.assertEqual(struct.unpack_from('<i', out, 0x430)[0], cascade)
                self.assertEqual(struct.unpack_from('<i', out, 0x458)[0], raw_depth)
                for idx in (6, 7, 8, 9):
                    at = 0x408 + idx * 8
                    self.assertEqual(out[at:at + 4], raw[at:at + 4])
        for bad in (-1, 3, 7, 31, 32):
            with self.subTest(bad=bad), self.assertRaises(graphics.Error):
                graphics.patch(raw, 0, effects_mask=bad)
        self.assertEqual(graphics.effect_ids(1 | 4 | 16), [1, 3, 5])

    def test_reject_malformed_and_unknown_update(self):
        raw = make_main()
        for effect, field, value in [
            (1, 'DepthShadowCascadeNum0', 4),
            (4, 'ShadowPrePassUseRawDepth', 1),
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
        for effect in (3, 5):
            self.assertEqual(graphics.patch(raw, 0, effect), raw,
                             'effect %d must not disable resource creation in the main BYML' % effect)
        for effect in (3, 4, 5):
            modified = graphics.patch(raw, 0, effect)
            for index in (6, 7, 8, 9):
                self.assertEqual(modified[0x404 + index * 8 + 4:0x40c + index * 8],
                                 raw[0x404 + index * 8 + 4:0x40c + index * 8],
                                 'all four output-producing resources must remain created')


if __name__ == '__main__':
    unittest.main()
