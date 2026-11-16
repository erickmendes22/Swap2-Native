// Conservative Ocarina 720p depth-attachment store policy.
// Vulkan 1.3 STORE_OP_NONE preserves previous contents of an untouched
// attachment. It is NOT equivalent to DONT_CARE.
#ifndef VKA_READONLY_DEPTH_STORE_H
#define VKA_READONLY_DEPTH_STORE_H
static inline int vka_readonly_depth_store_eligible(
    int ocarina, int enabled, unsigned width, unsigned height, unsigned samples,
    int vulkan_13, int has_depth, int has_stencil,
    int depth_load, int original_store, int pending_depth_clear,
    int depth_write_enabled, int classic_renderpass) {
    return ocarina && enabled && width == 1280u && height == 720u &&
           samples == 1u && vulkan_13 && has_depth && !has_stencil &&
           depth_load && original_store && !pending_depth_clear &&
           !depth_write_enabled && !classic_renderpass;
}
#endif
