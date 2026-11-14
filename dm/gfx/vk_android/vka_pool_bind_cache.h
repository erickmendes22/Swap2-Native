#pragma once
#include <vulkan/vulkan_core.h>
#include <string.h>

// Exact layout identity only. No inferred compatibility across layouts.
typedef struct {
    VkPipelineLayout layout;
    VkDescriptorSet sets[2];
    uint32_t count;
    uint64_t revision;
    int valid;
} vka_pool_bind_cache;

static inline void vka_pool_bind_prepare(vka_pool_bind_cache *c,
                                        VkPipelineLayout layout, int known_set0) {
    if (!known_set0 || c->layout != layout) c->valid = 0;
}

// Descriptor contents can change without a handle change. Preserve the
// original rebind after ANY texture/feedback descriptor-table update.
static inline void vka_pool_bind_revision(vka_pool_bind_cache *c, uint64_t revision) {
    if (c->revision != revision) { c->valid = 0; c->revision = revision; }
}

// 1: the exact sets remain bound; 0: caller must emit the original bind.
static inline int vka_pool_bind_same(vka_pool_bind_cache *c,
                                    VkPipelineLayout layout,
                                    const VkDescriptorSet *sets, uint32_t count) {
    if (!sets || !count || count > 2 || !sets[0]) { c->valid = 0; return 0; }
    int same = c->valid && c->layout == layout && c->count == count &&
               !memcmp(c->sets, sets, count * sizeof *sets);
    c->layout = layout; c->count = count;
    memcpy(c->sets, sets, count * sizeof *sets);
    c->valid = 1;
    return same;
}
