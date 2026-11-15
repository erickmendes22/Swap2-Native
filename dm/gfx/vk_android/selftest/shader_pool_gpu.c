// Actual NVN shader-pool queries and storage binding, actual Vulkan allocations.
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include <stdatomic.h>
#include <pthread.h>
#include <sched.h>
#include <stdarg.h>
#include "nvn_obj.h"
static void log_stub(const char*fmt,...){(void)fmt;}
#define LOG(...) log_stub(__VA_ARGS__)
#define NVN(name,ret,...) static ret h_##name(__VA_ARGS__)
static pool_t guest[2];static VkBuffer gpu[2];static uint64_t committed;
static void mtl_pool_need(const void*p,uint64_t n,const char*why){
 (void)why;
 for(int i=0;i<2;i++)if((uintptr_t)p>=(uintptr_t)guest[i].mem&&(uintptr_t)p+n<=(uintptr_t)guest[i].mem+guest[i].size){
  if(!gpu[i]){void*out;gpu[i]=buffer(guest[i].size,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,&out);memcpy(out,guest[i].mem,guest[i].size);committed+=guest[i].size;}return;
 }
 CHECK(0,"GPU address outside the registered pool");
}
static uint64_t dm_guest_unmapped(uintptr_t a,uint64_t n){(void)a;(void)n;return 0;}
static void pc_use(const pool_t*p,char k,uint64_t a,uint64_t n){(void)p;(void)k;(void)a;(void)n;}
static p_bind_buf recorded;
#define REC(c,op,type) ((type*)&recorded)
static void ssbo_slot_check(int s,int i){(void)s;(void)i;}
#include "shader_pool_policy.inc"
#include "shader_pool_hooks.inc"
static VkShaderModule shader(void){
 FILE*f=fopen(getenv("SYNC_COMP"),"rb");if(!f)exit(3);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint32_t*w=malloc(n);if(fread(w,1,n,f)!=(size_t)n)exit(3);fclose(f);
 VkShaderModuleCreateInfo ci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=n,.pCode=w};VkShaderModule m;VK(vkCreateShaderModule(dev,&ci,NULL,&m));free(w);return m;
}
int main(void){
 if(!init())return 77;
 VkDescriptorSetLayoutBinding binding[2]={{0,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL},{1,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL}};
 VkDescriptorSetLayoutCreateInfo dlci={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=2,.pBindings=binding};VkDescriptorSetLayout layout;VK(vkCreateDescriptorSetLayout(dev,&dlci,NULL,&layout));
 VkPushConstantRange pc={VK_SHADER_STAGE_COMPUTE_BIT,0,4};VkPipelineLayoutCreateInfo plci={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=1,.pSetLayouts=&layout,.pushConstantRangeCount=1,.pPushConstantRanges=&pc};VkPipelineLayout pipeline_layout;VK(vkCreatePipelineLayout(dev,&plci,NULL,&pipeline_layout));
 VkComputePipelineCreateInfo pci={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=shader(),.pName="main"},.layout=pipeline_layout};VkPipeline pipeline;VK(vkCreateComputePipelines(dev,VK_NULL_HANDLE,1,&pci,NULL,&pipeline));
 VkDescriptorPoolSize ps={VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,4};VkDescriptorPoolCreateInfo dpci={VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=2,.poolSizeCount=1,.pPoolSizes=&ps};VkDescriptorPool dp;VK(vkCreateDescriptorPool(dev,&dpci,NULL,&dp));
 uint32_t expected[1024];
 for(int defer=0;defer<2;defer++){
  g_shp_place=!defer;g_shp_log=0;committed=0;memset(gpu,0,sizeof gpu);
  guest[0]=(pool_t){.mem=malloc(1u<<20),.size=1u<<20};guest[1]=(pool_t){.mem=malloc(4096),.size=4096};
  memset(guest[0].mem,0x6d,guest[0].size);for(uint32_t i=0;i<1024;i++)((uint32_t*)guest[1].mem)[i]=i*17+3;
  for(int i=0;i<2;i++){shp_add(&guest[i],i+1);CHECK(h_nvnMemoryPoolGetBufferAddress((NVNmemoryPool*)&guest[i])==(uintptr_t)guest[i].mem,"guest address changed");}
  CHECK(committed==(defer?0:(1u<<20)+4096),"query committed unused shader memory");
  CHECK(nvn_shader_code_readable((uintptr_t)guest[0].mem,64),"unplaced program code not readable");
  h_nvnCommandBufferBindStorageBuffer(NULL,5,0,(uintptr_t)guest[1].mem,4096);
  CHECK(recorded.addr==(uintptr_t)guest[1].mem&&recorded.size==4096,"binding record changed");
  CHECK(gpu[1]&&committed==(defer?4096:(1u<<20)+4096),"mixed shader-pool data was not materialized");
  void*out;VkBuffer ob=buffer(4096,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,&out);
  VkDescriptorSetAllocateInfo dai={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=dp,.descriptorSetCount=1,.pSetLayouts=&layout};VkDescriptorSet ds;VK(vkAllocateDescriptorSets(dev,&dai,&ds));
  VkDescriptorBufferInfo info[2]={{gpu[1],0,4096},{ob,0,4096}};VkWriteDescriptorSet wr[2];for(int i=0;i<2;i++)wr[i]=(VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=ds,.dstBinding=i,.descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.pBufferInfo=&info[i]};vkUpdateDescriptorSets(dev,2,wr,0,NULL);
  VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
  vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline_layout,0,1,&ds,0,NULL);uint32_t seed=0x12345678;vkCmdPushConstants(cb,pipeline_layout,VK_SHADER_STAGE_COMPUTE_BIT,0,4,&seed);vkCmdDispatch(cb,16,1,1);
  VkMemoryBarrier host={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&host,0,NULL,0,NULL);
  VK(vkEndCommandBuffer(cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&si,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
  for(uint32_t i=0;i<1024;i++){uint32_t ix=(i&~63u)|((i+1)&63u);uint32_t value=((ix*17+3)^seed)+i;CHECK(((uint32_t*)out)[i]==value,"GPU data mismatch after deferred placement");if(!defer)expected[i]=((uint32_t*)out)[i];else CHECK(expected[i]==((uint32_t*)out)[i],"enabled/disabled mismatch");}
  printf("shader pool deferral%d:4096 bytes exact; committed %llu bytes\n",defer,(unsigned long long)committed);
  for(int i=0;i<2;i++){shp_del(&guest[i]);free(guest[i].mem);}
 }
 return fails?1:0;
}
