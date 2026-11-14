// Actual dependency policies, real storage writes, shared memory, indirect
// launch and chained transfer/compute consumers. No optional device extension.
#define NDSR_EXTRA_FNS(X) X(vkCmdCopyBuffer) X(vkCmdFillBuffer) X(vkCmdDispatchIndirect)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
static struct{PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier;}vk;
static uint64_t vka_n_bar,vka_n_transfer_bar,vka_n_compute_bar,vka_n_attachment_bar;
static uint64_t g_selective_transfer_deps,g_dispatch_selective_deps,g_dispatch_arg_deps;
static int vka_gp_active,opt,boost,nan_scan;
static void vka_gp_mark(VkCommandBuffer cb,const char*f,int l){(void)cb;(void)f;(void)l;}
static int env_value(const char *n,int def){
 if(!strcmp(n,"DM_VK_ATTACHMENT_PARTS"))return opt;
 if(!strcmp(n,"DM_VK_OOT_FPS_BOOST"))return boost;
 return def;
}
#define VKA_ENV(n,d) env_value(n,d)
#define DM_GAME_ID "0400486024DEC000"
static int vka_nan_on(void){return nan_scan;}
#include "sync_barriers.inc"
#define vka_barrier(cb) vka_barrier_at(cb,__FILE__,__LINE__)
#define vka_transfer_write_barrier(cb) vka_transfer_write_barrier_at(cb,__FILE__,__LINE__)
#define vka_compute_write_barrier(cb) vka_compute_write_barrier_at(cb,__FILE__,__LINE__)
#include "sync_policies.inc"
static VkShaderModule shader(void){
 FILE*f=fopen(getenv("SYNC_COMP"),"rb");if(!f)exit(3);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint32_t*w=malloc(n);if(fread(w,1,n,f)!=(size_t)n)exit(3);fclose(f);
 VkShaderModuleCreateInfo ci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=n,.pCode=w};VkShaderModule m;VK(vkCreateShaderModule(dev,&ci,NULL,&m));free(w);return m;
}
int main(void){
 if(!init())return 77;vk.vkCmdPipelineBarrier=vkCmdPipelineBarrier;
 VkDescriptorSetLayoutBinding binding[2]={{0,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL},{1,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL}};
 VkDescriptorSetLayoutCreateInfo dlci={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=2,.pBindings=binding};VkDescriptorSetLayout layout;VK(vkCreateDescriptorSetLayout(dev,&dlci,NULL,&layout));
 VkPushConstantRange pc={VK_SHADER_STAGE_COMPUTE_BIT,0,4};VkPipelineLayoutCreateInfo plci={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=1,.pSetLayouts=&layout,.pushConstantRangeCount=1,.pPushConstantRanges=&pc};VkPipelineLayout pipeline_layout;VK(vkCreatePipelineLayout(dev,&plci,NULL,&pipeline_layout));
 VkComputePipelineCreateInfo pci={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=shader(),.pName="main"},.layout=pipeline_layout};VkPipeline pipeline;VK(vkCreateComputePipelines(dev,VK_NULL_HANDLE,1,&pci,NULL,&pipeline));
 VkDescriptorPoolSize ps={VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,4};VkDescriptorPoolCreateInfo dpci={VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=2,.poolSizeCount=1,.pPoolSizes=&ps};VkDescriptorPool dp;VK(vkCreateDescriptorPool(dev,&dpci,NULL,&dp));
 VkDescriptorSetLayout layouts[2]={layout,layout};VkDescriptorSetAllocateInfo dai={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=dp,.descriptorSetCount=2,.pSetLayouts=layouts};VkDescriptorSet ds[2];VK(vkAllocateDescriptorSets(dev,&dai,ds));
 void*ptr[6];VkBuffer buf[6];for(int i=0;i<6;i++)buf[i]=buffer(i>=4?16:4096,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT|(i==5?VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT:0),&ptr[i]);
 ((uint32_t*)ptr[4])[0]=16;((uint32_t*)ptr[4])[1]=1;((uint32_t*)ptr[4])[2]=1;
 VkDescriptorBufferInfo info[4]={{buf[0],0,4096},{buf[1],0,4096},{buf[2],0,4096},{buf[3],0,4096}};VkWriteDescriptorSet wr[4];for(int i=0;i<4;i++)wr[i]=(VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=ds[i/2],.dstBinding=i%2,.descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.pBufferInfo=&info[i]};vkUpdateDescriptorSets(dev,4,wr,0,NULL);
 for(nan_scan=0;nan_scan<2;nan_scan++)for(opt=0;opt<2;opt++)for(boost=0;boost<2;boost++)for(int indirect=0;indirect<2;indirect++)for(int spill=0;spill<2;spill++){
  VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
  uint64_t full0=vka_n_bar,trans0=vka_n_transfer_bar,compute0=vka_n_compute_bar;
  vka_barrier(cb);vkCmdFillBuffer(cb,buf[0],0,4096,0x12345678u);boost_transfer_barrier(cb);
  vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline_layout,0,1,&ds[0],0,NULL);uint32_t seed=0x10203040u;vkCmdPushConstants(cb,pipeline_layout,VK_SHADER_STAGE_COMPUTE_BIT,0,4,&seed);
  if(indirect){VkBufferCopy c={0,0,12};vkCmdCopyBuffer(cb,buf[4],buf[5],1,&c);dispatch_argument_barrier(cb);vkCmdDispatchIndirect(cb,buf[5],0);}else vkCmdDispatch(cb,16,1,1);
  dispatch_write_barrier(cb,spill,indirect,UINT64_C(0x1122334455667788));
  VkBufferCopy c={0,0,4096};vkCmdCopyBuffer(cb,buf[1],buf[2],1,&c);boost_transfer_barrier(cb);
  vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline_layout,0,1,&ds[1],0,NULL);seed=0xa1b2c3d4u;vkCmdPushConstants(cb,pipeline_layout,VK_SHADER_STAGE_COMPUTE_BIT,0,4,&seed);vkCmdDispatch(cb,16,1,1);dispatch_write_barrier(cb,spill,0,UINT64_C(0x1122334455667788));
  int tx=boost||(opt&&!nan_scan),cs=opt&&!nan_scan;
  CHECK(vka_n_bar-full0==(uint64_t)(1+(tx?0:2)+(cs?0:2)+(indirect&&!cs?1:0)),"unexpected full barrier selection");
  CHECK(vka_n_transfer_bar-trans0==(uint64_t)((tx?2:0)+(indirect&&cs?1:0)),"transfer path not selected");
  CHECK(vka_n_compute_bar-compute0==(uint64_t)(cs?2:0),"compute path not selected");
  VkMemoryBarrier host={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&host,0,NULL,0,NULL);
  VK(vkEndCommandBuffer(cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&si,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
  for(uint32_t i=0;i<1024;i++){uint32_t rotated=(i&~63u)|((i+1)&63u);uint32_t expected=(((0x12345678u^0x10203040u)+rotated)^0xa1b2c3d4u)+i;CHECK(((uint32_t*)ptr[3])[i]==expected,"compute/transfer chain mismatch");}
  printf("selective sync parity nan_scan%d opt%d boost%d indirect%d spill%d:4096 bytes exact\n",nan_scan,opt,boost,indirect,spill);
 }
 return fails?1:0;
}
