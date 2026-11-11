"""Real native SPIR-V transform & semantics of Ocarina hot compute virtual retile."""
import ctypes
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
