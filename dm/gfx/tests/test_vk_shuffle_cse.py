"""The Vulkan library's shuffles with their constant addends taken out and repeats in a block shared (vk_android_spv.py shuffle_cse, run by vk_android_build.py finish()
before shuffle_lds): the translator's LDSM pattern (one register shuffled at several immediates, four rows each), nested constants with wraparound, a float shuffle of
the same bits, what it leaves (an addend that is not a constant, a subtraction, another block, a register written in between), spirv-val of the result and of its
shuffle_lds module, and on this Mac's GPU (spirv-cross to MSL, 32-lane SIMD-groups) both modules' outputs against the original's, bit for bit. In SPIR-V assembly, as the
translator writes it (registers in Function variables, passed to helpers by pointer): what ends the sharing (a call that writes the register, a demote, a call of a
function that may kill, itself or through another call) and what does not (a call of another register), a register reloaded in a loop after a load in an earlier block
(BlockValues numbers loads by block), and the keep bound."""
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[0] / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(HERE))
import vk_android_spv as spv  # noqa: E402
from test_vk_shuffle_lds import SPIRV_CROSS, RUNNER, compile_module, ops  # noqa: E402

SHADER = '''#version 450
#extension GL_KHR_shader_subgroup_basic : require
#extension GL_KHR_shader_subgroup_shuffle : require
layout(local_size_x = 128) in;
layout(set = 0, binding = 0, std430) readonly buffer In { uint w[]; } src;
layout(set = 0, binding = 1, std430) writeonly buffer Out { uint w[]; } dst;

void main()
{
    uint gid = gl_GlobalInvocationID.x, l = gl_SubgroupInvocationID & 31u, g = l >> 2, s = gl_SubgroupInvocationID & ~31u;
    uint a = src.w[gid * 4u], b = src.w[gid * 4u + 1u], c = src.w[gid * 4u + 2u];
    uint p = a + 0x20u;   // LDSM.x4 [Ra + 0x20]: the rows of four matrices (a register stored, then loaded for each shuffle)
    uint r0 = subgroupShuffle(p, s | g) ^ subgroupShuffle(p, s | (g + 8u)) ^ subgroupShuffle(p, s | (g + 16u)) ^ subgroupShuffle(p, s | (g + 24u));
    uint q = a + 0x240u;   // LDSM.x4 [Ra + 0x240]: the same four shuffles of a
    uint r1 = subgroupShuffle(q, s | g) + subgroupShuffle(q, s | (g + 8u)) * 3u + subgroupShuffle(q, s | (g + 16u)) * 5u + subgroupShuffle(q, s | (g + 24u)) * 7u;
    uint n = (a + 3u) + 0xfffffff0u;   // two constants, the sum wrapping
    r1 ^= subgroupShuffle(n, s | (g + 8u));
    float f = uintBitsToFloat(a);
    uint r2 = floatBitsToUint(subgroupShuffle(f, s | g)) ^ subgroupShuffle(a + b, s | g);   // a's bits as a float: shared; a + b: no constant
    if ((gl_WorkGroupID.x & 1u) != 0u) r2 += subgroupShuffle(a + 0x20u, s | g);   // another block: shuffled again (a uniform branch: a lane outside reads as undefined)
    a = b;   // the register written: a later shuffle of it is of another value
    uint r3 = subgroupShuffle(a + 0x20u, s | g) ^ subgroupShuffle(c - 4u, s | (31u - l));
    dst.w[gid * 4u] = r0; dst.w[gid * 4u + 1u] = r1; dst.w[gid * 4u + 2u] = r2; dst.w[gid * 4u + 3u] = r3;
}
'''


def validate(test, d, m, name):
    (d / f'{name}.spv').write_bytes(m.data())
    r = subprocess.run(['spirv-val', '--target-env', 'vulkan1.3', str(d / f'{name}.spv')], capture_output=True, text=True)
    test.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(shutil.which('glslangValidator') and shutil.which('spirv-val'), 'needs glslang and SPIRV-Tools')
