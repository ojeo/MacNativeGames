/* Detect integer-coordinate texture reads in the MSL associated with a reflection binding. */
#pragma once
#include <string.h>

static inline int nvn_msl_reads_texels(const char *source, const char *name) {
    if (!source || !name || !*name) return 0;
    const size_t length = strlen(name);
    for (const char *p = source; (p = strstr(p, name)) != NULL; p += length)
        if (!strncmp(p + length, ".read(", 6)) return 1;
    return 0;
}
