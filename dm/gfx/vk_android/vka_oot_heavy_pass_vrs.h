// Narrow 4x2 shading-rate experiment for the two measured 1280x720
// Ocarina graphics passes. Pure policy: no shader mutation or draw omission.
// The 2x2 setting stays authoritative for all other shaders and targets.
#ifndef VKA_OOT_HEAVY_PASS_VRS_H
#define VKA_OOT_HEAVY_PASS_VRS_H
#include <stdint.h>
#include <vulkan/vulkan_core.h>
static inline int vka_oot_heavy_4x2_eligible(
        int ocarina, int enabled, int driver_supports_4x2,
        int vrs_profile, uint32_t chosen_width, uint32_t chosen_height,
        uint64_t fragment_key, int mesh, uint32_t color_count,
        VkFormat color_format, VkFormat depth_format,
        uint32_t samples, int alpha_to_coverage) {
    return ocarina && enabled && driver_supports_4x2 && vrs_profile == 2 &&
           chosen_width == 2u && chosen_height == 2u &&
           (fragment_key == UINT64_C(0x1e4d2630d24846d0) ||
            fragment_key == UINT64_C(0x19f99e925937b038) ||
            fragment_key == UINT64_C(0x8ea627c8ef169ee1)) &&
           !mesh && color_count == 1u &&
           color_format == VK_FORMAT_B10G11R11_UFLOAT_PACK32 &&
           depth_format == VK_FORMAT_D32_SFLOAT &&
           samples == 1u && !alpha_to_coverage;
}
#endif
