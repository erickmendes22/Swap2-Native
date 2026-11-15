#!/usr/bin/env python3
"""Regression for the small source-compatible ports from original 0.1.8.5.

The GPU alias/shared-buffer feature is intentionally NOT ported here:
it changes guest-memory lifetime and Vulkan device allocations.
"""
import contextlib
import io
import os
import pathlib
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
REWRITE = (ROOT / "dm/tools/patch_nso.py").read_text()
PACK = (ROOT / "scripts/pack_android.py").read_text()
LSFG = (ROOT / "android/app/src/main/java/dev/nxnative/android/Lsfg.java").read_text()
BEGIN = "FS_MODS = os.environ.get('DM_EXEFS_MODS', '')"
END = "if BUILD_ID in FRAME_STEP and NAME == 'main' and not fs_changed:"


def inspect_frame_step(original: bytes, actual: bytes, mod_names: str):
    # Execute the real dry-check block, not a handwritten equivalent.
    fragment = REWRITE[REWRITE.index(BEGIN):REWRITE.index(END)]
    def stub(ctx):
        ctx.site(0, original.hex())
        ctx.emit(0)
    scope = dict(os=os, types=types, BUILD_ID="build", NAME="main",
                 FRAME_STEP={"build": stub}, KEY_PAGE_OFF=0,
                 IMG=bytearray(actual), here=lambda: 0,
                 use_area=lambda n: None)
    with patch.dict(os.environ, {"DM_EXEFS_MODS": mod_names}, clear=False):
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            exec(fragment, scope)
    return scope['fs_changed'], printed.getvalue()


class Upstream0185Ports(unittest.TestCase):
    def test_unmodified_frame_step_remains_enabled(self):
        changed, output = inspect_frame_step(b"\x01\x02\x03\x04", b"\x01\x02\x03\x04", "")
        self.assertEqual(changed, [])
        self.assertNotIn("left out", output)

    def test_exefs_mod_at_frame_step_keeps_the_mod(self):
        changed, output = inspect_frame_step(b"\x01\x02\x03\x04", b"\x80\x02\x03\x04", "Dynamic-fps")
        self.assertTrue(changed)
        self.assertIn("left out", output)
        self.assertIn("Dynamic-fps", output)

    def test_unexplained_patch_mismatch_is_fatal(self):
        with self.assertRaisesRegex(AssertionError, "frame step original bytes mismatch"):
            inspect_frame_step(b"\x01\x02\x03\x04", b"\x80\x02\x03\x04", "")

    def test_packer_passes_labels_per_module_to_both_rewriters(self):
        self.assertIn("def applied_mod_labels(module):", PACK)
        self.assertIn("mods.get(module, ())", PACK)
        self.assertIn("'DM_EXEFS_MODS': applied_mod_labels(m)", PACK)
        self.assertIn("env=dict(env, DM_EXEFS_MODS=applied_mod_labels(m))", PACK)

    def test_lsfg_paths_prioritize_known_directories(self):
        self.assertIn('"/storage/emulated/0/LSFG/Lossless.dll"', LSFG)
        self.assertIn('"/storage/emulated/0/Lossless.dll"', LSFG)
        self.assertLess(LSFG.index('"/storage/emulated/0/Switch2/Lossless.dll"'),
                        LSFG.index('"/storage/emulated/0/LSFG/Lossless.dll"'))
        self.assertLess(LSFG.index('"/storage/emulated/0/LSFG/Lossless.dll"'),
                        LSFG.index('"/storage/emulated/0/Download/Lossless.dll"'))


if __name__ == "__main__":
    unittest.main()
