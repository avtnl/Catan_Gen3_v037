"""
core/outlook_logic.py

Outlook calculations for Execution: next/new settlement/city/road targets.
"""

from typing import List, Set, Dict, Optional, Tuple, Any, Sequence

def next_settlement_spots(game: "Game", player_id: int) -> List[int]:
    """
    Return all viable intersections where the player can build a next settlement.

    Rules enforced:
        a) intersection is not occupied
        b) distance rule is satisfied
        c) intersection is connected to at least one road already on the board
           and owned by this player

    Ownership convention:
        - road.color == player.color is the canonical check.
        - player.color2 is accepted only as a defensive fallback, because
          Player currently initializes color2 equal to color.
    """

    player = next((p for p in game.players if p.id == player_id), None)
    board = game.board

    player_colors = {player.color}
    if getattr(player, "color2", None):
        player_colors.add(player.color2)

    # ────────────────────────────────────────────────
    # 1. Find all open endpoints of roads owned by this player
    # ────────────────────────────────────────────────
    tws_in_reach = set()

    for road in getattr(board, "roads", []):
        if road is None:
            continue
        if not getattr(road, "occupied_tf", False):
            continue
        if getattr(road, "color", None) not in player_colors:
            continue

        road_id = tuple(sorted(getattr(road, "id", ())))
        if len(road_id) != 2:
            continue

        tws_in_reach.update(road_id)

    # No owned roads → no normal next settlement spots
    if not tws_in_reach:
        return []

    # ────────────────────────────────────────────────
    # 2. Filter those endpoints by buildability
    # ────────────────────────────────────────────────
    candidates: List[int] = []

    for inter_id in sorted(tws_in_reach):
        if not (0 <= inter_id < len(board.intersections)):
            continue

        inter = board.intersections[inter_id]

        # Invalid / water intersection
        if inter is None:
            continue
        if inter_id in board.INTERSECTION_IN_WATER:
            continue

        # a) Not already occupied
        if getattr(inter, "occupied_tf", False):
            continue

        # Respect can_build_tf / canbuildYNX if present.
        # can_build_tf is boolean in your current Intersection class.
        can_build_flag = getattr(inter, "can_build_tf", True)
        if can_build_flag is False:
            continue

        legacy_flag = getattr(inter, "canbuildYNX", "Y")
        if legacy_flag == "X" or legacy_flag == "N":
            continue

        # b) Distance rule:
        # reject if any directly adjacent intersection is occupied.
        distance_ok = True
        for neighbor_id in getattr(inter, "three_intersection_ids", []):
            if not (0 <= neighbor_id < len(board.intersections)):
                continue
            if neighbor_id in board.INTERSECTION_IN_WATER:
                continue

            neighbor = board.intersections[neighbor_id]
            if neighbor is not None and getattr(neighbor, "occupied_tf", False):
                distance_ok = False
                break

        if not distance_ok:
            continue

        # c) Must touch at least one currently occupied road owned by this player.
        # This looks redundant because tws_in_reach came from owned roads,
        # but keeping this check protects against stale/malformed road data.
        connected_to_own_road = False
        for road_tuple in getattr(inter, "three_roads", []):
            road_id = tuple(sorted(road_tuple))

            road = next(
                (
                    r for r in board.roads
                    if r is not None
                    and tuple(sorted(getattr(r, "id", ()))) == road_id
                    and getattr(r, "occupied_tf", False)
                    and getattr(r, "color", None) in player_colors
                ),
                None
            )

            if road is not None:
                connected_to_own_road = True
                break

        if not connected_to_own_road:
            continue

        candidates.append(inter_id)

    return candidates

