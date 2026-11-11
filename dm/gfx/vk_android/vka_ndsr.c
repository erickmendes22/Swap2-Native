// agl's NDSR upscaler network replaced by FSR 1 EASU on the Vulkan replay (DM_VK_NDSR=fsr; docs/reference/rendering.md "agl's NDSR upscaler network replaced by FSR 1
// EASU on the Vulkan replay"). agl's light upscaler (agl_ndsr_vr_light.pck; Zelda: Ocarina of Time's fa3033d05c0a41d6) is a purely spatial network: one sampled input,
// one storage output, its weights in a storage buffer, and its sizes in the push bank (no history, motion or depth). Its HMMA blocks have no tensor cores to run on
// here: about 7.2 ms of a 33 ms frame on the Adreno 830. This is a deliberate workaround for that platform limit, opt-in and with a quality loss: the dispatch keeps
// its slot, descriptors and group count, and its pipeline is our own compute (fsr/ndsr_easu.comp), FSR 1 EASU from the network's input to its output. The three
// cheap anti-aliasing passes before it (edge classification, blend weights, the blend that packs the input) stay as they are. An output format without storage
// support (Zelda's B10G11R11_UFLOAT on Adreno, where a float storage view of it is refused and its stores go nowhere) takes the packed variant: each texel's 32-bit
// word stored through an R32_UINT view, the binding entered in the dispatch's vka_imgrt so stage_writes asks for that view (vka_ndsr_pipeline).
// Switches (live): DM_VK_NDSR = net (default: the network) | fsr (EASU) | bilinear; DM_VK_NDSR_INPUT = linear (default) | sqrt (the input holds sqrt(colour), the
// output the colour: agl's light upscaler, whose blend a335c1db6270c355 packs sqrt as RGB9E5); DM_VK_NDSR_MAP = full (default: the whole input onto the whole
// output) | push (agl's push bank mapping, experimental); DM_VK_NDSR_LOG=1: the push bank once per input and output size
#include "vka_ndsr.h"
#include "vka_ndsr_spv.h"
#include <stdlib.h>
#include <string.h>

// ---------- Plain C (the PC test builds this part with VKA_NDSR_PURE) ----------
#define DESC_COMBINED 1   // VkDescriptorType: VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER
#define DESC_STORAGE_IMAGE 3
#define DESC_UNIFORM_BUFFER 6
int vka_ndsr_match(const dmsh_vk_entry *e, const dmsh_vk_bind *b, uint16_t *tex_b, uint16_t *img_b, uint16_t *bank_b) {
    if (!e || !b || e->stage != DMSH_VK_STAGE_CS || !(e->flags & DMSH_VK_F_HMMA)) return 0;
    int nt = 0, ni = 0, ns = 0, nb = 0;
    const uint8_t plain = DMSH_VK_DIM_ARRAY | DMSH_VK_DIM_MS | DMSH_VK_DIM_DEPTH | DMSH_VK_DIM_SINT | DMSH_VK_DIM_UINT;
    for (unsigned i = 0; i < e->bind_count; i++) {
        const dmsh_vk_bind *x = &b[i];
        switch (x->kind) {
        case DMSH_VK_KIND_TEX:
            if (x->desc != DESC_COMBINED || !x->skind || (x->dim & DMSH_VK_DIM_MASK) != 1 || (x->dim & plain) || x->count > 1) return 0;
            nt++; *tex_b = x->binding; break;
        case DMSH_VK_KIND_IMG:
            if (x->desc != DESC_STORAGE_IMAGE || !(x->flags & DMSH_VK_BF_RW) || (x->flags & DMSH_VK_BF_ATOMIC) || (x->dim & DMSH_VK_DIM_MASK) != 1 || (x->dim & plain) || x->count > 1) return 0;
            ni++; *img_b = x->binding; break;
        case DMSH_VK_KIND_SBUF:
            if (x->flags & DMSH_VK_BF_RW) return 0;
            ns++; break;
        case DMSH_VK_KIND_DRVCB:
            if (x->reg == DMSH_PUSH_BANK) { if (x->desc != DESC_UNIFORM_BUFFER) return 0; nb++; *bank_b = x->binding; }
            break;
        case DMSH_VK_KIND_SUPPORT: break;
        default: return 0;   // anything else (a shared memory spill buffer, global memory, pools, more textures): not this interface
        }
    }
    return nt == 1 && ni == 1 && ns == 1 && nb == 1;
}
int vka_ndsr_pack_of(int vkformat) { return vkformat == 122 ? VKA_NDSR_PACK_B10G11R11 : vkformat == 37 ? VKA_NDSR_PACK_RGBA8 : VKA_NDSR_PACK_NONE; }   // (VkFormat numbers)
uint32_t *vka_ndsr_words(int packed, uint16_t tex_b, uint16_t img_b, uint16_t bank_b, size_t *n) {
    const uint32_t *src = packed ? vka_ndsr_easu_packed : vka_ndsr_easu;
    size_t bytes = packed ? sizeof vka_ndsr_easu_packed : sizeof vka_ndsr_easu, nw = bytes / 4;
    uint32_t *w = malloc(bytes); if (!w) return NULL;
    memcpy(w, src, bytes);
    int seen = 0;
    for (size_t i = 5; i < nw;) {   // (after the header) OpDecorate <id> Binding <n>: opcode 71, decoration 33
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > nw) { free(w); return NULL; }
        if (op == 71 && len == 4 && w[i + 2] == 33) {
            uint32_t v = w[i + 3];
            if (v == 100) { w[i + 3] = tex_b; seen |= 1; } else if (v == 101) { w[i + 3] = img_b; seen |= 2; } else if (v == 102) { w[i + 3] = bank_b; seen |= 4; }
        }
        i += len;
    }
    if (seen != 7) { free(w); return NULL; }
    *n = nw; return w;
}

