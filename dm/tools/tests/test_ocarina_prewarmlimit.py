"""Exercise the production, CPU-only speculative Vulkan prewarm budget.

Mock records represent pipeline compilation count, NOT real driver allocation
bytes or device PSS. A Vulkan pipeline omitted from speculative prewarm is
still compiled on demand by gfx_obtain / cs_obtain, using the saved cache.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
HDR = ROOT / "dm/gfx/vk_android/vka_prewarmlimit.h"
PSO = (ROOT / "dm/gfx/vk_android/vka_pso.c").read_text()

class OcarinaPrewarmBudget(unittest.TestCase):
    def test_production_policy_and_recent_records(self):
        src = r"""
#include <stdio.h>
#include <stdint.h>
#include "vka_prewarmlimit.h"
int main(void) {
  // Exact recorded counts: Swap 2111 keys, 2075 completed, Banana 1546.
  uint32_t small=vkpw_limit(8192u,15600412ull*1024u,1,0);
  uint32_t big=vkpw_limit(8192u,24ull<<30,1,0);
  uint32_t other=vkpw_limit(8192u,15600412ull*1024u,0,0);
  uint32_t forced=vkpw_limit(8192u,15600412ull*1024u,1,1);
  uint32_t disabled=vkpw_limit(1000u,15600412ull*1024u,1,0);
  if (small!=1536 || big!=8192 || other!=8192 ||
      forced!=8192 || disabled!=1000) return 2;
  size_t n=2111, count=0;
  for(size_t i=0;i<n && i<small;i++) {
      size_t record=vkpw_newest(n,i);
      if(record>=n || record<n-small || record!=n-1-i) return 3;
      count++;
  }
  if(count!=1536 || n-count!=575) return 4;
  // A key outside the speculative set is still valid for on-demand lookup.
  printf("speculative=%zu skipped=%zu newest=%zu oldest_kept=%zu; demand=unrestricted\\n",
         count,n-count,vkpw_newest(n,0),vkpw_newest(n,count-1));
  return 0;
}
"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'test.c').write_text(src)
            cc=shutil.which('clang') or shutil.which('cc')
            self.assertIsNotNone(cc)
            args=[cc,'-std=c11','-O1','-Wall','-Wextra','-Werror',
                  '-fsanitize=address,undefined','-I',str(HDR.parent),
                  str(p/'test.c'),'-o',str(p/'test')]
            c=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            x=subprocess.run([str(p/'test')],capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
            self.assertIn('speculative=1536 skipped=575',x.stdout)

    def test_only_prewarmer_is_capped(self):
        self.assertIn('g_pw_budget = vkpw_limit(',PSO)
        self.assertIn('uint32_t max = g_pw_budget;',PSO)
        self.assertIn('i = vkpw_newest(n, i);',PSO)
        self.assertIn('gfx_obtain(&fk, fnv(&fk, len',PSO)
        self.assertIn('cs_obtain(sh[5], &lay, &rt, 1',PSO)
        self.assertIn('vka_shader *const sh[VKA_NSTAGE], const vka_layout *lay, const vka_gkey *k, int prewarm, int *made)',PSO)
        self.assertIn('if (!prewarm && gpl_on()',PSO)
        # Every actual frame path remains free to ask gfx_obtain after prewarm.
        self.assertIn('gfx_obtain(&fk, fnv(&fk, len, 1469598103934665603ull), len, sh, lay, k, 0, &made)',PSO)

if __name__ == '__main__':
    unittest.main()
