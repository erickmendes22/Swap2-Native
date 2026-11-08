# Swap2-Native — preparation flow (handoff between Claude and the GPT)

Date: 2026-11-05. Asked by the user: "ao importar o jogo, ao clicar no botão jogar, vai para a tela de preparação (ao invés de um card); o jogador pode aguardar
finalizar a preparação e jogar, ou ele pode voltar e um mini resumo da preparação fica sendo exibido dentro do card do jogo". The GPT designs the interface;
Claude implements the flow and the backend. This file is the contract between the two: what each side owns, and the Java interface between them.

## The flow

1. The library: a game that needs preparing shows "Prepara ao jogar" on its card. Nothing is prepared when it is added.
2. **Jogar** on that game opens the **preparation screen** (`PrepareActivity`), a screen of its own (not a card in the library), and the preparation starts:
   the dump is checked first (problems are a plain message, and the screen is not opened), then the job runs in the background service (`PackService`).
   A job that was paused or stopped for that game is resumed instead.
3. On the preparation screen the player can:
   - **wait**: the progress updates live; when it is done, **Jogar** is enabled and starts the game;
   - **go back** (Back, or the screen's back button): the preparation goes on in the background and the library shows a **mini summary** of it inside that
     game's card (step and share done); tapping that card's Jogar (or the mini summary) opens the preparation screen again.
4. Pause / Resume are on the screen (and in the notification). There is no Skip: a game plays only with its pack.
5. One job at a time (the service runs one): Jogar on another game while one prepares says so.

Keep the app in front while it prepares on MIUI phones: MIUI freezes the whole app, the service too, when another app comes to the front (found on the
POCO F7 Ultra). Going back to the library is fine; leaving the app is not, until the battery exemption is asked for (open, Claude).

## Who owns what

| Part | Owner | Files |
|---|---|---|
| The flow, the job, the service, the state | Claude | `Ondevice.java` (`Ondevice.play`, the job logic), `PrepareState.java`, `PrepareActivity.java`, `PackService.java`, `Job.java` |
| The preparation screen's look | the GPT | `PrepareScreen.java` (Claude ships a plain placeholder with the interface below; replace its body, keep its interface) |
| The mini summary in the game card | the GPT | `MainActivity.java` (the card), from `PrepareState` |
| The calls from the library | the GPT calls them | `Ondevice.play(MainActivity, File dump)`, `Ondevice.state()`, `Ondevice.listen(...)`, `Ondevice.openScreen(MainActivity)` |

## The interface

### `PrepareState` (Claude; read-only for the UI)

One snapshot of the job, made on the main thread every time it changes (about once a second while it runs). Fields:

| Field | Meaning |
|---|---|
| `titleId`, `name`, `version`, `dump` | the game (`dump` is the game's folder or .nup: compare it with `Game.gameDir` to find its card) |
| `phase` | `RUNNING`, `PAUSED`, `FAILED`, `DONE`, `PENDING` |
| `step`, `steps` | the current step, 1-based, of 5 (identify, rewrite the code, split the shaders, translate the shaders, write the pack) |
| `stepName` | that step in words ("Translating the shaders") |
| `status` | the job's own sentence: the step and its count, why it paused ("battery below 20 %…"), or the error and what to do |
| `overall` | 0..1, the whole job's share done (never past 1) |
| `shadersDone`, `shadersTotal` | the shaders processed and their total (total 0 = not counted yet) |
| `canPause`, `canResume`, `canPlay` | which actions apply now |

Rules from the design docs that still hold: show a percentage only from `overall`, no time estimate the job does not report, "processed" not "compiled".

### `PrepareScreen` (the GPT; Claude's placeholder until then)

```java
final class PrepareScreen {
    interface Actions { void pause(); void resume(); void play(); void back(); }
    PrepareScreen(Activity a, Actions actions);   // builds the screen's views
    View view();                                   // PrepareActivity's content
    void render(PrepareState s);                   // called on every change; s is never null
}
```

`PrepareActivity` owns the lifecycle (binding the service, insets are the screen's), calls `render` on every change, and does what the actions ask:
`pause` / `resume` the job, `play` (only when `canPlay`: the game goes into the list and starts), `back` (finishes; the job goes on).

### The library side (the GPT)

- `Ondevice.state()`: the current job's `PrepareState`, or null when no game is being prepared (also null once a finished game is in the list).
- `Ondevice.listen(java.util.function.Consumer<PrepareState> l)`: `l` gets every change on the main thread (null when the job goes away); one listener (the
  library); `listen(null)` stops.
- `Ondevice.play(MainActivity a, File dump)`: what Jogar does for a game that needs preparing (its card's state, as today): checks, starts or resumes the job,
  and opens the preparation screen.
- `Ondevice.openScreen(MainActivity a)`: opens the preparation screen for the job there is (the mini summary's tap).

The previous preparation card in the library (`Ondevice.Panel`'s view) is no longer shown: the mini summary in the game card takes its place.

## UI implementation — 2026-11-05

The placeholder in `PrepareScreen.java` has been replaced with the preparation design, preserving its constructor, `view()`, `render()` and Actions interface. A wide screen has game identity/cover on the left and progress/actions on the right; below 720 dp the same content stacks and scrolls. Insets use `Ui.page`. The approved app symbol, navy surfaces and cyan/coral palette match the launcher.

The screen shows the overall percentage, current step, five-stage checklist, processed shader count when available, and the original job status/error message. Pending, running, paused, failed, done-but-not-playable and playable are distinct states. `canPlay` gates Play; reaching 100% alone does not. No Skip, estimated completion time or automatic launch was introduced. Back explicitly returns to the library; the explanatory text distinguishes this from leaving the app on phones that suspend background work.

The game card now has an inset clickable progress summary (step, overall percentage and progress bar), updated in place from the snapshot. It matches by dump path, hides on a null/different snapshot and restores the card's ordinary badge. The library listener is detached on pause and registered on resume. The service, job, state model and PrepareActivity remain Claude-owned and were not edited for the design.

New UI copy has English and Portuguese resources. `status` and `stepName` remain the backend's original text. This preparation flow supersedes the old shader mockup's Skip/automatic-start behavior.

### Validation handoff

Static XML, duplicate-string and UI resource-reference checks passed. Compilation and device rendering are pending with Claude; no APK was built or installed for this change.

- Capture portrait (360 dp), short landscape and tablet widths; verify readable progress, scrolling, cutout insets and large fonts.
- Exercise every phase, including DONE with `canPlay=false`, unknown shader total, long errors and battery pause. Verify percent only comes from `overall` and shader count uses processed terminology.
- Back during preparation must keep the service running and show the summary on the correct card. Reopen via the summary and via Play; library selection and scroll must stay intact.
- Pause/resume/retry must call the existing actions only when their capability flags permit it. Play stays disabled until `canPlay`; completing never launches automatically.
- Test job disappearance and switching to a different dump: the previous mini summary must disappear, without stale percent/badge or rebuilding the carousel every second.
- Verify rotation/activity recreation, listener cleanup, and repeated background/foreground transitions. Verify that starting another game while a job runs still uses the backend's single-job guard.
- Check TalkBack and controller focus for the mini summary, Back and pause/resume/play buttons; respect reduced-motion settings on entrance.

## Claude's validation — 2026-11-05 09:13

Built (no compile errors) and installed on the POCO F7 Ultra (short landscape, Portuguese). Seen on the device, with Zelda's job stopped at the rewrite
(FAILED; not resumed: the user asked not to resume it yet):

- Library: Zelda's card shows "Preparação interrompida" and the inset summary ("Etapa 2 de 5 · 1%", the step, the bar in coral). Donkey Kong Bananza keeps
  "Pronto", Mario Kart World "Prepara ao jogar". The summary makes Zelda's card taller than the others, so the row of cards no longer fits the short landscape
  height above the selected game's bar (the bar and the cards' lower half need scrolling): for the GPT.
- The first tap on the summary only selected the card; the second opened the preparation screen (tap on an unselected card's summary: select or open? the
  GPT's call).
- PrepareActivity: the GPT's screen in the FAILED state: "Preparação interrompida", "Etapa 2 de 5", 1%, "0 de 42.321 shaders processados", the job's error.
  The buttons were not reached: the user took the phone while it was checked (not tested: Retry / Resume, Play, Back's button).
- For Claude: `stepName` and `status` are the backend's English (`Job.STEP_TEXT`, `Job.statusText`); they get Portuguese resources on the backend side.

## Minimal perimeter progress — supersedes the inset summary

User visual correction on 2026-11-05, verified against the connected phone (`output/ui-review/library-border-before.png`): remove the preparation panel inside the card. Preparation must not increase card height.

`CardProgressBorder.java` now draws a 3 dp progress stroke clockwise around the rounded card perimeter, starting at top center, using only `PrepareState.overall`. There is no internal progress bar, stage text block or additional layout row. The existing status badge remains; detailed steps and errors stay on PrepareScreen. Select the card and use Play to reopen preparation, as before. TalkBack receives state, percentage and step through the card description.

The ordinary selection outline is retained when idle; during preparation a thin inset focus outline distinguishes selection from the progress stroke. Running uses cyan, paused amber, failed coral and playable green. The border updates in place without an animation loop or layout changes. Null/different snapshots restore the normal card border and badge.

Claude validation pending: build and inspect 0%, 1%, 25%, 50%, 100%, paused and failed states on selected/unselected cards; confirm equal card heights, rounded corners without clipping, no stale progress after job removal and normal controller focus. Codex captured the existing screen but did not build/install this revision.

## Bottom-edge progress refinement — supersedes perimeter progress

The user clarified that preparation progress belongs only on the bottom edge, filling left to right. `CardProgressBorder` now draws a 3 dp horizontal track between the rounded bottom corners; it no longer follows the perimeter. Selection retains its separate outline. No internal panel or extra card height is introduced.

New progress values interpolate over 260 ms with deceleration. The first snapshot appears immediately at the actual value; identical snapshots and selection changes do not restart animation. Reduced motion or disabled Android animators make updates immediate. Detaching the card or pausing the launcher settles/cancels animation. There is no repeating shimmer or idle animation.

Claude validation pending: verify 0/25/50/100%, updates mid-animation, no restart on selection, paused/error colors, return from preparation, reduced motion, and no clipping at the rounded corners. Source and whitespace reviewed; no build/install by Codex.

## Contextual library action — 2026-11-05

The selected-game action now follows a single UI state decision for both its label and click behavior:

| State | Action | Appearance |
|---|---|---|
| Initial readiness check incomplete | Checking (disabled) | Tonal |
| Usable pack, or snapshot `canPlay` | Play | Cyan |
| Preparation required | Prepare | Palette yellow `s2_warning` |
| Snapshot `canPause` | Pause | Tonal, pause icon |
| Snapshot `canResume`, not playable | Continue | Palette yellow |
| Other blocked state | Needs attention | Tonal; opens preparation details or Manage |

Prepare calls the existing `Ondevice.play` flow. Pause/Continue use the same PackService intents as PrepareActivity, without opening another screen. Continue reads the remembered job and checks its dump matches the selected game before sending ACTION_START. `Ondevice.pause/resume` are activity-observation lifecycle methods, not job-control actions, and are not used for the buttons. The backend job/service implementation is unchanged. Existing playable legacy libraries retain their current readiness semantics.

Static XML/resource-reference and whitespace checks passed. Claude build/device checks remain pending: ready/unprepared/running/paused/failed/unknown states, selecting a different game while a job runs, service state changes from notification, restoring the launcher, and a job disappearing before Continue. Confirm no click launches an unprepared game and UI labels only change to reflect received snapshots.


## Fixed-viewport preparation layout (2026-11-06)

`PrepareScreen` now owns a fixed-height, inset-aware page instead of the shared scrolling `Ui.page`. Landscape puts a compact cover/identity card beside the progress card; portrait uses a short horizontal identity strip above progress. The actual measured window drives the layout, including rotation and resize without Activity recreation. The background still fills the entire window.

The five stages occupy one horizontal strip. Back and the applicable primary action stay in a fixed 48 dp footer: Pause/Resume/Retry while preparing, Play only when ready. The existing `Actions` interface and job/service behavior are unchanged. Long game names use at most two lines; inline status is bounded and ellipsized. Tap the status to open its full selectable text in a dialog. Small windows reduce spacing and secondary text; very short windows omit the cover and footer hint. The page itself has no scroll container.

Validation: `compileReleaseJavaWithJavac` and Android resource processing passed with the native pack stage. Phone visual validation and installation were not performed for this change; the running preparation was not interrupted.
## Single-action flow (2026-11-08) — supersedes "Contextual library action"

Asked by the user ("esse fluxo ta muito complicado"), from a friend's phone (RedMagic 11 Air): Zelda's card said "Preparando…" with no percentage while its
button said "Requer atenção"; Play had shown an English dialog with Pick pack folder / Cancel / Prepare again, and Prepare again "stopped by itself" with no line
in any step log.

### What was wrong (root cause)

- The worker marked a step `running` in job.json before anything that can fail (the logs folder, the log's header, the tools' unpack), and its `catch` set the
  job failed without resetting the step. On a full disk the failed state was often not even saved. The job then read as "rewrite running" for good:
  `PackCheck.rewriting` made the card say "Preparing…", and since the job the launcher followed (`Ondevice.state()`) was another game's or none, the button fell
  to "Needs attention". Unpacking a new APK's tools into `filesDir` checked no space, kept the old version until the new one was there (twice the room), and
  logged its failure through a write that a full disk swallowed.
- The card had two sources (its own check and the one remembered job) that could disagree; `autoUpdate` could re-point the remembered job away from a dead one.

### The fix

- **The worker** (`PackService.work`): a step is marked running only after its preflight: the logs folder and a first log line, the free space the step needs
  (`DumpCheck.stepNeed`), and the tools unpacked and started (`PackEngine.prepare`: `NoSpace`, `ToolsFailed`). A failure there, or any exception, fails the job
  with a code (`errorCode` in job.json: `nospace`, `tools`, `killed`, `refused`, `io`, `step`, `dump`, `imported_shaders`, `unreadable`; `errorArgs` `free`/`need`;
  `error` keeps the English detail) and never leaves a step running (`Job.clearRunningSteps`). `Job.read` repairs older files: a job that is not running has no
  running step (`GameFlow.normalizeSteps`); a failure without a code is read from its detail (ENOSPC is `nospace`). A job.json that cannot be saved is reported to
  the launcher (`saveError`), and an unreadable one is a logcat error and a message, not a silent stop.
- **The tools' unpack** (`PackNative.start`): other versions and a stopped `.tmp` are deleted first, the room is checked against `assets/pack/size.txt`
  (build.gradle writes it beside `version.txt`) plus 64 MB, a failed unpack deletes its `.tmp`, and the log falls back to `Log.e`.
- **Space**: always checked for the job being made: `DumpCheck.NEED_FULL` (2 GB) for a whole job, `NEED_CODE` for a code-only one, plus the tools' unpack
  (`PackEngine.toolsBytes`). `NEED_CODE` (768 MB) and the per-step needs are placeholders **to measure** on the next device run. A job that does not fit is
  written failed `nospace` (its card says Try again with "X GB free, needs Y GB", its screen has Free up space).
- **One state per card** (`GameFlow.decide`, pure and tested; `GameState` for the texts; `PackFacts` for the check's facts): the game's own job (its job.json in
  its work folder, or the service's live state of it) first, then the pack. The first row that matches wins:

  | Job of this game | Pack facts | Button / why |
  |---|---|---|
  | running or pending, worker alive | — | View preparation |
  | running or pending, no worker | — | Continue (interrupted; the launcher also resumes it by itself, below) |
  | paused | — | View while the worker waits (battery, heat), else Continue; the caption says why |
  | failed | — | Try again; the sentence is its code's |
  | done and ready | not (checked and mods / build changed) | Play |
  | none or done | no profile | Fix (not supported) |
  | none or done | no pack / unfinished, a dump | Prepare |
  | none or done | code does not fit (mods, another game build), a dump, this version's shader library there | **Play, auto**: a short code job, then the game |
  | none or done | the same, the library missing or only an older one | Prepare (the short job never translates shaders) |
  | none or done | shaders missing but an older library plays (or legacy) | Play (the update runs in the background) |
  | none or done | shaders missing, a dump | Prepare |
  | none or done | anything above without a dump | Fix: one sheet with the reason, Pick the pack folder, More options |
  | none or done | fits | Play |

  The card's label, icon, caption, status line and colour all come from that one state (`MainActivity.render` / `showDetails`); "Needs attention" is only a
  caption, never a button label.
- **Play fixes the code by itself** (`Ondevice.fixCodeThenPlay`): no dialog; the job is `Job.adopt` code-only (`code_only` in job.json), the preparation screen
  shows it as "Applying your changes…" with one bar and no stage list, and starts the game when it is done (`PrepareActivity.EXTRA_AUTOPLAY`); a failure stays
  on the screen with its reason and Try again. A pack that still does not fit after a job says why (`launch(g, false)`), so it never loops. Code that other tools made (a pack from another device or an older
  rewriter) is not a mismatch: it plays as it is and is never rewritten in place by Play (a kill or a full disk during that rewrite would break a pack that
  played); Advanced's Prepare again redoes it, asked. When the short job's check finds that the library must be made too, or that the pack no longer reads,
  Play asks the Prepare question instead of starting a translation.
- **Recovery** (`Ondevice.Panel.recover`, 3 s after the launcher resumes): the newest job that is running or pending with no worker is started again
  (`EXTRA_FROM recover`, counted like a sticky restart, so a job Android ends every time fails `killed` instead of looping). `autoUpdate` no longer starts while
  another game has an unfinished job.
- **No dead ends, fewer choices**: Prepare's question is one body (what it does, time, need and free space), Prepare / Cancel and one link "I already have a pack
  or shaders…" (a shaders zip found in Switch2/Shaders is the one alternative with a button). Prepare on an unfinished job resumes it; an unfinished job for
  another pack folder offers "Delete and start over" (asked). The advanced choices (Prepare again, Pick the pack folder, Import / Export shaders, Import /
  Export pack) are one builder, `Ondevice.advancedRows`, under **Advanced** in the game's Options and in its settings' Preparation. "View preparation" shows
  whenever the game has its own unfinished job.
- **Background**: the screen says the preparation goes on in the background (see the notification) and starts again when the app opens; with notifications off
  it says so; a job Android stopped or refused offers "Allow in background" (only a link to the battery-optimization list; the app changes no setting).
- **Language**: every text of this path (card, sheet, preparation screen, notification, Prepare's and Play's messages, the job's status) is a resource in
  `values` and `values-pt`; the checks' own English stays in the logs and in Details. `dm/tools/tests/test_android_game_flow.py` checks the table on the JVM, the
  same keys and format arguments in both languages, and no hard-coded text in the flow's own files.

Not verified on a phone (no adb in this change): to check with the fake engine (`NX_FAKE_FAIL=nospace|tools|kill` in `ondevice/env.txt`,
[TESTING.md](../android/TESTING.md#preparation-failures)) and then on the friend's phone, whose job.json (`Work/0400486024DEC000/ondevice/job.json`: `state`,
`steps.rewrite.state`, `starts`, `error`) and logcat tag `nxpack` would confirm which path it took.

## Expected time (2026-11-08)

Asked by the user ("acho que fica legal colocar o tempo previsto de cada jogo, tipo para o Pokopia que leva muito mais tempo"): each game says how long its
preparation takes on this phone before it starts, and how long is left while it runs.

- **The estimate** (`PrepareTime`, pure, `PrepareTimeJvmTest` through `dm/tools/tests/test_android_prepare_time.py`): identify (10 s) + the code rewrite (when
  the code is redone) + the split (seconds per shader of the game's map: it reads the whole RomFS whatever the delta) + the shaders it translates x seconds per
  shader + the library written (60 s) + the pack step. Kept shaders cost nothing: an imported library is 0, a pack's older library takes the delta manifest's
  count (`Pack.deltaShaders`), a game with no manifest (Pokopia) all of its map. A library made with 0 to translate still costs the split and the library
  written. The card's check fills `PackFacts.mapShaders`, `toTranslate`, `shaders` (the library is made) and `rewrite`. A job keeps the manifest's count it was
  made with (`expected_shaders` in job.json) as the shaders step's total until the tool reports its own, so a delta update's time left is the delta's from the start.
- **The phone's rates** (`Job.rates(c, titleId)`, the `prepare_time` preferences, read at most every 30 s): learned by `PackService` as jobs run, else its SoC class's
  (`PrepareTime.defaults`, by `Build.SOC_MODEL`). Each step's `Tail` feeds a `PrepareTime.Meter` (windows of at least 20 s, each moving the rate by 0.3, the first
  progress line only the anchor); the shaders' rate is the translation stage's only. Every 10 minutes and at the step's end the meter's mean over at least 2
  minutes is kept (the split's as seconds per map shader; a split resumed from kept scan results teaches nothing), the rewrite's and the pack's from a whole
  run's seconds; a new measurement moves the kept rate by a fifth, always from the value kept before this run (no compounding). The rewrite's time is each game's
  own (`rewrite.<title ID>`: DKB's code rewrites in 74 s, Zelda's in 241 s), and a rewrite that kept a module (pack_android.py's "unchanged, kept": a Retry after
  a stop, a mods change to one module) teaches nothing.
- **Calibration** (Snapdragon 8 Elite, a friend's RedMagic 11 Air, Zelda: Ocarina of Time, 2026-11-07 logs): 41,927 shaders translated in two runs, 18,432 in
  80 min (19:13:36 to the pause at 20:33:28, 0.26 s each) and 23,488 in 2 h 11 min (20:43:54 to the pack step at 22:54:40, 0.33 s each: the phone slows as it
  heats up), 0.30 s each over both with 6 translators; the split of 42,339 shaders in 32 min (18:21:55 to the shaders step at 18:53:54: 0.045 s a map shader), the rewrite
  in 241 s. The 8 Gen 3, 8 Gen 2 and other classes are scaled guesses (**to measure**), and the pack step's 60 s is a placeholder (its log has no end time). On
  the 8 Elite: Zelda ~4 h 10 min, Pokopia (131,426 shaders) ~13 h, a pack with its shaders imported ~6 min. **Open**: the split is charged per shader of the
  map, but it reads RomFS entries (Zelda: 186,583 for 42,339 shaders); Pokopia's split time assumes Zelda's entries per shader, not measured.
- **Time left** (`Job.remaining`, `PrepareState.remaining`): the current step's count left at its measured rate (job.json's `steps.<step>.rate`, kept while
  paused), a counted step not measured yet at the phone's rate (shaders) or its share (split), a step without a count (rewrite, pack) its estimate less its
  time since `steps.<step>.started` (a tenth of it at least), then the remaining steps at the phone's rates.
- **Where**: the card's caption ("Prepares on first play · ~4 h 10 min"; while running "Preparing… · 41% · ~2 h 10 min"), the status line ("Prepared the first
  time you play it: about 4 h 10 min on this phone, once."; running "Translating shaders · 41% · ~2 h 10 min left"; Continue / Try again add "About … left."),
  Prepare's question and the Prepare again / shaders dialogs (`Ondevice.about`, replacing the fixed `ShaderLibs.minutes` ranges), the preparation screen's step
  line and the notification's subtext. Texts: `s2_time_about`, `s2_time_left`, `s2_time_left_sentence`, `s2_first_play_time`, `s2_first_play_shaders_time`
  (values, values-pt); the number itself is the same in both ("12 min", "2 h 30 min", "6 h": a minute under 20 min, 5 under an hour, 10 under 5 h, 30 beyond).
- **Cost**: no file work on the UI thread: the counts come from the card's check (off the main thread), the rates from preferences in memory.

Not verified on a phone (no adb in this change). A step without progress lines (rewrite, pack) only counts down when the service publishes a state.
