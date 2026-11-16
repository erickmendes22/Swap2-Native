# Ocarina Shadow Tool — Android (.nup via Arquivos)

Aplicativo Android independente do emulador, com ID
\`com.swap2native.ocarina.shadowtool\`. Não precisa de root, Termux,
Python, e não altera o NUP original.

**O que faz**

1. Abre o seletor de arquivos padrão do Android (**Arquivos**).
2. Você seleciona um arquivo \`.nup\` e o app lê o índice de forma aleatória,
   com verificação SHA-256, sem extrair o jogo inteiro.
3. Mostra as versões base/atualização do título \`0400486024DEC000\`
   que estiverem dentro do NUP.
4. Localiza e descompacta \`Pack/Bootup.Nin_Ounce_NVN2.pack.zs\`
   e \`Pack/ZsDic.pack.zs\`, inclusive arquivos comprimidos no próprio NUP.
5. Lê \`ModelSceneConfigParam/*.bgyml\` e apresenta os parâmetros de
   sombras. Permite **salvar relatório TXT** para investigação.
6. **Só se os campos de resolução 1024/4096 forem identificados pelos
   nomes exatos e sem ambiguidades**, habilita gerar overlay para
   512/2048 ou 256/1024. O app recusa qualquer alteração por
   offsets adivinhados ou nomes hash sem significado comprovado.

**Onde fica o overlay**

Após escolher uma pasta pelo Android, o aplicativo grava
\`Pack/Bootup.Nin_Ounce_NVN2.pack.zs\` DENTRO daquela pasta,
recriando a estrutura de overlay que o emulador usa. Ainda não
importa/aplica o overlay automaticamente no emulador; é um helper
separado. O NUP original nunca é sobrescrito.

**Limitações desta versão experimental**

- A localização exata de \`ModelSceneConfigParam/Main\` no NUP v131072
  **ainda não foi verificada com o arquivo real**. Pode estar em outro
  pack, pode ter chaves hash; nesse caso o app apenas inspeciona o
  Bootup e mostra o motivo do bloqueio do patch.
- O APK gerado em CI executa lógica real de NUP/SARC/BYML, mas sem um
  dump de recursos proprietário não é possível afirmar que reduz
  sombras no dispositivo nem prever ganhos de FPS.
- Alguns fornecedores do Android Arquivos (especialmente provedores
  de nuvem) não suportam leitura aleatória. Se for o caso, salve
  o NUP localmente no armazenamento interno e selecione-o por Arquivos.
- Se o NUP contém somente atualização e o pack existe só no jogo base
  em **outro NUP**, a ferramenta informa que não encontrou o recurso.

**Compilação**

O projeto usa o wrapper Gradle já versionado em \`android/app\`.
Da raiz do repositório:

\`\`\`bash
android/app/gradlew -p android/shadowtool assembleDebug
\`\`\`

O workflow \`ocarinashadow-android-apk.yml\` publica o APK como artefato.
A build do emulador continua independente. O debug APK terá a assinatura
do workflow; futuras atualizações devem usar uma chave estável.
