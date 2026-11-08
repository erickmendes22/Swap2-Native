"""dm/tools/exefs_patches.py, the exefs patches (mods) applied to a module before the Android rewrite, on synthetic files only (no mod of a real game is ever copied
here): IPS (records, RLE, the end marker), IPS32, IPSwitch .pchtxt (@nsobid, offset_shift, @enabled / @disabled, comments, strings, @stop); the selection by
build ID (a zero-padded file name, @nsobid) in the yuzu / Eden and Atmosphere layouts, in name order, '-' turning a mod off; the writes (the header ignored,
a code cave in text's page tail and a write into bss growing their segment, out-of-range writes refused before anything is written); the module key of
scripts/pack_android.py (unchanged without mods, ' mods=<digest>' with them) and its patched source copy; and the launcher's ExefsMods.java making the same
selection and digest (javac, skipped without a JDK)."""
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import lz4.block

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/tools'))
sys.path.insert(0, str(REPO / 'scripts'))
import exefs_patches as xp   # noqa: E402
import nso   # noqa: E402

BID = bytes.fromhex('0123456789abcdef0011223344556677' + '8899aabb') + bytes(12)   # a 20-byte build ID in its 0x20-byte field, as GNU build IDs are
TITLE = '0400000000ABC000'
TEXT, RO, DATA = bytes(range(256)) * 16 + bytes(0x10), b'read-only ' * 200, b'\x01\x02' * 0x500   # text 0x1010 bytes: its last page is 0x1000..0x2000


def page(x): return (x + 0xfff) & ~0xfff


def make_nso(segs=(TEXT, RO, DATA), bss=0x3000, bid=BID):
    """An NSO as Nintendo's tools write it: text and data LZ4, all hashed, a module name before text"""
    hdr, name, mo = bytearray(0x100), b'\x00\x00\x00\x00', 0
    hdr[:4] = b'NSO0'; hdr[0x40:0x60] = bid
    struct.pack_into('<II', hdr, 0x1c, 0x100, 0); struct.pack_into('<I', hdr, 0x2c, len(name))
    body = bytearray(name)
    for i, s in enumerate(segs):
        stored = lz4.block.compress(s, store_size=False) if i != 1 else s
        struct.pack_into('<III', hdr, 0x10 + i * 0x10, 0x100 + len(body), mo, len(s)); struct.pack_into('<I', hdr, 0x60 + 4 * i, len(stored))
        hdr[0xa0 + 0x20 * i:0xc0 + 0x20 * i] = hashlib.sha256(s).digest()
        body += stored; mo = page(mo + len(s))
    struct.pack_into('<I', hdr, 0xc, 0x38 | 1 | 4); struct.pack_into('<I', hdr, 0x3c, bss)
    return bytes(hdr + body)


def ips(records, rle=(), ips32=False):
    width, out = (4, b'IPS32') if ips32 else (3, b'PATCH')
    for off, data in records: out += off.to_bytes(width, 'big') + len(data).to_bytes(2, 'big') + data
    for off, n, v in rle: out += off.to_bytes(width, 'big') + b'\0\0' + n.to_bytes(2, 'big') + bytes([v])
    return out + (b'EEOF' if ips32 else b'EOF')


def write(p, b):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b if isinstance(b, bytes) else b.encode())
    return p


