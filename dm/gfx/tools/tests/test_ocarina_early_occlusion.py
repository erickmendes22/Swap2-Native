"""No-wait in-flight Vulkan occlusion pair evaluation.

Each same-reset-epoch query contributes a nonnegative count; intermediate
query results determine cumulative equality even when the command buffer
fence has not landed. None of the tests permits a speculative skip if ANY
required query is unavailable. Out-of-epoch reports are not compared early.
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

if __name__=="__main__": unittest.main()
