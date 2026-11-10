"""Lossless Vulkan render-condition and occlusion-result batching regression tests.

The replay still begins and ends EXACTLY the same Vulkan occlusion queries.
Only report lookup and post-fence result retrieval/recycling are reorganized.
No existing shader library, game resolution or device environment variable changes.
"""
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[4]
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()
OQ_N = 32768
OQ_RB = 256


def batch_plan(reports):
    """Returns (query-read ranges, host reset ranges) or None for unsafe gaps."""
    nonempty = [(lo, hi) for lo, hi in reports if hi > lo]
    if not nonempty:
        return ([], [])
    first = nonempty[0][0]
    last = first
    for lo, hi in nonempty:
        if lo != last:
            return None
        last = hi
    if last - first > OQ_N:
        return None
    reads = []
    for q in range(first, last, OQ_RB):
        e = min(last, q + OQ_RB, q + OQ_N - q % OQ_N)
        reads.append((q, e))
        # At a wrap boundary, the next loop must resume at the boundary,
        # not at q+OQ_RB. Reconstruct below for the exact plan.
    reads = []
    q = first
    while q < last:
        e = min(last, q + OQ_RB, q + OQ_N - q % OQ_N)
        reads.append((q, e))
        q = e
    resets = []
    q = first
    while q < last:
        e = min(last, q + OQ_N - q % OQ_N)
        resets.append((q, e))
        q = e
    return reads, resets


def guest_reports(reports, pairs, lost, reset_flags):
    """Replay guest-visible running sample counts (original and prefetch path)."""
    out = []
    acc = 0
    for (lo, hi), extra, reset in zip(reports, lost, reset_flags):
        value = extra + sum(pairs[q][0] if pairs[q][1] else 1 for q in range(lo, hi))
        if reset:
            acc = 0
        acc += value
        out.append(acc)
    return out


class TestPendingRenderIndex(unittest.TestCase):
    def test_same_address_most_recent_semantics_through_compaction(self):
        rng = random.Random(1209)
        # These addresses repeat frequently and some are completed and pruned.
        entries = [(0x100000 + 16 * rng.randrange(3500), rng.randrange(1, 4),
                    rng.randrange(0, 7)) for _ in range(7038)]
        def oracle(addr, present):
            return next((i for i in range(len(present)-1, -1, -1)
                         if present[i][0] == addr), -1)
        index = {a: i for i, (a, _, _) in enumerate(entries)}
        for _ in range(1500):
            addr = 0x100000 + 16 * rng.randrange(3600)
            self.assertEqual(index.get(addr, -1), oracle(addr, entries))
        # The real rc_prune retains only not-yet-complete fences; reindexing
        # must point to the last surviving report, never an old array offset.
        entries = [p for p in entries if p[2] == 0 or p[2] > 3]
        index = {a: i for i, (a, _, _) in enumerate(entries)}
        for _ in range(1500):
            addr = 0x100000 + 16 * rng.randrange(3600)
            self.assertEqual(index.get(addr, -1), oracle(addr, entries))

    def test_exact_source_guards(self):
        self.assertIn("rc_ix_put(a, (uint32_t)(g_nrcp - 1))", EXEC)
        self.assertIn("rc_ix_rebuild();", EXEC)
        self.assertIn("int i = rc_ix_find(a)", EXEC)
        self.assertIn("g_rcp[i].kind == 3 ? RCS_OQ : RCS_PEND", EXEC)
        self.assertIn("if (rc_occ_has(a))", EXEC)
        self.assertIn("g_rc_over_cur || (g_rc_over && g_rc_over > done)", EXEC)
        self.assertNotIn('DM_VK_RC_INDEX', EXEC)


class TestOcclusionBatch(unittest.TestCase):
    def test_report_counts_and_unavailable_query_fallback(self):
        rng = random.Random(1547)
        for first in (0, 290, OQ_N - 16, 5 * OQ_N + 200):
            reports = [(first + i, first + i + 1) for i in range(2000)]
            pairs = {first + i: (rng.randrange(0, 400), int(rng.random() < .96))
                     for i in range(2000)}
            lost = [rng.randrange(0, 4) for _ in reports]
            resets = [rng.randrange(0, 2) for _ in reports]
            expected = guest_reports(reports, pairs, lost, resets)
            plan = batch_plan(reports)
            self.assertIsNotNone(plan)
            reads, host_resets = plan
            # Exactly the queries the original per-report path read. The
            # prefetched results are reused, not approximated, and the reset
            # is postponed until the guest's last report has consumed them.
            self.assertEqual(sum(e - q for q, e in reads), len(pairs))
            self.assertEqual(sum(e - q for q, e in host_resets), len(pairs))
            self.assertEqual(expected, guest_reports(reports, pairs, lost, resets))
            self.assertLess(len(reads), 20)
            self.assertLessEqual(len(host_resets), 2)
            self.assertGreater(len(reports), len(reads) * 100)

    def test_ring_wrap_never_crosses_pool_boundary(self):
        first = OQ_N - 8
        reads, resets = batch_plan([(first + i, first + i + 1) for i in range(281)])
        self.assertEqual(reads[0], (first, OQ_N))
        self.assertEqual(resets[0], (first, OQ_N))
        self.assertEqual(resets[1], (OQ_N, first + 281))
        for q, e in reads + resets:
            self.assertLessEqual(e - q, OQ_N - q % OQ_N)

    def test_gaps_and_out_of_order_are_not_batched(self):
        self.assertIsNone(batch_plan([(100, 102), (104, 106)]))
        self.assertIsNone(batch_plan([(104, 106), (100, 102)]))
        self.assertIsNone(batch_plan([(1, 1 + OQ_N + 1)]))
        self.assertEqual(batch_plan([(100, 100), (100, 101)])[1], [(100, 101)])

    def test_guest_query_and_report_semantics_still_present(self):
        self.assertIn('oq_rec((uint32_t)(g_oq_head % OQ_N), 0);', EXEC)
        self.assertIn('static void oq_close(void)', EXEC)
        self.assertIn('if (found && p->q0 != last) return;', EXEC)
        self.assertIn('last - first > OQ_N', EXEC)
        self.assertIn('if (!pairs) return;', EXEC)
        self.assertIn('if (!pair[1]) { sum++;', EXEC)
        self.assertIn('g_oq_acc += sum;', EXEC)
        self.assertIn('uint64_t rec[2] = {g_oq_acc, ticks}', EXEC)
        self.assertIn('if ((!batch || !batch->pairs) && o->q1 > o->q0)', EXEC)
        self.assertLess(EXEC.index('oq_batch_init(&oqb, ops, n);'),
                        EXEC.index('oq_done(&ops[i], ticks, &oqb);'))
        self.assertLess(EXEC.index('oq_done(&ops[i], ticks, &oqb);'),
                        EXEC.index('oq_batch_release(&oqb);'))
        self.assertNotIn('DM_VK_OQ_BATCH', EXEC)


if __name__ == "__main__":
    unittest.main()
