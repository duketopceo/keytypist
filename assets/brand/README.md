# keytypist brand (PROPOSAL, owner signs off)

Hand-written SVG, no raster or generated imagery.

- **Mark** (`logo.svg`, `logo-dark.svg`): 64x64 grid. Outer rounded square (4px inset, r=12, 5px stroke) is the keycap. A faint inner rounded rect is the key's top face. A 5x20 ember bar is the text cursor, the "next key" being predicted. The 32x4 bar below is the backlight glow strip, the WPM daemon's output.
- **Wordmark** (`wordmark.svg`, `wordmark-dark.svg`): mark plus "key" in ink and "typist" in ember, letters drawn as 4px round-cap strokes on a 18px advance (no font dependency).
- Colours: see DESIGN.md tokens. Light variants use `#1F1A12` / `#8A5200`, dark use `#F2EBDD` / `#F5A623`.
- Legible at 16px: only the outer stroke and cursor bar survive, which is intended.
