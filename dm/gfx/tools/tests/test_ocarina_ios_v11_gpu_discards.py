"""Static structural checks for explicit NVN attachment discard in Ocarina iOS V11.

Run without games, shaders, Android toolchain, or a GPU. These checks guard
source-level invariants; only a device run can measure GPU time or rendering.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
NVN = (ROOT / "dm/gfx/nvn/hle_nvn.c").read_text()
OPS = (ROOT / "dm/gfx/nvn/nvn_obj.h").read_text()
CAP = (ROOT / "dm/gfx/nvn/nvn_capture.c").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()


class TestExplicitVulkanDiscard(unittest.TestCase):
    def test_backward_compatible_opcodes(self):
        self.assertIn("OP_PUSH_CONST, OP_DISCARD_COLOR, OP_DISCARD_DS, OP_COUNT_", OPS)

    def test_capture_walker_tracks_new_records(self):
        self.assertIn("OP_COUNT_ == 56", CAP)
        self.assertIn("ops 56", CAP)
        self.assertIn("case OP_DISCARD_COLOR: case OP_DISCARD_DS:", CAP)

    def test_android_only_guest_recording(self):
        self.assertIn("*REC(c, OP_DISCARD_COLOR, int32_t) = i;", NVN)
        self.assertIn("*REC(c, OP_DISCARD_DS, uint64_t) = 0;", NVN)
        self.assertIn("#if defined(__ANDROID__)", NVN)

    def test_guest_replay_preserves_order(self):
        self.assertIn("case OP_DISCARD_COLOR: case OP_DISCARD_DS: break;", EXEC)
        self.assertIn("vka_rp_discard(&S.rt, S.has_rt, index)", EXEC)
        self.assertIn("vka_rp_discard(&S.rt, S.has_rt, -1)", EXEC)
        self.assertIn("if (R.on || PC.n) vka_rp_end();", DRAW)

    def test_discard_loads_exact_view_only(self):
        self.assertIn("im->discard_level == level", TEX)
        self.assertIn("im->discard_layer == layer", TEX)
        self.assertIn("im->discard_layers == layers", TEX)
        self.assertIn("if (im->gpu_owned)", TEX)
        self.assertIn("im->discard_aspect = 0; // a GPU write invalidates", TEX)
        self.assertIn("ca[i].loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE", DRAW)

    def test_store_opt_is_only_for_immediate_new_pass(self):
        self.assertEqual(
            EXEC.count("!vka_rp_is_open() && h.size >= 8 ? immediate_discards(p + h.size, &d) : 0"),
            2,
        )
        self.assertIn("if (h.size != 16) break;", EXEC)
        self.assertIn("else break;\n        next += h.size;", EXEC)
        self.assertEqual(EXEC.count("vka_rp_predict_discard(0, 0); oq_sk1(sk);"), 2)
        self.assertIn("g_store_discard_colors & (1u << i)", DRAW)
        self.assertIn("g_store_discard_depth ? VK_ATTACHMENT_STORE_OP_DONT_CARE", DRAW)

    def test_no_fps_cap_or_new_gpu_toggle(self):
        self.assertNotIn("DM_VK_STORE_DISCARD", DRAW)
        self.assertNotIn("DM_VK_DISCARD", DRAW)
        self.assertIn("loads avoided %.1f/frame, stores avoided %.1f/frame", DRAW)


if __name__ == "__main__":
    unittest.main()
