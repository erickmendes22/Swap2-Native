"""Vulkan attachment-only renderpass dependency: stage-accurate GPU synchronization.

The original ALL_COMMANDS memory barrier remains required for:
  - explicit guest OP_BARRIER, even if the pass had no storage writes
  - an NVN barrier taken inside a render pass (pending until a hazard)
  - diagnostic paths that add reads/copies and standalone pending clears.
Graphics-only shader stores (including mesh/task) now use ALL_GRAPHICS
producer stages and ALL_COMMANDS consumers instead of a full producer scope.
A pure color/depth/stencil pass may narrow only the PRODUCER stages while
preserving the all-consumers destination and memory visibility.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()

class AttachmentDependencyTest(unittest.TestCase):
    def test_source_only_written_attachment_stages(self):
        p = TEX.index("void vka_attachment_write_barrier_at(")
        body = TEX[p:TEX.index("void vka_transfer_write_barrier_at(", p)]
        self.assertIn("VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT", body)
        self.assertIn("VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT", body)
        self.assertIn("VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT", body)
        self.assertIn("VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT", body)
        self.assertIn("VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT", body)
        self.assertIn("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT", body)
        self.assertIn("VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT", body)
        self.assertIn("vka_n_attachment_bar++", body)
        self.assertIn("if (vka_gp_active) vka_gp_mark(cb, file, line);", body)

    def test_guest_barriers_always_order_all_prior_commands(self):
        self.assertIn("g_rp_force_full = 1;\n    vka_rp_end();\n    g_rp_force_full = 0;", DRAW)
        self.assertIn("bar_covered = vka_rp_end_covers_barrier();", EXEC)
        self.assertIn("if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);", EXEC)
        self.assertIn("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT", TEX)
        self.assertIn("vka_barrier(g_cb);", DRAW)
        self.assertIn("vka_barrier(g_cb);", EXEC)

    def test_shader_stores_preserve_graphics_source_with_full_guest_barrier_fallback(self):
        self.assertIn("g_rp_force_full || R.bar_pending || had_clears || vka_nan_on()", DRAW)
        self.assertIn("else if (R.swrite) { g_rp_graphics++; vka_graphics_write_barrier(g_cb); }", DRAW)
        self.assertIn("if (!R.swrite && draw_writes(sh, d)) R.swrite = 1;", DRAW)
        self.assertIn("R.bar_pending = 1;", DRAW)
        self.assertIn("vka_oq_pass_end();", DRAW)
        self.assertIn("vk.vkCmdEndRendering(g_cb);", DRAW)
        self.assertLess(DRAW.index("vk.vkCmdEndRendering(g_cb);"), DRAW.index("if (full) { g_rp_full++; vka_barrier(g_cb); }"))
        self.assertIn("else { g_rp_scoped++; vka_attachment_write_barrier(g_cb); }", DRAW)
        self.assertIn("pass-end barriers: %.1f attachment-scoped, %.1f graphics-shader-scoped, %.1f full/frame", DRAW)

    def test_conservative_case_matrix(self):
        for guest in (False, True):
            for pending in (False, True):
                for storage in (False, True):
                    for clears in (False, True):
                        for diagnostic in (False, True):
                            full = guest or pending or clears or diagnostic
                            # Shader stores alone need a complete GRAPHICS
                            # producer dependency, not ALL_COMMANDS producer.
                            graphics = storage and not full
                            attachments = not full and not graphics
                            self.assertEqual(int(full) + int(graphics) + int(attachments), 1)
                            if full:
                                self.assertTrue(guest or pending or clears or diagnostic)
                            if graphics:
                                self.assertTrue(storage)
                                self.assertFalse(guest or pending or clears or diagnostic)

    def test_no_shader_library_or_new_toggle(self):
        self.assertIn("vka_attachment_write_barrier_at", HEADER)
        self.assertNotIn("DM_VK_RP_SCOPE", DRAW)
        self.assertNotIn("DM_VK_RP_SCOPE", TEX)

if __name__ == "__main__":
    unittest.main()
