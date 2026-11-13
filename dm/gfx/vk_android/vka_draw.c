// Draws and dispatches of the Vulkan replay: nvn_mtl.m's draw path on Vulkan. vka_exec.c walks the records; state records land in the queue's vka_dstate (vka_state_op),
// and each draw resolves its program to shaders (vka_shader.c), opens the dynamic-rendering pass of the bound targets if none is open, takes a pipeline keyed on the state
// Vulkan cannot set dynamically here (vka_pso.c), writes set 0 from the binding records (vka_bind.c's walker: push descriptors when they fit, else a set from the submission
// slot's pool), sets the dynamic state and draws. The pass stays open across draws and closes at anything else (vka_rp_end), followed by a full barrier.
// What is not here yet, each logged once: SINT attachments and integer vertex formats (no variants), transform feedback, DrawTexture, line loops and quads through indirect draws,
// tessellation's patch size, texel buffers, viewport swizzles other than a y flip
#if defined(__ANDROID__)
#include "vka.h"
#include "vka_selftest_spv.h"   // SPV_MESHCOUNT_COMP (mesh_ind_args)
#include "vka_ndsr.h"
#include "vka_ndsr_sampler.h"           // vka_ndsr_pipeline (vka_dispatch)
#include "vka_hidden_layers.h"   // exact experimental Ocarina fragment discard keys
#include "../nvn/nvn_mtl.h"
#include "../../host/plat/plat.h"
#include "vka_memu_abi.h"
#include "vka_prepass.h"
#include "vka_vegetation_profiles.h"
#include "vka_vegetation_supplement.h"  // generated 508 original task/mesh shader keys (kept ABI-stable)
#include "game_profile.h"
#include <math.h>
#include <stdio.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

static int g_classic_pass;
static VkCommandBuffer g_cb; static unsigned g_slot; static int g_prof, g_dyn_filter = 1, g_pass_keep = 1, g_vb_filter = 1;   // g_prof: DM_VK_PROF
static int g_vin_skip = 1;
static uint64_t g_vin_kept, g_vin_built, g_vb_kept, g_vb_bound;
uint64_t vka_n_rp;   // render passes the draws opened (vka_exec.c replay statistics)
static uint64_t g_draws, g_skipped, g_dispatches;
static int g_dispatch_overlap_pending;
static uint64_t g_dispatch_overlap_skipped;
uint64_t vka_frame(void);  // also used by the fail-closed SGSR chain frame tracker
// The Metal port can overlap successive compute dispatches when NVN issued no
// explicit barrier between them. The Vulkan replay had inserted a full GPU
// barrier after every single dispatch. Defer that dependency across adjacent
// dispatches only when their host spill/indirect buffers are not in use. Any
// draw, transfer, guest barrier, query, list boundary or command-buffer switch
// flushes first, preserving the ordering of all non-compute work.
void vka_dispatch_overlap_flush(void) {
    // Only compute dispatches can set pending: they have no external indirect
    // buffer or shared-memory spill and no guest OP_BARRIER between them.
    // End their GPU dependency with the actual compute/transfer producer
    // stages, not an ALL_COMMANDS -> ALL_COMMANDS memory drain. Every later
    // draw, copy, readback and guest synchronization still waits and sees
    // writes through ALL_COMMANDS read/write destination access.
    if (g_dispatch_overlap_pending && g_cb)
        vka_compute_write_barrier(g_cb);
    g_dispatch_overlap_pending = 0;
}
uint64_t vka_dispatch_overlap_skips(void) { return g_dispatch_overlap_skipped; }
// iOS V19 (cheemu21/kid-with-sword-remake, commit 5da2b49) identified
// the fourth/last 0.25-scale chain shader d99fbeeb53d38847. The first
// three programs do feature extraction/network/blend, before the last
// compute stage writes the game's scene image (UI is added afterwards).
// Only skip them once a PREVIOUS full frame successfully ran the last
// stage through the existing Vulkan FSR stand-in and the PRESENT path
// actually used SGSR1. The first frame is always left untouched.
// Fail closed if the source format/shape changes or the last stage fails.
// DM_VK_OOT_SGSR_CHAIN=0 restores the original chain, without a new APK.
static struct {
    uint64_t frame;
    int source_tid, primed, refused, skipped, completed;
    uint64_t bypassed;
} g_oot_sgsr_chain = {.frame = UINT64_MAX};
static void oot_sgsr_chain_frame(void) {
    uint64_t f = vka_frame();
    if (g_oot_sgsr_chain.frame == f) return;
    if (g_oot_sgsr_chain.skipped && !g_oot_sgsr_chain.completed) {
        g_oot_sgsr_chain.refused = 1;
        VRED_ONCE("Ocarina SGSR chain: previous frame had no d99fbeeb final network; "
                  "disable bypass and keep the game's original chain");
    }
    g_oot_sgsr_chain.frame = f;
    g_oot_sgsr_chain.source_tid = 0;
    g_oot_sgsr_chain.skipped = 0;
    g_oot_sgsr_chain.completed = 0;
}
static int oot_sgsr_chain_on(void) {
    return !strcmp(DM_GAME_ID, "0400486024DEC000")
        && VKA_ENV("DM_VK_OOT_SGSR_CHAIN", 0)
        && VKA_ENV("DM_VK_PRESENT_FILTER", 0) == 4
        && vka_present_sgsr_active() && !g_oot_sgsr_chain.refused
        && !vka_nan_on() && !vka_gp_active;
}
static int oot_sgsr_chain_part(uint64_t key) {
    if (key == UINT64_C(0xf8965bffbdf51d78)) return 2; // original HDR scene input
    if (key == UINT64_C(0xd17eefaff4f0bc23) ||
        key == UINT64_C(0xa335c1db6270c355)) return 1; // old feature/blend
    if (key == UINT64_C(0xd99fbeeb53d38847)) return 3; // 0.25 last network
    return 0;
}
static uint32_t g_claim_words;   // the draw's claim words (an upper bound of its primitives): 0 = its geometry shader takes no claim
#define SKIPQ() do { g_skipped++; if (VKA_ENV("DM_VK_SKIP_LOG", 0)) VLOG("skip log: draw or dispatch skipped at vka_draw.c:%d (frame %llu)", __LINE__, (unsigned long long)vka_frame()); return; } while (0)   // diagnostic: DM_VK_SKIP_LOG=1
#define SKIP(...) do { g_skipped++; static _Atomic int n_; if (atomic_fetch_add(&n_, 1) < 4) VRED(__VA_ARGS__); if (VKA_ENV("DM_VK_SKIP_LOG", 0)) VLOG("skip log: draw skipped at vka_draw.c:%d (frame %llu)", __LINE__, (unsigned long long)vka_frame()); return; } while (0)

// Whether draws and dispatches run. Without placed guest memory (an emulator's driver) the GPU sees no memory pool, so a game's draws would read nothing and only cost:
// pipeline compiles there take minutes each. Off there by default, on with placed memory; DM_VK_DRAW=0 / 1 overrides, the selftest turns them on for its own memory
static int g_force_draws;
void vka_draw_force(int on) { g_force_draws = on; }
static int draws_on(void) {
    int env = VKA_ENV("DM_VK_DRAW", -1); if (env > 0) env = 1;
    int on = g_force_draws || (env >= 0 ? env : V.placed);
    if (!on) VRED_ONCE("draws and dispatches are off (%s): their records are skipped; events, counters and fences still signal", env == 0 ? "DM_VK_DRAW=0" : "no placed guest memory, so the GPU would see no pool; DM_VK_DRAW=1 turns them on");
    return on;
}

// ---------- State ----------
// Banana Native's per-input stamps: unique across queue states and the
// mesh look-ahead's copies, not merely incremented within each copy.
static _Atomic uint64_t g_state_stamp;
static uint64_t state_stamp(void) { return atomic_fetch_add_explicit(&g_state_stamp, 1, memory_order_relaxed) + 1; }
void vka_dstate_reset(vka_dstate *d) {   // NVN's defaults (nvn_mtl.m state_reset)
    memset(d, 0, sizeof *d); d->inited = 1;
    for (int i = 0; i < 8; i++) d->blend[i] = (blend_st){i, NVN_BLEND_FUNC_ONE, NVN_BLEND_FUNC_ZERO, NVN_BLEND_FUNC_ONE, NVN_BLEND_FUNC_ZERO, NVN_BLEND_EQUATION_ADD, NVN_BLEND_EQUATION_ADD};
    d->color = (color_st){0, NVN_LOGIC_OP_COPY, NVN_ALPHA_FUNC_ALWAYS}; d->chmask.mask = 0xffffffffu;
    d->poly = (poly_st){NVN_FACE_NONE, NVN_FRONT_FACE_CCW, NVN_POLYGON_MODE_FILL, 0};
    d->ds = (ds_st){0, 1, NVN_DEPTH_FUNC_LESS, 0, NVN_STENCIL_FUNC_ALWAYS, NVN_STENCIL_FUNC_ALWAYS, 1, 1, 1, 1, 1, 1};
    d->st_vmask[0] = d->st_vmask[1] = d->st_wmask[0] = d->st_wmask[1] = 0xff; d->dr[1] = 1; d->b.samples = 1;
    d->s_vfmt = state_stamp(); d->s_vbuf = state_stamp(); d->s_push = state_stamp();
    for (int st = 0; st < VKA_NSTAGE; st++) { d->s_ssbo[st] = state_stamp(); d->s_tex[st] = state_stamp(); }
}
int nvn_dpool_base(const void *pool, int tex);   // hle_nvn.c: where a descriptor pool's IDs start in the host table
int vka_state_op(vka_dstate *d, uint32_t op, const void *a) {
    if (!d->inited) vka_dstate_reset(d);
    switch (op) {
    case OP_SET_TEX_POOL: case OP_SET_SAMP_POOL: { int tex = op == OP_SET_TEX_POOL, b = nvn_dpool_base(((const p_set_pool *)a)->pool, tex); if (tex) d->b.tex_base = b; else d->b.samp_base = b; break; }
    case OP_BIND_PROGRAM: { const p_bind_program *b = a;
        if (b->stages & 0x20) d->cprog = b->prog;
        for (int st = 0; st < VKA_NSTAGE; st++) if (st != 5 && (b->stages >> st & 1)) d->bst[st] = b->prog;   // NVN binds per stage (nvn_mtl.m bind_stages); 6 / 7: NVN2's task and mesh
        break; }
    case OP_BIND_STATE: {
        const p_bind_state *b = a; blend_st bs;
        switch (b->kind) {
        case 0: memcpy(&bs, b->bytes, sizeof bs); d->blend[bs.target] = bs; break;
        case 1: memcpy(&d->color, b->bytes, sizeof d->color); break;
        case 2: memcpy(&d->chmask, b->bytes, sizeof d->chmask); break;
        case 3: memcpy(&d->ms, b->bytes, sizeof d->ms); break;
        case 4: memcpy(&d->poly, b->bytes, sizeof d->poly); break;
        case 5: memcpy(&d->ds, b->bytes, sizeof d->ds); break;
        }
        break; }
    case OP_BIND_VATTR: { const p_bind_vattr *b = a; if (b->first >= 0 && b->n >= 0 && b->first + b->n <= 16) { memcpy(&d->attr[b->first], b->st, 4 * (size_t)b->n); if (b->first + b->n > d->nattr) d->nattr = b->first + b->n; d->s_vfmt = state_stamp(); } break; }
    case OP_BIND_VSTREAM: { const p_bind_vstream *b = a; if (b->first >= 0 && b->n >= 0 && b->first + b->n <= 16) { memcpy(&d->stream[b->first], b->st, 8 * (size_t)b->n); if (b->first + b->n > d->nstream) d->nstream = b->first + b->n; d->s_vfmt = state_stamp(); } break; }
    case OP_BIND_VBUF: case OP_BIND_VBUF1: { p_bind_vbuf tmp; const p_bind_vbuf *b = vbuf_rec(op, a, &tmp); if (b->first >= 0 && b->n >= 0 && b->first + b->n <= 16) { memcpy(&d->vbuf[b->first], b->r, sizeof *b->r * (size_t)b->n); d->s_vbuf = state_stamp(); } break; }
    case OP_BIND_UBO: case OP_BIND_UBO_SMALL: { p_bind_buf tmp; const p_bind_buf *b = bind_buf_rec(op, a, &tmp); if (b->stage >= 0 && b->stage < VKA_NSTAGE && b->index >= 0 && b->index < 16) d->b.ubo[b->stage][b->index] = (vka_range){b->addr, b->size}; break; }
    case OP_BIND_SSBO: { const p_bind_buf *b = a; if (b->stage >= 0 && b->stage < VKA_NSTAGE && b->index >= 0 && b->index < 16) { d->b.ssbo[b->stage][b->index] = (vka_range){b->addr, b->size}; d->s_ssbo[b->stage] = state_stamp(); } break; }
    case OP_BIND_TEX: case OP_BIND_TEX1: { p_bind_handles t1; const p_bind_handles *b = bind_rec(op, a, &t1);
        if (b->n < 0 || b->n > 32) { VRED_ONCE("texture bind record with count %d: overwritten after recording", b->n); break; }
        uint64_t h[32]; memcpy(h, b->h, 8 * (size_t)b->n);
        if (b->defer && b->src && b->n) {   // BindTexturesDeferred: the handles as memory holds them now (nvn_mtl.m bh_fresh); placed guest memory read directly, else word by word through the fault-safe read
            uint32_t w[32];
            if (vka_addr(b->src, 4u * (uint64_t)b->n, NULL, NULL, NULL)) { memcpy(w, (const void *)(uintptr_t)b->src, 4 * (size_t)b->n); for (int k = 0; k < b->n; k++) h[k] = w[k]; }
            else if (!plat_mem_read(b->src, w, 4 * (size_t)b->n)) for (int k = 0; k < b->n; k++) h[k] = w[k];   // one read for the run (they are in the game's heap; profile p2: 3.4 % in process_vm_readv)
            else for (int k = 0; k < b->n; k++) if (!plat_mem_read(b->src + 4u * k, &w[k], 4)) h[k] = w[k];   // a run across an unreadable page: word by word
        }
        if (b->stage >= 0 && b->stage < VKA_NSTAGE && b->first >= 0 && b->first + b->n <= VKA_NTEX) { memcpy(&d->b.tex[b->stage][b->first], h, 8 * (size_t)b->n); d->s_tex[b->stage] = state_stamp(); }
        break; }
    case OP_BIND_SAMP: { const p_bind_handles *b = a; if (b->stage >= 0 && b->stage < VKA_NSTAGE && b->first >= 0 && b->n >= 0 && b->first + b->n <= 128) { memcpy(&d->b.samp[b->stage][b->first], b->h, 8 * (size_t)b->n); d->s_tex[b->stage] = state_stamp(); } break; }
    case OP_BIND_IMG: { const p_bind_handles *b = a; if (b->stage >= 0 && b->stage < VKA_NSTAGE && b->first >= 0 && b->n >= 0 && b->first + b->n <= 32) { memcpy(&d->b.img[b->stage][b->first], b->h, 8 * (size_t)b->n); d->s_tex[b->stage] = state_stamp(); } break; }
    case OP_STENCIL: { const p_stencil *b = a;
        for (int f = 0; f < 2; f++) if (b->face & (1 << f)) { if (b->which == 0) d->st_vmask[f] = (uint32_t)b->value_mask; else if (b->which == 1) d->st_wmask[f] = (uint32_t)b->mask; else d->st_ref[f] = (uint32_t)b->ref; }
        break; }
    case OP_POLY_OFFSET: d->po = *(const p_poly_offset *)a; break;
    case OP_VIEWPORTS: { const p_viewports *b = a; for (int i = 0; i < b->n && b->first + i < 16; i++) memcpy(d->vp[b->first + i], b->v[i], 16); d->has_vp = 1; break; }
    case OP_DEPTH_RANGE: { const p_depth_range *b = a; d->dr[0] = b->n; d->dr[1] = b->f; break; }
    case OP_DEPTH_CLAMP: d->depth_clamp = ((const p_depth_clamp *)a)->on; break;
    case OP_VP_SWIZZLE: { const p_vp_swizzle *b = a; if (b->first >= 0 && b->first + b->n <= 16) memcpy(d->vp_sw[b->first], b->sw, 4 * (size_t)b->n); break; }
    case OP_BLEND_COLOR: memcpy(d->blend_color, ((const p_blend_color *)a)->rgba, 16); break;
    case OP_ALPHA_REF: d->alpha_ref = ((const p_alpha_ref *)a)->ref; break;
    case OP_PUSH_CONST: { const p_push_const *b = a; if ((uint32_t)b->offset + b->size <= DMSH_PUSH_SIZE) { memcpy(d->b.push[b->compute ? 1 : 0] + b->offset, b->data, b->size); d->s_push = state_stamp(); } break; }
    case OP_TF_BIND: break;
    case OP_TF_STATE: { const p_tf_state *b = a; d->tf_on = b->what == 0 || b->what == 3; break; }
    case OP_PRIM_RESTART: d->restart = *(const p_prim_restart *)a; break;
    case OP_RAST_DISCARD: d->rast_discard = ((const p_rast_discard *)a)->on; break;
    default: return 0;
    }
    return 1;
}

// ---------- Static buffers: zeros, a write sink, the support buffer ----------
static vka_span g_zero, g_sink, g_support;
static int statics(void) {
    static int ok = -1; if (ok >= 0) return ok;
    ok = vka_static(65536, V.ub_align > V.sb_align ? V.ub_align : V.sb_align, &g_zero) && vka_static(65536, V.sb_align, &g_sink) && vka_static(VKA_SUPPORT_SIZE, V.ub_align, &g_support);
    if (ok) { memset(g_zero.ptr, 0, 65536); memset(g_sink.ptr, 0, 65536); vka_support_fill(g_support.ptr, VKA_SUPPORT_SIZE); }
    return ok;
}

// ---------- Descriptor sets that do not fit a push (per submission slot) ----------
enum { NSLOT = 8, MAXPOOLS = 64 };
static VkDescriptorPool g_dp[NSLOT][MAXPOOLS]; static int g_ndp[NSLOT], g_cur_dp[NSLOT];
void vka_dyn_invalidate(void);
static void drv_memo_reset(void);
void vka_draw_sub_begin(VkCommandBuffer cb, unsigned slot) {
    vka_dispatch_overlap_flush(); // never carry an outstanding compute dependency to a new command buffer
    g_cb = cb; g_slot = slot % NSLOT; vka_dyn_invalidate();
    { void vka_mem_rec_thread(void); vka_mem_rec_thread(); }   // the address lookups' cache outside TLS for the recording thread (vka_mem.c)
    drv_memo_reset();   // the last submission's scratch spans go with its fence
    g_prof = VKA_ENV("DM_VK_PROF", 0) != 0; g_dyn_filter = VKA_ENV("DM_VK_DYN_FILTER", 1); g_pass_keep = VKA_ENV("DM_VK_PASS_KEEP", 1); g_vb_filter = VKA_ENV("DM_VK_VB_FILTER", 1);   // live: from this submission
    g_vin_skip = VKA_ENV("DM_VK_VIN_SKIP", 1);
    for (int i = 0; i < g_ndp[g_slot]; i++) vk.vkResetDescriptorPool(V.dev, g_dp[g_slot][i], 0);   // the slot's last submission is done (mtl_sub_begin waited for it)
    g_cur_dp[g_slot] = 0;
    vka_pso_save(0);
    static int ph; VkImageView placeholder(uint8_t dim, int storage);
    if (!V.null_desc && !ph && statics()) {   // no null descriptors: the placeholders are made here, outside any pass (their first use records a clear)
        ph = 1; static const uint8_t dims[] = {1, 2, 3, 1 | DMSH_VK_DIM_ARRAY, 3 | DMSH_VK_DIM_ARRAY};
        for (size_t i = 0; i < sizeof dims; i++) for (int c = 0; c < 3; c++) placeholder(dims[i] | (c == 1 ? DMSH_VK_DIM_SINT : c == 2 ? DMSH_VK_DIM_UINT : 0), 0);
    }
}
static VkDescriptorSet set_alloc(VkDescriptorSetLayout l) {
    for (;;) {
        int i = g_cur_dp[g_slot];
        if (i == g_ndp[g_slot]) {
            if (i == MAXPOOLS) { VRED_ONCE("descriptor pools exhausted in one submission"); return VK_NULL_HANDLE; }
            VkDescriptorPoolSize ps[] = {{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 8192}, {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2048}, {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 8192},
                                         {VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1024}, {VK_DESCRIPTOR_TYPE_SAMPLER, 1024}, {VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1024},
                                         {VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER, 256}, {VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER, 256}};
            VkDescriptorPoolCreateInfo pi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1024, .poolSizeCount = sizeof ps / sizeof *ps, .pPoolSizes = ps};
            if (vk.vkCreateDescriptorPool(V.dev, &pi, NULL, &g_dp[g_slot][i])) { VRED_ONCE("descriptor pool not made"); return VK_NULL_HANDLE; }
            g_ndp[g_slot]++;
        }
        VkDescriptorSetAllocateInfo ai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = g_dp[g_slot][i], .descriptorSetCount = 1, .pSetLayouts = &l};
        VkDescriptorSet s; VkResult r = vk.vkAllocateDescriptorSets(V.dev, &ai, &s);
        if (!r) return s;
        if (r != VK_ERROR_OUT_OF_POOL_MEMORY && r != VK_ERROR_FRAGMENTED_POOL) { VRED_ONCE("vkAllocateDescriptorSets %d", r); return VK_NULL_HANDLE; }
        g_cur_dp[g_slot]++;
    }
}

