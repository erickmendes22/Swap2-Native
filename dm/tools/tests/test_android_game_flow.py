"""The Android launcher's one-button game flow (docs/SWAP2-NATIVE-PREPARE-FLOW.md "Single-action flow"): GameFlow.java's decision table, job.json's
normalization and the failure codes on the JVM (android/app/src/jvmtest's GameFlowJvmTest; skipped without a JDK), and the strings it shows: the same keys and
the same format arguments in English (values) and Portuguese (values-pt), and no hard-coded text in the dialogs and Toasts of the flow's own files."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APP = REPO / 'android/app/src'
SRC = [APP / 'main/java/dev/nxnative/android/GameFlow.java', APP / 'main/java/dev/nxnative/android/PackFacts.java']
TEST = APP / 'jvmtest/java/dev/nxnative/android/GameFlowJvmTest.java'
EN, PT = APP / 'main/res/values/strings.xml', APP / 'main/res/values-pt/strings.xml'
# the flow's own files: every text they show comes from the resources
FLOW = [APP / 'main/java/dev/nxnative/android/ProblemSheet.java', APP / 'ondevice/java/dev/nxnative/android/GameState.java',
        APP / 'ondevice/java/dev/nxnative/android/PrepareScreen.java', APP / 'ondevice/java/dev/nxnative/android/PrepareActivity.java']


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
class Flow(unittest.TestCase):
    def test_table(self):
        with tempfile.TemporaryDirectory(prefix='gameflow_') as tmp:
            subprocess.run(['javac', '-Xlint:all', '-Werror', '-encoding', 'UTF-8', '-d', tmp, *map(str, SRC), str(TEST)], check=True, capture_output=True, text=True)
            r = subprocess.run(['java', '-cp', tmp, 'dev.nxnative.android.GameFlowJvmTest'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(r.stdout.startswith('ok '), r.stdout)


def strings(path):
    """name → text of every translatable string (plurals and arrays by name, text '')"""
    s = path.read_text(encoding='utf-8')
    out = {}
    for m in re.finditer(r'<string name="([^"]+)"([^>]*)>(.*?)</string>', s, re.S):
        if 'translatable="false"' not in m.group(2): out[m.group(1)] = m.group(3)
    for m in re.finditer(r'<(plurals|string-array) name="([^"]+)"', s): out[m.group(2)] = ''
    return out


def args(t): return sorted(re.findall(r'%(\d+)\$[-,.\d]*([sdf])', t))


class Strings(unittest.TestCase):
    def test_same_keys(self):
        en, pt = strings(EN), strings(PT)
        self.assertEqual(sorted(set(en) - set(pt)), [], 'in values only')
        self.assertEqual(sorted(set(pt) - set(en)), [], 'in values-pt only')

    def test_same_arguments(self):
        en, pt = strings(EN), strings(PT)
        for k in en.keys() & pt.keys():
            self.assertEqual(args(en[k]), args(pt[k]), f'{k}: the translations take other arguments')

    def test_apostrophes(self):   # aapt2 refuses an unescaped ' (and the text would lose it)
        for p in (EN, PT):
            for k, t in strings(p).items():
                self.assertIsNone(re.search(r"(?<!\\)'", t), f'{p.parent.name}/{k}: unescaped apostrophe')

    def test_flow_texts_from_resources(self):
        lit = re.compile(r'(setTitle|setMessage|makeText\([^,]+,|setText|Ui\.button\([^,]+,|Ui\.text\([^,]+,|Ui\.small\([^,]+,|Ui\.body\([^,]+,)\s*\(?"[A-Za-z]')
        for f in FLOW:
            for i, line in enumerate(f.read_text(encoding='utf-8').splitlines(), 1):
                self.assertIsNone(lit.search(line), f'{f.name}:{i}: a hard-coded text: {line.strip()}')


if __name__ == '__main__':
    unittest.main()
