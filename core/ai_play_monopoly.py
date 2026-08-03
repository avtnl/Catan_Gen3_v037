"""AI Play Monopoly — gates, MVP play/hold, resource choice, thin execute.

Runtime pipeline:
  1. Gate legality
  2. MVP play/hold (strip / phase / M-Crit)
  3. Attach resource index (0..4)
  4. Thin execute + Continue re-scan so buy/build can follow
  5. Log reason codes

API:

  plan_ai_play_monopoly(game) -> {play, timing, reason, resource_index, ...}
  execute_ai_play_monopoly(game, plan=...) -> {ok, resource_index, total_taken, slice_d, ...}

Monopoly is **post-roll only**. Execute strips one resource type from all
opponents (same rules as human Monopoly), then re-scans for Continue.
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
REASON_NO_MONOPOLY = "no_playable_monopoly"
REASON_WRONG_STATE = "monopoly_not_legal_in_state"
REASON_DISCARD_PENDING = "discard_pending"
REASON_KNIGHT_PENDING = "knight_play_already_pending"
REASON_TFR_PENDING = "tfr_play_already_pending"
REASON_MONOPOLY_PRE_ROLL = "monopoly_requires_dice_already_rolled"

# ── Reason codes (MVP play / hold) ──────────────────────────────────────────
REASON_M_CRIT = "m_crit"
REASON_STRIP_JACKPOT = "strip_jackpot"
REASON_STRIP_ABSOLUTE = "strip_absolute_jackpot"
REASON_LEADER_HOARD = "strip_leader_hoard"
REASON_STRIP_SOLID = "strip_solid"
REASON_HOLD_EARLY = "hold_early"
REASON_HOLD_THIN_STRIP = "hold_thin_strip"
REASON_HOLD_ALT_DCARD = "hold_alt_dcard"
REASON_HOLD_DEFAULT = "hold_default"

CARD_TYPE = "monopoly"
RESOURCE_ORDER = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_ALIASES = (
    ("Wheat", "wheat", "grain", "WHEAT"),
    ("Ore", "ore", "ORE"),
    ("Wood", "wood", "lumber", "WOOD"),
    ("Brick", "brick", "clay", "BRICK"),
    ("Sheep", "sheep", "wool", "SHEEP"),
)

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
LATE_VP_MIN = 8
MIN_STRIP_EARLY = 3
MIN_STRIP_MID = 3
MIN_STRIP_LATE = 2
MIN_STRIP_JACKPOT = 5
# Phase A: absolute volume jackpot (v045-ish hard spike) separate from soft jackpot
MIN_STRIP_ABSOLUTE_JACKPOT = 8
# Mid strip + strongest virtual leader holds this many of R → play
LEADER_HOARD_MIN_STRIP = 4
LEADER_HOARD_MIN_ON_LEADER = 4
PORT_RATE_MAX = 2  # 2:1 port boost
ALT_DCARD_BLOCK_MIN = 6.0
CONSERVATIVE_STRIP_FACTOR = 1.0  # observed counts; lower later for fog-of-war


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


def playable_monopoly_count(player: Any) -> int:
    """How many Monopoly cards the player may legally play (core-side, no GUI)."""
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


def evaluate_ai_monopoly_gates(
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
        "has_playable_monopoly": False,
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

    mono_count = playable_monopoly_count(player) if player is not None else 0
    gates["playable_monopoly_count"] = int(mono_count)
    if mono_count > 0:
        gates["has_playable_monopoly"] = True
    else:
        reasons_failed.append(REASON_NO_MONOPOLY)

    if resolved == "pre_roll":
        state_ok = False
        if REASON_MONOPOLY_PRE_ROLL not in reasons_failed:
            reasons_failed.append(REASON_MONOPOLY_PRE_ROLL)
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
        and gates["has_playable_monopoly"]
        and gates["state_ok"]
    )

    primary_reason = reasons_failed[0] if reasons_failed else REASON_HOLD_DEFAULT
    return {
        "legal": bool(legal),
        "gates": gates,
        "failed_reasons": reasons_failed,
        "primary_gate_reason": primary_reason if not legal else None,
        "window": resolved,
        "playable_monopoly_count": int(mono_count),
        "state": state,
        "phase": phase,
    }


# ────────────────────────────────────────────────────────────────────────────
# Strip estimation + M-Crit
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


def observed_strip_by_resource(game: Any, player: Any) -> List[int]:
    """Count actual opponent holdings per resource (MVP observed strip).

    Later versions can replace with fog-of-war estimates; tests and current AI
    use real ``rcards`` when present.
    """
    strip = [0, 0, 0, 0, 0]
    pid = _safe_player_id(player)
    for opp in list(getattr(game, "players", []) or []):
        if opp is None:
            continue
        if _safe_player_id(opp) == pid:
            continue
        hv = hand_vector5(opp)
        for i in range(5):
            strip[i] += int(hv[i] or 0)
    return strip


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
        if "dcard" in raw or "development" in raw:
            return "Buy development_card"
    if bool(direction.get("biggest_army") or direction.get("largest_army")):
        return "Buy development_card"
    return ""


def evaluate_m_crit_targets(
    player: Any,
    strip: Sequence[int],
    *,
    hand: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """Actions that become completable if we gain strip of a single resource r."""
    h = list(hand) if hand is not None else hand_vector5(player)
    preferred = _preferred_action_hint(player)
    rows: List[Dict[str, Any]] = []
    for action, cost in ACTION_COSTS.items():
        need = need_vector(h, cost)
        short = sum(need)
        if short <= 0:
            continue
        # M-Crit: shortfall is only on resources we can cover with strip
        for r in range(5):
            if need[r] <= 0:
                continue
            # After strip of r only: remaining shortfall
            remain = list(need)
            gain = min(int(strip[r] or 0), remain[r])
            remain[r] -= gain
            if sum(remain) == 0 and gain > 0:
                value = float(ACTION_VALUE.get(action, 1.0))
                if preferred and action == preferred:
                    value += 3.0
                if _vp(player) >= LATE_VP_MIN and action in {"Build city", "Build settlement"}:
                    value += 4.0
                rows.append(
                    {
                        "action": action,
                        "resource_index": r,
                        "need": need,
                        "shortfall": short,
                        "strip_needed": need[r],
                        "strip_available": int(strip[r] or 0),
                        "value": value,
                        "preferred_match": bool(preferred and action == preferred),
                    }
                )
    rows.sort(key=lambda x: float(x.get("value", 0)), reverse=True)
    return rows


def score_resources_for_monopoly(
    game: Any,
    player: Any,
    strip: Sequence[int],
    *,
    hand: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """Score each resource type for Monopoly choice."""
    from core.ai_dcard_timing import (
        has_port_rate_for_resource,
        leader_denial_resource_boost,
        leader_resource_hoard,
        trade_rates_vector5,
        virtual_vp,
    )

    h = list(hand) if hand is not None else hand_vector5(player)
    mcrits = evaluate_m_crit_targets(player, strip, hand=h)
    mcrit_by_r: Dict[int, Dict[str, Any]] = {}
    for row in mcrits:
        r = int(row["resource_index"])
        if r not in mcrit_by_r or float(row["value"]) > float(mcrit_by_r[r].get("value", 0)):
            mcrit_by_r[r] = row

    # Leader denial: weight by virtual VP (Oxley) × hand share
    pid = _safe_player_id(player)
    leader_weight = [0.0] * 5
    max_opp_vp = 0
    for opp in list(getattr(game, "players", []) or []):
        if opp is None or _safe_player_id(opp) == pid:
            continue
        ovp = _vp(opp)
        max_opp_vp = max(max_opp_vp, ovp)
        vvp = virtual_vp(opp)
        hv = hand_vector5(opp)
        w = 1.0 + 0.12 * ovp + 0.08 * vvp
        for i in range(5):
            leader_weight[i] += w * float(hv[i] or 0)

    # Phase B: denial — resources leaders need for next city/settle/etc.
    denial_boost = leader_denial_resource_boost(game, player, hand_fn=hand_vector5)

    preferred = _preferred_action_hint(player)
    bottle_boost = [0.0] * 5
    if preferred == "Build city":
        bottle_boost[0] += 1.5  # wheat
        bottle_boost[1] += 2.0  # ore
    elif preferred == "Build settlement":
        for i in (0, 2, 3, 4):
            bottle_boost[i] += 1.0
    elif preferred == "Build road":
        bottle_boost[2] += 1.5
        bottle_boost[3] += 1.5

    rates = trade_rates_vector5(game, player)

    scored: List[Dict[str, Any]] = []
    for r in range(5):
        s = int(strip[r] or 0)
        cons = int(round(s * CONSERVATIVE_STRIP_FACTOR))
        mc = mcrit_by_r.get(r)
        complete_bonus = float(mc.get("value", 0)) if mc else 0.0
        hoard = leader_resource_hoard(game, player, r, hand_fn=hand_vector5)
        max_leader = int(hoard.get("max_leader_hold") or 0)
        port_boost = 0.0
        has_port = has_port_rate_for_resource(rates, r, max_rate=PORT_RATE_MAX)
        if has_port and cons >= 2:
            port_boost = 2.5 + 0.4 * cons  # convert strip via 2:1
        denial = float(denial_boost[r] or 0.0)
        # Only pay denial when strip actually hits that type
        if cons <= 0:
            denial = 0.0

        score = (
            2.0 * cons
            + complete_bonus
            + 0.25 * leader_weight[r]
            + bottle_boost[r]
            + port_boost
            + (1.5 if max_leader >= LEADER_HOARD_MIN_ON_LEADER else 0.0)
            + 0.55 * denial  # Phase B denial weight
        )
        scored.append(
            {
                "resource_index": r,
                "resource_name": RESOURCE_ORDER[r],
                "strip": s,
                "conservative_strip": cons,
                "score": round(score, 3),
                "m_crit": mc is not None,
                "m_crit_action": str(mc.get("action") or "") if mc else "",
                "m_crit_value": complete_bonus,
                "max_leader_hold": max_leader,
                "has_port_2to1": bool(has_port),
                "port_boost": round(port_boost, 3),
                "denial_boost": round(denial, 3),
            }
        )
    scored.sort(key=lambda x: (float(x["score"]), int(x["strip"])), reverse=True)
    return scored


def stub_alt_dcard_score(game: Any, player: Any) -> Dict[str, Any]:
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

    if _playable_count(player, "year_of_plenty") > 0:
        # YOP is better when strip is thin — mild base
        score = 4.0
        details["year_of_plenty"] = score
        if score > best:
            best, best_card = score, "year_of_plenty"

    return {"score": float(best), "card": best_card, "details": details}


def collect_monopoly_features(
    game: Any,
    player: Any,
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    hand = hand_vector5(player)
    strip = observed_strip_by_resource(game, player)
    scored = score_resources_for_monopoly(game, player, strip, hand=hand)
    best = scored[0] if scored else None
    alt = stub_alt_dcard_score(game, player)
    vp = _vp(player)

    max_opp_vp = 0
    pid = _safe_player_id(player)
    for opp in list(getattr(game, "players", []) or []):
        if opp is None or _safe_player_id(opp) == pid:
            continue
        max_opp_vp = max(max_opp_vp, _vp(opp))

    early = vp <= EARLY_VP_MAX
    late = vp >= LATE_VP_MIN or max_opp_vp >= LATE_VP_MIN
    if late:
        phase = "late"
        min_strip = MIN_STRIP_LATE
    elif early:
        phase = "early"
        min_strip = MIN_STRIP_EARLY
    else:
        phase = "mid"
        min_strip = MIN_STRIP_MID

    best_strip = int(best.get("conservative_strip") or 0) if best else 0
    m_crit = bool(best and best.get("m_crit"))
    jackpot = best_strip >= MIN_STRIP_JACKPOT
    absolute_jackpot = best_strip >= MIN_STRIP_ABSOLUTE_JACKPOT
    max_leader_hold = int(best.get("max_leader_hold") or 0) if best else 0
    leader_hoard = bool(
        best_strip >= LEADER_HOARD_MIN_STRIP
        and max_leader_hold >= LEADER_HOARD_MIN_ON_LEADER
    )
    has_port = bool(best and best.get("has_port_2to1"))

    features: Dict[str, Any] = {
        "hand": hand,
        "strip_by_resource": list(strip),
        "resource_scores": scored,
        "best_resource": best,
        "best_strip": best_strip,
        "m_crit": m_crit,
        "m_crit_action": str(best.get("m_crit_action") or "") if best else "",
        "jackpot": jackpot,
        "absolute_jackpot": absolute_jackpot,
        "leader_hoard": leader_hoard,
        "max_leader_hold": max_leader_hold,
        "has_port_2to1": has_port,
        "phase": phase,
        "min_strip": min_strip,
        "vp_ai": vp,
        "max_opp_vp": max_opp_vp,
        "early_game": early,
        "late_game": late,
        "alt_dcard_score": float(alt.get("score") or 0),
        "alt_dcard_card": alt.get("card"),
        "alt_dcard_details": dict(alt.get("details") or {}),
        "resource_index": int(best["resource_index"]) if best else None,
        "resource_name": str(best.get("resource_name") or "") if best else None,
        "playable_monopoly": playable_monopoly_count(player),
        "strip_mode": "observed",
    }

    if features_override:
        for k, v in dict(features_override).items():
            features[k] = v
        # Recompute derived if strip override provided
        if "strip_by_resource" in features_override and "resource_scores" not in features_override:
            strip2 = list(features.get("strip_by_resource") or [0, 0, 0, 0, 0])
            scored2 = score_resources_for_monopoly(game, player, strip2, hand=hand)
            features["resource_scores"] = scored2
            best2 = scored2[0] if scored2 else None
            features["best_resource"] = best2
            features["best_strip"] = int(best2.get("conservative_strip") or 0) if best2 else 0
            features["m_crit"] = bool(best2 and best2.get("m_crit"))
            features["m_crit_action"] = str(best2.get("m_crit_action") or "") if best2 else ""
            features["jackpot"] = features["best_strip"] >= MIN_STRIP_JACKPOT
            features["absolute_jackpot"] = features["best_strip"] >= MIN_STRIP_ABSOLUTE_JACKPOT
            features["max_leader_hold"] = int(best2.get("max_leader_hold") or 0) if best2 else 0
            features["leader_hoard"] = bool(
                features["best_strip"] >= LEADER_HOARD_MIN_STRIP
                and features["max_leader_hold"] >= LEADER_HOARD_MIN_ON_LEADER
            )
            features["has_port_2to1"] = bool(best2 and best2.get("has_port_2to1"))
            if best2 and "resource_index" not in features_override:
                features["resource_index"] = int(best2["resource_index"])
                features["resource_name"] = str(best2.get("resource_name") or "")
        if "vp_ai" in features_override and "early_game" not in features_override:
            features["early_game"] = _safe_int(features.get("vp_ai"), 0) <= EARLY_VP_MAX
            features["late_game"] = _safe_int(features.get("vp_ai"), 0) >= LATE_VP_MIN

    return features


def decide_mvp_play_hold(features: Mapping[str, Any], window: str = "post_roll") -> Dict[str, Any]:
    """MVP: M-Crit / absolute jackpot / leader-hoard / jackpot / solid strip vs holds."""
    window = str(window or "post_roll")
    best_strip = _safe_int(features.get("best_strip"), 0)
    min_strip = _safe_int(features.get("min_strip"), MIN_STRIP_MID)
    soft = 2.0 * best_strip + (8.0 if features.get("m_crit") else 0.0)
    if features.get("absolute_jackpot"):
        soft += 3.0
    if features.get("leader_hoard"):
        soft += 2.5
    if features.get("has_port_2to1"):
        soft += 1.5
    soft -= 0.4 * _safe_float(features.get("alt_dcard_score"), 0)

    decision: Dict[str, Any] = {
        "play": False,
        "timing": None,
        "reason": REASON_HOLD_DEFAULT,
        "score": soft,
        "rule": "default",
        "available_timing_if_play": "post_roll" if window == "post_roll" else None,
        "resource_index": features.get("resource_index"),
        "resource_name": features.get("resource_name"),
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
        return _hold(REASON_MONOPOLY_PRE_ROLL, "pre_roll_blocked", soft)

    # 1) M-Crit — strip completes city/settle (etc.)
    if bool(features.get("m_crit")) and best_strip >= 1:
        # Early still needs meaningful strip
        if bool(features.get("early_game")) and best_strip < MIN_STRIP_EARLY and not bool(
            features.get("late_game")
        ):
            pass  # fall through — early needs strip ≥ 3 even for M-Crit soft race
        else:
            return _play(REASON_M_CRIT, "m_crit", max(soft, 12.0))
        # Early M-Crit with strip ≥ MIN_STRIP_EARLY
        if best_strip >= MIN_STRIP_EARLY:
            return _play(REASON_M_CRIT, "m_crit_early_race", max(soft, 12.0))

    # 2) Absolute volume jackpot (Phase A)
    if bool(features.get("absolute_jackpot")) or best_strip >= MIN_STRIP_ABSOLUTE_JACKPOT:
        return _play(REASON_STRIP_ABSOLUTE, "strip_absolute_jackpot", max(soft, 12.0))

    # 3) Leader-hoard concentration (v045 >8 + strongest, softened thresholds)
    if bool(features.get("leader_hoard")) and not bool(features.get("early_game")):
        return _play(REASON_LEADER_HOARD, "strip_leader_hoard", max(soft, 9.0))

    # 4) Soft jackpot strip
    if bool(features.get("jackpot")) or best_strip >= MIN_STRIP_JACKPOT:
        return _play(REASON_STRIP_JACKPOT, "strip_jackpot", max(soft, 10.0))

    # 5) Alt DCard — only blocks non-critical / non-jackpot
    alt = _safe_float(features.get("alt_dcard_score"), 0.0)
    if alt >= ALT_DCARD_BLOCK_MIN and best_strip < MIN_STRIP_JACKPOT:
        return _hold(REASON_HOLD_ALT_DCARD, "hold_alt_dcard", soft)

    # 6) Early default hold
    if bool(features.get("early_game")) and best_strip < MIN_STRIP_EARLY:
        return _hold(REASON_HOLD_EARLY, "hold_early", soft)

    # 7) Thin strip (port soft: allow min_strip-1 when 2:1 on best R and strip ≥ 2)
    effective_min = min_strip
    if bool(features.get("has_port_2to1")) and best_strip >= 2:
        effective_min = max(2, min_strip - 1)

    if best_strip < effective_min:
        return _hold(REASON_HOLD_THIN_STRIP, "hold_thin_strip", soft)

    # 8) Solid strip for phase
    if best_strip >= effective_min:
        return _play(REASON_STRIP_SOLID, "strip_solid", soft)

    return _hold(REASON_HOLD_DEFAULT, "hold_default", soft)


def attach_resource_choice(
    game: Any,
    player: Any,
    plan: Dict[str, Any],
    *,
    features: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach chosen monopoly resource index when play is decided."""
    plan = dict(plan or {})
    if not bool(plan.get("play")):
        plan["resource_index"] = None
        plan["resource_name"] = None
        plan["resource_choice_ok"] = None
        return plan

    warnings = list(plan.get("warnings") or [])
    features = features if features is not None else (plan.get("features") or {})

    ridx = features.get("resource_index")
    source = "best_score"
    if features.get("resource_index_override") is not None:
        ridx = features.get("resource_index_override")
        source = "features_override"

    try:
        ridx = int(ridx) if ridx is not None else None
    except Exception:
        ridx = None

    if ridx is None or not (0 <= ridx < 5):
        # Fallback: max strip resource
        strip = list(features.get("strip_by_resource") or observed_strip_by_resource(game, player))
        while len(strip) < 5:
            strip.append(0)
        ridx = max(range(5), key=lambda i: int(strip[i] or 0))
        source = "max_strip_fallback"
        if int(strip[ridx] or 0) <= 0:
            warnings.append("play_without_perfect_strip")
            ridx = 1  # Ore default

    plan["resource_index"] = int(ridx)
    plan["resource_name"] = RESOURCE_ORDER[int(ridx)]
    plan["resource_choice_ok"] = source != "max_strip_fallback" or True
    plan["resource_choice_source"] = source
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
        "action": "plan_ai_play_monopoly",
        "card": CARD_TYPE,
        "stage": STAGE,
        "play": bool(play),
        "timing": timing,
        "reason": str(reason or ""),
        "legal": bool(legal),
        "window": window,
        "player_id": player_id,
        "resource_index": None,
        "resource_name": None,
        "resource_choice_ok": None,
        "gates": dict(gates or {}),
        "failed_reasons": [],
        "playable_monopoly_count": int((gates or {}).get("playable_monopoly_count") or 0),
        "score": None,
        "features": {},
        "rule": None,
        "warnings": [],
        "executed": False,
        "notes": (
            "Thin pipeline: MVP strip/phase/M-Crit, resource choice, "
            "execute strips opponents and re-scans."
        ),
    }
    if extra:
        plan.update(extra)
    return plan


