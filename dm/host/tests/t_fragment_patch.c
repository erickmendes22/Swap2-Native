// Exercise the production fragment linkage gate without a GPU or game bytes.
// Optional two paths also check the user's real baseline/replacement libraries.
#include "../../gfx/vk_android/vka_fragment_patch.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

static const uint64_t key = UINT64_C(0x1e4d2630d24846d0);
typedef struct {
    dmsh_vk_header header;
    dmsh_vk_entry entry;
    dmsh_vk_bind bind;
    dmsh_vk_module modules[2];
    unsigned char blob[16];
} fixture;

static vka_shlib view(fixture *f) {
    return (vka_shlib){.h=&f->header, .ent=&f->entry, .bind=&f->bind,
                       .mod=f->modules, .blob=f->blob};
}
int main(int argc, char **argv) {
    fixture before = {0};
    memcpy(before.header.game, "0400486024DEC000", 16);
    memcpy(before.header.inputs, "aa5e7196d926", 12);
    memcpy(before.header.abi, "674db0a4ff79", 12);
    before.header.entry_count = 1;
    before.header.subgroup_size = 64;
    before.header.ssbo_align = 64;
    before.entry = (dmsh_vk_entry){.key=key, .stage=DMSH_VK_STAGE_FS,
        .mod_count=2, .bind_count=1, .c1_len=16, .fout_mask=1};
    before.modules[0].variant = 0;
    before.modules[1].variant = 1;
    fixture after = before;
    vka_shlib a=view(&before), b=view(&after);
    assert(vka_fragment_patch_compatible(&a, &b, key));
    // Mutation after each fresh copy must be refused by the exact same gate
    // the renderer calls, including same-count but different module variants.
#define REJECT(statement) do { after=before; statement; assert(!vka_fragment_patch_compatible(&a,&b,key)); } while (0)
    REJECT(after.header.inputs[0] ^= 1);
    REJECT(after.header.abi[0] ^= 1);
    REJECT(after.header.game[0] ^= 1);
    REJECT(after.header.subgroup_size = 32);
    REJECT(after.header.ssbo_align = 128);
    REJECT(after.entry.key++);
    REJECT(after.entry.stage = DMSH_VK_STAGE_CS);
    REJECT(after.entry.flags ^= 1);
    REJECT(after.entry.fout_mask ^= 1);
    REJECT(after.entry.fout_types ^= 1);
    REJECT(after.entry.uint_mask ^= 1);
    REJECT(after.entry.vin_types ^= 1);
    REJECT(after.entry.vin_mask ^= 1);
    REJECT(after.entry.local[0]++);
    REJECT(after.entry.shared++);
    REJECT(after.bind.dim++);
    REJECT(after.blob[0]++);
    REJECT(after.modules[1].variant = 2);
    after=before;
    if (argc == 3) {
        char err[256]; vka_shlib old={0}, patch={0};
        if (!vka_shlib_open(&old, argv[1], NULL, NULL, "0400486024DEC000", "674db0a4ff79", err, sizeof err) ||
            !vka_shlib_open(&patch, argv[2], "de2cd6b79f33", "a16478ff8bcd", "0400486024DEC000", "674db0a4ff79", err, sizeof err)) {
            fprintf(stderr,"%s\n",err); return 1;
        }
        assert(vka_fragment_patch_compatible(&old,&patch,key));
        vka_shlib_close(&old); vka_shlib_close(&patch);
        puts("real-library exact linkage passed");
    }
    puts("fragment linkage: match + 18 rejection cases passed");
    return 0;
}
