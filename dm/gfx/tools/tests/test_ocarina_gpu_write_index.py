"""Sorted GPU write-to-texture overlap cache survives steady-state updates.

With many active guest writes per frame, the old code rebuilt and sorted every
live image on every submission. The new cache builds when image membership
changes. Only images still alive and GPU-unowned are uploaded after a write.
"""
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[4]
SRC = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()


class Index:
    def __init__(self):
        self.live = []
        self.gen = 1
        self.cached_gen = 0
        self.cache = []
        self.sorts = 0

    def add(self, start, size):
        obj = [start, size, False]
        self.live.append(obj)
        self.gen += 1
        return obj

    def drop(self, obj):
        self.live.remove(obj)
        self.gen += 1

    def writes(self, start, end):
        if self.cached_gen != self.gen:
            self.cache = sorted(self.live, key=lambda x: x[0])
            self.cached_gen = self.gen
            self.sorts += 1
        return [x for x in self.cache if x[0] < end and start < x[0] + x[1] and not x[2]]


class WriteIndexTests(unittest.TestCase):
    def test_source_contract(self):
        self.assertIn("static uint64_t g_live_generation = 1;", SRC)
        self.assertIn("static uint64_t maxsz, sorted_generation;", SRC)
        self.assertIn("if (any && sorted_generation != g_live_generation)", SRC)
        self.assertIn("sorted_generation = g_live_generation;", SRC)
        self.assertIn("if (sorted_generation != g_live_generation) {", SRC)
        self.assertIn("img_pool_dead(im)) continue;", SRC)
        self.assertGreaterEqual(SRC.count("g_live_generation++;"), 2)

    def test_repeated_writes_avoid_resorts(self):
        rng = random.Random(2143)
        index = Index()
        for i in range(3000):
            index.add(4096 * (i + 1), 8192)
        for _ in range(400):
            a = rng.randrange(1, 3000) * 4096
            index.writes(a, a + 8192)
        self.assertEqual(index.sorts, 1)

    def test_always_same_as_exhaustive_scan(self):
        rng = random.Random(20261110)
        index = Index()
        for i in range(3000):
            if index.live and i % 23 == 0:
                index.drop(rng.choice(index.live))
            else:
                index.add(rng.randrange(1, 10000) * 4096, rng.randrange(1, 128) * 4096)
            if index.live and i % 9 == 0:
                rng.choice(index.live)[2] = True
            a = rng.randrange(1, 10000) * 4096
            b = a + rng.randrange(1, 100) * 4096
            expected = {id(x) for x in index.live if x[0] < b and a < x[0] + x[1] and not x[2]}
            self.assertEqual(expected, {id(x) for x in index.writes(a, b)})


if __name__ == "__main__":
    unittest.main()
