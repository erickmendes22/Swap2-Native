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
NATIVE = (ROOT / "dm/gfx/vk_android/vka_shader.c").read_text()
BUILDER = (ROOT / "dm/gfx/tools/vk_android_build.py").read_text()


class MissingShaderRepair(unittest.TestCase):
    def test_only_absent_keys_enter_a_stable_bounded_repair(self):
        selection = PICK.split("static List<String> keys(Job job) {", 1)[1].split(
            "/** The installed overlay already", 1)[0]
        self.assertIn("java.util.Arrays.sort(captureFiles,", selection)
        self.assertIn("if (ShaderLibs.hasKey(old, header, key)) continue;", selection)
        self.assertIn("if (hotVerified && ShaderLibs.hasKey(hot, hotHeader, key)) continue;", selection)
        self.assertIn("if (missing.size() == 128) break;", selection)
        self.assertIn("vegetationSet.contains(key)", selection)
        self.assertIn("completeVegetationInstalled", selection)
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

    def test_real_builder_merge_preserves_an_existing_shader_without_recompiling(self):
        # Execute the actual AST block from vk_android_build.py with small
        # synthetic verified modules. No proprietary shader capture is needed.
        import ast
        import collections
        import os
        import struct
        import sys
        import tempfile
        import types
        from unittest.mock import patch

        tree = ast.parse(BUILDER)
        blocks = [n for n in tree.body if isinstance(n, ast.If)
                  and "Ocarina incremental overlay" in ast.unparse(n)]
        self.assertEqual(len(blocks), 1)
        old_key = "0000000000000002"
        selected_key = "0000000000000001"
        old_entry = bytearray(64)
        old_entry[16] = 5

        class PreviousLibrary:
            def __init__(self, path):
                self.path = path
                self.ne = 2
                self.game = "0400486024DEC000"
                self.chain = "same-translator"
                self.inputs = "same-inputs"
                self.abi = "674db0a4ff79"
                self.sg = 64
                self.sa = 256
                self.version = "old-overlay"
                self.index = {old_key: 0, selected_key: 1}
                self.closed = False

            def hash_of(self, i, codec):
                key = old_key if i == 0 else selected_key
                return key, "verified", (key, bytes(old_entry), b"bindings", b"c1",
                                          [(0, 4, b"data", 0)])

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "v-old-overlay"
            folder.mkdir()
            (folder / "dmsh_vk.lib").write_bytes(b"fixture")
            selected = {selected_key}
            results = [(selected_key, "ok", "", ({"new": True}, []))]
            keys = [selected_key]
            ns = {
                "want": selected, "VEGETATION": False,
                "GAME": types.SimpleNamespace(id="0400486024DEC000"),
                "cache_root": tmp, "os": os, "struct": struct, "sys": sys,
                "VK": {"DIR_PREFIX": "v-", "LIB_FILE": "dmsh_vk.lib"},
                "delta": types.SimpleNamespace(Library=PreviousLibrary, zeroed=lambda b: b),
                "CHAIN": "same-translator", "INPUTS": "same-inputs",
                "ABI": "674db0a4ff79",
                "ANSWERS": {"subgroup_size": 64, "ssbo_align": 256},
                "STAGE": {"cs": 5}, "zstd": None,
                "STAGE_OF": {selected_key: "cs"}, "REUSED": set(),
                "results": results, "keys": keys,
            }
            with patch.dict(os.environ, {"DMSH_VK_OOT_PARTIAL": "1"}):
                exec(compile(ast.Module(body=blocks, type_ignores=[]),
                             "<real cumulative overlay block>", "exec"), ns)
            self.assertEqual(selected, {selected_key, old_key})
            self.assertEqual(set(keys), {selected_key, old_key})
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0][0], selected_key)
            self.assertEqual(results[1][0], old_key)
            self.assertEqual(results[1][3][0]["lib"]["binds"], b"bindings".hex())
            self.assertEqual(ns["STAGE_OF"][old_key], "cs")
            self.assertEqual(ns["REUSED"], {old_key})
            # This was the EXACT final report expression raising KeyError
            # after writing the library on the real phone.
            by_stage = collections.Counter(ns["STAGE_OF"][row[0]] for row in results)
            self.assertEqual(by_stage, {"cs": 2})

    def test_actual_missing_mesh_draw_captures_verified_partner_sources(self):
        self.assertIn("if (!e && p->sd[i].control && p->sd[i].data)", NATIVE)
        self.assertIn("ctl[0x56] == 7", NATIVE)
        self.assertIn("ctl[0x56] == 6", NATIVE)
        self.assertIn("int missing_mesh = !vka_shlib_find(&g_lib, mesh_key)", NATIVE)
        self.assertIn("int missing_task = have_task && !vka_shlib_find(&g_lib, task_key)", NATIVE)
        self.assertIn("if (hot_mesh || missing_mesh)", NATIVE)
        self.assertIn("if ((hot_task || missing_task)", NATIVE)
        self.assertIn("capture_ocarina_stage_pair(mesh_program, mesh_slot, mesh_key", NATIVE)
        self.assertNotIn("!a_key || !b_key || !g_hot_loaded", NATIVE)

    def test_compiler_writes_deferred_stamps_only_for_actual_unpaired_keys(self):
        self.assertIn("_key + '.deferred'", BUILDER)
        self.assertIn("_f.write(CHAIN +", BUILDER)
        self.assertIn("if deferred and 'CHAIN' in globals()", BUILDER)
        self.assertIn("File blocked = new File(captures, key +", PICK)
        self.assertIn("newestPairEvidence", PICK)
        self.assertIn("compilerStamp.equals(stamp.get(0))", PICK)
        self.assertIn("if (missing.size() == 128) break;", PICK)

    def test_packer_verifies_every_published_key_and_prior_source(self):
        self.assertIn("newHeader.entries != selectedKeys.size()", SERVICE)
        self.assertIn("ShaderLibs.hasKey(newLib, newHeader, key)", SERVICE)
        self.assertIn("ShaderLibs.hasKey(prior, previous, key)", SERVICE)
        self.assertIn("if (fresh == 0)", SERVICE)
        self.assertIn("j.expectedShaders(fresh);", SERVICE)
        self.assertIn("publishedHotKeys = selectedKeys;", SERVICE)


if __name__ == "__main__":
    unittest.main()
