"""Phase C2 WP-R5: first Victory-Way fit metrics (once per seat at first lock).

Formulas (plan §6.2, resource order Wheat/Ore/Wood/Brick/Sheep):

- ``fit_own``: cosine similarity of own production pips vs way need weights
- ``fit_board``: 1 − scarcity_risk (top needs vs board totals)
- ``fit_expand``: fraction of missing engines coverable by best d≤2 spots
- ``fit_total``: 0.40*fit_own + 0.25*fit_board + 0.35*fit_expand

Stored on ``player.first_way_fit``, CS fields, and ``result.json``
``first_way_fit_by_seat``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RESOURCE_NAMES = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
N_RES = 5

# Structure → resource cost weights (game order)
_W = 0  # Wheat
_O = 1  # Ore
_WO = 2  # Wood
_B = 3  # Brick
_S = 4  # Sheep

# Fixed weight table (v1) — units of card demand per structure flag
WEIGHT_CITY = (_W, 2.0), (_O, 3.0)  # city = 2W 3O
WEIGHT_SETTLE = (_W, 1.0), (_WO, 1.0), (_B, 1.0), (_S, 1.0)
WEIGHT_ROAD = (_WO, 1.0), (_B, 1.0)
WEIGHT_DCARD = (_W, 1.0), (_O, 1.0), (_S, 1.0)
WEIGHT_LA = (_W, 2.0), (_O, 3.0), (_S, 2.0)  # army engine tilt
WEIGHT_LR = (_WO, 4.0), (_B, 4.0)  # road engine tilt

FIT_OWN_W = 0.40
FIT_BOARD_W = 0.25
FIT_EXPAND_W = 0.35

# Own pips ≥ this count as "have engine" for that resource
ENGINE_PIP_THR = 2.0
# Spot covers an engine if its pips for that resource ≥ this
SPOT_COVER_PIP_THR = 2.0


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
        if f != f or f > 1e12:
            return default
        return f
    except Exception:
        return default


def _vec5(raw: Any, default: float = 0.0) -> List[float]:
    out = [default] * N_RES
    if raw is None:
        return out
    if isinstance(raw, Mapping):
        for i, name in enumerate(RESOURCE_NAMES):
            if name in raw:
                out[i] = _safe_float(raw.get(name), default)
            elif i in raw:
                out[i] = _safe_float(raw.get(i), default)
        return out
    try:
        seq = list(raw)
    except Exception:
        return out
    for i in range(min(N_RES, len(seq))):
        out[i] = _safe_float(seq[i], default)
    return out


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return max(0.0, min(1.0, float(x)))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [0, 1] for non-negative vectors (clamped)."""
    aa = _vec5(a)
    bb = _vec5(b)
    dot = sum(x * y for x, y in zip(aa, bb))
    na = math.sqrt(sum(x * x for x in aa))
    nb = math.sqrt(sum(y * y for y in bb))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return _clamp01(dot / (na * nb))


def need_weights_from_reqs(
    *,
    req_cities: int = 0,
    req_settles: int = 0,
    req_roads: int = 0,
    req_dcards: int = 0,
    way_la: bool = False,
    way_lr: bool = False,
    need_vector: Optional[Sequence[float]] = None,
) -> List[float]:
    """Build 5-vector need weights from structure counts / flags.

    If ``need_vector`` is provided and non-zero, blend it in (average with table).
    """
    w = [0.0] * N_RES
    for _ in range(max(0, int(req_cities or 0))):
        for idx, amt in WEIGHT_CITY:
            w[idx] += amt
    for _ in range(max(0, int(req_settles or 0))):
        for idx, amt in WEIGHT_SETTLE:
            w[idx] += amt
    for _ in range(max(0, int(req_roads or 0))):
        for idx, amt in WEIGHT_ROAD:
            w[idx] += amt
    for _ in range(max(0, int(req_dcards or 0))):
        for idx, amt in WEIGHT_DCARD:
            w[idx] += amt
    if way_la:
        for idx, amt in WEIGHT_LA:
            w[idx] += amt
    if way_lr:
        for idx, amt in WEIGHT_LR:
            w[idx] += amt

    nv = _vec5(need_vector) if need_vector is not None else [0.0] * N_RES
    if sum(nv) > 1e-9:
        # Blend table (structure-based) with EH need vector
        for i in range(N_RES):
            w[i] = 0.5 * w[i] + 0.5 * max(0.0, nv[i])
    # Avoid all-zero (cosine undefined → 0): tiny uniform if empty
    if sum(w) < 1e-9:
        w = [1.0] * N_RES
    return w


