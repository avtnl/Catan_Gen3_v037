"""core/player_trade.py

Trade-with-Player (TwP) planner and executor for Catan Gen3.

Version 1+
---------
Supported proposal shapes:

* 1:1 normal trade
* 2:1 tempting trade: active player gives 2 of one resource for 1 needed resource
* 1:2 scarcity-premium trade: active player gives 1 scarce resource for 2 abundant
  counterparty resources

The module is deliberately independent from GUI code.  It can be used in three
ways:

* Diagnostics: ``make_twp_offer_candidates(game, player)`` returns candidate
  dictionaries for viable_action_scanner / reports / a future TwP panel.
* AI-vs-AI automation: ``find_and_execute_best_ai_to_ai_trade(...)`` executes
  the best automatically acceptable deal.
* Human interactions: ``evaluate_twp_offer(...)`` can be called when a human
  proposes/receives a TwP deal; it returns accept/reject/counter-style data
  without mutating cards unless ``execute_twp_trade`` is called.

Resource order is the existing project order:

    [Wheat, Ore, Wood, Brick, Sheep]

No ``ANY`` resource is stored in the core vectors.  That can be a GUI layer later.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from math import isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:  # Normal project imports.
    from core.constants import ResourceCard  # type: ignore
except Exception:  # pragma: no cover - keeps standalone editing/testing possible.
    class ResourceCard:  # type: ignore[no-redef]
        WHEAT = "Wheat"
        ORE = "Ore"
        WOOD = "Wood"
        BRICK = "Brick"
        SHEEP = "Sheep"

try:
    from core.board import pips_from_tile_value  # type: ignore
except Exception:  # pragma: no cover
    def pips_from_tile_value(value: int) -> float:
        try:
            value = int(value)
        except Exception:
            return 0.0
        if not (2 <= value <= 12):
            return 0.0
        return float(6 - abs(7 - value))

try:
    from core.resource_time_estimator import (  # type: ignore
        get_player_production_pips,
        get_player_resource_cards_vector,
        get_player_trade_rates,
    )
except Exception:  # pragma: no cover
    get_player_production_pips = None  # type: ignore[assignment]
    get_player_resource_cards_vector = None  # type: ignore[assignment]
    get_player_trade_rates = None  # type: ignore[assignment]


RESOURCE_NAMES: Tuple[str, str, str, str, str] = (
    "Wheat",
    "Ore",
    "Wood",
    "Brick",
    "Sheep",
)
RESOURCE_ABBR: Tuple[str, str, str, str, str] = ("Wh", "O", "Wd", "B", "Sh")
RESOURCECARD_ATTRS: Tuple[str, str, str, str, str] = (
    "WHEAT",
    "ORE",
    "WOOD",
    "BRICK",
    "SHEEP",
)

# Existing game/action cost order: [Wheat, Ore, Wood, Brick, Sheep].
COST_ROAD: Tuple[int, int, int, int, int] = (0, 0, 1, 1, 0)
COST_SETTLEMENT: Tuple[int, int, int, int, int] = (1, 0, 1, 1, 1)
COST_CITY: Tuple[int, int, int, int, int] = (2, 3, 0, 0, 0)
COST_DCARD: Tuple[int, int, int, int, int] = (1, 1, 0, 0, 1)

TRADE_NORMAL_1_FOR_1 = "normal_1_for_1"
TRADE_TEMPTING_2_FOR_1 = "tempting_2_for_1"
TRADE_SCARCITY_PREMIUM_1_FOR_2 = "scarcity_premium_1_for_2"

SUPPORTED_TWP_QUANTITY_PATTERNS: Tuple[Tuple[int, int, str], ...] = (
    (1, 1, TRADE_NORMAL_1_FOR_1),
    (2, 1, TRADE_TEMPTING_2_FOR_1),
    (1, 2, TRADE_SCARCITY_PREMIUM_1_FOR_2),
)

# Conservative defaults.  The brick example discussed earlier had total_pips=11
# and should count as scarce; therefore <= 11 is the default scarce threshold.
DEFAULT_SCARCE_TOTAL_PIPS_MAX: float = 11.0
DEFAULT_SCARCE_PLAYERS_WITH_ACCESS_MAX: int = 2
DEFAULT_ABUNDANT_PLAYER_PIPS_MIN: float = 4.0
DEFAULT_ABUNDANT_HAND_MIN: int = 4
DEFAULT_MAX_PROPOSALS: int = 20

# T3 rate limits — stop spam / over-trading one partner
MAX_PROPOSALS_PER_COUNTERPARTY: int = 4
MAX_ACCEPTED_TWP_PER_ACTIVE_TURN: int = 2
# Block further non-unlock proposals after this many accepted TwPs this turn
STRICT_ACCEPTED_TWP_PER_ACTIVE_TURN: int = 1
# VP race thresholds for "don't gift the leader"
VP_LEADER_WARN: int = 7
VP_NEAR_WIN: int = 8
VP_LEAD_GAP: int = 2

MIN_ACTIVE_SCORE_BY_TRADE_TYPE: Dict[str, float] = {
    TRADE_NORMAL_1_FOR_1: 0.20,
    TRADE_TEMPTING_2_FOR_1: 0.35,
    TRADE_SCARCITY_PREMIUM_1_FOR_2: 0.50,
}
MIN_COUNTERPARTY_SCORE_BY_TRADE_TYPE: Dict[str, float] = {
    TRADE_NORMAL_1_FOR_1: -0.05,
    TRADE_TEMPTING_2_FOR_1: -0.05,
    TRADE_SCARCITY_PREMIUM_1_FOR_2: -0.10,
}

_EPS: float = 1e-9

# Product T1-A — package quality ranking (shared find + planner)
# Note: in-module "T1" keep/ditch unlock is separate; use pq_* symbols here.
PQ_UNLOCK_BONUS: float = 1.0
PQ_BANK_BEAT_2FOR1_BONUS: float = 0.50
PQ_DITCH_BONUS: float = 0.20
PQ_ESCALATE_BONUS: float = 0.35
PQ_ATTRACTIVENESS_EPS: float = 0.15  # dig-in / near-tie documentation


@dataclass(frozen=True)
class ResourceMarket:
    """Board/player resource scarcity context used by scarcity-premium trades."""

    board_total_pips: Tuple[float, float, float, float, float]
    players_with_access: Tuple[int, int, int, int, int]
    max_player_pips: Tuple[float, float, float, float, float]
    scarce: Tuple[bool, bool, bool, bool, bool]
    abundant_for_players: Dict[int, Tuple[bool, bool, bool, bool, bool]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "resource_order": list(RESOURCE_NAMES),
            "board_total_pips": list(self.board_total_pips),
            "players_with_access": list(self.players_with_access),
            "max_player_pips": list(self.max_player_pips),
            "scarce": list(self.scarce),
            "scarce_named": {
                RESOURCE_NAMES[i]: bool(self.scarce[i]) for i in range(5)
            },
            "abundant_for_players": {
                int(pid): {
                    RESOURCE_NAMES[i]: bool(flags[i]) for i in range(5)
                }
                for pid, flags in self.abundant_for_players.items()
            },
        }


@dataclass(frozen=True)
class TradeProfile:
    """One player's current TwP appetite and card-position profile."""

    player_id: int
    player_color: str
    is_human: bool
    hand: Tuple[int, int, int, int, int]
    trade_rates: Tuple[int, int, int, int, int]
    production_pips: Tuple[float, float, float, float, float]
    primary_action: str
    primary_cost: Tuple[int, int, int, int, int]
    primary_missing: Tuple[int, int, int, int, int]
    clear_surplus: Tuple[int, int, int, int, int]
    protected_resource_vector: Tuple[int, int, int, int, int]
    bottleneck_resource_vector: Tuple[int, int, int, int, int]
    offer_appetite: Tuple[int, int, int, int, int]
    accept_appetite: Tuple[int, int, int, int, int]
    offer_number: Tuple[int, int, int, int, int]
    accept_number: Tuple[int, int, int, int, int]
    reasons: Dict[str, List[str]] = field(default_factory=dict)
    # T1: Stage A hand-risk keep/ditch (units to protect vs willing to offer)
    keep_resource_vector: Tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)
    ditch_resource_vector: Tuple[int, int, int, int, int] = (0, 0, 0, 0, 0)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["resource_order"] = list(RESOURCE_NAMES)
        data["hand_named"] = _named(self.hand)
        data["trade_rates_named"] = _named(self.trade_rates)
        data["production_pips_named"] = _named(self.production_pips)
        data["primary_cost_named"] = _named(self.primary_cost)
        data["primary_missing_named"] = _named(self.primary_missing)
        data["clear_surplus_named"] = _named(self.clear_surplus)
        data["protected_resource_named"] = _named(self.protected_resource_vector)
        data["bottleneck_resource_named"] = _named(self.bottleneck_resource_vector)
        data["offer_appetite_named"] = _named(self.offer_appetite)
        data["accept_appetite_named"] = _named(self.accept_appetite)
        data["keep_resource_named"] = _named(self.keep_resource_vector)
        data["ditch_resource_named"] = _named(self.ditch_resource_vector)
        return data


@dataclass(frozen=True)
class TradeProposal:
    """Concrete active-player proposal against one counterparty."""

    active_player_id: int
    counterparty_id: int
    active_player_is_human: bool
    counterparty_is_human: bool
    trade_type: str
    active_give_index: int
    active_give_count: int
    active_receive_index: int
    active_receive_count: int
    active_score: float
    counterparty_score: float
    total_score: float
    active_gain_vector: Tuple[int, int, int, int, int]
    counterparty_gain_vector: Tuple[int, int, int, int, int]
    active_offer_appetite: int
    active_accept_appetite: int
    counterparty_offer_appetite: int
    counterparty_accept_appetite: int
    requires_human_confirmation: bool
    auto_executable: bool
    status: str = "candidate"
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    market_snapshot: Mapping[str, Any] = field(default_factory=dict)

    @property
    def description(self) -> str:
        return (
            f"P{self.active_player_id} gives {self.active_give_count} "
            f"{RESOURCE_NAMES[self.active_give_index]} for "
            f"{self.active_receive_count} {RESOURCE_NAMES[self.active_receive_index]} "
            f"from P{self.counterparty_id}"
        )

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["description"] = self.description
        data["resource_order"] = list(RESOURCE_NAMES)
        data["active_give_resource"] = RESOURCE_NAMES[self.active_give_index]
        data["active_receive_resource"] = RESOURCE_NAMES[self.active_receive_index]
        data["active_gain_named"] = _named(self.active_gain_vector)
        data["counterparty_gain_named"] = _named(self.counterparty_gain_vector)
        data["legacy_short_text"] = _format_short_trade(self)
        return data


@dataclass(frozen=True)
class TradeDecision:
    """Result of evaluating or executing one TwP proposal."""

    accepted: bool
    executed: bool
    proposal: Optional[TradeProposal]
    reason: str
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "executed": self.executed,
            "proposal": self.proposal.as_dict() if self.proposal else None,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def make_twp_offer_candidates(
    game: Any,
    player: Optional[Any] = None,
    *,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
    include_human_counterparties: bool = True,
) -> List[Dict[str, Any]]:
    """Return JSON-friendly TwP proposal candidates for scanner/report use.

    This is the safest integration point for ``viable_action_scanner``: it does
    not mutate cards and it does not require a GUI.
    """

    active = _resolve_player(game, player)
    if active is None:
        return []
    proposals = find_twp_proposals(
        game,
        active,
        max_candidates=max_candidates,
        include_human_counterparties=include_human_counterparties,
    )
    return [proposal.as_dict() for proposal in proposals]


def resolve_live_need_for_twp(
    game: Any,
    player: Any,
    *,
    active_profile: Optional[TradeProfile] = None,
) -> Tuple[str, List[int], List[int]]:
    """T11: supporting-action live_need (prefer Game vector, else profile missing).

    Returns ``(action_name, cost_vector, live_need_vector)``.
    """
    action = ""
    cost = [0, 0, 0, 0, 0]
    need = [0, 0, 0, 0, 0]
    if game is not None and player is not None:
        try:
            fn = getattr(game, "_supporting_action_live_need_vector", None)
            if callable(fn):
                act, cost_v, need_v = fn(player)
                action = str(act or "")
                cost = [max(0, int(x or 0)) for x in list(cost_v or [])[:5]]
                need = [max(0, int(x or 0)) for x in list(need_v or [])[:5]]
                while len(cost) < 5:
                    cost.append(0)
                while len(need) < 5:
                    need.append(0)
                if sum(need) > 0 or action:
                    return action, cost, need
        except Exception:
            pass
    if active_profile is not None:
        action = str(getattr(active_profile, "primary_action", "") or action)
        cost = [max(0, int(x or 0)) for x in list(getattr(active_profile, "primary_cost", ()) or [])[:5]]
        need = [max(0, int(x or 0)) for x in list(getattr(active_profile, "primary_missing", ()) or [])[:5]]
        while len(cost) < 5:
            cost.append(0)
        while len(need) < 5:
            need.append(0)
    return action, cost, need


def proposal_fills_live_need(
    proposal: Any,
    live_need: Optional[Sequence[int]],
) -> Tuple[bool, int]:
    """Return (fills?, cards_of_need_received) for active receive side."""
    need = [max(0, int(x or 0)) for x in list(live_need or [])[:5]]
    while len(need) < 5:
        need.append(0)
    if sum(need) <= 0:
        return False, 0
    data = _proposal_mapping(proposal)
    try:
        ri = int(data.get("active_receive_index", -1))
        rc = int(data.get("active_receive_count", 0) or 0)
    except Exception:
        return False, 0
    if not (0 <= ri < 5) or rc <= 0:
        return False, 0
    filled = min(rc, int(need[ri] or 0))
    return filled > 0, filled


def annotate_proposals_with_live_need(
    proposals: Sequence[TradeProposal],
    live_need: Optional[Sequence[int]],
    *,
    support_action: str = "",
) -> List[TradeProposal]:
    """T11: tag market_snapshot with fills_live_need / need_reduced for rank + dig-in."""
    out: List[TradeProposal] = []
    for raw in list(proposals or []):
        if raw is None or not isinstance(raw, TradeProposal):
            continue
        fills, filled_n = proposal_fills_live_need(raw, live_need)
        if not fills and not support_action:
            out.append(raw)
            continue
        snap_extra: Dict[str, Any] = {
            "fills_live_need": bool(fills),
            "live_need_filled": int(filled_n),
            "t11": True,
        }
        if support_action:
            snap_extra["live_need_action"] = str(support_action)
        # Prefer max of existing need_reduced and live fill
        prev_nr = 0
        try:
            prev_nr = int((raw.market_snapshot or {}).get("need_reduced") or 0)
        except Exception:
            prev_nr = 0
        if filled_n > 0:
            snap_extra["need_reduced"] = max(prev_nr, int(filled_n))
            if not (raw.market_snapshot or {}).get("fully_unlocks"):
                # Partial project progress for list-path rank
                pass
        reasons = ()
        if fills:
            reasons = (f"T11: fills live_need {filled_n}",)
        out.append(
            _tag_proposal_snapshot(
                raw,
                extra=snap_extra,
                extra_reasons=reasons,
            )
        )
    return out


def diagnose_twp_empty(
    game: Any,
    active_player: Any,
    *,
    active_profile: Optional[TradeProfile] = None,
    live_need: Optional[Sequence[int]] = None,
    mutual_count: int = 0,
    unlock_count: int = 0,
    frozen_active: bool = False,
    accepted_cap: bool = False,
) -> List[str]:
    """T11: structured skip reasons when the TwP pool is empty (not bare no_mutual)."""
    reasons: List[str] = []
    if accepted_cap:
        reasons.append("accepted_twp_cap")
        return reasons
    if frozen_active:
        reasons.append("T9_freeze_active")
        return reasons

    profile = active_profile
    if profile is None and active_player is not None:
        try:
            profile = build_trade_profile(game, active_player)
        except Exception:
            profile = None

    need = [max(0, int(x or 0)) for x in list(live_need or [])[:5]]
    while len(need) < 5:
        need.append(0)
    if sum(need) <= 0 and profile is not None:
        need = [max(0, int(x or 0)) for x in list(getattr(profile, "primary_missing", ()) or [])[:5]]
        while len(need) < 5:
            need.append(0)

    hand = [0, 0, 0, 0, 0]
    ditch = [0, 0, 0, 0, 0]
    keep = [0, 0, 0, 0, 0]
    if profile is not None:
        hand = [max(0, int(x or 0)) for x in list(getattr(profile, "hand", ()) or [])[:5]]
        ditch = [max(0, int(x or 0)) for x in list(getattr(profile, "ditch_resource_vector", ()) or [])[:5]]
        keep = [max(0, int(x or 0)) for x in list(getattr(profile, "keep_resource_vector", ()) or [])[:5]]
        while len(hand) < 5:
            hand.append(0)
        while len(ditch) < 5:
            ditch.append(0)
        while len(keep) < 5:
            keep.append(0)

    if sum(hand) <= 0:
        reasons.append("empty_hand")
    offerable = [0, 0, 0, 0, 0]
    for i in range(5):
        offerable[i] = min(hand[i], max(ditch[i], max(0, hand[i] - keep[i])))
    if sum(offerable) <= 0 and sum(hand) > 0:
        reasons.append("no_offerable_surplus")
    if sum(need) <= 0:
        reasons.append("no_live_need")
    else:
        need_bits = [
            f"{RESOURCE_ABBR[i]}{need[i]}" for i in range(5) if need[i] > 0
        ]
        if need_bits:
            reasons.append("live_need=" + ",".join(need_bits))
        if unlock_count <= 0:
            reasons.append("no_counterparty_for_live_need")
    if mutual_count <= 0:
        reasons.append("no_mutual")
    if unlock_count <= 0 and mutual_count <= 0 and sum(need) > 0 and sum(offerable) > 0:
        reasons.append("appetite_or_floor")
    # Dedup preserve order
    out: List[str] = []
    for r in reasons:
        if r and r not in out:
            out.append(r)
    return out or ["no_mutual"]


def format_twp_executed_events_line(
    proposal: Any,
    *,
    unlocked_action: str = "",
    need_reduced: int = 0,
    fills_live_need: bool = False,
    total_score: Any = None,
) -> str:
    """T11 Events: ``TwP: 1Sh→1Wh unlock settle (P1→P3) score=2.1``."""
    data = _proposal_mapping(proposal)
    try:
        gi = int(data.get("active_give_index", 0) or 0)
        gc = int(data.get("active_give_count", 0) or 0)
        ri = int(data.get("active_receive_index", 0) or 0)
        rc = int(data.get("active_receive_count", 0) or 0)
        g_name = RESOURCE_ABBR[gi] if 0 <= gi < 5 else "?"
        r_name = RESOURCE_ABBR[ri] if 0 <= ri < 5 else "?"
        aid = data.get("active_player_id")
        cid = data.get("counterparty_id")
        package = f"{gc}{g_name}→{rc}{r_name}"
    except Exception:
        package = "?"
        aid = data.get("active_player_id")
        cid = data.get("counterparty_id")

    why_bits: List[str] = []
    snap = data.get("market_snapshot") if isinstance(data.get("market_snapshot"), Mapping) else {}
    if unlocked_action:
        short = str(unlocked_action).replace("Build ", "").replace("Buy ", "").strip().lower()
        why_bits.append(f"unlock {short}")
    elif fills_live_need or snap.get("fills_live_need") or int(need_reduced or 0) > 0:
        act = str(snap.get("live_need_action") or snap.get("active_primary_action") or "need")
        short = act.replace("Build ", "").replace("Buy ", "").strip().lower() or "need"
        why_bits.append(f"fill {short}")
    elif snap.get("fully_unlocks") or snap.get("t3_active_completes"):
        why_bits.append("unlock")
    why = (" " + " ".join(why_bits)) if why_bits else ""

    seats = ""
    try:
        if aid is not None and cid is not None:
            seats = f" (P{int(aid)}→P{int(cid)})"
    except Exception:
        seats = ""

    score_txt = ""
    try:
        sc = total_score if total_score is not None else data.get("total_score")
        if sc is not None and sc != "":
            score_txt = f" score={float(sc):.1f}"
    except Exception:
        score_txt = ""

    line = f"TwP: {package}{why}{seats}{score_txt}"
    return line if len(line) <= 180 else line[:177] + "..."


