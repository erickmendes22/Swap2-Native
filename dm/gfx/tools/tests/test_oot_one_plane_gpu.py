"""Single vec4 unused-plane GPU experiment on actual Vulkan.

This measures 8 vs 7 output planes, unlike the older 8 vs 2 benchmark.
Runs on Mesa Lavapipe for correctness / directional evidence ONLY;
it is NOT an Adreno FPS or phone performance measurement.
"""
import json
import os
import shutil
import statistics
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from dm.gfx.tools.tests.test_ocarina_gpu_masked_write_benchmark import source

ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "dm/host/tests/t_android_memu_dispatch.c"

class OneUnusedPlaneGpu(unittest.TestCase):
    @unittest.skipUnless(os.getenv("MEMU_TEST_VULKAN") == "1",
                         "requires actual Vulkan ICD, set MEMU_TEST_VULKAN=1")
    def test_single_unused_vec4_real_gpu(self):
        cc = shutil.which("cc") or shutil.which("clang")
        glslang = shutil.which("glslangValidator")
        spirv_val = shutil.which("spirv-val")
        self.assertTrue(cc and glslang and spirv_val)
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            exe = d / "gpu-one-plane"
            c = subprocess.run([cc, "-O2", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                str(RUNNER), "-Wl,-l:libvulkan.so.1", "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(c.returncode, 0, c.stderr)

            shaders = {}
            for n in (7, 8):
                src = d / f"output{n}.comp"
                spv = d / f"output{n}.spv"
                src.write_text(source(n))
                subprocess.run([glslang, "-V", "--target-env", "vulkan1.1",
                    "-S", "comp", "-o", str(spv), str(src)], check=True,
                    capture_output=True, text=True)
                subprocess.run([spirv_val, "--target-env", "vulkan1.1",
                    str(spv)], check=True, capture_output=True, text=True)
                shaders[n] = spv

            record = d / "rec.bin"
            record.write_bytes(struct.pack("<32I", *([0] * 32)))
            arena = d / "arena.bin"
            result = d / "out.bin"
            for groups in (16, 64):
                nbytes = groups * 4096 * 4
                times = {7: [], 8: []}
                values = {}
                for round_i in range(4):
                    order = (7, 8) if round_i % 2 == 0 else (8, 7)
                    for planes in order:
                        arena.write_bytes(bytes(nbytes))
                        env = dict(os.environ, MEMU_TEST_REPEATS="24")
                        p = subprocess.run([str(exe), str(shaders[planes]),
                            str(record), str(arena), str(result),
                            str(groups), "1", "1"],
                            env=env, capture_output=True, text=True)
                        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
                        report = json.loads(p.stdout.strip().splitlines()[-1])
                        times[planes].append(report["gpu_ns_per_dispatch"])
                        values[planes] = result.read_bytes()

                full = memoryview(values[8]).cast("I")
                pruned = memoryview(values[7]).cast("I")
                self.assertEqual(len(full), groups * 4096)
                self.assertEqual(len(pruned), groups * 4096)
                for g in range(groups):
                    begin = g * 4096
                    # 7 surviving vec4s, i.e. 28 words per vertex, MUST
                    # match bit-for-bit, including every location and lane.
                    for w in range(7 * 512):
                        self.assertEqual(full[begin + w], pruned[begin + w],
                            (groups, g, w, "surviving output changed"))
                    # Exactly the eighth plane is unused. Prove writes
                    # really were removed (not only source syntax).
                    self.assertNotEqual(
                        full[begin + 7 * 512:begin + 4096].tolist(),
                        pruned[begin + 7 * 512:begin + 4096].tolist(),
                        (groups, g, "dead plane was not removed"))

                baseline = statistics.median(times[8])
                less = statistics.median(times[7])
                self.assertGreater(baseline, 0)
                self.assertGreater(less, 0)
                print(f"GPU one unused vec4 (Lavapipe; {groups} groups x128 vertices): "
                    f"8-plane={baseline/1000:.2f} us, "
                    f"7-plane={less/1000:.2f} us, "
                    f"7/8={less/baseline:.3f}; all surviving GPU words exact, "
                    "NOT an Adreno/Android FPS measurement", flush=True)
if __name__ == "__main__":
    unittest.main()
