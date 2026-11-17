"""Ocarina zero direct draw regression: runtime safety and no shader rebuild."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka_zero_draw_elide.h").read_text()

class ZeroDirectDrawTests(unittest.TestCase):
    def test_early_exit_precedes_resources_queries_and_pass(self):
        fn = DRAW.split("void vka_draw(vka_dstate *d,", 1)[1].split("void vka_dispatch(", 1)[0]
        early = fn.index("if (vka_oot_zero_direct_draw(&z))")
        self.assertLess(early, fn.index("vka_shader *sh"))
        self.assertLess(early, fn.index("if (!rp_begin("))
        self.assertLess(early, fn.index("vka_oq_draw();"))
        block = fn[early:fn.index("vka_shader *sh", early)]
        self.assertNotIn("g_skipped++", block)

    def test_opt_in_is_live_and_ocarina_only(self):
        fn = DRAW.split("void vka_draw(vka_dstate *d,", 1)[1]
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', fn)
        self.assertIn('VKA_ENV("DM_VK_OOT_ZERO_DRAW_ELIDE", 0)', fn)
        self.assertNotIn("static int oot_zero_mode", fn)
        self.assertIn("dw && dw->prim == NVN_PRIM_MESH", fn)

    def test_deferred_clears_occlusion_and_indirect_kept(self):
        self.assertIn("if (PC.n) pc_flush();", DRAW)
        self.assertIn("PC.c[PC.n++] = *c;", DRAW)
        self.assertIn("vka_oq_pass_end();", DRAW)
        self.assertIn("oq_sk1(sk);", EXEC)
        self.assertIn("!c->indirect && !c->multidraw_count", HEADER)
        self.assertNotIn("pass_open", HEADER)
        self.assertNotIn("pending_clears", HEADER)

if __name__ == "__main__":
    unittest.main()
