"""TwP Auto Rules editor panel (Step 5).

This module owns the Human Player's TwP Auto rule editor UI.  It deliberately
stores only raw rule text on ``game.human_twp_auto_rules``; Step 6 will add the
semantic rule parser/evaluator that makes TwP_Auto accept or reject offers.

The panel is modal and uses the same screen slot as the TwB/TwP panels.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

try:
    from gui.gui_constants import WIN, COLORS, Font, TRADE_BANK_PANEL_RECT, SOUNDS
except Exception:  # pragma: no cover - lightweight smoke-test fallback
    WIN = None  # type: ignore
    COLORS = {  # type: ignore
        "BLACK": (0, 0, 0),
        "WHITE": (255, 255, 255),
        "LGRAY": (210, 210, 210),
        "GRAY": (130, 130, 130),
        "GREEN": (0, 180, 0),
        "RED": (220, 0, 0),
        "YELLOW": (255, 235, 80),
    }
    class _FontFace:
        def render(self, text, aa, color):
            return pygame.Surface((max(12, len(str(text)) * 7), 16))
    class _Font:
        SMALL = type("F", (), {"value": {"regular": _FontFace(), "bold": _FontFace()}})()
        NORMAL = type("F", (), {"value": {"regular": _FontFace(), "bold": _FontFace()}})()
    Font = _Font  # type: ignore
    TRADE_BANK_PANEL_RECT = pygame.Rect(880, 445, 320, 250)  # type: ignore
    SOUNDS = {}  # type: ignore

try:
    from core.human_twp_policy import (
        get_human_twp_auto_rules,
        set_human_twp_auto_rules,
        validate_twp_auto_rule,
    )
except Exception:  # pragma: no cover
    def get_human_twp_auto_rules(game: Any) -> List[str]:
        return list(getattr(game, "human_twp_auto_rules", []) or [])
    def set_human_twp_auto_rules(game: Any, rules: Sequence[Any]) -> List[str]:
        result = [str(x) for x in list(rules or []) if str(x).strip()]
        setattr(game, "human_twp_auto_rules", result)
        return result
    def validate_twp_auto_rule(raw_rule: Any, *, existing_rules: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        text = str(raw_rule or "").replace(" ", "")
        if text and text.count("->") == 1 and text not in set(existing_rules or []):
            return {"ok": True, "rule": text}
        return {"ok": False, "reason": "invalid_rule"}

PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    max(TRADE_BANK_PANEL_RECT.height, 250),
)

CLOSE_RECT = pygame.Rect(PANEL_RECT.right - 28, PANEL_RECT.y + 8, 20, 20)
RULE_AREA_TOP = PANEL_RECT.y + 38
RULE_ROW_H = 25
VISIBLE_RULE_ROWS = max(3, (PANEL_RECT.height - 112) // RULE_ROW_H)
RULE_TEXT_X = PANEL_RECT.x + 24
RULE_DEL_X = PANEL_RECT.right - 72
INPUT_Y = PANEL_RECT.bottom - 72
BOTTOM_Y = PANEL_RECT.bottom - 35


def _empty_state() -> Dict[str, Any]:
    return {
        "active": False,
        "working_rules": [],
        "original_rules": [],
        "input_text": "",
        "editing": False,
        "message": "",
        "scroll_offset": 0,
        "rects": {},
    }


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return _empty_state()
    state = getattr(gui, "twp_auto_rules_panel_state", None)
    if not isinstance(state, dict):
        state = _empty_state()
        setattr(gui, "twp_auto_rules_panel_state", state)
    defaults = _empty_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    if not isinstance(state.get("working_rules"), list):
        state["working_rules"] = []
    if not isinstance(state.get("original_rules"), list):
        state["original_rules"] = []
    if not isinstance(state.get("rects"), dict):
        state["rects"] = {}
    try:
        state["scroll_offset"] = max(0, int(state.get("scroll_offset", 0) or 0))
    except Exception:
        state["scroll_offset"] = 0
    return state


def is_twp_auto_rules_panel_active(game: Any) -> bool:
    return bool(_state(game).get("active", False))


def open_twp_auto_rules_panel(game: Any) -> None:
    state = _state(game)
    rules = get_human_twp_auto_rules(game)
    state.clear()
    state.update(_empty_state())
    state.update({
        "active": True,
        "working_rules": list(rules),
        "original_rules": list(rules),
        "input_text": "",
        "editing": True,
        "message": "",
        "scroll_offset": 0,
    })
    try:
        game.gui.set_button("twp_auto_rules_panel", True)
    except Exception:
        pass
    # Keep other trade panels mutually exclusive.
    try:
        if isinstance(getattr(game.gui, "twp_panel_state", None), dict):
            game.gui.twp_panel_state["active"] = False
        if isinstance(getattr(game.gui, "twb_panel_state", None), dict):
            game.gui.twb_panel_state["active"] = False
    except Exception:
        pass


def close_twp_auto_rules_panel(game: Any, *, commit: bool = False) -> None:
    state = _state(game)
    if commit:
        rules = list(state.get("working_rules", []) or [])
        # If the current input line is valid, commit it too.
        text = str(state.get("input_text", "") or "").strip()
        if text:
            checked = validate_twp_auto_rule(text, existing_rules=rules)
            if checked.get("ok"):
                rules.append(str(checked.get("rule", "")))
        set_human_twp_auto_rules(game, rules)
    state.clear()
    state.update(_empty_state())
    try:
        game.gui.set_button("twp_auto_rules_panel", False)
    except Exception:
        pass
    try:
        clear_twp_auto_rules_panel_area()
    except Exception:
        pass


def clear_twp_auto_rules_panel_area() -> None:
    if WIN is not None:
        pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)


def _play_sound(key: str = "BUTTON") -> None:
    try:
        sound = SOUNDS.get(key) or SOUNDS.get("BUTTON")
        if sound is not None:
            pygame.mixer.Sound.play(sound)
    except Exception:
        pass


def _draw_button(rect: pygame.Rect, label: str, *, active: bool = True, selected: bool = False) -> None:
    fill = COLORS.get("WHITE", (255, 255, 255)) if active else COLORS.get("LGRAY", (210, 210, 210))
    border = COLORS.get("GREEN", (0, 180, 0)) if active else COLORS.get("GRAY", (130, 130, 130))
    if selected:
        fill = COLORS.get("YELLOW", (255, 235, 80))
    pygame.draw.rect(WIN, fill, rect)
    pygame.draw.rect(WIN, border, rect, 2)
    color = COLORS.get("BLACK", (0, 0, 0)) if active else COLORS.get("GRAY", (130, 130, 130))
    font = Font.SMALL.value["bold"] if active else Font.SMALL.value["regular"]
    text = font.render(label, True, color)
    WIN.blit(text, text.get_rect(center=rect.center))


def _visible_slice(state: Mapping[str, Any]) -> Tuple[int, List[str]]:
    rules = list(state.get("working_rules", []) or [])
    max_offset = max(0, len(rules) - VISIBLE_RULE_ROWS)
    offset = min(max(0, int(state.get("scroll_offset", 0) or 0)), max_offset)
    return offset, rules[offset: offset + VISIBLE_RULE_ROWS]


def draw_twp_auto_rules_panel(game: Any) -> None:
    state = _state(game)
    if not state.get("active"):
        return
    rects: Dict[str, pygame.Rect] = {}
    state["rects"] = rects

    clear_twp_auto_rules_panel_area()
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title = Font.SMALL.value["bold"].render("TwP Auto Rules", True, COLORS.get("BLACK", (0, 0, 0)))
    WIN.blit(title, (PANEL_RECT.x + 10, PANEL_RECT.y + 8))
    rects["close"] = CLOSE_RECT
    _draw_button(CLOSE_RECT, "X", active=True)

    small = Font.SMALL.value["regular"]
    bold = Font.SMALL.value["bold"]
    offset, visible = _visible_slice(state)
    rules = list(state.get("working_rules", []) or [])
    for row_index, rule in enumerate(visible):
        absolute_index = offset + row_index
        y = RULE_AREA_TOP + row_index * RULE_ROW_H
        line_label = f"{absolute_index + 1:>2}.     {rule}"
        WIN.blit(small.render(line_label, True, COLORS.get("BLACK", (0, 0, 0))), (RULE_TEXT_X, y + 4))
        del_rect = pygame.Rect(RULE_DEL_X, y, 52, 21)
        rects[f"del_{absolute_index}"] = del_rect
        _draw_button(del_rect, "DEL", active=True)

    if len(rules) > VISIBLE_RULE_ROWS:
        scroll_text = f"{offset + 1}-{min(offset + VISIBLE_RULE_ROWS, len(rules))}/{len(rules)}"
        WIN.blit(small.render(scroll_text, True, COLORS.get("GRAY", (130, 130, 130))), (PANEL_RECT.right - 58, RULE_AREA_TOP - 20))
        up_rect = pygame.Rect(PANEL_RECT.right - 34, RULE_AREA_TOP - 22, 22, 18)
        down_rect = pygame.Rect(PANEL_RECT.right - 34, RULE_AREA_TOP + VISIBLE_RULE_ROWS * RULE_ROW_H, 22, 18)
        rects["scroll_up"] = up_rect
        rects["scroll_down"] = down_rect
        _draw_button(up_rect, "^", active=offset > 0)
        _draw_button(down_rect, "v", active=offset < len(rules) - VISIBLE_RULE_ROWS)

    input_rect = pygame.Rect(RULE_TEXT_X, INPUT_Y, PANEL_RECT.width - 120, 24)
    plus_rect = pygame.Rect(PANEL_RECT.right - 72, INPUT_Y, 52, 24)
    rects["input"] = input_rect
    rects["plus"] = plus_rect
    pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), input_rect)
    pygame.draw.rect(WIN, COLORS.get("GREEN", (0, 180, 0)) if state.get("editing") else COLORS.get("GRAY", (130, 130, 130)), input_rect, 2)
    input_text = str(state.get("input_text", "") or "")
    display_text = input_text if input_text else "type rule, e.g. Wh->Wd"
    input_color = COLORS.get("BLACK", (0, 0, 0)) if input_text else COLORS.get("GRAY", (130, 130, 130))
    WIN.blit(small.render(display_text[-32:], True, input_color), (input_rect.x + 5, input_rect.y + 5))
    _draw_button(plus_rect, "+", active=True)

    msg = str(state.get("message", "") or "")
    if msg:
        msg_color = COLORS.get("RED", (220, 0, 0)) if "invalid" in msg.lower() or "duplicate" in msg.lower() or "required" in msg.lower() else COLORS.get("BLACK", (0, 0, 0))
        WIN.blit(small.render(msg[:40], True, msg_color), (RULE_TEXT_X, INPUT_Y - 18))

    nok_rect = pygame.Rect(PANEL_RECT.x + 94, BOTTOM_Y, 70, 27)
    ok_rect = pygame.Rect(PANEL_RECT.x + 174, BOTTOM_Y, 70, 27)
    rects["nok"] = nok_rect
    rects["ok"] = ok_rect
    _draw_button(nok_rect, "NOK", active=True)
    _draw_button(ok_rect, "OK", active=True)


def _try_add_input_rule(state: Dict[str, Any]) -> bool:
    rules = list(state.get("working_rules", []) or [])
    checked = validate_twp_auto_rule(state.get("input_text", ""), existing_rules=rules)
    if not checked.get("ok"):
        state["message"] = str(checked.get("reason", "invalid_rule"))
        return False
    rule = str(checked.get("rule", ""))
    rules.append(rule)
    state["working_rules"] = rules
    state["input_text"] = ""
    state["editing"] = True
    state["message"] = "rule added"
    if len(rules) > VISIBLE_RULE_ROWS:
        state["scroll_offset"] = max(0, len(rules) - VISIBLE_RULE_ROWS)
    return True


def handle_twp_auto_rules_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    if not is_twp_auto_rules_panel_active(game):
        return False
    state = _state(game)
    rects: Dict[str, pygame.Rect] = dict(state.get("rects", {}) or {})

    if not PANEL_RECT.collidepoint(pos):
        return True
    if rects.get("close") and rects["close"].collidepoint(pos):
        _play_sound("BUTTON")
        close_twp_auto_rules_panel(game, commit=False)
        return True
    if rects.get("nok") and rects["nok"].collidepoint(pos):
        _play_sound("BUTTON")
        close_twp_auto_rules_panel(game, commit=False)
        return True
    if rects.get("ok") and rects["ok"].collidepoint(pos):
        _play_sound("BUTTON")
        close_twp_auto_rules_panel(game, commit=True)
        return True
    if rects.get("input") and rects["input"].collidepoint(pos):
        _play_sound("BUTTON")
        state["editing"] = True
        state["message"] = ""
        return True
    if rects.get("plus") and rects["plus"].collidepoint(pos):
        if _try_add_input_rule(state):
            _play_sound("BUTTON")
        else:
            _play_sound("ERROR")
        return True
    if rects.get("scroll_up") and rects["scroll_up"].collidepoint(pos):
        state["scroll_offset"] = max(0, int(state.get("scroll_offset", 0) or 0) - 1)
        return True
    if rects.get("scroll_down") and rects["scroll_down"].collidepoint(pos):
        rules = list(state.get("working_rules", []) or [])
        state["scroll_offset"] = min(max(0, len(rules) - VISIBLE_RULE_ROWS), int(state.get("scroll_offset", 0) or 0) + 1)
        return True

    for key, rect in list(rects.items()):
        if not key.startswith("del_") or not rect.collidepoint(pos):
            continue
        try:
            index = int(key.split("_", 1)[1])
        except Exception:
            continue
        rules = list(state.get("working_rules", []) or [])
        if 0 <= index < len(rules):
            removed = rules.pop(index)
            state["working_rules"] = rules
            state["message"] = f"deleted {removed}"
            state["scroll_offset"] = min(int(state.get("scroll_offset", 0) or 0), max(0, len(rules) - VISIBLE_RULE_ROWS))
            _play_sound("BUTTON")
        return True

    return True


def handle_twp_auto_rules_key(game: Any, event: Any) -> bool:
    """Handle KEYDOWN while the rule editor is active."""
    if not is_twp_auto_rules_panel_active(game):
        return False
    state = _state(game)
    if not state.get("editing"):
        return True
    key = getattr(event, "key", None)
    if key == getattr(pygame, "K_ESCAPE", None):
        close_twp_auto_rules_panel(game, commit=False)
        return True
    if key == getattr(pygame, "K_RETURN", None) or key == getattr(pygame, "K_KP_ENTER", None):
        if _try_add_input_rule(state):
            _play_sound("BUTTON")
        else:
            _play_sound("ERROR")
        return True
    if key == getattr(pygame, "K_BACKSPACE", None):
        state["input_text"] = str(state.get("input_text", "") or "")[:-1]
        state["message"] = ""
        return True
    text = str(getattr(event, "unicode", "") or "")
    if text and text.isprintable():
        current = str(state.get("input_text", "") or "")
        if len(current) < 40:
            state["input_text"] = current + text
            state["message"] = ""
        return True
    return True


def handle_twp_auto_rules_mousewheel(game: Any, y: int) -> bool:
    """Handle MOUSEWHEEL while the rule editor is active."""
    if not is_twp_auto_rules_panel_active(game):
        return False
    state = _state(game)
    rules = list(state.get("working_rules", []) or [])
    max_offset = max(0, len(rules) - VISIBLE_RULE_ROWS)
    try:
        delta = int(y)
    except Exception:
        delta = 0
    state["scroll_offset"] = min(max_offset, max(0, int(state.get("scroll_offset", 0) or 0) - delta))
    return True
