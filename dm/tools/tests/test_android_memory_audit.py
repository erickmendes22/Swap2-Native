"""Verify package selection, physical-memory grouping, and denied-data handling."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
SCRIPT=ROOT/'android/tools/memory-audit.sh'

class AndroidMemoryAudit(unittest.TestCase):
 def test_grouping_subprocesses_and_unavailable_data(self):
  with tempfile.TemporaryDirectory() as td:
   d=Path(td);proc=d/'proc';sys=d/'sys';bin=d/'bin';bin.mkdir();proc.mkdir();sys.mkdir()
   (proc/'meminfo').write_text('MemTotal: 16000000 kB\nMemAvailable: 2000000 kB\n')
   processes=d/'ps';processes.write_text('PID ARGS\n101 com.swap2native.ootv11ios\n102 com.swap2native.ootv11ios:game\n103 dev.bananative.android:game\n104 com.swap2native.ootv11ios.evil\n105 unrelated.app\n')
   smaps='''1000-2000 rw-s 00000000 00:01 1 /dmabuf:driver
Rss: 64 kB
Pss: 32 kB
Private_Dirty: 0 kB
SwapPss: 0 kB
2000-3000 r--s 00000000 00:01 2 /a/shaders/v-test/dmsh_vk.lib
Rss: 64 kB
Pss: 48 kB
Private_Dirty: 0 kB
SwapPss: 0 kB
3000-4000 rw-p 00000000 00:00 0 [anon:nxnative guest]
Rss: 8192 kB
Pss: 8192 kB
Private_Dirty: 8192 kB
SwapPss: 4096 kB
'''
   for pid in (101,102,103):
    p=proc/str(pid);p.mkdir();(p/'status').write_text(f'Name:\tgame\nPid:\t{pid}\nVmRSS:\t8320 kB\n')
    if pid!=103:
     (p/'smaps').write_text(smaps);(p/'smaps_rollup').write_text('Rss: 8320 kB\nPss: 8272 kB\nSwapPss: 4096 kB\n')
   (bin/'dumpsys').write_text('#!/bin/sh\nprintf "DUMPSYS_PID=%s\\n" "$5"\n');(bin/'dumpsys').chmod(0o755)
   env=dict(os.environ,SWAP_AUDIT_PROC_ROOT=str(proc),SWAP_AUDIT_SYS_ROOT=str(sys),SWAP_AUDIT_PS_LIST_FILE=str(processes),PATH=str(bin)+os.pathsep+os.environ['PATH'])
   r=subprocess.run(['sh',str(SCRIPT),'-'],env=env,text=True,capture_output=True)
   self.assertEqual(r.returncode,0,r.stderr);s=r.stdout
   self.assertIn('=== PROCESS 102 com.swap2native.ootv11ios:game ===',s)
   self.assertIn('=== PROCESS 103 dev.bananative.android:game ===',s)
   self.assertNotIn('PROCESS 104',s);self.assertNotIn('unrelated.app',s)
   self.assertIn('          64           32            0            0        1 GPU mappings',s)
   self.assertIn('          64           48            0            0        1 translated shader libraries',s)
   self.assertIn('        8192         8192         8192         4096        1 guest named memory',s)
   self.assertIn('UNAVAILABLE: smaps (root may be required)',s)
   self.assertIn('DUMPSYS_PID=102',s)
   processes.write_text('PID ARGS\n104 unrelated.app\n')
   r=subprocess.run(['sh',str(SCRIPT),'-'],env=env,text=True,capture_output=True)
   self.assertEqual(r.returncode,2);self.assertIn('neither emulator',r.stdout)

 def test_shell_syntax_and_no_mutation_commands(self):
  subprocess.run(['sh','-n',str(SCRIPT)],check=True)
  s=SCRIPT.read_text()
  for forbidden in ('am force-stop','kill -','drop_caches','setprop ','ctl.txt','rm -'):
   self.assertNotIn(forbidden,s)
if __name__=='__main__':unittest.main()
