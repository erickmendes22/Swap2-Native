#!/usr/bin/env python3
"""Conservative Ocarina Vulkan ABI migration certificates.

An ABI digest change does NOT automatically require retranslating every shader:
old modules remain usable when the host-visible contract was only EXTENDED.
A certificate is produced only from two checked-in historic ABI headers and
the current headers, and only if every old symbol, struct and convention is
unchanged. Changed values/layouts/revisions REFUSE certification.

The Vulkan host accepts the old library byte-for-byte using only compiled,
audited certificates. All other transitions use existing per-key hash deltas
from a new reference build (vk_android_delta.py); never restamp an unverified
full library to a new ABI.
"""
import argparse
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
GAME = "0400486024DEC000"
PROFILE = ROOT / "dm/games" / GAME
ABI_VK = ROOT / "dm/gfx/nvn/dmsh_abi_vk.h"
ABI_COMMON = ROOT / "dm/gfx/nvn/dmsh_abi.h"
CHAIN_VK = ROOT / "dm/gfx/nvn/dmsh_chain_vk.h"
TARGET = ROOT / "dm/gfx/vk_android/vka_abi_compat.h"
MANIFEST = PROFILE / "vk_abi_compat.tsv"
HEX12 = re.compile(r"[a-f0-9]{12}\Z")
DEFINE = re.compile(r"^\s*#define\s+([A-Z][A-Z0-9_]*)\s+(\S+)\s*$")
VERSION = re.compile(r'#define\s+(DMSH_VK_CHAIN|DMSH_VK_ABI)\s+"([a-f0-9]{12})"')


class UnsafeMigration(ValueError):
    pass


