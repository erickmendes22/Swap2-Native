"""Ocarina mesh GPU diagnostic: no missing direct shader, no fake overdraw.

The driver-only statistics are opt-in and the existing full shader library is
never modified. A small compiled C check verifies the scene geometry selector
used by the actual sampled graphics profiler.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
VKA = ROOT / "dm/gfx/vk_android"
MEMU = (VKA / "vka_memu.c").read_text()
CONV = (VKA / "vka_memu_spv.c").read_text()
PROF = (VKA / "vka_gprof.c").read_text()
DRAW = (VKA / "vka_draw.c").read_text()
DEVICE = (VKA / "vka_dev.c").read_text()
PSO = (VKA / "vka_pso.c").read_text()
HEAD = (VKA / "vka.h").read_text()


class MeshSceneProbe(unittest.TestCase):
    def test_cpu_known_taskless_mesh_direct_dispatch_is_bounded(self):
        inc = (VKA / "vka_memu_draw.inc").read_text()
        conv = (VKA / "vka_memu_spv.c").read_text()
        setup = (VKA / "memu/memu_common.glsl").read_text()
        self.assertIn('DM_VK_OOT_MEMU_DIRECT_DISPATCH", 1', inc)
        self.assertIn('if (st == 7 && MB.e[idx].direct_groups)', inc)
        self.assertIn('vk.vkCmdDispatch(g_cb, MB.e[idx].direct_groups, 1, 1);', inc)
        self.assertIn('else\\n        vk.vkCmdDispatchIndirect', inc)
        self.assertIn('R[VKA_MEMU_R_TOTAL]', setup.replace("r[R + VKA_MEMU_R_TOTAL]", "R[VKA_MEMU_R_TOTAL]"))
        self.assertIn('OpULessThan, B.t_bool, flat, lim', conv)
        cc = shutil.which("cc")
        if not cc: self.skipTest("C compiler missing")
        code = r"""