def find_twp_proposals(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
    include_human_counterparties: bool = True,
    market: Optional[ResourceMarket] = None,
    max_per_counterparty: int = MAX_PROPOSALS_PER_COUNTERPARTY,
) -> List[TradeProposal]:
    """Generate and score Version-1+ TwP proposals for the active player.

    T3: counterparty accept model filters unlikely deals; rate limits cap spam
    per partner and after multiple accepted trades this turn.
    T11: unlock generation uses Game live_need; tags fills_live_need for rank.
    """

    active = _resolve_player(game, active_player)
    if active is None:
        return []

    board = getattr(game, "board", None)
    market = market or build_resource_market(game, board=board)
    active_profile = build_trade_profile(game, active, market=market)
    active_id = _player_id(active)
    support_action, support_cost, live_need = resolve_live_need_for_twp(
        game, active, active_profile=active_profile
    )
    # Prefer live_need as unlock missing when non-empty
    unlock_missing = live_need if sum(live_need) > 0 else None
    unlock_cost = support_cost if sum(live_need) > 0 and sum(support_cost) > 0 else None
    unlock_action = support_action if support_action else None

    # T3 rate limit: after hard cap of accepted TwPs this turn, stop offering more
    accepted_count = _accepted_twp_count_for_active_player_this_turn(game, active_id)
    if accepted_count >= MAX_ACCEPTED_TWP_PER_ACTIVE_TURN:
        try:
            setattr(
                game,
                "last_twp_empty_diagnosis",
                diagnose_twp_empty(
                    game,
                    active,
                    active_profile=active_profile,
                    live_need=live_need,
                    accepted_cap=True,
                ),
            )
        except Exception:
            pass
        return []

    # T9: skip all TwP if the active player is already a potential winner
    frozen_active = False
    try:
        from core.human_twp_policy import (
            is_potential_winner_twp_freeze,
            players_hit_twp_endgame_freeze,
        )

        if is_potential_winner_twp_freeze(active):
            frozen_active = True
            try:
                setattr(
                    game,
                    "last_twp_empty_diagnosis",
                    diagnose_twp_empty(
                        game,
                        active,
                        active_profile=active_profile,
                        live_need=live_need,
                        frozen_active=True,
                    ),
                )
            except Exception:
                pass
            return []
    except Exception:
        is_potential_winner_twp_freeze = None  # type: ignore
        players_hit_twp_endgame_freeze = None  # type: ignore

    proposals: List[TradeProposal] = []
    for counterparty in list(getattr(game, "players", []) or []):
        if counterparty is None or _player_id(counterparty) == active_id:
            continue
        if (not include_human_counterparties) and bool(getattr(counterparty, "is_human", False)):
            continue
        # T9: no deals with a potential-winner counterparty
        try:
            if players_hit_twp_endgame_freeze is not None and players_hit_twp_endgame_freeze(
                game, active, counterparty
            ):
                continue
        except Exception:
            pass
        counter_profile = build_trade_profile(game, counterparty, market=market)
        proposals.extend(_generate_pair_proposals(active_profile, counter_profile, market, game=game))

    proposals = [p for p in proposals if p.status == "candidate"]
    proposals = [
        p for p in proposals
        if not _is_inverse_of_recent_accepted_twp(game, p)[0]
    ]
    mutual_count = len(proposals)
    # After one accepted trade, only keep proposals that look like unlocks
    # (high active score / market snapshot reasons handled in generation)
    if accepted_count >= STRICT_ACCEPTED_TWP_PER_ACTIVE_TURN:
        proposals = [p for p in proposals if float(p.active_score) >= 1.0]

    # T1-B (Q2): always merge unlock candidates with mutual pool (not empty-only)
    # T11: pass live_need so unlock aligns with supporting action
    unlock_list: List[TradeProposal] = []
    try:
        unlock_list = list(
            find_unlock_twp_proposals(
                game,
                active,
                max_candidates=max(12, int(max_candidates or 12)),
                include_human_counterparties=include_human_counterparties,
                market=market,
                live_need=unlock_missing,
                primary_cost=unlock_cost,
                primary_action=unlock_action,
            )
            or []
        )
    except TypeError:
        # Older signature without live_need kwargs
        try:
            unlock_list = list(
                find_unlock_twp_proposals(
                    game,
                    active,
                    max_candidates=max(12, int(max_candidates or 12)),
                    include_human_counterparties=include_human_counterparties,
                    market=market,
                )
                or []
            )
        except Exception:
            unlock_list = []
    except Exception:
        unlock_list = []
    unlock_count = len(unlock_list)
    proposals = merge_mutual_and_unlock_proposals(
        proposals, unlock_list, game=game, active_profile=active_profile
    )
    # T11: tag live_need fill for rank (boost packages that reduce support need)
    proposals = annotate_proposals_with_live_need(
        proposals, live_need, support_action=support_action
    )

    # T8 belt: drop exact declined keys so they never rank
    try:
        from core.human_twp_policy import is_proposal_declined_this_turn

        proposals = [
            p for p in proposals if not is_proposal_declined_this_turn(game, p)
        ]
    except Exception:
        pass

    # T1-B (Q7): after HP declines 1:1, boost same-pair 2:1 / 1:2 once
    proposals = apply_decline_escalation_boosts(game, proposals)

    # T1-A: shared package-quality rank (unlock / ditch / score / lowest VP / RNG)
    proposals = sort_proposals_by_package_quality(
        proposals,
        game=game,
        active_profile=active_profile,
        live_need=live_need,
    )
    # T3: diversify — top N per counterparty before global cap
    proposals = _rate_limit_proposals_per_counterparty(
        proposals,
        max_per=max(1, int(max_per_counterparty or MAX_PROPOSALS_PER_COUNTERPARTY)),
        game=game,
        active_profile=active_profile,
    )
    proposals = proposals[: max(0, int(max_candidates))]
    if not proposals:
        try:
            setattr(
                game,
                "last_twp_empty_diagnosis",
                diagnose_twp_empty(
                    game,
                    active,
                    active_profile=active_profile,
                    live_need=live_need,
                    mutual_count=mutual_count,
                    unlock_count=unlock_count,
                    frozen_active=frozen_active,
                ),
            )
            setattr(game, "last_twp_live_need", list(live_need))
            setattr(game, "last_twp_support_action", str(support_action or ""))
        except Exception:
            pass
    else:
        try:
            setattr(game, "last_twp_empty_diagnosis", None)
            setattr(game, "last_twp_live_need", list(live_need))
            setattr(game, "last_twp_support_action", str(support_action or ""))
        except Exception:
            pass
    return proposals


def find_unlock_twp_proposals(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    max_candidates: int = 12,
    include_human_counterparties: bool = True,
    market: Optional[ResourceMarket] = None,
    live_need: Optional[Sequence[int]] = None,
    primary_cost: Optional[Sequence[int]] = None,
    primary_action: Optional[str] = None,
) -> List[TradeProposal]:
    """Generate project-unlock TwP deals without full mutual-appetite gates.

    For each resource still missing for the active player's *immediate* supporting
    action (road / settle / city / dcard), look for counterparties who can spare
    that resource and who will take our surplus/ditch. Prefer 1:1; allow 1:2 when
    the counterparty has two spare of our need (e.g. Wd → 2B).

    T11: optional ``live_need`` / ``primary_cost`` override aligns unlock with
    Game supporting-action vector when profile primary_missing is stale.

    Does not strip a counterparty's last primary-keep unit for a resource they
    still need for their own primary action.
    """
    active = _resolve_player(game, active_player)
    if active is None:
        return []
    board = getattr(game, "board", None)
    market = market or build_resource_market(game, board=board)
    # Rebuild profile with live support cost when provided (T11)
    if primary_cost is not None or primary_action is not None:
        active_profile = build_trade_profile(
            game,
            active,
            market=market,
            primary_cost=primary_cost,
            primary_action=primary_action,
        )
    else:
        active_profile = build_trade_profile(game, active, market=market)
    active_id = _player_id(active)

    if live_need is not None:
        missing = [max(0, int(x or 0)) for x in list(live_need)[:5]]
    else:
        missing = [max(0, int(x or 0)) for x in list(active_profile.primary_missing)[:5]]
    while len(missing) < 5:
        missing.append(0)
    if sum(missing) <= 0:
        return []

    hand = [max(0, int(x or 0)) for x in list(active_profile.hand)[:5]]
    while len(hand) < 5:
        hand.append(0)
    ditch = [max(0, int(x or 0)) for x in list(active_profile.ditch_resource_vector)[:5]]
    while len(ditch) < 5:
        ditch.append(0)
    keep = [max(0, int(x or 0)) for x in list(active_profile.keep_resource_vector)[:5]]
    while len(keep) < 5:
        keep.append(0)
    # Offerable: ditch first, then clear surplus beyond keep
    offerable = [0, 0, 0, 0, 0]
    for i in range(5):
        offerable[i] = max(ditch[i], max(0, hand[i] - keep[i]))
        offerable[i] = min(offerable[i], hand[i])

    if sum(offerable) <= 0:
        return []

    try:
        from core.human_twp_policy import (
            is_potential_winner_twp_freeze,
            players_hit_twp_endgame_freeze,
        )

        if is_potential_winner_twp_freeze(active):
            return []
    except Exception:
        players_hit_twp_endgame_freeze = None  # type: ignore

    ranked: List[Tuple[Tuple[Any, ...], TradeProposal]] = []
    for counterparty in list(getattr(game, "players", []) or []):
        if counterparty is None or _player_id(counterparty) == active_id:
            continue
        if (not include_human_counterparties) and bool(getattr(counterparty, "is_human", False)):
            continue
        try:
            if players_hit_twp_endgame_freeze is not None and players_hit_twp_endgame_freeze(
                game, active, counterparty
            ):
                continue
        except Exception:
            pass
        counter = build_trade_profile(game, counterparty, market=market)
        c_hand = [max(0, int(x or 0)) for x in list(counter.hand)[:5]]
        while len(c_hand) < 5:
            c_hand.append(0)
        c_missing = [max(0, int(x or 0)) for x in list(counter.primary_missing)[:5]]
        while len(c_missing) < 5:
            c_missing.append(0)
        c_keep = [max(0, int(x or 0)) for x in list(counter.keep_resource_vector)[:5]]
        while len(c_keep) < 5:
            c_keep.append(0)
        c_cost = [max(0, int(x or 0)) for x in list(counter.primary_cost)[:5]]
        while len(c_cost) < 5:
            c_cost.append(0)

        for get_idx in range(5):
            if missing[get_idx] <= 0:
                continue
            for give_idx in range(5):
                if give_idx == get_idx or offerable[give_idx] <= 0:
                    continue
                # Quantity patterns: 1:1 primary; 1:2 if they have spare stack
                patterns: List[Tuple[int, int, str]] = [(1, 1, TRADE_NORMAL_1_FOR_1)]
                if c_hand[get_idx] >= 2 and missing[get_idx] >= 1:
                    patterns.append((1, 2, TRADE_SCARCITY_PREMIUM_1_FOR_2))
                if offerable[give_idx] >= 2:
                    patterns.append((2, 1, TRADE_TEMPTING_2_FOR_1))

                for give_count, receive_count, trade_type in patterns:
                    if hand[give_idx] < give_count or offerable[give_idx] < give_count:
                        continue
                    if c_hand[get_idx] < receive_count:
                        continue
                    # Don't take units the counter still needs for *their* primary
                    # unless they keep enough after the gift.
                    c_after_need_res = c_hand[get_idx] - receive_count
                    if c_missing[get_idx] > 0 and c_after_need_res < c_missing[get_idx]:
                        continue
                    if c_keep[get_idx] > 0 and c_after_need_res < min(c_keep[get_idx], c_cost[get_idx]):
                        # Soft: allow if they retain at least one keep unit or zero cost
                        if c_cost[get_idx] > 0 and c_after_need_res < 1:
                            continue

                    # Active hand after
                    a_after = list(hand)
                    a_after[give_idx] -= give_count
                    a_after[get_idx] += receive_count
                    if a_after[give_idx] < 0:
                        continue
                    need_before = sum(missing)
                    # After receive, reduce live_need / cost shortfall on get_idx
                    need_after_list = list(missing)
                    need_after_list[get_idx] = max(
                        0, int(need_after_list[get_idx] or 0) - int(receive_count)
                    )
                    need_after = sum(need_after_list)
                    need_reduced = need_before - need_after
                    if need_reduced <= 0:
                        continue
                    fully = need_after <= 0

                    ditch_safe = give_count <= int(ditch[give_idx] or 0)
                    # Scores: unlock-biased; mild counterparty goodwill if they receive
                    # a resource they are missing
                    active_score = 2.5 * need_reduced + (4.0 if fully else 0.0)
                    if ditch_safe:
                        active_score += 0.5
                    counter_score = 0.4
                    if c_missing[give_idx] > 0:
                        counter_score += 1.2 * min(give_count, c_missing[give_idx])
                    if float(counter.production_pips[get_idx] or 0) >= DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
                        counter_score += 0.3  # they can replace what they gave
                    total_score = active_score + counter_score

                    requires_human = bool(active_profile.is_human or counter.is_human)
                    active_gain = [0, 0, 0, 0, 0]
                    counter_gain = [0, 0, 0, 0, 0]
                    active_gain[give_idx] -= give_count
                    active_gain[get_idx] += receive_count
                    counter_gain[give_idx] += give_count
                    counter_gain[get_idx] -= receive_count

                    prop = TradeProposal(
                        active_player_id=active_id,
                        counterparty_id=_player_id(counterparty),
                        active_player_is_human=bool(active_profile.is_human),
                        counterparty_is_human=bool(counter.is_human),
                        trade_type=trade_type,
                        active_give_index=int(give_idx),
                        active_give_count=int(give_count),
                        active_receive_index=int(get_idx),
                        active_receive_count=int(receive_count),
                        active_score=round(float(active_score), 4),
                        counterparty_score=round(float(counter_score), 4),
                        total_score=round(float(total_score), 4),
                        active_gain_vector=_tuple5_int(active_gain, default=0),
                        counterparty_gain_vector=_tuple5_int(counter_gain, default=0),
                        active_offer_appetite=max(2, int(active_profile.offer_appetite[give_idx] or 0)),
                        active_accept_appetite=1,
                        counterparty_offer_appetite=2,
                        counterparty_accept_appetite=max(1, int(counter.accept_appetite[give_idx] or 0)),
                        requires_human_confirmation=requires_human,
                        auto_executable=not requires_human,
                        status="candidate",
                        reasons=(
                            "unlock_fallback",
                            f"fills {need_reduced} toward {active_profile.primary_action}",
                            f"{'full unlock' if fully else 'partial unlock'}",
                            f"give {RESOURCE_NAMES[give_idx]}×{give_count}",
                            f"get {RESOURCE_NAMES[get_idx]}×{receive_count}",
                            "T11: live_need",
                        ),
                        market_snapshot={
                            "source": "unlock_fallback",
                            "active_primary_action": active_profile.primary_action,
                            "counterparty_primary_action": counter.primary_action,
                            "need_reduced": int(need_reduced),
                            "fully_unlocks": bool(fully),
                            "ditch_safe": bool(ditch_safe),
                            "fills_live_need": True,
                            "live_need_filled": int(need_reduced),
                            "t11": True,
                        },
                    )
                    # Lower rank key is better. Prefer 1:1 before 2:1 when unlock
                    # quality matches (give_count - receive_count); total_score last.
                    rank = (
                        0 if fully else 1,
                        -need_reduced,
                        0 if ditch_safe else 1,
                        max(0, int(give_count) - int(receive_count)),
                        -total_score,
                        _player_id(counterparty),
                        give_idx,
                        get_idx,
                    )
                    ranked.append((rank, prop))

    if not ranked:
        return []
    ranked.sort(key=lambda item: item[0])
    out: List[TradeProposal] = []
    seen: set = set()
    for _rank, prop in ranked:
        key = (
            prop.counterparty_id,
            prop.active_give_index,
            prop.active_give_count,
            prop.active_receive_index,
            prop.active_receive_count,
        )
        if key in seen:
            continue
        seen.add(key)
        if _is_inverse_of_recent_accepted_twp(game, prop)[0]:
            continue
        out.append(prop)
        if len(out) >= max(0, int(max_candidates)):
            break
    return out


def choose_best_twp_proposal(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    ai_only: bool = False,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
) -> Optional[TradeProposal]:
    """Return the highest-scoring proposal, optionally requiring AI-vs-AI."""

    proposals = find_twp_proposals(
        game,
        active_player,
        max_candidates=max_candidates,
        include_human_counterparties=not ai_only,
    )
    if ai_only:
        proposals = [p for p in proposals if p.auto_executable]
    return proposals[0] if proposals else None


def evaluate_twp_offer(
    game: Any,
    *,
    active_player: Any,
    counterparty: Any,
    active_give_index: int,
    active_give_count: int,
    active_receive_index: int,
    active_receive_count: int,
) -> TradeDecision:
    """Evaluate a concrete offer without executing it.

    This is useful when the future TwP panel submits a human-created offer.
    """

    market = build_resource_market(game, board=getattr(game, "board", None))
    active_profile = build_trade_profile(game, active_player, market=market)
    counter_profile = build_trade_profile(game, counterparty, market=market)
    trade_type = _classify_quantity_pattern(active_give_count, active_receive_count)
    if trade_type is None:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason=(
                "Unsupported TwP shape for Version 1+: only 1:1, 2:1, and "
                "guarded 1:2 trades are supported."
            ),
        )
    proposal = _build_proposal(
        active=active_profile,
        counter=counter_profile,
        give_idx=int(active_give_index),
        give_count=int(active_give_count),
        receive_idx=int(active_receive_index),
        receive_count=int(active_receive_count),
        trade_type=trade_type,
        market=market,
        game=game,
    )
    if proposal is None:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason="Offer fails card availability, appetite, or scarcity/abundance guard rails.",
        )

    inverse_blocked, inverse_reason = _is_inverse_of_recent_accepted_twp(game, proposal)
    if inverse_blocked:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=proposal,
            reason=inverse_reason,
        )

    return TradeDecision(
        accepted=True,
        executed=False,
        proposal=proposal,
        reason="Offer is acceptable according to the Version-1+ TwP scoring rules.",
    )


def trade_proposal_from_dict(data: Mapping[str, Any]) -> TradeProposal:
    """Rebuild a TradeProposal from its JSON-friendly dictionary form.

    Game stores the chosen TwP candidate in ``current_best_action`` as a
    dictionary so it can be displayed in the Execution Debug panel.  Continue
    should execute that exact frozen proposal rather than re-selecting a possibly
    different trade at click time.
    """

    if not isinstance(data, Mapping):
        raise TypeError("TradeProposal data must be a mapping")

    tuple_fields = {
        "active_gain_vector",
        "counterparty_gain_vector",
        "reasons",
    }
    kwargs: Dict[str, Any] = {}
    valid_names = {f.name for f in fields(TradeProposal)}
    for name in valid_names:
        if name not in data:
            continue
        value = data[name]
        if name in tuple_fields and not isinstance(value, tuple):
            value = tuple(value or [])
        kwargs[name] = value

    # field(default=...) values are not filled when we manually call the
    # dataclass constructor through kwargs, so provide the stable defaults here.
    kwargs.setdefault("status", "candidate")
    kwargs.setdefault("reasons", tuple())
    kwargs.setdefault("market_snapshot", {})

    return TradeProposal(**kwargs)  # type: ignore[arg-type]


def execute_twp_trade_from_dict(
    game: Any,
    proposal_data: Mapping[str, Any],
    *,
    require_human_confirmation: bool = True,
) -> TradeDecision:
    """Execute a TwP proposal previously returned by ``proposal.as_dict()``."""

    try:
        proposal = trade_proposal_from_dict(proposal_data)
    except Exception as exc:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason=f"Invalid TwP proposal dictionary: {exc}",
        )
    return execute_twp_trade(
        game,
        proposal,
        require_human_confirmation=require_human_confirmation,
    )


def execute_twp_trade(
    game: Any,
    proposal: TradeProposal,
    *,
    require_human_confirmation: bool = True,
) -> TradeDecision:
    """Execute a concrete TwP proposal by mutating both players' resource cards.

    Human-involved trades are not executed when ``require_human_confirmation`` is
    true.  The GUI/panel should call this again after confirmation.
    """

    if proposal is None:
        return TradeDecision(False, False, None, "No proposal supplied.")
    if require_human_confirmation and proposal.requires_human_confirmation:
        return TradeDecision(
            accepted=True,
            executed=False,
            proposal=proposal,
            reason="Human confirmation required before executing this TwP deal.",
        )

    inverse_blocked, inverse_reason = _is_inverse_of_recent_accepted_twp(game, proposal)
    if inverse_blocked:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=proposal,
            reason=inverse_reason,
        )

    active = _player_by_id(game, proposal.active_player_id)
    counter = _player_by_id(game, proposal.counterparty_id)
    if active is None or counter is None:
        return TradeDecision(False, False, proposal, "Active player or counterparty not found.")

    if not _has_cards(active, proposal.active_give_index, proposal.active_give_count):
        return TradeDecision(False, False, proposal, "Active player no longer has the offered cards.")
    if not _has_cards(counter, proposal.active_receive_index, proposal.active_receive_count):
        return TradeDecision(False, False, proposal, "Counterparty no longer has the requested cards.")

    _add_resource(active, proposal.active_give_index, -proposal.active_give_count)
    _add_resource(counter, proposal.active_give_index, proposal.active_give_count)
    _add_resource(counter, proposal.active_receive_index, -proposal.active_receive_count)
    _add_resource(active, proposal.active_receive_index, proposal.active_receive_count)

    _sync_number_of_rcards(active)
    _sync_number_of_rcards(counter)
    _record_twp_turn_details(game, active, counter, proposal)
    _play_twp_success_sound(game, proposal)

    try:
        from core import mglog

        give_v = [0, 0, 0, 0, 0]
        get_v = [0, 0, 0, 0, 0]
        try:
            gi = int(proposal.active_give_index)
            ri = int(proposal.active_receive_index)
            if 0 <= gi < 5:
                give_v[gi] = int(proposal.active_give_count or 0)
            if 0 <= ri < 5:
                get_v[ri] = int(proposal.active_receive_count or 0)
        except Exception:
            pass
        mglog.log_twp(
            game,
            active,
            getattr(proposal, "counterparty_id", None),
            give_v,
            get_v,
            source="execute_twp_trade",
        )
    except Exception:
        pass

    return TradeDecision(
        accepted=True,
        executed=True,
        proposal=proposal,
        reason=f"Executed TwP: {proposal.description}.",
    )



# ──────────────────────────────────────────────────────────────────────────────
# Human TwP wildcard panel support
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HumanTwPOption:
    """Concrete option produced from one human TwP wildcard request.

    The human/proposer always receives ``counterparty_gives`` and gives
    ``proposer_gives``.  Wildcards never enter the resource vectors; they are
    expanded here into ordinary [Wheat, Ore, Wood, Brick, Sheep] vectors.
    """

    proposer_id: int
    counterparty_id: int
    proposer_gives: Tuple[int, int, int, int, int]
    counterparty_gives: Tuple[int, int, int, int, int]
    score: float = 0.0
    reason: str = ""

    @property
    def description(self) -> str:
        return (
            f"P{self.proposer_id}: {_format_vector_amounts(self.proposer_gives)}"
            f" -> {_format_vector_amounts(self.counterparty_gives)} with P{self.counterparty_id}"
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "proposer_id": int(self.proposer_id),
            "counterparty_id": int(self.counterparty_id),
            "proposer_gives": list(self.proposer_gives),
            "counterparty_gives": list(self.counterparty_gives),
            "human_gives": list(self.proposer_gives),
            "human_receives": list(self.counterparty_gives),
            "score": round(float(self.score), 4),
            "reason": str(self.reason or ""),
            "description": self.description,
            "resource_order": list(RESOURCE_NAMES),
        }


