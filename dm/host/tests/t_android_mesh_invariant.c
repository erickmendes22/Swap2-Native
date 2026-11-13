// Pure-C regression test for native mesh Position Invariant at runtime.
// Synthetic module checks structural rewrite; a real glslc mesh module is
// accepted as an optional arg and validated with spirv-val by APK CI.
#include "../../gfx/vk_android/vka_spvpatch.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static int failures;
#define CHECK(c, s) do { if (!(c)) { fprintf(stderr, "FAIL: %s\n", s); failures++; } } while (0)
static int invariant(const uint32_t *w, size_t n) {
    for (size_t i = 5; i < n;) {
        size_t len = w[i] >> 16;
        if (!len || i + len > n) return 0;
        if ((w[i] & 65535u) == 72u && len == 4 &&
            w[i+1] == 42u && w[i+2] == 0u && w[i+3] == 18u) return 1;
        i += len;
    }
    return 0;
}
int main(int argc, char **argv) {
    // This deliberately contains just enough SPIR-V annotations for the
    // standalone conservative patcher. Not submitted to Vulkan.
    const uint32_t fake[] = {0x07230203u, 0x00010600u, 0, 50, 0,
        (5u<<16)|72u, 42, 0, 11, 0,
        (2u<<16)|19u, 1};
    size_t n=0; int changed=0; char err[256]="";
    uint32_t *out = vka_spv_mesh_position_invariant(fake,
        sizeof(fake)/4, &n, &changed, err, sizeof err);
    CHECK(out && changed && n == sizeof(fake)/4+4u, "one Position annotation");
    if (out) {
        CHECK(invariant(out,n), "Invariant attached to same Position member");
        CHECK(!memcmp(out,fake,10u*4u), "original annotation preserved");
        CHECK(!vka_spv_mesh_position_invariant(out,n,&n,&changed,err,sizeof err)
              && changed == 0 && !err[0], "idempotent second pass");
        free(out);
    }
    const uint32_t malformed[] = {0x07230203u, 0x00010600u, 0, 50, 0, 0u};
    CHECK(!vka_spv_mesh_position_invariant(malformed,
        sizeof(malformed)/4,&n,&changed,err,sizeof err) && err[0],
        "malformed SPIR-V is refused");
    if (argc == 3) {
        FILE *f=fopen(argv[1],"rb");
        CHECK(f != NULL, "open real mesh sample");
        if (f) {
            fseek(f,0,SEEK_END); long bytes=ftell(f); rewind(f);
            uint32_t *in = bytes>=20 && bytes%4==0 ? malloc((size_t)bytes) : NULL;
            CHECK(in && fread(in,1,(size_t)bytes,f)==(size_t)bytes, "read sample");
            fclose(f);
            if (in) {
                out=vka_spv_mesh_position_invariant(in,(size_t)bytes/4,&n,&changed,err,sizeof err);
                CHECK(out && changed, "real mesh sample Position patched");
                if (out) {
                    FILE *o=fopen(argv[2],"wb");
                    CHECK(o && fwrite(out,4,n,o)==n, "write real mesh sample");
                    if (o) fclose(o);
                    free(out);
                }
                free(in);
            }
        }
    }
    if (failures) return 1;
    puts("mesh Position Invariant tests passed");
    return 0;
}
