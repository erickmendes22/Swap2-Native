// SPDX-License-Identifier: GPL-3.0-or-later
// Device-log-grounded Ocarina direct zero-vertex draw elision.
// The Nov 17 720p capture includes EXACTLY two color+depth passes each
// containing one nonindirect draw with vertex/index count 0. Vulkan runs
// zero vertex/fragment invocations; the empty pass may still consume tiler
// attachment load/store time. Never skip pending clears, a started pass,
// indirect counts, unknown shader pairs, or different target shapes.
//
// An Ocarina-only opt-in A/B: no code path changes without the env switch.
// Predicate stays pure C for sanitizer and exhaustive guard tests.
#pragma once
#include <stdint.h>
#include <string.h>

typedef struct {
    const char *game;
    uint64_t vertex_key, fragment_key;
    int32_t count;
    uint64_t indirect, multidraw_count;
    uint32_t width, height;
    int color, depth, pass_open, pending_clears, transform_feedback, enabled;
} vka_zero_draw_case;

static inline int vka_oot_zero_draw_elide(const vka_zero_draw_case *c) {
    if (!c || !c->enabled || !c->game ||
        strcmp(c->game, "0400486024DEC000") ||
        c->count != 0 || c->indirect || c->multidraw_count ||
        c->width != 1280 || c->height != 720 ||
        !c->color || !c->depth || c->pass_open ||
        c->pending_clears || c->transform_feedback)
        return 0;
    // Exact VS/FS pairs observed independently in frames 1201, 1501, 1801.
    // The predicate must not become a fragment-key-only broad scene skip.
    return (c->vertex_key == UINT64_C(0xe5081d9aa59e1088) &&
            c->fragment_key == UINT64_C(0x087ef21b3a72ad3a)) ||
           (c->vertex_key == UINT64_C(0xf0d90ece8ba1aa59) &&
            c->fragment_key == UINT64_C(0x0fb4823639295a2d));
}
