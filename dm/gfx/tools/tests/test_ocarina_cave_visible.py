"""Execute production conservative counters, delayed publication and conditions."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]

class ConservativeCaveVisibility(unittest.TestCase):
    def test_actual_draw_reset_report_and_render_conditions(self):
        source=(ROOT/'dm/gfx/vk_android/vka_exec.c').read_text()
        conditions=source[source.index('typedef struct {\n    uint64_t addr, fence, oq_end'):source.index('// Every 300')]
        counters=source[source.index('void vka_oq_draw(void)'):source.index('// Query availability')]
        a=source.index('        if (ops[i].kind == 6) {')
        publish=source[a:source.index('        if (ops[i].kind == 4',a)]
        harness=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#define VLOG(...) ((void)0)
#define VRED_ONCE(...) ((void)0)
#define VRED(...) ((void)0)
#define VKA_ENV(k,d) (d)
typedef struct { int mode; uint64_t addr; } p_render_cond;
static uint64_t vka_done(void){return 0;}
static int vka_addr(uint64_t a,int n,void *b,void *o,void *p){(void)n;(void)b;(void)o;(void)p;return a!=0;}
uint64_t vka_frame(void){return 1;}
'''+conditions+r'''
static int oq_early_pair_equal(uint64_t a,uint64_t b,int *equal){(void)a;(void)b;(void)equal;return 0;}
typedef struct {int kind;uint32_t mode,v,type;uint64_t addr,q0,q1;} pop;
static pop pending[16000];static int npost;
static void post(pop p){if(npost==16000)abort();pending[npost++]=p;}
static int g_oq=2,g_oq_count,g_oq_fresh,g_oq_open,g_oq_split_pass,g_cb=1;
static uint32_t g_oq_lost;
static uint64_t g_oq_visible,g_oq_visible_draws,g_oq_head,g_oq_seg0;
static uint64_t g_oqs_q,g_oqs_full,g_oqs_fly,g_oqs_skip,g_oqs_reset,g_oqs_rep,g_oqs_nores;
static _Atomic uint64_t g_oq_ready,g_oq_freed;
static struct {int host;} OQ;
enum {OQ_N=32768};
static int queries,splits;
static int oq_on(void){return g_oq;}
static void oq_close(void){if(g_oq_open)abort();}
static void oq_rec(uint32_t q,int end){(void)q;(void)end;queries++;}
static int vka_rp_has_depth(void){return 1;}
static void vka_rp_end(void){splits++;}
static void vka_draw_stats(void *a,uint64_t *b,void *c,void *d){(void)a;(void)c;(void)d;*b=0;}
'''+counters+r'''
static void complete(int start,int end){
 pop *ops=pending;uint64_t ticks=0x987654321;
 for(int i=start;i<end;i++){
'''+publish+r'''
 abort();
 }
}
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);abort();}}while(0)
int main(void){
 uint64_t before[4]={0xdead,0xbeef,0xdead,0xbeef},after[4]={0xdead,0xbeef,0xdead,0xbeef};
 uint64_t ad=(uint64_t)(uintptr_t)before,bd=(uint64_t)(uintptr_t)after;
 oq_reset();CHECK(oq_report(ad,7)==2);rc_note(ad,2);
 for(int i=0;i<3;i++)vka_oq_draw();
 CHECK(oq_report(ad+16,7)==2);rc_note(ad+16,2);
 CHECK(before[0]==0xdead&&before[2]==0xdead); // recording must not publish
 complete(0,2);CHECK(before[0]==0&&before[2]==3&&before[1]==0x987654321);
 for(int i=0;i<2;i++)vka_oq_draw();
 CHECK(oq_report(bd,7)==2);rc_note(bd,2);
 g_oq_lost=2;CHECK(oq_report(bd+16,7)==2);rc_note(bd+16,2);
 complete(2,4);CHECK(after[0]==5&&after[2]==7); // cumulative, not constant 1
 int old=npost;oq_reset();CHECK(oq_report(bd,7)==2);
 vka_oq_draw();CHECK(oq_report(bd+16,7)==2);
 CHECK(after[0]==5&&after[2]==7);complete(old,npost);CHECK(after[0]==0&&after[2]==1);
 // Even equal completed proxy counts must not cull geometry: these are
 // conservative reports, not real pixel measurements. Exercise both modes,
 // explicit disable and unrelated timestamp-only memory comparisons.
 before[0]=before[2]=0;
 p_render_cond cond={1,ad};CHECK(!rc_eval(&cond));cond.mode=0;CHECK(!rc_eval(&cond));
 cond.mode=3;CHECK(rc_eval(&cond));cond.mode=2;CHECK(!rc_eval(&cond));
 uint64_t timestamp_pair[4]={0,10,0,20};cond=(p_render_cond){1,(uint64_t)(uintptr_t)timestamp_pair};
 CHECK(rc_eval(&cond));timestamp_pair[2]=9;CHECK(!rc_eval(&cond));
 // Reusing an occlusion-report address for a timestamp must restore exact
 // timestamp conditional-clear semantics, including the in-flight zero.
 rc_note(ad,1);rc_note(ad+16,1);cond=(p_render_cond){1,ad};CHECK(rc_eval(&cond));
 // Exercise removal through colliding probe chains and growth, not just the
 // no-collision addresses of the render-condition fixture.
 for(uint64_t i=1;i<=5000;i++)rc_occ_add(0x10000000+i*65536);
 for(uint64_t i=2;i<=5000;i+=2)rc_occ_remove(0x10000000+i*65536);
 for(uint64_t i=1;i<=5000;i++)CHECK(rc_occ_has(0x10000000+i*65536)==(int)(i%2));
 // The 1800-query scene must issue no query calls or split calls at all.
 for(int i=0;i<1800;i++){oq_reset();CHECK(oq_report(ad,7)==2);vka_oq_draw();CHECK(oq_report(ad+16,7)==2);}
 CHECK(queries==0&&splits==0&&g_oq_head==0&&g_oq_visible_draws==1806);
 free(g_rc_occ);free(g_rcp);
 puts("production: snapshots 0/3/5/7, reset 0/1, delayed publication, conservative visibility, timestamps and explicit disable; 1800 query pairs -> zero query calls and zero split calls");
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'visible.c';exe=Path(tmp)/'visible';src.write_text(harness)
            result=subprocess.run([shutil.which('cc'),'-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined',str(src),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('zero query calls and zero split calls',result.stdout)

if __name__=='__main__':unittest.main()
