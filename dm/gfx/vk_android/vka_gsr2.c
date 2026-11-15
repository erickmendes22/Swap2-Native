// Ocarina spatial-NDSR replacement: Qualcomm GSR2 with colour-derived optical
// flow. The current NDSR interface provides no game depth or motion buffers.
// A full-resolution HDR scene is reconstructed at the original NDSR dispatch,
// NOT from the already upscaled swapchain. Experimental/opt-in only.
// SPDX-License-Identifier: MIT; Qualcomm GSR2 shaders are BSD-3-Clause (gsr2/LICENSE).
#if defined(__ANDROID__)
#include "vka.h"
#include "vka_gsr2.h"
#include "vka_gsr2_spv.h"
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum { P_FLOW, P_CONVERT, P_ACTIVATE, P_UPSCALE, P_COUNT };
enum { W_FLOW, W_YCC0, W_YCC1, W_MDA0, W_MDA1, W_LUMA0, W_LUMA1,
       W_MDC, W_HISTORY0, W_HISTORY1, W_OUTPUT, W_COUNT };
typedef struct { VkImage img; VkImageView view; VkDeviceMemory mem; uint32_t w,h; } gsr_img;
static struct {
    int ready, last_mode;
    VkDescriptorSetLayout ds;
    VkPipelineLayout layout;
    VkSampler nearest, linear;
    VkPipeline pipeline[P_COUNT];
    gsr_img work[W_COUNT];
    uint64_t last_frame;
    int ping, history_ping;
    uint64_t calls, resets;
} G={.last_frame=UINT64_MAX};

static void image_free(gsr_img *w) {
    if (w->view) vk.vkDestroyImageView(V.dev,w->view,NULL);
    if (w->img) vk.vkDestroyImage(V.dev,w->img,NULL);
    if (w->mem) vk.vkFreeMemory(V.dev,w->mem,NULL);
    memset(w,0,sizeof *w);
}
static void retired_free(void *p) { gsr_img *w=p; image_free(w); free(w); }

