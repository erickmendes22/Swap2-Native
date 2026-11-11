// Shaders of the Vulkan replay: the game's library (android/SHADERS.md), its entries as VkShaderModules, and NVN programs resolved to one shader per stage.
// The library is <pack folder>/shaders/v-<DMSH_VK_CHAIN>/dmsh_vk.lib beside its inputs.tsv (the pack folder is the one the modules came from, dm_module_dir), or the file
// DM_VK_SHLIB names. One whose chain, Vulkan chain or game is not this host's is refused with a [RED] line: the game runs on with no draws. While this version's library is
// not in the pack yet (the app's delta update makes it, android/SHADERS.md#delta-updates), another v-<V>/ of the pack whose header carries this host's DMSH_VK_ABI is played
// instead (the newest): what the replay reads of it is the same; the new library is taken from the next start. Modules are made at a program's first draw (the submit
// thread), not at nvnProgramSetShaders
#if defined(__ANDROID__)
#include "vka.h"
#include "../nvn/nvn_mtl.h"
#include "../nvn/dmsh_chain.h"
#include "../nvn/dmsh_chain_vk.h"
#include "game_profile.h"
#include "vka_spvpatch.h"
#include "vka_abi_compat.h"  // audited source-level ABI extension certificates
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#include <time.h>

// Full imported shader library (up to 42k shaders) stays untouched. A newly
// compiled small hot-shader library can override only its listed keys while
// everything else keeps running from the stable full library.
static vka_shlib g_lib, g_hot; static int g_lib_state, g_hot_loaded;   // 0 not tried, 1 loaded, -1 none
static char g_lib_path[1024];                       // the library loaded (vka_shader_lib_path)
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;

// How each stage runs the subgroup operations of a library built for sg lanes (DMSH_VK_F_SUBGROUP shaders). A module built for 64 lanes splits ballots and shuffles into
// 32-lane halves, so it is right on 32 or 64 lanes; one built for n lanes, on n. Per stage, in this order: no subgroup operations in the stage on this device = rewritten
// as one-invocation subgroups (single_lane); a size the library is right for that the device may vary and lets a pipeline pin (subgroupSizeControl, the stage in
// requiredSubgroupSizeStages) = pinned to it (VkPipelineShaderStageRequiredSubgroupSizeCreateInfo, vka_pso.c); the device's fixed size right for the library = as built;
// otherwise (a wrong or varying size that cannot be pinned) = one-invocation subgroups too. Mesa Turnip on the Adreno 840 reports 128 lanes (64-128) with fragment and
// compute pinnable: before this, every stage ran the 64-lane modules at up to 128 lanes (black cave walls in DKB); now fragment and compute are pinned to 64 and the
// vertex, tessellation and geometry stages run one-lane subgroups, as on Qualcomm's driver (which has none in those stages). DM_VK_SUBGROUP_PIN (restart): 0 = no pinning,
// 1 = every stage the device lets pin (default), any other value = a VkShaderStageFlags mask of the stages that may pin (0x30: fragment and compute)
static uint32_t g_sg_pin[8]; static uint8_t g_sg_one[8];   // by DMSH_VK_STAGE_*
static const uint32_t g_stage_bit[8] = {VK_SHADER_STAGE_VERTEX_BIT, VK_SHADER_STAGE_TESSELLATION_CONTROL_BIT, VK_SHADER_STAGE_TESSELLATION_EVALUATION_BIT, VK_SHADER_STAGE_GEOMETRY_BIT,
                                        VK_SHADER_STAGE_FRAGMENT_BIT, VK_SHADER_STAGE_COMPUTE_BIT, VK_SHADER_STAGE_TASK_BIT_EXT, VK_SHADER_STAGE_MESH_BIT_EXT};
static void sg_plan(unsigned sg) {
    static const char *const nm[8] = {"vertex", "tess control", "tess evaluation", "geometry", "fragment", "compute", "task", "mesh"};
#define SG_OK(n) (sg == 64 ? ((n) == 32 || (n) == 64) : (n) == sg)
    unsigned pin = 0; int pm = VKA_ENV("DM_VK_SUBGROUP_PIN", 1); uint32_t pin_stages = pm == 1 ? V.subgroup_req_stages : V.subgroup_req_stages & (uint32_t)pm;
    if (V.subgroup_min != V.subgroup_max && pin_stages)
        for (unsigned c = sg; c >= 32 && !pin; c /= 2) if (SG_OK(c) && c >= V.subgroup_min && c <= V.subgroup_max) pin = c;
    // Turnip's geometry stage computes subgroup operations wrong at a pinned 64 (T30, Mesa 26.3: DKB's terrain culling GS 5d537f7630ec3671 left the cave walls black; one-lane
    // subgroups there drew them right, with every other stage pinned). Eden leaves geometry out of Turnip's subgroup stages too. DM_VK_SUBGROUP_GS (restart): 0 = the geometry
    // stage runs one-lane subgroups, 1 = as the device reports; default 0 on VK_DRIVER_ID_MESA_TURNIP, 1 on other drivers
    uint32_t stages = V.subgroup_stages;
    if (!VKA_ENV("DM_VK_SUBGROUP_GS", V.driver_id != VK_DRIVER_ID_MESA_TURNIP)) stages &= ~(uint32_t)VK_SHADER_STAGE_GEOMETRY_BIT;
    char q[256]; size_t qn = 0; q[0] = 0; int one_new = 0;
    for (int i = 0; i < 8; i++) {
        if (i >= DMSH_VK_STAGE_TS && !V.mesh) continue;
        uint32_t b = g_stage_bit[i]; g_sg_pin[i] = 0; g_sg_one[i] = 0;
        if (!(stages & b)) g_sg_one[i] = 1;
        else if (pin && (pin_stages & b)) g_sg_pin[i] = pin;
        else if (!SG_OK(V.subgroup_size) || V.subgroup_min != V.subgroup_max) g_sg_one[i] = 1, one_new = 1;
        qn += (size_t)snprintf(q + qn, sizeof q - qn, "%s%s %s", i ? ", " : "", nm[i], g_sg_one[i] ? "one lane" : g_sg_pin[i] ? (pin == 64 ? "pinned 64" : "pinned 32") : "as built");
        if (qn >= sizeof q) qn = sizeof q - 1;
    }
#undef SG_OK
    VLOG("subgroup shaders (built for %u lanes; the device's %u, %u-%u, pinnable in %#x, pinned in %#x): %s", sg, V.subgroup_size, V.subgroup_min, V.subgroup_max, V.subgroup_req_stages, pin ? pin_stages : 0, q);
    if (one_new) VLOG("subgroup shaders: stages whose subgroup size is wrong for the library or varies unpinned run them as one-invocation subgroups");
}
uint32_t vka_shader_sg_pin(int stage) { return stage >= 0 && stage < 8 ? g_sg_pin[stage] : 0; }

// Compute shaders' subgroup shuffles through workgroup memory (the library's DMSH_VK_MOD_SHUFFLE_LDS modules, vk_android_spv.py shuffle_lds). Turnip has no
// arbitrary-index shuffle instruction: ir3 makes each OpGroupNonUniformShuffle a loop of rotates, one pass per distinct (index - lane) in the subgroup, and the translator's
// LDSM / MOVM gathers take up to 24 (agl's upscaler network in DKB, 14a8aaf3e0a9edbd: 10.7 ms a dispatch on the Adreno 840, 2.0 ms with the module through workgroup
// memory, upstream BananaNative v0.1.3). Qualcomm's driver shuffles natively and runs the base module faster. DM_VK_SHUFFLE_LDS (restart): 1 = those modules, 0 = the
// base ones; default 1 on VK_DRIVER_ID_MESA_TURNIP, 0 on other drivers. Needs DMSH_VK_SHARED_MAX bytes of shared memory (the library keeps the modules within it).
// The plan is made once, when the library loads, and holds for the whole run: a shader's compute module (and the image-retyped modules made from it) never changes
static int g_shuffle_lds = -1;
static void shuffle_plan(void) {
    int want = VKA_ENV("DM_VK_SHUFFLE_LDS", V.driver_id == VK_DRIVER_ID_MESA_TURNIP) != 0;
    int fits = V.props.limits.maxComputeSharedMemorySize >= DMSH_VK_SHARED_MAX;
    g_shuffle_lds = want && fits;
    VLOG("compute subgroup shuffles: %s", g_shuffle_lds ? "through workgroup memory where the library has the module (DM_VK_SHUFFLE_LDS=0: the instruction)"
         : want ? "the instruction (the device's shared memory is under DMSH_VK_SHARED_MAX)" : "the instruction (DM_VK_SHUFFLE_LDS=1: through workgroup memory)");
}
int vka_shader_cs_variant(vka_shader *s) {
    if (g_shuffle_lds < 0) shuffle_plan();
    // (that module not made: logged by vka_shader_module; the base one)
    return g_shuffle_lds && vka_shlib_module(s->lib, s->e, DMSH_VK_MOD_SHUFFLE_LDS) && vka_shader_module(s, DMSH_VK_MOD_SHUFFLE_LDS) ? DMSH_VK_MOD_SHUFFLE_LDS : DMSH_VK_MOD_BASE;
}
VkShaderModule vka_shader_cs_module(vka_shader *s) { return vka_shader_module(s, vka_shader_cs_variant(s)); }

