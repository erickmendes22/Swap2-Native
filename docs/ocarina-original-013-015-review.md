# Ocarina Android — comparison with original Swap2-Native 0.1.3 / 0.1.5

Date: 2026-11-10. Target branch: `ocarina-v11-ios-perf-from-v101`.
Release references: [0.1.3-beta](https://github.com/mamcjr/Swap2-Native/releases/tag/v0.1.3-beta), [0.1.5-beta](https://github.com/mamcjr/Swap2-Native/releases/tag/v0.1.5-beta).

**Source limitation:** Both published Git tags refer to baseline commit
`e3ff75e44c08ab6afad1982efdfc1e03b2ad1dc0`. The corresponding changes
are in the source ZIP attached to each release, *not* the automatic GitHub
source archive. Without extracting those release ZIPs, these adaptations are
independent and based on their documented behavior; they are **not** a claim
of a direct port or identical implementation.

## Integrated in our existing Android branch

- `vka_imgmem.c`: serialize new 64-MiB block allocation by Vulkan memory type
  via a condition variable. Waiters retry existing blocks; reservation is
  cleared on both success and failure, and dedicated fallback is retained.
  This avoids concurrent redundant Vulkan block allocations during bursts.
  No change to image formats, guest memory, render results, or shaders.
- `vka_pso.c`: do not start unrelated speculative prewarm compilations while
  a foreground graphics/compute pipeline request is blocked on an in-progress
  compilation. Existing demanded pipeline wait is preserved.
- `vka_pso.c`: suspend *new speculative* prewarm work under Android system RAM
  pressure (MemAvailable below 512 MiB, adjustable with
  `DM_VK_PREWARM_RAM_FLOOR_MB`; 0 disables). Query procfs at most once every
  250 ms shared across prewarm threads; unavailable procfs uses old behavior.
- `vka_pso.c`: background pipeline-cache save period defaults to 60 s, up
  from 20 s. An explicit `DM_VK_PCACHE_SAVE_S` still overrides.
  Existing temp-file and rename-based cache replacement is preserved.
- `dm/gfx/tools/tests/test_ocarina_upstream_013_015_memory.py`: static
  lifecycle contracts and concurrent allocation model.

These reduce memory allocation bursts and speculative CPU/cache traffic;
they do not directly accelerate expensive GPU render passes. FPS gains on the
phone remain unmeasured.

## Already implemented before this comparison

- Shared Vulkan image blocks and zero-shared allocations, GPU fence-aware
  deferred destruction, image reference counts for pending linear writeback,
  serial-keyed texture reuse, and background/prewarm pipelines.
- A demanded pipeline already waits for the existing in-progress build in
  `gfx_obtain`/`cs_obtain`. Compiler failures may still produce missing draws.

## Requires the exact release sources and targeted porting

- 0.1.3: finalized-pool texture reclamation and memory-pressure eviction;
  pending upload retention fix (must preserve GPU/current-command-buffer
  references); application-pool `mem_map_limit` default and exceptions.
- 0.1.3: Zelda 8-GiB guest alias region and *prepared-pack metadata
  migration*. Our current profile declares 4.5 GiB (`mem_alias=0x120000000`);
  changing that profile alone risks invalidating existing prepared packs.
  The shader library must not be implicitly rebuilt.
- 0.1.5: cross-GPU-queue NVN event/sync dependencies for lighting, shader-
  referenced texture pool slot/lighmap residency, copied-texture ownership
  on finalize, and presentation scheduling relative to the queue lock.
- 0.1.5: file-backed shader-code pools, optional disk-backed RAM saver,
  safe singleton zero-shared allocation reuse, empty-block reclamation,
  hardware-AV1-to-dav1d failover.

The last group involves guest memory ownership, Vulkan queue timeline,
shader-visible handles and/or media decoder state. Do not transplant it by
release-note inference; run source-level comparisons and lifecycle tests.
Preserve the app package, signing configuration, workflow, prepared shaders,
saves, and update-over-existing-APK behavior. No build is triggered here.
