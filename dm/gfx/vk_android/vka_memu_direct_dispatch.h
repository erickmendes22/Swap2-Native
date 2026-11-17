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
    // Mode 1 is the 0.1.9 baseline (up to 64 workgroups).
    // Mode 2 is a reversible, opt-in 65..256 trial, only for CPU-known
    // taskless direct draws. Setup still calculates actual R_TOTAL and
    // allocates the arena; the converted shader retains flat < R_TOTAL.
    // Never extend indirect counts or workgroups with a task stage.
    const uint32_t limit = enabled >= 2 ? 256u : 64u;
    if (!ocarina || !enabled || has_task || indirect ||
        !requested || requested > limit || !max_groups ||
        requested > max_groups) return 0;
    uint64_t words = (uint64_t)vertex_stride +
                     (interleaved ? 0ull : primitive_stride);
    if (!words || (uint64_t)requested * words > arena_words) return 0;
    return requested;
}
