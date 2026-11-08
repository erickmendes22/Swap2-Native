# Ícone Android v2 — integração para Claude

Integrar a arte aprovada usando `assets/artwork/swap2-native/icon/android-v2/res/` em `android/mkwdroid/app/src/main/res/`. Este pacote é um handoff; ainda não aplicado ao APK.

| Densidade | Launcher legado, px | Camadas adaptativas, px |
|---|---:|---:|
| mdpi | 48×48 | 108×108 |
| hdpi | 72×72 | 162×162 |
| xhdpi | 96×96 | 216×216 |
| xxhdpi | 144×144 | 324×324 |
| xxxhdpi | 192×192 | 432×432 |

Cada mipmap contém `ic_launcher.png` e `ic_launcher_round.png`. Cada drawable contém `swap2_icon_foreground.png` com alpha e `swap2_icon_monochrome.png`, silhueta branca com alpha para receber a cor do tema. O foreground foi derivado da arte aprovada com ImageGen. Os exports usam Pillow/Lanczos. O símbolo cabe em 60 dp centrais da camada de 108 dp; fundo adaptativo #0B1020. A versão temática perde os relevos e cores por definição.

Os XMLs v26 usam foreground/background; v33 acrescenta monochrome. Ambos os nomes de launcher usam o mesmo adaptive icon; o sistema aplica a máscara. Os PNGs redondos são fallbacks legados. `store/swap2-native-512.png` é a exportação opaca de 512×512 da arte aprovada, separada dos recursos do APK.

Referência: [Android Developers — adaptive icons](https://developer.android.com/develop/ui/compose/system/icon_design_adaptive).

## Integração

1. Mesclar `res/` do pacote na pasta de recursos do app, substituindo o antigo `mipmap-anydpi-v26/ic_launcher.xml` e adicionando os demais arquivos. Preservar os outros recursos.
2. O Manifest já contém `android:icon="@mipmap/ic_launcher"`. Manter e acrescentar `android:roundIcon="@mipmap/ic_launcher_round"` ao elemento `application`.
3. Auditar referências aos antigos `@drawable/ic_launcher_foreground` e `@color/ic_launcher_background`, inclusive shortcuts. Os novos usam nomes `swap2_icon_*`. Remover os antigos somente quando não houver referências.
4. Preservar nome Swap2-Native e package ID atual. Ícones de notificação não fazem parte desta entrega.

## Verificação

- Conferir dimensões/alpha pelo `manifest.json` e `preview-masks.png` (círculo, squircle e quadrado). O preview é uma simulação estática, não validação no launcher.
- Compilar o APK debug pelo Gradle, verificando resolução dos recursos e ausência de conflitos.
- Coordenar testes no aparelho com o teste em andamento antes de instalar/reiniciar. Conferir tela inicial, lista de apps, Configurações, máscaras disponíveis e ícones temáticos habilitados/desabilitados quando suportados. Símbolo inteiro, sem quadrado na camada monochrome e legível em tamanho pequeno.
- Registrar build e testes realmente feitos. Não limpar dados do jogador para atualizar cache do launcher.

## Reprodução

`tools/export_swap2_android_icon.py` recebe o foreground transparente como primeiro argumento e grava apenas o pacote de arte. Arte/cutout: ferramenta integrada ImageGen; prompts no README do ícone. ZIP: `output/design/Swap2-Native-Android-Icon-v2.zip`.
