"""Production null-colour policy/cache scopes and real dynamic-rendering parity."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from dm.tools.tests.test_cave_query_gpu import VERT, FRAG

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for i in range(opening + 1, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if not depth:
            return source[start:i + 1]
    raise AssertionError(signature)


class DepthPassOptimizations(unittest.TestCase):
    def test_production_policy_preserves_original_geometry_and_cache_order(self):
        draw = (VK / "vka_draw.c").read_text()
        start = draw.index("    if (omit_color && (dp || sp)")
        end = draw.index("    // Two measured Ocarina 1280x720", start)
        policy = draw[start:end]
        header = (VK / "vka.h").read_text()
        macros = "\n".join(next(line for line in header.splitlines() if line.startswith("#define " + name))
                           for name in ("VKA_COLOR_OMITTED", "VKA_COLOR_ORIGINAL", "VKA_COLOR_RENDER"))
        tex = (VK / "vka_tex.c").read_text()
        barrier = function(tex, "void vka_attachment_parts_barrier_at(")
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <vulkan/vulkan_core.h>
static unsigned vka_n_attachment_bar, calls;
static uint64_t g_unused_color_passes, g_unused_color_views;
static int vka_gp_active;
static void vka_gp_mark(VkCommandBuffer cb,const char*f,int l){(void)cb;(void)f;(void)l;}
static void barrier(VkCommandBuffer cb,VkPipelineStageFlags src,VkPipelineStageFlags dst,VkDependencyFlags flags,uint32_t n,const VkMemoryBarrier *mb,uint32_t nb,const VkBufferMemoryBarrier*b,uint32_t ni,const VkImageMemoryBarrier*i){
 (void)cb;(void)b;(void)i;
 assert(src==(VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT|VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT|VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT));
 assert(dst==VK_PIPELINE_STAGE_ALL_COMMANDS_BIT&&!flags&&n==1&&!nb&&!ni);
 assert(mb->dstAccessMask==(VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT));
 calls=mb->srcAccessMask;
}
static struct{PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier;}vk={barrier};
''' + macros + "\n" + barrier + r'''
int main(void){
 for(int color=0;color<2;color++)for(int depth=0;depth<2;depth++){
  vka_attachment_parts_barrier_at(0,color,depth,"test",1);
  assert(calls==((color||!depth?VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT:0)|(depth||!color?VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT:0)));
 }
 assert(vka_n_attachment_bar==4);
 for(int requested=0;requested<2;requested++)for(int dep=0;dep<2;dep++)
 for(int samples=1;samples<=4;samples*=4)for(int load=0;load<3;load++)
 for(int store=0;store<2;store++)for(int bound=0;bound<2;bound++){
  struct{unsigned samples;int color_omitted;VkRect2D area;unsigned layers;VkFormat cf[8];}R={.samples=samples,.area={{0,0},{31,17}},.layers=3,.cf={VK_FORMAT_R8G8B8A8_UNORM}};
  VkRenderingAttachmentInfo ca[8]={{.imageView=bound?(VkImageView)(uintptr_t)1:0,.loadOp=load,.storeOp=store}};
  VkRenderingAttachmentInfo *dp=dep?&ca[1]:0,*sp=0;int n=1,omit_color=requested;
''' + policy + r'''
  int expected=requested&&dep&&samples==1&&load==VK_ATTACHMENT_LOAD_OP_LOAD&&store==VK_ATTACHMENT_STORE_OP_STORE&&bound;
  assert(R.color_omitted==expected);
  assert(ca[0].imageView==(expected?0:bound?(VkImageView)(uintptr_t)1:0));
  assert(R.area.extent.width==31&&R.area.extent.height==17&&R.layers==3&&R.samples==(unsigned)samples);
  assert(R.cf[0]==VK_FORMAT_R8G8B8A8_UNORM);
  uint32_t tagged=R.cf[0]|(R.color_omitted?VKA_COLOR_OMITTED:0);
  assert(VKA_COLOR_ORIGINAL(tagged)==R.cf[0]);
  assert(VKA_COLOR_RENDER(tagged)==(expected?VK_FORMAT_UNDEFINED:R.cf[0]));
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            src, exe = d / "policy.c", d / "policy"
            src.write_text(harness)
            build = subprocess.run([shutil.which("cc"), "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
                                    "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                                    str(src), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            subprocess.run([str(exe)], check=True)
        # The fallback/clear transitions must restore actual colour targets;
        # keeping the mask while reopening a full pass is safe, never reverse.
        self.assertIn("if (R.on && R.color_omitted && !omit_color) vka_rp_end();", draw)
        self.assertIn("R.color_omitted && c->ci >= 0", draw)
        self.assertIn("g_unused_color_refused = 1;", draw)
        self.assertIn("rp_begin(rt, has_rt, d, 0)", draw)
        self.assertIn("!d->chmask.mask && !d->ms.a2c", draw)
        self.assertIn("!draw_writes(sh, d)", draw)

    def test_depth_only_fragment_elision_preserves_all_occlusion_queries(self):
        draw = (VK / "vka_draw.c").read_text()
        shader = (VK / "vka_shader.c").read_text()
        h = (VK / "vka_fs_elide.h").read_text()
        self.assertIn('VKA_ENV("DM_VK_OOT_DEPTH_NO_FS", 1)', draw)
        self.assertIn('vka_shader_oot_fs_pure(sh[1])', draw)
        self.assertIn('if (!p && elide)', draw)
        self.assertIn('p = vka_gfx_pipeline(sh, &lay, &k);', draw)
        self.assertIn('without_fs[1] = NULL;', draw)
        self.assertIn('vka_oq_draw();', draw)
        self.assertIn('ptr[a[2]] = ptr[a[3]];', h)
        self.assertIn('if (built[i] && ptr[i] == 1)', h)
        self.assertIn('vka_spv_pure_fragment_output(w, nb / 4)', shader)
        cc = shutil.which("cc")
        if not cc: self.skipTest("C compiler missing")
        c = r"""
