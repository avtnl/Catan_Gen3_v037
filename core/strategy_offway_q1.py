"""P1+Q1: post-scan off-way settlement/city → L2 once before BA.

Restricts full L2 explore to cases where a *legal* settle/city target is not
part of the sticky / preferred Victory-Way structure set. Pure hand noise
stays on P1 true-light L0.

Does not cover off-way DCard (P1+Q2) or roads.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

STRUCTURE_ACTIONS = frozenset({
    "build city",
    "build settlement",
})

# Normalized action name fragments that count as structure families
_STRUCTURE_FRAGMENTS = (
    "build city",
    "build settlement",
    "city_upgrade",
    "next_settlement",
    "new_settlement",
)


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _norm_action(name: Any) -> str:
    return str(name or "").strip().lower().replace("_", " ")


def is_structure_action_name(name: Any) -> bool:
    n = _norm_action(name)
    if n in STRUCTURE_ACTIONS:
        return True
    # allow "build city" / fragments with extra words
    for frag in _STRUCTURE_FRAGMENTS:
        if frag in n:
            # exclude pure road
            if "road" in n and "settlement" not in n and "city" not in n:
                return False
            return True
    return False


def _add_structure_id(out: Set[int], value: Any) -> None:
    tid = _safe_int(value, None)
    if tid is not None and tid >= 0:
        out.add(int(tid))


def _add_from_mapping_targets(out: Set[int], m: Mapping[str, Any]) -> None:
    if not isinstance(m, Mapping):
        return
    for key in (
        "locked_rec_target_id",
        "recommendation_target_id",
        "settlement_target_id",
        "new_settlement_target_id",
        "city_upgrade_target_id",
        "target_id",
        "intersection_id",
        "rec_target_id",
        "board_recommendation_target_id",
    ):
        _add_structure_id(out, m.get(key))
    pt = m.get("project_target")
    if isinstance(pt, Mapping):
        for key in ("target_id", "intersection_id", "recommendation_target_id"):
            _add_structure_id(out, pt.get(key))
    for t in list(m.get("target_portfolio") or []):
        if isinstance(t, Mapping):
            for key in ("target_id", "intersection_id", "id"):
                _add_structure_id(out, t.get(key))
        else:
            try:
                if hasattr(t, "target_id"):
                    _add_structure_id(out, getattr(t, "target_id"))
            except Exception:
                pass


def _preferred_way_id(player: Any) -> Optional[int]:
    if player is None:
        return None
    for src in (
        getattr(player, "sticky_commitment", None),
        getattr(player, "strategic_direction", None),
    ):
        if not isinstance(src, Mapping):
            continue
        for key in ("locked_way_id", "preferred_way_id", "way_id"):
            wid = _safe_int(src.get(key), None)
            if wid is not None and wid > 0:
                return wid
    return None


def collect_on_way_structure_ids(
    player: Any,
    game: Any = None,
) -> Set[int]:
    """Intersection ids considered on sticky / preferred Victory-Way."""
    out: Set[int] = set()
    if player is None:
        return out

    sticky = getattr(player, "sticky_commitment", None)
    if isinstance(sticky, Mapping):
        _add_from_mapping_targets(out, sticky)
        # LR project may name a settlement tip
        lr = sticky.get("lr_project")
        if isinstance(lr, Mapping):
            _add_structure_id(out, lr.get("target_id"))
            _add_structure_id(out, lr.get("settlement_target_id"))

    direction = getattr(player, "strategic_direction", None)
    if isinstance(direction, Mapping):
        _add_from_mapping_targets(out, direction)

    # Cached board audit for locked/preferred way (no full L2)
    if game is not None:
        try:
            want = _preferred_way_id(player)
            audits = list(getattr(game, "current_board_way_audits", None) or [])
            single = getattr(game, "current_board_way_audit", None)
            if single is not None and single not in audits:
                audits = [single] + audits
            for a in audits:
                if a is None:
                    continue
                if isinstance(a, Mapping):
                    wid = _safe_int(a.get("way_id"), None)
                    port = a.get("target_portfolio") or []
                    rec = a.get("recommendation_target_id")
                else:
                    wid = _safe_int(getattr(a, "way_id", None), None)
                    port = getattr(a, "target_portfolio", None) or []
                    rec = getattr(a, "recommendation_target_id", None)
                if want is not None and wid is not None and wid != want:
                    continue
                _add_structure_id(out, rec)
                for t in list(port or []):
                    if isinstance(t, Mapping):
                        _add_structure_id(out, t.get("target_id") or t.get("intersection_id"))
                    else:
                        _add_structure_id(out, getattr(t, "target_id", None))
        except Exception:
            pass

    return out


def _target_id_from_row(row: Mapping[str, Any]) -> Optional[int]:
    tid = _safe_int(row.get("target_id"), None)
    if tid is not None:
        return tid
    tid = _safe_int(row.get("intersection_id"), None)
    if tid is not None:
        return tid
    cands = list(row.get("candidates") or [])
    for c in cands:
        if not isinstance(c, Mapping):
            continue
        tid = _safe_int(
            c.get("target_id")
            or c.get("intersection_id")
            or c.get("settlement_id")
            or c.get("city_id"),
            None,
        )
        if tid is not None:
            return tid
    return None


def _row_is_viable_structure(row: Mapping[str, Any]) -> bool:
    if not isinstance(row, Mapping):
        return False
    action = row.get("action") or row.get("name") or row.get("action_name")
    if not is_structure_action_name(action):
        return False
    # Prefer explicit viable/legal flags when present; default True if row listed
    if "viable" in row and not bool(row.get("viable")):
        return False
    if "legal" in row and not bool(row.get("legal")):
        return False
    # Do not require actionable (strategic) — D2
    return True


def iter_affordable_structure_candidates(game: Any) -> List[Dict[str, Any]]:
    """Legal structure rows from scan / execution choices (viable, not only BA-actionable)."""
    if game is None:
        return []
    seen: Set[Tuple[str, int]] = set()
    out: List[Dict[str, Any]] = []

    def _consume(rows: Any) -> None:
        for row in list(rows or []):
            if not isinstance(row, Mapping):
                continue
            if not _row_is_viable_structure(row):
                continue
            action = str(row.get("action") or row.get("name") or "")
            # Expand multi-candidate rows
            cands = list(row.get("candidates") or [])
            if cands:
                for c in cands:
                    if not isinstance(c, Mapping):
                        continue
                    tid = _safe_int(
                        c.get("target_id")
                        or c.get("intersection_id")
                        or c.get("settlement_id"),
                        None,
                    )
                    if tid is None:
                        continue
                    key = (_norm_action(action), int(tid))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "action": action,
                        "target_id": int(tid),
                        "source": "candidate",
                    })
            else:
                tid = _target_id_from_row(row)
                if tid is None:
                    continue
                key = (_norm_action(action), int(tid))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "action": action,
                    "target_id": int(tid),
                    "source": "row",
                })

    # Prefer full execution choices (all buy/build families with viable flag)
    _consume(getattr(game, "current_execution_choices", None))
    # Also actionable (subset) — covered by above when present
    _consume(getattr(game, "current_actionable_choices", None))

    # Scan dict fallback: scan_viable_actions / candidates by action name
    scan = getattr(game, "current_viable_action_scan", None)
    if isinstance(scan, Mapping):
        cands_map = scan.get("candidates")
        if isinstance(cands_map, Mapping):
            for aname, clist in cands_map.items():
                if not is_structure_action_name(aname):
                    continue
                for c in list(clist or []):
                    if not isinstance(c, Mapping):
                        continue
                    tid = _safe_int(
                        c.get("target_id")
                        or c.get("intersection_id")
                        or c.get("settlement_id"),
                        None,
                    )
                    if tid is None:
                        continue
                    key = (_norm_action(aname), int(tid))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "action": str(aname),
                        "target_id": int(tid),
                        "source": "scan_candidates",
                    })

    return out


def detect_offway_affordable_structures(
    game: Any,
    player: Any = None,
) -> Dict[str, Any]:
    """Pure detect: affordable settle/city targets not on sticky/way set."""
    result: Dict[str, Any] = {
        "hit": False,
        "offway": [],
        "on_way_ids": [],
        "reason": "",
        "preferred_way_id": None,
    }
    if game is None:
        result["reason"] = "no_game"
        return result
    if player is None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None
    if player is None:
        result["reason"] = "no_player"
        return result

    wid = _preferred_way_id(player)
    result["preferred_way_id"] = wid
    if wid is None:
        result["reason"] = "no_preferred_or_sticky_way"
        return result

    on_way = collect_on_way_structure_ids(player, game)
    result["on_way_ids"] = sorted(on_way)

    offway: List[Dict[str, Any]] = []
    for cand in iter_affordable_structure_candidates(game):
        tid = int(cand["target_id"])
        if tid in on_way:
            continue
        offway.append(dict(cand))

    result["offway"] = offway
    if offway:
        result["hit"] = True
        result["reason"] = f"offway_structure_n={len(offway)}"
    else:
        result["reason"] = "no_offway_structure"
    return result


# ─── Latch (once per seat / own-turn token) ─────────────────────────────────


def _turn_token(game: Any, player: Any) -> Tuple[Any, Any, Any]:
    pid = getattr(player, "id", None) if player is not None else None
    rnd = getattr(game, "round", None) if game is not None else None
    # Prefer explicit turn counter; fall back to sequence/state
    turn = getattr(game, "turn", None) if game is not None else None
    return (pid, rnd, turn)


def get_q1_latch(player: Any) -> Dict[str, Any]:
    raw = getattr(player, "q1_offway_l2_latch", None) if player is not None else None
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def q1_latch_blocks(game: Any, player: Any) -> bool:
    """True if Q1 already ran or was satisfied this own-turn episode."""
    latch = get_q1_latch(player)
    if not (latch.get("fired") or latch.get("resolved") or latch.get("skipped_satisfied")):
        return False
    token = _turn_token(game, player)
    return (
        latch.get("player_id") == token[0]
        and latch.get("round") == token[1]
        and latch.get("turn") == token[2]
    )


def mark_q1_latch(
    player: Any,
    game: Any,
    *,
    reason: str = "",
    offway: Optional[Sequence[Mapping[str, Any]]] = None,
    skipped: bool = False,
) -> Dict[str, Any]:
    token = _turn_token(game, player)
    bag = {
        "fired": not bool(skipped),
        "skipped_satisfied": bool(skipped),
        "resolved": True,  # blocks re-entry this turn either way
        "player_id": token[0],
        "round": token[1],
        "turn": token[2],
        "reason": str(reason or ""),
        "offway_targets": [
            {"action": r.get("action"), "target_id": r.get("target_id")}
            for r in list(offway or [])
            if isinstance(r, Mapping)
        ][:12],
    }
    if player is not None:
        try:
            setattr(player, "q1_offway_l2_latch", bag)
        except Exception:
            pass
    return bag


def clear_q1_latch(player: Any) -> None:
    if player is None:
        return
    try:
        setattr(player, "q1_offway_l2_latch", None)
    except Exception:
        pass


def _already_explored_this_step(game: Any) -> bool:
    """If last strategy refresh was already L2 explore, skip another full pass."""
    st = getattr(game, "last_strategy_context_status", None)
    if not isinstance(st, Mapping):
        return False
    mode = str(st.get("refresh_mode") or "").lower()
    if mode in ("explore", "l2", "force"):
        return bool(st.get("ok") is not False)
    return False


def maybe_q1_offway_structure_l2(
    game: Any,
    player: Any = None,
    *,
    reason: str = "",
    rescan: bool = True,
) -> Dict[str, Any]:
    """If post-scan off-way settle/city exists, run L2 once then optional rescan.

    Returns status dict for dig-in / Slice D.
    """
    status: Dict[str, Any] = {
        "fired": False,
        "skipped": True,
        "reason": "",
        "detect": {},
        "refresh": None,
        "latch": {},
    }
    if game is None:
        status["reason"] = "no_game"
        return status

    try:
        phase = str(getattr(game, "phase", "") or "")
    except Exception:
        phase = ""
    if phase != "Execution":
        status["reason"] = "not_execution"
        return status

    state = str(getattr(game, "state", "") or "")
    # Allow ActionSelection and close cousins; skip forced robber/discard pre-dice
    if state in {
        "AwaitingDiceRoll",
        "MoveRobber",
        "RobberMoveRequired",
        "SetRobber",
        "StealSelectOpponent",
        "DiscardPending",
    }:
        status["reason"] = f"blocked_state:{state}"
        return status

    if player is None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None
    if player is None:
        status["reason"] = "no_player"
        return status

    if q1_latch_blocks(game, player):
        status["reason"] = "latch_already_fired"
        status["latch"] = get_q1_latch(player)
        return status

    det = detect_offway_affordable_structures(game, player)
    status["detect"] = det
    if not det.get("hit"):
        status["reason"] = str(det.get("reason") or "no_hit")
        return status

    # Already did full explore this step (e.g. milestone) → mark satisfied, no second L2
    if _already_explored_this_step(game):
        latch = mark_q1_latch(
            player,
            game,
            reason="already_explored_satisfied",
            offway=det.get("offway") or [],
            skipped=True,
        )
        status["skipped"] = True
        status["reason"] = "already_explored_this_step"
        status["latch"] = latch
        status["fired"] = False
        return status

    try:
        from core.performance_trace import timed_span
    except Exception:
        timed_span = None  # type: ignore
    from contextlib import nullcontext

    span_cm = (
        timed_span(
            game,
            "q1_offway_l2",
            meta={
                "reason": str(reason or ""),
                "offway_n": len(det.get("offway") or []),
                "preferred_way_id": det.get("preferred_way_id"),
            },
        )
        if timed_span is not None
        else nullcontext({"meta": {}})
    )

    with span_cm as span_bag:
        # Bridge into should_run_l2_explore / explore path
        try:
            from core.strategy_reconsider import set_reconsider_flag

            set_reconsider_flag(
                player,
                "off_strategy_opportunity",
                reason=f"q1_offway:{det.get('reason')}",
                value=True,
            )
        except Exception:
            try:
                setattr(player, "force_strategy_recalc", True)
            except Exception:
                pass

        refresh_status = None
        try:
            ref = getattr(game, "refresh_strategy_context", None)
            if callable(ref):
                refresh_status = ref(
                    str(reason or "q1_offway_structure") + "+q1_offway",
                    mode="explore",
                )
            else:
                status["reason"] = "no_refresh_strategy_context"
                return status
        except Exception as exc:
            status["reason"] = f"l2_failed:{exc}"
            status["refresh"] = {"error": str(exc)}
            return status

        status["refresh"] = refresh_status if isinstance(refresh_status, dict) else {"raw": refresh_status}

        # Latch even if explore had soft issues — avoid thrash loops
        latch = mark_q1_latch(
            player,
            game,
            reason=str(det.get("reason") or "q1_offway"),
            offway=det.get("offway") or [],
            skipped=False,
        )
        status["latch"] = latch
        status["fired"] = True
        status["skipped"] = False
        status["reason"] = "l2_fired"

        if rescan:
            try:
                rva = getattr(game, "refresh_viable_actions", None)
                if callable(rva):
                    rva(str(reason or "q1_offway") + "+q1_post")
            except Exception as exc:
                status["rescan_error"] = str(exc)

        try:
            if isinstance(span_bag, dict):
                meta = span_bag.get("meta")
                if not isinstance(meta, dict):
                    meta = {}
                    span_bag["meta"] = meta
                meta["fired"] = True
                meta["offway_n"] = len(det.get("offway") or [])
                meta["way_count"] = 1
        except Exception:
            pass

    try:
        game.last_q1_offway_status = dict(status)
    except Exception:
        pass
    return status
