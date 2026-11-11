"""Real captured NVN2 shader hot-repair source validation.

The code may run without loading the large game profile or translation DLL;
extract the exact production function's AST and execute it on synthetic
control+code pairs. No key outside the explicit requested set is read.
"""
import ast
import hashlib
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = (ROOT / "dm/gfx/tools/vk_android_build.py").read_text()
TREE = ast.parse(SOURCE)
FN = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "captured_oot_records")

class CapturedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.capture = Path(self.tmp.name) / "nvn_shdump"
        self.pkg = Path(self.tmp.name) / "pkg"
        self.capture.mkdir()
        self.original = os.environ.get("DMSH_VK_CAPTURE_DIR")
        os.environ["DMSH_VK_CAPTURE_DIR"] = str(self.capture)
        self.addCleanup(self.restore)
        ns = dict(os=os, re=re, struct=struct, hashlib=hashlib, sys=sys,
                  GAME=types.SimpleNamespace(id="0400486024DEC000"))
        exec(compile(ast.Module(body=[FN], type_ignores=[]), "<production capture function>", "exec"), ns)
        self.repair = ns["captured_oot_records"]

    def restore(self):
        if self.original is None: os.environ.pop("DMSH_VK_CAPTURE_DIR", None)
        else: os.environ["DMSH_VK_CAPTURE_DIR"] = self.original

    def write_capture(self, stage=5):
        code=b"\x11\x22\x33\x44" * 20
        ctl=bytearray(0xd8)
        ctl[:8]=bytes.fromhex("34127698c9000000")
        ctl[0x56]=stage
        struct.pack_into("<I",ctl,0x44,len(code))
        # The key hashes 0x30 as zeros, just as the NVN2 game loader.
        key=hashlib.sha256(bytes(ctl[:0x30])+bytes(4)+bytes(ctl[0x34:0x48])+code).hexdigest()[:16]
        (self.capture/(key+".ctl")).write_bytes(ctl)
        (self.capture/(key+".code")).write_bytes(code)
        return key,ctl,code

    def test_compile_exact_selected_key_and_preserve_existing_profile(self):
        key,ctl,code=self.write_capture()
        loc={"aaaaaaaaaaaaaaaa":("cs_old.bin",0)}
        pc_of={"aaaaaaaaaaaaaaaa":"old"}
        n=self.repair({key},loc,pc_of,str(self.pkg))
        self.assertEqual(n,1)
        self.assertEqual(loc["aaaaaaaaaaaaaaaa"],("cs_old.bin",0))
        self.assertEqual(loc[key],("cs_captured_repair.bin",0))
        self.assertEqual(pc_of[key],"captured-runtime")
        blob=(self.pkg/"cs_captured_repair.bin").read_bytes()
        self.assertEqual(blob[:8],b"BTCDBTCD")
        self.assertEqual(struct.unpack_from("<2I",blob,0x28),(len(ctl),len(code)))
        self.assertEqual(blob[0x38:],code+ctl)

    def test_known_key_missing_from_split_package_uses_verified_capture(self):
        key,ctl,code=self.write_capture()
        loc={key:("cs_static.bin",0)}
        pc_of={key:"original-profile-metadata"}
        self.assertEqual(self.repair({key},loc,pc_of,str(self.pkg)),1)
        self.assertEqual(loc[key],("cs_captured_repair.bin",0))
        self.assertEqual(pc_of[key],"original-profile-metadata")
        self.assertEqual((self.pkg/"cs_captured_repair.bin").read_bytes()[0x38:],code+ctl)

    def test_existing_static_package_never_overridden_by_capture(self):
        key,_,_=self.write_capture()
        self.pkg.mkdir()
        (self.pkg/"cs_static.bin").write_bytes(b"static")
        loc={key:("cs_static.bin",0)}
        self.assertEqual(self.repair({key},loc,{},str(self.pkg)),0)
        self.assertEqual(loc[key],("cs_static.bin",0))
        self.assertFalse((self.pkg/"cs_captured_repair.bin").exists())

    def test_corrupted_capture_is_rejected_without_packaging(self):
        key,_,_=self.write_capture()
        with (self.capture/(key+".code")).open("ab") as f:f.write(b"x")
        with self.assertRaises(SystemExit) as cm:self.repair({key},{},{},str(self.pkg))
        self.assertIn("invalid NVN2 control header or code length",str(cm.exception))
        self.assertFalse((self.pkg/"cs_captured_repair.bin").exists())

    def test_unknown_key_never_builds_all_shaders(self):
        key,_,_=self.write_capture()
        loc={"aaaaaaaaaaaaaaaa":("cs_base.bin",0)}
        self.assertEqual(self.repair(set(),loc,{},str(self.pkg)),0)
        self.assertFalse(self.pkg.exists())
        with self.assertRaises(SystemExit): self.repair({"1234"},{},{},str(self.pkg))
        self.assertEqual(list(self.capture.glob("*.code")),[self.capture/(key+".code")])

    def test_overflow_refused(self):
        with self.assertRaises(SystemExit):
            self.repair({f"{i:016x}" for i in range(129)},{},{},str(self.pkg))

    def test_completed_library_fails_closed_before_mass_rebuild(self):
        svc=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        ui=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/Ondevice.java").read_text()
        self.assertLess(svc.index("if (reuseOcarinaShaders(j)) return;"),svc.index("if (j.apkChanged())"))
        self.assertIn("j.shadersInPack();",svc)
        self.assertIn('j.stepState("pack", "done");',svc)
        self.assertIn("Pack.libraryProblem(j.pack(), j.titleId()) == null",svc)
        self.assertIn("PackCheck.playBlocking(this, p, j.dump()) == null",svc)
        self.assertIn("Refusing a destructive 42,339-shader automatic rebuild",svc)
        self.assertIn("automatic retranslation of all 42,339 shaders is blocked.",svc)
        self.assertIn("Nenhuma recompilação foi iniciada",ui)
        self.assertIn("Não serão preparados os 42.339 shaders novamente",ui)

    def test_pack_96_percent_recovers_library_without_pack_tsv(self):
        svc=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        job=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/Job.java").read_text()
        screen=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/PrepareScreen.java").read_text()
        self.assertIn('finishedOcarinaLibrary(File shaderRoot, Job j)',svc)
        self.assertIn('new File(j.dir(), "lib")',svc)
        self.assertIn('new File(j.pack(), "shaders")',svc)
        self.assertIn('j.recoverFinishedShaderCache(inJob, cached.entries)',svc)
        self.assertIn('j.stepState("pack", "pending")',svc)
        self.assertIn('j.acceptPlayableShaderVersion()',svc)
        self.assertIn('header.entries < p.shaderTotal',svc)
        self.assertIn('synchronized List<String> hotKeys()',job)
        self.assertIn('synchronized void hotKeys(List<String> keys)',job)
        self.assertIn('synchronized void recoverFinishedShaderCache(File cache, long count)',job)
        self.assertIn('said = s.error;',screen)

    def test_android_wiring_is_selective(self):
        svc=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/PackService.java").read_text()
        java=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/OcarinaShaderDelta.java").read_text()
        self.assertIn('PackEngine.setenv("DMSH_VK_CAPTURE_DIR"',svc)
        self.assertIn('boolean capturedOnly = !hotKeys.isEmpty()',svc)
        self.assertIn('if (!capturedOnly) {',svc)
        self.assertIn('new File(od, "capture-pkg")',svc)
        self.assertIn('BuildConfig.NX_DMSH_VK_CHAIN.equals(header.vkChain)',java)
        self.assertIn('String key = f.getName().substring(0, 16)',java)
        self.assertIn('File old = Pack.libraryOf(job.pack());',java)
        self.assertIn('if (old == null) old = Pack.playableLibrary',java)
        self.assertNotIn('if (!manifest.isFile()) return List.of();',java)
        self.assertIn('!ShaderLibs.hasKey(old, header, key)',java)
        self.assertIn('HEAVY.contains(key)',java)
        self.assertIn('!BuildConfig.NX_DMSH_VK_CHAIN.equals(header.vkChain)',java)
        self.assertIn('missing.stream().filter(HEAVY::contains).count()',java)
        for key in ("066f5daf12e43c71","efaa4fa6a80ba719",
                    "5ad65c0eefd09c7f","9e6b00b050e30801"):
            self.assertIn('"'+key+'"',java)
        self.assertNotIn('if (!BuildConfig.NX_DMSH_VK_CHAIN.equals(header.vkChain)) {\\n            File captures',java)
        self.assertIn('alreadyRepaired(Job job, List<String> keys)',java)
        libs=(ROOT/"android/app/src/main/java/dev/nxnative/android/ShaderLibs.java").read_text()
        self.assertIn('static boolean hasKey(File lib, Header h, String key)',libs)
        self.assertIn('Long.reverseBytes(f.readLong())',libs)
        ui=(ROOT/"android/app/src/ondevice/java/dev/nxnative/android/Ondevice.java").read_text()
        self.assertIn('OcarinaShaderDelta.alreadyRepaired(probe, missing)',ui)
        self.assertIn('j.stepState("split", "done")',ui)
        self.assertIn('&& j.hotKeys().isEmpty()',svc)
        self.assertIn('List<String> hotKeys = j.hotKeys();',svc)
        self.assertNotIn('List<String> hotKeys = OcarinaShaderDelta.keys(j);',svc)
        self.assertIn('j.hotKeys(missing);',ui)

if __name__=="__main__": unittest.main()
