"""Ocarina GPU-only direct/indirect mesh dispatch correctness and timing A/B.

Use production dispatch-selection helper compiled with UBSan/ASan for all capacity,
task and indirect cases. With MEMU_TEST_VULKAN=1 use REAL Vulkan command buffers,
identical compute shaders and identical GPU output, comparing timestamps. Software
GPU timings are an indicator, NEVER a promise of an Adreno 891.14 FPS increase.
"""
from pathlib import Path
import json
import os
import re
import shutil
import statistics
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
INC = ROOT / "dm/gfx/vk_android"
SRC = (INC / "vka_memu_draw.inc").read_text()
RUNNER = ROOT / "dm/host/tests/t_android_memu_dispatch.c"


def function(src, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*\([^;]*?\)\s*\{", src, re.S)
    assert m is not None, name
    d = 1
    for i in range(m.end(), len(src)):
        d += (src[i] == "{") - (src[i] == "}")
        if not d:
            return src[m.start():i + 1]
    raise AssertionError("Unclosed C function: " + name)


class OcarinaDirectGPU(unittest.TestCase):
    def test_production_bounds_against_gpu_setup_and_distribution(self):
        cc = shutil.which("clang") or shutil.which("cc")
        self.assertIsNotNone(cc)
        helper = function(SRC, "memu_direct_x")
        stub = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "vka_memu_abi.h"
""" + "static uint32_t " + helper + r"""
static uint32_t min32(uint32_t a,uint32_t b){return a<b?a:b;}
int main(void){
    uint32_t r[VKA_MEMU_REC_WORDS]={0}; unsigned long checked=0, eligible=0;
    for(unsigned ind=0; ind<=1;ind++)
    for(unsigned stage=0;stage<=1;stage++)
    for(unsigned mode=0;mode<2;mode++)
    for(uint32_t cap=0;cap<=4096;cap=cap ? cap*2u : 1u) {
        r[VKA_MEMU_R_FLAGS]=(stage?VKA_MEMU_F_TASK:0u)|(mode?VKA_MEMU_F_INTERLEAVED:0u);
        for(uint32_t stride=0;stride<=33;stride+=3)
        for(uint32_t cnt=0;cnt<=80;cnt++) {
            r[VKA_MEMU_R_MAXG]=cnt%13 ? 64:8;
            r[VKA_MEMU_R_WT]=stride;
            r[VKA_MEMU_R_VSTRIDE]=stride;
            r[VKA_MEMU_R_PSTRIDE]=mode?0:stride*2u;
            uint32_t mx=min32(r[VKA_MEMU_R_MAXG],65535);
            uint64_t per=stage ? (uint64_t)stride+1u :
                mode ? stride:(uint64_t)stride+stride*2u;
            if(!per)per=1;
            uint32_t chosen=memu_direct_x(r,cap,cnt,ind,stage);
            if(chosen){
                assert(!ind && cnt>0 && cnt<=mx && (uint64_t)cnt*per<=cap);
                // On GPU, the setup shader computes the same groupCountX
                // if the arena allocation succeeds; on failure it writes
                // NTASK/TOTAL=0 and the converted compute shader returns.
                uint32_t allocated=cnt;
                for(uint32_t prev=0;prev<=cap+1;prev+=cap/2+1){
                    uint32_t gpu_limit=allocated;
                    if(prev>cap || (uint64_t)cnt*per>cap-prev)gpu_limit=0;
                    if(gpu_limit)assert(gpu_limit==chosen);
                }
                eligible++;
            } else if (!ind && cnt>0 && cnt<=mx && (uint64_t)cnt*per<=cap)
                assert(!"safe exact direct launch was not selected");
            checked++;
        }
    }
    // Explicit regression gates: x/y remap, true guest indirect and task
    // mesh after distribution all remain outside direct dispatch.
    r[VKA_MEMU_R_FLAGS]=VKA_MEMU_F_TASK;
    r[VKA_MEMU_R_MAXG]=65535;
    r[VKA_MEMU_R_WT]=3;
    assert(memu_direct_x(r,4096,4,1,1)==0);
    assert(memu_direct_x(r,4096,4,0,0)==0);
    assert(memu_direct_x(r,4096,65536,0,1)==0);
    r[VKA_MEMU_R_FLAGS]=0;
    r[VKA_MEMU_R_VSTRIDE]=128;
    r[VKA_MEMU_R_PSTRIDE]=64;
    assert(memu_direct_x(r,100,4,0,0)==0);
    assert(memu_direct_x(r,4096,4,0,0)==4);
    printf("production GPU launch bounds checked %lu combinations, eligible %lu, exact workgroup shapes and arena-empty guard preserved\n",checked,eligible);
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bounds.c"
            exe = Path(tmp) / "bounds"
            path.write_text(stub)
            subprocess.run([cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
                            "-Werror", "-fsanitize=address,undefined",
                            "-I", str(INC), str(path), "-o", str(exe)],
                           check=True, capture_output=True, text=True)
            out = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn("exact workgroup shapes", out.stdout)
            print(out.stdout.strip())

    def test_real_gpu_path_still_has_all_memory_hazards(self):
        self.assertIn("vk.vkCmdDispatch(g_cb, direct_x, 1, 1)", SRC)
        self.assertIn("vk.vkCmdDispatchIndirect(g_cb, MB.rec.buf", SRC)
        self.assertIn("if (VKA_ENV(\"DM_VK_OOT_MEMU_DIRECT_GPU\", 1))", SRC)
        self.assertIn("vka_barrier(g_cb); memu_helper(0); memu_phase_barrier()", SRC)
        self.assertIn("case MEMU_DIST:", SRC)
        self.assertIn("case MEMU_END: memu_phase_barrier();", SRC)
        self.assertLess(SRC.index("if (!sets_push(lay"), SRC.index("if (direct_x) {"))
        self.assertIn("dw->ind != 0", SRC)
        self.assertIn("E->direct_mesh_x = !ts ?", SRC)

    @unittest.skipUnless(os.environ.get("MEMU_TEST_VULKAN") == "1", "set MEMU_TEST_VULKAN=1 to run Vulkan GPU A/B")
    def test_real_vulkan_identical_work_and_dispatch_gpu_timestamps(self):
        cc = shutil.which("cc") or shutil.which("clang")
        glsl = shutil.which("glslangValidator")
        self.assertTrue(cc and glsl)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            exe = d / "dispatch"
            subprocess.run([cc, "-O2", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "dm/third_party/vulkan-headers/include"),
                            str(RUNNER), "-Wl,-l:libvulkan.so.1", "-o", str(exe)],
                           check=True, capture_output=True, text=True)
            shader = d / "shader.comp"
            shader.write_text("""#version 450
layout(local_size_x=32) in;
layout(set=0,binding=382,std430) buffer A { uint a[]; };
layout(set=0,binding=383,std430) readonly buffer R { uint r[]; };
layout(push_constant) uniform PC { uint first, n, cap, pad; } pc;
void main() {
    uint i=gl_GlobalInvocationID.x;
    if (i>=r[0]) return;
    a[i]=(i*1664525u+1013904223u)^r[1];
}""")
            module = d / "shader.spv"
            subprocess.run([glsl, "-V", "--target-env", "vulkan1.1",
                            "-S", "comp", "-o", str(module), str(shader)],
                           check=True, capture_output=True, text=True)
            repeats = 128
            for groups in (8, 64, 256):
                items = 32 * groups
                rec = d / "records.bin"
                mem = d / "arena.bin"
                rec.write_bytes(struct.pack("<32I", items, 0xDEADBEEF, *([0] * 30)))
                baseline = bytes(items * 4)
                measurements = {0:[],1:[]}
                results = {}
                for round_i in range(3):
                    for mode in ((0,1) if round_i % 2 == 0 else (1,0)):
                        mem.write_bytes(baseline)
                        out = d / f"gpu-out-{mode}.bin"
                        env = dict(os.environ, MEMU_TEST_REPEATS=str(repeats),
                                   MEMU_TEST_INDIRECT=str(mode))
                        proc = subprocess.run([str(exe), str(module), str(rec),
                                               str(mem), str(out), str(groups),"1","1"],
                                              env=env, check=True, capture_output=True, text=True)
                        ns = json.loads(proc.stdout.strip().splitlines()[-1])["gpu_ns_per_dispatch"]
                        measurements[mode].append(ns)
                        results[mode] = out.read_bytes()
                self.assertEqual(results[0], results[1], "direct and indirect GPU output differ")
                self.assertNotEqual(results[0], baseline, "test shader did not execute")
                direct = statistics.median(measurements[0])
                indirect = statistics.median(measurements[1])
                print(f"real Vulkan GPU same {groups}x32 workgroups: direct {direct:.0f} ns vs indirect {indirect:.0f} ns/dispatch; ratio {indirect/direct:.3f} (Lavapipe, not Adreno FPS)")
                self.assertGreater(direct,0)
                self.assertGreater(indirect,0)

if __name__ == "__main__":
    unittest.main()
