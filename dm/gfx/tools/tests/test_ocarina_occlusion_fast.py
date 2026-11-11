"""Ocarina binary occlusion fast path: exact zero-vs-positive visibility logic.

Each counted query contributes a nonnegative sample count. The native
occlusion query with PRECISE=0 is permitted to return 0 if and only if no
samples pass, and a nonzero value otherwise. Replacing each positive addend
with 1 preserves equality of cumulative counters *within a reset epoch*.
Exact sample counts may differ, so only Ocarina uses the trial fast path.
"""
import random
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[4] / "dm/gfx/vk_android/vka_exec.c").read_text()


class OcclusionFastTests(unittest.TestCase):
    def test_source_gates_and_fallback(self):
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', SRC)
        self.assertIn('VKA_ENV("DM_VK_OOT_FAST_OCCLUSION", 1)', SRC)
        self.assertIn('OQ.precise = f2.features.occlusionQueryPrecise != 0 && !oot_fast;', SRC)
        self.assertIn('DM_VK_OOT_FAST_OCCLUSION=0 restores precise counts', SRC)
        self.assertIn('OQ.precise ? VK_QUERY_CONTROL_PRECISE_BIT : 0', SRC)
        self.assertIn('g_oq_acc += sum;', SRC)  # don't skip reports or alter zero results
        self.assertIn('oq_close();', SRC)

    def test_equal_cumulative_before_after_visibility(self):
        rng = random.Random(1930)
        for _ in range(30000):
            n = rng.randrange(0, 120)
            counts = [rng.randrange(0, 1 << rng.randrange(0, 20)) for _ in range(n)]
            precise = [0]
            binary = [0]
            for x in counts:
                precise.append(precise[-1] + x)
                binary.append(binary[-1] + (x != 0))
            a = rng.randrange(n + 1)
            b = rng.randrange(a, n + 1)
            self.assertEqual(precise[a] == precise[b], binary[a] == binary[b])
            self.assertEqual(precise[a] != precise[b], binary[a] != binary[b])

    def test_reset_separates_cumulative_epochs(self):
        rng = random.Random(1986)
        for _ in range(900):
            sample = [rng.randrange(200) for _ in range(45)]
            for epoch in [sample[:24], sample[24:]]:
                first = sum(epoch)
                second = sum(x > 0 for x in epoch)
                self.assertEqual(first == 0, second == 0)


if __name__ == "__main__":
    unittest.main()
