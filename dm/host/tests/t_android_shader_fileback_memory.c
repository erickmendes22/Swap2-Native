// Actual file-backing primitive: CPU bytes remain correct and clean pages can
// be reclaimed. Explicit PAGEOUT here simulates OS reclaim, not runtime policy.
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "vka_fileback.h"
#ifndef MADV_PAGEOUT
#define MADV_PAGEOUT 21
#endif
static uint64_t pss(void){
 FILE*f=fopen("/proc/self/smaps_rollup","r");assert(f);char b[512];unsigned long long v=0;
 while(fgets(b,sizeof b,f))if(sscanf(b,"Pss: %llu",&v)==1)break;fclose(f);assert(v);return v;
}
int main(int argc,char**argv){
 assert(argc==2);size_t n=32u<<20;uint64_t initial=pss();
 uint8_t*p=mmap(0,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(p!=MAP_FAILED);memset(p,0x5b,n);uint64_t anonymous=pss();
 int error=0,fd=vkfb_open(argv[1],&error);assert(fd>=0);uint64_t next=0;int64_t off=vkfb_alloc(fd,&next,n);assert(off>=0);
 vkfb_run run={(uintptr_t)p,(uintptr_t)p+n};uint64_t copied=0;int lost=0;
 assert(!vkfb_to_file(fd,(uint64_t)off,(uintptr_t)p,n,&run,1,-1,&copied,&lost)&&!lost&&copied==n);
 uint64_t backed=pss();assert(!msync(p,n,MS_SYNC));assert(!madvise(p,n,MADV_PAGEOUT));uint64_t reclaimed=pss();
 // Neither successful remapping nor a zero Vulkan allocation guarantees lower
 // physical use until the backing pages are reclaimed.
 assert(anonymous>initial+24u*1024);assert(backed>initial+24u*1024);
 assert(reclaimed+24u*1024<backed);
 for(size_t i=0;i<n;i++)assert(p[i]==0x5b);uint64_t reread=pss();
 printf("initial=%llu anonymous=%llu file_backed=%llu after_explicit_reclaim=%llu after_full_reread=%llu KiB; data exact\n",(unsigned long long)initial,(unsigned long long)anonymous,(unsigned long long)backed,(unsigned long long)reclaimed,(unsigned long long)reread);
 munmap(p,n);close(fd);return 0;
}
