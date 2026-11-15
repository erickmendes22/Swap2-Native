"""Actual default selection plus physical reclaimability, not an APK/RAM claim."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
def function(s,sig):
 a=s.index(sig);b=s.index('{',a);i=b+1;d=1
 while d:d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
class ShaderFilebackDefault(unittest.TestCase):
 def test_launcher_policies_match_banana_ram_saver_ab(self):
  activity=(ROOT/'android/app/src/main/java/dev/nxnative/android/GameActivity.java').read_text()
  settings=(ROOT/'android/app/src/main/java/dev/nxnative/android/GameSettings.java').read_text()
  prefs=(ROOT/'android/app/src/main/java/dev/nxnative/android/Prefs.java').read_text()
  # With RAM Saver OFF, shader code is file-backed; ON adds large textures.
  self.assertIn('env.add("DM_MEM_FILEBACK=1");',activity)
  self.assertIn('(Prefs.ramSaver(this, id) ? "shader,texture" : "shader")',activity)
  # No stale Build 174 preference may force Vulkan shader-pool placement.
  self.assertIn('env.add("DM_VK_PLACE_SHADER_POOLS=0");',activity)
  self.assertNotIn('Prefs.shaderPoolMemory(',activity)
  self.assertNotIn('Prefs.shaderPoolMemory(',settings)
  self.assertNotIn('static boolean shaderPoolMemory(',prefs)
  # User's explicitly supplied per-game env stays applied last for debugging.
  self.assertLess(activity.index('env.add("DM_VK_PLACE_SHADER_POOLS=0")'),
                  activity.index('env.addAll(user);'))
  # App-private backing directory is passed even without RAM Saver.
  self.assertIn('"TMPDIR=" + getCacheDir()',activity)

 def test_default_is_only_shader_and_explicit_settings_remain_respected(self):
  source=(ROOT/'dm/gfx/vk_android/vka_mem.c').read_text()
  code='''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define VLOG(...) ((void)0)
#define VRED(...) ((void)0)
static int nvn_shader_pools_deferred(void){const char*p=getenv("TEST_SHADER_DEFERRED");return !p||atoi(p);}
'''+function(source,'static int fb_kinds(')+'\nint main(void){printf("%d\\n",fb_kinds());return 0;}\n'
  with tempfile.TemporaryDirectory() as td:
   d=Path(td);(d/'t.c').write_text(code)
   subprocess.run([shutil.which('cc'),'-std=c11','-O2',str(d/'t.c'),'-o',str(d/'t')],check=True)
   cases=[({},1),({'DM_MEM_FILEBACK':'0'},0),({'DM_MEM_FILEBACK':'1','DM_MEM_FILEBACK_KINDS':'shader,texture'},3),({'DM_MEM_FILEBACK':'1','DM_MEM_FILEBACK_KINDS':'texture'},2),({'TEST_SHADER_DEFERRED':'0'},0),({'TEST_SHADER_DEFERRED':'0','DM_MEM_FILEBACK':'1','DM_MEM_FILEBACK_KINDS':'shader,texture'},2)]
   for settings,want in cases:
    env={k:v for k,v in os.environ.items()if k not in ('DM_MEM_FILEBACK','DM_MEM_FILEBACK_KINDS','TEST_SHADER_DEFERRED')};env.update(settings)
    r=subprocess.run([str(d/'t')],env=env,text=True,capture_output=True,check=True);self.assertEqual(int(r.stdout),want,settings)
 @unittest.skipUnless(Path('/proc/self/smaps_rollup').exists(),'Linux physical accounting required')
 def test_real_cpu_backing_can_be_reclaimed_and_refaults_identical_bytes(self):
  with tempfile.TemporaryDirectory() as td:
   d=Path(td)
   r=subprocess.run([shutil.which('cc'),'-std=gnu11','-O2','-I',str(ROOT/'dm/gfx/vk_android'),str(ROOT/'dm/host/tests/t_android_shader_fileback_memory.c'),'-o',str(d/'t')],text=True,capture_output=True)
   self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(d/'t'),str(d)],text=True,capture_output=True,timeout=60)
   self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('data exact',r.stdout);print(r.stdout)
if __name__=='__main__':unittest.main()
