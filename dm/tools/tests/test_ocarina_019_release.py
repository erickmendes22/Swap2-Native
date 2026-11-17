"""0.1.9 release regression: UI, signed launch flags, patches and shader flows."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"
PACK = ROOT / "android/app/src/ondevice/java/dev/nxnative/android"

class Ocarina019(unittest.TestCase):
    def test_curated_graphics_page_and_independent_controls(self):
        txt = (JAVA / "GameSettings.java").read_text()
        start = txt.index("private static void graphicsOcarina019(")
        end = txt.index("/** The APK's assets", start)
        page = txt[start:end]
        for item in ("Reduzir custos de vegetação", "Reduzir neblina do chão",
                     "Economia de RAM", "Shared buffer", "oot_hotpass_vrs",
                     "renderProfile(a, g, again)", "fpsPatches(a, g, again)",
                     "builtinMods(a, g, box)", "s2_frame_cap"):
            self.assertIn(item, page)
        for hidden in ("feedbackInvocationCache", "ootDepthStoreNone",
                       "gpuPageIndex", "unusedColorTargets", "attachmentWriteScopes",
                       "computeOptimized", "keepCaveWalls", "shadowMaps(a, g"):
            self.assertNotIn(hidden, page)
        self.assertIn("graphicsOcarina019(a, g, p, again);", txt)
        self.assertIn("setMultiChoiceItems(labels, checked", txt)
        self.assertIn("startEffectProbe(a, g.titleId", txt)
        self.assertNotIn('Mapas de sombra (RomFS)', page)

    def test_four_internal_paths_always_on_without_toggles(self):
        a = (JAVA / "GameActivity.java").read_text()
        for flag in ("DM_VK_GMEM_PIDX=1", "DM_VK_UNUSED_COLOR=1",
                     "DM_VK_ATTACHMENT_PARTS=1", "DM_VK_OOT_CS_RETILE=1",
                     "DM_VK_MEMU_DIRECT_PAYLOAD=1"):
            self.assertIn(flag, a)
        self.assertIn("Prefs.gpuSharedBuffer(this, id)", a)
        self.assertIn("Prefs.ramSaver(this, id)", a)

    def test_fps_combination_is_actual_overlay_not_just_ui(self):
        gui = (JAVA / "GameSettings.java").read_text()
        svc = (PACK / "SceneService.java").read_text()
        overlay = (JAVA / "ShadowOverlay.java").read_text()
        script = (ROOT / "dm/tools/gsys_shadow.py").read_text()
        self.assertIn("SceneService.startGraphics(a, id", gui)
        self.assertIn("ShadowOverlay.currentMask", gui)
        self.assertIn("ShadowOverlay.currentMask", (JAVA / "GameActivity.java").read_text())
        self.assertIn("--effects-mask", script)
        self.assertIn("--effects-mask", overlay)
        self.assertIn("oot_post_effects", script)
        self.assertIn("oot_ssao_samples", script)
        self.assertIn("SceneService.graphicsVersion", gui)
        self.assertIn("static void startGraphics(", svc)
        self.assertNotIn("CreateDof', D_BOOL, 1, 0", script)
        self.assertNotIn("CreateBloom', D_BOOL, 1, 0", script)

    def test_full_preparation_includes_vegetation_and_import_both_counts(self):
        service = (PACK / "PackService.java").read_text()
        delta = (PACK / "OcarinaShaderDelta.java").read_text()
        prep = (PACK / "Ondevice.java").read_text()
        libs = (JAVA / "ShaderLibs.java").read_text()
        zip_src = (JAVA / "ShaderZip.java").read_text()
        self.assertIn('j.hotKeys(vegetationKeys);', service)
        self.assertIn('j.stepState("shaders", "pending");', service)
        self.assertIn("completeVegetationInstalled(", service)
        self.assertIn("vegetationKeyInstalled(", delta)
        self.assertIn("vegetationMissing", prep)
        self.assertIn("OCARINA_VEGETATION_ENTRIES = 508", libs)
        self.assertIn("isFullOcarinaCount(h.entries)", zip_src)

    def test_language_auto_and_plain_movies_default_on(self):
        language = (JAVA / "AppLanguage.java").read_text()
        mod = (ROOT / "dm/games/0400486024DEC000/mods/plain-movie-player/mod.tsv").read_text()
        self.assertIn('"", "en-US", "pt-BR"', language)
        self.assertIn('"System / Automático"', language)
        self.assertIn('if (code.isEmpty()) return base;', language)
        self.assertIn("android_default\\ton", mod)

if __name__ == "__main__":
    unittest.main()
