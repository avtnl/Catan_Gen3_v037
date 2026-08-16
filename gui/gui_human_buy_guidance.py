"""Human Execution-phase buy/build guidance for City, Settlement and DCard.

This module mirrors the Human Buy Road guidance pattern: the shared
viable_action_scanner / execution-manager output supplies the legal candidates,
while the human UI lets the player choose and confirm with OKY / OKN.

Game owns final mutations through public execute_human_* methods.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import pygame

from gui.gui_constants import COLORS, IMAGES, POSITIONS, WIN, SOUNDS

BUILD_CITY = "Build city"
BUILD_SETTLEMENT = "Build settlement"
BUY_DCARD = "Buy development_card"

CITY_MODE = "Show_available_cities"
SETTLEMENT_MODE = "Show_available_settlements"
DCARD_MODE = "Confirm_buy_dcard"
BUY_GUIDANCE_MODES = {CITY_MODE, SETTLEMENT_MODE, DCARD_MODE}

INTERSECTION_CLICK_RADIUS = 20
INTERSECTION_HIGHLIGHT_DIAMETER = 22
DCARD_CONFIRM_CENTER = (310, 280)


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return {"active": False, "action": "", "candidates": [], "selected_target": None}
    state = getattr(gui, "human_buy_guidance_state", None)
    if not isinstance(state, dict):
        state = {"active": False, "action": "", "candidates": [], "selected_target": None}
        setattr(gui, "human_buy_guidance_state", state)
    state.setdefault("active", False)
    state.setdefault("action", "")
    state.setdefault("candidates", [])
    state.setdefault("selected_target", None)
    return state


def is_human_buy_guidance_active(game: Any) -> bool:
    """Return True when a City/Settlement/DCard human buy modal is active."""
    return bool(_state(game).get("active", False))


def open_human_city_guidance(game: Any) -> bool:
    """Open City upgrade guidance from shared scanner candidates."""
    return _open_intersection_guidance(game, BUILD_CITY, CITY_MODE)


def open_human_settlement_guidance(game: Any) -> bool:
    """Open Settlement build guidance from shared scanner candidates."""
    return _open_intersection_guidance(game, BUILD_SETTLEMENT, SETTLEMENT_MODE)


def open_human_dcard_confirmation(game: Any) -> bool:
    """Open OKY/OKN confirmation for buying one development card."""
    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None:
        return False

    try:
        if str(getattr(game, "phase", "")) == "Execution" and str(getattr(game, "state", "")) == "ActionSelection":
            refresh = getattr(game, "refresh_viable_actions", None)
            if callable(refresh):
                refresh("human_buy_dcard_open")
    except Exception:
        pass

    if not _dcard_is_legal_now(game, player):
        _emit(game, player, "DBG: human Buy DCard opened, but DCard is not legal now.")
        return False

    state = _state(game)
    state.update({
        "active": True,
        "action": BUY_DCARD,
        "candidates": [],
        "selected_target": None,
    })
    _clear_buy_modes(gui)
    _set_mode(gui, DCARD_MODE, True)
    try:
        if hasattr(gui, "human_guidance"):
            gui.human_guidance.confirm_center = DCARD_CONFIRM_CENTER
    except Exception:
        pass
    draw_human_buy_guidance(game)
    return True


def close_human_buy_guidance(game: Any, *, redraw: bool = True) -> None:
    """Close the active City/Settlement/DCard guidance modal."""
    gui = getattr(game, "gui", None)
    state = _state(game)
    state.update({"active": False, "action": "", "candidates": [], "selected_target": None})
    if gui is not None:
        _clear_buy_modes(gui)
        try:
            if hasattr(gui, "human_guidance"):
                gui.human_guidance.confirm_center = None
        except Exception:
            pass
        try:
            if hasattr(gui, "animate_queue_elements"):
                gui.animate_queue_elements.clear()
        except Exception:
            pass
        if redraw:
            try:
                gui.draw_board_base(game.board)
                gui.draw_all_permanent_buildings(game.board)
                pygame.display.update()
            except Exception:
                pass


def draw_human_buy_guidance(game: Any) -> None:
    """Draw candidate pulses or OKY/OKN confirmation for the active buy modal."""
    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None or not is_human_buy_guidance_active(game):
        return

    state = _state(game)
    action = str(state.get("action", "") or "")
    selected = _safe_int_or_none(state.get("selected_target"))
    candidates = [_safe_int_or_none(x) for x in list(state.get("candidates", []) or [])]
    candidates = [x for x in candidates if x is not None]

    try:
        color = COLORS.get(str(getattr(player, "color", "")).upper(), COLORS.get("GREEN", (0, 180, 0)))
    except Exception:
        color = (0, 180, 0)

    try:
        if hasattr(gui, "animate_queue_elements"):
            gui.animate_queue_elements.clear()
        # City/settlement guidance should remain visible even when it follows
        # a robber/steal animation clear.
        try:
            gui.animations_enabled = True
        except Exception:
            pass

        if action == BUY_DCARD:
            if hasattr(gui, "human_guidance"):
                gui.human_guidance.confirm_center = DCARD_CONFIRM_CENTER
            if hasattr(gui, "draw_guidance_text"):
                gui.draw_guidance_text("Confirm buy DCard?", y_offset=25)
            _draw_ok_icons(DCARD_CONFIRM_CENTER)
            pygame.display.update()
            return

        queue_kind = _animation_kind_for_action(action)

        if selected is not None:
            center = _intersection_center(selected)
            if center is not None:
                gui.animate_queue_elements.append((center, color, INTERSECTION_HIGHLIGHT_DIAMETER, queue_kind))
                if hasattr(gui, "human_guidance"):
                    gui.human_guidance.confirm_center = center
                if hasattr(gui, "draw_guidance_text"):
                    gui.draw_guidance_text(f"Confirm {_short_action(action)} @{selected}?", y_offset=25)
                _draw_ok_icons(center)
        else:
            if hasattr(gui, "human_guidance"):
                gui.human_guidance.confirm_center = None
            for target in candidates:
                center = _intersection_center(target)
                if center is not None:
                    gui.animate_queue_elements.append((center, color, INTERSECTION_HIGHLIGHT_DIAMETER, queue_kind))
            if hasattr(gui, "draw_guidance_text"):
                gui.draw_guidance_text(f"Click a highlighted {_short_action(action).lower()} target", y_offset=25)

        if hasattr(gui, "_animate_elements"):
            gui._animate_elements(getattr(game, "board", None))
        pygame.display.update()
    except Exception:
        pass


def handle_human_buy_guidance_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle all clicks while City/Settlement/DCard guidance is active."""
    if not is_human_buy_guidance_active(game):
        return False

    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None:
        close_human_buy_guidance(game)
        return True

    state = _state(game)
    action = str(state.get("action", "") or "")
    selected = _safe_int_or_none(state.get("selected_target"))

    if action == BUY_DCARD:
        conf = _confirmation_click(gui, pos)
        if conf == "OKY":
            result = _execute_dcard(game)
            if isinstance(result, Mapping) and bool(result.get("ok")):
                # The Game execution method already plays the action-specific
                # success sound (BuyDCard/Fanfare).  Do not add an extra button
                # or info beep after a successful buy.
                close_human_buy_guidance(game, redraw=False)
                try:
                    gui.clear_guidance_text(y_offset=25)
                except Exception:
                    pass
                _refresh_after_buy(game, "after_human_buy_dcard")
            else:
                _play_sound(gui, "ERROR")
                reason = result.get("reason") if isinstance(result, Mapping) else "unknown_error"
                _emit(game, player, f"DBG: human DCard rejected; {reason}.")
                close_human_buy_guidance(game, redraw=False)
                try:
                    gui.clear_guidance_text(y_offset=25)
                except Exception:
                    pass
                _refresh_after_buy(game, "after_human_buy_dcard_rejected")
            return True
        if conf == "OKN":
            _play_sound(gui, "BUTTON")
            close_human_buy_guidance(game, redraw=False)
            try:
                gui.clear_guidance_text(y_offset=25)
            except Exception:
                pass
            _refresh_after_buy(game, "after_human_buy_dcard_cancelled")
            return True
        _play_sound(gui, "ERROR")
        return True

    if selected is not None:
        conf = _confirmation_click(gui, pos)
        if conf == "OKY":
            result = _execute_intersection_action(game, action, selected)
            if isinstance(result, Mapping) and bool(result.get("ok")):
                # The Game execution method already plays the action-specific
                # success sound (BuyDCard/Fanfare).  Do not add an extra button
                # or info beep after a successful buy.
                close_human_buy_guidance(game, redraw=False)
                # G3: clear "Confirm City @N?" / Settlement confirm line
                try:
                    gui.clear_guidance_text(y_offset=25)
                except Exception:
                    pass
                _refresh_after_buy(game, f"after_human_{_reason_token(action)}")
            else:
                _play_sound(gui, "ERROR")
                reason = result.get("reason") if isinstance(result, Mapping) else "unknown_error"
                _emit(game, player, f"DBG: human {_short_action(action)} @{selected} rejected; {reason}.")
                state["selected_target"] = None
                # Rebuild the candidate list in case another click made this target stale.
                state["candidates"] = legal_human_intersection_candidates(game, player, action)
                draw_human_buy_guidance(game)
            return True

        if conf == "OKN":
            _play_sound(gui, "BUTTON")
            state["selected_target"] = None
            try:
                gui.clear_guidance_text(y_offset=25)
            except Exception:
                pass
            draw_human_buy_guidance(game)
            return True

        _play_sound(gui, "ERROR")
        return True

    target = _find_clicked_candidate_intersection(state.get("candidates", []), pos)
    if target is None:
        _play_sound(gui, "ERROR")
        return True

    if target not in legal_human_intersection_candidates(game, player, action):
        _play_sound(gui, "ERROR")
        _emit(game, player, f"DBG: human {_short_action(action)} @{target} no longer legal; selector refreshed.")
        state["candidates"] = legal_human_intersection_candidates(game, player, action)
        draw_human_buy_guidance(game)
        return True

    _play_sound(gui, "BUTTON")
    state["selected_target"] = int(target)
    draw_human_buy_guidance(game)
    return True


