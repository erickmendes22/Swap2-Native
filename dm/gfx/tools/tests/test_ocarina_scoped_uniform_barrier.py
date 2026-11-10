"""Conservative Vulkan pipeline barrier refinement for OP_UPDATE_UB.

Inline uniform updates execute VkCmdCopyBuffer outside dynamic rendering and
previously used full ALL_COMMANDS -> ALL_COMMANDS after each transfer.
The replacement only scopes the writers to TRANSFER, leaving every possible
subsequent guest consumer (all stages and read/write) in the destination scope.
Other image and copy dependencies must retain their original full barriers.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()


class TestUniformUpdateTransferBarrier(unittest.TestCase):
    def test_only_the_inline_update_uses_the_new_scope(self):
        update = next(x for x in EXEC.splitlines() if "case OP_UPDATE_UB:" in x)
        self.assertIn("buf_update((const uint8_t *)a + 16, d, n);", update)
        self.assertIn("vka_transfer_write_barrier(g_cb);", update)
        self.assertNotIn("vka_barrier(g_cb)", update)
        self.assertEqual(EXEC.count("vka_transfer_write_barrier(g_cb)"), 1)
        self.assertIn("vk.vkCmdCopyBuffer(g_cb, s.buf, b, 1, &c)", EXEC)

    def test_transfer_write_is_only_source_writer(self):
        pos = TEX.index("void vka_transfer_write_barrier_at(")
        code = TEX[pos:TEX.index("void vka_img_barrier(", pos)]
        self.assertIn(".srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT", code)
        self.assertIn(".dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT", code)
        self.assertIn("VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT", code)
        self.assertIn("if (vka_gp_active) vka_gp_mark(cb, file, line);", code)
        self.assertIn("vka_n_transfer_bar++", code)

    def test_prior_pass_and_general_barrier_untouched(self):
        self.assertIn("vk.vkCmdEndRendering(g_cb);\n    vka_barrier(g_cb);", DRAW)
        self.assertIn("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT", TEX)
        self.assertIn("case OP_CLEAR_BUF: if (g_cb)", EXEC)
        self.assertIn("buf_fill(cb->addr, cb->size, cb->value); vka_barrier(g_cb);", EXEC)
        self.assertIn("buf_copy(s_, d, n); vka_barrier(g_cb);", EXEC)
        self.assertIn("case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);", EXEC)
        self.assertIn("default: if (g_cb && !vka_state_op(&S.d, h.op, a)) vka_rp_end()", EXEC)

    def test_full_destination_consumer_set(self):
        # All Vulkan command types that could touch the guest buffer still
        # fall inside ALL_COMMANDS with both read and write destination access.
        consumers = ("shader uniform read", "storage read", "storage write",
                     "vertex/index fetch", "indirect read", "transfer read", "transfer write")
        for _ in consumers:
            self.assertIn("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT", TEX)
            self.assertIn("VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT", TEX)

    def test_visible_counters_no_new_option(self):
        self.assertIn("Vulkan scoped upload dependencies:", EXEC)
        self.assertIn("vka_n_transfer_bar - tb0", EXEC)
        self.assertIn("vka_transfer_write_barrier_at", HEADER)
        self.assertNotIn("DM_VK_UPDATE_BARRIER", EXEC)


if __name__ == "__main__":
    unittest.main()
