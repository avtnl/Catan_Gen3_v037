"""S1: sticky target + route commitment + refresh policy.

Stops mid-route rec-target / way thrash across refresh_strategy_context by
persisting (locked_way_id, locked_rec_target_id, locked_roads_to_build) until
an invalidate event fires.

Board-shock policy (batched recalc flag):
  - Opponent settlement/city → flag other players (idempotent). Multiple
    opponents building between our turns still yields **one** way re-rank when
    the flag is consumed.
  - Own rec settle/city complete, or acquiring LA/LR:
      * has legal actions → force immediate way/target re-rank
      * no legal actions → same flag only (recalc once later)

Hard invalidators (always kill sticky when evaluated):
  - own rec settle completed; target occupied; race likely_lost;
    route edges illegal; locked way feasibility killed
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

STICKY_OPP_ROAD_RADIUS = 2

_FEAS_KILL = frozenset({"unrealistic", "impossible"})

# Actions that do not count as "still has something to do this turn".
_NON_BUILD_ACTION_NAMES = frozenset({
    "",
    "end turn",
    "pass",
    "roll dices",
    "roll dice",
    "none",
    "skip",
})


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _audit_get(audit: Any, key: str, default: Any = None) -> Any:
    if audit is None:
        return default
    if isinstance(audit, Mapping):
        return audit.get(key, default)
    return getattr(audit, key, default)


def _road_key(edge: Any) -> Optional[Tuple[int, int]]:
    try:
        if isinstance(edge, Mapping):
            a = edge.get("a", edge.get(0))
            b = edge.get("b", edge.get(1))
            if a is None or b is None:
                pair = list(edge.values())[:2]
                a, b = pair[0], pair[1]
            return tuple(sorted((int(a), int(b))))  # type: ignore[return-value]
        if isinstance(edge, (list, tuple)) and len(edge) >= 2:
            return tuple(sorted((int(edge[0]), int(edge[1]))))  # type: ignore[return-value]
    except Exception:
        return None
    return None


def _normalize_roads(roads: Any) -> List[List[int]]:
    out: List[List[int]] = []
    seen = set()
    for edge in list(roads or []):
        key = _road_key(edge)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append([int(key[0]), int(key[1])])
    return out


def get_sticky_commitment(player: Any) -> Optional[Dict[str, Any]]:
    """Return sticky portfolio if structure lock, LR project, and/or LA progress present."""
    if player is None:
        return None
    raw = getattr(player, "sticky_commitment", None)
    if not isinstance(raw, Mapping):
        return None
    tid = _safe_int(raw.get("locked_rec_target_id"), None)
    lr = raw.get("lr_project")
    has_lr = isinstance(lr, Mapping) and bool(lr.get("roads_to_build"))
    la = raw.get("la_progress")
    has_la = isinstance(la, Mapping) and bool(la)
    if tid is None and not has_lr and not has_la:
        return None
    return dict(raw)


def set_sticky_commitment(player: Any, commitment: Optional[Mapping[str, Any]]) -> bool:
    if player is None:
        return False
    try:
        if commitment is None:
            setattr(player, "sticky_commitment", None)
        else:
            setattr(player, "sticky_commitment", dict(commitment))
        return True
    except Exception:
        return False


def clear_sticky_commitment(player: Any) -> bool:
    return set_sticky_commitment(player, None)


# ---------------------------------------------------------------------------
# Batched strategy-recalc flag (one re-rank after many opponent builds)
# ---------------------------------------------------------------------------

def get_strategy_recalc_flag(player: Any) -> Dict[str, Any]:
    raw = getattr(player, "strategy_recalc_flag", None) if player is not None else None
    if not isinstance(raw, Mapping):
        return {
            "pending": False,
            "reasons": [],
            "builders": [],
            "events": [],
        }
    return {
        "pending": bool(raw.get("pending")),
        "reasons": list(raw.get("reasons") or []),
        "builders": list(raw.get("builders") or []),
        "events": list(raw.get("events") or []),
    }


def set_strategy_recalc_flag(player: Any, flag: Optional[Mapping[str, Any]]) -> bool:
    if player is None:
        return False
    try:
        if flag is None:
            setattr(player, "strategy_recalc_flag", None)
        else:
            setattr(player, "strategy_recalc_flag", dict(flag))
        return True
    except Exception:
        return False


def clear_strategy_recalc_flag(player: Any) -> bool:
    try:
        if player is not None:
            setattr(player, "force_strategy_recalc", False)
    except Exception:
        pass
    return set_strategy_recalc_flag(player, None)


def flag_strategy_recalc(
    player: Any,
    reason: str,
    *,
    builder_id: Optional[int] = None,
    detail: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """OR a reason onto the player's pending strategy-recalc flag (idempotent).

    Also dual-writes into ``strategy_reconsider_flags`` so turn-start
    ``mode=auto`` / ``should_run_l2_explore`` sees the batch without waiting
    for sticky apply (policy a/b/c).
    """
    flag = get_strategy_recalc_flag(player)
    flag["pending"] = True
    reasons = list(flag.get("reasons") or [])
    reason_s = str(reason or "strategy_recalc").strip() or "strategy_recalc"
    if reason_s not in reasons:
        reasons.append(reason_s)
    flag["reasons"] = reasons
    if builder_id is not None:
        builders = list(flag.get("builders") or [])
        try:
            bid = int(builder_id)
            if bid not in builders:
                builders.append(bid)
        except Exception:
            pass
        flag["builders"] = builders
    events = list(flag.get("events") or [])
    ev: Dict[str, Any] = {"reason": reason_s}
    if builder_id is not None:
        ev["builder_id"] = builder_id
    if detail:
        ev["detail"] = dict(detail)
    events.append(ev)
    # Cap event log
    flag["events"] = events[-12:]
    set_strategy_recalc_flag(player, flag)
    # Dual-write L1 significance for dice-time L2 gate
    try:
        from core.strategy_reconsider import map_recalc_reason_to_flag, set_reconsider_flag

        set_reconsider_flag(
            player,
            map_recalc_reason_to_flag(reason_s),
            reason=reason_s,
        )
    except Exception:
        pass
    return flag


def flag_opponents_after_structure(
    game: Any,
    builder: Any,
    structure: str,
    *,
    target_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Flag every non-builder player after an opponent settlement/city.

    Multiple opponent builds only keep ``pending=True`` with accumulated
    reasons/builders — strategy re-rank happens once when the flag is consumed.
    """
    kind = str(structure or "structure").lower()
    if "city" in kind:
        reason = "opponent_city"
    elif "sett" in kind:
        reason = "opponent_settlement"
    else:
        reason = "opponent_structure"
    builder_id = _safe_int(getattr(builder, "id", None), None)
    flagged: List[int] = []
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (builder_id is not None and pid == builder_id):
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=builder_id,
            detail={"target_id": target_id, "structure": kind},
        )
        flagged.append(pid)
    # P2-B: board piece change → drop portfolio cache for all seats
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(game, f"structure:{reason}")
    except Exception:
        pass
    return {
        "reason": reason,
        "builder_id": builder_id,
        "flagged_player_ids": flagged,
        "structure": kind,
        "target_id": target_id,
    }


def _player_pursues_longest_road(player: Any) -> bool:
    """True if preferred way still cares about LR (tags / summary / sticky)."""
    try:
        from core.strategy_way_kill import way_needs_longest_road

        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping) and way_needs_longest_road(direction):
            return True
    except Exception:
        pass
    try:
        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping):
            if bool(direction.get("longest_road") or direction.get("longest_route")):
                return True
            tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
            if "longest" in tags and "road" in tags:
                return True
    except Exception:
        pass
    return False


def _player_pursues_largest_army(player: Any) -> bool:
    """True if preferred way still cares about LA."""
    try:
        from core.strategy_way_kill import way_needs_largest_army

        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping) and way_needs_largest_army(direction):
            return True
    except Exception:
        pass
    try:
        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping):
            if bool(direction.get("biggest_army") or direction.get("largest_army")):
                return True
            tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
            if "army" in tags or "largest" in tags:
                return True
    except Exception:
        pass
    return False


