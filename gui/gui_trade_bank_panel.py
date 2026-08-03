"""Trade-with-Bank panel for human Execution turns.

Robust v045-inspired TwB panel.

The panel is a quantity editor, not a one-click selector:
    - each resource has a Give quantity and a Get quantity;
    - Give changes in chunks equal to that resource's current trade rate;
    - Get changes in single cards;
    - OK is active only when the give/get trade units balance.

UI state lives on ``game.gui.twb_panel_state``.  The real resource mutation is
performed by ``game.execute_trade_with_bank_vector_action(...)``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pygame

from gui.gui_constants import WIN, COLORS, Font, TRADE_BANK_PANEL_RECT, SOUNDS

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")

PANEL_RECT = TRADE_BANK_PANEL_RECT

# The user asked for the interactive controls to be right-aligned, with their
# left edge aligned with the left edge of the NOK button.  Keep all row controls
# and footer buttons on this shared x-coordinate.
CONTROL_BLOCK_WIDTH = 156
CONTROL_BLOCK_X = PANEL_RECT.right - CONTROL_BLOCK_WIDTH - 14
ROW_H = 28

CLOSE_RECT = pygame.Rect(PANEL_RECT.right - 28, PANEL_RECT.y + 8, 20, 20)
NOK_RECT = pygame.Rect(CONTROL_BLOCK_X, PANEL_RECT.bottom - 36, 70, 28)
OK_RECT = pygame.Rect(CONTROL_BLOCK_X + 86, PANEL_RECT.bottom - 36, 70, 28)


def clear_trade_bank_panel_area() -> None:
    """Clear the TwB panel rectangle, including any stale visual controls."""
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return {"active": False, "give": [0, 0, 0, 0, 0], "get": [0, 0, 0, 0, 0], "rects": {}}

    state = getattr(gui, "twb_panel_state", None)
    if not isinstance(state, dict):
        state = {}
        setattr(gui, "twb_panel_state", state)

    state.setdefault("active", False)
    state.setdefault("give", [0, 0, 0, 0, 0])
    state.setdefault("get", [0, 0, 0, 0, 0])
    state.setdefault("rects", {})

    # Normalize old one-click state if the module is hot-swapped during a run.
    if not isinstance(state.get("give"), list) or len(state.get("give", [])) < 5:
        state["give"] = [0, 0, 0, 0, 0]
    if not isinstance(state.get("get"), list) or len(state.get("get", [])) < 5:
        state["get"] = [0, 0, 0, 0, 0]
    state["give"] = [max(0, int(x or 0)) for x in list(state["give"])[:5]]
    state["get"] = [max(0, int(x or 0)) for x in list(state["get"])[:5]]

    return state


def is_trade_bank_panel_active(game: Any) -> bool:
    return bool(_state(game).get("active"))


def open_trade_bank_panel(game: Any) -> None:
    state = _state(game)
    state.update({"active": True, "give": [0, 0, 0, 0, 0], "get": [0, 0, 0, 0, 0], "rects": {}})
    try:
        game.gui.set_button("twb_panel", True)
    except Exception:
        pass


def close_trade_bank_panel(game: Any) -> None:
    state = _state(game)
    state.update({"active": False, "give": [0, 0, 0, 0, 0], "get": [0, 0, 0, 0, 0], "rects": {}})
    try:
        game.gui.set_button("twb_panel", False)
    except Exception:
        pass
    # Remove stale panel graphics immediately.  The event handler redraws after
    # the click as well, but this makes NOK/X/OK visibly deterministic.
    try:
        clear_trade_bank_panel_area()
    except Exception:
        pass


def _hand_and_rates(game: Any) -> Tuple[List[int], List[int]]:
    player = None
    try:
        player = game.get_current_player()
    except Exception:
        try:
            player = game.players[game.turn - 1]
        except Exception:
            player = None

    hand = [0, 0, 0, 0, 0]
    rates = [4, 4, 4, 4, 4]
    if player is None:
        return hand, rates

    try:
        info = player.rcards_in_hand()
        if isinstance(info, (list, tuple)):
            if len(info) >= 1 and isinstance(info[0], (list, tuple)):
                hand = [int(x or 0) for x in list(info[0])[:5]]
            if len(info) >= 2 and isinstance(info[1], (list, tuple)):
                rates = [int(x or 4) for x in list(info[1])[:5]]
    except Exception:
        try:
            order = game._execution_resource_order() if hasattr(game, "_execution_resource_order") else []
            if order:
                hand = [int(player.rcards.get(res, 0) or 0) for res in order[:5]]
        except Exception:
            pass

    # Fallback for older Player objects.
    if rates == [4, 4, 4, 4, 4]:
        for attr in ("trade_rates", "trade_ratio"):
            try:
                candidate = getattr(player, attr, None)
                if isinstance(candidate, (list, tuple)) and len(candidate) >= 5:
                    rates = [int(x or 4) for x in list(candidate)[:5]]
                    break
            except Exception:
                pass

    rates = [(r if r > 0 else 4) for r in (rates + [4, 4, 4, 4, 4])[:5]]
    return hand, rates


def _trade_units(give: List[int], rates: List[int]) -> int:
    units = 0
    for idx in range(5):
        rate = max(1, int(rates[idx] or 4))
        units += int(give[idx] or 0) // rate
    return units


def _validation(game: Any) -> Dict[str, Any]:
    state = _state(game)
    hand, rates = _hand_and_rates(game)
    give = list(state.get("give", [0, 0, 0, 0, 0]))[:5]
    get = list(state.get("get", [0, 0, 0, 0, 0]))[:5]

    reasons: List[str] = []
    for idx in range(5):
        rate = max(1, int(rates[idx] or 4))
        if give[idx] > hand[idx]:
            reasons.append(f"not enough {RESOURCE_NAMES[idx]}")
        if give[idx] % rate != 0:
            reasons.append(f"{RESOURCE_NAMES[idx]} give not multiple of {rate}")
        if give[idx] > 0 and get[idx] > 0:
            reasons.append(f"same resource {RESOURCE_NAMES[idx]}")

    units_give = _trade_units(give, rates)
    units_get = sum(int(x or 0) for x in get)
    if units_give <= 0:
        reasons.append("select give cards")
    if units_get <= 0:
        reasons.append("select get cards")
    if units_give != units_get:
        reasons.append(f"balance {units_give}:{units_get}")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "units_give": units_give,
        "units_get": units_get,
        "hand": hand,
        "rates": rates,
        "give": give,
        "get": get,
    }


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
    fill = COLORS.get("BLACK", (0, 0, 0))
    text_color = COLORS.get("WHITE", (255, 255, 255)) if active else COLORS.get("GRAY", (130, 130, 130))
    pygame.draw.rect(WIN, fill, rect)
    pygame.draw.rect(WIN, COLORS.get("GRAY", (130, 130, 130)), rect, 1)
    text = Font.SMALL.value["bold"].render(str(value), True, text_color)
    WIN.blit(text, text.get_rect(center=rect.center))


def _row_control_rects(row_y: int) -> Dict[str, pygame.Rect]:
    return {
        "give_minus": pygame.Rect(CONTROL_BLOCK_X, row_y, 20, 22),
        "give_value": pygame.Rect(CONTROL_BLOCK_X + 22, row_y, 30, 22),
        "give_plus": pygame.Rect(CONTROL_BLOCK_X + 54, row_y, 20, 22),
        "get_minus": pygame.Rect(CONTROL_BLOCK_X + 82, row_y, 20, 22),
        "get_value": pygame.Rect(CONTROL_BLOCK_X + 104, row_y, 30, 22),
        "get_plus": pygame.Rect(CONTROL_BLOCK_X + 136, row_y, 20, 22),
    }


def draw_trade_bank_panel(game: Any) -> None:
    state = _state(game)
    if not state.get("active"):
        # The panel may have been visible during the previous frame.  Always
        # clear its rectangle when inactive so a stale X/NOK/OK cannot remain
        # on screen after a trade or cancel.
        clear_trade_bank_panel_area()
        return

    hand, rates = _hand_and_rates(game)
    give = list(state.get("give", [0, 0, 0, 0, 0]))[:5]
    get = list(state.get("get", [0, 0, 0, 0, 0]))[:5]
    status = _validation(game)
    rects: Dict[str, pygame.Rect] = {}

    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title_font = Font.NORMAL.value["bold"]
    small = Font.SMALL.value["regular"]
    small_bold = Font.SMALL.value["bold"]

    x = PANEL_RECT.x + 12
    y = PANEL_RECT.y + 8
    WIN.blit(title_font.render("Trade with Bank", True, COLORS["BLACK"]), (x, y))
    _draw_button(CLOSE_RECT, "X", active=True)
    rects["close"] = CLOSE_RECT

    y += 34
    WIN.blit(small_bold.render("Resource", True, COLORS["BLACK"]), (x, y))
    WIN.blit(small_bold.render("Give", True, COLORS["BLACK"]), (CONTROL_BLOCK_X + 16, y))
    WIN.blit(small_bold.render("Get", True, COLORS["BLACK"]), (CONTROL_BLOCK_X + 101, y))
    y += 22

    units_give = int(status.get("units_give", 0) or 0)
    units_get = int(status.get("units_get", 0) or 0)

    for idx, resource_name in enumerate(RESOURCE_NAMES):
        row_y = y + idx * ROW_H
        rate = int(rates[idx] or 4)
        label = f"{resource_name} ({rate}:1)"
        WIN.blit(small.render(label, True, COLORS["BLACK"]), (x, row_y + 3))

        controls = _row_control_rects(row_y)
        give_minus_active = give[idx] > 0
        give_plus_active = give[idx] + rate <= hand[idx]
        # You cannot receive a resource you are giving in the same TwB action.
        get_minus_active = get[idx] > 0
        get_plus_active = give[idx] == 0 and units_get < units_give

        _draw_button(controls["give_minus"], "-", active=give_minus_active)
        _draw_value_box(controls["give_value"], give[idx], active=True)
        _draw_button(controls["give_plus"], "+", active=give_plus_active)

        _draw_button(controls["get_minus"], "-", active=get_minus_active)
        _draw_value_box(controls["get_value"], get[idx], active=True)
        _draw_button(controls["get_plus"], "+", active=get_plus_active)

        for key, rect in controls.items():
            rects[f"{key}_{idx}"] = rect

    # No balance/status sentence here: the table itself shows Give/Get quantities,
    # and the OK button state communicates whether the selected vector is valid.

    _draw_button(NOK_RECT, "NOK", active=True)
    _draw_button(OK_RECT, "OK", active=bool(status.get("ok")))
    rects["nok"] = NOK_RECT
    rects["ok"] = OK_RECT
    state["rects"] = rects


def _play_named_sound(game: Any, name: str) -> None:
    """Play a GUI sound with a direct SOUNDS fallback."""
    try:
        gui = getattr(game, "gui", None)
        play_sound = getattr(gui, "play_sound", None)
        if callable(play_sound):
            play_sound(name)
            return
    except Exception:
        pass
    try:
        sound = SOUNDS.get(str(name)) or SOUNDS.get("BUTTON")
        if sound is not None:
            pygame.mixer.Sound.play(sound)
    except Exception:
        pass


def _play_button_sound(game: Any) -> None:
    _play_named_sound(game, "BUTTON")


def _play_error_sound(game: Any) -> None:
    _play_named_sound(game, "ERROR")


def handle_trade_bank_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    state = _state(game)
    if not state.get("active"):
        return False

    rects = dict(state.get("rects", {}) or {})
    # If the panel was opened but not drawn yet, ensure rectangles exist.
    if not rects:
        draw_trade_bank_panel(game)
        rects = dict(state.get("rects", {}) or {})

    # X and NOK must close the panel in all cases.  Check the static rectangles
    # directly as well as stored rects so a stale rect dictionary can never make
    # the cancel controls unclickable.
    if CLOSE_RECT.collidepoint(pos) or (rects.get("close") and rects["close"].collidepoint(pos)):
        _play_button_sound(game)
        close_trade_bank_panel(game)
        return True

    if NOK_RECT.collidepoint(pos) or (rects.get("nok") and rects["nok"].collidepoint(pos)):
        _play_button_sound(game)
        close_trade_bank_panel(game)
        return True

    if not PANEL_RECT.collidepoint(pos):
        # Keep the panel modal; outside clicks are swallowed but do not mutate.
        return True

    hand, rates = _hand_and_rates(game)
    give = list(state.get("give", [0, 0, 0, 0, 0]))[:5]
    get = list(state.get("get", [0, 0, 0, 0, 0]))[:5]

    for idx in range(5):
        rate = int(rates[idx] or 4)

        rect = rects.get(f"give_minus_{idx}")
        if rect is not None and rect.collidepoint(pos):
            _play_button_sound(game)
            if give[idx] > 0:
                give[idx] = max(0, give[idx] - rate)
                # If the resource becomes give-able again, remove accidental get.
                if give[idx] > 0:
                    get[idx] = 0
                state["give"] = give
                state["get"] = get
            return True

        rect = rects.get(f"give_plus_{idx}")
        if rect is not None and rect.collidepoint(pos):
            _play_button_sound(game)
            if give[idx] + rate <= hand[idx]:
                give[idx] += rate
                get[idx] = 0
                state["give"] = give
                state["get"] = get
            return True

        rect = rects.get(f"get_minus_{idx}")
        if rect is not None and rect.collidepoint(pos):
            _play_button_sound(game)
            if get[idx] > 0:
                get[idx] = max(0, get[idx] - 1)
                state["get"] = get
            return True

        rect = rects.get(f"get_plus_{idx}")
        if rect is not None and rect.collidepoint(pos):
            status = _validation(game)
            _play_button_sound(game)
            if give[idx] == 0 and int(status.get("units_get", 0) or 0) < int(status.get("units_give", 0) or 0):
                get[idx] += 1
                state["get"] = get
            return True

    if rects.get("ok") and rects["ok"].collidepoint(pos):
        status = _validation(game)
        if not bool(status.get("ok")):
            _play_error_sound(game)
            return True
        if hasattr(game, "execute_trade_with_bank_vector_action"):
            result = game.execute_trade_with_bank_vector_action(list(status["give"]), list(status["get"]))
        elif hasattr(game, "execute_trade_with_bank_action"):
            # Very old fallback: only works for one-for-one bank trades.
            give_idx = next((i for i, value in enumerate(status["give"]) if value > 0), None)
            get_idx = next((i for i, value in enumerate(status["get"]) if value > 0), None)
            result = game.execute_trade_with_bank_action(int(give_idx), int(get_idx)) if give_idx is not None and get_idx is not None else {"ok": False, "reason": "missing_selection"}
        else:
            result = {"ok": False, "reason": "missing_game_method"}

        # A valid OK click always closes the modal.  If the Game rejects the
        # trade, report it, but do not leave the user stuck in the panel.
        if not bool(result.get("ok")):
            _play_error_sound(game)
            try:
                reason = str(result.get("reason", "rejected"))
                game.emit_twitter_event(None, f"DBG: TwB rejected; {reason}.")
            except Exception:
                pass
        close_trade_bank_panel(game)
        return True

    return True
