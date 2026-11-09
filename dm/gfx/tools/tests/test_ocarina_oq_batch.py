"""Occlusion result readback batching: no shaders compiled or modified.
This checks the query-index/ring math and preservation of report counts,
including reset boundaries, unavailable samples, cumulative reports and wrap.
"""
import random
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "dm/gfx/vk_android/vka_exec.c"

def baseline(events, results):
    # kind 4 = counted report; kind 5 = queries discarded after reset.
    cumulative = 0
    outputs = []
    for kind, fresh, lost, lo, hi in events:
        if kind == 4:
            total = lost + sum(results.get(q, (0, 0))[0] if results.get(q, (0, 0))[1]
                               else 1 for q in range(lo, hi))
            if fresh: cumulative = 0
            cumulative += total
            outputs.append(cumulative)
    return outputs

def readback_batch(events, results, limit=32768):
    ranges = [(lo,hi) for kind, fresh, lost, lo, hi in events
              if kind in (4,5) and hi>lo]
    if not ranges: return [], 0, 0
    first, last = min(a for a,b in ranges), max(b for a,b in ranges)
    if last - first > limit: raise ValueError("fallback required")
    parts = []
    q=first
    while q<last:
        k=min(last-q,limit-q%limit)
        parts.append((q,k))
        q+=k
    # Cached pairs indexed by the non-wrapped absolute sequence number.
    cached = {q: results.get(q,(0,0)) for q in range(first,last)}
    return baseline(events,cached),len(parts),last-first

class OcclusionBatchTests(unittest.TestCase):
    def test_source_invariant(self):
        src=SOURCE.read_text()
        for name in ("oq_prefetch(", "DM_VK_OQ_BATCH", "VK_QUERY_RESULT_WITH_AVAILABILITY_BIT",
                     "oq_done(&ops[i], ticks, &batch)", "free(batch.pairs)",
                     "readback %.1f get + %.1f reset calls/frame",
                     "atomic_fetch_add_explicit(&g_oq_reset_calls",
                     "if (batch.pairs && OQ.host)"):
            self.assertIn(name,src)
    def test_randomized_reports(self):
        rng=random.Random(0xAB911)
        for _ in range(75):
            first=rng.randrange(1,100000)
            seq=first
            results={}
            events=[]
            for i in range(rng.randrange(5,75)):
                k=rng.randrange(0,14)
                for q in range(seq,seq+k):
                    results[q]=(rng.randrange(0,65536),rng.randrange(0,2))
                kind=5 if rng.randrange(8)==0 else 4
                events.append((kind,int(i==0 or rng.randrange(30)==0),rng.randrange(0,3),seq,seq+k))
                seq+=k
            expected=baseline(events,results)
            actual,calls,n=readback_batch(events,results)
            self.assertEqual(actual,expected)
            if n:
                self.assertLessEqual(calls,2)
    def test_wrap_and_unavailable(self):
        events=[(4,1,0,32766,32768),(4,0,1,32768,32771),(5,0,0,32771,32774)]
        results={32766:(30,1),32767:(0,0),32768:(50,1),32769:(9999,0),32770:(2,1)}
        actual,calls,n=readback_batch(events,results)
        self.assertEqual(actual,[31,85])
        self.assertEqual(calls,2)
        self.assertEqual(n,8)
    def test_no_reports(self):
        self.assertEqual(readback_batch([],{}),([],0,0))

if __name__=="__main__": unittest.main()
