"""P2: plan-relevance for dirty L2 flags (turn-start explore gate).

Default: L0 at turn start. L2 only when a *relevant* shock was flagged for
this seat (structure/road/LA/LR/robber/need_next). Pure hand / Q2 alone → no L2.

No full portfolio / no 142 ranking here — flag setting only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

# Align with Q2 last-DCard thin deck
DECK_THIN_K: int = 3


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _road_edge_key(edge: Any) -> Optional[Tuple[int, int]]:
    try:
        if isinstance(edge, Mapping):
            a = edge.get("a", edge.get(0, edge.get("from")))
            b = edge.get("b", edge.get(1, edge.get("to")))
            if a is None or b is None:
                vals = list(edge.values())[:2]
                if len(vals) >= 2:
                    a, b = vals[0], vals[1]
            return tuple(sorted((int(a), int(b))))  # type: ignore[return-value]
        if isinstance(edge, (list, tuple)) and len(edge) >= 2:
            return tuple(sorted((int(edge[0]), int(edge[1]))))  # type: ignore[return-value]
    except Exception:
        return None
    return None


def _add_roads_from_value(out: Set[Tuple[int, int]], raw: Any) -> None:
    if raw is None:
        return
    if isinstance(raw, Mapping) and "roads_to_build" in raw:
        raw = raw.get("roads_to_build")
    for item in list(raw or []):
        key = _road_edge_key(item)
        if key is not None:
            out.add(key)


def collect_plan_road_edges(player: Any) -> Set[Tuple[int, int]]:
    """Edges on sticky / preferred plan (locked roads, LR project, direction)."""
    out: Set[Tuple[int, int]] = set()
    if player is None:
        return out
    sticky = getattr(player, "sticky_commitment", None)
    if isinstance(sticky, Mapping):
        _add_roads_from_value(out, sticky.get("locked_roads_to_build"))
        _add_roads_from_value(out, sticky.get("roads_to_build"))
        lr = sticky.get("lr_project")
        if isinstance(lr, Mapping):
            _add_roads_from_value(out, lr.get("roads_to_build"))
            _add_roads_from_value(out, lr.get("remaining_roads_to_build"))
    direction = getattr(player, "strategic_direction", None)
    if isinstance(direction, Mapping):
        for key in (
            "roads_to_build",
            "locked_roads_to_build",
            "supporting_action_roads_to_build",
            "next_roads",
            "remaining_roads_to_build",
        ):
            _add_roads_from_value(out, direction.get(key))
        pt = direction.get("project_target")
        if isinstance(pt, Mapping):
            _add_roads_from_value(out, pt.get("roads_to_build"))
    return out


def collect_plan_structure_ids(player: Any, game: Any = None) -> Set[int]:
    """Structure intersection ids on sticky / preferred way (reuse Q1)."""
    try:
        from core.strategy_offway_q1 import collect_on_way_structure_ids

        return set(collect_on_way_structure_ids(player, game))
    except Exception:
        out: Set[int] = set()
        for src in (
            getattr(player, "sticky_commitment", None),
            getattr(player, "strategic_direction", None),
        ):
            if not isinstance(src, Mapping):
                continue
            for key in (
                "locked_rec_target_id",
                "recommendation_target_id",
                "settlement_target_id",
                "new_settlement_target_id",
                "target_id",
            ):
                tid = _safe_int(src.get(key), None)
                if tid is not None and tid >= 0:
                    out.add(int(tid))
        return out


def player_pursues_lr(player: Any) -> bool:
    try:
        from core.strategy_sticky import _player_pursues_longest_road

        return bool(_player_pursues_longest_road(player))
    except Exception:
        pass
    sticky = getattr(player, "sticky_commitment", None)
    if isinstance(sticky, Mapping) and isinstance(sticky.get("lr_project"), Mapping):
        lr = sticky.get("lr_project") or {}
        if lr.get("roads_to_build") or lr.get("active"):
            return True
    return False


def player_pursues_la(player: Any) -> bool:
    try:
        from core.strategy_sticky import _player_pursues_largest_army

        if bool(_player_pursues_largest_army(player)):
            return True
    except Exception:
        pass
    try:
        from core.ai_la_progress import way_wants_largest_army

        if way_wants_largest_army(player):
            return True
    except Exception:
        pass
    sticky = getattr(player, "sticky_commitment", None)
    if isinstance(sticky, Mapping) and sticky.get("la_progress"):
        return True
    return False


def collect_plan_relevance(player: Any, game: Any = None) -> Dict[str, Any]:
    """Cheap plan fingerprint for dirty-flag gating."""
    structs = collect_plan_structure_ids(player, game)
    roads = collect_plan_road_edges(player)
    return {
        "structure_ids": structs,
        "road_edges": roads,
        "pursues_lr": player_pursues_lr(player),
        "pursues_la": player_pursues_la(player),
        "has_plan": bool(structs or roads or player_pursues_lr(player) or player_pursues_la(player)),
    }


def structure_relevant_to_player(
    player: Any,
    target_id: Any,
    game: Any = None,
) -> bool:
    """True if opp settle/city at target_id matters to this seat's plan."""
    tid = _safe_int(target_id, None)
    if tid is None:
        # Unknown site: only dirty if seat has *no* plan yet (cold) — prefer skip
        # to avoid global thrash (P2). Callers may still invalidate cache.
        return False
    plan_ids = collect_plan_structure_ids(player, game)
    if tid in plan_ids:
        return True
    # Adjacent to plan site (v1.1 lite): share any board edge with a plan id
    if plan_ids and game is not None:
        try:
            board = getattr(game, "board", None)
            if board is not None and hasattr(board, "get_neighbors"):
                for pid in plan_ids:
                    try:
                        neigh = board.get_neighbors(int(pid))
                        if tid in {int(n) for n in list(neigh or [])}:
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
    return False


