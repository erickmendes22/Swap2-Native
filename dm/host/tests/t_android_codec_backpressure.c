// CPU-only regression for AV1 codec backpressure deadlock avoidance.
#include "../hle_codec_backpressure.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    // The movie clock blocks a released but not acquired output picture
    // until the platform AV1 decoder's queue is completely saturated.
    for (int held = 0; held < 8; held++)
        assert(!cv_backpressure_escape(1, held, 8, 1, 1, 1, 1, 1));
    assert(cv_backpressure_escape(1, 8, 8, 1, 1, 1, 1, 1));
    assert(cv_backpressure_escape(1, 10, 8, 1, 1, 1, 1, 1));
    // No other codec changes its original acquisition/clock ordering.
    assert(!cv_backpressure_escape(0, 8, 8, 1, 1, 1, 1, 1));
    // No waiting consumer buffer, no available buffer, or an already
    // acquired buffer: no unsafe delivery is forced.
    assert(!cv_backpressure_escape(1, 8, 8, 0, 1, 1, 1, 1));
    assert(!cv_backpressure_escape(1, 8, 8, 1, 0, 1, 1, 1));
    assert(!cv_backpressure_escape(1, 8, 8, 1, 1, 0, 1, 1));
    // Normal movie clock disabled or explicit escape opt-out.
    assert(!cv_backpressure_escape(1, 8, 8, 1, 1, 1, 0, 1));
    assert(!cv_backpressure_escape(1, 8, 8, 1, 1, 1, 1, 0));
    puts("t_android_codec_backpressure: passed");
    return 0;
}
