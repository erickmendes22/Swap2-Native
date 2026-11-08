// Swap2-Native: the game profile at start (rt/game_profile.h). Reads the pack's game_profile.tsv, the rows dm/games/game.py runtime writes from the profile:
// <NAME> TAB <value> per constant (numbers in decimal), MODULE / DISPLAY_VERSION / WINDOW_FN per list item, FORMAT 1 first; '#' lines are comments.
// Every constant game.py writes must be there: a pack from a packer that knew fewer keys stops here with the missing one named, rather than running with a guess
#include "../dm.h"
#include "game_profile.h"
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct dm_game_rt dm_game = {.shared_font_ttf = -1, .nvn_api_major = -1, .nvn_api_minor = -1};

enum { T_STR, T_U64, T_INT, T_UINT };
static const struct { const char *name; int type; size_t off; } KEYS[] = {
#define S(n, f) {#n, T_STR, offsetof(struct dm_game_rt, f)}
#define U(n, f) {#n, T_U64, offsetof(struct dm_game_rt, f)}
#define I(n, f) {#n, T_INT, offsetof(struct dm_game_rt, f)}
#define W(n, f) {#n, T_UINT, offsetof(struct dm_game_rt, f)}
    S(ID, id), S(NAME, name), S(ROMFS_MARKER, romfs_marker), S(ARGS, args), S(ENV, env), S(FASTBOOT_ENV, fastboot_env), S(UE_FPS_CVAR, ue_fps_cvar),
    U(PROGRAM_ID, program_id), U(MEM_RESERVE, mem_reserve), U(MEM_ALIAS, mem_alias), U(MEM_STACK, mem_stack), U(APP_POOL, app_pool), U(MEM_USED, mem_used),
    U(SYS_RESOURCE, sys_resource), U(STDALLOC_CAP, stdalloc_cap),
    I(MEM_MAP_LIMIT, mem_map_limit), I(PRESENT_DISPLAY, present_display), I(CORE_PREEMPT, core_preempt), I(ALLOC_BIG_ALIGN, alloc_big_align), I(FPS_TARGET, fps_target),
    I(FPS_HOLD, fps_hold), I(UE_TEXTURE_POOL, ue_texture_pool), I(PRESENT_SNAP, present_snap), I(PSO_MTL4, pso_mtl4), I(ENC_THREAD, enc_thread), I(PAD_LAYOUT, pad_layout),
    I(OPMODE, opmode), I(PERF_BOOST, perf_boost), I(TEX_FLUSH_UPLOAD, tex_flush_upload), I(RENDER_COND, render_cond), I(TEX_DIRTY_UPLOAD, tex_dirty_upload),
    I(TEX_DYN_SLOTS, tex_dyn_slots), I(GPU_TS_SEGMENT, gpu_ts_segment), I(VCONV_RANGE, vconv_range),
    W(SHADER_KEY_SKIP_OFF, shader_key_skip_off), W(SHADER_KEY_SKIP_LEN, shader_key_skip_len),
#undef S
#undef U
#undef I
#undef W
};
#define NKEYS (sizeof KEYS / sizeof *KEYS)

static int num(const char *s, uint64_t *out) {
    char *end; errno = 0;
    unsigned long long v = strtoull(s, &end, 10);
    if (errno || end == s || *end) return 0;
    *out = v; return 1;
}

