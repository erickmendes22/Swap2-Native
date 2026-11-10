"""Exact-storage Vulkan texture index: preserve the full-scan alias semantics.

The old counting filter still linearly inspected every live image after a
positive hit. Bucket chains now give near-constant access for sparse aliases
and keep g_live order even after swap-with-last removal. This model checks
selection against the original full scan under collisions and mutations.
"""
import random
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()
MASK64 = (1 << 64) - 1
N = 1 << 15


def slot(addr):
    x = addr & MASK64
    x ^= x >> 33
    x = x * 0xff51afd7ed558ccd & MASK64
    x ^= x >> 33
    x = x * 0xc4ceb9fe1a85ec53 & MASK64
    x ^= x >> 33
    return x & (N - 1)


class LiveImageIndex:
    def __init__(self):
        self.live = []
        self.buckets = {}

    def add(self, addr, fmt):
        ident = len(self.live) + self.buckets.setdefault("_sequence", 0)
        self.buckets["_sequence"] += 1
        entry = (ident, addr, fmt)
        self.live.append(entry)
        self.buckets.setdefault(slot(addr), []).append(entry)
        return ident

    def remove(self, ident):
        at = next(i for i, e in enumerate(self.live) if e[0] == ident)
        old = self.live[at]
        self.live[at] = self.live[-1]
        self.live.pop()
        self.buckets[slot(old[1])].remove(old)
        # The C implementation unlinks the moved entry and reinserts it by
        # its new g_live index. Sort by current index to model that operation.
        for k, bucket in self.buckets.items():
            if isinstance(k, int):
                bucket.sort(key=self.live.index)

    def scan_old(self, addr, fmt):
        return next((e[0] for e in self.live if e[1] == addr and e[2] == fmt), None)

    def scan_new(self, addr, fmt):
        return next((e[0] for e in self.buckets.get(slot(addr), ())
                     if e[1] == addr and e[2] == fmt), None)


class LiveMemTests(unittest.TestCase):
    def test_source_contract(self):
        self.assertIn("static vka_img *g_live_mem[LIVE_MEM_N];", TEX)
        self.assertIn("static void live_mem_add(vka_img *im)", TEX)
        self.assertIn("static void live_mem_del(vka_img *im)", TEX)
        self.assertIn("static vka_img *live_mem_first(const void *p)", TEX)
        self.assertIn("while (at && at->live_index < im->live_index)", TEX)
        self.assertIn("candidate->mem == t->mem && same_shape(candidate, t, &f, 1)", TEX)
        self.assertIn("im->live_index = g_nlive;", TEX)
        self.assertIn("g_live[i] = moved;", TEX)
        self.assertIn("moved->live_index = i;", TEX)
        self.assertIn("live_mem_del(moved);", TEX)
        self.assertIn("struct vka_img *mem_next, *mem_prev; int live_index;", HEADER)
        self.assertNotIn("live_mem_possible", TEX)

    def test_collision_aliases_and_swap_deletion_match_old_scan(self):
        rng = random.Random(20261110)
        index = LiveImageIndex()
        ids = []
        # Smaller repeated-address population plus many distinct addresses.
        for step in range(1500):
            if ids and rng.randrange(5) == 0:
                ident = ids.pop(rng.randrange(len(ids)))
                index.remove(ident)
            else:
                addr = (rng.randrange(1, 450) << 12) if rng.randrange(3) else (rng.randrange(1, 1 << 40) << 12)
                ids.append(index.add(addr, rng.randrange(5)))
            for _ in range(5):
                if index.live and rng.randrange(3):
                    addr = rng.choice(index.live)[1]
                else:
                    addr = rng.randrange(1, 1 << 40) << 12
                fmt = rng.randrange(5)
                self.assertEqual(index.scan_old(addr, fmt), index.scan_new(addr, fmt))

    def test_old_order_with_shared_storage(self):
        idx = LiveImageIndex()
        a = idx.add(0x1000, 1)
        b = idx.add(0x1000, 1)
        c = idx.add(0x2000, 4)
        self.assertEqual(idx.scan_new(0x1000, 1), a)
        idx.remove(a)
        self.assertEqual(idx.scan_new(0x1000, 1), b)
        idx.add(0x2000, 4)
        idx.remove(c)
        self.assertEqual(idx.scan_new(0x2000, 4), idx.scan_old(0x2000, 4))


if __name__ == "__main__":
    unittest.main()