def find_human_twp_responder_options(
    game: Any,
    *,
    proposer_id: Optional[int] = None,
    offer_exact: Optional[Sequence[Any]] = None,
    offer_wildcard_count: int = 0,
    offer_wildcard_allowed: Optional[Sequence[Any]] = None,
    request_exact: Optional[Sequence[Any]] = None,
    request_wildcard_count: int = 0,
    request_wildcard_allowed: Optional[Sequence[Any]] = None,
    include_human_counterparties: bool = False,
    max_options_per_counterparty: int = 3,
    max_total_options: int = 12,
) -> Dict[str, Any]:
    """Expand a Human TwP wildcard request and find willing AI counterparties.

    Semantics of ``?`` follow the Layer 4 design:

    * If ``?`` is on the human-offer side, the opponent chooses which allowed
      resource the human pays.  The option exists only when the human has that
      concrete card combination.
    * If ``?`` is on the request side, the opponent chooses which allowed
      resource it gives.  The option exists only when the opponent has that
      concrete card combination.
    * When multiple opponents/options are possible, the GUI shows all options and
      the human chooses one or NOK.

    HP-to-HP confirmation is intentionally out of scope for this Layer 4A/4B
    update, so human counterparties are skipped by default.

    H-A: also returns ``offer_scan`` — per-AI accept/decline audit (instrumentation
    only; willingness math unchanged).
    """
    from core.human_twp_offer_audit import (
        MAX_DECLINED_PACKAGES_PER_AI,
        REASON_ACCEPTED,
        REASON_DECLINED_CANNOT_PAY,
        REASON_DECLINED_EMPTY_PACKAGE,
        REASON_DECLINED_SAME_RESOURCE,
        REASON_DECLINED_T9_FREEZE,
        REASON_ERROR_PROFILE,
        REASON_SCAN_NO_OFFER_WC_ALLOWED,
        REASON_SCAN_NO_REQUEST_WC_ALLOWED,
        REASON_SCAN_NOTHING_OFFERED,
        REASON_SCAN_NOTHING_REQUESTED,
        REASON_SCAN_PROPOSER_LACKS,
        REASON_SCAN_PROPOSER_NOT_FOUND,
        REASON_SCAN_T9_FREEZE_PROPOSER,
        REASON_SKIPPED_HUMAN,
        build_human_twp_offer_request,
        build_human_twp_offer_scan,
        classify_human_twp_willingness_reason,
        empty_offer_scan_for_early_exit,
        make_ai_evaluation,
        next_scan_id,
        profile_digest_from_trade_profile,
    )

    try:
        from core.human_twp_policy import (
            is_potential_winner_twp_freeze,
            players_hit_twp_endgame_freeze,
            projected_vp_for_twp_freeze,
        )
    except Exception:
        is_potential_winner_twp_freeze = None  # type: ignore
        players_hit_twp_endgame_freeze = None  # type: ignore
        projected_vp_for_twp_freeze = None  # type: ignore

    def _early(
        reason: str,
        *,
        proposer: Any = None,
        proposer_id_int: int = 0,
        hand: Optional[Sequence[Any]] = None,
        offer_vec: Optional[Sequence[Any]] = None,
        request_vec: Optional[Sequence[Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        pid = int(proposer_id_int or 0)
        color = ""
        try:
            if proposer is not None:
                color = str(getattr(proposer, "color", "") or "")
                if pid <= 0:
                    pid = _player_id(proposer)
        except Exception:
            pass
        scan = empty_offer_scan_for_early_exit(
            game,
            proposer_id=pid,
            proposer_color=color,
            proposer_hand=hand,
            offer_exact=offer_vec if offer_vec is not None else offer_exact,
            request_exact=request_vec if request_vec is not None else request_exact,
            offer_wildcard_count=offer_wildcard_count,
            request_wildcard_count=request_wildcard_count,
            offer_wildcard_allowed=offer_wildcard_allowed,
            request_wildcard_allowed=request_wildcard_allowed,
            scan_reason=reason,
        )
        out: Dict[str, Any] = {
            "ok": False,
            "reason": reason,
            "options": [],
            "resource_order": list(RESOURCE_NAMES),
            "offer_scan": scan,
        }
        if extra:
            out.update(extra)
        return out

    proposer = _player_by_id(game, int(proposer_id)) if proposer_id is not None else _resolve_player(game, None)
    if proposer is None:
        return _early(REASON_SCAN_PROPOSER_NOT_FOUND, proposer_id_int=int(proposer_id or 0))

    proposer_id_int = _player_id(proposer)
    proposer_color = str(getattr(proposer, "color", "") or "")
    offer_vec = _list5_int(offer_exact, default=0)
    request_vec = _list5_int(request_exact, default=0)
    offer_wc = max(0, int(offer_wildcard_count or 0))
    request_wc = max(0, int(request_wildcard_count or 0))
    offer_allowed = _allowed_indices_from_flags(offer_wildcard_allowed)
    request_allowed = _allowed_indices_from_flags(request_wildcard_allowed)

    if sum(offer_vec) + offer_wc <= 0:
        return _early(
            REASON_SCAN_NOTHING_OFFERED,
            proposer=proposer,
            proposer_id_int=proposer_id_int,
            offer_vec=offer_vec,
            request_vec=request_vec,
        )
    if sum(request_vec) + request_wc <= 0:
        return _early(
            REASON_SCAN_NOTHING_REQUESTED,
            proposer=proposer,
            proposer_id_int=proposer_id_int,
            offer_vec=offer_vec,
            request_vec=request_vec,
        )
    if offer_wc > 0 and not offer_allowed:
        return _early(
            REASON_SCAN_NO_OFFER_WC_ALLOWED,
            proposer=proposer,
            proposer_id_int=proposer_id_int,
            offer_vec=offer_vec,
            request_vec=request_vec,
        )
    if request_wc > 0 and not request_allowed:
        return _early(
            REASON_SCAN_NO_REQUEST_WC_ALLOWED,
            proposer=proposer,
            proposer_id_int=proposer_id_int,
            offer_vec=offer_vec,
            request_vec=request_vec,
        )

    proposer_hand = _get_hand(proposer)
    if not _vector_leq(offer_vec, proposer_hand):
        return _early(
            REASON_SCAN_PROPOSER_LACKS,
            proposer=proposer,
            proposer_id_int=proposer_id_int,
            hand=proposer_hand,
            offer_vec=offer_vec,
            request_vec=request_vec,
            extra={"hand": list(proposer_hand), "offer_exact": list(offer_vec)},
        )

    # T9: HP→AI offers — if the human proposer is already a potential winner
    # (projected VP > 6), no AI may accept. Same rule as AI→HP / AI↔AI paths.
    if is_potential_winner_twp_freeze is not None and is_potential_winner_twp_freeze(proposer):
        try:
            pvp = (
                int(projected_vp_for_twp_freeze(proposer))
                if projected_vp_for_twp_freeze is not None
                else None
            )
        except Exception:
            pvp = None
        return _early(
            REASON_SCAN_T9_FREEZE_PROPOSER,
            proposer=proposer,
            proposer_id_int=proposer_id_int,
            hand=proposer_hand,
            offer_vec=offer_vec,
            request_vec=request_vec,
            extra={
                "endgame_freeze": True,
                "proposer_projected_vp": pvp,
                "reason_detail": "endgame_twp_freeze_proposer",
            },
        )

    market = build_resource_market(game, board=getattr(game, "board", None))
    try:
        proposer_profile = build_trade_profile(game, proposer, market=market)
    except Exception:
        proposer_profile = None

    options: List[HumanTwPOption] = []
    skipped_human_counterparties: List[int] = []
    evaluations: List[Dict[str, Any]] = []
    scan_id = next_scan_id(game, proposer_id_int)
    request_snap = build_human_twp_offer_request(
        game,
        proposer_id=proposer_id_int,
        proposer_color=proposer_color,
        proposer_hand=proposer_hand,
        offer_exact=offer_vec,
        request_exact=request_vec,
        offer_wildcard_count=offer_wc,
        request_wildcard_count=request_wc,
        offer_wildcard_allowed=offer_wildcard_allowed,
        request_wildcard_allowed=request_wildcard_allowed,
    )

    for counter in list(getattr(game, "players", []) or []):
        if counter is None:
            continue
        counter_id = _player_id(counter)
        if counter_id <= 0:
            continue
        if counter_id == proposer_id_int:
            continue
        counter_color = str(getattr(counter, "color", "") or "")
        if _player_is_human(counter) and not include_human_counterparties:
            skipped_human_counterparties.append(counter_id)
            evaluations.append(
                make_ai_evaluation(
                    counterparty_id=counter_id,
                    counterparty_color=counter_color,
                    outcome="skipped",
                    reason_code=REASON_SKIPPED_HUMAN,
                    reason_text="HP↔HP deferred",
                    hand=_get_hand(counter),
                    can_pay_request=False,
                )
            )
            continue

        counter_hand = _get_hand(counter)
        can_pay = _vector_leq(request_vec, counter_hand)
        if not can_pay:
            evaluations.append(
                make_ai_evaluation(
                    counterparty_id=counter_id,
                    counterparty_color=counter_color,
                    outcome="declined",
                    reason_code=REASON_DECLINED_CANNOT_PAY,
                    reason_text="counterparty lacks requested cards",
                    hand=counter_hand,
                    can_pay_request=False,
                    packages_tried=0,
                )
            )
            continue

        # T9: freeze when the AI counterparty is a potential winner (or pair
        # still hits freeze for any other reason). Proposer-level freeze is
        # handled earlier; this covers AI leaders accepting from a low-VP HP.
        if players_hit_twp_endgame_freeze is not None and players_hit_twp_endgame_freeze(
            game, proposer, counter
        ):
            try:
                c_vp = (
                    int(projected_vp_for_twp_freeze(counter))
                    if projected_vp_for_twp_freeze is not None
                    else None
                )
            except Exception:
                c_vp = None
            evaluations.append(
                make_ai_evaluation(
                    counterparty_id=counter_id,
                    counterparty_color=counter_color,
                    outcome="declined",
                    reason_code=REASON_DECLINED_T9_FREEZE,
                    reason_text="endgame_twp_freeze_counterparty",
                    hand=counter_hand,
                    can_pay_request=True,
                    packages_tried=0,
                    best_package=None,
                    declined_packages=[
                        {
                            "reason_code": REASON_DECLINED_T9_FREEZE,
                            "reason_text": "endgame_twp_freeze_counterparty",
                            "counterparty_projected_vp": c_vp,
                            "score": None,
                        }
                    ],
                )
            )
            continue

        profile_error = False
        try:
            counter_profile = build_trade_profile(game, counter, market=market)
        except Exception:
            counter_profile = None
            profile_error = True

        digest = profile_digest_from_trade_profile(counter_profile)
        human_remaining = [max(0, proposer_hand[i] - offer_vec[i]) for i in range(5)]
        counter_remaining = [max(0, counter_hand[i] - request_vec[i]) for i in range(5)]

        offer_combos = _wildcard_combo_vectors(
            offer_wc,
            offer_allowed,
            human_remaining,
            prefer_accept_profile=counter_profile,
            max_vectors=24,
            receives_from_human=True,
        )
        request_combos = _wildcard_combo_vectors(
            request_wc,
            request_allowed,
            counter_remaining,
            prefer_offer_profile=counter_profile,
            max_vectors=24,
            receives_from_human=False,
        )

        local: List[HumanTwPOption] = []
        declined_packages: List[Dict[str, Any]] = []
        packages_tried = 0
        best_decline_score: Optional[float] = None
        best_decline_text = ""
        best_decline_code = ""

        for offer_extra in offer_combos:
            proposer_gives = _add_vectors5(offer_vec, offer_extra)
            if not _vector_leq(proposer_gives, proposer_hand):
                continue
            for request_extra in request_combos:
                counterparty_gives = _add_vectors5(request_vec, request_extra)
                if not _vector_leq(counterparty_gives, counter_hand):
                    continue
                if not any(proposer_gives) or not any(counterparty_gives):
                    packages_tried += 1
                    if len(declined_packages) < MAX_DECLINED_PACKAGES_PER_AI:
                        declined_packages.append(
                            {
                                "proposer_gives": list(proposer_gives),
                                "counterparty_gives": list(counterparty_gives),
                                "reason_code": REASON_DECLINED_EMPTY_PACKAGE,
                                "reason_text": "empty package",
                                "score": None,
                            }
                        )
                    continue
                if _same_positive_resource_on_both_sides(proposer_gives, counterparty_gives):
                    # Avoid confusing no-op/netted deals in the first UI layer.
                    packages_tried += 1
                    if len(declined_packages) < MAX_DECLINED_PACKAGES_PER_AI:
                        declined_packages.append(
                            {
                                "proposer_gives": list(proposer_gives),
                                "counterparty_gives": list(counterparty_gives),
                                "reason_code": REASON_DECLINED_SAME_RESOURCE,
                                "reason_text": "same resource on both sides",
                                "score": None,
                            }
                        )
                    continue

                packages_tried += 1
                willing, reason, score = _human_twp_counterparty_willingness(
                    counter_profile=counter_profile,
                    proposer_profile=proposer_profile,
                    proposer_gives=proposer_gives,
                    counterparty_gives=counterparty_gives,
                    offer_wildcard_count=offer_wc,
                    request_wildcard_count=request_wc,
                )
                if not willing:
                    code = classify_human_twp_willingness_reason(reason, willing=False)
                    if len(declined_packages) < MAX_DECLINED_PACKAGES_PER_AI:
                        declined_packages.append(
                            {
                                "proposer_gives": list(proposer_gives),
                                "counterparty_gives": list(counterparty_gives),
                                "reason_code": code,
                                "reason_text": str(reason or ""),
                                "score": round(float(score), 4),
                            }
                        )
                    if best_decline_score is None or float(score) > float(best_decline_score):
                        best_decline_score = float(score)
                        best_decline_text = str(reason or "")
                        best_decline_code = code
                    continue
                local.append(
                    HumanTwPOption(
                        proposer_id=proposer_id_int,
                        counterparty_id=counter_id,
                        proposer_gives=_tuple5_int(proposer_gives),
                        counterparty_gives=_tuple5_int(counterparty_gives),
                        score=score,
                        reason=reason,
                    )
                )

        local.sort(key=lambda item: (-float(item.score), item.description))
        if local:
            best = local[0]
            evaluations.append(
                make_ai_evaluation(
                    counterparty_id=counter_id,
                    counterparty_color=counter_color,
                    outcome="accepted",
                    reason_code=REASON_ACCEPTED,
                    reason_text=str(best.reason or ""),
                    score=float(best.score),
                    hand=counter_hand,
                    can_pay_request=True,
                    packages_tried=packages_tried,
                    best_package={
                        "proposer_gives": list(best.proposer_gives),
                        "counterparty_gives": list(best.counterparty_gives),
                        "score": round(float(best.score), 4),
                        "reason_text": str(best.reason or ""),
                    },
                    declined_packages=declined_packages,
                    profile_digest=digest,
                )
            )
            options.extend(local[: max(1, int(max_options_per_counterparty or 1))])
        else:
            if best_decline_code:
                reason_code = best_decline_code
                reason_text = best_decline_text or "no willing package"
            elif profile_error and packages_tried == 0:
                reason_code = REASON_ERROR_PROFILE
                reason_text = "profile build failed"
            elif packages_tried == 0:
                reason_code = REASON_DECLINED_EMPTY_PACKAGE
                reason_text = "no concrete packages to evaluate"
            else:
                reason_code = classify_human_twp_willingness_reason(
                    best_decline_text, willing=False
                )
                reason_text = best_decline_text or "no willing package"
            evaluations.append(
                make_ai_evaluation(
                    counterparty_id=counter_id,
                    counterparty_color=counter_color,
                    outcome="declined",
                    reason_code=reason_code,
                    reason_text=reason_text,
                    score=best_decline_score,
                    hand=counter_hand,
                    can_pay_request=True,
                    packages_tried=packages_tried,
                    best_package=None,
                    declined_packages=declined_packages,
                    profile_digest=digest,
                )
            )

    # De-duplicate identical concrete options and keep the best scoring version.
    dedup: Dict[Tuple[int, Tuple[int, ...], Tuple[int, ...]], HumanTwPOption] = {}
    for option in options:
        key = (int(option.counterparty_id), tuple(option.proposer_gives), tuple(option.counterparty_gives))
        if key not in dedup or option.score > dedup[key].score:
            dedup[key] = option
    options = sorted(
        dedup.values(),
        key=lambda item: (-float(item.score), item.counterparty_id, item.description),
    )
    options = options[: max(1, int(max_total_options or 1))]

    accepted_dicts = [option.as_dict() for option in options]
    scan_reason = "options_found" if options else "no_willing_counterparty"
    offer_scan = build_human_twp_offer_scan(
        request=request_snap,
        evaluations=evaluations,
        accepted_options=accepted_dicts,
        scan_reason=scan_reason,
        scan_id=scan_id,
        skipped_human_counterparties=skipped_human_counterparties,
    )

    return {
        "ok": bool(options),
        "reason": scan_reason,
        "options": accepted_dicts,
        "skipped_human_counterparties": skipped_human_counterparties,
        "resource_order": list(RESOURCE_NAMES),
        "proposer_id": proposer_id_int,
        "offer_exact": list(offer_vec),
        "request_exact": list(request_vec),
        "offer_wildcard_count": offer_wc,
        "request_wildcard_count": request_wc,
        "offer_scan": offer_scan,
    }


def execute_human_twp_vector_trade(
    game: Any,
    *,
    proposer_id: int,
    counterparty_id: int,
    proposer_gives: Sequence[Any],
    counterparty_gives: Sequence[Any],
    source: str = "human_twp_panel",
    reason: str = "human_trade_with_player",
) -> Dict[str, Any]:
    """Execute a concrete Human TwP vector trade after GUI confirmation."""

    proposer = _player_by_id(game, int(proposer_id))
    counter = _player_by_id(game, int(counterparty_id))
    give_vec = _list5_int(proposer_gives, default=0)
    receive_vec = _list5_int(counterparty_gives, default=0)
    result: Dict[str, Any] = {
        "ok": False,
        "action": "TwP",
        "proposer_id": int(proposer_id),
        "counterparty_id": int(counterparty_id),
        "proposer_gives": list(give_vec),
        "counterparty_gives": list(receive_vec),
        "reason": "",
    }

    if proposer is None or counter is None:
        result["reason"] = "proposer_or_counterparty_not_found"
        return result
    if not any(give_vec):
        result["reason"] = "nothing_offered"
        return result
    if not any(receive_vec):
        result["reason"] = "nothing_requested"
        return result
    if _same_positive_resource_on_both_sides(give_vec, receive_vec):
        result["reason"] = "same_resource_on_both_sides"
        return result
    # T9 hard gate: never execute HP→AI (or any) grant when a side is a potential winner
    try:
        from core.human_twp_policy import players_hit_twp_endgame_freeze

        if players_hit_twp_endgame_freeze(game, proposer, counter):
            result["reason"] = "endgame_twp_freeze"
            return result
    except Exception:
        pass
    if not _vector_leq(give_vec, _get_hand(proposer)):
        result["reason"] = "proposer_lacks_cards"
        return result
    if not _vector_leq(receive_vec, _get_hand(counter)):
        result["reason"] = "counterparty_lacks_cards"
        return result

    for idx in range(5):
        if give_vec[idx]:
            _add_resource(proposer, idx, -give_vec[idx])
            _add_resource(counter, idx, give_vec[idx])
        if receive_vec[idx]:
            _add_resource(counter, idx, -receive_vec[idx])
            _add_resource(proposer, idx, receive_vec[idx])

    _sync_number_of_rcards(proposer)
    _sync_number_of_rcards(counter)

    proposer_delta = [int(receive_vec[i]) - int(give_vec[i]) for i in range(5)]
    counter_delta = [-int(x) for x in proposer_delta]
    message = f"TwP {_format_vector_amounts(give_vec)} -> {_format_vector_amounts(receive_vec)} with P{int(counterparty_id)}"
    metadata = {
        "proposer_id": int(proposer_id),
        "counterparty_id": int(counterparty_id),
        "proposer_gives": list(give_vec),
        "counterparty_gives": list(receive_vec),
        "human_gives": list(give_vec),
        "human_receives": list(receive_vec),
        "resource_order": list(RESOURCE_NAMES),
        "description": message,
    }
    _record_human_twp_vector_turn_details(
        game,
        proposer,
        counter,
        proposer_delta=proposer_delta,
        counter_delta=counter_delta,
        message=message,
        metadata=metadata,
        source=source,
        reason=reason,
    )
    _play_twp_success_sound(game, None)

    try:
        from core import mglog

        mglog.log_twp(
            game,
            proposer,
            int(counterparty_id),
            give_vec,
            receive_vec,
            source=str(source or "human_twp"),
        )
    except Exception:
        pass

    result.update({
        "ok": True,
        "reason": "executed",
        "message": message,
        "proposer_delta": proposer_delta,
        "counterparty_delta": counter_delta,
    })
    return result


def _player_is_human(player: Any) -> bool:
    try:
        return bool(getattr(player, "is_human", False))
    except Exception:
        return False


def _allowed_indices_from_flags(flags: Optional[Sequence[Any]]) -> List[int]:
    if flags is None:
        return list(range(5))
    values = list(flags)
    if not values:
        return []
    out: List[int] = []
    for idx, value in enumerate(values[:5]):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on", RESOURCE_NAMES[idx].lower(), RESOURCE_ABBR[idx].lower()}:
                out.append(idx)
        elif bool(value):
            out.append(idx)
    return out


def _vector_leq(left: Sequence[Any], right: Sequence[Any]) -> bool:
    a = _list5_int(left, default=0)
    b = _list5_int(right, default=0)
    return all(a[i] <= b[i] for i in range(5))


def _add_vectors5(a: Sequence[Any], b: Sequence[Any]) -> List[int]:
    av = _list5_int(a, default=0)
    bv = _list5_int(b, default=0)
    return [av[i] + bv[i] for i in range(5)]


def _same_positive_resource_on_both_sides(a: Sequence[Any], b: Sequence[Any]) -> bool:
    av = _list5_int(a, default=0)
    bv = _list5_int(b, default=0)
    return any(av[i] > 0 and bv[i] > 0 for i in range(5))


def _wildcard_combo_vectors(
    count: int,
    allowed: Sequence[int],
    hand_remaining: Sequence[Any],
    *,
    prefer_accept_profile: Optional[TradeProfile] = None,
    prefer_offer_profile: Optional[TradeProfile] = None,
    max_vectors: int = 24,
    receives_from_human: bool = False,
) -> List[List[int]]:
    count = max(0, int(count or 0))
    if count <= 0:
        return [[0, 0, 0, 0, 0]]
    allowed_indices = [int(i) for i in allowed if 0 <= int(i) < 5]
    if not allowed_indices:
        return []
    remaining = _list5_int(hand_remaining, default=0)
    out: List[List[int]] = []

    def rec(start_idx: int, left: int, vector: List[int]) -> None:
        if len(out) >= max(1, int(max_vectors or 1)) * 4:
            return
        if left == 0:
            out.append(list(vector))
            return
        # Combinations with repetition: keep stable nondecreasing index order.
        for pos in range(start_idx, len(allowed_indices)):
            res_idx = allowed_indices[pos]
            if vector[res_idx] >= remaining[res_idx]:
                continue
            vector[res_idx] += 1
            rec(pos, left - 1, vector)
            vector[res_idx] -= 1

    rec(0, count, [0, 0, 0, 0, 0])

    def combo_score(vector: Sequence[int]) -> float:
        score = 0.0
        for i, amount in enumerate(_list5_int(vector, default=0)):
            if amount <= 0:
                continue
            if prefer_accept_profile is not None:
                appetite = int(prefer_accept_profile.accept_appetite[i] or 0)
                if appetite > 0:
                    score += amount * (8.0 - min(7.0, float(appetite)))
                elif receives_from_human:
                    score -= amount * 2.5
            if prefer_offer_profile is not None:
                appetite = int(prefer_offer_profile.offer_appetite[i] or 0)
                if appetite > 0:
                    score += amount * float(appetite)
                else:
                    score -= amount * 3.0
            # Prefer resources the owner can spare from actual hand volume.
            score += amount * min(2.0, float(remaining[i]) * 0.15)
        return score

    out.sort(key=lambda vec: (-combo_score(vec), tuple(vec)))
    return out[:max(1, int(max_vectors or 1))]


def _human_twp_counterparty_willingness(
    *,
    counter_profile: Optional[TradeProfile],
    proposer_profile: Optional[TradeProfile],
    proposer_gives: Sequence[Any],
    counterparty_gives: Sequence[Any],
    offer_wildcard_count: int,
    request_wildcard_count: int,
) -> Tuple[bool, str, float]:
    human_vec = _list5_int(proposer_gives, default=0)
    counter_vec = _list5_int(counterparty_gives, default=0)
    if counter_profile is None:
        # Conservative fallback: if the opponent can pay and receives at least as
        # many cards as it gives, consider it willing enough to show as option.
        score = float(sum(human_vec) - sum(counter_vec))
        return bool(sum(human_vec) >= sum(counter_vec)), "fallback quantity willingness", score

    receive_score = 0.0
    give_score = 0.0
    bad_give = []
    wanted_received = False
    for idx in range(5):
        if human_vec[idx] > 0:
            appetite = int(counter_profile.accept_appetite[idx] or 0)
            if appetite > 0:
                wanted_received = True
                receive_score += float(human_vec[idx]) * (8.0 - min(7.0, float(appetite)))
            else:
                receive_score += float(human_vec[idx]) * 0.25
        if counter_vec[idx] > 0:
            offer_appetite = int(counter_profile.offer_appetite[idx] or 0)
            if offer_appetite <= 0:
                bad_give.append(RESOURCE_NAMES[idx])
                give_score -= float(counter_vec[idx]) * 5.0
            else:
                give_score += float(counter_vec[idx]) * float(offer_appetite)

    quantity_bonus = 0.75 * (sum(human_vec) - sum(counter_vec))
    wildcard_bonus = 0.15 * (int(offer_wildcard_count or 0) + int(request_wildcard_count or 0))
    score = receive_score + give_score + quantity_bonus + wildcard_bonus

    if bad_give:
        return False, f"counterparty does not want to offer {', '.join(bad_give)}", score
    if not wanted_received and sum(human_vec) <= sum(counter_vec):
        return False, "counterparty does not want the offered cards enough", score
    if score < 0.25:
        return False, "counterparty score too low", score

    return True, "counterparty can choose wildcard resources and accepts concrete option", score


def _format_vector_amounts(values: Sequence[Any]) -> str:
    vec = _list5_int(values, default=0)
    parts = [f"{vec[i]}{RESOURCE_ABBR[i]}" for i in range(5) if vec[i] > 0]
    return "+".join(parts) if parts else "0"


def _record_human_twp_vector_turn_details(
    game: Any,
    proposer: Any,
    counter: Any,
    *,
    proposer_delta: Sequence[int],
    counter_delta: Sequence[int],
    message: str,
    metadata: Mapping[str, Any],
    source: str,
    reason: str,
) -> None:
    proposer_vec = _list5_int(proposer_delta, default=0) + [0]
    counter_vec = _list5_int(counter_delta, default=0) + [0]
    try:
        setattr(proposer, "turn_details_TwP", proposer_vec)
        setattr(proposer, "turn_details_last_TwPdeal", proposer_vec)
        setattr(counter, "turn_details_TwP", counter_vec)
        setattr(counter, "turn_details_last_TwPdeal", counter_vec)
    except Exception:
        pass

    # S7e Activity counters (human vector TwP path)
    try:
        from core.game_statistics import bump_player_stat

        bump_player_stat(proposer, "stats_twp_accepted", 1)
        bump_player_stat(counter, "stats_twp_accepted", 1)
        bump_player_stat(proposer, "stats_twp_proposed", 1)
    except Exception:
        pass

    myturn = getattr(game, "myturn", None)
    if myturn is not None:
        try:
            myturn.number_of_deals_offered = int(getattr(myturn, "number_of_deals_offered", 0) or 0) + 1
        except Exception:
            pass

    if hasattr(game, "record_turn_delta"):
        try:
            game.record_turn_delta(
                proposer,
                "TwP",
                resource_delta={RESOURCE_NAMES[i]: proposer_vec[i] for i in range(5) if proposer_vec[i]},
                event_type="trade_with_player",
                target_player_id=_player_id(counter),
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
            game.record_turn_delta(
                counter,
                "TwP",
                resource_delta={RESOURCE_NAMES[i]: counter_vec[i] for i in range(5) if counter_vec[i]},
                event_type="trade_with_player",
                target_player_id=_player_id(proposer),
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
            return
        except Exception:
            pass

    ledger = getattr(game, "turn_event_ledger", None)
    if ledger is not None and hasattr(ledger, "add_event"):
        try:
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=_player_id(proposer),
                event_type="TwP accepted",
                category="TwP",
                target_player_id=_player_id(counter),
                resource_delta={RESOURCE_NAMES[i]: proposer_vec[i] for i in range(5) if proposer_vec[i]},
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=_player_id(counter),
                event_type="TwP accepted",
                category="TwP",
                target_player_id=_player_id(proposer),
                resource_delta={RESOURCE_NAMES[i]: counter_vec[i] for i in range(5) if counter_vec[i]},
                public=True,
                source=source,
                reason=reason,
                message=message,
                metadata=dict(metadata),
            )
        except Exception:
            pass

def find_and_execute_best_ai_to_ai_trade(
    game: Any,
    active_player: Optional[Any] = None,
    *,
    max_candidates: int = DEFAULT_MAX_PROPOSALS,
) -> TradeDecision:
    """Find and execute the best AI-vs-AI TwP trade for the active player."""

    proposal = choose_best_twp_proposal(
        game,
        active_player,
        ai_only=True,
        max_candidates=max_candidates,
    )
    if proposal is None:
        return TradeDecision(
            accepted=False,
            executed=False,
            proposal=None,
            reason="No acceptable AI-vs-AI TwP proposal found.",
        )
    return execute_twp_trade(game, proposal, require_human_confirmation=False)


# ──────────────────────────────────────────────────────────────────────────────
# Profile and market construction
# ──────────────────────────────────────────────────────────────────────────────


def build_trade_profile(
    game: Any,
    player: Any,
    *,
    market: Optional[ResourceMarket] = None,
    primary_cost: Optional[Sequence[Any]] = None,
    primary_action: Optional[str] = None,
) -> TradeProfile:
    """Build appetite vectors from hand, production, current strategic direction."""

    board = getattr(game, "board", None)
    market = market or build_resource_market(game, board=board)
    hand = _tuple5_int(_get_hand(player))
    trade_rates = _tuple5_int(_get_trade_rates(board, player), default=4)
    production_pips = _tuple5_float(_get_production_pips(board, player))

    if primary_cost is None or primary_action is None:
        # Prefer Game's supporting-action mapping (road-first on settle routes).
        try:
            direction = getattr(player, "strategic_direction", None) or {}
            if isinstance(direction, Mapping) and game is not None:
                tgt_fn = getattr(game, "_target_action_from_strategic_direction", None)
                cost_fn = getattr(game, "_execution_cost_vector_for_action", None)
                if callable(tgt_fn) and callable(cost_fn):
                    act = str(tgt_fn(direction) or "")
                    if act:
                        primary_action = primary_action or act
                        primary_cost = primary_cost or cost_fn(act)
        except Exception:
            pass
        if primary_cost is None or primary_action is None:
            inferred_action, inferred_cost = _infer_primary_action_and_cost(player)
            primary_action = primary_action or inferred_action
            primary_cost = primary_cost or inferred_cost

    cost = _tuple5_int(primary_cost, default=0)
    missing = _tuple5_int([max(0, cost[i] - hand[i]) for i in range(5)], default=0)
    surplus = _tuple5_int([max(0, hand[i] - cost[i]) for i in range(5)], default=0)

    protected = _build_protected_resource_vector(
        player=player,
        primary_action=str(primary_action or "unknown"),
        primary_cost=cost,
        hand=hand,
        production_pips=production_pips,
        market=market,
    )
    # Strategy tags: raise protection for resources still needed by the pursued way/project.
    try:
        direction = getattr(player, "strategic_direction", None) or {}
        named_need = {}
        if isinstance(direction, Mapping):
            named_need = direction.get("needed_rcards") or direction.get("needed_rcards_after") or {}
        if isinstance(named_need, Mapping):
            prot = list(protected)
            for idx, name in enumerate(RESOURCE_NAMES):
                raw = named_need.get(name, named_need.get(name.lower(), 0))
                try:
                    nval = float(raw or 0)
                except Exception:
                    nval = 0.0
                if nval >= 1.0 and hand[idx] <= max(1, int(nval)):
                    prot[idx] = max(int(prot[idx]), 4)
                elif nval >= 2.0:
                    prot[idx] = max(int(prot[idx]), 3)
            protected = _tuple5_int(prot, default=0)
    except Exception:
        pass
    bottleneck = _build_bottleneck_resource_vector(
        hand=hand,
        production_pips=production_pips,
        protected_resource_vector=protected,
        market=market,
    )

    offer = [0, 0, 0, 0, 0]
    accept = [0, 0, 0, 0, 0]
    offer_number = [1, 1, 1, 1, 1]
    accept_number = [1, 1, 1, 1, 1]
    reasons: Dict[str, List[str]] = {name: [] for name in RESOURCE_NAMES}

    for idx, name in enumerate(RESOURCE_NAMES):
        if hand[idx] > 0:
            if surplus[idx] >= max(1, trade_rates[idx]):
                offer[idx] = 6
                reasons[name].append("surplus reaches bank/port trade rate; only trade if better than TwB")
            elif surplus[idx] >= 1:
                offer[idx] = 2
                reasons[name].append("clear surplus above primary cost")
            elif hand[idx] >= 2 and production_pips[idx] >= DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
                offer[idx] = 4
                reasons[name].append("protected card, but production can probably replace it")
            elif bool(market.scarce[idx]) and hand[idx] >= 1:
                offer[idx] = 4
                reasons[name].append("scarce-card premium may justify offering exactly one")

        if hand[idx] > 0 and protected[idx] >= 4 and surplus[idx] <= 0:
            reasons[name].append("primary-target protected; only give away if an immediate primary action is unlocked")
        elif hand[idx] > 0 and bottleneck[idx] > 0:
            reasons[name].append("bottleneck protected; avoid offering unless it immediately unlocks the primary target")

        if missing[idx] > 0:
            accept[idx] = 1 if production_pips[idx] <= 2.0 else 2
            reasons[name].append("missing for primary action")
        elif bool(market.scarce[idx]) and production_pips[idx] <= 2.0:
            accept[idx] = 3
            reasons[name].append("scarce on board and this player has weak access")

        # Clear surplus: willing to offer even when primary-cost surplus was 0
        # but hand holds 2+ and production can replace (unlock TwP for partners).
        if hand[idx] >= 2 and surplus[idx] >= 1 and offer[idx] == 0:
            offer[idx] = 2
            reasons[name].append("surplus above primary: offer for partner unlock")
        elif hand[idx] >= 3 and production_pips[idx] >= DEFAULT_ABUNDANT_PLAYER_PIPS_MIN and offer[idx] == 0:
            offer[idx] = 2
            reasons[name].append("abundant production + stack: soft offer for partner unlock")

    _add_on_the_fly_acceptance(hand, accept, reasons)

    # T1: keep/ditch from Stage A hand-risk (fallback: cost keep + surplus ditch)
    keep_vec, ditch_vec = _keep_ditch_vectors_for_player(game, player, hand=hand, primary_cost=cost)
    for idx, name in enumerate(RESOURCE_NAMES):
        if ditch_vec[idx] > 0 and hand[idx] > 0:
            # Prefer offering ditch over protected keep (even if primary_cost surplus is 0)
            if offer[idx] == 0:
                offer[idx] = 2
            reasons[name].append(f"T1 ditch={ditch_vec[idx]} keep={keep_vec[idx]}")
        if keep_vec[idx] > 0 and hand[idx] > 0 and ditch_vec[idx] <= 0:
            # Suppress casual offers of pure-keep resources. Unlock trades that
            # must spend keep still pass via strategy-guard + appetite bypass.
            if offer[idx] > 0 and offer[idx] < 6:
                offer[idx] = 0
            reasons[name].append("T1 keep unit: do not offer unless unlocks primary")
        elif keep_vec[idx] > 0 and ditch_vec[idx] > 0:
            # Mixed stack: allow ditch offers only (give_count limited by ditch guard)
            reasons[name].append(
                f"T1 mixed keep={keep_vec[idx]} ditch={ditch_vec[idx]}: offer only ditch units"
            )

    return TradeProfile(
        player_id=_player_id(player),
        player_color=str(getattr(player, "color", "")),
        is_human=bool(getattr(player, "is_human", False)),
        hand=hand,
        trade_rates=trade_rates,
        production_pips=production_pips,
        primary_action=str(primary_action or "unknown"),
        primary_cost=cost,
        primary_missing=missing,
        clear_surplus=surplus,
        protected_resource_vector=_tuple5_int(protected, default=0),
        bottleneck_resource_vector=_tuple5_int(bottleneck, default=0),
        offer_appetite=_tuple5_int(offer, default=0),
        accept_appetite=_tuple5_int(accept, default=0),
        offer_number=_tuple5_int(offer_number, default=1),
        accept_number=_tuple5_int(accept_number, default=1),
        reasons={k: v for k, v in reasons.items() if v},
        keep_resource_vector=_tuple5_int(keep_vec, default=0),
        ditch_resource_vector=_tuple5_int(ditch_vec, default=0),
    )


def build_resource_market(
    game: Any,
    *,
    board: Optional[Any] = None,
    scarce_total_pips_max: float = DEFAULT_SCARCE_TOTAL_PIPS_MAX,
    scarce_players_with_access_max: int = DEFAULT_SCARCE_PLAYERS_WITH_ACCESS_MAX,
    abundant_player_pips_min: float = DEFAULT_ABUNDANT_PLAYER_PIPS_MIN,
    abundant_hand_min: int = DEFAULT_ABUNDANT_HAND_MIN,
) -> ResourceMarket:
    """Classify board-level scarcity and player-level abundance."""

    board = board if board is not None else getattr(game, "board", None)
    board_total = _tuple5_float(_board_resource_pips(board))

    player_pips_by_id: Dict[int, Tuple[float, float, float, float, float]] = {}
    abundant_for_players: Dict[int, Tuple[bool, bool, bool, bool, bool]] = {}
    players = list(getattr(game, "players", []) or [])

    for player in players:
        pid = _player_id(player)
        pips = _tuple5_float(_get_production_pips(board, player))
        hand = _tuple5_int(_get_hand(player))
        player_pips_by_id[pid] = pips
        abundant_for_players[pid] = tuple(
            bool(pips[i] >= abundant_player_pips_min or hand[i] >= abundant_hand_min)
            for i in range(5)
        )  # type: ignore[assignment]

    players_with_access = []
    max_player_pips = []
    scarce = []
    for idx in range(5):
        access_count = sum(1 for pips in player_pips_by_id.values() if pips[idx] > _EPS)
        max_pip = max([pips[idx] for pips in player_pips_by_id.values()] or [0.0])
        players_with_access.append(access_count)
        max_player_pips.append(max_pip)
        scarce.append(
            bool(
                board_total[idx] <= scarce_total_pips_max
                or access_count <= scarce_players_with_access_max
            )
        )

    return ResourceMarket(
        board_total_pips=_tuple5_float(board_total),
        players_with_access=_tuple5_int(players_with_access, default=0),
        max_player_pips=_tuple5_float(max_player_pips),
        scarce=tuple(bool(x) for x in scarce),  # type: ignore[arg-type]
        abundant_for_players=abundant_for_players,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Proposal generation and scoring
# ──────────────────────────────────────────────────────────────────────────────


def _generate_pair_proposals(
    active: TradeProfile,
    counter: TradeProfile,
    market: ResourceMarket,
    *,
    game: Optional[Any] = None,
) -> List[TradeProposal]:
    proposals: List[TradeProposal] = []
    for give_idx in range(5):
        for receive_idx in range(5):
            if give_idx == receive_idx:
                continue
            for give_count, receive_count, trade_type in SUPPORTED_TWP_QUANTITY_PATTERNS:
                proposal = _build_proposal(
                    active=active,
                    counter=counter,
                    give_idx=give_idx,
                    give_count=give_count,
                    receive_idx=receive_idx,
                    receive_count=receive_count,
                    trade_type=trade_type,
                    market=market,
                    game=game,
                )
                if proposal is not None:
                    proposals.append(proposal)
    return proposals


def _build_proposal(
    *,
    active: TradeProfile,
    counter: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
    game: Optional[Any] = None,
) -> Optional[TradeProposal]:
    if not (0 <= give_idx < 5 and 0 <= receive_idx < 5):
        return None
    if give_idx == receive_idx:
        return None
    if active.hand[give_idx] < give_count:
        return None
    if counter.hand[receive_idx] < receive_count:
        return None

    guard_ok, guard_reasons = _quantity_guard_ok(
        active=active,
        counter=counter,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
        trade_type=trade_type,
        market=market,
    )
    if not guard_ok:
        return None

    strategy_ok, strategy_reasons = _active_strategy_guard_ok(
        game=game,
        active=active,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
        trade_type=trade_type,
        market=market,
    )
    if not strategy_ok:
        return None
    guard_reasons.extend(strategy_reasons)

    # T1: keep-funded unlocks zero offer-appetite on purpose; still allow them.
    active_unlock = _strategy_reasons_indicate_primary_unlock(strategy_reasons)
    # T3: counterparty may also spend keep only to unlock their primary
    counter_unlock = _trade_completes_primary_action(
        counter,
        give_idx=receive_idx,
        give_count=receive_count,
        receive_idx=give_idx,
        receive_count=give_count,
    )

    # Active gives ``give_idx`` and receives ``receive_idx``.
    # Counterparty gives ``receive_idx`` and receives ``give_idx``.
    if not active_unlock and not _appetite_ok(
        active.offer_appetite[give_idx], trade_type=trade_type, side="offer"
    ):
        return None
    if active_unlock and int(active.offer_appetite[give_idx] or 0) <= 0:
        guard_reasons.append(
            "T1: unlock exception bypasses zero offer-appetite on keep"
        )
    if not _appetite_ok(active.accept_appetite[receive_idx], trade_type=trade_type, side="accept"):
        return None
    if not counter_unlock and not _appetite_ok(
        counter.offer_appetite[receive_idx], trade_type=trade_type, side="offer"
    ):
        return None
    if counter_unlock and int(counter.offer_appetite[receive_idx] or 0) <= 0:
        guard_reasons.append(
            "T3: counterparty unlock bypasses zero offer-appetite on keep"
        )
    if not _appetite_ok(counter.accept_appetite[give_idx], trade_type=trade_type, side="accept"):
        return None

    # T3: would the counterparty actually accept? (keep/ditch + need + race)
    counter_ok, counter_adj, counter_accept_reasons = evaluate_counterparty_accept(
        game=game,
        active=active,
        counter=counter,
        active_give_idx=give_idx,
        active_give_count=give_count,
        active_receive_idx=receive_idx,
        active_receive_count=receive_count,
        trade_type=trade_type,
        market=market,
    )
    if not counter_ok:
        return None
    guard_reasons.extend(counter_accept_reasons)

    active_score = _score_trade_for_profile(
        profile=active,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
        trade_type=trade_type,
        market=market,
        is_active=True,
    )
    counter_score = _score_trade_for_profile(
        profile=counter,
        give_idx=receive_idx,
        give_count=receive_count,
        receive_idx=give_idx,
        receive_count=give_count,
        trade_type=trade_type,
        market=market,
        is_active=False,
    )
    counter_score = float(counter_score) + float(counter_adj)

    # Completes primary before score floor (T1-B Q4: unlock / no-prod 2:1 bypass)
    active_completes = _trade_completes_primary_action(
        active,
        give_idx=give_idx,
        give_count=give_count,
        receive_idx=receive_idx,
        receive_count=receive_count,
    )
    try:
        pips_on_give = float(active.production_pips[give_idx] or 0.0)
    except Exception:
        pips_on_give = 0.0
    floor_ok, floor_reason = twp_active_score_floor_ok(
        active_score,
        trade_type,
        completes_primary=bool(active_completes),
        active_pips_on_give=pips_on_give,
    )
    if not floor_ok:
        return None
    if floor_reason:
        guard_reasons.append(floor_reason)

    # S4 / P0-R2 / T1-C: pure-surplus / fair_surplus_for_need may yield low
    # counter_score; still allow when accept model flagged soft-accept.
    pure_surplus_ok = any(
        (
            "unlock_fallback_accept" in str(r)
            or "pure_surplus" in str(r)
            or "fair_surplus_for_need" in str(r)
            or "fair_1for1" in str(r)
        )
        for r in counter_accept_reasons
    )
    if (
        counter_score < MIN_COUNTERPARTY_SCORE_BY_TRADE_TYPE[trade_type]
        and not pure_surplus_ok
    ):
        return None
    risk_penalty = _counterparty_victory_risk_penalty(
        game,
        counter.player_id,
        active.player_id,
        market,
        active_completes_primary=active_completes,
        active_gives_idx=give_idx,
        counter_profile=counter,
    )
    total_score = active_score + counter_score - risk_penalty

    active_gain = [0, 0, 0, 0, 0]
    counter_gain = [0, 0, 0, 0, 0]
    active_gain[give_idx] -= int(give_count)
    active_gain[receive_idx] += int(receive_count)
    counter_gain[give_idx] += int(give_count)
    counter_gain[receive_idx] -= int(receive_count)

    requires_human = bool(active.is_human or counter.is_human)
    reasons = tuple(guard_reasons + _proposal_reason_lines(active, counter, give_idx, receive_idx, trade_type))
    if risk_penalty > _EPS:
        reasons = reasons + (f"T3 race penalty {risk_penalty:.2f}",)

    return TradeProposal(
        active_player_id=active.player_id,
        counterparty_id=counter.player_id,
        active_player_is_human=active.is_human,
        counterparty_is_human=counter.is_human,
        trade_type=trade_type,
        active_give_index=int(give_idx),
        active_give_count=int(give_count),
        active_receive_index=int(receive_idx),
        active_receive_count=int(receive_count),
        active_score=round(float(active_score), 4),
        counterparty_score=round(float(counter_score), 4),
        total_score=round(float(total_score), 4),
        active_gain_vector=_tuple5_int(active_gain, default=0),
        counterparty_gain_vector=_tuple5_int(counter_gain, default=0),
        active_offer_appetite=int(active.offer_appetite[give_idx]),
        active_accept_appetite=int(active.accept_appetite[receive_idx]),
        counterparty_offer_appetite=int(counter.offer_appetite[receive_idx]),
        counterparty_accept_appetite=int(counter.accept_appetite[give_idx]),
        requires_human_confirmation=requires_human,
        auto_executable=not requires_human,
        status="candidate",
        reasons=reasons,
        market_snapshot={
            "active_primary_action": active.primary_action,
            "counterparty_primary_action": counter.primary_action,
            "give_resource_scarce": bool(market.scarce[give_idx]),
            "active_give_protected": int(active.protected_resource_vector[give_idx]),
            "active_give_bottleneck": int(active.bottleneck_resource_vector[give_idx]),
            "active_receive_strategy_value": round(_resource_strategy_value(active, receive_idx, market), 3),
            "active_give_strategy_value": round(_resource_strategy_value(active, give_idx, market), 3),
            "receive_abundant_for_counterparty": bool(
                market.abundant_for_players.get(counter.player_id, (False,) * 5)[receive_idx]
            ),
            "t3_counterparty_accept_adj": round(float(counter_adj), 3),
            "t3_race_penalty": round(float(risk_penalty), 3),
            "t3_active_completes": bool(active_completes),
        },

    )


def _active_strategy_guard_ok(
    *,
    game: Optional[Any],
    active: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
) -> Tuple[bool, List[str]]:
    """Return whether the active player should strategically offer this deal.

    This guard is intentionally stricter than card/appetite availability.  It
    prevents TwP chains where the AI trades away a bottleneck or a card it just
    acquired, unless the follow-up trade immediately unlocks the current primary
    target, especially an upgrade_city target.
    """

    reasons: List[str] = []
    before = list(active.hand)
    after = list(active.hand)
    after[give_idx] -= int(give_count)
    after[receive_idx] += int(receive_count)
    if after[give_idx] < 0:
        return False, []

    before_missing = _weighted_missing_score(before, active.primary_cost, active.production_pips)
    after_missing = _weighted_missing_score(after, active.primary_cost, active.production_pips)
    completes_primary = bool(before_missing > _EPS and after_missing <= _EPS)
    primary_is_city = "city" in str(active.primary_action or "").lower()

    # T1: never offer keep units unless trade immediately completes primary (unlock)
    keep = list(getattr(active, "keep_resource_vector", None) or (0, 0, 0, 0, 0))
    ditch = list(getattr(active, "ditch_resource_vector", None) or (0, 0, 0, 0, 0))
    while len(keep) < 5:
        keep.append(0)
    while len(ditch) < 5:
        ditch.append(0)
    spends_keep = int(give_count) > int(ditch[give_idx] or 0)
    if spends_keep and not completes_primary:
        return (
            False,
            [
                f"blocked T1: gives keep {RESOURCE_NAMES[give_idx]} "
                f"(give {give_count} > ditch {ditch[give_idx]}) without unlocking {active.primary_action}"
            ],
        )
    if spends_keep and completes_primary:
        reasons.append(
            f"T1 exception: gives keep {RESOURCE_NAMES[give_idx]} because trade unlocks {active.primary_action}"
        )
    elif int(give_count) <= int(ditch[give_idx] or 0):
        reasons.append(f"T1: gives ditch {RESOURCE_NAMES[give_idx]} x{give_count}")

    received_this_turn = _received_resource_counts_this_turn(game, active.player_id) if game is not None else [0, 0, 0, 0, 0]
    if received_this_turn[give_idx] > 0 and not completes_primary:
        return (
            False,
            [
                f"blocked: {RESOURCE_NAMES[give_idx]} was received by TwP earlier this turn; "
                "do not trade it away again unless it immediately completes the primary target"
            ],
        )
    if received_this_turn[give_idx] > 0 and completes_primary:
        reasons.append(
            f"exception: gives {RESOURCE_NAMES[give_idx]} received earlier this turn because it immediately completes {active.primary_action}"
        )

    # Bottleneck rule: for example Brick with weak/no Brick access is protected
    # even when city is the primary target.  It may be spent only to complete the
    # primary target immediately.
    if int(active.bottleneck_resource_vector[give_idx] or 0) > 0 and not completes_primary:
        return (
            False,
            [
                f"blocked: gives bottleneck {RESOURCE_NAMES[give_idx]} without immediately completing {active.primary_action}"
            ],
        )
    if int(active.bottleneck_resource_vector[give_idx] or 0) > 0 and completes_primary:
        reasons.append(
            f"exception: gives bottleneck {RESOURCE_NAMES[give_idx]} because trade immediately completes {active.primary_action}"
        )

    # Primary protected resources such as Wheat/Ore for a city target should not
    # be offered away unless the trade completes an even more immediate target.
    if int(active.protected_resource_vector[give_idx] or 0) >= 4 and not completes_primary:
        return (
            False,
            [
                f"blocked: gives primary protected {RESOURCE_NAMES[give_idx]} for {active.primary_action}"
            ],
        )

    receive_value = _resource_strategy_value(active, receive_idx, market) * float(receive_count)
    give_value = _resource_strategy_value(active, give_idx, market) * float(give_count)
    value_delta = receive_value - give_value

    if completes_primary:
        if primary_is_city:
            reasons.append("strategy fit: trade immediately unlocks city upgrade; allow strong exception")
        else:
            reasons.append(f"strategy fit: trade immediately completes {active.primary_action}")
        return True, reasons

    # The received resource must help the active strategy more than the given
    # resource hurts it.  This blocks examples like Brick -> Wood when Brick is
    # the expansion bottleneck and Wood access is already sufficient.
    if value_delta <= 0.10:
        return (
            False,
            [
                f"blocked: strategy value does not improve enough "
                f"({RESOURCE_NAMES[receive_idx]} value {receive_value:.2f} <= "
                f"{RESOURCE_NAMES[give_idx]} value {give_value:.2f})"
            ],
        )

    prior_active_trades = _accepted_twp_count_for_active_player_this_turn(game, active.player_id) if game is not None else 0
    if prior_active_trades >= 1 and value_delta < 1.25:
        return (
            False,
            [
                "blocked: second TwP in same turn requires a strong same-target improvement "
                f"or an immediate primary action; value_delta={value_delta:.2f}"
            ],
        )

    reasons.append(
        f"strategy fit: receives {RESOURCE_NAMES[receive_idx]} improves active target more than giving {RESOURCE_NAMES[give_idx]}"
    )
    return True, reasons


def _quantity_guard_ok(
    *,
    active: TradeProfile,
    counter: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if trade_type == TRADE_NORMAL_1_FOR_1:
        reasons.append("normal 1:1 TwP")
        return True, reasons

    if trade_type == TRADE_TEMPTING_2_FOR_1:
        bank_rate = max(1, int(active.trade_rates[give_idx]))
        if bank_rate <= 2:
            return False, []
        if active.clear_surplus[give_idx] < 1 and active.hand[give_idx] < max(2, bank_rate - 1):
            return False, []
        reasons.append(
            f"tempting 2:1 TwP beats or approaches TwB for {RESOURCE_NAMES[give_idx]} "
            f"(bank rate {bank_rate}:1)"
        )
        return True, reasons

    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2:
        if give_count != 1 or receive_count != 2:
            return False, []
        if not bool(market.scarce[give_idx]):
            return False, []
        abundant_flags = market.abundant_for_players.get(counter.player_id, (False,) * 5)
        if not bool(abundant_flags[receive_idx]):
            return False, []
        if counter.hand[receive_idx] < 2:
            return False, []
        reasons.append(
            f"scarcity premium: {RESOURCE_NAMES[give_idx]} is scarce on the playboard; "
            f"P{counter.player_id} has abundance of {RESOURCE_NAMES[receive_idx]}"
        )
        return True, reasons

    return False, []


def _score_trade_for_profile(
    *,
    profile: TradeProfile,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
    trade_type: str,
    market: ResourceMarket,
    is_active: bool,
) -> float:
    before = list(profile.hand)
    after = list(profile.hand)
    after[give_idx] -= int(give_count)
    after[receive_idx] += int(receive_count)
    if after[give_idx] < 0:
        return -9999.0

    before_missing_score = _weighted_missing_score(before, profile.primary_cost, profile.production_pips)
    after_missing_score = _weighted_missing_score(after, profile.primary_cost, profile.production_pips)
    score = before_missing_score - after_missing_score

    # Make immediately completing the current primary cost attractive.
    if before_missing_score > _EPS and after_missing_score <= _EPS:
        score += 1.25

    # Appetite contributes, but does not replace timing/need logic.
    offer_appetite = int(profile.offer_appetite[give_idx] or 99)
    accept_appetite = int(profile.accept_appetite[receive_idx] or 99)
    score += max(0.0, (5.0 - min(offer_appetite, 5)) * 0.05)
    score += max(0.0, (5.0 - min(accept_appetite, 5)) * 0.08)

    completes_primary = before_missing_score > _EPS and after_missing_score <= _EPS

    # Strategy-fit nudges: receiving a high-value/primary resource should beat
    # giving away a low-value/secondary resource.  Giving away bottlenecks is
    # only tolerated when the trade immediately completes the primary target.
    value_delta = _resource_strategy_value(profile, receive_idx, market) * float(receive_count) - _resource_strategy_value(profile, give_idx, market) * float(give_count)
    score += 0.18 * value_delta

    # Guard against breaking a protected card in the main build target.
    if profile.primary_cost[give_idx] > 0 and before[give_idx] >= profile.primary_cost[give_idx] and after[give_idx] < profile.primary_cost[give_idx]:
        if completes_primary:
            score += 0.20
        elif profile.production_pips[give_idx] < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
            score -= 1.50
        else:
            score -= 0.55

    if profile.bottleneck_resource_vector[give_idx] > 0 and not completes_primary:
        score -= 1.25
    if profile.protected_resource_vector[give_idx] >= 4 and not completes_primary:
        score -= 0.90

    # T1 keep/ditch scoring (align TwP with hand-risk Stage A)
    keep = list(getattr(profile, "keep_resource_vector", None) or (0, 0, 0, 0, 0))
    ditch = list(getattr(profile, "ditch_resource_vector", None) or (0, 0, 0, 0, 0))
    while len(keep) < 5:
        keep.append(0)
    while len(ditch) < 5:
        ditch.append(0)
    if is_active:
        if int(give_count) <= int(ditch[give_idx] or 0):
            score += 0.40  # prefer offering ditch
        elif int(give_count) > int(ditch[give_idx] or 0) and not completes_primary:
            score -= 1.10  # penalize keep offers (usually blocked)
        if int(profile.primary_missing[receive_idx] or 0) > 0:
            score += 0.45  # receive fills primary shortfall
        # Prefer cheap unlock TwP over bank 4:1
        if completes_primary and int(give_count) == 1 and int(receive_count) == 1:
            bank_rate = max(1, int(profile.trade_rates[give_idx] or 4))
            # Receiving missing card via 1:1 is much better than bank_rate:1 on any surplus
            score += 0.55 + 0.20 * float(max(0, bank_rate - 1))
    else:
        # T3: counterparty perspective — same keep/ditch psychology
        if int(give_count) <= int(ditch[give_idx] or 0):
            score += 0.35  # happy to give ditch
        elif int(give_count) > int(ditch[give_idx] or 0) and not completes_primary:
            score -= 1.25  # will not casually give keep
        if int(profile.primary_missing[receive_idx] or 0) > 0:
            score += 0.55  # receiving fills their shortfall
        if completes_primary:
            score += 0.45  # they unlock their primary
        # Surplus-to-need is the classic "yes I'll take that"
        if int(profile.clear_surplus[give_idx] or 0) >= int(give_count) and int(
            profile.primary_missing[receive_idx] or 0
        ) > 0:
            score += 0.30

    # Scarcity/abundance nudges.
    if market.scarce[receive_idx]:
        score += 0.25
    if market.scarce[give_idx] and trade_type != TRADE_SCARCITY_PREMIUM_1_FOR_2:
        score -= 0.30
    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2 and is_active:
        # Active player is intentionally charging a premium for the scarce card.
        score += 0.35

    # Prefer player trade over bank when giving 2 for 1 and bank is 3:1/4:1.
    if trade_type == TRADE_TEMPTING_2_FOR_1 and is_active:
        bank_rate = max(1, int(profile.trade_rates[give_idx]))
        if int(give_count) < bank_rate:
            score += 0.30 * float(bank_rate - int(give_count))

    # Discard risk: reducing hand size above 7 is mildly useful; increasing it is risky.
    before_total = sum(before)
    after_total = sum(after)
    if before_total > 7 and after_total < before_total:
        score += 0.10 * float(before_total - after_total)
    if after_total > 7 and after_total > before_total:
        score -= 0.10 * float(after_total - before_total)

    return float(score)


def _strategy_reasons_indicate_primary_unlock(reasons: Sequence[str]) -> bool:
    """True when strategy-guard reasons mark an immediate primary unlock."""
    for raw in reasons or ():
        text = str(raw or "").lower()
        if not text:
            continue
        if "t1 exception" in text:
            return True
        if "immediately completes" in text or "immediately unlocks" in text:
            return True
        if "trade immediately unlocks" in text or "trade immediately completes" in text:
            return True
        if "unlocks" in text and "primary" in text:
            return True
    return False


def _keep_ditch_vectors_for_player(
    game: Any,
    player: Any,
    *,
    hand: Sequence[int],
    primary_cost: Sequence[int],
) -> Tuple[List[int], List[int]]:
    """T1: resolve keep/ditch from Stage A profile, with cost-based fallback."""
    try:
        from core.ai_hand_risk import build_hand_risk_profile

        risk = build_hand_risk_profile(game, player)
        keep = [max(0, int(x or 0)) for x in list(risk.get("keep") or [])[:5]]
        ditch = [max(0, int(x or 0)) for x in list(risk.get("ditch") or [])[:5]]
        while len(keep) < 5:
            keep.append(0)
        while len(ditch) < 5:
            ditch.append(0)
        # Sanity: keep+ditch should not exceed hand; repair if empty
        if sum(keep) + sum(ditch) > 0:
            return keep, ditch
    except Exception:
        pass
    hand_l = [max(0, int(x or 0)) for x in list(hand)[:5]]
    cost_l = [max(0, int(x or 0)) for x in list(primary_cost)[:5]]
    while len(hand_l) < 5:
        hand_l.append(0)
    while len(cost_l) < 5:
        cost_l.append(0)
    keep = [min(hand_l[i], cost_l[i]) for i in range(5)]
    ditch = [max(0, hand_l[i] - keep[i]) for i in range(5)]
    return keep, ditch


# ──────────────────────────────────────────────────────────────────────────────
# Helpers: cost inference, vectors, resources, logging
# ──────────────────────────────────────────────────────────────────────────────



def _strategic_text(player: Any) -> str:
    """Return a lowercase text blob describing the player's current strategy."""

    parts: List[str] = []
    for attr in ("strategic_direction", "last_strategic_direction", "primary_strategy"):
        value = getattr(player, attr, None)
        if isinstance(value, Mapping):
            for key in (
                "target",
                "target_action",
                "supporting_action_type",
                "action_type",
                "preferred_action_type",
                "need_compact",
                "strategy_name",
                "label",
                "name",
            ):
                item = value.get(key)
                if item not in (None, ""):
                    parts.append(str(item).lower())
            tags = value.get("tags", [])
            if isinstance(tags, Iterable) and not isinstance(tags, (str, bytes)):
                parts.extend(str(t).lower() for t in tags)
        elif value not in (None, ""):
            parts.append(str(value).lower())
    return " ".join(parts)


def _build_protected_resource_vector(
    *,
    player: Any,
    primary_action: str,
    primary_cost: Sequence[int],
    hand: Sequence[int],
    production_pips: Sequence[float],
    market: ResourceMarket,
) -> Tuple[int, int, int, int, int]:
    """Build a 0..5 resource-protection vector for the active strategy.

    Scale:
        0 = not protected
        1 = light protection
        2 = protected
        3 = strong secondary/bottleneck protection
        4 = primary-target protected
        5 = immediate missing primary resource, especially with weak access
    """

    text = _strategic_text(player)
    action = str(primary_action or "").lower()
    protected = [0, 0, 0, 0, 0]

    for idx in range(5):
        if int(primary_cost[idx] or 0) > 0:
            protected[idx] = max(protected[idx], 4)
            if int(hand[idx] or 0) < int(primary_cost[idx] or 0):
                protected[idx] = max(protected[idx], 5 if float(production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN else 4)

    primary_is_city = "city" in action or "city" in text or "upgrade_city" in text or "upgrade city" in text
    if primary_is_city:
        # Wheat/Ore are the true primary target resources for city.  This makes
        # them more protected than Wood/Brick when upgrade_city@... is active.
        protected[0] = max(protected[0], 4)
        protected[1] = max(protected[1], 4)
        if int(hand[0] or 0) < COST_CITY[0]:
            protected[0] = max(protected[0], 5 if float(production_pips[0]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN else 4)
        if int(hand[1] or 0) < COST_CITY[1]:
            protected[1] = max(protected[1], 5 if float(production_pips[1]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN else 4)

    expansion_words = (
        "settlement",
        "new_settlement",
        "new settlement",
        "road",
        "longest road",
        "longest_road",
    )
    has_expansion_plan = any(word in text for word in expansion_words)
    if has_expansion_plan:
        # Even with city as primary target, Wood/Brick may be needed for the
        # next-settlement/road part of the strategy when the strategic text
        # actually mentions roads/settlements.  A pure city target should not
        # over-protect Wood/Brick.
        for idx in (2, 3):
            secondary = 2
            if bool(market.scarce[idx]) or float(production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
                secondary = 3
            if float(production_pips[idx]) <= _EPS and int(hand[idx] or 0) > 0:
                secondary = 4 if idx == 3 else 3
            protected[idx] = max(protected[idx], secondary)

    # Sheep is only strategically protected when DCard or settlement is a real
    # target.  It stays low for city-only targets so Sheep -> Brick remains valid
    # when Brick supports roads/new settlements.
    if "dcard" in text or "development" in text or "army" in text or "knight" in text:
        protected[4] = max(protected[4], 3)
    if "settlement" in text:
        protected[4] = max(protected[4], 2)

    return _tuple5_int(protected, default=0)


def _build_bottleneck_resource_vector(
    *,
    hand: Sequence[int],
    production_pips: Sequence[float],
    protected_resource_vector: Sequence[int],
    market: ResourceMarket,
) -> Tuple[int, int, int, int, int]:
    """Mark protected resources that are hard for this player to replace."""

    bottleneck = [0, 0, 0, 0, 0]
    for idx in range(5):
        if int(protected_resource_vector[idx] or 0) <= 0:
            continue
        weak_access = float(production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN
        no_access = float(production_pips[idx]) <= _EPS
        scarce = bool(market.scarce[idx])
        # Only strongly protected resources become hard bottlenecks.  A lightly
        # protected Sheep card for a possible later settlement should not block
        # a useful Sheep -> Brick road-support trade when there is no DCard
        # ambition.
        if int(protected_resource_vector[idx] or 0) < 3:
            continue
        if no_access and int(hand[idx] or 0) > 0:
            bottleneck[idx] = 2
        elif weak_access and (scarce or int(protected_resource_vector[idx] or 0) >= 3):
            bottleneck[idx] = 1
    return _tuple5_int(bottleneck, default=0)


def _resource_strategy_value(profile: TradeProfile, resource_idx: int, market: ResourceMarket) -> float:
    """Return how valuable one card of this resource is to the profile."""

    idx = int(resource_idx)
    value = 0.0
    value += 0.75 * float(profile.protected_resource_vector[idx])
    value += 1.05 * float(max(0, profile.primary_missing[idx]))
    if int(profile.bottleneck_resource_vector[idx] or 0) > 0:
        value += 1.40 * float(profile.bottleneck_resource_vector[idx])
    if bool(market.scarce[idx]):
        value += 0.35
    if float(profile.production_pips[idx]) < DEFAULT_ABUNDANT_PLAYER_PIPS_MIN:
        value += 0.45
    if float(profile.production_pips[idx]) <= _EPS:
        value += 0.45
    return float(value)


def _trade_completes_primary_action(
    profile: TradeProfile,
    *,
    give_idx: int,
    give_count: int,
    receive_idx: int,
    receive_count: int,
) -> bool:
    before = list(profile.hand)
    after = list(profile.hand)
    after[give_idx] -= int(give_count)
    after[receive_idx] += int(receive_count)
    if after[give_idx] < 0:
        return False
    return bool(
        _weighted_missing_score(before, profile.primary_cost, profile.production_pips) > _EPS
        and _weighted_missing_score(after, profile.primary_cost, profile.production_pips) <= _EPS
    )


def _received_resource_counts_this_turn(game: Optional[Any], player_id: int) -> List[int]:
    counts = [0, 0, 0, 0, 0]
    if game is None:
        return counts
    for record in _twp_memory_records(game):
        try:
            active_id = int(record.get("active_player_id"))
            counter_id = int(record.get("counterparty_id"))
            give_idx = int(record.get("active_give_index"))
            give_count = int(record.get("active_give_count"))
            receive_idx = int(record.get("active_receive_index"))
            receive_count = int(record.get("active_receive_count"))
        except Exception:
            continue
        if int(player_id) == active_id and 0 <= receive_idx < 5:
            counts[receive_idx] += max(0, receive_count)
        elif int(player_id) == counter_id and 0 <= give_idx < 5:
            counts[give_idx] += max(0, give_count)
    return counts


def _accepted_twp_count_for_active_player_this_turn(game: Optional[Any], player_id: int) -> int:
    if game is None:
        return 0
    count = 0
    for record in _twp_memory_records(game):
        try:
            if int(record.get("active_player_id")) == int(player_id):
                count += 1
        except Exception:
            pass
    return count


def _compact_vector(values: Sequence[Any]) -> str:
    parts = []
    for idx, value in enumerate(list(values)[:5]):
        try:
            number = int(value or 0)
        except Exception:
            number = 0
        if number:
            parts.append(f"{RESOURCE_ABBR[idx]}{number}")
    return " ".join(parts) if parts else "-"


def _infer_primary_action_and_cost(player: Any) -> Tuple[str, Tuple[int, int, int, int, int]]:
    """Infer primary action/cost from strategic_direction (4G) when available.

    Immediate step only: if the preferred project still has roads to build,
    primary cost is a **road** (Wood+Brick), not the full settle+all-roads stack.
    That keeps TwP appetite / unlock scoring aligned with execution TwB.
    """
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        direction = {}

    # Prefer explicit supporting_action_type from board strategy.
    support = str(direction.get("supporting_action_type", "") or "").lower()
    if support in ("city", "city_upgrade", "upgrade_city"):
        return "city", COST_CITY
    if support in ("next_settlement", "build_settlement", "settlement"):
        # S4: settle package (Wh+Wd+B+Sh) for unlock TwP / TwB need-fill
        return "settlement", COST_SETTLEMENT
    if support in ("new_settlement",):
        roads = (
            direction.get("roads_to_build")
            or direction.get("supporting_action_roads_to_build")
            or direction.get("locked_roads_to_build")
            or []
        )
        try:
            n_roads = len(list(roads)) if roads else 0
        except Exception:
            n_roads = 0
        # Distance hint when path list missing but still expanding
        if n_roads <= 0:
            try:
                n_roads = int(
                    direction.get("distance_roads")
                    or (direction.get("project_target") or {}).get("distance_roads")
                    or 0
                )
            except Exception:
                n_roads = 0
        if n_roads > 0:
            return "road", COST_ROAD
        # Roads done → full settlement package (incl. Sheep/Wheat), not road-only
        return "settlement", COST_SETTLEMENT
    if support in ("road", "build_road"):
        return "road", COST_ROAD
    if support in ("buy_dcard", "dcard", "dev_card", "development_card"):
        return "development_card", COST_DCARD

    # Named need vector from 4G / strategy tags
    named = direction.get("needed_rcards") or direction.get("needed_rcards_after")
    if isinstance(named, Mapping) and any(float(named.get(n, 0) or 0) > 0 for n in RESOURCE_NAMES):
        cost = []
        for name in RESOURCE_NAMES:
            val = named.get(name, named.get(name.lower(), 0))
            try:
                cost.append(max(0, int(round(float(val or 0)))))
            except Exception:
                cost.append(0)
        action = support or str(direction.get("recommendation", "") or "strategy_need")
        return str(action)[:40] or "strategy_need", _tuple5_int(cost)

    text = _strategic_text(player)
    if "city" in text or "upgrade_city" in text or "upgrade city" in text:
        return "city", COST_CITY
    if "settlement" in text:
        return "settlement", COST_SETTLEMENT
    if "road" in text:
        return "road", COST_ROAD
    if "dcard" in text or "development" in text or "army" in text or "knight" in text:
        return "development_card", COST_DCARD

    settlements = list(getattr(player, "settlements", []) or [])
    cities = set(getattr(player, "cities", []) or [])
    if any(s not in cities for s in settlements):
        return "city", COST_CITY
    return "settlement", COST_SETTLEMENT


def _add_on_the_fly_acceptance(hand: Sequence[int], accept: List[int], reasons: Dict[str, List[str]]) -> None:
    # Build Road on the fly: one of Wood/Brick is missing, the other is present.
    if hand[2] > 0 and hand[3] == 0 and (accept[3] == 0 or accept[3] > 3):
        accept[3] = 3
        reasons["Brick"].append("build road on the fly")
    if hand[2] == 0 and hand[3] > 0 and (accept[2] == 0 or accept[2] > 3):
        accept[2] = 3
        reasons["Wood"].append("build road on the fly")

    # Build DCard on the fly: two of the three cards are already available.
    dcard = COST_DCARD
    for idx in (0, 1, 4):
        have_other = sum(1 for j in (0, 1, 4) if j != idx and hand[j] >= dcard[j])
        if hand[idx] < dcard[idx] and have_other >= 2 and (accept[idx] == 0 or accept[idx] > 3):
            accept[idx] = 3
            reasons[RESOURCE_NAMES[idx]].append("build development card on the fly")


def _weighted_missing_score(
    hand: Sequence[int],
    cost: Sequence[int],
    production_pips: Sequence[float],
) -> float:
    score = 0.0
    for idx in range(5):
        missing = max(0.0, float(cost[idx]) - float(hand[idx]))
        if missing <= _EPS:
            continue
        # Missing a low-production resource is more painful.
        production_weight = 1.0 + max(0.0, 4.0 - float(production_pips[idx])) * 0.12
        score += missing * production_weight
    return score


def _appetite_ok(value: int, *, trade_type: str, side: str) -> bool:
    if int(value or 0) <= 0:
        return False
    if trade_type == TRADE_NORMAL_1_FOR_1:
        return int(value) <= 4
    if trade_type == TRADE_TEMPTING_2_FOR_1:
        return int(value) <= 6 if side == "offer" else int(value) <= 4
    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2:
        # Counterparty may give two abundant cards even when their offer appetite
        # is 6 (bank-trade surplus), because receiving one scarce card can be
        # better than holding bankable surplus.
        return int(value) <= 6 if side == "offer" else int(value) <= 5
    return False


def _proposal_reason_lines(
    active: TradeProfile,
    counter: TradeProfile,
    give_idx: int,
    receive_idx: int,
    trade_type: str,
) -> List[str]:
    lines = [
        f"active primary action: {active.primary_action}",
        f"counterparty primary action: {counter.primary_action}",
        f"active wants {RESOURCE_NAMES[receive_idx]} appetite={active.accept_appetite[receive_idx]}",
        f"counterparty wants {RESOURCE_NAMES[give_idx]} appetite={counter.accept_appetite[give_idx]}",
        f"active protected vector: {_compact_vector(active.protected_resource_vector)}",
        f"active bottleneck vector: {_compact_vector(active.bottleneck_resource_vector)}",
    ]
    if trade_type == TRADE_SCARCITY_PREMIUM_1_FOR_2:
        lines.append("guarded reverse 2:1 allowed because offered card is scarce")
    return lines


def evaluate_counterparty_accept(
    *,
    game: Optional[Any],
    active: TradeProfile,
    counter: TradeProfile,
    active_give_idx: int,
    active_give_count: int,
    active_receive_idx: int,
    active_receive_count: int,
    trade_type: str,
    market: ResourceMarket,
) -> Tuple[bool, float, List[str]]:
    """T3: lightweight model of whether the counterparty would accept.

    From the counterparty's view:
      - they give ``active_receive_*`` (what active wants)
      - they receive ``active_give_*`` (what active offers)

    Hard rejects:
      - giving keep without unlocking their own primary
      - pure gift that only helps a racing leader (handled mainly via penalty)
    Soft score_adj nudges total_score toward plausible human accept/reject.
    """
    _ = (trade_type, market, active)
    reasons: List[str] = []
    adj = 0.0

    # Counter gives receive resource, gets give resource
    c_give_idx = int(active_receive_idx)
    c_give_count = int(active_receive_count)
    c_recv_idx = int(active_give_idx)
    c_recv_count = int(active_give_count)

    if not (0 <= c_give_idx < 5 and 0 <= c_recv_idx < 5):
        return False, 0.0, ["T3 reject: invalid resource indices"]
    if counter.hand[c_give_idx] < c_give_count:
        return False, 0.0, ["T3 reject: counterparty lacks cards"]

    keep = list(getattr(counter, "keep_resource_vector", None) or (0, 0, 0, 0, 0))
    ditch = list(getattr(counter, "ditch_resource_vector", None) or (0, 0, 0, 0, 0))
    clear_surplus = list(getattr(counter, "clear_surplus", None) or (0, 0, 0, 0, 0))
    while len(keep) < 5:
        keep.append(0)
    while len(ditch) < 5:
        ditch.append(0)
    while len(clear_surplus) < 5:
        clear_surplus.append(0)

    counter_completes = _trade_completes_primary_action(
        counter,
        give_idx=c_give_idx,
        give_count=c_give_count,
        receive_idx=c_recv_idx,
        receive_count=c_recv_count,
    )
    # T1-C: exportable = ditch Stage-A vector OR clear_surplus (not only ditch)
    exportable = max(
        int(ditch[c_give_idx] or 0),
        int(clear_surplus[c_give_idx] or 0),
    )
    if exportable <= 0:
        try:
            hand_n = int(counter.hand[c_give_idx] or 0)
            keep_n = int(keep[c_give_idx] or 0)
            exportable = max(0, hand_n - keep_n)
        except Exception:
            exportable = 0
    spends_keep = c_give_count > int(exportable or 0)

    if spends_keep and not counter_completes:
        return (
            False,
            0.0,
            [
                f"T3 reject: counterparty keeps {RESOURCE_NAMES[c_give_idx]} "
                f"(give {c_give_count} > exportable {exportable}); no primary unlock"
            ],
        )

    pure_surplus = not spends_keep and c_give_count <= int(exportable or 0)

    if spends_keep and counter_completes:
        reasons.append(
            f"T3 accept: counterparty spends keep {RESOURCE_NAMES[c_give_idx]} to unlock {counter.primary_action}"
        )
        adj += 0.35
    elif pure_surplus:
        reasons.append(
            f"T3: counterparty gives surplus {RESOURCE_NAMES[c_give_idx]} x{c_give_count}"
        )
        adj += 0.15

    # Need / surplus fit
    missing = list(counter.primary_missing)
    while len(missing) < 5:
        missing.append(0)
    needs_recv = int(missing[c_recv_idx] or 0) > 0
    if needs_recv:
        reasons.append(f"T3: counterparty needs {RESOURCE_NAMES[c_recv_idx]}")
        adj += 0.40
    elif int(counter.clear_surplus[c_recv_idx] or 0) > 0 and not counter_completes:
        # Receiving more of a surplus resource is weakly unattractive
        adj -= 0.15
        reasons.append(f"T3 soft: counterparty already has surplus {RESOURCE_NAMES[c_recv_idx]}")

    if counter_completes:
        reasons.append(f"T3 accept: unlocks counterparty {counter.primary_action}")
        adj += 0.50

    # Bottleneck only blocks when digging into keep (ditch surplus of a
    # bottleneck resource is still fair game — e.g. city path with spare Wheat).
    if (
        spends_keep
        and int(counter.bottleneck_resource_vector[c_give_idx] or 0) > 0
        and not counter_completes
    ):
        return (
            False,
            0.0,
            [f"T3 reject: counterparty bottleneck keep {RESOURCE_NAMES[c_give_idx]}"],
        )
    if (
        not spends_keep
        and int(counter.bottleneck_resource_vector[c_give_idx] or 0) > 0
        and not counter_completes
    ):
        adj -= 0.05  # mild caution, still allow ditch export
        reasons.append(f"T3 soft: ditch of bottleneck-type {RESOURCE_NAMES[c_give_idx]}")

    # Human counterparties are slightly more picky when not unlocking and not getting need
    if bool(counter.is_human) and not counter_completes and not needs_recv:
        adj -= 0.20
        reasons.append("T3 soft: human counterparty less eager without need/unlock")

    # Near-win gift check (active being fueled)
    near_win_gift = False
    try:
        active_vp = int(getattr(active, "victory_points", 0) or 0)
        if active_vp <= 0:
            active_vp = int(getattr(active, "points", 0) or 0)
        if active_vp >= int(VP_NEAR_WIN):
            near_win_gift = True
    except Exception:
        near_win_gift = False

    # T1-C / S4: soft-accept pure surplus export.
    # - AI: always (unlock_fallback_accept) unless near-win gift edge
    # - Human or AI: fair_surplus_for_need when they receive primary-missing
    #   (R7-class 1Wh→1B style) — always carry an explicit reason code
    if pure_surplus and not near_win_gift:
        fair_need = bool(needs_recv)
        if fair_need:
            reasons.append("T1-C: fair_surplus_for_need")
            reasons.append("unlock_fallback_accept: fair_1for1")
            adj += 0.35
        if not bool(counter.is_human):
            adj += 0.55
            if not fair_need:
                reasons.append("unlock_fallback_accept: pure_surplus")
            if not reasons:
                reasons.append("T3: counterparty accept model ok")
            return True, float(adj), reasons
        if fair_need:
            # HP receiving something they need for a pure-surplus give is fair
            adj += 0.25
            reasons.append("unlock_fallback_accept: fair_1for1_human")
            return True, float(adj), reasons

    # Minimum plausibility: adj path still needs base score elsewhere
    if adj < -0.35 and not counter_completes and not pure_surplus:
        return False, adj, reasons + ["T3 reject: counterparty value too weak"]

    if not reasons:
        reasons.append("T3: counterparty accept model ok")
    return True, float(adj), reasons


def _rate_limit_proposals_per_counterparty(
    proposals: Sequence[TradeProposal],
    *,
    max_per: int = MAX_PROPOSALS_PER_COUNTERPARTY,
    game: Optional[Any] = None,
    active_profile: Optional[TradeProfile] = None,
) -> List[TradeProposal]:
    """Keep at most ``max_per`` best proposals per counterparty (T3 spam control)."""
    if max_per <= 0:
        return list(proposals)

    def _pq_key(p: TradeProposal) -> Tuple[Any, ...]:
        return package_quality_rank_key_from_proposal(
            p, game=game, active_profile=active_profile
        )

    buckets: Dict[int, List[TradeProposal]] = {}
    for p in proposals:
        buckets.setdefault(int(p.counterparty_id), []).append(p)
    limited: List[TradeProposal] = []
    for _cp_id, items in buckets.items():
        items_sorted = sorted(items, key=_pq_key)
        limited.extend(items_sorted[:max_per])
    limited.sort(key=_pq_key)
    return limited


# ──────────────────────────────────────────────────────────────────────────────
# Product T1-A/B: package quality rank + merge + floors + decline escalate
# ──────────────────────────────────────────────────────────────────────────────


def twp_active_score_floor_ok(
    active_score: float,
    trade_type: str,
    *,
    completes_primary: bool = False,
    active_pips_on_give: float = 0.0,
) -> Tuple[bool, str]:
    """T1-B Q4: MIN active score with unlock / zero-production 2:1 bypasses.

    Returns (ok, reason). reason non-empty when a bypass was used (for dig-in).
    Junk 2:1 (no unlock, has own production of offered card) still blocked.
    """
    try:
        score = float(active_score)
    except Exception:
        score = -9999.0
    ttype = str(trade_type or TRADE_NORMAL_1_FOR_1)
    try:
        floor = float(MIN_ACTIVE_SCORE_BY_TRADE_TYPE.get(ttype, 0.20))
    except Exception:
        floor = 0.20
    if score >= floor - _EPS:
        return True, ""
    if ttype != TRADE_TEMPTING_2_FOR_1:
        return False, ""
    # Locked Q4 bypasses for 2:1 only
    if completes_primary:
        return True, "T1-B: 2:1 floor bypass (completes/unlocks primary)"
    try:
        pips = float(active_pips_on_give or 0.0)
    except Exception:
        pips = 0.0
    if pips <= _EPS:
        return True, "T1-B: 2:1 floor bypass (no own production of offered resource)"
    return False, ""


def _proposal_identity_key(proposal: Any) -> Tuple[int, int, int, int, int, int]:
    data = _proposal_mapping(proposal)
    try:
        return (
            int(data.get("active_player_id", 0) or 0),
            int(data.get("counterparty_id", 0) or 0),
            int(data.get("active_give_index", 0) or 0),
            int(data.get("active_give_count", 0) or 0),
            int(data.get("active_receive_index", 0) or 0),
            int(data.get("active_receive_count", 0) or 0),
        )
    except Exception:
        return (0, 0, 0, 0, 0, 0)


def _tag_proposal_snapshot(
    proposal: TradeProposal,
    *,
    source: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
    extra_reasons: Sequence[str] = (),
) -> TradeProposal:
    """Return a new TradeProposal with updated market_snapshot / reasons."""
    from dataclasses import replace

    snap = dict(proposal.market_snapshot or {})
    if source:
        prev = str(snap.get("source") or "")
        src = str(source)
        if not prev or prev == src:
            snap["source"] = src
        else:
            snap["source"] = "both"
    # Unlock full → treat as completes for list-path unlock_rank
    if snap.get("fully_unlocks") and not snap.get("t3_active_completes"):
        snap["t3_active_completes"] = True
    if extra:
        for k, v in dict(extra).items():
            snap[k] = v
    reasons = list(proposal.reasons or ())
    for r in extra_reasons:
        if r and r not in reasons:
            reasons.append(str(r))
    return replace(proposal, market_snapshot=snap, reasons=tuple(reasons))


def merge_mutual_and_unlock_proposals(
    mutual: Sequence[TradeProposal],
    unlock: Sequence[TradeProposal],
    *,
    game: Optional[Any] = None,
    active_profile: Optional[TradeProfile] = None,
) -> List[TradeProposal]:
    """T1-B Q2: union mutual + unlock pools; dedupe by exact package key."""
    del game, active_profile  # reserved for future quality-aware merge
    by_key: Dict[Tuple[int, int, int, int, int, int], TradeProposal] = {}

    for raw in list(mutual or []):
        if raw is None:
            continue
        p = raw if isinstance(raw, TradeProposal) else None
        if p is None:
            continue
        tagged = _tag_proposal_snapshot(p, source="mutual")
        by_key[_proposal_identity_key(tagged)] = tagged

    for raw in list(unlock or []):
        if raw is None or not isinstance(raw, TradeProposal):
            continue
        tagged = _tag_proposal_snapshot(raw, source="unlock")
        k = _proposal_identity_key(tagged)
        if k in by_key:
            prev = by_key[k]
            # Prefer higher total_score body; always preserve mutual T3 dig-in + reasons
            prefer = tagged if float(tagged.total_score) > float(prev.total_score) else prev
            other = prev if prefer is tagged else tagged
            merged_snap = dict(prefer.market_snapshot or {})
            for key, val in dict(other.market_snapshot or {}).items():
                if key not in merged_snap or str(key).startswith("t3_"):
                    # Prefer non-empty t3_* from either side (usually mutual)
                    if str(key).startswith("t3_") and key in merged_snap and merged_snap[key] is not None:
                        continue
                    if str(key).startswith("t3_"):
                        merged_snap[key] = val
                    elif key not in merged_snap:
                        merged_snap[key] = val
            # Force mutual t3_* if prev was mutual-sourced
            prev_src = str((prev.market_snapshot or {}).get("source") or "")
            if prev_src in {"mutual", "both"}:
                for key, val in dict(prev.market_snapshot or {}).items():
                    if str(key).startswith("t3_"):
                        merged_snap[key] = val
            merged_reasons = list(prefer.reasons or ())
            for r in list(other.reasons or ()):
                if r not in merged_reasons:
                    merged_reasons.append(r)
            from dataclasses import replace

            merged_snap["source"] = "both"
            by_key[k] = replace(
                prefer,
                market_snapshot=merged_snap,
                reasons=tuple(merged_reasons),
            )
        else:
            by_key[k] = tagged

    return list(by_key.values())


def parse_declined_proposal_keys(game: Optional[Any]) -> List[Tuple[int, int, int, int, int, int]]:
    """Normalize human_twp_declined_this_turn into 6-int keys."""
    if game is None:
        return []
    raw = getattr(game, "human_twp_declined_this_turn", None)
    try:
        items = list(raw or [])
    except Exception:
        items = []
    out: List[Tuple[int, int, int, int, int, int]] = []
    try:
        from core.human_twp_policy import normalize_proposal_key

        for item in items:
            try:
                key = normalize_proposal_key(item)
                if key and key != (0, 0, 0, 0, 0, 0):
                    out.append(tuple(int(x) for x in key[:6]))  # type: ignore[misc]
            except Exception:
                continue
    except Exception:
        for item in items:
            try:
                seq = list(item)
                if len(seq) >= 6:
                    out.append(tuple(int(seq[i] or 0) for i in range(6)))
            except Exception:
                continue
    return out


def apply_decline_escalation_boosts(
    game: Optional[Any],
    proposals: Sequence[TradeProposal],
) -> List[TradeProposal]:
    """T1-B Q7: after exact 1:1 decline, boost same-pair 2:1/1:2 once per turn.

    Does not re-include exact declined keys. If an escalated count for the pair
    was already declined, the pair is not re-boosted (one escalate family).
    """
    declined = parse_declined_proposal_keys(game)
    if not declined:
        return list(proposals or [])

    declined_set = set(declined)
    pairs_1for1: set = set()
    pairs_escalated_declined: set = set()
    for aid, cid, gi, gn, ri, rn in declined:
        pair = (aid, cid, gi, ri)
        if (gn, rn) == (1, 1):
            pairs_1for1.add(pair)
        if (gn, rn) in ((2, 1), (1, 2)):
            pairs_escalated_declined.add(pair)

    out: List[TradeProposal] = []
    for raw in list(proposals or []):
        if not isinstance(raw, TradeProposal):
            continue
        ident = _proposal_identity_key(raw)
        if ident in declined_set:
            continue  # T8 exact
        aid, cid, gi, gn, ri, rn = ident
        pair = (aid, cid, gi, ri)
        escalate = False
        if (
            pair in pairs_1for1
            and pair not in pairs_escalated_declined
            and (gn, rn) in ((2, 1), (1, 2))
        ):
            escalate = True
        if escalate:
            out.append(
                _tag_proposal_snapshot(
                    raw,
                    extra={
                        "pq_escalate": True,
                        "escalate_after_1for1_decline": True,
                    },
                    extra_reasons=("T1-B: escalate after 1:1 decline",),
                )
            )
        else:
            out.append(raw)
    return out


def _proposal_mapping(proposal: Any) -> Dict[str, Any]:
    if proposal is None:
        return {}
    if isinstance(proposal, Mapping):
        return dict(proposal)
    if hasattr(proposal, "as_dict") and callable(proposal.as_dict):
        try:
            return dict(proposal.as_dict())
        except Exception:
            pass
    out: Dict[str, Any] = {}
    for key in (
        "active_player_id",
        "counterparty_id",
        "trade_type",
        "active_give_index",
        "active_give_count",
        "active_receive_index",
        "active_receive_count",
        "active_score",
        "counterparty_score",
        "total_score",
        "requires_human_confirmation",
        "market_snapshot",
        "reasons",
    ):
        if hasattr(proposal, key):
            out[key] = getattr(proposal, key)
    return out


def counterparty_vp_for_package_rank(game: Optional[Any], counterparty_id: Any) -> int:
    """Lowest-VP partner preference (locked Q1): projected VP when available."""
    if game is None:
        return 0
    try:
        pid = int(counterparty_id)
    except Exception:
        return 0
    player = _player_by_id(game, pid)
    if player is None:
        return 0
    try:
        from core.human_twp_policy import projected_vp_for_twp_freeze

        return int(projected_vp_for_twp_freeze(player))
    except Exception:
        return _player_vp_for_trade(player)


def package_quality_rng_tie_break(
    game: Optional[Any],
    proposal: Any,
) -> int:
    """Stable seeded tie-break (locked Q1): lower is better; not raw player_id."""
    import hashlib

    data = _proposal_mapping(proposal)
    rnd = 0
    trn = 0
    if game is not None:
        try:
            rnd = int(getattr(game, "round", 0) or 0)
        except Exception:
            rnd = 0
        try:
            trn = int(getattr(game, "turn", 0) or 0)
        except Exception:
            trn = 0
    payload = (
        f"{rnd}|{trn}|"
        f"{data.get('active_player_id')}|{data.get('counterparty_id')}|"
        f"{data.get('active_give_index')}|{data.get('active_give_count')}|"
        f"{data.get('active_receive_index')}|{data.get('active_receive_count')}|"
        f"{data.get('trade_type')}|pq_t1a"
    )
    digest = hashlib.md5(payload.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def package_attractiveness(
    *,
    total_score: float,
    trade_type: str,
    unlock_rank: int,
    ditch_rank: int,
    escalate_rank: int = 1,
    bank_rate_give: int = 4,
) -> float:
    """Higher is better for package-quality ranking.

    Unlock still beats vanity. Productive **2:1 bank-beat** bonus applies only
    after a same-pair **1:1 was declined** (``escalate_rank == 0``). First-pass
    offers prefer fair 1:1 when unlock quality matches (see ``net_give_rank``).
    """
    base = float(total_score or 0.0)
    if int(unlock_rank) == 0:
        base += float(PQ_UNLOCK_BONUS)
        # 2:1 is more expensive for the AI — only "make the deal sweeter" after
        # HP already refused 1:1 on the same resource pair (T1 escalate).
        if (
            str(trade_type) == TRADE_TEMPTING_2_FOR_1
            and int(bank_rate_give or 4) >= 3
            and int(escalate_rank) == 0
        ):
            base += float(PQ_BANK_BEAT_2FOR1_BONUS)
    if int(ditch_rank) == 0:
        base += float(PQ_DITCH_BONUS)
    if int(escalate_rank) == 0:
        base += float(PQ_ESCALATE_BONUS)
    return float(base)


def net_give_rank_for_package(
    *,
    give_count: int,
    receive_count: int,
    escalate_rank: int = 1,
) -> int:
    """Lower is better. Prefer 1:1 before 2:1 on first offer; neutral after escalate.

    ``net = give - receive``: 1:1 → 0, tempting 2:1 → 1, scarcity 1:2 → 0 (clamped).
    When ``escalate_rank == 0`` (post-1:1 decline boost), do not demote 2:1.
    """
    try:
        net = int(give_count) - int(receive_count)
    except Exception:
        net = 0
    if int(escalate_rank) == 0:
        return 0
    return max(0, int(net))


def infer_unlock_rank_from_proposal(proposal: Any) -> int:
    """0 = completes primary (snapshot), 2 = unknown/none (list path without hand delta)."""
    data = _proposal_mapping(proposal)
    snap = data.get("market_snapshot") if isinstance(data.get("market_snapshot"), Mapping) else {}
    if snap.get("t3_active_completes") or snap.get("active_completes"):
        return 0
    return 2


def infer_ditch_rank_from_proposal(
    proposal: Any,
    active_profile: Optional[TradeProfile] = None,
    ditch_vec: Optional[Sequence[int]] = None,
) -> int:
    """0 = offer funded from ditch, 1 = spends keep."""
    data = _proposal_mapping(proposal)
    try:
        gi = int(data.get("active_give_index", 0) or 0)
        gc = int(data.get("active_give_count", 0) or 0)
    except Exception:
        return 0
    if not (0 <= gi < 5):
        return 0
    ditch: List[int] = [0, 0, 0, 0, 0]
    if ditch_vec is not None:
        for i, x in enumerate(list(ditch_vec)[:5]):
            ditch[i] = max(0, int(x or 0))
    elif active_profile is not None:
        raw = list(getattr(active_profile, "ditch_resource_vector", None) or ())[:5]
        for i, x in enumerate(raw):
            ditch[i] = max(0, int(x or 0))
    # Unlock path may tag ditch_safe
    snap = data.get("market_snapshot") if isinstance(data.get("market_snapshot"), Mapping) else {}
    if snap.get("ditch_safe") is True and ditch_vec is None and active_profile is None:
        return 0
    if gc > int(ditch[gi] or 0):
        return 1
    return 0


def infer_escalate_rank_from_proposal(proposal: Any) -> int:
    """0 = post-decline escalate boost (T1-B), 1 = normal."""
    data = _proposal_mapping(proposal)
    snap = data.get("market_snapshot") if isinstance(data.get("market_snapshot"), Mapping) else {}
    if snap.get("pq_escalate") or snap.get("escalate_after_1for1_decline"):
        return 0
    for r in list(data.get("reasons") or ()):
        text = str(r or "").lower()
        if "escalate after 1:1" in text or "pq_escalate" in text:
            return 0
    return 1


def bank_rate_for_give(proposal: Any, active_profile: Optional[TradeProfile] = None) -> int:
    data = _proposal_mapping(proposal)
    try:
        gi = int(data.get("active_give_index", 0) or 0)
    except Exception:
        gi = 0
    if active_profile is not None and 0 <= gi < 5:
        try:
            return max(1, int(active_profile.trade_rates[gi] or 4))
        except Exception:
            pass
    return 4


def package_quality_rank_key(
    proposal: Any,
    *,
    game: Optional[Any] = None,
    unlock_rank: Optional[int] = None,
    need_reduced: int = 0,
    ditch_rank: Optional[int] = None,
    escalate_rank: int = 1,
    active_profile: Optional[TradeProfile] = None,
    ditch_vec: Optional[Sequence[int]] = None,
    bank_rate_give: Optional[int] = None,
    attractiveness: Optional[float] = None,
) -> Tuple[Any, ...]:
    """Shared T1-A rank key — **lower is better**.

    Order: unlock → need fill → ditch → escalate → **fair ratio (1:1 before 2:1)**
    → attractiveness → counterparty VP (lowest first) → seeded RNG → indices.

    First offer: prefer 1:1 when unlock/need/ditch match. After HP declines that
    1:1, escalate tags 2:1 (``escalate_rank=0``) so it can surface next.
    """
    data = _proposal_mapping(proposal)
    u_rank = int(unlock_rank) if unlock_rank is not None else infer_unlock_rank_from_proposal(proposal)
    d_rank = (
        int(ditch_rank)
        if ditch_rank is not None
        else infer_ditch_rank_from_proposal(proposal, active_profile, ditch_vec)
    )
    e_rank = int(escalate_rank if escalate_rank is not None else 1)
    try:
        total = float(data.get("total_score", 0.0) or 0.0)
    except Exception:
        total = 0.0
    trade_type = str(data.get("trade_type") or TRADE_NORMAL_1_FOR_1)
    rate = (
        int(bank_rate_give)
        if bank_rate_give is not None
        else bank_rate_for_give(proposal, active_profile)
    )
    try:
        gi = int(data.get("active_give_index", 0) or 0)
        ri = int(data.get("active_receive_index", 0) or 0)
        gc = int(data.get("active_give_count", 0) or 0)
        rc = int(data.get("active_receive_count", 0) or 0)
    except Exception:
        gi = ri = gc = rc = 0
    attr = (
        float(attractiveness)
        if attractiveness is not None
        else package_attractiveness(
            total_score=total,
            trade_type=trade_type,
            unlock_rank=u_rank,
            ditch_rank=d_rank,
            escalate_rank=e_rank,
            bank_rate_give=rate,
        )
    )
    try:
        cid = int(data.get("counterparty_id", 0) or 0)
    except Exception:
        cid = 0
    vp = counterparty_vp_for_package_rank(game, cid)
    rng = package_quality_rng_tie_break(game, proposal)
    fair_rank = net_give_rank_for_package(
        give_count=gc, receive_count=rc, escalate_rank=e_rank
    )
    # Lower tuple wins. Prefer more need_reduced via -need_reduced.
    return (
        int(u_rank),
        -int(need_reduced or 0),
        int(d_rank),
        int(e_rank),
        int(fair_rank),
        -float(attr),
        int(vp),
        int(rng),
        int(gi),
        int(ri),
        -int(rc),
        int(gc),
    )


def package_quality_rank_key_from_proposal(
    proposal: Any,
    *,
    game: Optional[Any] = None,
    active_profile: Optional[TradeProfile] = None,
    ditch_vec: Optional[Sequence[int]] = None,
    escalate_rank: Optional[int] = None,
    live_need: Optional[Sequence[int]] = None,
) -> Tuple[Any, ...]:
    """Convenience for list sort when planner hand-delta unlock is unavailable."""
    e_rank = (
        int(escalate_rank)
        if escalate_rank is not None
        else infer_escalate_rank_from_proposal(proposal)
    )
    # Unlock list may carry need_reduced / fully_unlocks
    need_reduced = 0
    unlock_rank = None
    data = _proposal_mapping(proposal)
    snap = data.get("market_snapshot") if isinstance(data.get("market_snapshot"), Mapping) else {}
    try:
        if snap.get("fully_unlocks") or snap.get("t3_active_completes"):
            unlock_rank = 0
        if snap.get("need_reduced") is not None:
            need_reduced = max(0, int(snap.get("need_reduced") or 0))
            if need_reduced > 0 and unlock_rank is None:
                unlock_rank = 1
        # T11: live_need fill from snapshot or vector
        fills, filled_n = proposal_fills_live_need(proposal, live_need)
        if snap.get("fills_live_need") or fills:
            need_reduced = max(need_reduced, int(filled_n or snap.get("live_need_filled") or 0))
            if need_reduced > 0 and unlock_rank is None:
                unlock_rank = 1
            if unlock_rank == 2 and need_reduced > 0:
                unlock_rank = 1
    except Exception:
        pass
    return package_quality_rank_key(
        proposal,
        game=game,
        unlock_rank=unlock_rank,
        need_reduced=need_reduced,
        ditch_rank=None,
        escalate_rank=e_rank,
        active_profile=active_profile,
        ditch_vec=ditch_vec,
    )


def sort_proposals_by_package_quality(
    proposals: Sequence[Any],
    *,
    game: Optional[Any] = None,
    active_profile: Optional[TradeProfile] = None,
    ditch_vec: Optional[Sequence[int]] = None,
    live_need: Optional[Sequence[int]] = None,
) -> List[Any]:
    """Sort proposals with shared T1-A key (lower better). T11: optional live_need."""
    return sorted(
        list(proposals or []),
        key=lambda p: package_quality_rank_key_from_proposal(
            p,
            game=game,
            active_profile=active_profile,
            ditch_vec=ditch_vec,
            live_need=live_need,
        ),
    )


def build_package_quality_rank_meta(
    ranked: Sequence[Tuple[Tuple[Any, ...], Any]],
    *,
    chosen_index: int = 0,
) -> Dict[str, Any]:
    """Dig-in payload for Phase0 / PLAN (`last_twp_package_rank`)."""
    rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(list(ranked or [])[:8]):
        try:
            rank_key, proposal = item[0], item[1]
        except Exception:
            continue
        data = _proposal_mapping(proposal)
        rows.append(
            {
                "i": idx,
                "rank_key": list(rank_key) if isinstance(rank_key, tuple) else rank_key,
                "counterparty_id": data.get("counterparty_id"),
                "trade_type": data.get("trade_type"),
                "total_score": data.get("total_score"),
                "give": [
                    data.get("active_give_index"),
                    data.get("active_give_count"),
                ],
                "recv": [
                    data.get("active_receive_index"),
                    data.get("active_receive_count"),
                ],
                "unlock_rank": rank_key[0] if isinstance(rank_key, tuple) and rank_key else None,
                "counterparty_vp": rank_key[5] if isinstance(rank_key, tuple) and len(rank_key) > 5 else None,
            }
        )
    chosen = rows[chosen_index] if rows and 0 <= chosen_index < len(rows) else (rows[0] if rows else None)
    meta: Dict[str, Any] = {
        "s55_slice": False,
        "pq": True,
        "slice": "T1-C",
        "chosen": chosen,
        "top3": rows[:3],
        "candidate_count": len(list(ranked or [])),
        "reason_codes": [],
    }
    if chosen and isinstance(chosen.get("rank_key"), list) and chosen["rank_key"]:
        rk = chosen["rank_key"]
        codes: List[str] = []
        if rk[0] == 0:
            codes.append("unlock_full")
        elif rk[0] == 1:
            codes.append("need_partial")
        if len(rk) > 2 and rk[2] == 0:
            codes.append("ditch_offer")
        if len(rk) > 3 and rk[3] == 0:
            codes.append("escalate")
        if len(rk) > 5:
            codes.append(f"partner_vp={rk[5]}")
        meta["reason_codes"] = codes
        meta["dbg"] = format_package_quality_dbg(meta)
    return meta


def format_package_quality_dbg(meta: Optional[Mapping[str, Any]]) -> str:
    """One-line PLAN/DBG string for package quality pick."""
    if not isinstance(meta, Mapping) or not meta:
        return "TwP-PQ: n/a"
    chosen = meta.get("chosen") if isinstance(meta.get("chosen"), Mapping) else None
    if not chosen:
        return "TwP-PQ: none"
    try:
        gi, gc = chosen.get("give") or [None, None]
        ri, rc = chosen.get("recv") or [None, None]
        g_name = RESOURCE_ABBR[int(gi)] if gi is not None and 0 <= int(gi) < 5 else "?"
        r_name = RESOURCE_ABBR[int(ri)] if ri is not None and 0 <= int(ri) < 5 else "?"
        cid = chosen.get("counterparty_id")
        tt = str(chosen.get("trade_type") or "")
        short_tt = "2:1" if "2_for_1" in tt or "tempting" in tt else (
            "1:2" if "1_for_2" in tt or "scarcity" in tt else "1:1"
        )
        unlock = chosen.get("unlock_rank")
        u_tag = " unlock" if unlock == 0 else ""
        text = f"TwP-PQ: {gc}{g_name}→{rc}{r_name} ({short_tt}{u_tag}) vs P{cid}"
        return text if len(text) <= 72 else text[:69] + "..."
    except Exception:
        return "TwP-PQ: pick"


def _player_vp_for_trade(player: Any) -> int:
    if player is None:
        return 0
    try:
        from core.human_twp_policy import projected_vp_for_twp_freeze

        return int(projected_vp_for_twp_freeze(player))
    except Exception:
        pass
    try:
        return max(
            int(getattr(player, "victory_points", 0) or 0),
            int(getattr(player, "points", 0) or 0),
        )
    except Exception:
        return 0


def _counterparty_victory_risk_penalty(
    game: Optional[Any],
    counterparty_id: int,
    active_player_id: int,
    market: ResourceMarket,
    *,
    active_completes_primary: bool = False,
    active_gives_idx: int = -1,
    counter_profile: Optional[TradeProfile] = None,
) -> float:
    """T3: penalize gifting the race leader a needed engine card for free.

    Penalty is subtracted from total_score so active AI avoids "help the leader"
    deals unless the trade also unlocks active's own primary.
    """
    _ = market
    if game is None:
        return 0.0

    active = _player_by_id(game, int(active_player_id))
    counter = _player_by_id(game, int(counterparty_id))
    if active is None or counter is None:
        return 0.0

    active_vp = _player_vp_for_trade(active)
    counter_vp = _player_vp_for_trade(counter)
    if counter_vp <= 0 and active_vp <= 0:
        return 0.0

    # Does this deal hand counter a primary-need card?
    gifts_need = False
    if counter_profile is not None and 0 <= int(active_gives_idx) < 5:
        try:
            gifts_need = int(counter_profile.primary_missing[int(active_gives_idx)] or 0) > 0
        except Exception:
            gifts_need = False
    if not gifts_need:
        # Mild penalty only if they are clear leader and we complete nothing
        if counter_vp >= VP_NEAR_WIN and counter_vp >= active_vp + VP_LEAD_GAP and not active_completes_primary:
            return 0.25
        return 0.0

    penalty = 0.0
    lead = counter_vp - active_vp
    if counter_vp >= VP_NEAR_WIN:
        penalty += 0.90
    elif counter_vp >= VP_LEADER_WARN:
        penalty += 0.45
    if lead >= VP_LEAD_GAP:
        penalty += 0.35 + 0.15 * float(min(4, lead - VP_LEAD_GAP + 1))

    # Helping leader unlock is worse; if we also unlock, cut penalty in half
    if active_completes_primary:
        penalty *= 0.45
    else:
        # Free gift of engine card to leader
        penalty += 0.35

    return float(min(2.5, penalty))


def _classify_quantity_pattern(give_count: int, receive_count: int) -> Optional[str]:
    for g, r, trade_type in SUPPORTED_TWP_QUANTITY_PATTERNS:
        if int(give_count) == g and int(receive_count) == r:
            return trade_type
    return None


def _resolve_player(game: Any, player: Optional[Any]) -> Optional[Any]:
    if player is not None:
        return player
    getter = getattr(game, "get_current_player", None)
    if callable(getter):
        try:
            resolved = getter()
            if resolved is not None:
                return resolved
        except Exception:
            pass
    current = getattr(game, "current_player", None)
    if current is not None:
        return current
    turn = _safe_int_or_none(getattr(game, "turn", None))
    if turn is not None:
        for candidate in list(getattr(game, "players", []) or []):
            if _player_id(candidate) == turn:
                return candidate
    return None


def _player_by_id(game: Any, player_id: int) -> Optional[Any]:
    for player in list(getattr(game, "players", []) or []):
        if _player_id(player) == int(player_id):
            return player
    return None


def _player_id(player: Any) -> int:
    value = _safe_int_or_none(getattr(player, "id", None))
    return int(value or 0)


def _get_hand(player: Any) -> List[int]:
    """Return the player's resource hand in [Wheat, Ore, Wood, Brick, Sheep].

    Prefer the project's resource-time helper in the real game, but do not let a
    harmless all-zero helper result hide explicit mock/player data.  This matters
    for smoke tests and for partially constructed GUI/test players.
    """

    if player is None:
        return [0, 0, 0, 0, 0]

    fallback: Optional[List[int]] = None

    rcards_in_hand = getattr(player, "rcards_in_hand", None)
    if callable(rcards_in_hand):
        try:
            result = rcards_in_hand()
            if isinstance(result, (list, tuple)) and result:
                fallback = _list5_int(result[0], default=0)
        except Exception:
            fallback = None

    if fallback is None:
        rcards = getattr(player, "rcards", {})
        if isinstance(rcards, Mapping):
            out: List[int] = []
            for idx in range(5):
                card = _resource_card(idx)
                # Accept both ResourceCard enum/string keys and plain resource-name keys.
                out.append(int(rcards.get(card, rcards.get(RESOURCE_NAMES[idx], 0)) or 0))
            fallback = _list5_int(out, default=0)

    if callable(get_player_resource_cards_vector):
        try:
            helper_vec = _list5_int(get_player_resource_cards_vector(player), default=0)  # type: ignore[misc]
            # In the real game this is normally the best source.  In lightweight
            # mocks it can return [0,0,0,0,0] because the mock lacks board/game
            # details.  Prefer explicit non-zero player data in that case.
            if any(helper_vec) or fallback is None or not any(fallback):
                return helper_vec
        except Exception:
            pass

    return fallback if fallback is not None else [0, 0, 0, 0, 0]


def _get_trade_rates(board: Any, player: Any) -> List[int]:
    if callable(get_player_trade_rates):
        try:
            return _list5_int(get_player_trade_rates(board, player), default=4)  # type: ignore[misc]
        except Exception:
            pass
    rcards_in_hand = getattr(player, "rcards_in_hand", None)
    if callable(rcards_in_hand):
        try:
            result = rcards_in_hand()
            if isinstance(result, (list, tuple)) and len(result) > 1:
                return _list5_int(result[1], default=4)
        except Exception:
            pass
    return _list5_int(getattr(player, "trade_rates", [4, 4, 4, 4, 4]), default=4)


def _get_production_pips(board: Any, player: Any) -> List[float]:
    """Return production pips in [Wheat, Ore, Wood, Brick, Sheep].

    The project helper is preferred for real game objects.  If it returns all
    zeros while the player exposes explicit production data, use the explicit
    data instead.  This keeps standalone tests meaningful and avoids classifying
    every resource as inaccessible.
    """

    fallback = _list5_float(getattr(player, "resource_production", [0, 0, 0, 0, 0]), default=0.0)

    method = getattr(player, "calculate_resource_production_probability", None)
    if callable(method):
        try:
            result = method(board)
            if isinstance(result, Mapping):
                out: List[float] = []
                for idx in range(5):
                    card = _resource_card(idx)
                    out.append(float(result.get(card, result.get(RESOURCE_NAMES[idx], 0.0)) or 0.0))
                method_vec = _list5_float(out)
                if any(method_vec):
                    fallback = method_vec
        except Exception:
            pass

    if callable(get_player_production_pips):
        try:
            helper_vec = _list5_float(get_player_production_pips(board, player), default=0.0)  # type: ignore[misc]
            if any(helper_vec) or not any(fallback):
                return helper_vec
        except Exception:
            pass

    return fallback


def _board_resource_pips(board: Any) -> List[float]:
    out = [0.0, 0.0, 0.0, 0.0, 0.0]
    if board is None:
        return out
    terrain_to_idx = {
        "field": 0,
        "wheat": 0,
        "grain": 0,
        "mountain": 1,
        "ore": 1,
        "forest": 2,
        "wood": 2,
        "lumber": 2,
        "hill": 3,
        "brick": 3,
        "pasture": 4,
        "sheep": 4,
        "wool": 4,
    }
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        kind = str(getattr(tile, "type", "") or "").strip().lower()
        idx = terrain_to_idx.get(kind)
        if idx is None:
            continue
        try:
            value = int(getattr(tile, "value", 0) or 0)
        except Exception:
            value = 0
        out[idx] += float(pips_from_tile_value(value))
    return out


def _resource_card(index: int) -> Any:
    attr = RESOURCECARD_ATTRS[int(index)]
    return getattr(ResourceCard, attr, RESOURCE_NAMES[int(index)])


def _has_cards(player: Any, resource_index: int, count: int) -> bool:
    hand = _get_hand(player)
    return int(hand[int(resource_index)]) >= int(count)


def _add_resource(player: Any, resource_index: int, amount: int) -> None:
    card = _resource_card(resource_index)
    if not hasattr(player, "rcards") or not isinstance(getattr(player, "rcards"), dict):
        player.rcards = { _resource_card(i): 0 for i in range(5) }
    current = int(player.rcards.get(card, 0) or 0)
    player.rcards[card] = max(0, current + int(amount))


def _sync_number_of_rcards(player: Any) -> None:
    try:
        player.number_of_rcards = int(sum(_get_hand(player)))
    except Exception:
        pass




def _play_twp_success_sound(game: Any, proposal: TradeProposal) -> None:
    """Best-effort sound hook after an executed TwP deal.

    Best design is to let the Game/GUI layer own sound playback.  The current
    Successful TwP deals should use the normal cash-register deal sound.
    Informational TwP-found / infobleep sounds are reserved for offers being
    discovered or shown, not for completed trades.

    Design rule: core TwP execution may request a sound, but sound failure must
    never roll back a completed resource-card trade.
    """

    _ = proposal  # reserved for future per-trade sounds/metadata

    # Correct GUI sound keys from gui.gui_constants.Sound.
    # DEAL is CashRegister.wav and is preferred for completed TwP trades.
    # STEAL is a compatibility fallback because it also maps to CashRegister.wav
    # in older gui_constants copies.  Do not fall back to TWPFOUND2/infobleep
    # here: those are informational sounds, not successful-deal sounds.
    sound_names = ("DEAL", "STEAL")

    # Preferred design: use Game's existing execution-action sound hook.  The
    # companion core/game.py maps TwP actions to DEAL.
    execution_sound = getattr(game, "_play_execution_action_sound", None)
    if callable(execution_sound):
        for action_name in ("TwP", "TwP - Make offer", "trade_with_player"):
            try:
                if execution_sound(action_name):
                    return
            except Exception:
                pass

    # Secondary design: the game or GUI layer may expose a direct play_sound API.
    # Try the canonical GUI keys first, while keeping the old "infobleep" string
    # as a compatibility fallback.
    for hook_name in ("play_sound", "playSound", "sound_play"):
        hook = getattr(game, hook_name, None)
        if callable(hook):
            for sound_name in sound_names:
                try:
                    hook(sound_name)
                    return
                except TypeError:
                    try:
                        hook(sound_name, event="twp_executed")
                        return
                    except Exception:
                        pass
                except Exception:
                    pass

    # Compatibility fallbacks: game.sounds["TWPFOUND2"], game.gui.sounds,
    # game.sound_manager.TWPFOUND2, etc.
    candidate_roots = [game]
    for attr in ("sound_manager", "sounds", "audio", "gui"):
        value = getattr(game, attr, None)
        if value is not None:
            candidate_roots.append(value)

    for root in candidate_roots:
        sound = None
        if isinstance(root, Mapping):
            for sound_name in sound_names:
                sound = root.get(sound_name)
                if sound is not None:
                    break
        else:
            for sound_name in sound_names:
                sound = getattr(root, sound_name, None)
                if sound is not None:
                    break

        if sound is None:
            continue

        try:
            if callable(sound):
                sound()
                return
            play = getattr(sound, "play", None)
            if callable(play):
                play()
                return
        except Exception:
            pass

    # Final project-specific fallback: import the GUI registry lazily.  This
    # keeps player_trade.py import-safe in non-GUI tests, but lets main.py play
    # the actual sound when pygame/gui_constants is available.
    try:
        from gui.gui_constants import SOUNDS, initialize_sounds  # type: ignore

        if not SOUNDS:
            try:
                initialize_sounds()
            except Exception:
                pass

        for sound_name in sound_names:
            sound = SOUNDS.get(sound_name)
            if sound is None:
                continue
            play = getattr(sound, "play", None)
            if callable(play):
                play()
                return
    except Exception:
        pass


def _current_twp_scope(game: Any) -> Tuple[Optional[int], Optional[int]]:
    """Return the current (round, turn) marker used for same-turn TwP memory."""

    return (
        _safe_int_or_none(getattr(game, "round", None)),
        _safe_int_or_none(getattr(game, "turn", None)),
    )


def _same_twp_scope(game: Any, record: Mapping[str, Any]) -> bool:
    """Return True when a memory record belongs to the current game round/turn.

    The inverse-trade guard is intentionally same-turn scoped.  A player may
    rationally trade the other way on a later turn after new dice rolls change
    hands and strategy.  The loop we want to prevent is the immediate ping-pong
    within the same active turn/Continue sequence.
    """

    current_round, current_turn = _current_twp_scope(game)
    record_round = _safe_int_or_none(record.get("round"))
    record_turn = _safe_int_or_none(record.get("turn"))
    if current_round is None or current_turn is None:
        return True
    if record_round is None or record_turn is None:
        return True
    return int(record_round) == int(current_round) and int(record_turn) == int(current_turn)


def _turn_details_object(game: Any) -> Any:
    """Return the current turn-details object when available."""

    return getattr(game, "turn_details", None)


def _normalise_twp_record_list(raw_records: Any) -> List[Mapping[str, Any]]:
    """Return mapping records from a dynamically stored TwP memory value."""

    if not isinstance(raw_records, list):
        return []
    return [record for record in raw_records if isinstance(record, Mapping)]


def _twp_memory_records(game: Any) -> List[Mapping[str, Any]]:
    """Return same-turn accepted TwP records.

    Architectural home: ``game.turn_details.accepted_twp_deal_memory``.  This
    is turn-scoped state, so it belongs with the rest of the per-turn event
    details rather than as a loose ``Game`` attribute.

    Compatibility fallback: older test doubles or partially loaded games may
    not have ``turn_details``.  In that case, the function still reads the
    legacy ``game.twp_accepted_deal_memory`` attribute if present.
    """

    records: List[Mapping[str, Any]] = []

    turn_details = _turn_details_object(game)
    if turn_details is not None:
        records.extend(_normalise_twp_record_list(getattr(turn_details, "accepted_twp_deal_memory", None)))

    # Read-only legacy/mock fallbacks.  New records are written to turn_details
    # when available; lightweight tests without turn_details use
    # game.accepted_twp_deal_memory, while earlier builds used
    # game.twp_accepted_deal_memory.
    records.extend(_normalise_twp_record_list(getattr(game, "accepted_twp_deal_memory", None)))
    records.extend(_normalise_twp_record_list(getattr(game, "twp_accepted_deal_memory", None)))

    seen = set()
    same_turn_records: List[Mapping[str, Any]] = []
    for record in records:
        if not _same_twp_scope(game, record):
            continue
        key = (
            _safe_int_or_none(record.get("round")),
            _safe_int_or_none(record.get("turn")),
            _safe_int_or_none(record.get("active_player_id")),
            _safe_int_or_none(record.get("counterparty_id")),
            _safe_int_or_none(record.get("active_give_index")),
            _safe_int_or_none(record.get("active_give_count")),
            _safe_int_or_none(record.get("active_receive_index")),
            _safe_int_or_none(record.get("active_receive_count")),
        )
        if key in seen:
            continue
        seen.add(key)
        same_turn_records.append(record)
    return same_turn_records


def _proposal_is_inverse_of_record(proposal: TradeProposal, record: Mapping[str, Any]) -> bool:
    """Return True when ``proposal`` would undo a previous accepted TwP deal."""

    try:
        record_active = int(record.get("active_player_id"))
        record_counter = int(record.get("counterparty_id"))
        record_give_idx = int(record.get("active_give_index"))
        record_give_count = int(record.get("active_give_count"))
        record_receive_idx = int(record.get("active_receive_index"))
        record_receive_count = int(record.get("active_receive_count"))
    except Exception:
        return False

    # Same active/counter pair: old active tries to give back what they received.
    same_direction_inverse = (
        int(proposal.active_player_id) == record_active
        and int(proposal.counterparty_id) == record_counter
        and int(proposal.active_give_index) == record_receive_idx
        and int(proposal.active_give_count) == record_receive_count
        and int(proposal.active_receive_index) == record_give_idx
        and int(proposal.active_receive_count) == record_give_count
    )
    if same_direction_inverse:
        return True

    # Swapped active/counter pair: old counter tries to undo the same transfer.
    swapped_direction_inverse = (
        int(proposal.active_player_id) == record_counter
        and int(proposal.counterparty_id) == record_active
        and int(proposal.active_give_index) == record_give_idx
        and int(proposal.active_give_count) == record_give_count
        and int(proposal.active_receive_index) == record_receive_idx
        and int(proposal.active_receive_count) == record_receive_count
    )
    return bool(swapped_direction_inverse)


def _is_inverse_of_recent_accepted_twp(game: Any, proposal: TradeProposal) -> Tuple[bool, str]:
    """Block immediate inverse TwP proposals within the same active turn.

    Example loop to prevent:
        P2: 1Wd -> 1B with P1
        P2: 1B  -> 1Wd with P1

    The guard is checked both while generating candidates and again immediately
    before execution, so a frozen/stale Best-Action proposal cannot execute after a
    different TwP deal has changed the turn context.
    """

    for record in _twp_memory_records(game):
        if _proposal_is_inverse_of_record(proposal, record):
            try:
                previous = (
                    f"P{int(record.get('active_player_id'))}: "
                    f"{int(record.get('active_give_count'))}{RESOURCE_ABBR[int(record.get('active_give_index'))]}"
                    f"->{int(record.get('active_receive_count'))}{RESOURCE_ABBR[int(record.get('active_receive_index'))]} "
                    f"with P{int(record.get('counterparty_id'))}"
                )
            except Exception:
                previous = "previous accepted TwP"
            return (
                True,
                f"Blocked inverse TwP in same turn: {proposal.description} would undo {previous}.",
            )
    return False, ""


def _record_signature_from_record(record: Mapping[str, Any]) -> Tuple[Optional[int], ...]:
    """Return the canonical signature tuple for a TwP memory record."""

    return (
        _safe_int_or_none(record.get("active_player_id")),
        _safe_int_or_none(record.get("counterparty_id")),
        _safe_int_or_none(record.get("active_give_index")),
        _safe_int_or_none(record.get("active_give_count")),
        _safe_int_or_none(record.get("active_receive_index")),
        _safe_int_or_none(record.get("active_receive_count")),
    )


def _remember_accepted_twp_deal(game: Any, proposal: TradeProposal) -> None:
    """Store accepted TwP deal metadata used by the inverse-trade guard.

    Preferred storage is ``game.turn_details.accepted_twp_deal_memory`` because
    inverse-deal prevention is same-turn state.  When ``turn_details`` is not
    available, the function falls back to the legacy game-level attribute so
    standalone tests and lightweight mock games keep working.
    """

    try:
        current_round, current_turn = _current_twp_scope(game)
        record = {
            "round": current_round,
            "turn": current_turn,
            "active_player_id": int(proposal.active_player_id),
            "counterparty_id": int(proposal.counterparty_id),
            "active_give_index": int(proposal.active_give_index),
            "active_give_count": int(proposal.active_give_count),
            "active_receive_index": int(proposal.active_receive_index),
            "active_receive_count": int(proposal.active_receive_count),
            "trade_type": str(proposal.trade_type),
            "description": proposal.description,
            "legacy_short_text": _format_short_trade(proposal),
        }

        turn_details = _turn_details_object(game)
        owner = turn_details if turn_details is not None else game

        records = getattr(owner, "accepted_twp_deal_memory", None)
        if not isinstance(records, list):
            records = []
        records.append(record)

        # Keep the list small and remove records that are not from this turn.
        same_turn_records = [r for r in records if isinstance(r, Mapping) and _same_twp_scope(game, r)]
        same_turn_records = same_turn_records[-20:]
        setattr(owner, "accepted_twp_deal_memory", same_turn_records)

        # Store lightweight signatures too.  The current guard uses the record
        # list so it can produce readable debug reasons, but the signatures make
        # turn_details easy to inspect and future-proof for faster lookups.
        signatures = [_record_signature_from_record(r) for r in same_turn_records]
        setattr(owner, "accepted_twp_deal_signatures", signatures)

        # Keep one explicit last-deal pointer on turn_details when available;
        # otherwise use the legacy game object fallback.
        setattr(owner, "last_accepted_twp_deal", record)
        if turn_details is None:
            setattr(game, "twp_last_accepted_deal", record)
    except Exception:
        pass

def _record_twp_turn_details(game: Any, active: Any, counter: Any, proposal: TradeProposal) -> None:
    _remember_accepted_twp_deal(game, proposal)
    active_delta = list(proposal.active_gain_vector) + [0]
    counter_delta = list(proposal.counterparty_gain_vector) + [0]
    setattr(active, "turn_details_TwP", active_delta)
    setattr(active, "turn_details_last_TwPdeal", active_delta)
    setattr(counter, "turn_details_TwP", counter_delta)
    setattr(counter, "turn_details_last_TwPdeal", counter_delta)

    myturn = getattr(game, "myturn", None)
    if myturn is not None:
        try:
            myturn.number_of_deals_offered = int(getattr(myturn, "number_of_deals_offered", 0) or 0) + 1
        except Exception:
            pass

    # S7e Activity: completed TwP — both participants get TrP&A;
    # active proposer also gets TrP unless this offer was already counted when presented.
    try:
        from core.game_statistics import bump_player_stat

        bump_player_stat(active, "stats_twp_accepted", 1)
        bump_player_stat(counter, "stats_twp_accepted", 1)
        deal_key = (
            int(proposal.active_player_id),
            int(proposal.counterparty_id),
            int(proposal.active_give_index),
            int(proposal.active_give_count),
            int(proposal.active_receive_index),
            int(proposal.active_receive_count),
        )
        counted = getattr(game, "_s7e_twp_proposed_keys", None)
        if not isinstance(counted, set):
            counted = set()
            try:
                setattr(game, "_s7e_twp_proposed_keys", counted)
            except Exception:
                pass
        if deal_key not in counted:
            bump_player_stat(active, "stats_twp_proposed", 1)
            counted.add(deal_key)
    except Exception:
        pass

    ledger = getattr(game, "turn_event_ledger", None)
    if ledger is not None and hasattr(ledger, "add_event"):
        try:
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=proposal.active_player_id,
                event_type="TwP accepted",
                category="TwP",
                target_player_id=proposal.counterparty_id,
                resource_delta={RESOURCE_NAMES[i]: active_delta[i] for i in range(5)},
                public=True,
                source="core.player_trade.execute_twp_trade",
                reason=proposal.trade_type,
                message=proposal.description,
                metadata=proposal.as_dict(),
            )
            ledger.add_event(
                round_num=getattr(game, "round", None),
                turn=getattr(game, "turn", None),
                player_id=proposal.counterparty_id,
                event_type="TwP accepted",
                category="TwP",
                target_player_id=proposal.active_player_id,
                resource_delta={RESOURCE_NAMES[i]: counter_delta[i] for i in range(5)},
                public=True,
                source="core.player_trade.execute_twp_trade",
                reason=proposal.trade_type,
                message=proposal.description,
                metadata=proposal.as_dict(),
            )
        except Exception:
            pass


def _format_short_trade(proposal: TradeProposal) -> str:
    return (
        f"P{proposal.active_player_id}: "
        f"{proposal.active_give_count}{RESOURCE_ABBR[proposal.active_give_index]}"
        f"->{proposal.active_receive_count}{RESOURCE_ABBR[proposal.active_receive_index]} "
        f"with P{proposal.counterparty_id}"
    )


def _named(values: Sequence[Any]) -> Dict[str, Any]:
    return {RESOURCE_NAMES[i]: values[i] for i in range(min(5, len(values)))}


def _safe_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if not isfinite(out):
            return default
        return out
    except Exception:
        return default


def _list5_int(values: Optional[Sequence[Any]], default: int = 0) -> List[int]:
    out = [int(round(_safe_float(v, float(default)))) for v in list(values or [])[:5]]
    out.extend([int(default)] * max(0, 5 - len(out)))
    return out


def _list5_float(values: Optional[Sequence[Any]], default: float = 0.0) -> List[float]:
    out = [_safe_float(v, default) for v in list(values or [])[:5]]
    out.extend([float(default)] * max(0, 5 - len(out)))
    return out


def _tuple5_int(values: Optional[Sequence[Any]], default: int = 0) -> Tuple[int, int, int, int, int]:
    vec = _list5_int(values, default=default)
    return int(vec[0]), int(vec[1]), int(vec[2]), int(vec[3]), int(vec[4])


def _tuple5_float(values: Optional[Sequence[Any]], default: float = 0.0) -> Tuple[float, float, float, float, float]:
    vec = _list5_float(values, default=default)
    return float(vec[0]), float(vec[1]), float(vec[2]), float(vec[3]), float(vec[4])
