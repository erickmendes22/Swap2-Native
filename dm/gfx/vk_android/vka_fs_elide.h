// SPDX-License-Identifier: GPL-3.0-or-later
// Pure, fail-closed SPIR-V predicate for discarding an otherwise unobservable
// fragment stage in depth/occlusion draws. Does NOT rewrite any shader bytes.
// A depth-only draw with a discard, alpha test, FragDepth, SampleMask,
// image/SSBO/atomic write or an unknown extension MUST keep its fragment shader.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

// Only drop an FS if the non-fragment pipeline still computes the same
// depth/stencil/query samples, and every colour write mask is zero.
static inline int vka_oot_fs_elide_state(
    int oot, int enabled, int driver_ok, int raster_discard,
    int has_depth, int sample_count, int a2c, int alpha_test,
    int shader_writes, int transform_feedback, unsigned mask_union) {
    return oot && enabled && driver_ok && !raster_discard &&
           has_depth && sample_count == 1 && !a2c && !alpha_test &&
           !shader_writes && !transform_feedback && !mask_union;
}

static inline int vka_spv_pure_fragment_output(const uint32_t *w, size_t nw) {
    if (!w || nw < 5 || w[0] != UINT32_C(0x07230203) ||
        !w[3] || w[3] > 1048576u) return 0;
    const uint32_t bound = w[3];
    // ptr: 1 output, 2 private/function scratch, 0 unknown/external.
    unsigned char *ptr = calloc(bound, 1), *built = calloc(bound, 1);
    if (!ptr || !built) { free(ptr); free(built); return 0; }
    uint32_t ext_glsl = 0;
    int entry = 0, ok = 0;
    for (size_t p = 5; p < nw;) {
        uint32_t n = w[p] >> 16, op = w[p] & 0xffffu;
        const uint32_t *a = w + p;
        if (!n || n > nw-p || op > 1000u) goto done;
        if (op == 15) { // one fragment entry point only
            if (n < 5 || a[1] != 4 || entry++) goto done;
        } else if (op == 16) { // OriginUpperLeft or EarlyFragmentTests
            if (n < 3 || (a[2] != 7 && a[2] != 9)) goto done;
        } else if (op == 11) { // GLSL.std.450 is math, not a storage effect
            if (n < 4 || a[1] >= bound) goto done;
            const char *s = (const char *)(a+2);
            size_t sz = (size_t)(n-2)*4;
            const char *end = memchr(s, 0, sz);
            if (end && (size_t)(end-s) == 12 &&
                !memcmp(s, "GLSL.std.450", 12)) ext_glsl = a[1];
        } else if (op == 12) {
            if (n < 5 || !ext_glsl || a[3] != ext_glsl) goto done;
        } else if (op == 71 && n >= 4 && a[2] == 11) {
            if (a[1] >= bound) goto done;
            built[a[1]] = 1; // built-in fragment output may alter coverage
        } else if (op == 72 && n >= 4 && a[3] == 11) {
            goto done; // struct BuiltIn, possibly FragDepth/SampleMask
        } else if (op == 59) { // variable storage class
            if (n < 4 || a[2] >= bound) goto done;
            if (a[3] == 3) ptr[a[2]] = 1;
            else if (a[3] == 4 || a[3] == 6 || a[3] == 7) ptr[a[2]] = 2;
        } else if (op == 65 || op == 66 || op == 67 || op == 70) {
            if (n < 5 || a[2] >= bound || a[3] >= bound) goto done;
            ptr[a[2]] = ptr[a[3]];
        } else if (op == 83) { // CopyObject of a pointer
            if (n != 4 || a[2] >= bound || a[3] >= bound) goto done;
            ptr[a[2]] = ptr[a[3]];
        } else if (op == 62) { // Only outputs and local scratch are writable
            if (n < 3 || a[1] >= bound || !ptr[a[1]]) goto done;
        } else if (op == 63 || op == 64 || op == 99 ||
                   op == 224 || op == 225 ||
                   (op >= 227 && op <= 244) ||
                   (op >= 218 && op <= 222) || op == 252) {
            goto done; // copies, image writes, barriers, atomics or kill
        }
        p += n;
    }
    if (entry != 1) goto done;
    for (uint32_t i = 0; i < bound; i++)
        if (built[i] && ptr[i] == 1) goto done;
    ok = 1;
done:
    free(ptr); free(built);
    return ok;
}
