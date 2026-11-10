"""A Vulkan pool slot is updated only when its view changes.

Independent storage and sampled bindings cannot reuse one another. In-flight
parts keep the original descriptor if the view and image generation are equal;
when an image is destroyed/replaced the generation forces a fresh write. This
does not change the shader library ABI or require recompilation.
"""
from pathlib import Path
import random
import unittest

ROOT = Path(__file__).resolve().parents[4]
SRC = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()


class SlotMemo:
    def __init__(self):
        self.slots = {}

    def write(self, id, kind, view, gen):
        k = (id, kind)
        if self.slots.get(k) == (view, gen):
            return False
        self.slots[k] = (view, gen)
        return True


class DescriptorDedupTests(unittest.TestCase):
    def test_source_contract(self):
        self.assertIn("static pool_written *g_pool_written;", SRC)
        self.assertIn("slot->view[kind] == view", SRC)
        self.assertIn("slot->gen[kind] == gen", SRC)
        self.assertIn('VKA_ENV("DM_VK_POOL_SLOT_DEDUP", 1)', SRC)
        self.assertIn("int kind = w[nw].dstBinding == 2 ? 1 : 0;", SRC)
        self.assertIn("if (!unchanged) {", SRC)
        self.assertIn("if (nw == BATCH) { vk.vkUpdateDescriptorSets", SRC)
        self.assertIn("free(g_pool_written); g_pool_written = NULL;", SRC)

    def test_sampler_and_storage_are_distinct_slots(self):
        m = SlotMemo()
        self.assertTrue(m.write(5, 0, 101, 4))
        self.assertFalse(m.write(5, 0, 101, 4))
        self.assertTrue(m.write(5, 1, 101, 4))
        self.assertTrue(m.write(5, 0, 102, 4))
        self.assertTrue(m.write(5, 0, 102, 5))
        self.assertTrue(m.write(5, 1, 101, 5))
        self.assertFalse(m.write(5, 0, 102, 5))

    def test_no_false_skip_with_random_registration_and_image_changes(self):
        rng = random.Random(20261110)
        memo = SlotMemo()
        states = {}
        for _ in range(30000):
            id = rng.randrange(1, 1024)
            kind = rng.randrange(2)
            gen = rng.randrange(1, 40)
            view = rng.randrange(1, 10000)
            key = (id, kind)
            expected = states.get(key) != (view, gen)
            self.assertEqual(memo.write(id, kind, view, gen), expected)
            states[key] = (view, gen)


if __name__ == "__main__":
    unittest.main()
