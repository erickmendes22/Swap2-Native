// Swap2-Native: romfs_nx_open (romfs_image.h) against a RomFS folder - every path and size, and the bytes of one file in <every> (its first and
// last 64 KiB). usage: t_romfs_nx <romfs.bin> <the same RomFS extracted> [every, default 50]. Builds alone: cc -O2 -o t_romfs_nx t_romfs_nx.c
#define _GNU_SOURCE
#include <dirent.h>
#include <stdio.h>
#include "../romfs_image.h"

static romfs_img *m;
static const char *root;
static unsigned long every = 50, files, dirs, sampled, bad;
static uint8_t a[65536], b[65536];

static void walk(uint64_t k, const char *rel) {
    const img_ent *d = &m->e[k];
    char host[4096];
    snprintf(host, sizeof host, "%s/%s", root, rel);
    unsigned long want = 0;  // the folder's own count of children
    DIR *dir = opendir(host);
    if (!dir) { printf("MISSING dir %s\n", rel); bad++; return; }
    for (struct dirent *x; (x = readdir(dir));) if (strcmp(x->d_name, ".") && strcmp(x->d_name, "..") && strcmp(x->d_name, ".listing")) want++;   // (.listing: a downloader's file in every folder of a copied dump, not RomFS)
    closedir(dir);
    if (want != d->b) { printf("COUNT %s: image %llu, folder %lu\n", rel, (unsigned long long)d->b, want); bad++; }
    for (uint64_t j = 0; j < d->b; j++) {
        const img_ent *x = &m->e[d->a + j];
        char r[4096];
        snprintf(r, sizeof r, "%s%s%.*s", rel, *rel ? "/" : "", (int)x->nlen, m->names + x->name);
        snprintf(host, sizeof host, "%s/%s", root, r);
        struct stat st;
        if (stat(host, &st)) { printf("MISSING %s\n", r); bad++; continue; }
        if (!x->type) { dirs++; if (!S_ISDIR(st.st_mode)) { printf("NOT A DIR %s\n", r); bad++; } walk(d->a + j, r); continue; }
        files++;
        if ((uint64_t)st.st_size != x->b) { printf("SIZE %s: image %llu, folder %lld\n", r, (unsigned long long)x->b, (long long)st.st_size); bad++; continue; }
        if (files % every) continue;
        sampled++;
        int fd = open(host, O_RDONLY);
        for (int end = 0; end < 2 && fd >= 0; end++) {
            uint64_t n = x->b < sizeof a ? x->b : sizeof a, off = end ? x->b - n : 0;
            if (!n || !romfs_image_read(m->fd, a, n, (off_t)(x->a + off)) || !romfs_image_read(fd, b, n, (off_t)off) || memcmp(a, b, n)) {
                if (n) { printf("BYTES %s (%s)\n", r, end ? "end" : "start"); bad++; }
                break;
            }
        }
        if (fd >= 0) close(fd);
    }
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s <romfs.bin> <romfs folder> [every]\n", argv[0]); return 2; }
    if (argc > 3) every = strtoul(argv[3], NULL, 0);
    root = argv[2];
    if (!(m = romfs_nx_open(argv[1]))) { perror("romfs_nx_open"); return 1; }
    printf("%llu entries\n", (unsigned long long)m->n);
    walk(0, "");
    printf("%lu files, %lu directories, %lu files' bytes compared, %lu differences\n", files, dirs, sampled, bad);
    romfs_image_close(m);
    return bad ? 1 : 0;
}
