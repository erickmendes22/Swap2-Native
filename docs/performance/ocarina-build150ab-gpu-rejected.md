# Build150AB GPU A/B — REJECTED: no FPS / GPU gain

Measured from user-provided phone log `0400486024DEC000-20261114-070240.log`, Redmagic 11 Pro, Qualcomm driver 891.14, vegetation ON, graphics scale 2, SGSR, VRS profile 2, mesh route 1, coalesced 1, short task search 1.

Compared to the stable Build148c log `0400486024DEC000-20261113-210416.log` (same major GPU/scene settings, ON):
- Build148c stable 1500–2700: GPU p50 20.15–20.33ms (median of reported 300-frame windows ~20.29ms); frame p50 20.50–20.70ms.
- Build150AB stable 1800–3600: GPU p50 20.24–20.48ms (median ~20.39ms); frame p50 20.62–20.83ms; ~48FPS.
- Both: ~148–149 render passes/frame, ~2400 graphics draws/frame, ~7500 mesh-induced split passes/300 frames, ~20850 mesh draws in ~9825 batches/300 frames, 69 GPU mesh compute shader timestamps ~3ms in one sampled frame.
- GPU sampled raster `GFX_CHUNK`: ~10.4–10.7ms on both builds. `vka_draw.c:367` pass-end timestamps ~2.2ms on both.
- The top repeated long GPU raster interval has 16 draws and ~2.4ms, `topfs=a566b7687b712ff3:5`; ONLY 5/16 draws use this FS, so the ~2.4ms is NOT attributable to the FS alone.
- Original user-provided `nvn_shdump(2).zip` contains genuine .ctl/.code source captures for the hotter mesh shaders `eb021183bf9b0092` (~0.66ms GPU/dispatch) and `fed302d791a4ba43` (~0.53ms), but NOT the raster FS `a566b7687b712ff3`.

The synthetic shader size reduction was real (2141 -> 1126 SPIR-V words, 44 -> 23 static OpLoad on a test shader), and Vulkan output was bit-exact on Lavapipe; those facts did NOT translate into a gain on Adreno. This experiment is rejected for release, and MUST NOT be merged or suggested again as a performance improvement.

Previous attempts also rejected:
- Build149AB narrower intermediate compute-stage barrier: GPU regression ~1–1.7 FPS.
- SetRenderEnable(true) mesh lookahead fusion: no reduction in ~25 mesh-induced passes/frame.
- All native Qualcomm foliage meshes: prior phone capture showed corrupt white/spanning geometry; do NOT switch to native without a separate correctness fix.
- CPU-only mesh replay-state cache: synthetic CPU-side gain, not relevant to GPU-bound ~20ms frame.

**Primary objective**: reach <=16.67ms GPU per frame without reducing visual quality, i.e. recover ~3.6–3.8ms GPU. Next data-backed target: GPU graphics pass/tile cost, not CPU work or code-size-only simplification. Four-draw GPU-only timestamp attribution is isolated on `experiment/ocarina-gpu-graphics-4draw-profile` (changes timestamps on sampled frames only; does not pretend to improve FPS). Preserve the original Build148c tree on `ocarina-v11-ios-perf-from-v101`.
