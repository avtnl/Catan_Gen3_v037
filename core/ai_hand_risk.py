"""core/ai_hand_risk.py

Stage A: keep/ditch profile + policy (accept / soft_reduce / hard_reduce).
Stage B: risk TwB / risk TwP (ditch export under soft/hard policy).
Stage C: secondary helpful buy/build (spend ditch, on-strategy, non-preferred).
Stage D: seeded near-tie RNG for soft / low-stake indifference only.

T2: risk TwP is a peer of risk TwB inside the soft/hard package — ditch-only
player trades that reshape the hand or shed cards, preferred over bank when mutual.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_SHORT: Tuple[str, ...] = ("Wh", "Or", "Wd", "Br", "Sh")

# Policy thresholds (Stage A defaults — tune later)
SOFT_REDUCE_MIN_HAND: int = 10
HARD_REDUCE_MIN_HAND: int = 12
SOFT_REDUCE_KEEP_AT_RISK: int = 1
HARD_REDUCE_KEEP_AT_RISK: int = 2

# Cap soft engine need so full-way totals (e.g. 21 Wheat) do not freeze the hand
SOFT_ENGINE_KEEP_CAP_PER_RESOURCE: int = 2


def build_hand_risk_profile(game: Any, player: Any) -> Dict[str, Any]:
    """Return keep/ditch profile + policy for one player.

    keep_i  = units of resource i the AI prefers to protect if a 7 hits
    ditch_i = units it is willing to lose or dump first
    policy  = accept | soft_reduce | hard_reduce
    """
    hand = _hand_vector5(game, player)
    total = int(sum(hand))
    over_seven = max(0, total - 7)
    discard_if_seven = (total // 2) if total > 7 else 0

    pips = _production_pips_vector5(game, player)
    rates = _trade_rates_vector5(game, player)
    immediate = _immediate_need_vector5(player)
    soft_engine = _soft_engine_keep_vector5(player)
    need = [int(immediate[i] + soft_engine[i]) for i in range(5)]

    keep = [min(int(hand[i]), int(need[i])) for i in range(5)]
    ditch = [max(0, int(hand[i]) - int(keep[i])) for i in range(5)]

    protect_weight = [0.0] * 5
    surplus_weight = [0.0] * 5
    discard_score = [0.0] * 5
    for i in range(5):
        protect_weight[i] = float(keep[i]) * 3.0
        if pips[i] < 1.5 and keep[i] > 0:
            protect_weight[i] += 2.0
        if pips[i] < 1.0 and hand[i] <= 1 and keep[i] > 0:
            protect_weight[i] += 1.5
        surplus_weight[i] = float(ditch[i])
        if ditch[i] > 0 and rates[i] <= 3:
            surplus_weight[i] += 0.25

        if hand[i] <= 0:
            discard_score[i] = -999.0
            continue
        # Prefer ditch first; keep units score much lower for discard
        discard_score[i] = (
            surplus_weight[i] * 4.0
            + float(pips[i]) * 0.35
            + (0.4 if rates[i] <= 3 and ditch[i] > 0 else 0.0)
            - protect_weight[i] * 2.5
            + float(hand[i]) * 0.1
        )

    keep_at_risk, expected_loss = _simulate_discard_impact(
        hand=hand,
        keep=keep,
        discard_count=discard_if_seven,
        discard_score=discard_score,
    )
    policy = _policy_band(total=total, keep_at_risk=keep_at_risk)

    profile: Dict[str, Any] = {
        "stage": "A",
        "player_id": _safe_player_id(player),
        "total": total,
        "over_seven": over_seven,
        "discard_if_seven": discard_if_seven,
        "hand": list(hand),
        "keep": list(keep),
        "ditch": list(ditch),
        "immediate_need": list(immediate),
        "soft_engine_keep": list(soft_engine),
        "need": list(need),
        "production_pips": [float(x) for x in pips],
        "trade_rates": [int(x) for x in rates],
        "protect_weight": list(protect_weight),
        "surplus_weight": list(surplus_weight),
        "discard_score": list(discard_score),
        "keep_at_risk": int(keep_at_risk),
        "expected_loss_if_seven": list(expected_loss),
        "expected_loss_named": _named_vector(expected_loss),
        "keep_named": _named_vector(keep),
        "ditch_named": _named_vector(ditch),
        "hand_named": _named_vector(hand),
        "policy": policy,
        "policy_reason": _policy_reason(total, keep_at_risk, policy),
        "resource_order": list(RESOURCE_NAMES),
        "compact": format_hand_risk_compact(
            {
                "total": total,
                "policy": policy,
                "keep_at_risk": keep_at_risk,
                "discard_if_seven": discard_if_seven,
                "keep_named": _named_vector(keep),
                "ditch_named": _named_vector(ditch),
            }
        ),
    }
    return profile


def refresh_hand_risk_profile(game: Any, player: Any = None) -> Dict[str, Any]:
    """Compute profile and store on game + player for debug / discard reuse."""
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = None
    if player is None:
        empty = _empty_profile()
        try:
            setattr(game, "current_hand_risk_profile", empty)
        except Exception:
            pass
        return empty

    profile = build_hand_risk_profile(game, player)
    try:
        setattr(game, "current_hand_risk_profile", dict(profile))
    except Exception:
        pass
    try:
        setattr(player, "hand_risk_profile", dict(profile))
    except Exception:
        pass
    return profile


def get_hand_risk_profile(game: Any, player: Any = None) -> Dict[str, Any]:
    """Return stored profile or rebuild if missing/stale for this player."""
    stored = getattr(game, "current_hand_risk_profile", None) if game is not None else None
    if isinstance(stored, Mapping) and stored:
        if player is None:
            return dict(stored)
        pid = _safe_player_id(player)
        if stored.get("player_id") in (None, pid) or str(stored.get("player_id")) == str(pid):
            # Rebuild if hand total drifted
            hand = _hand_vector5(game, player)
            if int(sum(hand)) == int(stored.get("total", -1)):
                return dict(stored)
    if player is not None or game is not None:
        return refresh_hand_risk_profile(game, player)
    return _empty_profile()


def format_hand_risk_compact(profile: Mapping[str, Any]) -> str:
    """One-line debug: Hand 16 | policy accept | keep@risk 0 | ditch Wh5/Br2"""
    if not isinstance(profile, Mapping) or not profile:
        return "Hand: -"
    total = profile.get("total", 0)
    policy = profile.get("policy", "accept")
    risk = profile.get("keep_at_risk", 0)
    ditch_named = profile.get("ditch_named") if isinstance(profile.get("ditch_named"), Mapping) else {}
    ditch_bits = []
    for name, short in zip(RESOURCE_NAMES, RESOURCE_SHORT):
        n = int(ditch_named.get(name, 0) or 0) if ditch_named else 0
        if n > 0:
            ditch_bits.append(f"{short}{n}")
    ditch_text = "/".join(ditch_bits) if ditch_bits else "none"
    disc = profile.get("discard_if_seven", 0)
    if int(total or 0) <= 7:
        return f"Hand {total} | ok≤7 | ditch {ditch_text}"
    return f"Hand {total} | {policy} | keep@risk {risk} | if7 -{disc} | ditch {ditch_text}"


def format_hand_risk_detail_rows(profile: Mapping[str, Any], *, max_rows: int = 3) -> List[str]:
    """A few PLAN lines for Execution Debug."""
    if not isinstance(profile, Mapping) or not profile:
        return []
    rows = [format_hand_risk_compact(profile)]
    if int(profile.get("total", 0) or 0) <= 7:
        return rows[:max_rows]
    keep_named = profile.get("keep_named") if isinstance(profile.get("keep_named"), Mapping) else {}
    keep_bits = []
    for name, short in zip(RESOURCE_NAMES, RESOURCE_SHORT):
        n = int(keep_named.get(name, 0) or 0)
        if n > 0:
            keep_bits.append(f"{short}{n}")
    if keep_bits:
        rows.append("Keep: " + "/".join(keep_bits))
    reason = str(profile.get("policy_reason", "") or "")
    if reason:
        rows.append(f"Risk: {_fit(reason, 56)}")
    return rows[:max_rows]


# Soft TwB: prefer ports ≤3:1; hard may use 4:1 bank
SOFT_RISK_TWB_MAX_RATE: int = 3
HARD_RISK_TWB_MAX_RATE: int = 4

# Stage D — near-tie human touch (seeded, soft/low-stake only)
STAGE_D_ENABLED: bool = True
PACKAGE_SCORE_EPS: int = 3  # |s_score - t_score| ≤ this → may coin-flip on soft
SECONDARY_SIZE_EPS: int = 1  # secondary size_delta within this of best → band

# T5 — TwP soft partner choice (Stage D style, TwP-only)
TWP_PARTNER_SCORE_EPS: float = 0.40  # |total_score| band for partner indifference
TWP_RISK_SOFT_PASS_MAX_SCORE: int = 2  # risk TwP score ≤ this may soft-pass on soft policy
TWP_RISK_SOFT_PASS_PROB: float = 0.45  # P(skip marginal risk TwP → end/other)


def decision_rng(
    *,
    base_seed: Any = 0,
    round_n: int = 0,
    turn_n: int = 0,
    player_id: Any = 0,
    tag: str = "",
) -> random.Random:
    """Stable seeded RNG for Stage D (reproducible across runs with same seed)."""
    payload = f"{base_seed}|{int(round_n or 0)}|{int(turn_n or 0)}|{player_id}|{tag}".encode("utf-8")
    digest = hashlib.md5(payload).hexdigest()
    return random.Random(int(digest[:16], 16))


def rng_from_context(ctx: Optional[Mapping[str, Any]], *, tag: str) -> Optional[random.Random]:
    """Build RNG from game context mapping, or None if Stage D disabled / no ctx."""
    if not STAGE_D_ENABLED or not isinstance(ctx, Mapping):
        return None
    return decision_rng(
        base_seed=ctx.get("base_seed", ctx.get("game_seed", 0)),
        round_n=int(ctx.get("round", 0) or 0),
        turn_n=int(ctx.get("turn", 0) or 0),
        player_id=ctx.get("player_id", 0),
        tag=str(tag or ctx.get("tag") or "hand_risk"),
    )


def pick_near_tie_band(
    ranked: Sequence[Tuple[Any, Dict[str, Any]]],
    *,
    in_band: Callable[[Any, Any], bool],
    rng: Optional[random.Random],
    allow_rng: bool,
    decision_tag: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Pick best item, or random among near-ties when allow_rng.

    ranked: list of (rank_key, item_dict), lower/better already sorted preferred.
    in_band(best_rank, other_rank) -> True if other is in the indifference band.
    """
    meta: Dict[str, Any] = {
        "rng_used": False,
        "band_size": 0,
        "decision_tag": decision_tag,
        "stage": "D",
    }
    if not ranked:
        return None, meta
    ordered = list(ranked)
    best_rank, best_item = ordered[0]
    band_items = [best_item]
    for rank, item in ordered[1:]:
        try:
            if in_band(best_rank, rank):
                band_items.append(item)
        except Exception:
            break
    meta["band_size"] = len(band_items)
    if allow_rng and rng is not None and len(band_items) > 1:
        pick = rng.choice(band_items)
        meta["rng_used"] = True
        meta["picked_from_band"] = True
        # annotate pick
        out = dict(pick)
        out["rng_meta"] = dict(meta)
        return out, meta
    out = dict(best_item)
    out["rng_meta"] = dict(meta)
    return out, meta


