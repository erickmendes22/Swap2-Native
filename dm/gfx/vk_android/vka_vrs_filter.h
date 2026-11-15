// Diagnostic exclusions only: this never makes an ineligible pipeline use VRS.
#pragma once
#include <stdint.h>

static inline int vka_vrs_space(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

// Comma-separated hexadecimal FS keys (optional0x prefix), exact matches.
// 0 = keep the existing policy,1 = exclude,-1 = malformed WHOLE list.
// Callers fail to full-rate shading on malformed input, even after a match.
static inline int vka_vrs_exclusion(const char *list, uint64_t key) {
    if (!list) return 0;
    const char *p = list;
    while (vka_vrs_space(*p)) p++;
    if (!*p) return 0;
    int matched = 0;
    for (;;) {
        if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) p += 2;
        uint64_t value = 0; unsigned digits = 0;
        for (;;) {
            unsigned c = (unsigned char)*p, v;
            if (c >= '0' && c <= '9') v = c - '0';
            else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
            else break;
            if (++digits > 16) return -1;
            value = (value << 4) | v; p++;
        }
        if (!digits) return -1;
        matched |= value == key;
        while (vka_vrs_space(*p)) p++;
        if (!*p) return matched;
        if (*p++ != ',') return -1;
        while (vka_vrs_space(*p)) p++;
        if (!*p) return -1;
    }
}
