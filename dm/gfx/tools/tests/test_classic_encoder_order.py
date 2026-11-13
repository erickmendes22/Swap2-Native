"""Real production encoder regression for the missing classic-pass wrappers.

50,000 passes exceed the ring capacity. Poison caller arrays before publication.
A negative control restores the bypassed raw begin/end pointers from APK134.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
VK=ROOT/'dm/gfx/vk_android'

class ClassicEncoder(unittest.TestCase):
    def test_real_worker_order_ownership_copies_and_negative_control(self):
        source=(VK/'vka_enc.c').read_text()
        # Use the real ring, worker, serializers, dispatch and synchronization.
        # Only Android's platform include is adapted to a Linux host shim.
        names=set(re.findall(r'X\((vk\w+)\)',source[source.index('#define ENC_FNS'):source.index('#define ENC_ID')]))
        names.update(('vkCmdBeginRenderPass','vkCmdEndRenderPass'))
        shim='''#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
int test_env(const char *,int);
#define VKA_ENV(k,v) test_env(k,v)
#define VLOG(...) ((void)0)
#define VRED(...) fprintf(stderr,__VA_ARGS__)
int vka_nan_on(void);
uint64_t vka_host_fp(const char *);
void vka_enc_sync(void);
static struct {\n'''+''.join('PFN_'+n+' '+n+';\n' for n in sorted(names))+'} vk;\n'
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'encoder_test_shim.h').write_text(shim)
            (p/'encoder_under_test.c').write_text(source.replace('#include "vka.h"','#include "encoder_test_shim.h"',1))
            exe=p/'encoder'
            subprocess.run(['cc','-std=gnu11','-D_GNU_SOURCE','-D__ANDROID__','-O1','-g','-fsanitize=address,undefined','-I',str(p),'-I',str(ROOT/'dm/third_party/vulkan-headers/include'),str(ROOT/'dm/host/tests/t_android_encoder_classic.c'),'-lpthread','-o',str(exe)],check=True,capture_output=True)
            good=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(good.returncode,0,good.stdout+good.stderr)
            self.assertIn('200000 commands',good.stdout)
            import os
            bad=subprocess.run([str(exe)],env=dict(os.environ,ENC_NEGATIVE='1'),capture_output=True,text=True,timeout=30)
            self.assertNotEqual(bad.returncode,0,bad.stdout+bad.stderr)
            print(good.stdout+'negative control (APK134 raw begin/end): '+bad.stdout)
