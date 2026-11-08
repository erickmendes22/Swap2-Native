# Swap2-Native: biblioteca de jogos e perfis

> **Historical (2026-11-08):** this page describes the runtime from before the restart from Banana Native on 2026-11-04 (`runtime/`, `profiles/`, which no longer exist). The current app is described in [android/README.md](../android/README.md) and [android/LIBRARY.md](../android/LIBRARY.md).

O MKWDroid passou a se chamar **Swap2-Native**: o mesmo runtime, preparado para rodar qualquer jogo de Switch 2 que o
jogador tenha, cada um com seu perfil. Este documento descreve a estrutura que existe hoje e o que ainda falta.

## Pasta de jogos

O jogador escolhe uma pasta com uma subpasta por jogo, com qualquer nome:

```
Jogos/
  Mario Kart World/
    ExeFS/            main, main.npdm, sdk, rtld, subsdk0...   (exefs/ também serve: maiúsculas não importam)
    RomFS/            os arquivos do jogo
  Donkey Kong Bananza/
    ExeFS/
    romfs.bin         a RomFS numa imagem só, no lugar de RomFS/ (preferida quando as duas existem)
  DKB (dump)/
    base/exefs/  base/romfs/   o formato das ferramentas de dump: um nível abaixo, com updates/<versão>/ e dlc/ ao lado
    updates/1.1.0/exefs/       outra versão do jogo: o ExeFS dela
    updates/1.1.0/romfs/       ... e os arquivos que ela muda (por cima da RomFS da base), ou um romfs.bin inteiro
```

`runtime/library.c` acha o jogo em cada subpasta (nela, em `base/` ou um nível abaixo), lê o program id e a plataforma
do `main.npdm`, o build id do `main`, e o nome (do perfil, senão do `control.nacp` do dump, senão o nome da pasta). Um
jogo com algo faltando aparece na lista com o motivo.

**O jogo roda de onde está**: nada é copiado e não há recompilação. O código do próprio jogo roda nativo na CPU
(`runtime/native.c`), o ExeFS é lido da pasta do jogador e a RomFS também (uma pasta vira uma imagem virtual, sem cópia;
um `romfs.bin` é lido direto).

## Versões

Cada jogo pode ter várias versões: a base e cada `updates/<nome>/` que tenha um `exefs/`. A versão é uma configuração do
próprio jogo (`version = <nome>` no arquivo dele; sem a chave, a base) e se escolhe na biblioteca, no botão "Versão" do
jogo selecionado. O nome mostrado é o do perfil para o build daquela versão (`[builds]`), senão o da pasta.

- O ExeFS é o da versão; a RomFS é a `romfs/` dela por cima da `romfs/` da base (o arquivo que a versão tem vence, o
  resto vem da base: `romfs_virtual_open_over`), ou o `romfs.bin` dela inteiro. Uma versão sem dados próprios usa a
  RomFS da base. Uma `romfs/` de versão por cima de um `romfs.bin` da base não é aceita.
- Os filmes (abertos por caminho) vêm da `romfs/` da versão, senão da base.

## Configurações: geral e do jogo

Como no Eden: uma configuração geral para todos os jogos e, para cada jogo, só o que for diferente para ele.

| Arquivo | O quê |
|---|---|
| `<dados do app>/swap2native.ini` | a configuração geral |
| `<dados do app>/games/<program id>/swap2native.ini` | a do jogo: só as chaves que diferem da geral (e do perfil) |

A ordem de leitura é: os padrões do app, a geral, o `[settings]` do perfil do jogo, a do jogo. Ao salvar dentro de um
jogo, o arquivo dele recebe só o que difere da geral com o perfil. Uma mudança que volta ao valor geral sai do arquivo, e
um arquivo sem nada próprio é apagado.

- **Na biblioteca**, a engrenagem do topo abre a configuração geral, e a engrenagem ao lado de Jogar abre a do jogo
  selecionado. Uma faixa acima das configurações diz qual delas está aberta; na do jogo há "Usar a configuração geral",
  que apaga a dele.
- **Dentro do jogo**, o menu edita a configuração daquele jogo.
- **Do app, sempre na geral**: idioma, os avisos de primeira vez (`aspect_asked`, `menu_tip_seen`), o log, a GPU e as
  opções do Turnip, e os botões do controle físico (`bind_*`).
- API: `settings_set_game`, `settings_scope(id)` / `settings_scope_active`, `settings_game_get` / `_set` /
  `_use_general` (`runtime/settings.h`).

## Pasta de dados de cada jogo

