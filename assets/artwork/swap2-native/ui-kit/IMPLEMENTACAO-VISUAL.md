# Swap2-Native — especificação visual e implementação do launcher

Atualizado em 2 de novembro de 2026. Inclui o UI kit v1 completo.

## Escopo

Identidade visual e referência de interface. Claude implementará seleção da pasta, reconhecimento e listagem de dumps. Nenhum código ou identificador do aplicativo foi renomeado nesta entrega. O nome visível aprovado pelo usuário é **Swap2-Native**, com essa capitalização e hífen.

A identidade deixa de representar um jogo específico e passa a representar uma biblioteca. Não reutilizar o mundo de corrida como fundo global. Manter os controles de corrida em seu contexto de jogo, caso continuem fazendo parte do projeto.

## Entregáveis

Em assets/artwork/swap2-native/:
- swap2-native-logo-v1.png: marca horizontal sobre fundo sólido #0B1020.
- swap2-native-library-concept-v1.png: biblioteca com três jogos fictícios para demonstração.
- swap2-native-empty-concept-v1.png: primeira abertura, sem pasta escolhida.
- PROMPTS-v1.md: prompts originais usados na ferramenta integrada image_gen.

Os conceitos são composições estáticas. Construir botões, títulos, foco, cards e estados em código; não aplicar a tela inteira como uma textura clicável. O UI kit descrito abaixo fornece os elementos reutilizáveis da interface, separados dos conceitos. As capas fictícias demonstram a composição; não devem aparecer como jogos encontrados no produto.

## UI kit disponível para o Claude

Pasta-base: assets/artwork/swap2-native/ui-kit/. O kit contém **99 SVGs editáveis, 99 PNGs RGBA equivalentes e dois PNGs auxiliares**. A interface ainda precisa ser implementada e ligada ao scanner e ao runtime.

Ler nesta ordem:

1. Este documento: fluxo, estados e critérios de aceitação.
2. assets/artwork/swap2-native/ui-kit/README.md: composição e regras técnicas dos componentes.
3. assets/artwork/swap2-native/ui-kit/gallery.html: catálogo visual filtrável, aberto localmente no navegador.
4. assets/artwork/swap2-native/ui-kit/manifest.json: IDs, caminhos SVG/PNG, dimensões e stretchInsets.
5. assets/artwork/swap2-native/ui-kit/tokens.json: cores, espaçamento, tipografia, foco e animação.

Pacote completo: output/design/Swap2-Native-UI-Kit-v1.zip. Inclui conceitos, componentes, documentação e scripts de geração.

| Grupo no kit | Elementos e uso |
|---|---|
| brand/ | símbolo de troca, wordmark transparente e ícone quadrado do aplicativo |
| icons/ | 30 ícones para ações, navegação, biblioteca, áudio, vídeo e feedback |
| buttons/ | primário, secundário, perigo e botão de ícone; normal, foco, pressionado e desativado |
| panels/ | janela, toolbar, detalhes, popover, diálogo, tooltip e linha de opção |
| cards/ | normal, foco, selecionado e desativado; capa e texto são camadas separadas |
| tabs/ e fields/ | abas, pesquisa, entrada e seleção, com estados visuais |
| controls/ | interruptores, checkbox, radio e trilha/preenchimento/indicador de slider separados |
| badges/ e feedback/ | status, banners, spinner, progresso e skeleton de carregamento |
| covers/ | placeholder genérico para jogo sem capa |
| hints/ | A/B/X/Y e direcional, conforme a família do controle |
| illustrations/library-folder.png | ilustração inicial isolada, com transparência |
| backgrounds/launcher.png | fundo escuro sem textos ou componentes |

As versões PNG dos SVGs estão em png/ com a mesma hierarquia. Exemplo: buttons/primary-normal.svg → png/buttons/primary-normal.png. Usar pngFile do manifesto para evitar inferir caminhos.

## Orientação técnica para implementação

O runtime atual usa ImGui/SDL; SDL_LoadPNG não carrega SVG. Usar os PNGs fornecidos para leitura direta ou redesenhar componentes em ImGui com os tokens e a geometria dos SVGs. Manter os SVGs como fontes para exportações de maior densidade.

