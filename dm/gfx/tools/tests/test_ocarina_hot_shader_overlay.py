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

    def test_original_full_base_is_preferred_over_six_shader_current_version(self):
        # Regression: six new compilation results must augment the old
        # complete library, never substitute for its ~42k shader entries.
        app = ROOT / "android/app/src/main/java/dev/nxnative/android"
        pack = (app / "Pack.java").read_text()
        shader_libs = (app / "ShaderLibs.java").read_text()
        delta = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/OcarinaShaderDelta.java").read_text()
        self.assertIn('char oot_partial_current[1024]', HOST)
        self.assertIn('n > 1024', HOST)
        self.assertIn('st.st_mtime < best_time', HOST)
        self.assertIn('!memcmp(other.h->inputs, g_lib.h->inputs', HOST)
        self.assertIn('if (*oot_partial_current)', HOST)
        self.assertIn('g_lib.h->entry_count <= 1024', HOST)
        self.assertIn('head.entries <= 1024', pack)
        self.assertIn('h.entries <= 1024', shader_libs)
        self.assertIn('current.entries <= 1024', delta)

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
        # The reviewed compute-only 9e6b exception returns &g_hot
        # earlier than the final guarded mesh/task path. Verify the
        # UNCONDITIONAL fallback is still after mesh quarantine, not the
        # separate safe compute exception.
        mesh_guard = src.index('!VKA_ENV("DM_VK_OOT_HOT_MESH", 0)', src.index('static const vka_shlib *library_for_key'))
        final_hot = src.index('    return &g_hot;\n}', mesh_guard)
        self.assertLess(mesh_guard, final_hot)

    def test_hot_compute_only_uses_modern_translator_when_shader_abi_matches(self):
        # A full 42k-shader rebuild remains prohibited. The 9e6b shader
        # was captured during actual gameplay and may be translated alone
        # with the new V21/V22 raw memory improvements. The prior generic
        # SPIR-V workgroup-retile patch is correctly refused on this shader
        # because it reads group-dependent builtins; this source variant
        # keeps the guest's ORIGINAL dispatch grid and local size.
        self.assertIn('static int oot_hot_compute_compatible(', HOST)
        self.assertIn('key != UINT64_C(0x9e6b00b050e30801)', HOST)
        self.assertIn('old->stage != DMSH_VK_STAGE_CS', HOST)
        self.assertIn('newer->stage != DMSH_VK_STAGE_CS', HOST)
        self.assertIn('old->local[0] != newer->local[0]', HOST)
        self.assertIn('old->local[1] != newer->local[1]', HOST)
        self.assertIn('old->local[2] != newer->local[2]', HOST)
        self.assertIn('old->shared != newer->shared', HOST)
        self.assertIn('old->bind_count != newer->bind_count', HOST)
        self.assertIn('memcmp(a, b, (size_t)old->bind_count * sizeof *a) == 0', HOST)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT_COMPUTE", 1)', HOST)
        self.assertIn('if (compatible) return &g_hot;', HOST)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT_OVERRIDE", 0)', HOST)
        self.assertIn('VKA_ENV("DM_VK_OOT_HOT_MESH", 0)', HOST)
        self.assertIn('return &g_lib;', HOST)
        self.assertIn('DM_VK_OOT_HOT_COMPUTE=0 restores original shader', HOST)

    def test_mesh_fragment_pair_captured_from_actual_draw_stage_bindings(self):
        # The Vulkan ABI labels FS as stage 4, but NVN labels it stage 1.
        # More importantly, a mesh draw combines independently bound
        # d->bst[7] (mesh) and d->bst[1] (fragment), not necessarily the
        # shader list of a single NVN program. Old Build 46 missed these.
        import re
        abi=(ROOT/"dm/gfx/nvn/dmsh_abi_vk.h").read_text()
        bind=(ROOT/"dm/gfx/vk_android/vka_bind.h").read_text()
        draw=(ROOT/"dm/gfx/vk_android/vka_draw.c").read_text()
        stages={n:int(v) for n,v in re.findall(
            r"^#define DMSH_VK_STAGE_(FS|TS|MS)\s+(\d+)", abi, re.M)}
        self.assertEqual(stages, {"FS":4,"TS":6,"MS":7})
        self.assertIn("static const int8_t m[8] = {0, 3, 4, 2, 1, 5, 6, 7}",bind)
        self.assertIn("stage_in_program(pixel_program, vka_nvn_stage(DMSH_VK_STAGE_FS)",HOST)
        self.assertIn("stage_in_program(mesh_program, vka_nvn_stage(DMSH_VK_STAGE_MS)",HOST)
        self.assertIn("capture_ocarina_stage_pair(mesh_program, mesh_slot, mesh_key,",HOST)
        self.assertIn("pixel_program, frag_slot, frag_key, 'M'",HOST)
        self.assertIn("capture_ocarina_stage_pair(mesh_program, task_slot, task_key,",HOST)
        self.assertIn('const prog_t *mp = d->bst[7];',draw)
        self.assertIn('vka_ocarina_capture_mesh_draw_pair(mp, d->bst[1])',draw)
        self.assertLess(draw.index('vka_ocarina_capture_mesh_draw_pair(mp, d->bst[1])'),
                        draw.index('if (bad) SKIPQ();',draw.index('const prog_t *mp = d->bst[7];')))
        self.assertIn("captured[256]", draw)
        self.assertNotIn("pair_slots[7] && pair_slots[1]",HOST)
        self.assertIn("mesh_pairs.tsv",HOST)
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
