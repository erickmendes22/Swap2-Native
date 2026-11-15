"""Research GPU visibility using CURRENT query results, with no stale-frame approximation.

This does not enable conditional rendering in the application or establish
that the device driver supports it. No NVN counter/reset mapping is assumed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from dm.tools.tests.test_cave_query_gpu import VERT, FRAG

COMP = """#version 450
layout(local_size_x=32)in;
layout(set=0,binding=0,std430)readonly buffer Queries {uvec2 queries[];};
layout(set=0,binding=1,std430)writeonly buffer Arguments {uint args[];};
layout(push_constant)uniform P {uint invert;}pc;
void main(){
 uint i=gl_GlobalInvocationID.x;if(i>=2)return;
 bool visible=any(notEqual(queries[i],uvec2(0)));
 args[i*5]=3;args[i*5+1]=(visible!=(pc.invert!=0))?1:0;
 args[i*5+2]=0;args[i*5+3]=0;args[i*5+4]=0;
}
"""

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / 'dm/gfx/vk_android'


@unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN') == '1', 'real Vulkan ICD required')
class ConditionalVisibilityGPU(unittest.TestCase):
    def test_current_gpu_query_predicate_preserves_pixels_and_removes_vertex_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            env = dict(os.environ)
            for stage, source in [('vert', VERT), ('frag', FRAG), ('comp', COMP)]:
                p = d / ('visibility.' + stage)
                p.write_text(source)
                spv = str(p) + '.spv'
                subprocess.run([shutil.which('glslangValidator'), '-V', '--target-env', 'vulkan1.1',
                                '-S', stage, '-o', spv, str(p)], check=True, capture_output=True)
                env['VIS_' + stage.upper()] = spv
            exe = d / 'visibility'
            build = subprocess.run([shutil.which('cc'), '-O2', '-DVKA_NDSR_PURE',
                                    '-I', str(ROOT / 'dm/third_party/vulkan-headers/include'),
                                    '-I', str(VK), str(VK / 'selftest/conditional_visibility_gpu.c'),
                                    str(VK / 'vka_ndsr.c'), '-ldl', '-lm', '-o', str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=120)
            if run.returncode != 77:
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertNotIn('Validation Error', run.stdout + run.stderr)
                self.assertNotIn('SYNC-HAZARD', run.stdout + run.stderr)
                self.assertEqual(run.stdout.count('colour+depth exact'), 40, run.stdout)
            print(run.stdout)
            # Prove that the portable indirect paths do not depend on enabling
            # the conditional-rendering extension at device creation.
            env['VIS_NO_NATIVE'] = '1'
            portable = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(portable.returncode, 0, portable.stdout + portable.stderr)
            self.assertNotIn('Validation Error', portable.stdout + portable.stderr)
            self.assertNotIn('SYNC-HAZARD', portable.stdout + portable.stderr)
            self.assertEqual(portable.stdout.count('colour+depth exact'), 32, portable.stdout)
            print(portable.stdout)


if __name__ == '__main__':
    unittest.main()
