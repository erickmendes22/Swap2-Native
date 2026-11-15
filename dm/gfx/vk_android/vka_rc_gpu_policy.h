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
