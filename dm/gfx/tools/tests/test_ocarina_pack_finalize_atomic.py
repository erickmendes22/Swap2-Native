"""Regression tests for the 96% / stage-5 Ocarina shader pack failure.

These tests import only the independently testable finalization function from
pack_android.py, so CI doesn't require a game dump, proprietary shader bytecode,
or a full 42,339 shader rebuild.
"""
import ast
import struct
import sys
import types
import errno
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[4]
SOURCE = (REPO / 'scripts/pack_android.py').read_text()
TREE = ast.parse(SOURCE)
FUNCTION = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'install_library_file')
ns = {'Path': Path, 'os': os, 'shutil': shutil, 'Error': type('PackError', (Exception,), {})}
exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), 'pack_android.py', 'exec'), ns)
publish = ns['install_library_file']
PackError = ns['Error']


class OcarinaOldLibraryRegression(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.pack = Path(self.t.name)
        self.old = self.pack/'shaders'/'v-b6b21fb5753a'/'dmsh_vk.lib'
        self.old.parent.mkdir(parents=True)
        sys.path.insert(0, str(REPO/'dm/gfx/tools'))
        import vk_android_delta as delta
        self.delta = delta
        g = types.SimpleNamespace(id='0400486024DEC000')
        self.g = g
        ns = {'Path': Path, 'dmsh_chain': types.SimpleNamespace(inputs=lambda _: 'aa5e7196d926')}
        fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'compatible_ocarina_full_library')
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'pack_android.py', 'exec'), ns)
        self.find = ns['compatible_ocarina_full_library']

    def write(self, inputs='aa5e7196d926', abi=None, count=42339):
        d=self.delta
        e=bytearray(count*d.ENTRY.size)
        for i in range(count):
            struct.pack_into('<Q', e, i*d.ENTRY.size, i+1)
            e[i*d.ENTRY.size+17]=1
        mod=d.MOD.pack(0, 20, 20, 0, 0, 0)
        blob=b'\x03\x02\x23\x07'+bytes(16)
        end=d.HEAD.size+len(e)
        head=d.HEAD.pack(d.VK['LIB_MAGIC'], d.VK['LIB_VERSION'],
            b'old-chain', b'b6b21fb5753a', self.g.id.encode(), inputs.encode(),
            count, d.HEAD.size, 0, end, 1, end, end+len(mod), len(blob),
            64, 64, (abi or d.abi_digest()).encode())
        self.old.write_bytes(head+e+mod+blob)

    def test_previous_42339_shader_library_reused_without_retranslation(self):
        self.write()
        self.assertEqual(self.find(self.pack, self.g, 'da4d5d4b7a18'),self.old)

    def test_wrong_shader_inputs_are_refused(self):
        self.write(inputs='badbadbadbad')
        self.assertIsNone(self.find(self.pack, self.g, 'da4d5d4b7a18'))

    def test_wrong_abi_is_refused(self):
        self.write(abi='000000000000')
        self.assertIsNone(self.find(self.pack, self.g, 'da4d5d4b7a18'))

    def test_incomplete_previous_library_is_refused(self):
        self.write(count=42000)
        self.assertIsNone(self.find(self.pack, self.g, 'da4d5d4b7a18'))

    def test_packer_recovery_precedes_no_current_error(self):
        self.assertLess(SOURCE.index("old = compatible_ocarina_full_library(out, g, v)"),
                        SOURCE.index("if a.in_process: raise Error(f'no current shader library"))
        service=(REPO/'android/app/src/ondevice/java/dev/nxnative/android/PackService.java').read_text()
        self.assertIn('if (!j.hotKeys().isEmpty()) return false', service)
        self.assertIn('File[] versions = shaderRoot.listFiles', service)


