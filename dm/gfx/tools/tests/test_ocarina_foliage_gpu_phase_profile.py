"""Guard low-frequency GPU phase attribution for Ocarina foliage.

Diagnostic timestamps must only exist on explicitly sampled frames; the
ordinary renderer stays unchanged at 720p. A subsequent heavy-scene log
will show whether compute mesh, setup, barriers or raster takes the time.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


class FoliagePhaseProfile(unittest.TestCase):
    def test_lookahead_profiling_follows_real_work_order(self):
        s = (VK / "vka_exec.c").read_text()
        st = s.index("static void memu_scan(const uint8_t *p)")
        en = s.index("static void memu_before_draw", st)
        walk = s[st:en]
        stages = [
            ('"MEMU_START"', 'vka_memu_batch(MEMU_BEGIN'),
            ('"MEMU_ADD"', 'vka_memu_batch(MEMU_SETUP'),
            ('"MEMU_SETUP"', 'memu_walk(p, MEMU_TASK)'),
            ('"MEMU_TASK"', 'vka_memu_batch(MEMU_DIST'),
            ('"MEMU_DIST"', 'memu_walk(p, MEMU_MESH)'),
            ('"MEMU_MESH"', 'vka_memu_batch(MEMU_END'),
            ('"MEMU_END"', None),
        ]
        for marker, following in stages:
            self.assertIn(f'if (vka_gp_active) vka_gp_mark(g_cb, {marker}, 0);', walk)
            if following:
                self.assertLess(walk.index(marker), walk.index(following))
        self.assertLess(walk.index('memu_walk(p, MEMU_MESH)'), walk.index('"MEMU_MESH"'))
        self.assertLess(walk.index('vka_memu_batch(MEMU_END'), walk.index('"MEMU_END"'))

    def test_trace_is_sparse_and_disabled_without_foliage(self):
        s = (VK / "vka_gprof.c").read_text()
        self.assertIn('int every = VKA_ENV("DM_VK_GPUPROF",', s)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', s)
        self.assertIn('VKA_ENV("DM_VK_VEGETATION", 1) ? 300 : 0', s)
        self.assertIn('VLOG("gpu prof foliage phases:', s)
        for phase in ('MEMU_START','MEMU_ADD','MEMU_SETUP','MEMU_TASK','MEMU_DIST','MEMU_MESH','MEMU_END'):
            self.assertIn(f'"{phase}"',s)
        self.assertIn('vka_gp_active',s)
        self.assertIn('DM_VK_GPUPROF=0',s)

    def test_mesh_key_attribution_uses_original_shader_not_generated_xor_key(self):
        m = (VK / "vka_memu_draw.inc").read_text()
        g = (VK / "vka_gprof.c").read_text()
        h = (VK / "vka.h").read_text()
        self.assertIn('uint64_t original_key) {',m)
        self.assertIn('if (vka_gp_active) vka_gp_mesh_shader(g_cb, st == 6, original_key);',m)
        self.assertIn('MB.e[idx].ms ? MB.e[idx].ms->key : 0',m)
        self.assertIn('MB.e[idx].ts ? MB.e[idx].ts->key : 0',m)
        self.assertIn('void vka_gp_mesh_shader(VkCommandBuffer cb, int task, uint64_t key)',g)
        self.assertIn('void vka_gp_mesh_shader(VkCommandBuffer cb, int task, uint64_t key);',h)
        self.assertIn('m->mesh_key = 0; m->mesh_stage = 0;',g)
        self.assertIn('m->mesh_key = key;',g)
        self.assertIn('m->mesh_stage = task ? 1 : 2;',g)
        self.assertIn('gpu prof foliage key:',g)
        self.assertIn('MEMU_MESH_SHADER',g)
        self.assertIn('MEMU_TASK_SHADER',g)
        # Reporting must aggregate timestamps, not CPU time.
        self.assertIn('hot[j].ms += s[k].ms;',g)
        self.assertIn('int phase = m->mesh_stage == 1 ? 3 : 5;',g)
        self.assertIn('mesh_phase_ms[phase] += s[j].ms;',g)
        self.assertIn('rank < 12',g)
        self.assertIn('if (!vka_gp_active || cb != g_cb || g_n >= NQ) return;',g)

    def test_no_spirv_abi_or_render_scale_regression(self):
        shader = (VK / "vka_memu_spv.c").read_text()
        dev = (VK / "vka_dev.c").read_text()
        self.assertIn('DM_VK_MEMU_FAST_TASKLESS',shader)
        self.assertIn('qcom_ocarina',dev)
        self.assertIn('hybrid original-native/supplement-compute',dev)


if __name__ == '__main__':
    unittest.main()
