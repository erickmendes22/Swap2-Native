"""Per-game touch selection, persisted namespaces, complete mappings and safe-area geometry."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

class TouchResourceEncodingTest(unittest.TestCase):
    def test_string_resources_are_utf8(self):
        for path in (ROOT / 'android/app/src/main/res').glob('values*/strings.xml'):
            with self.subTest(path=path.name, locale=path.parent.name):
                text = path.read_bytes().decode('utf-8', errors='strict')
                self.assertNotIn('\ufffd', text)
                ET.fromstring(text)

class StandardSkinAssetTest(unittest.TestCase):
    """The standard skin v2: the bundled atlas is the selected clean one, and TouchProfile's sprite table is sprites-v2.json."""
    ART = ROOT / 'assets/artwork/swap2-native/standard-touch-v2'

    def test_bundled_atlas_is_clean(self):
        bundled = ROOT / 'android/app/src/main/res/drawable-nodpi/s2_standard_controls_v2.png'
        self.assertEqual(bundled.read_bytes(), (self.ART / 'standard-touch-atlas-v2-clean.png').read_bytes())
        self.assertNotEqual(bundled.read_bytes(), (self.ART / 'standard-touch-atlas-v2.png').read_bytes())

    def test_sprite_table_matches_manifest(self):
        manifest = json.loads((self.ART / 'sprites-v2.json').read_text(encoding='utf-8'))
        source = (ROOT / 'android/app/src/main/java/dev/nxnative/android/TouchProfile.java').read_text(encoding='utf-8')
        ids = re.findall(r'"([a-z0-9_]+)"', group1(r' SPRITE_IDS = \{(.*?)\};', source, re.S))
        rects = [list(map(int, m)) for m in re.findall(r'\{(\d+), (\d+), (\d+), (\d+)\}', group1(r'STANDARD_SPRITE_RECTS = \{(.*?)\n    \};', source, re.S))]
        self.assertEqual(ids, list(manifest['sprites']))
        self.assertEqual(rects, [manifest['sprites'][i]['rect_px'] for i in ids])
        self.assertIn(f"STANDARD_ATLAS_SIZE = {manifest['width']}", source)

    def test_layout_matches_reference(self):
        reference = json.loads((self.ART / 'layout-reference-v2.json').read_text(encoding='utf-8'))
        source = (ROOT / 'android/app/src/main/java/dev/nxnative/android/TouchProfile.java').read_text(encoding='utf-8')
        for control in reference['controls']:
            if not control['enabled_initially'] or control['sprite'] in ('left_stick_cap', 'right_stick_cap') or control['sprite'] in ('up', 'down', 'left', 'right'):
                continue
            (x, y), (w, h) = control['center_ref'], control['size_ref']
            def num(v): return f'{v:g}' + ('f' if v != int(v) else '')
            with self.subTest(sprite=control['sprite']):
                if control['sprite'] in ('left_stick_base', 'right_stick_base', 'visibility', 'settings'):
                    self.assertRegex(source, rf'"{control["sprite"]}", [^;]*?{num(x)}, {num(y)}, {w // 2:g}, {h // 2:g}\)')
                else:
                    self.assertIn(f'std("{control["sprite"]}", ', source)
                    self.assertRegex(source, rf'std\("{control["sprite"]}", \d+, ANCHOR_{control["anchor"].upper()}, {num(x)}, {num(y)}, {w:g}, {h:g}\)')


def group1(pattern, text, flags=0):
    """The first group of pattern's match in text: a failed test when the source has none"""
    m = re.search(pattern, text, flags); assert m, f'{pattern} matches nothing'; return m.group(1)


def png_size(path):
    """Width and height from a PNG's IHDR chunk."""
    data = Path(path).read_bytes()[:24]
    assert data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR'
    return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')

