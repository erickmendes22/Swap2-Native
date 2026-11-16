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
RUN = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameActivity.java").read_text()


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
        self.assertIn('VKA_ENV("DM_VK_OOT_HOTPASS_VRS", 0)', DEV)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOTPASS_VRS", 0)', PSO)
        self.assertIn('int explicit_boost = VKA_ENV("DM_VK_OOT_FPS_BOOST", 0)', DEV)
        self.assertIn('requested_rate > explicit_boost ? requested_rate : explicit_boost', DEV)
        self.assertIn('if (V.fps_boost_vrs && sh[1] && (balanced_hot || explicit_hot || extended_scene_hdr)', PSO)
        self.assertIn('(k->samples ? k->samples : 1) == 1', PSO)
        self.assertIn('k->ncolor > 0', PSO)
        self.assertIn('VKA_COLOR_ORIGINAL(k->cfmt[0]) == VK_FORMAT_B10G11R11_UFLOAT_PACK32', PSO)
        # Non-HDR UI and video pipelines retain pixel-accurate shading.
        self.assertIn('VK_KHR_FRAGMENT_SHADING_RATE_EXTENSION_NAME', DEV)
        self.assertIn('frate.pipelineFragmentShadingRate', DEV)
        self.assertIn('has_2x1', DEV)
        self.assertIn('V.fps_boost_vrs =', DEV)
        self.assertIn('DM_VK_OOT_HOTPASS_VRS=0 restores full fragment detail', DEV)
        self.assertIn('HOTPASS_VRS = {', OPTIONS)
        self.assertIn('getInt(Prefs.gameKey("oot_hotpass_vrs", id), 0)', OPTIONS)
        self.assertIn('out.add("DM_VK_OOT_HOTPASS_VRS=" + hotpassVrs(c, id));', OPTIONS)
        self.assertIn('GraphicsOptions.choice(a, id, "oot_hotpass_vrs"', SETTINGS)
        self.assertIn('"DM_VK_OOT_HOTPASS_VRS"', CTL)
        self.assertNotIn('shader_abi', OPTIONS)

    def test_optional_2x2_and_accurate_hdr_mesh_coverage(self):
        self.assertIn('"VRS 2×2"', OPTIONS)
        self.assertIn('getInt(Prefs.gameKey("oot_hotpass_vrs", id), 0), 0, 5)', OPTIONS)
        self.assertIn('else if (want_boost >= 2 && has_2x2)', DEV)
        self.assertIn('profiled_mesh_hdr = oot_profiled_mesh_hdr(sh, k, mesh)', PSO)
        self.assertIn('0xefaa4fa6a80ba719', PSO)
        self.assertIn('0x066f5daf12e43c71', PSO)
        self.assertIn('k->ncolor == 2', PSO)
        self.assertIn('VKA_COLOR_ORIGINAL(k->cfmt[1]) == VK_FORMAT_R16G16B16A16_SFLOAT', PSO)
        self.assertIn('profiled_hdr && !vrs_excluded(fs_hot))', PSO)
        self.assertIn('if (!r && P->fsrate.sType && sh[1]', PSO)
        self.assertIn('Ocarina VRS pipeline ready', PSO)
        self.assertNotIn('if (atomic_fetch_add(&nboost, 1) < 6)', PSO)

    def test_all_seventeen_vetted_hdr_shaders_use_two_by_two(self):
        # The old profile 3 ("expanded") was removed from the UI but its
        # five captured HDR fragment shaders were accidentally gated there.
        # Mode 2 (2x2) now gets all 12+5; mode 1 (2x1) stays conservative.
        # Larger 4x2/4x4 modes use the SAME allowlist, never broad HDR.
        self.assertIn('"VRS 2×2"', OPTIONS)
        self.assertIn("hotpass_vrs >= 5 ? 4 : hotpass_vrs >= 4 ? 3", DEV)
        self.assertIn('if (hotpass_vrs > 5) hotpass_vrs = 5', DEV)
        for key in ("0x8b13ac32679a0a3e", "0x19f99e925937b038",
                    "0x35a02875e7820e9a", "0x5a29269e72ac52aa",
                    "0xe55bcc53f003046a"):
            self.assertIn(key, PSO)
        self.assertIn('hotpass_profile >= 2 &&', PSO)
        self.assertNotIn('hotpass_profile >= 3 &&', PSO)
        self.assertIn('extended_hot && !mesh && k->ncolor == 1', PSO)
        self.assertIn('VKA_COLOR_ORIGINAL(k->cfmt[0]) == VK_FORMAT_B10G11R11_UFLOAT_PACK32', PSO)
        self.assertIn('k->dfmt == VK_FORMAT_D32_SFLOAT', PSO)
        self.assertNotIn('int broad_hdr_scene =', PSO)
        self.assertIn('k->dfmt == VK_FORMAT_D32_SFLOAT', PSO)
        self.assertIn('VKA_COLOR_ORIGINAL(k->cfmt[0]) == VK_FORMAT_B10G11R11_UFLOAT_PACK32', PSO)
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
        self.assertIn('"VRS 4×2"', OPTIONS)
        self.assertIn('"VRS 4×4"', OPTIONS)
        self.assertIn('getStringArray(R.array.s2_oot_hotpass_vrs)', OPTIONS)
        self.assertIn('<item>VRS 4×4</item>', (ROOT / 'android/app/src/main/res/values-pt/strings.xml').read_text())
        self.assertIn('if (r && P->fsrate.sType)', PSO)
        self.assertIn('fbi.pNext = &P->ri;', PSO)
        self.assertIn('VRS pipeline rejected', PSO)

    def test_compact_vrs_options_without_broad_scene_shader_expansion(self):
        # Only five visible choices; legacy stored profile 3 remains supported,
        # but it does not consume a duplicate entry in the dialog.
        self.assertIn('VRS_VISIBLE_MODES = {0, 1, 2, 4, 5}', OPTIONS)
        self.assertIn('vrsVisibleIndex(hotpassVrs(c, id))', OPTIONS)
        self.assertIn('vrsChoice(c, id, done);', OPTIONS)
        self.assertIn('integer(c, id, "oot_hotpass_vrs", VRS_VISIBLE_MODES[index]);', OPTIONS)
        pt = (ROOT / 'android/app/src/main/res/values-pt/strings.xml').read_text()
        import re
        choices = re.search(r'<string-array name="s2_oot_hotpass_vrs">(.*?)</string-array>', pt, re.S)
        self.assertIsNotNone(choices)
        self.assertEqual(choices.group(1).count("<item>"), 5)
        self.assertNotIn('HDR ampliado', choices.group(1))
        self.assertNotIn('experimental', choices.group(1).lower())
        # Regression: the Nov 11 4x4 experiment enabled >=128 shaders
        # and destroyed scene detail while GPU remained ~20ms/frame.
        self.assertNotIn('int broad_hdr_scene =', PSO)
        self.assertIn('uint32_t rate_w = V.fps_boost_width', PSO)
        self.assertNotIn('hotpass_profile >= 4 && !profiled_mesh_hdr', PSO)
        self.assertNotIn('rate_w = 2u; rate_h = 1u;', PSO)
        self.assertNotIn('rate_w = 2u; rate_h = 2u;', PSO)
        self.assertIn('V.fps_boost_has_2x1', PSO)
        self.assertIn('V.fps_boost_has_2x2', PSO)
        self.assertIn('VKA_COLOR_ORIGINAL(k->cfmt[0]) == VK_FORMAT_B10G11R11_UFLOAT_PACK32', PSO)
        self.assertIn('k->ncolor == 2', PSO)
        self.assertIn('logged_fs[128]', PSO)
        self.assertIn('VRS pipeline rejected', PSO)

    def test_vrs_4x2_4x4_applies_to_vetted_shaders_at_every_resolution(self):
        # Redmagic 11 Pro: both 360p and 480p suffered the same downgrade.
        # A shader's requested VRS must not be silently limited by scene scale.
        self.assertNotIn('DM_VK_OOT_SCENE_360', RUN)
        self.assertNotIn('DM_VK_OOT_SCENE_360', PSO)
        self.assertIn('uint32_t rate_w = V.fps_boost_width, rate_h = V.fps_boost_height;', PSO)
        self.assertNotIn('hotpass_profile >= 4 && !profiled_mesh_hdr', PSO)
        # Keep the 12+5 profiled HDR shaders only, never all 128+ unknown.
        self.assertNotIn('int broad_hdr_scene =', PSO)
        self.assertIn('(balanced_hot || explicit_hot || extended_scene_hdr)', PSO)
        self.assertIn('if (rate_w) {', PSO)
        self.assertIn('if (r && P->fsrate.sType)', PSO)
        self.assertIn('VRS pipeline rejected', PSO)

    def test_gpl_does_not_discard_requested_fragment_shading_rate(self):
        # Fast GPL link creates pNext=&libs and drops VRS -> 1x1.
        # Force full_pipeline (cached on future runs) for the VRS allowlist.
        self.assertIn('!P->mesh && !P->fsrate.sType)', PSO)
        self.assertIn('p = full_pipeline(P, sh, prewarm ? " (prewarm)" : NULL);', PSO)
        self.assertIn('P->fsrate.pNext = &P->ri;', PSO)

    def test_driver_vrs_rate_rejection_tries_supported_smaller_rates_before_1x1(self):
        self.assertIn('{4u, 2u, V.fps_boost_has_4x2}', PSO)
        self.assertIn('{2u, 2u, V.fps_boost_has_2x2}', PSO)
        self.assertIn('{2u, 1u, V.fps_boost_has_2x1}', PSO)
        self.assertIn('area >= original_area', PSO)
        self.assertIn('if (r) {', PSO)
        self.assertIn('final fallback 1x1', PSO)
        self.assertIn('Ocarina VRS pipeline fallback:', PSO)

    def test_fallback_no_invalid_pipeline_or_shader_abi_change(self):
        self.assertIn('V.fps_boost_width = V.fps_boost_vrs ? selected_w : 0u;', DEV)
        self.assertIn('if (rate_w) {', PSO)
        self.assertNotIn('shader_abi', OPTIONS)
        self.assertNotIn('shader_library', OPTIONS)


    def test_only_three_captured_720p_heavy_shader_keys_select_four_by_two(self):
        import shutil
        import subprocess
        import tempfile
        self.assertIn('#include "vka_oot_heavy_pass_vrs.h"', PSO)
        self.assertIn('DM_VK_OOT_HEAVY_4X2", 0', PSO)
        self.assertIn('rate_w = 4u; rate_h = 2u;', PSO)
        self.assertIn('V.fps_boost_has_4x2', PSO)
        self.assertIn('vka_oot_heavy_4x2_eligible(', PSO)
        self.assertIn('P->fsrate.fragmentSize.width = choices[i].w;', PSO)
        self.assertIn('{2u, 2u, V.fps_boost_has_2x2}', PSO)
        self.assertIn('vk.vkCreateGraphicsPipelines(V.dev, g_pc, 1, &P->ci, NULL, &p);', PSO)
        code = r"""
#include <assert.h>
#include <stdint.h>
#include <vulkan/vulkan_core.h>
#include "vka_oot_heavy_pass_vrs.h"
int main(void) {
    const uint64_t hot[3] = {
        UINT64_C(0x1e4d2630d24846d0), UINT64_C(0x19f99e925937b038),
        UINT64_C(0x8ea627c8ef169ee1)
    };
    for(int f=0;f<3;f++) {
        assert(vka_oot_heavy_4x2_eligible(1,1,1,2,2,2,hot[f],0,1,
            VK_FORMAT_B10G11R11_UFLOAT_PACK32,VK_FORMAT_D32_SFLOAT,1,0));
        for(int i=0;i<15;i++) {
            int x[]={1,1,1,2,2,2,0,1,1,0};
            uint64_t key=hot[f]; VkFormat color=VK_FORMAT_B10G11R11_UFLOAT_PACK32;
            VkFormat depth=VK_FORMAT_D32_SFLOAT;
            switch(i) {
                case 0:x[0]=0;break;
                case 1:x[1]=0;break;
                case 2:x[2]=0;break;
                case 3:x[3]=1;break;
                case 4:x[4]=4;break;
                case 5:x[5]=1;break;
                case 6:key=UINT64_C(0x00ce4088af2c8e12);break;
                case 7:x[6]=1;break;
                case 8:x[7]=2;break;
                case 9:color=VK_FORMAT_R8G8B8A8_UNORM;break;
                case 10:depth=VK_FORMAT_UNDEFINED;break;
                case 11:x[8]=4;break;
                case 12:x[9]=1;break;
                case 13:key=0;break;
                case 14:x[3]=4;break;
            }
            assert(!vka_oot_heavy_4x2_eligible(x[0],x[1],x[2],x[3],x[4],x[5],
                key,x[6],x[7],color,depth,x[8],x[9]));
        }
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "heavy.c"
            exe = Path(tmp) / "heavy"
            src.write_text(code)
            cmd = [shutil.which("cc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                   "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                   "-I", str(ROOT / "dm/gfx/vk_android"), str(src), "-o", str(exe)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
