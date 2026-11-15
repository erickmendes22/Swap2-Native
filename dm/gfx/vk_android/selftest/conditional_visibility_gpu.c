// Research only: exact current-query GPU predication, never installed by the renderer.
// Compare pixels, depth and actual vertex invocations against known CPU references.
#define VKA_RENDERPASS_TEST
#define VKA_CAVE_QUERY_TEST
#define VKA_GPU_VISIBILITY_TEST
#define NDSR_EXTRA_FNS(X) X(vkGetPhysicalDeviceFeatures2) X(vkCreateGraphicsPipelines) \
 X(vkCmdDraw) X(vkCmdSetScissor) X(vkCmdBeginQuery) X(vkCmdEndQuery) \
 X(vkCmdBeginRendering) X(vkCmdEndRendering) X(vkCmdCopyQueryPoolResults) \
 X(vkGetDeviceProcAddr) X(vkCmdDrawIndirect) X(vkCmdDrawIndexedIndirect) X(vkCmdBindIndexBuffer) \
 X(vkCmdDrawIndirectCount) X(vkCmdDrawIndexedIndirectCount)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include <assert.h>

static PFN_vkCmdBeginConditionalRenderingEXT vkCmdBeginConditionalRenderingEXT;
static PFN_vkCmdEndConditionalRenderingEXT vkCmdEndConditionalRenderingEXT;

