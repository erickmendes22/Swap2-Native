# Ocarina 0.1.6 — device log/build matrix and GPU texture pool feedback audit (2026-11-13)

Status: **experimental source implementation; off by default; no phone FPS gain claimed**. Keep full 508-shader foliage, scene resolution, SGSR1, VRS setting and original 42,339-shader library intact.

## Exact phone logs and builds

Each original `.7z` archive contains a single `.log`. The `DM_BUILD_COMMIT` and `DM_VK_*` settings were read from the **logs**, not inferred from filenames. All these sessions reported shader chain `779be11f4fed` and the same proprietary Qualcomm driver.

| Device log | Commit | Android workflow | Configuration | Frame p50 near frame 2100 | GPU p50 |
| --- | --- | --- | --- | ---: | ---: |
| `0400486024DEC000-20261113-065713.7z` | `b440784167c9` | [run 43378805362](https://github.com/erickmendes22/Swap2-Native/actions/runs/43378805362), #123 (called Build121 during conversation) | Full vegetation ON, planar/lookup ON | 25.12 ms at frame 1800 | 24.68 ms |
| `0400486024DEC000-20261113-070945.7z` | `b440784167c9` | same | Full vegetation OFF, planar/lookup OFF (not exercised when foliage OFF) | 18.05 ms at frame 1800 | 17.64 ms |
| `0400486024DEC000-20261113-075025.7z` | `ff3426bd541f` | [run 43410849160](https://github.com/erickmendes22/Swap2-Native/actions/runs/43410849160), Build124 | Full vegetation ON, component compute retile ON | 24.74 ms | 24.25 ms |
| `0400486024DEC000-20261113-085434.7z` | `ff379e5ee45c` | [run 43419038447](https://github.com/erickmendes22/Swap2-Native/actions/runs/43419038447), Build125 | Full vegetation ON, compute retile ON, **Fragment AST=0** | **24.47 ms** | **24.04 ms** |
| `0400486024DEC000-20261113-085545.7z` | `ff379e5ee45c` | same Build125 | Full vegetation ON, compute retile ON, **Fragment AST=1** | **24.61 ms** | **24.13 ms** |

Build125 is the reliable same-APK A/B of the *isolated* fragment AST flag: the frame p50 worsens 0.14 ms, GPU p50 worsens 0.09 ms, and the sampled 1e4d-dominated scene group measures 3.249 ms OFF vs 3.267 ms ON at frame 2101. Neither tiny delta proves causation under variable scene/draw counts, but **there is NO demonstrated speedup**. Do not enable by default or call it a successful optimization.

Build121's ON/OFF difference around frame 1800 is ~7.07 ms frame time / ~7.04 ms GPU, of which sampled graphics passes rise ~12.01 to ~13.97 ms (~1.96 ms), and ON conversion costs ~3.95 ms mesh + ~0.69 ms task. GPU frame sample components are not directly interchangeable with an interval median; no full 14 ms of scene graphics is avoidable. Keep image quality.

Build124 vs Build125 is **not** an isolated compute-retile comparison; commit, run context and camera may vary. The compute-retile experiment is kept as a separately reversible path but the 24.74 → 24.47 ms change cannot be attributed solely to it.

## Feedback bitmap must be preserved

The `075025` Build124 log reports, after 1802 feedback readbacks: **25,512 texture ID hits, 22 new texture images (72.5 MiB), zero readbacks deferred due to ring exhaustion**. These are real lazily discovered resources; disabling the feedback can create missing textures. Some fragment shaders (including `1e4d...`) have multiple feedback sites for the same IDs, but removing repeated sites across different control-flow branches is unsafe without path-sensitive proof. In prior synthetic tests both the per-fragment memo and cross-invocation grouping failed the real performance acceptance criteria; do not repeat as a default.

Current Vulkan `vka_tex.c` legacy path: pool-reading shaders atomically mark a 128 KiB bitmap, then each relevant submission executes a shader→transfer barrier, GPU buffer copy to an idle host-visible ring slot, transfer read→write barrier, 128 KiB GPU fill of the map, and transfer→host/graphics barrier. The GPU->CPU barrier already at the end of each submission remains in `vka_exec.c`.

### Experimental direct ring, `DM_VK_POOL_FB_DIRECT=1`

The implementation in `vka_tex.c` and `vka_exec.c` (disabled by default) binds the GPU writer directly to a **fence-released host-coherent ring slice**, via one immutable descriptor set per slot. The slot is reserved after old readbacks are consumed and **CPU memset occurs only at the first actual shader draw using pool feedback**, before binding the descriptor, never for the much more frequent submissions without pool reads. Subsequent draws do not clear accumulated bits. The ring reservation can be reused only when its previous fence has completed. The host bits become visible before the subsequent queue submission. `vka_tex_pfb_commit` records its fence and byte count, and the unchanged `pfb_consume_locked` enumerates exactly the same texture IDs. The mandatory submission-end ALL_COMMANDS→HOST barrier covers the direct shader stores. Direct submissions omit all three additional pool-feedback barriers, the copy and the GPU fill. They still execute the exact bitmap atomics inside fragment shaders, and do not remove scene work.

If all eight slices are in flight, or the shared legacy bitmap has pending bits after a skipped old readback, the original copy+fill path is retained. The descriptor sets are immutable while GPU commands are in flight, preserving Vulkan lifetime rules. Descriptor creation failure keeps the old path. Every 300 direct submissions, the log reports direct count, ring-full fallbacks and CPU slot clears; logs do not claim a GPU time gain.

A compiled production-C simulation under ASan/UBSan covers eight in-flight slots, duplicate bits, exact bitmap reads, no reuse until signaled fences, zero-stale-bit reuse, full-ring fallback, sticky pending map bits, and the absence of three old GPU commands in the direct case. Validation run: [Mesh compute correctness #10](https://github.com/erickmendes22/Swap2-Native/actions/runs/43437228516) (passed).


Same-build A/B toggle added to the Ocarina game settings: **Direct texture feedback (test)** / **Feedback direto de texturas (teste)**, default OFF. It maps to `DM_VK_POOL_FB_DIRECT=1`; the default/disabled choice emits `=0`. Restart the game between comparisons to let the Vulkan descriptor pool initialize once. The tests in `dm/gfx/tools/tests/test_ocarina_pool_fb_direct.py` compile the **real** `vka_tex_pfb_draw`, `vka_tex_pfb_begin` and `vka_tex_pfb_commit` with ASan/UBSan, checking exactly one CPU clear for several draws using the same slot and **zero clears for unused submissions**; the extra Android source wiring test is `dm/tools/tests/test_ocarina_pool_fb_launcher.py`. The original fallback commands and all texture discovery remain untouched.

**Release gate still open.** A physical Android GPU timing A/B with the **same commit/build**, direct ON vs OFF, identical vegetation/screen/camera, and matching set of consumed texture IDs + visuals is required to establish benefit. This change targets *feedback copy+fill overhead*, not the main 4 ms mesh compute or 14 ms raster budget; its total FPS benefit may be small or offset by the host 128 KiB memset. Do not claim or publish an FPS-boost APK solely based on this unit test.
