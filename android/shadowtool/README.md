# Ocarina Shadow Tool 0.3 — Android (.nup via Arquivos)

Aplicativo Android independente, com pacote `com.swap2native.ocarina.shadowtool`. Lê o NUP pelo seletor **Arquivos**, sem root, sem Termux e sem modificar o NUP original.

## Correção confirmada pelo diagnóstico da base v65536

O relatório `Ocarina-shadow-diagnostico (1).txt` identificou no RomFS o arquivo:

`gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml`

Os campos verdadeiros da configuração de gameplay são:

| Campo no Main | Original | Padrão | Baixo |
|---|---:|---:|---:|
| `DepthShadowTexWidth` | 1024 | 512 | 256 |
| `DepthShadowTexHeight` | 1024 | 512 | 256 |
| `StaticSdwWidth` | 4096 | 2048 | 1024 |

O código v0.1–0.2 bloqueava o patch porque só aceitava nomes genéricos como `CreateDepthShadow`; a configuração real do jogo utiliza os três nomes acima. Os testes usam um BYML sintético reproduzindo os nomes e valores do relatório. Eles **não substituem** um teste no NUP real e no renderizador.

**Não modificar:** `OcclusionQueryNum = 4096`, `CubemapMaxShapeNum = 4096`, `DepthShadowCascadeNum0` e `ModelSceneConfigParam/UI`. A configuração UI do arquivo real define mapas de profundidade de 4096, diferentes do Main, e fica intacta nesta versão.

## Como usar

1. Instalar o APK **Ocarina Shadow Tool** produzido nas Actions desta branch.
2. Selecionar o arquivo `.nup` pelo aplicativo **Arquivos** do Android.
3. Escolher `Base v65536` e tocar em **Analisar mapas de sombra**. O scanner lê diretamente o índice RomFS e, quando encontra `Main`, interrompe a busca sem tentar milhares de packs não relacionados.
4. Escolher **512 / 2048** ou **256 / 1024** e selecionar uma pasta de saída. O app salva um overlay no caminho `gsys/ModelSceneConfigParam/Main.gsys__ModelSceneConfigParam.bgyml`, dentro da pasta escolhida.
5. O overlay **ainda precisa ser aplicado ao emulador**. A ferramenta não altera o jogo instalado e não injeta o arquivo automaticamente.

Se os valores, nomes, tipos ou estrutura do arquivo selecionado diferirem, a criação do patch é bloqueada. O NUP original nunca é sobrescrito.

## Limitações

- O mapeamento dos três campos foi observado no **NUP base v65536**. Outras versões exigem confirmação dos respectivos parâmetros; a ferramenta falha em vez de alterar valores não verificados.
- O fato de gerar um overlay não comprova que o emulador o carregou nem que o FPS melhorou. Isso exige teste de jogo comparando a mesma cena.
- Se a pasta de destino já tiver o mesmo overlay, a ferramenta não sobrescreve o arquivo existente.
- O APK é separado do Swap2-Native; não modifica controles, shaders, opção A+B, perfil de vegetação ou a versão principal do emulador.
- A pesquisa de arquivos de packs continua disponível como fallback quando o `Main` não aparece como recurso direto. O fallback é limitado por contagem e tamanho.

## Compilar e testar

Na raiz do repositório:

```bash
android/app/gradlew --no-daemon -p android/shadowtool :testDebugUnitTest :assembleDebug
```

O workflow [Ocarina Shadow Tool — Android APK](../../.github/workflows/ocarina-shadowtool-android-apk.yml) executa os testes da reescrita BYML, compila um APK e publica `Ocarina-Shadow-Tool-Android-APK` como artefato.
