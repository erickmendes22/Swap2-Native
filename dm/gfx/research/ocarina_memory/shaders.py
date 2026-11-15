"""Isolated 8192-entry current-cache/page-index comparison, no game shaders."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
TRANSLATOR=ROOT/'dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Translation/Optimizations/GlobalToStorage.cs'

def source(mode, warm=False, negative=False):
    assert mode in ('baseline','page','hybrid')
    text=TRANSLATOR.read_text()
    for marker in ('new int[7]', 'Const(8192 - 1)', 'Const(8192)', 'Const(11)', 'Const(21)', 'mapLog2 - 1'):
        assert marker in text, 'Production helper changed; review fixture: '+marker
    head='''#version 460
#extension GL_EXT_buffer_reference : require
#extension GL_EXT_shader_explicit_arithmetic_types_int64 : require
layout(local_size_x=64) in;
layout(buffer_reference,std430,buffer_reference_align=4) buffer PU{uint v;};
layout(set=0,binding=0,std430) readonly buffer Map{uint w[];} map_;
layout(set=0,binding=1,std430) buffer Log{uint w[];} log_;
layout(set=0,binding=2,std430) readonly buffer Cases{uvec4 c[];} cases;
layout(set=0,binding=3,std430) buffer Out{uint o[];} out_;
uint hits=0u, searches=0u, probes=0u, index_reads=0u;
uint cache_i[2]=uint[2](0u,0u);
uint64_t cache_lo[2],cache_hi[2],cache_delta[2];
uint64_t word64(uint p){return packUint2x32(uvec2(map_.w[p],map_.w[p+1u]));}
uint64_t find_address(uint lo,uint hi,uint helper){
 uint64_t a=packUint2x32(uvec2(lo,hi));
'''
    body=[]
    if mode!='page':
        body+=['if(cache_i[helper]!=0u&&cache_lo[helper]<=a&&a<cache_hi[helper]){hits++;return a+cache_delta[helper];}',
               'uint selected=0u;bool selected_ok=false;',
               'if(word64(8u)<=a&&a<word64(10u)){selected=1u;selected_ok=true;}',
               'if(!selected_ok){uint chunk=(hi<<11u)|(lo>>21u);uint row=(chunk&8191u)*8u;uint tag=map_.w[row+6u],idx=map_.w[row+7u];',
               'if(tag==chunk&&hi<2097152u&&idx!=0u&&idx<8192u){selected=idx;selected_ok=true;}}']
    else:body+=['uint selected=0u;bool selected_ok=false;']
    if mode!='baseline':
        body+=['if(!selected_ok){index_reads++;uint base=map_.w[65536u],count=map_.w[65537u];uint page=(hi<<20u)|(lo>>12u);',
               'if(hi<4095u&&page>=base&&page-base<count){uint64_t rec=word64(65540u+(page-base)*2u);',
               'if((rec&uint64_t(1))!=uint64_t(0)){']
        if mode=='hybrid':
            body+=['cache_i[helper]=1u;cache_lo[helper]=a&~uint64_t(4095);cache_hi[helper]=cache_lo[helper]+uint64_t(4096);cache_delta[helper]=(rec&~uint64_t(4095))-cache_lo[helper];']
        body+=['return (rec&~uint64_t(4095))|uint64_t(lo&4095u);}}}']
    body+=['if(!selected_ok){searches++;uint index=0u;']
    for k in range(12,-1,-1):body+=[f'{{uint c=index+{1<<k}u;probes++;if(word64(c*8u)<=a)index=c;}}']
    body+=['selected=index;}uint p=selected*8u;if(!(a<word64(p+2u)))return uint64_t(0);']
    if mode!='page':body+=['cache_i[helper]=selected;cache_lo[helper]=word64(p);cache_hi[helper]=word64(p+2u);cache_delta[helper]=word64(p+4u);']
    body+=['return a+word64(p+4u);}',
           'uint gload(uint lo,uint hi){uint64_t a=find_address(lo,hi,0u);if(a==uint64_t(0))return 0u;return PU(a).v'+('^1u' if negative else '')+';}',
           'void gstore(uint lo,uint hi,uint value){uint64_t a=find_address(lo,hi,1u);if(a==uint64_t(0))return;',
           'uint page=(hi<<20u)|(lo>>12u),hash=(page*0x9e3779b1u)>>22u;',
           'for(uint pr=0u;pr<8u;pr++){uint slot=((hash+pr)&1023u)+1u,old=atomicCompSwap(log_.w[slot],0u,page);if(old==0u||old==page){PU(a).v=value;return;}}log_.w[0]=1u;PU(a).v=value;}',
           'void main(){uint i=gl_GlobalInvocationID.x;uvec4 c=cases.c[i];']
    if warm:
        for j,k in enumerate(('(i*5u+1u)&63u','(i*7u+3u)&63u','(i+1u)&63u','i')):
            body+=[f'{{uvec4 w=cases.c[{k}];out_.o[64u+i*4u+{j}u]=gload(w.x,w.y);}}']
    body+=['if(c.w==0u)out_.o[i]=gload(c.x,c.y);else{gstore(c.x,c.y,c.z);out_.o[i]=0xdeadu;}',
           'out_.o[320u+i*4u]=hits;out_.o[321u+i*4u]=searches;out_.o[322u+i*4u]=probes;out_.o[323u+i*4u]=index_reads;}']
    return head+'\n'.join(body)
