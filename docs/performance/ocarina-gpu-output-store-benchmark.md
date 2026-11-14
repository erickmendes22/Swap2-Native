# Ocarina GPU output memory traffic — synthetic benchmark, candidate rejected

Production Ocarina vegetation mesh emulation converts each vec4 output to four `OpStore` scalar words into a 128-vertex coalesced global-memory plane. Previous Build117 only removed redundant OpBitcasts, kept 4 scalar stores, and regressed the actual game.

The 2026-11-14 Vulkan A/B compared:
* **Baseline:** each shader invocation writes scalar output words to six vec4 attributes in 128-vertex planes (matching the current coalesced arena).
* **Candidate:** one packed `uvec4` output store instead of four scalar stores, with an equivalent 128-vertex / six-attribute logical payload. Arena output retiled by an independent CPU validator; **every byte matched**.
* Same Vulkan program inputs, workgroup counts, arithmetic, and byte count; only global-memory store pattern changed.
* Timestamped after warm-up with 24 repeated dispatches, three runs each, median recorded on Lavapipe software Vulkan. No APK and no production shaders changed.

| Mesh groups ×128 vertices, 6 vec4 outputs | Coalesced scalar | Packed vec4 | Packed / scalar |
|---|---:|---:|---:|
| 16 | 42.1 microseconds | 47.0 microseconds | **1.117** (11.7% slower) |
| 64 | 80.4 microseconds | 81.8 microseconds | **1.017** (1.7% slower) |
| 128 | 123.9 microseconds | 126.4 microseconds | **1.020** (2.0% slower) |

All three alternatives ran SLOWER under Vulkan software GPU. CI source and readback: https://github.com/erickmendes22/Swap2-Native/actions/runs/43587230316

**Decision:** reject packed uvec4 arena layout. The Adreno driver might behave differently, but it would be unjustified to rewrite the complete producer/consumer layout and test another APK with negative preliminary GPU results. Leave Build148c unchanged. Do not confuse fewer SPIR-V instructions with lower real GPU time.

Further GPU investigation: `vka_memu_spv.c` currently drops every original `OpSetMeshOutputsEXT` and builds indirect raster draw count from static `OutputPrimitivesEXT` maximum (`L.max_p * 3`) rather than the actual dynamically emitted primitive count. This is a **potential** raster overdraw issue but it is NOT proof of wasted work in the heavy Foliage.Product shaders: it depends on how many primitives those real modules emit. Do not lower primitive counts or skip geometry until the original game's exact output-count behavior is proven and pixel equivalence tested.
