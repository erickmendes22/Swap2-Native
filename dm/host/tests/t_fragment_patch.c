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
    assert(vka_fragment_patch_library_compatible(&a, &b));
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
    {
        dmsh_vk_header bh = before.header, ph = before.header;
        bh.entry_count = ph.entry_count = 2;
        dmsh_vk_entry be[2] = {before.entry, before.entry};
        be[0].key = UINT64_C(0x19f99e925937b038);
        dmsh_vk_entry pe[2]; memcpy(pe, be, sizeof pe);
        vka_shlib full = a, pair = b;
        full.h = &bh; full.ent = be; pair.h = &ph; pair.ent = pe;
        assert(vka_fragment_patch_library_compatible(&full, &pair));
        ph.entry_count = 3;
        assert(!vka_fragment_patch_library_compatible(&full, &pair));
        ph.entry_count = 1; // a heavy-only import would lose the prior patch
        assert(!vka_fragment_patch_library_compatible(&full, &pair));
        ph.entry_count = 2;
        pe[0].key = key; // duplicate / unsorted keys
        assert(!vka_fragment_patch_library_compatible(&full, &pair));
        pe[0] = be[0]; pe[1].key++;
        assert(!vka_fragment_patch_library_compatible(&full, &pair));
        pe[1] = be[1]; pe[0].fout_types ^= 1;
        assert(!vka_fragment_patch_library_compatible(&full, &pair));
        pe[0] = be[0]; pe[1].flags ^= 1;
        assert(!vka_fragment_patch_library_compatible(&full, &pair));
        puts("fragment set: legacy + reviewed pair and six refusal cases passed");
    }
    if (argc == 3) {
        char err[256]; vka_shlib old={0}, patch={0};
        if (!vka_shlib_open(&old, argv[1], NULL, NULL, "0400486024DEC000", "674db0a4ff79", err, sizeof err) ||
            !vka_shlib_open(&patch, argv[2], "de2cd6b79f33", "a16478ff8bcd", "0400486024DEC000", "674db0a4ff79", err, sizeof err)) {
            fprintf(stderr,"%s\n",err); return 1;
        }
        assert(vka_fragment_patch_compatible(&old,&patch,key));
        assert(vka_fragment_patch_library_compatible(&old,&patch));
        vka_shlib_close(&old); vka_shlib_close(&patch);
        puts("real-library exact linkage passed");
    }
    puts("fragment linkage: match + 18 rejection cases passed");
    return 0;
}
