// Run the production nn::codec implementation with delayed platform output.
// No compressed game data or Android MediaCodec service is needed. In
// particular, the client makes NO decoder calls while waiting for its event.
#define _GNU_SOURCE 1
#include "../hle.h"
#undef HLE_FORCE
#define HLE_FORCE(mangled, why, ret, cname, ...) static ret cname(__VA_ARGS__)
#include "../hle_codec_video.c"
#include <assert.h>
#include <stdatomic.h>
#include <unistd.h>

__thread _Atomic int dm_host_work;
uint64_t now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec; }
static pthread_mutex_t event_mu = PTHREAD_MUTEX_INITIALIZER;
static struct { void *addr; int set; } events[8];
static int event_slot(void *e) { for (int i = 0; i < 8; i++) if (events[i].addr == e) return i; for (int i = 0; i < 8; i++) if (!events[i].addr) { events[i].addr = e; return i; } abort(); }
void hle_bind_system_event(void *e, int clear) { (void)clear; pthread_mutex_lock(&event_mu); events[event_slot(e)].set = 0; pthread_mutex_unlock(&event_mu); }
void hle_signal_system_event(void *e) { pthread_mutex_lock(&event_mu); events[event_slot(e)].set = 1; pthread_mutex_unlock(&event_mu); }
void hle_clear_system_event(void *e) { pthread_mutex_lock(&event_mu); events[event_slot(e)].set = 0; pthread_mutex_unlock(&event_mu); }
static int event_set(void *e) { pthread_mutex_lock(&event_mu); int r = events[event_slot(e)].set; pthread_mutex_unlock(&event_mu); return r; }
static void destroy_event(void *e) { pthread_mutex_lock(&event_mu); int i = event_slot(e); events[i].addr = NULL; events[i].set = 0; pthread_mutex_unlock(&event_mu); }
void *guest_sym(const char *s) { return !strcmp(s, "_ZN2nn2os18DestroySystemEventEPNS0_15SystemEventTypeE") ? (void *)destroy_event : NULL; }

// These cases exercise only the platform AV1/H.264 path. Keep the production
// libvpx image allocator/conversion storage, but reject any accidental call
// into VP8/VP9 decoding instead of depending on a system decoder library.
vpx_codec_iface_t *vpx_codec_vp8_dx(void) { abort(); }
vpx_codec_iface_t *vpx_codec_vp9_dx(void) { abort(); }
vpx_codec_err_t vpx_codec_dec_init_ver(vpx_codec_ctx_t *ctx, vpx_codec_iface_t *iface,
                                     const vpx_codec_dec_cfg_t *cfg, vpx_codec_flags_t flags, int version) {
    (void)ctx; (void)iface; (void)cfg; (void)flags; (void)version; abort();
}
vpx_codec_err_t vpx_codec_destroy(vpx_codec_ctx_t *ctx) { (void)ctx; abort(); }
vpx_codec_err_t vpx_codec_decode(vpx_codec_ctx_t *ctx, const uint8_t *data, unsigned int size, void *user, long deadline) {
    (void)ctx; (void)data; (void)size; (void)user; (void)deadline; abort();
}
vpx_image_t *vpx_codec_get_frame(vpx_codec_ctx_t *ctx, vpx_codec_iter_t *iter) { (void)ctx; (void)iter; abort(); }
const char *vpx_codec_error(const vpx_codec_ctx_t *ctx) { (void)ctx; abort(); }
const char *vpx_codec_error_detail(const vpx_codec_ctx_t *ctx) { (void)ctx; abort(); }