def way_need_weights(game: Any, player: Any, way_id: int) -> Tuple[List[float], Dict[str, Any]]:
    """Resolve need weights for way_id; returns (weights, meta)."""
    meta: Dict[str, Any] = {
        "req_cities": 0,
        "req_settles": 0,
        "req_roads": 0,
        "req_dcards": 0,
        "way_la": False,
        "way_lr": False,
        "engines": [],
        "source": "table",
    }
    need_vec = None
    # Prefer preferred/direction remaining if matches way
    try:
        direction = getattr(player, "strategic_direction", None) if player is not None else None
        if isinstance(direction, Mapping):
            d_way = _safe_int(
                direction.get("preferred_way_id") or direction.get("way_id"), None
            )
            if d_way is not None and int(d_way) == int(way_id):
                wr = direction.get("way_requirements")
                if isinstance(wr, Mapping):
                    meta["req_cities"] = int(
                        wr.get("cities") or wr.get("city_upgrades") or 0
                    )
                    meta["req_settles"] = int(
                        wr.get("settlements")
                        or wr.get("new_settlements")
                        or wr.get("required_new_intersections")
                        or 0
                    )
                    meta["req_roads"] = int(wr.get("roads") or wr.get("roads_to_build") or 0)
                    meta["req_dcards"] = int(
                        wr.get("dcards") or wr.get("dev_cards") or 0
                    )
                    meta["way_lr"] = bool(wr.get("longest_road") or wr.get("lr"))
                    meta["way_la"] = bool(
                        wr.get("largest_army") or wr.get("biggest_army") or wr.get("la")
                    )
                    meta["source"] = "direction.way_requirements"
                rem = direction.get("remaining") or direction.get("needed_rcards")
                if isinstance(rem, (list, tuple)):
                    need_vec = rem
                elif isinstance(rem, Mapping):
                    need_vec = _vec5(rem)
    except Exception:
        pass

    # Strategy table
    try:
        from core.strategy_timing import load_strategy_requirements

        for strategy in load_strategy_requirements() or []:
            if int(getattr(strategy, "way_id", -1)) != int(way_id):
                continue
            meta["req_cities"] = int(getattr(strategy, "city_upgrades", 0) or 0)
            meta["req_settles"] = int(
                getattr(strategy, "new_settlements_to_build", 0) or 0
            )
            meta["req_roads"] = int(getattr(strategy, "roads_to_build", 0) or 0)
            meta["req_dcards"] = int(
                getattr(strategy, "development_cards_to_buy", 0) or 0
            )
            meta["way_lr"] = bool(getattr(strategy, "longest_road", False))
            meta["way_la"] = bool(
                getattr(strategy, "biggest_army", False)
                or getattr(strategy, "largest_army", False)
            )
            cn = getattr(strategy, "calculated_need", None)
            if cn is not None and need_vec is None:
                need_vec = cn
            meta["source"] = "strategy_table"
            break
    except Exception:
        pass

    # Engines via parse_way_requirements when possible
    try:
        from core.ai_way_portfolio import parse_way_requirements
        from core.strategy_timing import load_strategy_requirements

        by_id = {}
        for strategy in load_strategy_requirements() or []:
            try:
                by_id[int(strategy.way_id)] = strategy
            except Exception:
                continue
        req = parse_way_requirements(
            way_id, requirements_by_id=by_id, player_state=player
        )
        engines = list(getattr(req, "resource_engines_needed", None) or [])
        meta["engines"] = engines
        nv = getattr(req, "need_vector", None)
        if nv is not None and sum(_vec5(nv)) > 0:
            need_vec = nv
        meta["req_cities"] = int(getattr(req, "required_cities", 0) or meta["req_cities"])
        meta["req_settles"] = int(
            getattr(req, "required_new_intersections", 0) or meta["req_settles"]
        )
        meta["req_roads"] = int(
            getattr(req, "required_roads_min", 0) or meta["req_roads"]
        )
        meta["req_dcards"] = int(getattr(req, "required_dcards", 0) or meta["req_dcards"])
        meta["way_lr"] = bool(getattr(req, "longest_road", False) or meta["way_lr"])
        meta["way_la"] = bool(getattr(req, "biggest_army", False) or meta["way_la"])
    except Exception:
        pass

    weights = need_weights_from_reqs(
        req_cities=meta["req_cities"],
        req_settles=meta["req_settles"],
        req_roads=meta["req_roads"],
        req_dcards=meta["req_dcards"],
        way_la=meta["way_la"],
        way_lr=meta["way_lr"],
        need_vector=need_vec,
    )
    if not meta["engines"]:
        # Derive engines from top weights
        ranked = sorted(range(N_RES), key=lambda i: weights[i], reverse=True)
        meta["engines"] = [
            RESOURCE_NAMES[i] for i in ranked if weights[i] >= 1.0
        ][:4]
    return weights, meta


