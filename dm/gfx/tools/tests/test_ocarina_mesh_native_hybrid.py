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
static int g_vegetation_enabled = 1, native_base = 1;
#define VKA_ENV(k, def) (!strcmp((k),"DM_VK_VEGETATION") ? g_vegetation_enabled : native_base)
typedef struct { uint64_t key; } vka_shader;
typedef struct prog_t { vka_shader *ts, *ms; } prog_t;
typedef struct { const prog_t *bst[8]; } vka_dstate;
static int resolve(const prog_t *p,int stage,vka_shader **out,unsigned *bad) {
    (void)bad; *out = p ? (stage == 6 ? p->ts : stage == 7 ? p->ms : NULL) : NULL;
    return 1;
}
""" + "static int " + function(draw, 'veg_supplement_stage') + "\nint " + function(draw, 'vka_mesh_route') + r"""
int main(void) {
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
            p.ts->key = original_task.key;
        } else {
            p.ts->key = vka_veg_entries[i].key;
            p.ms->key = original_mesh.key;
        }
        assert(vka_mesh_route(&d) == 1);           // supplement compute
        g_vegetation_enabled = 0;
        assert(vka_mesh_route(&d) == -1);          // OFF skips work before batch
        g_vegetation_enabled = 1;
        p.ms->key = original_mesh.key;
        p.ts->key = original_task.key;
    }
    assert(vka_mesh_route(&d) == 0);                 // original still native
    V.task=0; assert(vka_mesh_route(&d) == 1);       // no task support -> old emu
    V.task=1; V.mesh=0; assert(vka_mesh_route(&d) == 1);
    V.mesh=1; native_base=0; assert(vka_mesh_route(&d) == 1); // rollback
    native_base=1; V.memu=0; assert(vka_mesh_route(&d) == 0); // native-only
    p.ms->key = vka_veg_entries[0].key;
    g_vegetation_enabled=0; assert(vka_mesh_route(&d) == -1);  // OFF works with emu disabled
    V.memu=1; V.task=0; assert(vka_mesh_route(&d) == -1); // OFF works without hardware task support
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

    def test_hybrid_lookahead_does_not_overtake_native_mesh(self):
        src = (VK / 'vka_exec.c').read_text()
        walk = function(src, 'memu_walk')
        self.assertLess(walk.index('if (route == 0) break;'),
                        walk.index('vka_memu_batch(phase'))
        self.assertIn('phase >= 0 || vegetation_off || hybrid', walk)
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
