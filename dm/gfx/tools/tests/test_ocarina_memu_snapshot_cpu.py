"""Validate actual Ocarina mesh snapshot dispatcher against the original
three guest-list walks, including nested OP_END and repeated mesh records.

The measured CPU time is a synthetic indicator, not device FPS.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
EXEC=(ROOT/"dm/gfx/vk_android/vka_exec.c").read_text()
DRAW=(ROOT/"dm/gfx/vk_android/vka_memu_draw.inc").read_text()

def extract(source,name):
    m=re.search(r'\b'+re.escape(name)+r'\s*\([^;]*?\)\s*\{',source,re.S)
    if not m: raise AssertionError(name)
    depth=1
    for i in range(m.end(),len(source)):
        depth += (source[i]=='{') - (source[i]=='}')
        if depth==0:return source[m.start():i+1]
    raise AssertionError("unterminated "+name)

class MeshSnapshots(unittest.TestCase):
    def test_order_and_original_fallback(self):
        self.assertIn("if (vka_memu_snapshot_on()) vka_memu_batch_snapshot(MEMU_TASK);", EXEC)
        self.assertIn("else memu_walk(p, MEMU_TASK);",EXEC)
        self.assertIn("if (vka_memu_snapshot_on()) vka_memu_batch_snapshot(MEMU_MESH);", EXEC)
        self.assertIn("else memu_walk(p, MEMU_MESH);",EXEC)
        self.assertIn("if (vka_memu_snapshot_on()) g_memu_draw_snapshot[ei] = *d;",DRAW)
        self.assertLess(DRAW.index("g_memu_draw_snapshot[ei] = *d;"),DRAW.index("E->ok = 1;"))
        self.assertIn('VKA_ENV("DM_VK_MEMU_SNAPSHOT", 1)',DRAW)
        self.assertIn('vka_memu_batch(MEMU_DIST, NULL, NULL, NULL, 0);',EXEC)

    def test_compiled_production_walk_and_snapshot_identical(self):
        cc=shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(cc)
        walk=extract(EXEC,"memu_walk")
        snap=extract(DRAW,"vka_memu_batch_snapshot")
        c=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>
#define DM_GAME_ID "0400486024DEC000"
#define VKA_ENV(a,b) (b)
#define NVN_PRIM_MESH 5
enum { OP_END=0, OP_CALL=1, OP_JUMP=2, OP_DRAW=3, OP_BIND_PROGRAM=4,
       OP_SET_RT=5,OP_DRAW_IDX=6,OP_RENDER_COND=7,OP_COUNT_=8 };
enum { MEMU_BEGIN,MEMU_ADD,MEMU_SETUP,MEMU_TASK,MEMU_DIST,MEMU_MESH,MEMU_END };
enum { VKA_MEMU_R_TASK_X=11,VKA_MEMU_R_MESH_X=12 };
typedef struct { uint32_t op,size; } op_hdr;
typedef struct { uint32_t op,size; uint64_t arg; } record;
typedef struct { int prim,mdi_cnt; } p_draw;
typedef struct { int state; } vka_dstate;
typedef struct { uint64_t key; } vka_shader;
typedef struct { int dummy; } vka_layout;
typedef struct { int ok; vka_shader *ts,*ms,*tcs,*mcs; vka_layout tl,ml; int tp,mp; } memu_ent;
static struct { int n; } V_unused;
static struct { int memu,mesh,task; } V={1,0,0};
static struct { vka_dstate d; int rc_skip; } S;
static vka_dstate g_memu_st,g_memu_draw_snapshot[128];
static memu_ent ent[128];
static struct { int live; struct {int n;} o; memu_ent *e; } MB={1,{0},ent};
static _Thread_local const uint8_t *g_memu_caller[16];
static _Thread_local int g_memu_depth;
static uint64_t g_memu_parent_resumes,g_memu_nested_batches,g_memu_boundary_op[OP_COUNT_+1];
static vka_shader shaders[4]={{99},{100},{101},{102}};
static struct {int stage,idx,state;uint64_t key;} calls[512];
static int ncalls;
static int vka_memu_snapshot_on(void){return 1;}
static int memu_allowed(uint32_t op){return op!=OP_SET_RT;}
static const p_draw *draw_rec(const void *a,uint32_t size,p_draw *temp) {
 (void)size;(void)temp;return (const p_draw*)a;
}
static int vka_mesh_route(const vka_dstate *s){(void)s;return 1;}
static int vka_vegetation_mesh_omit(const vka_dstate *s){(void)s;return 0;}
static int vka_state_op(vka_dstate *s,uint32_t op,const void*a){
 if(op==OP_BIND_PROGRAM){int state;memcpy(&state,a,4);s->state=state;}return 1;
}
static void memu_dispatch(const vka_dstate*d,int st,vka_shader*shader,
 const vka_layout*lay,int p,int idx,int arg,uint64_t key){
 (void)shader;(void)lay;(void)p;(void)arg;
 assert(ncalls<512);
 calls[ncalls++]=(typeof(calls[0])){st,idx,d->state,key};
}
static void vka_memu_batch(int phase,const vka_dstate*d,const p_draw*dw,const uint8_t*p,int idx){
 (void)dw;(void)p;
 assert(idx>=0 && idx<128);
 if(phase==MEMU_ADD){
   if(MB.o.n<idx+1)MB.o.n=idx+1;
   ent[idx]=(memu_ent){.ok=1,.ts=(idx&1)?&shaders[0]:0,
        .ms=&shaders[1],.tcs=(idx&1)?&shaders[2]:0,.mcs=&shaders[3]};
   g_memu_draw_snapshot[idx]=*d;
 }else if(phase==MEMU_TASK) {
   if(ent[idx].tcs)memu_dispatch(d,6,ent[idx].tcs,&ent[idx].tl,ent[idx].tp,idx,
                                  VKA_MEMU_R_TASK_X,ent[idx].ts?ent[idx].ts->key:0);
 }else if(phase==MEMU_MESH)
   memu_dispatch(d,7,ent[idx].mcs,&ent[idx].ml,ent[idx].mp,idx,
                 VKA_MEMU_R_MESH_X,ent[idx].ms?ent[idx].ms->key:0);
}
''' + 'static int ' + walk + '\nvoid ' + snap + r'''
int main(void){
 // Each state-changing record must be replayed in the original meeting order.
 record child[]={{OP_DRAW,16,5},{OP_BIND_PROGRAM,16,7},
                 {OP_DRAW,16,5},{OP_END,16,0}};
 record parent[]={{OP_BIND_PROGRAM,16,9},{OP_DRAW,16,5},
                  {OP_BIND_PROGRAM,16,11},{OP_DRAW,16,5},{OP_END,16,0}};
 g_memu_caller[0]=(const uint8_t*)parent;
 g_memu_depth=1;
 S.d.state=5;
 assert(memu_walk((const uint8_t*)child,MEMU_ADD)==4);
 assert(MB.o.n==4);
 assert(g_memu_parent_resumes==1);
 ncalls=0;
 memu_walk((const uint8_t*)child,MEMU_TASK);
 memu_walk((const uint8_t*)child,MEMU_MESH);
 int original_n=ncalls;
 typeof(calls[0]) original[512];
 memcpy(original,calls,sizeof calls);
 ncalls=0;
 vka_memu_batch_snapshot(MEMU_TASK);
 vka_memu_batch_snapshot(MEMU_MESH);
 assert(original_n==ncalls);
 for(int i=0;i<ncalls;i++){
   assert(memcmp(&original[i],&calls[i],sizeof calls[i])==0);
 }
 // Number of guest-list traversals in the baseline vs snapshot pipeline.
 // This synthetic input has two parent returns and several state transitions.
 int iterations=30000, n=0;
 struct timespec a,b;
 clock_gettime(CLOCK_MONOTONIC,&a);
 for(int i=0;i<iterations;i++) {
    S.d.state=5; n+=memu_walk((const uint8_t*)child,-1);
    n+=memu_walk((const uint8_t*)child,MEMU_TASK);
    n+=memu_walk((const uint8_t*)child,MEMU_MESH);
    ncalls=0;
 }
 clock_gettime(CLOCK_MONOTONIC,&b);
 double oldms=(b.tv_sec-a.tv_sec)*1000.0+(b.tv_nsec-a.tv_nsec)/1e6;
 clock_gettime(CLOCK_MONOTONIC,&a);
 for(int i=0;i<iterations;i++) {
    S.d.state=5;n+=memu_walk((const uint8_t*)child,-1);
    ncalls=0;
    vka_memu_batch_snapshot(MEMU_TASK);
    vka_memu_batch_snapshot(MEMU_MESH);
 }
 clock_gettime(CLOCK_MONOTONIC,&b);
 double newms=(b.tv_sec-a.tv_sec)*1000.0+(b.tv_nsec-a.tv_nsec)/1e6;
 printf("mesh snapshot synthetic guest traversal %d batches: original %.3f ms, snapshot %.3f ms (n=%d); identical ordered GPU dispatch data\n",
    iterations,oldms,newms,n);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"t.c";exe=Path(tmp)/"t"
            p.write_text(c)
            build=subprocess.run([cc,"-D_GNU_SOURCE","-std=gnu11","-O2","-Wall","-Wextra",
               "-Wno-unused-variable","-Wno-unused-function","-fsanitize=undefined",
               str(p),"-o",str(exe)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            print(run.stdout)

if __name__=="__main__":unittest.main()
