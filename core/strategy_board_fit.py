"""WP2: board-fit filter for Victory-Ways vs live structure / specials held.

A way **fits** when (see ``docs/Way_board_sync_fix_plan.md``):
  - CSV Cities+Settlements ≥ board C+S (cannot unbuild).
  - City upgrades realizable from owned S (+ optional new S).
  - Held LR/LA ⇒ way includes that special.
  - Held VP cards ≤ way VP-card need (``vp_surplus`` if not).
  - If still short on VP: DCard stack has ≥ remaining need **and** RP/ports
    can afford that many DCard buys (``vp_infeasible`` / ``vp_stack_short``).
  - Way needs LR and not given-up LR ⇒ LR still playboard-plausible
    (``assess_lr_feasibility``; skip when ``kill_lr`` episode active).
  - Way needs LA and not given-up LA ⇒ LA still feasible
    (``assess_la_feasibility``; skip when ``kill_la`` episode active).
  - Not holding LA/LR does **not** by itself ban pursuing those specials.
  - Give-up carve-out (P4): if episode kill_la/kill_lr and **no** fully
    sync way exists, re-score allowing those specials to be ignored
    (buildings + VP still hard).

Product lock: never select a way out of sync (give-up carve-out for LA/LR only).

Modes (``WAY_BOARD_FIT_MODE`` / game stamp):
  off                     — no filter (historical)
  filter                  — unfit ways demoted (rank ∞); preferred from fit set
  filter_and_force_switch — filter + clear sticky / force preferred when sticky unfit

See docs/SE_improvement_plan_v2.md §2, improving_SE_v3.txt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

INFINITE_TURNS = 9999.0

MODES = frozenset({"off", "filter", "filter_and_force_switch"})


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def normalize_board_fit_mode(raw: Any) -> str:
    m = str(raw or "off").strip().lower()
    if m in ("", "none", "0", "false", "no"):
        return "off"
    if m in ("on", "true", "yes", "1"):
        return "filter_and_force_switch"
    if m in ("filter_only", "soft"):
        return "filter"
    if m in ("force", "force_switch", "full"):
        return "filter_and_force_switch"
    if m in MODES:
        return m
    return "off"


def get_board_fit_mode(game: Any = None) -> str:
    if game is not None:
        try:
            m = getattr(game, "way_board_fit_mode", None)
            if m is not None and str(m).strip() != "":
                return normalize_board_fit_mode(m)
        except Exception:
            pass
    try:
        from core import constants as C

        return normalize_board_fit_mode(getattr(C, "WAY_BOARD_FIT_MODE", "off"))
    except Exception:
        return "off"


def is_board_fit_enabled(game: Any = None) -> bool:
    return get_board_fit_mode(game) != "off"


def is_board_fit_force_switch(game: Any = None) -> bool:
    return get_board_fit_mode(game) == "filter_and_force_switch"


def _deck_remaining(game: Any) -> Optional[int]:
    """Public DCard stack length only (fair-play: no type peek)."""
    try:
        from core.partial_way_salvage import public_dcard_deck_remaining

        return public_dcard_deck_remaining(game)
    except Exception:
        pass
    if game is None:
        return None
    for attr in ("dcards_stack", "development_card_deck", "dcard_deck"):
        try:
            stack = getattr(game, attr, None)
            if isinstance(stack, (list, tuple)):
                return len(stack)
            if isinstance(stack, int):
                return max(0, int(stack))
        except Exception:
            continue
    try:
        n = getattr(game, "development_cards_remaining", None)
        if n is not None:
            return max(0, int(n))
    except Exception:
        pass
    return None


def assess_vp_buyability(
    game: Any,
    player: Any,
    *,
    target_vp: int,
    held_vp: int,
) -> Dict[str, Any]:
    """P3: can the seat still obtain remaining VP DCards (stack + RP/ports)?

    Operator lock (2026-08-21):
      - hand VP > way VP → handled separately as ``vp_surplus``
      - hand VP < way VP → still sync if stack has enough cards to buy the
        shortfall **and** RP/ports can fund Wh+Ore+Sheep for those buys

    Conservative stack rule: need ``deck_remaining >= vp_short`` (cannot buy
    more cards than remain; types unknown so we do not assume VP density).
    """
    target = max(0, int(target_vp or 0))
    held = max(0, int(held_vp or 0))
    short = max(0, target - held)
    out: Dict[str, Any] = {
        "ok": True,
        "reasons": [],
        "target_vp": target,
        "held_vp": held,
        "vp_short": short,
        "deck_remaining": None,
        "buy_turns": None,
        "buy_found": None,
    }
    if short <= 0:
        out["reason"] = "no_vp_shortfall"
        return out

    if game is None:
        # Cannot judge stack/RP without game — leave fit to other checks.
        out["reason"] = "vp_buy_no_game"
        return out

    deck = _deck_remaining(game)
    out["deck_remaining"] = deck
    if deck is not None and deck < short:
        out["ok"] = False
        tag = "vp_stack_empty" if deck <= 0 else f"vp_stack_short:need={short},deck={deck}"
        out["reasons"].append(tag)
        out["reason"] = tag
        return out

    # RP / ports: EH until affordable short × DCard cost (Wh+Ore+Sh each).
    try:
        from core.resource_time_estimator import (
            RCARDS_FOR_DCARD,
            clean_vector,
            estimate_first_payable_turn,
            get_player_production_pips,
            get_player_resource_cards_vector,
            get_player_trade_rates,
        )

        board = getattr(game, "board", None) if game is not None else None
        one = clean_vector(RCARDS_FOR_DCARD)
        need = [float(short) * float(one[i]) for i in range(5)]
        hand = clean_vector(get_player_resource_cards_vector(player))
        pips = clean_vector(get_player_production_pips(board, player))
        rates = get_player_trade_rates(board, player)
        n_players = 4
        try:
            n_players = max(1, len(getattr(game, "players", None) or []) or 4)
        except Exception:
            n_players = 4
        first = estimate_first_payable_turn(
            current_hand=hand,
            production_pips=pips,
            need=need,
            trade_rates=rates,
            num_players=int(n_players),
        )
        turns = first.get("turns")
        found = bool(first.get("found", False))
        try:
            turns_f = float(turns) if turns is not None else INFINITE_TURNS
        except Exception:
            turns_f = INFINITE_TURNS
        out["buy_turns"] = turns_f
        out["buy_found"] = found
        if (not found) or turns_f >= INFINITE_TURNS - 1:
            out["ok"] = False
            out["reasons"].append("vp_infeasible:rp_ports")
            out["reason"] = "vp_infeasible:rp_ports"
            return out
    except Exception as exc:
        # Soft: if EH unavailable, do not invent unfit (stack check already done)
        out["buy_error"] = str(exc)[:120]
        out["reason"] = "vp_buy_eh_skipped"
        return out

    out["reason"] = "vp_buyable"
    return out


def ignored_specials_from_player(player: Any) -> frozenset:
    """Specials the seat has given up (episode and/or ignored_components)."""
    ignored: set = set()
    if player is None:
        return frozenset()
    try:
        from core.specials_dead_episode import get_specials_dead_episode

        ep = get_specials_dead_episode(player)
        if ep.get("active"):
            if ep.get("kill_la"):
                ignored.add("la")
            if ep.get("kill_lr"):
                ignored.add("lr")
    except Exception:
        pass
    for attr in ("strategic_direction", "sticky_commitment"):
        try:
            bag = getattr(player, attr, None)
            if not isinstance(bag, Mapping):
                continue
            for raw in list(bag.get("ignored_components") or []):
                s = str(raw or "").strip().lower()
                if s in ("la", "largest_army", "army", "biggest_army"):
                    ignored.add("la")
                if s in ("lr", "longest_road", "road", "longest_route"):
                    ignored.add("lr")
        except Exception:
            continue
    return frozenset(ignored)


def _normalize_ignored_specials(raw: Any) -> frozenset:
    if not raw:
        return frozenset()
    out: set = set()
    for x in raw if not isinstance(raw, str) else [raw]:
        s = str(x or "").strip().lower()
        if s in ("la", "largest_army", "army", "biggest_army"):
            out.add("la")
        elif s in ("lr", "longest_road", "road", "longest_route"):
            out.add("lr")
        elif s in ("la", "lr"):
            out.add(s)
    return frozenset(out)


def can_realize_way(
    way_id: Any,
    player: Any,
    *,
    strategy: Any = None,
    game: Any = None,
    allow_ignored_specials: Any = None,
) -> Dict[str, Any]:
    """Return ``{fit, reasons, way_id, soft}`` for one way vs player board.

    ``soft=True`` means unknown way / missing strategy — treated as fit so we
    do not empty the portfolio on table load failures.

    ``allow_ignored_specials``: iterable of ``la``/``lr`` to skip feasibility
    checks for (give-up carve-out). Buildings + VP rules never waived.
    """
    from core.strategy_way_residual import (
        holds_la,
        holds_lr,
        load_way_requirement,
        settlement_city_counts,
        unplayed_vp_cards,
    )

    ignore = _normalize_ignored_specials(allow_ignored_specials)
    wid = _safe_int(way_id, None)
    out: Dict[str, Any] = {
        "fit": True,
        "reasons": [],
        "way_id": wid,
        "soft": False,
        "allow_ignored_specials": sorted(ignore),
    }
    if player is None:
        out["soft"] = True
        out["reasons"] = ["no_player"]
        return out
    if wid is None or wid <= 0:
        out["soft"] = True
        out["reasons"] = ["no_way_id"]
        return out

    strat = strategy if strategy is not None else load_way_requirement(wid)
    if strat is None:
        out["soft"] = True
        out["reasons"] = ["unknown_way"]
        return out

    n_s, n_c = settlement_city_counts(player)
    total_b = n_s + n_c
    target_c = max(
        0,
        _safe_int(getattr(strat, "cities", 0), 0) or 0,
        _safe_int(getattr(strat, "city_upgrades", 0), 0) or 0,
    )
    target_s = max(0, _safe_int(getattr(strat, "settlements", 0), 0) or 0)
    target_b = max(
        _safe_int(getattr(strat, "buildings", 0), 0) or 0,
        target_c + target_s,
        target_c,
    )

    rem_new_s = max(0, target_b - total_b)
    rem_c = max(0, target_c - n_c)
    available_bases = n_s + rem_new_s
    reasons: List[str] = []
    fit = True

    # Operator lock (improving_SE + Way_and_Board_dont_sync 2026-08-21):
    # Never select a way whose CSV C+S is below buildings already on the board.
    # Example: way 7 = 2C+2S (4) vs 5 settlements on board → structure_surplus.
    if total_b > target_b:
        fit = False
        reasons.append(f"structure_surplus:board={total_b},way={target_b}")

    if rem_c > available_bases:
        fit = False
        reasons.append(
            f"city_bases_short:need_upgrades={rem_c},bases={available_bases}"
        )

    way_lr = bool(getattr(strat, "longest_road", False))
    way_la = bool(
        getattr(strat, "biggest_army", False)
        or getattr(strat, "largest_army", False)
    )

    if holds_lr(player) and not way_lr:
        fit = False
        reasons.append("holds_lr_way_no_lr")
    if holds_la(player) and not way_la:
        fit = False
        reasons.append("holds_la_way_no_la")

    # Aspect 2 VP sync: surplus + buyability (P3).
    target_vp = max(0, _safe_int(getattr(strat, "victory_point_cards", 0), 0) or 0)
    try:
        held_vp = max(0, int(unplayed_vp_cards(player) or 0))
    except Exception:
        held_vp = 0
    if held_vp > target_vp:
        fit = False
        reasons.append(f"vp_surplus:hand={held_vp},way={target_vp}")
    elif target_vp > 0 and held_vp < target_vp:
        vp_buy = assess_vp_buyability(
            game, player, target_vp=target_vp, held_vp=held_vp
        )
        out["vp_buy"] = dict(vp_buy)
        if not vp_buy.get("ok", True):
            fit = False
            reasons.extend(list(vp_buy.get("reasons") or []))

    # Episode give-up flags (also honor explicit allow_ignored_specials).
    given_up_lr = "lr" in ignore
    given_up_la = "la" in ignore
    try:
        from core.specials_dead_episode import get_specials_dead_episode

        ep = get_specials_dead_episode(player)
        if ep.get("active"):
            if ep.get("kill_lr"):
                given_up_lr = True
            if ep.get("kill_la"):
                given_up_la = True
    except Exception:
        pass

    # Aspect 1 LR playboard (skip when LR given up / ignored).
    if (
        way_lr
        and game is not None
        and not given_up_lr
        and not holds_lr(player)
    ):
        try:
            from core.strategy_way_kill import assess_lr_feasibility

            lr_meta = assess_lr_feasibility(
                game,
                player,
                direction={
                    "longest_road": True,
                    "preferred_way_id": wid,
                    "way_id": wid,
                },
            )
            if bool(lr_meta.get("hopeless")):
                fit = False
                reasons.append("lr_playboard_implausible")
        except Exception:
            pass

    # Aspect 3 LA feasibility (P4; skip when LA given up / ignored).
    if (
        way_la
        and game is not None
        and not given_up_la
        and not holds_la(player)
    ):
        try:
            from core.strategy_way_kill import assess_la_feasibility

            la_meta = assess_la_feasibility(
                game,
                player,
                direction={
                    "largest_army": True,
                    "biggest_army": True,
                    "preferred_way_id": wid,
                    "way_id": wid,
                },
            )
            out["la_feasibility"] = {
                "hopeless": bool(la_meta.get("hopeless")),
                "reason": la_meta.get("reason"),
                "gap": la_meta.get("gap"),
                "stack_remaining": la_meta.get("stack_remaining"),
            }
            if bool(la_meta.get("hopeless")):
                fit = False
                reasons.append("la_infeasible")
        except Exception:
            pass

    out["fit"] = bool(fit)
    out["reasons"] = reasons
    out["way_lr"] = way_lr
    out["way_la"] = way_la
    out["rem_cities"] = rem_c
    out["rem_settles"] = rem_new_s
    out["n_s"] = n_s
    out["n_c"] = n_c
    out["target_vp"] = target_vp
    out["held_vp"] = held_vp
    out["given_up_lr"] = given_up_lr
    out["given_up_la"] = given_up_la
    return out


def _audit_way_id(audit: Any) -> Optional[int]:
    try:
        if isinstance(audit, Mapping):
            return _safe_int(audit.get("way_id"), None)
        return _safe_int(getattr(audit, "way_id", None), None)
    except Exception:
        return None


def _annotate_fit_note(audit: Any, result: Mapping[str, Any], *, carve: bool = False) -> None:
    prefix = "board_fit_carve:" if carve else "board_fit:"
    note = prefix + (
        "ok" if result.get("fit") else ",".join(result.get("reasons") or ["fail"])
    )
    try:
        notes = list(getattr(audit, "notes", None) or [])
        if isinstance(audit, Mapping):
            notes = list(audit.get("notes") or [])
        notes.append(note)
        if hasattr(audit, "notes"):
            try:
                audit.notes = notes  # type: ignore[attr-defined]
            except Exception:
                pass
        elif isinstance(audit, dict):
            audit["notes"] = notes
    except Exception:
        pass


def _demote_unfit_audit(audit: Any) -> None:
    try:
        if hasattr(audit, "rank_key"):
            audit.rank_key = INFINITE_TURNS  # type: ignore[attr-defined]
        elif isinstance(audit, dict):
            audit["rank_key"] = INFINITE_TURNS
        if hasattr(audit, "feasibility"):
            try:
                audit.feasibility = "board_unfit"  # type: ignore[attr-defined]
            except Exception:
                pass
        elif isinstance(audit, dict):
            audit["feasibility"] = "board_unfit"
        if hasattr(audit, "board_expected_turns"):
            try:
                audit.board_expected_turns = INFINITE_TURNS  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass


def apply_board_fit_to_audits(
    audits: Sequence[Any],
    player: Any,
    *,
    game: Any = None,
    mode: Optional[str] = None,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Demote unfit audits (rank_key → ∞). Re-sort. Keep all for dig.

    If every way fails hard fit **and** the seat has given up LA/LR, re-score
    with ``allow_ignored_specials`` (buildings+VP still hard). If still none
    fit, set ``all_unfit_special_case``.
    """
    mode = normalize_board_fit_mode(mode if mode is not None else get_board_fit_mode(game))
    meta: Dict[str, Any] = {
        "mode": mode,
        "applied": False,
        "n_before": len(list(audits or [])),
        "n_fit": 0,
        "n_unfit": 0,
        "unfit_way_ids": [],
        "all_unfit_special_case": False,
        "giveup_carve_out": False,
        "ignored_specials": [],
    }
    items = list(audits or [])
    if mode == "off" or not items or player is None:
        return items, meta

    meta["applied"] = True

    def _evaluate(allow_ignored: Any) -> Tuple[List[int], List[int], List[Tuple[Any, Dict[str, Any]]]]:
        fit_ids_local: List[int] = []
        unfit_ids_local: List[int] = []
        results: List[Tuple[Any, Dict[str, Any]]] = []
        for audit in items:
            wid = _audit_way_id(audit)
            result = can_realize_way(
                wid,
                player,
                game=game,
                allow_ignored_specials=allow_ignored,
            )
            results.append((audit, result))
            if result.get("soft") or result.get("fit"):
                if wid is not None:
                    fit_ids_local.append(int(wid))
            else:
                unfit_ids_local.append(int(wid) if wid is not None else -1)
        return fit_ids_local, unfit_ids_local, results

    fit_ids, unfit_ids, scored = _evaluate(None)
    carve_ignored = ignored_specials_from_player(player)
    if unfit_ids and not fit_ids and carve_ignored:
        meta["giveup_carve_out"] = True
        meta["ignored_specials"] = sorted(carve_ignored)
        fit_ids, unfit_ids, scored = _evaluate(carve_ignored)

    for audit, result in scored:
        _annotate_fit_note(
            audit, result, carve=bool(meta.get("giveup_carve_out"))
        )
        if result.get("soft") or result.get("fit"):
            continue
        _demote_unfit_audit(audit)

    meta["n_fit"] = len(fit_ids)
    meta["n_unfit"] = len(unfit_ids)
    meta["unfit_way_ids"] = unfit_ids
    meta["fit_way_ids"] = fit_ids

    if unfit_ids and not fit_ids:
        meta["all_unfit_special_case"] = True
        return items, meta

    def _rk(a: Any) -> float:
        try:
            if isinstance(a, Mapping):
                return float(a.get("rank_key", INFINITE_TURNS) or INFINITE_TURNS)
            return float(getattr(a, "rank_key", INFINITE_TURNS) or INFINITE_TURNS)
        except Exception:
            return INFINITE_TURNS

    def _be(a: Any) -> float:
        try:
            if isinstance(a, Mapping):
                return float(a.get("board_expected_turns", INFINITE_TURNS) or INFINITE_TURNS)
            return float(getattr(a, "board_expected_turns", INFINITE_TURNS) or INFINITE_TURNS)
        except Exception:
            return INFINITE_TURNS

    items.sort(key=lambda a: (_rk(a), _be(a), _audit_way_id(a) or 0))
    return items, meta


