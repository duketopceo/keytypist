#!/usr/bin/env python3
"""
keytypist - live next-key prediction TUI.

Supports three engines:
- ngram: a tiny in-memory character n-gram trained from local typing history.
- llama: llama-cpp-python with a local .gguf model.
- llama-server: local llama.cpp HTTP server with a .gguf model.

All keystrokes and predictions are stored in a local SQLite database.
"""

from __future__ import annotations

import argparse
import curses
import json
import logging
import math
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

DATA_DIR = Path.home() / ".config" / "keytypist"
CORPUS_PATH = DATA_DIR / "corpus.txt"
DB_PATH = DATA_DIR / "keytypist.db"
LOG_PATH = DATA_DIR / "keytypist.log"

DEFAULT_CORPUS = (
    "the quick brown fox jumps over the lazy dog "
    "hello world this is a tiny model that learns from what you type "
    "it tries to guess the next character and light up that key "
    "press some keys and watch the board learn "
) * 20

ORDER = 5
TOP_K = 8
KB_START_Y = 6

KB_ROWS: list[list[tuple[str, int]]] = [
    [("esc", 5), ("`", 3), ("1", 3), ("2", 3), ("3", 3), ("4", 3), ("5", 3), ("6", 3), ("7", 3), ("8", 3), ("9", 3), ("0", 3), ("-", 3), ("=", 3), ("backspace", 6)],
    [("tab", 5), ("q", 3), ("w", 3), ("e", 3), ("r", 3), ("t", 3), ("y", 3), ("u", 3), ("i", 3), ("o", 3), ("p", 3), ("[", 3), ("]", 3), ("\\", 4)],
    [("capslock", 6), ("a", 3), ("s", 3), ("d", 3), ("f", 3), ("g", 3), ("h", 3), ("j", 3), ("k", 3), ("l", 3), (";", 3), ("'", 3), ("enter", 6)],
    [("shift_l", 7), ("z", 3), ("x", 3), ("c", 3), ("v", 3), ("b", 3), ("n", 3), ("m", 3), (",", 3), (".", 3), ("/", 3), ("shift_r", 8)],
    [("ctrl_l", 5), ("win", 5), ("alt_l", 5), ("space", 25), ("alt_r", 5), ("fn", 4), ("ctrl_r", 5)],
]

LABEL_DISPLAY: dict[str, str] = {
    "space": "",
    "backspace": "<-",
    "tab": "Tab",
    "capslock": "Cap",
    "enter": "Ret",
    "shift_l": "Shf",
    "shift_r": "Shf",
    "ctrl_l": "Ctl",
    "ctrl_r": "Ctl",
    "win": "Win",
    "alt_l": "Alt",
    "alt_r": "Alt",
    "fn": "Fn",
    "esc": "Esc",
}


def _setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _build_key_maps() -> tuple[dict[str, str], set[str]]:
    char_to_key = {" ": "space"}
    all_labels: set[str] = set()
    for row in KB_ROWS:
        for label, _ in row:
            all_labels.add(label)
            if len(label) == 1:
                char_to_key[label.lower()] = label
                char_to_key[label.upper()] = label
    return char_to_key, all_labels


CHAR_TO_KEY, ALL_LABELS = _build_key_maps()


def _display_for(label: str) -> str:
    return LABEL_DISPLAY.get(label, label)


def _thread_count() -> int:
    import os

    return os.cpu_count() or 1


class Engine(Protocol):
    """Pluggable prediction backend."""

    def predict(self, context: str, top_k: int = TOP_K) -> list[tuple[str, float]]:
        ...

    def close(self) -> None:
        ...


