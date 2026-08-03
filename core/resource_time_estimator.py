"""
core/resource_time_estimator.py

Standalone Expected-Hand turns-to-afford estimator for Catan.

Purpose
-------
This module turns the expected-hand feasibility formula into a fast,
explainable resource timing engine:

    current hand
  + expected production over future dice rolls
  + bank/port trading capacity
  + optional probability-aware confidence
  = estimated own turns until an action is affordable.

Important conventions
---------------------
All public vectors in this module use the project/game resource order:

    [Wheat, Ore, Wood, Brick, Sheep]

This intentionally differs from some Markov internals. Keeping this
module in game order avoids conversion mistakes when integrating with
constants.py, initial_placement_phase_manager.py, action_evaluator.py, and
fast_forward.py.

Drop-in status for v010b
------------------------
This module is intentionally defensive:
- It imports v010b constants when they exist.
- It falls back to local defaults when optional EH constants are missing.
- It does not mutate game/player/board state.
- It estimates resource timing only; legal/exact execution should still
  be validated elsewhere before an action is performed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from math import ceil, floor, inf, isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Project constants with isolation-friendly fallbacks
# ──────────────────────────────────────────────────────────────────────────────

try:
    from core.constants import (
        NUM_PLAYERS,
        RESOURCE_ORDER,
        TERRAIN_TO_RESOURCE,
        ResourceCard,
        RCARDS_FOR_CITY,
        RCARDS_FOR_DCARD,
        RCARDS_FOR_ROAD,
        RCARDS_FOR_SETTLEMENT,
    )
except Exception:  # pragma: no cover - allows standalone tests/imports.
    from enum import Enum

    NUM_PLAYERS = 4

    class ResourceCard(Enum):  # type: ignore[no-redef]
        WHEAT = "Wheat"
        ORE = "Ore"
        WOOD = "Wood"
        BRICK = "Brick"
        SHEEP = "Sheep"

    RESOURCE_ORDER = [
        ResourceCard.WHEAT,
        ResourceCard.ORE,
        ResourceCard.WOOD,
        ResourceCard.BRICK,
        ResourceCard.SHEEP,
    ]

    TERRAIN_TO_RESOURCE = {
        "Field": ResourceCard.WHEAT,
        "Mountain": ResourceCard.ORE,
        "Forest": ResourceCard.WOOD,
        "Hill": ResourceCard.BRICK,
        "Pasture": ResourceCard.SHEEP,
    }

    RCARDS_FOR_CITY = [2, 3, 0, 0, 0]
    RCARDS_FOR_SETTLEMENT = [1, 0, 1, 1, 1]
    RCARDS_FOR_ROAD = [0, 0, 1, 1, 0]
    RCARDS_FOR_DCARD = [1, 1, 0, 0, 1]


# Optional EH constants. These may not exist yet in older modules.
try:
    from core.constants import EXPECTED_HAND_CONFIDENCE_TARGET  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_CONFIDENCE_TARGET = 0.85

try:
    from core.constants import EXPECTED_HAND_MAX_TURNS  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_MAX_TURNS = 60.0

try:
    from core.constants import EXPECTED_HAND_STEP  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_STEP = 0.25

try:
    from core.constants import EXPECTED_HAND_CONTINUOUS_TRADING  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_CONTINUOUS_TRADING = True

try:
    from core.constants import EXPECTED_HAND_REQUIRE_CONFIDENCE  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_REQUIRE_CONFIDENCE = False

try:
    from core.constants import EXPECTED_HAND_ROLLS_PER_PLAYER_TURN  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_ROLLS_PER_PLAYER_TURN = NUM_PLAYERS

try:
    from core.constants import EXPECTED_HAND_TARGET_EXTRA_ROADS  # type: ignore
except Exception:  # pragma: no cover
    EXPECTED_HAND_TARGET_EXTRA_ROADS = 1


RESOURCE_NAMES: List[str] = [rc.value for rc in RESOURCE_ORDER]
RESOURCE_INDEX_BY_NAME: Dict[str, int] = {
    name.lower(): idx for idx, name in enumerate(RESOURCE_NAMES)
}
RESOURCE_INDEX_BY_NAME.update(
    {
        "grain": RESOURCE_INDEX_BY_NAME.get("wheat", 0),
        "lumber": RESOURCE_INDEX_BY_NAME.get("wood", 2),
        "sheep": RESOURCE_INDEX_BY_NAME.get("sheep", 4),
    }
)

ZERO_VECTOR: List[float] = [0.0, 0.0, 0.0, 0.0, 0.0]
INFINITE_TURNS: float = 9999.0
_EPS: float = 1e-9


# ──────────────────────────────────────────────────────────────────────────────
# Result containers
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PayabilityResult:
    """Detailed result from expected-hand + trade affordability check."""

    payable_direct: bool
    payable_after_trades: bool
    short: Tuple[float, float, float, float, float]
    surplus: Tuple[float, float, float, float, float]
    trade_rates: Tuple[int, int, int, int, int]
    trades_needed: float
    trades_available: float
    imports_received: Tuple[float, float, float, float, float]
    exports_used: Tuple[float, float, float, float, float]
    required_pretrade_hand: Tuple[float, float, float, float, float]
    continuous_trading: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfidenceResult:
    """Probability-aware confidence details for an affordability estimate."""

    confidence: float
    label: str
    min_resource_confidence: float
    joint_resource_confidence: float
    per_resource_confidence: Tuple[float, float, float, float, float]
    required_pretrade_hand: Tuple[float, float, float, float, float]
    needed_produced_cards: Tuple[int, int, int, int, int]
    n_rolls: int
    production_probabilities: Tuple[float, float, float, float, float]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionTimeEstimate:
    """Top-level expected-hand timing result for one target/action."""

    action: str
    target_type: str
    target_id: Optional[int]
    extra_roads_needed: int
    turns: float
    found: bool
    confidence: float
    confidence_target: float
    confidence_label: str
    expected_hand: Tuple[float, float, float, float, float]
    current_hand: Tuple[float, float, float, float, float]
    production_pips: Tuple[float, float, float, float, float]
    need: Tuple[float, float, float, float, float]
    trade_rates: Tuple[int, int, int, int, int]
    payability: Dict[str, Any]
    confidence_info: Dict[str, Any]
    explanation: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# Basic vector and numeric helpers
# ──────────────────────────────────────────────────────────────────────────────

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clean_vector(
    values: Optional[Sequence[Any]],
    length: int = 5,
    default: float = 0.0,
) -> List[float]:
    """Return a length-5 float vector in game resource order."""
    if values is None:
        return [default] * length

    out = [safe_float(v, default) for v in list(values)[:length]]
    if len(out) < length:
        out.extend([default] * (length - len(out)))
    return out


def clean_int_vector(
    values: Optional[Sequence[Any]],
    length: int = 5,
    default: int = 4,
) -> List[int]:
    out = [max(1, safe_int(v, default)) for v in list(values or [])[:length]]
    if len(out) < length:
        out.extend([default] * (length - len(out)))
    return out


def vector_add(a: Sequence[Any], b: Sequence[Any]) -> List[float]:
    av = clean_vector(a)
    bv = clean_vector(b)
    return [av[i] + bv[i] for i in range(5)]


def vector_sub(a: Sequence[Any], b: Sequence[Any]) -> List[float]:
    av = clean_vector(a)
    bv = clean_vector(b)
    return [av[i] - bv[i] for i in range(5)]


def vector_sum(values: Sequence[Any]) -> float:
    return float(sum(clean_vector(values)))


def vector_to_named_dict(
    values: Sequence[Any],
    *,
    digits: Optional[int] = None,
) -> Dict[str, float]:
    vec = clean_vector(values)
    if digits is not None:
        vec = [round(v, digits) for v in vec]
    return {RESOURCE_NAMES[i]: vec[i] for i in range(5)}


def finite_or_9999(value: Any) -> float:
    v = safe_float(value, INFINITE_TURNS)
    if not isfinite(v):
        return INFINITE_TURNS
    return v


# ──────────────────────────────────────────────────────────────────────────────
# Target costs
# ──────────────────────────────────────────────────────────────────────────────

def normalize_target_type(target_type: str, *, extra_roads_needed: int = 0) -> str:
    """Normalize action/strategy aliases to target names used here."""
    t = str(target_type or "").strip().lower()

    aliases = {
        "": "settlement_0r",
        "best": "settlement_0r",
        "settlement": "settlement_0r",
        "next_settlement": "settlement_0r",
        "build_settlement": "settlement_0r",
        "new_settlement": "settlement_1r",
        "build_road_to_settlement": "settlement_1r",
        "city": "city",
        "upgrade_city": "city",
        "upgrade_to_city": "city",
        "dev": "dev_card",
        "dcard": "dev_card",
        "dev_card": "dev_card",
        "discovery_card": "dev_card",
        "buy_discovery_card": "dev_card",
        "buy_dev_card": "dev_card",
        "4x_dev_card": "dev_card_4",
        "dev_card_4": "dev_card_4",
        "buy_4_discovery_cards": "dev_card_4",
        "road": "road_1r",
        "roads": "road_1r",
        "build_road": "road_1r",
        "road_only": "road_1r",
    }

    if t in (
        "settlement_0r",
        "settlement_1r",
        "settlement_2r",
        "road_0r",
        "road_1r",
        "road_2r",
        "city",
        "dev_card",
        "dev_card_4",
    ):
        return t

    if t.startswith("settlement_") and t.endswith("r"):
        return t

    if t.startswith("road_") and t.endswith("r"):
        return t

    if t in aliases:
        normalized = aliases[t]
        if normalized == "settlement_0r" and extra_roads_needed > 0:
            return f"settlement_{int(extra_roads_needed)}r"
        return normalized

    if extra_roads_needed > 0 and "settlement" in t:
        return f"settlement_{int(extra_roads_needed)}r"

    if extra_roads_needed >= 0 and "road" in t:
        return f"road_{int(max(0, extra_roads_needed))}r"

    return t


def target_cost_vector(target_type: str, extra_roads_needed: int = 0) -> List[float]:
    """
    Return resource cost in game order [Wheat, Ore, Wood, Brick, Sheep].

    Supported examples:
        settlement_0r / settlement / next_settlement
        settlement_1r / new_settlement
        settlement_2r
        city / upgrade_to_city
        dev_card / buy_discovery_card
        dev_card_4
    """
    normalized = normalize_target_type(target_type, extra_roads_needed=extra_roads_needed)

    if normalized.startswith("road_") and normalized.endswith("r"):
        try:
            roads = int(normalized.split("_", 1)[1].replace("r", ""))
        except Exception:
            roads = int(max(0, extra_roads_needed))

        road = clean_vector(RCARDS_FOR_ROAD)
        return [roads * road[i] for i in range(5)]

    if normalized.startswith("settlement_") and normalized.endswith("r"):
        try:
            roads = int(normalized.split("_", 1)[1].replace("r", ""))
        except Exception:
            roads = int(max(0, extra_roads_needed))

        settlement = clean_vector(RCARDS_FOR_SETTLEMENT)
        road = clean_vector(RCARDS_FOR_ROAD)
        return [settlement[i] + roads * road[i] for i in range(5)]

    if normalized in ("city", "upgrade_to_city"):
        return clean_vector(RCARDS_FOR_CITY)

    if normalized in ("dev_card", "buy_discovery_card"):
        return clean_vector(RCARDS_FOR_DCARD)

    if normalized in ("dev_card_4", "4x_dev_card", "buy_4_discovery_cards"):
        dev = clean_vector(RCARDS_FOR_DCARD)
        return [4.0 * x for x in dev]

    raise ValueError(f"Unknown target_type: {target_type!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Ports and trade rates
# ──────────────────────────────────────────────────────────────────────────────

def normalize_port_type(port_type: Optional[str]) -> str:
    if not port_type:
        return ""

    text = str(port_type).strip()
    if not text or text.lower() == "blank":
        return ""

    return text.replace("Sheep", "Wool")


def resource_index_from_name(name: str) -> Optional[int]:
    return RESOURCE_INDEX_BY_NAME.get(str(name or "").strip().lower())


def resource_index_from_port(port_type: str) -> Optional[int]:
    port = normalize_port_type(port_type)
    if not port.startswith("2:1"):
        return None

    parts = port.split(maxsplit=1)
    if len(parts) != 2:
        return None

    return resource_index_from_name(parts[1])


def get_trade_rates_from_ports(ports: Iterable[str]) -> List[int]:
    """
    Convert owned ports to trade rates in game order.

        No port -> [4, 4, 4, 4, 4]
        3:1     -> [3, 3, 3, 3, 3]
        2:1 X   -> X becomes 2; other resources keep their best rate.
    """
    rates = [4, 4, 4, 4, 4]

    for raw_port in ports or []:
        port = normalize_port_type(raw_port)
        if not port:
            continue

        if port == "3:1":
            rates = [min(rate, 3) for rate in rates]
            continue

        idx = resource_index_from_port(port)
        if idx is not None:
            rates[idx] = min(rates[idx], 2)

    return rates


def trade_rates_from_markov_ports(player_ports: Optional[Mapping[Any, Any]]) -> List[int]:
    """
    Convert Markov-style port dictionaries to game-order trade rates.

    Examples:
        {"generic": 3}
        {"brick": 2, "generic": 3}
        {"lumber": 2, "ore": 2}
    """
    rates = [4, 4, 4, 4, 4]
    if not player_ports:
        return rates

    generic = None

    for key, value in player_ports.items():
        name = str(key).strip().lower()
        ratio = max(1, safe_int(value, 4))

        if name in ("generic", "3:1", "three", "any"):
            generic = ratio if generic is None else min(generic, ratio)

    if generic is not None:
        rates = [min(rate, generic) for rate in rates]

    for key, value in player_ports.items():
        name = str(key).strip().lower()

        if name in ("generic", "3:1", "three", "any"):
            continue

        if name == "lumber":
            name = "wood"
        if name == "sheep":
            name = "sheep"

        idx = resource_index_from_name(name)
        if idx is not None:
            rates[idx] = min(rates[idx], max(1, safe_int(value, 4)))

    return rates


def normalize_trade_rates(
    trade_rates: Optional[Sequence[Any]] = None,
    *,
    ports: Optional[Iterable[str]] = None,
    player_ports: Optional[Mapping[Any, Any]] = None,
) -> List[int]:
    """Return trade rates in game order, with sensible fallbacks."""
    if trade_rates is not None:
        return clean_int_vector(trade_rates, default=4)

    if player_ports is not None:
        return trade_rates_from_markov_ports(player_ports)

    if ports is not None:
        return get_trade_rates_from_ports(ports)

    return [4, 4, 4, 4, 4]


# ──────────────────────────────────────────────────────────────────────────────
# Board/player extraction helpers
# ──────────────────────────────────────────────────────────────────────────────

def pips_from_dice_value(value: Any) -> float:
    """Classic Catan pip/dot count for a 2d6 number token."""
    v = safe_int(value, 0)
    if not 2 <= v <= 12 or v == 7:
        return 0.0
    return float(6 - abs(7 - v))


def true_probability_from_pips(pips: Any) -> float:
    return max(0.0, min(1.0, safe_float(pips, 0.0) / 36.0))


def _tile_by_id_or_index(board: Any, tile_id: Any) -> Any:
    try:
        idx = int(tile_id)
    except (TypeError, ValueError):
        return None

    tiles = getattr(board, "tiles", []) or []

    if 0 <= idx < len(tiles):
        return tiles[idx]

    # Fallback for boards where tile.id is not equal to list index.
    for tile in tiles:
        if safe_int(getattr(tile, "id", None), -999999) == idx:
            return tile

    return None


def get_intersection_resource_pips(
    board: Any,
    inter_id: int,
    multiplier: float = 1.0,
) -> List[float]:
    """
    Return production pips for one intersection in game order.

    Prefers precomputed intersection.all_tile_pips when present.
    Falls back to adjacent tile IDs + TERRAIN_TO_RESOURCE + token pips.
    """
    result = [0.0] * 5

    try:
        inter = board.intersections[int(inter_id)]
    except (AttributeError, TypeError, ValueError, IndexError):
        return result

    if inter is None:
        return result

    for attr in (
        "all_tile_pips",
        "all_tile_probabilities",
        "three_tile_probabilities_v2",
        "three_tile_probabilities",
    ):
        raw = getattr(inter, attr, None)
        if isinstance(raw, (list, tuple)) and len(raw) >= 5:
            vec = clean_vector(raw)
            if vector_sum(vec) > 0:
                return [multiplier * x for x in vec]

    for tile_id in getattr(inter, "three_tile_ids", []) or []:
        tile = _tile_by_id_or_index(board, tile_id)
        if tile is None:
            continue

        terrain = getattr(tile, "type", None)
        if terrain in (None, "Sea", "Desert", "Blank"):
            continue

        resource = TERRAIN_TO_RESOURCE.get(terrain)
        if resource is None:
            continue

        try:
            idx = RESOURCE_ORDER.index(resource)
        except ValueError:
            continue

        result[idx] += pips_from_dice_value(getattr(tile, "value", 0)) * multiplier

    return result


def production_pips_from_vertices_game_order(
    board: Any,
    vertices: Sequence[int],
) -> List[float]:
    """
    Sum production pips for a vertex multiset in game order.

    Duplicate vertex IDs are intentionally preserved. This models city-like
    doubled production and matches Markov's duplicate-preserving position keys.
    """
    total = [0.0] * 5

    for vertex in vertices or []:
        pips = get_intersection_resource_pips(board, int(vertex))
        total = vector_add(total, pips)

    return total


def player_production_vertices(player: Any) -> List[int]:
    """
    Return a duplicate-preserving production vertex list for one player.

    Settlements count once.
    Cities count twice.

    If a project keeps upgraded city IDs in player.settlements, they are not
    triple-counted.
    """
    settlements = [int(x) for x in getattr(player, "settlements", []) or []]
    cities = [int(x) for x in getattr(player, "cities", []) or []]

    city_set = set(cities)
    settlement_only = [x for x in settlements if x not in city_set]

    return settlement_only + cities + cities


def get_player_production_pips(board: Any, player: Any) -> List[float]:
    return production_pips_from_vertices_game_order(board, player_production_vertices(player))


def get_player_resource_cards_vector(player: Any) -> List[float]:
    """Return current hand in game order [Wheat, Ore, Wood, Brick, Sheep]."""
    rcards = getattr(player, "rcards", {}) or {}
    values = []

    for rc in RESOURCE_ORDER:
        try:
            values.append(float(rcards.get(rc, 0)))
        except AttributeError:
            values.append(0.0)

    return clean_vector(values)


def get_player_ports(board: Any, player: Any) -> List[str]:
    """Best-effort owned port extraction."""
    ports: List[str] = []

    # Preferred if player tracks port_access directly.
    port_access = getattr(player, "port_access", None)
    if isinstance(port_access, Mapping):
        for port, owned in port_access.items():
            if owned:
                norm = normalize_port_type(str(port))
                if norm and norm not in ports:
                    ports.append(norm)

    # Fallback: inspect structures on port intersections.
    vertex_ids = list(getattr(player, "settlements", []) or []) + list(
        getattr(player, "cities", []) or []
    )

    for vertex in vertex_ids:
        try:
            inter = board.intersections[int(vertex)]
        except (AttributeError, TypeError, ValueError, IndexError):
            continue

        if inter is None:
            continue

        for attr in ("port_type"):
            norm = normalize_port_type(getattr(inter, attr, ""))
            if norm and norm not in ports:
                ports.append(norm)

        if bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y":
            norm = normalize_port_type(getattr(inter, "port_type", getattr(inter, "port_type", "")))
            if norm and norm not in ports:
                ports.append(norm)

    return ports


def get_player_trade_rates(board: Any, player: Any) -> List[int]:
    """Return player's trade rates in game order."""
    trade_rates = getattr(player, "trade_rates", None)

    if isinstance(trade_rates, Mapping):
        values: List[int] = []
        ok = True

        for rc in RESOURCE_ORDER:
            try:
                values.append(max(1, int(trade_rates.get(rc, 4))))
            except Exception:
                ok = False
                break

        if ok and len(values) == 5:
            return values

    return get_trade_rates_from_ports(get_player_ports(board, player))


