"""Ocarina scene GPU profiler does not change normal rasterization.

The pass duration (~14ms) is not all avoidable: shaders, vertex work, depth
and the 720p presentation must remain untouched. This source guard checks
that timestamps divide 683x384 graphics passes only on sampled frames and
that mixed-fragment batches are not attributed to a single shader.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


class SceneChunkProfile(unittest.TestCase):
    def test_bound_to_existing_sparse_profiler_and_scene_dimensions(self):
        code = (VK / "vka_gprof.c").read_text()
        self.assertIn('enum { GFX_CHUNK = 16 };', code)
        self.assertIn('if (g_gfx_enabled && vka_gp_active', code)
        self.assertIn('VKA_ENV("DM_VK_OOT_GFX_CHUNKS", 1)', code)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', code)
        self.assertIn('!strncmp(desc, "683x384x1"', code)
        self.assertIn('g_n >= NQ - 16', code)
        self.assertIn('VKA_ENV("DM_VK_GPUPROF",', code)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000") ? 300 : 0', code)

    def test_stamps_after_draws_and_before_rendering_end(self):
        profiler = (VK / "vka_gprof.c").read_text()
        draw = (VK / "vka_draw.c").read_text()
        hdr = (VK / "vka.h").read_text()
        self.assertIn('if (g_gfx_n == GFX_CHUNK) gfx_chunk_flush();', profiler)
        self.assertIn('mark(g_cb, 0, "GFX_CHUNK", 0);', profiler)
        self.assertIn('void vka_gp_gfx_flush(void);', hdr)
        p = draw.index('void vka_rp_end(void)')
        end = draw.index('vk.vkCmdEndRendering(g_cb)', p)
        self.assertIn('if (vka_gp_active) vka_gp_gfx_flush();', draw[p:end])
        # Never move/add/end guest draws, change attachments, viewport,
        # shader bytes or content: the profiler is observation-only.
        self.assertIn('g_gfx_enabled = !strcmp', profiler)

    def test_full_pass_report_and_mixed_blocks_remain_independent(self):
        src = (VK / "vka_gprof.c").read_text()
        self.assertIn('if (file && !strcmp(file, "GFX_CHUNK"))', src)
        self.assertIn('m->desc[0] = 0;', src)
        self.assertIn('} else if (g_pass_new) {', src)
        self.assertIn('if (m->gfx_top * 4 < m->gfx_draws * 3)', src)
        self.assertIn('mixed_ms += s[i].ms;', src)
        self.assertIn('blocks measure graphics time including VS/depth/ROP', src)
        self.assertIn('if (g_m[i].gfx_block || g_m[i].passes > g_m[i - 1].passes)', src)
        self.assertIn('g_gfx_n = 0; g_gfx_enabled = 0;', src)
        self.assertIn('gpu prof scene chunk key:', src)


if __name__ == '__main__':
    unittest.main()
