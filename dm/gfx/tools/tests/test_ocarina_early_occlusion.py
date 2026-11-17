"""No-wait in-flight Vulkan occlusion pair evaluation.

Each same-reset-epoch query contributes a nonnegative count; intermediate
query results determine cumulative equality even when the command buffer
fence has not landed. None of the tests permits a speculative skip if ANY
required query is unavailable. Different reset epochs are comparable only when each report is independently fresh\nand at least one result is provably zero. Ambiguous positive pairs draw.
"""
import random
import unittest
from pathlib import Path

SRC=(Path(__file__).resolve().parents[4]/"dm/gfx/vk_android/vka_exec.c").read_text()

def early_equality(counts,first,second,lost,available,same_epoch=True):
    if not same_epoch: return None
    if lost[first]!=lost[second]: return False
    q0,q1=sorted((first,second))
    if any(not available[i] for i in range(q0,q1)): return None
    return not any(counts[q0:q1])

class EarlyOcclusionTests(unittest.TestCase):
    def test_source_requires_gpu_availability_no_wait_and_fence_safe(self):
        self.assertIn('DM_VK_OOT_EARLY_OCCLUSION", 1',SRC)
        self.assertIn('static int oq_early_pair_equal(',SRC)
        self.assertIn('a.oq_epoch != b.oq_epoch',SRC)
        self.assertIn('VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WITH_AVAILABILITY_BIT',SRC)
        self.assertIn('if (!pairs[2 * i + 1])',SRC)
        self.assertIn('if (q0 < returned)',SRC)
        self.assertIn('pthread_mutex_lock(&g_oq_mu);',SRC)
        self.assertIn('if (!all_available)',SRC)
        self.assertIn('rc_oq_early_eq' if False else 'oq_early_pair_equal(rc->addr, rc->addr + 16, &early_equal)',SRC)
        self.assertNotIn('VK_QUERY_RESULT_WAIT_BIT',SRC)

    def test_all_early_decisions_agree_with_cumulative_counts(self):
        rng=random.Random(209)
        for _ in range(15000):
            n=rng.randrange(1,130)
            counts=[rng.randrange(0,150) for i in range(n)]
            lost=[0]
            for i in range(n):
                lost.append(lost[-1]+(rng.randrange(7)==0))
            all_counts=[0]
            for i,x in enumerate(counts):
                all_counts.append(all_counts[-1]+x+lost[i+1]-lost[i])
            a,b=sorted(rng.sample(range(n+1),2))
            available=[rng.randrange(8)!=0 for i in range(n)]
            got=early_equality(counts,a,b,lost,available)
            if got is not None:
                self.assertEqual(got,all_counts[a]==all_counts[b])
            if not all(available[a:b]) and lost[a]==lost[b]:
                self.assertIsNone(got)

    def test_within_same_reset_only(self):
        counts=[0,0,12,0,0]
        lost=[0]*6
        self.assertIsNone(early_equality(counts,0,4,lost,[True]*5,False))
        self.assertFalse(early_equality(counts,1,4,lost,[True]*5))
        self.assertTrue(early_equality(counts,3,5,lost,[True]*5))
        self.assertIsNone(early_equality(counts,1,4,lost,[True,False,True,True,True]))


def fresh_zero(values, available, lost):
    # Match the C helper: lost or any AVAILABLE positive query proves nonzero.
    if lost or any(v > 0 and a for v, a in zip(values, available)): return False
    if not all(available): return None
    return True

def cross_reset_equality(a, aa, al, b, ba, bl):
    za, zb = fresh_zero(a, aa, al), fresh_zero(b, ba, bl)
    if za is None or zb is None: return None
    if za is False and zb is False: return None
    return za == zb

class CrossResetEarlyOcclusionTests(unittest.TestCase):
    def test_source_is_conservative_and_bounded(self):
        self.assertIn('DM_VK_OOT_CROSS_EPOCH_EARLY", 1', SRC)
        self.assertIn('if (a.oq_epoch != b.oq_epoch)', SRC)
        self.assertIn('!a.oq_fresh || !b.oq_fresh', SRC)
        self.assertIn('!a.fence && a.oq_end > a.oq_begin && !a.oq_lost', SRC)
        self.assertIn('!b.fence && b.oq_end > b.oq_begin && !b.oq_lost', SRC)
        self.assertIn('if (g_oq_cross_budget >= 96)', SRC)
        self.assertIn('oq_early_fresh_zero_locked', SRC)
        self.assertIn('if (r->oq_begin < returned) return 0;', SRC)
        self.assertIn('if (unavailable) return 0;', SRC)
        self.assertIn('if (!az && !bz)', SRC)
        self.assertIn('pthread_mutex_lock(&g_oq_mu);', SRC)
        self.assertNotIn('VK_QUERY_RESULT_WAIT_BIT', SRC)

    def test_cross_epoch_zero_and_positive_only_100000_cases(self):
        rng = random.Random(20261117)
        proved = 0
        for _ in range(100000):
            na, nb = rng.randrange(4), rng.randrange(4)
            a = [rng.randrange(7) for _ in range(na)]
            b = [rng.randrange(7) for _ in range(nb)]
            aa = [rng.randrange(4) != 0 for _ in range(na)]
            ba = [rng.randrange(4) != 0 for _ in range(nb)]
            al, bl = rng.randrange(3), rng.randrange(3)
            out = cross_reset_equality(a, aa, al, b, ba, bl)
            exact = sum(a) + al == sum(b) + bl
            if out is not None:
                proved += 1
                self.assertEqual(out, exact, (a, aa, al, b, ba, bl))
            if sum(a) + al > 0 and sum(b) + bl > 0:
                self.assertIsNone(out)
        self.assertGreater(proved, 1000)

    def test_missing_availability_still_permits_positive_proof(self):
        self.assertFalse(fresh_zero([3, 0], [True, False], 0))
        self.assertIsNone(fresh_zero([0, 0], [True, False], 0))
        self.assertTrue(cross_reset_equality([], [], 0, [0], [True], 0))
        self.assertFalse(cross_reset_equality([], [], 0, [1], [True], 0))
        self.assertIsNone(cross_reset_equality([1], [True], 0, [1], [True], 0))

if __name__=="__main__": unittest.main()
