"""Regression guards for Snapdragon 8 Elite native Vulkan probe crash avoidance.

The probe MUST be in another Android process so Vulkan driver teardown cannot
poison the game's future Vulkan state or terminate :game before game logging.
The Gradle APK job provides the actual Java and Manifest compilation gate.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"

class IsolatedReadiness(unittest.TestCase):
    def test_probe_process_is_dedicated_and_private(self):
        xml = MANIFEST.read_text()
        self.assertRegex(xml, r'(?s)<provider\s+android:name="\.GpuProbeProvider".*?android:exported="false"\s+android:process=":gpu_probe"\s*/>')
        self.assertIn('android:process=":game"', xml)
        self.assertIn('android:authorities="${applicationId}.gpu_probe"', xml)

    def test_game_process_does_not_probe_vulkan(self):
        game = (JAVA / "GameActivity.java").read_text()
        self.assertIn('getContentResolver().call(GpuProbeProvider.uri(this)', game)
        self.assertNotIn('Native.readiness(denv)', game)
        self.assertIn('GPU_READINESS_DECIDE_EXCEPTION', game)
        self.assertIn('GPU_READINESS_BEGIN isolated=true', game)

    def test_isolated_process_loads_correct_game_and_driver_env(self):
        src = (JAVA / "GpuProbeProvider.java").read_text()
        self.assertIn('Native.load(title)', src)
        self.assertIn('Native.readiness(extras.getStringArray("env"))', src)
        self.assertIn('context.getPackageName() + ".gpu_probe"', src)
        self.assertIn('unchecked=isolated Vulkan readiness failed', src)

if __name__ == "__main__":
    unittest.main()
