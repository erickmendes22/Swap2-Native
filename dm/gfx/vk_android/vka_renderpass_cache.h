// Cached classic render-pass backend from Banana Native Android snapshot
// 0bac816c8470f3b5a65f23dc011bdcc48ffcd59d; adapted to preserve discard operations.
#pragma once
#include "vka_cave_sync.h"
typedef struct { VkFormat cf[8]; uint32_t n; VkFormat ds; uint32_t d, s, samples, clear, discard_load, discard_store; } rpkey;   // clear: bit i colour i, bit 8 depth, bit 9 stencil
// Every shape's render pass is kept for the run (the pipelines made against it hold no reference, but each pass begun with it does until its fence): the list grows, so a
// shape past any cap never makes a new VkRenderPass per pass (the 256-entry array this was did, and leaked one at each)
typedef struct { rpkey k; VkRenderPass rp; } rpent;
static rpent *g_rpc; static int g_nrpc, g_rpcap; static pthread_mutex_t g_rpmu = PTHREAD_MUTEX_INITIALIZER;
static VkAttachmentLoadOp rp_load(const rpkey *k,unsigned bit) {
    return k->clear & (1u<<bit) ? VK_ATTACHMENT_LOAD_OP_CLEAR :
        k->discard_load & (1u<<bit) ? VK_ATTACHMENT_LOAD_OP_DONT_CARE : VK_ATTACHMENT_LOAD_OP_LOAD;
}
static VkAttachmentStoreOp rp_store(const rpkey *k,unsigned bit) {
    return k->discard_store & (1u<<bit) ? VK_ATTACHMENT_STORE_OP_DONT_CARE : VK_ATTACHMENT_STORE_OP_STORE;
}
static void rp_operations(rpkey *k,unsigned bit,const VkRenderingAttachmentInfo *a) {
    if(a->loadOp==VK_ATTACHMENT_LOAD_OP_CLEAR)k->clear|=1u<<bit;
    if(a->loadOp==VK_ATTACHMENT_LOAD_OP_DONT_CARE)k->discard_load|=1u<<bit;
    if(a->storeOp==VK_ATTACHMENT_STORE_OP_DONT_CARE)k->discard_store|=1u<<bit;
}
static VkRenderPass rp_obtain(const rpkey *k) {
    pthread_mutex_lock(&g_rpmu);
    for (int i = 0; i < g_nrpc; i++) if (!memcmp(&g_rpc[i].k, k, sizeof *k)) { VkRenderPass r = g_rpc[i].rp; pthread_mutex_unlock(&g_rpmu); return r; }
    VkAttachmentDescription at[9]; VkAttachmentReference cr[8], dr; uint32_t na = 0;
    VkSampleCountFlagBits sc = (VkSampleCountFlagBits)(k->samples ? k->samples : 1);
    for (uint32_t i = 0; i < k->n; i++) {
        if (k->cf[i] == VK_FORMAT_UNDEFINED) { cr[i] = (VkAttachmentReference){VK_ATTACHMENT_UNUSED, VK_IMAGE_LAYOUT_GENERAL}; continue; }
        at[na] = (VkAttachmentDescription){0, k->cf[i], sc, rp_load(k,i), rp_store(k,i),
                                           VK_ATTACHMENT_LOAD_OP_DONT_CARE, VK_ATTACHMENT_STORE_OP_DONT_CARE, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL};
        cr[i] = (VkAttachmentReference){na++, VK_IMAGE_LAYOUT_GENERAL};
    }
    if (k->ds) {
        at[na] = (VkAttachmentDescription){0, k->ds, sc, rp_load(k,8), rp_store(k,8),
                                           rp_load(k,9), rp_store(k,9), VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL};
        dr = (VkAttachmentReference){na++, VK_IMAGE_LAYOUT_GENERAL};
    }
    VkSubpassDescription sd = {0, VK_PIPELINE_BIND_POINT_GRAPHICS, 0, NULL, k->n, cr, NULL, k->ds ? &dr : NULL, 0, NULL};
    VkSubpassDependency self = vka_cave_depth_self_dependency();
    VkRenderPassCreateInfo ci = {VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount = na, .pAttachments = at, .subpassCount = 1, .pSubpasses = &sd,
        .dependencyCount = k->ds ? 1 : 0, .pDependencies = k->ds ? &self : NULL};
    VkRenderPass r = VK_NULL_HANDLE; VkResult e = vk.vkCreateRenderPass(V.dev, &ci, NULL, &r);
    if (e) { VRED_ONCE("vkCreateRenderPass %d", e); r = VK_NULL_HANDLE; }
    else {
        if (g_nrpc == g_rpcap) { int nc = g_rpcap ? 2 * g_rpcap : 64; rpent *n = realloc(g_rpc, (size_t)nc * sizeof *n); if (n) { g_rpc = n; g_rpcap = nc; } }
        if (g_nrpc < g_rpcap) { g_rpc[g_nrpc].k = *k; g_rpc[g_nrpc++].rp = r; } else VRED_ONCE("render pass list: out of memory");
        if ((g_nrpc & (g_nrpc - 1)) == 0 && g_nrpc >= 256) VLOG("classic render passes: %d shapes", g_nrpc);
    }
    pthread_mutex_unlock(&g_rpmu);
    return r;
}
VkRenderPass vka_rp_compat(const VkFormat *cf, uint32_t n, VkFormat df, VkFormat sf, uint32_t samples) {
    rpkey k; memset(&k, 0, sizeof k);
    if (n > 8) n = 8; memcpy(k.cf, cf, n * sizeof *cf); k.n = n; k.ds = df ? df : sf; k.d = df != 0; k.s = sf != 0; k.samples = samples ? samples : 1;
    return rp_obtain(&k);
}
typedef struct { VkImageCreateFlags fl; VkImageUsageFlags u; uint32_t w, h, nl, nvf; VkFormat vf[6]; } fbatt;
typedef struct { VkRenderPass rp; uint32_t w, h, layers, na; fbatt a[9]; } fbkey;
// Imageless framebuffers by shape, kept for the run (they name no image, so an image's end does not end them). An open-addressed table that doubles at half full: with
// classic passes on, every pipeline is made against a VkRenderPass, so a pass that fell back to dynamic rendering for want of a framebuffer would draw with pipelines
// it is not compatible with
typedef struct { fbkey k; VkFramebuffer fb; uint64_t h; int used; } fbent;
static fbent *g_fbc; static uint32_t g_fbcap, g_fbn;
static uint64_t fb_hash(const fbkey *k) { uint64_t h = 1469598103934665603ull; const uint8_t *p = (const uint8_t *)k; for (size_t i = 0; i < sizeof *k; i++) { h ^= p[i]; h *= 1099511628211ull; } return h; }
static int fb_grow(void) {
    uint32_t nc = g_fbcap ? 2 * g_fbcap : 1024; fbent *n = calloc(nc, sizeof *n);
    if (!n) return 0;
    for (uint32_t i = 0; i < g_fbcap; i++) if (g_fbc[i].used) { uint32_t j = (uint32_t)g_fbc[i].h & (nc - 1); while (n[j].used) j = (j + 1) & (nc - 1); n[j] = g_fbc[i]; }
    free(g_fbc); g_fbc = n; g_fbcap = nc;
    if (nc > 1024) VLOG("classic render passes: framebuffer table %u entries", nc);
    return 1;
}
static VkFramebuffer fb_obtain(const fbkey *k) {   // (the recording thread only)
    if (2 * (g_fbn + 1) > g_fbcap && !fb_grow()) { VRED_ONCE("framebuffer table: out of memory"); return VK_NULL_HANDLE; }
    uint64_t h = fb_hash(k); uint32_t i = (uint32_t)h & (g_fbcap - 1);
    for (; g_fbc[i].used; i = (i + 1) & (g_fbcap - 1)) if (g_fbc[i].h == h && !memcmp(&g_fbc[i].k, k, sizeof *k)) return g_fbc[i].fb;
    VkFramebufferAttachmentImageInfo ai[9];
    for (uint32_t a = 0; a < k->na; a++) ai[a] = (VkFramebufferAttachmentImageInfo){VK_STRUCTURE_TYPE_FRAMEBUFFER_ATTACHMENT_IMAGE_INFO, NULL, k->a[a].fl, k->a[a].u, k->a[a].w, k->a[a].h, k->a[a].nl, k->a[a].nvf, k->a[a].vf};
    VkFramebufferAttachmentsCreateInfo fa = {VK_STRUCTURE_TYPE_FRAMEBUFFER_ATTACHMENTS_CREATE_INFO, NULL, k->na, ai};
    VkFramebufferCreateInfo ci = {VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .pNext = &fa, .flags = VK_FRAMEBUFFER_CREATE_IMAGELESS_BIT, .renderPass = k->rp, .attachmentCount = k->na,
                                  .width = k->w, .height = k->h, .layers = k->layers};
    VkFramebuffer fb = VK_NULL_HANDLE; VkResult e = vk.vkCreateFramebuffer(V.dev, &ci, NULL, &fb);
    if (e) { VRED_ONCE("vkCreateFramebuffer %d", e); return VK_NULL_HANDLE; }
    g_fbc[i].k = *k; g_fbc[i].h = h; g_fbc[i].fb = fb; g_fbc[i].used = 1; g_fbn++;
    return fb;
}
static fbatt fb_att(const vka_img *im, uint32_t lv, uint32_t nl, VkFormat view) {
    fbatt a; memset(&a, 0, sizeof a);
    a.fl = im->cflags; a.u = im->usage; if (view != im->f.vk && (a.u & VK_IMAGE_USAGE_STORAGE_BIT)) a.u &= ~(VkImageUsageFlags)VK_IMAGE_USAGE_STORAGE_BIT;   // (as vka_view restricts an sRGB view)
    a.w = im->w >> lv ? im->w >> lv : 1; a.h = im->h >> lv ? im->h >> lv : 1; a.nl = nl;
    if (im->nvf) { a.nvf = im->nvf; memcpy(a.vf, im->vf, sizeof a.vf); } else { a.nvf = 1; a.vf[0] = view; }
    return a;
}
