"""GPU mesh task-index search: 8 for <=256 tasks vs historical 17.

This proves the task index for repeated offsets/empty tasks, including
boundary and random cases. On-device GPU timings are still required.
"""
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


def task_index(offsets, flat, steps):
    last, index, remaining = len(offsets) - 1, 0, len(offsets)
    for _ in range(steps):
        half = remaining >> 1
        midpoint = min(index + half, last)
        if offsets[midpoint] <= flat:
            index = midpoint
        remaining -= half
    return index


class MeshTaskSearch(unittest.TestCase):
    def test_all_boundary_counts_and_repeated_offsets(self):
        rng = random.Random(20261113)
        cases = 0
        sizes = [1, 2, 3, 4, 5, 7, 8, 15, 16, 31, 32, 33,
                 63, 64, 127, 128, 129, 255, 256, 257, 511, 512, 1024, 65535]
        for n in sizes:
            for _ in range(1000 if n < 1024 else 32):
                offsets = [0]
                for __ in range(n-1):
                    offsets.append(offsets[-1] + rng.randrange(0, 5))
                flat = rng.randrange(0, offsets[-1] + 6)
                self.assertEqual(
                    task_index(offsets, flat, 17),
                    task_index(offsets, flat, 8 if n <= 256 else 17),
                    (n, flat))
                cases += 1
        self.assertGreater(cases, 20000)

    def test_real_shader_preserves_fallback_and_key_isolation(self):
        spv = (VK / "vka_memu_spv.c").read_text()
        header = (VK / "vka_memu.h").read_text()
        self.assertIn("OpULessThanEqual, B.t_bool", spv)
        self.assertIn("nt, cu(&B, 256)", spv)
        self.assertIn("j < 8", spv)
        self.assertIn("j < 17", spv)
        self.assertIn("DM_VK_MEMU_SHORT_TASK_SEARCH", (VK / "vka_memu_spv.h").read_text())
        self.assertIn("VKA_MEMU_KEY_TASK_SHORT", header)
        self.assertIn("pv_taskidx, new_wgvar", spv)


if __name__ == "__main__":
    unittest.main()
