# AGENTS.md

`keytypist` predicts your next keystroke in a curses TUI and, separately, drives
your keyboard backlight from your real typing speed.

## Layout

| Path | What it is |
|---|---|
| `main.py` | The TUI and the prediction engines. ~756 lines, single file. |
| `wpm-backlight.py` | The WPM daemon. Reads `/dev/input/event*`, writes the LED. |
| `keytypist-wpm.service` | systemd unit for the daemon. |
| `install.sh` | Installs that unit. Requires root; re-execs itself through `pkexec`. |

## Commands

```bash
python3 main.py                      # n-gram engine, zero dependencies
python3 main.py --smoke              # non-curses smoke test — the only check that exists
python3 main.py --engine llama --model /path/to/model.gguf
python3 wpm-backlight.py             # needs python3-evdev and root
```

**There is no test suite and no CI.** `--smoke` is the entire verification
surface, so run it before claiming anything works. It exercises the n-gram
predictor only.

## Traps

- **`llama_cpp` is imported lazily, inside `LlamaCppEngine`, on purpose.** The
  default `ngram` engine must keep working with nothing installed. Do not hoist
  that import to module scope and do not add `llama-cpp-python` to a requirements
  file — the default path is deliberately dependency-free.
- **`evdev` is a hard, top-level import in `wpm-backlight.py` only.** `main.py`
  does not need it. A missing `evdev` is a daemon problem, not a `main.py` problem.
- **The backlight path is hardcoded to one machine.**
  `KBD_BACKLIGHT = Path("/sys/class/leds/dell::kbd_backlight")` is a
  Dell-specific LED class. On other hardware the daemon finds nothing. If you
  touch this, probe for the LED class rather than widening the constant.
- **`install.sh` hardcodes an absolute source path**
  (`/home/lukedaduke/Documents/github/personal/keytypist`) instead of using the
  script's own directory. Run from a fresh clone it copies from that path, not
  from your checkout. This is a real bug, not a usage note — fix it by resolving
  `$(dirname "$0")`, and say so in the PR.

## Runtime state

All state is user-local, under `~/.config/keytypist/`: `corpus.txt` (training
text), `keytypist.db` (SQLite keystroke and prediction log), `keytypist.log`.
Override the database with `--db`. Nothing in this repo is written at runtime,
so a clean checkout has no state to reset.

## Conventions

- Python 3.10+ (`from __future__ import annotations`, `X | None` unions).
- `Engine` is a `Protocol`; `NgramEngine`, `LlamaCppEngine` and
  `LlamaServerEngine` all satisfy it. A new engine implements the protocol and
  gets a `--engine` choice — do not add a subclass hierarchy.
- Guard `curses` calls with `_safe_addstr`. The TUI is expected to survive a
  terminal that is too small, and that helper is why.
