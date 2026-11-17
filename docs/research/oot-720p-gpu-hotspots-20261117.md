# Ocarina 720p GPU bottleneck investigation — 2026-11-17

Baseline: signed Android **v0.1.9** from `ocarina-v11-ios-perf-from-v101`, commit
`dbdc11ceaf49a5ea496d542d839a975b999ec170`.
Device: Redmagic 11 Pro (Adreno 840 / Qualcomm proprietary driver).
Source: two **device-recorded** heavy-scene logs from 2026-11-16, frames 1201, 1501 and 1801.
Do NOT publish personal log files or infer a device GPU FPS result from host tests.

## Measured cost and eliminated ideas

| Sampled GPU category | Approximate GPU time | Evidence/constraint |
| --- | ---: | --- |
| Two largest 1280×720 color+depth passes | 4.8 ms combined | Frame 1501, feedback-cache OFF: 517 draws / 2.749 ms and 247 draws / 2.084 ms; depth test ON, depth write OFF |
| Other 1280×720 graphics passes | ~4.2 ms | Include depth-write passes; pass times include all fixed-function GPU stages |
| Mesh-through-compute stage | ~2.9 ms | Timed GPU intervals; original mesh shader `eb021183bf9b0092` ~0.65 ms and `fed302d791a4ba43` ~0.5 ms |
| Task-through-compute stage | ~0.5 ms | Timed GPU intervals |
| Non-mesh compute intervals and completion dependencies | ~4.4 ms | ~130 intervals reported against `vka_draw.c` dispatch completion; NOT 4.4 ms of pure shader ALU |

Original paired ON/OFF feedback-cache study, frames 1501–1800:
`frame median 21.17 ms ON, 21.00 ms OFF`; `GPU median 20.71 ms ON, 20.67 ms OFF`.
Feature was fully removed from v0.1.9; **do not reintroduce**.
VRS beyond 2×2, isolated fragment instruction reductions, SSAO/depth BYML patches and
Bloom/DOF disabling have no measured useful speedup or are visually broken.
Do not enable aggressive foliage cuts: they visibly remove grasses/ferns.
Do not imply attachment load/store is measured physical DRAM bandwidth.
Do not assume `scissor-area/target-area` measures actual fragment overdraw.

## New opt-in experiment: taskless mesh direct dispatch 65..256

Source: `dm/gfx/vk_android/vka_memu_direct_dispatch.h` and
`dm/gfx/vk_android/vka_memu_draw.inc`, with a tested pure-C eligibility matrix
`dm/host/tests/t_oot_direct256.c`. Baseline still dispatches indirectly
above 64 groups. When `DM_VK_OOT_MEMU_DIRECT_256=1` is provided in **this
game's General → Environment**, no new UI switch, only CPU-known direct mesh
draws *without* task shader and *without* indirect count can dispatch 65..256
groups directly. Original `memu_setup.comp` still computes the arena,
`R_TOTAL` and the GPU draw arguments. The converted SPIR-V retains
`flat < R_TOTAL`; excess groups cannot write outputs. Unsupported paths
fall back to original dispatch. No game shaders/ABI or shader cache change.

**Validation:** standalone C ASan/UBSan workflow
`https://github.com/erickmendes22/Swap2-Native/actions/runs/44071610717`
passed. **Actual FPS benefit still unknown**: count first real extension hit
from `Ocarina taskless direct mesh 256 trial ACTIVE`. If absent, no target
dispatch benefited and the test should be retired, not widened blindly.

On identical 720p, same location/device temperature:
- Control: remove `DM_VK_OOT_MEMU_DIRECT_256` from per-game env; restart.
- Trial: set `DM_VK_OOT_MEMU_DIRECT_256=1`; restart.
- Compare frame p50, p90, GPU median, 1280 pass cost, mesh phases and correctness.
- Restore by removing the line. Do not claim a gain until this A/B.

## Next high-value source investigation

The two most expensive **1280×720 graphics** passes are mostly
`depth-test=1, depth-write=0`. Pass A has ~149k input triangle estimate and
517 draws; pass B ~80k and 247 draws. A major gain needs fewer actual
raster/geometry operations, not just smaller SPIR-V fragment instruction
counts (previous 30% cut yielded unchanged GPU latency). Explore whether
the *same mesh output and all guest inputs* legitimately recur between
depth/color draws, with per-record, input-revision, render-pass and write-side
effect checks. **Never reuse mesh output solely by shader key**:
`vka_memu_order.h` already documents repeated record addresses with
different shaders and render targets that must remain separate.

The 4.4 ms non-mesh compute category includes completion dependencies and
multiple different shader keys: avoid removing barriers speculatively.
The next baseline phone logs should isolate the full shader/output pipeline
before attempting a rewrite. Preserve foliage, original SSR/upscale, and
Qualcomm automatic driver settings.
