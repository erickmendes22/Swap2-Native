"""Exact cumulative NVN occlusion delta on SAME Vulkan submission only.

A report is normally fresh; its following cumulative report is not. Equality
of the two full counters equals zero samples + zero lost draws between them.
The verified existing GPU helper is reused with zero as A and delta as B.
No previous-submission query is eligible (query-pool host reset race).
"""
import hashlib
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"

class SameSubmissionDelta(unittest.TestCase):
    def test_compiled_real_range_policy_current_submission_and_epoch(self):
        code = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "vka_rc_gpu_policy.h"
int main(void) {
 vka_rc_gpu_delta d={0};
 // A and B are consecutive cumulative reports: B is NOT fresh. The
 // helper intentionally takes no "fresh" flag and does not demand one.
 assert(vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,100,107,90,110,&d));
 assert(d.begin==100&&d.end==107&&d.lost_delta==0);
 assert(vka_rc_gpu_delta_pair(3,3,5,5,0,0,7,9,101,101,90,110,&d));
 assert(d.begin==101&&d.end==101&&d.lost_delta==2);
 assert(!vka_rc_gpu_delta_pair(2,3,5,5,0,0,0,0,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,2,5,5,0,0,0,0,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,0,0,0,0,0,0,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,6,0,0,0,0,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,1,0,0,0,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,1,0,0,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,0,9,8,100,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,80,107,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,100,99,90,110,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,100,111,90,110,&d));
 assert(vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,100,356,90,900,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,100,357,90,900,&d));
 assert(!vka_rc_gpu_delta_pair(3,3,5,5,0,0,0,0,100,107,90,110,0));
 // Randomized policy parity with its EXACT documented guards.
 uint64_t seed=143;
 for(int i=0;i<100000;i++) {
  seed=seed*6364136223846793005ULL+1;
  uint64_t epochA=(seed>>28)&7,epochB=(seed>>31)&7;
  uint64_t begin=(seed>>16)&1023,end=(seed>>8)&1023;
  uint64_t sub=(seed>>11)&1023,head=(seed>>5)&1023;
  uint64_t lostA=(seed>>20)&31,lostB=(seed>>25)&31;
  uint64_t fenceA=(seed>>2)&1,fenceB=(seed>>3)&1;
  int ka=(seed>>6)&1?3:2,kb=(seed>>7)&1?3:2;
  int expected=ka==3&&kb==3&&epochA&&epochA==epochB&&
    !fenceA&&!fenceB&&lostB>=lostA&&
    begin>=sub&&end>=begin&&end<=head&&end-begin<=256;
  int actual=vka_rc_gpu_delta_pair(ka,kb,epochA,epochB,fenceA,fenceB,
    lostA,lostB,begin,end,sub,head,&d);
  assert(actual==expected);
  if(actual){assert(d.begin==begin&&d.end==end&&d.lost_delta==lostB-lostA);}
 }
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "policy.c"
            exe = Path(td) / "policy"
            src.write_text(code)
            p = subprocess.run([shutil.which("cc"), "-O2", "-std=c11",
                "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
                "-I", str(VK), str(src), "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            e = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(e.returncode, 0, e.stderr + e.stdout)

    def test_original_shader_and_exact_pair_arithmetic_are_preserved(self):
        src = (VK / "vka_rc_gpu.inc").read_text()
        self.assertIn('DM_VK_GPU_VISIBILITY", 0', src)
        self.assertIn('DM_VK_OOT_RC_DELTA", 1', src)
        self.assertIn('vka_rc_gpu_delta_pair(', src)
        self.assertIn('d.begin, d.end, OQ_N', src)
        self.assertIn('j[4] = off;', src)
        self.assertIn('j[5] = (uint32_t)(d.end - d.begin);', src)
        self.assertIn('j[6] = (uint32_t)d.lost_delta;', src)
        self.assertIn('j[7] = (uint32_t)(d.lost_delta >> 32);', src)
        self.assertIn('a->fence, b->fence', src)
        self.assertIn('a->oq_epoch, b->oq_epoch', src)
        self.assertIn('if (!RG.delta_mode)', src)
        self.assertIn('RG.delta_mode ? (a.oq_end == b.oq_end)', src)
        comp = (VK / "rc/visibility.comp").read_bytes()
        header = (VK / "vka_rc_gpu_spv.h").read_text()
        self.assertIn("source SHA256 " + hashlib.sha256(comp).hexdigest(), header)
        # For every precise pair cumulative equality is exactly the modulo
        # 64-bit delta zero check; for nonprecise only ZERO vs POSITIVE is safe.
        rng = random.Random(179)
        mask = (1 << 64) - 1
        for i in range(10000):
            prefix = rng.getrandbits(64)
            count = rng.randrange(17)
            delta = [0 if rng.randrange(4) else rng.getrandbits(64) for _ in range(count)]
            lost = rng.randrange(4)
            a = prefix
            b = (prefix + sum(delta) + lost) & mask
            self.assertEqual(a == b, (sum(delta) + lost) & mask == 0)
            if not any(delta) and not lost:
                self.assertEqual(a, b)

@unittest.skipUnless(os.getenv("MEMU_TEST_VULKAN") == "1",
                     "requires actual Vulkan ICD for GPU arithmetic")
class SameSubmissionDeltaGPU(unittest.TestCase):
    def test_actual_checked_in_helper_zero_vs_delta_all_modes(self):
        rng = random.Random(107)
        queries, jobs, expected = [], [], []
        mask = (1 << 64) - 1
        for i in range(640):
            n = rng.randrange(13)
            items = [rng.choice([0, 0, 0, 1, 0xffffffff,
                                 1 << 32, (1 << 64) - 1,
                                 rng.getrandbits(64)]) for _ in range(n)]
            off = len(queries); queries.extend(items)
            lost = rng.choice([0, 0, 1, 2, 1 << 32, mask])
            mode = i % 2
            precise = (i // 2) % 2
            jobs.extend([0, 0, 0, 0, off, n, lost & 0xffffffff,
                         lost >> 32, mode, precise, 0, 0])
            zero = (((sum(items) + lost) & mask) == 0) if precise else (
                not any(items) and lost == 0)
            expected.append(int(zero if mode == 0 else not zero))
        # Explicit carry: one query max + a lost count 1 wraps in 64 bits.
        off = len(queries); queries.append(mask)
        jobs.extend([0,0,0,0,off,1,1,0,0,1,0,0])
        expected.append(1)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            qp, jp, out = d/"queries.bin", d/"jobs.bin", d/"out.bin"
            qp.write_bytes(struct.pack("<" + "Q"*len(queries), *queries))
            jp.write_bytes(struct.pack("<" + "I"*len(jobs), *jobs))
            exe = d / "gpu-delta"
            cc = shutil.which("cc") or shutil.which("clang")
            self.assertTrue(cc)
            build = subprocess.run([cc, "-O2", "-DVKA_NDSR_PURE",
                "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                "-I", str(VK), str(VK / "selftest/rc_predicate_gpu.c"),
                str(VK / "vka_ndsr.c"), "-ldl", "-lm", "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe), str(qp), str(jp), str(out)],
                env=dict(os.environ), capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertNotIn("Validation Error", run.stderr + run.stdout)
            self.assertNotIn("SYNC-HAZARD", run.stderr + run.stdout)
            result = struct.unpack("<" + "I"*len(expected), out.read_bytes())
            self.assertEqual(result, tuple(expected))
            print(f"GPU cumulative-delta predicate: {len(expected)} exact "
                  "zero-vs-delta decisions, both modes, precise/nonprecise, "
                  "64-bit lost/carry; NO live-title FPS conclusion", flush=True)
if __name__ == "__main__":
    unittest.main()
