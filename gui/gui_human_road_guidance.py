"""Human Execution-phase Buy Road guidance.

This module is intentionally UI-focused.  It reuses the shared
viable_action_scanner / execution-manager output for legal road candidates,
then lets the human player pick one road and confirm it with OKY / OKN.

Game owns the final mutation through game.execute_human_build_road_action().
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import COLORS, IMAGES, POSITIONS, WIN, SOUNDS

BUILD_ROAD = "Build road"
ROAD_GUIDANCE_MODE = "Show_available_roads"
ROAD_CLICK_RADIUS = 20
ROAD_HIGHLIGHT_DIAMETER = 18

RoadId = Tuple[int, int]


def _state(game: Any) -> Dict[str, Any]:
    gui = getattr(game, "gui", None)
    if gui is None:
        return {"active": False, "candidates": [], "selected_road": None, "free_tfr": False}
    state = getattr(gui, "human_buy_road_state", None)
    if not isinstance(state, dict):
        state = {"active": False, "candidates": [], "selected_road": None, "free_tfr": False}
        setattr(gui, "human_buy_road_state", state)
    state.setdefault("active", False)
    state.setdefault("candidates", [])
    state.setdefault("selected_road", None)
    state.setdefault("free_tfr", False)
    return state


def is_human_road_guidance_active(game: Any) -> bool:
    """Return True when the human Buy Road selector is open."""
    return bool(_state(game).get("active", False))


def open_human_road_guidance(game: Any, *, free_tfr: bool = False) -> bool:
    """Open the human road selector using shared scanner road candidates.

    ``free_tfr=True``: placement for Two Free Roads (no cost; may place 1–2).
    """
    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None:
        return False

    # Free TFR: pieces must remain
    if free_tfr:
        try:
            remaining = int(game.player_roads_remaining(player)) if hasattr(game, "player_roads_remaining") else 1
        except Exception:
            remaining = 1
        if remaining <= 0:
            _emit(game, player, "DBG: free road open rejected — no road pieces left.")
            return False

    # Refresh the shared legality source once when the human explicitly opens the
    # selector.  From here on, the stored candidates are the visible options.
    try:
        if str(getattr(game, "phase", "")) == "Execution" and str(getattr(game, "state", "")) == "ActionSelection":
            refresh = getattr(game, "refresh_viable_actions", None)
            if callable(refresh):
                refresh("human_buy_road_open" if not free_tfr else "human_tfr_road_open")
    except Exception:
        pass

    candidates = legal_human_road_candidates(game, player)
    if not candidates:
        _emit(
            game,
            player,
            "DBG: human free road opened, but no legal road candidates."
            if free_tfr
            else "DBG: human Buy Road opened, but scanner found no legal road candidates.",
        )
        return False

    state = _state(game)
    state.update({
        "active": True,
        "candidates": [list(road) for road in candidates],
        "selected_road": None,
        "free_tfr": bool(free_tfr),
    })
    _set_mode(gui, ROAD_GUIDANCE_MODE, True)
    draw_human_road_guidance(game)
    return True


def close_human_road_guidance(game: Any, *, redraw: bool = True) -> None:
    """Close the road selector and clear its transient visuals."""
    gui = getattr(game, "gui", None)
    state = _state(game)
    state.update({"active": False, "candidates": [], "selected_road": None, "free_tfr": False})
    if gui is not None:
        _set_mode(gui, ROAD_GUIDANCE_MODE, False)
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


def draw_human_road_guidance(game: Any) -> None:
    """Draw candidate road pulses or selected-road OKY/OKN confirmation."""
    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None or not is_human_road_guidance_active(game):
        return

    state = _state(game)
    selected = _canonical_road(state.get("selected_road"))
    candidates = [_canonical_road(road) for road in list(state.get("candidates", []) or [])]
    candidates = [road for road in candidates if road is not None]

    try:
        color = COLORS.get(str(getattr(player, "color", "")).upper(), COLORS.get("GREEN", (0, 180, 0)))
    except Exception:
        color = (0, 180, 0)

    try:
        if hasattr(gui, "animate_queue_elements"):
            gui.animate_queue_elements.clear()
        # Build guidance uses the same animation queue as Initial Placement.
        # A preceding robber/steal clear may have disabled animations; reopen it
        # here so highlighted road options are visible.
        try:
            gui.animations_enabled = True
        except Exception:
            pass
        if selected is not None:
            center = _road_center(selected)
            if center is not None:
                gui.animate_queue_elements.append((center, color, ROAD_HIGHLIGHT_DIAMETER, "road"))
                if hasattr(gui, "human_guidance"):
                    gui.human_guidance.confirm_center = center
                if hasattr(gui, "draw_guidance_text"):
                    free = bool(state.get("free_tfr"))
                    prefix = "Confirm free road" if free else "Confirm road"
                    gui.draw_guidance_text(f"{prefix} {list(selected)}?", y_offset=25)
                _draw_ok_icons(gui, center)
        else:
            if hasattr(gui, "human_guidance"):
                gui.human_guidance.confirm_center = None
            for road in candidates:
                center = _road_center(road)
                if center is not None:
                    gui.animate_queue_elements.append((center, color, ROAD_HIGHLIGHT_DIAMETER, "road"))
            if hasattr(gui, "draw_guidance_text"):
                free = bool(state.get("free_tfr"))
                step = ""
                if free:
                    try:
                        pending = getattr(game, "pending_tfr_play", None) or {}
                        if isinstance(pending, Mapping) and pending.get("active"):
                            placed = int(pending.get("roads_placed", 0) or 0) + 1
                            total = int(pending.get("roads_total", 2) or 2)
                            step = f" ({placed} of {total})"
                    except Exception:
                        step = ""
                    gui.draw_guidance_text(f"Click a free road to place{step}", y_offset=25)
                else:
                    gui.draw_guidance_text("Click a highlighted road to build", y_offset=25)
        if hasattr(gui, "_animate_elements"):
            gui._animate_elements(getattr(game, "board", None))
        pygame.display.update()
    except Exception:
        pass


def handle_human_road_guidance_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle all clicks while the human road selector is open."""
    if not is_human_road_guidance_active(game):
        return False

    gui = getattr(game, "gui", None)
    player = _current_player(game)
    if gui is None or player is None:
        close_human_road_guidance(game)
        return True

    state = _state(game)
    selected = _canonical_road(state.get("selected_road"))

    if selected is not None:
        conf = None
        try:
            conf = gui.handle_confirmation_click(pos)
        except Exception:
            conf = None

        if conf == "OKY":
            free = bool(state.get("free_tfr"))
            result = _execute_selected_road(game, selected, free=free)
            if isinstance(result, Mapping) and bool(result.get("ok")):
                # The Game execution method already plays the successful BuildRoad
                # sound. Do not play a second generic BUTTON/infobleep here.
                need_another = bool(result.get("tfr_need_another_road"))
                close_human_road_guidance(game, redraw=False)
                # G3: clear "Confirm road …?" after OKY
                try:
                    gui.clear_guidance_text(y_offset=25)
                except Exception:
                    pass
                _refresh_after_build(game)
                if free and need_another:
                    # Second free road (or remaining free placements)
                    opened = open_human_road_guidance(game, free_tfr=True)
                    if not opened:
                        # No legal second road — end TFR early
                        try:
                            if hasattr(game, "_complete_tfr_play"):
                                game._complete_tfr_play(player, early=True)
                        except Exception:
                            pass
                        _emit(game, player, "Two Free Roads: no legal second road — ending early.")
                        _refresh_after_build(game)
            else:
                _play_sound(gui, "ERROR")
                reason = result.get("reason") if isinstance(result, Mapping) else "unknown_error"
                _emit(game, player, f"DBG: human Road {list(selected)} rejected; {reason}.")
                state["selected_road"] = None
                draw_human_road_guidance(game)
            return True

        if conf == "OKN":
            _play_sound(gui, "BUTTON")
            state["selected_road"] = None
            try:
                gui.clear_guidance_text(y_offset=25)
            except Exception:
                pass
            draw_human_road_guidance(game)
            return True

        _play_sound(gui, "ERROR")
        return True

    road = _find_clicked_candidate_road(state.get("candidates", []), pos)
    if road is None:
        _play_sound(gui, "ERROR")
        return True

    # Final UI safety check before showing OKY/OKN.  The execution method will
    # repeat this check before mutating the board.
    if not _road_is_legal_for_player(game, player, road):
        _play_sound(gui, "ERROR")
        _emit(game, player, f"DBG: human Road {list(road)} no longer legal; selector refreshed.")
        state["candidates"] = [list(r) for r in legal_human_road_candidates(game, player)]
        draw_human_road_guidance(game)
        return True

    _play_sound(gui, "BUTTON")
    state["selected_road"] = list(road)
    draw_human_road_guidance(game)
    return True


