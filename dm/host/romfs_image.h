// DMROMFS1's index loader, shared by the host mount and iOS startup. Startup must validate the same index before replacing a working folder.
#pragma once
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct { uint64_t a, b; uint32_t name; uint16_t nlen; uint8_t type, flags; } __attribute__((packed)) img_ent;   // directory: a = first child, b = children; file: a = offset, b = size
_Static_assert(sizeof(img_ent) == 24, "RomFS image entry layout");
#define IMG_ENT_DAMAGED 1    // in the image: this file failed the NCA's hash check and was written as read (nx_extract --allow-damaged)
#define IMG_ENT_REPORTED 2   // in memory only: the host has named this damaged file in its log
// aux / aux_free: a NUP image's own state (nup_image.h: its compressed files and their cache), freed with the image; NULL for a DMROMFS1 image
typedef struct { int fd; uint64_t n, damaged; img_ent *e; const char *names; void *aux; void (*aux_free)(void *); } romfs_img;

static void romfs_image_close(romfs_img *m) {
    if (m) { close(m->fd); free(m->e); if (m->aux_free) m->aux_free(m->aux); free(m); }
}
static int romfs_image_read(int fd, void *buf, size_t size, off_t off) {
    size_t got = 0;
    while (got < size) {
        ssize_t n = pread(fd, (char *)buf + got, size - got, off + (off_t)got);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { if (!n) errno = EINVAL; return 0; }
        got += (size_t)n;
    }
    return 1;
}
// Swap2-Native: a Nintendo RomFS image as is (hactool --romfs, or a dump's romfs.bin: the 0x50-byte header, the directory and file tables,
// the data from the header's data offset) opened into the same index as a DMROMFS1 image: breadth-first, each directory's children one
// run sorted by name (bytes, a shorter prefix first), a file's a its absolute offset in the image. NULL with errno EINVAL when the file is
// not one (or its tables are out of bounds, loop or repeat a name), another errno for an I/O or allocation failure. Only the host's hle_fs.c
// opens one: the header's other includers (the Mac launcher, the iOS app, the tool tests' validators) read DMROMFS1 images alone, hence unused
typedef struct { uint32_t meta; uint32_t name, nlen; uint8_t type; } romfs_nx_kid;
static int romfs_nx_kid_cmp(const void *pa, const void *pb, void *names) {
    const romfs_nx_kid *a = pa, *b = pb; const char *n = names;
    size_t l = a->nlen < b->nlen ? a->nlen : b->nlen; int c = memcmp(n + a->name, n + b->name, l);
    return c ? c : (a->nlen > b->nlen) - (a->nlen < b->nlen);
}
static void romfs_nx_sort(romfs_nx_kid *k, size_t n, const char *names) {   // (insertion sort per directory run: runs are short; no qsort_r portability)
    for (size_t i = 1; i < n; i++) {
        romfs_nx_kid x = k[i]; size_t j = i;
        while (j && romfs_nx_kid_cmp(&k[j - 1], &x, (void *)names) > 0) { k[j] = k[j - 1]; j--; }
        k[j] = x;
    }
}
static uint32_t romfs_nx_u32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static uint64_t romfs_nx_u64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
__attribute__((unused)) static romfs_img *romfs_nx_open(const char *path) {
    int fd = open(path, O_RDONLY); struct stat st; uint8_t h[0x50]; romfs_img *m = NULL;
    uint8_t *dmeta = NULL, *fmeta = NULL; romfs_nx_kid *kids = NULL; uint32_t *queue = NULL; char *pool = NULL; img_ent *e = NULL;
    if (fd < 0) return NULL;
    if (fstat(fd, &st) || !romfs_image_read(fd, h, sizeof h, 0)) goto bad;
    errno = EINVAL;
    uint64_t hsize = romfs_nx_u64(h), doff = romfs_nx_u64(h + 0x18), dsize = romfs_nx_u64(h + 0x20),
             foff = romfs_nx_u64(h + 0x38), fsize = romfs_nx_u64(h + 0x40), data = romfs_nx_u64(h + 0x48), size = (uint64_t)st.st_size;
    if (hsize != 0x50 || data < 0x50 || data > size || dsize < 0x18 || dsize > (64u << 20) || fsize > (512u << 20) ||
        doff > size || dsize > size - doff || foff > size || fsize > size - foff) goto bad;
    if (!(dmeta = malloc((size_t)dsize)) || !(fmeta = malloc(fsize ? (size_t)fsize : 1))) { errno = ENOMEM; goto bad; }
    if (!romfs_image_read(fd, dmeta, (size_t)dsize, (off_t)doff) || (fsize && !romfs_image_read(fd, fmeta, (size_t)fsize, (off_t)foff))) goto bad;
    errno = EINVAL;
    // Directory entry: parent, sibling, first child directory, first file, hash next (u32 each), name length (u32), name. File entry:
    // parent, sibling (u32), data offset, size (u64), hash next, name length (u32), name. None: 0xFFFFFFFF. Entries are 4-byte aligned.
    uint64_t maxd = dsize / 0x18 + 1, maxf = fsize / 0x20 + 1, cap = maxd + maxf;
    if (!(kids = malloc(sizeof *kids * (size_t)cap)) || !(queue = malloc(sizeof *queue * (size_t)maxd)) ||
        !(e = malloc(sizeof *e * (size_t)cap)) || !(pool = malloc((size_t)(dsize + fsize) + 1))) { errno = ENOMEM; goto bad; }
    uint64_t n = 1, names = 0, qh = 0, qt = 0, kidsn = 0;
    queue[qt++] = 0;   // the root directory, entry 0
    memset(&e[0], 0, sizeof e[0]);
    uint64_t *ent_of = (uint64_t *)malloc(sizeof *ent_of * (size_t)maxd); if (!ent_of) { errno = ENOMEM; goto bad; }
    ent_of[0] = 0;
    while (qh < qt) {
        uint64_t me = ent_of[qh]; uint32_t d = queue[qh++];
        if ((uint64_t)d + 0x18 > dsize) goto bad_free;
        const uint8_t *dr = dmeta + d;
        size_t first = (size_t)kidsn;
        for (uint32_t c = romfs_nx_u32(dr + 8), guard = 0; c != 0xFFFFFFFFu; guard++) {   // child directories
            if ((uint64_t)c + 0x18 > dsize || guard > maxd || kidsn >= cap) goto bad_free;
            uint32_t nl = romfs_nx_u32(dmeta + c + 0x14);
            if (!nl || nl > 0x300 || (uint64_t)c + 0x18 + nl > dsize) goto bad_free;
            memcpy(pool + names, dmeta + c + 0x18, nl);
            kids[kidsn++] = (romfs_nx_kid){c, (uint32_t)names, nl, 0}; names += nl;
            c = romfs_nx_u32(dmeta + c + 4);
        }
        for (uint32_t f = romfs_nx_u32(dr + 12), guard = 0; f != 0xFFFFFFFFu; guard++) {   // files
            if ((uint64_t)f + 0x20 > fsize || guard > maxf || kidsn >= cap) goto bad_free;
            uint32_t nl = romfs_nx_u32(fmeta + f + 0x1c);
            if (!nl || nl > 0x300 || (uint64_t)f + 0x20 + nl > fsize) goto bad_free;
            memcpy(pool + names, fmeta + f + 0x20, nl);
            kids[kidsn++] = (romfs_nx_kid){f, (uint32_t)names, nl, 1}; names += nl;
            f = romfs_nx_u32(fmeta + f + 4);
        }
        size_t cnt = (size_t)kidsn - first;
        romfs_nx_sort(kids + first, cnt, pool);
        e[me].a = n; e[me].b = cnt;
        for (size_t j = 0; j < cnt; j++) {
            const romfs_nx_kid *k = &kids[first + j]; const char *nm = pool + k->name;
            if (memchr(nm, 0, k->nlen) || memchr(nm, '/', k->nlen) || (k->nlen == 1 && nm[0] == '.') || (k->nlen == 2 && !memcmp(nm, "..", 2))) goto bad_free;
            if (j && !romfs_nx_kid_cmp(&kids[first + j - 1], k, pool)) goto bad_free;   // a name twice
            if (n >= cap) goto bad_free;
            img_ent *x = &e[n];
            x->name = k->name; x->nlen = (uint16_t)k->nlen; x->type = k->type; x->flags = 0;
            if (k->type) {
                uint64_t off = romfs_nx_u64(fmeta + k->meta + 8), sz = romfs_nx_u64(fmeta + k->meta + 0x10);
                if (off > size - data || sz > size - data - off) goto bad_free;
                x->a = data + off; x->b = sz;
            } else {
                if (qt >= maxd) goto bad_free;   // (more directories than the table holds: a loop)
                ent_of[qt] = n; queue[qt++] = k->meta;
                x->a = x->b = 0;
            }
            n++;
        }
    }
    free(ent_of);
    if (n > UINT32_MAX) goto bad;
    // the index as romfs_image_open keeps it: the entries, then the name pool, in one block
    if (!(m = calloc(1, sizeof *m))) { errno = ENOMEM; goto bad; }
    if (!(m->e = malloc(sizeof *e * (size_t)n + (size_t)names + 1))) { errno = ENOMEM; goto bad; }
    memcpy(m->e, e, sizeof *e * (size_t)n);
    memcpy((char *)m->e + sizeof *e * (size_t)n, pool, (size_t)names);
    m->fd = fd; m->n = n; m->names = (const char *)m->e + sizeof *e * (size_t)n;
    free(dmeta); free(fmeta); free(kids); free(queue); free(pool); free(e);
    return m;
bad_free:
    free(ent_of);
bad: {
    int er = errno ? errno : EINVAL;
    free(dmeta); free(fmeta); free(kids); free(queue); free(pool); free(e);
    if (m) { free(m->e); free(m); }
    close(fd);
    errno = er; return NULL;
    }
}

