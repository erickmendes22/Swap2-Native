"""Diagnostics must execute exactly the original pass end, irrespective of flags."""
from pathlib import Path
import subprocess,tempfile,shutil,unittest
ROOT=Path(__file__).resolve().parents[4]
class CaveObserver(unittest.TestCase):
 def test_production_observer_never_changes_the_original_pass_end(self):
  text=(ROOT/'dm/gfx/vk_android/vka_draw.c').read_text();a=text.index('void vka_rp_cave_end(void)');body=text[a:text.index('\nvoid vka_rp_end(void)',a)]
  code=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define VK_FORMAT_UNDEFINED 0
static struct{unsigned ncolor;int cf[8],cave_cwrite,cave_dwrite,swrite;}R;
static struct{int n;}PC;
static uint64_t g_cave_original_splits,g_cave_unused_color,g_cave_depth_readonly;
static int uploads,ends;
static int vka_ub_active(void){return uploads;}
static void vka_rp_end(void){ends++;}
'''+body+r'''
int main(void){for(unsigned colors=0;colors<5;colors++)for(int c=0;c<2;c++)for(int d=0;d<2;d++)for(int s=0;s<2;s++)for(PC.n=0;PC.n<2;PC.n++)for(uploads=0;uploads<2;uploads++){
 R=(typeof(R)){.ncolor=colors,.cave_cwrite=c,.cave_dwrite=d,.swrite=s};for(unsigned i=0;i<colors;i++)R.cf[i]=97;
 int before=ends;uint64_t split=g_cave_original_splits,unused=g_cave_unused_color,readonly=g_cave_depth_readonly;
 vka_rp_cave_end();if(ends!=before+1||g_cave_original_splits!=split+1||g_cave_unused_color-unused!=(uint64_t)(colors&&!c&&!s&&!PC.n&&!uploads)||g_cave_depth_readonly-readonly!=(uint64_t)!d)abort();
}puts("160 observer states: original physical pass end always executes once");return 0;}
'''
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'test.c';exe=Path(tmp)/'test';p.write_text(code)
   r=subprocess.run([shutil.which('cc'),'-Wall','-Wextra','-Werror','-fsanitize=undefined',str(p),'-o',str(exe)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(exe)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
  replay=(ROOT/'dm/gfx/vk_android/vka_exec.c').read_text()
  self.assertNotIn('g_oq_visible',replay)
  self.assertNotIn('vka_rp_cave_sync()',replay)
if __name__=='__main__':unittest.main()