static int image_get(VkCommandBuffer cb, gsr_img *w, uint32_t width, uint32_t height) {
    if (w->img && w->w==width && w->h==height) return 1;
    if (w->img) {
        // Previous submissions may still reference the old image. Retire only
        // after the current recording's next GPU timeline fence.
        gsr_img *old=malloc(sizeof *old);
        if (!old) return 0;
        *old=*w;
        vka_after(vka_fence_last()+1,retired_free,old);
    }
    memset(w,0,sizeof *w);
    VkImageCreateInfo ci={VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType=VK_IMAGE_TYPE_2D,
        .format=VK_FORMAT_R16G16B16A16_SFLOAT,
        .extent={width,height,1},.mipLevels=1,.arrayLayers=1,
        .samples=VK_SAMPLE_COUNT_1_BIT,.tiling=VK_IMAGE_TILING_OPTIMAL,
        .usage=VK_IMAGE_USAGE_STORAGE_BIT|VK_IMAGE_USAGE_SAMPLED_BIT|
               VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT};
    VkResult r=vk.vkCreateImage(V.dev,&ci,NULL,&w->img);
    VkMemoryRequirements mr={0};
    if(!r)vk.vkGetImageMemoryRequirements(V.dev,w->img,&mr);
    uint32_t type=r?UINT32_MAX:vka_mem_type(mr.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,0);
    if(!r && type==UINT32_MAX)r=VK_ERROR_OUT_OF_DEVICE_MEMORY;
    VkMemoryAllocateInfo ai={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize=mr.size,.memoryTypeIndex=type};
    if(!r)r=vk.vkAllocateMemory(V.dev,&ai,NULL,&w->mem);
    if(!r)r=vk.vkBindImageMemory(V.dev,w->img,w->mem,0);
    VkImageViewCreateInfo vi={VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
        .image=w->img,.viewType=VK_IMAGE_VIEW_TYPE_2D,
        .format=VK_FORMAT_R16G16B16A16_SFLOAT,
        .subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
    if(!r)r=vk.vkCreateImageView(V.dev,&vi,NULL,&w->view);
    if(r) {
        VRED_ONCE("Ocarina GSR2 work image %ux%u creation error %d; preserve original NDSR",width,height,r);
        image_free(w);return 0;
    }
    w->w=width;w->h=height;
    vka_img_barrier(cb,w->img,VK_IMAGE_ASPECT_COLOR_BIT,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_GENERAL);
    VkClearColorValue zero={{0,0,0,0}};
    VkImageSubresourceRange range={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
    vk.vkCmdClearColorImage(cb,w->img,VK_IMAGE_LAYOUT_GENERAL,&zero,1,&range);
    return 2;
}

static int init_pipeline(void) {
    if(G.ready)return G.ready>0;
    G.ready=-1;
    if(!V.push_desc || !vk.vkCmdPushDescriptorSetKHR) {
        VRED_ONCE("Ocarina GSR2 requires push descriptors, not advertised; original SGSR retained");
        return 0;
    }
    VkFormatProperties fp;
    vk.vkGetPhysicalDeviceFormatProperties(V.pd,VK_FORMAT_R16G16B16A16_SFLOAT,&fp);
    if(!(fp.optimalTilingFeatures&VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT) ||
       !(fp.optimalTilingFeatures&VK_FORMAT_FEATURE_BLIT_SRC_BIT)) {
        VRED_ONCE("Ocarina GSR2: RGBA16F storage/blit source unsupported; original SGSR retained");
        return 0;
    }
    VkDescriptorSetLayoutBinding bindings[6];
    for(uint32_t i=0;i<6;i++)bindings[i]=(VkDescriptorSetLayoutBinding){
        .binding=i,.descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:
                            VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
        .descriptorCount=1,.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo dci={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .flags=VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR,
        .bindingCount=6,.pBindings=bindings};
    VkResult r=vk.vkCreateDescriptorSetLayout(V.dev,&dci,NULL,&G.ds);
    VkPushConstantRange pc={VK_SHADER_STAGE_COMPUTE_BIT,0,128};
    VkPipelineLayoutCreateInfo li={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount=1,.pSetLayouts=&G.ds,.pushConstantRangeCount=1,.pPushConstantRanges=&pc};
    if(!r)r=vk.vkCreatePipelineLayout(V.dev,&li,NULL,&G.layout);
    VkSamplerCreateInfo si={VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
        .magFilter=VK_FILTER_NEAREST,.minFilter=VK_FILTER_NEAREST,
        .mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST,
        .addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeV=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.maxLod=0.25f};
    if(!r)r=vk.vkCreateSampler(V.dev,&si,NULL,&G.nearest);
    si.magFilter=si.minFilter=VK_FILTER_LINEAR;
    if(!r)r=vk.vkCreateSampler(V.dev,&si,NULL,&G.linear);
    const uint32_t *words[P_COUNT]={vka_gsr2_flow,vka_gsr2_convert,vka_gsr2_activate,vka_gsr2_upscale};
    const size_t sizes[P_COUNT]={sizeof vka_gsr2_flow,sizeof vka_gsr2_convert,
        sizeof vka_gsr2_activate,sizeof vka_gsr2_upscale};
    for(int i=0;i<P_COUNT && !r;i++) {
        VkShaderModule module=VK_NULL_HANDLE;
        VkShaderModuleCreateInfo mi={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
            .codeSize=sizes[i],.pCode=words[i]};
        r=vk.vkCreateShaderModule(V.dev,&mi,NULL,&module);
        if(!r){
            VkComputePipelineCreateInfo ci={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
                .stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
                    .stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=module,.pName="main"},
                .layout=G.layout};
            r=vk.vkCreateComputePipelines(V.dev,VK_NULL_HANDLE,1,&ci,NULL,&G.pipeline[i]);
        }
        if(module)vk.vkDestroyShaderModule(V.dev,module,NULL);
    }
    if(r){
        VRED_ONCE("Ocarina GSR2 Vulkan pipelines failed (%d); original SGSR retained",r);
        return 0;
    }
    G.ready=1;
    VLOG("Ocarina GSR2 four compute passes ready: optical-flow, convert, activate, temporal-upscale (opt-in); no game depth or zero motion fabricated");
    return 1;
}

// All dynamic inputs are sampled in GENERAL layout. Every stage is ordered
// before later reads by the same GPU execution barrier used for guest dispatches.
static void pass(VkCommandBuffer cb,int pipe,
                 const VkImageView input[4], const VkSampler sampler[4],
                 VkImageView out0,VkImageView out1,
                 const void *params,uint32_t w,uint32_t h){
    VkDescriptorImageInfo info[6];
    VkWriteDescriptorSet writes[6];
    for(int i=0;i<6;i++){
        info[i]=i<4?(VkDescriptorImageInfo){
            sampler[i]?sampler[i]:G.nearest,
            input[i]?input[i]:input[0],VK_IMAGE_LAYOUT_GENERAL}:
            (VkDescriptorImageInfo){VK_NULL_HANDLE,
                i==4?out0:(out1?out1:out0),VK_IMAGE_LAYOUT_GENERAL};
        writes[i]=(VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
            .dstBinding=(uint32_t)i,.descriptorCount=1,
            .descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:
                                VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
            .pImageInfo=&info[i]};
    }
    vk.vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,G.pipeline[pipe]);
    vk.vkCmdPushDescriptorSetKHR(cb,VK_PIPELINE_BIND_POINT_COMPUTE,G.layout,0,6,writes);
    vk.vkCmdPushConstants(cb,G.layout,VK_SHADER_STAGE_COMPUTE_BIT,0,128,params);
    vk.vkCmdDispatch(cb,(w+7)/8,(h+7)/8,1);
    vka_barrier(cb);
}

typedef struct {
    float render[2],rcp[2],mvs[2],kfov,reset;
    int32_t colour_base[2];
    float vrej,vlo,vk,pad[19];
} gsr_pc_convert;
typedef struct {
    float render[2],output[2],rrcp[2],orcp[2],jitter[2],ratio[2];
    float minlerp,reset;
    int32_t tonemap,tap9;
    float hmin,motw,boxtol,boxmotw,hscale,mlo,mrcp,hsmov,afmot,bsmov,hcr,mvnear,pad[4];
} gsr_pc_upscale;
_Static_assert(sizeof(gsr_pc_convert)==128,"GSR2 convert push constants");
_Static_assert(sizeof(gsr_pc_upscale)==128,"GSR2 upscale/flow push constants");

int vka_gsr2_try(VkCommandBuffer cb, vka_img *src, vka_img *dst,
                 int source_is_sqrt, uint64_t frame) {
    // Fail closed before doing any extra GPU work. In particular a lower
    // resolution input with NO native 720p destination must keep its shaders.
    if(!cb || !src || !dst || !source_is_sqrt || src->f.kind || dst->f.kind ||
       !src->inited || !dst->inited || src->samples!=1 || dst->samples!=1 ||
       !(src->usage&VK_IMAGE_USAGE_SAMPLED_BIT) ||
       !(dst->usage&VK_IMAGE_USAGE_TRANSFER_DST_BIT) ||
       dst->w!=1280 || dst->h!=720 ||
       !((src->w==640 && src->h==360) || (src->w==960 && src->h==540)) ||
       (uint64_t)src->w*dst->h!=(uint64_t)src->h*dst->w)
        return 0;
    VkFormatProperties sp,dp;
    vk.vkGetPhysicalDeviceFormatProperties(V.pd,src->f.vk,&sp);
    vk.vkGetPhysicalDeviceFormatProperties(V.pd,dst->f.vk,&dp);
    if(!(sp.optimalTilingFeatures&VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT) ||
       !(dp.optimalTilingFeatures&VK_FORMAT_FEATURE_BLIT_DST_BIT)) {
        VRED_ONCE("Ocarina GSR2: source sample/dest blit feature unavailable; SGSR retained");
        return 0;
    }
    if(!init_pipeline() || G.last_frame==frame)return 0;
    const uint32_t iw=src->w,ih=src->h,ow=dst->w,oh=dst->h;
    VkImageView colour=vka_view(src,src->f.vk,VK_IMAGE_VIEW_TYPE_2D,
        VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1,NULL);
    if(!colour)return 0;
    uint32_t ww[W_COUNT],hh[W_COUNT];
    for(int k=0;k<W_COUNT;k++){
        ww[k]=k>=W_HISTORY0?ow:iw;
        hh[k]=k>=W_HISTORY0?oh:ih;
    }
    int reset=(G.last_frame==UINT64_MAX || frame!=G.last_frame+1);
    for(int k=0;k<W_COUNT;k++){
        int built=image_get(cb,&G.work[k],ww[k],hh[k]);
        if(!built)return 0;
        reset|=built==2;
    }
    // All resources are ready. Destination is given its own storage before
    // this guest-visible write, including the pooled-zero-image case.
    vka_tex_own(dst,cb);
    if(!dst->img)return 0;
    vka_barrier(cb);
    gsr_img *w=G.work;
    const int next=G.ping^1, hist=G.history_ping^1;
    int p_ycc=G.ping?W_YCC1:W_YCC0,c_ycc=next?W_YCC1:W_YCC0;
    int p_mda=G.ping?W_MDA1:W_MDA0,c_mda=next?W_MDA1:W_MDA0;
    int p_luma=G.ping?W_LUMA1:W_LUMA0,c_luma=next?W_LUMA1:W_LUMA0;
    int p_hist=G.history_ping?W_HISTORY1:W_HISTORY0;
    int c_hist=hist?W_HISTORY1:W_HISTORY0;
    // The flow shader stores real frame-to-frame displacement in INPUT
    // texels. Qualcomm's convert pass normalizes pixel motion by 1/iw,1/ih
    // and maps it to NDC (-2*). Treating the displacement as already
    // normalized AND leaving mvs=1 made motion effectively zero/incorrect.
    gsr_pc_convert pc={{(float)iw,(float)ih},{1.0f/iw,1.0f/ih},
        {1.0f/iw,1.0f/ih},1.0f,reset?1.0f:0.0f,{0,0},
        1.0f,0.35f,0.3f,{0}};
    float area=(float)ow*(float)oh/((float)iw*(float)ih);
    float history_scale=fminf(area*area*area,10.0f);
    gsr_pc_upscale up={{(float)iw,(float)ih},{(float)ow,(float)oh},
        {1.0f/iw,1.0f/ih},{1.0f/ow,1.0f/oh},
        {0,0},{(float)ow/iw,history_scale},0.30f,reset?1.0f:0.0f,
        1,1,0.15f,0.08f,0.07f,0.15f,1.25f,0.6f,0.8f,
        0.35f,1.0f,1.0f,2.0f,1.0f,{0}};
    // Optical flow must compare the unaltered previous YCoCg with the
    // current INPUT scene. It must run before the new convert writes YCoCg.
    {VkImageView in[4]={colour,w[p_ycc].view,colour,colour};
     VkSampler sm[4]={G.nearest,G.nearest,G.nearest,G.nearest};
     pass(cb,P_FLOW,in,sm,w[W_FLOW].view,w[W_FLOW].view,&up,iw,ih);}
    // OOT_FLOW's convert reads the measured motion from binding2, rejects
    // mismatches in velocity.z, and squares sqrt-HDR source colour.
    {VkImageView in[4]={colour,colour,w[W_FLOW].view,colour};
     VkSampler sm[4]={G.nearest,G.nearest,G.nearest,G.nearest};
     pass(cb,P_CONVERT,in,sm,w[c_ycc].view,w[c_mda].view,&pc,iw,ih);}
    {VkImageView in[4]={w[p_luma].view,w[c_mda].view,w[c_ycc].view,w[p_mda].view};
     VkSampler sm[4]={G.nearest,G.nearest,G.nearest,G.nearest};
     pass(cb,P_ACTIVATE,in,sm,w[W_MDC].view,w[c_luma].view,&pc,iw,ih);}
    {VkImageView in[4]={w[p_hist].view,w[W_MDC].view,w[c_ycc].view,w[c_ycc].view};
     VkSampler sm[4]={G.linear,G.linear,G.nearest,G.nearest};
     pass(cb,P_UPSCALE,in,sm,w[c_hist].view,w[W_OUTPUT].view,&up,ow,oh);}
    // The NDSR target is an actual game image and will receive overlays/UI.
    // Blitting from RGBA16F avoids assuming B10G11R11 supports storage image.
    // Do not replace it with a newly allocated output unknown to the game.
    VkImageBlit bl={
        {VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},{{0,0,0},{(int32_t)ow,(int32_t)oh,1}},
        {VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},{{0,0,0},{(int32_t)ow,(int32_t)oh,1}}};
    vk.vkCmdBlitImage(cb,w[W_OUTPUT].img,VK_IMAGE_LAYOUT_GENERAL,
                      dst->img,VK_IMAGE_LAYOUT_GENERAL,1,&bl,VK_FILTER_NEAREST);
    vka_barrier(cb);
    vka_img_written(dst);
    G.ping=next;G.history_ping=hist;G.last_frame=frame;G.calls++;
    if(reset)G.resets++;
    if(G.calls==1 || G.calls==120 || !(G.calls&1023u))
        VLOG("Ocarina GSR2 optical-temporal active: %ux%u -> %ux%u; frame=%llu, calls=%llu, history resets=%llu (current %d), motion confidence rejection enabled; no fake NVN motion/depth",
            iw,ih,ow,oh,(unsigned long long)frame,(unsigned long long)G.calls,
            (unsigned long long)G.resets,reset);
    return 1;
}
#endif
