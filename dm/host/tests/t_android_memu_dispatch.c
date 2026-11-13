// Execute a converted mesh fixture on Vulkan, including software ICDs.
// Arguments: module.spv records.bin arena.bin result.bin x y z [helper]
// Helpers bind records/control/arena at 0/1/2; mesh uses 382/383.
// Host-coherent readback verifies actual GPU writes, not instruction counts.
#include <vulkan/vulkan_core.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define VK_OK(expr) do { VkResult result_ = (expr); if (result_ != VK_SUCCESS) { \
    fprintf(stderr, "%s: VkResult %d\n", #expr, result_); exit(1); } } while (0)
static void *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END); *size = (size_t)ftell(f); rewind(f);
    void *p = malloc(*size); if (!p || fread(p, 1, *size, f) != *size) exit(1);
    fclose(f); return p;
}
typedef struct { VkBuffer buffer; VkDeviceMemory memory; void *map; size_t size; } buffer;
static VkDevice device;
static VkPhysicalDevice physical;
static buffer make_buffer(const void *data, size_t size) {
    buffer b = {.size = size};
    VkBufferCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VK_OK(vkCreateBuffer(device, &ci, NULL, &b.buffer));
    VkMemoryRequirements req; vkGetBufferMemoryRequirements(device, b.buffer, &req);
    VkPhysicalDeviceMemoryProperties props; vkGetPhysicalDeviceMemoryProperties(physical, &props);
    uint32_t type = props.memoryTypeCount;
    for (uint32_t i = 0; i < props.memoryTypeCount; i++)
        if ((req.memoryTypeBits & (1u << i)) && (props.memoryTypes[i].propertyFlags &
            (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) ==
            (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) { type = i; break; }
    if (type == props.memoryTypeCount) { fprintf(stderr, "no coherent readback memory\n"); exit(1); }
    VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = req.size, .memoryTypeIndex = type};
    VK_OK(vkAllocateMemory(device, &ai, NULL, &b.memory));
    VK_OK(vkBindBufferMemory(device, b.buffer, b.memory, 0));
    VK_OK(vkMapMemory(device, b.memory, 0, size, 0, &b.map));
    memcpy(b.map, data, size); return b;
}
static void free_buffer(buffer *b) {
    vkUnmapMemory(device, b->memory); vkDestroyBuffer(device, b->buffer, NULL);
    vkFreeMemory(device, b->memory, NULL);
}
int main(int argc, char **argv) {
    if (argc != 8 && argc != 9) return 2;
    int helper = argc == 9;
    size_t ns, nr, na; uint32_t *spv = read_file(argv[1], &ns);
    void *records = read_file(argv[2], &nr), *arena = read_file(argv[3], &na);
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app};
    VkInstance instance; VK_OK(vkCreateInstance(&ici, NULL, &instance));
    uint32_t count = 0; VK_OK(vkEnumeratePhysicalDevices(instance, &count, NULL));
    if (!count) return 3;
    VkPhysicalDevice *devices = calloc(count, sizeof *devices);
    VK_OK(vkEnumeratePhysicalDevices(instance, &count, devices)); physical = devices[0]; free(devices);
    VkPhysicalDeviceProperties props; vkGetPhysicalDeviceProperties(physical, &props);
    fprintf(stderr, "Vulkan readback: %s\n", props.deviceName);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, NULL);
    VkQueueFamilyProperties *families = calloc(count, sizeof *families);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, families);
    uint32_t family = 0; while (family < count && !(families[family].queueFlags & VK_QUEUE_COMPUTE_BIT)) family++;
    uint32_t timestamp_bits = family < count ? families[family].timestampValidBits : 0;
    free(families); if (family == count) return 3;
    float priority = 1;
    VkDeviceQueueCreateInfo qci = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci};
    VK_OK(vkCreateDevice(physical, &dci, NULL, &device));
    VkQueue queue; vkGetDeviceQueue(device, family, 0, &queue);
    const char *initial_counter = getenv("MEMU_TEST_COUNTER");
    uint32_t control[16] = {initial_counter ? (uint32_t)strtoul(initial_counter, NULL, 10) : 0, 0};
    buffer buf[3] = {make_buffer(arena, na), make_buffer(records, nr), make_buffer(control, sizeof control)};
    VkDescriptorSetLayoutBinding bindings[3] = {0};
    for (int i = 0; i < (helper ? 3 : 2); i++) bindings[i] = (VkDescriptorSetLayoutBinding){
        .binding = helper ? (uint32_t)i : (uint32_t)(382 + i),
        .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo lci = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .bindingCount = helper ? 3 : 2, .pBindings = bindings};
    VkDescriptorSetLayout set_layout; VK_OK(vkCreateDescriptorSetLayout(device, &lci, NULL, &set_layout));
    VkPushConstantRange range = {.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT, .size = 16};
    VkPipelineLayoutCreateInfo plci = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount = 1, .pSetLayouts = &set_layout, .pushConstantRangeCount = 1, .pPushConstantRanges = &range};
    VkPipelineLayout layout; VK_OK(vkCreatePipelineLayout(device, &plci, NULL, &layout));
    VkShaderModuleCreateInfo sci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = ns, .pCode = spv};
    VkShaderModule shader; VK_OK(vkCreateShaderModule(device, &sci, NULL, &shader));
    VkComputePipelineCreateInfo pci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                  .module = shader, .pName = "main"}, .layout = layout};
    VkPipeline pipeline; VK_OK(vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pci, NULL, &pipeline));
    VkDescriptorPoolSize pool_size = {.type = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .descriptorCount = 3};
    VkDescriptorPoolCreateInfo dpci = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
        .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &pool_size};
    VkDescriptorPool pool; VK_OK(vkCreateDescriptorPool(device, &dpci, NULL, &pool));
    VkDescriptorSetAllocateInfo dsai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool = pool, .descriptorSetCount = 1, .pSetLayouts = &set_layout};
    VkDescriptorSet set; VK_OK(vkAllocateDescriptorSets(device, &dsai, &set));
    VkDescriptorBufferInfo info[3]; VkWriteDescriptorSet write[3];
    for (int i = 0; i < (helper ? 3 : 2); i++) {
        int b = helper ? (i == 0 ? 1 : i == 1 ? 2 : 0) : i;
        info[i] = (VkDescriptorBufferInfo){.buffer = buf[b].buffer, .range = buf[b].size};
        write[i] = (VkWriteDescriptorSet){.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
            .dstSet = set, .dstBinding = bindings[i].binding, .descriptorCount = 1,
            .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &info[i]};
    }
    vkUpdateDescriptorSets(device, helper ? 3 : 2, write, 0, NULL);
    VkCommandPoolCreateInfo cpci = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family};
    VkCommandPool command_pool; VK_OK(vkCreateCommandPool(device, &cpci, NULL, &command_pool));
    VkCommandBufferAllocateInfo cbai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = command_pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer command; VK_OK(vkAllocateCommandBuffers(device, &cbai, &command));
    VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VK_OK(vkBeginCommandBuffer(command, &begin));
    vkCmdBindPipeline(command, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(command, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, &set, 0, NULL);
    uint32_t push[4] = {0, (uint32_t)(nr / 128), (uint32_t)(na / 4), 0};
    vkCmdPushConstants(command, layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 16, push);
    uint32_t groups[3]; for (int i = 0; i < 3; i++) groups[i] = (uint32_t)strtoul(argv[5+i], NULL, 10);
    const char *repeat_env = getenv("MEMU_TEST_REPEATS");
    uint32_t repeats = repeat_env ? (uint32_t)strtoul(repeat_env, NULL, 10) : 1;
    if (!repeats || repeats > 256) return 2;
    VkQueryPool query = VK_NULL_HANDLE;
    VkMemoryBarrier between = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT,
        .dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT};
    if (repeat_env) {
        if (!timestamp_bits) { fprintf(stderr, "queue has no timestamp support\n"); return 3; }
        VkQueryPoolCreateInfo qp = {.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
            .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 2};
        VK_OK(vkCreateQueryPool(device, &qp, NULL, &query));
        // Warm JIT/cache state before measuring. Repeated dispatches are
        // ordered for their WAW/RAW hazards, including the arena readback.
        vkCmdDispatch(command, groups[0], groups[1], groups[2]);
        vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &between, 0, NULL, 0, NULL);
        vkCmdResetQueryPool(command, query, 0, 2);
        vkCmdWriteTimestamp(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, query, 0);
    }
    for (uint32_t i = 0; i < repeats; i++) {
        if (i) vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &between, 0, NULL, 0, NULL);
        vkCmdDispatch(command, groups[0], groups[1], groups[2]);
    }
    if (query) vkCmdWriteTimestamp(command, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, query, 1);
    VkMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
    VK_OK(vkEndCommandBuffer(command));
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &command};
    VK_OK(vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE)); VK_OK(vkQueueWaitIdle(queue));
    if (query) {
        uint64_t ticks[2];
        VK_OK(vkGetQueryPoolResults(device, query, 0, 2, sizeof ticks, ticks, sizeof(uint64_t),
            VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT));
        uint64_t elapsed = ticks[1] - ticks[0];
        if (timestamp_bits < 64) elapsed &= (1ull << timestamp_bits) - 1;
        printf("{\"gpu_ns_per_dispatch\":%.0f,\"repeats\":%u}\n",
               elapsed * (double)props.limits.timestampPeriod / repeats, repeats);
        vkDestroyQueryPool(device, query, NULL);
    }
    FILE *f = fopen(argv[4], "wb"); if (!f || fwrite(buf[0].map, 1, na, f) != na) return 1; fclose(f);
    if (helper) { f = fopen(argv[2], "wb"); if (!f || fwrite(buf[1].map, 1, nr, f) != nr) return 1; fclose(f); }
    const char *ctl_out = getenv("MEMU_TEST_CTL_OUT");
    if (ctl_out) { f = fopen(ctl_out, "wb"); if (!f || fwrite(buf[2].map, 1, 64, f) != 64) return 1; fclose(f); }
    vkDestroyCommandPool(device, command_pool, NULL); vkDestroyDescriptorPool(device, pool, NULL);
    vkDestroyPipeline(device, pipeline, NULL); vkDestroyShaderModule(device, shader, NULL);
    vkDestroyPipelineLayout(device, layout, NULL); vkDestroyDescriptorSetLayout(device, set_layout, NULL);
    for (int i = 0; i < 3; i++) free_buffer(&buf[i]);
    vkDestroyDevice(device, NULL); vkDestroyInstance(instance, NULL);
    free(spv); free(records); free(arena); return 0;
}
