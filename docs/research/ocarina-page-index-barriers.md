# Ocarina page-index and barrier research

Research branch: research/ocarina-page-index-barriers. Base: 29e2fad0ab9e7edca3e0c10f44ce715618bcb8c4.
Runtime remains unchanged; this branch must not trigger APK workflows or alter the active development branch.

## Evidence and scope

Earlier local probes: 13,451,200 barrier-policy sequences passed; 32 Vulkan storage/transfer/indirect cases matched, zero synchronization errors; removing the settle dependency generated16 validation errors. Page-index reference:4,500 randomized host updates and9,000,000 address lookups passed. The Vulkan fixture passed22 module executions (8 indexed) after enabling maintenance4 and restricting the synthetic window to the software driver's storage-buffer range. These are host/software-Vulkan checks, not Adreno gameplay measurements.

The direct Anka transformer admitted0 of8 sampled local modules. It assumes a12-step4096-entry search, whereas this branch's translator has13 steps8192 entries, a7-word per-helper exact-range cache, pool1 shortcut and tagged2MiB hints. Do not claim the direct port accelerates the application.

The heavy fragment19f99e925937b038 and the captured fragment1e4d2630d24846d0 have no GMEM_MAP binding in their available reflection. Captured mesh fed302d791a4ba43, eb021183bf9b0092 and3439aaa071d868ae contain253,254 and496 raw-load translation notes respectively; these are static sites, not measured runtime search misses.

The recorded177 heavy window has frame p50=25.95ms and GPU p50=22.03ms. Sample1501 graphics=14.733ms, mesh=3.477ms, task=0.593ms. Different percentile windows and sampled intervals are not additive frame predictions. Legacy174 sample1201:20.98ms GPU;12.95 graphics,3.91 identified compute,4.02 unclassified steps. The last category includes2.85ms mesh and0.44ms task, not4.02ms of removable barriers.

## Expanded experiments

1. An isolated8192-entry shader prototype must compare the existing exact-range/pool1/hint/search order with a page index, both with and without keeping the existing cache. Preserve unmapped-address behavior and write logs. Require full-table and4GiB-boundary cases. Do not change prepared-library ABI or runtime until these tests and ownership obligations are complete.
2. Preserve index generations until every consuming fence retires. No in-place mutation of a generation referenced by recorded work. Addresses outside index coverage must use the original search, not silently read zero. Bound memory and test pressure/fallback.
3. Validate compute barrier narrowing with real ordered transfers, indirect arguments and query-result copies. A pending/owed dependency must settle before non-compute work. Keep graphics/depth/pass barriers intact.
4. Collect non-overlapping operation counts and rejection reasons. Do not infer shader time from SPIR-V size or software-Vulkan timing.

## Conditional sensitivity, not measured gain

Using only the4.07ms sampled mesh/task budget: hypothetical reductions10/25/50percent save0.407/1.0175/2.035ms. If the saving fully shortens a25.95ms frame,38.54fps becomes39.15/40.11/41.82fps. A separate assumed0.6ms barrier saving plus the50percent scenario gives42.89fps. Neither the percentages nor0.6ms are measured;0fps or regression remains possible.60fps requires9.283ms less total frame time, unsupported by these two hypotheses alone.

## Reference pins

- AnkaNative b2c0f4cfc37a8c75fad1d36f3e912ef0820416e4: page-index shader/host tests.
- FrenklinFish/BananaNative6db28a65764f9661740ed2fd8aba51ed6f73702f: vka_gbar policy.
- Current production source and user-approved RAM/vegetation/upscale fixes remain on the pinned base.


## Expanded isolated prototype (not wired into the app)

`dm/gfx/research/ocarina_memory/` contains an8192-entry GLSL model guarded against changes to the current translator's cache/hint constants, a direct page-index model, and a cache-preserving model. It is a synthetic model of production semantics, not the actual translated game shader and not proof of runtime eligibility. The retained cache stores a page-local range after an index hit; original range-cache hits, pool1 and hints still precede the index. Uncovered pages fall back to the original full13-step search. A zero record never silently substitutes a valid load with zero. New library flags, runtime tables and ABI are deliberately absent.

Local exact-output results, each row over64 invocations including mapped/unmapped loads/stores, pool ends, high-word carries and out-of-window addresses:

| Table | Warm loads | Baseline search probes | Retained-cache index probes | Extra index reads | Probe reduction |
|---|---|---:|---:|---:|---:|
| Sparse | No |637|455|49|28.6%|
| Sparse | Yes |2977|2275|229|23.6%|
| Full8192 entries | No |637|364|49|42.9%|
| Full8192 entries | Yes |2899|1820|223|37.2%|

