"""core/ai_road_planner.py

Strategy-aware AI road planner.

This module is the Step-2 home for road intelligence.  It does not mutate game
state.  It combines:
- outlook/path discovery from core.outlook_logic;
- conservative risk checks from core.risk_assessment;
- optional Expected-Hand timing from core.resource_time_estimator;
- current player strategic_direction / last_strategic_direction.

Game.py should only ask this module: "is a Build-road candidate strategically
allowed, and which legal road should be executed?"
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from core.outlook_logic import (
        _normalise_road_key,
        candidate_road_set,
        find_reachable_new_settlement_paths,
        future_settlement_target_is_open,
        player_owned_road_keys,
        route_path_is_clear_for_player,
    )
except Exception:  # pragma: no cover - editor/import fallback
    def _normalise_road_key(road: Any) -> Tuple[int, int]:  # type: ignore[misc]
        try:
            a, b = list(road)[:2]
            return tuple(sorted((int(a), int(b))))
        except Exception:
            return ()  # type: ignore[return-value]

    def candidate_road_set(*_: Any, **__: Any) -> set[Tuple[int, int]]:
        return set()

    def find_reachable_new_settlement_paths(*_: Any, **__: Any) -> List[Dict[str, Any]]:
        return []

    def future_settlement_target_is_open(*_: Any, **__: Any) -> bool:
        return False

    def player_owned_road_keys(*_: Any, **__: Any) -> set[Tuple[int, int]]:
        return set()

    def route_path_is_clear_for_player(*_: Any, **__: Any) -> bool:
        return False

try:
    from core.risk_assessment import assess_new_settlement_path_risk
except Exception:  # pragma: no cover
    def assess_new_settlement_path_risk(*_: Any, **__: Any) -> Dict[str, Any]:
        return {"risk_level": "low", "risk_score": 0.0, "risk_class": 0, "reasons": []}

try:
    from core.resource_time_estimator import estimate_new_settlement_target
except Exception:  # pragma: no cover - optional timing layer
    estimate_new_settlement_target = None  # type: ignore[assignment]


BUILD_ROAD = "Build road"
MAX_AI_SETTLEMENT_ROAD_DISTANCE = 3


def execution_player_is_human(game: Any, player: Any) -> bool:
    """Return True when player should be treated as human in Execution."""
    if player is None:
        return False
    try:
        if bool(getattr(player, "is_human", False)):
            return True
    except Exception:
        pass
    try:
        human_player = bool(getattr(game, "HUMAN_PLAYER", False))
    except Exception:
        human_player = False
    # Most versions use core.constants.HUMAN_PLAYER rather than game.HUMAN_PLAYER.
    try:
        from core.constants import HUMAN_PLAYER  # type: ignore
        human_player = bool(HUMAN_PLAYER)
    except Exception:
        pass
    if not human_player:
        return False
    try:
        if hasattr(game, "_normalised_human_player_ids_for_execution"):
            return int(getattr(player, "id", 0) or 0) in game._normalised_human_player_ids_for_execution()
    except Exception:
        pass
    try:
        from core.constants import HP_ID  # type: ignore
        raw = HP_ID if isinstance(HP_ID, (list, tuple, set)) else [HP_ID]
        return int(getattr(player, "id", 0) or 0) in {int(x) for x in raw}
    except Exception:
        return False


def way_wants_longest_road(player: Any) -> bool:
    """True when sticky preferred way still tags Longest Road."""
    if player is None:
        return False
    try:
        direction = _current_player_strategic_direction(player)
        if bool(direction.get("longest_road") or direction.get("longest_route")):
            return True
        summary = direction.get("strategy_summary") if isinstance(direction.get("strategy_summary"), Mapping) else {}
        if bool(summary.get("longest_road")):
            return True
        wr = direction.get("way_requirements") if isinstance(direction.get("way_requirements"), Mapping) else {}
        if bool(wr.get("longest_road")):
            return True
        tags = direction.get("tags") or direction.get("way_tags") or []
        tag_text = " ".join(
            str(t).lower() for t in (tags if isinstance(tags, (list, tuple)) else [tags])
        )
        if "longest" in tag_text and "road" in tag_text:
            return True
    except Exception:
        return False
    return False


def _collect_lr_edge_candidates(game: Any, player: Any) -> List[Any]:
    """Cheap sample of edges to test for live LR claim (cap later)."""
    candidates: List[Any] = []
    try:
        report = getattr(game, "last_execution_scan_report", None) or {}
        # buy_build_choices style
        for choice in list(report.get("buy_build_choices") or [])[:20]:
            if not isinstance(choice, Mapping):
                continue
            if "road" not in str(choice.get("action") or "").lower():
                continue
            for c in list(choice.get("candidates") or [])[:20]:
                if isinstance(c, Mapping):
                    for key in ("road_id", "road", "edge", "target_road"):
                        if key in c:
                            candidates.append(c.get(key))
                            break
                else:
                    candidates.append(c)
        for row in list(report.get("candidates") or report.get("viable") or [])[:40]:
            if not isinstance(row, Mapping):
                continue
            act = str(row.get("action") or "").lower()
            if "road" not in act:
                continue
            for key in ("road_id", "road", "edge", "target_road"):
                if key in row:
                    candidates.append(row[key])
                    break
    except Exception:
        pass
    try:
        scan = getattr(game, "current_viable_action_scan", None)
        if isinstance(scan, Mapping):
            for c in list((scan.get("candidates") or {}).get(BUILD_ROAD) or [])[:30]:
                if isinstance(c, Mapping):
                    for key in ("road_id", "road", "edge"):
                        if key in c:
                            candidates.append(c.get(key))
                            break
    except Exception:
        pass
    try:
        direction = _current_player_strategic_direction(player)
        for key in ("roads_to_build", "next_roads", "candidate_roads", "lr_roads", "locked_roads_to_build"):
            raw = direction.get(key)
            if isinstance(raw, (list, tuple)):
                candidates.extend(list(raw))
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            candidates.extend(list(sticky.get("locked_roads_to_build") or []))
    except Exception:
        pass
    return candidates


def road_is_live_lr_claim_edge(game: Any, player: Any, road: Any) -> bool:
    """S5a: True when this single edge would take/steal LR now (way must want LR)."""
    if player is None or not way_wants_longest_road(player):
        return False
    key = _road_key_from_any(road)
    if not key:
        return False
    try:
        from core.longest_road import evaluate_lr_claim_after_edges

        eval_lr = evaluate_lr_claim_after_edges(game, player, [key], min_length=5)
        return bool(eval_lr.get("takes_now"))
    except Exception:
        return False


def ai_road_longest_road_exception_active(game: Any, player: Any) -> bool:
    """True when *some* legal edge is a live LR claim (PR4 / S5a diagnostic).

    S5a: does **not** disable the path guard globally — use
    ``road_is_live_lr_claim_edge`` per edge. This flag remains for callers that
    only need "is an LR steal live right now?".
    """
    if player is None or not way_wants_longest_road(player):
        return False
    try:
        from core.longest_road import evaluate_lr_claim_after_edges
    except Exception:
        return False

    checked = 0
    for raw in _collect_lr_edge_candidates(game, player):
        if checked >= 12:
            break
        key = _road_key_from_any(raw)
        if not key:
            continue
        try:
            eval_lr = evaluate_lr_claim_after_edges(game, player, [key], min_length=5)
            checked += 1
            if bool(eval_lr.get("takes_now")):
                return True
        except Exception:
            continue
    return False


def ai_road_guard_applies(game: Any, player: Any) -> bool:
    """Return True when AI road filtering should protect the player.

    S5a: always on for AI (LR is a per-edge exception, not a global off switch).
    """
    if player is None:
        return False
    if execution_player_is_human(game, player):
        return False
    return True


def _as_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _road_key_from_any(road: Any) -> Tuple[int, int]:
    return _normalise_road_key(road)


def _route_roads_from_value(value: Any) -> List[Tuple[int, int]]:
    """Extract road keys from mixed planner fields."""
    roads: List[Tuple[int, int]] = []

    def add_road(raw: Any) -> None:
        key = _road_key_from_any(raw)
        if key and key not in roads:
            roads.append(key)

    if isinstance(value, Mapping):
        for road_key in ("road_id", "road", "edge", "target_road", "road_to_build"):
            if road_key in value:
                add_road(value.get(road_key))
        for nested_key in (
            "roads_to_build",
            "supporting_action_roads_to_build",
            "supporting_action_path",
            "path",
            "road_path",
            "route_roads",
            "new_settlement_roads_to_build",
        ):
            if nested_key in value:
                for nested in _route_roads_from_value(value.get(nested_key)):
                    add_road(nested)
        return roads

    if isinstance(value, (list, tuple)):
        # Single road pair: [15, 16]
        if len(value) == 2 and all(not isinstance(x, (list, tuple, dict)) for x in value):
            add_road(value)
            return roads
        # Node path: [15, 16, 42]
        if len(value) >= 3 and all(not isinstance(x, (list, tuple, dict)) for x in value):
            nodes = list(value)
            for a, b in zip(nodes, nodes[1:]):
                add_road((a, b))
            return roads
        # List of road pairs or nested dicts.
        for item in value:
            for nested in _route_roads_from_value(item):
                add_road(nested)
    return roads


def _normalise_supporting_action_type(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "city": "city_upgrade",
        "build_city": "city_upgrade",
        "city_upgrade": "city_upgrade",
        "upgrade_city": "city_upgrade",
        "next_settlement": "next_settlement",
        "next_settle": "next_settlement",
        "build_next_settlement": "next_settlement",
        "new_settlement": "new_settlement",
        "new_settle": "new_settlement",
        "build_new_settlement": "new_settlement",
        "settlement": "build_settlement",
        "settle": "build_settlement",
        "build_settlement": "build_settlement",
        "road": "build_road",
        "build_road": "build_road",
        "dcard": "buy_dcard",
        "development_card": "buy_dcard",
        "buy_dcard": "buy_dcard",
    }
    return aliases.get(text, text)


def _current_player_strategic_direction(player: Any) -> Dict[str, Any]:
    """Return strategic_direction or last_strategic_direction as a plain dict."""
    if player is None:
        return {}
    for attr in ("strategic_direction", "last_strategic_direction"):
        value = getattr(player, attr, None)
        if isinstance(value, Mapping) and value:
            return dict(value)
    return {}


def _target_from_direction(direction: Mapping[str, Any]) -> Optional[int]:
    for key in (
        "recommendation_target_id",
        "locked_rec_target_id",
        "settlement_target_id",
        "new_settlement_target_id",
        "next_settlement_target_id",
        "target_settlement_id",
        "target_id",
        "intersection_id",
        "target",
        "location",
    ):
        if key in direction:
            target = _as_int(direction.get(key))
            if target is not None:
                return target
    pt = direction.get("project_target")
    if isinstance(pt, Mapping):
        target = _as_int(pt.get("target_id"))
        if target is not None:
            return target

    # Parse labels like "new_settlement@49".
    for key in ("target_label", "label", "supporting_action", "best_action_label", "recommendation"):
        text = str(direction.get(key, "") or "")
        if "@" in text:
            maybe = _as_int(text.split("@")[-1].strip().split()[0])
            if maybe is not None:
                return maybe
    return None


def sticky_or_direction_path_roads(player: Any) -> List[Tuple[int, int]]:
    """S5a: ordered remaining path roads — sticky first, then direction."""
    roads: List[Tuple[int, int]] = []
    try:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            for r in _route_roads_from_value(sticky.get("locked_roads_to_build")):
                if r not in roads:
                    roads.append(r)
    except Exception:
        pass
    direction = _current_player_strategic_direction(player)
    for key in (
        "locked_roads_to_build",
        "roads_to_build",
        "supporting_action_roads_to_build",
    ):
        for r in _route_roads_from_value(direction.get(key)):
            if r not in roads:
                roads.append(r)
    # Nested project_target.roads_to_build
    pt = direction.get("project_target")
    if isinstance(pt, Mapping):
        for r in _route_roads_from_value(pt.get("roads_to_build")):
            if r not in roads:
                roads.append(r)
    return roads


def remaining_path_roads_for_player(player: Any) -> List[Tuple[int, int]]:
    """Path roads not already owned by the player."""
    owned = set()
    try:
        from core.outlook_logic import player_owned_road_keys

        owned = player_owned_road_keys(getattr(player, "game", None), player)
    except Exception:
        for edge in list(getattr(player, "roads", None) or []):
            key = _road_key_from_any(edge)
            if key:
                owned.add(key)
    out: List[Tuple[int, int]] = []
    for r in sticky_or_direction_path_roads(player):
        if r and r not in owned and r not in out:
            out.append(r)
    return out


def road_is_on_strategy_path(player: Any, road: Any) -> bool:
    """True if edge is on sticky/direction settle path (remaining or full path)."""
    key = _road_key_from_any(road)
    if not key:
        return False
    path = sticky_or_direction_path_roads(player)
    return key in path


def strategy_new_settlement_route_plan(game: Any, player: Any) -> Dict[str, Any]:
    """Return strategy-approved new-settlement target/route metadata.

    S5a: prefers sticky locked path + rec target when present.
    """
    direction = _current_player_strategic_direction(player)
    if not direction:
        return {}

    support = ""
    for key in (
        "supporting_action_type",
        "supporting_action",
        "preferred_action_type",
        "preferred_action",
        "action_type",
        "action",
        "target_type",
    ):
        if key in direction:
            support = _normalise_supporting_action_type(direction.get(key))
            if support:
                break

    target = _target_from_direction(direction)
    # Sticky target if direction target missing
    if target is None:
        try:
            sticky = getattr(player, "sticky_commitment", None)
            if isinstance(sticky, Mapping):
                target = _as_int(sticky.get("locked_rec_target_id"))
        except Exception:
            pass

    roads = sticky_or_direction_path_roads(player)
    if not roads:
        roads = _route_roads_from_value(direction)

    kind = ""
    if support == "new_settlement":
        kind = "new_settlement"
    elif support in {"next_settlement", "build_settlement"}:
        kind = "next_settlement"
    elif roads and target is not None:
        # Strategy supplied a target + road path, so this is a road-supported new settlement.
        kind = "new_settlement"
    elif target is not None and support in {"build_road", "road", ""}:
        # S5a: rec target + path without explicit support still path-locks roads
        kind = "new_settlement"

    # Conservative: do not infer a generic new settlement if strategy only says
    # "Build road" without a settlement target.  That is exactly the random-road
    # behavior we are trying to prevent.
    if kind != "new_settlement" or target is None:
        return {}

    return {
        "kind": "new_settlement",
        "target_settlement_id": int(target),
        "roads_to_build": list(roads),
        "target_label": f"new_settle@{int(target)}",
        "supporting_action_type": support or "new_settlement",
        "direction": direction,
        "path_source": "sticky_or_direction",
    }


def _candidate_target_id(candidate: Mapping[str, Any]) -> Optional[int]:
    for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
        if key in candidate:
            value = _as_int(candidate.get(key))
            if value is not None:
                return value
    return None


def _candidate_pips(game: Any, target_id: int) -> float:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return 0.0
    if inter is None:
        return 0.0
    for attr in ("all_tile_pips", "three_tile_pips"):
        values = getattr(inter, attr, None)
        if isinstance(values, (list, tuple)):
            try:
                return float(sum(float(v or 0) for v in values))
            except Exception:
                pass
    total = 0.0
    try:
        for tile, _corner in game.board.intersection_to_corners.get(int(target_id), []) or []:
            for attr in ("pips", "pip", "production_pips"):
                value = getattr(tile, attr, None)
                if value not in (None, ""):
                    total += float(value)
                    break
    except Exception:
        pass
    return total


def _target_port_bonus(game: Any, target_id: int) -> float:
    try:
        inter = game.board.intersections[int(target_id)]
        port_tf = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
        if not port_tf:
            return 0.0
        port_type = str(getattr(inter, "port_type", "") or "").strip().lower()
        if port_type in {"", "blank", "none"}:
            return 0.0
        if port_type in {"3:1", "three", "any", "general"}:
            return 8.0
        return 5.0
    except Exception:
        return 0.0


def _expected_hand_timing_bonus(game: Any, player: Any, target_id: int, roads_to_build: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    """Return optional EH timing metadata and a score adjustment.

    If resource_time_estimator is unavailable, this quietly returns neutral
    timing.  This keeps the road planner independent enough for tests while still
    using EH timing in the real v033 project.
    """
    if estimate_new_settlement_target is None:
        return {"timing_score_adjustment": 0.0, "expected_turns": None, "timing_found": None}
    try:
        estimate = estimate_new_settlement_target(
            board=getattr(game, "board", None),
            player=player,
            settlement_id=int(target_id),
            roads_to_build=list(roads_to_build or []),
            current_turn=getattr(game, "turn", None),
            target_player_id=getattr(player, "id", None),
            num_players=len(list(getattr(game, "players", []) or [])) or 4,
        )
    except Exception:
        return {"timing_score_adjustment": 0.0, "expected_turns": None, "timing_found": None}

    try:
        turns = float(estimate.get("expected_turns", estimate.get("turns", 9999.0)) or 9999.0)
    except Exception:
        turns = 9999.0
    found = bool(estimate.get("found", turns < 9999.0))
    if not found or turns >= 9999.0:
        adjustment = -35.0
    else:
        adjustment = -min(40.0, turns * 2.0)
    return {
        "timing_score_adjustment": adjustment,
        "expected_turns": round(turns, 3) if turns < 9999.0 else 9999.0,
        "timing_found": found,
        "eh_estimate": estimate,
    }


def score_new_settlement_road_path(game: Any, player: Any, path: Mapping[str, Any]) -> Dict[str, Any]:
    """Score one reachable path toward a strategy-approved new settlement."""
    target_id = _as_int(path.get("target_settlement_id"))
    if target_id is None:
        return dict(path) | {"route_score": float("-inf"), "blocked": True, "reason": "invalid target"}

    roads_to_build = [_road_key_from_any(r) for r in list(path.get("roads_to_build", []) or [])]
    roads_to_build = [r for r in roads_to_build if r]
    all_roads = [_road_key_from_any(r) for r in list(path.get("route_all_roads", roads_to_build) or [])]
    all_roads = [r for r in all_roads if r]

    risk = assess_new_settlement_path_risk(game, player, target_id, all_roads or roads_to_build)
    if str(risk.get("risk_level", "")) == "blocked":
        return dict(path) | {
            "route_score": float("-inf"),
            "blocked": True,
            "risk": risk,
            "reason": "; ".join(list(risk.get("reasons", []) or [])) or "path blocked",
        }

    # Settlement beat-risk: EH for threats using RCARD_MEMORY_OPPONENTS belief
    try:
        from core.risk_assessment import enrich_settlement_race_risk_with_eh_memory

        risk = enrich_settlement_race_risk_with_eh_memory(
            game,
            player,
            risk,
            target_id=int(target_id),
            own_distance_roads=len(roads_to_build),
        )
    except Exception:
        pass

    timing = _expected_hand_timing_bonus(game, player, target_id, roads_to_build)
    pips = _candidate_pips(game, target_id)
    port_bonus = _target_port_bonus(game, target_id)
    distance_penalty = 10.0 * max(1, len(roads_to_build))
    risk_penalty = float(risk.get("risk_score", 0.0) or 0.0)
    timing_adjustment = float(timing.get("timing_score_adjustment", 0.0) or 0.0)

    score = (pips * 6.0) + port_bonus - distance_penalty - risk_penalty + timing_adjustment
    reasons = [
        f"target pips={round(pips, 2)}",
        f"roads_to_build={len(roads_to_build)}",
        f"risk={risk.get('risk_level', 'low')}",
    ]
    if timing.get("expected_turns") not in (None, ""):
        reasons.append(f"EH turns={timing.get('expected_turns')}")

    out = dict(path)
    out.update({
        "kind": "new_settlement",
        "target_settlement_id": target_id,
        "roads_to_build": roads_to_build,
        "route_all_roads": all_roads or roads_to_build,
        "next_road": roads_to_build[0] if roads_to_build else None,
        "target_label": f"new_settle@{target_id}",
        "route_score": round(float(score), 3),
        "route_risk": risk.get("risk_class", 0),
        "risk": risk,
        "timing": timing,
        "strategy_reason": "; ".join(reasons),
        "blocked": False,
    })
    return out


def _collect_live_lr_claim_edges(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    max_check: int = 12,
) -> List[Dict[str, Any]]:
    """All legal 1-edge live LR claim candidates (oracle flags, unsorted)."""
    if not way_wants_longest_road(player):
        return []
    legal_candidates = [dict(c) for c in list(candidates or []) if isinstance(c, Mapping)]
    edges: List[Tuple[int, int]] = []
    for c in legal_candidates:
        key = _road_key_from_any(c)
        if key and key not in edges:
            edges.append(key)
    if not edges:
        for raw in _collect_lr_edge_candidates(game, player):
            key = _road_key_from_any(raw)
            if key and key not in edges:
                edges.append(key)
    out: List[Dict[str, Any]] = []
    checked = 0
    for key in edges:
        if checked >= max_check:
            break
        checked += 1
        if not road_is_live_lr_claim_edge(game, player, key):
            continue
        steals = False
        try:
            from core.longest_road import evaluate_lr_claim_after_edges

            ev = evaluate_lr_claim_after_edges(game, player, [key])
            steals = bool(ev.get("steals"))
        except Exception:
            steals = False
        out.append(
            {
                "edge": key,
                "road": list(key),
                "path": [list(key)],
                "takes_now": True,
                "steals": steals,
                "claim_now": True,
            }
        )
    return out


def _sticky_settle_path_edges(player: Any) -> List[Tuple[int, int]]:
    """Locked sticky settle path as **directed** network→tip steps, if any.

    Ownership/legal callers should compare via ``_normalise_road_key``.
    """
    raw = None
    tip_id = None
    orient = None
    try:
        from core.strategy_sticky import get_sticky_commitment, orient_path_roads_network_to_tip

        orient = orient_path_roads_network_to_tip
        c = get_sticky_commitment(player)
        if isinstance(c, Mapping):
            raw = c.get("locked_roads_to_build") or c.get("roads_to_build")
            tip_id = c.get("locked_rec_target_id")
    except Exception:
        c = getattr(player, "sticky_commitment", None)
        if isinstance(c, Mapping):
            raw = c.get("locked_roads_to_build") or c.get("roads_to_build")
            tip_id = c.get("locked_rec_target_id")
    if not raw:
        try:
            d = getattr(player, "strategic_direction", None)
            if isinstance(d, Mapping):
                raw = d.get("roads_to_build") or d.get("locked_roads_to_build")
                if tip_id is None:
                    tip_id = d.get("locked_rec_target_id") or d.get(
                        "recommendation_target_id"
                    )
        except Exception:
            raw = None
    if isinstance(raw, str):
        parsed: List[List[int]] = []
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if "-" in part and part.count("-") == 1:
                a, b = part.split("-", 1)
                try:
                    parsed.append([int(a), int(b)])
                except Exception:
                    continue
        raw = parsed
    if orient is not None and raw:
        try:
            directed = orient(player, raw, tip_id=tip_id)
            if directed:
                return [tuple(e) for e in directed]  # type: ignore[misc]
        except Exception:
            pass
    out: List[Tuple[int, int]] = []
    for e in list(raw or []):
        try:
            a, b = int(e[0]), int(e[1])
            if a != b:
                out.append((a, b))
                continue
        except Exception:
            pass
        key = _road_key_from_any(e)
        if key:
            out.append(key)
    return out


def _prefer_dual_tip_road_over_branch(
    game: Any,
    player: Any,
    *,
    strategy_first: Any,
    sticky_path: Sequence[Any],
    settle_tid: int,
    legal_roads: Any,
    legal_candidates: Sequence[Mapping[str, Any]],
    owned: Any,
) -> Dict[str, Any]:
    """WP-ROAD2: if optimizer dual-tip edge beats branch-away first road, use it.

    Dig (White 35-34 vs 38-39; Blue 51-62 vs 51-52): refuse tip-away when a
    legal tip-serving edge exists.
    """
    first = _road_key_from_any(strategy_first)
    if not first:
        return {}
    path_keys = []
    owned_ids = set(owned or set())
    for e in list(sticky_path or []):
        # Prefer directed step when present; road_id for ownership filter.
        try:
            a, b = int(e[0]), int(e[1])
            k = (a, b) if a != b else ()
        except Exception:
            k = _road_key_from_any(e)
        if k and _normalise_road_key(k) not in owned_ids:
            path_keys.append(k)  # type: ignore[arg-type]
    # Build LR/grow candidates from legal roads + sticky remaining
    lr_candidates: List[Dict[str, Any]] = []
    seen = set()  # undirected road_ids
    for edge in path_keys:
        eid = _normalise_road_key(edge)
        if not eid or eid in seen:
            continue
        seen.add(eid)
        lr_candidates.append(
            {
                "edge": edge,
                "road": list(edge),
                "path": [list(e) for e in path_keys[:3]],
                "takes_now": bool(road_is_live_lr_claim_edge(game, player, edge)),
                "steals": False,
                "gain": 1,
            }
        )
    for cand in list(legal_candidates or []):
        if not isinstance(cand, Mapping):
            continue
        edge = _road_key_from_any(
            cand.get("road") or cand.get("road_id") or cand.get("edge")
        )
        eid = _normalise_road_key(edge) if edge else ()
        if not eid or eid in seen:
            continue
        if legal_roads and eid not in legal_roads:
            continue
        seen.add(eid)
        lr_candidates.append(
            {
                "edge": edge,
                "road": list(edge),
                "path": [list(edge)],
                "takes_now": bool(road_is_live_lr_claim_edge(game, player, edge)),
                "steals": False,
                "gain": 1,
            }
        )
    if not lr_candidates:
        return {}
    try:
        from core.road_optimizer import prepare_lr_road_decision

        bag = prepare_lr_road_decision(
            game,
            player,
            lr_candidates=lr_candidates,
            sticky_path=path_keys or sticky_path,
            roads_needed=max(1, len(path_keys) or 1),
        )
    except Exception:
        return {}
    best = bag.get("best") if isinstance(bag, Mapping) else None
    if not isinstance(best, Mapping):
        return {}
    tip_edge = _road_key_from_any(best.get("next_road") or best.get("edge"))
    reasons = list(best.get("reasons") or [])
    dual = any(str(r).startswith("dual_purpose") for r in reasons)
    # Prefer the sticky edge that actually hits the settle tip when strategy
    # first is a branch-away (Dig: 43-54 vs 43-44).
    tip_hit = None
    for e in path_keys:
        if int(settle_tid) in (int(e[0]), int(e[1])):
            tip_hit = e
            break
    path_ids = {_normalise_road_key(e) for e in path_keys}
    first_on_path = _normalise_road_key(first) in path_ids
    branch_away = not first_on_path
    chosen = None
    if branch_away and tip_hit and (
        not legal_roads or _normalise_road_key(tip_hit) in legal_roads
    ):
        chosen = tip_hit
    elif tip_edge and tip_edge != first and (
        not legal_roads or _normalise_road_key(tip_edge) in legal_roads
    ):
        tip_on_path = _normalise_road_key(tip_edge) in path_ids
        if dual or tip_on_path:
            if (
                first_on_path
                and tip_on_path
                and path_keys
                and _normalise_road_key(first) == _normalise_road_key(path_keys[0])
            ):
                chosen = None  # already on sticky tip order
            elif first_on_path and not dual:
                chosen = None
            else:
                chosen = tip_edge
    if not chosen:
        return {}
    rem = [chosen] + [e for e in path_keys if e != chosen]
    ranked = list(bag.get("ranked") or [])[:3]
    return {
        "kind": "new_settlement",
        "roads_to_build": rem,
        "next_road": chosen,
        "route_all_roads": rem,
        "target_settlement_id": int(settle_tid),
        "route_source": "road_optimizer_wp_road2_dual_tip",
        "strategy_reason": "wp_road2:" + (",".join(reasons) if reasons else "dual_tip"),
        "target_label": f"S@{settle_tid}",
        "blocked": False,
        "optimizer_reasons": reasons,
        "road_candidates_top3": ranked,
        "takes_now": bool(best.get("takes_now")),
    }


def _optimize_lr_priority_plan(
    game: Any,
    player: Any,
    *,
    claim_edges: Sequence[Mapping[str, Any]],
    legal_roads: Any,
    owned: Any,
) -> Dict[str, Any]:
    """When LR has priority: prepare_lr_road_decision (claimability + tips + rank)."""
    sticky_edges = _sticky_settle_path_edges(player)
    owned_ids = set(owned or set())
    sticky_remaining = [
        e for e in sticky_edges if _normalise_road_key(e) not in owned_ids
    ]
    lr_candidates: List[Dict[str, Any]] = [dict(c) for c in claim_edges]

    # Sticky first remaining edge as dual-purpose grow/claim candidate
    if sticky_remaining:
        first = sticky_remaining[0]
        first_id = _normalise_road_key(first)
        if not legal_roads or first_id in legal_roads:
            takes = bool(road_is_live_lr_claim_edge(game, player, first))
            gain = 0
            steals = False
            try:
                from core.longest_road import evaluate_lr_claim_after_edges

                ev = evaluate_lr_claim_after_edges(game, player, [first])
                takes = takes or bool(ev.get("takes_now"))
                steals = bool(ev.get("steals"))
                try:
                    from core.ai_lr_project import compute_lr_snapshot

                    snap = compute_lr_snapshot(game, player)
                    gain = int(ev.get("length_after") or 0) - int(snap.get("own_length") or 0)
                except Exception:
                    gain = 1 if not takes else 0
            except Exception:
                gain = 1 if not takes else 0
            # Always offer sticky tip edge so optimizer can anticipate
            lr_candidates.append(
                {
                    "edge": first,
                    "road": list(first),
                    "path": [list(e) for e in sticky_remaining[:3]],
                    "takes_now": takes,
                    "steals": steals,
                    "gain": max(0, gain),
                    "claim_now": takes,
                }
            )

    if not lr_candidates:
        return {}

    try:
        from core.road_optimizer import prepare_lr_road_decision

        bag = prepare_lr_road_decision(
            game,
            player,
            lr_candidates=lr_candidates,
            sticky_path=sticky_remaining or sticky_edges,
            roads_needed=max(1, len(sticky_remaining) or 1),
        )
    except Exception:
        return {}

    best = bag.get("best") if isinstance(bag, Mapping) else None
    if not isinstance(best, Mapping):
        return {}
    next_road = _road_key_from_any(best.get("next_road") or best.get("edge"))
    if not next_road:
        return {}
    if legal_roads and _normalise_road_key(next_road) not in legal_roads:
        return {}

    reasons = list(best.get("reasons") or [])
    claim_reasons = list((bag.get("claimability") or {}).get("reasons") or [])
    dual = any(str(r).startswith("dual_purpose") for r in reasons)
    takes = bool(best.get("takes_now"))
    path = best.get("path") or [list(next_road)]
    ranked = list(bag.get("ranked") or [])[:3]
    return {
        "kind": "lr_claim" if takes else "lr_grow",
        "roads_to_build": [tuple(p) if isinstance(p, (list, tuple)) else next_road for p in path]
        if isinstance(path, list)
        else [next_road],
        "next_road": next_road,
        "route_source": (
            "road_optimizer_lr_dual" if dual else "road_optimizer_lr_priority"
        ),
        "strategy_reason": (
            "road_optimizer: "
            + (",".join(reasons) if reasons else "lr_priority")
        ),
        "target_label": (
            f"LR+S{best.get('tip_id')}" if best.get("tip_id") is not None else "LR priority"
        ),
        "blocked": False,
        "optimizer_reasons": reasons,
        "claimability_reasons": claim_reasons,
        "takes_now": takes,
        "steals": bool(best.get("steals")),
        "road_candidates_top3": ranked,
    }


def _build_lr_claim_road_plan(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    legal_roads: Any = None,
    owned: Any = None,
) -> Dict[str, Any]:
    """S5a: LR-priority road — optimizer ranks claim + dual-purpose sticky tips.

    Arms when LR has priority: live 1-edge claim and/or stored/fresh LR claim
    project (``takes_now`` / ``claim_now``). Sticky settle edges are offered as
    dual-purpose alternatives.
    """
    claim_edges = _collect_live_lr_claim_edges(game, player, candidates)

    # Also pull LR project head edge when engine says claim-now (multi-edge).
    try:
        from core.ai_lr_project import (
            build_lr_project,
            get_stored_lr_project,
            remaining_lr_project_roads,
        )

        stored = get_stored_lr_project(player, game)
        rem = remaining_lr_project_roads(game, player) if stored else []
        proj = stored
        if not rem:
            proj = build_lr_project(game, player, candidates)
            if proj:
                rem = [
                    _road_key_from_any(r)
                    for r in list(proj.get("roads_to_build") or [])
                ]
                rem = [r for r in rem if r]
        takes_proj = bool(
            isinstance(proj, Mapping)
            and (proj.get("takes_now") or str(proj.get("kind") or "") == "lr_claim")
        )
        if takes_proj and rem:
            head = rem[0]
            already = {
                _road_key_from_any(c.get("edge") or c.get("road")) for c in claim_edges
            }
            if head and head not in already:
                claim_edges.append(
                    {
                        "edge": head,
                        "road": list(head),
                        "path": [list(e) for e in rem[:3]],
                        "takes_now": bool(proj.get("takes_now")),
                        "steals": bool(proj.get("steals")),
                        "claim_now": True,
                        "gain": proj.get("length_gain"),
                    }
                )
    except Exception:
        pass

    if not claim_edges:
        return {}

    owned_keys = owned if owned is not None else player_owned_road_keys(game, player)
    opt = _optimize_lr_priority_plan(
        game,
        player,
        claim_edges=claim_edges,
        legal_roads=legal_roads if legal_roads is not None else candidate_road_set(
            [dict(c) for c in list(candidates or []) if isinstance(c, Mapping)]
        ),
        owned=owned_keys,
    )
    if opt:
        # Normalize roads_to_build to road keys
        roads = []
        for r in list(opt.get("roads_to_build") or []):
            key = _road_key_from_any(r)
            if key:
                roads.append(key)
        if roads:
            opt["roads_to_build"] = roads
            opt["next_road"] = roads[0]
        return opt

    # Fallback: first live claim edge (legacy S5a)
    if claim_edges:
        key = _road_key_from_any(claim_edges[0].get("edge") or claim_edges[0].get("road"))
        if key:
            return {
                "kind": "lr_claim",
                "roads_to_build": [key],
                "next_road": key,
                "route_source": "s5a_live_lr_claim",
                "strategy_reason": "S5a: live Longest Road claim/steal edge",
                "target_label": "LR claim",
                "blocked": False,
            }
    return {}


def _alt_race_road_plan_if_urgent(
    game: Any,
    player: Any,
    legal_candidates: Sequence[Mapping[str, Any]],
    legal_roads: Any,
    *,
    exclude_tid: Optional[int] = None,
) -> Dict[str, Any]:
    """If another M/H race needs a road, return that plan (postpone calm settle).

    Used when the sticky settle is already connected / low-urgency: building a
    road is justified only by urgency elsewhere (real race), not by inventing
    detours to the settle-ready site.
    """
    try:
        from core.strategy_race_ba import race_ba_focus
    except Exception:
        return {}
    try:
        focus = race_ba_focus(game, player)
    except Exception:
        return {}
    if not isinstance(focus, Mapping) or not focus.get("apply"):
        return {}
    if str(focus.get("focus") or "").lower() != "road":
        return {}
    next_road = _road_key_from_any(focus.get("next_road"))
    if not next_road:
        return {}
    alt_tid = _as_int(focus.get("target_id"))
    if exclude_tid is not None and alt_tid is not None and int(alt_tid) == int(exclude_tid):
        return {}
    if legal_roads and next_road not in legal_roads:
        return {}
    return {
        "kind": "new_settlement",
        "target_settlement_id": alt_tid,
        "roads_to_build": [list(next_road)],
        "next_road": list(next_road),
        "route_source": "alt_race_urgent_road",
        "strategy_reason": str(focus.get("reason") or "alt_race"),
        "target_label": (
            f"alt_race@{alt_tid}" if alt_tid is not None else "alt_race"
        ),
        "dig_note": str(focus.get("dig_note") or ""),
    }


def _store_last_road_plan(game: Any, player: Any, plan: Mapping[str, Any]) -> None:
    """WP-DIG2: persist last road plan (incl. top-3) for CS Dig fields."""
    if not isinstance(plan, Mapping) or not plan:
        return
    try:
        if player is not None:
            setattr(player, "last_road_plan", dict(plan))
            setattr(player, "last_ai_road_plan", dict(plan))
    except Exception:
        pass
    try:
        if game is not None:
            setattr(game, "last_ai_road_plan", dict(plan))
    except Exception:
        pass


def build_ai_road_plan(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    commit_project: bool = True,
) -> Dict[str, Any]:
    """Return the best validated road plan for an AI player.

    Empty dict means: do not build a road now.

    S-LR-A priority:
      1. Live 1-edge LR claim
      2. Stored LR project next edge (sticky / last plan) if still legal
      3. Settlement strategy path
      4. Fresh multi-edge LR project (grow/claim)
      5. Empty

    Settle-ready sticky site (already connected): never invent detours to it.
    A road is allowed then only if another M/H race urgently needs one.

    ``commit_project=False``: plan only (no sticky/project store). Used by
    ``road_allowed_for_ai`` so a guard probe cannot arm a random grow path.
    """
    if not ai_road_guard_applies(game, player):
        return {}

    legal_candidates = [dict(c) for c in list(candidates or []) if isinstance(c, Mapping)]
    legal_roads = candidate_road_set(legal_candidates)
    owned = player_owned_road_keys(game, player)

    # --- 1) LR priority (live claim + road_optimizer dual-purpose) ---
    lr_claim = _build_lr_claim_road_plan(
        game,
        player,
        legal_candidates,
        legal_roads=legal_roads,
        owned=owned,
    )
    if lr_claim:
        if commit_project:
            try:
                from core.ai_lr_project import store_lr_project

                nr = _road_key_from_any(
                    lr_claim.get("next_road")
                    or (list(lr_claim.get("roads_to_build") or [None])[0])
                )
                if nr:
                    takes = bool(lr_claim.get("takes_now", True))
                    roads_store = []
                    for r in list(lr_claim.get("roads_to_build") or [nr]):
                        key = _road_key_from_any(r)
                        if key:
                            roads_store.append(list(key))
                    if not roads_store:
                        roads_store = [list(nr)]
                    store_lr_project(
                        game,
                        player,
                        {
                            "kind": "lr_claim" if takes else "lr_grow",
                            "roads_to_build": roads_store,
                            "next_road": list(nr),
                            "claim_after_n": 1 if takes else max(1, len(roads_store)),
                            "takes_now": takes,
                            "steals": bool(lr_claim.get("steals")),
                            "route_source": lr_claim.get("route_source"),
                            "strategy_reason": lr_claim.get("strategy_reason"),
                            "target_label": lr_claim.get("target_label") or "LR priority",
                        },
                    )
            except Exception:
                pass
        _store_last_road_plan(game, player, lr_claim)
        return lr_claim

    # --- 2) Stored LR project remaining edges ---
    try:
        from core.ai_lr_project import (
            get_stored_lr_project,
            lr_project_to_road_plan,
            remaining_lr_project_roads,
        )

        remaining_lr = remaining_lr_project_roads(game, player)
        if remaining_lr:
            first = remaining_lr[0]
            if not legal_roads or _normalise_road_key(first) in legal_roads:
                stored = get_stored_lr_project(player, game)
                plan = lr_project_to_road_plan(
                    dict(stored)
                    | {
                        "roads_to_build": [list(e) for e in remaining_lr],
                        "next_road": list(first),
                        "kind": stored.get("kind") or "lr_grow",
                        "route_source": "slr_stored_project",
                    }
                )
                if plan:
                    return plan
    except Exception:
        pass

    # --- 3) Settlement strategy path ---
    strategy_plan = strategy_new_settlement_route_plan(game, player)
    if strategy_plan:
        target_id = _as_int(strategy_plan.get("target_settlement_id"))
        if target_id is not None and future_settlement_target_is_open(game, player, target_id):
            # R10T3 policy: if sticky settle is **already connected** (settle-ready),
            # do **not** invent alternate multi-road detours (e.g. 19-20-21 port
            # path toward S32). That is not urgency — S@32 should be preferred
            # unless something else is urgent.
            #
            # Exception: another portfolio target is still a real M/H **race**
            # that needs a road — then building that race road is fine and the
            # calm settle-ready site may be postponed. Only urgency elsewhere
            # justifies skipping an affordable connected settle.
            settle_ready = False
            try:
                from core.outlook_logic import next_settlement_spots

                pid = int(getattr(player, "id"))
                settle_ready = int(target_id) in set(next_settlement_spots(game, pid) or [])
            except Exception:
                settle_ready = False

            if settle_ready:
                alt_plan = _alt_race_road_plan_if_urgent(
                    game, player, legal_candidates, legal_roads, exclude_tid=int(target_id)
                )
                if alt_plan:
                    return alt_plan
                return {}

            # First honour sticky/strategy route.
            # Path steps stay directed network→tip ([15,14] not tip-first [13,14]);
            # legal/owned membership uses undirected road_id via _normalise_road_key.
            try:
                from core.strategy_sticky import (
                    orient_path_roads_network_to_tip,
                    remaining_roads_for_player,
                )

                raw_roads = orient_path_roads_network_to_tip(
                    player,
                    strategy_plan.get("roads_to_build", []) or [],
                    tip_id=int(target_id),
                )
                roads_to_build = remaining_roads_for_player(
                    player,
                    strategy_plan.get("roads_to_build", []) or [],
                    tip_id=int(target_id),
                )
            except Exception:
                raw_roads = [
                    list(r)
                    for r in (
                        _road_key_from_any(x)
                        for x in list(strategy_plan.get("roads_to_build", []) or [])
                    )
                    if r
                ]
                roads_to_build = [
                    r for r in raw_roads if _normalise_road_key(r) not in owned
                ]
            if raw_roads:
                if roads_to_build and len(roads_to_build) <= MAX_AI_SETTLEMENT_ROAD_DISTANCE:
                    first_road = roads_to_build[0]
                    first_id = _normalise_road_key(first_road)
                    if (
                        (not legal_roads or first_id in legal_roads)
                        and route_path_is_clear_for_player(
                            game, player, raw_roads, target_id
                        )
                    ):
                        # WP-ROAD2: prefer dual-purpose tip edge over branch-away
                        dual = _prefer_dual_tip_road_over_branch(
                            game,
                            player,
                            strategy_first=first_road,
                            sticky_path=raw_roads,
                            settle_tid=int(target_id),
                            legal_roads=legal_roads,
                            legal_candidates=legal_candidates,
                            owned=owned,
                        )
                        if dual:
                            _store_last_road_plan(game, player, dual)
                            return dual
                        scored = score_new_settlement_road_path(
                            game,
                            player,
                            dict(strategy_plan)
                            | {
                                "route_all_roads": [list(r) for r in raw_roads],
                                "roads_to_build": [list(r) for r in roads_to_build],
                                "next_road": list(first_road),
                                "route_source": "s5a_sticky_or_strategy_path",
                            },
                        )
                        if not scored.get("blocked"):
                            _store_last_road_plan(game, player, scored)
                            return scored
                elif not roads_to_build:
                    # Sticky path fully owned but next_settlement_spots missed —
                    # still refuse alternate discovery toward this settle; allow
                    # only an urgent alt race road (same policy as settle_ready).
                    alt_plan = _alt_race_road_plan_if_urgent(
                        game, player, legal_candidates, legal_roads, exclude_tid=int(target_id)
                    )
                    if alt_plan:
                        return alt_plan
                    return {}

            # If strategy only supplies the settlement target, discover short paths.
            # WP-R4: prefer fresh reachability path_map before outlook BFS.
            try:
                from core.constants import REACHABILITY_MAPS
                from core.player_reachability import (
                    SENTINEL,
                    ensure_reachability_maps,
                    maps_are_fresh,
                    path_to_target,
                    remaining_roads_to_target,
                )
                from core.strategy_sticky import (
                    orient_path_roads_network_to_tip,
                    remaining_roads_for_player,
                )

                if bool(REACHABILITY_MAPS):
                    ensure_reachability_maps(game, player)
                if maps_are_fresh(player):
                    rem = remaining_roads_to_target(player, int(target_id))
                    raw_map = path_to_target(player, int(target_id))
                    map_roads = orient_path_roads_network_to_tip(
                        player, raw_map or [], tip_id=int(target_id)
                    )
                    to_build = remaining_roads_for_player(
                        player, raw_map or [], tip_id=int(target_id)
                    )
                    if (
                        map_roads
                        and to_build
                        and 1 <= int(rem) < SENTINEL
                        and len(to_build) <= MAX_AI_SETTLEMENT_ROAD_DISTANCE
                        and route_path_is_clear_for_player(
                            game, player, map_roads, int(target_id)
                        )
                    ):
                        first_road = to_build[0]
                        first_id = _normalise_road_key(first_road)
                        if not legal_roads or first_id in legal_roads:
                            scored_map = score_new_settlement_road_path(
                                game,
                                player,
                                {
                                    "target_settlement_id": int(target_id),
                                    "route_all_roads": [list(r) for r in map_roads],
                                    "roads_to_build": [list(r) for r in to_build],
                                    "next_road": list(first_road),
                                    "roads_remaining": len(to_build),
                                    "distance": len(map_roads),
                                    "route_source": "player_reachability.path_map",
                                },
                            )
                            if not scored_map.get("blocked") and scored_map.get(
                                "roads_to_build"
                            ):
                                _store_last_road_plan(game, player, scored_map)
                                return scored_map
            except Exception:
                pass

            paths = find_reachable_new_settlement_paths(
                game,
                player,
                target_ids=[target_id],
                max_distance=MAX_AI_SETTLEMENT_ROAD_DISTANCE,
                legal_road_candidates=legal_candidates,
            )
            scored_paths = [score_new_settlement_road_path(game, player, path) for path in paths]
            scored_paths = [p for p in scored_paths if not p.get("blocked") and p.get("roads_to_build")]
            if scored_paths:
                scored_paths.sort(
                    key=lambda p: (
                        float(p.get("route_score", float("-inf"))),
                        -int(p.get("roads_remaining", 99)),
                    ),
                    reverse=True,
                )
                best = dict(scored_paths[0])
                best["route_source"] = best.get("route_source") or "outlook_logic_discovered_route"
                return best

    # --- 4) Fresh multi-edge LR project (S-LR-A grow/claim) ---
    try:
        from core.ai_lr_project import (
            build_lr_project,
            lr_project_to_road_plan,
            store_lr_project,
        )

        project = build_lr_project(game, player, legal_candidates or candidates)
        if project:
            first = _road_key_from_any(
                project.get("next_road")
                or (list(project.get("roads_to_build") or [None])[0])
            )
            if first and (
                not legal_roads or _normalise_road_key(first) in legal_roads
            ):
                plan = lr_project_to_road_plan(project)
                if plan:
                    if commit_project:
                        store_lr_project(game, player, project)
                    return plan
            # If legal_roads filter empty (no candidates passed), still return plan
            if first and not legal_roads:
                plan = lr_project_to_road_plan(project)
                if plan:
                    if commit_project:
                        store_lr_project(game, player, project)
                    return plan
    except Exception:
        pass

    return {}


def choose_best_ai_road_candidate(
    game: Any,
    player: Any,
    candidates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return the concrete scanner candidate matching the planned next road."""
    plan = build_ai_road_plan(game, player, candidates)
    if not plan:
        return {}
    next_road = _road_key_from_any(plan.get("next_road") or (list(plan.get("roads_to_build", []) or [None])[0]))
    if not next_road:
        return {}
    for candidate in list(candidates or []):
        if not isinstance(candidate, Mapping):
            continue
        if _road_key_from_any(candidate) == next_road:
            out = dict(candidate)
            out["route_step"] = 1
            out["route_steps_total"] = len(list(plan.get("roads_to_build", []) or []))
            out["route_target_id"] = plan.get("target_settlement_id")
            out["route_target_label"] = plan.get("target_label")
            out["route_score"] = plan.get("route_score")
            out["route_risk"] = plan.get("route_risk")
            out["strategic_reason"] = plan.get("strategy_reason")
            out["ai_road_plan"] = plan
            return out
    # Synthetic candidate when plan is LR-only and scan row missing
    if plan.get("route_source") == "s5a_live_lr_claim":
        return {
            "road_id": list(next_road),
            "route_step": 1,
            "route_steps_total": 1,
            "strategic_reason": plan.get("strategy_reason"),
            "ai_road_plan": plan,
        }
    return {}


