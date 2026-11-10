"""Ocarina GPU barrier scopes: source contracts for preserving memory ordering.

Original 0.1.2 runs hundreds of full ALL_COMMANDS dependencies per frame.
These checks verify that only known producer classes are narrowed, and every
consumer stays in ALL_COMMANDS with read+write access. They do not claim FPS.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()
TEX = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
EXEC = (ROOT / "dm/gfx/vk_android/vka_exec.c").read_text()


def source_body(src, name, end_marker):
    a = src.index(name)
    b = src.index(end_marker, a + len(name))
    return src[a:b]


class BarrierScopeTests(unittest.TestCase):
    def test_shader_store_pass_full_fallback(self):
        body = source_body(DRAW, 'void vka_rp_end(void) {',
                           '// OP_BARRIER used to end a render pass')
        self.assertIn('g_rp_force_full || R.bar_pending || had_clears || vka_nan_on()', body)
        self.assertIn('if (full) { g_rp_full++; vka_barrier(g_cb); }', body)
        self.assertIn('else if (R.swrite) { g_rp_graphics++; vka_graphics_write_barrier(g_cb); }', body)
        self.assertIn('else { g_rp_scoped++; vka_attachment_write_barrier(g_cb); }', body)

    def test_graphics_shader_writes_have_complete_destination(self):
        body = source_body(TEX, 'void vka_graphics_write_barrier_at(',
                           '// A compute dispatch can write')
        self.assertIn('VK_ACCESS_MEMORY_WRITE_BIT', body)
        self.assertIn('VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT', body)
        self.assertIn('VK_PIPELINE_STAGE_ALL_GRAPHICS_BIT', body)
        self.assertIn('VK_PIPELINE_STAGE_ALL_COMMANDS_BIT', body)
        self.assertIn('vka_gp_mark(cb, file, line);', body)

    def test_transfer_producers_keep_all_consumers(self):
        body = source_body(TEX, 'void vka_transfer_write_barrier_at(',
                           'void vka_img_barrier(')
        self.assertIn('VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT', body)
        self.assertIn('VK_ACCESS_TRANSFER_WRITE_BIT', body)
        self.assertIn('VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT', body)
        self.assertIn('vka_gp_mark(cb, file, line);', body)
        self.assertIn('case OP_CLEAR_BUF:', EXEC)
        self.assertIn('case OP_COPY_B2B:', EXEC)
        for line in EXEC.splitlines():
            if 'case OP_CLEAR_BUF:' in line or 'case OP_COPY_B2B:' in line:
                self.assertIn('vka_transfer_write_barrier(g_cb)', line)
                self.assertNotIn('vka_barrier(g_cb)', line)

    def test_bounce_copy_never_loses_dependency(self):
        self.assertIn('if (to_tex) vka_transfer_write_barrier(g_cb);', EXEC)
        self.assertIn('if (bounce) {\n            vka_transfer_write_barrier(g_cb);', EXEC)
        self.assertIn('vka_transfer_write_barrier(g_cb); // buffer/image transfer completed', EXEC)
        self.assertIn('vka_transfer_write_barrier(g_cb); // vkCmdCopyImage /', EXEC)
        self.assertIn('case OP_BARRIER:', EXEC)
        self.assertIn('vka_barrier(g_cb)', EXEC)

    def test_counters_show_true_graphics_and_transfer_scope(self):
        self.assertIn('uint64_t vka_n_graphics_bar;', TEX)
        self.assertIn('g_rp_graphics != graphics0', DRAW)
        self.assertIn('graphics-shader-scoped', DRAW)
        self.assertIn('extern uint64_t vka_n_rp, vka_n_bar, vka_n_transfer_bar, vka_n_compute_bar;', EXEC)
        self.assertIn('void vka_graphics_write_barrier_at(', HEADER)


if __name__ == '__main__':
    unittest.main()
