"""
core/viable_action_scanner.py

Current-state legal/available action scanner for the Catan execution phase.

Design goal
-----------
This module answers only this question:

    Which action categories are currently legal/available for the acting player?

It deliberately does NOT choose the best action and does NOT project future states.
Use action_planner.py / a later project_action() layer for:

    current -> after TwB -> scan again
    current -> after YoP -> scan again
    current -> after accepted TwP -> scan again

Conventions
-----------
Resource vectors use the existing project order:

    [Wheat, Ore, Wood, Brick, Sheep]

The scanner returns both:

    - action_mask: compact 0/1 vector for algorithms
    - candidates: richer target/action variants for execution/planning/debugging
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations_with_replacement
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from core.constants import (
        RCARDS_FOR_CITY,
        RCARDS_FOR_DCARD,
        RCARDS_FOR_ROAD,
        RCARDS_FOR_SETTLEMENT,
        ResourceCard,
    )
except Exception:  # pragma: no cover - lets editors import this file outside the project.
    RCARDS_FOR_CITY = [2, 3, 0, 0, 0]
    RCARDS_FOR_SETTLEMENT = [1, 0, 1, 1, 1]
    RCARDS_FOR_ROAD = [0, 0, 1, 1, 0]
    RCARDS_FOR_DCARD = [1, 1, 0, 0, 1]

    class ResourceCard:  # type: ignore[no-redef]
        WHEAT = "Wheat"
        ORE = "Ore"
        WOOD = "Wood"
        BRICK = "Brick"
        SHEEP = "Sheep"


try:
    from core.player_trade import make_twp_offer_candidates  # type: ignore
except Exception:  # pragma: no cover - TwP planner is optional during staged development.
    make_twp_offer_candidates = None  # type: ignore[assignment]


# ──────────────────────────────────────────────────────────────────────────────
# Stable action names / vector layout
# ──────────────────────────────────────────────────────────────────────────────

TWP_MAKE_OFFER = "TwP - Make offer"
TWP_ACCEPT_OFFER = "TwP - Accept offer"
TWP_DECLINE_OFFER = "TwP - Decline offer"
TWP_CANCEL_OFFER = "TwP - Cancel offer"
TWP_CONFIRM_DEAL = "TwP - Confirm deal"
TWP_PROPOSE_COUNTER = "TwP - Propose counter offer"
TWP_ACCEPT_COUNTER = "TwP - Accept counter offer"
TWB = "TwB"
BUY_DCARD = "Buy development_card"
BUILD_CITY = "Build city"
BUILD_SETTLEMENT = "Build settlement"
BUILD_ROAD = "Build road"
PLAY_KNIGHT = "Play dcard Knight"
PLAY_YOP = "Play dcard Year_of_Plenty"
PLAY_TWO_FREE_ROADS = "Play dcard Two_Free_Roads"
PLAY_MONOPOLY = "Play dcard Monopoly"
ROLL_DICE = "Roll Dices"
DISCARD_RCARDS = "Discard resource_cards"
STEAL_SELECT_OPPONENT = "Steal - Select Opponent"
STEAL_PICK_RCARD = "Steal - Pick rcard"
REMOVE_ROBBER = "Remove robber"
MOVE_ROBBER = "Move robber"

ACTION_NAMES: Tuple[str, ...] = (
    TWP_MAKE_OFFER,
    TWP_ACCEPT_OFFER,
    TWP_DECLINE_OFFER,
    TWP_CANCEL_OFFER,
    TWP_CONFIRM_DEAL,
    TWP_PROPOSE_COUNTER,
    TWP_ACCEPT_COUNTER,
    TWB,
    BUY_DCARD,
    BUILD_CITY,
    BUILD_SETTLEMENT,
    BUILD_ROAD,
    PLAY_KNIGHT,
    PLAY_YOP,
    PLAY_TWO_FREE_ROADS,
    PLAY_MONOPOLY,
    ROLL_DICE,
    DISCARD_RCARDS,
    STEAL_SELECT_OPPONENT,
    STEAL_PICK_RCARD,
    REMOVE_ROBBER,
    MOVE_ROBBER,
)

ACTION_INDEX: Dict[str, int] = {name: idx for idx, name in enumerate(ACTION_NAMES)}

RESOURCE_NAMES: Tuple[str, str, str, str, str] = (
    "Wheat",
    "Ore",
    "Wood",
    "Brick",
    "Sheep",
)

# Conservative physical piece limits. If you track these somewhere else later,
# pass them into scanning_viable_actions(...).
DEFAULT_MAX_SETTLEMENTS = 5
DEFAULT_MAX_CITIES = 4
DEFAULT_MAX_ROADS = 15


# ──────────────────────────────────────────────────────────────────────────────
# Data containers
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ViableActionScan:
    """Result of scanning the current state for viable action categories."""

    player_id: Optional[int]
    player_color: str
    round_num: Optional[int]
    turn: Optional[int]
    phase: str
    state: str
    dice_value: int
    forced_action_mode: Optional[str]

    action_mask: List[int]
    action_flags: Dict[str, bool]
    candidates: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    blockers: Dict[str, List[str]] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def viable_actions(self) -> List[str]:
        return [name for name in ACTION_NAMES if self.action_flags.get(name, False)]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def scanning_viable_actions(
    game: Any,
    player: Optional[Any] = None,
    *,
    board: Optional[Any] = None,
    include_candidates: bool = True,
    enforce_forced_action_lock: bool = True,
    allow_actions_before_roll: bool = False,
    max_settlement_candidates: int = 80,
    max_road_candidates: int = 160,
    max_bank_trade_candidates: int = 80,
    max_yop_candidates: int = 15,
    max_piece_settlements: int = DEFAULT_MAX_SETTLEMENTS,
    max_piece_cities: int = DEFAULT_MAX_CITIES,
    max_piece_roads: int = DEFAULT_MAX_ROADS,
) -> ViableActionScan:
    """
    Scan the current game state and return currently viable action categories.

    This is a legality/availability scan, not a strategic evaluator.

    Parameters
    ----------
    game:
        Game object.
    player:
        Acting player. If omitted, uses game.current_player, then game.turn.
    board:
        Board object. If omitted, uses game.board.
    include_candidates:
        If True, include concrete candidate targets/trades where cheap enough.
    enforce_forced_action_lock:
        If True, forced states such as discard/robber/steal/roll dice suppress
        normal build/trade/dcard actions.
    allow_actions_before_roll:
        If False, execution-turn state with dice_value == 0 exposes only Roll Dices.
    max_*:
        Safety caps for candidate list sizes.

    Returns
    -------
    ViableActionScan
        Contains action_mask, action_flags, candidates, blockers, context, notes.
    """

    board = board if board is not None else getattr(game, "board", None)
    player = _resolve_player(game, player)
    turn_details = _get_turn_details(game)

    flags: Dict[str, bool] = {name: False for name in ACTION_NAMES}
    candidates: Dict[str, List[Dict[str, Any]]] = {name: [] for name in ACTION_NAMES}
    blockers: Dict[str, List[str]] = {name: [] for name in ACTION_NAMES}
    notes: List[str] = []

    round_num = _safe_int_or_none(getattr(game, "round", None))
    turn = _safe_int_or_none(getattr(game, "turn", None))
    phase = str(getattr(game, "phase", ""))
    state = str(getattr(game, "state", ""))
    dice_value = _get_dice_value(game, turn_details)

    player_id = _safe_int_or_none(getattr(player, "id", None)) if player is not None else None
    player_color = str(getattr(player, "color", "")) if player is not None else ""

    hand = _get_rcards_vector(player)
    trade_rates = _get_trade_rates_vector(player, game=game)
    trade_counts = [hand[i] // max(1, trade_rates[i]) for i in range(5)]
    total_rcards = int(sum(hand))

    context: Dict[str, Any] = {
        "hand": hand,
        "resource_order": list(RESOURCE_NAMES),
        "trade_rates": trade_rates,
        "trade_counts": trade_counts,
        "total_rcards": total_rcards,
        "dcards_stack_count": _dcard_stack_count(game),
        "dcard_counts": _all_playable_dcard_counts(player),
        "settlements_count": len(getattr(player, "settlements", []) or []) if player is not None else 0,
        "cities_count": len(getattr(player, "cities", []) or []) if player is not None else 0,
        "roads_count": len(getattr(player, "roads", []) or []) if player is not None else 0,
    }

    forced_mode = _detect_forced_action_mode(
        game=game,
        player=player,
        turn_details=turn_details,
        dice_value=dice_value,
        allow_actions_before_roll=allow_actions_before_roll,
    )

    if forced_mode and enforce_forced_action_lock:
        _populate_forced_actions(
            forced_mode=forced_mode,
            game=game,
            board=board,
            player=player,
            flags=flags,
            candidates=candidates,
            blockers=blockers,
            include_candidates=include_candidates,
        )
        notes.append(f"Forced action mode active: {forced_mode}. Normal actions suppressed.")
        return _make_scan(
            player_id=player_id,
            player_color=player_color,
            round_num=round_num,
            turn=turn,
            phase=phase,
            state=state,
            dice_value=dice_value,
            forced_action_mode=forced_mode,
            flags=flags,
            candidates=candidates,
            blockers=blockers,
            context=context,
            notes=notes,
        )

    # ── Normal current-turn actions ───────────────────────────────────────────

    if player is None:
        notes.append("No acting player could be resolved; only global/forced actions can be scanned.")
        return _make_scan(
            player_id=player_id,
            player_color=player_color,
            round_num=round_num,
            turn=turn,
            phase=phase,
            state=state,
            dice_value=dice_value,
            forced_action_mode=forced_mode,
            flags=flags,
            candidates=candidates,
            blockers=blockers,
            context=context,
            notes=notes,
        )

    _scan_twp_protocol(
        game=game,
        player=player,
        turn_details=turn_details,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
    )

    _scan_twp_make_offer(
        game=game,
        player=player,
        hand=hand,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
    )

    _scan_twb(
        hand=hand,
        trade_rates=trade_rates,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
        include_candidates=include_candidates,
        max_candidates=max_bank_trade_candidates,
    )

    _scan_buy_dcard(
        game=game,
        hand=hand,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
    )

    _scan_build_city(
        player=player,
        hand=hand,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
        max_piece_cities=max_piece_cities,
    )

    _scan_build_settlement(
        board=board,
        player=player,
        hand=hand,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
        include_candidates=include_candidates,
        max_piece_settlements=max_piece_settlements,
        max_candidates=max_settlement_candidates,
    )

    road_candidates = _scan_build_road(
        board=board,
        player=player,
        hand=hand,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
        include_candidates=include_candidates,
        max_piece_roads=max_piece_roads,
        max_candidates=max_road_candidates,
    )

    _scan_play_dcards(
        board=board,
        game=game,
        player=player,
        turn_details=turn_details,
        road_candidates=road_candidates,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
        include_candidates=include_candidates,
        max_yop_candidates=max_yop_candidates,
    )

    return _make_scan(
        player_id=player_id,
        player_color=player_color,
        round_num=round_num,
        turn=turn,
        phase=phase,
        state=state,
        dice_value=dice_value,
        forced_action_mode=forced_mode,
        flags=flags,
        candidates=candidates,
        blockers=blockers,
        context=context,
        notes=notes,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Forced-state scanning
# ──────────────────────────────────────────────────────────────────────────────

def _populate_forced_actions(
    *,
    forced_mode: str,
    game: Any,
    board: Any,
    player: Any,
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    include_candidates: bool,
) -> None:
    if forced_mode == "discard":
        flags[DISCARD_RCARDS] = True
        if include_candidates:
            count_to_discard = max(0, _get_total_rcards(player) // 2)
            candidates[DISCARD_RCARDS].append({
                "description": f"Discard {count_to_discard} resource cards",
                "count_to_discard": count_to_discard,
                "hand": _get_rcards_vector(player),
                "resource_order": list(RESOURCE_NAMES),
            })
        return

    if forced_mode == "robber":
        flags[REMOVE_ROBBER] = True
        flags[MOVE_ROBBER] = True
        if include_candidates:
            candidates[MOVE_ROBBER].extend(_robber_tile_candidates(board))
        return

    if forced_mode == "steal_select_opponent":
        flags[STEAL_SELECT_OPPONENT] = True
        if include_candidates:
            candidates[STEAL_SELECT_OPPONENT].extend(_stealable_opponent_candidates(game, player))
        return

    if forced_mode == "steal_pick_rcard":
        flags[STEAL_PICK_RCARD] = True
        if include_candidates:
            candidates[STEAL_PICK_RCARD].append({
                "description": "Pick one random resource card from selected opponent",
            })
        return

    if forced_mode == "roll_dice":
        flags[ROLL_DICE] = True
        if include_candidates:
            candidates[ROLL_DICE].append({"description": "Roll two dice to start production/robber step"})
        return

    blockers[ROLL_DICE].append(f"Unknown forced mode: {forced_mode}")


def _detect_forced_action_mode(
    *,
    game: Any,
    player: Any,
    turn_details: Any,
    dice_value: int,
    allow_actions_before_roll: bool,
) -> Optional[str]:
    """Best-effort forced-state detector using explicit flags first, state text second."""

    state_text = " ".join(
        str(getattr(obj, attr, ""))
        for obj in (game,)
        for attr in ("phase", "state", "state_1", "state_2")
    ).lower()

    if _player_must_discard(player, turn_details, dice_value, state_text):
        return "discard"

    if _truthy(getattr(turn_details, "validate_function_set_robber_by_HP", False)):
        return "robber"

    if "move robber" in state_text or "set robber" in state_text or "robber" in state_text:
        # Avoid treating every post-7 state as robber forever; state text must say it.
        if "steal" not in state_text:
            return "robber"

    if "select opponent" in state_text and "steal" in state_text:
        return "steal_select_opponent"

    if "pick" in state_text and "steal" in state_text:
        return "steal_pick_rcard"

    if "steal" in state_text:
        return "steal_select_opponent"

    if not allow_actions_before_roll and _is_execution_phase(game) and dice_value <= 0:
        return "roll_dice"

    return None


def _player_must_discard(player: Any, turn_details: Any, dice_value: int, state_text: str) -> bool:
    if player is None:
        return False

    player_id = _safe_int_or_none(getattr(player, "id", None))
    discard_flag = _truthy(getattr(turn_details, "validate_function_discard_rcards_by_HP", False))

    players_too_many = getattr(turn_details, "players_having_too_many_rcards", None)
    listed = False
    if isinstance(players_too_many, Sequence) and player_id is not None:
        if 0 <= player_id < len(players_too_many):
            listed = _truthy(players_too_many[player_id])
        elif 0 <= player_id - 1 < len(players_too_many):
            listed = _truthy(players_too_many[player_id - 1])

    # The dice can remain 7 after discard is already resolved, so do not rely on
    # dice_value alone unless the state/flags indicate discard handling.
    text_says_discard = "discard" in state_text
    has_too_many = _get_total_rcards(player) > 7

    return bool((discard_flag or listed or text_says_discard) and dice_value == 7 and has_too_many)


# ──────────────────────────────────────────────────────────────────────────────
# Trade scanning
# ──────────────────────────────────────────────────────────────────────────────

def _scan_twp_protocol(
    *,
    game: Any,
    player: Any,
    turn_details: Any,
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
) -> None:
    pending_deals = list(getattr(turn_details, "list_of_TwP", []) or [])
    player_id = _safe_int_or_none(getattr(player, "id", None))

    if _truthy(getattr(turn_details, "validate_function_TwP_Match", False)):
        flags[TWP_CONFIRM_DEAL] = True
        candidates[TWP_CONFIRM_DEAL].append({"description": "Confirm currently matched player trade"})

    if not pending_deals:
        blockers[TWP_ACCEPT_OFFER].append("No pending TwP offer found")
        blockers[TWP_DECLINE_OFFER].append("No pending TwP offer found")
        blockers[TWP_CANCEL_OFFER].append("No pending own TwP offer found")
        blockers[TWP_PROPOSE_COUNTER].append("No pending TwP offer found")
        blockers[TWP_ACCEPT_COUNTER].append("No pending counter offer found")
        return

    for idx, deal in enumerate(pending_deals):
        deal_dict = _deal_to_dict(idx, deal)
        involves_player = _deal_involves_player(deal, player_id)
        from_player = _deal_from_player(deal, player_id)

        if involves_player and not from_player:
            flags[TWP_ACCEPT_OFFER] = True
            flags[TWP_DECLINE_OFFER] = True
            flags[TWP_PROPOSE_COUNTER] = True
            candidates[TWP_ACCEPT_OFFER].append(deal_dict)
            candidates[TWP_DECLINE_OFFER].append(deal_dict)
            candidates[TWP_PROPOSE_COUNTER].append(deal_dict)

        if from_player:
            flags[TWP_CANCEL_OFFER] = True
            candidates[TWP_CANCEL_OFFER].append(deal_dict)

        if _deal_looks_like_counter(deal):
            flags[TWP_ACCEPT_COUNTER] = True
            candidates[TWP_ACCEPT_COUNTER].append(deal_dict)


def _scan_twp_make_offer(
    *,
    game: Any,
    player: Any,
    hand: Sequence[int],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
) -> None:
    opponents = [p for p in list(getattr(game, "players", []) or []) if getattr(p, "id", None) != getattr(player, "id", None)]
    if sum(hand) <= 0:
        blockers[TWP_MAKE_OFFER].append("Player has no resource cards to offer")
        return
    if not opponents:
        blockers[TWP_MAKE_OFFER].append("No opponents found")
        return

    if make_twp_offer_candidates is not None:
        try:
            twp_candidates = make_twp_offer_candidates(game, player, max_candidates=20)
        except Exception as exc:
            twp_candidates = []
            blockers[TWP_MAKE_OFFER].append(f"TwP planner failed: {exc}")
        if twp_candidates:
            flags[TWP_MAKE_OFFER] = True
            candidates[TWP_MAKE_OFFER].extend(twp_candidates)
            return

    flags[TWP_MAKE_OFFER] = True
    candidates[TWP_MAKE_OFFER].append({
        "description": "Player can make a trade offer; concrete give/get scoring belongs in TwP planner",
        "opponent_ids": [_safe_int_or_none(getattr(p, "id", None)) for p in opponents],
        "hand": list(hand),
        "resource_order": list(RESOURCE_NAMES),
    })


def _scan_twb(
    *,
    hand: Sequence[int],
    trade_rates: Sequence[int],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    include_candidates: bool,
    max_candidates: int,
) -> None:
    made_any = False
    for give_idx, give_name in enumerate(RESOURCE_NAMES):
        rate = max(1, int(trade_rates[give_idx]))
        if int(hand[give_idx]) < rate:
            continue
        for get_idx, get_name in enumerate(RESOURCE_NAMES):
            if get_idx == give_idx:
                continue
            made_any = True
            if include_candidates and len(candidates[TWB]) < max_candidates:
                candidates[TWB].append({
                    "description": f"Trade {rate} {give_name} for 1 {get_name}",
                    "give_resource": give_name,
                    "get_resource": get_name,
                    "give_index": give_idx,
                    "get_index": get_idx,
                    "rate": rate,
                    "give_vector": _unit_vector(give_idx, rate),
                    "get_vector": _unit_vector(get_idx, 1),
                })
    if made_any:
        flags[TWB] = True
    else:
        blockers[TWB].append("No resource count reaches its bank/port trade rate")


# ──────────────────────────────────────────────────────────────────────────────
# Buy/build scanning
# ──────────────────────────────────────────────────────────────────────────────

def _scan_buy_dcard(
    *,
    game: Any,
    hand: Sequence[int],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
) -> None:
    stack_count = _dcard_stack_count(game)
    stack_available = stack_count is None or stack_count > 0
    affordable = _can_pay(hand, RCARDS_FOR_DCARD)

    if affordable and stack_available:
        flags[BUY_DCARD] = True
        candidates[BUY_DCARD].append({
            "description": "Buy one development card from the stack",
            "cost_vector": list(RCARDS_FOR_DCARD),
            "resource_order": list(RESOURCE_NAMES),
            "dcards_stack_count": stack_count,
        })
        return

    if not affordable:
        blockers[BUY_DCARD].append(_missing_text(hand, RCARDS_FOR_DCARD))
    if not stack_available:
        blockers[BUY_DCARD].append("Development-card stack is empty")


def _scan_build_city(
    *,
    player: Any,
    hand: Sequence[int],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    max_piece_cities: int,
) -> None:
    cities = set(_safe_int_list(getattr(player, "cities", []) or []))
    settlements = _safe_int_list(getattr(player, "settlements", []) or [])
    targets = [sid for sid in settlements if sid not in cities]

    if len(cities) >= max_piece_cities:
        blockers[BUILD_CITY].append(f"No city pieces left; already has {len(cities)} cities")
        return
    if not targets:
        blockers[BUILD_CITY].append("No settlement available to upgrade")
        return
    if not _can_pay(hand, RCARDS_FOR_CITY):
        blockers[BUILD_CITY].append(_missing_text(hand, RCARDS_FOR_CITY))
        return

    flags[BUILD_CITY] = True
    for sid in targets:
        candidates[BUILD_CITY].append({
            "description": f"Upgrade settlement {sid} to city",
            "target_id": sid,
            "cost_vector": list(RCARDS_FOR_CITY),
            "resource_order": list(RESOURCE_NAMES),
        })


def _scan_build_settlement(
    *,
    board: Any,
    player: Any,
    hand: Sequence[int],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    include_candidates: bool,
    max_piece_settlements: int,
    max_candidates: int,
) -> None:
    settlements = _safe_int_list(getattr(player, "settlements", []) or [])
    if len(settlements) >= max_piece_settlements:
        blockers[BUILD_SETTLEMENT].append(f"No settlement pieces left; already has {len(settlements)} settlements")
        return

    targets = _legal_settlement_targets(board, player)
    if not targets:
        blockers[BUILD_SETTLEMENT].append("No legal settlement target currently reachable")
        return
    if not _can_pay(hand, RCARDS_FOR_SETTLEMENT):
        blockers[BUILD_SETTLEMENT].append(_missing_text(hand, RCARDS_FOR_SETTLEMENT))
        return

    flags[BUILD_SETTLEMENT] = True
    if include_candidates:
        for target in targets[:max_candidates]:
            candidates[BUILD_SETTLEMENT].append({
                "description": f"Build settlement at intersection {target}",
                "target_id": target,
                "cost_vector": list(RCARDS_FOR_SETTLEMENT),
                "resource_order": list(RESOURCE_NAMES),
            })


def _scan_build_road(
    *,
    board: Any,
    player: Any,
    hand: Sequence[int],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    include_candidates: bool,
    max_piece_roads: int,
    max_candidates: int,
) -> List[Tuple[int, int]]:
    roads_owned = [_canonical_road(r) for r in (getattr(player, "roads", []) or []) if _canonical_road(r) is not None]
    roads_owned = [r for r in roads_owned if r is not None]

    if len(roads_owned) >= max_piece_roads:
        blockers[BUILD_ROAD].append(f"No road pieces left; already has {len(roads_owned)} roads")
        return []

    targets = _legal_road_targets(board, player)
    if not targets:
        blockers[BUILD_ROAD].append("No legal road target currently connected to player network")
        return []
    if not _can_pay(hand, RCARDS_FOR_ROAD):
        blockers[BUILD_ROAD].append(_missing_text(hand, RCARDS_FOR_ROAD))
        return targets

    flags[BUILD_ROAD] = True
    if include_candidates:
        for road in targets[:max_candidates]:
            candidates[BUILD_ROAD].append({
                "description": f"Build road {list(road)}",
                "road_id": list(road),
                "cost_vector": list(RCARDS_FOR_ROAD),
                "resource_order": list(RESOURCE_NAMES),
            })
    return targets


# ──────────────────────────────────────────────────────────────────────────────
# Development-card scanning
# ──────────────────────────────────────────────────────────────────────────────

def _scan_play_dcards(
    *,
    board: Any,
    game: Any,
    player: Any,
    turn_details: Any,
    road_candidates: Sequence[Tuple[int, int]],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    include_candidates: bool,
    max_yop_candidates: int,
) -> None:
    if _truthy(getattr(turn_details, "dcard_played_in_turn_TF", False)):
        for action in (PLAY_KNIGHT, PLAY_YOP, PLAY_TWO_FREE_ROADS, PLAY_MONOPOLY):
            blockers[action].append("A development card has already been played this turn")
        return

    dcard_counts = _all_playable_dcard_counts(player)

    if dcard_counts.get("knight", 0) > 0:
        flags[PLAY_KNIGHT] = True
        if include_candidates:
            candidates[PLAY_KNIGHT].extend(_robber_tile_candidates(board))
    else:
        blockers[PLAY_KNIGHT].append("No playable Knight card in hand")

    if dcard_counts.get("year_of_plenty", 0) > 0:
        flags[PLAY_YOP] = True
        if include_candidates:
            count = 0
            for i, j in combinations_with_replacement(range(5), 2):
                candidates[PLAY_YOP].append({
                    "description": f"Take {RESOURCE_NAMES[i]} and {RESOURCE_NAMES[j]}",
                    "resource_indices": [i, j],
                    "resource_names": [RESOURCE_NAMES[i], RESOURCE_NAMES[j]],
                    "gain_vector": _unit_vector(i, 1, extra_index=j),
                })
                count += 1
                if count >= max_yop_candidates:
                    break
    else:
        blockers[PLAY_YOP].append("No playable Year of Plenty card in hand")

    if dcard_counts.get("two_free_roads", 0) > 0:
        if road_candidates:
            flags[PLAY_TWO_FREE_ROADS] = True
            if include_candidates:
                candidates[PLAY_TWO_FREE_ROADS].append({
                    "description": "Play Two Free Roads; first-road candidates are listed separately",
                    "available_first_roads_count": len(road_candidates),
                    "available_first_roads_preview": [list(r) for r in road_candidates[:20]],
                    "cost_vector": [0, 0, 0, 0, 0],
                })
        else:
            blockers[PLAY_TWO_FREE_ROADS].append("No legal first road target available")
    else:
        blockers[PLAY_TWO_FREE_ROADS].append("No playable Two Free Roads card in hand")

    if dcard_counts.get("monopoly", 0) > 0:
        flags[PLAY_MONOPOLY] = True
        if include_candidates:
            for idx, name in enumerate(RESOURCE_NAMES):
                candidates[PLAY_MONOPOLY].append({
                    "description": f"Declare Monopoly on {name}",
                    "resource_index": idx,
                    "resource_name": name,
                })
    else:
        blockers[PLAY_MONOPOLY].append("No playable Monopoly card in hand")


# ──────────────────────────────────────────────────────────────────────────────
# Candidate target helpers
# ──────────────────────────────────────────────────────────────────────────────

def _legal_settlement_targets(board: Any, player: Any) -> List[int]:
    if board is None or player is None:
        return []

    targets = set()

    # Prefer outlook if it already contains currently reachable settlements.
    outlook = getattr(player, "outlook", None)
    for raw in list(getattr(outlook, "next_settlements", []) or []):
        target = _safe_int_or_none(raw)
        if target is not None and _intersection_can_receive_settlement(board, target):
            targets.add(target)

    # Board fallback: unoccupied/can_build intersection touching player road.
    player_road_endpoints = _player_road_endpoints(player)
    for inter in list(getattr(board, "intersections", []) or []):
        if inter is None:
            continue
        inter_id = _safe_int_or_none(getattr(inter, "id", None))
        if inter_id is None:
            continue
        if inter_id not in player_road_endpoints:
            continue
        if _intersection_can_receive_settlement(board, inter_id):
            targets.add(inter_id)

    return sorted(targets)


def _legal_road_targets(board: Any, player: Any) -> List[Tuple[int, int]]:
    if board is None or player is None:
        return []

    legal: List[Tuple[int, int]] = []
    seen = set()

    for road_obj in list(getattr(board, "roads", []) or []):
        road_id = _canonical_road(getattr(road_obj, "id", None))
        if road_id is None or road_id in seen:
            continue
        seen.add(road_id)
        if not _board_says_road_buildable(board, road_id, getattr(player, "color", "")):
            continue
        if not _road_touches_player_network_without_crossing_opponent(board, player, road_id):
            continue
        legal.append(road_id)

    return sorted(legal)


def _intersection_can_receive_settlement(board: Any, intersection_id: int) -> bool:
    if intersection_id < 0:
        return False
    if intersection_id in set(getattr(board, "INTERSECTION_IN_WATER", []) or []):
        return False

    try:
        inter = board.intersections[intersection_id]
    except Exception:
        return False

    if inter is None:
        return False
    if _truthy(getattr(inter, "occupied_tf", False)):
        return False
    if not _truthy(getattr(inter, "can_build_tf", True)):
        return False
    return True


def _board_says_road_buildable(board: Any, road_id: Tuple[int, int], color: str) -> bool:
    fn = getattr(board, "can_build_road_for_color_tf", None)
    if callable(fn):
        try:
            return bool(fn(list(road_id), color))
        except TypeError:
            try:
                return bool(fn(road_id, color))
            except Exception:
                pass
        except Exception:
            pass

    # Fallback: valid Road object exists and is not occupied.
    for road in list(getattr(board, "roads", []) or []):
        rid = _canonical_road(getattr(road, "id", None))
        if rid == road_id:
            return not _truthy(getattr(road, "occupied_tf", False))
    return False


def _road_touches_player_network_without_crossing_opponent(board: Any, player: Any, road_id: Tuple[int, int]) -> bool:
    player_color = str(getattr(player, "color", ""))
    player_structures = set(_safe_int_list(getattr(player, "settlements", []) or []))
    player_structures.update(_safe_int_list(getattr(player, "cities", []) or []))
    player_roads = [_canonical_road(r) for r in (getattr(player, "roads", []) or [])]
    player_roads = [r for r in player_roads if r is not None]

    for endpoint in road_id:
        if endpoint in player_structures:
            return True

        # Opponent structure blocks extension through that endpoint.
        if _endpoint_has_opponent_structure(board, endpoint, player_color):
            continue

        for owned_road in player_roads:
            if endpoint in owned_road:
                return True

    return False


def _endpoint_has_opponent_structure(board: Any, intersection_id: int, player_color: str) -> bool:
    try:
        inter = board.intersections[intersection_id]
    except Exception:
        return False
    if inter is None:
        return False
    if not _truthy(getattr(inter, "occupied_tf", False)):
        return False
    return str(getattr(inter, "color", "")) != player_color


# ──────────────────────────────────────────────────────────────────────────────
# Robber/steal candidates
# ──────────────────────────────────────────────────────────────────────────────

def _robber_tile_candidates(board: Any) -> List[Dict[str, Any]]:
    if board is None:
        return []
    out: List[Dict[str, Any]] = []
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        tile_type = str(getattr(tile, "type", ""))
        tile_id = _safe_int_or_none(getattr(tile, "id", None))
        if tile_id is None:
            continue
        if tile_type in ("Sea", "Desert", "Blank", ""):
            continue
        if _truthy(getattr(tile, "occupied_tf", False)):
            continue
        out.append({
            "description": f"Move robber to tile {tile_id} ({tile_type})",
            "tile_id": tile_id,
            "tile_type": tile_type,
            "tile_value": _safe_int_or_none(getattr(tile, "value", None)),
        })
    return sorted(out, key=lambda x: (x.get("tile_value") or 0, x.get("tile_id") or 0), reverse=True)


def _stealable_opponent_candidates(game: Any, player: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    player_id = getattr(player, "id", None)
    for opponent in list(getattr(game, "players", []) or []):
        if getattr(opponent, "id", None) == player_id:
            continue
        total = _get_total_rcards(opponent)
        if total <= 0:
            continue
        out.append({
            "description": f"Steal from player {getattr(opponent, 'id', None)}",
            "opponent_id": _safe_int_or_none(getattr(opponent, "id", None)),
            "opponent_color": str(getattr(opponent, "color", "")),
            "opponent_resource_count": total,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Player/card/resource helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_player(game: Any, player: Optional[Any]) -> Optional[Any]:
    if player is not None:
        return player
    current = getattr(game, "current_player", None)
    if current is not None:
        return current

    turn = _safe_int_or_none(getattr(game, "turn", None))
    if turn is None:
        return None

    for p in list(getattr(game, "players", []) or []):
        if _safe_int_or_none(getattr(p, "id", None)) == turn:
            return p
    return None


def _get_turn_details(game: Any) -> Any:
    return getattr(game, "turn_details", None) or getattr(game, "turn_detail", None)


def _get_rcards_vector(player: Any) -> List[int]:
    if player is None:
        return [0, 0, 0, 0, 0]

    fn = getattr(player, "rcards_in_hand", None)
    if callable(fn):
        try:
            cards, _, _ = fn()
            return _clean_int_vector(cards, length=5, default=0)
        except Exception:
            pass

    rcards = getattr(player, "rcards", {}) or {}
    order = [ResourceCard.WHEAT, ResourceCard.ORE, ResourceCard.WOOD, ResourceCard.BRICK, ResourceCard.SHEEP]
    values = []
    for rc in order:
        values.append(_safe_int(rcards.get(rc, rcards.get(str(getattr(rc, "value", rc)), 0)), 0))
    return _clean_int_vector(values, length=5, default=0)


def _get_trade_rates_vector(player: Any, game: Any = None) -> List[int]:
    """Return bank trade rates in [Wheat, Ore, Wood, Brick, Sheep] order."""
    if player is None:
        return [4, 4, 4, 4, 4]

    if game is not None and hasattr(game, "get_player_bank_trade_rates"):
        try:
            return [max(1, x) for x in _clean_int_vector(game.get_player_bank_trade_rates(player), length=5, default=4)]
        except Exception:
            pass

    fn = getattr(player, "rcards_in_hand", None)
    if callable(fn):
        try:
            _, rates, _ = fn()
            return [max(1, x) for x in _clean_int_vector(rates, length=5, default=4)]
        except Exception:
            pass

    rates = getattr(player, "trade_rates", [4, 4, 4, 4, 4]) or [4, 4, 4, 4, 4]
    if isinstance(rates, (list, tuple)):
        return [max(1, x) for x in _clean_int_vector(rates, length=5, default=4)]

    if isinstance(rates, dict):
        order = [ResourceCard.WHEAT, ResourceCard.ORE, ResourceCard.WOOD, ResourceCard.BRICK, ResourceCard.SHEEP]
        aliases = [
            ("wheat", "grain"),
            ("ore",),
            ("wood", "lumber"),
            ("brick",),
            ("sheep", "wool"),
        ]
        out = []
        for idx, rc in enumerate(order):
            val = rates.get(rc, None)
            if val is None:
                val = rates.get(str(getattr(rc, "value", rc)), None)
            if val is None:
                val = rates.get(str(getattr(rc, "name", rc)), None)
            if val is None:
                for alias in aliases[idx]:
                    if alias in rates:
                        val = rates[alias]
                        break
            out.append(max(1, _safe_int(val, 4)))
        return out

    return [4, 4, 4, 4, 4]

def _get_total_rcards(player: Any) -> int:
    if player is None:
        return 0
    value = getattr(player, "number_of_rcards", None)
    if value is not None:
        try:
            return int(value)
        except Exception:
            pass
    return int(sum(_get_rcards_vector(player)))


def _all_playable_dcard_counts(player: Any) -> Dict[str, int]:
    return {
        "knight": _dcard_count(player, "knight"),
        "year_of_plenty": _dcard_count(player, "year_of_plenty"),
        "two_free_roads": _dcard_count(player, "two_free_roads"),
        "monopoly": _dcard_count(player, "monopoly"),
    }


def _dcard_count(player: Any, card_name: str) -> int:
    if player is None:
        return 0

    target = _normalize_dcard_name(card_name)

    development_cards = getattr(player, "development_cards", None)
    if isinstance(development_cards, Sequence) and not isinstance(development_cards, (str, bytes)):
        count = sum(1 for card in development_cards if _normalize_dcard_name(card) == target)
        if count > 0:
            return count

    # Fallback for older states. The meaning of dcard_summary columns has changed
    # over versions, so use the maximum positive count from columns 1..n as a
    # conservative "has at least one" signal.
    for row in list(getattr(player, "dcard_summary", []) or []):
        if not row:
            continue
        if _normalize_dcard_name(row[0]) != target:
            continue
        counts = [_safe_int(v, 0) for v in list(row)[1:]]
        return max(counts) if counts else 0
    return 0


def _dcard_stack_count(game: Any) -> Optional[int]:
    stack = getattr(game, "dcards_stack", None)
    if stack is None:
        return None
    try:
        return len(stack)
    except Exception:
        return None


def _normalize_dcard_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace(" ", "_").replace("-", "_")
    aliases = {
        "year_of_plenty": "year_of_plenty",
        "yop": "year_of_plenty",
        "two_free_roads": "two_free_roads",
        "two_roads": "two_free_roads",
        "road_building": "two_free_roads",
        "knight": "knight",
        "monopoly": "monopoly",
        "victory_point": "victory_point",
    }
    return aliases.get(text, text)


# ──────────────────────────────────────────────────────────────────────────────
# Generic helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_scan(
    *,
    player_id: Optional[int],
    player_color: str,
    round_num: Optional[int],
    turn: Optional[int],
    phase: str,
    state: str,
    dice_value: int,
    forced_action_mode: Optional[str],
    flags: Dict[str, bool],
    candidates: Dict[str, List[Dict[str, Any]]],
    blockers: Dict[str, List[str]],
    context: Dict[str, Any],
    notes: List[str],
) -> ViableActionScan:
    clean_candidates = {k: v for k, v in candidates.items() if v}
    clean_blockers = {k: v for k, v in blockers.items() if v}
    mask = [1 if flags.get(name, False) else 0 for name in ACTION_NAMES]
    return ViableActionScan(
        player_id=player_id,
        player_color=player_color,
        round_num=round_num,
        turn=turn,
        phase=phase,
        state=state,
        dice_value=dice_value,
        forced_action_mode=forced_action_mode,
        action_mask=mask,
        action_flags={name: bool(flags.get(name, False)) for name in ACTION_NAMES},
        candidates=clean_candidates,
        blockers=clean_blockers,
        context=context,
        notes=notes,
    )


def _get_dice_value(game: Any, turn_details: Any) -> int:
    for source in (turn_details, game):
        raw = getattr(source, "dice_roll", None)
        value = _dice_raw_to_value(raw)
        if value > 0:
            return value
    return 0


def _dice_raw_to_value(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        vals = [_safe_int(x, 0) for x in raw]
        if len(vals) == 2:
            return int(vals[0] + vals[1])
        if len(vals) == 1:
            return int(vals[0])
    try:
        return int(raw)
    except Exception:
        return 0


def _is_execution_phase(game: Any) -> bool:
    return str(getattr(game, "phase", "")).lower() == "execution"


def _can_pay(hand: Sequence[int], cost: Sequence[int]) -> bool:
    h = _clean_int_vector(hand, length=5, default=0)
    c = _clean_int_vector(cost, length=5, default=0)
    return all(h[i] >= c[i] for i in range(5))


def _missing_text(hand: Sequence[int], cost: Sequence[int]) -> str:
    h = _clean_int_vector(hand, length=5, default=0)
    c = _clean_int_vector(cost, length=5, default=0)
    missing = [max(0, c[i] - h[i]) for i in range(5)]
    parts = [f"{missing[i]} {RESOURCE_NAMES[i]}" for i in range(5) if missing[i] > 0]
    return "Missing " + ", ".join(parts) if parts else "Enough resources"


def _unit_vector(index: int, amount: int, *, extra_index: Optional[int] = None) -> List[int]:
    out = [0, 0, 0, 0, 0]
    if 0 <= index < 5:
        out[index] += int(amount)
    if extra_index is not None and 0 <= extra_index < 5:
        out[extra_index] += 1
    return out


def _player_road_endpoints(player: Any) -> set[int]:
    endpoints: set[int] = set()
    for raw in list(getattr(player, "roads", []) or []):
        road = _canonical_road(raw)
        if road is None:
            continue
        endpoints.update(road)
    return endpoints


def _canonical_road(raw: Any) -> Optional[Tuple[int, int]]:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        raw = raw.get("id") or raw.get("road_id")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
        return None
    a = _safe_int_or_none(raw[0])
    b = _safe_int_or_none(raw[1])
    if a is None or b is None or a == b:
        return None
    return tuple(sorted((a, b)))


def _safe_int_list(values: Iterable[Any]) -> List[int]:
    out = []
    for value in values:
        cleaned = _safe_int_or_none(value)
        if cleaned is not None:
            out.append(cleaned)
    return sorted(set(out))


def _clean_int_vector(values: Any, *, length: int, default: int) -> List[int]:
    if values is None or isinstance(values, (str, bytes)):
        raw = []
    else:
        try:
            raw = list(values)
        except Exception:
            raw = []
    out = [_safe_int(v, default) for v in raw[:length]]
    out.extend([default] * max(0, length - len(out)))
    return out


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "yes", "y", "1"}
    return bool(value)


def _deal_to_dict(idx: int, deal: Any) -> Dict[str, Any]:
    return {
        "description": f"Pending TwP deal #{idx}",
        "deal_index": idx,
        "raw_deal": deal,
    }


def _deal_involves_player(deal: Any, player_id: Optional[int]) -> bool:
    if player_id is None:
        return False
    if isinstance(deal, Mapping):
        values = list(deal.values())
    elif isinstance(deal, Sequence) and not isinstance(deal, (str, bytes)):
        values = list(deal)
    else:
        values = [deal]
    return any(_safe_int_or_none(v) == player_id for v in values[:4])


def _deal_from_player(deal: Any, player_id: Optional[int]) -> bool:
    if player_id is None:
        return False
    if isinstance(deal, Mapping):
        for key in ("from_player", "from_player_id", "player_from", "offering_player", "offeror"):
            if _safe_int_or_none(deal.get(key)) == player_id:
                return True
        return False
    if isinstance(deal, Sequence) and not isinstance(deal, (str, bytes)) and len(deal) > 1:
        # Best-effort only: in many older list-based deal formats, early columns
        # contain source/target player ids.
        return _safe_int_or_none(deal[1]) == player_id
    return False


def _deal_looks_like_counter(deal: Any) -> bool:
    text = str(deal).lower()
    return "counter" in text
