"""AI Play Year of Plenty (YOP) — gates, MVP, resource pair, thin execute.

Runtime pipeline:
  1. Gate legality
  2. MVP play/hold (C-Crit complete-now)
  3. Attach resource pair (r1, r2)
  4. Thin execute + Continue re-scan so buy/build can follow
  5. Log reason codes

API:

  plan_ai_play_yop(game) -> {play, timing, reason, resource_indices, ...}
  execute_ai_play_yop(game, plan=...) -> {ok, resource_indices, slice_d, ...}

YOP is **post-roll only**. Execute consumes the card, adds two bank resources,
then re-scans so city/settle/etc. can appear on the next AI Continue.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ── Reason codes (gates) ────────────────────────────────────────────────────
REASON_SKELETON_HOLD = "skeleton_hold"
REASON_NOT_EXECUTION = "not_execution_phase"
REASON_NO_PLAYER = "no_current_player"
REASON_HUMAN_PLAYER = "current_player_is_human"
REASON_ROBBER_ACTIVE = "robber_flow_already_active"
REASON_DCARD_ALREADY = "already_played_dcard_this_turn"
REASON_NO_YOP = "no_playable_yop"
REASON_WRONG_STATE = "yop_not_legal_in_state"
REASON_DISCARD_PENDING = "discard_pending"
REASON_KNIGHT_PENDING = "knight_play_already_pending"
REASON_TFR_PENDING = "tfr_play_already_pending"
REASON_YOP_PRE_ROLL = "yop_requires_dice_already_rolled"

# ── Reason codes (MVP play / hold) ──────────────────────────────────────────
REASON_C_CRIT = "c_crit"
REASON_C_SOFT = "c_soft"
REASON_HOLD_EARLY = "hold_early"
REASON_HOLD_ALT_DCARD = "hold_alt_dcard"
REASON_HOLD_DEFAULT = "hold_default"
REASON_HOLD_NO_SHORTFALL = "hold_no_shortfall"
REASON_HOLD_BANK_COVERS = "hold_bank_covers"
REASON_HOLD_DCARD_BUY = "hold_yop_for_dcard"

CARD_TYPE = "year_of_plenty"
RESOURCE_ORDER = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_ALIASES = (
    ("Wheat", "wheat", "grain", "WHEAT"),
    ("Ore", "ore", "ORE"),
    ("Wood", "wood", "lumber", "WOOD"),
    ("Brick", "brick", "clay", "BRICK"),
    ("Sheep", "sheep", "wool", "SHEEP"),
)

# Cost vectors [Wheat, Ore, Wood, Brick, Sheep]
COST_CITY = [2, 3, 0, 0, 0]
COST_SETTLE = [1, 0, 1, 1, 1]
COST_ROAD = [0, 0, 1, 1, 0]
COST_DCARD = [1, 1, 0, 0, 1]

ACTION_COSTS: Dict[str, List[int]] = {
    "Build city": list(COST_CITY),
    "Build settlement": list(COST_SETTLE),
    "Build road": list(COST_ROAD),
    "Buy development_card": list(COST_DCARD),
}

# Complete-now value for ranking targets
ACTION_VALUE = {
    "Build city": 12.0,
    "Build settlement": 9.0,
    "Buy development_card": 6.0,
    "Build road": 3.5,
}

ROBBER_FLOW_STATES = frozenset(
    {
        "MoveRobber",
        "RobberMoveRequired",
        "SetRobber",
        "StealSelectOpponent",
        "StealPickRCard",
        "DiscardPending",
    }
)

STAGE = "execute_thin"

EARLY_VP_MAX = 3
ALT_DCARD_BLOCK_MIN = 6.0
C_SOFT_MIN_VALUE = 6.0


def _safe_player_id(player: Any) -> Optional[int]:
    try:
        return int(getattr(player, "id", 0) or 0)
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _dice_not_rolled(game: Any) -> bool:
    dice_roll = getattr(game, "dice_roll", None)
    state = str(getattr(game, "state", "") or "")
    if state == "AwaitingDiceRoll":
        return True
    if dice_roll in (None, 0, "", []):
        return True
    if isinstance(dice_roll, (list, tuple)):
        return len(dice_roll) == 0
    try:
        return int(dice_roll) <= 0
    except Exception:
        return False


def _dcard_already_played_this_turn(game: Any) -> bool:
    for attr in ("myturn", "turn_details"):
        try:
            td = getattr(game, attr, None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                return True
        except Exception:
            pass
    return False


def _is_human_player(game: Any, player: Any) -> bool:
    try:
        if bool(getattr(player, "is_human", False)):
            return True
    except Exception:
        pass
    try:
        checker = getattr(game, "_is_current_player_human_for_execution", None)
        if callable(checker) and player is getattr(game, "current_player", None):
            return bool(checker())
        if callable(checker) and player is game.get_current_player():
            return bool(checker())
    except Exception:
        pass
    return False


def playable_yop_count(player: Any) -> int:
    """How many YOP cards the player may legally play (core-side, no GUI)."""
    if player is None:
        return 0
    found_row = False
    try:
        summary = list(getattr(player, "dcard_summary", []) or [])
        for row in summary:
            row_list = list(row or [])
            if not row_list:
                continue
            if str(row_list[0]) != CARD_TYPE:
                continue
            found_row = True
            while len(row_list) < 4:
                row_list.append(0)
            return max(0, int(row_list[2] or 0))
    except Exception:
        found_row = False
    if found_row:
        return 0
    try:
        return sum(
            1 for c in (getattr(player, "development_cards", []) or []) if str(c) == CARD_TYPE
        )
    except Exception:
        return 0


def _resolve_window(game: Any, window: Optional[str]) -> str:
    if window in ("pre_roll", "post_roll"):
        return str(window)
    state = str(getattr(game, "state", "") or "")
    if state == "AwaitingDiceRoll" or _dice_not_rolled(game):
        return "pre_roll"
    if state == "ActionSelection":
        return "post_roll"
    return "unknown"


def evaluate_ai_yop_gates(
    game: Any,
    player: Any,
    *,
    window: Optional[str] = None,
) -> Dict[str, Any]:
    """Return gate evaluation without mutating game state."""
    resolved = _resolve_window(game, window)
    gates: Dict[str, Any] = {
        "phase_ok": False,
        "player_ok": False,
        "ai_ok": False,
        "not_robber_flow": False,
        "not_discard_pending": False,
        "not_knight_pending": False,
        "not_tfr_pending": False,
        "dcard_slot_free": False,
        "has_playable_yop": False,
        "state_ok": False,
        "post_roll_only": True,
        "window": resolved,
    }
    reasons_failed: List[str] = []

    phase = str(getattr(game, "phase", "") or "")
    gates["phase_ok"] = phase == "Execution"
    if not gates["phase_ok"]:
        reasons_failed.append(REASON_NOT_EXECUTION)

    if player is None:
        reasons_failed.append(REASON_NO_PLAYER)
    else:
        gates["player_ok"] = True

    if player is not None:
        human = _is_human_player(game, player)
        gates["ai_ok"] = not human
        if human:
            reasons_failed.append(REASON_HUMAN_PLAYER)

    state = str(getattr(game, "state", "") or "")
    if state in ROBBER_FLOW_STATES:
        reasons_failed.append(REASON_ROBBER_ACTIVE)
    else:
        gates["not_robber_flow"] = True

    pending_7 = getattr(game, "pending_seven_roll", None) or {}
    pending_steal = getattr(game, "pending_robber_steal", None) or {}
    if isinstance(pending_7, dict) and pending_7.get("active"):
        gates["not_robber_flow"] = False
        if REASON_ROBBER_ACTIVE not in reasons_failed:
            reasons_failed.append(REASON_ROBBER_ACTIVE)
    if isinstance(pending_steal, dict) and pending_steal.get("active"):
        gates["not_robber_flow"] = False
        if REASON_ROBBER_ACTIVE not in reasons_failed:
            reasons_failed.append(REASON_ROBBER_ACTIVE)

    pending_discard = list(getattr(game, "pending_discard_queue", None) or [])
    if pending_discard:
        reasons_failed.append(REASON_DISCARD_PENDING)
    else:
        gates["not_discard_pending"] = True

    pending_knight = getattr(game, "pending_knight_play", None) or {}
    if isinstance(pending_knight, dict) and pending_knight.get("active"):
        reasons_failed.append(REASON_KNIGHT_PENDING)
    else:
        gates["not_knight_pending"] = True

    pending_tfr = getattr(game, "pending_tfr_play", None) or {}
    if isinstance(pending_tfr, dict) and pending_tfr.get("active"):
        reasons_failed.append(REASON_TFR_PENDING)
    else:
        gates["not_tfr_pending"] = True

    if _dcard_already_played_this_turn(game):
        reasons_failed.append(REASON_DCARD_ALREADY)
    else:
        gates["dcard_slot_free"] = True

    yop_count = playable_yop_count(player) if player is not None else 0
    gates["playable_yop_count"] = int(yop_count)
    if yop_count > 0:
        gates["has_playable_yop"] = True
    else:
        reasons_failed.append(REASON_NO_YOP)

    if resolved == "pre_roll":
        state_ok = False
        if REASON_YOP_PRE_ROLL not in reasons_failed:
            reasons_failed.append(REASON_YOP_PRE_ROLL)
    elif resolved == "post_roll":
        state_ok = state == "ActionSelection" and not _dice_not_rolled(game)
        if not state_ok:
            reasons_failed.append(REASON_WRONG_STATE)
    else:
        state_ok = False
        reasons_failed.append(REASON_WRONG_STATE)
    gates["state_ok"] = bool(state_ok)

    legal = (
        gates["phase_ok"]
        and gates["player_ok"]
        and gates["ai_ok"]
        and gates["not_robber_flow"]
        and gates["not_discard_pending"]
        and gates["not_knight_pending"]
        and gates["not_tfr_pending"]
        and gates["dcard_slot_free"]
        and gates["has_playable_yop"]
        and gates["state_ok"]
    )

    primary_reason = reasons_failed[0] if reasons_failed else REASON_HOLD_DEFAULT
    return {
        "legal": bool(legal),
        "gates": gates,
        "failed_reasons": reasons_failed,
        "primary_gate_reason": primary_reason if not legal else None,
        "window": resolved,
        "playable_yop_count": int(yop_count),
        "state": state,
        "phase": phase,
    }


# ────────────────────────────────────────────────────────────────────────────
# Hand / shortfall / C-Crit
# ────────────────────────────────────────────────────────────────────────────


def hand_vector5(player: Any) -> List[int]:
    """Return [Wheat, Ore, Wood, Brick, Sheep] counts from player.rcards."""
    out = [0, 0, 0, 0, 0]
    if player is None:
        return out
    rcards = getattr(player, "rcards", None)
    if not isinstance(rcards, Mapping):
        return out
    for i, aliases in enumerate(RESOURCE_ALIASES):
        total = 0
        for key, val in rcards.items():
            text = str(getattr(key, "value", key)).strip()
            name = str(getattr(key, "name", "")).strip()
            key_l = text.lower()
            name_l = name.lower()
            for alias in aliases:
                if key_l == str(alias).lower() or name_l == str(alias).lower() or text == str(alias):
                    try:
                        total += int(val or 0)
                    except Exception:
                        pass
                    break
        out[i] = max(0, total)
    return out


def need_vector(hand: Sequence[int], cost: Sequence[int]) -> List[int]:
    h = list(hand[:5]) + [0] * 5
    c = list(cost[:5]) + [0] * 5
    return [max(0, int(c[i] or 0) - int(h[i] or 0)) for i in range(5)]


def shortfall_sum(need: Sequence[int]) -> int:
    return sum(max(0, int(x or 0)) for x in list(need)[:5])


def pick_two_from_need(
    need: Sequence[int],
    *,
    production_pips: Optional[Sequence[float]] = None,
    bank_occupied: Optional[Sequence[int]] = None,
) -> Tuple[int, int]:
    """Greedy fill of shortfall into exactly two resource indices.

    Phase B: when padding a free second (or leftover) slot, prefer scarce
    production (lowest own pips), then bank scarcity — not always Ore.
    """
    from core.ai_dcard_timing import scarcest_resource_indices

    picks: List[int] = []
    need_left = [max(0, int(x or 0)) for x in list(need)[:5]]
    while len(need_left) < 5:
        need_left.append(0)
    for i in range(5):
        while need_left[i] > 0 and len(picks) < 2:
            picks.append(i)
            need_left[i] -= 1
    # Pad remaining slots with scarce production resources
    while len(picks) < 2:
        if any(need_left):
            for i in range(5):
                if need_left[i] > 0:
                    picks.append(i)
                    need_left[i] -= 1
                    break
            else:
                scarce = scarcest_resource_indices(
                    production_pips, bank_occupied=bank_occupied, n=1
                )
                picks.append(scarce[0] if scarce else 1)
        else:
            # Free pad: scarcest among types not already double-stacked if possible
            scarce = scarcest_resource_indices(
                production_pips,
                bank_occupied=bank_occupied,
                exclude=[],
                n=5,
            )
            chosen = None
            for idx in scarce:
                # Prefer a type we don't already hold twice in picks
                if picks.count(idx) < 2:
                    chosen = idx
                    break
            if chosen is None:
                chosen = scarce[0] if scarce else (picks[0] if picks else 1)
            picks.append(int(chosen))
    return int(picks[0]), int(picks[1])


def _production_pips5(game: Any, player: Any) -> List[float]:
    """Best-effort production pips [W,O,Wd,B,S]."""
    try:
        from core.resource_time_estimator import get_player_production_pips

        board = getattr(game, "board", None)
        if board is not None and player is not None:
            pips = get_player_production_pips(board, player)
            if isinstance(pips, (list, tuple)) and len(pips) >= 5:
                return [float(x or 0) for x in pips[:5]]
    except Exception:
        pass
    # Fallback: player.pips if present
    raw = getattr(player, "pips", None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 5:
        return [float(x or 0) for x in raw[:5]]
    if isinstance(raw, Mapping):
        order = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
        return [float(raw.get(k, 0) or 0) for k in order]
    return [1.0, 1.0, 1.0, 1.0, 1.0]


def _preferred_action_hint(player: Any) -> str:
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return ""
    for key in (
        "supporting_action_type",
        "preferred_action_type",
        "action_type",
        "preferred_action",
    ):
        raw = str(direction.get(key) or "").lower()
        if not raw:
            continue
        if "city" in raw:
            return "Build city"
        if "settle" in raw:
            return "Build settlement"
        if "road" in raw:
            return "Build road"
        if "dcard" in raw or "development" in raw or "dev" in raw:
            return "Buy development_card"
    if bool(direction.get("biggest_army") or direction.get("largest_army")):
        return "Buy development_card"
    if bool(direction.get("longest_road")):
        return "Build road"
    return ""


def _vp(player: Any) -> int:
    for attr in ("victory_points", "points"):
        try:
            return int(getattr(player, attr) or 0)
        except Exception:
            pass
    return 0


def _playable_count(player: Any, card_type: str) -> int:
    ct = str(card_type)
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            row_list = list(row or [])
            if not row_list or str(row_list[0]) != ct:
                continue
            while len(row_list) < 4:
                row_list.append(0)
            return max(0, int(row_list[2] or 0))
    except Exception:
        pass
    try:
        return sum(1 for c in (getattr(player, "development_cards", []) or []) if str(c) == ct)
    except Exception:
        return 0


def stub_alt_dcard_score(game: Any, player: Any) -> Dict[str, Any]:
    """Stub opportunity cost for other playable DCards."""
    best = 0.0
    best_card = None
    details: Dict[str, float] = {}

    if _playable_count(player, "knight") > 0:
        army = _safe_int(getattr(player, "size_largest_army", 0), 0)
        score = 2.0
        if army >= 2:
            score = 8.0
        details["knight"] = score
        if score > best:
            best, best_card = score, "knight"

    if _playable_count(player, "two_free_roads") > 0:
        score = 3.0
        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping):
            for key in ("roads_needed_for_settle", "next_roads_to_settle"):
                if _safe_int(direction.get(key), 0) in (1, 2):
                    score = 7.0
                    break
        details["two_free_roads"] = score
        if score > best:
            best, best_card = score, "two_free_roads"

    if _playable_count(player, "monopoly") > 0:
        score = 3.5
        details["monopoly"] = score
        if score > best:
            best, best_card = score, "monopoly"

    return {"score": float(best), "card": best_card, "details": details}


def evaluate_complete_now_targets(
    player: Any,
    *,
    hand: Optional[Sequence[int]] = None,
    trade_rates: Optional[Sequence[int]] = None,
    game: Any = None,
) -> List[Dict[str, Any]]:
    """Score actions completable with exactly 1–2 YOP resources after bank trades.

    Phase A: residual shortfall uses bank/port rates (v045 total_yop style).
    Actions the bank already covers are skipped (YOP not needed).
    """
    from core.ai_dcard_timing import bank_residual_after_trades, trade_rates_vector5

    h = list(hand) if hand is not None else hand_vector5(player)
    rates = list(trade_rates) if trade_rates is not None else None
    if rates is None:
        rates = trade_rates_vector5(game, player) if game is not None else None
        if rates is None:
            rates = list(getattr(player, "trade_rates", None) or [4, 4, 4, 4, 4])
            if not isinstance(rates, list):
                rates = [4, 4, 4, 4, 4]

    preferred = _preferred_action_hint(player)
    pips = _production_pips5(game, player) if game is not None else _production_pips5(None, player)
    bank_occ = None
    try:
        raw_tw = getattr(game, "TW_type_occupied", None) if game is not None else None
        if isinstance(raw_tw, (list, tuple)) and len(raw_tw) >= 5:
            bank_occ = [int(x or 0) for x in raw_tw[:5]]
    except Exception:
        bank_occ = None

    rows: List[Dict[str, Any]] = []
    for action, cost in ACTION_COSTS.items():
        need = need_vector(h, cost)
        short = shortfall_sum(need)
        if short <= 0:
            continue  # already affordable — YOP not needed for this action
        bank = bank_residual_after_trades(h, cost, rates)
        residual = int(bank["residual_shortfall"])
        if residual <= 0:
            continue  # bank/port trades cover the shortfall
        if residual > 2:
            continue  # YOP alone cannot complete residual
        # Pair from residual-oriented need; pad free slots by scarce pips (Phase B)
        a, b = pick_two_from_need(need, production_pips=pips, bank_occupied=bank_occ)
        value = float(ACTION_VALUE.get(action, 1.0))
        if preferred and action == preferred:
            value += 3.0
        # Late game boost for VP actions
        if _vp(player) >= 8 and action in {"Build city", "Build settlement"}:
            value += 4.0
        # Slight preference for lower residual (bank already did work)
        value += max(0.0, 2.0 - float(residual))
        rows.append(
            {
                "action": action,
                "cost": list(cost),
                "need": need,
                "shortfall": short,
                "residual_shortfall": residual,
                "total_bank_trades": int(bank["total_bank_trades"]),
                "resource_indices": [a, b],
                "value": value,
                "preferred_match": bool(preferred and action == preferred),
            }
        )
    rows.sort(key=lambda r: float(r.get("value", 0)), reverse=True)
    return rows


def collect_yop_features(
    game: Any,
    player: Any,
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    from core.ai_dcard_timing import trade_rates_vector5

    hand = hand_vector5(player)
    rates = trade_rates_vector5(game, player)
    targets = evaluate_complete_now_targets(
        player, hand=hand, trade_rates=rates, game=game
    )
    best = targets[0] if targets else None
    alt = stub_alt_dcard_score(game, player)
    vp = _vp(player)
    early = vp <= EARLY_VP_MAX
    army = _safe_int(getattr(player, "size_largest_army", 0), 0)
    preferred = _preferred_action_hint(player)
    la_race = bool(
        preferred == "Buy development_card"
        or army >= 2
        or bool(
            isinstance(getattr(player, "strategic_direction", None), Mapping)
            and (
                (getattr(player, "strategic_direction") or {}).get("biggest_army")
                or (getattr(player, "strategic_direction") or {}).get("largest_army")
            )
        )
    )
    win_nowish = vp >= 8

    c_crit = False
    demote_dcard_buy = False
    if best:
        act = str(best.get("action") or "")
        residual = int(best.get("residual_shortfall") or best.get("shortfall") or 0)
        if act in {"Build city", "Build settlement"} and 1 <= residual <= 2:
            c_crit = True
        elif act == "Buy development_card" and 1 <= residual <= 2:
            # Phase A: demote YOP→DC unless LA race or late win package
            if la_race or win_nowish or bool(best.get("preferred_match")):
                c_crit = True
            else:
                demote_dcard_buy = True
                c_crit = False
        elif act == "Build road" and best.get("preferred_match"):
            c_crit = False  # soft only for pure road
        else:
            c_crit = False

    residual_best = int(best.get("residual_shortfall") or 0) if best else 0
    bank_covers_all = bool(
        best is None
        and any(
            shortfall_sum(need_vector(hand, cost)) > 0
            for cost in ACTION_COSTS.values()
        )
    )
    # Detect "had shortfalls but bank covered every action"
    if best is None:
        for cost in ACTION_COSTS.values():
            raw = shortfall_sum(need_vector(hand, cost))
            if raw > 0:
                from core.ai_dcard_timing import bank_residual_shortfall

                if bank_residual_shortfall(hand, cost, rates) <= 0:
                    bank_covers_all = True
                    break

    features: Dict[str, Any] = {
        "hand": hand,
        "trade_rates": list(rates),
        "complete_targets": targets,
        "best_target": best,
        "c_crit": bool(c_crit and best is not None),
        "c_soft": bool(
            best is not None
            and not c_crit
            and not demote_dcard_buy
            and float(best.get("value", 0)) >= C_SOFT_MIN_VALUE
        ),
        "shortfall": int(best.get("shortfall") or 0) if best else 0,
        "residual_shortfall": residual_best,
        "target_action": str(best.get("action") or "") if best else "",
        "resource_indices": list(best.get("resource_indices") or []) if best else None,
        "vp_ai": vp,
        "early_game": early,
        "la_race": bool(la_race),
        "demote_dcard_buy": bool(demote_dcard_buy),
        "bank_covers_targets": bool(bank_covers_all),
        "alt_dcard_score": float(alt.get("score") or 0),
        "alt_dcard_card": alt.get("card"),
        "alt_dcard_details": dict(alt.get("details") or {}),
        "hand_size": sum(hand),
        "playable_yop": playable_yop_count(player),
    }

    if features_override:
        for k, v in dict(features_override).items():
            features[k] = v
        # Re-derive c_crit if only shortfall/target provided
        if "c_crit" not in features_override and features.get("best_target"):
            pass
        if "early_game" not in features_override and "vp_ai" in features_override:
            features["early_game"] = _safe_int(features.get("vp_ai"), 0) <= EARLY_VP_MAX

    return features


def decide_mvp_play_hold(features: Mapping[str, Any], window: str = "post_roll") -> Dict[str, Any]:
    """MVP: C-Crit play, bank-covers hold, demote DC-buy, alt/early/soft holds."""
    window = str(window or "post_roll")
    soft = 0.0
    best = features.get("best_target") if isinstance(features.get("best_target"), Mapping) else None
    if best:
        soft = float(best.get("value") or 0) - 0.4 * _safe_float(features.get("alt_dcard_score"), 0)

    decision: Dict[str, Any] = {
        "play": False,
        "timing": None,
        "reason": REASON_HOLD_DEFAULT,
        "score": soft,
        "rule": "default",
        "available_timing_if_play": "post_roll" if window == "post_roll" else None,
        "target_action": str(features.get("target_action") or ""),
    }

    def _play(reason: str, rule: str, score: float) -> Dict[str, Any]:
        decision.update(
            {
                "play": True,
                "timing": "post_roll" if window == "post_roll" else None,
                "reason": reason,
                "score": score,
                "rule": rule,
            }
        )
        return decision

    def _hold(reason: str, rule: str, score: float) -> Dict[str, Any]:
        decision.update(
            {
                "play": False,
                "timing": None,
                "reason": reason,
                "score": score,
                "rule": rule,
            }
        )
        return decision

    if window != "post_roll":
        return _hold(REASON_YOP_PRE_ROLL, "pre_roll_blocked", soft)

    if bool(features.get("c_crit")):
        return _play(REASON_C_CRIT, "c_crit", max(soft, 10.0))

    # Phase A: only residual need for DCard buy, and not LA/win — hold
    if bool(features.get("demote_dcard_buy")):
        return _hold(REASON_HOLD_DCARD_BUY, "hold_yop_for_dcard", soft)

    alt = _safe_float(features.get("alt_dcard_score"), 0.0)
    if alt >= ALT_DCARD_BLOCK_MIN:
        return _hold(REASON_HOLD_ALT_DCARD, "hold_alt_dcard", soft)

    if bool(features.get("early_game")):
        return _hold(REASON_HOLD_EARLY, "hold_early", soft)

    if bool(features.get("c_soft")) and soft >= C_SOFT_MIN_VALUE:
        # Avoid YOP into fat hand without spend
        if _safe_int(features.get("hand_size"), 0) >= 7:
            return _hold(REASON_HOLD_DEFAULT, "hold_hand_risk", soft)
        return _play(REASON_C_SOFT, "c_soft", soft)

    if not best:
        if bool(features.get("bank_covers_targets")):
            return _hold(REASON_HOLD_BANK_COVERS, "hold_bank_covers", soft)
        return _hold(REASON_HOLD_NO_SHORTFALL, "hold_no_shortfall", soft)

    return _hold(REASON_HOLD_DEFAULT, "hold_default", soft)


def attach_resource_pair(
    game: Any,
    player: Any,
    plan: Dict[str, Any],
    *,
    features: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach the two YOP resource indices when play is decided.

    Prefer the best complete-now target shortfall. Weak/missing pair does not
    cancel play (defaults to Ore/Ore only as last resort for execute safety).
    """
    plan = dict(plan or {})
    if not bool(plan.get("play")):
        plan["resource_indices"] = None
        plan["resource_names"] = None
        plan["resource_pair_ok"] = None
        plan["target_action"] = None
        return plan

    warnings = list(plan.get("warnings") or [])
    features = features if features is not None else (plan.get("features") or {})

    indices = features.get("resource_indices")
    if features.get("resource_indices_override") is not None:
        indices = features.get("resource_indices_override")
        source = "features_override"
    else:
        source = "complete_now_need"

    pair: Optional[List[int]] = None
    if isinstance(indices, (list, tuple)) and len(indices) >= 2:
        try:
            a, b = int(indices[0]), int(indices[1])
            if 0 <= a < 5 and 0 <= b < 5:
                pair = [a, b]
        except Exception:
            pair = None

    if pair is None:
        best = features.get("best_target") if isinstance(features.get("best_target"), Mapping) else None
        if best and isinstance(best.get("resource_indices"), (list, tuple)):
            try:
                a, b = int(best["resource_indices"][0]), int(best["resource_indices"][1])
                if 0 <= a < 5 and 0 <= b < 5:
                    pair = [a, b]
                    source = "best_target"
            except Exception:
                pair = None

    if pair is None:
        # Recompute from hand (Phase B: scarce pad via game pips)
        try:
            targets = evaluate_complete_now_targets(player, game=game)
            if targets:
                a, b = targets[0]["resource_indices"]
                pair = [int(a), int(b)]
                source = "recompute"
                plan["target_action"] = str(targets[0].get("action") or "")
        except Exception:
            pair = None

    if pair is None:
        # Phase B default: two scarcest production types (not hard-coded Ore/Ore)
        try:
            pips = _production_pips5(game, player)
            from core.ai_dcard_timing import scarcest_resource_indices

            scarce = scarcest_resource_indices(pips, n=2)
            if len(scarce) >= 2:
                pair = [int(scarce[0]), int(scarce[1])]
            elif len(scarce) == 1:
                pair = [int(scarce[0]), int(scarce[0])]
            else:
                pair = [1, 1]
            source = "scarce_default"
        except Exception:
            pair = [1, 1]
            source = "default_ore_ore"
        warnings.append("play_without_perfect_pair")

    names = [RESOURCE_ORDER[pair[0]], RESOURCE_ORDER[pair[1]]]
    plan["resource_indices"] = pair
    plan["resource_names"] = names
    plan["resource_pair_ok"] = source != "default_ore_ore"
    plan["resource_pair_source"] = source
    plan["target_action"] = plan.get("target_action") or features.get("target_action")
    plan["play"] = True
    plan["warnings"] = warnings
    return plan


