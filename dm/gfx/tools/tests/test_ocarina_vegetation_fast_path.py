"""Structural regression guards for Ocarina's vegetation-off GPU fast path.

These do not claim device FPS. They ensure the raster cut cannot regress into
a compute-only draw or a gratuitous render-pass split on future refactors.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


def function(source: str, name: str) -> str:
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", source, re.S)
    assert m, f"{name} not found"
    n = 1
    for i in range(m.end(), len(source)):
        n += (source[i] == "{") - (source[i] == "}")
        if not n:
            return source[m.start():i+1]
    raise AssertionError(f"{name} has no closing brace")


class VegetationGpuFastPath(unittest.TestCase):
    def setUp(self):
        self.draw = (VK / "vka_draw.c").read_text()
        self.exec = (VK / "vka_exec.c").read_text()
        self.memu = (VK / "vka_memu_draw.inc").read_text()

    def test_same_omittability_used_before_compute_and_at_raster(self):
        safe = function(self.draw, "vegetation_omittable")
        early = function(self.draw, "vka_vegetation_mesh_omit")
        raster = function(self.draw, "vegetation_cut")
        self.assertIn('DM_VK_VEGETATION', safe)
        self.assertIn('d->tf_on', safe)
        self.assertIn('vka_vegetation_key', safe)
        for unsafe in ('DMSH_VK_BF_RW', 'DMSH_VK_BF_ATOMIC',
                       'DMSH_VK_BF_NOSLOT', 'DMSH_VK_KIND_GMEM_LOG',
                       'DMSH_VK_KIND_UNKNOWN'):
            self.assertIn(unsafe, safe)
        for stage in ('6', '7', '1'):
            self.assertIn(f'&sh[{stage}]', early)
        self.assertIn('return vegetation_omittable(d, sh)', early)
        self.assertIn('vegetation_omittable(d, sh)', raster)

    def test_lookahead_checks_real_state_and_omits_before_batching(self):
        walk = function(self.exec, 'memu_walk')
        self.assertIn('phase >= 0 || vegetation_off', walk)
        self.assertIn('vka_state_op(&g_memu_st, h.op, a)', walk)
        omission = walk.index('vka_vegetation_mesh_omit(&g_memu_st)')
        self.assertLess(omission, walk.index('vka_memu_batch(phase'))
        self.assertIn('n++;', walk[omission:])
        before = function(self.exec, 'memu_before_draw')
        self.assertLess(before.index('vka_vegetation_mesh_omit(&S.d)'),
                        before.index('if (!vka_rp_is_open())'))
        self.assertLess(before.index('return;'),
                        before.index('vka_rp_end(); vka_memu_n_splits++'))

    def test_producer_barriers_kept_safe_with_rollback(self):
        phase_bar = function(self.memu, 'memu_phase_barrier')
        self.assertIn('DM_VK_MEMU_SCOPED_BAR', phase_bar)
        self.assertIn('vka_compute_write_barrier(g_cb)', phase_bar)
        self.assertIn('vka_barrier(g_cb)', phase_bar)
        batch = function(self.memu, 'vka_memu_batch')
        self.assertIn('case MEMU_SETUP: vka_barrier(g_cb); memu_helper(0); memu_phase_barrier();', batch)
        self.assertIn('case MEMU_DIST:', batch)
        self.assertIn('if (MB.task_draws) { memu_phase_barrier(); memu_helper(1); memu_phase_barrier(); }', batch)
        self.assertIn('case MEMU_END: memu_phase_barrier();', batch)
        self.assertIn('case MEMU_MESH:', batch)

    def test_taskless_batch_has_no_distribution_work_to_do(self):
        setup = (VK / "memu/memu_setup.comp").read_text()
        dist = (VK / "memu/memu_dist.comp").read_text()
        batch = function(self.memu, 'vka_memu_batch')
        self.assertIn('place(R, count);', setup)
        self.assertIn('VKA_MEMU_F_TASK', dist)
        self.assertIn('return;', dist)
        self.assertIn('MB.task_draws = 0', batch)
        self.assertIn('if (E->tcs) {', batch)
        self.assertIn('MB.task_draws++;', batch)
        self.assertIn('vka_memu_task_small++', batch)
        self.assertIn('if (MB.task_draws)', batch)


if __name__ == '__main__':
    unittest.main()
