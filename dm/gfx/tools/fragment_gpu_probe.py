#!/usr/bin/env python3
"""Headless fragment comparison with explicitly synthetic resources.

Not a game replay or a phone performance prediction. Descriptor-array indices
are specialized to zero and their arrays to one element in BOTH probe modules.
Original shader libraries are never modified. Requires vulkan (Python), numpy,
glslangValidator, spirv-val and a Vulkan 1.3 graphics ICD.
"""
import argparse
import collections
import json
from pathlib import Path
import struct
import subprocess
import time

import numpy as np
import vulkan as v
import vk_android_spv as spv


def prepare(source, destination):
    m = spv.Module(source.read_bytes())
    resources = m.resources()
    pools = {r['id'] for r in resources if r['count'] > 1}
    u32 = m.add_type(21,32,0)
    zero = m.add_const(u32,0); one = m.add_const(u32,1)
    for ident in pools:
        _, ty = m.pointee(m.vars[ident][0])
        if m.op(ty) != 28:
            raise ValueError('probe supports fixed descriptor arrays only')
        m.types[ty][3] = one
    # Array lengths must be declared before their OpTypeArray, not merely
    # before the entry function (Module.add_const's normal insertion point).
    if pools:
        declaration=next(i for i in m.ins if i[0]&65535==43 and i[2]==one)
        m.ins.remove(declaration)
        first_array=min(m.ins.index(m.types[m.pointee(m.vars[ident][0])[1]]) for ident in pools)
        m.ins.insert(first_array,declaration)
    for ins in m.ins:
        if ins[0]&65535 in (65,66) and ins[3] in pools:
            if len(ins) != 5:
                raise ValueError('unexpected descriptor access chain')
            ins[4] = zero
    # Indices are now constant zero; nonuniform descriptor capabilities and
    # annotations are unnecessary for this deliberately restricted probe.
    m.ins = [i for i in m.ins if not (
        i[0]&65535 == 71 and i[2] == 5300 or
        i[0]&65535 == 17 and i[1] in (28,5301,5302,5307))]
    spv.strip_unused_caps(m)
    if not any(i[0]&65535 in (96,97) for i in m.ins):
        m.ins=[i for i in m.ins if not(i[0]&65535==17 and i[1]==25)]
    # Probe descriptors all live in one small set; production's sparse
    # pool/table binding numbers need not be supported by the software ICD.
    for ordinal,r in enumerate(sorted(m.resources(),key=lambda r:(r['set'],r['binding']))):
        m.set_binding(r['id'],0,ordinal)
    spv.formatless_storage_caps(m)
    destination.write_bytes(m.data())
    subprocess.run(['spirv-val','--target-env','vulkan1.3',str(destination)],check=True)
    return spv.Module(destination.read_bytes())


def vertex_shader(fragment, path):
    declarations=[]; values=[]
    for vid,(ptr,sc) in fragment.vars.items():
        d=fragment.decos.get(vid,{})
        if sc != 1 or 30 not in d:
            continue
        _,ty=fragment.pointee(ptr)
        if fragment.op(ty) != 23 or fragment.types[ty][3] != 4 or fragment.op(fragment.types[ty][2]) != 22:
            raise ValueError('probe currently requires vec4 fragment inputs')
        loc=d[30][0]; qualifier='flat ' if 14 in d else 'noperspective ' if 13 in d else ''
        declarations.append(f'layout(location={loc}) {qualifier}out vec4 value{loc};')
        values.append(f'value{loc}=data.seed[{loc}]+vec4(p,0,0)*data.seed[{64+loc}];')
    text='#version 450\n'+ '\n'.join(declarations)+'''
layout(set=0,binding=511,std430) readonly buffer Seeds { vec4 seed[]; } data;
void main(){
vec2 p=vec2((gl_VertexIndex<<1)&2,gl_VertexIndex&2);
gl_Position=vec4(p*2.0-1.0,0,1);
'''+ '\n'.join(values)+'\n}\n'
    path.write_text(text)
    out=path.with_suffix('.spv')
    subprocess.run(['glslangValidator','-V','--target-env','vulkan1.3',str(path),'-o',str(out)],check=True,capture_output=True)
    return out