# ──────────────────────────────────────────────────────────────────────────────
# Initial-placement candidate helpers
# ──────────────────────────────────────────────────────────────────────────────

def initial_resources_from_intersection(board: Any, inter_id: int) -> List[float]:
    """
    Return the starting resource cards gained from a second initial settlement.

    This is card count, not pips. Order: [Wheat, Ore, Wood, Brick, Sheep].
    Sea and desert are ignored.
    """
    hand = [0.0, 0.0, 0.0, 0.0, 0.0]

    try:
        inter = board.intersections[int(inter_id)]
    except (AttributeError, TypeError, ValueError, IndexError):
        return hand

    if inter is None:
        return hand

    for tile_id in getattr(inter, "three_tile_ids", []) or []:
        tile = _tile_by_id_or_index(board, tile_id)
        if tile is None:
            continue

        terrain = getattr(tile, "type", None)
        if terrain in (None, "Sea", "Desert", "Blank"):
            continue

        resource = TERRAIN_TO_RESOURCE.get(terrain)
        if resource is None:
            continue

        try:
            idx = RESOURCE_ORDER.index(resource)
        except ValueError:
            continue

        hand[idx] += 1.0

    return hand


def trade_rates_after_candidate(
    board: Any,
    player: Any,
    candidate_id: Optional[int] = None,
    base_rates: Optional[Sequence[Any]] = None,
) -> List[int]:
    """
    Return trade rates after adding a candidate settlement.

    This is useful during initial placement because a candidate may sit on a port
    before the candidate is actually appended to player.settlements.
    """
    rates = clean_int_vector(base_rates, default=4) if base_rates is not None else get_player_trade_rates(board, player)

    if candidate_id is None:
        return rates

    try:
        inter = board.intersections[int(candidate_id)]
    except (AttributeError, TypeError, ValueError, IndexError):
        return rates

    if inter is None:
        return rates

    if not getattr(inter, "port_tf", False):
        return rates

    port_type = normalize_port_type(getattr(inter, "port_type", ""))
    if not port_type:
        return rates

    candidate_rates = get_trade_rates_from_ports([port_type])
    return [min(rates[i], candidate_rates[i]) for i in range(5)]


