"""Shared Phase-A DCard timing helpers (virtual VP, bank residual shortfall).

Used by YOP / Monopoly / Knight / TFR / chooser for consistent play-when math.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Resource order: Wheat, Ore, Wood, Brick, Sheep
DEFAULT_TRADE_RATES = [4, 4, 4, 4, 4]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_player_id(player: Any) -> Optional[int]:
    try:
        return int(getattr(player, "id", 0) or 0)
    except Exception:
        return None


def victory_points(player: Any) -> int:
    """Best available VP total for AI timing.

    W4: take the max of stored ``victory_points``/``points`` and
    ``effective_vp`` (board + specials + VP DCards). Unit-test stubs often set
    the field without full settlement lists; live players may lag the field
    after a mutation until recalculate runs.
    """
    stored = None
    for attr in ("victory_points", "points"):
        try:
            raw = getattr(player, attr, None)
            if raw is not None:
                stored = int(raw)
                break
        except Exception:
            pass
    eff = None
    try:
        from core.victory import effective_vp

        eff = int(effective_vp(player))
    except Exception:
        eff = None
    if stored is not None and eff is not None:
        return max(stored, eff)
    if stored is not None:
        return stored
    return int(eff or 0)


def unplayed_dcard_count(player: Any) -> int:
    """Count development cards still in hand (not yet played)."""
    if player is None:
        return 0
    try:
        n = int(getattr(player, "number_of_dcards", None) or 0)
        if n > 0:
            return n
    except Exception:
        pass
    try:
        cards = list(getattr(player, "development_cards", []) or [])
        if cards:
            return len(cards)
    except Exception:
        pass
    # Sum playable counts from dcard_summary rows [type, ?, not_played, played]
    total = 0
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            row_list = list(row or [])
            while len(row_list) < 4:
                row_list.append(0)
            # Skip pure VP rows if marked victory_point — still count as hidden strength
            total += max(0, int(row_list[2] or 0))
    except Exception:
        pass
    return max(0, total)


def virtual_vp(player: Any) -> int:
    """Mark Oxley-style virtual strength: VP + unplayed DCards."""
    return victory_points(player) + unplayed_dcard_count(player)


def virtual_vp_table(game: Any) -> List[Tuple[Any, int]]:
    """Return [(player, virtual_vp), ...] for all non-None players."""
    out: List[Tuple[Any, int]] = []
    for p in list(getattr(game, "players", []) or []):
        if p is None:
            continue
        out.append((p, virtual_vp(p)))
    return out


def find_strongest_opponents(
    game: Any,
    player: Any,
) -> List[Any]:
    """Opponents with max virtual VP (ties kept; self excluded from return).

    If the acting player is sole leader, returns the next-tier opponents.
    If co-leader, returns the other co-leaders.
    If not leader, returns the current leader set.
    """
    table = virtual_vp_table(game)
    if not table:
        return []
    pid = _safe_player_id(player)
    scores = [(p, v) for p, v in table]
    max_v = max(v for _, v in scores)
    leaders = [p for p, v in scores if v == max_v]
    leader_ids = {_safe_player_id(p) for p in leaders}

    if pid in leader_ids and len(leaders) == 1:
        # Sole leader → strongest opponents = next tier
        rest = [(p, v) for p, v in scores if _safe_player_id(p) != pid]
        if not rest:
            return []
        next_max = max(v for _, v in rest)
        return [p for p, v in rest if v == next_max]
    if pid in leader_ids:
        return [p for p in leaders if _safe_player_id(p) != pid]
    return list(leaders)


def trade_rates_vector5(game: Any, player: Any) -> List[int]:
    """Player bank/port rates [W,O,Wd,B,S]; default 4:1."""
    # Explicit trade_rates on player
    rates = getattr(player, "trade_rates", None)
    if isinstance(rates, (list, tuple)) and len(rates) >= 5:
        return [max(1, _safe_int(rates[i], 4)) for i in range(5)]
    if isinstance(rates, Mapping):
        order = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
        aliases = {
            "Wheat": ("Wheat", "wheat", "grain"),
            "Ore": ("Ore", "ore"),
            "Wood": ("Wood", "wood", "lumber"),
            "Brick": ("Brick", "brick", "clay"),
            "Sheep": ("Sheep", "sheep", "wool"),
        }
        out: List[int] = []
        for name in order:
            val = None
            for key in aliases[name]:
                if key in rates:
                    val = rates[key]
                    break
            out.append(max(1, _safe_int(val, 4)))
        if len(out) == 5:
            return out

    # resource_time_estimator when board present
    try:
        from core.resource_time_estimator import get_player_trade_rates

        board = getattr(game, "board", None)
        if board is not None and player is not None:
            got = get_player_trade_rates(board, player)
            if isinstance(got, (list, tuple)) and len(got) >= 5:
                return [max(1, _safe_int(got[i], 4)) for i in range(5)]
    except Exception:
        pass
    return list(DEFAULT_TRADE_RATES)


def need_vector5(hand: Sequence[int], cost: Sequence[int]) -> List[int]:
    h = list(hand[:5]) + [0] * 5
    c = list(cost[:5]) + [0] * 5
    return [max(0, _safe_int(c[i]) - _safe_int(h[i])) for i in range(5)]


def bank_residual_after_trades(
    hand: Sequence[int],
    cost: Sequence[int],
    trade_rates: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """v045-style residual shortfall after banking surplus at trade rates.

    total_short = sum(max(0, cost - hand))
    surplus bank trades = sum floor(surplus_i / rate_i)
    residual = max(0, total_short - bank_trades)

    residual is how many resources a DCard (YOP) still needs after legal TwB.
    """
    h = [_safe_int(x) for x in list(hand[:5])]
    while len(h) < 5:
        h.append(0)
    c = [_safe_int(x) for x in list(cost[:5])]
    while len(c) < 5:
        c.append(0)
    rates = [max(1, _safe_int(x, 4)) for x in list(trade_rates or DEFAULT_TRADE_RATES)[:5]]
    while len(rates) < 5:
        rates.append(4)

    need = [max(0, c[i] - h[i]) for i in range(5)]
    surplus = [max(0, h[i] - c[i]) for i in range(5)]
    trades = [surplus[i] // rates[i] for i in range(5)]
    total_short = sum(need)
    total_trades = sum(trades)
    residual = max(0, total_short - total_trades)

    return {
        "hand": h,
        "cost": c,
        "need": need,
        "surplus": surplus,
        "trade_rates": rates,
        "bank_trades": trades,
        "total_short": int(total_short),
        "total_bank_trades": int(total_trades),
        "residual_shortfall": int(residual),
        "bank_covers": residual <= 0 and total_short > 0,
        "already_affordable": total_short <= 0,
    }


def bank_residual_shortfall(
    hand: Sequence[int],
    cost: Sequence[int],
    trade_rates: Optional[Sequence[int]] = None,
) -> int:
    """Residual cards still needed after bank trades (0 if bank covers or affordable)."""
    return int(bank_residual_after_trades(hand, cost, trade_rates)["residual_shortfall"])


def resource_shape_hint(
    hand: Sequence[int],
    *,
    prefer_settle: bool = False,
    prefer_city: bool = False,
    prefer_road: bool = False,
    prefer_dcard: bool = False,
    trade_rates: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Shape of residual need for chooser TFR vs YOP bias.

    wood_brick_shape: residual is only (or mostly) Wood+Brick after bank.
    multi_type_yop: residual 1–2 across mixed types.
    """
    costs: Dict[str, List[int]] = {
        "settle": [1, 0, 1, 1, 1],
        "city": [2, 3, 0, 0, 0],
        "road": [0, 0, 1, 1, 0],
        "dcard": [1, 1, 0, 0, 1],
    }
    order = []
    if prefer_city:
        order.append("city")
    if prefer_settle:
        order.append("settle")
    if prefer_road:
        order.append("road")
    if prefer_dcard:
        order.append("dcard")
    if not order:
        order = ["settle", "city", "road", "dcard"]

    best = None
    for name in order:
        info = bank_residual_after_trades(hand, costs[name], trade_rates)
        if info["already_affordable"]:
            continue
        if best is None or info["residual_shortfall"] < best["residual_shortfall"]:
            best = {**info, "action": name}

    if best is None:
        return {
            "action": None,
            "residual_shortfall": 0,
            "wood_brick_shape": False,
            "multi_type_yop": False,
            "need": [0, 0, 0, 0, 0],
        }

    need = list(best["need"])
    res = int(best["residual_shortfall"])
    wb = need[2] + need[3]
    other = need[0] + need[1] + need[4]
    wood_brick = res > 0 and wb > 0 and other == 0
    # Also wood/brick dominant residual (allow tiny other if bank covered other)
    if not wood_brick and res > 0 and wb >= res and other == 0:
        wood_brick = True
    multi = 1 <= res <= 2 and not wood_brick

    return {
        "action": best.get("action"),
        "residual_shortfall": res,
        "wood_brick_shape": bool(wood_brick),
        "multi_type_yop": bool(multi),
        "need": need,
        "total_short": best.get("total_short"),
        "total_bank_trades": best.get("total_bank_trades"),
    }


