"""
Modular 7-roll / robber flow for Catan.

Starter scope:
- discard execution (AI + human panel hook);
- basic robber placement strategy;
- basic opponent-to-steal selection;
- optional random steal executor;
- no hypothetical simulation or long-term robber planning yet.

Copy this file to: core/game_7logic.py
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import random
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROBBER_MOVE_STATES = {"MoveRobber", "RobberMoveRequired", "SetRobber"}
STEAL_SELECT_STATE = "StealSelectOpponent"
STEAL_PICK_STATE = "StealPickRCard"
ACTION_SELECTION_STATE = "ActionSelection"

RESOURCE_NAMES = ("Wheat", "Ore", "Wood", "Brick", "Sheep")


@dataclass
class SevenRollResult:
    """Runtime summary of what happened after a 7 was rolled."""

    ok: bool
    player_id: Optional[int]
    dice_total: int = 7
    state_after: str = "MoveRobber"
    discard_required: bool = False
    players_to_discard: Optional[List[Dict[str, Any]]] = None
    robber_tile_before: Optional[int] = None
    legal_robber_tile_ids: Optional[List[int]] = None
    forced_action: str = "Move robber"
    warnings: Optional[List[str]] = None

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["players_to_discard"] = data.get("players_to_discard") or []
        data["legal_robber_tile_ids"] = data.get("legal_robber_tile_ids") or []
        data["warnings"] = data.get("warnings") or []
        return data


@dataclass
class RobberPlan:
    """Chosen robber placement and optional victim."""

    ok: bool
    player_id: Optional[int]
    tile_id: Optional[int]
    opponent_id: Optional[int]
    score: float
    reason: str
    corner_list: List[int]
    selected_opponent: Optional[Dict[str, Any]]
    candidate_tiles: List[Dict[str, Any]]
    needed_resource_weights: Dict[str, float]
    warnings: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RobberMoveResult:
    """Runtime summary after the robber is moved to a tile."""

    ok: bool
    player_id: Optional[int]
    tile_id: Optional[int]
    tile_id_before: Optional[int]
    state_after: str
    selected_opponent_id: Optional[int]
    stealable_opponents: List[Dict[str, Any]]
    plan: Optional[Dict[str, Any]]
    warnings: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RobberStealResult:
    """Runtime summary after one random resource is stolen."""

    ok: bool
    player_id: Optional[int]
    opponent_id: Optional[int]
    stolen_resource: Optional[str]
    state_after: str
    warnings: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# Lightweight GUI event feed hooks
# ──────────────────────────────────────────────────────────────────────────────


def _emit_twitter(game: Any, player_id: Optional[int], message: str) -> None:
    """Send one v045-inspired event-feed message to the GUI if available.

    The GUI side keeps the top-right pane. This function keeps game_7logic
    independent: no pygame import, no direct drawing, and no failure if the
    GUI is absent in tests/no-GUI runs.
    """
    gui = getattr(game, "gui", None)
    if gui is None:
        return

    try:
        if hasattr(gui, "add_tweet"):
            gui.add_tweet(player_id, message)
        else:
            if not hasattr(gui, "twitter") or not isinstance(getattr(gui, "twitter", None), list):
                gui.twitter = []
            gui.twitter.append([player_id, message])
            if hasattr(gui, "update_twitter"):
                gui.update_twitter()
    except Exception:
        # The event feed is visual/logging only; never break game logic.
        pass


def _safe_gui_call(game: Any, method_name: str, *args, **kwargs) -> None:
    """Best-effort GUI feedback hook; visuals must never break game logic."""
    gui = getattr(game, "gui", None)
    if gui is None:
        return
    try:
        method = getattr(gui, method_name, None)
        if callable(method):
            method(*args, **kwargs)
    except Exception:
        pass


def _show_robber_tile_visual(game: Any, tile_id: Optional[int]) -> None:
    """Show robber.png plus the v045-style white radius-60 tile animation."""
    if tile_id is None:
        return
    _safe_gui_call(game, "show_tile_having_robber", getattr(game, "board", None), int(tile_id), "Y")


def _show_steal_victim_visual(game: Any, intersection_ids: Any) -> None:
    """Show red radius-20 rings on the victim's adjacent settlement/city intersections."""
    if not intersection_ids:
        return
    _safe_gui_call(game, "show_victim_of_steal", getattr(game, "board", None), intersection_ids)


def _show_available_robber_tiles_visual(game: Any, tile_ids: Any) -> None:
    """Show player-colored legal robber-tile choices for a human player."""
    if not tile_ids:
        return
    _safe_gui_call(game, "show_available_robber_tiles", getattr(game, "board", None), tile_ids)


def _show_available_steal_targets_visual(game: Any, opponents: Any) -> None:
    """Show player-colored steal-target choices for a human player."""
    if not opponents:
        return
    _safe_gui_call(game, "show_available_steal_opponents", getattr(game, "board", None), opponents)


def _is_human_player(player: Any) -> bool:
    """Robustly detect whether the current player should use manual robber choices."""
    try:
        return bool(getattr(player, "is_human", False))
    except Exception:
        return False


def _selected_victim_intersections(game: Any, opponent_id: Optional[int] = None) -> List[int]:
    """Return adjacent intersection IDs for the selected/passed robber-steal victim."""
    pending = getattr(game, "pending_robber_steal", {}) or {}
    if opponent_id is None:
        opponent_id = _safe_int(pending.get("selected_opponent_id"))
    if opponent_id is None:
        return []

    for row in list(pending.get("stealable_opponents", []) or []):
        try:
            if _safe_int(row.get("opponent_id")) == int(opponent_id):
                return [int(x) for x in list(row.get("adjacent_intersections", []) or [])]
        except Exception:
            continue

    plan = pending.get("plan") or {}
    selected = plan.get("selected_opponent") if isinstance(plan, Mapping) else None
    if isinstance(selected, Mapping) and _safe_int(selected.get("opponent_id")) == int(opponent_id):
        try:
            return [int(x) for x in list(selected.get("adjacent_intersections", []) or [])]
        except Exception:
            return []
    return []


def _record_turn_event(
    game: Any,
    *,
    player: Any = None,
    player_id: Optional[int] = None,
    event_type: str,
    category: Optional[str] = None,
    target_player_id: Optional[int] = None,
    resource_delta: Optional[Mapping[Any, Any]] = None,
    public: bool = True,
    source: str = "game_7logic",
    reason: str = "",
    message: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> None:
    """Record a structured event when Game exposes the event-ledger API."""
    try:
        if hasattr(game, "record_turn_event"):
            game.record_turn_event(
                player=player,
                player_id=player_id,
                event_type=event_type,
                category=category,
                target_player_id=target_player_id,
                resource_delta=dict(resource_delta or {}),
                public=public,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata or {}),
            )
    except Exception:
        pass


def _record_turn_delta(
    game: Any,
    player: Any,
    category: str,
    resource_name: str,
    amount: int,
    *,
    event_type: Optional[str] = None,
    target_player_id: Optional[int] = None,
    source: str = "game_7logic",
    reason: str = "",
    message: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> None:
    """Record a resource delta, falling back to legacy player vectors."""
    try:
        if hasattr(game, "record_turn_delta"):
            game.record_turn_delta(
                player,
                category,
                resource_delta={resource_name: int(amount)},
                event_type=event_type or category,
                target_player_id=target_player_id,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata or {}),
            )
            return
    except Exception:
        pass

    try:
        attr = {
            "steal": "turn_details_steal",
            "discard": "turn_details_discard",
            "buy": "turn_details_buy",
            "TwP": "turn_details_TwP",
            "TwB": "turn_details_TwB",
            "dcard": "turn_details_dcard",
            "resource_production": "turn_details_resource_production",
            "resource_production_robber": "turn_details_resource_production_robber",
        }.get(category, category)
        _add_turn_detail_delta(player, attr, resource_name, amount)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Public API called by Game
