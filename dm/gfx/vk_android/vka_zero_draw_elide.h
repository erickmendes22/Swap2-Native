// SPDX-License-Identifier: GPL-3.0-or-later
// Direct zero-count raster draws have zero shader invocations and no
// attachment or shader writes. Skipping the *draw* is safe regardless of
// an existing render pass or deferred clears. Those operations are preserved
// by the normal command stream and are NEVER discarded here.
//
// Do not apply to GPU-indirect or multi-draw-count commands: the GPU may
// supply a nonzero count. Mesh draws have their own early-zero path.
#pragma once
#include <stdint.h>

typedef struct {
    int enabled, mesh;
    int32_t count;
    uint64_t indirect, multidraw_count;
} vka_zero_direct_case;

static inline int vka_oot_zero_direct_draw(const vka_zero_direct_case *c) {
    return c && c->enabled && !c->mesh &&
        c->count == 0 && !c->indirect && !c->multidraw_count;
}
