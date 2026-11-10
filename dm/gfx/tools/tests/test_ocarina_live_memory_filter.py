"""Regression model for vka_tex_get's conservative live-memory prefilter.

This is not a frame-rate benchmark. It checks that the filter never rejects
a texture address already present among live images, including collisions,
shared addresses, removals and re-use of previous addresses. The C code must
still execute same_shape in its original g_live order for possible aliases.
"""
import random
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
MASK64 = (1 << 64) - 1
N = 1 << 16

def slots(addr):
    x = addr & MASK64
    x ^= x >> 33
    x = x * 0xff51afd7ed558ccd & MASK64
    x ^= x >> 33
    x = x * 0xc4ceb9fe1a85ec53 & MASK64
    x ^= x >> 33
    return x & (N - 1), (x >> 16) & (N - 1)

class LiveMemoryFilter:
    def __init__(self):
        self.count = [0] * N
    def add(self, addr):
        if addr:
            a, b = slots(addr)
            self.count[a] += 1
            self.count[b] += 1
    def remove(self, addr):
        if addr:
            a, b = slots(addr)
            self.count[a] -= 1
            self.count[b] -= 1
            assert self.count[a] >= 0 and self.count[b] >= 0
    def possible(self, addr):
        if not addr:
            return False
        a, b = slots(addr)
        return self.count[a] != 0 and self.count[b] != 0

class LiveMemTests(unittest.TestCase):
    def test_source_contract(self):
        self.assertIn("static void live_mem_add(const void *p)", TEX)
        self.assertIn("static void live_mem_del(const void *p)", TEX)
        self.assertIn("static int live_mem_possible(const void *p)", TEX)
        self.assertIn("g_live[g_nlive++] = im;\n            live_mem_add(im->mem);", TEX)
        self.assertIn("if (g_live[i] == im) { live_mem_del(im->mem);", TEX)
        self.assertIn("if (live_mem_possible(t->mem))\n        for (int i = 0; i < g_nlive && !im; i++)", TEX)
        self.assertIn("same_shape(g_live[i], t, &f, 1)", TEX)
        self.assertNotIn("if (t->mem && same_shape(g_live[i]", TEX)

    def test_new_addresses_and_aliases(self):
        rng = random.Random(20261110)
        filt = LiveMemoryFilter()
        active = []
        for i in range(4000):
            addr = rng.randrange(1, 1 << 42) << 12
            active.append(addr)
            filt.add(addr)
        for _ in range(10000):
            addr = rng.choice(active)
            self.assertTrue(filt.possible(addr))
        # Multiple VkImages can have the same storage with different formats:
        # removal of one cannot make the others disappear from the filter.
        duplicate = active[333]
        for _ in range(50):
            filt.add(duplicate)
        for _ in range(50):
            filt.remove(duplicate)
            self.assertTrue(filt.possible(duplicate))
        for addr in active:
            filt.remove(addr)
        self.assertFalse(any(filt.count))

    def test_mutations_and_collision_are_conservative(self):
        rng = random.Random(3678)
        filt = LiveMemoryFilter()
        active = []
        for iteration in range(14000):
            if not active or rng.randrange(3):
                addr = (rng.randrange(2000) + 1) << 12
                active.append(addr)
                filt.add(addr)
            else:
                pos = rng.randrange(len(active))
                addr = active.pop(pos)
                filt.remove(addr)
            for addr in active[-12:]:
                self.assertTrue(filt.possible(addr))
        for addr in active:
            filt.remove(addr)
        self.assertFalse(any(filt.count))

    def test_original_alias_order_preserved(self):
        # A bloom hit falls through to an unchanged full-order scan,
        # including formats that can learn new image view compatibility.
        live = [(0x1000, "R8"), (0x1000, "R16"), (0x2000, "R16")]
        f = LiveMemoryFilter()
        for addr, _ in live:
            f.add(addr)
        def scan(mem, fmt):
            if not f.possible(mem):
                return None
            return next((i for i, entry in enumerate(live)
                         if entry == (mem, fmt)), None)
        self.assertEqual(scan(0x1000, "R16"), 1)
        self.assertEqual(scan(0x2000, "R16"), 2)
        self.assertIsNone(scan(0x3000, "R16"))
        self.assertIsNone(scan(0, "R8"))

if __name__ == "__main__":
    unittest.main()