// Optional alternative module for Ocarina's heavy 9e6b compute. Not an
// in-place change to the game's shader library: the original VkShaderModule
// stays available for indirect and different-size dispatches.
VkShaderModule vka_shader_oot_cs_retile_module(vka_shader *s) {
    if (!s || s->key != UINT64_C(0x9e6b00b050e30801) || !s->e ||
        s->e->stage != DMSH_VK_STAGE_CS || s->e->shared != 0 ||
        (s->e->flags & DMSH_VK_F_SUBGROUP) ||
        s->e->local[0] != 8 || s->e->local[1] != 4 || s->e->local[2] != 4)
        return VK_NULL_HANDLE;
    pthread_mutex_lock(&g_mu);
    if (s->oot_cs_retile_checked) {
        VkShaderModule hit = s->oot_cs_retile_mod;
        pthread_mutex_unlock(&g_mu);
        return hit;
    }
    pthread_mutex_unlock(&g_mu);
    char why[256] = "";
    VkShaderModule mod = VK_NULL_HANDLE;
    // The vendor's native compute shuffle variant is the base module in
    // this Qualcomm driver. If another driver chooses a shuffle-LDS
    // variant, fall back rather than silently bypass its optimization.
    int variant = vka_shader_cs_variant(s);
    if (variant == DMSH_VK_MOD_BASE) {
        const dmsh_vk_module *m = vka_shlib_module(s->lib, s->e, variant);
        size_t bytes = 0;
        uint32_t *words = m ? vka_shlib_spirv(s->lib, m, &bytes, why, sizeof why) : NULL;
        if (words) {
            // The original 9e6b contains group/local builtins and refused
            // the bare LocalSize-only rewrite. A virtual-workgroup variant
            // preserves their original values, using GlobalInvocationId.
            // The exact 8x9x12 direct dispatch is checked at the callsite.
            size_t virtual_n = 0;
            uint32_t *virtual_w = VKA_ENV("DM_VK_OOT_CS_VIRTUAL_RETILE", 1)
                ? vka_spv_oot_cs_virtual_retile(words, bytes / 4,
                                                &virtual_n, why, sizeof why)
                : NULL;
            if (virtual_w || vka_spv_oot_cs_retile(words, bytes / 4,
                                                   why, sizeof why)) {
                VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
                    .codeSize = virtual_w ? virtual_n * 4 : bytes,
                    .pCode = virtual_w ? virtual_w : words};
                VkResult result = vk.vkCreateShaderModule(V.dev, &ci, NULL, &mod);
                if (result) snprintf(why, sizeof why, "VkShaderModule rejected %d", result);
            }
            free(virtual_w);
            free(words);
        }
    } else snprintf(why, sizeof why, "different compute module variant (%d)", variant);
    pthread_mutex_lock(&g_mu);
    if (!s->oot_cs_retile_checked) {
        s->oot_cs_retile_checked = 1;
        s->oot_cs_retile_mod = mod;
    } else if (mod) {
        vk.vkDestroyShaderModule(V.dev, mod, NULL);
    }
    VkShaderModule actual = s->oot_cs_retile_mod;
    pthread_mutex_unlock(&g_mu);
    if (actual == mod) {
        VLOG("Ocarina compute FPS Boost 9e6b: %s (%s); original shader preserved",
             actual ? "8x4x2 optimized workgroups enabled" : "safe retiling unavailable",
             why[0] ? why : "no compatible module");
    }
    return actual;
}

const char *vka_shader_lib_path(void) { return g_lib_path; }

// An ABI digest can change for a purely additive extension (new UNUSED
// descriptor kind/variant/flag). Reusing an old COMPLETE library is safe only
// for an exact old version/ABI/profile tuple certified from both ABI source
// snapshots at build time. Any changed old descriptor value, struct or ABI_REV
// fails the certificate generator; no runtime version-spoofing is permitted.
static int certified_abi_open(vka_shlib *lib, const char *path, char *err, size_t errn) {
    for (unsigned i = 0; i < VKA_ABI_COMPAT_COUNT; i++) {
        const vka_abi_approved *c = &vka_abi_compat[i];
        if (!vka_shlib_open(lib, path, DMSH_CHAIN, DMSH_VK_CHAIN,
                            DM_GAME_ID, c->old_abi, err, errn))
            continue;
        char version[17], inputs[17];
        vka_shlib_str(lib->h->vk_chain, version);
        vka_shlib_str(lib->h->inputs, inputs);
        if (!strcmp(version, c->old_vk) && !strcmp(inputs, c->inputs)
            && !memcmp(lib->h->abi, c->old_abi, 12)) return 1;
        vka_shlib_close(lib);
    }
    return 0;
}

