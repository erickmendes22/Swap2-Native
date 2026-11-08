// Swap2-Native: the game profile read at start instead of compiled in (one host for every game; android/host/CMakeLists.txt NX_RUNTIME_PROFILE). The same names as the
// header dm/games/game.py writes for a host built for one game (game.py header), each a field of dm_game, which game_rt.c fills from the pack's game_profile.tsv
// (game.py runtime, written by scripts/pack_android.py) before main runs (front_android.c nxhost_main). The lists and the optional keys have no macro here: their few
// users read dm_game under DM_GAME_RUNTIME (hle_cheats.c, hle_sdk16.c, loader.c, main.c, hle_nvn.c)
#pragma once
#include <stdint.h>

#define DM_GAME_RUNTIME 1
#define DM_GAME_RT_MAXMOD 16
#define DM_GAME_RT_MAXVER 32
#define DM_GAME_RT_MAXWFN 16

struct dm_game_ver { const char *build, *ver; };
struct dm_game_wfn { const char *build; uint64_t wfn, hfn; unsigned w, h; };

struct dm_game_rt {
    const char *id, *name, *romfs_marker, *args, *env, *fastboot_env, *ue_fps_cvar;
    uint64_t program_id, mem_reserve, mem_alias, mem_stack, app_pool, mem_used, sys_resource, stdalloc_cap;
    int mem_map_limit, present_display, core_preempt, alloc_big_align, fps_target, fps_hold, ue_texture_pool, present_snap, pso_mtl4, enc_thread, pad_layout, opmode,
        perf_boost, tex_flush_upload, render_cond, tex_dirty_upload, tex_dyn_slots, gpu_ts_segment, vconv_range;
    unsigned shader_key_skip_off, shader_key_skip_len;
    int shared_font_ttf;            // -1: the profile has no shared_font (the host decides by the SDK)
    int nvn_api_major, nvn_api_minor;   // -1: no device_api (by the SDK)
    uint64_t core_mask; int ideal_core;   // the NPDM's cores (CORE_MASK / IDEAL_CORE rows); core_mask 0: a pack from a packer before them (hle_thread.c takes a Switch 1's 0x7)
    const char *modules[DM_GAME_RT_MAXMOD]; int nmod;
    struct dm_game_ver vers[DM_GAME_RT_MAXVER]; int nvers;
    struct dm_game_wfn wfn[DM_GAME_RT_MAXWFN]; int nwfn;
};
extern struct dm_game_rt dm_game;

// Reads <path> (game.py runtime's rows) into dm_game. 0 = loaded; -1 with the reason logged ([RED]) when the file is missing, malformed or lacks a key
int dm_game_load(const char *path);

#define DM_GAME_ID (dm_game.id)
#define DM_GAME_NAME (dm_game.name)
#define DM_GAME_PROGRAM_ID (dm_game.program_id)
#define DM_GAME_NMOD (dm_game.nmod)
#define DM_GAME_ROMFS_MARKER (dm_game.romfs_marker)
#define DM_GAME_MEM_RESERVE (dm_game.mem_reserve)
#define DM_GAME_MEM_ALIAS (dm_game.mem_alias)
#define DM_GAME_MEM_STACK (dm_game.mem_stack)
#define DM_GAME_APP_POOL (dm_game.app_pool)
#define DM_GAME_MEM_USED (dm_game.mem_used)
#define DM_GAME_SYS_RESOURCE (dm_game.sys_resource)
#define DM_GAME_ARGS (dm_game.args)
#define DM_GAME_ENV (dm_game.env)
#define DM_GAME_FASTBOOT_ENV (dm_game.fastboot_env)
#define DM_GAME_MEM_MAP_LIMIT (dm_game.mem_map_limit)
#define DM_GAME_STDALLOC_CAP (dm_game.stdalloc_cap)
#define DM_GAME_PRESENT_DISPLAY (dm_game.present_display)
#define DM_GAME_CORE_PREEMPT (dm_game.core_preempt)
#define DM_GAME_CORE_MASK (dm_game.core_mask)
#define DM_GAME_IDEAL_CORE (dm_game.ideal_core)
#define DM_GAME_ALLOC_BIG_ALIGN (dm_game.alloc_big_align)
#define DM_GAME_FPS_TARGET (dm_game.fps_target)
#define DM_GAME_FPS_HOLD (dm_game.fps_hold)
#define DM_GAME_UE_TEXTURE_POOL (dm_game.ue_texture_pool)
#define DM_GAME_UE_FPS_CVAR (dm_game.ue_fps_cvar)
#define DM_GAME_PRESENT_SNAP (dm_game.present_snap)
#define DM_GAME_PSO_MTL4 (dm_game.pso_mtl4)
#define DM_GAME_ENC_THREAD (dm_game.enc_thread)
#define DM_GAME_PAD_LAYOUT (dm_game.pad_layout)
#define DM_GAME_OPMODE (dm_game.opmode)
#define DM_GAME_PERF_BOOST (dm_game.perf_boost)
#define DM_GAME_TEX_FLUSH_UPLOAD (dm_game.tex_flush_upload)
#define DM_GAME_SHADER_KEY_SKIP_OFF (dm_game.shader_key_skip_off)
#define DM_GAME_SHADER_KEY_SKIP_LEN (dm_game.shader_key_skip_len)
#define DM_GAME_RENDER_COND (dm_game.render_cond)
#define DM_GAME_TEX_DIRTY_UPLOAD (dm_game.tex_dirty_upload)
#define DM_GAME_TEX_DYN_SLOTS (dm_game.tex_dyn_slots)
#define DM_GAME_GPU_TS_SEGMENT (dm_game.gpu_ts_segment)
#define DM_GAME_VCONV_RANGE (dm_game.vconv_range)
#define DM_GAME_NWINDOW_FN (dm_game.nwfn)
