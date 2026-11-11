"""Conservative registered-pool framebuffer feedback refinement.

A dynamic texture-pool shader can sample any live registered ID, but only
an ID whose guest storage overlaps a current render attachment can create
feedback. Unknown address or extent stays conservative; cache invalidates
on texture registration and pass changes.
"""
from pathlib import Path
import random
import unittest

ROOT=Path(__file__).resolve().parents[4]
TEX=(ROOT/"dm/gfx/vk_android/vka_tex.c").read_text()
DRAW=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
HEADER=(ROOT/"dm/gfx/vk_android/vka.h").read_text()


def overlaps(attachments, registered):
    for base,size in attachments:
        if base is None or size is None or not size:
            return True
        for addr,length in registered:
            if addr is None or length is None or not length:
                return True
            if addr <= base and base-addr < length:
                return True
            if addr > base and addr-base < size:
                return True
    return False


class PoolFeedbackTests(unittest.TestCase):
    def test_source_contract(self):
        self.assertIn("int vka_tex_pool_in_pass(void)",HEADER)
        self.assertIn("int vka_tex_pool_in_pass(void) {",TEX)
        self.assertIn("g_wk.pool[st] && vka_tex_pool_in_pass()",DRAW)
        self.assertIn("atomic_fetch_add_explicit(&g_tpool_stamp, 1, memory_order_release);",TEX)
        self.assertIn("g_fb_stamp++;",TEX)
        self.assertIn("if (!e->t.mem || !e->t.L.size)",TEX)
        self.assertIn("if (!f || !f->mem || !f->L.size)",TEX)

    def test_false_only_if_no_possible_alias(self):
        self.assertFalse(overlaps([(0x1000,0x1000)],[(0x3000,0x1000)]))
        self.assertTrue(overlaps([(0x1000,0x1000)],[(0x1800,0x1000)]))
        self.assertTrue(overlaps([(0x1800,0x1000)],[(0x1000,0x1000)]))
        self.assertFalse(overlaps([(0x2000,0x1000)],[(0x1000,0x1000)]))
        self.assertTrue(overlaps([(0x1000,0x1000)],[(None,0x100)]))
        self.assertTrue(overlaps([(None,0x1000)],[(0x3000,0x1000)]))

    def test_random_intervals(self):
        rng=random.Random(5101)
        for _ in range(3000):
            att=[(rng.randrange(0,4000)*4096,rng.randrange(1,400)*4096)]
            reg=[(rng.randrange(0,4000)*4096,rng.randrange(1,400)*4096) for i in range(14)]
            lo,sz=att[0]
            expected=any(max(lo,addr)<min(lo+sz,addr+length) for addr,length in reg)
            self.assertEqual(overlaps(att,reg),expected)


if __name__=="__main__":
    unittest.main()
