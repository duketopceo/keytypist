#!/usr/bin/env python3
"""
keytypist-wpm — drive the keyboard backlight from typing speed.

Reads /dev/input/event* devices for key presses, computes rolling WPM,
and adjusts the Dell keyboard backlight accordingly. Intended to run as a
systemd service (needs read access to input devices and write access to
the backlight).
"""

from __future__ import annotations

import argparse
import json
import logging
import select
import sys
import time
from collections import deque
from pathlib import Path

try:
    from evdev import InputDevice, ecodes
except ImportError as e:
    print("python3-evdev is required (install with `omarchy pkg add python3-evdev` or equivalent)", file=sys.stderr)
    raise

LOG_PATH = Path("/var/log/keytypist-wpm.log")
TICKER_FILE = Path("/var/log/keytypist-wpm.ticker")
KBD_BACKLIGHT = Path("/sys/class/leds/dell::kbd_backlight")
BRIGHTNESS_FILE = KBD_BACKLIGHT / "brightness"
MAX_BRIGHTNESS_FILE = KBD_BACKLIGHT / "max_brightness"

# Keys that count toward "typing" for WPM. Modifiers, media keys, arrows, and
# other non-character keys are excluded.
TYPING_KEYCODES: frozenset[int] = frozenset(
    getattr(ecodes, name)
    for name in (
        # letters
        "KEY_A", "KEY_B", "KEY_C", "KEY_D", "KEY_E", "KEY_F", "KEY_G", "KEY_H",
        "KEY_I", "KEY_J", "KEY_K", "KEY_L", "KEY_M", "KEY_N", "KEY_O", "KEY_P",
        "KEY_Q", "KEY_R", "KEY_S", "KEY_T", "KEY_U", "KEY_V", "KEY_W", "KEY_X",
        "KEY_Y", "KEY_Z",
        # digits
        "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4", "KEY_5", "KEY_6", "KEY_7",
        "KEY_8", "KEY_9",
        # punctuation
        "KEY_COMMA", "KEY_DOT", "KEY_SLASH", "KEY_SEMICOLON", "KEY_APOSTROPHE",
        "KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_MINUS", "KEY_EQUAL",
        "KEY_BACKSLASH", "KEY_GRAVE",
        # word-level keys that still count as typing
        "KEY_SPACE", "KEY_ENTER", "KEY_BACKSPACE", "KEY_TAB",
        "KEY_KP0", "KEY_KP1", "KEY_KP2", "KEY_KP3", "KEY_KP4", "KEY_KP5",
        "KEY_KP6", "KEY_KP7", "KEY_KP8", "KEY_KP9",
    )
)

DEFAULT_WINDOW_SEC = 5.0
DEFAULT_IDLE_TIMEOUT_SEC = 3.0
DEFAULT_FAST_WPM = 60.0
DEFAULT_MEDIUM_WPM = 25.0


def _open_keyboards() -> dict[int, InputDevice]:
    """Open all input devices that look like real keyboards."""
    devices: dict[int, InputDevice] = {}
    for path in sorted(Path("/dev/input").glob("event*")):
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        caps = dev.capabilities()
        if ecodes.EV_KEY not in caps:
            dev.close()
            continue
        keys = set(caps[ecodes.EV_KEY])
        if not keys.intersection(TYPING_KEYCODES):
            dev.close()
            continue
        devices[dev.fd] = dev
    return devices


def _read_brightness_max() -> int:
    try:
        return int(MAX_BRIGHTNESS_FILE.read_text().strip())
    except (OSError, ValueError):
        return 2


def _set_brightness(level: int) -> None:
    try:
        BRIGHTNESS_FILE.write_text(str(level))
    except OSError as e:
        logging.error("Failed to write %s: %s", BRIGHTNESS_FILE, e)


def _disable_start_triggers() -> None:
    """Take over the backlight so keyboard/touchpad hardware triggers don't
    override our software control."""
    try:
        (KBD_BACKLIGHT / "start_triggers").write_text("-keyboard -touchpad")
        logging.info("Disabled hardware backlight start triggers")
    except OSError as e:
        logging.warning("Could not disable backlight start triggers: %s", e)