def pick_twp_partner_near_tie(
    ranked: Sequence[Tuple[Any, Dict[str, Any]]],
    *,
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
    allow_rng: bool = True,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """T5: among equally good TwP deals, soft-randomize partner / identical shape.

    Rank key convention (lower better), matching Game unlock planner:
      (unlock_rank, ditch_rank, -total_score, counterparty_id, give_idx, recv_idx, size_delta)

    Rules:
    - Never mix unlock (0) with non-unlock (1) — unlock always wins cleanly.
    - Unlock band: same unlock+ditch+resource shape, score within TWP_PARTNER_SCORE_EPS,
      different counterparties may be chosen.
    - Non-unlock band: same unlock+ditch, score within ε (partner variety on soft trades).
    - Stage D off or allow_rng False → strict argmax (first after sort).
    """
    meta: Dict[str, Any] = {
        "rng_used": False,
        "band_size": 0,
        "decision_tag": "twp_partner",
        "stage": "T5",
        "t5": True,
    }
    if not ranked:
        return None, meta

    ordered = sorted(list(ranked), key=lambda item: item[0])
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="twp_partner")
    use_rng = bool(allow_rng and STAGE_D_ENABLED and active_rng is not None)

    def _in_band(best_rank: Any, other_rank: Any) -> bool:
        if not isinstance(best_rank, tuple) or not isinstance(other_rank, tuple):
            return best_rank == other_rank
        if len(best_rank) < 3 or len(other_rank) < 3:
            return best_rank == other_rank
        # Never randomize unlock away
        if int(best_rank[0]) != int(other_rank[0]):
            return False
        if int(best_rank[1]) != int(other_rank[1]):
            return False
        try:
            best_score = -float(best_rank[2])
            other_score = -float(other_rank[2])
        except Exception:
            return False
        if abs(best_score - other_score) > float(TWP_PARTNER_SCORE_EPS):
            return False
        # Unlock: require same trade shape (give/recv resources + net cards)
        if int(best_rank[0]) == 0 and len(best_rank) >= 7 and len(other_rank) >= 7:
            return (
                int(best_rank[4]) == int(other_rank[4])
                and int(best_rank[5]) == int(other_rank[5])
                and int(best_rank[6]) == int(other_rank[6])
            )
        return True

    pick, band_meta = pick_near_tie_band(
        ordered,
        in_band=_in_band,
        rng=active_rng,
        allow_rng=use_rng,
        decision_tag="twp_partner",
    )
    meta.update(band_meta)
    meta["stage"] = "T5"
    meta["t5"] = True
    if isinstance(pick, Mapping):
        out = dict(pick)
        out["rng_meta"] = dict(meta)
        return out, meta
    return pick, meta


