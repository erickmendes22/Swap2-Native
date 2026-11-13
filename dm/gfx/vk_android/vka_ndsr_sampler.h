// Descriptor-only adapter for a spatial stand-in. Shader layouts and the
// guest sampler objects are unchanged. Call before push-descriptor caching.
#pragma once
static inline int vka_ndsr_linear_write(VkWriteDescriptorSet *writes, uint32_t n,
                                        uint16_t binding, VkSampler sampler,
                                        VkDescriptorImageInfo *scratch) {
    if (!sampler || !scratch) return 0;
    for (uint32_t i=0;i<n;i++) {
        VkWriteDescriptorSet *w=&writes[i];
        if (w->dstBinding!=binding || w->descriptorCount!=1 ||
            w->descriptorType!=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER || !w->pImageInfo) continue;
        *scratch=*w->pImageInfo;scratch->sampler=sampler;w->pImageInfo=scratch;
        return 1;
    }
    return 0;
}
