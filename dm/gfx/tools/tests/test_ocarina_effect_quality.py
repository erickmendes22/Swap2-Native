"""Live-source regression for Ocarina hard-shadow and ground-mist GPU presets."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"
APP = ROOT / "android/app/src/main/java/dev/nxnative/android"


def function(src, name):
    import re
    match = re.search(r"\b(?:static\s+)?int\s+" + name + r"\s*\([^;]*?\)\s*\{", src, re.S)
    if not match:
        raise AssertionError("missing exact " + name)
    begin = match.start()
    first = src.index("{", match.start())
    n = 1
    i = first + 1
    while n:
        n += (src[i] == "{") - (src[i] == "}")
        i += 1
    return src[begin:i]


class OcarinaEffectQuality(unittest.TestCase):
    def test_shadow_gate_uses_actual_comparison_sampler_only(self):
        text = (VK / "vka_tex.c").read_text()
        self.assertIn('#include "game_profile.h"', text)
        self.assertIn("DM_VK_OOT_SHADOW_HARD", text)
        self.assertIn("ci.compareEnable && !iv", text)
        self.assertIn("ci.magFilter = ci.minFilter = VK_FILTER_NEAREST", text)
        self.assertIn("ci.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST", text)
        self.assertIn("ci.anisotropyEnable = VK_FALSE", text)
        self.assertIn('strcmp(DM_GAME_ID, "0400486024DEC000")', text)
        self.assertIn(".compareOp = p->cmp_func", text)
        self.assertNotIn("ci.compareEnable = VK_FALSE", text)

    def test_fog_effect_is_actual_identified_paired_shader_not_froxels(self):
        draw = (VK / "vka_draw.c").read_text()
        replay = (VK / "vka_exec.c").read_text()
        self.assertIn("0x5ad65c0eefd09c7f", draw)
        self.assertIn("0x066f5daf12e43c71", draw)
        self.assertIn("0x554cf8c05126a133", draw)
        self.assertNotIn("0x9ed48d1011f1b48b", function(draw, "oot_ground_mist_safe"))
        self.assertIn("vka_ground_mist_mesh_omit(&g_memu_st)", replay)
        self.assertIn("vka_ground_mist_mesh_omit(&S.d)", replay)
        self.assertIn("oot_ground_mist_safe(d, sh)", draw)
        self.assertIn("d->tf_on", draw)
        self.assertIn("DMSH_VK_BF_RW | DMSH_VK_BF_ATOMIC | DMSH_VK_BF_NOSLOT", draw)

    def test_actual_c_pair_and_side_effect_validation(self):
        cc = shutil.which("clang") or shutil.which("cc")
        if not cc:
            self.skipTest("no C compiler")
        draw = (VK / "vka_draw.c").read_text()
        safe = function(draw, "oot_ground_mist_safe")
        code = '''
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "dmsh_abi_vk.h"
#define VKA_NSTAGE 8
#define DM_GAME_ID "0400486024DEC000"
static int mist_on;
#define VKA_ENV(key, fallback) mist_on
typedef struct { int tf_on; } vka_dstate;
typedef struct { const dmsh_vk_entry *e; const dmsh_vk_bind *b; uint64_t key; } vka_shader;
''' + safe + '''
int main(void) {
    dmsh_vk_entry entry={0};
    dmsh_vk_bind bind={0};
    vka_shader mesh={.e=&entry,.b=&bind,.key=0x066f5daf12e43c71ull};
    vka_shader fog={.e=&entry,.b=&bind,.key=0x5ad65c0eefd09c7full};
    vka_shader *sh[8]={0}; sh[1]=&fog; sh[7]=&mesh;
    vka_dstate state={0};
    assert(!oot_ground_mist_safe(&state,sh)); // original always on
    mist_on=1; assert(oot_ground_mist_safe(&state,sh));
    mesh.key=0x554cf8c05126a133ull; assert(oot_ground_mist_safe(&state,sh));
    mesh.key=0x1234; assert(!oot_ground_mist_safe(&state,sh));
    mesh.key=0x066f5daf12e43c71ull; fog.key=0x1234;
    assert(!oot_ground_mist_safe(&state,sh));
    fog.key=0x5ad65c0eefd09c7full;
    state.tf_on=1; assert(!oot_ground_mist_safe(&state,sh)); state.tf_on=0;
    entry.bind_count=1; bind.flags=DMSH_VK_BF_RW;
    assert(!oot_ground_mist_safe(&state,sh));
    bind.flags=DMSH_VK_BF_ATOMIC; assert(!oot_ground_mist_safe(&state,sh));
    bind.flags=DMSH_VK_BF_NOSLOT; assert(!oot_ground_mist_safe(&state,sh));
    bind.flags=0; bind.kind=DMSH_VK_KIND_GMEM_LOG;
    assert(!oot_ground_mist_safe(&state,sh));
    bind.kind=DMSH_VK_KIND_UNKNOWN;
    assert(!oot_ground_mist_safe(&state,sh));
    entry.bind_count=0; sh[1]=0; assert(!oot_ground_mist_safe(&state,sh));
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src = pathlib.Path(td) / "test.c"
            exe = pathlib.Path(td) / "test"
            src.write_text(code)
            subprocess.run([cc, "-std=c11", "-O1", "-g", "-Wall", "-Werror",
                            "-I" + str(ROOT / "dm/gfx/nvn"),
                            str(src), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_launcher_settings_stay_per_game_default_off(self):
        prefs=(APP / "Prefs.java").read_text()
        ui=(APP / "GameSettings.java").read_text()
        launcher=(APP / "GameActivity.java").read_text()
        for key in ("shadowHard","groundMistOff"):
            self.assertIn("Prefs." + key + "(a, id)", ui)
            self.assertIn("Prefs." + key + "(this, id)", launcher)
        self.assertIn('"oot_shadow_hard", id), false',prefs)
        self.assertIn('"oot_ground_mist_off", id), false',prefs)
        self.assertIn("DM_VK_OOT_SHADOW_HARD=", launcher)
        self.assertIn("DM_VK_OOT_GROUND_MIST_OFF=", launcher)


if __name__ == "__main__":
    unittest.main()
