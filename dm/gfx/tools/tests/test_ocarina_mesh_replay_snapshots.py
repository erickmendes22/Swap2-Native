"""Compare production Ocarina mesh lookahead against state-cached task/mesh phases.
No GPU work, shaders or command order are changed. CPU synthetic indicator only.
"""
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
MEMU = (ROOT / "dm/gfx/vk_android/vka_memu_draw.inc").read_text()

def function(src, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", src, re.S)
    assert m, name
    level = 1
    for end in range(m.end(), len(src)):
        level += (src[end] == "{") - (src[end] == "}")
        if not level:
            return src[m.start():end+1]
    raise AssertionError("unclosed " + name)

class MeshReplaySnapshots(unittest.TestCase):
    def test_production_snapshot_is_before_any_early_exit(self):
        add = function(MEMU, "vka_memu_batch")
        i = add.index("int ei = vka_memu_order_add(&MB.o, p);")
        snapshot = add.index("memcpy(&MB.st[ei], d, sizeof MB.st[ei]);")
        validate = add.index("if (!resolve(mp, 6, &ts, &bad)")
        self.assertLess(i, snapshot)
        self.assertLess(snapshot, validate)
        self.assertIn("vka_dstate st[MEMU_MAX]", MEMU)
        self.assertIn("vka_memu_replay_phase(MEMU_TASK);", EXEC)
        self.assertIn("vka_memu_replay_phase(MEMU_MESH);", EXEC)
        self.assertNotIn("memu_walk(p, MEMU_TASK);", EXEC)
        self.assertNotIn("memu_walk(p, MEMU_MESH);", EXEC)
        self.assertIn("if (phase != MEMU_TASK && phase != MEMU_MESH) return;", MEMU)

    def test_compiled_production_walk_and_replay_match_gpu_trace(self):
        stub = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define DM_GAME_ID "0400486024DEC000"
#define VKA_ENV(key, def) (def)
#define NVN_PRIM_MESH 5
enum { OP_END, OP_CALL, OP_JUMP, OP_DRAW, OP_BIND_PROGRAM, OP_SET_RT, OP_DRAW_IDX, OP_RENDER_COND, OP_BARRIER, OP_COUNT_ };
enum { MEMU_BEGIN, MEMU_ADD, MEMU_SETUP, MEMU_TASK, MEMU_DIST, MEMU_MESH, MEMU_END };
typedef struct { uint32_t op, size; } op_hdr;
typedef struct { uint32_t op, size; uint64_t arg; } record;
typedef struct { int prim, mdi_cnt; } p_draw;
typedef struct { int state; } vka_dstate;
static struct { int memu, mesh, task; } V;
static struct { vka_dstate d; int rc_skip; } S;
static vka_dstate g_memu_st;
static const uint8_t *g_memu_caller[16]; static int g_memu_depth;
static uint64_t g_memu_parent_resumes, g_memu_nested_batches;
static uint64_t g_memu_boundary_op[OP_COUNT_+1];
enum { MEMU_MAX = 128 };
static struct { struct { int n; } o; vka_dstate st[MEMU_MAX]; } MB;
typedef struct {int phase, idx, state;} gpu_cmd;
static gpu_cmd trace[MEMU_MAX*2]; static int count;
static int state_ops, looked, resumed;
static int memu_allowed(uint32_t op) { return op != OP_SET_RT && op != OP_RENDER_COND && op != OP_BARRIER; }
static const p_draw *draw_rec(const void *a, uint32_t n, p_draw *out) { (void)n; (void)out; return a; }
static int vka_mesh_route(const vka_dstate *s) { (void)s; return 1; }
static int vka_vegetation_mesh_omit(const vka_dstate *s) { (void)s; return 0; }
static int vka_state_op(vka_dstate *s, uint32_t op, const void *a) {
    state_ops++;
    if (op == OP_BIND_PROGRAM) { int v; memcpy(&v,a,4); s->state=v; }
    return 1;
}
static void vka_memu_batch(int phase, const vka_dstate *d,
                           const p_draw *dw,const uint8_t *p,int idx) {
    (void)dw; (void)p;
    if (phase == MEMU_ADD) {
        assert(idx == MB.o.n && idx < MEMU_MAX);
        MB.st[idx] = *d; MB.o.n++;
    } else {
        assert(count < MEMU_MAX*2);
        trace[count++] = (gpu_cmd){phase,idx,d->state};
    }
}
""" + "static int " + function(EXEC, "memu_walk") + "\nvoid " + function(MEMU, "vka_memu_replay_phase") + r"""
int main(void) {
    record nested[] = {
        {OP_BIND_PROGRAM,16,30}, {OP_DRAW,16,5},
        {OP_BIND_PROGRAM,16,31}, {OP_DRAW,16,5},
        {OP_END,16,0}
    };
    record commands[] = {
        {OP_BIND_PROGRAM,16,10}, {OP_DRAW,16,5},
        {OP_CALL,16,0},
        {OP_BIND_PROGRAM,16,40}, {OP_DRAW,16,5},
        {OP_BIND_PROGRAM,16,50}, {OP_DRAW,16,5},
        {OP_END,16,0}
    };
    commands[2].arg = (uintptr_t)nested;
    gpu_cmd old[MEMU_MAX*2]; int oldcount;
    int old_stateops,new_stateops;
    for (int iter=0;iter<300;iter++) {
        MB.o.n = 0; S.d.state = 1; g_memu_depth=0;count=0;state_ops=0;
        assert(memu_walk((const uint8_t*)commands,MEMU_ADD)==5);
        assert(MB.o.n==5);
        assert(memu_walk((const uint8_t*)commands,MEMU_TASK)==5);
        assert(memu_walk((const uint8_t*)commands,MEMU_MESH)==5);
        oldcount=count; memcpy(old,trace,(size_t)count*sizeof(gpu_cmd));
        old_stateops=state_ops;
        MB.o.n=0;S.d.state=1;g_memu_depth=0;count=0;state_ops=0;
        assert(memu_walk((const uint8_t*)commands,MEMU_ADD)==5);
        vka_memu_replay_phase(MEMU_TASK);
        vka_memu_replay_phase(MEMU_MESH);
        new_stateops=state_ops;
        assert(count==oldcount && memcmp(trace,old,(size_t)count*sizeof(gpu_cmd))==0);
        assert(new_stateops*3==old_stateops);
    }
    // No lookahead may cross guest barriers, target swaps, or conditions.
    for (int op=OP_SET_RT;op<=OP_BARRIER;op++) {
        if(op!=OP_SET_RT && op!=OP_RENDER_COND && op!=OP_BARRIER)continue;
        record blocked[]={{OP_DRAW,16,5},{(uint32_t)op,16,0},{OP_DRAW,16,5},{OP_END,16,0}};
        MB.o.n=0; S.d.state=11; count=0;
        assert(memu_walk((const uint8_t*)blocked,MEMU_ADD)==1);
        vka_memu_replay_phase(MEMU_TASK);
        vka_memu_replay_phase(MEMU_MESH);
        assert(count==2 && trace[0].idx==0 && trace[1].idx==0);
    }
    printf("cached mesh GPU order identical; 2 of 3 CPU-only state walks eliminated; baseline ops=%d cached ops=%d\n",old_stateops,new_stateops);
    return 0;
}
"""
        cc=shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(cc)
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"snapshot.c"; exe=Path(tmp)/"snapshot"
            src.write_text(stub)
            subprocess.run([cc,"-std=c11","-O1","-g","-Wall","-Wextra","-Werror",
                "-Wno-unused-variable","-fsanitize=address,undefined",str(src),"-o",str(exe)],
                check=True,capture_output=True,text=True)
            result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
            self.assertIn("cached mesh GPU order identical",result.stdout)

if __name__ == "__main__":
    unittest.main()