def new_settlement_spots(game: "Game", player_id: int) -> List[int]:
    """
    Return all viable NEW-settlement candidates at hop distance 2 or 3.

    Operator procedure (2026-08-21) — implemented literally:

      Step 1  For each existing own settlement **or city**, collect every
              intersection whose **board** graph distance from that building
              is exactly 2 or exactly 3. (d=1 is illegal under Catan.)
      Step 2  Drop potentials that are unavailable or violate the Catan
              distance rule (occupied / adjacent to any S or C / water / …).
      Step 3  Keep only those that still have **at least one viable path**
              of hop length 2 or 3 from that same building: every road on the
              path empty or own; intermediate opponent S/C blocks. Multiple
              paths may exist — existence is enough for candidacy (path pick
              is road_optimizer / pathfinder later).
      Step 4  Repeat for the next own S/C.
      End     Deduplicate candidates.

    No min_pathlength_map prefilter (that dropped legal Dig/Show sites).
    Full scan is well under 0.5s on a standard board.

    Ownership: road.color == player.color (color2 defensive alias).
    """
    player = next((p for p in game.players if p.id == player_id), None)
    if player is None:
        return []

    board = game.board

    player_colors = {player.color}
    if getattr(player, "color2", None):
        player_colors.add(player.color2)

    # Own S and C are both starts (city = upgraded settlement).
    start_intersections: Set[int] = set(getattr(player, "settlements", []) or [])
    start_intersections.update(getattr(player, "cities", []) or [])

    if not start_intersections:
        return []

    road_by_id: Dict[Tuple[int, int], Any] = {}
    for road in getattr(board, "roads", []) or []:
        if road is None:
            continue
        road_id = tuple(sorted(getattr(road, "id", ())))
        if len(road_id) == 2:
            road_by_id[road_id] = road

    def _road_between(a: int, b: int):
        return road_by_id.get(tuple(sorted((a, b))))

    def _road_is_empty_or_mine(a: int, b: int) -> bool:
        road = _road_between(a, b)
        if road is None:
            return False
        road_color = getattr(road, "color", "Blank")
        if road_color in player_colors:
            return True
        if road_color in ("", "Blank", None):
            return True
        return False

    def _neighbors(inter_id: int) -> List[int]:
        if not (0 <= inter_id < len(board.intersections)):
            return []
        inter = board.intersections[inter_id]
        if inter is None:
            return []
        out: List[int] = []
        for nxt in getattr(inter, "three_intersection_ids", []) or []:
            if not (0 <= nxt < len(board.intersections)):
                continue
            if board.intersections[nxt] is None:
                continue
            if nxt in getattr(board, "INTERSECTION_IN_WATER", []):
                continue
            out.append(int(nxt))
        return out

    def _intersection_can_build(inter_id: int) -> bool:
        """Step 2: available + Catan distance rule vs any occupied S/C."""
        if not (0 <= inter_id < len(board.intersections)):
            return False
        inter = board.intersections[inter_id]
        if inter is None:
            return False
        if inter_id in getattr(board, "INTERSECTION_IN_WATER", []):
            return False
        if getattr(inter, "occupied_tf", False):
            return False
        if getattr(inter, "can_build_tf", True) is False:
            return False
        if getattr(inter, "canbuildYNX", "Y") in ("N", "X"):
            return False
        for neighbor_id in getattr(inter, "three_intersection_ids", []) or []:
            if not (0 <= neighbor_id < len(board.intersections)):
                continue
            neighbor = board.intersections[neighbor_id]
            if neighbor is not None and getattr(neighbor, "occupied_tf", False):
                return False
        return True

    def _intermediate_blocked_by_opponent(next_id: int, target_id: int) -> bool:
        if int(next_id) == int(target_id):
            return False
        try:
            return bool(
                intersection_has_opponent_structure(game, player, int(next_id))
            )
        except Exception:
            inter = (
                board.intersections[next_id]
                if 0 <= next_id < len(board.intersections)
                else None
            )
            if inter is None or not getattr(inter, "occupied_tf", False):
                return False
            return getattr(inter, "color", None) not in player_colors

    def _geometric_ring_d2_d3(start_id: int) -> Set[int]:
        """Step 1: board-graph intersections at exact hop distance 2 or 3."""
        ring: Set[int] = set()
        if not (0 <= start_id < len(board.intersections)):
            return ring
        # BFS on topology only (road ownership checked in Step 3).
        queue: List[Tuple[int, int]] = [(start_id, 0)]
        seen: Set[int] = {start_id}
        while queue:
            node, depth = queue.pop(0)
            if depth >= 3:
                continue
            for nxt in _neighbors(node):
                if nxt in seen:
                    continue
                seen.add(nxt)
                nd = depth + 1
                if nd in (2, 3):
                    ring.add(nxt)
                if nd < 3:
                    queue.append((nxt, nd))
        return ring

    def _has_viable_path_from_start(start_id: int, target_id: int) -> bool:
        """Step 3: >=1 path start->target of hop length 2 or 3, viable roads."""
        stack = [(start_id, 0, {start_id})]
        while stack:
            current_id, depth, visited = stack.pop()
            if depth in (2, 3) and current_id == target_id:
                return True
            if depth >= 3:
                continue
            for next_id in _neighbors(current_id):
                if next_id in visited:
                    continue
                if not _road_is_empty_or_mine(current_id, next_id):
                    continue
                if _intermediate_blocked_by_opponent(next_id, target_id):
                    continue
                stack.append((next_id, depth + 1, visited | {next_id}))
        return False

    # Steps 1-4 over each own S/C; End = unique set.
    candidates: Set[int] = set()
    for start_id in sorted(start_intersections):
        potentials = _geometric_ring_d2_d3(int(start_id))
        for tid in potentials:
            if not _intersection_can_build(int(tid)):
                continue
            if not _has_viable_path_from_start(int(start_id), int(tid)):
                continue
            candidates.add(int(tid))

    return sorted(candidates)