def should_suppress_ai_strategic_road_choice(
    game: Any,
    choice: Mapping[str, Any],
    *,
    player: Optional[Any] = None,
) -> bool:
    """Return True when a Build-road choice has no path or live-LR edge."""
    if not isinstance(choice, Mapping):
        return False
    if str(choice.get("action", "") or "") != BUILD_ROAD:
        return False
    player = player if player is not None else getattr(game, "get_current_player", lambda: None)()
    if not ai_road_guard_applies(game, player):
        return False
    candidates = [dict(c) for c in list(choice.get("candidates", []) or []) if isinstance(c, Mapping)]
    # Keep choice if *any* candidate is allowed (path or live LR)
    for c in candidates:
        if road_allowed_for_ai(game, player, c):
            return False
    # Also allow if planner finds a path/LR plan that matches a candidate
    plan = build_ai_road_plan(game, player, candidates)
    return not bool(plan)


def road_allowed_for_ai(game: Any, player: Any, road: Any) -> bool:
    """S5a last-moment guard: path edge, LR project edge, or live LR claim."""
    if not ai_road_guard_applies(game, player):
        return True
    wanted = _road_key_from_any(road)
    if not wanted:
        return False
    # 1) Sticky / strategy path (any remaining path edge is ok for execution
    #    if it is the planned next, or still on path when plan rebuild is thin)
    remaining = remaining_path_roads_for_player(player)
    if remaining:
        if wanted == remaining[0]:
            return True
        # Allow any remaining path edge that is still on the committed route
        # (stale plan item) but never off-path.
        if wanted in remaining:
            return True
    elif road_is_on_strategy_path(player, wanted):
        # Owned progress already dropped remaining; still on full path list
        # only if not owned — remaining_path empty means all owned or no path
        pass

    # 1b) S-LR-A: remaining edges on stored LR project
    try:
        from core.ai_lr_project import remaining_lr_project_roads

        lr_rem = remaining_lr_project_roads(game, player)
        if wanted in lr_rem:
            return True
    except Exception:
        pass

    # 2) Live LR claim/steal for this edge only
    if road_is_live_lr_claim_edge(game, player, wanted):
        return True

    # 3) Match planner next road (discovered path / fresh LR project).
    # Do not commit_project: a guard probe must not arm sticky LR on random edges.
    plan = build_ai_road_plan(
        game, player, [{"road_id": list(wanted)}], commit_project=False
    )
    if plan:
        next_road = _road_key_from_any(
            plan.get("next_road") or (list(plan.get("roads_to_build", []) or [None])[0])
        )
        kind = str(plan.get("kind") or "")
        route = str(plan.get("route_source") or "")
        if next_road and next_road == wanted:
            # Settle / non-LR plans always ok
            if not kind.startswith("lr"):
                return True
            # Live claim always ok
            if kind == "lr_claim" or bool(plan.get("takes_now")) or "claim" in route:
                return True
            # Fresh LR grow: only allow if edge was already on a stored project
            # (step 1b) — do not green-light arbitrary grow edges via probe.
            return False
        # Allow remaining edges only on already-stored multi-edge project (1b)
        if kind.startswith("lr") and "stored" in route:
            for r in list(plan.get("roads_to_build") or []):
                if _road_key_from_any(r) == wanted:
                    return True
    return False


