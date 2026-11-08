"""The Vulkan library's vertex shaders reading the driver segment's base-instance word (c0 + 0x644) from the BaseInstance builtin (vk_android_spv.py base_instance): a
hand-written module in the translator's shape (vp_c0 a Uniform block of vec4[4096], the word read as row 100 component 1 and bit-cast to an integer, as Mario Kart World's
vegetation finds its instance records), the builtin, its capability and its interface entry added, the word's access chain gone, a builtin the module already has reused,
a load of the whole row 100 given the word as component 1, a read at a computed row counted as left, other stages left alone, and spirv-val of each result."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[0] / 'tools'
sys.path.insert(0, str(TOOLS))
import vk_android_spv as spv  # noqa: E402

HEAD = '''               OpCapability Shader
{caps}
               OpMemoryModel Logical GLSL450
               OpEntryPoint Vertex %main "main" %gl_InstanceIndex {iface} %out0 %pv
               OpName %vp_c0 "vp_c0"
               OpDecorate %arr ArrayStride 16
               OpDecorate %blk Block
               OpMemberDecorate %blk 0 Offset 0
               OpDecorate %vp_c0 DescriptorSet 0
               OpDecorate %vp_c0 Binding 1
               OpDecorate %gl_InstanceIndex BuiltIn InstanceIndex
{decos}
               OpDecorate %out0 Location 0
               OpDecorate %pvb Block
               OpMemberDecorate %pvb 0 BuiltIn Position
       %void = OpTypeVoid
         %fn = OpTypeFunction %void
      %float = OpTypeFloat 32
        %int = OpTypeInt 32 1
       %uint = OpTypeInt 32 0
        %v4f = OpTypeVector %float 4
  %uint_4096 = OpConstant %uint 4096
        %arr = OpTypeArray %v4f %uint_4096
        %blk = OpTypeStruct %arr
      %p_blk = OpTypePointer Uniform %blk
      %vp_c0 = OpVariable %p_blk Uniform
       %p_uf = OpTypePointer Uniform %float
      %p_uv4 = OpTypePointer Uniform %v4f
       %p_ii = OpTypePointer Input %int
%gl_InstanceIndex = OpVariable %p_ii Input
{vars}
      %p_ov4 = OpTypePointer Output %v4f
       %out0 = OpVariable %p_ov4 Output
        %pvb = OpTypeStruct %v4f
      %p_pvb = OpTypePointer Output %pvb
         %pv = OpVariable %p_pvb Output
      %int_0 = OpConstant %int 0
      %int_1 = OpConstant %int 1
     %int_17 = OpConstant %int 17
    %int_100 = OpConstant %int 100
     %int_80 = OpConstant %int 80
       %main = OpFunction %void None %fn
          %l = OpLabel
         %ii = OpLoad %int %gl_InstanceIndex
{body}
         %pp = OpAccessChain %p_ov4 %pv %int_0
               OpStore %pp %o
               OpStore %out0 %o
               OpReturn
               OpFunctionEnd
'''

# the translator's shape: (InstanceIndex [- BaseInstance] + c0[100].y) * 80, the word read as a float and bit-cast
WORD = '''         %ac = OpAccessChain %p_uf %vp_c0 %int_0 %int_100 %int_1
         %bw = OpLoad %float %ac
         %bi = OpBitcast %int %bw
        %rec = OpIAdd %int %ii %bi
          %r = OpIMul %int %rec %int_80
          %f = OpConvertSToF %float %r
        %ac2 = OpAccessChain %p_uv4 %vp_c0 %int_0 %int_17
        %row = OpLoad %v4f %ac2
          %o = OpVectorTimesScalar %v4f %row %f'''
PLAIN = HEAD.format(caps='', iface='', decos='', vars='', body=WORD)

# a module that has BaseInstance already (Ryujinx's InstanceIndex - BaseInstance), a load of the whole row 100, and a read at a computed row
ROW = HEAD.format(caps='               OpCapability DrawParameters', iface='%gl_BaseInstance',
                  decos='               OpDecorate %gl_BaseInstance BuiltIn BaseInstance', vars='%gl_BaseInstance = OpVariable %p_ii Input', body='''
         %bb = OpLoad %int %gl_BaseInstance
         %id = OpISub %int %ii %bb
        %ac1 = OpAccessChain %p_uv4 %vp_c0 %int_0 %int_100
        %r100 = OpLoad %v4f %ac1
         %bw = OpCompositeExtract %float %r100 1
         %bi = OpBitcast %int %bw
        %rec = OpIAdd %int %id %bi
          %r = OpIMul %int %rec %int_80
          %f = OpConvertSToF %float %r
        %ac3 = OpAccessChain %p_uf %vp_c0 %int_0 %id %int_1
         %dw = OpLoad %float %ac3
         %f2 = OpFAdd %float %f %dw
        %ac2 = OpAccessChain %p_uv4 %vp_c0 %int_0 %int_17
        %row = OpLoad %v4f %ac2
          %o = OpVectorTimesScalar %v4f %row %f2''')


def tool(name): return shutil.which(name)


@unittest.skipUnless(tool('spirv-as') and tool('spirv-val') and tool('spirv-dis'), 'needs SPIRV-Tools (spirv-as, spirv-val, spirv-dis)')
class BaseInstance(unittest.TestCase):
    def build(self, d, text):
        (d / 'a.spvasm').write_text(text)
        r = subprocess.run(['spirv-as', '--target-env', 'vulkan1.1', str(d / 'a.spvasm'), '-o', str(d / 'a.spv')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return spv.Module((d / 'a.spv').read_bytes())

    def check(self, d, m):
        (d / 'r.spv').write_bytes(m.data())
        r = subprocess.run(['spirv-val', '--target-env', 'vulkan1.3', str(d / 'r.spv')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return subprocess.run(['spirv-dis', '--raw-id', str(d / 'r.spv')], capture_output=True, text=True, check=True).stdout

    def c0(self, m): return next(v for v, n in m.names.items() if n == 'vp_c0')

    def builtin(self, m):
        v, member = m.builtin_var(spv.SC_INPUT, spv.BUILTIN_BASE_INSTANCE)
        self.assertIsNotNone(v); self.assertIsNone(member)
        return v

    def test_word(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t); m = self.build(d, PLAIN); c0 = self.c0(m)
            self.assertIn(0x644, spv.block_rows(m, c0)[0])
            self.assertNotIn(spv.CAP_DRAW_PARAMETERS, m.caps)
            self.assertEqual(spv.base_instance(m, c0), (1, 0))
            v = self.builtin(m)
            self.assertIn(v, m.interface())
            self.assertIn(spv.CAP_DRAW_PARAMETERS, m.caps)
            rows, dyn = spv.block_rows(m, c0)
            self.assertEqual((rows, dyn), ([17 * 16], False))   # the word's chain is gone, row 17 stays
            loads = {x[2] for x in m.ins if x[0] & 0xffff == spv.OP_LOAD and x[3] == v}
            casts = [x for x in m.ins if x[0] & 0xffff == spv.OP_BITCAST and x[3] in loads]
            self.assertEqual(len(casts), 1); self.assertEqual(m.op(casts[0][1]), spv.OP_TYPE_FLOAT)   # the load's float, from BaseInstance's bits
            self.check(d, m)

    def test_row_existing_builtin(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t); m = self.build(d, ROW); c0 = self.c0(m)
            v0 = self.builtin(m); n_vars = len(m.vars); n_caps = len(m.caps)
            self.assertEqual(spv.base_instance(m, c0), (1, 1))   # the row load rewritten; the computed row left (counted)
            self.assertEqual(self.builtin(m), v0); self.assertEqual(len(m.vars), n_vars); self.assertEqual(len(m.caps), n_caps)
            ins = [x for x in m.ins if x[0] & 0xffff == spv.OP_COMPOSITE_INSERT]
            self.assertEqual(len(ins), 1); self.assertEqual(ins[0][5:], [1])   # component 1 of the row
            self.assertTrue(spv.block_rows(m, c0)[1])   # (the computed read stays, for the build's red line)
            self.check(d, m)

    def test_other_stage(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t); m = self.build(d, PLAIN); before = m.data()
            m.entry[1] = 4   # as a pixel shader: no BaseInstance there
            self.assertEqual(spv.base_instance(m, self.c0(m)), (0, 0))
            m.entry[1] = 0
            self.assertEqual(m.data(), before)


if __name__ == '__main__':
    unittest.main()
