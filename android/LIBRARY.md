# Swap2-Native: the game library

The flow the user set for Swap2-Native (2026-11-05), and where each step stands in this tree. One APK runs every game: there is no APK per game.

## The flow

1. The user opens the app.
2. They choose the folder their games are in (on the phone: `/sdcard/Switch2/Games`, one folder or `.nup` per game; [README.md](README.md#the-switch2-folder)).
3. Swap2-Native recognizes the games, makes a profile for each and downloads their covers.
4. The first time a game is played, its preparation runs (code rewrite, shader split and translation, android/ONDEVICE.md). A phone that should not translate the shaders imports them (the game's Options › Import shaders…, a zip from Export shaders… on another phone or `scripts/shaders_zip.py` on a computer): its preparation then only rewrites the code ([SHADERS.md](SHADERS.md#shader-zips)).
5. For each game the user can choose the version and the DLC, and either make a settings profile of its own (resolution, GPU driver, frame rate cap, ...) or use the general one.
6. The user can import and export saves.

## Status

| Step | State | Where |
|---|---|---|
| One host for every game | **Done, run on the phone (2026-11-05)**: Donkey Kong Bananza plays at 30 fps on the POCO F7 Ultra (Adreno 830) with Turnip Gen8 V32, its log says `game profile …/game_profile.tsv … read at start`; `libnxhost.so` reads the game's profile from its pack at start (`game_profile.tsv`, `dm/games/game.py runtime`); pack format 2 | `dm/host/rt`, `android/host/CMakeLists.txt` `NX_RUNTIME_PROFILE`, `scripts/pack_android.py`, `Native.java` |
| Profiles without an APK build | **Done, not run yet**: the Switch 2 profiles of `dm/games` are built in; any other game's profile folder goes in `/sdcard/Switch2/profiles/<title ID>/` (the launcher reads it, the packer gets `DM_GAMES_DIR`) | `Profile.java` `userDir` / `user`, `PackService.java` |
| 2. Choose the games folder | Exists: Add game takes a folder of several games and adds each (`MainActivity.addAll`). Missing: the folder kept as *the* library folder, with Refresh and Change folder (UI kit flow) | `MainActivity.java` |
| 3. Recognize games | Exists for games with a profile (title ID from `main.npdm`, `Pack.npdmOf`) | |
| 3. A profile for each game | Missing: a provisional profile made on the phone for a game without one (`dm/games/profile_guess.py` and `game.py`, which the embedded Python can run), written to `Switch2/profiles/<title ID>` | |
| 3. Covers | **Done, not seen on the phone yet**: the eShop icon by title ID from tinfoil.media (`/ti/<id>/512/512/`, else 256: Switch 2 titles answer 503 at 512), as the old runtime did (ae9a8a9 MKWDroidActivity.downloadCover); kept in `Switch2/covers/<id>.png`; drawn whole over a blurred copy in the card's wide cover area. Zelda: Ocarina of Time answers 503 at both sizes (asked again each run) | `Covers.java`, `MainActivity.card` |
| 4. Preparation at first Play | **Done, not run yet**: Add game adds a dump without a pack at once; its card's button is Play, which prepares first (Ondevice asks) and says so under the name | `MainActivity.java` (`added`, the card's problem branch) |
| 5. Version and DLC per game | Partly: Prepare takes the newest update (`pack_android.py --version`) and every DLC. Missing: the choice in the game's sheet | |
| 5. Settings profile per game | Exists: Game settings (resolution, frame rate cap, GPU driver, pause on return, extra environment), each "Default" = the general settings | `GameSettings.java`, `Prefs.java`, `GpuDriver.java` |
| 4. Shaders made elsewhere | **Done, not run on a phone yet (2026-11-07)**: the game's Options (in order after Prepare again) has Export shaders…, Import shaders…, Export full pack…, Import full pack…; Import shaders… puts a checked library into the pack (or `packs/<id>` with no pack yet) and Prepare skips its shader steps for it | `ShaderUi.java`, `ShaderZip.java`, `PackService.java` (`ShaderZip.ready`), `Job.shadersInPack` |
| 6. Import / export saves | Exists: Back up save, Restore a backup…, Import save from another emulator… (a .zip), Export save… (a .zip) (backups in `Switch2/save-backups/<title ID>`) | `SaveUi.java`, `SaveStore.java`, `SaveZip.java` |
| Look | **Done**: the home is the library of the concepts (header with Change folder / Refresh / Settings, Library and its count, the folder bar, a row of cover cards with badges, the selected game's bar with Play, gamepad hints), the empty library as its concept, in Portuguese on a Portuguese phone (`values-pt`); a compact layout for a phone held sideways | `MainActivity.java`, `Ui.java`, `res/` |
| Preparation screen | **To do (the GPT: interface)**: the user wants the preparation as a screen of its own, not a card in the library (2026-11-05), as assets/artwork/swap2-native/shaders/precompile-v2.html draws it. What it shows comes from the job, as `Ondevice.Panel` reads it today: `Job` (job.json: `state` running / paused / done / failed / pending, `step`, `statusText`, `overall()` 0..1, `shadersDone()` / `shadersTotal()`, `name()`, `version()`, `reason()`), kept current by `PackService`'s messages (bind with flags 0, `MSG_REGISTER`, then `MSG_STATE` with `job` and `alive`); actions `Ondevice.prepare`, pause / resume through the panel's `goOrPause`, Play when `ready`. There is no Skip: a game plays only with its pack | `Ondevice.java` (`Panel`), `Job.java`, `PackService.java` |

Found on the phone (2026-11-05): a dump of another build than its built-in profile's (Mario Kart World `main` 9e244438…, the profile's 1.8.0 is d00e4f39…) is added, then its Prepare is refused by the build check (DumpCheck). Step 3's profile for each game has to cover a known game at an unknown build too.

Open (2026-11-05): MIUI froze the whole app, its foreground Prepare service included, as soon as another app came to the front (every thread in `do_freezer_trap`; the job stood still 11 minutes until the app was brought back). Preparing in the background needs the app exempted from battery optimization (ask for it before Prepare) or the job kept in front.

Found on the phone (2026-11-05): the POCO F7 Ultra's own Qualcomm driver has no placed memory maps (`VK_EXT_map_memory_placed`), so the readiness check stops a game there; a Turnip for Adreno 8xx works (Turnip Gen8 V32 from the app's driver download; the old runtime used V37 from the same author). For the GPT: the selected game's bar cuts the version ("Atualização 45875" for 458752).
