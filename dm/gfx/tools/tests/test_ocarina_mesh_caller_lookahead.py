"""Compile production memu_walk and prove nested OP_CALL returns remain in one batch.

The replay (unlike Banana Native's iterative variant) uses recursive exec().
Until this patch memu_walk started with nret=0 inside every nested list, so
its lookahead stopped at the child OP_END, repeating GPU setup/dispatch/pass
splits for adjacent parent draws. The test executes the ACTUAL walker with
simulated guest command records and checks crossing one and two call levels.
"""
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
SRC = (ROOT / 'dm/gfx/vk_android/vka_exec.c').read_text()


def body(source, name):
    m = re.search(r'\b' + re.escape(name) + r'\s*\([^;]*?\)\s*\{', source, re.S)
    assert m, name
    depth = 1
    for i in range(m.end(), len(source)):
        depth += (source[i] == '{') - (source[i] == '}')
        if not depth:
            return source[m.start():i+1]
    raise AssertionError('unterminated ' + name)


class MeshCallerLookahead(unittest.TestCase):
    def test_production_walker_resumes_one_and_two_parent_lists(self):
        src = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define DM_GAME_ID "0400486024DEC000"
#define VKA_ENV(key, def) (def)
#define NVN_PRIM_MESH 5
enum { OP_END=0, OP_CALL=1, OP_JUMP=2, OP_DRAW=3, OP_BIND_PROGRAM=4, OP_SET_RT=5, OP_DRAW_IDX=6, OP_COUNT_=7 };
enum { MEMU_BEGIN, MEMU_ADD, MEMU_SETUP, MEMU_TASK, MEMU_DIST, MEMU_MESH, MEMU_END };
typedef struct { uint32_t op, size; } op_hdr;
typedef struct { uint32_t op, size; uint64_t arg; } record;
typedef struct { int prim, mdi_cnt; } p_draw;
typedef struct { int state; } vka_dstate;
static struct { int memu, mesh, task; } V = {0,0,0};
static struct { vka_dstate d; } S;
static vka_dstate g_memu_st;
static _Thread_local const uint8_t *g_memu_caller[16];
static _Thread_local int g_memu_depth;
static uint64_t g_memu_parent_resumes, g_memu_nested_batches;
static uint64_t g_memu_boundary_op[OP_COUNT_ + 1];
static int batched, states[32];
static int memu_allowed(uint32_t op) { return op != OP_SET_RT; }
static const p_draw *draw_rec(const void *arg, uint32_t size, p_draw *tmp) {
    (void)size; (void)tmp; return (const p_draw *)arg;
}
static int vka_mesh_route(const vka_dstate *s) { (void)s; return 1; }
static int vka_vegetation_mesh_omit(const vka_dstate *s) { (void)s; return 0; }
static void vka_state_op(vka_dstate *s, uint32_t op, const void *a) {
    if (op == OP_BIND_PROGRAM) { int v; memcpy(&v, a, sizeof v); s->state = v; }
}
static void vka_memu_batch(int phase, const vka_dstate *s, const p_draw *d, const uint8_t *p, int idx) {
    (void)p; (void)d; (void)idx;
    assert(phase == MEMU_ADD);
    assert(batched < 32);
    states[batched++] = s->state;
}
""" + "static int " + body(SRC, 'memu_walk') + r"""
int main(void) {
    // Called list: draw@10, end; parent: draw@20, end.
    record inner[] = {{OP_DRAW,16,5}, {OP_END,16,0}};
    record parent[] = {{OP_BIND_PROGRAM,16,20}, {OP_DRAW,16,5}, {OP_END,16,0}};
    g_memu_depth = 1; g_memu_caller[0] = (const uint8_t*)&parent[0];
    S.d.state = 10;
    assert(memu_walk((const uint8_t*)&inner[0], MEMU_ADD) == 2);
    assert(batched == 2 && states[0] == 10 && states[1] == 20);
    assert(g_memu_parent_resumes == 1 && g_memu_nested_batches == 1);
    // Grandchild -> middle -> outer, preserving state updates at both returns.
    record middle[] = {{OP_BIND_PROGRAM,16,30}, {OP_DRAW,16,5}, {OP_END,16,0}};
    record outer[] = {{OP_BIND_PROGRAM,16,40}, {OP_DRAW,16,5}, {OP_END,16,0}};
    g_memu_depth = 2; g_memu_caller[0] = (const uint8_t*)&outer[0];
    g_memu_caller[1] = (const uint8_t*)&middle[0];
    batched = 0; S.d.state = 10;
    assert(memu_walk((const uint8_t*)&inner[0], MEMU_ADD) == 3);
    assert(batched == 3 && states[0] == 10 && states[1] == 30 && states[2] == 40);
    assert(g_memu_parent_resumes == 3 && g_memu_nested_batches == 2);
    // A real render-target change remains a hard lookahead boundary.
    record boundary[] = {{OP_BIND_PROGRAM,16,30}, {OP_DRAW,16,5},
                         {OP_SET_RT,16,0}, {OP_DRAW,16,5}, {OP_END,16,0}};
    g_memu_depth = 1; g_memu_caller[0] = (const uint8_t*)&boundary[0];
    batched = 0; S.d.state = 10;
    assert(memu_walk((const uint8_t*)&inner[0], MEMU_ADD) == 2);
    assert(batched == 2 && states[0] == 10 && states[1] == 30);
    // The existence probe remains side-effect-free and sees first mesh draw.
    batched = 0; assert(memu_walk((const uint8_t*)&inner[0], -1) == 1);
    assert(batched == 0);
    return 0;
}
"""
        cc = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(cc)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp)/'replay.c'; exe = Path(tmp)/'replay'
            f.write_text(src)
            subprocess.run([cc,'-std=c11','-O1','-g','-Wall','-Wextra',
                            '-Werror','-fsanitize=address,undefined',str(f),'-o',str(exe)],
                           check=True)
            subprocess.run([str(exe)], check=True)

    def test_real_recursive_exec_captures_return_before_child_and_restores_depth(self):
        exec_src = body(SRC[SRC.index('static void exec(const uint8_t *p, int depth)'):], 'exec')
        self.assertIn('g_memu_depth = depth;', exec_src)
        self.assertIn('g_memu_caller[depth] = p + h.size;', exec_src)
        self.assertLess(exec_src.index('g_memu_caller[depth] = p + h.size;'),
                        exec_src.index('exec((const uint8_t *)(uintptr_t)t, depth + 1)'))
        self.assertIn('g_memu_depth = depth; // child returned:', exec_src)
        walk = body(SRC, 'memu_walk')
        self.assertIn('for (int i = 0; i < nret; i++) ret[i] = g_memu_caller[i];',walk)
        self.assertIn('if (!memu_allowed(h.op) || h.size < 8) {',walk)
        self.assertIn('g_memu_boundary_op[h.op]++',walk)


if __name__ == '__main__':
    unittest.main()
