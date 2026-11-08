# Swap2-Native launcher v3 — Android UI handoff

Date: 2026-11-05. UI implementation by Codex; packaging, build and device validation remain with Claude.

## Current implementation

The current launcher is Java in `android/app/src/main/java/dev/nxnative/android/`, not the former ImGui implementation. Use this document for the implementation changes below; the v1 artwork remains the visual reference. The old `output/ui-review` captures are not evidence of this Android UI's current appearance.

The approved library concept keeps its navy background, cyan selection, coral brand accent, cover carousel and explicit Play action. Tapping a cover selects it; it does not launch a game. The existing folder discovery, preparation, readiness and launch paths remain in use.

- `MainActivity.java`: narrow windows (<600 dp) put folder/refresh actions on their own row. The brand ellipsizes instead of colliding with the settings button. Cards size to narrow windows, and status sits below the title so long labels do not consume the game name. The selected-game bar stacks its details above its actions on narrow windows. A dedicated gear opens game settings; Manage remains separate.
- Selection and library scroll positions survive settings navigation, configuration changes and saved-instance restoration. Per-game settings return to their previous vertical position after changing a choice.
- General settings add an Interface group with persisted sound and reduced-motion preferences. Existing game defaults, system tools and diagnostics retain their existing behavior. New labels have English and Portuguese resources; pre-existing detailed technical dialogs and several explanatory values still use English.
- `GameSettings.java`: game settings now occupy a full scrolling page, with game identity, an inheritance explanation, graphics/gameplay settings, and a separate Advanced section. Default still follows the global values; overrides remain keyed by title ID using the existing Prefs/GpuDriver implementation. Unsupported resolution choices remain hidden.
- `Ui.java`: vector icon tiles on the updated settings pages, 48 dp icon buttons, labeled switches, and row toggling where there is no separate row action.
- `LauncherEffects.java`: 180 ms fade/vertical entrance, disabled by the UI preference or Android animator settings. Static cyan selection elevation and existing focus/ripple effects provide feedback without a continuous animation loop. No particles, video background or per-frame work is introduced.

## Approved icon

The current Android project already has the v2 launcher icon wired through `AndroidManifest.xml`: `@mipmap/ic_launcher`, `@mipmap/ic_launcher_round`, adaptive v26 and monochrome v33 resources. `Ui.badge()` uses `drawable-nodpi/s2_brand.webp`, the matching cropped brand symbol. This revision reuses it in the home and general-settings headers; do not replace it with the older flat `s2_symbol`.

Original exports: `assets/artwork/swap2-native/icon/android-v2/`. The older icon handoff's legacy project path is superseded by `android/app/src/main/res/`.

## Sound

`res/raw/s2_tap.wav` is an original synthesized 75 ms PCM16 mono sound, 24 kHz. Regenerate with `python tools/generate_launcher_sound.py`. No API key, network call, external audio dependency or ElevenLabs usage is needed.

SoundPool loads asynchronously on launcher resume and releases on pause. Buttons use a low playback gain; no audio focus is requested. Sound is suppressed when disabled in Interface, when Android sound effects are disabled, or when the ringer is silent/vibrate. It is not a game sound system. Loading failure or a tap before loading completes is silent. Existing native Android dialogs retain platform feedback.

## Validation handoff to Claude

Build and device checks are pending. Codex performed resource/XML/reference checks and diff inspection only; no device was restarted, no APK was installed, and no runtime/packager/shader file was changed for this UI revision.

1. Compile the launcher with the normal supported Gradle configuration, then test the UI-only/fake pack mode where appropriate. Report compilation errors before integration into the real game run.
2. Capture empty and populated libraries at 360 dp portrait, 600 dp split-window/tablet, and short landscape. Include a cutout and large font (1.3x and 2x). Check no overlap, every action reachable by scrolling, cover proportions preserved, and title/status readability. No invented game entries or covers in production.
3. Select a game late in the carousel; open global settings, return, open game settings, change a choice, rotate, return, and recreate the activity. Confirm selected game and library scroll position survive. Check Back from a picker/dialog returns to its owning page.
4. Verify every existing resolution/FPS/GPU-driver option still writes the same preference and takes effect on the next game launch. Test global inheritance versus explicit overrides on two different title IDs. Confirm unavailable resolution/host-limited FPS cases remain clear and honest.
5. Test game settings from both the new gear and Manage. Test folders, logs, saves, and preparation while navigating; progress must resume only on the library page. Confirm launch still happens only from Play.
6. Verify touch targets and keyboard/controller focus. Check TalkBack announces settings titles, switches and game actions. Confirm no duplicate sound on custom actions; silent/vibrate, zero volume, system sound-effects off, and the UI sound switch suppress playback. Backgrounding must release the pool.
7. Disable animations in Android and in Interface independently. Confirm page entrance is immediate, navigation still works, and no background animation loop remains. Rapidly open/back through pages and change settings to catch stale view callbacks.
8. Inspect installed icon in circle/squircle masks and Android themed icons. Compare home/settings brand against the approved cyan/coral icon. Capture screenshots of home, global settings, per-game settings and advanced options for visual approval.

