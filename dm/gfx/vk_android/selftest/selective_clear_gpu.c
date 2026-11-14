#define VKA_RENDERPASS_TEST
#define NDSR_EXTRA_FNS(X) X(vkCmdClearDepthStencilImage) X(vkCmdBeginRendering) X(vkCmdEndRendering) X(vkCmdClearAttachments)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
static struct{PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier;PFN_vkCmdClearColorImage vkCmdClearColorImage;PFN_vkCmdClearDepthStencilImage vkCmdClearDepthStencilImage;}vk;
static uint64_t vka_n_bar,vka_n_transfer_bar,vka_n_attachment_bar,g_selective_clear_deps;
static int vka_gp_active,opt,nan_scan;
static VkCommandBuffer g_cb;
static void vka_gp_mark(VkCommandBuffer cb,const char*f,int l){(void)cb;(void)f;(void)l;}
#define VKA_ENV(n,d) opt
static int vka_nan_on(void){return nan_scan;}
#include "clear_barriers.inc"
#define vka_barrier(cb) vka_barrier_at(cb,__FILE__,__LINE__)
#define vka_transfer_write_barrier(cb) vka_transfer_write_barrier_at(cb,__FILE__,__LINE__)
#define vka_attachment_parts_barrier(cb,c,d) vka_attachment_parts_barrier_at(cb,c,d,__FILE__,__LINE__)
#define NVN_TEXTURE_TARGET_3D 99
// Match exactly the production function's used fields; the clear_rect adapter
// records real Vulkan attachment clears for the production fallback branch.
typedef struct{struct{int target;}d;struct{VkFormat vk;}f;VkImage img;VkImageView view;unsigned w,h;}vka_img;
typedef struct{vka_img*im;VkClearValue out;int ci,whole;VkFormat fmt;uint32_t l0,nl,lv;VkImageAspectFlags asp;VkRect2D rc;}vka_pclear;
static unsigned vka_img_slices(vka_img*im,uint32_t lv){(void)im;(void)lv;return 1;}
static void clear_rect(vka_img*im,VkFormat fmt,VkImageAspectFlags asp,uint32_t lv,uint32_t l0,uint32_t nl,VkRect2D rc,const VkClearValue*val){
 (void)fmt;(void)lv;(void)l0;(void)nl;
 VkRenderingAttachmentInfo att={VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,.imageView=im->view,.imageLayout=VK_IMAGE_LAYOUT_GENERAL,.loadOp=VK_ATTACHMENT_LOAD_OP_LOAD,.storeOp=VK_ATTACHMENT_STORE_OP_STORE};
 VkRenderingInfo ri={VK_STRUCTURE_TYPE_RENDERING_INFO,.renderArea={{0,0},{im->w,im->h}},.layerCount=1,.colorAttachmentCount=asp==VK_IMAGE_ASPECT_COLOR_BIT?1:0,.pColorAttachments=&att,.pDepthAttachment=asp==VK_IMAGE_ASPECT_DEPTH_BIT?&att:NULL};
 vkCmdBeginRendering(g_cb,&ri);VkClearAttachment ca={.aspectMask=asp,.colorAttachment=0,.clearValue=*val};VkClearRect cr={rc,0,1};vkCmdClearAttachments(g_cb,1,&ca,1,&cr);vkCmdEndRendering(g_cb);
}
#include "clear_policy.inc"
int main(void){
 if(!init())return 77;vk.vkCmdPipelineBarrier=vkCmdPipelineBarrier;vk.vkCmdClearColorImage=vkCmdClearColorImage;vk.vkCmdClearDepthStencilImage=vkCmdClearDepthStencilImage;
 const unsigned sizes[][2]={{64,64},{960,540}};
 for(int s=0;s<2;s++)for(nan_scan=0;nan_scan<2;nan_scan++)for(opt=0;opt<2;opt++){
  unsigned w=sizes[s][0],h=sizes[s][1];vka_img im[2]={0};
  for(int i=0;i<2;i++){im[i].w=w;im[i].h=h;im[i].f.vk=i?VK_FORMAT_D32_SFLOAT:VK_FORMAT_R8G8B8A8_UNORM;im[i].img=image(im[i].f.vk,w,h,(i?VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT:VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT,NULL);VkImageViewCreateInfo vi={VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=im[i].img,.viewType=VK_IMAGE_VIEW_TYPE_2D,.format=im[i].f.vk,.subresourceRange={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};VK(vkCreateImageView(dev,&vi,NULL,&im[i].view));}
  VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&g_cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(g_cb,&bi));
  VkImageMemoryBarrier ib[2];for(int i=0;i<2;i++)ib[i]=(VkImageMemoryBarrier){VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.dstAccessMask=VK_ACCESS_MEMORY_WRITE_BIT|VK_ACCESS_MEMORY_READ_BIT,.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED,.newLayout=VK_IMAGE_LAYOUT_GENERAL,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.image=im[i].img,.subresourceRange={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
  vkCmdPipelineBarrier(g_cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,NULL,0,NULL,2,ib);
  uint64_t full=vka_n_bar,transfer=vka_n_transfer_bar,attach=vka_n_attachment_bar;
  for(int i=0;i<4;i++){
   int depth=i/2,whole=!(i&1);VkClearValue val={0};if(depth)val.depthStencil.depth=whole?0.5f:0.25f;else{val.color.float32[whole?1:0]=1;val.color.float32[3]=1;}
   vka_pclear c={.im=&im[depth],.ci=depth?-1:0,.fmt=im[depth].f.vk,.asp=depth?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,.whole=whole,.nl=1,.out=val,.rc={{w/4,h/4},{w/2,h/2}}};vka_clear_outside(&c);
  }
  CHECK(vka_n_bar-full==(opt&&!nan_scan?0:4),"clear full dependency count mismatch");CHECK(vka_n_transfer_bar-transfer==(opt&&!nan_scan?2:0),"clear transfer dependency count mismatch");CHECK(vka_n_attachment_bar-attach==(opt&&!nan_scan?2:0),"clear attachment dependency count mismatch");
  size_t bytes=(size_t)w*h*4;void*mapped;VkBuffer out=buffer(bytes*2,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&mapped);for(int i=0;i<2;i++){VkBufferImageCopy c={.bufferOffset=i*bytes,.imageSubresource={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={w,h,1}};vkCmdCopyImageToBuffer(g_cb,im[i].img,VK_IMAGE_LAYOUT_GENERAL,out,1,&c);}
  VkMemoryBarrier mb={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};vkCmdPipelineBarrier(g_cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&mb,0,NULL,0,NULL);VK(vkEndCommandBuffer(g_cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&g_cb};VK(vkQueueSubmit(q,1,&si,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
  for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){int rect=x>=w/4&&x<w/4+w/2&&y>=h/4&&y<h/4+h/2;size_t j=(size_t)y*w+x;CHECK(((uint32_t*)mapped)[j]==(rect?0xff0000ffu:0xff00ff00u),"clear colour pixels mismatch");CHECK(((float*)((char*)mapped+bytes))[j]==(rect?0.25f:0.5f),"clear depth pixels mismatch");}
  printf("selective clear parity %ux%u opt%d nan_scan%d:full colour+depth exact\n",w,h,opt,nan_scan);
 }
 return fails?1:0;
}