class ShaderPackFinalization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = root / 'ondevice' / 'lib' / 'v-current' / 'dmsh_vk.lib'
        self.output = root / 'packs' / 'Ocarina' / 'shaders' / 'v-current' / 'dmsh_vk.lib'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'shader-library-header' + b'x' * (1 << 20))

    def tearDown(self):
        self.tmp.cleanup()

    def test_hardlink_instead_of_second_full_copy(self):
        with mock.patch.object(shutil, 'copyfileobj', side_effect=AssertionError('large duplicate created')):
            message = publish(self.source, self.output)
        self.assertIn('hard link', message)
        self.assertTrue(os.path.samefile(self.source, self.output))
        self.assertEqual(self.output.stat().st_size, self.source.stat().st_size)

    def test_retry_does_not_destroy_existing_library(self):
        publish(self.source, self.output)
        initial_inode = self.output.stat().st_ino
        self.assertEqual(publish(self.source, self.output), 'already linked')
        self.assertEqual(self.output.stat().st_ino, initial_inode)
        self.assertTrue(self.source.exists())

    def test_external_storage_falls_back_to_copy_without_modifying_source(self):
        with mock.patch.object(os, 'link', side_effect=OSError(errno.EXDEV, 'cross-device')):
            with mock.patch.object(shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(1 << 31, 1 << 30, 1 << 30)):
                message = publish(self.source, self.output)
        self.assertIn('streamed copy', message)
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())
        self.assertFalse(os.path.samefile(self.source, self.output))
        self.assertTrue(self.source.exists())

    def test_android_fuse_rejects_links_but_atomic_move_needs_no_space(self):
        # FUSE may prohibit hard links even on the same filesystem.
        with mock.patch.object(os, 'link', side_effect=OSError(errno.EPERM, 'hard link blocked')):
            with mock.patch.object(shutil, 'copyfileobj', side_effect=AssertionError('duplicate shader library')):
                with mock.patch.object(shutil, 'disk_usage', side_effect=AssertionError('no copy performed')):
                    method = publish(self.source, self.output, move_private=True)
        self.assertIn('atomic move', method)
        self.assertFalse(self.source.exists())
        self.assertTrue(self.output.exists())
        self.assertEqual(self.output.read_bytes()[:21], b'shader-library-header')

    def test_source_cannot_be_moved_when_user_did_not_opt_in(self):
        with mock.patch.object(os, 'link', side_effect=OSError(errno.EPERM, 'FUSE denied')):
            with mock.patch.object(shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(1 << 31, 1 << 30, 1 << 30)):
                method = publish(self.source, self.output)
        self.assertIn('streamed copy', method)
        self.assertTrue(self.source.exists())

    def test_android_retry_recovers_finished_library_after_atomic_move(self):
        code = SOURCE
        self.assertIn('a.move_shader_cache and not library_current(lib, g) and library_current(dst, g)', code)
        self.assertIn('recovered completed library in', code)
        self.assertIn("'--move-shader-cache'", code)
        java = (REPO / 'android/app/src/ondevice/java/dev/nxnative/android/PackService.java').read_text()
        self.assertIn('boolean ownedCache = j.shaderCache().getCanonicalFile()', java)
        self.assertIn('"--move-shader-cache", "-j", "1", "--in-process"', java)
        self.assertIn('Math.min(need, 256L << 20)', java)

    def test_insufficient_space_refuses_duplicate_early_preserves_both(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b'old installed library')
        with mock.patch.object(os, 'link', side_effect=OSError(errno.EPERM, 'FUSE denied')):
            with mock.patch.object(shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(8 << 20, 6 << 20, 2 << 20)):
                with self.assertRaisesRegex(PackError, 'Retry will not translate the shaders again'):
                    publish(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'old installed library')
        self.assertEqual(self.source.stat().st_size, len(b'shader-library-header') + (1 << 20))
        self.assertFalse(self.output.with_name('dmsh_vk.lib.partial').exists())

    def test_interrupted_partial_file_is_replaced(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        partial = self.output.with_name('dmsh_vk.lib.partial')
        partial.write_bytes(b'dead partial from earlier failed attempt')
        publish(self.source, self.output)
        self.assertFalse(partial.exists())
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())

    def test_same_source_destination_is_noop(self):
        self.assertEqual(publish(self.source, self.source), 'already linked')
        self.assertTrue(self.source.exists())


if __name__ == '__main__':
    unittest.main()
