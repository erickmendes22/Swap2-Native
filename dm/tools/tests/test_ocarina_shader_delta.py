"""Ocarina selected-key updates must not rebuild, relabel, or destroy 42k shaders."""
import ast
import importlib.util
import pathlib
import struct
import tempfile
import types
import unittest
from unittest import mock

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
        self.assertIn('new File(pack, vegetation ? "shaders/vegetation" : "shaders/hot").getPath()', source)
        self.assertIn('new String[4 + hotKeys.size()]', source)
        self.assertIn('argv[k + 4] = hotKeys.get(k)', source)
        self.assertIn('"--hot-keys", String.join(",", publishedHotKeys)', source)
        self.assertIn('new File(pack, "shaders/hot/v-"', source)
        self.assertIn('unique.size() != selectedKeys.size()', source)
        self.assertIn('!hotKeys.containsAll(selectedKeys)', source)
        self.assertIn('selected_keys.tsv', source)

    def test_per_release_scope_is_pinned_not_guessed(self):
        code = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/OcarinaShaderDelta.java").read_text()
        self.assertIn('header.vkChain.equals(columns[0])', code)
        self.assertIn('BuildConfig.NX_DMSH_VK_CHAIN.equals(columns[1])', code)
        self.assertIn('profile.shaderInputs.equals(columns[2])', code)
        self.assertIn('BuildConfig.NX_DMSH_VK_ABI.equals(columns[3])', code)
        self.assertIn('!unique.add(k)', code)
        scope = (ROOT / "dm/games/0400486024DEC000/vk_hot_delta.tsv").read_text()
        self.assertFalse(any(l.strip() and not l.startswith("#") for l in scope.splitlines()))

    def test_shaders_only_import_prepares_code_instead_of_blocking(self):
        # Real screen regression: the user imported all 42,339 merged shaders,
        # then Prepare incorrectly rejected the shader-only pack because
        # pack.tsv did not exist yet. A valid library must be checked first.
        source = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/Ondevice.java").read_text()
        start = source.index("File target = packOverride != null ? packOverride : AppStorage.pack(a, r.titleId);")
        end = source.index("long need = (imported ? DumpCheck.NEED_CODE", start)
        gate = source[start:end]
        self.assertLess(gate.index("boolean imported ="), gate.index("&& !Pack.libraryVersions(target).isEmpty() && !imported"))
        self.assertIn("&& ShaderZip.ready(target, r.titleId)", gate)
        self.assertIn("Job j = Job.create(r, AppStorage.pack(a, r.titleId));", source)
        self.assertIn("ShaderZip.ready(j.pack(), r.titleId)) j.shadersInPack();", source)
        job = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/Job.java").read_text()
        self.assertIn('o.put("shader_cache", new File(pack(), "shaders").getPath());', job)
        self.assertIn('o.put("shaders_imported", true);', job)

    @staticmethod
    def packer_functions():
        # Execute the REAL packer functions in isolation, not an alternate
        # copy of their logic or string-only assertions.
        source = ROOT / "scripts/pack_android.py"
        tree = ast.parse(source.read_text())
        wanted = {"library_current", "compatible_ocarina_full_library"}
        funcs = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
        assert {fn.name for fn in funcs} == wanted
        namespace = {
            "Path": pathlib.Path, "VK_LIB": "dmsh_vk.lib",
            "dmsh_chain": types.SimpleNamespace(inputs=lambda g: INPUTS),
            "lib_stamp": lambda d: {"game": GAME, "inputs": INPUTS}
                if (d / "dmsh_vk.lib").is_file() else {},
        }
        exec(compile(ast.Module(body=funcs, type_ignores=[]), str(source), "exec"), namespace)
        return namespace

    def test_merged_full_42339_import_is_used_even_with_six_entry_current_library(self):
        # An imported full v-b6b21f library and a six-shader current-chain
        # result can both have a correct inputs stamp. The 6-entry file must
        # NEVER be mistaken for the playable library used by pack_android.
        funcs = self.packer_functions()
        game = types.SimpleNamespace(id=GAME)
        pinned = self.p / "shaders/v-b6b21fb5753a/dmsh_vk.lib"
        write_lib(pinned, "b6b21fb5753a", 42339)
        current = self.p / f"shaders/v-{NEWVK}/dmsh_vk.lib"
        write_lib(current, NEWVK, 6)
        with mock.patch.object(delta, "abi_digest", return_value=ABI):
            self.assertFalse(funcs["library_current"](current.parent, game),
                             "six-shader hot result must not pass as complete base")
            self.assertTrue(funcs["library_current"](pinned.parent, game),
                            "42,339-shader full original-chain library must be recognized")
            self.assertEqual(
                funcs["compatible_ocarina_full_library"](self.p, game, NEWVK),
                pinned, "finalizing pack must use the actual imported full library")

            # A different same-chain 42,339-shader file with six modified
            # entry bytes is still valid; it must not be SHA-forced back to
            # the pristine historical file during code-only preparation.
            before = pinned.read_bytes()
            with pinned.open("r+b") as o:
                for key in [1, 111, 222, 333, 444, 555]:
                    o.seek(delta.HEAD.size + key * delta.ENTRY.size + 32)
                    o.write(b"R")
            changed = pinned.read_bytes()
            self.assertNotEqual(before, changed)
            self.assertEqual(len(before), len(changed))
            self.assertEqual(funcs["compatible_ocarina_full_library"](self.p, game, NEWVK), pinned)
            self.assertEqual(pinned.read_bytes(), changed,
                             "six updated records are not touched by pack recovery")

    def test_ooc_current_library_must_have_all_exact_42339_entries(self):
        funcs = self.packer_functions()
        game = types.SimpleNamespace(id=GAME)
        current = self.p / f"shaders/v-{NEWVK}/dmsh_vk.lib"
        with mock.patch.object(delta, "abi_digest", return_value=ABI):
            self.assertFalse(funcs["library_current"](current.parent, game),
                             "selective 2-entry hot result is NOT a full library")
            write_lib(current, NEWVK, 42338)
            self.assertFalse(funcs["library_current"](current.parent, game),
                             "42338 entries are incomplete")
            write_lib(current, NEWVK, 42339)
            self.assertTrue(funcs["library_current"](current.parent, game))
            write_lib(current, NEWVK, 42339, abi="ffffffffffff")
            self.assertFalse(funcs["library_current"](current.parent, game),
                             "wrong ABI must be refused even with 42,339 entries")

    def test_full_pipeline_remains_when_no_scope(self):
        source = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        self.assertIn('if (!hotKeys.isEmpty())', source)
        self.assertIn('lib.getPath()', source)
        self.assertIn('List<String> hotKeys = j.hotKeys();', source)
        self.assertNotIn('List<String> hotKeys = OcarinaShaderDelta.keys(j);', source)
        # A full pack must NEVER switch to hot overlay mode while finalizing.
        pack = (ROOT / "scripts/pack_android.py").read_text()
        self.assertIn('if a.hot_keys:', pack)
        self.assertIn('shaders: incremental update:', pack)
        self.assertIn('if not library_current(lib, g):', pack)


if __name__ == "__main__":
    unittest.main()
