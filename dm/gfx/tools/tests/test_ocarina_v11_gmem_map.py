"""Ocarina V11: extended Vulkan raw-GMEM map keeps the first 4095 slots
identical for old shader libraries and permits newly translated searches
to find addresses beyond 4095. Synthetic CPU-side equivalence test.
"""
import bisect
import random
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]

class ExtendedGmemMap(unittest.TestCase):
    def test_source_wires_vulkan_and_translator(self):
        draw = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
        xlate = (ROOT / "dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Translation/Optimizations/GlobalToStorage.cs").read_text()
        service = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        self.assertIn("#define VKA_GMEM_MAP_ENTRIES 8192", draw)
        self.assertIn('DMSH_GMEM_MAP_8192") == "1" ? 13 : GmemMapLog2', xlate)
        self.assertIn('PackEngine.setenv("DMSH_GMEM_MAP_8192"', service)
        self.assertIn('DMSH_GMEM_MAP_ENTRIES 4096', (ROOT / "dm/gfx/nvn/dmsh_abi.h").read_text())

    def test_full_table_boundary_search(self):
        rng = random.Random(0x6118192)
        # One sentinel and 4,600 non-overlapping placed segments, more
        # than the original 4095-entry map could represent.
        starts = [0]
        ends = [0]
        at = 0x200000000
        for _ in range(4600):
            at += 0x1000 * rng.randint(1, 3)
            starts.append(at)
            ends.append(at + 0x1000 * rng.randint(1, 5))
            at = ends[-1]
        while len(starts) < 8192:
            starts.append((1 << 64) - 1)
            ends.append((1 << 64) - 1)
        def lookup(address, search_steps):
            index = 0
            for shift in range(search_steps - 1, -1, -1):
                candidate = index + (1 << shift)
                if starts[candidate] <= address:
                    index = candidate
            return index if starts[index] <= address < ends[index] else None
        for index in (1, 60, 4095, 4096, 4499, 4600):
            addr = starts[index]
            self.assertEqual(index, lookup(addr, 13))
            if index < 4096:
                self.assertEqual(index, lookup(addr, 12))
            else:
                self.assertIsNone(lookup(addr, 12))
        for _ in range(20000):
            index = rng.randrange(1, 4601)
            a = starts[index] + rng.randrange(ends[index] - starts[index])
            j = bisect.bisect_right(starts, a) - 1
            self.assertEqual(j, lookup(a, 13))

if __name__ == "__main__":
    unittest.main()
