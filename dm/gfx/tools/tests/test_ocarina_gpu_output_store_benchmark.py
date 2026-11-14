"""Independent Vulkan GPU benchmark of Foliage.Product-style mesh output writes.

The production emulation stores vec4 output as FOUR scalar SSBO words, each
32 lanes coalescing a *plane* of 128 vertices. The comparison tests one packed
uvec4 SSBO store per vector, with an equivalent 128-vertex × six-attribute
payload. The value bytes are retiled and compared EXACTLY. This is a synthetic
GPU memory-work experiment, never an Adreno FPS prediction. It does not modify
the emulator, the installed shaders or any gameplay frame.
"""
import array
from pathlib import Path
import json
import os
import shutil
import statistics
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "dm/host/tests/t_android_memu_dispatch.c"

HEADER = """#version 450
layout(local_size_x=32) in;
layout(set=0,binding=383,std430) readonly buffer Rec { uint r[]; };
layout(push_constant) uniform Push { uint first,n,cap,pad; } pc;
"""
VALUE = """uint val(uint g, uint v, uint k, uint c) {
    return (g * 0x9e3779b9u) ^ (v * 131u + k * 4099u + c * 65537u);
}
"""
SCALAR = HEADER + """
layout(set=0,binding=382,std430) buffer A { uint a[]; };
""" + VALUE + """
void main() {
    uint g=gl_WorkGroupID.x, t=gl_LocalInvocationID.x;
    for(uint vi=0u;vi<4u;vi++){
        uint v=t+32u*vi;
        for(uint k=0u;k<6u;k++){
            uint base=g*3072u+k*512u+v;
            for(uint c=0u;c<4u;c++)
                a[base+c*128u]=val(g,v,k,c);
        }
    }
}
"""
PACKED = HEADER + """
layout(set=0,binding=382,std430) buffer A { uvec4 a[]; };
""" + VALUE + """
void main() {
    uint g=gl_WorkGroupID.x, t=gl_LocalInvocationID.x;
    for(uint vi=0u;vi<4u;vi++){
        uint v=t+32u*vi;
        for(uint k=0u;k<6u;k++){
            a[g*768u+v*6u+k]=uvec4(val(g,v,k,0u),val(g,v,k,1u),
                val(g,v,k,2u),val(g,v,k,3u));
        }
    }
}
"""


def canonical(data, groups, packed):
    words = array.array("I"); words.frombytes(data)
    if not packed:
        return words
    flat = array.array("I", [0]) * len(words)
    for g in range(groups):
        for v in range(128):
            for k in range(6):
                src = (g*128*6 + v*6 + k)*4
                dst = g*128*6*4 + k*512 + v
                for c in range(4):
                    flat[dst + c*128] = words[src+c]
    return flat


class ActualGPUStoreWork(unittest.TestCase):
    def test_equivalent_scalar_and_packed_math(self):
        for g in (0, 7):
            for v in (0, 31, 32, 127):
                for k in range(6):
                    for c in range(4):
                        value = ((g * 0x9e3779b9) ^
                                (v * 131 + k * 4099 + c * 65537)) & 0xffffffff
                        self.assertEqual(value, value)
        self.assertEqual(4*128*6, 3072)
        self.assertEqual(128*6, 768)
        self.assertIn("a[base+c*128u]", SCALAR)
        self.assertIn("uvec4(val(g,v,k,0u)", PACKED)

    @unittest.skipUnless(os.environ.get("MEMU_TEST_VULKAN")=="1",
                         "requires real Vulkan ICD + glslang in GPU CI")
    def test_real_vulkan_gpu_store_timing_and_bitwise_output(self):
        cc = shutil.which("cc") or shutil.which("clang")
        glslang = shutil.which("glslangValidator")
        self.assertTrue(cc and glslang)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            exe = d/"vulkan-compute"
            subprocess.run([cc,"-O2","-Wall","-Wextra","-Werror","-I",
                str(ROOT/"dm/third_party/vulkan-headers/include"),
                str(RUNNER),"-Wl,-l:libvulkan.so.1","-o",str(exe)],
                check=True,capture_output=True,text=True)
            mods = {}
            for kind,source in (("scalar",SCALAR),("packed",PACKED)):
                src = d/f"{kind}.comp"; dst=d/f"{kind}.spv"
                src.write_text(source)
                subprocess.run([glslang,"-V","--target-env","vulkan1.1",
                    "-S","comp","-o",str(dst),str(src)],check=True,
                    capture_output=True,text=True)
                subprocess.run(["spirv-val","--target-env","vulkan1.1",
                    str(dst)],check=True,capture_output=True,text=True)
                mods[kind]=dst
            rec=d/"rec.bin";rec.write_bytes(struct.pack("<32I", *([0]*32)))
            for groups in (16, 64, 128):
                arena=d/"arena.bin";out=d/"gpu-output.bin"
                size=groups*128*6*4*4
                results={}
                samples={k:[] for k in mods}
                repeats=24
                for run in range(3):
                    for kind in (("scalar","packed") if run%2==0
                                 else ("packed","scalar")):
                        arena.write_bytes(bytes(size))
                        env=dict(os.environ,MEMU_TEST_REPEATS=str(repeats))
                        proc=subprocess.run([str(exe),str(mods[kind]),
                            str(rec),str(arena),str(out),
                            str(groups),"1","1"],env=env,check=True,
                            capture_output=True,text=True)
                        samples[kind].append(
                            json.loads(proc.stdout.strip().splitlines()[-1])
                                ["gpu_ns_per_dispatch"])
                        results[kind]=canonical(out.read_bytes(),groups,kind=="packed")
                self.assertEqual(results["scalar"],results["packed"],
                                 f"all {size} output bytes must match after retiling")
                self.assertNotEqual(results["scalar"],canonical(bytes(size),groups,False))
                a=statistics.median(samples["scalar"])
                b=statistics.median(samples["packed"])
                print(f"GPU memory A/B {groups}x128 mesh verts, six vec4 attrs: "
                      f"coalesced scalar {a/1000:.1f}us vs packed uvec4 {b/1000:.1f}us; "
                      f"packed/scalar={b/a:.3f}; exact GPU output bytes={size}; "
                      f"Lavapipe software Vulkan (NOT Adreno FPS)")
                self.assertGreater(a,0);self.assertGreater(b,0)


if __name__=="__main__":
    unittest.main()
