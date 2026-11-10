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
        if op != "compute" or (op == "compute_spill") or (op == "compute_indirect"):
            if pending:
                barriers += 1
                pending = False
        if op.startswith("compute"):
            can_defer = op == "compute" and n + 1 < len(ops) and ops[n + 1] == "compute"
            if can_defer:
                pending = True
            else:
                barriers += 1
                pending = False
    if pending:
        barriers += 1
    return barriers


class ComputeOverlap(unittest.TestCase):
    def test_source_defers_only_direct_consecutive_compute(self):
        self.assertIn('if (h.op != OP_DISPATCH) vka_dispatch_overlap_flush();', EXEC)
        self.assertIn('next.op == OP_DISPATCH && next.size >= 8', EXEC)
        self.assertIn('if (sb || dp->ind) vka_dispatch_overlap_flush();', DRAW)
        self.assertIn('next_is_dispatch && !sb && !dp->ind', DRAW)
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
        self.assertEqual(model(["compute", "compute", "barrier", "compute", "end"]), 2)
        self.assertEqual(model(["compute", "draw", "compute"]), 2)
        self.assertEqual(model(["compute", "compute_spill", "draw"]), 2)
        self.assertEqual(model(["compute", "compute_indirect", "draw"]), 2)

    def test_original_guarded_barriers_remain(self):
        self.assertIn('vka_compute_write_barrier(g_cb);', DRAW)
        self.assertIn('vka_barrier(g_cb); // the final dispatch publishes all grouped writes', DRAW)
        self.assertIn('case OP_BARRIER: if (g_cb && !bar_kept && !bar_covered) vka_barrier(g_cb);', EXEC)


if __name__ == "__main__":
    unittest.main()
