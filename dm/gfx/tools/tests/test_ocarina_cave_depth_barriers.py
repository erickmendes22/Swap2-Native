"""Compile production guest-barrier policy; preserve explicit depth-cache boundaries."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]

class CaveDepthBarriers(unittest.TestCase):
    def test_actual_barrier_policy_all_bits_and_attachment_states(self):
        text=(ROOT/'dm/gfx/vk_android/vka_draw.c').read_text()
        a=text.index('int vka_rp_game_barrier(uint32_t bits) {')
        fn=text[a:text.index('\nvoid vka_rp_bar_stats',a)]
        prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "nvn.h"
static struct {int on,swrite,df,sf,dwrite,bar_pending;} R;
static uint64_t g_bar_in,g_bar_kept,g_cave_depth_boundaries;
static int enabled,keep;
#define VKA_ENV(k,d) (keep)
static int cave_depth_boundary_on(void){return enabled;}
'''
        main=r'''
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(void){
 for(enabled=0;enabled<=1;enabled++)for(keep=0;keep<=1;keep++)
 for(int on=0;on<2;on++)for(int writer=0;writer<2;writer++)
 for(int depth=0;depth<2;depth++)for(int stencil=0;stencil<2;stencil++)
 for(int dirty=0;dirty<2;dirty++)for(unsigned bits=0;bits<256;bits++){
  R=(typeof(R)){.on=on,.swrite=writer,.df=depth,.sf=stencil,.dwrite=dirty};
  uint64_t n=g_cave_depth_boundaries,k=g_bar_kept;
  int boundary=on&&!writer&&keep&&enabled&&(depth||stencil)&&
       ((bits&NVN_BARRIER_INVALIDATE_ZCULL_BIT)||(dirty&&(bits&7)));
  int expected=on&&!writer&&keep&&!boundary;
  CHECK(vka_rp_game_barrier(bits)==expected);
  CHECK(g_cave_depth_boundaries-n==(uint64_t)boundary);
  CHECK(g_bar_kept-k==(uint64_t)expected);
  CHECK(R.bar_pending==expected);
 }
 // Thousands of read-only report boundaries must not become pass boundaries.
 // Guest depth-order requests do split once after a writer; the reopened pass
 // starts clean. No camera/location heuristic or per-query flush is involved.
 enabled=keep=1;uint64_t start=g_cave_depth_boundaries;
 R=(typeof(R)){.on=1,.df=1,.dwrite=1};
 CHECK(!vka_rp_game_barrier(NVN_BARRIER_ORDER_FRAGMENTS_BIT));
 R=(typeof(R)){.on=1,.df=1};
 for(int i=0;i<1800;i++)CHECK(vka_rp_game_barrier(NVN_BARRIER_ORDER_FRAGMENTS_BIT));
 CHECK(g_cave_depth_boundaries-start==1);
 CHECK(!vka_rp_game_barrier(NVN_BARRIER_INVALIDATE_ZCULL_BIT)); // explicit cache request even without a writer
 puts("32768 production policy cases and 1800 read-only boundaries passed");return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'barrier.c';exe=Path(tmp)/'barrier';src.write_text(prefix+fn+main)
            result=subprocess.run([shutil.which('cc'),'-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-I',str(ROOT/'dm/gfx/nvn/include'),str(src),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('1800 read-only boundaries passed',result.stdout)
        # The dirty flag includes load-op, queued/inline clears and draw writes;
        # a new pass resets the whole state. Guest barriers retain full ordering.
        self.assertIn('memset(&R, 0, sizeof R)',text)
        self.assertIn('if (late[i]->ci < 0) R.dwrite = 1',text)
        self.assertIn('if (ci < 0) R.dwrite = 1',text)
        self.assertIn('R.awrite = R.dwrite = 1',text)
        self.assertIn('sp->loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR)) R.dwrite = 1',text)
        replay=(ROOT/'dm/gfx/vk_android/vka_exec.c').read_text()
        self.assertIn('if (!bar_kept) bar_covered = vka_rp_end_covers_barrier()',replay)
        self.assertIn('g_rp_force_full = 1;',text)

if __name__=='__main__':unittest.main()