#include "vka_memu_direct_dispatch.h"
#include <assert.h>
int main(void) {
  assert(vka_memu_direct_groups(1,1,0,0,32,65535,65536,64,32,0)==32);
  assert(vka_memu_direct_groups(1,1,0,0,64,65535,65536,64,32,0)==64);
  assert(vka_memu_direct_groups(1,1,0,0,64,65535,4096,64,32,0)==0);
  assert(vka_memu_direct_groups(1,1,0,0,64,65535,4096,64,32,1)==64);
  assert(vka_memu_direct_groups(0,1,0,0,1,65535,65536,1,1,0)==0);
  assert(vka_memu_direct_groups(1,0,0,0,1,65535,65536,1,1,0)==0);
  assert(vka_memu_direct_groups(1,1,1,0,1,65535,65536,1,1,0)==0);
  assert(vka_memu_direct_groups(1,1,0,1,1,65535,65536,1,1,0)==0);
  assert(vka_memu_direct_groups(1,1,0,0,65,65535,65536,1,1,0)==0);
  assert(vka_memu_direct_groups(1,1,0,0,32,16,65536,1,1,0)==0);
  assert(vka_memu_direct_groups(1,1,0,0,1,65535,65536,0,0,0)==0);
  assert(vka_memu_direct_groups(1,1,0,0,32,65535,32,4294967295u,4294967295u,0)==0);
}
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)/"memu_direct.c"
            exe = Path(td)/"memu_direct"
            src.write_text(code)
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(VKA), str(src), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_actual_scene_profile_selects_both_1280x720_passes(self):
        compiler = shutil.which("cc")
        if not compiler:
            self.skipTest("C compiler missing")
        code = r"""
#include <assert.h>
#include "vka_scene_profile.h"
int main(void) {
    assert(vka_scene_profile_size("1280x720x1 c0:37 d:126"));
    assert(vka_scene_profile_1280("1280x720x1 c0:122 d:126"));
    assert(vka_scene_profile_1280("1280x720x1 d:126"));
    assert(vka_scene_profile_1280("1280x720x1"));
    assert(!vka_scene_profile_1280("1280x720x10"));
    assert(!vka_scene_profile_1280("1280x720x1_suffix"));
    assert(!vka_scene_profile_1280("1280x720x2 c0:122"));
    assert(!vka_scene_profile_1280(""));
    assert(!vka_scene_profile_1280(0));
    assert(vka_scene_profile_size("1280x720x1"));
    assert(vka_scene_profile_size("960x540x1 d:126"));
    assert(vka_scene_profile_size("683x384x1"));
    assert(!vka_scene_profile_size("1280x720x10"));
    assert(!vka_scene_profile_size("1280x720x2"));
    assert(!vka_scene_profile_size("1280x720x1not-a-pass"));
    assert(!vka_scene_profile_size("1280x719x1"));
    return 0;
}"""
        with tempfile.TemporaryDirectory() as td:
            exe, src = Path(td)/"scene-test", Path(td)/"scene-test.c"
            src.write_text(code)
            subprocess.run([compiler, "-std=c11", "-Wall", "-Werror",
                            "-I", str(VKA), str(src), "-o", str(exe)],
                           check=True)
            subprocess.run([str(exe)], check=True)

    def test_driver_statistics_are_real_and_opt_in(self):
        self.assertIn("VK_KHR_PIPELINE_EXECUTABLE_PROPERTIES_EXTENSION_NAME", DEVICE)
        self.assertIn("want_pipe_stats = VKA_ENV(\"DM_VK_PIPE_STATS\", 0)", DEVICE)
        self.assertIn("V.pipe_stats = 0;", DEVICE)
        self.assertIn("vkGetPipelineExecutableStatisticsKHR", HEAD)
        self.assertIn("VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR", PSO)
        self.assertIn("vka_pipe_stats(p, cs->key, 0, 0)", PSO)
        self.assertIn("vka_pipe_stats(p,", PSO)
        self.assertIn("VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_UINT64_KHR", DEVICE)

    def test_source_to_compute_ab_is_not_a_new_shader_library(self):
        self.assertIn("DM_VK_MEMU_PLANE_DIAG", MEMU)
        self.assertIn("vka_memu_cs_diagnostic_mode(", MEMU)
        self.assertIn("source-to-pipeline: source=", MEMU)
        self.assertIn("uint32_t plane_helper = 0;", CONV)
        self.assertIn("diag->fallback++", CONV)
        self.assertIn("diag->matched++", CONV)
        self.assertIn("lut_mode < 0 ? vka_memu_plane_lut() : lut_mode", CONV)
        self.assertIn("free(baseline);", MEMU)
        self.assertNotIn("VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR", CONV)

    def test_raster_depth_proxy_and_attachment_traffic_are_labeled(self):
        self.assertIn("vka_gp_pass_io(lc, scount, ld, sd, R.samples)", DRAW)
        self.assertIn("vka_gp_draw(sh[0]", DRAW)
        self.assertIn("g_scene.depth_test +=", PROF)
        self.assertIn("g_scene.depth_write +=", PROF)
        self.assertIn("g_scene.scissor_sum +=", PROF)
        self.assertIn("g_scene.direct_triangles +=", PROF)
        self.assertIn("1280x720 pass: frame", PROF)
        self.assertIn("NOT measured pixel overdraw", PROF)
        self.assertIn("NOT measured DRAM traffic", PROF)
        self.assertIn("VK_QUERY_TYPE_PIPELINE_STATISTICS", PROF)
        self.assertIn("VK_QUERY_PIPELINE_STATISTIC_FRAGMENT_SHADER_INVOCATIONS_BIT", PROF)
        self.assertIn("vka_gp_pass_begin_query(g_cb)", DRAW)
        self.assertIn("vka_gp_pass_end_query(g_cb)", DRAW)
        self.assertIn("g_scene.pipeline_query = g_pipe_active;", PROF)
        self.assertIn("pipelineStatisticsQuery != VK_FALSE", DEVICE)
        self.assertIn("VK_QUERY_RESULT_64_BIT", PROF)
        self.assertIn("fragment-invocations/target-pixel=", PROF)
        self.assertIn("for (int j = i - 1; j > 0 && g_m[j].gfx_block; --j)", PROF)
        # Both the sample-time and the report-time branches MUST use the
        # exact same tested token predicate. The old length=11 comparison
        # silently dropped every real "1280x720x1 c0:122 ..." descriptor.
        self.assertIn("g_pass_1280 = vka_scene_profile_1280(desc);", PROF)
        self.assertIn("if (!vka_scene_profile_1280(g_m[i].desc)) continue;", PROF)
        self.assertNotIn('strncmp(g_m[i].desc, "1280x720x1", 11)', PROF)
        self.assertIn("if (g_seen_1280 && !np)", PROF)
        self.assertIn("memset(elapsed, 0, sizeof elapsed);", PROF)
        self.assertIn("g_seen_1280 = 0;", PROF)


if __name__ == "__main__":
    unittest.main()
