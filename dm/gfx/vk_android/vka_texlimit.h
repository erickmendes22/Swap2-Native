// CPU-only Vulkan image-cache policy. Preserve live GPU content, pending fences and recent resources.
// Android devices with <=12 GiB reserve at least 1/8 RAM; /proc/pressure/memory
// prevents growth before lmkd kills the foreground process.
#ifndef VKA_TEXLIMIT_H
#define VKA_TEXLIMIT_H
#include <stdint.h>
#define VKTL_MIB (1ull << 20)
#define VKTL_FLOOR (512ull * VKTL_MIB)
#define VKTL_SMALL (12ull << 30)
enum { VKTL_KEEP_FRAMES = 2 };
typedef struct {
    uint64_t mem_total, mem_avail, heap_size, heap_budget, heap_usage, img_bytes;
} vktl_in;
static inline uint64_t vktl_sub(uint64_t a, uint64_t b) { return a > b ? a - b : 0; }
static inline uint64_t vktl_reserve(uint64_t total) {
    if (total && total <= VKTL_SMALL) return total / 8 > VKTL_FLOOR ? total / 8 : VKTL_FLOOR;
    uint64_t r = total / 32;
    return r > VKTL_FLOOR ? r : VKTL_FLOOR;
}
static inline uint64_t vktl_limit(const vktl_in *in) {
    uint64_t lim = UINT64_MAX;
    if (in->mem_total && in->mem_avail) {
        uint64_t room = vktl_sub(in->mem_avail, vktl_reserve(in->mem_total));
        uint64_t l = in->img_bytes > UINT64_MAX - room ? UINT64_MAX : in->img_bytes + room;
        if (l < lim) lim = l;
    }
    if (in->heap_budget) {
        uint64_t other = vktl_sub(in->heap_usage, in->img_bytes);
        uint64_t l = vktl_sub(in->heap_budget - in->heap_budget / 16, other);
        if (l < lim) lim = l;
    } else if (in->heap_size) {
        uint64_t l = in->heap_size / 2;
        if (l < lim) lim = l;
    }
    return lim == UINT64_MAX || lim < VKTL_FLOOR ? VKTL_FLOOR : lim;
}
// PSI some avg10 in hundredths of a percent. >=5% stop growing;
// >=15% shed an eighth of the cache, subject to the 512 MiB floor.
static inline uint64_t vktl_pressure_limit(uint64_t limit, uint64_t images, unsigned psi100) {
    if (psi100 >= 1500) {
        uint64_t reduced = images - images / 8;
        if (reduced < VKTL_FLOOR) reduced = VKTL_FLOOR;
        return reduced < limit ? reduced : limit;
    }
    if (psi100 >= 500 && images > VKTL_FLOOR && images < limit) return images;
    return limit;
}
static inline uint64_t vktl_target(uint64_t limit) { return limit - limit / 16; }
static inline int vktl_evictable(uint64_t frame, uint64_t last, int holds, int gpu_owned,
                                  int fence_pending, int reconstructible) {
    if (!reconstructible || holds || gpu_owned || fence_pending || !last || frame <= last) return 0;
    return frame - last >= VKTL_KEEP_FRAMES;
}
static inline int vktl_order(uint64_t a, uint64_t b) { return a < b ? -1 : a > b; }
#endif
