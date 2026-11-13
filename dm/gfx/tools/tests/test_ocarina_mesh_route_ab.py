"""Ocarina Snapdragon 891.14 mesh routing regression contracts.
These source checks catch launcher-only toggles and unintended depth cuts;
real SPIR-V shader testing lives in t_android_mesh_invariant.c.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"
APP = ROOT / "android/app/src/main/java/dev/nxnative/android"

class MeshRouteAB(unittest.TestCase):
    def test_qualcomm_has_native_features_but_supplement_stays_compute(self):
        dev = (VK / "vka_dev.c").read_text()
        draw = (VK / "vka_draw.c").read_text()
        self.assertIn("x_mesh && fmesh.meshShader", dev)
        self.assertIn("V.task = V.mesh && fmesh.taskShader", dev)
        self.assertIn("qcom_ocarina", dev)
        self.assertIn("DM_VK_OOT_MESH_ROUTE", dev)
        self.assertIn('return hybrid ? (supplement ? 1 : 0)', draw)

    def test_all_three_routes_without_default_regression(self):
        draw = (VK / "vka_draw.c").read_text()
        self.assertIn('VKA_ENV("DM_VK_OOT_MESH_ROUTE", -1)', draw)
        self.assertIn("if (test_route == -1) return V.memu ? 1 : 0;", draw)
        self.assertIn("if (test_route == 1 && V.memu) return 1;", draw)
        self.assertIn("if (test_route == 2 && V.mesh && V.task) return 0;", draw)
        self.assertIn("if (supplement && !vegetation_on) return -1;", draw)

    def test_invariant_only_for_native_test_and_no_depth_skip(self):
        shader = (VK / "vka_shader.c").read_text()
        patch = (VK / "vka_spvpatch.c").read_text()
        draw = (VK / "vka_draw.c").read_text()
        self.assertIn("vka_spv_mesh_position_invariant(", shader)
        self.assertIn('VKA_ENV("DM_VK_OOT_MESH_ROUTE", 0) == 2', shader)
        self.assertIn("OpMemberDecorate", patch)
        self.assertIn("DecInvariant = 18", patch)
        self.assertIn('if (vegetation_cut(d, sh)) return;', draw)
        self.assertIn("vk.vkCmdDrawMeshTasksEXT", draw)
        # Depth prepasses are *not* cut or relaxed: fog/shadow depend on them.
        self.assertNotIn("mesh_cut(d, rt", draw)
        self.assertNotIn("vkpp_prepass(", draw)

    def test_removed_diagnostic_ui_cannot_override_compute_route(self):
        ui = (APP / "GameSettings.java").read_text()
        pref = (APP / "Prefs.java").read_text()
        game = (APP / "GameActivity.java").read_text()
        self.assertNotIn('private static void meshRouteDialog(', ui)
        self.assertNotIn('"Execução da vegetação (GPU)"', ui)
        self.assertNotIn('meshRouteDialog(a, g, again)', ui)
        self.assertIn('return OCARINA_TITLE.equals(titleId) ? 1 : -1;', pref)
        self.assertIn('static void ocarinaMeshRoute(Context c, String titleId, int mode) { /* retired */ }', pref)
        self.assertIn('"DM_VK_OOT_MESH_ROUTE=" + Prefs.ocarinaMeshRoute(this, id)', game)
        # Advanced env remains available for driver diagnosis, but old UI
        # preferences can no longer select a broken native mesh mode.
        self.assertIn('VKA_ENV("DM_VK_OOT_MESH_ROUTE", -1)', (VK / "vka_draw.c").read_text())

if __name__ == "__main__":
    unittest.main()
