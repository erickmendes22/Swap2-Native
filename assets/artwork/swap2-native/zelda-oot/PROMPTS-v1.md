# Zelda touch buttons v1

Generated with the built-in image_gen tool on 2026-11-05. Output: `zelda-touch-buttons-v1.png`. Original alpha preserved; no post-processing. This is a themed artwork atlas, not a verified input mapping for the remake.

## Final prompt

Use case: ui-mockup. Asset type: transparent mobile game touch-control button atlas for Swap2-Native, themed around The Legend of Zelda: Ocarina of Time. Create ONE polished square sprite sheet of exactly 16 separate circular buttons in a precise 4 by 4 grid. Equal circle sizes, generous fully transparent gutters and outer margins so every button can be cropped independently. Deep midnight forest-green enamel button faces, thin antique gold rims, restrained turquoise edge glow, subtle engraved fantasy filigree confined to the rim. Bold ivory and pale-gold central pictograms with simple silhouettes readable at 48dp. Premium elegant Zelda adventure feel, not photorealistic, not overly busy, no background scene. Each button contains exactly ONE main symbol. Reading row by row left to right: row 1 sword with purple hilt, blue heraldic shield, rolling/dodging curved arrow, four-corner target-lock reticle; row 2 blue ocarina with clearly visible finger holes, bow and arrow, hooked grappling chain, round bomb with fuse; row 3 winged glowing fairy, folded adventure map with location marker, leather equipment satchel, stylized eye/camera-look symbol; row 4 left directional chevron, right directional chevron, two pause bars, settings gear. Keep all symbols centered, all circles completely visible, clean consistent front view and lighting. NO letters, numbers, text, title, captions, controller labels, watermark, checkerboard or colored backdrop. The outside of all circles and all gutters must have genuine alpha transparency. These are thematic action symbols, not a claim about the remake's actual button mappings.

## Atlas order

Read left to right, top to bottom:

1. Sword, shield, roll/dodge, target lock.
2. Ocarina, bow, grappling hook, bomb.
3. Fairy, map, equipment bag, look/camera.
4. Left, right, pause, app settings.

Keep controller letters, localization and pressed-state feedback in runtime. Measure actual icon bounds before cropping; generated grids are not guaranteed exact. Item symbols should represent assignable slots only after the game's real bindings and equipment behavior have been checked. Do not create automatic equipment swaps, macros or assumed bindings from this artwork. Analog sticks can use native vector drawing in matching forest green, gold and turquoise.

Status: integrated into the Android `zelda-oot` touch profile on 2026-11-05, with editable provisional symbols and visible controller labels. See [integration notes](../../../../docs/SWAP2-NATIVE-TOUCH-PROFILES.md). Gameplay action mappings and on-device appearance still require validation.
