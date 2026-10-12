# keytypist landscape (2026-10-11)

Scope: keytypist is a Python curses TUI that predicts the next key from your own typing history (n-gram or local llama), logs to SQLite, plus a root daemon that maps rolling WPM to keyboard backlight brightness. Read from `main.py` (engines `NgramEngine`, `LlamaCppEngine`, `LlamaServerEngine`, `Database`, curses UI) and `wpm-backlight.py` (evdev, sysfs).

## Neighbours

Typing-test TUIs (the nearest category users will compare against):
- [smassh](https://pypi.org/project/smassh) (Python, Textual): Monkeytype-style test, about 1.2k stars per the search listing. Better: themes, polished UI. Worse: no learning from your own history.
- [ttyper](https://dev.to/maxniederman/ttyper-a-terminal-based-typing-test-2ih7) (Rust): minimal CLI practice, installable from crates.io.
- [termitype](https://www.linuxlinks.com/termitype-feature-rich-terminal-typing-test/) (Rust, Ratatui): feature-rich, many options.
- [monkeytui](https://pkg.go.dev/github.com/ricardojparram/monkeytui) (Go, Bubble Tea): time/words/quote modes, command palette, persisted config.
- [tttui](https://pypi.org/project/tttui) (Python): WPM graph drawn in Unicode Braille.

Keyboard backlight tooling:
- [Arch Wiki: Keyboard backlight](https://wiki.archlinux.org/title/Keyboard_backlight): documents the sysfs convention `/sys/class/leds/<vendor>::kbd_backlight/{brightness,max_brightness}` and `brightnessctl --device=...`.
- [dumb-brightness](https://github.com/m-khvoinitsky/dumb-brightness): sets any sysfs brightness file.
- [UPower KbdBacklight](https://upower.freedesktop.org/docs/KbdBacklight.html): D-Bus interface exposing the sysfs path and a change signal.

## What users expect
Typing tools: a scored test with WPM and accuracy, themes, persisted settings, packaged install (`pip`/`cargo`). Backlight tools: vendor-agnostic device discovery and no root-owned hand-edited paths.

## What is unique
No surveyed typing TUI predicts your next key from your own corpus, and none ties typing speed to the keyboard backlight. The two halves share no code, so they are really two products in one repo.

## Gaps in this repo
- `wpm-backlight.py` hardcodes `dell::kbd_backlight`; `install.sh` and `keytypist-wpm.service` hardcode `/home/lukedaduke/...`. Neither works on another machine as shipped.
- No tests, no packaging, no CI. Only `python3 main.py --smoke` exists as a check.
- Predictions have no scoring (accuracy over time) surfaced to the user, so the "keeps learning" claim is not visible.
