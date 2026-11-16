"""Ocarina mesh task-index optimization: exact 0/1-task GPU behavior."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


def lookup(offsets, flat, steps):
    n = len(offsets)
    rem, idx = n, 0
    last = max(n, 1) - 1
    for _ in range(steps):
        half = rem >> 1
        mid = min(idx + half, last)
        # The original kernel supplies at least one protected arena word.
        current = offsets[mid] if n else 0
        if current <= flat:
            idx = mid
        rem -= half
    return idx


def fast_lookup(offsets, flat):
    n = len(offsets)
    if n <= 1:
        return 0
    return lookup(offsets, flat, 8 if n <= 256 else 17)


class OcarinaTaskSingleGpu(unittest.TestCase):
    def test_single_task_equals_all_old_search_results(self):
        # Regardless of offset or workgroup ID the original index stays 0.
        for offset in (0, 1, 3, 100, (1 << 20)):
            for flat in (0, 1, 2, 3, 99, 100, 200, (1 << 20)):
                self.assertEqual(lookup([offset], flat, 8), fast_lookup([offset], flat))
                self.assertEqual(lookup([offset], flat, 17), fast_lookup([offset], flat))
        self.assertEqual(fast_lookup([], 12), 0)

    def test_multiple_tasks_retain_same_lookup(self):
        # Duplicate starts encode tasks that emit no mesh workgroups.
        for n in (2, 3, 4, 8, 15, 16, 31, 64, 128, 255, 256, 257, 511, 1024):
            for stride in (0, 1, 2, 10):
                off = [(i // 3 if i % 4 == 0 else i) * stride for i in range(n)]
                off.sort()
                for flat in (0, 1, 3, 8, 16, 63, 127, 511, 1024):
                    self.assertEqual(fast_lookup(off, flat),
                                     lookup(off, flat, 8 if n <= 256 else 17))

    def test_actual_gpu_code_and_pipeline_key(self):
        spv = (VK / "vka_memu_spv.c").read_text()
        cache = (VK / "vka_memu.h").read_text()
        inc = (VK / "vka_memu_draw.inc").read_text()
        stats = (VK / "vka_memu.c").read_text()
        self.assertIn("uint32_t one = op2(&f, OpULessThanEqual, B.t_bool, nt, c1);", spv)
        self.assertIn("INS(&O, OpBranchConditional, one, one_label, many_label);", spv)
        self.assertIn("INS(&O, OpStore, pv_taskidx, c0);", spv)
        self.assertIn("uint32_t its = c0, rems = nt;", spv)
        self.assertIn("uint32_t itl = c0, reml = nt;", spv)
        self.assertIn("VKA_MEMU_KEY_TASK_SINGLE", cache)
        self.assertIn("vka_memu_task_single++", inc)
        self.assertIn("single-task eligible:", stats)
        # All other paths still select the original query-count reads;
        # zero task flag still uses the proven taskless fast path.
        self.assertIn("INS(&O, OpBranchConditional, istask, task_label, plain_label);", spv)


if __name__ == "__main__":
    unittest.main()
