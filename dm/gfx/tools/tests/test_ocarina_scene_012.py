"""Ocarina 0.1.2: internal scene scaling is a real RomFS palette patch, not output blit."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
APP = ROOT / "android/app/src/main/java/dev/nxnative/android"
PREFS = (APP / "Prefs.java").read_text()
UI = (APP / "GameSettings.java").read_text()
RUN = (APP / "GameActivity.java").read_text()
SERVICE = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/SceneService.java").read_text()
DYN = (ROOT / "dm/tools/gsys_dynres.py").read_text()
PRESENT = (ROOT / "dm/gfx/vk_android/vka_present.c").read_text()
PACK = (APP / "Pack.java").read_text()
SHADERS = (APP / "ShaderLibs.java").read_text()


class InternalSceneResolution(unittest.TestCase):
    def test_scene_scale_choices_are_internal(self):
        for k in ('"0.6133"', '"0.46875"', '"0.4166667"', '"0.3125"'):
            self.assertIn(k, PREFS)
        for label in ("720p", "540p", "480p", "360p"):
            self.assertIn(label, PREFS)
        self.assertIn("Prefs.OCARINA_SCENE_SCALES[w - 1]", UI)
        self.assertIn("SceneService.start(a, id, in[1], scale, expect, in[0]", UI)
        self.assertIn("ap.add_argument('--scale'", DYN)
        self.assertIn("DynamicResolutionParam", DYN)
        self.assertIn("ResolutionReduceScale", DYN)

    def test_existing_four_scene_choices_are_unchanged_and_sgsr_is_shader_driven(self):
        # The user explicitly chose to KEEP the original resolutions:
        # 720p 0.6133, 540p 0.46875, 480p 0.4166667,
        # and 360p 0.3125. The iOS 0.25/0.6/0.75 values denote
        # game-internal network variants, not new launcher resolutions.
        self.assertIn('{"0.6133", "0.46875", "0.4166667", "0.3125"}', PREFS)
        self.assertNotIn('"0.25"', PREFS)
        self.assertNotIn('"0.6"', PREFS)
        self.assertNotIn('"0.75"', PREFS)
        self.assertIn("Prefs.OCARINA_SCENE_NAMES", UI)
        self.assertIn("Prefs.OCARINA_SCENE_SCALES[w - 1]", UI)
        self.assertIn("Prefs.setSceneScale(a, id, scale)", UI)
        self.assertIn("SceneOverlay.current(files, id, scale, expect, in[0])", UI)
        self.assertIn("if scale != 0.6133", DYN)
        self.assertIn("else lambda v: scale", DYN)
        self.assertIn('gameKey("scene_scale", titleId), profileScale', PREFS)
        self.assertIn('for (String s : OCARINA_SCENE_SCALES) if (s.equals(v)) return v;', PREFS)
        n = (ROOT / "dm/gfx/vk_android/vka_ndsr.c").read_text()
        self.assertIn('cs->key == UINT64_C(0xb106afba1a18faa9)', n)
        self.assertIn('cs->key == UINT64_C(0xfa3033d05c0a41d6)', n)
        self.assertIn('VKA_ENV("DM_VK_OOT_SGSR_CHAIN", 0)', n)

    def test_separate_intermediate_and_final_filters(self):
        self.assertIn("Reconstrução da cena (GPU)", UI)
        self.assertIn("Filtro da tela (não reduz render)", UI)
        self.assertIn("Resolução interna da cena (GPU)", UI)
        self.assertIn("DM_VK_PRESENT_FILTER", PRESENT)

    def test_no_default_change_and_overlay_stamped(self):
        self.assertIn('gameKey("scene_scale", titleId), profileScale', PREFS)
        self.assertIn("static void setSceneScale(Context c, String titleId, String v)", PREFS)
        self.assertNotIn("static void sceneScale(Context c, String titleId, String v)", PREFS)
        self.assertIn("sceneWanted(id, scale)", UI)
        self.assertIn("Prefs.setSceneScale(a, id, scale)", UI)
        self.assertIn("Prefs.sceneScale(this, id, prof.sceneScale())", RUN)
        self.assertIn("SceneOverlay.stampText(scale, expect, version)", SERVICE)
        self.assertIn("internal render scene scale", RUN)
        # The original 720p palette remains bounded in the patcher, while all
        # lower scales are set uniformly: otherwise changing resolution had no effect.
        self.assertIn("if scale != 0.6133", DYN)
        self.assertIn("else lambda v: scale", DYN)

    def test_reuse_previous_library_with_matching_abi(self):
        self.assertIn("File compatible = playableLibrary(dir, titleId);", PACK)
        self.assertIn("if (compatible != null) return null;", PACK)
        self.assertIn("!h.fits(lib.length())", SHADERS)
        self.assertIn("!titleId.equals(h.game)", SHADERS)
        self.assertIn("!abi.equals(h.abi)", SHADERS)
        self.assertIn("but none matches the game's required ABI", PACK)

    def test_scene_status_reports_selected_dynamic_scale(self):
        self.assertIn("Prefs.sceneLabel(scale)", UI)
        self.assertIn("tamanho dinâmico", UI)
        self.assertIn("480p nominal", PREFS)
        self.assertIn("360p nominal", PREFS)

    def test_larger_scene_is_cheaper_only_if_bound_by_pixels(self):
        # Relative pixel workloads; measured GPU savings need a phone benchmark.
        src = 1275 * 717
        for dims in ((960, 540), (853, 480), (640, 360)):
            self.assertLess(dims[0] * dims[1], src)


if __name__ == "__main__":
    unittest.main()