def legal_human_intersection_candidates(game: Any, player: Any, action: str) -> List[int]:
    """Return legal city/settlement targets from scanner output with safe fallback."""
    targets: List[int] = []
    seen = set()

    for target in _scanner_intersection_candidates(game, action):
        if target is not None and target not in seen:
            seen.add(target)
            targets.append(target)

    if not targets:
        for target in _execution_choice_intersection_candidates(game, action):
            if target is not None and target not in seen:
                seen.add(target)
                targets.append(target)

    if not targets:
        for target in _fallback_intersection_candidates(game, player, action):
            if target is not None and target not in seen:
                seen.add(target)
                targets.append(target)

    legal = [target for target in targets if _intersection_action_is_legal(game, player, action, target)]
    return sorted(legal)


def _open_intersection_guidance(game: Any, action: str, mode: str) -> bool:
    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None:
        return False

    try:
        if str(getattr(game, "phase", "")) == "Execution" and str(getattr(game, "state", "")) == "ActionSelection":
            refresh = getattr(game, "refresh_viable_actions", None)
            if callable(refresh):
                refresh(f"human_{_reason_token(action)}_open")
    except Exception:
        pass

    candidates = legal_human_intersection_candidates(game, player, action)
    if not candidates:
        _emit(game, player, f"DBG: human {_short_action(action)} opened, but scanner found no legal candidates.")
        return False

    state = _state(game)
    state.update({
        "active": True,
        "action": action,
        "candidates": list(candidates),
        "selected_target": None,
    })
    _clear_buy_modes(gui)
    _set_mode(gui, mode, True)
    draw_human_buy_guidance(game)
    return True


