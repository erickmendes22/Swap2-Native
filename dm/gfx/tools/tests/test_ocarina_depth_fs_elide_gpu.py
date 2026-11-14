"""Test the actual conservative SPIR-V depth-fragment elision guard.

The GPU claim is ONLY avoided fragment execution on proven colour-masked
passes; visual equivalence is also checked in the existing cave GPU fixture.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/"dm/gfx/vk_android"
DRAW=(VK/"vka_draw.c").read_text()
HDR=(VK/"vka_depth_fs_elide.h").read_text()

SAFE="""#version 450
layout(location=0) out vec4 c;
void main() {c=vec4(0.3,0.4,0.5,1.0);}
"""
SAFE_EARLY="""#version 450
layout(early_fragment_tests) in;
layout(location=0) out vec4 c;
void main() {c=vec4(1.0);}
"""
BAD_DISCARD="""#version 450
layout(location=0) out vec4 c;
void main() {if(gl_FragCoord.x>10.0) discard;c=vec4(1.0);}
"""
BAD_DEPTH="""#version 450
layout(location=0) out vec4 c;
void main() {gl_FragDepth = gl_FragCoord.z * 0.5; c=vec4(1.0);}
"""
BAD_STORE="""#version 450
layout(set=0,binding=0,std430) buffer Store {uint b[];} data;
layout(location=0) out vec4 c;
void main() {data.b[0]=42u;c=vec4(1.0);}
"""
BAD_ATOMIC="""#version 450
layout(set=0,binding=0,std430) buffer Store {uint b[];} data;
layout(location=0) out vec4 c;
void main() {atomicAdd(data.b[0],1u);c=vec4(1.0);}
"""

class DepthFsElision(unittest.TestCase):
    def test_source_gate_keeps_queries_depth_and_original_fallback(self):
        self.assertIn('vka_depth_fs_spv_safe(spv, nbytes / 4u)',DRAW)
        self.assertIn('VKA_ENV("DM_VK_OOT_DEPTH_FS_ELIDE", 1)',DRAW)
        self.assertIn('VKA_ENV("DM_VK_UNUSED_COLOR", 0)',DRAW)
        self.assertIn('d->color.alpha_func == NVN_ALPHA_FUNC_ALWAYS',DRAW)
        self.assertIn('b->flags & (DMSH_VK_BF_RW | DMSH_VK_BF_ATOMIC | DMSH_VK_BF_NOSLOT)',DRAW)
        self.assertIn('!g_unused_color_refused',DRAW)
        self.assertIn('depth_fs_stub = 1;',DRAW)
        self.assertIn('variant = VKA_OOT_DEPTH_FS_STUB_VARIANT;',DRAW)
        self.assertNotIn('sh[1] = NULL;',DRAW)
        PSO=(VK/"vka_pso.c").read_text()
        self.assertIn('oot_depth_stub_module()',PSO)
        self.assertIn('k->fs_variant == VKA_OOT_DEPTH_FS_STUB_VARIANT',PSO)
        # The original occlusion splitting and original draw path are intact.
        self.assertIn('vka_rp_cave_depth_dirty()', (VK/"vka_exec.c").read_text())
        self.assertIn('vka_oq_pass_end();',DRAW)
        self.assertIn('vk.vkCmdDraw',DRAW)

    def test_stub_is_valid_vulkan_fragment_stage(self):
        cc=shutil.which("cc") or shutil.which("clang")
        validator=shutil.which("spirv-val")
        self.assertTrue(cc and validator)
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);c=d/"dump.c";out=d/"stub.spv";exe=d/"dump"
            c.write_text(r"""
#include <stdio.h>
#include "vka_depth_fs_stub_spv.h"
int main(int argc,char**argv) {
 if(argc!=2)return 2;
 FILE*f=fopen(argv[1],"wb");if(!f)return 3;
 if(fwrite(VKA_DEPTH_FS_STUB_SPV,1,sizeof VKA_DEPTH_FS_STUB_SPV,f)!=
    sizeof VKA_DEPTH_FS_STUB_SPV)return 4;
 fclose(f);return 0;
}
""")
            b=subprocess.run([cc,"-std=c11","-Wall","-Wextra","-Werror",
                "-I",str(VK),str(c),"-o",str(exe)],
                capture_output=True,text=True)
            self.assertEqual(b.returncode,0,b.stderr)
            subprocess.run([str(exe),str(out)],check=True)
            b=subprocess.run([validator,"--target-env","vulkan1.1",str(out)],
                capture_output=True,text=True)
            self.assertEqual(b.returncode,0,b.stdout+b.stderr)

    def test_real_translated_spirv_safety_matrix(self):
        glslang=shutil.which("glslangValidator")
        cc=shutil.which("cc") or shutil.which("clang")
        self.assertTrue(glslang and cc, "requires glslangValidator and cc")
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)
            harness=d/"check.c";exe=d/"check"
            harness.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "vka_depth_fs_elide.h"
int main(int argc,char**argv) {
 if(argc!=3)return 4;
 FILE *f=fopen(argv[1],"rb");if(!f)return 5;
 if(fseek(f,0,SEEK_END))return 6;
 long z=ftell(f);rewind(f);if(z<=0||z%4)return 7;
 uint32_t *w=malloc((size_t)z);if(!w)return 8;
 if(fread(w,1,(size_t)z,f)!=(size_t)z)return 9;
 fclose(f);
 int safe=vka_depth_fs_spv_safe(w,(size_t)z/4);
 free(w);
 if(safe!=atoi(argv[2])){fprintf(stderr,"unexpected safe=%d\n",safe);return 10;}
 return 0;
}
''')
            b=subprocess.run([cc,"-std=c11","-O2","-Wall","-Wextra",
                "-Werror","-fsanitize=undefined","-I",str(VK),
                str(harness),"-o",str(exe)],capture_output=True,text=True)
            self.assertEqual(b.returncode,0,b.stderr)
            for name,source,safe in [
                ("constant_color",SAFE,1),("early_depth",SAFE_EARLY,1),
                ("kill",BAD_DISCARD,0),("depth_write",BAD_DEPTH,0),
                ("storage_store",BAD_STORE,0),("storage_atomic",BAD_ATOMIC,0)]:
                glsl=d/(name+".frag");spv=d/(name+".spv")
                glsl.write_text(source)
                proc=subprocess.run([glslang,"-V","--target-env","vulkan1.1",
                   "-S","frag","-o",str(spv),str(glsl)],capture_output=True,text=True)
                self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
                result=subprocess.run([str(exe),str(spv),str(safe)],
                   capture_output=True,text=True)
                self.assertEqual(result.returncode,0,
                                 name+": "+result.stdout+result.stderr)
            print("actual GLSL->SPIR-V: 2 pure-colour FS accepted; kill, "
                  "depth write, storage write and atomic rejected (6/6)")

if __name__=="__main__": unittest.main()
