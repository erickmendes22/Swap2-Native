"""Static regression checks for the NVN explicit-discard Vulkan optimization.

These require no shaders, game files, Android toolchain or GPU.
They do not establish that a particular game calls the discard operations.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
OBJ = (ROOT / "dm/gfx/nvn/nvn_obj.h").read_text()
NVN = (ROOT / "dm/gfx/nvn/hle_nvn.c").read_text()
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()


class ExplicitAttachmentDiscard(unittest.TestCase):
    def test_old_opcode_numbers_not_renumbered(self):
        self.assertIn("OP_ALPHA_REF, OP_PUSH_CONST, OP_DISCARD_COLOR, OP_DISCARD_DS, OP_COUNT_", OBJ)

    def test_guest_discard_records_are_replayed(self):
        self.assertIn("*REC(c, OP_DISCARD_COLOR, int32_t) = i;", NVN)
        self.assertIn("*REC(c, OP_DISCARD_DS, uint64_t) = 0;", NVN)
        self.assertIn("vka_rp_discard(&S.rt, S.has_rt, index)", EXEC)
        self.assertIn("vka_rp_discard(&S.rt, S.has_rt, -1)", EXEC)
        self.assertIn("if (R.on || PC.n) vka_rp_end();", DRAW)

    def test_discards_only_match_exact_attachment_subresources(self):
        self.assertIn("im->discard_level == level", TEX)
        self.assertIn("im->discard_layer == layer", TEX)
        self.assertIn("im->discard_layers == layers", TEX)
        self.assertIn("if (im->gpu_owned)", TEX)
        self.assertIn("im->discard_aspect = 0;  // write", TEX)

    def test_vulkan_load_can_be_discarded_but_store_stays(self):
        self.assertIn("ca[i].loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;", DRAW)
        self.assertIn(".loadOp = discarded ? VK_ATTACHMENT_LOAD_OP_DONT_CARE : VK_ATTACHMENT_LOAD_OP_LOAD", DRAW)
        self.assertIn(".storeOp = VK_ATTACHMENT_STORE_OP_STORE", DRAW)
        self.assertIn("render-pass loads avoided", DRAW)
        self.assertNotIn("DM_VK_DISCARD", DRAW)


if __name__ == "__main__":
    unittest.main()
