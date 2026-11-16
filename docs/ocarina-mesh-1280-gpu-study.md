# Ocarina GPU performance: mesh compute, driver statistics, 1280x720 scene

Source: `0400486024DEC000-20261115-215743.log` from the real `df66a303`
Android build. Diagnostic code was added separately; there are **no measured
post-change phone FPS numbers**. Do not confuse the SPIR-V fixture tests with a
Redmagic/Adreno frame-time gain.

## Grounded pre-change workload

The real GPU profiler recorded, on game frames 901 / 1201 / 1501:

- Overall GPU ~23.67 / 22.88 / 22.86 ms. Full scene passes ~14.19 / 14.19 / 14.06 ms.
- One 1280×720 color+depth pass: 393 / 509 / 399 draws and 1.906 / 2.759 /
  1.952 ms. Dominant FS key `1e4d2630d24846d0` (236 / 238 / 238 draws).
- Another 1280×720 color+depth pass: 374 / 254 / 362 draws and 2.886 /
  2.106 / 2.881 ms. Its top FS keys include `8ea627c8ef169ee1`,
  `edce918b7374c89b`, `264e6e6de176460a`.
- Depth-only 1280×720 passes: ~0.52–0.69 ms even for ~320–478 draws.
  Top depth-pass shader `00ce4088af2c8e12`.
- Color attachment VkFormat 122 (B10G11R11_UFLOAT_PACK32), depth VkFormat
  126 (D32_SFLOAT): each is 4 bytes per pixel. At 1280×720, **one complete
  uncompressed attachment plane is 3.52 MiB**. This does NOT mean each render
  pass transferred that much DRAM: tile-local loads/stores, partial coverage,
  compression and memory reuse change physical traffic.
- Sampled foliage mesh compute ~3.10–3.30 ms and task compute ~0.5 ms.
  Recording Vulkan ~19.8–20.5 ms per game frame, so do not optimize GPU alone.

## Code changes (all diagnostic-only)

1. `DM_VK_MEMU_PLANE_DIAG=1`: for each newly generated real mesh/task compute
   print its source key, whether a named `mesh_plane_store` was recognized,
   direct-table matches, fallbacks, a conservative reason, plus exact SPIR-V
   instruction, store, Workgroup variable and barrier counts before/after.
   `=2` additionally regenerates **in memory** the old `LUT=0` SPIR-V for
   the six known hot source keys and prints its counters against the selected
   compute version. This alternate is never installed or executed. A driver
   may optimize both versions differently, so size/instruction counts alone
   do not prove faster GPU execution.
2. `DM_VK_PIPE_STATS=1`: if `VK_KHR_pipeline_executable_properties` is exposed
   by the chosen driver, request real execution statistics when compiling
   compute pipelines; `=2` also captures monolithic graphics pipelines.
   Log real vendor-defined register, spill, scratch, shared memory,
   instruction, wave and occupancy values *when available*. Source and derived
   compute key mapping lets the two diagnostics join. Unsupported drivers log
   the absence once and continue normally.
   `DM_VK_PIPE_STATS_MAX=96` (limits pipelines reported),
   `DM_VK_PIPE_STATS_VERBOSE=1` (optional: log more vendor counters).
3. The existing sampled GPU profiler now recognizes the actual
   `1280x720x1` scene, timestamps groups of 16 raster draws, and sums
   the chunks with the pass tail instead of reporting only the tail.
   `DM_VK_SCENE_PASS_DIAG=1` prints each dominant pass's draw count,
   submitted direct-triangle estimate, indirect draws, depth-test/write and
   stencil counts, scissor-area accumulation and Vulkan attachment load/store
   counts. Scissor coverage is an upper-bound proxy, **not measured overdraw**.
   Logical attachment operations are **not measured DRAM bandwidth**.
4. `DM_VK_SCENE_PASS_DIAG=2` additionally uses
   `VK_QUERY_TYPE_PIPELINE_STATISTICS` on sampled 1280×720 passes, **only if**
   the Vulkan device exposes the `pipelineStatisticsQuery` feature. It
   reports actual input primitives, vertex invocations, clipped primitives
   and fragment shader invocations. VRS 2×2, early depth, culling and MSAA
   mean fragment invocations per screen pixel are **not literal overdraw**.
   If unsupported, the old timestamp profiler still functions.

All options above are OFF by default except the pre-existing sparse
`DM_VK_GPUPROF=300` interval for Ocarina. The full 42,339 base and the
separate 508 vegetation shader library are **untouched**.

## Paired phone capture protocol (first diagnostics, then performance)

At a reproducible save/camera and similar clock/temperature conditions,
start Zelda with these diagnostic settings (restart required for GPU device
extensions and already-derived shaders):

```
DM_VK_MEMU_PLANE_DIAG=2
DM_VK_PIPE_STATS=2
DM_VK_PIPE_STATS_MAX=96
DM_VK_SCENE_PASS_DIAG=2
DM_VK_GPUPROF=300
DM_VK_OOT_GFX_CHUNKS=1
```

Capture enough gameplay to obtain `gpu prof 1280x720 pass` and
`gpu prof 1280x720 Vulkan pipeline counters` for *multiple* sampled frames.
If no Vulkan query feature or executable-properties extension is available,
log that and compare the remaining observations rather than inventing
register/occupancy/overdraw numbers.

For honest performance A/B, **turn diagnostics off** (especially per-pass
queries), keep the same save, scene resolution and visual quality, and
alternate two runs with `DM_VK_MEMU_PLANE_LUT=1` (current direct path)
versus `DM_VK_MEMU_PLANE_LUT=0` (old branch-ladder fallback).
Restart between modes because derived shaders/pipeline cache IDs need a
fresh process. Collect stable gameplay FPS and p50/p95 GPU frame time,
not just the synthetic module instruction count. Do not treat unrelated
differences in CPU temperature, GMem index or VRS as the effect of this
specific optimization.

Expected outcomes:
- High raster time + high fragment invocations with VRS 2x2: pixel/overdraw
  optimization candidates, but inspect depth tests and the paired FS key.
- High raster time + low fragment invocations + high vertex invocations:
  geometry/vertex/ROP/attachment candidates; do not blame the FS alone.
- Color+depth pass costs substantially more than depth-only with similar
  draws: investigate color reads/writes, fragment execution and blending.
  A depth-only pass's low time does not prove the other pass is overdraw.
- A mesh helper with `fallback=1` and `PER_PRIMITIVE_OUTPUT` needs a
  distinct semantics-proof and GPU readback regression before optimizing.
  Never activate a guessed pointer remap or disable foliage to claim speed.

## Tests and limits

- `test_memu_plane_lut.py`: actually executes old and new C converter modes
  with the same source SPIR-V, validates output modules, and verifies
  diagnostic match/fallback counts.
- `test_ocarina_mesh_scene_probe.py`: compiles the scene-size classifier
  and validates the source guardrails for driver executable statistics,
  Vulkan pipeline queries, and buffer traffic labels.
- Android NDK syntax compile, native mesh correctness and readback tests
  in GitHub Actions remain required before releasing an APK.

Physical DRAM bytes, exact hardware overdraw, future FPS uplift and driver
occupancy **cannot be deduced** from the original saved log alone.
