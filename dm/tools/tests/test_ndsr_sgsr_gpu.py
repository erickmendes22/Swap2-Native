"""Actual SGSR1 SPIR-V versus an independent Banana public-source reference.

All pixels, both stores and encodings, HDR, odd sizes, cropped push mapping,
legacy grid coverage, sampler isolation, and a deliberately wrong old kernel.
A software Vulkan driver's timings are diagnostics, never an Adreno FPS claim.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
VK = ROOT / 'dm/gfx/vk_android'
sys.path.insert(0, str(VK / 'fsr'))
import ndsr_spv


class SgsrGpu(unittest.TestCase):
    def test_reference_pixels_and_grid(self):
        compiler = shutil.which('cc')
        glslc, validator = ndsr_spv.tool('glslc'), ndsr_spv.tool('spirv-val')
        if not sys.platform.startswith('linux') or not all((compiler, glslc, validator)):
            self.skipTest('Linux C compiler, glslc and spirv-val required')
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            env = dict(os.environ, NDSR_SGSR_TEST='1')
            for packed in (0, 1):
                for variant, source, flags in (
                    ('REF', VK / 'selftest/sgsr_reference.comp', (['-DNDSR_PACKED=1'] if packed else [])),
                    ('STRIDE', VK / 'fsr/ndsr_sgsr.comp', [f'-DPACKED={packed}', '-DSGSR_GRID_STRIDE=1']),
                ):
                    output = tmp / f'{variant}-{packed}.spv'
                    subprocess.run([glslc, '-O', '--target-env=vulkan1.1', *flags,
                                    str(source), '-o', str(output)], check=True, capture_output=True)
                    subprocess.run([validator, '--target-env', 'vulkan1.1', str(output)], check=True, capture_output=True)
                    env[f'SGSR_{variant}_{"PACKED" if packed else "FLOAT"}'] = str(output)
            exe = tmp / 'ndsr-gpu'
            subprocess.run([compiler, '-O2', '-DVKA_NDSR_PURE', '-I', str(ROOT / 'dm/third_party/vulkan-headers/include'),
                            '-I', str(VK), str(VK / 'selftest/ndsr_lvp.c'), str(VK / 'vka_ndsr.c'),
                            '-ldl', '-lm', '-o', str(exe)], check=True, capture_output=True)
            result = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=300)
            if result.returncode == 77:
                self.skipTest(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count('SGSR reference:'), 20, result.stdout)
            self.assertEqual(result.stdout.count('max_error=0 '), 20, result.stdout)
            self.assertIn('old simplified kernel differs', result.stdout)
            print(result.stdout)


if __name__ == '__main__':
    unittest.main()
