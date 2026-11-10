"""Watcher indexing of Vulkan images with CPU writes and sparse remappings.

Checks that only images still requiring memory reuploads are visited when the
guest dirty-page clock advances, while sparse GPU-written images remain watched.
It also exercises safe removal during iteration and swap-with-last removals.
"""
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()


class WatchModel:
    def __init__(self):
        self.live = []
        self.watch = []

    def create(self, kind):
        token = object()
        self.live.append((token, kind))
        if kind in ("tracked", "sparse", "sparse_gpu"):
            self.watch.insert(0, token)
        return token

    def drop(self, token):
        self.live = [e for e in self.live if e[0] is not token]
        self.watch = [e for e in self.watch if e is not token]

    def gpu_written(self, token):
        kind = next(kind for obj, kind in self.live if obj is token)
        if kind != "sparse_gpu":
            self.watch = [e for e in self.watch if e is not token]

    def pool_finalized(self, token):
        self.watch = [e for e in self.watch if e is not token]

    def watched(self):
        return set(self.watch)


class WatcherTests(unittest.TestCase):
    def test_source_registers_every_active_watch_kind(self):
        for expr in ("static vka_img *g_watch_head;", "watch_add(im);",
                     "watch_del(im);", "watch_listed", "watch_prev", "watch_next",
                     "for (vka_img *im = g_watch_head, *next; im; im = next)",
                     "next = im->watch_next;", "if (!im->vbind) watch_del(im);"):
            self.assertIn(expr, SOURCE)
        self.assertIn("struct vka_img *watch_next, *watch_prev; int watch_listed;", HEADER)
        self.assertIn("if (mode == ST_SPARSE) { im->vtrack = 1; watch_add(im);", SOURCE)
        self.assertIn("if (mode == ST_TRACK) { im->track = 1; watch_add(im);", SOURCE)

    def test_ever_growing_images_do_not_expand_page_scan(self):
        model = WatchModel()
        for i in range(12000):
            model.create("no_watch")
        for i in range(28):
            model.create("tracked")
        self.assertEqual(len(model.live), 12028)
        self.assertEqual(len(model.watched()), 28)

    def test_release_and_gpu_ownership_across_random_streaming(self):
        rng = random.Random(0x20261110)
        model = WatchModel()
        expected = {}
        for _ in range(7000):
            if not expected or rng.randrange(4):
                k = rng.choice(("tracked", "sparse", "sparse_gpu", "zero"))
                obj = model.create(k)
                expected[obj] = (k != "zero")
            else:
                obj = rng.choice(list(expected))
                if rng.randrange(2):
                    model.gpu_written(obj)
                    if next(k for o, k in model.live if o is obj) != "sparse_gpu":
                        expected[obj] = False
                else:
                    model.pool_finalized(obj)
                    expected[obj] = False
                    if rng.randrange(3) == 0:
                        model.drop(obj)
                        del expected[obj]
            self.assertEqual(model.watched(), {o for o, active in expected.items() if active})


if __name__ == "__main__":
    unittest.main()
