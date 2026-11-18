"""The optional UI must reach the production gate without altering178 defaults."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'android/app/src/main'


class GPUVisibilityOption(unittest.TestCase):
    def test_option_default_and_native_environment_match(self):
        prefs = (APP / 'java/dev/nxnative/android/Prefs.java').read_text()
        self.assertIn('getBoolean(gameKey("gpu_visibility", titleId), false)', prefs)
        self.assertIn('putBoolean(gameKey("gpu_visibility", titleId), on)', prefs)
        game = (APP / 'java/dev/nxnative/android/GameActivity.java').read_text()
        self.assertIn('"DM_VK_GPU_VISIBILITY=" + (Prefs.gpuVisibility(this, id) ? "1" : "0")', game)
        source = (ROOT / 'dm/gfx/vk_android/vka_rc_gpu.inc').read_text()
        self.assertIn('VKA_ENV("DM_VK_GPU_VISIBILITY", 0)', source)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', source)
        settings = (APP / 'java/dev/nxnative/android/GameSettings.java').read_text()
        self.assertIn('.toggle(a, Prefs.gpuVisibility(a, id)', settings)
        self.assertIn('R.string.s2_gpu_visibility_note', settings)
        # 0.1.9 routes Ocarina to this dedicated compact page, not the old
        # graphics() list. An old hidden switch is not a user-visible option.
        start = settings.index('private static void graphicsOcarina019(')
        end = settings.index("/** The APK's assets", start)
        page = settings[start:end]
        self.assertIn('a.getString(R.string.s2_gpu_visibility)', page)
        self.assertIn('.toggle(a, Prefs.gpuVisibility(a, id)', page)
        self.assertIn('gpuVisibility.value(a.getString(R.string.s2_gpu_visibility_note))', page)
        self.assertIn('box.addView(gpuVisibility.view)', page)
        self.assertLess(page.index('box.addView(mist.view)'), page.index('box.addView(gpuVisibility.view)'))
        self.assertLess(page.index('box.addView(gpuVisibility.view)'), page.index('box.addView(ram.view)'))
        self.assertIn('.remove(Prefs.gameKey("gpu_visibility", id))', settings)
        # The launcher passes BOTH states, not merely the enabled state.
        self.assertIn('Prefs.gpuVisibility(this, id) ? "1" : "0"', game)

    def test_supported_translations_exist_once_and_preserve_resource_validity(self):
        for directory in ('values', 'values-pt', 'values-tr', 'values-pl', 'values-ru'):
            with self.subTest(directory=directory):
                tree = ET.parse(APP / 'res' / directory / 'strings.xml')
                for key in ('s2_gpu_visibility', 's2_gpu_visibility_note'):
                    matches = tree.findall(f'./string[@name="{key}"]')
                    self.assertEqual(len(matches), 1)
                    self.assertTrue(matches[0].text)


if __name__ == '__main__':
    unittest.main()
