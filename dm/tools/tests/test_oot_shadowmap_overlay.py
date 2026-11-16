"""Ocarina shadow BYML inspector/overlay safety tests (not a fake game-data patch)."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "dm/tools"))
import gsys_shadowmaps as shadow  # noqa


def row(path, field, kind, offset, value):
    return ("System/GameGraphics/ModelSceneConfigParam/Main.bgyml",
            path, field, kind, offset, value)


class ShadowOverlaySafety(unittest.TestCase):
    def test_only_verified_named_shadow_sizes(self):
        values = [
            row("CreateDepthShadow/ShadowMapWidth", "ShadowMapWidth", 0xd1, 16, 1024),
            row("CreateDepthShadow/ShadowMapHeight", "ShadowMapHeight", 0xd1, 20, 1024),
            row("CreateStaticDepthShadow/ShadowMapSize", "ShadowMapSize", 0xd1, 40, 4096),
            row("CreateDepthShadow/DepthShadowCascadeNum0", "DepthShadowCascadeNum0", 0xd1, 44, 3),
            row("CreateEnvCubeMap/TextureSize", "TextureSize", 0xd1, 48, 1024)
        ]
        patch = shadow.select_fields(values, dynamic=512, static=2048)
        self.assertEqual(set(patch), {16, 20, 40})
        self.assertNotIn(44, patch)
        self.assertNotIn(48, patch)
        raw = bytearray(64)
        for r in values:
            raw[r[4]:r[4]+4] = int(r[5]).to_bytes(4, 'little')
        result = shadow.patch_raw(bytes(raw), patch)
        self.assertEqual(int.from_bytes(result[16:20], 'little'), 512)
        self.assertEqual(int.from_bytes(result[20:24], 'little'), 512)
        self.assertEqual(int.from_bytes(result[40:44], 'little'), 2048)
        self.assertEqual(result[44:], bytes(raw)[44:])
        self.assertEqual(result[:16], bytes(raw)[:16])

    def test_unknown_hashed_keys_fail_closed(self):
        hashed = [row("CreateDepthShadow/#ab3354ae", "#ab3354ae", 0xd1, 20, 1024)]
        with self.assertRaises(shadow.g.Error):
            shadow.select_fields(hashed, dynamic=512)
        with self.assertRaises(shadow.g.Error):
            shadow.select_fields([], static=2048)

    def test_no_blind_1024_rewrites_or_cascade_changes(self):
        x = [
            row("CreateDepthShadow/DepthShadowCascadeNum0", "DepthShadowCascadeNum0", 0xd1, 12, 1024),
            row("CreateEnvCubeMap/TextureSize", "TextureSize", 0xd1, 24, 1024)
        ]
        with self.assertRaises(shadow.g.Error):
            shadow.select_fields(x, dynamic=512)
        x.append(row("CreateDepthShadow/ShadowMapSize", "ShadowMapSize", 0xd1, 40, 1024))
        x.append(row("CreateDepthShadow/SomeOtherSize", "SomeOtherSize", 0xd1, 44, 800))
        with self.assertRaises(shadow.g.Error):
            shadow.select_fields(x, dynamic=512)

    def test_missing_game_files_does_not_create_overlay(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            dst = root / "patch"
            code = shadow.main(["--romfs", str(root), "--dynamic", "512",
                                "--static", "2048", "--out", str(dst)])
            self.assertEqual(code, 1)
            self.assertFalse(dst.exists())


if __name__ == '__main__':
    unittest.main()
