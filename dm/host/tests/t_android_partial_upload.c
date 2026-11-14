// Execute vka_tex.c's real partial uploader; full NVN deswizzle is the oracle.
#ifdef PARTIAL_GPU
#define main ndsr_unused_main
#include "selftest/ndsr_lvp.c"
#undef main
#else
#include <vulkan/vulkan_core.h>
#endif
#include <assert.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../gfx/tex/nvn_deswizzle.h"

// NVN values shared with the recording API; the layout/deswizzler below are
// the real production implementations, not a linear stand-in.
enum { NVN_TEXTURE_FLAGS_LINEAR=0x10, NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET=0x40,
       NVN_TEXTURE_FLAGS_SPARSE=0x20 };
typedef struct { VkBuffer buf; VkDeviceSize off; uint8_t *ptr; } vka_span;
typedef struct { uint32_t bw,bh,bpb; int kind; } vka_fmt;
typedef struct { nvn_texdesc d; nvn_texlayout L; uint8_t *mem; } tex_t;
typedef struct {
    int track,inited,gpu_owned; struct { int z; } m; void *vpool;
    uint32_t base,samples,depth,levels,layers,w,h; vka_fmt f;
    uint64_t stamp; const void *span; VkImage img; VkImageAspectFlags aspect;
} vka_img;
typedef struct { uint64_t lo,hi,fence; } gw_t;
static gw_t g_gw[4]; static int g_ngw;
static int enabled=1, diagnostic, unmapped, scratch_fail=-1, decode_fail;
static uint64_t clock_stamp=1, pages[65536], g_up_ns, g_up_bytes;
static uint8_t *storage, *gpu_bytes[32][32];
static size_t sizes[32][32]; static unsigned copies, queries;
static uint64_t copied_bytes, checks, full_bytes;
static void *scratch_ptrs[4096]; static unsigned nscratch;
static int inject_race; static size_t race_offset;
#define VKA_ENV(key, def) enabled
#define VLOG(...) ((void)0)
static int vka_nan_on(void) { return diagnostic; }
static uint64_t vka_done(void) { return 5; }
static uint64_t now_ns(void) { return clock_stamp*1000; }
static uint64_t dm_guest_unmapped(uintptr_t a, uint64_t n) { (void)a;(void)n;return unmapped; }
static uint64_t nvn_dirty_now(void) { return clock_stamp; }
static void nvn_dirty_protect(const void *p, size_t n) { (void)p;(void)n; }
static int nvn_dirty_since_span(const void *span,const void *p,size_t n,uint64_t stamp) {
    (void)span; size_t off=(const uint8_t *)p-storage; int result=0;
    for(size_t i=off/4096;i<=(off+n-1)/4096;i++) if(pages[i]>stamp) result=1;
    // A loader writes an image AFTER its clean check. This must be seen on
    // the next check (the uploader cannot advance its stamp past this write).
    if(inject_race && ++queries==2) {
        storage[race_offset]^=0x5a;pages[race_offset/4096]=++clock_stamp;inject_race=0;
    }
    return result;
}
static int vka_scratch(size_t n,size_t align,vka_span *s) {
    (void)align;
    if(scratch_fail==0)return 0;
    if(scratch_fail>0)scratch_fail--;
#ifdef PARTIAL_GPU
    void *p; s->buf=buffer(n,VK_BUFFER_USAGE_TRANSFER_SRC_BIT,&p);s->ptr=p;
#else
    s->ptr=malloc(n);assert(s->ptr);scratch_ptrs[nscratch++]=s->ptr;
    s->buf=(VkBuffer)(uintptr_t)s->ptr;
#endif
    s->off=0;return 1;
}
static int checked_deswizzle(const nvn_texdesc *d,unsigned lv,unsigned ly,const void *p,void *out,size_t pitch) {
    return decode_fail ? -1 : nvn_deswizzle(d,lv,ly,p,out,pitch);
}
static void record_copy(VkCommandBuffer cb,VkBuffer b,VkImage image,VkImageLayout layout,uint32_t n,const VkBufferImageCopy *c) {
    assert(n==1 && c->imageSubresource.layerCount==1 && c->imageSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT);
    uint32_t lv=c->imageSubresource.mipLevel,ly=c->imageSubresource.baseArrayLayer;
    assert(c->imageOffset.x==0 && c->imageOffset.y==0 && c->imageOffset.z==0 && c->imageExtent.depth==1);
    copies++;copied_bytes+=sizes[lv][ly];
#ifdef PARTIAL_GPU
    vkCmdCopyBufferToImage(cb,b,image,layout,n,c);
#else
    (void)cb;(void)image;(void)layout;
    memcpy(gpu_bytes[lv][ly],(const uint8_t *)(uintptr_t)b+c->bufferOffset,sizes[lv][ly]);
#endif
}
static struct { PFN_vkCmdCopyBufferToImage vkCmdCopyBufferToImage; } vk={record_copy};
#define nvn_deswizzle checked_deswizzle
#include "partial_production.inc"
#undef nvn_deswizzle