#ifndef VKA_NDSR_PURE
// ---------- The replay ----------
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>

static struct { int mode, enc, map, log; } g_sw;   // mode: 0 net, 1 fsr, 2 bilinear
static uint32_t g_sw_gen;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static void switches(void) {   // read again after a live change (vka_env_gen), under g_mu
    uint32_t g = atomic_load(&vka_env_gen);
    if (g == g_sw_gen) return;
    g_sw_gen = g;
    char v[64];
    g_sw.mode = !vka_env_str("DM_VK_NDSR", v, sizeof v) || !strcmp(v, "net") || !strcmp(v, "0") ? 0 : !strcmp(v, "bilinear") ? 2 : !strcmp(v, "fsr") || !strcmp(v, "1") ? 1 : -1;
    if (g_sw.mode < 0) { VRED("DM_VK_NDSR=%s: not net, fsr or bilinear; the network runs", v); g_sw.mode = 0; }
    g_sw.enc = vka_env_str("DM_VK_NDSR_INPUT", v, sizeof v) && !strcmp(v, "sqrt") ? VKA_NDSR_ENC_SQRT : VKA_NDSR_ENC_LINEAR;
    g_sw.map = vka_env_str("DM_VK_NDSR_MAP", v, sizeof v) && !strcmp(v, "push") ? VKA_NDSR_MAP_PUSH : VKA_NDSR_MAP_FULL;
    g_sw.log = vka_env_str("DM_VK_NDSR_LOG", v, sizeof v) && atoi(v) > 0;
}

// Pipelines made, by shader, layout and modes; the sizes logged, by shader and modes; the shaders refused (logged once each). pack: VKA_NDSR_PACK_* (NONE: the float store)
enum { NPIPE = 64, NLOG = 64, NREF = 32 };
static struct { uint64_t key; VkPipelineLayout layout; int enc, map, kernel, pack; VkPipeline p; } g_pipe[NPIPE];
static int g_npipe;
static struct { uint64_t key; uint32_t iw, ih, ow, oh; int enc, map, kernel, pack, push; } g_log[NLOG];
static int g_nlog;
static uint64_t g_ref[NREF]; static int g_nref;
static void refused(uint64_t key, const char *why) {   // under g_mu
    for (int i = 0; i < g_nref; i++) if (g_ref[i] == key) return;
    if (g_nref < NREF) g_ref[g_nref++] = key;
    VRED("NDSR network %016llx not replaced (DM_VK_NDSR): %s; the network runs", (unsigned long long)key, why);
}

