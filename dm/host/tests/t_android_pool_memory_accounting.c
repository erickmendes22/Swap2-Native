// Physical-memory regression: driver allocation counters are not process PSS.
// Run in a fresh process per case, using real Linux mappings and production
// copy_readable + Shared buffer MAP_FIXED replacement code extracted by Python.
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
typedef struct {uintptr_t lo,hi;int prot;}prun;
#include "pool_copy.inc"
static void sw_hole_check(uintptr_t a,size_t n,int freed,const char*why){(void)a;(void)n;(void)freed;(void)why;abort();}
static void *sw_mmap_fixed(uintptr_t a,size_t n){return mmap((void*)a,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);}
#define VK_SUCCESS 0
#define VK_ERROR_MEMORY_MAP_FAILED (-5)
static void replace_with_exported_pool(uintptr_t lo,size_t n,void*p,int fd){
 struct{int fd_alias;}s={1};struct{int fd;}exported={fd};int ok=0,r=-1;
 prun run={lo,lo+n,PROT_READ|PROT_WRITE};copy_readable(p,lo,&run,1);
#include "pool_map.inc"
 assert(ok&&r==0);
}
static void memory(uint64_t*rss,uint64_t*pss){
 FILE*f=fopen("/proc/self/smaps_rollup","r");if(!f)exit(77);char b[512];*rss=*pss=0;
 while(fgets(b,sizeof b,f)){unsigned long long n;if(sscanf(b,"Rss: %llu",&n)==1)*rss=n;if(sscanf(b,"Pss: %llu",&n)==1)*pss=n;}fclose(f);assert(*rss&&*pss);
}
int main(int argc,char**argv){
 assert(argc==3);int defer=atoi(argv[1]),stride=atoi(argv[2]);assert((defer==0||defer==1)&&(stride==1||stride==4));
 uint64_t r0,p0,r1,p1;memory(&r0,&p0);size_t n=64u<<20,page=(size_t)getpagesize();
 uint8_t*guest=mmap(0,n,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(guest!=MAP_FAILED);
 for(size_t i=0;i<n;i+=page*(size_t)stride)guest[i]=(uint8_t)((i/page)%251+1);
 void*driver=MAP_FAILED;int fd=-1;
 if(!defer){fd=memfd_create("actual-pool-placement",0);assert(fd>=0&&!ftruncate(fd,(off_t)n));driver=mmap(0,n,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);assert(driver!=MAP_FAILED);replace_with_exported_pool((uintptr_t)guest,n,driver,fd);}
 uint64_t checksum=0;for(size_t i=0;i<n;i+=page){uint8_t expected=(i/page)%(size_t)stride?0:(uint8_t)((i/page)%251+1);assert(guest[i]==expected);checksum+=guest[i];}
 memory(&r1,&p1);
 printf("%d,%d,%llu,%llu,%llu,%llu\n",defer,stride,(unsigned long long)(defer?0:n/1024),(unsigned long long)(r1-r0),(unsigned long long)(p1-p0),(unsigned long long)checksum);
 munmap(guest,n);if(driver!=MAP_FAILED)munmap(driver,n);if(fd>=0)close(fd);return 0;
}