static int lib_load(void) {
    if (g_lib_state) return g_lib_state > 0;
    g_lib_state = -1;
    char path[1024], err[256]; const char *e = getenv("DM_VK_SHLIB"); const char *dir = dm_module_dir(); dir = dir && *dir ? dir : ".";
    if (e && *e) snprintf(path, sizeof path, "%s", e);
    else snprintf(path, sizeof path, "%s/shaders/" DMSH_VK_DIR_PREFIX "%s/" DMSH_VK_LIB_FILE, dir, DMSH_VK_CHAIN);
    int have = !access(path, R_OK) && vka_shlib_open(&g_lib, path, DMSH_CHAIN, DMSH_VK_CHAIN, DM_GAME_ID, DMSH_VK_ABI, err, sizeof err);
    if (!have && !(e && *e)) {   // this version's library not in the pack (yet): the newest other v-<V>/ that this host reads the same (its ABI)
        char why[256]; snprintf(why, sizeof why, "%s", access(path, R_OK) ? "missing" : err);
        char sd[1024], best[1024] = "", compatible[1024] = "", old[1024] = "";
        time_t bt = 0, ct = 0, ot = 0; snprintf(sd, sizeof sd, "%s/shaders", dir);
        DIR *d = opendir(sd); struct dirent *de;
        while (d && (de = readdir(d))) {
            if (strncmp(de->d_name, DMSH_VK_DIR_PREFIX, strlen(DMSH_VK_DIR_PREFIX))) continue;
            char p[1024]; struct stat st; vka_shlib t; char e2[256];
            if (snprintf(p, sizeof p, "%s/%s/" DMSH_VK_LIB_FILE, sd, de->d_name) >= (int)sizeof p || stat(p, &st) || !strcmp(p, path)) continue;
            if (vka_shlib_open(&t, p, DMSH_CHAIN, DMSH_VK_CHAIN, DM_GAME_ID, DMSH_VK_ABI, e2, sizeof e2)) {
                vka_shlib_close(&t);
                if (!*best || st.st_mtime > bt) { snprintf(best, sizeof best, "%s", p); bt = st.st_mtime; }
                continue;
            }
            // A certified additive ABI extension allows the *original*
            // library to stay mapped without copying or rebuilding 42k SPIR-V
            // modules. Only source-level-audited transitions appear here.
            if (certified_abi_open(&t, p, e2, sizeof e2)) {
                vka_shlib_close(&t);
                if (!*compatible || st.st_mtime > ct) {
                    snprintf(compatible, sizeof compatible, "%s", p); ct = st.st_mtime;
                }
                continue;
            }
            // A library made before the abi field (all zero): its ABI is not known, so it is the last resort, played with a warning rather than nothing drawn
            // (the user's choice: never block Play on it; the app suggests one more shader update, after which updates are deltas of the same ABI)
            int legacy = vka_shlib_open(&t, p, NULL, NULL, DM_GAME_ID, NULL, e2, sizeof e2);
            if (legacy) { static const char z[12]; legacy = !memcmp(t.h->abi, z, sizeof z); vka_shlib_close(&t); if (!legacy) snprintf(e2, sizeof e2, "another ABI than this host's %s", DMSH_VK_ABI); }
            if (!legacy) { VLOG("shader library %s not usable here: %s", p, e2); continue; }
            if (!*old || st.st_mtime > ot) { snprintf(old, sizeof old, "%s", p); ot = st.st_mtime; }
        }
        if (d) closedir(d);
        if (*best && vka_shlib_open(&g_lib, best, DMSH_CHAIN, DMSH_VK_CHAIN, DM_GAME_ID, DMSH_VK_ABI, err, sizeof err)) {
            char v[17]; vka_shlib_str(g_lib.h->vk_chain, v);
            VLOG("shader library %s: this host's version %s is %s (the app's shader update makes it); playing version %s, the same ABI %s", path, DMSH_VK_CHAIN, why, v, DMSH_VK_ABI);
            snprintf(path, sizeof path, "%s", best); have = 1;
        } else if (!*best && *compatible && certified_abi_open(&g_lib, compatible, err, sizeof err)) {
            char v[17]; vka_shlib_str(g_lib.h->vk_chain, v);
            VLOG("shader ABI migration: using complete prior library %s (version %s, additive-compatible certified ABI); no retranslation or header relabelling",
                 compatible, v);
            snprintf(path, sizeof path, "%s", compatible); have = 1;
        } else if (!*best && !*compatible && *old && vka_shlib_open(&g_lib, old, NULL, NULL, DM_GAME_ID, NULL, err, sizeof err)) {
            char v[17]; vka_shlib_str(g_lib.h->vk_chain, v);
            VRED("shader library %s: this host's version %s is %s; playing version %s, made before versioned shader updates (no ABI in its header, this host's is %s): "
                 "it may draw wrong. Update the shaders once in the app; later updates are then partial", path, DMSH_VK_CHAIN, why, v, DMSH_VK_ABI);
            snprintf(path, sizeof path, "%s", old); have = 1;
        } else { VRED("no shader library at %s (the pack's shaders/" DMSH_VK_DIR_PREFIX "%s: %s) and none of another version with this host's ABI %s: nothing is drawn", path, DMSH_VK_CHAIN, why, DMSH_VK_ABI); return 0; }
    }
    if (!have) { VRED("shader library %s refused: %s; nothing is drawn", path, access(path, R_OK) ? "missing" : err); return 0; }
    snprintf(g_lib_path, sizeof g_lib_path, "%s", path);
    // The translator's answers in the header against this device: modules built for 64-lane subgroups split ballots and shuffles into 32-lane halves, so they are right on
    // 32 or 64 lanes; storage buffers are bound rounded down to ssbo_align, which the device's alignment must divide (android/SHADERS.md "Translator answers")
    unsigned sg = g_lib.h->subgroup_size ? g_lib.h->subgroup_size : 32, sa = g_lib.h->ssbo_align;
    sg_plan(sg); if (g_shuffle_lds < 0) shuffle_plan();   // (once a run: a selftest compute pipeline may have made the plan already)
    if (sa && (sa % V.sb_align)) { VRED("shader library %s refused: built for storage buffers at %u-byte boundaries, the device needs %llu; nothing is drawn", path, sa, (unsigned long long)V.sb_align); vka_shlib_close(&g_lib); return 0; }
    char inputs[17]; vka_shlib_str(g_lib.h->inputs, inputs);
    VLOG("shader library %s: %u shaders, %u modules, %.1f MB (chain %s, Vulkan chain %s, inputs %s; %u-lane subgroups, storage buffers at %u)", path, g_lib.h->entry_count, g_lib.h->mod_count,
         g_lib.size / 1e6, DMSH_CHAIN, DMSH_VK_CHAIN, inputs, sg, sa ? sa : 1);
    g_lib_state = 1;
    // Selective translator updates: compile only a small list of bottleneck
    // shaders with the new V21/V22 vector/GMEM translator and place the
    // resulting partial dmsh_vk.lib in shaders/hot/v-<current>/.
    // The full older library remains completely intact, so no 4-hour
    // 42k-shader rebuild is required to test/replace foliage mesh shaders.
    // This overlay is strictly same-game, same-ABI and same-current-toolchain.
    // An absent, invalid or incomplete overlay never blocks the full library.
    // Compare against the known good full library without deleting or
    // renaming the prepared hot overlay. Default ON for safely translated
    // fragment/compute patches; DM_VK_OOT_HOT=0 is a full A/B rollback.
    if (!(e && *e) && VKA_ENV("DM_VK_OOT_HOT", 1)) {
        char hp[1024], he[256];
        if (snprintf(hp, sizeof hp, "%s/shaders/hot/" DMSH_VK_DIR_PREFIX "%s/" DMSH_VK_LIB_FILE,
                     dir, DMSH_VK_CHAIN) < (int)sizeof hp && !access(hp, R_OK)) {
            if (vka_shlib_open(&g_hot, hp, DMSH_CHAIN, DMSH_VK_CHAIN, DM_GAME_ID, DMSH_VK_ABI, he, sizeof he)) {
                // The overlay's translated descriptor and c1 inputs must
                // match the complete library being used, not merely its game
                // and Vulkan ABI. Only a bounded partial library is an overlay.
                // Reject mismatches without disturbing the stable base.
                if (!g_hot.h->entry_count || g_hot.h->entry_count > 1024 ||
                    memcmp(g_hot.h->inputs, g_lib.h->inputs, sizeof g_hot.h->inputs)) {
                    VRED("GPU hot-shader overlay %s rejected (shader count or profile inputs differ from the complete base); original library preserved", hp);
                    vka_shlib_close(&g_hot);
                } else {
                    g_hot_loaded = 1;
                    unsigned quarantine = 0, old_mesh = 0, old_keys = 0;
                    for (unsigned k = 0; k < g_hot.h->entry_count; k++) {
                        const dmsh_vk_entry *entry = &g_hot.ent[k];
                        int old = vka_shlib_find(&g_lib, entry->key) != NULL;
                        if (old) old_keys++;
                        if (entry->stage != DMSH_VK_STAGE_MS && entry->stage != DMSH_VK_STAGE_TS)
                            continue;
                        quarantine++;
                        if (old) old_mesh++;
                    }
                    VLOG("GPU hot-shader overlay: %u new shaders from %s; untouched %u stable shaders from %s remain available",
                         g_hot.h->entry_count, hp, g_lib.h->entry_count, path);
                    VLOG("Ocarina hot shader safety: %u overlay mesh/task entries (%u also in full library) quarantined by default; "
                         "%u previously working base shaders preferred until retranslation is proven equivalent. "
                         "Captured-only mesh layouts lack validated pixel/mesh pairings and caused screen-spanning white triangles and ~26 FPS. "
                         "DM_VK_OOT_HOT_OVERRIDE=1 enables overriding previously working shaders; "
                         "DM_VK_OOT_HOT_MESH=1 additionally enables unvalidated mesh/task; "
                         "DM_VK_OOT_HOT=0 disables the entire overlay. "
                         "Original 42k shaders and all compiled hot results remain intact.",
                         quarantine, old_mesh, old_keys);
                }
            } else {
                VRED("GPU hot-shader overlay %s rejected (%s); using full stable library unchanged", hp, he);
            }
        }
    }
    if (!(e && *e) && !VKA_ENV("DM_VK_OOT_HOT", 1))
        VLOG("Ocarina GPU hot-shader overlay disabled by DM_VK_OOT_HOT=0: using intact full library for an A/B render comparison");
    const char *ck = getenv("DM_VK_SHLIB_CHECK");
    if (ck && atoi(ck)) vka_shlib_check_all(&g_lib);
    return 1;
}

// ---------- Static memory: buffers that live as long as the process ----------
typedef struct { VkBuffer buf; VkDeviceMemory mem; uint8_t *ptr; VkDeviceSize size, used; } stblk;
static stblk g_st;
int vka_static(VkDeviceSize n, VkDeviceSize align, vka_span *out) {
    if (!align) align = 16;
    pthread_mutex_lock(&g_mu);
    VkDeviceSize o = (g_st.used + align - 1) / align * align;
    if (!g_st.buf || o + n > g_st.size) {
        stblk b = {0}; b.size = n > (4u << 20) ? (n + 0xFFFF) & ~(VkDeviceSize)0xFFFF : 4u << 20;
        VkBufferCreateInfo bi = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = b.size, .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT |
                                 VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT};
        VkMemoryRequirements mr; void *p = NULL; uint32_t t = UINT32_MAX;
        if (!vk.vkCreateBuffer(V.dev, &bi, NULL, &b.buf)) {
            vk.vkGetBufferMemoryRequirements(V.dev, b.buf, &mr);
            t = vka_mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, 0);
            VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = t};
            if (t == UINT32_MAX || vk.vkAllocateMemory(V.dev, &ai, NULL, &b.mem) || vk.vkBindBufferMemory(V.dev, b.buf, b.mem, 0) || vk.vkMapMemory(V.dev, b.mem, 0, VK_WHOLE_SIZE, 0, &p)) p = NULL;
        }
        if (!p) { pthread_mutex_unlock(&g_mu); VRED("static block of %llu bytes not allocated", (unsigned long long)b.size); return 0; }
        b.ptr = p; g_st = b; o = 0;   // the old block stays (its buffers are still bound by shaders)
    }
    g_st.used = o + n; *out = (vka_span){g_st.buf, g_st.ptr + o, o};
    pthread_mutex_unlock(&g_mu);
    return 1;
}