def road_relevant_to_player(
    player: Any,
    road_id: Any,
    game: Any = None,
) -> bool:
    """True if opp road hits plan edges or LR project (not every road for LR-chasers)."""
    edge = _road_edge_key(road_id)
    plan_edges = collect_plan_road_edges(player)
    if edge is not None and edge in plan_edges:
        return True
    if not player_pursues_lr(player):
        return False
    # LR pursuer: only if edge is on sticky LR project (or plan edges empty →
    # conservatively flag LR pursuers when we cannot match edges)
    sticky = getattr(player, "sticky_commitment", None)
    lr_edges: Set[Tuple[int, int]] = set()
    if isinstance(sticky, Mapping):
        lr = sticky.get("lr_project")
        if isinstance(lr, Mapping):
            _add_roads_from_value(lr_edges, lr.get("roads_to_build"))
            _add_roads_from_value(lr_edges, lr.get("remaining_roads_to_build"))
    if edge is not None and edge in lr_edges:
        return True
    # No explicit LR edges stored: fall back to "any road dirties LR pursuers"
    # only when plan_edges and lr_edges are both empty (legacy LR soft path).
    if not plan_edges and not lr_edges and edge is not None:
        return True
    return False


def _deck_remaining(game: Any) -> Optional[int]:
    if game is None:
        return None
    for attr in ("dcards_stack", "development_card_deck", "dcard_deck"):
        try:
            stack = getattr(game, attr, None)
            if isinstance(stack, (list, tuple)):
                return len(stack)
            if isinstance(stack, int):
                return max(0, int(stack))
        except Exception:
            pass
    return None


def _table_la_pressure(game: Any) -> bool:
    try:
        for p in list(getattr(game, "players", None) or []):
            army = int(
                getattr(p, "largest_army_size", 0)
                or getattr(p, "army_size", 0)
                or getattr(p, "knights_played", 0)
                or 0
            )
            if army >= 2:
                return True
    except Exception:
        pass
    return False


