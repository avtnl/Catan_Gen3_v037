"""M-GUI re-play navigation buttons + dice (match live human button chrome).

Layout (SE Dig product):
  **One top row (8):** <<G  <R  <T  <  >  >T  >R  >>G
  Dig Previous/Next live in ``gui_replay_dig`` below the dice (not here).
  Panel fill LGRAY + BLACK border; enabled GREEN/WHITE, disabled GRAY/GRAY.
  Dice: live show_dices positions (20 / 110, y=380) in LEFT_DICE_PANEL_RECT.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pygame

try:
    from gui.gui_constants import (
        HUMAN_BUTTON_PANEL_RECT,
        LEFT_DICE_PANEL_RECT,
        COLORS,
        Font,
    )

    PANEL = HUMAN_BUTTON_PANEL_RECT.copy()
    DICE_PANEL = LEFT_DICE_PANEL_RECT.copy()
except Exception:  # pragma: no cover
    PANEL = pygame.Rect(10, 265, 330, 255)
    DICE_PANEL = pygame.Rect(15, 370, 175, 90)
    COLORS = {
        "LGRAY": (200, 200, 200),
        "DGRAY": (100, 100, 100),
        "GRAY": (169, 169, 169),
        "BLACK": (0, 0, 0),
        "WHITE": (255, 255, 255),
        "GREEN": (0, 255, 0),
        "RED": (255, 0, 0),
    }
    Font = None  # type: ignore

# Single top row: first / prev round / prev turn / prev row / next row / next turn / next round / last
_TOP_SPECS: Tuple[Tuple[str, str], ...] = (
    ("first", "<<G"),
    ("previous_round", "<R"),
    ("previous_turn", "<T"),
    ("previous", "<"),
    ("continue", ">"),
    ("next_turn", ">T"),
    ("next_round", ">R"),
    ("last", ">>G"),
)

# Legacy names kept empty so dig layer owns bottom row
_SMALL_SPECS: Tuple[Tuple[str, str], ...] = ()

_BTN_SPECS: Tuple[Tuple[str, str], ...] = _TOP_SPECS

_CAP_KEY = {
    "first": "can_first",
    "previous_round": "can_previous_round",
    "previous_turn": "can_previous_turn",
    "previous": "can_previous",
    "continue": "can_continue",
    "next_turn": "can_next_turn",
    "next_round": "can_next_round",
    "last": "can_last",
}

_FORWARD_IDS = frozenset({"continue", "next_turn", "next_round", "last"})

# Live show_dices blit positions (gui.GUI.show_dices)
LIVE_DICE_X1 = 20
LIVE_DICE_X2 = 110
LIVE_DICE_Y = 380


def _rgb(name: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    try:
        v = COLORS.get(name, default)
        return (int(v[0]), int(v[1]), int(v[2]))
    except Exception:
        return default


def button_rects(
    panel: pygame.Rect = PANEL,
    dice: pygame.Rect = DICE_PANEL,
) -> Dict[str, pygame.Rect]:
    """Single top row of 8 nav buttons (above dice). Bottom row reserved for dig."""
    pad, gap = 6, 4
    # Leave room for cat fields between nav and dice (~36 px)
    max_bottom = int(dice.y - pad - 40)
    top_y = panel.y + pad
    row_h = max(26, min(36, max_bottom - top_y))
    top_band = pygame.Rect(
        panel.x + pad,
        top_y,
        max(40, panel.width - 2 * pad),
        row_h,
    )

    out: Dict[str, pygame.Rect] = {}
    n = len(_TOP_SPECS)
    bw = max(28, (top_band.width - gap * (n - 1)) // n)
    for i, (bid, _) in enumerate(_TOP_SPECS):
        out[bid] = pygame.Rect(
            top_band.x + i * (bw + gap),
            top_band.y,
            bw,
            top_band.height,
        )
    return out


def button_enabled(bid: str, cap: Mapping[str, Any]) -> bool:
    key = _CAP_KEY.get(bid)
    if not key:
        return False
    return bool(cap.get(key))


def button_red_border(bid: str, cap: Mapping[str, Any]) -> bool:
    """Legacy name: True when disabled (live uses GRAY border, not red)."""
    return not button_enabled(bid, cap)


def hit_test(pos: Tuple[int, int], rects: Mapping[str, pygame.Rect]) -> Optional[str]:
    for bid, rect in rects.items():
        if rect.collidepoint(pos[0], pos[1]):
            return bid
    return None


def _ensure_fonts() -> None:
    if Font is None:
        return
    try:
        Font.initialize_fonts()
    except Exception:
        pass


def _font_title() -> pygame.font.Font:
    """Resource Potential header style: Font.NORMAL bold, black."""
    _ensure_fonts()
    try:
        return Font.NORMAL.value["bold"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16, bold=True)


def _font_large() -> pygame.font.Font:
    """Top-row labels — same as live Play / Continue / Roll Dices."""
    _ensure_fonts()
    try:
        return Font.LARGE.value["regular"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 24, bold=False)


def _font_small() -> pygame.font.Font:
    _ensure_fonts()
    try:
        return Font.SMALL.value["regular"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 10, bold=False)


def draw_nav_panel(
    screen: pygame.Surface,
    cap: Mapping[str, Any],
    *,
    font: Optional[pygame.font.Font] = None,
    font_small: Optional[pygame.font.Font] = None,
    hover_id: Optional[str] = None,
    panel: pygame.Rect = PANEL,
) -> Dict[str, pygame.Rect]:
    """Draw panel + buttons matching live human panel colors/fonts."""
    # Live: panel area is LGRAY with BLACK border width 2
    lgray = _rgb("LGRAY", (200, 200, 200))
    black = _rgb("BLACK", (0, 0, 0))
    green = _rgb("GREEN", (0, 255, 0))
    gray = _rgb("GRAY", (169, 169, 169))
    white = _rgb("WHITE", (255, 255, 255))

    font_large = font or _font_large()
    font_sm = font_small or _font_small()
    title_font = _font_title()
    rects = button_rects(panel)

    pygame.draw.rect(screen, lgray, panel)
    pygame.draw.rect(screen, black, panel, 2)

    title = title_font.render("Re-play navigation", True, black)
    screen.blit(title, (panel.x + 10, panel.y - 22))

    labels = {bid: lab for bid, lab in _BTN_SPECS}

    for bid, rect in rects.items():
        en = button_enabled(bid, cap)
        pygame.draw.rect(screen, lgray, rect)
        border_col = green if en else gray
        text_col = white if en else gray
        pygame.draw.rect(screen, border_col, rect, 2)

        lab = labels.get(bid, bid)
        # Compact labels: prefer SMALL so 8 fit; fall back shrink
        use_font = font_sm
        text = use_font.render(lab, True, text_col)
        if text.get_width() > rect.width - 4:
            text = font_sm.render(lab, True, text_col)
        screen.blit(text, text.get_rect(center=rect.center))
    return rects


_dice_cache: Dict[int, Optional[pygame.Surface]] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_dice_surface(value: int) -> Optional[pygame.Surface]:
    v = int(value)
    if v in _dice_cache:
        return _dice_cache[v]
    if not (1 <= v <= 6):
        _dice_cache[v] = None
        return None
    try:
        from gui.gui_constants import IMAGES

        surf = (IMAGES.get(f"DICE_{v}") or {}).get("default")
        if surf is not None:
            _dice_cache[v] = surf
            return surf
    except Exception:
        pass
    path = _project_root() / "assets" / "images" / f"{v}.png"
    try:
        img = pygame.image.load(str(path)).convert_alpha()
        img = pygame.transform.scale(img, (75, 75))
        _dice_cache[v] = img
        return img
    except Exception:
        _dice_cache[v] = None
        return None


def draw_dice(
    screen: pygame.Surface,
    dice: Optional[Sequence[int]],
    dice_sum: Optional[int] = None,
    *,
    rect: pygame.Rect = DICE_PANEL,
    font: Optional[pygame.font.Font] = None,
) -> None:
    """F7: live show_dices positions inside LEFT_DICE_PANEL_RECT."""
    lgray = _rgb("LGRAY", (200, 200, 200))
    black = _rgb("BLACK", (0, 0, 0))
    font = font or _font_large()

    pygame.draw.rect(screen, lgray, rect)

    pair: Optional[Tuple[int, int]] = None
    if dice is not None and len(dice) >= 2:
        try:
            pair = (int(dice[0]), int(dice[1]))
        except Exception:
            pair = None
    if pair is None and dice_sum is not None:
        total = int(dice_sum)
        pairs = [(a, total - a) for a in range(1, 7) if 1 <= total - a <= 6]
        if pairs:
            pair = pairs[len(pairs) // 2]

    if pair is None:
        msg = font.render("—", True, _rgb("GRAY", (169, 169, 169)))
        screen.blit(msg, msg.get_rect(center=rect.center))
        return

    x1, x2, y = LIVE_DICE_X1, LIVE_DICE_X2, LIVE_DICE_Y
    for val, x in ((pair[0], x1), (pair[1], x2)):
        surf = load_dice_surface(val)
        if surf is not None:
            screen.blit(surf, (x, y))
        else:
            t = font.render(str(val), True, black)
            screen.blit(t, (x + 25, y + 20))


def apply_nav_click(session: Any, bid: str, mrep: Any) -> Tuple[bool, str]:
    """Run nav action for button id. Returns (ok, status_extra)."""
    cap = mrep.nav_capabilities(session)
    if not button_enabled(bid, cap):
        if bid in _FORWARD_IDS and cap.get("forward_blocked_incomplete_start"):
            return False, "MGlog does not start at R-2T1 — forward navigation disabled."
        if bid in _FORWARD_IDS and cap.get("forward_blocked_no_more_data"):
            if not session.completeness.ends_ok:
                return False, "MGlog incomplete — no further data available."
            return False, "End of MGlog."
        return False, "Button disabled."

    name = {
        "first": "step_first",
        "continue": "step_continue",
        "last": "step_last",
        "previous_turn": "step_previous_turn",
        "next_turn": "step_next_turn",
        "previous_round": "step_previous_round",
        "next_round": "step_next_round",
        "previous": "step_previous",
    }.get(bid)
    if not name:
        return False, "Unknown button."
    fn = getattr(mrep, name, None)
    if not callable(fn):
        return False, "Unknown button."
    result = fn(session)
    if result is None:
        if bid in _FORWARD_IDS:
            if not session.completeness.starts_ok:
                return False, "MGlog does not start at R-2T1 — forward navigation disabled."
            return False, "MGlog incomplete — no further data available."
        return False, "Navigation failed."
    return True, ""


__all__ = [
    "PANEL",
    "DICE_PANEL",
    "LIVE_DICE_X1",
    "LIVE_DICE_X2",
    "LIVE_DICE_Y",
    "button_rects",
    "button_enabled",
    "button_red_border",
    "hit_test",
    "draw_nav_panel",
    "draw_dice",
    "load_dice_surface",
    "apply_nav_click",
]
