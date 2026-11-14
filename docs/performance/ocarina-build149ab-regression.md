# Ocarina Build149AB — REJECTED GPU performance experiment

Actual phone logs, Qualcomm 891.14, vegetation enabled, 960x540 -> 1280x720 SGSR, integrated mesh-compute path, before/after with the same launcher settings:

- Build148c baseline: `0400486024DEC000-20261113-210416.log`
  - Stable frames 1500–2700: GPU p50 20.15–20.33 ms; frame p50 20.50–20.70 ms (~48.3–48.8 FPS)
  - ~148–149 render passes/frame, ~2402–2408 draws/frame
  - At sampled frame 2701: GFX_CHUNK 10.40 ms, MEMU_MESH_SHADER 2.92 ms, other compute vka_draw.c:2339 3.42 ms, pass-end barrier vka_draw.c:367 2.20 ms.
- Build149AB scope narrowing: `0400486024DEC000-20261113-223418.log`
  - Stable frames 1500–2400: GPU p50 20.63–20.95 ms; frame p50 20.99–21.40 ms (~46.7–47.6 FPS)
  - ~149 render passes/frame, ~2402–2406 draws/frame
  - Actual `DM_VK_MEMU_INTERPHASE_SCOPE=1`: ~74–80 intermediate compute-to-compute/indirect barriers/frame; ~79 remaining compute-to-ALL barriers/frame. Total barriers not meaningfully reduced.
  - At sampled frame 2401: GFX_CHUNK 10.72 ms, MEMU_MESH_SHADER 3.01 ms, other compute 3.52 ms, pass-end barrier 2.73 ms.
  - Same driver and internal scene/SGSR settings. Differences in sampled graphics blocks mean exact attribution is approximate; observed regression is real.

**Decision:** Reject Build149AB. A narrower Vulkan barrier stage mask did not eliminate mesh-induced render pass splits or the tiler load/store cost, and it regressed GPU performance. Do not merge `DM_VK_MEMU_INTERPHASE_SCOPE` to `ocarina-v11-ios-perf-from-v101`. Keep the validated Build148c baseline. Do not turn the failed intermediate-barrier scope into a user setting.

Next research priority: capture exact graphics render pass and dependency differences on a matched vegetation ON vs OFF scene, and target attachment load/store and pass splits *with guest hazard preservation*. Do not reintroduce `DM_VK_MEMU_RC_TRUE_FUSE` (previously tested and rejected after 174854 log).

This experiment's CI-valid correctness checks do not demonstrate a performance improvement; synthetic checks are indicators, never phone FPS guarantees.
