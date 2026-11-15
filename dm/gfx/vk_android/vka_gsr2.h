// Opt-in Qualcomm GSR2 temporal reconstruction of Ocarina's actual scene.
// Source: current NDSR sqrt-encoded colour; motion: optical from previous scene.
// No guest shader ABI changes, no engine motion/depth fabricated.
#pragma once
#if defined(__ANDROID__)
#include "vka.h"
int vka_gsr2_try(VkCommandBuffer cb,vka_img *src,vka_img *dst,
                 int source_is_sqrt,uint64_t frame,
                 int srcid,uint8_t srcdim,int samplerid);
#endif
