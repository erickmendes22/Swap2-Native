// RAM pressure and image lifetime rules: independent of Android/Vulkan.
#include <stdio.h>
#include "../../gfx/vk_android/vka_texlimit.h"
#define M VKTL_MIB
static int failures;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAILED line %d: %s\n",__LINE__,#x); failures++; } } while (0)
int main(void) {
    CHECK(vktl_reserve(12ull<<30) == (12ull<<30)/8);
    CHECK(vktl_reserve(8ull<<30) == (8ull<<30)/8);
    CHECK(vktl_reserve(16ull<<30) == VKTL_FLOOR);
    vktl_in v = {.mem_total=12ull<<30,.mem_avail=2ull<<30,.img_bytes=2200*M};
    CHECK(vktl_limit(&v) == 2200*M + 512*M);
    v.mem_avail=800*M;
    CHECK(vktl_limit(&v)==2200*M);
    CHECK(vktl_pressure_limit(3200*M,2400*M,400)==3200*M);
    CHECK(vktl_pressure_limit(3200*M,2400*M,500)==2400*M);
    CHECK(vktl_pressure_limit(3200*M,2400*M,1500)==2100*M);
    CHECK(vktl_pressure_limit(700*M,2400*M,1500)==700*M);
    CHECK(vktl_target(1600*M)==1500*M);
    CHECK(!vktl_evictable(100,99,0,0,0,1));
    CHECK(vktl_evictable(100,98,0,0,0,1));
    CHECK(!vktl_evictable(100,40,1,0,0,1));
    CHECK(!vktl_evictable(100,40,0,1,0,1));
    CHECK(!vktl_evictable(100,40,0,0,1,1));
    CHECK(!vktl_evictable(100,40,0,0,0,0));
    CHECK(vktl_order(1,2)<0 && vktl_order(3,2)>0 && !vktl_order(3,3));
    v.heap_budget=4ull<<30; v.heap_usage=3400*M;
    CHECK(vktl_limit(&v)<=v.heap_budget);
    puts(failures ? "t_android_texlimit: FAILED" : "t_android_texlimit: ok");
    return !!failures;
}