class NgramEngine:
    """Tiny in-memory n-gram continuation model."""

    def __init__(self, order: int = ORDER) -> None:
        self.order = order
        self.counts: dict[str, Counter] = defaultdict(Counter)
        self.total = 0

    def feed(self, text: str) -> None:
        for i in range(len(text) - self.order):
            ctx = text[i : i + self.order]
            nxt = text[i + self.order]
            self.counts[ctx][nxt] += 1
            self.total += 1

    def observe(self, context: str, nxt: str) -> None:
        ctx = context[-self.order :]
        self.counts[ctx][nxt] += 1
        self.total += 1

    def predict(self, context: str, top_k: int = TOP_K) -> list[tuple[str, float]]:
        for o in range(self.order, 0, -1):
            ctx = context[-o:]
            if ctx in self.counts:
                counter = self.counts[ctx]
                total = sum(counter.values())
                items = counter.most_common(top_k)
                return [(c, n / total) for c, n in items]
        return []

    def close(self) -> None:
        pass


class LlamaCppEngine:
    """Local .gguf model via llama-cpp-python."""

    def __init__(
        self,
        model_path: Path,
        n_ctx: int = 512,
        n_threads: int | None = None,
        n_gpu_layers: int = -1,
    ) -> None:
        try:
            from llama_cpp import Llama  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                "llama-cpp-python is not installed. "
                "Install it in a venv: pip install llama-cpp-python"
            ) from e

        self.model_path = model_path
        self.n_ctx = n_ctx
        if n_threads is None:
            n_threads = _thread_count()

        logging.info("Loading %s ...", model_path)
        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        logging.info("Model loaded.")

    def predict(self, context: str, top_k: int = TOP_K) -> list[tuple[str, float]]:
        prompt = context[-(self.n_ctx - 10) :]
        if not prompt:
            return []

        result = self.llm.create_completion(
            prompt,
            max_tokens=1,
            logprobs=top_k * 3,
            temperature=0.0,
            top_p=1.0,
            top_k=0,
            stop=None,
        )

        logprobs = result["choices"][0].get("logprobs", {})
        top_logprobs: Sequence[dict[str, float]] = logprobs.get("top_logprobs", [])
        if not top_logprobs:
            return []

        predictions: list[tuple[str, float]] = []
        seen: set[str] = set()
        for token, logp in top_logprobs[0].items():
            text = token.strip().lower()
            if not text:
                continue
            ch = text[0]
            if ch in seen or ch not in CHAR_TO_KEY:
                continue
            seen.add(ch)
            prob = math.exp(logp)
            predictions.append((ch, prob))
            if len(predictions) >= top_k:
                break
        return predictions

    def close(self) -> None:
        pass


