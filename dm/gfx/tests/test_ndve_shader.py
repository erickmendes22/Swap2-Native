"""NDSR mixed descriptors and NDVE video programs, using synthetic data only."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import shader_split as split


def shader(seed):
    ctl = bytearray(0xd8)
    ctl[:8] = split.CTL_MAGIC + b'\xc9\0\0\0'
    struct.pack_into('<I', ctl, 0x44, 32)
    ctl[0x56] = 5
    return bytes(ctl), bytes([seed]) * 32


def ndsr(start=0x14):
    data = bytearray(0x400)
    data[:4] = b'NDSR'
    struct.pack_into('<II', data, start, 0x380, 0x10b)
    for i, at in enumerate((start + 8, start + 32)):
        c, k = 0x100 + i * 0x100, 0x300 + i * 32
        ctl, code = shader(i + 1)
        struct.pack_into('<4I', data, at, c, len(ctl) << 4 | 6, k, 0x207)
        data[c:c + len(ctl)], data[k:k + len(code)] = ctl, code
        if i == 0: struct.pack_into('<II', data, at + 16, 0x390, 0x10b)
    return bytes(data)


def ndve():
    nested = ndsr()
    ctl, code = shader(3)
    group = struct.pack('<II', 1, 1) + struct.pack('<II', 32, 4)
    group += struct.pack('<4I', 36, len(ctl), len(code), 0) + bytes(4) + ctl + code
    directory = struct.pack('<II3I', 24, 1, 6, 0, len(group))
    archive = group + directory + struct.pack('<I4s', len(group), b'1ALR')
    header = struct.pack('<4s4I', b'NDVE', 0x0ff00005, 0, len(nested), len(archive)).ljust(0x28, b'\0')
    return header + nested + archive


class VideoShaderTests(unittest.TestCase):
    def test_mixed_constants_keep_both_shader_alignments(self):
        for start in (0x10, 0x14):
            with self.subTest(start=start):
                found = split.ndsr_shaders(ndsr(start), '/synthetic')
                self.assertEqual([(c, k) for _, _, c, k in found], [shader(1), shader(2)])

    def test_nested_and_archive_programs_are_dispatched(self):
        found = []
        split.scan_blob(ndve(), '/video.dat', found)
        self.assertEqual([(c, k) for _, _, c, k in found], [shader(1), shader(2), shader(3)])
        self.assertTrue(all(st == 'cs' for _, st, _, _ in found))

    def test_loose_file_prefilter_allows_ndve(self):
        with tempfile.NamedTemporaryFile(suffix='.dat', delete=False) as f:
            f.write(ndve())
            tmp_path = f.name
        try:
            rel, uniq, pairs, extra = split.scan_file((tmp_path, 'video.dat'))
            self.assertEqual(len(uniq), 3)
        finally:
            if os.path.exists(tmp_path): os.unlink(tmp_path)

    def test_bad_lengths_version_footer_and_descriptors_are_rejected(self):
        original = ndve()
        base = 0x28 + len(ndsr())
        for offset, value in ((4, 6), (0x10, 1), (base + 8, 0),
                              (base + 16, 0xffff), (base + 20, 8),
                              (base + 28, 1), (len(original) - 4, 0)):
            with self.subTest(offset=offset):
                bad = bytearray(original)
                struct.pack_into('<I', bad, offset, value)
                with self.assertRaises(SystemExit): split.ndve_shaders(bad, '/invalid')
        with self.assertRaises(SystemExit): split.ndve_shaders(original[:-1], '/truncated')


if __name__ == '__main__':
    unittest.main()
