// Modules of t_android_spvpatch's test of vka_spv_img_retype (dm/gfx/vk_android/vka_spvpatch.c): compute shaders shaped as the translator emits formatted surface
// operations (SULD.P / SUST.P: OpLoad of the image variable, or of an access chain into an array of them, then OpImageRead / OpImageWrite of vec4 floats) and
// texture reads (TEX / TLD / TLD4 of float sampled images: SPV_IMG_M4). Assembled with spirv-as --target-env vulkan1.3 from the text below (the NDK's shader-tools), valid by spirv-val
//
// SPV_IMG_M1: float storage images of format Unknown at set 0 bindings 1 (read through a copy, size queried, written), 2 (an array of two, element 1 read and written)
// and 3 (the same type as 1, left float), and an R32ui unsigned image at binding 4 (SULD.D's)
//   OpCapability Shader
//   OpCapability StorageImageReadWithoutFormat
//   OpCapability StorageImageWriteWithoutFormat
//   OpCapability ImageQuery
//   OpMemoryModel Logical GLSL450
//   OpEntryPoint GLCompute %main "main" %img1 %img2 %img3 %img4
//   OpExecutionMode %main LocalSize 8 8 1
//   OpDecorate %img1 DescriptorSet 0
//   OpDecorate %img1 Binding 1
//   OpDecorate %img2 DescriptorSet 0
//   OpDecorate %img2 Binding 2
//   OpDecorate %img3 DescriptorSet 0
//   OpDecorate %img3 Binding 3
//   OpDecorate %img4 DescriptorSet 0
//   OpDecorate %img4 Binding 4
//   %void = OpTypeVoid
//   %fn = OpTypeFunction %void
//   %float = OpTypeFloat 32
//   %uint = OpTypeInt 32 0
//   %int = OpTypeInt 32 1
//   %v4float = OpTypeVector %float 4
//   %v2int = OpTypeVector %int 2
//   %v4uint = OpTypeVector %uint 4
//   %fimg = OpTypeImage %float 2D 0 0 0 2 Unknown
//   %uimg = OpTypeImage %uint 2D 0 0 0 2 R32ui
//   %p_fimg = OpTypePointer UniformConstant %fimg
//   %p_uimg = OpTypePointer UniformConstant %uimg
//   %uint_2 = OpConstant %uint 2
//   %arr = OpTypeArray %fimg %uint_2
//   %p_arr = OpTypePointer UniformConstant %arr
//   %img1 = OpVariable %p_fimg UniformConstant
//   %img2 = OpVariable %p_arr UniformConstant
//   %img3 = OpVariable %p_fimg UniformConstant
//   %img4 = OpVariable %p_uimg UniformConstant
//   %int_0 = OpConstant %int 0
//   %int_1 = OpConstant %int 1
//   %coord = OpConstantComposite %v2int %int_0 %int_1
//   %f0 = OpConstant %float 0
//   %main = OpFunction %void None %fn
//   %entry = OpLabel
//   %l1 = OpLoad %fimg %img1
//   %l1c = OpCopyObject %fimg %l1
//   %t1 = OpImageRead %v4float %l1c %coord
//   %sz = OpImageQuerySize %v2int %l1
//   %x = OpCompositeExtract %float %t1 0
//   %t2 = OpCompositeConstruct %v4float %x %f0 %f0 %f0
//   OpImageWrite %l1 %coord %t2
//   %pc = OpAccessChain %p_fimg %img2 %int_1
//   %l2 = OpLoad %fimg %pc
//   %t3 = OpImageRead %v4float %l2 %sz
//   OpImageWrite %l2 %coord %t3
//   %l3 = OpLoad %fimg %img3
//   %t4 = OpImageRead %v4float %l3 %coord
//   OpImageWrite %l3 %coord %t4
//   %l4 = OpLoad %uimg %img4
//   %t5 = OpImageRead %v4uint %l4 %coord
//   OpImageWrite %l4 %coord %t5
//   OpReturn
//   OpFunctionEnd
//
// SPV_IMG_M2: a float storage image of format Unknown at set 0 binding 0, read sparse and written back; the module has no unsigned integer type
//   OpCapability Shader
//   OpCapability SparseResidency
//   OpCapability StorageImageReadWithoutFormat
//   OpCapability StorageImageWriteWithoutFormat
//   OpMemoryModel Logical GLSL450
//   OpEntryPoint GLCompute %main "main" %img0
//   OpExecutionMode %main LocalSize 64 1 1
//   OpDecorate %img0 DescriptorSet 0
//   OpDecorate %img0 Binding 0
//   %void = OpTypeVoid
//   %fn = OpTypeFunction %void
//   %float = OpTypeFloat 32
//   %int = OpTypeInt 32 1
//   %v4float = OpTypeVector %float 4
//   %v2int = OpTypeVector %int 2
//   %res = OpTypeStruct %int %v4float
//   %fimg = OpTypeImage %float 2D 0 0 0 2 Unknown
//   %p_fimg = OpTypePointer UniformConstant %fimg
//   %img0 = OpVariable %p_fimg UniformConstant
//   %int_0 = OpConstant %int 0
//   %coord = OpConstantComposite %v2int %int_0 %int_0
//   %main = OpFunction %void None %fn
//   %entry = OpLabel
//   %l = OpLoad %fimg %img0
//   %sr = OpImageSparseRead %res %l %coord
//   %code = OpCompositeExtract %int %sr 0
//   %tex = OpCompositeExtract %v4float %sr 1
//   OpImageWrite %l %coord %tex
//   OpReturn
//   OpFunctionEnd
//
// SPV_IMG_M3: a float storage image of format Unknown at set 0 binding 1 (read and written), beside an unsigned sampled texture at binding 0 whose image type
// (OpTypeImage %uint 2D 0 0 0 1 Unknown) has the storage image's shape but Sampled = 1: binding 1 as uint of format Unknown must declare its own image type
//   OpCapability Shader
//   OpCapability StorageImageReadWithoutFormat
//   OpCapability StorageImageWriteWithoutFormat
//   OpMemoryModel Logical GLSL450
//   OpEntryPoint GLCompute %main "main" %img %tex
//   OpExecutionMode %main LocalSize 1 1 1
//   OpDecorate %img DescriptorSet 0
//   OpDecorate %img Binding 1
//   OpDecorate %tex DescriptorSet 0
//   OpDecorate %tex Binding 0
//   %void = OpTypeVoid
//   %fn = OpTypeFunction %void
//   %float = OpTypeFloat 32
//   %uint = OpTypeInt 32 0
//   %int = OpTypeInt 32 1
//   %v4float = OpTypeVector %float 4
//   %v4uint = OpTypeVector %uint 4
//   %v2int = OpTypeVector %int 2
//   %fimg = OpTypeImage %float 2D 0 0 0 2 Unknown
//   %pfimg = OpTypePointer UniformConstant %fimg
//   %img = OpVariable %pfimg UniformConstant
//   %uimg = OpTypeImage %uint 2D 0 0 0 1 Unknown
//   %usimg = OpTypeSampledImage %uimg
//   %pusimg = OpTypePointer UniformConstant %usimg
//   %tex = OpVariable %pusimg UniformConstant
//   %int0 = OpConstant %int 0
//   %c00 = OpConstantComposite %v2int %int0 %int0
//   %main = OpFunction %void None %fn
//   %l = OpLabel
//   %t = OpLoad %usimg %tex
//   %ti = OpImage %uimg %t
//   %u = OpImageFetch %v4uint %ti %c00 Lod %int0
//   %i = OpLoad %fimg %img
//   %r = OpImageRead %v4float %i %c00
//   %fu = OpBitcast %v4float %u
//   %s = OpFAdd %v4float %r %fu
//   OpImageWrite %i %c00 %s
//   OpReturn
//   OpFunctionEnd
#pragma once
#include <stdint.h>
static const uint32_t SPV_IMG_M1[] = {
    0x07230203, 0x00010600, 0x00070000, 0x00000027, 0x00000000, 0x00020011, 0x00000001, 0x00020011, 0x00000037, 0x00020011, 0x00000038, 0x00020011,
    0x00000032, 0x0003000e, 0x00000000, 0x00000001, 0x0009000f, 0x00000005, 0x00000001, 0x6e69616d, 0x00000000, 0x00000002, 0x00000003, 0x00000004,
    0x00000005, 0x00060010, 0x00000001, 0x00000011, 0x00000008, 0x00000008, 0x00000001, 0x00040047, 0x00000002, 0x00000022, 0x00000000, 0x00040047,
    0x00000002, 0x00000021, 0x00000001, 0x00040047, 0x00000003, 0x00000022, 0x00000000, 0x00040047, 0x00000003, 0x00000021, 0x00000002, 0x00040047,
    0x00000004, 0x00000022, 0x00000000, 0x00040047, 0x00000004, 0x00000021, 0x00000003, 0x00040047, 0x00000005, 0x00000022, 0x00000000, 0x00040047,
    0x00000005, 0x00000021, 0x00000004, 0x00020013, 0x00000006, 0x00030021, 0x00000007, 0x00000006, 0x00030016, 0x00000008, 0x00000020, 0x00040015,
    0x00000009, 0x00000020, 0x00000000, 0x00040015, 0x0000000a, 0x00000020, 0x00000001, 0x00040017, 0x0000000b, 0x00000008, 0x00000004, 0x00040017,
    0x0000000c, 0x0000000a, 0x00000002, 0x00040017, 0x0000000d, 0x00000009, 0x00000004, 0x00090019, 0x0000000e, 0x00000008, 0x00000001, 0x00000000,
    0x00000000, 0x00000000, 0x00000002, 0x00000000, 0x00090019, 0x0000000f, 0x00000009, 0x00000001, 0x00000000, 0x00000000, 0x00000000, 0x00000002,
    0x00000021, 0x00040020, 0x00000010, 0x00000000, 0x0000000e, 0x00040020, 0x00000011, 0x00000000, 0x0000000f, 0x0004002b, 0x00000009, 0x00000012,
    0x00000002, 0x0004001c, 0x00000013, 0x0000000e, 0x00000012, 0x00040020, 0x00000014, 0x00000000, 0x00000013, 0x0004003b, 0x00000010, 0x00000002,
    0x00000000, 0x0004003b, 0x00000014, 0x00000003, 0x00000000, 0x0004003b, 0x00000010, 0x00000004, 0x00000000, 0x0004003b, 0x00000011, 0x00000005,
    0x00000000, 0x0004002b, 0x0000000a, 0x00000015, 0x00000000, 0x0004002b, 0x0000000a, 0x00000016, 0x00000001, 0x0005002c, 0x0000000c, 0x00000017,
    0x00000015, 0x00000016, 0x0004002b, 0x00000008, 0x00000018, 0x00000000, 0x00050036, 0x00000006, 0x00000001, 0x00000000, 0x00000007, 0x000200f8,
    0x00000019, 0x0004003d, 0x0000000e, 0x0000001a, 0x00000002, 0x00040053, 0x0000000e, 0x0000001b, 0x0000001a, 0x00050062, 0x0000000b, 0x0000001c,
    0x0000001b, 0x00000017, 0x00040068, 0x0000000c, 0x0000001d, 0x0000001a, 0x00050051, 0x00000008, 0x0000001e, 0x0000001c, 0x00000000, 0x00070050,
    0x0000000b, 0x0000001f, 0x0000001e, 0x00000018, 0x00000018, 0x00000018, 0x00040063, 0x0000001a, 0x00000017, 0x0000001f, 0x00050041, 0x00000010,
    0x00000020, 0x00000003, 0x00000016, 0x0004003d, 0x0000000e, 0x00000021, 0x00000020, 0x00050062, 0x0000000b, 0x00000022, 0x00000021, 0x0000001d,
    0x00040063, 0x00000021, 0x00000017, 0x00000022, 0x0004003d, 0x0000000e, 0x00000023, 0x00000004, 0x00050062, 0x0000000b, 0x00000024, 0x00000023,
    0x00000017, 0x00040063, 0x00000023, 0x00000017, 0x00000024, 0x0004003d, 0x0000000f, 0x00000025, 0x00000005, 0x00050062, 0x0000000d, 0x00000026,
    0x00000025, 0x00000017, 0x00040063, 0x00000025, 0x00000017, 0x00000026, 0x000100fd, 0x00010038,
};
static const uint32_t SPV_IMG_M2[] = {
    0x07230203, 0x00010600, 0x00070000, 0x00000013, 0x00000000, 0x00020011, 0x00000001, 0x00020011, 0x00000029, 0x00020011, 0x00000037, 0x00020011,
    0x00000038, 0x0003000e, 0x00000000, 0x00000001, 0x0006000f, 0x00000005, 0x00000001, 0x6e69616d, 0x00000000, 0x00000002, 0x00060010, 0x00000001,
    0x00000011, 0x00000040, 0x00000001, 0x00000001, 0x00040047, 0x00000002, 0x00000022, 0x00000000, 0x00040047, 0x00000002, 0x00000021, 0x00000000,
    0x00020013, 0x00000003, 0x00030021, 0x00000004, 0x00000003, 0x00030016, 0x00000005, 0x00000020, 0x00040015, 0x00000006, 0x00000020, 0x00000001,
    0x00040017, 0x00000007, 0x00000005, 0x00000004, 0x00040017, 0x00000008, 0x00000006, 0x00000002, 0x0004001e, 0x00000009, 0x00000006, 0x00000007,
    0x00090019, 0x0000000a, 0x00000005, 0x00000001, 0x00000000, 0x00000000, 0x00000000, 0x00000002, 0x00000000, 0x00040020, 0x0000000b, 0x00000000,
    0x0000000a, 0x0004003b, 0x0000000b, 0x00000002, 0x00000000, 0x0004002b, 0x00000006, 0x0000000c, 0x00000000, 0x0005002c, 0x00000008, 0x0000000d,
    0x0000000c, 0x0000000c, 0x00050036, 0x00000003, 0x00000001, 0x00000000, 0x00000004, 0x000200f8, 0x0000000e, 0x0004003d, 0x0000000a, 0x0000000f,
    0x00000002, 0x00050140, 0x00000009, 0x00000010, 0x0000000f, 0x0000000d, 0x00050051, 0x00000006, 0x00000011, 0x00000010, 0x00000000, 0x00050051,
    0x00000007, 0x00000012, 0x00000010, 0x00000001, 0x00040063, 0x0000000f, 0x0000000d, 0x00000012, 0x000100fd, 0x00010038,
};
static const uint32_t SPV_IMG_M3[] = {
    0x07230203, 0x00010600, 0x00070000, 0x0000001b, 0x00000000, 0x00020011, 0x00000001, 0x00020011, 0x00000037, 0x00020011, 0x00000038, 0x0003000e,
    0x00000000, 0x00000001, 0x0007000f, 0x00000005, 0x00000001, 0x6e69616d, 0x00000000, 0x00000002, 0x00000003, 0x00060010, 0x00000001, 0x00000011,
    0x00000001, 0x00000001, 0x00000001, 0x00040047, 0x00000002, 0x00000022, 0x00000000, 0x00040047, 0x00000002, 0x00000021, 0x00000001, 0x00040047,
    0x00000003, 0x00000022, 0x00000000, 0x00040047, 0x00000003, 0x00000021, 0x00000000, 0x00020013, 0x00000004, 0x00030021, 0x00000005, 0x00000004,
    0x00030016, 0x00000006, 0x00000020, 0x00040015, 0x00000007, 0x00000020, 0x00000000, 0x00040015, 0x00000008, 0x00000020, 0x00000001, 0x00040017,
    0x00000009, 0x00000006, 0x00000004, 0x00040017, 0x0000000a, 0x00000007, 0x00000004, 0x00040017, 0x0000000b, 0x00000008, 0x00000002, 0x00090019,
    0x0000000c, 0x00000006, 0x00000001, 0x00000000, 0x00000000, 0x00000000, 0x00000002, 0x00000000, 0x00040020, 0x0000000d, 0x00000000, 0x0000000c,
    0x0004003b, 0x0000000d, 0x00000002, 0x00000000, 0x00090019, 0x0000000e, 0x00000007, 0x00000001, 0x00000000, 0x00000000, 0x00000000, 0x00000001,
    0x00000000, 0x0003001b, 0x0000000f, 0x0000000e, 0x00040020, 0x00000010, 0x00000000, 0x0000000f, 0x0004003b, 0x00000010, 0x00000003, 0x00000000,
    0x0004002b, 0x00000008, 0x00000011, 0x00000000, 0x0005002c, 0x0000000b, 0x00000012, 0x00000011, 0x00000011, 0x00050036, 0x00000004, 0x00000001,
    0x00000000, 0x00000005, 0x000200f8, 0x00000013, 0x0004003d, 0x0000000f, 0x00000014, 0x00000003, 0x00040064, 0x0000000e, 0x00000015, 0x00000014,
    0x0007005f, 0x0000000a, 0x00000016, 0x00000015, 0x00000012, 0x00000002, 0x00000011, 0x0004003d, 0x0000000c, 0x00000017, 0x00000002, 0x00050062,
    0x00000009, 0x00000018, 0x00000017, 0x00000012, 0x0004007c, 0x00000009, 0x00000019, 0x00000016, 0x00050081, 0x00000009, 0x0000001a, 0x00000018,
    0x00000019, 0x00040063, 0x00000017, 0x00000012, 0x0000001a, 0x000100fd, 0x00010038,
};
//
// SPV_IMG_M4: float sampled images as the translator declares them (DeclareSamplers: OpTypeImage %float ... Sampled 1 Unknown), at set 0 bindings 1 (combined: a fetch
// through OpImage, a size query and an explicit-LOD sample), 2 (an array of two combined ones, element 1: a gather through a copy, a fetch), 3 (combined: a sparse
// fetch), 4 (a depth-compare one: OpImageSampleDrefExplicitLod, refused when selected), 5 (the separate form: an image that OpSampledImage pairs with the sampler at
// binding 6) and 7 (the same type as 1, left float); binding 0 is a float storage image of format Unknown the results are written to
//   OpCapability Shader
//   OpCapability SparseResidency
//   OpCapability ImageQuery
//   OpCapability StorageImageWriteWithoutFormat
//   OpMemoryModel Logical GLSL450
//   OpEntryPoint GLCompute %main "main" %out %t1 %t2 %t3 %t4 %t5 %s6 %t7
//   OpExecutionMode %main LocalSize 8 8 1
//   OpDecorate %out DescriptorSet 0
//   OpDecorate %out Binding 0
//   OpDecorate %t1 DescriptorSet 0
//   OpDecorate %t1 Binding 1
//   OpDecorate %t2 DescriptorSet 0
//   OpDecorate %t2 Binding 2
//   OpDecorate %t3 DescriptorSet 0
//   OpDecorate %t3 Binding 3
//   OpDecorate %t4 DescriptorSet 0
//   OpDecorate %t4 Binding 4
//   OpDecorate %t5 DescriptorSet 0
//   OpDecorate %t5 Binding 5
//   OpDecorate %s6 DescriptorSet 0
//   OpDecorate %s6 Binding 6
//   OpDecorate %t7 DescriptorSet 0
//   OpDecorate %t7 Binding 7
//   %void = OpTypeVoid
//   %fn = OpTypeFunction %void
//   %float = OpTypeFloat 32
//   %int = OpTypeInt 32 1
//   %uint = OpTypeInt 32 0
//   %v4float = OpTypeVector %float 4
//   %v2float = OpTypeVector %float 2
//   %v2int = OpTypeVector %int 2
//   %fimg = OpTypeImage %float 2D 0 0 0 1 Unknown
//   %fsimg = OpTypeSampledImage %fimg
//   %dimg = OpTypeImage %float 2D 1 0 0 1 Unknown
//   %dsimg = OpTypeSampledImage %dimg
//   %oimg = OpTypeImage %float 2D 0 0 0 2 Unknown
//   %samp = OpTypeSampler
//   %p_fsimg = OpTypePointer UniformConstant %fsimg
//   %uint_2 = OpConstant %uint 2
//   %arr = OpTypeArray %fsimg %uint_2
//   %p_arr = OpTypePointer UniformConstant %arr
//   %p_dsimg = OpTypePointer UniformConstant %dsimg
//   %p_fimg = OpTypePointer UniformConstant %fimg
//   %p_samp = OpTypePointer UniformConstant %samp
//   %p_oimg = OpTypePointer UniformConstant %oimg
//   %res = OpTypeStruct %int %v4float
//   %out = OpVariable %p_oimg UniformConstant
//   %t1 = OpVariable %p_fsimg UniformConstant
//   %t2 = OpVariable %p_arr UniformConstant
//   %t3 = OpVariable %p_fsimg UniformConstant
//   %t4 = OpVariable %p_dsimg UniformConstant
//   %t5 = OpVariable %p_fimg UniformConstant
//   %s6 = OpVariable %p_samp UniformConstant
//   %t7 = OpVariable %p_fsimg UniformConstant
//   %int_0 = OpConstant %int 0
//   %int_1 = OpConstant %int 1
//   %coord = OpConstantComposite %v2int %int_0 %int_1
//   %f0 = OpConstant %float 0
//   %f05 = OpConstant %float 0.5
//   %uv = OpConstantComposite %v2float %f05 %f05
//   %main = OpFunction %void None %fn
//   %entry = OpLabel
//   %l1 = OpLoad %fsimg %t1
//   %i1 = OpImage %fimg %l1
//   %a = OpImageFetch %v4float %i1 %coord Lod %int_0
//   %sz = OpImageQuerySizeLod %v2int %i1 %int_0
//   %b = OpImageSampleExplicitLod %v4float %l1 %uv Lod %f0
//   %pc = OpAccessChain %p_fsimg %t2 %int_1
//   %l2 = OpLoad %fsimg %pc
//   %l2c = OpCopyObject %fsimg %l2
//   %c = OpImageGather %v4float %l2c %uv %int_0
//   %i2 = OpImage %fimg %l2
//   %d = OpImageFetch %v4float %i2 %sz Lod %int_0
//   %l3 = OpLoad %fsimg %t3
//   %i3 = OpImage %fimg %l3
//   %sr = OpImageSparseFetch %res %i3 %coord Lod %int_0
//   %e = OpCompositeExtract %v4float %sr 1
//   %l4 = OpLoad %dsimg %t4
//   %g = OpImageSampleDrefExplicitLod %float %l4 %uv %f05 Lod %f0
//   %l5 = OpLoad %fimg %t5
//   %l6 = OpLoad %samp %s6
//   %si = OpSampledImage %fsimg %l5 %l6
//   %h = OpImageSampleExplicitLod %v4float %si %uv Lod %f0
//   %l7 = OpLoad %fsimg %t7
//   %k = OpImageSampleExplicitLod %v4float %l7 %uv Lod %f0
//   %s1 = OpFAdd %v4float %a %b
//   %s2 = OpFAdd %v4float %s1 %c
//   %s3 = OpFAdd %v4float %s2 %d
//   %s4 = OpFAdd %v4float %s3 %e
//   %s5 = OpFAdd %v4float %s4 %h
//   %s6v = OpFAdd %v4float %s5 %k
//   %s7 = OpVectorTimesScalar %v4float %s6v %g
//   %o = OpLoad %oimg %out
//   OpImageWrite %o %coord %s7
//   OpReturn
//   OpFunctionEnd
static const uint32_t SPV_IMG_M4[] = {
    0x07230203, 0x00010600, 0x00070000, 0x00000047, 0x00000000, 0x00020011, 0x00000001, 0x00020011, 0x00000029, 0x00020011, 0x00000032, 0x00020011,
    0x00000038, 0x0003000e, 0x00000000, 0x00000001, 0x000d000f, 0x00000005, 0x00000001, 0x6e69616d, 0x00000000, 0x00000002, 0x00000003, 0x00000004,
    0x00000005, 0x00000006, 0x00000007, 0x00000008, 0x00000009, 0x00060010, 0x00000001, 0x00000011, 0x00000008, 0x00000008, 0x00000001, 0x00040047,
    0x00000002, 0x00000022, 0x00000000, 0x00040047, 0x00000002, 0x00000021, 0x00000000, 0x00040047, 0x00000003, 0x00000022, 0x00000000, 0x00040047,
    0x00000003, 0x00000021, 0x00000001, 0x00040047, 0x00000004, 0x00000022, 0x00000000, 0x00040047, 0x00000004, 0x00000021, 0x00000002, 0x00040047,
    0x00000005, 0x00000022, 0x00000000, 0x00040047, 0x00000005, 0x00000021, 0x00000003, 0x00040047, 0x00000006, 0x00000022, 0x00000000, 0x00040047,
    0x00000006, 0x00000021, 0x00000004, 0x00040047, 0x00000007, 0x00000022, 0x00000000, 0x00040047, 0x00000007, 0x00000021, 0x00000005, 0x00040047,
    0x00000008, 0x00000022, 0x00000000, 0x00040047, 0x00000008, 0x00000021, 0x00000006, 0x00040047, 0x00000009, 0x00000022, 0x00000000, 0x00040047,
    0x00000009, 0x00000021, 0x00000007, 0x00020013, 0x0000000a, 0x00030021, 0x0000000b, 0x0000000a, 0x00030016, 0x0000000c, 0x00000020, 0x00040015,
    0x0000000d, 0x00000020, 0x00000001, 0x00040015, 0x0000000e, 0x00000020, 0x00000000, 0x00040017, 0x0000000f, 0x0000000c, 0x00000004, 0x00040017,
    0x00000010, 0x0000000c, 0x00000002, 0x00040017, 0x00000011, 0x0000000d, 0x00000002, 0x00090019, 0x00000012, 0x0000000c, 0x00000001, 0x00000000,
    0x00000000, 0x00000000, 0x00000001, 0x00000000, 0x0003001b, 0x00000013, 0x00000012, 0x00090019, 0x00000014, 0x0000000c, 0x00000001, 0x00000001,
    0x00000000, 0x00000000, 0x00000001, 0x00000000, 0x0003001b, 0x00000015, 0x00000014, 0x00090019, 0x00000016, 0x0000000c, 0x00000001, 0x00000000,
    0x00000000, 0x00000000, 0x00000002, 0x00000000, 0x0002001a, 0x00000017, 0x00040020, 0x00000018, 0x00000000, 0x00000013, 0x0004002b, 0x0000000e,
    0x00000019, 0x00000002, 0x0004001c, 0x0000001a, 0x00000013, 0x00000019, 0x00040020, 0x0000001b, 0x00000000, 0x0000001a, 0x00040020, 0x0000001c,
    0x00000000, 0x00000015, 0x00040020, 0x0000001d, 0x00000000, 0x00000012, 0x00040020, 0x0000001e, 0x00000000, 0x00000017, 0x00040020, 0x0000001f,
    0x00000000, 0x00000016, 0x0004001e, 0x00000020, 0x0000000d, 0x0000000f, 0x0004003b, 0x0000001f, 0x00000002, 0x00000000, 0x0004003b, 0x00000018,
    0x00000003, 0x00000000, 0x0004003b, 0x0000001b, 0x00000004, 0x00000000, 0x0004003b, 0x00000018, 0x00000005, 0x00000000, 0x0004003b, 0x0000001c,
    0x00000006, 0x00000000, 0x0004003b, 0x0000001d, 0x00000007, 0x00000000, 0x0004003b, 0x0000001e, 0x00000008, 0x00000000, 0x0004003b, 0x00000018,
    0x00000009, 0x00000000, 0x0004002b, 0x0000000d, 0x00000021, 0x00000000, 0x0004002b, 0x0000000d, 0x00000022, 0x00000001, 0x0005002c, 0x00000011,
    0x00000023, 0x00000021, 0x00000022, 0x0004002b, 0x0000000c, 0x00000024, 0x00000000, 0x0004002b, 0x0000000c, 0x00000025, 0x3f000000, 0x0005002c,
    0x00000010, 0x00000026, 0x00000025, 0x00000025, 0x00050036, 0x0000000a, 0x00000001, 0x00000000, 0x0000000b, 0x000200f8, 0x00000027, 0x0004003d,
    0x00000013, 0x00000028, 0x00000003, 0x00040064, 0x00000012, 0x00000029, 0x00000028, 0x0007005f, 0x0000000f, 0x0000002a, 0x00000029, 0x00000023,
    0x00000002, 0x00000021, 0x00050067, 0x00000011, 0x0000002b, 0x00000029, 0x00000021, 0x00070058, 0x0000000f, 0x0000002c, 0x00000028, 0x00000026,
    0x00000002, 0x00000024, 0x00050041, 0x00000018, 0x0000002d, 0x00000004, 0x00000022, 0x0004003d, 0x00000013, 0x0000002e, 0x0000002d, 0x00040053,
    0x00000013, 0x0000002f, 0x0000002e, 0x00060060, 0x0000000f, 0x00000030, 0x0000002f, 0x00000026, 0x00000021, 0x00040064, 0x00000012, 0x00000031,
    0x0000002e, 0x0007005f, 0x0000000f, 0x00000032, 0x00000031, 0x0000002b, 0x00000002, 0x00000021, 0x0004003d, 0x00000013, 0x00000033, 0x00000005,
    0x00040064, 0x00000012, 0x00000034, 0x00000033, 0x00070139, 0x00000020, 0x00000035, 0x00000034, 0x00000023, 0x00000002, 0x00000021, 0x00050051,
    0x0000000f, 0x00000036, 0x00000035, 0x00000001, 0x0004003d, 0x00000015, 0x00000037, 0x00000006, 0x0008005a, 0x0000000c, 0x00000038, 0x00000037,
    0x00000026, 0x00000025, 0x00000002, 0x00000024, 0x0004003d, 0x00000012, 0x00000039, 0x00000007, 0x0004003d, 0x00000017, 0x0000003a, 0x00000008,
    0x00050056, 0x00000013, 0x0000003b, 0x00000039, 0x0000003a, 0x00070058, 0x0000000f, 0x0000003c, 0x0000003b, 0x00000026, 0x00000002, 0x00000024,
    0x0004003d, 0x00000013, 0x0000003d, 0x00000009, 0x00070058, 0x0000000f, 0x0000003e, 0x0000003d, 0x00000026, 0x00000002, 0x00000024, 0x00050081,
    0x0000000f, 0x0000003f, 0x0000002a, 0x0000002c, 0x00050081, 0x0000000f, 0x00000040, 0x0000003f, 0x00000030, 0x00050081, 0x0000000f, 0x00000041,
    0x00000040, 0x00000032, 0x00050081, 0x0000000f, 0x00000042, 0x00000041, 0x00000036, 0x00050081, 0x0000000f, 0x00000043, 0x00000042, 0x0000003c,
    0x00050081, 0x0000000f, 0x00000044, 0x00000043, 0x0000003e, 0x0005008e, 0x0000000f, 0x00000045, 0x00000044, 0x00000038, 0x0004003d, 0x00000016,
    0x00000046, 0x00000002, 0x00040063, 0x00000046, 0x00000023, 0x00000045, 0x000100fd, 0x00010038,
};