// ---------- The render pass ----------
static uint64_t g_attachment_discards, g_attachment_loads_avoided, g_attachment_stores_avoided;
static uint32_t g_store_discard_colors;
static int g_store_discard_depth;
// Only for a new pass opened by this draw, immediately before a contiguous sequence
// of guest DiscardColor / DiscardDepthStencil records. Never applied to an open pass.
void vka_rp_predict_discard(uint32_t colors, int depth) {
    g_store_discard_colors = colors;
    g_store_discard_depth = depth != 0;
}
static struct {
    int on; VkRect2D area; uint32_t layers, samples;
    uint32_t ncolor; VkFormat cf[8]; uint8_t ckind[8]; VkFormat df, sf;
    vka_img *cim[8]; uint32_t clv[8], cl0[8]; int nci;   // the colour attachments (DM_VK_NANSCAN)
    p_set_rt rt; int has_rt;                             // the targets it was opened for: a later SET_RT of the same targets keeps it open
    uint32_t cnl[8], dnl; VkExtent2D cext[8], dext;      // each attachment's layers and level size (clears in the pass must cover what they would outside it)
    int swrite;                                          // a draw of the pass wrote memory (storage buffers or images, raw global stores, a geometry shader's claim)
    int awrite;                                          // an actual colour/depth/stencil write or clear occurred; depth-test-only occlusion passes stay read-only
    int bar_pending;                                     // a game barrier came inside the pass and was taken there (vka_rp_game_barrier): the draws after it are checked (bar_hazard)
} R;
// Clears waiting for the pass of their targets (vka_rp_clear), in order: the next draw over the same targets opens its pass with them (loadOp CLEAR, or vkCmdClearAttachments),
// anything else does them outside a pass first (pc_flush), as before
enum { NPC = 16 };
static struct { int n; p_set_rt rt; vka_pclear c[NPC]; } PC;
static void pc_flush(void) { int n = PC.n; PC.n = 0; for (int i = 0; i < n; i++) vka_clear_outside(&PC.c[i]); }
// The same targets: the same textures and the same views of them (field by field: the records' padding is not compared)
static int view_same(const view_t *a, const view_t *b) {
    return a->set_levels == b->set_levels && a->set_layers == b->set_layers && a->set_format == b->set_format && (!a->set_levels || (a->base_level == b->base_level && a->nlevels == b->nlevels)) &&
           (!a->set_layers || (a->min_layer == b->min_layer && a->nlayers == b->nlayers)) && (!a->set_format || a->format == b->format);
}
static int rt_same(const p_set_rt *a, int ha, const p_set_rt *b, int hb) {
    if (!ha || !hb) return !ha && !hb;
    if (a->n != b->n || a->depth != b->depth || !!a->has_dview != !!b->has_dview || (a->has_dview && !view_same(&a->dview, &b->dview))) return 0;
    for (int i = 0; i < a->n && i < 8; i++) {
        if (a->color[i] != b->color[i] || !!a->has_cview[i] != !!b->has_cview[i]) return 0;
        if (a->color[i] && a->has_cview[i] && !view_same(&a->cview[i], &b->cview[i])) return 0;
    }
    return 1;
}
// Game barriers (OP_BARRIER) that came with a pass open: taken inside it (DM_VK_BAR_KEEP), ended it at once, ended it later at a draw that needed it (bar_hazard)
static uint64_t g_bar_in, g_bar_kept, g_bar_late, g_bar_duplicate_avoided;
static uint64_t g_rp_scoped, g_rp_graphics, g_rp_full, g_rp_pending_attachment;
static uint64_t g_rp_readonly_barriers_avoided; // no attachment or shader writes; no producer to publish
static uint64_t g_rp_postub_barriers_saved;
static int g_rp_force_full; // OP_BARRIER has stricter guest-visible ordering than an ordinary pass transition
void vka_oq_pass_end(void), vka_oq_draw(void);   // vka_exec.c "Occlusion queries"
// A retained guest barrier need not close the graphics pass merely to
// apply a following inline uniform update: with no shader-memory writes,
// the barrier only orders rasterized attachment writes. The buffered update
// has its own snapshot and later draws use vka_ub_overlay, while every
// image/SSBO/vertex/indirect/opaque-memory alias still ends the pass before
// the draw. Pass-end flush still orders previous GPU readers before copies.
// Only Ocarina enables this expanded safe subset by default; disabling
// DM_VK_OOT_UB_AFTER_BARRIER=0 restores the earlier strict split behavior.
int vka_rp_bar_pending(void) { return R.on && R.bar_pending && !R.swrite; }
int vka_rp_can_defer_ub(uint64_t addr, uint64_t size) {
    if (!R.on || R.swrite || !VKA_ENV("DM_VK_UB_DEFER", 1) || !size) return 0;
    if (R.bar_pending &&
        !VKA_ENV("DM_VK_OOT_UB_AFTER_BARRIER",
                 !strcmp(DM_GAME_ID, "0400486024DEC000"))) return 0;
    // Never defer an update into a live render attachment. That would
    // otherwise overwrite an earlier graphics write at the delayed flush.
    if (R.has_rt) {
        for (int i = 0; i < R.rt.n && i < 8; i++) {
            const tex_t *t = R.rt.color[i];
            if (t && (!t->mem || !t->L.size ||
                (addr <= (uint64_t)(uintptr_t)t->mem ?
                (uint64_t)(uintptr_t)t->mem - addr < size :
                addr - (uint64_t)(uintptr_t)t->mem < t->L.size))) return 0;
        }
        const tex_t *t = R.rt.depth;
        if (t && (!t->mem || !t->L.size ||
            (addr <= (uint64_t)(uintptr_t)t->mem ?
            (uint64_t)(uintptr_t)t->mem - addr < size :
            addr - (uint64_t)(uintptr_t)t->mem < t->L.size))) return 0;
    }
    return 1;
}
void vka_rp_end(void) {
    int had_clears = PC.n != 0;
    if (PC.n) pc_flush();
    if (!R.on) return;
    // An NVN barrier retained INSIDE a pass does not automatically make its
    // eventual pass end an all-stages producer. A retained barrier is allowed
    // only when the prior draws had no shader memory writes (vka_rp_game_barrier).
    // If later draws add shader writes, R.swrite restores the full barrier.
    // Without shader writes only color/depth attachments were modified: an
    // attachment-write -> ALL_COMMANDS read/write barrier orders every next
    // consumer, even if this pass has a pending guest barrier. This is the
    // largest avoidable barrier class in Ocarina's heavy scenes.
    // Forced OP_BARRIER, external clears and diagnostics retain ALL_COMMANDS.
    int full = g_rp_force_full || had_clears || vka_nan_on();
    int pending_attachment = R.bar_pending && !full && !R.swrite;
    vka_oq_pass_end();   // an occlusion query active in the pass ends inside it
    // The sparse 683x384 scene profiler closes its final <16-draw interval
    // while this dynamic rendering pass is still active. It emits NO GPU
    // commands on ordinary frames and preserves all attachment contents.
    if (vka_gp_active) vka_gp_gfx_flush();
    if(g_classic_pass)vk.vkCmdEndRenderPass(g_cb);else vk.vkCmdEndRendering(g_cb);
    g_classic_pass=0;
    // vkCmdCopyBuffer is forbidden inside rendering. Flush any deferred
    // uniform writes after ending the pass, with a read->transfer dependency.
    // The draw-side shadow already held those values for in-pass consumers.
    const int postub = vka_ub_active();
    vka_ub_flush_pass();
    // The deferred-uniform flush performed an ALL_COMMANDS memory barrier
    // immediately after EndRendering, then published GPU copies through
    // TRANSFER -> ALL_COMMANDS barriers. No new draw writes occurred after
    // it. Repeating the render-pass barrier therefore orders no work.
    // Keep exact earlier dependencies for passes WITHOUT a deferred flush;
    // preserve the option to restore the prior behavior for A/B tests.
    const int reused = postub && !strcmp(DM_GAME_ID, "0400486024DEC000") &&
        VKA_ENV("DM_VK_OOT_POSTUB_BAR_DEDUP", 1);
    if (full || (R.swrite && VKA_ENV("DM_VK_OOT_FPS_BOOST", 0) <= 0)) {
        if (reused) g_rp_postub_barriers_saved++;
        else { g_rp_full++; vka_barrier(g_cb); }
    } else if (R.swrite) {
        if (reused) g_rp_postub_barriers_saved++;
        else { g_rp_graphics++; vka_graphics_write_barrier(g_cb); }
    } else if (!R.awrite && !R.bar_pending
               && !strcmp(DM_GAME_ID, "0400486024DEC000")
               && VKA_ENV("DM_VK_OOT_READONLY_PASS", 1)) {
        // A pure depth-test / sample-only pass has no colour/depth/stencil
        // OR shader-memory writer (R.swrite was handled above). Its reads
        // still need an EXECUTION dependency against later attachment or
        // transfer writes (WAR); omitting the entire pipeline barrier is
        // unsafe with dynamic rendering. Replace the attachment memory
        // flush with a graphics-read -> ALL_COMMANDS execution dependency.
        // No loadOp/attachment clear, stencil write, or explicit guest
        // barrier may take this path. =0 keeps the original memory barrier.
        vka_graphics_read_barrier(g_cb);
        g_rp_readonly_barriers_avoided++;
    } else {
        if (pending_attachment) g_rp_pending_attachment++;
        if (reused) g_rp_postub_barriers_saved++;
        else { g_rp_scoped++; vka_attachment_write_barrier(g_cb); }
    }
    R.on = 0; vka_tex_feedback(NULL, NULL, 0);
    if (vka_nan_on()) vka_nan_pass(g_cb, R.cim, R.clv, R.cl0, R.nci);
}
// OP_BARRIER used to end a render pass (emitting a full ALL_COMMANDS memory
// barrier) and immediately emit a second identical full memory barrier, without
// any Vulkan commands between. The second one orders no new writes. Reuse the
// first, but do not skip the explicit barrier if NaN diagnostics record further
// GPU work after the pass-end barrier, or if no pass was actually open.
int vka_rp_end_covers_barrier(void) {
    int covered = R.on && !vka_nan_on();
    // This path covers OP_BARRIER only because the pass end emits a FULL
    // barrier. Never use the attachment-only path to satisfy an NVN barrier.
    g_rp_force_full = 1;
    vka_rp_end();
    g_rp_force_full = 0;
    if (covered) g_bar_duplicate_avoided++;
    return covered;
}
static void rt_range(const vka_img *im, const view_t *v, int has_v, uint32_t *lv, uint32_t *l0, uint32_t *nl) {
    *lv = has_v && v->set_levels ? v->base_level : 0;
    *l0 = has_v && v->set_layers ? v->min_layer : 0;
    if (!vka_img_lv(im, lv)) { *lv = im->levels; *nl = 0; return; }   // a level the image leaves out (a sparse texture's unmapped levels)
    uint32_t all = vka_img_slices(im, *lv);
    *nl = has_v && v->set_layers && v->nlayers ? v->nlayers : all - (*l0 < all ? *l0 : 0);
    if (*l0 + *nl > all) *nl = *l0 < all ? all - *l0 : 0;
}
// Opens the pass over the bound targets: 0 = it cannot (no target can be an attachment), logged
// Decided at device startup: all pipelines and passes must agree.
int vka_classic_rp(void) {
    static int on=-1;
    if(on<0 && V.dev) {
        const char *e=getenv("DM_VK_CLASSIC_RP");
        int want=e && atoi(e)!=0;
        on=want && V.imageless;
        VLOG("cached classic render passes: %s (imageless=%d; DM_VK_CLASSIC_RP)",on ? "on" : "off",V.imageless);
    }
    return on>0;
}
#include "vka_renderpass_cache.h"
static int rp_begin(const p_set_rt *rt, int has_rt, const vka_dstate *d) {
    if (R.on) { if (!g_pass_keep || rt_same(rt, has_rt, &R.rt, R.has_rt)) return 1; vka_rp_end(); }   // a new SET_RT of other targets ends the pass at its first draw (exec does not)
    if (PC.n && !rt_same(rt, has_rt, &PC.rt, 1)) pc_flush();                             // clears of other targets: done before
    VkRenderingAttachmentInfo ca[8], da = {0}, sa; uint32_t w = UINT32_MAX, h = UINT32_MAX, layers = UINT32_MAX, samples = 0;
    vka_img *s_im[9]={0};uint32_t s_lv[9]={0},s_nl[9]={0};
    vka_img *fb_im[9]; uint32_t fb_lv[9]; int nfb = 0;   // the attachments' images and levels (vka_tex_feedback)
    memset(&R, 0, sizeof R);
    if (has_rt) R.rt = *rt; R.has_rt = has_rt;
    int n = has_rt ? (rt->n < 8 ? rt->n : 8) : 0;
    for (int i = 0; i < n; i++) {
        ca[i] = (VkRenderingAttachmentInfo){VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageLayout = VK_IMAGE_LAYOUT_GENERAL,
                                        .loadOp = VK_ATTACHMENT_LOAD_OP_LOAD,
                                        .storeOp = (g_store_discard_colors & (1u << i)) ? VK_ATTACHMENT_STORE_OP_DONT_CARE : VK_ATTACHMENT_STORE_OP_STORE};
        R.cf[i] = VK_FORMAT_UNDEFINED;
        const tex_t *t = rt->color[i]; if (!t) continue;
        vka_img *im = vka_tex_get(t, g_cb); vka_fmt f;
        if (!im || !vka_fmt_of(rt->has_cview[i] && rt->cview[i].set_format ? rt->cview[i].format : t->d.format, &f)) continue;
        if (!(im->usage & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT) || f.kind >= 3) { VRED_ONCE("colour target %d (format %#x) cannot be a Vulkan colour attachment: not drawn into", i, t->d.format); continue; }
        if (im->depth > 1 && !(im->usage & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)) continue;   // its slices are drawn into through 2D-array views (img_create)
        uint32_t lv, l0, nl; rt_range(im, &rt->cview[i], rt->has_cview[i], &lv, &l0, &nl);
        if (lv >= im->levels || !nl) continue;
        if (samples && im->samples != samples) { VRED_ONCE("colour targets of different sample counts"); continue; }
        vka_tex_own(im, g_cb);   // (a zero-shared image gets memory of its own before it is drawn into: no pass is open here)
        VkImageView v = vka_view(im, f.view, nl > 1 ? VK_IMAGE_VIEW_TYPE_2D_ARRAY : VK_IMAGE_VIEW_TYPE_2D, VK_IMAGE_ASPECT_COLOR_BIT, lv, 1, l0, nl, NULL);
        if (!v) continue;
        if (vka_img_discard_take(im, VK_IMAGE_ASPECT_COLOR_BIT, lv, l0, nl)) {
            ca[i].loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
            g_attachment_loads_avoided++;
        }
        if (ca[i].storeOp == VK_ATTACHMENT_STORE_OP_DONT_CARE) g_attachment_stores_avoided++;
        s_im[i]=im;s_lv[i]=lv;s_nl[i]=nl;
        ca[i].imageView = v; R.cf[i] = f.view; R.ckind[i] = f.kind; samples = im->samples; fb_im[nfb] = im; fb_lv[nfb++] = lv;
        R.cim[R.nci] = im; R.clv[R.nci] = lv; R.cl0[R.nci++] = l0;
        uint32_t lw = im->w >> lv ? im->w >> lv : 1, lh = im->h >> lv ? im->h >> lv : 1;
        R.cnl[i] = nl; R.cext[i] = (VkExtent2D){lw, lh};
        if (lw < w) w = lw; if (lh < h) h = lh; if (nl < layers) layers = nl;
        vka_img_written(im);
    }
    R.ncolor = (uint32_t)n;
    VkRenderingAttachmentInfo *dp = NULL, *sp = NULL;
    if (has_rt && rt->depth) {
        vka_img *im = vka_tex_get(rt->depth, g_cb);
        if (im && im->f.kind >= 3 && (im->usage & VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT) && (!samples || im->samples == samples)) {
            uint32_t lv, l0, nl; rt_range(im, &rt->dview, rt->has_dview, &lv, &l0, &nl);
            if (lv < im->levels && nl) vka_tex_own(im, g_cb);
            VkImageView v = lv < im->levels && nl ? vka_view(im, im->f.vk, nl > 1 ? VK_IMAGE_VIEW_TYPE_2D_ARRAY : VK_IMAGE_VIEW_TYPE_2D, im->aspect, lv, 1, l0, nl, NULL) : VK_NULL_HANDLE;
            if (v) {
                VkImageAspectFlags aspects = im->aspect & (VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT);
                int discarded = vka_img_discard_take(im, aspects, lv, l0, nl);
                da = (VkRenderingAttachmentInfo){VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageView = v, .imageLayout = VK_IMAGE_LAYOUT_GENERAL,
                                                  .loadOp = discarded ? VK_ATTACHMENT_LOAD_OP_DONT_CARE : VK_ATTACHMENT_LOAD_OP_LOAD,
                                                  .storeOp = g_store_discard_depth ? VK_ATTACHMENT_STORE_OP_DONT_CARE : VK_ATTACHMENT_STORE_OP_STORE};
                if (discarded) g_attachment_loads_avoided++;
                if (g_store_discard_depth) g_attachment_stores_avoided++;
                if (im->aspect & VK_IMAGE_ASPECT_DEPTH_BIT) { dp = &da; R.df = im->f.vk; }
                if (im->aspect & VK_IMAGE_ASPECT_STENCIL_BIT) { sp = &da; R.sf = im->f.vk; }
                s_im[8]=im;s_lv[8]=lv;s_nl[8]=nl;
                samples = im->samples; fb_im[nfb] = im; fb_lv[nfb++] = lv;
                uint32_t lw = im->w >> lv ? im->w >> lv : 1, lh = im->h >> lv ? im->h >> lv : 1;
                R.dnl = nl; R.dext = (VkExtent2D){lw, lh};
                if (lw < w) w = lw; if (lh < h) h = lh; if (nl < layers) layers = nl;
                vka_img_written(im);
            }
        } else if (im) VRED_ONCE("depth target (format %#x) cannot be a Vulkan depth attachment: drawn without depth", rt->depth->d.format);
    }
    if (w == UINT32_MAX) {   // no attachment at all (rasterizer discard, or targets Vulkan cannot take): the viewport's size, for side effects
        if (!d->has_vp) { VRED_ONCE("a draw with no render target and no viewport: skipped"); return 0; }
        w = (uint32_t)fabsf(d->vp[0][2]); h = (uint32_t)fabsf(d->vp[0][3]); if (!w) w = 1; if (!h) h = 1; layers = 1;
    }
    R.area = (VkRect2D){{0, 0}, {w, h}}; R.layers = layers; R.samples = samples ? samples : 1;
    // The pending clears of these targets (PC): loadOp CLEAR when one covers its attachment and the attachment is the render area, else vkCmdClearAttachments once the pass
    // begins when the rectangle is inside the render area and the attachment has the pass's layers, else outside before it begins
    int nlate = 0; vka_pclear *late[NPC];
    sa = da;
    for (int k = 0; k < PC.n; k++) {
        vka_pclear *c = &PC.c[k]; int ci = c->ci;
        int att = ci >= 0 ? ci < n && ca[ci].imageView && R.cnl[ci] == layers && R.cnl[ci] == c->nl
                          : R.dnl == layers && R.dnl == c->nl && (!(c->asp & VK_IMAGE_ASPECT_DEPTH_BIT) || dp) && (!(c->asp & VK_IMAGE_ASPECT_STENCIL_BIT) || sp);
        VkExtent2D e = ci >= 0 ? (ci < 8 ? R.cext[ci] : (VkExtent2D){0, 0}) : R.dext;
        int whole = att && !c->rc.offset.x && !c->rc.offset.y && c->rc.extent.width == w && c->rc.extent.height == h && e.width == w && e.height == h;
        int inarea = att && (uint32_t)c->rc.offset.x + c->rc.extent.width <= w && (uint32_t)c->rc.offset.y + c->rc.extent.height <= h;
        if (whole && !nlate) {   // (after a late one it would come first: late too)
            if (ci >= 0) { ca[ci].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR; ca[ci].clearValue = c->in; }
            else { if (c->asp & VK_IMAGE_ASPECT_DEPTH_BIT) { da.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR; da.clearValue.depthStencil.depth = c->in.depthStencil.depth; }
                   if (c->asp & VK_IMAGE_ASPECT_STENCIL_BIT) { sa.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR; sa.clearValue.depthStencil.stencil = c->in.depthStencil.stencil; } }
        } else if (inarea) late[nlate++] = c;
        else vka_clear_outside(c);
    }
    if (sp) sp = &sa;
    #undef INAREA
    #undef WHOLE
    vka_tex_feedback(fb_im, fb_lv, nfb);
    VkRenderingInfo ri = {VK_STRUCTURE_TYPE_RENDERING_INFO, .renderArea = R.area, .layerCount = layers, .colorAttachmentCount = (uint32_t)n, .pColorAttachments = ca,
                          .pDepthAttachment = dp, .pStencilAttachment = sp};
    if (vka_gp_active) {   // DM_VK_GPUPROF: what the pass is, for the step it ends
        char b[96]; size_t bn = (size_t)snprintf(b, sizeof b, "%ux%ux%u", w, h, layers);
        for (int i = 0; i < n && bn < sizeof b; i++) if (ca[i].imageView) bn += (size_t)snprintf(b + bn, sizeof b - bn, " c%d:%d%s", i, R.cf[i], ca[i].loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR ? "C" : "");
        if (dp || sp) snprintf(b + bn, bn < sizeof b ? sizeof b - bn : 0, " d:%d%s", R.df ? R.df : R.sf, (dp ? dp : sp)->loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR ? "C" : "");
        vka_gp_pass(b);
    }
    // A loadOp CLEAR is a real attachment write even if no subsequent draw
    // touches it. Late vkCmdClearAttachments is also an attachment writer.
    for (int i = 0; i < n; i++)
        if (ca[i].imageView && ca[i].loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) R.awrite = 1;
    if ((dp && dp->loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) ||
        (sp && sp->loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) || nlate)
        R.awrite = 1;
    g_classic_pass = 0;
    if (vka_classic_rp()) {   // DM_VK_CLASSIC_RP: the same pass as a VkRenderPass with an imageless framebuffer
        rpkey k; memset(&k, 0, sizeof k); fbkey fk; memset(&fk, 0, sizeof fk);
        VkImageView views[9]; VkClearValue cv[9]; uint32_t na = 0;
        k.n = (uint32_t)n; k.samples = samples;
        for (int i = 0; i < n; i++) {
            if (!ca[i].imageView) { k.cf[i] = VK_FORMAT_UNDEFINED; continue; }
            k.cf[i] = R.cf[i]; rp_operations(&k,(unsigned)i,&ca[i]);
            fk.a[na] = fb_att(s_im[i], s_lv[i], s_nl[i], R.cf[i]); views[na] = ca[i].imageView; cv[na++] = ca[i].clearValue;
        }
        if (dp || sp) {
            k.ds = R.df ? R.df : R.sf; k.d = dp != NULL; k.s = sp != NULL;
            if(dp)rp_operations(&k,8,dp);if(sp)rp_operations(&k,9,sp);
            fk.a[na] = fb_att(s_im[8], s_lv[8], s_nl[8], k.ds); views[na] = da.imageView;
            cv[na].depthStencil.depth = da.clearValue.depthStencil.depth; cv[na++].depthStencil.stencil = sa.clearValue.depthStencil.stencil;
        }
        VkRenderPass rp = rp_obtain(&k);
        fk.rp = rp; fk.w = w; fk.h = h; fk.layers = layers; fk.na = na;
        VkFramebuffer fb = rp ? fb_obtain(&fk) : VK_NULL_HANDLE;   // Never fall back to an incompatible dynamic pipeline.
        if (!fb) { VRED_ONCE("classic framebuffer unavailable: draw refused, no incompatible dynamic fallback"); return 0; }
        if (fb) {
            VkRenderPassAttachmentBeginInfo ab = {VK_STRUCTURE_TYPE_RENDER_PASS_ATTACHMENT_BEGIN_INFO, NULL, na, views};
            VkRenderPassBeginInfo rb = {VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .pNext = na ? &ab : NULL, .renderPass = rp, .framebuffer = fb, .renderArea = R.area, .clearValueCount = na, .pClearValues = cv};
            vk.vkCmdBeginRenderPass(g_cb, &rb, VK_SUBPASS_CONTENTS_INLINE); g_classic_pass = 1;
        }
    }
    if(!g_classic_pass)vk.vkCmdBeginRendering(g_cb, &ri);
    R.on = 1; vka_n_rp++; if (g_dyn_filter == 2) vka_dyn_invalidate();   // DM_VK_DYN_FILTER=2: the dynamic state set again at each pass (bisect)
    for (int k = 0; k < nlate; k++) { VkClearAttachment c = {late[k]->asp, late[k]->ci >= 0 ? (uint32_t)late[k]->ci : 0, late[k]->in}; VkClearRect cr = {late[k]->rc, 0, layers}; vk.vkCmdClearAttachments(g_cb, 1, &c, 1, &cr); }
    PC.n = 0;
    return 1;
}
int vka_pass_keep(void) { return g_pass_keep; }
// A game barrier (nvnCommandBufferBarrier) with a draw pass open. NVN orders the work before it against the work after it (ORDER_PRIMITIVES / ORDER_FRAGMENTS, the cache
// invalidations); the replay used to end the pass there and record a full barrier, so every barrier between draws into the same targets cost a pass end, a store and a
// load of every attachment on a tiler (the next draw reopens it with LOAD). Inside a pass Vulkan already keeps the attachment writes of draws in rasterization order, so
// what a barrier between two draws of one pass can order is: memory the earlier draws wrote with shader stores (the pass then ends at once, as nvn_mtl.m's OP_BARRIER
// does for a pass with shader writes), and an attachment of the pass that a later draw samples (a feedback read: the pass ends before that draw, bar_hazard). Everything
// else the draws read was written before the pass began, behind the barrier that ended what wrote it. DM_VK_BAR_KEEP=1 takes such barriers inside the pass (live;
// default 0 for all other games; Ocarina's launcher enables it for a phone
// A/B with an env.txt fallback to 0. Alias views of attachment guest memory
// are also checked by vka_tex_id_in_pass; the counts in replay statistics
// show how many passes and loads/stores were avoided.
int vka_rp_game_barrier(uint32_t bits) {
    (void)bits;
    if (!R.on) return 0;
    g_bar_in++;
    if (R.swrite || !VKA_ENV("DM_VK_BAR_KEEP", 0)) return 0;
    R.bar_pending = 1; g_bar_kept++;
    return 1;
}
void vka_rp_bar_stats(char *b, size_t n, double frames) {
    static uint64_t i0, k0, l0, d0, a0, s0, dup0, scoped0, graphics0, full0, pending0, reused0, ro0;
    if (frames <= 0) { if (n) b[0] = 0; return; }
    if (g_bar_in != i0 || g_attachment_discards != d0 || g_attachment_loads_avoided != a0 || g_attachment_stores_avoided != s0 || g_bar_duplicate_avoided != dup0 || g_rp_scoped != scoped0 || g_rp_graphics != graphics0 || g_rp_full != full0 || g_rp_postub_barriers_saved != reused0 || g_rp_readonly_barriers_avoided != ro0)
        snprintf(b, n, "game barriers inside a draw pass per frame: %.1f, %.1f kept, %.1f ended later; redundant full barriers avoided %.1f/frame; pass-end barriers: %.1f attachment-scoped, %.1f graphics-shader-scoped, %.1f full/frame; pending-attachment scoped %.1f/frame; redundant post-uniform barriers removed %.1f/frame; read-only passes using execution-only dependency %.1f/frame; explicit attachment discards %.1f/frame, loads avoided %.1f/frame, stores avoided %.1f/frame",
                 (g_bar_in - i0) / frames, (g_bar_kept - k0) / frames, (g_bar_late - l0) / frames,
                 (g_bar_duplicate_avoided - dup0) / frames,
                 (g_rp_scoped - scoped0) / frames, (g_rp_graphics - graphics0) / frames, (g_rp_full - full0) / frames, (g_rp_pending_attachment - pending0) / frames, (g_rp_postub_barriers_saved - reused0) / frames, (g_rp_readonly_barriers_avoided - ro0) / frames,
                 (g_attachment_discards - d0) / frames, (g_attachment_loads_avoided - a0) / frames, (g_attachment_stores_avoided - s0) / frames);
    else if (n) b[0] = 0;
    i0 = g_bar_in; k0 = g_bar_kept; l0 = g_bar_late; dup0 = g_bar_duplicate_avoided; scoped0 = g_rp_scoped; graphics0 = g_rp_graphics; full0 = g_rp_full; pending0 = g_rp_pending_attachment; reused0 = g_rp_postub_barriers_saved; ro0 = g_rp_readonly_barriers_avoided;
    d0 = g_attachment_discards; a0 = g_attachment_loads_avoided; s0 = g_attachment_stores_avoided;
}
// A real NVN discard ends the current pass and invalidates precisely the bound
// image's view. A next pass may avoid the attachment LOAD; STORE is unchanged.
void vka_rp_discard(const p_set_rt *rt, int has_rt, int color_index) {
    if (!has_rt || !rt || color_index < -1 || color_index >= 8) return;
    const tex_t *t = color_index < 0 ? rt->depth : color_index < rt->n ? rt->color[color_index] : NULL;
    if (!t) return;
    if (R.on || PC.n) vka_rp_end();
    vka_img *im = vka_tex_acquire(t->serial);
    if (!im) return;
    const view_t *view = color_index < 0 ? &rt->dview : &rt->cview[color_index];
    int has_view = color_index < 0 ? rt->has_dview : rt->has_cview[color_index];
    uint32_t lv, l0, nl;
    rt_range(im, view, has_view, &lv, &l0, &nl);
    if (lv < im->levels && nl) {
        VkImageAspectFlags asp = color_index < 0 ? im->aspect & (VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT) : VK_IMAGE_ASPECT_COLOR_BIT;
        if (asp && (im->aspect & asp) == asp) {
            vka_img_discard_mark(im, asp, lv, l0, nl);
            g_attachment_discards++;
        }
    }
    vka_tex_drop(im);
}
int vka_rp_is_open(void) { return R.on; }
int vka_rp_open_for(const p_set_rt *rt, int has_rt) { return R.on && rt_same(rt, has_rt, &R.rt, R.has_rt); }
// The draw about to come may start a new part of the submission: no pass is open over its targets and no clear waits for them (an open pass over other targets ends at it anyway)
int vka_rp_split_ok(const p_set_rt *rt, int has_rt) { return R.on ? !rt_same(rt, has_rt, &R.rt, R.has_rt) : PC.n ? has_rt && !rt_same(rt, has_rt, &PC.rt, 1) : 1; }
void vka_draw_cb_switch(VkCommandBuffer cb) { vka_dispatch_overlap_flush(); g_cb = cb; vka_dyn_invalidate(); }   // the submission goes on in another command buffer (vka_exec.c chunk): its bound state is gone
// Before a clear of these targets records anything (vka_tex_get may record a first upload): a pass over other targets ends, pending clears of other targets are done
void vka_rp_prep_clear(const p_set_rt *rt, int has_rt) {
    if (R.on) { if (!rt_same(rt, has_rt, &R.rt, R.has_rt)) vka_rp_end(); }
    else if (PC.n && !rt_same(rt, has_rt, &PC.rt, 1)) pc_flush();
}
// A clear of one of the bound targets (colour index ci, or depth / stencil when ci < 0) inside the render pass: an open pass over the same targets takes it as
// vkCmdClearAttachments (rasterization-ordered with its draws), a closed one opens over them with it (loadOp CLEAR). 0 = not here: the caller ends the pass and clears outside.
// rc is in the attachment's level (the scissored part), nl the layers the clear names: they must be the attachment's own, within the render area
int vka_rp_clear(const p_set_rt *rt, int has_rt, const vka_dstate *d, const vka_pclear *c) {
    (void)d;
    if (!g_cb || !has_rt || !draws_on()) return 0;
    if (R.on && !rt_same(rt, has_rt, &R.rt, R.has_rt)) return 0;
    if (!R.on) {
        if (PC.n && (!rt_same(rt, has_rt, &PC.rt, 1) || PC.n == NPC)) pc_flush();
        if (!PC.n) PC.rt = *rt;
        PC.c[PC.n++] = *c;
        return 1;
    }
    int ci = c->ci; uint32_t nl = c->nl; VkRect2D rc = c->rc;
    if (ci >= 0 ? ci >= 8 || !R.cf[ci] || R.cnl[ci] != nl || nl != R.layers : ((c->asp & VK_IMAGE_ASPECT_DEPTH_BIT) && !R.df) || ((c->asp & VK_IMAGE_ASPECT_STENCIL_BIT) && !R.sf) || R.dnl != nl || nl != R.layers) return 0;
    if ((uint32_t)rc.offset.x + rc.extent.width > R.area.extent.width || (uint32_t)rc.offset.y + rc.extent.height > R.area.extent.height) return 0;
    VkClearAttachment ca = {c->asp, ci >= 0 ? (uint32_t)ci : 0, c->in}; VkClearRect cr = {rc, 0, nl};
    vk.vkCmdClearAttachments(g_cb, 1, &ca, 1, &cr);
    R.awrite = 1; // a clear is never a read-only occlusion pass
    return 1;
}

// ---------- Formats and fixed-function mappings ----------
// NVN vertex formats 0x01-0x30: four rows (1-4 components) of {UNORM8, SNORM8, UINT8, SINT8, FLOAT16, UNORM16, SNORM16, UINT16, SINT16, FLOAT32, UINT32, SINT32}
#define VF(n, s) VK_FORMAT_##n##_##s
static const VkFormat VROW[4][12] = {
    {VF(R8, UNORM), VF(R8, SNORM), VF(R8, UINT), VF(R8, SINT), VF(R16, SFLOAT), VF(R16, UNORM), VF(R16, SNORM), VF(R16, UINT), VF(R16, SINT), VF(R32, SFLOAT), VF(R32, UINT), VF(R32, SINT)},
    {VF(R8G8, UNORM), VF(R8G8, SNORM), VF(R8G8, UINT), VF(R8G8, SINT), VF(R16G16, SFLOAT), VF(R16G16, UNORM), VF(R16G16, SNORM), VF(R16G16, UINT), VF(R16G16, SINT), VF(R32G32, SFLOAT), VF(R32G32, UINT), VF(R32G32, SINT)},
    {VF(R8G8B8, UNORM), VF(R8G8B8, SNORM), VF(R8G8B8, UINT), VF(R8G8B8, SINT), VF(R16G16B16, SFLOAT), VF(R16G16B16, UNORM), VF(R16G16B16, SNORM), VF(R16G16B16, UINT), VF(R16G16B16, SINT), VF(R32G32B32, SFLOAT), VF(R32G32B32, UINT), VF(R32G32B32, SINT)},
    {VF(R8G8B8A8, UNORM), VF(R8G8B8A8, SNORM), VF(R8G8B8A8, UINT), VF(R8G8B8A8, SINT), VF(R16G16B16A16, SFLOAT), VF(R16G16B16A16, UNORM), VF(R16G16B16A16, SNORM), VF(R16G16B16A16, UINT), VF(R16G16B16A16, SINT), VF(R32G32B32A32, SFLOAT), VF(R32G32B32A32, UINT), VF(R32G32B32A32, SINT)},
};
static const VkFormat VSCALED[4][2][2] = {   // [components][8 / 16 bits][unsigned / signed]
    {{VF(R8, USCALED), VF(R8, SSCALED)}, {VF(R16, USCALED), VF(R16, SSCALED)}}, {{VF(R8G8, USCALED), VF(R8G8, SSCALED)}, {VF(R16G16, USCALED), VF(R16G16, SSCALED)}},
    {{VF(R8G8B8, USCALED), VF(R8G8B8, SSCALED)}, {VF(R16G16B16, USCALED), VF(R16G16B16, SSCALED)}}, {{VF(R8G8B8A8, USCALED), VF(R8G8B8A8, SSCALED)}, {VF(R16G16B16A16, USCALED), VF(R16G16B16A16, SSCALED)}}};