def sticky_or_direction_way_id(player: Any) -> Optional[int]:
    try:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            w = _safe_int(sticky.get("locked_way_id"), None)
            if w is not None and w > 0:
                return w
    except Exception:
        pass
    try:
        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping):
            w = _safe_int(
                direction.get("preferred_way_id") or direction.get("way_id"), None
            )
            if w is not None and w > 0:
                return w
    except Exception:
        pass
    return None


def way_fits_player(
    way_id: Any,
    player: Any,
    *,
    game: Any = None,
    allow_ignored_specials: Any = None,
    use_player_giveup: bool = False,
) -> bool:
    ignored = allow_ignored_specials
    if use_player_giveup and not ignored:
        ignored = ignored_specials_from_player(player)
    r = can_realize_way(
        way_id, player, game=game, allow_ignored_specials=ignored
    )
    return bool(r.get("fit") or r.get("soft"))


def maybe_force_board_fit(
    game: Any,
    player: Any,
    *,
    reason: str = "board_fit",
) -> Dict[str, Any]:
    """If sticky/preferred way fails board-fit, flag L2 / hard invalid.

    Call after own settlement/city builds and after LA/LR gain (and optionally
    loss). Under ``filter_and_force_switch``, clears sticky so the next explore
    locks a fitting way. See ``docs/Way_board_sync_fix_plan.md`` P1.

    Give-up carve-out: if full fit fails but the seat has kill_la/kill_lr and
    the same way fits with those specials ignored (buildings/VP still ok),
    do **not** clear sticky.
    """
    out: Dict[str, Any] = {
        "checked": False,
        "fit": True,
        "flagged": False,
        "cleared_sticky": False,
        "way_id": None,
        "reasons": [],
        "mode": get_board_fit_mode(game),
        "giveup_carve_out": False,
    }
    mode = out["mode"]
    if mode == "off" or player is None:
        return out

    wid = sticky_or_direction_way_id(player)
    out["way_id"] = wid
    out["checked"] = True
    if wid is None:
        return out

    result = can_realize_way(wid, player, game=game)
    out["fit"] = bool(result.get("fit") or result.get("soft"))
    out["reasons"] = list(result.get("reasons") or [])
    if out["fit"]:
        return out

    carve = ignored_specials_from_player(player)
    if carve:
        result2 = can_realize_way(
            wid, player, game=game, allow_ignored_specials=carve
        )
        if result2.get("fit") or result2.get("soft"):
            out["fit"] = True
            out["giveup_carve_out"] = True
            out["ignored_specials"] = sorted(carve)
            out["reasons"] = list(result2.get("reasons") or [])
            return out

    out["flagged"] = True
    try:
        from core.strategy_sticky import flag_strategy_recalc

        flag_strategy_recalc(
            player,
            "board_fit_mismatch",
            detail={
                "reason": reason,
                "way_id": wid,
                "fit_reasons": out["reasons"],
                "mode": mode,
            },
        )
    except Exception:
        pass
    try:
        player.force_strategy_recalc = True
    except Exception:
        pass

    if mode == "filter_and_force_switch":
        try:
            from core.strategy_sticky import clear_sticky_commitment

            clear_sticky_commitment(player)
            out["cleared_sticky"] = True
        except Exception:
            pass
        try:
            from core.strategy_explicit_recalc import note_hard_invalid

            note_hard_invalid(player, reason=f"board_fit:{','.join(out['reasons'][:3])}")
        except Exception:
            pass

    try:
        player.last_board_fit = dict(out)
    except Exception:
        pass
    if game is not None:
        try:
            game.last_board_fit = dict(out)
            game.last_board_fit_player_id = getattr(player, "id", None)
        except Exception:
            pass
    return out


