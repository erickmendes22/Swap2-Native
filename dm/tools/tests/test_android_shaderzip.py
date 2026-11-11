"""The Android launcher's Export shaders… / Import shaders… (ShaderZip.java) on the JVM: javac compiles it with PackZip, Pack, Nup, Zstd, Profile, ShaderLibs,
SaveStore, a stub BuildConfig and android/app/src/jvmtest's ShaderZipJvmTest: an export and import round trip (a stored zip in the layout's order, read back,
reused when it is there; the imported library equal byte for byte, into a pack and into a folder with no pack), which library an export takes, every refusal with
the target pack unchanged (another title, version or inputs; a header that disagrees with the manifest; tables outside the file; a flipped byte; a truncated zip;
too big; no space; zip slip and extra or duplicate entries; the library before the manifest from a stream; a manifest over 64 KiB), a cancel, the atomic replace
and its recovery, an older library restamped into this version, and the zips found for a title. Then, when scripts/shaders_zip.py is there, a zip made by it from
a synthetic library is imported by the JVM code (the computer's and the phone's format are one). Skipped without a JDK."""
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / 'android/app/src/main/java/dev/nxnative/android'
TEST = REPO / 'android/app/src/jvmtest/java/dev/nxnative/android/ShaderZipJvmTest.java'
SCRIPT = REPO / 'scripts/shaders_zip.py'
CUR, ABI, ID, INPUTS = 'aaaaaaaaaaaa', 'bbbbbbbbbbbb', '040074A01BF12000', 'abcdef012345'
STUB = '''package dev.nxnative.android;
public final class BuildConfig {
    public static final String NX_PROFILES = "040074A01BF12000\\tDonkey Kong Bananza\\t22852\\tabcdef012345\\t458752 main=aa\\t\\tplayable\\t\\t\\n0400C3F00006E000\\tMario Kart World\\t0\\tunknown\\t\\n0400486024DEC000\\tOcarina of Time\\t42339\\tabcdef012345\\t131072 main=aa\\t\\tplayable\\t";
    public static final String NX_DMSH_VK_CHAIN = "aaaaaaaaaaaa", NX_DMSH_VK_ABI = "bbbbbbbbbbbb";
}
'''


def synthetic_lib(entries=3, blob=5000):
    """A library with a valid 128-byte header (dmsh_abi_vk.h dmsh_vk_header) and its tables"""
    h = bytearray(128)
    struct.pack_into('<II', h, 0, 0x4B56534D, 1)
    for off, s in ((8, 'chain0000000'), (24, CUR), (40, ID), (56, INPUTS)): h[off:off + len(s)] = s.encode()
    struct.pack_into('<IIIIIIQQ', h, 72, entries, 128, 0, 0, 0, 0, 128 + entries * 64, blob)
    h[116:128] = ABI.encode()
    return bytes(h) + bytes(entries * 64) + hashlib.sha256(b'x').digest() * (blob // 32) + bytes(blob % 32)


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
class ShaderZipJvm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.d = Path(cls.tmp.name)
        (d / 'stub').mkdir()
        (d / 'stub/BuildConfig.java').write_text(STUB)
        (d / 'stub/Prefs.java').write_text(
            'package dev.nxnative.android; final class Prefs { '
            'static final String OCARINA_TITLE = "0400486024DEC000"; }\\n'
        )
        srcs = [SRC / f'{n}.java' for n in ('ShaderZip', 'PackZip', 'Pack', 'Nup', 'Zstd', 'Profile', 'ShaderLibs', 'ShaderAbiCert', 'SaveStore', 'SaveZip')]
        r = subprocess.run(['javac', '-encoding', 'UTF-8', '-Xlint:all,-try', '-Werror', '-d', str(d / 'classes'), *map(str, srcs), str(TEST), str(d / 'stub/BuildConfig.java'), str(d / 'stub/Prefs.java')],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def java(self, *args):
        return subprocess.run(['java', '-cp', str(self.d / 'classes'), 'dev.nxnative.android.ShaderZipJvmTest', *args], capture_output=True, text=True)

    def test_cases(self):
        (self.d / 'run').mkdir()
        r = self.java(str(self.d / 'run'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith('ok '), r.stdout)

    @unittest.skipUnless(SCRIPT.is_file(), 'no scripts/shaders_zip.py')
    def test_computer_zip(self):
        lib_dir = self.d / 'mac/android-shaders/lib' / f'v-{CUR}'
        lib_dir.mkdir(parents=True)
        (lib_dir / 'dmsh_vk.lib').write_bytes(synthetic_lib())
        (lib_dir / 'inputs.tsv').write_text(f'# stamp\ngame\t{ID}\ninputs\t{INPUTS}\n')
        pack = self.d / 'mac/android-pack'
        pack.mkdir(parents=True)
        (pack / 'pack.tsv').write_text(f'format\t2\ntarget\tandroid\ntitle_id\t{ID}\nname\tDonkey Kong Bananza\nversion\t458752\nbuild\tmain=aa\n')
        out = self.d / 'mac/out'
        r = subprocess.run([sys.executable, str(SCRIPT), str(lib_dir), '--out', str(out), '--pack', str(pack)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        zips = list(out.glob('*.zip'))
        self.assertEqual([z.name for z in zips], [f'swap2-shaders-{ID}-458752-v-{CUR}.zip'], r.stdout)
        self.assertFalse(list(out.glob('*.partial')))
        r = self.java('import', str(zips[0]), str(self.d / 'phone'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.split(), ['imported', CUR, '3', 'true'])
        self.assertEqual((self.d / f'phone/shaders/v-{CUR}/dmsh_vk.lib').read_bytes(), (lib_dir / 'dmsh_vk.lib').read_bytes())
        # a second run finds the same zip there and keeps it
        r = subprocess.run([sys.executable, str(SCRIPT), str(lib_dir), '--out', str(out), '--pack', str(pack)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(list(out.glob('*.zip'))), 1)
        # a library that is not one fails
        bad = self.d / 'mac/bad/v-x'
        bad.mkdir(parents=True)
        (bad / 'dmsh_vk.lib').write_bytes(b'not a library')
        r = subprocess.run([sys.executable, str(SCRIPT), str(bad), '--out', str(out)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
