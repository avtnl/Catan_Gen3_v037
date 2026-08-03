"""core/risk_assessment.py

Small, conservative risk helpers for AI road/new-settlement planning.

This module deliberately does not execute game actions.  It answers questions
such as: can an opponent block this path, touch this target, or race us to the
same new-settlement spot?

PR-A (distance-rule spoiler):
  An opponent who settles a *neighbor* of our target invalidates that target
  under the distance rule.  We therefore raise risk when opponents can reach
  such a kill-site, even if they never race the target itself.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

try:
    from core.outlook_logic import (
        _normalise_road_key,
        board_road_map,
        future_settlement_target_is_open,
        intersection_has_opponent_structure,
        road_is_empty_or_owned_by_player,
    )
except Exception:  # pragma: no cover - editor/test fallback
    def _normalise_road_key(road: Any) -> Tuple[int, int]:  # type: ignore[misc]
        try:
            a, b = list(road)[:2]
            return tuple(sorted((int(a), int(b))))
        except Exception:
            return ()  # type: ignore[return-value]

    def board_road_map(board: Any) -> Dict[Tuple[int, int], Any]:
        return {}

    def future_settlement_target_is_open(*_: Any, **__: Any) -> bool:
        return False

    def intersection_has_opponent_structure(*_: Any, **__: Any) -> bool:
        return False

    def road_is_empty_or_owned_by_player(*_: Any, **__: Any) -> bool:
        return False


RiskTuple = Tuple[str, float]

# BFS depth for “can opponent reach kill-site / target with free roads”
_MAX_SPOILER_ROAD_DEPTH = 2


def _player_colors(player: Any) -> set[str]:
    colors = {str(getattr(player, "color", ""))}
    color2 = getattr(player, "color2", None)
    if color2:
        colors.add(str(color2))
    return {c for c in colors if c and c != "Blank"}


def _safe_player_id(player: Any) -> Optional[int]:
    try:
        pid = int(getattr(player, "id", 0) or 0)
        return pid if pid > 0 else None
    except Exception:
        return None


def _target_neighbors(game: Any, target_id: int) -> set[int]:
    try:
        inter = game.board.intersections[int(target_id)]
        return {int(x) for x in list(getattr(inter, "three_intersection_ids", []) or [])}
    except Exception:
        return set()


def _water_set(game: Any) -> set[int]:
    try:
        return {int(x) for x in list(getattr(game.board, "INTERSECTION_IN_WATER", []) or [])}
    except Exception:
        return set()


def _intersection_open_for_settle(game: Any, intersection_id: int) -> bool:
    """True if a settlement could still be placed here (occupation + flags)."""
    board = getattr(game, "board", None)
    try:
        iid = int(intersection_id)
    except Exception:
        return False
    if iid in _water_set(game):
        return False
    try:
        inter = board.intersections[iid]
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
    # Distance rule vs any existing structure (any player)
    try:
        for nb in list(getattr(inter, "three_intersection_ids", []) or []):
            ninter = board.intersections[int(nb)]
            if ninter is not None and bool(getattr(ninter, "occupied_tf", False)):
                return False
    except Exception:
        pass
    return True


def _empty_road_adjacency(game: Any) -> Dict[int, List[int]]:
    """Undirected graph of empty board edges (legal future roads)."""
    adj: Dict[int, List[int]] = {}
    board = getattr(game, "board", None)
    try:
        rmap = board_road_map(board)
    except Exception:
        rmap = {}
    try:
        for road in list(getattr(board, "roads", []) or []):
            key = _normalise_road_key(getattr(road, "id", None) or getattr(road, "intersections", None))
            if not key or len(key) < 2:
                continue
            a, b = int(key[0]), int(key[1])
            occupied = bool(getattr(road, "occupied_tf", False))
            # Prefer map if present
            if key in rmap:
                occupied = bool(getattr(rmap[key], "occupied_tf", occupied))
            if occupied:
                continue
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    except Exception:
        pass
    return adj


def _player_network_nodes(game: Any, player: Any) -> Set[int]:
    """Intersections already on this player's road/settlement network."""
    nodes: Set[int] = set()
    colors = _player_colors(player)
    try:
        for sid in list(getattr(player, "settlements", []) or []):
            nodes.add(int(sid))
        for cid in list(getattr(player, "cities", []) or []):
            nodes.add(int(cid))
    except Exception:
        pass
    try:
        for road in list(getattr(player, "roads", []) or []):
            key = _normalise_road_key(road)
            if key and len(key) >= 2:
                nodes.add(int(key[0]))
                nodes.add(int(key[1]))
    except Exception:
        pass
    # Also scan board roads of their color
    try:
        for road in list(getattr(game.board, "roads", []) or []):
            if not bool(getattr(road, "occupied_tf", False)):
                continue
            if str(getattr(road, "color", "")) not in colors:
                continue
            key = _normalise_road_key(getattr(road, "id", None))
            if key and len(key) >= 2:
                nodes.add(int(key[0]))
                nodes.add(int(key[1]))
    except Exception:
        pass
    return nodes


