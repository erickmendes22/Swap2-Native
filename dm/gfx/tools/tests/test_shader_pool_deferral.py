"""Execute actual shader-pool policy and NVN data hooks, without a phone."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
NVN=ROOT/'dm/gfx/nvn'
SOURCE=(NVN/'hle_nvn.c').read_text()

def function(src,sig):
 a=src.index(sig);p=src.index('{',a);i=p+1;d=1
 while d:d+=(src[i]=='{')-(src[i]=='}');i+=1
 return src[a:i]

def policy():
 a=SOURCE.index('enum { SHP_MAX');b=SOURCE.index('__attribute__((weak)) void dm_gfx_pool_fileback',a)
 return SOURCE[a:b]

PREFIX=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>
#include "nvn_obj.h"
static void log_stub(const char *fmt,...){(void)fmt;}
#define LOG(...) log_stub(__VA_ARGS__)
#define NVN(name,ret,...) static ret h_##name(__VA_ARGS__)
static uint64_t calls,bytes,requested,lastaddr,lastlen,unmapped;
static void mtl_pool_need(const void*p,uint64_t n,const char*why){assert(p&&n&&why);calls++;bytes+=n;lastaddr=(uintptr_t)p;lastlen=n;}
static uint64_t dm_guest_unmapped(uintptr_t p,uint64_t n){(void)p;(void)n;return unmapped;}
static void pc_use(const pool_t*p,char k,uint64_t a,uint64_t n){(void)p;(void)k;(void)a;(void)n;}
static unsigned char record[1024];
#define REC(c,op,type) ((type *)(void*)record)
static void ssbo_slot_check(int s,int i){assert(s>=0&&i>=0);}
'''

class ShaderPoolDeferral(unittest.TestCase):
 def compile_run(self,code):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'test.c').write_text(code)
   r=subprocess.run([shutil.which('cc'),'-std=gnu11','-O1','-g','-fsanitize=address,undefined','-I',str(NVN),'-I',str(NVN/'include'),str(p/'test.c'),'-lpthread','-o',str(p/'test')],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(p/'test')],env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),capture_output=True,text=True,timeout=60)
   self.assertEqual(r.returncode,0,r.stdout+r.stderr)

 def test_actual_queries_data_bind_lifetime_and_overflow(self):
  hooks='\n'.join(function(SOURCE,'NVN('+n+',')for n in ['nvnMemoryPoolGetBufferAddress','nvnCommandBufferBindStorageBuffer'])
  code=PREFIX+policy()+hooks+r'''
int main(void){
 size_t MiB=1u<<20;uint8_t *mem=mmap(0,512*MiB,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(mem!=MAP_FAILED);
 pool_t p[3]={{.mem=mem,.size=244*MiB},{.mem=mem+250*MiB,.size=100*MiB},{.mem=mem+400*MiB,.size=MiB}};
 g_shp_place=0;g_shp_log=0;for(int i=0;i<3;i++)shp_add(&p[i],i+1);
 // Same 345 MiB logical shader-pool layout: no driver allocation for addresses.
 for(int i=0;i<3;i++)assert(h_nvnMemoryPoolGetBufferAddress((NVNmemoryPool*)&p[i])==(uintptr_t)p[i].mem);
 assert(!calls&&!bytes);assert(nvn_shader_code_readable((uintptr_t)mem+16,32));
 assert(!nvn_shader_code_readable((uintptr_t)mem+244*MiB-4,8));
 assert(!nvn_shader_code_readable(UINT64_MAX-4,16));
 unmapped=1;assert(!nvn_shader_code_readable((uintptr_t)mem,4));unmapped=0;
 for(int kind=SHK_TEX;kind<SHK_N;kind++){
  uint64_t before=calls;shp_bind(kind,(uintptr_t)mem+32,64);assert(calls==before+1&&lastaddr==(uintptr_t)mem+32&&lastlen==64);
 }
 // Real NVN storage binding still records identical arguments after placing data.
 h_nvnCommandBufferBindStorageBuffer(0,5,3,(uintptr_t)mem+64,128);
 p_bind_buf *r=(p_bind_buf*)record;assert(r->stage==5&&r->index==3&&r->addr==(uintptr_t)mem+64&&r->size==128);
 // A command crossing both shader pools must place its WHOLE original range.
 shp_bind(SHK_COPY,(uintptr_t)mem+240*MiB,20*MiB);assert(lastaddr==(uintptr_t)mem+240*MiB&&lastlen==20*MiB);
 // Unknown length means the remainder of the containing shader pool.
 shp_bind(SHK_IBUF,(uintptr_t)p[1].mem+MiB,0);assert(lastlen==99*MiB);
 // Finalize, reuse and unknown addresses cannot suppress normal allocation.
 shp_del(&p[1]);assert(!shp_skip(SHK_ADDR,(uintptr_t)p[1].mem,1));shp_add(&p[1],99);
 shp_del(&p[0]);assert(!nvn_shader_code_readable((uintptr_t)mem,4));shp_add(&p[0],100);
 g_shp_place=1;calls=bytes=0;
 for(int i=0;i<3;i++)h_nvnMemoryPoolGetBufferAddress((NVNmemoryPool*)&p[i]);assert(bytes==345*MiB&&calls==3);
 // Opt-out still returns the same addresses and commits the historical amount.
 pool_t bad={.mem=(uint8_t*)(uintptr_t)(UINT64_MAX-32),.size=64};int count=atomic_load(&g_shp_n);shp_add(&bad,999);assert(atomic_load(&g_shp_n)==count);
 munmap(mem,512*MiB);return 0;
}
'''
  self.compile_run(code)

 def test_cpu_shader_hash_guard_uses_live_guest_code(self):
  # Execute the real mapping condition in keys_hash, including a negative control
  # for the old mtl_addr-only guard; hashes still consume the same guest bytes.
  f=function(SOURCE,'static int keys_hash(')
  self.assertIn('nvn_shader_code_readable(sd->data, ncode)',f)
  code=PREFIX+policy()+r'''
static uint32_t ncode=64;
static int mtl_addr(uint64_t a,uint64_t n,void**b,uint64_t*o){(void)a;(void)n;(void)b;(void)o;return 0;}
void nvn_ctl_lens(const void*p,uint32_t*a,uint32_t*b){(void)p;*a=16;*b=ncode;}
static int nvn2_ctl(const void*p){(void)p;return 0;}
#define NVN2_KEY_CTL 16
#define DM_GAME_SHADER_KEY_SKIP_LEN 0
#define DM_GAME_SHADER_KEY_SKIP_OFF 0
typedef struct{uint64_t v;}plat_sha256_t;
static void plat_sha256_init(plat_sha256_t*p){p->v=0;}
static void plat_sha256_update(plat_sha256_t*p,const void*d,size_t n){for(size_t i=0;i<n;i++)p->v=p->v*131+((const uint8_t*)d)[i];}
static void plat_sha256_final(uint8_t*d,plat_sha256_t*p){memset(d,0,32);memcpy(d,&p->v,8);}
'''+f+r'''
int main(void){uint8_t data[128],ctl[16]={0},got[8],expected[32];for(int i=0;i<128;i++)data[i]=(uint8_t)i;
 pool_t p={.mem=data,.size=128};g_shp_place=0;shp_add(&p,1);
 NVNshaderData sd={.data=(uintptr_t)data,.control=ctl};assert(keys_hash(&sd,1,got));
 plat_sha256_t hash;plat_sha256_init(&hash);plat_sha256_update(&hash,ctl,16);plat_sha256_update(&hash,data,64);plat_sha256_final(expected,&hash);assert(!memcmp(got,expected,8));
 shp_del(&p);assert(!keys_hash(&sd,1,got));return 0;}
'''
  self.compile_run(code)

 def test_all_address_command_hooks_and_fallbacks_are_preserved(self):
  expected={
   'nvnCommandBufferReportCounter':'SHK_REPORT','nvnCommandBufferReportValue':'SHK_REPORT',
   'nvnCommandBufferCopyBufferToBuffer':'SHK_COPY','nvnCommandBufferCopyBufferToTexture':'SHK_COPY','nvnCommandBufferCopyTextureToBuffer':'SHK_COPY',
   'nvnCommandBufferUpdateUniformBuffer':'SHK_UPDATE','nvnCommandBufferClearBuffer':'SHK_CLEAR',
   'nvnCommandBufferBindVertexBuffers':'SHK_VBUF','nvnCommandBufferBindUniformBuffer':'SHK_UBO',
   'nvnCommandBufferBindStorageBuffer':'SHK_SSBO','nvnCommandBufferBindStorageBuffers':'SHK_SSBO',
   'nvnCommandBufferDispatchComputeIndirect':'SHK_IND','nvnCommandBufferBindTransformFeedbackBuffer':'SHK_XFB',
   'nvnCommandBufferBindTransformFeedbackBuffers':'SHK_XFB','nvnCommandBufferBeginTransformFeedback':'SHK_XFB',
   'nvnCommandBufferEndTransformFeedback':'SHK_XFB','nvnCommandBufferPauseTransformFeedback':'SHK_XFB',
   'nvnCommandBufferResumeTransformFeedback':'SHK_XFB','nvnCommandBufferDrawTransformFeedback':'SHK_XFB',
   'nvnCommandBufferSetRenderEnableConditional':'SHK_COND','nvnMemoryPoolMapVirtual':'SHK_MAP'}
  for n,kind in expected.items():
   f=function(SOURCE,'NVN('+n+',');self.assertIn('shp_bind('+kind,f,n)
   if '*REC('in f:self.assertLess(f.index('shp_bind('),f.index('*REC('),n)
  self.assertIn('shp_bind(SHK_IBUF',function(SOURCE,'static void rec_draw_idx('))
  self.assertIn('shp_bind(SHK_IND',function(SOURCE,'static void rec_draw('))
  self.assertIn('shp_use(SHK_TEX',function(SOURCE,'NVN(nvnTextureInitialize,'))
  self.assertIn('shp_add(o, gen)',function(SOURCE,'NVN(nvnMemoryPoolInitialize,'))
  self.assertIn('shp_del(',function(SOURCE,'NVN(nvnMemoryPoolFinalize,'))
  self.assertIn('SHP_PLACE_DEFAULT = 1',SOURCE)
  self.assertIn('n ? n : pn',function(SOURCE,'static void shp_bind_slow('))

if __name__=='__main__':unittest.main()