def estimate_initial_placement_candidate_time(
    board: Any,
    player: Any,
    candidate_id: int,
    *,
    existing_settlements: Optional[Sequence[int]] = None,
    game_round: int = -2,
    current_hand: Optional[Sequence[Any]] = None,
    extra_roads_needed: int = EXPECTED_HAND_TARGET_EXTRA_ROADS,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    num_players: int = EXPECTED_HAND_ROLLS_PER_PLAYER_TURN,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
) -> Dict[str, Any]:
    """
    Estimate EH timing for an initial-placement settlement candidate.

    In round -2:
        - current_hand usually stays empty.
        - production vertices = [candidate_id].

    In round -1:
        - production vertices = existing settlements + candidate.
        - current hand receives starting resources from the candidate.
        - candidate port is included in the trade-rate estimate.

    The target defaults to settlement + one road:
        [1 Wheat, 0 Ore, 2 Wood, 2 Brick, 1 Sheep]
    """
    if existing_settlements is None:
        existing_settlements = list(getattr(player, "settlements", []) or [])

    vertices = list(existing_settlements)
    if candidate_id not in vertices:
        vertices.append(candidate_id)

    if current_hand is None:
        hand = get_player_resource_cards_vector(player)
    else:
        hand = clean_vector(current_hand)

    if int(game_round) == -1:
        hand = vector_add(hand, initial_resources_from_intersection(board, candidate_id))

    production_pips = production_pips_from_vertices_game_order(board, vertices)
    rates = trade_rates_after_candidate(board, player, candidate_id)

    target_type = f"settlement_{int(max(0, extra_roads_needed))}r"

    estimate = estimate_action_time(
        board=board,
        player=player,
        target_type=target_type,
        target_id=int(candidate_id),
        vertices=vertices,
        current_hand=hand,
        production_pips=production_pips,
        trade_rates=rates,
        extra_roads_needed=int(extra_roads_needed),
        confidence_target=confidence_target,
        num_players=int(num_players),
        step=step,
        max_turns=max_turns,
        continuous_trading=continuous_trading,
        require_confidence=require_confidence,
    )

    estimate["initial_placement_candidate_id"] = int(candidate_id)
    estimate["initial_placement_round"] = int(game_round)
    estimate["initial_placement_vertices"] = vertices
    estimate["initial_placement_starting_resources"] = tuple(
        initial_resources_from_intersection(board, candidate_id)
        if int(game_round) == -1
        else ZERO_VECTOR
    )

    return estimate