int dm_game_load(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { LOG("[RED] game profile %s: %s (a pack from a packer before the one host for every game: prepare the game again)", path, strerror(errno)); return -1; }
    char seen[NKEYS] = {0}, line[4096]; int format = 0, lineno = 0, bad = 0;
    while (fgets(line, sizeof line, f)) {
        lineno++;
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
        if (!n || line[0] == '#') continue;
        char *c[8]; int nc = 0;
        for (char *p = line; nc < 8;) { c[nc++] = p; char *t = strchr(p, '\t'); if (!t) break; *t = 0; p = t + 1; }
        if (!strcmp(c[0], "FORMAT")) { format = nc > 1 ? atoi(c[1]) : 0; continue; }
        if (!strcmp(c[0], "MODULE") && nc == 2 && dm_game.nmod < DM_GAME_RT_MAXMOD) { dm_game.modules[dm_game.nmod++] = strdup(c[1]); continue; }
        if (!strcmp(c[0], "DISPLAY_VERSION") && nc == 3 && dm_game.nvers < DM_GAME_RT_MAXVER) {
            dm_game.vers[dm_game.nvers++] = (struct dm_game_ver){strdup(c[1]), strdup(c[2])}; continue;
        }
        uint64_t a, b, w, h;
        if (!strcmp(c[0], "WINDOW_FN") && nc == 6 && dm_game.nwfn < DM_GAME_RT_MAXWFN && num(c[2], &a) && num(c[3], &b) && num(c[4], &w) && num(c[5], &h)) {
            dm_game.wfn[dm_game.nwfn++] = (struct dm_game_wfn){strdup(c[1]), a, b, (unsigned)w, (unsigned)h}; continue;
        }
        if (!strcmp(c[0], "SHARED_FONT_TTF") && nc == 2 && num(c[1], &a)) { dm_game.shared_font_ttf = (int)a; continue; }
        if (!strcmp(c[0], "NVN_API_MAJOR") && nc == 2 && num(c[1], &a)) { dm_game.nvn_api_major = (int)a; continue; }
        if (!strcmp(c[0], "NVN_API_MINOR") && nc == 2 && num(c[1], &a)) { dm_game.nvn_api_minor = (int)a; continue; }
        // The NPDM's cores (pack_android.py): optional, so that a pack from an earlier packer still starts (hle_thread.c logs that it takes 0x7 then)
        if (!strcmp(c[0], "CORE_MASK") && nc == 2 && num(c[1], &a)) { dm_game.core_mask = a; continue; }
        if (!strcmp(c[0], "IDEAL_CORE") && nc == 2 && num(c[1], &a)) { dm_game.ideal_core = (int)a; continue; }
        unsigned k = 0;
        while (k < NKEYS && strcmp(KEYS[k].name, c[0])) k++;
        if (k == NKEYS) { LOG("[RED] game profile %s:%d: unknown row %s (a newer packer than this host?)", path, lineno, c[0]); bad = 1; continue; }
        const char *v = nc > 1 ? c[1] : "";
        char *field = (char *)&dm_game + KEYS[k].off;
        if (KEYS[k].type == T_STR) *(const char **)field = strdup(v);
        else if (!num(v, &a)) { LOG("[RED] game profile %s:%d: %s is not a number: %s", path, lineno, c[0], v); bad = 1; continue; }
        else if (KEYS[k].type == T_U64) *(uint64_t *)field = a;
        else if (KEYS[k].type == T_INT) *(int *)field = (int)a;
        else *(unsigned *)field = (unsigned)a;
        seen[k] = 1;
    }
    fclose(f);
    if (format != 1) { LOG("[RED] game profile %s: format %d, this host reads 1", path, format); return -1; }
    for (unsigned k = 0; k < NKEYS; k++) if (!seen[k]) { LOG("[RED] game profile %s: no %s row", path, KEYS[k].name); bad = 1; }
    if (!dm_game.nmod) { LOG("[RED] game profile %s: no MODULE rows", path); bad = 1; }
    if (dm_game.nvn_api_major >= 0 && dm_game.nvn_api_minor < 0) { LOG("[RED] game profile %s: NVN_API_MAJOR without NVN_API_MINOR", path); bad = 1; }
    if (bad) return -1;
    LOG("game profile %s: %s (%s), %d modules, %d builds, read at start", path, dm_game.name, dm_game.id, dm_game.nmod, dm_game.nvers);
    return 0;
}
