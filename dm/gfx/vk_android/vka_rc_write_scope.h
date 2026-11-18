// GPU visibility / guest-memory write scope for compute bindings.
// Conservative: only a fully decoded, read-only resource list is permitted
// to preserve previous submissions' query reports. No Vulkan calls.
// Unknown bindings, storage images, global memory logs, writes and atomics
// always invalidate the report generation.
#pragma once
#include "vka_bind.h"
static inline int vka_rc_compute_may_write(const vka_res *r, int n) {
    if (n < 0 || (n > 0 && !r)) return 1;
    for (int i=0; i<n; i++) {
        if (r[i].flags & (DMSH_VK_BF_RW|DMSH_VK_BF_ATOMIC|DMSH_VK_BF_NOSLOT))
            return 1;
        if (r[i].what == VKA_R_IMG || r[i].what == VKA_R_GMEM_LOG)
            return 1;
        switch (r[i].what) {
        case VKA_R_NULL: case VKA_R_BUF: case VKA_R_C1:
        case VKA_R_SUPPORT: case VKA_R_DRV: case VKA_R_TEX:
        case VKA_R_TBUF: case VKA_R_GMEM_MAP: case VKA_R_SHARED_SPILL:
            break;
        default: return 1;
        }
    }
    return 0;
}
