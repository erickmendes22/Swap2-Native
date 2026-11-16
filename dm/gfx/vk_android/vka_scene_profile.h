// Exact known scene shapes, not a substring match against arbitrary targets.
#pragma once
#include <string.h>
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
