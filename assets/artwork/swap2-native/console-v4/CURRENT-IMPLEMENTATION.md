# Swap2-Native — current Console revision 6

Updated 2026-11-06 after live user feedback. This revision is the current selection and overrides conflicting asset choices in [the base Console v4 specification](IMPLEMENTATION.md). The containing artwork directory is still called `console-v4` to preserve existing local links. Read `selection.json` there before importing resources.

The user approved the richer library composition, requested matching settings, rejected the typographic-S arrow experiment, requested the original angular cyan/coral logo silhouette recolored black with small colored shadows, and requested a light version for dark mode. Audio must come from ElevenLabs; the intermediate procedural sound experiment is **not selected**.

## Current artwork

| Item | Selected file |
|---|---|
| Light/dark brand board | [brand-v6/brand-board.png](./brand-v6/brand-board.png) |
| Black mark for light mode | [brand-v6/mark-light.svg](./brand-v6/mark-light.svg) |
| Light mark for dark mode | [brand-v6/mark-dark.svg](./brand-v6/mark-dark.svg) |
| Rich library, requested mark | [library-rich-v3.png](./mockups/library-rich-v3.png) |
| General settings | [settings-general-rich-v3.png](./mockups/settings-general-rich-v3.png) |
| Per-game settings | [settings-game-rich-v3.png](./mockups/settings-game-rich-v3.png) |
| Exact new audio prompts | [audio-v3-elevenlabs/PROMPTS.md](./audio-v3-elevenlabs/PROMPTS.md) |
| Current audio delivery metadata | [audio-v3-elevenlabs/delivery.json](./audio-v3-elevenlabs/delivery.json) |
| Current opening with new audio | [boot-preview-current.mp4](./preview/boot-preview-current.mp4) |
| Updated preview and audio audition | [preview/index.html](./preview/index.html) |

PNG screens are visual references, not textures to place over an app. Build actual native focusable, accessible controls. Their fictional cover art, sample player avatar, battery/time and example values are not runtime data. Use recognized game covers and real job/device state. Do not create an online account system, paid services or missing game functionality just because a pictogram appears in the reference.

## Brand v6: original angular arrows, both themes

The current mark interprets the original angular emblem, rather than the rejected curved/typographic S design. Use `brand-v6/geometry.json` and its exact editable SVG/native vector paths. Compact mark = two arrows plus 2; startup lockup adds Swap2-Native beneath it.

- Light theme: near-black `#15171B` arrow faces, numeral and wordmark.
- Dark theme: off-white `#F4F4F2` arrow faces, numeral and wordmark.
- Both: small cyan/coral offset shadows, approximately 1.5 source units. No large glow, colored faces or chromatic animation trails.
- Mark source box is **192x112**, origin -4,-4 in SVG. All separate layers share this box. Do not use v4's 192x108 box or mix old/new layers. Numeral 2 is unchanged in meaning and aligned beside the mark.
- Transparent mark, lockup and separate upper/lower/numeral layers are provided as SVG/PNG. `brand-v6/android/` contains VectorDrawable layers/marks, adaptive icon and monochrome foregrounds, API-26/API-33 icon XML, and legacy density PNGs.
- In Android, layer three identically sized ImageViews (upper/lower/2) and a wordmark TextView; use the base timeline in `motion.json`. On theme change replace all three layers coherently. Do not animate a full PNG/video for runtime startup.

Keep `brand/` v4 and `brand-s-v5/` as history only. They are not selected. App package IDs, activities and signing remain unchanged. Use the new v6 icon resources if replacing the launcher icon; do not accidentally import the older curved v4 adaptive foreground.

## Richer library finish

The approved revision adds controlled depth and game identity, not extra dashboard data:

- A softly enlarged impression of the selected game's real cover in the upper background, approximately 6-10% opacity, under a strong neutral veil. Debounce selection and cache a small blurred/downsampled cover; no per-frame decode or blur, no expensive effects over gameplay. Fall back to the neutral background if the cover is absent.
- Strong selected-title hierarchy, one secondary state/version line and a horizontal square-cover carousel. Cards keep a fixed footprint and bounded labels regardless of game-name length.
- Fine outer focus frame with a subtle cyan/coral offset edge, light shadow/elevation, 1.02x art-only focus scale where reduced motion permits. Give the carousel enough outer padding to avoid clipping focus rings.
- A pale rounded selected-game action shelf, readable status with icon/text, Options and state-appropriate primary action. Keep existing Ready/Prepare/Pause/Continue/Retry logic; the richer styling does not change job semantics.
- A low-profile floating lower dock with original line icons, subtle active plate, label and selected underline. Route each item to an existing local app function. Use keyboard/gamepad hints only when that input is supported; touch users retain normal accessible buttons.
- Preparation stroke stays only on the cover's bottom edge, grows left-to-right from actual progress, and stops while paused. No thick card footer or fake progress.

