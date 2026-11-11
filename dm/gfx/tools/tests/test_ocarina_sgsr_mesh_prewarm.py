"""Source contracts for two GPU optimizations imported from BananaNative.

The SGSR1 fragment source must be compiled and SPIR-V validated by CI (a
second step). These tests do not claim a device-level FPS gain.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PRESENT = (ROOT / 'dm/gfx/vk_android/vka_present.c').read_text()
SGSR = (ROOT / 'dm/gfx/vk_android/fsr/sgsr1.frag').read_text()
SGSR_BUILD = (ROOT / 'dm/gfx/vk_android/fsr/sgsr_spv.py').read_text()
PSO = (ROOT / 'dm/gfx/vk_android/vka_pso.c').read_text()
JAVA = (ROOT / 'android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java').read_text()


class SgsrMesh(unittest.TestCase):
    def test_sgsr_is_compiled_single_pass_in_720p_gpu_attachment(self):
        self.assertIn('#include "vka_present_sgsr.h"', PRESENT)
        self.assertIn('vka_sgsr1_frag', PRESENT)
        self.assertIn('if (sgsr && g_fsr.sgsr)', PRESENT)
        self.assertIn('g_fsr.finish[k]', PRESENT)
        self.assertIn('static int fsr_mid(unsigned k, uint32_t w, uint32_t h, int sgsr_only)', PRESENT)
        self.assertIn('(sgsr_only ? !g_fsr.mid[k] : !!g_fsr.mid[k])', PRESENT)
        self.assertIn('if (!sgsr_only)', PRESENT)
        self.assertIn('sgsr && g_fsr.sgsr ? 1u : 2u', PRESENT)
        self.assertIn('if (g_fsr.mid[k]) vk.vkDestroyImage', PRESENT)
        self.assertIn('if (g_fsr.finish[k]) vk.vkDestroyImage', PRESENT)
        self.assertIn('vka_img_barrier(cb, g_fsr.finish[k]', PRESENT)
        self.assertIn('rk.vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_fsr.sgsr)', PRESENT)
        self.assertIn('if (!g_fsr.sgsr)', PRESENT)
        self.assertIn('} // end FSR1 two-pass fallback', PRESENT)
        self.assertIn('1280.0 / dw, 720.0 / dh', PRESENT)
        self.assertIn('VK_FORMAT_R8G8B8A8_UNORM', PRESENT)
        self.assertIn('vka_fsr_easu_frag', PRESENT)
        self.assertIn('vka_fsr_rcas_frag', PRESENT)
        self.assertIn('g_rot.pipe', PRESENT)

    def test_sgsr_spirv_source_has_edge_adaptive_qualcomm_algorithm(self):
        self.assertIn('SPDX-License-Identifier: BSD-3-Clause', SGSR)
        self.assertIn('fastLanczos2', SGSR)
        self.assertIn('textureGather(tex', SGSR)
        self.assertIn('edgeVote', SGSR)
        self.assertIn('fragColour = vec4(color, 1.0)', SGSR)
        self.assertIn('spirv-val', SGSR_BUILD)
        self.assertIn('--target-env=vulkan1.1', SGSR_BUILD)
        self.assertIn('vka_present_sgsr.h', SGSR_BUILD)

    def test_ui_can_select_onepass_and_preserve_previous_fsr(self):
        self.assertIn('"SGSR 1 (1 passagem até 720p)"', JAVA)
        self.assertIn('value = clamp(value, 0, 4);', JAVA)
        self.assertIn('runningFsr = value == 3 || value == 4;', JAVA)
        self.assertIn('return Prefs.OCARINA_TITLE.equals(id) && previous == 0 ? 4 : previous;', JAVA)
        self.assertIn('out.add("DM_VK_FSR=" + (m == 3 || m == 4 ? 1 : 0));', JAVA)
        self.assertIn('present_filter == 4', PRESENT)

    def test_sampleable_images_do_not_require_native_blit_source(self):
        # Ocarina's Adreno window format is sampleable with linear filtering,
        # but may lack VK_FORMAT_FEATURE_BLIT_SRC_BIT. SGSR/FSR should still
        # render using the shader path, not silently use rot-linear.
        self.assertIn('int can_sample = im && im->inited', PRESENT)
        self.assertIn('VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT', PRESENT)
        self.assertIn('VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT', PRESENT)
        self.assertIn('int fsr = fsr_wanted() && can_sample && (dw > cw || dh > ch);', PRESENT)
        self.assertIn('SGSR/FSR upscale unavailable: reason=', PRESENT)
        self.assertNotIn('int fsr = blit > 0 && fsr_wanted()', PRESENT)

    def test_mesh_pipelines_prewarms_task_mesh_and_fragment(self):
        self.assertIn('r->kind > 2', PSO)
        self.assertIn('r.kind == 2', PSO)
        self.assertIn('sh[6] = vka_shader_by_key(r.key[0])', PSO)
        self.assertIn('sh[7] = vka_shader_by_key(r.key[1])', PSO)
        self.assertIn('sh[1] = vka_shader_by_key(r.key[2])', PSO)
        self.assertIn('vka_shader *record[5] = {sh[6], sh[7], sh[1], NULL, NULL};', PSO)
        self.assertIn('pw_note(2, record, k,', PSO)
        self.assertIn('gfx_obtain(&fk, fnv(&fk, len', PSO)


if __name__ == '__main__':
    unittest.main()