- PNGs dos componentes estão em dimensão base 1x. Para telas de alta densidade, rasterizar os SVGs em tamanho adequado, sem ampliar ícones pequenos indefinidamente.
- Painéis e botões com stretchInsets devem preservar cantos e bordas por desenho em nove partes. Não esticar a imagem inteira indiscriminadamente. Cards preservam a área da capa e a altura do rodapé.
- Textos são desenhados em runtime e traduzidos. Botões, badges e campos não incluem legendas. Wordmark e hints contêm texto SVG e precisam de uma fonte definida antes da rasterização final.
- Sobre botões ciano/coral, usar texto e ícones #0B1020. Sobre superfícies escuras, #F3F6FC. Ícones exportados são claros; aplicar a cor correta ao compor.
- Slider e progresso usam partes separadas; posição/preenchimento vêm de valores reais. Spinner é estático no arquivo e precisa de animação em runtime, respeitando movimento reduzido.
- Wordmark e ilustração usam contain. Fundo usa cover. Não deformar marca ou imagens. O ícone quadrado é uma fonte visual; ainda é necessário gerar os recursos e máscaras Android.
- Carregar texturas por contexto/backend, respeitar alpha/pitch, invalidar recursos ao recriar o backend e incluir os arquivos usados no empacotamento Android.
- Estado desativado deve afetar superfície, texto e ícone e bloquear a ação. Seleção de card e foco de navegação são independentes.

Para regerar: python tools/generate_swap2_ui_kit.py e python tools/rasterize_swap2_ui_kit.py. A rasterização usa Pillow e Chrome local em modo headless; não acessa a internet. Os scripts não implementam a interface do aplicativo.

## Entrega funcional esperada do Claude

Implementar a seleção de pasta, leitura dos dados do scanner e biblioteca usando os assets deste kit. Renderizar o nome Swap2-Native de forma consistente, migrando referências visuais do nome anterior. Alterações de package ID, caminhos de dados e migração de instalação são decisões separadas da identidade visual; preservar os dados do usuário.

Montar primeiro a abertura vazia e a biblioteca; em seguida os estados de análise/erro e configurações. Não tratar as capas fictícias como jogos instalados e não usar as telas conceituais como texturas únicas. Não alterar os controles touch de corrida ao aplicar o tema do launcher.

## Identidade

Símbolo: duas setas opostas formando um movimento de troca e sugerindo um S. Marca original, sem reproduzir o símbolo do Switch. A logo PNG conceitual inclui fundo escuro. Para a interface, usar ui-kit/brand/wordmark.svg ou seu PNG transparente em ui-kit/png/brand/wordmark.png. O símbolo e o ícone também estão disponíveis em vetor; manter sua proporção e área livre de pelo menos meia altura do símbolo.

Paleta sugerida:
- fundo: #0B1020
- superfícies: #151E32
- superfícies elevadas: #1C2942
- foco e ação principal: #31D7ED
- acento secundário: #FF686B
- texto principal: #F3F6FC
- texto secundário: #AAB8CF
- reconhecido: #70DCB2
- alerta: #FFC477

Ciano destaca a seleção e a ação principal; coral é um acento discreto da marca. Não usar somente cor para comunicar erro, foco ou disponibilidade.

Tipografia: sans serif geométrica legível. Usar fonte disponível e devidamente licenciada; títulos semibold/bold, informações regulares. Não presumir a fonte exata do desenho gerado. Escala inicial: título 28–32 sp, seção 22–24 sp, nomes de jogos 18–20 sp, corpo 14–16 sp, informações auxiliares 12–14 sp. Contraste e alvo mínimo de toque 48 dp.

Espaçamento em múltiplos de 8 dp; margens de 24–32 dp; cantos de cards 16–20 dp e botões 12–16 dp. Foco ciano de 2–3 dp com brilho leve e espaço para não cortar o contorno. Animações curtas e discretas de foco/entrada, com opção de movimento reduzido.

## Fluxo visual

1. Sem pasta configurada: logo e engrenagem no topo; ilustração de pasta; título “Sua biblioteca começa aqui”; explicação “Escolha a pasta com os dumps dos seus jogos.”; ação primária “Escolher pasta”.
2. Ao escolher pasta: abrir seletor do sistema. Cancelar conserva o estado anterior. Durante análise, mostrar atividade e texto “Buscando jogos…”; progresso indeterminado quando o total não for conhecido.
3. Com resultado: título “Biblioteca”, quantidade de jogos reconhecidos, nome amigável da pasta, “Trocar pasta”, “Atualizar” e engrenagem no topo. Exibir cards com capas reais disponíveis e nome. Não expor caminhos internos longos por padrão.
4. Selecionar um card destaca sua borda e atualiza o painel contextual. “Jogar” deve estar perto do jogo selecionado. Não iniciar automaticamente só por tocar para selecionar.
5. Abrir configurações mantém a identidade escura/ciano/coral e permite retornar com seleção e rolagem preservadas.