Approximate finish tokens: panel radius 20-24 dp, button radius 20-24 dp, subtle 1 dp light edge, surface elevation about 2 dp, shadow opacity about 8% in light mode. Prefer static drawable layers and existing elevations to live backdrop blur. Preserve 48 dp practical touch targets, contrast and reduced motion. The screenshot's lighting is an art reference; avoid trying to reproduce it with multiple permanent GPU effects.

## General settings

Use `settings-general-rich-v3.png` as the composition target. A softly inset category rail contains Interface, Audio, Controls, Performance, GPU Drivers and About, each with an original line icon. Selected category is a dark rounded pill with pale text/icon and tiny colored edge detail. Right side uses softly raised rounded panels and readable option rows.

The Interface pane includes a theme-choice card with three live preview tiles (Light, Dark, System), then separate rows for opening animation, reduced motion and interface sounds. The source image's Portuguese text is a UI reference; all native text belongs in localized string resources. Use actual switches, not switches painted into the image. Sound volume belongs in Audio and may be linked from Interface. Changes use the existing preference store and save behavior.

On narrow windows, show a category list followed by its settings page. On wide screens, keep the rail stable and scroll only the option pane when content needs it. Settings are allowed to scroll; the user's no-scroll requirement applies to the full preparation page. Do not shrink category/option text to fit the screenshot at all font scales.

## Per-game settings

Use `settings-game-rich-v3.png`: compact real cover and game identity, a Per-game badge, and the sentence that adjustments affect only this title. Categories: General, Graphics, Controls, Audio, Preparation, Files.

Rows must distinguish **Inherit global** from **Custom** and display the effective inherited value from current preferences/driver choice, not a hardcoded system driver. Example reference fields are resolution, driver, touch profile and performance overlay. Restore defaults affects only the current game's overrides, with the existing confirmation; it never deletes saves, shader caches or global options. Keep controls' game-specific profiles and their per-game edits intact.

Avatar/profile presentation should remain local and generic unless the existing app actually has a profile model. Show only real device time/battery/connectivity and do not request new permissions solely for decorative status symbols.

## ElevenLabs audio revision 3

All nine MP3 files in `audio-v3-elevenlabs/` were generated by actual successful ElevenLabs Sound Effects API calls using the revised prompts. No synthetic replacement is used in the selected set. `prompts.json`, `PROMPTS.md` and `generation.json` record the exact English prompts, parameters, model and generation metadata. The key stayed in the environment and must never enter the APK or logs.

These prompts request single short muted UI impacts and simple rounded tones, with no ambient bed, whoosh, reverb, voices, long tails or recognizable existing console motif. The API accepts containers of at least 0.5 seconds; shorter requested audible lengths are prompt guidance, not a guarantee. For delivery, original recordings were decoded to mono 48 kHz/16-bit, normalized with headroom, trimmed and given short edge fades/duration budgets. Full MP3 originals remain available for comparison and re-editing.

| Cue | Current WAV duration |
|---|---|
| Navigation/focus | 80 ms |
| Confirm | 180 ms |
| Back | 150 ms |
| Panel open / close | 220 / 180 ms |
| Ready | 450 ms |
| Notice/error | 260 ms |
| Game launch | 450 ms |
| Opening | about 839 ms |

Use only WAVs from `audio-v3-elevenlabs/` for new `res/raw` imports. `audio/` (first ElevenLabs set) and `audio-v2/` (procedural experiment) are historical/unselected. The native routing, per-sound readiness, foreground-only playback, deduplication, mute/system policy and master-volume composition in the base specification still apply. Cue gains are now read from the **v3** delivery manifest. Do not mix gains from v1/v2 or play an old generic tap in addition to a semantic cue.

The new audio is ready for user audition, not claimed subjectively approved. The preview opens the new visual references by default and loads these actual v3 WAVs. Use the audio buttons to hear each recording. The Test navigation button opens a native-DOM behavior prototype with illustrative covers; it is an approximation of behavior, while the rich mockups are the visual target. No browser autoplay is attempted on initial page load.

## Implementation and verification

Claude should first import selected v6 brand/v3 audio resources, then apply the rich native layout/theme finish and settings hierarchy using the existing models/actions. Preserve base fullscreen, cover aspect, current selection, asynchronous scan state, fixed-viewport PrepareScreen, touch themes, overlays, services and host behavior. No backend rewrite is required for these visual revisions.

Validate source paths/rectangles, resource resolution, both mark themes, short cue playback, sound-off/system mute, lifecycle, reduced motion, deep links and return from game, job state actions and per-game inheritance. Inspect actual Android UI over 16:9/20:9/21:9/portrait, font scaling, cutouts and keyboard/gamepad/touch focus. The current work supplies reviewed artwork and technically checked media/prototype assets; it does not claim a new APK install, device rendering or a user-approved sound result.

Reference for the original console's structural inspiration: [Nintendo Switch 2 official HOME/settings support screenshots](https://support.nintendo.com/hk/switch2/mastery/accessibility/index.html). The selected brand, effects and sounds are original Swap2-Native assets; do not copy Nintendo interface bitmaps or audio into the product.
