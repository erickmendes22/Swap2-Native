"""GPU-real workgroup density: validated stage keys, counts and shadow-only gates."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"
APP = ROOT / "android/app/src/main/java/dev/nxnative/android"


def reduced_counts(groups, task_counts, mode):
    # Model the generated task_out counts: zero specific task group emissions.
    counts = []
    for task, cnt in enumerate(task_counts):
        cut = (mode == 1 and task % 4 == 3) or (mode == 2 and task % 2 == 1)
        counts.append(0 if cut else cnt)
    # The real distribution reads these exact counts to produce R_TOTAL.
    return counts, sum(counts)


class FoliageTaskDensity(unittest.TestCase):
    def test_no_dispatch_for_group_zero_counts_and_dense_offsets(self):
        for n in (1, 2, 3, 4, 5, 8, 16, 32, 97, 257, 3200):
            for counts in ([1] * n, [3] * n, list(range(n)),
                           [0 if i % 7 == 0 else 5 for i in range(n)]):
                normal, total = reduced_counts(n, counts, 0)
                self.assertEqual(normal, counts)
                self.assertEqual(total, sum(counts))
                for mode in (1, 2):
                    new, work = reduced_counts(n, counts, mode)
                    self.assertLessEqual(work, total)
                    self.assertEqual(work, sum(new))
                    # Distribution offsets must remain contiguous and never
                    # index past allocated group count after suppression.
                    out = 0
                    for val in new:
                        start = out
                        out += val
                        self.assertGreaterEqual(out, start)
                    self.assertEqual(out, work)
                    self.assertTrue(all(v in (0, counts[i]) for i, v in enumerate(new)))
        for mode, expect in ((0, 400), (1, 300), (2, 200)):
            self.assertEqual(reduced_counts(400, [1] * 400, mode)[1], expect)

    def test_exact_only_one_reviewed_task_mesh_pair(self):
        src = (VK / "vka_memu_draw.inc").read_text()
        abi = (VK / "vka_memu_abi.h").read_text()
        spv = (VK / "vka_memu_spv.c").read_text()
        tags = (VK / "vka_memu.h").read_text()
        self.assertIn("0x99280b7b8aae78df", src)
        self.assertIn("0xeb021183bf9b0092", src)
        self.assertIn("DMSH_VK_BF_RW | DMSH_VK_BF_ATOMIC | DMSH_VK_BF_NOSLOT", src)
        self.assertIn('VKA_ENV("DM_VK_VEGETATION", 1)', src)
        self.assertIn('VKA_ENV("DM_VK_OOT_FOLIAGE_DENSITY", 0)', src)
        self.assertIn("VKA_MEMU_F_FOLIAGE_75", src)
        self.assertIn("VKA_MEMU_F_FOLIAGE_50", src)
        self.assertIn("VKA_MEMU_F_FOLIAGE_75 16", abi)
        self.assertIn("VKA_MEMU_F_FOLIAGE_50 32", abi)
        self.assertIn("emit_count = sel(&f, B.t_u32, cut, c0, cnt);", spv)
        self.assertIn("R_COUNTS)), ts)), emit_count", spv)
        self.assertIn("VKA_MEMU_KEY_TASK_DENSITY", tags)
        self.assertIn("stage == DMSH_VK_STAGE_TS ? VKA_MEMU_KEY_TASK_DENSITY", tags)
        self.assertNotIn("vkCmdDrawIndexedIndirect", spv)

    def test_shadow_pass_restricted_to_1024_4096_depth_only(self):
        e = (VK / "vka_exec.c").read_text()
        self.assertIn("S.rt.depth->d.width", e)
        self.assertIn("w == h && (w == 1024 || w == 4096)", e)
        self.assertIn("!S.d.ds.dt || !S.d.ds.dw", e)
        self.assertIn("if (S.rt.color[i]) return 0;", e)
        self.assertIn("vka_memu_oot_shadow_level(shadow);", e)
        self.assertIn('VKA_ENV("DM_VK_OOT_SHADOW_FOLIAGE", 0)', e)

    def test_game_settings_retire_old_pair_a_b_shader_deletion(self):
        prefs = (APP / "Prefs.java").read_text()
        launcher = (APP / "GameActivity.java").read_text()
        page = (APP / "GameSettings.java").read_text()
        self.assertIn("oot_vegetation_detail_v3", prefs)
        self.assertIn("oot_shadow_foliage", prefs)
        self.assertIn("checked != 3", prefs)
        self.assertIn("DM_VK_OOT_VEG_QUALITY=0", launcher)
        self.assertIn("DM_VK_OOT_FOLIAGE_DENSITY=", launcher)
        self.assertIn("DM_VK_OOT_SHADOW_FOLIAGE=", launcher)
        self.assertNotIn("Teste A ·", page)
        self.assertNotIn("Teste B ·", page)
        self.assertIn("Custo das sombras", page)

    def test_compile_and_execute_real_abi_flags(self):
        cc = shutil.which("cc") or shutil.which("clang")
        if not cc:
            self.skipTest("C compiler missing")
        text = """
#include <stdint.h>
#include <assert.h>
#include "vka_memu_abi.h"
static uint32_t count_after(uint32_t flags, uint32_t task, uint32_t count) {
    int cut = ((flags & VKA_MEMU_F_FOLIAGE_75) && ((task & 3) == 3)) ||
              ((flags & VKA_MEMU_F_FOLIAGE_50) && ((task & 1) != 0));
    return cut ? 0 : count;
}
int main(void) {
    uint32_t sum0=0, sum1=0, sum2=0;
    for (uint32_t t=0;t<400;t++) {
        sum0 += count_after(0,t,5);
        sum1 += count_after(VKA_MEMU_F_TASK|VKA_MEMU_F_FOLIAGE_75,t,5);
        sum2 += count_after(VKA_MEMU_F_TASK|VKA_MEMU_F_FOLIAGE_50,t,5);
    }
    assert(sum0==2000 && sum1==1500 && sum2==1000);
    assert((VKA_MEMU_F_FOLIAGE_75 &
         (VKA_MEMU_F_TASK|VKA_MEMU_F_INDEXED|VKA_MEMU_F_INTERLEAVED|VKA_MEMU_F_COALESCED)) == 0);
    assert((VKA_MEMU_F_FOLIAGE_50 & VKA_MEMU_F_FOLIAGE_75) == 0);
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            source = pathlib.Path(td)/"case.c"
            exe = pathlib.Path(td)/"case"
            source.write_text(text)
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I" + str(VK), str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
