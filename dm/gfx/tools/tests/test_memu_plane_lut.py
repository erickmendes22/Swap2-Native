"""Exercise the complete structured plane scatter and its actual GPU writes."""
import importlib.util
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import unittest
from unittest.mock import patch

import test_memu_coalesced_readback as common

U32, ROOT = common.U32, common.ROOT


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


fixture = load_module("plane_fixture", ROOT / "dm/host/tests/memu/plane_fixture.py")
audit = load_module("memu_plane_audit", ROOT / "dm/gfx/tools/memu_plane_audit.py")


class PlaneLut(common.CoalescedReadback):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which("spirv-as") or not shutil.which("spirv-val"):
            raise unittest.SkipTest("spirv-as and spirv-val required")

    def source(self, planes, max_v=128, **kwargs):
        asm, spv = self.work / "fixture.spvasm", self.work / "fixture.spv"
        asm.write_text(fixture.mesh_source(planes, max_v, **kwargs))
        subprocess.run(["spirv-as", "--target-env", "spv1.4", str(asm), "-o", str(spv)], check=True)
        subprocess.run(["spirv-val", "--target-env", "vulkan1.3", str(spv)], check=True)
        return list(struct.unpack(f"<{spv.stat().st_size//4}I", spv.read_bytes()))

    def variant(self, source, enabled, coalesced=0):
        with patch.dict(os.environ, {"DM_VK_MEMU_PLANE_LUT": str(enabled)}):
            layout, cs, vs = self.convert(source, coalesced)
        for name, words in (("cs", cs), ("vs", vs)):
            path = self.work / f"validate-{name}.spv"; self.write_words(path, words)
            subprocess.run(["spirv-val", "--target-env", "vulkan1.3", str(path)], check=True)
        return layout, cs, vs

    def test_sparse_planes_exhaustive_words_and_raw_values(self):
        rng = random.Random(9817)
        patterns = [list(range(4)) + [4],
                    list(range(4)) + list(range(4, 24)),
                    list(range(4)) + sorted(rng.sample(range(4, 100), 23))]
        for planes in patterns:
            for max_v in (96, 128):
                source = self.source(planes, max_v)
                for coalesced in (0, 1):
                    _, old, _ = self.variant(source, 0, coalesced)
                    _, new, _ = self.variant(source, 1, coalesced)
                    self.assertNotEqual(old, new)
                    a, b = audit.PlaneHelper(old), audit.PlaneHelper(new)
                    word_limit = ((max_v + 31)//32) * len(planes) * 32
                    for word in range(word_limit + 33):
                        value = (1664525*word + 1013904223) & 0xffffffff
                        self.assertEqual(a.run(word, value)[0], b.run(word, value)[0], (max_v, planes, word))
                    for word in (0, 1, 31, 32, word_limit-1, word_limit, 0x80000000, 0xffffffff):
                        for value in (0, 0x80000000, 0x7f800000, 0xff800000, 0x7fc12345, 0xffffffff):
                            self.assertEqual(a.run(word, value)[0], b.run(word, value)[0])
                    self.assertLessEqual(b.run(0, 0)[2], 4)  # two bounds and z/w guards
                    self.assertGreater(a.run(0, 0)[2], b.run(0, 0)[2])

    def test_unknown_side_effects_keep_the_original_shader(self):
        for mutation in ("extra_store", "changed_mirror"):
            source = self.source(list(range(4)) + [4, 8, 12, 20], mutation=mutation)
            self.assertEqual(self.variant(source, 0)[1:], self.variant(source, 1)[1:])

    @unittest.skipUnless(os.environ.get("MEMU_TEST_VULKAN") == "1", "set MEMU_TEST_VULKAN=1 for GPU readback")
    def test_real_gpu_output_and_z_w_mirror_match_independent_oracle(self):
        runner = self.work / "plane-dispatch"
        subprocess.run([self.cc, "-O1", "-Wall", "-Wextra", "-Werror", "-I",
                        str(ROOT / "dm/third_party/vulkan-headers/include"),
                        str(ROOT / "dm/host/tests/t_android_memu_dispatch.c"),
                        "-Wl,-l:libvulkan.so.1", "-o", str(runner)], check=True)
        planes = list(range(4)) + [4, 8, 12, 16, 20, 21, 22, 24, 25, 26, 28, 32, 33, 34, 36, 37, 38, 44, 45, 46, 48, 49, 50]
        for max_v in (96, 128):
            source = self.source(planes, max_v)
            for coalesced in (0, 1):
                outputs = []
                for enabled in (0, 1):
                    layout, cs, _ = self.variant(source, enabled, coalesced)
                    groups = ((max_v+31)//32) * len(planes) + 2  # include invalid words
                    rec = (U32 * 32)(); self.lib.vka_memu_rec_mesh(layout, rec)
                    rec[24] = groups; rec[25] = rec[15] * 3; rec[26] = rec[25] + rec[15]*groups
                    blank = [0x7fc12345] * (rec[26] + rec[16]*groups + 1024)
                    expected = list(blank)
                    locations = list(layout.vloc[:layout.nvloc]); mirror = 4 + 4 * locations.index(31)
                    def address(group, vertex, component):
                        return rec[25] + group*rec[15] + (component*max_v + vertex if coalesced else vertex*layout.vw + component)
                    for group in range(groups):
                        plane = group % len(planes); chunk = group // len(planes)
                        valid = chunk*32 < max_v
                        code = planes[plane]
                        for vertex in range(max_v):
                            z, w = 0x12345678, 0x9abcdef0
                            lane = vertex % 32
                            word = group*32 + lane
                            bits = 0x7fc12345 if lane == 0 else 0x80000000 if lane == 1 else (word*1664525+1013904223) & 0xffffffff
                            if valid and vertex//32 == chunk:
                                component = code if code < 4 else 4 + 4 * locations.index((code-4)//4) + (code&3)
                                expected[address(group, vertex, component)] = bits
                                if code == 2: z = bits
                                if code == 3: w = bits
                            for c, value in enumerate((z, w, 0, 0x3f800000)):
                                expected[address(group, vertex, mirror+c)] = value
                        bias = rec[25] // layout.vw + group * max_v
                        expected[rec[26]+group*3:rec[26]+group*3+3] = [bias, bias, bias]
                    rp, ap, out, sp = (self.work / n for n in ("p-rec.bin", "p-arena.bin", "p-out.bin", "p-cs.spv"))
                    self.write_words(rp, rec); self.write_words(ap, blank); self.write_words(sp, cs)
                    subprocess.run([str(runner), str(sp), str(rp), str(ap), str(out), str(groups), "1", "1"], check=True, capture_output=True)
                    actual = list(struct.unpack(f"<{out.stat().st_size//4}I", out.read_bytes()))
                    differences = [(i, a, b) for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
                    self.assertFalse(differences, (max_v, enabled, coalesced, differences[:8]))
                    outputs.append(actual)
                self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
