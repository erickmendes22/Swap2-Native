"""Ocarina visual-quality GPU patches: exact whitelist and draw/compute parity."""
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
GAME = ROOT / "dm/games/0400486024DEC000/game.tsv"
VK = ROOT / "dm/gfx/vk_android"
APP = ROOT / "android/app/src/main/java/dev/nxnative/android"


class OcarinaQualityTest(unittest.TestCase):
    def test_reviewed_cosmetic_pairs_not_arbitrary_shaders(self):
        profiles = [
            (cols[1], cols[2]) for line in GAME.read_text().splitlines()
            if (cols := line.split("\t"))[0] == "mesh_vegetation_cut"
        ]
        self.assertEqual(len(profiles), 7)
        hdr = (VK / "vka_vegetation_quality.h").read_text()
        # The v2 profile selects only the formerly retained pair A and B.
        keep = [profiles[3], profiles[6]]
        for first, second in keep:
            self.assertIn(first, hdr)
            self.assertIn(second, hdr)
        self.assertEqual(hdr.count("return 1;"), 1)
        self.assertEqual(hdr.count("return 2;"), 1)
        self.assertIn("tier == 3 || tier == pair", hdr)
        self.assertIn("tier <= 0 || tier >= 4", hdr)
        for first, second in profiles:
            if (first, second) not in keep:
                self.assertNotIn(first, hdr)
                self.assertNotIn(second, hdr)
        # No backdoor for unrelated games, other original Ocarina shaders,
        # or the other two full-vegetation original cosmetic pairs.
        self.assertIn('strcmp(title, "0400486024DEC000")', hdr)
        self.assertIn("tier <= 0 || tier >= 4", hdr)
        self.assertNotIn("mesh_vegetation_cut", (VK / "vka_memu_spv.c").read_text())

    def test_native_cut_before_expensive_mesh_compute_and_final_raster(self):
        draw = (VK / "vka_draw.c").read_text()
        replay = (VK / "vka_exec.c").read_text()
        self.assertIn('#include "vka_vegetation_quality.h"', draw)
        self.assertIn("vka_vegetation_quality_key(DM_GAME_ID, sh[7]->key, tier)", draw)
        self.assertIn("d->tf_on", draw)
        self.assertIn("DMSH_VK_BF_RW | DMSH_VK_BF_ATOMIC | DMSH_VK_BF_NOSLOT", draw)
        self.assertIn("const int quality_trim =", replay)
        self.assertIn("vegetation_off || quality_trim", replay)
        self.assertIn("vka_vegetation_mesh_omit(&g_memu_st)", replay)
        self.assertIn("vka_vegetation_mesh_omit(&S.d)", replay)
        self.assertIn("vegetation_cut(d, sh)", draw)
        self.assertIn('VKA_ENV("DM_VK_OOT_VEG_QUALITY", 0)', draw)

    def test_launcher_fallback_and_game_local_prefs(self):
        pref = (APP / "Prefs.java").read_text()
        settings = (APP / "GameSettings.java").read_text()
        activity = (APP / "GameActivity.java").read_text()
        self.assertIn('getBoolean(gameKey("full_vegetation", id), true)', pref)
        self.assertIn('getInt(gameKey("oot_vegetation_detail_v3", id), fallback)', pref)
        self.assertIn('checked != 3', pref)
        self.assertIn('Prefs.fullVegetation(a,id,true)', settings)
        self.assertIn('Prefs.vegetationDetail(a, id, index)', settings)
        self.assertIn('DM_VK_OOT_VEG_QUALITY=', activity)
        self.assertIn('DM_VK_VEGETATION=', activity)

    def test_compile_and_execute_actual_quality_selector(self):
        if not shutil.which("cc"):
            self.skipTest("C compiler unavailable")
        code = r'''
#include <stdint.h>
#include <assert.h>
#include "vka_vegetation_profiles.h"
#include "vka_vegetation_quality.h"
int main(void) {
    const char *title = "0400486024DEC000";
    const uint64_t pairs[7][2] = {
      {0x0c1ffecd02018fb0ull,0xeed1add7c89f5d34ull},
      {0x25c4a740753e7d7aull,0x73dc0b90c4082e43ull},
      {0x101ecb327aafe9b1ull,0x17c8ab6419068d4bull},
      {0x5b737961ae3e1b10ull,0xecead5cd0569091full},
      {0xeebdb9347d09b344ull,0x604134a5262ff670ull},
      {0xd98076e4148db34full,0xfed302d791a4ba43ull},
      {0x839241636fce850aull,0x4c7d6be5a7717c8dull}
    };
    for(int level=0;level<=4;level++){
        int selected=0;
        for(int i=0;i<7;i++) {
            int a=vka_vegetation_quality_key(title,pairs[i][0],level);
            int b=vka_vegetation_quality_key(title,pairs[i][1],level);
            assert(a==b);
            if(a)selected++;
            assert(vka_vegetation_key(title,pairs[i][0]));
        }
        assert(selected==(level==1?1:level==2?1:level==3?2:0));
    }
    assert(!vka_vegetation_quality_key("another-title", pairs[3][0], 3));
    assert(!vka_vegetation_quality_key(title, 0x123456789abcdef0ull, 3));
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src = pathlib.Path(td) / "test.c"
            out = pathlib.Path(td) / "test"
            src.write_text(code)
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-I", str(VK), str(src), "-o", str(out)],
                check=True
            )
            subprocess.run([str(out)], check=True)


if __name__ == "__main__":
    unittest.main()