These count executed search steps, not all GPU instructions or bytes. The index introduces dependent reads and potentially live registers; fewer search probes is not a proportional shader speedup. The warm case deliberately alternates pools and is not a measured game cache-hit distribution. Replacing the cache entirely requires320 index lookups in the warm fixture, versus223/229 when it is retained. Therefore investigate the retained-cache form first; do not claim that replacing a zero-read cache hit with an indexed load is always faster.

The four configurations compare every loaded value, warm-load digest, all pool bytes, the write-log page set and sink behavior across all three algorithms. Four corrupted-load negative controls are detected. Software-Vulkan validation must stay clean. The host index test still checks4500 mutation steps/9million random lookups. It mutates an idle index for arithmetic testing; it does not prove safe lifetime of live GPU generations.

Barrier tests execute the original policy and record scopes with this branch's production barrier functions. They include transfer chains, direct/indirect dispatches and timestamp-result copies.32cases preserve4096bytes each. The broken settle dependency must raise synchronization errors. Exhaustive policy proof covers13,451,200 abstract sequences. This is not a complete interception-layer integration; every production work API, especially query copies, must be classified before any runtime adoption.

## Remaining gates

- Translate actual captured helpers to the new model; automatic admission remains0/8 with the unmodified Anka pass. Do not commit proprietary modules.
- Prove generation immutability, including several mapping changes within one unsubmitted command buffer; reject in-place reuse while any recorded reader exists.
- Test index memory cap, non-page-aligned pools, partial coverage and original-search fallback in the actual renderer. A9GiB flat window needs18MiB per8-byte index copy before metadata; four copies are72MiB. Prefer a bounded strategy and preserve the confirmed RAM savings.
- Measure actual cache/hint misses and target-stage GPU time on Adreno before revising the conditional FPS sensitivity. Keep shader math, depth, vegetation and user settings unchanged.
- The workflow is branch-specific, read-only to GitHub and has no build/sign/publish steps. Its first step verifies the active renderer, translator, profile and launcher are unchanged from the research base.

Reference snapshots retain original comments; `pidx_reference.h`, `pidx_random.c` and the base of `pidx_gpu.c` derive from AnkaNative's pinned MIT sources. The synthetic GPU runner additionally enables maintenance4, uses8192 entries, keeps its window within128MiB descriptor limits, and exports independent work counters. The barrier policy/record scopes and exhaustive checker come from Banana Native (MIT); the policy is identical in FrenklinFish6db28a65764f and local upstreamdc7c4203cee1a4784afb751a8ea8abce6b31acd3. These references are fixtures, never linked by the Android build.

## Cache locality and recorded-reader ownership follow-up

The repeated-pool fixture makes200 valid cache hits. A direct index performs320 index reads, whereas the cache-preserving form needs49. Exact output and write-log comparisons still pass for sparse and full tables. This reinforces that fewer binary-search probes alone cannot establish a gain over our existing cache. No phone cache-hit rate is inferred.

The proposed, research-only `index_generation_policy.h` never selects a recorded reader for rewriting, even before it has a fence. It reuses the same immutable generation, otherwise an idle completed buffer, otherwise allocates within its byte cap, otherwise falls back to the original lookup.100000 generated ownership schedules pass. The real reference index builder demonstrates that changing a second buffer preserves the first generation, while an intentional in-place update changes what an old reader would see. This is a host ownership/design proof, not integration into the live Vulkan allocator.

The first Actions attempt correctly failed when the missing-dependency negative control produced no synchronization diagnostic. Its newer validation layer warned about deprecated layer settings; the reason it missed that negative control is not yet established. CI now requests `VK_VALIDATION_VALIDATE_SYNC=1` without the deprecated enables variable; the older local layer uses its older setting. The negative control remains mandatory; it is not skipped or weakened.

Actions follow-up: current Khronos documentation specifies the `VK_VALIDATION_` setting prefix and the newest layer defaults `syncval_shader_accesses_heuristic` to false. Both synchronization validation and shader-access tracking are now explicitly requested (`VK_VALIDATION_SYNCVAL_SHADER_ACCESSES_HEURISTIC=1`). The mandatory negative control tests whether the configuration actually detects the omitted dependency. Official references: https://github.com/KhronosGroup/Vulkan-ValidationLayers/blob/main/docs/syncval_usage.md and layers/VkLayer_khronos_validation.json.in.
