"""Compare actual full-guest dependency absorption against explicit publication."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from dm.gfx.tools.tests import test_selective_transfer_compute_gpu as sync
from dm.gfx.tools.tests.test_depth_pass_optimizations import function
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/'dm/gfx/vk_android'

class GuestBoundaryContract(unittest.TestCase):
 def test_kept_barriers_never_acknowledge_pending_writes(self):
  draw=(VK/'vka_draw.c').read_text();ex=(VK/'vka_exec.c').read_text()
  helpers='\n'.join(function(draw,n)for n in ['void vka_dispatch_overlap_flush(', 'int vka_dispatch_guest_can_cover(', 'void vka_dispatch_guest_covered('])
  start=ex.index('        case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered)')
  handler=ex[start:ex.index('        case OP_DRAW:',start)]
  code=r'''#include <assert.h>
#include <stdint.h>
#include <string.h>
static int g_cb,g_dispatch_overlap_pending,g_dispatch_guest_merged;
static int rp,profile,nan_scan,opt,dedup,full,flush;
#define vka_gp_active profile
#define VKA_ENV(n,d) (n[6]=='A'?opt:dedup)
static int vka_rp_is_open(void){return rp;}
static int vka_nan_on(void){return nan_scan;}
static void vka_compute_write_barrier(int cb){assert(cb);flush++;}
static void vka_barrier(int cb){assert(cb);full++;}
static int narrow,deferred;
static int vka_gbar_game(int cb,uint32_t bits){assert(cb);(void)bits;if(narrow)deferred++;return narrow;}
''' + helpers + r'''
#define OP_BARRIER 1
static void boundary(int bar_kept,int bar_covered){int32_t bits=0;const void*a=&bits;switch(OP_BARRIER){
''' + handler + r'''}}
int main(void){
 for(rp=0;rp<2;rp++)for(profile=0;profile<2;profile++)
 for(nan_scan=0;nan_scan<2;nan_scan++)for(opt=0;opt<2;opt++)
 for(dedup=0;dedup<2;dedup++)for(g_cb=0;g_cb<2;g_cb++){
  g_dispatch_overlap_pending=1;
  assert(vka_dispatch_guest_can_cover()==(!rp&&!profile&&!nan_scan&&dedup&&g_cb));
  assert(g_dispatch_overlap_pending); // Checking eligibility cannot drop writes.
 }
 g_cb=1;full=flush=g_dispatch_guest_merged=0;
 g_dispatch_overlap_pending=1;boundary(1,0);
 assert(flush==1&&full==0&&g_dispatch_guest_merged==0&&!g_dispatch_overlap_pending);
 g_dispatch_overlap_pending=1;boundary(0,0);
 assert(full==1&&g_dispatch_guest_merged==1&&!g_dispatch_overlap_pending);
 // A preceding pass end already recorded the required full barrier.
 g_dispatch_overlap_pending=1;boundary(0,1);
 assert(full==1&&g_dispatch_guest_merged==2&&!g_dispatch_overlap_pending);
 narrow=1;g_dispatch_overlap_pending=1;boundary(0,0);
 assert(full==1&&deferred==1&&g_dispatch_guest_merged==3&&!g_dispatch_overlap_pending);
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'test.c').write_text(code)
   build=subprocess.run([shutil.which('cc'),'-std=c11','-Wall','-Werror',str(p/'test.c'),'-o',str(p/'test')],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   subprocess.run([str(p/'test')],check=True)

@unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','real Vulkan ICD required')
class ComputeGuestGPU(unittest.TestCase):
 def test_real_production_dependency_and_byte_exact_chained_consumers(self):
  tex=(VK/'vka_tex.c').read_text();draw=(VK/'vka_draw.c').read_text();ex=(VK/'vka_exec.c').read_text()
  barriers='\n'.join(function(tex,'void '+n+'(')for n in ['vka_barrier_at','vka_transfer_write_barrier_at','vka_compute_write_barrier_at'])
  policies=function(ex,'static void boost_transfer_barrier(')+'\n'+function(draw,'static void dispatch_write_barrier(')+'\n'+function(draw,'static void dispatch_argument_barrier(')
  helpers='\n'.join(function(draw,n)for n in ['void vka_dispatch_overlap_flush(', 'int vka_dispatch_guest_can_cover(', 'void vka_dispatch_guest_covered('])
  start=ex.index('        if (h.op != OP_DISPATCH && !overlap_state_record(h.op)) {')
  prefix=ex[start:ex.index('        const void *a =',start)]
  start=ex.index('        case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered)')
  handler=ex[start:ex.index('        case OP_DRAW:',start)]
  runner=sync.SelectiveSyncGPU()
  runner.run_fixture('compute_guest_gpu',{'sync_barriers.inc':barriers,'sync_policies.inc':policies,'guest_helpers.inc':helpers,'guest_prefix.inc':prefix,'guest_handler.inc':handler},{'4096 bytes exact':256},sync.COMP)

if __name__=='__main__':unittest.main()
