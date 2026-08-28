"""Resource (RCard) trade/spend ladder toward sticky / listed targets.

Operator body (`docs/placeholders.txt` / `docs/P3_optimizers_spec.md`):

  2.1 TwB **and TwP** that help the player hit target(s) sooner.
  2.2 Playing DCards (touch ``dcard_optimizer``):
        a) Knight — steal supports winning a race; only when steal odds
           for the needed type look substantial (knowledge stub later).
        b) YOP — race win or unlock action(s) that yield ≥1 new VP.
        c) Monopoly — same bar as YOP.
  2.3 Combinations of 2.1 + 2.2 (e.g. Monopoly scarce type → TwB into need).

Name note: **RCard** = resource cards. DCard play sequencing lives in
``dcard_optimizer``; this module only *suggests when* a play helps the
resource/target ladder.

Related live code:
  - ``core.player_trade`` / human TwP policy
  - ``core.ai_hand_risk`` (risk TwB/TwP)
  - portfolio / EH TwB for Tgt & ETA
  - ``core.ai_play_*`` + ``ai_play_dcard_choice`` for actual plays

WIRING (slice 1 — near-complete fill):
  ``suggest_trades_for_targets`` enumerates unlock TwP (and bank rows that
  still leave the target affordable) when the seat is 1–3 cards short of the
  live supporting action. Used by Dig/ACT and as a BA TwP bias helper.
  Combo Monopoly→TwB remains dig-first.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

WIRING_STATUS = "partial_dcard_touchpoints_twp_invent"
WIRING_TODO = (
    "Deepen combo Monopoly→TwB; Dig ACT one-liner for touchpoints "
    "(docs/P3_optimizers_spec.md / SE WP-TWP2 invent+wait)."
)

_RESOURCE_ABBR = ("Wh", "O", "Wd", "B", "Sh")
_WHEAT_IDX = 0

# Canonical action costs in project order [Wh, O, Wd, B, Sh].
ACTION_COSTS: Dict[str, Tuple[int, int, int, int, int]] = {
    "Build road": (0, 0, 1, 1, 0),
    "Build settlement": (1, 0, 1, 1, 1),
    "Build city": (2, 3, 0, 0, 0),
    "Buy development_card": (1, 1, 0, 0, 1),
}


def _vec5(raw: Any) -> List[int]:
    out = [max(0, int(x or 0)) for x in list(raw or [])[:5]]
    while len(out) < 5:
        out.append(0)
    return out


def _hand_vector(game: Any, player: Any) -> List[int]:
    fn = getattr(game, "_execution_hand_vector_for_player", None) if game is not None else None
    if callable(fn):
        try:
            return _vec5(fn(player))
        except Exception:
            pass
    # Fallback: rcards mapping / list
    try:
        from core.constants import ResourceCard

        order = [
            ResourceCard.WHEAT,
            ResourceCard.ORE,
            ResourceCard.WOOD,
            ResourceCard.BRICK,
            ResourceCard.SHEEP,
        ]
        rc = getattr(player, "rcards", None) or {}
        if isinstance(rc, Mapping):
            return _vec5([rc.get(k, 0) for k in order])
    except Exception:
        pass
    return [0, 0, 0, 0, 0]


def _live_support_need(game: Any, player: Any) -> Tuple[str, List[int], List[int]]:
    """Return (action, cost, live_need) for the seat's immediate support action."""
    try:
        from core.player_trade import resolve_live_need_for_twp

        act, cost, need = resolve_live_need_for_twp(game, player)
        return str(act or ""), _vec5(cost), _vec5(need)
    except Exception:
        pass
    fn = getattr(game, "_supporting_action_live_need_vector", None) if game is not None else None
    if callable(fn):
        try:
            act, cost, need = fn(player)
            return str(act or ""), _vec5(cost), _vec5(need)
        except Exception:
            pass
    return "", [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]


def _format_need(need: Sequence[int]) -> str:
    bits = [
        f"{_RESOURCE_ABBR[i]}{int(need[i])}"
        for i in range(5)
        if int(need[i] or 0) > 0
    ]
    return ",".join(bits) if bits else "—"


def _twb_rows_that_unlock(
    *,
    hand: Sequence[int],
    cost: Sequence[int],
    need: Sequence[int],
    rates: Sequence[int],
) -> List[Dict[str, Any]]:
    """Bank rows that fully unlock ``cost`` after the trade (generic any resource)."""
    hand_v = _vec5(hand)
    cost_v = _vec5(cost)
    need_v = _vec5(need)
    rates_v = _vec5(rates) if rates is not None else [4, 4, 4, 4, 4]
    for i in range(5):
        if rates_v[i] <= 0:
            rates_v[i] = 4
    surplus = [max(0, hand_v[i] - cost_v[i]) for i in range(5)]
    rows: List[Dict[str, Any]] = []
    for get_idx in range(5):
        if need_v[get_idx] <= 0:
            continue
        for give_idx in range(5):
            if give_idx == get_idx:
                continue
            rate = int(rates_v[give_idx] or 4)
            if surplus[give_idx] < rate:
                continue
            give = [0, 0, 0, 0, 0]
            get = [0, 0, 0, 0, 0]
            give[give_idx] = rate
            get[get_idx] = 1
            after = [hand_v[i] - give[i] + get[i] for i in range(5)]
            if any(v < 0 for v in after):
                continue
            if any(after[i] < cost_v[i] for i in range(5)):
                # Does not leave target affordable — skip (R3T2: 4Wh→Wd leaves Wh0)
                continue
            rows.append(
                {
                    "kind": "TwB",
                    "give_index": give_idx,
                    "give_count": rate,
                    "get_index": get_idx,
                    "get_count": 1,
                    "label": (
                        f"TwB {rate}{_RESOURCE_ABBR[give_idx]}→1{_RESOURCE_ABBR[get_idx]}"
                    ),
                    "fully_unlocks": True,
                    "reason": "near_complete_bank_unlock",
                }
            )
    return rows


def _proposal_as_dict(p: Any) -> Dict[str, Any]:
    try:
        if hasattr(p, "as_dict"):
            return dict(p.as_dict() or {})
    except Exception:
        pass
    return {}


