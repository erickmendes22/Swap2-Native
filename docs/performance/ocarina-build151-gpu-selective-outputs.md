# Ocarina GPU Build151AB — paired mesh output pruning (experimental)

Baseline: 0.1.6 Build148c tree `6d1d32ea879d0af9867abe94582137bcc9eb41b5`. Source build pinned to `62b707e98ebef8a8eddd720c267555ed6a006704`. Production branch must remain byte-for-byte unchanged after the signed APK CI.

## Finding: old primitive-count hypothesis disproved by REAL original library

Analyzed user-supplied `vegetation.zip`, original `dmsh_vk.lib` and `index.json`. It contains **508 converted shaders**: 491 mesh and 17 task. Decompressed and parsed SPIR-V instruction streams. **All 491 mesh modules contain exactly one `OpSetMeshOutputsEXT` and both arguments are constant, equal to each module's declared OutputVertices and OutputPrimitivesEXT.** No excess draw primitives can be removed by shrinking its declared primitive count. The previous idea is rejected.

## New actual GPU work, not CPU or SPIR-V-code-size-only

Many hot Foliage.Product mesh shaders export 7–10 vec4 locations per vertex. Original GPU producer ALWAYS performs OpStore writes for ALL exported fragment varyings into the global SSBO arena, then the generated Vulkan vertex consumer ALWAYS reads their four component words. A bound FS may declare only a subset. On draws with no task program, the Android runtime now:

1. Extracts the exact bound FS's SPIR-V Input Location mask using the existing verified `vka_memu_fs_input_locs` parser. If no FS, use mask 0; any unreadable/unsupported FS falls back.
2. If at least two distinct vec4 locations are provably unconsumed and every requested location is produced by this mesh, generates and caches a masked *mesh compute producer* with those output OpStores eliminated and a matching masked *vertex consumer* with the corresponding four SSBO OpLoads per location omitted.
3. Uses the pair only when BOTH Vulkan shader modules exist; otherwise BOTH original stages. Only original render geometry, index writes, position, culling, payload and original texture/buffer bindings remain. No guest shader library change, no removed primitive, no resolution loss, no altered renderer barriers or render passes.
4. Distinct derived pipeline keys for masked modules; up to 16 masks per mesh, original remains the default fallback, and `DM_VK_OOT_VARYING_PRUNE=0` is a private rollback, not an app UI toggle.

## GPU correctness checks / synthetic indicator (not phone FPS)

Native real shader conversion (ASan/UBSan and spirv-val) shows:
- Original fully preserved **byte-for-byte** when mask=ALL.
- Triangle fixture generated VS: 13→5 GPU SSBO reads when two unused vec4 locations omitted; output store count 3→1. Mesh compute producer OpStore 18→13. Point fixture keeps position/point size and primitive metadata.
- Original vs paired masked producer/consumer executed on software Vulkan, both scalar and coalesced layouts, comparing **every fragment-visible value** bit-for-bit. All tests passed. Timings for small 4-workgroup fixtures had mixed signs: these are correctness tests, not broad speedup indicators.

Separate Vulkan **GPU timestamp A/B** with 128 vertices / mesh workgroup, 8 vec4 planes in the baseline vs 2 consumed planes in specialized producer; all remaining output bytes matched exactly:
| Workgroups | Baseline all 8 | Pruned 2 | GPU speedup |
|---:|---:|---:|---:|
| 16 | 43.74 µs | 31.75 µs | 1.378× |
| 64 | 91.09 µs | 43.99 µs | 2.071× |
| 128 | 152.90 µs | 63.32 µs | 2.415× |

This benchmark measures real global memory operations, not code size or CPU. It ran on Mesa Lavapipe (software Vulkan), not Adreno 840. It is **ONLY a synthetic indicator**, not a demonstrated game FPS increase.

Both complete workflows succeeded:
- https://github.com/erickmendes22/Swap2-Native/actions/runs/43590158473 — mesh GPU correctness, actual dispatch and arena readback, GPU memory A/B
- https://github.com/erickmendes22/Swap2-Native/actions/runs/43590158492 — complete Android Vulkan source and game regression

Signed test APK CI: https://github.com/erickmendes22/Swap2-Native/actions/runs/43590356233

## A/B acceptance

Run exact same 540p scene with vegetation ON, SGSR, coalesced=1, VRS 2×2, driver 891.14, same position and thermal state; compare game FPS and GPU p50/p95 over stable 300-frame windows against Build148c. Logs include `GPU fragment-masked draws` and `unused arena scalar channels/vertex` every 300 frames to prove the optimized code actually ran. If no measurable gain or any pixel artifact, reject immediately. Keep original baseline build unchanged until tested.
