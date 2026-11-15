// Research-only bounded ownership policy. No renderer hooks or allocations.
// A recorded reader is ownership even before a fence exists. Never rewrite it.
#pragma once
#include <stdint.h>
enum{RI_FALLBACK=-1,RI_ALLOCATE=-2};
typedef struct{uint64_t generation,fence,bytes;int recorded;}ri_slot;
static inline int ri_pick(const ri_slot*s,int n,int max,uint64_t gen,uint64_t done,uint64_t need,uint64_t budget){
 if(n<0||n>max||!need||need>budget)return RI_FALLBACK;
 uint64_t used=0;
 for(int i=0;i<n;i++){
  if(s[i].bytes>budget-used)return RI_FALLBACK;
  used+=s[i].bytes;
 }
 for(int i=0;i<n;i++)if(s[i].generation==gen&&s[i].bytes>=need)return i;
 for(int i=0;i<n;i++)if(!s[i].recorded&&s[i].fence<=done&&s[i].bytes>=need)return i;
 if(n<max&&need<=budget-used)return RI_ALLOCATE;
 return RI_FALLBACK; // use the original search; no wait and no in-place overwrite
}
