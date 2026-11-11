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
        self.assertIn('g_hot_loaded && vka_shlib_find(&g_hot, key)', HOST)
        self.assertIn('return &g_lib;', HOST)
        self.assertIn('vka_shader_make(library_for_key(key), key)', HOST)
        self.assertIn('const vka_shlib *source = library_for_key(key);', HOST)
        self.assertIn('out->sh[st] = vka_shader_make(source, key);', HOST)
        self.assertIn('An absent, invalid or incomplete overlay never blocks the full library', HOST)

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
