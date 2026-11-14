"""Execute the production partial uploader against full deswizzle and Vulkan.

Checks every layer/mip, compressed storage, clean-image preservation and
fallbacks. Optional Vulkan readback uses the very same production commands.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]


class PartialUpload(unittest.TestCase):
    def run_harness(self, gpu):
        source = (ROOT / "dm/gfx/vk_android/vka_tex.c").read_text()
        sub = source[source.index("static void sub_range("):]
        sub = sub[:sub.index("\n// The finest level")]
        part = source[source.index("static uint64_t g_partial_uploads,"):]
        part = part[:part.index("\nvoid mtl_tex_init(")]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "partial_production.inc").write_text(sub + "\n" + part)
            cmd = [shutil.which("cc"), "-O1", "-g", "-std=gnu11", "-Wall", "-Wextra",
                   "-I", str(work), "-I", str(ROOT / "dm/gfx/vk_android"),
                   "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                   str(ROOT / "dm/host/tests/t_android_partial_upload.c"),
                   str(ROOT / "dm/gfx/nvn/nvn_tex.c"),
                   str(ROOT / "dm/gfx/tex/nvn_deswizzle.c")]
            if gpu:
                cmd += ["-DPARTIAL_GPU", "-DVKA_NDSR_PURE",
                        str(ROOT / "dm/gfx/vk_android/vka_ndsr.c"), "-ldl", "-lm"]
            else:
                cmd += ["-Werror", "-fsanitize=address,undefined"]
            exe = work / "partial"
            build = subprocess.run(cmd + ["-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0")
            run = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn("Validation Error", run.stdout + run.stderr)
            self.assertIn("partial uploads: exact", run.stdout)
            print(run.stdout)

    def test_full_deswizzle_oracle_and_fallbacks(self):
        self.run_harness(False)

    @unittest.skipUnless(os.getenv("MEMU_TEST_VULKAN") == "1", "real Vulkan ICD required")
    def test_vulkan_array_mip_readback(self):
        self.run_harness(True)


if __name__ == "__main__":
    unittest.main()
