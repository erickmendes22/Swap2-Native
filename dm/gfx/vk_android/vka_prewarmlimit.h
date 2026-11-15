// Conservative Ocarina prewarm admission: resident VkPipelines are not
// released until exit, so excessive speculative prewarm consumes driver
// native heap even though the pipeline cache is already present on disk.
// Never gate frame-demand pipelines or remove any library / shader entries.
#ifndef VKA_PREWARMLIMIT_H
#define VKA_PREWARMLIMIT_H
#include <stdint.h>
#include <stddef.h>
#define VKPW_SMALL_PHONE (16ull << 30)
#define VKPW_SMALL_CAP 1536u
static inline uint32_t vkpw_limit(uint32_t requested, uint64_t total_physical,
                                   int ocarina, int explicit_max) {
    if (ocarina && !explicit_max && total_physical &&
        total_physical <= VKPW_SMALL_PHONE && requested > VKPW_SMALL_CAP)
        return VKPW_SMALL_CAP;
    return requested;
}
static inline size_t vkpw_newest(size_t total, size_t ordinal) {
    return total - 1 - ordinal;
}
#endif
