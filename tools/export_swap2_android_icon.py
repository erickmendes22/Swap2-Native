"""Export the approved artwork and ImageGen foreground; never modifies app sources."""
from pathlib import Path
from PIL import Image, ImageDraw
import json
import sys

root = Path(__file__).resolve().parents[1]
base = root / 'assets/artwork/swap2-native/icon'
src = Image.open(base / 'swap2-native-icon-v2.png').convert('RGBA')
fg = Image.open(sys.argv[1]).convert('RGBA')
if fg.getextrema()[3][0] == 255:
    raise ValueError('Foreground must have alpha transparency')
fg = fg.crop(fg.getbbox())
out = base / 'android-v2'
res = out / 'res'
records = []
def save(im, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    records.append({'file': str(path.relative_to(out)), 'size': list(im.size)})

for density, scale in [('mdpi',1),('hdpi',1.5),('xhdpi',2),('xxhdpi',3),('xxxhdpi',4)]:
    size = round(48 * scale)
    icon = src.resize((size,size), Image.Resampling.LANCZOS)
    save(icon, res / f'mipmap-{density}/ic_launcher.png')
    mask = Image.new('L',(size*4,size*4)); ImageDraw.Draw(mask).ellipse((0,0,size*4-1,size*4-1),fill=255)
    rounded = icon.copy(); rounded.putalpha(mask.resize((size,size),Image.Resampling.LANCZOS))
    save(rounded, res / f'mipmap-{density}/ic_launcher_round.png')
    # Fit the complete emblem within the central 60 dp of a 108 dp layer.
    side = round(108 * scale)
    symbol = fg.copy(); symbol.thumbnail((round(60*scale),round(60*scale)),Image.Resampling.LANCZOS)
    layer = Image.new('RGBA',(side,side))
    layer.alpha_composite(symbol,((side-symbol.width)//2,(side-symbol.height)//2))
    save(layer,res / f'drawable-{density}/swap2_icon_foreground.png')
    mono = Image.new('RGBA',layer.size,'white'); mono.putalpha(layer.getchannel('A'))
    save(mono,res / f'drawable-{density}/swap2_icon_monochrome.png')

save(src.resize((512,512),Image.Resampling.LANCZOS),out/'store/swap2-native-512.png')
for version in ['mipmap-anydpi-v26','mipmap-anydpi-v33']:
    for name in ['ic_launcher','ic_launcher_round']:
        mono = '\n    <monochrome android:drawable="@drawable/swap2_icon_monochrome" />' if version.endswith('33') else ''
        path = res/version/(name+'.xml'); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n    <background android:drawable="@color/swap2_icon_background" />\n    <foreground android:drawable="@drawable/swap2_icon_foreground" />'+mono+'\n</adaptive-icon>\n',encoding='utf-8')
p = res/'values/swap2_icon.xml'; p.parent.mkdir(parents=True,exist_ok=True)
p.write_text('<?xml version="1.0" encoding="utf-8"?>\n<resources><color name="swap2_icon_background">#0B1020</color></resources>\n',encoding='utf-8')
(out/'manifest.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
preview = Image.new('RGB',(960,360),'#e5e9f0')
layer = Image.open(res/'drawable-xxxhdpi/swap2_icon_foreground.png')
composite = Image.new('RGBA',layer.size,'#0B1020'); composite.alpha_composite(layer)
# Static previews approximate the central 72 dp masked viewport, not launcher animations.
margin=72; central=composite.crop((margin,margin,432-margin,432-margin)).resize((240,240),Image.Resampling.LANCZOS)
for i,shape in enumerate(['circle','squircle','square']):
    mask=Image.new('L',(960,960)); draw=ImageDraw.Draw(mask)
    if shape=='circle': draw.ellipse((0,0,959,959),fill=255)
    elif shape=='squircle': draw.rounded_rectangle((0,0,959,959),radius=220,fill=255)
    else: draw.rectangle((0,0,959,959),fill=255)
    preview.paste(central,(40+i*320,60),mask.resize((240,240),Image.Resampling.LANCZOS))
save(preview,out/'preview-masks.png')
print(f'Exported {len(records)} PNGs to {out}')
