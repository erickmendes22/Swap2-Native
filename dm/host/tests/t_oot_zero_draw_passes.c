// SPDX-License-Identifier: GPL-3.0-or-later
// Pure C eligibility suite: no Vulkan dependencies or shader-library build.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "../../gfx/vk_android/vka_zero_draw_elide.h"

int main(void) {
    vka_zero_direct_case c = {.enabled=1, .mesh=0, .count=0,
                              .indirect=0, .multidraw_count=0};
    assert(vka_oot_zero_direct_draw(&c));
    // The former pass_open/pending_clear/attachment-size/shader-pair gates
    // were not required to omit a zero-invocation draw. Clears still execute
    // through ordinary PC flush and must never be omitted by this helper.
    c.enabled=0; assert(!vka_oot_zero_direct_draw(&c)); c.enabled=1;
    c.mesh=1; assert(!vka_oot_zero_direct_draw(&c)); c.mesh=0;
    c.indirect=1; assert(!vka_oot_zero_direct_draw(&c)); c.indirect=0;
    c.multidraw_count=1; assert(!vka_oot_zero_direct_draw(&c)); c.multidraw_count=0;
    for (int n=-3;n<=3;n++) {
        c.count=n;
        assert(vka_oot_zero_direct_draw(&c) == (n==0));
    }
    assert(!vka_oot_zero_direct_draw(0));
    puts("PASS: zero direct nonmesh draws omitted; indirect/mesh/nonzero unchanged");
    return 0;
}