def maybe_soft_pass_risk_twp(
    risk_twp: Optional[Mapping[str, Any]],
    *,
    policy: str = "soft_reduce",
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
) -> Tuple[Optional[Mapping[str, Any]], Dict[str, Any]]:
    """T5: on soft_reduce, sometimes skip a marginal risk TwP (pass / let other valves).

    Never applies to unlock TwP. Only when risk_trade_score is very low.
    """
    meta: Dict[str, Any] = {
        "soft_passed": False,
        "decision_tag": "twp_risk_soft_pass",
        "stage": "T5",
        "score": 0,
    }
    if not isinstance(risk_twp, Mapping):
        return None, meta
    pol = str(policy or "soft_reduce")
    score = risk_trade_score(risk_twp)
    meta["score"] = int(score)
    if pol != "soft_reduce" or not STAGE_D_ENABLED:
        return risk_twp, meta
    if score > int(TWP_RISK_SOFT_PASS_MAX_SCORE):
        return risk_twp, meta
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="twp_risk_soft_pass")
    if active_rng is None:
        return risk_twp, meta
    if active_rng.random() < float(TWP_RISK_SOFT_PASS_PROB):
        meta["soft_passed"] = True
        meta["reason"] = f"T5 soft-pass marginal risk TwP (score={score})"
        return None, meta
    return risk_twp, meta


def select_risk_twb_candidate(
    profile: Mapping[str, Any],
    twb_candidates: Sequence[Mapping[str, Any]],
    *,
    rates: Optional[Sequence[int]] = None,
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
    live_need: Optional[Sequence[int]] = None,
) -> Optional[Dict[str, Any]]:
    """Stage B: pick one TwB that exports ditch to reduce discard exposure.

    Rules:
    - Only when policy is soft_reduce or hard_reduce and hand > 7
    - Export only from ditch (never spend keep units)
    - Soft: max rate 3:1; hard: max rate 4:1
    - Prefer better rate, larger dump, get into soft/immediate need shortfall
    - Prefer trades that lower keep_at_risk or hand size
    - P0-R4: if ``live_need`` has any shortfall, **prefer** get-resources in
      that vector; if any such candidate exists, **only** those are ranked
      (no Ore dump while still missing Wd/B for the supporting action)
    - No follow-up build required (pure risk valve)

    Returns dict with give/get vectors + score metadata, or None.
    """
    if not isinstance(profile, Mapping) or not profile:
        return None
    policy = str(profile.get("policy", "accept") or "accept")
    total = int(profile.get("total", 0) or 0)
    if total <= 7:
        return None
    if policy not in {"soft_reduce", "hard_reduce"}:
        return None

    hand = [max(0, int(x or 0)) for x in list(profile.get("hand") or [])[:5]]
    while len(hand) < 5:
        hand.append(0)
    ditch = [max(0, int(x or 0)) for x in list(profile.get("ditch") or [])[:5]]
    while len(ditch) < 5:
        ditch.append(0)
    keep = [max(0, int(x or 0)) for x in list(profile.get("keep") or [])[:5]]
    while len(keep) < 5:
        keep.append(0)
    immediate = [max(0, int(x or 0)) for x in list(profile.get("immediate_need") or [])[:5]]
    while len(immediate) < 5:
        immediate.append(0)
    soft_engine = [max(0, int(x or 0)) for x in list(profile.get("soft_engine_keep") or [])[:5]]
    while len(soft_engine) < 5:
        soft_engine.append(0)

    # P0-R4: supporting-action shortfall (cost − hand), not soft-engine bulk
    need_vec = [0, 0, 0, 0, 0]
    if live_need is not None:
        for i, v in enumerate(list(live_need)[:5]):
            try:
                need_vec[i] = max(0, int(v or 0))
            except Exception:
                need_vec[i] = 0
    need_active = sum(need_vec) > 0

    max_rate = SOFT_RISK_TWB_MAX_RATE if policy == "soft_reduce" else HARD_RISK_TWB_MAX_RATE
    rates_list = [max(1, int(x or 4)) for x in list(rates or profile.get("trade_rates") or [4, 4, 4, 4, 4])[:5]]
    while len(rates_list) < 5:
        rates_list.append(4)

    # Shortfall vs keep budget: how many more of i we'd like for project
    want = [max(0, immediate[i] + soft_engine[i] - hand[i]) for i in range(5)]
    # Align "want" with live_need when provided (stronger project signal)
    if need_active:
        for i in range(5):
            want[i] = max(want[i], need_vec[i])

    ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for raw in list(twb_candidates or []):
        if not isinstance(raw, Mapping):
            continue
        give, get, rate, give_idx, get_idx = _parse_twb_candidate(raw, rates_list)
        if give_idx is None or get_idx is None or rate is None:
            continue
        if rate > max_rate:
            continue
        give_amt = int(give[give_idx] or 0)
        get_amt = int(get[get_idx] or 0)
        if give_amt <= 0 or get_amt <= 0:
            continue
        # Export only ditch
        if give_amt > ditch[give_idx]:
            continue
        if give_amt > hand[give_idx]:
            continue
        # Never export keep units of that resource
        if hand[give_idx] - give_amt < keep[give_idx]:
            continue

        after = [hand[i] - int(give[i] or 0) + int(get[i] or 0) for i in range(5)]
        if any(v < 0 for v in after):
            continue
        size_after = sum(after)
        size_delta = total - size_after  # should be rate - get_amt ≈ rate-1

        fills_live_need = bool(need_active and need_vec[get_idx] > 0)

        # Prefer get that fills project shortfall
        get_need_bonus = 0
        if fills_live_need or want[get_idx] > 0:
            get_need_bonus = 4 if fills_live_need else 3
        elif get_idx != give_idx and soft_engine[get_idx] > 0:
            get_need_bonus = 1

        # Estimate keep_at_risk after trade (reuse profile builder pieces)
        after_keep = [min(after[i], keep[i]) for i in range(5)]
        # keep budget may grow if we received needed cards
        for i in range(5):
            budget = immediate[i] + soft_engine[i]
            after_keep[i] = min(after[i], max(keep[i], min(budget, after[i])))
        after_ditch = [max(0, after[i] - after_keep[i]) for i in range(5)]
        after_discard_n = size_after // 2 if size_after > 7 else 0
        # Approximate risk: if after_ditch sum < discard_n, keep at risk
        ditch_sum = sum(after_ditch)
        after_keep_at_risk = max(0, after_discard_n - ditch_sum)
        before_risk = int(profile.get("keep_at_risk", 0) or 0)
        risk_delta = before_risk - after_keep_at_risk  # positive = better

        # Soft: require some benefit (size down or risk down or useful get)
        if policy == "soft_reduce":
            if size_delta < 1 and risk_delta <= 0 and get_need_bonus == 0:
                continue
            # Soft: avoid pure waste 4:1 already filtered by max_rate

        # Hard: allow pure size dump even with useless get
        if policy == "hard_reduce" and size_delta < 1:
            continue

        # Rank: lower tuple is better
        # - fill live_need first, then rate, size dump, risk relief, ditch
        rank = (
            0 if fills_live_need else 1,
            int(rate),
            -int(size_delta),
            -int(risk_delta),
            -int(get_need_bonus),
            -int(ditch[give_idx]),
            int(give_idx),
            int(get_idx),
        )
        ranked.append(
            (
                rank,
                {
                    "candidate": dict(raw),
                    "give": list(give),
                    "get": list(get),
                    "rate": int(rate),
                    "give_index": int(give_idx),
                    "get_index": int(get_idx),
                    "hand_before": list(hand),
                    "hand_after": list(after),
                    "size_before": int(total),
                    "size_after": int(size_after),
                    "size_delta": int(size_delta),
                    "keep_at_risk_before": before_risk,
                    "keep_at_risk_after": int(after_keep_at_risk),
                    "policy": policy,
                    "get_need_bonus": int(get_need_bonus),
                    "fills_live_need": bool(fills_live_need),
                    "mode": "risk_twb",
                    "reason": _risk_twb_reason(
                        policy, rate, give_idx, get_idx, size_delta, risk_delta, get_need_bonus
                    ),
                },
            )
        )

    if not ranked:
        return None

    # P0-R4: if any candidate fills live_need, drop pure dumps that do not
    if need_active and any(bool(item[1].get("fills_live_need")) for item in ranked):
        ranked = [item for item in ranked if bool(item[1].get("fills_live_need"))]
    ranked.sort(key=lambda item: item[0])
    policy = str(profile.get("policy", "accept") or "accept")
    # Stage D: soft — randomize among same rate/size/risk_delta/need (get may differ).
    # hard — only exact full-rank ties (deterministic argmax unless identical).
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="risk_twb")
    allow = STAGE_D_ENABLED and policy == "soft_reduce"

    def _twb_in_band(best_rank: Any, other_rank: Any) -> bool:
        if not isinstance(best_rank, tuple) or not isinstance(other_rank, tuple):
            return best_rank == other_rank
        if policy == "hard_reduce":
            return best_rank == other_rank
        # soft: first 4 components (rate, size, risk_delta, get_need)
        return best_rank[:4] == other_rank[:4]

    pick, _meta = pick_near_tie_band(
        ranked,
        in_band=_twb_in_band,
        rng=active_rng,
        allow_rng=allow,
        decision_tag="risk_twb",
    )
    return pick