def _scanner_intersection_candidates(game: Any, action: str) -> List[int]:
    scan = getattr(game, "current_viable_action_scan", None)
    candidates = None
    if isinstance(scan, Mapping):
        candidates = scan.get("candidates")
    else:
        candidates = getattr(scan, "candidates", None)
    if not isinstance(candidates, Mapping):
        return []
    keys = _candidate_keys(action)
    out: List[int] = []
    for key in keys:
        for item in list(candidates.get(key, []) or []):
            target = _target_from_candidate(item)
            if target is not None:
                out.append(target)
    return out


def _execution_choice_intersection_candidates(game: Any, action: str) -> List[int]:
    out: List[int] = []
    for row in list(getattr(game, "current_execution_choices", []) or []):
        if not isinstance(row, Mapping) or str(row.get("action", "") or "") != action:
            continue
        for item in list(row.get("candidates", []) or []):
            target = _target_from_candidate(item)
            if target is not None:
                out.append(target)
        target = _target_from_candidate(row.get("candidate"))
        if target is not None:
            out.append(target)
    return out


def _fallback_intersection_candidates(game: Any, player: Any, action: str) -> List[int]:
    if action == BUILD_CITY:
        return [_safe_int(x) for x in list(getattr(player, "settlements", []) or []) if _safe_int_or_none(x) is not None]

    if action == BUILD_SETTLEMENT:
        out: List[int] = []
        # First use outlook's reachable next settlement spots if available.
        outlook = getattr(player, "outlook", None)
        for key in ("next_settlement_spots", "next_settlements", "next_settlement_targets"):
            values = getattr(outlook, key, None)
            if isinstance(values, Mapping):
                values = values.keys()
            for raw in list(values or []):
                target = _target_from_candidate(raw)
                if target is None:
                    target = _safe_int_or_none(raw)
                if target is not None:
                    out.append(target)
        # Conservative board fallback: test every intersection.
        if not out:
            for index, _inter in enumerate(list(getattr(getattr(game, "board", None), "intersections", []) or [])):
                out.append(int(index))
        return out

    return []


