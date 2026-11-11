"""Ocarina 0.1.6: exact intra-basic-block captured fragment shader ALU CSE."""
from pathlib import Path
import importlib.util
import unittest

R=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location("vk_android_spv",R/"dm/gfx/tools/vk_android_spv.py")
spv=importlib.util.module_from_spec(spec)
spec.loader.exec_module(spv)
BUILD=(R/"dm/gfx/tools/vk_android_build.py").read_text()

def inst(op,*args):return [((len(args)+1)<<16)|op,*args]
def shader(decorate=False):
    w=[spv.MAGIC,0x00010300,0,75,0]
    w+=inst(17,1)+inst(14,0,1)
    w+=inst(15,4,20,0x6e69616d,0)
    if decorate: w+=inst(71,32,42)
    w+=inst(19,1)+inst(33,2,1)+inst(22,3,32)
    w+=inst(43,3,4,0x3f800000)
    w+=inst(54,1,20,0,2)+inst(248,21)
    w+=inst(129,3,31,4,4)
    w+=inst(129,3,32,4,4)
    w+=inst(129,3,33,4,31)
    w+=inst(129,3,34,4,31)
    w+=inst(248,22)
    w+=inst(129,3,35,4,4)
    w+=inst(253)+inst(56)
    import struct
    return struct.pack("<%dI"%len(w),*w)

class AluCseTest(unittest.TestCase):
    def test_pure_repeat_uses_copy_and_preserves_ssa_identity(self):
        m=spv.Module(shader())
        self.assertEqual(spv.local_alu_cse(m),2)
        copies=[x for x in m.ins if (x[0]&0xffff)==spv.OP_COPY_OBJECT]
        self.assertEqual({tuple(x[1:]) for x in copies},
                         {(3,32,31),(3,34,33)})
        self.assertEqual(spv.local_alu_cse(m),0)
        self.assertEqual(spv.Module(m.data()).data(),m.data())
        self.assertEqual(m.header[3],75)

    def test_never_crosses_basic_blocks_and_never_folds_decorated(self):
        m=spv.Module(shader(True))
        self.assertEqual(spv.local_alu_cse(m),1)
        self.assertFalse(any((x[0]&0xffff)==spv.OP_COPY_OBJECT and x[2]==32
                             for x in m.ins))
        self.assertFalse(any((x[0]&0xffff)==spv.OP_COPY_OBJECT and x[2]==35
                             for x in m.ins))

    def test_scoped_to_real_captured_fragment_keys_and_before_validator(self):
        for key in ("1e4d2630d24846d0","00ce4088af2c8e12","5ad65c0eefd09c7f"):
            self.assertIn("'"+key+"'",BUILD)
        self.assertIn("spv.local_alu_cse(m)",BUILD)
        self.assertIn("'oot_alu_cse': oot_alu",BUILD)
        self.assertLess(BUILD.index("spv.local_alu_cse(m)"),
                        BUILD.index("mods = [(VK['MOD_BASE'], m.data())]"))
        self.assertLess(BUILD.index("spv.local_alu_cse(m)"),
                        BUILD.index("for variant, data in mods:"))
        self.assertIn("if err: return 'spirv-val failed'",BUILD)

if __name__=="__main__": unittest.main()
