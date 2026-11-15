# Isolating coarse-shading artifacts

Ocarina build172's user comparison removes surface stripes with VRS off. New
settings default off; explicit per-game choices remain intact. That comparison
does not yet identify the responsible fragment shader or measure a VRS FPS gain.

With a deliberately enabled VRS rate, `DM_VK_VRS_EXCLUDE_FS` is a diagnostic
comma-separated list of hexadecimal fragment keys. Restart the game after each
change: existing pipelines are not rebuilt live. For example,
`DM_VK_VRS_EXCLUDE_FS=5ad65c0eefd09c7f` keeps that fragment at full-detail shading
and leaves the original VRS policy for all other shaders. It does not skip draws
or alter depth, resolution, shader libraries or bindings. This example is an
isolation target, **not a confirmed culprit or stripe fix**. The filter never
enables VRS on an otherwise ineligible pipeline. Malformed/oversized lists keep
candidate pipelines at full detail; an absent/empty list leaves the policy alone.
Do not toggle layer omission, upscaling or resolution in the same comparison.

The first narrow comparison can exclude the known two-RGBA16F/D32 task/mesh pass
(`5ad65c0eefd09c7f`). If this does not isolate the stripes, compare the scene pair
`1e4d2630d24846d0,19f99e925937b038` separately. Neither is known to be responsible
from the all-VRS-off result alone. Retain the user's accepted VRS-off setting
until a selective configuration has been visually checked on the phone.

Source tests compile and exercise the actual parser and runtime wrapper, including
exact keys, malformed tails and truncation. They do not simulate a physical
Adreno coarse-shading image or prove a selective quality/performance result.