def log_ai_monopoly_plan(game: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = dict(plan or {})
    window = str(plan.get("window") or "unknown")

    try:
        game.last_ai_monopoly_plan = plan
    except Exception:
        pass
    try:
        by_window = getattr(game, "last_ai_monopoly_plan_by_window", None)
        if not isinstance(by_window, dict):
            by_window = {}
        by_window[window] = plan
        game.last_ai_monopoly_plan_by_window = by_window
    except Exception:
        pass
    if window == "pre_roll":
        try:
            game.last_ai_monopoly_plan_pre_roll = plan
        except Exception:
            pass
    elif window == "post_roll":
        try:
            game.last_ai_monopoly_plan_post_roll = plan
        except Exception:
            pass

    trace_row = {
        "kind": "play_monopoly",
        "stage": plan.get("stage"),
        "window": window,
        "play": bool(plan.get("play")),
        "timing": plan.get("timing"),
        "reason": plan.get("reason"),
        "legal": bool(plan.get("legal")),
        "player_id": plan.get("player_id"),
        "playable_monopoly_count": plan.get("playable_monopoly_count"),
        "resource_index": plan.get("resource_index"),
        "resource_name": plan.get("resource_name"),
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
                "AI Monopoly plan "
                f"[P{plan.get('player_id')}] window={window} "
                f"legal={plan.get('legal')} play={plan.get('play')} "
                f"timing={plan.get('timing')} reason={plan.get('reason')} "
                f"r={plan.get('resource_name')} score={plan.get('score')}"
            )
    except Exception:
        pass

    return plan


def plan_ai_play_monopoly(
    game: Any,
    player: Any = None,
    *,
    window: Optional[str] = None,
    log: bool = True,
    features_override: Optional[Mapping[str, Any]] = None,
    skip_resource_choice: bool = False,
) -> Dict[str, Any]:
    """Plan Monopoly: gates + MVP play/hold + resource choice."""
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    player_id = _safe_player_id(player)
    gate_info = evaluate_ai_monopoly_gates(game, player, window=window)
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
                "playable_monopoly_count": int(gate_info.get("playable_monopoly_count") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
            },
        )
    else:
        features = collect_monopoly_features(
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
                "playable_monopoly_count": int(gate_info.get("playable_monopoly_count") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
                "available_timing_if_play": decision.get("available_timing_if_play"),
                "score": decision.get("score"),
                "features": features,
                "rule": decision.get("rule"),
                "resource_index": decision.get("resource_index"),
                "resource_name": decision.get("resource_name"),
            },
        )
        if bool(plan.get("play")) and not skip_resource_choice:
            plan = attach_resource_choice(game, player, plan, features=features)

    if log:
        plan = log_ai_monopoly_plan(game, plan)
    return plan


