---
title: keytypist program roadmap
type: program
status: active
date: 2026-10-11
---
# keytypist program roadmap

Generated directly (ce-plan skill not used: tiny repo, fields written per the brief). Overlaps: PR #1 (TUI, touches `main.py`, `wpm-backlight.py`, README, install files) and PR #5 (AGENTS.md). Land #1 first; every code unit below should be rebased on it.

## Now

### U1. Make the daemon portable
- Status: not started. Evidence: `wpm-backlight.py` `KBD_BACKLIGHT = /sys/class/leds/dell::kbd_backlight`; `install.sh` `REPO=/home/lukedaduke/...`; the service `ExecStart` hardcodes the same home.
- Difficulty: easy. Glob `/sys/class/leds/*kbd_backlight*`, template the unit with `sed` at install time.
- Feasibility: some laptops (e.g. Apple Asahi `kbd_backlight`) need udev perms; hardware-only testing.
- Simpler alternative: drop the custom sysfs writes and call `brightnessctl` (documented in the Arch Wiki). Deletes `_read_brightness_max`, `_set_brightness`.
- Verification: `python3 -m py_compile`; dry-run flag prints chosen device.

### U2. Add a minimal test and CI
- Status: not started. Evidence: no tests, no workflows; only `--smoke`.
- Difficulty: easy. pytest on `NgramEngine`, `_brightness_for_wpm`.
- Feasibility: `evdev` import at module top blocks importing `wpm-backlight.py` in CI; stub it.
- Simpler alternative: run `main.py --smoke` and `py_compile` in one workflow.
- Verification: workflow green on a PR.

## Next

### U3. Show prediction accuracy in the TUI header
- Status: not started. Evidence: DB already logs every keystroke and prediction.
- Difficulty: medium (query + a header field; depends on PR #1 DB schema).
- Feasibility: none external.
- Simpler alternative: print a one-line summary at exit instead of live.

### U4. Package as `pipx install keytypist`
- Difficulty: medium: split `main.py` (single 23 KB file) only as far as `pyproject.toml` entry points need.
- Feasibility: llama-cpp-python must stay an optional extra.
- Simpler alternative: leave single-file, add `pyproject` with `py-modules`.

## Later

### U5. Pick one engine path
- Difficulty: medium. `LlamaCppEngine` and `LlamaServerEngine` overlap; the server variant avoids a heavy build dependency. Candidate to delete `LlamaCppEngine` (about 70 lines).
- Feasibility: user preference; keep if in-process inference matters.

### U6. Optional scored typing-test mode
- Difficulty: hard (new UI mode, scoring). Feasibility: crowded space (see research); only worthwhile if prediction accuracy becomes the hook.
- Simpler alternative: skip it and stay a predictor.
