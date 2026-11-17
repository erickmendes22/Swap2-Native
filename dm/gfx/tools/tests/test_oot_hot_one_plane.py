"""Exact hot mesh/FS source-only single-plane pruning policy.

No new GPU shaders are created unless ACTUAL bound FS input mask identifies
one unused vec4. Producer/consumer must apply the same predicate and the
original >=2-plane rule stays for every other shader and title.
"""
import unittest,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/"dm/gfx/vk_android"
SRC=(VK/"vka_memu.c").read_text()
class HotOnePlane(unittest.TestCase):
    def test_pair_safety_and_identical_masks(self):
        cs=SRC.split("vka_shader *vka_memu_cs_for_fs(",1)[1].split(
            "vka_shader *vka_memu_vs_for_fs(",1)[0]
        vs=SRC.split("vka_shader *vka_memu_vs_for_fs(",1)[1].split(
            "vka_shader *vka_memu_by_key(",1)[0]
        for path in (cs,vs):
            self.assertIn('vka_oot_hot_one_plane_eligible(',path)
            self.assertIn('VKA_ENV("DM_VK_OOT_ONE_PLANE_PRUNE", 0)',path)
            self.assertIn('unsigned dropped = (unsigned)__builtin_popcountll(all & ~used);',path)
            self.assertIn('used == all',path)
            self.assertIn('vka_memu_pixel_mask(fragment, &used)',path)
        self.assertIn('vka_memu_cs_masked(',cs)
        self.assertIn('vka_memu_vs_masked(',vs)
        self.assertIn('g_memu_varying_words_saved += dropped * 4u',vs)
        self.assertIn('hot-mesh-draws=',SRC)
        self.assertIn('bound-FS-resolved=',SRC)
        self.assertIn('void vka_memu_hot_one_pair_note(',SRC)
        self.assertIn('vka_memu_hot_one_pair_note(ms->key, fs_ok && fs != NULL);',draw)
        draw=(VK/"vka_memu_draw.inc").read_text()
        self.assertIn('if (sel_cs && sel_cs != E->mcs)',draw)
        self.assertIn('E->vs = sel_vs; E->mcs = sel_cs;',draw)
    def test_compiled_c_policy_exact_keys_and_rollback(self):
        code=r"""
#include <assert.h>
#include <stdint.h>
#include "vka_oot_one_plane.h"
int main(void) {
 const uint64_t k[]={
    0xeb021183bf9b0092ULL,0xfed302d791a4ba43ULL,
    0x3439aaa071d868aeULL,0x604134a5262ff670ULL,
    0x73dc0b90c4082e43ULL
 };
 for(unsigned i=0;i<5;i++)for(unsigned d=0;d<6;d++)
 for(int game=0;game<2;game++)for(int on=0;on<2;on++){
   int expect=game&&on&&d==1&&i<3;
   assert(vka_oot_hot_one_plane_eligible(game,on,k[i],d)==expect);
 }
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/"p.c";exe=Path(td)/"p";src.write_text(code)
            p=subprocess.run(["cc","-std=c11","-O2","-Wall","-Wextra","-Werror",
                "-fsanitize=undefined","-I",str(VK),str(src),"-o",str(exe)],
                capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            q=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(q.returncode,0,q.stderr)
if __name__=="__main__":
    unittest.main()