def ai_road_block_reason(game: Any, player: Any, candidates: Optional[Sequence[Mapping[str, Any]]] = None) -> str:
    """Return a short explanation when a legal AI road is suppressed."""
    if player is None:
        return "AI road guard: no current player."
    strategy_plan = strategy_new_settlement_route_plan(game, player)
    if strategy_plan:
        target = _as_int(strategy_plan.get("target_settlement_id"))
        if target is None:
            return "AI road guard: new-settlement strategy has no target intersection."
        if not future_settlement_target_is_open(game, player, target):
            return f"AI road guard: target new_settle@{target} is no longer buildable/open."
        plan = build_ai_road_plan(game, player, candidates)
        if plan:
            return "AI road guard: route is allowed."
        return (
            f"AI road guard (S5a): no path/next road to new_settle@{target}; "
            "off-path roads blocked."
        )
    if way_wants_longest_road(player) and ai_road_longest_road_exception_active(game, player):
        return "AI road guard (S5a): LR claim edge available."
    try:
        from core.ai_lr_project import remaining_lr_project_roads

        if remaining_lr_project_roads(game, player):
            return "AI road guard (S-LR-A): LR project edges remaining."
    except Exception:
        pass
    if way_wants_longest_road(player):
        return (
            "AI road guard (S5a/S-LR-A): way wants LR but no live claim / "
            "no grow path in candidates; off-path blocked."
        )
    return "AI road guard (S5a): no strategy path and no live LR claim; do not build a generic road."
