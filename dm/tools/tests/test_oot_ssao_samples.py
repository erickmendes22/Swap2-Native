"""A/B SSAO reduction: keep scene allocations and patch only exact sample count."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oot_ssao_samples as ssao


def scene(samples=5, kind=0xd1, key='alchemy_sample_pair_num'):
    keys = [key, 'UnrelatedTextureSize', 'SsaoOutputEnabled']
    b = bytearray(512)
    struct.pack_into('<2sHIII', b, 0, b'YB', 7, 0x20, 0, 0x100)
    b[0x20:0x24] = bytes((0xc2, len(keys), 0, 0))
    offset = 0x20 + 4 + 4 * (len(keys) + 1)
    for i, name in enumerate(keys):
        struct.pack_into('<I', b, 0x24 + 4 * i, offset - 0x20)
        encoded = name.encode()
        b[offset:offset + len(encoded)] = encoded
        offset += len(encoded) + 1
    b[0x100:0x104] = bytes((0xc1, len(keys), 0, 0))
    for i, (ty, val) in enumerate(((kind, samples), (0xd1, 4096), (0xd0, 1))):
        at = 0x104 + i * 8
        b[at] = i
        b[at + 3] = ty
        struct.pack_into('<i', b, at + 4, val)
    return bytes(b)


class TestSsaoReduce(unittest.TestCase):
    def test_only_sample_count_changes(self):
        original = scene()
        reduced, n = ssao.patch_byml(original)
        self.assertEqual(n, 1)
        self.assertEqual(reduced[0x108:0x10c], (2).to_bytes(4, 'little'))
        self.assertEqual(reduced[0x110:0x114], (4096).to_bytes(4, 'little'))
        self.assertEqual(reduced[0x118:0x11c], (1).to_bytes(4, 'little'))
        self.assertEqual(sum(a != b for a, b in zip(original, reduced)), 1)

    def test_fail_closed_for_unproven_values(self):
        for sample in (0, 1, 2, 3, 4, 6, 10):
            with self.subTest(samples=sample):
                with self.assertRaises(ssao.Error):
                    ssao.patch_byml(scene(samples=sample))
        with self.assertRaises(ssao.Error):
            ssao.patch_byml(scene(kind=0xd2))
        unrecognized = scene(key='unknown_sample_count')
        self.assertEqual(ssao.patch_byml(unrecognized), (unrecognized, 0))

    def test_invalid_byml_and_no_patching_when_unknown(self):
        with self.assertRaises(Exception):
            ssao.patch_byml(b'not a byml')
        self.assertEqual(ssao.SOURCE_PAIRS, 5)
        self.assertEqual(ssao.TRIAL_PAIRS, 2)


if __name__ == '__main__':
    unittest.main()
