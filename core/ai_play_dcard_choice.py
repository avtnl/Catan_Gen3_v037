"""AI cross-card DCard chooser (PR0 shell + PR1–PR4 scoring).

Pipeline:
  1. Plan legal DCards for the window (post_roll: all four; pre_roll: Knight only)
  2. Assign tier + normalized scores (PR1)
  3. Preferred-way / race boosts (PR3)
  4. Score HOLD with option value + VP-bluff pressure (PR2)
  5. Pick max norm_score; execute at most one (or none)

API:
  plan_ai_dcard_choice(game, window=...) -> choice dict
  maybe_execute_ai_dcard_choice(game, window=...) -> choice + execute_result
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

STAGE = "chooser_pr1_pr4_phase_b"

CARD_ORDER: Tuple[str, ...] = (
    "knight",
    "two_free_roads",
    "year_of_plenty",
    "monopoly",
)

# Pre-roll sub-chooser (PR4): only Knight is rules-legal to play before dice.
PRE_ROLL_ALLOWED: Tuple[str, ...] = ("knight",)

REASON_NONE_LEGAL = "none_legal"
REASON_HOLD_NONE_WANT_PLAY = "hold_none_want_play"
REASON_HOLD_BLUFF_VP = "hold_bluff_vp_pressure"
REASON_HOLD_OPTION = "hold_option_value"
REASON_MAX_SCORE = "max_score"
REASON_ALREADY_PLAYED = "already_played_dcard_this_turn"
REASON_WRONG_WINDOW = "chooser_unsupported_window"
REASON_FIRST_PLAY_FIXED_ORDER = "first_play_fixed_order"  # legacy alias unused

# PR1 tier ladder
TIER_POINTS = {
    "win_now": 100.0,
    "crit": 80.0,
    "strong": 55.0,
    "soft": 35.0,
    "weak": 15.0,
    "hold_plan": 0.0,
}

# Map plan reasons → tier (substring / exact)
REASON_TIER: Dict[str, str] = {
    # Knight
    "la_crit": "crit",
    "unblock_self": "crit",
    "meta_self_blocked_promote_pre_roll": "crit",
    "la_race": "strong",
    "deny_leader": "strong",
    "score_play": "soft",
    "hold_detention": "hold_plan",
    "hold_for_seven": "hold_plan",
    "hold_default": "hold_plan",
    "hold_weak_targets": "hold_plan",
    "skeleton_hold": "hold_plan",
    # TFR
    "s_crit": "crit",
    "lr_crit": "crit",
    "early_path": "strong",
    "settle_path": "soft",
    "hold_early": "hold_plan",
    "hold_alt_dcard": "hold_plan",
    "hold_weak_path": "hold_plan",
    # YOP
    "c_crit": "crit",
    "c_soft": "soft",
    "hold_no_shortfall": "hold_plan",
    "hold_bank_covers": "hold_plan",
    "hold_yop_for_dcard": "hold_plan",
    # Monopoly
    "m_crit": "crit",
    "strip_absolute_jackpot": "crit",
    "strip_leader_hoard": "strong",
    "strip_jackpot": "strong",
    "strip_solid": "soft",
    "hold_thin_strip": "hold_plan",
    # Knight Phase A
    "hold_la_delay": "hold_plan",
    "hold_low_value_hex": "hold_plan",
    "hold_for_winning_post_roll_dcard": "hold_plan",
}

# Phase A/B shape / early / same-turn timing boosts (norm_score deltas)
SHAPE_TFR_BOOST = 10.0
SHAPE_YOP_BOOST = 8.0
EARLY_TFR_OVER_KNIGHT = 14.0
EARLY_KNIGHT_DEMOTE = 10.0
# Phase B: same-turn VP conversion gate
SAME_TURN_CONVERT_BOOST = 12.0
SAME_TURN_SWING_BOOST = 6.0
SAME_TURN_SOFT_PENALTY = 10.0  # late soft non-converting plays
WIN_NOW_VP_FLOOR = 9
# W4: extra push when projected effective_vp + action ≥ VICTORY
WIN_NOW_PROJECTED_EXTRA = 20.0

# Preferred-way affinity: direction hint → favored cards
WAY_CARD_BOOST: Dict[str, Tuple[str, ...]] = {
    "la": ("knight", "year_of_plenty", "monopoly"),
    "lr": ("two_free_roads", "knight"),
    "city": ("year_of_plenty", "monopoly", "knight"),
    "settle": ("two_free_roads", "year_of_plenty", "monopoly"),
    "expand": ("two_free_roads", "year_of_plenty"),
    "road": ("two_free_roads",),
}

LATE_VP = 8
CONTENDER_GAP = 2
BLUFF_B0 = 10.0
CRIT_HOLD_PENALTY = 40.0
STRONG_HOLD_PENALTY = 15.0
SOFT_ONLY_HOLD_BOOST = 14.0


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


def _vp(player: Any) -> int:
    """VP for chooser win_now math (W4: max of stored + effective_vp)."""
    try:
        from core.ai_dcard_timing import victory_points

        return int(victory_points(player))
    except Exception:
        pass
    for attr in ("victory_points", "points"):
        try:
            return int(getattr(player, attr) or 0)
        except Exception:
            pass
    return 0


def _dcard_already_played(game: Any) -> bool:
    for attr in ("myturn", "turn_details"):
        try:
            td = getattr(game, attr, None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                return True
        except Exception:
            pass
    return False


def _hidden_dcard_count(player: Any) -> int:
    """Public-ish count of face-down DCards (playable + new)."""
    if player is None:
        return 0
    total = 0
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            row_list = list(row or [])
            if not row_list:
                continue
            name = str(row_list[0])
            if name == "victory_point":
                # VP stays hidden forever; still counts as "unknown threat"
                while len(row_list) < 4:
                    row_list.append(0)
                total += max(0, int(row_list[1] or 0)) + max(0, int(row_list[2] or 0))
                # played VP often in col3; don't double-count
                continue
            while len(row_list) < 4:
                row_list.append(0)
            total += max(0, int(row_list[1] or 0)) + max(0, int(row_list[2] or 0))
        if total > 0:
            return total
    except Exception:
        pass
    try:
        return len(list(getattr(player, "development_cards", []) or []))
    except Exception:
        return 0


def _preferred_way_tags(player: Any) -> Set[str]:
    tags: Set[str] = set()
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return tags
    if bool(direction.get("biggest_army") or direction.get("largest_army")):
        tags.add("la")
    if bool(direction.get("longest_road") or direction.get("longest_route")):
        tags.add("lr")
    for key in (
        "supporting_action_type",
        "preferred_action_type",
        "action_type",
        "preferred_action",
    ):
        raw = str(direction.get(key) or "").lower()
        if "city" in raw:
            tags.add("city")
        if "settle" in raw:
            tags.add("settle")
            tags.add("expand")
        if "road" in raw:
            tags.add("road")
            tags.add("expand")
        if "dcard" in raw or "development" in raw or "army" in raw:
            tags.add("la")
    return tags


def reason_to_tier(reason: str) -> str:
    r = str(reason or "").strip().lower()
    if r in REASON_TIER:
        return REASON_TIER[r]
    # substring fallbacks
    if "crit" in r:
        return "crit"
    if "jackpot" in r:
        return "strong"
    if "hold" in r:
        return "hold_plan"
    if "soft" in r or "path" in r or "solid" in r:
        return "soft"
    if r.startswith("la_") or r.startswith("s_") or r.startswith("c_") or r.startswith("m_"):
        return "strong"
    return "weak"


def normalize_play_score(
    card: str,
    plan: Mapping[str, Any],
    *,
    way_tags: Optional[Set[str]] = None,
    vp_ai: int = 0,
    max_opp_vp: int = 0,
    shape: Optional[Mapping[str, Any]] = None,
    early_game: bool = False,
) -> Dict[str, Any]:
    """PR1 tier + residual + PR3 way/race + Phase A/B shape/early/same-turn."""
    from core.ai_dcard_timing import same_turn_convert_info

    reason = str(plan.get("reason") or "")
    tier = reason_to_tier(reason)
    raw = _safe_float(plan.get("score"), 0.0)
    residual = 0.1 * max(0.0, min(20.0, raw))
    base = float(TIER_POINTS.get(tier, 0.0)) + residual

    way_tags = way_tags or set()
    way_boost = 0.0
    for tag in way_tags:
        favored = WAY_CARD_BOOST.get(tag) or ()
        if card in favored:
            way_boost = max(way_boost, 12.0 if tag in {"la", "city", "lr"} else 8.0)
    base += way_boost

    race_boost = 0.0
    late = max(vp_ai, max_opp_vp) >= LATE_VP
    if late and tier in {"crit", "strong", "win_now"}:
        race_boost = 10.0
    elif late and tier == "soft":
        race_boost = 4.0
    base += race_boost

    shape = shape or {}
    shape_boost = 0.0
    # Shape boosts resolve TFR vs YOP when both are viable; do not inflate
    # soft-only plays enough to beat HOLD bluff (see test_hold_bluff_late_soft_only).
    if tier in {"crit", "strong", "win_now"} or any(
        k in reason for k in ("s_crit", "lr_crit", "early_path", "settle_path", "c_crit")
    ):
        if bool(shape.get("wood_brick_shape")) and card == "two_free_roads":
            shape_boost = SHAPE_TFR_BOOST
        elif bool(shape.get("multi_type_yop")) and card == "year_of_plenty":
            shape_boost = SHAPE_YOP_BOOST
    base += shape_boost

    early_boost = 0.0
    if early_game:
        # Early expand: favor TFR over soft knights (unless knight is crit LA/unblock)
        if card == "two_free_roads" and tier in {"soft", "strong", "crit"}:
            early_boost = EARLY_TFR_OVER_KNIGHT * 0.65
        if card == "knight" and tier in {"soft", "weak"}:
            early_boost = -EARLY_KNIGHT_DEMOTE
        # Non-LA strong knights early (score/deny soft) — mild demote
        if (
            card == "knight"
            and tier in {"crit", "strong"}
            and "la" not in reason
            and "unblock" not in reason
            and "meta" not in reason
        ):
            if "deny" not in reason:
                early_boost = min(early_boost, -EARLY_KNIGHT_DEMOTE * 0.6)
    base += early_boost

    # Phase B / W4: same-turn VP / swing conversion gate (effective_vp based)
    convert = same_turn_convert_info(card, plan, vp_ai=vp_ai)
    convert_boost = 0.0
    if bool(convert.get("win_now")):
        tier = "win_now"
        convert_boost = SAME_TURN_CONVERT_BOOST + WIN_NOW_PROJECTED_EXTRA
    elif bool(convert.get("converts_vp")):
        convert_boost = SAME_TURN_CONVERT_BOOST
        if tier == "soft":
            tier = "strong"  # promote converting softs
        # Near-threshold convert: promote toward win_now when one VP short
        try:
            thr = int(convert.get("threshold") or 10)
            if int(vp_ai) + max(int(convert.get("vp_delta_est") or 0), 1) >= thr:
                tier = "win_now"
                convert_boost = SAME_TURN_CONVERT_BOOST + WIN_NOW_PROJECTED_EXTRA
        except Exception:
            pass
    elif bool(convert.get("swing")) and tier in {"soft", "strong"}:
        convert_boost = SAME_TURN_SWING_BOOST
    elif (
        late
        and tier == "soft"
        and not bool(convert.get("converts_vp"))
        and not bool(convert.get("swing"))
        and card in {"year_of_plenty", "two_free_roads", "monopoly"}
    ):
        # Soft non-converting economic plays late → prefer HOLD
        convert_boost = -SAME_TURN_SOFT_PENALTY
    base += convert_boost

    # win_now: converting crit near victory, or convert.win_now
    if tier == "crit" and vp_ai >= WIN_NOW_VP_FLOOR:
        tier = "win_now"
    if tier == "win_now":
        base = (
            float(TIER_POINTS["win_now"])
            + residual
            + way_boost
            + race_boost
            + shape_boost
            + early_boost
            + max(0.0, convert_boost)
        )

    return {
        "tier": tier,
        "norm_score": round(base, 3),
        "way_boost": way_boost,
        "race_boost": race_boost,
        "shape_boost": shape_boost,
        "early_boost": early_boost,
        "convert_boost": convert_boost,
        "converts_vp": bool(convert.get("converts_vp")),
        "same_turn_win_now": bool(convert.get("win_now") or tier == "win_now"),
        "projected_vp": convert.get("projected_vp"),
        "raw_score": raw,
        "reason": reason,
    }


def score_hold_dcard(
    game: Any,
    player: Any,
    play_candidates: Sequence[Mapping[str, Any]],
    *,
    vp_ai: int,
    max_opp_vp: int,
) -> Dict[str, Any]:
    """PR2: option value + VP-bluff pressure, with crit penalties."""
    hidden = _hidden_dcard_count(player)
    n_playable_types = sum(
        1
        for c in play_candidates
        if bool(c.get("legal")) and bool(c.get("play")) and str(c.get("card")) != "HOLD"
    )
    # Count distinct legal playable plans even if play=False (option)
    n_legal_types = sum(
        1 for c in play_candidates if bool(c.get("legal")) and str(c.get("card")) != "HOLD"
    )

    option = 2.0
    if n_legal_types >= 2:
        option = 8.0
    elif n_legal_types == 1:
        option = 5.0
    if vp_ai <= 3:
        option += 2.0  # early option value

    # Soft-only board → boost hold
    best_tier = "hold_plan"
    for c in play_candidates:
        if not bool(c.get("play")):
            continue
        t = str(c.get("tier") or "weak")
        if TIER_POINTS.get(t, 0) > TIER_POINTS.get(best_tier, 0):
            best_tier = t
    if best_tier in {"soft", "weak", "hold_plan"}:
        option += SOFT_ONLY_HOLD_BOOST

    # Bluff VP pressure
    late_factor = 0.0
    peak = max(vp_ai, max_opp_vp)
    if peak >= LATE_VP:
        late_factor = 1.0
    elif peak >= 6:
        late_factor = 0.5
    elif peak >= 4:
        late_factor = 0.1

    contender = 1.0 if vp_ai >= max_opp_vp - CONTENDER_GAP else 0.4
    bluff = 0.0
    if hidden > 0 and late_factor > 0:
        bluff = BLUFF_B0 * min(hidden, 3) * late_factor * contender

    hold = option + bluff
    reason = REASON_HOLD_OPTION
    if bluff >= option and bluff > 0:
        reason = REASON_HOLD_BLUFF_VP

    # Crit / strong plays heavily penalize holding
    if best_tier in {"win_now", "crit"}:
        hold -= CRIT_HOLD_PENALTY
    elif best_tier == "strong":
        hold -= STRONG_HOLD_PENALTY

    # If nobody wants to play, HOLD is free win
    if n_playable_types == 0:
        hold = max(hold, 50.0)
        reason = REASON_HOLD_NONE_WANT_PLAY

    return {
        "card": "HOLD",
        "legal": True,
        "play": False,
        "tier": "hold_plan",
        "norm_score": round(hold, 3),
        "reason": reason,
        "raw_score": hold,
        "option_value": option,
        "bluff_vp_pressure": bluff,
        "hidden_dcards": hidden,
        "late_factor": late_factor,
        "best_play_tier": best_tier,
        "plan": None,
    }


def _plan_cards(
    game: Any,
    player: Any,
    *,
    window: str,
    allowed: Sequence[str],
) -> List[Dict[str, Any]]:
    """Call per-card planners for allowed types."""
    candidates: List[Dict[str, Any]] = []
    planners: Dict[str, Callable[..., Dict[str, Any]]] = {}
    try:
        from core.ai_play_knight import plan_ai_play_knight

        planners["knight"] = plan_ai_play_knight
    except Exception:
        pass
    try:
        from core.ai_play_tfr import plan_ai_play_tfr

        planners["two_free_roads"] = plan_ai_play_tfr
    except Exception:
        pass
    try:
        from core.ai_play_yop import plan_ai_play_yop

        planners["year_of_plenty"] = plan_ai_play_yop
    except Exception:
        pass
    try:
        from core.ai_play_monopoly import plan_ai_play_monopoly

        planners["monopoly"] = plan_ai_play_monopoly
    except Exception:
        pass

    for card in allowed:
        fn = planners.get(card)
        if fn is None:
            candidates.append(
                {
                    "card": card,
                    "legal": False,
                    "play": False,
                    "reason": "planner_unavailable",
                    "raw_score": None,
                    "norm_score": 0.0,
                    "tier": "hold_plan",
                    "plan": None,
                }
            )
            continue
        try:
            plan = fn(game, player, window=window, log=False)
        except TypeError:
            try:
                plan = fn(game, window=window, log=False)
            except Exception as exc:
                candidates.append(
                    {
                        "card": card,
                        "legal": False,
                        "play": False,
                        "reason": f"plan_error:{exc}",
                        "raw_score": None,
                        "norm_score": 0.0,
                        "tier": "hold_plan",
                        "plan": None,
                    }
                )
                continue
        except Exception as exc:
            candidates.append(
                {
                    "card": card,
                    "legal": False,
                    "play": False,
                    "reason": f"plan_error:{exc}",
                    "raw_score": None,
                    "norm_score": 0.0,
                    "tier": "hold_plan",
                    "plan": None,
                }
            )
            continue

        plan = dict(plan or {})
        candidates.append(
            {
                "card": card,
                "legal": bool(plan.get("legal")),
                "play": bool(plan.get("play")),
                "reason": str(plan.get("reason") or ""),
                "raw_score": plan.get("score"),
                "timing": plan.get("timing"),
                "plan": plan,
            }
        )
    return candidates


def _enrich_candidates(
    game: Any,
    player: Any,
    candidates: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Add norm_score / tier and build HOLD row."""
    from core.ai_dcard_timing import resource_shape_hint, trade_rates_vector5, virtual_vp

    # S-LR-E / S-LA-E: refresh coach lists for soft bias this chooser pass
    try:
        from core.ai_lr_project import (
            build_lr_turn_suggestions,
            get_stored_lr_project,
            pick_turn_focus,
        )

        foc = None
        try:
            foc = pick_turn_focus(game, player).get("focus")
        except Exception:
            foc = None
        if get_stored_lr_project(player, game):
            build_lr_turn_suggestions(game, player, focus=str(foc) if foc else None)
        try:
            from core.ai_la_progress import (
                build_la_turn_suggestions,
                get_stored_la_progress,
            )

            if get_stored_la_progress(player, game):
                build_la_turn_suggestions(
                    game, player, focus=str(foc) if foc else None
                )
        except Exception:
            pass
    except Exception:
        pass

    vp_ai = _vp(player)
    max_opp = 0
    max_opp_vvp = 0
    pid = _safe_player_id(player)
    for opp in list(getattr(game, "players", []) or []):
        if opp is None or _safe_player_id(opp) == pid:
            continue
        max_opp = max(max_opp, _vp(opp))
        max_opp_vvp = max(max_opp_vvp, virtual_vp(opp))
    # Soft VP threat for late race boosts
    max_opp_eff = max(max_opp, max_opp_vvp - 1)
    way_tags = _preferred_way_tags(player)
    early_game = vp_ai <= 3

    shape: Dict[str, Any] = {}
    try:
        from core.ai_play_yop import hand_vector5

        hand = hand_vector5(player)
        rates = trade_rates_vector5(game, player)
        prefer_settle = "settle" in way_tags or "expand" in way_tags
        prefer_city = "city" in way_tags
        prefer_road = "lr" in way_tags or "road" in way_tags
        prefer_dcard = "la" in way_tags
        shape = resource_shape_hint(
            hand,
            prefer_settle=prefer_settle,
            prefer_city=prefer_city,
            prefer_road=prefer_road,
            prefer_dcard=prefer_dcard,
            trade_rates=rates,
        )
    except Exception:
        shape = {}

    enriched: List[Dict[str, Any]] = []
    for row in candidates:
        plan = row.get("plan") if isinstance(row.get("plan"), Mapping) else {}
        if bool(row.get("play")) and bool(row.get("legal")):
            norm = normalize_play_score(
                str(row.get("card")),
                plan or {"reason": row.get("reason"), "score": row.get("raw_score")},
                way_tags=way_tags,
                vp_ai=vp_ai,
                max_opp_vp=max_opp_eff,
                shape=shape,
                early_game=early_game,
            )
            # Extra early: if TFR is playable, boost TFR further (Phase B polish)
            card = str(row.get("card") or "")
            if early_game and card == "two_free_roads" and bool(row.get("play")):
                if str(norm.get("tier")) in {"soft", "strong", "crit"}:
                    extra = EARLY_TFR_OVER_KNIGHT * 0.55
                    norm["norm_score"] = round(float(norm["norm_score"]) + extra, 3)
                    norm["early_boost"] = float(norm.get("early_boost") or 0) + extra
            # S-LR-B: LR-crit TFR (project claims) outranks soft knights
            if card == "two_free_roads" and bool(row.get("play")):
                plan_f = plan if isinstance(plan, Mapping) else {}
                feats = plan_f.get("features") if isinstance(plan_f.get("features"), Mapping) else {}
                if bool(
                    plan_f.get("lr_takes_now")
                    or feats.get("lr_crit")
                    or feats.get("lr_takes_now")
                    or str(plan_f.get("reason") or "") == "lr_crit"
                ):
                    slr_boost = 12.0
                    norm["norm_score"] = round(float(norm.get("norm_score") or 0) + slr_boost, 3)
                    norm["slr_tfr_boost"] = slr_boost
                    if str(norm.get("tier") or "") in {"", "soft", "hold"}:
                        norm["tier"] = "crit"
            # S-LR-E: soft bias from top turn suggestion when focus is LR
            # S-LR-C: LA race knight boost; dense-pack city YOP boost
            try:
                top_act = None
                focus = None
                dense_pack = False
                la_race = False
                sug = getattr(game, "last_lr_turn_suggestions", None)
                if not sug:
                    sug = getattr(player, "lr_turn_suggestions", None)
                if isinstance(sug, list) and sug:
                    top = sug[0] if isinstance(sug[0], Mapping) else {}
                    if not top.get("secondary"):
                        top_act = str(top.get("action") or "")
                d = getattr(player, "strategic_direction", None) or {}
                if isinstance(d, Mapping):
                    focus = str(d.get("turn_focus") or "")
                    dense_pack = bool(d.get("dense_pack"))
                    la_race = bool(d.get("la_race"))
                if not focus:
                    try:
                        from core.ai_lr_project import pick_turn_focus

                        fi = pick_turn_focus(game, player)
                        focus = str(fi.get("focus") or "")
                        dense_pack = bool(fi.get("dense_pack"))
                        la_race = bool(fi.get("la_race"))
                    except Exception:
                        pass
                if focus == "lr" or top_act:
                    if card == "two_free_roads" and top_act == "play_tfr" and bool(row.get("play")):
                        norm["norm_score"] = round(float(norm.get("norm_score") or 0) + 8.0, 3)
                        norm["slr_e_boost"] = "play_tfr"
                    elif card == "year_of_plenty" and top_act == "play_yop_road_res" and bool(row.get("play")):
                        norm["norm_score"] = round(float(norm.get("norm_score") or 0) + 7.0, 3)
                        norm["slr_e_boost"] = "play_yop_road_res"
                    elif card == "monopoly" and top_act and top_act.startswith("play_mono") and bool(row.get("play")):
                        norm["norm_score"] = round(float(norm.get("norm_score") or 0) + 6.0, 3)
                        norm["slr_e_boost"] = top_act
                # S-LA-E: soft bias from top LA suggestion (small; avoid double-count with C)
                try:
                    la_top = None
                    la_sug = getattr(game, "last_la_turn_suggestions", None)
                    if not la_sug:
                        la_sug = getattr(player, "la_turn_suggestions", None)
                    if isinstance(la_sug, list) and la_sug:
                        top_la = la_sug[0] if isinstance(la_sug[0], Mapping) else {}
                        if not top_la.get("secondary"):
                            la_top = str(top_la.get("action") or "")
                    if la_top and bool(row.get("play")):
                        if card == "knight" and la_top in {
                            "play_knight_take",
                            "play_knight_race",
                            "play_knight_robber",
                        }:
                            # Only +3 if S-LR-C did not already boost heavily
                            if not norm.get("slr_c_boost"):
                                norm["norm_score"] = round(
                                    float(norm.get("norm_score") or 0) + 8.0, 3
                                )
                                norm["sla_e_boost"] = la_top
                            else:
                                norm["norm_score"] = round(
                                    float(norm.get("norm_score") or 0) + 2.0, 3
                                )
                                norm["sla_e_boost"] = la_top + "_addon"
                        elif card == "year_of_plenty" and la_top == "play_yop_owg":
                            norm["norm_score"] = round(
                                float(norm.get("norm_score") or 0) + 6.0, 3
                            )
                            norm["sla_e_boost"] = "play_yop_owg"
                        elif card == "monopoly" and la_top == "play_mono_ore":
                            norm["norm_score"] = round(
                                float(norm.get("norm_score") or 0) + 5.0, 3
                            )
                            norm["sla_e_boost"] = "play_mono_ore"
                except Exception:
                    pass
                # S-LR-C: when LA race is BA focus, elevate knight over soft LR path cards
                if (focus == "la" or la_race) and card == "knight" and bool(row.get("play")):
                    k_reason = str(row.get("reason") or plan.get("reason") or "")
                    if "la" in k_reason or str(norm.get("tier") or "") in {
                        "crit",
                        "strong",
                        "soft",
                        "win_now",
                    }:
                        la_boost = 9.0 if focus == "la" else 5.0
                        norm["norm_score"] = round(float(norm.get("norm_score") or 0) + la_boost, 3)
                        norm["slr_c_boost"] = "la_race_knight"
                # S-LR-C: dense pack + city focus → light YOP bias toward city resources
                if (
                    dense_pack
                    and focus == "city"
                    and card == "year_of_plenty"
                    and bool(row.get("play"))
                ):
                    plan_f = plan if isinstance(plan, Mapping) else {}
                    tgt = str(
                        plan_f.get("target_action")
                        or (plan_f.get("features") or {}).get("target_action")
                        or ""
                    ).lower()
                    if "city" in tgt or not tgt:
                        yop_boost = 4.0
                        norm["norm_score"] = round(float(norm.get("norm_score") or 0) + yop_boost, 3)
                        norm["slr_c_boost"] = "dense_city_yop"
                # S-LR-C: when focus=la, soft demote non-crit TFR so knight can win
                if focus == "la" and card == "two_free_roads" and bool(row.get("play")):
                    plan_f = plan if isinstance(plan, Mapping) else {}
                    feats = plan_f.get("features") if isinstance(plan_f.get("features"), Mapping) else {}
                    if not (
                        plan_f.get("lr_takes_now")
                        or feats.get("lr_crit")
                        or feats.get("lr_takes_now")
                    ):
                        demote = 6.0
                        norm["norm_score"] = round(float(norm.get("norm_score") or 0) - demote, 3)
                        norm["slr_c_demote"] = "la_over_soft_tfr"
            except Exception:
                pass
            out = dict(row)
            out.update(norm)
            enriched.append(out)
        else:
            out = dict(row)
            out["tier"] = reason_to_tier(str(row.get("reason") or ""))
            out["norm_score"] = 0.0 if not bool(row.get("play")) else float(
                TIER_POINTS.get(out["tier"], 0)
            )
            out["way_boost"] = 0.0
            out["race_boost"] = 0.0
            out["convert_boost"] = 0.0
            enriched.append(out)

    # Phase B: pairwise early TFR ≻ non-crit Knight when both want play
    if early_game:
        tfr_row = next(
            (
                r
                for r in enriched
                if str(r.get("card")) == "two_free_roads"
                and bool(r.get("play"))
                and bool(r.get("legal"))
            ),
            None,
        )
        k_row = next(
            (
                r
                for r in enriched
                if str(r.get("card")) == "knight"
                and bool(r.get("play"))
                and bool(r.get("legal"))
            ),
            None,
        )
        if tfr_row is not None and k_row is not None:
            k_reason = str(k_row.get("reason") or "")
            k_tier = str(k_row.get("tier") or "")
            # Keep LA-crit / unblock / meta / deny above TFR
            knight_forced = any(
                x in k_reason
                for x in ("la_crit", "unblock", "meta", "deny_leader", "la_race")
            ) or k_tier == "win_now"
            if not knight_forced:
                # Ensure TFR wins head-to-head early
                k_score = _safe_float(k_row.get("norm_score"), 0)
                t_score = _safe_float(tfr_row.get("norm_score"), 0)
                if t_score <= k_score:
                    bump = (k_score - t_score) + 3.0
                    tfr_row["norm_score"] = round(t_score + bump, 3)
                    tfr_row["early_boost"] = float(tfr_row.get("early_boost") or 0) + bump
                    tfr_row["early_tfr_over_knight"] = True
                # Soft demote knight further when expand preferred
                if "expand" in way_tags or "settle" in way_tags or "lr" in way_tags:
                    k_row["norm_score"] = round(
                        _safe_float(k_row.get("norm_score"), 0) - EARLY_KNIGHT_DEMOTE * 0.4,
                        3,
                    )
                    k_row["early_boost"] = float(k_row.get("early_boost") or 0) - (
                        EARLY_KNIGHT_DEMOTE * 0.4
                    )

    # WP4: soft knight vs TFR bias from race plans (after early pairwise polish)
    wp4_policy: Dict[str, Any] = {}
    try:
        from core.specials_race_plans import (
            apply_knight_tfr_policy_to_candidates,
            prefer_knight_before_tfr,
            refresh_specials_race_plans,
        )

        policy = getattr(player, "knight_tfr_policy", None)
        if not isinstance(policy, Mapping) or policy.get("prefer_knight") is None:
            # Ensure plans exist for this chooser pass (cheap if already refreshed)
            if not getattr(player, "lr_race_plan", None) and not getattr(
                player, "la_race_plan", None
            ):
                refresh_specials_race_plans(
                    game, player, reason="dcard_chooser", apply_sticky=False
                )
            policy = prefer_knight_before_tfr(
                game,
                player,
                lr_plan=getattr(player, "lr_race_plan", None),
                la_plan=getattr(player, "la_race_plan", None),
            )
            try:
                player.knight_tfr_policy = dict(policy)
            except Exception:
                pass
        if isinstance(policy, Mapping):
            wp4_policy = dict(policy)
            enriched = apply_knight_tfr_policy_to_candidates(enriched, policy)
    except Exception:
        wp4_policy = {}

    hold = score_hold_dcard(
        game,
        player,
        enriched,
        vp_ai=vp_ai,
        max_opp_vp=max_opp,
    )
    # Phase B: when best play is soft non-converting late, HOLD already boosted via
    # SOFT_ONLY_HOLD_BOOST; convert_boost penalty on soft cards aids this.

    ctx = {
        "vp_ai": vp_ai,
        "max_opp_vp": max_opp,
        "max_opp_virtual_vp": max_opp_vvp,
        "way_tags": sorted(way_tags),
        "hidden_dcards": hold.get("hidden_dcards"),
        "shape": dict(shape) if shape else {},
        "early_game": early_game,
        "phase_a_timing": True,
        "phase_b_polish": True,
        "knight_tfr_policy": wp4_policy or None,
    }
    return enriched + [hold], ctx


