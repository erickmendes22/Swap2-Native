// Pure-C gate test for an optional extended taskless mesh direct dispatch.
// This verifies source-replay eligibility only, NOT phone GPU performance.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "../../gfx/vk_android/vka_memu_direct_dispatch.h"
static uint32_t trial(int enabled, uint32_t groups, uint32_t arena) {
    return vka_memu_direct_groups(1, enabled, 0, 0, groups,
                                 65535u, arena, 12u, 4u, 0);
}
int main(void) {
    // The old 0.1.9 path is EXACTLY unchanged for <=64 and rejects >=65.
    assert(trial(1, 1, 8192) == 1);
    assert(trial(1, 64, 8192) == 64);
    assert(trial(1, 65, 8192) == 0);
    // Only the opt-in mode extends eligibility through 256.
    for (uint32_t g = 65; g <= 256; g++)
        assert(trial(2, g, 8192) == g);
    assert(trial(2, 257, 8192) == 0);
    assert(trial(0, 64, 8192) == 0);
    assert(vka_memu_direct_groups(0, 2, 0, 0, 128, 256, 8192, 12, 4, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 1, 0, 128, 256, 8192, 12, 4, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 0, 1, 128, 256, 8192, 12, 4, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 127, 8192, 12, 4, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 256, 0, 12, 4, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 256, 1000, 12, 4, 0) == 0);
    // Interleaved source has one stride; separate vertex/primitive need both.
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 256, 1536, 12, 4, 1) == 128);
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 256, 1536, 12, 4, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 256, 8192, 0, 0, 0) == 0);
    assert(vka_memu_direct_groups(1, 2, 0, 0, 128, 256, 8192, UINT32_MAX,
                                  UINT32_MAX, 0) == 0);
    // If the allocator has less space because earlier batches used it,
    // R_TOTAL is lower. The actual mesh SPIR-V tests flat < R_TOTAL,
    // so extended direct dispatch can only launch extra idle groups.
    puts("PASS: 64 baseline stable; opt-in 65..256 bounded; task/indirect/arena guarded");
    return 0;
}
