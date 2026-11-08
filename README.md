# Swap2-Native

Play your own copies of Nintendo Switch 2 games natively on Android phones.

It is not an emulator: the game's own ARM64 code runs directly on the phone's CPU (rewritten only where Android's kernel requires it), a host answers the Switch 2's system calls and services, the game's NVN2 graphics commands are replayed on Vulkan, and its shaders are translated to SPIR-V, offline on a computer or on the phone itself. The app is `com.swap2native`; one APK runs every game.

Forked from Banana Native v0.1.1 by moceure, itself built on nxnative by seedds (MIT).

> [!CAUTION]
> Only download the app from this repository's [Releases](https://github.com/mamcjr/Swap2-Native/releases). Copies elsewhere are not made here.

> [!IMPORTANT]
> Experimental. Most of this code was written with AI coding assistants and tested by hand on two phones. Expect bugs, heat and slowdowns.

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
| RedMagic 11 Air | Snapdragon 8 Elite (Adreno 830) | used to prepare Zelda: Ocarina of Time (2026-11-07); driver not recorded |

Other phones are untested. Settings › **Readiness check** says what a phone lacks before a game starts (for example a driver without placed memory maps, which some Qualcomm drivers lack: Settings › GPU driver installs a Turnip).

## What you need

- Android 13 or newer on a 64-bit phone with a Snapdragon (Adreno) GPU and 12-16 GB of RAM.
- Your own game, dumped from your own console: a dump folder (`base/`, `updates/<version>/`, `dlc/<title ID>/<n>/`) or a `.nup` file ([android/NUP.md](android/NUP.md)). No keys or firmware are needed or used.
- Free space for the preparation: the dump is read in place; a game's pack and shader library take hundreds of MB to a few GB, and Prepare needs a few GB more while it runs.

## Install

1. Download the APK from [Releases](https://github.com/mamcjr/Swap2-Native/releases) and install it.
2. Open **Swap2-Native** and allow **All files access** (the app reads your games from shared storage).
3. Optional: Settings › **GPU driver** to pick the system driver or install a Turnip, and Settings › **Readiness check**.

## Prepare a game

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
- **Upscaling:** AMD FidelityFX FSR 1 for the final picture, and for agl's games (Zelda, Mario Kart World, Donkey Kong Bananza) FSR 1 in place of the game's upscaler network, which is faster on Adreno. Zelda can also draw its 3D scene at 720p.
- **Frame generation (LSFG):** Lossless Scaling's frame generation, with your own `Lossless.dll` (not included).
- On-screen controls with a layout editor, gamepads, exefs mods, save backups, pause on return, and a performance overlay.

## Known issues

- The phone gets hot, and the frame rate drops when it throttles.
- Some Android skins freeze the app in the background, which stops a preparation: exempt it from battery optimization or keep it in front.
- A new app version can need a game's shaders made again; the app says so and offers Prepare.
- Per-game issues are in each game's note (linked in [Games](#games)).

## Building

See [android/README.md, Build the APK](android/README.md#build-the-apk). Release keys are never in this repository.

## Credits and licence

- **[Banana Native](https://github.com/moceure/BananaNative)** by moceure: the direct upstream. Swap2-Native is a fork of its v0.1.1 (commit `d154da1`): the Android host and launcher.
- **[nxnative](https://github.com/seedds/nxnative)** by seedds (MIT), and everything it credits [below](docs/nxnative.md#acknowledgements).
- Mario Kart World findings from [kartnative](https://github.com/pahorema/kartnative) (pahorema) and [switch2mac](https://github.com/azmasm/switch2mac) (azmasm); task and mesh shader lowering from [Eglantine](https://github.com/djihads80/eglantine) via switch2mac; frame generation ported from [Eden](https://git.eden-emu.dev/eden-emu/eden) and [lsfg-vk](https://github.com/PancakeTAS/lsfg-vk); Zelda: Ocarina of Time findings from [Lichii](https://github.com/zortos293/Lichii) (ideas only).
- **AMD FidelityFX FSR 1** (MIT), [dm/third_party/fidelityfx-fsr1](dm/third_party/fidelityfx-fsr1/README.md).
- Other third-party code and its licences: [dm/third_party](dm/third_party/README.md).

The Android app is **GPL-3.0-or-later** as a whole ([android/NOTICE.md](android/NOTICE.md)); each release is built from its tagged commit. nxnative's own files keep their MIT licence ([LICENSE](LICENSE)).

Nintendo Switch, The Legend of Zelda, Mario Kart, Donkey Kong and Pokémon are trademarks of their owners; this project is not affiliated with or endorsed by Nintendo. It contains no game code, keys or assets: you need your own legally dumped games.

Problems: open an [issue](https://github.com/mamcjr/Swap2-Native/issues/new/choose) with the form. Questions and phone reports: [Discussions](https://github.com/mamcjr/Swap2-Native/discussions).

## Upstream

Swap2-Native keeps nxnative's Apple-platform code and tools (iPhone, iPad and Mac builds, Switch 1 games). Their documentation, nxnative's own README, is in [docs/nxnative.md](docs/nxnative.md).
