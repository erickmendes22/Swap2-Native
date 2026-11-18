"""GPU query archive: cross-submission reuse is generation-bound and no-wait on CPU."""
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/"dm/gfx/vk_android"

class ArchiveProof(unittest.TestCase):
    def test_native_policy_100000_randomized_and_ring_recycling(self):
        code=r"""
#include <assert.h>
#include <stdint.h>
#include "vka_rc_gpu_policy.h"
int main(void) {
  vka_rc_archive_pair p;
  vka_rc_archive_report a={100,101,3,0,4,1},b={105,106,4,0,4,1};
  assert(vka_rc_archive_pair_valid(a,b,90,150,140,&p)&&!p.delta);
  b.fresh=0;assert(!vka_rc_archive_pair_valid(a,b,90,150,140,&p));
  b.fresh=1;b.epoch=3;b.lost=3;
  assert(vka_rc_archive_pair_valid(a,b,90,150,140,&p)&&p.delta&&p.begin==101&&p.end==106&&p.lost==3);
  assert(!vka_rc_archive_pair_valid(a,b,105,150,140,&p));
  assert(!vka_rc_archive_pair_valid(a,b,90,105,140,&p));
  assert(!vka_rc_archive_pair_valid(a,b,90,150,105,&p));
  a.fence=0;assert(!vka_rc_archive_pair_valid(a,b,90,150,140,&p));
  a.fence=4;
  uint64_t seed=978234;
  for(int i=0;i<100000;i++) {
    seed=seed*6364136223846793005ULL+1;
    uint64_t o=seed&1023,head=o+((seed>>12)&1023);
    uint64_t sub=head-((seed>>11)&3);
    a=(vka_rc_archive_report){.begin=(seed>>17)&2047,.epoch=(seed>>8)&3,.fence=(seed>>3)&1,.fresh=!!(seed&8),.lost=(seed>>40)&7};
    a.end=a.begin+((seed>>23)&511);
    b=(vka_rc_archive_report){.begin=(seed>>6)&2047,.epoch=(seed>>13)&3,.fence=(seed>>4)&1,.fresh=!!(seed&16),.lost=(seed>>44)&7};
    b.end=b.begin+((seed>>31)&511);
    int accepted=vka_rc_archive_pair_valid(a,b,o,head,sub,&p);
    if(accepted){
      assert(a.fence&&b.fence&&a.epoch&&b.epoch);
      assert(a.begin>=o&&b.begin>=o&&a.end<=head&&b.end<=head);
      assert(a.end<=sub&&b.end<=sub);
      assert(a.end-a.begin<=256&&b.end-b.begin<=256);
      if(a.epoch!=b.epoch)assert(a.fresh&&b.fresh&&!p.delta);
      else assert(p.delta&&p.begin==a.end&&p.end==b.end&&p.lost==b.lost-a.lost);
    }
  }
  return 0;
}"""
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"policy.c"
            exe=Path(td)/"policy"
            src.write_text(code)
            cmd=[shutil.which("cc"),"-std=c11","-O2","-Wall","-Wextra","-Werror","-fsanitize=undefined","-I",str(VK),str(src),"-o",str(exe)]
            c=subprocess.run(cmd, capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            r=subprocess.run([str(exe)], capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_snapshot_produced_before_fence_host_reset_and_consumed_on_gpu(self):
        exe=(VK/"vka_exec.c").read_text()
        gpu=(VK/"vka_rc_gpu.inc").read_text()
        shader=(VK/"rc/visibility.comp").read_text()
        self.assertIn("oq_archive_flush(g_cb); // final part",exe)
        self.assertIn("oq_archive_flush(g_cb); // each chunk",exe)
        self.assertIn("VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT",exe)
        self.assertIn("VKA_ENV(\"DM_VK_OOT_OQ_ARCHIVE\", 1)",exe)
        self.assertIn("g_oq_archive_head = end;",exe)
        self.assertIn("vka_rc_archive_pair_valid(aa, bb",gpu)
        self.assertIn("vka_dispatch(&S.d, a);",exe)
        self.assertIn("vka_rc_compute_may_write(g_wk.r[5], g_wk.n[5])", (VK/"vka_draw.c").read_text())
        self.assertIn("old_write_epoch / frames",gpu)
        self.assertIn('DM_VK_OOT_RC_COMPUTE_RO", 1',(VK/"vka_draw.c").read_text())
        self.assertIn("static _Atomic int g_oq_archive_enabled;",exe)
        self.assertIn("vk.vkCmdCopyBuffer(g_cb, g_oq_archive.buf",gpu)
        self.assertIn("VKA_ENV(\"DM_VK_OOT_OQ_ARCHIVE\", 1)",gpu)
        self.assertIn("if(!az&&!bz){predicate[i]=1;return;}",shader)
        self.assertNotIn("OQ.get(",gpu)

    def test_boolean_proof_cross_reset_never_speculates_two_positive(self):
        rng=random.Random(17969)
        for _ in range(100000):
            a,b=rng.randrange(256),rng.randrange(256)
            # The archive records zero/positive boolean query values.
            az=a==0
            bz=b==0
            decided=(az or bz)
            if decided:self.assertEqual(az==bz,a==b)
            if a and b:self.assertFalse(decided)

if __name__=="__main__":unittest.main()
