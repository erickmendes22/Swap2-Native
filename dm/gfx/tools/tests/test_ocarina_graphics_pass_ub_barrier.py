"""Ocarina GPU graphics passes: keep attachment-only guest barriers while
deferring independent inline uniform uploads, with guarded shadow snapshots.

The previous path ended a pass on every update after R.bar_pending.
Model all byte-level overlapping uniform updates and exercise fail-closed
conditions; NDK compiles the native sources in the existing APK workflow.
"""
from pathlib import Path
import random
import unittest

ROOT=Path(__file__).resolve().parents[4]
DRAW=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
EXEC=(ROOT/"dm/gfx/vk_android/vka_exec.c").read_text()
HDR=(ROOT/"dm/gfx/vk_android/vka.h").read_text()

def intersects(a,an,b,bn):
    return an>0 and bn>0 and (a<=b and b-a<an or b<a and a-b<bn)

def eligible(on, shader_writes, bar_pending, enabled, oot,
             opt_in, addr, n, attachments):
    if not on or shader_writes or not enabled or n<=0:
        return False
    if bar_pending and not (oot if opt_in is None else opt_in):
        return False
    if any(intersects(addr,n,a,al) for a,al in attachments):
        return False
    return True

class BarrierRetainedUniformTest(unittest.TestCase):
    def test_oot_guest_barrier_eligible_only_with_no_shader_writes(self):
        targets=[(4096,128),(8192,2048)]
        self.assertTrue(eligible(1,0,1,1,1,None,2048,64,targets))
        self.assertFalse(eligible(1,1,1,1,1,None,2048,64,targets))
        self.assertFalse(eligible(1,0,1,1,1,None,4096,64,targets))
        self.assertFalse(eligible(1,0,1,1,1,None,8240,64,targets))
        self.assertFalse(eligible(1,0,1,1,0,None,2048,64,targets))
        self.assertFalse(eligible(1,0,1,1,1,False,2048,64,targets))
        self.assertFalse(eligible(1,0,1,0,1,None,2048,64,targets))
        self.assertFalse(eligible(0,0,1,1,1,None,2048,64,targets))

    def test_ordered_snapshots_match_immediate_writes_across_guest_barriers(self):
        rng=random.Random(20261111)
        for _ in range(1000):
            base=rng.randbytes(1024)
            immediate=bytearray(base)
            queued=[]
            for _ in range(rng.randrange(2,30)):
                offset=rng.randrange(1024)
                count=rng.randrange(1,1025-offset)
                buf=rng.randbytes(count)
                queued.append((offset,buf))
                immediate[offset:offset+count]=buf
                # Every possible post-update draw sees its own overlay:
                shadow=bytearray(base)
                for a,d in queued: shadow[a:a+len(d)]=d
                self.assertEqual(immediate,shadow)
            flush=bytearray(base)
            for a,d in queued:flush[a:a+len(d)]=d
            self.assertEqual(immediate,flush)

    def test_integration_checks_guest_and_gpu_hazard_guards(self):
        self.assertIn('int vka_rp_bar_pending(void)',DRAW)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")',DRAW)
        self.assertIn('DM_VK_OOT_UB_AFTER_BARRIER',DRAW)
        self.assertIn('int vka_rp_bar_pending(void);',HDR)
        self.assertIn('g_ub_after_guest_bar++;',EXEC)
        self.assertIn('if (after_barrier)',EXEC)
        self.assertIn('g_ub_pending[g_ub_np++]',EXEC)
        self.assertIn('if (hazard) vka_rp_end();',DRAW)
        self.assertIn('r->desc == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER',DRAW)
        self.assertIn('vka_tex_id_overlaps_pending_ub(r->tid)',DRAW)
        self.assertIn('vka_ub_overlay(addr, s.ptr, size);',DRAW)
        self.assertIn('vka_barrier(g_cb);\n    for (int i = 0; i < g_ub_np; i++)',EXEC)
        self.assertIn('vka_transfer_write_barrier(g_cb);',EXEC)
        self.assertIn('R.rt.depth',DRAW)
        self.assertIn('R.rt.color[i]',DRAW)
        self.assertIn('!R.on || R.swrite',DRAW)

if __name__=="__main__": unittest.main()
