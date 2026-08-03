"""core/ai_way_portfolio.py

Phase 4G board-grounded way portfolio re-estimation (4G-A visibility-first).

Layers: (1) requirement parser (2) portfolio builder (3) selector (4) shallow scenarios.
Guardrails: max 2 critical contested races / 4 branches; portfolio repair on lose;
no mid-branch way switching; 4G-B optional preferred_way override via behavior_override.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RESOURCE_ORDER = ["Wheat", "Ore", "Wood", "Brick", "Sheep"]
INFINITE_TURNS = 9999.0
DEFAULT_PRODUCTION_HORIZON_TURNS = 12.0
MAX_TARGETS_PER_WAY = 8
MAX_COMBOS = 70
MAX_ROAD_DISTANCE = 2
MAX_CRITICAL_RACES = 2
BOARD_OVERRIDE_MIN_RANK_EDGE = 0.75
BOARD_OVERRIDE_BURIED_INDEX = 2  # 0-based: abstract at rank 3+ favors board#1
BOARD_OVERRIDE_REQUIRE_FEASIBLE = True
FRAGILITY_RANK = {"low": 0, "medium": 1, "high": 2}
# PR-B / product 1b: race ETA margin (own turns) for risk upgrade
RACE_ETA_MARGIN = 0.5
# PR-F prioritization weights (priority_score = win_delta - λ_η·self_eta - λ_r·risk_pen)
PRIORITY_LAMBDA_ETA = 0.35
PRIORITY_LAMBDA_RISK = 1.0
# Fallback L2 way cap when game stage is unknown (prefer portfolio_top_n_for_game).
PORTFOLIO_EVAL_TOP_N = 9
PORTFOLIO_CACHE_ENABLED = True


def _resolve_portfolio_top_n(game: Any = None, limit: Optional[int] = None) -> int:
    """Early 3 / Mid 6 / End 9 (policy D); explicit limit wins when provided."""
    if limit is not None:
        try:
            return max(1, int(limit))
        except Exception:
            pass
    try:
        from core.strategy_reconsider import portfolio_top_n_for_game

        return max(1, int(portfolio_top_n_for_game(game)))
    except Exception:
        return int(PORTFOLIO_EVAL_TOP_N)


@dataclass
class PortfolioTarget:
    target_id: int
    kind: str
    resource_gain_named: Dict[str, float]
    roads_to_build: List[List[int]]
    distance_roads: int
    race_status: str
    portfolio_role: str
    reason: str
    score: float = 0.0
    port: Optional[str] = None
    # PR-A / PR-B timing + risk pack (optional; defaults keep old call sites working)
    risk_level: str = "low"
    risk_score: float = 0.0
    risk_reasons: List[str] = field(default_factory=list)
    block_sites: List[Dict[str, Any]] = field(default_factory=list)
    threat_opponents: List[Dict[str, Any]] = field(default_factory=list)
    # PR-B minimal: own expected turns if this target is prioritized #1
    self_eta_own_turns: Optional[float] = None
    self_eta_source: str = ""
    # Win-span (PR-B)
    baseline_win_turns: Optional[float] = None
    win_turns_if_target: Optional[float] = None
    win_delta: Optional[float] = None
    # PR-F prioritization
    priority_score: Optional[float] = None
    priority_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BranchScenario:
    name: str
    portfolio: List[PortfolioTarget]
    realistic_turns: float
    feasibility: str
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["portfolio"] = [t.as_dict() if hasattr(t, "as_dict") else asdict(t) for t in self.portfolio]
        return d


@dataclass
class WayRequirements:
    way_id: int
    required_new_intersections: int
    required_cities: int
    required_dcards: int
    required_roads_min: int
    needed_rcards: Dict[str, float]
    resource_engines_needed: List[str]
    longest_road: bool = False
    biggest_army: bool = False
    abstract_expected_turns: float = INFINITE_TURNS
    need_vector: Tuple[float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WayBoardAudit:
    way_id: int
    abstract_expected_turns: float
    realistic_expected_turns: float
    board_expected_turns: float
    best_case_turns: float
    fallback_case_turns: float
    feasibility: str
    fragility: str
    target_portfolio: List[PortfolioTarget]
    critical_race_targets: List[int]
    branches: List[BranchScenario]
    needed_rcards_before: Dict[str, float]
    needed_rcards_after: Dict[str, float]
    recommendation: str
    recommendation_target_id: Optional[int]
    requirements: Optional[Dict[str, Any]] = None
    rank_key: float = INFINITE_TURNS
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["target_portfolio"] = [t.as_dict() if hasattr(t, "as_dict") else asdict(t) for t in self.target_portfolio]
        d["branches"] = [b.as_dict() if hasattr(b, "as_dict") else asdict(b) for b in self.branches]
        return d


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _named_need(vector: Sequence[Any]) -> Dict[str, float]:
    vec = list(vector)[:5]
    while len(vec) < 5:
        vec.append(0.0)
    return {RESOURCE_ORDER[i]: round(_safe_float(vec[i]), 3) for i in range(5)}


def _normalize_way_ids(top_ways: Any) -> List[int]:
    out: List[int] = []
    seen = set()
    for item in list(top_ways or []):
        if isinstance(item, Mapping):
            way_id = item.get("way_id") or item.get("preferred_way_id") or item.get("id")
        else:
            way_id = item
        wid = _safe_int(way_id, -1)
        if wid < 0 or wid in seen:
            continue
        seen.add(wid)
        out.append(wid)
    return out


def _road_pairs(roads: Sequence[Any]) -> List[List[int]]:
    out: List[List[int]] = []
    for raw in roads or []:
        try:
            a, b = list(raw)[:2]
            ai, bi = int(a), int(b)
            if ai == bi:
                continue
            pair = [min(ai, bi), max(ai, bi)]
            if pair not in out:
                out.append(pair)
        except Exception:
            continue
    return out


def _pips_named(board: Any, target_id: int) -> Dict[str, float]:
    try:
        from core.resource_time_estimator import get_intersection_resource_pips
        pips = get_intersection_resource_pips(board, int(target_id))
        return {RESOURCE_ORDER[i]: round(_safe_float(pips[i]), 3) for i in range(5) if _safe_float(pips[i]) > 1e-9}
    except Exception:
        return {}


def _port_at(board: Any, target_id: int) -> Optional[str]:
    try:
        inter = board.intersections[int(target_id)]
        port = getattr(inter, "port", None) or getattr(inter, "port_type", None)
        text = str(port or "").strip()
        if not text or text.lower() == "blank":
            return None
        return text
    except Exception:
        return None


def _num_players(game: Any) -> int:
    try:
        return max(1, len(list(getattr(game, "players", []) or [])))
    except Exception:
        return 4



def parse_way_requirements(way_id, *, requirements_by_id=None, player_state=None, abstract_expected_turns=INFINITE_TURNS):
    strategy = None
    if requirements_by_id is not None:
        strategy = requirements_by_id.get(int(way_id))
    if strategy is None:
        return WayRequirements(way_id=int(way_id), required_new_intersections=0, required_cities=0, required_dcards=0, required_roads_min=0, needed_rcards={}, resource_engines_needed=[], abstract_expected_turns=_safe_float(abstract_expected_turns, INFINITE_TURNS))
    remaining = None
    if player_state is not None:
        try:
            from core.strategy_timing import calculate_remaining_need
            remaining = calculate_remaining_need(strategy, player_state)
        except Exception:
            remaining = None
    if remaining is not None:
        need_vec = tuple(remaining.need_vector)
        req = WayRequirements(way_id=int(way_id), required_new_intersections=int(remaining.remaining_new_settlements), required_cities=int(remaining.remaining_city_upgrades), required_dcards=int(remaining.remaining_dev_cards_to_buy), required_roads_min=int(remaining.remaining_roads_to_build), needed_rcards=_named_need(need_vec), resource_engines_needed=[], longest_road=bool(getattr(strategy, "longest_road", False)), biggest_army=bool(getattr(strategy, "biggest_army", False)), abstract_expected_turns=_safe_float(abstract_expected_turns, INFINITE_TURNS), need_vector=need_vec)
    else:
        need_vec = tuple(getattr(strategy, "calculated_need", (0, 0, 0, 0, 0)))
        req = WayRequirements(way_id=int(way_id), required_new_intersections=int(getattr(strategy, "new_settlements_to_build", 0) or 0), required_cities=int(getattr(strategy, "city_upgrades", 0) or 0), required_dcards=int(getattr(strategy, "development_cards_to_buy", 0) or 0), required_roads_min=int(getattr(strategy, "roads_to_build", 0) or 0), needed_rcards=_named_need(need_vec), resource_engines_needed=[], longest_road=bool(getattr(strategy, "longest_road", False)), biggest_army=bool(getattr(strategy, "biggest_army", False)), abstract_expected_turns=_safe_float(abstract_expected_turns, INFINITE_TURNS), need_vector=need_vec)
    engines = [name for name, amount in req.needed_rcards.items() if _safe_float(amount) >= 2.0]
    if req.required_cities > 0 or req.required_dcards > 0:
        for name in ("Wheat", "Ore", "Sheep"):
            if name not in engines:
                engines.append(name)
    if req.required_new_intersections > 0 or req.required_roads_min > 0:
        for name in ("Wood", "Brick"):
            if name not in engines:
                engines.append(name)
    req.resource_engines_needed = engines
    return req


def _race_status_from_risk(risk):
    level = str(risk.get("risk_level", "low") or "low").lower()
    if level == "blocked":
        return "likely_lost"
    if level in ("high", "medium"):
        return "contested"
    return "safe"


def _assign_portfolio_role(*, pips_named, engines, race_status, distance_roads, port, current_pips_named):
    engine_set = set(engines or [])
    gains = {k: _safe_float(v) for k, v in (pips_named or {}).items() if _safe_float(v) > 0}
    total_pips = sum(gains.values())
    bottleneck_hits = []
    for eng in engine_set:
        current = _safe_float(current_pips_named.get(eng, 0.0))
        gain = _safe_float(gains.get(eng, 0.0))
        if gain >= 2.0 and current < 2.0:
            bottleneck_hits.append(eng)
        elif gain >= 3.0 and current < 3.5:
            bottleneck_hits.append(eng)
    port_helps = False
    if port:
        port_l = port.lower()
        for eng in engine_set:
            if eng.lower() in port_l or (eng == "Sheep" and "wool" in port_l):
                port_helps = True
            if "3:1" in port_l or "2:1" in port_l:
                port_helps = True
    if bottleneck_hits and total_pips >= 4.0:
        role, reason = "critical", "hard bottleneck " + "/".join(bottleneck_hits)
    elif bottleneck_hits:
        role, reason = "important", "helps bottleneck " + "/".join(bottleneck_hits)
    elif port_helps and total_pips >= 3.0:
        role, reason = "important", "port+production " + str(port)
    elif total_pips >= 6.0:
        role, reason = "important", "strong production node"
    elif total_pips >= 3.0:
        role, reason = "useful", "solid production"
    else:
        role, reason = "optional", "low production value"
    if race_status == "likely_lost" and role == "critical":
        reason = reason + "; race pressure high"
    if distance_roads >= 2 and role == "optional":
        reason = reason + "; distant"
    return role, reason


def build_candidate_targets(game, player, requirements, *, max_targets=MAX_TARGETS_PER_WAY, max_road_distance=MAX_ROAD_DISTANCE):
    board = getattr(game, "board", None)
    if board is None or player is None:
        return []
    try:
        from core.resource_time_estimator import get_player_production_pips
        current_pips_named = _named_need(get_player_production_pips(board, player))
    except Exception:
        current_pips_named = {n: 0.0 for n in RESOURCE_ORDER}
    paths = []
    try:
        from core.outlook_logic import find_reachable_new_settlement_paths, next_settlement_spots
        paths = list(find_reachable_new_settlement_paths(game, player, max_distance=max(1, min(3, int(max_road_distance)))) or [])
        try:
            pid = int(getattr(player, "id"))
            for tid in next_settlement_spots(game, pid) or []:
                paths.append({"kind": "next_settlement", "target_settlement_id": int(tid), "roads_to_build": [], "roads_remaining": 0, "distance": 0})
        except Exception:
            pass
    except Exception:
        paths = []
    best_by_target = {}
    for path in paths:
        try:
            tid = int(path.get("target_settlement_id") or path.get("intersection_id") or path.get("target_id"))
        except Exception:
            continue
        dist = _safe_int(path.get("roads_remaining", path.get("distance", 99)), 99)
        prev = best_by_target.get(tid)
        if prev is None or dist < _safe_int(prev.get("roads_remaining", prev.get("distance", 99)), 99):
            best_by_target[tid] = path
    candidates = []
    for tid, path in best_by_target.items():
        roads = _road_pairs(path.get("roads_to_build") or [])
        dist = len(roads) if roads else _safe_int(path.get("roads_remaining", path.get("distance", 0)), 0)
        if dist > max_road_distance:
            continue
        pips_named = _pips_named(board, tid)
        port = _port_at(board, tid)
        risk = {}
        try:
            from core.risk_assessment import assess_new_settlement_path_risk, opponent_settlement_race_risk
            risk = assess_new_settlement_path_risk(game, player, tid, roads) if roads else opponent_settlement_race_risk(game, player, tid)
        except Exception:
            risk = {"risk_level": "low", "risk_score": 0.0, "threat_opponents": [], "block_sites": [], "reasons": []}
        race_status = _race_status_from_risk(risk)
        role, reason = _assign_portfolio_role(pips_named=pips_named, engines=requirements.resource_engines_needed, race_status=race_status, distance_roads=dist, port=port, current_pips_named=current_pips_named)
        total_pips = sum(_safe_float(v) for v in pips_named.values())
        score = total_pips * 3.0 + (4.0 if port else 0.0)
        score += {"critical": 8.0, "important": 4.0, "useful": 2.0, "optional": 0.0}.get(role, 0.0)
        score -= {"safe": 0.0, "contested": 3.0, "likely_lost": 8.0}.get(race_status, 0.0)
        score -= float(dist) * 2.5 + _safe_float(risk.get("risk_score", 0.0)) * 0.05
        # PR-B minimal: self ETA if this intersection is prioritized #1
        self_eta, self_eta_src = _estimate_self_eta_own_turns(
            game, player, distance_roads=int(dist), target_id=int(tid)
        )
        risk_level = str(risk.get("risk_level", "low") or "low").lower()
        threats = list(risk.get("threat_opponents") or [])
        # Only attach threat list when med/high/blocked (product: no opp detail if low)
        if risk_level in ("low", "safe", ""):
            threats_out: List[Dict[str, Any]] = []
        else:
            threats_out = [dict(t) for t in threats if isinstance(t, Mapping)]
        candidates.append(
            PortfolioTarget(
                target_id=int(tid),
                kind=("next_settlement" if dist == 0 else "new_settlement"),
                resource_gain_named=pips_named,
                roads_to_build=roads,
                distance_roads=int(dist),
                race_status=race_status,
                portfolio_role=role,
                reason=reason,
                score=round(score, 3),
                port=port,
                risk_level=risk_level,
                risk_score=_safe_float(risk.get("risk_score", 0.0)),
                risk_reasons=[str(r) for r in list(risk.get("reasons") or [])[:6]],
                block_sites=[dict(b) for b in list(risk.get("block_sites") or []) if isinstance(b, Mapping)],
                threat_opponents=threats_out,
                self_eta_own_turns=self_eta,
                self_eta_source=self_eta_src,
            )
        )
    candidates.sort(key=lambda t: (-t.score, t.distance_roads, t.target_id))
    usable = [c for c in candidates if c.race_status != "likely_lost"]
    if len(usable) < max(1, requirements.required_new_intersections):
        usable = candidates
    return usable[: max(1, int(max_targets))]


def _estimate_self_eta_own_turns(
    game: Any,
    player: Any,
    *,
    distance_roads: int,
    target_id: int,
) -> Tuple[Optional[float], str]:
    """Expected own turns to build on target if prioritized #1 (PR-B).

    Prefers resource_time_estimator (settle + extra roads). Falls back to a
    simple road-count heuristic so UI always has a number when possible.
    """
    dist = max(0, int(distance_roads or 0))
    try:
        from core.resource_time_estimator import estimate_action_time

        board = getattr(game, "board", None)
        if board is not None and player is not None:
            est = estimate_action_time(
                board,
                player,
                "settlement",
                target_id=int(target_id),
                extra_roads_needed=dist,
            )
            turns = None
            if isinstance(est, Mapping):
                turns = est.get("turns")
            else:
                turns = getattr(est, "turns", None)
            if turns is not None:
                t = float(turns)
                if t < 9000:
                    return round(t, 2), "eh_settle_plus_roads"
    except Exception:
        pass
    # Heuristic: ~1.5 own turns per road + ~2 for the settlement package
    stub = round(float(dist) * 1.5 + 2.0, 2)
    return stub, "stub_road_settle"


def _estimate_player_eta_to_site(
    game: Any,
    player: Any,
    *,
    site_id: int,
    roads_needed: Optional[int] = None,
) -> Tuple[Optional[float], str]:
    """EH (or stub) own-turns for *player* to settle site_id if they prioritize it."""
    dist = 0 if roads_needed is None else max(0, int(roads_needed))
    if roads_needed is None:
        try:
            from core.risk_assessment import _min_empty_roads_to_reach

            reached = _min_empty_roads_to_reach(game, player, int(site_id), max_depth=3)
            if reached is None:
                return None, "unreachable"
            dist = int(reached)
        except Exception:
            dist = 2
    return _estimate_self_eta_own_turns(
        game, player, distance_roads=dist, target_id=int(site_id)
    )


def _fill_threat_opponent_etas(
    game: Any,
    threats: Sequence[Mapping[str, Any]],
    *,
    race_target_id: int,
) -> List[Dict[str, Any]]:
    """Attach eta_own_turns for race (to T) or block (to kill-site)."""
    out: List[Dict[str, Any]] = []
    players_by_id: Dict[int, Any] = {}
    for p in list(getattr(game, "players", []) or []):
        try:
            players_by_id[int(getattr(p, "id"))] = p
        except Exception:
            continue

    for raw in threats:
        if not isinstance(raw, Mapping):
            continue
        t = dict(raw)
        pid = t.get("player_id")
        opp = None
        try:
            if pid is not None:
                opp = players_by_id.get(int(pid))
        except Exception:
            opp = None
        if opp is None:
            # Match by color
            col = str(t.get("color") or "")
            for p in list(getattr(game, "players", []) or []):
                if str(getattr(p, "color", "")) == col:
                    opp = p
                    break
        if opp is None:
            out.append(t)
            continue

        mode = str(t.get("mode") or "race").lower()
        roads_needed = t.get("roads_needed")
        try:
            roads_needed_i = int(roads_needed) if roads_needed is not None else None
        except Exception:
            roads_needed_i = None

        if mode == "block" and t.get("block_site") is not None:
            site = int(t["block_site"])
            eta, src = _estimate_player_eta_to_site(
                game, opp, site_id=site, roads_needed=roads_needed_i
            )
            t["eta_own_turns"] = eta
            t["eta_source"] = src
            t["eta_site"] = site
        else:
            eta, src = _estimate_player_eta_to_site(
                game, opp, site_id=int(race_target_id), roads_needed=roads_needed_i
            )
            t["eta_own_turns"] = eta
            t["eta_source"] = src
            t["eta_site"] = int(race_target_id)
        out.append(t)
    return out


def _portfolio_forcing_target(
    portfolio: Sequence[PortfolioTarget],
    candidates: Sequence[PortfolioTarget],
    requirements: WayRequirements,
    forced: PortfolioTarget,
) -> List[PortfolioTarget]:
    """Build a portfolio of the same size that includes *forced* as a settle target."""
    k = max(0, int(requirements.required_new_intersections or 0))
    if k <= 0:
        return [forced]
    if any(int(t.target_id) == int(forced.target_id) for t in portfolio):
        # Keep selected portfolio; put forced first for readability
        rest = [t for t in portfolio if int(t.target_id) != int(forced.target_id)]
        return [forced] + list(rest)
    pool = [t for t in candidates if int(t.target_id) != int(forced.target_id)]
    pool.sort(key=lambda t: (-float(t.score), int(t.distance_roads), int(t.target_id)))
    return [forced] + pool[: max(0, k - 1)]


def _best_board_turns_including_target(
    game: Any,
    player: Any,
    requirements: WayRequirements,
    candidates: Sequence[PortfolioTarget],
    forced: PortfolioTarget,
    *,
    fallback_portfolio: Sequence[PortfolioTarget],
) -> float:
    """Min board-expected turns among portfolios that include *forced*."""
    cand_list = list(candidates or [])
    best: Optional[float] = None
    try:
        ports = select_portfolios(cand_list, requirements, max_combos=min(40, MAX_COMBOS))
    except Exception:
        ports = []
    for p in ports or []:
        if not any(int(x.target_id) == int(forced.target_id) for x in p):
            continue
        try:
            turns = estimate_board_turns_for_portfolio(game, player, requirements, list(p))
        except Exception:
            continue
        if best is None or turns < best:
            best = float(turns)
    if best is not None:
        return best
    forced_port = _portfolio_forcing_target(
        list(fallback_portfolio or []), cand_list, requirements, forced
    )
    return float(
        estimate_board_turns_for_portfolio(game, player, requirements, forced_port)
    )


def _expand_soft_race_threats(
    game: Any,
    player: Any,
    target: PortfolioTarget,
    *,
    max_depth: int = MAX_ROAD_DISTANCE,
) -> None:
    """PR-C: merge race-mode threats for opponents within *max_depth* empty roads of T.

    Runs even when geometry risk is low (threat list may have been stripped at
    candidate build). Does not change risk_level; ETA upgrade does that next.
    """
    try:
        from core.risk_assessment import (
            _dedupe_threats,
            _min_empty_roads_to_reach,
            _opponent_players,
            _threat_record,
        )
    except Exception:
        return
    try:
        tid = int(target.target_id)
    except Exception:
        return
    existing: List[Dict[str, Any]] = [
        dict(t) for t in list(target.threat_opponents or []) if isinstance(t, Mapping)
    ]
    try:
        opps = list(_opponent_players(game, player) or [])
    except Exception:
        opps = []
    for opp in opps:
        try:
            roads = _min_empty_roads_to_reach(
                game, opp, tid, max_depth=int(max_depth)
            )
        except Exception:
            roads = None
        if roads is None:
            continue
        rn = int(roads)
        if rn == 0:
            reason = f"network reaches @{tid}"
        elif rn == 1:
            reason = f"1 road from @{tid}"
        else:
            reason = f"{rn} roads from @{tid}"
        existing.append(
            _threat_record(
                player=opp,
                mode="race",
                roads_needed=rn,
                reason=reason,
            )
        )
    try:
        target.threat_opponents = _dedupe_threats(existing)
    except Exception:
        target.threat_opponents = existing


def _upgrade_risk_with_race_eta(target: PortfolioTarget) -> None:
    """Product 1b / PR-C: raise risk when an opponent can beat/race us on the clock.

    Compares best threat ``eta_own_turns`` to ``self_eta_own_turns`` with
    ``RACE_ETA_MARGIN``. Never *lowers* geometry/spoiler risk (block_sites and
    prior medium/high stay). May raise low→medium/high when soft race ETAs race us.
    """
    self_eta = target.self_eta_own_turns
    if self_eta is None:
        return
    try:
        self_f = float(self_eta)
    except Exception:
        return
    etas: List[float] = []
    for t in list(target.threat_opponents or []):
        if not isinstance(t, Mapping):
            continue
        raw = t.get("eta_own_turns")
        if raw is None:
            continue
        try:
            e = float(raw)
        except Exception:
            continue
        if e < 9000:
            etas.append(e)
    if not etas:
        return
    best = min(etas)
    margin = float(RACE_ETA_MARGIN)
    level = str(target.risk_level or "low").lower()
    rank = {"low": 0, "medium": 1, "med": 1, "high": 2, "blocked": 3}
    cur = rank.get(level, 0)
    prev = cur
    reason = ""
    # Opponent finishes strictly sooner → high
    if best + margin < self_f:
        cur = max(cur, 2)
        reason = f"ETA race: best opp {best:.1f}t beats self {self_f:.1f}t"
    # Opponent within margin of our ETA → at least medium
    elif best <= self_f + margin:
        cur = max(cur, 1)
        reason = f"ETA race: best opp {best:.1f}t within margin of self {self_f:.1f}t"
    inv = {0: "low", 1: "medium", 2: "high", 3: "blocked"}
    target.risk_level = inv.get(cur, level)
    target.race_status = _race_status_from_risk({"risk_level": target.risk_level})
    if cur > prev:
        # Raise score floor to match geometry bands; never lower
        floors = {1: 20.0, 2: 45.0, 3: 99.0}
        try:
            target.risk_score = max(float(target.risk_score or 0.0), floors.get(cur, 0.0))
        except Exception:
            target.risk_score = floors.get(cur, 0.0)
        if reason:
            notes = list(target.risk_reasons or [])
            if reason not in notes:
                notes.append(reason)
            target.risk_reasons = notes[:8]


def attach_timing_pack_to_portfolio(
    game: Any,
    player: Any,
    requirements: WayRequirements,
    portfolio: Sequence[PortfolioTarget],
    candidates: Sequence[PortfolioTarget],
    *,
    baseline_win_turns: float,
) -> List[PortfolioTarget]:
    """PR-B + PR-C: self_eta, win-span, soft race threats, opp ETAs, ETA risk upgrade."""
    baseline = _safe_float(baseline_win_turns, INFINITE_TURNS)
    if baseline >= INFINITE_TURNS / 2:
        # Fall back to portfolio EH if baseline looks empty
        try:
            baseline = estimate_board_turns_for_portfolio(
                game, player, requirements, list(portfolio)
            )
        except Exception:
            pass
    baseline = float(min(max(baseline, 0.0), INFINITE_TURNS))
    cand_list = list(candidates or [])
    port_list = list(portfolio or [])

    for t in port_list:
        if not isinstance(t, PortfolioTarget):
            continue
        # Self ETA
        if t.self_eta_own_turns is None:
            eta, src = _estimate_self_eta_own_turns(
                game,
                player,
                distance_roads=int(t.distance_roads or 0),
                target_id=int(t.target_id),
            )
            t.self_eta_own_turns = eta
            t.self_eta_source = src

        # Win span: preferred-way total (baseline) vs best portfolio that includes T
        try:
            win_if = _best_board_turns_including_target(
                game,
                player,
                requirements,
                cand_list,
                t,
                fallback_portfolio=port_list,
            )
        except Exception:
            win_if = baseline
        t.baseline_win_turns = round(baseline, 2) if baseline < 9000 else None
        t.win_turns_if_target = round(float(win_if), 2) if float(win_if) < 9000 else None
        if t.baseline_win_turns is not None and t.win_turns_if_target is not None:
            t.win_delta = round(t.baseline_win_turns - t.win_turns_if_target, 2)
        else:
            t.win_delta = None

        # PR-C: soft race threats even when geometry risk is low / list was stripped
        try:
            _expand_soft_race_threats(game, player, t)
        except Exception:
            pass
        # Opponent ETAs on geometry + soft race threats
        if t.threat_opponents:
            t.threat_opponents = _fill_threat_opponent_etas(
                game, t.threat_opponents, race_target_id=int(t.target_id)
            )
        # Product 1b / PR-C ETA race upgrade (never lowers geometry/spoiler)
        _upgrade_risk_with_race_eta(t)
        # After upgrade, if still low, clear threat list for UI (no opp detail)
        if str(t.risk_level or "low").lower() in ("low", "safe", ""):
            t.threat_opponents = []
        elif t.threat_opponents is None:
            t.threat_opponents = []

    return port_list


def _combo_base_score(combo, requirements):
    score = sum(t.score for t in combo)
    covered = set()
    for t in combo:
        for res, pips in (t.resource_gain_named or {}).items():
            if _safe_float(pips) >= 2.0:
                covered.add(res)
    for eng in requirements.resource_engines_needed:
        score += 2.0 if eng in covered else -1.0
    score -= 1.5 * sum(1 for t in combo if t.portfolio_role == "critical" and t.race_status == "contested")
    return score


def select_portfolios(candidates, requirements, *, max_combos=MAX_COMBOS):
    k = max(0, int(requirements.required_new_intersections))
    if k == 0:
        return [[]]
    pool = list(candidates)
    if len(pool) < k:
        return [pool] if pool else [[]]
    ranked = [(_combo_base_score(combo, requirements), combo) for combo in combinations(pool, k)]
    ranked.sort(key=lambda x: (-x[0], [t.target_id for t in x[1]]))
    out, seen = [], set()
    for _score, combo in ranked:
        key = frozenset(t.target_id for t in combo)
        if key in seen:
            continue
        seen.add(key)
        out.append(list(combo))
        if len(out) >= max_combos:
            break
    return out


def _critical_contested(portfolio):
    crit = [t for t in portfolio if t.portfolio_role == "critical" and t.race_status == "contested"]
    crit.sort(key=lambda t: (-t.score, t.target_id))
    return crit[:MAX_CRITICAL_RACES]


def _portfolio_need_vector(requirements, portfolio):
    try:
        from core.strategy_timing import strategy_cost_from_components
        road_count = sum(max(0, int(t.distance_roads)) for t in portfolio)
        n_settle = len(portfolio) if requirements.required_new_intersections > 0 else requirements.required_new_intersections
        roads = road_count if requirements.required_new_intersections > 0 else requirements.required_roads_min
        need = strategy_cost_from_components(new_settlements=n_settle, city_upgrades=requirements.required_cities, roads=roads, dev_cards=requirements.required_dcards)
        shortfall = max(0, requirements.required_new_intersections - len(portfolio))
        if shortfall > 0:
            extra = strategy_cost_from_components(new_settlements=shortfall, city_upgrades=0, roads=shortfall * 2, dev_cards=0)
            need = tuple(_safe_float(need[i]) + _safe_float(extra[i]) for i in range(5))
        return [float(x) for x in need]
    except Exception:
        return list(requirements.need_vector)


def _production_credit_vector(portfolio, horizon):
    credit = [0.0] * 5
    for t in portfolio:
        for i, name in enumerate(RESOURCE_ORDER):
            pips = _safe_float((t.resource_gain_named or {}).get(name, 0.0))
            if pips <= 0:
                continue
            credit[i] += min(pips * 0.35 * (horizon / DEFAULT_PRODUCTION_HORIZON_TURNS), pips * 0.5)
    return credit


def estimate_board_turns_for_portfolio(game, player, requirements, portfolio, *, incomplete_penalty_turns=0.0):
    board = getattr(game, "board", None)
    if board is None or player is None:
        return INFINITE_TURNS
    need = _portfolio_need_vector(requirements, portfolio)
    credit = _production_credit_vector(portfolio, DEFAULT_PRODUCTION_HORIZON_TURNS)
    adjusted = [max(0.0, need[i] - credit[i] * 0.5) for i in range(5)]
    try:
        from core.resource_time_estimator import get_player_production_pips, get_player_resource_cards_vector, get_player_trade_rates
        from core.strategy_timing import estimate_resource_requirement_time
        estimate = estimate_resource_requirement_time(current_hand=get_player_resource_cards_vector(player), production_pips=get_player_production_pips(board, player), need=adjusted, trade_rates=get_player_trade_rates(board, player), num_players=_num_players(game), require_confidence=False)
        turns = _safe_float(estimate.get("turns", INFINITE_TURNS), INFINITE_TURNS)
    except Exception:
        turns = max(1.0, sum(adjusted) / 1.5)
    if incomplete_penalty_turns > 0:
        turns += incomplete_penalty_turns
    if requirements.required_new_intersections > len(portfolio) and requirements.required_new_intersections > 0:
        turns += 6.0 * (requirements.required_new_intersections - len(portfolio))
    return float(min(max(turns, 0.0), INFINITE_TURNS))


def _repair_portfolio(lost, portfolio, candidates):
    remaining = [t for t in portfolio if t.target_id != lost.target_id]
    used = {t.target_id for t in remaining}
    replacements = [c for c in candidates if c.target_id not in used and c.target_id != lost.target_id]
    replacements.sort(key=lambda t: (0 if t.portfolio_role in ("critical", "important") else 1, 0 if t.race_status == "safe" else 1, -t.score, t.distance_roads))
    if not replacements:
        return remaining, False
    remaining.append(replacements[0])
    remaining.sort(key=lambda t: (-t.score, t.target_id))
    return remaining, True


def evaluate_portfolio_scenarios(game, player, requirements, portfolio, candidates):
    base_turns = estimate_board_turns_for_portfolio(game, player, requirements, portfolio)
    branches = [BranchScenario(name="base", portfolio=list(portfolio), realistic_turns=base_turns, feasibility="high" if base_turns < 40 else "medium", note="selected portfolio")]
    critical = _critical_contested(portfolio)
    critical_ids = [t.target_id for t in critical]
    if not critical:
        return {"best_case_turns": base_turns, "board_expected_turns": base_turns, "fallback_case_turns": base_turns, "branches": branches, "critical_race_targets": [], "feasibility": "high" if base_turns < INFINITE_TURNS / 2 else "unrealistic", "fragility": "low"}
    win_turns = base_turns
    branches.append(BranchScenario(name="win_" + "_".join(str(i) for i in critical_ids), portfolio=list(portfolio), realistic_turns=win_turns, feasibility="high", note="win critical races"))
    lose_turns_list = []
    for lost in critical:
        repaired, ok = _repair_portfolio(lost, portfolio, candidates)
        if ok and len(repaired) >= len(portfolio):
            lose_turns = estimate_board_turns_for_portfolio(game, player, requirements, repaired)
            note = "lost @{} repaired with @{}".format(lost.target_id, repaired[-1].target_id if repaired else "?")
            feas = "medium"
        else:
            lose_turns = estimate_board_turns_for_portfolio(game, player, requirements, repaired, incomplete_penalty_turns=8.0)
            note = "lost @{} unrepaired — fragile".format(lost.target_id)
            feas = "fragile"
        lose_turns_list.append(lose_turns)
        branches.append(BranchScenario(name="lose_{}".format(lost.target_id), portfolio=list(repaired), realistic_turns=lose_turns, feasibility=feas, note=note))
    fallback = max(lose_turns_list) if lose_turns_list else base_turns
    expected = (0.55 * win_turns + 0.45 * (sum(lose_turns_list) / float(len(lose_turns_list)))) if lose_turns_list else win_turns
    downside = fallback - expected
    if fallback >= INFINITE_TURNS / 2 or any(b.feasibility == "fragile" for b in branches):
        fragility, feasibility = "high", ("fragile" if fallback >= 50 else "medium")
    elif downside >= 4.0:
        fragility, feasibility = "high", "medium"
    elif downside >= 2.0:
        fragility, feasibility = "medium", "medium"
    else:
        fragility, feasibility = "low", "high"
    return {"best_case_turns": float(win_turns), "board_expected_turns": float(expected), "fallback_case_turns": float(fallback), "branches": branches, "critical_race_targets": critical_ids, "feasibility": feasibility, "fragility": fragility}


def _rank_key(board_expected, feasibility, fragility, fallback):
    feas_pen = {"high": 0.0, "medium": 1.5, "fragile": 4.0, "low": 3.0, "unrealistic": 50.0, "impossible": 100.0}.get(str(feasibility).lower(), 2.0)
    frag_pen = {"low": 0.0, "medium": 1.0, "high": 3.0}.get(str(fragility).lower(), 1.0)
    downside = max(0.0, _safe_float(fallback) - _safe_float(board_expected))
    return _safe_float(board_expected) + feas_pen + frag_pen + 0.25 * min(downside, 20.0)


def _risk_penalty_for_priority(target: PortfolioTarget) -> Tuple[float, str]:
    """Risk penalty component for priority_score (higher = worse)."""
    level = str(getattr(target, "risk_level", "low") or "low").lower()
    base = {"low": 0.0, "safe": 0.0, "medium": 1.5, "med": 1.5, "high": 3.0, "blocked": 6.0}.get(
        level, 0.5
    )
    notes: List[str] = [level or "low"]
    self_eta = getattr(target, "self_eta_own_turns", None)
    try:
        self_f = float(self_eta) if self_eta is not None else None
    except Exception:
        self_f = None
    opp_etas: List[float] = []
    for th in list(getattr(target, "threat_opponents", None) or []):
        if not isinstance(th, Mapping):
            continue
        raw = th.get("eta_own_turns")
        if raw is None:
            continue
        try:
            e = float(raw)
        except Exception:
            continue
        if e < 9000:
            opp_etas.append(e)
    if self_f is not None and opp_etas:
        best_opp = min(opp_etas)
        margin = float(RACE_ETA_MARGIN)
        # Opponent finishes sooner or within race margin → extra penalty
        if best_opp < self_f + margin:
            gap = (self_f + margin) - best_opp
            base += 0.5 * max(0.0, gap)
            notes.append(f"race_gap={gap:.1f}")
    return float(base), "+".join(notes)


def compute_priority_score(target: PortfolioTarget) -> Tuple[float, str]:
    """PR-F: win_delta − λ_η·self_eta − λ_r·risk_penalty. Higher is better."""
    try:
        win_delta = float(target.win_delta) if target.win_delta is not None else 0.0
    except Exception:
        win_delta = 0.0
    try:
        self_eta = (
            float(target.self_eta_own_turns)
            if target.self_eta_own_turns is not None
            else 12.0
        )
    except Exception:
        self_eta = 12.0
    if self_eta >= 9000:
        self_eta = 12.0
    risk_pen, risk_note = _risk_penalty_for_priority(target)
    score = (
        win_delta
        - float(PRIORITY_LAMBDA_ETA) * self_eta
        - float(PRIORITY_LAMBDA_RISK) * risk_pen
    )
    # Small role bump so critical contested still surfaces when timings tie
    role = str(getattr(target, "portfolio_role", "") or "").lower()
    race = str(getattr(target, "race_status", "") or "").lower()
    if role == "critical" and race == "contested":
        score += 0.75
    reason = (
        f"Δw={win_delta:+.1f} η={self_eta:.1f} r={risk_pen:.1f}({risk_note}) "
        f"→ {score:.2f}"
    )
    return round(score, 3), reason


def apply_priority_scores(portfolio: Sequence[PortfolioTarget]) -> List[PortfolioTarget]:
    """Mutate each target with priority_score / priority_reason (PR-F)."""
    out = list(portfolio or [])
    for t in out:
        if not isinstance(t, PortfolioTarget):
            continue
        try:
            sc, reason = compute_priority_score(t)
            t.priority_score = sc
            t.priority_reason = reason
        except Exception as exc:
            t.priority_score = None
            t.priority_reason = f"priority_error:{exc}"
    return out


def _recommendation_from_portfolio(portfolio):
    if not portfolio:
        return "hold / city-dev path", None
    # PR-F: prefer priority_score when timing pack has filled it
    has_priority = any(
        isinstance(t, PortfolioTarget) and t.priority_score is not None for t in portfolio
    )
    if has_priority:
        ordered = sorted(
            [t for t in portfolio if isinstance(t, PortfolioTarget)],
            key=lambda t: (
                -(t.priority_score if t.priority_score is not None else -9999.0),
                int(t.distance_roads or 0),
                int(t.target_id),
            ),
        )
    else:
        ordered = sorted(
            portfolio,
            key=lambda t: (
                0 if (t.portfolio_role == "critical" and t.race_status == "contested") else 1,
                0 if t.portfolio_role == "critical" else 1,
                0 if t.race_status == "contested" else 1,
                -t.score,
                t.distance_roads,
            ),
        )
    if not ordered:
        return "hold / city-dev path", None
    top = ordered[0]
    if has_priority and top.priority_score is not None:
        if top.distance_roads > 0:
            return "priority road toward @{} ({})".format(
                top.target_id, top.priority_reason or f"score={top.priority_score}"
            ), top.target_id
        return "priority settle @{} ({})".format(
            top.target_id, top.priority_reason or f"score={top.priority_score}"
        ), top.target_id
    if top.race_status == "contested" and top.portfolio_role in ("critical", "important"):
        return "race @{}".format(top.target_id), top.target_id
    if top.distance_roads > 0:
        return "road toward @{}".format(top.target_id), top.target_id
    return "settle @{}".format(top.target_id), top.target_id


def build_way_geo_bundle(
    game,
    player,
    way_id,
    *,
    requirements_by_id=None,
    player_state=None,
    abstract_expected_turns=INFINITE_TURNS,
    max_targets_per_way=MAX_TARGETS_PER_WAY,
    max_combos=MAX_COMBOS,
    max_road_distance=MAX_ROAD_DISTANCE,
) -> Dict[str, Any]:
    """P3-B: board/path geometry for one way (candidates + portfolio shells).

    Independent of hand for pathfinding; ``parse_way_requirements`` still uses
    current player_state so structure counts stay correct. Callers reuse this
    bundle across hand-only rescoring.
    """
    req = parse_way_requirements(
        way_id,
        requirements_by_id=requirements_by_id,
        player_state=player_state,
        abstract_expected_turns=abstract_expected_turns,
    )
    candidates = build_candidate_targets(
        game,
        player,
        req,
        max_targets=max_targets_per_way,
        max_road_distance=max_road_distance,
    )
    portfolios = select_portfolios(candidates, req, max_combos=max_combos) or [[]]
    capped = [list(p) for p in list(portfolios)[: min(12, len(portfolios))]]
    return {
        "way_id": int(way_id),
        "candidates": list(candidates),
        "portfolios": capped,
        "req_structure": (
            int(getattr(req, "required_new_intersections", 0) or 0),
            int(getattr(req, "required_cities", 0) or 0),
            int(getattr(req, "required_dcards", 0) or 0),
            int(getattr(req, "required_roads_min", 0) or 0),
            bool(getattr(req, "longest_road", False)),
            bool(getattr(req, "biggest_army", False)),
        ),
    }


def score_way_from_geo_bundle(
    game,
    player,
    bundle: Mapping[str, Any],
    *,
    requirements_by_id=None,
    player_state=None,
    abstract_expected_turns=INFINITE_TURNS,
) -> WayBoardAudit:
    """P3-B: hand/ETA scoring over a cached geometry bundle (no path rebuild)."""
    way_id = _safe_int(
        bundle.get("way_id") if isinstance(bundle, Mapping) else -1,
        -1,
    )
    req = parse_way_requirements(
        way_id,
        requirements_by_id=requirements_by_id,
        player_state=player_state,
        abstract_expected_turns=abstract_expected_turns,
    )
    candidates = list(bundle.get("candidates") or []) if isinstance(bundle, Mapping) else []
    portfolios = list(bundle.get("portfolios") or [[]]) if isinstance(bundle, Mapping) else [[]]
    if not portfolios:
        portfolios = [[]]
    best_audit = None
    for portfolio in portfolios[: min(12, len(portfolios))]:
        portfolio = list(portfolio or [])
        scenario = evaluate_portfolio_scenarios(game, player, req, portfolio, candidates)
        need_after = _named_need(_portfolio_need_vector(req, portfolio))
        board_exp = _safe_float(scenario["board_expected_turns"])
        best_c = _safe_float(scenario["best_case_turns"])
        fall_c = _safe_float(scenario["fallback_case_turns"])
        try:
            portfolio = attach_timing_pack_to_portfolio(
                game,
                player,
                req,
                portfolio,
                candidates,
                baseline_win_turns=board_exp,
            )
        except Exception as exc:
            try:
                for t in portfolio:
                    if isinstance(t, PortfolioTarget) and not t.risk_reasons:
                        t.risk_reasons = []
                    if isinstance(t, PortfolioTarget):
                        t.risk_reasons.append(f"timing_pack_error:{exc}")
            except Exception:
                pass
        try:
            portfolio = apply_priority_scores(portfolio)
        except Exception:
            pass
        rec, rec_id = _recommendation_from_portfolio(portfolio)
        rk = _rank_key(board_exp, str(scenario["feasibility"]), str(scenario["fragility"]), fall_c)
        notes: List[str] = []
        if rec_id is not None:
            try:
                top = next(
                    (
                        t
                        for t in portfolio
                        if isinstance(t, PortfolioTarget) and int(t.target_id) == int(rec_id)
                    ),
                    None,
                )
                if top is not None and top.priority_reason:
                    notes.append(f"priority:{top.priority_reason}")
            except Exception:
                pass
        audit = WayBoardAudit(
            way_id=int(way_id),
            abstract_expected_turns=_safe_float(req.abstract_expected_turns),
            realistic_expected_turns=board_exp,
            board_expected_turns=board_exp,
            best_case_turns=best_c,
            fallback_case_turns=fall_c,
            feasibility=str(scenario["feasibility"]),
            fragility=str(scenario["fragility"]),
            target_portfolio=list(portfolio),
            critical_race_targets=list(scenario.get("critical_race_targets") or []),
            branches=list(scenario.get("branches") or []),
            needed_rcards_before=dict(req.needed_rcards),
            needed_rcards_after=need_after,
            recommendation=rec,
            recommendation_target_id=rec_id,
            requirements=req.as_dict(),
            rank_key=rk,
            notes=notes,
        )
        if best_audit is None or audit.rank_key < best_audit.rank_key:
            best_audit = audit
    if best_audit is None:
        return WayBoardAudit(
            way_id=int(way_id),
            abstract_expected_turns=_safe_float(abstract_expected_turns, INFINITE_TURNS),
            realistic_expected_turns=INFINITE_TURNS,
            board_expected_turns=INFINITE_TURNS,
            best_case_turns=INFINITE_TURNS,
            fallback_case_turns=INFINITE_TURNS,
            feasibility="unrealistic",
            fragility="high",
            target_portfolio=[],
            critical_race_targets=[],
            branches=[],
            needed_rcards_before=dict(req.needed_rcards),
            needed_rcards_after=dict(req.needed_rcards),
            recommendation="empty_geo_bundle",
            recommendation_target_id=None,
            requirements=req.as_dict(),
            rank_key=INFINITE_TURNS,
            notes=["empty_geo_bundle"],
        )
    return best_audit


def evaluate_one_way(
    game,
    player,
    way_id,
    *,
    requirements_by_id=None,
    player_state=None,
    abstract_expected_turns=INFINITE_TURNS,
    max_targets_per_way=MAX_TARGETS_PER_WAY,
    max_combos=MAX_COMBOS,
    max_road_distance=MAX_ROAD_DISTANCE,
    geo_bundle: Optional[Mapping[str, Any]] = None,
    return_bundle: bool = False,
):
    """Full one-way eval. P3-B: optional geo_bundle reuse; optional return_bundle."""
    bundle = geo_bundle
    if not isinstance(bundle, Mapping):
        bundle = build_way_geo_bundle(
            game,
            player,
            way_id,
            requirements_by_id=requirements_by_id,
            player_state=player_state,
            abstract_expected_turns=abstract_expected_turns,
            max_targets_per_way=max_targets_per_way,
            max_combos=max_combos,
            max_road_distance=max_road_distance,
        )
    audit = score_way_from_geo_bundle(
        game,
        player,
        bundle,
        requirements_by_id=requirements_by_id,
        player_state=player_state,
        abstract_expected_turns=abstract_expected_turns,
    )
    if return_bundle:
        return audit, bundle
    return audit


def invalidate_board_way_portfolio_cache(game: Any, reason: str = "") -> None:
    """P2-B / P3-B: drop score + geometry caches (after board/strategy mutations)."""
    if game is None:
        return
    try:
        gen = int(getattr(game, "_portfolio_cache_generation", 0) or 0) + 1
        game._portfolio_cache_generation = gen
    except Exception:
        gen = 0
    try:
        game._board_way_portfolio_cache = None
        game._portfolio_geo_cache = None
        game._board_way_portfolio_cache_meta = {
            "invalidated_reason": str(reason or "manual"),
            "generation": gen,
            "hit": False,
            "geo_cache_hit": False,
            "hand_rescore": False,
        }
    except Exception:
        pass


def _portfolio_hand_fingerprint(player: Any) -> Tuple[int, ...]:
    """Stable hand key: prefer string/enum-tolerant rcards scan, then RTE vector."""
    order = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
    try:
        rcards = getattr(player, "rcards", None) or {}
        if isinstance(rcards, Mapping) and rcards:
            out = []
            for name in order:
                val = 0
                # Direct string key
                if name in rcards:
                    val = int(rcards.get(name) or 0)
                else:
                    for k, v in rcards.items():
                        kn = getattr(k, "value", k)
                        if str(kn) == name:
                            val = int(v or 0)
                            break
                out.append(val)
            # If any non-zero or any key matched, use this scan
            if any(out) or any(True for _ in rcards):
                return tuple(out)
    except Exception:
        pass
    try:
        from core.resource_time_estimator import get_player_resource_cards_vector

        vec = list(get_player_resource_cards_vector(player) or [])[:5]
        return tuple(int(x or 0) for x in (vec + [0, 0, 0, 0, 0])[:5])
    except Exception:
        pass
    return (0, 0, 0, 0, 0)


def _portfolio_board_fingerprint(game: Any) -> Tuple[Any, ...]:
    """Structural board key: pieces + robber (not hand)."""
    parts: List[Any] = []
    try:
        for p in list(getattr(game, "players", []) or []):
            pid = _safe_int(getattr(p, "id", -1), -1)
            settles = tuple(sorted(int(x) for x in (getattr(p, "settlements", None) or []) if x is not None))
            cities = tuple(sorted(int(x) for x in (getattr(p, "cities", None) or []) if x is not None))
            roads_raw = []
            for r in list(getattr(p, "roads", None) or []):
                try:
                    if isinstance(r, (list, tuple)) and len(r) >= 2:
                        a, b = int(r[0]), int(r[1])
                        roads_raw.append((min(a, b), max(a, b)))
                except Exception:
                    continue
            roads = tuple(sorted(set(roads_raw)))
            parts.append((pid, settles, cities, roads))
    except Exception:
        parts.append(("players_err",))
    robber = None
    try:
        board = getattr(game, "board", None)
        robber = getattr(board, "robber_tile", None)
        if robber is None:
            robber = getattr(board, "robber_tile_id", None)
        if robber is None and board is not None:
            robber = getattr(board, "robber", None)
        try:
            robber = int(robber) if robber is not None else None
        except Exception:
            robber = str(robber)
    except Exception:
        robber = None
    parts.append(("robber", robber))
    return tuple(parts)


def _portfolio_sticky_fingerprint(player: Any) -> Tuple[Any, ...]:
    sticky = getattr(player, "sticky_commitment", None) if player is not None else None
    if not isinstance(sticky, Mapping):
        return (None, None, None, None)
    roads = sticky.get("locked_roads_to_build")
    road_t = None
    if roads:
        try:
            road_t = tuple(
                tuple(int(x) for x in edge[:2])
                for edge in list(roads)[:6]
                if isinstance(edge, (list, tuple)) and len(edge) >= 2
            )
        except Exception:
            road_t = str(roads)[:80]
    return (
        sticky.get("locked_way_id"),
        sticky.get("locked_rec_target_id"),
        sticky.get("locked_target_kind"),
        road_t,
    )


def build_portfolio_geo_cache_key(
    game: Any,
    player: Any,
    way_ids: Sequence[int],
) -> Tuple[Any, ...]:
    """P3-B geometry key: gen + player + ways + board + sticky (+ force). No hand."""
    cap = _resolve_portfolio_top_n(game)
    wid_t = tuple(int(w) for w in list(way_ids or [])[: cap])
    gen = 0
    try:
        gen = int(getattr(game, "_portfolio_cache_generation", 0) or 0)
    except Exception:
        gen = 0
    force = False
    try:
        force = bool(getattr(player, "force_strategy_recalc", False))
    except Exception:
        force = False
    return (
        gen,
        _safe_int(getattr(player, "id", -1), -1),
        wid_t,
        _portfolio_board_fingerprint(game),
        _portfolio_sticky_fingerprint(player),
        force,
    )


def build_portfolio_cache_key(
    game: Any,
    player: Any,
    way_ids: Sequence[int],
    abs_map: Optional[Mapping[Any, Any]] = None,
) -> Tuple[Any, ...]:
    """Fingerprint for full score cache hit (geo + hand + abstract ETAs)."""
    cap = _resolve_portfolio_top_n(game)
    wid_t = tuple(int(w) for w in list(way_ids or [])[: cap])
    abs_t = []
    if isinstance(abs_map, Mapping):
        for w in wid_t:
            try:
                abs_t.append((w, round(float(abs_map.get(w, INFINITE_TURNS) or INFINITE_TURNS), 2)))
            except Exception:
                abs_t.append((w, INFINITE_TURNS))
    geo = build_portfolio_geo_cache_key(game, player, way_ids)
    return (
        geo,
        tuple(abs_t),
        _portfolio_hand_fingerprint(player),
    )


def evaluate_top_ways_board_feasibility(
    game,
    player,
    top_ways,
    max_targets_per_way=MAX_TARGETS_PER_WAY,
    max_combos=MAX_COMBOS,
    max_road_distance=MAX_ROAD_DISTANCE,
    abstract_turns_by_way=None,
    *,
    use_cache: bool = True,
):
    """Evaluate top ways with P3-B two-tier cache (geometry vs hand score)."""
    way_ids = _normalize_way_ids(top_ways)
    if not way_ids:
        return []
    abs_map = dict(abstract_turns_by_way or {})
    top_cap = _resolve_portfolio_top_n(game)
    if not abs_map:
        try:
            from core.strategy_timing import rank_strategies_for_player
            board = getattr(game, "board", None)
            if board is not None and player is not None:
                report = rank_strategies_for_player(
                    board,
                    player,
                    top_n=max(int(top_cap), len(way_ids)),
                    include_all=False,
                    require_confidence=False,
                )
                for row in list(report.get("top_strategies", []) or []):
                    if isinstance(row, Mapping):
                        abs_map[_safe_int(row.get("way_id"), -1)] = _safe_float(
                            row.get("turns", INFINITE_TURNS), INFINITE_TURNS
                        )
        except Exception:
            pass

    eval_ids = list(way_ids[: int(top_cap)])
    score_key = None
    geo_key = None
    if use_cache and PORTFOLIO_CACHE_ENABLED and game is not None:
        try:
            geo_key = build_portfolio_geo_cache_key(game, player, eval_ids)
            score_key = build_portfolio_cache_key(game, player, eval_ids, abs_map)
            cached = getattr(game, "_board_way_portfolio_cache", None)
            if (
                isinstance(cached, Mapping)
                and cached.get("key") == score_key
                and cached.get("audits") is not None
            ):
                audits = list(cached.get("audits") or [])
                try:
                    game.current_board_way_audit = audits[0] if audits else None
                    game.current_board_way_audits = audits
                    game._board_way_portfolio_cache_meta = {
                        "hit": True,
                        "geo_cache_hit": True,
                        "hand_rescore": False,
                        "stored": False,
                        "way_count": len(audits),
                        "key_ways": list(eval_ids),
                    }
                except Exception:
                    pass
                return audits
        except Exception:
            score_key = None
            geo_key = None

    # P3-B: geometry-only hit → rescore with current hand (skip path rebuild)
    geo_bundles: Optional[List[Dict[str, Any]]] = None
    geo_hit = False
    if use_cache and PORTFOLIO_CACHE_ENABLED and game is not None and geo_key is not None:
        try:
            geo_cached = getattr(game, "_portfolio_geo_cache", None)
            if (
                isinstance(geo_cached, Mapping)
                and geo_cached.get("key") == geo_key
                and geo_cached.get("bundles") is not None
            ):
                raw_bundles = list(geo_cached.get("bundles") or [])
                if len(raw_bundles) == len(eval_ids):
                    geo_bundles = [dict(b) for b in raw_bundles if isinstance(b, Mapping)]
                    if len(geo_bundles) == len(eval_ids):
                        geo_hit = True
        except Exception:
            geo_bundles = None
            geo_hit = False

    requirements_by_id, player_state = {}, None
    try:
        from core.strategy_timing import build_player_strategy_state, load_strategy_requirements
        board = getattr(game, "board", None)
        if board is not None and player is not None:
            player_state = build_player_strategy_state(board, player)
        for strategy in load_strategy_requirements():
            requirements_by_id[int(strategy.way_id)] = strategy
    except Exception:
        pass

    audits: List[Any] = []
    new_bundles: List[Dict[str, Any]] = []
    for idx, way_id in enumerate(eval_ids):
        abs_t = abs_map.get(way_id, INFINITE_TURNS)
        try:
            if geo_hit and geo_bundles is not None:
                bundle = geo_bundles[idx]
                audit = score_way_from_geo_bundle(
                    game,
                    player,
                    bundle,
                    requirements_by_id=requirements_by_id,
                    player_state=player_state,
                    abstract_expected_turns=abs_t,
                )
                new_bundles.append(dict(bundle))
            else:
                result = evaluate_one_way(
                    game,
                    player,
                    way_id,
                    requirements_by_id=requirements_by_id,
                    player_state=player_state,
                    abstract_expected_turns=abs_t,
                    max_targets_per_way=max_targets_per_way,
                    max_combos=max_combos,
                    max_road_distance=max_road_distance,
                    return_bundle=True,
                )
                if isinstance(result, tuple) and len(result) == 2:
                    audit, bundle = result
                else:
                    audit = result
                    bundle = {
                        "way_id": int(way_id),
                        "candidates": [],
                        "portfolios": [[]],
                        "synthetic": True,
                    }
                new_bundles.append(dict(bundle) if isinstance(bundle, Mapping) else {
                    "way_id": int(way_id),
                    "candidates": [],
                    "portfolios": [[]],
                    "synthetic": True,
                })
            audits.append(audit)
        except Exception as exc:
            audits.append(
                WayBoardAudit(
                    way_id=int(way_id),
                    abstract_expected_turns=abs_t,
                    realistic_expected_turns=INFINITE_TURNS,
                    board_expected_turns=INFINITE_TURNS,
                    best_case_turns=INFINITE_TURNS,
                    fallback_case_turns=INFINITE_TURNS,
                    feasibility="unrealistic",
                    fragility="high",
                    target_portfolio=[],
                    critical_race_targets=[],
                    branches=[],
                    needed_rcards_before={},
                    needed_rcards_after={},
                    recommendation="evaluation_error",
                    recommendation_target_id=None,
                    rank_key=INFINITE_TURNS,
                    notes=[str(exc)],
                )
            )
            new_bundles.append({
                "way_id": int(way_id),
                "candidates": [],
                "portfolios": [[]],
                "error": str(exc),
            })

    audits.sort(key=lambda a: (a.rank_key, a.board_expected_turns, a.way_id))
    if game is not None:
        try:
            game.current_board_way_audit = audits[0] if audits else None
            game.current_board_way_audits = audits
        except Exception:
            pass
        if use_cache and PORTFOLIO_CACHE_ENABLED:
            try:
                if score_key is None:
                    score_key = build_portfolio_cache_key(game, player, eval_ids, abs_map)
                if geo_key is None:
                    geo_key = build_portfolio_geo_cache_key(game, player, eval_ids)
                game._board_way_portfolio_cache = {
                    "key": score_key,
                    "audits": list(audits),
                }
                # Keep geometry ordered by eval_ids (not audit sort) for rescoring
                game._portfolio_geo_cache = {
                    "key": geo_key,
                    "bundles": list(new_bundles),
                    "way_ids": list(eval_ids),
                }
                game._board_way_portfolio_cache_meta = {
                    "hit": False,
                    "geo_cache_hit": bool(geo_hit),
                    "hand_rescore": bool(geo_hit),
                    "stored": True,
                    "way_count": len(audits),
                    "key_ways": list(eval_ids),
                }
            except Exception:
                pass
    return audits


def format_audit_compact(audit):
    if not audit:
        return "FEAS: (no board audit)"
    try:
        way_id = getattr(audit, "way_id", None) if not isinstance(audit, Mapping) else audit.get("way_id")
        exp = getattr(audit, "board_expected_turns", None) if not isinstance(audit, Mapping) else audit.get("board_expected_turns")
        if exp is None:
            exp = getattr(audit, "realistic_expected_turns", None) if not isinstance(audit, Mapping) else audit.get("realistic_expected_turns")
        best = getattr(audit, "best_case_turns", None) if not isinstance(audit, Mapping) else audit.get("best_case_turns")
        fall = getattr(audit, "fallback_case_turns", None) if not isinstance(audit, Mapping) else audit.get("fallback_case_turns")
        frag = getattr(audit, "fragility", None) if not isinstance(audit, Mapping) else audit.get("fragility")
        feas = getattr(audit, "feasibility", None) if not isinstance(audit, Mapping) else audit.get("feasibility")
        return "FEAS way{} exp={:.1f} best={:.1f} fall={:.1f} frag={} feas={}".format(way_id, _safe_float(exp), _safe_float(best), _safe_float(fall), frag or "?", feas or "?")
    except Exception:
        return "FEAS: (audit format error)"


def format_portfolio_compact(audit):
    if not audit:
        return "PORT: -"
    portfolio = getattr(audit, "target_portfolio", None) if not isinstance(audit, Mapping) else audit.get("target_portfolio")
    if not portfolio:
        return "PORT: (no new settlements)"
    parts = []
    for t in list(portfolio)[:4]:
        if hasattr(t, "target_id"):
            parts.append("@{} {}r {} {}".format(t.target_id, t.distance_roads, t.race_status, t.portfolio_role))
        elif isinstance(t, Mapping):
            parts.append("@{} {}r {} {}".format(t.get("target_id"), t.get("distance_roads"), t.get("race_status"), t.get("portfolio_role")))
    return "PORT " + " | ".join(parts)


def collect_top_way_ids_from_report(report, game, player, *, limit=None):
    if limit is None:
        limit = _resolve_portfolio_top_n(game)
    else:
        limit = _resolve_portfolio_top_n(game, limit=limit)
    way_ids, seen = [], set()
    def _add(wid):
        i = _safe_int(wid, -1)
        if i < 0 or i in seen:
            return
        seen.add(i)
        way_ids.append(i)
    player_id = _safe_int(getattr(player, "id", -1), -1)
    by_player = report.get("by_player", {}) or {}
    block = by_player.get(str(player_id)) or by_player.get(player_id) if player_id >= 0 else None
    if block is None and by_player:
        block = next(iter(by_player.values()))
    if isinstance(block, Mapping):
        for row in list(block.get("baseline_top_strategies", []) or []):
            if isinstance(row, Mapping):
                _add(row.get("way_id"))
        pref = block.get("preferred_strategy") or {}
        if isinstance(pref, Mapping):
            _add(pref.get("preferred_way_id") or pref.get("way_id"))
        for row in list(block.get("strategy_preference_candidates", []) or []):
            if isinstance(row, Mapping):
                _add(row.get("way_id") or row.get("preferred_way_id"))
    direction = getattr(player, "strategic_direction", None) or {}
    if isinstance(direction, Mapping):
        _add(direction.get("preferred_way_id") or direction.get("way_id"))
    sticky = getattr(player, "sticky_commitment", None) if player is not None else None
    if isinstance(sticky, Mapping):
        # Always keep locked way in the L2 set even if abstract rank drops it.
        _add(sticky.get("locked_way_id"))
    if not way_ids:
        try:
            from core.strategy_timing import rank_strategies_for_player
            board = getattr(game, "board", None)
            if board is not None:
                ranked = rank_strategies_for_player(board, player, top_n=limit, include_all=False, require_confidence=False)
                for row in list(ranked.get("top_strategies", []) or []):
                    if isinstance(row, Mapping):
                        _add(row.get("way_id"))
        except Exception:
            pass
    return way_ids[:limit]


def collect_l0_way_ids(report, game, player, *, limit: int = 3) -> List[int]:
    """P3-C L0: sticky + preferred way only (optionally a couple of alts)."""
    limit = max(1, min(int(limit or 3), _resolve_portfolio_top_n(game)))
    way_ids: List[int] = []
    seen = set()

    def _add(wid: Any) -> None:
        i = _safe_int(wid, -1)
        if i < 0 or i in seen:
            return
        seen.add(i)
        way_ids.append(i)

    sticky = getattr(player, "sticky_commitment", None) if player is not None else None
    if isinstance(sticky, Mapping):
        _add(sticky.get("locked_way_id"))
    direction = getattr(player, "strategic_direction", None) if player is not None else None
    if isinstance(direction, Mapping):
        _add(direction.get("preferred_way_id") or direction.get("way_id"))
    # Report preferred / first baseline as last-resort seed
    if not way_ids:
        for wid in collect_top_way_ids_from_report(report, game, player, limit=1):
            _add(wid)
    return way_ids[:limit]




def _audit_get(audit, key, default=None):
    if audit is None:
        return default
    if isinstance(audit, Mapping):
        return audit.get(key, default)
    return getattr(audit, key, default)


def _portfolio_target_list(audit):
    portfolio = _audit_get(audit, "target_portfolio", []) or []
    out = []
    for t in portfolio:
        if hasattr(t, "as_dict"):
            out.append(t.as_dict())
        elif isinstance(t, Mapping):
            out.append(dict(t))
        else:
            out.append(t)
    return out


def _pick_project_target(audit):
    """Return (target_dict_or_None, roads_list) for the immediate project."""
    tid = _audit_get(audit, "recommendation_target_id")
    portfolio = _portfolio_target_list(audit)
    chosen = None
    if tid is not None:
        for t in portfolio:
            if _safe_int(t.get("target_id"), -1) == _safe_int(tid, -2):
                chosen = t
                break
    if chosen is None and portfolio:
        # same ordering spirit as _recommendation_from_portfolio
        def key(t):
            role = str(t.get("portfolio_role", ""))
            race = str(t.get("race_status", ""))
            return (
                0 if (role == "critical" and race == "contested") else 1,
                0 if role == "critical" else 1,
                0 if race == "contested" else 1,
                -_safe_float(t.get("score", 0.0)),
                _safe_int(t.get("distance_roads", 0), 0),
            )
        chosen = sorted(portfolio, key=key)[0]
    if not chosen:
        return None, []
    roads = list(chosen.get("roads_to_build") or [])
    return chosen, roads


def derive_supporting_action_type(audit):
    """Map board project to supporting_action_type for execution bridge / road planner."""
    req = _audit_get(audit, "requirements") or {}
    if isinstance(req, Mapping):
        new_s = _safe_int(req.get("required_new_intersections"), 0)
        cities = _safe_int(req.get("required_cities"), 0)
        dcards = _safe_int(req.get("required_dcards"), 0)
    else:
        new_s = cities = dcards = 0
    portfolio = _portfolio_target_list(audit)
    if new_s > 0 or portfolio:
        chosen, roads = _pick_project_target(audit)
        dist = _safe_int((chosen or {}).get("distance_roads"), 0) if chosen else 0
        if not roads and dist == 0 and chosen:
            return "next_settlement"
        return "new_settlement"
    if cities > 0:
        return "city_upgrade"
    if dcards > 0:
        return "buy_dcard"
    return ""


def board_audit_to_strategic_direction(audit, *, abstract_preferred=None, override_applied=False, override_reason=""):
    """Convert a WayBoardAudit into a strategic_direction / preferred_strategy dict."""
    abstract_preferred = dict(abstract_preferred or {}) if isinstance(abstract_preferred, Mapping) else {}
    way_id = _safe_int(_audit_get(audit, "way_id"), -1)
    rec = str(_audit_get(audit, "recommendation", "") or "")
    rec_id = _audit_get(audit, "recommendation_target_id")
    if rec_id is not None:
        rec_id = _safe_int(rec_id, None)  # type: ignore[arg-type]
    chosen, roads = _pick_project_target(audit)
    supporting = derive_supporting_action_type(audit)
    req = _audit_get(audit, "requirements") or {}
    if not isinstance(req, Mapping):
        req = {}
    remaining = {
        "new_settlements": _safe_int(req.get("required_new_intersections"), 0),
        "cities": _safe_int(req.get("required_cities"), 0),
        "roads": _safe_int(req.get("required_roads_min"), 0),
        "development_cards": _safe_int(req.get("required_dcards"), 0),
    }
    needed = _audit_get(audit, "needed_rcards_after") or _audit_get(audit, "needed_rcards_before") or req.get("needed_rcards") or {}
    if not isinstance(needed, Mapping):
        needed = {}
    need_compact = " ".join(
        "{}{}".format(k[:2] if k != "Wheat" else "Wh", int(round(_safe_float(v))))
        for k, v in needed.items() if _safe_float(v) > 0
    ) or "none"
    # Attach 142-way composition tags so STR can show LA/City/VP (not NewS-as-Settle)
    tags: List[str] = []
    biggest_army = bool(req.get("biggest_army") or req.get("largest_army"))
    longest_road = bool(req.get("longest_road"))
    vp_cards = _safe_int(req.get("victory_point_cards") or req.get("required_vp_cards"), 0)
    table_settlements = 0
    try:
        from core.strategy_timing import load_strategy_requirements

        for row in load_strategy_requirements() or []:
            if _safe_int(getattr(row, "way_id"), -1) != way_id:
                continue
            biggest_army = bool(getattr(row, "biggest_army", biggest_army))
            longest_road = bool(getattr(row, "longest_road", longest_road))
            vp_cards = _safe_int(getattr(row, "victory_point_cards", vp_cards), vp_cards)
            table_settlements = _safe_int(getattr(row, "settlements", 0), 0)
            if remaining["cities"] <= 0:
                remaining["cities"] = _safe_int(getattr(row, "city_upgrades", 0) or getattr(row, "cities", 0), 0)
            if remaining["new_settlements"] <= 0:
                remaining["new_settlements"] = _safe_int(getattr(row, "new_settlements_to_build", 0), 0)
            # Prefer joint expected DC buys for remaining (ranking model)
            rem_dc = _safe_int(getattr(row, "development_cards_to_buy", 0), 0)
            if rem_dc > 0:
                remaining["development_cards"] = rem_dc
            break
    except Exception:
        pass
    if longest_road:
        tags.append("Longest Road")
    if biggest_army:
        tags.append("Largest Army")
    if remaining["cities"] > 0:
        tags.append("{} cities".format(remaining["cities"]))
    # Settlements column only (way 16 → no Settle tag; NewS stays in remaining for PROJ)
    if table_settlements > 0:
        tags.append("{} settlements".format(table_settlements))
    if vp_cards > 0:
        tags.append("{} VP cards".format(vp_cards))
    # S11: city-only ways may have recommendation_target_id=None — tag kind for sticky
    target_kind = ""
    if supporting == "city_upgrade":
        target_kind = "C"
    elif supporting in ("new_settlement", "next_settlement"):
        target_kind = "S"
    elif supporting in ("buy_dcard",):
        target_kind = "DCard"

    direction = {
        "preferred_way_id": way_id if way_id >= 0 else None,
        "way_id": way_id if way_id >= 0 else None,
        "preference_source": "4G-B_board_portfolio" if override_applied else "4G-B_board_enrichment",
        "board_expected_turns": _safe_float(_audit_get(audit, "board_expected_turns")),
        "realistic_expected_turns": _safe_float(_audit_get(audit, "realistic_expected_turns") or _audit_get(audit, "board_expected_turns")),
        "best_case_turns": _safe_float(_audit_get(audit, "best_case_turns")),
        "fallback_case_turns": _safe_float(_audit_get(audit, "fallback_case_turns")),
        "fragility": _audit_get(audit, "fragility"),
        "feasibility": _audit_get(audit, "feasibility"),
        "rank_key": _safe_float(_audit_get(audit, "rank_key"), INFINITE_TURNS),
        "target_portfolio": _portfolio_target_list(audit),
        "critical_race_targets": list(_audit_get(audit, "critical_race_targets") or []),
        "recommendation": rec,
        "recommendation_target_id": rec_id,
        "settlement_target_id": rec_id,
        "new_settlement_target_id": rec_id,
        "target_id": rec_id,
        "target_kind": target_kind,
        "locked_target_kind": target_kind or None,
        "roads_to_build": roads,
        "supporting_action_type": supporting,
        "supporting_action": rec,
        "tags": tags,
        "strategy_summary": {
            "largest_army": biggest_army,
            "biggest_army": biggest_army,
            "longest_road": longest_road,
            "cities": remaining["cities"],
            "new_settlements": remaining["new_settlements"],
            "victory_point_cards": vp_cards,
        },
        "remaining": remaining,
        "remaining_new_settlements": remaining["new_settlements"],
        "needed_rcards": dict(needed),
        "need_compact": need_compact,
        "way_requirements": {
            "new_settlements": remaining["new_settlements"],
            "cities": remaining["cities"],
            "roads": remaining["roads"],
            "development_cards": remaining["development_cards"],
            "victory_point_cards": vp_cards,
            "biggest_army": biggest_army,
            "longest_road": longest_road,
        },
        "abstract_preferred_way_id": abstract_preferred.get("preferred_way_id") or abstract_preferred.get("way_id"),
        "board_override_applied": bool(override_applied),
        "override_reason": override_reason or "",
    }
    if chosen:
        direction["project_target"] = chosen
        direction["target_label"] = "new_settle@{}".format(chosen.get("target_id"))
    return direction


def _board_has_critical_portfolio(board_audit) -> bool:
    """True if board winner portfolio includes a critical (or critical contested) target."""
    portfolio = _audit_get(board_audit, "target_portfolio", []) or []
    crit_ids = list(_audit_get(board_audit, "critical_race_targets", []) or [])
    if crit_ids:
        return True
    for t in portfolio:
        if hasattr(t, "portfolio_role"):
            role = str(getattr(t, "portfolio_role", "") or "")
            race = str(getattr(t, "race_status", "") or "")
        elif isinstance(t, Mapping):
            role = str(t.get("portfolio_role", "") or "")
            race = str(t.get("race_status", "") or "")
        else:
            continue
        if role == "critical" or (role in ("critical", "important") and race == "contested"):
            return True
    return False


def should_override_abstract_preferred(board_audit, abstract_preferred=None, audits=None, *, min_rank_edge=BOARD_OVERRIDE_MIN_RANK_EDGE, require_feasible=BOARD_OVERRIDE_REQUIRE_FEASIBLE):
    """Gate: whether board ranking should replace abstract preferred way.

    Returns (apply: bool, reason: str).

    Prefer adopting board#1 when it is clearly faster and/or carries a critical
    portfolio project, or when abstract preference is payment-unreliable.
    """
    if board_audit is None:
        return False, "no_board_audit"
    feas = str(_audit_get(board_audit, "feasibility", "") or "").lower()
    if require_feasible and feas in ("unrealistic", "impossible"):
        return False, "board_winner_not_feasible"
    board_way = _safe_int(_audit_get(board_audit, "way_id"), -1)
    if board_way < 0:
        return False, "invalid_board_way"
    abstract_preferred = abstract_preferred if isinstance(abstract_preferred, Mapping) else {}
    abs_way = _safe_int(abstract_preferred.get("preferred_way_id") or abstract_preferred.get("way_id"), -1)
    board_rank = _safe_float(_audit_get(board_audit, "rank_key"), INFINITE_TURNS)
    board_turns = _safe_float(
        _audit_get(board_audit, "board_expected_turns", _audit_get(board_audit, "realistic_expected_turns")),
        INFINITE_TURNS,
    )
    # same way: enrich only
    if abs_way >= 0 and abs_way == board_way:
        return False, "same_way_enrich_only"
    # no abstract: adopt board
    if abs_way < 0:
        return True, "no_abstract_preferred"
    # abstract way missing from audits entirely
    if audits:
        audit_ways = {_safe_int(_audit_get(a, "way_id"), -1) for a in audits}
        if abs_way not in audit_ways:
            return True, "abstract_way_not_in_board_top"
    # find abstract audit for rank comparison
    abs_rank = None
    abs_frag = None
    abs_turns = None
    abs_audit = None
    for a in list(audits or []):
        if _safe_int(_audit_get(a, "way_id"), -1) == abs_way:
            abs_audit = a
            abs_rank = _safe_float(_audit_get(a, "rank_key"), INFINITE_TURNS)
            abs_frag = str(_audit_get(a, "fragility", "medium") or "medium")
            abs_turns = _safe_float(
                _audit_get(a, "board_expected_turns", _audit_get(a, "realistic_expected_turns")),
                INFINITE_TURNS,
            )
            break
    if abs_rank is None:
        return True, "abstract_way_unscored_on_board"

    edge = float(min_rank_edge)
    # Classic: board rank_key clearly better
    if board_rank + 1e-9 <= abs_rank - edge:
        return True, "board_rank_better_by_{:.2f}".format(abs_rank - board_rank)

    # Board faster on expected turns with critical portfolio project
    if abs_turns is not None and board_turns + 1e-9 <= abs_turns - max(0.75, edge * 0.75):
        if _board_has_critical_portfolio(board_audit):
            return True, "board_faster_critical_portfolio_by_{:.2f}t".format(abs_turns - board_turns)
        if board_turns + 1e-9 <= abs_turns - edge:
            return True, "board_faster_turns_by_{:.2f}".format(abs_turns - board_turns)

    # Abstract payment unreliable / continuous-only while board is feasible
    payment_unreliable = (
        _strategy_pref_bool_local(abstract_preferred.get("payment_reliable")) is False
        or "continuous" in str(abstract_preferred.get("payment_model", "") or "").lower()
        or "unreliable" in str(abstract_preferred.get("preference_reason", "") or "").lower()
        or "payment caution" in str(abstract_preferred.get("preference_level", "") or "").lower()
    )
    if payment_unreliable and feas in ("high", "medium") and board_rank <= abs_rank + 0.25:
        return True, "board_replaces_unreliable_abstract"

    # Abstract buried on board list (3rd or worse) while board#1 is better
    if audits:
        for idx, a in enumerate(list(audits or [])):
            if _safe_int(_audit_get(a, "way_id"), -1) == abs_way:
                if idx >= int(BOARD_OVERRIDE_BURIED_INDEX) and board_rank < abs_rank:
                    return True, "board_top_abstract_buried_at_{}".format(idx + 1)
                break

    # robustness: similar rank but lower fragility
    board_frag = str(_audit_get(board_audit, "fragility", "medium") or "medium")
    bf = FRAGILITY_RANK.get(board_frag, 1)
    af = FRAGILITY_RANK.get(abs_frag or "medium", 1)
    if bf < af and abs(abs_rank - board_rank) <= edge + 0.5:
        return True, "more_robust_similar_rank"
    return False, "keep_abstract_preferred"


def _strategy_pref_bool_local(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def persist_strategic_direction(player, direction):
    """Persist strategic_direction on player (mirrors action_planner helper)."""
    if player is None or not isinstance(direction, Mapping):
        return False
    preferred_dict = dict(direction)
    try:
        setter = getattr(player, "set_strategic_direction", None)
        if callable(setter):
            setter(preferred_dict)
            return True
    except Exception:
        pass
    try:
        previous = getattr(player, "strategic_direction", None)
        setattr(player, "last_strategic_direction", previous)
        setattr(player, "strategic_direction", preferred_dict)
        history = list(getattr(player, "strategic_direction_history", []) or [])
        history.append(preferred_dict)
        setattr(player, "strategic_direction_history", history[-20:])
        return True
    except Exception:
        return False


def apply_board_behavior_override(report, game, player, audits, *, persist=True):
    """4G-B: decide override, build direction, optionally persist. Mutates report."""
    if not audits:
        report["board_way_override"] = {"applied": False, "reason": "no_audits"}
        return report
    winner = audits[0]
    pid = str(getattr(player, "id", ""))
    block = (report.get("by_player") or {}).get(pid)
    if not isinstance(block, dict):
        # try int key
        block = (report.get("by_player") or {}).get(getattr(player, "id", None)) or {}
    if not isinstance(block, dict):
        block = {}
    abstract = dict(block.get("preferred_strategy") or {})
    if not abstract:
        direction_now = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction_now, Mapping):
            abstract = dict(direction_now)
    apply, reason = should_override_abstract_preferred(winner, abstract, audits)
    # Always build board direction; mark whether override of way_id applies
    direction = board_audit_to_strategic_direction(
        winner,
        abstract_preferred=abstract,
        override_applied=apply,
        override_reason=reason,
    )
    if not apply:
        # enrichment: keep abstract way if present, still attach board project
        abs_way = _safe_int(abstract.get("preferred_way_id") or abstract.get("way_id"), -1)
        board_way = _safe_int(_audit_get(winner, "way_id"), -1)
        if abs_way >= 0:
            direction["preferred_way_id"] = abs_way
            direction["way_id"] = abs_way
            direction["preference_source"] = "4G-B_board_enrichment_keep_abstract_way"
            direction["board_context_way_id"] = board_way
            direction["board_rank_way_id"] = board_way
            direction["preferred_board_diverge"] = bool(board_way >= 0 and board_way != abs_way)
            # Prefer remaining/requirements from preferred-way audit when available
            pref_audit = None
            for a in list(audits or []):
                if _safe_int(_audit_get(a, "way_id"), -1) == abs_way:
                    pref_audit = a
                    break
            if pref_audit is not None:
                pref_dir = board_audit_to_strategic_direction(
                    pref_audit,
                    abstract_preferred=abstract,
                    override_applied=False,
                    override_reason=reason,
                )
                for key in (
                    "remaining", "remaining_new_settlements", "needed_rcards", "need_compact",
                    "way_requirements", "feasibility", "fragility", "board_expected_turns",
                    "realistic_expected_turns", "best_case_turns", "fallback_case_turns", "rank_key",
                ):
                    if key in pref_dir:
                        direction[key] = pref_dir[key]
                # Keep immediate board geography (race target) from board#1 when diverge
                if direction.get("preferred_board_diverge"):
                    direction["board_recommendation"] = direction.get("recommendation")
                    direction["board_recommendation_target_id"] = direction.get("recommendation_target_id")
                    # Restore preferred-way recommendation if it had one; else keep board race
                    if pref_dir.get("recommendation_target_id") not in (None, ""):
                        # Prefer preferred audit project when present
                        direction["recommendation"] = pref_dir.get("recommendation")
                        direction["recommendation_target_id"] = pref_dir.get("recommendation_target_id")
                        direction["settlement_target_id"] = pref_dir.get("settlement_target_id")
                        direction["new_settlement_target_id"] = pref_dir.get("new_settlement_target_id")
                        direction["target_id"] = pref_dir.get("target_id")
                        direction["roads_to_build"] = pref_dir.get("roads_to_build")
                        direction["supporting_action_type"] = pref_dir.get("supporting_action_type")
                        direction["supporting_action"] = pref_dir.get("supporting_action")
                        if pref_dir.get("project_target"):
                            direction["project_target"] = pref_dir.get("project_target")
                            direction["target_label"] = pref_dir.get("target_label")

    # S5b: LA/LR way feasibility kill (one-shot re-rank; latch prevents thrash)
    way_kill_meta: Dict[str, Any] = {"killed": False, "reason": "not_run"}
    try:
        from core.strategy_way_kill import (
            apply_way_feasibility_kills,
            format_way_kill_dbg,
            pick_audit_excluding_way,
        )

        way_kill_meta = apply_way_feasibility_kills(game, player, direction)
        if way_kill_meta.get("killed"):
            blocked = way_kill_meta.get("way_id")
            alt = pick_audit_excluding_way(audits, blocked)
            if alt is not None:
                direction = board_audit_to_strategic_direction(
                    alt,
                    abstract_preferred=abstract,
                    override_applied=True,
                    override_reason=str(way_kill_meta.get("reason") or "way_kill"),
                )
                direction["way_kill"] = dict(way_kill_meta)
                direction["preference_source"] = (
                    str(direction.get("preference_source") or "") + "+S5b_way_kill"
                ).lstrip("+")
            way_kill_meta["dbg"] = format_way_kill_dbg(way_kill_meta)
    except Exception as kill_exc:
        way_kill_meta = {"killed": False, "reason": f"way_kill_error:{kill_exc}", "s5b": True}

    # S5.5-A/B/C: assess specials; if preferred needs dead LA/LR, divert (once/turn latch)
    s55_meta: Dict[str, Any] = {"s55": True, "slice": "C", "reason": "not_run"}
    try:
        from core.strategy_specials_divert import (
            format_specials_assess_dbg,
            format_specials_divert_dbg,
            maybe_specials_divert_on_turn_start,
        )

        s55_meta = maybe_specials_divert_on_turn_start(
            game,
            player,
            audits,
            direction,
            abstract_preferred=abstract,
            phase="portfolio_override",
            store=True,
            apply_direction=False,
        )
        if not s55_meta.get("dbg"):
            s55_meta["dbg"] = format_specials_divert_dbg(s55_meta)
        assess = s55_meta.get("assess") if isinstance(s55_meta.get("assess"), Mapping) else {}
        direction["specials_assess"] = {
            "kill_la_recommended": assess.get("kill_la_recommended"),
            "kill_lr_recommended": assess.get("kill_lr_recommended"),
            "la_reason": (assess.get("la") or {}).get("reason") if isinstance(assess.get("la"), Mapping) else s55_meta.get("reason_la"),
            "lr_reason": (assess.get("lr") or {}).get("reason") if isinstance(assess.get("lr"), Mapping) else s55_meta.get("reason_lr"),
            "dbg": format_specials_assess_dbg(assess) if assess else s55_meta.get("dbg"),
            "skipped": bool(s55_meta.get("skipped")),
        }
        if (
            s55_meta.get("fired")
            and not s55_meta.get("skipped")
            and isinstance(s55_meta.get("direction_out"), Mapping)
        ):
            direction = dict(s55_meta["direction_out"])
            direction["way_kill"] = dict(way_kill_meta) if way_kill_meta.get("killed") else {
                "killed": True,
                "kind": "LA" if s55_meta.get("kill_la") else "LR",
                "reason": s55_meta.get("reason"),
                "s55_divert": True,
            }
            direction["specials_divert"] = {
                "fired": True,
                "from_way": s55_meta.get("preferred_way_before"),
                "to_way": s55_meta.get("chosen_way_id"),
                "kill_la": s55_meta.get("kill_la"),
                "kill_lr": s55_meta.get("kill_lr"),
                "fallback": s55_meta.get("fallback"),
                "dbg": s55_meta.get("dbg"),
                "phase": s55_meta.get("phase"),
            }
            apply = True
            reason = str(s55_meta.get("reason") or "s55_specials_divert")
        elif s55_meta.get("skipped") and s55_meta.get("fired"):
            direction["specials_divert"] = {
                "fired": True,
                "cached": True,
                "to_way": s55_meta.get("chosen_way_id"),
                "kill_la": s55_meta.get("kill_la"),
                "kill_lr": s55_meta.get("kill_lr"),
                "dbg": s55_meta.get("dbg"),
                "phase": s55_meta.get("phase"),
            }
        way_kill_meta["s55"] = {
            "kill_la": s55_meta.get("kill_la"),
            "kill_lr": s55_meta.get("kill_lr"),
            "fired": s55_meta.get("fired"),
            "skipped": s55_meta.get("skipped"),
            "chosen_way_id": s55_meta.get("chosen_way_id"),
            "dbg": s55_meta.get("dbg"),
        }
    except Exception as s55_exc:
        s55_meta = {"s55": True, "slice": "C", "reason": f"s55_error:{s55_exc}"}

    # S1: sticky target / way / route — hold until invalidate events
    sticky_meta = {"applied": False, "reason": "sticky_skipped"}
    try:
        from core.strategy_sticky import apply_sticky_layer

        direction, sticky_meta = apply_sticky_layer(game, player, audits, direction)
    except Exception as sticky_exc:
        sticky_meta = {"applied": False, "reason": "sticky_error", "error": str(sticky_exc)}

    report["board_way_override"] = {
        "applied": bool(apply),
        "reason": reason,
        "from_way": abstract.get("preferred_way_id") or abstract.get("way_id"),
        "to_way": direction.get("preferred_way_id"),
        "board_rank_way": _safe_int(_audit_get(winner, "way_id"), -1),
        "preferred_board_diverge": bool(direction.get("preferred_board_diverge")),
        "recommendation": direction.get("recommendation"),
        "recommendation_target_id": direction.get("recommendation_target_id"),
        "supporting_action_type": direction.get("supporting_action_type"),
        "sticky": dict(sticky_meta) if isinstance(sticky_meta, Mapping) else sticky_meta,
        "way_kill": dict(way_kill_meta) if isinstance(way_kill_meta, Mapping) else way_kill_meta,
        "specials_divert": {
            "fired": bool(s55_meta.get("fired")),
            "skipped": bool(s55_meta.get("skipped")),
            "chosen_way_id": s55_meta.get("chosen_way_id"),
            "kill_la": s55_meta.get("kill_la"),
            "kill_lr": s55_meta.get("kill_lr"),
            "dbg": s55_meta.get("dbg"),
            "phase": s55_meta.get("phase"),
        },
    }
    report["s55_specials_divert"] = {
        k: v
        for k, v in dict(s55_meta).items()
        if k not in {"direction_out", "assess"} or k == "assess"
    }
    # Shrink assess for report
    if isinstance(report["s55_specials_divert"].get("assess"), Mapping):
        ass = dict(report["s55_specials_divert"]["assess"])
        ass.pop("snapshot", None)
        report["s55_specials_divert"]["assess"] = {
            "kill_la_recommended": ass.get("kill_la_recommended"),
            "kill_lr_recommended": ass.get("kill_lr_recommended"),
            "la": ass.get("la"),
            "lr": ass.get("lr"),
        }
    report["sticky_commitment"] = dict(sticky_meta) if isinstance(sticky_meta, Mapping) else sticky_meta
    report["s5b_way_kill"] = dict(way_kill_meta) if isinstance(way_kill_meta, Mapping) else way_kill_meta
    # Snapshot abstract for diagnostics
    if isinstance(block, dict):
        if abstract:
            block["abstract_preferred_strategy"] = {
                k: v for k, v in abstract.items()
                if k not in ("candidates", "target_portfolio")
            }
        block["preferred_strategy"] = {
            k: v for k, v in direction.items() if k != "target_portfolio"
        }
        block["board_preferred_strategy"] = direction
        block["sticky_commitment"] = getattr(player, "sticky_commitment", None)
        report.setdefault("by_player", {})[pid] = block
    if persist:
        persist_strategic_direction(player, direction)
        try:
            game.current_board_strategic_direction = direction
        except Exception:
            pass
    return report


def apply_board_way_portfolio_layer(
    report,
    game,
    *,
    enabled=True,
    behavior_override=False,
    hand_only: bool = False,
):
    try:
        from core.performance_trace import timed_span
    except Exception:
        timed_span = None  # type: ignore
    from contextlib import nullcontext

    try:
        stage_top = _resolve_portfolio_top_n(game)
        from core.strategy_reconsider import game_stage_label

        stage_label = game_stage_label(game)
    except Exception:
        stage_top = int(PORTFOLIO_EVAL_TOP_N)
        stage_label = "unknown"
    span_cm = (
        timed_span(
            game,
            "way_portfolio_eval",
            meta={
                "behavior_override": bool(behavior_override),
                "hand_only": bool(hand_only),
                "top_n": int(stage_top),
                "game_stage": str(stage_label),
            },
        )
        if timed_span is not None
        else nullcontext({})
    )
    with span_cm as span_bag:
        out = _apply_board_way_portfolio_layer_impl(
            report,
            game,
            enabled=enabled,
            behavior_override=behavior_override,
            hand_only=hand_only,
        )
        # Attach final cache meta after eval (hit known only after)
        try:
            meta = dict(getattr(game, "_board_way_portfolio_cache_meta", None) or {})
            out.setdefault("settings", {})
            if isinstance(out.get("settings"), dict):
                out["settings"]["portfolio_cache_hit"] = bool(meta.get("hit"))
                out["settings"]["portfolio_cache_way_count"] = meta.get("way_count")
                out["settings"]["portfolio_hand_only"] = bool(hand_only)
            out["portfolio_cache"] = meta
            if isinstance(span_bag, dict):
                bag_meta = span_bag.setdefault("meta", {})
                if isinstance(bag_meta, dict):
                    bag_meta["cache_hit"] = bool(meta.get("hit"))
                    bag_meta["geo_cache_hit"] = bool(meta.get("geo_cache_hit"))
                    bag_meta["hand_rescore"] = bool(meta.get("hand_rescore"))
                    bag_meta["hand_only"] = bool(hand_only)
                    bag_meta["way_count"] = meta.get("way_count")
            if isinstance(out.get("settings"), dict):
                out["settings"]["portfolio_geo_cache_hit"] = bool(meta.get("geo_cache_hit"))
                out["settings"]["portfolio_hand_rescore"] = bool(meta.get("hand_rescore"))
        except Exception:
            pass
        return out


def _patch_direction_eta_from_audit(player: Any, audit: Any) -> None:
    """L0: refresh board ETA fields on sticky preferred direction without way switch."""
    if player is None or audit is None:
        return
    direction = getattr(player, "strategic_direction", None)
    if not isinstance(direction, dict):
        return
    try:
        wid = _safe_int(_audit_get(audit, "way_id"), -1)
        pref = _safe_int(
            direction.get("preferred_way_id") or direction.get("way_id"),
            -1,
        )
        sticky = getattr(player, "sticky_commitment", None)
        sticky_wid = None
        if isinstance(sticky, Mapping):
            sticky_wid = _safe_int(sticky.get("locked_way_id"), -1)
        if wid > 0 and pref > 0 and wid != pref and wid != sticky_wid:
            return
        direction["board_expected_turns"] = _safe_float(
            _audit_get(audit, "board_expected_turns"), INFINITE_TURNS
        )
        direction["realistic_expected_turns"] = _safe_float(
            _audit_get(audit, "realistic_expected_turns"), INFINITE_TURNS
        )
        direction["board_feasibility"] = _audit_get(audit, "feasibility")
        direction["board_recommendation"] = _audit_get(audit, "recommendation")
        direction["recommendation_target_id"] = _audit_get(
            audit, "recommendation_target_id"
        )
        direction["l0_hand_rescore"] = True
        setattr(player, "strategic_direction", direction)
    except Exception:
        pass


def _apply_board_way_portfolio_layer_impl(
    report,
    game,
    *,
    enabled=True,
    behavior_override=False,
    hand_only: bool = False,
):
    settings = dict(report.get("settings", {}) or {})
    settings["board_way_portfolio_enabled"] = bool(enabled)
    if hand_only:
        settings["board_way_portfolio_stage"] = "P3C_L0_hand_only"
        behavior_override = False
    else:
        settings["board_way_portfolio_stage"] = (
            "4G-A_visibility" if not behavior_override else "4G-B_behavior"
        )
    settings["board_way_portfolio_behavior_override"] = bool(behavior_override)
    settings["board_way_portfolio_hand_only"] = bool(hand_only)
    report["settings"] = settings
    if not enabled:
        report["board_way_audits"] = []
        return report
    player = None
    try:
        getter = getattr(game, "get_current_player", None)
        if callable(getter):
            player = getter()
    except Exception:
        player = None
    if player is None:
        try:
            players = list(getattr(game, "players", []) or [])
            player = players[0] if players else None
        except Exception:
            player = None
    if player is None:
        report["board_way_audits"] = []
        report["board_way_audit_error"] = "no_current_player"
        return report
    try:
        stage_top_n = _resolve_portfolio_top_n(game)
        try:
            settings["portfolio_top_n"] = int(stage_top_n)
            from core.strategy_reconsider import game_stage_label

            settings["game_stage"] = game_stage_label(game)
        except Exception:
            settings["portfolio_top_n"] = int(stage_top_n)
        report["settings"] = settings
        if hand_only:
            top_ways = collect_l0_way_ids(report, game, player, limit=3)
        else:
            top_ways = collect_top_way_ids_from_report(
                report, game, player, limit=int(stage_top_n)
            )
        abs_map = {}
        pid = str(getattr(player, "id", ""))
        block = (report.get("by_player") or {}).get(pid) or {}
        for row in list(block.get("baseline_top_strategies", []) or []):
            if isinstance(row, Mapping):
                abs_map[_safe_int(row.get("way_id"), -1)] = _safe_float(row.get("turns", INFINITE_TURNS), INFINITE_TURNS)
        # Prefer sticky/direction abstract ETA when present for L0
        if hand_only and isinstance(getattr(player, "strategic_direction", None), Mapping):
            d = player.strategic_direction
            wid = _safe_int(d.get("preferred_way_id") or d.get("way_id"), -1)
            if wid > 0 and wid not in abs_map:
                for key in ("board_expected_turns", "realistic_expected_turns", "expected_turns", "turns"):
                    if d.get(key) is not None:
                        abs_map[wid] = _safe_float(d.get(key), INFINITE_TURNS)
                        break
        audits = evaluate_top_ways_board_feasibility(
            game, player, top_ways, abstract_turns_by_way=abs_map, use_cache=True
        )
        report["board_way_audits"] = [a.as_dict() for a in audits]
        if audits:
            report["board_feasibility"] = audits[0].feasibility
            report["board_expected_turns"] = audits[0].board_expected_turns
            report["board_realistic_turns"] = audits[0].realistic_expected_turns
            report["board_best_case_turns"] = audits[0].best_case_turns
            report["board_fallback_case_turns"] = audits[0].fallback_case_turns
            report["board_fragility"] = audits[0].fragility
            report["board_recommendation"] = audits[0].recommendation
            report["board_rank_order"] = [a.way_id for a in audits]
        else:
            report["board_feasibility"] = "unknown"
            report["board_recommendation"] = "no_audits"
        if behavior_override and audits:
            apply_board_behavior_override(report, game, player, audits, persist=True)
        elif audits:
            # 4G-A visibility / L0: record pending; patch ETA on current way
            abstract = {}
            pid = str(getattr(player, "id", ""))
            block = (report.get("by_player") or {}).get(pid) or {}
            if isinstance(block, Mapping):
                abstract = dict(block.get("preferred_strategy") or {})
            apply, reason = should_override_abstract_preferred(audits[0], abstract, audits)
            report["board_way_override_pending"] = {
                "would_apply": apply,
                "reason": reason,
                "way_id": audits[0].way_id,
                "recommendation": audits[0].recommendation,
                "hand_only": bool(hand_only),
            }
            if hand_only:
                # Prefer audit matching sticky/preferred way for ETA patch
                match = audits[0]
                pref = _safe_int(
                    (abstract or {}).get("preferred_way_id")
                    or (abstract or {}).get("way_id"),
                    -1,
                )
                sticky = getattr(player, "sticky_commitment", None)
                sticky_wid = (
                    _safe_int(sticky.get("locked_way_id"), -1)
                    if isinstance(sticky, Mapping)
                    else -1
                )
                for a in audits:
                    wid = _safe_int(getattr(a, "way_id", None), -1)
                    if wid > 0 and (wid == sticky_wid or wid == pref):
                        match = a
                        break
                _patch_direction_eta_from_audit(player, match)
                report["l0_hand_only"] = {
                    "ways": [int(w) for w in top_ways],
                    "matched_way": _safe_int(getattr(match, "way_id", None), -1),
                    "board_expected_turns": _safe_float(
                        getattr(match, "board_expected_turns", None), INFINITE_TURNS
                    ),
                }
    except Exception as exc:
        report["board_way_audits"] = []
        report["board_way_audit_error"] = str(exc)
    return report
