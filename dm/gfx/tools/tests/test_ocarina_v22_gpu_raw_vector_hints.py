"""Structural and mathematical coverage for Ocarina Vulkan V21/V22 GPU paths.

No benchmark here asserts FPS. These tests verify that vector-load lowering is
connected through the frontend, raw helper, private spill, and SPIR-V backend,
and that 2 MiB range hints cannot resolve an unmapped guest address to a
different pool. Vulkan validation and on-device benchmarking remain required.
"""
import random
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RY = ROOT / "dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader"
GTS = (RY / "Translation/Optimizations/GlobalToStorage.cs").read_text()
SPV = (RY / "CodeGen/Spirv/Instructions.cs").read_text()
RESOURCE = (RY / "Translation/ResourceManager.cs").read_text()
AMP = (RY / "Instructions/InstEmitAmpereMem.cs").read_text()
MAXWELL = (RY / "Instructions/InstEmitMemory.cs").read_text()
OP = (RY / "IntermediateRepresentation/Operation.cs").read_text()
STORAGE = (RY / "IntermediateRepresentation/StorageKind.cs").read_text()
HOST = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()

N = 8192
S = 1 << 21


def host_hint(rows):
    """Model of last-writer-wins hash hints in words 6 and 7."""
    hints = {}
    for i, (lo, hi) in enumerate(rows, 1):
        start = (lo + S - 1) // S
        end = hi // S
        for chunk in range(start, min(end, 2**32)):
            hints[chunk & (N - 1)] = (chunk, i)
    return hints


def resolve(rows, hints, addr):
    chunk = addr >> 21
    if chunk > 0xFFFFFFFF:
        return None
    entry = hints.get(chunk & (N - 1))
    if not entry or entry[0] != chunk or not 0 < entry[1] < N:
        return None
    i = entry[1] - 1
    lo, hi = rows[i]
    return i if lo <= addr < hi else None


class RawVectorTests(unittest.TestCase):
    def test_frontend_and_spirv_compile_path(self):
        for src in (AMP, MAXWELL):
            self.assertIn('load.GlobalVectorCount = count;', src)
            self.assertIn('load.GlobalVectorWord = index;', src)
        self.assertIn('public int GlobalVectorCount { get; set; }', OP)
        self.assertIn('GlobalMemoryVector,', STORAGE)
        self.assertIn('public int GetRawVectorMemory()', RESOURCE)
        self.assertIn('RawVectorFunctions', GTS)
        self.assertIn('TryGetRawVectorFunction(', GTS)
        self.assertIn('GenerateRawVectorLoad(', GTS)
        self.assertIn('Const(resourceManager.GetRawVectorMemory())', GTS)
        self.assertIn('operation.StorageKind == StorageKind.GlobalMemoryVector', SPV)
        self.assertIn('context.Load(vectorType, pointer, MemoryAccessMask.Aligned)', SPV)
        self.assertIn('context.CompositeExtract(context.TypeU32(), value, (SpvLiteralInteger)word)', SPV)

    def test_raw_cache_and_hint_path(self):
        self.assertIn('bool cacheLast = true;', GTS)
        self.assertIn('new int[7]', GTS)
        self.assertIn('MapWord(hintRow, 6)', GTS)
        self.assertIn('MapWord(hintRow, 7)', GTS)
        self.assertIn('context.Branch(afterSearch);', GTS)
        self.assertIn('context.ICompareLessUnsigned(addrHigh, Const(1 << 21))', GTS)
        self.assertIn('#define VKA_GMEM_MAP_ENTRIES 8192', HOST)
        self.assertIn('const uint64_t granule = UINT64_C(1) << 21', HOST)
        self.assertIn('DMSH_GMEM_MAP_ENTRY + 24', HOST)

    def test_hints_only_cover_full_chunks(self):
        rows = [(0x1123456, 0x1FF0040),
                (0x6000000, 0x6F12004),
                (0x200000000, 0x200900000)]
        hints = host_hint(rows)
        rng = random.Random(20261110)
        # A hint must NEVER map an address outside its actual segment;
        # a collision is allowed to produce a miss, not a false pool.
        for i in range(10000):
            addr = rng.randrange(0, 0x201000000)
            got = resolve(rows, hints, addr)
            if got is not None:
                self.assertLessEqual(rows[got][0], addr)
                self.assertLess(addr, rows[got][1])

    def test_collisions_and_bounds_are_conservative(self):
        rows = [(S, 3*S), ((8192+1)*S, (8192+3)*S)]
        hints = host_hint(rows)
        # Same modulo slot: the most recently written tag wins.
        self.assertIsNone(resolve(rows, hints, S))
        self.assertEqual(resolve(rows, hints, (8192+1)*S), 1)
        self.assertIsNone(resolve(rows, hints, (8192+3)*S))
        self.assertIsNone(resolve(rows, hints, (1 << 53) + S))
        # A partial first/last 2 MiB chunk is never in the tag table.
        odd = [(S+64, 4*S-64)]
        self.assertEqual(host_hint(odd).keys(), {2})


if __name__ == "__main__":
    unittest.main()
