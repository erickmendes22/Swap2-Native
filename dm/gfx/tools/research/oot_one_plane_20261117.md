# Ocarina 0.1.9 — one dead vec4 plane, 17 Nov 2026

## Decision

**Research only; do not publish a standalone APK or assert FPS improvement.** The production branch `ocarina-v11-ios-perf-from-v101` remains on the reverted all-compute revision `7932d1e`. The previous RenderEnable fusion has already failed on the full suite and must not be reintroduced.

## Ground truth: Adreno 840, Qualcomm 891.14, 17:43 log

Source: user-provided `0400486024DEC000-20261117-174315.log` (not committed here).

- Frames 1201–1500: 16,343 mesh draws across 8,324 compute batches; 6,900 graphics pass splits. Existing `GPU fragment-masked draws` was **0**.
- Sparse sampled frame 1501: leading 1280×720 graphics passes ~3.453 ms (476 draws, 154,830 direct triangle estimate) and ~1.492 ms (286 draws, 73,924 triangle estimate); mesh compute stage total ~3.70 ms across 56 marks in this sampled frame. A per-draw timestamp inside tiled rendering was previously unreliable.
- Existing >=2 unused vec4 threshold applies to ALL meshes. Zero masked draws **does not prove** absence of exactly ONE unused vec4 for the actual bound fragment shaders.

## Actual Vulkan tests (Mesa Lavapipe; NOT Adreno)

CI run `44181495374`, success. Tests:

1. Real, converted mesh-compute producer and generated vertex consumer with real Vulkan buffers, task and taskless, coalesced and non-coalesced: bitwise-exact surviving inputs (test_memu_coalesced_readback).
2. Synthetic write-only benchmark, exactly 8 vs 7 vec4 output planes, alternating order, four samples and 24 repetitions each:
   - 16 × 128 vertices: 61.71 us → 57.81 us; 6.3% reduction.
   - 64 × 128 vertices: 135.44 us → 121.19 us; 10.5% reduction.
   - Every retained GPU word bit-for-bit equal; eighth attribute output genuinely unmodified in pruned variant.
3. Real converted-pair GPU timings were **mixed**: pruned/full 1.009, 1.039, 0.977, 1.029, 0.980, 0.970 across six fixture settings. This contradicts extrapolating the synthetic write-only gain directly to the real game.

## Constrained source experiment

- Scope **only** source mesh keys `eb021183bf9b0092`, `fed302d791a4ba43`, `3439aaa071d868ae`. The first two were present in the Adreno 1280p sparse samples, but the log cannot establish their unused-input masks.
- Requires actual bound FS SPIR-V location mask with exactly one unused vec4. Unknown mask, unavailable FS, mismatched input layout, failure to create either stage, and exhausted variant cache: original full producer and consumer remain.
- Producer compute and consumer vertex shader are selected together; position, indices, culling, task payloads and guest memory/barriers remain.
- `DM_VK_OOT_ONE_PLANE_PRUNE=0` by default on research branch; explicit 1 enables the tentative fast path.
- Research-only stats count matching hot mesh draw keys, actual FS resolution, unknown/invalid input masks, 0/1/≥2 unused locations. No new GPU timestamps or guest draw changes.

## Next decision gate

**Do not make an APK for the single-plane path until the actual workload is shown to have eligible one-plane pairs or it is bundled with another demonstrably useful GPU change.** The primary ~3.45ms/1.49ms classic graphics passes remain higher-priority candidates than the one-plane GPU write microbenchmark. To reach 50 FPS from ~20.7ms GPU median requires roughly 0.7ms reduction; the write-only benchmark cannot demonstrate that magnitude in the live game.
