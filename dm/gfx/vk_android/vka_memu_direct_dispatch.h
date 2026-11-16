// Small direct-dispatch fast path for GPU-emulated Ocarina taskless mesh draws.
// The control/setup pass still owns arena allocation and R_TOTAL; the converted
// shader compares flat workgroup ID with R_TOTAL before accessing outputs.
// Never bypass GPU-generated counts, task distribution, or oversized grids.
#pragma once
#include <stdint.h>
static inline uint32_t vka_memu_direct_groups(
        int ocarina, int enabled, int has_task, int indirect,
        uint32_t requested, uint32_t max_groups, uint32_t arena_words,
        uint32_t vertex_stride, uint32_t primitive_stride, int interleaved) {
    if (!ocarina || !enabled || has_task || indirect ||
        !requested || requested > 64u || !max_groups ||
        requested > max_groups) return 0;
    uint64_t words = (uint64_t)vertex_stride +
                     (interleaved ? 0ull : primitive_stride);
    if (!words || (uint64_t)requested * words > arena_words) return 0;
    return requested;
}
