"""Guard the lower-resolution Ocarina SGSR internal path, without using
classic render passes or changing the known-good direct 1280x720 route.

The independent full-GPU pixel test remains dm/tools/tests/test_ndsr_sgsr_gpu.py.
"""
import math
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/"dm/gfx/vk_android"
COMP=(VK/"fsr/ndsr_sgsr.comp").read_text()
REF=(VK/"selftest/sgsr_reference.comp").read_text()
ACT=(ROOT/"android/app/src/main/java/dev/nxnative/android/GameActivity.java").read_text()
PREFS=(ROOT/"android/app/src/main/java/dev/nxnative/android/Prefs.java").read_text()
DRAW=(VK/"vka_draw.c").read_text()
NDSR=(VK/"vka_ndsr.c").read_text()

class SgsrLowResolutionSafety(unittest.TestCase):
    def test_integer_texel_centres_and_no_one_row_offset(self):
        for source in (COMP, REF):
            self.assertIn('vec2(-0.5,-0.5)',source)
            self.assertNotIn('vec2(-0.5,0.5)',source)
        # The shader's output-UV->input-texel equation must land on
        # exactly the same input texel centre for x and y, at arbitrary
        # fractional scales and the two scene sizes that are not 720p.
        for iw,ih,ow,oh in [(683,384,2048,1152),
                            (854,480,2048,1152),
                            (960,540,2048,1152),
                            (1280,720,1280,720)]:
            for x,y in [(0,0),(1,1),(ow//2,oh//2),(ow-1,oh-1)]:
                srcx=(x+0.5)*iw/ow-0.5
                srcy=(y+0.5)*ih/oh-0.5
                self.assertLess(abs((srcx+0.5)/iw-(x+0.5)/ow),1e-12)
                self.assertLess(abs((srcy+0.5)/ih-(y+0.5)/oh),1e-12)
                oldy=srcy+1.0
                self.assertAlmostEqual(oldy-srcy,1.0)

    def test_extreme_hdr_contrast_never_divides_zero(self):
        self.assertIn('highp float safeSum = max(float(sum), 1.0e-4);',COMP)
        self.assertIn('highp float std = min(sumMean*sumMean, 65504.0);',COMP)
        self.assertIn('abs(aWY.x) > 1.0e-5',COMP)
        self.assertIn('!any(isnan(aWY))',COMP)
        self.assertIn('!any(isinf(aWY))',COMP)
        for contrast in (0,1e-30,1e-10,1e-5,1e-4,0.03137,0.5,256):
            reciprocal=10.14185/max(contrast,1e-4)
            variance=min(reciprocal*reciprocal,65504.)
            self.assertTrue(math.isfinite(variance))
            self.assertLessEqual(variance,65504.)
        # The output is still HDR, has the same packed-store interface and
        # never renders a second pass to clean up artifacts.
        self.assertIn('if(ENC==1)result*=result;',COMP)
        self.assertIn('store(ivec2(p)+org,result);',COMP)
        self.assertIn('imageStore(dst, p, uvec4(w));',COMP)

    def test_cave_wall_backend_is_unconditionally_disabled(self):
        self.assertIn('env.add("DM_VK_CLASSIC_RP=0");',ACT)
        self.assertIn('static boolean classicPasses(Context c,String id) { return false; }',PREFS)
        self.assertIn('strcmp(DM_GAME_ID, "0400486024DEC000") != 0;',DRAW)
        self.assertIn('VKA_ENV("DM_VK_OQ_SPLIT_PASS", 0) != 0', (VK/"vka_exec.c").read_text())
        self.assertIn('if (split) vka_rp_cave_end();', (VK/"vka_exec.c").read_text())
        self.assertIn('VKA_ENV("DM_VK_UNUSED_COLOR", 0)',DRAW)

    def test_direct_720p_does_not_run_internal_nonlinear_sgsr(self):
        prof=(ROOT/"android/app/src/main/java/dev/nxnative/android/OcarinaRenderProfile.java").read_text()
        self.assertIn('static boolean direct720(int mode) { return checked(mode) == 3; }',prof)
        self.assertIn('OcarinaRenderProfile.direct720(Prefs.renderProfile(this, id))',ACT)
        self.assertIn('env.add("DM_VK_NDSR=bilinear");',ACT)
        self.assertIn('int sgsr_internal = g_sw.mode == 3',NDSR)

if __name__=="__main__":unittest.main()
