"""Actual dead-image decision and live-pool alias guard, no guest-data reads."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_ocarina_cpu_written_serials import function

R = Path(__file__).resolve().parents[4]


class DeadGpuRetirement(unittest.TestCase):
    def test_actual_sweep_releases_dead_images_below_budget_without_touching_live_content(self):
        tex = (R / 'dm/gfx/vk_android/vka_tex.c').read_text()
        code = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include "vka_texlimit.h"
#define VLOG(...) ((void)0)
#define VKA_ENV(key,def) (def)
typedef struct { uint64_t gen; } pool_t;
typedef struct {
 const pool_t *pool;uint64_t pgen,pfin,serial,last_frame,last_fence,bytes;
 uint8_t *mem;struct {uint64_t size;} L;
 int pdead,track,holds,gpu_owned,refs,live_index;void *vpool;
 uint32_t sentinel;
} vka_img;
typedef struct {uint64_t serial;vka_img *im;} smap_ent;
typedef struct {struct {const pool_t *pool;uint64_t serial;}t;uint64_t pgen;int retired;}treg_ent;
static smap_ent g_map[16];static size_t g_mapcap=16;
static vka_img *g_live[8];static int g_nlive;
static treg_ent g_treg[8];static int g_ntreg=8;
static uint64_t frame=100,done=100,fin=1,g_dead_images,g_dead_image_bytes,freed_bytes;
static int dirty_count;
static uint64_t vka_frame(void){return frame;}
static uint64_t vka_done(void){return done;}
static uint64_t nvn_pool_fin(void){return fin;}
static uint64_t nvn_pool_live(const void *p,void*f,void*s){(void)f;(void)s;return p?((const pool_t*)p)->gen:0;}
static int nvn_pool_storage_live(const void *p,uint64_t n){assert(p && n);return 0;}
static void watch_del(vka_img *im){(void)im;}
static smap_ent *map_get(uint64_t s){for(int i=0;i<16;i++)if(g_map[i].serial==s)return &g_map[i];return 0;}
static void map_del(uint64_t s){smap_ent *e=map_get(s);assert(e);e->serial=~0ull;e->im=0;}
static void redirty_ids(vka_img *im){(void)im;dirty_count++;}
static void unref_locked(vka_img *im){
 assert(im->refs>0);if(--im->refs)return;
 assert(im->last_fence<=done && !im->holds && im->sentinel==0x12345678);
 int i=im->live_index,last=--g_nlive;assert(g_live[i]==im);
 if(i!=last){g_live[i]=g_live[last];g_live[i]->live_index=i;}
 freed_bytes+=im->bytes;free(im);
}
static vka_img *make(pool_t *pool,uint64_t serial,int gpu){
 vka_img *im=calloc(1,sizeof *im);assert(im);
 *im=(vka_img){.pool=pool,.pgen=1,.serial=serial,.last_frame=40,.last_fence=90,
   .bytes=64*VKTL_MIB,.mem=(void*)(uintptr_t)(0x10000*serial),.L={4096},
   .gpu_owned=gpu,.refs=1,.live_index=g_nlive,.sentinel=0x12345678};
 g_live[g_nlive++]=im;g_map[serial]=(smap_ent){serial,im};return im;
}
''' + function(tex[tex.index('static int img_pool_dead(vka_img *im) {'):], 'img_pool_dead') + '\n'
        code += '\n'.join(function(tex, n) for n in ('treg_pins_image', 'img_retire_candidate',
                                                     'img_forget_locked', 'vka_tex_retire_dead_locked'))
        code += r'''
int main(void){
 pool_t dead={0},live={1};
 vka_img *alive=make(&live,1,1);make(&dead,2,1);
 vka_img *pending=make(&dead,3,1);pending->last_fence=150;
 vka_img *held=make(&dead,4,1);held->holds=1;
 vka_img *aliased=make(&dead,5,1);make(&dead,6,0);
 g_treg[1]=(treg_ent){.t={&dead,2},.pgen=1}; // obsolete registration must not pin
 g_treg[2]=(treg_ent){.t={&live,5},.pgen=1}; // live registration must pin
 vka_tex_retire_dead_locked();
 assert(g_dead_images==2 && freed_bytes==128*VKTL_MIB && g_nlive==4);
 assert(alive->sentinel==0x12345678 && pending->refs==1 && held->refs==1 && aliased->refs==1);
 assert(!map_get(2) && !map_get(6) && map_get(1)->im==alive && dirty_count==2);
 // Retry after completed fences and released holds, independent of pressure.
 frame=131;done=200;held->holds=0;g_treg[2].retired=1;
 vka_tex_retire_dead_locked();
 assert(g_dead_images==5 && freed_bytes==320*VKTL_MIB && g_nlive==1);
 assert(g_live[0]==alive && alive->sentinel==0x12345678 && dirty_count==5);
 assert(map_get(1)->im==alive && !map_get(3) && !map_get(4) && !map_get(5));
 // Still-live GPU content is retained across repeated sweeps.
 frame=200;fin++;vka_tex_retire_dead_locked();assert(g_nlive==1 && freed_bytes==320*VKTL_MIB);
 free(alive);puts("actual sweep: dead GPU/CPU images released, live image bytes and pending references protected");
 return 0;
}
'''
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc: self.skipTest('C compiler required')
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory);c=tmp/'sweep.c';exe=tmp/'sweep';c.write_text(code)
            compiled=subprocess.run([cc,'-std=gnu11','-O1','-g','-Wall','-Werror',
                                     '-fsanitize=address,undefined','-I',str(R/'dm/gfx/vk_android'),
                                     str(c),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(exe)],env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),
                                  capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_generation_range_and_retirement_guards(self):
        tex = (R / 'dm/gfx/vk_android/vka_tex.c').read_text()
        nvn = (R / 'dm/gfx/nvn/hle_nvn.c').read_text()
        prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include "vka_texlimit.h"
#define VLOG(...) ((void)0)
typedef struct { uint8_t *mem; uint64_t size,gen; } pool_t;
typedef struct { const pool_t *p; uint64_t gen; } plive;
static plive g_pl[4];static uint32_t g_cpl=4;
static pthread_mutex_t g_pl_mu=PTHREAD_MUTEX_INITIALIZER;
static uint64_t finalized;
static uint64_t nvn_pool_fin(void){return finalized;}
static uint64_t nvn_pool_live(const void *p,void *f,void *s){(void)f;(void)s;return p?((const pool_t*)p)->gen:0;}
typedef struct {
 const pool_t *pool; uint64_t pgen,pfin,serial,last_frame,last_fence;
 uint8_t *mem;struct {uint64_t size;} L;
 int pdead,track,holds,gpu_owned;void *vpool;
} vka_img;
static void watch_del(vka_img *im){(void)im;}
'''
        source = prefix + function(nvn, 'nvn_pool_storage_live') + '\n'
        source += function(tex[tex.index('static int img_pool_dead(vka_img *im) {'):], 'img_pool_dead') + '\n'
        source += function(tex, 'img_retire_candidate') + r'''
int main(void){
 pool_t owner={(void*)0x10000,0x1000,1},alias={(void*)0x10800,0x1000,2};
 g_pl[0]=(plive){&owner,1};g_pl[2].p=(const pool_t*)1;
 vka_img im={.pool=&owner,.pgen=1,.mem=(void*)0x10400,.L={0x200},
             .last_frame=40,.last_fence=90,.gpu_owned=1,.track=1};
 assert(!img_retire_candidate(&im,100,100,0));
 owner.gen=0;g_pl[0]=(plive){0};finalized++;
 assert(img_retire_candidate(&im,100,100,0));assert(im.pdead && im.gpu_owned && !im.track);
 assert(!img_retire_candidate(&im,100,100,1));
 im.holds=1;assert(!img_retire_candidate(&im,100,100,0));im.holds=0;
 im.last_fence=101;assert(!img_retire_candidate(&im,100,100,0));im.last_fence=90;
 im.last_frame=99;assert(!img_retire_candidate(&im,100,100,0));
 im.last_frame=100;assert(!img_retire_candidate(&im,100,100,0));
 im.last_frame=0;assert(!img_retire_candidate(&im,100,100,0));im.last_frame=40;
 im.vpool=&alias;assert(!img_retire_candidate(&im,100,100,0));im.vpool=0;
 im.pgen=0;assert(!img_retire_candidate(&im,100,100,0));im.pgen=1;
 im.mem=0;assert(!img_retire_candidate(&im,100,100,0));im.mem=(void*)0x10400;
 im.pool=0;assert(!img_retire_candidate(&im,100,100,0));im.pool=&owner;
 // Live overlapping storage vetoes retirement even without a descriptor.
 g_pl[1]=(plive){&alias,2};alias.mem=(void*)0x105ff;
 assert(!img_retire_candidate(&im,100,100,0));
 alias.mem=(void*)0x10600;assert(img_retire_candidate(&im,100,100,0));
 alias.mem=(void*)0x10000;alias.size=0x400;assert(img_retire_candidate(&im,100,100,0));
 alias.size=0x401;assert(!img_retire_candidate(&im,100,100,0));
 // Reinitialization at the owner's object address does not revive old IDs,
 // but its new overlapping storage still protects the old GPU content.
 owner.gen=3;g_pl[0]=(plive){&owner,3};
 assert(!img_retire_candidate(&im,100,100,0));g_pl[0]=(plive){0};
 alias.mem=0;alias.size=0;assert(img_retire_candidate(&im,100,100,0));
 alias.size=4096;assert(!img_retire_candidate(&im,100,100,0));
 alias.mem=(void*)(UINTPTR_MAX-1);alias.size=4;assert(!img_retire_candidate(&im,100,100,0));
 g_pl[1]=(plive){0};
 im.mem=(void*)(UINTPTR_MAX-1);im.L.size=4;assert(!img_retire_candidate(&im,100,100,0));
 im.mem=(void*)0x10400;im.L.size=0;assert(!img_retire_candidate(&im,100,100,0));
 im.L.size=0x200;assert(img_retire_candidate(&im,100,100,0));
 puts("dead GPU retirement: actual generation, alias, fence, hold, sparse/video and overflow guards passed");
 return 0;
}
'''
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory); c = tmp / 'dead.c'; exe = tmp / 'dead'
            c.write_text(source)
            compiled = subprocess.run([cc, '-std=gnu11', '-O1', '-g', '-Wall', '-Werror',
                                       '-fsanitize=address,undefined', '-pthread', '-I', str(R / 'dm/gfx/vk_android'),
                                       str(c), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(exe)], env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'),
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('guards passed', result.stdout)

    def test_normal_gpu_eviction_stays_forbidden_and_retirement_precedes_budget(self):
        source = (R / 'dm/gfx/vk_android/vka_tex.c').read_text()
        normal = function(source, 'img_evict_locked')
        self.assertIn('im->gpu_owned', normal)
        retire = function(source, 'vka_tex_retire_dead_locked')
        self.assertIn('treg_pins_image(&g_treg[id])', retire)
        self.assertNotIn('vka_pfb_set()', retire)
        self.assertIn('img_retire_candidate(im,frame,done,registered[i])', retire)
        prepare = source[source.index('int vka_tex_prepare('):]
        self.assertLess(prepare.index('vka_tex_retire_dead_locked();'), prepare.index('vka_tex_prune_locked();'))


if __name__ == '__main__':
    unittest.main()