def _empty_plan(
    *,
    play: bool = False,
    timing: Optional[str] = None,
    reason: str,
    legal: bool = False,
    window: str = "unknown",
    player_id: Optional[int] = None,
    gates: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "ok": True,
        "action": "plan_ai_play_yop",
        "card": CARD_TYPE,
        "stage": STAGE,
        "play": bool(play),
        "timing": timing,
        "reason": str(reason or ""),
        "legal": bool(legal),
        "window": window,
        "player_id": player_id,
        "resource_indices": None,
        "resource_names": None,
        "resource_pair_ok": None,
        "target_action": None,
        "gates": dict(gates or {}),
        "failed_reasons": [],
        "playable_yop_count": int((gates or {}).get("playable_yop_count") or 0),
        "score": None,
        "features": {},
        "rule": None,
        "warnings": [],
        "executed": False,
        "notes": (
            "Thin pipeline: MVP C-Crit play/hold, resource pair attach, "
            "execute adds resources and re-scans."
        ),
    }
    if extra:
        plan.update(extra)
    return plan


def log_ai_yop_plan(game: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = dict(plan or {})
    window = str(plan.get("window") or "unknown")

    try:
        game.last_ai_yop_plan = plan
    except Exception:
        pass
    try:
        by_window = getattr(game, "last_ai_yop_plan_by_window", None)
        if not isinstance(by_window, dict):
            by_window = {}
        by_window[window] = plan
        game.last_ai_yop_plan_by_window = by_window
    except Exception:
        pass
    if window == "pre_roll":
        try:
            game.last_ai_yop_plan_pre_roll = plan
        except Exception:
            pass
    elif window == "post_roll":
        try:
            game.last_ai_yop_plan_post_roll = plan
        except Exception:
            pass

    trace_row = {
        "kind": "play_yop",
        "stage": plan.get("stage"),
        "window": window,
        "play": bool(plan.get("play")),
        "timing": plan.get("timing"),
        "reason": plan.get("reason"),
        "legal": bool(plan.get("legal")),
        "player_id": plan.get("player_id"),
        "playable_yop_count": plan.get("playable_yop_count"),
        "resource_indices": plan.get("resource_indices"),
        "target_action": plan.get("target_action"),
        "score": plan.get("score"),
        "rule": plan.get("rule"),
    }
    try:
        trace = getattr(game, "current_ai_decision_trace", None)
        if not isinstance(trace, list):
            trace = []
            game.current_ai_decision_trace = trace
        trace.append(trace_row)
    except Exception:
        pass

    try:
        if bool(getattr(game, "execution_debug_print_tf", False)):
            print(
                "AI YOP plan "
                f"[P{plan.get('player_id')}] window={window} "
                f"legal={plan.get('legal')} play={plan.get('play')} "
                f"timing={plan.get('timing')} reason={plan.get('reason')} "
                f"pick={plan.get('resource_names')} target={plan.get('target_action')}"
            )
    except Exception:
        pass

    return plan


def plan_ai_play_yop(
    game: Any,
    player: Any = None,
    *,
    window: Optional[str] = None,
    log: bool = True,
    features_override: Optional[Mapping[str, Any]] = None,
    skip_resource_pair: bool = False,
) -> Dict[str, Any]:
    """Plan YOP: gates + MVP play/hold + resource pair attach."""
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    player_id = _safe_player_id(player)
    gate_info = evaluate_ai_yop_gates(game, player, window=window)
    resolved = str(gate_info.get("window") or "unknown")
    gates = dict(gate_info.get("gates") or {})

    if not gate_info.get("legal"):
        reason = str(
            gate_info.get("primary_gate_reason")
            or (gate_info.get("failed_reasons") or [REASON_WRONG_STATE])[0]
        )
        plan = _empty_plan(
            play=False,
            timing=None,
            reason=reason,
            legal=False,
            window=resolved,
            player_id=player_id,
            gates=gates,
            extra={
                "failed_reasons": list(gate_info.get("failed_reasons") or []),
                "playable_yop_count": int(gate_info.get("playable_yop_count") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
            },
        )
    else:
        features = collect_yop_features(
            game, player, features_override=features_override
        )
        decision = decide_mvp_play_hold(features, resolved)
        plan = _empty_plan(
            play=bool(decision.get("play")),
            timing=decision.get("timing"),
            reason=str(decision.get("reason") or REASON_HOLD_DEFAULT),
            legal=True,
            window=resolved,
            player_id=player_id,
            gates=gates,
            extra={
                "failed_reasons": [],
                "playable_yop_count": int(gate_info.get("playable_yop_count") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
                "available_timing_if_play": decision.get("available_timing_if_play"),
                "score": decision.get("score"),
                "features": features,
                "rule": decision.get("rule"),
                "target_action": decision.get("target_action") or features.get("target_action"),
            },
        )
        if bool(plan.get("play")) and not skip_resource_pair:
            plan = attach_resource_pair(game, player, plan, features=features)

    if log:
        plan = log_ai_yop_plan(game, plan)
    return plan


# ────────────────────────────────────────────────────────────────────────────
# Thin execute
# ────────────────────────────────────────────────────────────────────────────


def _consume_yop_card(game: Any, player: Any) -> Dict[str, Any]:
    remover = getattr(game, "_remove_development_card_from_player", None)
    if callable(remover):
        if remover(player, CARD_TYPE):
            return {"ok": True, "source": "game_remove"}
        try:
            idx_fn = getattr(game, "_execution_dcard_summary_index", None)
            idx = int(idx_fn(CARD_TYPE)) if callable(idx_fn) else 3
            row = player.dcard_summary[idx]
            if int(row[2] or 0) <= 0:
                return {"ok": False, "reason": REASON_NO_YOP}
            row[2] = int(row[2]) - 1
            row[3] = int(row[3] or 0) + 1
            cards = list(getattr(player, "development_cards", []) or [])
            for i, c in enumerate(cards):
                if str(c) == CARD_TYPE:
                    cards.pop(i)
                    break
            player.development_cards = cards
            player.number_of_dcards = len(cards)
            return {"ok": True, "source": "summary_force"}
        except Exception:
            return {"ok": False, "reason": "could_not_consume_yop"}

    cards = list(getattr(player, "development_cards", []) or [])
    for i, c in enumerate(cards):
        if str(c) == CARD_TYPE:
            cards.pop(i)
            player.development_cards = cards
            try:
                for row in list(getattr(player, "dcard_summary", []) or []):
                    if row and str(row[0]) == CARD_TYPE:
                        while len(row) < 4:
                            row.append(0)
                        if int(row[2] or 0) > 0:
                            row[2] = int(row[2]) - 1
                        row[3] = int(row[3] or 0) + 1
                        break
            except Exception:
                pass
            return {"ok": True, "source": "fallback_list"}
    return {"ok": False, "reason": REASON_NO_YOP}


def _add_yop_resources(game: Any, player: Any, a: int, b: int) -> Dict[str, Any]:
    """Add two resources to the hand (bank unlimited in this ruleset)."""
    gain_vec = [0, 0, 0, 0, 0]
    gain_vec[a] += 1
    gain_vec[b] += 1

    # Prefer Game resource keys when available
    resources = None
    try:
        order_fn = getattr(game, "_execution_resource_order", None)
        if callable(order_fn):
            resources = list(order_fn())[:5]
    except Exception:
        resources = None
    if not resources or len(resources) < 5:
        try:
            from core.constants import ResourceCard

            resources = [
                ResourceCard.WHEAT,
                ResourceCard.ORE,
                ResourceCard.WOOD,
                ResourceCard.BRICK,
                ResourceCard.SHEEP,
            ]
        except Exception:
            resources = list(RESOURCE_ORDER)

    try:
        if not isinstance(getattr(player, "rcards", None), dict):
            player.rcards = {}
        for idx in range(5):
            amount = int(gain_vec[idx] or 0)
            if amount <= 0:
                continue
            key = resources[idx]
            # Also set string name for tests using string keys
            name = RESOURCE_ORDER[idx]
            player.rcards[key] = int(player.rcards.get(key, 0) or 0) + amount
            if key != name:
                player.rcards[name] = int(player.rcards.get(name, 0) or 0) + amount
        try:
            from core.constants import ResourceCard

            player.number_of_rcards = sum(
                int(player.rcards.get(rc, 0) or 0) for rc in ResourceCard
            )
        except Exception:
            player.number_of_rcards = sum(hand_vector5(player))
    except Exception as exc:
        return {"ok": False, "reason": f"could_not_add_resources:{exc}", "gain_vector": gain_vec}

    return {
        "ok": True,
        "gain_vector": gain_vec,
        "resource_indices": [a, b],
        "resource_names": [RESOURCE_ORDER[a], RESOURCE_ORDER[b]],
    }


def execute_ai_play_yop(
    game: Any,
    player: Any = None,
    *,
    plan: Optional[Mapping[str, Any]] = None,
    window: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Thin execute: consume YOP, add two resources, re-scan for Continue."""
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    result: Dict[str, Any] = {
        "ok": False,
        "action": "Play Year of Plenty",
        "source": "ai",
        "stage": STAGE,
        "reason": "",
        "player_id": _safe_player_id(player),
        "plan": None,
        "resource_indices": None,
        "resource_names": None,
        "slice_d": None,
        "executed": False,
    }

    if plan is None:
        plan = plan_ai_play_yop(game, player, window=window or "post_roll", log=True)
    plan = dict(plan or {})
    result["plan"] = plan

    if not bool(plan.get("legal")) and not force:
        result["reason"] = str(plan.get("reason") or "not_legal")
        return result
    if not bool(plan.get("play")) and not force:
        result["reason"] = str(plan.get("reason") or "plan_hold")
        return result

    gates = evaluate_ai_yop_gates(game, player, window="post_roll")
    if not gates.get("legal") and not force:
        result["reason"] = str(gates.get("primary_gate_reason") or "not_legal_at_execute")
        return result

    if _is_human_player(game, player):
        result["reason"] = REASON_HUMAN_PLAYER
        return result

    ensure = getattr(game, "_ensure_player_dcard_state", None)
    if callable(ensure):
        try:
            ensure(player)
        except Exception:
            pass

    consumed = _consume_yop_card(game, player)
    if not consumed.get("ok"):
        result["reason"] = str(consumed.get("reason") or "could_not_consume_yop")
        return result

    mark = getattr(game, "_mark_dcard_played_this_turn", None)
    if callable(mark):
        try:
            mark(CARD_TYPE, player)
        except TypeError:
            try:
                mark(CARD_TYPE)
            except Exception:
                pass
        except Exception:
            pass
    else:
        try:
            td = getattr(game, "myturn", None) or getattr(game, "turn_details", None)
            if td is not None:
                td.dcard_played_in_turn_TF = True
                try:
                    td.dcard_played_in_turn_player_id = _safe_player_id(player)
                except Exception:
                    pass
        except Exception:
            pass

    indices = plan.get("resource_indices")
    if not (isinstance(indices, (list, tuple)) and len(indices) >= 2):
        plan = attach_resource_pair(game, player, plan, features=plan.get("features") or {})
        indices = plan.get("resource_indices")
    try:
        a, b = int(indices[0]), int(indices[1])
    except Exception:
        a, b = 1, 1
    if not (0 <= a < 5 and 0 <= b < 5):
        a, b = 1, 1

    add_res = _add_yop_resources(game, player, a, b)
    if not add_res.get("ok"):
        result["reason"] = str(add_res.get("reason") or "add_failed")
        result["resource_indices"] = [a, b]
        return result

    pick_text = (
        f"{RESOURCE_ORDER[a]} + {RESOURCE_ORDER[b]}"
        if a != b
        else f"2× {RESOURCE_ORDER[a]}"
    )
    message = f"AI plays Year of Plenty → {pick_text}"
    try:
        emit = getattr(game, "emit_twitter_event", None)
        if callable(emit):
            emit(_safe_player_id(player), message)
    except Exception:
        pass
    try:
        rec = getattr(game, "record_turn_event", None)
        if callable(rec):
            rec(
                player=player,
                event_type="play_dcard",
                source="ai_play_yop",
                message=message,
                metadata={
                    "card": CARD_TYPE,
                    "resource_indices": [a, b],
                    "resource_names": [RESOURCE_ORDER[a], RESOURCE_ORDER[b]],
                    "target_action": plan.get("target_action"),
                    "plan_reason": plan.get("reason"),
                },
            )
    except Exception:
        pass
    try:
        delta_fn = getattr(game, "record_turn_delta", None)
        if callable(delta_fn):
            delta = {}
            for idx, name in ((a, RESOURCE_ORDER[a]), (b, RESOURCE_ORDER[b])):
                delta[name] = int(delta.get(name, 0) or 0) + 1
            delta_fn(
                player,
                "dcard",
                resource_delta=delta,
                event_type="play_dcard",
                source="ai_play_yop",
                reason="year_of_plenty",
                message=message,
                metadata={"card": CARD_TYPE, "resource_indices": [a, b]},
            )
    except Exception:
        pass

    # Continue re-scan so city/settle unlocked by new cards can follow
    slice_d = None
    cont = getattr(game, "continue_action_selection_after_action", None)
    if callable(cont):
        try:
            slice_d = cont(
                "after_ai_play_yop",
                player=player,
                action_result={
                    "action": "Play Year of Plenty",
                    "ok": True,
                    "resource_indices": [a, b],
                    "target_action": plan.get("target_action"),
                },
                clear_forced_locks=True,
            )
        except Exception as exc:
            slice_d = {"ok": False, "reason": str(exc)}
    else:
        try:
            ref = getattr(game, "refresh_strategy_after_event", None)
            if callable(ref):
                ref("after_ai_play_yop", kind="hand")
            else:
                ref2 = getattr(game, "refresh_strategy_context", None)
                if callable(ref2):
                    ref2("after_ai_play_yop", mode="auto")
        except Exception:
            pass
        try:
            refa = getattr(game, "refresh_viable_actions", None)
            if callable(refa):
                refa("after_ai_play_yop")
        except Exception:
            pass
        try:
            game.state = "ActionSelection"
        except Exception:
            pass
        slice_d = {"ok": True, "reason": "after_ai_play_yop_fallback", "state": "ActionSelection"}

    try:
        refresh = getattr(game, "_refresh_gui_scoreboard_after_dcard_change", None)
        if callable(refresh):
            refresh("after_ai_play_yop")
    except Exception:
        pass

    result.update(
        {
            "ok": True,
            "executed": True,
            "reason": str(plan.get("reason") or "executed"),
            "timing": "post_roll",
            "resource_indices": [a, b],
            "resource_names": [RESOURCE_ORDER[a], RESOURCE_ORDER[b]],
            "gain_vector": add_res.get("gain_vector"),
            "target_action": plan.get("target_action"),
            "slice_d": slice_d,
            "state_after": str(getattr(game, "state", "") or ""),
            "message": message,
        }
    )

    try:
        game.last_ai_yop_execute_result = result
    except Exception:
        pass
    try:
        plan["executed"] = True
        plan["execute_result"] = {
            "ok": True,
            "resource_indices": [a, b],
            "resource_names": [RESOURCE_ORDER[a], RESOURCE_ORDER[b]],
        }
        game.last_ai_yop_plan = plan
    except Exception:
        pass

    try:
        if bool(getattr(game, "execution_debug_print_tf", False)):
            print(
                "AI YOP EXECUTE "
                f"[P{result.get('player_id')}] {message} "
                f"target={plan.get('target_action')} state={result.get('state_after')}"
            )
    except Exception:
        pass

    return result


def maybe_execute_ai_yop_for_window(
    game: Any,
    window: str = "post_roll",
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan for window; if play+post_roll, execute thin and return result."""
    plan = plan_ai_play_yop(
        game,
        window=window,
        log=True,
        features_override=features_override,
    )
    out: Dict[str, Any] = {
        "planned": plan,
        "executed": False,
        "executed_result": None,
    }
    if str(window) != "post_roll":
        return out
    if not bool(plan.get("play")):
        return out
    if str(plan.get("timing") or "") != "post_roll":
        return out
    executed = execute_ai_play_yop(game, plan=plan, window=window)
    out["executed"] = bool(executed.get("executed"))
    out["executed_result"] = executed
    return out


__all__ = [
    "STAGE",
    "CARD_TYPE",
    "RESOURCE_ORDER",
    "REASON_SKELETON_HOLD",
    "REASON_C_CRIT",
    "REASON_HOLD_EARLY",
    "REASON_HOLD_ALT_DCARD",
    "REASON_HOLD_BANK_COVERS",
    "REASON_HOLD_DCARD_BUY",
    "REASON_YOP_PRE_ROLL",
    "REASON_NO_YOP",

    "playable_yop_count",
    "hand_vector5",
    "need_vector",
    "pick_two_from_need",
    "evaluate_complete_now_targets",
    "evaluate_ai_yop_gates",
    "collect_yop_features",
    "decide_mvp_play_hold",
    "attach_resource_pair",
    "plan_ai_play_yop",
    "log_ai_yop_plan",
    "execute_ai_play_yop",
    "maybe_execute_ai_yop_for_window",
]
