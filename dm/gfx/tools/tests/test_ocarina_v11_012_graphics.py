"""V11 iOS: source integration checks for the no-guest-shader-rebuild 0.1.2 options."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"
VK = ROOT / "dm/gfx/vk_android/vka_present.c"
UI = (JAVA / "MainActivity.java").read_text()
GAME = (JAVA / "GameSettings.java").read_text()
LAUNCH = (JAVA / "GameActivity.java").read_text()
SIDE = (JAVA / "SidePanel.java").read_text()
OPTS = (JAVA / "GraphicsOptions.java").read_text()
FSR = (JAVA / "Fsr.java").read_text()
TOUCH = (JAVA / "TouchControls.java").read_text()
PRESENT = VK.read_text()
WF = (ROOT / ".github/workflows/ocarina-v11-ios-apk.yml").read_text()


class V11Graphics012Tests(unittest.TestCase):
    def test_global_and_game_overrides(self):
        for key in ("present_filter", "picture_stretch", "bg_pipelines", "fsr_sharp"):
            self.assertIn('"' + key + '"', OPTS)
            self.assertIn('"' + key + '"', GAME)
        # 0.1.6 keeps timestamps as an internal diagnostic setting, not a
        # redundant game menu choice.
        self.assertIn('"gpu_timestamps"', OPTS)
        self.assertNotIn('"gpu_timestamps"', GAME)
        self.assertIn('DM_VK_OOT_HOTPASS_VRS=" + hotpassVrs(c, id)', OPTS)
        self.assertIn("GraphicsOptions.reset(a, id)", GAME)
        self.assertIn('GraphicsOptions.choice(this, null, "present_filter"', UI)
        self.assertIn('GraphicsOptions.choice(a, id, "present_filter"', GAME)

    def test_modes_reach_vulkan_without_game_shader_translation(self):
        self.assertIn('DM_VK_PRESENT_FILTER=', OPTS)
        self.assertIn('DM_VK_PICTURE_STRETCH=', OPTS)
        self.assertIn('DM_VK_FSR=', OPTS)
        self.assertIn('int nearest = present_filter == 1;', PRESENT)
        self.assertIn('!nearest &&', PRESENT)
        self.assertIn('stretch ? ew', PRESENT)
        self.assertIn('GraphicsOptions.env(this, id, env)', LAUNCH)
        self.assertLess(LAUNCH.index('GraphicsOptions.env(this, id, env)'), LAUNCH.index('env.addAll(user)'))
        self.assertIn('GraphicsOptions.rows(act, box, game())', SIDE)

    def test_fsr_sharpness_off_is_neutral_rcas(self):
        self.assertIn('SHARPS = {-1f, 0f, 0.25f, 0.5f, 1f}', FSR)
        self.assertIn('sharp < 0 ? 0.0f : exp2f(-sharp)', PRESENT)
        self.assertIn('SHARPS = {-1f, 0f, 0.25f, 0.5f, 1f}', OPTS)

    def test_touch_coordinates_match_stretch(self):
        self.assertIn('GraphicsOptions.stretch(getContext(), gameTitleId)', TOUCH)
        self.assertIn('new float[] {0f, 0f, 1f, 1f}', TOUCH)
        self.assertIn('VKA_ENV("DM_VK_PICTURE_STRETCH", 0)', PRESENT)

    def test_pipeline_and_timestamp_options(self):
        self.assertIn('DM_VK_GPL=0', OPTS)
        self.assertIn('DM_VK_PREWARM=0', OPTS)
        self.assertIn('DM_NVN_GPU_TS=', OPTS)
        self.assertIn('"segment" : "submission"', OPTS)

    def test_preserve_ios_v11_update_contract(self):
        self.assertIn('branches: [ocarina-v11-ios-perf-from-v101', WF)
        self.assertIn('-PnxApp=ootv11ios', WF)
        self.assertIn('com.swap2native.ootv11ios', WF)
        self.assertIn('key: swap2-ootv11ios-test-signing-v1', WF)
        self.assertIn('Refusing to generate an incompatible signer', WF)
        self.assertIn('a1c468aff0b99e28c001991c94e7f1f5373493deb26e822b54a335801a76f4ad', WF)
        self.assertIn('-PnxVersionCode="$GITHUB_RUN_NUMBER"', WF)
        self.assertIn('ci/ocarina-ios-ready.txt', WF)


if __name__ == "__main__":
    unittest.main()
