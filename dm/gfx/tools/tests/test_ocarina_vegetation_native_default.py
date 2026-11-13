"""Regression guard: Qualcomm Ocarina foliage must avoid corrupt native mesh.

Although Adreno 891.14 advertises meshShader+taskShader, the native path
draws Ocarina foliage as white wireframe/triangles. The app must route
supplemental foliage to compute, preserving original-library native mesh
via the existing hybrid policy and keeping vegetation-OFF fast.

This test checks the literal production capability selection and the runtime
rollback switch, plus the 508-key supplement path. It cannot establish GPU
FPS or prove every new shader compiles on every Vulkan implementation.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"


class NativeFoliageDefault(unittest.TestCase):
    def test_qualcomm_avoids_broken_native_foliage_in_ocarina(self):
        dev = (VK / "vka_dev.c").read_text()
        m = re.search(r'V\.memu\s*=\s*e\s*&&\s*\*e\s*\?\s*strcmp\(e,\s*"0"\)\s*!=\s*0\s*:\s*([^;]+);', dev)
        self.assertIsNotNone(m)
        default = m.group(1).strip()
        self.assertEqual(default, '(!V.task || qcom_ocarina || route == 1)')
        self.assertIn('VKA_ENV("DM_VK_OOT_MESH_ROUTE", 0)', dev)
        # A missing user override is still hybrid, and only explicit
        # all-compute mode 1 modifies the emulation default.
        self.assertIn('route == 1', default)
        self.assertIn('const int qcom_ocarina = V.driver_id == VK_DRIVER_ID_QUALCOMM_PROPRIETARY', dev)
        self.assertIn('!strcmp(DM_GAME_ID, "0400486024DEC000")', dev)
        self.assertIn('getenv("DM_VK_MESH_EMU")', dev)
        self.assertIn('hybrid original-native/supplement-compute', dev)

    def test_supplement_still_loads_with_native_driver(self):
        shader = (VK / "vka_shader.c").read_text()
        draw = (VK / "vka_draw.c").read_text()
        self.assertIn('vegetation_complete(&g_vegetation, &g_lib)', shader)
        self.assertIn('verified original task/mesh shaders', shader)
        self.assertIn('vka_shlib_spirv(s->lib, m, &nb', shader)
        self.assertIn('if (!hybrid && vegetation_on) return V.memu ? 1 : 0;', draw)
        self.assertIn('if (supplement && !vegetation_on) return -1;', draw)
        self.assertIn('return hybrid ? (supplement ? 1 : 0) : (V.memu ? 1 : 0);', draw)

    def test_legacy_compute_remains_explicit_rollback(self):
        dev = (VK / "vka_dev.c").read_text()
        self.assertIn('V.memu = e && *e ? strcmp(e, "0") != 0 :', dev)
        self.assertIn('(!V.task || qcom_ocarina || route == 1)', dev)
        memu = (VK / "vka_memu_draw.inc").read_text()
        self.assertIn('vka_memu_batch(int phase', memu)
        self.assertIn('case MEMU_MESH:', memu)


if __name__ == "__main__":
    unittest.main()
