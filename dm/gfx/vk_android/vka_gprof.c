// GPU time by step (DM_VK_GPUPROF=n, live): one frame in every n (n >= 1) gets a GPU timestamp after each full barrier the replay records (vka_barrier) and at the start of
// each submission and of each part of one (vka_exec.c chunk). Every full barrier waits for all earlier work, so the time between two timestamps is the GPU time of what was
// recorded between them: one render pass, or the clears / copies / uploads of one op. Once the frame's last submission is done the log gets one "gpu prof" block:
// the frame's GPU time by kind (passes, transfers, barriers with nothing between them) and the steps that cost most, each with the recording site of the barrier that
// ended it (file:line), the draws in it and the pass's attachments. Gaps between submissions and parts (the GPU waiting for recording) are left out.
// It costs a stall per profiled frame (timestamps), nothing when off (one cached switch read per submission)
#if defined(__ANDROID__)
#include "vka.h"
#include "vka_scene_profile.h"
#include <stdlib.h>
#include <string.h>

enum { NQ = 2048, DESC = 256, SHADERS = 64 };
typedef struct { const char *file; int line; int kind; uint64_t draws, passes, ops; uint64_t mesh_key; uint64_t gfx_key; uint8_t mesh_stage, gfx_block, gfx_draws, gfx_top; char desc[DESC]; } gp_mark;   // kind: 0 barrier, 1 submission start, 2 part start, 3 commit
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
static uint64_t g_first_vs, g_first_mesh, g_first_task;
static uint32_t g_first_units, g_first_instances, g_first_indirect;
static char g_compute[DESC];
static int g_compute_new;
// Timestamp 16 consecutive graphics draws inside the pass, on sampled frames
// ONLY, without changing resolution, blending, depth, shader, attachments or
// the normal draw sequence. The old GPU profiler knew only pass totals and
// could not distinguish a costly fragment shader from attachment load/store.
// Only the legacy 683x384 and handheld 640x360 / 960x540 scene passes are sampled; no extra GPU commands on 299/300
// frames. Attribution to a key requires >=12 of 16 draws using it.
enum { GFX_CHUNK = 16 };
static uint64_t g_gfx_keys[GFX_CHUNK];
static unsigned g_gfx_n;
static int g_gfx_enabled;
static void mark(VkCommandBuffer cb, int kind, const char *file, int line);
static void gfx_chunk_flush(void) {
    if (!g_gfx_enabled || !g_gfx_n || !vka_gp_active || !g_cb || g_n >= NQ - 16) {
        g_gfx_n = 0;
        return;
    }
    uint64_t top = 0; unsigned best = 0;
    for (unsigned i = 0; i < g_gfx_n; i++) {
        unsigned n = 0;
        for (unsigned j = 0; j < g_gfx_n; j++) n += g_gfx_keys[j] == g_gfx_keys[i];
        if (n > best) { best = n; top = g_gfx_keys[i]; }
    }
    mark(g_cb, 0, "GFX_CHUNK", 0);
    gp_mark *m = &g_m[g_n - 1];
    m->gfx_block = 1; m->gfx_key = top; m->gfx_draws = (uint8_t)g_gfx_n;
    m->gfx_top = (uint8_t)best;
    snprintf(m->desc, sizeof m->desc, "gfx chunk %u draws topfs=%016llx:%u",
             g_gfx_n, (unsigned long long)top, best);
    g_gfx_n = 0;
}
void vka_gp_gfx_flush(void) { if (vka_gp_active) gfx_chunk_flush(); }

