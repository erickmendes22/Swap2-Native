# Donkey Kong Bananza — layout touch v1 para Swap2-Native

**Android implementation update (2026-11-05):** per-game selection and the Bananza layout are now implemented in the Java launcher. See [Touch profiles](SWAP2-NATIVE-TOUCH-PROFILES.md) for the actual integration, storage, tests and remaining device validation. The `runtime/ui/touch_controls.mm` reference below describes an older implementation, not the current Android tree. Auxiliary commands currently use the visible D-pad, and camera uses a visible right stick.

Proposta visual do modo **1 jogador**, controle completo. Integrado ao runtime em f75d8f3 (touch_profile = action, runtime/ui/touch_controls.mm; ver docs/SWAP2-NATIVE.md); ainda não conferido no aparelho. Conferir os comandos na versão do jogo e nas opções de remapeamento antes da implementação. As imagens são referências geradas, não capturas reais de jogo.

## Arquivos

Em assets/artwork/swap2-native/bananza/:
- bananza-touch-layout-v1.png: conceito completo com posição dos controles.
- bananza-touch-buttons-v1.png: folha de 16 botões, RGBA, sem letras incorporadas.
- PROMPTS-v1.md: prompts usados na ferramenta integrada image_gen.

Desenhar letras e legendas em runtime. Direção e câmera usam analógicos vetoriais simples com as cores do kit Swap2-Native; não dependem de recorte da imagem conceitual. Reaproveitar o ícone more de ui-kit/icons/more.svg para o painel extra.

Atlas final conferido visualmente: 16 símbolos na ordem solicitada, 1254 × 1254 RGBA com alpha. Conceito: 1672 × 941. O círculo de câmera no conceito é uma anotação visual, não exige um botão permanente.

## Comandos

Mapeamento de referência, resumido a partir das fontes no final:

| Ação | Entrada | Comportamento touch |
|---|---|---|
| Movimento | analógico esquerdo | eixo 2D contínuo |
| Câmera | analógico direito | arrasto em área livre ou analógico opcional |
| Socar / balançar fragmento | Y | toque e duração fiel; ações dependem do contexto |
| Pular | A | preservar pressionar/segurar/soltar |
| Socar para cima | X | botão próprio |
| Socar para baixo / mergulho | B | botão próprio; contexto no chão/ar |
| Agarrar / arrancar / mirar / arremessar | ZR | manter e liberar fielmente, sem repetir automaticamente |
| Rolar / surfar fragmento | ZL | mesmo botão contextual |
| Palma/sonar | R | botão de palma |
| Música/assobio | L | manter enquanto pressionado |
| Bananza | L + R | atalho touch mantém ambos juntos |
| Trocar forma | direcional esquerda/direita | dois botões extras |
| Habilidades | direcional cima | botão extra |
| Foto | direcional baixo | botão extra |
| Mapa | − | botão extra |
| Pausa do jogo | + | botão pequeno no topo |
| Configurações Swap2-Native | ação local do aplicativo | engrenagem separada de + |

O salto com fragmento usa A no contexto adequado, e não um botão Switch adicional. Habilidades das transformações também reutilizam comandos: manter a duração das entradas, sem inventar combos ou trocar mapeamento por tempo. O modo cooperativo de Pauline tem outro esquema e fica fora deste perfil inicial.

## Disposição sugerida

A prioridade é manter movimento, pulo, soco e agarrar acessíveis e deixar o centro da cena livre. Coordenadas são proporções da área útil, após insets, e precisam ser ajustadas ao aspecto e à escala.

