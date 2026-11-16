"""A/B wiring: this experiment cannot be held hostage to phone FPS evidence.

Only correctness/opt-in behavior is CI-gated. Actual ms/FPS must come from
paired runs on an Android device, which GitHub's runner does not provide.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"
CORE = ROOT / "dm/gfx/vk_android"


class FeedbackInvocationLauncherTest(unittest.TestCase):
    def test_default_off_and_independent_setting(self):
        p = (JAVA / "Prefs.java").read_text()
        self.assertIn('gameKey("fb_invocation_cache", titleId), false', p)
        self.assertIn("static boolean feedbackInvocationCache", p)
        self.assertIn("static void feedbackInvocationCache", p)
        self.assertNotIn('return gpuPageIndex(c, titleId)', p)

    def test_ui_and_reset(self):
        g = (JAVA / "GameSettings.java").read_text()
        self.assertIn("Feedback de texturas por fragmento · ON/OFF", g)
        self.assertIn("Prefs.feedbackInvocationCache(a, id, on)", g)
        # This must be visible before the ordinary Graphics settings; the old
        # row was buried near the end of a long page and easy to miss.
        graphics = g.split("private static void graphics(MainActivity", 1)[1]
        self.assertLess(graphics.index("Feedback de texturas por fragmento"),
                        graphics.index("Profile prof = Profile.of(id);"))
        self.assertIn(".toggle(a, cacheOn,", graphics)
        self.assertIn("ATIVADO (teste)", graphics)
        self.assertIn("DESLIGADO (original)", graphics)
        self.assertEqual(g.count("Feedback de texturas por fragmento · ON/OFF"), 1)
        self.assertIn('.remove(Prefs.gameKey("fb_invocation_cache", id))', g)

    def test_flag_reaches_runtime(self):
        a = (JAVA / "GameActivity.java").read_text()
        t = (CORE / "vka_tex.c").read_text()
        s = (CORE / "vka_spvpatch.c").read_text()
        self.assertIn('env.add("DM_VK_OOT_FB_INVOCATION_CACHE="', a)
        self.assertIn("Prefs.feedbackInvocationCache(this, id)", a)
        self.assertIn('env.add("DM_VK_SCENE_PASS_DIAG=1")', a)
        self.assertIn('VKA_ENV("DM_VK_OOT_FB_INVOCATION_CACHE", 0)', t)
        self.assertIn("VKA_PFB_INVOCATION_CACHE", s)
        self.assertIn("model == PF_Fragment", s)


if __name__ == "__main__":
    unittest.main()