def _min_empty_roads_to_reach(
    game: Any,
    player: Any,
    target_id: int,
    *,
    max_depth: int = _MAX_SPOILER_ROAD_DEPTH,
) -> Optional[int]:
    """Min empty roads for *player* to connect their network to target_id.

    0 means already on network / road already touches target.
    None means unreachable within max_depth.
    """
    try:
        target = int(target_id)
    except Exception:
        return None
    start = _player_network_nodes(game, player)
    if not start:
        return None
    if target in start:
        return 0
    # Already a road of theirs on an edge into target
    colors = _player_colors(player)
    try:
        for road in list(getattr(game.board, "roads", []) or []):
            if not bool(getattr(road, "occupied_tf", False)):
                continue
            if str(getattr(road, "color", "")) not in colors:
                continue
            key = _normalise_road_key(getattr(road, "id", None))
            if key and target in key:
                return 0
    except Exception:
        pass

    adj = _empty_road_adjacency(game)
    # BFS over empty edges from network
    q: deque[Tuple[int, int]] = deque()
    seen: Set[int] = set(start)
    for n in start:
        q.append((n, 0))
    while q:
        node, dist = q.popleft()
        if dist >= max_depth:
            continue
        for nxt in adj.get(node, []):
            if nxt in seen:
                continue
            nd = dist + 1
            if nxt == target:
                return nd
            if nd < max_depth:
                seen.add(nxt)
                q.append((nxt, nd))
            elif nd == max_depth and nxt == target:
                return nd
            else:
                seen.add(nxt)
                if nxt == target:
                    return nd
    return None


def _opponent_players(game: Any, player: Any) -> List[Any]:
    out: List[Any] = []
    own_id = _safe_player_id(player)
    own_colors = _player_colors(player)
    for other in list(getattr(game, "players", []) or []):
        if other is None:
            continue
        oid = _safe_player_id(other)
        if own_id is not None and oid == own_id:
            continue
        if str(getattr(other, "color", "")) in own_colors:
            continue
        out.append(other)
    return out


def _threat_record(
    *,
    player: Any,
    mode: str,
    block_site: Optional[int] = None,
    roads_needed: Optional[int] = None,
    reason: str = "",
) -> Dict[str, Any]:
    return {
        "player_id": _safe_player_id(player),
        "color": str(getattr(player, "color", "") or ""),
        "mode": mode,  # "race" | "block"
        "block_site": int(block_site) if block_site is not None else None,
        # PR-B full: fill eta_own_turns via EH; stub leaves None
        "eta_own_turns": None,
        "roads_needed": roads_needed,
        "reason": reason,
    }


