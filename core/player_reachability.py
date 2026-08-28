"""Per-player reachability matrices (Gen2-style path / pathlength / real_distance).

Gen3 ``Player`` already allocates 67×67 maps and save/loads them, but historically
never rebuilt them. This module owns rebuild + incremental invalidate and the
query façade used by Strategy-Engine callers.

Axes (per player):
  rows (starts) = own S/C ∪ endpoints of own roads
  cols (ends)   = still-legal settle intersections for this player

Horizon: store sentinel 99 / [] when pathlength or real_distance ≥ 5.

Product metric for EH / race / min-cover: ``real_distance`` = roads still to build
on the best free path (own roads on the path are credited).

See ``docs/player_reachability_maps_plan.md``.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

MAP_SIZE = 67
HORIZON = 5
SENTINEL = 99

RoadKey = Tuple[int, int]


def _flag_enabled() -> bool:
    try:
        from core.constants import REACHABILITY_MAPS

        return bool(REACHABILITY_MAPS)
    except Exception:
        return True


def _normalise_road_key(road: Any) -> RoadKey:
    try:
        if isinstance(road, dict):
            for key in ("road_id", "road", "edge", "id"):
                if key in road:
                    return _normalise_road_key(road.get(key))
        values = list(road)[:2]
        if len(values) != 2:
            return ()  # type: ignore[return-value]
        a, b = int(values[0]), int(values[1])
        if a == b:
            return ()  # type: ignore[return-value]
        return (a, b) if a < b else (b, a)
    except Exception:
        return ()  # type: ignore[return-value]


def _player_colors(player: Any) -> Set[str]:
    colors = {str(getattr(player, "color", "") or "")}
    color2 = getattr(player, "color2", None)
    if color2:
        colors.add(str(color2))
    colors.discard("")
    return colors


def starts_for_player(game: Any, player: Any) -> List[int]:
    """Start TWs: own settlements/cities plus endpoints of own roads (Gen2 all_tws)."""
    nodes: Set[int] = set()
    try:
        for sid in list(getattr(player, "settlements", []) or []):
            nodes.add(int(sid))
        for cid in list(getattr(player, "cities", []) or []):
            nodes.add(int(cid))
    except Exception:
        pass
    colors = _player_colors(player)
    try:
        for road in list(getattr(player, "roads", []) or []):
            key = _normalise_road_key(road)
            if key and len(key) == 2:
                nodes.add(int(key[0]))
                nodes.add(int(key[1]))
    except Exception:
        pass
    board = getattr(game, "board", None)
    try:
        for road in list(getattr(board, "roads", []) or []):
            if not bool(getattr(road, "occupied_tf", False)):
                # Unoccupied: still count if listed on player.roads above
                continue
            if str(getattr(road, "color", "") or "") not in colors:
                continue
            key = _normalise_road_key(getattr(road, "id", None))
            if key and len(key) == 2:
                nodes.add(int(key[0]))
                nodes.add(int(key[1]))
    except Exception:
        pass
    return sorted(n for n in nodes if 0 <= n < MAP_SIZE)


def legal_settle_ends(game: Any, player: Any) -> List[int]:
    """Intersections still legal as a future settlement for this player."""
    from core.outlook_logic import future_settlement_target_is_open

    board = getattr(game, "board", None)
    if board is None:
        return []
    ends: List[int] = []
    water = set(getattr(board, "INTERSECTION_IN_WATER", []) or [])
    inters = list(getattr(board, "intersections", []) or [])
    for iid, inter in enumerate(inters):
        if inter is None:
            continue
        if iid in water:
            continue
        if 0 <= iid < MAP_SIZE and future_settlement_target_is_open(game, player, iid):
            ends.append(int(iid))
    return ends


def _owned_road_keys(game: Any, player: Any) -> Set[RoadKey]:
    from core.outlook_logic import player_owned_road_keys

    return set(player_owned_road_keys(game, player))


def _adjacency_empty_or_own(game: Any, player: Any) -> Dict[int, List[int]]:
    """Undirected graph: edges that are empty or owned by *player*."""
    from core.outlook_logic import board_road_map, road_is_empty_or_owned_by_player

    board = getattr(game, "board", None)
    adj: Dict[int, List[int]] = {}
    try:
        rmap = board_road_map(board)
    except Exception:
        rmap = {}
    for key in rmap:
        if not key or len(key) != 2:
            continue
        if not road_is_empty_or_owned_by_player(game, player, key):
            continue
        a, b = int(key[0]), int(key[1])
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    for k in adj:
        adj[k] = sorted(set(adj[k]))
    return adj


def _opponent_blocks_vertex(game: Any, player: Any, node_id: int, *, target: int) -> bool:
    from core.outlook_logic import intersection_has_opponent_structure

    if int(node_id) == int(target):
        return False
    return bool(intersection_has_opponent_structure(game, player, int(node_id)))


def _best_path_between(
    game: Any,
    player: Any,
    start: int,
    end: int,
    *,
    adj: Dict[int, List[int]],
    owned: Set[RoadKey],
    horizon: int = HORIZON,
) -> Optional[Dict[str, Any]]:
    """BFS for a free path start→end; prefer fewer remaining roads, then shorter pathlength.

    Returns dict with path (road keys), pathlength, real_distance — or None if
    unreachable within horizon.
    """
    start_i, end_i = int(start), int(end)
    if start_i == end_i:
        return {"path": [], "pathlength": 0, "real_distance": 0}

    # state: node, path_nodes
    queue: deque[Tuple[int, List[int]]] = deque()
    queue.append((start_i, [start_i]))
    # seen (node, depth) — depth = hops = pathlength
    seen: Set[Tuple[int, int]] = {(start_i, 0)}
    best: Optional[Dict[str, Any]] = None

    while queue:
        node, path_nodes = queue.popleft()
        depth = len(path_nodes) - 1
        if depth >= horizon:
            continue
        for nxt in adj.get(node, []):
            if nxt in path_nodes:
                continue
            if _opponent_blocks_vertex(game, player, nxt, target=end_i):
                continue
            new_nodes = path_nodes + [int(nxt)]
            new_depth = len(new_nodes) - 1
            state = (int(nxt), new_depth)
            if state in seen:
                continue
            seen.add(state)

            if int(nxt) == end_i:
                from core.outlook_logic import route_roads_from_nodes

                # Directed path steps start→end; ownership uses undirected road_id.
                all_roads = route_roads_from_nodes(new_nodes)
                pathlength = len(all_roads)
                real = sum(
                    1 for r in all_roads if _normalise_road_key(r) not in owned
                )
                if pathlength >= horizon or real >= horizon:
                    continue
                cand = {
                    "path": [list(r) for r in all_roads],
                    "pathlength": pathlength,
                    "real_distance": real,
                    "route_nodes": list(new_nodes),
                }
                if best is None or (real, pathlength) < (
                    int(best["real_distance"]),
                    int(best["pathlength"]),
                ):
                    best = cand
                continue

            if new_depth < horizon:
                queue.append((int(nxt), new_nodes))

    return best


def _ensure_map_shapes(player: Any) -> None:
    w = h = MAP_SIZE
    if not isinstance(getattr(player, "path_map", None), list) or len(player.path_map) != h:
        player.path_map = [[[] for _ in range(w)] for _ in range(h)]
    if not isinstance(getattr(player, "pathlength_map", None), list) or len(player.pathlength_map) != h:
        player.pathlength_map = [[SENTINEL for _ in range(w)] for _ in range(h)]
    if not isinstance(getattr(player, "real_distance_map", None), list) or len(player.real_distance_map) != h:
        player.real_distance_map = [[SENTINEL for _ in range(w)] for _ in range(h)]
    if not isinstance(getattr(player, "min_pathlength_map_for_targeted_TWs", None), list):
        player.min_pathlength_map_for_targeted_TWs = [SENTINEL] * h
    if not isinstance(getattr(player, "min_real_distance_map_for_targeted_TWs", None), list):
        player.min_real_distance_map_for_targeted_TWs = [SENTINEL] * h
    # Pad / trim min vectors
    for attr in (
        "min_pathlength_map_for_targeted_TWs",
        "min_real_distance_map_for_targeted_TWs",
        "min_distance_map_for_targeted_TWs",
    ):
        vec = getattr(player, attr, None)
        if not isinstance(vec, list):
            setattr(player, attr, [SENTINEL] * h)
        elif len(vec) < h:
            setattr(player, attr, list(vec) + [SENTINEL] * (h - len(vec)))
        elif len(vec) > h:
            setattr(player, attr, list(vec)[:h])


def _clear_maps(player: Any) -> None:
    _ensure_map_shapes(player)
    w = h = MAP_SIZE
    player.path_map = [[[] for _ in range(w)] for _ in range(h)]
    player.pathlength_map = [[SENTINEL for _ in range(w)] for _ in range(h)]
    player.real_distance_map = [[SENTINEL for _ in range(w)] for _ in range(h)]
    player.min_pathlength_map_for_targeted_TWs = [SENTINEL] * h
    player.min_real_distance_map_for_targeted_TWs = [SENTINEL] * h


def _recompute_min_vectors(player: Any, starts: Sequence[int], ends: Sequence[int]) -> None:
    h = MAP_SIZE
    min_pl = [SENTINEL] * h
    min_rd = [SENTINEL] * h
    for j in ends:
        best_pl = SENTINEL
        best_rd = SENTINEL
        for i in starts:
            try:
                pl = int(player.pathlength_map[i][j])
                rd = int(player.real_distance_map[i][j])
            except Exception:
                continue
            if pl < best_pl:
                best_pl = pl
            if rd < best_rd:
                best_rd = rd
        min_pl[j] = best_pl
        min_rd[j] = best_rd
    player.min_pathlength_map_for_targeted_TWs = min_pl
    player.min_real_distance_map_for_targeted_TWs = min_rd


def _fill_pair(
    game: Any,
    player: Any,
    start: int,
    end: int,
    *,
    adj: Dict[int, List[int]],
    owned: Set[RoadKey],
) -> None:
    i, j = int(start), int(end)
    if not (0 <= i < MAP_SIZE and 0 <= j < MAP_SIZE):
        return
    found = _best_path_between(game, player, i, j, adj=adj, owned=owned)
    if found is None:
        player.path_map[i][j] = []
        player.pathlength_map[i][j] = SENTINEL
        player.real_distance_map[i][j] = SENTINEL
        return
    player.path_map[i][j] = list(found["path"])
    player.pathlength_map[i][j] = int(found["pathlength"])
    player.real_distance_map[i][j] = int(found["real_distance"])


def rebuild_reachability_maps(game: Any, player: Any) -> Dict[str, Any]:
    """Full refresh of path / pathlength / real_distance maps for *player*.

    Returns a small summary dict (starts/ends counts, filled cells).
    """
    if player is None or getattr(game, "board", None) is None:
        return {"ok": False, "reason": "missing_player_or_board"}

    _clear_maps(player)
    starts = starts_for_player(game, player)
    ends = legal_settle_ends(game, player)
    if not starts or not ends:
        player._reachability_dirty = False  # type: ignore[attr-defined]
        player._reachability_starts = list(starts)  # type: ignore[attr-defined]
        player._reachability_ends = list(ends)  # type: ignore[attr-defined]
        return {
            "ok": True,
            "starts": len(starts),
            "ends": len(ends),
            "filled": 0,
            "horizon": HORIZON,
        }

    adj = _adjacency_empty_or_own(game, player)
    owned = _owned_road_keys(game, player)
    filled = 0
    for i in starts:
        for j in ends:
            _fill_pair(game, player, i, j, adj=adj, owned=owned)
            try:
                if int(player.real_distance_map[i][j]) < SENTINEL:
                    filled += 1
            except Exception:
                pass

    _recompute_min_vectors(player, starts, ends)
    player._reachability_dirty = False  # type: ignore[attr-defined]
    player._reachability_starts = list(starts)  # type: ignore[attr-defined]
    player._reachability_ends = list(ends)  # type: ignore[attr-defined]
    return {
        "ok": True,
        "starts": len(starts),
        "ends": len(ends),
        "filled": filled,
        "horizon": HORIZON,
    }


def maps_are_fresh(player: Any) -> bool:
    """True when maps exist and are not marked dirty."""
    if player is None:
        return False
    if bool(getattr(player, "_reachability_dirty", True)):
        return False
    try:
        rd = player.real_distance_map
        if not isinstance(rd, list) or len(rd) < MAP_SIZE:
            return False
    except Exception:
        return False
    return True


def remaining_roads_to_target(player: Any, tid: int) -> int:
    """Best ``min_real_distance`` to tip *tid*, or SENTINEL if unknown."""
    try:
        j = int(tid)
    except Exception:
        return SENTINEL
    if not (0 <= j < MAP_SIZE):
        return SENTINEL
    try:
        vec = getattr(player, "min_real_distance_map_for_targeted_TWs", None)
        if isinstance(vec, list) and j < len(vec):
            return int(vec[j])
    except Exception:
        pass
    return SENTINEL


def path_to_target(player: Any, tid: int) -> List[List[int]]:
    """Best ``path_map`` row (by real_distance, then pathlength) to tip *tid*."""
    try:
        j = int(tid)
    except Exception:
        return []
    if not (0 <= j < MAP_SIZE):
        return []
    starts = list(getattr(player, "_reachability_starts", None) or [])
    if not starts:
        # Fallback: scan all rows that have a non-sentinel real_distance
        try:
            starts = [
                i
                for i in range(MAP_SIZE)
                if int(player.real_distance_map[i][j]) < SENTINEL
            ]
        except Exception:
            return []
    best_path: List[List[int]] = []
    best_key = (SENTINEL, SENTINEL)
    for i in starts:
        try:
            rd = int(player.real_distance_map[i][j])
            pl = int(player.pathlength_map[i][j])
        except Exception:
            continue
        if rd >= SENTINEL:
            continue
        key = (rd, pl)
        if key < best_key:
            best_key = key
            try:
                raw = player.path_map[i][j] or []
                best_path = [list(r) for r in raw]
            except Exception:
                best_path = []
    return best_path


# ── Incremental API (WP-R2: correct via full rebuild stubs first) ─────────────


def update_after_own_road(game: Any, player: Any, road: Any) -> Dict[str, Any]:
    """Refresh maps after this player builds *road* (v1: full rebuild)."""
    _ = road
    if not _flag_enabled():
        return {"ok": False, "reason": "flag_off"}
    return rebuild_reachability_maps(game, player)


def update_after_own_settlement(game: Any, player: Any, tid: int) -> Dict[str, Any]:
    """Amend maps after this player settles at *tid* (v1: full rebuild)."""
    _ = tid
    if not _flag_enabled():
        return {"ok": False, "reason": "flag_off"}
    return rebuild_reachability_maps(game, player)


def invalidate_after_opponent_road(game: Any, viewer: Any, road: Any) -> Dict[str, Any]:
    """Invalidate *viewer* maps after an opponent builds *road* (v1: full rebuild)."""
    _ = road
    if not _flag_enabled():
        return {"ok": False, "reason": "flag_off"}
    return rebuild_reachability_maps(game, viewer)


def invalidate_after_opponent_settlement(game: Any, viewer: Any, tid: int) -> Dict[str, Any]:
    """Invalidate *viewer* maps after an opponent settles at *tid* (v1: full rebuild)."""
    _ = tid
    if not _flag_enabled():
        return {"ok": False, "reason": "flag_off"}
    return rebuild_reachability_maps(game, viewer)


def mark_dirty(player: Any) -> None:
    """Mark maps stale so callers fall back to BFS until rebuild."""
    if player is not None:
        player._reachability_dirty = True  # type: ignore[attr-defined]


def should_maintain_maps(player: Any) -> bool:
    """AI always (when flag on); human seats when Check-Mode / Dig needs geometry."""
    if not _flag_enabled() or player is None:
        return False
    if not bool(getattr(player, "is_human", False)):
        return True
    try:
        from core.debug_mode import is_check_mode

        return bool(is_check_mode())
    except Exception:
        try:
            from core.constants import CHECK_MODE

            return bool(CHECK_MODE)
        except Exception:
            return False


def ensure_reachability_maps(game: Any, player: Any) -> Dict[str, Any]:
    """Rebuild *player* maps if missing/dirty and maintenance is enabled."""
    if not should_maintain_maps(player):
        return {"ok": False, "reason": "skip_seat"}
    if maps_are_fresh(player):
        return {"ok": True, "reason": "fresh"}
    return rebuild_reachability_maps(game, player)


def ensure_dig_seat_maps(game: Any, player: Any) -> Dict[str, Any]:
    """WP-R5: Dig/Check-Mode may rebuild maps for the **displayed** seat.

    Unlike ``ensure_reachability_maps``, human seats are included when Dig needs
    geometry (scrub / Show), even if ``CHECK_MODE`` is off for product AI-only
    maintenance. No-op when ``REACHABILITY_MAPS`` is False.
    """
    if not _flag_enabled() or player is None or getattr(game, "board", None) is None:
        return {"ok": False, "reason": "skip"}
    if maps_are_fresh(player):
        return {"ok": True, "reason": "fresh", "dig": True}
    out = rebuild_reachability_maps(game, player)
    if isinstance(out, dict):
        out = dict(out)
        out["dig"] = True
    return out


def sc_hop_distance(player: Any, tid: int) -> Optional[int]:
    """Best pathlength from own S/C starts to *tid* (PLN2 hop), or None."""
    try:
        j = int(tid)
    except Exception:
        return None
    if not (0 <= j < MAP_SIZE):
        return None
    starts: List[int] = []
    try:
        starts.extend(int(x) for x in list(getattr(player, "settlements", []) or []))
        starts.extend(int(x) for x in list(getattr(player, "cities", []) or []))
    except Exception:
        return None
    if not starts:
        return None
    pl_map = getattr(player, "pathlength_map", None)
    best = SENTINEL
    for s in starts:
        try:
            pl = int(pl_map[int(s)][j])
        except Exception:
            continue
        if pl < best:
            best = pl
    if best >= SENTINEL:
        return None
    return int(best)


def rebuild_all_maintained_seats(game: Any) -> Dict[str, Any]:
    """Full rebuild for every seat that should maintain maps (post-IP / load)."""
    results: List[Dict[str, Any]] = []
    for p in list(getattr(game, "players", None) or []):
        if not should_maintain_maps(p):
            continue
        results.append({"player_id": getattr(p, "id", None), **rebuild_reachability_maps(game, p)})
    return {"ok": True, "seats": results}


def notify_settlement_built(game: Any, builder: Any, tid: int) -> Dict[str, Any]:
    """Own settle amend + opponent invalidate for maintained seats."""
    if not _flag_enabled():
        return {"ok": False, "reason": "flag_off"}
    own = None
    others: List[Dict[str, Any]] = []
    if should_maintain_maps(builder):
        own = update_after_own_settlement(game, builder, tid)
    builder_id = getattr(builder, "id", None)
    for p in list(getattr(game, "players", None) or []):
        if p is None or getattr(p, "id", None) == builder_id:
            continue
        if not should_maintain_maps(p):
            continue
        others.append(
            {
                "player_id": getattr(p, "id", None),
                **invalidate_after_opponent_settlement(game, p, tid),
            }
        )
    return {"ok": True, "own": own, "others": others, "tid": tid}


def notify_road_built(game: Any, builder: Any, road: Any) -> Dict[str, Any]:
    """Own road refresh + opponent invalidate for maintained seats."""
    if not _flag_enabled():
        return {"ok": False, "reason": "flag_off"}
    own = None
    others: List[Dict[str, Any]] = []
    if should_maintain_maps(builder):
        own = update_after_own_road(game, builder, road)
    builder_id = getattr(builder, "id", None)
    for p in list(getattr(game, "players", None) or []):
        if p is None or getattr(p, "id", None) == builder_id:
            continue
        if not should_maintain_maps(p):
            continue
        others.append(
            {
                "player_id": getattr(p, "id", None),
                **invalidate_after_opponent_road(game, p, road),
            }
        )
    return {"ok": True, "own": own, "others": others}


__all__ = [
    "MAP_SIZE",
    "HORIZON",
    "SENTINEL",
    "starts_for_player",
    "legal_settle_ends",
    "rebuild_reachability_maps",
    "ensure_reachability_maps",
    "ensure_dig_seat_maps",
    "rebuild_all_maintained_seats",
    "should_maintain_maps",
    "maps_are_fresh",
    "mark_dirty",
    "remaining_roads_to_target",
    "path_to_target",
    "sc_hop_distance",
    "update_after_own_road",
    "update_after_own_settlement",
    "invalidate_after_opponent_road",
    "invalidate_after_opponent_settlement",
    "notify_road_built",
    "notify_settlement_built",
]