class Parse(unittest.TestCase):
    def test_ips_records_rle_and_end(self):
        r = xp.parse_ips(ips([(0x123456, b'\xaa\xbb')], rle=[(0x200, 5, 0x7f)]) + b'\x00\x10\x00', 'x.ips')   # a truncation size after EOF is ignored
        self.assertEqual(r, [xp.Record(0x123456, b'\xaa\xbb'), xp.Record(0x200, b'\x7f' * 5)])

    def test_ips32_offsets(self):
        self.assertEqual(xp.parse_ips(ips([(0x3c46300, b'1234')], ips32=True)), [xp.Record(0x3c46300, b'1234')])

    def test_damaged_files(self):
        for b, what in ((b'PATCH\x00\x01\x00\x00\x02ab', 'no EOF'), (b'PATCH\x00\x01\x00\x00\x09ab', 'past the end'), (b'PATCH\x00\x01', 'cut short'),
                        (b'IPS32\x00\x00\x01\x00\x00\x01aEOF', 'no EEOF'), (b'NOTIPS', 'not an IPS')):
            with self.subTest(what), self.assertRaisesRegex(xp.Error, what): xp.parse_ips(b, 'x.ips')

    def test_pchtxt(self):
        t = ('// a dynamic thing\r\n@nsobid-0123456789ABCDEF00112233445566778899AABB\n\n@flag offset_shift 0x100\n'
             '0010 deadbeef // set\n'
             '@enabled\n0020 0102 # one\n  0030 "a\\n/b" // a string keeps its slash\n0040 \'q\'\n'
             '@disabled\n0050 ffff\n'
             '@enabled\n0060 0A0b\n@stop\n0070 1111\n')
        bid, recs = xp.parse_pchtxt(t.encode(), 't.pchtxt')
        self.assertEqual(bid, BID.hex())
        self.assertEqual(recs, [xp.Record(0x120, b'\x01\x02'), xp.Record(0x130, b'a\n/b'), xp.Record(0x140, b'q'), xp.Record(0x160, b'\x0a\x0b')])

    def test_pchtxt_errors_and_ids(self):
        with self.assertRaisesRegex(xp.Error, 'even number'): xp.parse_pchtxt(b'@enabled\n0010 abc\n')
        with self.assertRaisesRegex(xp.Error, 'is not'): xp.parse_pchtxt(b'@enabled\nzz 00\n')
        self.assertIsNone(xp.pchtxt_build_id(b'// @nsobid-1234\n'))
        self.assertIsNone(xp.pchtxt_build_id(b'@stop\n@nsobid-1234\n'))
        self.assertEqual(xp.pchtxt_build_id(b'  @NSOBID-ab\n@nsobid-CD # later wins\n'), 'cd' + '0' * 62)


