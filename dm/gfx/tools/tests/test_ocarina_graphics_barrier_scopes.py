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
        self.assertIn('int full = g_rp_force_full || had_clears || vka_nan_on();', body)
        self.assertIn('int pending_attachment = R.bar_pending && !full && !R.swrite;', body)
        self.assertIn('if (pending_attachment) g_rp_pending_attachment++;', body)
        self.assertIn('if (full || (R.swrite && VKA_ENV("DM_VK_OOT_FPS_BOOST", 0) <= 0)) {', body)
        self.assertIn('g_rp_full++; vka_barrier(g_cb);', body)
        self.assertIn('g_rp_graphics++; vka_graphics_write_barrier(g_cb);', body)
        self.assertIn('g_rp_scoped++; vka_attachment_write_barrier(g_cb);', body)
        self.assertIn('const int postub = vka_ub_active();', body)
        self.assertIn('DM_VK_OOT_POSTUB_BAR_DEDUP', body)

    def test_readonly_occlusion_pass_omits_only_producer_free_barrier(self):
        # An Ocarina depth-TEST-only draw can produce a query result without
        # writing any color/depth/stencil attachment. This is NOT permission
        # to remove a dependency after a loadOp CLEAR, in-pass clear, depth
        # write, any stencil state, fragment output, shader store or an
        # explicit NVN barrier. All such cases retain previous barriers.
        body = source_body(DRAW, 'void vka_rp_end(void) {',
                           '// OP_BARRIER used to end a render pass')
        self.assertIn('int awrite;', DRAW)
        self.assertIn('if (ca[i].imageView && ca[i].loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) R.awrite = 1;', DRAW)
        self.assertIn('if ((dp && dp->loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) ||', DRAW)
        self.assertIn('(sp && sp->loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR) || nlate)', DRAW)
        self.assertIn('R.awrite = 1; // a clear is never a read-only occlusion pass', DRAW)
        self.assertIn('if (k.att[i].mask) { R.awrite = 1; break; }', DRAW)
        self.assertIn('R.df != VK_FORMAT_UNDEFINED && d->ds.dt && d->ds.dw', DRAW)
        self.assertIn('R.sf != VK_FORMAT_UNDEFINED && d->ds.st', DRAW)
        self.assertLess(body.index('if (full || (R.swrite'),
                        body.index('else if (!R.awrite'))
        self.assertLess(body.index('else if (R.swrite)'),
                        body.index('else if (!R.awrite'))
        self.assertIn('VKA_ENV("DM_VK_OOT_READONLY_PASS", 1)', body)
        self.assertIn('g_rp_readonly_barriers_avoided++;', body)
        self.assertIn('g_rp_scoped++; vka_attachment_write_barrier(g_cb);', body)
        self.assertIn('read-only passes without attachment barrier', DRAW)

    def test_delta_push_descriptor_updates_preserve_unchanged_bindings(self):
        # Same Vulkan pipeline layout, same ordered bindings, and descriptor
        # count 1 are required. Changed binding order always falls back to
        # full push; an unrelated game retains the old default (0).
        self.assertIn('VKA_ENV("DM_VK_PUSH_DELTA",', DRAW)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")) && g_pd[c].n == k', DRAW)
        self.assertIn('if (a[0] != b[0]) ok = 0;', DRAW)
        self.assertIn('else if (memcmp(a + 1, b + 1, 3 * sizeof *a)) g_dw[g_dwn++] = g_w.w[i];', DRAW)
        self.assertIn('vk.vkCmdPushDescriptorSetKHR(g_cb, bp, lay->layout, 0, g_dwn, g_dw)', DRAW)
        self.assertIn('w->descriptorCount != 1', DRAW)
        self.assertIn('g_pd[c].w[0] == buf[0] && g_pd[c].w[1] == buf[1]', DRAW)

    def test_readonly_barrier_truth_table(self):
        from itertools import product
        # Every possible combination of NVN operations must keep a barrier
        # when ANY recognized attachment or shader write / forced ordering
        # was recorded. Only the producer-free condition is optimized.
        for values in product((False, True), repeat=6):
            color_write, depth_write, stencil, clear, shader_store, full = values
            expected = any(values)
            suppress = not (color_write or depth_write or stencil or clear) and not shader_store and not full
            self.assertEqual(not suppress, expected)

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
                self.assertIn('boost_transfer_barrier(g_cb)', line)
                self.assertNotIn('vka_barrier(g_cb)', line)

    def test_bounce_copy_never_loses_dependency(self):
        self.assertIn('if (to_tex) boost_transfer_barrier(g_cb);', EXEC)
        self.assertIn('if (bounce) {\n            boost_transfer_barrier(g_cb);', EXEC)
        self.assertIn('boost_transfer_barrier(g_cb); // buffer/image transfer completed', EXEC)
        self.assertIn('boost_transfer_barrier(g_cb); // vkCmdCopyImage /', EXEC)
        self.assertIn('case OP_BARRIER:', EXEC)
        self.assertIn('vka_barrier(g_cb)', EXEC)

    def test_counters_show_true_graphics_and_transfer_scope(self):
        self.assertIn('uint64_t vka_n_graphics_bar;', TEX)
        self.assertIn('g_rp_graphics != graphics0', DRAW)
        self.assertIn('graphics-shader-scoped', DRAW)
        self.assertIn('extern uint64_t vka_n_rp, vka_n_bar, vka_n_transfer_bar, vka_n_compute_bar;', EXEC)
        self.assertIn('void vka_graphics_write_barrier_at(', HEADER)
        self.assertIn('VKA_ENV("DM_VK_OOT_FPS_BOOST", 0) > 0', EXEC)
        self.assertIn('else vka_barrier(cb);', EXEC)


if __name__ == '__main__':
    unittest.main()