## Biblioteca

Paisagem: três cards visíveis como referência, com rolagem horizontal ou grade responsiva quando houver mais jogos. A quantidade deve se adaptar ao tamanho e densidade; não comprimir textos para manter exatamente três cards. Retrato: grade de uma ou duas colunas e ações em uma barra compacta.

Área superior: marca à esquerda; pasta, atualização e configurações à direita. Em telas estreitas, manter ícones com rótulos acessíveis e mover ações secundárias para menu.

Cards: capa em proporção uniforme, título abaixo, contorno de foco fora da área da capa. Capas de proporções diferentes devem ser acomodadas sem deformar. Título longo usa até duas linhas e reticências. Sem capa: placeholder com inicial/símbolo e gradiente discreto, sem inventar uma capa ou confundir com outro jogo.

“Reconhecido” significa identificado pelo scanner. Não implica que o jogo execute corretamente. Estados de pronto, arquivos incompletos e incompatibilidade só podem aparecer quando o backend fornecer essa informação; nessa situação, usar rótulos específicos. Não mostrar versão, região, ícone ou título inventados quando faltarem metadados.

O card selecionado mostra nome e versão, se conhecida, e a ação Jogar. Se a biblioteca estiver vazia, essa ação não aparece. Se o backend fornecer motivo para impedir a execução, desabilitar a ação e explicar em linguagem simples.

## Estados complementares a implementar

- Pasta selecionada sem jogos reconhecidos: “Nenhum jogo reconhecido nesta pasta”, ações Atualizar e Trocar pasta.
- Acesso à pasta perdido: explicar e pedir nova seleção; conservar a biblioteca em cache apenas com indicação de indisponível, se houver cache.
- Falha na análise: aviso legível e opção Tentar novamente; não apresentar erro como biblioteca vazia.
- Dump incompleto: indicar no card/detalhes e mostrar orientação do backend.
- Muitos jogos: busca por título; filtros somente quando houver utilidade e dados suficientes.
- Retorno do jogo: restaurar foco no jogo iniciado e posição da biblioteca.
- Primeira abertura e resultado vazio são estados diferentes; não mostrar a introdução inicial sempre que a pasta estiver vazia.

## Navegação

Toque e controle devem oferecer as mesmas ações. Direcional/analógico navega; confirmar seleciona ou ativa a ação em foco; voltar fecha painel ou retorna. Não misturar o botão B do controle físico de família Xbox com a legenda Nintendo sem considerar o mapeamento existente. Desenhar hints de acordo com o dispositivo ativo e ocultá-los quando só toque estiver em uso.

A seleção de um card e o foco de um botão são estados distintos. Botão Jogar identifica claramente qual jogo iniciará. Nenhuma atividade de análise deve capturar o foco repetidamente.

## Configurações: extensão visual

Reaproveitar a estrutura de painel do projeto com nova paleta, superfícies e tipografia. Agrupar Biblioteca (pasta e nova análise), Interface (tema/escala, se implementados), Controles e opções efetivamente suportadas pelo runtime. Não exibir ajustes fictícios só porque cabem na proposta visual. Ações destrutivas exigem diferenciação e confirmação existente.

## Critérios visuais para entrega do Claude

- Nome Swap2-Native consistente em todas as telas visíveis.
- Logo sem deformação, foco legível e botões com alvos de toque adequados.
- Primeira abertura, análise, resultado vazio, erro e biblioteca populada cobertos.
- Textos e cards alimentados por dados reais; os três jogos fictícios dos conceitos não são dados iniciais.
- Capturas reais comparadas com os conceitos em paisagem e retrato.
- Seleção, foco e rolagem preservados ao retornar de configurações/jogo.
- Manifesto sem caminhos quebrados e todos os assets utilizados presentes no APK.
- Botões e ícones legíveis em telas de alta densidade, legendas longas sem sobreposição e estados sem deformação.
- Slider, progresso e spinner conectados ao estado real; ações indisponíveis corretamente desativadas.
- Sem instalação ou operação no aparelho durante o teste concorrente sem coordenação com o usuário.

A proposta visual pode ser refinada após a revisão do usuário; não implica uma alteração funcional já implementada.


## Validação do material entregue

Os 99 SVGs passaram por leitura XML. As 99 versões PNG foram renderizadas com Chrome headless, inspecionadas em folha conjunta e verificadas quanto a dimensões, alpha e correspondência com o manifesto. Ilustração e fundo foram gerados com image_gen; os prompts estão no kit. Essa validação dos assets não substitui testes da interface funcional no aparelho.
