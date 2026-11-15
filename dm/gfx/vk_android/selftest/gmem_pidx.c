// Standalone CPU validation of the production page index; build with:
// cc -std=c11 -O2 -Wall -Wextra -Werror -I dm/gfx/vk_android
//   dm/gfx/vk_android/selftest/gmem_pidx.c -o /tmp/gmem_pidx && /tmp/gmem_pidx
#include "../vka_gmem_pidx.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
static uint64_t rng = UINT64_C(0x91720261115);
static uint64_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; }
static int reference(uint64_t a,const uint64_t *lo,const uint64_t *hi,int n) {
    int at = 0;
    for (int i=0;i<n;i++) if (a>=lo[i]&&a<hi[i]) at=i+1;
    return at;
}
static int indexed(uint64_t a,const uint32_t *w,const uint64_t *lo,const uint64_t *hi,int n) {
    uint64_t page=a>>12;
    if (page < (UINT64_C(1)<<32) && w[1] && page>=w[0] && page-w[0]<w[1]) {
        uint32_t x=w[4+(size_t)(page-w[0])];
        if (x && x<8192 && x<=(uint32_t)n) {
            // As in the compiler: records only cover whole pages, but also
            // recheck the exact range so stale/invalid claims never win.
            if (a>=lo[x-1]&&a<hi[x-1]) return (int)x;
        }
    }
    return reference(a,lo,hi,n);
}
int main(void) {
    enum {N=70, WORDS=4+4096};
    uint64_t lo[N],hi[N]; uint32_t w[WORDS];
    uint64_t start=UINT64_C(0x1020000000);
    for (int i=0;i<N;i++) {
        start+=4096 + (rnd()%8192);
        lo[i]=start+(rnd()%33);
        hi[i]=lo[i]+4096+(rnd()%131072);
        start=hi[i];
    }
    size_t cov=vka_gmem_pidx_build(w,WORDS,lo,hi,N);
    assert(cov && w[1]==WORDS-4);
    for(int i=0;i<200000;i++) {
        uint64_t a;
        switch(i%5) {
        case 0: a=lo[rnd()%N]+rnd()%4096;break;
        case 1: a=hi[rnd()%N]-1;break;
        case 2: a=hi[rnd()%N];break;
        case 3: a=lo[0]+rnd()%(hi[N-1]-lo[0]);break;
        default: a=(rnd()&1)?(UINT64_C(1)<<44):(lo[0]-8192);break;
        }
        assert(indexed(a,w,lo,hi,N)==reference(a,lo,hi,N));
    }
    uint64_t badlo[2]={0x1000,0x2000},badhi[2]={0x3000,0x4000};
    assert(!vka_gmem_pidx_build(w,WORDS,badlo,badhi,2) && !w[1]);
    assert(!vka_gmem_pidx_build(w,3,lo,hi,N));
    assert(!vka_gmem_pidx_build(w,WORDS,NULL,hi,N)&&!w[1]);
    uint64_t edgeLo[1]={UINT64_C(0xffefff000)},edgeHi[1]={UINT64_C(0xfff001000)};
    assert(vka_gmem_pidx_build(w,WORDS,edgeLo,edgeHi,1));
    uint64_t beyond[1]={UINT64_C(1)<<45}, beyondHi[1]={(UINT64_C(1)<<45)+8192};
    assert(!vka_gmem_pidx_build(w,WORDS,beyond,beyondHi,1) && !w[1]);
    puts("GMEM page index: 200000 differential lookups, partial pages, overlap and 32-bit page bound passed");
    return 0;
}