def flag_opponents_after_road(
    game: Any,
    builder: Any,
    *,
    road_id: Any = None,
    only_lr_pursuers: bool = True,
) -> Dict[str, Any]:
    """S1 extension: batch-flag after opponent road (LR landscape).

    Default: only flag players whose way still pursues Longest Road (less noise
    than settle/city global flags). Multiple roads still collapse to one re-rank
    when the flag is consumed.
    """
    reason = "opponent_road"
    builder_id = _safe_int(getattr(builder, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (builder_id is not None and pid == builder_id):
            continue
        if only_lr_pursuers and not _player_pursues_longest_road(p):
            skipped.append(pid)
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=builder_id,
            detail={"road_id": road_id, "structure": "road"},
        )
        flagged.append(pid)
    # P2-B: road mutates board connectivity / LR landscape
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(game, f"road:{reason}")
    except Exception:
        pass
    return {
        "reason": reason,
        "builder_id": builder_id,
        "flagged_player_ids": flagged,
        "skipped_non_lr_player_ids": skipped,
        "road_id": road_id,
        "only_lr_pursuers": bool(only_lr_pursuers),
    }


def flag_opponents_after_knight(
    game: Any,
    player: Any,
    *,
    only_la_pursuers: bool = True,
    army_size: Any = None,
) -> Dict[str, Any]:
    """S1 extension: batch-flag after a knight is played (LA gap, even pre-steal).

    Default: only flag players whose way still pursues Largest Army.
    Holder flips still also set lost_largest_army / own_largest_army separately.
    """
    reason = "opponent_knight"
    actor_id = _safe_int(getattr(player, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (actor_id is not None and pid == actor_id):
            continue
        if only_la_pursuers and not _player_pursues_largest_army(p):
            skipped.append(pid)
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=actor_id,
            detail={"army_size": army_size, "structure": "knight"},
        )
        flagged.append(pid)
    return {
        "reason": reason,
        "builder_id": actor_id,
        "flagged_player_ids": flagged,
        "skipped_non_la_player_ids": skipped,
        "army_size": army_size,
        "only_la_pursuers": bool(only_la_pursuers),
    }


def flag_opponents_after_dcard_buy(
    game: Any,
    buyer: Any,
    *,
    only_la_pursuers: bool = True,
) -> Dict[str, Any]:
    """Weak S1 extension: opp bought a DCard (deck thins toward LA).

    Only flags LA-pursuing opponents by default. Prefer knight-play flags for
    strong army-gap updates.
    """
    reason = "opponent_dcard_buy"
    buyer_id = _safe_int(getattr(buyer, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (buyer_id is not None and pid == buyer_id):
            continue
        if only_la_pursuers and not _player_pursues_largest_army(p):
            skipped.append(pid)
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=buyer_id,
            detail={"structure": "dcard_buy"},
        )
        flagged.append(pid)
    return {
        "reason": reason,
        "builder_id": buyer_id,
        "flagged_player_ids": flagged,
        "skipped_non_la_player_ids": skipped,
        "only_la_pursuers": bool(only_la_pursuers),
    }


def player_has_legal_actions(game: Any, player: Any = None) -> bool:
    """True if the current scan shows a non-pass/end/roll action.

    Defaults to True when scan data is missing (safer: force recalc).
    """
    skip = _NON_BUILD_ACTION_NAMES

    def _name_of(item: Any) -> str:
        if item is None:
            return ""
        if isinstance(item, Mapping):
            return str(
                item.get("action")
                or item.get("name")
                or item.get("label")
                or item.get("action_name")
                or ""
            ).strip().lower()
        return str(getattr(item, "action", None) or getattr(item, "name", None) or "").strip().lower()

    def _any_real(seq: Any) -> Optional[bool]:
        found_any = False
        for item in list(seq or []):
            found_any = True
            name = _name_of(item)
            if name not in skip:
                return True
        if found_any:
            return False
        return None

    for attr in (
        "current_actionable_choices",
        "current_execution_choices",
    ):
        hit = _any_real(getattr(game, attr, None))
        if hit is not None:
            return bool(hit)

    scan = getattr(game, "current_viable_action_scan", None)
    if isinstance(scan, Mapping):
        for key in ("actionable_choices", "viable_actions", "choices"):
            hit = _any_real(scan.get(key))
            if hit is not None:
                return bool(hit)
        # Nested reports
        for key in ("scan_viable_actions", "actions"):
            hit = _any_real(scan.get(key))
            if hit is not None:
                return bool(hit)

    # No scan data → assume still acting (recalc)
    return True


def note_own_strategy_milestone(
    game: Any,
    player: Any,
    reason: str,
    *,
    has_legal_actions: Optional[bool] = None,
    detail: Optional[Mapping[str, Any]] = None,
) -> str:
    """Handle own rec-settle / city / LA / LR milestones.

    S14-1a: target complete + legal buy/build remaining → recalc_now (full re-solve).
    S14-1b: complete with nothing left → flag_only (next turn re-solve).

    Returns:
      ``\"recalc_now\"`` — clear sticky + force re-rank on next sticky apply
      ``\"flag_only\"`` — batch flag for a later single re-rank (no legal actions)
    """
    if player is None:
        return "flag_only"
    reason_s = str(reason or "own_milestone").strip() or "own_milestone"
    flag_strategy_recalc(player, reason_s, detail=detail)
    if has_legal_actions is None:
        has_legal_actions = player_has_legal_actions(game, player)
    if has_legal_actions:
        try:
            setattr(player, "force_strategy_recalc", True)
        except Exception:
            pass
        clear_sticky_commitment(player)
        try:
            setattr(player, "pending_full_resolve", {
                "reason": reason_s,
                "trigger": "s14_1a_target_complete_with_actions",
                "detail": dict(detail or {}),
            })
        except Exception:
            pass
        try:
            from core.strategy_reconsider import set_reconsider_flag

            set_reconsider_flag(player, "need_next_target", reason=reason_s)
        except Exception:
            pass
        return "recalc_now"
    try:
        setattr(player, "force_strategy_recalc", False)
    except Exception:
        pass
    try:
        from core.strategy_reconsider import set_reconsider_flag

        set_reconsider_flag(player, "need_next_target", reason=f"defer:{reason_s}")
    except Exception:
        pass
    try:
        setattr(player, "pending_full_resolve", {
            "reason": reason_s,
            "trigger": "s14_1b_target_complete_next_turn",
            "detail": dict(detail or {}),
        })
    except Exception:
        pass
    return "flag_only"


# S14-2: off-way opportunity must beat locked way ETA by this many own-turns
# Align with strategy_reconsider.STRATEGY_SWITCH_MIN_ETA_GAIN (anti-thrash *).
try:
    from core.strategy_reconsider import STRATEGY_SWITCH_MIN_ETA_GAIN as S14_OFFWAY_ETA_DELTA
except Exception:  # pragma: no cover
    S14_OFFWAY_ETA_DELTA: float = 1.0


def should_offway_opportunity_resolve(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Mapping[str, Any],
    *,
    eta_delta: float = S14_OFFWAY_ETA_DELTA,
) -> Tuple[bool, str, Dict[str, Any]]:
    """S14-2: legal build/buy not on locked way, alt way includes it with lower win-ETA.

    Returns (should_resolve, reason, meta). Hard-caps to one full re-solve signal.
    """
    meta: Dict[str, Any] = {"trigger": "s14_2_offway_lower_eta"}
    commitment = get_sticky_commitment(player)
    if not commitment:
        return False, "", meta
    locked_way = _safe_int(commitment.get("locked_way_id"), None)
    locked_tid = _safe_int(commitment.get("locked_rec_target_id"), None)
    if locked_way is None:
        return False, "", meta

    locked_eta = _safe_float(
        direction.get("realistic_expected_turns")
        or direction.get("board_expected_turns")
        or direction.get("rank_key"),
        default=9999.0,
    )
    locked_audit = find_audit_for_way(audits, locked_way)
    if locked_audit is not None:
        locked_eta = _safe_float(
            _audit_get(locked_audit, "realistic_expected_turns")
            or _audit_get(locked_audit, "board_expected_turns")
            or _audit_get(locked_audit, "rank_key"),
            default=locked_eta,
        )
    meta["locked_way_id"] = locked_way
    meta["locked_eta"] = locked_eta
    meta["locked_target_id"] = locked_tid

    # Legal action targets this turn (non-pass)
    legal_targets: List[Tuple[str, Optional[int]]] = []
    for attr in ("current_actionable_choices", "current_execution_choices"):
        for row in list(getattr(game, attr, None) or []):
            if not isinstance(row, Mapping):
                continue
            name = str(row.get("action") or row.get("name") or "").strip().lower()
            if name in _NON_BUILD_ACTION_NAMES:
                continue
            tid = None
            cands = list(row.get("candidates") or [])
            if cands and isinstance(cands[0], Mapping):
                tid = _safe_int(
                    cands[0].get("target_id")
                    or cands[0].get("intersection_id")
                    or cands[0].get("road_id"),
                    None,
                )
            if tid is None:
                tid = _safe_int(row.get("target_id"), None)
            legal_targets.append((name, tid))
        if legal_targets:
            break
    if not legal_targets:
        return False, "", meta

    # Targets that are "on way": locked target + portfolio of locked way
    on_way_ids = set()
    if locked_tid is not None:
        on_way_ids.add(int(locked_tid))
    if locked_audit is not None:
        for t in _portfolio_list(locked_audit):
            t_id = _target_id_of(t)
            if t_id is not None:
                on_way_ids.add(int(t_id))

    delta = float(eta_delta if eta_delta is not None else S14_OFFWAY_ETA_DELTA)
    for action_name, tid in legal_targets:
        if tid is None:
            # DCard buy etc. — treat as off-way only if not supporting locked path
            if "dcard" in action_name or "development" in action_name:
                # skip soft DCard unless LA way on an alt
                continue
            continue
        if int(tid) in on_way_ids:
            continue
        # Find an alternate way whose portfolio includes this target with better ETA
        for audit in list(audits or []):
            way_id = _safe_int(_audit_get(audit, "way_id"), None)
            if way_id is None or way_id == locked_way:
                continue
            port_ids = set()
            for t in _portfolio_list(audit):
                t_id = _target_id_of(t)
                if t_id is not None:
                    port_ids.add(int(t_id))
            if int(tid) not in port_ids and _safe_int(_audit_get(audit, "recommendation_target_id"), None) != tid:
                continue
            alt_eta = _safe_float(
                _audit_get(audit, "realistic_expected_turns")
                or _audit_get(audit, "board_expected_turns")
                or _audit_get(audit, "rank_key"),
                default=9999.0,
            )
            if alt_eta + 1e-6 < locked_eta - delta:
                meta.update({
                    "offway_target_id": tid,
                    "offway_action": action_name,
                    "alt_way_id": way_id,
                    "alt_eta": alt_eta,
                    "eta_delta": locked_eta - alt_eta,
                })
                return True, f"s14_2_offway_t{tid}_way{way_id}_eta{alt_eta:.1f}", meta
    return False, "", meta


def should_consume_recalc_flag(game: Any, player: Any) -> Tuple[bool, str]:
    """Whether pending flag should force a way re-rank on this sticky apply.

    - ``force_strategy_recalc`` (own milestone while legal actions remain): always.
    - Opponent settle/city (and similar board-shock reasons): always on the next
      strategy refresh for this player — multiple builders collapse to one re-rank.
    - Own-only milestones with **no** legal actions: defer (flag stays).
    - Own-only milestones with legal actions: consume now.
    """
    if player is not None and bool(getattr(player, "force_strategy_recalc", False)):
        return True, "force_strategy_recalc"
    flag = get_strategy_recalc_flag(player)
    if not flag.get("pending"):
        return False, "no_flag"
    reasons = [str(r) for r in (flag.get("reasons") or [])]
    board_shock = any(
        r.startswith("opponent_")
        or r.startswith("lost_")
        or r.startswith("way_kill_")
        or r in ("largest_army_change", "longest_road_change", "special_award_change")
        for r in reasons
    )
    if board_shock:
        joined = ",".join(reasons[:4]) or "board_shock"
        return True, "flag_board_shock:" + joined
    if player_has_legal_actions(game, player):
        return True, "flag_own_milestone_with_actions:" + ",".join(reasons[:4])
    # Own-only milestone and nothing left to do this turn → one re-rank later.
    return False, "flag_deferred_no_legal_actions"


def consume_strategy_recalc_flag(player: Any) -> Dict[str, Any]:
    """Clear pending flag after a single re-rank. Returns the prior flag meta."""
    prior = get_strategy_recalc_flag(player)
    clear_strategy_recalc_flag(player)
    return prior


def _own_structure_ids(player: Any) -> set:
    ids = set()
    for attr in ("settlements", "cities"):
        for item in list(getattr(player, attr, None) or []):
            try:
                ids.add(int(item))
            except Exception:
                pass
    return ids


def _all_structures_by_player(game: Any) -> Dict[int, set]:
    out: Dict[int, set] = {}
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None:
            continue
        out[pid] = _own_structure_ids(p)
    return out


def _own_road_keys(player: Any) -> set:
    keys = set()
    for edge in list(getattr(player, "roads", None) or []):
        key = _road_key(edge)
        if key is not None:
            keys.add(key)
    return keys


def _all_opp_road_keys(game: Any, player: Any) -> set:
    own_id = _safe_int(getattr(player, "id", None), None)
    keys = set()
    for p in list(getattr(game, "players", None) or []):
        if _safe_int(getattr(p, "id", None), None) == own_id:
            continue
        keys |= _own_road_keys(p)
    return keys


def _intersection_neighbors(board: Any, node: int) -> List[int]:
    neighbors: List[int] = []
    try:
        inters = getattr(board, "intersections", None) or []
        if 0 <= int(node) < len(inters) and inters[int(node)] is not None:
            inter = inters[int(node)]
            raw = getattr(inter, "three_intersection_ids", None) or []
            for nid in raw:
                try:
                    neighbors.append(int(nid))
                except Exception:
                    pass
            if neighbors:
                return neighbors
    except Exception:
        pass
    try:
        conn = getattr(board, "list_of_roads_connected_to_intersection", None) or []
        if 0 <= int(node) < len(conn):
            for road in conn[int(node)] or []:
                key = _road_key(road)
                if key is None:
                    continue
                a, b = key
                neighbors.append(b if a == int(node) else a)
    except Exception:
        pass
    return neighbors


def nodes_within_hops(board: Any, origin: int, radius: int) -> set:
    """BFS hop ball around origin (inclusive)."""
    origin = int(origin)
    radius = max(0, int(radius))
    seen = {origin}
    frontier = [origin]
    for _ in range(radius):
        nxt: List[int] = []
        for node in frontier:
            for nb in _intersection_neighbors(board, node):
                if nb not in seen:
                    seen.add(nb)
                    nxt.append(nb)
        frontier = nxt
        if not frontier:
            break
    return seen


def road_near_target(board: Any, edge: Any, target_id: int, radius: int = STICKY_OPP_ROAD_RADIUS) -> bool:
    key = _road_key(edge)
    if key is None:
        return False
    ball = nodes_within_hops(board, int(target_id), radius)
    return key[0] in ball or key[1] in ball


def snapshot_opponent_board(
    game: Any,
    player: Any,
    *,
    target_id: Optional[int] = None,
    road_radius: int = STICKY_OPP_ROAD_RADIUS,
) -> Dict[str, Any]:
    """Compact opponent structure/road signature used for board-shock invalidation."""
    own_id = _safe_int(getattr(player, "id", None), None)
    board = getattr(game, "board", None)
    structures: List[List[Any]] = []
    roads_near: List[List[Any]] = []
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or pid == own_id:
            continue
        for sid in list(getattr(p, "settlements", None) or []):
            try:
                structures.append([pid, "S", int(sid)])
            except Exception:
                pass
        for cid in list(getattr(p, "cities", None) or []):
            try:
                structures.append([pid, "C", int(cid)])
            except Exception:
                pass
        for edge in list(getattr(p, "roads", None) or []):
            key = _road_key(edge)
            if key is None:
                continue
            if target_id is None:
                near = True
            elif board is None:
                # Fallback without graph: endpoint equals target or adjacent by shared int
                near = int(target_id) in key
            else:
                near = road_near_target(board, key, int(target_id), radius=road_radius)
            if near:
                roads_near.append([pid, int(key[0]), int(key[1])])
    structures.sort(key=lambda x: (x[0], x[1], x[2]))
    roads_near.sort(key=lambda x: (x[0], x[1], x[2]))
    return {
        "opp_structures": structures,
        "opp_roads_near": roads_near,
    }


def remaining_roads_for_player(player: Any, roads: Sequence[Any]) -> List[List[int]]:
    """Drop edges the player already owns (progress along the route)."""
    owned = _own_road_keys(player)
    out: List[List[int]] = []
    for edge in _normalize_roads(roads):
        key = _road_key(edge)
        if key is None or key in owned:
            continue
        out.append([int(key[0]), int(key[1])])
    return out


def route_edges_legal(game: Any, player: Any, roads: Sequence[Any]) -> Tuple[bool, str]:
    """False when an unbuilt path edge is already owned by an opponent."""
    opp = _all_opp_road_keys(game, player)
    remaining = remaining_roads_for_player(player, roads)
    for edge in remaining:
        key = _road_key(edge)
        if key is not None and key in opp:
            return False, "route_edge_owned_by_opponent"
    return True, "ok"


def target_occupied_by_other(game: Any, player: Any, target_id: int) -> bool:
    own_id = _safe_int(getattr(player, "id", None), None)
    for pid, ids in _all_structures_by_player(game).items():
        if pid == own_id:
            continue
        if int(target_id) in ids:
            return True
    return False


def target_own_complete(
    player: Any,
    target_id: int,
    *,
    kind: Any = None,
) -> bool:
    """True when the locked target is finished for its kind.

    Settle lock: own settlement or city at id.
    City lock (S11): own **city** at id (settlement alone is not complete).
    """
    tid = int(target_id)
    kind_s = str(kind or "").strip().upper()
    if kind_s in ("C", "CITY", "CITY_UPGRADE", "BUILD_CITY"):
        try:
            cities = {int(x) for x in list(getattr(player, "cities", []) or [])}
            return tid in cities
        except Exception:
            return False
    return tid in _own_structure_ids(player)


def target_blocked_on_board(game: Any, target_id: int) -> bool:
    board = getattr(game, "board", None)
    if board is None:
        return False
    try:
        inters = getattr(board, "intersections", None) or []
        if 0 <= int(target_id) < len(inters) and inters[int(target_id)] is not None:
            inter = inters[int(target_id)]
            if getattr(inter, "can_build_tf", True) is False:
                # Own structure may also set can_build false; caller checks own complete first.
                return True
    except Exception:
        pass
    return False


def _portfolio_list(audit: Any) -> List[Any]:
    raw = _audit_get(audit, "target_portfolio", []) or []
    return list(raw)


def _target_id_of(item: Any) -> Optional[int]:
    if item is None:
        return None
    if isinstance(item, Mapping):
        return _safe_int(item.get("target_id"), None)
    return _safe_int(getattr(item, "target_id", None), None)


def _target_field(item: Any, name: str, default: Any = None) -> Any:
    if item is None:
        return default
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def find_target_in_audits(
    audits: Sequence[Any],
    target_id: int,
    *,
    preferred_way_id: Optional[int] = None,
) -> Tuple[Optional[Any], Optional[Any]]:
    """Return (audit, target) for target_id; prefer preferred_way_id when set."""
    tid = int(target_id)
    fallback: Tuple[Optional[Any], Optional[Any]] = (None, None)
    for audit in list(audits or []):
        for t in _portfolio_list(audit):
            if _target_id_of(t) == tid:
                way = _safe_int(_audit_get(audit, "way_id"), -1)
                if preferred_way_id is not None and way == int(preferred_way_id):
                    return audit, t
                if fallback[0] is None:
                    fallback = (audit, t)
    return fallback


def find_audit_for_way(audits: Sequence[Any], way_id: int) -> Optional[Any]:
    wid = int(way_id)
    for audit in list(audits or []):
        if _safe_int(_audit_get(audit, "way_id"), -1) == wid:
            return audit
    return None


def commit_from_direction(
    direction: Mapping[str, Any],
    game: Any,
    player: Any,
) -> Optional[Dict[str, Any]]:
    """Build a new sticky commitment from a strategic_direction dict.

    S11: city paths may lock ``C@settlement_id`` when rec target was blank.
    S13: stores multi-target display list for STICKY/PROJ.
    """
    if not isinstance(direction, Mapping):
        return None
    direction_local = dict(direction)
    try:
        from core.strategy_target_format import (
            KIND_CITY,
            KIND_SETTLE,
            collect_display_targets,
            enrich_direction_city_target,
            infer_target_kind,
            primary_target_id,
        )

        direction_local = enrich_direction_city_target(direction_local, player)
        tid = primary_target_id(direction_local)
        kind = infer_target_kind(direction_local, player=player, target_id=tid)
        display = collect_display_targets(direction_local, player=player)
    except Exception:
        tid = _safe_int(
            direction_local.get("recommendation_target_id")
            or direction_local.get("settlement_target_id")
            or direction_local.get("target_id"),
            None,
        )
        kind = ""
        display = []
    way_id = _safe_int(
        direction_local.get("preferred_way_id") or direction_local.get("way_id"),
        None,
    )
    # S-LR-A2: allow LR-only commit when no structure target
    lr_proj = None
    if isinstance(direction_local.get("lr_project"), Mapping):
        lr_proj = dict(direction_local.get("lr_project") or {})
    if tid is None and not lr_proj:
        return None
    if tid is None and lr_proj:
        return {
            "locked_way_id": way_id,
            "locked_rec_target_id": None,
            "locked_target_kind": "LR",
            "locked_roads_to_build": list(lr_proj.get("roads_to_build") or []),
            "lr_project": lr_proj,
            "display_targets": list(display or []),
            "opp_structures": [],
            "opp_roads_near": [],
            "sticky_version": 3,
        }
    # S18: prefer portfolio roads for this tid; drop orphan edges for other sites
    roads = remaining_roads_for_player(player, direction_local.get("roads_to_build") or [])
    if not roads_serve_target(roads, tid):
        roads = []
    # City upgrades do not need road routes
    if str(kind).upper() in ("C", "CITY", "CITY_UPGRADE") or str(
        direction_local.get("supporting_action_type") or ""
    ).lower().find("city") >= 0:
        if not roads:
            roads = []
    snap = snapshot_opponent_board(game, player, target_id=tid)
    kind_s = str(kind or "S").strip().upper() or "S"
    if kind_s in ("CITY", "CITY_UPGRADE", "BUILD_CITY"):
        kind_s = "C"
    elif kind_s in ("SETTLE", "SETTLEMENT", "NEW_SETTLEMENT", "NEXT_SETTLEMENT"):
        kind_s = "S"
    out_c = {
        "locked_way_id": way_id,
        "locked_rec_target_id": tid,
        "locked_target_kind": kind_s,
        "locked_roads_to_build": roads,
        "display_targets": list(display or []),
        "opp_structures": list(snap.get("opp_structures") or []),
        "opp_roads_near": list(snap.get("opp_roads_near") or []),
        "sticky_version": 3 if lr_proj else 2,
    }
    if lr_proj:
        out_c["lr_project"] = lr_proj
    return out_c


def should_invalidate_sticky(
    game: Any,
    player: Any,
    commitment: Mapping[str, Any],
    audits: Sequence[Any],
    *,
    consume_flag: bool = False,
    flag_reason: str = "",
) -> Tuple[bool, str]:
    """Return (invalidate?, reason).

    Opponent settle/city board shock is **not** snap-diff based anymore: callers
    set ``strategy_recalc_flag`` and pass ``consume_flag=True`` when it is time
    for a single batched re-rank.
    """
    if not isinstance(commitment, Mapping):
        return True, "no_commitment"
    tid = _safe_int(commitment.get("locked_rec_target_id"), None)
    has_lr = isinstance(commitment.get("lr_project"), Mapping) and bool(
        (commitment.get("lr_project") or {}).get("roads_to_build")
    )
    # S-LR-A2: pure LR portfolio — do not full-invalidate for missing structure tid
    if tid is None:
        if has_lr:
            return False, "lr_only_portfolio"
        return True, "no_locked_target"
    way_id = _safe_int(commitment.get("locked_way_id"), None)

    kind = commitment.get("locked_target_kind")
    if target_own_complete(player, tid, kind=kind):
        # Structure target done — caller may strip tid and keep LR (not full clear)
        if str(kind or "").upper() in ("C", "CITY", "CITY_UPGRADE"):
            return True, "own_rec_city_complete"
        return True, "own_rec_settle_complete"

    if target_occupied_by_other(game, player, tid):
        return True, "target_occupied_by_opponent"

    # Batched opponent / milestone re-rank (one consume clears many builders)
    if consume_flag:
        return True, str(flag_reason or "strategy_recalc_flag")

    roads = list(commitment.get("locked_roads_to_build") or [])
    # LR-only roads on commitment shouldn't fail settle route legality when kind is C
    if str(kind or "").upper() in ("C", "CITY") and not roads:
        roads = []
    # Prefer fresher roads from audits when available for legality check
    audit_hit, target_hit = find_target_in_audits(audits, tid, preferred_way_id=way_id)
    if target_hit is not None:
        fresh = _normalize_roads(_target_field(target_hit, "roads_to_build", []))
        if fresh:
            roads = fresh
        race = str(_target_field(target_hit, "race_status", "") or "").lower()
        risk = str(_target_field(target_hit, "risk_level", "") or "").lower()
        if race == "likely_lost" or risk == "blocked":
            return True, "target_race_impossible"

    legal, legal_reason = route_edges_legal(game, player, roads)
    if not legal:
        return True, legal_reason

    # Opponent road that lands on path near target still kills route (hard).
    # Near-target opp roads that do not own our edges are covered by the flag
    # when settle/city lands; pure road blocking uses route_edges_legal above.

    if way_id is not None:
        way_audit = find_audit_for_way(audits, way_id)
        if way_audit is not None:
            feas = str(_audit_get(way_audit, "feasibility", "") or "").lower()
            if feas in _FEAS_KILL:
                return True, "locked_way_infeasible"

    # Target blocked on board and not own (own handled above)
    if target_blocked_on_board(game, tid) and not target_own_complete(player, tid):
        if target_occupied_by_other(game, player, tid):
            return True, "target_blocked_occupied"
        if target_hit is None:
            return True, "target_blocked_on_board"

    return False, "hold"


def roads_serve_target(roads: Any, target_id: Any) -> bool:
    """S18: True if road list is empty (at site) or forms a graph incident to target.

    Orphan edges for a *different* settle site return False so we re-path.
    """
    tid = _safe_int(target_id, None)
    if tid is None:
        return True
    norm = _normalize_roads(roads)
    if not norm:
        return True
    adj: Dict[int, set] = {}
    for a, b in ((int(e[0]), int(e[1])) for e in norm):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return tid in adj


def repath_roads_for_locked_target(
    audits: Sequence[Any],
    player: Any,
    *,
    target_id: Any,
    way_id: Any = None,
    fallback_roads: Any = None,
) -> List[List[int]]:
    """S18: roads_to_build for locked settle target from live portfolio only."""
    tid = _safe_int(target_id, None)
    if tid is None:
        return remaining_roads_for_player(player, fallback_roads or [])
    _audit, target = find_target_in_audits(
        audits, tid, preferred_way_id=_safe_int(way_id, None)
    )
    if target is not None:
        fresh = _normalize_roads(_target_field(target, "roads_to_build", []))
        return remaining_roads_for_player(player, fresh)
    fb = _normalize_roads(fallback_roads or [])
    if roads_serve_target(fb, tid):
        return remaining_roads_for_player(player, fb)
    # Orphan fallback — drop rather than keep wrong-site edges
    return []


def race_competitor_annotation(target: Any) -> str:
    """S17: `` race P3`` / `` race P3~2t`` for contested; empty for safe."""
    if target is None:
        return ""
    race = str(_target_field(target, "race_status", "") or "").lower()
    risk = str(_target_field(target, "risk_level", "") or "").lower()
    threats = _target_field(target, "threat_opponents", None) or []
    if not isinstance(threats, (list, tuple)):
        threats = []
    best_pid = None
    best_eta = None
    for raw in threats:
        if not isinstance(raw, Mapping):
            continue
        try:
            pid = int(raw.get("player_id")) if raw.get("player_id") is not None else None
        except Exception:
            pid = None
        eta = raw.get("eta_own_turns")
        try:
            eta_f = float(eta) if eta is not None and eta != "" else None
        except Exception:
            eta_f = None
        if pid is None:
            continue
        if best_eta is None or (eta_f is not None and (best_eta is None or eta_f < best_eta)):
            best_pid = pid
            if eta_f is not None:
                best_eta = eta_f
        elif best_pid is None:
            best_pid = pid
    if race in ("", "safe") and risk in ("", "low", "safe"):
        return ""
    if race == "likely_lost":
        if best_pid is not None:
            return " lost vs P{}".format(best_pid)
        return " lost?"
    if race == "contested" or (
        risk in ("medium", "med", "high", "blocked") and threats
    ):
        if best_pid is not None and best_eta is not None:
            return " race P{}~{:.0f}t".format(best_pid, best_eta)
        if best_pid is not None:
            return " race P{}".format(best_pid)
        return " race"
    return ""


def _recommendation_label(target: Any, tid: int) -> str:
    """S17: clean S@ when uncontested; show competitor ETA only when raced."""
    dist = _safe_int(_target_field(target, "distance_roads", 0), 0) or 0
    race = str(_target_field(target, "race_status", "") or "").lower()
    ann = race_competitor_annotation(target)
    if race in ("", "safe") and not ann:
        if dist > 0:
            return "road toward S@{}".format(tid)
        return "settle S@{}".format(tid)
    if dist > 0:
        return "road toward S@{}{}".format(tid, ann)
    if ann:
        return "settle S@{}{}".format(tid, ann)
    return "settle S@{}".format(tid)


def record_last_sticky_switch(
    player: Any,
    game: Any,
    *,
    from_way: Any = None,
    to_way: Any = None,
    from_tid: Any = None,
    to_tid: Any = None,
    reason: str = "",
    from_roads: Any = None,
    to_roads: Any = None,
) -> Dict[str, Any]:
    """S19: structured dig-in when way/target (or forced re-path) changes."""
    payload: Dict[str, Any] = {
        "from_way": _safe_int(from_way, None),
        "to_way": _safe_int(to_way, None),
        "from_tid": _safe_int(from_tid, None),
        "to_tid": _safe_int(to_tid, None),
        "reason": str(reason or "sticky_switch"),
        "from_roads": _normalize_roads(from_roads or []),
        "to_roads": _normalize_roads(to_roads or []),
        "round": _safe_int(getattr(game, "round", None), None) if game is not None else None,
        "turn": _safe_int(getattr(game, "turn", None), None) if game is not None else None,
        "player_id": _safe_int(getattr(player, "id", None), None) if player is not None else None,
    }
    # Only record real changes (or explicit repath reasons)
    if (
        payload["from_way"] == payload["to_way"]
        and payload["from_tid"] == payload["to_tid"]
        and payload["reason"] not in ("repath_orphan_roads", "s18_repath")
    ):
        return payload
    try:
        if player is not None:
            setattr(player, "last_sticky_switch", dict(payload))
    except Exception:
        pass
    try:
        if game is not None:
            setattr(game, "last_sticky_switch", dict(payload))
    except Exception:
        pass
    return payload


def _apply_target_fields(
    direction: Dict[str, Any],
    tid: int,
    target: Any,
    roads: List[List[int]],
    *,
    kind: Any = None,
) -> None:
    direction["recommendation_target_id"] = tid
    direction["settlement_target_id"] = tid
    direction["new_settlement_target_id"] = tid
    direction["target_id"] = tid
    direction["roads_to_build"] = list(roads)
    direction["locked_rec_target_id"] = tid
    kind_s = str(kind or direction.get("locked_target_kind") or "").strip().upper()
    is_city = kind_s in ("C", "CITY", "CITY_UPGRADE", "BUILD_CITY")
    if is_city:
        direction["locked_target_kind"] = "C"
        direction["target_kind"] = "C"
        direction["city_upgrade_target_id"] = tid
        direction["supporting_action_type"] = "city_upgrade"
        direction["target_label"] = "city_upgrade@C@{}".format(tid)
        direction["recommendation"] = "city C@{}".format(tid)
        direction["supporting_action"] = direction["recommendation"]
        if target is not None:
            direction["project_target"] = (
                target.as_dict()
                if hasattr(target, "as_dict")
                else dict(target)
                if isinstance(target, Mapping)
                else target
            )
        return
    direction["locked_target_kind"] = kind_s or "S"
    direction["target_kind"] = direction["locked_target_kind"]
    if target is not None:
        direction["project_target"] = (
            target.as_dict() if hasattr(target, "as_dict") else dict(target) if isinstance(target, Mapping) else target
        )
        direction["target_label"] = "new_settle@S@{}".format(tid)
        direction["recommendation"] = _recommendation_label(target, tid)
        direction["supporting_action"] = direction["recommendation"]
        dist = _safe_int(_target_field(target, "distance_roads", len(roads)), len(roads)) or 0
        if dist <= 0 and not roads:
            direction["supporting_action_type"] = "next_settlement"
        else:
            direction["supporting_action_type"] = "new_settlement"
    else:
        direction["recommendation"] = (
            "road toward S@{}".format(tid) if roads else "settle S@{}".format(tid)
        )
        direction["supporting_action"] = direction["recommendation"]
        direction["supporting_action_type"] = "new_settlement" if roads else "next_settlement"


def _strip_structure_lock_keep_lr(commitment: Mapping[str, Any]) -> Dict[str, Any]:
    """After city/settle complete: drop structure fields, keep lr_project."""
    out = dict(commitment)
    for key in (
        "locked_rec_target_id",
        "city_upgrade_target_id",
        "opp_structures",
        "opp_roads_near",
    ):
        out.pop(key, None)
    if out.get("lr_project"):
        out["locked_target_kind"] = "LR"
        roads = list((out.get("lr_project") or {}).get("roads_to_build") or [])
        out["locked_roads_to_build"] = roads
    return out


def force_sticky_on_direction(
    direction: Dict[str, Any],
    commitment: Mapping[str, Any],
    audits: Sequence[Any],
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """Force locked way/target onto direction; refresh remaining roads from portfolio."""
    out = dict(direction)
    tid = _safe_int(commitment.get("locked_rec_target_id"), None)
    way_id = _safe_int(commitment.get("locked_way_id"), None)
    kind = commitment.get("locked_target_kind")
    lr_proj = commitment.get("lr_project") if isinstance(commitment.get("lr_project"), Mapping) else None

    if tid is None:
        # S-LR-A2: LR-only sticky still applies project to direction
        if lr_proj:
            try:
                from core.ai_lr_project import apply_lr_project_to_direction

                out = apply_lr_project_to_direction(out, player, game)
            except Exception:
                out["lr_project"] = dict(lr_proj)
            if way_id is not None:
                out["preferred_way_id"] = way_id
                out["way_id"] = way_id
            out["sticky_applied"] = True
            out["locked_target_kind"] = out.get("locked_target_kind") or "LR"
            try:
                from core.strategy_target_format import collect_display_targets, format_targets_line

                out["display_targets"] = collect_display_targets(out, player=player)
                out["display_targets_line"] = format_targets_line(out, player=player)
            except Exception:
                pass
        return out

    roads = remaining_roads_for_player(player, commitment.get("locked_roads_to_build") or [])
    target = None
    preferred_audit = None
    if way_id is not None:
        preferred_audit = find_audit_for_way(audits, way_id)
    audit_hit, target_hit = find_target_in_audits(audits, tid, preferred_way_id=way_id)
    if target_hit is not None:
        target = target_hit
        fresh = remaining_roads_for_player(
            player, _normalize_roads(_target_field(target_hit, "roads_to_build", []))
        )
        # Prefer live portfolio roads when present
        roads = fresh if fresh or _target_field(target_hit, "distance_roads", None) == 0 else roads
        if audit_hit is not None and preferred_audit is None:
            preferred_audit = audit_hit

    # Prefer locked way ids on direction
    if way_id is not None:
        out["preferred_way_id"] = way_id
        out["way_id"] = way_id
        out["locked_way_id"] = way_id
        # If we have the locked way audit, pull remaining / ETA fields from it
        if preferred_audit is not None:
            for key in (
                "board_expected_turns",
                "realistic_expected_turns",
                "best_case_turns",
                "fallback_case_turns",
                "feasibility",
                "fragility",
                "rank_key",
            ):
                val = _audit_get(preferred_audit, key, None)
                if val is not None:
                    out[key] = val
            port = _portfolio_list(preferred_audit)
            if port:
                out["target_portfolio"] = [
                    t.as_dict() if hasattr(t, "as_dict") else dict(t) if isinstance(t, Mapping) else t
                    for t in port
                ]

    _apply_target_fields(out, tid, target, roads, kind=kind)
    out["locked_roads_to_build"] = list(roads)
    out["locked_target_kind"] = kind or out.get("locked_target_kind")
    # S-LR-A2: keep LR project alongside structure lock
    if lr_proj:
        try:
            from core.ai_lr_project import apply_lr_project_to_direction, refresh_lr_project_roads

            refreshed = refresh_lr_project_roads(game, player, lr_proj)
            if refreshed:
                out = apply_lr_project_to_direction(out, player, game)
            else:
                out.pop("lr_project", None)
        except Exception:
            out["lr_project"] = dict(lr_proj)
    # S13: attach multi-target display list
    try:
        from core.strategy_target_format import collect_display_targets, format_targets_line

        display = list(commitment.get("display_targets") or []) or collect_display_targets(
            out, player=player
        )
        out["display_targets"] = display
        out["display_targets_line"] = format_targets_line(out, player=player)
    except Exception:
        pass
    out["sticky_applied"] = True
    out["sticky_reason"] = "hold"
    src = str(out.get("preference_source") or "")
    if "S1_sticky" not in src:
        out["preference_source"] = (src + "+S1_sticky").lstrip("+")
    return out


def refresh_commitment_roads(
    commitment: Mapping[str, Any],
    audits: Sequence[Any],
    player: Any,
    *,
    game: Any = None,
) -> Dict[str, Any]:
    """Update remaining roads in commitment from live portfolio without changing locks.

    S18: never keep edges that do not serve ``locked_rec_target_id`` (orphan path).
    """
    out = dict(commitment)
    tid = _safe_int(out.get("locked_rec_target_id"), None)
    way_id = _safe_int(out.get("locked_way_id"), None)
    if tid is None:
        return out
    prev_roads = list(out.get("locked_roads_to_build") or [])
    roads = repath_roads_for_locked_target(
        audits,
        player,
        target_id=tid,
        way_id=way_id,
        fallback_roads=prev_roads,
    )
    # If portfolio missing but prev roads still serve target, keep remaining
    if not roads and roads_serve_target(prev_roads, tid):
        roads = remaining_roads_for_player(player, prev_roads)
    if prev_roads and not roads_serve_target(prev_roads, tid) and roads != prev_roads:
        try:
            record_last_sticky_switch(
                player,
                game,
                from_way=way_id,
                to_way=way_id,
                from_tid=tid,
                to_tid=tid,
                reason="s18_repath",
                from_roads=prev_roads,
                to_roads=roads,
            )
        except Exception:
            pass
    out["locked_roads_to_build"] = roads
    return out


def apply_sticky_layer(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Main S1 entry: hold or (re)commit sticky lock onto strategic direction.

    Returns (direction_dict, sticky_meta).
    """
    try:
        from core.performance_trace import timed_span
    except Exception:
        return _apply_sticky_layer_impl(game, player, audits, direction)
    with timed_span(
        game,
        "sticky_apply",
        meta={"player_id": getattr(player, "id", None)},
        emit_spike=False,
    ):
        return _apply_sticky_layer_impl(game, player, audits, direction)


def _apply_sticky_layer_impl(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    direction_out = dict(direction or {})
    meta: Dict[str, Any] = {
        "applied": False,
        "held": False,
        "committed": False,
        "invalidated": False,
        "invalidate_reason": "",
        "reason": "",
        "locked_way_id": None,
        "locked_rec_target_id": None,
        "locked_roads_to_build": [],
        "flag_consumed": False,
        "flag_deferred": False,
        "flag_reasons": [],
        "recalc_mode": "",
    }

    consume_flag, consume_reason = should_consume_recalc_flag(game, player)
    flag_before = get_strategy_recalc_flag(player)
    meta["flag_reasons"] = list(flag_before.get("reasons") or [])
    if flag_before.get("pending") and not consume_flag:
        meta["flag_deferred"] = True
        meta["recalc_mode"] = "flag_deferred_no_legal_actions"
    elif consume_flag:
        meta["recalc_mode"] = "recalc_now"

    commitment = get_sticky_commitment(player)
    # S19: keep a copy before invalidate clears sticky (for last_sticky_switch)
    prev_commitment_snapshot: Optional[Dict[str, Any]] = (
        dict(commitment) if isinstance(commitment, Mapping) else None
    )
    if commitment is not None:
        invalidate, inv_reason = should_invalidate_sticky(
            game,
            player,
            commitment,
            audits,
            consume_flag=bool(consume_flag),
            flag_reason=consume_reason,
        )
        if invalidate:
            # S-LR-A2: structure complete/occupied → strip structure, keep LR if any
            if inv_reason in (
                "own_rec_city_complete",
                "own_rec_settle_complete",
                "target_occupied_by_opponent",
            ) and isinstance(commitment.get("lr_project"), Mapping):
                commitment = _strip_structure_lock_keep_lr(commitment)
                if commitment.get("lr_project") or commitment.get("locked_rec_target_id") is not None:
                    set_sticky_commitment(player, commitment)
                    meta["invalidated"] = True
                    meta["invalidate_reason"] = inv_reason + "+keep_lr"
                    # continue into hold path with reduced commitment
                    invalidate = False
                else:
                    clear_sticky_commitment(player)
                    commitment = None
                    meta["invalidated"] = True
                    meta["invalidate_reason"] = inv_reason
            elif inv_reason == "lr_only_portfolio":
                invalidate = False  # pure LR handled by ensure_lr below
            else:
                clear_sticky_commitment(player)
                commitment = None
                meta["invalidated"] = True
                meta["invalidate_reason"] = inv_reason
        if commitment is not None and not invalidate:
            # S14-2: off-way opportunity with lower win-ETA → force one full re-solve
            try:
                offway, off_reason, off_meta = should_offway_opportunity_resolve(
                    game, player, audits, direction_out
                )
            except Exception:
                offway, off_reason, off_meta = False, "", {}
            if offway:
                clear_sticky_commitment(player)
                try:
                    setattr(player, "force_strategy_recalc", True)
                    setattr(
                        player,
                        "pending_full_resolve",
                        {"reason": off_reason, "trigger": "s14_2", "detail": dict(off_meta or {})},
                    )
                except Exception:
                    pass
                commitment = None
                meta["invalidated"] = True
                meta["invalidate_reason"] = off_reason or "s14_2_offway"
                meta["s14_offway"] = dict(off_meta or {})
                # fall through to re-commit from current direction
            else:
                # S-LR-A2: refresh/invalidate LR project independently
                try:
                    from core.ai_lr_project import (
                        clear_lr_project_from_sticky,
                        ensure_lr_project_sticky,
                        get_stored_lr_project,
                        should_invalidate_lr_project,
                    )

                    lr_meta = ensure_lr_project_sticky(game, player)
                    meta["lr"] = dict(lr_meta)
                    if lr_meta.get("invalidated") and not get_stored_lr_project(player, game):
                        # LR gone; if no structure lock left, fall through
                        commitment = get_sticky_commitment(player)
                        if commitment is None:
                            # fall through to commit
                            pass
                except Exception as lr_exc:
                    meta["lr_error"] = str(lr_exc)

                # S-LA-A: refresh/invalidate LA progress independently
                try:
                    from core.ai_la_progress import ensure_la_progress_sticky

                    la_meta = ensure_la_progress_sticky(game, player)
                    meta["la"] = dict(la_meta)
                except Exception as la_exc:
                    meta["la_error"] = str(la_exc)

                commitment = get_sticky_commitment(player)
                if commitment is None:
                    pass  # fall through to commit
                else:
                    direction_out = force_sticky_on_direction(
                        direction_out, commitment, audits, game, player
                    )
                    commitment = refresh_commitment_roads(
                        commitment, audits, player, game=game
                    )
                    # Re-attach refreshed lr_project / la_progress onto commitment
                    try:
                        from core.ai_lr_project import get_stored_lr_project

                        lr_now = get_stored_lr_project(player, game)
                        if lr_now:
                            commitment["lr_project"] = lr_now
                        elif "lr_project" in commitment:
                            commitment.pop("lr_project", None)
                    except Exception:
                        pass
                    try:
                        from core.ai_la_progress import (
                            apply_la_progress_to_direction,
                            get_stored_la_progress,
                        )

                        la_now = get_stored_la_progress(player, game)
                        if la_now:
                            commitment["la_progress"] = la_now
                            direction_out = apply_la_progress_to_direction(
                                direction_out, player, game
                            )
                        elif "la_progress" in commitment:
                            commitment.pop("la_progress", None)
                    except Exception:
                        pass
                    # Refresh board snapshot so diagnostics stay current, but do not
                    # use snap-diff as an invalidator (flag owns board-shock batching).
                    tid = _safe_int(commitment.get("locked_rec_target_id"), None)
                    if tid is not None:
                        snap = snapshot_opponent_board(game, player, target_id=tid)
                        commitment["opp_structures"] = list(snap.get("opp_structures") or [])
                        commitment["opp_roads_near"] = list(snap.get("opp_roads_near") or [])
                    # S13 refresh multi-target list on hold
                    try:
                        from core.strategy_target_format import (
                            collect_display_targets,
                            format_targets_line,
                        )

                        commitment["display_targets"] = collect_display_targets(
                            direction_out, player=player
                        )
                        direction_out["display_targets"] = list(commitment["display_targets"])
                        direction_out["display_targets_line"] = format_targets_line(
                            direction_out, player=player
                        )
                    except Exception:
                        pass
                    # Turn focus (A2 + S-LR-C race/dense flags)
                    try:
                        from core.ai_lr_project import pick_turn_focus

                        focus_info = pick_turn_focus(game, player)
                        direction_out["turn_focus"] = focus_info.get("focus")
                        direction_out["turn_focus_reason"] = focus_info.get("reason")
                        direction_out["dense_pack"] = bool(focus_info.get("dense_pack"))
                        direction_out["la_race"] = bool(focus_info.get("la_race"))
                        direction_out["lr_race"] = bool(focus_info.get("lr_race"))
                        direction_out["defer_optional_claim"] = bool(
                            focus_info.get("defer_optional_claim")
                        )
                        commitment["turn_focus"] = focus_info.get("focus")
                        commitment["turn_focus_reason"] = focus_info.get("reason")
                        meta["turn_focus"] = focus_info.get("focus")
                        meta["dense_pack"] = bool(focus_info.get("dense_pack"))
                        meta["la_race"] = bool(focus_info.get("la_race"))
                        meta["lr_race"] = bool(focus_info.get("lr_race"))
                    except Exception:
                        pass
                    set_sticky_commitment(player, commitment)
                    meta["applied"] = True
                    meta["held"] = True
                    meta["reason"] = "sticky_hold"
                    meta["locked_way_id"] = commitment.get("locked_way_id")
                    meta["locked_rec_target_id"] = commitment.get("locked_rec_target_id")
                    meta["locked_roads_to_build"] = list(commitment.get("locked_roads_to_build") or [])
                    direction_out["sticky_meta"] = {
                        "held": True,
                        "reason": "sticky_hold",
                        "flag_deferred": meta["flag_deferred"],
                        "flag_reasons": meta["flag_reasons"],
                        "locked_way_id": meta["locked_way_id"],
                        "locked_rec_target_id": meta["locked_rec_target_id"],
                        "lr_project": bool(commitment.get("lr_project")),
                        "turn_focus": direction_out.get("turn_focus"),
                    }
                    return direction_out, meta

    # Own milestone with no legal actions: clear sticky already, but do not
    # re-lock a thrashy provisional target until flag is consumed later.
    if meta.get("flag_deferred") and not consume_flag and not meta.get("invalidated"):
        # No commitment and flag deferred — leave unlocked until next consume
        meta["reason"] = "flag_deferred_no_commit"
        direction_out["sticky_meta"] = {
            "held": False,
            "committed": False,
            "flag_deferred": True,
            "flag_reasons": meta["flag_reasons"],
            "reason": meta["reason"],
        }
        return direction_out, meta

    # Hard invalidate while flag deferred (e.g. own rec complete, no legal acts):
    # do not commit a new lock yet — keep flag for a single later re-rank.
    if meta.get("invalidated") and meta.get("flag_deferred") and not consume_flag:
        meta["reason"] = "invalidated_flag_deferred_no_commit"
        direction_out["sticky_meta"] = {
            "held": False,
            "committed": False,
            "invalidated": True,
            "invalidate_reason": meta.get("invalidate_reason"),
            "flag_deferred": True,
            "flag_reasons": meta["flag_reasons"],
            "reason": meta["reason"],
        }
        return direction_out, meta

    # S11: enrich city target before commit when rec blank
    try:
        from core.strategy_target_format import enrich_direction_city_target

        direction_out = enrich_direction_city_target(direction_out, player)
    except Exception:
        pass

    # Snapshot prior lock for S19 switch log (prefer pre-invalidate copy)
    prev_for_switch = prev_commitment_snapshot
    if prev_for_switch is None:
        try:
            prev_for_switch = get_sticky_commitment(player)
        except Exception:
            prev_for_switch = None

    # Commit from current direction (fresh, force, or post-invalidate with consume)
    new_c = commit_from_direction(direction_out, game, player)
    # S18: after commit, force roads from portfolio for locked tid (no orphan edges)
    if new_c is not None and new_c.get("locked_rec_target_id") is not None:
        fixed_roads = repath_roads_for_locked_target(
            audits,
            player,
            target_id=new_c.get("locked_rec_target_id"),
            way_id=new_c.get("locked_way_id"),
            fallback_roads=new_c.get("locked_roads_to_build"),
        )
        # Prefer portfolio path; if empty keep commit roads only when they serve tid
        if fixed_roads:
            new_c["locked_roads_to_build"] = fixed_roads
        elif not roads_serve_target(
            new_c.get("locked_roads_to_build"), new_c.get("locked_rec_target_id")
        ):
            new_c["locked_roads_to_build"] = []

    # S-LR-A2: arm LR project even when structure commit exists or alone
    lr_meta: Dict[str, Any] = {}
    try:
        from core.ai_lr_project import (
            ensure_lr_project_sticky,
            get_stored_lr_project,
            merge_lr_project_into_sticky,
            pick_turn_focus,
            apply_lr_project_to_direction,
        )

        lr_meta = ensure_lr_project_sticky(game, player)
        meta["lr"] = dict(lr_meta)
    except Exception as lr_exc:
        meta["lr_error"] = str(lr_exc)
        lr_meta = {}

    # S-LA-A: arm LA progress alongside structure / LR
    la_meta: Dict[str, Any] = {}
    try:
        from core.ai_la_progress import ensure_la_progress_sticky

        la_meta = ensure_la_progress_sticky(game, player)
        meta["la"] = dict(la_meta)
    except Exception as la_exc:
        meta["la_error"] = str(la_exc)
        la_meta = {}

    if new_c is not None:
        # Merge any LR project / LA progress into the new structure commitment
        try:
            from core.ai_lr_project import get_stored_lr_project

            lr_now = get_stored_lr_project(player, game)
            if lr_now:
                new_c["lr_project"] = lr_now
                new_c["sticky_version"] = max(3, int(new_c.get("sticky_version") or 0) or 3)
        except Exception:
            pass
        try:
            from core.ai_la_progress import get_stored_la_progress

            la_now = get_stored_la_progress(player, game)
            if la_now:
                new_c["la_progress"] = la_now
                new_c["sticky_version"] = max(3, int(new_c.get("sticky_version") or 0) or 3)
        except Exception:
            pass
        # S19: log way/target switch when locks change
        try:
            prev_way = (
                (prev_for_switch or {}).get("locked_way_id")
                if isinstance(prev_for_switch, Mapping)
                else None
            )
            prev_tid = (
                (prev_for_switch or {}).get("locked_rec_target_id")
                if isinstance(prev_for_switch, Mapping)
                else None
            )
            prev_roads = (
                list((prev_for_switch or {}).get("locked_roads_to_build") or [])
                if isinstance(prev_for_switch, Mapping)
                else []
            )
            switch_reason = meta.get("invalidate_reason") or meta.get("reason") or "sticky_commit"
            if meta.get("invalidated"):
                switch_reason = str(meta.get("invalidate_reason") or "recommit_after_invalidate")
            if prev_tid is not None or prev_way is not None:
                if (
                    _safe_int(prev_tid, None) != _safe_int(new_c.get("locked_rec_target_id"), None)
                    or _safe_int(prev_way, None) != _safe_int(new_c.get("locked_way_id"), None)
                ):
                    sw = record_last_sticky_switch(
                        player,
                        game,
                        from_way=prev_way,
                        to_way=new_c.get("locked_way_id"),
                        from_tid=prev_tid,
                        to_tid=new_c.get("locked_rec_target_id"),
                        reason=switch_reason,
                        from_roads=prev_roads,
                        to_roads=new_c.get("locked_roads_to_build"),
                    )
                    meta["last_sticky_switch"] = dict(sw)
                    direction_out["last_sticky_switch"] = dict(sw)
        except Exception:
            pass
        set_sticky_commitment(player, new_c)
        if consume_flag or flag_before.get("pending"):
            # One re-rank absorbs all batched opponent builds / milestones
            consume_strategy_recalc_flag(player)
            meta["flag_consumed"] = True
        else:
            try:
                setattr(player, "force_strategy_recalc", False)
            except Exception:
                pass
        try:
            setattr(player, "pending_full_resolve", None)
        except Exception:
            pass
        meta["applied"] = True
        meta["committed"] = True
        if meta["invalidated"] and meta.get("flag_consumed"):
            meta["reason"] = "sticky_recommit_after_flag"
        elif meta["invalidated"]:
            meta["reason"] = "sticky_recommit_after_invalidate"
        else:
            meta["reason"] = "sticky_commit"
        meta["locked_way_id"] = new_c.get("locked_way_id")
        meta["locked_rec_target_id"] = new_c.get("locked_rec_target_id")
        meta["locked_roads_to_build"] = list(new_c.get("locked_roads_to_build") or [])
        direction_out["locked_way_id"] = new_c.get("locked_way_id")
        direction_out["locked_rec_target_id"] = new_c.get("locked_rec_target_id")
        direction_out["locked_roads_to_build"] = list(new_c.get("locked_roads_to_build") or [])
        direction_out["locked_target_kind"] = new_c.get("locked_target_kind")
        try:
            from core.ai_lr_project import apply_lr_project_to_direction, pick_turn_focus
            from core.ai_la_progress import apply_la_progress_to_direction

            direction_out = apply_lr_project_to_direction(direction_out, player, game)
            direction_out = apply_la_progress_to_direction(direction_out, player, game)
            focus_info = pick_turn_focus(game, player)
            direction_out["turn_focus"] = focus_info.get("focus")
            direction_out["turn_focus_reason"] = focus_info.get("reason")
            direction_out["dense_pack"] = bool(focus_info.get("dense_pack"))
            direction_out["la_race"] = bool(focus_info.get("la_race"))
            direction_out["lr_race"] = bool(focus_info.get("lr_race"))
            direction_out["defer_optional_claim"] = bool(
                focus_info.get("defer_optional_claim")
            )
            meta["turn_focus"] = focus_info.get("focus")
            meta["dense_pack"] = bool(focus_info.get("dense_pack"))
            meta["la_race"] = bool(focus_info.get("la_race"))
            meta["lr_race"] = bool(focus_info.get("lr_race"))
        except Exception:
            pass
        direction_out["display_targets"] = list(new_c.get("display_targets") or [])
        try:
            from core.strategy_target_format import collect_display_targets, format_targets_line

            direction_out["display_targets"] = collect_display_targets(
                direction_out, player=player
            )
            direction_out["display_targets_line"] = format_targets_line(
                direction_out, player=player
            )
            new_c["display_targets"] = list(direction_out["display_targets"])
            set_sticky_commitment(player, new_c)
        except Exception:
            pass
        direction_out["sticky_applied"] = True
        direction_out["sticky_reason"] = meta["reason"]
        src = str(direction_out.get("preference_source") or "")
        if "S1_sticky" not in src:
            direction_out["preference_source"] = (src + "+S1_sticky").lstrip("+")
        direction_out["sticky_meta"] = {
            "held": False,
            "committed": True,
            "reason": meta["reason"],
            "invalidate_reason": meta.get("invalidate_reason") or "",
            "flag_consumed": meta["flag_consumed"],
            "flag_reasons": meta["flag_reasons"],
            "locked_way_id": meta["locked_way_id"],
            "locked_rec_target_id": meta["locked_rec_target_id"],
            "locked_target_kind": new_c.get("locked_target_kind"),
            "display_targets_line": direction_out.get("display_targets_line"),
            "lr_project": bool(new_c.get("lr_project")),
            "la_progress": bool(new_c.get("la_progress")),
            "turn_focus": direction_out.get("turn_focus"),
        }
    else:
        # No structure target — may still have LR-only and/or LA-only sticky
        try:
            from core.ai_lr_project import (
                apply_lr_project_to_direction,
                get_stored_lr_project,
                pick_turn_focus,
            )
            from core.ai_la_progress import (
                apply_la_progress_to_direction,
                get_stored_la_progress,
            )

            lr_now = get_stored_lr_project(player, game)
            la_now = get_stored_la_progress(player, game)
            if lr_now or la_now:
                if lr_now:
                    direction_out = apply_lr_project_to_direction(direction_out, player, game)
                if la_now:
                    direction_out = apply_la_progress_to_direction(direction_out, player, game)
                focus_info = pick_turn_focus(game, player)
                direction_out["turn_focus"] = focus_info.get("focus")
                direction_out["turn_focus_reason"] = focus_info.get("reason")
                direction_out["dense_pack"] = bool(focus_info.get("dense_pack"))
                direction_out["la_race"] = bool(focus_info.get("la_race"))
                direction_out["lr_race"] = bool(focus_info.get("lr_race"))
                direction_out["defer_optional_claim"] = bool(
                    focus_info.get("defer_optional_claim")
                )
                meta["applied"] = True
                meta["committed"] = True
                meta["reason"] = (
                    "sticky_commit_lr_la"
                    if lr_now and la_now
                    else ("sticky_commit_lr_only" if lr_now else "sticky_commit_la_only")
                )
                meta["turn_focus"] = focus_info.get("focus")
                meta["dense_pack"] = bool(focus_info.get("dense_pack"))
                meta["la_race"] = bool(focus_info.get("la_race"))
                meta["lr_race"] = bool(focus_info.get("lr_race"))
                try:
                    from core.strategy_target_format import (
                        collect_display_targets,
                        format_targets_line,
                    )

                    direction_out["display_targets"] = collect_display_targets(
                        direction_out, player=player
                    )
                    direction_out["display_targets_line"] = format_targets_line(
                        direction_out, player=player
                    )
                except Exception:
                    pass
                direction_out["sticky_applied"] = True
                direction_out["sticky_meta"] = {
                    "held": False,
                    "committed": True,
                    "reason": meta["reason"],
                    "lr_project": True,
                    "turn_focus": direction_out.get("turn_focus"),
                }
                if consume_flag or flag_before.get("pending"):
                    consume_strategy_recalc_flag(player)
                    meta["flag_consumed"] = True
                return direction_out, meta
        except Exception:
            pass
        meta["reason"] = "no_rec_target_to_lock"
        if meta["invalidated"]:
            meta["reason"] = "invalidated_no_new_target"
        if consume_flag:
            consume_strategy_recalc_flag(player)
            meta["flag_consumed"] = True
    return direction_out, meta
