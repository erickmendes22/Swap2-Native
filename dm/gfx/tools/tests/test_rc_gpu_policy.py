"""Execute production report admission; no pending query may outlive its owner."""
import hashlib
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
VK = ROOT / 'dm/gfx/vk_android'


class RCGpuPolicy(unittest.TestCase):
    def test_actual_report_admission_and_boundaries(self):
        src = r'''
#include <assert.h>
#include <stdint.h>
#include "vka_rc_gpu_policy.h"
int main(void) {
 assert(vka_rc_gpu_range(3,1,0,0,12,13,10,20));
 assert(vka_rc_gpu_range(3,1,0,0,10,10,10,20));
 assert(!vka_rc_gpu_range(2,1,0,0,12,13,10,20));
 assert(!vka_rc_gpu_range(3,0,0,0,12,13,10,20));
 assert(!vka_rc_gpu_range(3,1,1,0,12,13,10,20));
 assert(!vka_rc_gpu_range(3,1,0,0,9,13,10,20));
 assert(!vka_rc_gpu_range(3,1,0,0,14,13,10,20));
 assert(!vka_rc_gpu_range(3,1,0,0,12,21,10,20));
 assert(vka_rc_gpu_range(3,1,0,0,100,356,100,1000));
 assert(!vka_rc_gpu_range(3,1,0,0,100,357,100,1000));
 assert(!vka_rc_gpu_range(3,1,0,0,UINT64_MAX-4,UINT64_MAX,0,UINT64_MAX-1));
 assert(!vka_rc_gpu_range(3,1,0,1,12,13,10,20));
 uint64_t seed=71;
 for (int i=0;i<100000;i++) {
  seed=seed*6364136223846793005ULL+1;
  uint64_t start=seed>>8, count=(seed&511), first=start-(seed&15);
  uint64_t end=start+count, head=start+((seed>>16)&511);
  int expected=end>=start && start>=first && end<=head && count<=256;
  assert(vka_rc_gpu_range(3,1,0,0,start,end,first,head)==expected);
 }
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'policy.c'; exe = p.with_suffix('')
            p.write_text(src)
            subprocess.run([shutil.which('cc'), '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I', str(VK), str(p), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_same_epoch_cumulative_query_delta_strict_current_submission(self):
        source = r"""
#include <assert.h>
#include <stdint.h>
#include "vka_rc_gpu_policy.h"
int main(void) {
    // Report A is nonfresh; B is nonfresh but their prefix cancels.
    assert(vka_rc_gpu_delta_range(3,3,8,8,0,0,0,0,90,95,50,100));
    assert(vka_rc_gpu_delta_range(3,3,8,8,0,0,22,22,90,90,50,100));
    // Any uncounted/lost query, stale ring entry, new reset, previous
    // submission, or too-long interval retains conservative CPU drawing.
    assert(!vka_rc_gpu_delta_range(2,3,8,8,0,0,0,0,90,95,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,9,0,0,0,0,90,95,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,1,0,0,0,90,95,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,0,1,0,0,90,95,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,0,0,0,1,90,95,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,0,0,0,0,49,95,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,0,0,0,0,90,89,50,100));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,0,0,0,0,90,101,50,100));
    assert(vka_rc_gpu_delta_range(3,3,8,8,0,0,0,0,90,346,50,1000));
    assert(!vka_rc_gpu_delta_range(3,3,8,8,0,0,0,0,90,347,50,1000));
    uint64_t seed=271;
    for (int i=0;i<100000;i++) {
        seed=seed*6364136223846793005ULL+1;
        uint64_t lo=seed>>16, range=(seed>>7)&511, hi=lo+range;
        int same=(seed&3)!=0, lost=(seed>>3)&1, stale=(seed>>8)&1;
        int expect=same && !lost && !stale && range<=256;
        assert(vka_rc_gpu_delta_range(3,3,19,19+!same,0,stale,
                                      0,lost,lo,hi,lo,hi) == expect);
    }
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"delta.c";exe=p.with_suffix("")
            p.write_text(source)
            subprocess.run([shutil.which("cc"),"-std=c11","-O2","-Wall",
                            "-Wextra","-Werror","-I",str(VK),str(p),"-o",
                            str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
        inc = (VK / "vka_rc_gpu.inc").read_text()
        self.assertIn("static int rc_gpu_report_pair(", inc)
        self.assertIn("vka_rc_gpu_delta_range(a->kind, b->kind,", inc)
        self.assertIn("!OQ.precise", inc)
        self.assertIn("a->oq_begin = first; a->oq_end = first; a->oq_lost = 0;", inc)
        self.assertIn("b->oq_begin = first; b->oq_lost = 0;", inc)
        self.assertIn("rc_gpu_report_pair(cond.addr, &jobs[n].a, &jobs[n].b)", inc)
        self.assertIn("rc_gpu_report_pair(cond.addr, &a, &b)", inc)

    def test_actual_copy_planner_deduplication_merge_and_ring_wrap(self):
        source = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "vka_rc_gpu_policy.h"
int main(void){
 vka_rc_gpu_plan p={0};uint32_t off;
 assert(vka_rc_gpu_plan_add(&p,3,5,256,&off)&&off==0&&p.copies==1);
 assert(vka_rc_gpu_plan_add(&p,5,7,256,&off)&&off==2&&p.copies==1&&p.copy[0].count==4);
 assert(vka_rc_gpu_plan_add(&p,3,5,256,&off)&&off==0&&p.total==4&&p.copies==1);
 assert(vka_rc_gpu_plan_add(&p,100,100,256,&off)&&p.total==4);
 memset(&p,0,sizeof p);
 assert(vka_rc_gpu_plan_add(&p,255,258,256,&off)&&p.copies==2&&p.total==3);
 assert(p.copy[0].first==255&&p.copy[0].count==1&&p.copy[1].first==0&&p.copy[1].count==2);
 assert(!vka_rc_gpu_plan_add(&p,8,7,256,&off));
 assert(!vka_rc_gpu_plan_add(&p,0,257,256,&off));
 assert(!vka_rc_gpu_plan_add(&p,0,2,1,&off));
 uint64_t seed=179;
 for(int round=0;round<1000;round++){
  memset(&p,0,sizeof p);uint32_t values[4096]={0};
  for(int i=0;i<128;i++){
   seed=seed*6364136223846793005ULL+1;
   uint64_t begin=(seed>>32)&65535;uint32_t count=(seed&15);
   if(!vka_rc_gpu_plan_add(&p,begin,begin+count,32768,&off))break;
   for(unsigned c=0;c<p.copies;c++)for(unsigned k=0;k<p.copy[c].count;k++)
    values[p.copy[c].offset+k]=p.copy[c].first+k;
   for(unsigned k=0;k<count;k++)assert(values[off+k]==(begin+k)%32768);
   uint32_t total=p.total,copies=p.copies;
   assert(vka_rc_gpu_plan_add(&p,begin,begin+count,32768,&off));
   assert(total==p.total&&copies==p.copies);
  }
 }
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'copies.c'; exe = p.with_suffix('')
            p.write_text(source)
            subprocess.run([shutil.which('cc'), '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I', str(VK), str(p), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_actual_collector_rejects_partial_and_unsafe_blocks(self):
        from dm.gfx.tools.tests.test_ocarina_mesh_native_hybrid import function
        text = (VK / 'vka_rc_gpu.inc').read_text()
        source = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "vka_rc_gpu_policy.h"
enum {OP_END,OP_JUMP,OP_CALL,OP_RENDER_COND,OP_DRAW,OP_DRAW_IDX,
      OP_BIND_PROGRAM,OP_SET_RT,OP_BARRIER,OP_CLEAR_COLOR,OP_REPORT_COUNTER,OP_UPDATE_UB};
enum {NVN_PRIM_MESH=256,NVN_DRAW_PRIMITIVE_LINE_LOOP=2,NVN_DRAW_PRIMITIVE_QUADS=7};
typedef struct {uint32_t op,size;}op_hdr;
typedef struct {int32_t mode,pad;uint64_t addr;}p_render_cond;
typedef struct {int prim,base_instance,mdi_cnt;}p_draw;
typedef p_draw p_draw_idx;
typedef struct {uint64_t serial;}prog_t;
typedef struct {const prog_t *bst[5];int tf_on,rast_discard,safe;}vka_dstate;
typedef struct {uint64_t oq_begin,oq_end;}rc_rep;
""" + text[text.index('typedef struct {'):text.index('static rc_gpu_job g_rc_jobs')] + r"""
static vka_dstate g_rc_scan;
static struct {vka_dstate d;}S;
static int g_memu_depth;
static const uint8_t *g_memu_caller[16];
static int rc_gpu_report(uint64_t a,rc_rep *r){r->oq_begin=1;r->oq_end=2;return a!=0xbad;}
static int rc_gpu_report_pair(uint64_t a,rc_rep *r,rc_rep *s){
 return rc_gpu_report(a,r)&&rc_gpu_report(a+16,s);
}
static int vka_rc_gpu_state_safe(const vka_dstate*d){return d->safe&&!d->tf_on&&!d->rast_discard;}
static const p_draw*draw_rec(const void*a,uint32_t n,p_draw*t){(void)n;(void)t;return a;}
static const p_draw_idx*draw_idx_rec(const void*a,uint32_t n,p_draw_idx*t){(void)n;(void)t;return a;}
static int overlap_state_record(uint32_t op){return op==OP_BIND_PROGRAM;}
static void vka_state_op(vka_dstate*d,uint32_t op,const void*a){if(op==OP_BIND_PROGRAM)memcpy(&d->safe,a,4);}
""" + 'static void ' + function(text,'rc_gpu_context_of') + '\nstatic int ' + function(text,'rc_gpu_collect') + r"""
typedef struct {op_hdr h;union{p_render_cond c;p_draw d;const uint8_t*p;int safe;}u;}record;
#define REC(op) (record){.h={op,sizeof(record)}}
static record cond(int mode){record r=REC(OP_RENDER_COND);r.u.c=(p_render_cond){mode,0,0x1000};return r;}
static record draw(void){record r=REC(OP_DRAW);r.u.d=(p_draw){3,0,0};return r;}
int main(void){
 rc_gpu_job jobs[128];S.d.safe=1;
 record a[]={cond(1),draw(),cond(2),REC(OP_END)};
 assert(rc_gpu_collect((const uint8_t*)a,jobs)==1&&jobs[0].p==(const uint8_t*)&a[0]);
 // A clear/report/inline update makes the whole current block ineligible.
 const uint32_t bad[]={OP_CLEAR_COLOR,OP_REPORT_COUNTER,OP_UPDATE_UB};
 for(unsigned i=0;i<3;i++){
  a[2]=REC(bad[i]);assert(rc_gpu_collect((const uint8_t*)a,jobs)==0);
 }
 record b[]={cond(1),draw(),cond(0),draw(),REC(OP_CLEAR_COLOR),REC(OP_END)};
 assert(rc_gpu_collect((const uint8_t*)b,jobs)==1); // first FULL block only
 record c[]={cond(1),draw(),REC(OP_BIND_PROGRAM),draw(),cond(2),REC(OP_END)};
 c[2].u.safe=0;assert(rc_gpu_collect((const uint8_t*)c,jobs)==0); // no partial predication
 c[2].u.safe=1;assert(rc_gpu_collect((const uint8_t*)c,jobs)==1);
 record d[]={cond(1),draw(),cond(2),REC(OP_END)};
 d[1].u.d.prim=NVN_PRIM_MESH;assert(!rc_gpu_collect((const uint8_t*)d,jobs));
 d[1].u.d.prim=NVN_DRAW_PRIMITIVE_QUADS;assert(!rc_gpu_collect((const uint8_t*)d,jobs));
 d[1]=draw();d[1].u.d.base_instance=1;assert(!rc_gpu_collect((const uint8_t*)d,jobs));
 d[1]=draw();d[1].u.d.mdi_cnt=1;assert(!rc_gpu_collect((const uint8_t*)d,jobs));
 d[1]=draw();d[1].h.op=OP_DRAW_IDX;assert(rc_gpu_collect((const uint8_t*)d,jobs)==1);
 S.d.tf_on=1;assert(!rc_gpu_collect((const uint8_t*)d,jobs));S.d.tf_on=0;
 d[0].u.c.addr=0xbad;assert(!rc_gpu_collect((const uint8_t*)d,jobs));
 // Nested-list return is part of a block, not its end.
 record child[]={draw(),REC(OP_END)};
 record parent[]={cond(1),REC(OP_CALL),draw(),cond(2),REC(OP_END)};
 parent[1].u.p=(const uint8_t*)child;
 assert(rc_gpu_collect((const uint8_t*)parent,jobs)==1);
 record inner[]={cond(1),draw(),REC(OP_END)};
 g_memu_depth=1;g_memu_caller[0]=(const uint8_t*)&parent[2];
 assert(rc_gpu_collect((const uint8_t*)inner,jobs)==1&&jobs[0].context.depth==1);
 // The same child record under a DIFFERENT caller/state cannot reuse a cached proof.
 rc_gpu_context first=jobs[0].context, second;
 const uint8_t *different[1]={(const uint8_t*)&parent[3]};
 rc_gpu_context_of(&second,&S.d,1,different);assert(memcmp(&first,&second,sizeof first));
 rc_gpu_context_of(&second,&S.d,1,g_memu_caller);assert(!memcmp(&first,&second,sizeof first));
 prog_t p={1};S.d.bst[0]=&p;rc_gpu_context_of(&first,&S.d,1,g_memu_caller);
 p.serial++;rc_gpu_context_of(&second,&S.d,1,g_memu_caller);assert(memcmp(&first,&second,sizeof first));
 g_memu_depth=17;assert(!rc_gpu_collect((const uint8_t*)inner,jobs));g_memu_depth=0;
 inner[1].h.size=0;assert(!rc_gpu_collect((const uint8_t*)inner,jobs));
 record many[259];
 for(int i=0;i<129;i++){many[2*i]=cond(i&1);many[2*i+1]=draw();}
 many[258]=REC(OP_END);assert(rc_gpu_collect((const uint8_t*)many,jobs)==128);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'collect.c'; exe = p.with_suffix('')
            p.write_text(source)
            subprocess.run([shutil.which('cc'), '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-I', str(VK), str(p), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    def test_checked_in_helper_has_current_source_and_valid_spirv(self):
        text = (VK / 'vka_rc_gpu_spv.h').read_text()
        digest = hashlib.sha256((VK / 'rc/visibility.comp').read_bytes()).hexdigest()
        self.assertIn('source SHA256 ' + digest, text)
        words = [int(x, 16) for x in re.findall(r'0x[0-9a-f]{8}', text)]
        self.assertEqual(words[0], 0x07230203)
        validator = shutil.which('spirv-val')
        if validator:
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / 'helper.spv'
                p.write_bytes(struct.pack('<' + 'I' * len(words), *words))
                subprocess.run([validator, '--target-env', 'vulkan1.1', str(p)], check=True)

@unittest.skipUnless(__import__('os').getenv('MEMU_TEST_VULKAN') == '1', 'real Vulkan ICD required')
class RCGpuArithmetic(unittest.TestCase):
    def test_actual_checked_in_helper_64bit_counts_and_uncertainty(self):
        import os
        import random
        rng = random.Random(179)
        mask = (1 << 64) - 1
        values = [0, 1, 2, 0xffffffff, 1 << 32, 1 << 63, mask]
        queries = values + [rng.getrandbits(64) if i % 3 else 0 for i in range(64)]
        jobs, expected = [], []
        def append(firsta, counta, losta, firstb, countb, lostb, mode, precise):
            a = queries[firsta:firsta+counta]; b = queries[firstb:firstb+countb]
            jobs.extend([firsta, counta, losta & 0xffffffff, losta >> 32,
                         firstb, countb, lostb & 0xffffffff, lostb >> 32, mode, precise, 0, 0])
            if precise:
                equal = ((sum(a) + losta) & mask) == ((sum(b) + lostb) & mask)
            elif not any(a) and not any(b):
                equal = losta == lostb
            else:
                az = not any(a) and not losta; bz = not any(b) and not lostb
                if not az and not bz:
                    expected.append(1); return  # both positive: numerical comparison is unknown
                equal = az and bz
            expected.append(int(equal if mode == 0 else not equal))
        for precise in (0, 1):
            for mode in (0, 1):
                for a in range(7):
                    for b in range(7):
                        append(a, 1, 0, b, 1, 0, mode, precise)
                append(1, 1, mask, 0, 1, 0, mode, precise)  #64-bit carry/wrap
                append(0, 0, 1 << 32, 0, 0, 0, mode, precise)  # equal low words, different high
                append(0, 0, mask, 0, 0, mask, mode, precise)  # empty fresh reports
        # Same-reset report-pair delta: empty A prefix and actual inter-report
        # query interval B, verified against the original cumulative equality.
        for i in range(40):
            for mode in (0, 1):
                append(0, 0, 0, i, 1, 0, mode, 0)
        for i in range(1000):
            fa, fb = rng.randrange(40), rng.randrange(40)
            append(fa, rng.randrange(8), rng.getrandbits(64), fb, rng.randrange(8),
                   rng.getrandbits(64), i & 1, (i >> 1) & 1)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            qp, jp, output = d / 'queries.bin', d / 'jobs.bin', d / 'out.bin'
            qp.write_bytes(struct.pack('<' + 'Q' * len(queries), *queries))
            jp.write_bytes(struct.pack('<' + 'I' * len(jobs), *jobs))
            exe = d / 'predicate'
            build = subprocess.run([shutil.which('cc'), '-O2', '-DVKA_NDSR_PURE',
                                    '-I', str(ROOT / 'dm/third_party/vulkan-headers/include'),
                                    '-I', str(VK), str(VK / 'selftest/rc_predicate_gpu.c'),
                                    str(VK / 'vka_ndsr.c'), '-ldl', '-lm', '-o', str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe), str(qp), str(jp), str(output)],
                                 env=dict(os.environ), capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn('Validation Error', run.stdout + run.stderr)
            self.assertNotIn('SYNC-HAZARD', run.stdout + run.stderr)
            result = struct.unpack('<' + 'I' * len(expected), output.read_bytes())
            self.assertEqual(list(result), expected)
            print(run.stdout)


if __name__ == "__main__":
    unittest.main()