def own_production_pips(game: Any, player: Any) -> List[float]:
    board = getattr(game, "board", None) if game is not None else None
    try:
        from core.resource_time_estimator import get_player_production_pips

        if board is not None and player is not None:
            return _vec5(get_player_production_pips(board, player))
    except Exception:
        pass
    try:
        if player is not None and board is not None and hasattr(
            player, "get_current_production_pips"
        ):
            return _vec5(player.get_current_production_pips(board))
    except Exception:
        pass
    return [0.0] * N_RES


def board_total_pips(game: Any) -> List[float]:
    """Sum hex pips by resource over the whole board (each tile once)."""
    board = getattr(game, "board", None) if game is not None else None
    totals = [0.0] * N_RES
    if board is None:
        return totals
    try:
        from core.resource_time_estimator import pips_from_dice_value
        from core.constants import TERRAIN_TO_RESOURCE, RESOURCE_ORDER
    except Exception:
        pips_from_dice_value = None  # type: ignore
        TERRAIN_TO_RESOURCE = {}  # type: ignore
        RESOURCE_ORDER = list(RESOURCE_NAMES)  # type: ignore

    tiles = getattr(board, "tiles", None) or getattr(board, "hexes", None) or []
    seen = set()
    for tile in list(tiles) or []:
        if tile is None:
            continue
        tid = id(tile)
        if tid in seen:
            continue
        seen.add(tid)
        terrain = getattr(tile, "type", None) or getattr(tile, "terrain", None)
        if terrain in (None, "Sea", "Desert", "Blank"):
            continue
        try:
            resource = TERRAIN_TO_RESOURCE.get(terrain)
        except Exception:
            resource = None
        if resource is None:
            # name match
            t = str(terrain or "").lower()
            for i, name in enumerate(RESOURCE_NAMES):
                if name.lower() in t or t in name.lower():
                    resource = name
                    break
        if resource is None:
            continue
        try:
            idx = list(RESOURCE_ORDER).index(resource) if resource in list(RESOURCE_ORDER) else RESOURCE_NAMES.index(str(resource))
        except Exception:
            try:
                idx = RESOURCE_NAMES.index(str(resource))
            except Exception:
                continue
        if pips_from_dice_value is not None:
            pips = pips_from_dice_value(
                getattr(tile, "value", None) or getattr(tile, "number", 0)
            )
        else:
            # classic: 2/12→1, 3/11→2, … 6/8→5, 7→0
            n = _safe_int(getattr(tile, "value", None) or getattr(tile, "number", 0), 0) or 0
            pips = float({2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}.get(n, 0))
        totals[idx] += float(pips or 0)

    # Fallback: sum unique intersection tile contribs if tiles empty
    if sum(totals) < 1e-9:
        try:
            from core.resource_time_estimator import get_intersection_resource_pips

            inters = getattr(board, "intersections", None) or []
            # Each tile is shared by ~3 vertices — divide by 3 to approximate
            acc = [0.0] * N_RES
            n = 0
            for inter in inters:
                if inter is None:
                    continue
                iid = getattr(inter, "id", None)
                if iid is None:
                    continue
                p = get_intersection_resource_pips(board, int(iid))
                acc = [a + _safe_float(x) for a, x in zip(acc, p)]
                n += 1
            if n:
                totals = [a / 3.0 for a in acc]
        except Exception:
            pass
    return totals