def _hand_after_proposal(hand: Sequence[int], proposal: Any) -> List[int]:
    h = _vec5(hand)
    snap = getattr(proposal, "market_snapshot", None) or {}
    if isinstance(snap, Mapping) and snap.get("multi_resource_give"):
        gain = [int(x or 0) for x in list(getattr(proposal, "active_gain_vector", ()) or [])[:5]]
        while len(gain) < 5:
            gain.append(0)
        return [h[i] + gain[i] for i in range(5)]
    try:
        gi = int(getattr(proposal, "active_give_index"))
        gc = int(getattr(proposal, "active_give_count") or 0)
        ri = int(getattr(proposal, "active_receive_index"))
        rc = int(getattr(proposal, "active_receive_count") or 0)
    except Exception:
        return h
    if 0 <= gi < 5:
        h[gi] -= gc
    if 0 <= ri < 5:
        h[ri] += rc
    return h


def _can_pay(hand: Sequence[int], cost: Sequence[int]) -> bool:
    h, c = _vec5(hand), _vec5(cost)
    return all(h[i] >= c[i] for i in range(5))


def enumerate_two_leg_unlock_chains(
    game: Any,
    player: Any,
    *,
    cost: Optional[Sequence[int]] = None,
    need: Optional[Sequence[int]] = None,
    hand: Optional[Sequence[int]] = None,
    support_action: str = "",
    include_human_counterparties: bool = True,
    prefer_wh_sweetener: bool = True,
) -> Dict[str, Any]:
    """Enumerate two-leg TwP packages that restore a spent settle-cost card.

    R3T2 pattern (generic): missing only ``M`` for target cost; temporarily give
    bridge resource ``B`` (part of cost, currently held) for ``M``, then restore
    ``B`` with surplus ``S`` (e.g. Ore): ``B→M`` then ``S→B``. Legs may use
    different counterparties. Optional Wh sweetener on leg2 (``S+Wh→B``) raises
    accept odds when modeling rejection risk.

    Returns **at most one** chosen package (a XOR b): never schedules both
    alternative bridges in the same plan.
    """
    if cost is None or need is None:
        action, cost_v, need_v = _live_support_need(game, player)
        support_action = support_action or action
        cost = cost_v
        need = need_v
    cost_v = _vec5(cost)
    need_v = _vec5(need)
    hand_v = _vec5(hand) if hand is not None else _hand_vector(game, player)

    missing_idxs = [i for i in range(5) if need_v[i] > 0]
    if len(missing_idxs) != 1:
        return {
            "ok": True,
            "packages": [],
            "chosen": None,
            "note": f"need_not_single:{_format_need(need_v)}",
        }
    miss_idx = missing_idxs[0]

    # Bridge: in target cost, currently held (≥1), not the missing resource
    bridges = [
        i
        for i in range(5)
        if i != miss_idx and cost_v[i] > 0 and hand_v[i] >= 1
    ]
    # Restorer: clear surplus vs cost (e.g. Ore when settling)
    restorers = [i for i in range(5) if hand_v[i] > cost_v[i] and i != miss_idx]

    if not bridges or not restorers:
        return {
            "ok": True,
            "packages": [],
            "chosen": None,
            "note": "no_bridge_or_restorer",
        }

    try:
        from core.player_trade import (
            find_directed_unlock_twp_proposals,
            with_wh_sweetener,
        )
    except Exception as exc:
        return {"ok": False, "packages": [], "chosen": None, "note": f"import:{exc}"}

    packages: List[Dict[str, Any]] = []
    for bridge in bridges:
        for restorer in restorers:
            if restorer == bridge:
                continue
            # Leg1 live_need = missing only (spend bridge for miss)
            leg1_need = [0, 0, 0, 0, 0]
            leg1_need[miss_idx] = int(need_v[miss_idx])
            leg1_list = find_directed_unlock_twp_proposals(
                game,
                player,
                give_index=bridge,
                receive_index=miss_idx,
                live_need=leg1_need,
                primary_cost=cost_v,
                primary_action=support_action or "Build settlement",
                max_candidates=6,
                include_human_counterparties=include_human_counterparties,
            )
            if not leg1_list:
                continue
            for leg1 in leg1_list:
                hand_mid = _hand_after_proposal(hand_v, leg1)
                if hand_mid[miss_idx] < cost_v[miss_idx]:
                    continue
                if hand_mid[bridge] >= cost_v[bridge]:
                    # Bridge not spent / still affordable — one-leg enough; skip chain
                    continue
                # Leg2: restore bridge with restorer
                leg2_need = [0, 0, 0, 0, 0]
                leg2_need[bridge] = max(0, cost_v[bridge] - hand_mid[bridge])
                if sum(leg2_need) <= 0:
                    continue
                # Simulate mid-hand on a shadow isn't available; directed unlock
                # uses live profiles from current hands. Prefer CPs that still
                # have bridge resource and want restorer (city pivot etc.).
                leg2_list = find_directed_unlock_twp_proposals(
                    game,
                    player,
                    give_index=restorer,
                    receive_index=bridge,
                    live_need=leg2_need,
                    primary_cost=cost_v,
                    primary_action=support_action or "Build settlement",
                    max_candidates=6,
                    include_human_counterparties=include_human_counterparties,
                )
                # Filter: active must still hold restorer after leg1
                leg2_ok = []
                for leg2 in leg2_list:
                    if hand_mid[restorer] < int(getattr(leg2, "active_give_count", 1) or 1):
                        continue
                    # Avoid same physical cards contradiction; CP for leg2 must
                    # still have bridge after leg1 if same CP gave bridge away.
                    cid1 = int(getattr(leg1, "counterparty_id", -1) or -1)
                    cid2 = int(getattr(leg2, "counterparty_id", -2) or -2)
                    if cid1 == cid2:
                        # Same opponent: they gained restorer? No — they received
                        # bridge in leg1? Leg1: we give bridge, they give miss.
                        # They now have less miss resource, more bridge — OK for
                        # leg2 we need them to give bridge back: they just got
                        # our bridge, so they have more bridge. Good.
                        pass
                    hand_end = _hand_after_proposal(hand_mid, leg2)
                    if not _can_pay(hand_end, cost_v):
                        continue
                    leg2_ok.append((leg2, False, hand_end))
                    if prefer_wh_sweetener and hand_mid[_WHEAT_IDX] > cost_v[_WHEAT_IDX]:
                        # Keep ≥1 Wh for settle cost when sweetening
                        sweet = with_wh_sweetener(leg2, wheat_index=_WHEAT_IDX, extra_wheat=1)
                        if sweet is not None and hand_mid[_WHEAT_IDX] >= cost_v[_WHEAT_IDX] + 1:
                            hand_end_s = _hand_after_proposal(hand_mid, sweet)
                            if _can_pay(hand_end_s, cost_v):
                                leg2_ok.append((sweet, True, hand_end_s))

                for leg2, sweetened, hand_end in leg2_ok:
                    cid1 = int(getattr(leg1, "counterparty_id", -1) or -1)
                    cid2 = int(getattr(leg2, "counterparty_id", -1) or -1)
                    human = bool(
                        getattr(leg1, "requires_human_confirmation", False)
                        or getattr(leg2, "requires_human_confirmation", False)
                    )
                    score = float(getattr(leg1, "total_score", 0) or 0) + float(
                        getattr(leg2, "total_score", 0) or 0
                    )
                    if sweetened:
                        score += 0.25  # acceptance hedge
                    if not human:
                        score += 0.5
                    if cid1 != cid2:
                        score += 0.15  # diversification OK
                    label = (
                        f"{_RESOURCE_ABBR[bridge]}→{_RESOURCE_ABBR[miss_idx]} P{cid1}"
                        f" then {_RESOURCE_ABBR[restorer]}"
                        f"{'+Wh' if sweetened else ''}→{_RESOURCE_ABBR[bridge]} P{cid2}"
                    )
                    packages.append(
                        {
                            "kind": "TwP_chain2",
                            "bridge_index": bridge,
                            "miss_index": miss_idx,
                            "restorer_index": restorer,
                            "sweetened": sweetened,
                            "label": label,
                            "score": score,
                            "human": human,
                            "leg1": _proposal_as_dict(leg1),
                            "leg2": _proposal_as_dict(leg2),
                            "hand_after": hand_end,
                            "fully_unlocks": True,
                            "reason": "two_leg_near_complete_unlock",
                        }
                    )

    packages.sort(
        key=lambda p: (
            0 if not p.get("human") else 1,
            0 if p.get("fully_unlocks") else 1,
            -float(p.get("score") or 0),
            0 if p.get("sweetened") else 1,
            str(p.get("label") or ""),
        )
    )
    # Pick exactly one package (a XOR b) — first after sort
    chosen = packages[0] if packages else None
    return {
        "ok": True,
        "packages": packages[:8],  # dig visibility
        "chosen": chosen,
        "note": (
            f"chose {chosen.get('label')}"
            if chosen
            else "no_two_leg_chain"
        ),
    }


