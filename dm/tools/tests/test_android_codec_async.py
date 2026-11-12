"""Exercise production codec queues and NativeSync with delayed platform output."""
import ctypes.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class AndroidCodecAsync(unittest.TestCase):
    def test_delayed_platform_output(self):
        compiler = shutil.which("clang") or shutil.which("gcc")
        self.assertIsNotNone(compiler, "a C compiler is required")
        vpx = ctypes.util.find_library("vpx")
        self.assertIsNotNone(vpx, "the system libvpx runtime is required")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            subprocess.run([
                "python3", str(ROOT / "dm/games/game.py"), "header",
                "0400486024DEC000", str(work / "game_profile.h"),
            ], check=True, cwd=ROOT)
            executable = work / "codec_async"
            subprocess.run([
                compiler, "-D__ANDROID__", "-D__aarch64__",
                # The test executes portable C/POSIX, with no signal contexts
                # or ARM instructions. Suppress glibc's duplicate x86 signal
                # context definitions while including the Android host API.
                "-D_ASM_X86_SIGCONTEXT_H", "-std=gnu11", "-O1", "-g",
                "-Wall", "-Werror", "-Wno-unused-function",
                "-Wno-tautological-compare", "-fsanitize=address,undefined",
                "-ffunction-sections", "-fdata-sections", "-I" + directory,
                "-I" + str(ROOT / "dm/third_party/libvpx"),
                str(ROOT / "dm/host/tests/t_android_codec_async.c"),
                "-l:" + vpx, "-pthread", "-Wl,--gc-sections", "-o", str(executable),
            ], check=True, cwd=ROOT)
            environment = os.environ.copy()
            # LeakSanitizer cannot enumerate threads under this workspace's
            # tracer. ASan bounds/UAF and UBSan checks remain active.
            environment["ASAN_OPTIONS"] = "detect_leaks=0"
            result = subprocess.run(
                [str(executable)], check=True, timeout=30, env=environment,
                capture_output=True, text=True,
            )
            self.assertIn("20 delayed-output", result.stdout)


if __name__ == "__main__":
    unittest.main()
