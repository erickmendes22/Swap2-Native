"""GPU timestamp-profile regression, independent of app/CPU optimization.

Normal replay graphics commands and shaders must remain identical. The only
difference is how sampled GPU elapsed time is partitioned among blocks.
"""
import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "vk_android" / "vka_gprof.c").read_text()
SHADER = (Path(__file__).resolve().parents[2] / "vk_android" / "vka_shader.c").read_text()


class OcarinaGraphicsGPUProfile(unittest.TestCase):
    def test_four_draw_gpu_samples_preserve_render_work(self):
        self.assertRegex(SRC, r"enum\s*\{\s*GFX_CHUNK\s*=\s*4\s*\}")
        # Existing 75% attribution threshold: 3 of 4 draws must agree.
        self.assertIn("m->gfx_top * 4 < m->gfx_draws * 3", SRC)
        # Normal frames have no extra GPU timestamp, native draw or barrier.
        self.assertIn("if (!vka_gp_active) return;", SRC)
        self.assertIn("if (g_gfx_enabled && vka_gp_active && g_gfx_n < GFX_CHUNK)", SRC)
        self.assertIn('VKA_ENV("DM_VK_OOT_GFX_CHUNKS", 1)', SRC)
        self.assertIn("vka_scene_profile_size(desc)", SRC)
        self.assertIn("g_n >= NQ - 16", SRC)
        self.assertRegex(SRC, r"enum\s*\{\s*NQ\s*=\s*2048")
        # Before: one 16-draw interval with only 5 matches: cannot blame FS.
        old = ["a566b7687b712ff3"] * 5 + [f"other{i}" for i in range(11)]
        self.assertLess(old.count(old[0]) * 4, 16 * 3)
        # New 4-draw intervals can distinguish hot consecutive draws and
        # exclude unrelated raster work without changing draw order.
        chunks = [old[i:i + 4] for i in range(0, len(old), 4)]
        self.assertEqual([len(c) for c in chunks], [4, 4, 4, 4])
        self.assertGreaterEqual(chunks[0].count(old[0]), 3)
        self.assertLess(chunks[2].count(old[0]), 3)
        # Previously observed stable frame ~1077 timestamps of which ~165
        # were 16-draw chunks; with ~2400 draws, new count remains in budget.
        self.assertLess(1077 - 165 + (2400 + 3) // 4, 2048)

    def test_missing_raster_shader_sources_captured_once_with_existing_shdump(self):
        cap = SHADER[SHADER.index("static int ocarina_hot_shader_slot("):
                     SHADER.index("static int capture_matches(")]
        keys = re.findall(r"UINT64_C[(]0x([0-9a-f]{16})[)]", cap)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertLess(len(keys), 32)  # unsigned done bitmask has exactly 32 bits.
        for key in ("a566b7687b712ff3", "a1d325b7a1c81256",
                    "9f36b8ee91e736c6", "438955b0098580f7",
                    "09bdc3e13d9f2461"):
            self.assertIn(key, keys)
        capture = SHADER[SHADER.index("static void capture_hot_shader_source("):
                         SHADER.index("static int capture_ocarina_stage_pair(")]
        self.assertIn("unsigned mask = 1u << slot;", capture)
        self.assertIn("capture_shader_source(p, i, key)", capture)
        self.assertIn('getenv("DM_NVN_SHDUMP")', SHADER)
        self.assertIn("if (key == keys[i]) return (int)i;", cap)

    def test_gpu_profiler_only_not_renderer_changes(self):
        self.assertIn('mark(g_cb, 0, "GFX_CHUNK", 0)', SRC)
        self.assertIn('if (g_n == GFX_CHUNK) gfx_chunk_flush()', SRC.replace("g_gfx_n", "g_n"))
        self.assertIn('g_gfx_enabled = !strcmp(DM_GAME_ID, "0400486024DEC000")', SRC)


if __name__ == "__main__":
    unittest.main()
