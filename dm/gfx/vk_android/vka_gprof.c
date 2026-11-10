// GPU time by step (DM_VK_GPUPROF=n, live): one frame in every n (n >= 1) gets a GPU timestamp after each full barrier the replay records (vka_barrier) and at the start of
// each submission and of each part of one (vka_exec.c chunk). Every full barrier waits for all earlier work, so the time between two timestamps is the GPU time of what was
// recorded between them: one render pass, or the clears / copies / uploads of one op. Once the frame's last submission is done the log gets one "gpu prof" block:
// the frame's GPU time by kind (passes, transfers, barriers with nothing between them) and the steps that cost most, each with the recording site of the barrier that
// ended it (file:line), the draws in it and the pass's attachments. Gaps between submissions and parts (the GPU waiting for recording) are left out.
// It costs a stall per profiled frame (timestamps), nothing when off (one cached switch read per submission)
#if defined(__ANDROID__)
#include "vka.h"
#include <stdlib.h>
#include <string.h>

enum { NQ = 2048, DESC = 256, SHADERS = 64 };
typedef struct { const char *file; int line; int kind; uint64_t draws, passes, ops; char desc[DESC]; } gp_mark;   // kind: 0 barrier, 1 submission start, 2 part start, 3 commit
static gp_mark g_m[NQ]; static int g_n;
static VkQueryPool g_qp; static int g_ok = -1; static double g_tick_ns;
static PFN_vkCmdWriteTimestamp g_write; static PFN_vkCmdResetQueryPool g_reset; static PFN_vkGetQueryPoolResults g_get;
static int g_state;                     // 0 idle, 1 recording the profiled frame, 2 waiting for its last fence
static uint64_t g_frame, g_last_frame, g_fence; static VkCommandBuffer g_cb;
static char g_pass[DESC]; static int g_pass_new;   // the last pass opened (vka_gp_pass), taken by the next mark
static uint64_t g_sub_frame; static int g_sub_frame_set;
// Optional attribution for the currently timed pass; ordinary frames do no accounting.
static struct { uint64_t key; unsigned count; } g_fs[SHADERS];
static unsigned g_pass_draws, g_fs_over;
static int g_nfs;
static uint64_t g_first_vs, g_first_mesh;
static char g_compute[DESC];
static int g_compute_new;

void vka_gp_draw(uint64_t vertex, uint64_t fragment, uint64_t mesh) {
    if (!vka_gp_active) return;
    if (!g_pass_draws) { g_first_vs = vertex; g_first_mesh = mesh; }
    g_pass_draws++;
    for (int i = 0; i < g_nfs; i++) if (g_fs[i].key == fragment) { g_fs[i].count++; return; }
    if (g_nfs < SHADERS) { g_fs[g_nfs].key = fragment; g_fs[g_nfs++].count = 1; }
    else g_fs_over++;
}
void vka_gp_compute(uint64_t key, uint32_t x, uint32_t y, uint32_t z, int replaced) {
    if (!vka_gp_active) return;
    snprintf(g_compute, sizeof g_compute, "compute %016llx grid %ux%ux%u%s",
        (unsigned long long)key, x, y, z, replaced ? " NDSR-replaced" : "");
    g_compute_new = 1;
}
int vka_gp_active;                      // marks are taken (read by vka_barrier)

