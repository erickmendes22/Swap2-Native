// SPDX-FileCopyrightText: Copyright 2026 Swap2-Native contributors
// SPDX-License-Identifier: GPL-3.0-or-later
// Strict SPIR-V proof: a fragment shader may be dropped from a depth-only
// draw only when all its stores are invocation-private or ordinary colour
// outputs, and it cannot change coverage/depth/stencil or global memory.
// The output attachment is ALREADY masked and omitted by the caller.
// Fail closed on unknown pointers, specialization, ray, atomics and EXT ops.
#ifndef VKA_DEPTH_FS_ELIDE_H
#define VKA_DEPTH_FS_ELIDE_H
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
static inline int vka_depth_fs_spv_safe(const uint32_t *w, size_t nw) {
    if (!w || nw < 5 || w[0] != UINT32_C(0x07230203) || !w[3] ||
        w[3] > 1048576u || nw > 1048576u) return 0;
    const uint32_t bound = w[3];
    // Pointer roots: 3 Output, 6 Private, 7 Function; other classes refuse.
    uint8_t *roots = calloc(bound, 1);
    if (!roots) return 0;
    int safe = 1, fragment_entry = 0;
    for (size_t i = 5; i < nw && safe;) {
        uint32_t op = w[i] & 0xffffu, n = w[i] >> 16;
        if (!n || i + n > nw) { safe = 0; break; }
        switch (op) {
        case 15: // OpEntryPoint: ExecutionModel Fragment == 4
            if (n < 4 || w[i+1] != 4) safe = 0;
            else fragment_entry = 1;
            break;
        case 16: { // OpExecutionMode: only pixel origin and early depth test
            if (n < 3) { safe = 0; break; }
            uint32_t mode = w[i+2];
            if (mode != 7 && mode != 8 && mode != 9) safe = 0;
            break;
        }
        case 331: // OpExecutionModeId: unknown shader-output semantics
        case 57:  // OpFunctionCall: do not assume pointer alias/side effects
        case 63: case 64: // OpCopyMemory / OpCopyMemorySized
        case 99: // OpImageWrite
        case 224: case 225: // ControlBarrier / MemoryBarrier
        case 252: case 4416: case 5380: // Kill, Terminate, Demote
        case 318: case 319: // atomic flags
            safe = 0; break;
        case 71: // OpDecorate BuiltIn FragDepth / SampleMask / FragStencil
            if (n >= 4 && w[i+2] == 11 &&
                (w[i+3] == 22 || w[i+3] == 20 ||
                 w[i+3] == 5014)) safe = 0;
            break;
        case 72: // OpMemberDecorate BuiltIn
            if (n >= 5 && w[i+3] == 11 &&
                (w[i+4] == 22 || w[i+4] == 20 ||
                 w[i+4] == 5014)) safe = 0;
            break;
        case 59: // OpVariable: resultType, resultId, storageClass
            if (n < 4 || w[i+2] >= bound) { safe = 0; break; }
            roots[w[i+2]] = w[i+3] == 3 ? 3 : w[i+3] == 6 ? 6 :
                            w[i+3] == 7 ? 7 : 1;
            break;
        case 65: case 66: case 67: case 70: // pointer access chains
        case 83: // OpCopyObject: only carry known original pointer class
            if (n < 4 || w[i+2] >= bound || w[i+3] >= bound) { safe = 0; break; }
            roots[w[i+2]] = roots[w[i+3]];
            break;
        case 62: // OpStore: only colour or invocation-local state
            if (n < 3 || w[i+1] >= bound ||
                (roots[w[i+1]] != 3 && roots[w[i+1]] != 6 &&
                 roots[w[i+1]] != 7)) safe = 0;
            break;
        default:
            // All atomic shader instructions, including core and vendor ones.
            if ((op >= 227 && op <= 244) || op >= 4000) safe = 0;
            break;
        }
        i += n;
    }
    free(roots);
    return safe && fragment_entry;
}
#endif
