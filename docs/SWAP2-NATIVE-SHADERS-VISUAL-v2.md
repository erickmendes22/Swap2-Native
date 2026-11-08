# Swap2-Native — revisão visual da pré-compilação v2

Data: 3 de novembro de 2026. Entrega visual para Claude; runtime não alterado.

## Material atual inspecionado

- docs/SWAP2-NATIVE.md: biblioteca e arquitetura implementadas.
- android/out/compile1.png: captura de 12/24 itens.
- android/out/compile2.png: captura de 24/24 com spinner e Pular ainda visíveis.
- runtime/ui/library_ui.mm: library_ui_compile_draw.
- runtime/ui/launcher.mm: página COMPILING e transição para o jogo.
- runtime/nvn/vulkan/pipeline_list.h e pipeline_list.c: contrato de progresso.

As capturas da pré-compilação foram abertas e examinadas. O launcher.png antigo ainda mostra o MKWDroid; não foi usado como referência atual da biblioteca.

## Diagnóstico

O fluxo atual apresenta o conteúdo em uma coluna com grandes intervalos: spinner, título, explicação longa, barra, contador e botão. Isso perde hierarquia em telas largas. O nome do jogo já pode ser desenhado pelo código, mas não aparece nas duas capturas examinadas. A captura 24/24 não distingue a contagem completa de uma preparação ainda ativa.

A redação atual promete que o jogo não para para montar os gráficos. A versão nova explica que a preparação reduz pausas: não pode garantir ausência de travamentos ou cobrir shaders nunca vistos.

## Arquivos novos

Em assets/artwork/swap2-native/shaders/:
- precompile-v2.html: protótipo navegável local, responsivo, sem dependências externas.
- precompile-v2.png: prévia renderizada de 1600 × 900, com dados de exemplo.
- precompile-finalizing-v2.png: prévia da finalização em 1600 × 720.
- README.md: resumo e pontos de entrada.

HTML é referência visual, não uma proposta de substituir ImGui por WebView. As telas renderizadas não são screenshots de uma implementação nativa.

Abrir o HTML:
- sem parâmetros ou ?state=compiling: andamento conhecido.
- ?state=unknown: preparação sem total.
- ?state=finishing: contagem concluída, backend ainda ativo.
- &game=Nome: simular nomes reais/longos sem alterar o arquivo.

A área abaixo da tela contém controles de demonstração, não faz parte da UI final. O botão do protótipo não inicia jogo. A capa mostrada é um placeholder abstrato original em SVG, não a capa de Mario Kart World; o nome e 12/24 são exemplos.

## Composição proposta

Manter o fundo escuro e a marca existentes. Reduzir a marca no topo e evitar uma segunda barra de navegação.

Centro da tela com largura máxima de aproximadamente 1200 unidades na referência 1600 × 900:
- esquerda: card de cerca de 330 unidades com capa/placeholder, rótulo Jogo selecionado e nome;
- intervalo de aproximadamente 70 unidades;
- direita: rótulo PRÉ-COMPILAÇÃO, título Preparando seu jogo, explicação curta, painel de progresso e ação secundária.

Capa real disponível: reutilizar o caminho/resolvedor existente da biblioteca com contain/cover conforme a política de capas. Capa ausente: usar covers/placeholder do kit ou o símbolo abstrato do protótipo. Nome ausente: mostrar Jogo selecionado e não uma string vazia. Não inventar versão ou dados de driver.

Em telas estreitas, card vira uma linha compacta acima do progresso. Em paisagem baixa, reduzir os espaços e o tamanho da capa antes de reduzir texto ou alvos de toque. Preservar no mínimo 48 dp por ação. Nome longo usa até duas linhas; não sobrepor o painel direito.

## Hierarquia e texto

- Título principal: Preparando seu jogo.
- Explicação: Preparando o cache gráfico para reduzir pausas durante a partida.
- Etapa atual: Compilando shaders.
- Contador: N de T itens processados.
- Ação: Pular preparação.
- Consequência junto da ação: O restante será preparado durante o jogo e pode causar pausas.
- Rodapé: O jogo abrirá automaticamente ao concluir.

Usar traduções no sistema i18n existente. Textos e números são desenhados pelo runtime. Não exportar a imagem inteira para uma textura clicável.

