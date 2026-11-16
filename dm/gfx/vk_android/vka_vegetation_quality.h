// SPDX-License-Identifier: GPL-3.0-or-later
// Runtime, Ocarina-only cosmetic vegetation patches. These seven reviewed
// original depth/colour mesh pairs are the existing game.tsv's
// mesh_vegetation_cut list (ported from Banana Native). Never cut an
// unknown shader, an unpaired colour/depth stage, or all foliage by accident.
//
// Tiers are conservative: 1 omits two most expensive measured cosmetic
// pairs, 2 omits those plus three further reviewed pairs. All other 508
// supplement stages and all task/mesh/fragment shaders remain untouched.
// Caller must separately verify the draw has no storage/atomic/feedback
// side effects and is not recording transform feedback.
#pragma once
#include <stdint.h>
#include <string.h>
static inline int vka_vegetation_quality_key(const char *title, uint64_t key, int tier) {
    if (!title || strcmp(title, "0400486024DEC000") || tier <= 0 || tier >= 3) return 0;
    static const struct { uint64_t depth, colour; int tier; } groups[] = {
        { UINT64_C(0xd98076e4148db34f), UINT64_C(0xfed302d791a4ba43), 1 },
        { UINT64_C(0x101ecb327aafe9b1), UINT64_C(0x17c8ab6419068d4b), 1 },
        { UINT64_C(0xeebdb9347d09b344), UINT64_C(0x604134a5262ff670), 2 },
        { UINT64_C(0x25c4a740753e7d7a), UINT64_C(0x73dc0b90c4082e43), 2 },
        { UINT64_C(0x0c1ffecd02018fb0), UINT64_C(0xeed1add7c89f5d34), 2 }
    };
    for (unsigned i = 0; i < sizeof groups / sizeof *groups; ++i)
        if (tier >= groups[i].tier &&
            (key == groups[i].depth || key == groups[i].colour)) return 1;
    return 0;
}
