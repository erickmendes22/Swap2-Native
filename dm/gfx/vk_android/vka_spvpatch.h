// SPIR-V rewrites made by the replay at pipeline time (vka_spvpatch.c). Plain C, no Vulkan
#pragma once
#include <stddef.h>
#include <stdint.h>
// The vertex module w (nw words) with the vec4 float Input variables at the locations of umask retyped as uvec4 and those of smask as ivec4, every load of them bit-cast back
// to float: the shader then sees the integer register bits Maxwell's fetch gives an integer format. A malloc'd copy (*out_nw words), or NULL with the reason in err
uint32_t *vka_spv_vin_retype(const uint32_t *w, size_t nw, uint32_t umask, uint32_t smask, size_t *out_nw, char *err, size_t errn);
// Subgroup operations and built-ins rewritten as subgroups of one invocation, for a stage the device runs none in (vka_spvpatch.c). A malloc'd copy (*out_nw words,
// *changed = 1), NULL with err empty when the module has none, NULL with the reason in err when it cannot be rewritten
uint32_t *vka_spv_subgroup_single(const uint32_t *w, size_t nw, size_t *out_nw, int *changed, char *err, size_t errn);
// A geometry shader's memory writes, counted (the return; -1 with err on failure) and, with out and a count above 0, the module with each of them made only by the run of
// the shader that first claims its primitive in the storage buffer at set 0 binding (zeroed for each draw, a word per primitive), malloc'd (*out_nw words): vka_spvpatch.c
int vka_spv_gs_claim(const uint32_t *w, size_t nw, uint32_t binding, uint32_t **out, size_t *out_nw, char *err, size_t errn);
// A pixel shader's float colour outputs at the locations of umask / smask as unsigned / signed integers of their bits (each store bit-cast), for integer attachments: malloc'd
// (*out_nw words), NULL with the reason in err (vka_spvpatch.c)
uint32_t *vka_spv_fout_retype(const uint32_t *w, size_t nw, uint32_t umask, uint32_t smask, size_t *out_nw, char *err, size_t errn);
// An image to retype (vka_spv_img_retype): the variable at descriptor set / binding, its class (1 unsigned, 2 signed integer) and, for a storage image, the SPIR-V Image
// Format to declare (0: keep Unknown; else one of that class: Rgba32i 21 ... R8i 29, Rgba32ui 30 ... R8ui 39). A sampled image takes 0 (it keeps Unknown)
typedef struct { uint32_t set, binding; uint8_t cls, fmt; } vka_spv_imgsel;
// The float storage images of format Unknown and the float sampled images (combined or separate; or arrays of them) at sel (nsel, at most 8) as integer images of that
// class (and format), each read, fetch, sample and gather bit-cast back to float and each written texel bit-cast to the integer vector, for integer textures bound to
// formatted surface operations and texture reads; a depth comparison on one is refused: malloc'd (*out_nw words), NULL with the reason in err (vka_spvpatch.c)
uint32_t *vka_spv_img_retype(const uint32_t *w, size_t nw, const vka_spv_imgsel *sel, int nsel, size_t *out_nw, char *err, size_t errn);

// Conservative Ocarina-specific compute retile: in-place SPIR-V rewrite of
// 8x4x4 local size to 8x4x2 only if no local/group-dependent operations exist.
// The caller must launch twice as many groups in Z. 1 = safe rewrite applied.
int vka_spv_oot_cs_retile(uint32_t *w, size_t nw, char *why, size_t whylen);

/* Ocarina-specific virtualized 8x4x4 -> 8x4x2 compute retile.
 * Caller frees the returned SPIR-V words. All original workgroup builtins
 * are reconstructed from GlobalInvocationId at the exact 8x9x12 dispatch.
 * Refuse barriers/LDS/atomics/subgroups, unknown and aliased inputs. */
uint32_t *vka_spv_oot_cs_virtual_retile(const uint32_t *w, size_t nw,
                                       size_t *out_nw, char *why, size_t whylen);

// Texture-use feedback for the texture pool (vka_spvpatch.c vka_spv_pool_fb): before each read of the pool (a one-index access chain into the sampled-image array at set
// `set` binding `tex_binding`) the module sets bit (id & 31) of word id >> 5 of a storage buffer at set `fb_set` binding `fb_binding`, id the index's low 20 bits: an atomic
// OR when a load finds the bit clear. flags: VKA_PFB_VTX_STORES (the device has vertexPipelineStoresAndAtomics: vertex, tessellation and geometry modules may take it),
// VKA_PFB_EARLY (a pixel shader whose tests can give the same result early gets EarlyFragmentTests: its stores would otherwise move its depth test after shading).
// alpha_spec: the SpecId of the alpha test's function (DMSH_VK_SPEC_ALPHA_FUNC). A malloc'd copy (*out_nw words; *sites the reads given code; *early 0 no mode added,
// 1 added and right for every pipeline without alpha to coverage, 2 added and right only with the alpha test off too); NULL with err empty when the module reads no pool,
// NULL with the reason in err when it cannot take the code (the module is then used as it is: its pool reads report nothing)
enum { VKA_PFB_VTX_STORES = 1, VKA_PFB_EARLY = 2 };
uint32_t *vka_spv_pool_fb(const uint32_t *w, size_t nw, uint32_t set, uint32_t tex_binding, uint32_t fb_set, uint32_t fb_binding, unsigned flags, uint32_t alpha_spec, size_t *out_nw, int *sites, int *early, char *err, size_t errn);
// A pixel shader's user inputs moved to other locations, or made constant, for another earlier stage than its own (vka_spvpatch.c vka_spv_input_remap): the input at location
// L < 16 moves to nibble L of map, or with nibble 0xf becomes a Private (0, 0, 0, 1). A malloc'd copy (*out_nw words; *moved / *consts the original locations of each kind);
// NULL with err empty when nothing changes, NULL with the reason in err when it cannot be made
uint32_t *vka_spv_input_remap(const uint32_t *w, size_t nw, uint64_t map, size_t *out_nw, uint32_t *moved, uint32_t *consts, char *err, size_t errn);

uint32_t *vka_spv_spec_freeze(const uint32_t *w, size_t nw, uint32_t spec_id, uint32_t value, size_t *out_nw);