class ShuffleCseRewrite(unittest.TestCase):
    def test_factored_and_shared(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); m = compile_module(d, SHADER)
            self.assertEqual(len(ops(m, spv.OP_GROUP_NON_UNIFORM_SHUFFLE)), 14)
            # factored: p's 4, q's 4, n, the branch's and the last a + 0x20; shared: q's 4 (p's rows), n (row g + 8), f (row g, as a float)
            self.assertEqual(spv.shuffle_cse(m), (11, 6))
            sh = ops(m, spv.OP_GROUP_NON_UNIFORM_SHUFFLE)
            self.assertEqual(len(sh), 8)   # a's 4 rows, a + b, the branch's, b's and c - 4's
            u32 = m.find_type(spv.OP_TYPE_INT, 32, 0)
            self.assertTrue(all(x[1] == u32 for x in sh))
            adds = [x for x in ops(m, spv.OP_IADD) if any(x[3] == y[2] for y in sh)]   # shuffle(x) + c
            self.assertEqual(len(adds), 4 + 4 + 1 + 1 + 1)   # (n's second constant adds to the first's sum)
            self.assertTrue(all(x[4] in m.consts for x in adds))
            validate(self, d, m, 'cse')
            self.assertEqual(spv.shuffle_cse(m), (0, 0))   # nothing left to do
            self.assertTrue(spv.shuffle_lds(m, 32768))
            validate(self, d, m, 'lds')

    def test_left_alone(self):
        src = SHADER[:SHADER.index('void main()')] + '''void main()
{
    uint l = gl_SubgroupInvocationID & 31u, a = src.w[gl_GlobalInvocationID.x], b = src.w[gl_GlobalInvocationID.x + 1u];
    dst.w[gl_GlobalInvocationID.x] = subgroupShuffle(a + b, l) ^ subgroupShuffle(a, l ^ 1u) ^ subgroupShuffle(b - 4u, l ^ 2u);
}
'''
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); m = compile_module(d, src)
            before = m.data()
            self.assertEqual(spv.shuffle_cse(m), (0, 0))   # no constant addend, no repeat
            self.assertEqual(m.data(), before)


ASM = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformShuffle
OpCapability DemoteToHelperInvocation
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %in %out
OpExecutionMode %main OriginUpperLeft
OpDecorate %in Location 0
OpDecorate %in Flat
OpDecorate %out Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%uint = OpTypeInt 32 0
%bool = OpTypeBool
%pin = OpTypePointer Input %uint
%pout = OpTypePointer Output %uint
%pfn = OpTypePointer Function %uint
%fnp = OpTypeFunction %void %pfn
%in = OpVariable %pin Input
%out = OpVariable %pout Output
%c1 = OpConstant %uint 1
%sg = OpConstant %uint 3
%c5 = OpConstant %uint 5
%c6 = OpConstant %uint 6
%c32 = OpConstant %uint 32
%c64 = OpConstant %uint 64
%c100 = OpConstant %uint 100
%set = OpFunction %void None %fnp
%sp = OpFunctionParameter %pfn
%sl = OpLabel
OpStore %sp %c64
OpReturn
OpFunctionEnd
%kf = OpFunction %void None %fn
%kl = OpLabel
%kx = OpLoad %uint %in
%kc = OpULessThan %bool %kx %c5
OpSelectionMerge %km None
OpBranchConditional %kc %kk %km
%kk = OpLabel
OpKill
%km = OpLabel
OpReturn
OpFunctionEnd
%kf2 = OpFunction %void None %fn
%k2l = OpLabel
%k2r = OpFunctionCall %void %kf
OpReturn
OpFunctionEnd
%main = OpFunction %void None %fn
%e = OpLabel
%r = OpVariable %pfn Function
%t = OpVariable %pfn Function
%v = OpLoad %uint %in
OpStore %r %v
BODY
OpReturn
OpFunctionEnd
'''
# a register shuffled at +32, MID, reloaded and shuffled at +32 again (the translator's two LDSMs of one base around other code)
TWO = '''%a0 = OpLoad %uint %r
%p0 = OpIAdd %uint %a0 %c32
%s0 = OpGroupNonUniformShuffle %uint %sg %p0 %c5
MID
%a1 = OpLoad %uint %r
%p1 = OpIAdd %uint %a1 %c32
%s1 = OpGroupNonUniformShuffle %uint %sg %p1 %c5
%x = OpBitwiseXor %uint %s0 %s1
OpStore %out %x'''


@unittest.skipUnless(shutil.which('spirv-as') and shutil.which('spirv-val'), 'needs SPIRV-Tools (spirv-as, spirv-val)')
class ShuffleCseAsm(unittest.TestCase):
    def build(self, d, body):
        (d / 'a.spvasm').write_text(ASM.replace('BODY', body))
        r = subprocess.run(['spirv-as', '--target-env', 'vulkan1.3', str(d / 'a.spvasm'), '-o', str(d / 'a.spv')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return spv.Module((d / 'a.spv').read_bytes())

    def run_pass(self, body, want, keep=spv.SHUFFLE_KEEP):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); m = self.build(d, body)
            validate(self, d, m, 'orig')
            n = len(ops(m, spv.OP_GROUP_NON_UNIFORM_SHUFFLE))
            self.assertEqual(spv.shuffle_cse(m, keep), want)
            self.assertEqual(len(ops(m, spv.OP_GROUP_NON_UNIFORM_SHUFFLE)), n - want[1])
            validate(self, d, m, 'cse')

    def test_calls_and_demote(self):
        cases = {'': (2, 1),   # nothing between: shared
                 '%cr = OpFunctionCall %void %set %t': (2, 1),   # a call that writes another register
                 '%cr = OpFunctionCall %void %set %r': (2, 0),   # a call that writes this one (through its pointer)
                 'OpStore %r %c6': (2, 0),   # a store to it
                 'OpDemoteToHelperInvocation': (2, 0),   # the set of invocations changes
                 '%cr = OpFunctionCall %void %kf': (2, 0),   # a call of a function that may kill
                 '%cr = OpFunctionCall %void %kf2': (2, 0)}   # and of one that calls it
        for mid, want in cases.items():
            with self.subTest(mid=mid): self.run_pass(TWO.replace('MID', mid), want)

    def test_reload_in_loop(self):
        # a: r loaded before the loop; w: r reloaded in the loop's body, which stores r afterwards (the back edge brings the store to the next iteration's reload):
        # no store between them in the program's order, but w differs from a from the second iteration on, so their shuffles are not shared
        body = '''OpBranch %pre