def update_outlook_settlement_targets(game: "Game", player_id: int):
    """
    Update player.outlook[0].next_settlements and player.outlook[0].new_settlements.

    Returns:
        The updated outlook object, or None if player_id is invalid.
    """
    player = next((p for p in game.players if p.id == player_id), None)
    if player is None:
        return None

    # Player normally starts with player.outlook = [Outlook()].
    # This fallback protects older loaded saves or test players.
    if not hasattr(player, "outlook") or player.outlook is None:
        player.outlook = []

    if not player.outlook:
        from core.player import Outlook
        player.outlook.append(Outlook())

    outlook = player.outlook[0]

    next_spots = next_settlement_spots(game, player_id)
    new_spots = new_settlement_spots(game, player_id)

    # Main Outlook fields
    outlook.next_settlements = list(next_spots)
    outlook.new_settlements = list(new_spots)

    # Distances for first/second new settlement target.
    # Prefer the existing pathlength map if available.
    def _distance_to_new_settlement(inter_id: int) -> int:
        path_map = getattr(player, "min_pathlength_map_for_targeted_TWs", None)
        if path_map is not None:
            try:
                if 0 <= inter_id < len(path_map):
                    return int(path_map[inter_id])
            except Exception:
                pass
        return 99

    return outlook
# ─────────────────────────────────────────────────────────────────────────────
# AI road-planning path discovery helpers
# ─────────────────────────────────────────────────────────────────────────────

RoadKey = Tuple[int, int]


def _normalise_road_key(road: Any) -> RoadKey:
    """Return a sorted two-intersection road key, or () when invalid."""
    if isinstance(road, dict):
        for key in ("road_id", "road", "edge", "target_road", "road_to_build"):
            if key in road:
                return _normalise_road_key(road.get(key))
    try:
        values = list(road)[:2]
        if len(values) != 2:
            return ()  # type: ignore[return-value]
        a, b = int(values[0]), int(values[1])
        if a == b:
            return ()  # type: ignore[return-value]
        return tuple(sorted((a, b)))
    except Exception:
        return ()  # type: ignore[return-value]


def board_road_map(board: Any) -> Dict[RoadKey, Any]:
    """Return board Road objects keyed by normalized road id."""
    out: Dict[RoadKey, Any] = {}
    for road in list(getattr(board, "roads", []) or []):
        key = _normalise_road_key(getattr(road, "id", None))
        if key:
            out[key] = road
    return out


