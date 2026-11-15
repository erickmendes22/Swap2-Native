"""Execute production report admission; no pending query may outlive its owner."""
import hashlib
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / 'dm/gfx/vk_android'


class RCGpuPolicy(unittest.TestCase):
    def test_actual_report_admission_and_boundaries(self):
        src = r'''
#include <assert.h>
#include <stdint.h>
#include "vka_rc_gpu_policy.h"
int main(void) {
 assert(vka_rc_gpu_range(3,1,0,0,12,13,10,20));
 assert(vka_rc_gpu_range(3,1,0,0,10,10,10,20));
 assert(!vka_rc_gpu_range(2,1,0,0,12,13,10,20));
 assert(!vka_rc_gpu_range(3,0,0,0,12,13,10,20));
 assert(!vka_rc_gpu_range(3,1,1,0,12,13,10,20));
 assert(!vka_rc_gpu_range(3,1,0,0,9,13,10,20));
 assert(!vka_rc_gpu_range(3,1,0,0,14,13,10,20));
 assert(!vka_rc_gpu_range(3,1,0,0,12,21,10,20));
 assert(vka_rc_gpu_range(3,1,0,0,100,356,100,1000));
 assert(!vka_rc_gpu_range(3,1,0,0,100,357,100,1000));
 assert(!vka_rc_gpu_range(3,1,0,0,UINT64_MAX-4,UINT64_MAX,0,UINT64_MAX-1));
 assert(!vka_rc_gpu_range(3,1,0,1,12,13,10,20));
 uint64_t seed=71;
 for (int i=0;i<100000;i++) {
  seed=seed*6364136223846793005ULL+1;
  uint64_t start=seed>>8, count=(seed&511), first=start-(seed&15);
  uint64_t end=start+count, head=start+((seed>>16)&511);
  int expected=end>=start && start>=first && end<=head && count<=256;
  assert(vka_rc_gpu_range(3,1,0,0,start,end,first,head)==expected);
 }
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'policy.c'; exe = p.with_suffix('')
            p.write_text(src)
            subprocess.run([shutil.which('cc'), '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I', str(VK), str(p), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_checked_in_helper_has_current_source_and_valid_spirv(self):
        text = (VK / 'vka_rc_gpu_spv.h').read_text()
        digest = hashlib.sha256((VK / 'rc/visibility.comp').read_bytes()).hexdigest()
        self.assertIn('source SHA256 ' + digest, text)
        words = [int(x, 16) for x in re.findall(r'0x[0-9a-f]{8}', text)]
        self.assertEqual(words[0], 0x07230203)
        validator = shutil.which('spirv-val')
        if validator:
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / 'helper.spv'
                p.write_bytes(struct.pack('<' + 'I' * len(words), *words))
                subprocess.run([validator, '--target-env', 'vulkan1.1', str(p)], check=True)


if __name__ == '__main__':
    unittest.main()

@unittest.skipUnless(__import__('os').getenv('MEMU_TEST_VULKAN') == '1', 'real Vulkan ICD required')
class RCGpuArithmetic(unittest.TestCase):
    def test_actual_checked_in_helper_64bit_counts_and_uncertainty(self):
        import os
        import random
        rng = random.Random(179)
        mask = (1 << 64) - 1
        values = [0, 1, 2, 0xffffffff, 1 << 32, 1 << 63, mask]
        queries = values + [rng.getrandbits(64) if i % 3 else 0 for i in range(64)]
        jobs, expected = [], []
        def append(firsta, counta, losta, firstb, countb, lostb, mode, precise):
            a = queries[firsta:firsta+counta]; b = queries[firstb:firstb+countb]
            jobs.extend([firsta, counta, losta & 0xffffffff, losta >> 32,
                         firstb, countb, lostb & 0xffffffff, lostb >> 32, mode, precise, 0, 0])
            if precise:
                equal = ((sum(a) + losta) & mask) == ((sum(b) + lostb) & mask)
            elif not any(a) and not any(b):
                equal = losta == lostb
            else:
                az = not any(a) and not losta; bz = not any(b) and not lostb
                if not az and not bz:
                    expected.append(1); return  # both positive: numerical comparison is unknown
                equal = az and bz
            expected.append(int(equal if mode == 0 else not equal))
        for precise in (0, 1):
            for mode in (0, 1):
                for a in range(7):
                    for b in range(7):
                        append(a, 1, 0, b, 1, 0, mode, precise)
                append(1, 1, mask, 0, 1, 0, mode, precise)  #64-bit carry/wrap
                append(0, 0, 1 << 32, 0, 0, 0, mode, precise)  # equal low words, different high
                append(0, 0, mask, 0, 0, mask, mode, precise)  # empty fresh reports
        for i in range(1000):
            fa, fb = rng.randrange(40), rng.randrange(40)
            append(fa, rng.randrange(8), rng.getrandbits(64), fb, rng.randrange(8),
                   rng.getrandbits(64), i & 1, (i >> 1) & 1)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            qp, jp, output = d / 'queries.bin', d / 'jobs.bin', d / 'out.bin'
            qp.write_bytes(struct.pack('<' + 'Q' * len(queries), *queries))
            jp.write_bytes(struct.pack('<' + 'I' * len(jobs), *jobs))
            exe = d / 'predicate'
            build = subprocess.run([shutil.which('cc'), '-O2', '-DVKA_NDSR_PURE',
                                    '-I', str(ROOT / 'dm/third_party/vulkan-headers/include'),
                                    '-I', str(VK), str(VK / 'selftest/rc_predicate_gpu.c'),
                                    str(VK / 'vka_ndsr.c'), '-ldl', '-lm', '-o', str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe), str(qp), str(jp), str(output)],
                                 env=dict(os.environ), capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn('Validation Error', run.stdout + run.stderr)
            self.assertNotIn('SYNC-HAZARD', run.stdout + run.stderr)
            result = struct.unpack('<' + 'I' * len(expected), output.read_bytes())
            self.assertEqual(list(result), expected)
            print(run.stdout)
