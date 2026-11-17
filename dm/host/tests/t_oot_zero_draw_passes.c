// SPDX-License-Identifier: GPL-3.0-or-later
// Hardware-log-constrained eligibility, not a GPU speed benchmark.
#include <assert.h>
#include <stdio.h>
#include "../../gfx/vk_android/vka_zero_draw_elide.h"
static vka_zero_draw_case good(uint64_t vs, uint64_t fs) {
    return (vka_zero_draw_case){
        .game="0400486024DEC000", .vertex_key=vs, .fragment_key=fs,
        .count=0, .indirect=0, .multidraw_count=0, .width=1280,
        .height=720, .color=1, .depth=1, .pass_open=0,
        .pending_clears=0, .transform_feedback=0, .enabled=1
    };
}
int main(void) {
    vka_zero_draw_case a=good(UINT64_C(0xe5081d9aa59e1088),UINT64_C(0x087ef21b3a72ad3a));
    vka_zero_draw_case b=good(UINT64_C(0xf0d90ece8ba1aa59),UINT64_C(0x0fb4823639295a2d));
    assert(vka_oot_zero_draw_elide(&a));
    assert(vka_oot_zero_draw_elide(&b));
    // Guards: a changed shader pair, game, mesh/indirect/multidraw,
    // any nonzero count, active renderpass, pending clear, TF, dimensions,
    // or missing target all keep the ORIGINAL draw.
    a.enabled=0;assert(!vka_oot_zero_draw_elide(&a));a.enabled=1;
    a.game="OTHER";assert(!vka_oot_zero_draw_elide(&a));a.game="0400486024DEC000";
    a.vertex_key=b.vertex_key;assert(!vka_oot_zero_draw_elide(&a));a.vertex_key=UINT64_C(0xe5081d9aa59e1088);
    a.fragment_key=b.fragment_key;assert(!vka_oot_zero_draw_elide(&a));a.fragment_key=UINT64_C(0x087ef21b3a72ad3a);
    for (int n=-2; n<=2; n++) {
        if (n != 0) {
            a.count = n;
            assert(!vka_oot_zero_draw_elide(&a));
        }
    }
    a.count = 0;
    a.indirect=1;assert(!vka_oot_zero_draw_elide(&a));a.indirect=0;
    a.multidraw_count=1;assert(!vka_oot_zero_draw_elide(&a));a.multidraw_count=0;
    a.pass_open=1;assert(!vka_oot_zero_draw_elide(&a));a.pass_open=0;
    a.pending_clears=1;assert(!vka_oot_zero_draw_elide(&a));a.pending_clears=0;
    a.transform_feedback=1;assert(!vka_oot_zero_draw_elide(&a));a.transform_feedback=0;
    a.width=960;assert(!vka_oot_zero_draw_elide(&a));a.width=1280;
    a.height=540;assert(!vka_oot_zero_draw_elide(&a));a.height=720;
    a.color=0;assert(!vka_oot_zero_draw_elide(&a));a.color=1;
    a.depth=0;assert(!vka_oot_zero_draw_elide(&a));a.depth=1;
    assert(!vka_oot_zero_draw_elide(NULL));
    puts("PASS: both exact recorded 720p zero-count shader pairs; all safety guards");
    return 0;
}
