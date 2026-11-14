"""GPU-only 128-vertex foliage SSBO write elimination, exact surviving output.

Unlike SPIR-V size/CPU tests, this executes actual Vulkan GPU dispatches with
8 vertex vec4 output planes/workgroup. Variant writes all 8 planes; pruned writes
only 2 demanded by FS and MUST match the baseline for every surviving value.
This is a synthetic performance *indicator*, never a phone FPS guarantee.
"""
import json
import os
import shutil
import statistics
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
RUNNER=ROOT/"dm/host/tests/t_android_memu_dispatch.c"
INTRO="""#version 450
layout(local_size_x=32) in;
layout(set=0,binding=382,std430) buffer Arena { uint a[]; };
layout(set=0,binding=383,std430) readonly buffer Record { uint r[]; };
layout(push_constant) uniform Push {uint first,n,cap,pad;} pc;
void main() {
    uint g=gl_WorkGroupID.x,t=gl_LocalInvocationID.x;
    for(uint vi=0u;vi<4u;vi++) {
        uint v=t+vi*32u;
        uint base=g*4096u+v;
"""
# A fixed eight-attribute version of Foliage's coalesced storage layout.
# SPIR-V OpStore count genuinely changes, not an irrelevant bitcast rewrite.
def source(used):
    body=""
    for k in range(used):
        for c in range(4):
            body+=f"        a[base+{k*512+c*128}u] = (g*1664525u)^(v*131u+{k*4099+c*65537}u);\n"
    return INTRO+body+"    }\n}\n"

class GPUSelectiveStores(unittest.TestCase):
    @unittest.skipUnless(os.getenv("MEMU_TEST_VULKAN")=="1","real Vulkan ICD required")
    def test_real_vulkan_8_to_2_attribute_mesh_writes(self):
        cc=shutil.which("cc") or shutil.which("clang")
        glslang=shutil.which("glslangValidator")
        self.assertTrue(cc and glslang)
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);exe=d/"vulkan"
            subprocess.run([cc,"-O2","-Wall","-Wextra","-Werror",
                "-I",str(ROOT/"dm/third_party/vulkan-headers/include"),
                str(RUNNER),"-Wl,-l:libvulkan.so.1","-o",str(exe)],
                check=True,capture_output=True,text=True)
            mod={}
            for k in (2,8):
                src=d/f"attr{k}.comp";spv=d/f"attr{k}.spv"
                src.write_text(source(k))
                subprocess.run([glslang,"-V","--target-env","vulkan1.1",
                    "-S","comp","-o",str(spv),str(src)],check=True,capture_output=True,text=True)
                subprocess.run(["spirv-val","--target-env","vulkan1.1",str(spv)],check=True,capture_output=True,text=True)
                mod[k]=spv
            rp=d/"rec.bin";rp.write_bytes(struct.pack("<32I",*([0]*32)))
            mem=d/"arena.bin";out=d/"out.bin"
            for groups in (16,64,128):
                size=groups*4096*4
                gpu_times={2:[],8:[]}
                outputs={}
                for rep in range(5):
                    for k in ((2,8) if rep%2==0 else (8,2)):
                        mem.write_bytes(bytes(size))
                        env=dict(os.environ,MEMU_TEST_REPEATS="32")
                        task=subprocess.run([str(exe),str(mod[k]),str(rp),str(mem),
                            str(out),str(groups),"1","1"],env=env,check=True,
                            capture_output=True,text=True)
                        gpu_times[k].append(json.loads(task.stdout.strip().splitlines()[-1])
                                            ["gpu_ns_per_dispatch"])
                        outputs[k]=out.read_bytes()
                before=memoryview(outputs[8]).cast("I")
                after=memoryview(outputs[2]).cast("I")
                for group in range(groups):
                    for i in range(1024):
                        p=group*4096+i
                        self.assertEqual(before[p],after[p],
                            (groups,group,i,"all 2 surviving GPU attribute planes identical"))
                self.assertNotEqual(outputs[2],outputs[8],"dead output writes actually omitted")
                a=statistics.median(gpu_times[8]);b=statistics.median(gpu_times[2])
                print(f"GPU foliage 8->2 vec4 outputs at {groups}x128 vertices: "
                      f"all={a/1000:.2f}us pruned={b/1000:.2f}us speedup={a/b:.3f}x, "
                      f"exact surviving pixels/attributes; Lavapipe not Adreno FPS")
                self.assertGreater(a,0);self.assertGreater(b,0)

if __name__=="__main__":
    unittest.main()
