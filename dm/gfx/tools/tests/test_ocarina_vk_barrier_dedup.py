"""Regression checks: avoid duplicate Vulkan full barrier after ending a draw pass.

An explicit guest barrier still gets a FULL pass-end memory dependency;
this is not a relaxation of dependency masks or guest command ordering.
This test requires neither the Android toolchain nor compiled guest shaders.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()


class TestRedundantRenderPassBarrier(unittest.TestCase):
    def test_pass_end_already_has_a_full_barrier(self):
        # The replacement is safe only while this full barrier still exists.
        self.assertIn('vk.vkCmdEndRendering(g_cb);', DRAW)
        self.assertIn('g_rp_force_full || R.bar_pending || had_clears || vka_nan_on()', DRAW)
        self.assertIn('if (full || (R.swrite && VKA_ENV("DM_VK_OOT_FPS_BOOST", 0) <= 0)) {', DRAW)
        self.assertIn('g_rp_full++; vka_barrier(g_cb);', DRAW)
        self.assertIn('g_rp_force_full = 1;\n    vka_rp_end();\n    g_rp_force_full = 0;', DRAW)
        self.assertIn('VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT', TEX)
        self.assertIn('VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT', TEX)

    def test_no_skip_if_pass_closed_or_nan_diagnostics_add_work(self):
        self.assertIn('int covered = R.on && !vka_nan_on();', DRAW)
        self.assertIn('g_rp_force_full = 1;\n    vka_rp_end();\n    g_rp_force_full = 0;', DRAW)
        self.assertIn('if (covered) g_bar_duplicate_avoided++;', DRAW)
        self.assertIn('return covered;', DRAW)
        self.assertIn('int vka_rp_end_covers_barrier(void);', HEADER)

    def test_only_normal_duplicated_barrier_suppressed(self):
        self.assertIn('bar_covered = vka_rp_end_covers_barrier();', EXEC)
        self.assertIn('if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);', EXEC)
        self.assertIn('int bar_kept = 0, bar_covered = 0;', EXEC)
        self.assertIn('redundant full barriers avoided %.1f/frame', DRAW)

    def test_count_for_all_guest_barrier_cases(self):
        # Model the two paths. With an open pass and no NaN scan, the already
        # recorded pass-end barrier covers the immediately following guest
        # barrier; in all other cases, one explicit barrier is still recorded.
        for open_pass in (False, True):
            for nan_scan in (False, True):
                covered = open_pass and not nan_scan
                old_count = int(open_pass) + 1
                new_count = int(open_pass) + int(not covered)
                self.assertGreaterEqual(new_count, 1)
                self.assertEqual(old_count - new_count, int(covered))
        # DM_VK_BAR_KEEP=1 is the existing optional alternative: no explicit
        # barrier is emitted, and this new path does not touch that behavior.
        self.assertIn('if (g_cb && !bar_kept && !bar_covered)', EXEC)


if __name__ == '__main__':
    unittest.main()
