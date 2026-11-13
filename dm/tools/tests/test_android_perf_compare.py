import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("android_perf_compare", Path(__file__).resolve().parents[1] / "android_perf_compare.py")
perf = importlib.util.module_from_spec(spec); spec.loader.exec_module(perf)


def log(frame_ms=27.61, gpu_ms=27.15, barriers=187, vegetation=1):
    return perf.parse(f"""[nxlaunch] env DM_VK_VEGETATION={vegetation}
[dm] [nvn] timing up to frame 1200: frame time p50 {frame_ms} / p95 29.18 / max 40.63 ms (300 frames); frame work p50 27.54 / p95 29.11 / max 40.57 ms (300 frames); GPU p50 {gpu_ms} / p95 28.43 / max 54.89 ms (299 frames);
[dm] [vk] replay up to frame 1200: per frame 2419 draws, 150 render passes, 67 clears / copies (60 in a pass), {barriers} full barriers, 80 inline uniform updates, 6.0 submissions (9.6 parts); recording 18.34 ms a frame (7.58 us a draw)
[dm] [vk] gpu prof foliage phases: mesh 1.0 ms
""")


class PerfCompare(unittest.TestCase):
    def test_faster_sparse_mesh_cannot_mask_interval_regression(self):
        result = perf.compare(log(), log(33.22, 28.66, 220), 1200)
        self.assertEqual(result["verdict"], "regression")
        self.assertAlmostEqual(result["change_pct"]["frame_p50_ms"], 20.319)
        self.assertIn("frame_p50_ms", result["regressed_metrics"])
        self.assertTrue(result["context_differences"])

    def test_vegetation_off_does_not_pass_as_an_optimization(self):
        result = perf.compare(log(), log(20, 19, vegetation=0))
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("vegetation differs", result["context_differences"])

    def test_missing_matching_window_is_not_a_pass(self):
        with self.assertRaises(ValueError):
            perf.compare(log(), {"windows": {}, "metadata": {}})

    def test_equal_run_is_not_claimed_as_an_improvement(self):
        self.assertEqual(perf.compare(log(), log())["verdict"], "no_regression_detected")


if __name__ == "__main__":
    unittest.main()
