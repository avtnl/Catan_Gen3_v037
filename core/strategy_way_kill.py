"""S5b: way feasibility kill for Largest Army / Longest Road.

Cheap O(players) checks — no full portfolio re-solve. On kill: one-shot
``force_strategy_recalc`` + clear sticky + latch so the same kill does not
re-fire every refresh.

Logging: ``player.last_way_kill`` / ``game.last_way_kill`` and reason strings
``way_kill: LA infeasible`` / ``way_kill: LR infeasible``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Product defaults (plan §7)
LA_GAP_KILL = 3
LR_GAP_KILL = 4
DCARD_STACK_TINY = 2  # stack remaining at/below this + gap≥1 → LA kill


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _direction_of(player: Any, direction: Any = None) -> Dict[str, Any]:
    if isinstance(direction, Mapping) and direction:
        return dict(direction)
    raw = getattr(player, "strategic_direction", None) if player is not None else None
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def way_id_from_direction(direction: Mapping[str, Any]) -> Optional[int]:
    for key in ("preferred_way_id", "way_id", "locked_way_id"):
        v = direction.get(key)
        if v is None or v == "" or v == "-":
            continue
        try:
            return int(float(v))
        except Exception:
            continue
    return None


def way_needs_largest_army(direction: Mapping[str, Any]) -> bool:
    if not direction:
        return False
    if bool(direction.get("biggest_army") or direction.get("largest_army")):
        return True
    summary = direction.get("strategy_summary") if isinstance(direction.get("strategy_summary"), Mapping) else {}
    if bool(summary.get("biggest_army") or summary.get("largest_army")):
        return True
    wr = direction.get("way_requirements") if isinstance(direction.get("way_requirements"), Mapping) else {}
    if bool(wr.get("biggest_army") or wr.get("largest_army")):
        return True
    tags = direction.get("tags") or []
    text = " ".join(str(t).lower() for t in (tags if isinstance(tags, (list, tuple)) else [tags]))
    if "largest army" in text or "biggest army" in text or text.strip() == "la":
        return True
    if "largest" in text and "army" in text:
        return True
    return False


def way_needs_longest_road(direction: Mapping[str, Any]) -> bool:
    if not direction:
        return False
    if bool(direction.get("longest_road") or direction.get("longest_route")):
        return True
    summary = direction.get("strategy_summary") if isinstance(direction.get("strategy_summary"), Mapping) else {}
    if bool(summary.get("longest_road")):
        return True
    wr = direction.get("way_requirements") if isinstance(direction.get("way_requirements"), Mapping) else {}
    if bool(wr.get("longest_road")):
        return True
    tags = direction.get("tags") or []
    text = " ".join(str(t).lower() for t in (tags if isinstance(tags, (list, tuple)) else [tags]))
    if "longest" in text and "road" in text:
        return True
    return False


def _army_size(player: Any) -> int:
    try:
        return max(0, int(getattr(player, "size_largest_army", 0) or 0))
    except Exception:
        return 0


def _holds_la(player: Any, game: Any = None) -> bool:
    if bool(getattr(player, "largest_army_tf", False)):
        return True
    holder = getattr(game, "largest_army_player", None) if game is not None else None
    if holder is not None and player is not None:
        try:
            return int(getattr(holder, "id", -1)) == int(getattr(player, "id", -2))
        except Exception:
            return holder is player
    return False


def _holds_lr(player: Any, game: Any = None) -> bool:
    if bool(getattr(player, "longest_route_tf", False) or getattr(player, "longest_road_tf", False)):
        return True
    holder = getattr(game, "longest_road_player", None) if game is not None else None
    if holder is not None and player is not None:
        try:
            return int(getattr(holder, "id", -1)) == int(getattr(player, "id", -2))
        except Exception:
            return holder is player
    return False


def _dcard_stack_remaining(game: Any) -> Optional[int]:
    if game is None:
        return None
    stack = getattr(game, "dcards_stack", None)
    if isinstance(stack, (list, tuple)):
        return len(stack)
    try:
        n = getattr(game, "number_of_dcards_left", None)
        if n is not None:
            return int(n)
    except Exception:
        pass
    return None


def _playable_knights_in_hand(player: Any) -> int:
    # dcard_summary row knight: [name, x, y, z] — y playable
    try:
        for row in list(getattr(player, "dcard_summary", None) or []):
            if not row:
                continue
            name = str(row[0] if not isinstance(row, Mapping) else row.get("name", "")).lower()
            if "knight" in name:
                if isinstance(row, Mapping):
                    return max(0, int(row.get("y", row.get("playable", 0)) or 0))
                if len(row) >= 3:
                    return max(0, int(row[2] or 0))
    except Exception:
        pass
    try:
        cards = list(getattr(player, "development_cards", None) or [])
        return sum(1 for c in cards if "knight" in str(c).lower())
    except Exception:
        return 0


def _max_opponent_army(game: Any, player: Any) -> Tuple[int, Optional[int]]:
    own_id = _safe_int(getattr(player, "id", None), -1)
    best = 0
    best_pid = None
    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None), -2)
        if pid == own_id:
            continue
        a = _army_size(p)
        if a > best:
            best = a
            best_pid = pid
    holder = getattr(game, "largest_army_player", None)
    if holder is not None:
        hid = _safe_int(getattr(holder, "id", None), -3)
        if hid != own_id:
            ha = _army_size(holder)
            if ha >= best:
                best = ha
                best_pid = hid
    return best, best_pid


def assess_la_feasibility(
    game: Any,
    player: Any,
    direction: Optional[Mapping[str, Any]] = None,
    *,
    gap_kill: int = LA_GAP_KILL,
) -> Dict[str, Any]:
    """Return {hopeless, reason, gap, own, best_opp, stack, ...}."""
    d = _direction_of(player, direction)
    meta: Dict[str, Any] = {
        "kind": "LA",
        "hopeless": False,
        "reason": "",
        "gap": 0,
        "own_army": 0,
        "best_opp_army": 0,
        "stack_remaining": None,
        "needs_la": False,
    }
    if not way_needs_largest_army(d):
        meta["reason"] = "way_does_not_need_LA"
        return meta
    meta["needs_la"] = True
    if _holds_la(player, game):
        meta["reason"] = "holding_LA"
        return meta

    own = _army_size(player)
    best_opp, opp_id = _max_opponent_army(game, player)
    gap = max(0, best_opp - own)
    stack = _dcard_stack_remaining(game)
    playable = _playable_knights_in_hand(player)
    meta.update(
        {
            "own_army": own,
            "best_opp_army": best_opp,
            "best_opp_id": opp_id,
            "gap": gap,
            "stack_remaining": stack,
            "playable_knights": playable,
        }
    )

    # Potential catch-up: playable + rough stack knights (stack mixed; use //4 as weak bound)
    potential = own + playable
    if stack is not None:
        potential += max(0, min(stack, 5))  # cap optimistic buys

    if gap >= int(gap_kill):
        # Cannot close even with optimistic remaining knights
        if potential < best_opp + 1:
            meta["hopeless"] = True
            meta["reason"] = (
                f"way_kill: LA infeasible (gap={gap}, own={own}, opp={best_opp}, "
                f"stack={stack})"
            )
            return meta

    if stack is not None and stack <= int(DCARD_STACK_TINY) and gap >= 1:
        if potential < best_opp + 1:
            meta["hopeless"] = True
            meta["reason"] = (
                f"way_kill: LA infeasible (stack_tiny={stack}, gap={gap}, own={own}, opp={best_opp})"
            )
            return meta

    meta["reason"] = "LA_still_plausible"
    return meta


def _road_length(game: Any, player: Any) -> int:
    try:
        from core.longest_road import compute_longest_road_for_player

        res = compute_longest_road_for_player(game, player)
        if isinstance(res, Mapping):
            return max(0, int(res.get("length", res.get("size", 0)) or 0))
        return max(0, int(getattr(res, "length", 0) or 0))
    except Exception:
        pass
    try:
        return max(0, int(getattr(player, "size_longest_route", 0) or 0))
    except Exception:
        return 0


def _max_opponent_road_length(game: Any, player: Any) -> Tuple[int, Optional[int]]:
    own_id = _safe_int(getattr(player, "id", None), -1)
    best = 0
    best_pid = None
    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None), -2)
        if pid == own_id:
            continue
        n = _road_length(game, p)
        if n > best:
            best = n
            best_pid = pid
    holder = getattr(game, "longest_road_player", None)
    if holder is not None:
        hid = _safe_int(getattr(holder, "id", None), -3)
        if hid != own_id:
            hn = _road_length(game, holder)
            if hn >= best:
                best = hn
                best_pid = hid
    return best, best_pid


def assess_lr_feasibility(
    game: Any,
    player: Any,
    direction: Optional[Mapping[str, Any]] = None,
    *,
    gap_kill: int = LR_GAP_KILL,
) -> Dict[str, Any]:
    """Return {hopeless, reason, gap, own_len, best_opp_len, live_claim}."""
    d = _direction_of(player, direction)
    meta: Dict[str, Any] = {
        "kind": "LR",
        "hopeless": False,
        "reason": "",
        "gap": 0,
        "own_len": 0,
        "best_opp_len": 0,
        "live_claim": False,
        "needs_lr": False,
    }
    if not way_needs_longest_road(d):
        meta["reason"] = "way_does_not_need_LR"
        return meta
    meta["needs_lr"] = True
    if _holds_lr(player, game):
        meta["reason"] = "holding_LR"
        return meta

    own = _road_length(game, player)
    best_opp, opp_id = _max_opponent_road_length(game, player)
    gap = max(0, best_opp - own)
    meta.update(
        {
            "own_len": own,
            "best_opp_len": best_opp,
            "best_opp_id": opp_id,
            "gap": gap,
        }
    )

    live_claim = False
    try:
        from core.ai_road_planner import ai_road_longest_road_exception_active

        live_claim = bool(ai_road_longest_road_exception_active(game, player))
    except Exception:
        live_claim = False
    meta["live_claim"] = live_claim

    if gap >= int(gap_kill) and not live_claim:
        meta["hopeless"] = True
        meta["reason"] = (
            f"way_kill: LR infeasible (gap={gap}, own={own}, opp={best_opp}, no_claim_edge)"
        )
        return meta

    meta["reason"] = "LR_still_plausible"
    return meta


def _latch_blocks(player: Any, way_id: Optional[int], kind: str, game: Any) -> bool:
    """True if same kill already latched for this way (and holders unchanged)."""
    latch = getattr(player, "way_kill_latch", None)
    if not isinstance(latch, Mapping):
        return False
    if str(latch.get("kind") or "") != str(kind):
        return False
    if way_id is not None and _safe_int(latch.get("way_id"), -999) != int(way_id):
        return False
    # Holder change clears latch effect
    if kind == "LA":
        cur_holder = getattr(game, "largest_army_player", None) if game is not None else None
        latched = latch.get("holder_id")
        try:
            cur_id = int(getattr(cur_holder, "id", -1)) if cur_holder is not None else None
        except Exception:
            cur_id = None
        if latched is not None and cur_id is not None and int(latched) != int(cur_id):
            return False
    if kind == "LR":
        cur_holder = getattr(game, "longest_road_player", None) if game is not None else None
        latched = latch.get("holder_id")
        try:
            cur_id = int(getattr(cur_holder, "id", -1)) if cur_holder is not None else None
        except Exception:
            cur_id = None
        if latched is not None and cur_id is not None and int(latched) != int(cur_id):
            return False
    return True


def _set_latch(player: Any, *, way_id: Optional[int], kind: str, game: Any, reason: str) -> None:
    holder = None
    if kind == "LA":
        h = getattr(game, "largest_army_player", None) if game is not None else None
        holder = _safe_int(getattr(h, "id", None), None) if h is not None else None
    elif kind == "LR":
        h = getattr(game, "longest_road_player", None) if game is not None else None
        holder = _safe_int(getattr(h, "id", None), None) if h is not None else None
    latch = {
        "way_id": way_id,
        "kind": kind,
        "round": _safe_int(getattr(game, "round", 0), 0) if game is not None else 0,
        "turn": _safe_int(getattr(game, "turn", 0), 0) if game is not None else 0,
        "holder_id": holder,
        "reason": reason,
    }
    try:
        setattr(player, "way_kill_latch", latch)
    except Exception:
        pass


def _fire_kill(
    game: Any,
    player: Any,
    *,
    kind: str,
    reason: str,
    way_id: Optional[int],
    detail: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    from core.strategy_sticky import (
        clear_sticky_commitment,
        flag_strategy_recalc,
    )

    flag_strategy_recalc(
        player,
        f"way_kill_{kind}_infeasible",
        detail=dict(detail or {}) | {"reason": reason, "way_id": way_id},
    )
    try:
        setattr(player, "force_strategy_recalc", True)
    except Exception:
        pass
    clear_sticky_commitment(player)
    # P2-B: S5b kill / S14-class — drop portfolio so next refresh re-evals
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(
            game, f"way_kill_{kind}:{reason}"
        )
    except Exception:
        pass
    # S-LA-A: drop LA progress object even if sticky was already empty
    if kind == "LA":
        try:
            from core.ai_la_progress import clear_la_progress_from_sticky

            clear_la_progress_from_sticky(player, game)
        except Exception:
            pass
        try:
            setattr(player, "la_progress", None)
        except Exception:
            pass
    _set_latch(player, way_id=way_id, kind=kind, game=game, reason=reason)

    payload = {
        "killed": True,
        "kind": kind,
        "reason": reason,
        "way_id": way_id,
        "round": _safe_int(getattr(game, "round", 0), 0) if game is not None else 0,
        "turn": _safe_int(getattr(game, "turn", 0), 0) if game is not None else 0,
        "detail": dict(detail or {}),
    }
    try:
        setattr(player, "last_way_kill", dict(payload))
    except Exception:
        pass
    try:
        if game is not None:
            setattr(game, "last_way_kill", dict(payload))
    except Exception:
        pass
    try:
        if game is not None and bool(getattr(game, "execution_debug_print_tf", False)):
            print(f"DBG {reason}")
    except Exception:
        pass
    return payload


def apply_way_feasibility_kills(
    game: Any,
    player: Any,
    direction: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run LA then LR kill checks. At most one kill fires per call.

    Returns meta: killed, kind, reason, latched, la_assess, lr_assess.
    """
    out: Dict[str, Any] = {
        "killed": False,
        "kind": "",
        "reason": "",
        "latched": False,
        "way_id": None,
        "la_assess": {},
        "lr_assess": {},
        "s5b": True,
    }
    if player is None:
        out["reason"] = "no_player"
        return out

    d = _direction_of(player, direction)
    way_id = way_id_from_direction(d)
    out["way_id"] = way_id

    la = assess_la_feasibility(game, player, d)
    out["la_assess"] = la
    if la.get("hopeless"):
        if _latch_blocks(player, way_id, "LA", game):
            out["latched"] = True
            out["reason"] = "latched_LA"
            return out
        fired = _fire_kill(
            game,
            player,
            kind="LA",
            reason=str(la.get("reason") or "way_kill: LA infeasible"),
            way_id=way_id,
            detail=la,
        )
        out.update(fired)
        return out

    lr = assess_lr_feasibility(game, player, d)
    out["lr_assess"] = lr
    if lr.get("hopeless"):
        if _latch_blocks(player, way_id, "LR", game):
            out["latched"] = True
            out["reason"] = "latched_LR"
            return out
        fired = _fire_kill(
            game,
            player,
            kind="LR",
            reason=str(lr.get("reason") or "way_kill: LR infeasible"),
            way_id=way_id,
            detail=lr,
        )
        out.update(fired)
        return out

    out["reason"] = "no_kill"
    return out