#include "vka_fs_elide.h"
#include <assert.h>
static uint32_t w[128]; static size_t n;
static void add(unsigned op,unsigned count,const uint32_t *p){
 w[n++]=((count+1u)<<16)|op;
 for(unsigned i=0;i<count;i++)w[n++]=p[i];
}
#define I(op,...) do { uint32_t x[]={__VA_ARGS__};add(op,sizeof(x)/4,x);}while(0)
static void basic(void){
 n=5;w[0]=0x07230203;w[1]=0x00010600;w[2]=0;w[3]=64;w[4]=0;
 I(15,4,2,0x6e69616d,0);
 I(16,2,7);I(59,1,4,3);I(59,1,5,7);
 I(54,1,2,0,3);I(248,8);I(62,4,10);
}
int main(void) {
 assert(vka_oot_fs_elide_state(1,1,1,0,1,1,0,0,0,0,0));
 assert(!vka_oot_fs_elide_state(1,1,1,0,1,1,1,0,0,0,0));
 assert(!vka_oot_fs_elide_state(1,1,1,0,1,1,0,1,0,0,0));
 assert(!vka_oot_fs_elide_state(1,1,1,0,1,1,0,0,1,0,0));
 assert(!vka_oot_fs_elide_state(1,1,1,0,1,1,0,0,0,0,1));
 assert(!vka_oot_fs_elide_state(1,1,1,0,1,4,0,0,0,0,0));
 basic(); I(62,5,10);I(253,0);I(56,0);
 assert(vka_spv_pure_fragment_output(w,n));
 basic(); I(252,0);I(253,0);I(56,0);
 assert(!vka_spv_pure_fragment_output(w,n));
 basic(); I(99,1,10);I(253,0);I(56,0);
 assert(!vka_spv_pure_fragment_output(w,n));
 basic(); I(62,6,10);I(253,0);I(56,0);
 assert(!vka_spv_pure_fragment_output(w,n));
 basic(); I(253,0);I(56,0);I(71,4,11,22);
 assert(!vka_spv_pure_fragment_output(w,n));
 basic(); I(253,0);I(56,0);I(16,2,12);
 assert(!vka_spv_pure_fragment_output(w,n));
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)/"elide.c"
            exe = Path(td)/"elide"
            src.write_text(c)
            run = subprocess.run([cc, "-std=c11", "-O2", "-Wall", "-Wextra",
                "-Werror", "-I", str(VK), str(src), "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            subprocess.run([str(exe)], check=True)

    def test_ocarina_720p_depth_store_none_policy_and_write_safety(self):
        draw = (VK / "vka_draw.c").read_text()
        self.assertIn('da.storeOp = VK_ATTACHMENT_STORE_OP_NONE;', draw)
        self.assertIn('VKA_ENV("DM_VK_OOT_DEPTH_STORE_NONE", 0)', draw)
        self.assertIn('V.props.apiVersion >= VK_API_VERSION_1_3', draw)
        self.assertIn('if (R.on && R.readonly_depth_store && d && d->ds.dt && d->ds.dw)', draw)
        self.assertIn('if (R.on && R.readonly_depth_store && c->ci < 0)', draw)
        header = (VK / "vka_readonly_depth_store.h").read_text()
        self.assertIn('width == 1280u && height == 720u', header)
        self.assertIn('depth_load && original_store && !pending_depth_clear', header)
        harness = """
#include <assert.h>
#include "vka_readonly_depth_store.h"
int main(void) {
    int args[13]={1,1,1280,720,1,1,1,0,1,1,0,0,0};
    assert(vka_readonly_depth_store_eligible(1,1,1280,720,1,1,1,0,1,1,0,0,0));
    for(int i=0;i<13;i++){
       int a[13];for(int j=0;j<13;j++)a[j]=args[j];
       a[i]=(i==2)?960:(i==3)?540:(i==4)?4:(i==7||i>=10)?1:0;
       assert(!vka_readonly_depth_store_eligible(a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12]));
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / "depth_store.c", Path(tmp) / "depth_store"
            src.write_text(harness)
            run = subprocess.run([shutil.which("cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                                  "-I", str(VK), str(src), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            subprocess.run([str(exe)], check=True)

    @unittest.skipUnless(os.getenv("MEMU_TEST_VULKAN") == "1", "real Vulkan ICD required")
    def test_real_query_colour_and_depth_parity_for_all_switch_combinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            tex = (VK / "vka_tex.c").read_text()
            (d / "attachment_parts.inc").write_text(
                function(tex, "void vka_attachment_write_barrier_at(") + "\n" +
                function(tex, "void vka_attachment_parts_barrier_at("))
            env = dict(os.environ)
            for stage, source in (("vert", VERT), ("frag", FRAG)):
                p = d / ("test." + stage)
                p.write_text(source)
                spv = str(p) + ".spv"
                subprocess.run([shutil.which("glslangValidator"), "-V", "--target-env", "vulkan1.1",
                                "-S", stage, "-o", spv, str(p)], check=True, capture_output=True)
                env["CAVE_" + stage.upper()] = spv
            exe = d / "depth"
            build = subprocess.run([shutil.which("cc"), "-O2", "-DVKA_NDSR_PURE", "-I", str(d),
                                    "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                                    "-I", str(VK), str(VK / "selftest/depth_pass_gpu.c"),
                                    str(VK / "vka_ndsr.c"), "-ldl", "-lm", "-o", str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn("Validation Error", run.stdout + run.stderr)
            self.assertEqual(run.stdout.count("192 precise queries exact"), 6, run.stdout)
            print(run.stdout)


if __name__ == "__main__":
    unittest.main()
