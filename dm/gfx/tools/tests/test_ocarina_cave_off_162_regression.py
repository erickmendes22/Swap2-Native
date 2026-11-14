"""Pinned device-observed Build 162 cave-OFF behavior.

172311 (67f92dd): Qualcomm driver 891.14, DM_VK_OQ_SPLIT_PASS=0,
DM_VK_UNUSED_COLOR=1 and DM_VK_ATTACHMENT_PARTS=1; user confirms that
cave walls do not flicker. This is a *visual/device observation*, not a
software-only proof of the underlying driver mechanism, and not a heavy-scene
FPS benchmark. Changes must not alter this fast OFF configuration.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()

class CaveOff162Regression(unittest.TestCase):
    def test_off_has_zero_extra_physical_cave_pass_splits(self):
        # All precise/counted reports remain posted. Only optional
        # *physical* pass-end is under the cave switch and depth-dirty gate.
        start = EXEC.index("static int oq_report(")
        end = EXEC.index("// Query availability", start)
        body = EXEC[start:end]
        self.assertIn("g_oq_split_pass && g_oq_open", body)
        self.assertIn("vka_rp_has_depth() && vka_rp_cave_depth_dirty()", body)
        self.assertIn("oq_close();", body)
        self.assertIn("post((pop){4", body)
        self.assertIn("if (split) vka_rp_cave_end();", body)
        self.assertEqual(body.count("vka_rp_cave_end();"), 1)
        init = EXEC[EXEC.index("g_oq_split_pass ="):EXEC.index("typedef struct { VkCommandBuffer", EXEC.index("g_oq_split_pass ="))]
        self.assertIn('VKA_ENV("DM_VK_OQ_SPLIT_PASS", 0) != 0', init)
        self.assertNotIn('g_oq_split_pass = 1;', init)

    def test_build162_gpu_paths_remain_available_with_cave_split_off(self):
        # These are independent OFF-mode optimizations, NOT hidden forced
        # activation of the cave-split switch.
        self.assertIn('VKA_ENV("DM_VK_UNUSED_COLOR", 0)', DRAW)
        self.assertIn('VKA_ENV("DM_VK_ATTACHMENT_PARTS", 0)', DRAW)
        self.assertIn("vka_attachment_parts_barrier_at(", DRAW)
        self.assertIn("vka_attachment_parts_barrier_at(", TEX)
        self.assertIn("if (R.on && R.color_omitted && !omit_color) vka_rp_end();", DRAW)
        self.assertIn("!g_unused_color_refused", DRAW)
        self.assertIn("g_unused_color_refused = 1;", DRAW)
        self.assertIn('VKA_ENV("DM_VK_ATTACHMENT_PARTS", 0)', EXEC)
        self.assertIn("vka_tex_prepare(g_cb)", EXEC)

    def test_no_new_fragment_replacement_in_fast_cave_off_mode(self):
        # Distinguish actual 162 OFF rendering from a synthetic GPU fixture.
        # Future fragment optimization must be strictly gated when OFF;
        # otherwise it may reproduce Qualcomm-specific flickering.
        if "depth_fs_stub = 1;" not in DRAW:
            return  # stable 162/163 has no such feature; ideal baseline
        start = DRAW.index("if (sh[1] && !strcmp(DM_GAME_ID")
        end = DRAW.index("depth_fs_stub = 1;", start)
        guarded = DRAW[start:end]
        self.assertIn('VKA_ENV("DM_VK_OQ_SPLIT_PASS", 0) != 0', guarded)

if __name__ == "__main__":
    unittest.main()
