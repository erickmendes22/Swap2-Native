// Standalone deterministic GPU test of the production GSR2 upscale shader.
// No game assets, CPU rendering approximation, or Android input required.
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "vka_gsr2_spv.h"
#define CK(x) do { VkResult r=(x);if(r){fprintf(stderr,"%s:%d error %d\n",__FILE__,__LINE__,r);return 2;} }while(0)
#define REQ(x) do {if(!(x)){fprintf(stderr,"assert %s line %d\n",#x,__LINE__);return 2;}}while(0)
static VkDevice d;static VkPhysicalDevice pd;static VkPhysicalDeviceMemoryProperties mm;
static int memidx(uint32_t bits,VkMemoryPropertyFlags fl){for(uint32_t i=0;i<mm.memoryTypeCount;i++)if((bits&(1u<<i))&&(mm.memoryTypes[i].propertyFlags&fl)==fl)return (int)i;return -1;}
typedef struct{VkImage img;VkImageView v;VkDeviceMemory m;uint32_t w,h;} Im;
static Im im[12];static const uint32_t wi=640,hi=360,wo=1280,ho=720;
static int imgnew(int i,VkFormat f,uint32_t w,uint32_t h){
 Im *x=&im[i];x->w=w;x->h=h;
 VkImageCreateInfo ci={.sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,
 .format=f,.extent={w,h,1},.mipLevels=1,.arrayLayers=1,.samples=VK_SAMPLE_COUNT_1_BIT,
 .tiling=VK_IMAGE_TILING_OPTIMAL,.usage=VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|(i==5?0:VK_IMAGE_USAGE_STORAGE_BIT)};
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
typedef struct{float render[2],rcp[2],mvs[2],kfov,reset;int32_t colour_base[2];float vrej,vlo,vk,pad[19];} PCConvert;
_Static_assert(sizeof(PCConvert)==128,"convert PC ABI");
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
 const int push=getenv("GSR2_TEST_PUSH")!=NULL;
 uint32_t ne=0;CK(vkEnumerateDeviceExtensionProperties(pd,NULL,&ne,NULL));
 VkExtensionProperties extensions[1024];REQ(ne<=1024);
 CK(vkEnumerateDeviceExtensionProperties(pd,NULL,&ne,extensions));
 int supported=0;for(uint32_t i=0;i<ne;i++)if(!strcmp(extensions[i].extensionName,VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME))supported=1;
 if(push && !supported){fprintf(stderr,"Mesa ICD has no VK_KHR_push_descriptor\n");return 77;}
 const char *ext=VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME;
 VkDeviceCreateInfo dc={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qc,
 .enabledExtensionCount=push?1u:0u,.ppEnabledExtensionNames=push?&ext:NULL};
 CK(vkCreateDevice(pd,&dc,0,&d));VkQueue q;vkGetDeviceQueue(d,(uint32_t)qi,0,&q);
 PFN_vkCmdPushDescriptorSetKHR cmdPush=push?(PFN_vkCmdPushDescriptorSetKHR)vkGetDeviceProcAddr(d,"vkCmdPushDescriptorSetKHR"):NULL;
 REQ(!push||cmdPush);fprintf(stderr,"GSR2 descriptor path: %s\n",push?"push":"allocated");
 vkGetPhysicalDeviceMemoryProperties(pd,&mm);
 for(int i=0;i<12;i++) {
 VkFormat fmt=i==4?VK_FORMAT_R32_UINT:i==5?VK_FORMAT_B10G11R11_UFLOAT_PACK32:VK_FORMAT_R16G16B16A16_SFLOAT;
 uint32_t w=(i==1||i==2||i>=5)?wi:wo,h=(i==1||i==2||i>=5)?hi:ho;
  if(imgnew(i,fmt,w,h))return 2;
 }
 VkDescriptorSetLayoutBinding lb[6];for(int i=0;i<6;i++)lb[i]=(VkDescriptorSetLayoutBinding){
 .binding=i,.descriptorCount=1,.descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
 VkDescriptorSetLayoutCreateInfo lci={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
 .flags=push?VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR:0,.bindingCount=6,.pBindings=lb};
 VkDescriptorSetLayout sl;CK(vkCreateDescriptorSetLayout(d,&lci,0,&sl));
 VkPushConstantRange range={VK_SHADER_STAGE_COMPUTE_BIT,0,128};
 VkPipelineLayoutCreateInfo plci={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
 .setLayoutCount=1,.pSetLayouts=&sl,.pushConstantRangeCount=1,.pPushConstantRanges=&range};
 VkPipelineLayout layout;CK(vkCreatePipelineLayout(d,&plci,0,&layout));
 const uint32_t *modules[4]={vka_gsr2_flow,vka_gsr2_convert,vka_gsr2_activate,vka_gsr2_upscale};
 const size_t modulesz[4]={sizeof vka_gsr2_flow,sizeof vka_gsr2_convert,sizeof vka_gsr2_activate,sizeof vka_gsr2_upscale};
 VkPipeline pipes[4];
 for(int st=0;st<4;st++){
  VkShaderModuleCreateInfo smi={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=modulesz[st],.pCode=modules[st]};
  VkShaderModule sm;CK(vkCreateShaderModule(d,&smi,0,&sm));
  VkComputePipelineCreateInfo pi={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
   .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=sm,.pName="main"},.layout=layout};
  CK(vkCreateComputePipelines(d,0,1,&pi,0,&pipes[st]));
 }
 VkSamplerCreateInfo sci={.sType=VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,.magFilter=VK_FILTER_LINEAR,.minFilter=VK_FILTER_LINEAR,
 .mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
 .addressModeV=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.maxLod=.25f};
 VkSampler nearest,linear;CK(vkCreateSampler(d,&sci,0,&linear));sci.magFilter=sci.minFilter=VK_FILTER_NEAREST;CK(vkCreateSampler(d,&sci,0,&nearest));
 VkDescriptorPoolSize sizes[2]={{VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,16},{VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,8}};
 VkDescriptorPoolCreateInfo dpi={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=4,.poolSizeCount=2,.pPoolSizes=sizes};
 VkDescriptorSet ds[4]={0};
 if(!push){
 VkDescriptorPool pool;CK(vkCreateDescriptorPool(d,&dpi,0,&pool));
 VkDescriptorSetLayout lays[4]={sl,sl,sl,sl};
 VkDescriptorSetAllocateInfo sai={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=pool,.descriptorSetCount=4,.pSetLayouts=lays};
 CK(vkAllocateDescriptorSets(d,&sai,ds));
 }
 const int ids[4][6]={
 {5,7,5,5,6,6},    // flow: current source and previous YCC -> flow
 {5,5,6,5,2,8},    // convert: colour, flow -> YCC, MDA
 {10,8,2,9,1,11},  // activate: previous luma, MDA -> MDC, current luma
 {0,1,2,2,3,4}};  // upscale: previous hist, MDC, YCC -> history, output
 for(int st=0;st<4;st++){
  VkDescriptorImageInfo ii[6];VkWriteDescriptorSet wr[6];
  for(int i=0;i<6;i++){
   ii[i]=(VkDescriptorImageInfo){i<2&&st==3?linear:nearest,im[ids[st][i]].v,VK_IMAGE_LAYOUT_GENERAL};
   if(i>=4)ii[i].sampler=VK_NULL_HANDLE;
   wr[i]=(VkWriteDescriptorSet){.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=ds[st],.dstBinding=(uint32_t)i,
    .descriptorCount=1,.descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,.pImageInfo=&ii[i]};
  }
  if(!push)vkUpdateDescriptorSets(d,6,wr,0,0);
 }
 VkBuffer buf;VkDeviceMemory bm;VkDeviceSize bytes=(VkDeviceSize)wo*ho*4;
 VkBufferCreateInfo bci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=bytes,.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT};
 CK(vkCreateBuffer(d,&bci,0,&buf));VkMemoryRequirements bmr;vkGetBufferMemoryRequirements(d,buf,&bmr);
 int mt=memidx(bmr.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);REQ(mt>=0);
 VkMemoryAllocateInfo bai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=bmr.size,.memoryTypeIndex=(uint32_t)mt};
 CK(vkAllocateMemory(d,&bai,0,&bm));CK(vkBindBufferMemory(d,buf,bm,0));
 // Real packed B10G11R11 input: contrasting red/green/blue/grey tiles.
 uint32_t *in;CK(vkMapMemory(d,bm,0,bytes,0,(void**)&in));
 const uint32_t rbits=0x380u,gbits=0x380u<<11,bbits=0x1c0u<<22;
 for(uint32_t y=0;y<hi;y++)for(uint32_t x=0;x<wi;x++){
   int k=((int)x/40+(int)y/30)%4;
   in[y*wi+x]=k==0?rbits:k==1?gbits:k==2?bbits:(rbits|gbits|bbits);
 }
 vkUnmapMemory(d,bm);
 VkCommandPoolCreateInfo cpi={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=(uint32_t)qi};
 VkCommandPool cp;CK(vkCreateCommandPool(d,&cpi,0,&cp));
 VkCommandBufferAllocateInfo cbi={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=cp,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
 VkCommandBuffer cb;CK(vkAllocateCommandBuffers(d,&cbi,&cb));
 VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};CK(vkBeginCommandBuffer(cb,&begin));
 VkImageSubresourceRange rg={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
 for(int i=0;i<12;i++){
   VkImageMemoryBarrier bar={.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED,.newLayout=VK_IMAGE_LAYOUT_GENERAL,
   .dstAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
   .image=im[i].img,.subresourceRange=rg};
   vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,0,0,0,1,&bar);
   // YCoCg of sqrt(0.25) -> linear .25 -> tonemap .2.
   VkClearColorValue clear={{i==5?.5f:0.0f,i==5?.5f:0.0f,i==5?.5f:0.0f,0}};
   vkCmdClearColorImage(cb,im[i].img,VK_IMAGE_LAYOUT_GENERAL,&clear,1,&rg);
 }
 barrier(cb);
 // Transfer native packed input after image initialization, before optical flow.
 VkBufferImageCopy icopy={.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={wi,hi,1}};
 vkCmdCopyBufferToImage(cb,buf,im[5].img,VK_IMAGE_LAYOUT_GENERAL,1,&icopy);
 barrier(cb);
 PC pc={{(float)wi,(float)hi},{(float)wo,(float)ho},{1.0f/wi,1.0f/hi},{1.0f/wo,1.0f/ho},
 {0,0},{(float)wo/wi,10.0f},0.30f,1.0f,1,1,0.15f,0.08f,0.07f,0.15f,1.25f,0.6f,0.8f,0.35f,1.0f,1.0f,2.0f,1.0f,{0}};
 PCConvert cv={{(float)wi,(float)hi},{1.0f/wi,1.0f/hi},{1.0f/wi,1.0f/hi},1.0f,1.0f,{0,0},1.0f,0.35f,0.3f,{0}};
 for(int st=0;st<4;st++){
  vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipes[st]);
  if(push){
    VkDescriptorImageInfo pi[6];VkWriteDescriptorSet wr[6];
    for(int i=0;i<6;i++){
      pi[i]=(VkDescriptorImageInfo){i<2&&st==3?linear:i<4?nearest:VK_NULL_HANDLE,im[ids[st][i]].v,VK_IMAGE_LAYOUT_GENERAL};
      wr[i]=(VkWriteDescriptorSet){.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
      .dstBinding=(uint32_t)i,.descriptorCount=1,
      .descriptorType=i<4?VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,.pImageInfo=&pi[i]};
    }
    cmdPush(cb,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,6,wr);
  } else vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&ds[st],0,0);
  vkCmdPushConstants(cb,layout,VK_SHADER_STAGE_COMPUTE_BIT,0,128,st==0||st==3?(const void*)&pc:(const void*)&cv);
  uint32_t w=st==3?wo:wi,h=st==3?ho:hi;
  vkCmdDispatch(cb,(w+7)/8,(h+7)/8,1);barrier(cb);
 }
 VkBufferImageCopy c={.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={wo,ho,1}};
 vkCmdCopyImageToBuffer(cb,im[4].img,VK_IMAGE_LAYOUT_GENERAL,buf,1,&c);
 CK(vkEndCommandBuffer(cb));
 VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};
 CK(vkQueueSubmit(q,1,&submit,0));CK(vkQueueWaitIdle(q));
 uint32_t *map;CK(vkMapMemory(d,bm,0,bytes,0,(void**)&map));
 int bad=0,npx=0;
 for(int sy=15;sy<(int)hi-15;sy+=30)for(int sx=20;sx<(int)wi-20;sx+=40){
   int k=(sx/40+sy/30)%4,ox=2*sx,oy=2*sy;
   uint32_t pix=map[oy*wo+ox];
   unsigned rr=pix&0x7ffu,gg=(pix>>11)&0x7ffu,bb=(pix>>22)&0x3ffu;
   int reject=pix==0 ||
     (k==0 && !(rr>4*gg&&rr>4*bb)) ||
     (k==1 && !(gg>4*rr&&gg>4*bb)) ||
     (k==2 && !(bb>rr&&bb>gg)) ||
     (k==3 && !(rr>200&&gg>200&&bb>100));
   for(int dy=-2;dy<=2;dy+=2)for(int dx=-2;dx<=2;dx+=2)
     if(map[(oy+dy)*wo+(ox+dx)]!=pix)reject++;
   if(reject)bad++;
   npx++;
 }
 printf("GSR2 four-pass COLOR+EDGES reset-frame bad blocks %d/%d\n",bad,npx);
 REQ(npx>=100 && bad<npx/10);
 return 0;
}