def _pick_max_score(candidates: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Pick highest norm_score; ties: higher tier, then CARD_ORDER, HOLD last."""
    tier_rank = {k: i for i, k in enumerate(["hold_plan", "weak", "soft", "strong", "crit", "win_now"])}
    card_rank = {c: i for i, c in enumerate(CARD_ORDER)}
    card_rank["HOLD"] = 99

    def key(row: Mapping[str, Any]):
        return (
            _safe_float(row.get("norm_score"), -1e9),
            tier_rank.get(str(row.get("tier") or "hold_plan"), 0),
            -card_rank.get(str(row.get("card") or "HOLD"), 50),
        )

    best = None
    best_k = None
    for row in candidates:
        # Only HOLD or play=True compete for winning execute
        if str(row.get("card")) != "HOLD" and not bool(row.get("play")):
            continue
        if str(row.get("card")) != "HOLD" and not bool(row.get("legal")):
            continue
        k = key(row)
        if best is None or k > best_k:
            best = dict(row)
            best_k = k
    if best is None:
        return {
            "card": "HOLD",
            "legal": True,
            "play": False,
            "reason": REASON_NONE_LEGAL,
            "norm_score": 0.0,
            "tier": "hold_plan",
            "plan": None,
        }
    return best


def plan_ai_dcard_choice(
    game: Any,
    player: Any = None,
    *,
    window: str = "post_roll",
    log: bool = True,
    allowed_cards: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Plan which DCard (if any) to play this window using normalized scores."""
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    window = str(window or "post_roll")
    choice: Dict[str, Any] = {
        "ok": True,
        "action": "plan_ai_dcard_choice",
        "stage": STAGE,
        "window": window,
        "player_id": _safe_player_id(player),
        "play": False,
        "chosen": None,
        "reason": REASON_HOLD_NONE_WANT_PLAY,
        "score": None,
        "candidates": [],
        "executed": False,
        "execute_result": None,
        "context": {},
        "notes": (
            "PR1–PR4: tier normalization, HOLD bluff/option, preferred-way boosts; "
            "pre_roll = Knight-only sub-chooser."
        ),
    }

    if window not in ("post_roll", "pre_roll"):
        choice["reason"] = REASON_WRONG_WINDOW
        if log:
            _log_choice(game, choice)
        return choice

    if _dcard_already_played(game):
        choice["reason"] = REASON_ALREADY_PLAYED
        if log:
            _log_choice(game, choice)
        return choice

    if allowed_cards is not None:
        allowed = tuple(str(c) for c in allowed_cards)
    elif window == "pre_roll":
        allowed = PRE_ROLL_ALLOWED
    else:
        allowed = CARD_ORDER

    raw_cands = _plan_cards(game, player, window=window, allowed=allowed)
    candidates, ctx = _enrich_candidates(game, player, raw_cands)
    # WP-E1/F: rcard touchpoints boost Knight (LA claim / steal unlock settle)
    try:
        from core.rcard_optimizer import suggest_dcard_touchpoints

        tp = suggest_dcard_touchpoints(game, player)
        ctx["rcard_dcard_touchpoints"] = tp
        kbag = (tp or {}).get("knight") if isinstance(tp, Mapping) else {}
        if isinstance(kbag, Mapping) and bool(kbag.get("want")):
            boost = float(kbag.get("boost") or 10.0)
            for row in candidates:
                if str(row.get("card") or "") != "knight":
                    continue
                if not bool(row.get("legal")):
                    continue
                # Force into play competition when legal + touchpoint wants
                row["play"] = True
                row["norm_score"] = round(float(row.get("norm_score") or 0) + boost, 3)
                row["rcard_touch_boost"] = boost
                row["rcard_touch_reason"] = str(kbag.get("reason") or "rcard_knight_want")
                # Elevate tier so HOLD doesn't beat unlock/LA knight
                if str(row.get("tier") or "") in ("hold_plan", "weak", "soft", ""):
                    row["tier"] = "strong"
                break
        for card_key, bag_key in (
            ("year_of_plenty", "yop"),
            ("monopoly", "monopoly"),
        ):
            bag = (tp or {}).get(bag_key) if isinstance(tp, Mapping) else {}
            if not isinstance(bag, Mapping) or not bool(bag.get("want")):
                continue
            boost = float(bag.get("boost") or 5.0)
            for row in candidates:
                if str(row.get("card") or "") != card_key:
                    continue
                if not bool(row.get("legal")) or not bool(row.get("play")):
                    continue
                row["norm_score"] = round(float(row.get("norm_score") or 0) + boost, 3)
                row["rcard_touch_boost"] = boost
                break
    except Exception as _tp_exc:
        ctx["rcard_touch_error"] = str(_tp_exc)

    # WP-TFR1: when TFR plan says play with free-road tips, beat HOLD / buy-path
    # so preview executes TFR *before* Continue spends a paid road (n3d Orange R3).
    if window == "post_roll":
        try:
            for row in candidates:
                if str(row.get("card") or "") != "two_free_roads":
                    continue
                if not bool(row.get("legal")) or not bool(row.get("play")):
                    continue
                plan = row.get("plan") if isinstance(row.get("plan"), Mapping) else {}
                n_roads = len(list(plan.get("road_ids") or []))
                free_n = int(plan.get("free_roads_available") or plan.get("roads_to_place") or 0)
                if n_roads <= 0 and free_n <= 0:
                    break
                boost = 12.0 if n_roads >= 2 or free_n >= 2 else 9.0
                row["norm_score"] = round(float(row.get("norm_score") or 0) + boost, 3)
                row["wp_tfr1_boost"] = boost
                if str(row.get("tier") or "") in ("hold_plan", "weak", "soft", ""):
                    row["tier"] = "strong"
                ctx["wp_tfr1_prefer_play"] = True
                break
        except Exception as _tfr1_exc:
            ctx["wp_tfr1_error"] = str(_tfr1_exc)

        # WP-DCARD2: same boost for Knight/YOP/Monopoly when their plan says play
        try:
            for card_name, min_boost in (
                ("knight", 11.0),
                ("year_of_plenty", 9.0),
                ("monopoly", 9.0),
            ):
                for row in candidates:
                    if str(row.get("card") or "") != card_name:
                        continue
                    if not bool(row.get("legal")) or not bool(row.get("play")):
                        continue
                    plan = row.get("plan") if isinstance(row.get("plan"), Mapping) else {}
                    reason = str(plan.get("reason") or row.get("reason") or "").lower()
                    # Crit / plan-play reasons always force ahead of HOLD
                    strong = any(
                        tok in reason
                        for tok in (
                            "crit",
                            "la_",
                            "s_crit",
                            "lr_crit",
                            "early_path",
                            "settle_path",
                            "play",
                        )
                    ) or bool(row.get("rcard_touch_boost"))
                    boost = float(min_boost) + (3.0 if strong else 0.0)
                    row["norm_score"] = round(float(row.get("norm_score") or 0) + boost, 3)
                    row["wp_dcard2_boost"] = boost
                    if str(row.get("tier") or "") in ("hold_plan", "weak", "soft", ""):
                        row["tier"] = "strong"
                    ctx["wp_dcard2_prefer_play"] = card_name
                    break
        except Exception as _d2_exc:
            ctx["wp_dcard2_error"] = str(_d2_exc)

    choice["candidates"] = candidates
    choice["context"] = ctx

    winner = _pick_max_score(candidates)
    # WP-DCARD2: never HOLD when a legal plan-play card exists
    if str(winner.get("card") or "") == "HOLD" or not bool(winner.get("play")):
        for card_name in CARD_ORDER:
            for row in candidates:
                if str(row.get("card") or "") != card_name:
                    continue
                if not bool(row.get("legal")) or not bool(row.get("play")):
                    continue
                # Prefer cards we already boosted / crit-tagged
                if (
                    row.get("wp_tfr1_boost")
                    or row.get("wp_dcard2_boost")
                    or row.get("rcard_touch_boost")
                    or str(row.get("tier") or "") in ("strong", "crit", "win_now")
                ):
                    winner = dict(row)
                    ctx["wp_dcard2_forced_over_hold"] = card_name
                    break
            if str(winner.get("card") or "") != "HOLD" and bool(winner.get("play")):
                break

    choice["winner"] = winner
    choice["winner_plan"] = winner.get("plan")
    choice["score"] = winner.get("norm_score")
    choice["context"] = ctx

    if str(winner.get("card")) == "HOLD" or not bool(winner.get("play")):
        choice["play"] = False
        choice["chosen"] = None
        choice["reason"] = str(winner.get("reason") or REASON_HOLD_NONE_WANT_PLAY)
    else:
        choice["play"] = True
        choice["chosen"] = str(winner.get("card") or "")
        choice["reason"] = (
            "wp_dcard2_force_play"
            if ctx.get("wp_dcard2_forced_over_hold")
            else REASON_MAX_SCORE
        )

    if log:
        _log_choice(game, choice)
    return choice


def _log_choice(game: Any, choice: Mapping[str, Any]) -> None:
    try:
        game.last_ai_dcard_choice = dict(choice)
    except Exception:
        pass
    try:
        trace = getattr(game, "current_ai_decision_trace", None)
        if not isinstance(trace, list):
            trace = []
            game.current_ai_decision_trace = trace
        trace.append(
            {
                "kind": "dcard_choice",
                "stage": choice.get("stage"),
                "window": choice.get("window"),
                "play": bool(choice.get("play")),
                "chosen": choice.get("chosen"),
                "reason": choice.get("reason"),
                "score": choice.get("score"),
                "player_id": choice.get("player_id"),
            }
        )
    except Exception:
        pass
    try:
        from core.console import execution_debug_print

        execution_debug_print(
            game,
            "AI DCard choice "
            f"[P{choice.get('player_id')}] window={choice.get('window')} "
            f"play={choice.get('play')} chosen={choice.get('chosen')} "
            f"reason={choice.get('reason')} score={choice.get('score')}",
        )
    except Exception:
        pass


def _execute_card(
    game: Any,
    player: Any,
    card: str,
    plan: Optional[Mapping[str, Any]],
    *,
    window: str,
) -> Dict[str, Any]:
    card = str(card or "")
    win = str(window or "post_roll")
    try:
        if card == "knight":
            from core.ai_play_knight import execute_ai_play_knight

            return execute_ai_play_knight(game, player, plan=plan, window=win)
        if card == "two_free_roads":
            from core.ai_play_tfr import execute_ai_play_tfr

            return execute_ai_play_tfr(game, player, plan=plan, window=win)
        if card == "year_of_plenty":
            from core.ai_play_yop import execute_ai_play_yop

            return execute_ai_play_yop(game, player, plan=plan, window=win)
        if card == "monopoly":
            from core.ai_play_monopoly import execute_ai_play_monopoly

            return execute_ai_play_monopoly(game, player, plan=plan, window=win)
    except Exception as exc:
        return {"ok": False, "executed": False, "reason": f"execute_error:{exc}", "card": card}
    return {"ok": False, "executed": False, "reason": f"unknown_card:{card}", "card": card}


def maybe_execute_ai_dcard_choice(
    game: Any,
    window: str = "post_roll",
    *,
    log: bool = True,
    allowed_cards: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Plan DCard choice and execute at most one card."""
    player = None
    try:
        player = game.get_current_player()
    except Exception:
        player = getattr(game, "current_player", None)

    choice = plan_ai_dcard_choice(
        game,
        player,
        window=window,
        log=log,
        allowed_cards=allowed_cards,
    )
    choice = dict(choice or {})

    if not bool(choice.get("play")) or not choice.get("chosen"):
        choice["executed"] = False
        choice["execute_result"] = None
        if log:
            try:
                game.last_ai_dcard_choice = choice
            except Exception:
                pass
        return choice

    plan = choice.get("winner_plan") or (choice.get("winner") or {}).get("plan")
    executed = _execute_card(
        game,
        player,
        str(choice.get("chosen")),
        plan,
        window=str(window or "post_roll"),
    )
    choice["executed"] = bool(executed.get("executed") or executed.get("ok"))
    choice["execute_result"] = executed
    if log:
        try:
            game.last_ai_dcard_choice = choice
        except Exception:
            pass
        try:
            from core.console import execution_debug_print

            execution_debug_print(
                game,
                "AI DCard execute "
                f"[P{choice.get('player_id')}] chosen={choice.get('chosen')} "
                f"ok={executed.get('ok')} reason={executed.get('reason')}",
            )
        except Exception:
            pass
    return choice


__all__ = [
    "STAGE",
    "CARD_ORDER",
    "PRE_ROLL_ALLOWED",
    "reason_to_tier",
    "normalize_play_score",
    "score_hold_dcard",
    "plan_ai_dcard_choice",
    "maybe_execute_ai_dcard_choice",
]