// ---------- Shaders by key ----------
typedef struct { uint64_t key; vka_shader *sh; const vka_shlib *lib; } shent;
static shent *g_sh; static size_t g_shcap, g_shn;
static size_t hslot(uint64_t k, size_t cap) { return (size_t)((k * 0x9E3779B97F4A7C15ull) >> 17) & (cap - 1); }
static shent *sh_find(uint64_t key, const vka_shlib *L) {
    if (!g_shcap) return NULL;
    for (size_t i = hslot(key, g_shcap);; i = (i + 1) & (g_shcap - 1)) { if (!g_sh[i].sh) return NULL; if (g_sh[i].key == key && g_sh[i].lib == L) return &g_sh[i]; }
}
static void sh_put(uint64_t key, const vka_shlib *L, vka_shader *s) {
    if (2 * (g_shn + 1) > g_shcap) {
        size_t nc = g_shcap ? 2 * g_shcap : 1024; shent *n = calloc(nc, sizeof *n);
        for (size_t i = 0; i < g_shcap; i++) if (g_sh[i].sh) { size_t j = hslot(g_sh[i].key, nc); while (n[j].sh) j = (j + 1) & (nc - 1); n[j] = g_sh[i]; }
        free(g_sh); g_sh = n; g_shcap = nc;
    }
    size_t j = hslot(key, g_shcap); while (g_sh[j].sh) j = (j + 1) & (g_shcap - 1);
    g_sh[j] = (shent){key, s, L}; g_shn++;
}

