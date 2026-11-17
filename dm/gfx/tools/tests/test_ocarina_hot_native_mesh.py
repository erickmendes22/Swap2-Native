"""Native mesh A/B is exact-pair only and OFF without explicit opt-in."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[4]
SRC = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
HDR = (ROOT / "dm/gfx/vk_android/vka_oot_mesh_pair.h").read_text()
class NativeMeshPairSafety(unittest.TestCase):
    def test_exact_pair_and_driver_guard(self):
        start = SRC.index("int vka_mesh_route(const vka_dstate *d)")
        route = SRC[start:SRC.index("// A/B-only patch",start)]
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT_MESH_NATIVE", 0)',route)
        self.assertIn("V.mesh && V.task",route)
        self.assertIn("oot_hot_native_pair_state(d)) return 0;",route)
        self.assertIn("return 1;",route)
        self.assertIn("vka_oot_hot_native_mesh_pair(ms->key, fs->key)",SRC)
        for key in ("0xeb021183bf9b0092","0x087ef21b3a72ad3a",
                    "0xfed302d791a4ba43","0x0fb4823639295a2d"):
            self.assertIn(key,HDR)
    def test_same_route_in_lookahead_and_replay(self):
        self.assertIn("int route = vka_mesh_route(d);", SRC)
        self.assertIn("vka_mesh_route(&g_memu_st)", EXEC)
        self.assertIn("vka_mesh_route(&S.d)",EXEC)
        self.assertIn("if (route == 0)",EXEC)
        self.assertIn("if (route == 1 && V.memu)",SRC)
    def test_existing_gpu_commands_unchanged(self):
        self.assertIn("vk.vkCmdDrawMeshTasksIndirectEXT(g_cb, mi.buf, mi.off, 1, 12)",SRC)
        self.assertIn("vk.vkCmdDrawIndexedIndirect(g_cb, MB.rec.buf, ro, 1, 20)",SRC)
        self.assertIn("DM_VK_OOT_MESH_ROUTE",SRC)
if __name__ == "__main__":
    unittest.main()