def _player_has_settlement(player: Any) -> bool:
    return bool(list(getattr(player, "settlements", None) or []))


def actions_affordable(
    hand: Sequence[int],
    *,
    has_settlement: bool = True,
) -> List[str]:
    """Which standard spend actions the hand can pay (ignores board legality)."""
    h = _vec5(hand)
    out: List[str] = []
    for name, cost in ACTION_COSTS.items():
        if name == "Build city" and not has_settlement:
            continue
        if _can_pay(h, cost):
            out.append(name)
    return out


def counterparty_trade_incentive(
    hand_before: Sequence[int],
    hand_after: Sequence[int],
    *,
    has_settlement: bool = True,
) -> Dict[str, Any]:
    """What the counterparty gains from a hypothetical hand delta.

    Generic R5T4-style lens: full unlock of road / settle / city / DCard, or
    partial fill toward those costs.
    """
    before = set(actions_affordable(hand_before, has_settlement=has_settlement))
    after = set(actions_affordable(hand_after, has_settlement=has_settlement))
    newly = sorted(after - before)
    fills: Dict[str, int] = {}
    hb, ha = _vec5(hand_before), _vec5(hand_after)
    for name, cost in ACTION_COSTS.items():
        if name == "Build city" and not has_settlement:
            continue
        need_b = sum(max(0, cost[i] - hb[i]) for i in range(5))
        need_a = sum(max(0, cost[i] - ha[i]) for i in range(5))
        reduced = need_b - need_a
        if reduced > 0:
            fills[name] = int(reduced)
    return {
        "newly_unlocked": newly,
        "fills": fills,
        "full_unlock": bool(newly),
        "score": 3.0 * len(newly) + 0.8 * sum(fills.values()),
    }


