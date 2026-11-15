// Opt-in integration: immutable counter predicates from the CURRENT submission.
// Included after the replay's nested-list and state helpers. No shader ABI changes.
#include "vka_rc_gpu_policy.h"
#include "vka_rc_gpu_spv.h"
static struct {
    int enabled, n;
    uint64_t revision, submission_first;
    const uint8_t *record[VKA_RC_GPU_MAX_JOBS];
    vka_span predicates, current;
    VkDescriptorSetLayout set;
    VkPipelineLayout layout;
    VkPipeline pipeline;
    uint64_t batches, pairs, query_copies, requests;
} RG;
static vka_dstate g_rc_scan;

static void rc_gpu_sub_begin(void) {
    RG.enabled = !strcmp(DM_GAME_ID, "0400486024DEC000") && VKA_ENV("DM_VK_GPU_VISIBILITY", 0);
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
    return out->gpu_write_epoch == g_rc_gpu_write_epoch &&
        vka_rc_gpu_range(out->kind, out->oq_fresh, out->fence, out->oq_lost, out->oq_begin, out->oq_end,
                         RG.submission_first, g_oq_head);
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
static void rc_gpu_prepare(const uint8_t *p) {
    RG.n = 0; RG.revision = g_rc_revision;
    const uint8_t *ret[17]; int nr = g_memu_depth;
    if (nr < 0 || nr > 16) return;
    for (int i = 0; i < nr; i++) ret[i] = g_memu_caller[i];
    g_rc_scan = S.d;
    struct { const uint8_t *p; rc_rep a, b; uint32_t mode; } jobs[VKA_RC_GPU_MAX_JOBS];
    int n = 0, pending = -1, draws = 0;
    uint32_t total = 0;
    for (int guard = 0; guard < 200000; guard++) {
        op_hdr h; memcpy(&h, p, sizeof h); const void *arg = p + 8;
        if (h.size < 8) break;
        if (h.op == OP_END) {
            if (nr) { p = ret[--nr]; continue; }
            if (pending >= 0 && draws) n++;
            pending = -1; break;
        }
        if (h.op == OP_JUMP) { memcpy(&p, arg, 8); continue; }
        if (h.op == OP_CALL) { if (nr == 17) break; ret[nr++] = p + h.size; memcpy(&p, arg, 8); continue; }
        if (h.op == OP_RENDER_COND) {
            if (pending >= 0 && draws) n++;
            pending = -1; draws = 0;
            if (n == VKA_RC_GPU_MAX_JOBS || h.size < 8 + sizeof(p_render_cond)) break;
            p_render_cond cond; memcpy(&cond, arg, sizeof cond);
            if ((cond.mode == 0 || cond.mode == 1) && cond.addr <= UINT64_MAX - 16 &&
                rc_gpu_report(cond.addr, &jobs[n].a) && rc_gpu_report(cond.addr + 16, &jobs[n].b)) {
                jobs[n].p = p; jobs[n].mode = (uint32_t)cond.mode; pending = n;
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
    // A candidate is counted only after seeing its full safe block.
    if (!n) return;
    for (int i = 0; i < n; i++) {
        uint64_t amount = jobs[i].a.oq_end - jobs[i].a.oq_begin + jobs[i].b.oq_end - jobs[i].b.oq_begin;
        if (amount > VKA_RC_GPU_MAX_QUERIES - total) { n = i; break; }
        total += (uint32_t)amount;
    }
    if (!n || !rc_gpu_init()) return;
    vka_span query, job, predicate;
    VkDeviceSize align = V.sb_align > 8 ? V.sb_align : 8;
    if (!vka_scratch((total ? total : 1) * 8, align, &query) ||
        !vka_scratch((VkDeviceSize)n * 48, align, &job) ||
        !vka_scratch((VkDeviceSize)n * 4, align, &predicate)) return;
    // All queries come from reports recorded in this submission, already
    // closed. Their host-reset callback cannot run until this fence completes.
    vka_rp_end(); vka_dispatch_overlap_flush();
    uint32_t cursor = 0;
    for (int i = 0; i < n; i++) {
        uint32_t *j = (uint32_t *)job.ptr + i * 12; memset(j, 0, 48);
        const rc_rep *r[2] = {&jobs[i].a, &jobs[i].b};
        for (unsigned side = 0; side < 2; side++) {
            uint32_t count = (uint32_t)(r[side]->oq_end - r[side]->oq_begin);
            j[side * 4] = cursor; j[side * 4 + 1] = count;
            j[side * 4 + 2] = (uint32_t)r[side]->oq_lost; j[side * 4 + 3] = (uint32_t)(r[side]->oq_lost >> 32);
            for (uint64_t q = r[side]->oq_begin; q < r[side]->oq_end;) {
                uint32_t slot = (uint32_t)(q % OQ_N), k = (uint32_t)(r[side]->oq_end - q);
                if (k > OQ_N - slot) k = OQ_N - slot;
                vk.vkCmdCopyQueryPoolResults(g_cb, OQ.pool, slot, k, query.buf,
                    query.off + (VkDeviceSize)cursor * 8, 8, VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
                cursor += k; q += k; RG.query_copies++;
            }
        }
        j[8] = jobs[i].mode; j[9] = (uint32_t)OQ.precise; RG.record[i] = jobs[i].p;
    }
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
    int i;
    for (i = 0; i < RG.n; i++) if (RG.record[i] == p && RG.revision == g_rc_revision) break;
    if (i == RG.n) {
        rc_gpu_prepare(p);
        for (i = 0; i < RG.n; i++) if (RG.record[i] == p) break;
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
    VLOG("GPU visibility research: %.1f batches, %.1f exact current-submission pairs, %.1f query copies, %.1f draw-count predicate requests/frame; no hidden-draw/FPS claim",
        RG.batches / frames, RG.pairs / frames, RG.query_copies / frames, RG.requests / frames);
    RG.batches = RG.pairs = RG.query_copies = RG.requests = 0;
}
