# Testing the launcher on a phone

The first test: install the launcher, put Donkey Kong Bananza's game folder and its pack on the phone, start it, and send back the log. This build replays the game's clears and presents on Vulkan but not its draws, so a good run boots the game's CPU side and logs its NVN calls with a mostly black screen and the newest log lines over it. Do [Test 2](#test-2-graphics-self-test) first: it needs no game. [README.md](README.md) explains the pieces; [PORTING.md](PORTING.md) what is still a stub.

On the Mac, with the phone on USB and USB debugging on. `D` is the dump folder and `W` the pack's work folder:

```sh
D=~/switch-dumps
W=$D/040074A01BF12000-work
```

## 1. Build what goes to the phone

```sh
$D/.venv-nxnative/bin/python scripts/pack_android.py $D/DonkeyKongBananza   # → $W/android-pack (about 60 MB); not needed when the phone prepares it (below)
android/ondevice/build.sh $W/packer                                             # once: the app's packer (stage)
cd android/app && ./gradlew -PnxPackStage=$W/packer/stage apk && cd ../..      # → android/app/out/swap2-native-test.apk
```

Without a pack from the Mac, the app prepares one from the dump on the phone: copy only the dump (step 3 without `android-pack`), then in step 5 **Add game** finds no pack and offers **Prepare** (about 30-45 minutes in the background, ONDEVICE.md). Kill it (`adb shell am force-stop com.swap2native.test`) or restart the phone halfway: **Resume** on the main screen goes on from the shader it had reached.

## 2. Install the APK

```sh
adb install -r android/app/out/swap2-native-test.apk
```

Or copy the APK to the phone and open it from Files (allow installs from that app when asked).

## 3. Copy the game folder and the pack

The phone keeps games in `Switch2/Games` and each game's work folder in `Switch2/Work/<title ID>` ([README.md](README.md#the-switch2-folder)); a pack made on the Mac goes into that work folder as `android-pack`. Only the parts the host reads are needed: `base/exefs` (the launcher reads the title ID from `main.npdm`), the update and the DLC. The base RomFS (8.7 GB) can stay on the Mac. About 9.8 GB in all:

```sh
G=/sdcard/Switch2/Games/DonkeyKongBananza; P=/sdcard/Switch2/Work/040074A01BF12000
adb shell mkdir -p $G/base $G/updates $P
adb push $D/DonkeyKongBananza/base/exefs           $G/base/
adb push $D/DonkeyKongBananza/updates/458752       $G/updates/
adb push $D/DonkeyKongBananza/dlc                  $G/
adb push $W/android-pack                           $P/
adb shell ls $G/updates/458752/romfs $P/android-pack/pack.tsv
```

Without adb: copy the same folders over USB file transfer (MTP) into `Switch2/Games` and `Switch2/Work/040074A01BF12000` at the top of the phone's storage. After a new pack, copy `android-pack` again; the game folder stays.

## 4. All files access

Open Swap2-Native and tap **Grant All files access**, then turn on "Allow access to manage all files" for Swap2-Native and go back. With adb:

```sh
adb shell appops set --uid com.swap2native.test MANAGE_EXTERNAL_STORAGE allow
```

## 5. Add the game