void vka_gp_sub_frame(uint64_t f) { g_sub_frame = f; g_sub_frame_set = 1; }   // the replay worker: the game frame of the submission it replays next
static int init(void) {
    if (g_ok >= 0) return g_ok;
    g_ok = 0;
    g_write = (PFN_vkCmdWriteTimestamp)vk.vkGetDeviceProcAddr(V.dev, "vkCmdWriteTimestamp"); g_reset = (PFN_vkCmdResetQueryPool)vk.vkGetDeviceProcAddr(V.dev, "vkCmdResetQueryPool");
    g_get = (PFN_vkGetQueryPoolResults)vk.vkGetDeviceProcAddr(V.dev, "vkGetQueryPoolResults");
    PFN_vkCreateQueryPool create = (PFN_vkCreateQueryPool)vk.vkGetDeviceProcAddr(V.dev, "vkCreateQueryPool");
    VkQueryPoolCreateInfo ci = {VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO, .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = NQ};
    if (!g_write || !g_reset || !g_get || !create || create(V.dev, &ci, NULL, &g_qp) || V.props.limits.timestampPeriod <= 0) { VRED("gpu prof: no timestamp query pool"); return 0; }
    g_tick_ns = V.props.limits.timestampPeriod; g_ok = 1;
    return 1;
}
static void mark(VkCommandBuffer cb, int kind, const char *file, int line) {
    if (g_n >= NQ) return;
    gp_mark *m = &g_m[g_n]; m->file = file; m->line = line; m->kind = kind;
    uint64_t sk, di, pi; vka_draw_stats(&m->draws, &sk, &di, &pi); (void)sk; (void)di; (void)pi;
    extern uint64_t vka_n_rp; m->passes = vka_n_rp; uint64_t subs, rec; vka_exec_counts(&m->ops, &subs, &rec);
    if (g_pass_new) {
        snprintf(m->desc, DESC, "%s", g_pass);
        size_t used = strlen(m->desc);
        if (g_pass_draws && used < DESC) {
            used += (size_t)snprintf(m->desc + used, DESC - used, " | %u draws", g_pass_draws);
            if (g_pass_draws == 1 && used < DESC)
                used += (size_t)snprintf(m->desc + used, DESC - used, " vs=%016llx mesh=%016llx",
                    (unsigned long long)g_first_vs, (unsigned long long)g_first_mesh);
            unsigned char picked[SHADERS] = {0};
            for (int rank = 0; rank < 3 && used < DESC; rank++) {
                int best = -1;
                for (int j = 0; j < g_nfs; j++)
                    if (!picked[j] && (best < 0 || g_fs[j].count > g_fs[best].count)) best = j;
                if (best < 0) break;
                picked[best] = 1;
                used += (size_t)snprintf(m->desc + used, DESC - used, " fs=%016llx:%u",
                    (unsigned long long)g_fs[best].key, g_fs[best].count);
            }
            if (g_fs_over && used < DESC) snprintf(m->desc + used, DESC - used, " overflow=%u", g_fs_over);
        }
        g_pass_new = 0; g_pass_draws = 0; g_nfs = 0; g_fs_over = 0; g_compute_new = 0;
    } else if (g_compute_new) {
        snprintf(m->desc, DESC, "%s", g_compute);
        g_compute_new = 0;
    } else m->desc[0] = 0;
    vka_enc_sync();
    g_write(cb, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, g_qp, (uint32_t)g_n);
    g_n++;
}
void vka_gp_mark(VkCommandBuffer cb, const char *file, int line) { if (cb == g_cb) mark(cb, 0, file, line); }
void vka_gp_pass(const char *desc) { if (vka_gp_active) { snprintf(g_pass, DESC, "%s", desc); g_pass_new = 1; g_pass_draws = 0; g_nfs = 0; g_fs_over = 0; } }
void vka_gp_part(VkCommandBuffer cb) { if (!vka_gp_active) return; g_cb = cb; mark(cb, 2, "part", 0); }

