// Exercise the production Banana-derived cache on Vulkan and compare dynamic
// rendering with cached classic passes. No captured game shaders or assets.
#define VKA_RENDERPASS_TEST
#define NDSR_EXTRA_FNS(X) X(vkCreateRenderPass) X(vkCreateFramebuffer) X(vkCmdBeginRenderPass) X(vkCmdEndRenderPass) X(vkCmdBeginRendering) X(vkCmdEndRendering) X(vkCreateGraphicsPipelines) X(vkCmdDraw) X(vkCmdClearAttachments) X(vkCmdSetScissor)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include <pthread.h>
#include <time.h>
static struct { VkDevice dev; } V;
static struct {
 PFN_vkCreateRenderPass vkCreateRenderPass;
 PFN_vkCreateFramebuffer vkCreateFramebuffer;
} vk;
typedef struct {
 VkImageCreateFlags cflags; VkImageUsageFlags usage;
 struct { VkFormat vk; } f;
 uint32_t w,h,nvf;VkFormat vf[6];
} vka_img;
#define VLOG(...) ((void)0)
#define VRED_ONCE(...) fprintf(stderr,__VA_ARGS__)
#include "vka_renderpass_cache.h"
static double seconds(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static VkShaderModule module(const char *name){FILE *f=fopen(getenv(name),"rb");CHECK(f,"shader file");fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint32_t *b=malloc(n);CHECK(fread(b,1,n,f)==(size_t)n,"shader read");fclose(f);VkShaderModuleCreateInfo ci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=n,.pCode=b};VkShaderModule m;VK(vkCreateShaderModule(dev,&ci,NULL,&m));free(b);return m;}
static VkPipeline graphics(VkPipelineLayout layout,VkRenderPass rp,int width,int height){
 VkPipelineShaderStageCreateInfo sh[2]={{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_VERTEX_BIT,.module=module("RP_VERT"),.pName="main"},{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_FRAGMENT_BIT,.module=module("RP_FRAG"),.pName="main"}};
 VkPipelineVertexInputStateCreateInfo vi={VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
 VkPipelineInputAssemblyStateCreateInfo ia={VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
 VkViewport viewport={0,0,width,height,0,1};VkRect2D rect={{0,0},{width,height}};
 VkPipelineViewportStateCreateInfo vp={VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,.viewportCount=1,.pViewports=&viewport,.scissorCount=1,.pScissors=&rect};
 VkPipelineRasterizationStateCreateInfo rs={VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,.polygonMode=VK_POLYGON_MODE_FILL,.lineWidth=1};
 VkPipelineMultisampleStateCreateInfo ms={VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT};
 VkPipelineColorBlendAttachmentState att[2]={{.colorWriteMask=15},{.colorWriteMask=15}};
 VkPipelineColorBlendStateCreateInfo bs={VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,.attachmentCount=2,.pAttachments=att};
 VkFormat fmts[2]={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R8G8B8A8_UNORM};VkPipelineRenderingCreateInfo ri={VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO,.colorAttachmentCount=2,.pColorAttachmentFormats=fmts};
 VkDynamicState dynamic=VK_DYNAMIC_STATE_SCISSOR;VkPipelineDynamicStateCreateInfo dyn={VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,.dynamicStateCount=1,.pDynamicStates=&dynamic};
 VkGraphicsPipelineCreateInfo ci={VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,.pDynamicState=&dyn,.pNext=rp?NULL:&ri,.stageCount=2,.pStages=sh,.pVertexInputState=&vi,.pInputAssemblyState=&ia,.pViewportState=&vp,.pRasterizationState=&rs,.pMultisampleState=&ms,.pColorBlendState=&bs,.layout=layout,.renderPass=rp};
 VkPipeline result;VK(vkCreateGraphicsPipelines(dev,VK_NULL_HANDLE,1,&ci,NULL,&result));return result;
}
static double compare(int width,int height,int classic,uint8_t *output){
 VkImageView views[2];VkImage im[2];vka_img meta={.usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT,.f={VK_FORMAT_R8G8B8A8_UNORM},.w=width,.h=height};
 for(int i=0;i<2;i++)im[i]=image(meta.f.vk,width,height,meta.usage,&views[i]);
 rpkey k={.cf={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R8G8B8A8_UNORM},.n=2,.samples=1};
 VkRenderPass compat=vka_rp_compat(k.cf,2,0,0,1);CHECK(compat && compat==vka_rp_compat(k.cf,2,0,0,1),"render pass cache miss");
 VkPushConstantRange range={VK_SHADER_STAGE_FRAGMENT_BIT,0,16};VkPipelineLayoutCreateInfo li={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.pushConstantRangeCount=1,.pPushConstantRanges=&range};VkPipelineLayout layout;VK(vkCreatePipelineLayout(dev,&li,NULL,&layout));
 VkPipeline pipeline=graphics(layout,classic?compat:VK_NULL_HANDLE,width,height);
 size_t size=(size_t)width*height*4;void *mapped;VkBuffer dst=buffer(2*size,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&mapped);
 VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));
 VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
 for(int i=0;i<2;i++)barrier(cb,im[i],VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_GENERAL);
 double start=seconds();
 for(int pass=0;pass<150;pass++){
  VkRenderingAttachmentInfo at[2];VkClearValue clear[2]={0};k.clear=pass%3==0?3:0;k.discard_load=pass%3==2?3:0;if(pass==149)k.discard_load=0;
  for(int i=0;i<2;i++)at[i]=(VkRenderingAttachmentInfo){VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,.imageView=views[i],.imageLayout=VK_IMAGE_LAYOUT_GENERAL,.loadOp=rp_load(&k,i),.storeOp=VK_ATTACHMENT_STORE_OP_STORE};
  if(classic){
   VkRenderPass rp=rp_obtain(&k);CHECK(rp==rp_obtain(&k),"load/clear cache reuse");
   fbkey fk={.rp=rp,.w=width,.h=height,.layers=1,.na=2};for(int i=0;i<2;i++)fk.a[i]=fb_att(&meta,0,1,k.cf[i]);
   VkFramebuffer fb=fb_obtain(&fk);CHECK(fb && fb==fb_obtain(&fk),"framebuffer cache reuse");
   VkRenderPassAttachmentBeginInfo ab={VK_STRUCTURE_TYPE_RENDER_PASS_ATTACHMENT_BEGIN_INFO,.attachmentCount=2,.pAttachments=views};
   VkRenderPassBeginInfo begin={VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,.pNext=&ab,.renderPass=rp,.framebuffer=fb,.renderArea={{0,0},{width,height}},.clearValueCount=2,.pClearValues=clear};vkCmdBeginRenderPass(cb,&begin,VK_SUBPASS_CONTENTS_INLINE);
  }else{VkRenderingInfo begin={VK_STRUCTURE_TYPE_RENDERING_INFO,.renderArea={{0,0},{width,height}},.layerCount=1,.colorAttachmentCount=2,.pColorAttachments=at};vkCmdBeginRendering(cb,&begin);}
  float color[4]={(pass%17)/16.0f,(pass%7)/6.0f,(pass%13)/12.0f,1};
  VkRect2D scissor={{0,0},{(k.discard_load ? width : width/2),height}};vkCmdSetScissor(cb,0,1,&scissor);
  vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);vkCmdPushConstants(cb,layout,VK_SHADER_STAGE_FRAGMENT_BIT,0,16,color);vkCmdDraw(cb,3,1,0,0);
  // Partial clears exercise the same in-pass path as deferred guest clears.
  if(pass%5==0 || pass==149){VkClearAttachment a={.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT,.colorAttachment=1,.clearValue.color.float32={0.2f,0.4f,0.6f,1}};VkClearRect rc={.rect={{3,5},{width/3,height/3}},.layerCount=1};vkCmdClearAttachments(cb,1,&a,1,&rc);}
  if(classic)vkCmdEndRenderPass(cb);else vkCmdEndRendering(cb);
  for(int i=0;i<2;i++)barrier(cb,im[i],VK_IMAGE_LAYOUT_GENERAL,VK_IMAGE_LAYOUT_GENERAL);
 }
 double elapsed=(seconds()-start)*1e3;
 for(int i=0;i<2;i++){VkBufferImageCopy copy={.bufferOffset=i*size,.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={width,height,1}};vkCmdCopyImageToBuffer(cb,im[i],VK_IMAGE_LAYOUT_GENERAL,dst,1,&copy);}
 VK(vkEndCommandBuffer(cb));VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&submit,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));memcpy(output,mapped,2*size);return elapsed;
}
static void depth_stencil(void){
 const uint32_t w=37,h=29;VkFormat fmt=VK_FORMAT_D32_SFLOAT_S8_UINT;
 VkImageUsageFlags usage=VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
 VkImage im=image(fmt,w,h,usage,NULL);VkImageView view;
 VkImageViewCreateInfo vi={VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=im,.viewType=VK_IMAGE_VIEW_TYPE_2D,.format=fmt,.subresourceRange={VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT,0,1,0,1}};
 VK(vkCreateImageView(dev,&vi,NULL,&view));
 vka_img meta={.usage=usage,.f={fmt},.w=w,.h=h};rpkey key={.ds=fmt,.d=1,.s=1,.samples=1,.clear=(1u<<8)|(1u<<9)};
 VkRenderPass rp=rp_obtain(&key);fbkey fk={.rp=rp,.w=w,.h=h,.layers=1,.na=1};fk.a[0]=fb_att(&meta,0,1,fmt);VkFramebuffer fb=fb_obtain(&fk);CHECK(fb,"depth/stencil framebuffer");
 VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
 VkImageMemoryBarrier barrier={VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.dstAccessMask=VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT,.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED,.newLayout=VK_IMAGE_LAYOUT_GENERAL,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.image=im,.subresourceRange={VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT,0,1,0,1}};
 vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,NULL,0,NULL,1,&barrier);
 VkRenderPassAttachmentBeginInfo ab={VK_STRUCTURE_TYPE_RENDER_PASS_ATTACHMENT_BEGIN_INFO,.attachmentCount=1,.pAttachments=&view};VkClearValue clear={.depthStencil={0.375f,93}};
 VkRenderPassBeginInfo begin={VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,.pNext=&ab,.renderPass=rp,.framebuffer=fb,.renderArea={{0,0},{w,h}},.clearValueCount=1,.pClearValues=&clear};vkCmdBeginRenderPass(cb,&begin,VK_SUBPASS_CONTENTS_INLINE);vkCmdEndRenderPass(cb);
 barrier.srcAccessMask=VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;barrier.oldLayout=VK_IMAGE_LAYOUT_GENERAL;
 vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,NULL,0,NULL,1,&barrier);
 void *mapped;size_t depth=w*h*4;VkBuffer dst=buffer(depth+w*h,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&mapped);
 VkBufferImageCopy copies[2]={{.imageSubresource={VK_IMAGE_ASPECT_DEPTH_BIT,0,0,1},.imageExtent={w,h,1}},{.bufferOffset=depth,.imageSubresource={VK_IMAGE_ASPECT_STENCIL_BIT,0,0,1},.imageExtent={w,h,1}}};vkCmdCopyImageToBuffer(cb,im,VK_IMAGE_LAYOUT_GENERAL,dst,2,copies);
 VK(vkEndCommandBuffer(cb));VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&submit,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
 for(unsigned i=0;i<w*h;i++){CHECK(((float*)mapped)[i]==0.375f,"depth clear changed");CHECK(((uint8_t*)mapped)[depth+i]==93,"stencil clear changed");}
 puts("classic depth/stencil: independent aspect clears and GPU readback passed");
}
int main(void){
 if(!init())return 77;V.dev=dev;vk.vkCreateRenderPass=vkCreateRenderPass;vk.vkCreateFramebuffer=vkCreateFramebuffer;
 depth_stencil();
 for(unsigned load=0;load<3;load++)for(unsigned store=0;store<2;store++)for(unsigned bit=0;bit<10;bit++){
  rpkey k={0};VkRenderingAttachmentInfo a={.loadOp=load,.storeOp=store};rp_operations(&k,bit,&a);CHECK(rp_load(&k,bit)==load && rp_store(&k,bit)==store,"load/store aspect mapping");
 }
 const int shapes[][2]={{67,41},{960,540}};
 for(int i=0;i<2;i++){
  int w=shapes[i][0],h=shapes[i][1];size_t n=(size_t)w*h*8;uint8_t *a=malloc(n),*b=malloc(n);double dynamic[5],classic[5];
  for(int repeat=0;repeat<5;repeat++){
   // Alternate order after warming the production cache; record timings only
   // cover the 150 passes, draws and their dependencies, not pipeline creation.
   if(repeat&1){classic[repeat]=compare(w,h,1,b);dynamic[repeat]=compare(w,h,0,a);}
   else {dynamic[repeat]=compare(w,h,0,a);classic[repeat]=compare(w,h,1,b);}
   int diff=0;for(size_t j=0;j<n;j++)if(a[j]!=b[j])diff++;
   CHECK(diff==0,"dynamic/classic pixels differ: %d",diff);
   CHECK(a[3]==255 && a[n-1]==0,"LOAD did not preserve prior clear outside scissor");
   size_t partial=n/2+((size_t)5*w+3)*4;
   CHECK(a[partial]==51 && a[partial+1]==102 && a[partial+2]==153,"partial clear did not reach MRT1");
  }
  for(int j=0;j<5;j++)for(int k=j+1;k<5;k++){
   if(dynamic[k]<dynamic[j]){double t=dynamic[j];dynamic[j]=dynamic[k];dynamic[k]=t;}
   if(classic[k]<classic[j]){double t=classic[j];classic[j]=classic[k];classic[k]=t;}
  }
  printf("classic parity: %dx%d MRT pixels exact=1 across 5 runs; CPU record median 150 passes dynamic=%.3f classic=%.3f ms (software driver indicator only)\n",w,h,dynamic[2],classic[2]);free(a);free(b);
 }
 printf("classic cache: %d render pass shapes, %u framebuffer shapes; failures=%d\n",g_nrpc,g_fbn,fails);return fails?1:0;
}
