// SPDX-License-Identifier: GPL-3.0-or-later
// Runtime variant of the upstream Swap2-Native vk_android_mesh._undefer:
// remove the mesh-plane staging Workgroup copy after validating the exact
// function and two-variable shape. The existing C converter still performs
// the direct Output-to-arena SSBO conversion. Never rewrite the shader library.
#ifndef VKA_MEMU_UNDEFER_H
#define VKA_MEMU_UNDEFER_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
static inline int vka_memu_undefer_hot(uint64_t k) {
    return k == UINT64_C(0xeb021183bf9b0092) ||
           k == UINT64_C(0xfed302d791a4ba43);
}
static inline int vka_memu_u_drop(uint32_t id, const uint32_t f[4],
                                  const uint32_t cv[2]) {
    return id == f[1] || id == f[2] || id == f[3] ||
           id == cv[0] || id == cv[1];
}
static inline int vka_memu_u_name(const uint32_t *p, uint32_t len,
                                  const char *name) {
    if (len < 3) return 0;
    const char *s = (const char *)(p + 2);
    size_t n = (size_t)(len - 2) * 4;
    const char *end = memchr(s, 0, n);
    return end && (size_t)(end - s) == strlen(name) &&
           !memcmp(s, name, strlen(name));
}
static inline int vka_memu_u_valid(const uint32_t *w, size_t nw) {
    if (!w || nw < 6 || w[0] != UINT32_C(0x07230203) || !w[3]) return 0;
    for (size_t p = 5; p < nw;) {
        uint32_t len = w[p] >> 16;
        if (!len || len > nw - p) return 0;
        p += len;
    }
    return 1;
}
static inline uint32_t *vka_memu_undefer(const uint32_t *w, size_t nw,
                                         size_t *new_nw, uint32_t *replaced) {
    static const char *const names[4] = {
        "mesh_plane_store", "mesh_plane_defer", "mesh_plane_flush",
        "mesh_plane_clear"
    };
    uint32_t f[4] = {0}, cv[2] = {0};
    size_t begin[3] = {0}, end[3] = {0};
    uint8_t *wg = NULL;
    uint32_t *out = NULL;
    unsigned calls = 0, drops = 0, nc = 0;
    if (new_nw) *new_nw = 0;
    if (replaced) *replaced = 0;
    if (!vka_memu_u_valid(w, nw) || w[3] > 1000000u) return NULL;
    uint32_t bound = w[3];
    wg = calloc(bound, 1);
    if (!wg) return NULL;
    for (size_t p = 5; p < nw; p += w[p] >> 16) {
        uint32_t op = w[p] & 65535u, len = w[p] >> 16;
        if (op == 5 && len >= 3)
            for (int k = 0; k < 4; k++)
                if (vka_memu_u_name(w + p, len, names[k])) f[k] = w[p + 1];
        if (op == 59 && len >= 4 && w[p+2] < bound && w[p+3] == 4)
            wg[w[p+2]] = 1;
    }
    for (int k = 0; k < 4; k++) if (!f[k] || f[k] >= bound) goto done;
    for (size_t p = 5; p < nw; p += w[p] >> 16) {
        uint32_t op = w[p] & 65535u, len = w[p] >> 16;
        if (op == 54 && len >= 5)
            for (int k = 1; k < 4; k++) if (w[p+2] == f[k]) {
                if (begin[k-1]) goto done;
                begin[k-1] = p;
            }
        if (op == 56)
            for (int k = 0; k < 3; k++)
                if (begin[k] && !end[k]) end[k] = p + len;
    }
    for (int k = 0; k < 3; k++)
        if (!begin[k] || !end[k] || end[k] <= begin[k]) goto done;
    // Only two Workgroup staging variables are permitted in the defer body.
    for (size_t p = begin[0]; p < end[0]; p += w[p] >> 16) {
        uint32_t op = w[p] & 65535u, len = w[p] >> 16;
        if ((op == 65 || op == 66) && len >= 5 &&
            w[p+3] < bound && wg[w[p+3]]) {
            uint32_t id = w[p+3];
            if (id != cv[0] && id != cv[1]) {
                if (nc == 2) goto done;
                cv[nc++] = id;
            }
        }
    }
    if (nc != 2) goto done;
    // Reject unexpected live uses rather than removing a required output.
    for (size_t p = 5; p < nw; p += w[p] >> 16) {
        uint32_t op = w[p] & 65535u, len = w[p] >> 16;
        int removed = 0;
        for (int k = 0; k < 3; k++)
            if (p >= begin[k] && p < end[k]) removed = 1;
        if (removed) continue;
        if (op == 57 && len >= 4) {
            if (w[p+3] == f[1]) calls++;
            if (w[p+3] == f[2] || w[p+3] == f[3]) {
                drops++;
                continue;
            }
        }
        if (op == 15 || op == 5 || op == 6 || op == 71 ||
            op == 72 || op == 59 || op == 5632 || op == 5633) continue;
        for (uint32_t k = 1; k < len; k++)
            if (vka_memu_u_drop(w[p+k], f, cv)) {
                if (op == 57 && k == 3 && w[p+3] == f[1]) continue;
                goto done;
            }
    }
    if (calls < 16 || drops < 2) goto done;
    out = malloc(nw * 4);
    if (!out) goto done;
    memcpy(out, w, 5 * 4);
    size_t o = 5;
    for (size_t p = 5; p < nw; p += w[p] >> 16) {
        uint32_t op = w[p] & 65535u, len = w[p] >> 16;
        int skip = 0;
        for (int k = 0; k < 3; k++)
            if (p >= begin[k] && p < end[k]) skip = 1;
        if (skip) continue;
        if (op == 57 && len >= 4 &&
            (w[p+3] == f[2] || w[p+3] == f[3])) continue;
        if (op == 59 && len >= 4 &&
            (w[p+2] == cv[0] || w[p+2] == cv[1])) continue;
        if ((op == 5 || op == 6 || op == 71 || op == 72 ||
             op == 5632 || op == 5633) && len >= 2 &&
            vka_memu_u_drop(w[p+1], f, cv)) continue;
        if (op == 15 && len >= 4) {
            uint32_t ne = 3;
            while (ne < len) {
                uint32_t v = w[p + ne++];
                if (!(v & 0xff) || !(v & 0xff00) ||
                    !(v & 0xff0000) || !(v & 0xff000000)) break;
            }
            if (ne == len) { free(out); out = NULL; goto done; }
            uint32_t total = ne;
            for (uint32_t k = ne; k < len; k++)
                if (w[p+k] != cv[0] && w[p+k] != cv[1]) total++;
            out[o++] = (total << 16) | op;
            memcpy(out + o, w + p + 1, (ne - 1) * 4);
            o += ne - 1;
            for (uint32_t k = ne; k < len; k++)
                if (w[p+k] != cv[0] && w[p+k] != cv[1])
                    out[o++] = w[p+k];
            continue;
        }
        memcpy(out + o, w + p, len * 4);
        if (op == 57 && len >= 4 && w[p+3] == f[1])
            out[o+3] = f[0];
        o += len;
    }
    if (o >= nw || !vka_memu_u_valid(out, o)) {
        free(out); out = NULL; goto done;
    }
    if (new_nw) *new_nw = o;
    if (replaced) *replaced = calls;
done:
    free(wg);
    return out;
}
#endif
