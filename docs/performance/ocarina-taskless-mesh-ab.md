# Ocarina GPU — taskless-only mesh-compute specialization (experimental A/B)

Reference: stable **Build148c** source `210e250cfc870903e7718020ec7de014322dce3b`. Proposed shader-only GPU optimization on branch `experiment/ocarina-taskless-mesh-specialization`.

## What actually changes

- Only when a mesh draw has **NO bound task shader** (runtime `ts == NULL`), the producer pipeline uses `vka_memu_cs_taskless_of` instead of `vka_memu_cs_of`.
- The newly generated specialized compute shader removes the dynamic task-flag, binary task-offset-search and both task-search branches from the module. The index becomes `flat+first` and task ID 0.
- Preserve *all* mesh output and zero-payload writes, original vertex consumers, renderpasses, driver barriers, driver, fullscreen scene/profile/SGSR and complete original game shader libraries. Task-associated mesh draws keep exactly the original shader.
- The specialized pipeline has its own `VKA_MEMU_KEY_TASKLESS` xor tag; prewarm lookup includes this distinct identity to avoid using incompatible prior GPU pipeline bytes. No additional UI settings.

## Synthetic results (not device FPS)

Full native module converter + actual `spirv-val --target-env vulkan1.3` on the CI runner:

| Mode | Original words | Specialized words | SPIR-V loads before → after | Conditional branches before → after |
|---|---:|---:|---:|---:|
| default taskless fast path | 2141 | 1126 | 44 → 23 | 3 → 2 |
| taskless fast path OFF | 2158 | 1143 | 44 → 23 | 3 → 2 |
| 8/17-step task search ON | 2611 | 1148 | 53 → 23 | 4 → 2 |

Default code size -47.4%, static OpLoad -47.7% on the fixture. Existing fast-taskless original already **skipped executing the task search at runtime**, so static SPIR-V reduction is **not** equivalent to the same reduction in GPU time.

Vulkan (Mesa lavapipe, exact downloaded game-format fixtures) ran original and specialized pipelines independently and compared the entire arena output **bit-for-bit**, including payload and unwritten regions, both classic/coalesced vertex layouts and triangle/point meshes. `test_memu_coalesced_readback.py` passed. Full independent GPU correctness CI: https://github.com/erickmendes22/Swap2-Native/actions/runs/43544701003 . Android native-source/regression CI: https://github.com/erickmendes22/Swap2-Native/actions/runs/43544674423 .

## Release gate

This is a **GPU performance A/B candidate only**, NOT a release FPS gain. Compare Build148c against taskless specialization in the same scene and same Adreno driver, internal resolution, SGSR, VRS, coalesced mode and vegetation ON, using repeated GPU frame p50/p95 after warm-up. Reject if no reliable improvement, if any vegetation flicker/pixel difference, or if output/driver validation differs. Do not merge without on-device improvement.