def fit_board_score(need_weights: Sequence[float], board_pips: Sequence[float]) -> float:
    """1 − scarcity_risk; scarcity high when top needs have low board totals."""
    need = _vec5(need_weights)
    board = _vec5(board_pips)
    total_need = sum(need)
    if total_need < 1e-9:
        return 1.0
    board_mean = sum(board) / N_RES
    if board_mean < 1e-9:
        return 0.0
    risk = 0.0
    for i in range(N_RES):
        if need[i] <= 0:
            continue
        # Relative scarcity: low board vs mean and vs need share
        ratio = board[i] / board_mean
        scarcity_i = max(0.0, 1.0 - ratio)
        # Extra if absolute board is thin (< 6 pips classic weak hex share)
        if board[i] < 6.0:
            scarcity_i = max(scarcity_i, (6.0 - board[i]) / 6.0 * 0.5)
        risk += (need[i] / total_need) * scarcity_i
    return _clamp01(1.0 - risk)


def missing_engines(
    own_pips: Sequence[float],
    engines: Sequence[str],
    *,
    thr: float = ENGINE_PIP_THR,
) -> List[int]:
    """Resource indices still weak for listed engine names."""
    own = _vec5(own_pips)
    missing: List[int] = []
    for name in engines or []:
        try:
            idx = RESOURCE_NAMES.index(str(name))
        except ValueError:
            # allow index-like
            idx = _safe_int(name, None)
            if idx is None or not (0 <= idx < N_RES):
                continue
        if own[idx] < thr and idx not in missing:
            missing.append(idx)
    return missing


def _spot_pips(board: Any, tid: int) -> List[float]:
    try:
        from core.resource_time_estimator import get_intersection_resource_pips

        return _vec5(get_intersection_resource_pips(board, int(tid)))
    except Exception:
        pass
    try:
        inter = board.intersections[int(tid)]
        return _vec5(getattr(inter, "all_tile_pips", None))
    except Exception:
        return [0.0] * N_RES


def collect_d2_spot_pips(game: Any, player: Any, *, max_distance: int = 2) -> List[Tuple[int, List[float]]]:
    """List (target_id, pips5) for reachable new settlements within max_distance roads."""
    board = getattr(game, "board", None) if game is not None else None
    if board is None or player is None:
        return []
    spots: Dict[int, List[float]] = {}
    # Portfolio candidates (preferred)
    try:
        from core.ai_way_portfolio import (
            MAX_ROAD_DISTANCE,
            WayRequirements,
            build_candidate_targets,
        )

        req = WayRequirements(
            way_id=0,
            required_new_intersections=1,
            required_cities=0,
            required_dcards=0,
            required_roads_min=0,
            needed_rcards={},
            resource_engines_needed=list(RESOURCE_NAMES),
        )
        cands = build_candidate_targets(
            game,
            player,
            req,
            max_targets=12,
            max_road_distance=min(int(max_distance), int(MAX_ROAD_DISTANCE)),
        )
        for c in cands or []:
            tid = _safe_int(getattr(c, "target_id", None) or (c.get("target_id") if isinstance(c, Mapping) else None), None)
            if tid is None:
                continue
            dist = _safe_int(
                getattr(c, "distance_roads", None)
                or (c.get("distance_roads") if isinstance(c, Mapping) else None),
                99,
            )
            if dist is not None and dist > max_distance:
                continue
            gain = getattr(c, "resource_gain_named", None)
            if isinstance(gain, Mapping):
                spots[tid] = _vec5(gain)
            else:
                spots[tid] = _spot_pips(board, tid)
    except Exception:
        pass
    # Outlook paths fallback
    if not spots:
        try:
            from core.outlook_logic import find_reachable_new_settlement_paths

            paths = find_reachable_new_settlement_paths(
                game, player, max_distance=max(1, int(max_distance))
            ) or []
            for path in paths:
                if not isinstance(path, Mapping):
                    continue
                tid = _safe_int(
                    path.get("target_settlement_id")
                    or path.get("intersection_id")
                    or path.get("target_id"),
                    None,
                )
                if tid is None:
                    continue
                dist = _safe_int(path.get("roads_remaining", path.get("distance", 99)), 99)
                if dist is not None and dist > max_distance:
                    continue
                spots[tid] = _spot_pips(board, tid)
        except Exception:
            pass
    return [(tid, pips) for tid, pips in spots.items()]