#undef VF
// The Vulkan format for NVN vertex format f whose shader input has class want (DMSH_VK_TYPE_*): the format's own when its class matches, else the same layout in that class
// (Vulkan wants the classes equal). An integer format into a float input keeps its own format and *retype says the input's class must change (DMSH_VK_TYPE_SINT / UINT):
// Maxwell's fetch puts the integer's bits in the register the shader bit-casts, so the vertex module is rewritten to declare that input as an integer vector (vka_spvpatch.c).
// VK_FORMAT_UNDEFINED = not mapped
static VkFormat vin_format(int f, int want, int *changed, int *retype) {
    *changed = 0; *retype = 0;
    int n = 0, col = -1;   // row (components) and column of VROW, or a scaled / packed format
    if (f >= 0x01 && f <= 0x30) { n = (f - 1) / 12 + 1; col = (f - 1) % 12; }
    else if (f >= 0x51 && f <= 0x68) {   // integers read as floats (nvn_mtl.m vconv_i2f): USCALED / SSCALED, none for 32 bits
        int i = (f - 0x51) >> 1, sg = (f - 0x51) & 1, bits = 8 << (i % 3); n = i / 3 + 1;
        if (bits < 32 && want == DMSH_VK_TYPE_FLOAT) return VSCALED[n - 1][bits == 16][sg];
        col = bits == 8 ? 2 + sg : bits == 16 ? 7 + sg : 10 + sg; *changed = want == DMSH_VK_TYPE_FLOAT;
        if (want == DMSH_VK_TYPE_FLOAT) return VROW[n - 1][col];
    } else {
        VkFormat p = f == 0x3D ? VK_FORMAT_A2B10G10R10_UNORM_PACK32 : f == 0x69 ? VK_FORMAT_A2B10G10R10_SNORM_PACK32 : f == 0x3F ? VK_FORMAT_B10G11R11_UFLOAT_PACK32 : f == 0x9A ? VK_FORMAT_B8G8R8A8_UNORM : VK_FORMAT_UNDEFINED;
        if (p && want != DMSH_VK_TYPE_FLOAT) { *changed = 1; return want == DMSH_VK_TYPE_UINT ? VK_FORMAT_R32_UINT : VK_FORMAT_R32_SINT; }
        return p;
    }
    static const int8_t cls[12] = {0, 0, 2, 1, 0, 0, 0, 2, 1, 0, 2, 1};   // DMSH_VK_TYPE_* of each column
    if (cls[col] == want) return VROW[n - 1][col];
    if (want == DMSH_VK_TYPE_FLOAT && retype) { *retype = cls[col]; return VROW[n - 1][col]; }
    *changed = 1;
    int bits = col < 4 ? 8 : col < 9 ? 16 : 32, sg = col == 1 || col == 3 || col == 6 || col == 8 || col == 11;
    if (want == DMSH_VK_TYPE_FLOAT) return bits < 32 ? VSCALED[n - 1][bits == 16][sg] : VROW[n - 1][9];
    int base = bits == 8 ? 2 : bits == 16 ? 7 : 10;   // the integer of the same width, in the class asked
    return VROW[n - 1][base + (want == DMSH_VK_TYPE_SINT)];
}
static VkBlendFactor bfac(int f) {
    switch (f) {
    case NVN_BLEND_FUNC_ZERO: return VK_BLEND_FACTOR_ZERO; case NVN_BLEND_FUNC_ONE: return VK_BLEND_FACTOR_ONE;
    case NVN_BLEND_FUNC_SRC_COLOR: return VK_BLEND_FACTOR_SRC_COLOR; case NVN_BLEND_FUNC_ONE_MINUS_SRC_COLOR: return VK_BLEND_FACTOR_ONE_MINUS_SRC_COLOR;
    case NVN_BLEND_FUNC_SRC_ALPHA: return VK_BLEND_FACTOR_SRC_ALPHA; case NVN_BLEND_FUNC_ONE_MINUS_SRC_ALPHA: return VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    case NVN_BLEND_FUNC_DST_ALPHA: return VK_BLEND_FACTOR_DST_ALPHA; case NVN_BLEND_FUNC_ONE_MINUS_DST_ALPHA: return VK_BLEND_FACTOR_ONE_MINUS_DST_ALPHA;
    case NVN_BLEND_FUNC_DST_COLOR: return VK_BLEND_FACTOR_DST_COLOR; case NVN_BLEND_FUNC_ONE_MINUS_DST_COLOR: return VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR;
    case NVN_BLEND_FUNC_SRC_ALPHA_SATURATE: return VK_BLEND_FACTOR_SRC_ALPHA_SATURATE;
    case NVN_BLEND_FUNC_SRC1_COLOR: return VK_BLEND_FACTOR_SRC1_COLOR; case NVN_BLEND_FUNC_ONE_MINUS_SRC1_COLOR: return VK_BLEND_FACTOR_ONE_MINUS_SRC1_COLOR;
    case NVN_BLEND_FUNC_SRC1_ALPHA: return VK_BLEND_FACTOR_SRC1_ALPHA; case NVN_BLEND_FUNC_ONE_MINUS_SRC1_ALPHA: return VK_BLEND_FACTOR_ONE_MINUS_SRC1_ALPHA;
    case NVN_BLEND_FUNC_CONSTANT_COLOR: return VK_BLEND_FACTOR_CONSTANT_COLOR; case NVN_BLEND_FUNC_ONE_MINUS_CONSTANT_COLOR: return VK_BLEND_FACTOR_ONE_MINUS_CONSTANT_COLOR;
    case NVN_BLEND_FUNC_CONSTANT_ALPHA: return VK_BLEND_FACTOR_CONSTANT_ALPHA; case NVN_BLEND_FUNC_ONE_MINUS_CONSTANT_ALPHA: return VK_BLEND_FACTOR_ONE_MINUS_CONSTANT_ALPHA;
    }
    return VK_BLEND_FACTOR_ONE;
}
static VkBlendOp bop(int e) { return e >= 1 && e <= 5 ? (VkBlendOp)(e - 1) : VK_BLEND_OP_ADD; }
static int is_src1(int f) { return f >= NVN_BLEND_FUNC_SRC1_COLOR && f <= NVN_BLEND_FUNC_ONE_MINUS_SRC1_ALPHA; }
static int zero_src1(int f) { return f == NVN_BLEND_FUNC_SRC1_COLOR || f == NVN_BLEND_FUNC_SRC1_ALPHA ? NVN_BLEND_FUNC_ZERO : f == NVN_BLEND_FUNC_ONE_MINUS_SRC1_COLOR || f == NVN_BLEND_FUNC_ONE_MINUS_SRC1_ALPHA ? NVN_BLEND_FUNC_ONE : f; }
// An advanced blend mode as fixed-function factors where one exists (nvn_mtl.m adv_blend: the Porter-Duff modes with uncorrelated overlap)
static blend_st adv_blend(blend_st b) {
    if (!b.adv) return b;
    enum { Z = NVN_BLEND_FUNC_ZERO, O = NVN_BLEND_FUNC_ONE, SA = NVN_BLEND_FUNC_SRC_ALPHA, ISA = NVN_BLEND_FUNC_ONE_MINUS_SRC_ALPHA, DA = NVN_BLEND_FUNC_DST_ALPHA, IDA = NVN_BLEND_FUNC_ONE_MINUS_DST_ALPHA };
    static const uint8_t pd[][4] = {
        [NVN_BLEND_ADVANCED_MODE_ZERO] = {Z, Z, Z, Z},        [NVN_BLEND_ADVANCED_MODE_SRC] = {O, Z, O, Z},           [NVN_BLEND_ADVANCED_MODE_DST] = {Z, O, Z, O},
        [NVN_BLEND_ADVANCED_MODE_SRC_OVER] = {O, ISA, O, ISA}, [NVN_BLEND_ADVANCED_MODE_DST_OVER] = {IDA, O, IDA, O},
        [NVN_BLEND_ADVANCED_MODE_SRC_IN] = {DA, Z, DA, Z},     [NVN_BLEND_ADVANCED_MODE_DST_IN] = {Z, SA, Z, SA},
        [NVN_BLEND_ADVANCED_MODE_SRC_OUT] = {IDA, Z, IDA, Z},  [NVN_BLEND_ADVANCED_MODE_DST_OUT] = {Z, ISA, Z, ISA},
        [NVN_BLEND_ADVANCED_MODE_SRC_ATOP] = {DA, ISA, Z, O},  [NVN_BLEND_ADVANCED_MODE_DST_ATOP] = {IDA, SA, O, Z},
        [NVN_BLEND_ADVANCED_MODE_XOR] = {IDA, ISA, IDA, ISA},  [NVN_BLEND_ADVANCED_MODE_PLUS] = {O, O, O, O},
        [NVN_BLEND_ADVANCED_MODE_PLUS_CLAMPED] = {O, O, O, O}, [NVN_BLEND_ADVANCED_MODE_PLUS_CLAMPED_ALPHA] = {O, O, O, O},
    };
    const uint8_t *f = b.adv < sizeof pd / sizeof *pd && pd[b.adv][0] ? pd[b.adv] : NULL;
    if (!f || b.adv_ovl || (b.adv_npm && f[0] != O && f[0] != Z)) { VRED_ONCE("advanced blend mode %#x has no fixed-function equivalent: the state's blend functions are used", (unsigned)b.adv); return b; }
    b.src_rgb = b.adv_npm && f[0] == O ? SA : f[0]; b.dst_rgb = f[1]; b.src_a = f[2]; b.dst_a = f[3];
    b.eq_rgb = b.eq_a = NVN_BLEND_EQUATION_ADD;
    return b;
}
// NVN primitive → Vulkan topology; *expand: 1 quads, 2 line loop (indices made on the CPU), 0 none; -1 = not drawable
static VkPrimitiveTopology topology(int prim, int *expand) {
    *expand = 0;
    switch (prim) {
    case NVN_DRAW_PRIMITIVE_POINTS: return VK_PRIMITIVE_TOPOLOGY_POINT_LIST;
    case NVN_DRAW_PRIMITIVE_LINES: return VK_PRIMITIVE_TOPOLOGY_LINE_LIST;
    case NVN_DRAW_PRIMITIVE_LINE_LOOP: *expand = 2; return VK_PRIMITIVE_TOPOLOGY_LINE_STRIP;
    case NVN_DRAW_PRIMITIVE_LINE_STRIP: return VK_PRIMITIVE_TOPOLOGY_LINE_STRIP;
    case NVN_DRAW_PRIMITIVE_TRIANGLES: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    case NVN_DRAW_PRIMITIVE_TRIANGLE_STRIP: case NVN_DRAW_PRIMITIVE_QUAD_STRIP: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;   // a quad strip rasterizes as the triangle strip of its vertices
    case NVN_DRAW_PRIMITIVE_TRIANGLE_FAN: case NVN_DRAW_PRIMITIVE_POLYGON: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_FAN;
    case NVN_DRAW_PRIMITIVE_QUADS: *expand = 1; return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    case NVN_DRAW_PRIMITIVE_LINES_ADJACENCY: return VK_PRIMITIVE_TOPOLOGY_LINE_LIST_WITH_ADJACENCY;
    case NVN_DRAW_PRIMITIVE_LINE_STRIP_ADJACENCY: return VK_PRIMITIVE_TOPOLOGY_LINE_STRIP_WITH_ADJACENCY;
    case NVN_DRAW_PRIMITIVE_TRIANGLES_ADJACENCY: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST_WITH_ADJACENCY;
    case NVN_DRAW_PRIMITIVE_TRIANGLE_STRIP_ADJACENCY: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP_WITH_ADJACENCY;
    case NVN_DRAW_PRIMITIVE_PATCHES: return VK_PRIMITIVE_TOPOLOGY_PATCH_LIST;
    }
    *expand = -1; return VK_PRIMITIVE_TOPOLOGY_POINT_LIST;
}
static VkPrimitiveTopology topo_class(VkPrimitiveTopology t) {   // the pipeline's topology: one of each class, the draw sets its own dynamically
    switch (t) {
    case VK_PRIMITIVE_TOPOLOGY_POINT_LIST: return t;
    case VK_PRIMITIVE_TOPOLOGY_LINE_LIST: case VK_PRIMITIVE_TOPOLOGY_LINE_STRIP: case VK_PRIMITIVE_TOPOLOGY_LINE_LIST_WITH_ADJACENCY: case VK_PRIMITIVE_TOPOLOGY_LINE_STRIP_WITH_ADJACENCY: return VK_PRIMITIVE_TOPOLOGY_LINE_LIST;
    case VK_PRIMITIVE_TOPOLOGY_PATCH_LIST: return t;
    default: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    }
}

// ---------- Guest memory as descriptors ----------
static int cpu_read(uint64_t addr, void *out, size_t n) {   // guest bytes as the CPU sees them now
    if (vka_addr(addr, n, NULL, NULL, NULL)) { memcpy(out, (const void *)(uintptr_t)addr, n); return 1; }
    return !plat_mem_read(addr, out, n);
}
static int rd_cb(void *ctx, uint64_t addr, void *out, size_t n) { (void)ctx; return cpu_read(addr, out, n); }
// A uniform buffer: bound in place when Vulkan's offset alignment allows, else a copy of what the CPU sees now (a GPU write earlier in this submission is missed: logged)
static int ubo_desc(uint64_t addr, uint64_t size, VkDescriptorBufferInfo *bi) {
    if (!size || size > V.ub_range) size = size ? V.ub_range : 65536 < V.ub_range ? 65536 : V.ub_range;
    if (vka_ub_pending_overlap(addr, size)) {
        // Reuse one scratch snapshot for unchanged deferred-write state.
        // The scratch allocation survives until the submission fence.
        static struct {uint64_t addr, size, seq; vka_span s;} memo[32];
        static uint32_t slot;
        uint64_t seq = vka_ub_seq();
        for (int i = 0; i < 32; i++) if (memo[i].seq == seq &&
            memo[i].addr == addr && memo[i].size == size) {
            *bi = (VkDescriptorBufferInfo){memo[i].s.buf, memo[i].s.off, size};
            return 1;
        }
        vka_span s;
        if (!vka_scratch(size, V.ub_align, &s)) return 0;
        if (!vka_tex_gw_shadow_read(addr, s.ptr, size)) {
            // A draw hazard should have ended the pass before this point;
            // fail closed rather than bind old bytes if an opaque GPU write
            // became visible while preparing descriptors.
            VRED_ONCE("deferred uniform shadow cannot read a pending opaque GPU write");
            return 0;
        }
        vka_ub_overlay(addr, s.ptr, size);
        memo[slot++ & 31u] = (typeof(memo[0])){addr, size, seq, s};
        *bi = (VkDescriptorBufferInfo){s.buf, s.off, size};
        return 1;
    }
    VkBuffer b; VkDeviceSize o;
    uint64_t run = vka_addr_run(addr, size, &b, &o);
    if (run && !(o % V.ub_align) && !(addr % V.ub_align)) { *bi = (VkDescriptorBufferInfo){b, o, run}; return 1; }
    vka_span s; if (!vka_scratch(size, V.ub_align, &s)) return 0;
    if (!cpu_read(addr, s.ptr, size)) { memset(s.ptr, 0, size); VRED_ONCE("uniform buffer at %#llx is not readable: it reads zeros", (unsigned long long)addr); }
    else if (run) VRED_ONCE("uniform buffer at %#llx is not %llu-byte aligned: bound as a copy of the CPU's bytes", (unsigned long long)addr, (unsigned long long)V.ub_align);
    else VRED_ONCE("uniform buffer at %#llx is not in placed guest RAM: bound as a copy of the CPU's bytes", (unsigned long long)addr);
    *bi = (VkDescriptorBufferInfo){s.buf, s.off, size}; return 1;
}
static int ssbo_desc(uint64_t addr, uint64_t size, VkDescriptorBufferInfo *bi) {
    VkBuffer b; VkDeviceSize o;
    uint64_t run = vka_addr_run(addr, size ? size : V.sb_range, &b, &o);
    if (!run) { VRED_ONCE("storage buffer at %#llx is not in placed guest RAM: it is not bound", (unsigned long long)addr); return 0; }
    if (run > V.sb_range) run = V.sb_range;
    *bi = (VkDescriptorBufferInfo){b, o, run}; return 1;
}
// Driver segments (c0, c2, the push bank) and raw global memory's table, kept from the last draw of this submission that filled them: a draw whose segment holds the same
// bytes binds the same scratch span (DM_VK_DRV_MEMO, live, default 1). Each draw used to fill a fresh 2.5 KB span per segment it reads (memset and fill into scratch, under
// the scratch lock: ~10 KB of writes a draw, ~80 MB a frame in DKB's level), so no two draws' pushes were ever the same and the push dedupe (push_same) never matched them.
// Graphics stages only: an indirect dispatch's counts are copied into its c0 by the GPU (vka_dispatch). A span lives until the submission's fence (vka_scratch_retire at
// its commit), so the memo is forgotten at each submission's start (vka_draw_sub_begin)
typedef struct { VkBuffer buf; VkDeviceSize off; } c0_at;
static struct { int valid; vka_span s; uint64_t k[3]; uint8_t b[DMSH_DRV_SIZE]; } g_dm[VKA_NSTAGE][3];
static struct { int valid; uint64_t gen; vka_span s; } g_gm;
static struct { int valid; uint32_t ref; vka_span s; } g_sm_ref;   // the support buffer with the alpha test's reference (stage_writes)
static int g_drv_memo = 1, g_drv_stamp = 1; static uint64_t g_dm_hit, g_dm_miss, g_dm_stamp;
static void drv_memo_reset(void) { for (int st = 0; st < VKA_NSTAGE; st++) for (int b = 0; b < 3; b++) g_dm[st][b].valid = 0; g_gm.valid = 0; g_sm_ref.valid = 0; g_drv_memo = VKA_ENV("DM_VK_DRV_MEMO", 1); g_drv_stamp = VKA_ENV("DM_VK_DRV_STAMP", 1); }
// Ported from Banana Native: these are ALL inputs read by vka_drv_fill
// for a graphics stage. Compute's GPU-patched c0 remains excluded below.
static void drv_key(const vka_dstate *d, int st, int bank, int pool, uint64_t k[3]) {
    if (bank == 0) { k[0] = d->s_ssbo[st]; k[1] = d->b.base_instance; k[2] = d->b.samples; }
    else if (bank == 1) { k[0] = d->s_tex[st]; k[1] = pool ? (uint64_t)(uint32_t)d->b.tex_base | (uint64_t)(uint32_t)d->b.samp_base << 32 : 0; k[2] = (uint64_t)(pool != 0); }
    else { k[0] = d->s_push; k[1] = k[2] = 0; }
}
static int drv_seg(const vka_dstate *d, int st, int bank, int pool, VkDescriptorBufferInfo *bi, c0_at *c0) {
    size_t sz = vka_drv_size(bank); vka_span s;
    // One memo slot per segment kind: c0, c2 and the push bank. Any other driver bank (an all-zero c17-style read of DMSH_DRV_SIZE bytes) takes the fill below: sharing
    // the push bank's slot, an all-zero push block matched it and the 0x100-byte span was bound with a 0xA00-byte range (other draws' scratch, or past the buffer)
    int bi_ = bank == 0 ? 0 : bank == 2 ? 1 : bank == DMSH_PUSH_BANK ? 2 : -1;
    if (g_drv_memo && bi_ >= 0 && st != 5 && sz <= DMSH_DRV_SIZE) {
        static uint8_t tmp[DMSH_DRV_SIZE];
        typeof(g_dm[0][0]) *m = &g_dm[st][bi_];
        uint64_t key[3]; drv_key(d, st, bi_, pool, key);
        if (g_drv_stamp && m->valid && !memcmp(m->k, key, sizeof key)) { g_dm_hit++; g_dm_stamp++; *bi = (VkDescriptorBufferInfo){m->s.buf, m->s.off, sz}; return 1; }
        vka_drv_fill(&d->b, st, bank, pool, tmp);
        if (m->valid && !memcmp(m->b, tmp, sz)) { memcpy(m->k, key, sizeof key); g_dm_hit++; *bi = (VkDescriptorBufferInfo){m->s.buf, m->s.off, sz}; return 1; }
        if (!vka_scratch(sz, V.ub_align, &s)) return 0;
        memcpy(s.ptr, tmp, sz); memcpy(m->b, tmp, sz); memcpy(m->k, key, sizeof key); m->s = s; m->valid = 1; g_dm_miss++;
        *bi = (VkDescriptorBufferInfo){s.buf, s.off, sz};
        return 1;
    }
    if (!vka_scratch(sz, V.ub_align, &s)) return 0;
    vka_drv_fill(&d->b, st, bank, pool, s.ptr);
    *bi = (VkDescriptorBufferInfo){s.buf, s.off, sz};
    if (bank == 0 && c0) { c0->buf = s.buf; c0->off = s.off; }
    return 1;
}
// Port of the iOS dynamic-GMEM capacity fix, without changing the guest ABI.
// The old v10.1 SPIR-V library still sees its first 4096 entries unchanged.
// New Ocarina shaders opt into a 13-step lookup that reaches entry 8191.
#define VKA_GMEM_MAP_ENTRIES 8192
// Raw global memory's table (dmsh_abi.h DMSH_GMEM_MAP_*): entry 0 empty, then the placed chunks by address with delta = device address - guest address, unused entries at ~0
// (kept while no segment comes or goes: vka_mem_gen, and DM_VK_DRV_MEMO)
uint64_t vka_mem_gen(void);
static int gmem_map(VkDescriptorBufferInfo *bi) {
    size_t n = (size_t)VKA_GMEM_MAP_ENTRIES * DMSH_GMEM_MAP_ENTRY;
    uint64_t gen = vka_mem_gen();
    if (g_drv_memo && g_gm.valid && g_gm.gen == gen) { *bi = (VkDescriptorBufferInfo){g_gm.s.buf, g_gm.s.off, n}; return 1; }
    vka_span s; if (!vka_scratch(n, V.sb_align, &s)) return 0;
    memset(s.ptr, 0xff, n); memset(s.ptr, 0, DMSH_GMEM_MAP_ENTRY);
    static uint64_t lo[VKA_GMEM_MAP_ENTRIES], hi[VKA_GMEM_MAP_ENTRIES], bda[VKA_GMEM_MAP_ENTRIES];
    int k = vka_mem_chunks(lo, hi, bda, VKA_GMEM_MAP_ENTRIES - 1);
    for (int i = 0; i < k && i + 1 < VKA_GMEM_MAP_ENTRIES; i++) { uint64_t e[4] = {lo[i], hi[i], bda[i] - lo[i], 0}; memcpy(s.ptr + (size_t)(i + 1) * DMSH_GMEM_MAP_ENTRY, e, sizeof e); }
    // V22 raw-memory lookup: use the unused final two uint32 words of each
    // 32-byte entry as a collision-checked 2 MiB guest-address hint table.
    // Only a chunk entirely inside one mapped segment is eligible. A hash
    // collision merely evicts a hint, never changes the primary range table.
    // Existing shader libraries ignore these formerly zero/padding words.
    // Entry 0 also keeps its required empty [0,0) primary range.
    uint32_t hint_count = 0;
    for (int i = 0; i < k && i + 1 < VKA_GMEM_MAP_ENTRIES; i++) {
        const uint64_t granule = UINT64_C(1) << 21, mask = granule - 1;
        uint64_t start = (lo[i] >> 21) + ((lo[i] & mask) != 0);
        uint64_t stop = hi[i] >> 21;  // exclusive: only complete chunks
        for (uint64_t tag = start; tag < stop && tag <= UINT32_MAX; tag++) {
            uint32_t h = (uint32_t)(tag & (VKA_GMEM_MAP_ENTRIES - 1));
            uint32_t hint[2] = {(uint32_t)tag, (uint32_t)(i + 1)};
            memcpy(s.ptr + (size_t)h * DMSH_GMEM_MAP_ENTRY + 24, hint, sizeof hint);
            hint_count++;
        }
    }
    static int hint_log_once;
    if (!hint_log_once && hint_count) { hint_log_once = 1;
        VLOG("raw GMEM: built %u tagged 2-MiB lookup hints for %d placed pool ranges (no guest shader ABI change)", hint_count, k);
    }
    g_gm.valid = 1; g_gm.gen = gen; g_gm.s = s;   // (a segment that came between the read of gen and the table: the next draw sees a new gen and builds it again)
    *bi = (VkDescriptorBufferInfo){s.buf, s.off, n}; return 1;
}
// A compute program's shared memory past the device's limit (DMSH_VK_KIND_SHARED_SPILL; Ryujinx StructuredIr/SharedSpillInfo.cs): one buffer for the process
// (DM_VK_SHARED_SPILL_MB, default 16 MiB, at least one slice), reused by every such dispatch: each dispatch ends with a barrier (vka_dispatch), so the next one finds it free.
// A dispatch binds slices for as many workgroups as it has, or as the buffer holds; workgroup w takes slice w mod the slices bound. A dispatch with more workgroups than
// that runs in parts (vkCmdDispatchBase, a barrier between them), each part's linear indices a contiguous run no longer than the slices, so no two workgroups that may run
// at once share a slice. An indirect dispatch's group count is known only on the GPU: it gets the whole buffer (open: correct while no two workgroups the buffer's slice
// count apart run at once, which in-order workgroup launch makes very likely but Vulkan does not promise)
static vka_span g_spill; static VkDeviceSize g_spill_cap, g_spill_range;
static uint32_t spill_bytes(const vka_shader *cs) {
    for (unsigned i = 0; i < cs->e->bind_count; i++) if (cs->b[i].kind == DMSH_VK_KIND_SHARED_SPILL) return cs->b[i].bytes;
    return 0;
}
static int spill_buf(uint32_t slice) {
    static int failed;
    if (!g_spill.buf && !failed) {   // made once, at the first such dispatch (one try: a failure is logged once and their dispatches are skipped)
        VkDeviceSize cap = (VkDeviceSize)VKA_ENV("DM_VK_SHARED_SPILL_MB", 16) << 20, lim = V.props.limits.maxStorageBufferRange;
        if (lim && cap > lim) cap = lim;
        if (cap < (VkDeviceSize)DMSH_VK_SHARED_MAX * 2) cap = (VkDeviceSize)DMSH_VK_SHARED_MAX * 2;   // at least one slice of any program the build moves (they declare under twice the limit)
        if ((lim && cap > lim) || !vka_static(cap, V.sb_align, &g_spill)) { failed = 1; g_spill.buf = VK_NULL_HANDLE; VRED("no shared memory spill buffer of %llu bytes", (unsigned long long)cap); return 0; }
        g_spill_cap = cap;
        VLOG("shared memory spill buffer: %llu KiB (%llu slices of the first program's %u bytes)", (unsigned long long)(cap >> 10), (unsigned long long)(cap / slice), slice);
    }
    return g_spill.buf && g_spill_cap >= slice;
}
static void spill_dispatch(uint32_t x, uint32_t y, uint32_t z, uint64_t ns) {
    int first = 1;
    #define PART(bx, by, bz, cx, cy, cz) do { if (!first) vka_barrier(g_cb); first = 0; vk.vkCmdDispatchBase(g_cb, bx, by, bz, cx, cy, cz); } while (0)
    #define MIN(a, b) ((a) < (b) ? (a) : (b))
    if ((uint64_t)x * y <= ns) { uint32_t c = (uint32_t)(ns / ((uint64_t)x * y)); for (uint32_t z0 = 0; z0 < z; z0 += c) PART(0, 0, z0, x, y, MIN(c, z - z0)); }
    else if (x <= ns) { uint32_t c = (uint32_t)(ns / x); for (uint32_t zz = 0; zz < z; zz++) for (uint32_t y0 = 0; y0 < y; y0 += c) PART(0, y0, zz, x, MIN(c, y - y0), 1); }
    else for (uint32_t zz = 0; zz < z; zz++) for (uint32_t yy = 0; yy < y; yy++) for (uint32_t x0 = 0; x0 < x; x0 += (uint32_t)ns) PART(x0, yy, zz, MIN((uint32_t)ns, x - x0), 1, 1);
    #undef PART
    #undef MIN
}
static int gmem_log(VkDescriptorBufferInfo *bi) {
    if (vka_tex_gml_take(bi)) return 1;   // read when the submission is done: the textures over the pages its stores wrote are uploaded again
    size_t n = ((size_t)1 + (1u << DMSH_GMEM_LOG_LOG2)) * 4;
    vka_span s; if (!vka_scratch(n, V.sb_align, &s)) return 0;
    memset(s.ptr, 0, n);
    *bi = (VkDescriptorBufferInfo){s.buf, s.off, n}; return 1;
}

