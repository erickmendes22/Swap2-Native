"""Ocarina conservative compute read-only visibility retention."""
from pathlib import Path
import subprocess
import tempfile
import shutil
import unittest
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/"dm/gfx/vk_android"
class ComputeWriteScope(unittest.TestCase):
    def test_compiled_binding_matrix(self):
        code=r"""
#include <assert.h>
#include "vka_rc_write_scope.h"
int main(void) {
 vka_res r[2]={{0}};
 assert(!vka_rc_compute_may_write(r,0));
 assert(vka_rc_compute_may_write(0,-1));
 assert(vka_rc_compute_may_write(0,1));
 r[0].what=VKA_R_TEX;
 assert(!vka_rc_compute_may_write(r,1));
 r[1].what=VKA_R_BUF;
 assert(!vka_rc_compute_may_write(r,2));
 r[1].flags=DMSH_VK_BF_RW;
 assert(vka_rc_compute_may_write(r,2));
 r[1].flags=DMSH_VK_BF_ATOMIC;
 assert(vka_rc_compute_may_write(r,2));
 r[1].flags=DMSH_VK_BF_NOSLOT;
 assert(vka_rc_compute_may_write(r,2));
 r[1].flags=0;
 r[1].what=VKA_R_IMG;
 assert(vka_rc_compute_may_write(r,2));
 r[1].what=VKA_R_GMEM_LOG;
 assert(vka_rc_compute_may_write(r,2));
 r[1].what=255;
 assert(vka_rc_compute_may_write(r,2));
 r[1].what=VKA_R_GMEM_MAP;
 assert(!vka_rc_compute_may_write(r,2));
 r[1].what=VKA_R_SHARED_SPILL;
 assert(!vka_rc_compute_may_write(r,2));
 return 0;
}"""
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"scope.c"; executable=Path(td)/"scope"
            source.write_text(code)
            c=subprocess.run([shutil.which("cc"), "-std=c11","-O2","-Wall","-Wextra","-Werror",
                "-fsanitize=undefined","-I",str(VK),str(source),"-o",str(executable)],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            x=subprocess.run([str(executable)],capture_output=True,text=True)
            self.assertEqual(x.returncode,0,x.stdout+x.stderr)
    def test_dispatch_invalidates_only_after_binding_walk(self):
        source=(VK/"vka_exec.c").read_text()
        draw=(VK/"vka_draw.c").read_text()
        block=draw.split("void vka_dispatch(vka_dstate *d, const p_dispatch *dp) {",1)[1]
        self.assertIn("vka_rc_compute_may_write(g_wk.r[5], g_wk.n[5])",block)
        self.assertLess(block.index("walk_all(d, sh);"),block.index("vka_rc_compute_may_write(g_wk.r[5], g_wk.n[5])"))
        self.assertLess(block.index("vka_rc_compute_may_write(g_wk.r[5], g_wk.n[5])"),block.index("oot_sgsr_chain_frame();"))
        self.assertIn('DM_VK_OOT_RC_COMPUTE_RO", 1',block)
        self.assertIn("vka_dispatch(&S.d, a);",source)
        self.assertNotIn("vka_rc_gpu_invalidate();\n            vka_dispatch(&S.d, dp);",source)
if __name__=="__main__":unittest.main()