def pick_audit_excluding_way(audits: Sequence[Any], blocked_way_id: Optional[int]) -> Any:
    """First audit whose way_id is not blocked (for re-pick after kill)."""
    if blocked_way_id is None:
        return audits[0] if audits else None
    blocked = int(blocked_way_id)
    for a in list(audits or []):
        try:
            if isinstance(a, Mapping):
                wid = int(float(a.get("way_id", -1)))
            else:
                wid = int(float(getattr(a, "way_id", -1)))
        except Exception:
            continue
        if wid != blocked:
            return a
    return audits[0] if audits else None


def pick_audit_excluding_specials(
    audits: Sequence[Any],
    *,
    kill_la: bool = False,
    kill_lr: bool = False,
    blocked_way_id: Optional[int] = None,
) -> Any:
    """Prefer audits that do not need dead specials; fall back to exclude way_id.

    Used after give-up / S5b when a specials-dead episode is active (WP2).
    """
    src = list(audits or [])
    if not src:
        return None
    if kill_la or kill_lr:
        try:
            from core.strategy_specials_divert import filter_ways_without_specials

            filtered = filter_ways_without_specials(
                src, kill_la=bool(kill_la), kill_lr=bool(kill_lr)
            )
            if filtered:
                return filtered[0]
        except Exception:
            pass
    if blocked_way_id is not None:
        return pick_audit_excluding_way(src, blocked_way_id)
    return src[0]


def format_way_kill_dbg(meta: Mapping[str, Any]) -> str:
    if not meta:
        return "way_kill: n/a"
    if meta.get("killed"):
        return str(meta.get("reason") or f"way_kill: {meta.get('kind')}")
    if meta.get("latched"):
        return f"way_kill: latched {meta.get('reason')}"
    return f"way_kill: skip {meta.get('reason') or 'ok'}"
