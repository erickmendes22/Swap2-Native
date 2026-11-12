"""Production optimizer publication, retirement fences and RAM admission."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_ocarina_cpu_written_serials import function

ROOT = Path(__file__).resolve().parents[4]


class PipelineRetirement(unittest.TestCase):
    def test_replacement_lifetime_and_pressure(self):
        source = (ROOT / "dm/gfx/vk_android/vka_pso.c").read_text()
        code = r'''
#define _GNU_SOURCE 1
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <pthread.h>
#include "vka_texlimit.h"
typedef uint64_t VkPipeline;
typedef struct { VkPipeline p; unsigned char linked; } gval;
typedef struct opt_job { struct opt_job *next; gval *g; VkPipeline old; } opt_job;
static opt_job *g_opt_retired;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t g_nopt;
static _Atomic uint64_t g_opt_retire_queued, g_opt_retire_freed;
static struct { int dev; } V;
static unsigned destroyed[22000], destroyed_count;
static void destroy_pipeline(int dev, VkPipeline p, const void *a) {
    (void)dev; (void)a; assert(p < 22000 && !destroyed[p]);
    destroyed[p]=1; destroyed_count++;
}
static struct { void (*vkDestroyPipeline)(int,VkPipeline,const void*); } vk={destroy_pipeline};
static struct { uint64_t fence; void (*fn)(void*); void *arg; } pending[1200];
static int npending;
static void vka_after(uint64_t fence, void (*fn)(void*), void *arg) {
    assert(npending < 1200); pending[npending++]=(typeof(pending[0])){fence,fn,arg};
}
static void gpu_done(uint64_t fence) {
    for (int i=0;i<npending;i++) if (pending[i].fn && pending[i].fence<=fence) {
        void (*fn)(void*)=pending[i].fn; pending[i].fn=NULL; fn(pending[i].arg);
    }
}
static uint64_t clock_ns;
static uint64_t now_ns(void) { return clock_ns; }
static char meminfo[512]; static const char *floor_override; static int reads, unreadable;
static const char *test_env(const char *key) { assert(!strcmp(key,"DM_VK_PREWARM_RAM_FLOOR_MB")); return floor_override; }
static FILE *test_open(const char *path, const char *mode) {
    (void)mode; assert(!strcmp(path,"/proc/meminfo")); reads++;
    return unreadable ? NULL : fmemopen(meminfo,strlen(meminfo),"r");
}
static void memory_sample(unsigned available_mb) {
    snprintf(meminfo,sizeof meminfo,"MemTotal: 12582912 kB\nMemAvailable: %u kB\n",available_mb*1024);
    clock_ns+=300000000;
}
#define getenv test_env
#define fopen test_open
''' + "\n".join(function(source, n) for n in ("opt_publish", "opt_destroy_old", "vka_pso_retire")) + "\n" + function(source[source.index("static int pw_memory_pressure(void) {"):], "pw_memory_pressure") + r'''
#undef getenv
#undef fopen
int main(void) {
    gval current[1000];
    for (int i=0;i<1000;i++) {
        current[i]=(gval){i+1,1}; opt_job *j=calloc(1,sizeof *j); j->g=&current[i];
        assert(opt_publish(j,10001+i));
        assert(current[i].p==10001u+i && !current[i].linked);
    }
    assert(!destroyed_count && g_opt_retire_queued==1000);
    vka_pso_retire(7);
    assert(!destroyed_count && npending==1000);
    gpu_done(6); assert(!destroyed_count);
    // A publication after commit 7 cannot be collected by that commit.
    opt_job *late=calloc(1,sizeof *late); late->g=&current[0];
    assert(opt_publish(late,20001));
    gpu_done(7); assert(destroyed_count==1000 && !destroyed[10001]);
    vka_pso_retire(9); gpu_done(8); assert(!destroyed[10001]);
    gpu_done(9); assert(destroyed_count==1001 && destroyed[10001] && !destroyed[20001]);
    // Failed compilation keeps the working linked handle; no retirement.
    gval failure={21000,1}; opt_job fail={.g=&failure};
    assert(!opt_publish(&fail,0) && failure.p==21000 && failure.linked);
    assert(g_opt_retire_freed==g_opt_retire_queued);
    memory_sample(1024); assert(pw_memory_pressure());
    int before=reads; assert(pw_memory_pressure() && reads==before);
    memory_sample(2048); assert(!pw_memory_pressure());
    floor_override="512"; memory_sample(1024); assert(!pw_memory_pressure());
    floor_override="0"; memory_sample(64); assert(!pw_memory_pressure());
    floor_override=NULL; unreadable=1; memory_sample(64); assert(!pw_memory_pressure());
    puts("1001 replaced pipelines retired after their fences; failed compile, late publication and RAM admission passed");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            src, exe = work / "pipelines.c", work / "pipelines"
            src.write_text(code)
            compiler = shutil.which("clang") or shutil.which("gcc")
            self.assertIsNotNone(compiler)
            subprocess.run([
                compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Werror",
                "-pthread", "-fsanitize=address,undefined",
                "-I" + str(ROOT / "dm/gfx/vk_android"), str(src), "-o", str(exe),
            ], check=True)
            env = os.environ.copy()
            env["ASAN_OPTIONS"] = "detect_leaks=0"
            result = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Retirement must happen after all encoder calls of a submission,
        # rather than on the optimizer thread as soon as it swaps the handle.
        execute = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
        commit = function(execute, "vka_rp_sub_commit")
        self.assertIn("vka_enc_stop();", commit)
        tail = commit[commit.index("vka_enc_stop();"):]
        self.assertLess(tail.index("vka_pso_retire(fence)"), tail.index("vka_submit("))


if __name__ == "__main__":
    unittest.main()