// Placeholders for unbound images when the device has no null descriptors: 1x1 images of the shapes a shader may declare, zero (float, sint and uint views)
VkImageView placeholder(uint8_t dim, int storage) {
    static vka_img *im2, *im3, *im1; static VkImageView cache[3][7][3];
    int cls = dim & DMSH_VK_DIM_SINT ? 1 : dim & DMSH_VK_DIM_UINT ? 2 : 0, d = dim & DMSH_VK_DIM_MASK, a = (dim & DMSH_VK_DIM_ARRAY) != 0;
    if ((dim & DMSH_VK_DIM_MS) || d == 0) return VK_NULL_HANDLE;   // 1D shapes: the replay makes no 1D images (vka_tex.c img_create) and the translator declares none
    VkImageViewType vt = d == 0 ? (a ? VK_IMAGE_VIEW_TYPE_1D_ARRAY : VK_IMAGE_VIEW_TYPE_1D) : d == 2 ? VK_IMAGE_VIEW_TYPE_3D : d == 3 ? (a ? VK_IMAGE_VIEW_TYPE_CUBE_ARRAY : VK_IMAGE_VIEW_TYPE_CUBE) : a ? VK_IMAGE_VIEW_TYPE_2D_ARRAY : VK_IMAGE_VIEW_TYPE_2D;
    if (cache[storage][vt][cls]) return cache[storage][vt][cls];
    vka_img **pim = d == 2 ? &im3 : d == 0 ? &im1 : &im2;
    if (!*pim) {   // a texture of our own, made through the same path as the game's (zeroed at first use)
        static tex_t t[3]; tex_t *tt = &t[d == 2 ? 1 : d == 0 ? 2 : 0]; memset(tt, 0, sizeof *tt);
        tt->d.target = d == 2 ? NVN_TEXTURE_TARGET_3D : d == 0 ? NVN_TEXTURE_TARGET_1D_ARRAY : NVN_TEXTURE_TARGET_CUBEMAP_ARRAY; tt->d.format = NVN_FORMAT_RGBA8;
        tt->d.width = 1; tt->d.height = 1; tt->d.depth = d == 2 ? 1 : 6; tt->d.levels = 1; tt->d.flags = NVN_TEXTURE_FLAGS_IMAGE;
        nvn_tex_layout(&tt->d, &tt->L); tt->serial = nvn_new_serial();
        *pim = vka_tex_get(tt, g_cb);
        if (!*pim) return VK_NULL_HANDLE;
    }
    static const VkFormat f[3] = {VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_R8G8B8A8_SINT, VK_FORMAT_R8G8B8A8_UINT};
    uint32_t na = vt == VK_IMAGE_VIEW_TYPE_CUBE || vt == VK_IMAGE_VIEW_TYPE_CUBE_ARRAY ? 6 : vt == VK_IMAGE_VIEW_TYPE_2D_ARRAY || vt == VK_IMAGE_VIEW_TYPE_1D_ARRAY ? (*pim)->layers : 1;
    return cache[storage][vt][cls] = vka_view(*pim, f[cls], vt, VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, na, NULL);
}

// Where a draw's CPU time goes (DM_VK_PROF=1, logged with the replay statistics): the virtual counter at each phase boundary of vka_draw
static uint64_t g_pt_last, g_pt[9], g_ps[6]; static int g_pt_ph;
static inline uint64_t cntvct(void) { uint64_t v; __asm__ volatile("mrs %0, cntvct_el0" : "=r"(v)); return v; }
// ---------- Set 0 from the walk ----------
typedef struct { VkWriteDescriptorSet w[512]; VkDescriptorBufferInfo bi[512]; VkDescriptorImageInfo ii[512]; VkBufferView bv[512]; uint32_t n; } writes_t;
static writes_t g_w;
static vka_res g_res[512];   // the NaN scan's own walk (DM_VK_NANSCAN_FS)
// Formatted storage images (SULD.P / SUST.P) and sampled textures (TEX / TLD / TLD4) bound to integer textures. The translator declares their image a float one (of
// format Unknown); the hardware converts each texel by the bound descriptor's format, so an R32_UINT or R8_UINT texture hands the shader its integer values, while Vulkan
// takes no float image over a view of an integer format (id_view leaves the binding unbound: VUID-vkCmdDispatch-format-07752 / 07753). A dispatch whose walk binds an
// integer texture where the binding's dim names no sampled type (and no depth comparison) gets the module with that image retyped to the texture's class (a storage image
// also to its view's format; a sampled one keeps Unknown) (vka_shader_img_module, vka_spvpatch.c vka_spv_img_retype), the pipeline keyed by that choice (vka_pso.c
// ckey: a set 0 binding names one variable, storage or sampled), and stage_writes looks the view up with the retyped class. A binding whose array elements disagree, or
// that the module cannot have rewritten (a depth comparison on it), stays as it was (unbound, with its red line). A combined sampler over an integer view is the guest's
// nearest twin (stage_writes, vka_tex.c sampler_of: Vulkan filters no integer format). Compute only: graphics pipelines keep the float images (open). docs/reference/shaders.md "Formatted storage images bound to
// integer textures on the Vulkan replay". DM_VK_IMG_RETYPE=0 (live): never retyped, the earlier behaviour
static const vka_imgrt *g_rt5;   // the dispatch's retyped images while its set 0 is written (stage_writes, the compute stage)
static void img_retype_of(vka_shader *cs, const vka_res *r, int n, vka_imgrt *rt) {
    memset(rt, 0, sizeof *rt);
    if (!cs || n <= 0 || !VKA_ENV("DM_VK_IMG_RETYPE", 1)) return;
    uint32_t cand[VKA_IMGRT_MAX]; uint8_t dead[VKA_IMGRT_MAX] = {0}; int k = 0;   // each binding's choice (class 0: a float texture there); dead: its elements disagree
    for (int i = 0; i < n; i++) {
        int smp = r[i].desc == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER || r[i].desc == VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE;
        if (!(smp ? r[i].what == VKA_R_TEX : r[i].desc == VK_DESCRIPTOR_TYPE_STORAGE_IMAGE && r[i].what == VKA_R_IMG) || !r[i].tid
            || (r[i].dim & (DMSH_VK_DIM_SINT | DMSH_VK_DIM_UINT | DMSH_VK_DIM_DEPTH))) continue;
        uint8_t f = 0; int c = vka_tex_id_int_class(r[i].tid, &f);
        if (smp) f = 0;   // (a sampled image keeps format Unknown)
        // No null descriptors: a binding whose view is then refused gets placeholder()'s RGBA8 view of the retyped class, which a concrete declared format (R32ui) would not
        // match. Format Unknown takes either view (a read needs STORAGE_READ_WITHOUT_FORMAT for the format, as the float module's binding did)
        if (!V.null_desc) f = 0;
        // A format outside the basic storage set (R8ui, R8i, R16ui...) needs shaderStorageImageExtendedFormats: without it, Unknown (SPIR-V formats 21-24 and 30-33 are the basic ones)
        if (f && !V.ext_storage && !((f >= 21 && f <= 24) || (f >= 30 && f <= 33))) f = 0;
        uint32_t x = (uint32_t)r[i].binding << 16 | (uint32_t)f << 8 | (uint32_t)c;
        int j = 0; while (j < k && (cand[j] >> 16) != r[i].binding) j++;
        if (j == k) { if (k < VKA_IMGRT_MAX) cand[k++] = x; }
        else if (cand[j] != x) dead[j] = 1;
    }
    int m = 0;
    for (int j = 0; j < k; j++) if (!dead[j] && (cand[j] & 0xff)) {   // in binding order
        int at = m; while (at > 0 && (rt->b[at - 1] >> 16) > (cand[j] >> 16)) { rt->b[at] = rt->b[at - 1]; at--; }
        rt->b[at] = cand[j]; m++;
    }
    if (m && !vka_shader_img_retyped(cs, rt)) memset(rt, 0, sizeof *rt);   // not rewritten (logged once): the base module, those bindings unbound as before
}
static uint8_t rt_dim(uint16_t binding, uint8_t dim) {   // a storage or sampled binding's dim with the class img_retype_of gave its image
    if (g_rt5) for (int j = 0; j < VKA_IMGRT_MAX && g_rt5->b[j]; j++) if ((g_rt5->b[j] >> 16) == binding) return (uint8_t)(dim | ((g_rt5->b[j] & 0xff) == 1 ? DMSH_VK_DIM_UINT : DMSH_VK_DIM_SINT));
    return dim;
}
// One stage's results as descriptor writes. 0 = the draw cannot run (logged)
// Diagnostic (live through ctl, or nxreplay's environment): DM_VK_TEXSTAT_FS=<shader key, hex>, once per value: the textures the first draw or dispatch with that shader binds,
// each as the image its texture ID names when the draw is recorded, read back (level 0, layer 0) at the next frame boundary after the GPU is idle and summed up, with its
// sampler's registration and whether the view written into the descriptor is one of that image's views (vka_texstat_flush)
// DM_VK_TEXSTAT_AT=1 reads them right after that draw instead (the pass is ended and level 0, layer 0 copied out: what the draw sampled, and its targets with that draw's
// output, not what later work leaves in them), and also copies the uniform and storage buffers the draw binds, logged with a hash and written to DM_VK_TEXSTAT_DIR if set
#include "vka_capture.h"
typedef struct { int st, binding, tid, sid, own; uint8_t dim; VkImageView v; vka_img *im; uint64_t key; vcap_hbuf hb; size_t hbn; } texstat_t;
static texstat_t g_tst[32]; static int g_ntst; static uint64_t g_tst_done;
typedef struct { int st, binding, storage; uint64_t addr, size; vcap_hbuf hb; } texstat_buf;
static texstat_buf g_tsb[32]; static int g_ntsb, g_tst_at;   // g_tst_at: 1 = the noted draw's copies are still to be made (DM_VK_TEXSTAT_AT), 2 = made
vka_img *vka_tex_id_acquire(int id, VkImageView v, int *own_view);
void vka_samp_id_desc(int id, char *b, size_t n);
// DM_VK_TEXSTAT_ZB=<n> (diagnostic, once per value): every block-compressed texture sampled in the next frame (at most 1024 images), its level 0 layer 0 read back at the
// frame boundary and its all-zero blocks counted (an all-zero ASTC block is an error block, which the Adreno decodes as NaN); those with any are logged with the shader and
// binding that sampled them, then a summary
uint8_t *vcap_img_level0(vka_img *im, size_t *n);
typedef struct { vka_img *im; uint64_t key; int st, binding, tid; } zb_t;
static zb_t g_zb[1024]; static int g_nzb, g_zb_state; static double g_zb_was;
static void zb_note(const vka_shader *sh, int st, const vka_res *r) {
    static uint64_t fr = ~0ull; static int on;
    if (vka_frame() != fr) { fr = vka_frame(); double z = VKA_ENV("DM_VK_TEXSTAT_ZB", 0); on = 0;
        if (z != g_zb_was) { g_zb_was = z; g_zb_state = z ? 1 : 0; }
        if (g_zb_state == 1 && !g_nzb) { g_zb_state = 2; on = 1; } else if (g_zb_state == 2) g_zb_state = 3; }
    if (!on || g_nzb == 1024 || !sh || !(r->what == VKA_R_TEX) || !r->tid) return;
    int own; vka_img *im = vka_tex_id_acquire(r->tid, VK_NULL_HANDLE, &own);
    if (!im) return;
    if (im->f.bw <= 1) { vka_tex_drop(im); return; }
    for (int k = 0; k < g_nzb; k++) if (g_zb[k].im == im) { vka_tex_drop(im); return; }
    g_zb[g_nzb++] = (zb_t){im, sh->key, st, (int)r->binding, r->tid};
}
static void zb_flush(void) {
    if (!g_nzb || g_zb_state == 2) return;   // (the frame that takes them is not over)
    int with = 0; uint64_t zt = 0, bt = 0;
    for (int k = 0; k < g_nzb; k++) { zb_t *z = &g_zb[k]; size_t nb = 0; uint8_t *p = vcap_img_level0(z->im, &nb); uint32_t bpb = z->im->f.bpb ? z->im->f.bpb : 16; uint64_t nz = 0, n = 0;
        static const uint8_t zero[16];
        if (p) for (size_t o = 0; o + bpb <= nb; o += bpb) { n++; nz += !memcmp(p + o, zero, bpb < 16 ? bpb : 16); }
        free(p); zt += nz; bt += n;
        if (nz) { with++; VLOG("zero blocks: image of serial %llu %ux%u levels %u (base %u) VkFormat %d mode %d: %llu of %llu blocks of level 0 all zero; sampled by %016llx stage %d binding %d texture ID %d",
                               (unsigned long long)z->im->serial, z->im->w, z->im->h, z->im->levels, z->im->base, (int)z->im->f.vk, z->im->mode, (unsigned long long)nz, (unsigned long long)n, (unsigned long long)z->key, z->st, z->binding, z->tid); }
        vka_tex_drop(z->im); }
    VLOG("zero blocks: %d block-compressed images sampled in one frame, %d with all-zero blocks (%llu of %llu blocks)", g_nzb, with, (unsigned long long)zt, (unsigned long long)bt);
    g_nzb = 0;
}
void vka_texstat_flush(void);
void vka_texstat_flush_all(void) { if (g_zb_state == 2) g_zb_state = 3; vka_texstat_flush(); }   // (nxreplay: its one frame is over)
static void texstat_note(const vka_shader *sh, int st, const vka_res *r, VkImageView v) {
    static uint64_t fr = ~0ull, want, cur; static int taking;
    zb_note(sh, st, r);
    if (vka_frame() != fr) { fr = vka_frame(); const char *e = getenv("DM_VK_TEXSTAT_FS"); want = e && *e ? strtoull(e, NULL, 16) : 0; if (taking && cur != want) taking = 0; }
    if (!want || want == g_tst_done || !sh || sh->key != want) return;
    if (!taking) { if (g_ntst) return; taking = 1; cur = want; g_ntsb = 0; g_tst_at = VKA_ENV("DM_VK_TEXSTAT_AT", 0) != 0; }
    if (r->what == VKA_R_BUF && g_tst_at == 1 && g_ntsb < 32 && r->size) {   // (DM_VK_TEXSTAT_AT: the draw's buffers too)
        for (int k = 0; k < g_ntsb; k++) if (g_tsb[k].st == st && g_tsb[k].binding == (int)r->binding) return;
        g_tsb[g_ntsb++] = (texstat_buf){st, (int)r->binding, r->desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, r->addr, r->size}; return; }
    if (g_ntst == 32 || !(r->what == VKA_R_TEX || r->what == VKA_R_IMG) || !r->tid) return;
    for (int k = 0; k < g_ntst; k++) if (g_tst[k].st == st && g_tst[k].binding == (int)r->binding) { g_tst_done = want; taking = 0; return; }   // (the shader's next draw)
    texstat_t *t = &g_tst[g_ntst++]; *t = (texstat_t){st, (int)r->binding, r->tid, r->sid, 0, r->dim, v, NULL, want};
    t->im = vka_tex_id_acquire(r->tid, v, &t->own);
}
static void texstat_rt(const vka_shader *fs, const p_set_rt *rt, int has_rt) {   // the draw's colour targets (stage 9 in the lines)
    const char *e; uint64_t want;
    if (!fs || !has_rt || !rt || !g_ntst || !(e = getenv("DM_VK_TEXSTAT_FS")) || !(want = strtoull(e, NULL, 16)) || fs->key != want || g_tst[0].key != want) return;
    for (int k = 0; k < g_ntst; k++) if (g_tst[k].st == 9) return;
    for (int c = 0; c < rt->n && c < 8 && g_ntst < 32; c++) if (rt->color[c]) {
        texstat_t *t = &g_tst[g_ntst++]; *t = (texstat_t){9, c, 0, 0, 1, 0, VK_NULL_HANDLE, vka_tex_acquire(rt->color[c]->serial), want}; }
}
static void texstat_at(void) {   // DM_VK_TEXSTAT_AT, right after the noted draw or dispatch (vka_draw, vka_dispatch): its textures, targets and buffers copied out
    if (g_tst_at != 1 || !g_ntst || !g_cb) return;
    g_tst_at = 2; vka_rp_end();
    for (int k = 0; k < g_ntst; k++) { texstat_t *t = &g_tst[k]; cap_tsub *all; uint64_t total;
        if (!t->im || !t->im->inited || !vcap_subs(t->im, &all, &total)) continue;
        if (vcap_hbuf_make(&t->hb, all[0].bytes)) { vcap_img_copy(g_cb, t->im, &all[0], 1, t->hb.b, 0); t->hbn = (size_t)all[0].bytes; }
        free(all); }
    for (int k = 0; k < g_ntsb; k++) { texstat_buf *b = &g_tsb[k]; VkBuffer src; VkDeviceSize off;
        if (vka_addr_run(b->addr, b->size, &src, &off) < b->size || !vcap_hbuf_make(&b->hb, b->size)) { b->size = 0; continue; }
        VkBufferCopy c = {off, 0, b->size}; vka_barrier(g_cb); vk.vkCmdCopyBuffer(g_cb, src, b->hb.b, 1, &c); vka_barrier(g_cb); }
}
void vka_texstat_flush(void) {
    if (g_nzb && g_zb_state != 2) { mtl_finish(); zb_flush(); }
    if (!g_ntst) return;
    mtl_finish();
    for (int k = 0; k < g_ntst; k++) { texstat_t *t = &g_tst[k]; char sd[200] = ""; if (t->sid) vka_samp_id_desc(t->sid, sd, sizeof sd);
        char st_[520] = "no image"; vka_img *im = t->im; size_t nb = 0; uint8_t *p = NULL;
        if (t->hbn && (p = malloc(t->hbn))) { memcpy(p, t->hb.p, t->hbn); nb = t->hbn; } else if (im && !g_tst_at) p = vcap_img_level0(im, &nb);
        if (t->hb.b) vcap_hbuf_free(&t->hb);
        t->hbn = 0;
        if (p && nb) { uint32_t bpb = im->f.bpb ? im->f.bpb : 4; uint64_t lo = 0, hi = 0, cnt = 0, nlg = 0, nnan = 0, ninf = 0, hist[64] = {0}; double mn = 1e30, mx = -1e30, sum = 0, lg = 0;
            VkFormat vf = im->f.vk;
            for (size_t o = 0; o + bpb <= nb; o += bpb) { double x; uint32_t u;
                if (vf == VK_FORMAT_B10G11R11_UFLOAT_PACK32 || vf == VK_FORMAT_E5B9G9R9_UFLOAT_PACK32) {   // (the red channel)
                    memcpy(&u, p + o, 4);
                    if (vf == VK_FORMAT_E5B9G9R9_UFLOAT_PACK32) x = (u & 511) * exp2((int)(u >> 27) - 15 - 9);
                    else { uint32_t m = u & 63, e = (u >> 6) & 31; x = e == 0 ? m / 64.0 * exp2(-14) : e == 31 ? 65536.0 : (1 + m / 64.0) * exp2((int)e - 15); if (e == 31) { if (m) nnan++; else ninf++; } }
                    lo += x == 0; hi += x == 1; }
                else if (vf == VK_FORMAT_R16_SFLOAT || vf == VK_FORMAT_R16G16_SFLOAT || vf == VK_FORMAT_R16G16B16A16_SFLOAT) {
                    uint16_t h; memcpy(&h, p + o, 2); uint32_t e = (h >> 10) & 31, m = h & 1023; x = (e == 0 ? m / 1024.0 * exp2(-14) : e == 31 ? 65504.0 : (1 + m / 1024.0) * exp2((int)e - 15)) * (h >> 15 ? -1 : 1);
                    lo += x == 0; hi += x == 1; }
                else if (bpb == 2) { uint16_t h; memcpy(&h, p + o, 2); x = h / 65535.0; lo += h == 0; hi += h == 0xffff; }
                else if (bpb == 4 && (im->f.vk == VK_FORMAT_D32_SFLOAT || im->f.vk == VK_FORMAT_R32_SFLOAT || im->f.vk == VK_FORMAT_D32_SFLOAT_S8_UINT)) { float f; memcpy(&f, p + o, 4); x = f; lo += f == 0.f; hi += f == 1.f; }
                else if (bpb == 4 && im->f.kind >= 3) { memcpy(&u, p + o, 4); u &= 0xffffff; x = u / 16777215.0; lo += u == 0; hi += u == 0xffffff; }
                else { x = p[o] / 255.0; lo += p[o] == 0; hi += p[o] == 255; }
                cnt++; sum += x; if (x < mn) mn = x; if (x > mx) mx = x; if (x > 0 && x < 65000) { lg += log2(x); nlg++; int hb = (int)floor(log2(x)) + 32; hist[hb < 0 ? 0 : hb > 63 ? 63 : hb]++; } }
            int med = -99; { uint64_t acc = 0; for (int hb = 0; hb < 64; hb++) { acc += hist[hb]; if (acc * 2 >= nlg && nlg) { med = hb - 32; break; } } }
            snprintf(st_, sizeof st_, "%llu texels (component 0): %llu at 0, %llu at 1, %llu NaN, %llu infinite, range [%g, %g], mean %g, mean log2 of the finite positive ones %.2f, median in [2^%d, 2^%d)", (unsigned long long)cnt, (unsigned long long)lo, (unsigned long long)hi, (unsigned long long)nnan, (unsigned long long)ninf, mn, mx, cnt ? sum / cnt : 0, nlg ? lg / nlg : 0, med, med + 1); }
        free(p);
        { int vcap_img_nan_all(vka_img *im, uint64_t *nan, uint64_t *inf, uint64_t *texels); uint64_t a, b, c;
          if (im && !vcap_img_nan_all(im, &a, &b, &c)) { size_t l = strlen(st_); snprintf(st_ + l, sizeof st_ - l, "; all levels and layers (%u, %u): %llu NaN, %llu infinite of %llu texels", im->levels, im->layers,
                                                                (unsigned long long)a, (unsigned long long)b, (unsigned long long)c); } }
        VLOG("texstat %016llx stage %d binding %d texture ID %d (dim %#x): image of serial %llu %ux%u layers %u VkFormat %d, VkImage %p, view %p %s; %s; %s", (unsigned long long)t->key, t->st, t->binding, t->tid, t->dim,
             im ? (unsigned long long)im->serial : 0ull, im ? im->w : 0, im ? im->h : 0, im ? im->layers : 0, im ? (int)im->f.vk : 0, im ? (void *)im->img : NULL, (void *)t->v,
             t->own ? (g_tst_at ? "(one of its views; read at the draw)" : "(one of its views)") : "(NOT one of its views when recorded)", st_, sd);
        if (im) vka_tex_drop(im); }
    for (int k = 0; k < g_ntsb; k++) { texstat_buf *b = &g_tsb[k]; if (!b->hb.b) continue;
        uint64_t h = 0xcbf29ce484222325ull; for (uint64_t i = 0; i < b->size; i++) h = (h ^ b->hb.p[i]) * 0x100000001b3ull;
        const float *f = (const float *)b->hb.p; char fl[400]; size_t o = 0; for (uint64_t i = 0; i < 16 && 4 * i + 4 <= b->size; i++) o += (size_t)snprintf(fl + o, sizeof fl - o, " %g", f[i]);
        const char *dir = getenv("DM_VK_TEXSTAT_DIR"); char path[512] = "";
        if (dir && *dir) { snprintf(path, sizeof path, "%s/%016llx_s%d_b%d_%llx.bin", dir, (unsigned long long)g_tst[0].key, b->st, b->binding, (unsigned long long)b->addr);
                           FILE *fp = fopen(path, "wb"); if (fp) { fwrite(b->hb.p, 1, (size_t)b->size, fp); fclose(fp); } else path[0] = 0; }
        VLOG("texstat %016llx stage %d binding %d %s buffer %#llx+%#llx at the draw: hash %016llx, first floats%s%s%s", (unsigned long long)g_tst[0].key, b->st, b->binding, b->storage ? "storage" : "uniform",
             (unsigned long long)b->addr, (unsigned long long)b->size, (unsigned long long)h, fl, path[0] ? ", written to " : "", path);
        vcap_hbuf_free(&b->hb); }
    g_ntsb = 0; g_tst_at = 0;
    g_tst_done = g_tst[0].key; g_ntst = 0;
}
static int stage_writes(const vka_dstate *d, int st, const vka_shader *sh, const vka_res *r, int n, int pool, c0_at *c0) {
    for (int i = 0; i < n; i++) {
        if (g_w.n == 512) { VRED_ONCE("more than 512 descriptors in one draw"); return 0; }
        uint32_t k = g_w.n;
        VkWriteDescriptorSet *w = &g_w.w[k]; VkDescriptorBufferInfo *bi = &g_w.bi[k]; VkDescriptorImageInfo *ii = &g_w.ii[k];
        *w = (VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = r[i].binding, .dstArrayElement = r[i].elem, .descriptorCount = 1, .descriptorType = (VkDescriptorType)r[i].desc};
        int ok = 1;
        switch (r[i].desc) {
        case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER: case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER: {
            int storage = r[i].desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
            switch (r[i].what) {
            case VKA_R_BUF: ok = storage ? ssbo_desc(r[i].addr, r[i].size, bi) : ubo_desc(r[i].addr, r[i].size, bi);
                if (ok && storage && (r[i].flags & DMSH_VK_BF_RW)) vka_tex_gw_opaque(r[i].addr, bi->range);   // the shader may store into it
                break;
            case VKA_R_C1: if (sh->c1_len) *bi = (VkDescriptorBufferInfo){sh->c1.buf, sh->c1.off, (sh->c1_len + 15) & ~(VkDeviceSize)15}; else ok = 0; break;
            case VKA_R_SUPPORT:
                if (st == 1 && (sh->e->flags & DMSH_VK_F_ALPHA_TEST) && d->color.alpha_func && d->color.alpha_func != NVN_ALPHA_FUNC_ALWAYS) {   // word 0: the alpha test's reference
                    vka_span s;
                    if (g_drv_memo && g_sm_ref.valid && !memcmp(&g_sm_ref.ref, &d->alpha_ref, 4)) s = g_sm_ref.s;   // the same reference as the last alpha-tested draw: its copy (DM_VK_DRV_MEMO)
                    else { if (!vka_scratch(VKA_SUPPORT_SIZE, V.ub_align, &s)) return 0;
                           memcpy(s.ptr, g_support.ptr, VKA_SUPPORT_SIZE); memcpy(s.ptr, &d->alpha_ref, 4);
                           g_sm_ref.valid = 1; memcpy(&g_sm_ref.ref, &d->alpha_ref, 4); g_sm_ref.s = s; }
                    *bi = (VkDescriptorBufferInfo){s.buf, s.off, VKA_SUPPORT_SIZE};
                } else *bi = (VkDescriptorBufferInfo){g_support.buf, g_support.off, VKA_SUPPORT_SIZE};
                break;
            case VKA_R_DRV: { uint64_t td_ = g_prof ? cntvct() : 0;
                if (!drv_seg(d, st, r[i].bank, pool, bi, c0)) return 0;
                if (g_prof) g_ps[3] += cntvct() - td_;
                break; }
            case VKA_R_GMEM_MAP: ok = gmem_map(bi); break;
            case VKA_R_GMEM_LOG: ok = gmem_log(bi); break;
            case VKA_R_SHARED_SPILL: ok = st == 5 && g_spill_range && g_spill.buf; if (ok) *bi = (VkDescriptorBufferInfo){g_spill.buf, g_spill.off, g_spill_range}; break;
            default: ok = 0; break;
            }
            if (!ok) { if (V.null_desc) *bi = (VkDescriptorBufferInfo){VK_NULL_HANDLE, 0, VK_WHOLE_SIZE}; else *bi = (VkDescriptorBufferInfo){storage ? g_sink.buf : g_zero.buf, storage ? g_sink.off : g_zero.off, 65536}; }
            w->pBufferInfo = bi;
            if (r[i].what == VKA_R_BUF) texstat_note(sh, st, &r[i], VK_NULL_HANDLE);   // (DM_VK_TEXSTAT_AT: the draw's buffers)
            break; }
        case VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER: case VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE: case VK_DESCRIPTOR_TYPE_SAMPLER: case VK_DESCRIPTOR_TYPE_STORAGE_IMAGE: {
            int storage = r[i].desc == VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; uint64_t ti_ = g_prof ? cntvct() : 0;
            VkImageView v = VK_NULL_HANDLE; VkSampler s = VK_NULL_HANDLE; VkImageLayout lay = VK_IMAGE_LAYOUT_GENERAL;
            uint8_t dim = st == 5 ? rt_dim(r[i].binding, r[i].dim) : r[i].dim;   // (an image retyped for its integer texture: img_retype_of)
            if (r[i].desc != VK_DESCRIPTOR_TYPE_SAMPLER) {
                int tid = r[i].what == VKA_R_TEX || r[i].what == VKA_R_IMG ? r[i].tid : 0;
                if (tid) v = vka_tex_id_view_rec(tid, g_cb, dim, storage, &lay);
                // A 2D texture in a 3D or cube slot: what the game leaves bound where a shader's branch does not sample (DKB's materials keep a 1x1 2D texture in their volume slot 12).
                // It reads as unbound, zeros, as nvn_mtl.m's zero 3D / zero cube fallback does; noted once. Other mismatches are reported
                int dd = r[i].dim & DMSH_VK_DIM_MASK, tt = tid && !v ? vka_tex_id_target(tid) : -1;
                if (tid && !v && (dd == 2 || dd == 3) && (tt == NVN_TEXTURE_TARGET_2D || tt == NVN_TEXTURE_TARGET_2D_ARRAY)) {
                    static _Atomic int noted; if (!atomic_exchange(&noted, 1)) { char why[320]; vka_tex_id_desc(tid, why, sizeof why);
                        VLOG("%s binding fallback: shader %016llx binding %u, texture ID %d is a 2D texture (%s): it reads as zeros (the shader may leave it unused)", dd == 2 ? "3D" : "cube", (unsigned long long)sh->key, r[i].binding, tid, why); }
                } else if (tid && !v) { static _Atomic int nm; if (atomic_fetch_add(&nm, 1) < 8) { char why[320]; vka_tex_id_desc(tid, why, sizeof why);
                    VRED("shader %016llx binding %u: texture ID %d has no view of shape %#x%s: it reads as unbound (%s)", (unsigned long long)sh->key, r[i].binding, tid, dim, storage ? " (storage)" : "", why); } }
                if (!v && !V.null_desc) v = placeholder(dim, storage);
                if (!v && !V.null_desc) { VRED_ONCE("an unbound image of shape %#x and no null descriptors: the draw is skipped", dim); return 0; }
            }
            if (r[i].desc == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER || r[i].desc == VK_DESCRIPTOR_TYPE_SAMPLER) {
                // An integer view (a uint or sint binding: id_view gives one only to those) takes the sampler's nearest twin: Vulkan filters no integer format
                // (VUID-vkCmdDispatch-magFilter-04553 / mipmapMode-04770) and Ampere filters none either (vka_tex.c sampler_of). A separate sampler binding does not know its image
                s = r[i].sid ? vka_samp_id_rec(r[i].sid, r[i].desc == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER && (dim & (DMSH_VK_DIM_SINT | DMSH_VK_DIM_UINT))) : VK_NULL_HANDLE;
                if (!s) s = vka_samp_default();
            }
            *ii = (VkDescriptorImageInfo){s, v, lay};
            if (r[i].desc != VK_DESCRIPTOR_TYPE_SAMPLER) texstat_note(sh, st, &r[i], v);
            w->pImageInfo = ii; if (g_prof) { g_ps[4] += cntvct() - ti_; g_ps[5]++; }
            break; }
        case VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER: case VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER:
            if (r[i].what != VKA_R_NULL) VRED_ONCE("texel buffers are not on Vulkan yet (shader %016llx binding %u): bound as null", (unsigned long long)sh->key, r[i].binding);
            if (!V.null_desc) { VRED_ONCE("a texel buffer binding and no null descriptors: the draw is skipped"); return 0; }
            g_w.bv[k] = VK_NULL_HANDLE; w->pTexelBufferView = &g_w.bv[k];
            break;
        default: VRED_ONCE("descriptor type %u in a binding record", r[i].desc); return 0;
        }
        g_w.n++;
    }
    return 1;
}
// Each stage's bindings, walked once a draw or dispatch (walk_all): the images first used are made from them (make_images), then set 0 is written from them (bind_sets)
static struct { int n[VKA_NSTAGE], pool[VKA_NSTAGE]; char why[VKA_NSTAGE][200]; vka_res r[VKA_NSTAGE][512]; } g_wk;
static void walk_all(const vka_dstate *d, vka_shader *const sh[VKA_NSTAGE]) {
    uint64_t t0_ = g_prof ? cntvct() : 0;
    for (int st = 0; st < VKA_NSTAGE; st++) {
        vka_shader *s = sh[st]; g_wk.n[st] = 0; g_wk.pool[st] = 0; if (!s) continue;
        g_wk.n[st] = vka_walk(&d->b, st, s->e, s->b, s->lib->h->ssbo_align, V.sb_align, rd_cb, NULL, g_wk.r[st], 512, &g_wk.pool[st], g_wk.why[st], sizeof g_wk.why[st]);
    }
    if (g_prof) g_ps[0] += cntvct() - t0_;
}
// Writes set 0 from the walk (walk_all, just before) and binds it (and set 1 for shaders that read the pools). c0: where the compute stage's c0 went (an indirect dispatch copies its counts there)
// The last push descriptor set per bind point, as the words that decide it (layout, each write's binding, type and count, each descriptor's info): a draw whose writes
// are the same word for word skips its push (DM_VK_PUSH_DEDUP=0: every draw pushes). Pushed descriptors stay bound across draws and pipeline binds while the layout stays
// the same (Vulkan's pipeline layout compatibility); a new command buffer or a set bound in their place forgets them (vka_dyn_invalidate, bind_sets)
static struct { uint64_t *w; size_t n, cap; } g_pd[2];
static uint64_t g_pd_skip, g_pd_push, g_pd_skip_all, g_pd_push_all, g_pd_delta_w, g_pd_delta_all;
// The replay statistics' line: driver segments bound again (DM_VK_DRV_MEMO) and pushes skipped (DM_VK_PUSH_DEDUP) since the last line
void vka_drv_memo_stats(char *b, size_t n) {
    static uint64_t h0, m0, s0, p0, ds0, vk0, vb0, bk0, bb0;
    uint64_t h = g_dm_hit - h0, m = g_dm_miss - m0, sk = g_pd_skip_all - s0, pu = g_pd_push_all - p0;
    h0 = g_dm_hit; m0 = g_dm_miss; s0 = g_pd_skip_all; p0 = g_pd_push_all;
    uint64_t ds = g_dm_stamp - ds0, vk = g_vin_kept - vk0, vb = g_vin_built - vb0, bk = g_vb_kept - bk0, bb = g_vb_bound - bb0;
    ds0 = g_dm_stamp; vk0 = g_vin_kept; vb0 = g_vin_built; bk0 = g_vb_kept; bb0 = g_vb_bound;
    if (!h && !m && !sk && !pu) { if (n) b[0] = 0; return; }
    snprintf(b, n, "descriptors: driver segments %.0f %% the same bytes as the draw before (bound again: DM_VK_DRV_MEMO); push descriptor sets %.0f %% skipped as the same (DM_VK_PUSH_DEDUP); "
             "partial pushes (DM_VK_PUSH_DELTA) wrote %.0f %% of their descriptors; input stamps skipped %.0f %% of driver fills; vertex build/bind kept %.0f/%.0f %%", h + m ? 100.0 * h / (double)(h + m) : 0.0, sk + pu ? 100.0 * sk / (double)(sk + pu) : 0.0,
             g_pd_delta_all ? 100.0 * g_pd_delta_w / (double)g_pd_delta_all : 0.0, h + m ? 100.0 * ds / (double)(h + m) : 0.0,
             vk + vb ? 100.0 * vk / (double)(vk + vb) : 0.0, bk + bb ? 100.0 * bk / (double)(bk + bb) : 0.0);
    g_pd_delta_w = g_pd_delta_all = 0;
}
static VkWriteDescriptorSet g_dw[512]; static uint32_t g_dwn;   // the writes that changed (push_same returns 2)
static int push_same(VkPipelineBindPoint bp, VkPipelineLayout layout) {
    static uint64_t *buf; static size_t cap;
    size_t need = 2 + (size_t)g_w.n * 5, k = 0;
    if (need > cap) { cap = need * 2; buf = realloc(buf, cap * sizeof *buf); if (!buf) { cap = 0; return 0; } }
    buf[k++] = (uint64_t)layout; buf[k++] = g_w.n;
    for (uint32_t i = 0; i < g_w.n; i++) {
        const VkWriteDescriptorSet *w = &g_w.w[i];
        buf[k++] = (uint64_t)w->dstBinding | (uint64_t)w->dstArrayElement << 16 | (uint64_t)w->descriptorType << 32 | (uint64_t)w->descriptorCount << 48;
        if (w->descriptorCount != 1) return (g_pd[bp == VK_PIPELINE_BIND_POINT_COMPUTE].n = 0), 0;   // (the walk writes one descriptor per write)
        if (w->pBufferInfo) { buf[k++] = (uint64_t)w->pBufferInfo->buffer; buf[k++] = w->pBufferInfo->offset; buf[k++] = w->pBufferInfo->range; }
        else if (w->pImageInfo) { buf[k++] = (uint64_t)w->pImageInfo->sampler; buf[k++] = (uint64_t)w->pImageInfo->imageView; buf[k++] = w->pImageInfo->imageLayout; }
        else if (w->pTexelBufferView) { buf[k++] = (uint64_t)*w->pTexelBufferView; buf[k++] = 0; buf[k++] = 0; }
        else { buf[k++] = 1; buf[k++] = 1; buf[k++] = 1; }
    }
    int c = bp == VK_PIPELINE_BIND_POINT_COMPUTE;
    if (VKA_ENV("DM_VK_PUSH_DEDUP", 1) && g_pd[c].n == k && !memcmp(g_pd[c].w, buf, k * sizeof *buf)) { g_pd_skip++; g_pd_skip_all++; return 1; }
    // DM_VK_PUSH_DELTA=1 (default only for Ocarina; =0 restores full pushes): the same layout and the same writes in the same order as the last push, some of them with other descriptors:
    // only those are pushed. Vulkan lets push descriptors be updated incrementally; the others stay as the last push left them (until the set is disturbed: a new command
    // buffer or part, a set bound in its place, which forget g_pd)
    g_dwn = 0;
    if (VKA_ENV("DM_VK_PUSH_DELTA",
                 !strcmp(DM_GAME_ID, "0400486024DEC000")) && g_pd[c].n == k && g_pd[c].w[0] == buf[0] && g_pd[c].w[1] == buf[1]) {
        int ok = 1;
        for (uint32_t i = 0; i < g_w.n && ok; i++) {
            const uint64_t *a = g_pd[c].w + 2 + 4 * (size_t)i, *b = buf + 2 + 4 * (size_t)i;
            if (a[0] != b[0]) ok = 0; else if (memcmp(a + 1, b + 1, 3 * sizeof *a)) g_dw[g_dwn++] = g_w.w[i];
        }
        if (!ok) g_dwn = 0;
    }
    if (k > g_pd[c].cap) { g_pd[c].cap = k * 2; g_pd[c].w = realloc(g_pd[c].w, g_pd[c].cap * sizeof *buf); if (!g_pd[c].w) { g_pd[c].cap = g_pd[c].n = 0; return 0; } }
    memcpy(g_pd[c].w, buf, k * sizeof *buf); g_pd[c].n = k; g_pd_push++; g_pd_push_all++;
    if (g_dwn) { g_pd_delta_w += g_dwn; g_pd_delta_all += g_w.n; return 2; }
    return 0;
}
// A stand-in spatial reconstructor requires linear-clamp sampling even if
// the original neural network bound a nearest/repeat sampler. Descriptor
// layouts and the game's sampler objects stay intact; override this write only.
static VkSampler g_ndsr_linear_sampler;
static uint16_t g_ndsr_linear_binding;
static VkDescriptorImageInfo g_ndsr_linear_info;
static int sets_push(const vka_layout *lay, VkPipelineBindPoint bp, int any_pool) {
    if (bp == VK_PIPELINE_BIND_POINT_COMPUTE && g_ndsr_linear_sampler)
        vka_ndsr_linear_write(g_w.w,g_w.n,g_ndsr_linear_binding,g_ndsr_linear_sampler,&g_ndsr_linear_info);
    uint64_t t2_ = g_prof ? cntvct() : 0;
    if (lay->push) { int ps = g_w.n ? push_same(bp, lay->layout) : 1;
                     if (ps == 0) vk.vkCmdPushDescriptorSetKHR(g_cb, bp, lay->layout, 0, g_w.n, g_w.w);
                     else if (ps == 2) vk.vkCmdPushDescriptorSetKHR(g_cb, bp, lay->layout, 0, g_dwn, g_dw); }
    else {
        g_pd[bp == VK_PIPELINE_BIND_POINT_COMPUTE].n = 0;   // set 0 bound as a set: the last push is no longer what the draws see
        VkDescriptorSet set = set_alloc(lay->set0); if (!set) return 0;
        for (uint32_t i = 0; i < g_w.n; i++) g_w.w[i].dstSet = set;
        if (g_w.n) vk.vkUpdateDescriptorSets(V.dev, g_w.n, g_w.w, 0, NULL);
        vk.vkCmdBindDescriptorSets(g_cb, bp, lay->layout, 0, 1, &set, 0, NULL);
    }
    if (g_prof) g_ps[2] += cntvct() - t2_;
    if (any_pool) vka_tex_pfb_draw();   // (its pool reads are reported: this submission copies the bitmap out, vka_tex.c "Texture pool reads")
    if (any_pool) {   // set 1 the pool, and in the same call set 2 the pool reads' bitmap when they are reported (vka_tex.c "Texture pool reads")
        VkDescriptorSet ps[2] = {vka_bindless_set(), vka_pfb_set()};
        if (ps[0]) vk.vkCmdBindDescriptorSets(g_cb, bp, lay->layout, 1, ps[1] ? 2 : 1, ps, 0, NULL); else VRED_ONCE("a shader reads the texture pool and there is no pool set");
    }
    return 1;
}
static void memu_bind_arena(void);
static int bind_sets(const vka_dstate *d, vka_shader *const sh[VKA_NSTAGE], const vka_layout *lay, VkPipelineBindPoint bp, c0_at *c0) {
    g_w.n = 0;
    int any_pool = 0;
    uint64_t t1_ = g_prof ? cntvct() : 0;
    for (int st = 0; st < VKA_NSTAGE; st++) {
        vka_shader *s = sh[st]; if (!s) continue;
        if (st == 1 && d->rast_discard) continue;   // no fragments: its stage's records are not read (the layout keeps them unwritten: partially bound is not needed for push descriptors)
        int n = g_wk.n[st];
        if (n < 0) { static _Atomic int k; if (atomic_fetch_add(&k, 1) < 16) VRED("shader %016llx: %s; skipped", (unsigned long long)s->key, g_wk.why[st]); return 0; }
        any_pool |= g_wk.pool[st];
        if (!stage_writes(d, st, s, g_wk.r[st], n, g_wk.pool[st], st == 5 ? c0 : NULL)) return 0;
    }
    if (g_prof) g_ps[1] += cntvct() - t1_;
    if (sh[2] && sh[2]->gs_fx > 0 && bp == VK_PIPELINE_BIND_POINT_GRAPHICS) {   // the claim words, zeroed (vka_spv_gs_claim); bound also when the draw takes no claim (the layout has them)
        if (g_w.n == 512) { VRED_ONCE("more than 512 descriptors in one draw"); return 0; }
        VkDeviceSize n = 4 * (VkDeviceSize)(g_claim_words ? g_claim_words : 1); vka_span cs;
        if (!vka_scratch(n, V.sb_align, &cs)) return 0;
        memset(cs.ptr, 0, (size_t)n);
        uint32_t k = g_w.n++;
        g_w.bi[k] = (VkDescriptorBufferInfo){cs.buf, cs.off, n};
        g_w.w[k] = (VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = VKA_GS_CLAIM_BINDING, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &g_w.bi[k]};
    }
    if (sh[0] && sh[0]->memu == 2 && bp == VK_PIPELINE_BIND_POINT_GRAPHICS) memu_bind_arena();   // a mesh draw through compute: the arena it draws (vka_memu_draw.inc)
    return sets_push(lay, bp, any_pool);
}
// Images first used by a draw (from the walk, walk_all), or remade with storage use (vka_tex.c img_storage_upgrade): dry = only whether there is one
static int make_images(const vka_dstate *d, vka_shader *const sh[VKA_NSTAGE], int dry) {
    (void)d; int any = 0;
    for (int st = 0; st < VKA_NSTAGE; st++) {
        if (!sh[st]) continue;
        const vka_res *r = g_wk.r[st];
        for (int i = 0; i < g_wk.n[st]; i++) if ((r[i].what == VKA_R_TEX || r[i].what == VKA_R_IMG) && r[i].tid
                                                 && (vka_tex_id_pending_rec(r[i].tid, r[i].dim) || (r[i].what == VKA_R_IMG && vka_tex_id_storage_pending(r[i].tid)))) {   // (an image remade with storage use copies its content: outside the pass)
            any = 1; if (dry) return 1;
            vka_tex_id_view(r[i].tid, g_cb, r[i].dim, r[i].what == VKA_R_IMG, NULL);
        }
    }
    return any;
}

