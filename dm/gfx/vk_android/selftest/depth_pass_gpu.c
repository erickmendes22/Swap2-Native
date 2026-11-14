// Dynamic rendering parity for optional unused colour targets/write scopes.
#define VKA_RENDERPASS_TEST
#define VKA_CAVE_QUERY_TEST
#define NDSR_EXTRA_FNS(X) X(vkCreateGraphicsPipelines) X(vkCmdDraw) X(vkCmdSetScissor) X(vkCmdBeginQuery) X(vkCmdEndQuery) X(vkCmdBeginRendering) X(vkCmdEndRendering)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include <assert.h>
static struct { PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier; } vk;
static uint64_t vka_n_attachment_bar;
static int vka_gp_active;
static void vka_gp_mark(VkCommandBuffer cb,const char *f,int l){(void)cb;(void)f;(void)l;}
#include "attachment_parts.inc"
enum { N=192 };
static VkShaderModule mod(const char *name){FILE*f=fopen(getenv(name),"rb");if(!f)exit(3);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint32_t*b=malloc(n);if(fread(b,1,n,f)!=(size_t)n)exit(3);fclose(f);VkShaderModuleCreateInfo ci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=n,.pCode=b};VkShaderModule m;VK(vkCreateShaderModule(dev,&ci,NULL,&m));free(b);return m;}
static VkPipeline pipeline(VkPipelineLayout layout,int omit,int mode,int w,int h,int colors){
 VkPipelineShaderStageCreateInfo sh[2]={{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_VERTEX_BIT,.module=mod("CAVE_VERT"),.pName="main"},{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_FRAGMENT_BIT,.module=mod("CAVE_FRAG"),.pName="main"}};
 #ifdef VKA_DEPTH_NO_FS_TEST
 if(mode==1)sh[1].module=mod("CAVE_PURE_FRAG");
 #endif
 VkPipelineVertexInputStateCreateInfo vi={VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};VkPipelineInputAssemblyStateCreateInfo ia={VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
 VkViewport viewport={0,0,w,h,0,1};VkRect2D rect={{0,0},{w,h}};VkPipelineViewportStateCreateInfo vp={VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,.viewportCount=1,.pViewports=&viewport,.scissorCount=1,.pScissors=&rect};
 VkPipelineRasterizationStateCreateInfo rs={VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,.polygonMode=VK_POLYGON_MODE_FILL,.lineWidth=1};VkPipelineMultisampleStateCreateInfo ms={VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT};
 VkPipelineDepthStencilStateCreateInfo ds={VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO,.depthTestEnable=VK_TRUE,.depthWriteEnable=mode!=2,.depthCompareOp=mode==2?VK_COMPARE_OP_EQUAL:VK_COMPARE_OP_LESS_OR_EQUAL};
 VkPipelineColorBlendAttachmentState att={.colorWriteMask=mode==1?0:15};VkPipelineColorBlendStateCreateInfo bs={VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,.attachmentCount=colors,.pAttachments=colors?&att:NULL};VkDynamicState dynamic=VK_DYNAMIC_STATE_SCISSOR;VkPipelineDynamicStateCreateInfo dy={VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,.dynamicStateCount=1,.pDynamicStates=&dynamic};
 VkFormat cf=(omit&1)?VK_FORMAT_UNDEFINED:VK_FORMAT_R8G8B8A8_UNORM;VkPipelineRenderingCreateInfo ri={VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO,.colorAttachmentCount=1,.pColorAttachmentFormats=&cf,.depthAttachmentFormat=VK_FORMAT_D32_SFLOAT};
 VkGraphicsPipelineCreateInfo ci={VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,.pNext=&ri,.stageCount=(omit&4)?1:2,.pStages=sh,.pVertexInputState=&vi,.pInputAssemblyState=&ia,.pViewportState=&vp,.pRasterizationState=&rs,.pMultisampleState=&ms,.pDepthStencilState=&ds,.pColorBlendState=&bs,.pDynamicState=&dy,.layout=layout};VkPipeline p;VK(vkCreateGraphicsPipelines(dev,VK_NULL_HANDLE,1,&ci,NULL,&p));return p;
}

static void barrier_all(VkCommandBuffer cb){VkMemoryBarrier b={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT};vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&b,0,NULL,0,NULL);}
static double depth_run(int w,int h,int flags,uint64_t *counts,uint8_t *output){
 VkImageView views[2];VkImage ci=image(VK_FORMAT_R8G8B8A8_UNORM,w,h,VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT,&views[0]),di=image(VK_FORMAT_D32_SFLOAT,w,h,VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT,NULL);
 VkImageViewCreateInfo dvi={VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=di,.viewType=VK_IMAGE_VIEW_TYPE_2D,.format=VK_FORMAT_D32_SFLOAT,.subresourceRange={VK_IMAGE_ASPECT_DEPTH_BIT,0,1,0,1}};VK(vkCreateImageView(dev,&dvi,NULL,&views[1]));
 VkPushConstantRange push={VK_SHADER_STAGE_VERTEX_BIT|VK_SHADER_STAGE_FRAGMENT_BIT,0,32};VkPipelineLayoutCreateInfo lci={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.pushConstantRangeCount=1,.pPushConstantRanges=&push};VkPipelineLayout lay;VK(vkCreatePipelineLayout(dev,&lci,NULL,&lay));
 VkPipeline p[3];for(int i=0;i<3;i++)p[i]=pipeline(lay,i==1?(flags&5):0,i,w,h,1);
 VkQueryPoolCreateInfo qci={VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,.queryType=VK_QUERY_TYPE_OCCLUSION,.queryCount=N};VkQueryPool query;VK(vkCreateQueryPool(dev,&qci,NULL,&query));
 VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
 VkImageMemoryBarrier images[2];for(int i=0;i<2;i++)images[i]=(VkImageMemoryBarrier){VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT,.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED,.newLayout=VK_IMAGE_LAYOUT_GENERAL,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.image=i?di:ci,.subresourceRange={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
 vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,NULL,0,NULL,2,images);vkCmdResetQueryPool(cb,query,0,N);vkCmdResetQueryPool(cb,timer,0,2);vkCmdWriteTimestamp(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,timer,0);
 VkRenderingAttachmentInfo ca={VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,.imageView=views[0],.imageLayout=VK_IMAGE_LAYOUT_GENERAL,.loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR,.storeOp=VK_ATTACHMENT_STORE_OP_STORE,.clearValue.color.float32={0,0,0,1}};
 VkRenderingAttachmentInfo da={VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO,.imageView=views[1],.imageLayout=VK_IMAGE_LAYOUT_GENERAL,.loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR,.storeOp=VK_ATTACHMENT_STORE_OP_STORE,.clearValue.depthStencil={1,0}};
 VkRenderingInfo ri={VK_STRUCTURE_TYPE_RENDERING_INFO,.renderArea={{0,0},{w,h}},.layerCount=1,.colorAttachmentCount=1,.pColorAttachments=&ca,.pDepthAttachment=&da};
 vkCmdBeginRendering(cb,&ri);vkCmdEndRendering(cb);barrier_all(cb);ca.loadOp=da.loadOp=VK_ATTACHMENT_LOAD_OP_LOAD;
 for(int i=0;i<N;i++){
  int mode=i%4==0?0:i%4==1?2:1;ca.imageView=(flags&1)&&mode==1?VK_NULL_HANDLE:views[0];
  vkCmdBeginRendering(cb,&ri);
  float pc[8]={(i%7)/7.0f,0.5f,0.75f,1,mode==1?(i%4==2?0.8f:0.1f):0.2f,i%5==0?1:0,0,0};
  VkRect2D sc={{(i/4%4)*(w/4),(i/16%4)*(h/4)},{w/4,h/4}};
  vkCmdSetScissor(cb,0,1,&sc);vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_GRAPHICS,p[mode]);vkCmdPushConstants(cb,lay,VK_SHADER_STAGE_VERTEX_BIT|VK_SHADER_STAGE_FRAGMENT_BIT,0,32,pc);
  vkCmdBeginQuery(cb,query,i,VK_QUERY_CONTROL_PRECISE_BIT);vkCmdDraw(cb,3,1,0,0);vkCmdEndQuery(cb,query,i);
  vkCmdEndRendering(cb);
  if(flags&2)vka_attachment_parts_barrier_at(cb,mode!=1,mode!=2,__FILE__,__LINE__);else vka_attachment_write_barrier_at(cb,__FILE__,__LINE__);
 }
 vkCmdWriteTimestamp(cb,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,timer,1);barrier_all(cb);
 void*mapped;size_t bytes=(size_t)w*h*4;VkBuffer dst=buffer(bytes*2,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&mapped);
 for(int i=0;i<2;i++){VkBufferImageCopy c={.bufferOffset=i*bytes,.imageSubresource={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={w,h,1}};vkCmdCopyImageToBuffer(cb,i?di:ci,VK_IMAGE_LAYOUT_GENERAL,dst,1,&c);}
 VK(vkEndCommandBuffer(cb));VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&submit,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
 VK(vkGetQueryPoolResults(dev,query,0,N,N*8,counts,8,VK_QUERY_RESULT_64_BIT));memcpy(output,mapped,bytes*2);
 uint64_t ts[2];VK(vkGetQueryPoolResults(dev,timer,0,2,16,ts,8,VK_QUERY_RESULT_64_BIT));return(ts[1]-ts[0])*tick/1e6;
}
int main(void){
 if(!init())return 77;vk.vkCmdPipelineBarrier=vkCmdPipelineBarrier;
 const int sizes[][2]={{64,64},{960,540}};
 for(int s=0;s<2;s++){
  int w=sizes[s][0],h=sizes[s][1];size_t bytes=(size_t)w*h*8;uint8_t*a=malloc(bytes),*b=malloc(bytes);uint64_t qa[N],qb[N];
  double ta=depth_run(w,h,0,qa,a);
  #ifdef VKA_DEPTH_NO_FS_TEST
  const int maxflags=7;
  #else
  const int maxflags=3;
  #endif
  for(int flags=1;flags<=maxflags;flags++){
   double tb=depth_run(w,h,flags,qb,b);CHECK(!memcmp(a,b,bytes),"dynamic colour/depth bytes mismatch");CHECK(!memcmp(qa,qb,sizeof qa),"dynamic precise query mismatch");
   int zero=0;for(int i=0;i<N;i++)if(!qa[i])zero++;CHECK(zero&&zero<N,"need hidden and visible queries");
   printf("dynamic depth parity %dx%d flags%d: colour+depth+192 precise queries exact; all193 physical passes retained; GPU %.3f -> %.3fms (software ICD only)\n",w,h,flags,ta,tb);
  }
  #ifdef VKA_DEPTH_NO_FS_TEST
  // Warmed, alternating pairs isolate removal of the FS, separately from
  // the existing attachment options. Never use the cold first run as a gain.
  if(w==960)for(int round=0;round<4;round++){
   const int order[2][4]={{0,4,3,7},{7,3,4,0}};
   for(int j=0;j<4;j++){
    int flags=order[round&1][j];double ms=depth_run(w,h,flags,qb,b);
    CHECK(!memcmp(a,b,bytes)&&!memcmp(qa,qb,sizeof qa),"warmed parity mismatch");
    printf("depth FS isolated warm round%d flags%d GPU %.3fms (software ICD only)\n",round,flags,ms);
   }
  }
  #endif
  free(a);free(b);
 }
 return fails?1:0;
}