def legal_human_road_candidates(game: Any, player: Any) -> List[RoadId]:
    """Return legal road candidates from scanner output, with board safety filter."""
    roads: List[RoadId] = []
    seen = set()

    for road in _scanner_road_candidates(game):
        if road is not None and road not in seen:
            seen.add(road)
            roads.append(road)

    if not roads:
        for road in _execution_choice_road_candidates(game):
            if road is not None and road not in seen:
                seen.add(road)
                roads.append(road)

    if not roads:
        for road in _board_road_candidates(game):
            if road is not None and road not in seen:
                seen.add(road)
                roads.append(road)

    legal = [road for road in roads if _road_is_legal_for_player(game, player, road)]
    return sorted(legal)


def _execute_selected_road(game: Any, road: RoadId, *, free: bool = False) -> Mapping[str, Any]:
    method = getattr(game, "execute_human_build_road_action", None)
    if callable(method):
        try:
            return method(list(road), free=bool(free))
        except TypeError:
            return method(list(road))
    return {"ok": False, "reason": "missing_execute_human_build_road_action", "road_id": list(road)}


def _refresh_after_build(game: Any) -> None:
    try:
        refresh_strategy = getattr(game, "refresh_strategy_context", None)
        if callable(refresh_strategy):
            refresh_strategy("after_human_build_road", force=True)
    except Exception:
        pass
    try:
        refresh = getattr(game, "refresh_viable_actions", None)
        if callable(refresh):
            refresh("after_human_build_road")
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


