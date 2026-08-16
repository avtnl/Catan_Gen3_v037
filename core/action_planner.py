"""
core/action_planner.py

Stage-1/2 build-action timing and projection planner for Catan.

Purpose
-------
This module answers the first action-planning question:

    For each player, how many expected own turns are needed to complete each
    concrete build action that is currently visible from outlook_logic.py?

Stage 1 intentionally does NOT choose the final winning strategy yet. It
ranks concrete build actions by resource timing:

    - upgrade an existing settlement to a city
    - build a settlement at an already reachable next_settlement location
    - build a settlement at a new_settlement location plus the required roads

This version includes:

    Stage 1: build-action timing
    Stage 1B: likely 1:1 player-trade diagnostics
    Stage 2: hypothetical after-action player state
    Stage 3A: top-3 continuation strategy timing after every action
              for the current-turn player by default

Important Stage 3 rule:
    Player-trade opportunities are reported as diagnostics/upside only.
    They are NOT used for the base projection hand, continuation turns,
    total turns, or turn-gain metrics.

Later stages will add:

    Stage 4: tactical/risk scoring for contested locations

Conventions
-----------
Internal resource vectors use the project/game order:

    [Wheat, Ore, Wood, Brick, Wool]

Public report labels use Sheep instead of Wool:

    [Wheat, Ore, Wood, Brick, Sheep]

The module does not mutate game, board, or player state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil, floor, isfinite
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import csv
import json


# ──────────────────────────────────────────────────────────────────────────────
# Expected-Hand imports
# ──────────────────────────────────────────────────────────────────────────────

try:
    from core.resource_time_estimator import (  # type: ignore
        EXPECTED_HAND_CONFIDENCE_TARGET,
        EXPECTED_HAND_CONTINUOUS_TRADING,
        EXPECTED_HAND_MAX_TURNS,
        EXPECTED_HAND_REQUIRE_CONFIDENCE,
        EXPECTED_HAND_ROLLS_PER_PLAYER_TURN,
        EXPECTED_HAND_STEP,
        INFINITE_TURNS,
        clean_int_vector,
        clean_vector,
        compute_payability_with_trades,
        estimate_action_time,
        estimate_new_settlement_target,
        estimate_next_settlement_target,
        finite_or_9999,
        get_player_ports,
        get_player_production_pips,
        get_player_resource_cards_vector,
        get_player_trade_rates,
        get_intersection_resource_pips,
        normalize_port_type,
        trade_rates_after_candidate,
        safe_float,
        safe_int,
        target_cost_vector,
    )
except Exception:  # pragma: no cover - helps static editing outside project.
    EXPECTED_HAND_CONFIDENCE_TARGET = 0.85
    EXPECTED_HAND_CONTINUOUS_TRADING = True
    EXPECTED_HAND_MAX_TURNS = 60.0
    EXPECTED_HAND_REQUIRE_CONFIDENCE = False
    EXPECTED_HAND_ROLLS_PER_PLAYER_TURN = 4
    EXPECTED_HAND_STEP = 0.25
    INFINITE_TURNS = 9999.0

    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except Exception:
            return default

    def clean_vector(values: Optional[Sequence[Any]], length: int = 5, default: float = 0.0) -> List[float]:
        out = [safe_float(v, default) for v in list(values or [])[:length]]
        out.extend([default] * max(0, length - len(out)))
        return out

    def clean_int_vector(values: Optional[Sequence[Any]], length: int = 5, default: int = 4) -> List[int]:
        out = [max(1, safe_int(v, default)) for v in list(values or [])[:length]]
        out.extend([default] * max(0, length - len(out)))
        return out

    def finite_or_9999(value: Any) -> float:
        v = safe_float(value, INFINITE_TURNS)
        return v if isfinite(v) else INFINITE_TURNS

    def _missing(*_: Any, **__: Any) -> Any:
        raise ImportError("core.resource_time_estimator is required for action_planner.py")

    compute_payability_with_trades = _missing
    estimate_action_time = _missing
    estimate_new_settlement_target = _missing
    estimate_next_settlement_target = _missing
    get_player_ports = lambda board, player: []  # noqa: E731
    get_player_production_pips = _missing
    get_player_resource_cards_vector = _missing
    get_player_trade_rates = _missing
    target_cost_vector = _missing

    def get_intersection_resource_pips(board: Any, inter_id: int, multiplier: float = 1.0) -> List[float]:
        return [0.0, 0.0, 0.0, 0.0, 0.0]

    def normalize_port_type(port_type: Optional[str]) -> str:
        if not port_type:
            return ""
        text = str(port_type).strip()
        return "" if not text or text.lower() == "blank" else text.replace("Sheep", "Wool")

    def trade_rates_after_candidate(
        board: Any,
        player: Any,
        candidate_id: Optional[int] = None,
        base_rates: Optional[Sequence[Any]] = None,
    ) -> List[int]:
        return clean_int_vector(base_rates, default=4) if base_rates is not None else [4, 4, 4, 4, 4]




# ──────────────────────────────────────────────────────────────────────────────
# Strategy-timing imports for Stage 3A continuation rows
# ──────────────────────────────────────────────────────────────────────────────
try:
    from core.strategy_timing import (  # type: ignore
        PlayerStrategyState,
        build_player_strategy_state,
        load_strategy_requirements,
        rank_strategies_for_player_state,
    )
    _STRATEGY_TIMING_AVAILABLE = True
except Exception:  # pragma: no cover - lets this file compile outside project.
    PlayerStrategyState = None  # type: ignore
    build_player_strategy_state = None  # type: ignore
    load_strategy_requirements = None  # type: ignore
    rank_strategies_for_player_state = None  # type: ignore
    _STRATEGY_TIMING_AVAILABLE = False

# ──────────────────────────────────────────────────────────────────────────────
# Stage-4A/4B/4C/4D contested-location risk imports
# ──────────────────────────────────────────────────────────────────────────────
try:
    from core.risk_assessment import (  # type: ignore
        DEFAULT_STAGE4_PLAYER_SCOPE,
        STAGE4_SCOPE_ALL_PLAYERS,
        STAGE4_SCOPE_CURRENT_TURN_PLAYER,
        apply_risk_assessment_layer,
    )
    _RISK_ASSESSMENT_AVAILABLE = True
except Exception:  # pragma: no cover - lets this file compile outside project.
    DEFAULT_STAGE4_PLAYER_SCOPE = "current_turn_player"
    STAGE4_SCOPE_CURRENT_TURN_PLAYER = "current_turn_player"
    STAGE4_SCOPE_ALL_PLAYERS = "all_players"
    _RISK_ASSESSMENT_AVAILABLE = False

    def apply_risk_assessment_layer(report: Dict[str, Any], game: Any, **kwargs: Any) -> Dict[str, Any]:
        report.setdefault("warnings", []).append(
            "risk_assessment module is unavailable; Stage-4A/4B/4C/4D risk fields were not calculated"
        )
        return report


# ──────────────────────────────────────────────────────────────────────────────
# Local safe port/trade-rate helpers
# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 needs to project ports after a hypothetical settlement is built.  Some
# older local copies of resource_time_estimator.py changed display wording from
# Wool to Sheep and accidentally left normalize_port_type as text.replace("Sheep")
# without the replacement argument.  To keep this planner robust, use local safe
# helpers for projected port/trade-rate work instead of delegating back into that
# optional helper.

def normalize_port_type(port_type: Optional[str]) -> str:  # type: ignore[no-redef]
    """Return a normalized internal port label, using Wool internally."""
    if not port_type:
        return ""
    text = str(port_type).strip()
    if not text or text.lower() == "blank":
        return ""
    return text.replace("Sheep", "Wool")


def _resource_index_from_display_or_internal_name(name: Any) -> Optional[int]:
    text = str(name or "").strip().lower()
    aliases = {
        "wheat": 0,
        "grain": 0,
        "ore": 1,
        "wood": 2,
        "lumber": 2,
        "brick": 3,
        "wool": 4,
        "sheep": 4,
    }
    return aliases.get(text)


def _resource_index_from_port_type(port_type: Any) -> Optional[int]:
    port = normalize_port_type(port_type)
    if not port.startswith("2:1"):
        return None
    parts = port.split(maxsplit=1)
    if len(parts) != 2:
        return None
    return _resource_index_from_display_or_internal_name(parts[1])


def _trade_rates_from_ports_safe(ports: Iterable[Any]) -> List[int]:
    rates = [4, 4, 4, 4, 4]
    for raw_port in ports or []:
        port = normalize_port_type(raw_port)
        if not port:
            continue
        if port == "3:1":
            rates = [min(rate, 3) for rate in rates]
            continue
        idx = _resource_index_from_port_type(port)
        if idx is not None:
            rates[idx] = min(rates[idx], 2)
    return rates


def _safe_port_type_at_candidate(board: Any, candidate_id: Optional[int]) -> str:
    if candidate_id is None:
        return ""
    try:
        inter = board.intersections[int(candidate_id)]
    except Exception:
        return ""
    if inter is None:
        return ""
    has_port = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
    if not has_port:
        return ""
    return normalize_port_type(getattr(inter, "port_type", ""))


def trade_rates_after_candidate(  # type: ignore[no-redef]
    board: Any,
    player: Any,
    candidate_id: Optional[int] = None,
    base_rates: Optional[Sequence[Any]] = None,
) -> List[int]:
    """
    Return trade rates after a hypothetical candidate settlement.

    This local version avoids calling resource_time_estimator.trade_rates_after_candidate
    so Stage 2 remains compatible with older resource_time_estimator.py copies.
    """
    rates = clean_int_vector(base_rates, default=4) if base_rates is not None else clean_int_vector(
        get_player_trade_rates(board, player), default=4
    )
    port_type = _safe_port_type_at_candidate(board, candidate_id)
    if not port_type:
        return rates
    candidate_rates = _trade_rates_from_ports_safe([port_type])
    return [min(rates[i], candidate_rates[i]) for i in range(5)]


# ──────────────────────────────────────────────────────────────────────────────
# Stage-1 settings
# ──────────────────────────────────────────────────────────────────────────────

DISPLAY_RESOURCE_NAMES: Tuple[str, str, str, str, str] = (
    "Wheat",
    "Ore",
    "Wood",
    "Brick",
    "Sheep",
)

DEFAULT_ACTION_TOP_N: int = 10
DEFAULT_PRIMARY_CONTINUOUS_TRADING: bool = EXPECTED_HAND_CONTINUOUS_TRADING

# Stage 4 will replace this neutral placeholder with contested-location risk.
DEFAULT_STAGE1_RISK_SCORE: float = 0.0

# Stage-1B player-trade layer.
# The first implementation is intentionally conservative:
#   - only 1:1 resource-card trades
#   - at most one card pair between the same two players in one report pass
#   - deterministic tie handling for reports; real gameplay can randomize ties
DEFAULT_ENABLE_PLAYER_TRADES: bool = True
DEFAULT_MAX_PLAYER_TRADES_PER_PAIR: int = 1

# Stage 2 projection settings.
# Continuous-only projections are retained for transparency, but are marked as
# unreliable so Stage 3/4 can ignore or penalize them.
DEFAULT_ENABLE_ACTION_PROJECTIONS: bool = True
DEFAULT_ALLOW_CONTINUOUS_ONLY_PROJECTION: bool = True

# Stage 3A continuation settings.  For every projected action, the planner can
# re-rank the 142-way strategy table from the hypothetical after-action state
# and attach the top-N continuation strategies.
DEFAULT_ENABLE_CONTINUATION_STRATEGIES: bool = True
DEFAULT_CONTINUATION_TOP_N: int = 3

# Stage 3 normal decision support is only for the acting/current-turn player.
# All-player continuations are available for debugging, but are not the default.
STAGE3_SCOPE_CURRENT_TURN_PLAYER: str = "current_turn_player"
STAGE3_SCOPE_ALL_PLAYERS: str = "all_players"
DEFAULT_STAGE3_PLAYER_SCOPE: str = STAGE3_SCOPE_CURRENT_TURN_PLAYER

# Stage 4A risk assessment.  Current default mirrors Stage 3: decision support
# is for the acting/current-turn player.  Opponent data is still used as context.
DEFAULT_ENABLE_RISK_ASSESSMENT: bool = True
DEFAULT_STAGE4_RISK_PLAYER_SCOPE: str = STAGE4_SCOPE_CURRENT_TURN_PLAYER

# Stage 4E preferred-strategy / strategic-direction support.
# This selects a player-level preferred way_id from continuation rows.  It does
# not pick or execute a concrete action.
DEFAULT_ENABLE_STRATEGY_PREFERENCE: bool = True
DEFAULT_STRATEGY_PREFERENCE_MIN_GAIN: float = 0.25
DEFAULT_STRATEGY_PREFERENCE_STRONG_GAIN: float = 2.0
DEFAULT_PERSIST_STRATEGY_PREFERENCE_TO_PLAYER: bool = True

_EPS: float = 1e-9


# ──────────────────────────────────────────────────────────────────────────────
# Data containers
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ActionTradeDiagnostics:
    """Strict vs continuous trade diagnostics for one action estimate."""

    trade_required: bool
    payable_direct: bool
    payable_continuous: bool
    payable_discrete: bool
    continuous_only_trade_estimate: bool
    imports_required: float
    continuous_import_capacity: float
    discrete_import_capacity: int
    continuous_trade_margin: float
    discrete_trade_gap: float
    trade_margin: float
    anticipated_bank_trades: Tuple[str, ...]
    anticipated_bank_trades_text: str
    anticipated_bank_trades_possible: bool
    anticipated_bank_trades_still_missing: Tuple[float, float, float, float, float]
    short: Tuple[float, float, float, float, float]
    surplus: Tuple[float, float, float, float, float]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BuildActionTiming:
    """Stage-1 timing row for one concrete build action."""

    action_id: str
    action_type: str
    target_id: Optional[int]
    description: str
    cost_vector: Tuple[float, float, float, float, float]
    cost_named: Mapping[str, float]
    roads_to_build: Tuple[Tuple[int, int], ...] = field(default_factory=tuple)
    road_count: int = 0
    path: Tuple[Any, ...] = field(default_factory=tuple)
    distance: Optional[int] = None

    action_expected_own_turns: float = INFINITE_TURNS
    action_expected_global_turns: float = INFINITE_TURNS
    action_strict_expected_own_turns: float = INFINITE_TURNS
    action_strict_expected_global_turns: float = INFINITE_TURNS
    found: bool = False
    strict_found: bool = False
    confidence: float = 0.0
    confidence_label: str = "very_low"
    risk_score: float = DEFAULT_STAGE1_RISK_SCORE

    current_hand: Tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)
    production_pips: Tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)
    trade_rates: Tuple[int, int, int, int, int] = (4, 4, 4, 4, 4)
    ports: Tuple[str, ...] = field(default_factory=tuple)
    expected_hand_at_action_time: Tuple[float, float, float, float, float] = (0, 0, 0, 0, 0)
    trade_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    estimate: Mapping[str, Any] = field(default_factory=dict)
    strict_estimate: Mapping[str, Any] = field(default_factory=dict)
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self, *, include_debug: bool = False) -> Dict[str, Any]:
        data = {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target_id": self.target_id,
            "description": self.description,
            "cost_vector": list(self.cost_vector),
            "cost_named": dict(self.cost_named),
            "roads_to_build": [list(r) for r in self.roads_to_build],
            "road_count": self.road_count,
            "path": list(self.path),
            "distance": self.distance,
            "action_expected_own_turns": self.action_expected_own_turns,
            "action_expected_global_turns": self.action_expected_global_turns,
            "action_strict_expected_own_turns": self.action_strict_expected_own_turns,
            "action_strict_expected_global_turns": self.action_strict_expected_global_turns,
            "found": self.found,
            "strict_found": self.strict_found,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "risk_score": self.risk_score,
            "current_hand": list(self.current_hand),
            "current_hand_named": _resource_dict(self.current_hand),
            "production_pips": list(self.production_pips),
            "production_pips_named": _resource_dict(self.production_pips),
            "trade_rates": list(self.trade_rates),
            "trade_rates_named": {DISPLAY_RESOURCE_NAMES[i]: self.trade_rates[i] for i in range(5)},
            "ports": list(self.ports),
            "expected_hand_at_action_time": list(self.expected_hand_at_action_time),
            "expected_hand_at_action_time_named": _resource_dict(self.expected_hand_at_action_time, digits=3),
            "trade_diagnostics": dict(self.trade_diagnostics),
            "notes": list(self.notes),
        }
        if include_debug:
            data["estimate"] = dict(self.estimate)
            data["strict_estimate"] = dict(self.strict_estimate)
        return data


@dataclass(frozen=True)
class ProjectedActionResult:
    """Stage-2 hypothetical after-action state for one build action."""

    projection_valid: bool
    payment_model: str
    payment_reliable: bool
    projection_basis: str
    player_trade_benefit_used_for_projection: bool
    player_trade_projection_note: str
    projection_warnings: Tuple[str, ...]
    post_action_hand: Tuple[float, float, float, float, float]
    player_trade_gives: Tuple[float, float, float, float, float]
    player_trade_receives: Tuple[float, float, float, float, float]
    bank_exports_used: Tuple[float, float, float, float, float]
    bank_imports_received: Tuple[float, float, float, float, float]
    bank_trade_plan: Tuple[str, ...]
    production_gain: Tuple[float, float, float, float, float]
    production_pips_after_action: Tuple[float, float, float, float, float]
    trade_rates_after_action: Tuple[int, int, int, int, int]
    ports_after_action: Tuple[str, ...]
    settlements_after_action: Tuple[int, ...]
    cities_after_action: Tuple[int, ...]
    roads_after_action: Tuple[Tuple[int, int], ...]
    roads_count_after_action: int
    victory_points_after_action: int

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["post_action_hand_named"] = _resource_dict(self.post_action_hand, digits=3)
        data["production_gain_named"] = _resource_dict(self.production_gain, digits=3)
        data["production_pips_after_action_named"] = _resource_dict(self.production_pips_after_action, digits=3)
        data["trade_rates_after_action_named"] = {
            DISPLAY_RESOURCE_NAMES[i]: int(self.trade_rates_after_action[i])
            for i in range(5)
        }
        data["roads_after_action"] = [list(r) for r in self.roads_after_action]
        return data


# ──────────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────────

def _tuple5(values: Sequence[Any]) -> Tuple[float, float, float, float, float]:
    vec = clean_vector(values)
    return (float(vec[0]), float(vec[1]), float(vec[2]), float(vec[3]), float(vec[4]))


def _int_tuple5(values: Sequence[Any]) -> Tuple[int, int, int, int, int]:
    vec = clean_int_vector(values, default=4)
    return (int(vec[0]), int(vec[1]), int(vec[2]), int(vec[3]), int(vec[4]))


def _resource_dict(values: Sequence[Any], *, digits: Optional[int] = None) -> Dict[str, float]:
    vec = clean_vector(values)
    if digits is not None:
        vec = [round(v, digits) for v in vec]
    return {DISPLAY_RESOURCE_NAMES[i]: vec[i] for i in range(5)}


def _resource_compact(values: Sequence[Any]) -> str:
    vec = clean_vector(values)
    labels = ["W", "O", "Wd", "B", "Sh"]
    parts: List[str] = []
    for idx, value in enumerate(vec):
        if abs(value) <= _EPS:
            continue
        rounded = int(round(value))
        shown: Any = rounded if abs(value - rounded) <= _EPS else round(value, 2)
        parts.append(f"{labels[idx]}{shown}")
    return " ".join(parts) if parts else "none"


def _as_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _canonical_road_id(road: Any) -> Optional[Tuple[int, int]]:
    try:
        a, b = tuple(road)
        ai = int(a)
        bi = int(b)
    except Exception:
        return None
    if ai == bi:
        return None
    return (min(ai, bi), max(ai, bi))


def _canonical_road_tuple_list(roads: Optional[Iterable[Any]]) -> Tuple[Tuple[int, int], ...]:
    out: List[Tuple[int, int]] = []
    for road in list(roads or []):
        rid = _canonical_road_id(road)
        if rid is not None and rid not in out:
            out.append(rid)
    return tuple(out)


def _get_num_players(game: Any) -> int:
    try:
        return max(1, len(getattr(game, "players", []) or []))
    except Exception:
        return EXPECTED_HAND_ROLLS_PER_PLAYER_TURN


def _get_player_outlook(player: Any) -> Any:
    outlooks = getattr(player, "outlook", []) or []
    return outlooks[0] if outlooks else None


def _safe_sorted_unique_ints(values: Iterable[Any]) -> List[int]:
    out: List[int] = []
    for value in values or []:
        as_int = _as_int_or_none(value)
        if as_int is not None and as_int not in out:
            out.append(as_int)
    return sorted(out)


def _global_turns(own_turns: Any, num_players: int) -> float:
    turns = finite_or_9999(own_turns)
    if turns >= INFINITE_TURNS:
        return INFINITE_TURNS
    return float(turns) * max(1, int(num_players))


def _action_sort_key(row: BuildActionTiming) -> Tuple[Any, ...]:
    diag = dict(row.trade_diagnostics or {})
    continuous_only = bool(diag.get("continuous_only_trade_estimate", False))
    discrete_gap = safe_float(diag.get("discrete_trade_gap"), 0.0)
    return (
        not row.found,
        finite_or_9999(row.action_expected_own_turns),
        safe_float(row.risk_score, 0.0),
        -safe_float(row.confidence, 0.0),
        continuous_only,
        discrete_gap,
        row.action_type,
        row.target_id if row.target_id is not None else 999999,
        row.road_count,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Trade diagnostics
# ──────────────────────────────────────────────────────────────────────────────

def _trade_resource_abbr(index: int) -> str:
    """Compact resource labels for trade display."""
    return ("W", "O", "Wd", "B", "Sh")[int(index)]


def _format_trade_group(rate: int, exporter: int, importer: int, count: int) -> str:
    """Return a compact trade label such as 4W->1B (2x)."""
    base = f"{int(rate)}{_trade_resource_abbr(exporter)}->1{_trade_resource_abbr(importer)}"
    return f"{base} ({int(count)}x)" if int(count) > 1 else base


def _anticipated_whole_bank_trade_plan_detailed(
    expected_hand: Sequence[Any],
    cost_vector: Sequence[Any],
    trade_rates: Sequence[Any],
) -> Dict[str, Any]:
    """
    Build a strict whole-card bank/port trade plan plus export/import vectors.

    This is intentionally stricter than the continuous expected-hand trade plan.
    It uses whole outgoing groups, for example 4 Wheat -> 1 Brick.
    """
    hand = clean_vector(expected_hand)
    need = clean_vector(cost_vector)
    rates = clean_int_vector(trade_rates, default=4)

    missing_cards = [int(max(0, ceil(need[i] - hand[i] - _EPS))) for i in range(5)]
    exports_used = [0.0] * 5
    imports_received = [0.0] * 5

    if sum(missing_cards) <= 0:
        return {
            "labels": tuple(),
            "possible": True,
            "still_missing": _tuple5([0, 0, 0, 0, 0]),
            "exports_used": _tuple5(exports_used),
            "imports_received": _tuple5(imports_received),
            "operations": tuple(),
        }

    available_trades = [int(floor(max(0.0, hand[i] - need[i]) / max(1, rates[i]) + _EPS)) for i in range(5)]

    exporters = sorted(
        range(5),
        key=lambda idx: (rates[idx], -max(0.0, hand[idx] - need[idx]), idx),
    )
    importers = sorted(
        [idx for idx, missing in enumerate(missing_cards) if missing > 0],
        key=lambda idx: (-missing_cards[idx], idx),
    )

    groups: Dict[Tuple[int, int, int], int] = {}
    operations: List[Dict[str, Any]] = []

    for importer in importers:
        while missing_cards[importer] > 0:
            exporter = next((idx for idx in exporters if available_trades[idx] > 0), None)
            if exporter is None:
                break

            rate = max(1, int(rates[exporter]))
            available_trades[exporter] -= 1
            missing_cards[importer] -= 1
            exports_used[exporter] += float(rate)
            imports_received[importer] += 1.0

            key = (rate, exporter, importer)
            groups[key] = groups.get(key, 0) + 1
            operations.append(
                {
                    "rate": rate,
                    "export_resource": DISPLAY_RESOURCE_NAMES[exporter],
                    "import_resource": DISPLAY_RESOURCE_NAMES[importer],
                    "export_index": exporter,
                    "import_index": importer,
                    "quantity": 1,
                }
            )

    labels = tuple(
        _format_trade_group(rate, exporter, importer, count)
        for (rate, exporter, importer), count in groups.items()
    )

    return {
        "labels": labels,
        "possible": sum(missing_cards) <= 0,
        "still_missing": _tuple5(missing_cards),
        "exports_used": _tuple5(exports_used),
        "imports_received": _tuple5(imports_received),
        "operations": tuple(operations),
    }


def _anticipated_whole_bank_trade_plan(
    expected_hand: Sequence[Any],
    cost_vector: Sequence[Any],
    trade_rates: Sequence[Any],
) -> Tuple[Tuple[str, ...], bool, Tuple[float, float, float, float, float]]:
    """Backward-compatible wrapper around the detailed strict trade plan."""
    plan = _anticipated_whole_bank_trade_plan_detailed(expected_hand, cost_vector, trade_rates)
    return (
        tuple(plan["labels"]),
        bool(plan["possible"]),
        _tuple5(plan["still_missing"]),
    )


def compute_action_trade_diagnostics(
    expected_hand: Sequence[Any],
    cost_vector: Sequence[Any],
    trade_rates: Sequence[Any],
) -> ActionTradeDiagnostics:
    """
    Compare continuous expected trading with strict whole bank/port trading.

    The continuous model can say that 16.167 surplus cards at 4:1 can import
    about 4.042 cards.  Real Catan bank trading is stricter: each trade needs
    a whole group of cards at that resource's trade rate.
    """
    hand = clean_vector(expected_hand)
    need = clean_vector(cost_vector)
    rates = clean_int_vector(trade_rates, default=4)

    continuous = compute_payability_with_trades(hand, need, rates, continuous=True)
    discrete = compute_payability_with_trades(hand, need, rates, continuous=False)

    short = [max(0.0, need[i] - hand[i]) for i in range(5)]
    surplus = [max(0.0, hand[i] - need[i]) for i in range(5)]

    imports_required = float(sum(short))
    continuous_capacity = float(sum(surplus[i] / max(1, rates[i]) for i in range(5)))
    discrete_capacity = int(sum(floor((surplus[i] + _EPS) / max(1, rates[i])) for i in range(5)))

    payable_direct = bool(continuous.get("payable_direct", False)) or bool(discrete.get("payable_direct", False))
    payable_continuous = bool(continuous.get("payable_after_trades", False))
    payable_discrete = bool(discrete.get("payable_after_trades", False))
    continuous_only = bool(payable_continuous and not payable_discrete)

    continuous_margin = continuous_capacity - imports_required if imports_required > _EPS else 0.0
    discrete_gap = max(0.0, imports_required - float(discrete_capacity)) if not payable_discrete else 0.0

    # User-facing trade margin should not reward fractional/continuous-only
    # estimates.  It is positive only when strict whole trades really cover the
    # required imports.
    if imports_required > _EPS and payable_discrete:
        trade_margin = max(0.0, float(discrete_capacity) - imports_required)
    else:
        trade_margin = 0.0

    anticipated_trades, anticipated_possible, still_missing = _anticipated_whole_bank_trade_plan(
        hand,
        need,
        rates,
    )

    return ActionTradeDiagnostics(
        trade_required=imports_required > _EPS,
        payable_direct=payable_direct,
        payable_continuous=payable_continuous,
        payable_discrete=payable_discrete,
        continuous_only_trade_estimate=continuous_only,
        imports_required=round(imports_required, 6),
        continuous_import_capacity=round(continuous_capacity, 6),
        discrete_import_capacity=discrete_capacity,
        continuous_trade_margin=round(continuous_margin, 6),
        discrete_trade_gap=round(discrete_gap, 6),
        trade_margin=round(trade_margin, 6),
        anticipated_bank_trades=anticipated_trades,
        anticipated_bank_trades_text=", ".join(anticipated_trades) if anticipated_trades else "",
        anticipated_bank_trades_possible=anticipated_possible,
        anticipated_bank_trades_still_missing=still_missing,
        short=_tuple5(short),
        surplus=_tuple5(surplus),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Candidate extraction
# ──────────────────────────────────────────────────────────────────────────────

def _iter_city_upgrade_targets(player: Any) -> List[int]:
    """Current settlement locations that can be considered for city upgrades."""
    cities = set(_safe_sorted_unique_ints(getattr(player, "cities", []) or []))
    settlements = _safe_sorted_unique_ints(getattr(player, "settlements", []) or [])
    return [sid for sid in settlements if sid not in cities]


def _iter_next_settlement_targets(player: Any) -> List[int]:
    """Reachable settlement targets from outlook.next_settlements."""
    outlook = _get_player_outlook(player)
    if outlook is None:
        return []
    return _safe_sorted_unique_ints(getattr(outlook, "next_settlements", []) or [])


def _iter_new_settlement_records(player: Any) -> List[Dict[str, Any]]:
    """
    New settlement path records from outlook.new_settlement_paths.

    If the same target appears multiple times, keep the shortest/cheapest road
    path for Stage 1.  Later stages can preserve alternatives if path choice
    itself becomes tactically important.
    """
    outlook = _get_player_outlook(player)
    if outlook is None:
        return []

    best_by_target: Dict[int, Dict[str, Any]] = {}

    for raw in list(getattr(outlook, "new_settlement_paths", []) or []):
        if not isinstance(raw, Mapping):
            continue

        target = _as_int_or_none(raw.get("intersection_id"))
        if target is None:
            continue

        roads = _canonical_road_tuple_list(raw.get("roads_to_build", []) or [])
        road_count = safe_int(raw.get("road_count", len(roads)), len(roads))
        distance = safe_int(raw.get("distance", len(raw.get("path", []) or [])), len(raw.get("path", []) or []))

        record = {
            "intersection_id": target,
            "roads_to_build": roads,
            "road_count": road_count,
            "distance": distance,
            "path": list(raw.get("path", []) or []),
            "raw": dict(raw),
        }

        previous = best_by_target.get(target)
        if previous is None:
            best_by_target[target] = record
            continue

        prev_key = (safe_int(previous.get("road_count"), 999999), safe_int(previous.get("distance"), 999999))
        new_key = (road_count, distance)
        if new_key < prev_key:
            best_by_target[target] = record

    return [best_by_target[key] for key in sorted(best_by_target)]


# ──────────────────────────────────────────────────────────────────────────────
# Core Stage-1 evaluation
# ──────────────────────────────────────────────────────────────────────────────

def _make_action_row(
    *,
    game: Any,
    board: Any,
    player: Any,
    action_type: str,
    target_id: Optional[int],
    roads_to_build: Sequence[Tuple[int, int]],
    path: Sequence[Any],
    distance: Optional[int],
    cost_vector: Sequence[Any],
    estimate: Mapping[str, Any],
    strict_estimate: Mapping[str, Any],
    current_hand: Sequence[Any],
    production_pips: Sequence[Any],
    trade_rates: Sequence[Any],
    ports: Sequence[str],
    num_players: int,
) -> BuildActionTiming:
    turns = finite_or_9999(estimate.get("turns"))
    strict_turns = finite_or_9999(strict_estimate.get("turns"))
    expected_hand = clean_vector(estimate.get("expected_hand", current_hand))
    diag = compute_action_trade_diagnostics(expected_hand, cost_vector, trade_rates)

    cost = _tuple5(cost_vector)
    roads = tuple(roads_to_build or [])

    if action_type == "city_upgrade":
        description = f"Upgrade settlement {target_id} to city"
    elif action_type == "next_settlement":
        description = f"Build settlement at reachable intersection {target_id}"
    elif action_type == "new_settlement":
        description = f"Build settlement at intersection {target_id} plus {len(roads)} road(s)"
    else:
        description = f"{action_type} at {target_id}"

    notes: List[str] = []
    if diag.continuous_only_trade_estimate:
        notes.append("continuous_only_trade_estimate")
    if not diag.payable_discrete and diag.trade_required:
        notes.append("strict_discrete_trade_not_payable_at_reported_turn")

    return BuildActionTiming(
        action_id=f"P{getattr(player, 'id', '?')}:{action_type}:{target_id}:{len(roads)}",
        action_type=action_type,
        target_id=target_id,
        description=description,
        cost_vector=cost,
        cost_named=_resource_dict(cost),
        roads_to_build=tuple(roads),
        road_count=len(roads),
        path=tuple(path or []),
        distance=distance,
        action_expected_own_turns=float(turns),
        action_expected_global_turns=_global_turns(turns, num_players),
        action_strict_expected_own_turns=float(strict_turns),
        action_strict_expected_global_turns=_global_turns(strict_turns, num_players),
        found=bool(estimate.get("found", False)),
        strict_found=bool(strict_estimate.get("found", False)),
        confidence=safe_float(estimate.get("confidence"), 0.0),
        confidence_label=str(estimate.get("confidence_label", "very_low")),
        risk_score=DEFAULT_STAGE1_RISK_SCORE,
        current_hand=_tuple5(current_hand),
        production_pips=_tuple5(production_pips),
        trade_rates=_int_tuple5(trade_rates),
        ports=tuple(str(port) for port in ports or []),
        expected_hand_at_action_time=_tuple5(expected_hand),
        trade_diagnostics=diag.as_dict(),
        estimate=dict(estimate),
        strict_estimate=dict(strict_estimate),
        notes=tuple(notes),
    )


def build_action_timings_for_player(
    game: Any,
    player: Any,
    *,
    top_n_actions: Optional[int] = DEFAULT_ACTION_TOP_N,
    include_all: bool = True,
    include_debug: bool = False,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = DEFAULT_PRIMARY_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
) -> Dict[str, Any]:
    """
    Return Stage-1 action timing rows for one player.

    The report includes all discovered city/settlement actions when include_all
    is True.  best_actions is capped by top_n_actions.
    """
    board = getattr(game, "board", None)
    if board is None:
        raise ValueError("game.board is required")

    num_players = _get_num_players(game)
    current_turn = safe_int(getattr(game, "turn", None), 0)
    target_player_id = safe_int(getattr(player, "id", None), 0)

    hand = get_player_resource_cards_vector(player)
    pips = get_player_production_pips(board, player)
    rates = get_player_trade_rates(board, player)
    ports = get_player_ports(board, player)

    rows: List[BuildActionTiming] = []

    # A. Existing settlements -> city upgrades.
    for settlement_id in _iter_city_upgrade_targets(player):
        cost = target_cost_vector("city")
        estimate = estimate_action_time(
            board=board,
            player=player,
            target_type="city",
            target_id=settlement_id,
            current_hand=hand,
            production_pips=pips,
            trade_rates=rates,
            confidence_target=confidence_target,
            current_turn=current_turn,
            target_player_id=target_player_id,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=continuous_trading,
            require_confidence=require_confidence,
        )
        strict_estimate = estimate_action_time(
            board=board,
            player=player,
            target_type="city",
            target_id=settlement_id,
            current_hand=hand,
            production_pips=pips,
            trade_rates=rates,
            confidence_target=confidence_target,
            current_turn=current_turn,
            target_player_id=target_player_id,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=False,
            require_confidence=require_confidence,
        )
        rows.append(
            _make_action_row(
                game=game,
                board=board,
                player=player,
                action_type="city_upgrade",
                target_id=settlement_id,
                roads_to_build=[],
                path=[],
                distance=None,
                cost_vector=cost,
                estimate=estimate,
                strict_estimate=strict_estimate,
                current_hand=hand,
                production_pips=pips,
                trade_rates=rates,
                ports=ports,
                num_players=num_players,
            )
        )

    # B. Already reachable next settlements -> settlement only.
    for settlement_id in _iter_next_settlement_targets(player):
        cost = target_cost_vector("settlement_0r")
        estimate = estimate_next_settlement_target(
            board=board,
            player=player,
            settlement_id=settlement_id,
            current_hand=hand,
            production_pips=pips,
            trade_rates=rates,
            confidence_target=confidence_target,
            current_turn=current_turn,
            target_player_id=target_player_id,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=continuous_trading,
            require_confidence=require_confidence,
        )
        strict_estimate = estimate_next_settlement_target(
            board=board,
            player=player,
            settlement_id=settlement_id,
            current_hand=hand,
            production_pips=pips,
            trade_rates=rates,
            confidence_target=confidence_target,
            current_turn=current_turn,
            target_player_id=target_player_id,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=False,
            require_confidence=require_confidence,
        )
        rows.append(
            _make_action_row(
                game=game,
                board=board,
                player=player,
                action_type="next_settlement",
                target_id=settlement_id,
                roads_to_build=[],
                path=[],
                distance=None,
                cost_vector=cost,
                estimate=estimate,
                strict_estimate=strict_estimate,
                current_hand=hand,
                production_pips=pips,
                trade_rates=rates,
                ports=ports,
                num_players=num_players,
            )
        )

    # C. New settlements -> settlement + required roads.
    for record in _iter_new_settlement_records(player):
        settlement_id = safe_int(record.get("intersection_id"), -1)
        if settlement_id < 0:
            continue
        roads_to_build = _canonical_road_tuple_list(record.get("roads_to_build", []) or [])
        road_count = len(roads_to_build)
        cost = target_cost_vector(f"settlement_{road_count}r", extra_roads_needed=road_count)
        estimate = estimate_new_settlement_target(
            board=board,
            player=player,
            settlement_id=settlement_id,
            roads_to_build=roads_to_build,
            current_hand=hand,
            production_pips=pips,
            trade_rates=rates,
            confidence_target=confidence_target,
            current_turn=current_turn,
            target_player_id=target_player_id,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=continuous_trading,
            require_confidence=require_confidence,
        )
        strict_estimate = estimate_new_settlement_target(
            board=board,
            player=player,
            settlement_id=settlement_id,
            roads_to_build=roads_to_build,
            current_hand=hand,
            production_pips=pips,
            trade_rates=rates,
            confidence_target=confidence_target,
            current_turn=current_turn,
            target_player_id=target_player_id,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=False,
            require_confidence=require_confidence,
        )
        rows.append(
            _make_action_row(
                game=game,
                board=board,
                player=player,
                action_type="new_settlement",
                target_id=settlement_id,
                roads_to_build=roads_to_build,
                path=list(record.get("path", []) or []),
                distance=safe_int(record.get("distance"), road_count),
                cost_vector=cost,
                estimate=estimate,
                strict_estimate=strict_estimate,
                current_hand=hand,
                production_pips=pips,
                trade_rates=rates,
                ports=ports,
                num_players=num_players,
            )
        )

    rows.sort(key=_action_sort_key)

    limit = len(rows) if top_n_actions is None else max(0, int(top_n_actions))
    best_rows = rows[:limit]

    player_block = {
        "player": {
            "player_id": getattr(player, "id", None),
            "color": getattr(player, "color", ""),
            "current_hand": list(_tuple5(hand)),
            "current_hand_named": _resource_dict(hand),
            "production_pips": list(_tuple5(pips)),
            "production_pips_named": _resource_dict(pips),
            "trade_rates": list(_int_tuple5(rates)),
            "trade_rates_named": {DISPLAY_RESOURCE_NAMES[i]: int(_int_tuple5(rates)[i]) for i in range(5)},
            "ports": list(ports or []),
            "settlements": _safe_sorted_unique_ints(getattr(player, "settlements", []) or []),
            "cities": _safe_sorted_unique_ints(getattr(player, "cities", []) or []),
            "roads_count": len(getattr(player, "roads", []) or []),
        },
        "settings": {
            "stage": 1,
            "top_n_actions": top_n_actions,
            "include_all": include_all,
            "include_debug": include_debug,
            "confidence_target": confidence_target,
            "num_players": num_players,
            "step": step,
            "max_turns": max_turns,
            "continuous_trading": continuous_trading,
            "require_confidence": require_confidence,
            "risk_score_is_placeholder": True,
        },
        "best_actions": [row.as_dict(include_debug=include_debug) for row in best_rows],
    }

    if include_all:
        player_block["all_candidate_actions"] = [row.as_dict(include_debug=include_debug) for row in rows]

    return player_block



# ──────────────────────────────────────────────────────────────────────────────
# Stage-1B player-trade layer
# ──────────────────────────────────────────────────────────────────────────────

def _whole_short_and_surplus(
    expected_hand: Sequence[Any],
    cost_vector: Sequence[Any],
) -> Tuple[List[int], List[int]]:
    """Return whole-card shortages and whole-card surpluses for player trades."""
    hand = clean_vector(expected_hand)
    need = clean_vector(cost_vector)
    short = [int(max(0, ceil(need[i] - hand[i] - _EPS))) for i in range(5)]
    surplus = [int(max(0, floor(hand[i] - need[i] + _EPS))) for i in range(5)]
    return short, surplus


def _player_victory_points_from_game(game: Any, player_id: Any) -> int:
    """Best-effort victory-point lookup used only for player-trade priority."""
    try:
        pid = int(player_id)
    except Exception:
        pid = player_id

    for player in getattr(game, "players", []) or []:
        if getattr(player, "id", None) != pid:
            try:
                if int(getattr(player, "id", -999999)) != int(pid):
                    continue
            except Exception:
                continue

        for attr in ("victory_points", "points", "vp", "score"):
            value = getattr(player, attr, None)
            if value is not None:
                return max(0, safe_int(value, 0))

        # Conservative Catan fallback: settlements are 1 VP, cities are 2 VP.
        settlements = len(getattr(player, "settlements", []) or [])
        cities = len(getattr(player, "cities", []) or [])
        return int(settlements + 2 * cities)

    return 0


def _report_action_entries(report: Mapping[str, Any]) -> List[Tuple[int, Dict[str, Any], Dict[str, Any]]]:
    """
    Return (player_id, player_info, action_dict) for every action row available.

    Prefer all_candidate_actions when present because the player-trade profile
    should understand the player's broader near-term demand/supply, not only the
    already-capped best_actions list.
    """
    entries: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []
    for player_block in (report.get("by_player", {}) or {}).values():
        player_info = dict(player_block.get("player", {}) or {})
        pid = safe_int(player_info.get("player_id"), 0)
        actions = list(player_block.get("all_candidate_actions", []) or player_block.get("best_actions", []) or [])
        for action in actions:
            if isinstance(action, Mapping):
                entries.append((pid, player_info, action))
    return entries


def _build_player_trade_profiles(report: Mapping[str, Any], game: Any) -> Dict[int, Dict[str, Any]]:
    """
    Build player-level demand/supply profiles from Stage-1 action rows.

    demand[i] is the maximum whole-card shortage of resource i across the
    player's visible candidate actions.  supply[i] is the maximum whole-card
    surplus of resource i across those actions.  This makes the layer report
    mutually useful trades, without committing to one final action yet.
    """
    profiles: Dict[int, Dict[str, Any]] = {}

    for pid, player_info, action in _report_action_entries(report):
        if pid not in profiles:
            profiles[pid] = {
                "player_id": pid,
                "color": player_info.get("color", ""),
                "victory_points": _player_victory_points_from_game(game, pid),
                "production_pips": clean_vector(player_info.get("production_pips", [0, 0, 0, 0, 0])),
                "demand": [0, 0, 0, 0, 0],
                "supply": [0, 0, 0, 0, 0],
            }

        short, surplus = _whole_short_and_surplus(
            action.get("expected_hand_at_action_time", []),
            action.get("cost_vector", []),
        )
        for idx in range(5):
            profiles[pid]["demand"][idx] = max(profiles[pid]["demand"][idx], short[idx])
            profiles[pid]["supply"][idx] = max(profiles[pid]["supply"][idx], surplus[idx])

    return profiles


def _format_player_trade_for_player(trade: Mapping[str, Any], player_id: int) -> str:
    """Return player-perspective text such as P1->P4: 1W->1B."""
    a = int(trade["player_a_id"])
    b = int(trade["player_b_id"])
    a_gives = int(trade["a_gives"])
    b_gives = int(trade["b_gives"])

    if int(player_id) == a:
        other = b
        give = a_gives
        receive = b_gives
    elif int(player_id) == b:
        other = a
        give = b_gives
        receive = a_gives
    else:
        return ""

    return f"P{player_id}->P{other}: 1{_trade_resource_abbr(give)}->1{_trade_resource_abbr(receive)}"


def _allocate_likely_player_trades(
    profiles: Mapping[int, Mapping[str, Any]],
    *,
    max_trades_per_pair: int = DEFAULT_MAX_PLAYER_TRADES_PER_PAIR,
) -> List[Dict[str, Any]]:
    """
    Allocate likely mutually useful 1:1 player trades.

    Interpretation:
        B needs resource X.
        A can give X.
        A needs resource Y.
        B can give Y.

    Then A gives X to B and B gives Y to A.

    If several players can satisfy the same need, the report prioritizes the
    offer from the lower-victory-point player.  When victory points tie, the
    report uses deterministic player-id order and records the tie in the reason;
    real gameplay can randomize that tie later.
    """
    mutable: Dict[int, Dict[str, Any]] = {}
    for pid, profile in profiles.items():
        mutable[int(pid)] = {
            "player_id": int(pid),
            "color": profile.get("color", ""),
            "victory_points": safe_int(profile.get("victory_points"), 0),
            "production_pips": clean_vector(profile.get("production_pips", [0, 0, 0, 0, 0])),
            "demand": [safe_int(x, 0) for x in profile.get("demand", [0, 0, 0, 0, 0])],
            "supply": [safe_int(x, 0) for x in profile.get("supply", [0, 0, 0, 0, 0])],
        }

    accepted: List[Dict[str, Any]] = []
    pair_counts: Dict[Tuple[int, int], int] = {}
    player_ids = sorted(mutable)

    for receiver_id in player_ids:
        receiver = mutable[receiver_id]

        # Larger shortages first, then fixed resource order for readability.
        wanted_resources = sorted(
            range(5),
            key=lambda idx: (-receiver["demand"][idx], receiver["production_pips"][idx], idx),
        )

        for wanted in wanted_resources:
            while receiver["demand"][wanted] > 0:
                candidates: List[Tuple[Any, ...]] = []

                for giver_id in player_ids:
                    if giver_id == receiver_id:
                        continue

                    pair_key = (min(receiver_id, giver_id), max(receiver_id, giver_id))
                    if pair_counts.get(pair_key, 0) >= max(0, int(max_trades_per_pair)):
                        continue

                    giver = mutable[giver_id]

                    # Giver must be able to give the resource receiver wants.
                    if giver["supply"][wanted] <= 0:
                        continue

                    # Receiver must be able to give something the giver wants.
                    for receiver_gives in range(5):
                        if receiver_gives == wanted:
                            continue
                        if receiver["supply"][receiver_gives] <= 0:
                            continue
                        if giver["demand"][receiver_gives] <= 0:
                            continue

                        # Lower VP player gets priority.  If tied, deterministic
                        # player-id/resource order keeps the report reproducible.
                        tie_count = sum(
                            1
                            for other_id in player_ids
                            if other_id != receiver_id
                            and mutable[other_id]["supply"][wanted] > 0
                            and mutable[other_id]["victory_points"] == giver["victory_points"]
                        )
                        candidates.append(
                            (
                                giver["victory_points"],
                                giver["production_pips"][receiver_gives],
                                -giver["demand"][receiver_gives],
                                -receiver["demand"][wanted],
                                giver_id,
                                receiver_gives,
                                tie_count,
                            )
                        )

                if not candidates:
                    break

                vp, _giver_pips, _giver_need, _receiver_need, giver_id, receiver_gives, tie_count = sorted(candidates)[0]
                giver = mutable[giver_id]
                pair_key = (min(receiver_id, giver_id), max(receiver_id, giver_id))

                # Trade orientation in the stored record: player_a gives wanted
                # to player_b, while player_b gives receiver_gives to player_a.
                trade = {
                    "player_a_id": giver_id,
                    "player_b_id": receiver_id,
                    "a_gives": wanted,
                    "b_gives": int(receiver_gives),
                    "quantity": 1,
                    "status": "likely_accepted_tie" if tie_count > 1 else "likely_accepted",
                    "reason": (
                        f"P{receiver_id} needs {_trade_resource_abbr(wanted)} and P{giver_id} can offer it; "
                        f"P{giver_id} needs {_trade_resource_abbr(receiver_gives)} and P{receiver_id} can offer it. "
                        f"Offer priority uses lower victory points first"
                        + ("; victory-point tie is reported deterministically" if tie_count > 1 else "")
                        + "."
                    ),
                }
                accepted.append(trade)

                receiver["demand"][wanted] -= 1
                giver["supply"][wanted] -= 1
                giver["demand"][receiver_gives] -= 1
                receiver["supply"][receiver_gives] -= 1
                pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1

    return accepted


def _apply_player_trades_to_action(
    action: Dict[str, Any],
    player_id: int,
    accepted_trades: Sequence[Mapping[str, Any]],
) -> None:
    """Attach player-trade diagnostics to one action dictionary in-place."""
    hand = clean_vector(action.get("expected_hand_at_action_time", []))
    cost = clean_vector(action.get("cost_vector", []))
    rates = clean_int_vector(action.get("trade_rates", []), default=4)
    row_short, row_surplus = _whole_short_and_surplus(hand, cost)

    relevant_trades: List[Mapping[str, Any]] = []
    adjusted_hand = list(hand)

    for trade in accepted_trades:
        a = safe_int(trade.get("player_a_id"), -1)
        b = safe_int(trade.get("player_b_id"), -1)
        if player_id not in (a, b):
            continue

        if player_id == a:
            give = safe_int(trade.get("a_gives"), -1)
            receive = safe_int(trade.get("b_gives"), -1)
        else:
            give = safe_int(trade.get("b_gives"), -1)
            receive = safe_int(trade.get("a_gives"), -1)

        if not (0 <= give < 5 and 0 <= receive < 5):
            continue

        # A player-trade row is relevant for this action only when it gives away
        # an expected whole surplus card and receives a card this action lacks.
        if row_short[receive] <= 0 or row_surplus[give] <= 0:
            continue

        row_short[receive] -= 1
        row_surplus[give] -= 1
        adjusted_hand[give] -= 1.0
        adjusted_hand[receive] += 1.0
        relevant_trades.append(trade)

    adjusted_diag = compute_action_trade_diagnostics(adjusted_hand, cost, rates)

    player_trade_texts = [
        text
        for text in (_format_player_trade_for_player(trade, player_id) for trade in relevant_trades)
        if text
    ]
    counterparties = sorted(
        {
            safe_int(trade.get("player_b_id"), -1) if safe_int(trade.get("player_a_id"), -1) == player_id else safe_int(trade.get("player_a_id"), -1)
            for trade in relevant_trades
        }
    )
    statuses = sorted({str(trade.get("status", "likely_accepted")) for trade in relevant_trades})

    action["player_trade_diagnostics"] = {
        "anticipated_player_trades": [dict(t) for t in relevant_trades],
        "anticipated_player_trades_text": ", ".join(player_trade_texts),
        "anticipated_player_trades_possible": bool(relevant_trades),
        "anticipated_player_trade_count": len(relevant_trades),
        "anticipated_player_trade_counterparties": [pid for pid in counterparties if pid >= 0],
        "anticipated_player_trade_status": ",".join(statuses) if statuses else "none",
        "expected_hand_after_player_trades": _tuple5(adjusted_hand),
        "bank_trades_after_player_trades": adjusted_diag.anticipated_bank_trades,
        "bank_trades_after_player_trades_text": adjusted_diag.anticipated_bank_trades_text,
        "bank_trades_after_player_trades_possible": adjusted_diag.anticipated_bank_trades_possible,
        "player_trade_adjusted_still_missing": adjusted_diag.anticipated_bank_trades_still_missing,
        "player_trade_adjusted_payable_discrete": adjusted_diag.payable_discrete,
        "player_trade_adjusted_discrete_trade_gap": adjusted_diag.discrete_trade_gap,
        "player_trade_adjusted_trade_margin": adjusted_diag.trade_margin,
        "player_trade_adjusted_expected_own_turns": action.get("action_expected_own_turns"),
        "note": "Player trades are evaluated at the same Stage-1 action timing horizon; earlier timing search is a later refinement.",
    }


def apply_player_trade_layer(
    report: Dict[str, Any],
    game: Any,
    *,
    enabled: bool = DEFAULT_ENABLE_PLAYER_TRADES,
    max_trades_per_pair: int = DEFAULT_MAX_PLAYER_TRADES_PER_PAIR,
) -> Dict[str, Any]:
    """
    Add Stage-1B likely 1:1 player-trade diagnostics to an action report.

    This keeps bank-trade timing intact and adds separate player-trade columns
    for analysis.  Player trades are not guaranteed, so later Stage 4 risk
    scoring should treat player_trade_dependency as a tactical/risk input.
    """
    settings = dict(report.get("settings", {}) or {})
    settings["player_trades_enabled"] = bool(enabled)
    settings["player_trade_model"] = "mutually_useful_1_to_1_conservative"
    settings["max_player_trades_per_pair"] = int(max_trades_per_pair)
    report["settings"] = settings

    if not enabled:
        return report

    profiles = _build_player_trade_profiles(report, game)
    accepted_trades = _allocate_likely_player_trades(
        profiles,
        max_trades_per_pair=max_trades_per_pair,
    )

    report["player_trade_summary"] = {
        "profiles": profiles,
        "accepted_trades": accepted_trades,
        "notes": [
            "Only mutually useful 1:1 player trades are considered.",
            "Rows keep base bank-trade timing; player-trade-adjusted diagnostics are separate.",
            "Tie handling is deterministic in reports; gameplay can randomize equal-VP choices later.",
        ],
    }

    for player_block in (report.get("by_player", {}) or {}).values():
        player_info = player_block.get("player", {}) or {}
        pid = safe_int(player_info.get("player_id"), 0)
        for key in ("best_actions", "all_candidate_actions"):
            for action in list(player_block.get(key, []) or []):
                if isinstance(action, dict):
                    _apply_player_trades_to_action(action, pid, accepted_trades)

    return report



# ──────────────────────────────────────────────────────────────────────────────
# Stage-2 after-action projection layer
# ──────────────────────────────────────────────────────────────────────────────

def _vector_add(a: Sequence[Any], b: Sequence[Any]) -> List[float]:
    av = clean_vector(a)
    bv = clean_vector(b)
    return [av[i] + bv[i] for i in range(5)]


def _vector_sub(a: Sequence[Any], b: Sequence[Any]) -> List[float]:
    av = clean_vector(a)
    bv = clean_vector(b)
    return [av[i] - bv[i] for i in range(5)]


def _clamp_hand(values: Sequence[Any]) -> Tuple[float, float, float, float, float]:
    """Clamp tiny floating negative values to zero but preserve real warnings elsewhere."""
    out = []
    for value in clean_vector(values):
        if -1e-7 < value < 0:
            out.append(0.0)
        else:
            out.append(float(value))
    return _tuple5(out)


def _player_by_id(game: Any, player_id: Any) -> Any:
    for player in getattr(game, "players", []) or []:
        try:
            if int(getattr(player, "id", -999999)) == int(player_id):
                return player
        except Exception:
            if getattr(player, "id", None) == player_id:
                return player
    return None


def _current_turn_player_id(game: Any) -> Optional[int]:
    """Return the player id whose turn it is, using common project fallbacks.

    Normal game.turn values in this project are 1-based player ids.  The
    fallback also accepts zero-based or one-based list positions if a saved
    state ever stores turn that way.
    """
    players = list(getattr(game, "players", []) or [])
    if not players:
        return None

    # Prefer explicit current_player-style attributes when present.
    for attr in ("current_player", "active_player", "player_at_turn"):
        candidate = getattr(game, attr, None)
        if candidate is not None and hasattr(candidate, "id"):
            try:
                return int(getattr(candidate, "id"))
            except Exception:
                pass

    turn_value = getattr(game, "turn", None)

    # Most common: turn directly equals player.id.
    for player in players:
        try:
            if int(getattr(player, "id", -999999)) == int(turn_value):
                return int(getattr(player, "id"))
        except Exception:
            pass

    # Fallback: one-based index.
    try:
        idx = int(turn_value) - 1
        if 0 <= idx < len(players):
            return int(getattr(players[idx], "id"))
    except Exception:
        pass

    # Fallback: zero-based index.
    try:
        idx = int(turn_value)
        if 0 <= idx < len(players):
            return int(getattr(players[idx], "id"))
    except Exception:
        pass

    # Last resort: first listed player.
    try:
        return int(getattr(players[0], "id"))
    except Exception:
        return None


def _stage3_target_player_ids(game: Any, scope: str) -> List[int]:
    """Return player ids to receive Stage-3 continuation rows."""
    normalized = str(scope or STAGE3_SCOPE_CURRENT_TURN_PLAYER).strip().lower()
    if normalized == STAGE3_SCOPE_ALL_PLAYERS:
        out = []
        for player in getattr(game, "players", []) or []:
            try:
                out.append(int(getattr(player, "id")))
            except Exception:
                pass
        return out

    current_id = _current_turn_player_id(game)
    return [current_id] if current_id is not None else []


def _port_at_intersection(board: Any, inter_id: Optional[int]) -> str:
    if inter_id is None:
        return ""
    try:
        inter = board.intersections[int(inter_id)]
    except Exception:
        return ""
    if inter is None:
        return ""
    if not (bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"):
        return ""
    return normalize_port_type(getattr(inter, "port_type", ""))


def _projected_ports_after_action(board: Any, action: Mapping[str, Any], current_ports: Sequence[str]) -> Tuple[str, ...]:
    ports: List[str] = []
    for port in current_ports or []:
        norm = normalize_port_type(str(port))
        if norm and norm not in ports:
            ports.append(norm)

    if action.get("action_type") in {"next_settlement", "new_settlement"}:
        target_id = _as_int_or_none(action.get("target_id"))
        port = _port_at_intersection(board, target_id)
        if port and port not in ports:
            ports.append(port)

    return tuple(ports)


def _payment_projection_for_action(action: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Choose the BASE payment model for Stage-2 projection.

    Important rule for Stage 3:
        Player-trade opportunities are reported, but they are NOT used for the
        base projected hand.  Therefore they do not improve continuation turns,
        total turns, continuation gain, or net gain.

    Priority:
        1. direct payment at action time
        2. bank/port strict discrete payment
        3. continuous-only payment, marked as unreliable
        4. not payable
    """
    cost = clean_vector(action.get("cost_vector", []))
    rates = clean_int_vector(action.get("trade_rates", []), default=4)
    expected_hand = clean_vector(action.get("expected_hand_at_action_time", []))
    diag = dict(action.get("trade_diagnostics", {}) or {})
    pdiag = dict(action.get("player_trade_diagnostics", {}) or {})

    warnings: List[str] = []
    if pdiag.get("anticipated_player_trades_possible"):
        warnings.append("player_trade_opportunities_not_used_in_base_projection")

    player_gives = [0.0] * 5
    player_receives = [0.0] * 5

    def finish(
        *,
        model: str,
        hand_before_bank: Sequence[Any],
        bank_plan: Mapping[str, Any],
        reliable: bool,
        valid: bool,
        extra_warnings: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        local_warnings = list(warnings)
        local_warnings.extend(str(x) for x in list(extra_warnings or []))
        hand = clean_vector(hand_before_bank)
        exports = clean_vector(bank_plan.get("exports_used", [0, 0, 0, 0, 0]))
        imports = clean_vector(bank_plan.get("imports_received", [0, 0, 0, 0, 0]))
        post = [hand[i] - exports[i] + imports[i] - cost[i] for i in range(5)]
        significant_negative = [DISPLAY_RESOURCE_NAMES[i] for i, value in enumerate(post) if value < -1e-6]
        if significant_negative:
            local_warnings.append("post_action_hand_negative:" + ",".join(significant_negative))
            valid = False
        return {
            "projection_valid": bool(valid),
            "projection_basis": "base_no_player_trades",
            "payment_model": model,
            "base_payment_model": model,
            "payment_reliable": bool(reliable),
            "player_trade_benefit_used_for_projection": False,
            "player_trade_projection_note": (
                "Player-trade opportunities are diagnostic/upside only; "
                "base continuation metrics use direct/bank/port trades only."
            ),
            "projection_warnings": tuple(local_warnings),
            "post_action_hand": _clamp_hand(post),
            "player_trade_gives": _tuple5(player_gives),
            "player_trade_receives": _tuple5(player_receives),
            "bank_exports_used": _tuple5(exports),
            "bank_imports_received": _tuple5(imports),
            "bank_trade_plan": tuple(bank_plan.get("labels", tuple())),
        }

    # Direct payment: no shortage before any trades.
    short_direct = [max(0.0, cost[i] - expected_hand[i]) for i in range(5)]
    if sum(short_direct) <= _EPS:
        return finish(
            model="base_direct_no_player_trades",
            hand_before_bank=expected_hand,
            bank_plan={
                "labels": tuple(),
                "exports_used": _tuple5([0, 0, 0, 0, 0]),
                "imports_received": _tuple5([0, 0, 0, 0, 0]),
            },
            reliable=True,
            valid=True,
        )

    # Bank-only strict/discrete payment.
    if diag.get("payable_discrete"):
        bank_plan = _anticipated_whole_bank_trade_plan_detailed(expected_hand, cost, rates)
        labels = tuple(bank_plan.get("labels", tuple()))
        return finish(
            model="base_bank_trade_discrete_no_player_trades" if labels else "base_direct_no_player_trades",
            hand_before_bank=expected_hand,
            bank_plan=bank_plan,
            reliable=True,
            valid=bool(bank_plan.get("possible", False)),
        )

    # Continuous-only projection: useful for transparency, not reliable for ranking.
    if diag.get("payable_continuous") or diag.get("continuous_only_trade_estimate"):
        continuous = compute_payability_with_trades(expected_hand, cost, rates, continuous=True)
        bank_plan = {
            "labels": tuple(),
            "exports_used": _tuple5(continuous.get("exports_used", [0, 0, 0, 0, 0])),
            "imports_received": _tuple5(continuous.get("imports_received", [0, 0, 0, 0, 0])),
        }
        return finish(
            model="base_continuous_only_no_player_trades",
            hand_before_bank=expected_hand,
            bank_plan=bank_plan,
            reliable=False,
            valid=bool(continuous.get("payable_after_trades", False)),
            extra_warnings=["continuous_only_projection_unreliable"],
        )

    return finish(
        model="base_not_payable_no_player_trades",
        hand_before_bank=expected_hand,
        bank_plan={
            "labels": tuple(),
            "exports_used": _tuple5([0, 0, 0, 0, 0]),
            "imports_received": _tuple5([0, 0, 0, 0, 0]),
        },
        reliable=False,
        valid=False,
        extra_warnings=["action_not_payable_at_reported_time"],
    )


def _project_action_for_player(game: Any, player: Any, action: Mapping[str, Any]) -> ProjectedActionResult:
    board = getattr(game, "board", None)
    action_type = str(action.get("action_type", ""))
    target_id = _as_int_or_none(action.get("target_id"))
    warnings: List[str] = []

    payment = _payment_projection_for_action(action)
    warnings.extend(payment.get("projection_warnings", tuple()))

    current_settlements = _safe_sorted_unique_ints(getattr(player, "settlements", []) or [])
    current_cities = _safe_sorted_unique_ints(getattr(player, "cities", []) or [])
    current_roads = list(_canonical_road_tuple_list(getattr(player, "roads", []) or []))
    current_ports_raw = action.get("ports", None)
    current_ports = tuple(
        str(x) for x in (current_ports_raw if current_ports_raw is not None else get_player_ports(board, player)) or []
    )

    current_pips_raw = action.get("production_pips", None)
    current_pips = clean_vector(
        current_pips_raw if current_pips_raw is not None else get_player_production_pips(board, player)
    )

    current_rates_raw = action.get("trade_rates", None)
    current_rates = clean_int_vector(
        current_rates_raw if current_rates_raw is not None else get_player_trade_rates(board, player),
        default=4,
    )

    settlements_after = list(current_settlements)
    cities_after = list(current_cities)
    roads_after = list(current_roads)
    production_gain = [0.0] * 5
    vp_delta = 0

    if target_id is None:
        warnings.append("missing_target_id")
    else:
        target_pips = clean_vector(get_intersection_resource_pips(board, int(target_id)))

        if action_type == "city_upgrade":
            if target_id not in settlements_after:
                warnings.append("city_upgrade_target_not_in_current_settlements")
            settlements_after = [sid for sid in settlements_after if sid != target_id]
            if target_id not in cities_after:
                cities_after.append(target_id)
            production_gain = target_pips  # city adds one extra copy of an existing settlement's pips.
            vp_delta = 1

        elif action_type in {"next_settlement", "new_settlement"}:
            if target_id in settlements_after or target_id in cities_after:
                warnings.append("settlement_target_already_owned")
            if target_id not in settlements_after and target_id not in cities_after:
                settlements_after.append(target_id)
            production_gain = target_pips
            vp_delta = 1

            if action_type == "new_settlement":
                for road in _canonical_road_tuple_list(action.get("roads_to_build", []) or []):
                    if road not in roads_after:
                        roads_after.append(road)
                    else:
                        warnings.append(f"road_already_owned:{road}")
        else:
            warnings.append(f"unknown_action_type:{action_type}")

    settlements_after = sorted(set(int(x) for x in settlements_after))
    cities_after = sorted(set(int(x) for x in cities_after))
    roads_after = sorted(set(roads_after))
    pips_after = _vector_add(current_pips, production_gain)

    if action_type in {"next_settlement", "new_settlement"} and target_id is not None:
        rates_after = trade_rates_after_candidate(board, player, target_id, base_rates=current_rates)
    else:
        rates_after = current_rates

    ports_after = _projected_ports_after_action(board, action, current_ports)
    victory_points_after = _player_victory_points_from_game(game, getattr(player, "id", None)) + vp_delta

    return ProjectedActionResult(
        projection_valid=bool(payment.get("projection_valid")) and not any(w.startswith("unknown_action_type") for w in warnings),
        payment_model=str(payment.get("payment_model", "unknown")),
        payment_reliable=bool(payment.get("payment_reliable", False)),
        projection_basis=str(payment.get("projection_basis", "base_no_player_trades")),
        player_trade_benefit_used_for_projection=bool(payment.get("player_trade_benefit_used_for_projection", False)),
        player_trade_projection_note=str(payment.get("player_trade_projection_note", "")),
        projection_warnings=tuple(str(w) for w in warnings),
        post_action_hand=_tuple5(payment.get("post_action_hand", [0, 0, 0, 0, 0])),
        player_trade_gives=_tuple5(payment.get("player_trade_gives", [0, 0, 0, 0, 0])),
        player_trade_receives=_tuple5(payment.get("player_trade_receives", [0, 0, 0, 0, 0])),
        bank_exports_used=_tuple5(payment.get("bank_exports_used", [0, 0, 0, 0, 0])),
        bank_imports_received=_tuple5(payment.get("bank_imports_received", [0, 0, 0, 0, 0])),
        bank_trade_plan=tuple(str(x) for x in payment.get("bank_trade_plan", tuple())),
        production_gain=_tuple5(production_gain),
        production_pips_after_action=_tuple5(pips_after),
        trade_rates_after_action=_int_tuple5(rates_after),
        ports_after_action=tuple(str(x) for x in ports_after),
        settlements_after_action=tuple(int(x) for x in settlements_after),
        cities_after_action=tuple(int(x) for x in cities_after),
        roads_after_action=tuple(roads_after),
        roads_count_after_action=len(roads_after),
        victory_points_after_action=int(victory_points_after),
    )


def apply_action_projection_layer(
    report: Dict[str, Any],
    game: Any,
    *,
    enabled: bool = DEFAULT_ENABLE_ACTION_PROJECTIONS,
) -> Dict[str, Any]:
    """Attach Stage-2 after-action projections to every action row in-place."""
    settings = dict(report.get("settings", {}) or {})
    settings["action_projections_enabled"] = bool(enabled)
    settings["projection_model"] = "acting_player_only_after_action_state_base_no_player_trades"
    settings["projection_basis"] = "base_no_player_trades"
    settings["player_trade_benefit_used_for_projection"] = False
    settings["projection_payment_priority"] = [
        "base_direct_no_player_trades",
        "base_bank_trade_discrete_no_player_trades",
        "base_continuous_only_no_player_trades",
        "base_not_payable_no_player_trades",
    ]
    report["settings"] = settings

    if not enabled:
        return report

    for player_block in (report.get("by_player", {}) or {}).values():
        player_info = player_block.get("player", {}) or {}
        player = _player_by_id(game, player_info.get("player_id"))
        if player is None:
            continue
        for key in ("best_actions", "all_candidate_actions"):
            for action in list(player_block.get(key, []) or []):
                if isinstance(action, dict):
                    projection = _project_action_for_player(game, player, action)
                    action["projection"] = projection.as_dict()

    return report



# ──────────────────────────────────────────────────────────────────────────────
# Stage-3A continuation strategy layer
# ──────────────────────────────────────────────────────────────────────────────

def _strategy_state_from_projection(
    player_info: Mapping[str, Any],
    action: Mapping[str, Any],
    projection: Mapping[str, Any],
    *,
    fallback_state: Any = None,
) -> Any:
    """Build a PlayerStrategyState-like object from a Stage-2 projection."""
    if not _STRATEGY_TIMING_AVAILABLE or PlayerStrategyState is None:
        return None

    fallback_hand = []
    fallback_pips = []
    fallback_rates = []
    fallback_ports: Sequence[Any] = []
    fallback_settlements: Sequence[Any] = []
    fallback_cities: Sequence[Any] = []
    fallback_roads_count = 0
    fallback_dev_progress = 0

    if fallback_state is not None:
        fallback_hand = list(getattr(fallback_state, "current_hand", []) or [])
        fallback_pips = list(getattr(fallback_state, "production_pips", []) or [])
        fallback_rates = list(getattr(fallback_state, "trade_rates", []) or [])
        fallback_ports = list(getattr(fallback_state, "ports", []) or [])
        fallback_settlements = list(getattr(fallback_state, "settlements", []) or [])
        fallback_cities = list(getattr(fallback_state, "cities", []) or [])
        fallback_roads_count = safe_int(getattr(fallback_state, "roads_count", 0), 0)
        fallback_dev_progress = safe_int(getattr(fallback_state, "dev_card_progress", 0), 0)

    current_hand = _tuple5(projection.get("post_action_hand", fallback_hand))
    production_pips = _tuple5(projection.get("production_pips_after_action", fallback_pips))
    trade_rates = tuple(clean_int_vector(projection.get("trade_rates_after_action", fallback_rates), default=4))
    ports = tuple(str(x) for x in list(projection.get("ports_after_action", fallback_ports) or []))
    settlements = tuple(_safe_sorted_unique_ints(projection.get("settlements_after_action", fallback_settlements) or []))
    cities = tuple(_safe_sorted_unique_ints(projection.get("cities_after_action", fallback_cities) or []))
    roads_count = safe_int(projection.get("roads_count_after_action", fallback_roads_count), fallback_roads_count)

    return PlayerStrategyState(  # type: ignore[operator]
        player_id=safe_int(player_info.get("player_id", 0), 0),
        color=str(player_info.get("color", "")),
        current_hand=current_hand,
        production_pips=production_pips,
        trade_rates=trade_rates,  # type: ignore[arg-type]
        ports=ports,
        settlements=settlements,
        cities=cities,
        roads_count=roads_count,
        dev_card_progress=fallback_dev_progress,
    )


def _current_strategy_state_for_player(game: Any, player: Any) -> Any:
    if not _STRATEGY_TIMING_AVAILABLE or build_player_strategy_state is None:
        return None
    try:
        return build_player_strategy_state(getattr(game, "board", None), player)
    except Exception:
        return None


def _all_strategy_states_with_projection(game: Any, player_id: int, projected_state: Any) -> List[Any]:
    """Return table states, replacing the acting player with the projected state."""
    states: List[Any] = []
    for other in getattr(game, "players", []) or []:
        try:
            other_id = int(getattr(other, "id", -999999))
        except Exception:
            other_id = -999999
        if other_id == int(player_id):
            states.append(projected_state)
            continue
        state = _current_strategy_state_for_player(game, other)
        if state is not None:
            states.append(state)
    if not states:
        states = [projected_state]
    elif all(s is not projected_state for s in states):
        states.append(projected_state)
    return states


def _strategy_row_brief(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact continuation-strategy representation for action planning."""
    return {
        "rank": row.get("rank"),
        "way_id": row.get("way_id"),
        "turns": row.get("turns"),
        "found": row.get("found"),
        "confidence": row.get("confidence"),
        "confidence_label": row.get("confidence_label"),
        "need_vector": row.get("need_vector", []),
        "need_compact": row.get("need_compact", ""),
        "tags": list(row.get("tags", []) or []),
        "reason": row.get("reason", ""),
        "trade_dependency": list(row.get("trade_dependency", []) or []),
        "trade_diagnostics": dict(row.get("trade_diagnostics", {}) or {}),
        "remaining": dict(row.get("remaining", {}) or {}),
        "strategy_summary": dict(row.get("strategy_summary", {}) or {}),
    }


def _rank_strategy_state_top_n(
    state: Any,
    all_states: Sequence[Any],
    *,
    top_n: int,
    include_debug: bool,
    num_players: int,
    requirements: Optional[Sequence[Any]] = None,
    game: Any = None,
) -> Dict[str, Any]:
    """Rank strategies for a PlayerStrategyState, returning an empty report if unavailable."""
    if not _STRATEGY_TIMING_AVAILABLE or rank_strategies_for_player_state is None or state is None:
        return {
            "top_strategies": [],
            "settings": {"strategy_timing_available": False},
        }

    prefilter_k = None
    always_ids: list = []
    try:
        from core.l2_profile import profile_from_game

        prof = profile_from_game(game)
        if prof is not None and str(getattr(prof, "name", "") or "") == "fast":
            prefilter_k = getattr(prof, "abstract_prefilter_k", None)
    except Exception:
        pass
    # Force sticky/preferred into prefilter set when player available on state
    try:
        pid = getattr(state, "player_id", None) or getattr(state, "id", None)
        if game is not None and pid is not None:
            for p in list(getattr(game, "players", None) or []):
                if str(getattr(p, "id", "")) == str(pid) or getattr(p, "id", None) == pid:
                    for src in (
                        getattr(p, "sticky_commitment", None),
                        getattr(p, "strategic_direction", None),
                    ):
                        if isinstance(src, dict):
                            for key in ("locked_way_id", "preferred_way_id", "way_id"):
                                try:
                                    wid = int(src.get(key) or 0)
                                    if wid > 0:
                                        always_ids.append(wid)
                                except Exception:
                                    pass
                    break
    except Exception:
        pass

    kwargs: Dict[str, Any] = {
        "requirements": requirements,
        "top_n": top_n,
        "include_all": False,
        "include_debug": include_debug,
        "num_players": num_players,
        "all_player_states": all_states,
    }
    if prefilter_k is not None:
        kwargs["prefilter_k"] = prefilter_k
        kwargs["always_include_way_ids"] = always_ids

    try:
        return rank_strategies_for_player_state(state, **kwargs)  # type: ignore[misc]
    except TypeError:
        # Older signature without P4 kwargs
        kwargs.pop("prefilter_k", None)
        kwargs.pop("always_include_way_ids", None)
        return rank_strategies_for_player_state(state, **kwargs)  # type: ignore[misc]


def apply_strategy_continuation_layer(
    report: Dict[str, Any],
    game: Any,
    *,
    enabled: bool = DEFAULT_ENABLE_CONTINUATION_STRATEGIES,
    top_n: int = DEFAULT_CONTINUATION_TOP_N,
    include_debug: bool = False,
    player_scope: str = DEFAULT_STAGE3_PLAYER_SCOPE,
) -> Dict[str, Any]:
    """Attach Stage-3A top-N continuation strategies to every projected action."""
    settings = dict(report.get("settings", {}) or {})
    settings["continuation_strategies_enabled"] = bool(enabled)
    settings["continuation_top_n"] = int(top_n)
    settings["continuation_model"] = "projected_player_state_after_action_base_no_player_trades"
    settings["continuation_score_formula"] = "action_expected_own_turns + continuation_expected_own_turns_after_action"
    settings["continuation_uses_player_trade_benefit"] = False
    settings["stage3_player_scope"] = str(player_scope or DEFAULT_STAGE3_PLAYER_SCOPE)
    target_player_ids = _stage3_target_player_ids(game, settings["stage3_player_scope"])
    settings["stage3_target_player_ids"] = target_player_ids
    settings["acting_player_id"] = target_player_ids[0] if target_player_ids else None
    settings["strategy_timing_available"] = bool(_STRATEGY_TIMING_AVAILABLE)
    report["settings"] = settings

    if not enabled:
        return report

    if not _STRATEGY_TIMING_AVAILABLE:
        report.setdefault("warnings", []).append(
            "strategy_timing module is unavailable; continuation strategies were not calculated"
        )
        return report

    num_players = max(1, safe_int(settings.get("num_players", _get_num_players(game)), _get_num_players(game)))

    requirements_cache = None
    try:
        if load_strategy_requirements is not None:  # type: ignore[name-defined]
            requirements_cache = load_strategy_requirements()  # type: ignore[misc]
    except Exception as exc:
        report.setdefault("warnings", []).append(f"could_not_load_strategy_requirements_for_continuations: {exc}")
        requirements_cache = None

    target_set = set(int(x) for x in target_player_ids if x is not None)

    for player_block in (report.get("by_player", {}) or {}).values():
        player_info = player_block.get("player", {}) or {}
        player_id = safe_int(player_info.get("player_id", 0), 0)

        if target_set and int(player_id) not in target_set:
            player_block["continuation_scope_excluded"] = True
            player_block["continuation_scope_reason"] = "Stage 3 continuation planning is limited to the current-turn player."
            for key in ("best_actions", "all_candidate_actions"):
                for action in list(player_block.get(key, []) or []):
                    if isinstance(action, dict):
                        action["continuation_top_strategies"] = []
                        action["continuation_warning"] = "stage3_current_turn_player_only"
            continue

        player = _player_by_id(game, player_id)
        if player is None:
            continue

        current_state = _current_strategy_state_for_player(game, player)
        if current_state is None:
            continue

        current_all_states = []
        for other in getattr(game, "players", []) or []:
            s = _current_strategy_state_for_player(game, other)
            if s is not None:
                current_all_states.append(s)
        if not current_all_states:
            current_all_states = [current_state]

        baseline_report = _rank_strategy_state_top_n(
            current_state,
            current_all_states,
            top_n=max(1, int(top_n)),
            include_debug=include_debug,
            num_players=num_players,
            requirements=requirements_cache,
            game=game,
        )
        baseline_top = list(baseline_report.get("top_strategies", []) or [])
        baseline_best = baseline_top[0] if baseline_top else None
        baseline_best_way_id = baseline_best.get("way_id") if isinstance(baseline_best, Mapping) else None
        baseline_best_turns = finite_or_9999(
            baseline_best.get("turns", INFINITE_TURNS) if isinstance(baseline_best, Mapping) else INFINITE_TURNS
        )

        player_block["baseline_top_strategies"] = [
            _strategy_row_brief(row) for row in baseline_top[: max(0, int(top_n))]
        ]
        player_block["baseline_best_strategy"] = (
            _strategy_row_brief(baseline_best) if isinstance(baseline_best, Mapping) else None
        )

        for key in ("best_actions", "all_candidate_actions"):
            for action in list(player_block.get(key, []) or []):
                if not isinstance(action, dict):
                    continue
                projection = action.get("projection", {}) or {}
                if not projection:
                    action["continuation_top_strategies"] = []
                    action["continuation_warning"] = "missing_stage2_projection"
                    continue
                if not projection.get("projection_valid", False):
                    action["continuation_top_strategies"] = []
                    action["continuation_warning"] = "invalid_projection"
                    continue

                projected_state = _strategy_state_from_projection(
                    player_info,
                    action,
                    projection,
                    fallback_state=current_state,
                )
                if projected_state is None:
                    action["continuation_top_strategies"] = []
                    action["continuation_warning"] = "could_not_build_projected_strategy_state"
                    continue

                all_states = _all_strategy_states_with_projection(game, player_id, projected_state)
                continuation_report = _rank_strategy_state_top_n(
                    projected_state,
                    all_states,
                    top_n=max(1, int(top_n)),
                    include_debug=include_debug,
                    num_players=num_players,
                    requirements=requirements_cache,
                    game=game,
                )
                cont_rows = list(continuation_report.get("top_strategies", []) or [])[: max(0, int(top_n))]
                action_turns = finite_or_9999(action.get("action_expected_own_turns", INFINITE_TURNS))

                continuation_rows: List[Dict[str, Any]] = []
                for cont_idx, row in enumerate(cont_rows, start=1):
                    if not isinstance(row, Mapping):
                        continue
                    cont_turns = finite_or_9999(row.get("turns", INFINITE_TURNS))
                    total_turns = finite_or_9999(action_turns + cont_turns)
                    continuation_turn_gain = finite_or_9999(baseline_best_turns - cont_turns)
                    net_total_turn_gain = finite_or_9999(baseline_best_turns - total_turns)
                    way_id = row.get("way_id")
                    strategy_changed = (
                        baseline_best_way_id is not None and way_id is not None and str(way_id) != str(baseline_best_way_id)
                    )
                    brief = _strategy_row_brief(row)
                    brief.update(
                        {
                            "continuation_rank": cont_idx,
                            "continuation_way_id": way_id,
                            "continuation_expected_own_turns_after_action": cont_turns,
                            "action_expected_own_turns": action_turns,
                            "total_expected_own_turns": total_turns,
                            "baseline_best_way_id": baseline_best_way_id,
                            "baseline_best_expected_own_turns": baseline_best_turns,
                            "continuation_turn_gain": continuation_turn_gain,
                            "net_total_turn_gain": net_total_turn_gain,
                            "strategy_changed": bool(strategy_changed),
                        }
                    )
                    continuation_rows.append(brief)

                action["continuation_top_strategies"] = continuation_rows
                if continuation_rows:
                    action["best_continuation_strategy"] = continuation_rows[0]
                else:
                    action["continuation_warning"] = "no_continuation_strategy_found"

    return report


# ──────────────────────────────────────────────────────────────────────────────
# Stage-4E preferred way_id / player strategic direction
# ──────────────────────────────────────────────────────────────────────────────

def _strategy_pref_risk_rank(level: Any) -> int:
    text = str(level or "Low")
    if text == "High":
        return 2
    if text == "Medium":
        return 1
    return 0


def _strategy_pref_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def _strategy_pref_int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _strategy_candidate_from_continuation(
    *,
    action: Mapping[str, Any],
    continuation: Mapping[str, Any],
    action_rank: int,
    min_positive_gain: float = DEFAULT_STRATEGY_PREFERENCE_MIN_GAIN,
) -> Optional[Dict[str, Any]]:
    """
    Convert one action + one continuation row into a preferred-strategy candidate.

    This candidate is supporting evidence for a way_id, not a command to execute
    the supporting action.  Payment-unreliable rows may still be useful for
    strategic direction, but they should remain blocked from exact execution
    until the normal legal/payment guard says they are executable.
    """
    way_id = _strategy_pref_int_or_none(
        continuation.get("continuation_way_id", continuation.get("way_id"))
    )
    if way_id is None:
        return None

    projection = action.get("projection", {}) or {}
    risk = action.get("risk_assessment", {}) or {}

    projection_valid = _strategy_pref_bool(
        projection.get("projection_valid", action.get("found", False))
    )
    payment_reliable = _strategy_pref_bool(projection.get("payment_reliable", False))

    action_turns = finite_or_9999(
        continuation.get(
            "action_expected_own_turns",
            action.get("action_expected_own_turns", INFINITE_TURNS),
        )
    )
    continuation_turns = finite_or_9999(
        continuation.get(
            "continuation_expected_own_turns_after_action",
            continuation.get("turns", INFINITE_TURNS),
        )
    )

    total_turns = finite_or_9999(
        continuation.get("total_expected_own_turns", action_turns + continuation_turns)
    )
    net_gain = safe_float(continuation.get("net_total_turn_gain"), -INFINITE_TURNS)

    risk_level = str(
        risk.get(
            "action_risk_level",
            risk.get("risk_level", action.get("risk_level", "Low")),
        )
        or "Low"
    )
    risk_penalty = safe_float(risk.get("action_risk_penalty_turns"), 0.0)

    if total_turns < INFINITE_TURNS:
        risk_adjusted_total = total_turns + risk_penalty
    else:
        risk_adjusted_total = INFINITE_TURNS

    if net_gain > -INFINITE_TURNS / 2:
        risk_adjusted_gain = net_gain - risk_penalty
    else:
        risk_adjusted_gain = -INFINITE_TURNS

    confidence = safe_float(
        continuation.get("confidence", action.get("confidence", 0.0)),
        0.0,
    )

    if not projection_valid:
        preference_level = "Not usable"
        preference_reason = "Projection is invalid."
    elif risk_adjusted_gain < min_positive_gain:
        preference_level = "Watch only"
        preference_reason = "No clear positive risk-adjusted strategy gain."
    elif not payment_reliable:
        preference_level = "Preferred strategy - payment caution"
        preference_reason = (
            "Good strategic gain, but supporting projection uses an unreliable "
            "payment model such as continuous-only trading."
        )
    elif _strategy_pref_risk_rank(risk_level) >= 2:
        preference_level = "Preferred strategy - contested"
        preference_reason = "Good strategic gain, but target/path risk is High."
    elif risk_adjusted_gain >= DEFAULT_STRATEGY_PREFERENCE_STRONG_GAIN:
        preference_level = "Preferred strategy"
        preference_reason = "Good risk-adjusted strategy gain."
    else:
        preference_level = "Candidate strategy"
        preference_reason = "Positive but modest risk-adjusted strategy gain."

    return {
        "way_id": way_id,
        "preferred_way_id": way_id,
        "preference_level": preference_level,
        "preference_reason": preference_reason,

        # Supporting evidence only; not an action command.
        "supporting_action_id": action.get("action_id", ""),
        "supporting_action_rank": action_rank,
        "supporting_action_type": action.get("action_type", ""),
        "supporting_action_target_id": action.get("target_id"),
        "supporting_action_description": action.get("description", ""),

        "continuation_rank": continuation.get(
            "continuation_rank", continuation.get("rank", "")
        ),
        "continuation_expected_own_turns_after_action": continuation_turns,
        "action_expected_own_turns": action_turns,
        "total_expected_own_turns": total_turns,
        "risk_adjusted_total_expected_own_turns": risk_adjusted_total,
        "net_total_turn_gain": net_gain,
        "risk_adjusted_net_total_turn_gain": risk_adjusted_gain,

        "baseline_best_way_id": continuation.get("baseline_best_way_id", ""),
        "baseline_best_expected_own_turns": continuation.get(
            "baseline_best_expected_own_turns", ""
        ),
        "strategy_changed": bool(continuation.get("strategy_changed", False)),

        "risk_level": risk_level,
        "risk_penalty_turns": risk_penalty,
        "action_decision_level": risk.get("action_decision_level", ""),
        "action_decision_reason": risk.get("action_decision_reason", ""),

        "projection_valid": projection_valid,
        "payment_reliable": payment_reliable,
        "payment_model": projection.get("payment_model", ""),
        "projection_warnings": list(projection.get("projection_warnings", []) or []),

        "confidence": confidence,
        "confidence_label": continuation.get(
            "confidence_label", action.get("confidence_label", "")
        ),
        "need_vector": list(continuation.get("need_vector", []) or []),
        "need_compact": continuation.get("need_compact", ""),
        "tags": list(continuation.get("tags", []) or []),
        "reason": continuation.get("reason", ""),
        "trade_dependency": list(continuation.get("trade_dependency", []) or []),
    }


def _strategy_candidate_sort_key(candidate: Mapping[str, Any]) -> Tuple[Any, ...]:
    """Lower is better for strategy preference candidates."""
    risk_adjusted_total = finite_or_9999(
        candidate.get("risk_adjusted_total_expected_own_turns", INFINITE_TURNS)
    )
    risk_adjusted_gain = safe_float(
        candidate.get("risk_adjusted_net_total_turn_gain"), -INFINITE_TURNS
    )

    return (
        0 if _strategy_pref_bool(candidate.get("projection_valid", False)) else 1,
        risk_adjusted_total,
        _strategy_pref_risk_rank(candidate.get("risk_level", "Low")),
        0 if _strategy_pref_bool(candidate.get("payment_reliable", False)) else 1,
        -risk_adjusted_gain,
        safe_int(candidate.get("continuation_rank", 999), 999),
        safe_int(candidate.get("supporting_action_rank", 999), 999),
        safe_int(candidate.get("way_id", 999999), 999999),
    )


def select_preferred_strategy_for_player_block(
    player_block: Mapping[str, Any],
    *,
    min_positive_gain: float = DEFAULT_STRATEGY_PREFERENCE_MIN_GAIN,
    use_all_candidate_actions: bool = False,
) -> Dict[str, Any]:
    """
    Pick a preferred way_id for one player block.

    This does not pick a final action.  It chooses a strategic direction from
    the continuation rows already created by Stage 3 and annotated by Stage 4.
    """
    action_key = "all_candidate_actions" if use_all_candidate_actions else "best_actions"
    actions = list(player_block.get(action_key, []) or [])

    all_candidates: List[Dict[str, Any]] = []
    for action_rank, action in enumerate(actions, start=1):
        if not isinstance(action, Mapping):
            continue

        for continuation in list(action.get("continuation_top_strategies", []) or []):
            if not isinstance(continuation, Mapping):
                continue

            candidate = _strategy_candidate_from_continuation(
                action=action,
                continuation=continuation,
                action_rank=action_rank,
                min_positive_gain=min_positive_gain,
            )
            if candidate is not None:
                all_candidates.append(candidate)

    if not all_candidates:
        return {
            "preferred_way_id": None,
            "preference_level": "No strategy candidate",
            "preference_reason": "No continuation strategy rows were available.",
            "candidates": [],
        }

    # Keep only the best supporting row per way_id.
    best_by_way: Dict[int, Dict[str, Any]] = {}
    for candidate in all_candidates:
        way_id = safe_int(candidate.get("way_id"), -1)
        if way_id < 0:
            continue

        previous = best_by_way.get(way_id)
        if previous is None or _strategy_candidate_sort_key(candidate) < _strategy_candidate_sort_key(previous):
            best_by_way[way_id] = candidate

    way_candidates = sorted(best_by_way.values(), key=_strategy_candidate_sort_key)

    positive_candidates = [
        candidate
        for candidate in way_candidates
        if safe_float(candidate.get("risk_adjusted_net_total_turn_gain"), -INFINITE_TURNS) >= min_positive_gain
        and _strategy_pref_bool(candidate.get("projection_valid", False))
    ]
    selected_pool = positive_candidates if positive_candidates else way_candidates
    preferred = selected_pool[0]

    ranked_candidates: List[Dict[str, Any]] = []
    for idx, candidate in enumerate(way_candidates, start=1):
        row = dict(candidate)
        row["strategy_preference_rank"] = idx
        row["is_preferred_way"] = (
            safe_int(row.get("way_id"), -1) == safe_int(preferred.get("way_id"), -2)
        )
        ranked_candidates.append(row)

    preferred_out = dict(preferred)
    preferred_out["preferred_way_id"] = preferred_out.get("way_id")
    preferred_out["strategy_preference_rank"] = 1
    preferred_out["candidates"] = ranked_candidates
    return preferred_out


def _persist_preferred_strategy_to_player(
    player: Any,
    preferred_strategy: Mapping[str, Any],
) -> None:
    """Persist preferred_strategy on Player without requiring a hard dependency."""
    preferred_dict = dict(preferred_strategy or {})
    try:
        setter = getattr(player, "set_strategic_direction", None)
        if callable(setter):
            setter(preferred_dict)
            return
    except Exception:
        pass

    try:
        previous = getattr(player, "strategic_direction", None)
        setattr(player, "last_strategic_direction", previous)
        setattr(player, "strategic_direction", preferred_dict)
        history = list(getattr(player, "strategic_direction_history", []) or [])
        history.append(preferred_dict)
        setattr(player, "strategic_direction_history", history[-20:])
    except Exception:
        pass


def apply_strategy_preference_layer(
    report: Dict[str, Any],
    game: Any,
    *,
    enabled: bool = DEFAULT_ENABLE_STRATEGY_PREFERENCE,
    min_positive_gain: float = DEFAULT_STRATEGY_PREFERENCE_MIN_GAIN,
    use_all_candidate_actions: bool = False,
    persist_to_player: bool = DEFAULT_PERSIST_STRATEGY_PREFERENCE_TO_PLAYER,
) -> Dict[str, Any]:
    """
    Stage 4E: attach and optionally persist a player-level preferred way_id.

    Important distinction:
        action_decision_level answers: "Should I execute this concrete action now?"
        preferred_strategy answers: "Which way_id should this player pursue?"
    """
    settings = dict(report.get("settings", {}) or {})
    settings["strategy_preference_enabled"] = bool(enabled)
    settings["strategy_preference_stage"] = "4E_preferred_way_id"
    settings["strategy_preference_min_positive_gain"] = float(min_positive_gain)
    settings["strategy_preference_uses_all_candidate_actions"] = bool(use_all_candidate_actions)
    settings["strategy_preference_persisted_to_player"] = bool(persist_to_player and enabled)
    settings["strategy_preference_rule"] = (
        "Pick a preferred way_id from continuation rows using risk-adjusted total turns "
        "and risk-adjusted net gain. Payment-unreliable rows may still define a provisional "
        "strategic direction, but should not trigger automatic action execution."
    )
    report["settings"] = settings

    if not enabled:
        return report

    for player_block in (report.get("by_player", {}) or {}).values():
        if not isinstance(player_block, dict):
            continue

        preferred = select_preferred_strategy_for_player_block(
            player_block,
            min_positive_gain=min_positive_gain,
            use_all_candidate_actions=use_all_candidate_actions,
        )

        preferred_without_candidates = {
            key: value for key, value in preferred.items() if key != "candidates"
        }
        player_block["preferred_strategy"] = preferred_without_candidates
        player_block["strategy_preference_candidates"] = preferred.get("candidates", [])

        if persist_to_player:
            player_info = player_block.get("player", {}) or {}
            player_id = safe_int(player_info.get("player_id", 0), 0)
            player = _player_by_id(game, player_id)
            if player is not None:
                _persist_preferred_strategy_to_player(player, preferred_without_candidates)

    return report


def build_action_timing_report(
    game: Any,
    *,
    top_n_actions: Optional[int] = DEFAULT_ACTION_TOP_N,
    include_all: bool = True,
    include_debug: bool = False,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = DEFAULT_PRIMARY_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
    enable_player_trades: bool = DEFAULT_ENABLE_PLAYER_TRADES,
    max_player_trades_per_pair: int = DEFAULT_MAX_PLAYER_TRADES_PER_PAIR,
    enable_action_projections: bool = DEFAULT_ENABLE_ACTION_PROJECTIONS,
    enable_continuation_strategies: bool = DEFAULT_ENABLE_CONTINUATION_STRATEGIES,
    continuation_top_n: int = DEFAULT_CONTINUATION_TOP_N,
    stage3_player_scope: str = DEFAULT_STAGE3_PLAYER_SCOPE,
    enable_risk_assessment: bool = DEFAULT_ENABLE_RISK_ASSESSMENT,
    stage4_risk_player_scope: str = DEFAULT_STAGE4_RISK_PLAYER_SCOPE,
    enable_strategy_preference: bool = DEFAULT_ENABLE_STRATEGY_PREFERENCE,
    strategy_preference_min_positive_gain: float = DEFAULT_STRATEGY_PREFERENCE_MIN_GAIN,
    strategy_preference_use_all_candidate_actions: bool = False,
    persist_strategy_preference_to_player: bool = DEFAULT_PERSIST_STRATEGY_PREFERENCE_TO_PLAYER,
) -> Dict[str, Any]:
    """Build an action timing/projection report.

    Stage 1/2 diagnostics may exist for all players because player-trade
    opportunity detection benefits from table context.  Stage 3 continuation
    strategy rows are limited to the current-turn player by default.
    """
    report = {
        "round": getattr(game, "round", None),
        "turn": getattr(game, "turn", None),
        "phase": getattr(game, "phase", None),
        "state": getattr(game, "state", None),
        "stage": 4,
        "purpose": "build_action_timing_projection_continuation_and_risk_adjusted_decision_support",
        "resource_order": list(DISPLAY_RESOURCE_NAMES),
        "settings": {
            "top_n_actions": top_n_actions,
            "include_all": include_all,
            "include_debug": include_debug,
            "confidence_target": confidence_target,
            "num_players": _get_num_players(game),
            "step": step,
            "max_turns": max_turns,
            "continuous_trading": continuous_trading,
            "require_confidence": require_confidence,
            "risk_score_is_placeholder": not enable_risk_assessment,
            "risk_assessment_enabled": enable_risk_assessment,
            "risk_assessment_stage": "4D_combined_action_risk_and_decision_support",
            "risk_assessment_player_scope": stage4_risk_player_scope,
            "risk_assessment_available": bool(_RISK_ASSESSMENT_AVAILABLE),
            "player_trades_enabled": enable_player_trades,
            "player_trade_model": "mutually_useful_1_to_1_conservative",
            "max_player_trades_per_pair": max_player_trades_per_pair,
            "action_projections_enabled": enable_action_projections,
            "continuation_strategies_enabled": enable_continuation_strategies,
            "continuation_top_n": continuation_top_n,
            "stage3_player_scope": stage3_player_scope,
            "stage3_target_player_ids": _stage3_target_player_ids(game, stage3_player_scope),
            "continuation_uses_player_trade_benefit": False,
            "strategy_preference_enabled": enable_strategy_preference,
            "strategy_preference_stage": "4E_preferred_way_id",
            "strategy_preference_min_positive_gain": strategy_preference_min_positive_gain,
            "strategy_preference_uses_all_candidate_actions": strategy_preference_use_all_candidate_actions,
            "strategy_preference_persisted_to_player": bool(
                enable_strategy_preference and persist_strategy_preference_to_player
            ),
        },
        "by_player": {},
    }

    for player in getattr(game, "players", []) or []:
        player_id = str(getattr(player, "id", len(report["by_player"]) + 1))
        report["by_player"][player_id] = build_action_timings_for_player(
            game,
            player,
            top_n_actions=top_n_actions,
            include_all=include_all,
            include_debug=include_debug,
            confidence_target=confidence_target,
            step=step,
            max_turns=max_turns,
            continuous_trading=continuous_trading,
            require_confidence=require_confidence,
        )

    apply_player_trade_layer(
        report,
        game,
        enabled=enable_player_trades,
        max_trades_per_pair=max_player_trades_per_pair,
    )

    apply_action_projection_layer(
        report,
        game,
        enabled=enable_action_projections,
    )

    apply_strategy_continuation_layer(
        report,
        game,
        enabled=enable_continuation_strategies,
        top_n=continuation_top_n,
        include_debug=include_debug,
        player_scope=stage3_player_scope,
    )

    apply_risk_assessment_layer(
        report,
        game,
        enabled=enable_risk_assessment,
        player_scope=stage4_risk_player_scope,
    )

    apply_strategy_preference_layer(
        report,
        game,
        enabled=enable_strategy_preference,
        min_positive_gain=strategy_preference_min_positive_gain,
        use_all_candidate_actions=strategy_preference_use_all_candidate_actions,
        persist_to_player=persist_strategy_preference_to_player,
    )

    # === Phase 4G-B / P3-C: Board way portfolio (full explore vs L0 hand_only) ===
    try:
        from core.ai_way_portfolio import apply_board_way_portfolio_layer

        refresh_mode = str(getattr(game, "_strategy_refresh_mode", "") or "explore").lower()
        hand_only = refresh_mode in ("hand_only", "l0", "hand")
        # Full L2: behavior_override ranks may replace preferred way.
        # L0: rescore sticky/preferred only; never switch way here.
        apply_board_way_portfolio_layer(
            report,
            game,
            enabled=True,
            behavior_override=not hand_only,
            hand_only=hand_only,
        )
        try:
            report.setdefault("settings", {})
            if isinstance(report.get("settings"), dict):
                report["settings"]["strategy_refresh_mode"] = refresh_mode
        except Exception:
            pass
    except Exception as e:
        report["board_way_audits"] = []
        report["board_way_audit_error"] = str(e)

    return report

# ──────────────────────────────────────────────────────────────────────────────
# Formatting and persistence
# ──────────────────────────────────────────────────────────────────────────────

def save_action_timing_report_json(report: Mapping[str, Any], path: Path | str) -> Path:
    """Save a Stage-1 action timing report as JSON."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return out_path


def write_action_timing_report_csv(
    report: Mapping[str, Any],
    path: Path | str,
    *,
    use_all_candidate_actions: bool = False,
    delimiter: str = ";",
    decimal_separator: str = ",",
    float_digits: int = 6,
    excel_sep_hint: bool = True,
) -> Path:
    """
    Save a flat action-planning CSV.

    Default delimiter is semicolon (;) and default decimal separator is comma (,)
    so the file opens correctly in Excel with Dutch/European regional settings.

    Important:
        Scalar numeric fields are written using the configured decimal separator
        so Excel recognizes them as numbers. JSON/list fields remain text.

    Stage 3A expands the CSV to one row per:

        player × build action × continuation_strategy_rank

    Therefore each action normally produces three CSV rows when
    continuation_top_n=3.  This keeps Excel sorting/filtering simple.
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "report_round",
        "report_turn",
        "stage",
        "player_id",
        "color",
        "action_rank",
        "action_type",
        "target_id",
        "description",
        "road_count",
        "roads_to_build",
        "cost_vector",
        "cost_compact",
        "action_expected_own_turns",
        "action_expected_global_turns",
        "action_strict_expected_own_turns",
        "action_strict_expected_global_turns",
        "found",
        "strict_found",
        "confidence",
        "confidence_label",
        "risk_score",
        "risk_level",
        "risk_reason",
        "action_risk_level",
        "action_risk_score",
        "action_risk_source",
        "action_risk_penalty_turns",
        "risk_adjusted_total_expected_own_turns",
        "risk_adjusted_net_total_turn_gain",
        "tactical_urgency_level",
        "tactical_urgency_score",
        "action_decision_level",
        "action_decision_reason",
        "preferred_way_id",
        "preferred_way_level",
        "preferred_way_reason",
        "preferred_way_is_this_row",
        "preferred_way_supporting_action_id",
        "preferred_way_supporting_action_type",
        "preferred_way_supporting_action_target_id",
        "preferred_way_risk_adjusted_total",
        "preferred_way_risk_adjusted_gain",
        "target_contested",
        "target_race_relation",
        "target_race_margin",
        "target_race_significance_margin",
        "target_best_opponent_id",
        "target_best_opponent_color",
        "target_best_opponent_turns",
        "target_my_turns",
        "opponent_intent_level",
        "opponent_intent_score",
        "opponent_target_value_score",
        "opponent_target_value_reason",
        "opponent_low_contribution_to_resource_production",
        "opponent_best_alternative_turns",
        "opponent_opportunity_cost_penalty",
        "opponent_move_viability_level",
        "opponent_move_viability_score",
        "opponent_move_viability_reason",
        "opponent_target_value_level",
        "opponent_target_rank_by_value",
        "opponent_target_rank_by_timing",
        "opponent_best_candidate_target_id",
        "opponent_best_candidate_value_score",
        "opponent_best_candidate_turns",
        "opponent_target_value_gap_vs_best",
        "opponent_target_timing_gap_vs_best",
        "opponent_candidate_rank_bonus",
        "opponent_candidate_rank_penalty",
        "opponent_candidate_context_reason",
        "road_contested",
        "contested_roads_count",
        "road_risk_level",
        "road_risk_score",
        "road_risk_reason",
        "worst_contested_road",
        "worst_road_my_turns",
        "worst_road_opponent_turns",
        "worst_road_opponent_id",
        "worst_road_opponent_color",
        "worst_road_race_relation",
        "worst_road_race_margin",
        "worst_road_race_significance_margin",
        "road_race_details",
        "risk_stage",
        "risk_competitors",
        "risk_notes",
        "trade_required",
        "payable_discrete",
        "continuous_only_trade_estimate",
        "imports_required",
        "discrete_import_capacity",
        "discrete_trade_gap",
        "trade_margin",
        "continuous_trade_margin",
        "anticipated_trades_with_bank",
        "anticipated_trades_with_bank_possible",
        "anticipated_trades_with_bank_still_missing",
        "anticipated_trades_with_player",
        "anticipated_trades_with_player_status",
        "anticipated_trades_with_player_counterparties",
        "anticipated_trades_with_player_possible",
        "bank_trades_after_player_trades",
        "bank_trades_after_player_trades_possible",
        "player_trade_adjusted_still_missing",
        "player_trade_adjusted_payable_discrete",
        "player_trade_adjusted_discrete_trade_gap",
        "expected_hand_after_player_trades",
        "payment_model",
        "projection_basis",
        "player_trade_benefit_used_for_projection",
        "player_trade_projection_note",
        "projection_valid",
        "payment_reliable",
        "projection_warnings",
        "post_action_hand",
        "player_trade_gives",
        "player_trade_receives",
        "bank_exports_used",
        "bank_imports_received",
        "stage2_bank_trade_plan",
        "production_gain",
        "production_pips_after_action",
        "trade_rates_after_action",
        "ports_after_action",
        "settlements_after_action",
        "cities_after_action",
        "roads_count_after_action",
        "victory_points_after_action",
        "baseline_best_way_id",
        "baseline_best_expected_own_turns",
        "continuation_rank",
        "continuation_way_id",
        "continuation_expected_own_turns_after_action",
        "total_expected_own_turns",
        "continuation_turn_gain",
        "net_total_turn_gain",
        "strategy_changed",
        "continuation_found",
        "continuation_confidence",
        "continuation_confidence_label",
        "continuation_tags",
        "continuation_need_vector",
        "continuation_need_compact",
        "continuation_reason",
        "continuation_trade_dependency",
        "continuation_payment_trade_margin",
        "continuation_discrete_trade_gap",
        "current_hand",
        "production_pips",
        "trade_rates",
        "ports",
        "expected_hand_at_action_time",
        "notes",
    ]

    def build_base_row(
        *,
        player_info: Mapping[str, Any],
        action: Mapping[str, Any],
        rank: int,
        preferred_strategy: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        diag = action.get("trade_diagnostics", {}) or {}
        pdiag = action.get("player_trade_diagnostics", {}) or {}
        projection = action.get("projection", {}) or {}
        risk = action.get("risk_assessment", {}) or {}
        preferred = dict(preferred_strategy or {})
        return {
            "report_round": report.get("round"),
            "report_turn": report.get("turn"),
            "stage": report.get("stage", 1),
            "player_id": player_info.get("player_id"),
            "color": player_info.get("color"),
            "action_rank": rank,
            "action_type": action.get("action_type"),
            "target_id": action.get("target_id"),
            "description": action.get("description"),
            "road_count": action.get("road_count"),
            "roads_to_build": json.dumps(action.get("roads_to_build", []), ensure_ascii=False),
            "cost_vector": json.dumps(action.get("cost_vector", []), ensure_ascii=False),
            "cost_compact": _resource_compact(action.get("cost_vector", [])),
            "action_expected_own_turns": action.get("action_expected_own_turns"),
            "action_expected_global_turns": action.get("action_expected_global_turns"),
            "action_strict_expected_own_turns": action.get("action_strict_expected_own_turns"),
            "action_strict_expected_global_turns": action.get("action_strict_expected_global_turns"),
            "found": action.get("found"),
            "strict_found": action.get("strict_found"),
            "confidence": action.get("confidence"),
            "confidence_label": action.get("confidence_label"),
            "risk_score": risk.get("risk_score", action.get("risk_score")),
            "risk_level": risk.get("risk_level", action.get("risk_level", "")),
            "risk_reason": risk.get("risk_reason", action.get("risk_reason", "")),
            "action_risk_level": risk.get("action_risk_level", risk.get("risk_level", action.get("risk_level", ""))),
            "action_risk_score": risk.get("action_risk_score", risk.get("risk_score", action.get("risk_score", ""))),
            "action_risk_source": risk.get("action_risk_source", ""),
            "action_risk_penalty_turns": risk.get("action_risk_penalty_turns", 0.0),
            "risk_adjusted_total_expected_own_turns": risk.get("risk_adjusted_total_expected_own_turns", ""),
            "risk_adjusted_net_total_turn_gain": risk.get("risk_adjusted_net_total_turn_gain", ""),
            "tactical_urgency_level": risk.get("tactical_urgency_level", ""),
            "tactical_urgency_score": risk.get("tactical_urgency_score", ""),
            "action_decision_level": risk.get("action_decision_level", ""),
            "action_decision_reason": risk.get("action_decision_reason", ""),
            "preferred_way_id": preferred.get("preferred_way_id", preferred.get("way_id", "")),
            "preferred_way_level": preferred.get("preference_level", ""),
            "preferred_way_reason": preferred.get("preference_reason", ""),
            "preferred_way_is_this_row": False,
            "preferred_way_supporting_action_id": preferred.get("supporting_action_id", ""),
            "preferred_way_supporting_action_type": preferred.get("supporting_action_type", ""),
            "preferred_way_supporting_action_target_id": preferred.get("supporting_action_target_id", ""),
            "preferred_way_risk_adjusted_total": preferred.get("risk_adjusted_total_expected_own_turns", ""),
            "preferred_way_risk_adjusted_gain": preferred.get("risk_adjusted_net_total_turn_gain", ""),
            "target_contested": risk.get("target_contested", False),
            "target_race_relation": risk.get("target_race_relation", ""),
            "target_race_margin": risk.get("target_race_margin", ""),
            "target_race_significance_margin": risk.get("target_race_significance_margin", ""),
            "target_best_opponent_id": risk.get("target_best_opponent_id", ""),
            "target_best_opponent_color": risk.get("target_best_opponent_color", ""),
            "target_best_opponent_turns": risk.get("target_best_opponent_turns", ""),
            "target_my_turns": risk.get("target_my_turns", ""),
            "opponent_intent_level": risk.get("opponent_intent_level", ""),
            "opponent_intent_score": risk.get("opponent_intent_score", ""),
            "opponent_target_value_score": risk.get("opponent_target_value_score", ""),
            "opponent_target_value_reason": risk.get("opponent_target_value_reason", ""),
            "opponent_low_contribution_to_resource_production": risk.get("opponent_low_contribution_to_resource_production", ""),
            "opponent_best_alternative_turns": risk.get("opponent_best_alternative_turns", ""),
            "opponent_opportunity_cost_penalty": risk.get("opponent_opportunity_cost_penalty", ""),
            "opponent_move_viability_level": risk.get("opponent_move_viability_level", risk.get("opponent_intent_level", "")),
            "opponent_move_viability_score": risk.get("opponent_move_viability_score", risk.get("opponent_intent_score", "")),
            "opponent_move_viability_reason": risk.get("opponent_move_viability_reason", ""),
            "opponent_target_value_level": risk.get("opponent_target_value_level", ""),
            "opponent_target_rank_by_value": risk.get("opponent_target_rank_by_value", ""),
            "opponent_target_rank_by_timing": risk.get("opponent_target_rank_by_timing", ""),
            "opponent_best_candidate_target_id": risk.get("opponent_best_candidate_target_id", ""),
            "opponent_best_candidate_value_score": risk.get("opponent_best_candidate_value_score", ""),
            "opponent_best_candidate_turns": risk.get("opponent_best_candidate_turns", ""),
            "opponent_target_value_gap_vs_best": risk.get("opponent_target_value_gap_vs_best", ""),
            "opponent_target_timing_gap_vs_best": risk.get("opponent_target_timing_gap_vs_best", ""),
            "opponent_candidate_rank_bonus": risk.get("opponent_candidate_rank_bonus", ""),
            "opponent_candidate_rank_penalty": risk.get("opponent_candidate_rank_penalty", ""),
            "opponent_candidate_context_reason": risk.get("opponent_candidate_context_reason", ""),
            "road_contested": risk.get("road_contested", False),
            "contested_roads_count": risk.get("contested_roads_count", 0),
            "road_risk_level": risk.get("road_risk_level", ""),
            "road_risk_score": risk.get("road_risk_score", ""),
            "road_risk_reason": risk.get("road_risk_reason", ""),
            "worst_contested_road": json.dumps(risk.get("worst_contested_road", None), ensure_ascii=False),
            "worst_road_my_turns": risk.get("worst_road_my_turns", ""),
            "worst_road_opponent_turns": risk.get("worst_road_opponent_turns", ""),
            "worst_road_opponent_id": risk.get("worst_road_opponent_id", ""),
            "worst_road_opponent_color": risk.get("worst_road_opponent_color", ""),
            "worst_road_race_relation": risk.get("worst_road_race_relation", ""),
            "worst_road_race_margin": risk.get("worst_road_race_margin", ""),
            "worst_road_race_significance_margin": risk.get("worst_road_race_significance_margin", ""),
            "road_race_details": json.dumps(risk.get("road_race_details", []), ensure_ascii=False),
            "risk_stage": risk.get("risk_stage", ""),
            "risk_competitors": json.dumps(risk.get("competitors", []), ensure_ascii=False),
            "risk_notes": ";".join(str(x) for x in risk.get("notes", []) or []),
            "trade_required": diag.get("trade_required"),
            "payable_discrete": diag.get("payable_discrete"),
            "continuous_only_trade_estimate": diag.get("continuous_only_trade_estimate"),
            "imports_required": diag.get("imports_required"),
            "discrete_import_capacity": diag.get("discrete_import_capacity"),
            "discrete_trade_gap": diag.get("discrete_trade_gap"),
            "trade_margin": diag.get("trade_margin"),
            "continuous_trade_margin": diag.get("continuous_trade_margin"),
            "anticipated_trades_with_bank": diag.get("anticipated_bank_trades_text", ""),
            "anticipated_trades_with_bank_possible": diag.get("anticipated_bank_trades_possible"),
            "anticipated_trades_with_bank_still_missing": json.dumps(diag.get("anticipated_bank_trades_still_missing", []), ensure_ascii=False),
            "anticipated_trades_with_player": pdiag.get("anticipated_player_trades_text", ""),
            "anticipated_trades_with_player_status": pdiag.get("anticipated_player_trade_status", "none"),
            "anticipated_trades_with_player_counterparties": json.dumps(pdiag.get("anticipated_player_trade_counterparties", []), ensure_ascii=False),
            "anticipated_trades_with_player_possible": pdiag.get("anticipated_player_trades_possible", False),
            "bank_trades_after_player_trades": pdiag.get("bank_trades_after_player_trades_text", diag.get("anticipated_bank_trades_text", "")),
            "bank_trades_after_player_trades_possible": pdiag.get("bank_trades_after_player_trades_possible", diag.get("anticipated_bank_trades_possible")),
            "player_trade_adjusted_still_missing": json.dumps(pdiag.get("player_trade_adjusted_still_missing", diag.get("anticipated_bank_trades_still_missing", [])), ensure_ascii=False),
            "player_trade_adjusted_payable_discrete": pdiag.get("player_trade_adjusted_payable_discrete", diag.get("payable_discrete")),
            "player_trade_adjusted_discrete_trade_gap": pdiag.get("player_trade_adjusted_discrete_trade_gap", diag.get("discrete_trade_gap")),
            "expected_hand_after_player_trades": json.dumps(pdiag.get("expected_hand_after_player_trades", action.get("expected_hand_at_action_time", [])), ensure_ascii=False),
            "payment_model": projection.get("payment_model", ""),
            "projection_basis": projection.get("projection_basis", "base_no_player_trades"),
            "player_trade_benefit_used_for_projection": projection.get("player_trade_benefit_used_for_projection", False),
            "player_trade_projection_note": projection.get("player_trade_projection_note", ""),
            "projection_valid": projection.get("projection_valid", False),
            "payment_reliable": projection.get("payment_reliable", False),
            "projection_warnings": ";".join(str(x) for x in projection.get("projection_warnings", []) or []),
            "post_action_hand": json.dumps(projection.get("post_action_hand", []), ensure_ascii=False),
            "player_trade_gives": json.dumps(projection.get("player_trade_gives", []), ensure_ascii=False),
            "player_trade_receives": json.dumps(projection.get("player_trade_receives", []), ensure_ascii=False),
            "bank_exports_used": json.dumps(projection.get("bank_exports_used", []), ensure_ascii=False),
            "bank_imports_received": json.dumps(projection.get("bank_imports_received", []), ensure_ascii=False),
            "stage2_bank_trade_plan": ", ".join(str(x) for x in projection.get("bank_trade_plan", []) or []),
            "production_gain": json.dumps(projection.get("production_gain", []), ensure_ascii=False),
            "production_pips_after_action": json.dumps(projection.get("production_pips_after_action", []), ensure_ascii=False),
            "trade_rates_after_action": json.dumps(projection.get("trade_rates_after_action", []), ensure_ascii=False),
            "ports_after_action": json.dumps(projection.get("ports_after_action", []), ensure_ascii=False),
            "settlements_after_action": json.dumps(projection.get("settlements_after_action", []), ensure_ascii=False),
            "cities_after_action": json.dumps(projection.get("cities_after_action", []), ensure_ascii=False),
            "roads_count_after_action": projection.get("roads_count_after_action", ""),
            "victory_points_after_action": projection.get("victory_points_after_action", ""),
            "current_hand": json.dumps(action.get("current_hand", []), ensure_ascii=False),
            "production_pips": json.dumps(action.get("production_pips", []), ensure_ascii=False),
            "trade_rates": json.dumps(action.get("trade_rates", []), ensure_ascii=False),
            "ports": json.dumps(action.get("ports", []), ensure_ascii=False),
            "expected_hand_at_action_time": json.dumps(action.get("expected_hand_at_action_time", []), ensure_ascii=False),
            "notes": ";".join(str(x) for x in action.get("notes", []) or []),
        }

    def add_continuation_fields(row: Dict[str, Any], continuation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        out = dict(row)
        risk_penalty = safe_float(out.get("action_risk_penalty_turns"), 0.0)
        if not continuation:
            out.update(
                {
                    "risk_adjusted_total_expected_own_turns": "",
                    "risk_adjusted_net_total_turn_gain": "",
                    "baseline_best_way_id": "",
                    "baseline_best_expected_own_turns": "",
                    "continuation_rank": "",
                    "continuation_way_id": "",
                    "continuation_expected_own_turns_after_action": "",
                    "total_expected_own_turns": "",
                    "continuation_turn_gain": "",
                    "net_total_turn_gain": "",
                    "strategy_changed": "",
                    "continuation_found": "",
                    "continuation_confidence": "",
                    "continuation_confidence_label": "",
                    "continuation_tags": "",
                    "continuation_need_vector": "",
                    "continuation_need_compact": "",
                    "continuation_reason": "",
                    "continuation_trade_dependency": "",
                    "continuation_payment_trade_margin": "",
                    "continuation_discrete_trade_gap": "",
                }
            )
            return out

        tdiag = continuation.get("trade_diagnostics", {}) or {}
        total_expected = finite_or_9999(continuation.get("total_expected_own_turns", INFINITE_TURNS))
        net_gain = safe_float(continuation.get("net_total_turn_gain"), -INFINITE_TURNS)
        risk_adjusted_total = (total_expected + risk_penalty) if total_expected < INFINITE_TURNS else ""
        risk_adjusted_gain = (net_gain - risk_penalty) if net_gain > -INFINITE_TURNS / 2 else ""
        out.update(
            {
                "baseline_best_way_id": continuation.get("baseline_best_way_id", ""),
                "baseline_best_expected_own_turns": continuation.get("baseline_best_expected_own_turns", ""),
                "continuation_rank": continuation.get("continuation_rank", continuation.get("rank", "")),
                "continuation_way_id": continuation.get("continuation_way_id", continuation.get("way_id", "")),
                "continuation_expected_own_turns_after_action": continuation.get("continuation_expected_own_turns_after_action", continuation.get("turns", "")),
                "total_expected_own_turns": continuation.get("total_expected_own_turns", ""),
                "continuation_turn_gain": continuation.get("continuation_turn_gain", ""),
                "net_total_turn_gain": continuation.get("net_total_turn_gain", ""),
                "risk_adjusted_total_expected_own_turns": risk_adjusted_total,
                "risk_adjusted_net_total_turn_gain": risk_adjusted_gain,
                "strategy_changed": continuation.get("strategy_changed", ""),
                "continuation_found": continuation.get("found", ""),
                "continuation_confidence": continuation.get("confidence", ""),
                "continuation_confidence_label": continuation.get("confidence_label", ""),
                "continuation_tags": ", ".join(str(x) for x in continuation.get("tags", []) or []),
                "continuation_need_vector": json.dumps(continuation.get("need_vector", []), ensure_ascii=False),
                "continuation_need_compact": continuation.get("need_compact", ""),
                "continuation_reason": continuation.get("reason", ""),
                "continuation_trade_dependency": "; ".join(str(x) for x in continuation.get("trade_dependency", []) or []),
                "continuation_payment_trade_margin": tdiag.get("trade_margin", ""),
                "continuation_discrete_trade_gap": tdiag.get("discrete_trade_gap", ""),
            }
        )
        preferred_way_id = _strategy_pref_int_or_none(out.get("preferred_way_id"))
        row_way_id = _strategy_pref_int_or_none(
            continuation.get("continuation_way_id", continuation.get("way_id", ""))
        )
        out["preferred_way_is_this_row"] = (
            preferred_way_id is not None
            and row_way_id is not None
            and preferred_way_id == row_way_id
        )
        return out

    rows: List[Dict[str, Any]] = []
    settings = dict(report.get("settings", {}) or {})
    stage3_scope = str(settings.get("stage3_player_scope", "")).strip().lower()
    stage3_targets = set()
    for value in list(settings.get("stage3_target_player_ids", []) or []):
        try:
            stage3_targets.add(int(value))
        except Exception:
            pass
    hide_non_stage3_players = (
        bool(settings.get("continuation_strategies_enabled", False))
        and stage3_scope == STAGE3_SCOPE_CURRENT_TURN_PLAYER
        and bool(stage3_targets)
    )

    for player_block in (report.get("by_player", {}) or {}).values():
        player_info = player_block.get("player", {}) or {}
        try:
            csv_player_id = int(player_info.get("player_id"))
        except Exception:
            csv_player_id = -999999
        if hide_non_stage3_players and csv_player_id not in stage3_targets:
            continue

        action_key = "all_candidate_actions" if use_all_candidate_actions else "best_actions"
        actions = list(player_block.get(action_key, []) or [])
        for rank, action in enumerate(actions, start=1):
            if not isinstance(action, Mapping):
                continue
            preferred_strategy = player_block.get("preferred_strategy", {}) or {}
            base_row = build_base_row(
                player_info=player_info,
                action=action,
                rank=rank,
                preferred_strategy=preferred_strategy if isinstance(preferred_strategy, Mapping) else {},
            )
            continuations = list(action.get("continuation_top_strategies", []) or [])
            if continuations:
                for continuation in continuations:
                    rows.append(add_continuation_fields(base_row, continuation if isinstance(continuation, Mapping) else None))
            else:
                rows.append(add_continuation_fields(base_row, None))

    def format_csv_scalar(value: Any) -> Any:
        """
        Format scalar values for Excel-friendly CSV output.

        With Dutch/European Excel settings, semicolon is the field separator and
        comma is the decimal separator.  Writing 16,75 keeps the value numeric
        in Excel, while 16.75 is often treated as text.

        Do not convert JSON/list columns here; they are already strings and are
        meant to remain text fields.
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float):
            if not isfinite(value):
                return ""
            digits = max(0, int(float_digits))
            rounded = round(float(value), digits)
            if abs(rounded - int(round(rounded))) <= 10 ** (-(digits + 1)):
                return str(int(round(rounded)))
            text_value = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
            if decimal_separator and decimal_separator != ".":
                text_value = text_value.replace(".", str(decimal_separator))
            return text_value
        return value

    def format_csv_row(row: Mapping[str, Any]) -> Dict[str, Any]:
        return {field: format_csv_scalar(row.get(field, "")) for field in fieldnames}

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        if excel_sep_hint:
            f.write(f"sep={delimiter}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(format_csv_row(row) for row in rows)

    return out_path



def format_player_top_actions(player_block: Mapping[str, Any], *, limit: int = 5) -> str:
    """Return a compact console summary for one player's best Stage-1 actions."""
    player = player_block.get("player", {}) or {}
    actions = list(player_block.get("best_actions", []) or [])[: max(0, int(limit))]
    header = f"Player {player.get('player_id')} {player.get('color')} | best build actions"
    lines = [header]
    if not actions:
        lines.append("  - no candidate actions")
        return "\n".join(lines)

    for idx, action in enumerate(actions, start=1):
        diag = action.get("trade_diagnostics", {}) or {}
        strict_note = ""
        if diag.get("continuous_only_trade_estimate"):
            strict_note = " | continuous-only trade"
        projection = action.get("projection", {}) or {}
        payment_note = f" | payment={projection.get('payment_model')}" if projection else ""
        risk = action.get("risk_assessment", {}) or {}
        risk_note = f" | risk={risk.get('risk_level')}" if risk else ""
        cont = action.get("best_continuation_strategy", {}) or {}
        cont_note = ""
        if cont:
            cont_note = (
                f" | cont_way={cont.get('continuation_way_id')} "
                f"cont={cont.get('continuation_expected_own_turns_after_action')} "
                f"total={cont.get('total_expected_own_turns')}"
            )
        lines.append(
            "  "
            f"{idx}. {action.get('action_type')} target={action.get('target_id')} "
            f"turns={action.get('action_expected_own_turns')} "
            f"strict={action.get('action_strict_expected_own_turns')} "
            f"conf={safe_float(action.get('confidence'), 0.0):.3f}"
            f"{strict_note}"
            f"{payment_note}"
            f"{cont_note}"
            f"{risk_note}"
        )
    return "\n".join(lines)


def format_game_top_actions(report: Mapping[str, Any], *, limit: int = 5) -> str:
    """Return a compact console summary for all players."""
    blocks = []
    for player_block in (report.get("by_player", {}) or {}).values():
        blocks.append(format_player_top_actions(player_block, limit=limit))
    return "\n".join(blocks)


__all__ = [
    "ActionTradeDiagnostics",
    "BuildActionTiming",
    "ProjectedActionResult",
    "build_action_timings_for_player",
    "build_action_timing_report",
    "save_action_timing_report_json",
    "write_action_timing_report_csv",
    "apply_player_trade_layer",
    "apply_action_projection_layer",
    "apply_strategy_continuation_layer",
    "apply_risk_assessment_layer",
    "apply_strategy_preference_layer",
    "select_preferred_strategy_for_player_block",
    "STAGE3_SCOPE_CURRENT_TURN_PLAYER",
    "STAGE3_SCOPE_ALL_PLAYERS",
    "STAGE4_SCOPE_CURRENT_TURN_PLAYER",
    "STAGE4_SCOPE_ALL_PLAYERS",
    "format_player_top_actions",
    "format_game_top_actions",
]

# ──────────────────────────────────────────────────────────────────────────────
# Stage-4G Integrates Phase 4G stub + settlement-road priority
# ──────────────────────────────────────────────────────────────────────────────

try:
    from core.ai_way_portfolio import evaluate_top_ways_board_feasibility, format_audit_compact
    PORTFOLIO_AVAILABLE = True
except Exception:
    PORTFOLIO_AVAILABLE = False
    def evaluate_top_ways_board_feasibility(*args, **kwargs): 
        return []
    def format_audit_compact(audit): 
        return "FEAS: stub (not loaded)"

class ActionPlanner:
    def __init__(self, game):
        self.game = game

    # ──────────────────────────────────────────────────────────────────────────────
    # Helper functions
    # ──────────────────────────────────────────────────────────────────────────────

    def _get_viable_actions(self, player) -> List[Dict[str, Any]]:
        """Return raw viable buy/build actions from the execution scanner (complete function)."""
        scan = getattr(self.game, "current_viable_action_scan", None)
        if scan is None:
            from core.execution_phase_manager import ExecutionPhaseManager
            manager = ExecutionPhaseManager(self.game)
            scan = manager.refresh_viable_actions(reason="planner_get_viable_actions")
        
        viable = []
        for action_type, candidates in (scan.get("candidates", {}) if isinstance(scan, dict) else {}).items():
            for cand in candidates[:5]:
                viable.append({
                    "action_type": action_type,
                    "target_id": cand.get("target_id") if isinstance(cand, dict) else cand,
                    "viable": True,
                    "description": f"{action_type} @ {cand.get('target_id', cand)}" if isinstance(cand, dict) else action_type
                })
        return viable

    def _select_best_from_viable(self, viable_actions: List[Dict[str, Any]], player) -> Dict[str, Any]:
        """Select the best viable action based on strategy direction (complete function)."""
        if not viable_actions:
            return {"action": "End turn", "reason": "no_viable_actions"}
        
        direction = getattr(player, "strategic_direction", {}) or {}
        preferred_type = str(direction.get("supporting_action_type", "") or "").lower()
        
        for act in viable_actions:
            if preferred_type and preferred_type in str(act.get("action_type", "")).lower():
                return act
        
        return viable_actions[0]

    def _get_top_ways(self, player) -> List[int]:
        """Return top ways for portfolio evaluation (stub, complete function)."""
        direction = getattr(player, "strategic_direction", {}) or {}
        way_id = direction.get("preferred_way_id") or direction.get("way_id")
        if way_id:
            return [way_id]
        # 4G-A: prefer abstract rank fallback rather than hardcoded ways
        try:
            from core.strategy_timing import rank_strategies_for_player
            board = getattr(self.game, "board", None)
            if board is not None:
                ranked = rank_strategies_for_player(board, player, top_n=5, include_all=False, require_confidence=False)
                ids = [int(r.get("way_id")) for r in list(ranked.get("top_strategies", []) or []) if isinstance(r, dict) and r.get("way_id") is not None]
                if ids:
                    return ids
        except Exception:
            pass
        return []
    
    def get_best_action(self, player) -> Dict[str, Any]:
        """Main entry point for strategic decision with Phase 4G-B board project."""
        viable_actions = self._get_viable_actions(player)

        # Board portfolio (also sets game.current_board_way_audit)
        top_ways = self._get_top_ways(player)
        board_audits = evaluate_top_ways_board_feasibility(self.game, player, top_ways)
        if board_audits:
            best_audit = board_audits[0]
            self.game.current_board_way_audit = best_audit
            try:
                from core.console import digin, DEBUG

                digin(
                    "FEAS: Way {} exp={:.1f} frag={} rec={}".format(
                        best_audit.way_id,
                        best_audit.board_expected_turns,
                        best_audit.fragility,
                        best_audit.recommendation,
                    ),
                    level=DEBUG,
                )
            except Exception:
                print(
                    "FEAS: Way {} exp={:.1f} frag={} rec={}".format(
                        best_audit.way_id,
                        best_audit.board_expected_turns,
                        best_audit.fragility,
                        best_audit.recommendation,
                    )
                )
            # Ensure strategic_direction carries board project (4G-B)
            try:
                from core.ai_way_portfolio import (
                    board_audit_to_strategic_direction,
                    persist_strategic_direction,
                )
                direction = board_audit_to_strategic_direction(
                    best_audit,
                    abstract_preferred=getattr(player, "strategic_direction", None) or {},
                    override_applied=True,
                    override_reason="get_best_action_board_project",
                )
                # Prefer existing board-persisted direction if present and same way
                existing = getattr(player, "strategic_direction", None) or {}
                if not (isinstance(existing, dict) and existing.get("recommendation_target_id") is not None):
                    persist_strategic_direction(player, direction)
            except Exception:
                pass

        # Prefer action advancing board project target
        project_action = self._select_action_for_board_project(player, viable_actions)
        if project_action:
            return project_action

        # Settlement completion lock (road priority) toward strategy target when possible
        if self._needs_new_settlement(player) and not self._has_frontier_road_candidate(viable_actions):
            road_action = self._find_settlement_road(player)
            if road_action:
                return road_action

        return self._select_best_from_viable(viable_actions, player)

    def _select_action_for_board_project(self, player, viable_actions):
        """Pick a viable action that advances recommendation_target_id / supporting_action_type."""
        direction = getattr(player, "strategic_direction", None) or {}
        if not isinstance(direction, dict):
            direction = {}
        audit = getattr(self.game, "current_board_way_audit", None)
        target_id = direction.get("recommendation_target_id") or direction.get("settlement_target_id")
        if target_id is None and audit is not None:
            target_id = getattr(audit, "recommendation_target_id", None)
        try:
            target_id = int(target_id) if target_id is not None else None
        except Exception:
            target_id = None
        supporting = str(direction.get("supporting_action_type", "") or "").lower()
        roads = list(direction.get("roads_to_build") or [])
        if audit is not None and not roads:
            for t in list(getattr(audit, "target_portfolio", []) or []):
                tid = getattr(t, "target_id", None) if not isinstance(t, dict) else t.get("target_id")
                if target_id is not None and int(tid or -1) == int(target_id):
                    roads = list(getattr(t, "roads_to_build", None) or (t.get("roads_to_build") if isinstance(t, dict) else []) or [])
                    break

        def _norm_road(r):
            try:
                a, b = list(r)[:2]
                return tuple(sorted((int(a), int(b))))
            except Exception:
                return None

        road_set = {_norm_road(r) for r in roads}
        road_set.discard(None)

        # 1) Settlement at project target
        if target_id is not None:
            for act in viable_actions or []:
                if not isinstance(act, dict):
                    continue
                at = str(act.get("action_type", "")).lower()
                if "settle" in at:
                    tid = act.get("target_id")
                    try:
                        if tid is not None and int(tid) == target_id:
                            out = dict(act)
                            out["reason"] = "board_project_settle"
                            out["priority"] = "high"
                            return out
                    except Exception:
                        pass

        # 2) Road on project path
        if road_set or (supporting in ("new_settlement", "build_road") and target_id is not None):
            for act in viable_actions or []:
                if not isinstance(act, dict):
                    continue
                at = str(act.get("action_type", "")).lower()
                if "road" not in at:
                    continue
                rid = act.get("target_id") or act.get("road_id")
                nr = _norm_road(rid) if rid is not None else None
                if road_set and nr in road_set:
                    out = dict(act)
                    out["reason"] = "board_project_road"
                    out["priority"] = "high"
                    return out
            # scanner candidates on path
            path_road = self._find_settlement_road(player)
            if path_road:
                path_road = dict(path_road)
                path_road["reason"] = "board_project_road_scan"
                return path_road

        # 3) City / dcard when project says so
        if supporting in ("city_upgrade", "city"):
            for act in viable_actions or []:
                if isinstance(act, dict) and "city" in str(act.get("action_type", "")).lower():
                    out = dict(act)
                    out["reason"] = "board_project_city"
                    return out
        if supporting in ("buy_dcard", "dcard", "dev_card"):
            for act in viable_actions or []:
                if isinstance(act, dict) and ("dcard" in str(act.get("action_type", "")).lower() or "dev" in str(act.get("action_type", "")).lower()):
                    out = dict(act)
                    out["reason"] = "board_project_dcard"
                    return out
        return None
    
    def _needs_new_settlement(self, player) -> bool:
        """Check if current strategy needs new settlements (complete function)."""
        if not hasattr(player, 'strategic_direction') or not player.strategic_direction:
            return False
        
        direction = player.strategic_direction
        remaining = direction.get("remaining_new_settlements", 0)
        
        # Also check way requirements for robustness
        if "way_requirements" in direction:
            req = direction["way_requirements"]
            remaining = max(remaining, req.get("new_settlements", 0) - len(getattr(player, "settlements", [])))
        
        return remaining > 0
    
    def _has_frontier_road_candidate(self, viable_actions: List[Dict[str, Any]]) -> bool:
        """Check if there is already a viable road action available (complete function)."""
        for act in viable_actions or []:
            if isinstance(act, dict) and act.get("action_type") == "road":
                return True
            if isinstance(act, str) and "road" in act.lower():
                return True
        return False

    def _find_settlement_road(self, player) -> Optional[Dict[str, Any]]:
        """Find a frontier road toward the board/strategy settlement project."""
        scan = getattr(self.game, "current_viable_action_scan", None)
        if scan is None:
            from core.execution_phase_manager import ExecutionPhaseManager
            manager = ExecutionPhaseManager(self.game)
            scan = manager.refresh_viable_actions(reason="planner_find_settlement_road")

        direction = getattr(player, "strategic_direction", None) or {}
        roads = list(direction.get("roads_to_build") or []) if isinstance(direction, dict) else []
        preferred = set()
        for r in roads:
            try:
                a, b = list(r)[:2]
                preferred.add(tuple(sorted((int(a), int(b)))))
            except Exception:
                pass

        cands = list((scan.get("candidates", {}) if isinstance(scan, dict) else {}).get("Build road", []) or [])
        # Prefer roads on the project path
        if preferred:
            for cand in cands:
                rid = cand.get("target_id") or cand.get("road_id") if isinstance(cand, dict) else cand
                try:
                    a, b = list(rid)[:2]
                    key = tuple(sorted((int(a), int(b))))
                except Exception:
                    continue
                if key in preferred:
                    return {
                        "action_type": "road",
                        "target_id": rid,
                        "description": "Project path road (Phase 4G-B)",
                        "reason": "board_project_path",
                        "priority": "high",
                    }

        for cand in cands:
            if isinstance(cand, dict):
                target = cand.get("target_id") or cand.get("road_id")
                if target:
                    return {
                        "action_type": "road",
                        "target_id": target,
                        "description": "Frontier road to new settlement (Phase 4G)",
                        "reason": "settlement_completion_lock",
                        "priority": "high",
                    }
        return None