def plain_then_sweetener_pair(
    plain_proposal: Any,
    *,
    active_hand: Optional[Sequence[int]] = None,
    support_cost: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Generic offer ladder: try plain 1-resource give first; keep Wh-sweetener for decline.

    Returns ``{plain, sweetened, escalate_after_decline}``. Sweetener only when
    active still keeps support-cost Wheat after adding +1 Wh give.
    """
    plain_d = _proposal_as_dict(plain_proposal) if not isinstance(plain_proposal, Mapping) else dict(plain_proposal)
    out: Dict[str, Any] = {
        "plain": plain_d,
        "sweetened": None,
        "escalate_after_decline": True,
        "note": "plain_only",
    }
    try:
        from core.player_trade import trade_proposal_from_dict, with_wh_sweetener

        prop = (
            plain_proposal
            if hasattr(plain_proposal, "active_give_index")
            else trade_proposal_from_dict(plain_d)
        )
        hand = _vec5(active_hand) if active_hand is not None else None
        cost = _vec5(support_cost) if support_cost is not None else [0, 0, 0, 0, 0]
        if hand is not None and hand[_WHEAT_IDX] < cost[_WHEAT_IDX] + 1:
            out["note"] = "no_spare_wheat_for_sweetener"
            return out
        # Only sweeten true 1:1 plains
        if int(getattr(prop, "active_give_count", 0) or 0) != 1:
            out["note"] = "not_1for1"
            return out
        if int(getattr(prop, "active_give_index", -1)) == _WHEAT_IDX:
            out["note"] = "already_giving_wheat"
            return out
        sweet = with_wh_sweetener(prop)
        if sweet is None:
            out["note"] = "sweetener_unavailable"
            return out
        out["sweetened"] = _proposal_as_dict(sweet)
        out["note"] = "plain_then_wh_sweetener"
    except Exception as exc:
        out["note"] = f"sweetener_error:{exc}"
    return out


def _partner_city_score(incent: Mapping[str, Any]) -> float:
    """Extra weight when the partner unlocks or deeply fills a city (R6T4)."""
    newly = list(incent.get("newly_unlocked") or [])
    fills = incent.get("fills") if isinstance(incent.get("fills"), Mapping) else {}
    score = 0.0
    if "Build city" in newly:
        score += 5.0
    city_fill = int(fills.get("Build city") or 0)
    if city_fill >= 2:
        score += 2.5
    elif city_fill >= 1:
        score += 0.8
    return score


def _partner_action_bonus(incent: Mapping[str, Any]) -> float:
    """Generic partner-attractiveness beyond city (R6T3 road / DCard, etc.).

    Examples:
      - We need Brick for a sticky road; give Sheep for Brick while partner
        unlocks a DCard (Wh+O+Sh) — highly acceptable TwP.
      - Partner unlocks Build road / settlement.
    """
    newly = list(incent.get("newly_unlocked") or [])
    fills = incent.get("fills") if isinstance(incent.get("fills"), Mapping) else {}
    score = 0.0
    if "Buy development_card" in newly:
        score += 4.0
    elif int(fills.get("Buy development_card") or 0) >= 1:
        score += 1.0
    if "Build road" in newly:
        score += 3.0
    elif int(fills.get("Build road") or 0) >= 1:
        score += 0.7
    if "Build settlement" in newly:
        score += 3.5
    elif int(fills.get("Build settlement") or 0) >= 1:
        score += 0.7
    return score


def _append_mutual_offer(
    offers: List[Dict[str, Any]],
    *,
    prop: Any,
    hand: Sequence[int],
    cost_v: Sequence[int],
    need_v: Sequence[int],
    surplus: Sequence[int],
    get_idx: int,
    c_hand: Sequence[int],
    counter: Any,
    kind: str,
    primary_multi_give: bool = False,
) -> None:
    try:
        gi = int(prop.active_give_index)
        gc = int(prop.active_give_count or 0)
        ri = int(prop.active_receive_index)
        rc = int(prop.active_receive_count or 0)
        cid = int(prop.counterparty_id)
    except Exception:
        return
    # Counterparty after trade (honor multi-give vectors when present)
    snap = getattr(prop, "market_snapshot", None) or {}
    if isinstance(snap, Mapping) and snap.get("multi_resource_give"):
        gain_c = [int(x or 0) for x in list(getattr(prop, "counterparty_gain_vector", ()) or [])[:5]]
        while len(gain_c) < 5:
            gain_c.append(0)
        c_after = [int(c_hand[i]) + gain_c[i] for i in range(5)]
    else:
        c_after = list(c_hand)
        c_after[gi] += gc
        c_after[ri] -= rc
    if min(c_after) < 0:
        return
    incent = counterparty_trade_incentive(
        c_hand,
        c_after,
        has_settlement=_player_has_settlement(counter),
    )
    a_after = _hand_after_proposal(hand, prop)
    our_need_before = int(sum(need_v))
    our_need_after = our_need_before - min(
        int(need_v[get_idx]), int(rc or 1)
    )
    our_full = _can_pay(a_after, cost_v)
    if our_need_after >= our_need_before and not our_full:
        return
    if incent["score"] <= 0 and not incent["fills"] and not our_full:
        return
    score = (
        4.0 * (1 if our_full else 0)
        + 2.0 * (our_need_before - our_need_after)
        + float(incent["score"])
        + _partner_city_score(incent)
        + _partner_action_bonus(incent)
        + (0.4 if int(surplus[gi] if gi < 5 else 0) > 0 else 0.0)
        + (0.6 if primary_multi_give else 0.0)
    )
    them_bit = ",".join(incent.get("newly_unlocked") or []) or (
        f"city_fill{(incent.get('fills') or {}).get('Build city', 0)}"
        if (incent.get("fills") or {}).get("Build city")
        else "fill"
    )
    if primary_multi_give or (isinstance(snap, Mapping) and snap.get("wh_sweetener")):
        label = (
            f"{_RESOURCE_ABBR[gi]}+Wh→{_RESOURCE_ABBR[ri]} P{cid} (them:{them_bit})"
            if isinstance(snap, Mapping) and snap.get("wh_sweetener")
            else f"multi→{_RESOURCE_ABBR[ri]} P{cid} (them:{them_bit})"
        )
    else:
        label = f"{_RESOURCE_ABBR[gi]}→{_RESOURCE_ABBR[ri]} P{cid} (them:{them_bit})"
    offers.append(
        {
            "kind": kind,
            "label": label,
            "score": score,
            "counterparty_id": cid,
            "give_index": gi,
            "get_index": ri,
            "our_full_unlock": our_full,
            "our_need_reduced": our_need_before - our_need_after,
            "their_incentive": incent,
            "proposal": _proposal_as_dict(prop),
            "primary_multi_give": bool(primary_multi_give or (
                isinstance(snap, Mapping) and snap.get("multi_resource_give")
            )),
            "reason": kind,
        }
    )


def enumerate_mutual_unlock_twp(
    game: Any,
    player: Any,
    *,
    live_need: Optional[Sequence[int]] = None,
    support_cost: Optional[Sequence[int]] = None,
    support_action: str = "",
    include_human_counterparties: bool = True,
    max_offers: int = 16,
) -> Dict[str, Any]:
    """Enumerate TwP where we fill live_need and the partner unlocks/fills an action.

    R5T4 / R6T3 / R6T4 patterns (generic):
      - give surplus Ore for needed Wood while partner fills/unlocks city
      - give Wheat for Wood (Wh→Wd) when that fills partner city Wheat
      - give Brick for Sheep while partner unlocks a road
      - **Sh→B for our sticky road** while partner unlocks a DCard (R6T3)
      - **primary** Wh+O→Wd (multi-give) when that unlocks/deep-fills partner city
        (not only as a post-decline sweetener)
    """
    action, cost_v, need_v = _live_support_need(game, player)
    if support_cost is not None:
        cost_v = _vec5(support_cost)
    if live_need is not None:
        need_v = _vec5(live_need)
    support_action = support_action or action
    hand = _hand_vector(game, player)
    need_idxs = [i for i in range(5) if need_v[i] > 0]
    if not need_idxs:
        return {"ok": True, "offers": [], "chosen": None, "note": "no_live_need"}

    try:
        from core.player_trade import (
            find_directed_unlock_twp_proposals,
            with_wh_sweetener,
        )
    except Exception as exc:
        return {"ok": False, "offers": [], "chosen": None, "note": f"import:{exc}"}

    active_id = int(getattr(player, "id", -1) or -1)
    offers: List[Dict[str, Any]] = []

    # Prefer surplus gives; also allow keep-spend when it is the only path to need
    surplus = [max(0, hand[i] - cost_v[i]) for i in range(5)]
    give_candidates = [i for i in range(5) if hand[i] > 0 and i not in need_idxs]

    for get_idx in need_idxs:
        for give_idx in give_candidates:
            if give_idx == get_idx:
                continue
            props = find_directed_unlock_twp_proposals(
                game,
                player,
                give_index=give_idx,
                receive_index=get_idx,
                live_need=need_v,
                primary_cost=cost_v,
                primary_action=support_action or "Build settlement",
                max_candidates=8,
                include_human_counterparties=include_human_counterparties,
                allow_keep_spend=(surplus[give_idx] <= 0),
            )
            for prop in props:
                cid = int(getattr(prop, "counterparty_id", -1) or -1)
                counter = None
                for p in list(getattr(game, "players", []) or []):
                    if int(getattr(p, "id", -9) or -9) == cid:
                        counter = p
                        break
                if counter is None:
                    continue
                c_hand = _hand_vector(game, counter)
                _append_mutual_offer(
                    offers,
                    prop=prop,
                    hand=hand,
                    cost_v=cost_v,
                    need_v=need_v,
                    surplus=surplus,
                    get_idx=get_idx,
                    c_hand=c_hand,
                    counter=counter,
                    kind="TwP_mutual",
                )
                # R6T4: promote Wh+O (etc.) multi-give as a **first-class** offer
                # when it improves partner city / action incentive — not only after decline.
                ladder = plain_then_sweetener_pair(
                    prop, active_hand=hand, support_cost=cost_v
                )
                if not ladder.get("sweetened"):
                    continue
                try:
                    sweet_prop = with_wh_sweetener(prop)
                except Exception:
                    sweet_prop = None
                if sweet_prop is None:
                    continue
                # Active must still afford support-cost Wheat after sweetener
                a_after_s = _hand_after_proposal(hand, sweet_prop)
                if not all(a_after_s[i] >= 0 for i in range(5)):
                    continue
                _append_mutual_offer(
                    offers,
                    prop=sweet_prop,
                    hand=hand,
                    cost_v=cost_v,
                    need_v=need_v,
                    surplus=surplus,
                    get_idx=get_idx,
                    c_hand=c_hand,
                    counter=counter,
                    kind="TwP_mutual_city_pkg",
                    primary_multi_give=True,
                )

    def _them_unlocks(o: Mapping[str, Any]) -> list:
        return list((o.get("their_incentive") or {}).get("newly_unlocked") or [])

    offers.sort(
        key=lambda o: (
            0 if o.get("our_full_unlock") else 1,
            0 if "Build city" in _them_unlocks(o) else 1,
            0 if "Buy development_card" in _them_unlocks(o) else 1,
            0 if "Build road" in _them_unlocks(o) else 1,
            0 if (o.get("their_incentive") or {}).get("full_unlock") else 1,
            -float(o.get("score") or 0),
            0 if o.get("primary_multi_give") else 1,
            str(o.get("label") or ""),
        )
    )
    # Diversity: keep best plain + best multi per (partner, get_resource) so
    # Wh→Wd with Blue is not crowded out by many White multi-gives (R6T4).
    diversified: List[Dict[str, Any]] = []
    seen_slot: set = set()
    for o in offers:
        slot = (
            int(o.get("counterparty_id", -1) or -1),
            int(o.get("get_index", -1) or -1),
            1 if o.get("primary_multi_give") else 0,
            int(o.get("give_index", -1) or -1),
        )
        if slot in seen_slot:
            continue
        seen_slot.add(slot)
        diversified.append(o)
        if len(diversified) >= max(0, int(max_offers)):
            break
    offers = diversified
    return {
        "ok": True,
        "offers": offers,
        "chosen": offers[0] if offers else None,
        "note": (
            f"chose {offers[0]['label']}" if offers else "no_mutual_unlock"
        ),
        "active_player_id": active_id,
        "support_action": support_action,
        "live_need": need_v,
    }


def suggest_trades_for_targets(
    game: Any,
    player: Any,
    targets: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Suggest TwB/TwP that shorten acquire-Tgt for sticky / listed targets.

    Combines near-complete unlock TwP/TwB, two-leg chains, and mutual-unlock
    offers (partner city/road/settle/DCard incentive).
    """
    tgt_ids: List[Any] = []
    for t in list(targets or []):
        if isinstance(t, Mapping):
            tid = t.get("id") or t.get("target_id") or t.get("label")
            if tid is not None:
                tgt_ids.append(tid)
        else:
            tgt_ids.append(t)

    action, cost, need = _live_support_need(game, player)
    need_units = int(sum(need))
    hand = _hand_vector(game, player)
    twp_out: List[Dict[str, Any]] = []
    twb_out: List[Dict[str, Any]] = []
    chains: Dict[str, Any] = {"ok": True, "packages": [], "chosen": None, "note": "skipped"}
    mutual: Dict[str, Any] = {"ok": True, "offers": [], "chosen": None, "note": "skipped"}
    note = "no_live_need"

    if need_units <= 0:
        note = "already_affordable_or_no_support_action"
    else:
        note = f"need=[{_format_need(need)}] action={action or '—'}"
        if need_units <= 3:
            try:
                from core.player_trade import find_unlock_twp_proposals

                props = list(
                    find_unlock_twp_proposals(
                        game,
                        player,
                        max_candidates=12,
                        include_human_counterparties=True,
                        live_need=need,
                        primary_cost=cost if sum(cost) > 0 else None,
                        primary_action=action or None,
                    )
                    or []
                )
                for p in props:
                    d = _proposal_as_dict(p)
                    gi = int(getattr(p, "active_give_index", d.get("active_give_index", -1)) or -1)
                    gc = int(getattr(p, "active_give_count", d.get("active_give_count", 0)) or 0)
                    ri = int(
                        getattr(p, "active_receive_index", d.get("active_receive_index", -1))
                        or -1
                    )
                    rc = int(
                        getattr(p, "active_receive_count", d.get("active_receive_count", 0)) or 0
                    )
                    cid = getattr(p, "counterparty_id", d.get("counterparty_id"))
                    snap = getattr(p, "market_snapshot", None) or d.get("market_snapshot") or {}
                    twp_out.append(
                        {
                            "kind": "TwP",
                            "counterparty_id": cid,
                            "give_index": gi,
                            "give_count": gc,
                            "get_index": ri,
                            "get_count": rc,
                            "label": (
                                f"TwP {_RESOURCE_ABBR[gi] if 0 <= gi < 5 else '?'}{gc}"
                                f"→{_RESOURCE_ABBR[ri] if 0 <= ri < 5 else '?'}{rc}"
                                f" with P{cid}"
                            ),
                            "fully_unlocks": bool(snap.get("fully_unlocks")),
                            "take_reason": snap.get("take_reason"),
                            "reason": "near_complete_unlock_twp",
                            "proposal": d or None,
                        }
                    )
            except Exception as exc:  # pragma: no cover - soft
                note = f"{note}; twp_error:{exc}"

            rates = [4, 4, 4, 4, 4]
            try:
                rates = list(game.get_player_bank_trade_rates(player) or rates)
            except Exception:
                pass
            twb_out = _twb_rows_that_unlock(hand=hand, cost=cost, need=need, rates=rates)

            direct_full = any(bool(t.get("fully_unlocks")) for t in twp_out)
            if not direct_full and not twb_out:
                chains = enumerate_two_leg_unlock_chains(
                    game,
                    player,
                    cost=cost,
                    need=need,
                    hand=hand,
                    support_action=action,
                )
                if chains.get("chosen"):
                    note = f"{note}; chain={chains['chosen'].get('label')}"

        # Mutual-unlock always (R5T4): partner incentive + our need fill
        mutual = enumerate_mutual_unlock_twp(
            game,
            player,
            live_need=need,
            support_cost=cost,
            support_action=action,
        )
        if mutual.get("chosen"):
            note = f"{note}; mutual={mutual['chosen'].get('label')}"

    return {
        "ok": True,
        "wired": True,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "targets": tgt_ids,
        "support_action": action,
        "support_cost": cost,
        "live_need": need,
        "need_units": need_units,
        "hand": hand,
        "twb": twb_out,
        "twp": twp_out,
        "twp_chains": chains,
        "mutual_unlock": mutual,
        "note": note,
    }


def _missing_need_indices(game: Any, player: Any) -> List[int]:
    """Resource indices still short for the live support action."""
    try:
        _act, cost, need = _live_support_need(game, player)
    except Exception:
        return []
    out: List[int] = []
    for i, n in enumerate(list(need or [])[:5]):
        try:
            if int(n or 0) > 0:
                out.append(i)
        except Exception:
            continue
    return out


def _opp_hand_estimate(game: Any, opp: Any, res_idx: int) -> int:
    """Best-effort known/public hand count (0 if unknown)."""
    try:
        fn = getattr(game, "_execution_hand_vector_for_player", None)
        if callable(fn):
            hv = _vec5(fn(opp))
            if 0 <= int(res_idx) < 5:
                return max(0, int(hv[int(res_idx)] or 0))
    except Exception:
        pass
    return 0


def suggest_dcard_touchpoints(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """When Knight/YOP/Monopoly would support race or ≥1 VP (WP-E1).

    Consults ``plan_ai_play_knight`` and live support need. Sets ``knight.want``
    when the planner already plays, LA take/race, or a steal is likely to
    fill a missing settle/road resource from a fat-handed opponent.
    Does not execute — ``ai_play_dcard_choice`` consumes the bag.
    """
    sequence: Dict[str, Any] = {}
    try:
        from core.dcard_optimizer import plan_play_sequence

        sequence = plan_play_sequence(game, player)
    except Exception as exc:  # pragma: no cover
        sequence = {"ok": False, "error": str(exc)}

    knight: Dict[str, Any] = {
        "want": False,
        "reason": "no_signal",
        "play_plan": False,
        "unlock_steal": False,
        "need_indices": [],
        "boost": 0.0,
    }
    yop: Dict[str, Any] = {"want": False, "reason": "unscored"}
    monopoly: Dict[str, Any] = {"want": False, "reason": "unscored"}

    need_idx = _missing_need_indices(game, player)
    knight["need_indices"] = list(need_idx)

    # LA plan signals
    la_take = False
    try:
        la = getattr(player, "la_race_plan", None) or getattr(game, "last_la_race_plan", None)
        if isinstance(la, Mapping):
            lab = str(la.get("label") or "").lower()
            if "take" in lab or bool(la.get("play_knight")):
                la_take = True
    except Exception:
        la_take = False

    kplan: Dict[str, Any] = {}
    try:
        from core.ai_play_knight import plan_ai_play_knight

        kplan = plan_ai_play_knight(game, player, window="post_roll", log=False) or {}
    except Exception as exc:
        kplan = {"play": False, "error": str(exc)}

    if bool(kplan.get("play")):
        knight["want"] = True
        knight["play_plan"] = True
        knight["reason"] = str(kplan.get("reason") or "knight_plan_play")
        knight["boost"] = 10.0
        if la_take or "la" in str(kplan.get("reason") or "").lower():
            knight["boost"] = 14.0
            knight["reason"] = "la_claim_or_race:" + str(knight["reason"])

    # Steal unlock: missing resource for settle/road + opponent likely holds it
    if need_idx and not knight["want"]:
        try:
            players = list(getattr(game, "players", None) or [])
            pid = int(getattr(player, "id", -1) or -1)
            best_ev = 0.0
            best_held = 0
            best_idx = None
            best_opp = None
            for opp in players:
                if opp is None or int(getattr(opp, "id", -2) or -2) == pid:
                    continue
                try:
                    hv = _vec5(getattr(game, "_execution_hand_vector_for_player")(opp))
                    total = max(1, sum(hv))
                except Exception:
                    hv = [0, 0, 0, 0, 0]
                    total = 1
                for ri in need_idx:
                    held = max(0, int(hv[ri] if ri < len(hv) else 0))
                    if held <= 0:
                        continue
                    ev = float(held) / float(total)
                    if ev > best_ev or (ev == best_ev and held > best_held):
                        best_ev = ev
                        best_held = held
                        best_idx = ri
                        best_opp = getattr(opp, "id", None)
            # Dig bar (~67%): EV≥0.35 or held≥2 of the needed type
            if best_idx is not None and (best_ev >= 0.35 or best_held >= 2):
                playable = bool(kplan.get("legal")) or int(
                    kplan.get("playable_knight_count") or 0
                ) > 0
                if playable:
                    knight["want"] = True
                    knight["unlock_steal"] = True
                    knight["boost"] = 12.0
                    abbr = _RESOURCE_ABBR[int(best_idx)]
                    knight["reason"] = (
                        f"unlock_steal:{abbr}:ev={best_ev:.2f}:held={best_held}:opp={best_opp}"
                    )
                    knight["steal_resource_index"] = best_idx
                    knight["steal_opponent_id"] = best_opp
        except Exception as exc:
            knight["steal_error"] = str(exc)

    if la_take and not knight["want"]:
        if bool(kplan.get("legal")) or int(kplan.get("playable_knight_count") or 0) > 0:
            knight["want"] = True
            knight["boost"] = 11.0
            knight["reason"] = "la_plan_take_now"

    # Soft YOP: missing ≥2 need units and sequence prefers YOP
    try:
        head = str((sequence or {}).get("head") or "")
        need_units = sum(
            max(0, int(x or 0)) for x in (_live_support_need(game, player)[2] or [])
        )
        if head == "year_of_plenty" and need_units >= 2:
            yop = {"want": True, "reason": "sequence_head_yop_need", "boost": 6.0}
        if head == "monopoly" and need_units >= 1:
            monopoly = {
                "want": True,
                "reason": "sequence_head_mono_need",
                "boost": 5.0,
            }
    except Exception:
        pass

    return {
        "ok": True,
        "wired": True,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "knight": knight,
        "yop": yop,
        "monopoly": monopoly,
        "dcard_sequence": sequence,
        "knight_plan": {
            "play": bool(kplan.get("play")),
            "legal": bool(kplan.get("legal")),
            "reason": kplan.get("reason"),
        },
        "note": "WP-E1: knight want from plan/LA/steal-unlock; consumed by dcard_choice",
    }


def suggest_combo(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """Combined trade + DCard ideas (e.g. Monopoly → TwB).

    Stub only — illustrative end-game Monopoly+port pattern documented in
    ``strategy_card_coordinator``.
    """
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "combos": [],
        "note": "stub: Monopoly→TwB and similar combos not enumerated yet",
    }


def invent_unlock_twp_offers(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """WP-TWP2: invent live-need unlock TwP (1:1 and directed surplus→need).

    Used when the mutual appetite scanner returns nothing useful. Returns
    proposal objects (``TradeProposal``) plus compact offer dicts for Dig/BA.
    """
    out: Dict[str, Any] = {
        "ok": True,
        "proposals": [],
        "offers": [],
        "fully_unlocks_any": False,
        "note": "wp_twp2_invent",
    }
    try:
        action, cost, need = _live_support_need(game, player)
    except Exception:
        return {**out, "ok": False, "note": "no_live_need"}
    need_v = _vec5(need)
    cost_v = _vec5(cost)
    hand = _hand_vector(game, player)
    need_idx = [i for i, n in enumerate(need_v) if int(n or 0) > 0]
    if not need_idx:
        return {**out, "note": "nothing_missing"}

    # Surplus / ditchable = hand above cost for non-need resources
    surplus_idx: List[int] = []
    for i in range(5):
        if i in need_idx:
            continue
        try:
            if int(hand[i] or 0) > int(cost_v[i] or 0):
                surplus_idx.append(i)
            elif int(hand[i] or 0) > 0 and int(need_v[i] or 0) == 0:
                surplus_idx.append(i)
        except Exception:
            continue

    proposals: List[Any] = []
    try:
        from core.player_trade import (
            find_directed_unlock_twp_proposals,
            find_unlock_twp_proposals,
        )

        base = list(
            find_unlock_twp_proposals(
                game,
                player,
                max_candidates=16,
                include_human_counterparties=True,
                live_need=need_v,
                primary_cost=cost_v,
                primary_action=action or None,
            )
            or []
        )
        proposals.extend(base)
        for gi in surplus_idx:
            for ri in need_idx:
                if gi == ri:
                    continue
                # 1:1 then soft 1:2 / 2:1 directed
                for gc, rc in ((1, 1), (1, 2), (2, 1)):
                    if int(hand[gi] or 0) < gc:
                        continue
                    directed = list(
                        find_directed_unlock_twp_proposals(
                            game,
                            player,
                            give_index=gi,
                            receive_index=ri,
                            live_need=need_v,
                            primary_cost=cost_v,
                            primary_action=action or None,
                            max_candidates=6,
                            include_human_counterparties=True,
                            give_count=gc,
                            receive_count=rc,
                            allow_keep_spend=True,
                        )
                        or []
                    )
                    proposals.extend(directed)
    except Exception as exc:
        return {**out, "ok": False, "note": f"invent_error:{exc}"}

    # Dedup proposals by counterparty + give/get
    seen = set()
    uniq: List[Any] = []
    offers: List[Dict[str, Any]] = []
    def _idx(d: Mapping[str, Any], key: str, default: int = -1) -> int:
        try:
            v = d.get(key)
            if v is None or v == "":
                return int(default)
            return int(v)
        except Exception:
            return int(default)

    for p in proposals:
        try:
            d = p.as_dict() if hasattr(p, "as_dict") else dict(p or {})
        except Exception:
            continue
        key = (
            _idx(d, "counterparty_id", -1),
            _idx(d, "active_give_index", -1),
            max(1, _idx(d, "active_give_count", 1)),
            _idx(d, "active_receive_index", -1),
            max(1, _idx(d, "active_receive_count", 1)),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
        gi, ri = key[1], key[3]
        offers.append(
            {
                "kind": "TwP",
                "counterparty_id": key[0],
                "give_index": gi,
                "give_count": key[2],
                "get_index": ri,
                "get_count": key[4],
                "label": (
                    f"TwP {_RESOURCE_ABBR[gi] if 0 <= gi < 5 else '?'}{key[2]}"
                    f"→{_RESOURCE_ABBR[ri] if 0 <= ri < 5 else '?'}{key[4]}"
                    f" with P{key[0]}"
                ),
                "fully_unlocks": bool(
                    (d.get("market_snapshot") or {}).get("fully_unlocks")
                )
                or str((d.get("market_snapshot") or {}).get("source") or "")
                in ("unlock", "unlock_fallback", "both"),
                "reason": "wp_twp2_invent",
                "proposal": d,
            }
        )

    out["proposals"] = uniq
    out["offers"] = offers
    out["fully_unlocks_any"] = any(bool(o.get("fully_unlocks")) for o in offers)
    out["support_action"] = action
    out["live_need"] = need_v
    out["note"] = f"wp_twp2_invent n={len(uniq)} unlock={out['fully_unlocks_any']}"
    return out


def twp_wait_gate(
    game: Any,
    player: Any,
    *,
    hand: Optional[Sequence[int]] = None,
    unlocks_now: bool = False,
    hand_max_without_unlock: int = 4,
    hand_min_block_appetite: int = 8,
) -> Dict[str, Any]:
    """WP-TWP2 + WP-RISK1 TwP gates.

    - Small hand (≤4) + no unlock → wait (Dig White R4T3).
    - Large hand (≥8) + no unlock → soft-block appetite TwP (Dig discard risk).
    """
    hv = _vec5(hand if hand is not None else _hand_vector(game, player))
    total = int(sum(hv))
    unlocks = bool(unlocks_now)
    wait_small = bool(total <= int(hand_max_without_unlock) and not unlocks)
    block_appetite = bool(total >= int(hand_min_block_appetite) and not unlocks)
    wait = bool(wait_small or block_appetite)
    reason = "ok"
    if wait_small:
        reason = "wp_twp2_wait_small_hand"
    elif block_appetite:
        reason = "wp_risk1_block_appetite_twp"
    return {
        "ok": True,
        "wait": wait,
        "hand_total": total,
        "unlocks_now": unlocks,
        "threshold": int(hand_max_without_unlock),
        "appetite_threshold": int(hand_min_block_appetite),
        "wait_small": wait_small,
        "block_appetite": block_appetite,
        "reason": reason,
    }


def optimize_rcard_actions(
    game: Any,
    player: Any,
    *,
    targets: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Façade: Optimizing RCards — trades, mutual unlock, chains, DCard touchpoints.

    BA / TwP planners should consult this bag generically rather than special-case
    board stories. Preferred TwP order: mutual full unlock → near-complete unlock
    → two-leg chain → invent → other fills. Each mutual plain offer carries a
    sweetener sibling for decline escalation (1 resource first, +Wh second).
    """
    trades = suggest_trades_for_targets(game, player, targets)
    dc = suggest_dcard_touchpoints(game, player)
    combo = suggest_combo(game, player)
    invented = invent_unlock_twp_offers(game, player)

    preferred_twp: List[Dict[str, Any]] = []
    mutual = trades.get("mutual_unlock") or {}
    if isinstance(mutual, Mapping):
        for off in list(mutual.get("offers") or []):
            if isinstance(off, Mapping):
                preferred_twp.append(dict(off))
    for row in list(trades.get("twp") or []):
        if isinstance(row, Mapping):
            preferred_twp.append(dict(row))
    chain_chosen = (trades.get("twp_chains") or {}).get("chosen")
    if isinstance(chain_chosen, Mapping):
        preferred_twp.append(dict(chain_chosen))
    for row in list(invented.get("offers") or []):
        if isinstance(row, Mapping):
            preferred_twp.append(dict(row))

    # Dedup by (cid, give, get)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for row in preferred_twp:
        key = (
            row.get("counterparty_id"),
            row.get("give_index"),
            row.get("get_index"),
            row.get("kind"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return {
        "ok": True,
        "wired": bool(trades.get("wired")),
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "trades": trades,
        "invented": invented,
        "preferred_twp": deduped,
        "preferred_twb": list(trades.get("twb") or []),
        "dcard_touchpoints": dc,
        "combo": combo,
        "note": trades.get("note"),
    }


# Alias used in operator language
optimize_rcards = optimize_rcard_actions


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "ACTION_COSTS",
    "actions_affordable",
    "counterparty_trade_incentive",
    "plain_then_sweetener_pair",
    "enumerate_mutual_unlock_twp",
    "enumerate_two_leg_unlock_chains",
    "suggest_trades_for_targets",
    "suggest_dcard_touchpoints",
    "suggest_combo",
    "invent_unlock_twp_offers",
    "twp_wait_gate",
    "optimize_rcard_actions",
    "optimize_rcards",
]
