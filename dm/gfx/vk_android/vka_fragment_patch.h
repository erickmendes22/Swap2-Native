// Optional scene fragment replacement: immutable same-ABI libraries, exact IO
// and resource linkage. No Vulkan dependency: host tests exercise this gate.
#pragma once
#include "vka_shlib.h"
#include <string.h>

static inline int vka_fragment_patch_compatible(const vka_shlib *base,
                                                 const vka_shlib *patch,
                                                 uint64_t key) {
    if (!base->h || !patch->h ||
        memcmp(base->h->game, patch->h->game, sizeof base->h->game) ||
        memcmp(base->h->inputs, patch->h->inputs, sizeof base->h->inputs) ||
        memcmp(base->h->abi, patch->h->abi, sizeof base->h->abi) ||
        base->h->subgroup_size != patch->h->subgroup_size ||
        base->h->ssbo_align != patch->h->ssbo_align) return 0;
    const dmsh_vk_entry *a = vka_shlib_find(base, key);
    const dmsh_vk_entry *b = vka_shlib_find(patch, key);
    if (!a || !b || a->stage != DMSH_VK_STAGE_FS || b->stage != DMSH_VK_STAGE_FS ||
        a->flags != b->flags || a->mod_count != b->mod_count ||
        a->bind_count != b->bind_count || a->c1_len != b->c1_len ||
        a->fout_types != b->fout_types || a->fout_mask != b->fout_mask ||
        a->uint_mask != b->uint_mask || a->vin_mask != b->vin_mask ||
        a->vin_types != b->vin_types || a->shared != b->shared ||
        memcmp(a->local, b->local, sizeof a->local)) return 0;
    if (a->bind_count && memcmp(vka_shlib_binds(base, a), vka_shlib_binds(patch, b),
                               (size_t)a->bind_count * sizeof(dmsh_vk_bind))) return 0;
    if (a->c1_len && memcmp(vka_shlib_c1(base, a), vka_shlib_c1(patch, b), a->c1_len)) return 0;
    // Count alone does not prove that the same output/alpha variants exist.
    for (unsigned i = 0; i < a->mod_count; i++) {
        int variant = base->mod[a->mod + i].variant;
        if (!vka_shlib_module(patch, b, variant)) return 0;
    }
    return 1;
}
