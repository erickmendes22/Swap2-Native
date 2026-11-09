// Audited compatibility, scoped to this exact host ABI. Banana 228 uses
// an 8192-entry GMEM table and bitmap write log; both are handled in the
// corresponding replay modules. Never substitute ABI hashes in a file header.
#pragma once
#include <string.h>
#include "../nvn/dmsh_chain_vk.h"
#define VKA_ABI_COMPAT_FOR "674db0a4ff79"
#define DMSH_VK_ABI_COMPAT "228b73bd10f6"
#define VKA_ABI_LOG_BITMAP 1u
static inline int vka_abi_compat_of(const char abi[12]) {
    if (strcmp(DMSH_VK_ABI, VKA_ABI_COMPAT_FOR)) return -1;
    return !memcmp(abi, DMSH_VK_ABI_COMPAT, 12) ? VKA_ABI_LOG_BITMAP : -1;
}