def maybe_force_board_fit_after_specials(
    game: Any,
    player: Any,
    *,
    reason: str = "specials_board_fit",
) -> Dict[str, Any]:
    """Backward-compatible alias → ``maybe_force_board_fit``."""
    return maybe_force_board_fit(game, player, reason=reason)


def pick_best_fit_audit(
    audits: Sequence[Any],
    player: Any,
    *,
    game: Any = None,
) -> Tuple[Optional[Any], Dict[str, Any]]:
    """First audit that fits (list should already be rank-sorted)."""
    meta: Dict[str, Any] = {"picked_way_id": None, "skipped_unfit": []}
    for audit in list(audits or []):
        wid = _audit_way_id(audit)
        if way_fits_player(wid, player, game=game):
            meta["picked_way_id"] = wid
            return audit, meta
        if wid is not None:
            meta["skipped_unfit"].append(int(wid))
    return (list(audits)[0] if audits else None), meta


__all__ = [
    "MODES",
    "normalize_board_fit_mode",
    "get_board_fit_mode",
    "is_board_fit_enabled",
    "is_board_fit_force_switch",
    "can_realize_way",
    "assess_vp_buyability",
    "ignored_specials_from_player",
    "apply_board_fit_to_audits",
    "sticky_or_direction_way_id",
    "way_fits_player",
    "maybe_force_board_fit",
    "maybe_force_board_fit_after_specials",
    "pick_best_fit_audit",
]
