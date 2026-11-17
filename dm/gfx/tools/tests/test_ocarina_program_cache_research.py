"""Ocarina Vulkan program serial cache A/B and original resolve parity."""
import unittest
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
SRC=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
class ProgramCacheResearch(unittest.TestCase):
    def test_512_default_only_for_ocarina_and_64_rollback(self):
        self.assertIn("static unsigned g_pm_mask = 63;",SRC)
        self.assertIn('g_pm_mask = VKA_ENV("DM_VK_PROG_CACHE_512",',SRC)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")) ? 511u : 63u;',SRC)
        self.assertIn("g_pm[512];",SRC)
    def test_exact_serial_and_fallback(self):
        f=SRC.split("static int resolve(const prog_t *p,",1)[1].split(
            "// A predicated block",1)[0]
        self.assertIn("if (sr && m->serial == sr)",f)
        self.assertIn("if (!vka_prog_shaders(p, &ps)) return 0;",f)
        self.assertIn("if (sr) { m->serial = sr; m->ps = ps; }",f)
        self.assertIn("ps.bad & (1u << st | VKA_BAD_MISSING)",f)
        self.assertIn("ps.sh[st]",f)
        self.assertNotIn("getenv(",f)
        self.assertIn("g_pm_shadow64[(sr ^ (sr >> 6)) & 63u]",f)
    def test_shadow_64_and_real_512_independent(self):
        self.assertIn("g_pm_shadow_misses",SRC)
        self.assertIn("shadow old 64 slots",SRC)
        self.assertIn('g_pm_diag = VKA_ENV("DM_VK_PROG_CACHE_DIAG",',SRC)
        self.assertIn("g_pm_mask + 1u",SRC)
    def test_actual_compiled_resolver_matches_all_shaders(self):
        a=SRC.index("static int resolve(const prog_t *p,")
        b=SRC.index("// A predicated block",a)
        resolver=SRC[a:b]
        harness=r'''
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
enum { VKA_NSTAGE=8, VKA_BAD_MISSING=1u<<12 };
typedef struct { uint64_t key; } vka_shader;
typedef struct { uint64_t serial; vka_shader *sh[8]; unsigned bad; } prog_t;
typedef struct { vka_shader *sh[8]; unsigned bad; } vka_progsh;
static int expensive_calls;
static int vka_prog_shaders(const prog_t *p,vka_progsh *r){
 ++expensive_calls; memcpy(r->sh,p->sh,sizeof r->sh);r->bad=p->bad;return 1;
}
static unsigned g_pm_mask=63;
static int g_pm_diag=1;
static uint64_t g_pm_hits,g_pm_misses,g_pm_shadow_hits,g_pm_shadow_misses;
static uint64_t g_pm_shadow64[64];
static struct { uint64_t serial; vka_progsh ps; } g_pm[512];
''' + resolver + r'''
int main(void){
  prog_t p[128]={0};vka_shader sh[128]={0};
  for(int i=0;i<128;i++){p[i].serial=(uint64_t)i*64u+1u;sh[i].key=i+1;p[i].sh[1]=&sh[i];}
  int calls64=0,calls512=0;
  for(int mode=0;mode<2;mode++){
    memset(g_pm,0,sizeof g_pm);g_pm_mask=mode?511:63;
    expensive_calls=0;
    for(int repeat=0;repeat<6;repeat++)
      for(int i=0;i<128;i++){
        vka_shader *out=0;unsigned bad=0;
        assert(resolve(&p[i],1,&out,&bad)&&out==&sh[i]&&!bad);
      }
    if(mode)calls512=expensive_calls;else calls64=expensive_calls;
  }
  assert(calls512<calls64);
  printf("original 64: %d resolution calls; 512: %d, exactly same shader pointers\\n",calls64,calls512);
  // Missing-program and zero-serial paths must still use the old fallback.
  prog_t missing={0};missing.serial=0;missing.bad=(1u<<1);
  vka_shader *out=(vka_shader*)1;unsigned bad=0;
  assert(resolve(&missing,1,&out,&bad)&&!out&&(bad&(1u<<1)));
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"serial.c";exe=Path(td)/"serial"
            src.write_text(harness)
            p=subprocess.run(["cc","-std=gnu11","-O2","-Wall","-Wextra",
              "-fsanitize=undefined","-fno-omit-frame-pointer",str(src),
              "-o",str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            c=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr+c.stdout)
            self.assertIn("exactly same shader pointers",c.stdout)
if __name__=="__main__":
    unittest.main()