// The draw writes memory: a storage buffer or image it writes, raw global stores (their write log), a geometry shader's claimed writes (from the walk, walk_all)
static int draw_writes(vka_shader *const sh[VKA_NSTAGE], const vka_dstate *d) {
    if (sh[2] && sh[2]->gs_fx > 0) return 1;
    for (int st = 0; st < VKA_NSTAGE; st++) {
        if (!sh[st] || (st == 1 && d->rast_discard)) continue;
        const vka_res *r = g_wk.r[st];
        for (int i = 0; i < g_wk.n[st]; i++) if ((r[i].flags & DMSH_VK_BF_RW) || r[i].what == VKA_R_IMG || r[i].what == VKA_R_GMEM_LOG) return 1;
    }
    return 0;
}
// After a game barrier taken inside the pass (vka_rp_game_barrier): this draw needs the pass ended first when it writes memory (earlier draws of the pass may read what it
// overwrites), reads the texture pool directly (any texture, the pass's targets among them), or samples a texture whose image the pass draws into
static int bar_hazard(vka_shader *const sh[VKA_NSTAGE], const vka_dstate *d) {
    if (draw_writes(sh, d)) return 1;
    for (int st = 0; st < VKA_NSTAGE; st++) {
        if (!sh[st] || (st == 1 && d->rast_discard)) continue;
        if (g_wk.n[st] < 0) return 1;
        // A pool shader alone no longer implies a framebuffer feedback read:
        // query the exact registered guest ranges. If no texture aliases
        // this pass's attachments, the draw cannot sample its render targets.
        // Unknown or overlapping registration still ends the pass.
        if (g_wk.pool[st] && vka_tex_pool_in_pass()) return 1;
        const vka_res *r = g_wk.r[st];
        for (int i = 0; i < g_wk.n[st]; i++) if ((r[i].what == VKA_R_TEX || r[i].what == VKA_R_TBUF) && r[i].tid && vka_tex_id_in_pass(r[i].tid)) return 1;
    }
    return 0;
}

// ---------- Draws ----------
// A program's shaders by its serial (a program that gets new shaders gets a new serial, hle_nvn.c), remembered for the draws after: the shader table's lock and lookup
// were taken once per stage of every draw
static struct { uint64_t serial; vka_progsh ps; } g_pm[64];
static int resolve(const prog_t *p, int st, vka_shader **out, unsigned *bad) {
    *out = NULL; if (!p) return 1;
    vka_progsh ps;
    uint64_t sr = p->serial; typeof(g_pm[0]) *m = &g_pm[(sr ^ sr >> 6) & 63];
    if (sr && m->serial == sr) ps = m->ps;
    else { if (!vka_prog_shaders(p, &ps)) return 0; if (sr) { m->serial = sr; m->ps = ps; } }
    if (ps.bad & (1u << st | VKA_BAD_MISSING)) { *bad |= 1u << st; return 1; }
    *out = ps.sh[st]; return 1;
}
// Vertex input: an attribute per input location the vertex shader reads (Location = NVN attribute index), each from its stream; an input no attribute feeds reads a zero buffer.
// With VK_EXT_vertex_input_dynamic_state the descriptions are set per draw, else they go into the pipeline key
static struct { VkVertexInputBindingDescription2EXT b[33]; VkVertexInputAttributeDescription2EXT a[32]; uint32_t nb, na, used, zb; int zero; } VI;
static uint64_t g_vi_ser;
static void vin_build(const vka_dstate *d, const vka_shader *vs, vka_gkey *k) {
    g_vi_ser++;
    VI.nb = VI.na = VI.used = 0; VI.zero = 0;
    VI.zb = V.max_vin_bindings > 32 ? 31 : V.max_vin_bindings > 16 ? V.max_vin_bindings - 1 : 15;   // the zero buffer's binding: past the 16 streams when the device has room
    for (uint32_t loc = 0; loc < 32; loc++) {
        if (!(vs->e->vin_mask >> loc & 1)) continue;
        int want = (int)(vs->e->vin_types >> (2 * loc) & 3), changed = 0, retype = 0;
        const va_st *a = loc < 16 && (int)loc < d->nattr ? &d->attr[loc] : NULL;
        VkFormat f = a && a->fmt ? vin_format(a->fmt, want, &changed, &retype) : VK_FORMAT_UNDEFINED;
        if (retype == DMSH_VK_TYPE_UINT) k->vin_u |= 1u << loc; else if (retype == DMSH_VK_TYPE_SINT) k->vin_s |= 1u << loc;
        if (a && a->fmt && !f) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 4) VRED("vertex attribute format %#x is not mapped: the input reads zeros", a->fmt); }
        if (changed) { static uint64_t seen[4]; unsigned b = a->fmt & 255; if (!(seen[b >> 6] >> (b & 63) & 1)) { seen[b >> 6] |= 1ull << (b & 63);
            VRED("vertex attribute format %#x feeds a %s input: bound as VkFormat %d of that class (values may differ from Maxwell's fetch)", a->fmt, want == 0 ? "float" : want == 1 ? "sint" : "uint", f); } }
        if (!f) {
            f = want == DMSH_VK_TYPE_UINT ? VK_FORMAT_R32G32B32A32_UINT : want == DMSH_VK_TYPE_SINT ? VK_FORMAT_R32G32B32A32_SINT : VK_FORMAT_R32G32B32A32_SFLOAT;
            VI.a[VI.na++] = (VkVertexInputAttributeDescription2EXT){VK_STRUCTURE_TYPE_VERTEX_INPUT_ATTRIBUTE_DESCRIPTION_2_EXT, NULL, loc, VI.zb, f, 0};
            VI.zero = 1; continue;
        }
        uint32_t st = a->stream & 15;
        VI.a[VI.na++] = (VkVertexInputAttributeDescription2EXT){VK_STRUCTURE_TYPE_VERTEX_INPUT_ATTRIBUTE_DESCRIPTION_2_EXT, NULL, loc, st, f, a->offset};
        VI.used |= 1u << st;
    }
    for (uint32_t st = 0; st < 16; st++) if (VI.used >> st & 1) {
        uint32_t div = d->stream[st].divisor;
        if (div > 1 && !V.divisor) { VRED_ONCE("instance divisor %u and no vertexAttributeInstanceRateDivisor: drawn with divisor 1", div); div = 1; }
        VI.b[VI.nb++] = (VkVertexInputBindingDescription2EXT){VK_STRUCTURE_TYPE_VERTEX_INPUT_BINDING_DESCRIPTION_2_EXT, NULL, st, d->stream[st].stride,
                                                               div ? VK_VERTEX_INPUT_RATE_INSTANCE : VK_VERTEX_INPUT_RATE_VERTEX, div ? div : 1};
    }
    if (VI.zero) VI.b[VI.nb++] = (VkVertexInputBindingDescription2EXT){VK_STRUCTURE_TYPE_VERTEX_INPUT_BINDING_DESCRIPTION_2_EXT, NULL, VI.zb, 0, VK_VERTEX_INPUT_RATE_VERTEX, 1};
    if (!V.vin_dyn) {
        k->vin_static = 1;
        for (uint32_t i = 0; i < VI.na; i++) { uint32_t l = VI.a[i].location; k->va[l].fmt = VI.a[i].format; k->va[l].offset = VI.a[i].offset; k->va[l].binding = (uint8_t)VI.a[i].binding; k->va[l].used = 1; }
        for (uint32_t i = 0; i < VI.nb; i++) { uint32_t b = VI.b[i].binding; k->vb[b].stride = VI.b[i].stride; k->vb[b].divisor = VI.b[i].inputRate ? VI.b[i].divisor : 0; k->vb[b].used = 1; }
    }
}
// The vertex buffers the command buffer holds (slot: buffer, offset, size): a draw binds only the slots that changed, consecutive ones in one call. Vulkan keeps vertex
// buffer bindings across pipeline binds and passes for the life of the command buffer; forgotten with the dynamic state (vka_dyn_invalidate: a new command buffer or
// part). Profile p2: vin_bind was 13 % of the replay thread, one vkCmdBindVertexBuffers2 a stream a draw. DM_VK_VB_FILTER=0 (live): every slot every draw
static struct { int valid, vin_stale; VkBuffer b[33]; VkDeviceSize o[33], sz[33]; uint32_t vnb, vna; VkVertexInputBindingDescription2EXT vb[33]; VkVertexInputAttributeDescription2EXT va[32]; } VB;
static void vb_set(uint32_t slot, VkBuffer b, VkDeviceSize o, VkDeviceSize sz, uint32_t *n0, uint32_t *nn, VkBuffer *rb, VkDeviceSize *ro, VkDeviceSize *rs) {
    if (slot >= 33) return;
    if (VB.valid && g_vb_filter && VB.b[slot] == b && VB.o[slot] == o && VB.sz[slot] == sz) return;
    VB.b[slot] = b; VB.o[slot] = o; VB.sz[slot] = sz;
    if (*nn && *n0 + *nn != slot) { vk.vkCmdBindVertexBuffers2(g_cb, *n0, *nn, rb, ro, rs, NULL); *nn = 0; }   // a run ends: bound in one call
    if (!*nn) *n0 = slot;
    rb[*nn] = b; ro[*nn] = o; rs[*nn] = sz; (*nn)++;
}
static void vin_bind(const vka_dstate *d) {
    if (!VB.valid) memset(&VB, 0, sizeof VB);
    // The vertex input state too only when it changed (it was set every draw: up to 65 descriptions copied into the encoder's ring and the driver), and again after
    // every pipeline bind: Vulkan keeps dynamic vertex input across vkCmdBindPipeline, but drivers have lost it there before (hardening; the buffers stay filtered)
    if (V.vin_dyn) {
        int same = VB.valid && !VB.vin_stale && g_vb_filter && VB.vnb == VI.nb && VB.vna == VI.na && !memcmp(VB.vb, VI.b, VI.nb * sizeof *VI.b) && !memcmp(VB.va, VI.a, VI.na * sizeof *VI.a);
        if (!same) { vk.vkCmdSetVertexInputEXT(g_cb, VI.nb, VI.b, VI.na, VI.a); VB.vnb = VI.nb; VB.vna = VI.na; memcpy(VB.vb, VI.b, VI.nb * sizeof *VI.b); memcpy(VB.va, VI.a, VI.na * sizeof *VI.a); }
        VB.vin_stale = 0;
    }
    VkBuffer rb[33]; VkDeviceSize ro[33], rs[33]; uint32_t n0 = 0, nn = 0;
    for (uint32_t st = 0; st < 16; st++) if (VI.used >> st & 1) {   // each stream at its address, as far as it is bound and placed
        VkBuffer b = g_zero.buf; VkDeviceSize o = g_zero.off, sz = 65536;
        uint64_t addr = d->vbuf[st].address, size = d->vbuf[st].size;
        if (addr) { VkBuffer cb; VkDeviceSize co; uint64_t run = vka_addr_run(addr, size ? size : 1ull << 30, &cb, &co);
                    if (run) { b = cb; o = co; sz = run; } else VRED_ONCE("vertex stream at %#llx is not in placed guest RAM: it reads zeros", (unsigned long long)addr); }
        vb_set(st, b, o, sz, &n0, &nn, rb, ro, rs);
    }
    if (VI.zero) vb_set(VI.zb, g_zero.buf, g_zero.off, 65536, &n0, &nn, rb, ro, rs);
    if (nn) vk.vkCmdBindVertexBuffers2(g_cb, n0, nn, rb, ro, rs, NULL);
    VB.valid = 1;
}

// Banana Native's input-revision cache: reuse descriptions only for the
// same vertex shader and unchanged formats. Reuse buffer bindings only
// while the command buffer and placed-memory generation are unchanged.
static struct { int valid; const vka_shader *vs; uint64_t s_vfmt; uint32_t vin_u, vin_s; } VC;
static struct { int valid; uint64_t ser, s_vbuf, mg; } VBC;
static void vin_build_kept(const vka_dstate *d, const vka_shader *vs, vka_gkey *k) {
    if (g_vin_skip && V.vin_dyn && VC.valid && VC.vs == vs && VC.s_vfmt == d->s_vfmt) { k->vin_u = VC.vin_u; k->vin_s = VC.vin_s; g_vin_kept++; return; }
    vin_build(d, vs, k); g_vin_built++;
    VC.valid = 1; VC.vs = vs; VC.s_vfmt = d->s_vfmt; VC.vin_u = k->vin_u; VC.vin_s = k->vin_s;
}
static void vin_bind_kept(const vka_dstate *d) {
    uint64_t mg = vka_mem_gen();
    if (g_vin_skip && V.vin_dyn && g_vb_filter && VB.valid && !VB.vin_stale && VBC.valid && VBC.ser == g_vi_ser && VBC.s_vbuf == d->s_vbuf && VBC.mg == mg) { g_vb_kept++; return; }
    vin_bind(d); g_vb_bound++;
    VBC.valid = 1; VBC.ser = g_vi_ser; VBC.s_vbuf = d->s_vbuf; VBC.mg = mg;
}

// The guest indices of an indexed draw as 32-bit values (the CPU's view): for primitives Vulkan has no topology for and 8-bit indices on a device without them
static uint32_t *read_indices(uint64_t addr, int itype, uint32_t count) {
    size_t isz = itype == 0 ? 1 : itype == 1 ? 2 : 4; uint8_t *raw = malloc(isz * count + 4); uint32_t *o = malloc(4 * (size_t)count + 4);
    if (!raw || !o || !cpu_read(addr, raw, isz * count)) { free(raw); free(o); return NULL; }
    for (uint32_t i = 0; i < count; i++) o[i] = isz == 1 ? raw[i] : isz == 2 ? ((uint16_t *)raw)[i] : ((uint32_t *)raw)[i];
    free(raw); return o;
}

