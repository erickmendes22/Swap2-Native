"""Ocarina Vulkan FPS Boost — opt-in, driver-validated fragment shading rate.

Source/ABI regression checks. Actual GPU speed and correctness still require
the same-scene device A/B. This is not NX2navi WB_LAZY (which requires GPU
mirror memory and a CPU read-fault hook missing from this Vulkan backend).
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEV = (ROOT / "dm/gfx/vk_android/vka_dev.c").read_text()
PSO = (ROOT / "dm/gfx/vk_android/vka_pso.c").read_text()
HDR = (ROOT / "dm/gfx/vk_android/vka.h").read_text()
CTL = (ROOT / "dm/gfx/vk_android/vka_ctl.c").read_text()
OPTIONS = (ROOT / "android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java").read_text()
SETTINGS = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameSettings.java").read_text()


class FpsBoostTests(unittest.TestCase):
    def test_default_off_and_game_only(self):
        self.assertIn('getInt("oot_fps_boost", 0)', OPTIONS)
        self.assertIn('if (Prefs.OCARINA_TITLE.equals(id)) {', OPTIONS)
        self.assertIn('out.add("DM_VK_OOT_FPS_BOOST=0");', OPTIONS)
        self.assertNotIn('GraphicsOptions.choice(a, id, "oot_fps_boost"', SETTINGS)
        self.assertIn('out.add("DM_VK_OOT_FPS_BOOST=0");', OPTIONS)
        self.assertIn('"oot_fps_boost"', OPTIONS)

    def test_native_activation_checks_extension_and_feature(self):
        self.assertIn('want_boost > 0 && has_ext(de, nde, VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME)', DEV)
        self.assertIn('VkPhysicalDeviceFragmentShadingRateFeaturesKHR frate', DEV)
        self.assertIn('frate.pipelineFragmentShadingRate', DEV)
        self.assertIn('VK_SAMPLE_COUNT_1_BIT', DEV)
        self.assertIn('has_2x1', DEV)
        self.assertIn('has_2x2', DEV)
        self.assertIn('else if (want_boost > 0 && has_2x1)', DEV)
        self.assertIn('vkGetPhysicalDeviceFragmentShadingRatesKHR', DEV)
        self.assertIn('V.fps_boost_vrs =', DEV)

    def test_pipeline_only_changes_two_profiling_confirmed_fragment_programs(self):
        self.assertIn('0x5ad65c0eefd09c7f', PSO)
        self.assertIn('0x1e4d2630d24846d0', PSO)
        self.assertIn('if (V.fps_boost_vrs && sh[1]', PSO)
        self.assertIn('(k->samples ? k->samples : 1) == 1', PSO)
        self.assertIn('VK_STRUCTURE_TYPE_PIPELINE_FRAGMENT_SHADING_RATE_STATE_CREATE_INFO_KHR', PSO)
        # Both Vulkan structs must extend VkGraphicsPipelineCreateInfo,
        # not one another through VkPipelineRenderingCreateInfo.pNext.
        self.assertIn('P->fsrate.pNext = &P->ri;', PSO)
        self.assertIn('.pNext = P->fsrate.sType ? (const void *)&P->fsrate', PSO)
        self.assertNotIn('P->ri.pNext = &P->fsrate;', PSO)
        self.assertIn('P->ci = (VkGraphicsPipelineCreateInfo)', PSO)
        self.assertNotIn('SKIP("Ocarina FPS Boost', PSO)
        self.assertNotIn('VK_NULL_HANDLE; // FPS Boost', PSO)
        self.assertIn('uint32_t fps_boost_width, fps_boost_height', HDR)

    def test_pipeline_boost_requires_restart(self):
        self.assertIn('"DM_VK_OOT_FPS_BOOST"', CTL)
        before = CTL.index('static const char *const g_restart[]')
        after = CTL.index('static const char *const g_live[]')
        self.assertIn('"DM_VK_OOT_FPS_BOOST"', CTL[before:after])

    def test_seven_profiled_graphics_hot_shaders_use_balanced_2x1_if_supported(self):
        # Build54 profiler 100403: 14.11ms of 20.97ms GPU in 111 graphics
        # passes, including 2.44ms/416 draws, 2.28ms mesh+fragment, and
        # 1.81ms/351 draws. Before this patch FPS Boost was OFF and only
        # two shader keys could ever have VRS.
        for key in (
            "0x185d371b6c9475b2", "0x09bdc3e13d9f2461",
            "0x00ce4088af2c8e12", "0xa566b7687b712ff3",
            "0x8ea627c8ef169ee1", "0x1e4d2630d24846d0",
            "0x5ad65c0eefd09c7f", "0x264e6e6de176460a",
            "0xedce918b7374c89b", "0xfb29c58b3fab8e7b",
            "0xf48e795040c5dc9a", "0x80d2f2ff9f9882b8",
        ):
            self.assertIn(key, PSO)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOTPASS_VRS", 1)', DEV)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOTPASS_VRS", 1)', PSO)
        self.assertIn('int explicit_boost = VKA_ENV("DM_VK_OOT_FPS_BOOST", 0)', DEV)
        self.assertIn('requested_rate > explicit_boost ? requested_rate : explicit_boost', DEV)
        self.assertIn('if (V.fps_boost_vrs && sh[1] && (balanced_hot || explicit_hot || extended_scene_hdr)', PSO)
        self.assertIn('(k->samples ? k->samples : 1) == 1', PSO)
        self.assertIn('k->ncolor > 0', PSO)
        self.assertIn('k->cfmt[0] == VK_FORMAT_B10G11R11_UFLOAT_PACK32', PSO)
        # Non-HDR UI and video pipelines retain pixel-accurate shading.
        self.assertIn('VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME', DEV)
        self.assertIn('frate.pipelineFragmentShadingRate', DEV)
        self.assertIn('has_2x1', DEV)
        self.assertIn('V.fps_boost_vrs =', DEV)
        self.assertIn('DM_VK_OOT_HOTPASS_VRS=0 restores full fragment detail', DEV)
        self.assertIn('HOTPASS_VRS = {', OPTIONS)
        self.assertIn('getInt(Prefs.gameKey("oot_hotpass_vrs", id), 1)', OPTIONS)
        self.assertIn('out.add("DM_VK_OOT_HOTPASS_VRS=" + hotpassVrs(c, id));', OPTIONS)
        self.assertIn('GraphicsOptions.choice(a, id, "oot_hotpass_vrs"', SETTINGS)
        self.assertIn('"DM_VK_OOT_HOTPASS_VRS"', CTL)
        self.assertNotIn('shader_abi', OPTIONS)

    def test_optional_2x2_and_accurate_hdr_mesh_coverage(self):
        self.assertIn('Expanded — VRS 2×2', OPTIONS)
        self.assertIn('getInt(Prefs.gameKey("oot_hotpass_vrs", id), 1), 0, 5)', OPTIONS)
        self.assertIn('else if (want_boost >= 2 && has_2x2)', DEV)
        self.assertIn('profiled_mesh_hdr = mesh && sh[6] && sh[7]', PSO)
        self.assertIn('0xefaa4fa6a80ba719', PSO)
        self.assertIn('0x066f5daf12e43c71', PSO)
        self.assertIn('k->ncolor == 2', PSO)
        self.assertIn('k->cfmt[1] == VK_FORMAT_R16G16B16A16_SFLOAT', PSO)
        self.assertIn('profiled_hdr)', PSO)
        self.assertIn('if (!r && P->fsrate.sType && sh[1]', PSO)
        self.assertIn('Ocarina VRS pipeline ready', PSO)
        self.assertNotIn('if (atomic_fetch_add(&nboost, 1) < 6)', PSO)

    def test_optional_extended_two_by_two_hdr_coverage(self):
        # New 2026-11-11 111853 run: all 12 old shader pipelines are
        # compiled at 2x2 already. Keep profile 2 unchanged.
        # Only five further profiled HDR main-scene FS use profile 3.
        self.assertIn("Expanded — VRS 2×2", OPTIONS)
        self.assertIn("hotpass_vrs >= 5 ? 4 : hotpass_vrs >= 4 ? 3", DEV)
        self.assertIn('if (hotpass_vrs > 5) hotpass_vrs = 5', DEV)
        for key in ("0x8b13ac32679a0a3e", "0x19f99e925937b038",
                    "0x35a02875e7820e9a", "0x5a29269e72ac52aa",
                    "0xe55bcc53f003046a"):
            self.assertIn(key, PSO)
        self.assertIn('hotpass_profile >= 3', PSO)
        self.assertIn('extended_hot && !mesh && k->ncolor == 1', PSO)
        self.assertIn('k->dfmt == VK_FORMAT_D32_SFLOAT', PSO)
        self.assertIn('k->cfmt[0] == VK_FORMAT_B10G11R11_UFLOAT_PACK32', PSO)
        self.assertIn('(balanced_hot || explicit_hot || extended_scene_hdr)', PSO)
        self.assertNotIn('DM_VK_OOT_HOTPASS_VRS=3" &&', PSO)

    def test_opt_in_four_by_two_and_four_by_four_query_exact_single_sample_rates(self):
        self.assertIn('4x2', DEV)
        self.assertIn('4x4', DEV)
        self.assertIn('has_4x2', DEV)
        self.assertIn('has_4x4', DEV)
        self.assertIn('rates[i].sampleCounts & VK_SAMPLE_COUNT_1_BIT', DEV)
        self.assertIn('fragmentSize.width == 4 && rates[i].fragmentSize.height == 2', DEV)
        self.assertIn('fragmentSize.width == 4 && rates[i].fragmentSize.height == 4', DEV)
        self.assertIn('want_boost >= 4 && has_4x4', DEV)
        self.assertIn('want_boost >= 3 && has_4x2', DEV)
        self.assertIn('want_boost >= 2 && has_2x2', DEV)
        self.assertIn('want_boost > 0 && has_2x1', DEV)
        self.assertIn('Expanded — VRS 4×2 (experimental)', OPTIONS)
        self.assertIn('Expanded — VRS 4×4 (experimental)', OPTIONS)
        self.assertIn('getStringArray(R.array.s2_oot_hotpass_vrs)', OPTIONS)
        self.assertIn('VRS 4×4 (experimental)', (ROOT / 'android/app/src/main/res/values-pt/strings.xml').read_text())
        self.assertIn('if (r && P->fsrate.sType)', PSO)
        self.assertIn('fbi.pNext = &P->ri;', PSO)
        self.assertIn('VRS pipeline rejected', PSO)

    def test_fallback_no_invalid_pipeline_or_shader_abi_change(self):
        self.assertIn('V.fps_boost_width = V.fps_boost_vrs ? selected_w : 0u;', DEV)
        self.assertIn('if (V.fps_boost_width) {', PSO)
        self.assertNotIn('shader_abi', OPTIONS)
        self.assertNotIn('shader_library', OPTIONS)


if __name__ == "__main__":
    unittest.main()
