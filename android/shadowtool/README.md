# Ocarina Shadow Tool 0.2 — aplicativo Android independente

Aplicativo Android `com.swap2native.ocarina.shadowtool` para selecionar um **NUP** usando o aplicativo Arquivos do Android. Não exige root, Termux, Python, nem acesso amplo ao armazenamento. O NUP é aberto **somente para leitura**.

## Fluxo

1. Abrir o aplicativo e tocar em **Selecionar arquivo .nup**.
2. Escolher uma base ou atualização do Ocarina (Title ID `0400486024DEC000`) contida no NUP.
3. Tocar em **Analisar mapas de sombra**. A versão 0.2 percorre o índice **RomFS completo** da versão selecionada, incluindo recursos da base quando ela está no mesmo NUP. Procura arquivos `ModelSceneConfigParam` diretos e, na ausência deles, pesquisa os arquivos `Pack/*.pack.zs` (limites seguros de RAM, tamanho e contagem).
4. O relatório mostra o caminho do recurso encontrado, packs tentados e falhas, campos legíveis e valores 1024/4096 **somente como candidatos de diagnóstico**, não como autorização automática para patch.
5. **Somente** se campos de largura/altura/resolução no `CreateDepthShadow` e `CreateStaticDepthShadow` forem identificados sem ambiguidades, o aplicativo libera o overlay 512/2048 ou 256/1024. Se estiverem sob chaves hash não identificadas, a alteração continua bloqueada.
6. Selecionar uma pasta para exportar. O arquivo corrigido usa **o mesmo caminho RomFS do recurso de origem**. O NUP original jamais é modificado.

O app já consegue gerar um overlay de um `.bgyml` direto e sem compressão ou de um SARC `.pack.zs` com dicionário reconhecido. Não presume que o arquivo esteja em `Bootup.Nin_Ounce_NVN2.pack.zs`.

## O que o diagnóstico inicial demonstrou

O arquivo `Ocarina-shadow-diagnostico.txt` exportado pelo 0.1 apontou a base `v65536`: no Bootup inspecionado **não existe** `ModelSceneConfigParam/Main`. O programa 0.1 restringia sua inspeção a esse pack e, por isso, não provava a ausência da configuração em outros recursos.

A versão 0.2 foi criada para localizar o **recurso verdadeiro** antes de permitir a substituição. O fato de o código identificar caminhos candidatos não demonstra que a redução de 1024/4096 já funcionou no jogo. O emulador precisa usar o overlay para que haja qualquer mudança, e o ganho de FPS continua dependendo de teste em gameplay.

## Limitações e segurança

- A ferramenta **não injeta** o overlay no Swap2-Native, não altera as opções A+B de vegetação e não modifica shaders.
- Pacotes grandes, NUP sem a base necessária, arquivos comprimidos em formato ainda não suportado e campos hash/ambíguos podem permanecer sem patch; o relatório explica o bloqueio.
- Se o NUP contiver apenas a atualização, mas o recurso estiver somente na base em **outro NUP**, selecionar a base separadamente para identificar o arquivo.
- Para evitar corrupção, arquivos existentes na pasta de saída **não são sobrescritos**.
- A varredura tem teto de 60 packs inspecionados e 768 MiB cumulativos, com limite de 192 MiB por recurso; um resultado negativo pode ser parcial, e isso fica registrado no relatório.
- O APK é independente do emulador; a compatibilidade de assinatura para atualizar o APK depende da preservação do certificado usado na compilação.

## Compilar

Da raiz do repositório:

```bash
android/app/gradlew --no-daemon -p android/shadowtool :assembleDebug
```

O workflow [Ocarina Shadow Tool — Android APK](../../.github/workflows/ocarina-shadowtool-android-apk.yml) compila o APK e publica `Ocarina-Shadow-Tool-Android-APK` como artefato das Actions.
