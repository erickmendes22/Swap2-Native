#!/usr/bin/env python3
"""Build SGSR1's single-pass Vulkan fragment module as a C header.

The header is generated during the native Android build, not checked in.
This keeps it tied exactly to the Qualcomm BSD-3-Clause source and validates
the SPIR-V before any APK is built. --check does not write an artifact.
"""
import argparse
import glob
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SRC = HERE / "sgsr1.frag"
OUT = HERE.parent / "vka_present_sgsr.h"

def resolve(name):
    p = shutil.which(name)
    if p: return p
    roots = [os.environ.get("ANDROID_NDK_HOME", "")] + sorted(glob.glob(os.path.expanduser("~/android-ndk-*")), reverse=True)
    for root in filter(None, roots):
        for candidate in glob.glob(os.path.join(root, "shader-tools", "*", name)):
            return candidate
    return None

def compile_header():
    glslc, val = resolve("glslc"), resolve("spirv-val")
    if not glslc or not val: raise FileNotFoundError("glslc and spirv-val are required")
    args = [glslc, "-O", "--target-env=vulkan1.1"]
    with tempfile.TemporaryDirectory() as td:
        blob = Path(td) / "sgsr1.spv"
        subprocess.run(args + [str(SRC), "-o", str(blob)], check=True)
        subprocess.run([val, "--target-env", "vulkan1.1", str(blob)], check=True)
    numeric = subprocess.run(args + ["-mfmt=num", str(SRC), "-o", "-"], check=True, capture_output=True, text=True).stdout
    return ("// Generated from Qualcomm BSD-3-Clause SGSR 1 single-pass shader\n"
            "// by dm/gfx/vk_android/fsr/sgsr_spv.py. Do not edit.\n"
            "#pragma once\n#include <stdint.h>\n"
            "static const uint32_t vka_sgsr1_frag[] = {\n" + numeric.strip() + "\n};\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    try: text = compile_header()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print("SGSR1 shader compile failed:", exc, file=sys.stderr)
        return 2
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print("SGSR1 C header missing or stale", file=sys.stderr)
            return 1
    else:
        OUT.write_text(text)
        print(f"SGSR1 validated and emitted: {len(text)//1024} KiB C header")
    return 0

if __name__ == "__main__":
    sys.exit(main())
