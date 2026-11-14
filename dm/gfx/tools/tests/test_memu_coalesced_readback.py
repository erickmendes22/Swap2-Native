"""Execute mesh exports on Vulkan and decode them with the generated VS.

Set MEMU_TEST_VULKAN=1 with a Vulkan ICD and spirv-val/glslangValidator
to enable GPU readback. Software ICD results establish correctness only;
they are deliberately never used as evidence of Android FPS improvement.
"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / "dm/gfx/vk_android"
U32 = C.c_uint32


class Layout(C.Structure):
    _fields_ = [("task", C.c_int), ("local", U32 * 3), ("threads", U32),
                ("payload_words", U32), ("max_v", U32), ("max_p", U32),
                ("points", C.c_int), ("point_size", C.c_int), ("cull", C.c_int),
                ("vloc", C.c_uint8 * 32), ("ploc", C.c_uint8 * 32),
                ("nvloc", C.c_int), ("nploc", C.c_int), ("vw", U32),
                ("pw", U32), ("indexed", C.c_int), ("coalesced", C.c_int)]


def instructions(words):
    i = 5
    while i < len(words):
        n, op = words[i] >> 16, words[i] & 65535
        if not n or i + n > len(words):
            raise AssertionError("invalid SPIR-V instruction")
        yield op, words[i + 1:i + n]
        i += n


def vertex_outputs(words, arena, vertex_index):
    """Small straight-line VS evaluator, refusing all unsupported instructions.

    Float words stay raw bits throughout, including NaN/sentinel values.
    Arithmetic is only the generated reader's integer address arithmetic.
    """
    values, memory, storage, decorations = {}, {}, {}, {}
    running = False
    for op, a in instructions(words):
        if op == 71:
            decorations.setdefault(a[0], {})[a[1]] = a[2:]  # BuiltIn, Location
        elif op == 43:
            values[a[1]] = a[2]
        elif op == 59:
            values[a[1]] = (a[1], ())
            storage[a[1]] = a[2]
            if a[2] == 1:
                memory[a[1]] = vertex_index
            elif a[2] == 12:
                memory[a[1]] = (arena,)
        elif op == 54:
            running = True
        elif not running or op == 248:
            continue
        elif op in (65, 66):
            base, indices = values[a[2]]
            values[a[1]] = (base, indices + tuple(values[i] for i in a[3:]))
        elif op == 61:
            base, indices = values[a[2]]
            value = memory[base]
            for index in indices:
                value = value[index]  # bounds checked independently of the producer
            values[a[1]] = value
        elif op == 62:
            base, indices = values[a[0]]
            if indices:
                raise AssertionError("unexpected indexed VS output")
            memory[base] = values[a[1]]
        elif op == 124:
            values[a[1]] = values[a[2]]
        elif op == 80:
            values[a[1]] = tuple(values[i] for i in a[2:])
        elif op == 81:
            value = values[a[2]]
            for index in a[3:]:
                value = value[index]
            values[a[1]] = value
        elif op in (128, 132, 134, 137, 171, 176, 169):
            if op == 169:
                values[a[1]] = values[a[3] if values[a[2]] else a[4]]
                continue
            x, y = values[a[2]], values[a[3]]
            values[a[1]] = {128: lambda: (x + y) & 0xffffffff,
                            132: lambda: (x * y) & 0xffffffff,
                            134: lambda: x // y, 137: lambda: x % y,
                            171: lambda: x != y, 176: lambda: x < y}[op]()
        elif op == 253:
            break
        else:
            raise AssertionError(f"unsupported generated VS opcode {op}")
    return {tuple(sorted((k, tuple(v)) for k, v in decorations.get(i, {}).items()
                         if k in (11, 30))): memory[i]
            for i, sc in storage.items() if sc == 3}


class CoalescedReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        cls.cc = shutil.which("cc")
        if not cls.cc:
            raise unittest.SkipTest("C compiler required")
        shared = cls.work / "memu.so"
        subprocess.run([cls.cc, "-shared", "-fPIC", "-O1", str(VK / "vka_memu_spv.c"),
                        "-o", str(shared)], check=True)
        cls.lib = C.CDLL(str(shared))
        cls.configure(cls.lib)
        cls.libc = C.CDLL(None)
        cls.libc.free.argtypes = [C.c_void_p]
        text = (ROOT / "dm/host/tests/memu/memu_fixtures.h").read_text()
        cls.fixtures = {}
        for tag, body in re.findall(r"MEMU_(MESH_TRI|MESH_PTS)\[\] = \{(.*?)\};", text, re.S):
            cls.fixtures[tag] = [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", body)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def configure(lib):
        lib.vka_memu_layout_of.argtypes = [C.POINTER(U32), C.c_size_t, C.POINTER(Layout), C.c_char_p, C.c_size_t]
        lib.vka_memu_cs.argtypes = [C.POINTER(U32), C.c_size_t, C.POINTER(C.c_size_t), C.c_char_p, C.c_size_t]
        lib.vka_memu_cs.restype = C.POINTER(U32)
        lib.vka_memu_cs_masked.argtypes = [C.POINTER(U32), C.c_size_t, C.c_uint64,
                                           C.POINTER(C.c_size_t), C.c_char_p, C.c_size_t]
        lib.vka_memu_cs_masked.restype = C.POINTER(U32)
        lib.vka_memu_vs_masked.argtypes = [C.POINTER(Layout), C.c_uint64,
                                           C.POINTER(C.c_size_t), C.c_char_p, C.c_size_t]
        lib.vka_memu_vs_masked.restype = C.POINTER(U32)
        lib.vka_memu_vs.argtypes = [C.POINTER(Layout), C.POINTER(C.c_size_t), C.c_char_p, C.c_size_t]
        lib.vka_memu_vs.restype = C.POINTER(U32)
        lib.vka_memu_rec_mesh.argtypes = [C.POINTER(Layout), C.POINTER(U32)]

    def convert(self, words, enabled, lib=None):
        lib = lib or self.lib
        source = (U32 * len(words))(*words)
        layout, error = Layout(), C.create_string_buffer(256)
        with patch.dict(os.environ, {"DM_VK_MEMU_COALESCED": str(enabled)}):
            self.assertEqual(lib.vka_memu_layout_of(source, len(words), C.byref(layout), error, 256), 1, error.value)
            modules = []
            for function, args in ((lib.vka_memu_cs, (source, len(words))),
                                   (lib.vka_memu_vs, (C.byref(layout),))):
                size = C.c_size_t()
                output = function(*args, C.byref(size), error, 256)
                self.assertTrue(output, error.value)
                modules.append(list(output[:size.value]))
                self.libc.free(output)
        return layout, *modules

    @staticmethod
    def write_words(path, words):
        path.write_bytes(struct.pack(f"<{len(words)}I", *words))

    @unittest.skipUnless(os.environ.get("MEMU_TEST_VULKAN") == "1",
                         "requires real Vulkan hardware/ICD")
    def test_mesh_producer_and_vertex_masked_pair_gpu_readback(self):
        """Real Vulkan executes both mesh-compute modules and compares every
        actually consumed vertex/primitive output; dropped attribute planes
        remain unobserved by the selected fragment interface.
        """
        import statistics, json
        runner = self.work / "dispatch-masked-pair"
        subprocess.run([self.cc, "-O1", "-Wall", "-Wextra", "-Werror", "-I",
                        str(ROOT / "dm/third_party/vulkan-headers/include"),
                        str(ROOT / "dm/host/tests/t_android_memu_dispatch.c"),
                        "-Wl,-l:libvulkan.so.1", "-o", str(runner)], check=True)
        for tag, original in self.fixtures.items():
            for coalesced in (0, 1):
                with patch.dict(os.environ, {"DM_VK_MEMU_COALESCED": str(coalesced)}):
                    layout, cs_full, vs_full = self.convert(original, coalesced)
                    # Triangles use location 0, not location 2; point shader
                    # needs only PointSize and Position (no primitive varyings).
                    mask = 1 if tag == "MESH_TRI" else 0
                    fixture = (U32 * len(original))(*original)
                    size = C.c_size_t(); error = C.create_string_buffer(256)
                    mcs = self.lib.vka_memu_cs_masked(fixture, len(original),
                            mask, C.byref(size), error, 256)
                    self.assertTrue(mcs, error.value)
                    cs_masked = list(mcs[:size.value]); self.libc.free(mcs)
                    mvs = self.lib.vka_memu_vs_masked(C.byref(layout), mask,
                            C.byref(size), error, 256)
                    self.assertTrue(mvs, error.value)
                    vs_masked = list(mvs[:size.value]); self.libc.free(mvs)
                    self.assertLess(len(cs_masked),len(cs_full))
                    self.assertLess(len(vs_masked),len(vs_full))
                    for name, mod in (("baseline",cs_full),("pruned",cs_masked),
                                      ("vsfull",vs_full),("vsmasked",vs_masked)):
                        self.write_words(self.work/f"gpu-{name}.spv",mod)
                        subprocess.run(["spirv-val","--target-env","vulkan1.3",
                                        str(self.work/f"gpu-{name}.spv")],check=True)
                    record = (U32 * 32)()
                    self.lib.vka_memu_rec_mesh(C.byref(layout), record)
                    count = 4
                    record[12], record[21], record[24] = 7, 0, count
                    record[14], record[22], record[23] = 8, 128, 64
                    record[25] = record[15] * 3
                    record[26] = record[25] + (record[15]*count if layout.indexed
                                               else layout.max_v*layout.vw)
                    initial = [0x7fc12345] * (record[26] + record[16]*count + 1024)
                    rp, ap, out = (self.work/n for n in
                                   ("gpu-mask-rec.bin","gpu-mask-arena.bin","gpu-mask-out.bin"))
                    times = {"baseline":[], "pruned":[]}
                    outputs = {}
                    for round_i in range(3):
                        for kind in (("baseline","pruned") if round_i%2==0
                                     else ("pruned","baseline")):
                            self.write_words(rp,record);self.write_words(ap,initial)
                            env=dict(os.environ,MEMU_TEST_REPEATS="32")
                            proc=subprocess.run([str(runner),
                                str(self.work/f"gpu-{kind}.spv"),str(rp),
                                str(ap),str(out),"2","2","1"],
                                env=env,check=True,capture_output=True,text=True)
                            times[kind].append(json.loads(proc.stdout.strip().splitlines()[-1])
                                               ["gpu_ns_per_dispatch"])
                            arena=list(struct.unpack(f"<{out.stat().st_size//4}I",
                                                     out.read_bytes()))
                            vm=vs_full if kind=="baseline" else vs_masked
                            pixels=[]
                            for group in range(4):
                                for prim in range(4):
                                    if layout.indexed:
                                        idx=arena[record[26]+group*record[16]+prim*3]
                                    else:
                                        idx=(record[25]//record[15]+group)*layout.max_p+prim
                                    src=vertex_outputs(vm,arena,idx)
                                    # Exact fragment-facing interface plus the
                                    # fixed-function position/point size.
                                    pixels.append({k:v for k,v in src.items()
                                                   if (11,(0,)) in k or (11,(1,)) in k
                                                   or any(a==30 and (1<<v[0]) & mask
                                                          for a,v in k if a==30)})
                            outputs[kind]=pixels
                    self.assertEqual(outputs["baseline"],outputs["pruned"],
                                     (tag,coalesced,"fragment-visible GPU values"))
                    full_time=statistics.median(times["baseline"])
                    pruned_time=statistics.median(times["pruned"])
                    print(f"GPU actual mesh producer {tag} coalesced={coalesced}: "
                          f"full {full_time:.0f}ns vs fragment-pruned {pruned_time:.0f}ns, "
                          f"pruned/full={pruned_time/full_time:.3f} "
                          f"(Lavapipe, not Adreno FPS)")

    def test_default_modules_are_byte_identical_to_build118(self):
        # Recorded from c0397be0's actual converter before this change.
        golden = {
            "MESH_TRI": ["8e650af47d9f3b6d4a10ec156f63499e648fe9ce3828be669a99c8490b47b576",
                         "9f0f933eb33f3ac35b9a6fbd3fac24edca5bb282587edf6e16074f9841a03d00"],
            "MESH_PTS": ["b837a300215360465fe74e5ae0ae00fd3eb015aae817131a9477dc146d30b6ac",
                         "194ea4cb0e48f3848418001b145ed738984f8373113fb840316d8362322eb1c6"],
        }
        with patch.dict(os.environ, {"DM_VK_MEMU_FAST_TASKLESS": "1", "DM_VK_MEMU_VEC_BITCAST": "0"}):
            for tag, fixture in self.fixtures.items():
                for expected, module in zip(golden[tag], self.convert(fixture, 0)[1:]):
                    self.assertEqual(hashlib.sha256(struct.pack(f"<{len(module)}I", *module)).hexdigest(), expected)

    def test_real_prewarm_decoders_migrate_recipes_to_active_layout(self):
        def function(path, name):
            source = path.read_text()
            start = source.index(name)
            return source[start:source.index("\n}", start) + 2]
        decode = function(VK / "vka_memu.c", "vka_shader *vka_memu_by_key(")
        classify = function(VK / "vka_shader.c", "int vka_shader_memu_key(")
        source = self.work / "keys.c"
        source.write_text(r'''
#include <assert.h>
#include <pthread.h>
#include "vka_memu.h"
typedef struct vka_shader { const dmsh_vk_entry *e; uint64_t key; } vka_shader;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static int enabled, lut_enabled;
int vka_memu_coalesced(void) { return enabled; }
int vka_memu_plane_lut(void) { return lut_enabled; }
static const uint64_t base = 0x123456789abcdef0ull;
static dmsh_vk_entry entry;
static vka_shader original, cs[2], vs;
static int lib_load(void) { return 1; }
static void *library_for_key(uint64_t key) { (void)key; return NULL; }
static const dmsh_vk_entry *vka_shlib_find(void *lib, uint64_t key) { (void)lib; return key == base ? &entry : NULL; }
int vka_shader_lib_has(uint64_t key) { return key == base; }
static vka_shader *vka_shader_by_key(uint64_t key) { return key == base ? &original : NULL; }
vka_shader *vka_memu_cs_of(vka_shader *s, int gl) {
    assert(s == &original);
    cs[gl].key = base ^ VKA_MEMU_KEY_CS ^ vka_memu_layout_tag() ^ vka_memu_cs_tag(entry.stage) ^ (gl ? VKA_MEMU_KEY_GL : 0);
    return &cs[gl];
}
vka_shader *vka_memu_vs_of(vka_shader *s) { assert(s == &original); vs.key = base ^ VKA_MEMU_KEY_VS ^ vka_memu_layout_tag(); return &vs; }
''' + decode + "\n" + classify + r'''
int main(void) {
    const uint64_t tags[5] = {VKA_MEMU_KEY_CS, VKA_MEMU_KEY_CS ^ VKA_MEMU_KEY_GL, VKA_MEMU_KEY_VS,
        VKA_MEMU_KEY_CS ^ VKA_MEMU_KEY_PLANE_LUT, VKA_MEMU_KEY_CS ^ VKA_MEMU_KEY_PLANE_LUT ^ VKA_MEMU_KEY_GL};
    entry.stage = DMSH_VK_STAGE_MS; original.e = &entry;
    for (lut_enabled = 0; lut_enabled < 2; lut_enabled++) for (enabled = 0; enabled < 2; enabled++) for (int i = 0; i < 5; i++) {
        uint64_t key = base ^ tags[i] ^ vka_memu_layout_tag();
        assert(vka_memu_by_key(key) == (i == 2 ? &vs : &cs[i == 1 || i == 4]));
        uint64_t active = base ^ (i == 2 ? VKA_MEMU_KEY_VS : VKA_MEMU_KEY_CS ^ vka_memu_cs_tag(entry.stage)) ^ vka_memu_layout_tag();
        if (i == 1 || i == 4) active ^= VKA_MEMU_KEY_GL;
        assert(vka_memu_by_key(key)->key == active);
        assert(vka_shader_memu_key(key));
        assert(vka_memu_by_key(key ^ VKA_MEMU_KEY_COALESCED)->key == active);
        assert(vka_shader_memu_key(key ^ VKA_MEMU_KEY_COALESCED));
    }
    assert(!vka_shader_memu_key(base));
    return 0;
}
''')
        exe = self.work / "keys"
        subprocess.run([self.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(VK),
                        "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                        str(source), "-pthread", "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

    @unittest.skipUnless(os.environ.get("MEMU_TEST_VULKAN") == "1", "set MEMU_TEST_VULKAN=1 for GPU readback")
    def test_gpu_exports_and_generated_vertex_reader(self):
        runner = self.work / "dispatch"
        subprocess.run([self.cc, "-O1", "-Wall", "-Wextra", "-Werror", "-I",
                        str(ROOT / "dm/third_party/vulkan-headers/include"),
                        str(ROOT / "dm/host/tests/t_android_memu_dispatch.c"),
                        "-Wl,-l:libvulkan.so.1", "-o", str(runner)], check=True)
        # Execute the exact checked-in helper modules used at runtime.
        # Mixed records force padding and expose incorrect VBASE alignment.
        header = (VK / "vka_memu_coalesced_helpers_spv.h").read_text()
        helpers = {name: [int(x, 16) for x in re.findall(r"0x[0-9a-f]+", body)]
                   for name, body in re.findall(r"(SPV_MEMU_\w+)\[\d+\] = \{(.*?)\};", header, re.S)}
        for name, module in helpers.items():
            path = self.work / f"{name}.spv"; self.write_words(path, module)
            subprocess.run(["spirv-val", "--target-env", "vulkan1.1", str(path)], check=True)
        for count, capacity in ((3, 262144), (1000, 10000)):
            records = []
            for max_v in (96, 128, 64):
                record = [0] * 32
                record[11], record[13], record[15], record[16] = count, 2 | 8, max_v * 44, 192
                record[17], record[18], record[19], record[20] = 44, max_v, 192, 65535
                records += record
            rp, ap, out = (self.work / n for n in ("helpers-rec.bin", "helpers-arena.bin", "helpers-out.bin"))
            self.write_words(rp, records); self.write_words(ap, [0] * capacity)
            subprocess.run([str(runner), str(self.work / "SPV_MEMU_SETUP_COALESCED.spv"),
                            str(rp), str(ap), str(out), "1", "1", "1", "helper"], check=True, capture_output=True)
            result = struct.unpack("<96I", rp.read_bytes())
            spans = []
            for i in range(0, 96, 32):
                r = result[i:i+32]
                if count == 3:
                    self.assertEqual(r[24], count)
                else:
                    self.assertEqual(r[24], 0)  # capped allocation with no padding room
                    self.assertEqual(r[6], 0)
                self.assertEqual(r[25] % r[15], 0)
                if r[24]:
                    for base, size in ((r[25], r[15]), (r[26], r[16])):
                        end = base + size * r[24]
                        self.assertLessEqual(end, capacity)
                        for first, last in spans:
                            self.assertTrue(end <= first or base >= last)
                        spans.append((base, end))
        # Distribution allocates after existing task payloads and handles
        # an empty middle task without losing the exclusive-prefix mapping.
        record = [0] * 32
        record[13], record[15], record[16] = 1 | 2 | 8, 96 * 44, 192
        record[17], record[18], record[19], record[20] = 44, 96, 192, 65535
        record[21], record[23] = 3, 64
        arena = [0] * 65536; arena[64:67] = [2, 0, 2]
        self.write_words(rp, record); self.write_words(ap, arena)
        with patch.dict(os.environ, {"MEMU_TEST_COUNTER": "512"}):
            subprocess.run([str(runner), str(self.work / "SPV_MEMU_DIST_COALESCED.spv"),
                            str(rp), str(ap), str(out), "1", "1", "1", "helper"], check=True, capture_output=True)
        r = struct.unpack("<32I", rp.read_bytes())
        data = struct.unpack("<65536I", out.read_bytes())
        self.assertEqual(data[64:67], (0, 2, 2))
        self.assertEqual(r[24], 4)
        self.assertGreaterEqual(r[25], 512)
        self.assertEqual(r[25] % r[15], 0)
        self.assertEqual(r[6], 4 * 192)
        for tag, original in self.fixtures.items():
            for max_v in ([64, 96, 128] if tag == "MESH_TRI" else [32]):
                words = list(original)
                # The fixture's uint64 and OutputVertices both denote its
                # vertex capacity. Exercise the real hot shaders' 96/128.
                at = 5
                while at < len(words):
                    n, op = words[at] >> 16, words[at] & 65535
                    if tag == "MESH_TRI" and ((op == 16 and words[at + 2] == 26) or (op == 43 and words[at + 3] == 64)):
                        words[at + 3] = max_v
                    at += n
                for task in ([False, True] if tag == "MESH_TRI" else [False]):
                    results = []
                    for enabled in (0, 1):
                        layout, cs, vs = self.convert(words, enabled)
                        for name, module in (("cs", cs), ("vs", vs)):
                            path = self.work / f"{name}.spv"; self.write_words(path, module)
                            subprocess.run(["spirv-val", "--target-env", "vulkan1.3", str(path)], check=True)
                        rec = (U32 * 32)(); self.lib.vka_memu_rec_mesh(C.byref(layout), rec)
                        count = 4
                        rec[12], rec[21], rec[24] = 7, 3 if task else 0, count
                        rec[13] |= 1 if task else 0
                        rec[14], rec[22], rec[23] = 8, 128, 64
                        rec[25] = rec[15] * 3  # nonzero, group-aligned VBASE
                        rec[26] = rec[25] + (layout.max_v * layout.vw if not layout.indexed else rec[15] * count)
                        arena = [0x7fc12345] * (rec[26] + rec[16] * count + 1024)
                        arena[64:67] = [0, 2, 2]  # middle task emits zero meshes
                        for t in range(3):
                            arena[128 + 8*t:136 + 8*t] = [0, 100 + t, 9 + t, 3, 4, 5, 6, 7]
                        rp, ap, out = (self.work / n for n in ("records.bin", "arena.bin", "out.bin"))
                        self.write_words(rp, rec); self.write_words(ap, arena)
                        # A 2D dispatch exercises flattened workgroup indexing.
                        subprocess.run([str(runner), str(self.work / "cs.spv"), str(rp), str(ap), str(out), "2", "2", "1"], check=True, capture_output=True)
                        data = list(struct.unpack(f"<{out.stat().st_size//4}I", out.read_bytes()))
                        allowed = set()
                        for group in range(count):
                            for vertex in range(32):
                                for component in range(layout.vw):
                                    a = rec[25] + group * rec[15] + (component * max_v + vertex if enabled else vertex * layout.vw + component)
                                    allowed.add(a)
                            allowed.update(range(rec[26] + group * rec[16], rec[26] + group * rec[16] + 32 * layout.pw))
                        for i, (before, after) in enumerate(zip(arena, data)):
                            if before != after:
                                self.assertIn(i, allowed, (tag, max_v, task, enabled, i))
                        outputs = []
                        for group in range(count):
                            for primitive in range(32):
                                if layout.indexed:
                                    for corner in range(3):
                                        vi = data[rec[26] + group * rec[16] + primitive*3 + corner]
                                        outputs.append(vertex_outputs(vs, data, vi))
                                else:
                                    vi = (rec[25] // rec[15] + group) * layout.max_p + primitive
                                    outputs.append(vertex_outputs(vs, data, vi))
                        # Independent position oracle for the first primitive.
                        first = outputs[0][((11, (0,)),)]
                        expected_y = 100 if task else 0
                        expected_x = 0 if task or tag == "MESH_PTS" else 7
                        self.assertEqual(first, tuple(struct.unpack("<I", struct.pack("<f", x))[0]
                                                      for x in (expected_x, expected_y, 0, 1)))
                        results.append(outputs)
                    self.assertEqual(results[0], results[1], (tag, max_v, task))


if __name__ == "__main__":
    unittest.main()
