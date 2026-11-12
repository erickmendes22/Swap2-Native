"""Run the real CPU-written texture serial set without a Vulkan device."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]


def function(source, name):
    start = source.index(name + "(")
    start = source.rfind("\n", 0, start) + 1
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class CpuWrittenSerials(unittest.TestCase):
    def test_texture_lifetime_churn(self):
        source = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
        declaration = next(line for line in source.splitlines() if line.startswith("static ") and " g_cpuw" in line)
        code = '''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
#include "nvn_hmap.h"
static pthread_mutex_t g_tmu = PTHREAD_MUTEX_INITIALIZER;
''' + declaration + "\n" + "\n".join(function(source, n) for n in ("hslot", "cpuw_take", "vka_cap_cpuw")) + '''
int main(void) {
    uint64_t keys[256] = {0};
    for (uint64_t serial = 1, found = 0; found < 256; serial++) {
        size_t bucket = hslot(serial, 256);
        if (!keys[bucket]) { keys[bucket] = serial; found++; }
    }
    // This leaves every slot deleted in the old table while live count is 0.
    // Texture destruction must return even when its serial was never written.
    for (int i = 0; i < 256; i++) {
        assert(!cpuw_take(keys[i], 1));
        assert(cpuw_take(keys[i], 0));
    }
    fputs("all 256 original buckets have seen a removed texture\\n", stderr);
    assert(!cpuw_take(UINT64_C(10000000), 0));
    assert(!vka_cap_cpuw(UINT64_C(10000000)));
    for (int round = 0; round < 50; round++) {
        for (uint64_t i = 1; i <= 4096; i++) {
            uint64_t serial = (uint64_t)round * 10000 + i;
            assert(!cpuw_take(serial, 1));
            assert(cpuw_take(serial, 1));
            assert(vka_cap_cpuw(serial));
        }
        for (uint64_t i = 2; i <= 4096; i += 2)
            assert(cpuw_take((uint64_t)round * 10000 + i, 0));
        for (uint64_t i = 1; i <= 4096; i++) {
            uint64_t serial = (uint64_t)round * 10000 + i;
            assert(vka_cap_cpuw(serial) == (i % 2 == 1));
            assert(cpuw_take(serial, 0) == (i % 2 == 1));
        }
    }
    puts("CPU-written serial churn passed: 205056 texture lifetimes, membership and duplicate checks");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            src = work / "serials.c"
            src.write_text(code)
            exe = work / "serials"
            compiler = shutil.which("clang") or shutil.which("gcc")
            self.assertIsNotNone(compiler)
            subprocess.run([
                compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Werror",
                "-fsanitize=address,undefined", "-pthread",
                "-I" + str(ROOT / "dm/gfx/nvn"), str(src), "-o", str(exe),
            ], check=True)
            env = os.environ.copy()
            env["ASAN_OPTIONS"] = "detect_leaks=0"
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("205056 texture lifetimes", result.stdout)


if __name__ == "__main__":
    unittest.main()