def _intersection_action_is_legal(game: Any, player: Any, action: str, target: int) -> bool:
    if player is None or target is None:
        return False
    if str(getattr(game, "phase", "")) != "Execution":
        return False
    if str(getattr(game, "state", "")) != "ActionSelection":
        return False
    cost_method = getattr(game, "_execution_cost_vector_for_action", None)
    can_pay = getattr(game, "_can_player_pay_execution_cost", None)
    try:
        cost = cost_method(action) if callable(cost_method) else []
        if callable(can_pay) and not bool(can_pay(player, cost)):
            return False
    except Exception:
        return False

    if action == BUILD_CITY:
        try:
            if int(target) not in [int(x) for x in list(getattr(player, "settlements", []) or [])]:
                return False
            inter = game.board.intersections[int(target)]
            if inter is None:
                return False
            if str(getattr(inter, "color", "")) not in {"", str(getattr(player, "color", ""))}:
                return False
            return True
        except Exception:
            return False

    if action == BUILD_SETTLEMENT:
        try:
            method = getattr(game, "can_build_intersection_tf", None)
            if callable(method):
                return bool(method(int(target), player))
        except Exception:
            return False

    return False


def _dcard_is_legal_now(game: Any, player: Any) -> bool:
    if str(getattr(game, "phase", "")) != "Execution":
        return False
    if str(getattr(game, "state", "")) != "ActionSelection":
        return False
    try:
        if not list(getattr(game, "dcards_stack", []) or []):
            return False
        cost = game._execution_cost_vector_for_action(BUY_DCARD)
        return bool(game._can_player_pay_execution_cost(player, cost))
    except Exception:
        return False


def _execute_intersection_action(game: Any, action: str, target: int) -> Mapping[str, Any]:
    if action == BUILD_CITY:
        method = getattr(game, "execute_human_build_city_action", None)
        if callable(method):
            return method(int(target))
        return {"ok": False, "reason": "missing_execute_human_build_city_action", "target_id": int(target)}
    if action == BUILD_SETTLEMENT:
        method = getattr(game, "execute_human_build_settlement_action", None)
        if callable(method):
            return method(int(target))
        return {"ok": False, "reason": "missing_execute_human_build_settlement_action", "target_id": int(target)}
    return {"ok": False, "reason": "unsupported_intersection_action", "target_id": int(target)}


def _execute_dcard(game: Any) -> Mapping[str, Any]:
    method = getattr(game, "execute_human_buy_dcard_action", None)
    if callable(method):
        return method()
    return {"ok": False, "reason": "missing_execute_human_buy_dcard_action"}


def _strategy_already_refreshed_after_action(game: Any) -> bool:
    """True when Game executor already ran Slice D / strategy for this action."""
    try:
        slice_d = getattr(game, "last_slice_d_result", None)
        if isinstance(slice_d, Mapping) and slice_d.get("ok") is True:
            return True
    except Exception:
        pass
    try:
        last = getattr(game, "last_execution_result", None)
        if isinstance(last, Mapping):
            sd = last.get("slice_d")
            if isinstance(sd, Mapping) and sd.get("ok") is True:
                return True
    except Exception:
        pass
    return False


def _refresh_after_buy(game: Any, reason: str) -> None:
    """Rescan + GUI; strategy only if Game did not already Slice-D (P1 WP3: no force L2)."""
    try:
        if not _strategy_already_refreshed_after_action(game):
            ref = getattr(game, "refresh_strategy_after_event", None)
            if callable(ref):
                # kind=auto → classify_refresh_kind from reason (hand buy vs build milestone)
                ref(str(reason), kind="auto")
            else:
                refresh_strategy = getattr(game, "refresh_strategy_context", None)
                if callable(refresh_strategy):
                    refresh_strategy(str(reason), mode="auto")
    except Exception:
        pass
    try:
        refresh = getattr(game, "refresh_viable_actions", None)
        if callable(refresh):
            refresh(str(reason))
    except Exception:
        pass
    try:
        gui = getattr(game, "gui", None)
        if gui is not None:
            gui.draw_board_base(game.board)
            gui.draw_all_permanent_buildings(game.board)
            gui.update_scoreboard(game)
            pygame.display.update()
    except Exception:
        pass