def _parse_twb_candidate(
    candidate: Mapping[str, Any],
    rates: Sequence[int],
) -> Tuple[List[int], List[int], Optional[int], Optional[int], Optional[int]]:
    give = [0, 0, 0, 0, 0]
    get = [0, 0, 0, 0, 0]
    give_idx = candidate.get("give_index")
    get_idx = candidate.get("get_index")
    rate = candidate.get("rate")

    gv = candidate.get("give_vector") or candidate.get("give")
    getv = candidate.get("get_vector") or candidate.get("get")
    if isinstance(gv, Sequence) and not isinstance(gv, (str, bytes, Mapping)):
        for i, v in enumerate(list(gv)[:5]):
            try:
                give[i] = max(0, int(v or 0))
            except Exception:
                pass
    if isinstance(getv, Sequence) and not isinstance(getv, (str, bytes, Mapping)):
        for i, v in enumerate(list(getv)[:5]):
            try:
                get[i] = max(0, int(v or 0))
            except Exception:
                pass

    if give_idx is None:
        for i, v in enumerate(give):
            if v > 0:
                give_idx = i
                break
    if get_idx is None:
        for i, v in enumerate(get):
            if v > 0:
                get_idx = i
                break
    try:
        give_idx = int(give_idx) if give_idx is not None else None
        get_idx = int(get_idx) if get_idx is not None else None
    except Exception:
        return give, get, None, None, None

    if rate is None and give_idx is not None:
        rate = rates[give_idx] if give_idx < len(rates) else 4
    try:
        rate_i = int(rate or 4)
    except Exception:
        rate_i = 4

    if give_idx is not None and sum(give) == 0:
        give[give_idx] = rate_i
    if get_idx is not None and sum(get) == 0:
        get[get_idx] = 1
    if give_idx is not None and give[give_idx] <= 0:
        give[give_idx] = rate_i

    return give, get, rate_i, give_idx, get_idx


def _risk_twb_reason(
    policy: str,
    rate: int,
    give_idx: int,
    get_idx: int,
    size_delta: int,
    risk_delta: int,
    get_need_bonus: int,
) -> str:
    gname = RESOURCE_SHORT[give_idx] if 0 <= give_idx < 5 else "?"
    tname = RESOURCE_SHORT[get_idx] if 0 <= get_idx < 5 else "?"
    bits = [f"risk TwB {policy}", f"{rate}:1 {gname}→{tname}", f"size-{size_delta}"]
    if risk_delta > 0:
        bits.append(f"keep@risk-{risk_delta}")
    if get_need_bonus > 0:
        bits.append("fills need")
    return "; ".join(bits)


# ──────────────────────────────────────────────────────────────────────────────
# Stage B+ — risk TwP (T2: ditch-only mutual player trades in soft/hard package)
# ──────────────────────────────────────────────────────────────────────────────


