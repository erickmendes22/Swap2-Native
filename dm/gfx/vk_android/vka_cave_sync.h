// Optional Qualcomm cave workaround: framebuffer-local depth ordering.
// No changes to query results or render-condition decisions. The self-dependency
// and command share the exact same stages/accesses (Vulkan render-pass rules).
#pragma once
#define VKA_CAVE_DEPTH_STAGES (VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT)
#define VKA_CAVE_DEPTH_ACCESS (VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT)
static inline VkMemoryBarrier vka_cave_depth_memory_barrier(void) {
    return (VkMemoryBarrier){VK_STRUCTURE_TYPE_MEMORY_BARRIER, NULL,
                            VKA_CAVE_DEPTH_ACCESS, VKA_CAVE_DEPTH_ACCESS};
}
static inline VkSubpassDependency vka_cave_depth_self_dependency(void) {
    return (VkSubpassDependency){0, 0, VKA_CAVE_DEPTH_STAGES,
        VKA_CAVE_DEPTH_STAGES, VKA_CAVE_DEPTH_ACCESS, VKA_CAVE_DEPTH_ACCESS,
        VK_DEPENDENCY_BY_REGION_BIT};
}
