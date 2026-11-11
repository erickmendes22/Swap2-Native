"""Native source regression: a real pass-close uniform flush already publishes writes."""
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[4]
D=(R/"dm/gfx/vk_android/vka_draw.c").read_text()
E=(R/"dm/gfx/vk_android/vka_exec.c").read_text()
T=(R/"dm/gfx/vk_android/vka_tex.c").read_text()

class PostUbBarrier(unittest.TestCase):
    def test_full_publish_before_fallback_skipping(self):
        a=D.index('void vka_rp_end(void) {')
        b=D.index('// OP_BARRIER used to end a render pass',a)
        s=D[a:b]
        self.assertLess(s.index('vk.vkCmdEndRendering(g_cb);'),s.index('const int postub = vka_ub_active();'))
        self.assertLess(s.index('const int postub = vka_ub_active();'),s.index('vka_ub_flush_pass();'))
        self.assertLess(s.index('vka_ub_flush_pass();'),s.index('const int reused = postub'))
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")',s)
        self.assertIn('DM_VK_OOT_POSTUB_BAR_DEDUP',s)
        self.assertIn('g_rp_full++; vka_barrier(g_cb);',s)
        self.assertIn('g_rp_graphics++; vka_graphics_write_barrier(g_cb);',s)
        self.assertIn('g_rp_scoped++; vka_attachment_write_barrier(g_cb);',s)
        self.assertIn('g_rp_force_full',s)

    def test_real_flush_orders_copies_and_all_consumers(self):
        a=E.index('void vka_ub_flush_pass(void)')
        b=E.index('// ---------- Clears ----------',a)
        s=E[a:b]
        self.assertLess(s.index('vka_barrier(g_cb);'),s.index('buf_update(&g_inline_ub, w->bytes'))
        self.assertLess(s.index('buf_update(&g_inline_ub, w->bytes'),s.index('ub_flush(&g_inline_ub);'))
        self.assertIn('vka_transfer_write_barrier(g_cb);',E)
        self.assertIn('VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT',T)
        self.assertIn('g_ub_np = 0; g_ub_seq++;',s)

if __name__=="__main__": unittest.main()
