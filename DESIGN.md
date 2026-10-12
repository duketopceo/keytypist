# keytypist design direction: Ember Keycap

Research lock (terminal typing tools per `docs/research/2026-10-10-landscape.md`; refero-design not available in this run, so the method was applied by hand): most competitors use neutral dark themes with a blue or green accent. keytypist is about a keyboard that glows with speed, so the accent is a backlight amber on warm near-black. Decision ledger: amber over blue (matches the product's physical output); monospace-only type (terminal surface); no gradients or shadows (curses cannot render them).

## Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| bg | `#FBF6EA` | `#17140F` | page, README art |
| ink | `#1F1A12` | `#F2EBDD` | text, outlines |
| ember | `#8A5200` | `#F5A623` | cursor, top prediction, links |
| mute | `#5E5646` | `#A89F8C` | help text, rank-2+ keys |

Contrast (WCAG): ink/bg 16.0 and 15.5; ember/bg 5.9 and 9.1; mute/bg 6.7 and 7.0. All pass AA (4.5).

## Type
Monospace only (the user's terminal font; docs use `ui-monospace`). Wordmark is stroked paths, no font.

## Glyphs and motion
Round-cap 4px strokes on a 64px grid; keycap outline plus a cursor bar. Motion: none in the TUI beyond key highlight on press; any web or doc motion under 150 ms and disabled for `prefers-reduced-motion`.

## Surfaces and mapping
- TUI (curses, `main.py`): map rank 1 to ember bold reverse, rank 2-3 to ink, rest to mute DIM. Today it uses COLOR_YELLOW, CYAN, BLUE (pair 3 blue is low contrast on dark); replace with 256-colour ember/ink/mute when `curses.COLORS >= 256`, falling back to the current pairs. Replace the `=` rule under the title with a box-drawing line. Not applied in this PR: PR #1 rewrites `main.py`; do it after it lands.
- Daemon: no UI; the ticker file is the surface.
- README: logo header, `assets/brand/`.

Logo is a proposal; owner signs off.
