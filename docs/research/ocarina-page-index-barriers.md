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