def opponent_settlement_race_risk(game: Any, player: Any, target_id: int) -> Dict[str, Any]:
    """Return a conservative opponent-race assessment for a target.

    Geometry + PR-A distance-rule spoilers (kill-sites = neighbors of target).

    Soft race (1–2 empty roads to T): records race-mode threats for PR-C ETA
    upgrade, but does **not** raise risk_level on geometry alone. Hard geometry
    still elevates: network already on T (0 roads), opponent road touching /
    near T, and spoiler kill-site reach. Full low→med/high labeling for soft
    race is done in ``attach_timing_pack_to_portfolio`` via own/opp ETAs.
    """
    reasons: List[str] = []
    try:
        target = int(target_id)
    except Exception:
        return {
            "risk_level": "blocked",
            "risk_score": 99.0,
            "risk_class": 3,
            "contested_by": [],
            "threat_opponents": [],
            "block_sites": [],
            "reasons": ["invalid target"],
        }

    if not future_settlement_target_is_open(game, player, target):
        return {
            "risk_level": "blocked",
            "risk_score": 99.0,
            "risk_class": 3,
            "opponent_can_block": True,
            "opponent_can_settle_first": True,
            "contested_by": [],
            "threat_opponents": [],
            "block_sites": [],
            "reasons": [f"target new_settle@{target} is not open/buildable"],
        }

    own_colors = _player_colors(player)
    target_neighbors = _target_neighbors(game, target)
    contested_by: set[str] = set()
    threat_opponents: List[Dict[str, Any]] = []
    block_sites: List[Dict[str, Any]] = []
    risk_class = 0

    # ── Existing road pressure on target ──────────────────────────────────
    try:
        for road in list(getattr(game.board, "roads", []) or []):
            road_key = _normalise_road_key(getattr(road, "id", None))
            if not road_key or not bool(getattr(road, "occupied_tf", False)):
                continue
            color = str(getattr(road, "color", ""))
            if color in own_colors:
                continue
            if target in road_key:
                contested_by.add(color)
                risk_class = max(risk_class, 2)
                reasons.append(f"opponent road {road_key} already touches target")
                continue
            if any(endpoint in target_neighbors for endpoint in road_key):
                contested_by.add(color)
                risk_class = max(risk_class, 1)
                reasons.append(f"opponent road {road_key} is near target")
    except Exception:
        pass

    # Race: opponent roads to the target itself
    # Hard: 0 empty roads (already connected) → geometry high.
    # Soft (PR-C / 1b): 1–2 empty roads → record race threats only; ETA pack
    # may raise low→med/high. Never a substitute for spoiler medium/high.
    for opp in _opponent_players(game, player):
        roads_to_t = _min_empty_roads_to_reach(game, opp, target, max_depth=_MAX_SPOILER_ROAD_DEPTH)
        if roads_to_t is None:
            continue
        color = str(getattr(opp, "color", "") or "")
        if roads_to_t == 0:
            contested_by.add(color)
            risk_class = max(risk_class, 2)
            reasons.append(f"{color} network already reaches target @{target}")
            threat_opponents.append(
                _threat_record(
                    player=opp,
                    mode="race",
                    roads_needed=0,
                    reason=f"network reaches @{target}",
                )
            )
        elif roads_to_t <= _MAX_SPOILER_ROAD_DEPTH:
            contested_by.add(color)
            # Soft race: track for ETA upgrade; geometry risk stays as-is
            if roads_to_t == 1:
                reasons.append(
                    f"{color} soft-race: 1 empty road from target @{target} (ETA may raise risk)"
                )
            else:
                reasons.append(
                    f"{color} soft-race: {roads_to_t} empty roads from target @{target} "
                    f"(ETA may raise risk)"
                )
            threat_opponents.append(
                _threat_record(
                    player=opp,
                    mode="race",
                    roads_needed=int(roads_to_t),
                    reason=(
                        f"1 road from @{target}"
                        if roads_to_t == 1
                        else f"{roads_to_t} roads from @{target}"
                    ),
                )
            )

    # ── PR-A: distance-rule spoilers (settle neighbor → kill target) ──────
    for n in sorted(target_neighbors):
        if not _intersection_open_for_settle(game, n):
            # Already occupied by opponent next door → target may be dead
            if intersection_has_opponent_structure(game, player, n):
                risk_class = max(risk_class, 3)
                reasons.append(f"opponent structure at neighbor @{n} kills distance rule for @{target}")
                block_sites.append({"intersection_id": int(n), "mode": "occupied_neighbor"})
            continue

        for opp in _opponent_players(game, player):
            roads_to_n = _min_empty_roads_to_reach(game, opp, n, max_depth=_MAX_SPOILER_ROAD_DEPTH)
            if roads_to_n is None:
                continue
            color = str(getattr(opp, "color", "") or "")
            if roads_to_n == 0:
                contested_by.add(color)
                risk_class = max(risk_class, 2)
                reasons.append(
                    f"{color} can distance-block @{target} via kill-site @{n} (already connected)"
                )
                block_sites.append(
                    {
                        "intersection_id": int(n),
                        "by_player_id": _safe_player_id(opp),
                        "color": color,
                        "roads_needed": 0,
                        "mode": "block",
                    }
                )
                threat_opponents.append(
                    _threat_record(
                        player=opp,
                        mode="block",
                        block_site=n,
                        roads_needed=0,
                        reason=f"block @{target} via @{n}",
                    )
                )
            elif roads_to_n <= _MAX_SPOILER_ROAD_DEPTH:
                contested_by.add(color)
                # One road away from kill-site is medium; two roads still medium
                # (P3 @51+[51,52] needing [52,53] toward kill-site @53).
                risk_class = max(risk_class, 1)
                reasons.append(
                    f"{color} can distance-block @{target} via kill-site @{n} "
                    f"({roads_to_n} empty road(s))"
                )
                block_sites.append(
                    {
                        "intersection_id": int(n),
                        "by_player_id": _safe_player_id(opp),
                        "color": color,
                        "roads_needed": int(roads_to_n),
                        "mode": "block",
                    }
                )
                threat_opponents.append(
                    _threat_record(
                        player=opp,
                        mode="block",
                        block_site=n,
                        roads_needed=roads_to_n,
                        reason=f"block @{target} via @{n} in {roads_to_n}r",
                    )
                )

    # Dedupe threats by (player_id, mode, block_site)
    threat_opponents = _dedupe_threats(threat_opponents)

    risk_level = "low"
    risk_score = 0.0
    if risk_class == 1:
        risk_level = "medium"
        risk_score = 20.0
    elif risk_class == 2:
        risk_level = "high"
        risk_score = 45.0
    elif risk_class >= 3:
        risk_level = "blocked"
        risk_score = 99.0

    return {
        "risk_level": risk_level,
        "risk_score": risk_score,
        "risk_class": risk_class,
        "opponent_can_block": risk_class >= 1,
        "opponent_can_settle_first": risk_class >= 2,
        "contested_by": sorted(contested_by),
        "threat_opponents": threat_opponents,
        "block_sites": block_sites,
        "reasons": reasons or ["no nearby opponent road pressure or spoiler path detected"],
    }


