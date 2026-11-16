"""AGL Bloom and DepthOfField parameter controls in PMAA (AAMP) and loose RomFS."""
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oot_agl_pmaa as pmaa
import oot_post_effects as post


def make_pmaa(family='bloom', enable=1, intensity=0.75):
    b = bytearray(0xa0)
    typ = b'aglblm' if family == 'bloom' else b'agldof'
    b[:4] = b'AAMP'
    struct.pack_into('<I', b, 4, 2)          # V2
    struct.pack_into('<I', b, 8, 1)          # LE
    struct.pack_into('<I', b, 12, len(b))    # declared size
    struct.pack_into('<I', b, 20, 8)         # padded effect name length
    struct.pack_into('<III', b, 0x18, 1, 1, 2)
    b[0x30:0x38] = typ + b'\0' * (8-len(typ))
    # list, object, parameter table (2 x 8-byte entries)
    table = 0x30 + 8 + 12 + 8
    val0, val1 = 0x80, 0x84
    for i, (name, kind, target) in enumerate([
        ('enable', 0, val0),
        ('bloom_intensity' if family == 'bloom' else 'depth_blur', 1, val1)
    ]):
        entry = table + i * 8
        struct.pack_into('<I', b, entry, zlib.crc32(name.encode()))
        struct.pack_into('<I', b, entry+4, (kind << 24) | ((target-entry)//4))
    b[val0] = enable
    struct.pack_into('<f', b, val1, intensity)
    return bytes(b)


class PmaaPatches(unittest.TestCase):
    def test_bloom_and_dof_preserve_files_and_other_fields(self):
        for family in ('bloom', 'dof'):
            with self.subTest(effect=family):
                data = make_pmaa(family)
                new, count = pmaa.patch(data, family)
                self.assertEqual(count, 2)
                self.assertEqual(len(new), len(data))
                self.assertEqual(new[0x80], 0)
                self.assertEqual(struct.unpack_from('<f', new, 0x84)[0], 0)
                different = {i for i,(a,b) in enumerate(zip(data, new)) if a != b}
                self.assertTrue(different <= {0x80, 0x84, 0x85, 0x86, 0x87})
                self.assertEqual(pmaa.patch(new, family)[1], 0)

    def test_wrong_type_version_and_hash_fail_closed(self):
        with self.assertRaises(pmaa.Error):
            pmaa.patch(make_pmaa('dof'), 'bloom')
        bad = bytearray(make_pmaa())
        struct.pack_into('<I', bad, 4, 99)
        with self.assertRaises(pmaa.Error):
            pmaa.patch(bytes(bad), 'bloom')
        with self.assertRaises(pmaa.Error):
            pmaa.patch(b'not-PMAA', 'bloom')
        not_enabled = make_pmaa(enable=0, intensity=0.0)
        self.assertEqual(pmaa.patch(not_enabled, 'bloom'), (not_enabled, 0))

    def test_generates_both_effects_from_loose_agl_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'romfs'
            src = root / 'agl' / 'BloomParam' / 'Scene.baglblm'
            dof = root / 'agl' / 'DofParam' / 'Scene.bagldof'
            src.parent.mkdir(parents=True)
            dof.parent.mkdir(parents=True)
            src.write_bytes(make_pmaa('bloom'))
            dof.write_bytes(make_pmaa('dof'))
            out = Path(tmp) / 'overlay'
            count = post.generate(str(root), str(out), lambda _: None)
            self.assertEqual(count, 2)
            for original, fam in ((src, 'bloom'), (dof, 'dof')):
                changed = (out / original.relative_to(root)).read_bytes()
                self.assertNotEqual(changed, original.read_bytes())
                self.assertEqual(pmaa.patch(changed, fam)[1], 0)
            self.assertEqual(src.read_bytes(), make_pmaa('bloom'))


if __name__ == '__main__':
    unittest.main()
