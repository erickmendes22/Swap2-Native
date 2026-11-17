"""Conservative static guards on single-walk Ocarina mesh lookahead.

The source test intentionally does NOT claim GPU/FPS performance: only
real Adreno 840 A/B can establish that. It enforces command eligibility,
ordering, and the rollback for all other shader pairs.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka_oot_mesh_pair.h").read_text()

class MeshSinglePassSafety(unittest.TestCase):
    def test_single_walk_with_lazy_begin_only_after_first_eligible_mesh(self):
        scan = EXEC.split("static void memu_scan(const uint8_t *p) {",1)[1].split(
            "static void memu_before_draw(",1)[0]
        walk = EXEC.split("static int memu_walk(const uint8_t *p, int phase) {",1)[1].split(
            "static void memu_scan(",1)[0]
        self.assertIn("g_memu_cover = 1;", scan)
        self.assertIn("if (S.rc_skip) return;", scan)
        self.assertEqual(scan.count("memu_walk(p, MEMU_ADD)"), 1)
        self.assertNotIn("memu_walk(p, -1)", scan.split("if (!memu_walk(p, MEMU_ADD))")[0].replace(
            "// The former memu_walk(-1)", ""))
        self.assertNotIn("vka_memu_batch(MEMU_BEGIN", scan)
        self.assertIn("if (phase == MEMU_ADD && n == 0)", walk)
        self.assertIn("vka_memu_batch(MEMU_BEGIN, NULL, NULL, NULL, 0);", walk)
        self.assertLess(walk.index("if (n == 128) break;"), walk.index("if (phase == MEMU_ADD && n == 0)"))
        self.assertLess(walk.index("vka_memu_batch(MEMU_BEGIN"),walk.index("vka_memu_batch(phase, &g_memu_st, d, p, n)"))
        self.assertIn('vka_gp_mark(g_cb, "MEMU_START", 0)', walk)

    def test_guest_dependency_boundaries_unchanged(self):
        walk = EXEC.split("static int memu_walk(",1)[1].split("static void memu_scan(",1)[0]
        for s in ["if (!memu_allowed(h.op) || h.size < 8)",
                  "if (route == 0)", "if (n == 128) break;",
                  "vka_state_op(&g_memu_st, h.op, a)",
                  "g_memu_boundary_op[h.op]++"]:
            self.assertIn(s, walk)
        scan = EXEC.split("static void memu_scan(",1)[1].split("static void memu_before_draw(",1)[0]
        for phase in ("MEMU_SETUP", "MEMU_DIST", "MEMU_END"):
            self.assertIn("vka_memu_batch("+phase,scan)
        for phase in ("MEMU_TASK", "MEMU_MESH"):
            self.assertIn("vka_memu_batch_snapshot("+phase,scan)
            self.assertIn("memu_walk(p, "+phase+")",scan)

    def test_native_pair_only_with_driver_features_and_opt_in(self):
        route = DRAW.split("int vka_mesh_route(const vka_dstate *d) {",1)[1].split(
            "// A/B-only patch",1)[0]
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT_MESH_NATIVE", 0)',route)
        self.assertIn("V.mesh && V.task",route)
        self.assertIn("oot_hot_native_pair_state(d)) return 0;",route)
        self.assertIn("return 1;",route)
        self.assertIn("vka_oot_hot_native_mesh_pair(ms->key, fs->key)", DRAW)
        self.assertIn("0xeb021183bf9b0092",HEADER)
        self.assertIn("0x087ef21b3a72ad3a",HEADER)
        self.assertIn("0xfed302d791a4ba43",HEADER)
        self.assertIn("0x0fb4823639295a2d",HEADER)

if __name__ == "__main__":
    unittest.main()
