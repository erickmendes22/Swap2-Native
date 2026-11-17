// Exact source-pair routing guard for experimental Ocarina native mesh.
#include <assert.h>
#include <stdint.h>
#include "vka_oot_mesh_pair.h"
int main(void) {
    const uint64_t e = UINT64_C(0xeb021183bf9b0092);
    const uint64_t f = UINT64_C(0xfed302d791a4ba43);
    const uint64_t a = UINT64_C(0x087ef21b3a72ad3a);
    const uint64_t b = UINT64_C(0x0fb4823639295a2d);
    assert(vka_oot_hot_native_mesh_pair(e,a));
    assert(vka_oot_hot_native_mesh_pair(f,b));
    assert(!vka_oot_hot_native_mesh_pair(e,b));
    assert(!vka_oot_hot_native_mesh_pair(f,a));
    assert(!vka_oot_hot_native_mesh_pair(e,0));
    assert(!vka_oot_hot_native_mesh_pair(0,a));
    assert(!vka_oot_hot_native_mesh_pair(0,0));
    assert(!vka_oot_hot_native_mesh_pair(e,UINT64_C(0x1)));
    return 0;
}
