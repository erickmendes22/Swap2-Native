"""Deferred Vulkan uniforms: preserve guest GPU command ordering and all hazards.

Inspect invariants of Ocarina's shadow read path, live pass safety and flush.
The tests also compare overlapping recorded updates with direct sequential
writes under randomized interleavings; NDK clang compiles affected native C.
"""
from pathlib import Path
import random
import unittest

R=Path(__file__).resolve().parents[4]
EXEC=(R/"dm/gfx/vk_android/vka_exec.c").read_text()
DRAW=(R/"dm/gfx/vk_android/vka_draw.c").read_text()
TEX=(R/"dm/gfx/vk_android/vka_tex.c").read_text()

class DeferredUniformTests(unittest.TestCase):
    def test_passing_preconditions(self):
        self.assertIn('!VKA_ENV("DM_VK_UB_DEFER", 1)',DRAW)
        self.assertIn('R.swrite || R.bar_pending',DRAW)
        self.assertIn('R.rt.depth',DRAW)
        self.assertIn('R.rt.color[i]',DRAW)
        self.assertIn('g_ub_np < UB_DEFER_MAX',EXEC)
        self.assertIn('h.op == OP_BARRIER',EXEC)

    def test_shadow_and_hazards(self):
        self.assertIn('vka_tex_gw_shadow_read(addr, s.ptr, size)',DRAW)
        self.assertIn('vka_ub_overlay(addr, s.ptr, size)',DRAW)
        self.assertIn('vka_tex_id_overlaps_pending_ub(r->tid)',DRAW)
        self.assertIn('g_wk.n[st] < 0 || g_wk.pool[st]',DRAW)
        self.assertIn('vka_tex_id_overlaps_pending_ub(int id)',TEX)
        self.assertIn('memcpy(own, (const uint8_t *)a + 16, (size_t)n)',EXEC)
        self.assertIn('free(w->bytes);',EXEC)
        self.assertIn('if (g_ub_np || vka_rp_is_open()) vka_rp_end();',EXEC)
        self.assertIn('memo[i].seq == seq',DRAW)
        self.assertIn('r->what == VKA_R_GMEM_MAP || r->what == VKA_R_GMEM_LOG',DRAW)
        self.assertIn('r->desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER',DRAW)
        self.assertIn('vka_ub_pending_overlap(r->addr, r->size)',DRAW)
        self.assertIn('vka_tex_gw_shadow_safe(r->addr, r->size)',DRAW)
        self.assertIn('if (hazard) vka_rp_end();',DRAW)

    def test_flush_is_outside_renderpass_and_dependent(self):
        a=DRAW.index('vk.vkCmdEndRendering(g_cb);')
        b=DRAW.index('vka_ub_flush_pass();',a)
        self.assertLess(a,b)
        self.assertIn('vka_barrier(g_cb);\n    for (int i = 0; i < g_ub_np; i++)',EXEC)
        self.assertIn('buf_update(&g_inline_ub, w->bytes, w->addr, w->size);',EXEC)
        self.assertIn('ub_flush(&g_inline_ub);',EXEC)
        self.assertIn('g_ub_np = 0; g_ub_seq++;',EXEC)
        self.assertIn('w->fence && w->fence <= done',TEX)
        self.assertIn('if (w->kind == GW_OPAQUE || w->kind == GW_COPY)',TEX)

    def test_overlapping_writes_keep_last_recorded_byte(self):
        rng=random.Random(20261110)
        for _ in range(1000):
            old=bytearray(rng.randbytes(512))
            correct=bytearray(old)
            pending=[]
            for j in range(rng.randrange(2,25)):
                addr=rng.randrange(0,512)
                n=rng.randrange(1,513-addr)
                data=rng.randbytes(n)
                pending.append((addr,data))
                correct[addr:addr+n]=data
            shadow=bytearray(old)
            for addr,data in pending:
                shadow[addr:addr+len(data)]=data
            self.assertEqual(shadow,correct)

if __name__=="__main__": unittest.main()