def select_risk_twp_candidate(
    profile: Mapping[str, Any],
    twp_proposals: Sequence[Any],
    *,
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """T2 Stage B peer: pick a ditch-only TwP that improves hand risk / composition.

    Rules:
    - Only when policy is soft_reduce or hard_reduce and hand > 7
    - Export only from ditch (never spend keep units)
    - Do not grow hand (receive_count <= give_count)
    - Soft: require useful get (fills project shortfall) or net size dump
    - Hard: same, plus pure size dump (e.g. 2:1) even with neutral get
    - Prefer 1:1 mutual over multi-give; prefer need-fill; prefer risk relief

    ``twp_proposals`` may be TradeProposal objects or proposal dicts.
    """
    if not isinstance(profile, Mapping) or not profile:
        return None
    policy = str(profile.get("policy", "accept") or "accept")
    total = int(profile.get("total", 0) or 0)
    if total <= 7 or policy not in {"soft_reduce", "hard_reduce"}:
        return None

    hand = [max(0, int(x or 0)) for x in list(profile.get("hand") or [])[:5]]
    while len(hand) < 5:
        hand.append(0)
    ditch = [max(0, int(x or 0)) for x in list(profile.get("ditch") or [])[:5]]
    while len(ditch) < 5:
        ditch.append(0)
    keep = [max(0, int(x or 0)) for x in list(profile.get("keep") or [])[:5]]
    while len(keep) < 5:
        keep.append(0)
    immediate = [max(0, int(x or 0)) for x in list(profile.get("immediate_need") or [])[:5]]
    while len(immediate) < 5:
        immediate.append(0)
    soft_engine = [max(0, int(x or 0)) for x in list(profile.get("soft_engine_keep") or [])[:5]]
    while len(soft_engine) < 5:
        soft_engine.append(0)

    want = [max(0, immediate[i] + soft_engine[i] - hand[i]) for i in range(5)]
    before_risk = int(profile.get("keep_at_risk", 0) or 0)

    ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for raw in list(twp_proposals or []):
        parsed = _parse_twp_proposal(raw)
        if parsed is None:
            continue
        give_idx, give_count, receive_idx, receive_count, proposal_dict = parsed
        if give_idx == receive_idx:
            continue
        if give_count <= 0 or receive_count <= 0:
            continue
        # Risk valve must not grow the hand
        if receive_count > give_count:
            continue
        # Ditch-only export
        if give_count > ditch[give_idx]:
            continue
        if give_count > hand[give_idx]:
            continue
        if hand[give_idx] - give_count < keep[give_idx]:
            continue

        after = list(hand)
        after[give_idx] -= give_count
        after[receive_idx] += receive_count
        if any(v < 0 for v in after):
            continue
        size_after = sum(after)
        size_delta = total - size_after  # 0 for 1:1; +1 for 2:1

        get_need_bonus = 0
        if want[receive_idx] > 0:
            get_need_bonus = 3
        elif soft_engine[receive_idx] > 0 and receive_idx != give_idx:
            get_need_bonus = 1

        after_keep = [0, 0, 0, 0, 0]
        for i in range(5):
            budget = immediate[i] + soft_engine[i]
            after_keep[i] = min(after[i], max(keep[i], min(budget, after[i])))
        after_ditch = [max(0, after[i] - after_keep[i]) for i in range(5)]
        after_discard_n = size_after // 2 if size_after > 7 else 0
        after_keep_at_risk = max(0, after_discard_n - sum(after_ditch))
        risk_delta = before_risk - after_keep_at_risk

        # Soft/hard gates: need composition help or actual size dump
        if policy == "soft_reduce":
            if get_need_bonus <= 0 and size_delta < 1 and risk_delta <= 0:
                continue
        else:  # hard_reduce
            if get_need_bonus <= 0 and size_delta < 1:
                continue

        # Effective rate: 1 for 1:1, 2 for 2:1, …
        effective_rate = max(1, int(round(float(give_count) / float(max(1, receive_count)))))
        # Rank: lower is better — prefer 1:1, need fill, size dump, risk relief
        rank = (
            int(effective_rate),
            -int(get_need_bonus),
            -int(size_delta),
            -int(risk_delta),
            -float(proposal_dict.get("total_score", 0.0) or 0.0),
            int(proposal_dict.get("counterparty_id", 0) or 0),
            int(give_idx),
            int(receive_idx),
        )
        ranked.append(
            (
                rank,
                {
                    "mode": "risk_twp",
                    "proposal": dict(proposal_dict),
                    "candidate": dict(proposal_dict),
                    "give_index": int(give_idx),
                    "get_index": int(receive_idx),
                    "give_count": int(give_count),
                    "get_count": int(receive_count),
                    "give": _vector_from_swap(give_idx, give_count),
                    "get": _vector_from_swap(receive_idx, receive_count),
                    "rate": int(effective_rate),
                    "hand_before": list(hand),
                    "hand_after": list(after),
                    "size_before": int(total),
                    "size_after": int(size_after),
                    "size_delta": int(size_delta),
                    "keep_at_risk_before": before_risk,
                    "keep_at_risk_after": int(after_keep_at_risk),
                    "policy": policy,
                    "get_need_bonus": int(get_need_bonus),
                    "counterparty_id": int(proposal_dict.get("counterparty_id", 0) or 0),
                    "total_score": float(proposal_dict.get("total_score", 0.0) or 0.0),
                    "reason": _risk_twp_reason(
                        policy,
                        give_idx,
                        receive_idx,
                        give_count,
                        receive_count,
                        size_delta,
                        risk_delta,
                        get_need_bonus,
                    ),
                },
            )
        )

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="risk_twp")
    allow = STAGE_D_ENABLED and policy == "soft_reduce"

    def _twp_in_band(best_rank: Any, other_rank: Any) -> bool:
        if not isinstance(best_rank, tuple) or not isinstance(other_rank, tuple):
            return best_rank == other_rank
        if policy == "hard_reduce":
            return best_rank == other_rank
        # soft: same rate, need bonus, size, risk_delta
        return best_rank[:4] == other_rank[:4]

    pick, _meta = pick_near_tie_band(
        ranked,
        in_band=_twp_in_band,
        rng=active_rng,
        allow_rng=allow,
        decision_tag="risk_twp",
    )
    return pick


def _vector_from_swap(idx: int, count: int) -> List[int]:
    vec = [0, 0, 0, 0, 0]
    if 0 <= int(idx) < 5:
        vec[int(idx)] = max(0, int(count))
    return vec


def _parse_twp_proposal(raw: Any) -> Optional[Tuple[int, int, int, int, Dict[str, Any]]]:
    """Normalize TradeProposal / dict → (give_idx, give_n, recv_idx, recv_n, dict)."""
    if raw is None:
        return None
    if hasattr(raw, "as_dict") and callable(raw.as_dict):
        try:
            data = dict(raw.as_dict())
        except Exception:
            data = {}
        # Prefer live attributes when present
        try:
            gi = int(getattr(raw, "active_give_index"))
            gc = int(getattr(raw, "active_give_count"))
            ri = int(getattr(raw, "active_receive_index"))
            rc = int(getattr(raw, "active_receive_count"))
            data.setdefault("active_give_index", gi)
            data.setdefault("active_give_count", gc)
            data.setdefault("active_receive_index", ri)
            data.setdefault("active_receive_count", rc)
            data.setdefault("counterparty_id", int(getattr(raw, "counterparty_id", 0) or 0))
            data.setdefault("total_score", float(getattr(raw, "total_score", 0.0) or 0.0))
            data.setdefault("auto_executable", bool(getattr(raw, "auto_executable", False)))
            return gi, gc, ri, rc, data
        except Exception:
            raw = data
    if not isinstance(raw, Mapping):
        return None
    try:
        gi = int(raw.get("active_give_index"))
        gc = int(raw.get("active_give_count"))
        ri = int(raw.get("active_receive_index"))
        rc = int(raw.get("active_receive_count"))
    except Exception:
        return None
    if not (0 <= gi < 5 and 0 <= ri < 5):
        return None
    return gi, gc, ri, rc, dict(raw)


def _risk_twp_reason(
    policy: str,
    give_idx: int,
    receive_idx: int,
    give_count: int,
    receive_count: int,
    size_delta: int,
    risk_delta: int,
    get_need_bonus: int,
) -> str:
    gname = RESOURCE_SHORT[give_idx] if 0 <= give_idx < 5 else "?"
    tname = RESOURCE_SHORT[receive_idx] if 0 <= receive_idx < 5 else "?"
    bits = [
        f"risk TwP {policy}",
        f"{give_count}:{receive_count} {gname}→{tname}",
        f"size-{size_delta}",
    ]
    if risk_delta > 0:
        bits.append(f"keep@risk-{risk_delta}")
    if get_need_bonus > 0:
        bits.append("fills need")
    bits.append("ditch-funded")
    return "; ".join(bits)


def risk_trade_score(item: Optional[Mapping[str, Any]]) -> int:
    """Score a risk TwB or risk TwP pick for package comparison (higher = better)."""
    if not isinstance(item, Mapping):
        return 0
    mode = str(item.get("mode", "") or "")
    is_trade = mode in {"risk_twb", "risk_twp"} or item.get("give") is not None or item.get("size_delta") is not None
    if not is_trade and mode != "risk_twp":
        # Allow plan-item shaped dicts
        if item.get("action") not in ("TwB", "TwP"):
            return 0
    size = int(item.get("size_delta", 0) or 0)
    risk = int(item.get("keep_at_risk_before", 0) or 0) - int(item.get("keep_at_risk_after", 0) or 0)
    need = int(item.get("get_need_bonus", 0) or 0)
    score = size + risk * 6 + need * 2
    # T2: mutual player trade efficiency bonus (prefer TwP when it helps need)
    if mode == "risk_twp" or str(item.get("action", "")) == "TwP":
        give_n = int(item.get("give_count", 0) or 0)
        get_n = int(item.get("get_count", 0) or 0)
        if give_n <= 0:
            give_vec = list(item.get("give") or [])
            get_vec = list(item.get("get") or [])
            give_n = sum(int(x or 0) for x in give_vec[:5])
            get_n = sum(int(x or 0) for x in get_vec[:5])
        if need > 0 and give_n == 1 and get_n == 1:
            score += 5  # 1:1 need-fill beats typical 4:1 bank dump
        elif need > 0 and give_n == 2 and get_n == 1:
            score += 2
        elif size >= 1:
            score += 1  # slight prefer mutual size dump over bank
    return int(score)


