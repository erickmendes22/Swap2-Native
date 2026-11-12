"""The emulator's Play action must NEVER call a blocking Vulkan readiness probe."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
JAVA = ROOT / "android/app/src/main/java/dev/nxnative/android"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"

class NoAutomaticGPUPreflight(unittest.TestCase):
    def test_all_devices_go_directly_to_native_host(self):
        s = (JAVA / "GameActivity.java").read_text()
        self.assertIn("GPU_PREFLIGHT_DISABLED_ALL_DEVICES", s)
        self.assertIn("Native.start(args, env.toArray", s)
        self.assertLess(s.index("GPU_PREFLIGHT_DISABLED_ALL_DEVICES"), s.index("Native.start(args, env.toArray"))
        for gone in ("readinessHold(", "readinessDecide(", "Native.readiness(", "GpuProbeProvider",
                     "GPU_READINESS_DIALOG_SHOWN", "GPU_READINESS_BYPASS_SM8750"):
            self.assertNotIn(gone, s)
    def test_manual_probe_is_preserved_only_in_its_own_process(self):
        self.assertIn("Native.readiness(", (JAVA / "ReadinessActivity.java").read_text())
        xml = MANIFEST.read_text()
        self.assertIn('android:process=":readiness"', xml)
        self.assertNotIn("GpuProbeProvider", xml)

if __name__ == "__main__":
    unittest.main()
