// Custom GPU drivers: DM_VK_DRIVER names a Vulkan driver the launcher installed into the app's private files (android/README.md "Custom GPU drivers"), such as a Mesa Turnip
// build or another Qualcomm release, and the replay runs on it instead of the system's. The driver is loaded as Eden does it, through libadrenotools (BSD-2-Clause,
// dm/third_party/libadrenotools): a private copy of the system libvulkan.so (the loader) in a linker namespace of its own whose hook answers the loader's request for the
// vendor driver with the custom one. libadrenotools is a library of its own, libnxadreno.so, opened here only when a driver is named: its constructor (liblinkernsbypass)
// changes dlopen's page protection, which the system driver path must not see.
//   DM_VK_DRIVER=<folder>   the folder holds the driver and its meta.json ("libraryName": the .so to load), as the driver zips Eden and others use
//   DM_VK_DRIVER=<path>.so  that library (its folder must hold whatever else it loads)
//   unset, empty, "system"  the system libvulkan.so, as before
// DM_VK_HOOKDIR overrides where the hook libraries are (by default the folder libnxhost.so was loaded from, inside the APK). Restart only (vka_ctl.c g_restart).
// A driver that fails to load falls back to the system one, with a [RED] line saying why.
#if defined(__ANDROID__)
#include "vka.h"
#include <ctype.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define ADRENOTOOLS_DRIVER_CUSTOM 1   // dm/third_party/libadrenotools/include/adrenotools/priv.h
typedef void *(*open_libvulkan_fn)(int dlopen_mode, int feature_flags, const char *tmp_lib_dir, const char *hook_lib_dir, const char *custom_driver_dir,
                                   const char *custom_driver_name, const char *file_redirect_dir, void **user_mapping_handle);

static char g_tag[96];   // the custom driver in use (file-name safe), empty for the system's

const char *vka_driver_tag(void) { return g_tag[0] ? g_tag : NULL; }

// "libraryName" from a driver folder's meta.json: the one string value the loader needs (a small JSON file; no parser for one key)
static int meta_library(const char *dir, char *out, size_t cap) {
    char p[1024]; snprintf(p, sizeof p, "%s/meta.json", dir);
    FILE *f = fopen(p, "rb"); if (!f) return 0;
    char buf[8192]; size_t n = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[n] = 0;
    char *k = strstr(buf, "\"libraryName\""); if (!k) return 0;
    char *c = strchr(k + 13, ':'); if (!c) return 0;
    char *q = strchr(c, '"'); if (!q) return 0;
    char *e = strchr(q + 1, '"'); if (!e || (size_t)(e - q - 1) >= cap || e == q + 1) return 0;
    memcpy(out, q + 1, (size_t)(e - q - 1)); out[e - q - 1] = 0;
    return !strchr(out, '/');
}

static void set_tag(const char *s) {
    size_t n = 0;
    for (; *s && n + 1 < sizeof g_tag; s++) g_tag[n++] = isalnum((unsigned char)*s) || *s == '-' || *s == '_' || *s == '.' ? *s : '_';
    g_tag[n] = 0;
}

