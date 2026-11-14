# The Legend of Zelda: Ocarina of Time (`0400486024DEC000`)

A Switch 2 game: update v131072 over the base v65536, SDK 22.2.8 built for the Switch 2 (`Ounce`). Nintendo EPD's engine (sead / agl / gsys, Phive, RSDB, ELink2 / SLink2, Havok 2025.2) on NVN2, modules `main`, `subsdk0` and `sdk`. **Provisional profile, reaches the title screen**: brought up on Android in Swap2-Native (2026-11-05; POCO F7 Ultra, Adreno 830). Lichii (an Eden-based Switch 2 emulator) calls it "the green-hat kid adventure" ([Lichii build 75](https://github.com/zortos293/Lichii/releases/tag/build-75), [its PR 87](https://github.com/zortos293/Lichii/pull/87)).

## What it needs

Current Android movie investigation (2026-11-12): the clean-install run in
`0400486024DEC000-20261112-122824` reaches frame 911 at 21.39 s and then logs
only audio until the user stops it. Early AV1 release signalling is active.
The host's asynchronous output receiver closes a separately reproduced
late-output deadlock; device validation and the precise stalled thread in this
run remain open. See [Platform output arriving after Submit returns](../../../docs/reference/movies.md#platform-output-arriving-after-submit-returns)
for the mechanism and production-code regression. Build 91 still froze with
the receiver active in logs `125440` and `125938`; the latter has RAM Saver
disabled. The next host corrects [completed sync handles after buffer reuse](../../../docs/reference/movies.md#completed-decoder-sync-handles-after-buffer-reuse)
and enables nonfatal stall-state capture. Build 92 still froze; its `132541`
dump shows `ModuleSystemWorker2` burning CPU while texture destruction is
in progress, the main thread waiting for module work, and AV1 with completed
buffers and no released output to fill. The CPU-written texture serial set
can exhaust all empty slots with tombstones despite zero live entries, then
loop forever under the texture lock. The new host removes that tombstone
table; see [CPU-written serial churn stalls texture destruction](../../../docs/reference/rendering.md#cpu-written-serial-churn-stalls-texture-destruction).
The deterministic production-helper regression hung before the fix and passes
205,056 texture lifetimes after it. The build 93 log `134035` passed the intro
and reached frame 22,118 at 536.12 s, then ended abruptly under memory pressure.
The next-start log `142527` records the most recent exit as SIGKILL, RSS
4,669 MiB; its 14:25 timestamp does not identify the earlier 13:49 session.
The user reports reopening passes the same point. Cold pipeline compilation
is a working hypothesis, not a confirmed Android kill reason.
Code review found that optimized GPL pipelines replaced linked handles without
ever destroying them (537 optimizations in the long run). The follow-up host
retires those handles after recording and GPU fences, applies the system RAM
reserve to optional compilation, and permits reclaiming CPU images pinned only
by finalized pool generations. See [Linked pipelines retained after optimization](../../../docs/reference/shaders.md#linked-pipelines-retained-after-optimization)
and [Finalized pool descriptors pin CPU images](../../../docs/reference/rendering.md#finalized-pool-descriptors-pin-cpu-images).
Device validation of these memory changes remains open.
No gameplay FPS gain is claimed.

| Setting | Where | Why |
|---|---|---|
| `mem_reserve 0x380000000`, `mem_alias 0x120000000`, `app_pool 0x240000000`, `sys_resource 0x3000000` | [`game.tsv`](game.tsv) | virtual address memory: the NPDM declares a system resource (24 MB in the base, 48 MB in update 131072), and the game takes both a 6.2 GB heap (`nninitStartup`) and an address region of the rest of the pool (`main+0x9c2130`) after the 1 GB node area (its `sdk` has no reviewed node-area implementation). 9 GB heap region + 4.5 GB alias region: boots past memory setup; peaks not measured (open). [A profile's system resource guessed from another game](../../../docs/reference/memory.md#a-profiles-system-resource-guessed-from-another-game) |
| `render_cond on` | `game.tsv` | Donkey Kong Bananza and Mario Kart World need it (agl's clears under render conditions); assumed here, not checked (open) |
| `pad_layout full` | `game.tsv` | |

## Files

- The dump is one NUP file (`The Legend of Zelda Ocarina of Time [0400486024DEC000][v131072].nup`, 25.6 GB; [android/NUP.md](../../../android/NUP.md)) with the base and update 131072, read in place. The update's RomFS is the whole tree.
- Builds: v131072 `main` e0f3ccfaf50065ae4ea01eb5aeb13b1a, `subsdk0` b0110087a7b339ef74588d3bd0b4dd5d, `sdk` 1643a838814f9c10c696f930ed681e7f (the base v65536: `main` 33fa6c2c23848282a77e8b88a0a93f48).
- RomFS marker `System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs`.
- Shaders: `Shader/*.Product.110.product.Nin_Ounce_NVN2.bfsha.zs` (Model, Foliage, TerrainGround, SceneMaterial), `Layout2Shader/MergeShader.Product.100.Nin_Ounce_NVN2.bfsha.zs`, and the effects' `Effect/*.Nin_Ounce_NVN2.vsetb.byml.zs`.

## Shaders

- Split from the NUP on the PC (2026-11-05, `shader_split.py` on `…nup:update/131072/romfs`, about 40 minutes over WSL's `/mnt/d`): 42,321 shaders in [`shader_map.tsv`](shader_map.tsv) (compute 4,101, mesh 9, pixel 22,356, task 3, vertex 15,852; from Effect 22,403, Shader 14,204, other 5,569, layout 145), 4,113 compute answers, 26,894 variation pairs. About twice Donkey Kong Bananza's 22,852: Prepare on the phone takes about twice as long.
- Resolved 2026-11-06 (translation and `spirv-val` on the PC; not yet drawn on the phone): mesh program `2582bd7ea6490d33` is a point mesh that writes the point size ([NVN2 point mesh programs and their point size](../../../docs/reference/shaders.md#nvn2-point-mesh-programs-and-their-point-size)). Its row in [`shader_facts.tsv`](shader_facts.tsv) was patched with the fixed `mesh_facts` (`mesh` [32, 32, 128, 132, 0, 1, 2, 3, -1, 4], `mesh_topology` 1); a new split writes the same row.
- **Open, worked around:** 93 of the 42,321 did not build on the phone (Swap2-Native's Prepare, 2026-11-05), so the job wrote no library (`DMSH_VK_REQUIRE_ALL`). [`vk_delta.tsv`](vk_delta.tsv) lists them as not built ("-"), as a full build's manifest would, so the library is written without them: what draws with them does not draw. The causes, to fix in the translator:
  - 74: `spirv-val` rejects the module, "Vector access is out of bounds, vector size is 2, but access index is 2" (e.g. `1dc31f7fad13d519`). Resolved 2026-11-06: TXQ of a layer count on slots the effect shaders only query ([A size query of a layer count on a texture typed 2D](../../../docs/reference/shaders.md#a-size-query-of-a-layer-count-on-a-texture-typed-2d)).
  - 12: Ampere instruction `0x243` (e.g. `00b0635ae2b9613b`, `000fc400000004ff000000272c277243` at 0x6ab0): F2IP.U8.F32, resolved 2026-11-06; 6: `0x3a9` (e.g. `13002657609092b4`): ATOMG.CAS, resolved 2026-11-06 ([Ampere shader code](../../../docs/reference/shaders.md#ampere-shader-code-switch-2)). Checked with the translator on the PC: `00b0635ae2b9613b`, `aaa785ced92a88ef`, `13002657609092b4`, `1dc31f7fad13d519`, `d9bb4bdb13d711fb` build and pass `spirv-val`.
  - 1: `0x481` was a false BAHS entry in `agl_common.sharcb` (`68bbe98b3bfd9876`, a compute control section paired with vertex code), resolved 2026-11-06: the split no longer takes it ([BAHS in agl sharcb](../../../docs/reference/shaders.md#bahs-in-agl-sharcb)).
  - 1: the mesh program `2582bd7ea6490d33` above (no mesh layout), resolved 2026-11-06: it is a point mesh, the kind Lichii found in this game (the garden hedges).
  - The full PC build of 2026-11-06 (`v-aa71bc111ed5`, 42,336 of 42,339 ok) failed only three. All three were resolved on 2026-11-06 and checked with the translator on the PC (they build and pass `spirv-val`): that mesh program; its task `5d3a096025e375a1` ([A task program reading back its own task memory](../../../docs/reference/shaders.md#a-task-program-reading-back-its-own-task-memory)); and agl's compute `d17eefaff4f0bc23` ([Register texel offsets on fetches and samples (Vulkan)](../../../docs/reference/shaders.md#register-texel-offsets-on-fetches-and-samples-vulkan)). Every 150th key of the map (283 keys, 474 shaders with their pairs) translates to the same modules as before the change.
  Once a build holds all of them, the manifest is that build's full one (vk_android_build.py writes it beside the library).

## Found on this game

- [Constant component reads rejected by virtual compute retiling](../../../docs/reference/shaders.md#constant-component-reads-rejected-by-virtual-compute-retiling): the actual `9e6b` capture uses six scalar input pointers; the existing optimization never activated for it.

- [Unchanged driver inputs rebuilt per draw](../../../docs/reference/rendering.md#unchanged-driver-inputs-rebuilt-per-draw): port Banana Native input revisions and vertex caches, with production C equivalence and invalidation tests.

- [Compression dictionaries in bounded static shader extraction](../../../docs/reference/shaders.md#compression-dictionaries-in-bounded-static-shader-extraction): build 101 selected the correct stages but bypassed dictionary initialization when opening their compressed source.

- [Launcher shader selection before the pack process starts](../../../docs/reference/shaders.md#launcher-shader-selection-before-the-pack-process-starts): build 100 selected 56 captures instead of the 508 static stages because the launcher tried to initialize a service-owned native engine.

- [Extended NVN2 stages absent from the shader preparation](../../../docs/reference/shaders.md#extended-nvn2-stages-absent-from-the-shader-preparation): build 98 executes compute-mesh batches but the foliage's original shaders are absent from the preserved full library. Open; an executor-only APK cannot supply them.
- [Pipelines compiled with the game's floating-point environment on the Vulkan replay](../../../docs/reference/rendering.md#pipelines-compiled-with-the-games-floating-point-environment-on-the-vulkan-replay): its gameplay scene was overexposed (white-yellow walls, Link a dark silhouette) on Qualcomm 891.11.
- [The spin-wait search's decode cache is per head](../../../docs/reference/rewriter.md#the-spin-wait-searchs-decode-cache-is-per-head): its main's rewrite ran the phone's packer out of memory (5.7 GB); now 668 MB.
- Its main's text is ZBIC-compressed (system 22.0.0+): the on-device packer carries the `zbic` package (android/ondevice/build.sh).
- [A profile's system resource guessed from another game](../../../docs/reference/memory.md#a-profiles-system-resource-guessed-from-another-game): the first boot crashed in `VammManager::AllocateAddressRegion` (a null manager) with the profile's `sys_resource 0x0`; the Android pack now takes it from the NPDM.
- [Virtual audio devices of the Switch 2 SDKs](../../../docs/reference/audio.md#virtual-audio-devices-of-the-switch-2-sdks): it lists the virtual input devices (the microphone, for the ocarina) at boot and aborted when `auddmg:u` was not served. With no input device it skips the capture.
- [Input streams of the Switch 2 SDKs](../../../docs/reference/audio.md#input-streams-of-the-switch-2-sdks): with no input device listed it still purged and started its two microphone streams that never opened, and crashed at the first note of the ocarina (`main+0x336ee7c`, reported on seedds/nxnative as issue #1525). Resolved 2026-11-06 (host builds, unit test; not yet run to the ocarina on the phone): the host lists a silent microphone and serves both streams (`MainAudioIn` and `TrueRawAudioIn`, mono PCM16 at 48 kHz, 4800 frames).
- [Event descriptors for gRPC's poll engine](../../../docs/reference/services.md#event-descriptors-for-grpcs-poll-engine): its "npln" gRPC client aborted at boot without `nn::socket::EventFd`.
- [Play reports sent with `prepo::PlayReport::Send`](../../../docs/reference/services.md#play-reports-sent-with-prepoplayreportsend): after the prologue movie it aborted (`Result 0xe15`, `[RED] sf: ... prepo:u`) sending a play report at `main+0x379164c`. Resolved 2026-11-07, checked on the phone the same night: past the movie with no abort, into gameplay. The stub is now gated by SDK (Switch 2, major 19 on): this game's SDK 22.2.8 `Send` returns its `AsyncContext` at x8, as the SDKs of Donkey Kong Bananza and Mario Kart World do, whose `main` modules do not import it (checked by disassembly, 2026-11-07; the gate compiled, not yet run on the phone).
- [Pointer authentication key A is per thread on Android](../../../docs/reference/rewriter.md#pointer-authentication-key-a-is-per-thread-on-android): the SDK's fibers (its gRPC dispatcher) signed with key A on one thread and checked on another.
- [AV1 movies through the platform decoder](../../../docs/reference/movies.md#av1-movies-through-the-platform-decoder): its movies are AV1.
- [Movie pictures fall behind their sound when the game draws slower than the movie](../../../docs/reference/movies.md#movie-pictures-fall-behind-their-sound-when-the-game-draws-slower-than-the-movie): its opening and title video at 8.3 fps (2026-11-08, Qualcomm 891.11) acquired one 60 fps picture per frame, so the prologue's 100 s took about 12 minutes. Resolved 2026-11-08 with the movie clock (Lichii's semantics), measured on the phone: with NDVE (8.4 fps) 51.6 of 60 pictures a second dropped and the movie's time ran 0.97-0.98 s a second, the prologue ending after about 100 s; with the plain movie player (60 fps, below) it drops nothing.
- [Ampere HMMA and warp shuffles of agl's upscaler on Adreno](../../../docs/reference/shaders.md#ampere-hmma-and-warp-shuffles-of-agls-upscaler-on-adreno): the opening movie's NDVE chain, whose HMMA shaders (`dmsh_hmma16816_f16`) keep the GPU busy 211 ms a frame on Qualcomm 891.11; their calls are lowered at their sites from `DMSH_VK_CHAIN` `ee04915141ee` on (the same results, so the blocks stay). Resolved 2026-11-06 (measured alone on the phone, not yet in the game): with the lowering the title still took about 187 ms a frame and gameplay 374 ms on 891.11, because the lowering kept every gather of a block and the drivers spilled them (its cause (3)). A block now keeps three: on 891.11 the title's chain of 10 HMMA programs takes 98 ms instead of 171 (NDVE at 2048 groups), and agl's NDSR programs 3.6-16 ms instead of 12-77 (48×22 groups); on Turnip V38 the chain takes 219 ms instead of 866, and NDSR 4.2-38 instead of 52-542. Outputs are bit for bit the same. From those numbers (an estimate), the title's GPU frame falls to about 113 ms on 891.11 (from 187) and gameplay to roughly 80-100 ms (from 374), if a frame's NDSR work scales like the dispatches measured. Current (2026-11-07, not yet run on the phone): LDSM's shuffles with their offsets taken out and repeats shared (its cause (4), `shuffle_cse`) halve the native shuffles of the 41 HMMA programs it changes (15,207 → 7,649; NDVE `9442573ee4ace011` 992 → 124), bit for bit the same output on an RTX 3060; the Adreno times are open, and the phone run also times the sharing bounded at 8 results (9,931 shuffles), since unbounded it keeps up to 20 results live across agl's NDSR blocks.
- [Dead-code removal dropped the inputs of a producer with several results](../../../docs/reference/shaders.md#dead-code-removal-dropped-the-inputs-of-a-producer-with-several-results): this explains the opening video's garbage picture (Qualcomm 891.11) and black picture (Turnip). NDVE's `4f41ccf24f163e0d` kept 1 of its 46 HMMAs: R17 of the HMMA at +0x15b0 is never read, and its 10 operands were variables that nothing stored. In library `ba9c4d5d0782` this affects both its base and `shuffle_lds` modules. The same happened to agl's NDSR networks `54c6b94ddf539d9f`, `aa1243f635baa8e8`, `927ceaf3cf1be240` and `fa3033d05c0a41d6`, and to three AglShader image loads. Resolved in the translator on 2026-11-06: all 46 HMMAs are kept and no variable is left unstored. Checked on the PC only; the phone is not checked yet.
- WaitForAddress type 3 (64-bit wait if equal), which Lichii had to add for this game (Eglantine #567), was already in the host (`hle_thread.c`).
- [Guest reads of the counter frequency](../../../docs/reference/frame-rate.md#guest-reads-of-the-counter-frequency): its dynamic FPS mod divides counter spans by `cntfrq_el0`, which answered the phone's 19.2 MHz instead of the Ounce counter's 31.25 MHz.
- [Float atomic adds dropped by the translator](../../../docs/reference/shaders.md#float-atomic-adds-dropped-by-the-translator): 34 shaders (12 compute, 22 pixel) sum floats with `RED.E.ADD.F32.FTZ.RN`, 416 instructions that emitted nothing; Lichii's sky ambient SH sums (wrong scene and fog colours, yellow rocks) are of this kind. Now compare-and-swap loops (resolved 2026-11-06 in translation and spirv-val; not yet seen on the phone).
- [Compare-and-swap loops retry with the value the CAS returned](../../../docs/reference/shaders.md#compare-and-swap-loops-retry-with-the-value-the-cas-returned): Lichii's device lost in the autosave (its PR #206).
- [A compare-and-swap at an address in no buffer returned 0](../../../docs/reference/shaders.md#a-compare-and-swap-at-an-address-in-no-buffer-returned-0): the 6 foliage compute shaders with ATOMG.CAS (14 instructions) are the ones it could hang; here all 14 resolve to a storage buffer.
- [NVN2 point mesh programs and their point size](../../../docs/reference/shaders.md#nvn2-point-mesh-programs-and-their-point-size): mesh program `2582bd7ea6490d33` draws points and writes their size (plane 0, before position; control +0x5f = 1).
- [A task program reading back its own task memory](../../../docs/reference/shaders.md#a-task-program-reading-back-its-own-task-memory): task `5d3a096025e375a1` loads the payload word it stored (0x923 mode 0xb800).
- [Register texel offsets on fetches and samples (Vulkan)](../../../docs/reference/shaders.md#register-texel-offsets-on-fetches-and-samples-vulkan): agl's compute `d17eefaff4f0bc23` fetches with offsets from a register.
- [A multisample fetch with an offset read an offset as its sample index](../../../docs/reference/shaders.md#a-multisample-fetch-with-an-offset-read-an-offset-as-its-sample-index): found in review of the register-offset change; none of its shaders has the form.
- TLD4 0xf63 (bindless, [Ampere shader code](../../../docs/reference/shaders.md#ampere-shader-code-switch-2)), which Lichii met on this game, is in none of this tree's splits (42,339 records); it is registered from Lichii's layout.
- [Render conditions on occlusion reports and reports in flight on the Vulkan replay](../../../docs/reference/rendering.md#render-conditions-on-occlusion-reports-and-reports-in-flight-on-the-vulkan-replay): with `render_cond on`, the Vulkan replay skipped the conditions over its occlusion report pairs (1 == 1) and read reports of earlier submissions still on the GPU from old memory; found from Lichii frizti-v3, not yet measured here (the `render conditions per frame` line).
- [Prewarm made the oldest records first on the Vulkan replay](../../../docs/reference/rendering.md#prewarm-made-the-oldest-records-first-on-the-vulkan-replay): with its 42,321 shaders the prewarm list can pass the 8,192 records a run makes, and the newest were never made ahead.
- [Present period fitted to whole refreshes of the panel on the Vulkan replay](../../../docs/reference/frame-rate.md#present-period-fitted-to-whole-refreshes-of-the-panel-on-the-vulkan-replay): Lichii's genlock for this game at 30 fps; not yet measured here.
- [A phi of a constant buffer pointer and a loaded pointer read 0 on the loaded path](../../../docs/reference/shaders.md#a-phi-of-a-constant-buffer-pointer-and-a-loaded-pointer-read-0-on-the-loaded-path): `FoliageShader.sharcb` compute `00b0635ae2b9613b` and `10a2c776a57f5071` (16 loads each), the shape of Lichii's foliage that lost its leaves near Link (upstream #410). Partial census; not yet checked on the phone.
- [Ampere shader code (Switch 2)](../../../docs/reference/shaders.md#ampere-shader-code-switch-2), NVN2 compute's `c[0]`. Checked 2026-11-07 by disassembly, resolved with no change: the 18 compute shaders that read a group count read x at `c[0]` + 4 and y at + 8, as the replay writes them. Those 18 include agl's 8×8 `agl_technique_proc` sizes, terrain `e124fe4b4064ac83`'s flattened group index and the SH sum `21d9f83e6027c565`. ocarina-recomp's x at + 0 does not match. All 4,125 have control +0xaa..+0xb0 at 0, so one push table at +0xa9.
- [Pool indices without NonUniform on the Vulkan replay](../../../docs/reference/shaders.md#pool-indices-without-nonuniform-on-the-vulkan-replay): from Lichii's clustered-lighting finding (upstream #354). The translator decorates the indices only when the Vulkan build sets the `nonuniform_index` job key, and that key is not set yet.
- [Indirect NVN2 mesh draws on the Vulkan replay](../../../docs/reference/rendering.md#indirect-nvn2-mesh-draws-on-the-vulkan-replay): `nvnCommandBufferDrawMeshTasksIndirect` was the stub, so by ocarina-recomp's account the culled foliage and hedges were not drawn. It is now recorded and drawn from a `{count, 1, 1}` record that the GPU writes (a count past the device's workgroup limit draws nothing, as a direct draw past it). Resolved 2026-11-06 in code; compile-checked only, not yet run on the phone. `first` is not applied (open). The multi-draw and 3D forms are still on the stub.
- [Samples-passed reports counted with Vulkan occlusion queries](../../../docs/reference/rendering.md#samples-passed-reports-counted-with-vulkan-occlusion-queries): every samples-passed report read 1 on the Vulkan replay, which by Lichii's account drew the fog over Link and made leaves and lights flicker; by ocarina-recomp's account the game makes hundreds of reports a frame. Now counted, with cumulative NVN semantics. Resolved 2026-11-07 in code; compile-checked only, not yet run on the phone (A/B: `DM_VK_OCCLUSION=0`).
- [Integer shader images over float textures on the Vulkan replay](../../../docs/reference/rendering.md#integer-shader-images-over-float-textures-on-the-vulkan-replay): agl's upscaler (`d17eefaff4f0bc23`) stores its 1536x864 RGBA8 output as `R32_UINT` words; the view was never learned and gameplay was black. Resolved 2026-11-07 (phone: the scene shows, overexposed; see Open). That run had the R11G11B10F output's pair (`122 98`) written by hand into `vk_view_formats.txt`: `id_view` tried the storage remake before learning, which a format without storage support refuses. Now learned first, and `VK_IMAGE_CREATE_EXTENDED_USAGE_BIT` only on the images that need it; the remake never runs inside a render pass, and a float storage binding of such an image is unbound with a red line instead of a view without storage use (compiled; open: a phone run with the file removed). Its NDVE final pass (`4f41ccf24f163e0d`) is why sRGB textures with the IMAGE flag get storage use (texture 1931, `RGBA8_SRGB`, stored through an RGBA8 UNORM view).
- [Captures whose textures shared another format's image on the Vulkan replay](../../../docs/reference/rendering.md#captures-whose-textures-shared-another-formats-image-on-the-vulkan-replay): the gameplay captures (Link's house) did not replay: agl's `E5B9G9R9` upscaler input shares the `R11G11B10F` scene target's image. Resolved 2026-11-07 (phone: both captures replay).
- [Write protections that failed left CPU-written textures stale on the Vulkan replay](../../../docs/reference/rendering.md#write-protections-that-failed-left-cpu-written-textures-stale-on-the-vulkan-replay): found while looking for its missing text (below); the dirty tracker ignored failed `mprotect` calls and never printed them. None failed on the phone (2026-11-07): not the text's cause. A review found that a failed restore after a failed protection marked possibly read-only pages writable; such pages are now kept protected (compiled; no protection has failed on the phone so far).
- [Deferred register writes under a guard (Ampere scoreboards)](../../../docs/reference/shaders.md#deferred-register-writes-under-a-guard-ampere-scoreboards): the title's missing menu text. The glyph vertex shader `b19e1bdd247555ec` gave every corner of a glyph the same y. Fixed in the translator (2026-11-07); checked on the phone through `DM_VK_SPV_OVERRIDE`, not yet with a rebuilt library.
- [agl's NDSR upscaler network replaced by FSR 1 EASU on the Vulkan replay](../../../docs/reference/rendering.md#agls-ndsr-upscaler-network-replaced-by-fsr-1-easu-on-the-vulkan-replay): its light upscaler network `fa3033d05c0a41d6` (7.2 ms of a 33 ms gameplay frame on Qualcomm 891.11) runs as FSR 1 EASU with `DM_VK_NDSR=fsr` and `DM_VK_NDSR_INPUT=sqrt`. Current (2026-11-07, POCO F7 Ultra, Qualcomm 891.11, Link's house): with `DM_VK_GPUPROF=15` the network's dispatch took 7.4-8.5 ms and the GPU frame 34-35 ms (28.6 fps); with the stand-in the GPU frame is 27-30 ms and gameplay 32-35 fps, the same picture (the overexposure is unchanged). The game uses another network for another ratio, `b106afba1a18faa9` (1275x717 -> 2048x1152 with the 720p palette); the match rule takes it too. Its push bank (`DM_VK_NDSR_LOG=1`) maps the full images (c24[5] = 1, 1, 0, 0), so `DM_VK_NDSR_MAP=full` is right.

- [A pixel shader with partial colour masks wrote the wrong depth](../../../docs/reference/shaders.md#a-pixel-shader-with-partial-colour-masks-wrote-the-wrong-depth): 46 of its 126 pixel shaders that write depth (masks 0x10f, 0x100, 0x3f, 0x30) read `gl_FragDepth` from the wrong register; from ocarina-recomp v0.2.7. Fixed in the translator (2026-11-08, unit test and the PC sample: exactly those 46 and the 9 mesh programs changed); not yet on the phone. A candidate for the missing door (Open).
- [A mesh program's position was not invariant](../../../docs/reference/shaders.md#a-mesh-programs-position-was-not-invariant): its 9 mesh programs (tree canopies and falling leaves, by ocarina-recomp's account) now decorate their position `Invariant`; only drivers with `VK_EXT_mesh_shader` run them (not 891.11).
- [Whether a vibration device is mounted, Switch 2 SDK form](../../../docs/reference/services.md#whether-a-vibration-device-is-mounted-switch-2-sdk-form): its `main` imports `hid::IsOunceVibrationDeviceMounted`, which ocarina-recomp v0.2.7 found stopping at the hid service on a PC; both forms are answered now (compile-checked; the phone's runs never called it).
- [The process's cores](../../../docs/reference/threads.md#the-processs-cores): its NPDM declares cores 0-5 (mask 0x3f), where the host answered `GetInfo(CoreMask)` with 7 for every game. A thread pool library in its `main` sizes its workers and per-core arrays by `64 - clz(mask)` (`main+0x21f96f0`, three cores under 0x7), and some of its sead threads ask for cores 3-5 (`main+0x3299838`). The pack now takes the NPDM's cores (profile `core_mask 0x3f`, `ideal_core 0`); `DM_CORE_MASK=0x7` gives the earlier answer for an A/B. Measured 2026-11-08 (Link's house, Qualcomm 891.11): neutral, 30.2-30.9 fps and GPU 32.0-32.4 ms with 0x3f against 30.8 fps and 32.0-32.1 ms with 0x7, since the GPU is the limit there; kept on (the NPDM's value, and no out-of-range per-core slots).

## Open

- **Current (2026-11-08, measured on the phone): the opening and title movies without NDVE, on by default.** A/B on the POCO F7 Ultra (Qualcomm 891.11, battery 24-25 C at each start, 200 s from launch through the title): with NDVE 8.3-8.5 fps, 119 ms a frame; with the mod 59.8-60.3 fps, 16.7 ms a frame, GPU 2.82-2.84 ms (19 draws, 0 dispatches, 3 passes; two runs, with and without the movie clock), the movie at 60 pictures a second and in time (prologue 5,945 pictures, about 100 s), SoC 41 C on the title against 55-57 C. The picture is clean and as sharp at the phone's size (`TBa_50.png` against `TAa_50.png` in the run folder); gameplay after it unchanged (Link's house 30.8 fps, GPU 32.0 ms, against 30.4-30.7 / 32.2-32.4 without it). So [`mod.tsv`](mods/plain-movie-player/mod.tsv) now says `android_default on`: the launcher installs it once per game at its start, and the switch below turns it off. Earlier text: on Qualcomm 891.11 the movies take about 117 ms of a 119 ms GPU frame (the baseline after `DMSH_CHAIN` `fdd0dcd96fd9` and `DMSH_VK_CHAIN` `d274c85fc9f9`, battery below 25 C: 8.3-8.4 fps from the movie through the title, nearly all of it in the 14 dispatches of the NDVE chain; render passes 0.3-0.7 ms). `main+0x3b5f500` builds the movie player. With the flag at `[[x0 + 0x460] + 0x10]` set it makes the NDVE player (`main+0x3b62cd0`, 0x2f0 bytes); otherwise the plain one (`main+0x3b619e0`, 0x1c0 bytes), which shows the decoded 1920x1080 AV1 picture as it is. The profile's mod [`mods/plain-movie-player`](mods/plain-movie-player/exefs/plain-movie-player.pchtxt) turns the `cbz w8` at `main+0x3b5f524` (`28010034`) into `b +0x24` (`09000014`), so the game always takes the plain player. It was checked by disassembly of build e0f3ccfa, and `exefs_patches.py` applied to the dump's `main` changes those 4 bytes and nothing else (`DM_PROFILE_MODS_NSO=0400486024DEC000:main=<NSO>` makes `dm/tools/tests/test_profile_mods.py` check it again). It works around a platform limit (Adreno has no tensor cores, so the network's HMMA chain is emulated). To turn it off or on: Game settings › Graphics › **Movies without the neural network (faster)**. That copies it into `Switch2/Mods/0400486024DEC000/plain-movie-player/`, and the next Play or Prepare rewrites `main` ([Mods (exefs patches)](../../../android/README.md#mods-exefs-patches)). Found by edennx-ocarina-ios (arcatafuriosa, MIT, which has it as a rewriter cut; the analysis, kept outside the repository); the bytes here were derived and checked again. Open: the NDVE picture against the plain one side by side at the same movie time (only seen at different times), and the default-on install on a launcher that never had the mod (the phone had it pushed by hand; `BuiltinModsJvmTest` covers the logic).
- **Resolved (2026-11-08, checked on the phone with the `d274c85fc9f9` library): the door of Link's house did not show** (2026-11-07, POCO F7 Ultra, 891.11, reported by the user). With that library the doorway is open with the lit outside drawn through it (camera turned about 180 degrees, 891.11). The change it came with: [A pixel shader with partial colour masks wrote the wrong depth](../../../docs/reference/shaders.md#a-pixel-shader-with-partial-colour-masks-wrote-the-wrong-depth), 46 depth-writing pixel shaders whose depth came from the wrong register, agl's depth pass among them (the same library also carries the mesh `Invariant` fix, whose mesh draws 891.11 skips, so it is the depth fix). The door's own draw was not logged, so the link is by the before and after only. Candidates that were not needed from the other projects' notes: per-component colour write masks (ocarina-recomp `0cf12aa`, Hookshot PR 138: a fragment shader that writes only some components of a target), mesh draws skipped on this driver (4 a frame), the raw memory table cut at 4,095 segments.
- **Current (2026-11-08, POCO F7 Ultra, 891.11): the game process died once in Link's house.** In one of nine house runs (`FINa`, defaults only, the camera facing the doorway: 1,490 draws, 8.8 fps, recording 87 ms, images 4,020 MiB and 6,051 MiB of Vulkan memory, free RAM 0.8 GB of 14.8, SoC 96 C) the `:game` process died with no crash line and no tombstone while lmkd reported thrashing and killed other apps (`Process com.swap2native.test:game ... has died: fg TOP`). The repeat with the same APK and settings (`FINb`) ran through at 30.9 fps. Open: memory pressure in gameplay (free RAM 0.5-0.8 GB in every house run since 2026-11-07); the image total, 3.5-4.0 GiB, is the place to look.
  - The thermal A/B of 2026-11-08 (below) makes it the first problem of this game on the phone: 3 of 9 launches were killed (exit info `reason=3 (LOW_MEMORY)`, `:game` PSS 7.4 GB) and 2 more paged for most of the house, after `am kill-all` had left 9.2-9.6 GB free. When free memory reaches about 0.5 GB the game's major page faults go from under 1,000 to 8,000-30,000 per 10 s, the kernel takes up to 411 % of the 800 % CPU (`top`), the frame rate falls to 1-15 fps and the cpu zones sit at 95-99 C. The same floor 0 gave 30.7 fps in one run and 13.8 in the other. The 98 C peaks and the 0.6-1.7 s frames of these runs come from this paging, not from a setting. Neither FSR 1 nor the 720p scene lowers it (one of the two FSR 1 + 720p runs at auto was killed, the other paged).
- **Current (2026-11-08, POCO F7 Ultra, 891.11): the GPU clock floor, FSR 1 and the 720p scene, against temperature.** Each configuration from the same cold state (cpu zones at or below 40 C, battery at or below 30 C, at least 10 minutes idle; a battery at or below 26 C was not always reachable on the charger), 1 minute of the title, then 6 minutes in Link's house with the camera still, sampled every 10 s. Runs with little or no paging:

  | Configuration | fps p50 / p10 | GPU ms | Max cpu / gpu zone C | End cpu C | Battery | Lowest CPU caps (MHz) |
  |---|---|---|---|---|---|---|
  | `DM_VK_GPU_FLOOR=100` (the default) | 28.5 / 27.6 | 34.5 | 98.0 / 92.6 | 76 | 30.0 → 37.0 | 1555 / 1401 |
  | `DM_VK_GPU_FLOOR_AUTO=1` | 30.6 / 8.8 (paged in its last minute) | 32.1 | 98.8 / 90.7 | 97 | +8.0 | 1555 / 1401 |
  | `DM_VK_GPU_FLOOR=0` (second run) | 30.7 / 30.4 | 32.1 | 91.9 / 83.4 | 78 | +5.6 | 1996 / 1958 |
  | Floor 100 + FSR 1 + 720p | 39.8 / 37.5 | 24.5 | 97.2 / 83.0 | 79 | +6.0 | 1996 / 1958 |
  | Auto + FSR 1 + 720p (killed at 4 min 40 s) | 39.4 / 37.0 | 24.7 | 96.9 / 92.3 | 83 | +6.7 | 1555 / 1689 |

  - The floor: in the house the auto floor spent 100 % of its frames at 100 (recording start to GPU end p90 40-110 ms against the 16.7 ms it aims at, the title's 60 fps period), so there it is the fixed floor; it differs only on the title, where it stayed at 0. Floor 0 did not fall to 20 fps in this window: the GPU is about 97 % busy at 30 fps, so the driver's governor keeps the clock up by itself. It was the coolest run (peak cpu zone about 6 C lower, battery 1.4-2.4 C less) at the same frame rate, but it is one clean run of an idle room. The default stays at 100: it is general host behaviour, and Donkey Kong Bananza's controller needs it ([A GPU clock floor that follows the present period](../../../docs/reference/frame-rate.md#a-gpu-clock-floor-that-follows-the-present-period-holds-a-dynamic-interval-at-its-slowest)). Open: floor 0 in a heavier scene of this game (Kokiri Forest, a fight) before any change.
  - FSR 1 and 720p: about 40 fps instead of 30, frame time p95 about 29 ms instead of 36, the longest frame 136 ms instead of 242-742 ms; the heat is that of native at floor 100, because the GPU time saved goes into more frames. The log confirms FSR 1 EASU (1275x717 to 2048x1152, sqrt input) and the overlay. FSR 1 alone gave most of it (37.8-38.4 fps, the Upscaler A/B below). So the profile's `ndsr_default fsr` makes FSR 1 the Upscaler's default in the launcher; the player can still choose the network. The 720p scene stays off by default: it adds about 1.5 fps, holds the scene at 1275x717 where the game would raise it, and needs an overlay made from the player's files.
  - Title, 1 minute: 60 fps and 2.8 ms of GPU in every configuration, cpu zones 51-63 C.
  - Frame stability: the host logs only frames over 16.7 ms, which at 30-40 fps is every frame, so frame time p50 / p95, interval p99 and on-screen drops are what tell the runs apart. Without paging the interval p99 is 31.6-40.8 ms; with paging 324-337 ms.
  - CPU by thread (floor 100, idle in the house at about 28.5 fps, % of one core over 10 s, `/proc/<pid>/task/*/stat`): `vk-enc` 41.9, `vk-replay` 31.9, the game's main thread 19.4, five `ModuleSy` workers about 80 together, six `BaseProc` workers about 66 together, audio threads about 9, `RenderThread` (the overlay) 0.5; about 3.3 cores in all. No thread spins and no save thread shows. `vk-enc` records about 650 draws and 97 render passes a frame; it is the largest host thread, not a busy-wait.
- **Current (2026-11-07): gameplay frame rate after the 22:00 APK.** Two runs at 15-22 fps with GPU frames of 70-100 ms, after 29-31 fps / 32 ms at 17:24. Both with the overlay's CPU caps lowered (thermal headroom 0.7-0.8, the phone used by another project just before) and an A/B with the 17:23 APK under the same conditions was worse still, so heat is the likely cause; to be measured again on a cold phone before blaming a change.
- Android UI: the title ID selects the themed Zelda touch profile ([integration and validation](../../../docs/SWAP2-NATIVE-TOUCH-PROFILES.md#zelda-ocarina-of-time)). It preserves the complete controller inputs. Sword/shield/item symbols are editable provisional artwork, not confirmed gameplay bindings; device validation remains open.

- **Current (2026-11-06, POCO F7 Ultra):** with Qualcomm 891.11 the opening video now shows (it was black), but covered in black and white blocks, and the title screen over its video runs at 4.7 fps: the GPU is busy 211 ms a frame in the NDVE chain, whose 10 HMMA shaders emulate the tensor instruction (`dmsh_hmma16816_f16`); with the current translator the chain has no `gmem_map` binding left (all storage buffers, checked on the PC). Presses of A on the title had not started a game by 02:20 (the title loops its videos). With Turnip Gen8 V32 the video stays black and the process runs out of memory maps minutes in ([Memory maps run out under Turnip during a compute-heavy video](../../../docs/reference/memory.md#memory-maps-run-out-under-turnip-during-a-compute-heavy-video-android)), so the phone's `env-0400486024DEC000.txt` sets 891.11 for this game. Earlier (2026-11-05): reaches the title screen at 60 fps with the video black. Gameplay not reached yet (open: no input given past the title).
- **Current: opening video (`Movie/Ndve/Ndve-Nvn2-vid_seq5.dat.zs`) compute post-processing chain.** Its AV1 pictures decode (`c2.qti.av1.decoder`), and after each frame the game runs an 11-shader NDVE v5 compute super-resolution / enhancement pipeline (`49dff010b9832251`, `ba079f68ae288dba`, `0a56002cdc7e1fce`, `e6be82d835fbe4d3`, `e2eebd7ba18fe35f`, `9442573ee4ace011`, `a8b4fb48fee0ccf8`, `d15370a382630d4e`, `7f7ff0f36b54d90f`, `5a7d69b067a7f011`, `4f41ccf24f163e0d`). Four issues were found and fixed:
  1. `shader_split.py` now parses `NDVE` v5 containers and mixed 8/16-byte descriptors in `NDSR` (22 shaders from NDVE, 3 from agl NDSR packs; 24 of 25 pass `spirv-val`, only agl's `d17eefaff4f0bc23` fails `OpImageGather` offset).
  2. The final pass (`4f41ccf24f163e0d`) binds texture 1931 (created as `0x38` `RGBA8_SRGB`, 2560×1440) as a storage image view with format `0x25` (`RGBA8_UNORM`); `vka_tex.c` now upgrades sRGB-base images with UNORM storage twins using `VK_IMAGE_CREATE_EXTENDED_USAGE_BIT`.
  3. In the 9 CNN passes (`ba079f68ae288dba`..`5a7d69b067a7f011`), `ULDC.64 UR, c[0][...] -> UIADD3 -> LDG/STG [Ra + UR]` nested the constant buffer base address inside multiple `Add` nodes, so `GlobalToStorage.cs` failed to resolve `s[0]` (`c[0][0x310]`, output feature map) and `s[4]` (`c[0][0x350]`, skip-connection input in `7f7ff0f36b54d90f`), leaving them unbound in `VKA_R_BUF` and falling back to `StoreMultiRaw`/`LoadMultiRaw` (overflowing the 1024-slot `gmem_log` with 133M atomic CAS operations per frame). `GlobalToStorage.cs` now walks nested `Add` trees (`FindBaseAddressCbInAddTree` + `EnqueueAddPhis`), resolving all 24 compute shaders to inline `StorageBuffer` bindings with zero `gmem_map` / `gmem_log`.
  4. The `32×1×1` single-warp HMMA shaders exchange matrix tiles across lanes via `STS.128` + `LDSM` without `BAR.SYNC`; `ALdsm` in `InstEmitAmpereTensor.cs` now emits `SubgroupBarrier()` around the shared memory read loop.
  Checked on the device 2026-11-06 (library v-6607c8d19abc built with these changes, 42,252 shaders): the 11 keys are in the library and their pipelines are built; the picture is corrupted and slow (above). Open: the HMMA / LDSM numerics of the CNN passes, and their speed (the HMMA helper's calls lowered at their sites from `DMSH_VK_CHAIN` `ee04915141ee` on, [Ampere HMMA and warp shuffles of agl's upscaler on Adreno](../../../docs/reference/shaders.md#ampere-hmma-and-warp-shuffles-of-agls-upscaler-on-adreno); measured alone on the phone 2026-11-06 with the gather bound, in "Found on this game"; not yet measured in the game).
- **Current (2026-11-07, POCO F7 Ultra): text missing from the UI. Cause found; fixed in the translator (applied on the PC, not yet checked with a rebuilt library).**
  - How the game draws text: it rasterizes each text line on the CPU (FreeType, thread `UpdateTextBoxTextureThread`) into small linear R8 textures (256x46, 640x46). Then it builds its text boxes on the GPU in a few frames around the title's frame 500. The frame drifts between runs; `DM_NVN_CAPTURE=passes>=24:1:<path>` catches it ([TESTING.md](../../../android/TESTING.md#frame-capture-and-replay-on-the-phone)).
  - The build has three steps: glyph quads (`b19e1bdd247555ec` / `9b310b3349825e9a`, one instance per glyph, its 224-byte record at `BaseInstance * 224`) into small RGBA8 targets (198x40, 242x40, 592x49), then two passes into R8 targets, then onto the screen.
  - Ruled out: the upload of the lines (no `mprotect` failed, each line held its glyphs at its first sample, and the replay's line images hold them), and the driver (Turnip draws nothing either).
  - Cause: the glyph quads had no area. The translated vertex shader gave every corner the same y, because of [deferred register writes under a guard](../../../docs/reference/shaders.md#deferred-register-writes-under-a-guard-ampere-scoreboards): `@!P0 ALD R85, a[0x84]` and `@P0 FFMA R85` end a block.
  - Checked on the phone with the modules of a translator built with the change (`DM_VK_SPV_OVERRIDE`): the title shows "Continue", "New Game" and "Options / ZELDA NOTES Setting".
  - Applied 2026-11-07 in `dm/gfx/tools/dmsh_xlate_bin` (its `Ryujinx.Graphics.Shader.dll`, lock fingerprint `50bcd1badef63f58`). On the PC, of this game's 77 text and UI modules only the glyph shaders change, the same modules as on the phone. In the regression sample (every 100th key with the NDVE / NDSR keys), 441 of 1,168 modules change (285 keys), all valid.
  - Open: `dmsh_chain.py --header`, the library rebuild and Prepare; then the title and the in-game text need checking with the rebuilt library.
- Resolved 2026-11-07 (checked on the phone): gameplay was blocked after the prologue movie by the abort in `prepo::PlayReport::Send` ([Play reports sent with `prepo::PlayReport::Send`](../../../docs/reference/services.md#play-reports-sent-with-prepoplayreportsend)). The prologue movie takes ~10,500 frames at 8 fps (about 21 minutes); Plus does not skip it. A save is made after it: the title's A, then A on the slot and A on its first choice load Link's house in about 900 frames.
- **Current (2026-11-07, PC only; to run on the phone): the NDSR network off, FSR 1 in its place, and the scene at 1280x720.** Phone A/B 2026-11-08 (Link's house, 891.11, the NPDM's cores, no profiler): `DM_VK_NDSR=fsr DM_VK_NDSR_INPUT=sqrt` at the default 1536x864 scene 37.8-38.4 fps, GPU 25.4-25.9 ms (two runs, the second with Occlusion Off), against 30.2-30.9 fps and 32.0-32.4 ms with the network; the picture at the phone's size looks the same (`DAa_h1.png` against `HCa`/`H0a_h1.png`). Not made the default here: it replaces the game's upscaler in a host path every NVN2 game with agl's NDSR takes (Mario Kart World, Donkey Kong Bananza), so it needs their check and `regress.py` first; it stays the switch, and the best gameplay lead of this A/B.
  - Launcher settings (2026-11-08, compile-checked only; to run on the phone): both levers are per-game choices in the Android launcher's Game settings › Graphics. **Upscaler**: the network or FSR 1 (`DM_VK_NDSR=fsr`; FSR 1 by default since 2026-11-08, the profile's `ndsr_default fsr`; the profile's `ndsr_input sqrt` gives `DM_VK_NDSR_INPUT=sqrt` at every start). **Scene resolution**: Game default or 720p. Choosing 720p runs `gsys_dynres.py --scale 0.6135 --expect <the ten originals>` (the profile's `scene_scale_palette`) on the player's own RomFS in the packer's process on the phone, into `<app files>/overlay/0400486024DEC000/scene_720p/`, and the host gets it as `DM_ROMFS_OVERLAY` while its stamp names this pack's version ([android/README.md](../../../android/README.md), Scene resolution). Open: a phone run of both settings (the 720p overlay made on the phone, the `[nxlaunch] env` lines, the `NDSR network ... (1275x717 -> 2048x1152)` line), and the frame rate with both on against the 35.6-38.5 fps measured with the hand-made overlay.
  - Network: `DM_VK_NDSR=fsr` and `DM_VK_NDSR_INPUT=sqrt` (the network's input holds sqrt(colour), packed as RGB9E5 by `a335c1db6270c355`) replace `fa3033d05c0a41d6` with FSR 1 EASU in its slot ([the entry](../../../docs/reference/rendering.md#agls-ndsr-upscaler-network-replaced-by-fsr-1-easu-on-the-vulkan-replay)). The network's output (texture serial 4302, 2048x1152, NVN `0x3f` = `B10G11R11_UFLOAT`, VkFormat 122) has no storage support on Qualcomm 891.11, so `vka_tex.c` `view_of` leaves a float storage binding of it unbound (`[RED] ... no storage support: unbound`): the network's own stores go nowhere there, and the stand-in's would too. The stand-in therefore stores packed `B10G11R11` words through an `R32_UINT` view of that image (its packed variant; the log line ends `output VkFormat 122 without storage support: packed words through an R32_UINT view`). Prerequisite, open (the other workflow's `vka_tex.c`): `a335c1db6270c355`'s store of the network's input. Its binding 3 is a float storage image (shape `0x1`, format Unknown) that the shader writes with each packed RGB9E5 word as raw bits (`vec4(bitcast<float>(word), 0, 0, 0)`, its disassembly), bound to textures 294 / 296: an `E5B9G9R9` texture (NVN `0x40`, 1536x864, image usage `0x17`, no storage) registered with an `R32_UINT` view (NVN `0x0b`) (`[RED] vk: shader a335c1db6270c355 binding 3: texture ID 294 has no view of shape 0x1 (storage)`, 2026-11-07 run). `img_retype_of` does not retype it: `vka_tex_id_int_class` answers the texture's class, a float one, so adding storage use to the image alone would not bind it. What it needs: the integer class of the registered view when that view is an integer format of the texture's texel size over a float texture, so the binding becomes a uint image (the `retyped` line for binding 3) and `id_view` gives it an `R32_UINT` view of the `E5B9G9R9` image (the pair VkFormat 123 / 98 learned, the image remade with storage use through it). Until then the network and the stand-in alike read stale scene bits as RGB9E5 (not the overexposure, whose cause was the compile environment: below).
  - Scene size, from the game's own dynamic resolution palette. `Pack/Bootup.Nin_Ounce_NVN2.pack.zs` (zstd with `Pack/ZsDic.pack.zs`'s `pack.zsdic`, dictionary ID 4; 675,656 bytes decompressed) holds `System/GameGraphics/ModelSceneExtensionParam/Default.game__gfx__ModelSceneExtensionParam.bgyml` at pack+0x6a00. Its `DynamicResolutionParam` has two palettes (`Console` `#2ebeca77`: 10 levels, LoadThreshold 95; `Handheld` `#90e0a495`: the first 8, LoadThreshold 108) that share their level nodes: ResolutionReduceScale 0.75, 0.71112, 0.66667, 0.62223, 0.58334, 0.53334, 0.5, 0.4445, 0.37223, 0.33334 at pack+0x7640 + 0x14 i. The window is 2560x1440, the upscaler's output (`WindowCrop`) 2048x1152, and the scene 1536x864 = 2048x1152 x 0.75: level 0, where it stays (no `gpu_timestamps` key). `dm/tools/gsys_dynres.py --scale 0.625` writes 0.625 into all ten, checked against those originals, as an overlay pack at `<NSP folder>/0400486024DEC000-work/romfs_overlay_720p/Pack/Bootup.Nin_Ounce_NVN2.pack.zs` (110,355 bytes, sha256 `7dc6cd1c7afe61cb...`; the same decompressed size, 29 bytes differ). With `DM_ROMFS_OVERLAY` set to that folder the scene is not linear in the scale: 0.625 gave 1304x734 and 0.6135 gives 1275x717 (seen on the phone, 2026-11-07; the overlay now in the work folder is the 0.6135 one). With that scene, the NDSR stand-in and `DM_VK_FSR=1`, gameplay runs at 35.6-38.5 fps on a cool phone (28.6 with the network at 1536x864). Learned view pairs are keyed by size, so the first run at a new scene size shows the 123/37/122 -> 98 `[RED]` lines once.
  - The dynamic resolution controller (found 2026-11-08 by disassembly of `main` e0f3ccfa; not yet run with `segment` on the phone). `main+0x5a8f0`, once a frame on the singleton at `main+0x4e81dd0`, reads two timestamp counter reports, converts each with `nvnDeviceGetTimestampInNanoseconds`, and keeps (end - begin) ns x 0.001 = µs and a load of µs x 100 / 16666.67, the percent of a 60 fps frame; it averages the last 3 and 5 samples, and `main+0x805aa0` picks the level from that load against `LoadThreshold`. So 95 (Console, this 2560x1440 window) is 15.8 ms of GPU between the markers and 108 (Handheld) 18.0 ms. With `gpu_timestamps submission` (the default) both reports read one time, the load is 0, and level 0 stays. With `segment` our gameplay GPU (25 to 32 ms, a load of 150 to 195) is above either threshold at every level the phone can reach, so the game is expected to fall to its last level (0.33334), as on edennx's Mac (1536x864 to about 763x429). The A/B (instructions in the work folder, `PHONE_AB_dynres_occlusion.txt`): `DM_NVN_GPU_TS=segment` alone, then with `gsys_dynres.py --floor 0.5` (`romfs_overlay_dynfloor`: the last three levels raised to 0.5; sha256 `818f0657b64de0e2…`) and with `--floor 0.5 --threshold 190` (`romfs_overlay_dynfloor_t190`: 31.7 ms, aiming at 30 fps; `04adb32e1456fa0f…`), with `DM_VK_NDSR=fsr` so the `NDSR network … (WxH -> …)` lines trace each scene size. Phone A/B 2026-11-08 (all with the FSR stand-in, after one `segment` run each; numbers are the two stats 45 s and 75 s into the house): submission 1536x864 only, 37.8 / 38.3 fps, GPU 25.6 / 25.4 ms; `segment` fell as predicted (1536x864, 763x429, 683x384) to 30.5 / 42.6 fps, GPU 24.1 / 21.4 ms, the picture visibly softer, the phone at 96 C with the CPU capped; `segment` + `dynfloor` sat at 1024x576 (via 1457x820), 43.3 fps / GPU 22.6 ms, then 13.6 fps hot; `segment` + `dynfloor_t190` wandered over seven sizes from 1536x864 to 1024x576, 36.1 / 27.6 fps, GPU 26.8 / 28.6 ms. A fifth of the pixels saves only 4 ms of 25.5: the GPU time here is mostly not resolution-bound (98 dispatches, 97 passes, about 460 full barriers a frame). Decision: `gpu_timestamps` stays `submission` (the game keeps level 0) and the floor overlays are not used; `segment` and the overlays remain the A/B switches. Open: how the two markers fall on the replay's submissions (`DM_VK_SYNCLOG`, not run): across submissions the segment times carry the completion thread's latency, past 128 timestamp reports in one submission they fall back to the completion time, and a report inside an open render pass is stamped by a tiler wherever its driver puts it.
  - Present: `DM_VK_FSR=1` scales the 2048x1152 crop to the screen with EASU and RCAS. Fallbacks, none written yet: `DM_VK_NDSR_MAP=push` if the scene is drawn into part of a full-size target; a render scale cut at the dynamic resolution function `main+0x805aa0` (one caller, `main+0x31d3ee0`; Lichii's "Max Resolution" branches past it at `main+0x805bd0`); `DM_OPMODE=0` with the palette at 0.8333; a window patch at `main+0x31f39f4` / `+0x31f39f8` (2560x1440 to 1600x900).
- **Current (2026-11-07, POCO F7 Ultra, Qualcomm 891.11): gameplay (Link's house).** 29-31 fps, GPU 32-33 ms a frame, 650 draws (48 skipped), 98-126 dispatches, 97 render passes. The overexposed picture (walls and floor near white-yellow, Link a dark silhouette) is resolved (below). In its log: `nvnCommandBufferShadingRateImagePalette` / `BindShadingRateImage` unimplemented (`[RED]` every frame), 4 mesh draws skipped (the device has no `VK_EXT_mesh_shader`), `colour target 0 (format 0x49) cannot be a Vulkan colour attachment`, and agl's light upscaler's float storage of an `E5B9G9R9` target (no storage support; it was unbound in the first run and still is). GPU profile (`DM_VK_GPUPROF=15`, 11 frames): agl's NDSR light upscaler `fa3033d05c0a41d6` (32x36 groups of 128) 7.2 ms a frame (22 %), `agl_ndsr_vr` `f8965bffbdf51d78` 0.4 ms, `a335c1db6270c355` and `d17eefaff4f0bc23` 0.1 ms each: NDSR about 7.8 ms (24 %); `AglShader` `9e6b00b050e30801` (8x9x12 groups of 8x4x4) 4.3 ms; the main 1536x864 pass 12-13 ms; passes 12-13 ms and dispatches about 19 ms a frame in all. Before the view fix, in the black scene after the movie: 47 ms GPU, NDSR 7.3 ms (16 %).
  - Overexposure, resolved 2026-11-07 (checked on the phone): the replay's threads and Qualcomm's shader compiler ran with the game's FPCR (`0x1000000`, flush-to-zero, inherited from the game thread that started the replay worker), and the pipelines compiled that way made the main pass's materials write a scene far too bright ([Pipelines compiled with the game's floating-point environment on the Vulkan replay](../../../docs/reference/rendering.md#pipelines-compiled-with-the-games-floating-point-environment-on-the-vulkan-replay)). With the host's FPCR Link's house is lit correctly on the phone (2026-11-07, Qualcomm 891.11) without `tex_flush_upload` / `tex_dirty_upload` (both tried: not needed, and the profile does not set them), at 23.8 fps on a hot phone (45 C); the frame rate on a cool phone is still to measure. `nxreplay` was right all along because it is a process of its own: its threads start with FPCR 0, so the driver compiled its pipelines without flush-to-zero. How it was found: `DM_VK_TEXSTAT_FS` with `DM_VK_TEXSTAT_AT=1` read live and in `nxreplay` of the same scene: the first colour draw (`3687985571c47db6`, a full-screen pass) wrote the same values in both (median 2^4 to 2^5), the main materials' draws after it did not (the scene at the bloom pass `e894c441691ca151`: median 2^6 to 2^7 live, 2^-6 to 2^-5 in the replay), with the same textures and the same uniform buffer bytes (equal hashes); a live run with the host's FPCR and no pipeline cache was right, the same build with the old cache file (pipelines compiled under flush-to-zero) was still white, and `DM_VK_GUEST_FPCR=1` with `DM_VK_PCACHE=0` brought it back (the switch now keeps no cache file by itself). The end-of-frame readings of the scene target (5 % NaN) were agl's RGB9E5 network input that `a335c1db6270c355` writes over it after the tone map, not the scene. Earlier measurements: the scene is already too bright before the tone map. With the tone map `9e09b406de439a34` overridden to write log2 of its scene input (`DM_VK_SPV_OVERRIDE`), the live median is 2^7.25 / 2^6.6 / 2^5.0 (R / G / B) against 2^0.4 / 2^-0.1 / 2^-1.1 in a replay of the same frame: about 90 times. Replaying a capture of the frame from its last submission (`passes>=60`, the live state after the compute prologue) gives the dark picture too, so the live run and the replay render different results from the same captured state. In the live state the probe cubes `4128` / `4313` (128x128x6 `R11G11B10F`) hold a mean of about 209 (max 4416) and the probe face target `4312` the same, where the replay renders that face at 0.045; the screen-space shadow mask (1536x864 RGBA8, `MIN`-blended by `741cf40fbb5702f5` / `9aa7f545bb5abcae`) is 1.0 everywhere live and mostly shadowed in the replay, but forcing it to 0.25 in both leaves a gap of about 5 stops. Not the cause: the fog / composite pass `888c1068ac8f7043` (its scene input passed through: the live picture is unchanged), any compute dispatch (`DM_VK_DISPATCH_SKIP` ranges), `DM_VK_GPL=0`, `DM_VK_PREWARM=0`, an empty pipeline cache, `DM_VK_ENC=0`, `DM_VK_TEX_MEMO=0`, `DM_VK_DRV_MEMO=0` with the push, dynamic state, barrier and pass switches, `DM_VK_ZSHARE=0` with `DM_VK_UBWC=0`, and zero / one-filled lightmap, BC4 and tile textures in the replay. Render conditions decide the same live and in the replay. `DM_VK_WORKER=0` crashes at start (open); the inline replay now records with the host's FPCR too (not yet run).
  - Leads from Hookshot (NotRexed/Hookshot, the same build on Windows; the analysis, kept outside the repository): guest data the CPU rewrites after the submit (it replays submit-time copies only), cross-queue `nvnCommandBufferWaitEvent` (2 of 3 unmet in submit order, lit surfaces wrong), same-stream report → condition pairs (every condition true turns its picture white), and loads through loaded pointers that read 0 (its washed-out Kokiri). Checked against the overexposure (2026-11-07): the game waiting for the GPU at each submit (`DM_VK_SUBMIT_WAIT=2`) and the raw memory table shifted (`DM_VK_GMEM_SKIP_LOW=500`, a diagnostic since removed) changed nothing, and the render conditions decide the same live and in the replay (`DM_VK_RC_LOG`); its cause was the compile environment (above). The leads stay open for their own symptoms.
  - Leads from edennx-ocarina-ios (arcatafuriosa, nxnative patches running this build on an iPhone Air with Metal, MIT; the analysis, kept outside the repository, with HarkinianPad, useful for touch ideas only): `tex_flush_upload` / `tex_dirty_upload` (checked on the phone 2026-11-07: not needed, Link's house is lit correctly without them since the FPCR fix, and the profile does not set them), a raw memory table of 8,191 entries (4,095 lost foliage), zero-initialized shader variables, an NDVE cut at `main+0x3b5f524` and `gpu_timestamps segment`. Open: the other leads, not checked here yet.
  - Leads from Lichii after build 88 (builds 93 to 117 and `nx2` to `bf4c42e`; the analysis, kept outside the repository): the game's dynamic resolution from GPU time between its markers (`gpu_timestamps segment`), late movie frames dropped by a movie clock (written and measured on the phone 2026-11-08, on by default: [the entry](../../../docs/reference/movies.md#movie-pictures-fall-behind-their-sound-when-the-game-draws-slower-than-the-movie)), 33 to 37 storage buffers in the foliage culling computes against the translator's 32, HMMA.F16 rounded after each K=8 group, and mesh programs drawn through compute. Open: none checked here yet.
  - Leads from Fritchii v4 and v4.1 (Frizti's fork, renamed from Lichii, `72e5ad6` to `f6d42b8`; the analysis, kept outside the repository): the community "Occlusion Off" patch for this build (six words of main, no z-prepass and no samples-passed queries; an opt-in A/B only), its water flicker from a per-pixel texture handle (our bindless path covers it; it needs `nonuniform_index`), the storage buffer table budget, one-level table pointers bound at record time, and the attachment-less framebuffer clamp. The "Occlusion Off" mod is built for the A/B (2026-11-08; its bytes are not in this repository): an IPS32 (the offsets pass 16 MB, past IPS's 24 bits) in `<work folder>/mods_test/occlusion_off/0400486024DEC000/Occlusion-Off/exefs/E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348.ips`, the Mods tab's layout; all six original words checked by disassembly (`ldrb w8, [x0]` after the bool getters `main+0xf5acc0` and `+0xf5bf70`, stored at or compared with `[x22+0x18]`), and `exefs_patches.py` changes those 24 bytes only. Its A/B on the phone (2026-11-08, Link's house, 891.11, with the FSR stand-in): occlusion queries fell from about 1,100 to 48 a frame and `SetRenderEnable` from 518 to 24, but the frame did not change: 37.9-38.4 fps, GPU 25.8-25.9 ms, against 37.8-38.3 fps, 25.4-25.6 ms without it; the picture looked right (`OOa_cam2.png`). Decision: not used (a game behaviour change with no gain); its folder on the phone is `-Occlusion-Off`, off. Open: the other Fritchii leads.
  - Leads from Echora (Mars7x/echora, an AOT recompilation of this build to Rust with its own OS and NVN on Vulkan, title and opening movie only, GPL; the analysis, kept outside the repository): the Switch 2's six application cores (mask `0x3f` from the NPDM, where the host answered `GetInfo(CoreMask)` with 7; written 2026-11-08: [The process's cores](../../../docs/reference/threads.md#the-processs-cores), measured neutral on the phone and kept), an opt-in loop iteration cap in the SPIR-V as a hang diagnostic, and a movie rate in decoded pictures per second (written 2026-11-08 with the movie clock: a `[codec] … movie rate` line every 5 s, `DM_MOVIE_RATE`). Open: the other two not checked here yet.
  - Leads from NX2navi (tangerineturtle1/NX2navi, a static recompilation of this build to C for Windows with NVN2 on Vulkan; additions all rights reserved, so semantics only; the analysis, kept outside the repository): a fixed scene scale that sticks (`main+0x80641c` returns state 0, enabled after 120 presents), the output size in two places (`main+0x1202ee0` as well as `main+0x31f39f4`), render conditions on a timestamp reported in the same frame, the translator's `GlobalToStorage` losing the rest of a block after `DeleteNode` when storage slots run out, HMMA.F16 measured as one rounding after all K, and tensor programs found by opcode. Open: none checked here yet.
- Resolved: AV1 movies ([AV1 movies through the platform decoder](../../../docs/reference/movies.md#av1-movies-through-the-platform-decoder)): the movie player aborted at `subsdk0+0xf9bc` when the host had no AV1 decoder.
- Resolved: the PAC check in the SDK's fiber switch (`CRASH sig=4 pc=sdk+0x16d40c`, `autiasp` in `DispatchFiberContext` on `nn.npln.GrpcDispatcher`, with Qualcomm 891.11 and Turnip Gen8 V32 alike): Android's per-thread APIA key ([Pointer authentication key A is per thread on Android](../../../docs/reference/rewriter.md#pointer-authentication-key-a-is-per-thread-on-android)). Checked on the phone with the sdk rewritten on the PC; the on-device packer takes the fix with the next stage build.
- Resolved 2026-11-06 (not yet run on the phone): `nvnWindowBuilderSetAcquireTimeout`, `nvnWindowBuilderGetAcquireTimeout`, `nvnWindowGetAcquireTimeout`, `nvnWindowSetAcquireTimeout` (NVN2 API 231.40) are kept and read back (the host's acquire never times out), and `nvnCommandBufferSetComputeWorkloadPriority` is a hint the replay has nothing to apply to (`hle_nvn.c`).
- Open, from Lichii (frizti-v2; the research, kept outside the repository): the replay always reports SAMPLES_PASSED = 1 (`vka_exec.c`); this game's conditional rendering is driven by occlusion results, and Lichii's stale "visible" record drew the fog over Link and made leaves and lights flicker. Real occlusion queries (counted from the guest's reset, paused rather than reset between submissions) are the fix. Meanwhile (2026-11-06, not yet run) a render condition on an occlusion report draws instead of comparing the constant ([Render conditions on occlusion reports and reports in flight on the Vulkan replay](../../../docs/reference/rendering.md#render-conditions-on-occlusion-reports-and-reports-in-flight-on-the-vulkan-replay)). Resolved in code 2026-11-07, not yet run: the reports are counted ([Samples-passed reports counted with Vulkan occlusion queries](../../../docs/reference/rendering.md#samples-passed-reports-counted-with-vulkan-occlusion-queries)); to check on the phone: the fog over Link and the flicker, against `DM_VK_OCCLUSION=0`, and the `occlusion queries per frame` and `render conditions per frame` lines.
- The microphone: the host's input device is silent ([Input streams of the Switch 2 SDKs](../../../docs/reference/audio.md#input-streams-of-the-switch-2-sdks)). The phone's microphone would feed its streams' reads from Android's input (AAudio, the RECORD_AUDIO permission). What the game does with the capture (its update at `main+0x336d510` reads at most 256 frames at a time and processes them) is not known: the songs may need a played note or only the buttons. To check on the phone: playing a song at a door, with the `audio input stream` lines in the log, and `DM_AUDIO_IN=0` (no device, as before) as the comparison.
- Shaders: the 93 above (all resolved; the mesh program and its task not yet drawn on the phone). Lichii's PR 87 lists the Ampere forms it had to lower for this game (2,759 of 2,768 programs): `.EX` integer compares, `RED` / `REDUX` (signed too), global atomic UMax32, `UIMAD`, negated `F2I` (`F2I.U32.CEIL.NTZ R, -|R|`), packed U8 conversion, 64-bit `SHF` and shifts, `UBREV` / `UFLO` / `UPOPC` on UR16+, high-register forms of `SEL` / `MOV` / `ISBERD`, guarded `@UPn USEL` / `UISETP`, `SEL` with a uniform source, `CALL.REL.NOINC` helpers (a capture that took the call for a jump ran past `RET.REL.NODEC`), and `SHF.R.U64` immediates. Three `TLD4` gather forms stayed rejected there. A place to look for our 0x243 / 0x3a9 / 0x481 and the out-of-bounds vector accesses.
- Lichii reports outdoor volumetric fog 3-4 times too bright after those lowerings (its open issue), and 12-22 fps on a Ryzen 5900X with an RTX 3080.
- Window size (Donkey Kong Bananza's `window_fn` has no counterpart here yet), `render_cond` (assumed).
- **Dynamic FPS mod** (a third-party IPS for `main` e0f3ccfa…, shared in the yuzu / Eden layout `Dynamic-fps/exefs/E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348.ips`; its bytes are not in this repository): supported through the mods folder ([Mods (exefs patches)](../../../android/README.md#mods-exefs-patches)). It hooks `main+0x6e6cc4` (`fdiv s8, s1, s0`, the frame's delta = 60 / the target fps) with a `bl` to a 120-byte cave at `main+0x3c46200`, in text's page tail (text ends at 0x3c461d0; the patched module's text grows to 0x3c46278, so the rewriter sees the cave), which times the frame with `mrs cntpct_el0` and `cntfrq_el0`, keeps two words at `main+0x4e9fe00` (bss), clamps the measured time to 1/20 s, smooths it by 1/8 and takes it when it exceeds 1.03 times the game's delta. Checked on the PC (2026-11-06): the build ID matches, the hooked word is that `fdiv`, the cave was zeros, and `patch_nso.py --target android` of the patched `main` turns the cave's `cntpct` read into a gate (the only `cntpct` site of `main`). The cave divides by `cntfrq_el0`, which the phone answers with 19.2 MHz while this Ounce SDK's guest counter runs at 31.25 MHz: read directly, the mod took every frame for 1.63 times as long as it was (the game would run 1.5 to 1.63 times too fast). Resolved on the PC (2026-11-06) by [a gate for `cntfrq_el0` reads](../../../docs/reference/frame-rate.md#guest-reads-of-the-counter-frequency): the patched `main`'s rewrite has one `cntfrq` gate, at the cave's read. Current: not yet run on the phone (it needs an APK with the new host and tools, then Prepare again).

### Banana Native residency and vegetation port (2026-11-12)

Current: the 16:13 restart log explicitly records the preceding run killed for low memory. Ported [GPU-demand texture residency](../../../docs/reference/rendering.md#gpu-demand-texture-residency-and-compute-vegetation-on-android) and [compute vegetation](../../../docs/reference/rendering.md#vegetation-through-compute-mesh-emulation) from Banana Native android d652abeb534496724e798ff96474752903d7953a. Full vegetation defaults on and is wired from per-game preferences through DM_VK_VEGETATION to the draw selector. Off preserves shaders with guest writes. The first working shader library plus approved replacements remains unchanged; the runtime derives compute forms from available task/mesh modules. The build 98 audit below establishes that missing original stages also require a bounded static supplement; runtime conversion alone is insufficient. No full shader translation is required. Driver pipelines for transformed modules compile on first use.

Validation: production CPU converter and feedback rewriting regressions under ASan/UBSan, real selector tests for on/off and write protection. CI additionally validates resulting SPIR-V for Vulkan 1.3. Phone RAM, new-game transition stability and visible vegetation are still pending; do not call these device-confirmed fixes.

### Compute-mesh replay wiring follow-up (2026-11-12)

The 17:53:50 log of a4d1bfc confirms full vegetation enabled and compute emulation selected, but every reported mesh draw is skipped with `mesh draw through compute that the look-ahead did not prepare`. No compute-mesh batches were recorded. The port had added `memu_before_draw` without wiring it into this fork's custom OP_DRAW / OP_DRAW_IDX cases. Both executor paths now run preparation before discard prediction and occlusion accounting. The regression compiles the actual case bodies and checks preparation precedes rasterization, including an indexed draw opening a pass, initially open/closed passes and disabled rendering. Shader compilation alone did not cover this integration fault. Visible vegetation still requires a fresh device check.

### Build 98 vegetation dependency audit (2026-11-12)

Open, not a validated vegetation fix. The 18:19:09 log of b912250 shows compute-mesh execution (9,436 draws / 6,434 batches, later 21,595 / 14,134) with zero `not prepared`. This confirms the replay wiring, not coverage of the missing foliage programs: rejected programs do not reach those successful batches. The loaded library has 42,339 entries. All 28 distinct logged missing keys are absent from this fork's map and facts, and present in Banana Native android d652abeb534496724e798ff96474752903d7953a. There are 24 mesh and four task keys; 24 originate in Foliage.Product and four in Model.Product. Error reporting stops after 32 messages, so 28 is not a complete missing-shader census.

Comparing the static maps gives 509 additional unique upstream keys: 491 mesh, 17 task, one vertex. Of those, 114 map rows originate in the two Foliage containers. These are original guest shader keys, not runtime compute-emulation helper keys. The map contains 42,340 keys locally; the installed library's 42,339 entries are a separate count. Do not assume a map entry proves successful translation.

Confirmed blockers before another vegetation APK:

1. `shader_split.bnsh_shaders` reads six program slots, unlike upstream's nine. A fixture with real-format control headers and stages in slots 7/8 returns no shaders with the current production reader and task+mesh with the actual upstream reader. Restore extended NVN2 stage discovery with old-format pointer validation; do not replace unrelated memory/resume changes wholesale.
2. Carry the missing keys' source locations, mesh layouts and task/mesh/pixel pair metadata into a bounded preparation path. `0c1ffecd02018fb0`, `a5288d0a6c4971fd` and `d4171cf9adf0504b` have no facts here. The current selective job requires every source in `nvn_shdump`; it cannot obtain missing static records from the dump. The attached diagnostic archive contains a log, not the original control/code captures.
3. Preserve the working full library and approved replacements. Replacing `shader_map.tsv` / `shader_facts.tsv` wholesale changes the profile inputs digest and is not a safe incremental supplement. Validate the required stage/pixel dependency closure, source hashes, translation and ABI in a separate bounded update.
4. Repair the capture/bootstrap and load path together. `stage_in_program` recognizes stages through existing library entries; `vka_ocarina_capture_mesh_draw_pair` exits when no hot library is loaded, as in this run. `library_for_key` also rejects hot mesh/task entries by default, even when absent from the base. Blanket-enabling unverified older hot mesh shaders would reintroduce the previously observed geometry corruption.
5. A vegetation supplement must require its complete dependency closure. The generic capture repair currently defers unpaired/failed shaders and can publish the remaining subset. Successful partial publication or APK compilation does not prove the foliage shaders exist, load or draw.

Release gate: verify each requested foliage/task dependency exists in the resulting supplement and is selected by the real runtime path, then check its converted Vulkan modules and draw submission. Visible foliage remains a device validation item; no new APK was generated for this audit. See the [shared mechanism](../../../docs/reference/shaders.md#extended-nvn2-stages-absent-from-the-shader-preparation).


### Static vegetation supplement integration (2026-11-12)

Implemented, CPU validation passed; actual source translation and visible phone rendering remain pending. `vegetation_shaders.tsv` carries the 491 missing mesh and 17 missing task stages from the reviewed Banana Native map/facts, excluding the unrelated extra vertex key. It is a supplemental table, deliberately outside the original profile inputs digest. All 28 logged missing stages are included. The BNSH reader now covers the three extended slots with NVN2 validation and bounds checks for legacy programs.

`ocarina_vegetation.extract` reads only three top-level containers (two contain SARC members), visits the reviewed BNSH source locations, and verifies every original control/code hash, source stage and raw mesh layout. Original static facts preserve the pixel-padding requirements; this set has no per-primitive fragment overrides. The tool requires all stage/pixel dependencies in the preserved base or the selected set. It produces only 508 original shader records, not a full split or a runtime-capture repair. A translation failure or missing published key prevents replacing the supplemental library.

The on-device **Repair missing shaders** action prioritizes this explicit job over captured hot repairs. Retries persist its exact 508 keys, skip the full split, require no fresh gameplay/capture, and compile into `shaders/vegetation/v-<current>/dmsh_vk.lib`. The final step validates that file instead of invoking the hot-library packer. Existing base, approved replacements and hot overlay remain untouched. A one-time partial preparation from the user's game dump is necessary: an APK alone cannot manufacture the original shader code. Its output uses the current Vulkan chain and the original base inputs; neither old library header nor profile tables are relabelled.

At startup the runtime accepts only the exact reviewed stage set with base-compatible inputs, subgroup and buffer alignment, current-chain/ABI metadata, base SPIR-V modules and complete dependencies. The additive lookup precedes the old hot-mesh quarantine only for keys absent from the full base. Original entries retain their old modules. Program stage resolution, derived compute/vertex prewarm lookup and library membership all use that same lookup, avoiding another integration gap. The old capture bootstrap is not needed for this static update and its unverified geometry remains quarantined.

Validation: synthetic NVN2 BNSH -> production extended-slot reader -> verified records; changed code and inconsistent layouts rejected; manifest coverage/dependency checks; actual `vegetation_complete` and `library_for_key` with the production library reader under ASan/UBSan. Existing capture/overlay, mesh replay and chain tests are retained. This is not a visual validation or a measured FPS/RAM improvement. The device must complete the 508-stage preparation and then show the supplement accepted in its startup log before a gameplay result can establish visible foliage.


### Build 100 launcher-process regression (2026-11-12)

The phone video `Screenrecorder-20261112-190101.mp4` shows **56**, not 508, in Repair missing shaders, and the confirmation returns to the ready library without visible preparation. Root cause: `vegetationKeys()` called `PackNative.repo()` in the launcher process. Native context is installed only by `PackEngine.create` in the separate `:pack` service process; `repo()` therefore throws `PackNative.context not set`. The exception was swallowed, returning an empty vegetation list and selecting the 56 historical captures instead. The file was present in the APK; successful native builds and extraction tests did not exercise this process boundary.

Fixed: `ocarina_vegetation.py --header` generates the immutable `OcarinaVegetation.KEYS` Java registry from the same reviewed manifest as the native admission header. Launcher selection and persistent job-mode validation no longer require native context, extraction or Python. `--check` verifies both registries against the authoritative table. The shader service still verifies/extracts the real original sources before translation; embedding keys does not manufacture shader code.

A second control-flow bug hid the pending or failed optional shader job whenever the existing base was playable. The launcher now keeps its task visible until the update is done, without revoking Play on the unchanged full base. Explicit repair opens the preparation screen and clears autoplay.

Validation: `test_ocarina_vegetation_launcher.py` compiles the actual production selector and the actual visibility-control prefix on the JVM. With no native packer context and 56 old capture pairs, it requires exactly 508 static keys, zero native repo calls, the separate output path and visible pending/failed progress. Running the same test against build 100 reproduces `Expected 508 ... got 56`; independently restoring its old display prefix reproduces `Pending update hidden as playable base`. Both pass with the fix. Device translation and foliage rendering remain pending. See [launcher process isolation](../../../docs/reference/shaders.md#launcher-shader-selection-before-the-pack-process-starts).


### Build 101 dictionary-compressed static extraction (2026-11-12)

Phone log `shaders.log` at 19:16:13 and 19:16:25 (screenshot `1165618.jpg`) confirms the correct 508-stage `vegetation-pkg` job, then fails before translation on ApplicationPackage: `a frame needs zstd dictionary 1`. The partial extractor imported `shader_split` and called `unzs` directly, skipping the full splitter's worker initialization of `ZDICTS`. The error therefore did not establish that the user's dump lacked a dictionary.

Fixed: the bounded extractor loads `Pack/ZsDic.pack.zs` through the same read-only RomFS/NUP adapter before opening compressed shader containers. For a selected update, it loads the base dictionaries first and overlays that update's dictionaries; this works for both a `.nup:update/131072/romfs` selector and the corresponding extracted `updates/131072/romfs` layout. Each extraction gets a fresh decoded-dictionary cache and restores the prior module state on success or failure, so ID 1 from another dump cannot be reused accidentally. Source hashes, static layouts, exact 508-stage completeness and the separate output library remain required. Dictionary and shader input streams now close immediately after reading.

Validation: the production extractor processes an actual dictionary-compressed synthetic SARC/BNSH using a trained Zstandard dictionary with ID 1, first from an extracted update directory, then from an actual NUP with spaces in its filename and the dictionary only in its base package, and from the equivalent base/update directory layout. The records pass their original key checks. A subsequent dump with no dictionary fails instead of borrowing a previous ID. The build 101 extractor reproduces the same phone error even with a present dictionary pack; the updated code passes. CI installs the tested Zstandard backport for the host fixture; the phone already has the decompressor. No original game code or dictionary bytes are included in the test/repository. Device shader translation and rendering remain pending. See [compression dictionary initialization](../../../docs/reference/shaders.md#compression-dictionaries-in-bounded-static-shader-extraction).

### Working foliage: performance audit and pending memory-layout experiment (2026-11-13)

**Current:** the user confirms visible vegetation now works. Preserve the full 42,339-entry base, its six approved replacements, the separate verified 508-stage supplement, and the original-native/supplement-compute hybrid. Build118 (`c0397be0`) is the regression-rollback baseline, not a demonstrated foliage speedup. Do not restore the supplemental native path: the user's Build112/113 tests produced white geometry. The taskless search bypass and wider command-list look-ahead are already integrated; repeating them is not a new optimization.

The reviewed Banana Native upstream revision `d652abeb534496724e798ff96474752903d7953a` also explicitly disables native mesh on Qualcomm's proprietary driver by default (`vka_dev.c`, `mesh_qcom` / `x_mesh`), logging that its native mesh pipelines draw foliage incorrectly. `DM_VK_MESH=1` is an override there, not an upstream-confirmed correctness/performance fix. The earlier assertion that globally enabling native mesh simply restores Banana's safe default was incorrect. The hybrid retains this branch's already-working original draws without re-enabling the broken supplemental route.

The four supplied heavy-scene diagnostics have the following completed 901–1200-frame windows. These are interval medians, not averages of sparse GPU timestamps:

| Build / diagnostic timestamp | Frame p50 ms | GPU p50 ms | CPU recording ms | Draws/frame | Full barriers/frame |
|---|---:|---:|---:|---:|---:|
| 114 / 213557 | 27.63 | 27.11 | 17.82 | 2433 | 187 |
| 115 / 215129 | 27.47 | 27.01 | 17.27 | 2422 | 188 |
| 116 / 221557 | 27.61 | 27.15 | 18.34 | 2419 | 187 |
| 117 / 224747 | 33.22 | 28.66 | 18.21 | 2431 | 220 |

Build117 increased frame p50 by 20.32%, GPU p50 by 5.56%, and GPU p95 by 19.49%. Its four hot mesh samples total 4.564 ms against Build116's 4.604 ms; this does not establish a whole-frame improvement. The differing barrier count also prevents blaming the entire regression on its vector bitcast. Build118 restores the original scalar output SPIR-V by default. `dm/tools/android_perf_compare.py before.log after.log --frame 1200 --check` reproduces the regression verdict, reports changed context, and refuses to treat vegetation OFF or a missing warm interval as a successful comparison.

Build116's instrumented frame1201 attributes 7.468 ms to converted mesh execution, 0.733 ms to tasks, and 13.87 ms to graphics passes. The four largest mesh keys (`fed302d791a4ba43`, `eb021183bf9b0092`, `604134a5262ff670`, `73dc0b90c4082e43`) account for 4.604 ms. Sampling occurs once per 300 frames and perturbs execution; these sums are not interchangeable with the 27.15 ms interval GPU median. The scene targets are **683x384**, upscaled to 1280x720; a Banana Native 960x540 run is not an equal-resolution comparison.

The earlier paired Build105 logs 201149/201248 have frame p50 32.55/23.08 ms and GPU p50 28.58/22.62 ms with vegetation ON/OFF. They precede the hybrid and caller-stack changes, and differ in draw/barrier counts. They cannot quantify the current build's foliage raster cost or justify subtracting 7.468 ms from another build's median to infer a missing 2 ms.

**Experiment, off by default:** the existing arena stores vertex components as `base + vertex*VW + component`; adjacent invocations can write distant cache lines. `DM_VK_MEMU_COALESCED=1` transposes the vertex region within each mesh workgroup to `base + component*MAXV + vertex`. The generated vertex reader applies the inverse mapping. Primitive data, all 32-bit values, task mapping and draw counts are preserved. Indexed regions must now align to `MAXV*VW`, so there is extra allocation padding, at most one group stride minus one word per allocation. This is a memory-access hypothesis, **not a measured Adreno speedup**. Additional address arithmetic and padding may outweigh its benefit. Separate derived shader keys and helper modules prevent cache/producer/reader mixing. With the switch unset, both fixture CS/VS bytecode and the original checked-in setup/distribution modules remain unchanged. Original shader files and library ABI do not change, so this experiment requires no shader preparation.

Validation: actual converted mesh SPIR-V executed through Vulkan/SwiftShader, checked with `spirv-val`, then decoded using the production generated vertex reader with a bounds-checked evaluator. AoS and planar outputs match bit-for-bit for triangles with 64/96/128 capacity, taskless and task-driven dispatches, a zero-output middle task, 2D dispatch flattening, dynamic component stores, unwritten components, points, point sizes, per-primitive attributes and culling. Actual checked-in alternate setup/distribution modules pass Vulkan readback checks for alignment, non-overlap, bounded allocation failure and task prefix mapping. Scalar fixture hashes match Build118. Existing hybrid routing and ordering tests pass. SwiftShader correctness is **not physical GPU timing**; the CI workflow is deliberately named **Mesh compute correctness (no APK)**. The Mac `scripts/regress.py check` cannot execute on this Linux host (`/usr/lib/libproc.dylib` is absent), and no local game dump or physical Adreno is available.

Release gate remains open: a same-scene, same-driver device A/B must improve total warm frame/GPU time and preserve the visible scene and memory headroom before enabling the layout or issuing a performance APK. No new APK is triggered by this audit/experiment. See [the shared runtime mechanism](../../../docs/reference/rendering.md#compute-mesh-export-memory-layout-experiment).

### Direct plane scatter from the uploaded supplement (2026-11-13)

**Implemented for a controlled device test; Adreno frame-time improvement remains unmeasured.** The user's `vegetation.zip` contains a complete 508-entry library at `vegetation/v-b127f6d0b014/dmsh_vk.lib`, 35,084,220 bytes, SHA256 `c37b7801c2f4899ae75e16764e50075774955a899904a169e0e23cda37ebb80b`. All 17 task and 491 mesh modules convert and pass `spirv-val`; none are refused. This provides actual compiled instructions, unlike the previous diagnostic archives.

The four hot modules expose another cost independent of the experimental planar arena. `SpirvMeshEntry.cs` generates `mesh_plane_store(word, value)`, which walks every possible plane with independent conditional stores. Compute conversion preserves that entire ladder although every output now lands in a single word-addressed arena. The helpers have 63–130 call sites in the expensive shader bodies:

| Original mesh key | Call sites | Helper conditional branches, before/after | Mean executed helper instructions, before/after |
|---|---:|---:|---:|
| `fed302d791a4ba43` | 100 | 27 / 4 | 129.0 / 45.1 |
| `eb021183bf9b0092` | 63 | 23 / 4 | 112.6 / 45.0 |
| `604134a5262ff670` | 92 | 25 / 4 | 121.0 / 45.1 |
| `73dc0b90c4082e43` | 130 | 28 / 4 | 132.6 / 45.0 |

The executed-instruction means come from exhaustive interpretation of each real converted helper across its valid word range plus 33 out-of-range words. They count helper work, **not GPU cycles or whole-shader invocations**. The runtime converter now proves the complete known structured helper body, bounds, plane ordering, destination mapping and optional z/w workgroup mirrors before replacing the ladder with packed constant-vector lookup and one arena store. Only the two bounds and up to two mirror guards remain. Unknown bodies, extra stores, changed mirror values, primitive-plane cases, more than 32 planes and dangling local decorations retain the original conversion. No name or shader-key whitelist grants permission by itself.

Validation on the uploaded library: 464 mesh helpers match; the other modules retain the existing path, and every generated vertex shader stays byte-identical. 45,749 sampled word/value cases across all transformed real helpers and exhaustive cases for the four hot keys produce identical arena and workgroup writes. Independent synthetic fixtures cover sparse locations, 96/128 vertices, boundary/overflow words, raw NaN/infinity/negative-zero words, and changed-side-effect negative controls. Actual Vulkan readback checks complete arenas, index bias and exported z/w mirrors against an independent oracle, with both the default and experimental planar layouts.

A timestamped **software Vulkan synthetic fixture** with 27 helper calls per invocation and 16 ordered dispatches measured median 2.187 ms before / 0.745 ms after across three alternated runs per path, with identical readback. A one-call version dominated by mirror export measured 0.370 / 0.387 ms, with overlapping samples; it did not establish a gain. These are fixture timings on SwiftShader, **not measurements of the real Adreno game**. The real modules contain many other operations, including cached raw-memory access; the result cannot predict an FPS percentage.

`Optimize vegetation` / `Otimizar vegetação` defaults on and sets `DM_VK_MEMU_PLANE_LUT=1`; off restores the prior scalar scatter (`=0`) without removing foliage. Restart between comparisons, leave Full vegetation on, and use the same save/camera/driver. Distinct runtime compute keys prevent binary-cache confusion, while both old and new prewarm records resolve to the active implementation, including rollback. Vertex keys and the arena format do not change. The earlier coalesced arena remains off, and vector-bitcast remains off. The full 42,339 shaders, approved replacements, 508-entry supplement, shader ABI, native-original hybrid, package and signing identity are preserved. No shader preparation is required; affected driver pipelines may compile once.

See [the general scatter lowering](../../../docs/reference/rendering.md#dynamic-mesh-plane-scatter-through-a-branch-ladder). The test APK is an isolated runtime optimization with an in-app comparison switch, not a claim of confirmed phone FPS improvement.


### Build 120 device result and CPU input reuse (2026-11-13)

The uploaded `013618` log identifies `eed329f757df`, direct plane lookup enabled and complete foliage. The title menu lasts through frame 3000, so matching frame numbers against earlier runs would compare different scenes. Warm gameplay windows ending at 3900/4200 measure whole-frame p50 26.17/26.29 ms, GPU p50 25.74/25.82 ms and command recording 17.67/17.69 ms. The earlier Build 116 gameplay window measured 27.61/27.15/18.34 ms respectively. Camera differences prevent treating every delta as a controlled effect.

Sparse GPU samples nevertheless explain the observed change: mesh compute falls from 7.468 ms to 6.050 ms, with the four hot keys summing 4.604 to 3.515 ms. Graphics remains 13.87 to 13.89 ms. Other warm samples show mesh 5.910 ms and graphics 14.02 ms. Thus neither a repeat of taskless-search changes nor fixing only the remaining mesh work can establish 60 FPS; raster work and CPU command recording also need attention. VRS 2x2 already applies to the hot fragment stages and is not a new remedy.

Comparison with Banana Native `d652abeb534496724e798ff96474752903d7953a` found its input-stamp driver-segment and vertex-input reuse missing here. The previous memo still rebuilt each driver bank before comparing the bytes, although the device log reports 74% unchanged banks. The port stamps every relevant SSBO/texture/sampler/image/push change, includes direct base-instance/sample/pool inputs, and gives copied queue/look-ahead states globally unique revisions. Compute's GPU-patched c0 and unknown banks retain their original fill path. Vertex descriptions reuse the same shader/format revision; vertex buffer lookup reuse also requires the same memory generation and valid command-buffer state. `DM_VK_DRV_STAMP=0` and `DM_VK_VIN_SKIP=0` independently restore the earlier paths.

A compiled production-C regression compares 3000 mixed driver operations and copied states against actual `vka_drv_fill`, plus 500 vertex operations against the uncached production functions, including memory placement and command-buffer invalidation. ASan/UBSan passes. An x86 host synthetic repeat of an unchanged c2 bind measured 300.30 ns with 200000 fills versus 5.52 ns with zero fills. This measures avoided CPU work only, not an Adreno frame-time prediction. The runtime logs actual stamp and vertex cache hit rates.

The existing component-planar mesh arena can also be compared from `Vegetation memory layout (test)` / `Memória contígua da vegetação (teste)`. It remains OFF by default; full foliage and direct plane lookup stay ON. With lookup enabled, a 27-call software Vulkan fixture measured median 0.661 ms for the original arena versus 0.597 ms for component planes across three alternated runs; this is not phone FPS evidence. Producer and vertex-reader layouts are validated together. Historical prewarm recipes for either layout resolve to the active module and its distinct cache key, preserving recipes without reusing incompatible pipelines. Restart after changing the option; one-time driver compilation may occur, but the imported full library and ABI are preserved.

Next device comparison must evaluate whole warm frame/GPU intervals, not only a hot shader timestamp. For the remaining graphics cost, the existing `Work/0400486024DEC000/nvn_shdump/` capture folder contains original `.ctl`/`.code` hot-stage inputs; the uploaded archive contains only the text log, so their instructions have not yet been audited.


### Same-build foliage comparison and captured compute correction (2026-11-13)

Both `065713` (ON) and `070945` (OFF) identify `b440784167c9`, APK versionCode 123. Use warm intervals ending at 1500/1800 separately from sparse GPU frames 1201/1501/1801. Frame p50 is 25.135 versus 18.015 ms; GPU p50 24.680 versus 17.615 ms; command recording 17.675 versus 16.295 ms. The measured GPU increment is about 7.07 ms, not 14 ms. Graphics sample medians are 13.97 versus 11.92 ms: approximately 2.05 ms additional graphics. ON also costs about 4.01 ms mesh compute and 0.69 ms task work. Those are already represented in profiler intervals labelled bare steps: do not add that entire category again. Sparse profiling disables normal zero-dispatch/overlap shortcuts, so do not fit sampled compute totals directly to ordinary-frame medians.

The two heaviest initial graphics chunks sum 4.45-4.54 ms ON and 4.59-4.68 ms OFF. They are mixed-shader blocks and remain costly without foliage. Their time is neither a fragment-only measurement nor evidence of removable vegetation work. Scene subsets and mixed subsets overlap the complete graphics total. ON has 150 render passes versus 124 OFF, and about 35-36 more full barriers; these can also contribute to the graphics increment. Shader state operations are already fully covered by `memu_allowed`, and query report/reset operations are already allowed: merely repeating those proposed integrations would not fix the splits.

The OFF run also sets plane lookup/coalesced layout to zero. Its supplemental mesh work is omitted before preparation; this is not a controlled ON-layout comparison, but those switches do not execute the removed supplemental compute path. Driver, build, output resolution and scene settings match; camera identity is not mechanically proven by counters.

The supplied `nvn_shdump(1).zip` contains verified original `.ctl`/`.code` for fragment keys `1e4d2630d24846d0`, `5ad65c0eefd09c7f`, `00ce4088af2c8e12` and compute `9e6b00b050e30801`, plus task/mesh captures. Control/code hashes are checked before translation. Auditing the fragments with the existing local ALU-CSE pass removes zero further operations; repeating that pass is not a new optimization. The constant-white `00ce` fragment cannot explain its complete vertex/depth/ROP block duration. No fragment samples or shading effects have been removed.

The real compute confirms the exact failure logged on the device: `virtual=aliased/indirect builtin use`. It reads X/Y/Z through six `OpAccessChain` scalar component pointers into `LocalInvocationId` and `WorkgroupId`. The runtime virtual retiler only accepted whole-uvec3 `OpLoad`, so its intended 8x4x4 -> 8x4x2 variant was never active. The correction recognizes only a direct one-level Input-uint pointer with a literal 0/1/2 index and unqualified uint load. X/Y remain unchanged; GroupZ divides by two; LocalZ adds twice the physical GroupZ parity; NumWorkgroups remains the original 8x9x12. Dynamic indices, pointer escapes/nesting, qualified loads, shared memory, barriers and atomics remain refused. The existing caller still restricts this to the exact direct 8x9x12 dispatch and retains the original pipeline and `DM_VK_OOT_CS_RETILE=0` rollback.

The source-verified real shader now transforms successfully and both original/transformed modules pass Vulkan 1.3 validation after the existing formatless-image capability normalization. A standalone independent GPU fixture executes all 110592 invocations with original/retiled grids and compares every encoded group/local/grid tuple plus a write sentinel to a CPU oracle. This establishes identity and complete coverage, not real Adreno speed. The user still needs to measure the newly enabled variant. No full library, shader ABI, foliage, SGSR1 or output-resolution change is needed.


The controlled APK exposes `Optimize compute (test)` / `Otimizar compute (teste)` independently of foliage. It defaults ON (`DM_VK_OOT_CS_RETILE=1`); OFF selects the original compute on restart. The JVM regression executes the actual persistent preference and launch environment to verify that changing it does not alter foliage, plane lookup or coalesced storage settings. Keep those three established foliage settings ON for the next same-camera compute ON/OFF comparison.

### Build 124 device result and bounded fragment AST alternative (2026-11-13)

The user's 07:50:25 log confirms the component-pointer compute retile actually
runs (six virtualized scalar builtin loads, physical 8x4x2 workgroups). Warm
1500/1800-frame summaries move from 25.135 to 24.595 ms/frame and GPU
24.680 to 24.140 ms. These separate sessions are not an isolated causal
benchmark: the sampled `9e6b` compute remains about 1.3–1.4 ms, so do not credit
the whole ~0.54 ms to compute. Graphics remains about 14 ms, mesh about 4 ms.
The first 16-draw scene block consistently identifies all 16 fragments as
`1e4d2630d24846d0` and costs about 3.25–3.30 ms. This includes vertex, depth,
ROP and pass overhead, not 3.3 ms of removable fragment ALU.

The actual uploaded `.ctl/.code` captures were verified against their program
keys. The locked translator's non-debug AST mode compiles `1e4d`, with identical
reflection, descriptor resources and stage interface. The official normal-mode
one-key build reproduces the full manifest's entry digest `62a0bcaaa922986f`.
Do **not** enable this mode globally: `5ad6` and `9e6b` fail in the translator
with an AST operand cast error. Repeating existing local ALU CSE removes zero
additional operations in these captured fragments.

For the **final Vulkan base module**, code size falls 231,172 to 155,756 bytes.
After applying the same diagnostic `spirv-opt -O` to both final modules,
instructions fall 4,125 to 2,982, conditional branches 95 to 75, while all
18 image samples remain. Earlier raw-frontend instruction counts are not the
final Vulkan counts. These figures describe code, not predicted phone FPS.

Both final base and UINT-output variants passed 12 synthetic GPU comparisons
each (128x128 RGBA32F, four finite uniform patterns, three alternating runs).
Every comparison had max absolute error 0. Base output had all 65,536
components finite and nontrivial patterns with 21,239/41,875 distinct values.
UINT variant 1 uses an RGBA32_UINT target and exact integer equality (not
a float attachment or float tolerance). Textures retain their
actual dimensionality and all sample operations. Important limits: descriptors
are specialized to index zero on **both probe copies**, textures have one mip,
SSBO/support data are synthetic, and this is SwiftShader, not a game replay
or Adreno timing. The unchanged, fully indexed production modules are the
ones packaged. Warm software timestamps improve but do not establish an
Adreno speedup or guarantee equivalence on all game inputs.

Build 125 adds only the explicitly imported, one-entry fragment experiment
(documented in `android/SHADERS.md`). Its real version is `a16478ff8bcd`,
frontend `de2cd6b79f33`, same ABI and profile inputs. Normal headers and all
42,339+six replacement+508 supplement bytes stay intact. The APK has an
independent per-game switch and logs actual key selection. Import/recovery
and native resource/IO mismatch refusals are tested; the baseline and optimized
private libraries pass the production gate. No resolution, foliage, texture
samples, SGSR1 or shader quality setting is reduced. Phone performance and
visual validation of this alternative remain necessary; do not advertise a
measured FPS gain from its synthetic test.

The initial variant-1 probe used an incorrectly typed float target and was
excluded. Repeating it with the actual uint32 output format passes all 12
cases bit-for-bit. The generic negative control now also changes each UINT
output by one least-significant bit, and must fail. This probe correction does
not modify the production library, APK shader selector or packaged shader bytes.

### Build 125 phone A/B: AST alternative has no demonstrated speedup (2026-11-13)

The user's `085434` and `085545` logs are the same `ff379e5` APK and driver
891.14. The only launcher environment difference is `DM_VK_OOT_FRAGMENT_AST`
0 versus 1. OFF explicitly logs the original shader; ON logs both exact
resource/IO compatibility and `fragment AST ACTIVE`. Import and runtime
selection therefore worked. Do not attribute the negative result to a missing
ZIP, inactive option, or require the same upload/preparation again.

Use median-of-window-p50 values at frames 1500/1800/2100, excluding ON's
1200-frame transition (1783 versus ~2450 draws/frame):

| Metric | AST OFF | AST ON |
| --- | ---: | ---: |
| Frame p50 (ms) | 24.47 | 24.51 |
| GPU p50 (ms) | 24.01 | 24.05 |
| Frame p95 (ms) | 25.34 | 25.31 |
| CPU recording per frame (ms) | 16.73 | 16.64 |
| Sampled graphics intervals (ms) | 14.00 | 13.90 |
| Dominated `1e4d` graphics groups (ms) | 3.249 | 3.267 |

Stable windows contain ~2419–2422 OFF versus ~2451–2456 ON draws/frame;
these are not identical recorded replays. The differences do not demonstrate
a speedup or a meaningful regression. The IR reduction and synthetic timing
improvement did not translate to a demonstrated phone gain. Keep the option
reversible and do not enable/promote it as a proven performance improvement.
These files are sufficient to close this A/B; do not ask for another identical
pair without a concrete new question.

Source inspection of the production `vka_spv_pool_fb` transform on BOTH real
final `1e4d` modules finds seven injected feedback sites/conditional branches
and seven atomic-OR instructions (conditional, not necessarily executed for
every fragment). Both retain 18 texture sample instructions. Runtime injection
adds 121 SPIR-V instructions in each case; `early=2` requires the existing
pipeline alpha-test/coverage guard. The phone log confirms GPU pool feedback
is active. The previous probe did not include this runtime rewrite, so it did
not isolate its overhead. Feedback is required to discover and retain textures
read through the bindless pool: switching it off is not a quality-preserving
optimization. Its time is still unmeasured separately; neither texture latency,
feedback nor attachment/vertex costs are proven to explain the whole 3.27 ms.
A subsequent shader experiment must include the runtime-patched modules and
separately validate their texture-ID reporting as well as pixel values.

## SGSR1 and Banana comparison (2026-11-13, current)

The tested Banana 0.3.20 log identifies commit `db79a6d937a2`; that original
repository/commit was unavailable at audit time. The public Android source
snapshot audited here is `hidayat077/BananaNative` at
`0bac816c8470f3b5a65f23dc011bdcc48ffcd59d`. Do not equate the two revisions.

The same driver 891.14 logs show these different render workloads:

| Log / path | NDSR input and output | frame p50 at 1200 | GPU at 1200 |
|---|---|---:|---:|
| Swap 123745, internal SGSR1, optional hidden layers on | 683x384 -> 2048x1152 | 24.30 ms | 23.85 ms |
| Swap 123841, internal SGSR1, hidden layers off | 683x384 -> 2048x1152 | 24.55 ms | 24.12 ms |
| Swap 123945, bilinear NDSR plus final SGSR1 at 720p | 683x384 -> 2048x1152 | 24.04 ms | 23.63 ms |
| Banana 124342, internal SGSR1, handheld graphics scale 2 | 960x540 -> 1280x720 | 23.67 ms | 22.69 ms |

These are whole-frame samples, not isolated kernel benchmarks. Banana's NDSR
output has 2.56 times fewer pixels despite its larger scene. Sparse profiled
Swap frames report about 0.57-0.58 ms for internal SGSR1 versus 0.48 ms for
bilinear, but the existing ordinary-frame NDSR retile is disabled during GPU
profiling. Those samples cannot prove the normal retiled kernel cost.

**Resolved implementation mismatch:** the old internal SGSR1 adapter omitted
edge direction and used a different Y anchor and normalization. The new kernel
ports the public Banana/Qualcomm algorithm with the complete BSD notice,
mediump reconstruction, highp coordinates, an independent linear/clamp sampler,
24-byte dimension push constants, and direct 8x8 output dispatch. It retains
encoding conversion, HDR highlights, crop mapping and packed stores. The
original EASU, bilinear and final-720p options stay available. A non-direct
launch retains the prior compatible path. See
[Native SGSR1 reconstruction](../../../docs/reference/rendering.md#native-sgsr1-reconstruction).

**Explicit output comparison:** the new optional scene/output profile offers
640x360 -> 1280x720 and 960x540 -> 1280x720, by the engine's handheld scale-2
configuration and its own scene palette. Mode zero keeps the existing choices
and remains the default. Selecting a profile prepares only the scene overlay;
it does not rebuild the shader library. This is a disclosed output-profile
change, not an instruction-level speedup at identical output quality.

**Validation:** `test_ndsr_sgsr_gpu.py` compiles an independent public-source
reference plus the adapter's grid-stride control. Twenty combinations of sizes,
linear/sqrt inputs and float/packed B10G11R11 stores match every decoded output
pixel, with HDR values retained. An odd-origin crop preserves pixels outside
it. The previous simplified kernel fails the reference in 112,381 components,
so the comparison detects the regression it targets. Existing EASU/bilinear
GPU checks also pass. Software-driver timestamps are not phone performance
measurements; Adreno image quality and frame time remain to be checked.

**Other Banana differences, open:** the public source and tested log use
cached classic render passes (`DM_VK_CLASSIC_RP=1`) rather than this fork's
dynamic rendering. It also has a newer native mesh-prepass workaround with
22 mapped pairs; the seven coarse vegetation-quality pairs here are not its
equivalent. Neither mechanism is silently enabled or represented as already
ported by this SGSR fix. The log does not expose a vegetation-off flag, so a
vegetation difference is not established. No measured frame gain has yet been
attributed to these backend differences.


## Cached classic render passes (2026-11-13, current)

**APK134 defect found and corrected:** log `140709` confirms the encoder
thread and classic passes both enabled, and reports a preceding native SIGSEGV
without its faulting stack. The classic begin/end calls had been added to the
renderer but omitted from `vka_enc.c`. Thus `vkCmdBeginRenderPass` and
`vkCmdEndRenderPass` reached the driver directly on the producer while binds,
draws and barriers stayed queued on the worker. Vulkan command-buffer recording
was unordered and concurrently accessed. The earlier GPU fixture called the
driver directly and could not expose this missing integration.

`vka_enc.c` now copies classic begin/end records into the same ring as every
other command, including clear values and imageless attachment view arrays.
At dispatch the inline pNext record is rebased before the driver call. Unknown
pNext chains drain the queue before a direct call, preserving the existing
fallback rule. The ARM wait primitive is unchanged; a host atomic-load fallback
enables production-code Linux tests. Encoder installation logs
`classic render-pass begin/end serialization installed`.

The recovery-only candidate was superseded at the user's request. The corrected
cache is available in the same **Cached passes (Qualcomm)** control, now OFF
by default and on Restore defaults. ON explicitly sets `DM_VK_CLASSIC_RP=1`;
OFF sets zero. Restart after changing it. No resolution, vegetation, fragment
skip, filter, or prepared shader library is changed by this fix.

**Regression:** `test_classic_encoder_order.py` executes the actual producer,
worker, ring, serialization and dispatcher (only its Android header is adapted
for a Linux host). 50,000 passes / 200,000 commands exceed one full ring. Caller
arrays are poisoned immediately; order, worker ownership and copied values all
pass under ASan/UBSan. Its negative control bypasses the begin/end wrappers just
as APK134 did and fails the same checks. The GPU fixture now additionally
records every Vulkan command through that actual worker and compares dynamic
and classic MRT output at 67x41 and 960x540, including scissored LOAD/CLEAR,
partial clears and independent depth/stencil readback. Both direct and threaded
paths match exactly; CI enables Khronos validation. Software timings are not
Adreno FPS guarantees; threaded CPU-recording timing can regress on software.

The backend retains the public Banana snapshot's compatible whole/GPL pipelines
and imageless shape caches, preserving this fork's per-aspect load/store
semantics. See [Cached Vulkan render passes](../../../docs/reference/rendering.md#cached-vulkan-render-passes).

The earlier 540p log `134102` used EASU NDSR plus final SGSR1, heavy-fragment
skip ON and hidden layers OFF: p50 at frame1500 was 21.60 ms frame, 20.97 ms
GPU and 18.61 ms recording (149 passes). These timings overlap and must not be
added. The remaining gap to 16.67 ms and the fixed option's actual performance
on driver891.14 remain device-validation work, not a reason to claim 60 FPS.
The existing sampled scene profiler now recognizes 640x360 and 960x540 as well
as legacy683x384, with no ordinary-frame GPU commands.

### Withdrawn render-enable fusion experiment (2026-11-13)

The uploaded `174854` run identifies `32e82da+dirty`, driver 891.14,
960x540 scene, integral compute mesh routing and render-enable fusion ON.
At frames 1200-2400, frame p50 stays 20.83-20.99 ms and GPU p50
20.46-20.61 ms. The walker crosses roughly 22 unconditional-true records
per frame but still splits mesh preparation roughly 25 times per frame.
The synthetic true-only stream's batching improvement did not remove the
real scene's conditional boundaries. This run alone is not a controlled
ON/OFF proof of regression or a measure of the option's isolated cost.

At the user's request the experimental `Group vegetation across render
enable` control, launcher export, preference accessors, runtime override
and counters are removed. Previously saved values no longer enable it.
Every render-enable command again terminates mesh lookahead and clears
its coverage; replay still evaluates the original condition. Integral
compute routing and the existing prepared shader library are unchanged.
The production-walker C regression covers all four render-enable modes,
malformed records and nested command lists, not merely an idealized batch.

The sampled frame1501 graphics chunks total about 10.4 ms; mesh and task
intervals additionally account for about 3.1 and 0.5 ms respectively.
Blocks dominated by FS `1e4d2630d24846d0` sum about 3.14 ms, including
vertex, depth and attachment work: these are not fragment-only savings.
Forcing early fragment tests on alpha-discard modules was considered and
rejected: even read-only depth/stencil does not preserve samples-passed
query semantics when discarded fragments begin counting before shading.
`g_oq_count` persists after the first reset; a read-only attachment check
alone is insufficient. No such change is shipped.

Shading-rate image calls remain unimplemented; the device reports KHR
attachment shading-rate support, but the current trace does not establish
the guest palette ABI or image encoding. The inspected public Banana
snapshot also stubs these calls, so it is not evidence of a working port.
Removing this experiment is cleanup, not a claimed FPS optimization.

### Compute-route HDR VRS correction (2026-11-13)

The `174854` log uses integral compute and VRS 2x2. The captured HDR pass
`5ad65c0eefd09c7f` costs 0.55-0.71 ms at 480x270 with two RGBA16F targets,
but never reports VRS ready for that key. `pstate_fill` recognized only the
native `(task efaa4fa6a80ba719, mesh 066f5daf12e43c71, FS 5ad6...)` triple.
`draw_body` replaces task/mesh with its generated VS before pipeline creation,
so the format exception became unreachable. The observed VS
`086551b608e12c6b` is exactly that mesh key XOR the generated-VS and coalesced
layout tags. Recognize that generated VS with its `memu == 2` provenance and
the same FS/two-target format guard. Both scalar and coalesced layouts work.
The user's chosen rate, VRS-off path, driver support, single-sample guard and
fallback remain intact. This makes existing VRS apply to a previously missed
pass; coarse shading can change fine pixel detail as the existing VRS choice
already permits. The complete pass cost is not a predicted saving.

The production C eligibility test covers the exact observed VS, both arena
layouts, native triplet, unrelated shaders, provenance, null stages and every
attachment format up to 184. Pipeline source guards retain the existing
VRS-off, driver capability, sample count and whole-pipeline/GPL restrictions.
No graphics-key size, prepared library or original shader bytes change.

A second experiment stably compacted private indexed triangle padding in place.
It passed exact ordered indices and arena guards on GPU (15564 -> 6487
synthetic triangles), then SAME-command-buffer compute->indexed indirect
raster with alpha blending and precise occlusion: pixels and all 473296
covered samples match (1025 -> 257 triangles). But its extra dispatch has
inconsistent software timing, including regressions. It is NOT integrated
or enabled in this APK. The reproducible source/tests are preserved on
`research/ocarina-index-compaction-20261113`, commit
`f571d0bc8ed3774a17317e9b3cf17dcc6b915ae3`. Do not resurrect it as a new
user-facing option or claim device gains from removed-index counts alone.


### Optional Qualcomm cave walls (2026-11-14, device validation pending)

Ported Banana Native `dc7c4203`'s `DM_VK_OQ_SPLIT_PASS` workaround
(`vka_exec.c`, issue #210): after an active samples-passed query in a
depth/stencil pass, close the query, publish the original counter segment,
then store/end the pass. The exact driver interaction remains unknown.
The new **Keep cave walls (Qualcomm)** setting is off by default, per-game,
reset with Restore defaults, requires restart, and is ignored on other
drivers/titles. The user's requested Portuguese label is also provided.

The port retains this fork's non-precise visibility queries, batched post-fence
readback/host reset and attachment-scoped pass-end dependencies. It adds no
GPU waits, forced query result fetches or unconditional full GPU barrier.
Eligibility is cached at query initialization; OFF performs no depth-pass
inspection at a report. Active-query and open-depth checks avoid empty or
colour-only splits, as upstream does. These are retained efficiency paths,
not evidence of lower Adreno GPU time: the expensive attachment store/reload
is still required by the known workaround. Do not claim that its high device
cost has been eliminated or replace it with an unverified barrier.

`test_ocarina_cave_walls.py` compiles and executes the production report
function through 64 live/off/depth/empty paths, checking publication state,
query-end -> post -> pass-end order and zero pass inspection when off.
In-game cave preservation and enabled-option frame cost require device tests.

The new `084355` log is Build151AB source `62b707e+dirty` on Adreno 840
891.14: at frame3000 p50 frame/GPU is 20.60/20.22 ms. Sample3001 has
12.63 ms graphics passes, 2.999 ms mesh compute and 0.466 ms task intervals.
Fragment-masked draw/channel counters remain zero throughout: the preceding
synthetic store elimination did not activate on this scene. Do not describe
that candidate as a measured gain. This run exports `DM_VK_VEGETATION=1`;
that is the recorded configuration of this file, not an assumption about
the user's separate vegetation-OFF comparisons.


### Cave-wall split cost and conservative visibility candidate (2026-11-14)

Build152 A/B uploads `091037` (ON) and `091132` (OFF), Adreno 840 /
Qualcomm891.14, show comparable ~2400 draws but radically different passes:

| Metric | Split ON, frame1200 | OFF, frame1800 |
| --- | ---: | ---: |
| Frame p50 | 33.29 ms | 20.52 ms |
| GPU p50 | 32.05 ms | 20.17 ms |
| Draws/frame | 2399 | 2405 |
| Passes/frame | 1835 | 149 |

The option is not cave-local: it splits after every counted depth query.
The ON sample saturates the 2048 timestamp slots before the frame ends, so
its profiler's 12.91 ms partial sum is NOT total GPU time or a speedup.
The ordinary-frame timing above is authoritative. Scoped dependencies alone
did not make per-query attachment store/reload inexpensive on this device.

**Candidate, device validation pending:** the existing optional setting now
requests `DM_VK_OOT_CAVE_VISIBLE=1`. For Ocarina on Qualcomm only, this avoids
the hardware query/depth interaction rather than flushing attachments at every
query. No query pool, GPU begin/end queries, query readbacks or query-driven
pass splits are generated. Visibility comparisons on these reports keep
drawing conservatively, including after fence completion. This may increase
overdraw; it is NOT exact sample-count emulation, nor a proven driver fix.

Guest CPU readers receive cumulative positive draw proxies, snapshotted at
the report and published by the original completion path. RESET resets this
value; reports do not. A constant1 was rejected because before/after reports
would compare equal and could falsely hide geometry. Skipped/unavailable
draws count positive too. Timestamp reports and explicit render-disable
remain independent. Reusing an occlusion address for a timestamp removes its
old conservative tag, rehashing collisions without losing other addresses.

OFF retains real-query behavior. `DM_VK_OCCLUSION=0` still explicitly selects
the old unsupported-query fallback. An advanced `DM_VK_OQ_SPLIT_PASS=1`
override selects the original measured wall-preserving split workaround,
even with the new opt-in on. The launcher emits split=0 by default. No new
user control, shader-chain change, resolution reduction or preparation.

Production-code tests execute reset/draw/report, deferred publication, both
render-condition modes, explicit disable, timestamp address reuse and 5000
colliding marker addresses. 1800 query pairs issue exactly zero GPU query
or split calls. Existing real-query order/batching tests pass. These checks
prove work elimination and counter/control-flow properties, not cave image
correctness or Adreno FPS: both must be tested on the affected scene.


### Build153 did not preserve cave walls (2026-11-14, confirmed failure)

User uploads `095119` and `095224` both identify source `34ac426`,
conservative visibility ON, split OFF, zero hardware queries. The user
reports cave walls disappearing/reappearing. The outdoor-like `095119`
settles at ~2394 draws,149 passes,GPU18.1ms/frame; `095224` has ~876-955
draws,117-120 passes,GPU15.1-15.6ms. Lower timings do not establish visual
correctness or an isolated query-removal speedup. No on-device query is
necessary for the reported flicker, so conservative visibility alone is
withdrawn as a claimed cave fix.

**Build154 candidate: depth synchronization at guest barriers.**
`vka_rp_game_barrier` previously discarded the meaning of `bits`, including
`NVN_BARRIER_INVALIDATE_ZCULL_BIT`, while retaining the barrier inside the
pass. The optional Qualcomm cave path now returns to the existing full
pass-end/attachment-store/barrier path for explicit ZCULL invalidation over
a depth/stencil attachment, and for primitive/fragment order requests after
that pass may have written depth/stencil. Read-only depth passes and
colour-only passes retain their fast path. Depth dirty state covers loadOp
clears, queued partial clears, in-pass clears and depth/stencil draw writes;
opening a pass resets it. No location heuristic or per-query pass split.

The source issue is concrete (barrier bits were ignored); whether respecting
these depth-cache boundaries fixes the proprietary-driver wall defect is
still a device-test hypothesis. It does NOT prove the root driver cause.
The uploaded traces show ~83-86 retained guest barriers/frame, rather than
~1800 reports/frame outdoors. The actual number selected for depth
synchronization is logged separately; no FPS or split-count guarantee.
Conservative guest counter behavior and query elimination stay as in153.
Legacy per-query splits remain available through the existing override.

Production C policy testing covers all256 bit masks across enabled/off,
pass, shader-write, attachment and depth-dirty states (32768 cases). An
ordered writer boundary is followed by1800 read-only barriers with only
one extra pass boundary; explicit ZCULL still forces a boundary. Tests
check dirty-state integration and the original full-order replay handoff.
These are policy/integration checks, not Qualcomm image validation.


### Clothes flicker since Build153; rollback and real-query candidate (2026-11-14)

The user reports that154 still fails and clothes have also flickered since
153. Both new logs (`101050`,`101146`) run154 with conservative visibility
ON. The depth-boundary rule actually runs (~8/frame in the cave-like run,
~21/frame outdoors), so its failure is not an unselected codepath. The clothes
observation is user-provided; logs are not a visual capture.

**Withdrawn:** remove153's proxy counters, permanent conservative visibility,
timestamp-address marker change, and154's added guest-depth boundary policy.
Restore152's real GPU query allocation/results/reset/publication and ordinary
render-condition evaluation. Do not report the18ms outdoor timing as success
while the picture is wrong. The temporal link to153 warrants rollback; it
is not proof that every garment/cave defect has one cause.

**Build155 candidate:** optional mode2 uses the existing cached classic passes
and a framebuffer-local depth dependency after ending the real query. The
render pass declares the same self-dependency (EARLY/LATE_FRAGMENT_TESTS,
depth/stencil READ/WRITE, BY_REGION). No layout transition, report-count
substitution, forced visibility, shader edit or new user control. Mode1
retains the original pass-split workaround; OFF uses the152 query path.

Do not weaken broader dependencies: shader writes, pending guest barriers,
pending clears or uniform uploads always fall back to the original split.
Unavailable classic/imageless support also falls back. Encoder serialization
is the existing vkCmdPipelineBarrier wrapper; its original worker ownership
and payload-copy regression passes. Logs separately count in-pass barriers
and split fallbacks. Classic render-pass compatibility is unchanged by the
added depth self-dependency; prepared shader libraries/ABI are unchanged.

**Validation:** Vulkan software ICD with Khronos validation compares192 real
precise queries (44zero,148positive), colour pixels and D32 depth bytes at
64x64 and960x540: exact match to the pass-split reference, including alpha
discard, depth writes, EQUAL colour passes and read-only queries. Reference
193 pass instances become1. Software GPU timing varies with warmup and is
not an Adreno FPS claim. Production query/report order tests cover original,
mode2 and fallback;256 production sync-guard cases keep broader dependencies
on the original path. Actual cave/garment correctness and phone cost remain
device validation, not a proven fix from these tests alone.


### Resume checkpoint after155 (2026-11-14, WORK IN PROGRESS, not an APK)

User confirms clothing is fixed by155, cave walls still flicker, and the
previous outdoor area lost FPS. Uploads `104838` and `104948` both run
`63d23dd` with mode2; outdoor frame1500 GPU23.37ms,149passes,2398draws,
1723.9in-pass barriers/frame and zero fallback splits. Thus the path
was selected and failed its visual/performance objectives. Keep REAL GPU
query results; never resurrect153 proxy counters/conservative visibility.

Current work restores152's ORIGINAL physical per-query pass ends, dynamic
rendering default, and launcher mode1. Mode2's auto-classic selection, local
barriers, self-dependency header and guard test are removed. Added only
observational colour/depth write flags and one summary per300frames; they
do not select any render path. Original query report/order test passes.
The observer classifies physical pass ends that bind unused colour targets
and passes without depth writes, to quantify future bandwidth work.

CRITICAL next validation: we have not yet received a cave capture on this
phone using152's original physical-split algorithm. Its device-specific
visual correctness must be established before claiming an optimized
equivalent. Upstream issue210 still documents no cheaper proven fix.

Independent research fixture `selftest/cave_query_gpu.c` now keeps EVERY
physical depth pass end but omits masked-out colour attachments for read-only
queries. It is TEST ONLY, not integrated into gameplay. The test compares
real precise query counts, colour and depth under Khronos validation.
Latest local run was still pending when this checkpoint was saved; check
`test_cave_query_gpu.py` results before calling it validated.

Remaining work: finish that GPU readback, test production observer wrapper
for exact original command order, run affected query/graphics tests, update
release marker to156 only after checks, compile signed APK on the original
branch and inspect Actions result/artifact. Tell the user original-mode
cave correctness is unconfirmed; do not call it a performance fix. Save
intermediate checkpoints to GitHub frequently as explicitly requested.