# ──────────────────────────────────────────────────────────────────────────────


def handle_roll_seven_no_discard(game: Any, player: Any) -> Dict[str, Any]:
    """
    Start the 7-roll flow, but do not execute discard yet.

    Mutations:
    - records players who would need to discard later;
    - sets game.state to MoveRobber;
    - sets myturn.validate_function_set_robber_by_HP=True so scanner forces robber;
    - clears normal action state until robber flow is resolved.
    """
    warnings: List[str] = []
    player_id = _safe_player_id(player)

    robber_before = current_robber_tile_id(game)
    legal_tiles = legal_robber_tile_ids(game)
    players_to_discard = players_requiring_discard(game)
    discard_required = bool(players_to_discard)

    try:
        game.pending_seven_roll = {
            "active": True,
            "player_id": player_id,
            "discard_required_later": discard_required,
            "players_to_discard": players_to_discard,
            "robber_tile_before": robber_before,
            "legal_robber_tile_ids": legal_tiles,
        }
        game.last_7_result = dict(game.pending_seven_roll)
        game.pending_discard_queue = list(players_to_discard)
    except Exception as exc:
        warnings.append(f"Could not store pending_seven_roll: {exc}")

    try:
        game.myturn.players_having_too_many_rcards = _players_to_discard_flag_vector(players_to_discard)
    except Exception as exc:
        warnings.append(f"Could not update myturn discard flags: {exc}")

    robber_before_label = "?" if robber_before is None else str(robber_before)
    seven_message = f"rolled 7 - removed robber from tile {robber_before_label}"
    _emit_twitter(game, player_id, seven_message)
    _record_turn_event(
        game,
        player=player,
        event_type="seven_roll",
        source="dice_roll",
        message=seven_message,
        metadata={"robber_tile_before": robber_before, "discard_required": discard_required, "legal_robber_tile_ids": legal_tiles},
    )

    state_after = "MoveRobber"
    forced_action = "Move robber"
    if discard_required:
        _emit_twitter(game, player_id, "discard required before robber")
        _record_turn_event(
            game,
            player=player,
            event_type="discard_check",
            source="dice_roll",
            message="discard required before robber",
            metadata={"players_to_discard": players_to_discard},
        )
        disc = process_discard_queue(game, open_human_panel=True)
        if not disc.get("robber_ready"):
            state_after = DISCARD_PENDING_STATE
            forced_action = "Discard cards"
            try:
                game.state = DISCARD_PENDING_STATE
                game.state_1 = DISCARD_PENDING_STATE
                game.state_2 = ""
                game.myturn.validate_function_set_robber_by_HP = False
            except Exception as exc:
                warnings.append(f"Could not set DiscardPending: {exc}")
        else:
            _begin_robber_after_discards(game)
            state_after = "MoveRobber"
            # visuals for robber after discards
            _show_robber_tile_visual(game, robber_before)
            if _is_human_player(player):
                _show_available_robber_tiles_visual(game, legal_tiles)
    else:
        try:
            game.state = "MoveRobber"
            game.state_1 = "MoveRobber"
            game.state_2 = ""
            game.myturn.validate_function_discard_rcards_by_HP = False
            game.myturn.validate_function_set_robber_by_HP = True
        except Exception as exc:
            warnings.append(f"Could not set robber state: {exc}")
        _show_robber_tile_visual(game, robber_before)
        if _is_human_player(player):
            _show_available_robber_tiles_visual(game, legal_tiles)

    return SevenRollResult(
        ok=True,
        player_id=player_id,
        dice_total=7,
        state_after=state_after,
        discard_required=discard_required,
        players_to_discard=players_to_discard,
        robber_tile_before=robber_before,
        legal_robber_tile_ids=legal_tiles,
        forced_action=forced_action,
        warnings=warnings,
    ).as_dict()