def compare_risk_trades(
    risk_twp: Optional[Mapping[str, Any]],
    risk_twb: Optional[Mapping[str, Any]],
    *,
    policy: str = "soft_reduce",
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return 'risk_twp' | 'risk_twb' | '' — prefer mutual TwP when similar value (T2)."""
    has_p = isinstance(risk_twp, Mapping) and (
        risk_twp.get("mode") == "risk_twp"
        or risk_twp.get("action") == "TwP"
        or risk_twp.get("proposal") is not None
    )
    has_b = isinstance(risk_twb, Mapping) and (
        risk_twb.get("mode") == "risk_twb"
        or risk_twb.get("action") == "TwB"
        or risk_twb.get("give") is not None
        or risk_twb.get("size_delta") is not None
    )
    if has_p and not has_b:
        return "risk_twp"
    if has_b and not has_p:
        return "risk_twb"
    if not has_p and not has_b:
        return ""

    p_score = risk_trade_score(risk_twp)
    b_score = risk_trade_score(risk_twb)
    pol = str(policy or "soft_reduce")
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="risk_trades")
    # Soft near-tie: slight prefer TwP (human-like mutual dump)
    if STAGE_D_ENABLED and pol == "soft_reduce" and active_rng is not None:
        if abs(p_score - b_score) <= PACKAGE_SCORE_EPS:
            # Bias toward TwP on exact/near ties
            if p_score >= b_score:
                return "risk_twp"
            return active_rng.choice(["risk_twp", "risk_twb"])
    if p_score > b_score:
        return "risk_twp"
    if b_score > p_score:
        return "risk_twb"
    # hard_reduce pure ties → TwP (mutual preferred when equal)
    return "risk_twp"


# ──────────────────────────────────────────────────────────────────────────────
# Stage C — secondary helpful buy/build
# ──────────────────────────────────────────────────────────────────────────────

# Progress value for ranking secondary actions (higher = better)
SECONDARY_PROGRESS = {
    "Build city": 4,
    "Build settlement": 3,
    "Build road": 3,
    "Buy development_card": 2,
}


def select_secondary_helpful_action(
    profile: Mapping[str, Any],
    options: Sequence[Mapping[str, Any]],
    *,
    preferred_action: str = "",
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Stage C: pick a legal buy/build that spends ditch and helps the way.

    Each option mapping should include:
      action: str
      cost: [5] int
      strategy_fit: int  (0–3, higher = more on-strategy)
      label: optional str
      candidate: optional concrete target
      choice: optional full scanner choice

    Rules:
    - policy soft_reduce or hard_reduce, hand > 7
    - not the preferred strategic action family (unless preferred unaffordable already handled elsewhere)
    - can pay cost now
    - soft: entire cost from ditch; hard: at most 0 keep units (same as soft for v1)
    - strategy_fit > 0 required
    Stage D: soft near-ties among same progress/fit (size within ε) may be randomized.
    """
    if not isinstance(profile, Mapping) or not profile:
        return None
    policy = str(profile.get("policy", "accept") or "accept")
    total = int(profile.get("total", 0) or 0)
    if total <= 7 or policy not in {"soft_reduce", "hard_reduce"}:
        return None

    hand = [max(0, int(x or 0)) for x in list(profile.get("hand") or [])[:5]]
    while len(hand) < 5:
        hand.append(0)
    ditch = [max(0, int(x or 0)) for x in list(profile.get("ditch") or [])[:5]]
    while len(ditch) < 5:
        ditch.append(0)
    keep = [max(0, int(x or 0)) for x in list(profile.get("keep") or [])[:5]]
    while len(keep) < 5:
        keep.append(0)

    preferred = str(preferred_action or "").strip()
    ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    for raw in list(options or []):
        if not isinstance(raw, Mapping):
            continue
        action = str(raw.get("action", "") or "")
        if action not in SECONDARY_PROGRESS:
            continue
        if preferred and action == preferred:
            # Secondary must not steal the preferred family when it is the same
            # (preferred path uses actionable/unlock). Allow only if explicitly marked.
            if not bool(raw.get("allow_preferred_family", False)):
                continue

        cost = [0, 0, 0, 0, 0]
        raw_cost = raw.get("cost")
        if isinstance(raw_cost, Sequence) and not isinstance(raw_cost, (str, bytes, Mapping)):
            for i, v in enumerate(list(raw_cost)[:5]):
                try:
                    cost[i] = max(0, int(v or 0))
                except Exception:
                    pass
        if sum(cost) <= 0:
            continue
        # Can pay
        if any(hand[i] < cost[i] for i in range(5)):
            continue
        # Soft/hard v1: entire cost from ditch (never touch keep)
        if any(cost[i] > ditch[i] for i in range(5)):
            continue

        try:
            strategy_fit = int(raw.get("strategy_fit", 0) or 0)
        except Exception:
            strategy_fit = 0
        if strategy_fit <= 0:
            continue

        after = [hand[i] - cost[i] for i in range(5)]
        size_delta = sum(cost)
        size_after = sum(after)
        after_keep = [min(after[i], keep[i]) for i in range(5)]
        after_ditch = [max(0, after[i] - after_keep[i]) for i in range(5)]
        after_discard_n = size_after // 2 if size_after > 7 else 0
        after_keep_at_risk = max(0, after_discard_n - sum(after_ditch))
        before_risk = int(profile.get("keep_at_risk", 0) or 0)
        risk_delta = before_risk - after_keep_at_risk
        progress = int(SECONDARY_PROGRESS.get(action, 1))

        # Rank: higher progress/fit/size/risk relief is better → negate for min-tuple
        rank = (
            -progress,
            -strategy_fit,
            -size_delta,
            -risk_delta,
            action,
        )
        ranked.append(
            (
                rank,
                {
                    "mode": "secondary_helpful",
                    "action": action,
                    "cost": list(cost),
                    "strategy_fit": strategy_fit,
                    "progress": progress,
                    "hand_before": list(hand),
                    "hand_after": list(after),
                    "size_delta": size_delta,
                    "keep_at_risk_before": before_risk,
                    "keep_at_risk_after": after_keep_at_risk,
                    "policy": policy,
                    "candidate": dict(raw.get("candidate") or {}) if isinstance(raw.get("candidate"), Mapping) else {},
                    "choice": dict(raw.get("choice") or {}) if isinstance(raw.get("choice"), Mapping) else {},
                    "label": str(raw.get("label") or action),
                    "reason": _secondary_reason(action, strategy_fit, size_delta, policy),
                },
            )
        )

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="secondary")
    allow = STAGE_D_ENABLED and policy == "soft_reduce"

    def _sec_in_band(best_rank: Any, other_rank: Any) -> bool:
        if not isinstance(best_rank, tuple) or not isinstance(other_rank, tuple):
            return best_rank == other_rank
        if policy == "hard_reduce":
            return best_rank == other_rank
        # soft: same progress & fit; size_delta within ε (rank stores -size)
        if best_rank[0] != other_rank[0] or best_rank[1] != other_rank[1]:
            return False
        best_size = -int(best_rank[2])
        other_size = -int(other_rank[2])
        return abs(best_size - other_size) <= SECONDARY_SIZE_EPS

    pick, _meta = pick_near_tie_band(
        ranked,
        in_band=_sec_in_band,
        rng=active_rng,
        allow_rng=allow,
        decision_tag="secondary",
    )
    return pick


