"""Real Vulkan memory commitment and bytes after actual NVN command promotion."""
import os
import unittest
from dm.gfx.tools.tests import test_selective_transfer_compute_gpu as sync
from dm.gfx.tools.tests.test_shader_pool_deferral import SOURCE, function, policy

@unittest.skipUnless(os.getenv('MEMU_TEST_VULKAN')=='1','real Vulkan ICD required')
class ShaderPoolGPU(unittest.TestCase):
 def test_program_only_pool_stays_out_of_gpu_and_mixed_pool_still_renders(self):
  hooks='\n'.join(function(SOURCE,'NVN('+n+',')for n in ['nvnMemoryPoolGetBufferAddress','nvnCommandBufferBindStorageBuffer'])
  runner=sync.SelectiveSyncGPU()
  # The common harness adds Vulkan paths, also add the production NVN headers.
  headers='#include "'+str(sync.ROOT/'dm/gfx/nvn/nvn_obj.h')+'"\n'
  runner.run_fixture('shader_pool_gpu',{'shader_pool_policy.inc':policy(),'shader_pool_hooks.inc':hooks,'nvn_obj.h':headers,'nvn.h':'#include "'+str(sync.ROOT/'dm/gfx/nvn/include/nvn.h')+'"\n'}, {'4096 bytes exact':2,'committed 1052672 bytes':1,'committed 4096 bytes':1},sync.COMP)
if __name__=='__main__':unittest.main()