// The dynamic state the command buffer holds: each draw sets only what changed (the draw path set some 25 states a draw). Valid from the first draw of a submission until
// something else binds a graphics pipeline with static state (the masked stencil clear: vka_dyn_invalidate) or the submission ends; every graphics pipeline of the draws has
// the same dynamic states (vka_pso.c), so binding one keeps them, except a mesh pipeline, which has no topology or primitive restart (vka_draw resets DY.topo / DY.pr after one)
static struct { int valid; VkPipeline pipe; VkViewport vp; VkRect2D sc; uint32_t cull, ff, topo, dt, dw, dc, dbt, stt, dbe, rd, pr, sop[8], smask[6]; float db[3], bc[4]; } DY;
#define DY_SET(f, val, call) do { if (!DY.valid || !g_dyn_filter || memcmp(&DY.f, &(val), sizeof DY.f)) { memcpy(&DY.f, &(val), sizeof DY.f); call; } } while (0)
#define DY_SET1(f, val, call) do { uint32_t v_ = (val); if (!DY.valid || !g_dyn_filter || DY.f != v_) { DY.f = v_; call; } } while (0)
// The index buffer the command buffer holds: bound again only when it changes (DM_VK_VB_FILTER), forgotten with the dynamic state
static struct { int valid; VkBuffer b; VkDeviceSize o; VkIndexType t; } IB;
static void ib_bind(VkBuffer b, VkDeviceSize o, VkIndexType t) {
    if (IB.valid && g_vb_filter && IB.b == b && IB.o == o && IB.t == t) return;
    vk.vkCmdBindIndexBuffer(g_cb, b, o, t); IB.valid = 1; IB.b = b; IB.o = o; IB.t = t;
}
void vka_dyn_invalidate(void) { DY.valid = 0; VB.valid = 0; IB.valid = 0; g_pd[0].n = g_pd[1].n = 0; }
#define PT(i) do { if (g_prof) { uint64_t t_ = cntvct(); if ((i) > 0 && g_pt_ph == (i) - 1) g_pt[(i) > 0 ? (i) - 1 : 0] += t_ - g_pt_last; g_pt_last = t_; g_pt_ph = (i); } } while (0)
void vka_draw_prof(char *b, size_t n, double draws) {
    if (!g_prof || draws <= 0) { if (n) b[0] = 0; return; }
    uint64_t f; __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f)); double us = 1e6 / (double)f / draws;
    static const char *nm[8] = {"resolve", "layout", "images+pass+key", "vertex input", "pipeline", "sets", "vertex buffers+dynamic", "draw"};
    size_t o = 0; for (int i = 0; i < 8 && o < n; i++) o += snprintf(b + o, n - o, "%s%s %.2f", i ? ", " : "", nm[i], g_pt[i] * us);
    if (o < n) o += snprintf(b + o, n - o, "; pushes %.0f%% skipped as the last one", g_pd_skip + g_pd_push ? 100.0 * g_pd_skip / (double)(g_pd_skip + g_pd_push) : 0.0);
    g_pd_skip = g_pd_push = 0;
    if (o < n) o += snprintf(b + o, n - o, "; sets: walk %.2f, writes %.2f (driver segments %.2f, %.1f images %.2f), push %.2f", g_ps[0] * us, g_ps[1] * us, g_ps[3] * us, g_ps[5] / draws, g_ps[4] * us, g_ps[2] * us);
    memset(g_ps, 0, sizeof g_ps);
    memset(g_pt, 0, sizeof g_pt);
}
// An indirect NVN2 mesh draw (nvnCommandBufferDrawMeshTasksIndirect, hle_nvn.c). NVN's record is {count, first} (VK_NV_mesh_shader's layout), Vulkan's {x, y, z}: read in
// place, y = first (0 in practice) draws nothing. The GPU writes the record earlier in the frame (a culling compute), so the CPU cannot take count from it here: a one-thread
// compute (selftest/meshcount.comp) writes a {count, 1, 1} record into the submission's scratch (the span lives until the submission's fence), outside any pass (Vulkan allows
// no dispatch or copy inside one), and a barrier makes it readable as indirect arguments. A count past the device's limit per dimension (maxTaskWorkGroupCount /
// maxMeshWorkGroupCount, 65535 on the Adreno 840; undefined in VK_EXT_mesh_shader) becomes 0, as the direct draw skips one. Without push descriptors (or the pipeline) the CPU
// writes {0, 1, 1} and the GPU copies count over x, unchecked (a red line once). Whatever wrote the record ended with a barrier (dispatches, copies, passes). A pass open at this
// draw is ended for the dispatch and opened again with LOAD by rp_begin: on a tiler a store and a load of its attachments per indirect mesh draw inside a pass (counted in the
// log line below; open: making all of a pass's records before it begins would avoid it). first, the base workgroup, is not applied: the translated task and mesh shaders read
// their workgroup index with no base, as for the direct draw (open). The CPU's view of the record (an earlier GPU write) is checked for a nonzero first and a count past the limit
static VkPipeline g_mc_pipe; static VkPipelineLayout g_mc_lay; static VkDescriptorSetLayout g_mc_dsl;
static int mesh_count_ready(void) {   // the record's pipeline, made at the first indirect mesh draw (the replay thread); 0: the unchecked copy
    static int st; if (st) return st > 0;
    st = -1;
    if (!V.push_desc || !vk.vkCmdPushDescriptorSetKHR) { VRED("indirect mesh draws: no push descriptors: each count is copied as the GPU wrote it, not checked against the device's workgroup limit"); return 0; }
    VkDescriptorSetLayoutBinding b[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo dl = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR, .bindingCount = 2, .pBindings = b};
    VkPushConstantRange pc = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 8};
    VkPipelineLayoutCreateInfo li = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &g_mc_dsl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pc};
    VkShaderModuleCreateInfo mi = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof SPV_MESHCOUNT_COMP, .pCode = SPV_MESHCOUNT_COMP};
    VkShaderModule m = VK_NULL_HANDLE; VkResult r;
    if ((r = vk.vkCreateDescriptorSetLayout(V.dev, &dl, NULL, &g_mc_dsl)) || (r = vk.vkCreatePipelineLayout(V.dev, &li, NULL, &g_mc_lay)) || (r = vk.vkCreateShaderModule(V.dev, &mi, NULL, &m))) {
        VRED("indirect mesh draws: the count's pipeline not made (%d): each count is copied as the GPU wrote it, not checked against the device's workgroup limit", r); return 0; }
    VkComputePipelineCreateInfo ci = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main"}, .layout = g_mc_lay};
    r = vk.vkCreateComputePipelines(V.dev, VK_NULL_HANDLE, 1, &ci, NULL, &g_mc_pipe);
    vk.vkDestroyShaderModule(V.dev, m, NULL);
    if (r) { VRED("indirect mesh draws: the count's pipeline not made (%d): each count is copied as the GPU wrote it, not checked against the device's workgroup limit", r); return 0; }
    st = 1; return 1;
}
static int mesh_ind_args(uint64_t ind, uint32_t maxg, vka_span *out) {
    VkBuffer b; VkDeviceSize o, al = V.sb_align > 16 ? V.sb_align : 16;   // (the span is bound as a storage buffer: its offset at the storage alignment)
    if (!vka_addr(ind, 8, &b, &o, NULL) || (o & 3) || !vka_scratch(12, al, out)) return 0;
    int gpu = mesh_count_ready();
    static const uint32_t init[3] = {0, 1, 1}; memcpy(out->ptr, init, sizeof init);
    uint32_t cf[2];
    if (cpu_read(ind, cf, sizeof cf)) {
        static _Atomic int nl, nf, nm;
        if (atomic_fetch_add(&nl, 1) < 4) VLOG("indirect mesh draw: record at %#llx as the CPU sees it now (an earlier GPU write): count %u first %u", (unsigned long long)ind, cf[0], cf[1]);
        if (cf[1] && atomic_fetch_add(&nf, 1) < 4) VRED("indirect mesh draw with first workgroup %u (count %u; the CPU's view of the record at %#llx): drawn from 0 (the translated task / mesh shaders read their workgroup index with no base; open)", cf[1], cf[0], (unsigned long long)ind);
        if (cf[0] > maxg && atomic_fetch_add(&nm, 1) < 4) VRED("indirect mesh draw of %u workgroups (the CPU's view of the record at %#llx): more than the device's %u in one dimension, %s", cf[0], (unsigned long long)ind, maxg,
                                                               gpu ? "not drawn (as a direct draw past the limit)" : "drawn as the GPU's record says (no count pipeline)");
    }
    static uint64_t n, nsplit; n++;
    if (R.on) { nsplit++; vka_rp_end(); }
    if (!(n & (n - 1)) && __builtin_ctzll(n) % 4 == 0) VLOG("indirect mesh draws: %llu so far, %llu of them ended an open pass for their count", (unsigned long long)n, (unsigned long long)nsplit);
    if (gpu) {   // the record bound from the storage alignment below it, at is its word there
        VkDeviceSize base = o / V.sb_align * V.sb_align;
        VkDescriptorBufferInfo bi[2] = {{b, base, o - base + 4}, {out->buf, out->off, 12}};
        VkWriteDescriptorSet w[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi[0]},
                                     {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi[1]}};
        uint32_t pc[2] = {(uint32_t)((o - base) / 4), maxg};
        vk.vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, g_mc_pipe);
        vk.vkCmdPushDescriptorSetKHR(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, g_mc_lay, 0, 2, w);
        vk.vkCmdPushConstants(g_cb, g_mc_lay, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, pc);
        vk.vkCmdDispatch(g_cb, 1, 1, 1);
        g_pd[1].n = 0;   // the dispatches' last push is no longer bound (push_same)
    } else { VkBufferCopy c = {o, out->off, 4}; vk.vkCmdCopyBuffer(g_cb, b, out->buf, 1, &c); }
    vka_barrier(g_cb);
    return 1;
}
// DM_VK_DRAW_LOG=<n> (live): the first n draws of each frame, one line each with its index in the frame, its vertex and fragment shaders, its colour targets (serial, size,
// level), the channel mask and target 0's blend, then one line per texture it samples (binding, texture ID, sampler ID and the texture as vka_tex_id_desc tells it). With
// nxreplay and --dump-gpu it shows which draw writes a picture and from what
static void draw_log(const vka_dstate *d, vka_shader *const sh[VKA_NSTAGE], const p_draw *dw, const p_draw_idx *di) {
    uint64_t vka_frame(void); static unsigned long long nd; static uint64_t fr = ~0ull; static int lg;
    if (vka_frame() != fr) { fr = vka_frame(); lg = (int)VKA_ENV("DM_VK_DRAW_LOG", 0); nd = 0; }
    unsigned long long k = nd++; if (lg <= 0 || k >= (unsigned long long)lg) return;
    char t[400]; size_t o = 0; t[0] = 0;
    for (int i = 0; i < R.nci && o < sizeof t; i++) o += (size_t)snprintf(t + o, sizeof t - o, "%s%llu %ux%u lv %u", i ? ", " : "", (unsigned long long)R.cim[i]->serial, R.cim[i]->w, R.cim[i]->h, R.clv[i]);
    const blend_st *b = &d->blend[0];
    VLOG("draw %llu: vs %016llx fs %016llx %s %d (prim %d) into [%s]; viewport %.1f,%.1f %.1fx%.1f depth %.2f-%.2f, scissor %d,%d %ux%u, cull %u, depth test %u write %u, stencil test %u, rasterizer discard %d; "
         "channel mask %#x, blend enable %#x src %d/%d dst %d/%d eq %d/%d",
         k, sh[0] ? (unsigned long long)sh[0]->key : 0ull, sh[1] ? (unsigned long long)sh[1]->key : 0ull, dw ? "count" : "indexed", dw ? dw->count : di->count, dw ? dw->prim : di->prim,
         t, DY.vp.x, DY.vp.y, DY.vp.width, DY.vp.height, DY.vp.minDepth, DY.vp.maxDepth, DY.sc.offset.x, DY.sc.offset.y, DY.sc.extent.width, DY.sc.extent.height, DY.cull, DY.dt, DY.dw, DY.stt, d->rast_discard,
         d->chmask.mask, (unsigned)d->color.blend_en, (int)b->src_rgb, (int)b->src_a, (int)b->dst_rgb, (int)b->dst_a, (int)b->eq_rgb, (int)b->eq_a);
    if (R.has_rt && R.rt.depth) { const tex_t *z = R.rt.depth; vka_img *zi = vka_tex_get(z, VK_NULL_HANDLE);   // (made already: the pass is open)
        VLOG("draw %llu:   depth target: texture serial %llu target %d %ux%ux%u layers %u format %#x storage %p (view: %s layers %u+%u) -> image of serial %llu %p %ux%u layers %u", k, (unsigned long long)z->serial, z->d.target,
             z->d.width, z->d.height, z->d.depth, z->L.layers, z->d.format, (const void *)z->mem, R.rt.has_dview ? "set" : "none", R.rt.has_dview && R.rt.dview.set_layers ? R.rt.dview.min_layer : 0,
             R.rt.has_dview && R.rt.dview.set_layers ? R.rt.dview.nlayers : 0, zi ? (unsigned long long)zi->serial : 0ull, (void *)zi, zi ? zi->w : 0, zi ? zi->h : 0, zi ? zi->layers : 0); }
    for (uint32_t i = 0; i < VI.na; i++) { const VkVertexInputAttributeDescription2EXT *va = &VI.a[i]; const VkVertexInputBindingDescription2EXT *vb = NULL;
        for (uint32_t j = 0; j < VI.nb; j++) if (VI.b[j].binding == va->binding) vb = &VI.b[j];
        if (i == 0) VLOG("draw %llu:   instances %d base instance %d, first %d, base vertex %d, index buffer %#llx type %d, indirect %#llx", k, dw ? dw->instances : di->instances, dw ? dw->base_instance : di->base_instance,
                         dw ? dw->first : 0, dw ? 0 : di->base_vertex, dw ? 0ull : (unsigned long long)di->ibuf, dw ? -1 : di->itype, (unsigned long long)(dw ? dw->ind : di->ind));
        VLOG("draw %llu:   vertex location %u: VkFormat %d, binding %u%s offset %u stride %u rate %d, stream %#llx+%#llx", k, va->location, va->format, va->binding, va->binding == VI.zb && VI.zero ? " (zeros)" : "", va->offset,
             vb ? vb->stride : 0, vb ? (int)vb->inputRate : -1, va->binding < 16 ? (unsigned long long)d->vbuf[va->binding].address : 0ull, va->binding < 16 ? (unsigned long long)d->vbuf[va->binding].size : 0ull); }
    for (int st = 0; st < VKA_NSTAGE; st++) for (int i = 0; i < g_wk.n[st]; i++) {
        const vka_res *r = &g_wk.r[st][i];
        if (r->what == VKA_R_BUF || r->what == VKA_R_DRV) { VLOG("draw %llu:   stage %d binding %u %s %#llx+%#llx%s", k, st, r->binding, r->what == VKA_R_DRV ? "driver bank" : r->desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER ? "storage buffer" : "uniform buffer",
                                                               r->what == VKA_R_DRV ? (unsigned long long)r->bank : (unsigned long long)r->addr, (unsigned long long)r->size, r->what == VKA_R_BUF && !vka_addr(r->addr, r->size ? r->size : 1, NULL, NULL, NULL) ? " (not in placed memory)" : "");
            int nf = VKA_ENV("DM_VK_DRAW_LOG_UBO", 0);   // diagnostic: the buffer's first nf floats as the CPU sees them now
            if (nf > 0 && r->what == VKA_R_BUF && r->addr) { if (nf > 256) nf = 256; if ((uint64_t)nf * 4 > r->size) nf = (int)(r->size / 4);
                float fv[256]; if (nf > 0 && cpu_read(r->addr, fv, (size_t)nf * 4)) { char fb[4096]; size_t fo = 0;
                    for (int q = 0; q < nf && fo < sizeof fb - 32; q++) fo += (size_t)snprintf(fb + fo, sizeof fb - fo, "%s%g", q ? " " : "", fv[q]);
                    VLOG("draw %llu:     binding %u floats: %s", k, r->binding, fb); } }
            continue; }
        if (r->what != VKA_R_TEX && r->what != VKA_R_IMG) continue;
        char why[400]; vka_tex_id_desc(r->tid, why, sizeof why);
        VLOG("draw %llu:   stage %d binding %u%s texture ID %d sampler ID %d dim %#x: %s", k, st, r->binding, r->what == VKA_R_IMG ? " (image)" : "", r->tid, r->sid, r->dim, why);
    }
}
#include "vka_memu_draw.inc"
// Apply the same conservative, side-effect-free vegetation predicate to
// mesh->compute preparation and to the final raster draw.  A raster-only cut
// still does the task/mesh dispatch, allocates the arena and splits passes.
// The 508 newly admitted mesh/task shaders are deliberately kept separate
// from the 42,339-shader original library. The original Ocarina 0.1.6 ran its
// existing mesh shaders natively on VK_EXT_mesh_shader. Blanket Qualcomm
// mesh->compute emulation regressed CPU and GPU time even with foliage OFF.
// Classify by the generated, reviewed supplement keys (sorted by key), not
// by the small cosmetic 14-key vegetation-quality profile.
static int veg_supplement_stage(uint64_t key) {
    unsigned lo = 0, hi = sizeof vka_veg_entries / sizeof *vka_veg_entries;
    while (lo < hi) {
        unsigned mid = lo + (hi - lo) / 2;
        uint64_t k = vka_veg_entries[mid].key;
        if (k < key) lo = mid + 1;
        else hi = mid;
    }
    return lo < sizeof vka_veg_entries / sizeof *vka_veg_entries &&
           vka_veg_entries[lo].key == key;
}
// -1: supplement draw absent from the ORIGINAL library, vegetation OFF:
//     do not compile, dispatch, rasterize or split a pass for it.
//  0: pre-existing native mesh draw; no compute staging needed.
//  1: supplemental vegetation, retained on the proven compute route.
// The same decision is made in the look-ahead and the real draw. A native
// mesh draw is a look-ahead boundary, so compute is not reordered across it.
// DM_VK_OOT_NATIVE_BASE_MESH=0 restores all-mesh compute for a driver A/B.
int vka_mesh_route(const vka_dstate *d) {
    if (!d || strcmp(DM_GAME_ID, "0400486024DEC000"))
        return V.memu ? 1 : 0;
    const int hybrid = V.memu && V.mesh && V.task &&
                       VKA_ENV("DM_VK_OOT_NATIVE_BASE_MESH", 1);
    const int vegetation_on = VKA_ENV("DM_VK_VEGETATION", 1);
    const int test_route = VKA_ENV("DM_VK_OOT_MESH_ROUTE", -1);
    // In a full-vegetation all-compute run, every mesh draw is routed to
    // compute irrespective of its 508-key supplement membership. Avoid
    // resolving task/mesh programs and searching their keys on each
    // lookahead/replay. Vegetation OFF MUST continue the guarded lookup:
    // additional foliage programs still need to be omitted before dispatch.
    if (vegetation_on && V.memu && (test_route == -1 || test_route == 1))
        return 1;
    // The no-foliage option must omit newly added mesh stages even on
    // devices lacking native mesh support and on the all-compute rollback.
    if (!hybrid && vegetation_on) return V.memu ? 1 : 0;
    const prog_t *mp = d->bst[7];
    vka_shader *m = NULL, *ts = NULL, *ms = NULL;
    unsigned bad = 0, b2 = 0;
    if (d->bst[1] && d->bst[1] != mp &&
        resolve(d->bst[1], 7, &m, &b2) &&
        (m || (b2 & (1u << 7)))) mp = d->bst[1];
    if (!resolve(mp, 6, &ts, &bad) ||
        !resolve(mp, 7, &ms, &bad) || bad || !ms)
        return 1;  // preserve the current skip/failure path for missing stages
    int supplement = veg_supplement_stage(ms->key) ||
                     (ts && veg_supplement_stage(ts->key));
    if (supplement && !vegetation_on) return -1;
    // -1: auto uses all compute when the Vulkan device already selected
    // emulation (Qualcomm proprietary Ocarina / missing taskShader), or
    // original hardware-native otherwise. Explicitly saved mode 0 keeps
    // the previous hybrid. Mode 1 all-compute; mode 2 unsafe all-native.
    // IMPORTANT: the full-vegetation-OFF skip check above still runs first,
    // regardless of route, before any GPU work.
    if (test_route == -1) return V.memu ? 1 : 0;
    if (test_route == 1 && V.memu) return 1;
    if (test_route == 2 && V.mesh && V.task) return 0;
    return hybrid ? (supplement ? 1 : 0) : (V.memu ? 1 : 0);
}
static int vegetation_omittable(const vka_dstate *d, vka_shader *const *sh) {
    if (VKA_ENV("DM_VK_VEGETATION", 1) || d->tf_on || !sh[7] ||
        !vka_vegetation_key(DM_GAME_ID, sh[7]->key)) return 0;
    for (int stage = 0; stage < VKA_NSTAGE; stage++) {
        const vka_shader *shader = sh[stage];
        if (!shader) continue;
        for (unsigned j = 0; j < shader->e->bind_count; j++) {
            const dmsh_vk_bind *binding = &shader->b[j];
            if ((binding->flags & (DMSH_VK_BF_RW | DMSH_VK_BF_ATOMIC | DMSH_VK_BF_NOSLOT)) ||
                binding->kind == DMSH_VK_KIND_GMEM_LOG || binding->kind == DMSH_VK_KIND_UNKNOWN)
                return 0;
        }
    }
    return 1;
}
// Called before the memu look-ahead and at draw replay.  Resolve exactly the
// same task/mesh/pixel program pair used in vka_draw; never suppress shaders
// with memory side effects, unverified inputs, or transform feedback.
int vka_vegetation_mesh_omit(const vka_dstate *d) {
    if (VKA_ENV("DM_VK_VEGETATION", 1) || !d || d->tf_on) return 0;
    vka_shader *sh[VKA_NSTAGE] = {0}, *m = NULL;
    unsigned bad = 0, b2 = 0;
    const prog_t *mp = d->bst[7];
    if (d->bst[1] && d->bst[1] != mp &&
        resolve(d->bst[1], 7, &m, &b2) && (m || (b2 & (1u << 7))))
        mp = d->bst[1];
    if (!resolve(mp, 6, &sh[6], &bad) ||
        !resolve(mp, 7, &sh[7], &bad) ||
        !resolve(d->bst[1], 1, &sh[1], &bad) || bad) return 0;
    return vegetation_omittable(d, sh);
}
static int vegetation_cut(const vka_dstate *d, vka_shader *const *sh) {
    if (!vegetation_omittable(d, sh)) return 0;
    static uint64_t omitted;
    if (++omitted == 1 || omitted % 4096 == 0)
        VLOG("lower vegetation detail: %llu mesh draws omitted", (unsigned long long)omitted);
    return 1;
}
// Experimental Ocarina-only draw omissions. Resolve the pixel shader first,
// but skip before walk_all(), render-pass creation, pipeline lookup and bind.
// Independent switches: the two-layer option skips A+B; the single-shader
// option skips A only. If both are on, A is still skipped just once.
// NEVER enable by default: some scenes may need the shader's depth/colour.
static int oot_skip_hidden_fs(const vka_shader *fs) {
    // The common case must do no getenv or title lookup: almost all
    // of Ocarina's many thousands of draws use other fragment programs.
    if (!fs || (fs->key != VKA_OOT_FS_HEAVY &&
                fs->key != VKA_OOT_FS_LAYER2) ||
        strcmp(DM_GAME_ID, "0400486024DEC000")) return 0;
    int layers = VKA_ENV("DM_VK_OOT_HIDDEN_LAYERS", 0) != 0;
    int heavy = VKA_ENV("DM_VK_OOT_SKIP_HEAVY_FS", 0) != 0;
    if (!vka_oot_skip_fs_key(fs->key, layers, heavy)) return 0;
    static _Atomic uint64_t n_heavy, n_other;
    uint64_t n = fs->key == VKA_OOT_FS_HEAVY ?
        atomic_fetch_add(&n_heavy, 1) + 1 :
        atomic_fetch_add(&n_other, 1) + 1;
    if (n == 1 || !(n & 4095))
        VLOG("Ocarina experimental FS draw omission %016llx: %llu draws (two layers=%d, single shader=%d); disable options if sky, fog, depth or objects disappear",
             (unsigned long long)fs->key, (unsigned long long)n, layers, heavy);
    return 1;
}
void vka_draw(vka_dstate *d, const p_set_rt *rt, int has_rt, const p_scissor *sc, int has_sc, const p_draw *dw, const p_draw_idx *di) {
    if (!g_cb || !draws_on() || !statics()) SKIPQ();
    if (!d->inited) vka_dstate_reset(d);
    uint64_t mdi = dw ? dw->mdi_cnt : di->mdi_cnt; int mdi_i = dw ? dw->mdi_i : di->mdi_i;
    uint32_t mdi_max = dw ? dw->mdi_max : di->mdi_max, mdi_stride = dw ? dw->mdi_stride : di->mdi_stride;
    VkBuffer mdi_buffer = VK_NULL_HANDLE; VkDeviceSize mdi_offset = 0;
    if (mdi) {
        if (!V.indirect_count || !vk.vkCmdDrawIndirectCount || !vk.vkCmdDrawIndexedIndirectCount)
            SKIP("indirect-count draw requires drawIndirectCount and multiDrawIndirect");
        if (mdi_i != 0) return; // The first record emits the whole group; subsequent legacy records are for other backends.
        if (!mdi_max || mdi_max > V.props.limits.maxDrawIndirectCount || (mdi_stride & 3) || mdi_stride < (dw ? 16u : 20u))
            SKIP("invalid indirect-count maximum %u or stride %u", mdi_max, mdi_stride);
        if (!vka_addr(mdi, 4, &mdi_buffer, &mdi_offset, NULL) || (mdi_offset & 3))
            SKIP("indirect-count buffer is not aligned placed guest memory");
        static _Atomic int reported; if (!atomic_exchange(&reported, 1)) VLOG("indirect-count: native GPU count, max %u stride %u", mdi_max, mdi_stride);
    }
    d->b.base_instance = (uint32_t)(dw ? dw->base_instance : di->base_instance);
    vka_shader *sh[VKA_NSTAGE] = {0}; unsigned bad = 0;
    PT(0);
    // An NVN2 mesh draw (nvnCommandBufferDrawMeshTasks, hle_nvn.c): the task (optional) and mesh shaders of one program, the fragment stage's shader, in a mesh pipeline
    // (vka_pso.c pstate_fill) drawn with vkCmdDrawMeshTasksEXT: no vertex input, primitive type or index buffer
    int mesh = dw && dw->prim == NVN_PRIM_MESH;
    memu_ent *memu_e = NULL;   // a mesh draw through compute (vka_memu_draw.inc): drawn as a vertex draw of the arena
    if (mesh) {
        // (no fallback without the extension: the translated mesh programs exist only as mesh-stage modules, so a device without them draws neither the direct nor the indirect form)
        if (!V.mesh && VKA_ENV("DM_VK_SKIP_LOG", 0)) {   // diagnostic: what the skipped mesh draw would draw
            vka_shader *f_ = NULL, *m_ = NULL, *t_ = NULL; unsigned b_ = 0; const prog_t *mp_ = d->bst[7] ? d->bst[7] : d->bst[1];
            resolve(d->bst[1], 1, &f_, &b_); resolve(mp_, 7, &m_, &b_); resolve(mp_, 6, &t_, &b_);
            const tex_t *c0_ = has_rt && rt && rt->n > 0 ? rt->color[0] : NULL, *dz_ = has_rt && rt ? rt->depth : NULL;
            VLOG("skip log: mesh draw ts %016llx ms %016llx fs %016llx count %d%s, colour targets %d (0: serial %llu %ux%u format %#x), depth %llu %ux%u format %#x; channel mask %#x",
                 t_ ? (unsigned long long)t_->key : 0ull, m_ ? (unsigned long long)m_->key : 0ull, f_ ? (unsigned long long)f_->key : 0ull, dw->count, dw->ind ? " (indirect)" : "", has_rt && rt ? rt->n : -1,
                 c0_ ? (unsigned long long)c0_->serial : 0ull, c0_ ? c0_->d.width : 0, c0_ ? c0_->d.height : 0, c0_ ? c0_->d.format : 0,
                 dz_ ? (unsigned long long)dz_->serial : 0ull, dz_ ? dz_->d.width : 0, dz_ ? dz_->d.height : 0, dz_ ? dz_->d.format : 0, d->chmask.mask); }
        if (!V.mesh && !V.memu) SKIP("mesh draw (nvnCommandBufferDrawMeshTasks%s) on a device without VK_EXT_mesh_shader (or DM_VK_MESH=0): skipped", dw->ind ? "Indirect" : "");
        if (dw->ind && !vk.vkCmdDrawMeshTasksIndirectEXT) SKIP("indirect mesh draw: the driver has no vkCmdDrawMeshTasksIndirectEXT: skipped");
        // The program whose task and mesh shaders run: the fragment stage's when it has a mesh shader (a program's stages are bound together), else the one bound at the
        // mesh stage bit. Task and mesh come from the same program (a program's task shader feeds its own mesh shader)
        const prog_t *mp = d->bst[7];
        { vka_shader *m = NULL; unsigned b2 = 0; if (d->bst[1] && d->bst[1] != mp && resolve(d->bst[1], 7, &m, &b2) && (m || (b2 & 1u << 7))) mp = d->bst[1]; }
        if (!resolve(mp, 6, &sh[6], &bad) || !resolve(mp, 7, &sh[7], &bad) || !resolve(d->bst[1], 1, &sh[1], &bad)) SKIP("mesh draw skipped: no shader library");
        // The actual mesh and fragment programs can be DIFFERENT objects.
        // Capture their true shader pairing before skipping an unpaired hot
        // mesh; ProgramSetShaders did not know this draw-time combination.
        // Cache successful captures by program serials so this is O(1) on
        // the next ~1,800+ mesh draws, with no repeat source I/O.
        if (mp && d->bst[1] && mp->serial && d->bst[1]->serial) {
            static struct { uint64_t mesh, pixel; } captured[256];
            uint64_t mserial = mp->serial, pserial = d->bst[1]->serial;
            unsigned h = (unsigned)((mserial ^ (mserial >> 29) ^
                         pserial * UINT64_C(0x9e3779b97f4a7c15)) & 255u);
            if (captured[h].mesh != mserial || captured[h].pixel != pserial) {
                if (vka_ocarina_capture_mesh_draw_pair(mp, d->bst[1]))
                    captured[h] = (typeof(captured[h])){mserial, pserial};
            }
        }
        if (bad) SKIPQ();   // a refused or missing shader (logged when it was made)
        if (oot_skip_hidden_fs(sh[1])) SKIPQ();
        if (!sh[7]) SKIP("mesh draw with no mesh shader bound: skipped");
        if (d->bst[6] && d->bst[6] != mp) VRED_ONCE("mesh draw: a program bound at the task stage bit apart from the mesh program; drawn with the mesh program's own task shader, if any");
        // A pixel shader with per-primitive inputs reads what its mesh shader writes per primitive (Vulkan matches only equally decorated interfaces). The other way round
        // (a mesh shader with per-primitive outputs, a pixel shader without the decoration: vk_android_build.py leaves a pixel shader also drawn with vertex shaders per
        // vertex) the flags cannot tell whether it reads those locations: a red line
        if (sh[1] && (sh[1]->e->flags & DMSH_VK_F_MESH_PRIM) && !(sh[7]->e->flags & DMSH_VK_F_MESH_PRIM))
            SKIP("mesh draw: pixel shader %016llx reads per-primitive inputs that mesh shader %016llx does not write: skipped", (unsigned long long)sh[1]->key, (unsigned long long)sh[7]->key);
        if (sh[1] && !(sh[1]->e->flags & DMSH_VK_F_MESH_PRIM) && (sh[7]->e->flags & DMSH_VK_F_MESH_PRIM))
            VRED_ONCE("mesh draw: mesh shader %016llx writes per-primitive outputs and pixel shader %016llx has no per-primitive inputs: any it reads there are undefined", (unsigned long long)sh[7]->key, (unsigned long long)sh[1]->key);
        if (dw->first && !V.memu) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 4) VRED("mesh draw with first workgroup %d (count %d): drawn from 0 (the translated task / mesh shaders read their workgroup index with no base; open)", dw->first, dw->count); }
        if (!dw->ind && dw->count <= 0) return;   // (an indirect draw's count is the GPU's)
        if (d->tf_on) VRED_ONCE("transform feedback with a mesh draw: drawn without capture");
        if (vegetation_cut(d, sh)) return;
        int route = vka_mesh_route(d);
        if (route < 0) {
            static uint64_t omitted_supplement;
            if (++omitted_supplement == 1 || !(omitted_supplement & 4095))
                VLOG("mesh hybrid: %llu supplemental draws omitted with vegetation OFF (native base retained)",
                     (unsigned long long)omitted_supplement);
            return;
        }
        if (route == 0 && V.memu) {
            static uint64_t native_base;
            if (++native_base == 1 || !(native_base & 4095))
                VLOG("mesh hybrid: %llu original-library mesh draws submitted natively",
                     (unsigned long long)native_base);
        }
        if (route == 1 && V.memu) {   // through compute: its mesh work was done before the pass opened; it draws the arena with the mesh shader's vertex shader
            memu_e = memu_find();
            if (!memu_e) { vka_memu_n_skip++; SKIP("mesh draw through compute that the look-ahead did not prepare: skipped"); }
            if (!memu_e->ok) { g_skipped++;  return; }   // (logged where its shaders were refused)
            sh[0] = memu_e->vs; sh[6] = sh[7] = NULL; mesh = 0;
        }
    } else {
        for (int st = 0; st < 5; st++) if (!resolve(d->bst[st], st, &sh[st], &bad)) SKIP("draw skipped: no shader library");
        if (bad) SKIPQ();   // a refused or missing shader (logged when it was made)
        if (oot_skip_hidden_fs(sh[1])) SKIPQ();
        if (!sh[0]) SKIP("draw with no vertex shader bound: skipped");
        if (sh[1] && (sh[1]->e->flags & DMSH_VK_F_MESH_PRIM)) SKIP("pixel shader %016llx reads per-primitive mesh outputs and is drawn with a vertex shader: skipped", (unsigned long long)sh[1]->key);
        if (d->rast_discard && d->tf_on) SKIP("transform feedback is not on Vulkan yet (F_TF): the draw is skipped");
        if (d->tf_on) VRED_ONCE("transform feedback is not on Vulkan yet: the draw is drawn without capture");
    }
    if (d->poly.cull == NVN_FACE_FRONT_AND_BACK && !d->rast_discard) return;
    int prim = dw ? dw->prim : di->prim, expand = 0;
    VkPrimitiveTopology topo = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;   // (a mesh pipeline's: every translated mesh shader outputs triangles)
    if (memu_e) topo = memu_e->points ? VK_PRIMITIVE_TOPOLOGY_POINT_LIST : VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    else if (!mesh) {
        topo = topology(prim, &expand);
        if (expand < 0) SKIP("primitive type %d not on Vulkan: the draw is skipped", prim);
        if (topo == VK_PRIMITIVE_TOPOLOGY_PATCH_LIST) SKIP("tessellation patches are not on Vulkan yet (no patch size is recorded): the draw is skipped");
    }
    uint64_t ind = memu_e ? 0 : dw ? dw->ind : di->ind;
    // A geometry shader that writes memory makes those writes in the run that claims its primitive (vka_spv_gs_claim): a zeroed word per primitive at VKA_GS_CLAIM_BINDING.
    // Primitive IDs restart with each instance and an indirect draw's count is the GPU's, so those draws take the shader as it is (each run writing)
    g_claim_words = 0;
    if (sh[2] && sh[2]->gs_fx > 0) {
        int inst_n = dw ? dw->instances : di->instances;
        if (!ind && inst_n <= 1) { int32_t c = dw ? dw->count : di->count; g_claim_words = c > 0 ? (uint32_t)c : 1; }
        else VRED_ONCE("geometry shader %016llx writes memory in an %s draw: drawn without the claim, its writes repeated by the device's runs of each primitive", (unsigned long long)sh[2]->key, ind ? "indirect" : "instanced");
    }
    if (expand && ind) SKIP("an indirect draw of quads or a line loop is not on Vulkan yet: skipped");

    PT(1);
    // The last draw's shaders' layout (layouts live as long as the device): the layout table's lock and hash a draw
    static vka_shader *lsh[VKA_NSTAGE]; static vka_layout llay; static int lok;
    vka_layout lay;
    if (lok && !memcmp(lsh, sh, sizeof lsh)) lay = llay;
    else { lok = 0; if (!vka_layout_of(sh, 0, &lay)) SKIP("draw skipped: no pipeline layout"); memcpy(lsh, sh, sizeof lsh); llay = lay; lok = 1; }
    // Images first used by this draw are made (cleared or uploaded) outside the render pass, then the pass opens over the bound targets
    PT(2);
    walk_all(d, sh);
    if (R.on && vka_ub_active()) {
        int hazard = 0;
        // Raw global memory can load/store any guest address, so it must
        // see placed memory, not a speculative host shadow. Storage buffers
        // and texture buffers overlap only when their guest ranges do.
        for (int st = 0; st < VKA_NSTAGE && !hazard; st++) {
            if (!sh[st] || (st == 1 && d->rast_discard)) continue;
            if (g_wk.n[st] < 0 || g_wk.pool[st]) { hazard = 1; break; }
            for (int i = 0; i < g_wk.n[st]; i++) {
                const vka_res *r = &g_wk.r[st][i];
                if (r->what == VKA_R_GMEM_MAP || r->what == VKA_R_GMEM_LOG) { hazard = 1; break; }
                if (r->what == VKA_R_TBUF) { hazard = 1; break; }
                // A texture read after the guest's inline update must see
                // the new memory content. Render target vs uniform aliases
                // were checked at recording, but sampled images are dynamic.
                if ((r->what == VKA_R_TEX || r->what == VKA_R_IMG) &&
                    vka_tex_id_overlaps_pending_ub(r->tid)) { hazard = 1; break; }
                if (r->what == VKA_R_BUF && vka_ub_pending_overlap(r->addr, r->size)) {
                    if (r->desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER ||
                        !vka_tex_gw_shadow_safe(r->addr, r->size)) { hazard = 1; break; }
                }
            }
        }
        for (int st = 0; st < 16 && !hazard; st++) {
            uint64_t addr = d->vbuf[st].address, n = d->vbuf[st].size;
            if (addr && vka_ub_pending_overlap(addr, n ? n : 1)) hazard = 1;
        }
        // Guest index/indirect arguments can be written by OP_UPDATE_UB too.
        // Conservatively flush before those draws even with an unknown size.
        if ((di && (di->ibuf || di->ind || di->mdi_cnt)) ||
            (dw && (dw->ind || dw->mdi_cnt))) hazard = 1;
        if (hazard) vka_rp_end();
    }
    if (make_images(d, sh, 1)) { vka_rp_end(); make_images(d, sh, 0); }
    if (R.on && R.bar_pending && bar_hazard(sh, d)) { g_bar_late++; vka_rp_end(); }   // the game barrier taken inside the pass is needed here: the pass ends (its full barrier) first
    if (vka_nan_on() >= 2 && sh[1] && !d->rast_discard && vka_nan_probe(sh[1]->key)) {   // DM_VK_NANSCAN_FS: this draw's sampled textures, scanned before it
        char why[8]; int n = vka_walk(&d->b, 1, sh[1]->e, sh[1]->b, sh[1]->lib->h->ssbo_align, 0, rd_cb, NULL, g_res, 512, NULL, why, sizeof why), m = 0;
        static vka_img *ims[64]; static int bs[64], ts[64];
        for (int i = 0; i < n && m < 64; i++) if (g_res[i].what == VKA_R_TEX && g_res[i].tid) { ims[m] = vka_tex_id_img(g_res[i].tid, g_cb); bs[m] = g_res[i].binding; ts[m++] = g_res[i].tid;
            static _Atomic int nd; if (atomic_fetch_add(&nd, 1) < 32) { char why[320]; vka_tex_id_desc(g_res[i].tid, why, sizeof why); vka_img *im = ims[m - 1];
                if (getenv("DM_VK_NANSCAN_DUMP") && im && im->d.format >= 0x79 && im->d.format <= 0x94) vka_tex_id_dump(g_res[i].tid);
                vka_tex_id_check(g_res[i].tid);
                VLOG("NaN scan: input binding %u dim %#x texture ID %d sampler %d: %s; image inited %d gpu_owned %d track %d", g_res[i].binding, g_res[i].dim, g_res[i].tid, g_res[i].sid, why, im ? im->inited : -1, im ? im->gpu_owned : -1, im ? im->track : -1); } }
        int on = R.on; vka_rp_end(); (void)on;
        vka_nan_inputs(g_cb, ims, bs, ts, m);
    }
    vka_span mi = {0};   // an indirect mesh draw's Vulkan record, made outside the pass (mesh_ind_args)
    if (mesh && dw->ind && !mesh_ind_args(dw->ind, sh[6] ? V.task_groups : V.mesh_groups, &mi))
        SKIP("indirect mesh draw: its record at %#llx is not aligned placed guest RAM (or no scratch memory): skipped", (unsigned long long)dw->ind);
    if (!rp_begin(rt, has_rt, d)) SKIPQ();
    if (!R.swrite && draw_writes(sh, d)) R.swrite = 1;   // (a game barrier in this pass from now on ends it: vka_rp_game_barrier)
    d->b.samples = R.samples;
    vka_gkey k; memset(&k, 0, V.vin_dyn ? offsetof(vka_gkey, va) : sizeof k);   // (va, vb: only without vertex input dynamic state, vin_build; the pipeline lookup reads no further then)
    k.ncolor = (uint8_t)R.ncolor; k.samples = (uint8_t)R.samples; k.dfmt = R.df; k.sfmt = R.sf;
    k.topo = mesh ? 0 : (uint8_t)topo_class(topo);
    k.poly_mode = (uint8_t)(d->poly.mode == NVN_POLYGON_MODE_LINE && V.fill_lines ? VK_POLYGON_MODE_LINE : d->poly.mode == NVN_POLYGON_MODE_POINT && V.fill_lines ? VK_POLYGON_MODE_POINT : VK_POLYGON_MODE_FILL);
    k.depth_clamp = d->depth_clamp && V.depth_clamp; k.a2c = d->ms.a2c != 0;
    if (d->color.logic_op != NVN_LOGIC_OP_COPY && V.logic_op) { k.logic_en = 1; k.logic_op = (uint8_t)d->color.logic_op; }
    k.gl_depth = !vka_depth_zero();
    const vka_shader *fs = d->rast_discard ? NULL : sh[1];
    // The pixel shader's module (android/SHADERS.md "Variants"): MOD_UINT when every target it writes is a UINT attachment, MOD_UINT_MIXED when the UINT ones are exactly its
    // uint_mask, MOD_DUAL when target 0 blends with a SRC1 factor; else the base. The alpha test is the base's specialization constant in every variant
    uint32_t umask = 0, amask = 0;
    for (uint32_t i = 0; i < R.ncolor; i++) if (R.cf[i]) { amask |= 1u << i; if (R.ckind[i] == 1) umask |= 1u << i; }
    int variant = DMSH_VK_MOD_BASE;
    if (fs) {
        uint32_t fm = fs->e->fout_mask;
        if ((umask & fm) && (umask & fm) == (amask & fm) && vka_shlib_module(fs->lib, fs->e, DMSH_VK_MOD_UINT)) variant = DMSH_VK_MOD_UINT;
        else if ((umask & fm) && fs->e->uint_mask == (umask & fm) && vka_shlib_module(fs->lib, fs->e, DMSH_VK_MOD_UINT_MIXED)) variant = DMSH_VK_MOD_UINT_MIXED;
        else if ((d->color.blend_en & 1) && V.dual_src && vka_shlib_module(fs->lib, fs->e, DMSH_VK_MOD_DUAL)) {
            blend_st b0 = adv_blend(d->blend[0]);
            if (is_src1(b0.src_rgb) || is_src1(b0.dst_rgb) || is_src1(b0.src_a) || is_src1(b0.dst_a)) variant = DMSH_VK_MOD_DUAL;
        }
    }
    if (fs && (fs->e->flags & DMSH_VK_F_ALPHA_TEST) && d->color.alpha_func != NVN_ALPHA_FUNC_ALWAYS) k.alpha_func = (uint8_t)d->color.alpha_func;
    // No library variant for a float output into an integer attachment (the library has MOD_UINT only for outputs made of integer bits or constants): the base module
    // with those outputs retyped as the integer vectors of their bits (VKA_FS_RETYPE, vka_spv_fout_retype), which is what the hardware writes. DM_VK_FOUT_RETYPE=0: not written, as before
    // Only a module that was rewritten is used (one the rewrite refuses falls back to the base module, whose float outputs those targets then do not take: written = 0 below).
    // MOD_UINT_MIXED / MOD_DUAL pipelines keep their variant; a float output there into another integer target stays unwritten (open)
    if (fs && variant == DMSH_VK_MOD_BASE && VKA_ENV("DM_VK_FOUT_RETYPE", 1)) {
        uint32_t fu = 0, fsm = 0;
        for (uint32_t i = 0; i < R.ncolor; i++) if (R.cf[i] && (R.ckind[i] == 1 || R.ckind[i] == 2) && (fs->e->fout_mask >> i & 1) && (fs->e->fout_types >> (2 * i) & 3) == DMSH_VK_TYPE_FLOAT) { if (R.ckind[i] == 1) fu |= 1u << i; else fsm |= 1u << i; }
        if ((fu | fsm) && vka_shader_fout_retyped((vka_shader *)fs, fu, fsm)) variant = VKA_FS_RETYPE;
    }
    k.fs_variant = (uint8_t)variant; k.gs_fx = g_claim_words != 0;
    int src1_used = 0;
    for (uint32_t i = 0; i < R.ncolor; i++) {
        k.cfmt[i] = R.cf[i];
        if (!R.cf[i]) continue;
        uint32_t m = d->chmask.mask >> (4 * i) & 0xf;
        int written = fs && (fs->e->fout_mask >> i & 1);
        int out_cls = !fs ? 0 : variant == DMSH_VK_MOD_UINT || (variant == DMSH_VK_MOD_UINT_MIXED && (fs->e->uint_mask >> i & 1)) ? DMSH_VK_TYPE_UINT : (int)(fs->e->fout_types >> (2 * i) & 3);
        int att_cls = R.ckind[i] == 1 ? DMSH_VK_TYPE_UINT : R.ckind[i] == 2 ? DMSH_VK_TYPE_SINT : DMSH_VK_TYPE_FLOAT;
        if (variant == VKA_FS_RETYPE && out_cls == DMSH_VK_TYPE_FLOAT && att_cls != DMSH_VK_TYPE_FLOAT) out_cls = att_cls;   // (retyped in the module: vka_pso.c fout_masks)
        if (written && out_cls != att_cls) {   // Vulkan leaves a class mismatch undefined: the target is not written (SINT attachments have no variant yet)
            static _Atomic int n; if (atomic_fetch_add(&n, 1) < 4) VRED("fragment shader %016llx writes a %s output to a %s target %u: that target is not written", (unsigned long long)fs->key,
                                                                       out_cls == 0 ? "float" : out_cls == 1 ? "sint" : "uint", att_cls == 0 ? "float" : att_cls == 1 ? "sint" : "uint", i);
            written = 0;
        }
        k.att[i].mask = written ? (uint8_t)m : 0;   // outputs the shader does not write leave the target as it was (Maxwell writes only the shader's outputs)
        if (written && (d->color.blend_en >> i & 1) && att_cls == DMSH_VK_TYPE_FLOAT) {
            blend_st b = adv_blend(d->blend[i]);
            if (variant != DMSH_VK_MOD_DUAL && (is_src1(b.src_rgb) || is_src1(b.dst_rgb) || is_src1(b.src_a) || is_src1(b.dst_a))) {   // no second source: it reads as zero
                src1_used = 1; b.src_rgb = zero_src1(b.src_rgb); b.dst_rgb = zero_src1(b.dst_rgb); b.src_a = zero_src1(b.src_a); b.dst_a = zero_src1(b.dst_a); }
            k.att[i] = (typeof(k.att[i])){1, (uint8_t)bfac(b.src_rgb), (uint8_t)bfac(b.dst_rgb), (uint8_t)bop(b.eq_rgb), (uint8_t)bfac(b.src_a), (uint8_t)bfac(b.dst_a), (uint8_t)bop(b.eq_a), (uint8_t)m};
        }
    }
    // Only mark an attachment producer when a draw CAN write it. Many
    // Ocarina occlusion-query draws only depth-test against existing depth
    // and have all colour writes disabled. Tracking this is necessary to
    // skip redundant pass-end attachment barriers without guessing formats
    // or using a timestamp/driver heuristic. An unknown enabled stencil
    // state is deliberately considered writable.
    if (!d->rast_discard) {
        for (uint32_t i = 0; i < R.ncolor; i++)
            if (k.att[i].mask) { R.awrite = 1; break; }
        if ((R.df != VK_FORMAT_UNDEFINED && d->ds.dt && d->ds.dw) ||
            (R.sf != VK_FORMAT_UNDEFINED && d->ds.st))
            R.awrite = 1;
    }
    if (src1_used) VRED_ONCE("a SRC1 blend factor with no dual-source module (MOD_DUAL; the profile's dual_want.tsv) or no dualSrcBlend: the second source reads as zero");

    PT(3);
    if (!mesh) vin_build_kept(d, sh[0], &k);
    PT(4);
    VkPipeline p = vka_gfx_pipeline(sh, &lay, &k);
    if (!p) SKIPQ();
    if (!DY.valid || !g_dyn_filter || DY.pipe != p) { vk.vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_GRAPHICS, p); DY.pipe = p; VB.vin_stale = 1; }
    if (vka_nan_on()) vka_nan_draw(mesh ? sh[7]->key : sh[0]->key, fs ? fs->key : 0);
    PT(5);
    if (!bind_sets(d, sh, &lay, VK_PIPELINE_BIND_POINT_GRAPHICS, NULL)) SKIPQ();
    texstat_rt(sh[1], rt, has_rt);   // (diagnostic: DM_VK_TEXSTAT_FS)
    PT(6);
    if (!mesh) vin_bind_kept(d);

    // Viewport and scissor. The translator writes clip space for Metal (y up, origin upper left): Metal's viewport, flipped for a lower-left window origin as on Metal, then given
    // a negative height, maps it as Metal does (android/SHADERS.md "Depth and Y")
    float vx = d->has_vp ? d->vp[0][0] : 0, vy = d->has_vp ? d->vp[0][1] : 0, vw = d->has_vp ? d->vp[0][2] : (float)R.area.extent.width, vh = d->has_vp ? d->vp[0][3] : (float)R.area.extent.height;
    if (vka_origin_ll()) { vy += vh; vh = -vh; }
    { uint32_t sw; memcpy(&sw, d->vp_sw[0], 4);
      if (sw == 0x100) { vy += vh; vh = -vh; }
      else if (sw) VRED_ONCE("viewport swizzle %d,%d,%d,%d not implemented (drawn unswizzled)", d->vp_sw[0][0], d->vp_sw[0][1] ^ 2, d->vp_sw[0][2] ^ 4, d->vp_sw[0][3] ^ 6); }
    float n0 = d->dr[0] < 0 ? 0 : d->dr[0] > 1 ? 1 : d->dr[0], n1 = d->dr[1] < 0 ? 0 : d->dr[1] > 1 ? 1 : d->dr[1];
    if (!vw) vw = 1; if (!vh) vh = 1;
    VkViewport vp = {vx, vy + vh, vw, -vh, n0, n1};
    DY_SET(vp, vp, vk.vkCmdSetViewport(g_cb, 0, 1, &vp));
    VkRect2D scr = R.area;
    if (has_sc && !d->rast_discard) {
        int64_t x0 = sc->x < 0 ? 0 : sc->x, y0 = sc->y < 0 ? 0 : sc->y, x1 = (int64_t)sc->x + sc->w, y1 = (int64_t)sc->y + sc->h;
        if (x1 > R.area.extent.width) x1 = R.area.extent.width; if (y1 > R.area.extent.height) y1 = R.area.extent.height;
        if (x1 <= x0 || y1 <= y0) return;   // an empty scissor: nothing drawn
        scr = (VkRect2D){{(int32_t)x0, (int32_t)y0}, {(uint32_t)(x1 - x0), (uint32_t)(y1 - y0)}};
    }
    { int xs = VKA_ENV("DM_VK_XP_SCISSOR", 0);   // experiment (wrong picture): every draw's scissor cut to xs x xs pixels, to split a pass's GPU time into per-pixel and per-draw work
      if (xs > 0) { if (scr.extent.width > (uint32_t)xs) scr.extent.width = (uint32_t)xs; if (scr.extent.height > (uint32_t)xs) scr.extent.height = (uint32_t)xs; } }
    DY_SET(sc, scr, vk.vkCmdSetScissor(g_cb, 0, 1, &scr));
    // Rasterizer and depth / stencil
    DY_SET1(cull, (uint32_t)(d->poly.cull == NVN_FACE_FRONT ? VK_CULL_MODE_FRONT_BIT : d->poly.cull == NVN_FACE_BACK ? VK_CULL_MODE_BACK_BIT : d->poly.cull == NVN_FACE_FRONT_AND_BACK ? VK_CULL_MODE_FRONT_AND_BACK : VK_CULL_MODE_NONE), vk.vkCmdSetCullMode(g_cb, DY.cull));
    DY_SET1(ff, (uint32_t)((d->poly.front == NVN_FRONT_FACE_CCW) != vka_queue_origin_ll() ? VK_FRONT_FACE_COUNTER_CLOCKWISE : VK_FRONT_FACE_CLOCKWISE), vk.vkCmdSetFrontFace(g_cb, DY.ff));   // as nvn_mtl.m's winding
    // A mesh pipeline has no input assembly: the topology and primitive restart are not set for it, and set again at the next draw that has them (its pipeline bind may
    // have left them undefined)
    if (mesh) DY.topo = DY.pr = ~0u;
    else DY_SET1(topo, (uint32_t)(topo), vk.vkCmdSetPrimitiveTopology(g_cb, DY.topo));
    int hd = R.df != VK_FORMAT_UNDEFINED, hs = R.sf != VK_FORMAT_UNDEFINED;
    DY_SET1(dt, (uint32_t)(hd && d->ds.dt), vk.vkCmdSetDepthTestEnable(g_cb, DY.dt));
    DY_SET1(dw, (uint32_t)(hd && d->ds.dt && d->ds.dw), vk.vkCmdSetDepthWriteEnable(g_cb, DY.dw));
    DY_SET1(dc, (uint32_t)(d->ds.df >= 1 && d->ds.df <= 8 ? (VkCompareOp)(d->ds.df - 1) : VK_COMPARE_OP_ALWAYS), vk.vkCmdSetDepthCompareOp(g_cb, DY.dc));
    DY_SET1(dbt, (uint32_t)(VK_FALSE), vk.vkCmdSetDepthBoundsTestEnable(g_cb, DY.dbt));
    DY_SET1(stt, (uint32_t)(hs && d->ds.st), vk.vkCmdSetStencilTestEnable(g_cb, DY.stt));
    #define SOP(x) ((x) >= 1 && (x) <= 8 ? (VkStencilOp)((x) - 1) : VK_STENCIL_OP_KEEP)
    #define SCMP(x) ((x) >= 1 && (x) <= 8 ? (VkCompareOp)((x) - 1) : VK_COMPARE_OP_ALWAYS)
    { uint32_t so[8] = {SOP(d->ds.fail_f), SOP(d->ds.zpass_f), SOP(d->ds.zfail_f), SCMP(d->ds.sf_f), SOP(d->ds.fail_b), SOP(d->ds.zpass_b), SOP(d->ds.zfail_b), SCMP(d->ds.sf_b)};
      DY_SET(sop, so, (vk.vkCmdSetStencilOp(g_cb, VK_STENCIL_FACE_FRONT_BIT, so[0], so[1], so[2], so[3]), vk.vkCmdSetStencilOp(g_cb, VK_STENCIL_FACE_BACK_BIT, so[4], so[5], so[6], so[7]))); }
    #undef SOP
    #undef SCMP
    { uint32_t sm[6] = {d->st_vmask[0], d->st_vmask[1], d->st_wmask[0], d->st_wmask[1], d->st_ref[0], d->st_ref[1]};
      DY_SET(smask, sm, (vk.vkCmdSetStencilCompareMask(g_cb, VK_STENCIL_FACE_FRONT_BIT, sm[0]), vk.vkCmdSetStencilCompareMask(g_cb, VK_STENCIL_FACE_BACK_BIT, sm[1]),
                         vk.vkCmdSetStencilWriteMask(g_cb, VK_STENCIL_FACE_FRONT_BIT, sm[2]), vk.vkCmdSetStencilWriteMask(g_cb, VK_STENCIL_FACE_BACK_BIT, sm[3]),
                         vk.vkCmdSetStencilReference(g_cb, VK_STENCIL_FACE_FRONT_BIT, sm[4]), vk.vkCmdSetStencilReference(g_cb, VK_STENCIL_FACE_BACK_BIT, sm[5]))); }
    int bias_bit = d->poly.mode == NVN_POLYGON_MODE_POINT ? NVN_POLYGON_OFFSET_ENABLE_POINT : d->poly.mode == NVN_POLYGON_MODE_LINE ? NVN_POLYGON_OFFSET_ENABLE_LINE : NVN_POLYGON_OFFSET_ENABLE_FILL;
    int bias = (d->poly.offset_en & bias_bit) != 0;
    DY_SET1(dbe, (uint32_t)(bias), vk.vkCmdSetDepthBiasEnable(g_cb, DY.dbe));
    { float db[3] = {bias ? d->po.units : 0, bias && V.depth_bias_clamp ? d->po.clamp : 0, bias ? d->po.factor : 0}; DY_SET(db, db, vk.vkCmdSetDepthBias(g_cb, db[0], db[1], db[2])); }
    DY_SET1(rd, (uint32_t)(d->rast_discard != 0), vk.vkCmdSetRasterizerDiscardEnable(g_cb, DY.rd));
    DY_SET(bc, d->blend_color, vk.vkCmdSetBlendConstants(g_cb, d->blend_color));
    if (!DY.valid) vk.vkCmdSetLineWidth(g_cb, 1.0f);
    int restart = di && d->restart.on;
    if (restart) { uint32_t all = di->itype == 0 ? 0xff : di->itype == 1 ? 0xffff : 0xffffffffu; if (d->restart.index != all) VRED_ONCE("primitive restart index %#x is not the all-ones index Vulkan restarts at", d->restart.index); }
    if (!mesh) DY_SET1(pr, (uint32_t)(restart), vk.vkCmdSetPrimitiveRestartEnable(g_cb, DY.pr));
    DY.valid = 1;
    vka_oq_draw();   // counting samples passed: the pass's first draw (or the first after a report or reset) begins an occlusion query

    PT(7);
    // The draw. binst (c0 + 0x644 for the stages, vka_bind.c) is the CPU record's base instance, 0 for an indirect draw; vertex shaders read the word from BaseInstance instead
    // (vk_android_spv.py base_instance), which is each indirect draw's own firstInstance and binst for the direct ones; the build reports any other stage that reads it
    uint32_t inst = (uint32_t)((dw ? dw->instances : di->instances) > 0 ? (dw ? dw->instances : di->instances) : 1), binst = d->b.base_instance;
    if (mesh && dw->ind) vk.vkCmdDrawMeshTasksIndirectEXT(g_cb, mi.buf, mi.off, 1, 12);   // the {count, 1, 1} record mesh_ind_args made
    else if (memu_e) {
        VkDeviceSize ro = MB.rec.off + ((VkDeviceSize)memu_e->rec * VKA_MEMU_REC_WORDS + VKA_MEMU_R_DRAW) * 4;
        if (memu_e->indexed) { ib_bind(MB.arena, 0, VK_INDEX_TYPE_UINT32); vk.vkCmdDrawIndexedIndirect(g_cb, MB.rec.buf, ro, 1, 20); }
        else vk.vkCmdDrawIndirect(g_cb, MB.rec.buf, ro, 1, 16);
    } else if (mesh) {   // count workgroups of the task shader, or of the mesh shader without one (the device's limit per dimension: maxTaskWorkGroupCount / maxMeshWorkGroupCount, 65535 on the Adreno 840)
        static uint32_t largest; if ((uint32_t)dw->count > largest) { largest = (uint32_t)dw->count; static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VLOG("mesh draw: largest so far %u workgroups (task %016llx mesh %016llx)", largest, sh[6] ? (unsigned long long)sh[6]->key : 0ull, (unsigned long long)sh[7]->key); }
        uint32_t maxg = sh[6] ? V.task_groups : V.mesh_groups;
        if ((uint32_t)dw->count > maxg) SKIP("mesh draw of %d workgroups: more than the device's %u in one dimension; skipped", dw->count, maxg);
        vk.vkCmdDrawMeshTasksEXT(g_cb, (uint32_t)dw->count, 1, 1);
    } else if (expand) {   // quads or a line loop: the indices made here, 32-bit, in scratch memory
        uint32_t count = (uint32_t)(dw ? dw->count : di->count), *src = NULL;
        if (di && !(src = read_indices(di->ibuf, di->itype, count))) SKIP("indices at %#llx are not readable: the draw is skipped", (unsigned long long)di->ibuf);
        uint32_t nout = expand == 1 ? count / 4 * 6 : count + 1; vka_span s;
        if (!nout || !vka_scratch(4 * (VkDeviceSize)nout, 4, &s)) { free(src); return; }
        uint32_t *o = (uint32_t *)s.ptr, base = dw ? (uint32_t)dw->first : 0;
        #define IX(i) (src ? src[i] : base + (i))
        if (expand == 1) for (uint32_t q = 0; q < count / 4; q++) { static const uint8_t t[6] = {0, 1, 2, 0, 2, 3}; for (int j = 0; j < 6; j++) o[6 * q + j] = IX(4 * q + t[j]); }
        else { for (uint32_t i = 0; i < count; i++) o[i] = IX(i); o[count] = IX(0); }
        #undef IX
        free(src);
        ib_bind(s.buf, s.off, VK_INDEX_TYPE_UINT32);
        vk.vkCmdDrawIndexed(g_cb, nout, inst, 0, di ? di->base_vertex : 0, binst);
    } else if (dw) {
        if (ind) { VkBuffer b; VkDeviceSize o; if (!vka_addr(ind, mdi ? (uint64_t)(mdi_max - 1) * mdi_stride + 16 : 16, &b, &o, NULL) || (o & 3)) SKIP("indirect draw arguments at %#llx are not in placed guest RAM: skipped", (unsigned long long)ind);
                   if (mdi) vk.vkCmdDrawIndirectCount(g_cb, b, o, mdi_buffer, mdi_offset, mdi_max, mdi_stride); else vk.vkCmdDrawIndirect(g_cb, b, o, 1, 16); }
        else vk.vkCmdDraw(g_cb, (uint32_t)dw->count, inst, (uint32_t)dw->first, binst);
    } else {
        VkBuffer ib; VkDeviceSize io; VkIndexType it = di->itype == 0 ? VK_INDEX_TYPE_UINT8 : di->itype == 1 ? VK_INDEX_TYPE_UINT16 : VK_INDEX_TYPE_UINT32;
        size_t isz = di->itype == 0 ? 1 : di->itype == 1 ? 2 : 4;
        if (it == VK_INDEX_TYPE_UINT8 && !V.idx8) {   // 8-bit indices on a device without them: widened on the CPU
            if (ind) SKIP("an indirect draw of 8-bit indices on a device without them: skipped");
            uint32_t *src = read_indices(di->ibuf, 0, (uint32_t)di->count); vka_span s;
            if (!src || !vka_scratch(2 * (VkDeviceSize)di->count + 4, 4, &s)) { free(src); SKIP("8-bit indices at %#llx not readable: skipped", (unsigned long long)di->ibuf); }
            for (int i = 0; i < di->count; i++) ((uint16_t *)s.ptr)[i] = (uint16_t)src[i];
            free(src); ib = s.buf; io = s.off; it = VK_INDEX_TYPE_UINT16;
            if (restart) VRED_ONCE("primitive restart with widened 8-bit indices");
        } else if (!vka_addr(di->ibuf, ind ? isz : isz * (uint64_t)(di->count > 0 ? di->count : 1), &ib, &io, NULL) || io % isz) SKIP("index buffer at %#llx is not in placed guest RAM: skipped", (unsigned long long)di->ibuf);
        ib_bind(ib, io, it);
        if (ind) { VkBuffer b; VkDeviceSize o; if (!vka_addr(ind, mdi ? (uint64_t)(mdi_max - 1) * mdi_stride + 20 : 20, &b, &o, NULL) || (o & 3)) SKIP("indirect draw arguments at %#llx are not in placed guest RAM: skipped", (unsigned long long)ind);
                   if (mdi) vk.vkCmdDrawIndexedIndirectCount(g_cb, b, o, mdi_buffer, mdi_offset, mdi_max, mdi_stride); else vk.vkCmdDrawIndexedIndirect(g_cb, b, o, 1, 20); }
        else vk.vkCmdDrawIndexed(g_cb, (uint32_t)di->count, inst, 0, di->base_vertex, binst);
    }
    if (vka_gp_active)
        vka_gp_draw(sh[0] ? sh[0]->key : 0, sh[1] ? sh[1]->key : 0, sh[7] ? sh[7]->key : 0,
                    sh[6] ? sh[6]->key : 0,
                    (uint32_t)(dw ? dw->count : di->count), inst, ind != 0);
    draw_log(d, sh, dw, di);
    g_draws++;
    texstat_at();   // (diagnostic: DM_VK_TEXSTAT_AT)
    PT(8);
    if (vka_nan_on() >= 2 && vka_nan_split(R.cim, R.nci)) vka_rp_end();   // DM_VK_NANSCAN=2: a scan inside the game's pass
}

