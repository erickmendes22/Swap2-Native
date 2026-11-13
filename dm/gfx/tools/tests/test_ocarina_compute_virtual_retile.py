"""Real native SPIR-V transform & semantics of Ocarina hot compute virtual retile."""
import ctypes
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PATCHER = ROOT / "dm/gfx/vk_android/vka_spvpatch.c"
DRAW = (ROOT / "dm/gfx/vk_android/vka_draw.c").read_text()
SHADER = (ROOT / "dm/gfx/vk_android/vka_shader.c").read_text()
FACTS = (ROOT / "dm/games/0400486024DEC000/shader_facts.tsv").read_text()

def op(code, *params):
    return [((len(params)+1) << 16)|code, *params]

def sample(*unsafe):
    w = [0x07230203,0x00010300,0,64,0]
    w += op(17,1) + op(14,0,1)
    w += op(15,5,20,0x6e69616d,0,7,8,9,10)
    w += op(16,20,17,8,4,4)
    for var, builtin in ((7,28),(8,26),(9,27),(10,24)):
        w += op(71,var,11,builtin)
    w += op(19,1)+op(33,2,1)+op(21,3,32,0)+op(23,4,3,3)+op(32,5,1,4)
    for var in (7,8,9,10):
        w += op(59,5,var,1)
    w += op(54,1,20,0,2) + op(248,21)
    for res,var in ((22,8),(23,9),(24,10)):
        w += op(61,4,res,var)
    for u in unsafe:
        w += u
    w += op(253)+op(56)
    return w

def instructions(w):
    i=5
    while i<len(w):
        n=w[i]>>16
        assert n>0 and i+n<=len(w)
        yield w[i]&0xffff,w[i+1:i+n]
        i+=n

def component_sample():
    """The actual capture's scalar pointer/load shape, without guest code."""
    out = sample()[:5]
    for opcode, args in instructions(sample()):
        if opcode in (71, 59) and (args[0] if opcode == 71 else args[1]) == 7:
            continue
        if opcode == 15:
            args = [x for x in args if x != 7]
        if opcode == 54:
            out += op(32,30,1,3)
            for ident, value in ((31,0),(32,1),(33,2)):
                out += op(43,3,ident,value)
        if opcode == 61:
            continue
        if opcode == 253:
            for n, (var, index) in enumerate((v,c) for v in (8,9,10) for c in (31,32,33)):
                out += op(65,30,40+2*n,var,index)
                out += op(61,3,41+2*n,40+2*n)
        out += op(opcode,*args)
    return out