// NULL for an incomplete or invalid image (errno EINVAL), an I/O error, or allocation failure. The caller owns the descriptor and index on success.
static romfs_img *romfs_image_open(const char *path) {
    int fd = open(path, O_RDONLY); struct stat st; uint8_t h[32]; romfs_img *m = NULL; uint64_t ioff, isz, n;
    if (fd < 0) return NULL;
    if (fstat(fd, &st) || !romfs_image_read(fd, h, sizeof h, 0)) goto bad;
    errno = EINVAL;
    if (memcmp(h, "DMROMFS1", 8) || st.st_size < (off_t)sizeof h) goto bad;
    memcpy(&ioff, h + 8, 8); memcpy(&isz, h + 16, 8); memcpy(&n, h + 24, 8);
    if (!n || n > UINT32_MAX || ioff < sizeof h || ioff > (uint64_t)st.st_size || isz != (uint64_t)st.st_size - ioff || isz > SIZE_MAX || n > isz / sizeof(img_ent)) goto bad;
    if (!(m = calloc(1, sizeof *m))) goto bad;
    m->fd = fd;
    if (!(m->e = malloc((size_t)isz)) || !romfs_image_read(fd, m->e, (size_t)isz, (off_t)ioff)) goto bad;
    m->n = n; m->names = (const char *)m->e + n * sizeof(img_ent);
    uint64_t pool = isz - n * sizeof(img_ent), next_child = 1;
    errno = EINVAL;
    if (m->e[0].type || m->e[0].nlen) goto bad;
    for (uint64_t k = 0; k < n; k++) {
        const img_ent *x = &m->e[k];
        if ((uint64_t)x->name + x->nlen > pool || x->type > 1 || x->flags > (x->type ? IMG_ENT_DAMAGED : 0)) goto bad;
        m->damaged += x->flags;
        const char *name = m->names + x->name;
        if (k && (!x->nlen || x->nlen > 0x300 || memchr(name, 0, x->nlen) || memchr(name, '/', x->nlen) || (x->nlen == 1 && name[0] == '.') || (x->nlen == 2 && !memcmp(name, "..", 2)))) goto bad;
        if (x->type) { if (x->a < sizeof h || x->a > ioff || x->b > ioff - x->a) goto bad; }
        else {
            // Breadth-first child runs partition entries 1..n-1; reject cycles, aliases and unreachable entries.
            if (x->a != next_child || x->a <= k || x->a > n || x->b > n - x->a) goto bad;
            next_child += x->b;
        }
    }
    if (next_child != n) goto bad;
    for (uint64_t k = 0; k < n; k++) {
        const img_ent *d = &m->e[k]; if (d->type) continue;
        for (uint64_t j = 1; j < d->b; j++) {
            const img_ent *a = &m->e[d->a + j - 1], *b = a + 1;
            size_t len = a->nlen < b->nlen ? a->nlen : b->nlen;
            int c = memcmp(m->names + a->name, m->names + b->name, len);
            if (c > 0 || (!c && a->nlen >= b->nlen)) goto bad;
        }
    }
    return m;
bad: {
    int e = errno ? errno : EINVAL;
    if (m) romfs_image_close(m); else close(fd);
    errno = e; return NULL;
    }
}
