# Ocarina V10.1 — regression tests for two independent runtime paths.
# This test is source-level only; the native host and NativeAOT translator
# are also compiled by GitHub Actions.
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
NVN = ROOT / 'dm/gfx/nvn/hle_nvn.c'
SERVICE = ROOT / 'android/app/src/ondevice/java/dev/nxnative/android/PackService.java'

class OcarinaV101(unittest.TestCase):
    def test_host_ocarina_hold_default_off_with_explicit_override(self):
        s = NVN.read_text()
        self.assertIn('int ocarina = id && !strcmp(id, "0400486024DEC000");', s)
        self.assertIn('h = e ? strcmp(e, "off") != 0 : ocarina ? 0 : DM_GAME_FPS_HOLD;', s)
        self.assertIn('Ocarina V3 timing fix', s)
    def test_mobile_shader_step_receives_gmem_selection(self):
        s = SERVICE.read_text()
        self.assertIn('PackEngine.setenv("DMSH_GMEM_FAST1", "shaders".equals(s) && "0400486024DEC000".equals(j.titleId()) ? "1" : "0");', s)
        self.assertLess(s.index('PackEngine.setenv("DMSH_GMEM_FAST1"'),s.index('applyEnvFile(j, log);'))
if __name__ == '__main__':
    unittest.main()
