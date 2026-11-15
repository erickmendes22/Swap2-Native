#!/usr/bin/env python3
"""Ocarina individually testable layer omissions and internal SGSR1 source-level guards.

The actual new compute SPIR-V must ALSO pass glslc + spirv-val in APK CI.
"""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"


class OcarinaSgsrLayersTest(unittest.TestCase):
    def test_hidden_layers_exact_keys_and_independence(self):
        header = VK / "vka_hidden_layers.h"
        harness = r'''
#include "vka_hidden_layers.h"
#include <assert.h>
int main(void) {
    assert(!vka_oot_skip_fs_key(VKA_OOT_FS_HEAVY, 0, 0));
    assert(!vka_oot_skip_fs_key(VKA_OOT_FS_LAYER2, 0, 0));
    assert(vka_oot_skip_fs_key(VKA_OOT_FS_HEAVY, 0, 1));
    assert(!vka_oot_skip_fs_key(VKA_OOT_FS_LAYER2, 0, 1));
    assert(vka_oot_skip_fs_key(VKA_OOT_FS_HEAVY, 1, 0));
    assert(vka_oot_skip_fs_key(VKA_OOT_FS_LAYER2, 1, 0));
    assert(vka_oot_skip_fs_key(VKA_OOT_FS_HEAVY, 1, 1));
    assert(vka_oot_skip_fs_key(VKA_OOT_FS_LAYER2, 1, 1));
    assert(!vka_oot_skip_fs_key(0xABCDEF1234567890ULL, 1, 1));
    assert(!vka_oot_skip_fs_individual(VKA_OOT_FS_HEAVY, 0, 0));
    assert(!vka_oot_skip_fs_individual(VKA_OOT_FS_LAYER2, 0, 0));
    assert(vka_oot_skip_fs_individual(VKA_OOT_FS_HEAVY, 1, 0));
    assert(!vka_oot_skip_fs_individual(VKA_OOT_FS_LAYER2, 1, 0));
    assert(!vka_oot_skip_fs_individual(VKA_OOT_FS_HEAVY, 0, 1));
    assert(vka_oot_skip_fs_individual(VKA_OOT_FS_LAYER2, 0, 1));
    assert(vka_oot_skip_fs_individual(VKA_OOT_FS_HEAVY, 1, 1));
    assert(vka_oot_skip_fs_individual(VKA_OOT_FS_LAYER2, 1, 1));
    assert(!vka_oot_skip_fs_individual(0xABCDEF1234567890ULL, 1, 1));
    return 0;
}
'''
        self.assertTrue(header.exists())
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / "test.c"
            exe = pathlib.Path(tmp) / "test"
            src.write_text(harness)
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-O2", "-I", str(VK), str(src), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_layer_omission_retired_in_real_draw_path(self):
        text = (VK / "vka_draw.c").read_text()
        start = text.index("void vka_draw(vka_dstate")
        end = text.index("void vka_dispatch(", start)
        draw = text[start:end]
        self.assertNotIn("oot_skip_hidden_fs(", text)
        self.assertEqual(draw.count("if (oot_skip_one_fs(sh[1])) SKIPQ();"), 2)
        self.assertIn('int a = 0;', text)
        self.assertIn('DM_VK_OOT_SKIP_LAYER2_FS', text)
        self.assertIn('vka_oot_skip_fs_individual(fs->key, a, b)', text)
        self.assertNotIn('VKA_ENV("DM_VK_OOT_SKIP_HEAVY_FS", 0)', text)
        self.assertIn('VKA_ENV("DM_VK_OOT_SKIP_LAYER2_FS", 0)', text)

    def test_sgsr_full_n_ds_replacement_and_fallback(self):
        shader = (VK / "fsr/ndsr_easu.comp").read_text()
        host = (VK / "vka_ndsr.c").read_text()
        profile = (JAVA / "Profile.java").read_text()
        options = (JAVA / "GraphicsOptions.java").read_text()
        self.assertIn("vec3 sgsrReconstruct", shader)
        self.assertIn("KERNEL == 2", shader)
        self.assertEqual(shader.count("weight += sgsrWeight("), 11)
        self.assertIn("imageStore(dst", shader)
        self.assertIn("if (ENC == 1) c *= c;", shader)
        tiled = (VK / "fsr/ndsr_sgsr.comp").read_text()
        self.assertIn("#define UseEdgeDirection", tiled)
        self.assertIn("local_size_x=8,local_size_y=8", tiled)
        self.assertIn("VKA_NDSR_KERNEL_SGSR_TILED", host)
        self.assertIn("vka_ndsr_sgsr_words", host)
        self.assertIn(".addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE", host)
        self.assertIn('!strcmp(v, "sgsr")', host)
        self.assertIn("VKA_NDSR_KERNEL_SGSR", host)
        self.assertIn('env.add("DM_VK_NDSR=sgsr")', profile)
        self.assertIn('"sgsr-compute".equals(choice)', profile)
        self.assertIn("NDSR_SGSR_COMPUTE.equals(Prefs.ndsr(c, id))", options)
        self.assertIn('out.add("DM_VK_OOT_SGSR_CHAIN=" +', options)
        self.assertIn("DM_VK_NDSR=fsr", profile)

    def test_retired_layer_preference_cannot_restore_artifacts(self):
        pref = (JAVA / "Prefs.java").read_text()
        launch = (JAVA / "GameActivity.java").read_text()
        ui = (JAVA / "GameSettings.java").read_text()
        self.assertIn('static boolean hiddenLayersOff(Context c, String titleId) { return false; }', pref)
        self.assertNotIn('gameKey("oot_hidden_layers", titleId), false', pref)
        self.assertIn('env.add("DM_VK_OOT_HIDDEN_LAYERS=0");', launch)
        self.assertIn('env.add("DM_VK_OOT_SKIP_HEAVY_FS=0");', launch)
        self.assertIn('env.add("DM_VK_OOT_SKIP_LAYER2_FS="', launch)
        self.assertNotIn('Prefs.skipFsA(this, id)', launch)
        self.assertIn('Prefs.skipFsB(this, id)', launch)
        self.assertIn('static boolean skipFsA(Context c, String id) { return false; }', pref)
        self.assertIn('getBoolean(gameKey("oot_fs_b_diagnostic", id), false)', pref)
        self.assertNotIn('Prefs.skipFsA(a, id)', ui)
        self.assertIn('Prefs.skipFsB(a, id)', ui)
        self.assertIn('static boolean skipHeavyFragment(Context c, String titleId) { return false; }', pref)
        self.assertNotIn('Prefs.hiddenLayersOff(a, id)', ui)
        self.assertNotIn('"Ocultar camadas (teste)"', ui)
        self.assertNotIn('Prefs.skipHeavyFragment(a, id)', ui)


if __name__ == "__main__":
    unittest.main()
