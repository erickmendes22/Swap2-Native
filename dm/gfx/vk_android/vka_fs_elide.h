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

// The translator injects an optional alpha test before each return:
//    is_fn = (dm_alpha_func == N); pass = select(is_fn, cmp, pass);
//    SelectionMerge(ok); BranchConditional(pass, ok, kill);
//    Label(kill); Kill; Label(ok).
// When the pipeline does not specialize alpha_func, its SpecId=1 default
// zero makes all is_fn false and pass true. Verify the actual SPIR-V control
// dependence instead of assuming every ALPHA_TEST flag is safe. Reject other
// kills, unknown branches into kill labels and all specializations other than
// default zero. Does not modify SPIR-V bytes or guest-visible depth/query.
static inline int vka_spv_alpha_disabled_kills_dead(const uint32_t *w, size_t nw) {
    if (!w || nw < 6 || w[0] != UINT32_C(0x07230203) ||
        !w[3] || w[3] > 1048576u) return 0;
    const uint32_t bound = w[3];
    uint32_t spec=0, seen=0, good=0, lastmerge=0;
    uint8_t *known = calloc(bound, 1), *incoming = calloc(bound, 1),
            *safe = calloc(nw, 1);
    uint32_t *value = calloc(bound, 4);
    if (!known || !incoming || !safe || !value) goto fail;
    // Decorations come before declarations; collect only the translator's
    // specialization constant ID 1 and inspect all CFG edges to kill labels.
    for (size_t p=5; p<nw;) {
        uint32_t n=w[p]>>16, op=w[p]&0xffffu;
        if (!n || n>nw-p) goto fail;
        const uint32_t *a=w+p;
        if (op==71 && n==4 && a[2]==1 && a[3]==1) {
            if (spec && spec!=a[1]) goto fail;
            spec=a[1];
        }
        if (op==249 && n==2 && a[1]<bound)
            incoming[a[1]] = incoming[a[1]]<2 ? incoming[a[1]]+1 : 2;
        if (op==250 && n==4) {
            if (a[2]>=bound || a[3]>=bound) goto fail;
            if (incoming[a[2]]<2) incoming[a[2]]++;
            if (incoming[a[3]]<2) incoming[a[3]]++;
        }
        if (op==251 && n>=3) {
            if (a[2]>=bound) goto fail;
            if (incoming[a[2]]<2) incoming[a[2]]++;
            for (uint32_t j=4;j<n;j+=2) {
                if (a[j]>=bound) goto fail;
                if (incoming[a[j]]<2) incoming[a[j]]++;
            }
        }
        p+=n;
    }
    if (!spec || spec>=bound) goto fail;
    for (size_t p=5;p<nw;) {
        uint32_t n=w[p]>>16, op=w[p]&0xffffu;
        if (!n || n>nw-p) goto fail;
        const uint32_t *a=w+p;
        // Infer only constants needed to prove the injected alpha branch.
        if ((op==41 || op==42) && n==3 && a[2]<bound) {
            known[a[2]]=1; value[a[2]]=(op==41);
        }
        if (op==43 && n==4 && a[2]<bound) {
            known[a[2]]=1; value[a[2]]=a[3];
        }
        if (op==50 && n==4 && a[2]==spec && a[3]==0) {
            known[spec]=1; value[spec]=0;
        }
        if (op==170 && n==5 && a[2]<bound && a[3]<bound && a[4]<bound &&
            known[a[3]] && known[a[4]]) {
            known[a[2]]=1; value[a[2]]=(value[a[3]]==value[a[4]]);
        }
        if (op==169 && n==6 && a[2]<bound && a[3]<bound &&
            a[4]<bound && a[5]<bound && known[a[3]]) {
            uint32_t src=value[a[3]] ? a[4] : a[5];
            if (known[src]) { known[a[2]]=1; value[a[2]]=value[src]; }
        }
        if (op==247 && n==3) lastmerge=a[1];
        else if (op==250 && n==4 && a[1]<bound && known[a[1]] &&
                 value[a[1]]==1 && lastmerge==a[2] && a[3]<bound &&
                 incoming[a[3]]==1) {
            // Exact fall-through-less generated kill block:
            // BranchConditional true_label kill_label; Label kill; Kill;
            // Label true. No other branch anywhere may enter the kill.
            size_t p1=p+n;
            if (p1+2<nw && w[p1]==((2u<<16)|248u) && w[p1+1]==a[3]) {
                size_t p2=p1+2;
                if (p2<nw && w[p2]==((1u<<16)|252u)) {
                    size_t p3=p2+1;
                    if (p3+2<=nw && w[p3]==((2u<<16)|248u) &&
                        w[p3+1]==a[2]) safe[p2]=1;
                }
            }
            lastmerge=0;
        } else lastmerge=0;
        if (op==252) {
            seen++;
            if (!safe[p]) goto fail;
            good++;
        }
        p+=n;
    }
    free(known);free(incoming);free(safe);free(value);
    return good==seen && seen>0;
fail:
    free(known);free(incoming);free(safe);free(value);
    return 0;
}

static inline int vka_spv_pure_fragment_output_alpha(const uint32_t *w, size_t nw, int alpha_disabled) {
    // The only admitted killed fragment is a compiler-injected alpha test
    // proved dead for SpecId=1's unspecialized zero default.
    const int dead_alpha_kills = alpha_disabled && vka_spv_alpha_disabled_kills_dead(w,nw);
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
                   (op >= 218 && op <= 222) ||
                   (op == 252 && !dead_alpha_kills)) {
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

static inline int vka_spv_pure_fragment_output(const uint32_t *w, size_t nw) {
    return vka_spv_pure_fragment_output_alpha(w,nw,0);
}
