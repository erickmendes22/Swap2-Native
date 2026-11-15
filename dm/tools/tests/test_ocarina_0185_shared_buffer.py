#!/usr/bin/env python3
"""Opt-in 0.1.8.5 FD Shared buffer port: default, probe, map and restore guards."""
from pathlib import Path
import unittest
import shutil
import subprocess
import tempfile
import sys

R = Path(__file__).resolve().parents[3]
V = R / "dm/gfx/vk_android"
J = R / "android/app/src/main/java/dev/nxnative/android"
HDR = (V / "vka.h").read_text()
DEV = (V / "vka_dev.c").read_text()
MEM = (V / "vka_mem.c").read_text()
ALIAS = (V / "vka_fd_alias.h").read_text()
PREF = (J / "Prefs.java").read_text()
ACT = (J / "GameActivity.java").read_text()
UI = (J / "GameSettings.java").read_text()

class SharedBufferOptIn(unittest.TestCase):
    def test_direct_mapping_default_and_per_game_state(self):
        self.assertIn('gameKey("gpu_shared_buffer", titleId), false', PREF)
        self.assertIn('Prefs.gpuSharedBuffer(a, id)', UI)
        self.assertIn('"Shared buffer (memória GPU, teste)"', UI)
        self.assertIn('Prefs.gpuSharedBuffer(this, id) ? "prefer" : "placed"', ACT)

    def test_driver_never_exposes_fd_without_probe(self):
        self.assertIn('VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME', DEV)
        self.assertIn('X(vkGetMemoryFdKHR)', HDR)
        self.assertIn('X(vkGetPhysicalDeviceExternalBufferProperties)', HDR)
        self.assertIn('vka_fd_probe(&vk, V.pd, V.dev, &V.memp, V.bda, reason, sizeof reason)', DEV)
        self.assertIn('V.fd_alias = 1;', DEV)
        self.assertIn('V.placed = V.placed_range = V.unmap_reserve = 0;', DEV)
        self.assertIn('Shared buffer unavailable', DEV)
        self.assertIn('Direct mapping selected', DEV)
        self.assertIn('V.placed || V.fd_alias', MEM)

    def test_alias_is_really_mapped_bidirectionally(self):
        self.assertIn('VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT', ALIAS)
        self.assertIn('VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT', ALIAS)
        self.assertIn('VK_MEMORY_PROPERTY_HOST_COHERENT_BIT', ALIAS)
        self.assertIn('vkGetMemoryFdKHR', ALIAS)
        self.assertIn('MAP_SHARED | MAP_FIXED', ALIAS)
        self.assertIn('mprotect(', ALIAS)
        self.assertIn('if (V.fd_alias == 1)', MEM)
        self.assertIn('s.fd_alias = 1;', MEM)
        self.assertIn('copy_readable(p, lo, pr, npr)', MEM)
        self.assertIn('MAP_SHARED | MAP_FIXED, exported.fd, 0', MEM)

    def test_unsafe_unmap_is_avoided_and_default_path_kept(self):
        self.assertIn('if (!s.fd_alias) unmap_placed(s.mem);', MEM)
        self.assertIn('if (!s.fd_alias && !elsewhere) seg_free(&s, waited, fence);', MEM)
        self.assertIn('if (s.fd_alias) seg_free(&s, waited, fence);', MEM)
        self.assertIn('if (s->fd_alias) vk.vkUnmapMemory(V.dev, s->mem);', MEM)
        self.assertIn('if (!(s.buf = seg_buffer(n)))', MEM)
        self.assertIn('VK_MEMORY_MAP_PLACED_BIT_EXT', MEM)

    def compile_fixture(self, source, extra=None, succeeds=True):
        if not shutil.which('cc'): self.skipTest('C compiler required')
        with tempfile.TemporaryDirectory() as d:
            c=Path(d)/'fixture.c';exe=Path(d)/'fixture';c.write_text(source)
            if extra is not None: (Path(d)/'shared_unplace.inc').write_text(extra)
            r=subprocess.run(['cc','-std=gnu11','-O1','-Wall','-Wextra',str(c),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run([str(exe)],capture_output=True,text=True)
            if succeeds: self.assertEqual(r.returncode,0,r.stderr)
            else: self.assertNotEqual(r.returncode,0,'negative control did not reproduce failure')

    def test_real_draw_gate_with_both_backends_and_overrides(self):
        source=(V/'vka_draw.c').read_text();start=source.index('static int g_force_draws;')
        gate=source[start:source.index('// ---------- State',start)]
        prefix="""
#include <assert.h>
#include <sys/resource.h>
struct {int placed,fd_alias;} V;
static int option;
#define VKA_ENV(key,default_value) option
#define VRED_ONCE(...) ((void)0)
"""
        cases="""
int main(void){
 struct rlimit limit={0,0};setrlimit(RLIMIT_CORE,&limit);
 const int options[]={-2,-1,0,1,2};
 for(int placed=0;placed<2;placed++)for(int fd=0;fd<2;fd++)
 for(int force=0;force<2;force++)for(unsigned i=0;i<5;i++){
  V.placed=placed;V.fd_alias=fd;option=options[i];vka_draw_force(force);
  int expected=force ? 1 : option>=0 ? option!=0 : (placed || fd);
  assert(draws_on()==expected);
 }
 V.placed=V.fd_alias=0;option=-1;vka_draw_force(0);assert(!draws_on());
 return 0;
}
"""
        self.compile_fixture(prefix+gate+cases)
        broken=gate.replace('(V.placed || V.fd_alias)','V.placed')
        self.assertNotEqual(broken,gate)
        self.compile_fixture(prefix+broken+cases,succeeds=False)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux memfd alias fixture")
    def test_real_fd_retirement_bytes_protection_and_free_order(self):
        start=MEM.index('static void unplace(const seg_t *sp)')
        unplace=MEM[start:MEM.index('\n}\n',start)+3]
        fixture=(R/'dm/host/tests/t_shared_buffer_retire.c').read_text()
        self.compile_fixture(fixture,extra=unplace)

if __name__ == "__main__":
    unittest.main()
