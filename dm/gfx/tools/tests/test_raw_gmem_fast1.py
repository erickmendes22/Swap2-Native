#!/usr/bin/env python3
"""Synthetic memory-map equivalence for optional shader fast pool 1.
Not a GPU benchmark; no compiled shader library is required.
"""
import bisect
import random
import unittest

class GmemFast1Tests(unittest.TestCase):
    def test_full_range_and_fallback(self):
        r = random.Random(0xC0FFEE)
        for batch in range(300):
            at = r.randrange(1, 200) * 0x1000000
            pools = []
            for _ in range(r.randrange(3, 35)):
                at += r.randrange(1, 7) * 4096
                stop = at + r.randrange(1, 1000) * 4096
                pools.append((at, stop))
                at = stop
            if batch == 0:
                pools.append((0xFFFFFF000, 0x1000040000))
            pools.sort()
            starts = [x[0] for x in pools]
            for i in range(1000):
                address = (r.choice(pools)[0] + r.randrange(-0x10000, 0x10000)
                           if i % 2 else r.randrange(0, pools[-1][1] + 0x30000))
                j = bisect.bisect_right(starts, address) - 1
                expected = j if j >= 0 and address < pools[j][1] else None
                selected = 0 if pools[0][0] <= address < pools[0][1] else expected
                self.assertEqual(expected, selected)

if __name__ == '__main__':
    unittest.main()