typedef struct { int i; double ms; } step;
static int by_ms(const void *a, const void *b) { double d = ((const step *)b)->ms - ((const step *)a)->ms; return d > 0 ? 1 : d < 0 ? -1 : 0; }
static void report(void) {
    static uint64_t t[NQ];
    if (g_get(V.dev, g_qp, 0, (uint32_t)g_n, sizeof t, t, 8, VK_QUERY_RESULT_64_BIT)) { VLOG("gpu prof: frame %llu: results not ready", (unsigned long long)g_frame); return; }
    static step s[NQ]; int ns = 0; double tot = 0, pass = 0, xfer = 0, bare = 0, first = 0, compute = 0; int npass = 0, ncompute = 0;
    for (int i = 1; i < g_n; i++) {
        if (g_m[i].kind == 1 || g_m[i].kind == 2) continue;   // the gap before a submission or part: the GPU waited for recording
        double ms = t[i] > t[i - 1] ? (t[i] - t[i - 1]) * g_tick_ns / 1e6 : 0;
        tot += ms; s[ns++] = (step){i, ms};
        if (g_m[i].passes > g_m[i - 1].passes) { pass += ms; npass++; } else if (!strncmp(g_m[i].desc, "compute ", 8)) { compute += ms; ncompute++; } else if (g_m[i].ops > g_m[i - 1].ops || g_m[i].draws > g_m[i - 1].draws) xfer += ms; else bare += ms;
        if (g_m[i - 1].kind == 1) first += ms;
    }
    VLOG("gpu prof: frame %llu: %d timestamps, %.2f ms GPU: passes %.2f ms (%d), clears / copies / dispatches %.2f ms, steps with nothing recorded (barriers, uploads, writebacks) %.2f ms",
         (unsigned long long)g_frame, g_n, tot, pass, npass, xfer, bare);
    VLOG("gpu prof: identified compute %.2f ms (%d dispatch intervals), other transfers %.2f ms", compute, ncompute, xfer);
    if (VKA_ENV("DM_VK_GPUPROF_LIST", 0))   // every step in order
        for (int k = 0; k < ns; k++) { const gp_mark *a = &g_m[s[k].i - 1], *b = &g_m[s[k].i];
            VLOG("gpu prof: step #%d %.3f ms: %s:%d, %llu draws, %llu ops%s%s", s[k].i, s[k].ms, b->file, b->line, (unsigned long long)(b->draws - a->draws),
                 (unsigned long long)(b->ops - a->ops), b->desc[0] ? "; pass " : "", b->desc); }
    qsort(s, (size_t)ns, sizeof *s, by_ms);
    for (int k = 0; k < ns && k < 16; k++) {
        const gp_mark *a = &g_m[s[k].i - 1], *b = &g_m[s[k].i];
        VLOG("gpu prof:  #%d %.3f ms: %s:%d, %llu draws, %llu passes, %llu ops%s%s", s[k].i, s[k].ms, b->file, b->line, (unsigned long long)(b->draws - a->draws),
             (unsigned long long)(b->passes - a->passes), (unsigned long long)(b->ops - a->ops), b->desc[0] ? "; pass " : "", b->desc);
    }
    // by barrier site: count and time
    struct { const char *f; int l; int n; double ms; } site[64]; int nsite = 0;
    for (int k = 0; k < ns; k++) { const gp_mark *b = &g_m[s[k].i]; int j = 0;
        while (j < nsite && !(site[j].l == b->line && site[j].f == b->file)) j++;
        if (j == nsite) { if (nsite == 64) continue; site[nsite++] = (typeof(site[0])){b->file, b->line, 0, 0}; }
        site[j].n++; site[j].ms += s[k].ms; }
    char line[1200]; size_t ln = 0; line[0] = 0;
    for (int j = 0; j < nsite && ln < sizeof line; j++) ln += (size_t)snprintf(line + ln, sizeof line - ln, " %s:%d %dx %.2fms;", site[j].f, site[j].l, site[j].n, site[j].ms);
    VLOG("gpu prof: by site:%s", line);
}
// mtl_sub_begin, after the command buffer begins: arms the profile at a new frame, reports a finished one
void vka_gp_sub_begin(VkCommandBuffer cb, uint64_t frame) {
    if (g_sub_frame_set) frame = g_sub_frame;
    if (g_state == 2 && vka_done() >= g_fence) { report(); g_state = 0; }
    if (g_state == 1 && frame != g_frame) { g_state = 2; vka_gp_active = 0; g_cb = VK_NULL_HANDLE; }
    if (g_state == 2 && vka_done() >= g_fence) { report(); g_state = 0; }
    if (g_state == 0) {
        int every = VKA_ENV("DM_VK_GPUPROF", 0);
        if (every <= 0 || frame == g_frame || (g_last_frame && frame < g_last_frame + (uint64_t)every) || !init()) return;
        g_state = 1; g_frame = g_last_frame = frame; g_n = 0; vka_gp_active = 1; g_pass_new = 0; g_compute_new = 0; g_pass_draws = 0; g_nfs = 0; g_fs_over = 0;
        g_reset(cb, g_qp, 0, NQ);
    }
    if (g_state == 1) { g_cb = cb; mark(cb, 1, "submission", 0); }
}
void vka_gp_commit(VkCommandBuffer cb, uint64_t fence) { if (g_state == 1 && cb == g_cb) { mark(cb, 3, "commit", 0); g_fence = fence; } }
#endif
