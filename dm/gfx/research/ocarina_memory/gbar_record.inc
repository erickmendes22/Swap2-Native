// Banana Native vka_gbar.c rec(), MIT, unmodified scopes.
static void rec(VkCommandBuffer cb, int b, int ind) {
    VkPipelineStageFlags src = VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, dst;
    VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT};
    if (b == VKGB_B_NARROW) {   // compute writes to the next dispatches' reads and writes (and their indirect group counts)
        dst = VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | (ind ? VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT : 0);
        mb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_UNIFORM_READ_BIT | (ind ? VK_ACCESS_INDIRECT_COMMAND_READ_BIT : 0);
    } else if (b == VKGB_B_INDIRECT) { dst = VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT; mb.dstAccessMask = VK_ACCESS_INDIRECT_COMMAND_READ_BIT; }
    else { dst = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT; mb.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT; }   // VKGB_B_SETTLE
    vkCmdPipelineBarrier(cb, src, dst, 0, 1, &mb, 0, NULL, 0, NULL);
}