void vka_gp_draw(uint64_t vertex, uint64_t fragment, uint64_t mesh, uint64_t task,
                 uint32_t units, uint32_t instances, int indirect) {
    if (!vka_gp_active) return;
    if (!g_pass_draws) {
        g_first_vs = vertex; g_first_mesh = mesh; g_first_task = task;
        g_first_units = units; g_first_instances = instances; g_first_indirect = indirect != 0;
    }
    g_pass_draws++;
    if (g_gfx_enabled && vka_gp_active && g_gfx_n < GFX_CHUNK) {
        g_gfx_keys[g_gfx_n++] = fragment;
        if (g_gfx_n == GFX_CHUNK) gfx_chunk_flush();
    }
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
    m->mesh_key = 0; m->mesh_stage = 0;
    m->gfx_key = 0; m->gfx_block = m->gfx_draws = m->gfx_top = 0;
    // profiler query slots are reused on later sampled frames
    uint64_t sk, di, pi; vka_draw_stats(&m->draws, &sk, &di, &pi); (void)sk; (void)di; (void)pi;
    extern uint64_t vka_n_rp; m->passes = vka_n_rp; uint64_t subs, rec; vka_exec_counts(&m->ops, &subs, &rec);
    if (file && !strcmp(file, "GFX_CHUNK")) {
        // Leave g_pass_new and the complete fragment histogram untouched:
        // the final pass-end timestamp still describes the ENTIRE pass.
        m->desc[0] = 0;
    } else if (g_pass_new) {
        snprintf(m->desc, DESC, "%s", g_pass);
        size_t used = strlen(m->desc);
        if (g_pass_draws && used < DESC) {
            used += (size_t)snprintf(m->desc + used, DESC - used, " | %u draws", g_pass_draws);
            if (g_pass_draws == 1 && used < DESC)
                used += (size_t)snprintf(m->desc + used, DESC - used,
                    " %s=%u inst=%u%s vs=%016llx mesh=%016llx task=%016llx",
                    g_first_mesh ? "mesh_groups" : "vertices_or_indices", g_first_units,
                    g_first_instances, g_first_indirect ? " indirect" : "",
                    (unsigned long long)g_first_vs, (unsigned long long)g_first_mesh,
                    (unsigned long long)g_first_task);
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
// Sparse, timestamped attribution of each converted mesh/task GPU dispatch.
// A marker is emitted AFTER the dispatch so its interval measures the shader
// that just ran. This call is made only with vka_gp_active (1/300 frames).
void vka_gp_mesh_shader(VkCommandBuffer cb, int task, uint64_t key) {
    if (!vka_gp_active || cb != g_cb || g_n >= NQ) return;
    mark(cb, 0, task ? "MEMU_TASK_SHADER" : "MEMU_MESH_SHADER", 0);
    gp_mark *m = &g_m[g_n - 1];
    m->mesh_key = key;
    m->mesh_stage = task ? 1 : 2;
}
void vka_gp_pass(const char *desc) {
    if (vka_gp_active) {
        // A draw may be outside the chosen scene pass: never carry its
        // timestamp group into the next render target.
        g_gfx_n = 0;
        g_gfx_enabled = !strcmp(DM_GAME_ID, "0400486024DEC000") &&
            VKA_ENV("DM_VK_OOT_GFX_CHUNKS", 1) &&
            vka_scene_profile_size(desc);
        snprintf(g_pass, DESC, "%s", desc);
        g_pass_new = 1; g_pass_draws = 0; g_nfs = 0; g_fs_over = 0;
    }
}
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
        if (g_m[i].gfx_block || g_m[i].passes > g_m[i - 1].passes) {
            pass += ms;
            if (g_m[i].passes > g_m[i - 1].passes) npass++;
        } else if (!strncmp(g_m[i].desc, "compute ", 8)) { compute += ms; ncompute++; } else if (g_m[i].ops > g_m[i - 1].ops || g_m[i].draws > g_m[i - 1].draws) xfer += ms; else bare += ms;
        if (g_m[i - 1].kind == 1) first += ms;
    }
    VLOG("gpu prof: frame %llu: %d timestamps, %.2f ms GPU: passes %.2f ms (%d), clears / copies / dispatches %.2f ms, steps with nothing recorded (barriers, uploads, writebacks) %.2f ms",
         (unsigned long long)g_frame, g_n, tot, pass, npass, xfer, bare);
    VLOG("gpu prof: identified compute %.2f ms (%d dispatch intervals), other transfers %.2f ms", compute, ncompute, xfer);
    // Ocarina foliage: identify what the converted task/mesh GPU actually
    // costs. Every mark is after the corresponding phase, so a step's
    // destination name identifies the producer that finished. No per-frame
    // aggregation on ordinary frames and no assumption that a CPU replay
    // duration equals GPU compute time.
    double mesh_phase_ms[7] = {0};
    unsigned mesh_phase_n[7] = {0};
    static const char *const mesh_phase[7] = {
        "MEMU_START", "MEMU_ADD", "MEMU_SETUP", "MEMU_TASK",
        "MEMU_DIST", "MEMU_MESH", "MEMU_END"
    };
    for (int j = 0; j < ns; j++) {
        const gp_mark *m = &g_m[s[j].i];
        // Per-dispatch timestamps now split the old MEMU_MESH batch
        // interval. Add them back into its total so old/new profiler
        // reports remain comparable; also print the hottest source keys.
        if (m->mesh_stage) {
            int phase = m->mesh_stage == 1 ? 3 : 5;
            mesh_phase_ms[phase] += s[j].ms;
            mesh_phase_n[phase]++;
            continue;
        }
        for (int k = 0; k < 7; k++) if (m->file && !strcmp(m->file, mesh_phase[k])) {
            mesh_phase_ms[k] += s[j].ms;
            mesh_phase_n[k]++;
            break;
        }
    }
    if (mesh_phase_n[0] || mesh_phase_n[1] || mesh_phase_n[2] ||
        mesh_phase_n[3] || mesh_phase_n[4] || mesh_phase_n[5] || mesh_phase_n[6])
        VLOG("gpu prof foliage phases: frame %llu mesh start %.3fms/%u, record upload %.3fms/%u, setup %.3fms/%u, task %.3fms/%u, distribution %.3fms/%u, mesh compute %.3fms/%u, final barrier %.3fms/%u; timestamp intervals on ONE sampled frame (not representative CPU replay or ordinary-frame FPS)",
             (unsigned long long)g_frame,
             mesh_phase_ms[0], mesh_phase_n[0], mesh_phase_ms[1], mesh_phase_n[1],
             mesh_phase_ms[2], mesh_phase_n[2], mesh_phase_ms[3], mesh_phase_n[3],
             mesh_phase_ms[4], mesh_phase_n[4], mesh_phase_ms[5], mesh_phase_n[5],
             mesh_phase_ms[6], mesh_phase_n[6]);
    // Exact source-key attribution: no need to recompile the 508 source
    // shaders or guess which foliage variant is the real GPU bottleneck.
    // Include the stage's timestamp as part of the dispatch interval.
    struct { uint64_t key; double ms; unsigned n; int task; } hot[128] = {0};
    unsigned nhot = 0;
    for (int k = 0; k < ns; k++) {
        const gp_mark *m = &g_m[s[k].i];
        if (!m->mesh_stage) continue;
        unsigned j = 0;
        while (j < nhot && (hot[j].key != m->mesh_key ||
                            hot[j].task != (m->mesh_stage == 1))) j++;
        if (j == nhot) {
            if (nhot == sizeof(hot)/sizeof(hot[0])) continue;
            hot[j].key = m->mesh_key;
            hot[j].task = m->mesh_stage == 1;
            nhot++;
        }
        hot[j].ms += s[k].ms;
        hot[j].n++;
    }
    // Only report the 12 most expensive keys on each sampled frame. Preserve
    // complete workload execution; the profiler only observes timestamps.
    unsigned char reported[128] = {0};
    for (unsigned rank = 0; rank < nhot && rank < 12; rank++) {
        int best = -1;
        for (unsigned j = 0; j < nhot; j++)
            if (!reported[j] && (best < 0 || hot[j].ms > hot[best].ms)) best = (int)j;
        if (best < 0) break;
        reported[best] = 1;
        VLOG("gpu prof foliage key: frame %llu %s %016llx: %.3fms across %u dispatches",
             (unsigned long long)g_frame, hot[best].task ? "task" : "mesh",
             (unsigned long long)hot[best].key, hot[best].ms, hot[best].n);
    }
    // Source-key estimate for the big scene passes. A mixed block is NOT
    // assigned to a shader; unknown GPU work is kept visible instead of
    // falsely treating all of the pass's time as fragment instruction cost.
    struct { uint64_t key; double ms; unsigned groups, draws; } gh[64] = {0};
    unsigned ngh = 0; double mixed_ms = 0, sampled_ms = 0;
    unsigned groups = 0, mixed_groups = 0;
    for (int i = 0; i < ns; i++) {
        const gp_mark *m = &g_m[s[i].i];
        if (!m->gfx_block) continue;
        groups++; sampled_ms += s[i].ms;
        if (m->gfx_top * 4 < m->gfx_draws * 3) {
            mixed_ms += s[i].ms; mixed_groups++;
            continue;
        }
        unsigned j = 0;
        while (j < ngh && gh[j].key != m->gfx_key) j++;
        if (j == ngh) {
            if (ngh == sizeof(gh) / sizeof(gh[0])) {
                mixed_ms += s[i].ms; mixed_groups++; continue;
            }
            gh[j].key = m->gfx_key; ngh++;
        }
        gh[j].ms += s[i].ms;
        gh[j].groups++;
        gh[j].draws += m->gfx_top;
    }
    if (groups) {
        VLOG("gpu prof scene chunks: frame %llu vegetation=%d %u groups %.3fms, mixed %u groups %.3fms; blocks measure graphics time including VS/depth/ROP, NOT fragment shader-only time",
             (unsigned long long)g_frame, VKA_ENV("DM_VK_VEGETATION", 1),
             groups, sampled_ms, mixed_groups, mixed_ms);
        unsigned char chosen[64] = {0};
        for (unsigned rank = 0; rank < ngh && rank < 12; rank++) {
            int best = -1;
            for (unsigned k = 0; k < ngh; k++)
                if (!chosen[k] && (best < 0 || gh[k].ms > gh[best].ms)) best = (int)k;
            if (best < 0) break;
            chosen[best] = 1;
            VLOG("gpu prof scene chunk key: frame %llu fs %016llx %.3fms across %u dominated blocks (%u matching draws); includes fixed graphics stages",
                 (unsigned long long)g_frame, (unsigned long long)gh[best].key,
                 gh[best].ms, gh[best].groups, gh[best].draws);
        }
    }
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
        // Sparse opt-in-by-game diagnostics only for the unresolved Ocarina
        // vegetation bottleneck: one timestamped frame in every 300.
        // No tracing or altered GPU commands in the other 299 frames.
        // Explicit DM_VK_GPUPROF=0 disables it entirely, if desired.
        // Compare graphics costs with foliage ON and OFF in the SAME
        // build. If profiling were enabled only with foliage on, the
        // baseline's big graphics passes would remain unmeasured.
        // The one sampled frame in 300 is diagnostic; all others record
        // the exact original GPU commands. DM_VK_GPUPROF=0 disables both.
        int every = VKA_ENV("DM_VK_GPUPROF",
            !strcmp(DM_GAME_ID, "0400486024DEC000") ? 300 : 0);
        if (every <= 0 || frame == g_frame || (g_last_frame && frame < g_last_frame + (uint64_t)every) || !init()) return;
        g_state = 1; g_frame = g_last_frame = frame; g_n = 0; vka_gp_active = 1; g_pass_new = 0; g_compute_new = 0; g_pass_draws = 0; g_nfs = 0; g_fs_over = 0;
        g_gfx_n = 0; g_gfx_enabled = 0;
        g_reset(cb, g_qp, 0, NQ);
    }
    if (g_state == 1) { g_cb = cb; mark(cb, 1, "submission", 0); }
}
void vka_gp_commit(VkCommandBuffer cb, uint64_t fence) { if (g_state == 1 && cb == g_cb) { mark(cb, 3, "commit", 0); g_fence = fence; } }
#endif
