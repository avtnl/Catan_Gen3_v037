"""Human Play Development Card panel (GUI-first).

Shares the TwB/TwP/discard screen slot (PLAY_DCARD_PANEL_RECT).

Types:
  - knight / two_free_roads: Confirm + Cancel only
  - monopoly: one row of 5 RCards (exactly 1 selected → Confirm green)
  - year_of_plenty: two rows of 5 RCards (1 each → Confirm green)

Confirm this phase only prints to the terminal and closes the panel
(no full game-rule execution yet).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import WIN, COLORS, Font, IMAGES, SOUNDS

try:
    from gui.gui_constants import (
        PLAY_DCARD_PANEL_RECT,
        DCARD_PLAY_TYPES,
        DCARD_PLAY_LABELS,
        DCARD_PLAY_IMAGE_KEYS,
        DCARD_PLAYABLE_BORDER,
        DCARD_PANEL_OPEN_BORDER,
    )
except Exception:  # pragma: no cover
    from gui.gui_constants import TRADE_BANK_PANEL_RECT as PLAY_DCARD_PANEL_RECT

    DCARD_PLAY_TYPES = (
        "victory_point",
        "knight",
        "two_free_roads",
        "year_of_plenty",
        "monopoly",
    )
    DCARD_PLAY_LABELS = {
        "victory_point": "Victory Point",
        "knight": "Knight",
        "two_free_roads": "Two Free Roads",
        "year_of_plenty": "Year of Plenty",
        "monopoly": "Monopoly",
    }
    DCARD_PLAY_IMAGE_KEYS = {
        "victory_point": "DC_VPOINT",
        "knight": "DC_KNIGHT",
        "two_free_roads": "DC_ROAD",
        "year_of_plenty": "DC_PLENTY",
        "monopoly": "DC_MONOPOLY",
    }
    DCARD_PLAYABLE_BORDER = (0, 200, 0)
    DCARD_PANEL_OPEN_BORDER = (255, 196, 0)

PANEL_RECT = PLAY_DCARD_PANEL_RECT

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_SHORT: Tuple[str, ...] = ("Wh", "Or", "Wd", "Br", "Sh")
RC_IMAGE_KEYS: Tuple[str, ...] = ("FIELD", "MOUNTAIN", "FOREST", "HILL", "PASTURE")

# Unselected RCard: dark/neutral (recommendation); selected: green
BORDER_IDLE = COLORS.get("DGRAY", (100, 100, 100))
BORDER_SELECTED = COLORS.get("GREEN", (0, 255, 0))
BORDER_CONFIRM_READY = COLORS.get("GREEN", (0, 255, 0))
BORDER_CONFIRM_IDLE = COLORS.get("GRAY", (169, 169, 169))

CLOSE_RECT = pygame.Rect(PANEL_RECT.right - 28, PANEL_RECT.y + 8, 20, 20)
CANCEL_RECT = pygame.Rect(PANEL_RECT.right - 168, PANEL_RECT.bottom - 36, 72, 28)
CONFIRM_RECT = pygame.Rect(PANEL_RECT.right - 86, PANEL_RECT.bottom - 36, 72, 28)

PLAYABLE_TYPES = frozenset({"knight", "two_free_roads", "year_of_plenty", "monopoly"})


def clear_play_dcard_panel_area() -> None:
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return _empty_state()
    state = getattr(gui, "play_dcard_panel_state", None)
    if not isinstance(state, dict):
        state = _empty_state()
        setattr(gui, "play_dcard_panel_state", state)
    state.setdefault("active", False)
    state.setdefault("card_type", None)
    state.setdefault("player_id", None)
    state.setdefault("mono_selected", None)
    state.setdefault("yop_first", None)
    state.setdefault("yop_second", None)
    state.setdefault("rects", {})
    state.setdefault("message", "")
    state.setdefault("confirmed_stub", False)
    return state


def _empty_state() -> Dict[str, Any]:
    return {
        "active": False,
        "card_type": None,
        "player_id": None,
        "mono_selected": None,
        "yop_first": None,
        "yop_second": None,
        "rects": {},
        "message": "",
        "confirmed_stub": False,
    }


def is_play_dcard_panel_active(game: Any) -> bool:
    return bool(_state(game).get("active"))


def get_open_play_dcard_type(game: Any) -> Optional[str]:
    state = _state(game)
    if not state.get("active"):
        return None
    ct = state.get("card_type")
    return str(ct) if ct else None


def _close_competing_panels(game: Any) -> None:
    """Only one trade/discard/play-dcard panel in the shared slot."""
    try:
        from gui.gui_trade_bank_panel import close_trade_bank_panel, is_trade_bank_panel_active

        if is_trade_bank_panel_active(game):
            close_trade_bank_panel(game)
    except Exception:
        pass
    try:
        from gui.gui_trade_player_panel import close_trade_player_panel, is_trade_player_panel_active

        if is_trade_player_panel_active(game):
            close_trade_player_panel(game)
    except Exception:
        pass
    try:
        from gui.gui_discard_panel import close_discard_panel, is_discard_panel_active

        if is_discard_panel_active(game):
            close_discard_panel(game)
    except Exception:
        pass


def open_play_dcard_panel(game: Any, card_type: str, *, player_id: Optional[int] = None) -> bool:
    """Open panel for a playable DCard type. Returns False if invalid."""
    ct = str(card_type or "").strip()
    if ct not in PLAYABLE_TYPES:
        return False

    if player_id is None:
        try:
            player = game.get_current_player()
            player_id = int(getattr(player, "id", 0) or 0)
        except Exception:
            player_id = None

    _close_competing_panels(game)
    state = _state(game)
    state.update(
        {
            "active": True,
            "card_type": ct,
            "player_id": player_id,
            "mono_selected": None,
            "yop_first": None,
            "yop_second": None,
            "rects": {},
            "message": "",
            "confirmed_stub": False,
        }
    )
    try:
        game.gui.set_button("play_dcard_panel", True)
    except Exception:
        pass
    return True


def close_play_dcard_panel(game: Any) -> None:
    state = _state(game)
    state.update(_empty_state())
    try:
        game.gui.set_button("play_dcard_panel", False)
    except Exception:
        pass
    try:
        clear_play_dcard_panel_area()
    except Exception:
        pass


def _confirm_ready(state: Dict[str, Any]) -> bool:
    ct = str(state.get("card_type") or "")
    if ct in {"knight", "two_free_roads"}:
        return True
    if ct == "monopoly":
        return state.get("mono_selected") is not None
    if ct == "year_of_plenty":
        return state.get("yop_first") is not None and state.get("yop_second") is not None
    return False


def _rcard_icon_size() -> int:
    """Fit five icons in the panel body with padding (prefer 40, fall back)."""
    inner = PANEL_RECT.width - 24
    # 5 icons + 4 gaps of 6
    for size in (40, 36, 32, 30):
        if 5 * size + 4 * 6 <= inner:
            return size
    return 28


def _blit_rcard(idx: int, rect: pygame.Rect) -> None:
    key = RC_IMAGE_KEYS[idx] if 0 <= idx < 5 else None
    size = rect.width
    size_key = f"{size}x{size}"
    image = None
    if key:
        try:
            bag = IMAGES.get(key) or {}
            image = bag.get(size_key) or bag.get("40x40") or bag.get("30x30") or bag.get("default")
        except Exception:
            image = None
    if image is not None:
        try:
            if image.get_width() != size or image.get_height() != size:
                image = pygame.transform.smoothscale(image, (size, size))
            WIN.blit(image, rect)
            return
        except Exception:
            pass
    # Fallback: colored square + short label
    fills = [
        COLORS.get("FIELD", (255, 255, 153)),
        COLORS.get("MOUNTAIN", (139, 69, 19)),
        COLORS.get("FOREST", (0, 100, 0)),
        COLORS.get("HILL", (204, 0, 0)),
        COLORS.get("PASTURE", (173, 255, 47)),
    ]
    pygame.draw.rect(WIN, fills[idx] if 0 <= idx < 5 else COLORS["LGRAY"], rect)
    try:
        txt = Font.SMALL.value["bold"].render(RESOURCE_SHORT[idx], True, COLORS["BLACK"])
        WIN.blit(txt, txt.get_rect(center=rect.center))
    except Exception:
        pass


def _draw_button(rect: pygame.Rect, label: str, *, enabled: bool, ready_border: bool = False) -> None:
    fill = COLORS.get("WHITE", (255, 255, 255))
    if ready_border and enabled:
        border = BORDER_CONFIRM_READY
        width = 3
    elif enabled:
        border = COLORS.get("BLACK", (0, 0, 0))
        width = 2
    else:
        border = BORDER_CONFIRM_IDLE
        width = 2
    text_color = COLORS.get("BLACK", (0, 0, 0)) if enabled else COLORS.get("GRAY", (130, 130, 130))
    pygame.draw.rect(WIN, fill, rect)
    pygame.draw.rect(WIN, border, rect, width)
    font = Font.SMALL.value["bold"] if ready_border and enabled else Font.SMALL.value["regular"]
    text = font.render(label, True, text_color)
    WIN.blit(text, text.get_rect(center=rect.center))


def _draw_rcard_row(
    *,
    y: int,
    selected_idx: Optional[int],
    rects: Dict[str, pygame.Rect],
    prefix: str,
) -> None:
    size = _rcard_icon_size()
    gap = 6
    total_w = 5 * size + 4 * gap
    start_x = PANEL_RECT.x + max(12, (PANEL_RECT.width - total_w) // 2)
    for idx in range(5):
        r = pygame.Rect(start_x + idx * (size + gap), y, size, size)
        _blit_rcard(idx, r)
        selected = selected_idx is not None and int(selected_idx) == idx
        border = BORDER_SELECTED if selected else BORDER_IDLE
        pygame.draw.rect(WIN, border, r, 3 if selected else 2)
        rects[f"{prefix}_{idx}"] = r


def _dc_icon(card_type: str, size: int = 30):
    key = DCARD_PLAY_IMAGE_KEYS.get(card_type)
    if not key:
        return None
    try:
        bag = IMAGES.get(key) or {}
        img = bag.get(f"{size}x{size}") or bag.get("30x30") or bag.get("40x40")
        return img
    except Exception:
        return None


def draw_play_dcard_panel(game: Any) -> None:
    state = _state(game)
    if not state.get("active"):
        clear_play_dcard_panel_area()
        return

    ct = str(state.get("card_type") or "")
    label = DCARD_PLAY_LABELS.get(ct, ct or "DCard")
    rects: Dict[str, pygame.Rect] = {}
    ready = _confirm_ready(state)

    pygame.draw.rect(WIN, COLORS.get("LGRAY", (210, 210, 210)), PANEL_RECT)
    pygame.draw.rect(WIN, COLORS.get("BLACK", (0, 0, 0)), PANEL_RECT, 2)

    title_font = Font.NORMAL.value["bold"]
    small = Font.SMALL.value["regular"]
    small_bold = Font.SMALL.value["bold"]

    x = PANEL_RECT.x + 12
    y = PANEL_RECT.y + 8
    icon = _dc_icon(ct, 30)
    if icon is not None:
        try:
            WIN.blit(icon, (x, y))
            x += 36
        except Exception:
            pass
    WIN.blit(title_font.render(f"Play · {label}", True, COLORS["BLACK"]), (x, y + 4))
    _draw_button(CLOSE_RECT, "X", enabled=True)
    rects["close"] = CLOSE_RECT

    body_y = PANEL_RECT.y + 44
    if ct in {"knight", "two_free_roads"}:
        if ct == "knight":
            dice_roll = getattr(game, "dice_roll", None)
            pre = dice_roll in (None, 0, "", []) or str(getattr(game, "state", "")) == "AwaitingDiceRoll"
            lines = (
                "Play a Knight?",
                "Then: move the robber and steal if possible.",
                "Before roll — then you must roll the dice."
                if pre
                else "After roll — then continue your turn (buy/trade/end).",
            )
        else:
            pieces = 15
            try:
                if hasattr(game, "player_roads_remaining"):
                    pl = game.get_current_player()
                    pieces = int(game.player_roads_remaining(pl))
            except Exception:
                pieces = 15
            n = min(2, max(0, pieces))
            lines = (
                "Play Two Free Roads?",
                f"Then place {n} free road(s) on the board (no cost).",
                "If only 1 road piece remains, you place only 1.",
            )
        WIN.blit(small_bold.render(lines[0], True, COLORS["BLACK"]), (PANEL_RECT.x + 14, body_y))
        WIN.blit(small.render(lines[1], True, COLORS["DGRAY"]), (PANEL_RECT.x + 14, body_y + 22))
        WIN.blit(small.render(lines[2], True, COLORS["DGRAY"]), (PANEL_RECT.x + 14, body_y + 44))
    elif ct == "monopoly":
        WIN.blit(
            small_bold.render("Choose 1 resource type", True, COLORS["BLACK"]),
            (PANEL_RECT.x + 14, body_y),
        )
        WIN.blit(
            small.render("Take all of that type from opponents (later).", True, COLORS["DGRAY"]),
            (PANEL_RECT.x + 14, body_y + 18),
        )
        _draw_rcard_row(y=body_y + 42, selected_idx=state.get("mono_selected"), rects=rects, prefix="mono")
        sel = state.get("mono_selected")
        if sel is not None and 0 <= int(sel) < 5:
            WIN.blit(
                small.render(f"Selected: {RESOURCE_NAMES[int(sel)]}", True, COLORS["BLACK"]),
                (PANEL_RECT.x + 14, body_y + 42 + _rcard_icon_size() + 10),
            )
        else:
            WIN.blit(
                small.render("Selected: —", True, COLORS["DGRAY"]),
                (PANEL_RECT.x + 14, body_y + 42 + _rcard_icon_size() + 10),
            )
    elif ct == "year_of_plenty":
        WIN.blit(
            small_bold.render("Choose 2 resources from the bank", True, COLORS["BLACK"]),
            (PANEL_RECT.x + 14, body_y),
        )
        row_h = _rcard_icon_size() + 22
        WIN.blit(small.render("First pick:", True, COLORS["BLACK"]), (PANEL_RECT.x + 14, body_y + 18))
        _draw_rcard_row(y=body_y + 36, selected_idx=state.get("yop_first"), rects=rects, prefix="yop1")
        WIN.blit(
            small.render("Second pick:", True, COLORS["BLACK"]),
            (PANEL_RECT.x + 14, body_y + 36 + row_h),
        )
        _draw_rcard_row(
            y=body_y + 36 + row_h + 16,
            selected_idx=state.get("yop_second"),
            rects=rects,
            prefix="yop2",
        )
        a = state.get("yop_first")
        b = state.get("yop_second")
        a_txt = RESOURCE_NAMES[int(a)] if a is not None and 0 <= int(a) < 5 else "—"
        b_txt = RESOURCE_NAMES[int(b)] if b is not None and 0 <= int(b) < 5 else "—"
        status_y = min(PANEL_RECT.bottom - 52, body_y + 36 + 2 * row_h + 20)
        WIN.blit(small.render(f"Picks: {a_txt} + {b_txt}", True, COLORS["BLACK"]), (PANEL_RECT.x + 14, status_y))

    msg = str(state.get("message") or "")
    if msg:
        WIN.blit(
            small.render(msg[:48], True, COLORS.get("FOREST", (0, 100, 0))),
            (PANEL_RECT.x + 12, PANEL_RECT.bottom - 58),
        )

    _draw_button(CANCEL_RECT, "Cancel", enabled=True)
    _draw_button(CONFIRM_RECT, "Confirm", enabled=ready, ready_border=ready)
    rects["cancel"] = CANCEL_RECT
    rects["confirm"] = CONFIRM_RECT
    state["rects"] = rects


def _format_confirm_action(state: Dict[str, Any]) -> str:
    ct = str(state.get("card_type") or "")
    pid = state.get("player_id")
    if ct == "knight":
        return f"Play DCard: Knight (player {pid})"
    if ct == "two_free_roads":
        return f"Play DCard: Two Free Roads (player {pid})"
    if ct == "monopoly":
        sel = state.get("mono_selected")
        name = RESOURCE_NAMES[int(sel)] if sel is not None and 0 <= int(sel) < 5 else "?"
        return f"Play DCard: Monopoly → {name} (player {pid})"
    if ct == "year_of_plenty":
        a = state.get("yop_first")
        b = state.get("yop_second")
        an = RESOURCE_NAMES[int(a)] if a is not None and 0 <= int(a) < 5 else "?"
        bn = RESOURCE_NAMES[int(b)] if b is not None and 0 <= int(b) < 5 else "?"
        return f"Play DCard: Year of Plenty → {an} + {bn} (player {pid})"
    return f"Play DCard: {ct} (player {pid})"


def _play_panel_sound(game: Any, name: str = "BUTTON") -> None:
    """Play a panel UI sound (gui.play_sound if present, else SOUNDS)."""
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


def handle_play_dcard_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle click while panel is open. Returns True if click was consumed."""
    state = _state(game)
    if not state.get("active"):
        return False

    # Modal: any click while active is owned by this panel
    rects = state.get("rects") if isinstance(state.get("rects"), dict) else {}

    def _hit(name: str) -> bool:
        r = rects.get(name)
        return isinstance(r, pygame.Rect) and r.collidepoint(pos)

    if _hit("close") or _hit("cancel"):
        _play_panel_sound(game, "BUTTON")
        close_play_dcard_panel(game)
        return True

    if _hit("confirm"):
        if not _confirm_ready(state):
            state["message"] = "Select required resources first."
            _play_panel_sound(game, "ERROR")
            return True
        action_text = _format_confirm_action(state)
        print(action_text)
        state["confirmed_stub"] = True
        ct = str(state.get("card_type") or "")

        # Knight / YOP / Monopoly / TFR: real execution.
        if ct in {"knight", "year_of_plenty", "monopoly", "two_free_roads"}:
            exec_result = None
            try:
                if ct == "knight" and hasattr(game, "execute_human_play_knight_action"):
                    exec_result = game.execute_human_play_knight_action()
                elif ct == "year_of_plenty" and hasattr(game, "execute_human_play_yop_action"):
                    exec_result = game.execute_human_play_yop_action(
                        state.get("yop_first"),
                        state.get("yop_second"),
                    )
                elif ct == "monopoly" and hasattr(game, "execute_human_play_monopoly_action"):
                    exec_result = game.execute_human_play_monopoly_action(state.get("mono_selected"))
                elif ct == "two_free_roads" and hasattr(game, "execute_human_play_tfr_action"):
                    exec_result = game.execute_human_play_tfr_action()
            except Exception as exc:
                exec_result = {"ok": False, "reason": str(exc)}
            print(f"Play {ct} execution → {exec_result}")
            if not bool((exec_result or {}).get("ok")):
                state["message"] = str((exec_result or {}).get("reason") or "play_failed")
                state["confirmed_stub"] = False
                _play_panel_sound(game, "ERROR")
                return True
            # Success: play-card cue (BUTTON already covers Cancel / RCard picks).
            _play_panel_sound(game, "PLAYDCARD")
            close_play_dcard_panel(game)
            # TFR: open free road selector for first (and later second) free road
            if ct == "two_free_roads" and bool((exec_result or {}).get("open_free_road_guidance")):
                try:
                    from gui.gui_human_road_guidance import open_human_road_guidance

                    opened = open_human_road_guidance(game, free_tfr=True)
                    if not opened:
                        print("TFR: no legal free road candidates after play")
                        try:
                            player = game.get_current_player()
                            if hasattr(game, "_complete_tfr_play") and player is not None:
                                game._complete_tfr_play(player, early=True)
                        except Exception:
                            pass
                except Exception as exc:
                    print(f"TFR: failed to open free road guidance: {exc}")
            return True

        try:
            if hasattr(game, "emit_twitter_event"):
                game.emit_twitter_event(state.get("player_id"), action_text)
        except Exception:
            pass
        _play_panel_sound(game, "PLAYDCARD")
        state["message"] = "Confirmed (GUI demo — not executed yet)."
        close_play_dcard_panel(game)
        return True

    ct = str(state.get("card_type") or "")
    if ct == "monopoly":
        for idx in range(5):
            if _hit(f"mono_{idx}"):
                cur = state.get("mono_selected")
                state["mono_selected"] = None if cur is not None and int(cur) == idx else idx
                state["message"] = ""
                _play_panel_sound(game, "BUTTON")
                return True
    elif ct == "year_of_plenty":
        for idx in range(5):
            if _hit(f"yop1_{idx}"):
                cur = state.get("yop_first")
                state["yop_first"] = None if cur is not None and int(cur) == idx else idx
                state["message"] = ""
                _play_panel_sound(game, "BUTTON")
                return True
            if _hit(f"yop2_{idx}"):
                cur = state.get("yop_second")
                state["yop_second"] = None if cur is not None and int(cur) == idx else idx
                state["message"] = ""
                _play_panel_sound(game, "BUTTON")
                return True

    # Swallow outside clicks while modal
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Scoreboard hit-testing helpers (used by gui.py + event_handler)
# ─────────────────────────────────────────────────────────────────────────────


