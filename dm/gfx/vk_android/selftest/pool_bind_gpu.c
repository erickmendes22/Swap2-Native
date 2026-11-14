#define NDSR_EXTRA_FNS(X) X(vkCmdFillBuffer)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include "vka_pool_bind_cache.h"
static VkShaderModule shader(void){FILE*f=fopen(getenv("POOL_COMP"),"rb");if(!f)exit(3);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint32_t*w=malloc(n);if(fread(w,1,n,f)!=(size_t)n)exit(3);fclose(f);VkShaderModuleCreateInfo ci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=n,.pCode=w};VkShaderModule m;VK(vkCreateShaderModule(dev,&ci,NULL,&m));free(w);return m;}
static void dependency(VkCommandBuffer cb,VkPipelineStageFlags src,VkPipelineStageFlags dst,VkAccessFlags a,VkAccessFlags b){VkMemoryBarrier mb={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=a,.dstAccessMask=b};vkCmdPipelineBarrier(cb,src,dst,0,1,&mb,0,NULL,0,NULL);}
int main(void){
 if(!init())return 77;
 // Different push ranges make these layouts incompatible, although their
 // descriptor layouts match. Higher sets MUST be rebound after switching.
 VkDescriptorSetLayout dl[3];for(int i=0;i<3;i++){VkDescriptorSetLayoutBinding b={0,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,NULL};VkDescriptorSetLayoutCreateInfo ci={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=1,.pBindings=&b};VK(vkCreateDescriptorSetLayout(dev,&ci,NULL,&dl[i]));}
 VkPipelineLayout layout[2];VkPipeline pipeline[2];VkShaderModule module=shader();
 for(int i=0;i<2;i++){VkPushConstantRange pc={VK_SHADER_STAGE_COMPUTE_BIT,0,i?8:4};VkPipelineLayoutCreateInfo ci={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=3,.pSetLayouts=dl,.pushConstantRangeCount=1,.pPushConstantRanges=&pc};VK(vkCreatePipelineLayout(dev,&ci,NULL,&layout[i]));VkComputePipelineCreateInfo cp={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=module,.pName="main"},.layout=layout[i]};VK(vkCreateComputePipelines(dev,VK_NULL_HANDLE,1,&cp,NULL,&pipeline[i]));}
 VkDescriptorPoolSize ps={VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,5};VkDescriptorPoolCreateInfo dpi={VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=5,.poolSizeCount=1,.pPoolSizes=&ps};VkDescriptorPool dp;VK(vkCreateDescriptorPool(dev,&dpi,NULL,&dp));
 VkDescriptorSetLayout layouts[5]={dl[0],dl[1],dl[1],dl[2],dl[2]};VkDescriptorSet sets[5];VkDescriptorSetAllocateInfo ai={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=dp,.descriptorSetCount=5,.pSetLayouts=layouts};VK(vkAllocateDescriptorSets(dev,&ai,sets));
 void*m[5];VkBuffer b[5];for(int i=0;i<5;i++)b[i]=buffer(512,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,&m[i]);
 VkDescriptorBufferInfo info[5];VkWriteDescriptorSet writes[5];for(int i=0;i<5;i++){info[i]=(VkDescriptorBufferInfo){b[i],0,512};writes[i]=(VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=sets[i],.dstBinding=0,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.descriptorCount=1,.pBufferInfo=&info[i]};}vkUpdateDescriptorSets(dev,5,writes,0,NULL);
 for(int opt=0;opt<2;opt++){
  memset(m[0],0,512);memset(m[3],0,512);memset(m[4],0,512);((uint32_t*)m[1])[0]=0x1234;((uint32_t*)m[2])[0]=0xabcd;
  uint32_t values[2]={0x1234,0xabcd},expected[128],fb[2][128]={{0}};vka_pool_bind_cache cache={0};unsigned emitted=0,reused=0;
  VkCommandBuffer cb;VkCommandBufferAllocateInfo ac={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ac,&cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
  for(uint32_t i=0;i<128;i++){
   int l=i/16%2,p=i/8%2,f=i/4%2;
   if(i==48){dependency(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT,VK_ACCESS_TRANSFER_WRITE_BIT);vkCmdFillBuffer(cb,b[1],0,4,0x1111);dependency(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_ACCESS_TRANSFER_WRITE_BIT,VK_ACCESS_SHADER_READ_BIT);values[0]=0x1111;}
   vka_pool_bind_prepare(&cache,layout[l],i%31!=0);
   vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline[l]);vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,layout[l],0,1,&sets[0],0,NULL);
   VkDescriptorSet pair[2]={sets[1+p],sets[3+f]};
   if(opt&&vka_pool_bind_same(&cache,layout[l],pair,2))reused++;else{if(!opt)cache.valid=0;vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,layout[l],1,2,pair,0,NULL);emitted++;}
   vkCmdPushConstants(cb,layout[l],VK_SHADER_STAGE_COMPUTE_BIT,0,4,&i);vkCmdDispatch(cb,1,1,1);expected[i]=values[p]^i;fb[f][i]=values[p]+i;
  }
  dependency(cb,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,VK_ACCESS_SHADER_WRITE_BIT,VK_ACCESS_HOST_READ_BIT);VK(vkEndCommandBuffer(cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&si,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
  CHECK(!memcmp(m[0],expected,512),"pool output mismatch");CHECK(!memcmp(m[3],fb[0],512)&&!memcmp(m[4],fb[1],512),"feedback mismatch");CHECK(emitted+reused==128&&(!opt||reused>0),"pool dedup never selected");printf("pool GPU parity opt%d:128 outputs and256 feedback slots exact; binds%u skipped%u; incompatible layouts and changed buffer data preserved\n",opt,emitted,reused);
 }
 return fails?1:0;
}
