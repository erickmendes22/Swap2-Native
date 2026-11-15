"""Real physical memory, including the existing guest storage and CPU aliases."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
def block(source,start):
 a=source.index(start);b=source.index('{',a);d=1;i=b+1
 while d:d+=(source[i]=='{')-(source[i]=='}');i+=1
 return source[a:i]

@unittest.skipUnless(Path('/proc/self/smaps_rollup').exists(),'Linux PSS accounting required')
class PoolMemoryAccounting(unittest.TestCase):
 def test_driver_bytes_do_not_prove_physical_ram_saving(self):
  source=(ROOT/'dm/gfx/vk_android/vka_mem.c').read_text()
  copy=block(source,'static void copy_readable(')
  pos=source.index('        copy_readable(p, lo, pr, npr);')
  replacement=block(source[pos:],'if (s.fd_alias) {')
  with tempfile.TemporaryDirectory() as td:
   d=Path(td);(d/'pool_copy.inc').write_text(copy);(d/'pool_map.inc').write_text(replacement)
   build=subprocess.run([shutil.which('cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror','-I',str(d),str(ROOT/'dm/host/tests/t_android_pool_memory_accounting.c'),'-o',str(d/'test')],capture_output=True,text=True)
   self.assertEqual(build.returncode,0,build.stderr)
   results={}
   for stride in (1,4):
    for defer in (0,1):
     run=subprocess.run([str(d/'test'),str(defer),str(stride)],capture_output=True,text=True,timeout=30)
     self.assertEqual(run.returncode,0,run.stdout+run.stderr)
     mode,step,gpu,rss,pss,checksum=map(int,run.stdout.strip().split(','));results[defer,stride]=(gpu,rss,pss,checksum)
   for stride in (1,4):
    old,new=results[0,stride],results[1,stride]
    self.assertEqual(old[0],65536);self.assertEqual(new[0],0)
    self.assertEqual(old[3],new[3],'guest shader bytes changed')
   old,new=results[0,1],results[1,1]
   # Fully resident CPU storage remains: physical RAM is approximately equal,
   # despite 64 MiB less counted as driver allocations. RSS double-counts aliases.
   self.assertLess(abs(old[2]-new[2]),4096,results)
   self.assertGreater(old[1]-new[1],56000,results)
   # Savings are possible for unpopulated guest pages, but depend on workload.
   old,new=results[0,4],results[1,4]
   self.assertGreater(old[2]-new[2],40000,results)
   print('defer,stride: GPUcounter KiB / RSSdelta KiB / PSSdelta KiB')
   for case,row in results.items():print(case,row[:3])
if __name__=='__main__':unittest.main()
