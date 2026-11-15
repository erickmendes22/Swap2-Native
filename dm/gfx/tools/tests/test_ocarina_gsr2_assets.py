"""Structural prerequisites for Qualcomm GSR2 in the Ocarina Vulkan fork.

A spatial NDSR colour binding is NOT a DLSS interface: it contains neither
depth nor movement. A runtime GSR2 implementation must supply all inputs and
invalidate its temporal history explicitly rather than use zero vectors.
"""
import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
D = ROOT / "dm/gfx/vk_android/gsr2"

class Gsr2Assets(unittest.TestCase):
    def test_three_passes_and_licence(self):
        names = ("convert", "activate", "upscale")
        for name in names:
            s = (D / f"gsr2_{name}.comp").read_text()
            self.assertIn("#version 450", s)
            self.assertIn("Qualcomm Innovation Center", s)
            self.assertIn("BSD-3-Clause", s)
            self.assertIn("layout(local_size_x = 8, local_size_y = 8)", s)
            self.assertIn("layout(set = 0, binding = 4", s)
            self.assertIn("layout(set = 0, binding = 5", s)
        self.assertIn("Redistribution and use", (D / "LICENSE").read_text())

    def test_real_temporal_resources_not_optional(self):
        conv = (D / "gsr2_convert.comp").read_text()
        activate = (D / "gsr2_activate.comp").read_text()
        upscale = (D / "gsr2_upscale.comp").read_text()
        for name in ("InputDepth", "InputColor", "InputVelocity"):
            self.assertIn(name, conv)
        for name in ("PrevLumaHistory", "PrevMotionDepthAlphaBuffer"):
            self.assertIn(name, activate)
        for name in ("PrevHistoryOutput", "MotionDepthClipAlphaBuffer", "HistoryOutput"):
            self.assertIn(name, upscale)
        self.assertRegex(upscale, r"float reset;")
        # Existing Ocarina NDSR is spatial only; it must not be mistaken
        # for a source of game-provided motion or depth.
        ndsr = (ROOT/"dm/gfx/vk_android/vka_ndsr.c").read_text()
        self.assertIn("purely spatial network:", ndsr)
        self.assertIn("no history, motion or depth", ndsr)

    def test_generator_has_three_passes_and_atomic_output(self):
        src = (D/"gsr2_spv.py").read_text()
        ast.parse(src)
        for name in ("convert", "activate", "upscale"):
            self.assertIn(f'vka_gsr2_{name}', src)
        self.assertIn("spirv_val", src)
        self.assertIn("temp.replace(OUTPUT)", src)

    def test_gsr2_menu_and_launcher_gate_match_banana_profiles(self):
        game_settings=(ROOT/"android/app/src/main/java/dev/nxnative/android/GameSettings.java").read_text()
        graphics=(ROOT/"android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java").read_text()
        profile=(ROOT/"android/app/src/main/java/dev/nxnative/android/OcarinaRenderProfile.java").read_text()
        self.assertIn("static boolean temporalGsr2(int mode)",profile)
        self.assertIn("OcarinaRenderProfile.temporalGsr2(temporalProfile)",game_settings)
        self.assertIn("temporal.toggle(a,Prefs.ootGsr2(a,id)",game_settings)
        self.assertIn("OcarinaRenderProfile.temporalGsr2(Prefs.renderProfile(c,id))",graphics)
        self.assertIn('out.add("DM_VK_OOT_GSR2=" + (ootGsr2 ? 1 : 0))',graphics)
        self.assertNotIn("if (OcarinaRenderProfile.direct720(Prefs.renderProfile(a,id)))",game_settings)

    def test_actual_194_shader_key_does_not_bypass_gsr2(self):
        src=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
        run=(ROOT/"dm/gfx/vk_android/vka_gsr2.c").read_text()
        self.assertIn("04135bb812a0d66e",src)
        self.assertIn("vka_ndsr_match(sh[5]->e,sh[5]->b",src)
        self.assertNotIn('sh[5]->key==UINT64_C(0xd99fbeeb53d38847) ||',src)
        self.assertIn("(src->w==640 && src->h==360)",run)
        self.assertIn("(src->w==960 && src->h==540)",run)
        self.assertIn('VLOG("Ocarina GSR2 NDSR candidate:',src)

    def test_optical_flow_uses_pixel_units_once(self):
        flow=(D/"ocarina_flow.comp").read_text()
        run=(ROOT/"dm/gfx/vk_android/vka_gsr2.c").read_text()
        conv=(D/"gsr2_convert.comp").read_text()
        up=(D/"gsr2_upscale.comp").read_text()
        self.assertIn("vec4(vec2(delta),reject,0.0)",flow)
        self.assertIn("{1.0f/iw,1.0f/ih},1.0f,reset",run)
        self.assertIn("vec2 motion = -2.0 * velocity.xy * p.mvs;",conv)
        self.assertIn("-0.5 * Motion.x + Hruv.x",up)

    def test_195_full_frame_noise_avoids_cross_format_blit(self):
        src=(ROOT/"dm/gfx/vk_android/vka_gsr2.c").read_text()
        up=(D/"gsr2_upscale.comp").read_text()
        stable=(ROOT/"dm/gfx/vk_android/fsr/ndsr_sgsr.comp").read_text()
        self.assertIn("VK_FORMAT_R32_UINT",src)
        self.assertIn("VK_FORMAT_B10G11R11_UFLOAT_PACK32",src)
        self.assertIn("vk.vkCmdCopyImage(cb,w[W_OUTPUT].img",src)
        self.assertNotIn("vk.vkCmdBlitImage(cb,w[W_OUTPUT].img",src)
        self.assertIn("VK_FORMAT_FEATURE_TRANSFER_SRC_BIT",src)
        self.assertIn("VK_FORMAT_FEATURE_TRANSFER_DST_BIT",src)
        self.assertIn("layout(set = 0, binding = 5, r32ui)",up)
        self.assertIn("imageStore(SceneColorOutput, gid, uvec4(pack_b10g11r11(outColour)",up)
        self.assertIn("packHalf2x16",stable)
        self.assertIn("packHalf2x16",up)

    def test_generator_matches_on_gpu_runner_if_available(self):
        sys.path.insert(0, str(D))
        import gsr2_spv
        if not (gsr2_spv.tool("glslc") and gsr2_spv.tool("spirv-val")):
            self.skipTest("NDK shader tools not installed on this runner")
        generated = gsr2_spv.compile_header()
        for sym in ("vka_gsr2_convert", "vka_gsr2_activate", "vka_gsr2_upscale"):
            self.assertIn("static const uint32_t " + sym, generated)

if __name__ == "__main__":
    unittest.main()
