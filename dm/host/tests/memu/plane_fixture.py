"""Hand-authored mesh-plane scatter fixture; contains no game instructions.

Models the public SpirvMeshEntry generator's structured helper, including
its z/w mirror, to test runtime lowering with arbitrary sparse locations.
"""


def mesh_source(planes, max_v=128, mutation=None, mirror=True, calls=1):
    chunk = len(planes) * 32
    limit = ((max_v + 31) // 32) * chunk
    locations = sorted({(p - 4) // 4 for p in planes if p >= 4} | {31})
    constants = {0, 1, 2, 3, 5, 31, 32, 264, max_v, 2*max_v, chunk, limit,
                 1664525, 1013904223, 0x12345678, 0x9abcdef0, 0x7fc12345, 0x80000000,
                 *range(len(planes)), *(32*i for i in range(max(calls, (max_v+31)//32)))}
    globals_ = " ".join(f"%out{k}" for k in locations)
    s = [f'''OpCapability Shader
OpCapability MeshShadingEXT
OpExtension "SPV_EXT_mesh_shader"
OpMemoryModel Logical GLSL450
OpEntryPoint MeshEXT %main "main" %lid %wg %pos %idx %zw {globals_}
OpExecutionMode %main LocalSize 32 1 1
OpExecutionMode %main OutputVertices {max_v}
OpExecutionMode %main OutputPrimitivesEXT 1
OpExecutionMode %main OutputTrianglesEXT
OpName %scatter "mesh_plane_store"
OpDecorate %lid BuiltIn LocalInvocationIndex
OpDecorate %wg BuiltIn WorkgroupId
OpDecorate %pv Block
OpMemberDecorate %pv 0 BuiltIn Position
OpDecorate %idx BuiltIn PrimitiveTriangleIndicesEXT
''']
    s += [f"OpDecorate %out{k} Location {k}" for k in locations]
    s += ['''%void = OpTypeVoid
%bool = OpTypeBool
%uint = OpTypeInt 32 0
%float = OpTypeFloat 32
%v3u = OpTypeVector %uint 3
%v4f = OpTypeVector %float 4
%fn = OpTypeFunction %void
%fnuu = OpTypeFunction %void %uint %uint''']
    s += [f"%u{k} = OpConstant %uint {k}" for k in sorted(constants)]
    s += [f'''%f0 = OpConstant %float 0
%f1 = OpConstant %float 1
%zero3 = OpConstantComposite %v3u %u0 %u0 %u0
%pv = OpTypeStruct %v4f
%apos = OpTypeArray %pv %u{max_v}
%avec = OpTypeArray %v4f %u{max_v}
%aidx = OpTypeArray %v3u %u1
%azw = OpTypeArray %uint %u{2*max_v}
%pin = OpTypePointer Input %uint
%pingroup = OpTypePointer Input %v3u
%ppos = OpTypePointer Output %apos
%pvec = OpTypePointer Output %avec
%pidx = OpTypePointer Output %aidx
%poutf = OpTypePointer Output %float
%poutvec = OpTypePointer Output %v4f
%pouti = OpTypePointer Output %v3u
%pzw = OpTypePointer Workgroup %azw
%pwu = OpTypePointer Workgroup %uint
%lid = OpVariable %pin Input
%wg = OpVariable %pingroup Input
%pos = OpVariable %ppos Output
%idx = OpVariable %pidx Output
%zw = OpVariable %pzw Workgroup''']
    s += [f"%out{k} = OpVariable %pvec Output" for k in locations]
    s += [f'''%scatter = OpFunction %void None %fnuu
%word = OpFunctionParameter %uint
%value = OpFunctionParameter %uint
%sc0 = OpLabel
%fv = OpBitcast %float %value
%valid = OpULessThan %bool %word %u{limit}
OpSelectionMerge %end0 None
OpBranchConditional %valid %sc1 %end0
%sc1 = OpLabel
%rem = OpUMod %uint %word %u{chunk}
%plane = OpShiftRightLogical %uint %rem %u5
%group = OpUDiv %uint %word %u{chunk}
%first = OpIMul %uint %group %u32
%lane = OpBitwiseAnd %uint %rem %u31
%vertex = OpIAdd %uint %first %lane
%inrange = OpULessThan %bool %vertex %u{max_v}
OpSelectionMerge %end1 None
OpBranchConditional %inrange %sc2 %end1
%sc2 = OpLabel''']
    for n, code in enumerate(planes):
        target = f"%pos %vertex %u0 %u{code}" if code < 4 else f"%out{(code-4)//4} %vertex %u{code&3}"
        s += [f'''%test{n} = OpIEqual %bool %plane %u{n}
OpSelectionMerge %merge{n} None
OpBranchConditional %test{n} %case{n} %merge{n}
%case{n} = OpLabel
%target{n} = OpAccessChain %poutf {target}
OpStore %target{n} %fv''']
        if mutation == "extra_store" and n == 0:
            s += [f"OpStore %target{n} %fv"]
        if mirror and code in (2, 3):
            raw = "%word" if mutation == "changed_mirror" else "%value"
            s += [f'''%twice{n} = OpIMul %uint %vertex %u2
%offset{n} = OpIAdd %uint %twice{n} %u{code-2}
%mirror{n} = OpAccessChain %pwu %zw %offset{n}
OpStore %mirror{n} {raw}''']
        s += [f"OpBranch %merge{n}", f"%merge{n} = OpLabel"]
    s += ['''OpBranch %end1
%end1 = OpLabel
OpBranch %end0
%end0 = OpLabel
OpReturn
OpFunctionEnd
%main = OpFunction %void None %fn
%main0 = OpLabel
OpSetMeshOutputsEXT %MAX_VERTICES %u1
%l = OpLoad %uint %lid
%wv = OpLoad %v3u %wg
%wx = OpCompositeExtract %uint %wv 0
%baseword = OpIMul %uint %wx %u32
%inputword = OpIAdd %uint %baseword %l
%mul = OpIMul %uint %inputword %u1664525
%bits0 = OpIAdd %uint %mul %u1013904223
%lane0 = OpIEqual %bool %l %u0
%lane1 = OpIEqual %bool %l %u1
%bits1 = OpSelect %uint %lane0 %u2143363909 %bits0
%bits = OpSelect %uint %lane1 %u2147483648 %bits1''']
    for c in range((max_v+31)//32):
        s += [f'''%v{c} = OpIAdd %uint %l %u{32*c}
%zindex{c} = OpIMul %uint %v{c} %u2
%windex{c} = OpIAdd %uint %zindex{c} %u1
%zptr{c} = OpAccessChain %pwu %zw %zindex{c}
%wptr{c} = OpAccessChain %pwu %zw %windex{c}
OpStore %zptr{c} %u305419896
OpStore %wptr{c} %u2596069104''']
    s += ['OpControlBarrier %u2 %u2 %u264']
    for c in range(calls):
        s += [f"%callword{c} = OpIAdd %uint %inputword %u{32*c}",
              f"%call{c} = OpFunctionCall %void %scatter %callword{c} %bits"]
    s += ['OpControlBarrier %u2 %u2 %u264']
    for c in range((max_v+31)//32):
        s += [f'''%z{c} = OpLoad %uint %zptr{c}
%w{c} = OpLoad %uint %wptr{c}
%zf{c} = OpBitcast %float %z{c}
%wf{c} = OpBitcast %float %w{c}
%mirrorvec{c} = OpCompositeConstruct %v4f %zf{c} %wf{c} %f0 %f1
%mirrorout{c} = OpAccessChain %poutvec %out31 %v{c}
OpStore %mirrorout{c} %mirrorvec{c}''']
    s += ['''OpSelectionMerge %mainend None
OpBranchConditional %lane0 %indexwrite %mainend
%indexwrite = OpLabel
%indexptr = OpAccessChain %pouti %idx %u0
OpStore %indexptr %zero3
OpBranch %mainend
%mainend = OpLabel
OpReturn
OpFunctionEnd''']
    return ("\n".join(s) + "\n").replace("%MAX_VERTICES", f"%u{max_v}")