def dcard_buy_relevant_to_player(
    player: Any,
    game: Any = None,
    buyer: Any = None,
) -> bool:
    """Opp DCard buy: dirty only if we pursue LA or thin contested deck + LA care."""
    if player_pursues_la(player):
        return True
    deck = _deck_remaining(game)
    if deck is not None and deck <= int(DECK_THIN_K) and player_pursues_la(player):
        return True
    if deck is not None and deck <= int(DECK_THIN_K) and _table_la_pressure(game):
        # Thin deck + table army pressure: only seats that already pursue LA
        # (above) — non-LA seats stay quiet.
        return False
    return False


def robber_relevant_to_player(
    player: Any,
    tile_id: Any,
    game: Any = None,
) -> bool:
    """Robber on our production hex or plan-path hex → dirty; else not."""
    tid = _safe_int(tile_id, None)
    if tid is None or player is None:
        return False
    # Production: player settlements/cities adjacent to tile
    try:
        board = getattr(game, "board", None) if game is not None else None
        settlements = list(getattr(player, "settlements", None) or [])
        cities = list(getattr(player, "cities", None) or [])
        owned = set()
        for x in settlements + cities:
            i = _safe_int(x, None)
            if i is not None:
                owned.add(i)
        if board is not None and owned:
            # tile → intersection list
            tile_intersections = None
            for attr in ("get_tile_intersections", "tile_intersections"):
                fn = getattr(board, attr, None)
                if callable(fn):
                    try:
                        tile_intersections = fn(tid)
                        break
                    except Exception:
                        pass
            if tile_intersections is None:
                tiles = getattr(board, "tiles", None) or getattr(board, "hexes", None)
                if isinstance(tiles, Mapping):
                    t = tiles.get(tid) or tiles.get(str(tid))
                    if isinstance(t, Mapping):
                        tile_intersections = t.get("intersections") or t.get("nodes")
                    elif t is not None:
                        tile_intersections = getattr(t, "intersections", None) or getattr(
                            t, "nodes", None
                        )
            if tile_intersections:
                for n in list(tile_intersections):
                    ni = _safe_int(n, None)
                    if ni is not None and ni in owned:
                        return True
    except Exception:
        pass
    # Plan path: if any plan structure is on this tile's nodes
    plan_ids = collect_plan_structure_ids(player, game)
    if plan_ids and game is not None:
        try:
            board = getattr(game, "board", None)
            if board is not None:
                fn = getattr(board, "get_tile_intersections", None)
                nodes = fn(tid) if callable(fn) else None
                if nodes:
                    for n in list(nodes):
                        ni = _safe_int(n, None)
                        if ni is not None and ni in plan_ids:
                            return True
        except Exception:
            pass
    return False


def flag_opponents_after_robber(
    game: Any,
    mover: Any,
    *,
    tile_id: Any = None,
) -> Dict[str, Any]:
    """P2-8: flag seats for whom robber tile is plan/production relevant."""
    from core.strategy_sticky import flag_strategy_recalc

    reason = "opponent_robber"
    mover_id = _safe_int(getattr(mover, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (mover_id is not None and pid == mover_id):
            continue
        if not robber_relevant_to_player(p, tile_id, game):
            skipped.append(int(pid))
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=mover_id,
            detail={"tile_id": tile_id, "structure": "robber"},
        )
        flagged.append(int(pid))
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(game, f"robber:{reason}")
    except Exception:
        pass
    return {
        "reason": reason,
        "builder_id": mover_id,
        "flagged_player_ids": flagged,
        "skipped_irrelevant_player_ids": skipped,
        "tile_id": tile_id,
    }


def mark_q2_bought_this_turn(player: Any) -> None:
    """Analytics only — must not set L2 flags (P2-5)."""
    if player is None:
        return
    try:
        setattr(player, "q2_bought_this_turn", True)
    except Exception:
        pass


def clear_turn_ephemeral_dirty(player: Any) -> None:
    if player is None:
        return
    try:
        setattr(player, "q2_bought_this_turn", False)
    except Exception:
        pass
    try:
        # Q2 permission recomputed each rescan; clear stale allow on turn advance
        setattr(player, "q2_offway_dcard", None)
    except Exception:
        pass
