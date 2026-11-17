"""Hardware A/B retirement: no per-fragment feedback-cache rewrite.

Measured heavy-scene median: feedback cache ON GPU 20.71 ms, OFF 20.67 ms.
Restore native shader rewrite and Vulkan texture feedback to original path.
"""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[4]
NATIVE = ROOT / "dm/gfx/vk_android"
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"

class RetiredFeedbackInvocationCache(unittest.TestCase):
    def test_native_and_launcher_do_not_emit_retired_feature(self):
        for path in (
            NATIVE / "vka_spvpatch.c",
            NATIVE / "vka_spvpatch.h",
            NATIVE / "vka_tex.c",
            JAVA / "GameActivity.java",
            JAVA / "Prefs.java",
            JAVA / "GameSettings.java",
        ):
            with self.subTest(path=str(path)):
                code = path.read_text()
                self.assertNotIn("VKA_PFB_INVOCATION_CACHE", code)
                self.assertNotIn("DM_VK_OOT_FB_INVOCATION_CACHE", code)
                self.assertNotIn("feedbackInvocationCache(", code)
        self.assertNotIn('env.add("DM_VK_OOT_DEPTH_STORE_NONE', (JAVA/"GameActivity.java").read_text())

if __name__ == "__main__":
    unittest.main()