def player_owned_road_keys(game: "Game", player: Any) -> Set[RoadKey]:
    """Return normalized road keys owned by the player."""
    board = getattr(game, "board", None)
    road_map = board_road_map(board)
    colors = {str(getattr(player, "color", ""))}
    color2 = getattr(player, "color2", None)
    if color2:
        colors.add(str(color2))

    out: Set[RoadKey] = set()
    for key, road in road_map.items():
        try:
            if bool(getattr(road, "occupied_tf", False)) and str(getattr(road, "color", "")) in colors:
                out.add(key)
        except Exception:
            pass

    for raw in list(getattr(player, "roads", []) or []):
        key = _normalise_road_key(raw)
        if key:
            out.add(key)
    return out


def road_is_empty_or_owned_by_player(game: "Game", player: Any, road_id: Any) -> bool:
    """Return True when road_id can be part of player's future route."""
    board = getattr(game, "board", None)
    key = _normalise_road_key(road_id)
    if not key:
        return False
    road = board_road_map(board).get(key)
    if road is None:
        return False
    try:
        if not bool(getattr(road, "occupied_tf", False)):
            return True
    except Exception:
        return False
    return key in player_owned_road_keys(game, player)


def intersection_has_opponent_structure(game: "Game", player: Any, intersection_id: int) -> bool:
    """Return True if an opponent settlement/city blocks this intersection."""
    board = getattr(game, "board", None)
    try:
        inter = board.intersections[int(intersection_id)]
    except Exception:
        return False
    if inter is None:
        return False
    try:
        if not bool(getattr(inter, "occupied_tf", False)):
            return False
        own_colors = {str(getattr(player, "color", ""))}
        color2 = getattr(player, "color2", None)
        if color2:
            own_colors.add(str(color2))
        return str(getattr(inter, "color", "")) not in own_colors
    except Exception:
        return False


def future_settlement_target_is_open(game: "Game", player: Any, target_id: int) -> bool:
    """Return True when target_id remains a legal future settlement spot.

    This deliberately checks occupation/distance-rule state, not immediate road
    connectivity.  A new settlement 2 or 3 roads away can be valid before the
    connecting roads exist.
    """
    board = getattr(game, "board", None)
    try:
        target = int(target_id)
    except Exception:
        return False
    try:
        if target in set(getattr(board, "INTERSECTION_IN_WATER", []) or []):
            return False
        inter = board.intersections[target]
    except Exception:
        return False
    if inter is None:
        return False
    try:
        if bool(getattr(inter, "occupied_tf", False)):
            return False
    except Exception:
        pass
    try:
        if not bool(getattr(inter, "can_build_tf", True)):
            return False
    except Exception:
        pass
    return True


def candidate_road_set(candidates: Optional[Sequence[Dict[str, Any]]]) -> Set[RoadKey]:
    """Return normalized road ids from scanner candidates."""
    out: Set[RoadKey] = set()
    for candidate in list(candidates or []):
        if not isinstance(candidate, dict):
            continue
        key = _normalise_road_key(candidate)
        if key:
            out.add(key)
    return out


def route_path_is_clear_for_player(
    game: "Game",
    player: Any,
    path_roads: Sequence[RoadKey],
    target_id: Optional[int] = None,
) -> bool:
    """Return True if route roads are empty/mine and intermediate nodes are not blocked."""
    for road in list(path_roads or []):
        key = _normalise_road_key(road)
        if not key:
            return False
        if not road_is_empty_or_owned_by_player(game, player, key):
            return False
        for endpoint in key:
            if target_id is not None and int(endpoint) == int(target_id):
                continue
            if intersection_has_opponent_structure(game, player, int(endpoint)):
                return False
    return True


