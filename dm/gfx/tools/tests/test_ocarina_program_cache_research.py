"""Research only: check program-serial collision experiment has no shader ABI change."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
SRC = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
class ProgramCacheResearch(unittest.TestCase):
    def test_default_is_64_and_option_is_512(self):
        self.assertIn("static unsigned g_pm_mask = 63;", SRC)
        self.assertIn('VKA_ENV("DM_VK_PROG_CACHE_512", 0) ? 511u : 63u', SRC)
        self.assertIn("g_pm[512];", SRC)
    def test_same_serial_keys_and_slow_fallback(self):
        f=SRC.split("static int resolve(const prog_t *p,",1)[1].split(
            "// A predicated block",1)[0]
        self.assertIn("if (sr && m->serial == sr)",f)
        self.assertIn("if (!vka_prog_shaders(p, &ps)) return 0;",f)
        self.assertIn("if (sr) { m->serial = sr; m->ps = ps; }",f)
        self.assertIn("ps.bad & (1u << st | VKA_BAD_MISSING)",f)
        self.assertIn("ps.sh[st]",f)
        self.assertNotIn("getenv(",f)
    def test_default_production_shader_abi_untouched(self):
        self.assertIn('VLOG("Ocarina program-serial cache: slots=%u', SRC)
        self.assertIn('g_pm_diag = VKA_ENV("DM_VK_PROG_CACHE_DIAG", 0) != 0;', SRC)
if __name__ == "__main__":
    unittest.main()