static const char *stage_name(int s) { static const char *n[] = {"vertex", "tess control", "tess evaluation", "geometry", "fragment", "compute", "task", "mesh"}; return s >= 0 && s < 8 ? n[s] : "?"; }
// What the replay cannot run yet, decided once per shader: refused shaders keep their entry, so the draws that use them are skipped and counted
static const char *refusal(const vka_shlib *L, const dmsh_vk_entry *e) {
    if (e->flags & (DMSH_VK_F_NV_PASSTHROUGH | DMSH_VK_F_NV_VIEWPORT)) return "NV-only geometry passthrough / viewport mask (a library built before the gs_passthrough answer)";
    if (e->flags & DMSH_VK_F_INTERLOCK) return "fragment shader interlock";
    if (e->stage == DMSH_VK_STAGE_GS && !V.geom) return "a geometry shader on a device without geometryShader";
    if ((e->stage == DMSH_VK_STAGE_TCS || e->stage == DMSH_VK_STAGE_TES) && !V.tess) return "a tessellation shader on a device without tessellationShader";
    // NVN2 task and mesh programs, and the pixel shaders that read their per-primitive outputs (valid only in a mesh pipeline): only with VK_EXT_mesh_shader (vka_dev.c)
    if ((e->stage == DMSH_VK_STAGE_TS || e->stage == DMSH_VK_STAGE_MS || (e->flags & DMSH_VK_F_MESH_PRIM)) && !V.mesh) return "a task / mesh shader (or a pixel shader of their per-primitive outputs) on a device without VK_EXT_mesh_shader (or DM_VK_MESH=0)";
    if (e->stage == DMSH_VK_STAGE_TS && !V.task) return "a task shader on a device with mesh shaders but without taskShader";
    if (e->stage == DMSH_VK_STAGE_TS || e->stage == DMSH_VK_STAGE_MS) {   // the workgroup (the entry's local) within the device's limit
        uint64_t inv = (uint64_t)e->local[0] * e->local[1] * e->local[2];
        if (!inv || inv > (e->stage == DMSH_VK_STAGE_TS ? V.task_inv : V.mesh_inv)) return "a task / mesh workgroup larger than the device's (maxTaskWorkGroupInvocations / maxMeshWorkGroupInvocations)";
    }
    const dmsh_vk_bind *b = vka_shlib_binds(L, e);
    for (unsigned i = 0; i < e->bind_count; i++) if (b[i].kind == DMSH_VK_KIND_UNKNOWN) return "a binding the build could not place";
    return NULL;
}
// A module of a stage sg_plan runs as one lane (no subgroup operations there on this device, or a subgroup size the library is not right for that cannot be pinned) has them
// rewritten as subgroups of one invocation (vka_spv_subgroup_single; Qualcomm's Adreno 840 driver has them in fragment, compute, task and mesh shaders, not in the vertex pipeline's). Logged once per shader key; a module that cannot be rewritten is used as it is, with a red line
static void single_lane(uint64_t key, int stage, uint32_t **w, size_t *nb) {
    if (stage < 0 || stage > 7 || !g_sg_one[stage]) return;   // sg_plan
    // A task or mesh workgroup uses its subgroup operations across the workgroup (output counts, compaction): one-lane subgroups give it wrong results. The Adreno 840's
    // driver has them in both stages at its fixed 64 (subgroupSupportedStages 0xf0), so this is a device the library was not made for
    if (stage >= DMSH_VK_STAGE_TS) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("%s shader %016llx: its subgroup operations run as one lane (the device's subgroups in this stage do not fit the library): its output is likely wrong", stage == DMSH_VK_STAGE_TS ? "task" : "mesh", (unsigned long long)key); }
    size_t on = 0; int ch = 0; char e[256] = ""; uint32_t *o = vka_spv_subgroup_single(*w, *nb / 4, &on, &ch, e, sizeof e);
    if (!o) { if (e[0]) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("shader %016llx: subgroup operations in a stage without them not rewritten: %s", (unsigned long long)key, e); } return; }
    static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VLOG("shader %016llx: subgroup operations rewritten as one-invocation subgroups (%s)", (unsigned long long)key,
                                                            stage == DMSH_VK_STAGE_GS && V.driver_id == VK_DRIVER_ID_MESA_TURNIP ? "Turnip's geometry stage (DM_VK_SUBGROUP_GS)" : V.subgroup_stages & g_stage_bit[stage] ? "the device's subgroup size in this stage is not the library's and cannot be pinned" : "the device has none in this stage");
    free(*w); *w = o; *nb = on * 4;
}
// DM_VK_SPV_OVERRIDE=<folder> (a diagnostic, android/TESTING.md): <folder>/<key>_<variant>.spv, when it is there, is that module's SPIR-V instead of the library's (a shader
// rewritten to show its inputs, say, in nxreplay). Logged once per module; the interface (locations, bindings) must stay the library's, which the pipeline layout follows
static uint32_t *spv_override(uint64_t key, unsigned variant, size_t *nb) {
    const char *d = getenv("DM_VK_SPV_OVERRIDE");
    if (!d || !*d) return NULL;
    char p[1100]; snprintf(p, sizeof p, "%s/%016llx_%u.spv", d, (unsigned long long)key, variant);
    FILE *f = fopen(p, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint32_t *w = n >= 20 && n % 4 == 0 ? malloc((size_t)n) : NULL;
    if (w && fread(w, 1, (size_t)n, f) != (size_t)n) { free(w); w = NULL; }
    fclose(f);
    if (!w || w[0] != 0x07230203u) { VRED("DM_VK_SPV_OVERRIDE: %s is not a SPIR-V module: the library's is used", p); free(w); return NULL; }
    VLOG("DM_VK_SPV_OVERRIDE: shader %016llx variant %u from %s (%ld bytes)", (unsigned long long)key, variant, p, n);
    *nb = (size_t)n; return w;
}
static VkShaderModule spv_module(const vka_shlib *L, const dmsh_vk_entry *e, const dmsh_vk_module *m, uint64_t key, const char **why, char *err, size_t errn) {
    size_t nb = 0; uint32_t *w = spv_override(key, m->variant, &nb);
    if (!w) w = vka_shlib_spirv(L, m, &nb, err, errn);
    if (!w) { *why = err; return VK_NULL_HANDLE; }
    if (e->flags & DMSH_VK_F_SUBGROUP) single_lane(key, e->stage, &w, &nb);
    VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = nb, .pCode = w};
    VkShaderModule mod = VK_NULL_HANDLE; VkResult r = vk.vkCreateShaderModule(V.dev, &ci, NULL, &mod);
    free(w);
    if (r) { snprintf(err, errn, "vkCreateShaderModule %d (variant %u of %016llx)", r, m->variant, (unsigned long long)key); *why = err; return VK_NULL_HANDLE; }
    return mod;
}
VkShaderModule vka_shader_module(vka_shader *s, int variant) {
    if (variant < 0 || variant > DMSH_VK_MOD_SHUFFLE_LDS) return VK_NULL_HANDLE;
    if (s->mods[variant]) return s->mods[variant];
    const dmsh_vk_module *m = vka_shlib_module(s->lib, s->e, variant);
    if (!m) return VK_NULL_HANDLE;
    const char *why = NULL; char err[256];
    VkShaderModule mod = spv_module(s->lib, s->e, m, s->key, &why, err, sizeof err);
    if (!mod) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("shader %016llx variant %d: %s", (unsigned long long)s->key, variant, why); return VK_NULL_HANDLE; }
    pthread_mutex_lock(&g_mu);
    if (s->mods[variant]) { pthread_mutex_unlock(&g_mu); vk.vkDestroyShaderModule(V.dev, mod, NULL); return s->mods[variant]; }
    s->mods[variant] = mod;
    pthread_mutex_unlock(&g_mu);
    return mod;
}
// A geometry shader that writes memory, with those writes made by one run per primitive (vka_spv_gs_claim: the Adreno 840 runs a geometry shader several times for each
// primitive, each run writing memory). out NULL: only counts them. Made from the base module after the one-invocation subgroup rewrite
static int gs_words(vka_shader *s, uint32_t **out, size_t *on, char *err, size_t errn) {
    const dmsh_vk_module *m = vka_shlib_module(s->lib, s->e, DMSH_VK_MOD_BASE);
    size_t nb = 0; uint32_t *w = m ? vka_shlib_spirv(s->lib, m, &nb, err, errn) : NULL;
    if (!w) return -1;
    if (s->e->flags & DMSH_VK_F_SUBGROUP) single_lane(s->key, s->e->stage, &w, &nb);
    int r = vka_spv_gs_claim(w, nb / 4, VKA_GS_CLAIM_BINDING, out, on, err, errn);
    free(w); return r;
}
VkShaderModule vka_shader_gs_module(vka_shader *s) {
    if (s->gs_fx <= 0) return VK_NULL_HANDLE;
    if (s->gs_claim) return s->gs_claim;
    uint32_t *o = NULL; size_t on = 0; char err[256] = ""; VkShaderModule mod = VK_NULL_HANDLE;
    if (gs_words(s, &o, &on, err, sizeof err) > 0 && o) {
        VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = on * 4, .pCode = o};
        VkResult r = vk.vkCreateShaderModule(V.dev, &ci, NULL, &mod); if (r) { snprintf(err, sizeof err, "vkCreateShaderModule %d", r); mod = VK_NULL_HANDLE; }
    }
    free(o);
    if (!mod) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("geometry shader %016llx: module with the claim not made: %s", (unsigned long long)s->key, err); return VK_NULL_HANDLE; }
    pthread_mutex_lock(&g_mu);
    if (s->gs_claim) { pthread_mutex_unlock(&g_mu); vk.vkDestroyShaderModule(V.dev, mod, NULL); return s->gs_claim; }
    s->gs_claim = mod;
    pthread_mutex_unlock(&g_mu);
    return mod;
}
// The base vertex module with the inputs of umask / smask retyped (vka_spvpatch.c): made once per pair of masks, kept for the process like the base module
struct vka_vinmod { struct vka_vinmod *next; uint32_t u, s; VkShaderModule mod; };
VkShaderModule vka_shader_vin_module(vka_shader *s, uint32_t umask, uint32_t smask) {
    pthread_mutex_lock(&g_mu);
    for (struct vka_vinmod *v = s->vin; v; v = v->next) if (v->u == umask && v->s == smask) { VkShaderModule m = v->mod; pthread_mutex_unlock(&g_mu); return m; }
    pthread_mutex_unlock(&g_mu);
    VkShaderModule mod = VK_NULL_HANDLE; char err[256] = ""; int own = 0;   // own: made here (the base module of the fallback is the shader's, never destroyed)
    const dmsh_vk_module *m = vka_shlib_module(s->lib, s->e, DMSH_VK_MOD_BASE);
    size_t nb = 0; uint32_t *w = m ? vka_shlib_spirv(s->lib, m, &nb, err, sizeof err) : NULL;
    if (w && (s->e->flags & DMSH_VK_F_SUBGROUP)) single_lane(s->key, s->e->stage, &w, &nb);
    size_t on = 0; uint32_t *o = w ? vka_spv_vin_retype(w, nb / 4, umask, smask, &on, err, sizeof err) : NULL;
    if (o) { VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = on * 4, .pCode = o};
             VkResult r = vk.vkCreateShaderModule(V.dev, &ci, NULL, &mod); if (r) { snprintf(err, sizeof err, "vkCreateShaderModule %d", r); mod = VK_NULL_HANDLE; } else own = 1; }
    free(w); free(o);
    if (!mod) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("vertex shader %016llx: inputs %#x (uint) / %#x (int) not retyped: %s; the base module reads them as floats", (unsigned long long)s->key, umask, smask, err);
                mod = vka_shader_module(s, DMSH_VK_MOD_BASE); }
    // Two threads (the frame path and a prewarm or optimizer thread) may have made it at once: the first one in the list wins, the other's module is destroyed
    pthread_mutex_lock(&g_mu);
    for (struct vka_vinmod *o = s->vin; o; o = o->next) if (o->u == umask && o->s == smask) {
        VkShaderModule w = o->mod; pthread_mutex_unlock(&g_mu);
        if (own && mod != w) vk.vkDestroyShaderModule(V.dev, mod, NULL);   // (no pipeline was made from it: it never left this function)
        return w; }
    struct vka_vinmod *v = malloc(sizeof *v); *v = (struct vka_vinmod){s->vin, umask, smask, mod}; s->vin = v;
    pthread_mutex_unlock(&g_mu);
    return mod;
}
// The base pixel module with the float outputs of umask / smask retyped for integer attachments (vka_spvpatch.c vka_spv_fout_retype): made once per pair of masks, as the vertex ones
VkShaderModule vka_shader_fout_module(vka_shader *s, uint32_t umask, uint32_t smask) {
    pthread_mutex_lock(&g_mu);
    for (struct vka_vinmod *v = s->fout; v; v = v->next) if (v->u == umask && v->s == smask) { VkShaderModule m = v->mod; pthread_mutex_unlock(&g_mu); return m; }
    pthread_mutex_unlock(&g_mu);
    VkShaderModule mod = VK_NULL_HANDLE; char err[256] = ""; int own = 0;
    const dmsh_vk_module *m = vka_shlib_module(s->lib, s->e, DMSH_VK_MOD_BASE);
    size_t nb = 0; uint32_t *w = m ? vka_shlib_spirv(s->lib, m, &nb, err, sizeof err) : NULL;
    if (w && (s->e->flags & DMSH_VK_F_SUBGROUP)) single_lane(s->key, s->e->stage, &w, &nb);
    size_t on = 0; uint32_t *o = w ? vka_spv_fout_retype(w, nb / 4, umask, smask, &on, err, sizeof err) : NULL;
    if (o) { VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = on * 4, .pCode = o};
             VkResult r = vk.vkCreateShaderModule(V.dev, &ci, NULL, &mod); if (r) { snprintf(err, sizeof err, "vkCreateShaderModule %d", r); mod = VK_NULL_HANDLE; } else own = 1; }
    free(w); free(o);
    if (!mod) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("pixel shader %016llx: outputs %#x (uint) / %#x (int) not retyped for their integer targets: %s; the base module, whose float outputs those targets do not take", (unsigned long long)s->key, umask, smask, err);
                mod = vka_shader_module(s, DMSH_VK_MOD_BASE); }
    else { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VLOG("pixel shader %016llx: float outputs %#x (uint) / %#x (int) retyped for their integer targets (their bits written as they are)", (unsigned long long)s->key, umask, smask); }
    pthread_mutex_lock(&g_mu);
    for (struct vka_vinmod *x = s->fout; x; x = x->next) if (x->u == umask && x->s == smask) {
        VkShaderModule had = x->mod; pthread_mutex_unlock(&g_mu);
        if (own && mod != had) vk.vkDestroyShaderModule(V.dev, mod, NULL);
        return had; }
    struct vka_vinmod *v = malloc(sizeof *v);
    if (v) { *v = (struct vka_vinmod){s->fout, umask, smask, mod}; s->fout = v; }
    pthread_mutex_unlock(&g_mu);
    return mod;
}
int vka_shader_fout_retyped(vka_shader *s, uint32_t umask, uint32_t smask) {
    VkShaderModule m = vka_shader_fout_module(s, umask, smask);
    return m && m != vka_shader_module(s, DMSH_VK_MOD_BASE);
}
// The compute module vka_shader_cs_module picks (its DMSH_VK_MOD_SHUFFLE_LDS module where shuffle_plan takes it, else the base) with the formatted storage images and
// sampled images of rt (set 0 bindings) as integer images for the integer textures bound there (vka_spvpatch.c vka_spv_img_retype): made once per rt, as the vertex ones.
// The cache is keyed by rt alone: the variant is fixed for the run (shuffle_plan reads DM_VK_SHUFFLE_LDS once, a restart switch). A module that cannot be rewritten
// falls back to the unretyped one, whose bindings then stay unbound (vka_draw.c img_retype_of)
struct vka_imgmod { struct vka_imgmod *next; vka_imgrt rt; VkShaderModule mod; };
VkShaderModule vka_shader_img_module(vka_shader *s, const vka_imgrt *rt) {
    pthread_mutex_lock(&g_mu);
    for (struct vka_imgmod *v = s->imgm; v; v = v->next) if (!memcmp(&v->rt, rt, sizeof *rt)) { VkShaderModule m = v->mod; pthread_mutex_unlock(&g_mu); return m; }
    pthread_mutex_unlock(&g_mu);
    VkShaderModule mod = VK_NULL_HANDLE; char err[256] = ""; int own = 0;
    vka_spv_imgsel sel[VKA_IMGRT_MAX]; int n = 0;
    for (; n < VKA_IMGRT_MAX && rt->b[n]; n++) sel[n] = (vka_spv_imgsel){0, rt->b[n] >> 16, (uint8_t)(rt->b[n] & 0xff), (uint8_t)(rt->b[n] >> 8 & 0xff)};
    int var = vka_shader_cs_variant(s);
    const dmsh_vk_module *m = n ? vka_shlib_module(s->lib, s->e, var) : NULL;
    size_t nb = 0; uint32_t *w = m ? vka_shlib_spirv(s->lib, m, &nb, err, sizeof err) : NULL;
    if (w && (s->e->flags & DMSH_VK_F_SUBGROUP)) single_lane(s->key, s->e->stage, &w, &nb);
    size_t on = 0; uint32_t *o = w ? vka_spv_img_retype(w, nb / 4, sel, n, &on, err, sizeof err) : NULL;
    if (o) { VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = on * 4, .pCode = o};
             VkResult r = vk.vkCreateShaderModule(V.dev, &ci, NULL, &mod); if (r) { snprintf(err, sizeof err, "vkCreateShaderModule %d", r); mod = VK_NULL_HANDLE; } else own = 1; }
    free(w); free(o);
    char q[160]; size_t qn = 0; q[0] = 0;
    for (int k = 0; k < n && qn < sizeof q; k++) qn += (size_t)snprintf(q + qn, sizeof q - qn, "%s%u %s (format %u)", k ? ", " : "", rt->b[k] >> 16, (rt->b[k] & 0xff) == 1 ? "uint" : "sint", rt->b[k] >> 8 & 0xff);
    if (!mod) { static _Atomic int k; if (atomic_fetch_add(&k, 1) < 8) VRED("shader %016llx: images (storage or sampled) at bindings %s not retyped for their integer textures: %s; they read as unbound", (unsigned long long)s->key, q, err);
                mod = vka_shader_module(s, var); }
    else { static _Atomic int k; if (atomic_fetch_add(&k, 1) < 8) VLOG("shader %016llx: images (storage or sampled) at bindings %s retyped for their integer textures (texels as the hardware returns them)%s", (unsigned long long)s->key, q,
                                                                     var == DMSH_VK_MOD_SHUFFLE_LDS ? " in its shuffle_lds module" : ""); }
    pthread_mutex_lock(&g_mu);
    for (struct vka_imgmod *x = s->imgm; x; x = x->next) if (!memcmp(&x->rt, rt, sizeof *rt)) {
        VkShaderModule had = x->mod; pthread_mutex_unlock(&g_mu);
        if (own && mod != had) vk.vkDestroyShaderModule(V.dev, mod, NULL);
        return had; }
    struct vka_imgmod *v = malloc(sizeof *v);
    if (v) { *v = (struct vka_imgmod){s->imgm, *rt, mod}; s->imgm = v; }
    pthread_mutex_unlock(&g_mu);
    return mod;
}
int vka_shader_img_retyped(vka_shader *s, const vka_imgrt *rt) {
    VkShaderModule m = vka_shader_img_module(s, rt);   // (a fallback is the unretyped module of its variant, made before it: no new module made here)
    return m && m != s->mods[DMSH_VK_MOD_BASE] && m != s->mods[DMSH_VK_MOD_SHUFFLE_LDS];
}
vka_shader *vka_shader_make(const vka_shlib *L, uint64_t key) {
    pthread_mutex_lock(&g_mu);
    shent *h = sh_find(key, L);
    if (h) { vka_shader *s = h->sh; pthread_mutex_unlock(&g_mu); return s->bad ? NULL : s; }
    pthread_mutex_unlock(&g_mu);
    vka_shader *s = calloc(1, sizeof *s); s->key = key; s->lib = L;
    const dmsh_vk_entry *e = vka_shlib_find(L, key);
    const char *why = NULL; char err[256] = "";
    if (!e) why = "not in the shader library";
    else {
        s->e = e; s->b = vka_shlib_binds(L, e);
        why = refusal(L, e);
        const dmsh_vk_module *m = why ? NULL : vka_shlib_module(L, e, DMSH_VK_MOD_BASE);
        if (!why && !m) why = "no base module";
        if (m) s->mods[DMSH_VK_MOD_BASE] = spv_module(L, e, m, key, &why, err, sizeof err);
        if (!why && e->stage == DMSH_VK_STAGE_GS && VKA_ENV("DM_VK_GS_CLAIM", 1)) {   // memory writes: made once per primitive (vka_spv_gs_claim)
            char e2[256] = ""; s->gs_fx = gs_words(s, NULL, NULL, e2, sizeof e2);
            if (s->gs_fx < 0) VRED("geometry shader %016llx: memory writes not put under a claim (%s): drawn as it is, its writes repeated by the device's runs of each primitive", (unsigned long long)key, e2);
            else if (s->gs_fx) VLOG("geometry shader %016llx: %d memory writes, made by one run per primitive (a claim word per primitive at set 0 binding %d)", (unsigned long long)key, s->gs_fx, VKA_GS_CLAIM_BINDING);
        }
        if (!why && e->c1_len) {   // the c1 bytes: a uniform buffer of their own, made once
            if (vka_static(e->c1_len, V.ub_align, &s->c1)) { memcpy(s->c1.ptr, vka_shlib_c1(L, e), e->c1_len); s->c1_len = e->c1_len; }
            else why = "no static memory for its c1 bytes";
        }
    }
    if (why) {
        s->bad = 1;
        static _Atomic int n; if (atomic_fetch_add(&n, 1) < 64) VRED("shader %016llx (%s): %s; its draws are skipped", (unsigned long long)key, e ? stage_name(e->stage) : "?", why);
    }
    pthread_mutex_lock(&g_mu);
    h = sh_find(key, L);
    if (h) { if (s->mods[0]) vk.vkDestroyShaderModule(V.dev, s->mods[0], NULL); free(s); s = h->sh; }   // another thread made it meanwhile
    else sh_put(key, L, s);
    pthread_mutex_unlock(&g_mu);
    return s->bad ? NULL : s;
}

