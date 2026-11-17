// Opt-in integration: immutable counter predicates from the CURRENT submission.
// Included after the replay's nested-list and state helpers. No shader ABI changes.
#include "vka_rc_gpu_policy.h"
#include "vka_rc_gpu_spv.h"
typedef struct {
    const prog_t *program[5]; uint64_t serial[5];
    const uint8_t *caller[16]; int depth, tf, discard;
} rc_gpu_context;
typedef struct { const uint8_t *p; rc_rep a, b; uint32_t mode; rc_gpu_context context; } rc_gpu_job;
static rc_gpu_job g_rc_jobs[VKA_RC_GPU_MAX_JOBS];
static vka_rc_gpu_plan g_rc_plan;
static uint32_t g_rc_job_words[VKA_RC_GPU_MAX_JOBS * 12];
static void rc_gpu_context_of(rc_gpu_context *out, const vka_dstate *d, int depth, const uint8_t *const *caller) {
    memset(out, 0, sizeof *out); out->depth = depth; out->tf = d->tf_on; out->discard = d->rast_discard;
    for (int i = 0; i < 5; i++) { out->program[i] = d->bst[i]; out->serial[i] = d->bst[i] ? d->bst[i]->serial : 0; }
    for (int i = 0; i < depth && i < 16; i++) out->caller[i] = caller[i];
}
static struct {
    int enabled, n, delta_mode;
    uint64_t revision, submission_first;
    const uint8_t *record[VKA_RC_GPU_MAX_JOBS];
    rc_gpu_context context[VKA_RC_GPU_MAX_JOBS];
    vka_span predicates, current;
    VkDescriptorSetLayout set;
    VkPipelineLayout layout;
    VkPipeline pipeline;
    uint64_t batches, pairs, query_copies, requests, cpu_zero;
} RG;
static vka_dstate g_rc_scan;

