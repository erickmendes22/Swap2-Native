// Execute the actual production helper, including non-precise query uncertainty.
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include "../vka_rc_gpu_spv.h"
#include <assert.h>
static void *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb"); assert(f);
    fseek(f, 0, SEEK_END); *size = (size_t)ftell(f); rewind(f);
    void *p = malloc(*size); assert(p && fread(p, 1, *size, f) == *size); fclose(f); return p;
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    if (!init()) return 77;
    size_t qbytes, jbytes;
    void *queries = read_file(argv[1], &qbytes), *jobs = read_file(argv[2], &jbytes);
    assert(qbytes && !(qbytes % 8) && jbytes && !(jbytes % 48));
    uint32_t count = (uint32_t)(jbytes / 48);
    void *mapped[3];
    VkBuffer b[3] = {buffer(qbytes, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &mapped[0]),
        buffer(jbytes, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &mapped[1]),
        buffer((VkDeviceSize)count * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &mapped[2])};
    memcpy(mapped[0], queries, qbytes); memcpy(mapped[1], jobs, jbytes); memset(mapped[2], 0xa5, count * 4);
    VkDescriptorSetLayoutBinding bindings[3];
    for (unsigned i = 0; i < 3; i++) bindings[i] = (VkDescriptorSetLayoutBinding){
        .binding = i, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
        .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo si = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .bindingCount = 3, .pBindings = bindings};
    VkDescriptorSetLayout sl; VK(vkCreateDescriptorSetLayout(dev, &si, NULL, &sl));
    VkPushConstantRange pc = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 4};
    VkPipelineLayoutCreateInfo li = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount = 1, .pSetLayouts = &sl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pc};
    VkPipelineLayout layout; VK(vkCreatePipelineLayout(dev, &li, NULL, &layout));
    VkShaderModuleCreateInfo mi = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = sizeof SPV_RC_VISIBILITY, .pCode = SPV_RC_VISIBILITY};
    VkShaderModule module; VK(vkCreateShaderModule(dev, &mi, NULL, &module));
    VkComputePipelineCreateInfo pi = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
            .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = module, .pName = "main"}, .layout = layout};
    VkPipeline pipeline; VK(vkCreateComputePipelines(dev, VK_NULL_HANDLE, 1, &pi, NULL, &pipeline));
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 3};
    VkDescriptorPoolCreateInfo di = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
        .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &ps};
    VkDescriptorPool descriptors; VK(vkCreateDescriptorPool(dev, &di, NULL, &descriptors));
    VkDescriptorSetAllocateInfo da = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool = descriptors, .descriptorSetCount = 1, .pSetLayouts = &sl};
    VkDescriptorSet set; VK(vkAllocateDescriptorSets(dev, &da, &set));
    VkDescriptorBufferInfo bi[3] = {{b[0], 0, qbytes}, {b[1], 0, jbytes}, {b[2], 0, count * 4}};
    VkWriteDescriptorSet writes[3];
    for (unsigned i = 0; i < 3; i++) writes[i] = (VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
        .dstSet = set, .dstBinding = i, .descriptorCount = 1,
        .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi[i]};
    vkUpdateDescriptorSets(dev, 3, writes, 0, NULL);
    VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer cb; VK(vkAllocateCommandBuffers(dev, &ai, &cb));
    VkCommandBufferBeginInfo begin = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; VK(vkBeginCommandBuffer(cb, &begin));
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, &set, 0, NULL);
    vkCmdPushConstants(cb, layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 4, &count);
    vkCmdDispatch(cb, (count + 31) / 32, 1, 1);
    VkMemoryBarrier host = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
        0, 1, &host, 0, NULL, 0, NULL);
    VK(vkEndCommandBuffer(cb));
    VkSubmitInfo submit = {VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb};
    VK(vkQueueSubmit(q, 1, &submit, VK_NULL_HANDLE)); VK(vkQueueWaitIdle(q));
    FILE *f = fopen(argv[3], "wb"); assert(f && fwrite(mapped[2], 4, count, f) == count); fclose(f);
    printf("production counter predicates: %u jobs executed on Vulkan\n", count);
    return 0;
}
