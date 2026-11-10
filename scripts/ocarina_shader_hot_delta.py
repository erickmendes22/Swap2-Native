"""Validated on-device partial update: keep the old full library, replace only reviewed shaders.

Never restamp a previous compiler's complete library as if every shader had
been rebuilt by a new compiler. The Vulkan runtime already knows how to load
a compatible old full library plus shaders/hot/v-current/dmsh_vk.lib. This
function only validates that the smaller overlay and the full base agree
on title ID, shader inputs and the GPU ABI before the pack is declared ready.
"""
from pathlib import Path
import re
import sys

TOOLS = Path(__file__).resolve().parents[1] / "dm/gfx/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import vk_android_delta as delta

HOT_KEYS = re.compile(r"[0-9a-f]{16}\Z")


def validated_hot_base(pack, game, current_chain, current_vk, abi, inputs, keys):
    """Return the old full library used by a safe selected-key overlay.

    Raises ValueError without deleting any file or rewriting the full library.
    'keys' is the reviewed per-release list, not guessed from old SPIR-V.
    """
    pack = Path(pack)
    keys = list(keys)
    if not keys or len(keys) > 1024 or len(set(keys)) != len(keys) or any(
        not HOT_KEYS.fullmatch(k) for k in keys
    ):
        raise ValueError("hot update: missing, duplicate, or malformed reviewed shader keys")
    hot = pack / "shaders" / "hot" / f"v-{current_vk}" / "dmsh_vk.lib"
    if not hot.is_file():
        raise ValueError(f"hot update: selected shader overlay not finished: {hot}")
    overlay = None
    try:
        overlay = delta.Library(str(hot))
        if (overlay.game, overlay.chain, overlay.version, overlay.abi, overlay.inputs) != (
            game, current_chain, current_vk, abi, inputs
        ):
            raise ValueError("hot update: current partial library has wrong game, translator, GPU ABI or profile")
        if set(overlay.index) != set(keys):
            raise ValueError(f"hot update: partial library has {len(overlay.index)} entries but must hold exactly {len(keys)} reviewed keys")
        for i in range(overlay.ne):
            overlay.entry(i)  # every binding, module and compressed range must fit
    finally:
        if overlay is not None:
            overlay.close()
    root = pack / "shaders"
    candidates = sorted(
        [p for p in root.glob("v-*/dmsh_vk.lib") if p.parent.name != f"v-{current_vk}"],
        key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    for p in candidates:
        base = None
        try:
            base = delta.Library(str(p))
            if (base.game, base.abi, base.inputs) != (game, abi, inputs):
                continue
            if base.version == current_vk or base.ne <= len(keys):
                continue  # never treat a partial library as the fallback full game
            # Prior complete library must have every shader the game's profile
            # expects except keys that were untranslatable in that older build.
            # The full source manifest is authoritative for the actual count,
            # and no old entry may be re-labelled to the newer translator.
            if base.ne < 40000:
                continue  # Zelda's complete current profile has 42,339 keys
            for i in range(base.ne):
                base.entry(i)
            return p
        except (OSError, ValueError):
            continue
        finally:
            if base is not None:
                base.close()
    raise ValueError("hot update: no complete earlier Ocarina shader library with matching game, inputs and ABI; refusing to replace it with a partial library")