#ifdef PARTIAL_GPU
static VkCommandBuffer begin(vka_img *im,int first) {
    VkCommandBuffer cb;VkCommandBufferAllocateInfo a={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,.commandPool=pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};VK(vkAllocateCommandBuffers(dev,&a,&cb));
    VkCommandBufferBeginInfo b={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};VK(vkBeginCommandBuffer(cb,&b));
    VkImageMemoryBarrier mb={VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT,.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT,.oldLayout=first?VK_IMAGE_LAYOUT_UNDEFINED:VK_IMAGE_LAYOUT_GENERAL,.newLayout=VK_IMAGE_LAYOUT_GENERAL,.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,.image=im->img,.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,im->levels,0,im->layers}};
    vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,NULL,0,NULL,1,&mb);return cb;
}
static void submit(VkCommandBuffer cb) { VK(vkEndCommandBuffer(cb));VkSubmitInfo s={VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cb};VK(vkQueueSubmit(q,1,&s,VK_NULL_HANDLE));VK(vkQueueWaitIdle(q)); }
static void make_image(vka_img *im) {
    VkImageCreateInfo c={VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,.imageType=VK_IMAGE_TYPE_2D,.format=VK_FORMAT_R8G8B8A8_UNORM,.extent={im->w,im->h,1},.mipLevels=im->levels,.arrayLayers=im->layers,.samples=VK_SAMPLE_COUNT_1_BIT,.tiling=VK_IMAGE_TILING_OPTIMAL,.usage=VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT};
    VK(vkCreateImage(dev,&c,NULL,&im->img));VkMemoryRequirements r;vkGetImageMemoryRequirements(dev,im->img,&r);
    VkMemoryAllocateInfo a={VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=r.size,.memoryTypeIndex=mem_type(r.memoryTypeBits,0)};VkDeviceMemory m;VK(vkAllocateMemory(dev,&a,NULL,&m));VK(vkBindImageMemory(dev,im->img,m,0));
}
#endif
static size_t pitch_of(const vka_img *im,unsigned lv) { uint32_t w=im->w>>lv;if(!w)w=1;return (size_t)((w+im->f.bw-1)/im->f.bw)*im->f.bpb; }
static void full(vka_img *im,const tex_t *t,VkCommandBuffer cb) {
    for(unsigned lv=0;lv<im->levels;lv++)for(unsigned ly=0;ly<im->layers;ly++) {
        vka_span s;int save=scratch_fail;scratch_fail=-1;assert(vka_scratch(sizes[lv][ly],16,&s));scratch_fail=save;
        assert(!nvn_deswizzle(&t->d,lv,ly,t->mem,s.ptr,pitch_of(im,lv)));
        unsigned w=im->w>>lv,h=im->h>>lv;if(!w)w=1;if(!h)h=1;
        VkBufferImageCopy c={0,((w+im->f.bw-1)/im->f.bw)*im->f.bw,((h+im->f.bh-1)/im->f.bh)*im->f.bh,{im->aspect,lv,ly,1},{0,0,0},{w,h,1}};
        record_copy(cb,s.buf,im->img,VK_IMAGE_LAYOUT_GENERAL,1,&c);
    }
    im->stamp=clock_stamp;
}
static void compare(vka_img *im,const tex_t *t) {
#ifdef PARTIAL_GPU
    VkCommandBuffer cb=begin(im,0);void *read[32][32];
    for(unsigned lv=0;lv<im->levels;lv++)for(unsigned ly=0;ly<im->layers;ly++) {
        VkBuffer b=buffer(sizes[lv][ly],VK_BUFFER_USAGE_TRANSFER_DST_BIT,&read[lv][ly]);
        unsigned w=im->w>>lv,h=im->h>>lv;if(!w)w=1;if(!h)h=1;
        VkBufferImageCopy c={0,0,0,{im->aspect,lv,ly,1},{0,0,0},{w,h,1}};vkCmdCopyImageToBuffer(cb,im->img,VK_IMAGE_LAYOUT_GENERAL,b,1,&c);
    }
    submit(cb);
#endif
    for(unsigned lv=0;lv<im->levels;lv++)for(unsigned ly=0;ly<im->layers;ly++) {
        uint8_t *ref=malloc(sizes[lv][ly]);assert(!nvn_deswizzle(&t->d,lv,ly,t->mem,ref,pitch_of(im,lv)));
#ifdef PARTIAL_GPU
        memcpy(gpu_bytes[lv][ly],read[lv][ly],sizes[lv][ly]);
#endif
        assert(!memcmp(ref,gpu_bytes[lv][ly],sizes[lv][ly]));free(ref);checks++;
    }
#ifndef PARTIAL_GPU
    for(unsigned i=0;i<nscratch;i++)free(scratch_ptrs[i]);
    nscratch=0;
#endif
}
int main(void) {
#ifdef PARTIAL_GPU
    if(!init())return 77;
    const int formats[]={0x25};
#else
    const int formats[]={0x25,0x41,0x4b,0x4d,0x79};
#endif
    nvn_gob_switch2=1;
    for(unsigned fi=0;fi<sizeof(formats)/sizeof(formats[0]);fi++) {
        tex_t t={.d={.target=4,.format=formats[fi],.width=257,.height=129,.depth=8,.levels=5}};
        nvn_tex_layout(&t.d,&t.L);assert(t.L.layers==8);assert(t.L.size<sizeof(pages)/sizeof(pages[0])*4096);
        assert(!posix_memalign((void **)&storage,4096,(size_t)t.L.size));t.mem=storage;
        for(size_t i=0;i<t.L.size;i++)storage[i]=(uint8_t)(i*73u+(i>>8));
        memset(pages,0,sizeof pages);clock_stamp=1;g_ngw=0;
        int bw,bh,bpb=nvn_fmt_bpb(formats[fi],&bw,&bh);
        vka_img im={.track=1,.inited=1,.samples=1,.depth=1,.levels=5,.layers=8,.w=257,.h=129,.f={(uint32_t)bw,(uint32_t)bh,(uint32_t)bpb,0},.aspect=VK_IMAGE_ASPECT_COLOR_BIT};
        for(unsigned lv=0;lv<im.levels;lv++)for(unsigned ly=0;ly<im.layers;ly++) { unsigned h=im.h>>lv;if(!h)h=1;sizes[lv][ly]=pitch_of(&im,lv)*((h+im.f.bh-1)/im.f.bh);gpu_bytes[lv][ly]=malloc(sizes[lv][ly]);full_bytes+=sizes[lv][ly]; }
        VkCommandBuffer cb=VK_NULL_HANDLE;
#ifdef PARTIAL_GPU
        make_image(&im);cb=begin(&im,1);
#endif
        full(&im,&t,cb);
#ifdef PARTIAL_GPU
        submit(cb);
#endif
        compare(&im,&t);
        for(unsigned round=0;round<20;round++) {
            unsigned ly=round%8,lv=(round/8)%5;uint64_t off,len;sub_range(&t.d,&t.L,lv,ly,&off,&len);assert(len);
            size_t at=off+len/2;storage[at]^=(uint8_t)(round+1);pages[at/4096]=++clock_stamp;
#ifdef PARTIAL_GPU
            cb=begin(&im,0);
#endif
            copies=0;uint64_t before=copied_bytes;assert(upload_images_tracked(&im,&t,cb));
            assert(copies>0 && copies<40 && copied_bytes-before<full_bytes);
#ifdef PARTIAL_GPU
            submit(cb);
#endif
            compare(&im,&t);
        }
        // Every exclusion leaves image/stamp untouched and records no copy.
        for(int gate=0;gate<14;gate++) {
            vka_img x=im;enabled=1;diagnostic=unmapped=0;scratch_fail=-1;decode_fail=0;g_ngw=0;
            if(gate==0)enabled=0;
            if(gate==1)x.gpu_owned=1;
            if(gate==2)x.vpool=&x;
            if(gate==3)x.base=1;
            if(gate==4)x.samples=4;
            if(gate==5)x.depth=4;
            if(gate==6)x.f.kind=3;
            if(gate==7)diagnostic=1;
            if(gate==8)unmapped=1;
            if(gate==9)x.m.z=1;
            if(gate==10)x.track=0;
            if(gate==11)x.inited=0;
            if(gate==12)x.layers=x.levels=1;
            if(gate==13){g_ngw=1;g_gw[0]=(gw_t){(uint64_t)(uintptr_t)t.mem,(uint64_t)(uintptr_t)t.mem+16,6};}
            copies=0;assert(!upload_images_tracked(&x,&t,cb));assert(!copies&&x.stamp==im.stamp);
        }
        enabled=1;diagnostic=unmapped=g_ngw=0;
        for(unsigned flags=0;flags<3;flags++) {
            tex_t blocked=t;blocked.d.flags=flags==0?NVN_TEXTURE_FLAGS_LINEAR:flags==1?NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET:NVN_TEXTURE_FLAGS_SPARSE;
            copies=0;assert(!upload_images_tracked(&im,&blocked,cb));assert(!copies);
        }
#ifndef PARTIAL_GPU
        // A fully dirty array must preserve the original parallel upload.
        for(size_t pg=0;pg<(t.L.size+4095)/4096;pg++)pages[pg]=clock_stamp+1;
        clock_stamp++;copies=0;uint64_t full_stamp=im.stamp;
        assert(!upload_images_tracked(&im,&t,cb));assert(!copies&&im.stamp==full_stamp);
        full(&im,&t,cb);compare(&im,&t);

        // A second image changes after its clean check; the next call must
        // pick it up instead of advancing the stamp beyond that CPU write.
        uint64_t off,len;sub_range(&t.d,&t.L,0,0,&off,&len);storage[0]^=9;pages[0]=++clock_stamp;
        sub_range(&t.d,&t.L,0,1,&off,&len);race_offset=off+len/2;inject_race=1;queries=0;
        assert(upload_images_tracked(&im,&t,cb));assert(pages[race_offset/4096]>im.stamp);
        assert(upload_images_tracked(&im,&t,cb));compare(&im,&t);
        for(int failure=0;failure<2;failure++) {
            storage[0]^=7;pages[0]=++clock_stamp;uint64_t old=im.stamp;copies=0;
            scratch_fail=failure? -1:0;decode_fail=failure;
            assert(!upload_images_tracked(&im,&t,cb));assert(!copies&&im.stamp==old);
            scratch_fail=-1;decode_fail=0;full(&im,&t,cb);compare(&im,&t);
        }
#endif
        for(unsigned lv=0;lv<im.levels;lv++)for(unsigned ly=0;ly<im.layers;ly++)free(gpu_bytes[lv][ly]);
        free(storage);
    }
    printf("partial uploads: exact full-deswizzle oracle, %llu layer/mip comparisons; %llu bytes avoided; guards and concurrent writes preserved\n",(unsigned long long)checks,(unsigned long long)g_partial_saved);
    return 0;
}