def _write_ticker(path: Path, wpm: float, level: int, max_level: int) -> None:
    try:
        path.write_text(
            json.dumps(
                {
                    "wpm": round(wpm, 1),
                    "brightness_level": level,
                    "max_level": max_level,
                    "ts": time.time(),
                }
            )
            + "\n"
        )
    except OSError as e:
        logging.error("Failed to write ticker %s: %s", path, e)


def _brightness_for_wpm(
    wpm: float,
    *,
    fast_wpm: float,
    medium_wpm: float,
    invert: bool,
) -> int:
    if wpm <= 0:
        return 0
    if wpm >= fast_wpm:
        return 0 if invert else 2
    if wpm >= medium_wpm:
        return 1
    return 2 if invert else 0


def run(
    window_sec: float,
    idle_timeout_sec: float,
    fast_wpm: float,
    medium_wpm: float,
    invert: bool,
    ticker_file: Path | None = None,
) -> None:
    devices = _open_keyboards()
    if not devices:
        raise RuntimeError("no readable keyboards found in /dev/input")

    logging.info("Watching %d keyboard(s)", len(devices))
    _disable_start_triggers()
    press_times: deque[float] = deque()
    last_level = -1
    last_keypress_at = 0.0
    last_ticker_write = 0.0
    max_level = _read_brightness_max()

    while True:
        now = time.monotonic()
        # Poll for events; short timeout lets us update the brightness at a
        # regular cadence even when nothing is pressed.
        r, _w, _x = select.select(list(devices), [], [], 0.25)
        for fd in r:
            dev = devices[fd]
            try:
                for event in dev.read():
                    if event.type == ecodes.EV_KEY and event.value == 1 and event.code in TYPING_KEYCODES:
                        ts = now
                        press_times.append(ts)
                        last_keypress_at = ts
            except (BlockingIOError, OSError):
                # Device went away; drop it.
                devices.pop(fd, None)
                continue

        # Trim the rolling window.
        while press_times and press_times[0] < now - window_sec:
            press_times.popleft()

        idle = (now - last_keypress_at) > idle_timeout_sec
        count = len(press_times)
        # Words are defined as 5 characters.
        wpm = (count / 5.0) / (window_sec / 60.0) if window_sec > 0 else 0.0
        if idle:
            wpm = 0.0

        level = _brightness_for_wpm(
            wpm,
            fast_wpm=fast_wpm,
            medium_wpm=medium_wpm,
            invert=invert,
        )

        if level != last_level:
            logging.info("wpm=%.1f count=%d level=%d", wpm, count, level)
            _set_brightness(level)
            last_level = level

        if ticker_file and now - last_ticker_write >= 0.25:
            _write_ticker(ticker_file, wpm, level, max_level)
            last_ticker_write = now


def main() -> int:
    parser = argparse.ArgumentParser(description="keytypist WPM backlight driver")
    parser.add_argument("--window-sec", type=float, default=DEFAULT_WINDOW_SEC)
    parser.add_argument("--idle-timeout-sec", type=float, default=DEFAULT_IDLE_TIMEOUT_SEC)
    parser.add_argument("--fast-wpm", type=float, default=DEFAULT_FAST_WPM)
    parser.add_argument("--medium-wpm", type=float, default=DEFAULT_MEDIUM_WPM)
    parser.add_argument(
        "--invert",
        action="store_true",
        help="darker as you type faster (default is brighter)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=LOG_PATH,
        help="log file path (default: /var/log/keytypist-wpm.log)",
    )
    parser.add_argument(
        "--ticker-file",
        type=Path,
        default=TICKER_FILE,
        help="JSON ticker file path (default: /var/log/keytypist-wpm.ticker)",
    )
    parser.add_argument(
        "--no-ticker",
        action="store_true",
        help="disable the JSON ticker output",
    )
    args = parser.parse_args()

    logging.basicConfig(
        filename=str(args.log_file),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        run(
            window_sec=args.window_sec,
            idle_timeout_sec=args.idle_timeout_sec,
            fast_wpm=args.fast_wpm,
            medium_wpm=args.medium_wpm,
            invert=args.invert,
            ticker_file=None if args.no_ticker else args.ticker_file,
        )
    except Exception:
        logging.exception("keytypist-wpm crashed")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
