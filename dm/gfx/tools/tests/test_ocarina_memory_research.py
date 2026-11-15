"""Research-only current-helper/page-index Vulkan and barrier proofs; never an APK."""
from pathlib import Path
import json,os,re,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[4]
D=ROOT/'dm/gfx/research/ocarina_memory'
from dm.gfx.research.ocarina_memory.shaders import source

class Research(unittest.TestCase):
 def compile(self,src,exe,*extra):
  p=subprocess.run(['cc','-O2','-Wall','-Wextra','-I',str(D),str(src),*extra,'-o',str(exe)],capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr)
 def test_exhaustive_barrier_policy(self):
  with tempfile.TemporaryDirectory()as tmp:
   exe=Path(tmp)/'gbar';self.compile(D/'gbar_exhaustive.c',exe)
   p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=120)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);print(p.stdout)
 def test_random_page_index_generations(self):
  with tempfile.TemporaryDirectory()as tmp:
   exe=Path(tmp)/'pidx';self.compile(D/'pidx_random.c',exe)
   for gran in (65536,4096,1):
    for seed in (1,2,3):
     p=subprocess.run([str(exe),'500',str(seed),str(gran)],capture_output=True,text=True,timeout=120)
     self.assertEqual(p.returncode,0,p.stdout+p.stderr)
   print('4500 index update steps and9000000 address lookups exact')
 def test_index_generation_ownership_and_memory_cap(self):
  with tempfile.TemporaryDirectory()as tmp:
   exe=Path(tmp)/'generations';self.compile(D/'index_generation_test.c',exe)
   p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=60)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);print(p.stdout)
 @unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','software Vulkan fixture explicitly enabled')
 def test_current8192_helper_against_page_index_and_cache(self):
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp);exe=d/'run';self.compile(D/'pidx_gpu.c',exe,'-ldl')
   rows=[]
   for full in (False,True):
    for warm,locality in ((False,'mixed'),(True,'mixed'),(True,'repeated_pool')):
     reference=None
     for mode in ('baseline','page','hybrid'):
      spv=d/(mode+'.spv');p=spv.with_suffix('.comp');p.write_text(source(mode,warm,locality=locality))
      c=subprocess.run(['glslangValidator','-V','--target-env','vulkan1.3','-o',str(spv),str(p)],capture_output=True,text=True)
      self.assertEqual(c.returncode,0,c.stdout+c.stderr)
      subprocess.run(['spirv-val','--target-env','vulkan1.3',str(spv)],check=True)
      r=subprocess.run([str(exe),str(spv),*(['full']if full else[])],capture_output=True,text=True,timeout=120)
      self.assertEqual(r.returncode,0,r.stdout+r.stderr)
      self.assertNotRegex(r.stdout+r.stderr,r'Validation Error|SYNC-HAZARD|VUID-')
      semantic='\n'.join(l for l in r.stdout.splitlines()if not l.startswith('WORK '))
      if reference is None:reference=semantic
      self.assertEqual(semantic,reference,(mode,full,warm))
      work=dict((k,int(v))for k,v in re.findall(r'(cache_hits|searches|search_probes|index_reads)=(\d+)',r.stdout))
      rows.append(dict(mode=mode,full=full,warm=warm,locality=locality,**work))
     # Negative control: corrupt loaded values. The semantic comparison must catch it.
     p=d/'bad.comp';spv=d/'bad.spv';p.write_text(source('hybrid',warm,negative=True,locality=locality))
     subprocess.run(['glslangValidator','-V','--target-env','vulkan1.3','-o',str(spv),str(p)],check=True,capture_output=True)
     r=subprocess.run([str(exe),str(spv),*(['full']if full else[])],capture_output=True,text=True,timeout=120)
     self.assertEqual(r.returncode,0,r.stdout+r.stderr)
     semantic='\n'.join(l for l in r.stdout.splitlines()if not l.startswith('WORK '))
     self.assertNotEqual(semantic,reference,'corrupt-load negative control escaped')
   print(json.dumps(rows,indent=2))
   out=os.getenv('RESEARCH_RESULTS')
   if out:Path(out).write_text(json.dumps(rows,indent=2)+'\n')
 @unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','software Vulkan fixture explicitly enabled')
 def test_barriers_storage_transfer_indirect_querycopy_and_negative_control(self):
  from dm.gfx.tools.tests.test_depth_pass_optimizations import function
  VK=ROOT/'dm/gfx/vk_android';tex=(VK/'vka_tex.c').read_text()
  with tempfile.TemporaryDirectory()as tmp:
   d=Path(tmp)
   (d/'sync_barriers.inc').write_text('\n'.join(function(tex,'void '+n+'(')for n in ['vka_barrier_at','vka_transfer_write_barrier_at','vka_compute_write_barrier_at']))
   from dm.gfx.tools.tests.test_selective_transfer_compute_gpu import COMP
   comp=d/'test.comp';spv=d/'test.spv';comp.write_text(COMP)
   subprocess.run(['glslangValidator','-V','--target-env','vulkan1.1','-o',str(spv),str(comp)],check=True,capture_output=True)
   for broken in (False,True):
    header=(D/'gbar_reference.h').read_text()
    if broken:header=header.replace('r = VKGB_B_SETTLE;', 'r = VKGB_B_NONE;')
    (d/'gbar.h').write_text(header)
    policy='#include "gbar.h"\nstatic vkgb G;static vkgb_stats GS;\n'+(D/'gbar_record.inc').read_text()+r'''
static void before_work(VkCommandBuffer cb,int kind){int ind,b=vkgb_cmd(&G,kind,&ind,&GS);if(b)rec(cb,b,ind);}
static void boost_transfer_barrier(VkCommandBuffer cb){vka_barrier(cb);before_work(cb,VKGB_C_FULL);}
static void dispatch_argument_barrier(VkCommandBuffer cb){vka_barrier(cb);before_work(cb,VKGB_C_FULL);}
static void dispatch_write_barrier(VkCommandBuffer cb,int spill,int indirect,uint64_t key){(void)spill;(void)indirect;(void)key;if(!vkgb_game(&G,0,opt,&GS)){vka_barrier(cb);before_work(cb,VKGB_C_FULL);}}
'''
    (d/'sync_policies.inc').write_text(policy)
    exe=d/'barriers'
    self.compile(D/'gbar_gpu.c',exe,'-DVKA_NDSR_PURE','-I',str(d),'-I',str(VK),'-I',str(VK/'selftest'),str(VK/'vka_ndsr.c'),'-ldl','-lm')
    env=dict(os.environ,SYNC_COMP=str(spv))
    if os.getenv('RESEARCH_SYNC_NEW')=='1':
     env.pop('VK_LAYER_ENABLES',None);env['VK_LAYER_VALIDATE_SYNC']='1'
    else:env['VK_LAYER_ENABLES']='VK_VALIDATION_FEATURE_ENABLE_SYNCHRONIZATION_VALIDATION_EXT'
    run=subprocess.run([str(exe)],capture_output=True,text=True,env=env,timeout=120)
    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
    if broken:self.assertIn('SYNC-HAZARD',run.stdout+run.stderr)
    else:
     self.assertNotRegex(run.stdout+run.stderr,r'Validation Error|SYNC-HAZARD|VUID-')
     self.assertEqual(run.stdout.count('4096 bytes exact'),32)
     print(run.stdout)
if __name__=='__main__':unittest.main()
