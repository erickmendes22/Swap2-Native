// AV1 decoded-picture queue escape, no Android/host dependencies.
// A deadlocked intro can have a full producer queue while all released
// consumer buffers are still queued for Acquire. To break backpressure,
// permit exactly one early delivery, but only on saturated AV1 streams;
// the normal movie clock remains unchanged for VP8/VP9/H.264 and AV1
// when its queue is below capacity. This policy is unit-tested on Linux.
#ifndef DM_HLE_CODEC_BACKPRESSURE_H
#define DM_HLE_CODEC_BACKPRESSURE_H
static inline int cv_backpressure_escape(int is_av1, int held, int max_hold,
                                         int free_buffers, int pending,
                                         int pending_queued, int clock,
                                         int enabled) {
    return enabled && clock && pending_queued && is_av1
        && held >= max_hold && free_buffers > 0 && pending > 0;
}
#endif