// A shader of the game's libraries by key: the full library is always
// available. The real Ocarina 2026-11-11 051430 test showed 57 hot entries
// rendered enormous white mesh triangles and worsened the heavy-scene GPU
// from ~22 to ~38 ms. The captured-only mesh_facts parser has no complete
// mesh/fragment pairing map (flat per-primitive outputs and padding), so its
// syntactically valid SPIR-V cannot yet be assumed visually equivalent.
// Default to the OLD base for mesh/task; suppress unknown hot mesh/task
// rather than letting them corrupt geometry. This is an intentional
// correctness-first fallback until the missing pairing metadata is verified.
// Fragment/compute hot shaders remain available. The disk overlay remains
// intact for future repair, and users can opt into mesh experiments explicitly.
// The source-recaptured 9e6b compute is the ONLY existing-heavy shader
// that can switch to the new toolchain without any geometry/pixel interface.
// Its old NVIDIA-style 8x4x4 dispatch must still see identical workgroup,
// shared memory and descriptor semantics. A hot overlay that differs in even
// one resource/ABI field falls back to the 42k known-good library.
// This is NOT a blanket shader hot override: old Mesh/Task patches remain
// quarantined to prevent the white-triangle regression.
static int oot_hot_compute_compatible(const dmsh_vk_entry *old,
                                       const dmsh_vk_entry *newer) {
    if (!old || !newer || old->key != UINT64_C(0x9e6b00b050e30801) ||
        old->stage != DMSH_VK_STAGE_CS || newer->stage != DMSH_VK_STAGE_CS ||
        old->flags != newer->flags || old->shared != newer->shared ||
        old->local[0] != newer->local[0] ||
        old->local[1] != newer->local[1] ||
        old->local[2] != newer->local[2] ||
        old->bind_count != newer->bind_count ||
        old->c1_len != newer->c1_len)
        return 0;
    const dmsh_vk_bind *a = vka_shlib_binds(&g_lib, old);
    const dmsh_vk_bind *b = vka_shlib_binds(&g_hot, newer);
    return (a && b && memcmp(a, b, (size_t)old->bind_count * sizeof *a) == 0);
}

