"""CPU model and source contract tests for the opt-in iOS-V22-inspired
Android Vulkan GMEM improvements. These tests do not claim GPU FPS gains.
"""
from bisect import bisect_right
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[4]
O = ROOT / "dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader"

class OcarinaIosV22GmemTests(unittest.TestCase):
    def test_compile_path_and_private_cache(self):
        raw = (O / "Translation/Optimizations/GlobalToStorage.cs").read_text()
        memory = (O / "StructuredIr/MemoryDefinition.cs").read_text()
        spirv = (O / "CodeGen/Spirv/Declarations.cs").read_text()
        res = (O / "Translation/ResourceManager.cs").read_text()
        draw = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
        service = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        packer = (ROOT / "scripts/pack_android.py").read_text()
        chain = (ROOT / "dm/gfx/tools/dmsh_chain.py").read_text()
        self.assertIn("#define VKA_GMEM_MAP_ENTRIES 8192", draw)
        self.assertIn('DMSH_GMEM_MAP_8192") == "1"', raw)
        self.assertIn('DMSH_GMEM_LAST1") == "1"', raw)
        self.assertIn('int mapLog2 = extendedMap ? 13 : GmemMapLog2;', raw)
        self.assertIn("memory.ZeroInit && memoryStorage == StorageClass.Private", spirv)
        self.assertIn("public bool ZeroInit", memory)
        self.assertIn("AddRawLastEntryMemory()", res)
        self.assertIn("context.Store(StorageKind.LocalMemory, last[6]", raw)
        self.assertIn('PackEngine.setenv("DMSH_GMEM_LAST1"', service)
        self.assertIn("env['DMSH_GMEM_MAP_8192']", packer)
        for name in ("ResourceManager.cs", "MemoryDefinition.cs", "Declarations.cs"):
            self.assertIn(name, chain)

    def test_dynamic_lookup_and_cache(self):
        rng = random.Random(0x20261109)
        # Sorted non-overlapping Vulkan segments, including more than 4095.
        starts, ends = [0], [0]
        x = 0x100000000
        for _ in range(4600):
            x += 4096 * rng.randint(1, 4)
            starts.append(x)
            ends.append(x + 4096 * rng.randint(1, 5))
            x = ends[-1]
        padded = starts + [(1 << 64) - 1] * (8192 - len(starts))
        def search(a, steps):
            i = 0
            for bit in reversed(range(steps)):
                cand = i + (1 << bit)
                if padded[cand] <= a:
                    i = cand
            return i if i > 0 and i < len(ends) and starts[i] <= a < ends[i] else None
        # Per-invocation last-selected range: cache is initialized empty.
        prev = None
        hits = 0
        for _ in range(22000):
            i = rng.randrange(1, 4601)
            # Consecutive accesses tend to stay in the same range, as a shader
            # walks the words of a structure.
            for _ in range(rng.randint(1, 6)):
                a = starts[i] + rng.randrange(ends[i] - starts[i])
                if prev is not None and starts[prev] <= a < ends[prev]:
                    got = prev
                    hits += 1
                else:
                    got = search(a, 13)
                    prev = got
                expected = bisect_right(starts, a) - 1
                self.assertEqual(got, expected)
                if i <= 4095:
                    self.assertEqual(search(a, 12), expected)
                else:
                    self.assertIsNone(search(a, 12))
        self.assertGreater(hits, 20000)

    def test_unmapped_address_miss(self):
        ranges = [(0x1000, 0x2000), (0x4000, 0x7000)]
        for a in (0, 0x2000, 0x3000, 0x7000, 0x99999):
            self.assertFalse(any(lo <= a < hi for lo, hi in ranges))

if __name__ == "__main__":
    unittest.main()
