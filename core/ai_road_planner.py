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


def _build_lr_claim_road_plan(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """S5a: single-edge plan when that edge takes/steals LR and way wants LR."""
    if not way_wants_longest_road(player):
        return {}
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
    checked = 0
    for key in edges:
        if checked >= 12:
            break
        checked += 1
        if road_is_live_lr_claim_edge(game, player, key):
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

    ``commit_project=False``: plan only (no sticky/project store). Used by
    ``road_allowed_for_ai`` so a guard probe cannot arm a random grow path.
    """
    if not ai_road_guard_applies(game, player):
        return {}

    legal_candidates = [dict(c) for c in list(candidates or []) if isinstance(c, Mapping)]
    legal_roads = candidate_road_set(legal_candidates)
    owned = player_owned_road_keys(game, player)

    # --- 1) Live 1-edge LR claim ---
    lr_claim = _build_lr_claim_road_plan(game, player, legal_candidates)
    if lr_claim:
        if commit_project:
            try:
                from core.ai_lr_project import store_lr_project

                nr = _road_key_from_any(
                    lr_claim.get("next_road")
                    or (list(lr_claim.get("roads_to_build") or [None])[0])
                )
                if nr:
                    store_lr_project(
                        game,
                        player,
                        {
                            "kind": "lr_claim",
                            "roads_to_build": [list(nr)],
                            "next_road": list(nr),
                            "claim_after_n": 1,
                            "takes_now": True,
                            "route_source": lr_claim.get("route_source"),
                            "strategy_reason": lr_claim.get("strategy_reason"),
                            "target_label": "LR claim",
                        },
                    )
            except Exception:
                pass
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
            if not legal_roads or first in legal_roads:
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
            # First honour sticky/strategy route.
            raw_roads = [_road_key_from_any(r) for r in list(strategy_plan.get("roads_to_build", []) or [])]
            raw_roads = [r for r in raw_roads if r]
            if raw_roads:
                roads_to_build = [r for r in raw_roads if r not in owned]
                if roads_to_build and len(roads_to_build) <= MAX_AI_SETTLEMENT_ROAD_DISTANCE:
                    first_road = roads_to_build[0]
                    if (
                        (not legal_roads or first_road in legal_roads)
                        and route_path_is_clear_for_player(game, player, raw_roads, target_id)
                    ):
                        scored = score_new_settlement_road_path(
                            game,
                            player,
                            dict(strategy_plan)
                            | {
                                "route_all_roads": raw_roads,
                                "roads_to_build": roads_to_build,
                                "next_road": first_road,
                                "route_source": "s5a_sticky_or_strategy_path",
                            },
                        )
                        if not scored.get("blocked"):
                            return scored

            # If strategy only supplies the settlement target, discover short paths.
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
            if first and (not legal_roads or first in legal_roads):
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
