# Swap2-Native: license notice for the Android build

Swap2-Native (the Android launcher in `android/app` and the host it builds, `libnxhost.so`) is a fork of
[Banana Native](https://github.com/moceure/BananaNative) v0.1.1 by moceure (commit `d154da1`), whose Android port is based on
[nxnative](https://github.com/seedds/nxnative) by seedds. Both are MIT-licensed ([LICENSE](../LICENSE)); the repository's overview of what is MIT and what is
GPL is in [NOTICE.md](../NOTICE.md).

**The Android build that includes LSFG is GPL-3.0-or-later.** By default the host links Lossless Scaling frame generation, a C port of
[Eden](https://git.eden-emu.dev/eden-emu/eden)'s implementation (itself based on [lsfg-vk](https://github.com/PancakeTAS/lsfg-vk)), in
[`dm/gfx/vk_android/lsfg`](../dm/gfx/vk_android/lsfg/LICENSE.md), licensed GPL-3.0-or-later. An APK or `libnxhost.so` built with it is therefore distributed as a
whole under the GNU General Public License, version 3 or later ([COPYING](../dm/gfx/vk_android/lsfg/COPYING)); whoever passes such an APK on must offer its
complete source (this repository at the commit in the build tag). The MIT files keep their MIT license on their own; the rest of nxnative (the Mac and iPhone
builds) stays MIT. `./gradlew apk -PnxLsfg=false` builds an APK without LSFG; it is still GPL-3.0-or-later as a whole when it carries the on-device packer, whose translator is GPL too (below).

**The shader translator is GPL-3.0-or-later as a whole.** It translates Switch 2 task and mesh programs with
[`InstEmitAmpereMesh.cs`](../dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Instructions/InstEmitAmpereMesh.cs), ported from
[switch2mac](https://github.com/azmasm/switch2mac)'s `nx2_lower` (from [Eglantine](https://github.com/djihads80/eglantine)), GPL-3.0-or-later
([COPYING.GPL-3.0](../dm/third_party/ryujinx/COPYING.GPL-3.0)). The on-phone translator `libdmsh_xlate.so` and the Mac `dmsh_xlate_bin` are built with it, so
they are combined works under the GPL (see [dm/third_party/ryujinx/README.md](../dm/third_party/ryujinx/README.md)); the shader libraries they produce are the
games' own shaders translated, not part of this code. The other translator files keep their MIT license. Every APK that carries the on-device packer (`libdmsh_xlate.so`) is
therefore a GPL-3.0-or-later work whatever `nxLsfg` says, and the Mac and iPhone builds stay MIT only as apps: the committed translator `dm/gfx/tools/dmsh_xlate_bin` they run to
build shader libraries is the same GPL combined work.

**AMD FidelityFX Super Resolution 1** (MIT, Copyright (c) 2021 Advanced Micro Devices, Inc.): the headers `ffx_a.h` and `ffx_fsr1.h` in
[`dm/third_party/fidelityfx-fsr1`](../dm/third_party/fidelityfx-fsr1/README.md) ([LICENSE.txt](../dm/third_party/fidelityfx-fsr1/LICENSE.txt)), unmodified, are
compiled into the present's FSR 1 upscale (`dm/gfx/vk_android/fsr/`, SPIR-V in `vka_present_fsr.h` and `vka_ndsr_spv.h`). The other third-party code the
APK carries (libadrenotools, zstd, Ryujinx's shader library) is listed with its license in [dm/third_party/README.md](../dm/third_party/README.md).

Some fixes follow other projects' findings without copying their code: [kartnative](https://github.com/pahorema/kartnative) by pahorema (MIT) for
GPU-written sparse textures (`dm/gfx/vk_android/vka_tex.c`) and the per-primitive header of mesh programs (`dm/gfx/tools/shader_split.py`), and
[switch2mac](https://github.com/azmasm/switch2mac) by azmasm (MIT outside `nx2_lower`) for the SPIR-V mesh entry points marked in the translator. Thanks to them.

`Lossless.dll` belongs to Lossless Scaling (proprietary, sold separately). It is never in this repository or in an APK: the user supplies their own copy, which the
launcher finds on the phone or lets the user pick, and copies into the app's private files.

Custom GPU drivers are never in this repository or in an APK either. The launcher's **Download…** (`DriverFetch.java`) fetches a driver zip only when the user
taps it, from the public GitHub release pages of [MrPurple666/purple-turnip](https://github.com/MrPurple666/purple-turnip),
[K11MCH1/AdrenoToolsDrivers](https://github.com/K11MCH1/AdrenoToolsDrivers), [whitebelyash/freedreno_turnip-CI](https://github.com/whitebelyash/freedreno_turnip-CI),
[Weab-chan/freedreno_turnip-CI](https://github.com/Weab-chan/freedreno_turnip-CI) and [crueter/GameHub-8Elite-Drivers](https://github.com/crueter/GameHub-8Elite-Drivers);
thanks to their authors. Each download keeps its own licence: Mesa's Turnip driver is MIT-licensed, Qualcomm's Adreno driver binaries are proprietary.

## Interface art and sounds

The launcher's art and the touch-control artwork, under [`assets/artwork/swap2-native`](../assets/artwork/swap2-native) and `android/app/src/main/res`
(icons, backgrounds, drawables), are the project's own and are released with the project. The interface sounds in `android/app/src/main/res/raw` (`s2_*.wav`)
were generated with ElevenLabs Sound Effects on a paid plan that grants commercial use, and are released with the project likewise.

The Zelda-themed touch artwork (for example `s2_zelda_controls.png`) depicts Nintendo trademarks. They are used only to identify the game the layout is for;
Swap2-Native is not affiliated with, endorsed or sponsored by Nintendo. Nintendo, The Legend of Zelda, Mario Kart, Donkey Kong and Nintendo Switch are
trademarks of Nintendo.

Compute mesh emulation and texture-use feedback were ported from Banana Native (moceure/BananaNative, android d652abeb534496724e798ff96474752903d7953a). Compute mesh emulation derives from Hokkaido contributors (pavelgajdo/Hokkaido #569, #642), GPL-3.0-or-later. Texture-use feedback follows Anka Native (MIT, copyright 2026 seedds and EddizEge). Original copyright and SPDX notices are retained in the source.
