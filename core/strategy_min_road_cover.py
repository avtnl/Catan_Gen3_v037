"""Minimum legal empty-road cover for remaining new settlements (L2 victory need).

Operator lock (improving_SE_v5 / chat 2026-08-21):
  - When forming RCard need to Victory, choose settle *sites on the current
    playboard* so total empty roads is minimized.
  - Roads/settles must be Catan-legal (no path through opponent S/C).
  - Do **not** plan S/C/road *sequence* or LA/LR here — re-run L2 after each
    successful new settle/city.

Approximation: greedy sequential closest-site expansion (depth ≤ 3).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

Edge = Tuple[int, int]


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _norm_edge(raw: Any) -> Optional[Edge]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            a, b = int(raw[0]), int(raw[1])
            return (min(a, b), max(a, b))
        except Exception:
            return None
    return None


def legal_settle_sites(game: Any, player: Any) -> List[int]:
    """Open settlement intersections for *player* on the current playboard."""
    try:
        from core.outlook_logic import new_settlement_spots

        pid = int(getattr(player, "id"))
        return [int(x) for x in (new_settlement_spots(game, pid) or [])]
    except Exception:
        pass
    # Fallback: board intersections open for settle
    out: List[int] = []
    try:
        from core.risk_assessment import _intersection_open_for_settle

        board = getattr(game, "board", None)
        for inter in list(getattr(board, "intersections", None) or []):
            if inter is None:
                continue
            iid = _safe_int(getattr(inter, "id", None), None)
            if iid is None:
                continue
            if _intersection_open_for_settle(game, iid):
                out.append(int(iid))
    except Exception:
        pass
    return out


def min_roads_to_place_n_settlements(
    game: Any,
    player: Any,
    n_settlements: int,
    *,
    max_distance: int = 3,
) -> Dict[str, Any]:
    """Greedy min empty-road cover for *n_settlements* legal sites.

    Returns ``roads_needed``, ``sites`` (chosen intersection ids), ``paths``
    (list of road-id lists), ``ok``.
    """
    n = max(0, int(n_settlements or 0))
    out: Dict[str, Any] = {
        "ok": True,
        "roads_needed": 0,
        "sites": [],
        "paths": [],
        "unreachable": 0,
        "n_requested": n,
    }
    if n <= 0 or game is None or player is None:
        return out

    try:
        max_distance = max(1, min(3, int(max_distance)))
    except Exception:
        max_distance = 3

    sites_pool = legal_settle_sites(game, player)
    if not sites_pool:
        out["ok"] = False
        out["unreachable"] = n
        out["roads_needed"] = 0
        return out

    # Distance + path from current network (maps → outlook → BFS)
    try:
        from core.risk_assessment import _min_empty_roads_to_reach
        from core.outlook_logic import find_reachable_new_settlement_paths
    except Exception:
        out["ok"] = False
        return out

    try:
        from core.constants import REACHABILITY_MAPS
        from core.player_reachability import ensure_reachability_maps

        if bool(REACHABILITY_MAPS):
            ensure_reachability_maps(game, player)
    except Exception:
        pass

    # Expandable virtual network: start from owned S/C
    owned: Set[int] = set()
    try:
        owned.update(int(x) for x in list(getattr(player, "settlements", []) or []))
        owned.update(int(x) for x in list(getattr(player, "cities", []) or []))
    except Exception:
        owned = set()

    remaining_pool = set(int(x) for x in sites_pool)
    chosen: List[int] = []
    paths: List[List[Edge]] = []
    total_roads = 0

    for _ in range(n):
        if not remaining_pool:
            out["unreachable"] = n - len(chosen)
            out["ok"] = False
            break

        best_tid: Optional[int] = None
        best_dist: Optional[int] = None
        best_path: List[Edge] = []

        by_tid: Dict[int, Dict[str, Any]] = {}

        # First pick: prefer per-player reachability maps (independent tips; no
        # multi-target BFS stop-at-nearer quirk). Later picks need virtual
        # expansion past chosen sites — maps alone are insufficient then.
        if not chosen:
            try:
                from core.constants import REACHABILITY_MAPS
                from core.player_reachability import (
                    SENTINEL,
                    maps_are_fresh,
                    path_to_target,
                    remaining_roads_to_target,
                )

                if bool(REACHABILITY_MAPS) and maps_are_fresh(player):
                    for tid in list(remaining_pool):
                        rd = remaining_roads_to_target(player, int(tid))
                        if rd is None or int(rd) >= SENTINEL or int(rd) < 1:
                            continue
                        if int(rd) > max_distance:
                            continue
                        roads: List[Edge] = []
                        for raw in path_to_target(player, int(tid)):
                            e = _norm_edge(raw)
                            if e:
                                roads.append(e)
                        by_tid[int(tid)] = {
                            "dist": int(rd),
                            "roads": roads,
                            "source": "reachability_map",
                        }
            except Exception:
                pass

        missing = [t for t in remaining_pool if int(t) not in by_tid]
        if missing:
            try:
                path_rows = find_reachable_new_settlement_paths(
                    game,
                    player,
                    target_ids=list(missing),
                    max_distance=max_distance,
                )
            except Exception:
                path_rows = []
            for row in path_rows or []:
                if not isinstance(row, Mapping):
                    continue
                tid = _safe_int(
                    row.get("target_settlement_id")
                    or row.get("intersection_id")
                    or row.get("target_id"),
                    None,
                )
                if tid is None or tid not in remaining_pool:
                    continue
                dist = _safe_int(row.get("roads_remaining", row.get("distance")), None)
                roads = []
                for raw in list(row.get("roads_to_build") or []):
                    e = _norm_edge(raw)
                    if e:
                        roads.append(e)
                if dist is None:
                    dist = len(roads) if roads else None
                if dist is None:
                    continue
                prev = by_tid.get(int(tid))
                if prev is None or int(dist) < int(prev.get("dist") or 99):
                    by_tid[int(tid)] = {
                        "dist": int(dist),
                        "roads": roads,
                        "source": str(row.get("route_source") or "outlook"),
                    }

        for tid in list(remaining_pool):
            if tid in by_tid:
                dist = int(by_tid[tid]["dist"])
                roads = list(by_tid[tid]["roads"])
            else:
                # Virtual expansion: measure from owned ∪ chosen as if connected
                # Approximate by BFS from real player network only on first picks;
                # after choosing a site, we fake-expand owned for next iteration.
                dist_r = _min_empty_roads_to_reach(
                    game, player, int(tid), max_depth=max_distance
                )
                if dist_r is None:
                    continue
                dist = int(dist_r)
                roads = []
            # Adjust: if we already "placed" closer sites, distance from expanded
            # network may be shorter — recompute using chosen as extra starts via
            # a lightweight override when chosen non-empty.
            if chosen:
                dist2 = _dist_from_expanded_network(
                    game, player, int(tid), owned | set(chosen), max_depth=max_distance
                )
                if dist2 is not None and dist2 < dist:
                    dist = int(dist2)
                    roads = []
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_tid = int(tid)
                best_path = roads

        if best_tid is None or best_dist is None:
            out["unreachable"] = n - len(chosen)
            out["ok"] = False
            break

        chosen.append(best_tid)
        remaining_pool.discard(best_tid)
        total_roads += int(best_dist)
        paths.append(list(best_path))
        owned.add(best_tid)

    out["sites"] = chosen
    out["paths"] = paths
    out["roads_needed"] = int(total_roads)
    out["n_placed"] = len(chosen)
    return out


def _dist_from_expanded_network(
    game: Any,
    player: Any,
    target: int,
    network_nodes: Set[int],
    *,
    max_depth: int,
) -> Optional[int]:
    """BFS distance treating *network_nodes* as already connected (virtual settles)."""
    if int(target) in network_nodes:
        return 0
    try:
        from core.risk_assessment import (
            _empty_road_adjacency,
            _vertex_blocked_for_road_path,
        )
    except Exception:
        return None
    from collections import deque

    adj = _empty_road_adjacency(game)
    q: deque = deque()
    seen: Set[int] = set(int(x) for x in network_nodes)
    for n in list(seen):
        q.append((n, 0))
    while q:
        node, dist = q.popleft()
        if dist >= max_depth:
            continue
        for nxt in adj.get(node, []):
            if nxt in seen:
                continue
            if nxt != int(target) and _vertex_blocked_for_road_path(game, player, nxt):
                continue
            nd = dist + 1
            if nxt == int(target):
                return nd
            if nd < max_depth:
                seen.add(nxt)
                q.append((nxt, nd))
    return None


def victory_structure_road_need(
    game: Any,
    player: Any,
    *,
    remaining_new_settlements: int,
    remaining_city_upgrades: int = 0,
    max_distance: int = 3,
) -> Dict[str, Any]:
    """Roads needed for victory RCard vector (settles only; cities add 0 roads).

    City upgrades are assumed on existing (or already-planned) settle bases;
    sequence of upgrades is **not** planned — L2 refreshes after each build.
    """
    _ = remaining_city_upgrades  # documented no-op for road mass
    cover = min_roads_to_place_n_settlements(
        game,
        player,
        int(remaining_new_settlements or 0),
        max_distance=max_distance,
    )
    return {
        "roads_needed": int(cover.get("roads_needed") or 0),
        "sites": list(cover.get("sites") or []),
        "paths": list(cover.get("paths") or []),
        "ok": bool(cover.get("ok")),
        "unreachable": int(cover.get("unreachable") or 0),
        "cover": cover,
    }


__all__ = [
    "legal_settle_sites",
    "min_roads_to_place_n_settlements",
    "victory_structure_road_need",
]