class Probe:
    def __init__(self, resources, vertex, width=32):
        self.width=width; self.resources=resources; self.owned=[]; self.modules=[]; self.pipelines=[]
        self.instance=v.vkCreateInstance(v.VkInstanceCreateInfo(pApplicationInfo=v.VkApplicationInfo(pApplicationName='fragment synthetic probe',apiVersion=v.VK_MAKE_VERSION(1,3,0))),None)
        self.physical=v.vkEnumeratePhysicalDevices(self.instance)[0]
        props=v.vkGetPhysicalDeviceProperties(self.physical)
        self.name=props.deviceName
        self.family=next(i for i,p in enumerate(v.vkGetPhysicalDeviceQueueFamilyProperties(self.physical)) if p.queueFlags & v.VK_QUEUE_GRAPHICS_BIT)
        feature=v.VkPhysicalDeviceVulkan13Features(dynamicRendering=True)
        self.device=v.vkCreateDevice(self.physical,v.VkDeviceCreateInfo(pNext=feature,queueCreateInfoCount=1,pQueueCreateInfos=[v.VkDeviceQueueCreateInfo(queueFamilyIndex=self.family,queueCount=1,pQueuePriorities=[1.0])],pEnabledFeatures=v.VkPhysicalDeviceFeatures(robustBufferAccess=True)),None)
        self.queue=v.vkGetDeviceQueue(self.device,self.family,0)
        valid=v.vkGetPhysicalDeviceQueueFamilyProperties(self.physical)[self.family].timestampValidBits
        if not valid: raise ValueError('graphics queue has no timestamps')
        self.timestamp_mask=(1<<valid)-1
        self.tick=props.limits.timestampPeriod
        self.queries=v.vkCreateQueryPool(self.device,v.VkQueryPoolCreateInfo(queryType=v.VK_QUERY_TYPE_TIMESTAMP,queryCount=2),None)
        self.pool=v.vkCreateCommandPool(self.device,v.VkCommandPoolCreateInfo(flags=v.VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,queueFamilyIndex=self.family),None)
        self.cmd=v.vkAllocateCommandBuffers(self.device,v.VkCommandBufferAllocateInfo(commandPool=self.pool,level=v.VK_COMMAND_BUFFER_LEVEL_PRIMARY,commandBufferCount=1))[0]
        self.descriptor_buffers={}; self.images=[]
        bindings=[v.VkDescriptorSetLayoutBinding(binding=r['binding'],descriptorType=r['desc'],descriptorCount=1,stageFlags=v.VK_SHADER_STAGE_FRAGMENT_BIT) for r in resources]
        bindings.append(v.VkDescriptorSetLayoutBinding(binding=511,descriptorType=v.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,descriptorCount=1,stageFlags=v.VK_SHADER_STAGE_VERTEX_BIT))
        self.setlayout=v.vkCreateDescriptorSetLayout(self.device,v.VkDescriptorSetLayoutCreateInfo(bindingCount=len(bindings),pBindings=bindings),None)
        self.layout=v.vkCreatePipelineLayout(self.device,v.VkPipelineLayoutCreateInfo(setLayoutCount=1,pSetLayouts=[self.setlayout]),None)
        counts=collections.Counter(r['desc'] for r in resources); counts[7]+=1
        self.dp=v.vkCreateDescriptorPool(self.device,v.VkDescriptorPoolCreateInfo(maxSets=1,poolSizeCount=len(counts),pPoolSizes=[v.VkDescriptorPoolSize(type=k,descriptorCount=n) for k,n in counts.items()]),None)
        self.set=v.vkAllocateDescriptorSets(self.device,v.VkDescriptorSetAllocateInfo(descriptorPool=self.dp,descriptorSetCount=1,pSetLayouts=[self.setlayout]))[0]
        writes=[]
        self.sampler=v.vkCreateSampler(self.device,v.VkSamplerCreateInfo(magFilter=v.VK_FILTER_NEAREST,minFilter=v.VK_FILTER_NEAREST,mipmapMode=v.VK_SAMPLER_MIPMAP_MODE_NEAREST,addressModeU=v.VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,addressModeV=v.VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,addressModeW=v.VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,maxLod=0),None)
        self.begin()
        for resource in resources:
            r=resource; binding=r['binding']; desc=r['desc']
            args=dict(dstSet=self.set,dstBinding=binding,descriptorCount=1,descriptorType=desc)
            if desc in (6,7):
                size=65536 if desc==6 else 4*1024*1024
                buf=self.buffer(bytes(size),v.VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT if desc==6 else v.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)
                self.descriptor_buffers[binding]=(buf,r)
                args['pBufferInfo']=[v.VkDescriptorBufferInfo(buffer=buf[0],offset=0,range=size)]
            elif desc==0:
                args['pImageInfo']=[v.VkDescriptorImageInfo(sampler=self.sampler)]
            elif desc in (1,2):
                if r['dim']['depth'] or r['dim']['ms'] or r['dim']['type']:
                    raise ValueError('probe does not synthesize depth/MS/integer textures')
                image=self.image(r['dim'])
                self.barrier(image[0],v.VK_IMAGE_LAYOUT_UNDEFINED,v.VK_IMAGE_LAYOUT_GENERAL,0,v.VK_ACCESS_TRANSFER_WRITE_BIT,image[3])
                layers=image[3].layerCount; depth=4 if r['dim']['dim']==2 else 1
                data=np.zeros((layers,depth,4,4,4),dtype=np.float32)
                for layer in range(layers):
                    for z in range(depth):
                        for y in range(4):
                            for x in range(4):data[layer,z,y,x]=[0.1+(binding%3)*0.1+x/8+z/16,0.1+y/8,0.2+layer/8,1]
                upload=self.buffer(data.tobytes(),v.VK_BUFFER_USAGE_TRANSFER_SRC_BIT)
                copy=v.VkBufferImageCopy(imageSubresource=v.VkImageSubresourceLayers(aspectMask=1,mipLevel=0,baseArrayLayer=0,layerCount=layers),imageExtent=v.VkExtent3D(width=4,height=4,depth=depth))
                v.vkCmdCopyBufferToImage(self.cmd,upload[0],image[0],v.VK_IMAGE_LAYOUT_GENERAL,1,[copy])
                self.barrier(image[0],v.VK_IMAGE_LAYOUT_GENERAL,v.VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,v.VK_ACCESS_TRANSFER_WRITE_BIT,v.VK_ACCESS_SHADER_READ_BIT,image[3])
                args['pImageInfo']=[v.VkDescriptorImageInfo(sampler=self.sampler if desc==1 else v.VK_NULL_HANDLE,imageView=image[1],imageLayout=v.VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL)]
            else:
                raise ValueError('unsupported descriptor type '+str(desc))
            writes.append(v.VkWriteDescriptorSet(**args))
        seeds=np.zeros((128,4),dtype=np.float32)
        seeds[:64]=[0.25,0.5,1,1]; seeds[64:]=[0.25,0.125,0,0]
        self.seeds=self.buffer(seeds.tobytes(),v.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)
        writes.append(v.VkWriteDescriptorSet(dstSet=self.set,dstBinding=511,descriptorCount=1,descriptorType=7,pBufferInfo=[v.VkDescriptorBufferInfo(buffer=self.seeds[0],offset=0,range=seeds.nbytes)]))
        v.vkUpdateDescriptorSets(self.device,len(writes),writes,0,None)
        self.target=self.image({'dim':1,'array':False},width,width,target=True)
        self.barrier(self.target[0],v.VK_IMAGE_LAYOUT_UNDEFINED,v.VK_IMAGE_LAYOUT_GENERAL,0,v.VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,self.target[3])
        self.submit()
        self.readback=self.buffer(bytes(width*width*16),v.VK_BUFFER_USAGE_TRANSFER_DST_BIT)
        self.vertex=self.module(vertex)

    def buffer(self, data, usage):
        b=v.vkCreateBuffer(self.device,v.VkBufferCreateInfo(size=len(data),usage=usage,sharingMode=v.VK_SHARING_MODE_EXCLUSIVE),None)
        req=v.vkGetBufferMemoryRequirements(self.device,b)
        props=v.vkGetPhysicalDeviceMemoryProperties(self.physical)
        typ=next(i for i in range(props.memoryTypeCount) if req.memoryTypeBits>>i&1 and props.memoryTypes[i].propertyFlags & (v.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|v.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)==(v.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|v.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))
        memory=v.vkAllocateMemory(self.device,v.VkMemoryAllocateInfo(allocationSize=req.size,memoryTypeIndex=typ),None)
        v.vkBindBufferMemory(self.device,b,memory,0); mapped=v.vkMapMemory(self.device,memory,0,len(data),0); mapped[:]=data
        self.owned.append((b,memory)); return b,memory,mapped

    def image(self, dim, width=4,height=4,target=False):
        kind=dim['dim']; layers=6 if kind==3 else 2 if dim.get('array') else 1
        depth=4 if kind==2 else 1
        flags=v.VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT if kind==3 else 0
        usage=v.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|v.VK_IMAGE_USAGE_TRANSFER_SRC_BIT if target else v.VK_IMAGE_USAGE_SAMPLED_BIT|v.VK_IMAGE_USAGE_TRANSFER_DST_BIT
        image=v.vkCreateImage(self.device,v.VkImageCreateInfo(flags=flags,imageType=v.VK_IMAGE_TYPE_3D if kind==2 else v.VK_IMAGE_TYPE_2D,format=v.VK_FORMAT_R32G32B32A32_SFLOAT,extent=v.VkExtent3D(width=width,height=height,depth=depth),mipLevels=1,arrayLayers=layers,samples=v.VK_SAMPLE_COUNT_1_BIT,tiling=v.VK_IMAGE_TILING_OPTIMAL,usage=usage,sharingMode=v.VK_SHARING_MODE_EXCLUSIVE,initialLayout=v.VK_IMAGE_LAYOUT_UNDEFINED),None)
        req=v.vkGetImageMemoryRequirements(self.device,image)
        typ=next(i for i in range(32) if req.memoryTypeBits>>i&1)
        mem=v.vkAllocateMemory(self.device,v.VkMemoryAllocateInfo(allocationSize=req.size,memoryTypeIndex=typ),None);v.vkBindImageMemory(self.device,image,mem,0)
        sub=v.VkImageSubresourceRange(aspectMask=v.VK_IMAGE_ASPECT_COLOR_BIT,baseMipLevel=0,levelCount=1,baseArrayLayer=0,layerCount=layers)
        viewtype=v.VK_IMAGE_VIEW_TYPE_CUBE if kind==3 else v.VK_IMAGE_VIEW_TYPE_3D if kind==2 else v.VK_IMAGE_VIEW_TYPE_2D_ARRAY if dim.get('array') else v.VK_IMAGE_VIEW_TYPE_2D
        view=v.vkCreateImageView(self.device,v.VkImageViewCreateInfo(image=image,viewType=viewtype,format=v.VK_FORMAT_R32G32B32A32_SFLOAT,subresourceRange=sub),None)
        result=image,view,mem,sub
        self.images.append(result)
        return result

    def barrier(self, image, old, new, source, destination, sub=None):
        sub=sub or v.VkImageSubresourceRange(aspectMask=1,levelCount=1,layerCount=1)
        b=v.VkImageMemoryBarrier(srcAccessMask=source,dstAccessMask=destination,oldLayout=old,newLayout=new,srcQueueFamilyIndex=v.VK_QUEUE_FAMILY_IGNORED,dstQueueFamilyIndex=v.VK_QUEUE_FAMILY_IGNORED,image=image,subresourceRange=sub)
        v.vkCmdPipelineBarrier(self.cmd,v.VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,v.VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,None,0,None,1,[b])

    def begin(self):
        v.vkResetCommandBuffer(self.cmd,0)
        v.vkBeginCommandBuffer(self.cmd,v.VkCommandBufferBeginInfo())

    def submit(self):
        v.vkEndCommandBuffer(self.cmd)
        v.vkQueueSubmit(self.queue,1,[v.VkSubmitInfo(commandBufferCount=1,pCommandBuffers=[self.cmd])],v.VK_NULL_HANDLE)
        v.vkQueueWaitIdle(self.queue)

    def module(self, path):
        data=path.read_bytes()
        module=v.vkCreateShaderModule(self.device,v.VkShaderModuleCreateInfo(codeSize=len(data),pCode=data),None)
        self.modules.append(module)
        return module

    def pipeline(self,path):
        fragment=self.module(path)
        stages=[v.VkPipelineShaderStageCreateInfo(stage=v.VK_SHADER_STAGE_VERTEX_BIT,module=self.vertex,pName='main'),v.VkPipelineShaderStageCreateInfo(stage=v.VK_SHADER_STAGE_FRAGMENT_BIT,module=fragment,pName='main')]
        render=v.VkPipelineRenderingCreateInfo(colorAttachmentCount=1,pColorAttachmentFormats=[v.VK_FORMAT_R32G32B32A32_SFLOAT])
        info=v.VkGraphicsPipelineCreateInfo(pNext=render,stageCount=2,pStages=stages,pVertexInputState=v.VkPipelineVertexInputStateCreateInfo(),pInputAssemblyState=v.VkPipelineInputAssemblyStateCreateInfo(topology=v.VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST),pViewportState=v.VkPipelineViewportStateCreateInfo(viewportCount=1,pViewports=[v.VkViewport(width=self.width,height=self.width,minDepth=0,maxDepth=1)],scissorCount=1,pScissors=[v.VkRect2D(offset=v.VkOffset2D(x=0,y=0),extent=v.VkExtent2D(width=self.width,height=self.width))]),pRasterizationState=v.VkPipelineRasterizationStateCreateInfo(polygonMode=v.VK_POLYGON_MODE_FILL,cullMode=v.VK_CULL_MODE_NONE,frontFace=v.VK_FRONT_FACE_COUNTER_CLOCKWISE,lineWidth=1),pMultisampleState=v.VkPipelineMultisampleStateCreateInfo(rasterizationSamples=1),pColorBlendState=v.VkPipelineColorBlendStateCreateInfo(attachmentCount=1,pAttachments=[v.VkPipelineColorBlendAttachmentState(colorWriteMask=15)]),layout=self.layout)
        pipeline=v.vkCreateGraphicsPipelines(self.device,v.VK_NULL_HANDLE,1,[info],None)[0]
        self.pipelines.append(pipeline)
        return pipeline

    def render(self,pipeline,seed):
        # Buffers are synthetic finite patterns, not recorded game uniforms.
        for _,(buffer,r) in self.descriptor_buffers.items():
            size=len(buffer[2]); data=bytearray(size)
            if r['desc']==6 and r['name'] not in ('fp_c0','support_buffer'):
                data[:]=struct.pack('<f',seed)*(size//4)
            buffer[2][:]=data
        self.begin()
        v.vkCmdResetQueryPool(self.cmd,self.queries,0,2)
        self.barrier(self.target[0],v.VK_IMAGE_LAYOUT_GENERAL,v.VK_IMAGE_LAYOUT_GENERAL,v.VK_ACCESS_TRANSFER_READ_BIT,v.VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,self.target[3])
        v.vkCmdWriteTimestamp(self.cmd,v.VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,self.queries,0)
        attach=v.VkRenderingAttachmentInfo(imageView=self.target[1],imageLayout=v.VK_IMAGE_LAYOUT_GENERAL,loadOp=v.VK_ATTACHMENT_LOAD_OP_CLEAR,storeOp=v.VK_ATTACHMENT_STORE_OP_STORE,clearValue=v.VkClearValue(color=v.VkClearColorValue(float32=[-999,-999,-999,-999])))
        v.vkCmdBeginRendering(self.cmd,v.VkRenderingInfo(renderArea=v.VkRect2D(offset=v.VkOffset2D(x=0,y=0),extent=v.VkExtent2D(width=self.width,height=self.width)),layerCount=1,colorAttachmentCount=1,pColorAttachments=[attach]))
        v.vkCmdBindPipeline(self.cmd,v.VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline)
        v.vkCmdBindDescriptorSets(self.cmd,v.VK_PIPELINE_BIND_POINT_GRAPHICS,self.layout,0,1,[self.set],0,None)
        v.vkCmdDraw(self.cmd,3,1,0,0)
        v.vkCmdEndRendering(self.cmd)
        v.vkCmdWriteTimestamp(self.cmd,v.VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,self.queries,1)
        self.barrier(self.target[0],v.VK_IMAGE_LAYOUT_GENERAL,v.VK_IMAGE_LAYOUT_GENERAL,v.VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,v.VK_ACCESS_TRANSFER_READ_BIT,self.target[3])
        region=v.VkBufferImageCopy(imageSubresource=v.VkImageSubresourceLayers(aspectMask=1,mipLevel=0,baseArrayLayer=0,layerCount=1),imageExtent=v.VkExtent3D(width=self.width,height=self.width,depth=1))
        v.vkCmdCopyImageToBuffer(self.cmd,self.target[0],v.VK_IMAGE_LAYOUT_GENERAL,self.readback[0],1,[region])
        self.submit()
        times=v.ffi.new('uint64_t[2]')
        v.vkGetQueryPoolResults(self.device,self.queries,0,2,16,times,8,v.VK_QUERY_RESULT_64_BIT|v.VK_QUERY_RESULT_WAIT_BIT)
        self.gpu_ms=((int(times[1])-int(times[0]))&self.timestamp_mask)*self.tick/1e6
        return np.frombuffer(bytes(self.readback[2]),dtype=np.float32).copy()

    def close(self):
        v.vkDeviceWaitIdle(self.device)
        for p in self.pipelines:v.vkDestroyPipeline(self.device,p,None)
        for m in self.modules:v.vkDestroyShaderModule(self.device,m,None)
        v.vkDestroyDescriptorPool(self.device,self.dp,None)
        v.vkDestroyPipelineLayout(self.device,self.layout,None)
        v.vkDestroyDescriptorSetLayout(self.device,self.setlayout,None)
        v.vkDestroySampler(self.device,self.sampler,None)
        for image,view,memory,_ in self.images:
            v.vkDestroyImageView(self.device,view,None);v.vkDestroyImage(self.device,image,None);v.vkFreeMemory(self.device,memory,None)
        for buffer,memory in self.owned:
            v.vkUnmapMemory(self.device,memory);v.vkDestroyBuffer(self.device,buffer,None);v.vkFreeMemory(self.device,memory,None)
        v.vkDestroyQueryPool(self.device,self.queries,None)
        v.vkDestroyCommandPool(self.device,self.pool,None)
        v.vkDestroyDevice(self.device,None);v.vkDestroyInstance(self.instance,None)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('before',type=Path);p.add_argument('after',type=Path);p.add_argument('work',type=Path)
    p.add_argument('--size',type=int,default=32);p.add_argument('--repeats',type=int,default=1)
    args=p.parse_args();args.work.mkdir(parents=True,exist_ok=True)
    a=prepare(args.before,args.work/'before.spv');b=prepare(args.after,args.work/'after.spv')
    if a.resources()!=b.resources():
        # Resource IDs may differ; binding layout and shapes must match.
        left=[{k:v for k,v in r.items() if k!='id'} for r in a.resources()]
        right=[{k:v for k,v in r.items() if k!='id'} for r in b.resources()]
        if left!=right:raise ValueError('resource layout differs')
    vs=vertex_shader(a,args.work/'probe.vert')
    probe=Probe(a.resources(),vs,args.size)
    try:
        pa=probe.pipeline(args.work/'before.spv');pb=probe.pipeline(args.work/'after.spv')
        result=[]
        for iteration in range(args.repeats):
            for seed in (0.0,0.5,1.0,1.5):
                start=time.perf_counter()
                outputs={};timings={}
                order=[('before',pa),('after',pb)] if iteration%2==0 else [('after',pb),('before',pa)]
                for name,pipeline in order:
                    outputs[name]=probe.render(pipeline,seed);timings[name]=probe.gpu_ms
                original=outputs['before'];changed=outputs['after']
                finite=np.isfinite(original)&np.isfinite(changed)
                difference=float(np.max(np.abs(original[finite]-changed[finite]))) if np.any(finite) else None
                equal=bool(np.allclose(original,changed,rtol=1e-5,atol=1e-6,equal_nan=True))
                row={'iteration':iteration,'seed':seed,'equal':equal,'gpu_ms':timings,'max_abs_error':difference,'finite_values':int(np.isfinite(original).sum()),'unique_finite_values':len(np.unique(original[np.isfinite(original)])),'seconds':time.perf_counter()-start};result.append(row);print(json.dumps(row),flush=True)
                np.save(args.work/f'before-{seed}.npy',original);np.save(args.work/f'after-{seed}.npy',changed)
                if not equal:raise AssertionError('fragment output mismatch')
        print(json.dumps({'device':probe.name,'scope':'synthetic descriptor-index-zero probe, not a game replay','results':result}),flush=True)
    finally:
        probe.close()


if __name__=='__main__':main()