static const vka_shlib *library_for_key(uint64_t key) {
    if (!g_hot_loaded) return &g_lib;
    const dmsh_vk_entry *overlay = vka_shlib_find(&g_hot, key);
    if (!overlay) return &g_lib;
    // Runtime shader capture says the new version is syntactically valid,
    // not that it has the right pixel/mesh linkage. Prefer a known-good
    // original SPIR-V module whenever there is one; experimentation is an
    // opt-in and does not mutate either library on disk.
    const dmsh_vk_entry *base = vka_shlib_find(&g_lib, key);
    // Do not leave the V21/V22 translated compute on disk forever without
    // ever executing it: the old library's 9e6b module has the known
    // 0.5-1.4ms GPU cost and the generic SPIR-V group-size patch REFUSES
    // that module due to local/group dependent builtins. A newly translated
    // HOT compute with matching ABI is a safer improvement than forcing an
    // invalid workgroup retiling. Disable for A/B or any visual regression.
    if (base && key == UINT64_C(0x9e6b00b050e30801) &&
        VKA_ENV("DM_VK_OOT_HOT_COMPUTE", 1)) {
        static int compatible = -1;
        if (compatible < 0) {
            compatible = oot_hot_compute_compatible(base, overlay);
            VLOG("Ocarina profile-hot compute 9e6b: verified-resource ABI=%d; "
                 "%s (DM_VK_OOT_HOT_COMPUTE=0 restores original shader)",
                 compatible, compatible ? "new selective translator active" :
                 "original full-library shader retained");
        }
        if (compatible) return &g_hot;
    }
    if (base && !VKA_ENV("DM_VK_OOT_HOT_OVERRIDE", 0))
        return &g_lib;
    if ((overlay->stage == DMSH_VK_STAGE_MS ||
         overlay->stage == DMSH_VK_STAGE_TS) &&
        !VKA_ENV("DM_VK_OOT_HOT_MESH", 0))
        return &g_lib;
    return &g_hot;
}
vka_shader *vka_shader_by_key(uint64_t key) {
    pthread_mutex_lock(&g_mu); int ok = lib_load(); pthread_mutex_unlock(&g_mu);
    return ok ? vka_shader_make(library_for_key(key), key) : NULL;
}

// Every shader of a library through the device's compiler: each module made, each stage's set-0 layout made, each compute shader's pipeline built (graphics pipelines need
// a pair and state, so vertex and pixel shaders stop at the module and layout). DM_VK_SHLIB_CHECK=1 runs it when the game's library loads; the selftest runs it on DM_VK_SHLIB.
// Returns the number of failures; one log line per failure kind and a summary
int vka_shlib_check_all(const vka_shlib *L) {
    unsigned n = L->h->entry_count, made = 0, refused = 0, nolayout = 0, cs = 0, csfail = 0; uint64_t t0 = now_ns();
    for (unsigned i = 0; i < n; i++) {
        const dmsh_vk_entry *e = &L->ent[i];
        vka_shader *s = vka_shader_make(L, e->key);
        if (!s) { refused++; continue; }
        made++;
        for (int v = 1; v <= DMSH_VK_MOD_SHUFFLE_LDS; v++) if (vka_shlib_module(L, e, v) && !vka_shader_module(s, v)) nolayout++;   // the variants through the compiler too (counted as failures)
        vka_shader *sh[VKA_NSTAGE] = {0}; int st = vka_nvn_stage(e->stage); if (st < 0) { nolayout++; continue; } sh[st] = s;
        vka_layout lay;
        if (!vka_layout_of(sh, st == 5, &lay)) { nolayout++; continue; }
        if (st == 5) { uint64_t t = now_ns(); cs++; if (!vka_cs_pipeline(s, &lay)) csfail++;
                       if (cs <= 3 || cs % 25 == 0) VLOG("shader library check: compute pipeline %u (%016llx) %.0f ms; %u / %u shaders", cs, (unsigned long long)e->key, (now_ns() - t) / 1e6, i + 1, n); }
        if ((i + 1) % 2000 == 0) VLOG("shader library check: %u / %u shaders, %.1f s", i + 1, n, (now_ns() - t0) / 1e9);
    }
    VLOG("shader library check: %u shaders, %u modules made, %u refused, %u without a layout, %u compute pipelines (%u failed), %.1f s",
         n, made, refused, nolayout, cs, csfail, (now_ns() - t0) / 1e9);
    vka_pso_save(1);
    return (int)(nolayout + csfail);
}

// ---------- Programs ----------
// By serial (a new serial at every nvnProgramSetShaders; mtl_prog_release drops it): the program's stage keys resolved to shaders, each at the NVN stage its entry names
typedef struct { uint64_t serial; vka_progsh ps; } prent;
static prent *g_pr; static size_t g_prcap, g_prn;
static prent *pr_find(uint64_t s) {
    if (!g_prcap) return NULL;
    for (size_t i = hslot(s, g_prcap);; i = (i + 1) & (g_prcap - 1)) { if (!g_pr[i].serial) return NULL; if (g_pr[i].serial == s) return &g_pr[i]; }
}
static void pr_put(uint64_t s, const vka_progsh *ps) {
    prent *e = pr_find(s); if (e) { e->ps = *ps; return; }
    if (2 * (g_prn + 1) > g_prcap) {
        size_t nc = g_prcap ? 2 * g_prcap : 1024; prent *n = calloc(nc, sizeof *n);
        for (size_t i = 0; i < g_prcap; i++) if (g_pr[i].serial && g_pr[i].serial != ~0ull) { size_t j = hslot(g_pr[i].serial, nc); while (n[j].serial) j = (j + 1) & (nc - 1); n[j] = g_pr[i]; }
        free(g_pr); g_pr = n; g_prcap = nc; size_t live = 0; for (size_t i = 0; i < nc; i++) live += n[i].serial != 0; g_prn = live;
    }
    size_t j = hslot(s, g_prcap); while (g_pr[j].serial && g_pr[j].serial != ~0ull) j = (j + 1) & (g_prcap - 1);
    if (!g_pr[j].serial) g_prn++;
    g_pr[j] = (prent){s, *ps};
}
void vka_prog_put(uint64_t serial, const vka_progsh *ps) { pthread_mutex_lock(&g_mu); pr_put(serial, ps); pthread_mutex_unlock(&g_mu); }
void mtl_prog_release(prog_t *p) {
    if (!p || !p->serial) return;
    pthread_mutex_lock(&g_mu); prent *e = pr_find(p->serial); if (e) { e->serial = ~0ull; memset(&e->ps, 0, sizeof e->ps); } pthread_mutex_unlock(&g_mu);   // a tombstone
}
void mtl_prog_prefetch(const prog_t *p) { (void)p; }   // modules are made at the program's first draw (vka_prog_shaders)

// In-game, capture the four measured heavy shader control+code pairs once,
// even when the 42k-key imported SPIR-V base already contains them. The next
// translator revision can rebuild only these real sources as an overlay.
// No shader capture is attempted for other titles.
static int ocarina_hot_shader_slot(uint64_t key) {
    if (strcmp(DM_GAME_ID, "0400486024DEC000")) return -1;
    static const uint64_t keys[] = {
        UINT64_C(0x066f5daf12e43c71), UINT64_C(0xefaa4fa6a80ba719),
        UINT64_C(0x5ad65c0eefd09c7f), UINT64_C(0x9e6b00b050e30801)
    };
    for (int i = 0; i < 4; ++i) if (key == keys[i]) return i;
    return -1;
}

// Already-captured sources are checked byte for byte, not just by size.
// A previous crash may leave only one file, a short file or corrupted data.
static int capture_matches(const char *path, const void *src, size_t n) {
    struct stat st;
    if (stat(path, &st) || st.st_size != (off_t)n) return 0;
    FILE *f = fopen(path, "rb"); if (!f) return 0;
    const unsigned char *p = src;
    unsigned char buf[4096];
    size_t left = n; int ok = 1;
    while (left) {
        size_t m = left < sizeof buf ? left : sizeof buf;
        if (fread(buf, 1, m, f) != m || memcmp(buf, p, m)) { ok = 0; break; }
        p += m; left -= m;
    }
    fclose(f);
    return ok;
}

static int capture_write_file(const char *path, const void *src, size_t n) {
    char tmp[1100];
    if (snprintf(tmp, sizeof tmp, "%s.partial", path) >= (int)sizeof tmp) return 0;
    FILE *f = fopen(tmp, "wb"); if (!f) return 0;
    int ok = fwrite(src, 1, n, f) == n && fflush(f) == 0 && fsync(fileno(f)) == 0;
    if (fclose(f)) ok = 0;
    if (ok && !rename(tmp, path)) return 1;
    unlink(tmp);
    return 0;
}

static int capture_shader_source(const prog_t *p, unsigned i, uint64_t key) {
    const char *folder = getenv("DM_NVN_SHDUMP");
    if (!folder || !*folder || !p->sd[i].control || !p->sd[i].data) return 0;
    uint32_t nctl, ncode;
    nvn_ctl_lens(p->sd[i].control, &nctl, &ncode);
    if (nctl == 0x48) nctl = 0xd8; // NVN2 full control payload
    if (nctl < 0xd8 || nctl > 65536 || ncode < 4 || ncode > (1u << 24)) return 0;
    if (mkdir(folder, 0777) && access(folder, W_OK)) return 0;
    char ctl[1024], code[1024];
    if (snprintf(ctl, sizeof ctl, "%s/%016llx.ctl", folder, (unsigned long long)key) >= (int)sizeof ctl ||
        snprintf(code, sizeof code, "%s/%016llx.code", folder, (unsigned long long)key) >= (int)sizeof code) return 0;
    const void *bytes = (const void *)(uintptr_t)p->sd[i].data;
    if (capture_matches(ctl, p->sd[i].control, nctl) && capture_matches(code, bytes, ncode)) return 1;
    // Control is the completion marker. Never publish it before the code:
    // an interrupted capture cannot pretend to be a complete matched pair.
    unlink(ctl);
    if (!capture_write_file(code, bytes, ncode)) return 0;
    return capture_write_file(ctl, p->sd[i].control, nctl);
}

