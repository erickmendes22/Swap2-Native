"""Compile the production state decoder, driver memo and vertex caches.

Compare emitted bytes/state to the uncached production functions while
changing every dependency, copying queue states, replacing memory and
invalidating command buffers. No model of the cache substitutes for C.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


def function(source, signature):
    start = source.index(signature); brace = source.index("{", start)
    depth = 1; end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}"); end += 1
    return source[start:end]


def program():
    s = (VK / "vka_draw.c").read_text(); h = (VK / "vka.h").read_text()
    ds = h[h.index("typedef struct {\n    vka_bstate b;"):h.index("} vka_dstate;") + len("} vka_dstate;")]
    key = h[h.index("typedef struct {   // what a graphics pipeline"):h.index("} vka_gkey;") + len("} vka_gkey;")]
    state = s[s.index("static _Atomic uint64_t g_state_stamp;"):s.index("// ---------- Static buffers:")]
    memo = s[s.index("typedef struct { VkBuffer buf; VkDeviceSize off; } c0_at;"):s.index("// Port of the iOS dynamic-GMEM")]
    formats = s[s.index("#define VF(n, s)"):s.index("static VkFormat vin_format")]
    formats += function(s, "static VkFormat vin_format(")
    vertex = s[s.index("static struct { VkVertexInputBindingDescription2EXT b[33]"):s.index("// The guest indices of an indexed draw")]
    return r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <vulkan/vulkan_core.h>
#include "nvn_obj.h"
#include "vka_bind.h"
#define VRED(...) ((void)0)
#define VRED_ONCE(...) ((void)0)
typedef struct { VkBuffer buf; uint8_t *ptr; VkDeviceSize off; } vka_span;
typedef struct { const dmsh_vk_entry *e; } vka_shader;
static int stamp_option = 1;
#define VKA_ENV(name, fallback) (!strcmp(name, "DM_VK_DRV_STAMP") ? stamp_option : (fallback))
static struct { uint64_t ub_align; int max_vin_bindings, vin_dyn, divisor; } V = {64, 32, 1, 1};
static VkCommandBuffer g_cb;
static int g_vb_filter = 1, g_vin_skip = 1;
static uint64_t g_vin_kept, g_vin_built, g_vb_kept, g_vb_bound;
static uint64_t mem_generation = 1, addr_lookups;
static uint64_t vka_mem_gen(void) { return mem_generation; }
static int vka_addr(uint64_t a, uint64_t n, void *b, void *o, void *p) { (void)a;(void)n;(void)b;(void)o;(void)p;return 0; }
static int plat_mem_read(uint64_t a, void *p, size_t n) { memcpy(p,(void *)(uintptr_t)a,n);return 0; }
int nvn_dpool_base(const void *p, int tex) { (void)tex;return (int)(uintptr_t)p; }
static uint64_t vka_addr_run(uint64_t a, uint64_t n, VkBuffer *b, VkDeviceSize *o) {
    addr_lookups++;*b=(VkBuffer)(uintptr_t)(a+mem_generation*0x100000);*o=0;return n;
}
static void *allocated[8192]; static unsigned nallocated; static uint64_t fills;
static int vka_scratch(size_t n, uint64_t align, vka_span *s) {
    (void)align; assert(nallocated<8192); void *p=calloc(1,n);assert(p);
    allocated[nallocated++]=p;*s=(vka_span){(VkBuffer)(uintptr_t)nallocated,p,0};return 1;
}
void reference_drv_fill(const vka_bstate *, int, int, int, uint8_t *);
void vka_drv_fill(const vka_bstate *s, int st, int bank, int pool, uint8_t *b) { fills++;reference_drv_fill(s,st,bank,pool,b); }
static vka_span g_zero = {(VkBuffer)(uintptr_t)0x1234,NULL,0};
static struct {
    uint32_t nb, na; VkVertexInputBindingDescription2EXT vb[33]; VkVertexInputAttributeDescription2EXT va[32];
    VkBuffer b[33]; VkDeviceSize o[33], sz[33];
} gpu;
static void mock_vertex(VkCommandBuffer cb,uint32_t nb,const VkVertexInputBindingDescription2EXT *vb,uint32_t na,const VkVertexInputAttributeDescription2EXT *va) {
    (void)cb;gpu.nb=nb;gpu.na=na;memset(gpu.vb,0,sizeof gpu.vb);memset(gpu.va,0,sizeof gpu.va);
    memcpy(gpu.vb,vb,nb*sizeof *vb);memcpy(gpu.va,va,na*sizeof *va);
}
static void mock_buffers(VkCommandBuffer cb,uint32_t first,uint32_t n,const VkBuffer *b,const VkDeviceSize *o,const VkDeviceSize *sz,const VkDeviceSize *strides) {
    (void)cb;(void)strides;assert(first+n<=33);memcpy(gpu.b+first,b,n*sizeof *b);memcpy(gpu.o+first,o,n*sizeof *o);memcpy(gpu.sz+first,sz,n*sizeof *sz);
}
static struct { PFN_vkCmdSetVertexInputEXT vkCmdSetVertexInputEXT; PFN_vkCmdBindVertexBuffers2 vkCmdBindVertexBuffers2; } vk = {mock_vertex,mock_buffers};
''' + ds + "\n" + key + "\n" + state + "\n" + memo + "\n" + formats + "\n" + vertex + r'''
static uint32_t random_word(void) { static uint32_t x=0x17aa6015; x^=x<<13;x^=x>>17;x^=x<<5;return x; }
static void compare_bank(vka_dstate *d,int st,int bank,int pool) {
    uint8_t expected[DMSH_DRV_SIZE];reference_drv_fill(&d->b,st,bank,pool,expected);
    VkDescriptorBufferInfo info;assert(drv_seg(d,st,bank,pool,&info,NULL));assert(info.range==vka_drv_size(bank));
    uintptr_t i=(uintptr_t)info.buffer;assert(i&&i<=nallocated);
    assert(!memcmp(allocated[i-1],expected,info.range));
}
static void cleanup(void) { for(unsigned i=0;i<nallocated;i++)free(allocated[i]);nallocated=0;drv_memo_reset(); }
static void banks(void) {
    vka_dstate q[3];for(int i=0;i<3;i++)vka_dstate_reset(&q[i]);
    for(int i=0;i<3000;i++) {
        int qi=random_word()%3,st=random_word()%8,op=random_word()%8;vka_dstate *d=&q[qi];
        if(op==0) { p_bind_buf b={st,(int)(random_word()%16),random_word(),random_word()%4096};vka_state_op(d,OP_BIND_SSBO,&b); }
        if(op>=1&&op<=3) { p_bind_handles b={0};b.stage=st;b.first=random_word()%32;b.n=1;b.h[0]=random_word();vka_state_op(d,op==1?OP_BIND_TEX:op==2?OP_BIND_SAMP:OP_BIND_IMG,&b); }
        if(op==4) { uint8_t raw[sizeof(p_push_const)+16]={0};p_push_const *b=(p_push_const *)raw;b->compute=st==5;b->size=16;for(int j=0;j<16;j++)b->data[j]=(uint8_t)random_word();vka_state_op(d,OP_PUSH_CONST,b); }
        if(op==5) { d->b.samples=1u<<(random_word()%4);d->b.base_instance=random_word(); }
        if(op==6) { p_set_pool b={(const void *)(uintptr_t)(random_word()%512)};vka_state_op(d,OP_SET_TEX_POOL,&b);b.pool=(const void *)(uintptr_t)(random_word()%512);vka_state_op(d,OP_SET_SAMP_POOL,&b); }
        if(op==7) { *d=q[(qi+1)%3];p_bind_buf b={st,0,random_word(),64};vka_state_op(d,OP_BIND_SSBO,&b); }
        compare_bank(d,st,i%3==0?0:i%3==1?2:DMSH_PUSH_BANK,random_word()&1);
        if(i%71==0)drv_memo_reset();
    }
    // Fresh resets and divergent look-ahead copies must never share an
    // input stamp for different data, even with equal operation counts.
    vka_dstate a=q[0],b=q[0];p_bind_buf x={7,0,0x1000,64};
    vka_state_op(&a,OP_BIND_SSBO,&x);x.addr=0x2000;vka_state_op(&b,OP_BIND_SSBO,&x);
    assert(a.s_ssbo[7]!=b.s_ssbo[7]);compare_bank(&a,7,0,0);compare_bank(&b,7,0,0);compare_bank(&a,7,0,0);
    vka_dstate_reset(&a);vka_dstate_reset(&b);assert(a.s_tex[1]!=b.s_tex[1]);
    compare_bank(&a,1,DMSH_PUSH_BANK,0);compare_bank(&a,1,17,0);
    // Compute c0 can be patched by the GPU: it must not enter this memo.
    uint64_t old=fills;compare_bank(&a,5,0,0);compare_bank(&a,5,0,0);assert(fills==old+2);
    cleanup();
}
static void vertices(void) {
    vka_dstate d;vka_dstate_reset(&d);dmsh_vk_entry e={.vin_mask=15,.vin_types=0};vka_shader vs={&e};
    p_bind_vattr at={.first=0,.n=4};va_st attrs[4];
    for(int i=0;i<4;i++)attrs[i]=(va_st){.fmt=0x30,.offset=(uint32_t)(i*16),.stream=(uint32_t)i};memcpy(at.st,attrs,sizeof attrs);vka_state_op(&d,OP_BIND_VATTR,&at);
    p_bind_vstream streams={.first=0,.n=4};for(int i=0;i<4;i++)streams.st[i]=(vs_st){64,0};vka_state_op(&d,OP_BIND_VSTREAM,&streams);
    p_bind_vbuf buffers={.first=0,.n=4};for(int i=0;i<4;i++)buffers.r[i]=(NVNbufferRange){0x1000+(uint64_t)i*4096,4096};vka_state_op(&d,OP_BIND_VBUF,&buffers);
    for(int i=0;i<500;i++) {
        if(i%7==0) {attrs[0].offset=(random_word()%8)*4;memcpy(at.st,attrs,sizeof attrs);vka_state_op(&d,OP_BIND_VATTR,&at);}
        if(i%11==0) {buffers.r[0].address+=4096;vka_state_op(&d,OP_BIND_VBUF,&buffers);}
        if(i%13==0)mem_generation++;
        if(i%17==0)VB.valid=0;
        if(i%19==0)VB.vin_stale=1;
        vka_gkey k={0};g_vin_skip=1;vin_build_kept(&d,&vs,&k);vin_bind_kept(&d);
        typeof(VI) expected_vi=VI;typeof(gpu) expected_gpu=gpu;vka_gkey expected_key=k;uint64_t saved_ser=g_vi_ser;
        vka_gkey ref={0};vin_build(&d,&vs,&ref);vin_bind(&d);
        assert(!memcmp(&expected_vi,&VI,sizeof VI));assert(!memcmp(&expected_gpu,&gpu,sizeof gpu));assert(!memcmp(&expected_key,&ref,sizeof ref));
        g_vi_ser=saved_ser;
    }
    assert(g_vin_kept>0&&g_vb_kept>0);
    // Driver hardening after pipeline binding remains in force.
    V.vin_dyn=0;vka_gkey k={0};vin_build_kept(&d,&vs,&k);assert(k.vin_static);
    V.vin_dyn=1;
}
static double now(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static void benchmark(void) {
    vka_dstate d;vka_dstate_reset(&d);for(int i=0;i<VKA_NTEX;i++)d.b.tex[1][i]=(uint64_t)i+1;
    for(int on=0;on<=1;on++) {
        stamp_option=on;drv_memo_reset();VkDescriptorBufferInfo info;assert(drv_seg(&d,1,2,1,&info,NULL));
        uint64_t old=fills;double begin=now();for(int i=0;i<200000;i++)assert(drv_seg(&d,1,2,1,&info,NULL));double ns=(now()-begin)*1e9/200000;
        printf("driver stamp %d: %.2f ns/bind; %llu fills\n",on,ns,(unsigned long long)(fills-old));
        cleanup();
    }
}
int main(int argc,char **argv) { (void)argv;banks();vertices();if(argc>1)benchmark();puts("production input cache regression: ok");return 0; }
'''


class InputCaches(unittest.TestCase):
    def test_production_decoder_memo_and_vertex_equivalence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "cache.c"; source.write_text(program())
            common = ["cc", "-std=gnu11", "-O1", "-g", "-fsanitize=address,undefined", "-I", str(VK), "-I", str(ROOT / "dm/gfx/nvn"), "-I", str(ROOT / "dm/gfx/nvn/include"), "-I", str(ROOT / "dm/third_party/vulkan-headers/include")]
            subprocess.run([*common, "-Dvka_drv_fill=reference_drv_fill", "-c", str(VK / "vka_bind.c"), "-o", str(root / "bind.o")], check=True)
            subprocess.run([*common, str(source), str(root / "bind.o"), "-o", str(root / "cache")], check=True)
            subprocess.run([str(root / "cache")], check=True)


if __name__ == "__main__":
    unittest.main()
