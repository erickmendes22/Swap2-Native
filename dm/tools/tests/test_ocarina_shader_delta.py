"""Ocarina selected-key updates must not rebuild, relabel, or destroy 42k shaders."""
import importlib.util
import pathlib
import struct
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ocarina_shader_hot_delta.py"
spec = importlib.util.spec_from_file_location("ocarina_hot_delta", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
select = module.validated_hot_base
delta = module.delta

GAME = "0400486024DEC000"
INPUTS = "facedbadab12"
ABI = "123456789abc"
OLDVK = "111111111111"
NEWVK = "222222222222"
CHAIN = "333333333333"
KEYS = ("066f5daf12e43c71", "efaa4fa6a80ba719")


def write_lib(path, vk, count, keys=None, *, inputs=INPUTS, abi=ABI, chain=CHAIN, game=GAME):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(keys) if keys is not None else list(range(1, count + 1))
    count = len(keys)
    eo = delta.HEAD.size
    end = eo + count * delta.ENTRY.size
    header = delta.HEAD.pack(
        delta.VK["LIB_MAGIC"], delta.VK["LIB_VERSION"],
        chain.encode().ljust(16, b"\0"), vk.encode().ljust(16, b"\0"),
        game.encode().ljust(16, b"\0"), inputs.encode().ljust(16, b"\0"),
        count, eo, 0, end, 0, end, end, 0, 32, 16, abi.encode()
    )
    with path.open("wb") as f:
        f.write(header)
        for key in keys:
            e = bytearray(delta.ENTRY.size)
            struct.pack_into("<Q", e, 0, int(key, 16) if isinstance(key, str) else key)
            f.write(e)


class SelectedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = pathlib.Path(self.tmp.name)
        self.base = self.p / "shaders" / f"v-{OLDVK}" / "dmsh_vk.lib"
        self.overlay = self.p / "shaders" / "hot" / f"v-{NEWVK}" / "dmsh_vk.lib"
        write_lib(self.base, OLDVK, 42339)
        write_lib(self.overlay, NEWVK, len(KEYS), KEYS)
        self.hash_before = self.base.stat().st_size

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, keys=KEYS, **kw):
        return select(self.p, GAME, CHAIN, NEWVK, kw.get("abi", ABI),
                      kw.get("inputs", INPUTS), keys)

    def test_old_complete_lib_stays_as_is(self):
        self.assertEqual(self.plan(), self.base)
        self.assertEqual(self.base.stat().st_size, self.hash_before)
        self.assertTrue(self.overlay.exists())
        self.assertNotEqual(self.overlay, self.base)

    def test_no_full_base_is_refused(self):
        self.base.unlink()
        with self.assertRaisesRegex(ValueError, "no complete earlier"):
            self.plan()

    def test_no_overlay_is_refused(self):
        self.overlay.unlink()
        with self.assertRaisesRegex(ValueError, "not finished"):
            self.plan()

    def test_wrong_overlay_keys_are_refused(self):
        write_lib(self.overlay, NEWVK, 1, [KEYS[0]])
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.plan()

    def test_wrong_new_abi_is_refused(self):
        write_lib(self.overlay, NEWVK, len(KEYS), KEYS, abi="aaaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError, "wrong game"):
            self.plan()

    def test_wrong_old_abi_is_refused(self):
        write_lib(self.base, OLDVK, 42339, abi="aaaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError, "no complete earlier"):
            self.plan()

    def test_wrong_old_inputs_are_refused(self):
        write_lib(self.base, OLDVK, 42339, inputs="aaaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError, "no complete earlier"):
            self.plan()

    def test_truncated_old_base_is_refused(self):
        with self.base.open("r+b") as f:
            f.truncate(260)
        with self.assertRaisesRegex(ValueError, "no complete earlier"):
            self.plan()

    def test_no_keys_or_duplicate_or_nonhex_refused(self):
        for keys in [[], [KEYS[0], KEYS[0]], ["something"]]:
            with self.subTest(keys=keys), self.assertRaisesRegex(ValueError, "malformed"):
                self.plan(keys=keys)

    def test_android_command_line_updates_exact_shaders(self):
        source = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        self.assertIn('new File(pack, "shaders/hot").getPath()', source)
        self.assertIn('new String[4 + hotKeys.size()]', source)
        self.assertIn('argv[k + 4] = hotKeys.get(k)', source)
        self.assertIn('"--hot-keys", String.join(",", hotKeys)', source)

    def test_per_release_scope_is_pinned_not_guessed(self):
        code = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/OcarinaShaderDelta.java").read_text()
        self.assertIn('header.vkChain.equals(columns[0])', code)
        self.assertIn('BuildConfig.NX_DMSH_VK_CHAIN.equals(columns[1])', code)
        self.assertIn('profile.shaderInputs.equals(columns[2])', code)
        self.assertIn('BuildConfig.NX_DMSH_VK_ABI.equals(columns[3])', code)
        self.assertIn('!unique.add(k)', code)
        scope = (ROOT / "dm/games/0400486024DEC000/vk_hot_delta.tsv").read_text()
        self.assertFalse(any(l.strip() and not l.startswith("#") for l in scope.splitlines()))

    def test_full_pipeline_remains_when_no_scope(self):
        source = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        self.assertIn('if (!hotKeys.isEmpty())', source)
        self.assertIn('lib.getPath()', source)
        self.assertIn('OcarinaShaderDelta.keys(j)', source)
        pack = (ROOT / "scripts/pack_android.py").read_text()
        self.assertIn('if a.hot_keys:', pack)
        self.assertIn('shaders: incremental update:', pack)
        self.assertIn('if not library_current(lib, g):', pack)


if __name__ == "__main__":
    unittest.main()
