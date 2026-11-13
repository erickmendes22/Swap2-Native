"""First-time Ocarina translation and allocation-failure correctness guards."""
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[4]
P=(R/"android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
V=(R/"dm/gfx/tools/vk_android_build.py").read_text()
T=(R/"dm/gfx/vk_android/vka_tex.c").read_text()
ZIP=(R/"android/app/src/main/java/dev/nxnative/android/ShaderZip.java").read_text()
LIBS=(R/"android/app/src/main/java/dev/nxnative/android/ShaderLibs.java").read_text()
VK=(R/"dm/gfx/vk_android/vka_shader.c").read_text()
class ColdShaderBuild(unittest.TestCase):
    def test_strict_all_keys_cold_or_rebuild(self):
        self.assertIn('DMSH_VK_OOT_COLD_RETRY',P)
        self.assertIn('ocarinaShaders && hotKeys.isEmpty() ? "1" : "0"',P)
        self.assertIn('PackEngine.setenv("DMSH_VK_REQUIRE_ALL", "1")',P)
        self.assertIn("once = translate([jobs[key]], bd, 'cold_retry_' + key)",V)
        self.assertIn("if once.returncode == 0 and os.path.isfile(sp)",V)
        self.assertIn("xerr.pop(key, None)",V)
        self.assertIn("if _bad and os.environ.get('DMSH_VK_REQUIRE_ALL') == '1':",V)
        self.assertIn("no library written (DMSH_VK_REQUIRE_ALL)",V)
        self.assertIn("for key in batch:",V)
    def test_baseline_012_import_keeps_real_version_and_exact_binary_abi(self):
        # GitHub Actions 42917509914 (2026-11-10) compiled 42k
        # shaders with chain b6b21fb5753a, same ABI as current v0.1.6.
        # Never forge its header into the later 31f38178d067 version.
        self.assertIn('"b6b21fb5753a"', LIBS)
        self.assertIn('OCARINA_BASE_ENTRIES = 42339', LIBS)
        self.assertIn('entries == OCARINA_BASE_ENTRIES', LIBS)
        self.assertIn('h.fits(file.length()) && titleId.equals(h.game)', LIBS)
        self.assertIn('expectedAbi.equals(abi)', LIBS)
        self.assertIn('expectedInputs.equals(inputs)', LIBS)
        self.assertIn('&& !compatibleOcarinaBase()', ZIP)
        self.assertIn('boolean keepBaseline = ShaderLibs.trustedOcarinaBase', ZIP)
        self.assertIn('if (!s.version.equals(t.current) && !keepBaseline && !s.fragmentPatch)', ZIP)
        self.assertIn('ShaderLibs.trustedOcarinaBase(packDir, titleId', ZIP)
        self.assertIn('"v-b6b21fb5753a"', VK)

    def test_cold_build_does_not_modify_known_good_shader_translation(self):
        # The only new SPIR-V ALU pass in v0.1.6 belongs to intentional
        # captured-only repairs, never the complete 42k reference.
        self.assertIn("and bool(want)  # NEVER rewrite the first complete", V)
        self.assertIn("if want:\n    captured_oot_records(want", V)
        self.assertIn("if _bad and os.environ.get('DMSH_VK_REQUIRE_ALL') == '1':", V)
        self.assertIn("lib, size = write_library(results, publish=False)", V)
        self.assertIn("missing = set(keys) - set(_hashes)", V)
        self.assertIn("if missing or len(_hashes) < 40000:", V)
        self.assertIn("if _bad:\n        sys.exit(f'[RED] {_bad} shader hashes", V)
        self.assertIn("os.replace(lib, installed)", V)
        self.assertLess(V.index("lib, size = write_library(results, publish=False)"),
                        V.index("progress('check')"))
        self.assertLess(V.index("progress('check')"),
                        V.index("if not want and GAME.id == '0400486024DEC000':"))
        self.assertLess(V.index("if not want and GAME.id == '0400486024DEC000':"),
                        V.index("os.replace(lib, installed)"))

    def test_realloc_failure_keeps_resident_textures(self):
        self.assertIn('vka_img **tmp = cap ? realloc(g_live',T)
        self.assertIn('if (!tmp)',T)
        self.assertIn('img_destroy(im);',T)
        # The RAM cache now records last-use/fence values inside an im guard.
        # Preserve the important invariant: failed realloc never publishes the image.
        self.assertIn('if (im) {\n        __atomic_store_n(&im->last_frame',T)
        self.assertIn('map_put(t->serial, im);',T)
        self.assertIn('vka_tex_prune_locked();',T)
        self.assertNotIn('g_live = realloc(g_live, (size_t)g_livecap',T)
if __name__=="__main__":unittest.main()
