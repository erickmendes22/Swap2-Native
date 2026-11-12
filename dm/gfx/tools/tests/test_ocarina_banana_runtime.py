"""Run the production vegetation selector and GPU-feedback demand decision."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_ocarina_cpu_written_serials import function
ROOT = Path(__file__).resolve().parents[4]

class BananaRuntime(unittest.TestCase):
    def run_c(self, code):
        compiler = shutil.which('clang') or shutil.which('cc')
        self.assertTrue(compiler)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'test.c'; exe = Path(td) / 'test'
            src.write_text(code)
            subprocess.run([compiler, '-std=c11', '-O1', '-g', '-fsanitize=address,undefined',
                '-I'+str(ROOT/'dm/gfx/vk_android'), '-I'+str(ROOT/'dm/gfx/nvn'),
                str(src), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, env={**os.environ, 'ASAN_OPTIONS':'detect_leaks=0'})

    def test_full_vegetation_is_not_cut_and_writes_are_protected(self):
        draw = (ROOT/'dm/gfx/vk_android/vka_draw.c').read_text()
        self.run_c('''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "dmsh_abi_vk.h"
#include "vka_vegetation_profiles.h"
#define VKA_NSTAGE 8
#define DM_GAME_ID "0400486024DEC000"
static int full = 1;
#define VKA_ENV(name, fallback) full
#define VLOG(...) ((void)0)
typedef struct { int tf_on; } vka_dstate;
typedef struct { const dmsh_vk_entry *e; const dmsh_vk_bind *b; uint64_t key; } vka_shader;
''' + function(draw, 'vegetation_cut') + '''
int main(void) {
    dmsh_vk_entry entry = {0}; dmsh_vk_bind binding = {0};
    vka_shader mesh = {.e=&entry,.b=&binding,.key=UINT64_C(0x0c1ffecd02018fb0)};
    vka_shader *sh[8] = {0}; sh[7]=&mesh; vka_dstate state={0};
    assert(vka_vegetation_key(DM_GAME_ID, mesh.key));
    assert(!vka_vegetation_key("other-game",mesh.key));
    assert(!vegetation_cut(&state,sh));
    full=0; assert(vegetation_cut(&state,sh));
    state.tf_on=1; assert(!vegetation_cut(&state,sh)); state.tf_on=0;
    entry.bind_count=1;
    binding.flags=DMSH_VK_BF_RW; assert(!vegetation_cut(&state,sh));
    binding.flags=DMSH_VK_BF_ATOMIC; assert(!vegetation_cut(&state,sh));
    binding.flags=DMSH_VK_BF_NOSLOT; assert(!vegetation_cut(&state,sh));
    binding.flags=0; binding.kind=DMSH_VK_KIND_GMEM_LOG; assert(!vegetation_cut(&state,sh));
    binding.kind=DMSH_VK_KIND_UNKNOWN; assert(!vegetation_cut(&state,sh));
    mesh.key=123; entry.bind_count=0; assert(!vegetation_cut(&state,sh));
    full=1; assert(!vegetation_cut(&state,sh));
    return 0;
}
''')

    def test_gpu_feedback_demands_only_read_ids(self):
        tex = (ROOT/'dm/gfx/vk_android/vka_tex.c').read_text()
        self.run_c('''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
enum { PFB_WANT=1, PFB_NULL=2 };
typedef struct { uint64_t last_frame,last_fence; } vka_img;
typedef struct { vka_img *im; } smap_ent;
typedef struct { struct { uint64_t serial; void *pool; } t; int img; uint64_t pgen; } treg_ent;
static treg_ent g_treg[64]; static int g_ntreg=64; static unsigned g_ntex_slots=64;
static uint8_t state[64], *g_pfb_st=state;
static uint64_t g_pfb_hits,g_pfb_wants; static smap_ent map[64];
static int *g_tdirty,g_ntd,g_tdcap; static uint8_t *g_tdflag;
static uint64_t nvn_pool_live(void *p,void *x,void *y) { (void)p;(void)x;(void)y;return 1; }
static smap_ent *map_get(uint64_t s) { return &map[s]; }
static void dirty(int **l,int *n,int *cap,uint8_t **flags,int max,int id) {
    (void)l;(void)cap;(void)flags;(void)max;(void)id;(*n)++;
}
''' + function(tex,'pfb_hit') + '''
int main(void) {
    for(int i=1;i<64;i++){g_treg[i].t.serial=i;state[i]=PFB_NULL;}
    pfb_hit(12,100,200);
    assert(g_pfb_wants==1 && g_ntd==1 && state[12]&PFB_WANT);
    assert(!(state[13]&PFB_WANT));
    pfb_hit(12,100,200); assert(g_pfb_wants==1);
    vka_img image={90,180};map[12].im=&image;state[12]=0;
    int dirty_before=g_ntd;pfb_hit(12,101,201);
    assert(image.last_frame==101 && image.last_fence==201 && g_ntd==dirty_before);
    g_treg[13].img=1;pfb_hit(13,101,201); assert(!(state[13]&PFB_WANT));
    g_treg[14].t.pool=&image;g_treg[14].pgen=2;pfb_hit(14,101,201);assert(!(state[14]&PFB_WANT));
    pfb_hit(0,101,201);pfb_hit(64,101,201);
    return 0;
}
''')

if __name__ == '__main__':
    unittest.main()
