// Eligibility for exact GPU counters owned by the current submission.
#pragma once
#include <stdint.h>
enum { VKA_RC_GPU_MAX_JOBS = 128, VKA_RC_GPU_MAX_QUERIES = 4096, VKA_RC_GPU_MAX_RANGE = 256 };
static inline int vka_rc_gpu_range(int kind, int fresh, uint64_t fence, uint64_t lost,
                                  uint64_t begin, uint64_t end, uint64_t submission_begin, uint64_t head) {
    // A fresh report starts with zero: its segment sum plus lost draws is the
    // complete64-bit counter. Non-fresh cumulative reports need an older prefix.
    return kind == 3 && fresh && !fence && !lost && begin >= submission_begin &&
           end >= begin && end <= head && end - begin <= VKA_RC_GPU_MAX_RANGE;
}

// The game's occlusion test compares two cumulative counter reports.
// For reports from the SAME reset epoch, their difference is exactly the
// sum of the queries issued between their endpoints. The older prefix
// cancels, so neither report needs to be fresh. Both reports must still be
// in the current submission, have unchanged guest addresses and identical
// counts of lost queries. Query slots remain fenced until copied.
//
// With Ocarina's Boolean queries the interval can only be classified as
// zero or nonzero; that is precisely what its render condition needs.
// This gate must not be used for arbitrary numeric-counter comparisons.
static inline int vka_rc_gpu_delta_range(
    int kind_a, int kind_b,
    uint64_t epoch_a, uint64_t epoch_b,
    uint64_t fence_a, uint64_t fence_b,
    uint64_t lost_a, uint64_t lost_b,
    uint64_t end_a, uint64_t end_b,
    uint64_t submission_begin, uint64_t head) {
    return kind_a == 3 && kind_b == 3 &&
           epoch_a == epoch_b && !fence_a && !fence_b &&
           lost_a == lost_b &&
           vka_rc_gpu_range(3, 1, 0, 0, end_a, end_b,
                            submission_begin, head);
}

typedef struct { uint64_t begin, end; uint32_t offset; } vka_rc_gpu_qrange;
typedef struct { uint32_t first, count, offset; } vka_rc_gpu_copy;
typedef struct {
    unsigned ranges, copies, total;
    vka_rc_gpu_qrange range[VKA_RC_GPU_MAX_JOBS * 2];
    vka_rc_gpu_copy copy[VKA_RC_GPU_MAX_JOBS * 4];
} vka_rc_gpu_plan;
// Deduplicate immutable query ranges and merge contiguous physical pool copies.
static inline int vka_rc_gpu_plan_add(vka_rc_gpu_plan *p, uint64_t begin, uint64_t end,
                                      uint32_t ring, uint32_t *offset) {
    if (ring < VKA_RC_GPU_MAX_RANGE || p->ranges > VKA_RC_GPU_MAX_JOBS * 2 ||
        p->copies > VKA_RC_GPU_MAX_JOBS * 4 || p->total > VKA_RC_GPU_MAX_QUERIES || end < begin || end - begin > VKA_RC_GPU_MAX_RANGE) return 0;
    if (begin == end) { *offset = 0; return 1; }
    for (unsigned i = 0; i < p->ranges; i++) if (p->range[i].begin == begin && p->range[i].end == end) {
        *offset = p->range[i].offset; return 1;
    }
    uint32_t count = (uint32_t)(end - begin);
    if (p->ranges >= VKA_RC_GPU_MAX_JOBS * 2 || count > VKA_RC_GPU_MAX_QUERIES - p->total ||
        p->copies > VKA_RC_GPU_MAX_JOBS * 4 - 2) return 0;
    *offset = p->total;
    p->range[p->ranges++] = (vka_rc_gpu_qrange){begin, end, *offset};
    for (uint64_t q = begin; q < end;) {
        uint32_t slot = (uint32_t)(q % ring), n = (uint32_t)(end - q);
        if (n > ring - slot) n = ring - slot;
        vka_rc_gpu_copy *last = p->copies ? &p->copy[p->copies - 1] : 0;
        if (last && last->first + last->count == slot && last->offset + last->count == p->total)
            last->count += n;
        else p->copy[p->copies++] = (vka_rc_gpu_copy){slot, n, p->total};
        p->total += n; q += n;
    }
    return 1;
}