def _dedupe_threats(threats: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[Tuple[Any, str, Any], Dict[str, Any]] = {}
    for t in threats:
        if not isinstance(t, Mapping):
            continue
        key = (t.get("player_id"), str(t.get("mode") or ""), t.get("block_site"))
        prev = best.get(key)
        if prev is None:
            best[key] = dict(t)
            continue
        # Keep lower roads_needed if both present
        pr = prev.get("roads_needed")
        nr = t.get("roads_needed")
        if nr is not None and (pr is None or int(nr) < int(pr)):
            best[key] = dict(t)
    return list(best.values())


def assess_new_settlement_path_risk(
    game: Any,
    player: Any,
    target_id: int,
    path_roads: Sequence[Any],
) -> Dict[str, Any]:
    """Assess risk for one path toward a new-settlement target."""
    reasons: List[str] = []
    try:
        target = int(target_id)
    except Exception:
        return {
            "risk_level": "blocked",
            "risk_score": 99.0,
            "risk_class": 3,
            "threat_opponents": [],
            "block_sites": [],
            "reasons": ["invalid target"],
        }

    # Hard block if any road is unavailable or any intermediate node is blocked.
    normalized_roads: List[Tuple[int, int]] = []
    for raw in list(path_roads or []):
        key = _normalise_road_key(raw)
        if not key:
            return {
                "risk_level": "blocked",
                "risk_score": 99.0,
                "risk_class": 3,
                "threat_opponents": [],
                "block_sites": [],
                "reasons": ["invalid road in path"],
            }
        normalized_roads.append(key)
        if not road_is_empty_or_owned_by_player(game, player, key):
            return {
                "risk_level": "blocked",
                "risk_score": 99.0,
                "risk_class": 3,
                "opponent_can_block": True,
                "opponent_can_settle_first": False,
                "contested_by": [],
                "threat_opponents": [],
                "block_sites": [],
                "reasons": [f"road {key} is already occupied by another player"],
            }
        for endpoint in key:
            if int(endpoint) == target:
                continue
            if intersection_has_opponent_structure(game, player, int(endpoint)):
                return {
                    "risk_level": "blocked",
                    "risk_score": 99.0,
                    "risk_class": 3,
                    "opponent_can_block": True,
                    "opponent_can_settle_first": False,
                    "contested_by": [],
                    "threat_opponents": [],
                    "block_sites": [],
                    "reasons": [f"opponent structure blocks intermediate intersection {endpoint}"],
                }

    race = opponent_settlement_race_risk(game, player, target)
    reasons.extend(list(race.get("reasons", []) or []))

    # One extra soft penalty for long/chokepoint-ish routes.
    length_penalty = max(0, len(normalized_roads) - 1) * 5.0
    risk_score = float(race.get("risk_score", 0.0) or 0.0) + length_penalty
    risk_class = int(race.get("risk_class", 0) or 0)
    if length_penalty >= 10.0 and risk_class < 2:
        risk_class = max(risk_class, 1)
        reasons.append("longer route has more blocking exposure")

    risk_level = "low"
    if risk_class == 1:
        risk_level = "medium"
    elif risk_class == 2:
        risk_level = "high"
    elif risk_class >= 3:
        risk_level = "blocked"

    return {
        "risk_level": risk_level,
        "risk_score": risk_score,
        "risk_class": risk_class,
        "opponent_can_block": bool(race.get("opponent_can_block", False)),
        "opponent_can_settle_first": bool(race.get("opponent_can_settle_first", False)),
        "contested_by": list(race.get("contested_by", []) or []),
        "threat_opponents": list(race.get("threat_opponents", []) or []),
        "block_sites": list(race.get("block_sites", []) or []),
        "reasons": reasons or ["path risk is low"],
    }


def format_threat_opponents_short(threats: Sequence[Mapping[str, Any]]) -> str:
    """UI helper: 'P2, P3 (2.7t), P4' — only lowest eta shown among threats.

    Product choice (2): list all med/high threat opponents; attach expected
    turns only for the opponent with the lowest eta. Stub may have all etas None.
    """
    rows = [dict(t) for t in threats if isinstance(t, Mapping)]
    if not rows:
        return ""

    def _label(t: Mapping[str, Any]) -> str:
        pid = t.get("player_id")
        if pid is not None:
            return f"P{pid}"
        col = str(t.get("color") or "").strip()
        return col[:3] if col else "?"

    # Lowest finite eta
    best_idx = None
    best_eta = None
    for i, t in enumerate(rows):
        raw = t.get("eta_own_turns")
        if raw is None:
            continue
        try:
            eta = float(raw)
        except Exception:
            continue
        if eta >= 9000:
            continue
        if best_eta is None or eta < best_eta:
            best_eta = eta
            best_idx = i

    parts: List[str] = []
    for i, t in enumerate(rows):
        lab = _label(t)
        if best_idx is not None and i == best_idx and best_eta is not None:
            parts.append(f"{lab} ({best_eta:.1f}t)")
        else:
            # Optional block site hint when no eta yet
            bs = t.get("block_site")
            if bs is not None and best_idx is None:
                parts.append(f"{lab}(@{bs})")
            else:
                parts.append(lab)
    # Dedupe labels while preserving order
    seen: Set[str] = set()
    out: List[str] = []
    for p in parts:
        key = p.split("(")[0].split("@")[0]
        if key in seen and "(" not in p:
            continue
        seen.add(key)
        out.append(p)
    return ", ".join(out)


__all__ = [
    "opponent_settlement_race_risk",
    "assess_new_settlement_path_risk",
    "format_threat_opponents_short",
    "_min_empty_roads_to_reach",
    "_target_neighbors",
]
