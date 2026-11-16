"""Regression tests: Ocarina shadow overlay touches only three verified BYML integer words."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gsys_shadow


def fixture(width=1024, height=1024, static=4096):
    b = bytearray(512)
    struct.pack_into('<2sHIII', b, 0, b'YB', 7, 0x20, 0, 0x100)
    keys = ['DepthShadowTexHeight', 'DepthShadowTexWidth', 'StaticSdwWidth',
            'OcclusionQueryNum', 'CubemapMaxShapeNum']
    b[0x20] = 0xc2
    b[0x21] = len(keys)
    off = 0x20 + 4 + 4 * (len(keys) + 1)
    for i, name in enumerate(keys):
        struct.pack_into('<I', b, 0x24 + 4 * i, off - 0x20)
        n = name.encode()
        b[off:off + len(n)] = n
        off += len(n) + 1
    b[0x100] = 0xc1
    b[0x101] = len(keys)
    for i, value in enumerate((height, width, static, 4096, 4096)):
        p = 0x104 + 8 * i
        b[p] = i
        b[p + 3] = 0xd1
        struct.pack_into('<i', b, p + 4, value)
    return bytes(b)


class ShadowTests(unittest.TestCase):
    def test_both_profiles_and_unrelated_fields(self):
        original = fixture()
        for profile, expected in ((1, (512, 512, 2048)), (2, (256, 256, 1024))):
            result = gsys_shadow.patch(original, profile)
            self.assertEqual(len(result), len(original))
            self.assertEqual(tuple(struct.unpack_from('<i', result, 0x108 + 8 * i)[0]
                                   for i in range(3)), expected)
            self.assertEqual(result[0x11c:0x12c], original[0x11c:0x12c])
            self.assertEqual(sum(a != b for a, b in zip(original, result)), 3)
            self.assertEqual(struct.unpack_from('<i', original, 0x118)[0], 4096)

    def test_fail_closed_on_unknown_input(self):
        for b in (fixture(width=2048), fixture(static=2048), fixture(height=4096)):
            with self.assertRaises(gsys_shadow.Error):
                gsys_shadow.patch(b, 1)
        with self.assertRaises(gsys_shadow.Error):
            gsys_shadow.patch(fixture(), 3)
        b = bytearray(fixture())
        b[0x107] = 0xd3
        with self.assertRaises(gsys_shadow.Error):
            gsys_shadow.patch(bytes(b), 1)


if __name__ == '__main__':
    unittest.main()
