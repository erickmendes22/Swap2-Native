# Swap2-Native Ocarina — Android v0.1.6

A specialized Android fork of **[Swap2-Native](https://github.com/mamcjr/Swap2-Native)** by **mamcjr**, focused on *The Legend of Zelda: Ocarina of Time* (Switch 2 remake) and Snapdragon/Adreno devices. It retains the upstream native ARM64 execution, Switch services, Vulkan NVN2 replay and offline/on-device SPIR-V shader translation.

**Project lineage:** [mamcjr/Swap2-Native](https://github.com/mamcjr/Swap2-Native) → [Banana Native](https://github.com/moceure/BananaNative) by moceure → [nxnative](https://github.com/seedds/nxnative) by seedds.

The Ocarina-specific implementation is maintained on the [`ocarina-v11-ios-perf-from-v101` branch](https://github.com/erickmendes22/Swap2-Native/tree/ocarina-v11-ios-perf-from-v101). Other game profiles and inherited documentation are present in the source tree, but this v0.1.6 build primarily targets Ocarina.

> [!CAUTION]
> **These are not interchangeable APKs.** The original [mamcjr release](https://github.com/mamcjr/Swap2-Native/releases) uses `com.swap2native`. This Ocarina fork uses `com.swap2native.ootv11ios` and its own signing certificate. Install this fork separately; do not treat it as an in-place update of the original public app. Ocarina development APKs are published as [GitHub Actions build artifacts](https://github.com/erickmendes22/Swap2-Native/actions) until a public fork release is published.

> [!IMPORTANT]
> **Experimental software.** GPU-driver compatibility, rendering quality and performance vary by scene and device. VRS 4×2/4×4 can reduce image detail and are not guaranteed to outperform 2×2. No specific FPS target or crash-free gameplay is promised.

## Changes in this fork (v0.1.6)

Compared with the original **mamcjr/Swap2-Native** project:

- **Vulkan and GPU optimizations:** Ocarina-focused adjustments to graphics pipelines, render passes, barriers, uniform uploads, selected compute work, occlusion query handling and pipeline prewarming, with compatibility fallbacks.
- **Variable Rate Shading:** Optional **2×1, 2×2, 4×2 and 4×4** modes using driver-validated Vulkan rates. VRS is restricted to verified shader/pipeline cases rather than indiscriminately applied to all HDR shaders. The 2×2/4×2/4×4 modes share an expanded set of **17 identified fragment shaders**.
- **Internal resolution:** Separate Ocarina scene-resolution presets for **720p, 540p, 480p and 360p**, with the scene palette patched through a validated RomFS overlay; presentation upscaling is configured independently.
- **Upscaling:** FSR-based reconstruction plus an experimental **Snapdragon SGSR1** presentation path with supported fallbacks and selected reductions of redundant GPU upscaling work.
- **Shader preparation:** Incremental, per-shader recompilation and verified hot overlays; compatible builds preserve the existing **42,339-shader** base library instead of requiring a full recompilation. ABI/input checks protect against invalid reuse.
- **App experience:** Simplified performance settings, multilingual interface options, game-language selection where supported, and launcher/translation improvements.

These are changes in the **Ocarina branch**, not a claim that every optimization is absent from all newer upstream revisions. See the [original releases](https://github.com/mamcjr/Swap2-Native/releases) for the upstream baseline and the [branch history](https://github.com/erickmendes22/Swap2-Native/commits/ocarina-v11-ios-perf-from-v101) for implementation details.

## Games

The Legend of Zelda: Ocarina of Time is the focus of this fork. Status on the phone, from each game's note:

| Game | Title ID | Version | Status on Android |
|---|---|---|---|
| [The Legend of Zelda: Ocarina of Time](dm/games/0400486024DEC000/README.md) | `0400486024DEC000` | update v131072 | **In bring-up, gets into gameplay.** Opening and title movies at 60 fps; Link's house at about 30 fps (up to about 38 fps with FSR 1 in place of the game's upscaler network). Open: some UI text missing, an occasional process exit, the phone throttling |
| [Donkey Kong Bananza](dm/games/040074A01BF12000/README.md) | `040074A01BF12000` | update v458752 | **Plays**: about 30 fps on the POCO F7 Ultra with Turnip |
| [Mario Kart World](dm/games/0400C3F00006E000/README.md) | `0400C3F00006E000` | 1.8.0 | **In bring-up, not playable**: the game starts, then runs out of memory before its first frame |
| [Pokémon Pokopia](dm/games/0400A3A01EE4C000/README.md) | `0400A3A01EE4C000` | update v655360 (Ver. 2.0.1) | **Experimental**: the opening and the first walking scene, then it stops before the character comes out of a Poké Ball (open) |

A dump of another game build is refused by the build check, with a message that says which build the app needs. The [games table](dm/games/README.md#games) lists every profile in this tree, most of them nxnative's Switch 1 games for Apple platforms.

## Tested phones

| Phone | Chip | Tested with |
|---|---|---|
| POCO F7 Ultra | Snapdragon 8 Elite (Adreno 830) | Qualcomm system driver, or Turnip (Turnip Gen8 from the app's driver download) |
| RedMagic 11 Air | Snapdragon 8 Elite (Adreno 830) | used for early Zelda preparation in the upstream work (2026-11-07) |
| RedMagic 11 Pro | Snapdragon 8 Elite Gen 5 (Adreno 840) | Ocarina fork gameplay, Vulkan profiling and VRS 2×2/4×4 comparisons (2026-11-11) |

Other phones are untested. Settings › **Readiness check** says what a phone lacks before a game starts (for example a driver without placed memory maps, which some Qualcomm drivers lack: Settings › GPU driver installs a Turnip).

## What you need

- Android 13 or newer on a 64-bit phone with a Snapdragon (Adreno) GPU and 12-16 GB of RAM.
- Your own game, dumped from your own console: a dump folder (`base/`, `updates/<version>/`, `dlc/<title ID>/<n>/`) or a `.nup` file ([android/NUP.md](android/NUP.md)). No keys or firmware are needed or used.
- Free space for the preparation: the dump is read in place; a game's pack and shader library take hundreds of MB to a few GB, and Prepare needs a few GB more while it runs.

## Install

1. Get the Ocarina fork APK from this repository's [Actions](https://github.com/erickmendes22/Swap2-Native/actions) build artifacts (or this fork's [Releases](https://github.com/erickmendes22/Swap2-Native/releases) when available). Do **not** download the original mamcjr APK expecting it to be this build.
2. Open **Swap2-Native** and allow **All files access** (the app reads your games from shared storage).
3. Optional: Settings › **GPU driver** to pick the system driver or install a Turnip, and Settings › **Readiness check**.

## Prepare a game

New to the app? **Getting started** explains file selection and preparation. Open it from the empty library, Add game, or Settings → About. For a `.nup`, select the file itself; do not extract it. If Recent or Downloads cannot locate it, browse through Internal storage to its local folder. The app explains import failures and offers another selection without changing your dump.

Each game is prepared once: its code is rewritten for Android and its shaders are translated for Vulkan. The app does this on the phone ([android/LIBRARY.md](android/LIBRARY.md)):

1. Copy your dump (folder or `.nup`) into `/sdcard/Switch2/Games` on the phone.
2. In the app, choose that folder as your library. The app recognizes the games by title ID, uses the built-in profile for each and fetches its cover.
3. Tap **Play** on a game. The first time, it prepares the game first: code rewrite, shader split and translation. It runs in the background with a notification and can be paused; keep the phone charging and the app exempt from battery optimization. Nothing is uploaded. Zelda's 42,000 shaders take the longest.
4. When it is done, **Play** starts the game.

A phone that should not translate shaders can import them instead: the game's ⋯ › **Import shaders…** takes a zip made by **Export shaders…** on another phone, and Prepare then only rewrites the code ([android/SHADERS.md](android/SHADERS.md#shader-zips)).

### The Switch2 folder

| Folder | What |
|---|---|
| `Switch2/Games/` | your games: dump folders and `.nup` files |
| `Switch2/Work/<title ID>/` | a game's work folder: Prepare's working files, and a pack made on a computer (`android-pack`) |
| `Switch2/Mods/<title ID>/` | the game's exefs mods (IPS, IPS32, `.pchtxt`) |
| `Switch2/Shaders/` | shader zips from Export shaders… |
| `Switch2/profiles/<title ID>/` | a profile for a game the APK does not carry |

Prepared packs and saves stay in the app's own storage (`Android/data/com.swap2native/files/packs` and `saves`); a game's ⋯ menu backs saves up to `Switch2/save-backups/<title ID>/` and exports or imports them. Details: [android/README.md, The Switch2 folder](android/README.md#the-switch2-folder).

A pack can also be made on a computer with `scripts/pack_android.py` and copied to `Switch2/Work/<title ID>/android-pack` ([android/README.md, Pack a game](android/README.md#pack-a-game)).

## Features

- Game settings per game: resolution (phone 1080p, 720p or the game's own), frame rate cap, GPU driver, extra environment lines.
- **Upscaling:** AMD FidelityFX FSR 1, with experimental Snapdragon SGSR1 for the final image and safe fallback paths. Ocarina's internal 3D scene can use 720p, 540p, 480p or 360p independently of the final output filter.
- **VRS:** Vulkan fragment-shading-rate modes 2×1, 2×2, 4×2 and 4×4 where supported by the GPU driver; coverage is limited to identified pipelines, not all draws.
- **Shader cache:** verified incremental updates avoid repeating the entire Ocarina shader compilation when the existing library remains ABI-compatible.
- **Frame generation (LSFG):** Lossless Scaling's frame generation, with your own `Lossless.dll` (not included).
- On-screen controls with a layout editor, gamepads, exefs mods, save backups, pause on return, and a performance overlay.

## Known issues

- The phone gets hot, and the frame rate drops when it throttles.
- Some Android skins freeze the app in the background, which stops a preparation: exempt it from battery optimization or keep it in front.
- Compatible Ocarina updates reuse the completed shader library; changes to shader inputs or an incompatible ABI can still require selectively rebuilding the affected shaders.
- Per-game issues are in each game's note (linked in [Games](#games)).

## Building

See [android/README.md, Build the APK](android/README.md#build-the-apk). Release keys are never in this repository.

## Support the original project

The upstream **Swap2-Native** project is maintained by **mamcjr**. If you want to support the original developer, see [GitHub Sponsors](https://github.com/sponsors/mamcjr), [Ko-fi](https://ko-fi.com/mamcjr), or [Buy Me a Coffee](https://buymeacoffee.com/mamcjr). These are **mamcjr's** links, not donation accounts for this Ocarina fork.

## Credits and licence

### Original fork and foundational upstream work

- **[Swap2-Native](https://github.com/mamcjr/Swap2-Native) — mamcjr:** **direct base of this Ocarina fork**; Android launcher, game support, Vulkan runtime and upstream fixes. Original releases and documentation remain available at the linked repository.
- **[Banana Native / BananaNative](https://github.com/moceure/BananaNative) — moceure and contributors:** foundational Android native-host work and reference optimizations. mamcjr's Swap2-Native was itself derived from Banana Native v0.1.1.
- **[nxnative](https://github.com/seedds/nxnative) — seedds and contributors:** earlier underlying project (MIT); see its [additional acknowledgements](docs/nxnative.md#acknowledgements).

### Additional projects, references and research

- **AnkaNative — EddizEge and contributors:** upstream-related Android implementation work and technical references.
- **[Lichii](https://github.com/zortos293/Lichii) — zortos293 and contributors:** Zelda runtime, timing and optimization findings referenced during adaptation.
- **edennx-ocarina-ios — arcatafuriosa:** iOS Ocarina port and research used as a technical reference; Android features require their own implementation and verification.
- **[kartnative](https://github.com/pahorema/kartnative) — pahorema** and **[switch2mac](https://github.com/azmasm/switch2mac) — azmasm:** Switch 2 graphics/game compatibility findings.
- **[Eglantine](https://github.com/djihads80/eglantine) — djihads80:** task/mesh shader research referenced through switch2mac.
- **[Eden](https://git.eden-emu.dev/eden-emu/eden)** and **[lsfg-vk](https://github.com/PancakeTAS/lsfg-vk):** frame-generation integration references.
- **[VideoLAN dav1d](https://code.videolan.org/videolan/dav1d):** AV1 software-decoding library used by the inherited Android video path.
- **AMD FidelityFX FSR 1** (MIT), [bundled third-party source](dm/third_party/fidelityfx-fsr1/README.md); other dependencies and notices are in [dm/third_party](dm/third_party/README.md).

Credits distinguish the **direct upstream codebase** from **additional reference projects and technical findings**. Listing a project does not imply direct participation in or endorsement of this fork.

The Android app is **GPL-3.0-or-later** as a whole ([android/NOTICE.md](android/NOTICE.md)); nxnative's own files retain their MIT licence ([LICENSE](LICENSE)). Ocarina test builds are tied to their GitHub Actions source commits, while tagged releases should carry the corresponding source and notices.

Nintendo Switch, The Legend of Zelda, Mario Kart, Donkey Kong and Pokémon are trademarks of their owners; this project is not affiliated with or endorsed by Nintendo. It contains no game code, keys or assets: you need your own legally dumped games.

For issues specific to this fork, open a report in [this repository](https://github.com/erickmendes22/Swap2-Native/issues). For bugs in the original public build, use [mamcjr/Swap2-Native issues](https://github.com/mamcjr/Swap2-Native/issues). Include the game/build, device, GPU driver, selected resolution and VRS mode, and logs.

## Upstream

Swap2-Native keeps nxnative's Apple-platform code and tools (iPhone, iPad and Mac builds, Switch 1 games). Their documentation, nxnative's own README, is in [docs/nxnative.md](docs/nxnative.md).
