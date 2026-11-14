# Ocarina Vulkan direct GPU dispatch — bench result: not a release candidate

The baseline Build148c routes all direct and indirect task/mesh guest programs through **vkCmdDispatchIndirect**, even when direct guest task counts are already known.

This experiment preserved all guest true-indirect reads, 2D launch grids, Vulkan barriers, clipping at the arena limit, shaders, 42k program library and scene geometry. It replaced only proven direct / one-dimensional launch commands with **vkCmdDispatch**, retaining the generated NTASK/TOTAL bounds guard.

All 108,864 production-helper capacity combinations passed with ASan and UBSan; in 11,326 cases the dispatch could use the direct form. Android Vulkan source CI: https://github.com/erickmendes22/Swap2-Native/actions/runs/43586837354

Actual identical GPU program, arena bytes and host workgroup count validated on Mesa Lavapipe. Median GPU time **per dispatch** from the benchmark at commit 10fbeb92:
- 8×32 workgroups: direct 22,158 ns, indirect 22,490 ns (1.5% less).
- 64×32: direct 26,828 ns, indirect 26,318 ns (1.9% more).
- 256×32: direct 32,386 ns, indirect 32,028 ns (1.1% more).
Full Vulkan CI: https://github.com/erickmendes22/Swap2-Native/actions/runs/43586834404

**Result:** no consistent reduction in GPU work. We cannot infer an Adreno FPS improvement from Lavapipe, and the original user explicitly requires a strong synthetic performance indicator before testing another APK. Do not merge this feature or generate an APK for it.

Next experiment: direct GPU memory-store work, comparing actual scalar-plane writes with packed vector writes under bitwise output comparison. This is deliberately different from the failed 2026-11-12 Build117, which removed bitcasts but still issued four scalar GPU stores per vec4.
