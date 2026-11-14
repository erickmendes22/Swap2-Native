"""Real GPU query counts and colour/depth equality for in-pass cave dependency."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
VK=ROOT/'dm/gfx/vk_android'
VERT='''#version 450
layout(push_constant)uniform P{vec4 rgba;vec4 shape;}pc;
void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexIndex],pc.shape.x,1);}
'''
FRAG='''#version 450
layout(push_constant)uniform P{vec4 rgba;vec4 shape;}pc;
layout(location=0)out vec4 color;
void main(){if(pc.shape.y>0.5&&((int(gl_FragCoord.x)+int(gl_FragCoord.y))&1)==0)discard;color=pc.rgba;}
'''
class CaveQueryGPU(unittest.TestCase):
 @unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','real Vulkan ICD required')
 def test_precise_queries_and_pixels_match_split_reference(self):
  compiler=shutil.which('glslangValidator');self.assertTrue(compiler)
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);env=dict(os.environ)
   for stage,source in [('vert',VERT),('frag',FRAG)]:
    p=d/('test.'+stage);p.write_text(source);spv=str(p)+'.spv'
    subprocess.run([compiler,'-V','--target-env','vulkan1.1','-S',stage,'-o',spv,str(p)],check=True,capture_output=True)
    env['CAVE_'+stage.upper()]=spv
   exe=d/'cave'
   build=subprocess.run([shutil.which('cc'),'-O2','-DVKA_NDSR_PURE','-I',str(ROOT/'dm/third_party/vulkan-headers/include'),'-I',str(VK),str(VK/'selftest/cave_query_gpu.c'),str(VK/'vka_ndsr.c'),'-ldl','-lm','-lpthread','-o',str(exe)],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=120)
   self.assertEqual(run.returncode,0,run.stdout+run.stderr)
   self.assertNotIn('Validation Error',run.stdout+run.stderr)
   self.assertEqual(run.stdout.count('precise query counts exact'),2,run.stdout)
   print(run.stdout)
if __name__=='__main__':unittest.main()
