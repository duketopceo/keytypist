# keytypist

Live next-key prediction TUI for the terminal — plus a daemon that drives your
keyboard backlight from your real typing speed.

## What it does

`keytypist` renders an on-screen keyboard and tries to guess your next
character as you type. Every keystroke and prediction is logged to a local
SQLite database so the model keeps learning from *your* typing.

Two prediction engines:

- **`ngram`** (default) — a tiny in-memory character n-gram trained from your
  local typing history. Zero dependencies, instant.
- **`llama`** — [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)
  running a local `.gguf` model for smarter predictions.

`wpm-backlight` is a companion daemon: it watches `/dev/input/event*`, computes
your rolling WPM, and maps it to the keyboard backlight brightness
(`/sys/class/leds/dell::kbd_backlight`). Type faster → brighter.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install llama-cpp-python   # optional, only for the llama engine

# WPM backlight daemon (Omarchy/Arch; needs python3-evdev + root for input/LED access)
sudo ./install.sh
```

## Usage

```bash
python3 main.py                 # n-gram engine
python3 main.py --engine llama --model /path/to/model.gguf
```

Data lives in `~/.config/keytypist/` (`corpus.txt`, `keytypist.db`,
`keytypist.log`).

## License

MIT — see [LICENSE](LICENSE).
