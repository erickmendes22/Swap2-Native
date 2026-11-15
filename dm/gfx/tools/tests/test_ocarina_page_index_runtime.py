"""Regressions for the optional Ocarina GMEM index, not GPU FPS claims."""
from pathlib import Path
import unittest
import re

ROOT = Path(__file__).resolve().parents[4]
HOST = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
XLATE = (ROOT / "dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Translation/Optimizations/GlobalToStorage.cs").read_text()
PREFS = (ROOT / "android/app/src/main/java/dev/nxnative/android/Prefs.java").read_text()
APP = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameActivity.java").read_text()
UI = (ROOT / "android/app/src/main/java/dev/nxnative/android/GameSettings.java").read_text()
PACKSERVICE = (ROOT / "android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
HOTBUILDER = (ROOT / "scripts/build_ocarina_hot_shaders.py").read_text()
VKA_HEADER = (ROOT / "dm/gfx/vk_android/vka.h").read_text()
GBAR = (ROOT / "dm/gfx/vk_android/vka_gbar.c").read_text()
VKA_DEVICE = (ROOT / "dm/gfx/vk_android/vka_dev.c").read_text()


class PageIndexContracts(unittest.TestCase):
    def test_only_opt_in_and_existing_lookup_retained(self):
        self.assertIn('Environment.GetEnvironmentVariable("DMSH_GMEM_PIDX") == "1"', XLATE)
        self.assertIn('DMSH_GMEM_MAP_8192', XLATE)
        self.assertIn('new int[7]', XLATE)
        start = XLATE.index("private static void GenerateRawAccess(")
        end = XLATE.index("private static Operand MissedAccessResult(", start)
        s = XLATE[start:end]
        self.assertLess(s.index("context.MarkLabel(hintMiss);"), s.index("if (pageIndex)"))
        self.assertLess(s.index("if (pageIndex)"), s.index("int mapLog2 = extendedMap ? 13"))
        self.assertIn('context.BranchIfFalse(indexMiss, covered);', s)
        self.assertIn('context.BranchIfFalse(indexMiss, valid);', s)
        self.assertIn('context.Branch(afterSearch);', s)
        self.assertIn('context.ICompareLessUnsigned(candidate, Const(8192))', s)
        self.assertIn('context.ICompareLessUnsigned(addrHigh, Const(1 << 12))', s)

    def test_host_immutable_memory_and_cap(self):
        self.assertIn('g_pidx_submission_bytes = 0;', HOST)
        self.assertIn('const size_t index_cap = 2u << 20, budget = 4u << 20;', HOST)
        self.assertIn('if (extra) g_pidx_submission_bytes += extra;', HOST)
        self.assertIn('vka_gmem_pidx_build(', HOST)
        self.assertIn('vka_scratch(bytes, V.sb_align, &s)', HOST)
        self.assertIn('vka_scratch(n + 16, V.sb_align, &s)', HOST)
        self.assertIn('g_gm.bytes = bytes;', HOST)
        self.assertIn('g_gm.s.off, g_gm.bytes', HOST)

    def test_optional_launcher_and_ui(self):
        self.assertIn('getBoolean(gameKey("gpu_page_index", id), false)', PREFS)
        self.assertIn('DM_VK_GMEM_PIDX=', APP)
        self.assertIn('Prefs.gpuPageIndex', UI)
        self.assertIn('s2_gpu_page_index_note', UI)
        self.assertIn('PackEngine.setenv("DMSH_GMEM_PIDX", ocarinaShaders ? "1" : "0");', PACKSERVICE)
        self.assertIn('DMSH_GMEM_PIDX="1"', HOTBUILDER)


    def test_guest_barrier_dispatch_entries_are_declared_and_loaded(self):
        # The optional narrow-barrier wrapper installs hooks for several Vulkan
        # query commands. All hooked commands must exist in vka_fns, and the
        # central device loader must initialize them before installing hooks.
        declared = VKA_HEADER.split("#define VKA_DEVICE_FNS(X)", 1)[1].split("#define VKA_DECL(f)", 1)[0]
        hooked = GBAR.split("#define GB_FNS(X)", 1)[1].split("#define GB_DECL(f)", 1)[0]
        device_functions = set(re.findall(r"X\\((vk\\w+)\\)", declared))
        hooked_functions = set(re.findall(r"X\\((vk\\w+)\\)", hooked))
        self.assertTrue(hooked_functions)
        self.assertEqual(set(), hooked_functions - device_functions,
                         "The barrier hook references Vulkan function pointers not declared in vka_fns")
        self.assertIn("VKA_DEVICE_FNS(D)", VKA_DEVICE)
        self.assertLess(VKA_DEVICE.index("VKA_DEVICE_FNS(D)"),
                        VKA_DEVICE.index("vka_gbar_install();"))



if __name__ == "__main__":
    unittest.main()
