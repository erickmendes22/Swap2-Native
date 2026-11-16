"""Regression for actual v131072 /SSAO/AlchemySamplePairNum path and scalar."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oot_ssao_samples as ssao


def scene(samples=5, typ=0xd1, key='AlchemySamplePairNum', within_ssao=True):
    """Synthetic nested BYML matching /SSAO/AlchemySamplePairNum [0xd1] v5."""
    keys = ['SSAO' if within_ssao else 'Other', key, 'CreateSsocclusion', 'CreateShadowPrePass', 'UnrelatedTextureSize']
    b = bytearray(1024)
    struct.pack_into('<2sHIII', b, 0, b'YB', 7, 0x20, 0, 0x100)
    b[0x20:0x24] = bytes((0xc2, len(keys), 0, 0))
    offset = 0x24 + 4 * (len(keys) + 1)
    for i, name in enumerate(keys):
        struct.pack_into('<I', b, 0x24 + 4 * i, offset - 0x20)
        raw = name.encode()
        b[offset:offset+len(raw)] = raw
        offset += len(raw) + 1
    # root dictionary: SSAO nested, plus creation flag and independent texture size
    b[0x100:0x104] = bytes((0xc1, 3, 0, 0))
    for i, (index, kind, value) in enumerate([(0, 0xc1, 0x180), (2, 0xd0, 1),
                                                (3, 0xd0, 1)]):
        at = 0x104 + i * 8
        b[at] = index; b[at + 3] = kind
        struct.pack_into('<I', b, at + 4, value)
    # actual per-scene SSAO dictionary and 2 unrelated fields
    b[0x180:0x184] = bytes((0xc1, 2, 0, 0))
    entries = [(1, typ, samples), (4, 0xd1, 4096)]
    for i, (index, kind, value) in enumerate(entries):
        at = 0x184 + i * 8
        b[at] = index
        b[at + 3] = kind
        struct.pack_into('<I', b, at + 4, value)
    return bytes(b)


class TestSsaoReduce(unittest.TestCase):
    def test_exact_real_name_only_inside_ssao_container(self):
        original = scene()
        reduced, n = ssao.patch_byml(original)
        self.assertEqual(n, 1)
        self.assertEqual(struct.unpack_from('<i', reduced, 0x188)[0], 2)
        self.assertEqual(struct.unpack_from('<i', reduced, 0x190)[0], 4096)
        self.assertEqual(struct.unpack_from('<i', reduced, 0x110)[0], 1)   # CreateSsocclusion
        self.assertEqual(struct.unpack_from('<i', reduced, 0x118)[0], 1)   # CreateShadowPrePass
        self.assertEqual(sum(a != b for a, b in zip(original, reduced)), 1)

    def test_original_values_are_guarded(self):
        for samples in (0, 1, 4, 6, 10):
            with self.subTest(samples=samples):
                with self.assertRaises(ssao.Error):
                    ssao.patch_byml(scene(samples=samples))
        with self.assertRaises(ssao.Error):
            ssao.patch_byml(scene(typ=0xd2))
        wrong = scene(key='alchemy_sample_pair_num')
        self.assertEqual(ssao.patch_byml(wrong), (wrong, 0))
        self.assertEqual(ssao.patch_byml(scene(within_ssao=False))[1], 0)
        self.assertEqual(ssao.KEY, 'AlchemySamplePairNum')
        self.assertEqual((ssao.SOURCE_PAIRS, ssao.TRIAL_PAIRS), ((3, 5), 2))
        for original in (3, 5):
            with self.subTest(original=original):
                before = scene(samples=original)
                after, count = ssao.patch_byml(before)
                self.assertEqual(count, 1)
                self.assertEqual(struct.unpack_from('<i', after, 0x188)[0], 2)
        untouched = scene(samples=2)
        self.assertEqual(ssao.patch_byml(untouched), (untouched, 0))


if __name__ == '__main__':
    unittest.main()
