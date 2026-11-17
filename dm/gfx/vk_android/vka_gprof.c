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

// The heavy scene regularly exhausted2048 marks before its final passes.
// Only one frame in300 is sampled; ordinary frames still emit zero marks.
enum { NQ = 8192, DESC = 256, SHADERS = 64 };
typedef struct {
    uint64_t scissor_sum, direct_triangles;
    uint32_t draws, depth_test, depth_write, stencil, no_color, no_cull, indirect;
    uint16_t load_color, store_color, load_depth, store_depth, samples;
    int pipeline_query; // exact pipeline query index, -1 when unavailable
} scene_observation;
typedef struct { const char *file; int line; int kind; uint64_t draws, passes, ops; uint64_t mesh_key; uint64_t gfx_key; uint8_t mesh_stage, gfx_block, gfx_draws, gfx_top; uint16_t gfx_pass_id; uint32_t gfx_draw_id; scene_observation scene; char desc[DESC]; } gp_mark;   // kind: 0 barrier, 1 submission start, 2 part start, 3 commit
static gp_mark g_m[NQ]; static int g_n;
static VkQueryPool g_qp; static int g_ok = -1; static double g_tick_ns;
// Not an overdraw approximation: a real Vulkan pipeline statistics query.
// Enabled only on ONE frame out of every N (and only for 1280x720).
enum { NPIPE_Q = 96, NSTATS = 4 };
static VkQueryPool g_pipe_qp;
static uint32_t g_pipe_count;
static int g_pipe_active = -1, g_pass_1280;