def playable_count_for_type(player: Any, card_type: str) -> int:
    """Return how many of this DCard type the player can open in the Play UI.

    Summary row: ``[name, new/received (x), playable (y), played (z)]``.
    Only *y* (column 2) is playable. Same-turn buys stay in *x* until
    ``Game._mature_player_dcard_new_to_playable`` runs at end of turn.
    """
    ct = str(card_type or "")
    if ct == "victory_point":
        return 0
    expected = list(DCARD_PLAY_TYPES)
    try:
        idx = expected.index(ct)
    except ValueError:
        return 0
    try:
        summary = list(getattr(player, "dcard_summary", []) or [])
        row = list(summary[idx])
        if row and str(row[0]) == ct and len(row) >= 3:
            return max(0, int(row[2] or 0))
    except Exception:
        pass
    # No summary row: cannot infer same-turn vs playable; treat as not playable
    # so a buy does not become instantly clickable without maturity.
    return 0


def is_dcard_type_playable_now(game: Any, player: Any, card_type: str) -> bool:
    """GUI viability: human current player, playable type, count > 0."""
    ct = str(card_type or "")
    if ct not in PLAYABLE_TYPES:
        return False
    if str(getattr(game, "phase", "") or "") != "Execution":
        return False
    state = str(getattr(game, "state", "") or "")
    # Block during forced discard / robber steal flows
    blocked = ("Discard", "Robber", "Steal", "Seven", "MoveRobber", "SetRobber")
    if any(b in state for b in blocked):
        return False
    # Already played a DCard this turn
    try:
        td = getattr(game, "myturn", None) or getattr(game, "turn_details", None)
        if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
            return False
    except Exception:
        pass
    try:
        if not bool(getattr(player, "is_human", False)):
            return False
    except Exception:
        return False
    try:
        current = game.get_current_player()
        if current is None or int(getattr(current, "id", -1)) != int(getattr(player, "id", -2)):
            return False
    except Exception:
        return False

    # Knight: before roll (AwaitingDiceRoll) OR after roll (ActionSelection).
    # Other progress cards: only after dice (ActionSelection) for now.
    dice_roll = getattr(game, "dice_roll", None)
    dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"
    if ct == "knight":
        if dice_not_rolled:
            if state not in {"AwaitingDiceRoll", ""} and state != "AwaitingDiceRoll":
                # Still allow when dice clearly not rolled
                if state and "Action" in state:
                    return False
        else:
            if state != "ActionSelection":
                return False
    else:
        if dice_not_rolled or state != "ActionSelection":
            return False

    if playable_count_for_type(player, ct) <= 0:
        return False

    # TFR: no green border if player has no unused road pieces (max 15).
    if ct == "two_free_roads":
        try:
            remaining = (
                int(game.player_roads_remaining(player))
                if hasattr(game, "player_roads_remaining")
                else max(0, 15 - len(list(getattr(player, "roads", []) or [])))
            )
        except Exception:
            remaining = max(0, 15 - len(list(getattr(player, "roads", []) or [])))
        if remaining <= 0:
            return False

    return True