| Controle | Centro x,y | Tamanho visual relativo à altura |
|---|---|---|
| Analógico movimento | 0.13, 0.78 | diâmetro 0.25 |
| Rolar ZL | 0.10, 0.48 | diâmetro 0.11 |
| Palma/sonar R | 0.22, 0.57 | diâmetro 0.10 |
| Música L | 0.08, 0.30 | diâmetro 0.09 |
| Soco Y | 0.80, 0.68 | diâmetro 0.14 |
| Pulo A | 0.94, 0.68 | diâmetro 0.14 |
| Soco acima X | 0.87, 0.51 | diâmetro 0.11 |
| Soco abaixo B | 0.87, 0.85 | diâmetro 0.11 |
| Agarrar/arremessar ZR | 0.89, 0.31 | alvo 0.20 × 0.10 em unidades da altura |
| Transformação L+R | 0.50, 0.09 | alvo 0.23 × 0.09 em unidades da altura |
| Extras | 0.05, 0.08 | diâmetro 0.07 |
| Pausa + | 0.94, 0.08 | diâmetro 0.07 |
| Menu do aplicativo | 0.86, 0.08 | diâmetro 0.07 |

Área de câmera sugerida: zona livre entre centro e botões direitos, excluindo explicitamente todas as hitboxes. Não capturar a metade direita indiscriminadamente: agarrar e ataques precisam ter prioridade. O círculo de câmera na referência só indica essa zona e pode ficar oculto durante o jogo.

Extras em um painel compacto: mapa, habilidades, foto e duas setas para as formas. Não enviar entradas de jogo ao abrir/fechar o painel. Posicionar o painel sem sobrepor o analógico ou comandos principais, ou suspender a entrada de jogo enquanto estiver aberto. Permitir fixar favoritos na tela pelo editor.

## Folha de botões

Ordem visual solicitada, da esquerda para a direita:

| Linha | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| 1 | soco Y | pulo A | soco acima X | soco abaixo B |
| 2 | agarrar ZR | rolar ZL | palma R | música L |
| 3 | Bananza L+R | mapa − | habilidades ↑ | foto ↓ |
| 4 | forma anterior ← | forma seguinte → | pausa + | configurações |

Medir os retângulos reais após inspecionar o atlas; geração não garante grade exata. Preservar proporção, margens e alpha. Usar estados pressionado/foco em runtime sobre a mesma arte. Para ZR, um botão circular é fornecido; a apresentação retangular no conceito é opcional, com ícone do atlas em uma superfície nativa do kit.

## Requisitos de entrada

- Suportar movimento + câmera + agarrar + pulo/soco simultâneos.
- Preservar o ID e a captura de cada dedo; áreas de toque mínimas de 48 dp.
- Agregar proprietários por bit. O atalho L+R não pode liberar L ou R que continuem mantidos por outro dedo; soltar a música não pode cancelar a transformação ainda pressionada.
- Não usar turbo/autofire para socos por padrão; segurar pode ter significado próprio.
- Ao arrastar câmera, enviar os dois eixos e voltar a zero ao terminar; oferecer inversão/sensibilidade e alternativa com analógico.
- Não aplicar aceleração automática do perfil de corrida a este perfil.
- Liberar entradas ao cancelar toque, perder foco, trocar perfil, abrir editor/menu ou conectar controle físico.
- Preservar o perfil clássico para navegação de menus e como alternativa completa.
- Não detectar transformações por heurística de tempo. Se não houver estado confiável, manter os nomes básicos dos botões e deixar o jogo resolver o contexto.
- Persistir perfil por jogo e layout sem reordenar os 19 índices touch antigos. Usar ações semânticas e formato versionado para novas posições.
- Não instalar nem operar o aparelho durante o teste concorrente sem coordenação.

## Validação

Conferir 16:9 e 20:9, insets, tamanhos mínimos/máximos, HUD visível, hitboxes sem sobreposição e retomada após menus. Testar manter ZR e mover a câmera para mirar, largar ZR, pular segurando fragmento, atalho L+R com toques sobrepostos e ausência de comandos presos. Comparar capturas reais com o conceito antes de declarar integrado.

## Fontes

- Nintendo: https://www.nintendo.com/us/whatsnew/learn-how-to-make-the-most-of-donkey-kongs-powerful-mitts/
- Controles completos: https://www.shacknews.com/article/145147/controls-actions-donkey-kong-bananza

A Nintendo confirma os ataques direcionais, pulo, agarrar/arrancar, arremesso, surfe, sonar e música. Os comandos auxiliares e o combo L+R devem ser conferidos no jogo conforme o guia de controles.

