"""Lightweight console logging for lab / headless runs (Phase A+).

Intended first consumers: ``HeadlessGameRunner`` and ``run_headless.py``.
Interactive ``main.py`` and core strategy dumps are **not** migrated yet.

Levels (numeric, higher = more severe / always shown when threshold is high):

  TRACE  5   — very chatty dig-in
  DEBUG 10   — step detail (IP steps, each roll tag)
  INFO  20   — milestones (start, IP done, progress every N, result)
  WARN  30   — operator warnings
  ERROR 40   — failures / stuck diagnostics

Default threshold: INFO.

CLI mapping (run_headless):
  -q / --quiet  → WARN
  (default)     → INFO
  -v / --verbose → DEBUG
  --trace       → TRACE

Environment override (optional):
  HEADLESS_LOG_LEVEL = TRACE|DEBUG|INFO|WARN|ERROR  (or 5/10/20/30/40)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional, TextIO, Union

TRACE = 5
DEBUG = 10
INFO = 20
WARN = 30
ERROR = 40

LEVEL_NAMES = {
    TRACE: "TRACE",
    DEBUG: "DEBUG",
    INFO: "INFO",
    WARN: "WARN",
    ERROR: "ERROR",
}

_NAME_TO_LEVEL = {
    "TRACE": TRACE,
    "DEBUG": DEBUG,
    "INFO": INFO,
    "WARN": WARN,
    "WARNING": WARN,
    "ERROR": ERROR,
}

# Process-wide threshold (mutable for CLI).
_threshold: int = INFO
_stream: TextIO = sys.stdout
_show_level_prefix: bool = False

# ANSI colors for stderr warn/error (Windows Terminal / modern PowerShell OK).
_ANSI_RESET = "\033[0m"
_ANSI_RED = "\033[91m"
_ANSI_YELLOW = "\033[93m"
_color_enabled: Optional[bool] = None


def _enable_windows_ansi() -> None:
    """Best-effort VT processing for older Windows consoles (cmd.exe)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for std_id in (-11, -12):  # STDOUT, STDERR
            handle = kernel32.GetStdHandle(std_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _use_color(stream: Optional[TextIO] = None) -> bool:
    """True when ANSI color is allowed (TTY, not NO_COLOR)."""
    global _color_enabled
    if _color_enabled is not None:
        return bool(_color_enabled)
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        _enable_windows_ansi()
        return True
    try:
        target = stream if stream is not None else sys.stderr
        if bool(getattr(target, "isatty", lambda: False)()):
            _enable_windows_ansi()
            return True
        return False
    except Exception:
        return False


def set_color_enabled(enabled: Optional[bool]) -> None:
    """Force color on/off, or ``None`` to auto-detect (TTY + env)."""
    global _color_enabled
    _color_enabled = enabled


def parse_level(value: Union[str, int, None], default: int = INFO) -> int:
    """Parse a level name or int; return ``default`` on failure."""
    if value is None or value == "":
        return default
    if isinstance(value, int):
        return int(value)
    text = str(value).strip().upper()
    if text in _NAME_TO_LEVEL:
        return _NAME_TO_LEVEL[text]
    try:
        return int(text)
    except Exception:
        return default


def get_level() -> int:
    return int(_threshold)


def set_level(level: Union[str, int]) -> int:
    """Set process-wide log threshold; return the resolved level."""
    global _threshold
    _threshold = parse_level(level, default=INFO)
    return _threshold


def set_stream(stream: TextIO) -> None:
    global _stream
    _stream = stream


def set_show_level_prefix(enabled: bool) -> None:
    """When True, lines look like ``[INFO] message``."""
    global _show_level_prefix
    _show_level_prefix = bool(enabled)


def configure(
    *,
    level: Optional[Union[str, int]] = None,
    quiet: bool = False,
    verbose: bool = False,
    trace: bool = False,
    show_level_prefix: Optional[bool] = None,
    use_env: bool = True,
) -> int:
    """Configure threshold from CLI-style flags and optional env.

    Precedence (highest last wins among flags):
      env HEADLESS_LOG_LEVEL (if use_env and set)
      quiet → WARN
      default INFO
      verbose → DEBUG
      trace → TRACE
      explicit ``level=`` overrides all of the above
    """
    resolved = INFO
    if use_env:
        env = os.environ.get("HEADLESS_LOG_LEVEL") or os.environ.get("CATAN_LOG_LEVEL")
        if env:
            resolved = parse_level(env, default=INFO)
    if quiet:
        resolved = WARN
    if verbose:
        resolved = DEBUG
    if trace:
        resolved = TRACE
    if level is not None:
        resolved = parse_level(level, default=resolved)
    set_level(resolved)
    if show_level_prefix is not None:
        set_show_level_prefix(show_level_prefix)
    return get_level()


def enabled(level: int) -> bool:
    """True if a message at ``level`` would be emitted."""
    return int(level) >= int(_threshold)


def log(level: int, msg: Any = "", *args: Any, **kwargs: Any) -> None:
    """Emit ``msg`` if ``level >= threshold``. Supports % or format-style args lightly."""
    if not enabled(level):
        return
    text = str(msg)
    if args:
        try:
            text = text % args
        except Exception:
            try:
                text = text.format(*args)
            except Exception:
                text = f"{text} {' '.join(str(a) for a in args)}"
    if _show_level_prefix:
        name = LEVEL_NAMES.get(int(level), str(level))
        line = f"[{name}] {text}"
    else:
        line = text
    try:
        print(line, file=_stream, flush=kwargs.get("flush", True))
    except Exception:
        try:
            print(line, file=sys.stderr)
        except Exception:
            pass


def trace(msg: Any = "", *args: Any, **kwargs: Any) -> None:
    log(TRACE, msg, *args, **kwargs)


def debug(msg: Any = "", *args: Any, **kwargs: Any) -> None:
    log(DEBUG, msg, *args, **kwargs)


def info(msg: Any = "", *args: Any, **kwargs: Any) -> None:
    log(INFO, msg, *args, **kwargs)


def warn(msg: Any = "", *args: Any, **kwargs: Any) -> None:
    if not enabled(WARN):
        return
    text = str(msg)
    if args:
        try:
            text = text % args
        except Exception:
            try:
                text = text.format(*args)
            except Exception:
                text = f"{text} {' '.join(str(a) for a in args)}"
    if _show_level_prefix:
        text = f"[WARN] {text}"
    if _use_color(_stream):
        text = f"{_ANSI_YELLOW}{text}{_ANSI_RESET}"
    try:
        print(text, file=_stream, flush=kwargs.get("flush", True))
    except Exception:
        log(WARN, msg, *args, **kwargs)


def warning(msg: Any = "", *args: Any, **kwargs: Any) -> None:
    warn(msg, *args, **kwargs)


def error(msg: Any = "", *args: Any, **kwargs: Any) -> None:
    # Errors go to stderr (red when the terminal supports ANSI).
    if not enabled(ERROR):
        return
    text = str(msg)
    if args:
        try:
            text = text % args
        except Exception:
            text = f"{text} {' '.join(str(a) for a in args)}"
    if _show_level_prefix:
        text = f"[ERROR] {text}"
    if _use_color(sys.stderr):
        text = f"{_ANSI_RED}{text}{_ANSI_RESET}"
    try:
        print(text, file=sys.stderr, flush=True)
    except Exception:
        log(ERROR, msg, *args, **kwargs)


def level_name(level: Optional[int] = None) -> str:
    lv = get_level() if level is None else int(level)
    return LEVEL_NAMES.get(lv, str(lv))


def is_no_gui() -> bool:
    """True when ``NO_GUI_AT_ALL_TF`` is set (operator-owned).

    When True, ``digin`` routes through leveled ``log`` (quiet at INFO).
    """
    try:
        from core.constants import NO_GUI_AT_ALL_TF

        return bool(NO_GUI_AT_ALL_TF)
    except Exception:
        return False


def execution_debug_print(
    game: Any,
    msg: Any = "",
    *args: Any,
    level: int = DEBUG,
    **kwargs: Any,
) -> None:
    """AI DCard / execution dig-in lines gated by ``game.execution_debug_print_tf``.

    When the flag is off: no output.
    When on:
      - interactive (``NO_GUI_AT_ALL_TF=False``): always print (legacy)
      - headless (``NO_GUI_AT_ALL_TF=True``): ``digin`` at ``level`` (DEBUG → ``-v``)
    """
    try:
        if not bool(getattr(game, "execution_debug_print_tf", False)):
            return
    except Exception:
        return
    digin(msg, *args, level=level, **kwargs)


def digin(msg: Any = "", *args: Any, level: int = DEBUG, **kwargs: Any) -> None:
    """Diagnostic / dig-in chatter (Slice A/B, Markov dumps, advance_turn, …).

    Policy (operator owns ``NO_GUI_AT_ALL_TF``):
      - ``False`` (interactive): always ``print`` (legacy behaviour).
      - ``True`` (headless): route through ``log(level, …)`` so default INFO
        stays quiet; use ``-v`` / ``--trace`` to re-enable.

    Preferred levels for common offenders:
      - ``advance_turn executed`` → DEBUG
      - Slice A/B dump → DEBUG (or TRACE for multi-line body)
      - Markov INIT candidate lines → TRACE
      - Markov precompute banners → DEBUG
    """
    text = str(msg)
    if args:
        try:
            text = text % args
        except Exception:
            try:
                text = text.format(*args)
            except Exception:
                text = f"{text} {' '.join(str(a) for a in args)}"

    if is_no_gui():
        log(int(level), text, **kwargs)
        return
    # Interactive dig-in: always stdout (legacy print behaviour).
    try:
        print(text, file=sys.stdout, flush=True)
    except Exception:
        try:
            print(text)
        except Exception:
            pass
