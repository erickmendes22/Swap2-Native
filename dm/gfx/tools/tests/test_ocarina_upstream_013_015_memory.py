"""Source-contract and concurrency-model tests for the 0.1.3/0.1.5-inspired
memory allocation and speculative Vulkan pipeline admission adaptations.

The upstream release ZIPs contain their corresponding source; this file does
not assert byte-for-byte equivalence with those separately released sources.
No device FPS result is implied by these tests.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Condition, Lock
from time import sleep
import unittest

ROOT = Path(__file__).resolve().parents[4]
IM = (ROOT / "dm/gfx/vk_android/vka_imgmem.c").read_text()
PSO = (ROOT / "dm/gfx/vk_android/vka_pso.c").read_text()


class ImageBlockCoalesceModel:
    """One memory type, enough space for 16 image allocations per new block."""
    def __init__(self, fail_first=False):
        self.cv = Condition(Lock())
        self.allocating = False
        self.remaining = 0
        self.new_blocks = 0
        self.active_allocations = 0
        self.peak_allocations = 0
        self.fail_first = fail_first

    def reserve(self):
        with self.cv:
            if self.remaining:
                self.remaining -= 1
                return "block"
            while self.allocating:
                self.cv.wait()
                if self.remaining:
                    self.remaining -= 1
                    return "block"
            self.allocating = True
        # vkAllocateMemory must execute without the allocator mutex held.
        with self.cv:
            self.active_allocations += 1
            self.peak_allocations = max(self.peak_allocations,
                                        self.active_allocations)
        sleep(0.003)
        with self.cv:
            self.active_allocations -= 1
            self.new_blocks += 1
            failed = self.fail_first
            self.fail_first = False
            if not failed:
                self.remaining = 15
            self.allocating = False
            self.cv.notify_all()
        return "dedicated" if failed else "block"


class ImageBlockAndPrewarmTests(unittest.TestCase):
    def test_native_image_block_source_contract(self):
        self.assertIn("g_block_allocating[VK_MAX_MEMORY_TYPES]", IM)
        self.assertIn("while (!got && g_block_allocating[type])", IM)
        self.assertIn("pthread_cond_wait(&g_block_cv, &g_imu);", IM)
        self.assertIn("if (!got) g_block_allocating[type] = 1;", IM)
        self.assertIn("g_block_allocating[type] = 0;\n        pthread_cond_broadcast(&g_block_cv);", IM)
        self.assertIn("if (!got) return dedicated(img, type, mr, m);", IM)
        self.assertLess(IM.index("g_block_allocating[type] = 0;"),
                        IM.index("if (!got) return dedicated(img, type, mr, m);"))

    def test_parallel_allocations_share_a_block(self):
        m = ImageBlockCoalesceModel()
        with ThreadPoolExecutor(max_workers=16) as workers:
            results = list(workers.map(lambda _: m.reserve(), range(16)))
        self.assertEqual(results.count("block"), 16)
        self.assertEqual(m.new_blocks, 1)
        self.assertEqual(m.peak_allocations, 1)

    def test_failure_wakes_waiters_and_preserves_fallback(self):
        m = ImageBlockCoalesceModel(fail_first=True)
        with ThreadPoolExecutor(max_workers=10) as workers:
            results = list(workers.map(lambda _: m.reserve(), range(10)))
        self.assertEqual(results.count("dedicated"), 1)
        self.assertEqual(results.count("block"), 9)
        self.assertEqual(m.new_blocks, 2)
        self.assertEqual(m.peak_allocations, 1)

    def test_prewarmer_prioritizes_demanded_pipelines(self):
        self.assertIn("static _Atomic int g_pw_demand_waiters;", PSO)
        self.assertIn("atomic_fetch_add_explicit(&g_pw_demand_waiters, 1", PSO)
        self.assertIn("atomic_fetch_sub_explicit(&g_pw_demand_waiters, 1", PSO)
        before_claim = PSO.index("atomic_fetch_add(&g_pw_next, 1)")
        self.assertLess(PSO.index('atomic_load_explicit(&g_pw_demand_waiters, memory_order_relaxed)', PSO.index("static void *pw_main")), before_claim)

    def test_low_memory_pauses_only_speculative_prewarms(self):
        self.assertIn('VKA_ENV("DM_VK_PREWARM_RAM_FLOOR_MB", 512)', PSO)
        self.assertIn('sscanf(line, "MemAvailable: %llu kB", &kb)', PSO)
        self.assertIn("if (pw_memory_pressure())", PSO)
        self.assertIn("if (g->busy) busy_wait(g);", PSO)
        self.assertIn("static gval *gfx_obtain", PSO)

    def test_cache_save_is_less_frequent_and_atomic(self):
        self.assertIn('VKA_ENV("DM_VK_PCACHE_SAVE_S", 60)', PSO)
        self.assertIn("rename(tmp, g_pc_path)", PSO)


if __name__ == "__main__":
    unittest.main()