static VkPipeline make(vka_shader *cs, const vka_layout *lay, uint16_t tb, uint16_t ib, uint16_t bb, int enc, int map, int kernel, int pack) {   // under g_mu
    for (int i = 0; i < g_npipe; i++)
        if (g_pipe[i].key == cs->key && g_pipe[i].layout == lay->layout && g_pipe[i].enc == enc && g_pipe[i].map == map && g_pipe[i].kernel == kernel && g_pipe[i].pack == pack) return g_pipe[i].p;
    if (g_npipe == NPIPE) { refused(cs->key, "more than 64 pipelines"); return VK_NULL_HANDLE; }
    size_t nw; uint32_t *w = vka_ndsr_words(pack != VKA_NDSR_PACK_NONE, tb, ib, bb, &nw);
    VkPipeline p = VK_NULL_HANDLE; VkShaderModule m = VK_NULL_HANDLE; VkResult r = VK_ERROR_UNKNOWN;
    if (w) {
        VkShaderModuleCreateInfo mi = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = nw * 4, .pCode = w};
        r = vk.vkCreateShaderModule(V.dev, &mi, NULL, &m);
        free(w);
    }
    if (!r) {
        int32_t sv[4] = {enc, map, kernel, pack ? pack : VKA_NDSR_PACK_B10G11R11};   // (the float module has no constant 3: an entry for an absent ID is allowed)
        VkSpecializationMapEntry se[4] = {{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}};
        VkSpecializationInfo si = {4, se, sizeof sv, sv};
        VkComputePipelineCreateInfo ci = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = lay->layout,
            .stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main", .pSpecializationInfo = &si}};
        r = vk.vkCreateComputePipelines(V.dev, VK_NULL_HANDLE, 1, &ci, NULL, &p);   // (a small module: no pipeline cache)
        vk.vkDestroyShaderModule(V.dev, m, NULL);
        if (r) p = VK_NULL_HANDLE;
    }
    if (!p) VRED("NDSR network %016llx: its FSR 1 pipeline was not made (%s %d); the network runs", (unsigned long long)cs->key, w ? "vkCreate*" : "no placeholder bindings in the module", r);
    g_pipe[g_npipe++] = (typeof(g_pipe[0])){cs->key, lay->layout, enc, map, kernel, pack, p};   // (a failure is kept too: not tried again)
    return p;
}

static const vka_res *res_at(const vka_res *r, int n, uint16_t binding) { for (int i = 0; i < n; i++) if (r[i].binding == binding) return &r[i]; return NULL; }

static void log_sizes(const vka_dstate *d, uint64_t key, const vka_res *t, const vka_res *o, const vka_img *b, int enc, int map, int kernel, int pack, VkCommandBuffer cb) {   // under g_mu
    vka_img *a = vka_tex_id_img(t->tid, cb);
    uint32_t iw = a ? a->w : 0, ih = a ? a->h : 0, ow = b ? b->w : 0, oh = b ? b->h : 0;
    int i = 0; while (i < g_nlog && !(g_log[i].key == key && g_log[i].iw == iw && g_log[i].ih == ih && g_log[i].ow == ow && g_log[i].oh == oh && g_log[i].enc == enc && g_log[i].map == map && g_log[i].kernel == kernel && g_log[i].pack == pack)) i++;
    if (i == g_nlog) {
        if (g_nlog == NLOG) return;
        g_log[g_nlog++] = (typeof(g_log[0])){key, iw, ih, ow, oh, enc, map, kernel, pack, 0};
        VLOG("NDSR network %016llx replaced by %s (input %s, %s mapping, %ux%u -> %ux%u; texture IDs %d -> %d; output VkFormat %d %s)", (unsigned long long)key, kernel ? "bilinear" : "FSR 1 EASU",
             enc ? "sqrt" : "linear", map ? "push bank" : "full-image", iw, ih, ow, oh, t->tid, o->tid, b ? (int)b->f.vk : 0,
             pack ? "without storage support: packed words through an R32_UINT view" : "stored as floats");
    }
    if (g_sw.log && !g_log[i].push) {   // agl's c24 as the dispatch sees it (vka_bstate.push[1], the bytes vka_drv_fill copies for DMSH_PUSH_BANK)
        g_log[i].push = 1;
        const uint8_t *p = d->b.push[1];
        for (int row = 0; row < 8; row++) {
            uint32_t u[4]; float f[4]; memcpy(u, p + 16 * row, 16); memcpy(f, p + 16 * row, 16);
            VLOG("NDSR %016llx c24[%d] = %08x %08x %08x %08x (%g %g %g %g) (%d %d %d %d)", (unsigned long long)key, row, u[0], u[1], u[2], u[3], f[0], f[1], f[2], f[3],
                 (int)u[0], (int)u[1], (int)u[2], (int)u[3]);
        }
    }
}

