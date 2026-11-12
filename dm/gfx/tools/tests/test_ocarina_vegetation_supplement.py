"""Production BNSH extraction and additive runtime lookup, without game files."""
import contextlib
import copy
import io
import os
import random
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'dm/gfx/tools'), str(ROOT / 'dm/tools/fuzz')]
import ocarina_vegetation as veg
import fuzzlib
from test_ocarina_cpu_written_serials import function
ss = fuzzlib.import_shader_split()


def fixture():
    d = bytearray(0x1000); d[:4] = b'BNSH'; d[0x60:0x64] = b'grsc'
    struct.pack_into('<IQ', d, 0x7c, 1, 0x100); struct.pack_into('<Q', d, 0x110, 0x200)
    rows = {}
    for slot, stage, desc, ctl, code in [(7, 6, 0x300, 0x400, 0x600), (8, 7, 0x340, 0x500, 0x700)]:
        struct.pack_into('<Q', d, 0x208 + 8*slot, desc)
        struct.pack_into('<QQII', d, desc+8, ctl, code, 0x100, 0xd8)
        d[ctl:ctl+8] = bytes.fromhex('34127698c9000000')
        struct.pack_into('<I', d, ctl+0x44, 0x100); d[ctl+0x56] = stage
        struct.pack_into('<HH', d, ctl+0x58, 32, 128)
        struct.pack_into('<HH', d, ctl+0x60, 96, 64); d[ctl+0x5f] = 3
        struct.pack_into('<I', d, code, 0x461); d[code+0x35] = 0xf0
        d[code+0x90] = stage  # different genuine code hashes for the two stages
    found = ss.bnsh_shaders(bytes(d), 0, '/Shader/test.bfsha')
    for where, st, ctl, code in found:
        key = ss.skey(ctl, code)
        facts = ss.mesh_facts(key, st, ctl, code, {}, set())
        facts['pair'] = ['1234567890abcdef']
        rows[key] = ('task' if st == 'ts' else 'mesh', where, facts)
    return d, rows


