"""S-LA-A: Largest Army progress snapshot (buy residual + sticky token).

Pure helpers — no knight execute, no graph engine. Coach suggestions are S-LA-E.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple  # Sequence used by coach + residual

# Resource order: Wh, O, Wd, B, Sh (matches trade / hand vectors)
_RES_WH, _RES_O, _RES_SH = 0, 1, 4
DCARD_BUY_COST = (1, 1, 0, 0, 1)  # Wh, O, Wd, B, Sh


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _army_size(player: Any) -> int:
    try:
        return max(0, int(getattr(player, "size_largest_army", 0) or 0))
    except Exception:
        return 0


def _holds_la(player: Any) -> bool:
    return bool(
        getattr(player, "largest_army_tf", False)
        or getattr(player, "biggest_army_tf", False)
    )


def way_wants_largest_army(player: Any) -> bool:
    """True if preferred way still pursues Largest Army (tags / remaining DCards)."""
    if player is None:
        return False
    try:
        from core.ai_lr_project import way_wants_largest_army as _w

        if _w(player):
            return True
    except Exception:
        pass
    try:
        from core.strategy_way_kill import way_needs_largest_army

        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping) and way_needs_largest_army(direction):
            return True
    except Exception:
        pass
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return False
    rem = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
    try:
        if int((rem or {}).get("development_cards") or 0) > 0 and (
            bool(direction.get("biggest_army") or direction.get("largest_army"))
            or "army" in " ".join(str(t).lower() for t in list(direction.get("tags") or []))
        ):
            return True
    except Exception:
        pass
    return False


def _hand_vector5(player: Any) -> List[int]:
    hand = [0, 0, 0, 0, 0]
    if player is None:
        return hand
    try:
        rc = getattr(player, "rcards", None)
        if isinstance(rc, Mapping):
            names = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
            for i, n in enumerate(names):
                hand[i] = max(0, int(rc.get(n, rc.get(n.lower(), 0)) or 0))
            return hand
        if isinstance(rc, (list, tuple)) and len(rc) >= 5:
            return [max(0, int(rc[i] or 0)) for i in range(5)]
    except Exception:
        pass
    return hand


def _dcard_row_counts(player: Any, card_type: str = "knight") -> Tuple[int, int, int]:
    """Return (new, playable, revealed/played) for one dcard type."""
    ct = str(card_type or "knight")
    try:
        for row in list(getattr(player, "dcard_summary", None) or []):
            row_list = list(row or [])
            if not row_list or str(row_list[0]) != ct:
                continue
            while len(row_list) < 4:
                row_list.append(0)
            return (
                max(0, int(row_list[1] or 0)),
                max(0, int(row_list[2] or 0)),
                max(0, int(row_list[3] or 0)),
            )
    except Exception:
        pass
    # Fallback: development_cards hand all playable (unit stubs)
    try:
        n = sum(1 for c in (getattr(player, "development_cards", []) or []) if str(c) == ct)
        return (0, n, 0)
    except Exception:
        return (0, 0, 0)


def _portfolio_dcard_remaining(player: Any) -> Optional[int]:
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return None
    rem = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
    for key in ("development_cards", "dev_cards", "dcards"):
        if rem and rem.get(key) is not None and rem.get(key) != "":
            v = _safe_int(rem.get(key), None)
            if v is not None:
                return max(0, v)
    for key in ("development_cards_to_buy", "listed_development_cards"):
        if direction.get(key) is not None and direction.get(key) != "":
            v = _safe_int(direction.get(key), None)
            if v is not None:
                return max(0, v)
    return None


def _residual_for_dcard_buy(hand: Sequence[int]) -> Dict[str, int]:
    need = {
        "Wh": max(0, DCARD_BUY_COST[_RES_WH] - int(hand[_RES_WH] or 0)),
        "O": max(0, DCARD_BUY_COST[_RES_O] - int(hand[_RES_O] or 0)),
        "Sh": max(0, DCARD_BUY_COST[_RES_SH] - int(hand[_RES_SH] or 0)),
    }
    return {k: v for k, v in need.items() if v > 0}


def _can_buy_dcard(hand: Sequence[int], game: Any = None, player: Any = None) -> bool:
    if not _residual_for_dcard_buy(hand):
        return True
    # Scan legal buy if present
    if game is not None:
        for attr in ("current_actionable_choices", "current_execution_choices"):
            for row in list(getattr(game, attr, None) or []):
                if not isinstance(row, Mapping):
                    continue
                name = str(row.get("action") or "").lower()
                if "development" in name and bool(row.get("viable", row.get("actionable", True))):
                    return True
    return False


def _deck_remaining_est(game: Any) -> Optional[int]:
    try:
        stack = getattr(game, "development_card_deck", None)
        if stack is None:
            stack = getattr(game, "dcard_deck", None)
        if isinstance(stack, (list, tuple)):
            return len(stack)
        if isinstance(stack, int):
            return max(0, stack)
        n = getattr(game, "development_cards_remaining", None)
        if n is not None:
            return max(0, int(n))
    except Exception:
        pass
    return None


def should_arm_la_progress(game: Any, player: Any) -> bool:
    """Arm when way wants LA (incl. army 0 + tags/remaining DCards) or race is live."""
    if player is None:
        return False
    if way_wants_largest_army(player):
        return True
    try:
        from core.ai_lr_project import compute_la_race_state

        race = compute_la_race_state(game, player)
        if bool(race.get("la_race")):
            return True
    except Exception:
        pass
    # Race-shaped without way tag: both deep in knights
    army = _army_size(player)
    max_opp = 0
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    for opp in list(getattr(game, "players", None) or []):
        if opp is None:
            continue
        if (_safe_int(getattr(opp, "id", 0), 0) or 0) == pid:
            continue
        max_opp = max(max_opp, _army_size(opp))
    if army >= 2 and max_opp >= 2 and abs(army - max_opp) <= 1:
        return True
    return False


def compute_la_progress(game: Any, player: Any) -> Dict[str, Any]:
    """Build la_progress snapshot (no mutation)."""
    army_ai = _army_size(player)
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    max_opp = 0
    for opp in list(getattr(game, "players", None) or []):
        if opp is None:
            continue
        if (_safe_int(getattr(opp, "id", 0), 0) or 0) == pid:
            continue
        max_opp = max(max_opp, _army_size(opp))

    we_hold = _holds_la(player)
    wants = way_wants_largest_army(player)
    race_state: Dict[str, Any] = {}
    try:
        from core.ai_lr_project import compute_la_race_state

        race_state = compute_la_race_state(game, player)
    except Exception:
        race_state = {}
    la_race = bool(race_state.get("la_race"))

    target_army = max(3, max_opp + 1)
    if we_hold and army_ai > max_opp:
        knights_needed = 0
    else:
        knights_needed = max(0, target_army - army_ai)

    new_k, playable_k, revealed_k = _dcard_row_counts(player, "knight")
    would_take_now = bool(
        playable_k >= 1 and army_ai + 1 >= 3 and army_ai + 1 > max_opp
    )
    banked = playable_k + new_k
    knights_based_est = max(0, knights_needed - banked)
    portfolio_rem = _portfolio_dcard_remaining(player)
    if portfolio_rem is not None:
        buys_est = min(int(portfolio_rem), int(knights_based_est))
    else:
        buys_est = int(knights_based_est)

    hand = _hand_vector5(player)
    residual = _residual_for_dcard_buy(hand)
    can_buy = _can_buy_dcard(hand, game=game, player=player)

    # Labels
    if we_hold and knights_needed == 0:
        label = "LA hold"
        phase = "hold"
    elif would_take_now:
        label = "LA take" if not we_hold else "LA steal"
        phase = "take"
    elif army_ai == 0 and wants:
        label = "LA"
        phase = "chase"
    else:
        label = f"LA {army_ai}/{target_army}"
        phase = "chase"

    race_gap = abs(army_ai - max_opp) if (army_ai or max_opp) else 0

    return {
        "sticky_version": 1,
        "player_id": pid,
        "army_ai": int(army_ai),
        "max_opp_army": int(max_opp),
        "target_army": int(target_army),
        "race_gap": int(race_gap),
        "knights_needed_to_take": int(knights_needed),
        "knights_in_hand_playable": int(playable_k),
        "knights_in_hand_new": int(new_k),
        "knights_revealed_or_played_col": int(revealed_k),
        "would_take_now": bool(would_take_now),
        "we_hold_la": bool(we_hold),
        "la_race": bool(la_race),
        "wants_la": bool(wants),
        "deck_remaining_est": _deck_remaining_est(game),
        "buys_remaining_est": int(buys_est),
        "knights_based_buys_est": int(knights_based_est),
        "portfolio_dcard_remaining": portfolio_rem,
        "buy_cost": {"Wh": 1, "O": 1, "Sh": 1},
        "residual_for_buy": residual,
        "can_buy_dcard_now": bool(can_buy and buys_est > 0) if buys_est > 0 else bool(can_buy and knights_needed > 0),
        "target_label": label,
        "phase": phase,
        "hold_after_take": bool(phase == "hold"),
        "strategy_reason": (
            "S-LA-A: holding Largest Army"
            if phase == "hold"
            else (
                "S-LA-A: playable knight takes LA"
                if would_take_now
                else f"S-LA-A: chase LA need {knights_needed} knight(s), ~{buys_est} buys"
            )
        ),
    }


def format_la_progress_token(progress: Optional[Mapping[str, Any]]) -> str:
    """Display token: LA, LA 2/3, LA take, LA hold."""
    if not isinstance(progress, Mapping) or not progress:
        return "LA"
    label = str(progress.get("target_label") or "").strip()
    if label:
        return label
    army = int(progress.get("army_ai") or 0)
    target = int(progress.get("target_army") or 3)
    if progress.get("would_take_now"):
        return "LA take"
    if progress.get("we_hold_la") and int(progress.get("knights_needed_to_take") or 0) == 0:
        return "LA hold"
    if army == 0:
        return "LA"
    return f"LA {army}/{target}"


def get_stored_la_progress(player: Any, game: Any = None) -> Dict[str, Any]:
    if player is not None:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            prog = sticky.get("la_progress")
            if isinstance(prog, Mapping) and prog:
                return dict(prog)
        prog = getattr(player, "la_progress", None)
        if isinstance(prog, Mapping) and prog:
            return dict(prog)
        direction = getattr(player, "strategic_direction", None)
        if isinstance(direction, Mapping):
            prog = direction.get("la_progress")
            if isinstance(prog, Mapping) and prog:
                return dict(prog)
    if game is not None:
        last = getattr(game, "last_la_progress", None)
        if isinstance(last, Mapping) and last:
            pid = _safe_int(getattr(player, "id", None), None) if player is not None else None
            if pid is None or _safe_int(last.get("player_id"), None) in (None, pid):
                return dict(last)
    return {}


def store_la_progress(
    game: Any,
    player: Any,
    progress: Mapping[str, Any],
    *,
    merge_sticky: bool = True,
) -> Dict[str, Any]:
    data = dict(progress or {})
    if not data:
        return {}
    try:
        if player is not None:
            setattr(player, "la_progress", data)
    except Exception:
        pass
    try:
        if game is not None:
            data = dict(data)
            data.setdefault("player_id", _safe_int(getattr(player, "id", 0), 0))
            setattr(game, "last_la_progress", data)
    except Exception:
        pass
    if merge_sticky and player is not None:
        merge_la_progress_into_sticky(player, data, game=game)
    return data


def merge_la_progress_into_sticky(
    player: Any,
    progress: Mapping[str, Any],
    *,
    game: Any = None,
) -> Dict[str, Any]:
    """Attach la_progress without wiping city/settle/LR locks."""
    data = dict(progress or {})
    if not data:
        return {}
    raw = getattr(player, "sticky_commitment", None)
    commitment: Dict[str, Any] = dict(raw) if isinstance(raw, Mapping) else {}
    commitment["la_progress"] = data
    commitment["sticky_version"] = max(3, int(commitment.get("sticky_version") or 0) or 3)
    if (
        commitment.get("locked_rec_target_id") is None
        and not commitment.get("lr_project")
        and not commitment.get("locked_target_kind")
    ):
        commitment["locked_target_kind"] = "LA"
    try:
        setattr(player, "sticky_commitment", commitment)
        setattr(player, "la_progress", data)
    except Exception:
        pass
    return commitment


def clear_la_progress_from_sticky(player: Any, game: Any = None) -> None:
    """Drop la_progress; keep city/settle/LR locks."""
    try:
        if player is not None:
            setattr(player, "la_progress", None)
    except Exception:
        pass
    try:
        if game is not None:
            last = getattr(game, "last_la_progress", None)
            if isinstance(last, Mapping):
                if int(last.get("player_id") or 0) == int(getattr(player, "id", 0) or 0):
                    setattr(game, "last_la_progress", None)
    except Exception:
        pass
    raw = getattr(player, "sticky_commitment", None)
    if not isinstance(raw, Mapping):
        return
    commitment = dict(raw)
    commitment.pop("la_progress", None)
    has_struct = commitment.get("locked_rec_target_id") is not None
    has_lr = isinstance(commitment.get("lr_project"), Mapping) and bool(
        (commitment.get("lr_project") or {}).get("roads_to_build")
    )
    if not has_struct and not has_lr:
        # LA-only sticky
        if str(commitment.get("locked_target_kind") or "").upper() == "LA":
            try:
                setattr(player, "sticky_commitment", None)
            except Exception:
                pass
            return
    try:
        setattr(player, "sticky_commitment", commitment)
    except Exception:
        pass


def apply_la_progress_to_direction(
    direction: Mapping[str, Any],
    player: Any,
    game: Any = None,
) -> Dict[str, Any]:
    """Copy la_progress onto strategic_direction for UI / sticky display."""
    out = dict(direction or {})
    prog = get_stored_la_progress(player, game)
    if not prog:
        return out
    out["la_progress"] = dict(prog)
    out["la_target_label"] = format_la_progress_token(prog)
    if prog.get("wants_la") or prog.get("la_race") or prog.get("we_hold_la"):
        out["biggest_army"] = True
        out["largest_army"] = True
    tags = list(out.get("tags") or [])
    tag_text = " ".join(str(t).lower() for t in tags)
    if "army" not in tag_text and (prog.get("wants_la") or prog.get("la_race")):
        tags.append("Largest Army")
        out["tags"] = tags
    return out


def should_invalidate_la_progress(
    game: Any,
    player: Any,
    progress: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
    """Whether to drop stored la_progress."""
    prog = dict(progress or get_stored_la_progress(player, game) or {})
    if not prog:
        return True, "empty"

    # S5 way kill latch / last kill
    try:
        last = getattr(player, "last_way_kill", None)
        if isinstance(last, Mapping):
            kind = str(last.get("kind") or last.get("special") or "").upper()
            reason = str(last.get("reason") or "")
            if kind == "LA" or "LA infeasible" in reason or "way_kill_la" in reason.lower():
                if last.get("killed") or last.get("hopeless") or "infeasible" in reason:
                    return True, "way_kill_la"
        latch = getattr(player, "way_kill_latch", None)
        if isinstance(latch, Mapping) and latch.get("LA"):
            return True, "way_kill_la_latch"
    except Exception:
        pass

    # Hold-after-take: second sticky pass clears if army component gone from way
    if prog.get("hold_after_take") or str(prog.get("phase") or "") == "hold":
        # If already consumed one hold refresh marker
        if prog.get("hold_refresh_done"):
            if not way_wants_largest_army(player) and not bool(
                getattr(player, "largest_army_tf", False) and way_wants_largest_army(player)
            ):
                return True, "hold_refresh_clear"
            # Keep minimal hold while way still tags LA (defend); else clear
            if not way_wants_largest_army(player):
                return True, "hold_refresh_clear"

    # No longer wants and not race and not holding chase
    if not should_arm_la_progress(game, player):
        # Still holding LA with hold token — allow one cycle
        if prog.get("we_hold_la") and not prog.get("hold_refresh_done"):
            return False, "hold_pending"
        if not _holds_la(player):
            return True, "no_longer_wants_la"

    return False, "hold"


def ensure_la_progress_sticky(game: Any, player: Any) -> Dict[str, Any]:
    """Arm / refresh / hold / invalidate la_progress on sticky."""
    meta: Dict[str, Any] = {
        "armed": False,
        "held": False,
        "invalidated": False,
        "reason": "",
        "progress": None,
    }
    if player is None:
        meta["reason"] = "no_player"
        return meta

    existing = get_stored_la_progress(player, game)

    # Invalidate first
    if existing:
        inv, inv_reason = should_invalidate_la_progress(game, player, existing)
        if inv:
            clear_la_progress_from_sticky(player, game)
            meta["invalidated"] = True
            meta["reason"] = inv_reason
            existing = {}
            if inv_reason.startswith("way_kill") or inv_reason == "no_longer_wants_la":
                # may re-arm below if still wants (unlikely after kill)
                pass

    if not should_arm_la_progress(game, player):
        # Hold-after-take: keep one refresh of LA hold even if wants_la soft
        if existing and (
            existing.get("hold_after_take") or str(existing.get("phase") or "") == "hold"
        ):
            if not existing.get("hold_refresh_done") and _holds_la(player):
                refreshed = compute_la_progress(game, player)
                refreshed["phase"] = "hold"
                refreshed["target_label"] = "LA hold"
                refreshed["hold_after_take"] = True
                refreshed["hold_refresh_done"] = True
                refreshed["knights_needed_to_take"] = 0
                store_la_progress(game, player, refreshed, merge_sticky=True)
                meta.update({"held": True, "reason": "la_hold_refresh", "progress": refreshed})
                return meta
            clear_la_progress_from_sticky(player, game)
            meta["invalidated"] = True
            meta["reason"] = "la_disarm"
            return meta
        if existing:
            clear_la_progress_from_sticky(player, game)
            meta["invalidated"] = True
            meta["reason"] = "la_disarm"
        else:
            meta["reason"] = "no_arm"
        return meta

    progress = compute_la_progress(game, player)

    # Transition into hold after take
    if progress.get("we_hold_la") and int(progress.get("knights_needed_to_take") or 0) == 0:
        progress["phase"] = "hold"
        progress["target_label"] = "LA hold"
        progress["hold_after_take"] = True
        if existing.get("hold_after_take") or existing.get("hold_refresh_done"):
            progress["hold_refresh_done"] = True
            # Second cycle while still armed: if way no longer needs army, clear
            if progress.get("hold_refresh_done") and not way_wants_largest_army(player):
                clear_la_progress_from_sticky(player, game)
                meta["invalidated"] = True
                meta["reason"] = "hold_done_way_dropped_la"
                return meta
        store_la_progress(game, player, progress, merge_sticky=True)
        meta.update(
            {
                "held": bool(existing),
                "armed": not bool(existing),
                "reason": "la_hold" if existing else "la_arm_hold",
                "progress": progress,
            }
        )
        return meta

    store_la_progress(game, player, progress, merge_sticky=True)
    meta.update(
        {
            "armed": not bool(existing),
            "held": bool(existing),
            "reason": "la_hold" if existing else "la_arm",
            "progress": progress,
        }
    )
    return meta


# ---------------------------------------------------------------------------
# S-LA-E: turn suggestions (coach)
# ---------------------------------------------------------------------------

MAX_LA_TURN_SUGGESTIONS: int = 4


def _playable_dcard_count(player: Any, card_type: str) -> int:
    _new, playable, _rev = _dcard_row_counts(player, card_type)
    return int(playable)


def _knight_plan_reason(game: Any) -> str:
    try:
        plan = getattr(game, "last_ai_knight_plan", None)
        if isinstance(plan, Mapping):
            return str(plan.get("reason") or "")
        by_w = getattr(game, "last_ai_knight_plan_by_window", None)
        if isinstance(by_w, Mapping):
            post = by_w.get("post_roll") or by_w.get("pre_roll")
            if isinstance(post, Mapping):
                return str(post.get("reason") or "")
    except Exception:
        pass
    return ""


def build_la_turn_suggestions(
    game: Any,
    player: Any,
    *,
    progress: Optional[Mapping[str, Any]] = None,
    focus: Optional[str] = None,
    max_suggestions: int = MAX_LA_TURN_SUGGESTIONS,
) -> List[Dict[str, Any]]:
    """S-LA-E: ranked coach actions for advancing LA this turn (no multi-execute)."""
    prog = dict(progress or get_stored_la_progress(player, game) or {})
    if not prog:
        try:
            if should_arm_la_progress(game, player):
                prog = compute_la_progress(game, player)
        except Exception:
            prog = {}
    if not prog:
        return []

    # Quiet coach while holding after take (unless focus la for defend — still soft)
    phase = str(prog.get("phase") or "")
    if phase == "hold" and int(prog.get("knights_needed_to_take") or 0) == 0:
        # Only secondary hold note
        out_hold = [
            {
                "action": "hold_la_lead",
                "label": "HOLD LA (leading)",
                "rank": 1,
                "reason": "la_hold_after_take",
                "secondary": True,
            }
        ]
        try:
            if game is not None:
                setattr(game, "last_la_turn_suggestions", list(out_hold))
            if player is not None:
                setattr(player, "la_turn_suggestions", list(out_hold))
        except Exception:
            pass
        return out_hold

    if focus is None:
        try:
            from core.ai_lr_project import pick_turn_focus

            focus = str(pick_turn_focus(game, player).get("focus") or "pass")
        except Exception:
            focus = "pass"
    focus = str(focus or "pass").lower()

    army = int(prog.get("army_ai") or 0)
    max_opp = int(prog.get("max_opp_army") or 0)
    needed = int(prog.get("knights_needed_to_take") or 0)
    playable_k = int(prog.get("knights_in_hand_playable") or 0)
    would_take = bool(prog.get("would_take_now"))
    la_race = bool(prog.get("la_race"))
    buys_est = int(prog.get("buys_remaining_est") or 0)
    residual = prog.get("residual_for_buy") if isinstance(prog.get("residual_for_buy"), Mapping) else {}
    can_buy = bool(prog.get("can_buy_dcard_now"))
    # Refresh residual/can_buy from live hand if missing
    if not residual:
        residual = _residual_for_dcard_buy(_hand_vector5(player))
    if playable_k <= 0:
        playable_k = _playable_dcard_count(player, "knight")

    yop_n = _playable_dcard_count(player, "year_of_plenty")
    mono_n = _playable_dcard_count(player, "monopoly")
    k_reason = _knight_plan_reason(game).lower()

    city_id = None
    try:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            city_id = sticky.get("locked_rec_target_id") or sticky.get("city_upgrade_target_id")
        if city_id is None:
            d = getattr(player, "strategic_direction", None) or {}
            if isinstance(d, Mapping):
                city_id = d.get("city_upgrade_target_id") or d.get("recommendation_target_id")
    except Exception:
        pass

    candidates: List[Dict[str, Any]] = []

    def add(
        action: str,
        label: str,
        *,
        rank: int,
        reason: str,
        resources: Any = None,
        secondary: bool = False,
    ) -> None:
        candidates.append(
            {
                "action": action,
                "label": label,
                "rank": int(rank),
                "reason": reason,
                "resources": resources,
                "secondary": bool(secondary),
            }
        )

    # City focus primary note
    if focus == "city":
        cid = city_id if city_id is not None else "?"
        add(
            "hold_wait_city",
            f"Hold LA path; city first (C@{cid})",
            rank=0,
            reason="city_efficiency_focus",
            secondary=False,
        )

    # Mandatory-style take
    if would_take and playable_k >= 1:
        add(
            "play_knight_take",
            f"Play Knight (take LA {army + 1} vs {max_opp})",
            rank=1,
            reason="would_take_now",
        )
    elif playable_k >= 1 and la_race and army >= 2:
        add(
            "play_knight_race",
            f"Play Knight (LA race {army} vs {max_opp})",
            rank=2,
            reason="la_race_play",
        )
    elif playable_k >= 1 and any(
        x in k_reason for x in ("unblock", "deny", "meta", "self_block", "robber")
    ):
        add(
            "play_knight_robber",
            "Play Knight (unblock/deny)",
            rank=3,
            reason="knight_plan_robber",
        )
    elif playable_k >= 1 and needed > 0 and army < 2 and not la_race:
        # Early soft: prefer hold bank unless focus la
        add(
            "hold_bank_knight",
            "HOLD Knight (bank for LA race)",
            rank=8 if focus != "la" else 5,
            reason="early_hold_knight",
            secondary=focus != "la",
        )
    elif playable_k >= 1 and needed > 0:
        add(
            "play_knight_race",
            f"Play Knight (army {army}→{army + 1})",
            rank=3,
            reason="play_toward_la",
        )

    # Buy path
    if buys_est >= 1 or (needed > 0 and playable_k + int(prog.get("knights_in_hand_new") or 0) < needed):
        if can_buy or not residual:
            add(
                "buy_dcard",
                f"Buy DCard (~{max(1, buys_est)} for LA)",
                rank=3 if not would_take else 6,
                reason="buy_toward_knights",
            )
        elif residual and 1 <= sum(int(v or 0) for v in residual.values()) <= 2:
            # short resources
            parts = "+".join(
                f"{v}{k}" if int(v) > 1 else k for k, v in residual.items() if int(v or 0) > 0
            )
            if yop_n > 0:
                add(
                    "play_yop_owg",
                    f"Play YOP → {parts} for DCard (LA)",
                    rank=4,
                    reason="yop_fund_dcard",
                    resources=dict(residual),
                )
            add(
                "twb_unlock_dcard",
                f"TwB → {parts} for DCard (LA)",
                rank=6,
                reason="twb_hint_dcard",
                resources=dict(residual),
            )
        elif residual:
            parts = "+".join(k for k, v in residual.items() if int(v or 0) > 0)
            add(
                "twb_unlock_dcard",
                f"TwB → unlock DCard ({parts})",
                rank=7,
                reason="twb_hint_dcard",
                resources=dict(residual),
            )

    # YOP when residual 1–2 even if can_buy false above covered; if can buy skip
    if yop_n > 0 and residual and 1 <= sum(int(v or 0) for v in residual.values()) <= 2:
        if not any(c.get("action") == "play_yop_owg" for c in candidates):
            parts = "+".join(k for k, v in residual.items() if int(v or 0) > 0)
            add(
                "play_yop_owg",
                f"Play YOP → {parts} for DCard (LA)",
                rank=4,
                reason="yop_fund_dcard",
                resources=dict(residual),
            )

    # Monopoly Ore when Ore is sole/main bottleneck and multi-buy
    if mono_n > 0 and buys_est >= 2 and residual.get("O", 0):
        o_only = set(residual.keys()) <= {"O"} or int(residual.get("O") or 0) >= max(
            int(residual.get("Wh") or 0), int(residual.get("Sh") or 0)
        )
        if o_only:
            add(
                "play_mono_ore",
                "Play Monopoly → Ore (LA buys)",
                rank=5,
                reason="mono_ore_bottleneck",
                resources={"O": "bank"},
            )

    # Knight hold when plan says hold / pre-roll seven
    if playable_k >= 1 and (
        "hold" in k_reason or "seven" in k_reason or "bank" in k_reason
    ):
        if not any(c.get("action") == "hold_bank_knight" for c in candidates):
            add(
                "hold_bank_knight",
                "HOLD Knight (timing)",
                rank=9,
                reason="knight_plan_hold",
                secondary=True,
            )

    # Secondary when not LA focus
    secondary_focus = focus in {"city", "lr", "settle"}
    if focus == "lr":
        # Mandatory LR claim: all LA secondary
        for c in candidates:
            if c.get("action") != "hold_wait_city":
                c["secondary"] = True
                c["rank"] = int(c.get("rank") or 9) + 10
                if not str(c.get("label") or "").startswith("After"):
                    c["label"] = f"After LR: {c.get('label')}"
    elif focus == "city":
        for c in candidates:
            if c.get("action") == "hold_wait_city":
                c["rank"] = 0
                c["secondary"] = False
            else:
                c["secondary"] = True
                c["rank"] = int(c.get("rank") or 9) + 10
                if not str(c.get("label") or "").startswith("After city"):
                    c["label"] = f"After city: {c.get('label')}"
    elif focus == "settle":
        for c in candidates:
            c["secondary"] = True
            c["rank"] = int(c.get("rank") or 9) + 8
    elif focus == "la":
        for c in candidates:
            if c.get("action") == "hold_wait_city":
                c["rank"] = 20
                c["secondary"] = True

    candidates.sort(key=lambda c: (int(c.get("rank") or 99), str(c.get("action") or "")))
    seen_act = set()
    out: List[Dict[str, Any]] = []
    for c in candidates:
        act = str(c.get("action") or "")
        if act in seen_act:
            continue
        seen_act.add(act)
        out.append(c)
        if len(out) >= max(1, int(max_suggestions or MAX_LA_TURN_SUGGESTIONS)):
            break

    try:
        if game is not None:
            setattr(game, "last_la_turn_suggestions", list(out))
        if player is not None:
            setattr(player, "la_turn_suggestions", list(out))
    except Exception:
        pass
    return out


def format_la_suggestions_lines(
    suggestions: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    max_lines: int = 2,
) -> List[str]:
    """PLAN/DBG lines from LA suggestion list."""
    rows: List[str] = []
    items = [dict(s) for s in (suggestions or []) if isinstance(s, Mapping)]
    if not items:
        return rows
    primary = [s for s in items if not s.get("secondary")]
    secondary = [s for s in items if s.get("secondary")]
    if primary:
        labels = [str(s.get("label") or s.get("action") or "") for s in primary[:2]]
        labels = [x for x in labels if x]
        if labels:
            line = "LA: " + " · ".join(labels)
            rows.append(line if len(line) <= 62 else line[:59] + "...")
    if secondary and len(rows) < max_lines:
        labels = [str(s.get("label") or "") for s in secondary[:2]]
        labels = [x for x in labels if x]
        if labels:
            joined = " · ".join(labels)
            rows.append(joined if len(joined) <= 62 else joined[:59] + "...")
    return rows[: max(1, int(max_lines or 2))]


__all__ = [
    "DCARD_BUY_COST",
    "MAX_LA_TURN_SUGGESTIONS",
    "apply_la_progress_to_direction",
    "build_la_turn_suggestions",
    "clear_la_progress_from_sticky",
    "compute_la_progress",
    "ensure_la_progress_sticky",
    "format_la_progress_token",
    "format_la_suggestions_lines",
    "get_stored_la_progress",
    "merge_la_progress_into_sticky",
    "should_arm_la_progress",
    "should_invalidate_la_progress",
    "store_la_progress",
    "way_wants_largest_army",
]
