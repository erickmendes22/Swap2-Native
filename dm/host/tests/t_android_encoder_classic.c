// Includes the real encoder with only its platform header adapted by the runner.
// Fake driver callbacks observe command ordering, thread and copied arguments.
#include "encoder_under_test.c"
#include <assert.h>
static int enabled=1,worker_expected=1;
static pthread_t producer;
static _Atomic unsigned count,errors;
int vka_gp_active;
int vka_nan_on(void){return 0;}
uint64_t vka_host_fp(const char *who){(void)who;return 0;}
void vka_perf_thread(int nice){(void)nice;}
int test_env(const char *key,int fallback){
 if(!strcmp(key,"DM_VK_ENC"))return enabled;
 if(!strcmp(key,"DM_VK_ENC_BATCH"))return 1<<20;
 if(!strcmp(key,"DM_VK_ENC_SPIN_US"))return 0;
 return fallback;
}
static void check_step(unsigned step){
 if(count%4!=step)errors++;
 if(worker_expected==!!pthread_equal(producer,pthread_self()))errors++;
 count++;
}
static void VKAPI_CALL begin(VkCommandBuffer cb,const VkRenderPassBeginInfo *b,VkSubpassContents contents){
 (void)cb;unsigned n=count/4;check_step(0);
 if(contents!=VK_SUBPASS_CONTENTS_INLINE || b->renderArea.extent.width!=n+1 || b->clearValueCount!=2 || b->pClearValues[1].color.uint32[2]!=n+73)errors++;
 const VkRenderPassAttachmentBeginInfo *a=b->pNext;
 if(!a || a->sType!=VK_STRUCTURE_TYPE_RENDER_PASS_ATTACHMENT_BEGIN_INFO || a->attachmentCount!=2 || (uintptr_t)a->pAttachments[1]!=n+29)errors++;
}
static void VKAPI_CALL bind(VkCommandBuffer cb,VkPipelineBindPoint bp,VkPipeline p){(void)cb;(void)bp;(void)p;check_step(1);}
static void VKAPI_CALL draw(VkCommandBuffer cb,uint32_t a,uint32_t b,uint32_t c,uint32_t d){(void)cb;(void)a;(void)b;(void)c;(void)d;check_step(2);}
static void VKAPI_CALL end(VkCommandBuffer cb){(void)cb;check_step(3);}
static void pass(VkCommandBuffer cb,unsigned n){
 VkImageView views[2]={(VkImageView)(uintptr_t)17,(VkImageView)(uintptr_t)(n+29)};
 VkClearValue clears[2]={0};clears[1].color.uint32[2]=n+73;
 VkRenderPassAttachmentBeginInfo a={VK_STRUCTURE_TYPE_RENDER_PASS_ATTACHMENT_BEGIN_INFO,.attachmentCount=2,.pAttachments=views};
 VkRenderPassBeginInfo b={VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,.pNext=&a,.renderPass=(VkRenderPass)(uintptr_t)1,.framebuffer=(VkFramebuffer)(uintptr_t)2,.renderArea={{0,0},{n+1,31}},.clearValueCount=2,.pClearValues=clears};
 vk.vkCmdBeginRenderPass(cb,&b,VK_SUBPASS_CONTENTS_INLINE);
 // Caller storage is reused immediately, before publication to the worker.
 memset(views,0,sizeof views);memset(clears,0,sizeof clears);memset(&a,0,sizeof a);memset(&b,0,sizeof b);
 vk.vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_GRAPHICS,(VkPipeline)(uintptr_t)3);
 vk.vkCmdDraw(cb,3,1,0,0);vk.vkCmdEndRenderPass(cb);
}
int main(void){
 producer=pthread_self();vk.vkCmdBeginRenderPass=begin;vk.vkCmdEndRenderPass=end;vk.vkCmdBindPipeline=bind;vk.vkCmdDraw=draw;
 vka_enc_install();if(getenv("ENC_NEGATIVE")){vk.vkCmdBeginRenderPass=begin;vk.vkCmdEndRenderPass=end;}
 VkCommandBuffer cb=(VkCommandBuffer)(uintptr_t)7;vka_enc_start(cb);assert(vka_enc_on());
 // More than one complete ring: tests record relocation and producer waits.
 for(unsigned n=0;n<50000;n++)pass(cb,n);
 vka_enc_stop();if(count!=200000)errors++;
 printf("encoder threaded: %u commands, ring wraps=%llu, ordering/thread/copy errors=%u\n",count,(unsigned long long)(g_ph/RING),errors);
 if(errors)return 1;
 count=0;worker_expected=0;enabled=0;vka_enc_start(cb);assert(!vka_enc_on());
 for(unsigned n=0;n<10;n++)pass(cb,n);vka_enc_stop();
 printf("encoder direct: %u commands, errors=%u\n",count,errors);
 return errors?1:0;
}