# ──────────────────────────────────────────────────────────────────────────────
# Expected hand and trade affordability
# ──────────────────────────────────────────────────────────────────────────────

def estimate_expected_hand_after_turns(
    current_hand: Sequence[Any],
    production_pips: Sequence[Any],
    turns: float,
    rolls_per_player_turn: int = EXPECTED_HAND_ROLLS_PER_PLAYER_TURN,
) -> List[float]:
    """
    Expected resource hand after `turns` own turns.

    production_pips are classic Catan pips per 36 dice rolls.

    In a 4-player game, one own turn corresponds to roughly four global
    dice-roll opportunities, so:

        expected_added_cards_i = pips_i * turns * players / 36
    """
    hand = clean_vector(current_hand)
    pips = clean_vector(production_pips)
    factor = float(max(0, rolls_per_player_turn)) * max(0.0, float(turns)) / 36.0

    return [hand[i] + pips[i] * factor for i in range(5)]


def _allocate_trade_plan(
    short: Sequence[float],
    surplus: Sequence[float],
    trade_rates: Sequence[int],
    *,
    continuous: bool,
) -> Tuple[List[float], List[float], float, float]:
    """
    Greedily allocate generic bank/port imports to deficits.

    Returns:
        imports_received, exports_used, trades_needed, trades_available
    """
    short_v = clean_vector(short)
    surplus_v = clean_vector(surplus)
    rates = clean_int_vector(trade_rates, default=4)

    trades_needed = float(sum(short_v))
    trades_available = 0.0

    for i in range(5):
        trades_available += (
            surplus_v[i] / rates[i]
            if continuous
            else floor((surplus_v[i] + _EPS) / rates[i])
        )

    imports_received = [0.0] * 5
    exports_used = [0.0] * 5
    remaining_imports = trades_needed

    if remaining_imports <= _EPS:
        return imports_received, exports_used, trades_needed, trades_available

    # Use cheapest/best trade rates first; this makes confidence less pessimistic.
    exporters = sorted(range(5), key=lambda idx: (rates[idx], -surplus_v[idx], idx))
    importers = [idx for idx, deficit in enumerate(short_v) if deficit > _EPS]

    for exporter in exporters:
        if remaining_imports <= _EPS:
            break

        if surplus_v[exporter] <= _EPS:
            continue

        if continuous:
            max_imports_from_exporter = surplus_v[exporter] / rates[exporter]
        else:
            max_imports_from_exporter = float(floor((surplus_v[exporter] + _EPS) / rates[exporter]))

        imports_from_exporter = min(remaining_imports, max_imports_from_exporter)
        if imports_from_exporter <= _EPS:
            continue

        exports_used[exporter] += imports_from_exporter * rates[exporter]
        remaining_imports -= imports_from_exporter

        # Allocate imported cards to short resources in resource order.
        remaining_from_exporter = imports_from_exporter
        for importer in importers:
            if remaining_from_exporter <= _EPS:
                break

            still_short = max(0.0, short_v[importer] - imports_received[importer])
            if still_short <= _EPS:
                continue

            add = min(still_short, remaining_from_exporter)
            imports_received[importer] += add
            remaining_from_exporter -= add

    return imports_received, exports_used, trades_needed, trades_available


def compute_payability_with_trades(
    expected_hand: Sequence[Any],
    need: Sequence[Any],
    trade_rates: Sequence[Any],
    *,
    continuous: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
) -> Dict[str, Any]:
    """
    Check whether an expected hand can pay a cost directly or through bank/ports.

    This is still an expected-value check, not exact gameplay execution.
    Exact PLAY should remain the legality/affordability guard.
    """
    have = clean_vector(expected_hand)
    need_v = clean_vector(need)
    rates = clean_int_vector(trade_rates, default=4)

    short = [max(0.0, need_v[i] - have[i]) for i in range(5)]
    surplus = [max(0.0, have[i] - need_v[i]) for i in range(5)]

    payable_direct = all(s <= _EPS for s in short)

    imports_received, exports_used, trades_needed, trades_available = _allocate_trade_plan(
        short,
        surplus,
        rates,
        continuous=continuous,
    )

    payable_after_trades = payable_direct or (trades_available + _EPS >= trades_needed)

    # Required hand before trading: resources kept for the cost plus resources exported.
    # If a deficit resource receives imports, it need not be fully present before trade.
    required_pretrade = [
        max(0.0, need_v[i] - imports_received[i]) + exports_used[i]
        for i in range(5)
    ]

    result = PayabilityResult(
        payable_direct=bool(payable_direct),
        payable_after_trades=bool(payable_after_trades),
        short=tuple(short),
        surplus=tuple(surplus),
        trade_rates=tuple(rates),
        trades_needed=float(trades_needed),
        trades_available=float(trades_available),
        imports_received=tuple(imports_received),
        exports_used=tuple(exports_used),
        required_pretrade_hand=tuple(required_pretrade),
        continuous_trading=bool(continuous),
    )

    return result.as_dict()


# ──────────────────────────────────────────────────────────────────────────────
# Probability-aware confidence
# ──────────────────────────────────────────────────────────────────────────────

def _roll_count_for_confidence(turns: float, rolls_per_player_turn: int) -> int:
    """Use a conservative integer count of future dice-roll opportunities."""
    raw = max(0.0, float(turns)) * max(0, int(rolls_per_player_turn))
    nearest = round(raw)

    if abs(raw - nearest) < 1e-9:
        return int(nearest)

    return int(floor(raw + _EPS))


@lru_cache(maxsize=200_000)
def _probability_at_least_k_cached(n: int, p_key: int, k: int) -> float:
    p = p_key / 1_000_000.0

    if k <= 0:
        return 1.0
    if n <= 0:
        return 0.0
    if k > n:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0

    # Compute CDF up to k-1 using stable recurrence from P(X=0).
    # n is small enough in this use case, but this avoids repeated comb() calls.
    q = 1.0 - p
    pmf = q ** n
    cdf = pmf

    for x in range(1, k):
        pmf *= ((n - x + 1) / x) * (p / q)
        cdf += pmf

    return max(0.0, min(1.0, 1.0 - cdf))


def probability_at_least_k(n_rolls: float, p: float, k: int) -> float:
    """Approximate P(Binomial(n_rolls, p) >= k)."""
    n = int(max(0, round(n_rolls)))
    p_clamped = max(0.0, min(1.0, float(p)))
    p_key = int(round(p_clamped * 1_000_000))
    return _probability_at_least_k_cached(n, p_key, int(k))


def confidence_label(
    confidence: float,
    target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
) -> str:
    c = max(0.0, min(1.0, safe_float(confidence, 0.0)))

    if c + _EPS >= target:
        return "high"
    if c >= 0.70:
        return "medium"
    if c >= 0.40:
        return "low"

    return "very_low"


