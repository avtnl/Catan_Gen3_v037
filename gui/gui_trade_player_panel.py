"""Human Trade-with-Player panel for Execution turns.

Layer 4A/4B TwP panel:
    - Human clicks TwP in the existing button panel.
    - This panel opens in the same screen slot as the TwB panel.
    - Human enters exact resources plus optional '?' wildcard counts.
    - Opponents choose concrete wildcard resources.
    - Human chooses one willing opponent or NOK.
    - Human confirms the selected concrete deal with OKY/OKN.

This v3 panel intentionally mirrors the TwB layout more closely:
    - resource rows are vertical: Wh/O/Wd/B/Sh/?
    - Offer and Want are two columns
    - after FIND, opponent accept/reject markers appear below the resource rows
    - selecting an opponent replaces '?' with that opponent's concrete response
      and shows OKY/OKN on the right without a text-heavy confirmation screen.

Incoming AI→HP Manual-mode TwP offers are handled in this same module so the
outgoing and incoming TwP panels share one visual style and one layout source.

No HP-to-HP confirmation is implemented here; human counterparties are ignored
by the core lookup for now.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import WIN, COLORS, Font, TRADE_BANK_PANEL_RECT, SOUNDS

try:  # SCREEN_HEIGHT is available in current gui_constants, but keep old builds importable.
    from gui.gui_constants import SCREEN_HEIGHT
except Exception:  # pragma: no cover - import compatibility fallback
    SCREEN_HEIGHT = 720  # type: ignore

try:  # OKY/OKN/NOK images are present in the full GUI, absent in lightweight tests.
    from gui.gui_constants import IMAGES
except Exception:  # pragma: no cover - import compatibility fallback
    IMAGES = {}  # type: ignore

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_SHORT: Tuple[str, ...] = ("Wh", "O", "Wd", "B", "Sh")

# Use the TwB location.  gui_constants shifts the top 10 px up; keep the current bottom
# by letting this panel grow while keeping enough room for opponent results.
_PANEL_EXTRA_HEIGHT = 68
PANEL_RECT = pygame.Rect(
    TRADE_BANK_PANEL_RECT.x,
    TRADE_BANK_PANEL_RECT.y,
    TRADE_BANK_PANEL_RECT.width,
    min(
        max(TRADE_BANK_PANEL_RECT.height + _PANEL_EXTRA_HEIGHT, 318),
        max(TRADE_BANK_PANEL_RECT.height, int(SCREEN_HEIGHT) - TRADE_BANK_PANEL_RECT.y - 10),
    ),
)

ROW_H = 26
LABEL_X = PANEL_RECT.x + 20

# TwB-style vertical table.  The Offer/Want columns hold compact - Nr + controls.
OFFER_X = PANEL_RECT.x + 82
WANT_X = PANEL_RECT.x + 178
COL_W = 74
MINUS_W = 18
VALUE_W = 28
PLUS_W = 18
BUTTON_H = 21
VALUE_DX = 23
PLUS_DX = 56

# Confirmation area to the right of the Want column.
CONFIRM_X = PANEL_RECT.x + 252
CONFIRM_ICON_SIZE = 40
BOTTOM_ACTION_Y = PANEL_RECT.bottom - 33  # NOK/FIND 5 px up versus previous bottom - 28.

CLOSE_RECT = pygame.Rect(PANEL_RECT.right - 28, PANEL_RECT.y + 8, 20, 20)


def clear_trade_player_panel_area() -> None:
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)


def _empty_state() -> Dict[str, Any]:
    return {
        "active": False,
        "stage": "compose",
        "offer": [0, 0, 0, 0, 0],
        "request": [0, 0, 0, 0, 0],
        "offer_wildcard_count": 0,
        "request_wildcard_count": 0,
        # These remain part of the state/core call, but are no longer exposed as
        # extra toggle rows in the v3 TwB-style panel.  The core still prevents
        # same-resource-on-both-sides concrete deals.
        "offer_wildcard_allowed": [True, True, True, True, True],
        "request_wildcard_allowed": [True, True, True, True, True],
        "options": [],
        "selected_option": None,
        "message": "",
        "nok_flash_until": 0,
        "rects": {},
    }


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return _empty_state()
    state = getattr(gui, "twp_panel_state", None)
    if not isinstance(state, dict):
        state = _empty_state()
        setattr(gui, "twp_panel_state", state)

    defaults = _empty_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    for key in ("offer", "request", "offer_wildcard_allowed", "request_wildcard_allowed"):
        values = list(state.get(key, defaults[key]) or defaults[key])[:5]
        while len(values) < 5:
            values.append(defaults[key][len(values)])
        if "allowed" in key:
            state[key] = [bool(v) for v in values]
        else:
            state[key] = [max(0, int(v or 0)) for v in values]
    state["offer_wildcard_count"] = max(0, int(state.get("offer_wildcard_count", 0) or 0))
    state["request_wildcard_count"] = max(0, int(state.get("request_wildcard_count", 0) or 0))
    if state.get("stage") not in {"compose", "choose", "confirm"}:
        state["stage"] = "compose"
    if not isinstance(state.get("rects"), dict):
        state["rects"] = {}
    if not isinstance(state.get("options"), list):
        state["options"] = []
    return state


def is_trade_player_panel_active(game: Any) -> bool:
    return bool(_state(game).get("active"))


def open_trade_player_panel(game: Any) -> None:
    state = _state(game)
    new_state = _empty_state()
    new_state["active"] = True
    state.clear()
    state.update(new_state)
    try:
        game.gui.set_button("twp_panel", True)
    except Exception:
        pass
    # Keep TwB and TwP mutually exclusive without importing the TwB panel.
    try:
        twb = getattr(game.gui, "twb_panel_state", None)
        if isinstance(twb, dict):
            twb["active"] = False
            game.gui.set_button("twb_panel", False)
    except Exception:
        pass


def close_trade_player_panel(game: Any, *, cancel_offer: bool = True) -> None:
    """Close the human TwP compose panel.

    H-D: if the panel had run FIND (choose/confirm stage), record a cancelled
    grant so Phase0/Events can dig-in into abandoned offers.
    """
    state = _state(game)
    stage = str(state.get("stage") or "compose")
    # Only cancel after a scan (FIND); compose-only close is not an offer cancel.
    if cancel_offer and stage in {"choose", "confirm"}:
        try:
            cancel = getattr(game, "cancel_human_twp_offer", None)
            if callable(cancel):
                cancel(reason=f"panel_closed_{stage}")
        except Exception:
            pass
    state.clear()
    state.update(_empty_state())
    try:
        game.gui.set_button("twp_panel", False)
    except Exception:
        pass
    try:
        clear_trade_player_panel_area()
    except Exception:
        pass


def _play_button_sound(game: Any) -> None:
    try:
        sound = SOUNDS.get("BUTTON") or SOUNDS.get("TWPFOUND2")
        if sound is not None:
            pygame.mixer.Sound.play(sound)
    except Exception:
        pass


def _play_error_sound(game: Any) -> None:
    try:
        sound = SOUNDS.get("ERROR") or SOUNDS.get("BUTTON")
        if sound is not None:
            pygame.mixer.Sound.play(sound)
    except Exception:
        pass


def _play_no_twp_found_sound(game: Any) -> None:
    """Play the dedicated No_TwP_Found sound when no opponent accepts."""
    try:
        sound = SOUNDS.get("NOTWPFOUND") or SOUNDS.get("No_TwP_Found") or SOUNDS.get("ERROR") or SOUNDS.get("BUTTON")
        if sound is not None:
            pygame.mixer.Sound.play(sound)
    except Exception:
        pass


def _now_ms() -> int:
    try:
        return int(pygame.time.get_ticks())
    except Exception:
        return 0


def _current_player(game: Any) -> Any:
    try:
        return game.get_current_player()
    except Exception:
        try:
            return game.players[game.turn - 1]
        except Exception:
            return None


def _hand(game: Any) -> List[int]:
    player = _current_player(game)
    hand = [0, 0, 0, 0, 0]
    if player is None:
        return hand
    try:
        info = player.rcards_in_hand()
        if isinstance(info, (list, tuple)) and info and isinstance(info[0], (list, tuple)):
            hand = [int(x or 0) for x in list(info[0])[:5]]
            while len(hand) < 5:
                hand.append(0)
            return hand
    except Exception:
        pass
    try:
        order = game._execution_resource_order() if hasattr(game, "_execution_resource_order") else []
        if order:
            return [int(player.rcards.get(resource, 0) or 0) for resource in order[:5]]
    except Exception:
        pass
    return hand


def _draw_button(
    rect: pygame.Rect,
    label: str,
    *,
    active: bool = True,
    selected: bool = False,
    flash: bool = False,
) -> None:
    fill = COLORS.get("LGRAY", (210, 210, 210)) if selected else COLORS.get("WHITE", (255, 255, 255))
    if flash:
        fill = COLORS.get("YELLOW", (255, 235, 80))
    border = COLORS.get("GREEN", (0, 180, 0)) if active else COLORS.get("GRAY", (130, 130, 130))
    if flash:
        border = COLORS.get("RED", (220, 0, 0))
    text_color = COLORS.get("BLACK", (0, 0, 0)) if active else COLORS.get("GRAY", (130, 130, 130))
    pygame.draw.rect(WIN, fill, rect)
    pygame.draw.rect(WIN, border, rect, 2)
    font = Font.SMALL.value["bold"] if selected or flash else Font.SMALL.value["regular"]
    text = font.render(label, True, text_color)
    WIN.blit(text, text.get_rect(center=rect.center))


def _draw_value_box(rect: pygame.Rect, value: int) -> None:
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), rect)
    pygame.draw.rect(WIN, COLORS.get("GRAY", (130, 130, 130)), rect, 1)
    text = Font.SMALL.value["bold"].render(str(int(value or 0)), True, COLORS.get("WHITE", (255, 255, 255)))
    WIN.blit(text, text.get_rect(center=rect.center))


def _row_control_rects(row_y: int) -> Dict[str, pygame.Rect]:
    return {
        "offer_minus": pygame.Rect(OFFER_X, row_y, MINUS_W, BUTTON_H),
        "offer_value": pygame.Rect(OFFER_X + VALUE_DX, row_y, VALUE_W, BUTTON_H),
        "offer_plus": pygame.Rect(OFFER_X + PLUS_DX, row_y, PLUS_W, BUTTON_H),
        "request_minus": pygame.Rect(WANT_X, row_y, MINUS_W, BUTTON_H),
        "request_value": pygame.Rect(WANT_X + VALUE_DX, row_y, VALUE_W, BUTTON_H),
        "request_plus": pygame.Rect(WANT_X + PLUS_DX, row_y, PLUS_W, BUTTON_H),
    }


def _row_value_rects(row_y: int) -> Dict[str, pygame.Rect]:
    row = _row_control_rects(row_y)
    return {"offer_value": row["offer_value"], "request_value": row["request_value"]}


def _players_except_current(game: Any) -> List[Any]:
    current = _current_player(game)
    current_id = getattr(current, "id", None)
    players: List[Any] = []
    for player in list(getattr(game, "players", []) or []):
        if player is None:
            continue
        try:
            pid = int(getattr(player, "id", -1))
        except Exception:
            continue
        if pid <= 0:
            continue
        if current_id is not None:
            try:
                if pid == int(current_id):
                    continue
            except Exception:
                pass
        players.append(player)
    players.sort(key=lambda p: int(getattr(p, "id", 0) or 0))
    return players


def _willing_ids(options: Sequence[Any]) -> List[int]:
    ids: List[int] = []
    for option in options:
        if not isinstance(option, Mapping):
            continue
        try:
            pid = int(option.get("counterparty_id"))
        except Exception:
            continue
        if pid not in ids:
            ids.append(pid)
    return ids


def _best_option_for_opponent(options: Sequence[Any], player_id: int) -> Optional[Mapping[str, Any]]:
    candidates: List[Mapping[str, Any]] = []
    for opt in options:
        if not isinstance(opt, Mapping):
            continue
        try:
            if int(opt.get("counterparty_id", -1)) == int(player_id):
                candidates.append(opt)
        except Exception:
            continue
    if not candidates:
        return None
    return sorted(candidates, key=lambda opt: (-float(opt.get("score", 0.0) or 0.0), str(opt.get("description", ""))))[0]


def _opponent_results_y(include_question_row: bool = True) -> int:
    base_y = PANEL_RECT.y + 58
    rows = 6 if include_question_row else 5
    return base_y + rows * ROW_H + 10


def _player_border_color(player: Any) -> Tuple[int, int, int]:
    """Return the display color for an accepting opponent rectangle."""
    candidates = [
        getattr(player, "color", None),
        getattr(player, "colour", None),
        getattr(player, "player_color", None),
        getattr(player, "name", None),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if not text:
            continue
        key = text.upper()
        if key in COLORS:
            return COLORS[key]
        title_key = text.title().upper()
        if title_key in COLORS:
            return COLORS[title_key]
    # Stable fallback by player id.
    try:
        pid = int(getattr(player, "id", 0) or 0)
    except Exception:
        pid = 0
    fallback = {1: "BLUE", 2: "RED", 3: "WHITE", 4: "ORANGE"}.get(pid, "GRAY")
    return COLORS.get(fallback, COLORS.get("GRAY", (130, 130, 130)))


def _draw_red_x_inside_rect(rect: pygame.Rect) -> None:
    """Draw a red X matching the diagonals of the opponent rectangle."""
    red = COLORS.get("RED", (220, 0, 0))
    pad = 4
    try:
        if hasattr(pygame.draw, "line"):
            pygame.draw.line(WIN, red, (rect.x + pad, rect.y + pad), (rect.right - pad, rect.bottom - pad), 3)
            pygame.draw.line(WIN, red, (rect.right - pad, rect.y + pad), (rect.x + pad, rect.bottom - pad), 3)
            return
    except Exception:
        pass
    # Lightweight-test fallback where pygame.draw.line may not exist.
    font = Font.SMALL.value["bold"]
    x_text = font.render("X", True, red)
    WIN.blit(x_text, x_text.get_rect(center=rect.center))


def _draw_opponent_results_row(
    game: Any,
    rects: Dict[str, pygame.Rect],
    *,
    options: Optional[Sequence[Any]] = None,
    clickable: bool = False,
    selected_player_id: Optional[int] = None,
    animate_all_willing: bool = False,
    include_question_row: bool = True,
) -> None:
    """Draw opponent accept/reject boxes under the resource table.

    No animation is used.  Rejected/non-willing opponents get a gray rectangle
    plus a red X.  Accepting opponents get a rectangle in that player's color.
    Once one opponent is selected, the selected opponent gets a green rectangle;
    other accepting opponents become gray rectangles without a red X.
    """
    players = _players_except_current(game)
    if not players:
        return

    willing = set(_willing_ids(options or []))
    row_y = _opponent_results_y(include_question_row=include_question_row)
    start_x = OFFER_X + 12
    gap = 78 if len(players) <= 3 else 58
    font = Font.SMALL.value["bold"]

    for index, player in enumerate(players):
        try:
            pid = int(getattr(player, "id", -1))
        except Exception:
            continue
        label = f"P{pid}"
        center = (int(start_x + index * gap), int(row_y + 10))
        box_rect = pygame.Rect(center[0] - 23, center[1] - 14, 46, 28)
        is_willing = pid in willing
        is_selected = selected_player_id is not None and pid == int(selected_player_id)

        if is_selected:
            border_color = COLORS.get("GREEN", (0, 180, 0))
            show_cross = False
        elif is_willing and selected_player_id is None:
            border_color = _player_border_color(player)
            show_cross = False
        elif is_willing:
            border_color = COLORS.get("GRAY", (130, 130, 130))
            show_cross = False
        else:
            border_color = COLORS.get("GRAY", (130, 130, 130))
            show_cross = True

        pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), box_rect)
        pygame.draw.rect(WIN, border_color, box_rect, 3 if is_selected else 2)
        text_color = COLORS.get("BLACK", (0, 0, 0))
        text = font.render(label, True, text_color)
        WIN.blit(text, text.get_rect(center=box_rect.center))
        if show_cross:
            _draw_red_x_inside_rect(box_rect)

        if clickable and is_willing:
            rects[f"opponent_{pid}"] = box_rect

def draw_trade_player_panel(game: Any) -> None:
    state = _state(game)
    if not state.get("active"):
        clear_trade_player_panel_area()
        return

    rects: Dict[str, pygame.Rect] = {}
    state["rects"] = rects
    clear_trade_player_panel_area()
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title_font = Font.NORMAL.value["bold"]
    title = title_font.render("Trade with Player", True, COLORS.get("BLACK", (0, 0, 0)))
    WIN.blit(title, (PANEL_RECT.x + 10, PANEL_RECT.y + 8))
    rects["close"] = CLOSE_RECT
    _draw_button(CLOSE_RECT, "X", active=True)

    stage = str(state.get("stage", "compose"))
    if stage == "compose":
        _draw_compose(game, state, rects)
    elif stage == "choose":
        _draw_choose(game, state, rects)
    elif stage == "confirm":
        _draw_confirm(game, state, rects)


def _draw_column_headers() -> None:
    small = Font.SMALL.value["regular"]
    WIN.blit(small.render("Offer", True, COLORS.get("BLACK", (0, 0, 0))), (OFFER_X + 10, PANEL_RECT.y + 34))
    WIN.blit(small.render("Want", True, COLORS.get("BLACK", (0, 0, 0))), (WANT_X + 12, PANEL_RECT.y + 34))


def _draw_compose(game: Any, state: Dict[str, Any], rects: Dict[str, pygame.Rect]) -> None:
    hand = _hand(game)
    small = Font.SMALL.value["regular"]
    bold = Font.SMALL.value["bold"]

    _draw_column_headers()
    start_y = PANEL_RECT.y + 58

    for idx, abbr in enumerate(RESOURCE_SHORT):
        y = start_y + idx * ROW_H
        label = f"{abbr} ({hand[idx]})"
        WIN.blit(small.render(label, True, COLORS.get("BLACK", (0, 0, 0))), (LABEL_X, y + 3))
        row = _row_control_rects(y)
        for key, rect in row.items():
            rects[f"{key}_{idx}"] = rect
        _draw_button(row["offer_minus"], "-", active=state["offer"][idx] > 0)
        _draw_value_box(row["offer_value"], int(state["offer"][idx]))
        _draw_button(row["offer_plus"], "+", active=state["offer"][idx] < hand[idx])
        _draw_button(row["request_minus"], "-", active=state["request"][idx] > 0)
        _draw_value_box(row["request_value"], int(state["request"][idx]))
        _draw_button(row["request_plus"], "+", active=True)

    # Wildcard row, treated like an extra resource in the UI.
    y = start_y + 5 * ROW_H
    WIN.blit(bold.render("?", True, COLORS.get("BLACK", (0, 0, 0))), (LABEL_X, y + 3))
    row = _row_control_rects(y)
    for key, rect in row.items():
        rects[f"wild_{key}"] = rect
    _draw_button(row["offer_minus"], "-", active=state["offer_wildcard_count"] > 0)
    _draw_value_box(row["offer_value"], int(state["offer_wildcard_count"]))
    _draw_button(row["offer_plus"], "+", active=True)
    _draw_button(row["request_minus"], "-", active=state["request_wildcard_count"] > 0)
    _draw_value_box(row["request_value"], int(state["request_wildcard_count"]))
    _draw_button(row["request_plus"], "+", active=True)

    button_y = BOTTOM_ACTION_Y
    nok_rect = pygame.Rect(OFFER_X, button_y, 70, 27)
    find_rect = pygame.Rect(WANT_X, button_y, 70, 27)
    rects["nok"] = nok_rect
    rects["ok"] = find_rect

    flash_nok = int(state.get("nok_flash_until", 0) or 0) > _now_ms()
    _draw_button(nok_rect, "NOK", active=True, flash=flash_nok)
    _draw_button(find_rect, "FIND", active=True)


def _draw_static_trade_table(
    game: Any,
    state: Dict[str, Any],
    *,
    concrete_option: Optional[Mapping[str, Any]] = None,
    include_question_row: bool = True,
) -> None:
    """Draw Offer/Want values without editable buttons.

    When ``concrete_option`` is passed, the table shows the selected opponent's
    concrete vectors.  Otherwise it shows the original HP input, including '?'.
    """
    hand = _hand(game)
    small = Font.SMALL.value["regular"]
    bold = Font.SMALL.value["bold"]

    if concrete_option is not None:
        offer_values = list(concrete_option.get("proposer_gives", [0, 0, 0, 0, 0]) or [0, 0, 0, 0, 0])[:5]
        request_values = list(concrete_option.get("counterparty_gives", [0, 0, 0, 0, 0]) or [0, 0, 0, 0, 0])[:5]
        offer_wc = 0
        request_wc = 0
    else:
        offer_values = list(state.get("offer", [0, 0, 0, 0, 0]) or [0, 0, 0, 0, 0])[:5]
        request_values = list(state.get("request", [0, 0, 0, 0, 0]) or [0, 0, 0, 0, 0])[:5]
        offer_wc = int(state.get("offer_wildcard_count", 0) or 0)
        request_wc = int(state.get("request_wildcard_count", 0) or 0)

    while len(offer_values) < 5:
        offer_values.append(0)
    while len(request_values) < 5:
        request_values.append(0)

    _draw_column_headers()
    start_y = PANEL_RECT.y + 58
    for idx, abbr in enumerate(RESOURCE_SHORT):
        y = start_y + idx * ROW_H
        label = f"{abbr} ({hand[idx]})"
        WIN.blit(small.render(label, True, COLORS.get("BLACK", (0, 0, 0))), (LABEL_X, y + 3))
        row = _row_value_rects(y)
        _draw_value_box(row["offer_value"], int(offer_values[idx] or 0))
        _draw_value_box(row["request_value"], int(request_values[idx] or 0))

    if include_question_row:
        y = start_y + 5 * ROW_H
        WIN.blit(bold.render("?", True, COLORS.get("BLACK", (0, 0, 0))), (LABEL_X, y + 3))
        row = _row_value_rects(y)
        _draw_value_box(row["offer_value"], int(offer_wc or 0))
        _draw_value_box(row["request_value"], int(request_wc or 0))


def _draw_choose(game: Any, state: Dict[str, Any], rects: Dict[str, pygame.Rect]) -> None:
    # After FIND, freeze numbers and show acceptance markers below the table.
    _draw_static_trade_table(game, state, concrete_option=None, include_question_row=True)
    _draw_opponent_results_row(
        game,
        rects,
        options=list(state.get("options", []) or []),
        clickable=True,
        selected_player_id=None,
        animate_all_willing=True,
        include_question_row=True,
    )

    button_y = BOTTOM_ACTION_Y
    nok_rect = pygame.Rect(OFFER_X, button_y, 70, 27)
    find_rect = pygame.Rect(WANT_X, button_y, 70, 27)
    rects["nok"] = nok_rect
    rects["ok"] = find_rect
    # After FIND, the result is shown. FIND is disabled/gray.
    # NOK remains the normal green active button, also when no opponent accepts.
    _draw_button(nok_rect, "NOK", active=True)
    _draw_button(find_rect, "FIND", active=False)


def _draw_confirmation_icon(rect: pygame.Rect, key: str, fallback_label: str) -> None:
    """Draw a standard OKY/OKN image where available, otherwise a text button."""
    image = None
    try:
        image_entry = IMAGES.get(key, {}) if isinstance(IMAGES, Mapping) else {}
        if isinstance(image_entry, Mapping):
            image = image_entry.get("default") or image_entry.get("40x40") or image_entry.get("30x30")
        else:
            image = image_entry
    except Exception:
        image = None

    if image is not None:
        try:
            WIN.blit(image, (rect.x, rect.y))
            return
        except Exception:
            pass
    _draw_button(rect, fallback_label, active=True)


def _draw_confirm(game: Any, state: Dict[str, Any], rects: Dict[str, pygame.Rect]) -> None:
    option = state.get("selected_option") or {}
    selected_id: Optional[int] = None
    if isinstance(option, Mapping):
        try:
            selected_id = int(option.get("counterparty_id"))
        except Exception:
            selected_id = None

    concrete = option if isinstance(option, Mapping) else None
    _draw_static_trade_table(game, state, concrete_option=concrete, include_question_row=False)

    # Selected opponent label and OKY/OKN live to the right of the Want column.
    # The selected Px is aligned vertically with the Wd row, and moved 5 px
    # right versus the previous version.
    font = Font.SMALL.value["bold"]
    wd_mid_y = PANEL_RECT.y + 58 + 2 * ROW_H + BUTTON_H // 2
    if selected_id is not None:
        selected_text = font.render(f"P{selected_id}", True, COLORS.get("BLACK", (0, 0, 0)))
        WIN.blit(selected_text, selected_text.get_rect(center=(CONFIRM_X - 11, wd_mid_y)))

    oky_rect = pygame.Rect(CONFIRM_X + 3, PANEL_RECT.y + 76, CONFIRM_ICON_SIZE, CONFIRM_ICON_SIZE)
    okn_rect = pygame.Rect(CONFIRM_X + 3, PANEL_RECT.y + 132, CONFIRM_ICON_SIZE, CONFIRM_ICON_SIZE)
    rects["oky"] = oky_rect
    rects["okn"] = okn_rect
    _draw_confirmation_icon(oky_rect, "OKY", "OKY")
    _draw_confirmation_icon(okn_rect, "NOK", "OKN")

    _draw_opponent_results_row(
        game,
        rects,
        options=list(state.get("options", []) or []),
        clickable=True,
        selected_player_id=selected_id,
        animate_all_willing=False,
        include_question_row=False,
    )

    button_y = BOTTOM_ACTION_Y
    nok_rect = pygame.Rect(OFFER_X, button_y, 70, 27)
    find_rect = pygame.Rect(WANT_X, button_y, 70, 27)
    rects["nok"] = nok_rect
    rects["ok"] = find_rect
    _draw_button(nok_rect, "NOK", active=True)
    _draw_button(find_rect, "FIND", active=False)


def _compose_validation(state: Dict[str, Any]) -> Tuple[bool, str]:
    offer = list(state.get("offer", [0, 0, 0, 0, 0]))[:5]
    request = list(state.get("request", [0, 0, 0, 0, 0]))[:5]
    offer_wc = int(state.get("offer_wildcard_count", 0) or 0)
    request_wc = int(state.get("request_wildcard_count", 0) or 0)
    if sum(offer) + offer_wc <= 0:
        return False, "Select offer cards"
    if sum(request) + request_wc <= 0:
        return False, "Select wanted cards"
    return True, ""


def handle_trade_player_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    state = _state(game)
    if not state.get("active"):
        return False
    rects: Dict[str, pygame.Rect] = dict(state.get("rects", {}) or {})

    if not PANEL_RECT.collidepoint(pos):
        return True

    if rects.get("close") and rects["close"].collidepoint(pos):
        _play_button_sound(game)
        close_trade_player_panel(game)
        return True

    stage = str(state.get("stage", "compose"))

    if stage == "compose":
        return _handle_compose_click(game, state, rects, pos)
    if stage == "choose":
        return _handle_choose_click(game, state, rects, pos)
    if stage == "confirm":
        return _handle_confirm_click(game, state, rects, pos)
    return True


def _run_find(game: Any, state: Dict[str, Any]) -> None:
    ok, reason = _compose_validation(state)
    if not ok:
        _play_error_sound(game)
        state["message"] = reason
        state["nok_flash_until"] = 0
        return

    _play_button_sound(game)
    if hasattr(game, "find_human_twp_responder_options"):
        result = game.find_human_twp_responder_options(
            offer_exact=list(state["offer"]),
            offer_wildcard_count=int(state["offer_wildcard_count"]),
            offer_wildcard_allowed=list(state["offer_wildcard_allowed"]),
            request_exact=list(state["request"]),
            request_wildcard_count=int(state["request_wildcard_count"]),
            request_wildcard_allowed=list(state["request_wildcard_allowed"]),
        )
    else:
        result = {"ok": False, "reason": "missing_game_twp_lookup", "options": []}

    options = list((result or {}).get("options", []) or [])
    state["options"] = options
    state["selected_option"] = None
    state["stage"] = "choose"
    state["message"] = ""
    if options:
        state["nok_flash_until"] = 0
    else:
        _play_no_twp_found_sound(game)
        # Stay in choose so all opponents are shown as red X markers; NOK or X closes.
        # NOK is green/active, FIND is gray/inactive; no red/yellow flash needed.
        state["nok_flash_until"] = 0


def _handle_compose_click(game: Any, state: Dict[str, Any], rects: Dict[str, pygame.Rect], pos: Tuple[int, int]) -> bool:
    hand = _hand(game)
    if rects.get("nok") and rects["nok"].collidepoint(pos):
        _play_button_sound(game)
        close_trade_player_panel(game)
        return True

    for idx in range(5):
        if rects.get(f"offer_minus_{idx}") and rects[f"offer_minus_{idx}"].collidepoint(pos):
            _play_button_sound(game)
            state["offer"][idx] = max(0, int(state["offer"][idx]) - 1)
            state["message"] = ""
            state["nok_flash_until"] = 0
            return True
        if rects.get(f"offer_plus_{idx}") and rects[f"offer_plus_{idx}"].collidepoint(pos):
            if int(state["offer"][idx]) < hand[idx]:
                _play_button_sound(game)
                state["offer"][idx] += 1
            else:
                _play_error_sound(game)
            state["message"] = ""
            state["nok_flash_until"] = 0
            return True
        if rects.get(f"request_minus_{idx}") and rects[f"request_minus_{idx}"].collidepoint(pos):
            _play_button_sound(game)
            state["request"][idx] = max(0, int(state["request"][idx]) - 1)
            state["message"] = ""
            state["nok_flash_until"] = 0
            return True
        if rects.get(f"request_plus_{idx}") and rects[f"request_plus_{idx}"].collidepoint(pos):
            _play_button_sound(game)
            state["request"][idx] += 1
            state["message"] = ""
            state["nok_flash_until"] = 0
            return True

    for side in ("offer", "request"):
        count_key = f"{side}_wildcard_count"
        if rects.get(f"wild_{side}_minus") and rects[f"wild_{side}_minus"].collidepoint(pos):
            _play_button_sound(game)
            state[count_key] = max(0, int(state.get(count_key, 0) or 0) - 1)
            state["message"] = ""
            state["nok_flash_until"] = 0
            return True
        if rects.get(f"wild_{side}_plus") and rects[f"wild_{side}_plus"].collidepoint(pos):
            _play_button_sound(game)
            state[count_key] = min(6, int(state.get(count_key, 0) or 0) + 1)
            state["message"] = ""
            state["nok_flash_until"] = 0
            return True

    if rects.get("ok") and rects["ok"].collidepoint(pos):
        _run_find(game, state)
        return True

    return True


def _handle_choose_click(game: Any, state: Dict[str, Any], rects: Dict[str, pygame.Rect], pos: Tuple[int, int]) -> bool:
    if rects.get("nok") and rects["nok"].collidepoint(pos):
        _play_button_sound(game)
        close_trade_player_panel(game)
        return True
    if rects.get("ok") and rects["ok"].collidepoint(pos):
        # FIND is disabled once the offer result is shown.
        _play_error_sound(game)
        return True

    options = list(state.get("options", []) or [])
    for key, rect in rects.items():
        if not key.startswith("opponent_") or rect is None or not rect.collidepoint(pos):
            continue
        try:
            player_id = int(key.split("_", 1)[1])
        except Exception:
            continue
        option = _best_option_for_opponent(options, player_id)
        if option is None:
            _play_error_sound(game)
            return True
        _play_button_sound(game)
        state["selected_option"] = dict(option)
        state["stage"] = "confirm"
        state["message"] = ""
        return True

    return True


def _handle_confirm_click(game: Any, state: Dict[str, Any], rects: Dict[str, pygame.Rect], pos: Tuple[int, int]) -> bool:
    if rects.get("okn") and rects["okn"].collidepoint(pos):
        _play_button_sound(game)
        state["stage"] = "choose"
        state["selected_option"] = None
        return True
    if rects.get("nok") and rects["nok"].collidepoint(pos):
        # Bottom NOK behaves like OKN in the selected-opponent view: restore the
        # original HP input including '?' and return to opponent choice.
        _play_button_sound(game)
        state["stage"] = "choose"
        state["selected_option"] = None
        return True
    if rects.get("ok") and rects["ok"].collidepoint(pos):
        # FIND is disabled while a concrete selected deal is displayed.
        _play_error_sound(game)
        return True
    if rects.get("oky") and rects["oky"].collidepoint(pos):
        option = state.get("selected_option")
        if not isinstance(option, Mapping):
            _play_error_sound(game)
            state["message"] = "No option selected"
            return True
        if hasattr(game, "execute_human_twp_selected_option"):
            result = game.execute_human_twp_selected_option(option)
        else:
            result = {"ok": False, "reason": "missing_game_twp_execute"}
        if bool((result or {}).get("ok")):
            # Successful TwP execution already plays the CashRegister/DEAL sound
            # through core.player_trade / Game.  Do not add an extra button or
            # info beep here.
            close_trade_player_panel(game)
        else:
            _play_error_sound(game)
            state["message"] = str((result or {}).get("reason", "TwP rejected"))[:48]
            state["stage"] = "choose"
        return True

    # Allow selecting a different accepting opponent directly from the confirm view.
    options = list(state.get("options", []) or [])
    for key, rect in rects.items():
        if not key.startswith("opponent_") or rect is None or not rect.collidepoint(pos):
            continue
        try:
            player_id = int(key.split("_", 1)[1])
        except Exception:
            continue
        option = _best_option_for_opponent(options, player_id)
        if option is None:
            _play_error_sound(game)
            return True
        _play_button_sound(game)
        state["selected_option"] = dict(option)
        state["stage"] = "confirm"
        return True

    return True


# ---------------------------------------------------------------------------
# Incoming AI→HP TwP panel
# ---------------------------------------------------------------------------
# Best-clean architecture: the incoming Manual-mode panel lives in this same
# module as the normal HP-proposal TwP panel.  It reuses the same PANEL_RECT,
# title area, close button, resource table spacing, value boxes and bottom row
# style.  The old gui_trade_player_incoming_panel.py file is no longer needed;
# a tiny compatibility wrapper can re-export these functions for older imports.


def _pending_incoming_twp_offer(game: Any) -> Mapping[str, Any]:
    value = getattr(game, "pending_human_twp_offer", None)
    return value if isinstance(value, Mapping) and value.get("active") else {}


def is_twp_counter_panel_active(game: Any) -> bool:
    """T10: True while HP counter builder is open."""
    try:
        from core.human_twp_policy import is_twp_counter_active

        return bool(is_twp_counter_active(game))
    except Exception:
        value = getattr(game, "pending_twp_counter", None)
        return isinstance(value, Mapping) and bool(value.get("active"))


def is_incoming_twp_panel_active(game: Any) -> bool:
    """Return True while an incoming AI→HP Manual-mode TwP offer awaits HP."""
    if is_twp_counter_panel_active(game):
        return False
    return bool(_pending_incoming_twp_offer(game))


def open_incoming_twp_panel(game: Any, offer: Optional[Mapping[str, Any]] = None) -> None:
    """Open/update the incoming TwP panel from a prebuilt pending-offer dict."""
    if offer is None:
        return
    try:
        pending = dict(offer)
        pending.setdefault("active", True)
        game.pending_human_twp_offer = pending
    except Exception:
        pass


def _run_after_human_twp_answer(game: Any, reason: str, work) -> Any:
    """Run AI continue-after-HP-TwP-answer under busy scope so 'AI is thinking...' shows.

    The event loop only redraws after click handlers return; without this latch the
    long ``_continue_ai_twp_after_human_response`` freeze has no wait cue.
    """
    try:
        from core.performance_trace import play_continue_busy_scope
    except Exception:
        return work()
    with play_continue_busy_scope(game, reason=reason):
        return work()


def close_incoming_twp_panel(game: Any) -> None:
    """Close the incoming panel by declining the offer.

    Manual mode cannot leave an AI proposal unresolved, so the X button behaves
    like DECLINE.  If the response does not immediately open a fresh incoming
    offer, clear the TwP panel area so the old offer is not left visible.
    """
    try:
        if hasattr(game, "respond_to_pending_human_twp_offer"):
            _run_after_human_twp_answer(
                game,
                "after_human_twp_response_decline",
                lambda: game.respond_to_pending_human_twp_offer(False),
            )
        else:
            game.pending_human_twp_offer = None
    except Exception:
        try:
            game.pending_human_twp_offer = None
        except Exception:
            pass
    try:
        if not is_incoming_twp_panel_active(game):
            clear_trade_player_panel_area()
    except Exception:
        pass


def _incoming_proposal(game: Any) -> Mapping[str, Any]:
    pending = _pending_incoming_twp_offer(game)
    proposal = pending.get("proposal") if isinstance(pending, Mapping) else None
    return proposal if isinstance(proposal, Mapping) else {}


def _incoming_vec_from_proposal(proposal: Mapping[str, Any], side: str) -> List[int]:
    """Return a five-resource vector for the AI-gives or HP-gives side."""
    vec = [0, 0, 0, 0, 0]
    try:
        if side == "ai_gives":
            idx = int(proposal.get("active_give_index", 0) or 0)
            count = int(proposal.get("active_give_count", 0) or 0)
        else:
            idx = int(proposal.get("active_receive_index", 0) or 0)
            count = int(proposal.get("active_receive_count", 0) or 0)
        if 0 <= idx < 5:
            vec[idx] = max(0, count)
    except Exception:
        pass
    return vec


def _incoming_layout() -> Dict[str, pygame.Rect]:
    """Return click rectangles for the TwB-style incoming panel."""
    button_y = PANEL_RECT.bottom - 38
    button_w = 78
    button_h = 27
    gap = 15
    total_w = button_w * 3 + gap * 2
    start_x = PANEL_RECT.x + max(12, (PANEL_RECT.width - total_w) // 2)
    return {
        "panel": pygame.Rect(PANEL_RECT),
        "close": CLOSE_RECT,
        "decline": pygame.Rect(start_x, button_y, button_w, button_h),
        "accept": pygame.Rect(start_x + button_w + gap, button_y, button_w, button_h),
        "counter": pygame.Rect(start_x + (button_w + gap) * 2, button_y, button_w, button_h),
    }


def _draw_incoming_column_headers() -> None:
    small = Font.SMALL.value["regular"]
    # Keep headers centered above the same value boxes used by the normal TwP panel.
    ai_header = small.render("AI gives", True, COLORS.get("BLACK", (0, 0, 0)))
    hp_header = small.render("HP gives", True, COLORS.get("BLACK", (0, 0, 0)))
    WIN.blit(ai_header, ai_header.get_rect(center=(OFFER_X + VALUE_DX + VALUE_W // 2, PANEL_RECT.y + 43)))
    WIN.blit(hp_header, hp_header.get_rect(center=(WANT_X + VALUE_DX + VALUE_W // 2, PANEL_RECT.y + 43)))


def draw_incoming_twp_panel(game: Any) -> None:
    """Draw the incoming AI→HP TwP panel.

    The layout intentionally mirrors the normal TwP panel: same border, same
    vertical resource rows, same value boxes, no description line and no '?'
    row because the AI offer is already concrete.
    """
    if not is_incoming_twp_panel_active(game):
        return

    rects = _incoming_layout()
    proposal = _incoming_proposal(game)
    ai_vec = _incoming_vec_from_proposal(proposal, "ai_gives")
    hp_vec = _incoming_vec_from_proposal(proposal, "hp_gives")

    clear_trade_player_panel_area()
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title_font = Font.NORMAL.value["bold"]
    title = title_font.render("Trade with Player", True, COLORS.get("BLACK", (0, 0, 0)))
    WIN.blit(title, (PANEL_RECT.x + 10, PANEL_RECT.y + 8))
    _draw_button(CLOSE_RECT, "X", active=True)

    _draw_incoming_column_headers()
    start_y = PANEL_RECT.y + 58
    small = Font.SMALL.value["regular"]
    for idx, abbr in enumerate(RESOURCE_SHORT):
        y = start_y + idx * ROW_H
        WIN.blit(small.render(abbr, True, COLORS.get("BLACK", (0, 0, 0))), (LABEL_X, y + 3))
        row = _row_value_rects(y)
        _draw_value_box(row["offer_value"], int(ai_vec[idx] or 0))
        _draw_value_box(row["request_value"], int(hp_vec[idx] or 0))

    # T10: COUNTER enabled in Manual mode when not endgame-frozen
    counter_active = True
    try:
        from core.human_twp_policy import (
            MODE_MANUAL,
            get_human_twp_mode,
            proposal_hits_twp_endgame_freeze,
        )

        if get_human_twp_mode(game) != MODE_MANUAL:
            counter_active = False
        else:
            hit, _why, _m = proposal_hits_twp_endgame_freeze(game, proposal)
            if hit:
                counter_active = False
    except Exception:
        counter_active = True

    _draw_button(rects["decline"], "DECLINE", active=True)
    _draw_button(rects["accept"], "ACCEPT", active=True)
    _draw_button(rects["counter"], "COUNTER", active=counter_active)


def handle_incoming_twp_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle a click while the incoming TwP panel is active.

    Modal until HP ACCEPT / DECLINE / COUNTER (T10).
    """
    if not is_incoming_twp_panel_active(game):
        return False
    rects = _incoming_layout()

    if rects["close"].collidepoint(pos) or rects["decline"].collidepoint(pos):
        _play_button_sound(game)
        if hasattr(game, "respond_to_pending_human_twp_offer"):
            # Immediate "AI is thinking..." before T8 continue / re-plan freeze.
            _run_after_human_twp_answer(
                game,
                "after_human_twp_response_decline",
                lambda: game.respond_to_pending_human_twp_offer(False),
            )
        else:
            game.pending_human_twp_offer = None
        try:
            if not is_incoming_twp_panel_active(game) and not is_twp_counter_panel_active(game):
                clear_trade_player_panel_area()
        except Exception:
            pass
        return True

    if rects["accept"].collidepoint(pos):
        if hasattr(game, "respond_to_pending_human_twp_offer"):
            # Immediate "AI is thinking..." before T7 binding execute / re-plan freeze.
            _run_after_human_twp_answer(
                game,
                "after_human_twp_response_accept",
                lambda: game.respond_to_pending_human_twp_offer(True),
            )
        else:
            game.pending_human_twp_offer = None
        try:
            if not is_incoming_twp_panel_active(game) and not is_twp_counter_panel_active(game):
                clear_trade_player_panel_area()
        except Exception:
            pass
        return True

    if rects["counter"].collidepoint(pos):
        # T10: open counter builder
        try:
            from core.human_twp_policy import MODE_MANUAL, get_human_twp_mode

            if get_human_twp_mode(game) != MODE_MANUAL:
                _play_error_sound(game)
                return True
        except Exception:
            pass
        if hasattr(game, "begin_human_twp_counter"):
            result = game.begin_human_twp_counter()
            if not result.get("ok"):
                _play_error_sound(game)
            else:
                _play_button_sound(game)
        else:
            _play_error_sound(game)
        return True

    # Modal panel: swallow all other clicks while waiting for HP response.
    return True


