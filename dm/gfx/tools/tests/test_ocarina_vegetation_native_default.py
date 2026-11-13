"""Regression guard: Qualcomm with meshShader+taskShader must run native foliage.

Unlike the earlier global Qualcomm compute-emulation override (which made
foliage ON ~20 FPS slower than OFF), Banana Native and the working original
renderer default to native VK_EXT_mesh_shader whenever taskShader exists.
The user's Adreno 891.14 driver reports mesh=1 and task=1.

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
    def test_qualcomm_uses_mesh_hardware_like_reference_banana(self):
        dev = (VK / "vka_dev.c").read_text()
        m = re.search(r'V\.memu\s*=\s*e\s*&&\s*\*e\s*\?\s*strcmp\(e,\s*"0"\)\s*!=\s*0\s*:\s*([^;]+);', dev)
        self.assertIsNotNone(m)
        default = m.group(1).strip()
        self.assertEqual(default, '!V.task')
        self.assertNotIn('VK_DRIVER_ID_QUALCOMM_PROPRIETARY', default)
        self.assertIn('getenv("DM_VK_MESH_EMU")', dev)
        self.assertIn('native VK_EXT_mesh_shader', dev)

    def test_supplement_still_loads_with_native_driver(self):
        shader = (VK / "vka_shader.c").read_text()
        draw = (VK / "vka_draw.c").read_text()
        self.assertIn('vegetation_complete(&g_vegetation, &g_lib)', shader)
        self.assertIn('508 verified original task/mesh shaders', shader)
        self.assertIn('vka_shlib_spirv(s->lib, m, &nb', shader)
        self.assertIn('if (!hybrid && vegetation_on) return V.memu ? 1 : 0;', draw)
        self.assertIn('if (supplement && !vegetation_on) return -1;', draw)
        self.assertIn('return hybrid ? (supplement ? 1 : 0) : (V.memu ? 1 : 0);', draw)

    def test_legacy_compute_remains_explicit_rollback(self):
        dev = (VK / "vka_dev.c").read_text()
        self.assertIn('strcmp(e, "0") != 0 : !V.task;', dev)
        memu = (VK / "vka_memu_draw.inc").read_text()
        self.assertIn('vka_memu_batch(int phase', memu)
        self.assertIn('case MEMU_MESH:', memu)


if __name__ == "__main__":
    unittest.main()
