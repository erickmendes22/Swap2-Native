// SPDX-License-Identifier: GPL-3.0-or-later
// Scope a post-rendering attachment barrier to EXECUTED attachment stages,
// rather than inferring execution from writes. Depth/stencil may READ in
// early/late tests with depthMask=0 (WAR); a bound colour attachment may LOAD
// and blend/read even when all subsequent colour masks are zero. The
// original producer-write access masks are deliberately handled separately.
#pragma once
#include <vulkan/vulkan_core.h>
static inline VkPipelineStageFlags vka_attachment_access_src_stages(
        int color_written, int depth_written,
        int color_bound, int depth_bound) {
    const VkPipelineStageFlags both =
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
        VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |
        VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
    // When bookkeeping contradicts the actual attachments, or none can be
    // proven bound, preserve the original execution scope rather than
    // guessing. Guest OP_BARRIER and storage writers never call this path.
    if ((!color_written && !depth_written) ||
        (!color_bound && !depth_bound) ||
        (color_written && !color_bound) ||
        (depth_written && !depth_bound))
        return both;
    return (color_bound ? VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT : 0) |
           (depth_bound ? (VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |
                           VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT) : 0);
}