class LlamaServerEngine:
    """Local llama.cpp HTTP server with a .gguf model."""

    def __init__(
        self,
        model_path: Path,
        host: str = "127.0.0.1",
        port: int = 8080,
        n_ctx: int = 512,
        n_gpu_layers: int = -1,
    ) -> None:
        self.model_path = model_path
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.n_ctx = n_ctx

        binary = shutil.which("llama-server")
        if not binary:
            raise FileNotFoundError(
                "llama-server not found in PATH. Install llama.cpp (e.g. 'brew install llama.cpp')"
            )

        cmd = [
            binary,
            "-m", str(model_path),
            "-c", str(n_ctx),
            "--host", host,
            "--port", str(port),
        ]
        if n_gpu_layers > 0:
            cmd.extend(["-ngl", str(n_gpu_layers)])
        elif n_gpu_layers < 0:
            cmd.extend(["-ngl", "99"])

        logging.info("Starting llama-server: %s", " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self._wait_for_server(timeout=120)

    def _wait_for_server(self, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("llama-server exited before becoming ready")
            try:
                req = urllib.request.Request(f"{self.base_url}/health", method="GET")
                with urllib.request.urlopen(req, timeout=1) as resp:
                    if resp.status == 200:
                        logging.info("llama-server ready.")
                        return
            except urllib.error.URLError:
                pass
            time.sleep(0.2)
        raise TimeoutError(f"llama-server did not become ready within {timeout}s")

    def predict(self, context: str, top_k: int = TOP_K) -> list[tuple[str, float]]:
        prompt = context[-(self.n_ctx - 10) :]
        if not prompt:
            return []

        payload = {
            "prompt": prompt,
            "n_predict": 1,
            "n_probs": top_k * 3,
            "temperature": 0.0,
            "top_k": 0,
            "cache_prompt": True,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/completion",
            method="POST",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.load(resp)
        except urllib.error.URLError as e:
            logging.exception("llama-server request failed")
            raise

        completion_probs = result.get("completion_probabilities", [])
        if not completion_probs:
            return []

        top_logprobs = completion_probs[0].get("top_logprobs", [])
        predictions: list[tuple[str, float]] = []
        seen: set[str] = set()
        for item in top_logprobs:
            token = item.get("token", "")
            logp = item.get("logprob", float("-inf"))
            text = token.strip().lower()
            if not text:
                continue
            ch = text[0]
            if ch in seen or ch not in CHAR_TO_KEY:
                continue
            seen.add(ch)
            try:
                prob = math.exp(logp)
            except OverflowError:
                prob = 0.0
            predictions.append((ch, prob))
            if len(predictions) >= top_k:
                break
        return predictions

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Database:
    """Stores keystrokes and predictions for later analysis."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    started_at REAL NOT NULL,
                    engine TEXT NOT NULL,
                    model_path TEXT
                );
                CREATE TABLE IF NOT EXISTS keystrokes (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER REFERENCES sessions(id),
                    ts REAL NOT NULL,
                    context TEXT NOT NULL,
                    key TEXT NOT NULL,
                    engine TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER REFERENCES sessions(id),
                    ts REAL NOT NULL,
                    context TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    candidate TEXT NOT NULL,
                    probability REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_keystrokes_session ON keystrokes(session_id);
                CREATE INDEX IF NOT EXISTS idx_predictions_session ON predictions(session_id);
                """
            )
            self.conn.commit()
        except sqlite3.Error:
            logging.exception("Failed to initialize database at %s", DB_PATH)
            raise

    def start_session(self, engine: str, model_path: str | None = None) -> int:
        try:
            cur = self.conn.execute(
                "INSERT INTO sessions (started_at, engine, model_path) VALUES (?, ?, ?)",
                (time.time(), engine, model_path),
            )
            self.conn.commit()
            return int(cur.lastrowid)
        except sqlite3.Error:
            logging.exception("Failed to start session")
            raise

    def log_keystroke(
        self, session_id: int, context: str, key: str, engine: str
    ) -> None:
        try:
            self.conn.execute(
                "INSERT INTO keystrokes (session_id, ts, context, key, engine) VALUES (?, ?, ?, ?, ?)",
                (session_id, time.time(), context, key, engine),
            )
        except sqlite3.Error:
            logging.exception("Failed to log keystroke")

    def log_predictions(
        self,
        session_id: int,
        context: str,
        engine: str,
        predictions: Sequence[tuple[str, float]],
    ) -> None:
        try:
            now = time.time()
            rows = [
                (session_id, now, context, engine, c, p) for c, p in predictions
            ]
            self.conn.executemany(
                "INSERT INTO predictions (session_id, ts, context, engine, candidate, probability) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            self.conn.commit()
        except sqlite3.Error:
            logging.exception("Failed to log predictions")

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:
            logging.exception("Failed to close database")


def _load_or_seed_corpus() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CORPUS_PATH.exists():
        CORPUS_PATH.write_text(DEFAULT_CORPUS, errors="replace")
    return CORPUS_PATH.read_text(errors="replace")


def _append_corpus(text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("a", errors="replace") as f:
        f.write(text)


def _safe_addstr(scr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    if y < 0 or x < 0:
        return
    try:
        max_y, max_x = scr.getmaxyx()
        if y >= max_y or x >= max_x:
            return
        available = max_x - x
        if available <= 0:
            return
        if len(text) > available:
            text = text[:available]
        scr.addstr(y, x, text, attr)
    except curses.error:
        pass


def _draw_key(
    scr: curses.window, y: int, x: int, width: int, label: str, attr: int
) -> None:
    display = _display_for(label)
    inner = width - 2
    if len(display) > inner:
        display = display[:inner]
    left_pad = (inner - len(display)) // 2
    right_pad = inner - len(display) - left_pad

    _safe_addstr(scr, y, x, "+" + "-" * inner + "+", attr)
    mid = "|" + " " * left_pad + display + " " * right_pad + "|"
    _safe_addstr(scr, y + 1, x, mid, attr)
    _safe_addstr(scr, y + 2, x, "+" + "-" * inner + "+", attr)


def _attr_for(rank: int, mode: str) -> int:
    if not curses.has_colors():
        if rank == -1:
            return curses.A_DIM
        if rank == 0 and mode == "single":
            return curses.A_BOLD | curses.A_REVERSE
        if rank <= 0:
            return curses.A_BOLD
        if rank <= 2:
            return curses.A_NORMAL
        return curses.A_DIM

    if rank == -1:
        return curses.A_DIM | curses.color_pair(3)
    if rank == 0 and mode == "single":
        return curses.A_BOLD | curses.A_REVERSE | curses.color_pair(4)
    if rank == 0:
        return curses.A_BOLD | curses.color_pair(4)
    if rank == 1:
        return curses.A_BOLD | curses.color_pair(2)
    if rank <= 3:
        return curses.A_BOLD | curses.color_pair(1)
    return curses.A_DIM | curses.color_pair(3)


def _draw_keyboard(
    scr: curses.window, predictions: Sequence[tuple[str, float]], mode: str
) -> None:
    max_y, max_x = scr.getmaxyx()
    if max_y < 20 or max_x < 80:
        _safe_addstr(scr, 10, 2, "terminal too small, resize to at least 80x20")
        return

    pred_ranks: dict[str, int] = {}
    for i, (ch, _score) in enumerate(predictions):
        key = CHAR_TO_KEY.get(ch)
        if key and key not in pred_ranks:
            pred_ranks[key] = i

    start_y = KB_START_Y
    total_width = sum(w for _, w in KB_ROWS[0]) + len(KB_ROWS[0]) - 1
    start_x = max(0, (max_x - total_width) // 2)

    for r, row in enumerate(KB_ROWS):
        x = start_x
        for label, width in row:
            rank = pred_ranks.get(label, -1)
            attr = _attr_for(rank, mode)
            _draw_key(scr, start_y + r * 4, x, width, label, attr)
            x += width + 1


def _draw_header(
    scr: curses.window,
    buffer: str,
    predictions: Sequence[tuple[str, float]],
    mode: str,
    dirty: bool,
    engine_name: str,
) -> None:
    max_y, max_x = scr.getmaxyx()
    title = "keytypist — live next-key prediction"
    _safe_addstr(scr, 0, 2, title, curses.A_BOLD)
    _safe_addstr(scr, 1, 2, "=" * min(len(title), max_x - 4))

    status = (
        f"mode: {mode}  |  engine: {engine_name}  "
        f"|  dirty: {'yes' if dirty else 'no'}  |  predictions: {len(predictions)}"
    )
    _safe_addstr(scr, 2, 2, status)

    buf_text = f"typed: {buffer}"
    _safe_addstr(scr, 3, 2, buf_text[: max_x - 4])

    pred_text = "next: " + ", ".join(
        f"{repr(c)} {p*100:.0f}%" for c, p in predictions[:6]
    )
    _safe_addstr(scr, 4, 2, pred_text[: max_x - 4], curses.A_BOLD)

    help_text = "F1=toggle mode  Ctrl+S=save  Esc/Ctrl+C=quit"
    help_y = KB_START_Y + len(KB_ROWS) * 4
    if help_y < max_y:
        _safe_addstr(scr, help_y, 2, help_text[: max_x - 4], curses.A_DIM)


def _main_tui(stdscr: curses.window, engine: Engine, db: Database) -> None:
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)
    curses.noecho()
    curses.cbreak()

    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_BLUE, -1)
        curses.init_pair(4, curses.COLOR_YELLOW, -1)

    engine_name = getattr(engine, "model_path", None)
    if engine_name is None:
        engine_name = "ngram"
    else:
        engine_name = Path(engine_name).name
    session_id = db.start_session(
        engine="ngram" if isinstance(engine, NgramEngine) else "llama",
        model_path=str(engine_name) if not isinstance(engine, NgramEngine) else None,
    )

    buffer = ""
    mode = "candidates"
    dirty = False

    while True:
        stdscr.clear()
        predictions = engine.predict(buffer, top_k=TOP_K)
        db.log_predictions(session_id, buffer, str(engine_name), predictions)
        _draw_header(stdscr, buffer, predictions, mode, dirty, str(engine_name))
        _draw_keyboard(stdscr, predictions, mode)
        stdscr.refresh()

        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break

        if ch == curses.ERR:
            continue

        if ch == 27:
            break
        if ch == 3:
            break
        if ch == curses.KEY_F1 or ch == 265:
            mode = "single" if mode == "candidates" else "candidates"
            continue
        if ch == 19:
            _append_corpus(buffer)
            dirty = False
            continue
        if ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            if buffer:
                buffer = buffer[:-1]
            continue
        if ch == curses.KEY_RESIZE:
            continue

        if 32 <= ch <= 126:
            char = chr(ch)
            if isinstance(engine, NgramEngine):
                engine.observe(buffer, char)
            db.log_keystroke(session_id, buffer, char, str(engine_name))
            buffer += char
            dirty = True

    if dirty:
        _append_corpus(buffer)


def _build_engine(args: argparse.Namespace) -> Engine:
    if args.engine == "ngram":
        ngram = NgramEngine(ORDER)
        corpus = _load_or_seed_corpus()
        ngram.feed(corpus)
        logging.info("N-gram engine ready. corpus chars: %d", len(corpus))
        return ngram

    if args.engine == "llama":
        if not args.model or not args.model.exists():
            raise FileNotFoundError(
                "--model /path/to/model.gguf is required for --engine llama"
            )
        return LlamaCppEngine(args.model, n_gpu_layers=args.n_gpu_layers)

    if args.engine == "llama-server":
        if not args.model or not args.model.exists():
            raise FileNotFoundError(
                "--model /path/to/model.gguf is required for --engine llama-server"
            )
        return LlamaServerEngine(
            args.model,
            host=args.host,
            port=args.port,
            n_gpu_layers=args.n_gpu_layers,
        )

    raise ValueError(f"unknown engine: {args.engine}")


def _smoke(engine: Engine) -> None:
    logging.info("Smoke test with %s", type(engine).__name__)
    print("predict('the q'):", engine.predict("the q"))
    print("predict('hello '):", engine.predict("hello "))
    engine.close()


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description="keytypist next-key prediction TUI")
    parser.add_argument(
        "--engine",
        choices=["ngram", "llama", "llama-server"],
        default="ngram",
        help="prediction engine",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="path to .gguf model for llama or llama-server",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="llama-server host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="llama-server port",
    )
    parser.add_argument(
        "--n-gpu-layers",
        type=int,
        default=-1,
        help="GPU layers for llama engines (-1 = all)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="SQLite database path",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run a non-curses smoke test",
    )
    args = parser.parse_args()

    try:
        engine = _build_engine(args)
    except Exception:
        logging.exception("Engine setup failed")
        raise

    if args.smoke:
        _smoke(engine)
        return 0

    db = Database(args.db)
    try:
        curses.wrapper(_main_tui, engine, db)
    except Exception:
        logging.exception("TUI crashed")
        raise
    finally:
        db.close()
        engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