Tap **Add game** (the picker opens at `Switch2/Games`), open `DonkeyKongBananza`, and tap **Use this folder** (allow access when asked). The launcher finds the pack in `Switch2/Work/040074A01BF12000/android-pack` (or any `Work/<title ID>/<name>/` or older `<title ID>-work/<name>/` with a `pack.tsv` in the game's folder or up to three folders above it, `PackFind`) and lists "Donkey Kong Bananza (040074A01BF12000)" with no question when the pack fits (the dump's game build, this APK's shader library, or an older library the automatic shader update brings current). Without one it offers **Prepare** (above), **Use an existing pack…** or **Import pack…**. Picking `Switch2` or `Switch2/Games` adds every game in it (each `.nup` and dump subfolder, and those of `Switch2/Games`) and says in one message what was added, what this app cannot run and what needs Prepare.

With adb, adding and starting it in one step:

```sh
adb shell am start -n com.swap2native.test/dev.nxnative.android.MainActivity --es game /sdcard/Switch2/Games/DonkeyKongBananza --ez run true
# any app (files/saves/<id> by default): --es save <folder> names the save folder, as Folders does, so a test run never opens the user's save
adb shell am start -n com.swap2native.test/dev.nxnative.android.MainActivity --es add_game /sdcard/Switch2   # Add game's own path for a picked folder or .nup: all its games, one summary
```

## 6. Start it and watch the log

Start the log on the Mac first, then tap the game:

```sh
adb logcat -c && adb logcat -v time Swap2Native:V DEBUG:V libc:V '*:S' | tee nxnative-logcat.txt
```

The screen stays black with the last log lines at the bottom. Give it a minute: the stages below come within seconds of each other on the Mac. Back asks whether to stop the game; stopping ends the game's process and the launcher stays.

**On-screen controls.** With no gamepad connected, a semi-transparent Pro Controller is drawn over the game: the left stick high and the D-pad low on the left, A / B / X / Y high and the right stick (the camera) low on the right, ZL / L and R / ZR in the top corners with − and + next to them, and small L3 / R3 (stick clicks) beside the sticks. They sit in the black bars beside the 16:9 picture as far as they fit. Several fingers work at once; each press gives a short tick (when the phone's touch vibration is on). A touch that starts on a control drives only the control; touches elsewhere in the picture are the game's touchscreen. The small round button at the top centre hides or shows them (crossed out while hidden); hold it for the settings: opacity, size and the tick, kept for the next run. They hide by themselves when a gamepad connects and come back when the last one goes. The log says `[nxlaunch] on-screen controls: 15 in a 2420x1080 view …` and `[dm] input: on-screen controls: 15, the launcher's layout`.

## 7. Send the log back

Tap **Share log** in the game list (it sends the newest run's log), or pull every log:

```sh
adb pull /sdcard/Android/data/com.swap2native.test/files/logs/
```

If the game crashed, also send `nxnative-logcat.txt` (it has the phone's own crash report, a `DEBUG` backtrace) or `adb logcat -d -b crash`.

## What the log says at each stage

Each line below starts with `[nxlaunch]` (the launcher) or `[dm]` (the host). The first stage whose line is missing is where the run stopped; the last lines before that say why.

| Stage | Line | It means |
|---|---|---|
| 1 Launcher | `[nxlaunch] env DM_ROMFS=/storage/emulated/0/Switch2/Games/DonkeyKongBananza/updates/458752/romfs` and the other `env` / `arg` lines; `hooks: window yes, input yes, lifecycle yes` | the game process started and passed the folders |
| 2 Host started | `[nxlaunch] nxhost_main starts on its own thread (8 MiB stack)`, then `[dm] build: commit …, shader chain …, profile 040074A01BF12000` | `libnxhost_<title ID>.so` loaded and its crash handlers are in place behind ART's |
| 3 Thread slots | `[dm] thread slots: tpidr_el0 + 0x10 → K18 +0 KTLS +8 KTLR +0x10 KGATE +0x18` | the host's slot block sits in Bionic's `TLS_SLOT_APP`; `FATAL … TLS_SLOT_APP … another library uses the slot` or `thread slot layout mismatch` stops here |
| 4 Loader done | `[dm] main: gates … keys 0/1/2/3`, `[dm] sdk: gates …`, `[dm] main: base 0x… size …`, `reloc …`, `force: … entries hit`, `[dm] sdk: NintendoSDK nnSdk-…`, `[dm] stubs=…` | both modules mapped, relocated and their code made executable; `FATAL open …` names a file missing from the pack |
| 5 First guest code and SVCs | `[dm] >>> nnosInitialize`, then `[dm] guest AS 0x4000000000 +0x270000000  heap … alias … stack …` | the game's own code runs and its first memory SVC reserved the 9.75 GiB guest block at the expected address (`guest block: … was taken, reserved at …` is fine; `[RED] guest block` is not) |
| 6 SDK start-up | `[dm] >>> nninitInitializeSdkModule`, `[dm] >>> nninitStartup`, `[dm] >>> nnMain` | the SDK initialised and the game's `nnMain` runs: guest threads, the heap and file reads from the RomFS work |
| 7 First NVN call | `[dm] [nvn] device API …` | the game asked for NVN and initialises its device |
| 8 NVN up to the first frame | `[dm] [nvn] init 0: … functions … calls \| …`, then more `[dm] [nvn] frame …` lines (each early frame, then every 300th) | the game's NVN calls up to its first present, and its frame loop runs (the presents reach the stubs) |

Expected on the way, not failures: `[RED] vk: draw not yet on Vulkan` and the other `[RED] vk:` lines for what the replay does not do yet ([PORTING.md](PORTING.md#stubs-in-this-build)), `[RED] … not yet on Android` lines for the remaining stubs, and `UNIMPL …` lines for SDK calls the host stubs, which also appear on the Mac.

A crash prints `[dm] CRASH sig=… pc=… lr=…` with module offsets (`main+0x…`), the registers, a backtrace, a stack scan and a dump of every thread, and then the phone's own report in logcat (`F libc : Fatal signal …`, `F DEBUG : backtrace:`). `FATAL …` is the host stopping on purpose with its reason.

## Saves

A game's save is in the app's own storage (`AppStorage`, as Eden keeps its user folder): `/sdcard/Android/data/<app>/files/saves/<title ID>/`, its device save `saves/<title ID>_device/` beside it. Each installed package (the test build `com.swap2native.test`, a `-PnxApp=<suffix>` build `com.swap2native.<suffix>`, the play and release apps `com.swap2native`) has its own. A save folder picked in the game's ⋯ › Folders is used as it is instead. Android deletes the app's storage with the app; the manifest's `hasFragileUserData` makes uninstalling ask whether to keep it. **Back up saves** writes to shared storage (`/sdcard/Switch2/save-backups/<title ID>/`, below), which an uninstall never touches.

Up to 0.1.0 the default was on shared storage, beside the game (the folder holding the game folder or the `.nup`, `/sdcard/Switch2`; for a game now in `Switch2/Games`, the folder above it):

| App | Old default save folder |
|---|---|
| play and release | `/sdcard/Switch2/saves/<title ID>/` |
| test | `/sdcard/Switch2/saves-test/<title ID>/` |

**The one-time copy** (`SaveMigrate`, `GameActivity.defaultSave`): at a game's start, when no save folder is picked, the app's save has no file and the old default has a save, the old save (and its `_device`) is copied into the app's save under both saves' locks: into a staging folder `saves/.<title ID>.migrate/` first, checked file by file (path, size, SHA-256) against the old save, the old save scanned again, then renamed into place (the device save first, the main save last: the main save appearing is the commit). The app records it per title (`save_migrated@<title ID>`), shows a toast, and the log says `[nxlaunch] save: <app save> (existing); copied once from <old folder> (n files, size, checked); that folder is kept as it was`. The old folder is never written, moved or deleted (only its `<folder>.lock` beside it is taken, as before). A copy is never made over an app save that has a file. When the copy fails (or the old save has an unfinished commit), nothing half is played: that start uses the old folder, as 0.1.0 did, with a toast and `save: … not copied into the app's storage (<why>)`; the next start tries again. Until the copy is made, ⋯ › Folders, **Back up** and **Restore** show and use the old folder; afterwards Folders says where the save is and where it came from.

After that, an empty app save is filled from the private save of the first versions (`files/save/<title ID>`, kept), else from the seed `/sdcard/Switch2/save-seed/<title ID>/`, a save that reaches the first level. The log's `[nxlaunch] save: <path> (migrated|seeded|existing|new)` says which. If the folder cannot be created, the private folder is used and the log says so.

Each game has its own save folder, `DM_TEMP` (`files/temp/<title ID>`: pipeline cache, prewarm list), DLC links (`files/aoc/<title ID>`) and logs (`files/logs/<title ID>-<time>.log`, 10 kept per game); `env.txt` applies to every game, `files/env-<title ID>.txt` (written and `chmod 666`ed like `env.txt`) to one.

**Test agents** start from the seed: give the run its own save folder (a copy of the seed: `--es save <folder>` on the launcher's intent, or `DM_SAVE=` in `env-<title ID>.txt`, below) rather than deleting anything; never delete or overwrite the user's save folders (`Switch2/saves*`, `save-backups`, the apps' `files/saves`). To test the one-time copy, copy the seed into `saves-test/<title ID>` beside a game folder or `.nup` of your own (a new folder, say `Switch2/apptest/`; a `.nup` copies on the phone in seconds) and add that game with `--es game`. Update the seed with `adb push <save folder> /sdcard/Switch2/save-seed/` (the folder is named by the title ID). Saves are private data: never commit them.

### Packs in app storage

Prepare writes a new pack into the app's `files/packs/<title ID>/` (the job's working files stay in `Switch2/Work/<title ID>/ondevice`, or in an older `<dump>/../<title ID>-work/ondevice` until the launcher has moved it). A game's pack is looked for in the folder picked in Folders, then in `files/packs/<title ID>`, then beside the game (`Switch2/Work/<title ID>/android-pack`, `<title ID>-work/android-pack`, `Pack.find`), then in `Work/<title ID>/<any name>`, `<title ID>-work/<any name>` and `android-pack` of the game's folder and up to three folders above it (`PackFind`; the first that fits, else the first an automatic shader update brings current; never one of another game build): packs from earlier versions or a Mac keep working and are updated in place (restamp, shader updates), never copied. Tests: `python3 dm/tools/tests/test_android_packfind.py` (the finder and the folder scan, `Switch2/Games` and `Work/<title ID>` too) and `python3 dm/tools/tests/test_android_switch2_layout.py` (the launcher's move of the Switch2 folder into `Games/`, `Work/`, `Mods/` and the repointed paths: [README.md](README.md#the-switch2-folder)).

A game's ⋯ Manage sheet has **Export pack…** and **Import pack…** (`PackUi`, `PackZip`). Export writes the pack as one stored zip, `swap2-pack-<title ID>-<version>.zip`, into a picked folder (`<name>.partial`, read back entry by entry against the pack's files, then renamed; a name taken gets `-2`). Import takes such a zip (pack.tsv at its root or in its one top folder) or a pack folder: its title must have a profile in this APK and be the sheet's game; it is unpacked into `files/packs/<title ID>.partial` (an entry named outside it, `..`, an absolute path or a backslash, refuses the whole zip before anything is written), checked (`Pack.read`, finished code, a shader library of some version, `PackCheck.blocking` against the game folder), and only then swapped in: the pack that was there is kept as `<title ID>.replaced` until the new one has its name (a stop between the renames is put back by `PackZip.recover`). The card then uses it; a picked pack folder is let go (kept on the storage). An older library goes through the usual restamp or shader update. Both refuse while the game runs.

Without the pickers (test app only): `adb shell am start -n com.swap2native.test/dev.nxnative.android.MainActivity --es pack_title <title ID> [--es pack_game <game folder or .nup>] --es pack_export <folder>` (or `--es pack_import <zip or pack folder>`) runs the same for the listed game of that path (else the first of that title). Tests: `python3 dm/tools/tests/test_android_packzip.py` (round trip, zip slip, wrong titles, damaged packs, the swap).

### Preparation failures

The simulated engine (`-PnxPackEngine=fake`) fails on purpose with `NX_FAKE_FAIL` in the job's `ondevice/env.txt` (read before each step's preflight):
`nospace` (the tools' unpack reports a full disk: the job fails `nospace`, its card says Try again with the free and needed space, its screen has Free up
space), `tools` (the unpack fails: `tools`), `kill` (the process ends itself as a step starts: the next launcher start resumes the job, and two kills in one step
fail it `killed`), or a tool's name (that tool fails halfway: `step`). A job.json left with a step `running` by an older APK reads as pending once the job is not
running. The decisions themselves are tested on the JVM: `python -m unittest dm.tools.tests.test_android_game_flow`.

### Shader zips

A game's Options (and its settings' Preparation) has **Export shaders…** and **Import shaders…** (`ShaderUi`, `ShaderZip`, [SHADERS.md](SHADERS.md#shader-zips)). Without the pickers (test app only): `adb shell am start -n <package>/dev.nxnative.android.MainActivity --es shaders_title <title ID> [--es shaders_game <game folder or .nup>] --es shaders_export <folder>` (or `--es shaders_import <zip>`) runs the same for the listed game of that path (else the first of that title), with its progress dialog and result. After an import into a game with no pack, Prepare's job logs `split: the pack … holds this app's shader library (v-<V>): skipped, nothing is translated` (logcat `nxpack`) and its `job.json` has `"shaders_imported": true`. Tests on the computer: `python3 dm/tools/tests/test_android_shaderzip.py`.

### Save backups

A game's ⋯ Manage sheet has **Back up save**, **Restore a backup…**, **Import save from another emulator…** (a .zip) and **Export save…** (`SaveUi`, `SaveStore`, `SaveZip`). The save is `DM_SAVE` and, for a game whose main imports both `MountSaveData` and `MountDeviceSaveData`, its device save `<DM_SAVE>_device` beside it (`hle_fs.c` `h_fs_MountDeviceSave`; of the Switch 2 games here neither Donkey Kong Bananza's main nor Mario Kart World 1.8.0's imports `MountDeviceSaveData`, so both have the main save only). A backup holds both: `/sdcard/Switch2/save-backups/<title ID>/<yyyyMMdd-HHmmss>/main/` and `device/`, with a manifest `<name>.manifest.tsv` beside it (the layout, the source folder, then one line per file: SHA-256, size, path). The play and the test app share that folder; the list shows which save folder a backup came from. The app never deletes a finished backup (delete old ones with a file manager or `adb shell rm -r`).

- **The lock**: every backup, restore and recovery holds `<save>.lock` (`FileChannel.lock`). A game start takes it before the save is used and keeps it while its process lives (the kernel lets it go when the process ends, also after a crash), so **Back up** / **Restore** say "is running" exactly while that game runs, and a failed start (no host for the game, a save in use, any start error) ends its `:game` process at once instead of leaving it idle with a host loaded. Play on another game while one runs is answered by the running game ("stop it first"), one game at a time.
- A backup without a device save is not restored into a save that has one (the two parts would not belong together); an app backup always holds both.
- **Back up**: the save (both parts) is copied into `.partial-<name>/`, each file synced; the copy is compared with the save file by file (path, size, SHA-256) and the save is scanned again (a save that changed during the copy fails); the manifest is written, then the folder gets its name. Older than a day, at the next backup: a `.partial-*` folder that matches the manifest beside it (stopped just before its rename) gets its name; other `.partial-*` folders and manifests without their folder are removed (never a finished backup). The save is only read.
- **Import** takes a .zip (`SaveZip`): listed first (by its central directory when it has a path, else read once as a stream, 4 GB at most), every name checked (no absolute path, no `..`, no name twice in any case), this game's save found in it (a folder named the title ID in any case holding files, not below `load/`, `shader/` and other non-save folders, those below a `save` folder and the newest first; the yuzu family's device save, `save/0000000000000000/00000000000000000000000000000000/<TITLE ID>`, never one but the device save of the users' saves beside it; else the zip's top-level files, or its one top folder (a Ryujinx save folder, `0/` with `1/` beside it, gives its `0/`), neither taken when it holds `nand/`, `sdmc/`, `bis/`, `keys/`, a `.keys` file or a folder named by a 16- or 32-hex ID; `<part>_device` beside it, even empty, is the device save), and only that part extracted into `<save>.import` beside the save, under the save's lock, at most 10,000 entries, 512 MB a file and 1 GB in all, checked while it is written; the restore below then takes it, and the staging folder goes (one left by a stop goes at the next launcher start or game start). **Export** writes `<TITLE ID>/` and `<TITLE ID>_device/` into `swap2-save-<TITLE ID>-<time>.zip.partial`, reads it back with the importer (the same part, every file's SHA-256 and size), checks the save did not change, then names it; a `.partial` of this game left by a stopped export goes at the next export into that folder.
- **Restore / Import**: refused from the save itself, from inside it, from a folder holding it, and from its working folders (`<save>.restore`, `.new`, `.re`, `.work`, `.old`), compared by canonical paths. The source is checked against its manifest (a backup whose files no longer match is refused as damaged; an import's staging folder has none, and its `<folder>_device` beside it, if any, is its device save); a current save with anything in it is backed up first as `<time>-before-restore` (checked; when that fails, nothing else happens); each part is copied into `<part>.restore` beside its target and checked; then the set file `<save>.restore-set` names the pairs, each part gets `<part>.pend1` (naming its copy, fsynced), the set file goes, and each part is swapped in under the host's roll-forward journal (`plat_android.c` `plat_rename_swap`: FUSE has no `RENAME_EXCHANGE` and no xattrs): stage 1 deletes what the part has and the copy lacks, `.pend2` replaces `.pend1`, stage 2 renames the copy's files over the part's (each rename atomic), the markers go. A kill before the set file leaves the save as it was; after it, the next backup, restore or game start finishes it (`SaveStore.recover`), so both parts are the old version or the restored one. The final check compares names without case (shared storage is case-insensitive).
- **The journal's rules** are the same in the launcher (`SaveStore.recover`) and the host (`plat_swap_recover`, at each mount): a legacy `<save>.old` comes back when the save is missing and goes when it is there; an empty marker is dropped and the next one looked at; a marker naming anything but `<save>.new`, `<save>.re` or `<save>.restore` (same folder, by real path) is refused, and so is `.pend1` whose folder is gone (stage 1 would empty the save): the save and the marker are left as they are, the host logs `[RED] save swap journal …`, and the launcher refuses the start with the reason (move the marker away to use the save). Stage 2 runs only once `.pend1` is deleted and the folder synced (also when recovery finds both markers), so a second stop can never leave `.pend1` beside an emptied copy; such a `.pend1` from older builds (its folder holds no files while the save does) is dropped with its empty folder, the save staying as it is.
- Tests: `python3 dm/tools/tests/test_android_saves.py` runs `SaveStore`, `SaveMigrate` and `Profile` on the Mac's JVM (`android/app/src/jvmtest`): the one-time copy (copied and checked, never over an app save, the old folder unchanged, a failed copy leaving no save to play from and copied whole at the next start, an old save with a journal or in use left alone), backups (main and device), restores with their automatic backup, a damaged backup refused, swaps stopped after the set file, after `.pend1` and inside stage 2, each journal rule, the lock held by another process, refused sources, stale leftovers, canonical paths and the case-insensitive check; and it compiles the host's journal code from `plat_android.c` for the Mac and recovers the same stopped states with both, which must leave the same files.
- On the phone: back up, play a little and save, restore the backup and check the game loads the older save; `ls /sdcard/Switch2/save-backups/<title ID>/` shows both backups.

## Pause and background power

Press Home with the game running, wait, open it again: the log has `[lifecycle] background: … since the last pause or resume …` and, coming back, `[lifecycle] foreground: … in <s>` with the threads' CPU over the whole background stay (it should be a few tens of milliseconds a minute; any thread named there with real time is a busy loop to look at), then `[lifecycle] foreground, paused: the game waits for a tap`. The screen shows "Paused"; a tap logs `[lifecycle] continued: …`. The in-game panel's **Pause the game** does the same without leaving. With `DM_WATCH_STALL` set, a long pause must not end in `[RED] watchdog`.

## Diagnostic switches

A file `env.txt` in the app's folder adds `KEY=VALUE` lines to the host's environment for the next run, as `Documents/env.txt` does on the iPhone. For example:

```sh
adb shell 'f=/sdcard/Android/data/com.swap2native.test/files/env.txt; printf "DM_SVC=1\nDM_THR=1\nDM_WATCH_STALL=20\n" > $f; chmod 666 $f'
adb shell rm /sdcard/Android/data/com.swap2native.test/files/env.txt     # back to a normal run
```

**Paths stay the launcher's.** Lines of `env.txt`, `env-<title ID>.txt` or a game's own lines (Game settings) that set `DM_SAVE`, `DM_ROMFS`, `DM_TEMP`, `DM_ROOT`, `DM_AOC_DIR` or `HOME` are not taken: the game shows a message and the log has `[nxlaunch] [RED] env: not taken: …`. One exception, in the **test app only**: `DM_SAVE=<folder>` in `env-<title ID>.txt` (never `env.txt`, which every game reads) runs that game on that folder (a copied seed, for test runs that must not touch the app's own save), locked and recovered like any save, never migrated into or seeded; the log says `[nxlaunch] test app: DM_SAVE from env-<title ID>.txt: <folder>`. The play app ignores it with the same `[RED]` line.

The `chmod` is needed: a file `adb shell` writes there belongs to the shell user, readable only by its group, which the app is not in; without it the run goes on with no switches and the log says `[nxlaunch] [RED] env.txt: … exists but cannot be read`. The log lists each switch the host got as `[nxlaunch] env KEY=VALUE`.

**agl's NDSR network off, FSR 1 in its place** (Zelda: Ocarina of Time; [rendering.md](../docs/reference/rendering.md#agls-ndsr-upscaler-network-replaced-by-fsr-1-easu-on-the-vulkan-replay)): `DM_VK_NDSR=fsr` (or `bilinear`) runs FSR 1 EASU in the network's dispatch slot, `DM_VK_NDSR_INPUT=sqrt` for agl's light upscaler (its input holds sqrt(colour)), `DM_VK_NDSR_LOG=1` logs agl's push bank once per size, `DM_VK_NDSR_MAP=push` maps through it (unconfirmed). All live: `nxctl.sh env DM_VK_NDSR=net` / `=fsr` switches between the network and the stand-in in a running game, and `android_replay.py --env DM_VK_NDSR=fsr --env DM_VK_NDSR_INPUT=sqrt run <capture>` gives the stand-in's PNGs for an A/B against the network's. The log says `[vk] NDSR network <key> replaced by FSR 1 EASU (input sqrt, full-image mapping, <in> -> <out>; …)`, or `[RED] vk: NDSR network <key> not replaced …` with the reason. A game's scene size can be set from its own data with a RomFS overlay: `dm/tools/gsys_dynres.py` writes a gsys game's dynamic resolution palette with one scale (`--scale 0.625`: a 2048x1152 output draws its scene at 1280x720) into an overlay folder, which `DM_ROMFS_OVERLAY=<folder>` lays over the RomFS at the next start (the log's `fs` lines; the folder on the phone, for example `/storage/emulated/0/Switch2/Work/<title ID>/romfs_overlay_720p`). The launcher sets both for a game whose Game settings choose them: **Upscaler** FSR 1 gives `DM_VK_NDSR=fsr`, and every start of a game with agl's NDSR networks gets `DM_VK_NDSR_INPUT` from its profile's `ndsr_input` (Zelda: `sqrt`), so a hand-written `DM_VK_NDSR=fsr` takes the right input; **Scene resolution** 720p gives `DM_ROMFS_OVERLAY=<external files>/overlay/<title ID>/scene_720p` (made on the phone by `gsys_dynres.py` with the profile's `scene_scale_palette`, `SceneService`; its run's log is `overlay/<title ID>/scene_720p.log` beside it), or, when that overlay was made for another pack version, nothing and `[nxlaunch] Scene resolution 720p: the overlay ... was not made for this pack` as a `[RED]` line. The log's `[nxlaunch] env` lines show what a run got; lines of `env.txt`, the game's own lines and `env-<title ID>.txt` win over the settings (`DM_VK_NDSR=net` for an A/B with the Upscaler on FSR 1; for the scene, Game default in Game settings).

`DM_SVC=1` logs the memory SVCs, `DM_THR=1` the thread SVCs, `DM_FS=1` file opens, `DM_NVN_LOG=1` NVN objects, `DM_WATCH_STALL=<s>` dumps every thread when the game stops making progress for that long ([03-bringup.md](../docs/agents/03-bringup.md)).

## Frame capture and replay on the phone

A graphics test that boots the game and plays into the first level takes 1–3 minutes. Instead: capture one level frame once, then replay it on the phone without the game, as often as needed, in about half a minute a run (a tenth of a second of it the frame itself). The replay runs the current build's NVN → Vulkan replay (`dm/gfx/vk_android`) on the frame's recorded commands, pool memory and textures, and reports the CPU recording time, the GPU time and the picture.

- **Capture** (in the game, `vka_capture.c`): `DM_NVN_CAPTURE=@<seconds>:1:<path>` in `env.txt` captures the first frame that starts after that many seconds of the run (`<frame>:1:<path>` a frame number, as on the Mac: [docs/development.md](../docs/development.md#frame-capture-and-replay)). `DM_NVN_CAPTURE=passes>=<n>[@<seconds>]:1:<path>` captures from the first submission (after that many seconds) whose command lists hold at least n render target bindings (`SetRenderTargets` records, calls and jumps followed) up to the next present: a frame that renders more than the others, whichever frame number it falls on. The capture then starts at that submission, and what the frame's earlier submissions drew is read back as GPU content. Each submission with more bindings than any before is logged (`a submission before present N has K render target bindings, the most so far`), which shows the threshold to pick. It writes the file (about 3.2 GB for the tunnel: 2.65 GB of pool memory, 490 MB of render targets and other GPU-only images, the frame's 4 submissions) and `<path>.live.png`, the presented image; the run goes on afterwards. Captures are game data: they stay in `/sdcard/Switch2/Work/040074A01BF12000/captures/` (or the work folder on the Mac), never in the repository.
- **Replay** (`nxreplay`, `vka_replay.c`): an executable run from `adb shell` as the shell user, with `libnxhost.so` beside it in `/data/local/tmp/nxreplay` (no APK install; the app is not touched). It reads the capture and the pack's shader library from `/sdcard`, keeps its own pipeline cache beside it (seeded once from the app's), and writes PNGs beside the capture.

Hold the phone lock (`android/HANDOFF.md`) for both: the capture runs the game, the replay uses the GPU and 6 GB of memory.

### Capturing a level frame

A fresh copy of the seed save (a save at the first level: [Saves](#saves)), given to the run as its own save folder, reaches the mining tunnel with A pressed every 2 s; at 100 s the camera is in the tunnel:

```sh
a() { adb "$@"; }
F=/sdcard/Android/data/com.swap2native.test/files/env.txt
S=/sdcard/Switch2/saves-run-$(date +%m%d%H%M); a shell cp -r /sdcard/Switch2/save-seed/040074A01BF12000 $S   # a fresh level-1 save of its own
K=$(python3 -c "print(','.join('%d:A'%t for t in range(15,90,2)))")
a shell "printf 'DM_WATCH_STALL=25\nDM_KEYS=$K\nDM_NVN_CAPTURE=@100:1:/storage/emulated/0/Switch2/Work/040074A01BF12000/captures/tunnel.nvncap\n' > $F"
a shell am start --user 0 -n com.swap2native.test/dev.nxnative.android.MainActivity --es game /storage/emulated/0/Switch2/Games/DonkeyKongBananza --es save $S --ez run true
# about 2 minutes; the game log (files/logs/, newest) ends the capture with
#   [dm] DM_NVN_CAPTURE: frame 2673: 4 submits, 1052 segments, 2147 regions, … 3170.6 MB in 15969 ms → …/tunnel.nvncap; live digest 0640c5… (2880x1620 VkFormat 37)
a shell am force-stop --user 0 com.swap2native.test
a shell "printf 'DM_WATCH_STALL=25\n' > $F"                          # restore env.txt
```

The capture takes about 16 s inside the frame (each step waits for the GPU and writes the pool bytes); the game then carries on. `[RED] DM_NVN_CAPTURE` lines say what was not captured. Registered textures whose storage is in no live pool (133 in the tunnel: their pools were finalized while they stayed registered) are written without storage; their images' content is captured by serial. A capture only replays on a build with the same record layout (`nvn_obj.h`) and, for each program, a shader library with the same binding records; otherwise the replayer stops with a `[RED] nxreplay:` line that says to capture again.

### Replaying it

`dm/tools/android_replay.py` builds the replayer (CMake with the NDK, into the work folder's `replay-agent/build`; `--build <dir>` for another), pushes it and runs it:

```sh
python3 dm/tools/android_replay.py build            # libnxhost.so + nxreplay (about 1 min the first time, seconds after a change)
python3 dm/tools/android_replay.py push             # → /data/local/tmp/nxreplay
python3 dm/tools/android_replay.py run tunnel.nvncap --warm 3
python3 dm/tools/android_replay.py --env DM_VK_NANSCAN=1 run tunnel.nvncap --warm 2   # a switch for the replay (the live run's DM_* switches apply too)
python3 dm/tools/android_replay.py pull out/        # the PNGs beside the captures
```

A capture name without a `/` is looked up in the captures folder. By hand: `adb shell 'cd /data/local/tmp/nxreplay && LD_LIBRARY_PATH=. ./nxreplay /sdcard/Switch2/Work/040074A01BF12000/captures/tunnel.nvncap --warm 3'`. Options:

| Option | What |
|---|---|
| `--warm n` | n replays in one process, each after the one before: the first builds images and pipelines, the later ones show the steady state (use these for timing) |
| `--repeat n` | n replays, each in a fresh process |
| `--png <path>`, `--no-png` | where the presented image goes (default `<capture>.replay<n>.png` beside the capture), or none |
| `--list` | the textures the frame's records name, with their images (serial, size, VkFormat, GPU-written) |
| `--dump <serial>,…` | PNGs of those textures' level 0 after the last replay (`<capture>.r<n>_<serial>.png`) |
| `--dump-rt` | PNGs of every colour image the GPU wrote among them |
| `--dump-gpu` | PNGs of every colour image the GPU wrote, also those no record names (a scene target before its upscaler): `<capture>.r<n>_g<serial>_<w>x<h>_f<VkFormat>.png` |
| `--max-pixels n` | a frame that differs from the live one in at most n pixels still counts as a match |
| `--sync` | wait for the GPU after every submission (the default waits only where the capture took new state in between) |
| `--out <dir>`, `--no-flip` | another folder for the PNGs; no vertical flip for a lower-left origin |

What it prints (the tunnel capture, `android-replay` at the time of writing):

```
loaded in 9434 ms: 2147 regions (2650 MB, 0 not at their live address), 2070 pools, 1 textures, 190 programs, 2 descriptor pools, 4 submits; 2727 CPU-written textures marked
replay 1: submits CPU 203.97 ms (recording, 4 submits), GPU 80.56 ms, wall 345.05 ms to the last fence; 7458 draws (0 skipped), 10 dispatches, 86 render passes, 0 pipelines made; before the frame: 4627.4 ms applying the captured state (4490 images filled), 866.1 ms preparing
replay 2: submits CPU 59.24 ms (recording, 4 submits), GPU 20.99 ms, wall 123.48 ms to the last fence; …
replay 3: submits CPU 45.15 ms (recording, 4 submits), GPU 22.67 ms, wall 96.50 ms to the last fence; …
best of the warm replays: submits CPU 45.15 ms, GPU 20.99 ms, wall 96.50 ms
```

- **submits CPU**: the time in `mtl_sub_begin` … `mtl_sub_commit` for the frame's submissions (recording the Vulkan commands: the number the perf work moves); **GPU**: the frame's GPU time from the submissions' timestamps (`mtl_gpu_ms`); **wall**: from the first submission to the last fence.
- Replay 1 pays for the first use of everything (images made, modules, the bindless tables) and is not a timing; replays 2 and later are. "before the frame" (state applied, images filled, the first submission's texture uploads) is outside the timings.
- A whole run with `--warm 3` takes about 30 s: 9 s loading the capture (the file is in the page cache after the first run), 5 s for replay 1's state and about 3 s for each later one.
- The digest line compares the presented image with the live one, pixel by pixel, and names the PNG. Exit status 0 = the same picture (within `--max-pixels`), 1 = different, 2 = cannot replay (`[RED] nxreplay:` says why).

**Known (open):** the replays do not equal the live frame. Replay 1's picture is far off (most of the scene black with white-edged blobs, 4.6 M pixels differ); replays 2 and later are close to the live picture (the same scene, characters' poses slightly different, 1.1 M pixels differ) and equal to each other bit for bit. After replay 1 about 520 MB of pool memory (130,000 4 KiB blocks) were written by the replay where the live frame left them unchanged; replays 2 and 3 each write about 300 MB that way. So some GPU writes of the replay land where the live run's do not, or state the frame reads from before it (a previous frame's GPU output) is not all captured; this is the next thing to find, with `--dump` of the frame's targets and the pool comparison line. Until then use replays 2 and later: their timing is the frame's, and their picture shows the same NaN blobs as the game.

For a wrong draw, `DM_VK_DRAW_LOG=<n>` (live; with `nxreplay` set it in the shell before the command) logs the first n draws of each frame: shaders, colour targets, viewport and scissor, blend, instances and index buffer, vertex inputs, the buffers and the textures (with their view swizzle) each stage binds. `--dump <serial>,…` together with `--dump-gpu` also writes textures that no record names (those reached only through a texture ID, such as a CPU-written line of text), and `DM_VK_PNG_ALPHA=1` keeps the alpha of RGBA8 / BGRA8 pictures (otherwise opaque). A capture made with learned view formats (the app's `files/temp/<title ID>/vk_view_formats.txt`) replays with `DM_TEMP=<folder>` holding a copy of that file: the replayer leaves the captured `DM_TEMP` out, and without the pairs an image shared by textures of two formats is made with one format only ([Captures whose textures shared another format's image](../docs/reference/rendering.md#captures-whose-textures-shared-another-formats-image-on-the-vulkan-replay)). A capture made by the app replays with `DM_VK_PLACE_LAZY=0` (the replay places every pool when it is made; lazily nothing is placed and every draw is skipped) and, for a custom driver, `DM_VK_DRIVER=/data/local/tmp/nxreplay/drv` (a copy the shell user can read).

To test a shader by hand, `DM_VK_SPV_OVERRIDE=<folder>` (`vka_shader.c`) takes `<folder>/<key>_<variant>.spv`, when there is one, in place of the library's module of that shader (variant 0 the base module, 1 a pixel shader's integer-output one); each override is logged once. A module must keep the library's interface (its locations, sets and bindings): the pipeline layout comes from the library. Rewritten to show what it reads (a position written into a flat output, a fixed full-target position, a pixel shader that writes the bits of its inputs as colours, decoded from the `--dump` PNGs with `DM_VK_PNG_ALPHA=1`), it shows which input or which step of a draw goes wrong; with the modules of a translator built from a change, it checks the change on the phone before the library is rebuilt. Zelda's missing UI text was found this way ([Deferred register writes under a guard](../docs/reference/shaders.md#deferred-register-writes-under-a-guard-ampere-scoreboards)).

For a wrong compute result, `--env DM_VK_DISPATCH_LOG=1` logs each dispatch of the frame (its index, shader key, groups, workgroup size, shared memory, flags) and `DM_VK_DISPATCH_SKIP=<from>[,<to>]` records those dispatches without running them; with `--dump-gpu` that shows which dispatch writes a picture.

When the live picture and `nxreplay`'s replay of its capture differ, compare one shader's inputs and output in both: `DM_VK_TEXSTAT_FS=<key>` (live through `nxctl.sh env`, `--env` on the replay; once per value) logs the textures and colour targets of the first draw or dispatch with that shader, summed up (`texstat �` lines: zeros, ones, NaN, range, mean log2, median), and with `DM_VK_TEXSTAT_AT=1` they are read right after that draw or dispatch, with its uniform and storage buffers' hashes and first floats (`DM_VK_TEXSTAT_DIR=<folder>` writes the buffers too). Equal inputs and a different output point at the pipeline: the replayer is a process of its own and compiles with FPCR 0, as the live run's replay does since 2026-11-07; `DM_VK_GUEST_FPCR=1` (restart) gives the live replay the game's FPCR again for a comparison and keeps no pipeline cache file meanwhile ([rendering.md](../docs/reference/rendering.md#pipelines-compiled-with-the-games-floating-point-environment-on-the-vulkan-replay)). `DM_VK_RC_LOG=<n>` logs the next n render-condition decisions, `DM_VK_SUBMIT_WAIT=1` / `2` returns to the game only once the submission is recorded / has run on the GPU.

For the NaN hunt (`DM_VK_NANSCAN`): `--env DM_VK_NANSCAN=1` (or 2) on the replay logs the first pass writing NaN / Inf texels as in the game, in seconds per try instead of a level load.

## Fast test runs

For an agent's test run that only has to reach the first level, one line in `env.txt` does it as fast as the game allows:

```sh
adb shell 'f=/sdcard/Android/data/com.swap2native.test/files/env.txt; printf "DM_WATCH_STALL=25\nDM_FASTBOOT=1\n" > $f; chmod 666 $f'
```

`DM_FASTBOOT=1` sets the switches of the profile's `fastboot_env` that `env.txt` does not set already (each is logged as `DM_FASTBOOT: KEY=VALUE`). For Donkey Kong Bananza:

- `DM_KEYS=f1:A~0.1*3000/12`: A every 12 presented frames from the first one, instead of fixed seconds: each screen that waits for A gets it within a fifth of a second.
- `DM_MARK_DRAWS=3000`: once 5 frames in a row have 3,000 draws or more (the title has 63, the loading screen 6-9, the first level 5,500 and more), the log says `[mark] frame <n>: <draws> draws (…), <s> s from process start, wall clock <epoch>`. Wait for that line instead of a fixed time: `adb shell grep -a -m1 '\[mark\]' <newest log>`.
- `DM_MARK_KEYS_STOP=1`: no presses after the mark, so the level is not played by the script.

Start from a fresh copy of the seed save ([Saves](#saves)). Measured on the PNM-N49 (2026-11-02, `am start` to the mark): 49.2 s with `DM_KEYS=15:A*38/2`, 44.7, 49.3 and 50.4 s with `DM_FASTBOOT=1`. The presses take about 3 s off the time from the first present to the level load (23.2 s → 20.2-20.5 s); the run-to-run spread of the rest is as large. What is left is the game's ([the game's note](../dm/games/040074A01BF12000/README.md#boot-android)): the first present 6-9 s after start, the autosave notice before the title (about 15 s, takes no input), the title and the save's menus (about 4 s) and the level load (18-21 s, 0 new pipelines; `DM_FS=1`'s `[fs]` lines put the host's open and read time at about 3 s of it)

## Live control

While the game runs, an agent can change the replay's switches, take screenshots and read frame statistics without restarting it: the launcher sets `DM_CTL=<app files>/ctl.txt` (`/sdcard/Android/data/com.swap2native.test/files/ctl.txt`), the host reads each line appended to it within 100 ms (`dm/host/hle_hid.c`, the Mac's `DM_CTL`; on Android it starts at the file's end, so an old run's lines are not replayed), and `android/tools/nxctl.sh` appends a line with adb and prints the log lines that answer it (`[vk] ctl: …`):

```sh
android/tools/nxctl.sh env DM_VK_DRAW=0          # draws off from the next frame; env DM_VK_DRAW= clears it again
android/tools/nxctl.sh capture 30                # one line per frame: ms, draws, passes, barriers, clears / copies, submissions, recording ms, GPU ms
android/tools/nxctl.sh screenshot shot.png       # the next game frame (the window texture, before the present scales it) → ./shot.png
android/tools/nxctl.sh stats                     # the last 60 frames' averages, fps, placed memory, the switches set live
android/tools/nxctl.sh fps 30                    # the frame rate cap, as the in-game panel sets it (0 = the game's own)
android/tools/nxctl.sh A~0.2                     # any other DM_CTL line: a press, dump, ...
android/tools/nxctl.sh log 40                    # the run's last log lines (nothing sent)
```

`NX_SERIAL` picks the phone (default: adb's, `ANDROID_SERIAL` or the only phone), `NX_PKG` the app (default the test app `com.swap2native.test`). Without the script: `adb shell 'f=/sdcard/Android/data/com.swap2native.test/files/ctl.txt; echo "env DM_VK_STATS=0" >> $f; chmod 666 $f'` (the `chmod` as for `env.txt`). `DM_CTL=` in `env.txt` turns the reader off.

An `env KEY=VALUE` line is queued and applied at the next frame boundary: the first submission after the next present, under the host's submit lock, so no submission is half recorded with the old value. It sets the value for the replay's switches and in the process environment (host switches read at use see it too), then bumps a generation counter: each switch read through `VKA_ENV` (`dm/gfx/vk_android/vka.h`) is read again at its next use. The log line says which kind the switch is:

| Kind | Switches |
|---|---|
| live: the next frame | `DM_VK_DRAW`, `DM_VK_STATS`, `DM_VK_HANG_S`, `DM_VK_HANG_EXIT`, `DM_VK_FRAME_RATE` (a change of the game's rate after it), `DM_VK_FRAME_RATE_HOLD` (the next rate change), `DM_VK_GENLOCK` (the next present), `DM_VK_PCACHE_SAVE_S` (the next save), `DM_VK_GPL_PROBE`, `DM_VK_GPL_GIVEUP` (the next refused library), `DM_VK_TEX_TRACK` (textures made from then on), `DM_VK_PRETRANSFORM` (makes a new swapchain), `DM_VK_FSR`, `DM_VK_FSR_SHARP` (the next present), `DM_VK_NDSR`, `DM_VK_NDSR_INPUT`, `DM_VK_NDSR_MAP`, `DM_VK_NDSR_LOG` (the next dispatch of an NDSR network), `DM_VK_CHUNK`, `DM_VK_PASS_CLEARS`, `DM_VK_PASS_KEEP`, `DM_VK_DYN_FILTER`, `DM_VK_PROF` (each from the next submission), `DM_VK_ROWS` (the next re-upload), `DM_VK_SYNCLOG` (the game's next wait), `DM_VK_UBWC` (images made from then on; earlier ones keep theirs), `DM_VK_IMG_UPGRADE` (`0`: a texture bound as a shader image without NVN's IMAGE flag is no longer remade with storage use; the next binding), `DM_VK_NANSCAN_DUMP` (read at use), `DM_LSFG`, `DM_LSFG_MULT`, `DM_LSFG_TARGET`, `DM_LSFG_FLOW` (as the in-game settings) |
| restart only (logged as such) | `DM_VK_VALIDATE`, `DM_VK_PLACED`, `DM_VK_PCACHE`, `DM_VK_GUEST_FPCR` (the replay's threads take their FPCR when they start), `DM_VK_SHLIB`, `DM_VK_SHLIB_CHECK`, `DM_VK_GS_CLAIM`, `DM_VK_ADPF`, `DM_VK_ADPF_PIPELINE` (the session is made once), `DM_VK_GPU_FLOOR_KGSL` (the queue's kernel contexts are found when the device is made), `DM_VK_NANSCAN`, `DM_VK_NANSCAN_STEP`, `DM_VK_NANSCAN_DRAWS`, `DM_VK_NANSCAN_SERIAL`, `DM_VK_NANSCAN_FS` (the scan's buffers and probe are set up once), `DM_VK_WORKER`, `DM_VK_WORKER_FRAMES` (the replay thread starts once), `DM_VK_TEST_HANG`, `DM_LSFG_DLL`, `DM_FPS`, `DM_VK_PREWARM`, `DM_VK_PREWARM_MAX`, `DM_VK_PREWARM_FILE` (the prewarm threads start with the first pipeline) |

A new `DM_VK_*` switch is live when it is read with `VKA_ENV("DM_VK_…", default)` (a number; `vka_env_str` for a string) instead of `getenv`; one that sizes a device object or a cache goes into the restart-only table in `vka_ctl.c`, or its change must also drop that cache. A `VKA_ENV` call site may run on the game's thread and the replay worker at once: its cache (`vka_envc`) holds an atomic value, and only one thread at a time refreshes it, and only to a newer generation, so neither a torn nor an older value is read as current.

GPU time and the frame's timeline, live: `nxctl.sh env DM_VK_GPUPROF=50` times one frame in 50 step by step (GPU timestamps between the full barriers: `gpu prof:` lines with the frame's GPU time by kind and the costliest steps, `DM_VK_GPUPROF_LIST=1` every step; it slows the frame a little, so do not judge the frame rate with it on); `env DM_VK_SYNCLOG=200` logs the next 200 waits of the game together with each submission's recording and queueing times, its timestamp reports and when they were written (`sync …` lines, one clock in ms). `DM_VK_GPU_FLOOR` (default 100) and `DM_VK_CHUNK_PASS` (default 600) are the GPU clock floor and the pass splits ([rendering.md](../docs/reference/rendering.md#gpu-end-held-back-by-recording-and-a-clocked-down-gpu-on-the-vulkan-replay)); in `nxreplay` the floor also keeps the GPU timings steady from replay to replay (`--env DM_VK_GPU_FLOOR=100`). `DM_VK_ENC=0` records the Vulkan commands on the replay thread itself instead of the command encoder thread ([rendering.md](../docs/reference/rendering.md#recording-held-back-by-the-drivers-command-recording-on-the-vulkan-replay)); in `nxreplay` use `--env DM_VK_WORKER=0` for the recording time (with the worker, `submits CPU` is only the hand-over).

## Test 2: graphics self-test

No game or pack needed: it checks the Vulkan device, placed guest memory, the NVN replay (clears, copies, a draw and a compute dispatch through the shader library path) and the present on the phone. Install the APK (step 2), start the log on the Mac, open nxnative and tap **Graphics self-test**:

```sh
adb logcat -c && adb logcat -v time Swap2Native:V DEBUG:V libc:V '*:S' | tee nxnative-selftest.txt
```

The screen turns red with a white 128×128 square near the bottom-left corner and, in the middle, a triangle checkered magenta with see-through cells (the alpha test drops them) that turns once every 6 s, in a 16:9 picture (black bars on a wider panel), with the game's on-screen controls over it: try them here (presses light up and tick, the stick knobs follow the finger; they drive nothing), and hold the top-centre button for their settings. The square must stay near the bottom-left corner in both landscape orientations (turn the phone over while it runs). The background cycles red → yellow → green → cyan → blue → magenta, about every 6 s round, for 10 s (600 frames), and then the top of the screen shows **PASS (return code 0)** in green. **FAIL** in red shows the return code: the number of failed checks, or -1 when the host has no self-test. Back returns to the game list; **Share log** then sends `selftest-<time>.log`.

The log lines, in order:

1. `[nxlaunch] graphics selftest: nxnative … ; device …` and `nxhost_vk_selftest(0x…, 600)`;
2. `[vk] device Adreno (TM) 840, Vulkan 1.4.… ; placed maps yes …, update-after-bind yes, display timing yes …`;
3. `[vk] draw path: push descriptors yes (…), vertex input dynamic state yes, null descriptors yes, 8-bit indices …, geometry yes …; uniform alignment …, storage alignment …` (what the draws use: send this line back whatever it says);
4. `[vk] window 0x…`, `[vk] selftest: 64 MiB of guest memory at 0x…, placed Vulkan memory`, `[vk] selftest: shaders made; …`;
5. `[vk] swapchain 1080x2420, 3 images, format 37, FIFO, transform 0x2 (surface 0x2: pre-rotated), …` (the panel's own orientation: the picture is drawn turned, so the compositor does not rotate it; format 37 is R8G8B8A8_UNORM), and `[vk] window frame rate 60 fps`. Turning the phone over (the other landscape) logs `[vk] surface rotation 0x2 → 0x8: new swapchain`, and the picture stays upright. `DM_VK_PRETRANSFORM=0` in `env.txt` turns pre-rotation off for a game run (`transform 0x1 (surface 0x2: the compositor rotates)`);
6. `[vk] selftest: fence 1 done; texel (1200,650) ff0000ff (want ff0000ff), texel (100,100) ffffffff (want ffffffff), event 1 (want 1)`;
7. `[vk] selftest: draw: 1 drawn, 0 skipped; triangle centre texel (640,360) ffff00ff (want ffff00ff: a white texel times the tint), texel (685,360) ff0000ff (want ff0000ff: dropped by the alpha test)`: the draw path (shader modules from a library, pipeline, set 0, the texture and sampler pools, the uniform buffer, the c1 bytes, vertex attributes, the alpha test's specialization constant and reference);
8. `[vk] selftest: dispatch: 1 run; storage words 5 and 255: 4005, 4255 (want 4005, 4255)`: a compute dispatch with a storage buffer and the driver segment c0;
9. `[vk] selftest: 600 frames presented to the window; 1 graphics + 1 compute pipelines (0 failed), …; passed`, then `[nxlaunch] graphics selftest returned 0: PASS`.

The return code counts the failed groups of checks: placed memory, the clear / square / event read-backs, the draw, the dispatch. Any `[RED] vk:` line between 4 and 9 (a pipeline that failed, a shader refused, a layout) is the thing to send back; so is a crash in the driver (`DEBUG` lines naming `vulkan.adreno.so`).

On the Android emulator the device has no `VK_EXT_map_memory_placed`: the log says `placed maps no` and `NOT placed (no placed maps): a mapped Vulkan allocation instead, for the other checks`, every other check passes (the emulator has no push descriptors, vertex input dynamic state or null descriptors, so it runs the fallbacks of those) and the test ends with FAIL (return code 1) with the triangle on screen. That is expected there; on the phone, a missing `placed maps yes` or any other mismatch is the finding to send back. The emulator reports ROTATE_90 in landscape too, so it pre-rotates; `adb emu rotate` twice exercises ROTATE_270 and the swapchain recreation.

### The game's shader library on the device's compiler

`DM_VK_SHLIB_CHECK=1` in `env.txt` (step 6's diagnostic runs) makes the first game run, when its library loads, build every shader module of it and every compute pipeline, and log `[vk] shader library check: 22852 shaders, … modules made, … refused, … without a layout, 205 compute pipelines (… failed), … s`. The refused ones are expected (the four NV passthrough geometry shaders; see android/SHADERS.md); a failed compute pipeline or layout is a finding. Remove the line afterwards: the pipelines it built stay in the pipeline cache (`vk_pipelines-fp0.bin` in the game's temp folder), the check itself is not needed again.

## Emulator

The arm64 Android emulator on an Apple silicon Mac boots the game's CPU side as far as the phone should: through all eight stages, the title menu's frame loop and, with scripted presses, into the first level. It has no `VK_EXT_map_memory_placed` (SwiftShader), so the GPU sees no memory pool; the host notices that by itself (`placed maps no`, then `[RED] vk: no VK_EXT_map_memory_placed` and one `[RED] vk: memory pool … is not in placed guest RAM` per pool) and goes on, with or without `DM_VK_PLACED=0`. What it cannot show: placed guest memory and its `mprotect` / write-protect faults, the Adreno driver, the phone's speed and memory limits.

An AVD with room for the game folder (about 10 GB) and 8 GB of memory, kept on the dump drive (the home disk is nearly full):

```sh
export ANDROID_AVD_HOME=$D/avd
echo no | ~/Library/Android/sdk/cmdline-tools/latest/bin/avdmanager create avd -n nxemu -k 'system-images;android-36.1;google_apis_playstore;arm64-v8a' -d medium_phone
sed -i '' -e 's/^disk.dataPartition.size=.*/disk.dataPartition.size=24G/' -e 's/^hw.ramSize=.*/hw.ramSize=8192/' $ANDROID_AVD_HOME/nxemu.avd/config.ini
~/Library/Android/sdk/emulator/emulator -avd nxemu -no-window -no-audio -no-snapshot -no-boot-anim -gpu swiftshader_indirect -partition-size 24576 &
adb -s emulator-5554 wait-for-device
```

Then steps 2–4 and 6 with `adb -s emulator-5554` (the push takes about 5 minutes), and start the game with the intent of step 5. Without a display the window is the emulator's virtual one, and `adb shell input` events come from a virtual device, which the launcher does not give a player; press buttons with the host's scripted input instead, in `env.txt` ([Diagnostic switches](#diagnostic-switches)), for example A every 5 s from 25 s to leave the title:

```sh
adb -s emulator-5554 shell 'f=/sdcard/Android/data/com.swap2native.test/files/env.txt; printf "DM_KEYS=25:A,30:A,35:A,40:A,45:A,50:A\nDM_FS=1\n" > $f; chmod 666 $f'
```

A good run on the emulator (Donkey Kong Bananza 458752): stages 1–8 within about 7 s (2 s once the RomFS is in the page cache), the title menu at 67 draws a frame; after the presses the first level loads and its opening runs at about 740 draws a frame with 3.5 GB resident. The `[RED]` lines are the graphics stubs of [PORTING.md](PORTING.md#stubs-in-this-build) and the placed-memory ones above. The game's note has the details ([Boot (Android)](../dm/games/040074A01BF12000/README.md#boot-android)).

## Overlay and frame generation (LSFG)

The overlay is on by default: the build tag at the top left (`Swap2-Native beta · <branch>@<commit> · <time>`, the same as the log's first line `[nxlaunch] build …`) and at the top right the throttle dot with the frame rate (`<n> fps`; `-- fps` before the first frame and while nothing is presented), the frame time and GPU time, the CPU clock caps and the battery (README, Overlay: the dot's thresholds; each item has its own switch). Turn it off in the main screen or in the controls' settings (hold the top-centre button); `DM_OVERLAY=0` in `env.txt` hides it for a run.

Frame generation needs the user's own `Lossless.dll` (Lossless Scaling for Windows):

1. Copy it to the phone, e.g. `adb push Lossless.dll /sdcard/Documents/Emulation/bios/` (or `Switch2/`, or `Download/`); or pick it with **Frame generation (LSFG)… → Pick Lossless.dll**. The dialog then says where it was found.
2. Turn **Frame generation (LSFG)** on there (or in the game's settings), choose 2x / 3x / 4x or a target rate, and the motion estimation resolution (lower is faster).
3. Start the game. The overlay shows `<game> fps → <presented> fps (LSFG)` once the game's frame rate is steady (Eden's pacer waits about a second, and generates nothing while the game runs under 10 fps). The log: `[nxlaunch] frame generation: on; Lossless.dll from …`, `[vk] frame generation: 25 shaders from …`, `[vk] lsfg: chain WxH, flow …`, `[vk] frame generation: first 1 generated frame(s) …`, and every 15 s `[vk] fps: … (frame generation on)`.

Without a DLL (or on a GPU without what the shaders need), turning it on leaves the game running as before; the overlay says `LSFG unavailable` and the log `[RED] vk: frame generation unavailable: no Lossless.dll …`. With `env.txt` alone: `DM_LSFG=1`, `DM_LSFG_MULT=2`, `DM_LSFG_TARGET=0`, `DM_LSFG_FLOW=75`, `DM_LSFG_DLL=<path>`.
