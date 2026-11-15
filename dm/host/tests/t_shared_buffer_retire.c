// Exercise the production unplace() with real Linux FD aliases and page protections.
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <errno.h>
typedef struct {uintptr_t lo,hi;int mem,fd_alias;} seg_t;
typedef struct {uintptr_t lo,hi;int prot;} prun;
#define MAXRUN 8
#define VKA_ENV(key,default_value) 0
#define VRED_ONCE(...) ((void)0)
#define VRED(...) ((void)0)
#define VLOG(...) ((void)0)
static int ready,freed,checks,closed_fd;static void *driver;static size_t bytes;
static uint64_t vka_fence_last(void){return 73;}
static uint64_t vka_hang_ns(void){return 100;}
static int vka_wait_done(uint64_t f,uint64_t n){assert(f==73 && n==100);return ready;}
static int vka_hung(void){return 0;}
static int prot_runs(uintptr_t lo,uintptr_t hi,prun *p,int n){assert(n>=2);p[0]=(prun){lo,lo+8192,PROT_READ};p[1]=(prun){lo+8192,hi,PROT_READ|PROT_WRITE};return 2;}
static int prot_known(prun *p,int *n,uintptr_t lo,uintptr_t hi){(void)p;(void)n;(void)lo;(void)hi;return 1;}
static void swap_begin(uintptr_t lo,uintptr_t hi){assert(lo<hi);}
static void prot_readonly(prun *p,int n){for(int i=0;i<n;i++)assert(!mprotect((void*)p[i].lo,p[i].hi-p[i].lo,PROT_READ));}
static void unmap_placed(int m){(void)m;assert(!"shared alias must not use placed unmap");}
static void seg_free(seg_t *s,int waited,uint64_t fence){
 assert(s->fd_alias && fence==73);if(!waited)return;
 // Anonymous replacement must be installed BEFORE driver memory is freed.
 ((uint32_t*)driver)[0]^=0x1234;
 assert(*(uint32_t*)s->lo!=*(uint32_t*)driver);
 assert(!munmap(driver,bytes));close(closed_fd);freed++;
}
static void sw_hole_check(uintptr_t lo,size_t n,int was_freed,const char *why){
 (void)why;assert(!was_freed);assert(!msync((void*)lo,n,MS_ASYNC));checks++;
}
static void *sw_mremap_to(void *from,size_t n,uintptr_t to){return mremap(from,n,n,MREMAP_MAYMOVE|MREMAP_FIXED,(void*)to);}
static void *sw_mmap_fixed(uintptr_t lo,size_t n){return mmap((void*)lo,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);}
static int sw_mprotect(uintptr_t lo,size_t n,int prot){return mprotect((void*)lo,n,prot);}
static void swap_end_ok(int ok){assert(ok);}
static void swap_end(void){}
static uint64_t vka_mem_placed_bytes(void *p){(void)p;return 0;}
static void unexpected_unmap(int d,int m){(void)d;(void)m;assert(!"unexpected unmap");}
static int unexpected_map(int d,int m,int a,int b,int c,void **p){(void)d;(void)m;(void)a;(void)b;(void)c;(void)p;assert(0);return 1;}
struct {int dev;} V;
struct {void (*vkUnmapMemory)(int,int);int (*vkMapMemory)(int,int,int,int,int,void**);} vk={unexpected_unmap,unexpected_map};
#define VK_WHOLE_SIZE 0
#include "shared_unplace.inc"
static int permissions(void *at){
 FILE *f=fopen("/proc/self/maps","r");assert(f);char line[512],mode[5];unsigned long lo,hi;int found=0;
 while(fgets(line,sizeof line,f))if(sscanf(line,"%lx-%lx %4s",&lo,&hi,mode)==3 && (uintptr_t)at>=lo && (uintptr_t)at<hi){found=mode[1]=='w'?3:1;break;}
 fclose(f);return found;
}
int main(void){
 bytes=16384;
 for(ready=0;ready<2;ready++){
  freed=checks=0;closed_fd=memfd_create("shared-lifecycle",0);assert(closed_fd>=0 && !ftruncate(closed_fd,bytes));
  driver=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_SHARED,closed_fd,0);assert(driver!=MAP_FAILED);
  uint8_t *guest=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_SHARED,closed_fd,0);assert(guest!=MAP_FAILED);
  for(size_t i=0;i<bytes;i++)((uint8_t*)driver)[i]=(i/4096)%2 ? 0 : (uint8_t)(i*13+7);
  uint8_t expected[16384];memcpy(expected,guest,bytes);
  assert(!mprotect(guest,8192,PROT_READ));
  seg_t segment={(uintptr_t)guest,(uintptr_t)guest+bytes,1,1};
  unplace(&segment);
  assert(checks==1 && freed==ready && !memcmp(expected,guest,bytes));
  assert(permissions(guest)==1 && permissions(guest+8192)==3);
  if(!ready){((uint8_t*)driver)[9000]^=0xff;assert(guest[9000]==expected[9000]);munmap(driver,bytes);close(closed_fd);}
  munmap(guest,bytes);
 }
 puts("FD alias retirement: bytes, zero pages, protections, incomplete fence and free ordering exact");return 0;
}