def stripped(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


def canonical(src):
    return " ".join(stripped(src).split())


def abi_digest(vk: Path, common: Path):
    h = hashlib.sha256(b"dmsh_vk_abi\0")
    for p in (vk, common):
        h.update(p.name.encode() + b"\0" + canonical(p.read_text()).encode() + b"\0")
    return h.hexdigest()[:12]


def defines(src):
    symbols, rest = {}, []
    for line in stripped(src).splitlines():
        match = DEFINE.fullmatch(line.strip())
        if match:
            if match[1] in symbols:
                raise UnsafeMigration("duplicate ABI constant " + match[1])
            symbols[match[1]] = match[2]
        elif line.strip():
            rest.append(line)
    return symbols, canonical("\n".join(rest))


def additive_compatible(old_vk: Path, old_common: Path,
                        new_vk: Path = ABI_VK, new_common: Path = ABI_COMMON):
    """Only additive unused descriptor kinds, module variants or flag bits.

    The host's non-macro declarations and ALL original constants must remain
    semantically byte-identical (ignoring comments/whitespace); the common
    NVIDIA/NVN ABI cannot change at all. An ABI_REV bump is deliberately
    incompatible, even if the other header happens to be unchanged.
    """
    if canonical(old_common.read_text()) != canonical(new_common.read_text()):
        raise UnsafeMigration("common NVN ABI changed: cannot reuse previous SPIR-V")
    old_defs, old_structs = defines(old_vk.read_text())
    new_defs, new_structs = defines(new_vk.read_text())
    if old_structs != new_structs:
        raise UnsafeMigration("Vulkan ABI structs or field layout changed")
    for key, value in old_defs.items():
        if new_defs.get(key) != value:
            raise UnsafeMigration(f"changed or removed ABI constant {key}")
    added = set(new_defs) - set(old_defs)
    if not added:
        raise UnsafeMigration("ABI differs but no explicitly safe additive symbol was found")
    for key in added:
        val = new_defs[key]
        try:
            number = int(val, 0)
        except ValueError:
            raise UnsafeMigration(f"new ABI value is not a literal: {key}")
        if key.startswith("DMSH_VK_KIND_"):
            used = {int(v, 0) for k, v in old_defs.items()
                    if k.startswith("DMSH_VK_KIND_") and v.isdigit()}
            if number in used or not (0 < number < 255):
                raise UnsafeMigration(f"descriptor kind collision {key}")
        elif key.startswith("DMSH_VK_MOD_"):
            used = {int(v, 0) for k, v in old_defs.items()
                    if k.startswith("DMSH_VK_MOD_") and v.isdigit()}
            if number in used or not (0 <= number < 255):
                raise UnsafeMigration(f"shader module variant collision {key}")
        elif key.startswith("DMSH_VK_F_"):
            used = 0
            for k, v in old_defs.items():
                if k.startswith("DMSH_VK_F_") and v.isdigit():
                    used |= int(v)
            if number <= 0 or number & (number-1) or number & used:
                raise UnsafeMigration(f"shader flag collision {key}")
        else:
            raise UnsafeMigration(f"new ABI constant {key} is not additive-safe")
    return tuple(sorted(added))


def current_versions():
    values = dict(VERSION.findall(CHAIN_VK.read_text()))
    if "DMSH_VK_ABI" not in values or "DMSH_VK_CHAIN" not in values:
        raise UnsafeMigration("current Vulkan shader version header is malformed")
    if values["DMSH_VK_ABI"] != abi_digest(ABI_VK, ABI_COMMON):
        raise UnsafeMigration("current Vulkan ABI header is stale: regenerate with vk_android_build.py --header")
    return values


def certificates():
    versions = current_versions()
    certs = []
    if not MANIFEST.is_file():
        return certs
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cells = line.split("\t")
        if len(cells) != 5:
            raise UnsafeMigration("ABI transition must be old_vk, old_abi, new_vk, new_abi, inputs")
        old_vk, old_abi, new_vk, new_abi, inputs = cells
        if any(not HEX12.fullmatch(s) for s in cells):
            raise UnsafeMigration("ABI transition contains a malformed hexadecimal identity")
        if (new_vk, new_abi) != (versions["DMSH_VK_CHAIN"], versions["DMSH_VK_ABI"]):
            raise UnsafeMigration("ABI transition target is not this APK's Vulkan ABI and translator")
        src = PROFILE / "abi_history" / old_vk
        old_vk_header = src / "dmsh_abi_vk.h"
        old_common_header = src / "dmsh_abi.h"
        if not old_vk_header.is_file() or not old_common_header.is_file():
            raise UnsafeMigration("historical ABI source headers missing for " + old_vk)
        if abi_digest(old_vk_header, old_common_header) != old_abi:
            raise UnsafeMigration("historical ABI snapshot digest mismatch for " + old_vk)
        additive_compatible(old_vk_header, old_common_header)
        if old_abi == new_abi or old_vk == new_vk:
            raise UnsafeMigration("a cross-ABI migration requires distinct ABI and version")
        if (old_vk, inputs) in [(x[0], x[4]) for x in certs]:
            raise UnsafeMigration("duplicate ABI transition")
        certs.append(tuple(cells))
    return certs


def c_header(certs):
    # Immutable C data is trusted because the CI generator independently
    # checked both headers, exact old/new ABI digests and additive-only rules.
    rows = "".join(
        '    {"%s", "%s", "%s"},\n' % (c[0], c[1], c[4])
        for c in certs
    ) or '    {"", "", ""},\n'
    return (
        "// Generated by vk_abi_migrate.py after source-level ABI audit.\n"
        "// Never accept a mismatched ABI by changing only its version header.\n"
        "#pragma once\n"
        "typedef struct { const char *old_vk; const char *old_abi; const char *inputs; } vka_abi_approved;\n"
        "#define VKA_ABI_COMPAT_COUNT %d\n" % len(certs)
        + "static const vka_abi_approved vka_abi_compat[] = {\n"
        + rows + "};\n"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--header", action="store_true")
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    try:
        certs = certificates()
        if args.check:
            if not TARGET.is_file() or TARGET.read_text() != c_header(certs):
                raise UnsafeMigration("generated ABI transition header is missing/stale")
        if args.header:
            TARGET.write_text(c_header(certs))
        print(f"ABI migrations audited: {len(certs)} additive-compatible transitions; all unsafe changes require per-key reference hashes")
        return 0
    except UnsafeMigration as e:
        print("[RED] ABI migration rejected: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
