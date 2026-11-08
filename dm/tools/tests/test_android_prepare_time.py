"""The Android launcher's expected preparation time (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Expected time"): PrepareTime.java's estimate, time left, step meter and
text on the JVM (android/app/src/jvmtest's PrepareTimeJvmTest; skipped without a JDK)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APP = REPO / 'android/app/src'
SRC = [APP / 'main/java/dev/nxnative/android/PrepareTime.java']
TEST = APP / 'jvmtest/java/dev/nxnative/android/PrepareTimeJvmTest.java'


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
class PrepareTime(unittest.TestCase):
    def test_jvm(self):
        with tempfile.TemporaryDirectory(prefix='preparetime_') as tmp:
            subprocess.run(['javac', '-Xlint:all', '-Werror', '-encoding', 'UTF-8', '-d', tmp, *map(str, SRC), str(TEST)], check=True, capture_output=True, text=True)
            r = subprocess.run(['java', '-cp', tmp, 'dev.nxnative.android.PrepareTimeJvmTest'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(r.stdout.startswith('ok '), r.stdout)


if __name__ == '__main__':
    unittest.main()
