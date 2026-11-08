# Swap2-Native Console v4 — visual, motion and audio implementation

> Current selection is revision 6: use brand-v6 and audio-v3-elevenlabs. The rich library and general/per-game settings supersede the first flat mockups. See [CURRENT-IMPLEMENTATION.md](CURRENT-IMPLEMENTATION.md).

Date: 2026-11-06. User direction: a console-style launcher with a compact mark made from two opposing black arrows and a numeral 2, tiny cyan/coral offset shadows, and an animated startup where Swap2-Native appears beneath it. This delivery contains editable visual assets, Android resource templates, motion data, nine actual ElevenLabs sounds, mockups, a local interactive prototype and a rendered opening video. **The production APK/source UI has not been changed by this delivery.** Claude owns the native integration.


## Historical audio revision v2 (superseded)

The procedural `audio-v2/` experiment is retained only as history. It is not selected. The user explicitly requested a new ElevenLabs generation; use `audio-v3-elevenlabs/` and the current revision document instead. Older video/audio links below describe the initial package and are superseded by the selection table in the current revision.

## Open and review

- [Brand board](./brand/brand-board.png): light/dark versions of the approved direction.
- [Opening video with sound](./preview/boot-preview-audio-v2.mp4): a 1.5 s opening followed by a short library hold, 3 s total.
- [Interactive prototype](./preview/index.html): open locally in a browser. Replay the opening, change theme, select cards, open settings/prepare/empty/loading, and audition every sound. Browser audio starts only after a user interaction.
- [Light library](./mockups/library-light.png), [dark library](./mockups/library-dark.png), [general settings](./mockups/settings-general.png), [game settings](./mockups/settings-game.png), [preparation](./mockups/prepare.png), [empty state](./mockups/empty.png), [loading](./mockups/loading-light.png).

Cover illustrations and progress values are examples for layout review only. At runtime use the real game's cover from `Covers`, title and job snapshot. Never replace recognized game art with these example illustrations or show the sample 32% as live progress. The prototype demonstrates transitions; its settings rows are illustrative and do not implement native preferences.

## Package contents

The root folder is `assets/artwork/swap2-native/console-v4/`.

| Path | Purpose |
|---|---|
| `brand/geometry.json` | Exact arrow/numeral paths, view box, shadow offsets and theme foreground colors |
| `brand/mark-*.svg` / `.png` | Transparent compact mark: two arrows + 2 |
| `brand/lockup-*.svg` / `.png` | Mark with Swap2-Native beneath it |
| `brand/arrow_upper-*`, `arrow_lower-*`, `number_2-*` | Separate full-canvas layers for animation |
| `brand/ic-*.svg` | Original app navigation/action pictograms; use native tint |
| `android/s2_mark_v4_*.xml` | VectorDrawable compact marks |
| `android/s2_arrow_*`, `s2_number_2_*` | Separate aligned VectorDrawable animation layers |
| `android/s2_icon_v4_*.xml` | Adaptive icon foreground/background/monochrome templates |
| `android/mipmap-anydpi-v26`, `mipmap-anydpi-v33` | Adaptive icon templates, including Android 13 monochrome |
| `android/mipmap-{density}` | 48/72/96/144/192 px legacy icons |
| `android/values`, `android/values-night` | Light/dark semantic color resource templates |
| `tokens.json` | Theme colors, typography, spacing, radii, touch and focus sizes |
| `motion.json` | Timing, movement and playback policy |
| `audio-v2/*.wav` | Selected revision: delivery audio, mono PCM 48 kHz / 16-bit |
| `audio/*.mp3` | Original ElevenLabs generations, retained for provenance |
| `audio/generation.json` | Exact prompts, model and response metadata; no credentials |
| `audio/delivery.json` | Actual file durations, peak/RMS levels and suggested cue gains |
| `mockups/*.svg` / `.png` | Editable screen references and raster previews |
| `preview/index.html`, `preview/boot-preview.mp4` | Review artifacts; not runtime UI |

All final logo/screen graphics were authored as SVG/native vectors and rendered from those sources. An image-generation attempt for a library mockup was rejected; no generated mockup from that attempt is part of the selected package. Regenerating the logo with an image model is unnecessary: its exact paths are supplied. The script `tools/generate_console_audio.py` regenerates missing authorized audio using an environment key; it never belongs in the APK.

