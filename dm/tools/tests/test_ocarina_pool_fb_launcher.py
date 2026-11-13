"""Guard default-off texture feedback ring A/B wiring on Ocarina only."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[3]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"
RES = ROOT / "android/app/src/main/res"

class FeedbackAB(unittest.TestCase):
    def test_ui_pref_and_runtime_flag(self):
        p = (JAVA/"Prefs.java").read_text()
        a = (JAVA/"GameActivity.java").read_text()
        s = (JAVA/"GameSettings.java").read_text()
        c = (ROOT/"dm/gfx/vk_android/vka_tex.c").read_text()
        self.assertIn('getBoolean(gameKey("pool_feedback_direct", titleId), false)',p)
        self.assertIn('putBoolean(gameKey("pool_feedback_direct", titleId), on)',p)
        self.assertIn('DM_VK_POOL_FB_DIRECT=',a)
        self.assertIn('if (Prefs.OCARINA_TITLE.equals(id)) env.add("DM_VK_POOL_FB_DIRECT="',a)
        self.assertIn('Prefs.poolFeedbackDirect(this, id) ? "1" : "0"',a)
        self.assertIn('R.string.s2_texture_feedback_direct',s)
        self.assertIn('Prefs.poolFeedbackDirect(a, id)',s)
        self.assertIn('VKA_ENV("DM_VK_POOL_FB_DIRECT", 0)',c)
        self.assertIn('g_pfb_direct_cur >= 0 ? g_pfb_direct_set[g_pfb_direct_cur] : g_pfb_set;',c)
        self.assertIn('if (g_pfb_direct_cur >= 0 && !g_pfb_direct_cleared)',c)
        self.assertIn('if (!g_pfb_r[k].busy || g_pfb_r[k].fence > done) continue;',c)
        for path in [RES/"values/strings.xml",RES/"values-pt/strings.xml"]:
            xml=path.read_text()
            self.assertIn('name="s2_texture_feedback_direct"',xml)
            self.assertIn('name="s2_texture_feedback_direct_note"',xml)

if __name__ == "__main__":
    unittest.main()
