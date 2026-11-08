# Swap2-Native: license notice

Swap2-Native is a fork of [Banana Native](https://github.com/moceure/BananaNative) v0.1.1 by moceure (commit `d154da1`), whose Android port is based on
[nxnative](https://github.com/seedds/nxnative) by seedds. The repository is licensed file by file:

- **MIT by default.** Every file without a different license header or license file in its folder is MIT ([LICENSE](LICENSE): Swap2-Native contributors,
  moceure, seedds). MIT files stay MIT, also when they are built into a GPL work.
- **GPL-3.0-or-later parts**, confirmed by their headers and license files:
  - [`dm/gfx/vk_android/lsfg/`](dm/gfx/vk_android/lsfg/LICENSE.md): Lossless Scaling frame generation, ported from Eden (based on lsfg-vk): `lsfg.h`,
    `lsfg_chain.c`, `lsfg_dll.c`, `lsfg_pacer.c` (`SPDX-License-Identifier: GPL-3.0-or-later`), with [COPYING](dm/gfx/vk_android/lsfg/COPYING).
  - [`dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Instructions/InstEmitAmpereMesh.cs`](dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Instructions/InstEmitAmpereMesh.cs):
    the Switch 2 task / mesh lowering, ported from switch2mac's `nx2_lower` (from Eglantine), with
    [COPYING.GPL-3.0](dm/third_party/ryujinx/COPYING.GPL-3.0). The shader translator built with it (the on-phone `libdmsh_xlate.so`, the committed
    `dm/gfx/tools/dmsh_xlate_bin`) is a GPL-3.0-or-later combined work.
- **The APK as a whole is distributed under GPL-3.0-or-later**, because it links LSFG and carries the on-device packer's translator. Whoever passes an APK on
  must offer its complete source (this repository at the commit in the build tag). Details: [android/NOTICE.md](android/NOTICE.md).
- **Third-party code** keeps its own license, listed in [dm/third_party/README.md](dm/third_party/README.md) with each license file in its folder: AMD
  FidelityFX FSR 1 (MIT), libadrenotools and liblinkernsbypass (BSD 2-Clause; `libadrenotools/src/hook/kgsl.h` is a Linux kernel interface header,
  `GPL-2.0 WITH Linux-syscall-note`), zstd (BSD, dual-licensed with GPLv2, used under BSD), libvpx, FLIP, stb_vorbis, Vulkan-Headers and Ryujinx's shader
  library (MIT outside `InstEmitAmpereMesh.cs`).
- **Interface art and sounds** are the project's own, released with it; the Zelda-themed touch artwork depicts Nintendo trademarks for identification only
  ([android/NOTICE.md](android/NOTICE.md#interface-art-and-sounds)). Swap2-Native is not affiliated with Nintendo.

No game files, keys, `Lossless.dll` or GPU driver binaries are part of this repository or of an APK.
