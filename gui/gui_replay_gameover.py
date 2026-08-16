"""M-GUI G5: re-play Game Over strip — Playboard / Statistics / Save.

Statistics use full-log M-stats (not cursor-truncated). Save writes two PNGs
plus a manifest that references playboard + mglog paths.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

VIEW_PLAYBOARD = "playboard"
VIEW_STATISTICS = "statistics"

# Right-side strip (same slot family as live GAME_OVER / TwB)
try:
    from gui.gui_constants import GAME_OVER_PANEL_RECT, COLORS, WIN, SCOREBOARD_RECT, PLAYBOARD_RECT
except Exception:  # pragma: no cover
    GAME_OVER_PANEL_RECT = pygame.Rect(675, 520, 520, 260)
    COLORS = {}
    WIN = None
    SCOREBOARD_RECT = pygame.Rect(110, 540, 700, 240)
    PLAYBOARD_RECT = pygame.Rect(410, 25, 480, 475)

# Stats canvas: cover main left play area (not the right strip)
try:
    from gui.gui_constants import STATISTICS_CANVAS_RECT

    STATS_CANVAS = STATISTICS_CANVAS_RECT
except Exception:
    STATS_CANVAS = pygame.Rect(
        min(PLAYBOARD_RECT.x, 10),
        50,
        max(PLAYBOARD_RECT.right, 650) - min(PLAYBOARD_RECT.x, 10),
        max(PLAYBOARD_RECT.bottom, SCOREBOARD_RECT.bottom) - 50,
    )

STRIP = GAME_OVER_PANEL_RECT

# R2: completeness banner sits below the GO strip (same band even if strip hidden)
# Single-row banner (fits under GO strip on 800px screen); F10 avoids text overlap via L/R layout
BANNER_HEIGHT = 28
try:
    from gui.gui_constants import SCREEN_WIDTH as _SW, SCREEN_HEIGHT as _SH
except Exception:  # pragma: no cover
    _SW, _SH = 1225, 800


def banner_rect(*, screen_w: int = 0, screen_h: int = 0) -> pygame.Rect:
    """Full-width status banner **below** GAME_OVER_PANEL_RECT (B1)."""
    w = int(screen_w) if screen_w else int(_SW)
    h = int(screen_h) if screen_h else int(_SH)
    y = int(STRIP.bottom) + 4
    if y + BANNER_HEIGHT > h:
        y = max(0, h - BANNER_HEIGHT)
    return pygame.Rect(0, y, w, BANNER_HEIGHT)


def should_show_game_over_strip(game_over: bool) -> bool:
    """B2: GO strip only after re-play has applied ``game_over``."""
    return bool(game_over)


def should_show_status_banner(view: str) -> bool:
    """Q7 locked: never show completeness banner on Statistics view."""
    return str(view or "") != VIEW_STATISTICS


def strip_button_rects(strip: pygame.Rect = STRIP) -> Dict[str, pygame.Rect]:
    pad, gap, h = 10, 8, 34
    y = strip.bottom - h - 12
    bw = max(70, (strip.width - 2 * pad - 2 * gap) // 3)
    x0 = strip.x + pad
    return {
        "statistics": pygame.Rect(x0, y, bw, h),
        "playboard": pygame.Rect(x0 + bw + gap, y, bw, h),
        "save": pygame.Rect(x0 + 2 * (bw + gap), y, bw, h),
    }


def _ensure_fonts() -> None:
    """Product fonts: Comic Sans MS via Font.SMALL / NORMAL / LARGE."""
    try:
        from gui.gui_constants import Font

        Font.initialize_fonts()
    except Exception:
        pass


def _font_small() -> pygame.font.Font:
    _ensure_fonts()
    try:
        from gui.gui_constants import Font

        return Font.SMALL.value["regular"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 10)


def _font_normal() -> pygame.font.Font:
    _ensure_fonts()
    try:
        from gui.gui_constants import Font

        return Font.NORMAL.value["regular"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16)


def _font_normal_bold() -> pygame.font.Font:
    _ensure_fonts()
    try:
        from gui.gui_constants import Font

        return Font.NORMAL.value["bold"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16, bold=True)


def _font_large() -> pygame.font.Font:
    """Button labels — same as live Play / Continue / Roll Dices."""
    _ensure_fonts()
    try:
        from gui.gui_constants import Font

        return Font.LARGE.value["regular"]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 24)


# Strip button labels (shared size so "Save" matches "Statistics" / "Playboard")
_STRIP_LABELS: Dict[str, str] = {
    "statistics": "Statistics",
    "playboard": "Playboard",
    "save": "Save",
}


def strip_button_enabled(
    bid: str,
    view: str,
    *,
    save_done: bool = False,
) -> bool:
    """Which strip buttons are clickable for the current view.

    * Current view button is **disabled** (Playboard when playboard shown, etc.).
    * The other view switch is **enabled**.
    * Save is enabled until a successful save; then disabled for the rest of the session.
    """
    key = str(bid or "")
    if key == "statistics":
        return str(view or "") != VIEW_STATISTICS
    if key == "playboard":
        return str(view or "") != VIEW_PLAYBOARD
    if key == "save":
        return not bool(save_done)
    return False


def _shared_strip_button_font(rect_width: int, labels: Sequence[str]) -> pygame.font.Font:
    """One font for all strip buttons — longest label dictates size."""
    max_w = max(0, int(rect_width) - 6)
    for font in (_font_large(), _font_normal(), _font_small()):
        if all(font.size(str(lab))[0] <= max_w for lab in labels):
            return font
    return _font_small()


def _draw_btn(
    screen: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    *,
    enabled: bool = True,
    hover: bool = False,
    font: Optional[pygame.font.Font] = None,
) -> None:
    """Live-like chrome: green border + white text when enabled; gray when disabled."""
    green = COLORS.get("GREEN", (0, 255, 0))
    gray = COLORS.get("GRAY", (169, 169, 169))
    white = COLORS.get("WHITE", (255, 255, 255))
    lgray = COLORS.get("LGRAY", (200, 200, 200))
    en = bool(enabled)
    # Hover only brightens enabled buttons
    if en:
        border = green
        tc = white
    else:
        border = gray
        tc = gray
    # hover unused for color (enabled already green/white); keep param for API stability
    _ = hover
    pygame.draw.rect(screen, lgray, rect)
    pygame.draw.rect(screen, border, rect, 2)
    use_font = font or _font_large()
    text = use_font.render(label, True, tc)
    # Safety shrink if a custom font was passed too large
    if text.get_width() > rect.width - 6:
        for fb in (_font_normal(), _font_small()):
            cand = fb.render(label, True, tc)
            if cand.get_width() <= rect.width - 6:
                text = cand
                break
            text = cand
    screen.blit(text, text.get_rect(center=rect.center))


def draw_strip(
    screen: pygame.Surface,
    *,
    view: str,
    winner_id: Optional[int] = None,
    winner_color: str = "",
    final_vp: Any = "",
    complete: bool = False,
    hover_id: Optional[str] = None,
    last_save_msg: str = "",
    save_done: bool = False,
) -> Dict[str, pygame.Rect]:
    """Draw right-side Game Over chrome; return button rects."""
    black = COLORS.get("BLACK", (0, 0, 0))
    lgray = COLORS.get("LGRAY", (210, 210, 210))
    pygame.draw.rect(screen, lgray, STRIP)
    pygame.draw.rect(screen, black, STRIP, 2)

    title = _font_normal_bold().render("GAME OVER / DIG", True, black)
    screen.blit(title, (STRIP.x + 12, STRIP.y + 10))

    if winner_id is not None:
        line = f"Winner P{winner_id} ({winner_color or '?'})  {final_vp} VP"
    else:
        line = "No game_over in MGlog yet — stats still full-log"
    screen.blit(_font_normal().render(line[:48], True, black), (STRIP.x + 12, STRIP.y + 36))

    status = "MGlog complete" if complete else "MGlog incomplete"
    screen.blit(
        _font_small().render(status, True, (40, 100, 40) if complete else (140, 60, 20)),
        (STRIP.x + 12, STRIP.y + 56),
    )
    screen.blit(
        _font_small().render("Statistics = full MGlog (not cursor)", True, (80, 80, 80)),
        (STRIP.x + 12, STRIP.y + 74),
    )
    if last_save_msg:
        screen.blit(
            _font_small().render(last_save_msg[:50], True, (20, 80, 20)),
            (STRIP.x + 12, STRIP.y + 92),
        )

    rects = strip_button_rects(STRIP)
    # Shared font so short "Save" matches longer "Statistics" / "Playboard"
    btn_w = next(iter(rects.values())).width if rects else 70
    shared_font = _shared_strip_button_font(
        btn_w, list(_STRIP_LABELS.values())
    )
    for bid, label in _STRIP_LABELS.items():
        en = strip_button_enabled(bid, view, save_done=save_done)
        _draw_btn(
            screen,
            rects[bid],
            label,
            enabled=en,
            hover=(hover_id == bid and en),
            font=shared_font,
        )
    return rects


def hit_test(
    pos: Tuple[int, int],
    rects: Mapping[str, pygame.Rect],
    *,
    view: Optional[str] = None,
    save_done: bool = False,
    enabled_only: bool = False,
) -> Optional[str]:
    """Hit-test strip buttons. With ``enabled_only``, ignore disabled hits."""
    for k, r in rects.items():
        if r.collidepoint(pos[0], pos[1]):
            if enabled_only and view is not None:
                if not strip_button_enabled(k, view, save_done=save_done):
                    return None
            return k
    return None


def _cell(v: Any) -> str:
    if v is None:
        return "*"
    return str(v)


def _draw_table(
    screen: pygame.Surface,
    origin: Tuple[int, int],
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    col_widths: Sequence[int],
    row_h: int = 18,
) -> int:
    x0, y = origin
    black = (0, 0, 0)
    font = _font_small()
    total_w = sum(col_widths)
    # header
    pygame.draw.rect(screen, (200, 200, 210), pygame.Rect(x0, y, total_w, row_h))
    pygame.draw.rect(screen, black, pygame.Rect(x0, y, total_w, row_h), 1)
    cx = x0
    for i, h in enumerate(headers):
        w = col_widths[i]
        t = font.render(str(h), True, black)
        screen.blit(t, t.get_rect(center=(cx + w // 2, y + row_h // 2)))
        cx += w
    y += row_h
    for ri, row in enumerate(rows):
        bg = (235, 235, 235) if ri % 2 else (255, 255, 255)
        pygame.draw.rect(screen, bg, pygame.Rect(x0, y, total_w, row_h))
        pygame.draw.rect(screen, (120, 120, 120), pygame.Rect(x0, y, total_w, row_h), 1)
        cx = x0
        for i, cell in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 40
            t = font.render(_cell(cell)[:12], True, black)
            if i == 0:
                screen.blit(t, (cx + 3, y + 2))
            else:
                screen.blit(t, t.get_rect(center=(cx + w // 2, y + row_h // 2)))
            cx += w
        y += row_h
    return y


def draw_statistics(
    screen: pygame.Surface,
    stats: Mapping[str, Any],
    *,
    canvas: pygame.Rect = STATS_CANVAS,
) -> None:
    """Draw full-log M-stats tables on the left canvas."""
    lgray = COLORS.get("LGRAY", (210, 210, 210))
    black = COLORS.get("BLACK", (0, 0, 0))
    pygame.draw.rect(screen, lgray, canvas)
    pygame.draw.rect(screen, black, canvas, 2)

    pad = 10
    x = canvas.x + pad
    y = canvas.y + pad
    meta = dict(stats.get("meta") or {})

    title = _font_large().render("Statistics (from MGlog — full game)", True, black)
    screen.blit(title, (x, y))
    y += 28
    sub = (
        f"source={meta.get('source')}  events={meta.get('event_count')}  "
        f"rc_block={meta.get('rc_block')}  winner={meta.get('winner_id')}"
    )
    screen.blit(_font_small().render(sub[:90], True, (60, 60, 60)), (x, y))
    y += 22

    # Overview
    ov = []
    for r in stats.get("overview_rows") or []:
        ov.append(
            [
                f"P{r.get('player_id')}",
                r.get("TVP"),
                r.get("S"),
                r.get("C"),
                r.get("DC"),
                r.get("LA"),
                r.get("LR"),
                "W" if r.get("winner") else "",
            ]
        )
    screen.blit(_font_normal_bold().render("Overview", True, black), (x, y))
    y += 18
    y = _draw_table(
        screen,
        (x, y),
        ["P", "TVP", "S", "C", "DC", "LA", "LR", "win"],
        ov,
        [40, 40, 36, 36, 36, 36, 36, 36],
    )
    y += 10

    # Activity
    act = []
    for r in stats.get("activity_rows") or []:
        act.append(
            [
                f"P{r.get('player_id')}",
                r.get("TrP"),
                r.get("TrP_A"),
                r.get("RC_Use"),
                r.get("RC_Block"),
                r.get("DC_In"),
                r.get("DC_Played"),
            ]
        )
    screen.blit(_font_normal_bold().render("Activity", True, black), (x, y))
    y += 18
    y = _draw_table(
        screen,
        (x, y),
        ["P", "TrP", "TrP_A", "Use", "Block", "DC+", "DC play"],
        act,
        [40, 40, 48, 44, 48, 40, 52],
    )
    y += 10

    # Dice summary
    dice = dict(stats.get("dice") or {})
    by_face = dice.get("by_face") or {}
    faces = " ".join(f"{n}:{by_face.get(n, 0)}" for n in range(2, 13))
    screen.blit(
        _font_small().render(
            f"Dice total={dice.get('total', 0)}  {faces}"[:100], True, black
        ),
        (x, y),
    )
    y += 20
    rc = dict(stats.get("rcards_drawn") or {})
    br = dict(rc.get("by_resource") or {})
    screen.blit(
        _font_small().render(
            f"RCards drawn: Wh={br.get('Wheat', 0)} O={br.get('Ore', 0)} "
            f"Wd={br.get('Wood', 0)} B={br.get('Brick', 0)} Sh={br.get('Sheep', 0)} "
            f"tot={rc.get('total', 0)}",
            True,
            black,
        ),
        (x, y),
    )
    y += 18
    dc = dict(stats.get("dcards_drawn") or {})
    bt = dict(dc.get("by_type") or {})
    screen.blit(
        _font_small().render(
            f"DCards: VP={bt.get('victory_point', 0)} K={bt.get('knight', 0)} "
            f"TFR={bt.get('two_free_roads', 0)} YOP={bt.get('year_of_plenty', 0)} "
            f"Mono={bt.get('monopoly', 0)} tot={dc.get('total_drawn', 0)}",
            True,
            black,
        ),
        (x, y),
    )


def load_full_stats(session: Any) -> Dict[str, Any]:
    """Full-game M-stats for Statistics view."""
    from core.mglog_statistics import collect_endgame_statistics_from_mglog

    return collect_endgame_statistics_from_mglog(
        session.mglog_path,
        playboard_path=session.playboard_path,
    )


def _stem(path: str) -> str:
    p = Path(path)
    name = p.stem or "file"
    # sanitize for filenames
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60]


def save_replay_shots(
    screen: pygame.Surface,
    session: Any,
    *,
    paint_playboard,  # callable () -> None
    paint_statistics,  # callable () -> None
    out_dir: Optional[Path] = None,
    cursor: int = -1,
) -> Dict[str, Any]:
    """Render both views and save PNGs + manifest.

    ``paint_*`` callables must draw the full frame for that view onto ``screen``
    (including strip if desired). Returns paths dict.
    """
    pb_stem = _stem(session.playboard_path)
    mg_stem = _stem(session.mglog_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if out_dir is None:
        # Prefer next to mglog; else batch_runs/replay_shots
        mg_parent = Path(session.mglog_path).resolve().parent
        out_dir = mg_parent / "replay_shots"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = f"ReplayShot_{pb_stem}__{mg_stem}"
    path_pb = out_dir / f"{base}__playboard_{ts}.png"
    path_st = out_dir / f"{base}__statistics_{ts}.png"
    path_mf = out_dir / f"{base}__manifest_{ts}.txt"

    # Playboard view
    paint_playboard()
    pygame.image.save(screen, str(path_pb))

    # Statistics view
    paint_statistics()
    pygame.image.save(screen, str(path_st))

    manifest = "\n".join(
        [
            "Catan MGlog re-play screenshot manifest",
            f"timestamp={ts}",
            f"playboard={Path(session.playboard_path).resolve()}",
            f"mglog={Path(session.mglog_path).resolve()}",
            f"cursor={cursor}",
            f"events={session.n_events}",
            f"complete={session.completeness.complete}",
            f"starts_ok={session.completeness.starts_ok}",
            f"ends_ok={session.completeness.ends_ok}",
            f"screenshot_playboard={path_pb.resolve()}",
            f"screenshot_statistics={path_st.resolve()}",
            "",
        ]
    )
    path_mf.write_text(manifest, encoding="utf-8")

    return {
        "ok": True,
        "playboard_png": str(path_pb.resolve()),
        "statistics_png": str(path_st.resolve()),
        "manifest": str(path_mf.resolve()),
        "out_dir": str(out_dir.resolve()),
    }


__all__ = [
    "VIEW_PLAYBOARD",
    "VIEW_STATISTICS",
    "STRIP",
    "STATS_CANVAS",
    "BANNER_HEIGHT",
    "banner_rect",
    "should_show_game_over_strip",
    "should_show_status_banner",
    "strip_button_rects",
    "strip_button_enabled",
    "draw_strip",
    "draw_statistics",
    "hit_test",
    "load_full_stats",
    "save_replay_shots",
]