## Identity and theme

- Compact mark: opposite arrows left, black numeral 2 right. The shadows are small cyan `#42D4E5` / coral `#FF777D` offsets, not full colored arrow faces. Source offsets are 2 units; scale them with the mark, never into a neon glow.
- Light theme: off-white `#F4F4F2`, white surfaces, near-black `#15171B` text and focus. Dark theme: graphite `#17191D`, lighter graphite surfaces, off-white foreground including the mark for contrast. Full details are in `tokens.json`.
- Colors do not dominate the screen. Keep cyan/coral as brand accents. Preparation stays warm yellow, success and errors use accessible semantic colors; text must state the status too.
- Use the current system sans-serif family. The SVG wordmark uses Arial/system fallback as a reference; in Android render exact text `Swap2-Native` in the same system semibold family as the launcher. No custom Nintendo font or proprietary system UI asset is included.
- User preferences: Theme = System / Light / Dark, Interface sounds on/off, Interface volume 0..100%, Opening animation on/off, Reduce motion. Preserve existing `interface.sounds` and `interface.reduced_motion`; add versioned keys for new values. Default volume suggestion 35%, without overriding saved choices.
- Add semantic `s2v4_*` colors and theme-aware UI helpers rather than blindly replacing every `bn_*` color. Game overlays/touch themes must retain their separate palettes. Respect `values-night`, manual theme choice and theme-change recreation while preserving current page/selection.

## Startup sequence

Use native layers, not video playback or WebView. The MP4 is only a review artifact. Use the full-canvas upper arrow, lower arrow and numeral VectorDrawables in three identically sized stacked ImageViews, with a separate TextView for the wordmark. All layers share one alignment box; intrinsic path bounds must not shift their centers.

| Time | Motion |
|---|---|
| 0..440 ms | Upper arrow enters from x=-36 dp and fades to 1 |
| 120..560 ms | Lower arrow enters from x=+36 dp and fades to 1 |
| 420..660 ms | Numeral 2 fades in with a 5 dp upward settle |
| 660..900 ms | Swap2-Native appears below with a 6 dp upward settle |
| 900..1320 ms | Mark holds still |
| 1320..1500 ms | Startup surface fades into the already prepared library |

Scale translation to the actual displayed mark: the dp values describe the nominal 192x108 alignment box. Use `PathInterpolator(.2f,.8f,.2f,1f)` for arrows and a simple decelerating fade for the remaining layers. Start `boot` once near sequence start, only if it is already loaded and sound settings permit. Do not delay the UI waiting for audio and do not play the signature late after the library appears.

Show the full opening once for a normal cold launcher start, not every resume, rotation, return from a game, picker result or settings change. Keep an in-process guard and saved-instance state; external Play/deep-link intents should continue directly to their existing destination. A fresh process may show it again if the user leaves opening enabled. Reduced motion or system animator scale off: static mark crossfade at most 120 ms, no translations. Opening disabled: direct library. A skip action cancels animations and the boot stream cleanly.

