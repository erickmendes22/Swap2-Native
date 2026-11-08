# Swap2-Native — UI kit v1 para Claude

## Comece aqui

Abra gallery.html para ver o catálogo filtrável. Consulte manifest.json para dimensões, nomes e margens de esticamento; tokens.json é a fonte de cores, espaçamentos e escala. Os conceitos de biblioteca e primeira abertura estão um nível acima desta pasta. O documento docs/SWAP2-NATIVE-VISUAL-v1.md no repositório descreve o fluxo funcional.

Esta entrega contém 99 SVGs originais editáveis, suas 99 versões PNG em png/ e dois PNGs gerados com image_gen: ilustração inicial isolada e fundo. A aplicação não foi modificada. As duas telas conceituais são referências; montar a interface com elementos independentes.

## Inventário

- brand: símbolo, wordmark editável e ícone quadrado para aplicativo.
- icons: 30 ícones para pasta, atualização, configuração, jogar, voltar, fechar, busca, setas, confirmação, alerta, informação, cadeado, controle, grade/lista, ordenação, filtro, mais, áudio, vídeo, biblioteca, parar, externo, arquivo, tentar novamente e tema.
- buttons: primário, secundário e perigo, nos estados normal, foco, pressionado e desativado; quatro estados de botão só com ícone.
- panels: janela, barra superior, detalhes do jogo, menu suspenso, diálogo, dica e linha de opção.
- cards: normal, foco, selecionado e desativado.
- tabs e fields: quatro estados de abas e campos.
- controls: interruptores ligados/desligados/desativados, checkboxes, radios e partes separadas de slider.
- badges e feedback: status reconhecido/aviso/erro/neutro, banners reutilizáveis, spinner, partes de progresso e card de carregamento.
- covers: capa genérica quando o jogo não possui imagem.
- hints: A/B/X/Y e direcional; escolher conforme controle ativo.
- illustrations/library-folder.png: figura decorativa de primeira abertura, com alpha.
- backgrounds/launcher.png: fundo opaco, sem UI.

Os botões e superfícies não contêm rótulos; renderizar textos traduzidos no aplicativo. Os badges também são sem texto. Hints e wordmark usam texto SVG editável: a fonte sans-serif deve ser resolvida antes de exportar. Eles não são curvas de fonte incorporadas.

## Composição por tela

| Tela | Elementos |
|---|---|
| Primeira abertura | fundo, marca, ilustração, título/explicação nativos, botão primary + folder-open |
| Biblioteca | toolbar, marca, secondary + folder, secondary + refresh, icon-button + settings; cards com capa real; detalhes + primary/play |
| Busca e filtros | fields + search, filter/sort/grid/list, popover e checkbox/radio; somente se a função existir |
| Analisando pasta | spinner ou progresso real, texto de andamento, stop/cancel quando suportado |
| Nenhum jogo | folder ou ilustração, explicação, refresh/retry e folder-open |
| Erro de acesso | warning/lock, banner error, mensagem real, ação para nova seleção |
| Detalhes do jogo | details/window, capa real/placeholder, metadados disponíveis, status e Jogar |
| Configurações | window, tabs, option-row, toggle, slider, field/dropdown, voltar e fechar |
| Confirmação | dialog, secondary cancelar, danger para ação destrutiva; texto explícito |
| Feedback | banners para toast/aviso/erro/sucesso; tooltip; hints conforme dispositivo |

Não exibir ações fictícias só porque há ícones para elas. Não usar a capa placeholder como jogo real. Reconhecido não significa executável: o backend deve fornecer estados distintos.

## Renderização no runtime nativo

Os SVGs são fontes vetoriais e não serão carregados diretamente por SDL_LoadPNG. Escolher uma destas implementações:

1. Recriar retângulos, linhas, foco, controles e ícones em ImGui usando tokens e geometria dos SVGs.
2. Rasterizar os SVGs na etapa de build com um renderizador SVG compatível, gerando PNGs RGBA em escalas 1x/2x/3x. Não tentar ler SVG com SDL_LoadPNG.

As 99 versões PNG RGBA estão em png/ com a mesma estrutura de pastas, na dimensão base 1x do manifesto (pngFile). Foram rasterizadas com Chrome headless e conferidas em uma folha conjunta. São prontas para SDL_LoadPNG; exportar maior densidade a partir dos SVGs quando necessário para telas de alta resolução. Os dois PNGs auxiliares também estão prontos. Claude deve criar o empacotamento e validar os assets no APK.

Usar as dimensões e stretchInsets do manifesto para desenhar painéis em nove partes. Não redimensionar o PNG inteiro de um botão para qualquer proporção: preservar cantos, bordas e extremidades. Cards são guias de composição: a capa e o rodapé têm proporções próprias, não esticar tudo junto. SVGs com contorno não têm brilho exterior, evitando recortes.

PNG de fundo: preencher a tela com cover; a ilustração usa contain com a proporção preservada, sem corte. Carregar texturas uma vez por contexto e liberar/inutilizar corretamente após reiniciar o backend. Respeitar pitch e alpha.

Ícones têm stroke/fill branco explícito. Ao usar sobre botão ciano ou coral, recolorir para #0B1020 (ou desenhar via ImGui com essa cor). Sobre superfícies escuras usar #F3F6FC. Para desativar, reduzir contraste/opacidade de shell, ícone e texto. Badges coloridos usam texto escuro. Não depender apenas de cor para comunicar status.

## Estados e dimensões

- Normal: superfície estável.
- Hover/foco: contorno de alto contraste; a seleção do jogo é independente do foco do botão.
- Pressionado: cor mais escura; não deslocar layout.
- Desativado: sem ação e sem hover ativo; continuar legível.
- Animações: 120 ms para foco e 180 ms para painéis; respeitar movimento reduzido.
- Spinner é uma imagem estática: animar rotação em runtime, ou fornecer texto de atividade em movimento reduzido.
- Progresso: trilha e preenchimento separados; mostrar percentual apenas se houver total real.
- Tamanho visual do ícone 24–32 dp, alvo de toque mínimo 48 dp. Hints de controle não são alvos touch.

## Tipografia e marca

O símbolo vetorial e o wordmark são reconstruções limpas da identidade aprovada, com a mesma ideia de setas ciano/coral. O wordmark evita depender do PNG opaco. Usar a fonte final licenciada do projeto, gerar curvas se necessário e conferir se a palavra cabe sem deformação. O script não distribui arquivos de fontes.

brand/app-icon.svg tem fundo e silhueta quadrada para uso como referência de ícone; gerar recursos Android e revisar máscaras circular/squircle. Não tratá-lo como adaptive-icon XML pronto.

## Validação antes de integrar

Conferir XML e caminhos do manifesto; testar contraste, idiomas longos, escala de texto, recortes, alvos touch e navegação com controle. Comparar capturas reais com os conceitos em paisagem e retrato. Não operar o aparelho enquanto o teste concorrente estiver em andamento sem coordenação.

Os SVGs e a galeria são gerados por tools/generate_swap2_ui_kit.py. Alterações devem entrar no gerador para não serem perdidas. Os PNGs são produzidos separadamente; rodar o gerador preserva esses arquivos e este README.


## Regeração

Executar python tools/generate_swap2_ui_kit.py e depois python tools/rasterize_swap2_ui_kit.py. A segunda etapa exige Pillow e Chrome local, não usa a internet. O wordmark rasterizado usa a sans-serif resolvida pelo Chrome neste ambiente; para a marca final, fixar a fonte antes de exportar novamente.