# ────────────────────────────────────────────────────────────────────────────
# Thin execute
# ────────────────────────────────────────────────────────────────────────────


def _consume_monopoly_card(game: Any, player: Any) -> Dict[str, Any]:
    remover = getattr(game, "_remove_development_card_from_player", None)
    if callable(remover):
        if remover(player, CARD_TYPE):
            return {"ok": True, "source": "game_remove"}
        try:
            idx_fn = getattr(game, "_execution_dcard_summary_index", None)
            idx = int(idx_fn(CARD_TYPE)) if callable(idx_fn) else 4
            row = player.dcard_summary[idx]
            if int(row[2] or 0) <= 0:
                return {"ok": False, "reason": REASON_NO_MONOPOLY}
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
            return {"ok": False, "reason": "could_not_consume_monopoly"}

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
    return {"ok": False, "reason": REASON_NO_MONOPOLY}


def _count_resource_in_hand(rcards: Any, ridx: int) -> Tuple[int, Any]:
    """Return (amount, key_to_clear) for resource index in a hand mapping."""
    if not isinstance(rcards, dict):
        return 0, None
    name = RESOURCE_ORDER[ridx]
    aliases = RESOURCE_ALIASES[ridx]
    amount = 0
    key_found = None
    for key, val in list(rcards.items()):
        text = str(getattr(key, "value", key)).strip()
        kname = str(getattr(key, "name", "")).strip()
        for alias in aliases:
            if text.lower() == str(alias).lower() or kname.lower() == str(alias).lower() or text == str(alias):
                try:
                    amount += int(val or 0)
                except Exception:
                    pass
                key_found = key if key_found is None else key_found
                break
    return max(0, amount), key_found if key_found is not None else name


