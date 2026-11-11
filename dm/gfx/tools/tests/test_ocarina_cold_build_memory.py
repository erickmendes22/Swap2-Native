"""First-time Ocarina translation and allocation-failure correctness guards."""
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[4]
P=(R/"android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
V=(R/"dm/gfx/tools/vk_android_build.py").read_text()
T=(R/"dm/gfx/vk_android/vka_tex.c").read_text()
class ColdShaderBuild(unittest.TestCase):
    def test_strict_all_keys_cold_or_rebuild(self):
        self.assertIn('DMSH_VK_OOT_COLD_RETRY',P)
        self.assertIn('ocarinaShaders && hotKeys.isEmpty() ? "1" : "0"',P)
        self.assertIn('PackEngine.setenv("DMSH_VK_REQUIRE_ALL", "1")',P)
        self.assertIn("once = translate([jobs[key]], bd, 'cold_retry_' + key)",V)
        self.assertIn("if once.returncode == 0 and os.path.isfile(sp)",V)
        self.assertIn("xerr.pop(key, None)",V)
        self.assertIn("if _bad and os.environ.get('DMSH_VK_REQUIRE_ALL') == '1':",V)
        self.assertIn("no library written (DMSH_VK_REQUIRE_ALL)",V)
        self.assertIn("for key in batch:",V)
    def test_realloc_failure_keeps_resident_textures(self):
        self.assertIn('vka_img **tmp = cap ? realloc(g_live',T)
        self.assertIn('if (!tmp)',T)
        self.assertIn('img_destroy(im);',T)
        self.assertIn('if (im) map_put(t->serial, im);',T)
        self.assertNotIn('g_live = realloc(g_live, (size_t)g_livecap',T)
if __name__=="__main__":unittest.main()