def estimate_confidence_for_requirement(
    current_hand: Sequence[Any],
    required_pretrade_hand: Sequence[Any],
    production_pips: Sequence[Any],
    turns: float,
    rolls_per_player_turn: int = EXPECTED_HAND_ROLLS_PER_PLAYER_TURN,
    *,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
) -> Dict[str, Any]:
    """
    Estimate probability of having the required pre-trade hand at time `turns`.

    Approximation:
        Each resource is treated as a binomial production process with
        p = aggregate_resource_pips / 36 over n future dice-roll opportunities.
    """
    hand = clean_vector(current_hand)
    required = clean_vector(required_pretrade_hand)
    pips = clean_vector(production_pips)
    n_rolls = _roll_count_for_confidence(turns, rolls_per_player_turn)

    per_resource: List[float] = []
    needed_produced: List[int] = []
    probabilities: List[float] = []

    for i in range(5):
        missing = max(0.0, required[i] - hand[i])
        needed_cards = int(ceil(missing - _EPS))
        needed_produced.append(max(0, needed_cards))

        p = true_probability_from_pips(pips[i])
        probabilities.append(p)

        if needed_cards <= 0:
            per_resource.append(1.0)
        else:
            per_resource.append(probability_at_least_k(n_rolls, p, needed_cards))

    active = [per_resource[i] for i in range(5) if needed_produced[i] > 0]

    if not active:
        joint = 1.0
        min_conf = 1.0
    else:
        joint = 1.0
        for value in active:
            joint *= max(0.0, min(1.0, value))
        min_conf = min(active)

    result = ConfidenceResult(
        confidence=float(joint),
        label=confidence_label(joint, confidence_target),
        min_resource_confidence=float(min_conf),
        joint_resource_confidence=float(joint),
        per_resource_confidence=tuple(per_resource),
        required_pretrade_hand=tuple(required),
        needed_produced_cards=tuple(needed_produced),
        n_rolls=int(n_rolls),
        production_probabilities=tuple(probabilities),
    )

    return result.as_dict()


def estimate_direct_confidence(
    current_hand: Sequence[Any],
    need: Sequence[Any],
    production_pips: Sequence[Any],
    turns: float,
    num_players: int = EXPECTED_HAND_ROLLS_PER_PLAYER_TURN,
    *,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
) -> Dict[str, Any]:
    """Confidence of paying directly without trades."""
    return estimate_confidence_for_requirement(
        current_hand=current_hand,
        required_pretrade_hand=need,
        production_pips=production_pips,
        turns=turns,
        rolls_per_player_turn=num_players,
        confidence_target=confidence_target,
    )


