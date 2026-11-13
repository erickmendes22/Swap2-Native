"""Compile and exercise the renderer's exact fragment linkage gate."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class FragmentPatch(unittest.TestCase):
    def test_production_linkage_gate(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'fragment-patch'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            str(REPO/'dm/host/tests/t_fragment_patch.c'),
                            str(REPO/'dm/gfx/vk_android/vka_shlib.c'),
                            str(REPO/'dm/third_party/zstd/zstddeclib.c'),
                            '-o', str(out)], check=True, capture_output=True)
            result = subprocess.run([str(out)], check=True, capture_output=True, text=True)
            self.assertIn('18 rejection cases passed', result.stdout)