// Opened once per process: the readiness check (vka_readiness.c) may open it before the replay's vka_init does, and both get the same library (adrenotools would
// otherwise load the custom driver into a second namespace)
static void *driver_open(void);
void *vka_driver_open(void) {
    static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER; static int tried; static void *lib;
    pthread_mutex_lock(&mu);
    if (!tried) { tried = 1; lib = driver_open(); }
    pthread_mutex_unlock(&mu);
    return lib;
}
static void *driver_open(void) {
    const char *drv = getenv("DM_VK_DRIVER");
    int custom = drv && *drv && strcmp(drv, "system") != 0;
    const char *qgl = getenv("DM_QGL_REDIRECT");
    if (qgl && *qgl) {
        // Only allow the game-private folder prepared by QglConfig. Hooking
        // is opt-in, per process, and never writes to /data/vendor/gpu.
        char filename[1200];
        if (qgl[0] != '/' || strlen(qgl) > 1000) qgl = NULL;
        else {
            snprintf(filename, sizeof filename, "%s/data/vendor/gpu/qgl_config.txt", qgl);
            if (access(filename, R_OK) != 0) {
                VRED("DM_QGL_REDIRECT: no readable qgl_config.txt: ignoring override");
                qgl = NULL;
            }
        }
    } else qgl = NULL;
    if (!custom && !qgl) return NULL; // default: untouched system loader

    char dir[1024] = {0}, name[256] = {0};
    if (custom) {
        size_t l = strlen(drv);
        if (l > 3 && !strcmp(drv + l - 3, ".so")) {
            const char *sl = strrchr(drv, '/');
            if (!sl || (size_t)(sl - drv) + 2 > sizeof dir || strlen(sl + 1) >= sizeof name) {
                VRED("DM_VK_DRIVER=%s: not a full path: the system driver is used", drv);
                custom = 0;
            } else {
                snprintf(dir, sizeof dir, "%.*s/", (int)(sl - drv), drv);
                snprintf(name, sizeof name, "%s", sl + 1);
            }
        } else {
            snprintf(dir, sizeof dir, "%s%s", drv, drv[l - 1] == '/' ? "" : "/");
            if (!meta_library(drv, name, sizeof name)) {
                VRED("DM_VK_DRIVER=%s: no meta.json with a libraryName: the system driver is used", drv);
                custom = 0;
            }
        }
        if (custom && (!strncmp(dir, "/sdcard/", 8) || !strncmp(dir, "/storage/", 9)))
            VRED("DM_VK_DRIVER=%s is on shared storage; install to app private files", drv);
    }
    if (!custom && !qgl) return NULL;
    char hook[1024];
    const char *hd = getenv("DM_VK_HOOKDIR");
    if (hd && *hd) snprintf(hook, sizeof hook, "%s%s", hd, hd[strlen(hd) - 1] == '/' ? "" : "/");
    else {
        Dl_info di; const char *sl;
        if (!dladdr((void *)vka_driver_open, &di) || !di.dli_fname ||
            !(sl = strrchr(di.dli_fname, '/'))) {
            VRED("QGL/custom Vulkan: cannot locate hook libraries; system loader unchanged");
            return NULL;
        }
        snprintf(hook, sizeof hook, "%.*s/", (int)(sl - di.dli_fname), di.dli_fname);
    }
    void *at = dlopen("libnxadreno.so", RTLD_NOW | RTLD_LOCAL);
    open_libvulkan_fn open_vk = at ? (open_libvulkan_fn)dlsym(at, "adrenotools_open_libvulkan") : NULL;
    if (!open_vk) {
        VRED("QGL/custom Vulkan: libnxadreno.so missing (%s), using system driver", dlerror());
        return NULL;
    }
    int flags = (custom ? ADRENOTOOLS_DRIVER_CUSTOM : 0) | (qgl ? 2 : 0); // FILE_REDIRECT = 1 << 1
    void *lib = open_vk(RTLD_NOW, flags, NULL, hook,
                        custom ? dir : NULL, custom ? name : NULL, qgl, NULL);
    if (!lib) {
        VRED("QGL/custom Vulkan: adrenotools could not initialize (hooks %s); unmodified system Vulkan loader used", hook);
        return NULL;
    }
    if (qgl) VLOG("QGL override: private qgl_config.txt redirect armed (driver acceptance not verified)");
    if (!custom) return lib;
    const char *base = dir + strlen(dir) - 1;
    while (base > dir && base[-1] != '/') base--;
    char b[128];
    snprintf(b, sizeof b, "%.*s", (int)(dir + strlen(dir) - 1 - base), base);
    set_tag(b[0] ? b : name);
    VLOG("custom GPU driver: %s%s (hooks in %s), separate pipeline cache (vk_pipelines-%s" VKA_PCACHE_GEN ".bin unless DM_VK_PCACHE overrides)", dir, name, hook, g_tag);
    return lib;
}

#endif // __ANDROID__