def strip_resource_from_opponents(
    game: Any,
    player: Any,
    resource_index: int,
) -> Dict[str, Any]:
    """Move all of resource_index from each opponent to player."""
    ridx = int(resource_index)
    if not (0 <= ridx < 5):
        return {"ok": False, "reason": "resource_index_out_of_range", "total_taken": 0}

    # Prefer Game resource keys
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

    resource_key = resources[ridx]
    res_name = RESOURCE_ORDER[ridx]
    total_taken = 0
    taken_by_opponent: List[Dict[str, Any]] = []

    try:
        if not isinstance(getattr(player, "rcards", None), dict):
            player.rcards = {}
    except Exception:
        player.rcards = {}

    active_id = _safe_player_id(player)
    for opponent in list(getattr(game, "players", []) or []):
        if opponent is None:
            continue
        oid = _safe_player_id(opponent)
        if oid is not None and oid == active_id:
            continue

        rcards = getattr(opponent, "rcards", None) or {}
        if not isinstance(rcards, dict):
            continue
        amount, found_key = _count_resource_in_hand(rcards, ridx)
        if amount <= 0:
            continue

        # Zero opponent holdings for this resource (all matching keys)
        for key in list(rcards.keys()):
            text = str(getattr(key, "value", key)).strip()
            kname = str(getattr(key, "name", "")).strip()
            for alias in RESOURCE_ALIASES[ridx]:
                if text.lower() == str(alias).lower() or kname.lower() == str(alias).lower():
                    rcards[key] = 0
                    break
        try:
            opponent.rcards = rcards
            opponent.number_of_rcards = sum(hand_vector5(opponent))
        except Exception:
            pass

        # Add to active player
        player.rcards[resource_key] = int(player.rcards.get(resource_key, 0) or 0) + amount
        if resource_key != res_name:
            player.rcards[res_name] = int(player.rcards.get(res_name, 0) or 0) + amount
        total_taken += amount
        taken_by_opponent.append({"opponent_id": oid, "amount": amount})

    try:
        player.number_of_rcards = sum(hand_vector5(player))
    except Exception:
        pass

    return {
        "ok": True,
        "total_taken": int(total_taken),
        "resource_index": ridx,
        "resource_name": res_name,
        "taken_by_opponent": taken_by_opponent,
    }


