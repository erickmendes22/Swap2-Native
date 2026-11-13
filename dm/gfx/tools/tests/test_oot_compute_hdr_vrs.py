"""Execute the production VRS eligibility predicate after real mesh routing.

The observed compute VS must retain the previously configured HDR pass rate.
This is a pipeline-selection regression, not a phone timing prediction.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
PSO = (ROOT / 'dm/gfx/vk_android/vka_pso.c').read_text()
HEADER = (ROOT / 'dm/gfx/vk_android/vka_memu.h').read_text()
DRAW = (ROOT / 'dm/gfx/vk_android/vka_draw.c').read_text()


def function(name):
    start = PSO.index('static int ' + name + '(')
    opening = PSO.index('{', start)
    depth = 1
    for i in range(opening + 1, len(PSO)):
        depth += (PSO[i] == '{') - (PSO[i] == '}')
        if depth == 0:
            return PSO[start:i + 1]
    raise AssertionError('unterminated function')


class ComputeHdrVrs(unittest.TestCase):
    def test_actual_predicate_native_and_converted_mesh(self):
        cc = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(cc)
        definitions = '\n'.join(re.search(r'^#define ' + name + r' .*$', HEADER, re.M).group()
                                for name in ('VKA_MEMU_KEY_VS', 'VKA_MEMU_KEY_COALESCED'))
        source = r'''
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#define VKA_NSTAGE 8
#define VK_FORMAT_R16G16B16A16_SFLOAT 97
#define VK_FORMAT_B10G11R11_UFLOAT_PACK32 122
typedef struct { uint64_t key; int memu; } vka_shader;
typedef struct { uint32_t ncolor, cfmt[8]; } vka_gkey;
static uint64_t layout;
static uint64_t vka_memu_layout_tag(void) { return layout; }
''' + definitions + '\n' + function('oot_profiled_mesh_hdr') + r'''
int main(void) {
    vka_shader fs = {UINT64_C(0x5ad65c0eefd09c7f), 0};
    vka_shader ts = {UINT64_C(0xefaa4fa6a80ba719), 0};
    vka_shader ms = {UINT64_C(0x066f5daf12e43c71), 0};
    vka_shader vs = {0, 2};
    vka_shader *sh[8] = {0}; sh[1] = &fs;
    vka_gkey k = {.ncolor = 2, .cfmt = {97, 97}};
    for (int coalesced = 0; coalesced < 2; coalesced++) {
        layout = coalesced ? VKA_MEMU_KEY_COALESCED : 0;
        sh[0] = 0; sh[6] = &ts; sh[7] = &ms;
        assert(oot_profiled_mesh_hdr(sh, &k, 1));
        ts.key ^= 1; assert(!oot_profiled_mesh_hdr(sh, &k, 1)); ts.key ^= 1;
        ms.key ^= 1; assert(!oot_profiled_mesh_hdr(sh, &k, 1)); ms.key ^= 1;
        // This is draw_body's production replacement, not native mesh.
        vs.key = ms.key ^ VKA_MEMU_KEY_VS ^ layout;
        if (coalesced) assert(vs.key == UINT64_C(0x086551b608e12c6b));
        sh[0] = &vs; sh[6] = sh[7] = 0;
        assert(oot_profiled_mesh_hdr(sh, &k, 0));
        assert(!oot_profiled_mesh_hdr(sh, &k, 1));
        vs.key ^= 1; assert(!oot_profiled_mesh_hdr(sh, &k, 0)); vs.key ^= 1;
        vs.memu = 0; assert(!oot_profiled_mesh_hdr(sh, &k, 0));
        vs.memu = 1; assert(!oot_profiled_mesh_hdr(sh, &k, 0)); vs.memu = 2;
        fs.key ^= 1; assert(!oot_profiled_mesh_hdr(sh, &k, 0)); fs.key ^= 1;
        sh[1] = 0; assert(!oot_profiled_mesh_hdr(sh, &k, 0)); sh[1] = &fs;
        for (unsigned n = 0; n <= 8; n++) {
            k.ncolor = n;
            assert(oot_profiled_mesh_hdr(sh, &k, 0) == (n == 2));
        }
        k.ncolor = 2;
        for (int att = 0; att < 2; att++) {
            for (unsigned format = 0; format <= 184; format++) {
                k.cfmt[att] = format;
                assert(oot_profiled_mesh_hdr(sh, &k, 0) == (format == 97));
            }
            k.cfmt[att] = 97;
        }
        sh[0] = 0; assert(!oot_profiled_mesh_hdr(sh, &k, 0));
    }
    puts("HDR VRS: observed compute VS eligible in both layouts; unrelated passes excluded");
}
'''
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'hdr.c'
            path.write_text(source)
            binary = Path(td) / 'hdr'
            subprocess.run([cc, '-std=c11', '-O1', '-g', '-fsanitize=address,undefined',
                            str(path), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)

    def test_real_pipeline_uses_predicate_and_retains_opt_out_and_driver_guards(self):
        self.assertIn('sh[0] = memu_e->vs; sh[6] = sh[7] = NULL; mesh = 0;', DRAW)
        self.assertIn('profiled_mesh_hdr = oot_profiled_mesh_hdr(sh, k, mesh)', PSO)
        self.assertIn('V.fps_boost_vrs && sh[1] && (balanced_hot || explicit_hot || extended_scene_hdr)', PSO)
        self.assertIn('(k->samples ? k->samples : 1) == 1', PSO)
        self.assertIn('hotpass_profile > 0 && scene_hot && game_oot', PSO)
        self.assertIn('P->fsrate.pNext = &P->ri;', PSO)
        self.assertIn('gpl_on() && !P->mesh && !P->fsrate.sType', PSO)


if __name__ == '__main__':
    unittest.main()
