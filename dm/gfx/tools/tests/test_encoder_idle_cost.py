"""Actual encoder command ownership/order and CPU cost with idle polling off."""
from pathlib import Path
import re,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[4];VK=ROOT/'dm/gfx/vk_android'
class EncoderIdle(unittest.TestCase):
 def test_actual_ring_cpu_and_order(self):
  s=(VK/'vka_enc.c').read_text();names=set(re.findall(r'X\((vk\w+)\)',s[s.index('#define ENC_FNS'):s.index('#define ENC_ID')]))
  shim='''#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
int test_env(const char *,int);
#define VKA_ENV(k,v) test_env(k,v)
#define VLOG(...) ((void)0)
#define VRED(...) fprintf(stderr,__VA_ARGS__)
int vka_nan_on(void);
uint64_t vka_host_fp(const char *);
void vka_enc_sync(void);
static struct {\n'''+''.join('PFN_'+n+' '+n+';\n'for n in sorted(names))+'}vk;\n'
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);(d/'encoder_test_shim.h').write_text(shim);(d/'encoder_under_test.c').write_text(s.replace('#include "vka.h"','#include "encoder_test_shim.h"',1));exe=d/'test'
   build=subprocess.run(['cc','-std=gnu11','-D_GNU_SOURCE','-D__ANDROID__','-O2','-g','-fsanitize=undefined','-I',str(d),'-I',str(ROOT/'dm/third_party/vulkan-headers/include'),str(ROOT/'dm/host/tests/t_android_encoder_idle.c'),'-lpthread','-o',str(exe)],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   for spin in (200,0,0,200,200,0):
    r=subprocess.run([str(exe),str(spin)],capture_output=True,text=True,timeout=30);self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('256000 commands exact',r.stdout);print(r.stdout,end='')
if __name__=='__main__':unittest.main()
