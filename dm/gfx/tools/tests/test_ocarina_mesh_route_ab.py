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
        self.assertIn('VKA_ENV("DM_VK_OOT_MESH_ROUTE", 0)', draw)
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

    def test_launcher_and_reset_are_connected(self):
        pref = (APP / "Prefs.java").read_text()
        game = (APP / "GameActivity.java").read_text()
        ui = (APP / "GameSettings.java").read_text()
        self.assertIn('gameKey("oot_mesh_route", titleId), 0', pref)
        self.assertIn("DM_VK_OOT_MESH_ROUTE=", game)
        self.assertIn("Prefs.ocarinaMeshRoute(a, id)", ui)
        self.assertIn("meshRouteDialog(a, g, again)", ui)
        self.assertIn('.remove(Prefs.gameKey("oot_mesh_route", id))', ui)

if __name__ == "__main__":
    unittest.main()
