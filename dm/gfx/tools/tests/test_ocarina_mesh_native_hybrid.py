"""Exercise production Ocarina mesh routing against all reviewed 508 shader keys.

The old 42k library's native mesh path must NOT be routed through compute.
Only new supplement shaders use the mesh emulator (unless explicitly rolled
back), and vegetation OFF must discard them BEFORE GPU work on any driver.
These are compile/run C tests, not a claim about phone FPS or visuals.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


def function(source, name):
    import re
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", source, re.S)
    assert m is not None, name
    depth = 1
    for i in range(m.end(), len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[m.start():i + 1]
    raise AssertionError("unterminated " + name)


class MeshNativeHybrid(unittest.TestCase):
    def test_real_production_c_routes_all_508_without_reordering(self):
        draw = (VK / "vka_draw.c").read_text()
        source = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "dmsh_abi_vk.h"
#include "vka_vegetation_supplement.h"
#define DM_GAME_ID "0400486024DEC000"
static struct { int memu, mesh, task; } V = {1,1,1};
static int g_vegetation_enabled = 1, native_base = 1, route_mode = 0;
#define VKA_ENV(k, def) (!strcmp((k),"DM_VK_VEGETATION") ? g_vegetation_enabled : !strcmp((k),"DM_VK_OOT_MESH_ROUTE") ? route_mode : native_base)
typedef struct { uint64_t key; } vka_shader;
typedef struct prog_t { vka_shader *ts, *ms; } prog_t;
typedef struct { const prog_t *bst[8]; } vka_dstate;
static unsigned shader_resolves;
static int resolve(const prog_t *p,int stage,vka_shader **out,unsigned *bad) {
    ++shader_resolves;
    (void)bad; *out = p ? (stage == 6 ? p->ts : stage == 7 ? p->ms : NULL) : NULL;
    return 1;
}
""" + "static int " + function(draw, 'veg_supplement_stage') + "\nint " + function(draw, 'vka_mesh_route') + r"""
int main(void) {
    const uint64_t original_mesh_key = UINT64_C(0xdeadbeefef5a5120);
    const uint64_t original_task_key = UINT64_C(0xdeadbeefef5a5121);
    vka_shader original_mesh = {UINT64_C(0xdeadbeefef5a5120)};
    vka_shader original_task = {UINT64_C(0xdeadbeefef5a5121)};
    prog_t p = { .ts=&original_task, .ms=&original_mesh };
    vka_dstate d = {0}; d.bst[7] = &p;
    assert(!veg_supplement_stage(original_mesh.key));
    assert(vka_mesh_route(&d) == 0);                 // old native mesh restored
    g_vegetation_enabled = 0;
    assert(vka_mesh_route(&d) == 0);                 // no native->compute regression OFF
    g_vegetation_enabled = 1;
    for (unsigned i=0; i<sizeof vka_veg_entries / sizeof *vka_veg_entries; ++i) {
        assert(veg_supplement_stage(vka_veg_entries[i].key));
        if (i) assert(vka_veg_entries[i-1].key < vka_veg_entries[i].key);
        if (vka_veg_entries[i].stage == DMSH_VK_STAGE_MS) {
            p.ms->key = vka_veg_entries[i].key;
            p.ts->key = original_task_key;
        } else {
            p.ts->key = vka_veg_entries[i].key;
            p.ms->key = original_mesh_key;
        }
        assert(vka_mesh_route(&d) == 1);           // supplement compute
        g_vegetation_enabled = 0;
        assert(vka_mesh_route(&d) == -1);          // OFF skips work before batch
        g_vegetation_enabled = 1;
        p.ms->key = original_mesh_key;
        p.ts->key = original_task_key;
    }
    assert(vka_mesh_route(&d) == 0);                 // original still native
    V.task=0; assert(vka_mesh_route(&d) == 1);       // no task support -> old emu
    V.task=1; V.mesh=0; assert(vka_mesh_route(&d) == 1);
    V.mesh=1; native_base=0; assert(vka_mesh_route(&d) == 1); // rollback
    native_base=1; V.memu=0; assert(vka_mesh_route(&d) == 0); // native-only
    p.ms->key = vka_veg_entries[0].key;
    g_vegetation_enabled=0; assert(vka_mesh_route(&d) == -1);  // OFF works with emu disabled
    V.memu=1; V.task=0; assert(vka_mesh_route(&d) == -1); // OFF works without hardware task support
    // New experimental choices: verify both exact routes and native
    // capability fallback, independently from vegetation OFF semantics.
    g_vegetation_enabled=1; V.task=1; V.mesh=1;
    p.ms->key=original_mesh_key;
    route_mode=1; assert(vka_mesh_route(&d) == 1); // all compute
    route_mode=2; assert(vka_mesh_route(&d) == 0); // all native
    p.ms->key=vka_veg_entries[0].key;
    route_mode=1; assert(vka_mesh_route(&d) == 1); // supplemental compute
    route_mode=2; assert(vka_mesh_route(&d) == 0); // supplemental native
    V.task=0; assert(vka_mesh_route(&d) == 1);     // feature fallback
    V.task=1; g_vegetation_enabled=0;
    assert(vka_mesh_route(&d) == -1);              // vegetation OFF always omits
    // Measured Qualcomm all-compute fast path must NOT repeatedly resolve
    // two shaders per draw merely to reselect the known compute route.
    // Vegetation OFF still resolves them, or supplement foliage would leak.
    route_mode = 1; g_vegetation_enabled = 1; V.memu = 1;
    shader_resolves = 0;
    for (unsigned i = 0; i < 10000; ++i)
        assert(vka_mesh_route(&d) == 1);
    assert(shader_resolves == 0);
    route_mode = -1;   // automatic compute on a device requiring emulation
    shader_resolves = 0;
    for (unsigned i = 0; i < 10000; ++i)
        assert(vka_mesh_route(&d) == 1);
    assert(shader_resolves == 0);
    route_mode = 0; g_vegetation_enabled = 0;
    shader_resolves = 0;
    assert(vka_mesh_route(&d) == -1 && shader_resolves > 0);
    route_mode=0;
    return 0;
}
"""
        cc = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(cc)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "route.c"; exe = Path(td) / "route"
            src.write_text(source)
            subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                            '-I' + str(VK), '-I' + str(ROOT / "dm/gfx/nvn"),
                            str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_indirect_compute_draw_without_native_mesh_entrypoint(self):
        # Compile the production routing block, including every early-return
        # guard. A helper-only test would miss the old native check above it.
        draw = function((VK / "vka_draw.c").read_text(), 'vka_draw')
        start = draw.index('    int mesh = dw && dw->prim == NVN_PRIM_MESH;')
        end = draw.index('    if (d->poly.cull == NVN_FACE_FRONT_AND_BACK')
        block = draw[start:end]
        source = r"""
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
#define NVN_PRIM_MESH 99
#define VKA_NSTAGE 8
#define DMSH_VK_F_MESH_PRIM 1
#define VKA_ENV(k, def) 0
#define VLOG(...) ((void)0)
#define VRED(...) ((void)0)
#define VRED_ONCE(...) ((void)0)
#define SKIP(...) do { result = -1; return; } while (0)
#define SKIPQ() SKIP("")
typedef struct { unsigned flags; } entry;
typedef struct { uint64_t key; entry *e; } vka_shader;
typedef struct { uint64_t serial; } prog_t;
typedef struct { const prog_t *bst[8]; int tf_on, rast_discard; } vka_dstate;
typedef struct { int prim, count, first; uint64_t ind; } p_draw;
typedef struct { int ok; vka_shader *vs; } memu_ent;
static struct { int mesh, memu; } V;
static struct { void (*vkCmdDrawMeshTasksIndirectEXT)(void); } vk;
static entry entries[3];
static vka_shader shaders[3] = {{1,&entries[0]},{2,&entries[1]},{3,&entries[2]}};
static memu_ent arena = {1, &shaders[2]};
static int route, result, g_skipped, vka_memu_n_skip, prepared, calls;
static int resolve(const prog_t *p, int st, vka_shader **out, unsigned *bad) {
    (void)p; (void)bad; *out = st == 7 ? &shaders[0] : st == 1 ? &shaders[1] : NULL; return 1;
}
static int vka_ocarina_capture_mesh_draw_pair(const prog_t *a, const prog_t *b) { (void)a; (void)b; return 1; }
static int oot_skip_one_fs(vka_shader *s) { (void)s; return 0; }
static int oot_ground_mist_safe(vka_dstate *d, vka_shader **s) { (void)d; (void)s; return 0; }
static int vegetation_cut(vka_dstate *d, vka_shader **s) { (void)d; (void)s; return 0; }
static int vka_mesh_route(vka_dstate *d) { (void)d; return route; }
static memu_ent *memu_find(void) { ++calls; return prepared ? &arena : NULL; }
static void native_entry(void) {}
typedef struct { int unused; } tex_t;
static int has_rt;
static struct { int n; tex_t *color[1], *depth; } *rt;
static void check(vka_dstate *d, p_draw *dw) {
    vka_shader *sh[VKA_NSTAGE] = {0}; unsigned bad = 0;
""" + block + r"""
    result = mesh ? 2 : 1;
    if (!mesh) assert(memu_e == &arena && sh[0] == arena.vs && !sh[7]);
}
int main(void) {
    vka_dstate d = {0}; p_draw dw = {.prim=NVN_PRIM_MESH, .ind=4096};
    V.memu=1; V.mesh=0; route=1; prepared=1;
    check(&d,&dw); assert(result == 1 && calls == 1); // no mesh extension
    V.mesh=1; check(&d,&dw); assert(result == 1);     // extension, missing entry point
    dw.ind=0; dw.count=3; check(&d,&dw); assert(result == 1); // direct unchanged
    dw.ind=4096; prepared=0; check(&d,&dw); assert(result == -1 && vka_memu_n_skip == 1);
    prepared=1; route=0; check(&d,&dw); assert(result == -1); // native must still reject
    vk.vkCmdDrawMeshTasksIndirectEXT=native_entry;
    check(&d,&dw); assert(result == 2);               // native available
    vk.vkCmdDrawMeshTasksIndirectEXT=NULL; dw.ind=0;
    check(&d,&dw); assert(result == 2);               // native direct needs no indirect API
    dw.ind=4096; route=-1; result=7;
    check(&d,&dw); assert(result == 7);               // vegetation OFF remains omitted
    return 0;
}
"""
        cc = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(cc)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'indirect.c'; exe = Path(td) / 'indirect'
            src.write_text(source)
            subprocess.run([cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-variable', '-O2', str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_hybrid_lookahead_does_not_overtake_native_mesh(self):
        src = (VK / 'vka_exec.c').read_text()
        walk = function(src, 'memu_walk')
        self.assertLess(walk.index('if (route == 0) {'),
                        walk.index('vka_memu_batch(phase'))
        self.assertIn('phase >= 0 || vegetation_off || quality_trim || mist_off || hybrid', walk)
        self.assertIn('!vka_ground_mist_mesh_omit(&g_memu_st)', walk)
        self.assertIn('!vka_vegetation_mesh_omit(&g_memu_st)', walk)
        self.assertIn('vka_mesh_route(&g_memu_st)', walk)
        before = function(src, 'memu_before_draw')
        self.assertLess(before.index('if (mesh && route == 0) return;'),
                        before.index('vka_rp_end(); vka_memu_n_splits++'))

    def test_native_pixel_is_raw_while_compute_pixel_stays_flat(self):
        shader = (VK / "vka_shader.c").read_text()
        pso = (VK / "vka_pso.c").read_text()
        raw = function(shader, 'vka_shader_native_mesh_fs_module')
        self.assertIn('vka_shlib_spirv(s->lib, m, &nb', raw)
        self.assertNotIn('vka_memu_fs_flat(', raw)
        flat = function(shader, 'lib_words')
        self.assertIn('vka_memu_fs_flat(', flat)
        fill = function(pso, 'pstate_fill')
        self.assertIn('mesh && fs && V.memu && (s->e->flags & DMSH_VK_F_MESH_PRIM)', fill)
        self.assertIn('vka_shader_native_mesh_fs_module(s', fill)
        self.assertIn('vka_shader_native_mesh_fout_module(s', fill)
        self.assertIn('vka_shader_module(s,', fill)


if __name__ == '__main__':
    unittest.main()