def register_scoreboard_dcard_hit(
    game: Any,
    *,
    player_id: int,
    card_type: str,
    rect: pygame.Rect,
    playable: bool,
) -> None:
    gui = getattr(game, "gui", None)
    if gui is None:
        return
    hits = getattr(gui, "dcard_scoreboard_hit_rects", None)
    if not isinstance(hits, list):
        hits = []
        setattr(gui, "dcard_scoreboard_hit_rects", hits)
    hits.append(
        {
            "player_id": int(player_id),
            "card_type": str(card_type),
            "rect": rect,
            "playable": bool(playable),
        }
    )


def clear_scoreboard_dcard_hits(game: Any) -> None:
    gui = getattr(game, "gui", None)
    if gui is not None:
        setattr(gui, "dcard_scoreboard_hit_rects", [])


def handle_scoreboard_dcard_click(game: Any, pos: Tuple[int, int]) -> bool:
    """If click hits a playable scoreboard DCard, open the play panel."""
    gui = getattr(game, "gui", None)
    if gui is None:
        return False
    hits = getattr(gui, "dcard_scoreboard_hit_rects", None) or []
    for item in hits:
        if not isinstance(item, dict):
            continue
        if not item.get("playable"):
            continue
        rect = item.get("rect")
        if not isinstance(rect, pygame.Rect) or not rect.collidepoint(pos):
            continue
        ct = str(item.get("card_type") or "")
        if ct not in PLAYABLE_TYPES:
            continue
        ok = open_play_dcard_panel(game, ct, player_id=item.get("player_id"))
        return bool(ok)
    return False
