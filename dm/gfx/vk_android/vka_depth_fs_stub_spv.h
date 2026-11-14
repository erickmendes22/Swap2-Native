// SPDX-FileCopyrightText: Copyright 2026 Swap2-Native contributors
// SPDX-License-Identifier: GPL-3.0-or-later
// Handwritten SPIR-V 1.0 equivalent to:
// #version 450
// layout(origin_upper_left) in; void main() {}
// Fragment stage remains PRESENT for Qualcomm occlusion counters. No
// colour output, depth/stencil/sample modification, resource use or discard.
// Never select this without vka_depth_fs_spv_safe + depth-only draw guards.
#ifndef VKA_DEPTH_FS_STUB_SPV_H
#define VKA_DEPTH_FS_STUB_SPV_H
#include <stdint.h>
static const uint32_t VKA_DEPTH_FS_STUB_SPV[] = {
    UINT32_C(0x07230203), UINT32_C(0x00010000), 0, 5, 0,
    UINT32_C(0x00020011), 1,                // OpCapability Shader
    UINT32_C(0x0003000e), 0, 1,             // OpMemoryModel Logical GLSL450
    UINT32_C(0x0005000f), 4, 1,             // OpEntryPoint Fragment %1 "main"
    UINT32_C(0x6e69616d), 0,
    UINT32_C(0x00030010), 1, 7,             // OpExecutionMode %1 OriginUpperLeft
    UINT32_C(0x00020013), 2,                // %2 = OpTypeVoid
    UINT32_C(0x00030021), 3, 2,             // %3 = OpTypeFunction %2
    UINT32_C(0x00050036), 2, 1, 0, 3,       // %1 = OpFunction %2 None %3
    UINT32_C(0x000200f8), 4,                // %4 = OpLabel
    UINT32_C(0x000100fd),                   // OpReturn
    UINT32_C(0x00010038),                   // OpFunctionEnd
};
#endif
