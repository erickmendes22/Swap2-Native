// Ocarina experimental fragment-draw suppression. Only exact, profiled keys.
// No claim that a draw is genuinely occluded: discarded draws may contribute
// depth, colours or inputs used by later passes. UI options default OFF.
#pragma once
#include <stdint.h>
#define VKA_OOT_FS_HEAVY UINT64_C(0x5684f5e658eda176)
#define VKA_OOT_FS_LAYER2 UINT64_C(0x47eb514f6d5e9faf)
static inline int vka_oot_skip_fs_key(uint64_t fs_key, int hidden_layers_on,
                                       int heavy_fs_on) {
    return (hidden_layers_on &&
            (fs_key == VKA_OOT_FS_HEAVY || fs_key == VKA_OOT_FS_LAYER2)) ||
           (heavy_fs_on && fs_key == VKA_OOT_FS_HEAVY);
}
