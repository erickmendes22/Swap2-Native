#!/usr/bin/env python3
"""Opt-in 0.1.8.5 FD Shared buffer port: default, probe, map and restore guards."""
from pathlib import Path
import unittest

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

if __name__ == "__main__":
    unittest.main()
