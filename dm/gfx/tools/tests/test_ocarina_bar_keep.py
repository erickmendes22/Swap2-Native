"""Ocarina 0.1.2: keep Vulkan attachments on-chip across safe guest barriers.

Fast path requires no shader stores and conservative texture alias checks.
The player's env-<title>.txt can force DM_VK_BAR_KEEP=0 without changing APK.
Static checks do not replace hardware validation for flicker or GPU timings.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
ACT = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameActivity.java").read_text()

class BarKeepAliasTests(unittest.TestCase):
    def test_ocarina_default_is_reversible(self):
        enable = 'if (Prefs.OCARINA_TITLE.equals(id)) env.add("DM_VK_BAR_KEEP=1");'
        self.assertIn(enable, ACT)
        self.assertLess(ACT.index(enable), ACT.index('env.addAll(user)'))
        self.assertIn('VKA_ENV("DM_VK_BAR_KEEP", 0)', DRAW)

    def test_dont_keep_when_prior_draw_wrote_memory(self):
        self.assertIn('if (R.swrite || !VKA_ENV("DM_VK_BAR_KEEP", 0)) return 0;', DRAW)
        self.assertIn('if (!R.swrite && draw_writes(sh, d)) R.swrite = 1;', DRAW)
        self.assertIn('if (draw_writes(sh, d)) return 1;', DRAW)
        self.assertIn('R.bar_pending && bar_hazard(sh, d)', DRAW)

    def test_alias_detection_uses_guest_storage_and_not_only_image_identity(self):
        self.assertIn('static int in_fb_or_alias(const vka_img *im)', TEX)
        self.assertIn('if (in_fb(im)) return 1;', TEX)
        self.assertIn('if (!im || !im->mem || !im->L.size) return 1;', TEX)
        self.assertIn('if (!f || !f->mem || !f->L.size) return 1;', TEX)
        self.assertIn('(uint64_t)(b - a) < im->L.size', TEX)
        self.assertIn('(uint64_t)(a - b) < f->L.size', TEX)
        self.assertIn('!e || !e->im || in_fb_or_alias(e->im)', TEX)
        self.assertIn('vka_tex_id_in_pass(r[i].tid)', DRAW)

    def test_external_operations_end_the_pass(self):
        self.assertIn('case OP_BARRIER:', EXEC)
        self.assertIn('case OP_COPY_B2T: if (g_cb) copy_bt(a, 1)', EXEC)
        self.assertIn('case OP_COPY_T2T: if (g_cb) copy_t2t(a)', EXEC)
        self.assertIn('default: if (g_cb && !vka_state_op(&S.d, h.op, a)) vka_rp_end()', EXEC)
        self.assertIn('int vka_rp_open_for(', DRAW)

    def test_nonoverlapping_and_adjacent_ranges(self):
        def overlaps(a, alen, b, blen):
            if not alen or not blen: return True  # conservatively unknown
            return b - a < alen if a <= b else a - b < blen
        self.assertTrue(overlaps(0x1000, 4096, 0x1800, 4096))
        self.assertTrue(overlaps(0x1800, 4096, 0x1000, 4096))
        self.assertFalse(overlaps(0x1000, 4096, 0x2000, 4096))
        self.assertFalse(overlaps(0x2000, 4096, 0x1000, 4096))
        self.assertFalse(overlaps(0x1000, 4096, 0x8000, 4096))

if __name__ == "__main__":
    unittest.main()