# ─────────────────────────────────────────────────────────────────────────────
# T10: Counter builder panel
# ─────────────────────────────────────────────────────────────────────────────


def _counter_pending(game: Any) -> Mapping[str, Any]:
    value = getattr(game, "pending_twp_counter", None)
    return value if isinstance(value, Mapping) and value.get("active") else {}


def _counter_draft(game: Any) -> Dict[str, int]:
    pending = _counter_pending(game)
    draft = pending.get("draft") if isinstance(pending, Mapping) else None
    if isinstance(draft, Mapping) and draft:
        return {
            "ai_give_index": int(draft.get("ai_give_index", 0) or 0),
            "ai_give_count": int(draft.get("ai_give_count", 0) or 0),
            "hp_give_index": int(draft.get("hp_give_index", 0) or 0),
            "hp_give_count": int(draft.get("hp_give_count", 0) or 0),
        }
    try:
        from core.human_twp_policy import draft_from_proposal

        original = pending.get("original_proposal") if isinstance(pending, Mapping) else {}
        return draft_from_proposal(original or {})
    except Exception:
        return {
            "ai_give_index": 0,
            "ai_give_count": 0,
            "hp_give_index": 0,
            "hp_give_count": 0,
        }


def _counter_vec_from_draft(draft: Mapping[str, int], side: str) -> List[int]:
    vec = [0, 0, 0, 0, 0]
    try:
        if side == "ai_gives":
            idx = int(draft.get("ai_give_index", 0) or 0)
            count = int(draft.get("ai_give_count", 0) or 0)
        else:
            idx = int(draft.get("hp_give_index", 0) or 0)
            count = int(draft.get("hp_give_count", 0) or 0)
        if 0 <= idx < 5:
            vec[idx] = max(0, count)
    except Exception:
        pass
    return vec


