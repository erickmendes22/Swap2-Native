"""GPU-generated mesh draw diagnostics must not claim a zero-vertex raster pass."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
PROF = (ROOT / "dm/gfx/vk_android/vka_gprof.c").read_text()
MEMU = (ROOT / "dm/gfx/vk_android/vka_memu_draw.inc").read_text()

class GpuIndirectProof(unittest.TestCase):
    def test_profiling_separates_guest_count_from_real_indirect_gpu_args(self):
        self.assertIn("memu_e ? 2 : (ind != 0 ? 1 : 0)", DRAW)
        self.assertIn("guest_mesh_record_count", PROF)
        self.assertIn("GPU-generated-indirect-count-UNKNOWN", PROF)
        self.assertIn("g_first_indirect = (uint32_t)indirect;", PROF)
        self.assertIn("memu_e->ms->key", DRAW)

    def test_real_command_indirect_and_unchanged(self):
        self.assertIn("vk.vkCmdDrawIndexedIndirect(g_cb, MB.rec.buf, ro, 1, 20)", DRAW)
        self.assertIn("vk.vkCmdDrawIndirect(g_cb, MB.rec.buf, ro, 1, 16)", DRAW)
        self.assertIn("VkDeviceSize ro = MB.rec.off", DRAW)
        self.assertIn("VKA_MEMU_R_DRAW", DRAW)
        self.assertIn("r[VKA_MEMU_R_COUNT] = dw->count > 0", MEMU)

    def test_targeted_forensic_logs_only_sampled_passes(self):
        self.assertIn("if (vka_gp_active && sh[1] &&", DRAW)
        self.assertIn("Ocarina 720p zero-pass forensic:", DRAW)
        self.assertIn("0x087ef21b3a72ad3a", DRAW)
        self.assertIn("0x0fb4823639295a2d", DRAW)
        self.assertIn('memu_e ? (memu_e->indexed ? "DrawIndexedIndirect"', DRAW)
        self.assertIn("g_scene.indirect += indirect != 0;", PROF)

    def test_true_gpu_invocations_remain_opt_in_and_not_faked(self):
        self.assertIn('VKA_ENV("DM_VK_SCENE_PASS_DIAG", 0) >= 2', PROF)
        self.assertIn("fragment-invocations=%llu", PROF)
        self.assertIn("vertex-invocations=%llu", PROF)
        self.assertNotIn('VKA_ENV("DM_VK_SCENE_PASS_DIAG", 2)', PROF)

if __name__ == "__main__":
    unittest.main()