enum { W = 64, H = 64, BYTES = W * H * 4 };
static VkShaderModule module(const char *name) {
    FILE *f = fopen(getenv(name), "rb"); assert(f);
    fseek(f, 0, SEEK_END); long n = ftell(f); rewind(f);
    uint32_t *words = malloc(n); assert(words);
    assert(fread(words, 1, n, f) == (size_t)n); fclose(f);
    VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = n, .pCode = words};
    VkShaderModule m; VK(vkCreateShaderModule(dev, &ci, NULL, &m)); free(words); return m;
}
static VkPipeline make_pipeline(VkPipelineLayout lay, int query_only) {
    VkPipelineShaderStageCreateInfo sh[] = {
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT,
         .module = module("VIS_VERT"), .pName = "main"},
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT,
         .module = module("VIS_FRAG"), .pName = "main"}};
    VkPipelineVertexInputStateCreateInfo vi = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkViewport viewport = {0, 0, W, H, 0, 1}; VkRect2D scissor = {{0, 0}, {W, H}};
    VkPipelineViewportStateCreateInfo vp = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
        .viewportCount = 1, .pViewports = &viewport, .scissorCount = 1, .pScissors = &scissor};
    VkPipelineRasterizationStateCreateInfo rs = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode = VK_POLYGON_MODE_FILL, .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    VkPipelineDepthStencilStateCreateInfo ds = {VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO,
        .depthTestEnable = VK_TRUE, .depthWriteEnable = !query_only, .depthCompareOp = VK_COMPARE_OP_LESS};
    VkPipelineColorBlendAttachmentState att = {.colorWriteMask = query_only ? 0 : 15};
    VkPipelineColorBlendStateCreateInfo blend = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = 1, .pAttachments = &att};
    VkDynamicState dyn = VK_DYNAMIC_STATE_SCISSOR;
    VkPipelineDynamicStateCreateInfo dynamic = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = 1, .pDynamicStates = &dyn};
    VkFormat cf = VK_FORMAT_R8G8B8A8_UNORM;
    VkPipelineRenderingCreateInfo render = {VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO,
        .colorAttachmentCount = 1, .pColorAttachmentFormats = &cf, .depthAttachmentFormat = VK_FORMAT_D32_SFLOAT};
    VkGraphicsPipelineCreateInfo ci = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .pNext = &render,
        .stageCount = 2, .pStages = sh, .pVertexInputState = &vi, .pInputAssemblyState = &ia,
        .pViewportState = &vp, .pRasterizationState = &rs, .pMultisampleState = &ms,
        .pDepthStencilState = &ds, .pColorBlendState = &blend, .pDynamicState = &dynamic, .layout = lay};
    VkPipeline p; VK(vkCreateGraphicsPipelines(dev, VK_NULL_HANDLE, 1, &ci, NULL, &p));
    for (int i = 0; i < 2; i++) vkDestroyShaderModule(dev, sh[i].module, NULL);
    return p;
}
static void all_barrier(VkCommandBuffer cb) {
    VkMemoryBarrier b = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT, .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT};
    vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
        0, 1, &b, 0, NULL, 0, NULL);
}
static void draw(VkCommandBuffer cb, VkPipelineLayout lay, int which, int alpha, float z) {
    float pc[8] = {which == 0, which == 1, which == 2, 1, z, alpha, 0, 0};
    VkRect2D sc = {{0, 0}, {which == 1 ? W / 2 : W, H}};
    vkCmdSetScissor(cb, 0, 1, &sc);
    vkCmdPushConstants(cb, lay, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_COMPUTE_BIT, 0, 32, pc);
    vkCmdDraw(cb, 3, 1, 0, 0);
}
// path0 conservative; path1 native conditional; path2 exact CPU reference;
// path3 regular indirect; path4 indexed indirect (last two need no conditional-rendering extension).
static uint64_t run_visibility(int path, int invert, int alpha, int swap, uint8_t *out) {
    VkImageView views[2]; VkImage images[2];
    images[0] = image(VK_FORMAT_R8G8B8A8_UNORM, W, H,
        VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, &views[0]);
    images[1] = image(VK_FORMAT_D32_SFLOAT, W, H,
        VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, NULL);
    VkImageViewCreateInfo dview = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = images[1],
        .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = VK_FORMAT_D32_SFLOAT,
        .subresourceRange = {VK_IMAGE_ASPECT_DEPTH_BIT, 0, 1, 0, 1}};
    VK(vkCreateImageView(dev, &dview, NULL, &views[1]));
    VkDescriptorSetLayoutBinding bindings[2];
    for (int i = 0; i < 2; i++) bindings[i] = (VkDescriptorSetLayoutBinding){
        .binding = i, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
        .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo dci = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .bindingCount = 2, .pBindings = bindings};
    VkDescriptorSetLayout set_layout; VK(vkCreateDescriptorSetLayout(dev, &dci, NULL, &set_layout));
    VkPushConstantRange push = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_COMPUTE_BIT, 0, 32};
    VkPipelineLayoutCreateInfo lci = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount = 1, .pSetLayouts = &set_layout, .pushConstantRangeCount = 1, .pPushConstantRanges = &push};
    VkPipelineLayout lay; VK(vkCreatePipelineLayout(dev, &lci, NULL, &lay));
    VkPipeline pixels = make_pipeline(lay, 0), query_only = make_pipeline(lay, 1);
    VkQueryPoolCreateInfo qci = {VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
        .queryType = VK_QUERY_TYPE_OCCLUSION, .queryCount = 2};
    VkQueryPool oq, stats; VK(vkCreateQueryPool(dev, &qci, NULL, &oq));
    qci.queryType = VK_QUERY_TYPE_PIPELINE_STATISTICS; qci.queryCount = 1;
    qci.pipelineStatistics = VK_QUERY_PIPELINE_STATISTIC_VERTEX_SHADER_INVOCATIONS_BIT;
    VK(vkCreateQueryPool(dev, &qci, NULL, &stats));
    void *pred_map, *read_map, *args_map, *index_map, *fixed_map;
    VkBuffer pred = buffer(16, VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &pred_map);
    VkBuffer args = buffer(40, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT |
        (getenv("VIS_NO_NATIVE") ? 0 : VK_BUFFER_USAGE_CONDITIONAL_RENDERING_BIT_EXT), &args_map);
    memset(args_map, 0xa5, 40);
    VkBuffer fixed = buffer(40, VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT, &fixed_map);
    const uint32_t original_args[10] = {3,1,0,0,0,3,1,0,0,0};
    memcpy(fixed_map, original_args, sizeof original_args);
    VkBuffer indices = buffer(12, VK_BUFFER_USAGE_INDEX_BUFFER_BIT, &index_map);
    const uint32_t triangle[3] = {2, 0, 1}; memcpy(index_map, triangle, 12);
    VkDescriptorPoolSize size = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2};
    VkDescriptorPoolCreateInfo pool_info = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
        .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &size};
    VkDescriptorPool descriptors; VK(vkCreateDescriptorPool(dev, &pool_info, NULL, &descriptors));
    VkDescriptorSetAllocateInfo allocate = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool = descriptors, .descriptorSetCount = 1, .pSetLayouts = &set_layout};
    VkDescriptorSet set; VK(vkAllocateDescriptorSets(dev, &allocate, &set));
    VkDescriptorBufferInfo buffers[2] = {{pred, 0, 16}, {args, 0, 40}};
    VkWriteDescriptorSet writes[2];
    for (int i = 0; i < 2; i++) writes[i] = (VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
        .dstSet = set, .dstBinding = i, .descriptorCount = 1,
        .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &buffers[i]};
    vkUpdateDescriptorSets(dev, 2, writes, 0, NULL);
    VkComputePipelineCreateInfo compute_info = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                  .module = module("VIS_COMP"), .pName = "main"}, .layout = lay};
    VkPipeline compute; VK(vkCreateComputePipelines(dev, VK_NULL_HANDLE, 1, &compute_info, NULL, &compute));
    // A stale nonzero sentinel would erroneously execute the hidden draw.
    memset(pred_map, 0xa5, 16);
    VkBuffer read = buffer(BYTES * 2, VK_BUFFER_USAGE_TRANSFER_DST_BIT, &read_map);
    VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer cb; VK(vkAllocateCommandBuffers(dev, &ai, &cb));
    VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; VK(vkBeginCommandBuffer(cb, &bi));
    VkImageMemoryBarrier ib[2];
    for (int i = 0; i < 2; i++) ib[i] = (VkImageMemoryBarrier){VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT,
        .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_GENERAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = images[i], .subresourceRange = {i ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
        0, 0, NULL, 0, NULL, 2, ib);
    vkCmdResetQueryPool(cb, oq, 0, 2); vkCmdResetQueryPool(cb, stats, 0, 1);
    VkRenderingAttachmentInfo ca = {VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,
        .imageView = views[0], .imageLayout = VK_IMAGE_LAYOUT_GENERAL,
        .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
        .clearValue.color.float32 = {0, 0, 0, 1}};
    VkRenderingAttachmentInfo da = {VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,
        .imageView = views[1], .imageLayout = VK_IMAGE_LAYOUT_GENERAL,
        .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
        .clearValue.depthStencil = {1, 0}};
    VkRenderingInfo ri = {VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = {{0, 0}, {W, H}},
        .layerCount = 1, .colorAttachmentCount = 1, .pColorAttachments = &ca, .pDepthAttachment = &da};
    vkCmdBeginRendering(cb, &ri); vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, pixels);
    draw(cb, lay, 2, 0, 0.5f); // existing occluder, full viewport
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, query_only);
    for (int i = 0; i < 2; i++) {
        int obj = i ^ swap;
        vkCmdBeginQuery(cb, oq, i, VK_QUERY_CONTROL_PRECISE_BIT);
        draw(cb, lay, obj, alpha, obj ? 0.2f : 0.8f);
        vkCmdEndQuery(cb, oq, i);
    }
    vkCmdEndRendering(cb);
    // These are current submitted queries. The CPU never reads them to decide drawing.
    vkCmdCopyQueryPoolResults(cb, oq, 0, 2, pred, 0, 8,
        VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
    if (path == 1 || path >= 3) {
        VkMemoryBarrier to_compute = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_SHADER_READ_BIT};
        vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            0, 1, &to_compute, 0, NULL, 0, NULL);
        vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, compute);
        vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, lay, 0, 1, &set, 0, NULL);
        uint32_t pc[8] = {(uint32_t)invert};
        vkCmdPushConstants(cb, lay, push.stageFlags, 0, 32, pc);
        vkCmdDispatch(cb, 1, 1, 1);
        VkMemoryBarrier to_indirect = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_INDIRECT_COMMAND_READ_BIT};
        vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT,
            0, 1, &to_indirect, 0, NULL, 0, NULL);
        if (path == 1) {
            VkMemoryBarrier publish = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT,
                .dstAccessMask = VK_ACCESS_CONDITIONAL_RENDERING_READ_BIT_EXT};
            vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                VK_PIPELINE_STAGE_CONDITIONAL_RENDERING_BIT_EXT,
                0, 1, &publish, 0, NULL, 0, NULL);
        }
    }
    all_barrier(cb); ca.loadOp = da.loadOp = VK_ATTACHMENT_LOAD_OP_LOAD;
    vkCmdBeginRendering(cb, &ri); vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_GRAPHICS, pixels);
    vkCmdBeginQuery(cb, stats, 0, 0);
    for (int i = 0; i < 2; i++) {
        int obj = i ^ swap;
        if (path == 2 && !(invert ? !obj : obj)) continue;
        if (path == 1) {
            // Normalize BOTH halves of the 64-bit counter first. The EXT
            // predicate is only 32 bits and cannot consume a raw64 counter.
            VkConditionalRenderingBeginInfoEXT cond = {VK_STRUCTURE_TYPE_CONDITIONAL_RENDERING_BEGIN_INFO_EXT,
                .buffer = args, .offset = (VkDeviceSize)i * 20 + 4,
                .flags = 0};
            vkCmdBeginConditionalRenderingEXT(cb, &cond);
        }
        if (path >= 3) {
            float pc[8] = {obj == 0, obj == 1, 0, 1, obj ? 0.2f : 0.8f, alpha, 0, 0};
            VkRect2D sc = {{0, 0}, {obj ? W / 2 : W, H}};
            vkCmdSetScissor(cb, 0, 1, &sc);
            vkCmdPushConstants(cb, lay, push.stageFlags, 0, 32, pc);
            if (path == 6) {
                vkCmdBindIndexBuffer(cb, indices, 0, VK_INDEX_TYPE_UINT32);
                vkCmdDrawIndexedIndirectCount(cb, fixed, i * 20, args, i * 20 + 4, 1, 20);
            } else if (path == 5) {
                vkCmdDrawIndirectCount(cb, fixed, i * 20, args, i * 20 + 4, 1, 20);
            } else if (path == 4) {
                vkCmdBindIndexBuffer(cb, indices, 0, VK_INDEX_TYPE_UINT32);
                vkCmdDrawIndexedIndirect(cb, args, i * 20, 1, 20);
            } else vkCmdDrawIndirect(cb, args, i * 20, 1, 20);
        } else draw(cb, lay, obj, alpha, obj ? 0.2f : 0.8f);
        if (path == 1) vkCmdEndConditionalRenderingEXT(cb);
    }
    vkCmdEndQuery(cb, stats, 0); vkCmdEndRendering(cb); all_barrier(cb);
    for (int i = 0; i < 2; i++) {
        VkBufferImageCopy c = {.bufferOffset = i * BYTES,
            .imageSubresource = {i ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .imageExtent = {W, H, 1}};
        vkCmdCopyImageToBuffer(cb, images[i], VK_IMAGE_LAYOUT_GENERAL, read, 1, &c);
    }
    all_barrier(cb); VK(vkEndCommandBuffer(cb));
    VkSubmitInfo sub = {VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb};
    VK(vkQueueSubmit(q, 1, &sub, VK_NULL_HANDLE)); VK(vkQueueWaitIdle(q));
    uint64_t invoked = 0; VK(vkGetQueryPoolResults(dev, stats, 0, 1, 8, &invoked, 8, VK_QUERY_RESULT_64_BIT));
    uint64_t results[2]; VK(vkGetQueryPoolResults(dev, oq, 0, 2, 16, results, 8, VK_QUERY_RESULT_64_BIT));
    CHECK(results[swap] == 0 && results[swap ^ 1] > 0, "need exact hidden and visible query results");
    CHECK(!memcmp(results, pred_map, 16), "GPU predicate copy must replace every sentinel with this query's value");
    memcpy(out, read_map, BYTES * 2);
    return invoked;
}
#ifndef VKA_RC_COUNTER_REPLAY_TEST
int main(void) {
    if (!init()) return 77;
    if (!getenv("VIS_NO_NATIVE")) {
        vkCmdBeginConditionalRenderingEXT = (PFN_vkCmdBeginConditionalRenderingEXT)
            vkGetDeviceProcAddr(dev, "vkCmdBeginConditionalRenderingEXT");
        vkCmdEndConditionalRenderingEXT = (PFN_vkCmdEndConditionalRenderingEXT)
            vkGetDeviceProcAddr(dev, "vkCmdEndConditionalRenderingEXT");
        assert(vkCmdBeginConditionalRenderingEXT && vkCmdEndConditionalRenderingEXT);
    }
    uint8_t *reference = malloc(BYTES * 2), *gpu = malloc(BYTES * 2), *conservative = malloc(BYTES * 2);
    for (int invert = 0; invert < 2; invert++) for (int alpha = 0; alpha < 2; alpha++) for (int swap = 0; swap < 2; swap++) {
        uint64_t exact = run_visibility(2, invert, alpha, swap, reference);
        for (int path = 1; path <= 6; path++) {
        if (path == 2 || (path == 1 && getenv("VIS_NO_NATIVE"))) continue;
        uint64_t actual = run_visibility(path, invert, alpha, swap, gpu);
        uint64_t all = run_visibility(0, invert, alpha, swap, conservative);
        CHECK(!memcmp(reference, gpu, BYTES * 2), "conditional colour/depth must match exact current-result reference");
        CHECK(exact == 3 && actual == exact && all == 6, "conditional must eliminate actual hidden vertex work");
        if (!invert) CHECK(!memcmp(conservative, gpu, BYTES * 2), "conservative occlusion path must match colour/depth");
        else CHECK(memcmp(conservative, gpu, BYTES * 2), "inverted negative control must expose ignoring the condition");
        printf("current-query visibility path%d invert%d alpha%d swap%d: colour+depth exact; vertex invocations %llu -> %llu; no CPU predicate read (software Vulkan, not phone FPS)\n",
            path, invert, alpha, swap, (unsigned long long)all, (unsigned long long)actual);
        }
    }
    return fails ? 1 : 0;
}

#endif