def _player_hand_by_id(game: Any, player_id: Any) -> List[int]:
    try:
        from core.human_twp_policy import _hand_counts, _player_by_id_local

        p = _player_by_id_local(game, player_id)
        return _hand_counts(p)
    except Exception:
        return [0, 0, 0, 0, 0]


def _counter_layout(*, use_short_labels: bool = True) -> Dict[str, pygame.Rect]:
    button_y = PANEL_RECT.bottom - 38
    button_h = 27
    gap = 8
    # Prefer short labels for fit: Return / Reset / Back
    button_w = 70 if use_short_labels else 92
    total_w = button_w * 3 + gap * 2
    start_x = PANEL_RECT.x + max(8, (PANEL_RECT.width - total_w) // 2)
    return {
        "panel": pygame.Rect(PANEL_RECT),
        "close": CLOSE_RECT,
        "return": pygame.Rect(start_x, button_y, button_w, button_h),
        "reset": pygame.Rect(start_x + button_w + gap, button_y, button_w, button_h),
        "back": pygame.Rect(start_x + (button_w + gap) * 2, button_y, button_w, button_h),
    }


def _set_counter_draft(game: Any, draft: Mapping[str, int]) -> None:
    if hasattr(game, "update_human_twp_counter_draft"):
        game.update_human_twp_counter_draft(dict(draft))
    else:
        pending = getattr(game, "pending_twp_counter", None)
        if isinstance(pending, dict):
            pending["draft"] = dict(draft)


def draw_twp_counter_panel(game: Any) -> None:
    """T10: draw counter builder pre-filled from original offer."""
    if not is_twp_counter_panel_active(game):
        return

    pending = _counter_pending(game)
    draft = _counter_draft(game)
    original = pending.get("original_proposal") if isinstance(pending, Mapping) else {}
    original = original if isinstance(original, Mapping) else {}
    ai_id = original.get("active_player_id")
    hp_id = original.get("counterparty_id")
    ai_hand = _player_hand_by_id(game, ai_id)
    hp_hand = _player_hand_by_id(game, hp_id)
    # CHECK_MODE=False: do not cap AI steppers by real hand (would leak holdings).
    try:
        from core.debug_mode import twp_counter_ai_hand_cap_enabled

        ai_cap_by_hand = bool(twp_counter_ai_hand_cap_enabled())
    except Exception:
        ai_cap_by_hand = True
    COUNTER_AI_GENERIC_MAX = 4

    rects = _counter_layout(use_short_labels=True)
    ai_vec = _counter_vec_from_draft(draft, "ai_gives")
    hp_vec = _counter_vec_from_draft(draft, "hp_gives")

    clear_trade_player_panel_area()
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title_font = Font.NORMAL.value["bold"]
    title = title_font.render("Counter offer", True, COLORS.get("BLACK", (0, 0, 0)))
    WIN.blit(title, (PANEL_RECT.x + 10, PANEL_RECT.y + 8))
    _draw_button(CLOSE_RECT, "X", active=True)

    _draw_incoming_column_headers()
    start_y = PANEL_RECT.y + 58
    small = Font.SMALL.value["regular"]
    for idx, abbr in enumerate(RESOURCE_SHORT):
        y = start_y + idx * ROW_H
        label = f"{abbr}"
        WIN.blit(small.render(label, True, COLORS.get("BLACK", (0, 0, 0))), (LABEL_X, y + 3))
        row = _row_control_rects(y)
        # AI column: dig-in caps by real hand; normal play uses generic max
        ai_count = int(ai_vec[idx] or 0)
        if ai_cap_by_hand:
            ai_max = int(ai_hand[idx] or 0)
            ai_plus = ai_count < min(4, ai_max) if ai_max else False
        else:
            ai_max = COUNTER_AI_GENERIC_MAX
            ai_plus = ai_count < ai_max
        _draw_button(row["offer_minus"], "-", active=ai_count > 0)
        _draw_value_box(row["offer_value"], ai_count)
        _draw_button(row["offer_plus"], "+", active=ai_plus)
        # HP column: steppers capped by HP hand (own cards — always OK)
        hp_count = int(hp_vec[idx] or 0)
        hp_max = int(hp_hand[idx] or 0)
        _draw_button(row["request_minus"], "-", active=hp_count > 0)
        _draw_value_box(row["request_value"], hp_count)
        _draw_button(row["request_plus"], "+", active=hp_count < min(4, hp_max) if hp_max else False)

    _draw_button(rects["return"], "Return", active=True)
    _draw_button(rects["reset"], "Reset", active=True)
    _draw_button(rects["back"], "Back", active=True)


def handle_twp_counter_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    """T10: handle Return / Reset / Back and resource steppers."""
    if not is_twp_counter_panel_active(game):
        return False

    rects = _counter_layout(use_short_labels=True)
    draft = _counter_draft(game)
    pending = _counter_pending(game)
    original = pending.get("original_proposal") if isinstance(pending, Mapping) else {}
    original = original if isinstance(original, Mapping) else {}
    ai_hand = _player_hand_by_id(game, original.get("active_player_id"))
    hp_hand = _player_hand_by_id(game, original.get("counterparty_id"))
    try:
        from core.debug_mode import twp_counter_ai_hand_cap_enabled

        ai_cap_by_hand = bool(twp_counter_ai_hand_cap_enabled())
    except Exception:
        ai_cap_by_hand = True
    COUNTER_AI_GENERIC_MAX = 4

    if rects["close"].collidepoint(pos) or rects["back"].collidepoint(pos):
        # X and Back = restore Incoming (locked Q5)
        _play_button_sound(game)
        if hasattr(game, "back_from_human_twp_counter"):
            game.back_from_human_twp_counter()
        else:
            game.pending_twp_counter = None
        return True

    if rects["reset"].collidepoint(pos):
        _play_button_sound(game)
        if hasattr(game, "reset_human_twp_counter_draft"):
            game.reset_human_twp_counter_draft()
        return True

    if rects["return"].collidepoint(pos):
        if hasattr(game, "return_human_twp_counter"):
            # Return continues the AI (accept/decline counter) — show wait cue now.
            result = _run_after_human_twp_answer(
                game,
                "after_human_twp_counter_return",
                lambda: game.return_human_twp_counter(draft),
            )
            if not isinstance(result, Mapping):
                result = {}
            if not result.get("ok"):
                _play_error_sound(game)
            # Accept may play CashRegister; Decline uses button already skipped
            elif not result.get("accepted"):
                _play_button_sound(game)
        else:
            _play_error_sound(game)
        try:
            if not is_twp_counter_panel_active(game) and not is_incoming_twp_panel_active(game):
                clear_trade_player_panel_area()
        except Exception:
            pass
        return True

    # Resource steppers
    start_y = PANEL_RECT.y + 58
    for idx in range(5):
        y = start_y + idx * ROW_H
        row = _row_control_rects(y)
        # AI give column
        if row["offer_minus"].collidepoint(pos):
            if int(draft.get("ai_give_index", -1)) == idx and int(draft.get("ai_give_count", 0)) > 0:
                draft["ai_give_count"] = int(draft["ai_give_count"]) - 1
                if draft["ai_give_count"] <= 0:
                    draft["ai_give_count"] = 0
                _set_counter_draft(game, draft)
                _play_button_sound(game)
            return True
        if row["offer_plus"].collidepoint(pos):
            if ai_cap_by_hand:
                max_n = min(4, int(ai_hand[idx] or 0))
                if max_n <= 0:
                    _play_error_sound(game)
                    return True
            else:
                max_n = COUNTER_AI_GENERIC_MAX
            # Switch AI resource to this row if needed
            if int(draft.get("ai_give_index", -1)) != idx:
                draft["ai_give_index"] = idx
                draft["ai_give_count"] = 1
            else:
                draft["ai_give_count"] = min(max_n, int(draft.get("ai_give_count", 0) or 0) + 1)
            _set_counter_draft(game, draft)
            _play_button_sound(game)
            return True
        # HP give column
        if row["request_minus"].collidepoint(pos):
            if int(draft.get("hp_give_index", -1)) == idx and int(draft.get("hp_give_count", 0)) > 0:
                draft["hp_give_count"] = int(draft["hp_give_count"]) - 1
                if draft["hp_give_count"] <= 0:
                    draft["hp_give_count"] = 0
                _set_counter_draft(game, draft)
                _play_button_sound(game)
            return True
        if row["request_plus"].collidepoint(pos):
            max_n = min(4, int(hp_hand[idx] or 0))
            if max_n <= 0:
                _play_error_sound(game)
                return True
            if int(draft.get("hp_give_index", -1)) != idx:
                draft["hp_give_index"] = idx
                draft["hp_give_count"] = 1
            else:
                draft["hp_give_count"] = min(max_n, int(draft.get("hp_give_count", 0) or 0) + 1)
            _set_counter_draft(game, draft)
            _play_button_sound(game)
            return True

    return True  # modal swallow