def estimate_payability_confidence(
    current_hand: Sequence[Any],
    need: Sequence[Any],
    production_pips: Sequence[Any],
    turns: float,
    num_players: int,
    payability: Mapping[str, Any],
    *,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
) -> Dict[str, Any]:
    """
    Confidence for the affordability route implied by payability.

    If direct payment is possible, this is direct confidence. If trades are
    needed, confidence is based on the required pre-trade hand implied by the
    trade plan.
    """
    required = payability.get("required_pretrade_hand", need)

    return estimate_confidence_for_requirement(
        current_hand=current_hand,
        required_pretrade_hand=required,
        production_pips=production_pips,
        turns=turns,
        rolls_per_player_turn=num_players,
        confidence_target=confidence_target,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Turns-to-afford estimators
# ──────────────────────────────────────────────────────────────────────────────

def estimate_first_payable_turn(
    current_hand: Sequence[Any],
    production_pips: Sequence[Any],
    need: Sequence[Any],
    trade_rates: Sequence[Any],
    *,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    num_players: int = EXPECTED_HAND_ROLLS_PER_PLAYER_TURN,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
) -> Dict[str, Any]:
    """
    Search for the first own-turn horizon where the action is payable.

    The search intentionally mirrors the validation plan:
        t = 0.0, 0.25, 0.50, 0.75, ...

    Zero-turn shortcut:
        Before future timing, check whether the current real hand can already
        pay the full action cost after legal whole bank/port trades. If yes,
        return turns=0.0 and confidence=1.0.
    """
    hand = clean_vector(current_hand)
    pips = clean_vector(production_pips)
    need_v = clean_vector(need)
    rates = clean_int_vector(trade_rates, default=4)

    step = max(0.01, float(step))
    max_turns = max(0.0, float(max_turns))
    confidence_target = float(confidence_target)

    # Exact/current-hand zero-turn shortcut. Use integer trades, not continuous.
    zero_payability = compute_payability_with_trades(
        hand,
        need_v,
        rates,
        continuous=False,
    )

    zero_payable = bool(zero_payability.get("payable_direct", False)) or bool(
        zero_payability.get("payable_after_trades", False)
    )

    if zero_payable:
        confidence_info = {
            "confidence": 1.0,
            "label": "exact",
            "min_resource_confidence": 1.0,
            "joint_resource_confidence": 1.0,
            "per_resource_confidence": (1.0, 1.0, 1.0, 1.0, 1.0),
            "required_pretrade_hand": tuple(zero_payability.get("required_pretrade_hand", need_v)),
            "needed_produced_cards": (0, 0, 0, 0, 0),
            "n_rolls": 0,
            "production_probabilities": tuple(true_probability_from_pips(pips[i]) for i in range(5)),
            "reason": "current_hand_payable_now_exact_integer_trades",
        }

        return {
            "turns": 0.0,
            "found": True,
            "confidence": 1.0,
            "confidence_target": confidence_target,
            "confidence_label": "exact",
            "expected_hand": tuple(hand),
            "current_hand": tuple(hand),
            "production_pips": tuple(pips),
            "need": tuple(need_v),
            "trade_rates": tuple(rates),
            "payability": zero_payability,
            "confidence_info": confidence_info,
            "zero_turn_shortcut": True,
            "zero_turn_reason": "current_hand_payable_now_exact_integer_trades",
        }

    iterations = int(ceil(max_turns / step)) + 1
    last_info: Dict[str, Any] = {}

    for idx in range(iterations + 1):
        turns = min(max_turns, round(idx * step, 10))

        expected_hand = estimate_expected_hand_after_turns(
            hand,
            pips,
            turns,
            num_players,
        )

        payability = compute_payability_with_trades(
            expected_hand,
            need_v,
            rates,
            continuous=continuous_trading,
        )

        confidence_info = estimate_payability_confidence(
            hand,
            need_v,
            pips,
            turns,
            num_players,
            payability,
            confidence_target=confidence_target,
        )

        confidence = safe_float(confidence_info.get("confidence"), 0.0)
        payable = bool(payability.get("payable_after_trades", False))
        confident_enough = confidence + _EPS >= confidence_target

        last_info = {
            "turns": float(turns),
            "found": bool(payable and (confident_enough or not require_confidence)),
            "confidence": float(confidence),
            "confidence_target": confidence_target,
            "confidence_label": confidence_info.get(
                "label",
                confidence_label(confidence, confidence_target),
            ),
            "expected_hand": tuple(expected_hand),
            "current_hand": tuple(hand),
            "production_pips": tuple(pips),
            "need": tuple(need_v),
            "trade_rates": tuple(rates),
            "payability": payability,
            "confidence_info": confidence_info,
            "zero_turn_shortcut": False,
        }

        if last_info["found"]:
            return last_info

        if turns >= max_turns - _EPS:
            break

    expected_hand = estimate_expected_hand_after_turns(
        hand,
        pips,
        max_turns,
        num_players,
    )

    payability = compute_payability_with_trades(
        expected_hand,
        need_v,
        rates,
        continuous=continuous_trading,
    )

    confidence_info = estimate_payability_confidence(
        hand,
        need_v,
        pips,
        max_turns,
        num_players,
        payability,
        confidence_target=confidence_target,
    )

    return {
        "turns": INFINITE_TURNS,
        "found": False,
        "confidence": safe_float(confidence_info.get("confidence"), 0.0),
        "confidence_target": confidence_target,
        "confidence_label": confidence_info.get("label", "very_low"),
        "expected_hand": tuple(expected_hand),
        "current_hand": tuple(hand),
        "production_pips": tuple(pips),
        "need": tuple(need_v),
        "trade_rates": tuple(rates),
        "payability": payability,
        "confidence_info": confidence_info,
        "last_checked": last_info,
        "zero_turn_shortcut": False,
    }


def estimate_action_time(
    board: Any,
    player: Any,
    target_type: str,
    *,
    target_id: Optional[int] = None,
    vertices: Optional[Sequence[int]] = None,
    current_hand: Optional[Sequence[Any]] = None,
    production_pips: Optional[Sequence[Any]] = None,
    trade_rates: Optional[Sequence[Any]] = None,
    ports: Optional[Iterable[str]] = None,
    player_ports: Optional[Mapping[Any, Any]] = None,
    extra_roads_needed: int = 0,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    current_turn: Optional[int] = None,
    target_player_id: Optional[int] = None,
    num_players: Optional[int] = None,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
) -> Dict[str, Any]:
    """
    Estimate own turns until `player` can afford one target action.

    This function does not check board legality. It only estimates resource
    timing. Exact guards should still validate the real action before execution.
    """
    normalized = normalize_target_type(
        target_type,
        extra_roads_needed=extra_roads_needed,
    )
    need = target_cost_vector(normalized, extra_roads_needed=extra_roads_needed)

    if current_hand is None:
        current_hand = get_player_resource_cards_vector(player)
    hand = clean_vector(current_hand)

    if production_pips is None:
        if vertices is not None:
            production_pips = production_pips_from_vertices_game_order(board, vertices)
        else:
            production_pips = get_player_production_pips(board, player)
    pips = clean_vector(production_pips)

    if num_players is None:
        game = getattr(player, "game", None)
        players = getattr(game, "players", None)
        try:
            num_players = max(1, len(players))
        except Exception:
            num_players = EXPECTED_HAND_ROLLS_PER_PLAYER_TURN

    if trade_rates is None:
        if player_ports is not None:
            trade_rates = trade_rates_from_markov_ports(player_ports)
        elif ports is not None:
            trade_rates = get_trade_rates_from_ports(ports)
        else:
            trade_rates = get_player_trade_rates(board, player)
    rates = clean_int_vector(trade_rates, default=4)

    first = estimate_first_payable_turn(
        current_hand=hand,
        production_pips=pips,
        need=need,
        trade_rates=rates,
        confidence_target=confidence_target,
        num_players=int(num_players),
        step=step,
        max_turns=max_turns,
        continuous_trading=continuous_trading,
        require_confidence=require_confidence,
    )

    turns = finite_or_9999(first.get("turns"))
    found = bool(first.get("found", False))
    confidence = safe_float(first.get("confidence"), 0.0)

    estimate = ActionTimeEstimate(
        action=normalized,
        target_type=normalized,
        target_id=target_id,
        extra_roads_needed=int(extra_roads_needed),
        turns=float(turns),
        found=found,
        confidence=float(confidence),
        confidence_target=float(confidence_target),
        confidence_label=str(first.get("confidence_label", confidence_label(confidence, confidence_target))),
        expected_hand=tuple(clean_vector(first.get("expected_hand", ZERO_VECTOR))),
        current_hand=tuple(hand),
        production_pips=tuple(pips),
        need=tuple(need),
        trade_rates=tuple(rates),
        payability=dict(first.get("payability", {})),
        confidence_info=dict(first.get("confidence_info", {})),
        explanation={
            "resource_order": RESOURCE_NAMES,
            "estimator": "expected_hand_probability_aware",
            "confidence_required": bool(require_confidence),
            "step": float(step),
            "max_turns": float(max_turns),
            "num_players": int(num_players),
            "continuous_trading": bool(continuous_trading),
            "vertices": list(vertices) if vertices is not None else player_production_vertices(player),
            "raw_first_payable": first,
        },
    )

    return estimate.as_dict()


# ──────────────────────────────────────────────────────────────────────────────
# Fast-forward style event maps
# ──────────────────────────────────────────────────────────────────────────────

def default_action_specs_for_player(player: Any) -> List[Dict[str, Any]]:
    """
    Lightweight default resource targets for execution-phase timing.

    These are not full legal action candidates; they are high-level event-time
    targets used by fast-forward style planning.
    """
    specs: List[Dict[str, Any]] = []

    specs.append({"activity": "settlement_0r", "target_type": "settlement_0r", "extra_roads_needed": 0})
    specs.append({"activity": "new_settlement", "target_type": "settlement_1r", "extra_roads_needed": 1})
    specs.append({"activity": "settlement_2r", "target_type": "settlement_2r", "extra_roads_needed": 2})

    if len(getattr(player, "cities", []) or []) < 4:
        specs.append({"activity": "upgrade_to_city", "target_type": "city"})

    specs.append({"activity": "buy_discovery_card", "target_type": "dev_card"})

    return specs


def rank_action_times_for_player(
    board: Any,
    player: Any,
    action_specs: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    current_turn: Optional[int] = None,
    target_player_id: Optional[int] = None,
    num_players: Optional[int] = None,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
) -> List[Dict[str, Any]]:
    """Return action time estimates sorted by fastest expected-hand turns."""
    specs = list(action_specs or default_action_specs_for_player(player))
    rows: List[Dict[str, Any]] = []

    # Shared extraction keeps this function cheap for multiple targets.
    hand = get_player_resource_cards_vector(player)
    pips = get_player_production_pips(board, player)
    rates = get_player_trade_rates(board, player)

    for spec in specs:
        target_type = str(spec.get("target_type", spec.get("activity", "")))
        extra_roads_needed = safe_int(spec.get("extra_roads_needed", 0), 0)

        estimate = estimate_action_time(
            board,
            player,
            target_type,
            target_id=spec.get("target_id"),
            vertices=spec.get("vertices"),
            current_hand=spec.get("current_hand", hand),
            production_pips=spec.get("production_pips", pips),
            trade_rates=spec.get("trade_rates", rates),
            extra_roads_needed=extra_roads_needed,
            confidence_target=confidence_target,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=continuous_trading,
            require_confidence=require_confidence,
        )

        estimate["activity"] = str(spec.get("activity", estimate["target_type"]))
        estimate["description"] = spec.get("description", estimate["activity"])
        estimate["metadata"] = dict(spec.get("metadata", {}))
        rows.append(estimate)

    rows.sort(
        key=lambda r: (
            not bool(r.get("found", False)),
            finite_or_9999(r.get("turns")),
            -safe_float(r.get("confidence"), 0.0),
            str(r.get("activity", "")),
        )
    )

    return rows


def estimate_event_times_for_player(
    board: Any,
    player: Any,
    *,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    current_turn: Optional[int] = None,
    target_player_id: Optional[int] = None,
    num_players: Optional[int] = None,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
    include_debug: bool = True,
) -> Dict[str, Any]:
    """
    Return fast-forward style event times for one player.

    Keys are intentionally aligned with common requested_activity names:
        new_settlement
        upgrade_to_city
        buy_discovery_card
    """
    specs = [
        {"activity": "new_settlement", "target_type": "settlement_1r", "extra_roads_needed": 1},
        {"activity": "upgrade_to_city", "target_type": "city"},
        {"activity": "buy_discovery_card", "target_type": "dev_card"},
    ]

    rows = rank_action_times_for_player(
        board,
        player,
        specs,
        confidence_target=confidence_target,
        num_players=num_players,
        step=step,
        max_turns=max_turns,
        continuous_trading=continuous_trading,
        require_confidence=require_confidence,
    )

    out: Dict[str, Any] = {}
    debug: Dict[str, Any] = {}

    for row in rows:
        activity = str(row.get("activity", row.get("target_type", "")))
        out[activity] = finite_or_9999(row.get("turns"))
        debug[activity] = row

    if include_debug:
        out["__debug__"] = debug

    return out



# ──────────────────────────────────────────────────────────────────────────────
# Build-plan helpers for outlook / execution-phase forecasting
# ──────────────────────────────────────────────────────────────────────────────

def canonical_road_id_list(road: Any) -> Optional[List[int]]:
    """
    Return a canonical JSON-friendly road_id list.

    Convention:
        road_id = [min_intersection_id, max_intersection_id]

    This is deliberately different from a directed path step, where direction
    matters and the first item may be greater than the second.
    """
    try:
        a, b = tuple(road)
        a_i = int(a)
        b_i = int(b)
    except Exception:
        return None

    if a_i == b_i:
        return None

    return [min(a_i, b_i), max(a_i, b_i)]


def canonical_road_id_lists(roads: Optional[Iterable[Any]]) -> List[List[int]]:
    """Normalize and deduplicate road IDs while keeping deterministic ordering."""
    unique = set()

    for road in roads or []:
        road_id = canonical_road_id_list(road)
        if road_id is None:
            continue
        unique.add((road_id[0], road_id[1]))

    return [[a, b] for a, b in sorted(unique)]



def _player_owned_canonical_roads(player: Any) -> set[tuple[int, int]]:
    """Return canonical road IDs currently recorded on the player."""
    owned: set[tuple[int, int]] = set()
    for road in getattr(player, "roads", []) or []:
        rid = canonical_road_id_list(road)
        if rid is not None:
            owned.add((rid[0], rid[1]))
    return owned


def _board_road_owned_by_player(board: Any, player: Any, road_id: Any) -> bool:
    """Return True when the physical board road is already owned by this player."""
    target = canonical_road_id_list(road_id)
    if target is None:
        return False

    colors = {getattr(player, "color", None), getattr(player, "color2", None)}
    colors.discard(None)
    colors.discard("")

    for road in getattr(board, "roads", []) or []:
        if road is None:
            continue
        rid = canonical_road_id_list(getattr(road, "id", None))
        if rid != target:
            continue
        if getattr(road, "color", None) in colors and getattr(road, "occupied_tf", False):
            return True

    # Fallback to player.roads when board state is stale or loaded from older saves.
    return (target[0], target[1]) in _player_owned_canonical_roads(player)


def round_expected_turns_to_player_slot(
    raw_turns: Any,
    *,
    current_turn: Optional[int],
    target_player_id: Optional[int],
    num_players: Optional[int] = None,
) -> float:
    """
    Round an EH estimate to the next actual turn slot for the target player.

    Convention:
        raw_turns is an expected number of global player-turns from now.
        The returned value is an integer number of global player-turns from now
        when the target player can actually act.

    Examples for four players:
        current_turn=1, target_player_id=1, raw=6.25 -> 8
        current_turn=1, target_player_id=2, raw=6.25 -> 9

    The raw estimate is preserved separately by callers as expected_turns_raw.
    """
    try:
        turns = float(raw_turns)
    except Exception:
        return INFINITE_TURNS

    if not isfinite(turns) or turns >= INFINITE_TURNS:
        return INFINITE_TURNS

    n_players = int(num_players or NUM_PLAYERS or 4)
    if n_players <= 1:
        return float(max(0, ceil(turns)))

    try:
        current = int(current_turn) if current_turn is not None else None
        target = int(target_player_id) if target_player_id is not None else None
    except Exception:
        current = None
        target = None

    min_turns = int(max(0, ceil(turns)))

    if current is None or target is None:
        # No turn context available: return the next full cycle boundary.
        if min_turns == 0:
            return 0.0
        return float(int(ceil(min_turns / n_players) * n_players))

    wait_to_target = (target - current) % n_players

    if min_turns == 0:
        return float(wait_to_target)

    rounded = min_turns
    while rounded % n_players != wait_to_target:
        rounded += 1

    return float(rounded)


def estimate_turns_to_reach_road_in_path(
    board: Any,
    player: Any,
    *,
    path: Iterable[Any],
    contested_road_id: Any,
    current_turn: Optional[int] = None,
    target_player_id: Optional[int] = None,
    num_players: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Estimate when a player can build/reach one contested road in a directed path.

    A road's timing depends on its position in that player's path. If the road is
    the second road_in_path, the player must afford all unbuilt roads up to and
    including that road. Existing own roads on the path cost zero.
    """
    target = canonical_road_id_list(contested_road_id)
    if target is None:
        return {
            "found": False,
            "turns": INFINITE_TURNS,
            "expected_turns_raw": INFINITE_TURNS,
            "expected_turns": INFINITE_TURNS,
            "road_id": contested_road_id,
            "road_index": None,
            "roads_to_build_until_road": [],
            "path_until_road": [],
        }

    path_steps: List[List[int]] = []
    roads_to_build_until_road: List[List[int]] = []
    road_index: Optional[int] = None

    for idx, step in enumerate(path or [], start=1):
        try:
            a, b = tuple(step)
            directed_step = [int(a), int(b)]
        except Exception:
            continue

        step_road_id = canonical_road_id_list(directed_step)
        if step_road_id is None:
            continue

        path_steps.append(directed_step)

        if not _board_road_owned_by_player(board, player, step_road_id):
            roads_to_build_until_road.append(step_road_id)

        if step_road_id == target:
            road_index = idx
            break

    if road_index is None:
        return {
            "found": False,
            "turns": INFINITE_TURNS,
            "expected_turns_raw": INFINITE_TURNS,
            "expected_turns": INFINITE_TURNS,
            "road_id": target,
            "road_index": None,
            "roads_to_build_until_road": [],
            "path_until_road": path_steps,
        }

    estimate = estimate_turns_to_afford_build_plan(
        board=board,
        player=player,
        settlement_id=None,
        roads_to_build=roads_to_build_until_road,
        target_type="road",
        current_turn=current_turn,
        target_player_id=target_player_id,
        num_players=num_players,
        **kwargs,
    )

    estimate["road_id"] = target
    estimate["road_index"] = road_index
    estimate["path_until_road"] = path_steps
    estimate["roads_to_build_until_road"] = roads_to_build_until_road
    estimate["road_count_until_road"] = len(roads_to_build_until_road)

    return estimate


def estimate_turns_to_afford_build_plan(
    board: Any,
    player: Any,
    *,
    settlement_id: Optional[int] = None,
    roads_to_build: Optional[Iterable[Any]] = None,
    target_type: str = "settlement",
    current_hand: Optional[Sequence[Any]] = None,
    production_pips: Optional[Sequence[Any]] = None,
    trade_rates: Optional[Sequence[Any]] = None,
    confidence_target: float = EXPECTED_HAND_CONFIDENCE_TARGET,
    current_turn: Optional[int] = None,
    target_player_id: Optional[int] = None,
    num_players: Optional[int] = None,
    step: float = EXPECTED_HAND_STEP,
    max_turns: float = EXPECTED_HAND_MAX_TURNS,
    continuous_trading: bool = EXPECTED_HAND_CONTINUOUS_TRADING,
    require_confidence: bool = EXPECTED_HAND_REQUIRE_CONFIDENCE,
) -> Dict[str, Any]:
    """
    Estimate expected own turns until a concrete build plan is affordable.

    This is the generic execution/outlook version of EH. It does not score a
    hypothetical production vertex. Instead it uses the player's current hand,
    current settlements/cities, and current trade rates.

    Args:
        settlement_id:
            Optional target intersection. Used for diagnostics/UI only.

        roads_to_build:
            Canonical road IDs or road-like pairs that still need to be built.
            The number of roads determines the extra road cost.

        target_type:
            Usually "settlement". Use "city" or "dev_card" for other plans.

    Returns:
        A dictionary returned by estimate_action_time(...), enriched with a
        JSON-friendly build_plan block.
    """
    roads = canonical_road_id_lists(roads_to_build)
    road_count = len(roads)

    target_kind = str(target_type or "").strip().lower()

    if target_kind in (
        "settlement",
        "next_settlement",
        "new_settlement",
        "build_settlement",
        "",
    ):
        normalized_target_type = f"settlement_{road_count}r"
        extra_roads_needed = road_count
    elif "road" in target_kind:
        normalized_target_type = f"road_{road_count}r"
        extra_roads_needed = road_count
    else:
        normalized_target_type = target_type
        extra_roads_needed = road_count

    estimate = estimate_action_time(
        board=board,
        player=player,
        target_type=normalized_target_type,
        target_id=settlement_id,
        current_hand=current_hand,
        production_pips=production_pips,
        trade_rates=trade_rates,
        extra_roads_needed=extra_roads_needed,
        confidence_target=confidence_target,
        num_players=num_players,
        step=step,
        max_turns=max_turns,
        continuous_trading=continuous_trading,
        require_confidence=require_confidence,
    )

    estimate["build_plan"] = {
        "settlement_id": settlement_id,
        "roads_to_build": roads,
        "road_count": road_count,
        "target_type": normalized_target_type,
    }
    raw_turns = estimate.get("turns", INFINITE_TURNS)
    estimate["expected_turns_raw"] = raw_turns
    estimate["expected_turns"] = round_expected_turns_to_player_slot(
        raw_turns,
        current_turn=current_turn,
        target_player_id=target_player_id or getattr(player, "id", None),
        num_players=num_players,
    )

    return estimate


def estimate_next_settlement_target(
    board: Any,
    player: Any,
    settlement_id: int,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Estimate turns for a next settlement: settlement cost only, no roads."""
    return estimate_turns_to_afford_build_plan(
        board=board,
        player=player,
        settlement_id=int(settlement_id),
        roads_to_build=[],
        target_type="settlement",
        **kwargs,
    )


def estimate_new_settlement_target(
    board: Any,
    player: Any,
    settlement_id: int,
    roads_to_build: Optional[Iterable[Any]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Estimate turns for a new settlement: settlement + required road costs."""
    return estimate_turns_to_afford_build_plan(
        board=board,
        player=player,
        settlement_id=int(settlement_id),
        roads_to_build=roads_to_build,
        target_type="settlement",
        **kwargs,
    )


def annotate_outlook_with_expected_hand(
    board: Any,
    player: Any,
    outlook: Any,
    **kwargs: Any,
) -> Any:
    """
    Attach EH timing estimates to an Outlook object.

    Expected outlook fields:
        outlook.next_settlements = [28, 39, ...]
        outlook.new_settlement_paths = [
            {
                "intersection_id": 44,
                "path": [[24, 25], [25, 36], [36, 44]],
                "roads_to_build": [[24, 25], [25, 36], [36, 44]],
                "distance": 3,
            },
            ...
        ]

    Output fields:
        outlook.next_settlement_plans = [dict, ...]
        outlook.new_settlement_paths entries gain:
            - road_count
            - expected_turns
            - confidence
            - confidence_label
            - found
            - eh_estimate

    The function mutates and returns outlook for convenience.
    """
    next_plans: List[Dict[str, Any]] = []

    for inter_id in getattr(outlook, "next_settlements", []) or []:
        try:
            target_id = int(inter_id)
        except Exception:
            continue

        estimate = estimate_next_settlement_target(
            board=board,
            player=player,
            settlement_id=target_id,
            **kwargs,
        )

        next_plans.append(
            {
                "intersection_id": target_id,
                "path": [],
                "roads_to_build": [],
                "distance": 0,
                "road_count": 0,
                "expected_turns_raw": estimate.get("expected_turns_raw", estimate.get("turns", INFINITE_TURNS)),
                "expected_turns": estimate.get("expected_turns", estimate.get("turns", INFINITE_TURNS)),
                "confidence": estimate.get("confidence", 0.0),
                "confidence_label": estimate.get("confidence_label", ""),
                "found": bool(estimate.get("found", False)),
                "eh_estimate": estimate,
            }
        )

    enriched_new_paths: List[Dict[str, Any]] = []

    for record in getattr(outlook, "new_settlement_paths", []) or []:
        if not isinstance(record, Mapping):
            continue

        enriched = dict(record)

        try:
            target_id = int(enriched.get("intersection_id"))
        except Exception:
            continue

        roads = canonical_road_id_lists(enriched.get("roads_to_build", []) or [])
        estimate = estimate_new_settlement_target(
            board=board,
            player=player,
            settlement_id=target_id,
            roads_to_build=roads,
            **kwargs,
        )

        enriched["roads_to_build"] = roads
        enriched["road_count"] = len(roads)
        enriched["expected_turns_raw"] = estimate.get("expected_turns_raw", estimate.get("turns", INFINITE_TURNS))
        enriched["expected_turns"] = estimate.get("expected_turns", estimate.get("turns", INFINITE_TURNS))
        enriched["confidence"] = estimate.get("confidence", 0.0)
        enriched["confidence_label"] = estimate.get("confidence_label", "")
        enriched["found"] = bool(estimate.get("found", False))
        enriched["eh_estimate"] = estimate

        enriched_new_paths.append(enriched)

    setattr(outlook, "next_settlement_plans", next_plans)
    setattr(outlook, "new_settlement_paths", enriched_new_paths)

    return outlook

# ──────────────────────────────────────────────────────────────────────────────
# Markov / EH comparison helpers
# ──────────────────────────────────────────────────────────────────────────────

def compare_event_time_maps(
    markov_event_times: Mapping[str, Any],
    expected_hand_event_times: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Build a side-by-side comparison table for logs/diagnostics."""
    keys = sorted(
        set(k for k in markov_event_times.keys() if not str(k).startswith("__"))
        | set(k for k in expected_hand_event_times.keys() if not str(k).startswith("__"))
    )

    eh_debug = expected_hand_event_times.get("__debug__", {}) if isinstance(expected_hand_event_times, Mapping) else {}
    comparison: Dict[str, Dict[str, Any]] = {}

    for key in keys:
        markov_turns = finite_or_9999(markov_event_times.get(key, INFINITE_TURNS))
        eh_turns = finite_or_9999(expected_hand_event_times.get(key, INFINITE_TURNS))
        debug = dict(eh_debug.get(key, {}) or {}) if isinstance(eh_debug, Mapping) else {}

        comparison[key] = {
            "activity": key,
            "markov_turns": markov_turns,
            "expected_hand_turns": eh_turns,
            "delta_expected_minus_markov": (
                eh_turns - markov_turns
                if markov_turns < INFINITE_TURNS and eh_turns < INFINITE_TURNS
                else None
            ),
            "expected_hand_confidence": safe_float(debug.get("confidence"), 0.0),
            "expected_hand_confidence_label": debug.get("confidence_label"),
            "expected_hand_found": bool(debug.get("found", eh_turns < INFINITE_TURNS)),
            "expected_hand_debug": debug,
        }

    return comparison


def flatten_event_time_comparison(
    comparison: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert compare_event_time_maps(...) output to sortable row dictionaries."""
    rows = [dict(value) for value in comparison.values()]
    rows.sort(
        key=lambda r: (
            finite_or_9999(r.get("expected_hand_turns")),
            finite_or_9999(r.get("markov_turns")),
            str(r.get("activity", "")),
        )
    )
    return rows


__all__ = [
    "ActionTimeEstimate",
    "ConfidenceResult",
    "PayabilityResult",
    "EXPECTED_HAND_CONFIDENCE_TARGET",
    "EXPECTED_HAND_MAX_TURNS",
    "EXPECTED_HAND_STEP",
    "EXPECTED_HAND_CONTINUOUS_TRADING",
    "EXPECTED_HAND_REQUIRE_CONFIDENCE",
    "EXPECTED_HAND_ROLLS_PER_PLAYER_TURN",
    "EXPECTED_HAND_TARGET_EXTRA_ROADS",
    "INFINITE_TURNS",
    "RESOURCE_NAMES",
    "ZERO_VECTOR",
    "clean_vector",
    "clean_int_vector",
    "canonical_road_id_list",
    "canonical_road_id_lists",
    "round_expected_turns_to_player_slot",
    "estimate_turns_to_reach_road_in_path",
    "estimate_turns_to_afford_build_plan",
    "estimate_next_settlement_target",
    "estimate_new_settlement_target",
    "annotate_outlook_with_expected_hand",
    "compare_event_time_maps",
    "compute_payability_with_trades",
    "confidence_label",
    "default_action_specs_for_player",
    "estimate_action_time",
    "estimate_confidence_for_requirement",
    "estimate_direct_confidence",
    "estimate_event_times_for_player",
    "estimate_expected_hand_after_turns",
    "estimate_first_payable_turn",
    "estimate_initial_placement_candidate_time",
    "estimate_payability_confidence",
    "finite_or_9999",
    "flatten_event_time_comparison",
    "get_intersection_resource_pips",
    "get_player_ports",
    "get_player_production_pips",
    "get_player_resource_cards_vector",
    "get_player_trade_rates",
    "get_trade_rates_from_ports",
    "initial_resources_from_intersection",
    "normalize_port_type",
    "normalize_target_type",
    "normalize_trade_rates",
    "pips_from_dice_value",
    "player_production_vertices",
    "probability_at_least_k",
    "production_pips_from_vertices_game_order",
    "rank_action_times_for_player",
    "resource_index_from_name",
    "resource_index_from_port",
    "safe_float",
    "safe_int",
    "target_cost_vector",
    "trade_rates_after_candidate",
    "trade_rates_from_markov_ports",
    "true_probability_from_pips",
    "vector_add",
    "vector_sub",
    "vector_sum",
    "vector_to_named_dict",
]
