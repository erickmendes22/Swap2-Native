"""Ocarina v131072 guest frame ratio fix, validated on Swap2 V3.
No host binary hooks from V4/V5 and no V6 DRS selector replacement.
"""
from nso_asm import ADRP, B

def frame_step(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = (
        ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    )
    site = 0x6e6cc4
    fs_site(site, '2818201e')  # original fdiv s8,s1,s0
    start = here()
    emit(ADRP(16, here(), FS_STATE_OFF))
    for word in (
        0xb9400211, 0x340001b1, 0xb9402211, 0x34000171,
        0x1e230220, 0xf9401a10, 0x8b110210,
    ):
        emit(word)
    emit(ADRP(17, here(), FS_STATE_OFF))
    for word in (
        0xf9001a30, 0x1e210808, 0x52a84e10,
        0x1e270200, 0x1e201908,
    ):
        emit(word)
    emit(B(here(), site + 4))
    emit(0x1e201828)  # original fdiv s8,s1,s0 as fallback
    emit(B(here(), site + 4))
    fs_put(site, [B(site, start)],
           "Ocarina frame ratio = host frame step * base rate / 60")

FRAME_STEP = {'e0f3ccfaf50065ae4ea01eb5aeb13b1a': frame_step}
BINDING = [
    {'what': 'Ocarina guest frame ratio', 'now': 'build', 'goal': 'game',
     'purpose': 'frame rate', 'blocked': 'unvalidated other game builds',
     'checked': 'v131072 main original instruction 2818201e at +0x6e6cc4',
     'why': 'V3 tested fix; no V4/V5 native binary modifications'},
]
