"""Vulkan backport of iOS compute-dispatch overlap: synchronization contract.

A compute group may defer a full Vulkan barrier only across directly adjacent
NVN compute dispatches with no guest barrier, host spill, indirect arguments,
GPU instrumentation, or other command. This tests the source-level guards and
the boundary model without needing a phone or game shader rebuild.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()
UI = (ROOT / "android/app/src/main/java/dev/nxnative/android/GraphicsOptions.java").read_text()


def model(ops):
    """A host-dispatch overlap model; count barriers and non-compute boundaries."""
    pending = False
    barriers = 0
    for n, op in enumerate(ops):
        if op not in ("compute", "bind", "state"):
            if pending:
                barriers += 1
                pending = False
        if op.startswith("compute"):
            if op == "compute":
                pending = True
            else:
                barriers += 1
                pending = False
    if pending:
        barriers += 1
    return barriers


class ComputeOverlap(unittest.TestCase):
    def test_source_defers_only_direct_consecutive_compute(self):
        self.assertIn('if (h.op != OP_DISPATCH && !overlap_state_record(h.op)) vka_dispatch_overlap_flush();', EXEC)
        self.assertIn('static int overlap_state_record(uint32_t op)', EXEC)
        self.assertIn('case OP_BIND_UBO:', EXEC)
        self.assertIn('case OP_PUSH_CONST:', EXEC)
        self.assertIn('if (sb || dp->ind) vka_dispatch_overlap_flush();', DRAW)
        self.assertIn('if (!sb && !dp->ind', DRAW)
        self.assertIn('!vka_gp_active && !vka_nan_on()', DRAW)
        self.assertIn('g_dispatch_overlap_pending = 1;', DRAW)
        self.assertIn('g_dispatch_overlap_skipped++;', DRAW)
        self.assertIn('vka_dispatch_overlap_flush(void)', DRAW)
        self.assertIn('vka_draw_cb_switch(VkCommandBuffer cb) { vka_dispatch_overlap_flush();', DRAW)
        self.assertIn('void vka_dispatch_overlap_flush(void);', HEADER)

    def test_only_ocarina_enables_it_by_default(self):
        self.assertIn('if (Prefs.OCARINA_TITLE.equals(id)) {', UI)
        self.assertIn('out.add("DM_VK_OOT_DISPATCH_OVERLAP=1");', UI)
        self.assertIn('VKA_ENV("DM_VK_OOT_DISPATCH_OVERLAP", 0)', DRAW)

    def test_barriers_stay_at_boundaries(self):
        # All non-compute NVN operations (including explicit barriers, calls,
        # jumps, reports, and draws) flush the previous compute group.
        self.assertEqual(model(["compute", "compute", "compute", "draw"]), 1)
        self.assertEqual(model(["compute", "bind", "compute", "state", "compute", "draw"]), 1)
        self.assertEqual(model(["compute", "compute", "barrier", "compute", "end"]), 2)
        self.assertEqual(model(["compute", "draw", "compute"]), 2)
        self.assertEqual(model(["compute", "compute_spill", "draw"]), 2)
        self.assertEqual(model(["compute", "compute_indirect", "draw"]), 2)

    def test_zero_grid_dispatch_is_real_noop_not_a_redundant_gpu_barrier(self):
        # Build53 GPU timestamps repeatedly marked compute shaders
        # 510c344f..., e855420a..., cee08c63... at grid 0x0x0,
        # although the dispatch code did not issue vkCmdDispatch.
        # Return BEFORE pipeline creation, descriptor walks and GPU barrier;
        # keep pass-ending, guest dispatch constants, and explicit barrier.
        method = DRAW[DRAW.index('void vka_dispatch(vka_dstate *d, const p_dispatch *dp) {'):]
        zero = method.index('if (!dp->ind && (dp->x <= 0 || dp->y <= 0 || dp->z <= 0)')
        lookup = method.index('vka_shader *sh[VKA_NSTAGE]')
        self.assertLess(zero, lookup)
        self.assertIn('vka_rp_end();', method[:zero])
        self.assertIn('d->b.dispatch[0] = (uint32_t)dp->x;', method[zero:lookup])
        self.assertIn('d->b.dispatch[1] = (uint32_t)dp->y;', method[zero:lookup])
        self.assertIn('d->b.dispatch[2] = (uint32_t)dp->z;', method[zero:lookup])
        self.assertIn('vka_dispatch_overlap_flush();', method[zero:lookup])
        self.assertIn('!vka_gp_active', method[zero:lookup])
        self.assertIn('DM_VK_OOT_ZERO_DISPATCH", 1', method[zero:lookup])
        self.assertIn('case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);', EXEC)
        self.assertIn('if (dp->ind) vk.vkCmdDispatchIndirect(g_cb, ib, io);', DRAW)

    def test_profiled_9e6b_retile_does_not_require_quality_reducing_vrs(self):
        # Profiled 9e6b at ~0.5-1.4ms. The safe SPIR-V patcher refuses
        # subgroup/workgroup/local indexing and preserves each global ID.
        start = DRAW.index('if (!p && sh[5]->key == UINT64_C(0x9e6b00b050e30801)')
        end = DRAW.index('if (!p) p = rt.b[0]', start)
        mode = DRAW[start:end]
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', mode)
        self.assertIn('VKA_ENV("DM_VK_OOT_CS_RETILE", 1)', mode)
        self.assertNotIn('DM_VK_OOT_FPS_BOOST', mode)
        self.assertIn('!rt.b[0] && !dp->ind && !spill_bytes(sh[5])', mode)
        self.assertIn('dp->x == 8 && dp->y == 9 && dp->z == 12', mode)
        self.assertIn('maxComputeWorkGroupCount[2] >= 24', mode)
        self.assertIn('vka_cs_pipeline_oot_retile(', mode)
        self.assertIn('if (!p) p = rt.b[0]', DRAW[end:])

    def test_original_guarded_barriers_remain(self):
        self.assertIn('vka_compute_write_barrier(g_cb);', DRAW)
        self.assertIn('vka_barrier(g_cb); // the final dispatch publishes all grouped writes', DRAW)
        self.assertIn('case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);', EXEC)


if __name__ == "__main__":
    unittest.main()
