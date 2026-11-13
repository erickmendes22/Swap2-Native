"""Test real GPU texture feedback begin/commit C policy, no Android APK.

Compile the two production functions with a mocked Vk command sink. The GPU
shader writes are emulated by atomic bitmap ORs; fences control when the CPU
may consume the ring. Verify exact ID union, no reuse while busy, fallback
after eight active slots, no stale bits on reuse, and command counts.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
HDR = (ROOT / "dm/gfx/vk_android/vka.h").read_text()


def function(name):
    m = re.search(r"\bvoid\s+" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", TEX, re.S)
    assert m, name
    depth = 1
    for i in range(m.end(), len(TEX)):
        depth += (TEX[i] == "{") - (TEX[i] == "}")
        if not depth:
            return TEX[m.start():i + 1]
    raise AssertionError(name)


class DirectFeedback(unittest.TestCase):
    def test_real_production_c_with_asan_and_fence_simulation(self):
        fixture = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>
#define VLOG(...) ((void)0) /* Android logging is not part of the isolated policy */
typedef uint64_t VkDeviceSize;
typedef int VkCommandBuffer, VkBuffer;
enum { PFB_RING = 8, PFB_BYTES = 1<<17 };
enum { VK_STRUCTURE_TYPE_MEMORY_BARRIER=1, VK_ACCESS_SHADER_WRITE_BIT=2,
       VK_ACCESS_TRANSFER_READ_BIT=4, VK_ACCESS_TRANSFER_WRITE_BIT=8,
       VK_ACCESS_SHADER_READ_BIT=16, VK_ACCESS_HOST_READ_BIT=32,
       VK_PIPELINE_STAGE_ALL_COMMANDS_BIT=64, VK_PIPELINE_STAGE_TRANSFER_BIT=128,
       VK_PIPELINE_STAGE_HOST_BIT=256 };
typedef struct {uint32_t sType, srcAccessMask, dstAccessMask;} VkMemoryBarrier;
typedef struct {uint64_t srcOffset, dstOffset, size;} VkBufferCopy;
typedef struct {VkBuffer buf; uint8_t *ptr; VkDeviceSize off;} vka_span;
static struct {uint64_t fence;uint32_t n;int busy;} g_pfb_r[PFB_RING];
static pthread_mutex_t g_tmu = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int g_pfb=1, g_pfb_any=0;
static int g_pfb_direct_cur=-1, g_pfb_direct_on=1;
static uint64_t g_pfb_direct_zeros, g_pfb_direct_full, g_pfb_direct_subs;
static uint64_t g_pfb_skip;
static uint32_t g_ntreg=4096;
static uint8_t ring[PFB_RING*PFB_BYTES], bitmap[PFB_BYTES];
static vka_span g_pfb_ring={2,ring,0},g_pfb_map={1,bitmap,0};
static unsigned nbar, ncopy, nfill;
static void mock_bar(VkCommandBuffer cb,uint32_t s,uint32_t d,uint32_t dep,uint32_t count,
    const VkMemoryBarrier* barriers,uint32_t nbuf,const void* b,uint32_t nimg,const void* im){
    (void)cb;(void)s;(void)d;(void)dep;(void)nbuf;(void)b;(void)nimg;(void)im;
    assert(count==1 && barriers);nbar++;
}
static void mock_copy(VkCommandBuffer cb,VkBuffer src,VkBuffer dst,uint32_t count,const VkBufferCopy* r){
    (void)cb;assert(count==1 && src==1 && dst==2 && r);
    assert(r->size<=PFB_BYTES && r->dstOffset+r->size<=sizeof ring);
    memcpy(ring+r->dstOffset,bitmap+r->srcOffset,(size_t)r->size);ncopy++;
}
static void mock_fill(VkCommandBuffer cb,VkBuffer dst,uint64_t offset,uint64_t size,uint32_t data){
    (void)cb;assert(dst==1 && data==0 && offset==0 && size==PFB_BYTES);
    memset(bitmap,0,PFB_BYTES);nfill++;
}
static struct {
    void (*vkCmdPipelineBarrier)(VkCommandBuffer,uint32_t,uint32_t,uint32_t,uint32_t,
        const VkMemoryBarrier*,uint32_t,const void*,uint32_t,const void*);
    void (*vkCmdCopyBuffer)(VkCommandBuffer,VkBuffer,VkBuffer,uint32_t,const VkBufferCopy*);
    void (*vkCmdFillBuffer)(VkCommandBuffer,VkBuffer,uint64_t,uint64_t,uint32_t);
} vk={mock_bar,mock_copy,mock_fill};
""" + function("vka_tex_pfb_begin") + "\n" + function("vka_tex_pfb_commit") + r"""
static void bit(uint8_t *p,int id) {((uint32_t*)p)[id/32] |= 1u<<(id%32);}
static int got(const uint8_t *p,int id){return !!(((const uint32_t*)p)[id/32]&(1u<<(id%32)));}
static int used[4096];
static int consume(uint64_t done){
    int n=0;
    for(int k=0;k<PFB_RING;k++) if(g_pfb_r[k].busy && g_pfb_r[k].fence<=done){
        uint8_t *p=ring+k*PFB_BYTES;
        for(int id=0;id<(int)g_ntreg;id++)if(got(p,id)){used[id]++;n++;}
        g_pfb_r[k].busy=0;
    }
    return n;
}
int main(void){
    for(int i=0;i<PFB_RING;i++){
        vka_tex_pfb_begin(); assert(g_pfb_direct_cur==i);
        uint8_t *p=ring+i*PFB_BYTES; int id=33+i*47;
        assert(!got(p,id)); bit(p,id);bit(p,id);bit(p,1023);
        atomic_store(&g_pfb_any,1);vka_tex_pfb_commit(1,100+i);
        assert(g_pfb_direct_cur==-1 && g_pfb_r[i].busy);
        assert(g_pfb_r[i].fence==100u+i);
        assert(!nbar && !ncopy && !nfill);
    }
    assert(!consume(99));assert(consume(100)==2);
    assert(used[33]==1 && used[1023]==1);
    vka_tex_pfb_begin(); assert(g_pfb_direct_cur==0);
    assert(!got(ring,33) && !got(ring,1023));
    bit(ring,2047);atomic_store(&g_pfb_any,1);
    vka_tex_pfb_commit(1,200);
    vka_tex_pfb_begin();assert(g_pfb_direct_cur==-1);
    assert(g_pfb_direct_full==1);
    bit(bitmap,2201);bit(bitmap,17);atomic_store(&g_pfb_any,1);
    vka_tex_pfb_commit(1,201);
    assert(g_pfb_skip==1 && atomic_load(&g_pfb_any)==1);
    assert(!nbar && !ncopy && !nfill);
    assert(consume(101)==2);
    vka_tex_pfb_begin();assert(g_pfb_direct_cur==-1);
    vka_tex_pfb_commit(1,202);
    assert(ncopy==1 && nfill==1 && nbar==3);
    assert(!got(bitmap,2201));
    assert(consume(202)>=4);
    assert(used[17]==1 && used[2201]==1 && used[2047]==1);
    assert(used[33]==1 && used[80]==1);
    vka_tex_pfb_begin();assert(g_pfb_direct_cur>=0);
    int k=g_pfb_direct_cur;vka_tex_pfb_commit(1,300);
    assert(!g_pfb_r[k].busy);
    assert(ncopy==1 && nfill==1 && nbar==3);
    assert(g_pfb_direct_subs==9);
    return 0;
}
"""
        cc = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(cc)
        with tempfile.TemporaryDirectory() as tmp:
            source, exe = Path(tmp)/"pfb.c", Path(tmp)/"pfb"
            source.write_text(fixture)
            subprocess.run([cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
                            "-Werror", "-fsanitize=address,undefined", "-pthread",
                            str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_source_contract_keeps_fallback_and_gpu_host_sync(self):
        self.assertIn('VKA_ENV("DM_VK_POOL_FB_DIRECT", 0)', TEX)
        self.assertIn("g_pfb_direct_set[PFB_RING]", TEX)
        self.assertIn(".dstSet = g_pfb_direct_set[i]", TEX)
        self.assertIn("g_pfb_ring.off + (VkDeviceSize)i * PFB_BYTES", TEX)
        self.assertIn("g_pfb_direct_cur >= 0 ? g_pfb_direct_set[g_pfb_direct_cur] : g_pfb_set;", TEX)
        self.assertIn("g_pfb_r[slot].fence = UINT64_MAX;", TEX)
        self.assertIn("g_pfb_r[slot].fence = fence;", TEX)
        self.assertIn("memset(g_pfb_ring.ptr + (size_t)slot * PFB_BYTES, 0, PFB_BYTES);", TEX)
        self.assertIn("if (!g_pfb_r[k].busy || g_pfb_r[k].fence > done) continue;", TEX)
        a = EXEC.index("vka_tex_prepare(g_cb);")
        b = EXEC.index("vka_tex_pfb_begin();", a)
        c = EXEC.index("vka_draw_sub_begin(g_cb, k);", b)
        self.assertLess(a, b)
        self.assertLess(b, c)
        a = EXEC.index("vka_tex_pfb_commit(g_cb, fence);")
        b = EXEC.index("VK_ACCESS_HOST_READ_BIT | VK_ACCESS_HOST_WRITE_BIT", a)
        self.assertLess(a, b)
        self.assertIn("void vka_tex_pfb_begin(void);", HDR)
        self.assertIn("for (uint32_t x = wd[i]; x; x &= x - 1) pfb_hit(", TEX)


if __name__ == "__main__":
    unittest.main()