def execute_ai_play_monopoly(
    game: Any,
    player: Any = None,
    *,
    plan: Optional[Mapping[str, Any]] = None,
    window: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Thin execute: consume Monopoly, strip one resource, re-scan for Continue."""
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    result: Dict[str, Any] = {
        "ok": False,
        "action": "Play Monopoly",
        "source": "ai",
        "stage": STAGE,
        "reason": "",
        "player_id": _safe_player_id(player),
        "plan": None,
        "resource_index": None,
        "resource_name": None,
        "total_taken": 0,
        "slice_d": None,
        "executed": False,
    }

    if plan is None:
        plan = plan_ai_play_monopoly(game, player, window=window or "post_roll", log=True)
    plan = dict(plan or {})
    result["plan"] = plan

    if not bool(plan.get("legal")) and not force:
        result["reason"] = str(plan.get("reason") or "not_legal")
        return result
    if not bool(plan.get("play")) and not force:
        result["reason"] = str(plan.get("reason") or "plan_hold")
        return result

    gates = evaluate_ai_monopoly_gates(game, player, window="post_roll")
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

    consumed = _consume_monopoly_card(game, player)
    if not consumed.get("ok"):
        result["reason"] = str(consumed.get("reason") or "could_not_consume_monopoly")
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

    ridx = plan.get("resource_index")
    if ridx is None:
        plan = attach_resource_choice(game, player, plan, features=plan.get("features") or {})
        ridx = plan.get("resource_index")
    try:
        ridx = int(ridx)
    except Exception:
        ridx = 1
    if not (0 <= ridx < 5):
        ridx = 1

    strip_res = strip_resource_from_opponents(game, player, ridx)
    total_taken = int(strip_res.get("total_taken") or 0)
    res_name = str(strip_res.get("resource_name") or RESOURCE_ORDER[ridx])
    message = f"AI plays Monopoly → all {res_name} ({total_taken} taken)"

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
                source="ai_play_monopoly",
                message=message,
                metadata={
                    "card": CARD_TYPE,
                    "resource_index": ridx,
                    "resource_name": res_name,
                    "total_taken": total_taken,
                    "taken_by_opponent": strip_res.get("taken_by_opponent"),
                    "plan_reason": plan.get("reason"),
                },
            )
    except Exception:
        pass

    slice_d = None
    cont = getattr(game, "continue_action_selection_after_action", None)
    if callable(cont):
        try:
            slice_d = cont(
                "after_ai_play_monopoly",
                player=player,
                action_result={
                    "action": "Play Monopoly",
                    "ok": True,
                    "resource_index": ridx,
                    "total_taken": total_taken,
                },
                clear_forced_locks=True,
            )
        except Exception as exc:
            slice_d = {"ok": False, "reason": str(exc)}
    else:
        try:
            ref = getattr(game, "refresh_strategy_after_event", None)
            if callable(ref):
                ref("after_ai_play_monopoly", kind="hand")
            else:
                ref2 = getattr(game, "refresh_strategy_context", None)
                if callable(ref2):
                    ref2("after_ai_play_monopoly", mode="auto")
        except Exception:
            pass
        try:
            refa = getattr(game, "refresh_viable_actions", None)
            if callable(refa):
                refa("after_ai_play_monopoly")
        except Exception:
            pass
        try:
            game.state = "ActionSelection"
        except Exception:
            pass
        slice_d = {"ok": True, "reason": "after_ai_play_monopoly_fallback", "state": "ActionSelection"}

    try:
        refresh = getattr(game, "_refresh_gui_scoreboard_after_dcard_change", None)
        if callable(refresh):
            refresh("after_ai_play_monopoly")
    except Exception:
        pass

    result.update(
        {
            "ok": True,
            "executed": True,
            "reason": str(plan.get("reason") or "executed"),
            "timing": "post_roll",
            "resource_index": ridx,
            "resource_name": res_name,
            "total_taken": total_taken,
            "taken_by_opponent": strip_res.get("taken_by_opponent"),
            "slice_d": slice_d,
            "state_after": str(getattr(game, "state", "") or ""),
            "message": message,
        }
    )
    if total_taken <= 0:
        result.setdefault("warnings", [])
        if isinstance(result["warnings"], list):
            result["warnings"].append("strip_took_zero")

    try:
        game.last_ai_monopoly_execute_result = result
    except Exception:
        pass
    try:
        plan["executed"] = True
        plan["execute_result"] = {
            "ok": True,
            "resource_index": ridx,
            "resource_name": res_name,
            "total_taken": total_taken,
        }
        game.last_ai_monopoly_plan = plan
    except Exception:
        pass

    try:
        if bool(getattr(game, "execution_debug_print_tf", False)):
            print(
                "AI Monopoly EXECUTE "
                f"[P{result.get('player_id')}] {message} "
                f"state={result.get('state_after')}"
            )
    except Exception:
        pass

    return result


def maybe_execute_ai_monopoly_for_window(
    game: Any,
    window: str = "post_roll",
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan for window; if play+post_roll, execute thin and return result."""
    plan = plan_ai_play_monopoly(
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
    executed = execute_ai_play_monopoly(game, plan=plan, window=window)
    out["executed"] = bool(executed.get("executed"))
    out["executed_result"] = executed
    return out


__all__ = [
    "STAGE",
    "CARD_TYPE",
    "RESOURCE_ORDER",
    "REASON_SKELETON_HOLD",
    "REASON_M_CRIT",
    "REASON_STRIP_JACKPOT",
    "REASON_STRIP_ABSOLUTE",
    "REASON_LEADER_HOARD",
    "REASON_STRIP_SOLID",
    "REASON_HOLD_EARLY",
    "REASON_HOLD_THIN_STRIP",
    "REASON_HOLD_ALT_DCARD",
    "REASON_MONOPOLY_PRE_ROLL",
    "REASON_NO_MONOPOLY",
    "MIN_STRIP_ABSOLUTE_JACKPOT",
    "LEADER_HOARD_MIN_STRIP",
    "LEADER_HOARD_MIN_ON_LEADER",
    "playable_monopoly_count",
    "hand_vector5",
    "observed_strip_by_resource",
    "evaluate_m_crit_targets",
    "score_resources_for_monopoly",
    "evaluate_ai_monopoly_gates",
    "collect_monopoly_features",
    "decide_mvp_play_hold",
    "attach_resource_choice",
    "plan_ai_play_monopoly",
    "log_ai_monopoly_plan",
    "strip_resource_from_opponents",
    "execute_ai_play_monopoly",
    "maybe_execute_ai_monopoly_for_window",
]