def plan_basic_robber_action(
    game: Any,
    player: Any,
    *,
    preferred_opponent_id: Optional[int] = None,
    avoid_self_block: bool = True,
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    Pick a basic robber tile and optional steal opponent.

    Current starter strategy:
    1. Do not place on the current robber tile.
    2. Avoid blocking our own buildings, unless no useful non-self tile exists.
    3. Prefer high-probability tiles with opponent settlements/cities.
    4. Prefer stealing from opponents who hold cards useful to current strategic_direction.
    5. Tie-break toward more resources, more VP, and the previous player in turn order.
    """
    warnings: List[str] = []
    player_id = _safe_player_id(player)
    needed_weights = needed_resource_weights_from_strategy(player)

    candidates = score_robber_tiles(
        game,
        player,
        preferred_opponent_id=preferred_opponent_id,
        avoid_self_block=avoid_self_block,
        needed_resource_weights=needed_weights,
    )

    if not candidates and avoid_self_block:
        warnings.append("No non-self-blocking robber tile found; allowing self-block fallback.")
        candidates = score_robber_tiles(
            game,
            player,
            preferred_opponent_id=preferred_opponent_id,
            avoid_self_block=False,
            needed_resource_weights=needed_weights,
        )

    if not candidates:
        return RobberPlan(
            ok=False,
            player_id=player_id,
            tile_id=None,
            opponent_id=None,
            score=0.0,
            reason="No legal robber tile found.",
            corner_list=[],
            selected_opponent=None,
            candidate_tiles=[],
            needed_resource_weights=needed_weights,
            warnings=warnings,
        ).as_dict()

    candidates = sorted(candidates, key=lambda row: row.get("score", 0.0), reverse=True)
    best = candidates[0]
    tile_id = _safe_int(best.get("tile_id"))
    selected = best.get("selected_opponent") or None
    opponent_id = _safe_int(selected.get("opponent_id")) if isinstance(selected, dict) else None
    corner_list = list(selected.get("adjacent_intersections", []) if isinstance(selected, dict) else [])

    return RobberPlan(
        ok=True,
        player_id=player_id,
        tile_id=tile_id,
        opponent_id=opponent_id,
        score=float(best.get("score", 0.0) or 0.0),
        reason=str(best.get("reason", "Basic robber tile score.")),
        corner_list=corner_list,
        selected_opponent=selected,
        candidate_tiles=candidates[: max(1, int(top_k or 5))],
        needed_resource_weights=needed_weights,
        warnings=warnings,
    ).as_dict()


def execute_basic_robber_strategy(
    game: Any,
    player: Any,
    *,
    preferred_opponent_id: Optional[int] = None,
    execute_steal: bool = False,
) -> Dict[str, Any]:
    """
    Plan and execute a basic robber move.

    By default this only moves the robber and preselects an opponent.
    Set execute_steal=True to also steal one random resource immediately.
    """
    plan = plan_basic_robber_action(
        game,
        player,
        preferred_opponent_id=preferred_opponent_id,
    )
    if not plan.get("ok"):
        return {"ok": False, "plan": plan, "move": None, "steal": None}

    move = move_robber_basic(
        game,
        player,
        int(plan["tile_id"]),
        opponent_id=plan.get("opponent_id"),
        plan=plan,
    )

    steal = None
    if execute_steal and move.get("ok") and move.get("selected_opponent_id"):
        steal = steal_random_resource_basic(
            game,
            player,
            int(move["selected_opponent_id"]),
        )

    return {"ok": bool(move.get("ok")), "plan": plan, "move": move, "steal": steal}


def move_robber_basic(
    game: Any,
    player: Any,
    tile_id: int,
    *,
    opponent_id: Optional[int] = None,
    plan: Optional[Mapping[str, Any]] = None,
    auto_select_single: bool = True,
    auto_select_multiple: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Move the robber to tile_id and enter steal-selection/pick state if possible.

    This is intentionally basic:
    - no discard;
    - optional preselected opponent;
    - no automatic random steal unless caller invokes steal_random_resource_basic();
    - human players only auto-select when there is exactly one target.
    """
    warnings: List[str] = []
    player_id = _safe_player_id(player)
    is_human = _is_human_player(player)
    if auto_select_multiple is None:
        auto_select_multiple = not is_human
    before = current_robber_tile_id(game)

    tile = _tile_by_id(getattr(game, "board", None), tile_id)
    if tile is None:
        return RobberMoveResult(
            ok=False,
            player_id=player_id,
            tile_id=tile_id,
            tile_id_before=before,
            state_after=str(getattr(game, "state", "")),
            selected_opponent_id=None,
            stealable_opponents=[],
            plan=dict(plan or {}),
            warnings=[f"Tile {tile_id} does not exist."],
        ).as_dict()

    tile_type = str(getattr(tile, "type", ""))
    if tile_type in {"Sea", "Desert", "Blank", ""}:
        return RobberMoveResult(
            ok=False,
            player_id=player_id,
            tile_id=tile_id,
            tile_id_before=before,
            state_after=str(getattr(game, "state", "")),
            selected_opponent_id=None,
            stealable_opponents=[],
            plan=dict(plan or {}),
            warnings=[f"Robber cannot move to tile {tile_id} of type {tile_type!r}."],
        ).as_dict()

    if before == int(tile_id):
        return RobberMoveResult(
            ok=False,
            player_id=player_id,
            tile_id=tile_id,
            tile_id_before=before,
            state_after=str(getattr(game, "state", "")),
            selected_opponent_id=None,
            stealable_opponents=[],
            plan=dict(plan or {}),
            warnings=["Robber must move to a different tile."],
        ).as_dict()

    board = getattr(game, "board", None)
    for t in list(getattr(board, "tiles", []) or []):
        if t is not None:
            try:
                t.occupied_tf = False
            except Exception:
                pass

    tile.occupied_tf = True

    try:
        game.previous_tile_having_robber = [int(tile_id), getattr(game, "round", 0), getattr(game, "turn", 0)]
    except Exception:
        pass

    try:
        if not isinstance(game.list_of_tiles_having_robber, list):
            game.list_of_tiles_having_robber = []
        game.list_of_tiles_having_robber.append(
            {
                "round": getattr(game, "round", None),
                "turn": getattr(game, "turn", None),
                "player_id": player_id,
                "from_tile_id": before,
                "to_tile_id": int(tile_id),
                "selected_opponent_id": opponent_id,
            }
        )
    except Exception:
        pass

    opponents = stealable_opponents_adjacent_to_tile(game, player, int(tile_id))
    selected_opponent = None

    if opponent_id is not None:
        for row in opponents:
            if _safe_int(row.get("opponent_id")) == int(opponent_id):
                selected_opponent = row
                break
        if selected_opponent is None:
            warnings.append(f"Opponent {opponent_id} is not stealable from tile {tile_id}; choosing fallback.")

    if selected_opponent is None and opponents:
        if len(opponents) == 1 and auto_select_single:
            selected_opponent = opponents[0]
        elif len(opponents) > 1 and bool(auto_select_multiple):
            selected_opponent = choose_basic_steal_opponent(game, player, int(tile_id), candidates=opponents)
        else:
            # v045 human look & feel: when multiple victims touch the new robber
            # tile, show the candidate intersections and wait for a human click.
            selected_opponent = None

    selected_opponent_id = _safe_int(selected_opponent.get("opponent_id")) if selected_opponent else None

    try:
        game.pending_robber_steal = {
            "active": bool(opponents),
            "player_id": player_id,
            "tile_id": int(tile_id),
            "stealable_opponents": opponents,
            "selected_opponent_id": selected_opponent_id,
            "awaiting_human_target": bool(opponents and selected_opponent_id is None),
            "plan": dict(plan or {}),
        }
    except Exception:
        pass

    try:
        game.myturn.validate_function_set_robber_by_HP = False
    except Exception:
        pass

    if selected_opponent_id is not None:
        state_after = STEAL_PICK_STATE
    elif opponents:
        state_after = STEAL_SELECT_STATE
    else:
        state_after = ACTION_SELECTION_STATE
        try:
            if isinstance(getattr(game, "pending_seven_roll", None), dict):
                game.pending_seven_roll["active"] = False
        except Exception:
            pass

    try:
        game.state = state_after
        game.state_1 = state_after if state_after != ACTION_SELECTION_STATE else ""
        game.state_2 = ""
    except Exception as exc:
        warnings.append(f"Could not set post-robber state: {exc}")

    # v045-inspired robber visual feedback: robber.png + white radius-60 tile ring.
    _show_robber_tile_visual(game, int(tile_id))

    # If a victim is already selected, articulate which settlement/city is robbed.
    # If not, keep the v045 human-choice look: player-colored candidate TWs.
    if selected_opponent_id is not None:
        _show_steal_victim_visual(game, _selected_victim_intersections(game, selected_opponent_id))
    elif opponents:
        _show_available_steal_targets_visual(game, opponents)

    move_message = f"moved robber to tile {int(tile_id)}"
    _emit_twitter(game, player_id, move_message)
    try:
        from core import mglog

        mglog.log_set_robber(
            game,
            player,
            int(tile_id),
            from_tile_id=before,
        )
    except Exception:
        pass
    _record_turn_event(
        game,
        player=player,
        event_type="robber_move",
        source="robber",
        message=move_message,
        metadata={
            "from_tile_id": before,
            "to_tile_id": int(tile_id),
            "selected_opponent_id": selected_opponent_id,
            "stealable_opponents": opponents,
        },
    )
    if selected_opponent_id is not None:
        target_message = f"targets P{selected_opponent_id} for steal"
        _emit_twitter(game, player_id, target_message)
        _record_turn_event(
            game,
            player=player,
            event_type="robber_target_selected",
            target_player_id=selected_opponent_id,
            source="robber",
            message=target_message,
            metadata={"tile_id": int(tile_id)},
        )
    elif opponents:
        choose_message = "must choose steal target"
        _emit_twitter(game, player_id, choose_message)
        _record_turn_event(
            game,
            player=player,
            event_type="robber_target_required",
            source="robber",
            message=choose_message,
            metadata={"tile_id": int(tile_id), "stealable_opponents": opponents},
        )

    return RobberMoveResult(
        ok=True,
        player_id=player_id,
        tile_id=int(tile_id),
        tile_id_before=before,
        state_after=state_after,
        selected_opponent_id=selected_opponent_id,
        stealable_opponents=opponents,
        plan=dict(plan or {}),
        warnings=warnings,
    ).as_dict()


def select_robber_steal_opponent_basic(game: Any, player: Any, opponent_id: int) -> Dict[str, Any]:
    """Select the opponent to steal from after the robber has already moved."""
    pending = getattr(game, "pending_robber_steal", {}) or {}
    tile_id = _safe_int(pending.get("tile_id"))
    if tile_id is None:
        return {"ok": False, "warnings": ["No pending robber-steal tile."], "state_after": str(getattr(game, "state", ""))}

    opponents = pending.get("stealable_opponents") or stealable_opponents_adjacent_to_tile(game, player, tile_id)
    selected = None
    for row in opponents:
        if _safe_int(row.get("opponent_id")) == int(opponent_id):
            selected = row
            break

    if selected is None:
        return {
            "ok": False,
            "warnings": [f"Opponent {opponent_id} is not stealable from tile {tile_id}."],
            "tile_id": tile_id,
            "state_after": str(getattr(game, "state", "")),
        }

    pending["selected_opponent_id"] = int(opponent_id)
    pending["awaiting_human_target"] = False
    pending["active"] = True
    game.pending_robber_steal = pending

    try:
        game.state = STEAL_PICK_STATE
        game.state_1 = STEAL_PICK_STATE
        game.state_2 = ""
    except Exception:
        pass

    # v045-inspired victim visual: red radius-20 rings on the robbed player's intersections.
    _show_steal_victim_visual(game, list(selected.get("adjacent_intersections", []) or []))

    select_message = f"selects P{int(opponent_id)} to steal from"
    _emit_twitter(game, _safe_player_id(player), select_message)
    _record_turn_event(
        game,
        player=player,
        event_type="robber_target_selected",
        target_player_id=int(opponent_id),
        source="robber",
        message=select_message,
        metadata={"tile_id": tile_id},
    )

    return {
        "ok": True,
        "tile_id": tile_id,
        "selected_opponent_id": int(opponent_id),
        "selected_opponent": selected,
        "state_after": STEAL_PICK_STATE,
        "warnings": [],
    }


def steal_random_resource_basic(game: Any, player: Any, opponent_id: Optional[int] = None) -> Dict[str, Any]:
    """Steal one random resource card from the selected opponent."""
    warnings: List[str] = []
    player_id = _safe_player_id(player)

    pending = getattr(game, "pending_robber_steal", {}) or {}
    if opponent_id is None:
        opponent_id = _safe_int(pending.get("selected_opponent_id"))

    if opponent_id is None:
        return RobberStealResult(False, player_id, None, None, str(getattr(game, "state", "")), ["No opponent selected."]).as_dict()

    opponent = _player_by_id(game, int(opponent_id))
    if opponent is None:
        return RobberStealResult(False, player_id, int(opponent_id), None, str(getattr(game, "state", "")), ["Opponent not found."]).as_dict()

    bag: List[Any] = []
    rcards = getattr(opponent, "rcards", {}) or {}
    if isinstance(rcards, Mapping):
        for rc, count in rcards.items():
            try:
                n = int(count or 0)
            except Exception:
                n = 0
            for _ in range(max(0, n)):
                bag.append(rc)

    if not bag:
        return RobberStealResult(False, player_id, int(opponent_id), None, str(getattr(game, "state", "")), ["Opponent has no resource cards."]).as_dict()

    stolen = random.choice(bag)
    stolen_name = _resource_name(stolen)

    try:
        opponent.rcards[stolen] = int(opponent.rcards.get(stolen, 0)) - 1
        player.rcards[stolen] = int(player.rcards.get(stolen, 0)) + 1
        opponent.number_of_rcards = _resource_count(opponent)
        player.number_of_rcards = _resource_count(player)
    except Exception as exc:
        return RobberStealResult(False, player_id, int(opponent_id), None, str(getattr(game, "state", "")), [f"Could not move resource card: {exc}"]).as_dict()

    try:
        _record_turn_delta(
            game,
            player,
            "steal",
            stolen_name,
            +1,
            event_type="steal",
            target_player_id=int(opponent_id),
            source="robber",
            reason="robber steal",
            metadata={"opponent_id": int(opponent_id)},
        )
        _record_turn_delta(
            game,
            opponent,
            "steal",
            stolen_name,
            -1,
            event_type="steal_loss",
            target_player_id=player_id,
            source="robber",
            reason="robber steal",
            metadata={"thief_id": player_id},
        )
    except Exception:
        pass

    try:
        if isinstance(getattr(game, "pending_robber_steal", None), dict):
            game.pending_robber_steal["active"] = False
        if isinstance(getattr(game, "pending_seven_roll", None), dict):
            game.pending_seven_roll["active"] = False
        game.state = ACTION_SELECTION_STATE
        game.state_1 = ""
        game.state_2 = ""
    except Exception as exc:
        warnings.append(f"Could not clear post-steal state: {exc}")

    try:
        game.update_strategy_dashboard(player)
        game.update_strategy_dashboard(opponent)
    except Exception:
        pass

    # Repeat/confirm the victim visual at the actual steal moment, especially for AI turns
    # where selecting and stealing can happen in the same action.
    _show_steal_victim_visual(game, _selected_victim_intersections(game, int(opponent_id)))

    try:
        from core import mglog

        mglog.log_steal(game, player, int(opponent_id), stolen_name)
    except Exception:
        pass

    # Events: full resource name only in CHECK_MODE; else "a card" (option A).
    try:
        from core.debug_mode import is_check_mode

        if is_check_mode():
            steal_message = f"steals {stolen_name} from P{int(opponent_id)}"
        else:
            steal_message = f"steals a card from P{int(opponent_id)}"
    except Exception:
        steal_message = f"steals {stolen_name} from P{int(opponent_id)}"
    _emit_twitter(game, player_id, steal_message)
    _record_turn_event(
        game,
        player=player,
        event_type="steal_completed",
        target_player_id=int(opponent_id),
        source="robber",
        message=steal_message,
        metadata={"stolen_resource": stolen_name},
    )

    return RobberStealResult(
        ok=True,
        player_id=player_id,
        opponent_id=int(opponent_id),
        stolen_resource=stolen_name,
        state_after=ACTION_SELECTION_STATE,
        warnings=warnings,
    ).as_dict()


def cancel_basic_robber_flow(game: Any) -> Dict[str, Any]:
    """Clear transient 7-flow flags and return to normal action selection."""
    try:
        game.state = ACTION_SELECTION_STATE
        game.state_1 = ""
        game.state_2 = ""
    except Exception:
        pass

    try:
        game.myturn.validate_function_set_robber_by_HP = False
        game.myturn.validate_function_discard_rcards_by_HP = False
    except Exception:
        pass

    try:
        if isinstance(getattr(game, "pending_seven_roll", None), dict):
            game.pending_seven_roll["active"] = False
        if isinstance(getattr(game, "pending_robber_steal", None), dict):
            game.pending_robber_steal["active"] = False
    except Exception:
        pass

    return {"ok": True, "state_after": ACTION_SELECTION_STATE}


# ──────────────────────────────────────────────────────────────────────────────
# Strategy / scoring helpers
# ──────────────────────────────────────────────────────────────────────────────


def score_robber_tiles(
    game: Any,
    player: Any,
    *,
    preferred_opponent_id: Optional[int] = None,
    avoid_self_block: bool = True,
    needed_resource_weights: Optional[Mapping[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Return legal robber tiles with simple impact scores."""
    current = current_robber_tile_id(game)
    board = getattr(game, "board", None)
    player_color = str(getattr(player, "color", ""))
    needed = dict(needed_resource_weights or needed_resource_weights_from_strategy(player))

    candidates: List[Dict[str, Any]] = []
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        tile_id = _safe_int(getattr(tile, "id", None))
        if tile_id is None or tile_id == current:
            continue
        tile_type = str(getattr(tile, "type", ""))
        tile_value = _safe_int(getattr(tile, "value", None)) or 0
        if tile_type in {"Sea", "Desert", "Blank", ""}:
            continue

        pips = _pips_from_tile_value(tile_value)
        buildings = _tile_buildings(game, tile)
        own_weight = sum(b["weight"] for b in buildings if b.get("color") == player_color)
        opponent_buildings = [b for b in buildings if b.get("color") not in {"", "Blank", player_color}]

        if avoid_self_block and own_weight > 0:
            continue
        if not opponent_buildings and own_weight <= 0:
            continue

        impact_score = 0.0
        player_ids_impacted: List[int] = []
        for b in opponent_buildings:
            opponent = _player_by_color(game, str(b.get("color", "")))
            opponent_id = _safe_player_id(opponent) if opponent is not None else None
            if opponent_id is not None and opponent_id not in player_ids_impacted:
                player_ids_impacted.append(opponent_id)
            vp = _victory_points(opponent) if opponent is not None else 0
            rc = _resource_count(opponent) if opponent is not None else 0
            threat_multiplier = 1.0 + (0.10 * vp) + (0.03 * rc)
            impact_score += pips * float(b.get("weight", 0)) * threat_multiplier

        if own_weight > 0:
            impact_score -= pips * own_weight * 2.5

        selected = choose_basic_steal_opponent(
            game,
            player,
            tile_id,
            preferred_opponent_id=preferred_opponent_id,
            needed_resource_weights=needed,
        )
        steal_score = float(selected.get("score", 0.0)) if selected else 0.0

        preferred_bonus = 0.0
        if preferred_opponent_id is not None and selected and _safe_int(selected.get("opponent_id")) == int(preferred_opponent_id):
            preferred_bonus = 2.0

        score = impact_score + steal_score + preferred_bonus
        if score <= 0.0:
            continue

        candidates.append(
            {
                "tile_id": tile_id,
                "tile_type": tile_type,
                "tile_value": tile_value,
                "pips": pips,
                "score": round(score, 4),
                "production_block_score": round(impact_score, 4),
                "steal_score": round(steal_score, 4),
                "own_blocked_weight": own_weight,
                "opponent_building_weight": sum(b["weight"] for b in opponent_buildings),
                "impacted_opponent_ids": sorted(player_ids_impacted),
                "selected_opponent": selected,
                "stealable_opponents": stealable_opponents_adjacent_to_tile(game, player, tile_id),
                "reason": _robber_candidate_reason(tile_id, tile_value, pips, selected, own_weight),
            }
        )

    return candidates


def choose_basic_steal_opponent(
    game: Any,
    player: Any,
    tile_id: int,
    *,
    preferred_opponent_id: Optional[int] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    needed_resource_weights: Optional[Mapping[str, float]] = None,
) -> Optional[Dict[str, Any]]:
    """Pick a steal opponent from a robber tile."""
    rows = list(candidates if candidates is not None else stealable_opponents_adjacent_to_tile(game, player, tile_id))
    if not rows:
        return None

    needed = dict(needed_resource_weights or needed_resource_weights_from_strategy(player))
    safe_id = _safe_steal_player_id(game, player)

    scored: List[Dict[str, Any]] = []
    for row in rows:
        opponent_id = _safe_int(row.get("opponent_id"))
        opponent = _player_by_id(game, opponent_id) if opponent_id is not None else None
        resource_count = _resource_count(opponent) if opponent is not None else int(row.get("opponent_resource_count", 0) or 0)
        vp = _victory_points(opponent) if opponent is not None else 0
        needed_match = _needed_resource_match_score(opponent, needed)
        safe_bonus = 0.75 if opponent_id == safe_id else 0.0
        preferred_bonus = 5.0 if preferred_opponent_id is not None and opponent_id == int(preferred_opponent_id) else 0.0
        score = preferred_bonus + (2.0 * needed_match) + (0.60 * resource_count) + (0.35 * vp) + safe_bonus

        enriched = dict(row)
        enriched.update(
            {
                "score": round(score, 4),
                "victory_points": vp,
                "needed_resource_match_score": round(needed_match, 4),
                "safe_steal_bonus": safe_bonus,
                "preferred_opponent_bonus": preferred_bonus,
                "reason": (
                    "preferred opponent" if preferred_bonus else
                    "holds useful resources" if needed_match > 0 else
                    "most attractive adjacent opponent"
                ),
            }
        )
        scored.append(enriched)

    scored.sort(key=lambda x: (x.get("score", 0.0), x.get("opponent_resource_count", 0), x.get("victory_points", 0)), reverse=True)
    return scored[0]


def needed_resource_weights_from_strategy(player: Any) -> Dict[str, float]:
    """
    Very small strategic-resource preference model.

    It reads player.strategic_direction.remaining when available. If no strategic
    direction exists, returns neutral weights.
    """
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return {}

    remaining = direction.get("remaining", {}) or {}
    summary = direction.get("strategy_summary", {}) or {}
    weights = {name: 0.0 for name in RESOURCE_NAMES}

    if _positive(remaining.get("remaining_city_upgrades")):
        weights["Wheat"] += 2.0
        weights["Ore"] += 3.0

    if _positive(remaining.get("remaining_new_settlements")):
        weights["Wheat"] += 1.0
        weights["Wood"] += 1.0
        weights["Brick"] += 1.0
        weights["Sheep"] += 1.0

    if _positive(remaining.get("remaining_roads_to_build")):
        weights["Wood"] += 1.0
        weights["Brick"] += 1.0

    if _positive(remaining.get("remaining_dev_cards_to_buy")) or bool(summary.get("largest_army", summary.get("biggest_army", False))):
        weights["Wheat"] += 1.0
        weights["Ore"] += 1.0
        weights["Sheep"] += 1.0

    # Remove zeroes for cleaner JSON.
    return {k: v for k, v in weights.items() if v > 0}


# ──────────────────────────────────────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────────────────────────────────────


def current_robber_tile_id(game: Any) -> Optional[int]:
    """Return the tile currently occupied by the robber, if any."""
    board = getattr(game, "board", None)
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        try:
            if bool(getattr(tile, "occupied_tf", False)):
                return int(getattr(tile, "id"))
        except Exception:
            continue
    return None


def players_requiring_discard(game: Any) -> List[Dict[str, Any]]:
    """
    Return players with more than 7 resource cards.

    Used by process_discard_queue / handle_roll_seven to drive discard execution.
    """
    out: List[Dict[str, Any]] = []
    for p in list(getattr(game, "players", []) or []):
        total = _resource_count(p)
        if total > 7:
            out.append(
                {
                    "player_id": _safe_player_id(p),
                    "color": str(getattr(p, "color", "")),
                    "resource_count": total,
                    "discard_count": total // 2,
                }
            )
    return out


def legal_robber_tile_ids(game: Any) -> List[int]:
    """All legal land tiles except desert/sea/current robber tile."""
    current = current_robber_tile_id(game)
    board = getattr(game, "board", None)
    out: List[int] = []
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        tile_id = _safe_int(getattr(tile, "id", None))
        tile_type = str(getattr(tile, "type", ""))
        if tile_id is None:
            continue
        if tile_id == current:
            continue
        if tile_type in {"Sea", "Desert", "Blank", ""}:
            continue
        out.append(tile_id)
    return sorted(out)


def stealable_opponents_adjacent_to_tile(game: Any, player: Any, tile_id: int) -> List[Dict[str, Any]]:
    """Return opponents with a settlement/city adjacent to tile_id and at least 1 rcard."""
    tile = _tile_by_id(getattr(game, "board", None), tile_id)
    if tile is None:
        return []

    acting_color = str(getattr(player, "color", ""))
    buildings = _tile_buildings(game, tile)
    by_player_id: Dict[int, Dict[str, Any]] = {}

    for b in buildings:
        color = str(b.get("color", ""))
        if not color or color == "Blank" or color == acting_color:
            continue

        opponent = _player_by_color(game, color)
        if opponent is None:
            continue

        total = _resource_count(opponent)
        if total <= 0:
            continue

        oid = _safe_player_id(opponent)
        if oid is None:
            continue

        entry = by_player_id.setdefault(
            oid,
            {
                "opponent_id": oid,
                "opponent_color": color,
                "opponent_resource_count": total,
                "adjacent_intersections": [],
                "building_weight": 0,
            },
        )
        inter_id = _safe_int(b.get("intersection_id"))
        if inter_id is not None and inter_id not in entry["adjacent_intersections"]:
            entry["adjacent_intersections"].append(inter_id)
        entry["building_weight"] += int(b.get("weight", 0) or 0)

    return sorted(by_player_id.values(), key=lambda x: x["opponent_id"])


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _safe_player_id(player: Any) -> Optional[int]:
    try:
        return int(getattr(player, "id"))
    except Exception:
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _positive(value: Any) -> bool:
    try:
        return float(value or 0) > 0.0
    except Exception:
        return False


def _pips_from_tile_value(value: int) -> float:
    try:
        value = int(value)
    except Exception:
        return 0.0
    if not (2 <= value <= 12) or value == 7:
        return 0.0
    return float(6 - abs(7 - value))


def _victory_points(player: Any) -> int:
    if player is None:
        return 0
    for attr in ("victory_points", "points"):
        try:
            return int(getattr(player, attr))
        except Exception:
            pass
    return 0


def _resource_count(player: Any) -> int:
    if player is None:
        return 0
    rcards = getattr(player, "rcards", {})
    if isinstance(rcards, Mapping):
        total = 0
        for v in rcards.values():
            try:
                total += int(v or 0)
            except Exception:
                pass
        return total

    try:
        return int(getattr(player, "number_of_rcards", 0) or 0)
    except Exception:
        return 0


def _players_to_discard_flag_vector(players_to_discard: Iterable[Dict[str, Any]]) -> List[int]:
    flags = [0, 0, 0, 0, 0]
    for row in players_to_discard:
        pid = _safe_int(row.get("player_id"))
        if pid is not None and 0 <= pid < len(flags):
            flags[pid] = 1
    return flags


def _tile_by_id(board: Any, tile_id: int) -> Any:
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is not None and _safe_int(getattr(tile, "id", None)) == int(tile_id):
            return tile
    return None


def _intersection_by_id(board: Any, inter_id: int) -> Any:
    intersections = list(getattr(board, "intersections", []) or [])
    if 0 <= int(inter_id) < len(intersections):
        inter = intersections[int(inter_id)]
        if inter is not None and _safe_int(getattr(inter, "id", None)) == int(inter_id):
            return inter

    for inter in intersections:
        if inter is not None and _safe_int(getattr(inter, "id", None)) == int(inter_id):
            return inter
    return None


def _player_by_id(game: Any, player_id: Optional[int]) -> Any:
    if player_id is None:
        return None
    for p in list(getattr(game, "players", []) or []):
        if _safe_player_id(p) == int(player_id):
            return p
    return None


def _player_by_color(game: Any, color: str) -> Any:
    for p in list(getattr(game, "players", []) or []):
        if str(getattr(p, "color", "")) == str(color):
            return p
    return None


def _corner_value(corner: Any, name: str, default: Any = None) -> Any:
    if isinstance(corner, Mapping):
        return corner.get(name, default)
    return getattr(corner, name, default)


def _tile_buildings(game: Any, tile: Any) -> List[Dict[str, Any]]:
    """Return settlement/city records around a tile."""
    out: List[Dict[str, Any]] = []
    board = getattr(game, "board", None)

    for corner in list(getattr(tile, "corners", []) or []):
        inter_id = _safe_int(_corner_value(corner, "intersection"))
        inter = _intersection_by_id(board, inter_id) if inter_id is not None else None

        kind = str(getattr(inter, "face", "") if inter is not None else "")
        color = str(getattr(inter, "color", "") if inter is not None else "")

        if kind in {"", "Blank", "None"}:
            kind = str(_corner_value(corner, "kind", _corner_value(corner, "type", "Blank")))
        if color in {"", "Blank", "None"}:
            color = str(_corner_value(corner, "color", "Blank"))

        kind_lower = kind.lower()
        if kind_lower == "city":
            weight = 2
        elif kind_lower == "settlement":
            weight = 1
        else:
            continue

        out.append(
            {
                "intersection_id": inter_id,
                "kind": "City" if weight == 2 else "Settlement",
                "color": color,
                "weight": weight,
            }
        )

    return out


def _safe_steal_player_id(game: Any, player: Any) -> Optional[int]:
    """The previous player in turn order, used as a small tie-break bonus."""
    players = list(getattr(game, "players", []) or [])
    if not players:
        return None
    player_id = _safe_player_id(player)
    if player_id is None:
        return None
    ids = [_safe_player_id(p) for p in players]
    ids = [pid for pid in ids if pid is not None]
    if player_id not in ids:
        return None
    idx = ids.index(player_id)
    return ids[idx - 1]


def _resource_name(resource: Any) -> str:
    value = getattr(resource, "value", None)
    if value is not None:
        return str(value)
    name = getattr(resource, "name", None)
    if name is not None:
        return str(name).title()
    return str(resource)


def _needed_resource_match_score(opponent: Any, needed_weights: Mapping[str, float]) -> float:
    if opponent is None or not needed_weights:
        return 0.0
    score = 0.0
    rcards = getattr(opponent, "rcards", {}) or {}
    if not isinstance(rcards, Mapping):
        return 0.0
    for rc, count in rcards.items():
        try:
            n = int(count or 0)
        except Exception:
            n = 0
        score += n * float(needed_weights.get(_resource_name(rc), 0.0) or 0.0)
    return score


def _resource_delta_vector(resource_name: str, amount: int) -> List[int]:
    # Existing turn_detail vectors use six slots; first five are resources.
    out = [0, 0, 0, 0, 0, 0]
    try:
        idx = RESOURCE_NAMES.index(resource_name)
        out[idx] = int(amount)
    except Exception:
        pass
    return out


def _add_turn_detail_delta(player: Any, attr_name: str, resource_name: str, amount: int) -> None:
    """Add one resource delta to an existing player turn-detail vector."""
    current = getattr(player, attr_name, None)
    if not isinstance(current, list):
        current = [0, 0, 0, 0, 0, 0]
    if len(current) < 6:
        current = list(current) + [0] * (6 - len(current))
    delta = _resource_delta_vector(resource_name, amount)
    for i in range(6):
        current[i] += delta[i]
    setattr(player, attr_name, current)


def _robber_candidate_reason(
    tile_id: int,
    tile_value: int,
    pips: float,
    selected: Optional[Mapping[str, Any]],
    own_weight: int,
) -> str:
    parts = [f"tile {tile_id} value {tile_value} blocks {pips:g} pips"]
    if selected:
        parts.append(f"steal target player {selected.get('opponent_id')}")
    if own_weight:
        parts.append(f"self-block fallback weight {own_weight}")
    return "; ".join(parts)



# ──────────────────────────────────────────────────────────────────────────────
# Discard logic (kept in game_7logic for now — strategy-aware AI + human submit)
# ──────────────────────────────────────────────────────────────────────────────

DISCARD_PENDING_STATE = "DiscardPending"


def build_strategy_resource_profile(game: Any, player: Any) -> Dict[str, Any]:
    """Shared protect/surplus weights for discard (and TwP consumers).

    Stage A: prefer ``ai_hand_risk`` keep/ditch scores so discard matches the
    hand-risk profile. Falls back to legacy need-based weights if import fails.

    Higher protect_weight => keep the card.
    Higher discard_score => prefer discarding that resource.
    """
    try:
        from core.ai_hand_risk import build_hand_risk_profile

        risk = build_hand_risk_profile(game, player)
        return {
            "hand": list(risk.get("hand") or [0, 0, 0, 0, 0]),
            "need": list(risk.get("need") or [0, 0, 0, 0, 0]),
            "production_pips": list(risk.get("production_pips") or [0.0] * 5),
            "trade_rates": list(risk.get("trade_rates") or [4, 4, 4, 4, 4]),
            "protect_weight": list(risk.get("protect_weight") or [0.0] * 5),
            "surplus_weight": list(risk.get("surplus_weight") or [0.0] * 5),
            "discard_score": list(risk.get("discard_score") or [0.0] * 5),
            "resource_order": list(RESOURCE_NAMES),
            "hand_risk_profile": dict(risk),
            "keep": list(risk.get("keep") or [0, 0, 0, 0, 0]),
            "ditch": list(risk.get("ditch") or [0, 0, 0, 0, 0]),
            "policy": risk.get("policy", "accept"),
        }
    except Exception:
        pass

    hand = _hand_vector5(player)
    pips = _production_pips_vector5(game, player)
    rates = _trade_rates_vector5(game, player)
    need = _strategy_need_vector5(player)

    protect = [0.0] * 5
    surplus = [0.0] * 5
    for i in range(5):
        protect[i] = float(need[i]) * 3.0
        if pips[i] < 1.5 and need[i] > 0:
            protect[i] += 2.0
        if pips[i] < 1.0 and hand[i] <= 1:
            protect[i] += 1.5
        surplus[i] = max(0.0, float(hand[i]) - float(need[i]))
        if surplus[i] > 0 and rates[i] <= 3:
            surplus[i] += 0.25

    discard_score = [0.0] * 5
    for i in range(5):
        if hand[i] <= 0:
            discard_score[i] = -999.0
            continue
        discard_score[i] = (
            surplus[i] * 4.0
            + float(pips[i]) * 0.35
            + (0.4 if rates[i] <= 3 and surplus[i] > 0 else 0.0)
            - protect[i] * 2.5
            + float(hand[i]) * 0.1
        )

    return {
        "hand": hand,
        "need": need,
        "production_pips": pips,
        "trade_rates": rates,
        "protect_weight": protect,
        "surplus_weight": surplus,
        "discard_score": discard_score,
        "resource_order": list(RESOURCE_NAMES),
    }


def _hand_vector5(player: Any) -> List[int]:
    out = [0, 0, 0, 0, 0]
    if player is None:
        return out
    rcards = getattr(player, "rcards", None)
    if isinstance(rcards, Mapping):
        for i, name in enumerate(RESOURCE_NAMES):
            # enum or string keys
            val = 0
            for key in (name, name.lower(), name.upper()):
                if key in rcards:
                    try:
                        val = int(rcards.get(key) or 0)
                        break
                    except Exception:
                        pass
            if val == 0:
                for k, v in rcards.items():
                    kn = getattr(k, "value", k)
                    if str(kn) == name:
                        try:
                            val = int(v or 0)
                        except Exception:
                            val = 0
                        break
            out[i] = max(0, val)
        return out
    try:
        info = player.rcards_in_hand()
        if isinstance(info, (list, tuple)) and info and isinstance(info[0], (list, tuple)):
            return [max(0, int(x or 0)) for x in list(info[0])[:5]] + [0] * 5
    except Exception:
        pass
    return out[:5]


def _production_pips_vector5(game: Any, player: Any) -> List[float]:
    try:
        from core.resource_time_estimator import get_player_production_pips
        board = getattr(game, "board", None)
        if board is not None and player is not None:
            return [float(x) for x in get_player_production_pips(board, player)[:5]]
    except Exception:
        pass
    return [0.0] * 5


def _trade_rates_vector5(game: Any, player: Any) -> List[int]:
    try:
        from core.resource_time_estimator import get_player_trade_rates
        board = getattr(game, "board", None)
        if board is not None and player is not None:
            return [max(1, int(x or 4)) for x in get_player_trade_rates(board, player)[:5]]
    except Exception:
        pass
    return [4, 4, 4, 4, 4]


def _strategy_need_vector5(player: Any) -> List[int]:
    """Best-effort remaining resource need from strategic_direction / defaults."""
    need = [0, 0, 0, 0, 0]
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        direction = {}

    named = direction.get("needed_rcards") or direction.get("needed_rcards_after")
    if isinstance(named, Mapping):
        for i, name in enumerate(RESOURCE_NAMES):
            for key in (name, name.lower(), "Wool" if name == "Sheep" else name):
                if key in named:
                    try:
                        need[i] = max(0, int(round(float(named.get(key) or 0))))
                    except Exception:
                        pass
                    break

    # Cost from supporting action if need empty
    if sum(need) == 0:
        support = str(direction.get("supporting_action_type", "") or "").lower()
        costs = {
            "city": [2, 3, 0, 0, 0],
            "city_upgrade": [2, 3, 0, 0, 0],
            "settlement": [1, 0, 1, 1, 1],
            "next_settlement": [1, 0, 1, 1, 1],
            "new_settlement": [1, 0, 2, 2, 1],  # settlement + ~1 road soft
            "road": [0, 0, 1, 1, 0],
            "buy_dcard": [1, 1, 0, 0, 1],
            "dcard": [1, 1, 0, 0, 1],
            "development_card": [1, 1, 0, 0, 1],
        }
        for key, vec in costs.items():
            if key in support:
                need = list(vec)
                break
    return need


def plan_ai_discard(game: Any, player: Any, discard_count: Optional[int] = None) -> Dict[str, Any]:
    """Choose which cards an AI player discards (strategy-aware / Stage A keep-ditch)."""
    hand = _hand_vector5(player)
    total = sum(hand)
    if discard_count is None:
        discard_count = total // 2 if total > 7 else 0
    discard_count = max(0, int(discard_count))
    profile = build_strategy_resource_profile(game, player)
    scores = list(profile["discard_score"])
    remaining = list(hand)
    discard_vec = [0, 0, 0, 0, 0]
    reasons: List[str] = []
    keep = list(profile.get("keep") or [0, 0, 0, 0, 0])
    ditch_left = [max(0, int(hand[i]) - int(keep[i])) for i in range(5)]

    for _ in range(discard_count):
        best_i = None
        best_s = -1e18
        for i in range(5):
            if remaining[i] <= 0:
                continue
            s = scores[i]
            # Prefer pure ditch units; penalize taking last keep unit
            if ditch_left[i] <= 0:
                s -= 5.0
            if profile["protect_weight"][i] >= 3.0 and remaining[i] == 1:
                s -= 1.5
            if s > best_s:
                best_s = s
                best_i = i
        if best_i is None:
            break
        discard_vec[best_i] += 1
        remaining[best_i] -= 1
        if ditch_left[best_i] > 0:
            ditch_left[best_i] -= 1
            tag = "ditch"
        else:
            tag = "keep"
        reasons.append(f"drop {RESOURCE_NAMES[best_i]} ({tag}, score={best_s:.2f})")

    risk = profile.get("hand_risk_profile") if isinstance(profile.get("hand_risk_profile"), Mapping) else {}
    return {
        "ok": sum(discard_vec) == discard_count or discard_count == 0,
        "player_id": _safe_player_id(player),
        "discard_count": discard_count,
        "discard_vector": discard_vec,
        "hand_before": hand,
        "reasons": reasons[:8],
        "strategy_note": "Stage A keep={} ditch={} policy={}".format(
            profile.get("keep", profile.get("need")),
            profile.get("ditch"),
            profile.get("policy", risk.get("policy", "accept")),
        ),
        "profile": {
            k: profile[k]
            for k in (
                "need",
                "protect_weight",
                "surplus_weight",
                "discard_score",
                "keep",
                "ditch",
                "policy",
            )
            if k in profile
        },
        "hand_risk_profile": dict(risk) if risk else {},
    }


def execute_discard(game: Any, player: Any, discard_vector: Sequence[Any], *, source: str = "discard") -> Dict[str, Any]:
    """Mutate player hand by removing discard_vector cards. Returns result dict."""
    hand = _hand_vector5(player)
    vec = [max(0, int(x or 0)) for x in list(discard_vector or [])[:5]]
    while len(vec) < 5:
        vec.append(0)
    result: Dict[str, Any] = {
        "ok": False,
        "player_id": _safe_player_id(player),
        "discard_vector": vec,
        "hand_before": hand,
        "reason": "",
    }
    if player is None:
        result["reason"] = "no_player"
        return result
    for i in range(5):
        if vec[i] > hand[i]:
            result["reason"] = f"not_enough_{RESOURCE_NAMES[i]}"
            return result
    total = sum(hand)
    required = total // 2 if total > 7 else 0
    # Allow exact required or explicit vector matching required when still over 7
    if required > 0 and sum(vec) != required:
        result["reason"] = f"must_discard_{required}_got_{sum(vec)}"
        return result
    if required == 0 and sum(vec) == 0:
        result["ok"] = True
        result["reason"] = "nothing_to_discard"
        result["hand_after"] = hand
        return result

    _apply_hand_delta(player, [-v for v in vec])
    hand_after = _hand_vector5(player)
    result.update({"ok": True, "reason": "executed", "hand_after": hand_after})

    pid = _safe_player_id(player)
    parts = [f"{RESOURCE_NAMES[i]}:{vec[i]}" for i in range(5) if vec[i]]
    message = "discarded " + (", ".join(parts) if parts else "nothing")
    try:
        from core import mglog

        mglog.log_discard_7(game, player, vec, source=str(source or "discard"))
    except Exception:
        pass
    _emit_twitter(game, pid, message)
    _record_turn_event(
        game,
        player=player,
        event_type="discard",
        source=source,
        message=message,
        metadata={"discard_vector": vec, "hand_before": hand, "hand_after": hand_after, "resource_order": list(RESOURCE_NAMES)},
    )
    try:
        for i, name in enumerate(RESOURCE_NAMES):
            if vec[i]:
                _record_turn_delta(
                    game,
                    player,
                    "discard",
                    name,
                    -int(vec[i]),
                    event_type="discard",
                    source=source,
                    reason="discard",
                    message=message,
                )
    except Exception:
        pass
    return result


def _apply_hand_delta(player: Any, delta: Sequence[int]) -> None:
    """Add delta (can be negative) to player.rcards for each resource index."""
    if player is None:
        return
    if not hasattr(player, "rcards") or not isinstance(getattr(player, "rcards", None), dict):
        # best effort
        try:
            from core.constants import ResourceCard
            player.rcards = {rc: 0 for rc in ResourceCard}
        except Exception:
            player.rcards = {name: 0 for name in RESOURCE_NAMES}

    rcards = player.rcards
    for i, name in enumerate(RESOURCE_NAMES):
        amount = int(delta[i] if i < len(delta) else 0)
        if amount == 0:
            continue
        key = None
        for k in list(rcards.keys()):
            kn = getattr(k, "value", k)
            if str(kn) == name:
                key = k
                break
        if key is None:
            try:
                from core.constants import ResourceCard
                for rc in ResourceCard:
                    if rc.value == name:
                        key = rc
                        break
            except Exception:
                key = name
        if key is None:
            key = name
        cur = int(rcards.get(key, 0) or 0)
        rcards[key] = max(0, cur + amount)
    try:
        player.number_of_rcards = int(sum(_hand_vector5(player)))
    except Exception:
        pass


def validate_human_discard_vector(player: Any, discard_vector: Sequence[Any]) -> Dict[str, Any]:
    hand = _hand_vector5(player)
    vec = [max(0, int(x or 0)) for x in list(discard_vector or [])[:5]]
    while len(vec) < 5:
        vec.append(0)
    reasons: List[str] = []
    for i in range(5):
        if vec[i] > hand[i]:
            reasons.append(f"not enough {RESOURCE_NAMES[i]}")
    total = sum(hand)
    required = total // 2 if total > 7 else 0
    if sum(vec) != required:
        reasons.append(f"need {required} cards, selected {sum(vec)}")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "hand": hand,
        "discard_vector": vec,
        "discard_count": required,
        "selected": sum(vec),
    }


def process_discard_queue(game: Any, *, open_human_panel: bool = True) -> Dict[str, Any]:
    """
    Process remaining discard queue.
    - AI players: auto plan+execute immediately
    - Human: open discard panel and pause (state DiscardPending)

    Returns status including whether robber may proceed.
    """
    pending = getattr(game, "pending_discard_queue", None)
    if pending is None:
        pending = []
        try:
            game.pending_discard_queue = pending
        except Exception:
            pass

    # Normalize queue entries
    queue: List[Dict[str, Any]] = list(pending or [])
    executed: List[Dict[str, Any]] = []
    waiting_human: Optional[Dict[str, Any]] = None

    while queue:
        entry = queue[0]
        pid = _safe_int(entry.get("player_id"))
        player = _player_by_id(game, pid)
        if player is None:
            queue.pop(0)
            continue
        total = _resource_count(player)
        need = total // 2 if total > 7 else 0
        if need <= 0:
            queue.pop(0)
            continue

        if _is_human_player(player):
            waiting_human = {
                "player_id": pid,
                "discard_count": need,
                "resource_count": total,
            }
            try:
                game.state = DISCARD_PENDING_STATE
                game.state_1 = DISCARD_PENDING_STATE
                game.myturn.validate_function_discard_rcards_by_HP = True
                game.myturn.validate_function_set_robber_by_HP = False
            except Exception:
                pass
            if open_human_panel:
                try:
                    from gui.gui_discard_panel import open_discard_panel
                    open_discard_panel(game, player_id=pid, discard_count=need)
                except Exception as exc:
                    waiting_human["panel_error"] = str(exc)
            break

        # AI
        plan = plan_ai_discard(game, player, discard_count=need)
        res = execute_discard(game, player, plan.get("discard_vector", []), source="ai_discard")
        executed.append({"plan": plan, "result": res})
        queue.pop(0)

    try:
        game.pending_discard_queue = queue
    except Exception:
        pass

    robber_ready = not queue and waiting_human is None
    if robber_ready:
        try:
            game.myturn.validate_function_discard_rcards_by_HP = False
        except Exception:
            pass
    return {
        "ok": True,
        "executed": executed,
        "waiting_human": waiting_human,
        "queue_remaining": list(queue),
        "robber_ready": robber_ready,
    }


def submit_human_discard(game: Any, discard_vector: Sequence[Any], *, player_id: Optional[int] = None) -> Dict[str, Any]:
    """Validate and execute human discard, then continue the discard queue."""
    if player_id is None:
        try:
            player_id = int((getattr(game, "pending_discard_queue") or [{}])[0].get("player_id"))
        except Exception:
            player_id = None
    player = _player_by_id(game, player_id)
    if player is None:
        return {"ok": False, "reason": "player_not_found"}
    check = validate_human_discard_vector(player, discard_vector)
    if not check.get("ok"):
        return {"ok": False, "reason": "; ".join(check.get("reasons") or ["invalid"]), "validation": check}
    res = execute_discard(game, player, check["discard_vector"], source="human_discard_panel")
    if not res.get("ok"):
        return res
    # Pop this human from queue if present
    queue = list(getattr(game, "pending_discard_queue", []) or [])
    queue = [e for e in queue if _safe_int(e.get("player_id")) != _safe_player_id(player)]
    game.pending_discard_queue = queue
    try:
        from gui.gui_discard_panel import close_discard_panel
        close_discard_panel(game)
    except Exception:
        pass
    # Continue with remaining discards / enable robber
    cont = process_discard_queue(game, open_human_panel=True)
    if cont.get("robber_ready"):
        _begin_robber_after_discards(game)
    return {"ok": True, "discard": res, "continuation": cont}


def _begin_robber_after_discards(game: Any) -> None:
    """Transition to MoveRobber after all discards complete."""
    pending = getattr(game, "pending_seven_roll", None) or {}
    active_id = pending.get("player_id")
    active = _player_by_id(game, active_id) if active_id is not None else None
    legal = pending.get("legal_robber_tile_ids") or legal_robber_tile_ids(game)
    robber_before = pending.get("robber_tile_before")
    try:
        game.state = "MoveRobber"
        game.state_1 = "MoveRobber"
        game.myturn.validate_function_set_robber_by_HP = True
        game.myturn.validate_function_discard_rcards_by_HP = False
    except Exception:
        pass
    if active is not None and _is_human_player(active):
        _show_robber_tile_visual(game, robber_before if robber_before is not None else current_robber_tile_id(game))
        _show_available_robber_tiles_visual(game, legal)
    _emit_twitter(game, active_id, "discard complete — place robber")



__all__ = [
    "ACTION_SELECTION_STATE",
    "ROBBER_MOVE_STATES",
    "STEAL_PICK_STATE",
    "STEAL_SELECT_STATE",
    "handle_roll_seven_no_discard",
    "plan_basic_robber_action",
    "score_robber_tiles",
    "choose_basic_steal_opponent",
    "execute_basic_robber_strategy",
    "move_robber_basic",
    "select_robber_steal_opponent_basic",
    "steal_random_resource_basic",
    "cancel_basic_robber_flow",
    "current_robber_tile_id",
    "players_requiring_discard",
    "submit_human_discard",
    "process_discard_queue",
    "validate_human_discard_vector",
    "execute_discard",
    "plan_ai_discard",
    "build_strategy_resource_profile",
    "DISCARD_PENDING_STATE",
    "legal_robber_tile_ids",
    "stealable_opponents_adjacent_to_tile",
]