class Zelda40SkinAssetTest(unittest.TestCase):
    """Zelda's 40th anniversary skin (docs/SWAP2-NATIVE-ZELDA40-TOUCH-v1.md): the bundled atlas, its sprite table, its placement and its routing."""
    ART = ROOT / 'assets/artwork/swap2-native/zelda-40'
    PROFILE = ROOT / 'android/app/src/main/java/dev/nxnative/android/TouchProfile.java'
    CONTROLS = ROOT / 'android/app/src/main/java/dev/nxnative/android/TouchControls.java'
    # The handoff's table: sprite -> (the Zelda profile's existing control ID, guest bit)
    BUTTONS = {'a': ('face_a', 1), 'b': ('face_b', 2), 'x': ('slot_x', 4), 'y': ('slot_y', 8), 'l3': ('left_click', 16), 'r3': ('right_click', 32),
               'l': ('shoulder_left', 64), 'r': ('shoulder_right', 128), 'zl': ('trigger_left', 256), 'zr': ('trigger_right', 512),
               'plus': ('plus', 1024), 'minus': ('minus', 2048)}
    STICKS = {'left_stick_base': ('move', 0), 'right_stick_base': ('camera', 1)}

    def zelda_items(self):
        source = self.PROFILE.read_text(encoding='utf-8')
        return group1(r'StandardItem\[\] ZELDA40 = \{(.*?)\n    \};', source, re.S)

    def test_bundled_atlas(self):
        bundled = ROOT / 'android/app/src/main/res/drawable-nodpi/s2_zelda40_controls.png'
        self.assertEqual(bundled.read_bytes(), (self.ART / 'zelda-40-touch-atlas-v1.png').read_bytes())
        manifest = json.loads((self.ART / 'sprites-v1.json').read_text(encoding='utf-8'))
        self.assertEqual(png_size(bundled), (manifest['width'], manifest['height']))
        self.assertEqual(png_size(bundled), (1263, 1245))
        # The old Zelda atlas stays bundled for compatibility
        self.assertTrue((ROOT / 'android/app/src/main/res/drawable-nodpi/s2_zelda_controls.png').is_file())

    def test_sprite_table_matches_manifest(self):
        manifest = json.loads((self.ART / 'sprites-v1.json').read_text(encoding='utf-8'))
        source = self.PROFILE.read_text(encoding='utf-8')
        ids = re.findall(r'"([a-z0-9_]+)"', group1(r' SPRITE_IDS = \{(.*?)\};', source, re.S))
        rects = [list(map(int, m)) for m in re.findall(r'\{(\d+), (\d+), (\d+), (\d+)\}', group1(r'ZELDA40_SPRITE_RECTS = \{(.*?)\n    \};', source, re.S))]
        self.assertEqual(ids, list(manifest['sprites']))
        self.assertEqual(rects, [manifest['sprites'][i]['rect_px'] for i in ids])
        self.assertIn(f"ZELDA40_ATLAS_W = {manifest['width']}, ZELDA40_ATLAS_H = {manifest['height']}", source)
        for i, (l, t, r, b) in zip(ids, rects):
            with self.subTest(sprite=i):
                self.assertTrue(0 <= l < r <= manifest['width'] and 0 <= t < b <= manifest['height'])

    def test_layout_matches_reference(self):
        reference = json.loads((self.ART / 'layout-reference-v1.json').read_text(encoding='utf-8'))
        self.assertEqual((reference['profile_id'], reference['title_id'], reference['skin_id']), ('zelda-oot', '0400486024DEC000', 'zelda-40'))
        source = self.PROFILE.read_text(encoding='utf-8')
        items = self.zelda_items()
        self.assertIn(f'ZELDA40_REF_W = {reference["reference_canvas"][0]}, ZELDA40_REF_H = {reference["reference_canvas"][1]}', source)
        self.assertRegex(source, r'new Skin\("zelda-40", [^;]*?, ' + re.escape(f'{reference["default_opacity"]:g}') + r'f,')
        controls = {c['sprite']: c for c in reference['controls']}
        def num(v): return f'{v:g}' + ('f' if v != int(v) else '')
        for sprite, control in controls.items():
            (x, y), (w, h), anchor = control['center_ref'], control['size_ref'], control['anchor'].upper()
            with self.subTest(sprite=sprite):
                if not control['enabled_initially']:
                    self.assertNotIn(f'"{sprite}"', items)   # Capture, Home, C: hidden, no invented bits
                elif sprite in self.BUTTONS:
                    action, bit = self.BUTTONS[sprite]
                    self.assertIn(f'zb("{action}", "{sprite}", {bit}, ANCHOR_{anchor}, {num(x)}, {num(y)}, {w:g}, {h:g})', items)
                elif sprite in self.STICKS:
                    action, stick = self.STICKS[sprite]
                    self.assertIn(f'new StandardItem("{action}", "{sprite}", 1, 0, {stick}, ANCHOR_{anchor}, {num(x)}, {num(y)}, {num(w / 2)}, {num(h / 2)})', items)
                elif sprite in ('visibility', 'settings'):
                    self.assertIn(f'new StandardItem("{sprite}", "{sprite}", STANDARD_APP, 0, 0, ANCHOR_{anchor}, {num(x)}, {num(y)}, {num(w / 2)}, {num(h / 2)})', items)
        # Caps: same centre as their base, cap / base and the 28-unit travel
        for side in ('left', 'right'):
            base, cap = controls[f'{side}_stick_base'], controls[f'{side}_stick_cap']
            self.assertEqual(base['center_ref'], cap['center_ref'])
            self.assertIn(f'ZELDA40_CAP = {cap["size_ref"][0]}f / {base["size_ref"][0]}f, ZELDA40_STICK_TRAVEL = 28f / {base["size_ref"][0] // 2}f', source)
        # D-pad: the four measured centres (up, right, down, left), one region at their bounding box's centre with its largest half extent
        dpad = [controls[d] for d in ('up', 'right', 'down', 'left')]
        table = group1(r'ZELDA40_DPAD = \{(.*?)\};', source)
        self.assertEqual([list(map(float, m)) for m in re.findall(r'\{([\d.]+), ([\d.]+)\}', table)], [list(map(float, d['center_ref'])) for d in dpad])
        self.assertTrue(all(d['size_ref'] == [90, 90] and d['anchor'] == 'left' for d in dpad))
        self.assertIn('ZELDA40_DPAD_SIZE = 90', source)
        x0 = min(d['center_ref'][0] - 45 for d in dpad); x1 = max(d['center_ref'][0] + 45 for d in dpad)
        y0 = min(d['center_ref'][1] - 45 for d in dpad); y1 = max(d['center_ref'][1] + 45 for d in dpad)
        half = max(x1 - x0, y1 - y0) / 2
        self.assertIn(f'new StandardItem("directions", "", 2, 0xf000, 0, ANCHOR_LEFT, {num((x0 + x1) / 2)}, {num((y0 + y1) / 2)}, {num(half)}, {num(half)})', items)

    def test_routing(self):
        profile = self.PROFILE.read_text(encoding='utf-8')
        controls = self.CONTROLS.read_text(encoding='utf-8')
        self.assertIn('return CLASSIC.equals(profile) ? STANDARD_SKIN : ZELDA.equals(profile) ? ZELDA40_SKIN : null;', profile)
        self.assertIn('s == TouchProfile.ZELDA40_SKIN ? dev.nxnative.android.R.drawable.s2_zelda40_controls : dev.nxnative.android.R.drawable.s2_standard_controls_v2', controls)
        self.assertIn('options.inScaled = false', controls)
        # The old action-icon indices never address the anniversary atlas, and are never erased
        self.assertNotIn('getInt(setting("zelda_icon_', controls)
        self.assertNotIn('remove(setting("zelda_icon_', controls)
        self.assertNotIn('s2_zelda_controls', controls)
        for strings in (ROOT / 'android/app/src/main/res').glob('values*/strings.xml'):
            with self.subTest(strings=strings.parent.name):
                self.assertIn('name="s2_zelda40_hint"', strings.read_text(encoding='utf-8'))


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
class TouchProfileTest(unittest.TestCase):
    def test_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            sources = [ROOT / 'android/app/src/main/java/dev/nxnative/android/TouchProfile.java',
                       ROOT / 'android/app/src/jvmtest/java/dev/nxnative/android/TouchProfileJvmTest.java']
            subprocess.run(['javac', '-Xlint:all', '-Werror', '-d', directory, *map(str, sources)], check=True, capture_output=True)
            run = subprocess.run(['java', '-cp', directory, 'dev.nxnative.android.TouchProfileJvmTest'], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

if __name__ == '__main__':
    unittest.main()