static PFN_vkCmdWriteTimestamp g_write; static PFN_vkCmdResetQueryPool g_reset; static PFN_vkGetQueryPoolResults g_get;
static int g_state;                     // 0 idle, 1 recording the profiled frame, 2 waiting for its last fence
static uint64_t g_frame, g_last_frame, g_fence; static VkCommandBuffer g_cb;
static char g_pass[DESC]; static int g_pass_new;   // the last pass opened (vka_gp_pass), taken by the next mark
static uint64_t g_sub_frame; static int g_sub_frame_set;
// Optional attribution for the currently timed pass; ordinary frames do no accounting.
static struct { uint64_t key; unsigned count; } g_fs[SHADERS];
static unsigned g_pass_draws, g_fs_over;
static scene_observation g_scene;  // one sampled pass only; NEVER actual GPU pixel/DRAM counters
static uint32_t g_seen_1280; // detect a missing report rather than silently reusing a broken selector
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
// Opt-in 1280x720 draw-level timing ONLY on the frame already selected by
// the sparse GPU profiler. No changes to normal-frame command buffers.
// Unlike 16-draw chunks, fine marks distinguish a long-latency draw from
// adjacent shaders and expose its exact vertex/fragment pairing.
static int g_gfx_fine;
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
                 uint32_t units, uint32_t instances, int indirect,
                 uint32_t scissor_pixels, uint32_t draw_flags, uint64_t triangles) {
    if (!vka_gp_active) return;
    if (!g_pass_draws) {
        g_first_vs = vertex; g_first_mesh = mesh; g_first_task = task;
        g_first_units = units; g_first_instances = instances;
        // 0 = direct, 1 = conventional indirect, 2 = MEMU's generated
        // GPU indirect draw (guest mesh record count is NOT vertex count).
        g_first_indirect = (uint32_t)indirect;
    }
    g_pass_draws++;
    g_scene.scissor_sum += scissor_pixels;
    g_scene.direct_triangles += triangles;
    g_scene.depth_test += (draw_flags & 1) != 0;
    g_scene.depth_write += (draw_flags & 2) != 0;
    g_scene.stencil += (draw_flags & 4) != 0;
    g_scene.no_color += (draw_flags & 8) != 0;
    g_scene.no_cull += (draw_flags & 16) != 0;
    g_scene.indirect += indirect != 0;
    if (g_gfx_enabled && vka_gp_active && g_gfx_n < GFX_CHUNK) {
        g_gfx_keys[g_gfx_n++] = fragment;
        if (g_gfx_n == GFX_CHUNK) gfx_chunk_flush();
    }
    if (g_gfx_fine && vka_gp_active && g_cb && g_n < NQ - 16) {
        // Called directly AFTER the original vkCmdDraw* command, inside
        // its render pass, just like the existing 16-draw timestamp marks.
        // This is observational only: no shader, target, state, draw,
        // memory barrier, or submission is added or removed.
        mark(g_cb, 0, "GFX_DRAW", 0);
        gp_mark *m = &g_m[g_n - 1];
        m->gfx_block = 2;  // timed individual draw; not a 16-draw chunk
        m->gfx_pass_id = (uint16_t)g_seen_1280;
        m->gfx_draw_id = g_pass_draws;
        m->gfx_key = fragment;
        snprintf(m->desc, sizeof m->desc,
            "fine 1280 pass=%u draw=%u vs=%016llx fs=%016llx mesh=%016llx task=%016llx units=%u inst=%u indirect=%d",
            (unsigned)m->gfx_pass_id, m->gfx_draw_id,
            (unsigned long long)vertex, (unsigned long long)fragment,
            (unsigned long long)mesh, (unsigned long long)task,
            units, instances, indirect);
    }
    for (int i = 0; i < g_nfs; i++ ) if (g_fs[i].key == fragment) { g_fs[i].count++; return; }
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
    g_tick_ns = V.props.limits.timestampPeriod;
    if (V.pipeline_query && VKA_ENV("DM_VK_SCENE_PASS_DIAG", 0) >= 2 &&
        vk.vkCmdBeginQuery && vk.vkCmdEndQuery) {
        VkQueryPoolCreateInfo q = {
            VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO, .queryType = VK_QUERY_TYPE_PIPELINE_STATISTICS,
            .queryCount = NPIPE_Q,
            .pipelineStatistics =
                VK_QUERY_PIPELINE_STATISTIC_INPUT_ASSEMBLY_PRIMITIVES_BIT |
                VK_QUERY_PIPELINE_STATISTIC_VERTEX_SHADER_INVOCATIONS_BIT |
                VK_QUERY_PIPELINE_STATISTIC_CLIPPING_PRIMITIVES_BIT |
                VK_QUERY_PIPELINE_STATISTIC_FRAGMENT_SHADER_INVOCATIONS_BIT
        };
        VkResult r = create(V.dev, &q, NULL, &g_pipe_qp);
        if (r) VLOG("scene pass pipeline statistics query unavailable: %d; timestamp profiling retained", r);
        else VLOG("scene pass pipeline statistics query enabled: up to %u real 1280x720 Vulkan render passes per sampled frame; zero impact on non-profiled frames", NPIPE_Q);
    } else if (VKA_ENV("DM_VK_SCENE_PASS_DIAG", 0) >= 2)
        VLOG("scene pass pipeline statistics unavailable: device does not support pipelineStatisticsQuery; using raster proxies only");
    g_ok = 1;
    return 1;
}
static void mark(VkCommandBuffer cb, int kind, const char *file, int line) {
    if (g_n >= NQ) return;
    gp_mark *m = &g_m[g_n]; m->file = file; m->line = line; m->kind = kind;
    m->mesh_key = 0; m->mesh_stage = 0;
    m->gfx_key = 0; m->gfx_block = m->gfx_draws = m->gfx_top = 0;
    m->gfx_pass_id = 0; m->gfx_draw_id = 0;
    memset(&m->scene, 0, sizeof m->scene);
    // profiler query slots are reused on later sampled frames
    uint64_t sk, di, pi; vka_draw_stats(&m->draws, &sk, &di, &pi); (void)sk; (void)di; (void)pi;
    extern uint64_t vka_n_rp; m->passes = vka_n_rp; uint64_t subs, rec; vka_exec_counts(&m->ops, &subs, &rec);
    if (file && !strcmp(file, "GFX_CHUNK")) {
        // A chunk is a timestamp sub-interval, not the whole render pass.
        m->desc[0] = 0;
    } else if (file && !strcmp(file, "GFX_BEGIN")) {
        // Timing the pass start must not consume its final-pass histogram.
        m->desc[0] = 0;
    } else if (file && !strcmp(file, "GFX_DRAW")) {
        // Leave g_pass_new and the complete fragment histogram untouched:
        // the final pass-end timestamp still describes the ENTIRE pass.
        m->desc[0] = 0;
    } else if (g_pass_new) {
        g_scene.draws = g_pass_draws;
        m->scene = g_scene;
        snprintf(m->desc, DESC, "%s", g_pass);
        size_t used = strlen(m->desc);
        if (g_pass_draws && used < DESC) {
            used += (size_t)snprintf(m->desc + used, DESC - used, " | %u draws", g_pass_draws);
            if (g_pass_draws == 1 && used < DESC)
                used += (size_t)snprintf(m->desc + used, DESC - used,
                    " %s=%u inst=%u%s vs=%016llx mesh=%016llx task=%016llx",
                    g_first_indirect == 2 ? "guest_mesh_record_count" :
                    g_first_mesh ? "mesh_groups" : "vertices_or_indices", g_first_units,
                    g_first_instances,
                    g_first_indirect == 2 ? " GPU-generated-indirect-count-UNKNOWN" :
                    g_first_indirect ? " indirect" : "",
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
void vka_gp_pass_io(unsigned load_color, unsigned store_color,
                    unsigned load_depth, unsigned store_depth, unsigned samples) {
    if (!vka_gp_active) return;
    g_scene.load_color = (uint16_t)load_color;
    g_scene.store_color = (uint16_t)store_color;
    g_scene.load_depth = (uint16_t)load_depth;
    g_scene.store_depth = (uint16_t)store_depth;
    g_scene.samples = (uint16_t)samples;
}
void vka_gp_pass_begin_query(VkCommandBuffer cb) {
    if (!vka_gp_active || !g_pipe_qp || !g_pass_1280 ||
        g_pipe_count >= NPIPE_Q || g_pipe_active >= 0 || cb != g_cb) return;
    uint32_t id = g_pipe_count++;
    vk.vkCmdBeginQuery(cb, g_pipe_qp, id, 0);
    g_pipe_active = (int)id;
}
void vka_gp_pass_end_query(VkCommandBuffer cb) {
    if (g_pipe_active < 0 || cb != g_cb) return;
    vk.vkCmdEndQuery(cb, g_pipe_qp, (uint32_t)g_pipe_active);
    g_scene.pipeline_query = g_pipe_active;
    g_pipe_active = -1;
}
void vka_gp_pass(const char *desc) {
    if (vka_gp_active) {
        memset(&g_scene, 0, sizeof g_scene);
        g_scene.pipeline_query = -1;
        // "1280x720x1" is exactly 10 bytes; the next character of the
        // actual description is a SPACE before "c0:122 d:126", not NUL.
        // Matching 11 bytes accidentally excluded every useful scene pass.
        g_pass_1280 = vka_scene_profile_1280(desc);
        if (g_pass_1280) g_seen_1280++;
        // A draw may be outside the chosen scene pass: never carry its
        // timestamp group into the next render target.
        g_gfx_n = 0;
        g_gfx_fine = !strcmp(DM_GAME_ID, "0400486024DEC000") &&
            VKA_ENV("DM_VK_OOT_GFX_FINE", VKA_ENV("DM_VK_SCENE_PASS_DIAG", 0) >= 2) != 0 && g_pass_1280;
        // The two timestamp granularities must be mutually exclusive.
        // Every non-profiled frame still records ZERO of either kind.
        g_gfx_enabled = !strcmp(DM_GAME_ID, "0400486024DEC000") &&
            VKA_ENV("DM_VK_OOT_GFX_CHUNKS", 1) &&
            vka_scene_profile_size(desc);
        if (g_gfx_fine) g_gfx_enabled = 0;
        snprintf(g_pass, DESC, "%s", desc);
        g_pass_new = 1; g_pass_draws = 0; g_nfs = 0; g_fs_over = 0;
    }
}
void vka_gp_fine_pass_begin(VkCommandBuffer cb) {
    if (!vka_gp_active || !g_gfx_fine || !cb || g_n >= NQ - 16) return;
    // Timestamp AFTER vkCmdBeginRendering and pipeline-query begin, BEFORE
    // any draw. Separates initial pass/load/previous dependency interval from
    // per-draw intervals. Do not confuse this interval with pure attachment
    // DRAM traffic: it can include GPU work before the render pass.
    mark(cb, 0, "GFX_BEGIN", 0);
    gp_mark *m = &g_m[g_n - 1];
    m->gfx_block = 3; // pass-start interval, not a draw or mixed 16-draw block
    m->gfx_pass_id = (uint16_t)g_seen_1280;
    snprintf(m->desc, sizeof m->desc,
        "fine 1280 pass=%u BEGIN (pass/load/dependencies before first draw)",
        (unsigned)m->gfx_pass_id);
}
void vka_gp_part(VkCommandBuffer cb) { if (!vka_gp_active) return; g_cb = cb; mark(cb, 2, "part", 0); }

typedef struct { int i; double ms; } step;
static int by_ms(const void *a, const void *b) { double d = ((const step *)b)->ms - ((const step *)a)->ms; return d > 0 ? 1 : d < 0 ? -1 : 0; }
static void report(void) {
    static uint64_t t[NQ];
    if (g_get(V.dev, g_qp, 0, (uint32_t)g_n, sizeof t, t, 8, VK_QUERY_RESULT_64_BIT)) { VLOG("gpu prof: frame %llu: results not ready", (unsigned long long)g_frame); return; }
    uint64_t pipe_data[NPIPE_Q * NSTATS] = {0};
    int have_pipe_data = g_pipe_qp && g_pipe_count &&
        !g_get(V.dev, g_pipe_qp, 0, g_pipe_count,
               (size_t)g_pipe_count * NSTATS * sizeof(uint64_t),
               pipe_data, NSTATS * sizeof(uint64_t), VK_QUERY_RESULT_64_BIT);
    static step s[NQ]; int ns = 0; double tot = 0, pass = 0, xfer = 0, bare = 0, first = 0, compute = 0; int npass = 0, ncompute = 0;
    static double elapsed[NQ]; // index by GPU timestamp, before sorting steps
    // Submission/part markers are skipped in this report. Reusing old
    // values from a previous sampled frame would invent graphics time.
    memset(elapsed, 0, sizeof elapsed);
    for (int i = 1; i < g_n; i++) {
        if (g_m[i].kind == 1 || g_m[i].kind == 2) continue;   // the gap before a submission or part: the GPU waited for recording
        double ms = t[i] > t[i - 1] ? (t[i] - t[i - 1]) * g_tick_ns / 1e6 : 0;
        elapsed[i] = ms;
        tot += ms; s[ns++] = (step){i, ms};
        if (g_m[i].gfx_block || g_m[i].passes > g_m[i - 1].passes) {
            pass += ms;
            if (g_m[i].passes > g_m[i - 1].passes) npass++;
        } else if (!strncmp(g_m[i].desc, "compute ", 8)) { compute += ms; ncompute++; } else if (g_m[i].ops > g_m[i - 1].ops || g_m[i].draws > g_m[i - 1].draws) xfer += ms; else bare += ms;
        if (g_m[i - 1].kind == 1) first += ms;
    }
    if (g_n >= NQ) VLOG("gpu prof INCOMPLETE: timestamp capacity %u reached; this is a partial frame, never the complete GPU frame cost", (unsigned)NQ);
    VLOG("gpu prof: frame %llu: %d timestamps, %.2f ms GPU: passes %.2f ms (%d), clears / copies / dispatches %.2f ms, steps with nothing recorded (barriers, uploads, writebacks) %.2f ms",
         (unsigned long long)g_frame, g_n, tot, pass, npass, xfer, bare);
    VLOG("gpu prof: identified compute %.2f ms (%d dispatch intervals), other transfers %.2f ms", compute, ncompute, xfer);
    // Summarize existing GPU timestamp intervals by compute shader key.
    // The old top-16 log hid the bulk of the ~4.5ms scene compute work.
    // NO additional timestamp commands or GPU/normal-frame instrumentation.
    if (ncompute && !strcmp(DM_GAME_ID, "0400486024DEC000")) {
        struct { uint64_t key; double ms; unsigned count; } cs[128] = {0};
        unsigned ncs = 0, unclassified = 0;
        double attributed = 0.0;
        for (int k = 0; k < ns; k++) {
            const gp_mark *m = &g_m[s[k].i];
            if (strncmp(m->desc, "compute ", 8)) continue;
            char *end = NULL;
            uint64_t key = (uint64_t)strtoull(m->desc + 8, &end, 16);
            if (end == m->desc + 8 || *end != ' ') { unclassified++; continue; }
            unsigned j = 0;
            while (j < ncs && cs[j].key != key) j++;
            if (j == ncs) {
                if (ncs == sizeof(cs)/sizeof(cs[0])) { unclassified++; continue; }
                cs[ncs++].key = key;
            }
            cs[j].count++;
            cs[j].ms += s[k].ms;
            attributed += s[k].ms;
        }
        VLOG("gpu prof compute source breakdown: frame %llu %u shader keys, "
             "%.3fms attributed of %.3fms identified (%u unclassified intervals); "
             "already-recorded timestamps, no extra GPU instrumentation",
             (unsigned long long)g_frame, ncs, attributed, compute, unclassified);
        unsigned char chosen[128] = {0};
        for (unsigned rank = 0; rank < ncs && rank < 12; rank++) {
            int best = -1;
            for (unsigned j = 0; j < ncs; j++)
                if (!chosen[j] && (best < 0 || cs[j].ms > cs[best].ms)) best = (int)j;
            if (best < 0) break;
            chosen[best] = 1;
            VLOG("gpu prof compute source key: frame %llu cs %016llx "
                 "%.3fms across %u dispatch intervals (%.3fms mean); "
                 "includes completion dependency, NOT pure shader ALU time",
                 (unsigned long long)g_frame, (unsigned long long)cs[best].key,
                 cs[best].ms, cs[best].count, cs[best].ms / cs[best].count);
        }
    }
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
        if (m->gfx_block != 1) continue;
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
    // Existing samples exposed two dominant 1280x720 passes. The prior
    // 16-draw fragment attribution only recognized 683/640/960 targets.
    // For each pass, sum its 16-draw timestamp chunks PLUS the final
    // partial chunk: counting only the pass-end mark undercounts it.
    // Scissor coverage is an intentionally loose OVERDRAW PROXY, not the
    // number of executed fragments. Attachment load/store counts are NOT
    // observed DRAM transactions (the tiler may keep/merge them on chip).
    if (VKA_ENV("DM_VK_SCENE_PASS_DIAG", 0)) {
        struct {
            int i; double ms; unsigned chunks;
        } passes_1280[64] = {0};
        unsigned np = 0;
        for (int i = 1; i < g_n; i++) {
            if (!vka_scene_profile_1280(g_m[i].desc)) continue;
            double ms = elapsed[i];
            unsigned blocks = 0;
            for (int j = i - 1; j > 0 && g_m[j].gfx_block; --j) {
                ms += elapsed[j];
                blocks++;
            }
            if (np < sizeof(passes_1280)/sizeof(passes_1280[0]))
                passes_1280[np++] = (typeof(passes_1280[0])){i, ms, blocks};
        }
        if (g_seen_1280 && !np)
            VRED("Ocarina GPU profiler: %u 1280x720 scene passes were "
                 "recognized when recording, but NONE matched the report; "
                 "diagnostic inconsistent (no FPS/overdraw conclusion)",
                 g_seen_1280);
        if (np)
            VLOG("Ocarina GPU profiler: sampled %u 1280x720 pass(es), "
                 "%u recognized at record time; timestamp and raster "
                 "state report below", np, g_seen_1280);
        for (unsigned rank = 0; rank < np && rank < 12; rank++) {
            unsigned best = rank;
            for (unsigned j = rank + 1; j < np; j++)
                if (passes_1280[j].ms > passes_1280[best].ms) best = j;
            typeof(passes_1280[0]) swap = passes_1280[rank];
            passes_1280[rank] = passes_1280[best];
            passes_1280[best] = swap;
            const gp_mark *m = &g_m[passes_1280[rank].i];
            const scene_observation *o = &m->scene;
            double scissor_equiv = (double)o->scissor_sum / (1280.0 * 720.0);
            if (have_pipe_data && o->pipeline_query >= 0 &&
                (uint32_t)o->pipeline_query < g_pipe_count) {
                const uint64_t *q = pipe_data + o->pipeline_query * NSTATS;
                VLOG("gpu prof 1280x720 Vulkan pipeline counters: frame %llu "
                     "pass-end=%d input-primitives=%llu vertex-invocations=%llu "
                     "clipping-primitives=%llu fragment-invocations=%llu "
                     "fragment-invocations/target-pixel=%.3f "
                     "(VRS/depth/MSAA can change this; NOT literal overdraw)",
                     (unsigned long long)g_frame, passes_1280[rank].i,
                     (unsigned long long)q[0], (unsigned long long)q[1],
                     (unsigned long long)q[2], (unsigned long long)q[3],
                     (double)q[3] / (1280.0 * 720.0));
            }
            VLOG("gpu prof 1280x720 pass: frame %llu GPU %.3fms "
                 "(%u timed 16-draw blocks) draws=%u direct-triangle-est=%llu "
                 "indirect=%u depth-test=%u depth-write=%u stencil=%u "
                 "no-color=%u cull-none=%u scissor-area/target-area=%.2f "
                 "(NOT measured pixel overdraw), attachments load-color=%u "
                 "store-color=%u load-depth=%u store-depth=%u samples=%u "
                 "(NOT measured DRAM traffic), %s",
                 (unsigned long long)g_frame, passes_1280[rank].ms,
                 passes_1280[rank].chunks,  // samples, not all 16-draw blocks in a frame
                 (unsigned)o->draws,
                 (unsigned long long)o->direct_triangles,
                 o->indirect, o->depth_test, o->depth_write,
                 o->stencil, o->no_color, o->no_cull, scissor_equiv,
                 (unsigned)o->load_color, (unsigned)o->store_color,
                 (unsigned)o->load_depth, (unsigned)o->store_depth,
                 (unsigned)o->samples, m->desc);
        }
    }
    if (VKA_ENV("DM_VK_GPUPROF_LIST", 0))   // every step in order
        for (int k = 0; k < ns; k++) { const gp_mark *a = &g_m[s[k].i - 1], *b = &g_m[s[k].i];
            VLOG("gpu prof: step #%d %.3f ms: %s:%d, %llu draws, %llu ops%s%s", s[k].i, s[k].ms, b->file, b->line, (unsigned long long)(b->draws - a->draws),
                 (unsigned long long)(b->ops - a->ops), b->desc[0] ? "; pass " : "", b->desc); }
    qsort(s, (size_t)ns, sizeof *s, by_ms);
    // List the expensive *individual* draws, not their 16-draw neighbors.
    // Only sampled 1280x720 frames with DM_VK_OOT_GFX_FINE=1 emit this.
    // Timestamp boundaries can introduce their own GPU overhead; rankings
    // are diagnostic, NEVER an asserted FPS gain.
    unsigned fine_count = 0, fine_reported = 0, fine_begin = 0;
    double fine_ms = 0, fine_begin_ms = 0;
    for (int k = 0; k < ns; k++) if (g_m[s[k].i].gfx_block == 3) {
        const gp_mark *m = &g_m[s[k].i];
        fine_begin++; fine_begin_ms += s[k].ms;
        if (s[k].ms > 0.15)
            VLOG("gpu prof 1280x720 FINE BEGIN: frame %llu %.3fms %s",
                 (unsigned long long)g_frame, s[k].ms, m->desc);
    }
    for (int k = 0; k < ns; k++) if (g_m[s[k].i].gfx_block == 2) {
        fine_count++; fine_ms += s[k].ms;
        if (fine_reported++ < 32) {
            const gp_mark *m = &g_m[s[k].i];
            VLOG("gpu prof 1280x720 FINE draw: frame %llu rank=%u %.3fms %s",
                 (unsigned long long)g_frame, fine_reported, s[k].ms, m->desc);
        }
    }
    if (fine_count)
        VLOG("gpu prof 1280x720 FINE summary: frame %llu %u individually timestamped draws total %.3fms; %u separate BEGIN intervals %.3fms; one sampled frame only (begin includes previous dependencies, not solely DRAM load); no ordinary-frame cost or FPS claim",
             (unsigned long long)g_frame, fine_count, fine_ms, fine_begin, fine_begin_ms);
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
        g_gfx_n = 0; g_gfx_enabled = 0; g_gfx_fine = 0;
        g_pass_1280 = 0; g_seen_1280 = 0;
        g_pipe_count = 0; g_pipe_active = -1;
        g_reset(cb, g_qp, 0, NQ);
        if (g_pipe_qp) g_reset(cb, g_pipe_qp, 0, NPIPE_Q);
    }
    if (g_state == 1) { g_cb = cb; mark(cb, 1, "submission", 0); }
}
void vka_gp_commit(VkCommandBuffer cb, uint64_t fence) { if (g_state == 1 && cb == g_cb) { mark(cb, 3, "commit", 0); g_fence = fence; } }
#endif
