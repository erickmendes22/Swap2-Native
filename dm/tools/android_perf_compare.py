#!/usr/bin/env python3
"""Compare the same completed warm frame window in two Android logs.

Sparse GPU phase samples are separate from interval medians. A faster mesh
sample never overrides a frame/GPU regression. These counters cannot prove
that the camera, visibility or scene content was identical.
"""
import argparse
import json
from pathlib import Path
import re


def parse(text):
    windows = {}
    for line in text.splitlines():
        m = re.search(r"timing up to frame (\d+): frame time p50 ([\d.]+) / p95 ([\d.]+).*?GPU p50 ([\d.]+) / p95 ([\d.]+)", line)
        if m:
            windows.setdefault(int(m[1]), {}).update(dict(zip(
                ("frame_p50_ms", "frame_p95_ms", "gpu_p50_ms", "gpu_p95_ms"), map(float, m.groups()[1:]))))
        m = re.search(r"replay up to frame (\d+): per frame (\d+) draws, (\d+) render passes,.*? (\d+) full barriers,.*?recording ([\d.]+) ms", line)
        if m:
            windows.setdefault(int(m[1]), {}).update(dict(zip(
                ("draws", "render_passes", "barriers", "recording_ms"), map(float, m.groups()[1:]))))
    metadata = {}
    for name, pattern in (("device", r"\[nxlaunch\] device ([^\n]+?), Android"),
                          ("driver", r"\[nxlaunch\] env DM_VK_DRIVER=([^\n]+)"),
                          ("vegetation", r"\[nxlaunch\] env DM_VK_VEGETATION=(\d+)")):
        m = re.search(pattern, text)
        if m:
            metadata[name] = m[1]
    return {"windows": windows, "metadata": metadata}


def compare(before, after, frame=None, tolerance=3.0):
    required = {"frame_p50_ms", "frame_p95_ms", "gpu_p50_ms", "gpu_p95_ms", "draws", "barriers"}
    common = sorted(f for f in before["windows"].keys() & after["windows"].keys()
                    if f >= 900 and required <= before["windows"][f].keys()
                    and required <= after["windows"][f].keys()
                    and all(run["windows"][f][k] > 0 for run in (before, after)
                            for k in ("frame_p50_ms", "frame_p95_ms", "gpu_p50_ms", "gpu_p95_ms")))
    if not common or (frame is not None and frame not in common):
        raise ValueError("no requested completed warm window in both logs (frame >= 900)")
    frame = frame if frame is not None else common[-1]
    a, b = before["windows"][frame], after["windows"][frame]
    changes = {k: round(100 * (b[k] / a[k] - 1), 3) for k in a.keys() & b.keys() if a[k] > 0}
    context = [f"{k} differs" for k in before["metadata"].keys() & after["metadata"].keys()
               if before["metadata"][k] != after["metadata"][k]]
    for k, limit in (("draws", 1), ("barriers", 10), ("render_passes", 5)):
        if abs(changes.get(k, 0)) > limit:
            context.append(f"{k} changed by {changes[k]:+.2f}%")
    regressed = [k for k in ("frame_p50_ms", "frame_p95_ms", "gpu_p50_ms", "gpu_p95_ms")
                 if changes[k] > tolerance]
    return {"window_end_frame": frame, "before": a, "after": b,
            "change_pct": changes, "regressed_metrics": regressed,
            "context_differences": context,
            "verdict": "regression" if regressed else "inconclusive" if context else "no_regression_detected",
            "limitation": "One interval per run; matched scene and repeated device runs still required. Sparse shader samples do not establish frame-time gains."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("before", type=Path); p.add_argument("after", type=Path)
    p.add_argument("--frame", type=int)
    p.add_argument("--tolerance-pct", type=float, default=3)
    p.add_argument("--check", action="store_true", help="fail on regression or incomparable context")
    args = p.parse_args()
    try:
        result = compare(parse(args.before.read_text(errors="replace")),
                         parse(args.after.read_text(errors="replace")), args.frame, args.tolerance_pct)
    except ValueError as e:
        p.error(str(e))
    print(json.dumps(result, indent=2))
    return int(args.check and result["verdict"] != "no_regression_detected")


if __name__ == "__main__":
    raise SystemExit(main())
