"""The actual explicit scene/output policy, without Android or game bytes."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]


@unittest.skipUnless(shutil.which('java'),'JDK required')
class RenderProfile(unittest.TestCase):
    def test_actual_policy(self):
        with tempfile.TemporaryDirectory() as d:
            compiler=[shutil.which('javac')] if shutil.which('javac') else ['java','com.sun.tools.javac.Main']
            subprocess.run([*compiler,'-encoding','UTF-8','-Xlint:all','-Werror','-d',d,
                str(ROOT/'android/app/src/main/java/dev/nxnative/android/OcarinaRenderProfile.java'),
                str(ROOT/'android/app/src/jvmtest/java/dev/nxnative/android/OcarinaRenderProfileJvmTest.java')],check=True,capture_output=True)
            subprocess.run(['java','-cp',d,'dev.nxnative.android.OcarinaRenderProfileJvmTest'],check=True)