def fit_expand_score(
    own_pips: Sequence[float],
    engines: Sequence[str],
    spot_pips_list: Sequence[Sequence[float]],
    *,
    thr: float = ENGINE_PIP_THR,
    cover_thr: float = SPOT_COVER_PIP_THR,
) -> Tuple[float, Dict[str, Any]]:
    """Greedy cover of missing engines by d≤2 spots."""
    missing = missing_engines(own_pips, engines, thr=thr)
    meta: Dict[str, Any] = {
        "missing_engines": [RESOURCE_NAMES[i] for i in missing],
        "d2_count": len(list(spot_pips_list or [])),
        "covered": [],
    }
    if not missing:
        return 1.0, meta
    remaining = set(missing)
    covered: List[str] = []
    # Greedy: pick spot covering most remaining engines
    available = [ _vec5(s) for s in (spot_pips_list or []) ]
    while remaining and available:
        best_i = -1
        best_cover: List[int] = []
        for i, sp in enumerate(available):
            cov = [idx for idx in remaining if sp[idx] >= cover_thr]
            if len(cov) > len(best_cover):
                best_cover = cov
                best_i = i
        if best_i < 0 or not best_cover:
            break
        for idx in best_cover:
            remaining.discard(idx)
            covered.append(RESOURCE_NAMES[idx])
        available.pop(best_i)
    meta["covered"] = covered
    frac = (len(missing) - len(remaining)) / float(len(missing))
    return _clamp01(frac), meta


def compute_fit_scores(
    *,
    own_pips: Sequence[float],
    board_pips: Sequence[float],
    need_weights: Sequence[float],
    engines: Sequence[str],
    spot_pips_list: Sequence[Sequence[float]],
) -> Dict[str, Any]:
    """Pure scoring from vectors (unit-test friendly)."""
    own = _vec5(own_pips)
    board = _vec5(board_pips)
    need = _vec5(need_weights)
    fit_own = cosine_similarity(own, need)
    fit_board = fit_board_score(need, board)
    fit_expand, expand_meta = fit_expand_score(own, engines, spot_pips_list)
    fit_total = _clamp01(
        FIT_OWN_W * fit_own + FIT_BOARD_W * fit_board + FIT_EXPAND_W * fit_expand
    )
    return {
        "own_pips": [round(x, 3) for x in own],
        "board_pips": [round(x, 3) for x in board],
        "need_weights": [round(x, 3) for x in need],
        "d2_count": int(expand_meta.get("d2_count") or 0),
        "fit_own": round(fit_own, 4),
        "fit_board": round(fit_board, 4),
        "fit_expand": round(fit_expand, 4),
        "fit_total": round(fit_total, 4),
        "missing_engines": expand_meta.get("missing_engines") or [],
        "covered_engines": expand_meta.get("covered") or [],
    }


def compute_first_way_fit(
    game: Any,
    player: Any,
    way_id: Any,
) -> Optional[Dict[str, Any]]:
    """Compute first-way fit bag for ``way_id`` (no store)."""
    wid = _safe_int(way_id, None)
    if wid is None or wid <= 0:
        return None
    own = own_production_pips(game, player)
    board = board_total_pips(game)
    need, req_meta = way_need_weights(game, player, wid)
    engines = list(req_meta.get("engines") or [])
    spots = collect_d2_spot_pips(game, player, max_distance=2)
    spot_pips = [p for _, p in spots]
    scores = compute_fit_scores(
        own_pips=own,
        board_pips=board,
        need_weights=need,
        engines=engines,
        spot_pips_list=spot_pips,
    )
    bag: Dict[str, Any] = {
        "way_id": int(wid),
        "own_pips": scores["own_pips"],
        "board_pips": scores["board_pips"],
        "need_weights": scores["need_weights"],
        "d2_count": scores["d2_count"],
        "d2_spot_ids": [tid for tid, _ in spots[:12]],
        "fit_own": scores["fit_own"],
        "fit_board": scores["fit_board"],
        "fit_expand": scores["fit_expand"],
        "fit_total": scores["fit_total"],
        "engines": engines,
        "missing_engines": scores["missing_engines"],
        "covered_engines": scores["covered_engines"],
        "req": {
            "cities": req_meta.get("req_cities"),
            "settles": req_meta.get("req_settles"),
            "roads": req_meta.get("req_roads"),
            "dcards": req_meta.get("req_dcards"),
            "la": req_meta.get("way_la"),
            "lr": req_meta.get("way_lr"),
            "source": req_meta.get("source"),
        },
        "round": _safe_int(getattr(game, "round", None), None) if game is not None else None,
        "turn": _safe_int(getattr(game, "turn", None), None) if game is not None else None,
        "player_id": _safe_int(getattr(player, "id", None), None) if player is not None else None,
    }
    return bag