Cada jogo tem a sua: `<dados do app>/games/<program id>/` (no Android, `Android/data/com.mkwdroid/files/games/...`).
Ao jogar, essa pasta vira a raiz de dados, então tudo o que o runtime já abria por nome relativo passa a ser do jogo:

| Arquivo | O quê |
|---|---|
| `swap2native.ini` | a configuração própria do jogo (só o que difere da geral) |
| `save/`, `cache/`, `mods/` | saves, cache de shaders e pipelines, mods |
| `profile.ini`, `patches/` | as mudanças do próprio jogador no perfil |

Na raiz do app ficam `library.txt` (a pasta de jogos), `last_game.txt` (o jogo da próxima abertura) e `profiles/` (os
perfis que vêm com o app). O jogo que já estava copiado em `extracted/` na raiz (de antes da biblioteca) continua
jogável como um card "Instalado"; o app não copia mais nada.

O `mkwdroid.ini` antigo vira `swap2native.ini` na primeira abertura.

## Perfis

Um perfil por program id: `profiles/<program id>/profile.ini` e `profiles/<program id>/patches/`. A pasta `profiles/`
do repositório é compilada dentro do `libmain.so` (o CMakeLists gera uma tabela) e escrita em `<dados do app>/profiles`
na abertura, onde o jogador também pode pôr perfis de jogos que o app não traz. As mudanças do jogador vão no
`profile.ini` da pasta do jogo (as mesmas chaves), nunca no arquivo que vem com o app, que é reescrito.

Modelo completo: `profiles/_example/profile.ini` (do runtime antigo).

| Seção | Para quê | Quem lê |
|---|---|---|
| `[game]` | `name`, `short_name`, `platform` (`switch2` / `switch`) | a lista de jogos |
| `[builds]` | `<build id do main, hex, 8+ dígitos> = <versão>` | a lista de jogos |
| `[touch]` | `hide = L3, R3, DPAD`; `<controle> = x, y` (fração da tela, o layout do jogador ainda vence); `label.<controle> = texto`; `layout = race / action` (o layout próprio do jogo, oferecido na aba Controles); `race_shaders = <hash>, ...` (quando mostrar o layout de corrida) | `ui/touch_controls.mm` |
| `[settings]` | padrões do jogo para as chaves das configurações (`frame_rate`, `resolution`, `touch_profile`...) | `runtime/settings.c`, entre a geral e a do jogo |
| `[optimize]` | chaves `LARECOMP_*` postas no ambiente antes do jogo iniciar (se já não estiverem) | `runtime/library.c` |
| `[patches]` | `<arquivo> = on / off` (sem a linha: ligado) | `runtime/patches.c` |

Os controles se chamam `A B X Y L ZL R ZR MINUS PLUS MENU LSTICK RSTICK L3 R3 UP DOWN LEFT RIGHT` (e `DPAD` para os
quatro direcionais). O "Restaurar padrões" do menu volta aos padrões do perfil.

### Layout touch de corrida

`touch_profile = race` no `[settings]` de um perfil (o do Mario Kart World já traz) troca o layout de controle pelo de
corrida (`runtime/ui/touch_controls.mm`, do runtime antigo). Na aba
Controles o jogador escolhe Controle ou Corrida, a aceleração automática e volante ou setas.

| Controle | Botão | Notas |
|---|---|---|
| Volante | analógico esquerdo inteiro | centro fixo onde ele descansa; a tampa acompanha o dedo e gira um pouco |
| Acelerar / Freio | A / B | retângulos; com a aceleração automática o pedal some, imagem e área de toque |
| Drift / Pulo | R | duas superfícies do mesmo botão: R fica até soltar as duas |
| Item, Retrovisor | L, X | |
| Pausa / Menu do app | + / menu do Swap2-Native | ações separadas |
| Extras (...) | | painel: mapa (Y), foto (−), rebobinar (↓), reiniciar (L3), área de câmera, layout de controle |
| Setas (opção) | eixo X do analógico | as duas juntas: reto |

- **Aceleração automática** (`touch_auto_accel`; não é a do jogo): o botão do pedal no alto arma e desarma a
  condução, e um ponto cheio ou vazado mostra o estado. Armada, os controles seguram A; o freio suspende A enquanto
  está apertado. Pausa, menus, editor, controle físico, app em segundo plano, troca de layout e o início do jogo
  desarmam. Ao pausar, A é solto um quadro antes do +.
