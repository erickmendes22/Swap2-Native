"""The mods a profile ships (dm/games/<id>/mods/<folder>/: exefs/<files> and mod.tsv), which the Android launcher offers as a switch and copies into the mods
folder when it is turned on (android/app/src/main/java/dev/nxnative/android/BuiltinMods.java; android/README.md "Mods (exefs patches)"). For each one: mod.tsv
has only known keys, android_default is on or off, and label and note name strings that res/values and res/values-pt both have; every patch file in exefs/
parses (dm/tools/exefs_patches.py) and is for a module build of one of the profile's build rows (its first 16 bytes, as game.tsv gives them); every record is
covered by a check row (module, offset, original bytes) of the same length. With DM_PROFILE_MODS_NSO=<title ID>:<module>=<NSO file>[,...] (a dump's module, never
in the repository) the original bytes are also compared with that module and the patched words read back. The launcher's BuiltinMods.java runs its JVM test
(javac, skipped without a JDK)."""
import os
import shutil
import subprocess
import tempfile
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/tools'))
sys.path.insert(0, str(REPO / 'dm/games'))
import exefs_patches as xp   # noqa: E402
import game   # noqa: E402
import nso   # noqa: E402

KEYS = {'label', 'note', 'android_default', 'check'}
RES = REPO / 'android/app/src/main/res'


def mods():
    """[(profile dir, mod dir)] of every profile's shipped mods"""
    return [(p, m) for p in sorted((REPO / 'dm/games').iterdir()) if (p / 'mods').is_dir() for m in sorted((p / 'mods').iterdir()) if m.is_dir()]


def rows(tsv):
    out = []
    for ln in tsv.read_text(encoding='utf-8').splitlines():
        if ln.strip() and not ln.startswith('#'): out.append(ln.split('\t'))
    return out


def strings(lang):
    f = RES / ('values' if lang == 'en' else f'values-{lang}') / 'strings.xml'
    return set(re.findall(r'<string name="([^"]+)"', f.read_text(encoding='utf-8')))


def given_nsos():
    out = {}
    for item in filter(None, os.environ.get('DM_PROFILE_MODS_NSO', '').split(',')):
        k, _, path = item.partition('=')
        out[k.strip()] = Path(path.strip())
    return out


class ProfileMods(unittest.TestCase):
    def test_shipped_mods(self):
        en, pt, nsos = strings('en'), strings('pt'), given_nsos()
        for prof, mod in mods():
            with self.subTest(mod=f'{prof.name}/{mod.name}'):
                self.assertTrue(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', mod.name), 'a folder name the shared storage and the launcher keep as it is')
                meta = rows(mod / 'mod.tsv')
                kv = {r[0]: r[1:] for r in meta if r[0] != 'check'}
                self.assertFalse({r[0] for r in meta} - KEYS, 'unknown keys in mod.tsv')
                self.assertIn(kv.get('android_default', [''])[0], ('on', 'off'))
                for k in ('label', 'note'):
                    s = kv.get(k, [''])[0]
                    self.assertIn(s, en, f'{k} {s!r} is not in res/values/strings.xml')
                    self.assertIn(s, pt, f'{k} {s!r} is not in res/values-pt/strings.xml')
                checks = [(r[1], int(r[2], 0), bytes.fromhex(r[3])) for r in meta if r[0] == 'check']
                builds = {(m, bid[:32]) for b in game.load(str(prof)).builds().values() for m, bid in b.items() if m != 'display'}
                files = sorted(f for f in (mod / 'exefs').iterdir() if f.is_file())
                self.assertTrue(files, 'no patch file in exefs/')
                for f in files:
                    self.assertIn(f.suffix.lower(), xp.EXTS)
                    recs = xp.parse(f)
                    bid = xp.pchtxt_build_id(f.read_bytes()) if f.suffix.lower() == '.pchtxt' else xp.pad(f.name.split('.')[0])
                    module = next((m for m, b in builds if b == bid[:32]), None)
                    self.assertIsNotNone(module, f'{f.name} is for build {bid[:40]}, which no build row of the profile has')
                    for r in recs:
                        at = r.offset - xp.HEADER
                        hit = [c for c in checks if c[0] == module and c[1] == at and len(c[2]) == len(r.data)]
                        self.assertTrue(hit, f'{f.name}: the record at {module}+{at:#x} has no check row of its original bytes')
                        self.assertNotEqual(hit[0][2], r.data)
                    nso_file = nsos.get(f'{prof.name}:{module}')
                    if nso_file:
                        data = nso_file.read_bytes()
                        self.assertEqual(xp.pad(data[0x40:0x60].hex()), bid, f'{nso_file} is another build')
                        img = nso.load(data, module).image
                        for m, at, orig in checks:
                            if m == module: self.assertEqual(bytes(img[at:at + len(orig)]), orig, f'{module}+{at:#x} in {nso_file}')
                        patched, _ = xp.apply(data, [(f'{mod.name}/exefs/{f.name}', f)], module)
                        pimg = nso.load(patched, module).image
                        for r in recs:
                            at = r.offset - xp.HEADER
                            self.assertEqual(bytes(pimg[at:at + len(r.data)]), r.data)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
    def test_launcher_builtin_mods(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            pkg = REPO / 'android/app/src/main/java/dev/nxnative/android'
            test = REPO / 'android/app/src/jvmtest/java/dev/nxnative/android/BuiltinModsJvmTest.java'
            r = subprocess.run(['javac', '-Xlint:all', '-Werror', '-d', str(d / 'classes'), str(pkg / 'BuiltinMods.java'), str(pkg / 'ExefsMods.java'), str(test)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            (d / 'work').mkdir()
            r = subprocess.run(['java', '-cp', str(d / 'classes'), 'dev.nxnative.android.BuiltinModsJvmTest', str(d / 'work')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
