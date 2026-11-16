"""Ocarina GPU: tests exact VkBuffer transfer dependency replacing global flush.

Compile the exact ub_flush C implementation with a mocked Vulkan command
recorder, checking barrier parameters and unchanged fallback.  A lower CPU
test is not proof of saved Adreno GPU time; on-device GPU frames decide.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'dm/gfx/vk_android/vka_exec.c'


class BufferBarrierTests(unittest.TestCase):
    def test_scope_and_fallback_with_real_native_function(self):
        original = SOURCE.read_text()
        anchor = 'static void ub_flush(ub_batch *b) {'
        self.assertEqual(original.count(anchor), 1)
        body = original[original.index(anchor):original.index('static int ub_overlap(', original.index(anchor))]
        self.assertIn('VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER', body)
        self.assertIn('DM_VK_OOT_UB_BUFFER_BARRIER", 1', body)
        self.assertIn('vka_transfer_write_barrier(g_cb)', body)
        self.assertIn('.buffer = b->dst, .offset = 0, .size = VK_WHOLE_SIZE', body)
        # Test with the original function copied unchanged after these stubs.
        code = r"""
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t VkDeviceSize;
typedef void *VkBuffer;
typedef void *VkCommandBuffer;
typedef unsigned VkPipelineStageFlags;
typedef struct {VkDeviceSize srcOffset, dstOffset, size;} VkBufferCopy;
typedef struct {int sType;const void *pNext;unsigned srcAccessMask,dstAccessMask;
    unsigned srcQueueFamilyIndex,dstQueueFamilyIndex;
    VkBuffer buffer;VkDeviceSize offset,size;} VkBufferMemoryBarrier;
enum {VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER=11,
      VK_ACCESS_TRANSFER_WRITE_BIT=8,VK_ACCESS_MEMORY_READ_BIT=16,
      VK_ACCESS_MEMORY_WRITE_BIT=32,VK_PIPELINE_STAGE_TRANSFER_BIT=64,
      VK_PIPELINE_STAGE_ALL_COMMANDS_BIT=128,
      VK_QUEUE_FAMILY_IGNORED=~0u};
#define VK_WHOLE_SIZE (~(VkDeviceSize)0)
#define VK_NULL_HANDLE NULL
static int option=1;
static const char *DM_GAME_ID="0400486024DEC000";
#define VKA_ENV(name,value) (option)
static VkCommandBuffer g_cb;
static uint64_t g_ub_copy_cmds, g_ub_buffer_dependencies;
static int fallback, copies, barriers;
static VkBuffer copied_dst, barrier_dst;
static unsigned seen_src,seen_dst,seen_nm,seen_nb;
static VkDeviceSize seen_offset,seen_size;
static void copy_(VkCommandBuffer cb,VkBuffer src,VkBuffer dst,
                   unsigned n,const VkBufferCopy *regions) {
    (void)cb;(void)src;(void)regions;
    assert(n>0);copied_dst=dst;copies++;
}
static void barrier_(VkCommandBuffer cb,unsigned src,unsigned dst,unsigned flags,
                     unsigned nm,const void *memory,unsigned nb,
                     const VkBufferMemoryBarrier *buffers,unsigned ni,const void *images) {
    (void)cb;(void)flags;(void)memory;(void)ni;(void)images;
    barriers++;seen_src=src;seen_dst=dst;seen_nm=nm;seen_nb=nb;
    assert(nb==1 && buffers);
    assert(buffers->sType==VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER);
    assert(buffers->srcAccessMask==VK_ACCESS_TRANSFER_WRITE_BIT);
    assert(buffers->dstAccessMask==(VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT));
    assert(buffers->srcQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED);
    assert(buffers->dstQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED);
    barrier_dst=buffers->buffer;seen_offset=buffers->offset;seen_size=buffers->size;
}
static struct {
    void (*vkCmdCopyBuffer)(VkCommandBuffer,VkBuffer,VkBuffer,unsigned,const VkBufferCopy*);
    void (*vkCmdPipelineBarrier)(VkCommandBuffer,unsigned,unsigned,unsigned,unsigned,
                                 const void*,unsigned,const VkBufferMemoryBarrier*,unsigned,const void*);
} vk={copy_,barrier_};
static void vka_transfer_write_barrier(VkCommandBuffer cb) {(void)cb;fallback++;}
typedef struct {VkBuffer src,dst;unsigned n;VkBufferCopy region[64];} ub_batch;
""" + body + r"""
int main(void) {
    ub_batch b={0};
    b.src=(VkBuffer)(uintptr_t)0x1111;
    b.dst=(VkBuffer)(uintptr_t)0x2222;
    b.n=2;
    b.region[0]=(VkBufferCopy){0,4096,256};
    b.region[1]=(VkBufferCopy){256,16384,512};
    ub_flush(&b);
    assert(b.n==0 && copies==1 && barriers==1 && fallback==0);
    assert(copied_dst==barrier_dst && barrier_dst==(VkBuffer)(uintptr_t)0x2222);
    assert(seen_src==VK_PIPELINE_STAGE_TRANSFER_BIT);
    assert(seen_dst==VK_PIPELINE_STAGE_ALL_COMMANDS_BIT);
    assert(seen_nm==0 && seen_nb==1 && seen_offset==0 && seen_size==VK_WHOLE_SIZE);
    assert(g_ub_copy_cmds==1 && g_ub_buffer_dependencies==1);
    // Guest memory segmented across two buffers: one barrier per batch.
    b.dst=(VkBuffer)(uintptr_t)0x3333;b.n=1;
    ub_flush(&b);
    assert(barrier_dst==(VkBuffer)(uintptr_t)0x3333 && barriers==2);
    // Other games are unchanged, even when the option is forced on.
    DM_GAME_ID="other-title";b.n=1;ub_flush(&b);
    assert(barriers==2 && fallback==1 && b.n==0);
    // Opt out is the byte-for-byte original global barrier call.
    DM_GAME_ID="0400486024DEC000";option=0;b.n=1;ub_flush(&b);
    assert(barriers==2 && fallback==2);
    return 0;
}
"""
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'test.c'; exe=Path(d)/'test';
            src.write_text(code)
            p=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                              str(src),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    unittest.main()