def route_roads_from_nodes(nodes: Sequence[int]) -> List[RoadKey]:
    """Convert ``[a,b,c]`` node path to **directed** steps ``[(a,b), (b,c)]``.

    Core distinction:
      - **road_id** = undirected ``(min, max)`` via ``_normalise_road_key`` (ownership / legal)
      - **path step** = directed ``(from, to)`` along the walk (network → tip)

    Do not sort endpoints here — callers that need road_id identity must normalise.
    """
    out: List[RoadKey] = []
    try:
        clean = [int(n) for n in list(nodes or [])]
    except Exception:
        return out
    for a, b in zip(clean, clean[1:]):
        if a == b:
            continue
        out.append((int(a), int(b)))
    return out


def _as_directed_path_step(road: Any) -> RoadKey:
    """Keep path direction when present; do not sort to road_id."""
    try:
        if isinstance(road, dict):
            for key in ("road_id", "road", "edge", "target_road", "road_to_build"):
                if key in road:
                    return _as_directed_path_step(road.get(key))
        values = list(road)[:2]
        if len(values) != 2:
            return ()  # type: ignore[return-value]
        a, b = int(values[0]), int(values[1])
        if a == b:
            return ()  # type: ignore[return-value]
        return (a, b)
    except Exception:
        return ()  # type: ignore[return-value]


