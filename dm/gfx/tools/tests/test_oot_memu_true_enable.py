"""Only unconditional RenderEnable(TRUE) may be traversed by mesh scan.

No guest visibility tests, DISABLE, barriers, copies, render-target changes,
or query-report side effects may be moved. Test actual C helper and inspect
the original replay and mesh-scan code paths for identical admission.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/"dm/gfx/vk_android"
EXEC=(VK/"vka_exec.c").read_text()

class TrueEnableScan(unittest.TestCase):
    def test_same_predicate_applied_to_scan_and_replay(self):
        self.assertIn('#include "vka_memu_true_cond.h"', EXEC)
        fn=EXEC.split('static int memu_allowed_record(',1)[1].split('// One walk from record',1)[0]
        self.assertIn('bytes < 8u + sizeof(p_render_cond)',fn)
        self.assertIn('vka_memu_true_cond_allowed(',fn)
        self.assertIn('VKA_ENV("DM_VK_OOT_MEMU_TRUE_ENABLE", 1)',fn)
        self.assertIn('memu_allowed(op)',fn)
        self.assertIn('if (h.size < 8 || !memu_allowed_record(h.op, a, h.size))',EXEC)
        self.assertIn('if (g_memu_cover && !memu_allowed_record(h.op, a, h.size))',EXEC)
        self.assertEqual(EXEC.count('g_memu_constant_enable_crossed;'),1)
    def test_dynamic_query_modes_remain_hard_boundaries(self):
        body=EXEC.split('static int memu_allowed(uint32_t op)',1)[1].split('// An unconditional ENABLE',1)[0]
        self.assertNotIn('case OP_RENDER_COND:',body)
        self.assertIn('case OP_BARRIER:',EXEC)
        self.assertIn('case OP_SET_RT:',EXEC)
        self.assertIn('case OP_DISPATCH:',EXEC)
        self.assertIn('case OP_UPDATE_UB:',EXEC)
        self.assertIn('case OP_RENDER_COND: S.rc_skip = rc_eval(a); rc_gpu_bind(p); break;',EXEC)
        self.assertIn('render conditions per frame:',EXEC)
    def test_real_c_policy_modes_and_opt_out(self):
        code=r"""
#include <assert.h>
#include "vka_memu_true_cond.h"
int main(void) {
  for(int game=0;game<2;game++)for(int enabled=0;enabled<2;enabled++)
  for(unsigned mode=0;mode<8;mode++){
    int expected=game && enabled && mode==2u;
    assert(vka_memu_true_cond_allowed(game,enabled,mode)==expected);
  }
  assert(!vka_memu_true_cond_allowed(1,1,0));
  assert(!vka_memu_true_cond_allowed(1,1,1));
  assert(vka_memu_true_cond_allowed(1,1,2));
  assert(!vka_memu_true_cond_allowed(1,1,3));
  return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"test.c"; bin=Path(td)/"test"
            src.write_text(code)
            p=subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",
              "-fsanitize=undefined","-I",str(VK),str(src),"-o",str(bin)],
              text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr)
            r=subprocess.run([str(bin)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
if __name__=="__main__":
    unittest.main()
