"""Validate the opt-in fragment bitmap cache against the existing SPIR-V rewriter.

This is a compile/SPIR-V-structure test, not a GPU timing or visual-parity test.
The shader deliberately reads the same dynamic texture ID twice.  The cache
must preserve the atomic feedback path for cache misses and leave OFF unchanged.
"""
import os
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
HDR = ROOT / "dm/gfx/vk_android/vka_spvpatch.h"
SRC = ROOT / "dm/gfx/vk_android/vka_spvpatch.c"
TEX = ROOT / "dm/gfx/vk_android/vka_tex.c"

FRAG = r"""
#version 460
#extension GL_EXT_nonuniform_qualifier : require
layout(set=0, binding=0) uniform texture2D texture_pool[16];
layout(set=0, binding=1) uniform sampler source_sampler;
layout(push_constant) uniform Parameters { int texture_id; } parameters;
layout(location=0) in vec2 uv;
layout(location=0) out vec4 out_colour;
void main() {
    int id = parameters.texture_id;
    vec4 a = texture(sampler2D(texture_pool[nonuniformEXT(id)], source_sampler), uv);
    vec4 b = texture(sampler2D(texture_pool[nonuniformEXT(id)], source_sampler), uv + vec2(0.1, 0.0));
    out_colour = a + b;
}
"""

HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include "vka_spvpatch.h"
static int transform(const uint32_t *input, size_t count, const char *dst, unsigned flags) {
    size_t n = 0; int sites = 0, early = 0;
    char err[512] = "";
    uint32_t *words = vka_spv_pool_fb(input, count, 0, 0, 2, 0,
       flags, 0, &n, &sites, &early, err, sizeof err);
    if (!words || sites < 2) {
        fprintf(stderr, "rewrite rejected: sites=%d (%s)\n", sites, err);
        free(words); return 0;
    }
    FILE *out = fopen(dst, "wb");
    int good = out && fwrite(words, 4, n, out) == n;
    if (out) fclose(out);
    printf("flags=%u sites=%d words=%zu early=%d\n", flags, sites, n, early);
    free(words); return good;
}
int main(int argc, char **argv) {
    if (argc != 4) return 1;
    FILE *file = fopen(argv[1], "rb");
    if (!file) return 2;
    fseek(file, 0, SEEK_END); long length = ftell(file); rewind(file);
    if (length <= 20 || length % 4) { fclose(file); return 3; }
    uint32_t *input = malloc(length);
    if (!input) { fclose(file); return 4; }
    if (fread(input, 1, length, file) != (size_t)length) {
        free(input); fclose(file); return 5;
    }
    fclose(file);
    int ok = transform(input, length / 4, argv[2], 0) &&
             transform(input, length / 4, argv[3], VKA_PFB_INVOCATION_CACHE);
    free(input);
    return ok ? 0 : 6;
}
"""

def ops(path):
    data = pathlib.Path(path).read_bytes()
    words = struct.unpack("<%dI" % (len(data)//4), data)
    counts = {}
    for i in range(5, len(words)):
        pass
    i=5
    while i<len(words):
        n=words[i]>>16
        if not n or i+n>len(words):
            raise AssertionError("invalid SPIR-V instruction layout")
        op=words[i]&65535
        counts[op]=counts.get(op,0)+1
        i+=n
    return counts

class CacheValidation(unittest.TestCase):
    def test_fragment_cache_rewriter_validates_and_is_opt_in(self):
        for name in ("glslangValidator", "spirv-val", "cc"):
            self.assertIsNotNone(shutil.which(name), name+" is required")
        self.assertIn('VKA_ENV("DM_VK_OOT_FB_INVOCATION_CACHE", 0)', TEX.read_text())
        self.assertIn("VKA_PFB_INVOCATION_CACHE = 4", HDR.read_text())
        with tempfile.TemporaryDirectory() as temp:
            d=pathlib.Path(temp)
            source=d/"cache.frag"
            source.write_text(FRAG)
            spv=d/"original.spv"; base=d/"base.spv"; cache=d/"cache.spv"
            exe=d/"rewrite"
            subprocess.run(["glslangValidator","-V","--target-env","vulkan1.3",
                            "-o",str(spv),str(source)],check=True)
            (d/"rewrite.c").write_text(HARNESS)
            subprocess.run(["cc","-std=c11","-O1","-g","-Wall","-Wextra",
                            "-fsanitize=address,undefined",
                            "-I",str(SRC.parent),str(d/"rewrite.c"),str(SRC),"-o",str(exe)],
                           check=True)
            env=os.environ.copy(); env["ASAN_OPTIONS"]="detect_leaks=0"
            subprocess.run([str(exe),str(spv),str(base),str(cache)],check=True,env=env)
            for path in (spv,base,cache):
                subprocess.run(["spirv-val","--target-env","vulkan1.3",str(path)],
                               check=True)
            a=ops(base); b=ops(cache)
            # The same feedback atomics exist, but repeat IDs can short-circuit them.
            self.assertGreaterEqual(a.get(241,0), 2)
            self.assertEqual(a.get(241,0), b.get(241,0))
            self.assertGreater(b.get(247,0), a.get(247,0)) # conditional merges
            self.assertGreater(b.get(59,0), a.get(59,0))  # one Private variable

if __name__ == "__main__":
    unittest.main()