- **Só dirigindo**: `race_shaders` no `[touch]` do perfil lista fragment shaders do HUD da corrida (o hash do
  renderer, o mesmo do `LARECOMP_LOG_FSSEEN`). O layout de corrida aparece enquanto um deles desenhou nos últimos 15
  quadros; fora disso (título, menus, pausa, resultado) fica o de controle, e a aceleração automática desarma. Sem a
  chave, o layout de corrida fica sempre. O editor mostra o layout escolhido na aba Controles, dirigindo ou não.
  No Mario Kart World é o `72708a573abfd3f2`, que gera as mips do alvo 588x588 do minimapa (histórico de pixel do
  círculo do minimapa, 2026-11-02). O `f338eddddc511b9f`, que põe o círculo na tela, não serve: ele também desenha o
  fundo desfocado do menu de pausa. Conferido no POCO: clássico no título, no menu e na pausa; de corrida no modo
  livre (volta ~1 s depois de retomar). Num boot lento (2-4 fps) o layout só liga quando o minimapa começa a ser
  desenhado.
- **Botões**: recompostos a cada quadro a partir dos dedos (`runtime/ui/touch_race.h`, testado por
  `tools/test_touch_race.c`). Um controle que some debaixo de um dedo para de contar.
- **Layouts**: o de controle (`touch_layout`, intocado), o de corrida manual (`touch_race_layout`) e o automático
  (`touch_race_layout_auto`), salvos pelo nome de cada controle (formato `1;nome=x,y[,tamanho];...`). O editor e
  "Restaurar layout" mexem só no que está na tela.
- **Tamanho de cada botão**: no editor, toque num controle (contorno amarelo) e use − / + na barra, de 50% a 200% em
  passos de 10%, por cima do "Tamanho dos botões" geral. Vale para os dois layouts (`touch_sizes` no de controle).
- **Artes**: `assets/artwork/mkwdroid-touch-race-{primary,extra}-v2.png` (1254²), com os limites de cada desenho medidos
  na tabela `race_bounds`. Sem as folhas, formas simples com legenda.
- **Ainda não conferido no jogo**: se o MKW usa esse mapeamento (A, B, R, L, X, Y, −, ↓, L3) na versão 1.0.0; o lançamento
  de itens para trás e para os lados pelo volante; se segurar A na tela de resultado avança sozinho (desarme ao fim
  da corrida); as posições em 16:9 e 20:9 contra o HUD; e o teste no aparelho.

### Layout touch de ação

`touch_profile = action` (o perfil do Donkey Kong Bananza já traz, com `layout = action` no `[touch]` e a câmera por
arrasto) é o layout de [SWAP2-NATIVE-BANANZA-TOUCH-v1.md](SWAP2-NATIVE-BANANZA-TOUCH-v1.md), no mesmo arquivo. Cada botão
é o do jogo: o que ele faz no chão, no ar, segurando um pedaço ou transformado é o jogo que decide. Nada de turbo, de
botão segurado pelos controles ou de transformação adivinhada por tempo.

| Controle | Botão | Notas |
|---|---|---|
| Movimento | analógico esquerdo | centro fixo onde ele descansa |
| Soco, Pulo, Soco para cima, Soco para baixo | Y, A, X, B | |
| Agarrar / arremessar, Rolar, Palma, Música | ZR, ZL, R, L | seguram enquanto o dedo fica |
| Bananza | L + R | um dedo segura os dois; soltar a Música ou a Palma em outro dedo não solta o L+R, e vice-versa |
| Pausa / Menu do app | + / menu do Swap2-Native | |
| Extras (...) | | painel: mapa (−), habilidades (↑), foto (↓), forma anterior / seguinte (← / →), layout de controle |
| Câmera | analógico direito | um dedo na parte livre da tela à direita do analógico, fora dos botões: por arrasto (`touch_drag_camera`) ou como analógico onde o dedo cai |

- **Botões**: cada controle tem um conjunto de botões, e o que vai ao jogo é a soma dos dedos a cada quadro
  (`runtime/ui/touch_action.h`, testado em `tools/test_touch_race.c`).
- **Câmera**: "Inverter a câmera para cima / baixo" (`touch_camera_invert`) vale para a câmera do toque em todos os
  layouts; a sensibilidade é a da câmera por arrasto.
- **Layout salvo**: `touch_action_layout` (formato `1;nome=x,y[,tamanho];...`, nomes em `g_touch_action_names`),
  `touch_action_extras` (painel aberto). Os 19 índices antigos (`touch_layout`, `touch_sizes`) não mudaram.
- **Artes**: `assets/artwork/swap2-native/bananza/bananza-touch-buttons-v1.png` (1254², 4 x 4, limites na tabela
  `action_bounds`); a letra de cada botão é desenhada por baixo, numa pílula. Analógicos e extras são desenhados
  nas cores do kit.