%pre = OpLabel
%a = OpLoad %uint %r
%pa = OpIAdd %uint %a %c32
OpBranch %hdr
%hdr = OpLabel
OpLoopMerge %merge %cont None
OpBranch %body
%body = OpLabel
%w = OpLoad %uint %r
%pw = OpIAdd %uint %w %c32
%s1 = OpGroupNonUniformShuffle %uint %sg %pa %c5
%s2 = OpGroupNonUniformShuffle %uint %sg %pw %c5
%x = OpBitwiseXor %uint %s1 %s2
OpStore %out %x
%w1 = OpIAdd %uint %w %c1
OpStore %r %w1
OpBranch %cont
%cont = OpLabel
%lc = OpULessThan %bool %w1 %c100
OpBranchConditional %lc %hdr %merge
%merge = OpLabel'''
        self.run_pass(body, (2, 0))

    def test_keep(self):
        # keys (a, 5), (a, 6), (a, 5) at +32, +32, +64: the third repeats the first unless a keep of 1 dropped it for the second
        body = '''%a0 = OpLoad %uint %r
%p0 = OpIAdd %uint %a0 %c32
%s0 = OpGroupNonUniformShuffle %uint %sg %p0 %c5
%s1 = OpGroupNonUniformShuffle %uint %sg %p0 %c6
%p2 = OpIAdd %uint %a0 %c64
%s2 = OpGroupNonUniformShuffle %uint %sg %p2 %c5
%x0 = OpBitwiseXor %uint %s0 %s1
%x = OpBitwiseXor %uint %x0 %s2
OpStore %out %x'''
        for keep, want in ((None, (3, 1)), (2, (3, 1)), (1, (3, 0))):
            with self.subTest(keep=keep): self.run_pass(body, want, keep)


@unittest.skipUnless(shutil.which('glslangValidator') and shutil.which('xcrun') and shutil.which('clang') and SPIRV_CROSS.exists(), 'needs glslang, Xcode and spirv-cross')
class ShuffleCseOnGpu(unittest.TestCase):
    def run_module(self, d, name, data):
        (d / f'{name}.spv').write_bytes(data)
        subprocess.run([str(SPIRV_CROSS), str(d / f'{name}.spv'), '--msl', '--msl-version', '20300', '--msl-decoration-binding', '--rename-entry-point', 'main', 'check', 'comp',
                        '--output', str(d / f'{name}.metal')], check=True)
        subprocess.run(['xcrun', '-sdk', 'macosx', 'metal', '-c', '-O1', str(d / f'{name}.metal'), '-o', str(d / f'{name}.air')], check=True)
        subprocess.run(['xcrun', '-sdk', 'macosx', 'metallib', str(d / f'{name}.air'), '-o', str(d / f'{name}.metallib')], check=True)
        if not (d / 'run').exists():
            (d / 'run.m').write_text(RUNNER)
            subprocess.run(['clang', '-fobjc-arc', '-O1', str(d / 'run.m'), '-framework', 'Metal', '-framework', 'Foundation', '-o', str(d / 'run')], check=True)
        r = subprocess.run([str(d / 'run'), str(d / f'{name}.metallib')], capture_output=True)
        if r.returncode == 2: self.skipTest(r.stdout.decode().strip())
        self.assertEqual(r.returncode, 0, r.stdout[:200])
        return r.stdout

    def test_same_output(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); m = compile_module(d, SHADER)
            ref = self.run_module(d, 'native', m.data())
            self.assertEqual(spv.shuffle_cse(m), (11, 6))
            outs = {'cse': self.run_module(d, 'cse', m.data())}
            self.assertTrue(spv.shuffle_lds(m, 32768))
            outs['cse_lds'] = self.run_module(d, 'cse_lds', m.data())
            for name, out in outs.items():
                self.assertEqual(len(out), len(ref))
                diff = sum(1 for i in range(0, len(ref), 4) if ref[i:i + 4] != out[i:i + 4])
                self.assertEqual(diff, 0, f'{name}: {diff} of {len(ref) // 4} words differ')
            self.assertGreater(len(set(struct.unpack(f'<{len(ref) // 4}I', ref))), 1000)   # (the outputs carry data)


if __name__ == '__main__':
    unittest.main()
