# Swap2-Native — ícone v2

## Pacote Android

O pacote `android-v2/` contém densidades, camadas adaptativas, XMLs e preview. Guia para Claude: `docs/SWAP2-NATIVE-ICONE-ANDROID-v2.md` na raiz do repositório. Ainda não integrado ao APK.

Foreground derivado com ImageGen usando este prompt: “Remove ONLY the midnight navy background, replacing it with real alpha transparency. Preserve both cyan and coral swap arrows exactly, including their geometry, orientation, relative placement, bevels, colors and subtle shading. No new shapes, no text, no outline, no glow, no shadow outside the emblem. Maintain square image, original centered placement and original margins. This is the transparent foreground cutout for an Android adaptive icon, not a redesign.”

Arte criada com a ferramenta integrada image_gen. Arquivo: `swap2-native-icon-v2.png`. Proposta visual; ainda não aplicada ao APK. Fundo opaco em quadrado completo, sem máscara externa pré-aplicada. A integração Android deve conferir recortes circular/squircle e gerar recursos nas densidades adequadas; este PNG não é um adaptive icon em camadas.

## Prompt utilizado

Use case: logo-brand. Create a premium Android app icon for Swap2-Native, a native game launcher. One single square icon artwork, full bleed opaque midnight navy #0B1020 background, no surrounding presentation or device. Center a bold original emblem made of two thick opposing swap arrows forming a compact angular S / continuous exchange loop, cyan #31D7ED upper arrow moving right and coral #FF686B lower arrow moving left, clear dark negative space between them. Subtle sculpted bevel and restrained soft lighting, satin material, crisp precise edges, contemporary console gaming identity, strong simple silhouette readable at 48 pixels. Symbol centered inside middle 65 percent with generous Android adaptive mask safe padding; background extends to all four square edges, no pre-rounded outer corners. No text, no letters, no tiny controller buttons, no Nintendo or Switch marks, no characters, no decorative particles, no extra frame, no watermark. Visually striking but refined, mostly flat face-on view with very subtle dimensional depth. Output square high resolution.
