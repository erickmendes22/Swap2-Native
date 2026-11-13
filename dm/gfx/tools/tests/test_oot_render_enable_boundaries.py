"""Production mesh lookahead must stop at every render-enable boundary.
The failed fusion option is removed; replay still evaluates all conditions.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()


def body(source, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", source, re.S)
    assert m, name
    depth = 1
    for i in range(m.end(), len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if not depth:
            return source[m.start():i + 1]
    raise AssertionError("unterminated C function " + name)


class RenderEnableBoundaries(unittest.TestCase):
    def test_experiment_cannot_be_reenabled_from_saved_preferences(self):
        app = ROOT / "android/app/src/main/java/dev/nxnative/android"
        for name in ("Prefs.java", "GameSettings.java", "GameActivity.java"):
            text = (app / name).read_text()
            self.assertNotIn("memuRenderEnableFuse", text)
            self.assertNotIn("DM_VK_MEMU_RC_TRUE_FUSE", text)
        self.assertNotIn("DM_VK_MEMU_RC_TRUE_FUSE", SRC)

    def test_real_production_walker_respects_all_render_conditions(self):
        cc = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(cc)
        source = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define DM_GAME_ID "0400486024DEC000"
#define VKA_ENV(k, def) (def)
#define NVN_PRIM_MESH 5
enum {
 OP_END=0, OP_JUMP=1, OP_CALL=2, OP_DRAW=3,
 OP_DRAW_IDX=4, OP_RENDER_COND=5, OP_BARRIER=6,
 OP_SET_RT=7, OP_BIND_PROGRAM=8, OP_COUNT_=9
};
enum { MEMU_BEGIN, MEMU_ADD, MEMU_SETUP, MEMU_TASK, MEMU_DIST, MEMU_MESH, MEMU_END };
typedef struct { uint32_t op, size; } op_hdr;
typedef struct { uint32_t op,size; uint64_t x,y; } record;
typedef struct { int32_t mode,pad; uint64_t addr; } p_render_cond;
typedef struct { int prim,mdi_cnt; } p_draw;
typedef struct { int state; } vka_dstate;
static struct {int memu,mesh,task;} V = {1,0,0};
static struct {vka_dstate d; int rc_skip;} S;
static vka_dstate g_memu_st;
static _Thread_local const uint8_t *g_memu_caller[16];
static _Thread_local int g_memu_depth;
static uint64_t g_memu_parent_resumes,g_memu_nested_batches;
static uint64_t g_memu_boundary_op[OP_COUNT_+1];
static int g_n, states[128];
static int memu_allowed(uint32_t op) {
    return op != OP_RENDER_COND && op != OP_BARRIER && op != OP_SET_RT;
}
static const p_draw *draw_rec(const void *p, uint32_t size, p_draw *tmp) {
    (void)size; (void)tmp; return (const p_draw *)p;
}
static int vka_mesh_route(const vka_dstate *s) {(void)s; return 1;}
static int vka_vegetation_mesh_omit(const vka_dstate *s) {(void)s; return 0;}
static void vka_state_op(vka_dstate *s,uint32_t op,const void *a) {
    if (op == OP_BIND_PROGRAM) {int x;memcpy(&x,a,4);s->state=x;}
}
static void vka_memu_batch(int phase,const vka_dstate *d,const p_draw *dw,
                            const uint8_t *p,int idx) {
    (void)dw;(void)p;(void)idx;
    assert(phase==MEMU_ADD);
    assert(g_n < 128);
    states[g_n++]=d->state;
}
""" + "static int " + body(SRC, "memu_walk") + r"""
static int walk(const record *records) {
 S.rc_skip=0;S.d.state=10;
 g_n=0;g_memu_depth=0;
 int n=memu_walk((const uint8_t*)records,MEMU_ADD);
 assert(n==g_n);
 return n;
}
int main(void) {
 for(int mode=0;mode<=3;mode++) {
  record r[]={{OP_DRAW,24,5,0},{OP_RENDER_COND,24,(uint64_t)mode,0},
              {OP_BIND_PROGRAM,24,20,0},{OP_DRAW,24,5,0},{OP_END,24,0,0}};
  assert(walk(r)==1 && states[0]==10);
 }
 record malformed[]={{OP_DRAW,24,5,0},{OP_RENDER_COND,16,2,0},{OP_END,24,0,0}};
 assert(walk(malformed)==1);
 record inner[]={{OP_DRAW,24,5,0},{OP_RENDER_COND,24,2,0},{OP_END,24,0,0}};
 record parent[]={{OP_DRAW,24,5,0},{OP_END,24,0,0}};
 S.rc_skip=0;S.d.state=10;g_n=0;g_memu_depth=1;
 g_memu_caller[0]=(const uint8_t*)parent;
 assert(memu_walk((const uint8_t*)inner,MEMU_ADD)==1);
 assert(g_n==1 && g_memu_parent_resumes==0);
 puts("render-enable boundaries: all modes and nested-list conditions retained");
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.c"
            exe = Path(d) / "test"
            p.write_text(source)
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-O1", "-g", "-fsanitize=address,undefined",
                            str(p), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_source_preserves_render_query_and_barrier_replay(self):
        b = body(SRC, "memu_walk")
        self.assertNotIn('DM_VK_MEMU_RC_TRUE_FUSE', SRC)
        self.assertIn('if (!memu_allowed(h.op) || h.size < 8)', b)
        self.assertIn('case OP_RENDER_COND: S.rc_skip = rc_eval(a);', SRC)
        self.assertIn('case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);', SRC)


if __name__ == "__main__":
    unittest.main()
