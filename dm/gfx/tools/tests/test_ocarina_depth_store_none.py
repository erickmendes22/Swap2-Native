"""Ocarina 720p Vulkan 1.3 depth STORE_OP_NONE read-only correctness gate.

This is a GPU memory traffic candidate, NOT another VRS experiment.
Unit tests exercise the exact native eligibility predicate compiled by a C
compiler, and assert that the first later writer/clear reopens a STORE pass.
Real FPS and image equivalence still require Adreno device testing.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HDR = ROOT / "dm/gfx/vk_android/vka_readonly_depth_store.h"
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
VRS = (ROOT / "dm/gfx/vk_android/vka_oot_heavy_pass_vrs.h").read_text()

class ReadonlyDepthStoreTests(unittest.TestCase):
    def test_title_default_off_and_optin_reversible(self):
        self.assertIn('VKA_ENV("DM_VK_OOT_DEPTH_STORE_NONE", 0)', DRAW)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', DRAW)
        self.assertIn('if (R.on && R.readonly_depth_store && d && d->ds.dt && d->ds.dw)', DRAW)
        self.assertIn('if (R.on && R.readonly_depth_store && c->ci < 0)', DRAW)
        self.assertIn('da.storeOp = VK_ATTACHMENT_STORE_OP_NONE;', DRAW)
        self.assertIn('g_readonly_depth_writer_splits++', DRAW)
        self.assertNotIn('0x19f99e925937b038', VRS, "never revive the zero-FPS 4x2 VRS patch")

    def test_native_eligibility_strictly_readonly_720p_no_stencil(self):
        self.assertTrue(shutil.which('cc'), "C compiler required")
        src = r"""
#include <assert.h>
#include "vka_readonly_depth_store.h"
static int q(int ocarina, int enabled, unsigned width, unsigned height,
             unsigned samples, int vk13, int depth, int stencil, int load,
             int store, int clear, int writing, int classic) {
    return vka_readonly_depth_store_eligible(
        ocarina, enabled, width, height, samples, vk13, depth, stencil,
        load, store, clear, writing, classic);
}
int main(void) {
    const int baseline[13]={1,1,1280,720,1,1,1,0,1,1,0,0,0};
    assert(q(1,1,1280,720,1,1,1,0,1,1,0,0,0));
    for (int i=0;i<13;i++) {
        int z[13]; for(int j=0;j<13;j++)z[j]=baseline[j];
        switch(i) {
            case 0:z[i]=0;break;
            case 1:z[i]=0;break;
            case 2:z[i]=960;break;
            case 3:z[i]=540;break;
            case 4:z[i]=4;break;
            case 5:z[i]=0;break;
            case 6:z[i]=0;break;
            case 7:z[i]=1;break;
            case 8:z[i]=0;break;
            case 9:z[i]=0;break;
            case 10:z[i]=1;break;
            case 11:z[i]=1;break;
            case 12:z[i]=1;break;
        }
        assert(!q(z[0],z[1],z[2],z[3],z[4],z[5],
                  z[6],z[7],z[8],z[9],z[10],z[11],z[12]));
    }
    return 0;
}"""
        with tempfile.TemporaryDirectory() as work:
            f = Path(work)/"test.c"
            exe=Path(work)/"test"
            f.write_text(src)
            cmd=[shutil.which("cc"),"-std=c11","-O2","-Wall","-Wextra","-Werror",
                 "-I",str(HDR.parent),str(f),"-o",str(exe)]
            p=subprocess.run(cmd, capture_output=True,text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
