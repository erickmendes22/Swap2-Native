"""ABI transitions must never invalidate/relabel all game shaders by accident.

Compatible extensions can map the unchanged old full library. Real ABI
changes must use per-shader hash comparisons or translation, not a fake stamp.
"""
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
S = ROOT / "dm/gfx/tools/vk_abi_migrate.py"
spec = importlib.util.spec_from_file_location("vk_abi_migrate_tested", S)
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class AbiProtection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_vk = self.root / "old_vk.h"
        self.old_common = self.root / "old_common.h"
        self.new_vk = self.root / "new_vk.h"
        self.new_common = self.root / "new_common.h"
        self.old_vk.write_text(v.ABI_VK.read_text())
        self.old_common.write_text(v.ABI_COMMON.read_text())
        self.new_vk.write_text(v.ABI_VK.read_text())
        self.new_common.write_text(v.ABI_COMMON.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self):
        return v.additive_compatible(self.old_vk, self.old_common,
                                     self.new_vk, self.new_common)

    def test_unchanged_actual_abi(self):
        self.assertEqual(v.current_versions()["DMSH_VK_ABI"],
                         v.abi_digest(v.ABI_VK, v.ABI_COMMON))
        self.assertEqual(v.certificates(), [])
        self.assertIn("#define VKA_ABI_COMPAT_COUNT 0", v.TARGET.read_text())
        self.assertIn("private static final Cert[] CERTS", v.TARGET_JAVA.read_text())

    def test_new_unused_binding_kind_preserves_old_shaders(self):
        self.new_vk.write_text(self.new_vk.read_text() +
                               "\n#define DMSH_VK_KIND_UNUSED_EXTRA 23\n")
        self.assertEqual(self.audit(), ("DMSH_VK_KIND_UNUSED_EXTRA",))

    def test_new_flag_bit_preserves_old_shaders(self):
        self.new_vk.write_text(self.new_vk.read_text() +
                               "\n#define DMSH_VK_F_UNUSED_EXTRA 16384\n")
        self.assertEqual(self.audit(), ("DMSH_VK_F_UNUSED_EXTRA",))

    def test_descriptor_renumber_requires_migration_or_retranslation(self):
        s = self.new_vk.read_text()
        self.assertIn("#define DMSH_VK_KIND_SBUF 5", s)
        self.new_vk.write_text(s.replace("#define DMSH_VK_KIND_SBUF 5",
                                         "#define DMSH_VK_KIND_SBUF 24"))
        with self.assertRaisesRegex(v.UnsafeMigration, "changed or removed"):
            self.audit()

    def test_rev_bump_always_refused(self):
        self.new_vk.write_text(self.new_vk.read_text().replace(
            "#define DMSH_VK_ABI_REV 1", "#define DMSH_VK_ABI_REV 2"))
        with self.assertRaises(v.UnsafeMigration):
            self.audit()

    def test_changed_layout_always_refused(self):
        self.new_vk.write_text(self.new_vk.read_text().replace(
            "uint16_t subgroup_size;", "uint32_t subgroup_size;"))
        with self.assertRaisesRegex(v.UnsafeMigration, "Vulkan ABI structs"):
            self.audit()

    def test_changed_common_abi_always_refused(self):
        self.new_common.write_text(self.new_common.read_text() + "\n#define EXTENDED_POINTER_SIZE 16\n")
        with self.assertRaisesRegex(v.UnsafeMigration, "common NVN ABI"):
            self.audit()

    def test_flag_collision_refused(self):
        self.new_vk.write_text(self.new_vk.read_text() +
                               "\n#define DMSH_VK_F_UNUSED_EXTRA 8192\n")
        with self.assertRaisesRegex(v.UnsafeMigration, "flag collision"):
            self.audit()

    def test_arbitrary_new_define_refused(self):
        self.new_vk.write_text(self.new_vk.read_text() +
                               "\n#define DMSH_VK_UNSAFE_NEW_MEANING 1\n")
        with self.assertRaisesRegex(v.UnsafeMigration, "not additive-safe"):
            self.audit()

    def test_cpp_and_java_share_the_exact_approved_tuples(self):
        c = ("0123456789ab", "aabbccddeeff", "fedcba987654",
             "123456789abc", "112233445566")
        self.assertIn(c[0], v.c_header([c]))
        self.assertIn(c[1], v.c_header([c]))
        self.assertIn(c[4], v.c_header([c]))
        self.assertIn(c[0], v.java_source([c]))
        self.assertIn(c[1], v.java_source([c]))
        self.assertIn(c[4], v.java_source([c]))

    def test_old_library_remains_untouched_and_compiled_same_abi_is_accepted(self):
        text = (ROOT / "dm/gfx/vk_android/vka_shader.c").read_text()
        self.assertIn("certified_abi_open(&t, p", text)
        self.assertIn("certified_abi_open(&g_lib, compatible", text)
        self.assertIn('!memcmp(lib->h->abi, c->old_abi, 12)', text)
        self.assertIn('!strcmp(inputs, c->inputs)', text)
        self.assertIn("const dmsh_vk_entry *overlay = vka_shlib_find(&g_hot, key)", text)
        self.assertIn("VKA_ENV(\"DM_VK_OOT_HOT_MESH\", 0)", text)
        self.assertIn("return &g_lib;", text)
        android = (ROOT / "android/app/src/main/java/dev/nxnative/android/ShaderLibs.java").read_text()
        self.assertIn("ShaderAbiCert.approved(titleId, h.vkChain, h.abi, h.inputs)", android)

if __name__ == "__main__":
    unittest.main()