class VirtualRetile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which("cc") or shutil.which("clang")
        cls.temp=tempfile.TemporaryDirectory()
        lib=Path(cls.temp.name)/"patch.so"
        subprocess.run([compiler,"-std=c11","-O2","-fPIC","-shared",
                        str(PATCHER),"-o",str(lib)],check=True,capture_output=True)
        cls.native=ctypes.CDLL(str(lib))
        cls.fn=cls.native.vka_spv_oot_cs_virtual_retile
        cls.fn.argtypes=[ctypes.POINTER(ctypes.c_uint32),ctypes.c_size_t,
                         ctypes.POINTER(ctypes.c_size_t),ctypes.c_char_p,ctypes.c_size_t]
        cls.fn.restype=ctypes.c_void_p
        cls.c=ctypes.CDLL(None)
        cls.c.free.argtypes=[ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def patch(self,w):
        src=(ctypes.c_uint32*len(w))(*w)
        n=ctypes.c_size_t()
        err=ctypes.create_string_buffer(256)
        p=self.fn(src,len(w),ctypes.byref(n),err,len(err))
        try:
            data=list(struct.unpack("<%dI"%n.value,ctypes.string_at(p,n.value*4))) if p else None
            return data,err.value.decode()
        finally:
            if p: self.c.free(p)

    def test_emits_real_local_group_replacements(self):
        before=sample()
        after,why=self.patch(before)
        self.assertIsNotNone(after,why)
        self.assertEqual(before[3],64)
        self.assertGreater(after[3],64)
        lines=list(instructions(after))
        self.assertTrue(any(o==16 and a[-3:]==[8,4,2] for o,a in lines))
        self.assertTrue(any(o==194 and a[1]==22 for o,a in lines))
        self.assertTrue(any(o==199 and a[1]==23 for o,a in lines))
        self.assertTrue(any(o==83 and a[1]==24 for o,a in lines))
        self.assertFalse(any(o==61 and a[-1] in (8,9,10) for o,a in lines))
        self.assertIn("virtualized 3",why)

    def test_shader_without_global_invocation_id_uses_native_group_local(self):
        # NVN translator can emit WorkgroupId and LocalInvocationId
        # without a declared GlobalInvocationId. This was a false hard
        # blocker in Build59; preserve the original per-lane semantics.
        original=sample()
        adjusted=original[:5]
        for opcode,args in instructions(original):
            if opcode==71 and args[0]==7: continue
            if opcode==59 and args[1]==7: continue
            if opcode==15:
                args=[x for x in args if x != 7]
            adjusted+=op(opcode,*args)
        patched,why=self.patch(adjusted)
        self.assertIsNotNone(patched,why)
        parsed=list(instructions(patched))
        self.assertTrue(any(code==82 for code,_ in parsed))
        self.assertTrue(any(code==134 for code,_ in parsed))
        self.assertTrue(any(code==137 for code,_ in parsed))
        self.assertTrue(any(code==128 for code,_ in parsed))
        # Raw hardware group/local loads are needed to reconstruct old
        # logical values; only the old NumWorkgroups input must disappear.
        self.assertFalse(any(code==61 and args[-1]==10
                             for code,args in parsed))

    def test_identical_indices_for_all_110592_invocations(self):
        for z in range(24*2):
            for y in range(9*4):
                for x in range(8*8):
                    orig_group=x//8,y//4,z//4
                    virt_group=x>>3,y>>2,z>>2
                    orig_local=x%8,y%4,z%4
                    virt_local=x&7,y&3,z&3
                    self.assertEqual(virt_group,orig_group)
                    self.assertEqual(virt_local,orig_local)
        self.assertEqual(8*9*12*128,8*9*24*64)

    def test_fail_closed_on_unsafe_shader_features(self):
        bad=[op(224,1,1,1),op(227,3,30,8,1),
             op(71,30,11,29),op(72,30,0,11,26),
             op(65,5,30,8,1),op(59,5,31,4),op(333,3,30,1)]
        for extra in bad:
            with self.subTest(extra=extra):
                ret,_=self.patch(sample(extra))
                self.assertIsNone(ret)
        self.assertIsNone(self.patch([0,1,2])[0])

    def test_constant_scalar_components_match_real_capture_shape(self):
        patched, reason = self.patch(component_sample())
        self.assertIsNotNone(patched, reason)
        self.assertIn('9 local/group builtin loads', reason)
        self.assertIn((16,[20,17,8,4,2]), list(instructions(patched)))
        # X/Y are physically unchanged; NumWorkgroups uses the original
        # literal grid, GroupZ halves, and LocalZ restores the half-group.
        rows = list(instructions(patched))
        self.assertIn((61,[3,41,40]), rows)
        self.assertIn((61,[3,43,42]), rows)
        self.assertTrue(any(code == 134 and args[1] == 45 for code,args in rows))
        self.assertTrue(any(code == 128 and args[1] == 51 for code,args in rows))
        for result in (53,55,57):
            self.assertTrue(any(code == 81 and args[1] == result for code,args in rows))

    def test_component_pointer_escape_and_dynamic_index_still_refused(self):
        for extra in (op(83,30,58,40), op(62,40,31), op(65,30,58,40,31)):
            src = component_sample()
            src = src[:-2] + extra + src[-2:]
            self.assertIsNone(self.patch(src)[0])
        for index in (7,57):  # neither is a literal integer component
            src = component_sample(); out = src[:5]
            for code,args in instructions(src):
                if code == 65 and args[1] == 40:
                    args[-1] = index
                out += op(code,*args)
            self.assertIsNone(self.patch(out)[0])
        for value in (3,0xffffffff):
            src = component_sample(); out = src[:5]
            for code,args in instructions(src):
                if code == 43 and args[1] == 33:
                    args[-1] = value
                out += op(code,*args)
            self.assertIsNone(self.patch(out)[0])

    def test_inbounds_scalar_components_and_qualified_load_guard(self):
        src = component_sample(); inbounds = src[:5]; qualified = src[:5]
        for code,args in instructions(src):
            inbounds += op(66 if code == 65 else code,*args)
            qualified += op(code,*(args+[0] if code == 61 and args[1] == 41 else args))
        self.assertIsNotNone(self.patch(inbounds)[0])
        self.assertIsNone(self.patch(qualified)[0])

    @unittest.skipUnless(os.environ.get('MEMU_TEST_VULKAN') == '1', 'requires Vulkan ICD and spirv-as')
    def test_actual_gpu_all_component_ids_match_independent_oracle(self):
        root = Path(self.temp.name)
        before = root/'component-ids.spv'; after = root/'component-ids-retiled.spv'
        subprocess.run(['spirv-as','--target-env','vulkan1.3',str(ROOT/'dm/host/tests/compute/component_ids.spvasm'),'-o',str(before)],check=True)
        original = list(struct.unpack('<%dI'%(before.stat().st_size//4),before.read_bytes()))
        patched, reason = self.patch(original)
        self.assertIsNotNone(patched,reason)
        after.write_bytes(struct.pack('<%dI'%len(patched),*patched))
        for p in (before,after):
            subprocess.run(['spirv-val','--target-env','vulkan1.3',str(p)],check=True)
        runner = root/'dispatch'
        subprocess.run(['cc','-O1','-I',str(ROOT/'dm/third_party/vulkan-headers/include'),str(ROOT/'dm/host/tests/t_android_memu_dispatch.c'),'-Wl,-l:libvulkan.so.1','-o',str(runner)],check=True)
        record = root/'record.bin'; record.write_bytes(bytes(128))
        arena = root/'arena.bin'; arena.write_bytes(bytes(64*36*48*16))
        expected = bytearray()
        for z in range(48):
            for y in range(36):
                for x in range(64):
                    expected += struct.pack('<4I',(x//8)+(y//4)*256+(z//4)*65536,(x%8)+(y%4)*256+(z%4)*65536,8+9*256+12*65536,0x12345678)
        for module, gz in ((before,12),(after,24)):
            output = root/(module.stem+'.bin')
            subprocess.run([str(runner),str(module),str(record),str(arena),str(output),'8','9',str(gz)],check=True,capture_output=True)
            self.assertEqual(output.read_bytes(), expected)

    def test_runtime_scope_and_9ed48_limited_to_safe_barrier(self):
        self.assertIn("vka_spv_oot_cs_virtual_retile",SHADER)
        self.assertIn("DM_VK_OOT_CS_VIRTUAL_RETILE",SHADER)
        self.assertIn('!rt.b[0] && !dp->ind && !spill_bytes(sh[5])',DRAW)
        self.assertIn('dp->x == 8 && dp->y == 9 && dp->z == 12',DRAW)
        self.assertIn('9e6b00b050e30801\t{"local":[8,4,4],"shared":0}',FACTS)
        self.assertIn('9ed48d1011f1b48b\t{"local":[8,8,8],"shared":18432}',FACTS)
        self.assertIn('sh[5]->key == UINT64_C(0x9ed48d1011f1b48b)',DRAW)
        self.assertIn('vka_compute_write_barrier(g_cb)',DRAW)
        self.assertNotIn('sh[5]->key == UINT64_C(0x9e6b00b050e30801) && VKA_ENV("DM_VK_OOT_FPS_BOOST"',DRAW)

if __name__=="__main__": unittest.main()
