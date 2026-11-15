"""Production Android Ocarina MapPhysicalMemory budget policy: actual branch
from game_rt.c, and native SVC guards. Does not claim device PSS savings.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PROFILE = (ROOT / "dm/host/rt/game_rt.c").read_text()
SVC = (ROOT / "dm/host/hle_svc.c").read_text()


class OcarinaAppPoolBudget(unittest.TestCase):
    def test_native_runtime_default_and_rollback(self):
        start = PROFILE.index('    if (dm_game.id && !strcmp(dm_game.id, "0400486024DEC000")) {')
        end = PROFILE.index("\n#endif", start)
        policy = PROFILE[start:end]
        self.assertIn("#if defined(__ANDROID__)", PROFILE[:start])
        code = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static struct {const char *id; int mem_map_limit;} dm_game;
#define LOG(...) ((void)0)
static void apply(void) {
''' + policy + r'''
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    dm_game.id = argv[1];
    dm_game.mem_map_limit = atoi(argv[2]);
    apply();
    printf("%d\n", dm_game.mem_map_limit);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            src, binary = Path(td) / "budget.c", Path(td) / "budget"
            src.write_text(code)
            cc = shutil.which("clang") or shutil.which("cc")
            self.assertIsNotNone(cc)
            p = subprocess.run([cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                                str(src), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            for gid, packed, override, expected in (
                ("0400486024DEC000", 0, None, 1),
                ("0400486024DEC000", 1, None, 1),
                ("0400486024DEC000", 0, "1", 1),
                ("0400486024DEC000", 1, "0", 0),
                ("0400486024DEC000", 0, "0", 0),
                ("040074A01BF12000", 0, None, 0),
                ("040074A01BF12000", 0, "1", 0),
                ("040074A01BF12000", 1, "0", 1),
            ):
                env = {k: v for k, v in os.environ.items() if k != "DM_MEM_MAP_LIMIT"}
                if override is not None:
                    env["DM_MEM_MAP_LIMIT"] = override
                p = subprocess.run([str(binary), gid, str(packed)], env=env,
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(int(p.stdout), expected, (gid, packed, override))

    def test_real_svc_limits_both_heap_and_physical_mapping(self):
        self.assertIn("if (DM_GAME_MEM_MAP_LIMIT && num == 0x2C)", SVC)
        self.assertIn("g_heap_cur + DM_GAME_MEM_USED + big_bss_bytes()", SVC)
        self.assertIn("atomic_load(&g_alias_mapped)", SVC)
        self.assertIn("regs[0] = 0x10801; return 0;", SVC)
        self.assertIn("if (DM_GAME_MEM_MAP_LIMIT && (charged > APP_POOL || size > APP_POOL - charged))", SVC)
        self.assertIn("if (DM_GAME_MEM_MAP_LIMIT) v += (uint64_t)atomic_load(&g_alias_mapped);", SVC)


if __name__ == "__main__":
    unittest.main()
