// Standalone deterministic GPU test of the production GSR2 upscale shader.
// No game assets, CPU rendering approximation, or Android input required.
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "vka_gsr2_spv.h"
#define CK(x) do { VkResult r=(x);if(r){fprintf(stderr,"%s:%d error %d\n",__FILE__,__LINE__,r);return 2;} }while(0)
#define REQ(x) do {if(!(x)){fprintf(stderr,"assert %s line %d\n",#x,__LINE__);return 2;}}while(0)
static VkDevice d;static VkPhysicalDevice pd;static VkPhysicalDeviceMemoryProperties mm;
static int memidx(uint32_t bits,VkMemoryPropertyFlags fl){for(uint32_t i=0;i<mm.memoryTypeCount;i++)if((bits&(1u<<i))&&(mm.memoryTypes[i].propertyFlags&fl)==fl)return (int)i;return -1;}
typedef struct{VkImage img;VkImageView v;VkDeviceMemory m;uint32_t w,h;} Im;
static Im im[5];static const uint32_t wi=640,hi=360,wo=1280,ho=720;
static int imgnew(int i,VkFormat f,uint32_t w,uint32_t h){
 Im *x=&im[i];x->w=w;x->h=h;
 VkImageCreateInfo ci={.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,
 .format=f,.extent={w,h,1},.mipLevels=1,.arrayLayers=1,.samples=VK_SAMPLE_COUNT_1_BIT,
 .tiling=VK_IMAGE_TILING_OPTIMAL,.usage=VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_STORAGE_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
 CK(vkCreateImage(d,&ci,0,&x->img));VkMemoryRequirements req;vkGetImageMemoryRequirements(d,x->img,&req);
 int mt=memidx(req.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);REQ(mt>=0);
 VkMemoryAllocateInfo ai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,.memoryTypeIndex=(uint32_t)mt};
 CK(vkAllocateMemory(d,&ai,0,&x->m));CK(vkBindImageMemory(d,x->img,x->m,0));
 VkImageViewCreateInfo vi={.sType=VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=x->img,.viewType=VK_IMAGE_VIEW_TYPE_2D,.format=f,
 .subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};CK(vkCreateImageView(d,&vi,0,&x->v));return 0;
}
static void barrier(VkCommandBuffer cb){
 VkMemoryBarrier b={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,
 .dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT};
 vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&b,0,0,0,0);
}
typedef struct{
 float render[2],output[2],rrcp[2],orcp[2],jitter[2],ratio[2];
 float minlerp,reset;int32_t tm,tap9;
 float hmin,motw,boxtol,boxmotw,hscale,mlo,mrcp,hsmov,afmot,bsmov,hcr,mvnear,pad[4];
} PC;
_Static_assert(sizeof(PC)==128,"GSR2 push constant ABI");
int main(void){
 VkApplicationInfo ai={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,.apiVersion=VK_API_VERSION_1_1};
 VkInstanceCreateInfo ic={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pApplicationInfo=&ai};
 VkInstance inst;CK(vkCreateInstance(&ic,0,&inst));
 uint32_t n=0;CK(vkEnumeratePhysicalDevices(inst,&n,0));REQ(n>0&&n<=8);
 VkPhysicalDevice gpus[8];CK(vkEnumeratePhysicalDevices(inst,&n,gpus));pd=gpus[0];
 VkPhysicalDeviceProperties pr;vkGetPhysicalDeviceProperties(pd,&pr);fprintf(stderr,"synthetic GPU %s\n",pr.deviceName);
 uint32_t nq=0;vkGetPhysicalDeviceQueueFamilyProperties(pd,&nq,0);REQ(nq>0&&nq<=16);
 VkQueueFamilyProperties qs[16];vkGetPhysicalDeviceQueueFamilyProperties(pd,&nq,qs);
 int qi=-1;for(uint32_t i=0;i<nq;i++)if(qs[i].queueFlags&VK_QUEUE_COMPUTE_BIT){qi=(int)i;break;}REQ(qi>=0);
 float priority=1.0f;VkDeviceQueueCreateInfo qc={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,.queueFamilyIndex=(uint32_t)qi,.queueCount=1,.pQueuePriorities=&priority};
 VkDeviceCreateInfo dc={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qc};
 CK(vkCreateDevice(pd,&dc,0,&d));VkQueue q;vkGetDeviceQueue(d,(uint32_t)qi,0,&q);
 vkGetPhysicalDeviceMemoryProperties(pd,&mm);
 for(int i=0;i<5;i++) {
  VkFormat fmt=i==4?VK_FORMAT_R32_UINT:VK_FORMAT_R16G16B16A16_SFLOAT;
  uint32_t w=(i==1||i==2)?wi:wo,h=(i==1||i==2)?hi:ho;
  if(imgnew(i,fmt,w,h))return 2;
 }
 VkDescriptorSetLayoutBinding lb[6];for(int i=0;i<6;i++)lb[i]=(VkDescriptorSetLayoutBinding){
 .binding=i,.descriptorCount=1,.descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
 VkDescriptorSetLayoutCreateInfo lci={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=6,.pBindings=lb};
 VkDescriptorSetLayout sl;CK(vkCreateDescriptorSetLayout(d,&lci,0,&sl));
 VkPushConstantRange range={VK_SHADER_STAGE_COMPUTE_BIT,0,128};
 VkPipelineLayoutCreateInfo plci={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
 .setLayoutCount=1,.pSetLayouts=&sl,.pushConstantRangeCount=1,.pPushConstantRanges=&range};
 VkPipelineLayout layout;CK(vkCreatePipelineLayout(d,&plci,0,&layout));
 VkShaderModuleCreateInfo smi={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=sizeof vka_gsr2_upscale,.pCode=vka_gsr2_upscale};
 VkShaderModule sm;CK(vkCreateShaderModule(d,&smi,0,&sm));
 VkComputePipelineCreateInfo pi={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
 .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=sm,.pName="main"},.layout=layout};
 VkPipeline p;CK(vkCreateComputePipelines(d,0,1,&pi,0,&p));
 VkSamplerCreateInfo sci={.sType=VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,.magFilter=VK_FILTER_LINEAR,.minFilter=VK_FILTER_LINEAR,
 .mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
 .addressModeV=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.maxLod=.25f};
 VkSampler nearest,linear;CK(vkCreateSampler(d,&sci,0,&linear));sci.magFilter=sci.minFilter=VK_FILTER_NEAREST;CK(vkCreateSampler(d,&sci,0,&nearest));
 VkDescriptorPoolSize sizes[2]={{VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,4},{VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,2}};
 VkDescriptorPoolCreateInfo dpi={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=1,.poolSizeCount=2,.pPoolSizes=sizes};
 VkDescriptorPool pool;CK(vkCreateDescriptorPool(d,&dpi,0,&pool));
 VkDescriptorSetAllocateInfo sai={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=pool,.descriptorSetCount=1,.pSetLayouts=&sl};
 VkDescriptorSet ds;CK(vkAllocateDescriptorSets(d,&sai,&ds));
 int ids[6]={0,1,2,2,3,4};VkDescriptorImageInfo ii[6];VkWriteDescriptorSet wr[6];
 for(int i=0;i<6;i++){
   ii[i]=(VkDescriptorImageInfo){i<2?linear:i<4?nearest:VK_NULL_HANDLE,im[ids[i]].v,VK_IMAGE_LAYOUT_GENERAL};
   wr[i]=(VkWriteDescriptorSet){.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=ds,.dstBinding=(uint32_t)i,
    .descriptorCount=1,.descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,.pImageInfo=&ii[i]};
 }
 vkUpdateDescriptorSets(d,6,wr,0,0);
 VkBuffer buf;VkDeviceMemory bm;VkDeviceSize bytes=(VkDeviceSize)wo*ho*4;
 VkBufferCreateInfo bci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=bytes,.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT};
 CK(vkCreateBuffer(d,&bci,0,&buf));VkMemoryRequirements bmr;vkGetBufferMemoryRequirements(d,buf,&bmr);
 int mt=memidx(bmr.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);REQ(mt>=0);
 VkMemoryAllocateInfo bai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=bmr.size,.memoryTypeIndex=(uint32_t)mt};
 CK(vkAllocateMemory(d,&bai,0,&bm));CK(vkBindBufferMemory(d,buf,bm,0));
 VkCommandPoolCreateInfo cpi={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=(uint32_t)qi};
 VkCommandPool cp;CK(vkCreateCommandPool(d,&cpi,0,&cp));
 VkCommandBufferAllocateInfo cbi={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=cp,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
 VkCommandBuffer cb;CK(vkAllocateCommandBuffers(d,&cbi,&cb));
 VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};CK(vkBeginCommandBuffer(cb,&begin));
 VkImageSubresourceRange rg={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
 for(int i=0;i<5;i++){
   VkImageMemoryBarrier bar={.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED,.newLayout=VK_IMAGE_LAYOUT_GENERAL,
   .dstAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
   .image=im[i].img,.subresourceRange=rg};
   vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,0,0,0,1,&bar);
   // YCoCg of sqrt(0.25) -> linear .25 -> tonemap .2.
   VkClearColorValue clear={{i==2?.2f:0.0f,0,0,0}};
   vkCmdClearColorImage(cb,im[i].img,VK_IMAGE_LAYOUT_GENERAL,&clear,1,&rg);
 }
 barrier(cb);
 PC pc={{(float)wi,(float)hi},{(float)wo,(float)ho},{1.0f/wi,1.0f/hi},{1.0f/wo,1.0f/ho},
 {0,0},{(float)wo/wi,10.0f},0.30f,1.0f,1,1,0.15f,0.08f,0.07f,0.15f,1.25f,0.6f,0.8f,0.35f,1.0f,1.0f,2.0f,1.0f,{0}};
 vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,p);
 vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&ds,0,0);
 vkCmdPushConstants(cb,layout,VK_SHADER_STAGE_COMPUTE_BIT,0,128,&pc);
 vkCmdDispatch(cb,(wo+7)/8,(ho+7)/8,1);barrier(cb);
 VkBufferImageCopy c={.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={wo,ho,1}};
 vkCmdCopyImageToBuffer(cb,im[4].img,VK_IMAGE_LAYOUT_GENERAL,buf,1,&c);
 CK(vkEndCommandBuffer(cb));
 VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};
 CK(vkQueueSubmit(q,1,&submit,0));CK(vkQueueWaitIdle(q));
 uint32_t *map;CK(vkMapMemory(d,bm,0,bytes,0,(void**)&map));uint32_t ref=map[(ho/2)*wo+wo/2];
 int bad=0,npx=0;for(int y=20;y<(int)ho-20;y+=9)for(int x=20;x<(int)wo-20;x+=9){npx++;if(map[y*wo+x]!=ref)bad++;}
 printf("GSR2 synthetic reset-frame output=0x%08x nonuniform=%d/%d\n",ref,bad,npx);
 REQ(ref!=0 && bad<npx/15);
 return 0;
}
