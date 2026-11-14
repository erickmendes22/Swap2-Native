"""Compare projected task/mesh snapshots through real walker/driver bank code."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from dm.gfx.tools.tests.test_banana_input_caches import function
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/'dm/gfx/vk_android'

class SnapshotRows(unittest.TestCase):
 def test_real_state_and_descriptor_equivalence(self):
  h=(VK/'vka.h').read_text();ds=h[h.index('typedef struct {\n    vka_bstate b;'):h.index('} vka_dstate;')+len('} vka_dstate;')]
  inc=(VK/'vka_memu_draw.inc').read_text()
  self.assertIn('memu_snapshot_capture(&g_memu_draw_snapshot[ei], d);',inc)
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);(d/'snapshot_under_test.h').write_text(ds+'\n'+function(inc,'static void memu_snapshot_capture('))
   exe=d/'snapshot'
   build=subprocess.run(['cc','-O2','-g','-fsanitize=undefined','-I',str(d),'-I',str(VK),'-I',str(ROOT/'dm/gfx/nvn'),'-I',str(ROOT/'dm/gfx/nvn/include'),'-I',str(ROOT/'dm/third_party/vulkan-headers/include'),str(ROOT/'dm/host/tests/t_memu_snapshot_rows.c'),str(VK/'vka_bind.c'),'-o',str(exe)],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=60)
   self.assertEqual(run.returncode,0,run.stdout+run.stderr)
   self.assertNotIn('runtime error:',run.stderr)
   print(run.stdout)
if __name__=='__main__':unittest.main()