Android 12+ already supplies a system splash. Match its background and static vector to the chosen theme, then dismiss it promptly into the native intro/library; do not hold two separate branded loading screens or add a fixed wait to system startup. Configure API-31 platform splash theme attributes in versioned resources. Use the existing Activity architecture; no AndroidX migration is required solely for this design. See [Android splash mechanics](https://developer.android.com/develop/ui/views/launch/splash-screen).

Scan/load library data asynchronously while the intro runs. If the data is still unavailable after the maximum opening, show the supplied loading state with three quiet indeterminate dots and the honest label Carregando biblioteca. Do not invent percentages or a minimum scan duration. Once loaded, switch to library or the empty state. Work continues independently of intro visibility.

## Library and preparation states

Use a horizontally snapping row of square covers with modest 12 dp corner radius. Maximize cover area; place title/status beneath the artwork with bounded height, at most two title lines. A long name must never grow the card or the entire carousel. Focus is a crisp 3 dp monochrome ring outside the cover with safe padding; subtle 1.02x visual emphasis is optional. No thick glow. Preserve selection by title ID across refreshes.

The lower detail strip describes the selected game and offers its actual action. The preparation border is a thin stroke along only the bottom edge, growing left to right; interpolate old-to-new real job values over 220 ms. It must not imply progress while paused.

| Actual state | Detail action |
|---|---|
| Valid ready pack | Jogar, neutral black/white primary |
| Needs preparation | Preparar, warm yellow |
| Preparation running | Pausar, warm yellow; secondary access to the full preparation screen |
| Paused | Continuar, warm yellow |
| Failed and retry allowed | Tentar novamente, with readable error details |
| Unsupported/missing prerequisite | Show the reason and the appropriate existing check/import action; never enable Play |

The browser prototype uses Ver preparação for its mocked running item so that a demo click opens the sample page. The table above and the existing service/state contract govern native behavior; do not copy the demo's simulated job logic.

Bottom navigation contains existing actions only: library, choose/change folder, controls settings, general settings, profile/about. Do not invent an account requirement or an online store. If the app has no user profiles, route the profile pictogram to its existing local app information or omit it until implemented. Preserve long-press/manage and selected-game Options.

The full preparation page remains **without scrolling**: compact identity and progress panel, one stage strip, fixed Back and applicable Pause/Continue/Play action. Preserve the latest `PrepareScreen` fixed-viewport work, job callbacks and long-status dialog. Do not restore a page-sized ScrollView or the old vertical five-step list. Reopening a running job must not restart translation.

## Settings

Wide screens: a category column on the left and readable option rows on the right. General categories: Interface, Audio, Controls, Performance, Drivers, About. Game settings: General, Graphics, Controls, Audio, Preparation, Files. Use the real current options and feature availability; mockups are examples of hierarchy.

Settings lists may scroll inside the right pane when needed, independently of the stable category column. On narrow/portrait screens use a category list followed by its options page, preserving a normal Back stack. Do not compress labels into unreadable two-pane columns. Target 48 dp rows/touch controls, clear selected states and visible keyboard/gamepad focus.

Each game option distinguishes Inherit global from an explicit override; show the effective value. Restore this game only clears that game's overrides after the existing confirmation, never global options, files or shader caches. Reuse `Prefs`, `GameSettings`, driver and touch profile selection logic. Preserve Zelda 40, standard v2, DK and Mario Kart control skins. Theme changes are launcher presentation, not renderer/shader settings.

## Motion and effects

`motion.json` is authoritative for timings. Implement with current ViewPropertyAnimator/ValueAnimator helpers in `LauncherEffects` and `Ui`; avoid an animation framework dependency.

- Page enter: 180 ms fade with 8 dp travel. Exit/back: 120 ms, opposing direction. Animate only the content region; keep the app frame steady.
- Options sheet: 220 ms with 16 dp travel, dim backdrop, focus trapped until close; return focus to the originating card/button.
- Carousel: 160 ms snap; focus emphasis 90 ms, press 60 ms at 0.98 art scale. Hit targets do not move with decorative feedback.
- Progress: 220 ms interpolation of reported values. Loading dots: 900 ms cycle, foreground only, no sound loop.
- Cancel old animators on rebind, replacement, background and detach. Do not allocate bitmaps in draw/layout or run permanent animations when idle. Avoid blur/particle effects over game surfaces.
- Honor both the existing reduced-motion preference and `ValueAnimator.areAnimatorsEnabled()`. Reduced motion keeps focus/contrast feedback and state changes without travel or scaling. No flashing effects.

## Audio delivery and routing

The files were actually generated through [ElevenLabs Sound Effects](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert), using the configured environment key. Original prompts request original console-like timbres without an existing console motif. No Nintendo audio was copied. Original MP3s and generation metadata are retained; delivery WAVs were trimmed/faded/normalized with conservative headroom. The source API model is recorded in `audio/generation.json`.

| Cue / raw resource name | Event |
|---|---|
| `s2_boot.wav` | Once on the enabled normal launcher intro |
| `s2_focus.wav` | Actual selection change; throttle to once per 120 ms; 100 ms delivered clip |
| `s2_confirm.wav` | Accepted confirm/toggle, including pause/resume |
| `s2_back.wav` | Back to previous app screen |
| `s2_panel_open.wav` | Options/settings panel opens |
| `s2_panel_close.wav` | Panel closes |
| `s2_ready.wav` | Observed preparation transition to ready, once per job completion |
| `s2_error.wav` | Action rejected with a visible explanatory message, not every status poll |
| `s2_launch.wav` | Accepted Play intent, once, before entering game |

Copy WAVs into `res/raw/`. Extend `LauncherEffects` with a cue enum/map, 3 SoundPool streams and per-resource load readiness. The current single `ready` boolean/tap-only member is insufficient for asynchronous multi-sample loading. Ignore stale callbacks after release; skip an unloaded cue rather than queueing it for late playback. Load/release with the existing activity lifecycle. Android recommends SoundPool for predecoded short sound effects; see [SoundPool reference](https://developer.android.com/reference/android/media/SoundPool).

Final playback gain = stored interface volume × cue gain from `delivery.json`. Do not multiply it twice. A default 35% volume with 0.22 focus / 0.40 other cue gain is intentionally quiet. Respect system sound-effects preference, silent/vibrate/DND expectations and user mute; no audio-focus takeover or background loops. Do not change game/audio-renderer volume. Stop UI streams on leaving the launcher, intro cancellation and activity pause.

One action gets one semantic cue. Do not keep the old generic tap plus a new confirm simultaneously. No sounds on redraw, scan updates, fake focus events, scrolling inertia, restored initial selection or held touch gameplay inputs. Repeated preparation polling must not replay ready/error chimes: compare transition plus stable job ID. Foreground completion only; the background service's notification behavior remains independent.

The sounds passed technical PCM/peak/duration checks, not subjective approval by the user. Audition all nine in the prototype/normal speakers/headphones before final volume tuning. The environment API key stays outside files/logs/APK. Native playback is entirely offline; no ElevenLabs API or credentials in the app.

## Claude implementation sequence and boundaries

1. Import vector/PNG/icon and WAV resources under new names. Keep old resources until references and resource shrinking are checked. The adaptive templates reference drawable resources; put foreground/background/monochrome XML under drawable, adaptive icons under the supplied mipmap-anydpi folders, legacy PNGs under density folders. Update both manifest icon/roundIcon references together when the new icon is selected.
2. Add theme tokens/manual theme preference using `Ui`, day/night resources and existing fullscreen handling. Preserve root edge-to-edge background and actual cutout-safe interactive content. Keep stable card dimensions on font/locale changes.
3. Update library and general/game settings composition in `MainActivity`/`GameSettings`, with data/actions supplied by existing models. Keep folder import, pack validation, readiness, saves and service IPC unchanged.
4. Extend `LauncherEffects` with lifecycle-safe motion and cue routing, then add native intro layers over the existing Activity instead of another splash Activity. Persist navigation/selection and skip deep links/hot resumes.
5. Re-skin `PrepareScreen` while preserving fixed-viewport geometry and all service actions. Keep touch/overlay/game renderer behavior unchanged.
6. Run Java/resource build and meaningful UI/input/state checks. Only then generate/install an APK according to the current user's authorization and active preparation state. Do not interrupt a running preparation as a side effect of a visual preview.

No host, shader chain, NSO patch, packer, game files or current device state is changed by this design delivery.

## Acceptance and actual verification

Native integration must cover:

- Cold start, hot resume, rotation, process recreation, disabled intro, reduced/system-disabled animation, direct Play intent, foreground/background mid-animation and slow library scan. No double splash, artificial scan delay or accidental job restart.
- 16:9/20:9/21:9, portrait/narrow window, full-screen cutouts, font scale and long localized titles; covers remain square, selection is reachable, prepare page does not scroll, settings panes scroll only where required.
- Ready / needs prepare / running / paused / failed / unsupported and stale async callbacks. Correct action label, enabled state, progress ownership and selected-game details.
- General versus game overrides, actual supported drivers, controls/overlay settings and persistence. Theme changes must not reset state or affect gameplay rendering.
- Sound mute, master volume, system sound setting, silent/vibrate, headphones, fast repeated focus, cue-not-loaded, background, game start and old pool callback. No double cue, clipping, hanging sound or replayed completion.
- Accessibility labels, contrast in both themes, keyboard/gamepad navigation and focus return; utility icon actions match their actual function.

For this delivery: vector/XML/JSON/media assets were structurally checked; SVG mockups were rendered and visually inspected; JS syntax and screen/handler rendering are checked locally; WAVs have known format/peaks and MP4 duration is 3 s. The computer-use browser could not reach the local preview server, so a real browser interaction/audio audition is not claimed. No Android build, installation, actual phone UI or received game-input test is claimed for this package.
