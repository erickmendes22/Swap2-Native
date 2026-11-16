"""Ocarina: genuine missing-key repairs must never replace existing shaders.

These source contracts run before an APK can ship. The native tool also
validates hashes/SPIR-V of carried entries while building the actual overlay.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
PICK = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/OcarinaShaderDelta.java").read_text()
UI = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/Ondevice.java").read_text()
SERVICE = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
BUILDER = (ROOT / "dm/gfx/tools/vk_android_build.py").read_text()


class MissingShaderRepair(unittest.TestCase):
    def test_only_absent_keys_enter_a_stable_bounded_repair(self):
        selection = PICK.split("static List<String> keys(Job job) {", 1)[1].split(
            "/** The installed overlay already", 1)[0]
        self.assertIn("java.util.Arrays.sort(captureFiles,", selection)
        self.assertIn("if (ShaderLibs.hasKey(old, header, key)) continue;", selection)
        self.assertIn("if (hotVerified && ShaderLibs.hasKey(hot, hotHeader, key)) continue;", selection)
        self.assertIn("if (missing.size() == 128) break;", selection)
        self.assertNotIn("vegetationKeys()", selection)
        self.assertNotIn("vk_hot_delta.tsv", selection)
        self.assertNotIn("HEAVY.contains(key)", selection)
        self.assertNotIn("SCENE_FRAGMENTS.contains(key)", selection)

    def test_done_is_done_no_mandatory_repeat(self):
        self.assertIn("if (selected.isEmpty() || done) {", UI)
        self.assertNotIn("done && !explicit && !retryRequested", UI)
        self.assertIn("if (again && !card", UI)

    def test_new_partial_overlay_keeps_old_successes_without_retranslation(self):
        self.assertIn("_old.hash_of(_entry_no, zstd)", BUILDER)
        self.assertIn("results.extend(_preserved)", BUILDER)
        self.assertIn("want.update(k for k, _, _, _ in _preserved)", BUILDER)
        self.assertIn("keys.extend(k for k, _, _, _ in _preserved)", BUILDER)
        self.assertIn("_old.chain == CHAIN", BUILDER)
        self.assertIn("_old.abi == ABI", BUILDER)
        self.assertIn("_old.inputs == INPUTS", BUILDER)
        self.assertIn("if len(want | set(_old.index)) > 1024:", BUILDER)
        self.assertIn("if os.path.isfile(installed):", BUILDER)
        self.assertNotIn("if os.path.isfile(installed) and not os.path.isfile(previous):", BUILDER)

    def test_packer_verifies_every_published_key_and_prior_source(self):
        self.assertIn("newHeader.entries != selectedKeys.size()", SERVICE)
        self.assertIn("ShaderLibs.hasKey(newLib, newHeader, key)", SERVICE)
        self.assertIn("ShaderLibs.hasKey(prior, previous, key)", SERVICE)
        self.assertIn("if (fresh == 0)", SERVICE)
        self.assertIn("j.expectedShaders(fresh);", SERVICE)
        self.assertIn("publishedHotKeys = selectedKeys;", SERVICE)


if __name__ == "__main__":
    unittest.main()
