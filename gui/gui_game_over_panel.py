"""Post-game UI (W3 + S7a + G8): Statistics ↔ Playboard toggle + New Game.

After ``game.game_over``:

* A **right-slot strip** (``POST_GAME_STRIP_RECT`` / TwB family) offers
  **Statistics** | **Playboard** | **New Game**.
* **Statistics (S7a)** fills ``STATISTICS_CANVAS_RECT`` — the full left stack
  (human buttons + playboard + scoreboard) — with multi-table stats.
  The strip stays on the right so it never overlaps the canvas.
* **Playboard** clears the canvas and restores the frozen board / scoreboard.
* **New Game** (G8) enters OKY/NOK confirm; OKY captures screenshots then sets
  ``post_game_ui["request_new_game"]`` for ``main`` to recreate the session.

State lives on ``game.post_game_ui`` (also mirrored lightly on ``game.gui``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

from pathlib import Path
from datetime import datetime
import os

from gui.gui_constants import (
    WIN,
    COLORS,
    Font,
    HUMAN_BUTTON_PANEL_RECT,
    SOUNDS,
    PLAYBOARD_RECT,
    SCOREBOARD_RECT,
    TWITTER_PANEL_RECT,
)

try:
    from gui.gui_constants import GAME_OVER_PANEL_RECT
except Exception:  # pragma: no cover
    from gui.gui_constants import TRADE_BANK_PANEL_RECT as GAME_OVER_PANEL_RECT

try:
    from gui.gui_constants import (
        STATISTICS_CANVAS_RECT,
        POST_GAME_STRIP_RECT,
        POST_GAME_STRIP_BUTTON_RECTS,
        post_game_strip_button_rects,
        post_game_confirm_new_game_rects,
    )
except Exception:  # pragma: no cover
    STATISTICS_CANVAS_RECT = pygame.Rect(
        min(PLAYBOARD_RECT.x, HUMAN_BUTTON_PANEL_RECT.x, SCOREBOARD_RECT.x),
        min(PLAYBOARD_RECT.y, HUMAN_BUTTON_PANEL_RECT.y, SCOREBOARD_RECT.y),
        max(PLAYBOARD_RECT.right, HUMAN_BUTTON_PANEL_RECT.right, SCOREBOARD_RECT.right)
        - min(PLAYBOARD_RECT.x, HUMAN_BUTTON_PANEL_RECT.x, SCOREBOARD_RECT.x),
        max(PLAYBOARD_RECT.bottom, HUMAN_BUTTON_PANEL_RECT.bottom, SCOREBOARD_RECT.bottom)
        - min(PLAYBOARD_RECT.y, HUMAN_BUTTON_PANEL_RECT.y, SCOREBOARD_RECT.y),
    )
    POST_GAME_STRIP_RECT = pygame.Rect(
        GAME_OVER_PANEL_RECT.x,
        GAME_OVER_PANEL_RECT.y,
        GAME_OVER_PANEL_RECT.width,
        GAME_OVER_PANEL_RECT.height,
    )

    def post_game_strip_button_rects(strip_rect=None):
        panel = strip_rect if strip_rect is not None else POST_GAME_STRIP_RECT
        pad, gap, h = 10, 8, 36
        y = panel.bottom - h - 12
        bw = max(70, (panel.width - 2 * pad - 2 * gap) // 3)
        x0 = panel.x + pad
        return {
            "statistics": pygame.Rect(x0, y, bw, h),
            "playboard": pygame.Rect(x0 + bw + gap, y, bw, h),
            "new_game": pygame.Rect(x0 + 2 * (bw + gap), y, bw, h),
        }

    def post_game_confirm_new_game_rects(strip_rect=None):
        panel = strip_rect if strip_rect is not None else POST_GAME_STRIP_RECT
        pad, gap, h = 10, 8, 36
        y = panel.bottom - h - 12
        bw = max(90, (panel.width - 2 * pad - gap) // 2)
        x0 = panel.x + pad
        return {
            "confirm_ok": pygame.Rect(x0, y, bw, h),
            "confirm_cancel": pygame.Rect(x0 + bw + gap, y, bw, h),
        }

    POST_GAME_STRIP_BUTTON_RECTS = post_game_strip_button_rects()

try:
    from core.constants import SAVE_PATH
except Exception:  # pragma: no cover
    SAVE_PATH = os.path.join(os.path.expanduser("~"), "Documents", "Projecten", "Python", "Catan_Gen3", "Logs")

# Legacy right-slot rect (TwB family). S7a stats body uses CANVAS_RECT instead.
PANEL_RECT = GAME_OVER_PANEL_RECT
CANVAS_RECT = STATISTICS_CANVAS_RECT
STRIP_PANEL = POST_GAME_STRIP_RECT

VIEW_STATISTICS = "statistics"
VIEW_PLAYBOARD = "playboard"
VIEWS = (VIEW_STATISTICS, VIEW_PLAYBOARD)

# Overview column headers (plan §9)
OVERVIEW_HEADERS = ("TVP", "S", "C", "DC", "LA", "LR")

PLAYER_COLOR_RGB = {
    "Blue": COLORS.get("BLUE", (0, 0, 255)),
    "Red": COLORS.get("RED", (255, 0, 0)),
    "White": COLORS.get("WHITE", (255, 255, 255)),
    "Orange": COLORS.get("ORANGE", (255, 165, 0)),
}


def _empty_state() -> Dict[str, Any]:
    return {
        "active": False,
        "view": VIEW_STATISTICS,
        "winner_id": None,
        "color": "",
        "final_vp": 0,
        "threshold": 10,
        "breakdown": {},
        "standings": [],
        "reason": "",
        "revealed_vp": 0,
        "round": 0,
        "turn": 0,
        "rects": {},
        "request_new_game": False,
        "opened": False,
        "statistics": None,  # S7b frozen snapshot
        "confirm_new_game": False,  # G8: OKY/NOK before New Game
    }


def _state(game: Any) -> Dict[str, Any]:
    """Return mutable post-game UI state on the game (preferred) or gui."""
    if game is None:
        return _empty_state()
    state = getattr(game, "post_game_ui", None)
    if not isinstance(state, dict):
        state = _empty_state()
        try:
            game.post_game_ui = state
        except Exception:
            pass
    # Keep required keys
    base = _empty_state()
    for key, default in base.items():
        state.setdefault(key, default)
    if str(state.get("view") or "") not in VIEWS:
        state["view"] = VIEW_STATISTICS
    # Mirror on gui for any code that peeks there
    try:
        gui = getattr(game, "gui", None)
        if gui is not None:
            setattr(gui, "post_game_ui_state", state)
    except Exception:
        pass
    return state


def is_post_game_ui_active(game: Any) -> bool:
    """True when game is over and post-game UI has been opened."""
    if game is None:
        return False
    if bool(getattr(game, "game_over", False)):
        st = _state(game)
        return bool(st.get("active") or st.get("opened"))
    return bool(_state(game).get("active"))


def is_game_over_panel_active(game: Any) -> bool:
    """True when Statistics body should occupy the shared modal slot."""
    if not is_post_game_ui_active(game):
        return False
    st = _state(game)
    return str(st.get("view") or "") == VIEW_STATISTICS


def is_statistics_view(game: Any) -> bool:
    return is_game_over_panel_active(game)


def clear_game_over_panel_area() -> None:
    """Clear the S7a Statistics canvas (left stack). Also clears legacy right slot."""
    bg = COLORS.get("LGRAY", (210, 210, 210))
    try:
        pygame.draw.rect(WIN, bg, CANVAS_RECT)
    except Exception:
        pass
    try:
        pygame.draw.rect(WIN, bg, PANEL_RECT)
    except Exception:
        pass


def clear_statistics_canvas_area() -> None:
    """Clear only the full left Statistics canvas."""
    try:
        pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), CANVAS_RECT)
    except Exception:
        pass


def _close_competing_panels(game: Any) -> None:
    """Game-over modal beats TwB / TwP / discard / Play DCard."""
    closers: List[Tuple[str, str]] = [
        ("gui.gui_trade_bank_panel", "close_trade_bank_panel"),
        ("gui.gui_trade_player_panel", "close_trade_player_panel"),
        ("gui.gui_discard_panel", "close_discard_panel"),
        ("gui.gui_play_dcard_panel", "close_play_dcard_panel"),
    ]
    for mod_name, fn_name in closers:
        try:
            import importlib

            mod = importlib.import_module(mod_name)
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                fn(game)
        except Exception:
            pass


def _snapshot_from_game(game: Any) -> Dict[str, Any]:
    wr = getattr(game, "win_result", None)
    if isinstance(wr, dict) and wr:
        return dict(wr)
    # Fallback build from winner / standings helpers
    winner = getattr(game, "winner", None)
    breakdown: Dict[str, Any] = {}
    standings: List[Dict[str, Any]] = []
    try:
        from core.victory import vp_breakdown, standings_snapshot

        if winner is not None:
            breakdown = dict(vp_breakdown(winner))
        standings = list(standings_snapshot(game))
    except Exception:
        pass
    return {
        "winner_id": getattr(winner, "id", None) if winner is not None else None,
        "color": str(getattr(winner, "color", "") or "") if winner is not None else "",
        "final_vp": int(breakdown.get("total") or getattr(winner, "victory_points", 0) or 0),
        "threshold": 10,
        "breakdown": breakdown,
        "standings": standings,
        "reason": "game_over",
        "revealed_vp_cards": int(breakdown.get("vp_cards") or 0),
        "round": int(getattr(game, "round", 0) or 0),
        "turn": int(getattr(game, "turn", 0) or 0),
    }


def open_game_over_panel(game: Any, *, win_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Open post-game UI after a win (idempotent).

    Defaults to Statistics view and closes competing right-slot modals.
    """
    if game is None:
        return _empty_state()

    snap = dict(win_result) if isinstance(win_result, dict) and win_result else _snapshot_from_game(game)
    _close_competing_panels(game)

    state = _state(game)
    already = bool(state.get("opened"))
    state.update(
        {
            "active": True,
            "opened": True,
            "view": state.get("view") if already and state.get("view") in VIEWS else VIEW_STATISTICS,
            "winner_id": snap.get("winner_id"),
            "color": str(snap.get("color") or ""),
            "final_vp": int(snap.get("final_vp") or 0),
            "threshold": int(snap.get("threshold") or 10),
            "breakdown": dict(snap.get("breakdown") or {}),
            "standings": list(snap.get("standings") or []),
            "reason": str(snap.get("reason") or ""),
            "revealed_vp": int(
                snap.get("revealed_vp_cards")
                or (snap.get("breakdown") or {}).get("vp_cards")
                or 0
            ),
            "round": int(snap.get("round") or getattr(game, "round", 0) or 0),
            "turn": int(snap.get("turn") or getattr(game, "turn", 0) or 0),
            "rects": {},
            "request_new_game": False,
            "statistics": None,
        }
    )
    # S7b: freeze Overview/Dice/deck tables at open so toggles stay stable
    try:
        from core.game_statistics import collect_endgame_statistics

        state["statistics"] = collect_endgame_statistics(game, post_game_state=state)
    except Exception:
        state["statistics"] = None
    try:
        game.post_game_ui = state
    except Exception:
        pass

    # W4: fanfare plays once in check_and_declare_winner; do not double-play here.
    if not already and not bool(getattr(game, "win_fanfare_played", False)):
        try:
            sound = SOUNDS.get("FANFARE") or SOUNDS.get("ENDGAME") or SOUNDS.get("BELL")
            if sound is not None:
                sound.play()
            setattr(game, "win_fanfare_played", True)
        except Exception:
            pass

    try:
        game.gui.set_button("game_over_panel", True)
    except Exception:
        pass

    return dict(state)


