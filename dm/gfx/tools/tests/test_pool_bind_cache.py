"""Exact-layout texture/feedback binding cache and real Vulkan consumers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/'dm/gfx/vk_android'
COMP='''#version 450
layout(local_size_x=1)in;
layout(set=0,binding=0,std430)writeonly buffer O{uint o[];};
layout(set=1,binding=0,std430)readonly buffer P{uint p[];};
layout(set=2,binding=0,std430)writeonly buffer F{uint f[];};
layout(push_constant)uniform C{uint i;}pc;
void main(){o[pc.i]=p[0]^pc.i;f[pc.i]=p[0]+pc.i;}
'''
class PoolBindCache(unittest.TestCase):
 def test_bind_point_reset_layout_feedback_and_partial_pool(self):
  src=r'''
#include <assert.h>
#include <stdint.h>
#include "vka_pool_bind_cache.h"
#define H(T,n) ((T)(uintptr_t)(n))
int main(void){
 vka_pool_bind_cache c[2]={{0}};VkPipelineLayout a=H(VkPipelineLayout,1),b=H(VkPipelineLayout,2);VkDescriptorSet p[2]={H(VkDescriptorSet,3),H(VkDescriptorSet,4)};
 for(int st=0;st<2;st++){vka_pool_bind_prepare(&c[st],a,0);assert(!vka_pool_bind_same(&c[st],a,p,2));vka_pool_bind_prepare(&c[st],a,1);assert(vka_pool_bind_same(&c[st],a,p,2));}
 vka_pool_bind_prepare(&c[1],b,1);assert(!vka_pool_bind_same(&c[1],b,p,2));assert(vka_pool_bind_same(&c[0],a,p,2));
 vka_pool_bind_revision(&c[0],1);assert(!vka_pool_bind_same(&c[0],a,p,2));
 vka_pool_bind_revision(&c[0],1);assert(vka_pool_bind_same(&c[0],a,p,2));
 vka_pool_bind_revision(&c[0],2);assert(!vka_pool_bind_same(&c[0],a,p,2));
 for(unsigned i=0;i<10000;i++){
  for(int st=0;st<2;st++){
   vka_pool_bind_prepare(&c[st],a,0);assert(!vka_pool_bind_same(&c[st],a,p,2));assert(vka_pool_bind_same(&c[st],a,p,2));
   VkDescriptorSet z[2]={p[0],H(VkDescriptorSet,i+100)};assert(!vka_pool_bind_same(&c[st],a,z,2));assert(vka_pool_bind_same(&c[st],a,z,2));
   assert(!vka_pool_bind_same(&c[st],a,z,1));assert(vka_pool_bind_same(&c[st],a,z,1));
   vka_pool_bind_prepare(&c[st],b,1);assert(!vka_pool_bind_same(&c[st],a,z,1));
   c[st].valid=0;assert(!vka_pool_bind_same(&c[st],a,z,1));assert(!vka_pool_bind_same(&c[st],a,z,0));
  }
 }
}
'''
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);(d/'test.c').write_text(src);exe=d/'test'
   subprocess.run(['cc','-O2','-fsanitize=undefined','-I',str(VK),'-I',str(ROOT/'dm/third_party/vulkan-headers/include'),str(d/'test.c'),'-o',str(exe)],check=True,capture_output=True)
   subprocess.run([str(exe)],check=True)
  draw=(VK/'vka_draw.c').read_text();inc=(VK/'vka_memu_draw.inc').read_text()
  self.assertIn('g_set0_layout[pool_slot] == lay->layout',draw)
  self.assertIn('g_set0_layout[pool_slot] = lay->layout;',draw)
  self.assertIn('g_set0_layout[0] = g_set0_layout[1] = VK_NULL_HANDLE;',draw)
  self.assertIn('g_set0_layout[1] = VK_NULL_HANDLE;',inc)
  self.assertIn('vka_tex_pfb_draw();',draw)
  self.assertIn('g_pool_bind[0].valid = g_pool_bind[1].valid = 0;',draw)
  self.assertIn('g_pd[1].n = 0; g_pool_bind[1].valid = 0;',inc)
  self.assertIn('g_pd[1].n = 0; g_pool_bind[1].valid = 0;',draw)
  tex=(VK/'vka_tex.c').read_text()
  self.assertEqual(tex.count('vk.vkUpdateDescriptorSets('),1)
  self.assertIn('vka_pool_descriptor_revision()',draw)
  self.assertIn('atomic_fetch_add_explicit(&g_pool_descriptor_revision, 1, memory_order_release)',tex)

 @unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','real Vulkan required')
 def test_real_gpu_outputs_feedback_and_incompatible_layouts(self):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);p=d/'test.comp';p.write_text(COMP);spv=str(p)+'.spv'
   subprocess.run([shutil.which('glslangValidator'),'-V','-o',spv,str(p)],check=True,capture_output=True)
   exe=d/'gpu';build=subprocess.run(['cc','-O2','-DVKA_NDSR_PURE','-I',str(VK),'-I',str(ROOT/'dm/third_party/vulkan-headers/include'),str(VK/'selftest/pool_bind_gpu.c'),str(VK/'vka_ndsr.c'),'-ldl','-lm','-o',str(exe)],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run([str(exe)],env=dict(os.environ,POOL_COMP=spv),capture_output=True,text=True,timeout=60)
   self.assertEqual(run.returncode,0,run.stdout+run.stderr)
   self.assertNotIn('Validation Error',run.stdout+run.stderr)
   self.assertEqual(run.stdout.count('outputs and256 feedback slots exact'),2,run.stdout)
   print(run.stdout)
if __name__=='__main__':unittest.main()
