// Ocarina hot mesh: admit ONE dead output vec4 only for exact on-device
// profiled source keys. All other meshes retain the original >=2-plane
// threshold. Never prune unless the actual bound fragment input mask is
// known and both compute producer + vertex reader specialize together.
#pragma once
#include <stdint.h>
static inline int vka_oot_hot_one_plane_eligible(
        int is_ocarina, int enabled, uint64_t mesh_key, unsigned removed_vec4) {
    return is_ocarina && enabled && removed_vec4 == 1u &&
        (mesh_key == UINT64_C(0xeb021183bf9b0092) ||
         mesh_key == UINT64_C(0xfed302d791a4ba43) ||
         mesh_key == UINT64_C(0x3439aaa071d868ae));
}