static void rc_gpu_sub_begin(void) {
    RG.enabled = !strcmp(DM_GAME_ID, "0400486024DEC000") && VKA_ENV("DM_VK_GPU_VISIBILITY", 0);
    // The existing feature is OFF by default. With it enabled, use the
    // same-epoch DELTA of two cumulative reports, not two fresh counters.
    // DM_VK_OOT_RC_DELTA=0 restores the original fresh-only experiment.
    RG.delta_mode = RG.enabled && VKA_ENV("DM_VK_OOT_RC_DELTA", 1);
    RG.n = 0; RG.current.buf = VK_NULL_HANDLE; RG.submission_first = g_oq_head;
}
void vka_rc_gpu_invalidate(void) {
    if (!RG.enabled) return;
    g_rc_gpu_write_epoch++; g_rc_revision++; RG.current.buf = VK_NULL_HANDLE; RG.n = 0;
}
static void rc_gpu_written(uint64_t addr, uint64_t bytes) {
    if (!RG.enabled || !bytes) return;
    if (bytes > 4096 || bytes - 1 > UINT64_MAX - addr) { vka_rc_gpu_invalidate(); return; }
    uint64_t start = addr & ~UINT64_C(15), last = (addr + bytes - 1) & ~UINT64_C(15);
    for (uint64_t p = start;; p += 16) {
        int i = rc_ix_find(p);
        if (i >= 0 && g_rcp[i].kind == 3) { vka_rc_gpu_invalidate(); return; }
        if (p == last) break;
    }
}
static int rc_gpu_report(uint64_t addr, rc_rep *out) {
    if (addr & 15) return 0;
    int i = rc_ix_find(addr);
    if (i < 0) return 0;
    *out = g_rcp[i];
    if (out->gpu_write_epoch != g_rc_gpu_write_epoch) return 0;
    if (!RG.delta_mode) return
        vka_rc_gpu_range(out->kind, out->oq_fresh, out->fence, out->oq_lost, out->oq_begin, out->oq_end,
                         RG.submission_first, g_oq_head);
    // Raw per-report validity for cumulative-delta pairing, still only
    // records written in the CURRENT submission: earlier completed reports
    // can have their query slots reset asynchronously by the host.
    return out->kind == 3 && out->oq_epoch && !out->fence &&
        out->oq_end >= out->oq_begin &&
        out->oq_end >= RG.submission_first &&
        out->oq_end <= g_oq_head;
}
static int rc_gpu_pair_valid(const rc_rep *a, const rc_rep *b, vka_rc_gpu_delta *delta) {
    if (!RG.delta_mode) return 1; // both sides passed original fresh-only gate
    return vka_rc_gpu_delta_pair(
        a->kind, b->kind, a->oq_epoch, b->oq_epoch,
        a->fence, b->fence, a->oq_lost, b->oq_lost,
        a->oq_end, b->oq_end,
        RG.submission_first, g_oq_head, delta);
}
static int rc_gpu_init(void) {
    if (RG.pipeline) return 1;
    VkDescriptorSetLayoutBinding b[3];
    for (unsigned i = 0; i < 3; i++) b[i] = (VkDescriptorSetLayoutBinding){
        .binding = i, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
        .descriptorCount = 1, .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT};
    VkDescriptorSetLayoutCreateInfo si = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
        .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, .bindingCount = 3, .pBindings = b};
    if (!RG.set && vk.vkCreateDescriptorSetLayout(V.dev, &si, NULL, &RG.set)) return 0;
    VkPushConstantRange pc = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 4};
    VkPipelineLayoutCreateInfo li = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount = 1, .pSetLayouts = &RG.set, .pushConstantRangeCount = 1, .pPushConstantRanges = &pc};
    if (!RG.layout && vk.vkCreatePipelineLayout(V.dev, &li, NULL, &RG.layout)) return 0;
    VkShaderModuleCreateInfo mi = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = sizeof SPV_RC_VISIBILITY, .pCode = SPV_RC_VISIBILITY};
    VkShaderModule module;
    if (vk.vkCreateShaderModule(V.dev, &mi, NULL, &module)) return 0;
    VkComputePipelineCreateInfo pi = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                  .module = module, .pName = "main"}, .layout = RG.layout};
    VkResult r = vk.vkCreateComputePipelines(V.dev, VK_NULL_HANDLE, 1, &pi, NULL, &RG.pipeline);
    vk.vkDestroyShaderModule(V.dev, module, NULL);
    return r == VK_SUCCESS;
}
// Every admitted block has only classic, side-effect-free draws and state.
// Crossing report/reset/transfer/clear/dispatch/event records is forbidden.
// Complete a block at the next render-enable command, or the outer list end;
// otherwise discard its candidate. No partial block is ever predicated.
static int rc_gpu_collect(const uint8_t *p, rc_gpu_job *jobs) {
    const uint8_t *ret[17]; int nr = g_memu_depth;
    if (nr < 0 || nr > 16) return 0;
    for (int i = 0; i < nr; i++) ret[i] = g_memu_caller[i];
    g_rc_scan = S.d;
    int n = 0, pending = -1, draws = 0;
    for (int guard = 0; guard < 200000; guard++) {
        op_hdr h; memcpy(&h, p, sizeof h); const void *arg = p + 8;
        if (h.size < 8) break;
        if (h.op == OP_END) {
            if (nr) { p = ret[--nr]; continue; }
            if (pending >= 0 && draws) n++;
            pending = -1; break;
        }
        if (h.op == OP_JUMP) { memcpy(&p, arg, 8); continue; }
        if (h.op == OP_CALL) { if (nr == 16) break; ret[nr++] = p + h.size; memcpy(&p, arg, 8); continue; }
        if (h.op == OP_RENDER_COND) {
            if (pending >= 0 && draws) n++;
            pending = -1; draws = 0;
            if (n == VKA_RC_GPU_MAX_JOBS || h.size < 8 + sizeof(p_render_cond)) break;
            p_render_cond cond; memcpy(&cond, arg, sizeof cond);
            if ((cond.mode == 0 || cond.mode == 1) && cond.addr <= UINT64_MAX - 16 &&
                rc_gpu_report(cond.addr, &jobs[n].a) && rc_gpu_report(cond.addr + 16, &jobs[n].b) &&
                rc_gpu_pair_valid(&jobs[n].a, &jobs[n].b, &(vka_rc_gpu_delta){0})) {
                if (RG.delta_mode
                    ? (jobs[n].a.oq_end == jobs[n].b.oq_end &&
                       jobs[n].a.oq_lost == jobs[n].b.oq_lost)
                    : (jobs[n].a.oq_begin == jobs[n].a.oq_end &&
                       jobs[n].b.oq_begin == jobs[n].b.oq_end)) {
                    p += h.size; continue; // rc_gpu_bind resolves these exact empty counters on the CPU.
                }
                jobs[n].p = p; jobs[n].mode = (uint32_t)cond.mode;
                rc_gpu_context_of(&jobs[n].context, &g_rc_scan, nr, ret); pending = n;
            }
        } else if (h.op == OP_DRAW || h.op == OP_DRAW_IDX) {
            if (pending >= 0) {
                int safe = vka_rc_gpu_state_safe(&g_rc_scan);
                if (h.op == OP_DRAW) { p_draw tmp; const p_draw *d = draw_rec(arg, h.size, &tmp);
                    safe = safe && d->prim != NVN_PRIM_MESH && !d->mdi_cnt && !d->base_instance &&
                        d->prim != NVN_DRAW_PRIMITIVE_LINE_LOOP && d->prim != NVN_DRAW_PRIMITIVE_QUADS; }
                else { p_draw_idx tmp; const p_draw_idx *d = draw_idx_rec(arg, h.size, &tmp);
                    safe = safe && !d->mdi_cnt && !d->base_instance &&
                        d->prim != NVN_DRAW_PRIMITIVE_LINE_LOOP && d->prim != NVN_DRAW_PRIMITIVE_QUADS; }
                if (!safe) { pending = -1; break; }
                else draws++;
            }
        } else if (overlap_state_record(h.op) || h.op == OP_SET_RT || h.op == OP_BARRIER) {
            vka_state_op(&g_rc_scan, h.op, arg);
        } else break;
        p += h.size;
    }
    return n;
}
static void rc_gpu_prepare(const uint8_t *p) {
    RG.n = 0; RG.revision = g_rc_revision;
    rc_gpu_job *jobs = g_rc_jobs;
    int n = rc_gpu_collect(p, jobs);
    if (!n) return;
    memset(&g_rc_plan, 0, sizeof g_rc_plan);
    for (int i = 0; i < n; i++) {
        uint32_t *j = g_rc_job_words + i * 12; memset(j, 0, 48);
        const rc_rep *r[2] = {&jobs[i].a, &jobs[i].b};
        if (RG.delta_mode) {
            vka_rc_gpu_delta d;
            uint32_t off = 0;
            if (!rc_gpu_pair_valid(r[0], r[1], &d) ||
                !vka_rc_gpu_plan_add(&g_rc_plan, d.begin, d.end, OQ_N, &off))
                return;
            // The original checked-in SPIR-V helper compares TWO counters.
            // Encode zero as its A and the exact cumulative difference as B.
            // Non-precise queries have sound zero/positive semantics; precise
            // queries sum the full 64-bit count. No shader module or ABI edit.
            j[4] = off;
            j[5] = (uint32_t)(d.end - d.begin);
            j[6] = (uint32_t)d.lost_delta;
            j[7] = (uint32_t)(d.lost_delta >> 32);
        } else for (unsigned side = 0; side < 2; side++) {
            if (!vka_rc_gpu_plan_add(&g_rc_plan, r[side]->oq_begin, r[side]->oq_end, OQ_N, &j[side * 4])) return;
            j[side * 4 + 1] = (uint32_t)(r[side]->oq_end - r[side]->oq_begin);
            j[side * 4 + 2] = (uint32_t)r[side]->oq_lost;
            j[side * 4 + 3] = (uint32_t)(r[side]->oq_lost >> 32);
        }
        j[8] = jobs[i].mode; j[9] = (uint32_t)OQ.precise;
    }
    if (!rc_gpu_init()) return;
    uint32_t total = g_rc_plan.total;
    vka_span query, job, predicate;
    VkDeviceSize align = V.sb_align > 8 ? V.sb_align : 8;
    if (!vka_scratch((total ? total : 1) * 8, align, &query) ||
        !vka_scratch((VkDeviceSize)n * 48, align, &job) ||
        !vka_scratch((VkDeviceSize)n * 4, align, &predicate)) return;
    memcpy(job.ptr, g_rc_job_words, (size_t)n * 48);
    // All queries come from closed reports in this submission. Their reset
    // callback cannot run until this fence completes, after these copies.
    vka_rp_end(); vka_dispatch_overlap_flush();
    for (unsigned i = 0; i < g_rc_plan.copies; i++) {
        const vka_rc_gpu_copy *c = &g_rc_plan.copy[i];
        vk.vkCmdCopyQueryPoolResults(g_cb, OQ.pool, c->first, c->count, query.buf,
            query.off + (VkDeviceSize)c->offset * 8, 8, VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
    }
    for (int i = 0; i < n; i++) { RG.record[i] = jobs[i].p; RG.context[i] = jobs[i].context; }
    RG.query_copies += g_rc_plan.copies;
    VkMemoryBarrier transfer = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT | VK_ACCESS_HOST_WRITE_BIT,
        .dstAccessMask = VK_ACCESS_SHADER_READ_BIT};
    vk.vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_TRANSFER_BIT | VK_PIPELINE_STAGE_HOST_BIT,
        VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &transfer, 0, NULL, 0, NULL);
    VkDescriptorBufferInfo bi[3] = {{query.buf, query.off, (total ? total : 1) * 8},
        {job.buf, job.off, (VkDeviceSize)n * 48}, {predicate.buf, predicate.off, (VkDeviceSize)n * 4}};
    VkWriteDescriptorSet writes[3];
    for (unsigned i = 0; i < 3; i++) writes[i] = (VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
        .dstBinding = i, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi[i]};
    vk.vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, RG.pipeline);
    vk.vkCmdPushDescriptorSetKHR(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, RG.layout, 0, 3, writes);
    uint32_t count = (uint32_t)n;
    vk.vkCmdPushConstants(g_cb, RG.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, 4, &count);
    vk.vkCmdDispatch(g_cb, (count + 31) / 32, 1, 1);
    VkMemoryBarrier publish = {VK_STRUCTURE_TYPE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_INDIRECT_COMMAND_READ_BIT};
    vk.vkCmdPipelineBarrier(g_cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT,
        0, 1, &publish, 0, NULL, 0, NULL);
    vka_dyn_invalidate();
    RG.n = n; RG.predicates = predicate; RG.batches++; RG.pairs += (uint64_t)n;
}
static void rc_gpu_bind(const uint8_t *p) {
    RG.current.buf = VK_NULL_HANDLE;
    if (!RG.enabled || S.rc_skip || !g_cb || g_oq != 1 || !OQ.pool ||
        !V.push_desc || V.max_push < 3 || !V.indirect_count || !vk.vkCmdCopyQueryPoolResults ||
        !vk.vkCmdDrawIndirectCount || !vk.vkCmdDrawIndexedIndirectCount) return;
    p_render_cond cond; memcpy(&cond, p + 8, sizeof cond);
    if (cond.mode != 0 && cond.mode != 1) return;
    rc_rep a, b;
    if (!rc_gpu_report(cond.addr, &a) || cond.addr > UINT64_MAX - 16 ||
        !rc_gpu_report(cond.addr + 16, &b) ||
        !rc_gpu_pair_valid(&a, &b, &(vka_rc_gpu_delta){0})) return;
    if (RG.delta_mode ? (a.oq_end == b.oq_end && a.oq_lost == b.oq_lost)
                      : (a.oq_begin == a.oq_end && b.oq_begin == b.oq_end)) {
        // Fresh + zero lost + no queries proves both counters are exactly zero,
        // independently of GPU completion. Do not dispatch a predicate helper.
        S.rc_skip = cond.mode == 1; RG.cpu_zero++; return;
    }
    rc_gpu_context context;
    rc_gpu_context_of(&context, &S.d, g_memu_depth, g_memu_caller);
    int i;
    for (i = 0; i < RG.n; i++) if (RG.record[i] == p && RG.revision == g_rc_revision &&
        !memcmp(&RG.context[i], &context, sizeof context)) break;
    if (i == RG.n) {
        rc_gpu_prepare(p);
        for (i = 0; i < RG.n; i++) if (RG.record[i] == p &&
            !memcmp(&RG.context[i], &context, sizeof context)) break;
    }
    if (i < RG.n) { RG.current = RG.predicates; RG.current.off += (VkDeviceSize)i * 4; }
}
int vka_rc_gpu_enabled(void) { return RG.enabled; }
int vka_rc_gpu_predicate(VkBuffer *buffer, VkDeviceSize *offset) {
    if (!RG.enabled || !RG.current.buf) return 0;
    *buffer = RG.current.buf; *offset = RG.current.off; RG.requests++; return 1;
}
static void rc_gpu_stats(double frames) {
    if (!RG.enabled || frames <= 0) return;
    VLOG("GPU visibility research: delta=%d (1=same-reset cumulative difference, 0=original fresh-only), %.1f batches, %.1f exact current-submission pairs, %.1f query copies, %.1f draw-count predicate requests, %.1f exact empty-delta CPU decisions/frame; no hidden-draw/FPS claim",
        RG.delta_mode, RG.batches / frames, RG.pairs / frames, RG.query_copies / frames, RG.requests / frames, RG.cpu_zero / frames);
    RG.batches = RG.pairs = RG.query_copies = RG.requests = RG.cpu_zero = 0;
}
