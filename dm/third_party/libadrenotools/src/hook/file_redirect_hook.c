// SPDX-License-Identifier: BSD-2-Clause
// Qualcomm qgl_config.txt-only file redirection, adapted from libadrenotools.
// Other fopen calls pass through unchanged in hook_impl.cpp.
#include "hook_impl.h"
__attribute__((visibility("default"))) FILE *fopen(const char *filename, const char *mode) {
    return hook_fopen(filename, mode);
}