def ensure_post_game_ui(game: Any) -> Dict[str, Any]:
    """Open post-game UI if the game is over but the panel was never opened."""
    if game is None or not bool(getattr(game, "game_over", False)):
        return _state(game) if game is not None else _empty_state()
    st = _state(game)
    if not st.get("opened"):
        return open_game_over_panel(game)
    st["active"] = True
    return st


def set_post_game_view(game: Any, view: str) -> Dict[str, Any]:
    """Switch between statistics and playboard views."""
    st = ensure_post_game_ui(game)
    v = str(view or "").strip().lower()
    if v in ("stats", "stat", "statistics"):
        v = VIEW_STATISTICS
    if v in ("board", "play", "playboard", "review"):
        v = VIEW_PLAYBOARD
    if v not in VIEWS:
        return st
    prev = str(st.get("view") or "")
    st["view"] = v
    st["rects"] = {}
    if v == VIEW_PLAYBOARD:
        try:
            clear_statistics_canvas_area()
        except Exception:
            pass
        # Board was covered by the canvas — restore underlay + strip
        try:
            redraw_playboard_underlay(game)
        except Exception:
            pass
    elif v == VIEW_STATISTICS and prev != VIEW_STATISTICS:
        # Next draw_game_over_panel fills the canvas; no extra work required.
        pass
    return st