def already_has_first_way_fit(player: Any) -> bool:
    raw = getattr(player, "first_way_fit", None) if player is not None else None
    return isinstance(raw, Mapping) and raw.get("way_id") is not None


def snapshot_first_way_fit(
    game: Any,
    player: Any,
    way_id: Any = None,
    *,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Compute once and store on player.first_way_fit. Returns bag or None."""
    if player is None:
        return None
    if already_has_first_way_fit(player) and not force:
        return dict(getattr(player, "first_way_fit") or {})
    wid = way_id
    if wid is None:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            wid = sticky.get("locked_way_id")
        if wid is None:
            direction = getattr(player, "strategic_direction", None)
            if isinstance(direction, Mapping):
                wid = direction.get("preferred_way_id") or direction.get("way_id")
    bag = compute_first_way_fit(game, player, wid)
    if bag is None:
        return None
    try:
        setattr(player, "first_way_fit", dict(bag))
    except Exception:
        pass
    # Ensure ways_used includes first way
    try:
        from core.strategy_explicit_recalc import track_way_used

        track_way_used(player, bag.get("way_id"), switched=False)
    except Exception:
        pass
    return dict(bag)


def maybe_snapshot_on_first_lock(
    game: Any,
    player: Any,
    *,
    is_first_way: bool,
    way_id: Any = None,
) -> Optional[Dict[str, Any]]:
    """Hook for sticky publish: snapshot only on first way lock."""
    if not is_first_way:
        return None
    return snapshot_first_way_fit(game, player, way_id=way_id, force=False)


def collect_first_way_fit_by_seat(game: Any) -> Dict[str, Any]:
    """End-of-game map seat → first_way_fit bag (compact)."""
    out: Dict[str, Any] = {}
    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None:
            continue
        raw = getattr(p, "first_way_fit", None)
        if not isinstance(raw, Mapping):
            continue
        out[str(pid)] = {
            "way_id": raw.get("way_id"),
            "fit_own": raw.get("fit_own"),
            "fit_board": raw.get("fit_board"),
            "fit_expand": raw.get("fit_expand"),
            "fit_total": raw.get("fit_total"),
            "d2_count": raw.get("d2_count"),
            "own_pips": raw.get("own_pips"),
            "board_pips": raw.get("board_pips"),
        }
    return out


def cs_fields_from_first_way_fit(player: Any) -> Dict[str, Any]:
    """Additive CS fields from player.first_way_fit."""
    out = {
        "first_way_id": None,
        "first_way_fit_own": None,
        "first_way_fit_board": None,
        "first_way_fit_expand": None,
        "first_way_fit_total": None,
        "first_way_fit_d2_count": None,
    }
    raw = getattr(player, "first_way_fit", None) if player is not None else None
    if not isinstance(raw, Mapping):
        return out
    out["first_way_id"] = _safe_int(raw.get("way_id"), None)
    out["first_way_fit_own"] = _safe_float(raw.get("fit_own"), default=float("nan"))
    if out["first_way_fit_own"] != out["first_way_fit_own"]:
        out["first_way_fit_own"] = None
    else:
        out["first_way_fit_own"] = float(out["first_way_fit_own"])
    for src, dst in (
        ("fit_board", "first_way_fit_board"),
        ("fit_expand", "first_way_fit_expand"),
        ("fit_total", "first_way_fit_total"),
    ):
        v = raw.get(src)
        try:
            out[dst] = float(v) if v is not None else None
        except Exception:
            out[dst] = None
    out["first_way_fit_d2_count"] = _safe_int(raw.get("d2_count"), None)
    return out


__all__ = [
    "RESOURCE_NAMES",
    "cosine_similarity",
    "need_weights_from_reqs",
    "way_need_weights",
    "own_production_pips",
    "board_total_pips",
    "fit_board_score",
    "fit_expand_score",
    "compute_fit_scores",
    "compute_first_way_fit",
    "snapshot_first_way_fit",
    "maybe_snapshot_on_first_lock",
    "collect_first_way_fit_by_seat",
    "cs_fields_from_first_way_fit",
    "already_has_first_way_fit",
]
