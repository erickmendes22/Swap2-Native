"""Source-order and sparse-GPU-timing invariants for per-draw hotspot research.

The new Vulkan timestamps only run when DM_VK_OOT_GFX_FINE is enabled AND
an existing sampled profiler frame is active. They must not change draw
commands, screen resolution, attachments, barriers, pipeline ABI or render
condition semantics. These are structural tests, not Android FPS evidence.
"""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
P=(ROOT/"dm/gfx/vk_android/vka_gprof.c").read_text()
D=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
class FineGpuHotDraw(unittest.TestCase):
    def test_opt_in_1280x720_and_sampled_frame_only(self):
        f=P.split("void vka_gp_pass(",1)[1].split("void vka_gp_part(",1)[0]
        self.assertIn('VKA_ENV("DM_VK_OOT_GFX_FINE", 0)',f)
        self.assertIn('g_pass_1280;',f)
        self.assertIn('g_gfx_enabled = !g_gfx_fine',f)
        x=P.split("void vka_gp_draw(",1)[1].split("void vka_gp_compute(",1)[0]
        self.assertIn('g_gfx_fine && vka_gp_active && g_cb && g_n < NQ - 16',x)
        self.assertIn('mark(g_cb, 0, "GFX_DRAW", 0);',x)
        self.assertIn('m->gfx_pass_id = (uint16_t)g_seen_1280;',x)
        self.assertIn('m->gfx_draw_id = g_pass_draws;',x)
    def test_pass_report_not_lost_and_chunks_still_work(self):
        self.assertIn('!strcmp(file, "GFX_CHUNK") || !strcmp(file, "GFX_DRAW")',P)
        self.assertIn('m->gfx_block = 2;',P)
        self.assertIn('if (m->gfx_block != 1) continue;',P)
        self.assertIn('g_m[j].gfx_block',P)
        self.assertIn('gpu prof 1280x720 FINE draw:',P)
        self.assertIn('gpu prof 1280x720 FINE summary:',P)
        self.assertIn('g_gfx_enabled = 0; g_gfx_fine = 0;',P)
    def test_bounded_and_preserves_original_draw_path(self):
        self.assertIn('enum { NQ = 8192',P)
        self.assertIn('if (g_n >= NQ) return;',P)
        for cmd in ("vk.vkCmdDrawIndexedIndirect(g_cb, MB.rec.buf, ro, 1, 20);",
                    "vk.vkCmdDraw(g_cb, (uint32_t)dw->count, inst, (uint32_t)dw->first, binst);"):
            self.assertIn(cmd,D)
        self.assertIn('vka_gp_draw(sh[0] ? sh[0]->key : 0,',D)
if __name__=="__main__":
    unittest.main()