// A platform decoder that finishes well AFTER Submit has returned.
struct mavc { uint64_t due; int64_t pts; int pending; };
mavc *mavc_new(void) { return calloc(1, sizeof(mavc)); }
mavc *mavc_new_av1(int w, int h) { (void)w; (void)h; return mavc_new(); }
void mavc_free(mavc *a) { free(a); }
void mavc_drop(mavc *a) { a->pending = 0; }
void mavc_param_sets(mavc *a, const uint8_t *p, size_t n) { (void)a; (void)p; (void)n; }
int mavc_decode(mavc *a, const uint8_t *p, int n, int64_t pts) { (void)p; (void)n; a->pts = pts; a->due = now_ns() + 40000000; a->pending = 1; return 0; }
int mavc_take(mavc *a, int flush, uint8_t *dst, int w, int h, int64_t *pts) {
    (void)flush;
    if (!a->pending || now_ns() < a->due) return 0;
    memset(dst, 81, (size_t)w * h); memset(dst + w * h, 128, (size_t)w * h / 2);
    *pts = a->pts; a->pending = 0; return 1;
}

static void await_event(void *e) {
    uint64_t limit = now_ns() + 1000000000;
    while (!event_set(e) && now_ns() < limit) usleep(1000);
    assert(event_set(e) && "late platform output never signalled NativeSync event");
}
int main(void) {
    uint8_t decoder[0x400] = {0}, pool[0x40] = {0}, point[0x80] = {0}, memory[16 * 16 * 4];
    setenv("DM_MOVIE_RATE", "0", 1);
    for (int round = 0; round < 20; round++) {
        int codec = round & 1 ? CV_H264 : CV_AV1;
        g_cv_clk = codec == CV_AV1;   // cover AV1's pre-Acquire policy and H.264 without clock dropping
        assert(!cv_dec_init(decoder, codec, 16, 16, 3, 3, NULL, 0));
        cv_pref pref = h_cv_pref(16, 16, 3, 0);
        assert(!h_cv_pool(pool, memory, sizeof memory, &pref, 1, 0));
        assert(!cv_dec_reg(decoder, 0, pool, 0));
        uint32_t idx; cv_sync sync; uint64_t id;
        assert(!cv_dec_acq(&idx, &sync, decoder));
        cv_dec_rel(decoder, idx, sync);
        assert(!cv_dec_acq(&idx, &sync, decoder));
        assert(!h_spt_create(point));
        assert(!h_spt_request(point, &sync));
        const uint8_t packet = 1;
        assert(!cv_dec_submit(&id, decoder, &packet, 1, 123000, false));
        assert(!event_set(point));
        await_event(point);   // no Acquire, Release, Submit or sync poll here
        assert(sync_reached(&sync));
        uint16_t w, h, cw, ch; int64_t ts; bool eos;
        assert(!cv_dec_props(&w, &h, &cw, &ch, &ts, &eos, decoder, idx) && ts == 123000 && !eos);
        // Also receive while the output remains queued BEFORE Acquire.
        cv_dec_rel(decoder, idx, sync);
        sync.gen++;
        assert(!h_spt_request(point, &sync));
        assert(!cv_dec_submit(&id, decoder, &packet, 1, 456000, false));
        await_event(point);
        assert(!cv_dec_acq(&idx, &sync, decoder));
        assert(!cv_dec_props(&w, &h, &cw, &ch, &ts, &eos, decoder, idx) && ts == 456000);
        // Flush discards an unfinished packet; a fresh packet still wakes us.
        cv_dec_rel(decoder, idx, sync);
        assert(!cv_dec_acq(&idx, &sync, decoder));
        assert(!h_spt_request(point, &sync));
        assert(!cv_dec_submit(&id, decoder, &packet, 1, 789000, false));
        assert(!cv_dec_reset(decoder));
        usleep(60000); assert(!event_set(point));
        assert(!cv_dec_submit(&id, decoder, &packet, 1, 999000, false));
        await_event(point);
        // Finalize joins even with a delayed packet still pending.
        cv_dec_rel(decoder, idx, sync);
        assert(!cv_dec_submit(&id, decoder, &packet, 1, 1110000, false));
        h_spt_cancel(point); h_spt_destroy(point);
        assert(!cv_dec_fin(decoder));
        h_cv_poolfin(pool);
    }
    puts("t_android_codec_async: 20 delayed-output, pre-Acquire, flush and finalize cycles passed");
    return 0;
}
