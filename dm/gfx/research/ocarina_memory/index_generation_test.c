#include "index_generation_policy.h"
#include "pidx_reference.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(void){
 ri_slot s[4]={{1,0,1048576,1},{2,100,1048576,0},{3,101,1048576,0},{4,0,1048576,1}};
 assert(ri_pick(s,4,4,5,99,1048576,4*1048576)==RI_FALLBACK);
 assert(ri_pick(s,4,4,1,99,1048576,4*1048576)==0); // same immutable generation
 assert(ri_pick(s,4,4,5,100,1048576,4*1048576)==1);
 assert(ri_pick(s,1,4,5,0,1048576,1048576)==RI_FALLBACK);
 assert(ri_pick(s,1,4,5,0,1048576,2*1048576)==RI_ALLOCATE);
 uint64_t seed=179;
 for(int round=0;round<100000;round++){
  for(int i=0;i<4;i++){seed=seed*6364136223846793005ULL+1;s[i]=(ri_slot){seed&7,(seed>>4)&255,1048576,(seed>>20)&1};}
  uint64_t gen=(seed>>30)&7,done=(seed>>38)&255;
  int r=ri_pick(s,4,4,gen,done,1048576,4*1048576);
  if(r>=0)assert(s[r].generation==gen||(!s[r].recorded&&s[r].fence<=done));
 }
 // Actual index builder: a second mapping generation must not change a
 // previously recorded generation's addresses. Updating in place DOES change
 // them, even before submission; this is the negative control we must avoid.
 uint64_t lo[1]={0x100000},hi[1]={0x102000},delta[1]={0x400000};
 uint64_t al[2],ah[2],ad[2],bl[2],bh[2],bd[2];
 uint8_t a[64]={0},b[64]={0};vka_pidx_stats st={0};
 vka_pidx A={.max=2,.lo=al,.hi=ah,.dl=ad},B={.max=2,.lo=bl,.hi=bh,.dl=bd};
 assert(vka_pidx_update(a,4,&A,lo,hi,delta,1,1,&st));
 uint64_t old=((uint64_t*)(a+16))[0];delta[0]=0x800000;
 assert(vka_pidx_update(b,4,&B,lo,hi,delta,1,1,&st));
 assert(((uint64_t*)(a+16))[0]==old&&((uint64_t*)(b+16))[0]!=old);
 assert(vka_pidx_update(a,4,&A,lo,hi,delta,1,1,&st));
 assert(((uint64_t*)(a+16))[0]!=old); // demonstrates old-reader corruption
 puts("100000 ownership schedules; bounded fallback; immutable generations; in-place negative control detected");
 return 0;
}
