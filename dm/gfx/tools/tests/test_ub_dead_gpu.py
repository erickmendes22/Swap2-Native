"""Production deferred-write flush on Vulkan, preserving byte/journal history."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

R = Path(__file__).resolve().parents[4]
V = R / 'dm/gfx/vk_android'


class DeadUniformGpu(unittest.TestCase):
    def test_production_flush_and_negative_controls(self):
        cc = shutil.which('cc')
        if not sys.platform.startswith('linux') or not cc:
            self.skipTest('Linux and C compiler required')
        source = (V / 'vka_exec.c').read_text()
        begin = source.index('enum { UB_BATCH_MAX = 64 };')
        end = source.index('// ---------- Clears ----------', begin)
        body = source[begin:end]
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for variant in ('normal', 'broken-coverage'):
                code = body
                if variant == 'broken-coverage':
                    old = 'w->size <= later->size - offset'
                    self.assertIn(old, code)
                    code = code.replace(old, 'offset < later->size')
                (tmp / 'ub_flush.inc').write_text(code)
                exe = tmp / variant
                command = [cc, '-O1', '-g', '-DVKA_NDSR_PURE', '-I', str(tmp),
                           '-I', str(R / 'dm/third_party/vulkan-headers/include'),
                           '-I', str(V), str(V / 'selftest/ub_dead_gpu.c'),
                           str(V / 'vka_ndsr.c'), '-ldl', '-lm', '-o', str(exe)]
                compiled = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
                if result.returncode == 77:
                    self.skipTest(result.stdout + result.stderr)
                if variant == 'normal':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('Validation Error', result.stdout + result.stderr)
                    self.assertIn('528 cases;', result.stdout)
                    self.assertIn('repeated copies 64 -> 1; failures0', result.stdout)
                    print(result.stdout)
                    broken = subprocess.run([str(exe), 'broken-journal'], capture_output=True, text=True, timeout=120)
                    self.assertNotEqual(broken.returncode, 0, 'missing journal update was not detected')
                    self.assertIn('texture journal history changed', broken.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0, 'partial-write data loss was not detected')
                    self.assertIn('GPU contents differ', result.stdout)


if __name__ == '__main__':
    unittest.main()
