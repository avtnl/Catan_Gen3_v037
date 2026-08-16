"""M-GUI G7 + F10: synthetic re-play Events strip (from MGlog only).

Uses live ``TWITTER_PANEL_RECT`` and live Events fonts (Font.NORMAL bold title,
Font.SMALL regular lines). Scroll hint sits **below** the panel bottom border
(not in the header) so it never overlaps the title or event lines.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

import pygame

try:
    from gui.gui_constants import TWITTER_PANEL_RECT, COLORS, Font
except Exception:  # pragma: no cover
    TWITTER_PANEL_RECT = pygame.Rect(900, 15, 300, 180)
    COLORS = {
        "LGRAY": (200, 200, 200),
        "BLACK": (0, 0, 0),
        "DGRAY": (100, 100, 100),
        "GREEN": (0, 140, 60),
        "WHITE": (255, 255, 255),
    }
    Font = None  # type: ignore

TITLE = "Re-play events (from MGlog)"
LINE_H = 13
PAD = 8
# Single title row inside panel; scroll hint is drawn under the panel border
HEADER_LINE = 18
TITLE_H = HEADER_LINE + 4

_SEAT_RGB = {
    1: (40, 90, 200),
    2: (200, 40, 40),
    3: (230, 230, 230),
    4: (220, 130, 30),
}


def panel_rect() -> pygame.Rect:
    return TWITTER_PANEL_RECT.copy()


def max_visible_lines(rect: Optional[pygame.Rect] = None) -> int:
    r = rect or panel_rect()
    return max(1, (r.height - TITLE_H - 6) // LINE_H)


def clamp_scroll(scroll: int, n_lines: int, visible: int) -> int:
    if n_lines <= visible:
        return 0
    max_scroll = n_lines - visible
    return max(0, min(int(scroll), max_scroll))


def visible_slice(
    lines: Sequence[Any],
    *,
    scroll: int = 0,
    visible: Optional[int] = None,
) -> Tuple[List[Any], int]:
    n = len(lines)
    vis = int(visible) if visible is not None else max_visible_lines()
    sc = clamp_scroll(scroll, n, vis)
    if n == 0:
        return [], 0
    end = n - sc
    start = max(0, end - vis)
    return list(lines[start:end]), sc


def _ensure_fonts() -> None:
    if Font is None:
        return
    try:
        Font.initialize_fonts()
    except Exception:
        pass


def _font_title() -> pygame.font.Font:
    """Match live Events title: Font.NORMAL bold."""
    _ensure_fonts()
    try:
        return Font.NORMAL.value["bold"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16, bold=True)


def _font_line() -> pygame.font.Font:
    """Match live Events lines: Font.SMALL regular."""
    _ensure_fonts()
    try:
        return Font.SMALL.value["regular"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 10, bold=False)


def _line_text(entry: Any) -> str:
    if entry is None:
        return ""
    if isinstance(entry, str):
        return entry
    disp = getattr(entry, "display", None)
    if callable(disp):
        try:
            return str(disp(with_rt=False))
        except Exception:
            pass
    msg = getattr(entry, "message", None)
    if msg is not None:
        return str(msg)
    return str(entry)


def _line_pid(entry: Any) -> Optional[int]:
    if entry is None or isinstance(entry, str):
        return None
    pid = getattr(entry, "player_id", None)
    try:
        return int(pid) if pid is not None else None
    except Exception:
        return None


def _line_index(entry: Any) -> Optional[int]:
    if entry is None or isinstance(entry, str):
        return None
    idx = getattr(entry, "index", None)
    try:
        return int(idx) if idx is not None else None
    except Exception:
        return None


def draw_event_strip(
    screen: pygame.Surface,
    lines: Sequence[Any],
    *,
    scroll: int = 0,
    cursor_index: Optional[int] = None,
    rect: Optional[pygame.Rect] = None,
) -> int:
    """Draw Events panel. Title inside; scroll hint **below** bottom border."""
    pane = rect or panel_rect()
    bg = COLORS.get("LGRAY", (200, 200, 200))
    border = COLORS.get("BLACK", (0, 0, 0))
    dim = COLORS.get("DGRAY", (100, 100, 100))

    pygame.draw.rect(screen, bg, pane)
    pygame.draw.rect(screen, border, pane, 1)

    title_font = _font_title()
    line_font = _font_line()

    # Title only inside panel (left)
    screen.blit(
        title_font.render(TITLE, True, border),
        (pane.x + PAD, pane.y + 2),
    )

    vis = max_visible_lines(pane)
    slice_lines, sc = visible_slice(lines, scroll=scroll, visible=vis)
    n = len(lines)

    # Scroll hint just below the panel's bottom border (outside the box)
    if n > vis:
        hint = f"↑{sc} older · wheel · {n} total"
        screen.blit(
            line_font.render(hint, True, dim),
            (pane.x + PAD, pane.bottom + 3),
        )

    if not lines:
        empty = line_font.render("(no events yet)", True, dim)
        screen.blit(empty, (pane.x + PAD, pane.y + TITLE_H))
        return 0

    y = pane.y + TITLE_H
    for entry in slice_lines:
        text = _line_text(entry)
        pid = _line_pid(entry)
        idx = _line_index(entry)
        is_cursor = (
            cursor_index is not None
            and idx is not None
            and int(idx) == int(cursor_index)
        )

        if is_cursor:
            pygame.draw.rect(
                screen,
                (210, 230, 210),
                pygame.Rect(pane.x + 2, y - 1, pane.width - 4, LINE_H),
            )

        dx = pane.x + PAD + 4
        dy = y + LINE_H // 2
        if pid is not None and int(pid) in _SEAT_RGB:
            pygame.draw.circle(screen, _SEAT_RGB[int(pid)], (dx, dy), 4)
            if int(pid) == 3:
                pygame.draw.circle(screen, border, (dx, dy), 4, 1)
        else:
            pygame.draw.circle(screen, dim, (dx, dy), 3, 1)

        prefix = f"{idx:>3} " if idx is not None else ""
        raw = f"{prefix}{text}"
        max_w = pane.width - (PAD + 16) - PAD
        col = border if not is_cursor else (0, 90, 40)
        surf = line_font.render(raw, True, col)
        if surf.get_width() > max_w:
            while raw and line_font.size(raw + "…")[0] > max_w:
                raw = raw[:-1]
            surf = line_font.render(raw + "…", True, col)
        screen.blit(surf, (pane.x + PAD + 12, y))
        y += LINE_H

    return sc


def hit_test(pos: Tuple[int, int], rect: Optional[pygame.Rect] = None) -> bool:
    r = rect or panel_rect()
    return bool(r.collidepoint(pos))


def scroll_delta_from_wheel(event: Any) -> int:
    try:
        y = int(getattr(event, "y", 0) or 0)
        return -y if y else 0
    except Exception:
        return 0


__all__ = [
    "TITLE",
    "TITLE_H",
    "panel_rect",
    "max_visible_lines",
    "clamp_scroll",
    "visible_slice",
    "draw_event_strip",
    "hit_test",
    "scroll_delta_from_wheel",
]
