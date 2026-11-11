#!/usr/bin/env python3
"""Build ONLY selected Ocarina GPU bottleneck shaders for the Vulkan hot overlay.

Usage (PC/Mac with the matching translator, game shader package and SPIRV-Tools):
 python3 scripts/build_ocarina_hot_shaders.py \\
   --pkg /path/to/previously-split/pkg \\
   --pack /path/to/installed/game/pack \\
   --key 066f5daf12e43c71 --key efaa4fa6a80ba719

The original 42k-shader library is not modified. The runtime opens the new
partial library at <pack>/shaders/hot/v-<DMSH_VK_CHAIN>/dmsh_vk.lib and
prefers its keys; every other key is read from the existing full library.
This does NOT regenerate all shaders. No changes to the Android package/signing
and no new environment variable are necessary.

The tool accepts either a previously split package or verified runtime
control/code captures from the Ocarina phone session (--capture-dir). A new
shader cannot be translated from an old SPIR-V .lib alone.
"""
from pathlib import Path
import argparse
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GAME = "0400486024DEC000"
DEFAULT_KEYS = (
    "066f5daf12e43c71",  # heavy foliage mesh, from on-device logs
    "efaa4fa6a80ba719",  # task stage paired with heavy foliage mesh
    "5ad65c0eefd09c7f",  # heavy fragment
    "9e6b00b050e30801",  # heavy compute
)
KEY = re.compile(r"[0-9a-fA-F]{16}\Z")