- **Ainda não conferido**: o jogo ainda não roda, então nada disso foi visto no Bananza. O mapeamento segue o guia de
  controles, sem conferência no jogo.

## Patches

Os formatos que a comunidade já usa, aplicados a cada módulo (`main`, `sdk`) logo depois de carregado e antes da
relocação, como o loader do console:

- **`.pchtxt`** (IPSwitch, o do yuzu / Eden / Ryujinx): `@nsobid-<build id>`, `@flag offset_shift 0x100`,
  `@enabled` / `@disabled`, linhas `<offset> <bytes em hex>` ou `<offset> "texto"`, `@stop`.
- **`.ips`** (exefs_patches do Atmosphère): IPS ou IPS32, o arquivo com o nome do build id do módulo.

Exemplo (mudar o minimapa de lugar): `profiles/_example/patches/move_minimap.pchtxt` (do runtime antigo).
O código do jogo roda sempre nativo, então os patches de código sempre valem.

## Como um jogo começa

1. `main.c`: `rt_paths_init`, depois `library_startup`: o jogo de `--game <pasta>` / `LARECOMP_GAME=<pasta>`, senão o
   de `last_game.txt`, senão o `extracted/` da raiz.
2. `library_activate`: a pasta de dados do jogo vira a raiz, o perfil e as configurações (geral, perfil, do jogo) são
   lidos, e a versão escolhida nelas define o ExeFS e a RomFS. Depois, `[optimize]` vai para o ambiente.
3. O launcher abre na biblioteca; `boot()` carrega os módulos da pasta do jogador (com os patches), abre a RomFS dela
   e inicia, sempre com o código nativo.

Trocar de jogo reinicia o app (`MKWDroidActivity.restartApp`), para que o `[optimize]` e o driver valham desde o
começo.

**Trocar o driver Vulkan** (Configurações > Driver Vulkan na tela inicial) não pede mais "Reiniciar agora": o driver
escolhido vale quando o jogo começa, como no Eden (lá, `DriverViewModel.onLaunchGame` instala o driver escolhido e
`InitializeGpuDriver` o abre de novo pelo adrenotools a cada jogo; a instância e o device Vulkan são refeitos por
emulação). Aqui o driver é carregado uma vez por processo (`android_driver.c`, antes do device que o launcher já usa),
então o JOGAR seguinte, com um driver escolhido desde o início, faz o que o JOGAR em outro jogo faz: grava o
`play_next` e reinicia direto no jogo (`library_ui_restart_into_active`), já com o driver novo.

