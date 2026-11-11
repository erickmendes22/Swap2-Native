"""Ocarina GPU hot-shader overlays: protect original 42k shader library.

The full imported library is always the fallback. New translated SPIR-V is
allowed only for explicitly selected keys and a verified matching game ABI.
This tests the runtime selection contracts, not proprietary game assets.
"""
from pathlib import Path
import tempfile
import unittest
import importlib.util

SCRIPT = ROOT = Path(__file__).resolve().parents[4]
_PUBLISH = SCRIPT / "scripts/build_ocarina_hot_shaders.py"
_spec = importlib.util.spec_from_file_location("oot_hot_publish", _PUBLISH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
publish = _module.publish_verified_hot_manifest

ROOT = Path(__file__).resolve().parents[4]
HOST = (ROOT / "dm/gfx/vk_android/vka_shader.c").read_text()
BUILDER = (ROOT / "scripts/build_ocarina_hot_shaders.py").read_text()


class HotShaderOverlay(unittest.TestCase):
    def test_host_retains_original_library_and_uses_override_by_key(self):
        self.assertIn('static vka_shlib g_lib, g_hot;', HOST)
        self.assertIn('shaders/hot/', HOST)
        self.assertIn('vka_shlib_open(&g_hot, hp, DMSH_CHAIN, DMSH_VK_CHAIN, DM_GAME_ID, DMSH_VK_ABI', HOST)
        self.assertIn('g_hot_loaded', HOST)
        self.assertIn('const dmsh_vk_entry *overlay = vka_shlib_find(&g_hot, key)', HOST)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT_MESH", 0)', HOST)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT", 1)', HOST)
        self.assertIn('return &g_lib;', HOST)
        self.assertIn('vka_shader_make(library_for_key(key), key)', HOST)
        self.assertIn('const vka_shlib *source = library_for_key(key);', HOST)
        delta=(ROOT / "android/app/src/ondevice/java/dev/nxnative/android/OcarinaShaderDelta.java").read_text()
        self.assertIn('HEAVY.contains(key)', delta)
        self.assertIn('ShaderLibs.hasKey(old, header, key)', delta)
        self.assertIn('!BuildConfig.NX_DMSH_VK_CHAIN.equals(header.vkChain)', delta)
        self.assertIn('File captures = new File(job.dir().getParentFile(), "nvn_shdump")',delta)
        self.assertIn('out->sh[st] = vka_shader_make(source, key);', HOST)
        self.assertIn('An absent, invalid or incomplete overlay never blocks the full library', HOST)

    def test_failed_57_shader_overlay_quarantines_unpaired_mesh_stages(self):
        # Regression: previous version compiled 57 valid SPIR-V modules,
        # but its 53 newly captured mesh/task shaders were not given the
        # pixel pair metadata needed for correct geometry and produced
        # screen-spanning white triangles and a large GPU time regression.
        src = HOST
        self.assertIn('overlay->stage == DMSH_VK_STAGE_MS', src)
        self.assertIn('overlay->stage == DMSH_VK_STAGE_TS', src)
        self.assertIn('!VKA_ENV("DM_VK_OOT_HOT_MESH", 0)', src)
        self.assertIn('return &g_lib;', src)
        self.assertIn('return &g_hot;', src)
        self.assertIn('DM_VK_OOT_HOT=0', src)
        self.assertIn('!VKA_ENV("DM_VK_OOT_HOT_OVERRIDE", 0)', src)
        self.assertIn('vka_shlib_find(&g_lib, key)', src)
        self.assertIn('old_keys++;', src)
        self.assertIn('quarantine++;', src)
        self.assertIn('vka_shlib_find(&g_lib, entry->key)', src)
        self.assertLess(src.index('!VKA_ENV("DM_VK_OOT_HOT_MESH", 0)'),
                        src.index('return &g_hot;', src.index('static const vka_shlib *library_for_key')))

    def test_nv_mesh_fragment_pairs_use_fragment_stage_not_tess_control(self):
        # Build 46 compiled the capture code but looked at pair_slots[1],
        # which is TCS, not FS. With the real mesh and pixel present the
        # condition was always false, so all five retries lacked pairs.
        import re
        abi=(ROOT / "dm/gfx/nvn/dmsh_abi_vk.h").read_text()
        stages={name:int(index) for name,index in re.findall(
            r"^#define DMSH_VK_STAGE_(VS|TCS|TES|GS|FS|CS|TS|MS)\\s+(\\d+)",
            abi, re.M)}
        self.assertEqual(stages["TCS"],1)
        self.assertEqual(stages["FS"],4)
        self.assertEqual(stages["TS"],6)
        self.assertEqual(stages["MS"],7)
        self.assertIn('pair_slots[DMSH_VK_STAGE_MS] && pair_slots[DMSH_VK_STAGE_FS]',HOST)
        self.assertIn('pair_slots[DMSH_VK_STAGE_FS] - 1, pair_keys[DMSH_VK_STAGE_FS]',HOST)
        self.assertIn('pair_slots[DMSH_VK_STAGE_TS] && pair_slots[DMSH_VK_STAGE_MS]',HOST)
        self.assertNotIn('pair_slots[7] && pair_slots[1]',HOST)
        self.assertNotIn("pair_keys[1], 'M'",HOST)
        # The captured first 57-key retry fails on key 04452448ac915259;
        # this fixes recording, not that key's flat/primitive equivalence.
        self.assertIn('capture_ocarina_stage_pair(p,',HOST)

    def test_heavy_shader_capture_enables_later_targeted_recompilation(self):
        self.assertIn('capture_hot_shader_source(p, i, key)', HOST)
        self.assertIn('capture_shader_source(p, i, key)', HOST)
        self.assertIn('0x9e6b00b050e30801', HOST)
        self.assertIn('0x066f5daf12e43c71', HOST)
        self.assertIn('capture_matches(ctl, p->sd[i].control, nctl)', HOST)
        self.assertIn('unlink(ctl);', HOST)
        self.assertIn('capture_write_file(code, bytes, ncode)', HOST)
        self.assertIn('capture_write_file(ctl, p->sd[i].control, nctl)', HOST)
        self.assertIn('sources.add_argument("--capture-dir", type=Path', BUILDER)
        self.assertIn('env["DMSH_VK_CAPTURE_DIR"] = str(capture)', BUILDER)
        self.assertIn('tempfile.TemporaryDirectory', BUILDER)
        src = (ROOT / "dm/gfx/tools/vk_android_build.py").read_text()
        self.assertIn("CAPTURED_MESH_FACTS = borrow_mesh_layout()", src)
        self.assertIn("FACTS[key] = {**existing, **{field: value for field, value in derived.items()", src)
        self.assertIn("n.name == 'mesh_facts'", src)
        self.assertIn("stage in ('ms', 'ts')", src)
        self.assertIn("mesh_pairs.tsv", src)
        self.assertIn("observed = [p for p in pairs", src)
        self.assertIn("pixel_sources, observed", src)
        self.assertIn("captured mesh/fragment mismatch", src)
        self.assertIn("'code_bytes': lambda data: data", src)
        self.assertIn('capture_ocarina_stage_pair', HOST)
        self.assertIn('mesh_pairs.tsv', HOST)

    def test_051430_upscale_regression_uses_known_good_default(self):
        # Prior good gameplay: b106 NDSR via EASU, SGSR1-single-pass.
        # Bad Build 44: b106 bilinear, SGSR was rot-linear fallback.
        # The requested filter alone does NOT prove it ran.
        ndsr = (ROOT / "dm/gfx/vk_android/vka_ndsr.c").read_text()
        present = (ROOT / "dm/gfx/vk_android/vka_present.c").read_text()
        self.assertIn('cs->key == UINT64_C(0xb106afba1a18faa9)', ndsr)
        self.assertIn('VKA_ENV("DM_VK_OOT_NDSR_BILINEAR", 0)', ndsr)
        self.assertIn('Ocarina SGSR/FSR unavailable despite requested filter', present)
        self.assertIn('if (present_filter >= 3 && !fsr_applied)', present)
        self.assertIn('fsr_requested=%d sampling=%d', present)

    def test_builder_only_compiles_explicit_hot_keys(self):
        self.assertIn('DEFAULT_KEYS = (', BUILDER)
        for key in ("066f5daf12e43c71", "efaa4fa6a80ba719",
                    "5ad65c0eefd09c7f", "9e6b00b050e30801"):
            self.assertIn(key, BUILDER)
        self.assertIn('"--key", action="append"', BUILDER)
        self.assertIn('any(shaders.glob("v-*/dmsh_vk.lib"))', BUILDER)
        self.assertIn('overlay_root = shaders / "hot"', BUILDER)
        self.assertIn('"--target", "vulkan", str(pkg)', BUILDER)
        self.assertIn('str(overlay_root), *keys', BUILDER)
        self.assertIn('"--check", str(output)', BUILDER)

    def test_manifest_publish_requires_verified_exact_versions_and_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vk_hot_delta.tsv"
            path.write_text("# human-reviewed GPU hot shader delta\n")
            keys = ["5ad65c0eefd09c7f", "066f5daf12e43c71"]
            ids = ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "dddddddddddd")
            self.assertTrue(publish(path, *ids, keys))
            self.assertFalse(publish(path, *ids, keys))
            row = "\t".join((*ids, ",".join(sorted(keys))))
            self.assertEqual(path.read_text().splitlines()[-1], row)
            with self.assertRaisesRegex(ValueError, "different shader-key list"):
                publish(path, *ids, ["9e6b00b050e30801"])
            with self.assertRaisesRegex(ValueError, "actual changed"):
                publish(path, ids[0], ids[0], ids[2], ids[3], keys)
            with self.assertRaisesRegex(ValueError, "malformed"):
                publish(path, "wrong", *ids[1:], keys)
            self.assertEqual(path.read_text().splitlines()[-1], row)

    def test_abi_and_game_id_are_checked_before_overlay(self):
        self.assertIn('env["DM_GAME"] = GAME', BUILDER)
        self.assertIn('DMSH_VK_REQUIRE_ALL="1"', BUILDER)
        self.assertIn('DMSH_GMEM_MAP_8192="1"', BUILDER)
        self.assertIn('DM_GAME_ID, DMSH_VK_ABI, he, sizeof he', HOST)


if __name__ == '__main__':
    unittest.main()
