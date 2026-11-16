// Exact known scene shapes, not a substring match against arbitrary targets.
#pragma once
#include <string.h>
// The sampled GPU profiler receives full pass descriptors such as
// "1280x720x1 c0:122 d:126". Match the *token* and its separator,
// not the implicit NUL byte of the shorter string literal.
static inline int vka_scene_profile_1280(const char *desc) {
    return desc && !strncmp(desc, "1280x720x1", 10) &&
           (!desc[10] || desc[10] == ' ');
}
static inline int vka_scene_profile_size(const char *desc) {
    if(!desc || strlen(desc)<9)return 0;
    // The heavy 1280x720 scene appears in the user's GPU samples. The
    // former strict nine-character gate omitted it from the 16-draw timing
    // attribution entirely; accept exact size tokens, never a prefix.
    const char *const shapes[] = {"683x384x1", "640x360x1", "960x540x1",
                                   "1280x720x1"};
    for (unsigned i = 0; i < sizeof(shapes)/sizeof(shapes[0]); i++) {
        size_t n = strlen(shapes[i]);
        if (!strncmp(desc, shapes[i], n) && (!desc[n] || desc[n] == ' '))
            return 1;
    }
    return 0;
}
