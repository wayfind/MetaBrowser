"""Create a mac_privacy_runner fixture: synthetic canary font, owned root and state.json.

Glyphs are plain rectangles drawn here (no copied outlines). mac_privacy_acceptance.py
expects 1 em advances (18 glyphs at 20px = 360px) and a 3 em U+E9F1 glyph (60px).
Usage: uv run --no-project --python 3.12 --with fonttools python make_privacy_canary_font.py NEW_ROOT
"""
import json, os, secrets, sys
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

root = Path(sys.argv[1])
family = 'MetaBrowserPrivacyCanary' + secrets.token_hex(6)
# One em per glyph: the acceptance expects 18 glyphs at 20px to measure exactly 360px.
advances = {'.notdef': 1000, 'space': 1000, 'i': 1000, 'W': 1000, 'uniE9F1': 3000}  # private glyph: 3 em -> 60px at 20px
advances.update({f'digit{d}': 1000 for d in range(10)})
cmap = {32: 'space', ord('i'): 'i', ord('W'): 'W', 0xE9F1: 'uniE9F1'}
cmap.update({ord(str(d)): f'digit{d}' for d in range(10)})
fb = FontBuilder(1000, isTTF=True)
order = list(advances)
fb.setupGlyphOrder(order)
fb.setupCharacterMap(cmap)
glyphs = {}
for name, width in advances.items():
    pen = TTGlyphPen(None)
    if name != 'space':
        pen.moveTo((60, 0)); pen.lineTo((60, 700)); pen.lineTo((width - 60, 700)); pen.lineTo((width - 60, 0)); pen.closePath()
    glyphs[name] = pen.glyph()
fb.setupGlyf(glyphs)
fb.setupHorizontalMetrics({name: (width, 60 if name != 'space' else 0) for name, width in advances.items()})
fb.setupHorizontalHeader(ascent=800, descent=-200)
fb.setupNameTable({'familyName': family, 'styleName': 'Regular', 'fullName': family, 'psName': family,
                   'uniqueFontIdentifier': family + '-test', 'version': 'Version 1.000'})
fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
fb.setupPost()
root.mkdir(parents=True, exist_ok=False)
(root / '.metabrowser-owned-fixture').write_text('mac-privacy')
font = root / 'canary.ttf'
fb.save(str(font))
state = {'root': str(root), 'font': str(font), 'family': family,
         'installed_font': str(Path.home() / 'Library/Fonts' / (family + '.ttf'))}
state_path = root / 'state.json'
with os.fdopen(os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as s:
    json.dump(state, s)
print(json.dumps({'state': str(state_path), 'family': family, 'bytes': font.stat().st_size}))
