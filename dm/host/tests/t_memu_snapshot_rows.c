#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <vulkan/vulkan_core.h>
#include "nvn_obj.h"
#include "vka_bind.h"
#include "snapshot_under_test.h"
static uint64_t rng=UINT64_C(0x123456789abcdef);
static uint32_t random_word(void){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;return(uint32_t)rng;}
static int read_guest(void*ctx,uint64_t addr,void*out,size_t n){(void)ctx;for(size_t i=0;i<n;i++)((uint8_t*)out)[i]=(uint8_t)((addr+i)*37u);return 1;}
static uint64_t ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return(uint64_t)t.tv_sec*1000000000u+t.tv_nsec;}
static __attribute__((noinline)) void full_copy(vka_dstate*d,const vka_dstate*s){memcpy(d,s,sizeof *s);__asm__ volatile(""::"g"(d):"memory");}
static __attribute__((noinline)) void projected_copy(vka_dstate*d,const vka_dstate*s){memu_snapshot_capture(d,s);__asm__ volatile(""::"g"(d):"memory");}
int main(void){
 vka_dstate *s=malloc(sizeof*s),*d=malloc(sizeof*d);assert(s&&d);
 const unsigned kinds[]={DMSH_VK_KIND_CBUF,DMSH_VK_KIND_C1,DMSH_VK_KIND_DRVCB,DMSH_VK_KIND_SUPPORT,DMSH_VK_KIND_SBUF,DMSH_VK_KIND_UBO_PTR,DMSH_VK_KIND_SBUF_UBO,DMSH_VK_KIND_TEX,DMSH_VK_KIND_TEX_UBO,DMSH_VK_KIND_TEX_C2A,DMSH_VK_KIND_TBUF,DMSH_VK_KIND_IMG,DMSH_VK_KIND_SAMP,DMSH_VK_KIND_SAMP_TEX,DMSH_VK_KIND_SAMP_ID,DMSH_VK_KIND_SAMP_UBO,DMSH_VK_KIND_SAMP_C2A,DMSH_VK_KIND_GMEM_MAP,DMSH_VK_KIND_GMEM_LOG,DMSH_VK_KIND_SHARED_SPILL};
 dmsh_vk_bind binds[sizeof kinds/sizeof kinds[0]];memset(binds,0,sizeof binds);
 for(unsigned i=0;i<sizeof kinds/sizeof kinds[0];i++)binds[i]=(dmsh_vk_bind){.kind=kinds[i],.desc=VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,.binding=i,.count=1,.reg=i%16,.sreg=i%16,.off=0,.soff=0,.skind=DMSH_VK_KIND_SAMP_TEX};
 dmsh_vk_entry e={0};e.bind_count=sizeof kinds/sizeof kinds[0];
 uint64_t banks=0,walks=0;
 for(unsigned trial=0;trial<4096;trial++){
  for(size_t i=0;i<sizeof*s;i++)((uint8_t*)s)[i]=(uint8_t)random_word();
  s->b.tex_base=random_word()&1023;s->b.samp_base=random_word()&1023;
  // Poison unrelated rows. Any accidental cross-stage read disagrees with
  // the full reference instead of hiding behind zero-initialized memory.
  memset(d,0xa5,sizeof*d);memu_snapshot_capture(d,s);
  assert(!memcmp((char*)d+offsetof(vka_dstate,bst),(char*)s+offsetof(vka_dstate,bst),sizeof*s -offsetof(vka_dstate,bst)));
  assert(!memcmp((char*)&d->b+offsetof(vka_bstate,push),(char*)&s->b+offsetof(vka_bstate,push),sizeof s->b -offsetof(vka_bstate,push)));
  for(int st=6;st<8;st++){
   assert(!memcmp(d->b.ubo[st],s->b.ubo[st],sizeof s->b.ubo[st]));assert(!memcmp(d->b.ssbo[st],s->b.ssbo[st],sizeof s->b.ssbo[st]));
   assert(!memcmp(d->b.tex[st],s->b.tex[st],sizeof s->b.tex[st]));assert(!memcmp(d->b.samp[st],s->b.samp[st],sizeof s->b.samp[st]));assert(!memcmp(d->b.img[st],s->b.img[st],sizeof s->b.img[st]));
   const int bank[]={0,2,DMSH_PUSH_BANK};for(unsigned b=0;b<3;b++)for(int pool=0;pool<2;pool++){
    uint8_t x[DMSH_DRV_SIZE+DMSH_PUSH_SIZE],y[sizeof x];memset(x,0x7d,sizeof x);memset(y,0x7d,sizeof y);vka_drv_fill(&s->b,st,bank[b],pool,x);vka_drv_fill(&d->b,st,bank[b],pool,y);assert(!memcmp(x,y,sizeof x));banks++;
   }
   vka_res x[64],y[64];int px=0,py=0;char ex[128]={0},ey[128]={0};
   int nx=vka_walk(&s->b,st,&e,binds,16,16,read_guest,NULL,x,64,&px,ex,sizeof ex),ny=vka_walk(&d->b,st,&e,binds,16,16,read_guest,NULL,y,64,&py,ey,sizeof ey);
   assert(nx==ny&&px==py&&!strcmp(ex,ey));
   for(int i=0;i<nx;i++){
#define EQ(f) assert(x[i].f==y[i].f)
    EQ(what);EQ(desc);EQ(flags);EQ(dim);EQ(binding);EQ(elem);EQ(bank);EQ(tid);EQ(sid);EQ(addr);EQ(size);
#undef EQ
   }
   walks++;
  }
  // Original guest state may be reused/mutated immediately after capture.
  uint64_t old=d->b.tex[6][0];s->b.tex[6][0]^=UINT64_MAX;assert(d->b.tex[6][0]==old);
 }
 size_t bytes=2*(sizeof s->b.ubo[0]+sizeof s->b.ssbo[0]+sizeof s->b.tex[0]+sizeof s->b.samp[0]+sizeof s->b.img[0])+sizeof s->b -offsetof(vka_bstate,push)+sizeof*s -offsetof(vka_dstate,bst);
 printf("snapshot parity: %llu driver banks, %llu descriptor walks exact; %zu -> %zu copied bytes/draw (%.1f%% less)\n",(unsigned long long)banks,(unsigned long long)walks,sizeof*s,bytes,100.0*(sizeof*s-bytes)/sizeof*s);
 enum{N=64,ITERS=30000};vka_dstate *src=malloc(N*sizeof*src),*dst=malloc(N*sizeof*dst);assert(src&&dst);memset(src,0x37,N*sizeof*src);memset(dst,0,N*sizeof*dst);
 for(int round=0;round<3;round++)for(int j=0;j<2;j++){
  int projected=j^(round&1);uint64_t t=ns();for(int i=0;i<ITERS;i++){unsigned k=i%N;if(projected)projected_copy(&dst[k],&src[k]);else full_copy(&dst[k],&src[k]);}t=ns()-t;
  printf("snapshot copy microbenchmark round%d %s:%.1f ns/draw (host CPU only, not phone FPS)\n",round,projected?"rows":"full",(double)t/ITERS);
 }
 free(src);free(dst);free(s);free(d);return 0;
}
