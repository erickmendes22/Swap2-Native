"""Ocarina 0.1.2: verify expensive GPU pixels are capped in BOTH FSR passes.

These are source-contract checks plus a deterministic sizing model. The
Android CI also compiles the C implementation using the stable shader library.
No claim about on-device FPS is made by these tests.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
PRESENT = (ROOT / "dm/gfx/vk_android/vka_present.c").read_text()
NDSR = (ROOT / "dm/gfx/vk_android/vka_ndsr.c").read_text()
OPTIONS = (ROOT / "android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java").read_text()


def cap720(dw, dh):
    scale = min(1, 1280 / dw, 720 / dh)
    return max(1, int(dw * scale + .5)), max(1, int(dh * scale + .5))


class Actual720pGpuWork(unittest.TestCase):
    def test_preserves_aspect_and_limits_expensive_pixel_count(self):
        for native in [(2162, 1216), (2400, 1080), (1280, 720),
                       (1280, 800), (720, 1280), (3840, 2160), (600, 400)]:
            w, h = cap720(*native)
            self.assertLessEqual(w, native[0])
            self.assertLessEqual(h, native[1])
            self.assertLessEqual(w, 1280)
            self.assertLessEqual(h, 720)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
        w, h = cap720(2162, 1216)
        self.assertEqual((w, h), (1279, 720))
        self.assertLess(w * h, 2162 * 1216 * .36)

    def test_easu_and_rcas_are_both_rendered_at_capped_size(self):
        self.assertIn('double fs = fmin(1.0, fmin(1280.0 / dw, 720.0 / dh));', PRESENT)
        self.assertIn('fsr_mid(k, (uint32_t)fw, (uint32_t)fh)', PRESENT)
        self.assertIn('fsr_copy(cb, k, idx, im, cx, cy, cw, ch, dx, dy, dw, dh, fw, fh)', PRESENT)
        self.assertIn('float sx = (float)cw / fw, sy = (float)ch / fh;', PRESENT)
        self.assertIn('VkViewport v = {0, 0, (float)fw, (float)fh, 0, 1};', PRESENT)
        self.assertIn('ri.renderArea = sc;', PRESENT)
        self.assertIn('g_fsr.easu', PRESENT)
        self.assertIn('g_fsr.rcas', PRESENT)
        self.assertIn('g_fsr.fview[k]', PRESENT)
        self.assertIn('g_fsr.finish[k]', PRESENT)
        self.assertIn('VK_FORMAT_R8G8B8A8_UNORM)))', PRESENT)

    def test_final_native_screen_pass_is_only_bilinear_sampling(self):
        self.assertIn('VkDescriptorImageInfo fin = {g_rot.samp[1], g_fsr.fview[k]', PRESENT)
        self.assertIn('rk.vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_rot.pipe);', PRESENT)
        self.assertIn('g_pre', PRESENT)
        self.assertIn('VK_SURFACE_TRANSFORM_ROTATE_90_BIT_KHR:', PRESENT)
        self.assertIn('VK_SURFACE_TRANSFORM_ROTATE_270_BIT_KHR:', PRESENT)
        self.assertIn('VK_IMAGE_LAYOUT_PRESENT_SRC_KHR', PRESENT)
        self.assertIn('vka_img_barrier(cb, g_fsr.finish[k]', PRESENT)
        self.assertIn('if (g_fsr.finish[k]) vk.vkDestroyImage', PRESENT)
        self.assertIn('if (g_fsr.fmem[k]) vk.vkFreeMemory', PRESENT)

    def test_game_ndsr_does_not_run_full_res_easu(self):
        self.assertIn('cs->key == UINT64_C(0x7c511cc23ff85d14)', NDSR)
        self.assertIn('oi->w * oi->h > 1280ull * 720', NDSR)
        self.assertIn('VKA_NDSR_KERNEL_BILINEAR : VKA_NDSR_KERNEL_EASU;', NDSR)
        self.assertIn('g_sw.mode == 1', NDSR)
        self.assertIn('g_sw.enc, g_sw.map, kernel, pack', NDSR)

    def test_ocarina_default_selects_working_720p_fsr_without_new_toggle(self):
        self.assertIn('Prefs.OCARINA_TITLE.equals(id) && previous == 0 ? 3 : previous', OPTIONS)
        self.assertIn('if (p.contains(key)) return', OPTIONS)
        self.assertIn('DM_VK_FSR=', OPTIONS)
        self.assertNotIn('DM_VK_FSR_720', OPTIONS)


if __name__ == "__main__":
    unittest.main()
