"""Execute actual guard and actual Vulkan barrier descriptors, including fallback."""
from pathlib import Path
import subprocess,tempfile,shutil,unittest
ROOT=Path(__file__).resolve().parents[4]
class CaveSyncGuard(unittest.TestCase):
 def test_production_guard_keeps_upload_and_shader_writer_splits(self):
  text=(ROOT/'dm/gfx/vk_android/vka_draw.c').read_text();a=text.index('int vka_rp_cave_sync(void)');fn=text[a:text.index('\nvoid vka_rp_end',a)]
  code=r'''
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "vka_cave_sync.h"
static struct{int on,df,sf,swrite,bar_pending;}R;static struct{int n;}PC;
static int g_classic_pass,uploads,calls;static uint64_t g_cave_sync_inpass,g_cave_sync_fallback;
static VkCommandBuffer g_cb;
static int vka_ub_active(void){return uploads;}
static void VKAPI_CALL capture(VkCommandBuffer cb,VkPipelineStageFlags src,VkPipelineStageFlags dst,VkDependencyFlags flags,uint32_t n,const VkMemoryBarrier*b,uint32_t nb,const VkBufferMemoryBarrier*bb,uint32_t ni,const VkImageMemoryBarrier*ib){
 (void)cb;(void)bb;(void)ib;
 if(src!=VKA_CAVE_DEPTH_STAGES||dst!=src||flags!=VK_DEPENDENCY_BY_REGION_BIT||n!=1||nb||ni||b->srcAccessMask!=VKA_CAVE_DEPTH_ACCESS||b->dstAccessMask!=b->srcAccessMask){abort();}
 calls++;
}
static struct{PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier;}vk={capture};
'''+fn+r'''
int main(void){for(int on=0;on<2;on++)for(g_classic_pass=0;g_classic_pass<2;g_classic_pass++)for(int df=0;df<2;df++)for(int sf=0;sf<2;sf++)for(int writer=0;writer<2;writer++)for(int guest_bar=0;guest_bar<2;guest_bar++)for(PC.n=0;PC.n<2;PC.n++)for(uploads=0;uploads<2;uploads++){
 R=(typeof(R)){on,df,sf,writer,guest_bar};int wanted=on&&g_classic_pass&&(df||sf)&&!writer&&!guest_bar&&!PC.n&&!uploads;int old=calls;
 if(vka_rp_cave_sync()!=wanted||calls-old!=wanted)abort();
}puts("256 real guard cases pass, framebuffer dependency fields match");return 0;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'test.c';exe=Path(tmp)/'test';p.write_text(code)
   r=subprocess.run([shutil.which('cc'),'-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',str(ROOT/'dm/third_party/vulkan-headers/include'),'-I',str(ROOT/'dm/gfx/vk_android'),str(p),'-o',str(exe)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(exe)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
  exec_=(ROOT/'dm/gfx/vk_android/vka_exec.c').read_text()
  self.assertNotIn('g_oq_visible',exec_)
  self.assertNotIn('DM_VK_OOT_CAVE_VISIBLE',exec_)
  self.assertIn('post((pop){4, (uint32_t)g_oq_fresh, g_oq_lost, t, ad, g_oq_seg0, g_oq_head})',exec_)
if __name__=='__main__':unittest.main()