def publish_verified_hot_manifest(manifest, old_vk, new_vk, inputs, abi, keys):
    """Publish one exact reviewed on-device update, never an unverified ABI bypass.

    Caller must have successfully compiled, checked and compared the partial
    library against an existing complete, source-compatible base library.
    Records only the chosen shader keys, not a fictional new 42k full build.
    """
    ids = (old_vk, new_vk, inputs, abi)
    if any(not re.fullmatch(r"[a-f0-9]{12}", x) for x in ids):
        raise ValueError("cannot publish malformed old/new translator, profile or ABI identity")
    if old_vk == new_vk:
        raise ValueError("incremental release must have an actual changed Vulkan translator version")
    keys = sorted(set(keys))
    if not keys or len(keys) > 1024 or any(not re.fullmatch(r"[a-f0-9]{16}", k) for k in keys):
        raise ValueError("no valid, bounded, individually reviewed hot shader keys")
    row = "\t".join((*ids, ",".join(keys)))
    old = manifest.read_text(encoding="utf-8")
    for line in old.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t", 4)
        if len(fields) != 5:
            raise ValueError("existing reviewed hot shader manifest is malformed")
        if tuple(fields[:4]) == ids:
            if line == row:
                return False  # idempotent release publication
            raise ValueError("a different shader-key list is already published for this exact release")
    tmp = manifest.with_name(manifest.name + ".tmp")
    tmp.write_text(old.rstrip("\n") + "\n" + row + "\n", encoding="utf-8")
    os.replace(tmp, manifest)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sources = ap.add_mutually_exclusive_group(required=True)
    sources.add_argument("--pkg", type=Path,
                    help="previously split game shader package directory (NOT the full game dump)")
    sources.add_argument("--capture-dir", type=Path,
                    help="nvn_shdump captured shader pairs from gameplay; compile ONLY selected keys without re-splitting 42k source records")
    ap.add_argument("--pack", required=True, type=Path,
                    help="game pack directory containing the original full shaders/ library")
    ap.add_argument("--key", action="append", default=[], help="additional 16-digit shader key")
    ap.add_argument("--keys-file", type=Path,
                    help="one 16-digit key per line, optionally followed by # comment")
    ap.add_argument("--no-default-keys", action="store_true",
                    help="only translate the --key / --keys-file entries")
    ap.add_argument("--publish-review", action="store_true",
                    help="after full source/ABI validation, write exact old/new keys to the APK's vk_hot_delta.tsv for later on-device updates")
    args = ap.parse_args()

    keys = set() if args.no_default_keys else set(DEFAULT_KEYS)
    keys.update(args.key)
    if args.keys_file:
        for line in args.keys_file.read_text().splitlines():
            line = line.partition("#")[0].strip()
            if line: keys.add(line)
    if not keys or any(not KEY.fullmatch(k) for k in keys):
        ap.error("provide one or more valid 16-hex-digit shader keys")
    keys = sorted(k.lower() for k in keys)

    pack = args.pack.expanduser().resolve()
    capture = args.capture_dir.expanduser().resolve() if args.capture_dir else None
    temp = None
    if capture:
        if not capture.is_dir():
            ap.error(f"missing capture folder: {capture}")
        for key in keys:
            if not (capture / (key + ".code")).is_file() or not (capture / (key + ".ctl")).is_file():
                ap.error(f"capture of selected key {key} is incomplete; play its scene once before a selective build")
        temp = tempfile.TemporaryDirectory(prefix="ocarina-selected-shader-captures-")
        pkg = Path(temp.name) / "pkg"
        pkg.mkdir()
    else:
        pkg = args.pkg.expanduser().resolve()
        if not pkg.is_dir():
            ap.error(f"no shader source folder: {pkg}; old SPIR-V .lib alone cannot compile changed GPU code")
    shaders = pack / "shaders"
    if not shaders.is_dir() or not any(shaders.glob("v-*/dmsh_vk.lib")):
        ap.error(f"{shaders} has no original complete shader library; refusing to build an unsafe overlay")

    env = os.environ.copy()
    env["DM_GAME"] = GAME
    if capture:
        env["DMSH_VK_CAPTURE_DIR"] = str(capture)
        print(f"Selected {len(keys)} runtime-captured shaders; no full game shader split or translated base rebuild required")
    env.update(DMSH_GMEM_FAST1="1", DMSH_GMEM_MAP_8192="1",
               DMSH_GMEM_LAST1="1", DMSH_VK_REQUIRE_ALL="1")
    tool = ROOT / "dm/gfx/tools/vk_android_build.py"
    chain = ROOT / "dm/gfx/tools/dmsh_chain.py"
    # Explicit headers ensure the just-built overlay agrees with the running
    # native host's expected game, toolchain and ABI.
    subprocess.run([sys.executable, str(chain), "--header"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, str(tool), "--header"], cwd=ROOT, env=env, check=True)
    version = subprocess.check_output(
        [sys.executable, str(tool), "--version"], cwd=ROOT, env=env, text=True).strip()

    overlay_root = shaders / "hot"
    print(f"Rebuilding {len(keys)} selected GPU shaders, NOT the entire 42k library:")
    for k in keys: print(" ", k)
    subprocess.run([sys.executable, str(tool), "--target", "vulkan", str(pkg),
                    str(overlay_root), *keys], cwd=ROOT, env=env, check=True)
    output = overlay_root / f"v-{version}" / "dmsh_vk.lib"
    if not output.is_file():
        raise RuntimeError(f"hot overlay build produced no library: {output}")
    subprocess.run([sys.executable, str(tool), "--check", str(output)],
                   cwd=ROOT, env=env, check=True)
    print(f"Validated selective GPU overlay: {output}")
    if args.publish_review:
        # A development release is authorized only AFTER the actual selected
        # SPIR-V has been compiled/validated and a complete old library is
        # checked against the target ABI, game and shader profile inputs.
        # Merely rewriting an ABI/version header would be unsafe.
        tools_dir = ROOT / "dm/gfx/tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        from vk_android_delta import Library
        from ocarina_shader_hot_delta import validated_hot_base
        target = Library(str(output))
        try:
            old_lib = validated_hot_base(pack, GAME, target.chain,
                                         target.version, target.abi,
                                         target.inputs, keys)
            previous = Library(str(old_lib))
            try:
                old_vk = previous.version
            finally:
                previous.close()
            manifest = ROOT / "dm/games" / GAME / "vk_hot_delta.tsv"
            changed = publish_verified_hot_manifest(
                manifest, old_vk, target.version, target.inputs, target.abi, keys)
            print(("Published" if changed else "Already published") +
                  f" exact {len(keys)}-key on-device shader delta: {manifest}")
        finally:
            target.close()
    print("The original stable shader library was not replaced or rebuilt.")
    if temp:
        temp.cleanup()


if __name__ == "__main__":
    main()
