// Vulkan compute mesh look-ahead: constant NVN render-enable is a pure
// replay-state update (S.rc_skip = 0). It makes no GPU query, memory transfer,
// guest barrier or render-target change. The only admitted case is
// OP_RENDER_COND with mode=2, Ocarina, and opt-in feature enabled.
// All modes 0/1 depend on query results and mode 3 DISABLES drawing.
#pragma once
static inline int vka_memu_true_cond_allowed(int ocarina, int enabled, unsigned mode) {
    return ocarina && enabled && mode == 2u;
}
