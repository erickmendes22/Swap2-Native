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
SPLIT = ROOT / "dm/gfx/tools/shader_split.py"
SPLIT_TREE = ast.parse(SPLIT.read_text())
MESH_FN = next(n for n in SPLIT_TREE.body if isinstance(n, ast.FunctionDef) and n.name == "mesh_facts")

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
        decoder = {'struct': struct}
        exec(compile(ast.Module(body=[MESH_FN], type_ignores=[]), str(SPLIT), 'exec'), decoder)
        self.facts = {}
        ns = dict(os=os, re=re, struct=struct, hashlib=hashlib, sys=sys,
                  FACTS=self.facts, CAPTURED_MESH_FACTS=decoder['mesh_facts'],
                  borrow_mesh_layout=lambda: decoder['mesh_facts'],
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

    def test_28_missing_shader_captures_build_one_bounded_overlay(self):
        # This is the actual missing-key count from the 2026-11-11 Ocarina
        # gameplay log. Synthetic sources, no proprietary game assets or
        # 42,339-source split required.
        keys = set()
        for i in range(28):
            code = struct.pack("<I", 1 << 10) + bytes([i + 1]) * 76
            ctl = bytearray(0xd8)
            ctl[:8] = bytes.fromhex("34127698c9000000")
            ctl[0x56] = 1  # graphics stage: shader code SPH selects vertex
            struct.pack_into("<I", ctl, 0x44, len(code))
            key = hashlib.sha256(
                bytes(ctl[:0x30]) + bytes(4) + bytes(ctl[0x34:0x48]) + code
            ).hexdigest()[:16]
            keys.add(key)
            (self.capture / (key + ".ctl")).write_bytes(ctl)
            (self.capture / (key + ".code")).write_bytes(code)
        self.assertEqual(len(keys), 28)
        loc = {}
        self.assertEqual(self.repair(keys, loc, {}, str(self.pkg)), 28)
        self.assertEqual(set(loc), keys)
        self.assertTrue((self.pkg / "vs_captured_repair.bin").is_file())
        self.assertEqual({v[0] for v in loc.values()}, {"vs_captured_repair.bin"})
        self.assertFalse((self.pkg / "shader_map.tsv").exists())

    def write_mesh_task(self, stage, seed):
        assert stage in (6, 7)
        code = bytearray(0x100)
        code[0x35] = 0xf0  # four position-plane components
        code[0x36] = seed & 0xf   # one or more generic vector components
        code[0x70] = seed
        ctl = bytearray(0xd8)
        ctl[:8] = bytes.fromhex("34127698c9000000")
        ctl[0x56] = stage
        struct.pack_into("<I", ctl, 0x44, len(code))
        struct.pack_into("<HH", ctl, 0x58, 64, 128)
        ctl[0x5f] = 3
        struct.pack_into("<HH", ctl, 0x60, 64, 126)
        key = hashlib.sha256(
            bytes(ctl[:0x30]) + bytes(4) + bytes(ctl[0x34:0x48]) + code
        ).hexdigest()[:16]
        (self.capture / (key + ".ctl")).write_bytes(ctl)
        (self.capture / (key + ".code")).write_bytes(code)
        return key

    def test_captured_mesh_has_real_layout_without_full_split(self):
        key = self.write_mesh_task(7, 13)
        loc = {}
        self.assertEqual(self.repair({key}, loc, {}, str(self.pkg)), 1)
        facts = self.facts[key]
        self.assertEqual(facts["local"], [64, 1, 1])
        self.assertEqual(facts["mesh"][:7], [64, 126, 128, 0, 1, 2, 3])
        self.assertEqual(facts["mesh_topology"], 3)
        self.assertEqual(loc[key][0], "ms_captured_repair.bin")

    def test_captured_task_has_real_payload_layout(self):
        key = self.write_mesh_task(6, 17)
        self.assertEqual(self.repair({key}, {}, {}, str(self.pkg)), 1)
        self.assertEqual(self.facts[key]["mesh"], [0, 0, 128])
        self.assertEqual(self.facts[key]["local"], [64, 1, 1])

    def test_53_missing_mesh_task_layouts_have_no_profile_dependency(self):
        # Reproduce the observed 49 mesh + 4 task failures, using the real
        # shader_split mesh_facts parser on verified synthetic captures.
        keys = set()
        for i in range(49):
            keys.add(self.write_mesh_task(7, i + 1))
        for i in range(4):
            keys.add(self.write_mesh_task(6, i + 65))
        self.assertEqual(len(keys), 53)
        loc = {}
        self.assertEqual(self.repair(keys, loc, {}, str(self.pkg)), 53)
        self.assertEqual(len(loc), 53)
        self.assertEqual(len(self.facts), 53)
        self.assertEqual(sum(bool(v.get("mesh")) for v in self.facts.values()), 53)
        self.assertEqual(len(list(self.pkg.glob("*_captured_repair.bin"))), 2)
        self.assertFalse((self.pkg / "shader_map.tsv").exists())

    def test_malformed_mesh_layout_is_rejected_before_compiling(self):
        key = self.write_mesh_task(7, 13)
        ctlp = self.capture / (key + ".ctl")
        # Invalidating the thread count changes no key (hash uses only
        # control[:0x48]), but must not produce unverified mesh facts.
        ctl = bytearray(ctlp.read_bytes())
        struct.pack_into("<H", ctl, 0x58, 0)
        ctlp.write_bytes(ctl)
        with self.assertRaises(SystemExit) as cm:
            self.repair({key}, {}, {}, str(self.pkg))
        self.assertIn("mesh layout cannot be recovered", str(cm.exception))
        self.assertFalse((self.pkg / "ms_captured_repair.bin").exists())

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
        self.assertIn('An old full 42k shader split can still be on disk.',svc)
        self.assertNotIn('&&\\n                        !new File(split, "pkg").isDirectory();',svc)
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
        self.assertIn('OcarinaShaderDelta.alreadyRepaired(probe, selected)',ui)
        self.assertIn('j.stepState("split", "done")',ui)
        self.assertIn('j.hotKeys(selected);',ui)
        self.assertIn('offerOcarinaHotRepair(r, pd, code, f.tools, false)',ui)
        self.assertIn('static void repairCapturedShaders(MainActivity a, Game g)',ui)
        self.assertIn('panel.repairCapturedShaders(g);',ui)
        self.assertIn('R.string.s2_ocarina_repair_note',ui)
        self.assertIn('No new valid captured shader sources', (ROOT/'android/app/src/main/res/values/strings.xml').read_text())
        self.assertIn('Reparar shaders capturados', (ROOT/'android/app/src/main/res/values-pt/strings.xml').read_text())
        self.assertLess(ui.index('offerOcarinaHotRepair(r, pd, code, f.tools, false)'),
                        ui.index('if (!code && !shaders)'))
        self.assertIn('&& j.hotKeys().isEmpty()',svc)
        self.assertIn('List<String> hotKeys = j.hotKeys();',svc)
        self.assertNotIn('List<String> hotKeys = OcarinaShaderDelta.keys(j);',svc)
        self.assertIn('j.hotKeys(selected);',ui)

if __name__=="__main__": unittest.main()