def _scanner_road_candidates(game: Any) -> List[RoadId]:
    scan = getattr(game, "current_viable_action_scan", None)
    candidates = None
    if isinstance(scan, Mapping):
        candidates = scan.get("candidates")
    else:
        candidates = getattr(scan, "candidates", None)
    if not isinstance(candidates, Mapping):
        return []
    out: List[RoadId] = []
    for key in (BUILD_ROAD, "BUILD_ROAD", "build_road", "road"):
        for item in list(candidates.get(key, []) or []):
            road = _road_from_candidate(item)
            if road is not None:
                out.append(road)
    return out


def _execution_choice_road_candidates(game: Any) -> List[RoadId]:
    out: List[RoadId] = []
    for row in list(getattr(game, "current_execution_choices", []) or []):
        if not isinstance(row, Mapping) or str(row.get("action", "") or "") != BUILD_ROAD:
            continue
        for item in list(row.get("candidates", []) or []):
            road = _road_from_candidate(item)
            if road is not None:
                out.append(road)
        road = _road_from_candidate(row.get("candidate"))
        if road is not None:
            out.append(road)
    return out


def _board_road_candidates(game: Any) -> List[RoadId]:
    board = getattr(game, "board", None)
    out: List[RoadId] = []
    for road_obj in list(getattr(board, "roads", []) or []):
        road = _canonical_road(getattr(road_obj, "id", None))
        if road is not None:
            out.append(road)
    return out


