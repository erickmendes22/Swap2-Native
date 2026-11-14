"""Actual submission-prefix dependencies and conservative preparation coverage."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from dm.gfx.tools.tests.test_depth_pass_optimizations import function
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/'dm/gfx/vk_android'

class PrepareBarrier(unittest.TestCase):
 def test_all_preparation_gpu_paths_mark_possible_work(self):
  tex=(VK/'vka_tex.c').read_text()
  f=function(tex,'int vka_tex_prepare(')
  self.assertIn('int gpu_work = !g_set;',f)
  self.assertEqual(f.count('return gpu_work;'),2)
  # New preparation helpers taking the command buffer must be classified;
  # never replace this contract with upload-byte counters (misses remaps).
  f=re.sub(r'/\*.*?\*/|//[^\n]*','',f,flags=re.S)
  calls=[]
  for m in re.finditer(r'\b(\w+)\([^()\n]*\bcb\b[^()\n]*\)',f):
   name=m.group(1)
   if name in ('vka_tex_prepare','PREP_GPU'):continue
   calls.append(name)
   self.assertTrue(f[:m.start()].endswith('PREP_GPU('),m.group(0))
  self.assertEqual(set(calls),{'upload_tracked','upload_fill','upload_rows_tracked','upload_images_tracked',
                              'sparse_refresh','sparse_bind','watch_scan','write_tex'})
  self.assertNotIn('vk.vkCmd',f)

 @unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','real Vulkan ICD required')
 def test_actual_submission_prefix_readback_and_dependency_counts(self):
  tex=(VK/'vka_tex.c').read_text();exe_source=(VK/'vka_exec.c').read_text()
  start=exe_source.index("    vka_barrier(g_cb);   // the host's writes")
  end=exe_source.index('    // Reserve a fence-released',start)
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp)
   (d/'prepare_prefix.inc').write_text(exe_source[start:end])
   (d/'full_barrier.inc').write_text(function(tex,'void vka_barrier_at('))
   exe=d/'prepare'
   build=subprocess.run([shutil.which('cc'),'-O2','-DVKA_NDSR_PURE','-I',str(d),
    '-I',str(ROOT/'dm/third_party/vulkan-headers/include'),'-I',str(VK),str(VK/'selftest/prepare_barrier_gpu.c'),
    str(VK/'vka_ndsr.c'),'-ldl','-lm','-o',str(exe)],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=60)
   self.assertEqual(run.returncode,0,run.stdout+run.stderr)
   self.assertNotIn('Validation Error',run.stdout+run.stderr)
   self.assertEqual(run.stdout.count('4096 bytes exact'),8,run.stdout)
   print(run.stdout)
if __name__=='__main__':unittest.main()
