"""Human discard panel for 7-roll (hand > 7).

Look-and-feel matches TwB/TwP:
- same screen slot (DISCARD_PANEL_RECT / TRADE_BANK_PANEL_RECT family)
- LGRAY panel, black border, Font.SMALL controls
- per-resource - / value / + rows
- NOK resets selection; OK confirms exact discard count

Does not modify TwB or TwP panel modules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pygame

from gui.gui_constants import WIN, COLORS, Font, SOUNDS

try:
    from gui.gui_constants import DISCARD_PANEL_RECT
except Exception:  # pragma: no cover
    from gui.gui_constants import TRADE_BANK_PANEL_RECT as DISCARD_PANEL_RECT

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")

PANEL_RECT = DISCARD_PANEL_RECT
CONTROL_BLOCK_WIDTH = 100
CONTROL_BLOCK_X = PANEL_RECT.right - CONTROL_BLOCK_WIDTH - 14
ROW_H = 28

CLOSE_RECT = pygame.Rect(PANEL_RECT.right - 28, PANEL_RECT.y + 8, 20, 20)
NOK_RECT = pygame.Rect(CONTROL_BLOCK_X - 86, PANEL_RECT.bottom - 36, 70, 28)
OK_RECT = pygame.Rect(CONTROL_BLOCK_X, PANEL_RECT.bottom - 36, 70, 28)


def clear_discard_panel_area() -> None:
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return {"active": False, "selected": [0, 0, 0, 0, 0], "rects": {}, "discard_count": 0, "player_id": None, "message": ""}
    state = getattr(gui, "discard_panel_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(gui, "discard_panel_state", state)
    state.setdefault("active", False)
    state.setdefault("selected", [0, 0, 0, 0, 0])
    state.setdefault("rects", {})
    state.setdefault("discard_count", 0)
    state.setdefault("player_id", None)
    state.setdefault("message", "")
    if not isinstance(state.get("selected"), list) or len(state.get("selected", [])) < 5:
        state["selected"] = [0, 0, 0, 0, 0]
    state["selected"] = [max(0, int(x or 0)) for x in list(state["selected"])[:5]]
    return state


def is_discard_panel_active(game: Any) -> bool:
    return bool(_state(game).get("active"))


def open_discard_panel(game: Any, *, player_id: Optional[int] = None, discard_count: Optional[int] = None) -> None:
    state = _state(game)
    if player_id is None:
        try:
            player_id = int((getattr(game, "pending_discard_queue") or [{}])[0].get("player_id"))
        except Exception:
            player_id = None
    if discard_count is None:
        discard_count = 0
        try:
            from core.game_7logic import _hand_vector5, _player_by_id
            player = _player_by_id(game, player_id)
            total = sum(_hand_vector5(player))
            discard_count = total // 2 if total > 7 else 0
        except Exception:
            discard_count = 0
    state.update({
        "active": True,
        "selected": [0, 0, 0, 0, 0],
        "rects": {},
        "discard_count": int(discard_count or 0),
        "player_id": player_id,
        "message": "",
    })
    try:
        game.gui.set_button("discard_panel", True)
    except Exception:
        pass


def close_discard_panel(game: Any) -> None:
    state = _state(game)
    state.update({"active": False, "selected": [0, 0, 0, 0, 0], "rects": {}, "message": ""})
    try:
        game.gui.set_button("discard_panel", False)
    except Exception:
        pass
    try:
        clear_discard_panel_area()
    except Exception:
        pass


def _player(game: Any):
    state = _state(game)
    pid = state.get("player_id")
    try:
        from core.game_7logic import _player_by_id
        return _player_by_id(game, pid)
    except Exception:
        try:
            return game.get_current_player()
        except Exception:
            return None


def _hand(game: Any) -> List[int]:
    try:
        from core.game_7logic import _hand_vector5
        return _hand_vector5(_player(game))
    except Exception:
        return [0, 0, 0, 0, 0]


def _validation(game: Any) -> Dict[str, Any]:
    state = _state(game)
    selected = list(state.get("selected", [0, 0, 0, 0, 0]))[:5]
    hand = _hand(game)
    need = int(state.get("discard_count") or 0)
    reasons = []
    for i in range(5):
        if selected[i] > hand[i]:
            reasons.append(f"not enough {RESOURCE_NAMES[i]}")
    if sum(selected) != need:
        reasons.append(f"need {need}, selected {sum(selected)}")
    return {"ok": not reasons and need > 0, "reasons": reasons, "hand": hand, "selected": selected, "need": need}


def _draw_button(rect: pygame.Rect, label: str, *, active: bool, selected: bool = False) -> None:
    fill = COLORS.get("WHITE", (255, 255, 255)) if not selected else COLORS.get("LGRAY", (210, 210, 210))
    border = COLORS.get("GREEN", (0, 180, 0)) if active else COLORS.get("GRAY", (130, 130, 130))
    text_color = COLORS.get("BLACK", (0, 0, 0)) if active else COLORS.get("GRAY", (130, 130, 130))
    pygame.draw.rect(WIN, fill, rect)
    pygame.draw.rect(WIN, border, rect, 2)
    font = Font.SMALL.value["bold"] if selected else Font.SMALL.value["regular"]
    text = font.render(label, True, text_color)
    WIN.blit(text, text.get_rect(center=rect.center))


def _draw_value_box(rect: pygame.Rect, value: int, *, active: bool = True) -> None:
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), rect)
    pygame.draw.rect(WIN, COLORS.get("GRAY", (130, 130, 130)), rect, 1)
    text_color = COLORS.get("WHITE", (255, 255, 255)) if active else COLORS.get("GRAY", (130, 130, 130))
    text = Font.SMALL.value["bold"].render(str(value), True, text_color)
    WIN.blit(text, text.get_rect(center=rect.center))


def draw_discard_panel(game: Any) -> None:
    state = _state(game)
    if not state.get("active"):
        clear_discard_panel_area()
        return

    hand = _hand(game)
    selected = list(state.get("selected", [0, 0, 0, 0, 0]))[:5]
    need = int(state.get("discard_count") or 0)
    status = _validation(game)
    rects: Dict[str, pygame.Rect] = {}

    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title_font = Font.NORMAL.value["bold"]
    small = Font.SMALL.value["regular"]
    small_bold = Font.SMALL.value["bold"]

    x = PANEL_RECT.x + 12
    y = PANEL_RECT.y + 8
    selected_total = sum(selected)
    remaining = max(0, need - selected_total)
    meets_requirement = bool(status.get("ok"))  # exact need selected, legal vs hand
    WIN.blit(title_font.render(f"Discard — need {need}", True, COLORS["BLACK"]), (x, y))
    _draw_button(CLOSE_RECT, "X", active=True)
    rects["close"] = CLOSE_RECT

    # Skip Hand line (already on scoreboard). Resource rows start higher so
    # +/- controls clear the NOK/OK strip; Selected status sits under Sheep.
    y += 28
    WIN.blit(small_bold.render("Resource", True, COLORS["BLACK"]), (x, y))
    WIN.blit(small_bold.render("Drop", True, COLORS["BLACK"]), (CONTROL_BLOCK_X + 28, y))
    y += 22

    for idx in range(5):
        row_y = y + idx * ROW_H
        WIN.blit(small.render(f"{RESOURCE_NAMES[idx]} (have {hand[idx]})", True, COLORS["BLACK"]), (x, row_y + 3))
        minus = pygame.Rect(CONTROL_BLOCK_X, row_y, 22, 22)
        value = pygame.Rect(CONTROL_BLOCK_X + 26, row_y, 32, 22)
        plus = pygame.Rect(CONTROL_BLOCK_X + 62, row_y, 22, 22)
        _draw_button(minus, "-", active=selected[idx] > 0)
        _draw_value_box(value, selected[idx])
        _draw_button(plus, "+", active=selected[idx] < hand[idx] and selected_total < need)
        rects[f"minus_{idx}"] = minus
        rects[f"value_{idx}"] = value
        rects[f"plus_{idx}"] = plus

    # Under Sheep: selection progress. Red until the required drop is met.
    sel_y = y + 5 * ROW_H + 4
    sel_color = (
        COLORS.get("BLACK", (0, 0, 0))
        if meets_requirement
        else COLORS.get("RED", (220, 0, 0))
    )
    WIN.blit(
        small_bold.render(
            f"Selected {selected_total} / {need}  (still {remaining})",
            True,
            sel_color,
        ),
        (x, sel_y),
    )

    msg = state.get("message") or ""
    if not status.get("ok") and status.get("reasons"):
        # Prefer the Selected line for count feedback; keep other errors only.
        reasons = [r for r in (status.get("reasons") or []) if not str(r).startswith("need ")]
        if reasons:
            msg = reasons[0]
        elif not msg:
            msg = ""
    if msg:
        WIN.blit(
            small.render(str(msg)[:42], True, COLORS.get("DGRAY", (80, 80, 80))),
            (x, PANEL_RECT.bottom - 58),
        )

    _draw_button(NOK_RECT, "NOK", active=True)
    _draw_button(OK_RECT, "OK", active=bool(status.get("ok")))
    rects["nok"] = NOK_RECT
    rects["ok"] = OK_RECT
    state["rects"] = rects


def handle_discard_panel_click(game: Any, pos) -> bool:
    """Return True if the click was consumed by the discard panel."""
    state = _state(game)
    if not state.get("active"):
        return False
    rects = state.get("rects") or {}
    # Always consume clicks while active (modal like TwB)
    if not PANEL_RECT.collidepoint(pos):
        return True

    selected = list(state.get("selected", [0, 0, 0, 0, 0]))[:5]
    hand = _hand(game)
    need = int(state.get("discard_count") or 0)

    if rects.get("close") and rects["close"].collidepoint(pos):
        # Close is not skip: reset selection only (must discard)
        state["selected"] = [0, 0, 0, 0, 0]
        state["message"] = "must discard before continuing"
        _play(game, "BUTTON")
        return True
    if rects.get("nok") and rects["nok"].collidepoint(pos):
        state["selected"] = [0, 0, 0, 0, 0]
        state["message"] = ""
        _play(game, "BUTTON")
        return True
    if rects.get("ok") and rects["ok"].collidepoint(pos):
        status = _validation(game)
        if not status.get("ok"):
            state["message"] = (status.get("reasons") or ["invalid"])[0]
            _play(game, "ERROR")
            return True
        try:
            from core.game_7logic import submit_human_discard
            result = submit_human_discard(game, status["selected"], player_id=state.get("player_id"))
            if not result.get("ok"):
                state["message"] = str(result.get("reason") or "failed")
                _play(game, "ERROR")
                return True
            _play(game, "BUTTON")
        except Exception as exc:
            state["message"] = str(exc)
            _play(game, "ERROR")
        return True

    for idx in range(5):
        minus = rects.get(f"minus_{idx}")
        plus = rects.get(f"plus_{idx}")
        if minus and minus.collidepoint(pos) and selected[idx] > 0:
            selected[idx] -= 1
            state["selected"] = selected
            state["message"] = ""
            _play(game, "BUTTON")
            return True
        if plus and plus.collidepoint(pos):
            if selected[idx] < hand[idx] and sum(selected) < need:
                selected[idx] += 1
                state["selected"] = selected
                state["message"] = ""
                _play(game, "BUTTON")
            else:
                _play(game, "ERROR")
            return True
    return True


def _play(game: Any, name: str) -> None:
    try:
        gui = getattr(game, "gui", None)
        if gui is not None and hasattr(gui, "play_sound"):
            gui.play_sound(name)
            return
    except Exception:
        pass
    try:
        sound = SOUNDS.get(name) or SOUNDS.get("BUTTON")
        if sound is not None:
            pygame.mixer.Sound.play(sound)
    except Exception:
        pass
