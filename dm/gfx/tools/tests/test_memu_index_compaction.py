"""Production mesh-index compaction: exact order, memory bounds and GPU raster.

No game data. Optional software-GPU timing is never a phone FPS prediction.
"""
import ctypes as C
import importlib.util
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / 'dm/gfx/vk_android'
GPU = (os.environ.get('VK_ICD_FILENAMES') and shutil.which('glslangValidator')
       and shutil.which('spirv-val') and importlib.util.find_spec('numpy')
       and importlib.util.find_spec('vulkan'))


def function(source, name):
    m = re.search(r'\b' + name + r'\s*\([^;]*?\)\s*\{', source, re.S)
    assert m, name
    depth = 1
    for i in range(m.end(), len(source)):
        depth += (source[i] == '{') - (source[i] == '}')
        if not depth:
            return source[m.start():i + 1]
    raise AssertionError(name)


class CompactionGuards(unittest.TestCase):
    def test_real_fragment_auditor(self):
        with tempfile.TemporaryDirectory() as td:
            shared = Path(td) / 'audit.so'
            subprocess.run([shutil.which('cc'), '-shared', '-fPIC', '-O1',
                            str(VK / 'vka_memu_spv.c'), '-o', str(shared)], check=True)
            lib = C.CDLL(str(shared))
            f = lib.vka_memu_fs_compact_safe
            f.argtypes = [C.POINTER(C.c_uint32), C.c_size_t]
            def audit(words):
                return f((C.c_uint32 * len(words))(*words), len(words))
            base = [0x07230203, 0x00010300, 0, 20, 0, 4 << 16 | 15, 4, 1, 0]
            self.assertEqual(audit(base), 1)
            self.assertEqual(audit(base + [4 << 16 | 71, 5, 11, 7]), 0)
            self.assertEqual(audit(base + [5 << 16 | 72, 5, 0, 11, 7]), 0)
            self.assertEqual(audit(base + [4 << 16 | 71, 5, 11, 15]), 1)
            self.assertEqual(audit(base + [0]), 0)
            self.assertEqual(audit(base + [9 << 16 | 71, 5]), 0)
            wrong = base.copy(); wrong[6] = 0
            self.assertEqual(audit(wrong), 0)
            self.assertEqual(audit(base[:5]), 0)

    def test_real_draw_eligibility(self):
        code = r'''
#include <stdint.h>
#include <assert.h>
#include <stddef.h>
#define NVN_POLYGON_MODE_FILL 2
typedef struct {int indexed;unsigned max_p;} vka_memu_layout;
typedef struct {int rast_discard,tf_on;struct{int mode;} poly;void*bst[8];} vka_dstate;
typedef struct{int unused;} vka_shader;
static int available=1,safe=1,resolved=1,refused=0;
static int vka_memu_compact_available(void){return available;}
static int vka_memu_compact_fs_safe(vka_shader*p){(void)p;return safe;}
static int resolve(void*p,int stage,vka_shader**out,unsigned*bad){(void)p;assert(stage==1);*out=0;*bad=refused;return resolved;}
''' + 'static int ' + function((VK / 'vka_memu_draw.inc').read_text(), 'memu_compact_eligible') + r'''
int main(void){
 vka_dstate d={.poly={2}};vka_memu_layout l={1,32};
 assert(memu_compact_eligible(&d,&l));
 for(int m=0;m<4;m++){d.poly.mode=m;assert(memu_compact_eligible(&d,&l)==(m==2));}d.poly.mode=2;
 d.tf_on=1;assert(!memu_compact_eligible(&d,&l));d.tf_on=0;
 d.rast_discard=1;assert(!memu_compact_eligible(&d,&l));d.rast_discard=0;
 l.indexed=0;assert(!memu_compact_eligible(&d,&l));l.indexed=1;
 l.max_p=15;assert(!memu_compact_eligible(&d,&l));l.max_p=32;
 safe=0;assert(!memu_compact_eligible(&d,&l));safe=1;
 available=0;assert(!memu_compact_eligible(&d,&l));available=1;
 resolved=0;assert(!memu_compact_eligible(&d,&l));resolved=1;
 refused=1;assert(!memu_compact_eligible(&d,&l));
}
'''
        with tempfile.TemporaryDirectory() as td:
            c = Path(td) / 'guard.c'; c.write_text(code)
            exe = Path(td) / 'guard'
            subprocess.run(['cc', '-std=c11', '-O1', '-g', '-fsanitize=address,undefined', str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_integration_retains_barriers_and_original_list_on_failure(self):
        src = (VK / 'vka_memu_draw.inc').read_text()
        self.assertIn('if (memu_compact_eligible(d, &mi->L))', src)
        tail = src[src.index('case MEMU_END:'):]
        self.assertLess(tail.index('memu_helper(2)'), tail.index('memu_phase_barrier();'))
        self.assertIn('VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &mb', tail)
        self.assertIn('if (!target) return;', function(src, 'memu_helper'))
        shader = (VK / 'memu/memu_compact.comp').read_text()
        self.assertIn('subgroupBallotExclusiveBitCount(active_mask)', shader)
        self.assertNotIn('gl_LocalInvocationIndex', shader)
        self.assertIn('n > pc.cap - first', shader)
        host = (VK / 'vka_memu.c').read_text()
        self.assertIn('g_ar[i].fence <= done', host)
        self.assertIn('g_compact_input += a->cp[VKA_MEMU_CTL_COMPACT_INPUT]', host)


@unittest.skipUnless(GPU, 'explicit Vulkan ICD and optional probe dependencies required')
class CompactionGpu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.tmp = tempfile.TemporaryDirectory(); cls.work = Path(cls.tmp.name)
        cls.runner = cls.work / 'dispatch'
        subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'dm/third_party/vulkan-headers/include'),
                        str(ROOT / 'dm/host/tests/t_android_memu_dispatch.c'),
                        '-Wl,-l:libvulkan.so.1', '-o', str(cls.runner)], check=True)
        text = (VK / 'vka_memu_compact_spv.h').read_text()
        body = re.search(r'SPV_MEMU_COMPACT\[\d+\] = \{(.*?)\};', text, re.S).group(1)
        words = [int(x, 16) for x in re.findall(r'0x[0-9a-f]+', body)]
        cls.module = cls.work / 'compact.spv'
        cls.module.write_bytes(struct.pack('<%dI' % len(words), *words))
        subprocess.run(['spirv-val', '--target-env', 'vulkan1.1', str(cls.module)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_shader(self, arena, records):
        np = self.np
        inp = self.work / 'input.bin'; inp.write_bytes(arena.tobytes())
        rec = self.work / 'records.bin'; rec.write_bytes(records.tobytes())
        out = self.work / 'out.bin'; ctl = self.work / 'ctl.bin'
        result = subprocess.run([str(self.runner), str(self.module), str(rec), str(inp), str(out),
                                 str(len(records)), '1', '1', 'helper'],
                                env=dict(os.environ, MEMU_TEST_CTL_OUT=str(ctl)), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (np.frombuffer(out.read_bytes(), dtype=np.uint32).copy(),
                np.frombuffer(rec.read_bytes(), dtype=np.uint32).reshape((-1, 32)).copy(),
                np.frombuffer(ctl.read_bytes(), dtype=np.uint32).copy())

    def test_gpu_order_bounds_dense_sparse_and_noop_records(self):
        np = self.np; rng = random.Random(774)
        arena = [0xdeadbeef] * 11; records = []; expected = []; ni = no = 0
        for nt in (0, 1, 2, 63, 64, 65, 127, 128, 129, 513, 4096):
            for density in (0, 1, 4):
                first = len(arena); source = []
                for i in range(nt):
                    t = [3*i+1, 3*i+2, 3*i+3]
                    if density == 0 or (density == 1 and rng.randrange(4)):
                        if i % 3 == 0: t[1] = t[0]
                        elif i % 3 == 1: t[2] = t[0]
                        else: t[2] = t[1]
                    source.append(t)
                source = np.array(source, dtype=np.uint32).reshape((-1, 3))
                good = source[(source[:, 0] != source[:, 1]) & (source[:, 0] != source[:, 2]) & (source[:, 1] != source[:, 2])]
                arena.extend(source.reshape(-1).tolist()); arena.extend([0xdeadbeef] * 13)
                r = np.zeros(32, dtype=np.uint32); r[6:11] = [3*nt, 1, first, 0, 0]; r[13] = 18; r[26] = first
                records.append(r); expected.append((first, good.reshape(-1).copy()))
                ni += nt; no += len(good)
        before = np.array(arena, dtype=np.uint32); rec = np.array(records, dtype=np.uint32)
        # Unsupported flags and out-of-range records must leave all state alone.
        for flags, first, count in ((2, 0, 3), (16, 0, 3), (18, len(before)+1, 3), (18, 11, 4)):
            r = np.zeros(32, dtype=np.uint32); r[6] = count; r[13] = flags; r[26] = first
            rec = np.vstack((rec, r))
        after, changed, ctl = self.run_shader(before, rec)
        oracle = before.copy(); expected_rec = rec.copy()
        for i, (first, good) in enumerate(expected):
            oracle[first:first+len(good)] = good; expected_rec[i, 6] = len(good)
        np.testing.assert_array_equal(after, oracle)
        np.testing.assert_array_equal(changed, expected_rec)
        self.assertEqual((int(ctl[2]), int(ctl[3])), (ni, no))
        self.assertEqual(len(after), len(before))
        print(f'GPU compaction: {ni} -> {no} triangles; stable indices, exact guards, no extra arena bytes')

    def test_gpu_raster_and_precise_occlusion_match(self):
        import vulkan as v
        np = self.np
        sys.path.insert(0, str(ROOT / 'dm/gfx/tools'))
        from fragment_gpu_probe import Probe
        nt = 1025
        triangles = np.arange(nt*3, dtype=np.uint32).reshape((-1, 3))
        triangles[np.arange(nt) % 4 != 0, 1] = triangles[np.arange(nt) % 4 != 0, 0]
        arena = np.concatenate((np.full(11, 0xdeadbeef, dtype=np.uint32), triangles.reshape(-1), np.full(13, 0xdeadbeef, dtype=np.uint32)))
        records = np.zeros((1, 32), dtype=np.uint32); records[0, 6:11] = [nt*3, 1, 11, 0, 0]; records[0, 13] = 18; records[0, 26] = 11
        compact, rec, _ = self.run_shader(arena, records)
        vertex = self.work / 'raster.vert'; fragment = self.work / 'raster.frag'
        vertex.write_text('''#version 450
layout(location=0) flat out vec4 color;
void main(){uint id=uint(gl_VertexIndex), n=id/3u, corner=id%3u;
vec2 p=vec2((corner<<1u)&2u,corner&2u);
float scale=0.1+float(n%11u)/12.0;
vec2 offset=vec2(float(n%7u)/7.0,float(n%5u)/5.0)*0.3;
gl_Position=vec4((p*2.0-1.0)*scale+offset,0.5,1.0);
color=vec4(float(n%13u)/13.0,float(n%17u)/17.0,float(n%19u)/19.0,0.2);}''')
        fragment.write_text('''#version 450
layout(location=0) flat in vec4 color;layout(location=0) out vec4 outcolor;
void main(){outcolor=color;}''')
        for p in (vertex, fragment):
            subprocess.run(['glslangValidator', '-V', '--target-env', 'vulkan1.3', str(p), '-o', str(p)+'.spv'], check=True, stdout=subprocess.DEVNULL)
        create_device = v.vkCreateDevice
        def precise_device(physical, info, allocator):
            if not v.vkGetPhysicalDeviceFeatures(physical).occlusionQueryPrecise:
                self.skipTest('precise occlusion queries unavailable')
            info.pEnabledFeatures.occlusionQueryPrecise = 1
            return create_device(physical, info, allocator)
        with patch.object(v, 'vkCreateDevice', side_effect=precise_device):
            probe = Probe([], Path(str(vertex)+'.spv'), width=67)
        query = v.vkCreateQueryPool(probe.device, v.VkQueryPoolCreateInfo(queryType=v.VK_QUERY_TYPE_OCCLUSION, queryCount=1), None)
        blend = v.VkPipelineColorBlendAttachmentState
        def alpha_blend(*a, **kw):
            kw.update(blendEnable=1, srcColorBlendFactor=v.VK_BLEND_FACTOR_SRC_ALPHA,
                      dstColorBlendFactor=v.VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
                      colorBlendOp=v.VK_BLEND_OP_ADD, srcAlphaBlendFactor=v.VK_BLEND_FACTOR_ONE,
                      dstAlphaBlendFactor=v.VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA, alphaBlendOp=v.VK_BLEND_OP_ADD)
            return blend(*a, **kw)
        sl = v.vkCreateDescriptorSetLayout(probe.device, v.VkDescriptorSetLayoutCreateInfo(bindingCount=3,
            pBindings=[v.VkDescriptorSetLayoutBinding(binding=i, descriptorType=v.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                descriptorCount=1, stageFlags=v.VK_SHADER_STAGE_COMPUTE_BIT) for i in range(3)]), None)
        layout = v.vkCreatePipelineLayout(probe.device, v.VkPipelineLayoutCreateInfo(setLayoutCount=1, pSetLayouts=[sl],
            pushConstantRangeCount=1, pPushConstantRanges=[v.VkPushConstantRange(stageFlags=v.VK_SHADER_STAGE_COMPUTE_BIT, size=16)]), None)
        pool = v.vkCreateDescriptorPool(probe.device, v.VkDescriptorPoolCreateInfo(maxSets=1, poolSizeCount=1,
            pPoolSizes=[v.VkDescriptorPoolSize(type=v.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, descriptorCount=3)]), None)
        ds = v.vkAllocateDescriptorSets(probe.device, v.VkDescriptorSetAllocateInfo(descriptorPool=pool, descriptorSetCount=1, pSetLayouts=[sl]))[0]
        # Keep the CFFI stage object alive: the embedded stage copies its
        # pName pointer, whose owner must survive vkCreateComputePipelines.
        stage = v.VkPipelineShaderStageCreateInfo(stage=v.VK_SHADER_STAGE_COMPUTE_BIT,
            module=probe.module(self.module), pName='main')
        create = v.VkComputePipelineCreateInfo(layout=layout, stage=stage)
        cp = v.vkCreateComputePipelines(probe.device, v.VK_NULL_HANDLE, 1, [create], None)[0]
        try:
            with patch.object(v, 'VkPipelineColorBlendAttachmentState', side_effect=alpha_blend):
                pipeline = probe.pipeline(Path(str(fragment)+'.spv'))
            begin = v.vkCmdBeginRendering; end = v.vkCmdEndRendering
            def begin_query(cmd, info):
                v.vkCmdResetQueryPool(cmd, query, 0, 1)
                if enable_compact:
                    v.vkCmdBindPipeline(cmd, v.VK_PIPELINE_BIND_POINT_COMPUTE, cp)
                    v.vkCmdBindDescriptorSets(cmd, v.VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1, [ds], 0, None)
                    push = v.ffi.new('uint32_t[]', [0, 1, len(arena), 0])
                    v.vkCmdPushConstants(cmd, layout, v.VK_SHADER_STAGE_COMPUTE_BIT, 0, 16, push)
                    v.vkCmdDispatch(cmd, 1, 1, 1)
                    barrier = v.VkMemoryBarrier(srcAccessMask=v.VK_ACCESS_SHADER_WRITE_BIT,
                        dstAccessMask=v.VK_ACCESS_MEMORY_READ_BIT | v.VK_ACCESS_MEMORY_WRITE_BIT)
                    v.vkCmdPipelineBarrier(cmd, v.VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                        v.VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 1, [barrier], 0, None, 0, None)
                begin(cmd, info); v.vkCmdBeginQuery(cmd, query, 0, v.VK_QUERY_CONTROL_PRECISE_BIT)
            def end_query(cmd):
                v.vkCmdEndQuery(cmd, query, 0); end(cmd)
                barrier = v.VkMemoryBarrier(srcAccessMask=v.VK_ACCESS_SHADER_WRITE_BIT, dstAccessMask=v.VK_ACCESS_HOST_READ_BIT)
                v.vkCmdPipelineBarrier(cmd, v.VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                    v.VK_PIPELINE_STAGE_HOST_BIT, 0, 1, [barrier], 0, None, 0, None)
            images = []; samples = []; times = []
            for enable_compact in (False, True, False, True):
                # Source records and source indices on EVERY run. The compute
                # helper and indexed INDIRECT raster run on the SAME queue,
                # with no CPU readback or count substitution between them.
                index = probe.buffer(arena.tobytes(), v.VK_BUFFER_USAGE_INDEX_BUFFER_BIT | v.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)
                indirect = probe.buffer(records.tobytes(), v.VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT | v.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)
                ctl = probe.buffer(bytes(64), v.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)
                buffers = [indirect, ctl, index]
                writes = [v.VkWriteDescriptorSet(dstSet=ds, dstBinding=i, descriptorCount=1,
                    descriptorType=v.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, pBufferInfo=[v.VkDescriptorBufferInfo(buffer=b[0], offset=0, range=len(b[2]))])
                    for i, b in enumerate(buffers)]
                v.vkUpdateDescriptorSets(probe.device, 3, writes, 0, None)
                def draw(cmd, *_):
                    v.vkCmdBindIndexBuffer(cmd, index[0], 0, v.VK_INDEX_TYPE_UINT32)
                    v.vkCmdDrawIndexedIndirect(cmd, indirect[0], 24, 1, 20)
                with patch.object(v, 'vkCmdDraw', side_effect=draw), patch.object(v, 'vkCmdBeginRendering', side_effect=begin_query), patch.object(v, 'vkCmdEndRendering', side_effect=end_query):
                    images.append(probe.render(pipeline, 0))
                times.append(probe.gpu_ms)
                expected_count = int(rec[0, 6]) if enable_compact else nt*3
                self.assertEqual(int(np.frombuffer(bytes(indirect[2]), dtype=np.uint32)[6]), expected_count)
                n = v.ffi.new('uint64_t[1]')
                v.vkGetQueryPoolResults(probe.device, query, 0, 1, 8, n, 8, v.VK_QUERY_RESULT_64_BIT | v.VK_QUERY_RESULT_WAIT_BIT)
                samples.append(int(n[0]))
            for image, sample in zip(images[1:], samples[1:]):
                np.testing.assert_array_equal(images[0], image); self.assertEqual(samples[0], sample)
            self.assertGreater(samples[0], 0)
            print(f'GPU raster: blended pixels and {samples[0]} precise covered samples match; 1025 -> {int(rec[0,6])//3} triangles')
            print(f'Software-only warm GPU interval including compaction: original={times[2]:.3f} ms compact={times[3]:.3f} ms; not Adreno FPS')
        finally:
            v.vkDestroyPipeline(probe.device, cp, None)
            v.vkDestroyDescriptorPool(probe.device, pool, None)
            v.vkDestroyPipelineLayout(probe.device, layout, None)
            v.vkDestroyDescriptorSetLayout(probe.device, sl, None)
            v.vkDestroyQueryPool(probe.device, query, None); probe.close()



if __name__ == '__main__':
    unittest.main()
