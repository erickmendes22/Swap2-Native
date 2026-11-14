"""Real transfer/compute/clear ordering with actual production dependency code."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from dm.gfx.tools.tests.test_depth_pass_optimizations import function
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/'dm/gfx/vk_android'
COMP='''#version 450
layout(local_size_x=64)in;
layout(set=0,binding=0,std430)readonly buffer A{uint a[];};
layout(set=0,binding=1,std430)writeonly buffer B{uint b[];};
layout(push_constant)uniform P{uint seed;}pc;
shared uint tmp[64];
void main(){uint i=gl_GlobalInvocationID.x;uint l=gl_LocalInvocationID.x;
tmp[l]=a[i]^pc.seed;barrier();b[i]=tmp[(l+1)&63]+i;}
'''

@unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','real Vulkan ICD required')
class SelectiveSyncGPU(unittest.TestCase):
 def run_fixture(self,name,files,expected,shader=None):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);env=dict(os.environ)
   for p,s in files.items():(d/p).write_text(s)
   if shader:
    p=d/'test.comp';p.write_text(shader);out=str(p)+'.spv'
    subprocess.run([shutil.which('glslangValidator'),'-V','--target-env','vulkan1.1','-o',out,str(p)],check=True,capture_output=True);env['SYNC_COMP']=out
   exe=d/'test';build=subprocess.run([shutil.which('cc'),'-O2','-DVKA_NDSR_PURE','-I',str(d),'-I',str(ROOT/'dm/third_party/vulkan-headers/include'),'-I',str(VK),str(VK/('selftest/'+name+'.c')),str(VK/'vka_ndsr.c'),'-ldl','-lm','-o',str(exe)],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=120)
   self.assertEqual(run.returncode,0,run.stdout+run.stderr)
   self.assertNotIn('Validation Error',run.stdout+run.stderr)
   for text,count in expected.items():self.assertEqual(run.stdout.count(text),count,run.stdout)
   print(run.stdout)

 def test_shared_storage_indirect_arguments_and_chained_consumers(self):
  tex=(VK/'vka_tex.c').read_text();draw=(VK/'vka_draw.c').read_text();ex=(VK/'vka_exec.c').read_text()
  barriers='\n'.join(function(tex,'void '+n+'(')for n in ['vka_barrier_at','vka_transfer_write_barrier_at','vka_compute_write_barrier_at'])
  policies=function(ex,'static void boost_transfer_barrier(')+'\n'+function(draw,'static void dispatch_write_barrier(')+'\n'+function(draw,'static void dispatch_argument_barrier(')
  self.run_fixture('selective_sync_gpu',{'sync_barriers.inc':barriers,'sync_policies.inc':policies},{'4096 bytes exact':32},COMP)

 def test_transfer_and_attachment_clears_with_preserved_untouched_pixels(self):
  tex=(VK/'vka_tex.c').read_text();ex=(VK/'vka_exec.c').read_text()
  barriers='\n'.join(function(tex,'void '+n+'(')for n in ['vka_barrier_at','vka_transfer_write_barrier_at','vka_attachment_parts_barrier_at'])
  self.run_fixture('selective_clear_gpu',{'clear_barriers.inc':barriers,'clear_policy.inc':function(ex,'void vka_clear_outside(')},{'full colour+depth exact':8})
if __name__=='__main__':unittest.main()