O painel de progresso tem fundo elevado, borda discreta, etapa à esquerda e percentual destacado à direita; barra abaixo, contador e atividade na última linha. Spinner pequeno junto do status é suficiente; retirar o spinner grande isolado.

## Contrato real de estados

A API existente oferece done, total e bool going (vk_precompile_progress). done conta processados, inclusive ignorados; não é um contador comprovado de sucesso de compilação. Não rotular como shaders compilados ou cache pronto.

| Condição | Apresentação | Ação |
|---|---|---|
| going e total > 0 e done < total | Compilando shaders, percentual e N/T | Pular preparação habilitado |
| going e total <= 0 | preparação indeterminada, spinner/barra indeterminada; sem percentual | preservar possibilidade de pular conforme backend |
| going e total > 0 e done >= total | Finalizando preparação; contador completo; pequeno indicador de atividade | ocultar/desativar Pular e não emitir skip via voltar |
| going falso, sem skip solicitado | transição automática conforme fluxo existente | não adicionar botão Jogar artificial |
| skip solicitado pelo usuário | enviar vk_precompile_skip uma vez e seguir o fluxo atual | não chamar cancelar nem apagar cache |

Percentual é floor(100 * clamp(done,0,total) / total), quando total > 0. É fração dos itens, não estimativa de tempo. Não inventar ETA, velocidade ou etapas de gravação/otimização que o backend não informa. Finalização não deve alegar salvamento do cache sem um sinal real. O check visual nesse estado indica somente contagem processada, não sucesso global.

Preservar a regra existente da página COMPILING: só aparece a partir de 0,5 s e quando há trabalho suficiente para evitar flash. Não impor duração mínima nem atrasar o jogo para exibir o design.

O botão Pular não é cancelamento da inicialização. O backend permite que trabalhos já em execução continuem em segundo plano. A redação deve representar esse comportamento. Manter a tecla Voltar/B/Escape equivalente somente enquanto Pular estiver habilitado. O hint acompanha a família real do controle e some no modo só toque.

## Integração visual no código atual

Atualizar library_ui_compile_draw sem modificar scanner, pipeline list ou renderer para fins cosméticos. Reutilizar:
- library_ui_background, brand, text, text_centered, fit/wrap;
- button e foco existentes;
- resolvedor de capas da biblioteca, identificando pelo jogo ativo de forma estável;
- tokens C_BG, C_SURFACE, C_ELEVATED, C_FOCUS, C_TEXT, C_MUTED, C_BORDER e C_OK.

A função hoje recebe apenas done/total, sendo chamada enquanto going está ativo; finalização pode ser deduzida de done >= total nesse intervalo, sem iniciar o jogo antecipadamente. O launcher continua dono da transição quando going se torna falso. Não armazenar progresso fictício nem simular contagem suavizada que ultrapasse o valor real. Toda animação deve ser leve e respeitar movimento reduzido quando implementado.

As medidas do HTML são referência de proporção, não pixels para copiar literalmente. Converter para o sistema S já usado pelo ImGui e calcular a altura disponível. Não codificar y=210 e ir somando espaços sem verificar o limite inferior. Não deixar o card esconder o foco ou as bordas.

## Critérios de aceitação

1. Identidade do jogo visível, inclusive sem capa/nome e com nome longo.
2. Painel principal equilibrado em 16:9 e 20:9; ação inteira visível em altura compacta.
3. Contagem 0/T, intermediária, T/T e total desconhecido representadas corretamente.
4. T/T com backend ativo não oferece Pular nem sugere que a preparação travou.
5. Progresso nunca ultrapassa a barra; valores inválidos são limitados antes de desenhar.
6. i18n e foco por controle continuam funcionando; foco não é recapturado a cada frame.
7. Fluxo rápido conserva a regra de não exibir uma tela piscando.
8. Capturas reais comparadas às prévias, diferenciadas de mockups na documentação.
9. Teste de skip e finalização sem apagar dados/cache nem interromper teste concorrente no aparelho sem coordenação.

## Relação com o restante do launcher

A biblioteca implementada em library_ui.mm continua como base. Esta revisão concentra-se na pré-compilação: usar card/capa, marca e superfícies consistentes com ela, sem introduzir outra paleta ou uma tela inteira ligada a Mario Kart. O mesmo layout deve funcionar com Donkey Kong Bananza e qualquer outro jogo reconhecido.

