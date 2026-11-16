# Ocarina Switch 2 Android — GPU visual-quality patches (16 Nov 2026)

## Evidence: two actual Adreno 840 / proprietary 891.14 captures
These are **two measured runs, not controlled A/B proofs of any individual effect**.
Sources: user logs 0400486024DEC000-20261116-113049 and
0400486024DEC000-20261116-113200 (unpacked .7z).
Both use APK commit f59138f, Ocarina v131072, scene_720p,
DM_VK_VEGETATION=1, DM_VK_OOT_MESH_ROUTE=1 and QGL redirect armed.
The log does not confirm that proprietary Qualcomm consumed qgl_config.

| Metric | 11:30:49 log | 11:32:00 log |
| --- | ---: | ---: |
| frame 1201–1500 GPU p50 | 21.50ms | 21.93ms |
| reported FPS | 44.7 | 42.2 |
| mesh compute frame 1201 | 3.147ms | 3.173ms |
| "vegetation" GRAPHICS chunks frame 1201 | 13.022ms | 12.831ms |
| "mixed" GRAPHICS chunks frame 1201 | 5.016ms | 5.167ms |
| top graphics chunk frame 1201, fs=19f99e925937b038 | 3.641ms | 3.597ms |
| second graphics chunk frame 1201, fs=5684f5e658eda176 | 1.717ms | 1.688ms |
| third graphics chunk frame 1201, fs=47e804143a060733 | 0.952ms | 0.928ms |
| pass 128x128 colour+depth with ~208 draws | 0.767ms | 0.801ms |

"Vegetation" chunks are **not exclusively foliage**: timed groups include
VS, depth tests, ROP/colour and potentially unrelated scene content.
Do NOT sum different sampled GPU timestamp categories as if independent.
The 128x128 pass is NOT proven to be a shadow atlas; don't delete it.
The three top fragment keys are NOT proven fog, shadow or foliage shaders.

## Patch A, already implemented — reviewed cosmetic foliage pairs
Quality 0 retains the original complete scene.
Quality 1 removes **two paired mesh depth/colour variants** known
from game.tsv and Banana Native's reviewed seven pairs:
- d98076e4148db34f / fed302d791a4ba43
- 101ecb327aafe9b1 / 17c8ab6419068d4b

Quality 2 removes those, plus:
- eebdb9347d09b344 / 604134a5262ff670
- 25c4a740753e7d7a / 73dc0b90c4082e43
- 0c1ffecd02018fb0 / eed1add7c89f5d34

Quality 3 maps to existing complete supplemental foliage OFF (unchanged).
No wildcard shader deletion and no framebuffer-layout changes. Safe producer
filter refuses shader binds that could write external memory or use transform
feedback. Suppress eligible draws during lookahead BEFORE mesh compute, and
again at raster, preventing orphan depth/colour work. Identical game data,
same 42k base and 508-variant supplement; no shader prepare/rebuild needed.
Research C/JVM/Android NDK compile CI: 43889454112 SUCCESS.
Full APK build has a separate validation gate and original signer policy.
Performance and image quality still require on-device controlled A/B.

## Next quality-patch targets, NOT implemented, because the sources
## do not yet identify correct shader/pass semantics
1. **Shadow generation/filtering:** compare original game shadow atlas and
   cascades, if any, by actual image attachments and their producers. Lowering
   only the shadow-map size may save geometry/raster/ROP; lowering PCF
   tap count only affects verified shadow-sampling fragment shaders.
   Never assume the 128x128 pass is a shadow pass.
2. **Volumetric fog:** separate its volumetric integration passes from
   full-screen colour grading. Lower step/sample count or its intermediate
   buffer resolution when exact resource and shader dependencies are known.
   Fog/exposure colour multipliers alone do NOT remove GPU instructions;
   "SOUL RESTORED" style visual changes are not benchmark gains.
3. **Broader foliage density/LOD:** the 508 supplemental stages include
   114 originally sourced from Foliage BNSH containers (104 mesh + 10 task).
   The initial patch deliberately avoids assuming every Foliage stage is
   a safe independent object. Future low-density patches require verified
   depth/colour correspondence and side-effect rejection before omitting
   more than the seven reviewed original pairs.

For a reproducible result, use the SAME 720p scene, driver, temperature
and camera/route; capture GPU p50, frame p50 and the time of top graphics
chunks. Estimate FPS gains only after the measured reduction in frame time.