def request_new_game(game: Any) -> Dict[str, Any]:
    """G8/G13: enter New Game confirm (Yes/No). Actual start is confirm_ok."""
    st = ensure_post_game_ui(game)
    st["confirm_new_game"] = True
    st["rects"] = {}
    try:
        sound = SOUNDS.get("BUTTON")
        if sound is not None:
            sound.play()
    except Exception:
        pass
    return st


def _commit_new_game(game: Any) -> Dict[str, Any]:
    """Capture endgame screenshots, then flag main to start a fresh game."""
    st = ensure_post_game_ui(game)
    st["confirm_new_game"] = False
    try:
        paths = capture_endgame_screenshots(game)
        st["screenshot_paths"] = paths
        try:
            game.last_endgame_screenshots = dict(paths)
        except Exception:
            pass
        print(f"Endgame screenshots: {paths}")
    except Exception as exc:
        st["screenshot_error"] = str(exc)
        print(f"Endgame screenshot failed: {exc}")
    st["request_new_game"] = True
    try:
        sound = SOUNDS.get("NEXTGAME") or SOUNDS.get("BUTTON")
        if sound is not None:
            sound.play()
    except Exception:
        pass
    return st


def consume_new_game_request(game: Any) -> bool:
    """Return True once if New Game was requested (then clear the flag)."""
    st = _state(game)
    if bool(st.get("request_new_game")):
        st["request_new_game"] = False
        return True
    return False


def close_game_over_panel(game: Any, *, keep_post_game: bool = True) -> None:
    """Hide Statistics body; by default keep the strip (still game over)."""
    st = _state(game)
    if keep_post_game and bool(getattr(game, "game_over", False)):
        st["view"] = VIEW_PLAYBOARD
        st["active"] = True
    else:
        st.update(_empty_state())
    try:
        clear_game_over_panel_area()
    except Exception:
        pass
    try:
        game.gui.set_button("game_over_panel", bool(st.get("active")))
    except Exception:
        pass


# ── Geometry ─────────────────────────────────────────────────────────────────

def _strip_button_rects() -> Dict[str, pygame.Rect]:
    """Three equal buttons inside the post-game strip (from gui_constants)."""
    try:
        return post_game_strip_button_rects(STRIP_PANEL)
    except Exception:
        # Defensive copy of the eager constants snapshot
        return {
            k: pygame.Rect(v)
            for k, v in dict(POST_GAME_STRIP_BUTTON_RECTS or {}).items()
        }


def _reason_label(reason: str) -> str:
    text = str(reason or "").replace("_", " ").strip()
    if not text:
        return ""
    # Common hook reasons → short human text
    mapping = {
        "after ai build city": "City",
        "after human build city": "City",
        "after ai build settlement": "Settlement",
        "after human build settlement": "Settlement",
        "after ai build road": "Longest Road",
        "after human build road": "Longest Road",
        "after human free road": "Longest Road",
        "after tfr complete": "Two Free Roads / LR",
        "after knight largest army": "Largest Army",
        "after ai buy dcard": "Development card",
        "after human buy dcard": "Development card",
        "declared winner": "Victory points",
        "reached victory points": "Victory points",
    }
    low = text.lower()
    for key, label in mapping.items():
        if key in low:
            return label
    if len(text) > 42:
        return text[:39] + "..."
    return text


def _color_rgb(name: str) -> Tuple[int, int, int]:
    return PLAYER_COLOR_RGB.get(str(name or ""), COLORS.get("DGRAY", (100, 100, 100)))


def _font_small():
    try:
        return Font.SMALL.value["regular"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 12)


def _font_normal():
    try:
        return Font.NORMAL.value["regular"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16)


def _font_normal_bold():
    try:
        return Font.NORMAL.value["bold"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16, bold=True)


def _font_large():
    try:
        return Font.LARGE.value["regular"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 22)


def _draw_toggle_button(
    rect: pygame.Rect,
    label: str,
    *,
    active: bool,
    selected: bool = False,
) -> None:
    """Green border when selected/active; gray when inactive option."""
    if selected:
        border = COLORS.get("GREEN", (0, 255, 0))
        text_c = COLORS.get("WHITE", (255, 255, 255))
        fill = (40, 90, 40)
    elif active:
        border = COLORS.get("GREEN", (0, 255, 0))
        text_c = COLORS.get("WHITE", (255, 255, 255))
        fill = COLORS.get("DGRAY", (80, 80, 80))
    else:
        border = COLORS.get("GRAY", (169, 169, 169))
        text_c = COLORS.get("GRAY", (169, 169, 169))
        fill = COLORS.get("DGRAY", (100, 100, 100))
    pygame.draw.rect(WIN, fill, rect)
    pygame.draw.rect(WIN, border, rect, 2)
    font = _font_normal()
    # Shrink label if needed
    text_surf = font.render(label, True, text_c)
    if text_surf.get_width() > rect.width - 6:
        font = _font_small()
        text_surf = font.render(label, True, text_c)
    WIN.blit(text_surf, text_surf.get_rect(center=rect.center))