VkPipeline vka_ndsr_pipeline(const vka_dstate *d, vka_shader *cs, const vka_layout *lay, const vka_res *r, int n, vka_imgrt *rt, VkCommandBuffer cb, int source_is_scene_linear) {
    if (!cs || !cs->e || !(cs->e->flags & DMSH_VK_F_HMMA)) return VK_NULL_HANDLE;   // (every other dispatch: one test)
    pthread_mutex_lock(&g_mu);
    switches();
    VkPipeline p = VK_NULL_HANDLE; uint16_t tb = 0, ib = 0, bb = 0;
    if (!g_sw.mode) goto out;
    if (!vka_ndsr_match(cs->e, cs->b, &tb, &ib, &bb)) {   // (another HMMA program: NDVE's movie networks; logged once each, so a network of another interface shows)
        int i = 0; while (i < g_nref && g_ref[i] != cs->key) i++;
        if (i == g_nref && g_nref < NREF) { g_ref[g_nref++] = cs->key; VLOG("NDSR: HMMA compute %016llx is not of agl's network interface: it runs as it is", (unsigned long long)cs->key); }
        goto out;
    }
    const vka_res *t = n > 0 ? res_at(r, n, tb) : NULL, *o = n > 0 ? res_at(r, n, ib) : NULL;
    if (rt && rt->b[0]) { refused(cs->key, "its images are retyped for integer textures"); goto out; }
    if (!t || !o || t->what != VKA_R_TEX || o->what != VKA_R_IMG || t->tid <= 0 || o->tid <= 0) { refused(cs->key, "its input or output has no texture bound"); goto out; }
    // The output's format: a float store needs its storage support. Without it (B10G11R11_UFLOAT on Adreno: vka_tex.c view_of refuses the float storage view, the
    // binding is unbound and the stores go nowhere, the network's as well) the packed variant, through the R32_UINT view id_view gives an unsigned binding of a float
    // texture of 4-byte texels; a format of neither kind: refused (it would be unbound too)
    vka_img *oi = vka_tex_id_img(o->tid, cb);
    if (!oi) { refused(cs->key, "its output texture has no image"); goto out; }
    VkFormatProperties fp; vk.vkGetPhysicalDeviceFormatProperties(V.pd, oi->f.vk, &fp);
    int storage = (fp.optimalTilingFeatures & VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT) != 0, pack = storage ? VKA_NDSR_PACK_NONE : vka_ndsr_pack_of(oi->f.vk);
    if (!storage && !pack) {
        char why[96]; snprintf(why, sizeof why, "its output's VkFormat %d has no storage support and no packed store here", (int)oi->f.vk);
        refused(cs->key, why); goto out;
    }
    if (pack && !rt) { refused(cs->key, "its output needs the packed store and the dispatch passed no vka_imgrt"); goto out; }
    // Ocarina's 7c511 NDSR originally runs the expensive EASU work on a
    // 2048x1152 output after its scene has already rendered at 854x480.
    // The final on-screen FSR chain now processes only <=1280x720. Preserve
    // encoded-colour conversion and the exact full-size output image, but use
    // the SPIR-V's existing one-sample bilinear kernel for the redundant
    // large NDSR stage. EASU still runs once in the 720p final pipeline.
    // This changes actual per-pixel GPU instructions, not a driver variable.
    // The Nov 11 Redmagic gameplay log uses b106afba1a18faa9 for
    // 1275x717 -> 2048x1152, not the earlier 7c511 profile key.
    // The former remained on costly full-resolution EASU even with final
    // SGSR1 (or FSR1) already selected. Only simplify this duplicate large
    // upscale when a final edge-aware upscaler is actually enabled.
    // The bilinear SPIR-V variant keeps sqrt->linear colour conversion,
    // output size, and the exact same storage-image binding.
    // The 2026-11-11 Build 44 Redmagic session requested SGSR1 but
    // actually used rot-linear fallback. Basing this optimization only on
    // the REQUESTED filter removed its only working EASU pass. Default to
    // the validated original b106 network; allow a deliberate A/B experiment
    // only with DM_VK_OOT_NDSR_BILINEAR=1.
    int oot_network = cs->key == UINT64_C(0x7c511cc23ff85d14)
                   || (cs->key == UINT64_C(0xb106afba1a18faa9)
                       && VKA_ENV("DM_VK_OOT_NDSR_BILINEAR", 0));
    int final_upscale = VKA_ENV("DM_VK_PRESENT_FILTER", 0) >= 3;
    int large_oot = g_sw.mode == 1 && oot_network && final_upscale
                    && ((uint64_t)oi->w * oi->h > 1280ull * 720);
    // At 0.25 the iOS V19 chain uses the original scene HDR colour from
    // f896... instead of the three intermediate upscaler outputs. When Vulkan
    // has a confirmed SGSR1 presentation and explicitly substitutes that
    // source for d99fbeeb..., the source is LINEAR HDR, not the sqrt-packed
    // output of a335.... Keep the existing EASU SPIR-V in-chain as a safe
    // colour/size converter; Snapdragon SGSR1 runs at final presentation.
    // Other scales and failed substitutions keep their exact original path.
    if (source_is_scene_linear && cs->key != UINT64_C(0xd99fbeeb53d38847)) {
        refused(cs->key, "scene-linear chain source is only verified for Ocarina scale 0.25");
        goto out;
    }
    // The 0.25 experimental replacement must remove expensive in-game
    // upscaling taps, not run EASU at 2048x1152 and then SGSR again.
    // A cheap full-image bilinear/colour-conversion pass produces the exact
    // output image that later UI passes sample; Qualcomm SGSR1 does the
    // edge-aware reconstruction once at final presentation. If SGSR was not
    // REALLY applied, vka_draw never enables source_is_scene_linear.
    int kernel = (g_sw.mode == 2 || large_oot || source_is_scene_linear)
               ? VKA_NDSR_KERNEL_BILINEAR : VKA_NDSR_KERNEL_EASU;
    int effective_enc = source_is_scene_linear ? VKA_NDSR_ENC_LINEAR : g_sw.enc;
    int effective_map = source_is_scene_linear ? VKA_NDSR_MAP_FULL : g_sw.map;
    if (source_is_scene_linear) {
        static _Atomic int logged_quarter;
        if (!atomic_exchange(&logged_quarter, 1))
            VLOG("Ocarina scale 0.25: native network taps removed; "
                 "linear-HDR to game output using one bilinear colour pass "
                 "(%ux%u); Snapdragon SGSR1 is used at final presentation",
                 oi->w, oi->h);
    }
    if (large_oot) {
        static _Atomic int logged;
        if (!atomic_exchange(&logged, 1))
            VLOG("Ocarina NDSR large-output optimization: replace full %ux%u EASU taps with converted bilinear; EASU+RCAS final capped at 1280x720",
                 oi->w, oi->h);
    }
    p = make(cs, lay, tb, ib, bb, effective_enc, effective_map, kernel, pack);
    if (p && pack) { memset(rt, 0, sizeof *rt); rt->b[0] = (uint32_t)ib << 16 | 33u << 8 | 1u; }   // (the output an unsigned R32ui image: vka_draw.c rt_dim, then id_view)
    if (p) log_sizes(d, cs->key, t, o, oi, effective_enc, effective_map, kernel, pack, cb);
out:
    pthread_mutex_unlock(&g_mu);
    return p;
}
#endif
