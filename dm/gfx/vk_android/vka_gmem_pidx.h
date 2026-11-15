// Optional bounded GPU page-to-pool index for raw guest-memory lookups.
// Each index is an immutable snapshot in the submission's fence-retired scratch
// buffer, appended after the existing 8192 x 32-byte GMEM table. Old shaders
// read the original table unchanged; unindexed pages use its binary search.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum { VKA_GMEM_PIDX_HEADER_WORDS = 4, VKA_GMEM_PIDX_PAGE_SHIFT = 12 };
// Header: [base page (low 32), record count, 0, 0]; record: segment index
// (one-based, matching the original sorted table), zero means search fallback.
// Only guest pages below 2^32 page numbers and wholly inside a placed
// segment are admitted. No device addresses are cached in the index.
static inline size_t vka_gmem_pidx_build(uint32_t *dst, size_t words,
        const uint64_t *lo, const uint64_t *hi, int n) {
    if (!dst || words < VKA_GMEM_PIDX_HEADER_WORDS) return 0;
    memset(dst, 0, words * sizeof *dst);
    if (!lo || !hi || n <= 0 || n >= 8192) return 0;
    // A mapping overlap would make a page's owner ambiguous: leave the
    // header empty, so every lookup uses the original sorted-table search.
    for (int i = 0; i < n; i++)
        if (hi[i] <= lo[i] || (i && lo[i] < hi[i - 1])) return 0;
    const uint64_t guest_page_limit = UINT64_C(1) << 32;
    uint64_t base = guest_page_limit;
    for (int i = 0; i < n; i++) {
        uint64_t start = (lo[i] >> 12) + !!(lo[i] & 4095u);
        uint64_t stop = hi[i] >> 12;
        if (start < stop && start < guest_page_limit) {
            base = start;
            break;
        }
    }
    if (base == guest_page_limit) return 0;
    uint64_t capacity = words - VKA_GMEM_PIDX_HEADER_WORDS;
    if (capacity > guest_page_limit - base) capacity = guest_page_limit - base;
    if (!capacity) return 0;
    uint64_t end = base + capacity, covered = 0;
    for (int i = 0; i < n; i++) {
        uint64_t a = (lo[i] >> 12) + !!(lo[i] & 4095u);
        uint64_t z = hi[i] >> 12;
        if (a < base) a = base;
        if (z > end) z = end;
        for (uint64_t page = a; page < z; page++) {
            dst[VKA_GMEM_PIDX_HEADER_WORDS + (size_t)(page - base)] =
                (uint32_t)(i + 1);
            covered++;
        }
    }
    if (!covered) return 0;
    dst[0] = (uint32_t)base;
    dst[1] = (uint32_t)capacity;
    return (size_t)covered;
}
