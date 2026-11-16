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
        self.assertIn('else' + chr(10) + '        vk.vkCmdDispatchIndirect', inc)
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

    def test_hot_mesh_undefer_is_narrow_and_keeps_old_pack(self):
        hdr = (VKA / "vka_memu_undefer.h").read_text()
        memu = (VKA / "vka_memu.c").read_text()
        cache = (VKA / "vka_memu.h").read_text()
        self.assertIn("mesh_plane_defer", hdr)
        self.assertIn("mesh_plane_clear", hdr)
        self.assertIn("mesh_plane_flush", hdr)
        self.assertIn("removed deferred Workgroup copy", memu)
        self.assertIn('DM_VK_OOT_MEMU_UNDEFER", 1', memu)
        self.assertIn("vka_memu_undefer_hot(s->key)", memu)
        self.assertIn("VKA_MEMU_KEY_UNDEFER", cache)
        self.assertIn("VKA_MEMU_KEY_UNDEFER : 0", memu)
        self.assertIn("vka_memu_cs_masked(source,", memu)
        self.assertIn("vka_memu_cs(src, src_words,", memu)
        self.assertIn("if (nc != 2) goto done;", hdr)
        self.assertIn("if (calls < 16 || drops < 2) goto done;", hdr)
        self.assertIn("out[o+3] = f[0];", hdr)

    def test_undefer_header_compiles_and_refuses_unknown_sources(self):
        cc = shutil.which("cc")
        if not cc: self.skipTest("C compiler missing")
        c = r"""
#include "vka_memu_undefer.h"
#include <assert.h>
int main(void) {
  uint32_t bad[]={0x07230203,0x00010600,0,256,0,0x00020011,1};
  size_t n=7;uint32_t nc=9;
  assert(vka_memu_undefer(bad,7,&n,&nc)==0 && n==0 && nc==0);
  assert(vka_memu_undefer_hot(UINT64_C(0xeb021183bf9b0092)));
  assert(vka_memu_undefer_hot(UINT64_C(0xfed302d791a4ba43)));
  assert(!vka_memu_undefer_hot(UINT64_C(0x73dc0b90c4082e43)));
  return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "check.c"
            exe = Path(td) / "check"
            path.write_text(c)
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(VKA), str(path), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_undefer_removes_exact_staging_copy_and_preserves_other_workgroup(self):
        cc = shutil.which("cc")
        if not cc: self.skipTest("C compiler missing")
        # Synthetic SPIR-V shape: store/defer/clear/flush, two staging
        # Workgroup variables, one unrelated Workgroup variable and 20 calls.
        # The source remains unmodified. Test every resulting instruction.
        c = r"""
#include "vka_memu_undefer.h"
#include <assert.h>
#include <stdio.h>
static uint32_t w[512]; static size_t n;
static void ins(unsigned op,unsigned cnt,const uint32_t *v) {
  w[n++]=((cnt+1)<<16)|op;
  for(unsigned i=0;i<cnt;i++) w[n++]=v[i];
}
#define I(op,...) do {uint32_t v[]={__VA_ARGS__};ins(op,sizeof(v)/4,v);}while(0)
static void name(unsigned id,const char*s) {
  uint32_t v[32]={0};v[0]=id;memcpy(v+1,s,strlen(s));
  ins(5,1+strlen(s)/4+1,v);
}
static void fn(unsigned id){I(54,9u,id,0u,8u);I(248,id+80);}
static void end(void){I(253,0u);I(56,0u);}
int main(void) {
  n=5;w[0]=0x07230203;w[1]=0x00010600;w[3]=256;
  name(1,"mesh_plane_store");name(2,"mesh_plane_defer");
  name(3,"mesh_plane_flush");name(4,"mesh_plane_clear");
  I(15,5365u,20u,0x6e69616du,0u,30u,31u,32u);
  I(59,10u,30u,4u);I(59,10u,31u,4u);I(59,10u,32u,4u);
  fn(1);end();
  fn(2);I(65,11u,40u,30u,60u);I(65,11u,41u,31u,60u);end();
  fn(3);end();fn(4);end();
  fn(20);I(57,9u,72u,4u);
  for(int i=0;i<20;i++)I(57,9u,(unsigned)(120+i),2u);
  I(57,9u,151u,3u);end();
  size_t old=n, now=0;uint32_t calls=0;
  uint32_t *out=vka_memu_undefer(w,n,&now,&calls);
  assert(out && calls==20 && now<old);
  unsigned store=0, entry=0, other=0;
  for(size_t p=5;p<now;p+=out[p]>>16) {
    unsigned op=out[p]&65535u,len=out[p]>>16;
    if(op==57){assert(out[p+3]!=2&&out[p+3]!=3&&out[p+3]!=4);
      if(out[p+3]==1)store++;}
    if(op==59){assert(out[p+2]!=30&&out[p+2]!=31);other++;}
    if(op==15){entry++;for(unsigned k=5;k<len;k++)
      assert(out[p+k]!=30&&out[p+k]!=31);}
  }
  assert(store==20&&entry==1&&other==1);
  free(out);return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "exact_shape.c"
            exe = Path(td) / "exact_shape"
            src.write_text(c)
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
