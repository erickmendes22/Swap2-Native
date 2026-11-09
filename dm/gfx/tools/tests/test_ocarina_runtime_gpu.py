"""Source checks for the GPU-side no-rebuild render-pass optimization."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
D = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
E = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()

class OcarinaRuntimeGPUTests(unittest.TestCase):
    def test_keep_pass_is_game_specific_and_switchable(self):
        self.assertIn('return !strcmp(DM_GAME_ID, "0400486024DEC000");', D)
        self.assertIn('getenv("DM_VK_BAR_KEEP")', D)
        self.assertIn('if (R.swrite || !bar_keep_enabled()) return 0;', D)
        self.assertIn('if (R.on && R.bar_pending && bar_hazard(sh, d))', D)
        self.assertIn('if (draw_writes(sh, d)) return 1;', D)
        self.assertIn('vka_tex_id_in_pass', D)

    def test_shader_abi_untouched(self):
        # All changes affect the runtime backend; a fallback to the original
        # Swap2 shader library remains possible without any new compilation.
        self.assertNotIn('DMSH_GMEM_LAST1', D)
        self.assertNotIn('DMSH_GMEM_LAST1', E)
        self.assertIn('DM_VK_OQ_BATCH', E)

if __name__ == "__main__":
    unittest.main()
