"""Ocarina hot compute: actual C SPIR-V retile parser tests.

No game assets required; compile vka_spvpatch.c as a host shared library and
exercise the same validation/rewriter that the Android build uses. The
retiling is opt-in and refuses unsafe shaders rather than inventing results.
"""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "dm/gfx/vk_android/vka_spvpatch.c"
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
PSO = (ROOT / "dm/gfx/vk_android/vka_pso.c").read_text()
SH = (ROOT / "dm/gfx/vk_android/vka_shader.c").read_text()


def ins(op, *args):
    return [(len(args) + 1) << 16 | op, *args]


def module(*additional):
    # Minimal instruction stream for testing the safety analyzer. Not
    # intended for submission to a graphics driver.
    result = [0x07230203, 0x00010300, 0, 128, 0]
    result += ins(15, 5, 1, 0x6e69616d, 0)  # OpEntryPoint GLCompute, "main"
    result += ins(16, 1, 17, 8, 4, 4)      # OpExecutionMode LocalSize
    result += ins(71, 2, 11, 28)           # BuiltIn GlobalInvocationId
    for x in additional:
        result += x
    return result


class RetileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc") or shutil.which("clang")
        if not compiler:
            raise RuntimeError("C compiler needed for native SPIR-V parser tests")
        cls.tmp = tempfile.TemporaryDirectory()
        so = Path(cls.tmp.name) / "spvpatch.so"
        subprocess.run([compiler, "-std=c11", "-O2", "-shared", "-fPIC",
                        str(SRC), "-o", str(so)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cls.lib = ctypes.CDLL(str(so))
        cls.fn = cls.lib.vka_spv_oot_cs_retile
        cls.fn.argtypes = [ctypes.POINTER(ctypes.c_uint32),
                           ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
        cls.fn.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def patch(self, data):
        arr = (ctypes.c_uint32 * len(data))(*data)
        why = ctypes.create_string_buffer(200)
        result = self.fn(arr, len(data), why, len(why))
        return result, list(arr), why.value.decode("utf-8")

    def test_equal_global_invocation_domain(self):
        original = module()
        ok, changed, why = self.patch(original)
        self.assertEqual(ok, 1, why)
        self.assertEqual(changed[13:16], [8, 4, 2])
        self.assertEqual(8 * 4 * 4 * 8 * 9 * 12, 8 * 4 * 2 * 8 * 9 * 24)
        self.assertEqual(original[:15], changed[:15])
        self.assertEqual(original[16:], changed[16:])

    def test_refuses_group_or_local_builtins(self):
        for builtin in [24, 25, 26, 27, 29, 36, 40, 41]:
            with self.subTest(builtin=builtin):
                data = module(ins(71, 3, 11, builtin))
                ok, after, _ = self.patch(data)
                self.assertEqual(ok, 0)
                self.assertEqual(after, data)

    def test_refuses_shared_storage_barriers_atomic_and_subgroups(self):
        cases = [ins(59, 5, 7, 4), ins(224, 1, 1, 1),
                 ins(225, 1, 1), ins(227, 1, 2, 3, 4),
                 ins(333, 1, 2, 3)]
        for event in cases:
            with self.subTest(event=event):
                data = module(event)
                ok, after, _ = self.patch(data)
                self.assertEqual(ok, 0)
                self.assertEqual(after, data)

    def test_refuses_wrong_local_size_or_unsafe_spirv(self):
        different = module()
        different[15] = 3
        for raw in [different, module()[:-1], [0, 1, 2, 3, 4],
                    module(ins(331, 1, 17, 3))]:
            with self.subTest(raw=raw[-5:]):
                ok, after, _ = self.patch(raw)
                self.assertEqual(ok, 0)
                self.assertEqual(after, raw)

    def test_indirect_and_unsafe_sizes_keep_original(self):
        self.assertIn("!rt.b[0] && !dp->ind && !spill_bytes(sh[5])", DRAW)
        self.assertIn("dp->x > 0 && dp->y > 0 && dp->z > 0", DRAW)
        self.assertIn("maxComputeWorkGroupCount[2] / 2u", DRAW)
        self.assertNotIn("dp->x == 8 && dp->y == 9 && dp->z == 12", DRAW)
        self.assertIn("vka_cs_pipeline_oot_retile(sh[5], &lay, &oot_cs_retiled)", DRAW)
        self.assertIn("(oot_cs_retiled ? 2u : 1u)", DRAW)
        self.assertIn("if (!p) p = rt.b[0] ?", DRAW)
        self.assertIn("uint32_t retiled; } ckey;", PSO)
        self.assertIn("k.retiled = retiled != 0;", PSO)
        self.assertIn("s->e->shared != 0", SH)
        self.assertIn("s->e->flags & DMSH_VK_F_SUBGROUP", SH)


if __name__ == "__main__":
    unittest.main()