def package_scores(
    secondary: Optional[Mapping[str, Any]],
    risk_twb: Optional[Mapping[str, Any]],
    risk_twp: Optional[Mapping[str, Any]] = None,
) -> Tuple[int, int, int]:
    """Numeric scores used by package compare (and Stage D ε-band).

    Returns (secondary_score, risk_twb_score, risk_twp_score).
    TwB score remains compatible with pre-T2 callers (index 1).
    """
    has_s = isinstance(secondary, Mapping) and secondary.get("action")
    has_b = isinstance(risk_twb, Mapping) and (
        risk_twb.get("mode") == "risk_twb"
        or risk_twb.get("action") == "TwB"
        or risk_twb.get("give") is not None
        or risk_twb.get("size_delta") is not None
    )
    has_p = isinstance(risk_twp, Mapping) and (
        risk_twp.get("mode") == "risk_twp"
        or risk_twp.get("action") == "TwP"
        or risk_twp.get("proposal") is not None
    )
    s_score = 0
    b_score = 0
    p_score = 0
    if has_s:
        s_prog = int(secondary.get("progress", 0) or 0)  # type: ignore[union-attr]
        s_fit = int(secondary.get("strategy_fit", 0) or 0)  # type: ignore[union-attr]
        s_size = int(secondary.get("size_delta", 0) or 0)  # type: ignore[union-attr]
        s_risk = int(secondary.get("keep_at_risk_before", 0) or 0) - int(secondary.get("keep_at_risk_after", 0) or 0)  # type: ignore[union-attr]
        s_score = s_prog * 8 + s_fit * 3 + s_size + s_risk * 2
    if has_b:
        b_score = risk_trade_score(risk_twb)
    if has_p:
        p_score = risk_trade_score(risk_twp)
    return s_score, b_score, p_score


