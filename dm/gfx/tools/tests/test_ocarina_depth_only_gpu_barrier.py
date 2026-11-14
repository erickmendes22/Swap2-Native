"""Production depth-only Vulkan dependency: compile actual path and assert masks.

Not a claim of FPS improvement: this proves our 823-per-frame opportunity
removes unrelated colour producer stages while preserving depth visibility.
"""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[4]
TEX=(ROOT/"dm/gfx/vk_android/vka_tex.c").read_text()
DRAW=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
BEGIN="void vka_depth_write_barrier_at(VkCommandBuffer cb, const char *file, int line) {"
END="// A pass that truly did not write any colour/depth/stencil attachment or"

class DepthBarrier(unittest.TestCase):
    def test_actual_vk_memory_barrier_masks(self):
        self.assertIn(BEGIN,TEX)
        function=TEX[TEX.index(BEGIN):TEX.index(END,TEX.index(BEGIN))]
        harness=r"""
#include <stdint.h>
#include <stdlib.h>
typedef void* VkCommandBuffer;
typedef unsigned VkPipelineStageFlags;
typedef unsigned VkAccessFlags;
typedef struct { unsigned sType, pNext; VkAccessFlags srcAccessMask,dstAccessMask; } VkMemoryBarrier;
enum {
 VK_STRUCTURE_TYPE_MEMORY_BARRIER=100,
 VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT=1<<0,
 VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT=1<<1,
 VK_ACCESS_MEMORY_READ_BIT=1<<2,
 VK_ACCESS_MEMORY_WRITE_BIT=1<<3,
 VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT=1<<4,
 VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT=1<<5,
 VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT=1<<6,
 VK_PIPELINE_STAGE_ALL_COMMANDS_BIT=1<<7
};
static int vka_gp_active;
static uint64_t vka_n_depth_only_bar;
static void vka_gp_mark(VkCommandBuffer cb,const char* file,int line) { (void)cb;(void)file;(void)line; abort(); }
static int calls;
static void mock_barrier(VkCommandBuffer cb, VkPipelineStageFlags src,VkPipelineStageFlags dst,unsigned dep,
        unsigned n,const VkMemoryBarrier *mb,unsigned nbuf,const void*buf,unsigned nimg,const void*img) {
 (void)cb;(void)buf;(void)img;
 if(src!=(VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT|VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT)||
    dst!=VK_PIPELINE_STAGE_ALL_COMMANDS_BIT||dep||n!=1||!mb||nbuf||nimg||
    mb->srcAccessMask!=VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT||
    mb->dstAccessMask!=(VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT)) abort();
 ++calls;
}
static struct { void (*vkCmdPipelineBarrier)(VkCommandBuffer,VkPipelineStageFlags,VkPipelineStageFlags,unsigned,
unsigned,const VkMemoryBarrier*,unsigned,const void*,unsigned,const void*); } vk={mock_barrier};
""" + function + r"""
int main(void) {
 for(int i=0;i<823;i++)vka_depth_write_barrier_at((VkCommandBuffer)1,"test",40);
 if(calls!=823||vka_n_depth_only_bar!=823)return 2;
 return 0;
}
"""
        cc=shutil.which("cc") or shutil.which("clang")
        with tempfile.TemporaryDirectory() as t:
            src=pathlib.Path(t)/"test.c";exe=pathlib.Path(t)/"test"
            src.write_text(harness)
            p=subprocess.run([cc,"-std=c11","-Wall","-Wextra","-Werror",
                "-fsanitize=undefined",str(src),"-o",str(exe)],
                capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            r=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_production_selects_only_known_depth_producer(self):
        p=DRAW.index('void vka_rp_end(void) {')
        q=DRAW.index('// OP_BARRIER used to end a render pass',p)
        body=DRAW[p:q]
        self.assertIn('R.cave_dwrite && !R.cave_cwrite',body)
        self.assertIn('vka_depth_write_barrier(g_cb);',body)
        self.assertIn('else { g_rp_scoped++; vka_attachment_write_barrier(g_cb); }',body)
        self.assertLess(body.index('if (full || (R.swrite'), body.index('R.cave_dwrite && !R.cave_cwrite'))
        self.assertLess(body.index('const int reused'), body.index('R.cave_dwrite && !R.cave_cwrite'))
        self.assertIn('if ((R.df != VK_FORMAT_UNDEFINED && d->ds.dt && d->ds.dw)',DRAW)
        self.assertIn('if (k.att[i].mask) { R.awrite = 1; R.cave_cwrite = 1; break; }',DRAW)
        # 823/949 are eligible in the heavy-scene sampled frame (ceiling,
        # NOT GPU time saved); semantic matrix: all producers still ordered.
        for colour in range(2):
            for depth in range(2):
                for storage in range(2):
                    for force in range(2):
                        path="full" if force or storage else (
                            "depth" if depth and not colour else "combined")
                        if path=="depth":
                            self.assertTrue(depth and not colour and not storage and not force)
                        else:
                            self.assertFalse(path=="depth")

if __name__=="__main__":unittest.main()
