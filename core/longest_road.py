"""Pure Longest Road length engine (PR2 — compute only, no award/VP).

Computes each player's longest continuous road under standard Catan rules:

  - Count individual road segments in a continuous chain (no edge reuse).
  - Forks do not add length (simple path only).
  - Opponent settlements/cities **interrupt** continuity: paths may end at a
    foreign-occupied intersection but cannot pass *through* it.
  - Own settlements/cities do **not** interrupt.

Used later by recompute/award (PR3). This module has no GUI or VP side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

Edge = Tuple[int, int]


def normalize_edge(a: Any, b: Any = None) -> Optional[Edge]:
    """Return canonical undirected edge (min, max), or None if invalid."""
    try:
        if b is None:
            # Single sequence argument: [a, b] or (a, b)
            if isinstance(a, (list, tuple)) and len(a) >= 2:
                u, v = int(a[0]), int(a[1])
            else:
                return None
        else:
            u, v = int(a), int(b)
    except Exception:
        return None
    if u == v:
        return None
    return (u, v) if u < v else (v, u)


def normalize_edges(raw_edges: Iterable[Any]) -> List[Edge]:
    """Deduplicate and normalize a mixed list of road representations."""
    out: List[Edge] = []
    seen: Set[Edge] = set()
    for raw in raw_edges or []:
        e = None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            e = normalize_edge(raw[0], raw[1])
        elif isinstance(raw, Mapping):
            for key in ("id", "road_id", "edge", "road"):
                if key in raw:
                    e = normalize_edge(raw[key])
                    break
        if e is None or e in seen:
            continue
        seen.add(e)
        out.append(e)
    return out


@dataclass
class LongestRoadResult:
    """Longest continuous road for one player."""

    player_id: int
    length: int = 0
    path_edges: List[Edge] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "player_id": int(self.player_id),
            "length": int(self.length),
            "path_edges": [list(e) for e in self.path_edges],
        }


def _build_adjacency(edges: Sequence[Edge]) -> Dict[int, List[Tuple[int, Edge]]]:
    """node -> list of (neighbor, edge_key)."""
    adj: Dict[int, List[Tuple[int, Edge]]] = {}
    for e in edges:
        u, v = e
        adj.setdefault(u, []).append((v, e))
        adj.setdefault(v, []).append((u, e))
    return adj


def compute_longest_road_for_edges(
    edges: Sequence[Any],
    *,
    barrier_nodes: Optional[Iterable[int]] = None,
    player_id: int = 0,
) -> LongestRoadResult:
    """Longest simple path (by edge count) in a player's road graph.

    Parameters
    ----------
    edges :
        Player roads as pairs / lists.
    barrier_nodes :
        Intersections occupied by **other** players' settlements/cities.
        Paths may end at a barrier but cannot continue through it.
    player_id :
        Stored on the result for multi-player helpers.
    """
    edge_list = normalize_edges(edges)
    barriers: Set[int] = set()
    for n in barrier_nodes or []:
        try:
            barriers.add(int(n))
        except Exception:
            pass

    if not edge_list:
        return LongestRoadResult(player_id=int(player_id), length=0, path_edges=[])

    adj = _build_adjacency(edge_list)
    nodes = list(adj.keys())

    best_len = 0
    best_path: List[Edge] = []

    def can_expand_from(node: int, depth: int) -> bool:
        # depth == 0: starting at this node (allowed even if barrier)
        # depth > 0: arrived via an edge — barriers block further expansion
        if node in barriers and depth > 0:
            return False
        return True

    def dfs(node: int, used: Set[Edge], path: List[Edge]) -> None:
        nonlocal best_len, best_path
        depth = len(path)
        if depth > best_len:
            best_len = depth
            best_path = list(path)
        if not can_expand_from(node, depth):
            return
        for nbr, edge in adj.get(node, []):
            if edge in used:
                continue
            used.add(edge)
            path.append(edge)
            dfs(nbr, used, path)
            path.pop()
            used.remove(edge)

    # Start DFS from every node (endpoints and hubs)
    for start in nodes:
        dfs(start, set(), [])

    return LongestRoadResult(
        player_id=int(player_id),
        length=int(best_len),
        path_edges=list(best_path),
    )


def _player_id(player: Any) -> int:
    try:
        return int(getattr(player, "id", 0) or 0)
    except Exception:
        return 0


def _player_color(player: Any) -> str:
    return str(getattr(player, "color", "") or "")


def _occupied_building_nodes(player: Any) -> Set[int]:
    """Settlement + city intersection ids for one player."""
    nodes: Set[int] = set()
    for attr in ("settlements", "cities"):
        try:
            for loc in list(getattr(player, attr, []) or []):
                try:
                    nodes.add(int(loc))
                except Exception:
                    pass
        except Exception:
            pass
    return nodes


def _player_road_edges(player: Any) -> List[Edge]:
    raw = list(getattr(player, "roads", []) or [])
    return normalize_edges(raw)


def foreign_barrier_nodes(game: Any, player: Any) -> Set[int]:
    """Intersections with other players' settlements/cities."""
    pid = _player_id(player)
    color = _player_color(player)
    barriers: Set[int] = set()
    for opp in list(getattr(game, "players", []) or []):
        if opp is None:
            continue
        if _player_id(opp) == pid and pid > 0:
            continue
        if pid <= 0 and color and _player_color(opp) == color:
            continue
        if _player_id(opp) == pid:
            continue
        # Skip self by identity when ids missing
        if opp is player:
            continue
        barriers |= _occupied_building_nodes(opp)
    return barriers


