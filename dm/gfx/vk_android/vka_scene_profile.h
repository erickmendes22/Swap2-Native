// Exact known scene shapes, not a substring match against arbitrary targets.
#pragma once
#include <string.h>
static inline int vka_scene_profile_size(const char *desc) {
    if(!desc || strlen(desc)<9 || (desc[9] && desc[9]!=' '))return 0;
    return !strncmp(desc,"683x384x1",9) || !strncmp(desc,"640x360x1",9) ||
        !strncmp(desc,"960x540x1",9);
}
