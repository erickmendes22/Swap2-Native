"""Vulkan attachment-only renderpass dependency: stage-accurate GPU synchronization.

The original ALL_COMMANDS memory barrier remains required for:
  - explicit guest OP_BARRIER, even if the pass had no storage writes
  - an NVN barrier taken inside a render pass only when it also involved shader writes
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
        self.assertIn("int full = g_rp_force_full || had_clears || vka_nan_on();", DRAW)
        self.assertIn("int pending_attachment = R.bar_pending && !full && !R.swrite;", DRAW)
        self.assertIn("else { g_rp_graphics++; vka_graphics_write_barrier(g_cb); }", DRAW)
        self.assertIn("DM_VK_OOT_POSTUB_BAR_DEDUP", DRAW)
        self.assertIn("const int postub = vka_ub_active();", DRAW)
        self.assertIn('R.swrite && VKA_ENV("DM_VK_OOT_FPS_BOOST", 0) <= 0', DRAW)
        self.assertIn("if (!R.swrite && draw_writes(sh, d)) R.swrite = 1;", DRAW)
        self.assertIn("R.bar_pending = 1;", DRAW)
        self.assertIn("vka_oq_pass_end();", DRAW)
        self.assertIn("vk.vkCmdEndRendering(g_cb);", DRAW)
        self.assertLess(DRAW.index("vk.vkCmdEndRendering(g_cb);"), DRAW.index('if (full || (R.swrite && VKA_ENV("DM_VK_OOT_FPS_BOOST", 0) <= 0)) {'))
        self.assertIn("else { g_rp_scoped++; vka_attachment_write_barrier(g_cb); }", DRAW)
        self.assertIn("if (pending_attachment) g_rp_pending_attachment++;", DRAW)
        self.assertIn("pass-end barriers: %.1f attachment-scoped, %.1f graphics-shader-scoped, %.1f full/frame", DRAW)
        self.assertIn("pending-attachment scoped %.1f/frame", DRAW)

    def test_conservative_case_matrix(self):
        for guest in (False, True):
            for pending in (False, True):
                for storage in (False, True):
                    for clears in (False, True):
                        for diagnostic in (False, True):
                            full = guest or clears or diagnostic or (pending and storage)
                            # If this pass wrote storage and boost is off,
                            # the full dependency remains. The lower-level
                            # code may select ALL_GRAPHICS with FPS Boost.
                            graphics = storage and not full
                            attachments = not full and not graphics
                            self.assertEqual(int(full) + int(graphics) + int(attachments), 1)
                            if full:
                                self.assertTrue(guest or clears or diagnostic or (pending and storage))
                            if graphics:
                                self.assertTrue(storage)
                                self.assertFalse(guest or clears or diagnostic or pending)

    def test_memu_interphase_hazards_use_only_compute_and_indirect_consumers(self):
        # Scope changes ONLY the internal staging dependencies, not guest
        # barriers or the final dependency protecting fragment/vertex/copies.
        memu = (ROOT / "dm/gfx/vk_android/vka_memu_draw.inc").read_text()
        begin = TEX.index("void vka_memu_interphase_barrier_at(")
        end = TEX.index("void vka_transfer_write_barrier_at(", begin)
        narrow = TEX[begin:end]
        self.assertIn("VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT", narrow)
        self.assertIn("VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT", narrow)
        self.assertIn("VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT", narrow)
        self.assertIn("VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT", narrow)
        self.assertIn("VK_ACCESS_INDIRECT_COMMAND_READ_BIT", narrow)
        self.assertNotIn("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT", narrow)
        self.assertIn("vka_n_memu_interphase_bar++", narrow)
        self.assertIn("vka_memu_interphase_barrier_at", HEADER)
        self.assertIn("#define vka_memu_interphase_barrier(cb)", HEADER)
        self.assertIn('VKA_ENV("DM_VK_MEMU_INTERPHASE_SCOPE", 1)', memu)
        self.assertIn('VKA_ENV("DM_VK_MEMU_SCOPED_BAR", 1)', memu)
        self.assertIn("case MEMU_SETUP: vka_barrier(g_cb);", memu)
        self.assertIn("memu_helper(0); memu_phase_barrier(1);", memu)
        self.assertIn("if (MB.task_draws) { memu_phase_barrier(1); memu_helper(1); memu_phase_barrier(1); }", memu)
        self.assertIn("case MEMU_END: memu_phase_barrier(0);", memu)
        self.assertIn("else\n        vka_compute_write_barrier(g_cb);", memu)
        # Synthetic per-batch hazard matrix: setup->task, task->distribution,
        # distribution->mesh, or setup->mesh for taskless batches. All use
        # only compute shader accesses and indirect-dispatch argument reads.
        for task_draws in range(0, 129):
            edges = [("setup", "task"), ("task", "distribution"),
                     ("distribution", "mesh")] if task_draws else [("setup", "mesh")]
            for producer, consumer in edges:
                self.assertIn(consumer, ("task", "distribution", "mesh"))
                self.assertIn(producer, ("setup", "task", "distribution"))
            # Final mesh->raster cannot use the narrow dependency.
            self.assertNotIn(("mesh", "raster"), edges)

    def test_mesh_scoped_stats_are_valid_c_lines(self):
        # Reject accidental literal backslash-n tokens outside the C string.
        # This happened in the first APK job even though source-level tests passed.
        at = EXEC.index('Ocarina mesh staging:')
        frag = EXEC[at:EXEC.index('static uint64_t overlap0', at)]
        self.assertNotIn(chr(92) + 'n', frag)
        self.assertIn('mi0 = vka_n_memu_interphase_bar;', frag)

    def test_no_shader_library_or_new_toggle(self):
        self.assertIn("vka_attachment_write_barrier_at", HEADER)
        self.assertNotIn("DM_VK_RP_SCOPE", DRAW)
        self.assertNotIn("DM_VK_RP_SCOPE", TEX)

if __name__ == "__main__":
    unittest.main()