def find_reachable_new_settlement_paths(
    game: "Game",
    player: Any,
    *,
    target_ids: Optional[Sequence[int]] = None,
    max_distance: int = 3,
    legal_road_candidates: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Find open paths to reachable new-settlement targets.

    This is deliberately an outlook/path-discovery function, not a strategic
    decision-maker.  It returns all valid short routes, and ai_road_planner.py
    later chooses the best route.

    Rules:
    - start from any existing own settlement/city;
    - path length must be 1..max_distance, with max_distance defaulting to 3;
    - every road on the path is empty or already owned by the player;
    - intermediate opponent structures block the route;
    - the target itself must be open/buildable;
    - if legal_road_candidates are supplied, the first unbuilt road must be one
      of those currently legal scanner roads.
    """
    board = getattr(game, "board", None)
    if board is None or player is None:
        return []
    try:
        max_distance = max(1, min(3, int(max_distance)))
    except Exception:
        max_distance = 3

    starts: Set[int] = set()
    try:
        starts.update(int(x) for x in list(getattr(player, "settlements", []) or []))
        starts.update(int(x) for x in list(getattr(player, "cities", []) or []))
    except Exception:
        starts = set()
    if not starts:
        return []

    if target_ids is None:
        try:
            target_ids = new_settlement_spots(game, int(getattr(player, "id")))
        except Exception:
            target_ids = []
    target_set: Set[int] = set()
    for raw in list(target_ids or []):
        try:
            target_set.add(int(raw))
        except Exception:
            pass
    target_set = {t for t in target_set if future_settlement_target_is_open(game, player, t)}
    if not target_set:
        return []

    road_map = board_road_map(board)
    adjacency: Dict[int, List[int]] = {}
    for a, b in road_map:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    owned_roads = player_owned_road_keys(game, player)
    legal_first_roads = candidate_road_set(legal_road_candidates)
    require_legal_first = bool(legal_first_roads)

    results: List[Dict[str, Any]] = []
    map_hit_targets: Set[int] = set()

    # Tier H: prefer fresh per-player reachability maps (BFS fallback for misses).
    # Never uses maps to hard-exclude candidacy — only to supply routes.
    try:
        from core.constants import REACHABILITY_MAPS
        from core.player_reachability import (
            SENTINEL,
            maps_are_fresh,
            path_to_target,
            remaining_roads_to_target,
        )

        if bool(REACHABILITY_MAPS) and maps_are_fresh(player):
            for tid in sorted(target_set):
                rem = remaining_roads_to_target(player, tid)
                if not (1 <= int(rem) <= int(max_distance)):
                    continue
                raw_path = path_to_target(player, tid)
                if not raw_path:
                    continue
                # Keep directed path steps (network→tip); road_id only for ownership/legal.
                all_roads = [_as_directed_path_step(r) for r in raw_path]
                all_roads = [r for r in all_roads if r]
                if not all_roads:
                    continue
                roads_to_build = [
                    r for r in all_roads if _normalise_road_key(r) not in owned_roads
                ]
                if not roads_to_build or len(roads_to_build) > max_distance:
                    continue
                first_road = roads_to_build[0]
                first_id = _normalise_road_key(first_road)
                if require_legal_first and first_id not in legal_first_roads:
                    continue
                if not route_path_is_clear_for_player(game, player, all_roads, int(tid)):
                    continue
                # Reconstruct nodes from directed steps in order
                route_nodes: List[int] = []
                for a, b in all_roads:
                    if not route_nodes:
                        if int(a) in starts:
                            route_nodes = [int(a), int(b)]
                        elif int(b) in starts:
                            route_nodes = [int(b), int(a)]
                        else:
                            route_nodes = [int(a), int(b)]
                    else:
                        prev = route_nodes[-1]
                        if int(a) == prev:
                            route_nodes.append(int(b))
                        elif int(b) == prev:
                            route_nodes.append(int(a))
                        else:
                            route_nodes.extend([int(a), int(b)])
                start_id = int(route_nodes[0]) if route_nodes else -1
                results.append({
                    "kind": "new_settlement",
                    "target_settlement_id": int(tid),
                    "start_intersection_id": start_id,
                    "route_nodes": list(route_nodes),
                    "route_all_roads": list(all_roads),
                    "roads_to_build": list(roads_to_build),
                    "next_road": first_road,
                    "distance": len(all_roads),
                    "roads_remaining": len(roads_to_build),
                    "target_label": f"new_settle@{int(tid)}",
                    "route_source": "player_reachability.path_map",
                })
                map_hit_targets.add(int(tid))
    except Exception:
        map_hit_targets = set()

    pending_targets = {t for t in target_set if int(t) not in map_hit_targets}
    for start in sorted(starts):
        if not pending_targets and map_hit_targets:
            break
        queue: List[Tuple[int, List[int]]] = [(start, [start])]
        seen: Set[Tuple[int, int]] = {(start, 0)}
        while queue:
            node, path_nodes = queue.pop(0)
            depth = len(path_nodes) - 1
            if depth >= max_distance:
                continue

            for nxt in sorted(adjacency.get(node, [])):
                if nxt in path_nodes:
                    continue
                road_key = _normalise_road_key((node, nxt))
                if not road_key:
                    continue
                if not road_is_empty_or_owned_by_player(game, player, road_key):
                    continue
                if int(nxt) not in target_set and intersection_has_opponent_structure(game, player, int(nxt)):
                    continue

                new_nodes = path_nodes + [int(nxt)]
                new_depth = len(new_nodes) - 1
                state_key = (int(nxt), new_depth)
                if state_key in seen:
                    continue
                seen.add(state_key)

                if int(nxt) in pending_targets:
                    all_roads = route_roads_from_nodes(new_nodes)
                    roads_to_build = [
                        r for r in all_roads if _normalise_road_key(r) not in owned_roads
                    ]
                    if not roads_to_build:
                        continue
                    if len(roads_to_build) > max_distance:
                        continue
                    first_road = roads_to_build[0]
                    first_id = _normalise_road_key(first_road)
                    if require_legal_first and first_id not in legal_first_roads:
                        continue
                    if not route_path_is_clear_for_player(game, player, all_roads, int(nxt)):
                        continue
                    results.append({
                        "kind": "new_settlement",
                        "target_settlement_id": int(nxt),
                        "start_intersection_id": int(start),
                        "route_nodes": list(new_nodes),
                        "route_all_roads": list(all_roads),
                        "roads_to_build": list(roads_to_build),
                        "next_road": first_road,
                        "distance": len(all_roads),
                        "roads_remaining": len(roads_to_build),
                        "target_label": f"new_settle@{int(nxt)}",
                        "route_source": "outlook_logic.find_reachable_new_settlement_paths",
                    })
                    continue

                queue.append((int(nxt), new_nodes))

    # Stable order: shortest first, then target id, then path.
    results.sort(key=lambda r: (int(r.get("roads_remaining", 99)), int(r.get("target_settlement_id", 9999)), str(r.get("route_nodes"))))
    return results
