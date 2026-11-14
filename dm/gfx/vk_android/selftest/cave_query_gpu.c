// Real query/colour/depth parity: research only: original depth pass ends with/without unused colour attachments.
#define VKA_RENDERPASS_TEST
#define VKA_CAVE_QUERY_TEST
#define NDSR_EXTRA_FNS(X) X(vkCreateRenderPass) X(vkCreateFramebuffer) X(vkCmdBeginRenderPass) X(vkCmdEndRenderPass) X(vkCreateGraphicsPipelines) X(vkCmdDraw) X(vkCmdSetScissor) X(vkCmdBeginQuery) X(vkCmdEndQuery)
#define main ndsr_unused_main
#include "ndsr_lvp.c"
#undef main
#include <pthread.h>
static struct {VkDevice dev;} V;
static struct {PFN_vkCreateRenderPass vkCreateRenderPass;PFN_vkCreateFramebuffer vkCreateFramebuffer;} vk;
typedef struct {VkImageCreateFlags cflags;VkImageUsageFlags usage;struct{VkFormat vk;}f;uint32_t w,h,nvf;VkFormat vf[6];}vka_img;
#define VLOG(...) ((void)0)
#define VRED_ONCE(...) fprintf(stderr,__VA_ARGS__)
#include "vka_renderpass_cache.h"
enum {N=192};
static VkShaderModule mod(const char *name){FILE*f=fopen(getenv(name),"rb");if(!f)exit(3);fseek(f,0,SEEK_END);long n=ftell(f);rewind(f);uint32_t*b=malloc(n);if(fread(b,1,n,f)!=(size_t)n)exit(3);fclose(f);VkShaderModuleCreateInfo ci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=n,.pCode=b};VkShaderModule m;VK(vkCreateShaderModule(dev,&ci,NULL,&m));free(b);return m;}
static VkPipeline pipeline(VkPipelineLayout layout,VkRenderPass rp,int mode,int w,int h,int colors){
 VkPipelineShaderStageCreateInfo sh[2]={{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_VERTEX_BIT,.module=mod("CAVE_VERT"),.pName="main"},{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_FRAGMENT_BIT,.module=mod("CAVE_FRAG"),.pName="main"}};
 VkPipelineVertexInputStateCreateInfo vi={VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};VkPipelineInputAssemblyStateCreateInfo ia={VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
 VkViewport viewport={0,0,w,h,0,1};VkRect2D rect={{0,0},{w,h}};VkPipelineViewportStateCreateInfo vp={VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,.viewportCount=1,.pViewports=&viewport,.scissorCount=1,.pScissors=&rect};
 VkPipelineRasterizationStateCreateInfo rs={VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,.polygonMode=VK_POLYGON_MODE_FILL,.lineWidth=1};VkPipelineMultisampleStateCreateInfo ms={VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT};
 VkPipelineDepthStencilStateCreateInfo ds={VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO,.depthTestEnable=VK_TRUE,.depthWriteEnable=mode==0,.depthCompareOp=mode==2?VK_COMPARE_OP_EQUAL:VK_COMPARE_OP_LESS_OR_EQUAL};
 VkPipelineColorBlendAttachmentState att={.colorWriteMask=mode==1?0:15};VkPipelineColorBlendStateCreateInfo bs={VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,.attachmentCount=colors,.pAttachments=colors?&att:NULL};VkDynamicState dynamic=VK_DYNAMIC_STATE_SCISSOR;VkPipelineDynamicStateCreateInfo dy={VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,.dynamicStateCount=1,.pDynamicStates=&dynamic};
 VkGraphicsPipelineCreateInfo ci={VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,.stageCount=2,.pStages=sh,.pVertexInputState=&vi,.pInputAssemblyState=&ia,.pViewportState=&vp,.pRasterizationState=&rs,.pMultisampleState=&ms,.pDepthStencilState=&ds,.pColorBlendState=&bs,.pDynamicState=&dy,.layout=layout,.renderPass=rp};VkPipeline p;VK(vkCreateGraphicsPipelines(dev,VK_NULL_HANDLE,1,&ci,NULL,&p));return p;
}
static void barrier_all(VkCommandBuffer cb){VkMemoryBarrier b={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT};vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&b,0,NULL,0,NULL);}
static double cave_run(int w,int h,int local,uint64_t *counts,uint8_t *output){
 VkFormat cf=VK_FORMAT_R8G8B8A8_UNORM,df=VK_FORMAT_D32_SFLOAT;VkImageUsageFlags cu=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT,du=VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
 VkImageView views[2];VkImage ci=image(cf,w,h,cu,&views[0]),di=image(df,w,h,du,NULL);VkImageViewCreateInfo dvi={VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,.image=di,.viewType=VK_IMAGE_VIEW_TYPE_2D,.format=df,.subresourceRange={VK_IMAGE_ASPECT_DEPTH_BIT,0,1,0,1}};VK(vkCreateImageView(dev,&dvi,NULL,&views[1]));
 rpkey keys[3]={{0}};keys[0]=(rpkey){.cf={cf},.n=1,.ds=df,.d=1,.samples=1,.clear=1|(1u<<8)};keys[1]=keys[0];keys[1].clear=0;keys[2]=(rpkey){.n=0,.ds=df,.d=1,.samples=1};VkRenderPass rp[3]={rp_obtain(&keys[0]),rp_obtain(&keys[1]),rp_obtain(&keys[2])};
 vka_img meta[2]={{.usage=cu,.f={cf},.w=w,.h=h},{.usage=du,.f={df},.w=w,.h=h}};VkFramebuffer fb[3];for(int i=0;i<3;i++){fbkey fk={.rp=rp[i],.w=w,.h=h,.layers=1,.na=i==2?1:2};if(i==2)fk.a[0]=fb_att(&meta[1],0,1,df);else{fk.a[0]=fb_att(&meta[0],0,1,cf);fk.a[1]=fb_att(&meta[1],0,1,df);}fb[i]=fb_obtain(&fk);}
 VkPushConstantRange push={VK_SHADER_STAGE_VERTEX_BIT|VK_SHADER_STAGE_FRAGMENT_BIT,0,32};VkPipelineLayoutCreateInfo lci={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.pushConstantRangeCount=1,.pPushConstantRanges=&push};VkPipelineLayout lay;VK(vkCreatePipelineLayout(dev,&lci,NULL,&lay));VkPipeline p[3];for(int i=0;i<3;i++)p[i]=pipeline(lay,local&&i==1?rp[2]:rp[0],i,w,h,local&&i==1?0:1);
 VkQueryPoolCreateInfo qci={VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,.queryType=VK_QUERY_TYPE_OCCLUSION,.queryCount=N};VkQueryPool query;VK(vkCreateQueryPool(dev,&qci,NULL,&query));VkCommandBuffer cb;VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&ai,&cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&bi));
 VkImageMemoryBarrier images[2];for(int i=0;i<2;i++)images[i]=(VkImageMemoryBarrier){VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT,.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED,.newLayout=VK_IMAGE_LAYOUT_GENERAL,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.image=i?di:ci,.subresourceRange={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1}};
 vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,NULL,0,NULL,2,images);vkCmdResetQueryPool(cb,query,0,N);vkCmdResetQueryPool(cb,timer,0,2);vkCmdWriteTimestamp(cb,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,timer,0);
 VkRenderPassAttachmentBeginInfo ab={VK_STRUCTURE_TYPE_RENDER_PASS_ATTACHMENT_BEGIN_INFO,.attachmentCount=2,.pAttachments=views};VkClearValue clear[2]={{.color.float32={0,0,0,1}},{.depthStencil={1,0}}};VkRenderPassBeginInfo rb={VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,.pNext=&ab,.renderPass=rp[0],.framebuffer=fb[0],.renderArea={{0,0},{w,h}},.clearValueCount=2,.pClearValues=clear};vkCmdBeginRenderPass(cb,&rb,VK_SUBPASS_CONTENTS_INLINE);
 for(int i=0;i<N;i++){
  int mode=i%4==0?0:i%4==1?2:1;float pc[8]={(i%7)/7.0f,0.5f,0.75f,1,mode==1?(i%4==2?0.8f:0.1f):0.2f,i%5==0?1:0,0,0};
  VkRect2D sc={{(i/4%4)*(w/4),(i/16%4)*(h/4)},{w/4,h/4}};vkCmdSetScissor(cb,0,1,&sc);vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_GRAPHICS,p[mode]);vkCmdPushConstants(cb,lay,VK_SHADER_STAGE_VERTEX_BIT|VK_SHADER_STAGE_FRAGMENT_BIT,0,32,pc);vkCmdBeginQuery(cb,query,i,VK_QUERY_CONTROL_PRECISE_BIT);vkCmdDraw(cb,3,1,0,0);vkCmdEndQuery(cb,query,i);
  // Keep every original physical depth pass end. Only a read-only query's
  // masked-out colour attachment is omitted in the research variant.
  vkCmdEndRenderPass(cb);barrier_all(cb);
  int next=local&&i+1<N&&((i+1)%4)>=2?2:1;
  ab.attachmentCount=next==2?1:2;ab.pAttachments=next==2?&views[1]:views;
  rb.renderPass=rp[next];rb.framebuffer=fb[next];
  vkCmdBeginRenderPass(cb,&rb,VK_SUBPASS_CONTENTS_INLINE);
 }
 vkCmdEndRenderPass(cb);vkCmdWriteTimestamp(cb,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,timer,1);barrier_all(cb);void*mapped;size_t bytes=(size_t)w*h*4;VkBuffer dst=buffer(bytes*2,VK_BUFFER_USAGE_TRANSFER_DST_BIT,&mapped);for(int i=0;i<2;i++){VkBufferImageCopy copy={.bufferOffset=i*bytes,.imageSubresource={i?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT,0,0,1},.imageExtent={w,h,1}};vkCmdCopyImageToBuffer(cb,i?di:ci,VK_IMAGE_LAYOUT_GENERAL,dst,1,&copy);}
 VK(vkEndCommandBuffer(cb));VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&submit,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));VK(vkGetQueryPoolResults(dev,query,0,N,N*8,counts,8,VK_QUERY_RESULT_64_BIT));memcpy(output,mapped,bytes*2);uint64_t ts[2];VK(vkGetQueryPoolResults(dev,timer,0,2,16,ts,8,VK_QUERY_RESULT_64_BIT));return (ts[1]-ts[0])*tick/1e6;
}
int main(void){if(!init())return 77;V.dev=dev;vk.vkCreateRenderPass=vkCreateRenderPass;vk.vkCreateFramebuffer=vkCreateFramebuffer;const int sizes[][2]={{64,64},{960,540}};for(int s=0;s<2;s++){int w=sizes[s][0],h=sizes[s][1];size_t n=(size_t)w*h*8;uint8_t*a=malloc(n),*b=malloc(n);uint64_t qa[N],qb[N];double ta=cave_run(w,h,0,qa,a),tb=cave_run(w,h,1,qb,b);CHECK(!memcmp(a,b,n),"colour/depth pixels mismatch");CHECK(!memcmp(qa,qb,sizeof qa),"real query sample counts mismatch");int zero=0,nonzero=0;for(int i=0;i<N;i++)if(qa[i])nonzero++;else zero++;CHECK(zero&&nonzero,"test lacks hidden/visible samples");printf("cave parity %dx%d: pixels+depth+%d precise query counts exact; zero=%d positive=%d; physical depth pass instances %d unchanged; 96 unused colour loads/stores omitted; GPU %.3f -> %.3f ms (software ICD only)\n",w,h,N,zero,nonzero,N+1,ta,tb);free(a);free(b);}return fails?1:0;}
