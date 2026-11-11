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
        self.assertEqual((w, h), (1280, 720))
        self.assertLess(w * h, 2162 * 1216 * .36)

    def test_easu_and_rcas_are_both_rendered_at_capped_size(self):
        self.assertIn('double fs = fmin(1.0, fmin(1280.0 / dw, 720.0 / dh));', PRESENT)
        self.assertIn('fsr_mid(k, (uint32_t)fw, (uint32_t)fh, present_filter == 4 && g_fsr.sgsr)', PRESENT)
        self.assertIn('fsr_copy(cb, k, idx, im, cx, cy, cw, ch, dx, dy, dw, dh, fw, fh, present_filter == 4)', PRESENT)
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
        # Normal frames retain the chosen colour and mapping; ONLY the
        # explicitly validated Ocarina 0.25 direct HDR input overrides them.
        self.assertIn('int effective_enc = source_is_scene_linear ? VKA_NDSR_ENC_LINEAR : g_sw.enc;', NDSR)
        self.assertIn('int effective_map = source_is_scene_linear ? VKA_NDSR_MAP_FULL : g_sw.map;', NDSR)
        self.assertIn('make(cs, lay, tb, ib, bb, effective_enc, effective_map, kernel, pack)', NDSR)
        self.assertIn('source_is_scene_linear && cs->key != UINT64_C(0xd99fbeeb53d38847)', NDSR)

    def test_ndsr_retile_replaces_guest_grid_not_guest_shader(self):
        draw = (ROOT / 'dm/gfx/vk_android/vka_draw.c').read_text()
        header = (ROOT / 'dm/gfx/vk_android/vka_ndsr.h').read_text()
        # The no-new-shader-translation path modifies the dispatch of
        # precisely the already-selected NDSR stand-in pipeline.
        self.assertIn('vka_ndsr_grid_x(uint32_t width, uint32_t height,', header)
        self.assertIn('gp_ndsr_replaced && !dp->ind && !sb', draw)
        self.assertIn('!vka_gp_active', draw)
        self.assertIn('!vka_nan_on()', draw)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', draw)
        self.assertIn('VKA_ENV("DM_VK_OOT_NDSR_RETILE", 1)', draw)
        self.assertIn('vka_ndsr_grid_x(ndsr_ow, ndsr_oh, native,', draw)
        self.assertIn('V.props.limits.maxComputeWorkGroupCount[0]', draw)
        self.assertIn('if (ndsr_groups_x) vk.vkCmdDispatch(g_cb, ndsr_groups_x, 1, 1);', draw)
        self.assertIn('else if (sb && (uint64_t)dp->x', draw)
        self.assertIn('else vk.vkCmdDispatch(g_cb, (uint32_t)dp->x', draw)
        self.assertIn('scene_linear, &ndsr_ow, &ndsr_oh', draw)

    def test_ndsr_grid_stride_retile_preserves_every_output_pixel(self):
        # The committed NDSR SPIR-V's shader uses
        #   p = group_id*128 + lane + k*(groups*128).
        # When we make the number of groups ceil(pixels/256), this is a
        # bijection of all output pixels with at most two loop iterations
        # per lane. No original shader SPIR-V or workgroup indexing is changed.
        from math import ceil
        for w, h in [(1, 1), (17, 13), (257, 129), (640, 360),
                     (1275, 717), (2048, 1152), (3840, 2160)]:
            count = w * h
            groups = ceil(count / 256)
            self.assertLessEqual(groups, 65535)
            stride = 128 * groups
            self.assertGreaterEqual(stride, count // 2)
            self.assertLessEqual(ceil(count / stride), 2)
            sample = range(count) if count <= 50_000 else (
                list(range(1024)) + list(range(count - 1024, count)) +
                [count // 2, count // 3, count // 5])
            for p in sample:
                lane_with_group = p % stride
                group, lane = divmod(lane_with_group, 128)
                loop = p // stride
                self.assertLess(group, groups)
                self.assertLess(lane, 128)
                self.assertLess(loop, 2)
                self.assertEqual(group * 128 + lane + loop * stride, p)

    def test_sgsr_selection_cannot_silently_disable_requested_upscaler(self):
        # The 2026-11-11 Build 49 log reported DM_VK_PRESENT_FILTER=4 but
        # fsr_requested=0, even though the launcher had DM_VK_FSR=1.
        # Presentation selection is authoritative for swapchain setup,
        # frame scheduling and descriptor pipeline initialization.
        fn = PRESENT[PRESENT.index("static int present_filter_setting(void)"):
                     PRESENT.index("static VkPipeline fsr_pipe(")]
        # A stale per-callsite cache had filter=4 in the present frame, but
        # fsr_wanted=0 since it first ran earlier during swapchain startup.
        # Both paths MUST use the same uncached reader to avoid split modes.
        self.assertIn('vka_env_str("DM_VK_PRESENT_FILTER", value, sizeof value)', fn)
        self.assertIn('int selected = present_filter_setting();', fn)
        self.assertIn('if (selected == 3 || selected == 4) return 1;', fn)
        self.assertIn('if (selected != 0) return 0;', fn)
        self.assertIn('vka_env_str("DM_VK_FSR", value, sizeof value)', fn)
        self.assertIn('int present_filter = present_filter_setting();', PRESENT)
        self.assertNotIn('VKA_ENV("DM_VK_PRESENT_FILTER", 0)', PRESENT)
        self.assertIn('g_sview_fsr = fsr_wanted()', PRESENT)
        self.assertIn('if (rot_rotates(pre) || fsr_wanted())', PRESENT)
        self.assertIn('int fsr = fsr_wanted() && can_sample', PRESENT)
        self.assertIn('fsr_copy(cb, k, idx, im', PRESENT)
        self.assertIn('if (fsr && !g_sview[idx])', PRESENT)

    def test_ios_v19_025_snapdragon_chain_requires_verified_gpu_success(self):
        draw = (ROOT / 'dm/gfx/vk_android/vka_draw.c').read_text()
        ui = (ROOT / 'android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java').read_text()
        present = PRESENT
        self.assertIn('0xd99fbeeb53d38847', draw)
        self.assertIn('0xf8965bffbdf51d78', draw)
        self.assertIn('0xd17eefaff4f0bc23', draw)
        self.assertIn('0xa335c1db6270c355', draw)
        self.assertIn('src->w <= 640 && src->h <= 360', draw)
        self.assertNotIn('src->w <= 1024 && src->h <= 576', draw)
        self.assertIn('DM_VK_OOT_SGSR_CHAIN", 0', draw)
        self.assertIn('vka_present_sgsr_active()', draw)
        self.assertIn('g_oot_sgsr_chain.primed', draw)
        self.assertIn('if (scene_linear && !p)', draw)
        self.assertIn('g_wk.r[5][scene_binding].tid = scene_previous_tid;', draw)
        self.assertIn('g_oot_sgsr_chain.completed = 1;', draw)
        self.assertIn('atomic_store_explicit(&g_sgsr_last_present, method == 4', present)
        self.assertIn('atomic_store_explicit(&g_sgsr_last_present, 0', present)
        self.assertIn('DM_VK_OOT_SGSR_CHAIN=" + sgsrChain(c, id)', ui)
        self.assertIn('static int sgsrChain(Context c, String id)', ui)

    def test_060_and_075_networks_drop_only_redundant_easu_after_real_sgsr(self):
        # Logs 08:29:37 and 08:31:06 show these actual NDSR keys
        # for 1536x864 and 1275x717 -> 2048x1152; neither is d99f.
        self.assertIn('cs->key == UINT64_C(0xb106afba1a18faa9)', NDSR)
        self.assertIn('cs->key == UINT64_C(0xfa3033d05c0a41d6)', NDSR)
        self.assertIn('sgsr_network_light = g_sw.mode == 1', NDSR)
        self.assertIn('VKA_ENV("DM_VK_OOT_SGSR_CHAIN", 0)', NDSR)
        self.assertIn('vka_present_sgsr_active()', NDSR)
        self.assertIn('(uint64_t)oi->w * oi->h > 1280ull * 720', NDSR)
        self.assertIn('sgsr_network_light)', NDSR)
        self.assertIn('VKA_NDSR_KERNEL_BILINEAR : VKA_NDSR_KERNEL_EASU;', NDSR)
        self.assertIn('Ocarina SGSR internal network:', NDSR)
        self.assertIn('Desativado (seguro)', OPTIONS)

    def test_025_network_really_replaces_heavy_taps_not_just_output_filter(self):
        # SGSR is applied only after this inexpensive GPU conversion; no
        # full-resolution EASU taps for source_is_scene_linear.
        self.assertIn('g_sw.mode == 2 || large_oot || source_is_scene_linear', NDSR)
        self.assertIn('VKA_NDSR_KERNEL_BILINEAR : VKA_NDSR_KERNEL_EASU', NDSR)
        self.assertIn('effective_enc = source_is_scene_linear ? VKA_NDSR_ENC_LINEAR', NDSR)
        self.assertIn('effective_map = source_is_scene_linear ? VKA_NDSR_MAP_FULL', NDSR)
        self.assertIn('if (source_is_scene_linear && cs->key != UINT64_C(0xd99fbeeb53d38847))', NDSR)

    def test_ocarina_default_selects_working_720p_fsr_without_new_toggle(self):
        self.assertIn('Prefs.OCARINA_TITLE.equals(id) && previous == 0 ? 4 : previous', OPTIONS)
        self.assertIn('if (p.contains(key)) return', OPTIONS)
        self.assertIn('DM_VK_FSR=', OPTIONS)
        self.assertNotIn('DM_VK_FSR_720', OPTIONS)


if __name__ == "__main__":
    unittest.main()