Remaining visual acceptance requires those real Android captures; the earlier design mockups are references, not screenshots of this revision.

## Card title alignment fix — 2026-11-05

Observed directly in an ADB screenshot of the connected phone (`output/ui-review/library-long-name-before.png`): the Zelda title occupied two lines while Mario Kart World occupied one, pushing Zelda's badge and bottom edge down. The title TextView previously had only a maximum of two lines, so its measured height depended on the title.

`MainActivity.card()` now reserves exactly two text lines for every title, top-aligned with end ellipsis. Line height still follows Android font scaling instead of a fixed pixel height. Card widths and cover sizes are unchanged. The preparation summary remains a separate conditional section.

Claude validation: rebuild and compare these same two cards on the phone; title areas, ordinary status badges and bottom edges should align when the cards have the same preparation-summary state. Also check a title exceeding two lines and large font scaling. The screenshot records the pre-fix installed build; the source fix has not been installed by Codex.

## Minimal perimeter progress — supersedes the inset summary

User visual correction on 2026-11-05, verified against the connected phone (`output/ui-review/library-border-before.png`): remove the preparation panel inside the card. Preparation must not increase card height.

`CardProgressBorder.java` now draws a 3 dp progress stroke clockwise around the rounded card perimeter, starting at top center, using only `PrepareState.overall`. There is no internal progress bar, stage text block or additional layout row. The existing status badge remains; detailed steps and errors stay on PrepareScreen. Select the card and use Play to reopen preparation, as before. TalkBack receives state, percentage and step through the card description.

The ordinary selection outline is retained when idle; during preparation a thin inset focus outline distinguishes selection from the progress stroke. Running uses cyan, paused amber, failed coral and playable green. The border updates in place without an animation loop or layout changes. Null/different snapshots restore the normal card border and badge.

Claude validation pending: build and inspect 0%, 1%, 25%, 50%, 100%, paused and failed states on selected/unselected cards; confirm equal card heights, rounded corners without clipping, no stale progress after job removal and normal controller focus. Codex captured the existing screen but did not build/install this revision.

## Cover-first cards — 2026-11-05

User refinement supersedes the wide cover plus text-footer layout. Library cards are now square (176 dp in short landscape; up to 240 dp otherwise), with the cover occupying the entire card. Square eShop artwork fills the tile; different aspect ratios use FIT_CENTER to preserve the complete image. The blurred duplicate backdrop was removed.

The title uses normal capitalization, 14 sp semibold, at most two lines over a bottom gradient. It no longer reserves an opaque footer or changes the tile dimensions. Status pills are removed from the visible card; the selected-game details bar and accessibility expose status. Preparation progress remains on the perimeter. Missing artwork keeps the controller placeholder and readable title. Tap still selects, Play still launches, long press still opens Manage.

Claude visual validation pending: compare real square covers, missing covers, non-square art and long titles in portrait/landscape and large font settings; check the selected-game status updates while preparation runs. No build or install performed by Codex for this change.

## Immersive edge-to-edge launcher — 2026-11-05

User requested a continuous screen without the lateral cutout/system-bar bands. `Ui.page()` now configures full-window drawing with `setDecorFitsSystemWindows(false)`, `LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS`, transparent system bars and transient system-bar reveal by edge swipe. The shared page reapplies immersive mode when its window regains focus. Both day/night launcher themes declare the same cutout and contrast policy.

The background remains full bleed. Insets apply only to interactive content; the previous opaque status-bar scrim was removed, and scrolling content clips to its safe padding. Width calculations use current window metrics for split-window layouts. The game renderer and host are unchanged. This is edge-to-edge presentation, not an endlessly repeating library carousel.

References: [Android immersive mode](https://developer.android.com/develop/ui/views/layout/immersive) and [display cutouts](https://developer.android.com/develop/ui/views/layout/display-cutout).

Static XML parsing and diff whitespace checks passed. Claude should build and verify portrait/landscape with the physical camera cutout, gesture and three-button navigation, temporary bar reveal, returning from pickers/dialogs, keyboard, rotation and multi-window. Confirm the background reaches all edges while controls remain accessible; platform-managed window decorations may remain in multi-window. No build/install performed by Codex.

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


## Console v4 visual handoff (2026-11-06)

The [Console v4 specification](SWAP2-NATIVE-CONSOLE-v4.md) supersedes the earlier launcher logo/palette direction with two dark arrows plus a numeral 2, restrained cyan/coral shadows, light/dark neutral themes, native startup motion and nine generated UI sounds. It is a design/resource handoff; production integration remains pending. Existing job flows, game data and themed touch controls are preserved.
