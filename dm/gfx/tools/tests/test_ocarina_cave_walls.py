"""Execute production oq_report: exact query publication and opt-in split order."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]

class CaveWalls(unittest.TestCase):
    def test_production_report_preserves_results_and_only_splits_live_depth_queries(self):
        cc = shutil.which('cc')
        self.assertIsNotNone(cc)
        text = (ROOT / 'dm/gfx/vk_android/vka_exec.c').read_text()
        start = text.index('static int oq_report(')
        end = text.index('// Query availability', start)
        function = text[start:end]
        harness = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { uint32_t kind, mode, v, t; uint64_t ad, q0, q1; } pop;
static int g_oqs_rep, g_oqs_nores, g_oq_count, g_oq_fresh, g_oq_open;
static int g_oq_split_pass, g_cb, enabled, depth, inspect, splits;
static uint32_t g_oq_lost;
static uint64_t g_oq_head, g_oq_seg0, g_oq_lost_epoch_total, g_oq_last_report_head;
static char events[8]; static int n; static pop posted;
static int oq_on(void) { return enabled; }
static int vka_rp_has_depth(void) { inspect++; return depth; }
static void oq_close(void) { if (g_oq_open) { events[n++]='Q';g_oq_open=0; } }
static void post(pop p) { events[n++]='P'; posted=p; }
static void vka_rp_end(void) {
    if(g_oq_open || g_oq_seg0!=g_oq_head || g_oq_fresh || g_oq_lost) abort();
    events[n++]='E'; splits++;
}
'''
        main = r'''
int main(void) {
 for(int opt=0; opt<2; opt++) for(int on=0;on<2;on++)
 for(int count=0;count<2;count++) for(int cb=0;cb<2;cb++)
 for(int open=0;open<2;open++) for(int dep=0;dep<2;dep++) {
    g_oq_split_pass=opt;enabled=on;g_oq_count=count;g_cb=cb;
    g_oq_open=open;depth=dep;inspect=0;splits=0;n=0;memset(events,0,sizeof events);
    g_oq_fresh=1;g_oq_lost=3;g_oq_head=110;g_oq_seg0=100;
    g_oq_lost_epoch_total=7;g_oq_last_report_head=90;
    int result=oq_report(0x12340,7),live=on&&count&&cb;
    if(result!=live) abort();
    if(!live) { if(n||inspect||splits||g_oq_seg0!=100||g_oq_lost!=3) abort();continue; }
    const char *want=open?(opt&&dep?"QPE":"QP"):"P";
    if(strcmp(events,want)||splits!=(opt&&open&&dep)) abort();
    if(inspect!=(opt&&open)) abort(); // OFF adds zero pass inspections.
    if(posted.kind!=4||posted.mode!=1||posted.v!=3||posted.t!=7||
       posted.ad!=0x12340||posted.q0!=100||posted.q1!=110) abort();
    if(g_oq_lost_epoch_total!=10||g_oq_last_report_head!=110||g_oq_seg0!=110||g_oq_fresh||g_oq_lost) abort();
 }
 puts("64 production report paths: publication unchanged; end-query/post/end-pass ordered; OFF has zero pass inspections");
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'query.c'; exe=Path(tmp)/'query'
            src.write_text(harness+function+main)
            subprocess.run([cc,'-Wall','-Wextra','-Werror','-fsanitize=undefined',str(src),'-o',str(exe)],check=True,capture_output=True,text=True)
            result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
            self.assertIn('64 production report paths',result.stdout)

if __name__ == '__main__': unittest.main()