class Select(unittest.TestCase):
    def tree(self, root):
        t = root / TITLE
        write(t / 'b-mod/exefs' / (BID.hex()[:40].upper() + '.ips'), ips([(0x100, b'B')]))
        write(t / 'b-mod/exefs' / (BID.hex() + '.IPS'), ips([(0x101, b'b')]))   # the full 64 digits, extension in any case
        write(t / 'a-mod/ExeFS/any name.pchtxt', f'@nsobid-{BID.hex()[:40]}\n@enabled\n0002 41\n')
        write(t / 'a-mod/ExeFS/other.pchtxt', '@nsobid-ffff\n@enabled\n0002 41\n')   # another build
        write(t / 'a-mod/ExeFS' / ('ff' + BID.hex()[2:40] + '.ips'), ips([]))         # another build
        write(t / 'a-mod/ExeFS/readme.txt', 'not a patch')
        write(t / 'a-mod/ExeFS/.pchtxt', f'@nsobid-{BID.hex()[:40]}\n@enabled\n0002 41\n')   # hidden files are skipped
        write(t / 'b-mod/exefs' / ('._' + BID.hex()[:40] + '.ips'), ips([(0x100, b'X')]))
        write(t / '-off/exefs' / (BID.hex()[:40] + '.ips'), ips([]))                   # turned off
        write(t / 'c-mod/romfs/x.bin', 'no exefs')
        write(t / 'exefs_patches/atmo' / (BID.hex()[:32] + BID.hex()[32:40] + '.ips'), ips([(0x103, b'A')]))
        write(t / 'exefs_patches/-atmo-off' / (BID.hex()[:40] + '.ips'), ips([]))
        write(t / 'exefs_patches/short' / (BID.hex()[:32] + '.ips'), ips([]))         # 32 digits: bytes 0x10..0x14 are not zero, so not this build
        return t

    def test_find_order_layouts_and_matching(self):
        with tempfile.TemporaryDirectory() as d:
            self.tree(Path(d))
            got = [label for label, _ in xp.find(d, TITLE.lower(), BID)]
            self.assertEqual(got, ['a-mod/ExeFS/any name.pchtxt', f'b-mod/exefs/{BID.hex()[:40].upper()}.ips', f'b-mod/exefs/{BID.hex()}.IPS',
                                   f'exefs_patches/atmo/{BID.hex()[:40]}.ips'])
            self.assertEqual(xp.find(d, TITLE, bytes(0x20)), [])
            self.assertEqual(xp.find(Path(d) / 'none', TITLE, BID), [])
            self.assertEqual(xp.find(None, TITLE, BID), [])

    def test_digest_follows_files(self):
        with tempfile.TemporaryDirectory() as d:
            t = self.tree(Path(d))
            a = xp.digest(xp.find(d, TITLE, BID))
            self.assertEqual(a, xp.digest(xp.find(d, TITLE, BID.hex())))
            (t / 'exefs_patches/atmo' / (BID.hex()[:40] + '.ips')).write_bytes(ips([(0x103, b'Z')]))
            b = xp.digest(xp.find(d, TITLE, BID))
            (t / 'b-mod').rename(t / '-b-mod')
            c = xp.digest(xp.find(d, TITLE, BID))
            self.assertEqual(len({a, b, c}), 3)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
    def test_launcher_makes_the_same_choice(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); root = d / 'mods'; t = self.tree(root)
            write(t / 'a-mod/ExeFS/tricky.pchtxt', '  @n\n@nsobid-\n/ @nsobid-11\n@nsobid-0123 "q" // c\n@s\n@nsobid-99\n')
            src = REPO / 'android/app/src/main/java/dev/nxnative/android/ExefsMods.java'
            test = REPO / 'android/app/src/jvmtest/java/dev/nxnative/android/ExefsModsJvmTest.java'
            r = subprocess.run(['javac', '-Xlint:all', '-Werror', '-d', str(d / 'classes'), str(src), str(test)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ids = [BID.hex(), BID.hex()[:40], '0' * 64]
            r = subprocess.run(['java', '-cp', str(d / 'classes'), 'dev.nxnative.android.ExefsModsJvmTest', str(root), TITLE, *ids], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            want = []
            for i in ids:
                f = xp.find(root, TITLE, i)
                want.append(f'find {i} ' + ('|'.join(label for label, _ in f) or '-') + ' ' + (xp.digest(f) if f else '-'))
            for p in sorted(root.rglob('*')):
                if p.is_file() and p.name.lower().endswith('.pchtxt'): want.append(f'pchtxt {p.relative_to(root).as_posix()} {xp.pchtxt_build_id(p.read_bytes()) or "-"}')
            want.append('key 0123|')
            self.assertEqual(r.stdout.splitlines(), want)

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'no JDK')
    def test_launcher_mods_section(self):
        # The game settings' Mods section (ExefsMods list / on and off / remove / install): its JVM checks, on a temporary folder of their own
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = REPO / 'android/app/src/main/java/dev/nxnative/android/ExefsMods.java'
            test = REPO / 'android/app/src/jvmtest/java/dev/nxnative/android/ExefsModsJvmTest.java'
            r = subprocess.run(['javac', '-Xlint:all', '-Werror', '-d', str(d / 'classes'), str(src), str(test)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run(['java', '-cp', str(d / 'classes'), 'dev.nxnative.android.ExefsModsJvmTest', '--install'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(r.stdout.startswith('ok '), r.stdout)


class Apply(unittest.TestCase):
    def files(self, d, *blobs):
        return [(f'm/exefs/{i}.ips', write(Path(d) / f'{i}.ips', b)) for i, b in enumerate(blobs)]

    def test_writes_cave_and_bss(self):
        data = make_nso()
        m0 = nso.load(data)
        bss_at = m0.segments[2][0] + m0.segments[2][1]
        with tempfile.TemporaryDirectory() as d:
            files = self.files(d, ips([(0x10, b'HEADER!!'), (0xfc, b'\xee' * 8)]),                # the header part is ignored, the rest lands at 0
                               ips([(0x100 + 0x1800, b'\xc0\x03\x5f\xd6')], ips32=True),           # a code cave in text's page tail (text is 0x1010 bytes)
                               ips([(0x100 + bss_at + 0x20, b'\x55' * 4)], rle=[(0x100 + 0x40, 3, 0x99)]))   # into bss, and RLE into text
            out, report = xp.apply(data, files, 'main')
        m = nso.load(out, 'patched')   # hashes checked
        self.assertEqual(m.build_id, BID)
        self.assertEqual(report, [('m/exefs/0.ips', 2, 4), ('m/exefs/1.ips', 1, 4), ('m/exefs/2.ips', 2, 7)])
        self.assertEqual(bytes(m.image[:4]), b'\xee' * 4)
        self.assertEqual(bytes(m.image[0x40:0x43]), b'\x99' * 3)
        self.assertEqual(m.segments[0], (0, 0x1804)); self.assertEqual(bytes(m.image[0x1800:0x1804]), b'\xc0\x03\x5f\xd6')
        self.assertEqual(m.segments[1], m0.segments[1])
        self.assertEqual(m.segments[2], (m0.segments[2][0], m0.segments[2][1] + 0x24))
        self.assertEqual(m.bss, m0.bss - 0x24)   # the module ends where it did
        self.assertEqual(bytes(m.image[bss_at + 0x20:bss_at + 0x24]), b'\x55' * 4)
        self.assertEqual(bytes(m.image[0x1010:0x1800]), bytes(0x7f0))
        self.assertEqual(bytes(m.image[0x100:0x1000]), TEXT[0x100:0x1000])
        self.assertEqual(bytes(m.image[m.segments[1][0]:][:len(RO)]), RO)

    def test_out_of_range_is_refused_before_writing(self):
        data = make_nso()
        m0 = nso.load(data)
        end = m0.segments[2][0] + m0.segments[2][1] + m0.bss
        with tempfile.TemporaryDirectory() as d:
            for what, blob in (('outside the module', ips([(0x100 + end, b'x')], ips32=True)),
                               ('across a segment', ips([(0x100 + 0x1ffe, b'xxxx')])),   # text's page tail into ro's first page
                               ('outside the module', ips([(0x100 + 0x2000 + 0x10000, b'x')], ips32=True))):
                with self.subTest(what), self.assertRaisesRegex(xp.Error, what):
                    xp.plan(data[:0x100], self.files(d, ips([(0x100, b'ok')]), blob), 'main')

    def test_nro_is_refused(self):
        with self.assertRaisesRegex(xp.Error, 'NSO'): xp.layout(bytes(0x10) + b'NRO0' + bytes(0x100))


class PackKey(unittest.TestCase):
    def test_key_and_source_copy(self):
        import pack_android
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prof = d / 'profile'; write(prof / 'game.tsv', 'name\tTest\n')
            g = types.SimpleNamespace(dir=prof, id=TITLE)
            src = write(d / 'game/exefs/main', make_nso())
            files = [('m/exefs/a.ips', write(d / 'mods/a.ips', ips([(0x100, b'\x1f\x20\x03\xd5')])))]
            plain = pack_android.rewrite_key(src, g)
            self.assertTrue(plain.endswith(' target=android'))
            self.assertEqual(plain, pack_android.rewrite_key(src, g, ()))
            k = pack_android.rewrite_key(src, g, files)
            self.assertEqual(k.split(' ')[1:], ['target=android', 'mods=' + xp.digest(files)])
            self.assertNotEqual(k.split(' ')[0], plain.split(' ')[0])   # exefs_patches.py is in the key with mods
            out = d / 'pack'; out.mkdir()
            self.assertEqual(pack_android.rewriter_src(src, out, 'main'), src)
            f = pack_android.rewriter_src(src, out, 'main', files)
            self.assertEqual(f, out / '.nup-src/main/main')
            self.assertEqual(bytes(nso.read(f).image[:4]), b'\x1f\x20\x03\xd5')


if __name__ == '__main__':
    unittest.main()