def compare_risk_package_scores(
    secondary: Optional[Mapping[str, Any]],
    risk_twb: Optional[Mapping[str, Any]],
    *,
    risk_twp: Optional[Mapping[str, Any]] = None,
    policy: str = "soft_reduce",
    rng: Optional[random.Random] = None,
    rng_context: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return 'secondary' | 'risk_twb' | 'risk_twp' | '' for which package wins.

    Prefer real progress (secondary) when strong.
    Prefer risk TwP over risk TwB when mutual value is similar (T2).
    Stage D: on soft_reduce only, near-tie scores (|Δ|≤PACKAGE_SCORE_EPS) may RNG
    between secondary and the best risk trade.
    hard_reduce stays pure argmax (no package coin-flip vs secondary).
    """
    # First resolve TwP vs TwB (T2 prefer mutual when competitive)
    trade_winner = compare_risk_trades(
        risk_twp,
        risk_twb,
        policy=policy,
        rng=rng,
        rng_context=rng_context,
    )
    best_trade: Optional[Mapping[str, Any]] = None
    trade_label = ""
    if trade_winner == "risk_twp" and isinstance(risk_twp, Mapping):
        best_trade = risk_twp
        trade_label = "risk_twp"
    elif trade_winner == "risk_twb" and isinstance(risk_twb, Mapping):
        best_trade = risk_twb
        trade_label = "risk_twb"

    has_s = isinstance(secondary, Mapping) and secondary.get("action")
    has_t = best_trade is not None
    if has_s and not has_t:
        return "secondary"
    if has_t and not has_s:
        return trade_label
    if not has_s and not has_t:
        return ""

    s_score, b_score, p_score = package_scores(secondary, risk_twb, risk_twp)
    t_score = p_score if trade_label == "risk_twp" else b_score
    # If trade_label set, use that trade's score directly
    if trade_label:
        t_score = risk_trade_score(best_trade)

    pol = str(policy or "soft_reduce")
    active_rng = rng if rng is not None else rng_from_context(rng_context, tag="risk_package")
    if (
        STAGE_D_ENABLED
        and pol == "soft_reduce"
        and active_rng is not None
        and abs(s_score - t_score) <= PACKAGE_SCORE_EPS
    ):
        pick = active_rng.choice(["secondary", trade_label])
        return pick
    if s_score >= t_score:
        return "secondary"
    return trade_label


def _secondary_reason(action: str, strategy_fit: int, size_delta: int, policy: str) -> str:
    short = {
        "Build city": "City",
        "Build settlement": "Settle",
        "Build road": "Road",
        "Buy development_card": "DCard",
    }.get(action, action)
    return f"secondary {short} ({policy}); fit {strategy_fit}; hand-{size_delta}"


# ──────────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────────


def _empty_profile() -> Dict[str, Any]:
    z = [0, 0, 0, 0, 0]
    return {
        "stage": "A",
        "player_id": None,
        "total": 0,
        "over_seven": 0,
        "discard_if_seven": 0,
        "hand": list(z),
        "keep": list(z),
        "ditch": list(z),
        "immediate_need": list(z),
        "soft_engine_keep": list(z),
        "need": list(z),
        "keep_at_risk": 0,
        "expected_loss_if_seven": list(z),
        "policy": "accept",
        "policy_reason": "no_player",
        "compact": "Hand: -",
        "resource_order": list(RESOURCE_NAMES),
    }


def _policy_band(*, total: int, keep_at_risk: int) -> str:
    if total <= 7:
        return "accept"
    if keep_at_risk >= HARD_REDUCE_KEEP_AT_RISK or total >= HARD_REDUCE_MIN_HAND:
        return "hard_reduce"
    if keep_at_risk >= SOFT_REDUCE_KEEP_AT_RISK or total >= SOFT_REDUCE_MIN_HAND:
        return "soft_reduce"
    # Over 7 but ditch covers full discard and size modest
    return "accept"


def _policy_reason(total: int, keep_at_risk: int, policy: str) -> str:
    if total <= 7:
        return "hand≤7 no discard risk"
    if policy == "accept":
        return "ditch covers if7 discard; accept over-7 hold"
    if policy == "hard_reduce":
        if keep_at_risk >= HARD_REDUCE_KEEP_AT_RISK:
            return f"keep@risk {keep_at_risk} (hard)"
        return f"hand {total}≥{HARD_REDUCE_MIN_HAND} (hard)"
    if keep_at_risk >= SOFT_REDUCE_KEEP_AT_RISK:
        return f"keep@risk {keep_at_risk} (soft)"
    return f"hand {total}≥{SOFT_REDUCE_MIN_HAND} (soft)"


def _simulate_discard_impact(
    *,
    hand: Sequence[int],
    keep: Sequence[int],
    discard_count: int,
    discard_score: Sequence[float],
) -> Tuple[int, List[int]]:
    """Simulate ditch-first discard; count keep units lost and expected loss vector."""
    rem = [max(0, int(x or 0)) for x in list(hand)[:5]]
    while len(rem) < 5:
        rem.append(0)
    ditch_left = [max(0, int(hand[i]) - int(keep[i])) for i in range(5)]
    scores = [float(x) for x in list(discard_score)[:5]]
    while len(scores) < 5:
        scores.append(-999.0)

    loss = [0, 0, 0, 0, 0]
    keep_lost = 0
    for _ in range(max(0, int(discard_count))):
        best_i = None
        best_s = -1e18
        for i in range(5):
            if rem[i] <= 0:
                continue
            s = scores[i]
            if s > best_s:
                best_s = s
                best_i = i
        if best_i is None:
            break
        rem[best_i] -= 1
        loss[best_i] += 1
        if ditch_left[best_i] > 0:
            ditch_left[best_i] -= 1
        else:
            keep_lost += 1
    return keep_lost, loss


def _immediate_need_vector5(player: Any) -> List[int]:
    """Preferred-action cost budget to protect (full cost, not shortfall).

    keep uses min(hand, cost + soft_engine). Using shortfall would fail to protect
    cards already in hand that still pay the preferred build.
    """
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        direction = {}
    support = str(direction.get("supporting_action_type", "") or "").lower()
    costs = {
        "city": [2, 3, 0, 0, 0],
        "city_upgrade": [2, 3, 0, 0, 0],
        "build_city": [2, 3, 0, 0, 0],
        "settlement": [1, 0, 1, 1, 1],
        "next_settlement": [1, 0, 1, 1, 1],
        "build_settlement": [1, 0, 1, 1, 1],
        # new settlement project: settlement + road soft budget until roads done
        "new_settlement": [1, 0, 2, 2, 1],
        "road": [0, 0, 1, 1, 0],
        "build_road": [0, 0, 1, 1, 0],
        "buy_dcard": [1, 1, 0, 0, 1],
        "dcard": [1, 1, 0, 0, 1],
        "development_card": [1, 1, 0, 0, 1],
    }
    # Prefer road cost when expansion still has roads to build
    roads = direction.get("roads_to_build")
    has_roads = isinstance(roads, Sequence) and not isinstance(roads, (str, bytes, Mapping)) and any(
        r not in (None, "", [], ()) for r in list(roads or [])
    )
    if "new_settlement" in support and has_roads:
        return [0, 0, 1, 1, 0]
    for key, vec in costs.items():
        if key in support:
            return list(vec)
    return [0, 0, 0, 0, 0]


def _soft_engine_keep_vector5(player: Any) -> List[int]:
    """Capped soft keep from way need / needed_rcards (not full CSV totals)."""
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        direction = {}
    soft = [0, 0, 0, 0, 0]
    named = direction.get("needed_rcards") or direction.get("needed_rcards_after")
    if isinstance(named, Mapping):
        for i, name in enumerate(RESOURCE_NAMES):
            raw = 0.0
            for key in (name, name.lower(), "Wool" if name == "Sheep" else name):
                if key in named:
                    try:
                        raw = float(named.get(key) or 0)
                    except Exception:
                        raw = 0.0
                    break
            if raw > 0:
                # Cap so full-way totals (e.g. 21 Wheat) do not freeze the hand
                soft[i] = min(SOFT_ENGINE_KEEP_CAP_PER_RESOURCE, max(1, int(round(raw))))
    return soft


def _hand_vector5(game: Any, player: Any) -> List[int]:
    out = [0, 0, 0, 0, 0]
    if player is None:
        return out
    # Prefer game helper when present
    if game is not None:
        try:
            getter = getattr(game, "_execution_hand_vector_for_player", None)
            if callable(getter):
                vec = getter(player)
                if isinstance(vec, Sequence) and not isinstance(vec, (str, bytes)):
                    return [max(0, int(x or 0)) for x in list(vec)[:5]] + [0] * 5
        except Exception:
            pass
    rcards = getattr(player, "rcards", None)
    if isinstance(rcards, Mapping):
        for i, name in enumerate(RESOURCE_NAMES):
            val = 0
            for key in (name, name.lower(), name.upper()):
                if key in rcards:
                    try:
                        val = int(rcards.get(key) or 0)
                        break
                    except Exception:
                        pass
            if val == 0:
                for k, v in rcards.items():
                    kn = getattr(k, "value", k)
                    if str(kn) == name:
                        try:
                            val = int(v or 0)
                        except Exception:
                            val = 0
                        break
            out[i] = max(0, val)
        return out
    try:
        info = player.rcards_in_hand()
        if isinstance(info, (list, tuple)) and info and isinstance(info[0], (list, tuple)):
            return [max(0, int(x or 0)) for x in list(info[0])[:5]] + [0] * max(0, 5 - len(list(info[0])[:5]))
    except Exception:
        pass
    return out[:5]


def _production_pips_vector5(game: Any, player: Any) -> List[float]:
    try:
        from core.resource_time_estimator import get_player_production_pips

        board = getattr(game, "board", None) if game is not None else None
        if board is not None and player is not None:
            return [float(x) for x in get_player_production_pips(board, player)[:5]]
    except Exception:
        pass
    return [0.0] * 5


def _trade_rates_vector5(game: Any, player: Any) -> List[int]:
    try:
        from core.resource_time_estimator import get_player_trade_rates

        board = getattr(game, "board", None) if game is not None else None
        if board is not None and player is not None:
            return [max(1, int(x or 4)) for x in get_player_trade_rates(board, player)[:5]]
    except Exception:
        pass
    if game is not None:
        try:
            getter = getattr(game, "get_player_bank_trade_rates", None)
            if callable(getter) and player is not None:
                rates = getter(player)
                if isinstance(rates, Sequence):
                    return [max(1, int(x or 4)) for x in list(rates)[:5]]
        except Exception:
            pass
    return [4, 4, 4, 4, 4]


def _named_vector(values: Sequence[int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, name in enumerate(RESOURCE_NAMES):
        try:
            n = int(values[i] or 0)
        except Exception:
            n = 0
        if n:
            out[name] = n
    return out


def _safe_player_id(player: Any) -> Optional[int]:
    try:
        return int(getattr(player, "id"))
    except Exception:
        return None


def _fit(text: str, n: int) -> str:
    s = str(text or "")
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


__all__ = [
    "RESOURCE_NAMES",
    "build_hand_risk_profile",
    "refresh_hand_risk_profile",
    "get_hand_risk_profile",
    "format_hand_risk_compact",
    "format_hand_risk_detail_rows",
    "select_risk_twb_candidate",
    "select_risk_twp_candidate",
    "select_secondary_helpful_action",
    "compare_risk_package_scores",
    "compare_risk_trades",
    "risk_trade_score",
    "package_scores",
    "decision_rng",
    "rng_from_context",
    "pick_near_tie_band",
    "pick_twp_partner_near_tie",
    "maybe_soft_pass_risk_twp",
    "SOFT_REDUCE_MIN_HAND",
    "HARD_REDUCE_MIN_HAND",
    "SOFT_RISK_TWB_MAX_RATE",
    "HARD_RISK_TWB_MAX_RATE",
    "STAGE_D_ENABLED",
    "PACKAGE_SCORE_EPS",
    "TWP_PARTNER_SCORE_EPS",
    "TWP_RISK_SOFT_PASS_MAX_SCORE",
    "TWP_RISK_SOFT_PASS_PROB",
]
