"""Compile the real pool-generation and image retirement decisions."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_ocarina_cpu_written_serials import function

ROOT = Path(__file__).resolve().parents[4]


class RetiredPoolImages(unittest.TestCase):
    def test_dead_generations_and_live_aliases(self):
        source = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
        code = '''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdio.h>
#include "vka_texlimit.h"
#define VLOG(...) ((void)0)
enum { ST_ZERO, ST_FILL };
typedef struct { uint64_t gen; } pool_t;
typedef struct { struct { pool_t *pool; uint64_t serial; } t; uint64_t pgen; int retired; } treg_ent;
typedef struct {
    pool_t *pool; uint64_t pgen, pfin, serial, last_frame, last_fence;
    void *mem; int pdead, track, mode, from_mem, holds, gpu_owned;
} vka_img;
static uint64_t finalized;
static uint64_t nvn_pool_fin(void) { return finalized; }
static uint64_t nvn_pool_live(const void *p, void *flags, void *sparse) { (void)flags; (void)sparse; return p ? ((const pool_t *)p)->gen : 0; }
static void watch_del(vka_img *im) { (void)im; }
''' + function(source[source.index("static int img_pool_dead(vka_img *im) {"):], "img_pool_dead") + "\n" + "\n".join(function(source, n) for n in ("treg_pins_image", "img_prune_candidate")) + '''
int main(void) {
    pool_t pool = {1}; int bytes;
    treg_ent old = {.t={.pool=&pool,.serial=12}, .pgen=1};
    vka_img image = {.pool=&pool,.pgen=1,.last_frame=40,.last_fence=90,
                    .mode=ST_FILL,.from_mem=1,.mem=&bytes,.track=1};
    assert(treg_pins_image(&old));
    assert(!img_prune_candidate(&image,100,100,1));
    // Finalization invalidates the descriptor by generation, independently
    // of pointer reuse. No guest storage is read by the candidate check.
    pool.gen=0; finalized++;
    assert(!treg_pins_image(&old));
    assert(img_prune_candidate(&image,100,100,0));
    assert(image.pdead && !image.track);
    // Keep GPU content, host holds, pending fences, recent resources, and
    // another LIVE alias to the very same image.
    image.gpu_owned=1; assert(!img_prune_candidate(&image,100,100,0)); image.gpu_owned=0;
    image.holds=1; assert(!img_prune_candidate(&image,100,100,0)); image.holds=0;
    image.last_fence=101; assert(!img_prune_candidate(&image,100,100,0)); image.last_fence=90;
    image.last_frame=99; assert(!img_prune_candidate(&image,100,100,0)); image.last_frame=40;
    assert(!img_prune_candidate(&image,100,100,1));
    // A new pool at the same address does not revive its old descriptor.
    pool.gen=2;
    assert(!treg_pins_image(&old));
    treg_ent alias = {.t={.pool=&pool,.serial=13},.pgen=2};
    assert(treg_pins_image(&alias));
    assert(!img_prune_candidate(&image,100,100,treg_pins_image(&alias)));
    // Unknown generations remain conservative; a retired descriptor can
    // only become active again through explicit registration.
    old.pgen=0; assert(treg_pins_image(&old));
    old.retired=1; assert(!treg_pins_image(&old));
    old.retired=0; old.pgen=2; assert(treg_pins_image(&old));
    puts("retired pool image policy: passed");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            src, exe = work / "retirement.c", work / "retirement"
            src.write_text(code)
            compiler = shutil.which("clang") or shutil.which("gcc")
            self.assertIsNotNone(compiler)
            subprocess.run([
                compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Werror",
                "-fsanitize=address,undefined", "-I" + str(ROOT / "dm/gfx/vk_android"),
                str(src), "-o", str(exe),
            ], check=True)
            env = os.environ.copy()
            env["ASAN_OPTIONS"] = "detect_leaks=0"
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