def _animation_kind_for_action(action: str) -> str:
    """Return the queue kind expected by GUI._animate_elements().

    The animation loop recognizes board-object kinds such as ``settlement`` and
    ``city``.  Earlier versions queued the generic kind ``intersection`` for
    both City and Settlement guidance.  That could draw a static circle once,
    but it was not treated as a normal animated board object afterwards.
    """
    if action == BUILD_CITY:
        return "city"
    if action == BUILD_SETTLEMENT:
        return "settlement"
    return "intersection"

def _candidate_keys(action: str) -> Tuple[str, ...]:
    if action == BUILD_CITY:
        return (BUILD_CITY, "BUILD_CITY", "build_city", "city")
    if action == BUILD_SETTLEMENT:
        return (BUILD_SETTLEMENT, "BUILD_SETTLEMENT", "build_settlement", "settlement")
    return (action,)


def _target_from_candidate(value: Any) -> Optional[int]:
    if isinstance(value, Mapping):
        for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
            if key in value:
                return _safe_int_or_none(value.get(key))
        return None
    return _safe_int_or_none(value)


def _find_clicked_candidate_intersection(candidates: Iterable[Any], pos: Tuple[int, int]) -> Optional[int]:
    px, py = int(pos[0]), int(pos[1])
    best: Optional[int] = None
    best_dist = 999999
    for raw in candidates:
        target = _safe_int_or_none(raw)
        if target is None:
            continue
        center = _intersection_center(target)
        if center is None:
            continue
        dx = px - int(center[0])
        dy = py - int(center[1])
        dist = dx * dx + dy * dy
        if dist <= INTERSECTION_CLICK_RADIUS * INTERSECTION_CLICK_RADIUS and dist < best_dist:
            best = target
            best_dist = dist
    return best


def _intersection_center(target: int) -> Optional[Tuple[int, int]]:
    try:
        pos = POSITIONS["intersections"][int(target)]
        return (int(pos[0]), int(pos[1]))
    except Exception:
        return None


def _confirmation_click(gui: Any, pos: Tuple[int, int]) -> Optional[str]:
    try:
        return gui.handle_confirmation_click(pos)
    except Exception:
        return None


def _draw_ok_icons(center: Tuple[int, int]) -> None:
    try:
        x, y = center
        WIN.blit(IMAGES["OKY"]["default"], (int(x) + 35, int(y) - 45))
        WIN.blit(IMAGES["NOK"]["default"], (int(x) + 35, int(y) + 10))
    except Exception:
        pass


def _set_mode(gui: Any, name: str, active: bool) -> None:
    try:
        setter = getattr(gui, "set_mode", None)
        if callable(setter):
            setter(name, bool(active), "gui_human_buy_guidance")
            return
    except Exception:
        pass
    try:
        modes = [str(x) for x in list(getattr(gui, "modes", []) or [])]
        if active and name not in modes:
            modes.append(name)
        if not active:
            modes = [x for x in modes if x != name]
        gui.modes = modes
    except Exception:
        pass


def _clear_buy_modes(gui: Any) -> None:
    for mode in BUY_GUIDANCE_MODES:
        _set_mode(gui, mode, False)


def _current_player(game: Any) -> Any:
    try:
        getter = getattr(game, "get_current_player", None)
        if callable(getter):
            return getter()
    except Exception:
        pass
    try:
        return game.players[int(getattr(game, "turn", 1)) - 1]
    except Exception:
        return None


def _short_action(action: str) -> str:
    if action == BUILD_CITY:
        return "City"
    if action == BUILD_SETTLEMENT:
        return "Settlement"
    if action == BUY_DCARD:
        return "DCard"
    return str(action or "action")


def _reason_token(action: str) -> str:
    return _short_action(action).lower().replace(" ", "_")


def _safe_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _play_sound(gui: Any, name: str) -> None:
    """Play guidance/button sounds with a direct SOUNDS fallback.

    Some GUI copies do not expose gui.play_sound().  Initial Placement plays the
    same BUTTON/ERROR assets directly, so mirror that behavior here.
    """
    try:
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


def _emit(game: Any, player: Any, message: str) -> None:
    try:
        emitter = getattr(game, "emit_twitter_event", None)
        if callable(emitter):
            emitter(getattr(player, "id", None), str(message))
            return
    except Exception:
        pass
    try:
        gui = getattr(game, "gui", None)
        if gui is not None and hasattr(gui, "add_tweet"):
            gui.add_tweet(getattr(player, "id", None), str(message), update=False)
    except Exception:
        pass
