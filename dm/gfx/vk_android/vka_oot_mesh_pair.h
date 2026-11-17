// Research-only exact mesh/fragment pairing for a selective native-mesh A/B.
// The GPU sampled both pairs as independent >0.75ms compute+raster workloads.
// Do not route a mesh based on its key alone: the same source can be bound to
// other fragment programs with different per-primitive interface requirements.
#pragma once
#include <stdint.h>
static inline int vka_oot_hot_native_mesh_pair(uint64_t mesh_key, uint64_t fragment_key) {
    return (mesh_key == UINT64_C(0xeb021183bf9b0092) &&
            fragment_key == UINT64_C(0x087ef21b3a72ad3a)) ||
           (mesh_key == UINT64_C(0xfed302d791a4ba43) &&
            fragment_key == UINT64_C(0x0fb4823639295a2d));
}