def draw_post_game_strip(game: Any) -> None:
    """Draw GAME OVER chrome in the **right** TwB slot (G8).

    Left stack is Statistics canvas or Playboard; this strip never overlaps it.
    """
    if not is_post_game_ui_active(game) and not bool(getattr(game, "game_over", False)):
        return
    ensure_post_game_ui(game)
    st = _state(game)
    view = str(st.get("view") or VIEW_STATISTICS)
    confirm = bool(st.get("confirm_new_game"))

    # Right-slot chrome only
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), STRIP_PANEL)
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), STRIP_PANEL, 2)

    # Winner banner
    color_name = str(st.get("color") or "")
    wid = st.get("winner_id")
    final_vp = int(st.get("final_vp") or 0)
    title = _font_normal_bold().render("GAME OVER", True, COLORS.get("BLACK", (0, 0, 0)))
    WIN.blit(title, (STRIP_PANEL.x + 12, STRIP_PANEL.y + 10))

    swatch = pygame.Rect(STRIP_PANEL.x + 12, STRIP_PANEL.y + 38, 18, 18)
    pygame.draw.rect(WIN, _color_rgb(color_name), swatch)
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), swatch, 1)
    winner_line = f"P{wid or '?'} ({color_name or '?'})  {final_vp} VP"
    WIN.blit(
        _font_small().render(winner_line, True, COLORS.get("BLACK", (0, 0, 0))),
        (swatch.right + 8, STRIP_PANEL.y + 38),
    )
    how = _reason_label(str(st.get("reason") or ""))
    sub = f"R{st.get('round', 0)}/T{st.get('turn', 0)}"
    if how:
        sub = f"{sub} · {how}"
    WIN.blit(
        _font_small().render(sub[:42], True, COLORS.get("DGRAY", (80, 80, 80))),
        (STRIP_PANEL.x + 12, STRIP_PANEL.y + 62),
    )

    st["rects"] = dict(st.get("rects") or {})
    if confirm:
        WIN.blit(
            _font_small().render("Start a new game?", True, COLORS.get("BLACK", (0, 0, 0))),
            (STRIP_PANEL.x + 12, STRIP_PANEL.y + 90),
        )
        try:
            crects = post_game_confirm_new_game_rects(STRIP_PANEL)
        except Exception:
            crects = post_game_strip_button_rects(STRIP_PANEL)
        st["rects"].update(crects)
        # G13 (30-G): Yes / No instead of OKY / NOK
        _draw_toggle_button(crects.get("confirm_ok") or crects.get("statistics"), "Yes", active=True, selected=True)
        _draw_toggle_button(crects.get("confirm_cancel") or crects.get("playboard"), "No", active=True, selected=False)
        return

    rects = _strip_button_rects()
    st["rects"].update(rects)

    # Selected view is highlighted; the other two stay green-border enabled (G8).
    _draw_toggle_button(
        rects["statistics"],
        "Statistics",
        active=(view != VIEW_STATISTICS),
        selected=(view == VIEW_STATISTICS),
    )
    _draw_toggle_button(
        rects["playboard"],
        "Playboard",
        active=(view != VIEW_PLAYBOARD),
        selected=(view == VIEW_PLAYBOARD),
    )
    _draw_toggle_button(
        rects["new_game"],
        "New Game",
        active=True,
        selected=False,
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def collect_overview_rows(game: Any, st: Optional[Mapping] = None) -> List[Dict[str, Any]]:
    """Build Overview table rows (delegates to ``core.game_statistics``)."""
    from core.game_statistics import collect_overview_rows as _collect

    return list(_collect(game, st))


def collect_dice_stats(game: Any) -> Dict[str, Any]:
    """Dice histogram 2–12 + total rolls (delegates to ``core.game_statistics``)."""
    from core.game_statistics import collect_dice_stats as _collect

    return dict(_collect(game))


def _endgame_statistics_snapshot(game: Any, st: Optional[Mapping] = None) -> Dict[str, Any]:
    """Return (and optionally cache) the S7a/S7b statistics bundle."""
    from core.game_statistics import collect_endgame_statistics

    state = st if isinstance(st, Mapping) else (_state(game) if game is not None else {})
    cached = state.get("statistics") if isinstance(state, Mapping) else None
    if isinstance(cached, Mapping) and cached.get("overview_rows") is not None:
        # Refresh dice/deck cheaply if frozen mid-game? Prefer freeze at open.
        return dict(cached)
    snap = collect_endgame_statistics(game, post_game_state=state)
    try:
        if game is not None:
            ui = _state(game)
            ui["statistics"] = dict(snap)
    except Exception:
        pass
    return snap


def _draw_table_grid(
    *,
    origin: Tuple[int, int],
    col_widths: Sequence[int],
    headers: Sequence[str],
    body_rows: Sequence[Sequence[str]],
    row_height: int = 18,
    header_bg: Optional[Tuple[int, int, int]] = None,
) -> int:
    """Draw a simple header + body grid; returns y after last row."""
    x0, y = origin
    black = COLORS.get("BLACK", (0, 0, 0))
    white = COLORS.get("WHITE", (255, 255, 255))
    dgray = COLORS.get("DGRAY", (80, 80, 80))
    hbg = header_bg or (200, 200, 210)
    font = _font_small()
    total_w = sum(int(w) for w in col_widths)

    # Header
    pygame.draw.rect(WIN, hbg, pygame.Rect(x0, y, total_w, row_height))
    pygame.draw.rect(WIN, black, pygame.Rect(x0, y, total_w, row_height), 1)
    cx = x0
    for i, head in enumerate(headers):
        w = int(col_widths[i])
        pygame.draw.line(WIN, dgray, (cx, y), (cx, y + row_height), 1)
        label = font.render(str(head), True, black)
        WIN.blit(label, label.get_rect(center=(cx + w // 2, y + row_height // 2)))
        cx += w
    y += row_height

    for r_i, cells in enumerate(body_rows):
        bg = (235, 235, 235) if r_i % 2 else white
        pygame.draw.rect(WIN, bg, pygame.Rect(x0, y, total_w, row_height))
        pygame.draw.rect(WIN, dgray, pygame.Rect(x0, y, total_w, row_height), 1)
        cx = x0
        for i, cell in enumerate(cells):
            w = int(col_widths[i]) if i < len(col_widths) else 40
            pygame.draw.line(WIN, dgray, (cx, y), (cx, y + row_height), 1)
            text = font.render(str(cell), True, black)
            # First column left-ish; numeric columns centered
            if i == 0:
                WIN.blit(text, (cx + 4, y + max(0, (row_height - text.get_height()) // 2)))
            else:
                WIN.blit(text, text.get_rect(center=(cx + w // 2, y + row_height // 2)))
            cx += w
        y += row_height
    return y


def draw_game_over_statistics_panel(game: Any) -> None:
    """S7a–S7e: Overview, Activity, Resource, Dice, RCards/DCards drawn."""
    if not is_game_over_panel_active(game):
        return
    st = _state(game)
    black = COLORS.get("BLACK", (0, 0, 0))
    dgray = COLORS.get("DGRAY", (80, 80, 80))
    lgray = COLORS.get("LGRAY", (210, 210, 210))

    # Full left canvas
    pygame.draw.rect(WIN, lgray, CANVAS_RECT)
    pygame.draw.rect(WIN, black, CANVAS_RECT, 2)

    pad = 12
    x = CANVAS_RECT.x + pad
    y = CANVAS_RECT.y + pad
    content_bottom = CANVAS_RECT.bottom - pad
    content_right = CANVAS_RECT.right - pad

    stats = _endgame_statistics_snapshot(game, st)

    title = _font_large().render("Statistics", True, black)
    WIN.blit(title, (x, y))
    y += title.get_height() + 4

    # Winner line
    color_name = str(st.get("color") or "")
    swatch = pygame.Rect(x, y + 2, 14, 14)
    pygame.draw.rect(WIN, _color_rgb(color_name), swatch)
    pygame.draw.rect(WIN, black, swatch, 1)
    how = _reason_label(str(st.get("reason") or ""))
    head = (
        f"Winner P{st.get('winner_id') or '?'} ({color_name or '?'})  ·  "
        f"{st.get('final_vp', 0)} VP"
    )
    if how:
        head = f"{head}  ·  via {how}"
    WIN.blit(_font_normal().render(head, True, black), (swatch.right + 8, y))
    y += 22
    sub = f"R{st.get('round', 0)}/T{st.get('turn', 0)}  thr={st.get('threshold', 10)}"
    WIN.blit(_font_small().render(sub, True, dgray), (x, y))
    y += 18

    # ── Overview ──────────────────────────────────────────────────────────
    WIN.blit(_font_normal_bold().render("Overview", True, black), (x, y))
    y += 18
    overview = list(stats.get("overview_rows") or [])
    player_w = 90
    num_w = 48
    headers = ("Player",) + OVERVIEW_HEADERS
    col_widths = [player_w] + [num_w] * len(OVERVIEW_HEADERS)
    body: List[List[str]] = []
    for row in overview[:4]:
        mark = "★ " if row.get("winner") else ""
        pid = row.get("player_id")
        col = str(row.get("color") or "")
        label = f"{mark}P{pid} {col}"[:14]
        body.append(
            [
                label,
                str(row.get("TVP", 0)),
                str(row.get("S", 0)),
                str(row.get("C", 0)),
                str(row.get("DC", 0)),
                str(row.get("LA", 0)),
                str(row.get("LR", 0)),
            ]
        )
    if not body:
        body = [["—", "0", "0", "0", "0", "0", "0"]]
    y = _draw_table_grid(
        origin=(x, y),
        col_widths=col_widths,
        headers=headers,
        body_rows=body,
        row_height=18,
    )
    y += 12

    # ── Activity Stats (S7d–e) ─────────────────────────────────────────────
    # G13 (30-G): title→table gap matches Overview (18), not tighter 16.
    if y + 40 < content_bottom:
        WIN.blit(_font_normal_bold().render("Activity Stats", True, black), (x, y))
        y += 18
        act_headers = (
            "Player",
            "TVP",
            "TrP",
            "TrP&A",
            "RC Use",
            "RC Block",
            "DC In",
            "DC Played",
        )
        act_widths = [80, 36, 40, 48, 52, 58, 44, 64]
        activity_rows = list(stats.get("activity_rows") or [])
        act_body: List[List[str]] = []
        for row in activity_rows[:4]:
            mark = "★ " if row.get("winner") else ""
            pid = row.get("player_id")
            col = str(row.get("color") or "")
            label = f"{mark}P{pid} {col}"[:12]
            act_body.append(
                [
                    label,
                    str(row.get("TVP", 0)),
                    str(row.get("TrP", 0)),
                    str(row.get("TrP_A", 0)),
                    str(row.get("RC_Use", 0)),
                    str(row.get("RC_Block", 0)),
                    str(row.get("DC_In", 0)),
                    str(row.get("DC_Played", 0)),
                ]
            )
        if not act_body:
            act_body = [["—"] + ["0"] * 7]
        y = _draw_table_grid(
            origin=(x, y),
            col_widths=act_widths,
            headers=act_headers,
            body_rows=act_body,
            row_height=17,
        )
        WIN.blit(
            _font_small().render(
                "TrP=offers presented · TrP&A=deals done · RC Use=spent · Block=robber denied · DC Played excl. VP",
                True,
                dgray,
            ),
            (x, y + 2),
        )
        y += 16
        y += 6

    # ── Resource Stats (S7c, per player from ledger) ───────────────────────
    if y + 50 < content_bottom:
        WIN.blit(_font_normal_bold().render("Resource Stats", True, black), (x, y))
        y += 16
        # Group label row (In / Loss)
        res_headers = (
            "Player",
            "TVP",
            "TRC In",
            "TRC Loss",
            "TRC Nett",
            "DR",
            "Rob",
            "DC",
            "Tr",
            "DR=7",
            "Rob",
            "DC",
            "Tr",  # G13: loss-side TwP+TwB (same label as In-side Tr)
        )
        # Fit to canvas width
        base_w = [70, 34, 48, 54, 54, 34, 34, 34, 34, 40, 34, 34, 34]
        table_w = sum(base_w)
        max_w = max(200, content_right - x)
        if table_w > max_w:
            scale = max_w / float(table_w)
            res_widths = [max(28, int(w * scale)) for w in base_w]
        else:
            res_widths = list(base_w)
        # Mini group captions above in/out blocks
        try:
            # col index 5–8 = In breakdown, 9–12 = Loss
            in_x = x + sum(res_widths[:5])
            loss_x = x + sum(res_widths[:9])
            WIN.blit(
                _font_small().render("── RCards In ──", True, dgray),
                (in_x, y),
            )
            WIN.blit(
                _font_small().render("── RCards Loss ──", True, dgray),
                (loss_x, y),
            )
            y += 12
        except Exception:
            pass

        resource_rows = list(stats.get("resource_rows") or [])
        res_body: List[List[str]] = []
        for row in resource_rows[:4]:
            mark = "★ " if row.get("winner") else ""
            pid = row.get("player_id")
            col = str(row.get("color") or "")
            label = f"{mark}P{pid} {col}"[:12]
            res_body.append(
                [
                    label,
                    str(row.get("TVP", 0)),
                    str(row.get("TRC_In", 0)),
                    str(row.get("TRC_Loss", 0)),
                    str(row.get("TRC_Nett", 0)),
                    str(row.get("in_DR", 0)),
                    str(row.get("in_Rob", 0)),
                    str(row.get("in_DC", 0)),
                    str(row.get("in_Tr", 0)),
                    str(row.get("loss_DR7", 0)),
                    str(row.get("loss_Rob", 0)),
                    str(row.get("loss_DC", 0)),
                    str(row.get("loss_Tr", 0)),
                ]
            )
        if not res_body:
            res_body = [["—"] + ["0"] * 12]
        y = _draw_table_grid(
            origin=(x, y),
            col_widths=res_widths,
            headers=res_headers,
            body_rows=res_body,
            row_height=17,
        )
        meta = dict(stats.get("meta") or {})
        if meta.get("resource_source") == "no_ledger" or meta.get("ledger_event_count", 0) == 0:
            WIN.blit(
                _font_small().render(
                    "(no turn ledger — Resource Stats zeros; Nett ≠ cards left in hand)",
                    True,
                    dgray,
                ),
                (x, y + 2),
            )
            y += 14
        else:
            WIN.blit(
                _font_small().render(
                    "TRC Nett = In−Loss (not hand size). Buy spends in Loss only. Tr = TwP+TwB.",
                    True,
                    dgray,
                ),
                (x, y + 2),
            )
            y += 14
        y += 8

    # ── Dice Stats ────────────────────────────────────────────────────────
    if y + 40 < content_bottom:
        WIN.blit(_font_normal_bold().render("Dice Stats", True, black), (x, y))
        y += 18
        dice = dict(stats.get("dice") or collect_dice_stats(game))
        faces = list(range(2, 13))
        d_headers = ["Total"] + [str(f) for f in faces]
        d_widths = [54] + [36] * 11
        table_w = sum(d_widths)
        max_w = max(200, content_right - x)
        if table_w > max_w:
            scale = max_w / float(table_w)
            d_widths = [max(22, int(w * scale)) for w in d_widths]
        hist = dice.get("hist") or [0] * 13
        d_body = [
            [str(dice.get("total", 0))]
            + [str(hist[f] if f < len(hist) else 0) for f in faces]
        ]
        y = _draw_table_grid(
            origin=(x, y),
            col_widths=d_widths,
            headers=d_headers,
            body_rows=d_body,
            row_height=18,
        )
        y += 12

    # ── RCards Stats (game-level production drawn) ────────────────────────
    if y + 40 < content_bottom:
        WIN.blit(
            _font_normal_bold().render("RCards Stats (drawn by production)", True, black),
            (x, y),
        )
        y += 18
        from core.game_statistics import RCARD_KEYS, RCARD_SHORT

        rc = dict(stats.get("rcards_drawn") or {})
        by_r = dict(rc.get("by_resource") or {})
        r_headers = list(RCARD_SHORT) + ["Total"]
        r_widths = [48] * len(RCARD_SHORT) + [54]
        r_body = [
            [str(int(by_r.get(RCARD_KEYS[i], 0))) for i in range(len(RCARD_KEYS))]
            + [str(int(rc.get("total", 0)))]
        ]
        y = _draw_table_grid(
            origin=(x, y),
            col_widths=r_widths,
            headers=r_headers,
            body_rows=r_body,
            row_height=18,
        )
        src = str(rc.get("source") or "")
        if src == "no_ledger":
            WIN.blit(
                _font_small().render(
                    "(no turn ledger — production totals unavailable)",
                    True,
                    dgray,
                ),
                (x, y + 2),
            )
            y += 14
        y += 10

    # ── DCards Stats (game-level drawn from bank) ─────────────────────────
    if y + 40 < content_bottom:
        WIN.blit(
            _font_normal_bold().render("DCards Stats (drawn from bank)", True, black),
            (x, y),
        )
        y += 18
        from core.game_statistics import DCARD_KEYS, DCARD_SHORT

        dc = dict(stats.get("dcards_drawn") or {})
        by_t = dict(dc.get("by_type") or {})
        dc_headers = list(DCARD_SHORT) + ["Total"]
        dc_widths = [56, 56, 48, 48, 70, 54]
        dc_body = [
            [str(int(by_t.get(DCARD_KEYS[i], 0))) for i in range(len(DCARD_KEYS))]
            + [str(int(dc.get("total_drawn", 0)))]
        ]
        y = _draw_table_grid(
            origin=(x, y),
            col_widths=dc_widths,
            headers=dc_headers,
            body_rows=dc_body,
            row_height=18,
        )
        y += 10

    # Footer
    if y + 30 < content_bottom:
        note = "S7a–S7e · Overview · Activity · Resource · Dice · Deck"
        WIN.blit(_font_small().render(note, True, dgray), (x, y))
        y += 16

    footer = f"canvas {CANVAS_RECT.width}×{CANVAS_RECT.height}  ·  toggle strip on left"
    WIN.blit(
        _font_small().render(footer, True, dgray),
        (x, min(y + 4, content_bottom - 2) if content_bottom > y else CANVAS_RECT.bottom - 16),
    )


def draw_game_over_panel(game: Any) -> None:
    """Draw Statistics canvas (if active) then strip on top (z-order)."""
    if bool(getattr(game, "game_over", False)):
        ensure_post_game_ui(game)
    if not is_post_game_ui_active(game):
        return
    # Canvas first so strip buttons paint above it and stay clickable.
    if is_game_over_panel_active(game):
        draw_game_over_statistics_panel(game)
    draw_post_game_strip(game)


def handle_game_over_click(game: Any, pos: Sequence[int]) -> bool:
    """Handle strip / panel clicks. Returns True if the click was consumed."""
    if not bool(getattr(game, "game_over", False)) and not is_post_game_ui_active(game):
        return False
    ensure_post_game_ui(game)
    st = _state(game)
    rects = dict(st.get("rects") or {})

    try:
        point = (int(pos[0]), int(pos[1]))
    except Exception:
        return False

    # G8: New Game confirmation mode
    if bool(st.get("confirm_new_game")):
        try:
            crects = post_game_confirm_new_game_rects(STRIP_PANEL)
        except Exception:
            crects = _strip_button_rects()
        st["rects"] = dict(rects)
        st["rects"].update(crects)
        ok_r = crects.get("confirm_ok")
        cancel_r = crects.get("confirm_cancel")
        if ok_r is not None and ok_r.collidepoint(point):
            _commit_new_game(game)
            return True
        if cancel_r is not None and cancel_r.collidepoint(point):
            st["confirm_new_game"] = False
            st["rects"] = {}
            try:
                s = SOUNDS.get("BUTTON")
                if s is not None:
                    s.play()
            except Exception:
                pass
            return True
        if STRIP_PANEL.collidepoint(point):
            return True
        return True  # modal confirm absorbs clicks

    # Always recompute strip rects so clicks work even before first draw
    strip = _strip_button_rects()
    rects.update(strip)
    st["rects"] = rects

    if strip["statistics"].collidepoint(point):
        if str(st.get("view") or "") != VIEW_STATISTICS:
            set_post_game_view(game, VIEW_STATISTICS)
            try:
                s = SOUNDS.get("BUTTON")
                if s is not None:
                    s.play()
            except Exception:
                pass
        return True

    if strip["playboard"].collidepoint(point):
        if str(st.get("view") or "") != VIEW_PLAYBOARD:
            set_post_game_view(game, VIEW_PLAYBOARD)
            try:
                s = SOUNDS.get("BUTTON")
                if s is not None:
                    s.play()
            except Exception:
                pass
        return True

    if strip["new_game"].collidepoint(point):
        request_new_game(game)
        return True

    # Statistics full canvas: swallow clicks so board tools do not fire underneath
    if is_game_over_panel_active(game) and CANVAS_RECT.collidepoint(point):
        return True

    # Strip panel area swallows leftover clicks (frozen controls)
    if STRIP_PANEL.collidepoint(point):
        return True

    return False


def handle_game_over_key(game: Any, key: int) -> bool:
    """ESC → Playboard (review). Returns True if handled."""
    if not bool(getattr(game, "game_over", False)):
        return False
    ensure_post_game_ui(game)
    try:
        if key == pygame.K_ESCAPE:
            set_post_game_view(game, VIEW_PLAYBOARD)
            return True
    except Exception:
        pass
    return False


# Aliases used by plan / event_handler
def handle_game_over_panel_click(game: Any, pos: Sequence[int]) -> bool:
    return handle_game_over_click(game, pos)


# ── W4 endgame screenshots ───────────────────────────────────────────────────

def _clip_rect_to_win(rect: pygame.Rect) -> Optional[pygame.Rect]:
    try:
        area = WIN.get_rect()
        clipped = rect.clip(area)
        if clipped.width <= 0 or clipped.height <= 0:
            return None
        return clipped
    except Exception:
        return None


def _save_regions_composite(
    rects: Sequence[pygame.Rect],
    *,
    name_prefix: str,
    background: Optional[Tuple[int, int, int]] = None,
) -> str:
    """Blit multiple screen rects into one image (bounding box) and save to SAVE_PATH."""
    valid: List[pygame.Rect] = []
    for r in rects:
        if r is None:
            continue
        try:
            rr = pygame.Rect(r)
        except Exception:
            continue
        clipped = _clip_rect_to_win(rr)
        if clipped is not None:
            valid.append(clipped)
    if not valid:
        raise RuntimeError("no valid rects for screenshot")

    min_x = min(r.x for r in valid)
    min_y = min(r.y for r in valid)
    max_x = max(r.right for r in valid)
    max_y = max(r.bottom for r in valid)
    w = max(1, max_x - min_x)
    h = max(1, max_y - min_y)
    bg = background if background is not None else COLORS.get("LGRAY", (210, 210, 210))
    surf = pygame.Surface((w, h))
    surf.fill(bg)
    for r in valid:
        try:
            piece = WIN.subsurface(r).copy()
            surf.blit(piece, (r.x - min_x, r.y - min_y))
        except Exception:
            continue

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    Path(SAVE_PATH).mkdir(parents=True, exist_ok=True)
    filename = os.path.join(SAVE_PATH, f"{name_prefix}_{timestamp}.png")
    pygame.image.save(surf, filename)
    return filename


def redraw_playboard_underlay(game: Any) -> None:
    """Restore board + scoreboard + events under the cleared Statistics canvas.

    Used when switching to Playboard view so the left stack is not left blank.
    Does not force Statistics canvas; draws strip via ``draw_post_game_strip``.
    """
    gui = getattr(game, "gui", None)
    if gui is None:
        return
    try:
        if hasattr(gui, "draw_board_base") and getattr(game, "board", None) is not None:
            gui.draw_board_base(game.board)
            if hasattr(gui, "draw_all_permanent_buildings"):
                gui.draw_all_permanent_buildings(game.board)
            if hasattr(gui, "draw_robber_from_board"):
                try:
                    gui.draw_robber_from_board(game.board)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        gui.update_round_turn(game, special=False)
    except Exception:
        pass
    try:
        gui.update_scoreboard(game)
    except Exception:
        pass
    try:
        if hasattr(gui, "update_twitter"):
            gui.update_twitter()
    except Exception:
        pass
    try:
        if hasattr(gui, "draw_execution_debug_panel"):
            gui.draw_execution_debug_panel(game)
    except Exception:
        pass
    try:
        from gui.gui_human_player import GUIHumanPlayer

        GUIHumanPlayer().show_buttons_HP(game, analysis_tf=False)
    except Exception:
        pass
    try:
        # Strip only — Statistics canvas must stay off in playboard view
        if is_post_game_ui_active(game):
            draw_post_game_strip(game)
    except Exception:
        pass


def redraw_endgame_for_screenshot(game: Any) -> None:
    """Redraw board, scoreboard, twitter, and post-game chrome for capture."""
    gui = getattr(game, "gui", None)
    if gui is None:
        # Still allow pure stats draw without gui binding
        try:
            draw_game_over_panel(game)
        except Exception:
            pass
        try:
            pygame.display.update()
        except Exception:
            pass
        return
    try:
        if hasattr(gui, "draw_board_base") and getattr(game, "board", None) is not None:
            gui.draw_board_base(game.board)
            if hasattr(gui, "draw_all_permanent_buildings"):
                gui.draw_all_permanent_buildings(game.board)
            if hasattr(gui, "draw_robber_from_board"):
                try:
                    gui.draw_robber_from_board(game.board)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        gui.update_round_turn(game, special=False)
    except Exception:
        pass
    try:
        gui.update_scoreboard(game)
    except Exception:
        pass
    try:
        if hasattr(gui, "update_twitter"):
            gui.update_twitter()
    except Exception:
        pass
    try:
        if hasattr(gui, "draw_execution_debug_panel"):
            gui.draw_execution_debug_panel(game)
    except Exception:
        pass
    try:
        from gui.gui_human_player import GUIHumanPlayer

        GUIHumanPlayer().show_buttons_HP(game, analysis_tf=False)
    except Exception:
        pass
    try:
        draw_game_over_panel(game)
    except Exception:
        pass
    try:
        pygame.display.update()
    except Exception:
        pass


def capture_endgame_screenshots(game: Any) -> Dict[str, str]:
    """Take two endgame screenshots before New Game.

    1) **Playboard pack**: playboard + scoreboard + Events/twitter panel
       (Statistics body hidden).
    2) **Statistics**: full left canvas (S7a) including strip chrome.
    """
    ensure_post_game_ui(game)
    paths: Dict[str, str] = {}

    # --- 1) Playboard + scoreboard + twitter ---
    # Avoid recursive restore noise: set view then redraw underlay
    st = _state(game)
    st["view"] = VIEW_PLAYBOARD
    st["rects"] = {}
    try:
        clear_statistics_canvas_area()
    except Exception:
        pass
    redraw_endgame_for_screenshot(game)
    try:
        paths["playboard"] = _save_regions_composite(
            [PLAYBOARD_RECT, SCOREBOARD_RECT, TWITTER_PANEL_RECT],
            name_prefix="Catan_Endgame_Playboard",
        )
    except Exception as exc:
        paths["playboard_error"] = str(exc)

    # --- 2) Full Statistics canvas ---
    st["view"] = VIEW_STATISTICS
    st["rects"] = {}
    redraw_endgame_for_screenshot(game)
    try:
        paths["statistics"] = _save_regions_composite(
            [CANVAS_RECT],
            name_prefix="Catan_Endgame_Statistics",
        )
    except Exception as exc:
        paths["statistics_error"] = str(exc)

    # Leave UI on Statistics (default post-game view)
    try:
        st["view"] = VIEW_STATISTICS
        redraw_endgame_for_screenshot(game)
    except Exception:
        pass

    return paths


__all__ = [
    "VIEW_STATISTICS",
    "VIEW_PLAYBOARD",
    "CANVAS_RECT",
    "STATISTICS_CANVAS_RECT",
    "open_game_over_panel",
    "ensure_post_game_ui",
    "close_game_over_panel",
    "draw_game_over_panel",
    "draw_post_game_strip",
    "draw_game_over_statistics_panel",
    "handle_game_over_click",
    "handle_game_over_panel_click",
    "handle_game_over_key",
    "is_post_game_ui_active",
    "is_game_over_panel_active",
    "is_statistics_view",
    "set_post_game_view",
    "request_new_game",
    "consume_new_game_request",
    "clear_game_over_panel_area",
    "clear_statistics_canvas_area",
    "collect_overview_rows",
    "collect_dice_stats",
    "capture_endgame_screenshots",
    "redraw_endgame_for_screenshot",
    "redraw_playboard_underlay",
]