def _road_from_candidate(value: Any) -> Optional[RoadId]:
    if isinstance(value, Mapping):
        for key in ("road_id", "road", "edge", "target_road"):
            if key in value:
                road = _canonical_road(value.get(key))
                if road is not None:
                    return road
        return None
    return _canonical_road(value)


def _canonical_road(value: Any) -> Optional[RoadId]:
    try:
        a, b = tuple(value)[:2]
        return tuple(sorted((int(a), int(b))))  # type: ignore[return-value]
    except Exception:
        return None


def _road_center(road: RoadId) -> Optional[Tuple[int, int]]:
    try:
        p1 = POSITIONS["intersections"][int(road[0])]
        p2 = POSITIONS["intersections"][int(road[1])]
        return ((int(p1[0]) + int(p2[0])) // 2, (int(p1[1]) + int(p2[1])) // 2)
    except Exception:
        return None


def _find_clicked_candidate_road(candidates: Iterable[Any], pos: Tuple[int, int]) -> Optional[RoadId]:
    px, py = int(pos[0]), int(pos[1])
    best: Optional[RoadId] = None
    best_dist = 999999
    for raw in candidates:
        road = _canonical_road(raw)
        if road is None:
            continue
        center = _road_center(road)
        if center is None:
            continue
        dx = px - int(center[0])
        dy = py - int(center[1])
        dist = dx * dx + dy * dy
        if dist <= ROAD_CLICK_RADIUS * ROAD_CLICK_RADIUS and dist < best_dist:
            best = road
            best_dist = dist
    return best


def _road_is_legal_for_player(game: Any, player: Any, road: RoadId) -> bool:
    board = getattr(game, "board", None)
    if board is None or player is None or road is None:
        return False
    try:
        if not bool(board.can_build_road_for_color_tf(list(road), str(getattr(player, "color", "")))):
            return False
    except Exception:
        return False
    return _road_touches_player_network_without_crossing_opponent(game, player, road)


def _road_touches_player_network_without_crossing_opponent(game: Any, player: Any, road: RoadId) -> bool:
    board = getattr(game, "board", None)
    player_color = str(getattr(player, "color", ""))
    player_structures = {int(x) for x in list(getattr(player, "settlements", []) or [])}
    player_structures.update(int(x) for x in list(getattr(player, "cities", []) or []))
    player_roads = [_canonical_road(r) for r in list(getattr(player, "roads", []) or [])]
    player_roads = [r for r in player_roads if r is not None]

    for endpoint in road:
        if int(endpoint) in player_structures:
            return True
        if _endpoint_has_opponent_structure(board, int(endpoint), player_color):
            continue
        for owned in player_roads:
            if int(endpoint) in owned:
                return True
    return False


def _endpoint_has_opponent_structure(board: Any, intersection_id: int, player_color: str) -> bool:
    try:
        inter = board.intersections[int(intersection_id)]
    except Exception:
        return False
    if inter is None or not bool(getattr(inter, "occupied_tf", False)):
        return False
    return str(getattr(inter, "color", "")) != str(player_color)


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


def _set_mode(gui: Any, name: str, active: bool) -> None:
    try:
        setter = getattr(gui, "set_mode", None)
        if callable(setter):
            setter(name, bool(active), "gui_human_road_guidance")
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


def _draw_ok_icons(gui: Any, center: Tuple[int, int]) -> None:
    try:
        x, y = center
        WIN.blit(IMAGES["OKY"]["default"], (int(x) + 35, int(y) - 45))
        WIN.blit(IMAGES["NOK"]["default"], (int(x) + 35, int(y) + 10))
    except Exception:
        pass


def _play_sound(gui: Any, name: str) -> None:
    """Play guidance/button sounds with a direct SOUNDS fallback."""
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