def sarc(members):
    """Synthetic named SARC, using the same wire layout as the game containers."""
    names = b''.join(n + b'\0' + bytes(-(len(n)+1) % 4) for n, _ in members)
    sfat = b'SFAT' + struct.pack('<HHI', 12, len(members), 0x65)
    data = b''; name_at = 0
    for name, payload in members:
        start = len(data); data += payload
        sfat += struct.pack('<IIII', 0, 0x1000000 | name_at//4, start, len(data))
        name_at += (len(name)+4)//4*4
        data += bytes(-len(data) % 0x100)
    end = 0x14 + len(sfat) + 8 + len(names); off = (end+255)//256*256
    head = b'SARC' + struct.pack('<HHII', 0x14, 0xfeff, off+len(data), off) + bytes(4)
    head += sfat + b'SFNT' + struct.pack('<HH', 8, 0) + names
    return head + bytes(off-len(head)) + data


class VegetationSupplement(unittest.TestCase):
    def test_dictionary_compressed_sarc_from_update_nup_and_directory(self):
        zstd = ss.zstd_mod()
        # Genuine trained dictionary, with the same dictionary ID as the
        # failing phone frame. No extracted game data is used.
        raw = bytearray(zstd.train_dict([random.Random(i).randbytes(2048)
                                       for i in range(100)], 1024).dict_content)
        struct.pack_into('<I', raw, 4, 1)
        dictionary = zstd.ZstdDict(bytes(raw))
        dictionary_pack = zstd.compress(sarc([(b'shaders.zsdic', bytes(raw))]))
        data, original = fixture()
        label = '/Shader/ApplicationPackage.Nin_Ounce_NVN2.release.sarc.zs/Model.Nin_Ounce_NVN2.bfsha'
        rows = {key: (stage, source.replace('/Shader/test.bfsha', label), facts)
                for key, (stage, source, facts) in original.items()}
        compressed = zstd.compress(sarc([(b'Model.Nin_Ounce_NVN2.bfsha', bytes(data))]), zstd_dict=dictionary)
        self.assertEqual(ss.zs_dict_id(compressed), 1)
        old_tables, old_cache = ss.ZDICTS, ss._ZD
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            root = Path(td); dump = root/'dump'
            base = dump/'base/romfs'; update = dump/'updates/131072/romfs'
            (base/'Pack').mkdir(parents=True); (update/'Shader').mkdir(parents=True)
            shader = update/'Shader/ApplicationPackage.Nin_Ounce_NVN2.release.sarc.zs'
            shader.write_bytes(compressed)
            # Before the fix, even a present dictionary was never registered.
            (update/'Pack').mkdir()
            (update/'Pack/ZsDic.pack.zs').write_bytes(dictionary_pack)
            ss.ZDICTS, ss._ZD = {}, {}
            try:
                result = veg.extract(str(update), root/'folder-pkg', rows, ss)
                self.assertEqual(set(result), set(rows))
                self.assertEqual(ss.ZDICTS, {})
                self.assertEqual(ss._ZD, {})
                # The NUP update has no dictionary pack of its own; resolve
                # its unchanged base dictionary through the real NUP reader.
                (update/'Pack/ZsDic.pack.zs').unlink()
                (base/'Pack/ZsDic.pack.zs').write_bytes(dictionary_pack)
                npdm = bytearray(0x100); npdm[0x80:0x84] = b'ACI0'
                struct.pack_into('<Q', npdm, 0x90, int(veg.TITLE, 16))
                exefs = dump/'base/exefs'; exefs.mkdir()
                (exefs/'main.npdm').write_bytes(npdm)
                nup = root/'Game With Spaces.nup'
                subprocess.run([sys.executable, str(ROOT/'dm/tools/nup_pack.py'),
                                str(dump), str(nup), '--raw'], check=True, capture_output=True)
                result = veg.extract(str(nup)+':update/131072/romfs', root/'nup-pkg', rows, ss)
                self.assertEqual(set(result), set(rows))
                self.assertEqual(ss.ZDICTS, {})
                self.assertEqual(ss._ZD, {})
                # The equivalent extracted directory uses the same base
                # fallback, without requiring the game to be repacked.
                result = veg.extract(str(update), root/'base-folder-pkg', rows, ss)
                self.assertEqual(set(result), set(rows))
                # A new unrelated dump cannot reuse dictionary ID 1 from the
                # preceding extraction. Missing dictionaries still fail.
                (base/'Pack/ZsDic.pack.zs').unlink()
                with self.assertRaisesRegex(SystemExit, 'needs zstd dictionary 1'):
                    veg.extract(str(update), root/'missing', rows, ss)
                self.assertEqual(ss.ZDICTS, {})
                self.assertEqual(ss._ZD, {})
            finally:
                ss.ZDICTS, ss._ZD = old_tables, old_cache

    def test_extended_slots_are_extracted_and_hash_checked(self):
        data, rows = fixture()
        self.assertEqual({v[0] for v in rows.values()}, {'task', 'mesh'})
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            root = Path(td); (root/'Shader').mkdir(); f = root/'Shader/test.bfsha'; f.write_bytes(data)
            locations = veg.extract(str(root), root/'pkg', rows, ss)
            self.assertEqual(set(locations), set(rows))
            for key, (name, index) in locations.items():
                raw = (root/'pkg'/name).read_bytes()
                self.assertEqual(raw[:8], b'BTCDBTCD')
                nc, nk = struct.unpack_from('<II', raw, 0x28)
                self.assertEqual(ss.skey(raw[0x38+nk:0x38+nk+nc], raw[0x38:0x38+nk]), key)
            # A changed code byte no longer has the reviewed original key.
            data[0x780] ^= 1; f.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'keys missing'):
                veg.extract(str(root), root/'bad', rows, ss)
            self.assertFalse((root/'bad/ms_vegetation.bin').exists())

    def test_layout_conflict_and_unrelated_extended_words(self):
        data, rows = fixture()
        bad = copy.deepcopy(rows)
        key = next(k for k, v in bad.items() if v[0] == 'mesh')
        bad[key][2]['mesh'][0] += 1
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            root = Path(td); (root/'Shader').mkdir(); (root/'Shader/test.bfsha').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'fact mismatch'):
                veg.extract(str(root), root/'pkg', bad, ss)
        struct.pack_into('<Q', data, 0x208 + 7*8, 0xffffffffffff)
        data[0x500:0x508] = bytes(8)
        self.assertEqual(ss.bnsh_shaders(bytes(data), 0, 'legacy-tail'), [])

    def test_reviewed_keys_cover_logged_foliage_and_dependencies(self):
        rows = veg.manifest()
        self.assertEqual(len(rows), 508)
        self.assertEqual(sum(v[0] == 'task' for v in rows.values()), 17)
        self.assertIn('0c1ffecd02018fb0', rows)
        self.assertIn('a5288d0a6c4971fd', rows)
        self.assertIn('d4171cf9adf0504b', rows)
        base = {c[3] for l in (veg.MANIFEST.parent/'shader_map.tsv').read_text().splitlines()
                if len(c := l.split('\t')) >= 5 and c[0].endswith('.bin')}
        self.assertFalse(set(rows) & base)
        veg.validate_dependencies(rows, base)
        with self.assertRaisesRegex(ValueError, 'dependency missing'):
            veg.validate_dependencies(rows, ())
        self.assertEqual(veg.HEADER.read_text(), veg.header_text())

    def test_real_runtime_load_gate_and_lookup_preserve_base(self):
        src = (ROOT/'dm/gfx/vk_android/vka_shader.c').read_text()
        helpers = '\n'.join(function(src, name) for name in ('vegetation_complete', 'library_for_key'))
        code = '''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "vka_shlib.h"
#include "vka_vegetation_supplement.h"
#include "../nvn/dmsh_chain_vk.h"
static vka_shlib g_lib, g_hot, g_vegetation;
static int g_hot_loaded, g_vegetation_loaded;
#define VKA_ENV(n,d) (d)
#define VLOG(...) ((void)0)
static int oot_hot_scene_fragment_compatible(const dmsh_vk_entry*a,const dmsh_vk_entry*b){return 0;}
static int oot_hot_compute_compatible(const dmsh_vk_entry*a,const dmsh_vk_entry*b){return 0;}
''' + helpers + '''
int main(void) {
    size_t n = sizeof vka_veg_entries / sizeof *vka_veg_entries;
    size_t m = sizeof vka_veg_dependencies / sizeof *vka_veg_dependencies;
    dmsh_vk_header vh={.entry_count=n}, bh={.entry_count=m};
    memcpy(vh.abi,DMSH_VK_ABI,12);
    dmsh_vk_entry *ve=calloc(n,sizeof *ve), *be=calloc(m,sizeof *be);
    dmsh_vk_module module={.variant=DMSH_VK_MOD_BASE};
    for (unsigned i=0;i<n;i++) ve[i]=(dmsh_vk_entry){.key=vka_veg_entries[i].key,.stage=vka_veg_entries[i].stage,.mod_count=1};
    for (unsigned i=0;i<m;i++) be[i].key=vka_veg_dependencies[i];
    g_vegetation=(vka_shlib){.h=&vh,.ent=ve,.mod=&module};
    g_lib=(vka_shlib){.h=&bh,.ent=be};
    assert(vegetation_complete(&g_vegetation,&g_lib));
    g_vegetation_loaded=1;
    for(unsigned i=0;i<n;i++) {
        const vka_shlib *chosen=library_for_key(ve[i].key);
        assert(chosen==(vka_shlib_find(&g_lib,ve[i].key)?&g_lib:&g_vegetation));
    }
    // Existing known keys always keep their stable module, including when
    // an old unvalidated hot overlay is absent or mesh quarantine is on.
    assert(library_for_key(be[m-1].key)==&g_lib);
    vh.entry_count--;assert(!vegetation_complete(&g_vegetation,&g_lib));vh.entry_count++;
    ve[0].stage=DMSH_VK_STAGE_CS;assert(!vegetation_complete(&g_vegetation,&g_lib));ve[0].stage=vka_veg_entries[0].stage;
    g_vegetation.by_abi=1;assert(!vegetation_complete(&g_vegetation,&g_lib));g_vegetation.by_abi=0;
    vh.inputs[0]=1;assert(!vegetation_complete(&g_vegetation,&g_lib));vh.inputs[0]=0;
    bh.entry_count=0;assert(!vegetation_complete(&g_vegetation,&g_lib));
    free(ve);free(be);return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            f = Path(td)/'test.c'; out = Path(td)/'test'; f.write_text(code)
            subprocess.run([shutil.which('clang') or 'cc', '-std=c11', '-D_GNU_SOURCE', '-g', '-O1',
                '-fsanitize=address,undefined', '-I'+str(ROOT/'dm/gfx/vk_android'),
                str(f), str(ROOT/'dm/gfx/vk_android/vka_shlib.c'), '-lzstd', '-o', str(out)], check=True)
            subprocess.run([str(out)], check=True, env={**os.environ, 'ASAN_OPTIONS':'detect_leaks=0'})


if __name__ == '__main__': unittest.main()
