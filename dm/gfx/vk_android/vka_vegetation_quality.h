// SPDX-License-Identifier: GPL-3.0-or-later
// Ocarina v2: isolate the TWO PAIRS left untouched by the previous
// aggressive 5-of-7 foliage presets. The player's screenshots confirmed
// those older presets removed important grasses and ferns. Never reuse
// aggressive old preferences on new builds.
//
// Both entries are EXACT original Foliage mesh depth/colour shader pairs
// listed in the reviewed game.tsv. Do not skip Foliage task stages or
// mesh stages outside these two pairs. The call site rejects storage/
// atomic/opaque effects and transform feedback before skipping, and
// applies the same decision during mesh lookahead and raster.
#pragma once
#include <stdint.h>
#include <string.h>
static inline int vka_vegetation_quality_pair(const char *title, uint64_t key) {
    if (!title || strcmp(title, "0400486024DEC000")) return 0;
    if (key == UINT64_C(0x5b737961ae3e1b10) ||
        key == UINT64_C(0xecead5cd0569091f)) return 1;
    if (key == UINT64_C(0x839241636fce850a) ||
        key == UINT64_C(0x4c7d6be5a7717c8d)) return 2;
    return 0;
}
static inline int vka_vegetation_quality_key(const char *title, uint64_t key, int tier) {
    if (tier <= 0 || tier >= 4) return 0;
    int pair = vka_vegetation_quality_pair(title, key);
    return pair && (tier == 3 || tier == pair);
}
