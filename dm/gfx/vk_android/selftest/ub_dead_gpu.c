// Execute the production deferred-write overlay, batcher and pass-close flush.
// The Python driver extracts their unchanged source into ub_flush.inc.
#define NDSR_EXTRA_FNS(X) X(vkCmdCopyBuffer) X(vkFreeCommandBuffers)
#define main unused_ndsr_main
#include "ndsr_lvp.c"
#undef main
#include <stdint.h>
#include <assert.h>
#include <limits.h>
static struct { PFN_vkCmdPipelineBarrier vkCmdPipelineBarrier; PFN_vkCmdCopyBuffer vkCmdCopyBuffer; } vk;
static VkCommandBuffer g_cb;
static uint64_t g_ub_shadows, g_ub_flushed, g_ub_scoped_before_copy;
static uint64_t g_ub_dead_writes, g_ub_dead_bytes, g_ub_copy_cmds, g_ub_copy_regions;
static int optimize, broken_journal;
#define DM_GAME_ID "0400486024DEC000"
#define VKA_ENV(key, def) (!strcmp(key,"DM_VK_UB_DEAD_WRITES") ? optimize : (def))
#define VRED_ONCE(...) do { fprintf(stderr,__VA_ARGS__); exit(2); } while(0)
typedef struct { VkBuffer buf; VkDeviceSize off; uint8_t *ptr; } vka_span;
static VkBuffer scratch, guest;
static uint8_t *scratch_ptr, *guest_ptr;
static size_t scratch_used;
static unsigned journal_n, expected_journal_n;
static uint64_t journal_hash, expected_journal_hash;
static uint8_t journal_bytes[512];
static uint64_t hash_write(uint64_t hash, uint64_t addr, uint64_t n, const void *data) {
    hash = (hash ^ addr) * UINT64_C(1099511628211);
    hash = (hash ^ n) * UINT64_C(1099511628211);
    for(uint64_t k=0;k<n;k++) hash=(hash^((const uint8_t*)data)[k])*UINT64_C(1099511628211);
    return hash;
}
static void vka_tex_gw_update(uint64_t addr,uint64_t n,const void *data) {
    if(broken_journal && optimize && journal_n==0) return;
    journal_n++;journal_hash=hash_write(journal_hash,addr,n,data);
    assert(addr>=4096 && addr+n<=4608);
    memcpy(journal_bytes+addr-4096,data,n);
}
static int vka_scratch(uint64_t n,unsigned align,vka_span *s) {
    scratch_used=(scratch_used+align-1)&~(size_t)(align-1);
    assert(scratch_used+n<=131072);
    *s=(vka_span){scratch,scratch_used,scratch_ptr+scratch_used};scratch_used+=n;return 1;
}
static uint64_t vka_addr_run(uint64_t addr,uint64_t n,VkBuffer *b,VkDeviceSize *off) {
    assert(addr>=4096 && addr+n<=4608);
    *b=guest;*off=addr-4096;uint64_t run=64-(*off%64);return run<n?run:n;
}
static void vka_barrier(VkCommandBuffer cb) {
    VkMemoryBarrier mb={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT};
    vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&mb,0,NULL,0,NULL);
}
static void vka_transfer_write_barrier(VkCommandBuffer cb) {
    VkMemoryBarrier mb={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT};
    vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&mb,0,NULL,0,NULL);
}
#include "ub_flush.inc"
static uint32_t random_state=0x161172;
static uint32_t random_u32(void){random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
static void queue_write(unsigned addr,unsigned n,uint8_t *expected) {
    assert(g_ub_np<UB_DEFER_MAX && addr+n<=512);
    uint8_t *data=malloc(n);assert(data);
    for(unsigned k=0;k<n;k++)data[k]=(uint8_t)random_u32();
    g_ub_pending[g_ub_np++]=(ub_pass_write){4096+addr,n,data};
    memcpy(expected+addr,data,n);
    expected_journal_n++;expected_journal_hash=hash_write(expected_journal_hash,4096+addr,n,data);
    uint8_t shadow[512];memset(shadow,0xa5,sizeof shadow);
    vka_ub_overlay(4096,shadow,sizeof shadow);
    CHECK(!memcmp(expected,shadow,sizeof shadow),"per-draw shadow changed before pass close");
}
int main(int argc,char **argv) {
    (void)argc;broken_journal=argv[1] && !strcmp(argv[1],"broken-journal");
    if(!init())return 77;
    vk.vkCmdCopyBuffer=vkCmdCopyBuffer;vk.vkCmdPipelineBarrier=vkCmdPipelineBarrier;
    scratch=buffer(131072,VK_BUFFER_USAGE_TRANSFER_SRC_BIT,(void**)&scratch_ptr);
    guest=buffer(512,VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,(void**)&guest_ptr);
    VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
    uint64_t repeated_copies[2]={0};unsigned cases=0;
    for(int pattern=0;pattern<132;pattern++)for(int scoped=0;scoped<2;scoped++)for(optimize=0;optimize<2;optimize++) {
        scratch_used=0;journal_n=expected_journal_n=0;journal_hash=expected_journal_hash=0;
        uint8_t expected[512];memset(expected,0xa5,sizeof expected);memset(journal_bytes,0xa5,sizeof journal_bytes);memset(guest_ptr,0xa5,512);
        if(pattern==0)for(int k=0;k<64;k++)queue_write(64,64,expected);
        else if(pattern==1){queue_write(0,128,expected);queue_write(64,128,expected);}
        else if(pattern==2){queue_write(0,128,expected);queue_write(0,64,expected);queue_write(64,64,expected);}
        else if(pattern==3){queue_write(64,64,expected);queue_write(0,256,expected);queue_write(128,128,expected);}
        else {unsigned count=pattern==4?128:2+random_u32()%127;
            for(unsigned k=0;k<count;k++){unsigned addr=(random_u32()%128)*4;unsigned n=(1+random_u32()%((512-addr)/4))*4;queue_write(addr,n,expected);}}
        uint64_t before_copies=g_ub_copy_cmds,before_dead=g_ub_dead_writes;
        VK(vkAllocateCommandBuffers(dev,&ai,&g_cb));VkCommandBufferBeginInfo bi={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(g_cb,&bi));
        vka_barrier(g_cb);vka_ub_flush_pass(scoped);
        VkMemoryBarrier host={VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(g_cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&host,0,NULL,0,NULL);
        VK(vkEndCommandBuffer(g_cb));VkSubmitInfo si={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&g_cb};VK(vkQueueSubmit(q,1,&si,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q));
        CHECK(!memcmp(expected,guest_ptr,512),"GPU contents differ pattern%d opt%d scoped%d",pattern,optimize,scoped);
        CHECK(!memcmp(expected,journal_bytes,512) && journal_n==expected_journal_n && journal_hash==expected_journal_hash,"texture journal history changed");
        CHECK(g_ub_np==0 && g_inline_ub.n==0,"pending state not retired");
        if(pattern==0){repeated_copies[optimize]=g_ub_copy_cmds-before_copies;CHECK(g_ub_copy_cmds-before_copies==(optimize?1u:64u),"repeated overwrite did not eliminate GPU commands");}
        if(pattern==1 || pattern==2)CHECK(g_ub_dead_writes==before_dead,"partial/union overlap was incorrectly elided");
        vkFreeCommandBuffers(dev,pool,1,&g_cb);cases++;
    }
    // Address-wrap and zero-sized records are deliberately never elided.
    g_ub_np=2;g_ub_pending[0]=(ub_pass_write){UINT64_MAX-3,8,NULL};g_ub_pending[1]=(ub_pass_write){0,UINT64_MAX,NULL};CHECK(!ub_superseded(0),"wrapping earlier range");
    g_ub_pending[0]=(ub_pass_write){10,4,NULL};g_ub_pending[1]=(ub_pass_write){0,0,NULL};CHECK(!ub_superseded(0),"zero later range");
    g_ub_pending[0]=(ub_pass_write){UINT64_MAX-8,4,NULL};g_ub_pending[1]=(ub_pass_write){UINT64_MAX-12,16,NULL};CHECK(!ub_superseded(0),"wrapping later range");
    printf("deferred uniform GPU parity: %u cases; journal and per-draw shadows exact; repeated copies %llu -> %llu; failures%d\n",cases,(unsigned long long)repeated_copies[0],(unsigned long long)repeated_copies[1],fails);
    return fails?1:0;
}