int dm_sdk_ounce(void);
static int g_nvn2 = -1;
void vka_set_nvn2(int on) { g_nvn2 = on != 0; }
int vka_nvn2(void) { if (g_nvn2 < 0) g_nvn2 = dm_sdk_ounce(); return g_nvn2; }   // first called at a dispatch or a capture, after the modules are loaded
void vka_dispatch(vka_dstate *d, const p_dispatch *dp) {
    if (!g_cb || !draws_on() || !statics()) SKIPQ();
    if (!d->inited) vka_dstate_reset(d);
    vka_rp_end();
    // GPU profiler on Build 53: several 0x0x0 guest compute records (e.g.
    // cee08c634ef1f343, 510c344f1b4e4e55, e855420a39e60874)
    // still allocate descriptors and issue a full VkMemoryBarrier, although
    // Vulkan dispatch is intentionally NOT emitted for any zero dimension.
    // These have no shader invocations and no observable shader writes.
    // Preserve the guest dispatch constants and the earlier pass boundary,
    // and flush any actual pending producers from dispatch overlap.
    // The guest's explicit OP_BARRIER remains independent and untouched.
    // Indirect dispatches are excluded because GPU-written counts are not
    // inspectable without a readback.
    if (!dp->ind && (dp->x <= 0 || dp->y <= 0 || dp->z <= 0) &&
        !strcmp(DM_GAME_ID, "0400486024DEC000") &&
        !vka_gp_active && VKA_ENV("DM_VK_OOT_ZERO_DISPATCH", 1)) {
        d->b.dispatch[0] = (uint32_t)dp->x;
        d->b.dispatch[1] = (uint32_t)dp->y;
        d->b.dispatch[2] = (uint32_t)dp->z;
        d->b.nvn2 = (uint32_t)vka_nvn2();
        vka_dispatch_overlap_flush();
        g_dispatches++;
        return;
    }
    vka_shader *sh[VKA_NSTAGE] = {0}; unsigned bad = 0;
    if (!resolve(d->cprog, 5, &sh[5], &bad)) SKIP("dispatch skipped: no shader library");
    if (bad) SKIPQ();
    if (!sh[5]) SKIP("dispatch with no compute shader bound: skipped");
    vka_layout lay; if (!vka_layout_of(sh, 1, &lay)) SKIP("dispatch skipped: no pipeline layout");
    walk_all(d, sh);   // bindings are evaluated once before any pipeline
    oot_sgsr_chain_frame();
    int chain_part = oot_sgsr_chain_part(sh[5]->key), scene_linear = 0;
    int scene_binding = -1, scene_previous_tid = 0;
    if (!dp->ind && g_wk.n[5] > 0 && g_oot_sgsr_chain.primed &&
        oot_sgsr_chain_on()) {
        if (chain_part == 2) {
            // Capture the SAME first texture ID that iOS V19 takes from the
            // first shader's bound input. Reject sampler-only entries and
            // larger scenes: 0.6 / 0.667 must continue their own networks.
            for (int i = 0; i < g_wk.n[5]; i++) {
                vka_res *r = &g_wk.r[5][i];
                if (r->what != VKA_R_TEX || r->tid <= 0) continue;
                vka_img *src = vka_tex_id_img(r->tid, g_cb);
                if (src && src->f.kind == 0 &&
                    src->f.vk == VK_FORMAT_B10G11R11_UFLOAT_PACK32 &&
                    src->w > 0 && src->h > 0 &&
                    // 0.6/0.667 of the guest's 1440x810 scene can still
                    // fit within 1024x576. Those scales end at DIFFERENT
                    // networks and cannot be short-circuited to d99.
                    // Only arm source capture for a plausible <=0.25 image.
                    src->w <= 640 && src->h <= 360 &&
                    src->samples == 1 &&
                    (src->usage & VK_IMAGE_USAGE_SAMPLED_BIT)) {
                    g_oot_sgsr_chain.source_tid = r->tid;
                }
                break;
            }
        }
        if (g_oot_sgsr_chain.source_tid &&
            (chain_part == 1 || chain_part == 2)) {
            g_oot_sgsr_chain.skipped++;
            g_oot_sgsr_chain.bypassed++;
            return; // the d99fbeeb stage will write the original game image
        }
        if (chain_part == 3 && g_oot_sgsr_chain.source_tid) {
            for (int i = 0; i < g_wk.n[5]; i++) {
                vka_res *r = &g_wk.r[5][i];
                if (r->what != VKA_R_TEX || r->tid <= 0) continue;
                scene_binding = i;
                scene_previous_tid = r->tid;
                r->tid = g_oot_sgsr_chain.source_tid;
                scene_linear = 1;
                break;
            }
        }
    }
    vka_imgrt rt; img_retype_of(sh[5], g_wk.r[5], g_wk.n[5], &rt);
    vka_ndsr_launch ndsr_launch={0};
    VkPipeline p = vka_ndsr_pipeline(d, sh[5], &lay, g_wk.r[5], g_wk.n[5], &rt, g_cb,
                                     scene_linear, !dp->ind, &ndsr_launch);
    if (scene_linear && !p) {
        // The last stage's output/pipeline failed its runtime checks after
        // earlier stages were skipped. Restore the old flow on later frames.
        // Never allow another frame to skip anything on this unsafe path.
        g_oot_sgsr_chain.refused = 1;
        // Restore the guest's original descriptor before trying its original
        // pipeline for this frame. Never bind an unexpected scene source to
        // an arbitrary original network just because the replacement failed.
        if (scene_binding >= 0) {
            g_wk.r[5][scene_binding].tid = scene_previous_tid;
            img_retype_of(sh[5], g_wk.r[5], g_wk.n[5], &rt);
        }
        VRED_ONCE("Ocarina SGSR chain: d99fbeeb refused the direct HDR input; "
                  "original chain restored for subsequent frames");
    }
    const int gp_ndsr_replaced = p != VK_NULL_HANDLE;
    uint32_t ndsr_ow=ndsr_launch.width,ndsr_oh=ndsr_launch.height,ndsr_tile=ndsr_launch.tile;
    int oot_cs_retiled = 0;
    // The hot 9e6b kernel uses an 8x9x12 direct grid and 8x4x4 local size
    // (110,592 invocations). Try a *different* pipeline with 8x4x2 local
    // size and 8x9x24 grid, keeping every GlobalInvocationId unchanged.
    // Only if the SPIR-V safety scan confirms no local/group-dependent ops.
    // Indirect, image-retyped and any other-size dispatch keeps the original.
    // The GPU profiler measured this one compute dispatch at 0.5-1.4 ms
    // even with SGSR and NDSR retile already running. Its SPIR-V patcher
    // reconstructs original local/group IDs, and refuses barriers,
    // shared/workgroup memory, atomics and escaping builtin pointers. The
    // 8x4x4*8x9x12 -> 8x4x2*8x9x24 mapping preserves the SAME 110,592
    // invocations, with no change to the game's library or output.
    // Enable automatically for the EXACT known size, independent of the
    // quality-reducing FPS Boost/VRS option. DM_VK_OOT_CS_RETILE=0 restores
    // the original pipeline. If the original shader fails the safety scan
    // or Vulkan rejects the variant, keep the original compute unmodified.
    if (!p && sh[5]->key == UINT64_C(0x9e6b00b050e30801)
        && !strcmp(DM_GAME_ID, "0400486024DEC000")
        && VKA_ENV("DM_VK_OOT_CS_RETILE", 1)
        && !rt.b[0] && !dp->ind && !spill_bytes(sh[5])
        && dp->x == 8 && dp->y == 9 && dp->z == 12
        && V.props.limits.maxComputeWorkGroupCount[2] >= 24) {
        p = vka_cs_pipeline_oot_retile(sh[5], &lay, &oot_cs_retiled);
        if (oot_cs_retiled) { static _Atomic int logged;
            if (!atomic_exchange(&logged, 1))
                VLOG("Ocarina GPU profiled compute 9e6b: 8x4x4*8x9x12 -> 8x4x2*8x9x24, equal global invocations; original pipeline preserved; DM_VK_OOT_CS_RETILE=0 disables");
        }
    }
    if (!p) p = rt.b[0] ? vka_cs_pipeline_img(sh[5], &lay, &rt) : vka_cs_pipeline(sh[5], &lay);
    if (vka_nan_on()) vka_tex_watch_dispatch(sh[5]->key);
    if (!p) SKIPQ();
    d->b.dispatch[0] = (uint32_t)dp->x; d->b.dispatch[1] = (uint32_t)dp->y; d->b.dispatch[2] = (uint32_t)dp->z; d->b.nvn2 = (uint32_t)vka_nvn2();
    VkBuffer ib = VK_NULL_HANDLE; VkDeviceSize io = 0;
    if (dp->ind && (!vka_addr(dp->ind, 12, &ib, &io, NULL) || (io & 3))) SKIP("indirect dispatch arguments at %#llx are not in placed guest RAM: skipped", (unsigned long long)dp->ind);
    uint32_t sb = spill_bytes(sh[5]); uint64_t ns = 0;   // shared memory in the spill buffer: the slices this dispatch binds (spill_buf)
    // The replacement NDSR module has local_size_x=128 and a pure
    // grid-stride image walk. The guest HMMA network often launches far
    // fewer groups than there are output pixels, forcing each lane through
    // the bilinear/EASU loop repeatedly. Increase ONLY the replacement's
    // dispatch groups, targeting <=2 output texels per lane. The original
    // shader never sees changed group sizes; no 42k shader rebuild or new
    // SPIR-V is required. If resources, driver limits, or diagnostics do
    // not support it, preserve the original launch unmodified.
    uint32_t ndsr_groups_x = 0;
    if (gp_ndsr_replaced && !ndsr_tile && !dp->ind && !sb && !vka_gp_active &&
        !vka_nan_on() && !strcmp(DM_GAME_ID, "0400486024DEC000") &&
        VKA_ENV("DM_VK_OOT_NDSR_RETILE", 1) &&
        dp->x > 0 && dp->y > 0 && dp->z > 0) {
        uint64_t native = (uint64_t)dp->x * (uint64_t)dp->y * (uint64_t)dp->z;
        ndsr_groups_x = vka_ndsr_grid_x(ndsr_ow, ndsr_oh, native,
                              V.props.limits.maxComputeWorkGroupCount[0]);
        if (ndsr_groups_x) {
            static _Atomic int noted;
            if (!atomic_exchange(&noted, 1))
                VLOG("Ocarina NDSR compute retile: %llu original HMMA groups -> "
                     "%u 128-lane Vulkan groups for %ux%u output "
                     "(<=2 texels/lane; same exact output, DM_VK_OOT_NDSR_RETILE=0 disables)",
                     (unsigned long long)native, ndsr_groups_x, ndsr_ow, ndsr_oh);
        }
    }
    if (sb || dp->ind) vka_dispatch_overlap_flush(); // spill slices or GPU-sourced indirect arguments cannot overlap an earlier dispatch
    if (sb) {
        if (!spill_buf(sb)) SKIP("dispatch of %016llx skipped: no shared memory spill buffer of %u bytes", (unsigned long long)sh[5]->key, sb);
        uint64_t cap = g_spill_cap / sb, total = dp->ind ? cap : (uint64_t)(dp->x > 0 ? dp->x : 0) * (uint64_t)(dp->y > 0 ? dp->y : 0) * (uint64_t)(dp->z > 0 ? dp->z : 0);
        ns = total < cap ? total : cap; if (!ns) ns = 1;
        g_spill_range = ns * sb;
        if (dp->ind) VRED_ONCE("indirect dispatch of a program with its shared memory in the spill buffer (%016llx): its %llu slices are shared by workgroups that many apart", (unsigned long long)sh[5]->key, (unsigned long long)ns);
    }
    c0_at c0 = {0};
    g_rt5 = rt.b[0] ? &rt : NULL;
    g_ndsr_linear_binding=ndsr_launch.input_binding;g_ndsr_linear_sampler=ndsr_launch.sampler;
    int bound_ = bind_sets(d, sh, &lay, VK_PIPELINE_BIND_POINT_COMPUTE, &c0);
    g_ndsr_linear_sampler=VK_NULL_HANDLE;
    g_rt5 = NULL;
    if (!bound_) {
        if (scene_linear) g_oot_sgsr_chain.refused = 1;
        SKIPQ();
    }
    if (dp->ind && c0.buf) {   // the group counts the GPU wrote, into c0's dispatch words before the dispatch reads them (nvn_mtl.m g_c0_dim_buf); NVN2 reads them at c0 + 4 too
        VkBufferCopy c[2] = {{io, c0.off + DMSH_C0_DISPATCH, 12}, {io, c0.off + DMSH_C0_DISPATCH_NVN2, 12}};
        vk.vkCmdCopyBuffer(g_cb, ib, c0.buf, d->b.nvn2 ? 2 : 1, c);
        vka_barrier(g_cb);
    }
    // DM_VK_DISPATCH_LOG=1: one line per dispatch (its index in the submission's run of dispatches since the last log reset, key, groups, workgroup, shared memory, flags);
    // DM_VK_DISPATCH_SKIP=<from>[,<to>]: dispatches from..to (default: to the end) are recorded without their vkCmdDispatch, to find the one that writes a wrong picture
    // DM_VK_DISPATCH_SKIP_KEY=<hex key>[,<key>...] (diagnostic): the dispatches of these shaders are recorded without their vkCmdDispatch. Both are read once a frame
    uint64_t vka_frame(void); static unsigned long long nd; static uint64_t fr = ~0ull; static int lg; static char sk[64], kk[256];
    if (vka_frame() != fr) { fr = vka_frame(); lg = (int)VKA_ENV("DM_VK_DISPATCH_LOG", 0); nd = 0;
                             if (!vka_env_str("DM_VK_DISPATCH_SKIP", sk, sizeof sk)) sk[0] = 0; if (!vka_env_str("DM_VK_DISPATCH_SKIP_KEY", kk, sizeof kk)) kk[0] = 0; }
    unsigned long long di = nd++; int skip = 0;
    if (sk[0]) { char *e; unsigned long long a = strtoull(sk, &e, 10), b = *e == ',' ? strtoull(e + 1, NULL, 10) : ~0ull; skip = di >= a && di <= b; }
    for (const char *q = kk; *q;) { char *e; unsigned long long kv = strtoull(q, &e, 16); if (e == q) break; if (kv == (unsigned long long)sh[5]->key) skip = 1; q = *e == ',' ? e + 1 : e; }
    if (lg) VLOG("dispatch %llu: %016llx groups %d,%d,%d%s local %u,%u,%u shared %u flags %#x%s", di, (unsigned long long)sh[5]->key, dp->x, dp->y, dp->z, dp->ind ? " (indirect)" : "",
                 sh[5]->e->local[0], sh[5]->e->local[1], sh[5]->e->local[2], sh[5]->e->shared, sh[5]->e->flags, skip ? " SKIPPED" : "");
    if (lg >= 2) for (int i = 0; i < g_wk.n[5]; i++) {   // DM_VK_DISPATCH_LOG=2 (diagnostic): its buffers, with DM_VK_DRAW_LOG_UBO their first floats; its textures
        const vka_res *r = &g_wk.r[5][i];
        if (r->what == VKA_R_BUF) {
            VLOG("dispatch %llu:   binding %u %s %#llx+%#llx%s", di, r->binding, r->desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER ? "storage buffer" : "uniform buffer", (unsigned long long)r->addr, (unsigned long long)r->size, (r->flags & DMSH_VK_BF_RW) ? " (written)" : "");
            int nf = VKA_ENV("DM_VK_DRAW_LOG_UBO", 0);
            if (nf > 0 && r->addr) { if (nf > 256) nf = 256; if ((uint64_t)nf * 4 > r->size) nf = (int)(r->size / 4);
                float fv[256]; if (nf > 0 && cpu_read(r->addr, fv, (size_t)nf * 4)) { char fb[4096]; size_t fo = 0;
                    for (int q = 0; q < nf && fo < sizeof fb - 32; q++) fo += (size_t)snprintf(fb + fo, sizeof fb - fo, "%s%g", q ? " " : "", fv[q]);
                    VLOG("dispatch %llu:     binding %u floats: %s", di, r->binding, fb); } }
        } else if (r->what == VKA_R_TEX || r->what == VKA_R_IMG) { char why[400]; vka_tex_id_desc(r->tid, why, sizeof why);
            VLOG("dispatch %llu:   binding %u%s texture ID %d: %s", di, r->binding, r->what == VKA_R_IMG ? " (image)" : "", r->tid, why); }
        else if (r->what == VKA_R_GMEM_MAP || r->what == VKA_R_GMEM_LOG) VLOG("dispatch %llu:   binding %u raw global memory %s", di, r->binding, r->what == VKA_R_GMEM_MAP ? "table" : "write log");
    }
    if (skip) { vka_barrier(g_cb); g_dispatches++; texstat_at(); return; }
    if (vka_gp_active) vka_gp_compute(sh[5]->key, ndsr_tile ? (ndsr_ow + ndsr_tile - 1) / ndsr_tile : (uint32_t)dp->x,
        ndsr_tile ? (ndsr_oh + ndsr_tile - 1) / ndsr_tile : (uint32_t)dp->y,
        ndsr_tile ? 1u : (uint32_t)dp->z * (oot_cs_retiled ? 2u : 1u), gp_ndsr_replaced);
    vk.vkCmdBindPipeline(g_cb, VK_PIPELINE_BIND_POINT_COMPUTE, p);
    if (dp->ind) vk.vkCmdDispatchIndirect(g_cb, ib, io);
    else if (dp->x > 0 && dp->y > 0 && dp->z > 0) {
        if (ndsr_tile) {
            vk.vkCmdPushConstants(g_cb,lay.layout,VK_SHADER_STAGE_COMPUTE_BIT,0,sizeof ndsr_launch.push,&ndsr_launch.push);
            vk.vkCmdDispatch(g_cb,(ndsr_ow+ndsr_tile-1)/ndsr_tile,(ndsr_oh+ndsr_tile-1)/ndsr_tile,1);
        }
        else if (ndsr_groups_x) vk.vkCmdDispatch(g_cb, ndsr_groups_x, 1, 1);
        else if (sb && (uint64_t)dp->x * dp->y * dp->z > ns) spill_dispatch((uint32_t)dp->x, (uint32_t)dp->y, (uint32_t)dp->z, ns);
        else vk.vkCmdDispatch(g_cb, (uint32_t)dp->x, (uint32_t)dp->y,
                               (uint32_t)dp->z * (oot_cs_retiled ? 2u : 1u));
    }
    // Ocarina's 9e6b compute appears twice per frame in heavy scenes.
    // Keep every workgroup and shader output. Narrow only the barrier's
    // producer stages; all later GPU consumers stay synchronized.
    // Backport of the iOS dispatch_overlap mechanism: when the next NVN
    // command is another compute dispatch (possibly with intervening bindings)
    // and the guest requested no barrier, there is no guest-visible ordering to force.
    // Group them on the GPU; close the group with a single barrier before any
    // non-dispatch operation (or before another dispatch using host spill).
    // Never group indirect dispatches, shared-memory spill, the GPU profiler
    // or NaN instrumentation. The explicit NVN OP_BARRIER is never skipped.
    if (!sb && !dp->ind && !vka_gp_active && !vka_nan_on()
        && VKA_ENV("DM_VK_OOT_DISPATCH_OVERLAP", 0)) {
        g_dispatch_overlap_pending = 1;
        g_dispatch_overlap_skipped++;
    } else {
        g_dispatch_overlap_pending = 0;
        // Profiled hot Ocarina compute dispatches have only compute/transfer
        // producer writes. Retain ALL_COMMANDS visibility for every later
        // graphics/compute/transfer consumer, but remove unrelated graphics
        // producer stages from the post-dispatch barrier. This applies
        // without FPS Boost and leaves indirect/spill dispatches unchanged.
        if (!strcmp(DM_GAME_ID, "0400486024DEC000") &&
            !sb && !dp->ind && VKA_ENV("DM_VK_OOT_CS_SYNC", 1) &&
            (sh[5]->key == UINT64_C(0x9e6b00b050e30801) ||
             sh[5]->key == UINT64_C(0x9ed48d1011f1b48b)))
            vka_compute_write_barrier(g_cb);
        else
            vka_barrier(g_cb); // the final dispatch publishes all grouped writes
    }
    if (chain_part == 3 && p && !dp->ind && oot_sgsr_chain_on()) {
        // Mark as proven only AFTER descriptor binding and Vulkan dispatch.
        // Future frames may then omit the 3 upstream network dispatches.
        g_oot_sgsr_chain.primed = 1;
        if (scene_linear) {
            g_oot_sgsr_chain.completed = 1;
            static int note;
            if (!note++) VLOG("Ocarina SGSR1 0.25 chain: took scene HDR directly "
                             "at d99fbeeb; skipped %d original GPU dispatches "
                             "in this frame, EASU conversion in-chain, SGSR1 "
                             "single-pass final present", g_oot_sgsr_chain.skipped);
        }
    }
    g_dispatches++;
    texstat_at();   // (diagnostic: DM_VK_TEXSTAT_AT, a compute key's textures and buffers)
}
void vka_draw_stats(uint64_t *draws, uint64_t *skipped, uint64_t *dispatches, uint64_t *pipelines) {
    if (draws) *draws = g_draws; if (skipped) *skipped = g_skipped; if (dispatches) *dispatches = g_dispatches; if (pipelines) *pipelines = 0;
}
#endif
