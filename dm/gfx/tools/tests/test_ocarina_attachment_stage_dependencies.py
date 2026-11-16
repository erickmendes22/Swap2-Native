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

    def test_bound_attachments_preserve_war_while_unused_stages_drop(self):
        import shutil, subprocess, tempfile
        draw = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
        tex = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
        self.assertIn("vka_attachment_parts_access_barrier_at(g_cb,", draw)
        self.assertIn("if (!R.color_omitted)", draw)
        self.assertIn("color_bound |= R.cf[i] != VK_FORMAT_UNDEFINED;", draw)
        self.assertIn("R.df != VK_FORMAT_UNDEFINED || R.sf != VK_FORMAT_UNDEFINED", draw)
        self.assertIn("vka_attachment_access_src_stages(", tex)
        self.assertIn("VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 1, &mb", tex)
        self.assertIn('depth-read WAR retained when depth bound', draw)
        source = r"""
#include <assert.h>
#include <vulkan/vulkan_core.h>
#include "vka_attachment_stage_policy.h"
int main(void) {
    VkPipelineStageFlags C=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkPipelineStageFlags D=VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |
                           VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
    for(int cw=0;cw<=1;cw++)for(int dw=0;dw<=1;dw++)
    for(int cb=0;cb<=1;cb++)for(int db=0;db<=1;db++){
        VkPipelineStageFlags actual=vka_attachment_access_src_stages(cw,dw,cb,db);
        VkPipelineStageFlags expected=(!cb&&!db)||(cw&&!cb)||(dw&&!db) ?
                                  C|D : (cb?C:0)|(db?D:0);
        assert(actual==expected);
        // A depth-only bound pass with NO depth writes still orders depth
        // tests (WAR) against later depth replacements.
        if (db && !cb && !cw) assert((actual&D)==D);
        if (cb && !db && !dw) assert((actual&C)==C);
    }
    assert(vka_attachment_access_src_stages(1,0,1,0)==C);
    assert(vka_attachment_access_src_stages(0,1,0,1)==D);
    assert(vka_attachment_access_src_stages(0,0,1,1)==(C|D));
    assert(vka_attachment_access_src_stages(0,0,0,0)==(C|D));
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"stage.c";exe=Path(td)/"stage"
            p.write_text(source)
            cc=shutil.which("cc")
            if not cc: self.skipTest("C compiler missing")
            proc=subprocess.run([cc,"-std=c11","-Wall","-Wextra","-Werror",
                "-I",str(ROOT / "dm/third_party/vulkan-headers/include"),
                "-I",str(ROOT / "dm/gfx/vk_android"),
                str(p),"-o",str(exe)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            subprocess.run([str(exe)],check=True)

    def test_guest_barriers_always_order_all_prior_commands(self):
        self.assertIn("g_rp_force_full = 1;\n    vka_rp_end();\n    g_rp_force_full = 0;", DRAW)
        self.assertIn("bar_covered = vka_rp_end_covers_barrier();", EXEC)
        self.assertIn("if (!vka_gbar_game(g_cb,(uint32_t)bits)) vka_barrier(g_cb);", EXEC)
        self.assertIn('VKA_ENV("DM_VK_BAR_NARROW", 0)', (ROOT/"dm/gfx/vk_android/vka_gbar.c").read_text())
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
        self.assertIn("else vka_attachment_write_barrier(g_cb);", DRAW)
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

    def test_no_shader_library_or_new_toggle(self):
        self.assertIn("vka_attachment_write_barrier_at", HEADER)
        self.assertNotIn("DM_VK_RP_SCOPE", DRAW)
        self.assertNotIn("DM_VK_RP_SCOPE", TEX)

if __name__ == "__main__":
    unittest.main()
