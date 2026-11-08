// The Android replay's SPIR-V rewrite of vertex inputs fed integer formats (dm/gfx/vk_android/vka_spvpatch.c), on the Mac: the graphics selftest's vertex shader
// (a component read through an access chain at location 0, whole loads at location 1) retyped as uint / int, checked by structure and, when spirv-val is on the PATH,
// by validation. DM_VK_SPV_DIR=<folder of .spv vertex modules> also rewrites each of those (every vec4 input as uint) and validates it. DM_VK_GS_SPV=<a geometry module
// that writes memory> puts its writes under a per-primitive claim (vka_spv_gs_claim, after the one-invocation subgroup rewrite) and validates it. The storage image retype
// (vka_spv_img_retype) runs on t_android_spvpatch_img.h's modules, on every float storage image of format Unknown in DM_VK_SPV_DIR's modules (as uint, then as int)
// and on each of their float sampled images
#include "../../gfx/vk_android/vka_spvpatch.h"
#include "../../gfx/vk_android/vka_selftest_spv.h"
#include "t_android_spvpatch_img.h"
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int g_fail;
#define CHECK(c, ...) do { if (!(c)) { g_fail++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
static int have_val(void) { return system("spirv-val --version >/dev/null 2>&1") == 0; }   // NOLINT(bugprone-command-processor): the test runs spirv-val from the PATH, on fixed arguments
static int validate(const uint32_t *w, size_t n, const char *tag) {
    char path[256]; snprintf(path, sizeof path, "/tmp/t_spvpatch_%d.spv", (int)getpid());
    FILE *f = fopen(path, "wb"); if (!f) return 0; fwrite(w, 4, n, f); fclose(f);
    char cmd[400]; snprintf(cmd, sizeof cmd, "spirv-val --target-env vulkan1.3 %s", path);
    int r = system(cmd); remove(path);   // NOLINT(bugprone-command-processor): spirv-val on the test's own temporary file
    if (r) printf("  spirv-val failed on %s\n", tag);
    return r == 0;
}
// A module file's words (*nw of them), or NULL when it cannot be read whole
static uint32_t *read_spv(const char *p, size_t *nw) {
    *nw = 0;
    FILE *f = fopen(p, "rb"); if (!f) return NULL;
    long sz = fseek(f, 0, SEEK_END) ? -1 : ftell(f);
    uint32_t *w = sz > 0 && !fseek(f, 0, SEEK_SET) ? malloc((size_t)sz) : NULL;
    if (w && fread(w, 1, (size_t)sz, f) != (size_t)sz) { free(w); w = NULL; }
    fclose(f);
    if (w) *nw = (size_t)sz / 4;
    return w;
}
static int count_op(const uint32_t *w, size_t n, uint32_t op) { int k = 0; for (size_t i = 5; i < n; i += w[i] >> 16) { if (!(w[i] >> 16)) break; k += (w[i] & 0xffff) == op; } return k; }
// The instruction defining id among the types and globals (OpType*: id at word 1; OpVariable: word 2), or NULL
static const uint32_t *def_of(const uint32_t *w, size_t n, uint32_t id) {
    for (size_t i = 5; i < n; i += w[i] >> 16) { if (!(w[i] >> 16)) break; uint32_t op = w[i] & 0xffff;
        if (op == 54) break;   // OpFunction
        if ((op >= 19 && op <= 39 && w[i + 1] == id) || (op == 59 && w[i + 2] == id)) return w + i; }
    return NULL;
}
// The set 0 bindings of the module's float storage images of format Unknown (sampled 0), or of its float sampled images (sampled 1: an image of Sampled = 1 or the
// OpTypeSampledImage of one), a variable of one or of an array of them: up to max, their count
static int float_images(const uint32_t *w, size_t n, uint32_t *bind, int max, int sampled) {
    int k = 0;
    for (size_t i = 5; i < n && k < max; i += w[i] >> 16) { if (!(w[i] >> 16) || (w[i] & 0xffff) == 54) break;
        if ((w[i] & 0xffff) != 59 || w[i + 3] != 0) continue;   // OpVariable UniformConstant
        const uint32_t *p = def_of(w, n, w[i + 1]), *t = p && (p[0] & 0xffff) == 32 ? def_of(w, n, p[3]) : NULL;
        if (t && ((t[0] & 0xffff) == 28 || (t[0] & 0xffff) == 29)) t = def_of(w, n, t[2]);
        if (t && sampled && (t[0] & 0xffff) == 27) t = def_of(w, n, t[2]);   // OpTypeSampledImage
        const uint32_t *st = t && (t[0] & 0xffff) == 25 ? def_of(w, n, t[2]) : NULL;
        if (!st || (st[0] & 0xffff) != 22 || t[7] != (sampled ? 1u : 2u) || t[8] != 0) continue;
        uint32_t set = ~0u, b = ~0u;
        for (size_t j = 5; j < n; j += w[j] >> 16) { if (!(w[j] >> 16)) break; if ((w[j] & 0xffff) == 71 && w[j + 1] == w[i + 2]) { if (w[j + 2] == 34) set = w[j + 3]; if (w[j + 2] == 33) b = w[j + 3]; } }
        if (set == 0 && b != ~0u) bind[k++] = b;
    }
    return k;
}
int main(void) {
    int val = have_val();
    size_t n = sizeof SPV_TRI_VERT / 4, on = 0; char err[200] = "";
    uint32_t *o = vka_spv_vin_retype(SPV_TRI_VERT, n, 1, 2, &on, err, sizeof err);
    CHECK(o, "selftest vertex shader not rewritten: %s", err);
    if (o) {
        CHECK(o[3] > SPV_TRI_VERT[3], "bound grows (%u → %u)", SPV_TRI_VERT[3], o[3]);
        CHECK(count_op(o, on, 124) >= count_op(SPV_TRI_VERT, n, 124) + 2, "a bitcast after each load of the two inputs");
        CHECK(count_op(o, on, 21) >= 2, "an int type of each signedness");
        if (val) CHECK(validate(o, on, "selftest vertex"), "valid SPIR-V");
        free(o);
    }
    CHECK(!vka_spv_vin_retype(SPV_TRI_VERT, n, 4, 0, &on, err, sizeof err), "a location the module does not read is refused");
    CHECK(!vka_spv_vin_retype(SPV_TRI_VERT, n, 1, 1, &on, err, sizeof err), "a location both uint and int is refused");
    {   // A float colour output into an integer target (vka_spv_fout_retype): the selftest's fragment shader, its vec4 output at location 0 as uvec4 / ivec4
        size_t fn = sizeof SPV_TRI_FRAG / 4;
        for (int c = 0; c < 2; c++) {
            uint32_t *f = vka_spv_fout_retype(SPV_TRI_FRAG, fn, c ? 0 : 1, c ? 1 : 0, &on, err, sizeof err);
            CHECK(f, "selftest fragment shader output not retyped (%s): %s", c ? "int" : "uint", err);
            if (!f) continue;
            CHECK(count_op(f, on, 124) >= count_op(SPV_TRI_FRAG, fn, 124) + 1, "a bitcast before each store of the output");
            CHECK(count_op(f, on, 21) >= 1, "an integer type");
            if (val) CHECK(validate(f, on, c ? "selftest fragment (int)" : "selftest fragment (uint)"), "valid SPIR-V");
            free(f);
        }
        CHECK(!vka_spv_fout_retype(SPV_TRI_FRAG, fn, 2, 0, &on, err, sizeof err), "a location the module does not write is refused");
        CHECK(!vka_spv_fout_retype(SPV_TRI_FRAG, fn, 1, 1, &on, err, sizeof err), "a location both uint and int is refused");
    }
    {   // Formatted storage images bound to integer textures (vka_spv_img_retype)
        size_t n1 = sizeof SPV_IMG_M1 / 4, n2 = sizeof SPV_IMG_M2 / 4;
        // Binding 1 as R32ui (the module's own R32ui image type is taken, not declared again), the array at binding 2 as int of format Unknown; binding 3 stays float
        vka_spv_imgsel a[2] = {{0, 1, 1, 33}, {0, 2, 2, 0}};
        uint32_t *x = vka_spv_img_retype(SPV_IMG_M1, n1, a, 2, &on, err, sizeof err);
        CHECK(x, "M1 bindings 1 (R32ui) and 2 (int) not retyped: %s", err);
        if (x) {
            CHECK(count_op(x, on, 25) == count_op(SPV_IMG_M1, n1, 25) + 1, "one new image type (%d, was %d)", count_op(x, on, 25), count_op(SPV_IMG_M1, n1, 25));
            CHECK(count_op(x, on, 124) == count_op(SPV_IMG_M1, n1, 124) + 4, "a bitcast for each of the two reads and two writes (%d)", count_op(x, on, 124));
            CHECK(count_op(x, on, 17) == count_op(SPV_IMG_M1, n1, 17), "no capability added for R32ui");
            if (val) CHECK(validate(x, on, "M1 R32ui + int"), "valid SPIR-V");
            free(x);
        }
        vka_spv_imgsel b[1] = {{0, 1, 1, 39}};   // R8ui: an extended format
        x = vka_spv_img_retype(SPV_IMG_M1, n1, b, 1, &on, err, sizeof err);
        CHECK(x, "M1 binding 1 as R8ui not retyped: %s", err);
        if (x) {
            CHECK(count_op(x, on, 17) == count_op(SPV_IMG_M1, n1, 17) + 1, "StorageImageExtendedFormats added for R8ui");
            if (val) CHECK(validate(x, on, "M1 R8ui"), "valid SPIR-V");
            free(x);
        }
        vka_spv_imgsel r1[1] = {{0, 4, 1, 0}}, r2[1] = {{0, 9, 1, 0}}, r3[1] = {{0, 1, 1, 21}}, r4[2] = {{0, 1, 1, 0}, {0, 1, 2, 0}};
        CHECK(!vka_spv_img_retype(SPV_IMG_M1, n1, r1, 1, &on, err, sizeof err), "an integer image is refused");
        CHECK(!vka_spv_img_retype(SPV_IMG_M1, n1, r2, 1, &on, err, sizeof err), "a binding the module lacks is refused");
        CHECK(!vka_spv_img_retype(SPV_IMG_M1, n1, r3, 1, &on, err, sizeof err), "a signed format for the unsigned class is refused");
        CHECK(!vka_spv_img_retype(SPV_IMG_M1, n1, r4, 2, &on, err, sizeof err), "a binding named twice is refused");
        // A sparse read, in a module without an unsigned type: uint (declared), int (the module's), and R8i
        vka_spv_imgsel m2[3][1] = {{{0, 0, 1, 0}}, {{0, 0, 2, 0}}, {{0, 0, 2, 29}}};
        for (int c = 0; c < 3; c++) {
            x = vka_spv_img_retype(SPV_IMG_M2, n2, m2[c], 1, &on, err, sizeof err);
            CHECK(x, "M2 case %d not retyped: %s", c, err);
            if (!x) continue;
            CHECK(count_op(x, on, 124) == count_op(SPV_IMG_M2, n2, 124) + 2, "a bitcast for the sparse read and the write");
            CHECK(count_op(x, on, 21) == count_op(SPV_IMG_M2, n2, 21) + (c == 0), "the unsigned type declared only for uint");
            CHECK(count_op(x, on, 30) == count_op(SPV_IMG_M2, n2, 30) + 1, "a sparse result struct of the integer texel");
            if (val) { char tag[32]; snprintf(tag, sizeof tag, "M2 case %d", c); CHECK(validate(x, on, tag), "valid SPIR-V"); }
            free(x);
        }
        // An unsigned sampled texture's image type of the same shape (Sampled = 1) is not taken for the storage image: a new one is declared
        size_t n3 = sizeof SPV_IMG_M3 / 4; vka_spv_imgsel m3[1] = {{0, 1, 1, 0}};
        x = vka_spv_img_retype(SPV_IMG_M3, n3, m3, 1, &on, err, sizeof err);
        CHECK(x, "M3 binding 1 as uint not retyped: %s", err);
        if (x) {
            CHECK(count_op(x, on, 25) == count_op(SPV_IMG_M3, n3, 25) + 1, "a storage image type declared beside the sampled one (%d, was %d)", count_op(x, on, 25), count_op(SPV_IMG_M3, n3, 25));
            if (val) CHECK(validate(x, on, "M3 uint"), "valid SPIR-V");
            free(x);
        }
        // Sampled images (TEX / TLD / TLD4 of integer textures): combined at 1 (fetch, sample) as uint, the array at 2 (gather, fetch) as int, the sparse fetch at 3 and the
        // separate image at 5 (OpSampledImage with binding 6's sampler) as uint; binding 7, of binding 1's type, stays float
        size_t n4 = sizeof SPV_IMG_M4 / 4;
        vka_spv_imgsel m4[4] = {{0, 1, 1, 0}, {0, 2, 2, 0}, {0, 3, 1, 0}, {0, 5, 1, 0}};
        x = vka_spv_img_retype(SPV_IMG_M4, n4, m4, 4, &on, err, sizeof err);
        CHECK(x, "M4 sampled bindings 1, 2, 3, 5 not retyped: %s", err);
        if (x) {
            CHECK(count_op(x, on, 25) == count_op(SPV_IMG_M4, n4, 25) + 2, "a uint and an int sampled image type (%d, was %d)", count_op(x, on, 25), count_op(SPV_IMG_M4, n4, 25));
            CHECK(count_op(x, on, 27) == count_op(SPV_IMG_M4, n4, 27) + 2, "their two sampled image types (%d, was %d)", count_op(x, on, 27), count_op(SPV_IMG_M4, n4, 27));
            CHECK(count_op(x, on, 124) == count_op(SPV_IMG_M4, n4, 124) + 6, "a bitcast for each of the two fetches, two samples, the gather and the sparse fetch (%d)", count_op(x, on, 124));
            CHECK(count_op(x, on, 30) == count_op(SPV_IMG_M4, n4, 30) + 1, "a sparse result struct of the integer texel");
            CHECK(count_op(x, on, 17) == count_op(SPV_IMG_M4, n4, 17), "no capability added");
            if (val) CHECK(validate(x, on, "M4 sampled uint + int"), "valid SPIR-V");
            free(x);
        }
        vka_spv_imgsel m4b[2] = {{0, 0, 1, 33}, {0, 1, 1, 0}};   // a storage image (R32ui) and a sampled one (uint) in one rewrite
        x = vka_spv_img_retype(SPV_IMG_M4, n4, m4b, 2, &on, err, sizeof err);
        CHECK(x, "M4 storage binding 0 (R32ui) and sampled binding 1 (uint) not retyped: %s", err);
        if (x) {
            CHECK(count_op(x, on, 25) == count_op(SPV_IMG_M4, n4, 25) + 2, "a storage and a sampled image type (%d)", count_op(x, on, 25));
            CHECK(count_op(x, on, 27) == count_op(SPV_IMG_M4, n4, 27) + 1, "one sampled image type (%d)", count_op(x, on, 27));
            CHECK(count_op(x, on, 124) == count_op(SPV_IMG_M4, n4, 124) + 3, "a bitcast for the write, the fetch and the sample (%d)", count_op(x, on, 124));
            if (val) CHECK(validate(x, on, "M4 storage R32ui + sampled uint"), "valid SPIR-V");
            free(x);
        }
        vka_spv_imgsel m4c[1] = {{0, 7, 2, 0}};   // binding 7 alone as int, binding 1 of the same type left float
        x = vka_spv_img_retype(SPV_IMG_M4, n4, m4c, 1, &on, err, sizeof err);
        CHECK(x, "M4 binding 7 as int not retyped: %s", err);
        if (x) { if (val) CHECK(validate(x, on, "M4 binding 7 int"), "valid SPIR-V"); free(x); }
        vka_spv_imgsel q1[1] = {{0, 4, 1, 0}}, q2[1] = {{0, 1, 1, 33}}, q3[1] = {{0, 6, 1, 0}};
        CHECK(!vka_spv_img_retype(SPV_IMG_M4, n4, q1, 1, &on, err, sizeof err), "a depth comparison is refused");
        CHECK(!vka_spv_img_retype(SPV_IMG_M4, n4, q2, 1, &on, err, sizeof err), "a format for a sampled image is refused");
        CHECK(!vka_spv_img_retype(SPV_IMG_M4, n4, q3, 1, &on, err, sizeof err), "a sampler is refused");
    }
    const char *dir = getenv("DM_VK_SPV_DIR");
    if (dir) {
        DIR *d = opendir(dir); struct dirent *e; int done = 0, refused = 0, idone = 0, irefused = 0, sdone = 0, srefused = 0;
        while (d && (e = readdir(d))) {
            size_t l = strlen(e->d_name); if (l < 4 || strcmp(e->d_name + l - 4, ".spv")) continue;
            char p[1024]; snprintf(p, sizeof p, "%s/%s", dir, e->d_name);
            size_t nw; uint32_t *w = read_spv(p, &nw); if (!w) continue;
            // every Location-decorated input: find them by a first rewrite of all 32 locations, narrowing on refusal
            uint32_t mask = 0;
            for (size_t i = 5; i < nw; i += w[i] >> 16) { if (!(w[i] >> 16)) break; if ((w[i] & 0xffff) == 71 && (w[i] >> 16) >= 4 && i + 3 < nw && w[i + 2] == 30 && w[i + 3] < 32) {
                uint32_t id = w[i + 1]; for (size_t j = 5; j < nw; j += w[j] >> 16) { if (!(w[j] >> 16)) break; if ((w[j] & 0xffff) == 59 && (w[j] >> 16) >= 4 && j + 3 < nw && w[j + 2] == id && w[j + 3] == 1) mask |= 1u << w[i + 3]; } } }
            uint32_t *x = mask ? vka_spv_vin_retype(w, nw, mask, 0, &on, err, sizeof err) : NULL;
            if (!x) { refused++; if (refused <= 4) printf("  %s: %s\n", e->d_name, mask ? err : "no input"); }
            else { done++; if (val) CHECK(validate(x, on, e->d_name), "%s valid", e->d_name); free(x); }
            uint32_t ib[8]; int ni = float_images(w, nw, ib, 8, 0);   // every float storage image of format Unknown, as uint then as int
            for (int c = 1; ni && c <= 2; c++) {
                vka_spv_imgsel s[8]; for (int k = 0; k < ni; k++) s[k] = (vka_spv_imgsel){0, ib[k], (uint8_t)c, 0};
                uint32_t *y = vka_spv_img_retype(w, nw, s, ni, &on, err, sizeof err);
                if (!y) { irefused++; if (irefused <= 4) printf("  %s: storage images as %s: %s\n", e->d_name, c == 1 ? "uint" : "int", err); continue; }
                idone++; if (val) CHECK(validate(y, on, e->d_name), "%s storage images as %s valid", e->d_name, c == 1 ? "uint" : "int"); free(y);
            }
            ni = float_images(w, nw, ib, 8, 1);   // each float sampled image alone, as uint then as int (one a depth comparison reads is refused)
            for (int k = 0; k < ni; k++) for (int c = 1; c <= 2; c++) {
                vka_spv_imgsel s1 = {0, ib[k], (uint8_t)c, 0};
                uint32_t *y = vka_spv_img_retype(w, nw, &s1, 1, &on, err, sizeof err);
                if (!y) { srefused++; if (srefused <= 4) printf("  %s: sampled image %u as %s: %s\n", e->d_name, ib[k], c == 1 ? "uint" : "int", err); continue; }
                sdone++; if (val) CHECK(validate(y, on, e->d_name), "%s sampled image %u as %s valid", e->d_name, ib[k], c == 1 ? "uint" : "int"); free(y);
            }
            free(w);
        }
        if (d) closedir(d);
        printf("t_android_spvpatch: %d modules rewritten, %d refused in %s; storage images retyped in %d, refused in %d; sampled images retyped %d times, refused %d\n",
               done, refused, dir, idone, irefused, sdone, srefused);
    }
    const char *gs = getenv("DM_VK_GS_SPV");
    if (gs) {
        size_t nw; uint32_t *w = read_spv(gs, &nw); CHECK(w, "%s not readable", gs);
        if (w) {
            int ch = 0; size_t sn = 0; uint32_t *sg = vka_spv_subgroup_single(w, nw, &sn, &ch, err, sizeof err); if (sg) { free(w); w = sg; nw = sn; }
            int found = vka_spv_gs_claim(w, nw, 255, NULL, NULL, err, sizeof err);
            CHECK(found >= 0, "%s: memory writes counted (%s)", gs, err);
            uint32_t *x = NULL; size_t xn = 0; int r = found > 0 ? vka_spv_gs_claim(w, nw, 255, &x, &xn, err, sizeof err) : -1;
            if (found > 0) CHECK(r == found && x, "claim module made (%s)", err);
            if (x) {
                CHECK(count_op(x, xn, 218) == count_op(w, nw, 218), "emits as before");
                CHECK(count_op(x, xn, 247) == count_op(w, nw, 247) + found, "a selection around each write");
                CHECK(count_op(x, xn, 229) == count_op(w, nw, 229) + 1, "one exchange for the claim");
                if (val) CHECK(validate(x, xn, "gs claim"), "claim module valid");
                free(x);
            }
            printf("t_android_spvpatch: %s: %d memory writes claimed\n", gs, found);
            free(w); }
    }
    printf("t_android_spvpatch: %s%s\n", g_fail ? "FAILED" : "ok", val ? "" : " (no spirv-val: structure only)");
    return g_fail != 0;
}