def leader_resource_hoard(
    game: Any,
    player: Any,
    resource_index: int,
    *,
    hand_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """How much of resource_index the strongest (virtual VP) opponents hold."""
    strongest = find_strongest_opponents(game, player)
    r = max(0, min(4, int(resource_index)))
    max_hold = 0
    total_hold = 0
    details: List[Dict[str, Any]] = []

    def _hand(p: Any) -> List[int]:
        if hand_fn is not None:
            try:
                return list(hand_fn(p))[:5]
            except Exception:
                pass
        # Minimal fallback: try rcards mapping
        out = [0, 0, 0, 0, 0]
        rcards = getattr(p, "rcards", None)
        if isinstance(rcards, Mapping):
            keys = (
                ("Wheat", "wheat", "grain"),
                ("Ore", "ore"),
                ("Wood", "wood", "lumber"),
                ("Brick", "brick", "clay"),
                ("Sheep", "sheep", "wool"),
            )
            for i, aliases in enumerate(keys):
                for k, v in rcards.items():
                    text = str(getattr(k, "value", k)).lower()
                    if text in {a.lower() for a in aliases}:
                        out[i] += _safe_int(v)
                        break
        return out

    for opp in strongest:
        hv = _hand(opp)
        while len(hv) < 5:
            hv.append(0)
        n = _safe_int(hv[r])
        max_hold = max(max_hold, n)
        total_hold += n
        details.append(
            {
                "player_id": _safe_player_id(opp),
                "virtual_vp": virtual_vp(opp),
                "count": n,
            }
        )

    return {
        "resource_index": r,
        "strongest_count": len(strongest),
        "max_leader_hold": int(max_hold),
        "total_leader_hold": int(total_hold),
        "details": details,
    }


def has_port_rate_for_resource(
    trade_rates: Sequence[int],
    resource_index: int,
    *,
    max_rate: int = 2,
) -> bool:
    """True if player has a 2:1 (or better) port on that resource index."""
    r = max(0, min(4, int(resource_index)))
    rates = list(trade_rates[:5]) + [4] * 5
    return max(1, _safe_int(rates[r], 4)) <= max_rate


# Phase B: same-turn VP / swing detection + leader denial needs
COST_CITY = [2, 3, 0, 0, 0]
COST_SETTLE = [1, 0, 1, 1, 1]
COST_ROAD = [0, 0, 1, 1, 0]
COST_DCARD = [1, 1, 0, 0, 1]

SAME_TURN_VP_REASONS = frozenset(
    {
        "c_crit",
        "m_crit",
        "m_crit_early_race",
        "s_crit",
        "lr_crit",
        "la_crit",
        "strip_absolute_jackpot",
        "strip_leader_hoard",
    }
)
SAME_TURN_SWING_REASONS = frozenset(
    {
        "deny_leader",
        "la_race",
        "early_path",
        "strip_jackpot",
        "meta_self_blocked_promote_pre_roll",
        "unblock_self",
    }
)


def same_turn_convert_info(
    card: str,
    plan: Mapping[str, Any],
    *,
    vp_ai: int = 0,
    victory_threshold: Optional[int] = None,
) -> Dict[str, Any]:
    """Whether playing this DCard likely yields a same-turn VP or decisive swing.

    Community heuristic: Mono/YOP/TFR should usually convert into ≥1 VP (or
    deny/win-now); soft non-converting plays should lose to HOLD late.

    W4: ``win_now`` when ``effective_vp + estimated_delta ≥ victory_threshold``
    (default 10 / constants.VICTORY).
    """
    try:
        from core.constants import VICTORY as _VICTORY
    except Exception:
        _VICTORY = 10
    thr = max(1, int(victory_threshold if victory_threshold is not None else _VICTORY))

    reason = str(plan.get("reason") or "").strip().lower()
    features = plan.get("features") if isinstance(plan.get("features"), Mapping) else {}
    target = str(
        plan.get("target_action")
        or features.get("target_action")
        or features.get("m_crit_action")
        or ""
    ).lower()

    converts_vp = reason in SAME_TURN_VP_REASONS
    swing = reason in SAME_TURN_SWING_REASONS
    if "city" in target or "settle" in target:
        converts_vp = True
    if reason in {"lr_crit", "la_crit"}:
        converts_vp = True

    # Estimated VP from this play (rough)
    delta = 0
    if reason in {"la_crit", "lr_crit"}:
        delta = 2
    elif converts_vp and ("city" in target):
        delta = 1  # upgrade net +1
    elif converts_vp and ("settle" in target or reason in {"c_crit", "m_crit", "s_crit"}):
        delta = 1
    elif reason in {"strip_absolute_jackpot", "strip_leader_hoard", "strip_jackpot"}:
        delta = 0  # economic; may enable VP next
        swing = True

    projected = int(vp_ai) + max(int(delta), 1 if converts_vp else 0)
    win_now = bool(converts_vp and projected >= thr)
    if reason == "la_crit" and int(vp_ai) + 2 >= thr:
        win_now = True
        delta = max(delta, 2)
    if reason == "lr_crit" and int(vp_ai) + 2 >= thr:
        win_now = True
        delta = max(delta, 2)
    # Explicit plan flag from card planners
    if bool(plan.get("win_now") or features.get("win_now")):
        win_now = True

    return {
        "converts_vp": bool(converts_vp),
        "swing": bool(swing or converts_vp),
        "win_now": bool(win_now),
        "vp_delta_est": int(delta),
        "projected_vp": int(vp_ai) + int(delta),
        "threshold": thr,
        "target": target,
        "reason": reason,
        "card": str(card),
    }


def leader_denial_resource_boost(
    game: Any,
    player: Any,
    *,
    hand_fn: Optional[Any] = None,
) -> List[float]:
    """Boost resources strongest opponents need for their next build (denial Mono).

    For each strongest virtual-VP opponent, find actions they are 1–3 cards short
    of and boost those resource indices.
    """
    boost = [0.0] * 5
    strongest = find_strongest_opponents(game, player)
    if not strongest:
        # Fall back to all opponents if leader set empty
        pid = _safe_player_id(player)
        strongest = [
            p
            for p in list(getattr(game, "players", []) or [])
            if p is not None and _safe_player_id(p) != pid
        ]

    def _hand(p: Any) -> List[int]:
        if hand_fn is not None:
            try:
                hv = list(hand_fn(p))[:5]
                while len(hv) < 5:
                    hv.append(0)
                return [max(0, _safe_int(x)) for x in hv]
            except Exception:
                pass
        return [0, 0, 0, 0, 0]

    goals = (
        ("city", COST_CITY, 3.5),
        ("settle", COST_SETTLE, 3.0),
        ("dcard", COST_DCARD, 1.5),
        ("road", COST_ROAD, 1.2),
    )
    for opp in strongest:
        hv = _hand(opp)
        vvp = virtual_vp(opp)
        weight = 1.0 + 0.08 * vvp
        for _name, cost, w in goals:
            need = need_vector5(hv, cost)
            short = sum(need)
            if short <= 0 or short > 3:
                continue
            # Closer = higher denial value
            closeness = 4.0 - float(short)
            for r in range(5):
                if need[r] > 0:
                    boost[r] += weight * w * closeness * float(need[r])
    return boost


# End-game pre-roll knight: hold if another DCard can win post-roll this turn
END_GAME_VP_MIN = 7  # self or max opp at/above → consider end game


def is_end_game_vp(*, vp_ai: int = 0, max_opp_vp: int = 0) -> bool:
    return max(int(vp_ai or 0), int(max_opp_vp or 0)) >= END_GAME_VP_MIN


def scan_winning_post_roll_dcards(
    game: Any,
    player: Any,
    *,
    exclude_knight: bool = True,
) -> Dict[str, Any]:
    """Hypothetically score non-pre-roll DCards as if post-roll (ignore dice gate).

    Returns whether any *other* DCard would likely win this turn (same-turn
    convert to 10 VP / win_now). Used to HOLD pre-roll Knight and save the
    one-DCard-per-turn slot.
    """
    vp_ai = victory_points(player)
    max_opp = 0
    pid = _safe_player_id(player)
    for opp in list(getattr(game, "players", []) or []):
        if opp is None or _safe_player_id(opp) == pid:
            continue
        max_opp = max(max_opp, victory_points(opp), virtual_vp(opp) - 1)

    winners: List[Dict[str, Any]] = []

    def _consider(card: str, decision: Mapping[str, Any], features: Mapping[str, Any]) -> None:
        if not bool(decision.get("play")):
            return
        plan_like = {
            "reason": decision.get("reason"),
            "score": decision.get("score"),
            "features": features,
            "target_action": features.get("target_action")
            or features.get("m_crit_action")
            or decision.get("target_action"),
        }
        info = same_turn_convert_info(card, plan_like, vp_ai=vp_ai)
        win = bool(info.get("win_now"))
        # Also treat converts_vp with projected total ≥ 10
        if not win and bool(info.get("converts_vp")):
            if vp_ai + max(int(info.get("vp_delta_est") or 0), 1) >= 10:
                win = True
        if win:
            winners.append(
                {
                    "card": card,
                    "reason": str(decision.get("reason") or ""),
                    "score": float(decision.get("score") or 0),
                    "convert": info,
                    "target_action": plan_like.get("target_action"),
                }
            )

    # Year of Plenty
    try:
        from core.ai_play_yop import (
            collect_yop_features,
            decide_mvp_play_hold as decide_yop,
            playable_yop_count,
        )

        if playable_yop_count(player) > 0:
            feat = collect_yop_features(game, player)
            dec = decide_yop(feat, "post_roll")
            _consider("year_of_plenty", dec, feat)
    except Exception:
        pass

    # Monopoly
    try:
        from core.ai_play_monopoly import (
            collect_monopoly_features,
            decide_mvp_play_hold as decide_mono,
            playable_monopoly_count,
        )

        if playable_monopoly_count(player) > 0:
            feat = collect_monopoly_features(game, player)
            dec = decide_mono(feat, "post_roll")
            _consider("monopoly", dec, feat)
    except Exception:
        pass

    # Two free roads
    try:
        from core.ai_play_tfr import (
            collect_tfr_features,
            decide_mvp_play_hold as decide_tfr,
            playable_tfr_count,
        )

        if playable_tfr_count(player) > 0:
            feat = collect_tfr_features(game, player)
            dec = decide_tfr(feat, "post_roll")
            _consider("two_free_roads", dec, feat)
    except Exception:
        pass

    # Optional: post-roll knight as alternate win (LA) — not "other" for exclude
    if not exclude_knight:
        try:
            from core.ai_play_knight import (
                collect_knight_features,
                decide_mvp_play_hold as decide_k,
                playable_knight_count,
            )

            if playable_knight_count(player) > 0:
                feat = collect_knight_features(game, player)
                dec = decide_k(feat, "post_roll")
                _consider("knight", dec, feat)
        except Exception:
            pass

    winners.sort(
        key=lambda w: (
            1 if bool((w.get("convert") or {}).get("win_now")) else 0,
            float(w.get("score") or 0),
        ),
        reverse=True,
    )
    return {
        "has_winner": bool(winners),
        "winners": winners,
        "best": winners[0] if winners else None,
        "vp_ai": vp_ai,
        "max_opp_vp": max_opp,
        "end_game": is_end_game_vp(vp_ai=vp_ai, max_opp_vp=max_opp),
    }


def should_hold_preroll_knight_for_winning_dcard(
    game: Any,
    player: Any,
    *,
    features: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """True when end-game pre-roll Knight should yield the DCard slot to a post-roll win card."""
    feat = dict(features or {})
    vp_ai = _safe_int(feat.get("vp_ai"), victory_points(player))
    max_opp = _safe_int(feat.get("max_opp_vp"), 0)
    if max_opp <= 0:
        pid = _safe_player_id(player)
        for opp in list(getattr(game, "players", []) or []):
            if opp is None or _safe_player_id(opp) == pid:
                continue
            max_opp = max(max_opp, victory_points(opp))
    if not is_end_game_vp(vp_ai=vp_ai, max_opp_vp=max_opp):
        return {
            "hold": False,
            "reason": "not_end_game",
            "scan": None,
        }
    scan = scan_winning_post_roll_dcards(game, player, exclude_knight=True)
    if bool(scan.get("has_winner")):
        best = scan.get("best") or {}
        return {
            "hold": True,
            "reason": "hold_for_winning_post_roll_dcard",
            "winning_card": best.get("card"),
            "winning_reason": best.get("reason"),
            "scan": scan,
        }
    return {
        "hold": False,
        "reason": "no_post_roll_winner",
        "scan": scan,
    }


def scarcest_resource_indices(
    production_pips: Optional[Sequence[float]] = None,
    *,
    bank_occupied: Optional[Sequence[int]] = None,
    exclude: Optional[Sequence[int]] = None,
    n: int = 2,
) -> List[int]:
    """Return up to n resource indices ordered by scarcest production (low pips first).

    Ties broken by bank scarcity (lower bank_occupied = scarcer) then fixed order.
    """
    pips = [float(x or 0) for x in list(production_pips or [1, 1, 1, 1, 1])[:5]]
    while len(pips) < 5:
        pips.append(1.0)
    bank = [int(x or 0) for x in list(bank_occupied or [0, 0, 0, 0, 0])[:5]]
    while len(bank) < 5:
        bank.append(0)
    excluded = set(int(x) for x in (exclude or []) if 0 <= int(x) < 5)
    order = sorted(
        [i for i in range(5) if i not in excluded],
        key=lambda i: (pips[i], bank[i], i),
    )
    return order[: max(0, int(n))]


__all__ = [
    "DEFAULT_TRADE_RATES",
    "victory_points",
    "unplayed_dcard_count",
    "virtual_vp",
    "virtual_vp_table",
    "find_strongest_opponents",
    "trade_rates_vector5",
    "need_vector5",
    "bank_residual_after_trades",
    "bank_residual_shortfall",
    "resource_shape_hint",
    "leader_resource_hoard",
    "has_port_rate_for_resource",
    "same_turn_convert_info",
    "leader_denial_resource_boost",
    "scarcest_resource_indices",
    "SAME_TURN_VP_REASONS",
    "SAME_TURN_SWING_REASONS",
    "END_GAME_VP_MIN",
    "is_end_game_vp",
    "scan_winning_post_roll_dcards",
    "should_hold_preroll_knight_for_winning_dcard",
]
