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

// NVN sample counters are cumulative within a reset epoch. If reports A
// and B are in that SAME epoch, A==B iff no samples (including lost reports)
// were generated BETWEEN A.end and B.end. B is normally NOT fresh; requiring
// two 'fresh' reports excludes this most common exact pair.
//
// This admits ONLY query sequences that began in the CURRENT Vulkan
// submission. Cross-submission queries must NEVER be copied here: the prior
// completion callback may host-reset their query pool slots before our
// next GPU submission reads them. No previous-frame visibility is assumed.
typedef struct { uint64_t begin, end, lost_delta; } vka_rc_gpu_delta;
static inline int vka_rc_gpu_delta_pair(
    int kind_a, int kind_b, uint64_t epoch_a, uint64_t epoch_b,
    uint64_t fence_a, uint64_t fence_b,
    uint64_t lost_a, uint64_t lost_b,
    uint64_t end_a, uint64_t end_b,
    uint64_t submission_first, uint64_t head,
    vka_rc_gpu_delta *out) {
    if (!out || kind_a != 3 || kind_b != 3 ||
        !epoch_a || epoch_a != epoch_b || fence_a || fence_b ||
        lost_b < lost_a || end_a < submission_first ||
        end_b < end_a || end_b > head ||
        end_b - end_a > VKA_RC_GPU_MAX_RANGE)
        return 0;
    *out = (vka_rc_gpu_delta){end_a, end_b, lost_b - lost_a};
    return 1;
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

// Immutable archived Vulkan-query eligibility for GPU-side occlusion decisions.
// The archive is a sequence-numbered ring copied BEFORE host query-pool reset.
// A range must be entirely present, from an earlier submitted command buffer,
// and not overwritten. Never compare positive BOOLEAN counts across resets.
typedef struct {
    uint64_t begin, end, epoch, lost, fence;
    int fresh;
} vka_rc_archive_report;
typedef struct { int delta; uint64_t begin, end, lost; } vka_rc_archive_pair;
static inline int vka_rc_archive_pair_valid(
    vka_rc_archive_report a, vka_rc_archive_report b,
    uint64_t oldest, uint64_t archived_end, uint64_t submission_first,
    vka_rc_archive_pair *out) {
    if (!out || !a.fence || !b.fence || !a.epoch || !b.epoch ||
        a.begin > a.end || b.begin > b.end ||
        a.begin < oldest || b.begin < oldest ||
        a.end > archived_end || b.end > archived_end ||
        a.end > submission_first || b.end > submission_first ||
        a.end - a.begin > VKA_RC_GPU_MAX_RANGE ||
        b.end - b.begin > VKA_RC_GPU_MAX_RANGE) return 0;
    if (a.epoch == b.epoch) {
        if (b.end < a.end || b.lost < a.lost ||
            b.end - a.end > VKA_RC_GPU_MAX_RANGE) return 0;
        *out = (vka_rc_archive_pair){1, a.end, b.end, b.lost - a.lost};
        return 1;
    }
    // Independent fresh report values: the checked-in shader leaves two
    // positive non-precise counters visible, rather than guessing equality.
    if (!a.fresh || !b.fresh) return 0;
    *out = (vka_rc_archive_pair){0, 0, 0, 0};
    return 1;
}
