# Ocarina Adreno 840 – visual-quality V2 A/B results, 16 Nov 2026

User-submitted real logs: `0400486024DEC000-20261116-125935.7z`,
`130842.7z`, `130934.7z`, `131032.7z`.
All four are build 75a821b7, same installed game, Qualcomm 891.14, 720p scene
overlay, `DM_VK_OOT_VEG_QUALITY=3` (A+B), `DM_VK_VEGETATION=1`.
**All four retain the unrelated dangerous diagnostic `DM_VK_OOT_SKIP_LAYER2_FS=1`.**
This must be OFF for proper image quality testing. No solo vegetation A/B
comparisons exist yet.

## Real 2×2 effect toggle comparison

| log | hard shadow PCF | low ground mist OFF | Frame p50 frames 901–1200 | GPU p50 frames 901–1200 | frame 1201 GPU sampled |
|---|---:|---:|---:|---:|---:|
| 130842 | 0 | 0 | 21.75ms | 21.42ms | 23.62ms |
| 130934 | 1 | 0 | 21.93ms | 21.43ms | 23.28ms |
| 131032 | 0 | 1 | 21.43ms | 21.03ms | 22.93ms |
| 125935 | 1 | 1 | 21.49ms | 21.06ms | 22.60ms |

GPU reduction of fog toggle versus baseline: 0.39ms median and 0.69ms
sampled frame (~0.9 FPS at 21ms GPU). Adds plausibility, but no repeated
controlled runs at fixed camera, identical driver clocks/temperature, so
NOT a proven sustained FPS gain. Both toggles together do not
demonstrate an advantage over fog only. Hard-shadow PCF alone:
21.43ms versus 21.42ms, no measured benefit.

The exact ground-mist shader `5ad65c0eefd09c7f` shows 0.285/0.339/
0.304ms in baseline sampled chunks, and is absent from both fog-OFF
runs. A matching `066f5daf12e43c71` mesh dispatch around 0.07–0.08ms
also vanishes where fog is OFF. GPU profile frame 1201 GFX blocks:
baseline 12.36ms, fog OFF 11.99ms; mesh compute baseline 3.32ms, fog
OFF 3.01ms. These frame samples are not guaranteed identical draw
composition; do not add profiler categories as independent GPU time.

The runtime shadow patch logs just one compare sampler switching
linear to nearest. It does not cut shadow geometry, atlas sizes or
shadow raster passes; its tiny/no FPS gain is expected.

## Foliage detail direction

All four runs omit pairs A and B together. The log confirms A/B
counters at 2048: A=1024, B=1024, so both paths really execute;
**this is not a controlled test of solo A vs solo B**. Earlier V1
logs 120500 and 120825, where those pairs were retained, sampled
the `4c7d6be5a7717c8d` mesh at ~0.065–0.072ms per frame, so the
preserved B pair alone is unlikely to yield a dramatic FPS gain.
A pair's cost remains unisolated and is not inferred as zero.

The most expensive measured foliage work in the full scene is NOT the
two retained pairs: `eb021183bf9b0092` (Foliage mesh
~0.64–0.68ms/one dispatch, paired with task
`99280b7b8aae78df`) and `fed302d791a4ba43`
(Foliage mesh ~0.50–0.60ms/one dispatch, a previously over-aggressively
deleted cosmetic pair). The game's visible foliage must remain,
so **future work should reduce emitted vegetation density/LOD on these
specific task/mesh variants, not drop the complete shader key**.
Keep their depth/colour variants coherent, preserve atomic/memory
side-effect checks and reject any unverified shader rewriting.
Do not enable experimental cuts by default.

## Recommendations for the next validation

1. Disable `Omitir shader B (teste)` (`DM_VK_OOT_SKIP_LAYER2_FS=0`) to
   avoid corrupted image and confounding performance.
2. Keep hard-shadow PCF OFF; no benchmark advantage.
3. If visual effect is acceptable, compare low-ground-mist OFF and ON
   again with unchanged camera and cooler/clock state.
4. Test vegetation FULL, A ONLY, B ONLY, A+B in identical scene, not
   screenshots from different camera positions.
5. Research a game-parameter patch reducing shadow atlas resolution
   through its real `ModelSceneConfigParam/Main` BYML in the user's
   own RomFS, with exact discovered keys and version/content checks.
   The source materials here do NOT provide this packed asset, so a
   safe shadow-map-resolution patch has not yet been implemented.

No signed APK changes are authorized by this diagnostic; this is
a research-only record of the user-provided captures.
