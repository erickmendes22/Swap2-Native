"""Exact production VRS exclusion parsing, including malformed tail rejection."""
from pathlib import Path
import ctypes
import random
import shutil
import subprocess
import tempfile
import unittest

R = Path(__file__).resolve().parents[4]
V = R / 'dm/gfx/vk_android'


class VrsExclusion(unittest.TestCase):
    def test_actual_runtime_wrapper_handles_absent_invalid_and_truncated_lists(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        source = (V / 'vka_pso.c').read_text()
        start = source.index('static int vrs_excluded(uint64_t key)')
        end = source.index('// 0 = a stage', start)
        wrapper = source[start:end]
        fixture = '''
#include "vka_vrs_filter.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
static const char *setting;
static int vka_env_str(const char *key,char *out,size_t n) {
    (void)key;
    if (!setting) { if(n)out[0]=0; return 0; }
    snprintf(out,n,"%s",setting);return 1;
}
#define VRED_ONCE(...) ((void)0)
#define VLOG(...) ((void)0)
''' + wrapper + '''
int check(const char *value,uint64_t key) { setting=value;return vrs_excluded(key); }
'''
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory); c = tmp / 'runtime.c'; lib = tmp / 'runtime.so'
            c.write_text(fixture)
            built = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                    '-shared', '-fPIC', '-I', str(V), str(c), '-o', str(lib)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            check = ctypes.CDLL(str(lib)).check
            check.argtypes = [ctypes.c_char_p, ctypes.c_uint64]; check.restype = ctypes.c_int
            key = 0x5ad65c0eefd09c7f
            for value in (None, b'', b'1e4d2630d24846d0'):
                self.assertEqual(check(value, key), 0)
            for value in (b'5ad65c0eefd09c7f', b'not-hex', b'5ad65c0eefd09c7f,bad-key',
                          b'0,' * 511 + b'0', b'0,' * 1024 + b'0'):
                self.assertEqual(check(value, key), 1)

    def test_native_parser(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            source = tmp / 'parser.c'
            source.write_text('#include "vka_vrs_filter.h"\n'
                              'int check(const char *s, uint64_t k) { return vka_vrs_exclusion(s,k); }\n')
            library = tmp / 'parser.so'
            built = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                    '-shared', '-fPIC', '-I', str(V), str(source),
                                    '-o', str(library)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            check = ctypes.CDLL(str(library)).check
            check.argtypes = [ctypes.c_char_p, ctypes.c_uint64]
            check.restype = ctypes.c_int
            key = 0x5ad65c0eefd09c7f
            for value in (None, b'', b' \t\n', b'1e4d2630d24846d0', b'0', b'ffffffffffffffff'):
                self.assertEqual(check(value, key), 0, value)
            for value in (b'5ad65c0eefd09c7f', b' 0X5AD65C0EEFD09C7F ',
                          b'1e4d2630d24846d0,5ad65c0eefd09c7f,19f99e925937b038',
                          b'5ad65c0eefd09c7f,5ad65c0eefd09c7f'):
                self.assertEqual(check(value, key), 1, value)
            for value in (b',', b'0x', b'-1', b'0x10000000000000000',
                          b'0x00000000000000000', b'5ad65c0eefd09c7f0',
                          b'5ad65c0eefd09c7', b'5ad65c0eefd09c7f,',
                          b'5ad65c0eefd09c7f,,1', b'5ad65c0eefd09c7f,bad-key',
                          b'5ad65c0eefd09c7f;19f99e925937b038', b'5ad65c0eefd09c7f 1'):
                if value == b'5ad65c0eefd09c7':
                    self.assertEqual(check(value, key), 0)
                else:
                    self.assertEqual(check(value, key), -1, value)
            rng = random.Random(172)
            for _ in range(2000):
                keys = [rng.getrandbits(64) for _ in range(rng.randrange(1, 18))]
                selected = rng.choice(keys) if rng.randrange(2) else rng.getrandbits(64)
                tokens = [(('0x' if rng.randrange(2) else '') + f'{k:016x}') for k in keys]
                value = (' \t' + ', '.join(tokens) + '\n').encode()
                self.assertEqual(check(value, selected), int(selected in keys))
                # An earlier matching token cannot hide a malformed tail.
                self.assertEqual(check(value + b',not-hex', keys[0]), -1)

    def test_filter_only_narrows_existing_policy(self):
        source = (V / 'vka_pso.c').read_text()
        self.assertIn('profiled_hdr && !vrs_excluded(fs_hot))', source)
        self.assertIn('if (V.fps_boost_vrs && sh[1] && (balanced_hot || explicit_hot || extended_scene_hdr)', source)
        self.assertIn('if (excluded < 0)', source)
        self.assertIn('strlen(list) == sizeof list - 1 ? -1', source)
        self.assertIn('"DM_VK_VRS_EXCLUDE_FS"', source)
        self.assertIn('if (!vka_env_str(', source)
        self.assertIn('restart to change DM_VK_VRS_EXCLUDE_FS', source)
        ctl = (V / 'vka_ctl.c').read_text()
        restart = ctl[ctl.index('g_restart[]'):ctl.index('// Switches the replay reads again')]
        self.assertIn('"DM_VK_VRS_EXCLUDE_FS"', restart)


if __name__ == '__main__':
    unittest.main()
