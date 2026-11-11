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
        self.assertIn('out.add("DM_VK_OOT_FPS_BOOST=" + fpsBoost(c, id));', OPTIONS)
        self.assertIn('if (Prefs.OCARINA_TITLE.equals(id)) {', SETTINGS)
        self.assertIn('FPS Boost — VRS (experimental)', SETTINGS)
        self.assertIn('"oot_fps_boost"', OPTIONS)

    def test_native_activation_checks_extension_and_feature(self):
        self.assertIn('want_boost > 0 && has_ext(de, nde, VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME)', DEV)
        self.assertIn('VkPhysicalDeviceFragmentShadingRateFeaturesKHR frate', DEV)
        self.assertIn('frate.pipelineFragmentShadingRate', DEV)
        self.assertIn('VK_SAMPLE_COUNT_1_BIT', DEV)
        self.assertIn('has_2x1', DEV)
        self.assertIn('has_2x2', DEV)
        self.assertIn('want_boost > 0 && has_2x1 ? 1u : 0u', DEV)
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
        self.assertIn('hotpass_vrs > explicit_boost ? hotpass_vrs : explicit_boost', DEV)
        self.assertIn('if (V.fps_boost_vrs && sh[1] && (balanced_hot || explicit_hot)', PSO)
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
        self.assertIn('"oot_hotpass_vrs"', SETTINGS)
        self.assertIn('"DM_VK_OOT_HOTPASS_VRS"', CTL)
        self.assertNotIn('shader_abi', OPTIONS)

    def test_optional_2x2_and_accurate_hdr_mesh_coverage(self):
        self.assertIn('Agressivo — VRS 2×2 nos passes pesados', OPTIONS)
        self.assertIn('getInt(Prefs.gameKey("oot_hotpass_vrs", id), 1), 0, 2)', OPTIONS)
        self.assertIn('want_boost >= 2 && has_2x2 ? 2u', DEV)
        self.assertIn('profiled_mesh_hdr = mesh && sh[6] && sh[7]', PSO)
        self.assertIn('0xefaa4fa6a80ba719', PSO)
        self.assertIn('0x066f5daf12e43c71', PSO)
        self.assertIn('k->ncolor == 2', PSO)
        self.assertIn('k->cfmt[1] == VK_FORMAT_R16G16B16A16_SFLOAT', PSO)
        self.assertIn('profiled_hdr)', PSO)
        self.assertIn('if (!r && P->fsrate.sType && sh[1]', PSO)
        self.assertIn('Ocarina VRS pipeline ready', PSO)
        self.assertNotIn('if (atomic_fetch_add(&nboost, 1) < 6)', PSO)

    def test_fallback_no_invalid_pipeline_or_shader_abi_change(self):
        self.assertIn('V.fps_boost_width = V.fps_boost_vrs ? 2u : 0u;', DEV)
        self.assertIn('if (V.fps_boost_width) {', PSO)
        self.assertNotIn('shader_abi', OPTIONS)
        self.assertNotIn('shader_library', OPTIONS)


if __name__ == "__main__":
    unittest.main()
