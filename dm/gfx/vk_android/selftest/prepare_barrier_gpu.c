// Execute the actual submission prefix on Vulkan, including a real GPU write
// before it and optional preparation writes between its two dependencies.
#define NDSR_EXTRA_FNS(X) X(vkCmdFillBuffer) X(vkCmdCopyBuffer)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
static struct { PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier; } vk;
static uint64_t vka_n_bar, g_prepare_barriers_removed;
static int vka_gp_active;
static void vka_gp_mark(VkCommandBuffer cb,const char*f,int l){(void)cb;(void)f;(void)l;}
#include "full_barrier.inc"
#define vka_barrier(cb) vka_barrier_at(cb,__FILE__,__LINE__)
static VkCommandBuffer g_cb;
static VkBuffer source;
static int opt, prep;
#define VKA_ENV(name,def) opt
static int vka_tex_prepare(VkCommandBuffer cb){
 if(prep==1)vkCmdFillBuffer(cb,source,0,4096,0x87654321u);
 // Cases2/3: conservatively retained dependency for a sparse/descriptor
 // preparation attempt even if that attempt recorded no transfer.
 return prep!=0;
}
static void submission_prefix(void){
#include "prepare_prefix.inc"
}
int main(void){
 if(!init())return 77;vk.vkCmdPipelineBarrier=vkCmdPipelineBarrier;
 void *unused,*mapped;source=buffer(4096,VK_BUFFER_USAGE_TRANSFER_DST_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT,&unused);
 VkBuffer output=buffer(4096,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&mapped);
 for(prep=0;prep<4;prep++)for(opt=0;opt<2;opt++){
  VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));
  VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));g_cb=cb;
  vkCmdFillBuffer(cb,source,0,4096,0x12345678u);
  uint64_t barriers=vka_n_bar,removed=g_prepare_barriers_removed;
  submission_prefix();
  CHECK(vka_n_bar-barriers==(opt&&prep==0?1:2),"wrong dependency count");
  CHECK(g_prepare_barriers_removed-removed==(opt&&prep==0?1:0),"wrong removed count");
  VkBufferCopy copy={0,0,4096};vkCmdCopyBuffer(cb,source,output,1,&copy);
  VkMemoryBarrier host={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&host,0,NULL,0,NULL);
  VK(vkEndCommandBuffer(cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&si,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
  for(int i=0;i<1024;i++)CHECK(((uint32_t*)mapped)[i]==(prep==1?0x87654321u:0x12345678u),"GPU preparation readback mismatch");
  printf("prepare GPU parity prep%d opt%d:4096 bytes exact,%llu full dependencies\n",prep,opt,(unsigned long long)(vka_n_bar-barriers));
 }
 return fails?1:0;
}