static void capture_hot_shader_source(const prog_t *p, unsigned i, uint64_t key) {
    int slot = ocarina_hot_shader_slot(key);
    if (slot < 0) return;
    static _Atomic unsigned done;
    unsigned mask = 1u << slot;
    if (atomic_load(&done) & mask) return;
    if (capture_shader_source(p, i, key)) {
        atomic_fetch_or(&done, mask);
        VLOG("Ocarina shader %016llx captured for independent mesh/compute hot recompilation; complete base library retained",
             (unsigned long long)key);
    }
}

// Persist REAL mesh<->pixel and task<->mesh bindings, not guessed SPIR-V
// interfaces. shader_split.mesh_facts needs these pairs to derive flat and
// per-primitive outputs. The old selected-only capture stored code/control,
// but rebuilt each mesh with mesh_pairs=[], causing white spanning triangles.
// Records contain only validated shader keys; source bytes stay in .ctl/.code.
// This metadata is collected once per distinct pair, on real gameplay.
// It never changes the installed full 42k library or the current overlay.
typedef struct { uint64_t a, b; unsigned char kind; } oot_pair;
static oot_pair g_oot_pairs[2048];
static unsigned g_oot_npair;
static pthread_mutex_t g_oot_pairs_mu = PTHREAD_MUTEX_INITIALIZER;

static int capture_ocarina_stage_pair(const prog_t *a_prog, unsigned a_slot, uint64_t a_key,
                                      const prog_t *b_prog, unsigned b_slot, uint64_t b_key,
                                      unsigned char kind) {
    if (strcmp(DM_GAME_ID, "0400486024DEC000") || !a_prog || !b_prog ||
        !a_key || !b_key || !g_hot_loaded) return 0;
    const char *folder = getenv("DM_NVN_SHDUMP");
    if (!folder || !*folder) return 0;
    pthread_mutex_lock(&g_oot_pairs_mu);
    for (unsigned n = 0; n < g_oot_npair; n++)
        if (g_oot_pairs[n].a == a_key && g_oot_pairs[n].b == b_key &&
            g_oot_pairs[n].kind == kind) {
            pthread_mutex_unlock(&g_oot_pairs_mu);
            return 1;
        }
    if (g_oot_npair == sizeof(g_oot_pairs) / sizeof(g_oot_pairs[0])) {
        pthread_mutex_unlock(&g_oot_pairs_mu);
        return 0;
    }
    // The draw combines mesh and fragment shaders that may belong to
    // DIFFERENT NVN programs. The old ProgramSetShaders-only capture read
    // both from one program and missed these real draw-time relationships.
    // Capture the source of each stage from its own owner before publishing.
    if (!capture_shader_source(a_prog, a_slot, a_key) ||
        !capture_shader_source(b_prog, b_slot, b_key)) {
        pthread_mutex_unlock(&g_oot_pairs_mu);
        return 0;
    }
    char file[1024];
    int n = snprintf(file, sizeof file, "%s/mesh_pairs.tsv", folder);
    if (n <= 0 || n >= (int)sizeof file) {
        pthread_mutex_unlock(&g_oot_pairs_mu);
        return 0;
    }
    int saved = 0;
    FILE *out = fopen(file, "a");
    if (out) {
        saved = fprintf(out, "%c\t%016llx\t%016llx\n",
            kind, (unsigned long long)a_key, (unsigned long long)b_key) > 0;
        saved = saved && fflush(out) == 0 && fsync(fileno(out)) == 0;
        if (fclose(out)) saved = 0;
        if (saved) {
            g_oot_pairs[g_oot_npair++] = (oot_pair){a_key, b_key, kind};
            static _Atomic unsigned reports;
            if (atomic_fetch_add(&reports, 1) < 32)
                VLOG("Ocarina captured draw-time %c pair %016llx -> %016llx (different NVN programs supported); 42k base untouched",
                     kind, (unsigned long long)a_key, (unsigned long long)b_key);
        }
    }
    pthread_mutex_unlock(&g_oot_pairs_mu);
    return saved;
}

// Return a REAL stage key and its index in the owning NVN program. A key's
// Vulkan ABI stage must be converted through vka_nvn_stage: ABI FS=4 is NVN
// FS=1. The pipeline's bound-program index is also NVN, not ABI.
static int stage_in_program(const prog_t *p, int stage, uint64_t *key, unsigned *slot) {
    if (!p) return 0;
    for (unsigned i = 0; i < p->nstage && i < 6; i++) {
        uint8_t md[8];
        if (!prog_key(p, i, md)) continue;
        uint64_t k = vka_shlib_key(md);
        const dmsh_vk_entry *e = g_hot_loaded ? vka_shlib_find(&g_hot, k) : NULL;
        if (!e) e = vka_shlib_find(&g_lib, k);
        if (e && vka_nvn_stage(e->stage) == stage) {
            *key = k; *slot = i;
            return 1;
        }
    }
    return 0;
}

// Called from the actual mesh DRAW, with the selected mesh-program and pixel
// program (d->bst[7] and d->bst[1]). ProgramSetShaders is not sufficient:
// these programs are not necessarily the same object. Called BEFORE
// SKIPQ so a quarantined or missing mesh can still provide a verified pair.
int vka_ocarina_capture_mesh_draw_pair(const prog_t *mesh_program, const prog_t *pixel_program) {
    if (strcmp(DM_GAME_ID, "0400486024DEC000") || !g_hot_loaded ||
        !mesh_program || !pixel_program) return 1;
    uint64_t mesh_key = 0, frag_key = 0, task_key = 0;
    unsigned mesh_slot = 0, frag_slot = 0, task_slot = 0;
    if (!stage_in_program(mesh_program, vka_nvn_stage(DMSH_VK_STAGE_MS),
                          &mesh_key, &mesh_slot)) return 0;
    int hot_mesh = vka_shlib_find(&g_hot, mesh_key) != NULL;
    int have_task = stage_in_program(mesh_program, vka_nvn_stage(DMSH_VK_STAGE_TS),
                                     &task_key, &task_slot);
    int hot_task = have_task && vka_shlib_find(&g_hot, task_key);
    if (!hot_mesh && !hot_task) return 1; // unchanged full-library shader
    int complete = 1;
    if (hot_mesh) {
        if (!stage_in_program(pixel_program, vka_nvn_stage(DMSH_VK_STAGE_FS),
                              &frag_key, &frag_slot))
            complete = 0;
        else if (!capture_ocarina_stage_pair(mesh_program, mesh_slot, mesh_key,
                                             pixel_program, frag_slot, frag_key, 'M'))
            complete = 0;
    }
    if (hot_task && !capture_ocarina_stage_pair(mesh_program, task_slot, task_key,
                                                mesh_program, mesh_slot, mesh_key, 'T'))
        complete = 0;
    return complete; // let the draw cache only successfully captured pairs
}

int vka_prog_shaders(const prog_t *p, vka_progsh *out) {
    memset(out, 0, sizeof *out);
    if (!p || !p->serial) return 0;
    pthread_mutex_lock(&g_mu); prent *e = pr_find(p->serial); if (e) *out = e->ps; pthread_mutex_unlock(&g_mu);
    if (e) return 1;
    pthread_mutex_lock(&g_mu); int ok = lib_load(); pthread_mutex_unlock(&g_mu);
    if (!ok) return 0;
    for (unsigned i = 0; i < p->nstage && i < 6; i++) {   // (a program has at most 6 shaders: hle_nvn.c nvnProgramSetShaders)
        uint8_t md[8];
        if (!prog_key(p, i, md)) continue;
        uint64_t key = vka_shlib_key(md);
        const vka_shlib *source = library_for_key(key);
        const dmsh_vk_entry *en = vka_shlib_find(source, key);
        if (!en) {
            out->bad |= VKA_BAD_MISSING; static _Atomic int n; if (atomic_fetch_add(&n, 1) < 32) VRED("shader %016llx (program stage %u) is not in the shader library", (unsigned long long)key, i);
            capture_shader_source(p, i, key);
            continue;
        }
        // Capture the four proven heavy shaders for future selective translator
        // experiments. This is not shader compilation and does not modify
        // any installed shader library or Vulkan pipeline cache.
        capture_hot_shader_source(p, i, key);
        int st = vka_nvn_stage(en->stage);
        if (st < 0) { out->bad |= VKA_BAD_MISSING; continue; }   // (vka_shlib_open refuses a stage past DMSH_VK_STAGE_MS)
        if (out->sh[st]) { static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) VRED("program serial %llu has two %s shaders (%016llx, %016llx): the second is used", (unsigned long long)p->serial, stage_name(en->stage), (unsigned long long)out->sh[st]->key, (unsigned long long)key); }
        out->sh[st] = vka_shader_make(source, key);
        if (!out->sh[st]) out->bad |= 1u << st;
    }
    vka_prog_put(p->serial, out);
    return 1;
}
#endif