def compute_longest_road_for_player(game: Any, player: Any) -> LongestRoadResult:
    """Longest continuous road for one player on the current game board."""
    if player is None:
        return LongestRoadResult(player_id=0, length=0, path_edges=[])
    edges = _player_road_edges(player)
    barriers = foreign_barrier_nodes(game, player)
    return compute_longest_road_for_edges(
        edges,
        barrier_nodes=barriers,
        player_id=_player_id(player),
    )


def compute_longest_road_lengths(game: Any) -> Dict[int, LongestRoadResult]:
    """Compute longest continuous road for every non-None player.

    Returns
    -------
    dict
        ``player_id -> LongestRoadResult``. Players with id 0 are keyed by
        enumeration index offset only if needed; normally ids are 1..N.
    """
    results: Dict[int, LongestRoadResult] = {}
    for player in list(getattr(game, "players", []) or []):
        if player is None:
            continue
        res = compute_longest_road_for_player(game, player)
        pid = res.player_id
        if pid <= 0:
            # Fallback unique key
            pid = len(results) + 1
            res.player_id = pid
        results[pid] = res
    return results


def continuous_length_with_extra_edges(
    game: Any,
    player: Any,
    extra_edges: Optional[Sequence[Any]] = None,
) -> LongestRoadResult:
    """Longest continuous road if ``extra_edges`` were already built by player.

    Used by AI plan-time LR-crit (TFR free roads, speculative paid roads).
    Does not mutate the game.
    """
    if player is None:
        return LongestRoadResult(player_id=0, length=0, path_edges=[])
    base = _player_road_edges(player)
    extras = normalize_edges(extra_edges or [])
    # Drop extras already owned
    owned = set(base)
    extras = [e for e in extras if e not in owned]
    barriers = foreign_barrier_nodes(game, player)
    return compute_longest_road_for_edges(
        list(base) + list(extras),
        barrier_nodes=barriers,
        player_id=_player_id(player),
    )


def evaluate_lr_claim_after_edges(
    game: Any,
    player: Any,
    extra_edges: Optional[Sequence[Any]] = None,
    *,
    min_length: int = 5,
) -> Dict[str, Any]:
    """Whether adding ``extra_edges`` would take / reclaim Longest Road.

    Uses real continuous lengths for all players (PR2 engine). Tie rule matches
    award recompute: need strictly more than current holder (or ≥min if vacant).
    """
    pid = _player_id(player)
    all_lens = compute_longest_road_lengths(game)
    ai_now = int((all_lens.get(pid) or LongestRoadResult(pid)).length)
    after = continuous_length_with_extra_edges(game, player, extra_edges)
    ai_after = int(after.length)

    max_opp = 0
    holder_id = None
    holder_len = 0
    someone_holds = False
    for p in list(getattr(game, "players", []) or []):
        if p is None:
            continue
        opid = _player_id(p)
        olen = int((all_lens.get(opid) or LongestRoadResult(opid)).length)
        # Prefer live size from engine over stale size_longest_route
        try:
            if bool(getattr(p, "longest_route_tf", False)):
                someone_holds = True
                holder_id = opid
                holder_len = olen
        except Exception:
            pass
        if opid != pid:
            max_opp = max(max_opp, olen)

    # If no tf flags but lengths known, treat max≥min as effective holder length
    if not someone_holds:
        best = 0
        best_id = None
        for opid, res in all_lens.items():
            if int(res.length) > best:
                best = int(res.length)
                best_id = opid
        if best >= min_length:
            someone_holds = True
            holder_id = best_id
            holder_len = best

    takes_now = False
    if ai_after < min_length:
        takes_now = False
    elif someone_holds and holder_id is not None and holder_id != pid:
        takes_now = ai_after > holder_len
    elif someone_holds and holder_id == pid:
        # Already hold: free roads "take" only if they reaffirm after (always true if still max)
        takes_now = ai_after >= min_length and ai_after >= max(holder_len, max_opp)
        # Not a critical *claim* if already holding — only critical to *steal* or first claim
        takes_now = False
    else:
        # Vacant special
        takes_now = ai_after >= min_length and ai_after > max_opp

    steals = bool(
        takes_now and someone_holds and holder_id is not None and holder_id != pid
    )
    first_claim = bool(takes_now and not someone_holds)

    return {
        "player_id": pid,
        "length_now": ai_now,
        "length_after": ai_after,
        "max_opp_length": int(max_opp),
        "holder_id": holder_id,
        "holder_length": int(holder_len),
        "someone_holds_lr": bool(someone_holds),
        "takes_now": bool(takes_now),
        "steals": bool(steals),
        "first_claim": bool(first_claim),
        "extra_edges": [list(e) for e in normalize_edges(extra_edges or [])],
        "path_after": list(after.path_edges),
        "min_length": int(min_length),
    }


__all__ = [
    "Edge",
    "LongestRoadResult",
    "normalize_edge",
    "normalize_edges",
    "compute_longest_road_for_edges",
    "compute_longest_road_for_player",
    "compute_longest_road_lengths",
    "foreign_barrier_nodes",
    "continuous_length_with_extra_edges",
    "evaluate_lr_claim_after_edges",
]
