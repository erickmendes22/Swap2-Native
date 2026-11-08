"""The phone's Switch2 folder layout (android/README.md "The Switch2 folder"; Switch2Layout.java with android/app/src/jvmtest's Switch2LayoutJvmTest) on the JVM:
the one-time move of games into Games/, <title ID>-work into Work/<title ID> and mods/ into Mods/ by rename, what it leaves alone (app data, unknown files,
a title whose Prepare job runs, an entry whose target exists), a failed rename, later runs, an interrupted run finished from move.log, the repointing of
saved paths and job.json, and where a dump's work folder is. Skipped without a JDK."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / 'android/app/src/main/java/dev/nxnative/android'
TEST = REPO / 'android/app/src/jvmtest/java/dev/nxnative/android/Switch2LayoutJvmTest.java'


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
class Switch2LayoutJvm(unittest.TestCase):
    def test_move_and_repoint(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = subprocess.run(['javac', '-Xlint:all', '-Werror', '-d', str(d / 'classes'), str(SRC / 'Switch2Layout.java'), str(SRC / 'Frontend.java'), str(TEST)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            (d / 'run').mkdir()
            r = subprocess.run(['java', '-cp', str(d / 'classes'), 'dev.nxnative.android.Switch2LayoutJvmTest', str(d / 'run')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(r.stdout.startswith('ok '), r.stdout)


if __name__ == '__main__':
    unittest.main()