**Um driver por jogo**: a chave `vk_driver` das configurações (`""` = o primeiro pacote instalado, ou o do sistema se não
houver; `system`; ou o nome de um pacote, sem a extensão). Como qualquer outra, ela pode ser geral ou do jogo (o
arquivo do jogo guarda só o que difere), e o perfil do jogo pode trazer uma em `[settings]`. A seção Driver Vulkan da
tela inicial mostra "Driver de todos os jogos" nas configurações gerais e "Driver deste jogo" nas do jogo (com "Igual às
configurações gerais"), uma linha por pacote instalado e "Adicionar driver". Os pacotes ficam todos em
`<arquivos externos>/drivers` (instalar um não apaga os outros); a activity desempacota todos ao iniciar
(`MKWDroidActivity.unpackDrivers`) e passa a lista em `LARECOMP_VK_DRIVERS`; o `android_driver.c` escolhe o do jogo
antes de carregar. Recuperação (o atalho "Escolher driver" do ícone e a janela de erro de driver): o pacote escolhido ali
vale nessa abertura, vira o driver geral e tira o do jogo (`files/driver_pick`, `LARECOMP_VK_DRIVER_PICK`). Um teste que
passa `LARECOMP_VK_DRIVER` na intent continua mandando (`LARECOMP_VK_DRIVER_FIXED`). Ainda não há como remover um pacote
pela tela (só "Driver do sistema" no atalho, que apaga todos).

Trocar dentro do processo, sem processo novo, foi avaliado e deixado de lado por enquanto: além do device, do swapchain
e do ImGui, o `exec.c` guarda a numeração das submissões da timeline, o anel de memória temporária, o buffer de leitura
e vários objetos criados sob demanda; refazer o device deixando um deles para trás trava ou fecha o app. Só valeria
antes do primeiro boot do processo e com um reset completo do `exec.c`.

## Launcher

A biblioteca é a primeira tela (`runtime/ui/library_ui.mm`, com o visual de
[SWAP2-NATIVE-VISUAL-v1.md](SWAP2-NATIVE-VISUAL-v1.md)): marca, Trocar pasta, Atualizar e configurações no topo; um card
por jogo (a capa do jogador, senão um placeholder com a inicial), o selecionado com o nome, a versão ou o problema, e
JOGAR ao lado. Estados: primeira abertura, buscando jogos, pasta sem jogos, pasta que não abre (o Android tirou o acesso
ou ela mudou de lugar). A busca roda numa thread; a seleção e a rolagem ficam ao voltar das configurações ou do jogo.

- **Capas**: `cover.png` (ou `icon.png`) na pasta do jogo ou na pasta de dados dele. Os ícones JPEG dos dumps
  (`icon_*.dat`) ainda não, porque o app não tem decodificador JPEG.
- **O jogo instalado no app** (o `extracted/` da raiz, de antes da biblioteca) aparece como um card "Instalado". A tela
  antiga de preparar e copiar arquivos não é mais aberta por nada (o código dela ainda está no `launcher.mm`).
- **Versão** e **configuração do jogo**: dois botões ao lado de Jogar (ver as seções acima).
- **JOGAR** num jogo que não é o carregado: `library_choose`, `<dados do app>/play_next` e o app reinicia; na abertura
  seguinte o launcher acha o `play_next` e joga direto (com as perguntas de primeira vez, se faltarem).
- **Configurações** voltam para a biblioteca, com o fundo do kit atrás.
- Desenho: formas, ícones e texto desenhados em ImGui (nítidos em qualquer densidade), com as cores e medidas do
  `tokens.json`. Do kit entram no APK só o fundo, a ilustração da pasta e o símbolo (`build.gradle.kts`, como
  `assets/res/swap2-*.png`); os PNGs 1x dos componentes não são usados.
- **Pré-compilação** (`library_ui_compile_draw`, com o visual de SWAP2-NATIVE-SHADERS-VISUAL-v2.md): o card do jogo
  à esquerda (a capa da biblioteca do jogo ativo, senão o símbolo; "Jogo selecionado" se não houver nome) e à direita
  o painel: etapa, percentual (`floor(100 * done / total)`, limitado), barra, "N de T itens processados" e um spinner
  pequeno. Sem total: barra indeterminada, sem percentual. `done >= total` ainda em andamento: "Finalizando
  preparação", Pular desativado e Voltar/B não pula. Em tela estreita o card vira uma linha acima do painel; em altura
  baixa encolhem só os espaços. A página continua aparecendo só a partir de 0,5 s (`launcher.mm`). Ainda não
  conferida no aparelho.
- A tela antiga do MKW (`MAIN`) continua no código, só para testes (`LARECOMP_LAUNCHER_SHOT=<n>:main`).
- O launcher aceita como pronto um jogo da biblioteca com qualquer build (o perfil diz quais ele conhece), lendo o
  ExeFS e a RomFS da pasta do jogador.

Falta: retrato (o app é só paisagem hoje), busca por título quando houver muitos jogos, movimento reduzido (só o
spinner anima), o ícone do app a partir do `brand/app-icon.svg` e capturas no aparelho comparadas com os conceitos.

## O que ainda falta para ser genérico

- **Nome do pacote**: `com.mkwdroid`, a classe `MKWDroidActivity`, `android/mkwdroid/` e as funções JNI
  `Java_com_mkwdroid_*` continuam. Trocar o pacote instala um app novo (dados e caches em outro lugar) e mexe no
  `build.gradle.kts` e no `launcher.mm` do outro agente, então fica para uma troca combinada. A tag do logcat
  (`MKWDroid`) também, porque os scripts de teste dependem dela. O nome visível do app já é Swap2-Native.
- **Código específico do MKW no runtime**: cerca de 30 testes de `g_game_version` / program id (`loader.c`,
  `nvn/objects.c`, `hle/framepace.c`, `hle/widescreen.c`...), herdados do TOTK e do MKW. Devem virar chaves de perfil
  conforme outros jogos rodarem.
- **DLC**: a pasta `dlc/` é achada, mas não usada.
- **Código antigo de cópia e recompilação**: não é mais chamado, mas ainda está no repositório (`gamebuild.c`,
  `gamelib.c`, a tela SETUP e o `extract_thread` do `launcher.mm`, `tools/gen.py`...). Sai numa limpeza à parte.
- **Filmes de um `romfs.bin`**: abertos por caminho, eles só existem numa `romfs/` em pasta; um jogo com `romfs.bin` fica
  sem os filmes até o player de vídeo ler de dentro da imagem.
