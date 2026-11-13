"""Synthetic fragment fixture proves comparison accepts equivalence and detects changes.

Requires an explicitly selected Vulkan 1.3 ICD and optional Python Vulkan/numpy.
No game shaders are included in the repository.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
AVAILABLE = (os.environ.get('VK_ICD_FILENAMES') and
             all(shutil.which(x) for x in ('glslangValidator', 'spirv-val')) and
             all(importlib.util.find_spec(x) for x in ('vulkan', 'numpy')))


@unittest.skipUnless(AVAILABLE, 'explicit Vulkan ICD and optional probe dependencies required')
class FragmentGpuProbe(unittest.TestCase):
    def test_equivalent_and_changed_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d)
            for integer in (False, True):
                with self.subTest(integer=integer):
                    shaders = []
                    base = 'floatBitsToUint(value)' if integer else 'value'
                    equivalent = 'floatBitsToUint(vec4(value.xyz, value.w + 0.0))' if integer else 'vec4(value.xyz, value.w + 0.0)'
                    wrong = base + (' + uvec4(1)' if integer else ' + vec4(0.125)')
                    for name, value in (('original', base), ('equivalent', equivalent), ('wrong', wrong)):
                        source = work / (str(integer) + name + '.frag')
                        source.write_text('#version 450\nlayout(location=2) in vec4 value;\n'
                                          'layout(location=0) out ' + ('uvec4' if integer else 'vec4') +
                                          ' color;\nvoid main(){color=' + value + ';}\n')
                        out = source.with_suffix('.spv')
                        subprocess.run(['glslangValidator', '-V', str(source), '-o', str(out)],
                                       check=True, capture_output=True)
                        shaders.append(out)
                    def probe(candidate, name):
                        return subprocess.run([sys.executable, str(REPO/'dm/gfx/tools/fragment_gpu_probe.py'),
                                               str(shaders[0]), str(candidate), str(work/(str(integer)+name)), '--size', '16'],
                                              capture_output=True, text=True, timeout=45)
                    equal = probe(shaders[1], 'equal')
                    self.assertEqual(equal.returncode, 0, equal.stdout + equal.stderr)
                    result = json.loads(equal.stdout.splitlines()[-1])
                    self.assertIn('uint32' if integer else 'float32', result['output_type'])
                    self.assertTrue(all(r['equal'] and r['unique_finite_values'] > 1 for r in result['results']))
                    wrong_result = probe(shaders[2], 'wrong')
                    self.assertNotEqual(wrong_result.returncode, 0)
                    self.assertIn('fragment output mismatch', wrong_result.stderr)
