"""Production classic render-pass cache versus dynamic rendering on Vulkan.

Actual draws, MRT, load/clear/discard, partial clears, independent depth/stencil
readback, cache reuse, and alternate-order CPU-recording measurements.
Software timing is an indicator only, not an Adreno frame-rate guarantee.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
VK=ROOT/'dm/gfx/vk_android'
sys.path.insert(0,str(VK/'fsr'))
import ndsr_spv

VERT='''#version 450
void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexIndex],0.5,1);}
'''
FRAG='''#version 450
layout(push_constant)uniform P{vec4 color;}pc;
layout(location=0)out vec4 a;layout(location=1)out vec4 b;
void main(){a=pc.color;b=vec4(pc.color.bgr,1);}
'''

class RenderpassCache(unittest.TestCase):
    def test_pixels_and_cpu_recording(self):
        cc,glslc=shutil.which('cc'),ndsr_spv.tool('glslc')
        if not sys.platform.startswith('linux') or not cc or not glslc:
            self.skipTest('Linux C and GLSL compilers required')
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory);env=dict(os.environ)
            if Path('/usr/share/vulkan/explicit_layer.d/VkLayer_khronos_validation.json').exists():
                env['VK_INSTANCE_LAYERS']='VK_LAYER_KHRONOS_validation'
            for stage,source in [('vert',VERT),('frag',FRAG)]:
                p=tmp/('test.'+stage);p.write_text(source);spv=str(p)+'.spv'
                subprocess.run([glslc,'--target-env=vulkan1.1',str(p),'-o',spv],check=True,capture_output=True)
                env['RP_'+stage.upper()]=spv
            exe=tmp/'renderpass'
            subprocess.run([cc,'-O2','-DVKA_NDSR_PURE','-I',str(ROOT/'dm/third_party/vulkan-headers/include'),'-I',str(VK),str(VK/'selftest/renderpass_gpu.c'),str(VK/'vka_ndsr.c'),'-ldl','-lm','-lpthread','-o',str(exe)],check=True,capture_output=True)
            r=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=180)
            if r.returncode==77:self.skipTest(r.stdout+r.stderr)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertNotIn('Validation Error',r.stdout+r.stderr)
            self.assertEqual(r.stdout.count('MRT pixels exact=1 across 5 runs'),2,r.stdout)
            self.assertIn('depth/stencil: independent aspect clears and GPU readback passed',r.stdout)
            print(r.stdout)

    def test_pipeline_compatibility_and_isolated_fallback(self):
        pso=(VK/'vka_pso.c').read_text();draw=(VK/'vka_draw.c').read_text();tex=(VK/'vka_tex.c').read_text()
        self.assertIn('VkRenderPass rp;',pso)
        self.assertEqual(pso.count('.renderPass=rp'),5)
        self.assertIn('pk.rp=rp;',pso);self.assertIn('fk.rp=rp;',pso)
        self.assertIn('if(!P->ci.renderPass)return 0;',pso)
        self.assertIn('if (!fb) {',draw)
        self.assertIn('if(!g_classic_pass)vk.vkCmdBeginRendering',draw)
        self.assertIn('if(g_classic_pass)vk.vkCmdEndRenderPass',draw)
        self.assertIn('V.driver_id==VK_DRIVER_ID_QUALCOMM_PROPRIETARY',draw)
        self.assertIn('im->cflags=ci.flags;',tex)

if __name__=='__main__':unittest.main()
