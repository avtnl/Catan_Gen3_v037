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
    """Undirected road_id (min, max). Ownership / legal sets use this only."""
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
    """Dedupe to undirected road_ids ``[min, max]`` (order of first occurrence).

    Do **not** use this for path execution order. Paths need directed steps
    from the player's network toward the tip — see ``orient_path_roads_network_to_tip``.
    """
    out: List[List[int]] = []
    seen = set()
    for edge in list(roads or []):
        key = _road_key(edge)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append([int(key[0]), int(key[1])])
    return out


def _network_nodes_for_player(player: Any) -> set:
    """Intersections on this player's S/C + road network."""
    nodes: set = set()
    try:
        for sid in list(getattr(player, "settlements", []) or []):
            nodes.add(int(sid))
        for cid in list(getattr(player, "cities", []) or []):
            nodes.add(int(cid))
    except Exception:
        pass
    try:
        for edge in list(getattr(player, "roads", []) or []):
            key = _road_key(edge)
            if key is None:
                continue
            nodes.add(int(key[0]))
            nodes.add(int(key[1]))
    except Exception:
        pass
    return nodes


def orient_path_roads_network_to_tip(
    player: Any,
    roads: Any,
    tip_id: Any = None,
) -> List[List[int]]:
    """Orient / order path edges as directed steps ``[from, to]`` toward *tip*.

    Core distinction (Gen2 / Outlook):
      - **road_id** = undirected ``[min, max]`` (board edge identity)
      - **path step** = directed ``[from, to]`` along the route from the player's
        network toward the settlement tip (e.g. network@15 → ``[15, 14]`` then
        ``[14, 13]`` for tip@13 — never tip-first ``[13, 14]`` as the next build)

    Accepts mixed undirected ids or directed steps; returns directed steps in
    network→tip build order. Empty if *roads* is empty.
    """
    tip = _safe_int(tip_id, None)
    undirected: List[Tuple[int, int]] = []
    seen = set()
    for edge in list(roads or []):
        key = _road_key(edge)
        if key is None or key in seen:
            continue
        seen.add(key)
        undirected.append(key)
    if not undirected:
        return []

    network = _network_nodes_for_player(player)
    adj: Dict[int, List[int]] = {}
    for a, b in undirected:
        adj.setdefault(int(a), []).append(int(b))
        adj.setdefault(int(b), []).append(int(a))

    # Infer tip: degree-1 node in the subgraph that is not already on the network
    if tip is None:
        leaves = [n for n, nbrs in adj.items() if len(nbrs) == 1 and n not in network]
        if len(leaves) == 1:
            tip = int(leaves[0])
        elif leaves:
            tip = int(max(leaves))  # stable-ish pick
        else:
            # both ends on network or cycle — keep undirected id order as last resort
            return [[int(a), int(b)] for a, b in undirected]

    # BFS from network nodes that touch the path subgraph → reconstruct tip path
    from collections import deque

    starts = [n for n in network if n in adj]
    if not starts:
        # Path not yet attached: orient so tip is the last node if possible
        # Prefer a leaf that is the tip, walk the unique path
        if tip in adj and len(adj) <= len(undirected) + 1:
            # pick other leaf as start
            leaves = [n for n, nbrs in adj.items() if len(nbrs) == 1]
            start = None
            for leaf in leaves:
                if int(leaf) != int(tip):
                    start = int(leaf)
                    break
            if start is None and leaves:
                start = int(leaves[0])
            if start is not None:
                steps: List[List[int]] = []
                prev = None
                cur = start
                guard = 0
                while cur is not None and guard < 64:
                    guard += 1
                    nbrs = [x for x in adj.get(cur, []) if x != prev]
                    if not nbrs:
                        break
                    nxt = nbrs[0]
                    steps.append([int(cur), int(nxt)])
                    if int(nxt) == int(tip):
                        return steps
                    prev, cur = cur, nxt
        return [[int(a), int(b)] for a, b in undirected]

    parent: Dict[int, Optional[int]] = {}
    q: deque = deque()
    for s in sorted(starts):
        if s not in parent:
            parent[int(s)] = None
            q.append(int(s))
    while q:
        u = q.popleft()
        for v in sorted(adj.get(u, [])):
            if int(v) in parent:
                continue
            parent[int(v)] = int(u)
            q.append(int(v))

    if tip not in parent:
        # Tip not reachable through given edges from network — return
        # undirected leftovers (caller may still discover a path).
        return [[int(a), int(b)] for a, b in undirected]

    nodes_rev: List[int] = []
    cur: Optional[int] = int(tip)
    guard = 0
    while cur is not None and guard < 64:
        guard += 1
        nodes_rev.append(int(cur))
        cur = parent.get(int(cur))
    nodes_rev.reverse()
    steps = []
    for i in range(len(nodes_rev) - 1):
        steps.append([int(nodes_rev[i]), int(nodes_rev[i + 1])])
    return steps


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
    """Flag non-builder seats for whom the structure site is *plan-relevant* (P2).

    Multiple opponent builds only keep ``pending=True`` with accumulated
    reasons/builders — strategy re-rank happens once when the flag is consumed.
    Always invalidates portfolio geometry cache (board fingerprint).
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
    skipped_irrelevant: List[int] = []
    try:
        from core.strategy_dirty import structure_relevant_to_player
    except Exception:
        structure_relevant_to_player = None  # type: ignore
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (builder_id is not None and pid == builder_id):
            continue
        relevant = True
        if structure_relevant_to_player is not None:
            try:
                relevant = bool(structure_relevant_to_player(p, target_id, game))
            except Exception:
                relevant = True
        if not relevant:
            skipped_irrelevant.append(int(pid))
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=builder_id,
            detail={"target_id": target_id, "structure": kind, "relevant": True},
        )
        # WP3 code 6: plan-relevant structure is a sticky-target threat
        try:
            from core.strategy_explicit_recalc import note_sticky_target_threat

            note_sticky_target_threat(
                game,
                p,
                reason=f"{reason}:tw={target_id}",
                force=True,
            )
        except Exception:
            pass
        flagged.append(int(pid))
    # P2-B: board piece change → drop portfolio cache for all seats
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(game, f"structure:{reason}")
    except Exception:
        pass
    # Reachability maps: settle amends geometry; city upgrade does not.
    reachability: Dict[str, Any] = {}
    if "city" not in kind and target_id is not None:
        try:
            from core.player_reachability import notify_settlement_built

            reachability = notify_settlement_built(game, builder, int(target_id))
        except Exception:
            reachability = {}
    return {
        "reason": reason,
        "builder_id": builder_id,
        "flagged_player_ids": flagged,
        "skipped_irrelevant_player_ids": skipped_irrelevant,
        "structure": kind,
        "target_id": target_id,
        "reachability": reachability,
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
    """P2: batch-flag after opponent road only if plan-edge or LR-project relevant.

    ``only_lr_pursuers`` kept for API compat; relevance is via
    ``road_relevant_to_player`` (plan roads / LR project, not every map edge).
    """
    reason = "opponent_road"
    builder_id = _safe_int(getattr(builder, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    try:
        from core.strategy_dirty import road_relevant_to_player
    except Exception:
        road_relevant_to_player = None  # type: ignore
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (builder_id is not None and pid == builder_id):
            continue
        relevant = False
        if road_relevant_to_player is not None:
            try:
                relevant = bool(road_relevant_to_player(p, road_id, game))
            except Exception:
                relevant = only_lr_pursuers and _player_pursues_longest_road(p)
        else:
            relevant = (not only_lr_pursuers) or _player_pursues_longest_road(p)
        if not relevant:
            skipped.append(int(pid))
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=builder_id,
            detail={"road_id": road_id, "structure": "road", "relevant": True},
        )
        flagged.append(int(pid))
    # P2-B: road mutates board connectivity / LR landscape
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(game, f"road:{reason}")
    except Exception:
        pass
    reachability: Dict[str, Any] = {}
    try:
        from core.player_reachability import notify_road_built

        reachability = notify_road_built(game, builder, road_id)
    except Exception:
        reachability = {}
    return {
        "reason": reason,
        "reachability": reachability,
        "builder_id": builder_id,
        "flagged_player_ids": flagged,
        "skipped_irrelevant_player_ids": skipped,
        "skipped_non_lr_player_ids": skipped,  # legacy key
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
    """P2: batch-flag after knight only for LA-relevant seats."""
    reason = "opponent_knight"
    actor_id = _safe_int(getattr(player, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    try:
        from core.strategy_dirty import player_pursues_la
    except Exception:
        player_pursues_la = None  # type: ignore
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (actor_id is not None and pid == actor_id):
            continue
        la = False
        if player_pursues_la is not None:
            try:
                la = bool(player_pursues_la(p))
            except Exception:
                la = _player_pursues_largest_army(p)
        else:
            la = _player_pursues_largest_army(p)
        if only_la_pursuers and not la:
            skipped.append(int(pid))
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=actor_id,
            detail={"army_size": army_size, "structure": "knight", "relevant": True},
        )
        flagged.append(int(pid))
    return {
        "reason": reason,
        "builder_id": actor_id,
        "flagged_player_ids": flagged,
        "skipped_non_la_player_ids": skipped,
        "skipped_irrelevant_player_ids": skipped,
        "army_size": army_size,
        "only_la_pursuers": bool(only_la_pursuers),
    }


def flag_opponents_after_dcard_buy(
    game: Any,
    buyer: Any,
    *,
    only_la_pursuers: bool = True,
) -> Dict[str, Any]:
    """P2-7: opp DCard buy → dirty only if LA-relevant (or thin-deck + LA care)."""
    reason = "opponent_dcard_buy"
    buyer_id = _safe_int(getattr(buyer, "id", None), None)
    flagged: List[int] = []
    skipped: List[int] = []
    try:
        from core.strategy_dirty import dcard_buy_relevant_to_player
    except Exception:
        dcard_buy_relevant_to_player = None  # type: ignore
    for p in list(getattr(game, "players", None) or []):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None or (buyer_id is not None and pid == buyer_id):
            continue
        relevant = False
        if dcard_buy_relevant_to_player is not None:
            try:
                relevant = bool(dcard_buy_relevant_to_player(p, game, buyer))
            except Exception:
                relevant = (not only_la_pursuers) or _player_pursues_largest_army(p)
        else:
            relevant = (not only_la_pursuers) or _player_pursues_largest_army(p)
        if only_la_pursuers and not relevant:
            skipped.append(int(pid))
            continue
        if not relevant:
            skipped.append(int(pid))
            continue
        flag_strategy_recalc(
            p,
            reason,
            builder_id=buyer_id,
            detail={"structure": "dcard_buy", "relevant": True},
        )
        flagged.append(int(pid))
    return {
        "reason": reason,
        "builder_id": buyer_id,
        "flagged_player_ids": flagged,
        "skipped_non_la_player_ids": skipped,
        "skipped_irrelevant_player_ids": skipped,
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


def remaining_roads_for_player(
    player: Any,
    roads: Sequence[Any],
    tip_id: Any = None,
) -> List[List[int]]:
    """Drop owned edges, then return **directed** network→tip path steps.

    Ownership uses undirected road_ids. Returned steps keep path direction so
    ``roads_to_build[0]`` is always the legal next build from the network when
    the route is attached (e.g. ``[15, 14]`` not tip-first ``[13, 14]``).
    """
    owned = _own_road_keys(player)
    remaining_u: List[Tuple[int, int]] = []
    seen = set()
    for edge in list(roads or []):
        key = _road_key(edge)
        if key is None or key in owned or key in seen:
            continue
        seen.add(key)
        remaining_u.append(key)
    if not remaining_u:
        return []
    tip = _safe_int(tip_id, None)
    directed = orient_path_roads_network_to_tip(player, remaining_u, tip_id=tip)
    if directed:
        return directed
    return [[int(a), int(b)] for a, b in remaining_u]


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


def _residual_new_settles(direction: Mapping[str, Any], player: Any = None) -> int:
    """Best-effort remaining new settlements from direction / way residual."""
    for key in (
        "req_settles",
        "remaining_new_settlements",
        "required_new_intersections",
    ):
        v = _safe_int((direction or {}).get(key), None)
        if v is not None and v > 0:
            return int(v)
    try:
        req = (direction or {}).get("requirements")
        if isinstance(req, Mapping):
            v = _safe_int(
                req.get("required_new_intersections")
                or req.get("remaining_new_settlements")
                or req.get("new_settlements"),
                None,
            )
            if v is not None and v > 0:
                return int(v)
    except Exception:
        pass
    try:
        from core.strategy_way_residual import compute_way_residual

        bag = compute_way_residual(
            (direction or {}).get("preferred_way_id")
            or (direction or {}).get("way_id")
            or getattr(player, "preferred_way_id", None),
            player,
            preferred=direction,
        )
        v = _safe_int((bag or {}).get("req_settles"), 0) or 0
        if v > 0:
            return int(v)
    except Exception:
        pass
    return 0


def _pick_best_open_settle_tip(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Pick an open settle tip (portfolio or geometry) for post-structure recommit.

    Returns ``{target_id, roads, dist, score_key}`` or None.
    Does not hard-ban contested/high race — shortest playboard path wins.
    """
    tips: List[Dict[str, Any]] = []

    def _add(tid: Any, *, roads: Any = None, dist: Any = None, eta: Any = None, score: Any = None) -> None:
        i = _safe_int(tid, None)
        if i is None:
            return
        try:
            if target_occupied_by_other(game, player, int(i)) or target_blocked_on_board(game, int(i)):
                return
        except Exception:
            pass
        if roads is not None:
            directed = orient_path_roads_network_to_tip(player, roads, tip_id=int(i))
            road_list = directed if directed else _normalize_roads(roads)
        else:
            road_list = []
        tips.append(
            {
                "target_id": int(i),
                "roads": road_list,
                "dist": _safe_int(dist, 99) or 99,
                "eta": _safe_float(eta, 9999.0),
                "score": _safe_float(score, -9999.0),
            }
        )

    # Preferred audit portfolio first
    preferred_way = _safe_int(
        (direction or {}).get("preferred_way_id") or (direction or {}).get("way_id"),
        None,
    )
    ordered_audits = list(audits or [])
    if preferred_way is not None:
        ordered_audits = sorted(
            ordered_audits,
            key=lambda a: 0 if _safe_int(_audit_get(a, "way_id"), None) == preferred_way else 1,
        )
    for audit in ordered_audits:
        for item in _portfolio_list(audit):
            tid = _target_id_of(item)
            if tid is None:
                continue
            kind = str(_target_field(item, "kind", "") or _target_field(item, "target_kind", "") or "S").upper()
            if kind in ("C", "CITY", "CITY_UPGRADE"):
                continue
            roads = (
                _target_field(item, "roads_to_build", None)
                or _target_field(item, "path", None)
                or _target_field(item, "roads", None)
            )
            _add(
                tid,
                roads=roads,
                dist=_target_field(item, "distance_roads", None) or _target_field(item, "dist", None),
                eta=_target_field(item, "self_eta", None) or _target_field(item, "eta", None),
                score=_target_field(item, "priority_score", None) or _target_field(item, "score", None),
            )
        if tips:
            break

    # Geometry fallback — WP-R4: map-first, then outlook
    if not tips and game is not None and player is not None:
        try:
            from core.constants import REACHABILITY_MAPS
            from core.outlook_logic import (
                find_reachable_new_settlement_paths,
                next_settlement_spots,
            )
            from core.player_reachability import (
                SENTINEL,
                ensure_reachability_maps,
                maps_are_fresh,
                path_to_target,
                remaining_roads_to_target,
            )

            if bool(REACHABILITY_MAPS):
                ensure_reachability_maps(game, player)

            pid = int(getattr(player, "id"))
            spots = list(next_settlement_spots(game, pid) or [])

            if maps_are_fresh(player):
                # Prefer open tips with remaining roads ≤ 3 from maps
                try:
                    from core.outlook_logic import new_settlement_spots

                    cand_ids = list(new_settlement_spots(game, pid) or [])[:16]
                except Exception:
                    cand_ids = list(spots)[:16]
                for tid in cand_ids:
                    rd = remaining_roads_to_target(player, int(tid))
                    if rd is None or int(rd) >= SENTINEL or int(rd) < 1:
                        continue
                    if int(rd) > 3:
                        continue
                    _add(
                        tid,
                        roads=path_to_target(player, int(tid)),
                        dist=int(rd),
                    )

            if not tips:
                paths = find_reachable_new_settlement_paths(
                    game, player, target_ids=spots[:12] or None, max_distance=3
                )
                for p in paths or []:
                    if not isinstance(p, Mapping):
                        continue
                    _add(
                        p.get("target_settlement_id")
                        or p.get("target_id")
                        or p.get("settlement_id"),
                        roads=p.get("roads_to_build") or p.get("path"),
                        dist=p.get("roads_remaining") or p.get("distance"),
                        eta=p.get("eta"),
                    )
            if not tips:
                for sid in spots[:8]:
                    _add(sid, dist=0)
        except Exception:
            pass

    if not tips:
        return None
    tips.sort(key=lambda t: (float(t["eta"]), int(t["dist"]), -float(t["score"]), int(t["target_id"])))
    return tips[0]


# Soft invalidate reasons that should not abandon a still-Fastest settle (WP-STICKY1).
_SOFT_RERANK_INVALIDATE = (
    "force_strategy_recalc",
    "strategy_recalc",
    "flag:lr_or_component",
    "need_next_target",
    "wp_h",
    "same_way",
)
# New tip must beat previous ETA by at least this many turns to steal sticky.
STICKY1_ETA_IMPROVE_MIN = 1.0
# WP-STICKY2: block way_switch that worsens next-settle ETA by this much (Dig g002 S47→S61).
STICKY2_ETA_WORSEN_MIN = 1.5
_STICKY2_ALLOW_SWITCH_TOKENS = (
    "race_",
    "deny",
    "occupied",
    "blocked",
    "impossible",
    "explicit_142",
    "board_fit",
    "specials_dead",
    "offway",
    "s14_2",
    "structure_surplus",
    "holds_lr",
    "holds_la",
)


def _settle_eta_from_audits_or_direction(
    audits: Sequence[Any],
    direction: Mapping[str, Any],
    target_id: int,
) -> Optional[float]:
    """Best-effort ETA for a settle id from audits / direction catalog."""
    tid = int(target_id)
    for audit in list(audits or []):
        try:
            settles = _audit_get(audit, "plan_settles") or _audit_get(audit, "settles")
            if isinstance(settles, Mapping):
                row = settles.get(tid) or settles.get(str(tid))
                if isinstance(row, Mapping):
                    for k in ("eta", "eta_turns", "turns"):
                        if row.get(k) is not None:
                            return float(row.get(k))
                elif row is not None:
                    try:
                        return float(row)
                    except Exception:
                        pass
            # compact catalog "24:3:14.0:high:..."
            cat = str(_audit_get(audit, "plan_catalog") or "")
            for part in cat.split(";"):
                if part.startswith(f"S{tid}:") or part.startswith(f"{tid}:"):
                    bits = part.split(":")
                    if len(bits) >= 3:
                        try:
                            return float(bits[2])
                        except Exception:
                            pass
        except Exception:
            continue
    try:
        cat = str(direction.get("plan_catalog") or "")
        for part in cat.split(";"):
            if part.startswith(f"S{tid}:"):
                bits = part.split(":")
                if len(bits) >= 3:
                    return float(bits[2])
    except Exception:
        pass
    # direction portfolio sites
    for key in ("plan_settles", "settlement_etas", "settle_etas"):
        bag = direction.get(key)
        if isinstance(bag, Mapping):
            row = bag.get(tid) or bag.get(str(tid))
            if isinstance(row, Mapping) and row.get("eta") is not None:
                try:
                    return float(row.get("eta"))
                except Exception:
                    pass
            try:
                if row is not None:
                    return float(row)
            except Exception:
                pass
    return None


def _target_still_open_for_player(
    game: Any,
    player: Any,
    target_id: int,
) -> bool:
    """True if settle vertex is still buildable / not occupied."""
    tid = int(target_id)
    try:
        for p in list(getattr(game, "players", []) or []):
            for attr in ("settlements", "cities"):
                owned = list(getattr(p, attr, []) or [])
                if tid in owned or str(tid) in {str(x) for x in owned}:
                    return False
    except Exception:
        pass
    try:
        board = getattr(game, "board", None)
        if board is not None:
            occ = getattr(board, "is_vertex_occupied", None) or getattr(
                board, "vertex_occupied", None
            )
            if callable(occ) and bool(occ(tid)):
                return False
            can = getattr(board, "can_build_settlement_at", None)
            if callable(can) and player is not None:
                try:
                    return bool(can(tid, getattr(player, "color", None)))
                except TypeError:
                    return bool(can(tid))
    except Exception:
        pass
    return True


def maybe_preserve_prev_settle_on_soft_rerank(
    direction: Mapping[str, Any],
    prev_commitment: Optional[Mapping[str, Any]],
    game: Any,
    player: Any,
    audits: Sequence[Any],
    *,
    invalidate_reason: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """WP-STICKY1: keep invested settle on soft same-way rerank unless clearly worse.

    Returns (direction_out, meta). Meta empty when no preserve applied.
    """
    direction_out = dict(direction or {})
    meta: Dict[str, Any] = {}
    prev = prev_commitment if isinstance(prev_commitment, Mapping) else None
    if not prev:
        return direction_out, meta
    inv = str(invalidate_reason or "").lower()
    # Hard invalidates always allow retarget
    if any(
        h in inv
        for h in (
            "occupied",
            "race_impossible",
            "route_illegal",
            "own_rec_settle_complete",
            "own_rec_city_complete",
            "explicit_142",
            "specials_dead",
            "offway_opportunity",
            "s14_2",
        )
    ):
        meta["skipped"] = "hard_invalidate"
        return direction_out, meta
    soft = (not inv) or any(tok in inv for tok in _SOFT_RERANK_INVALIDATE)
    if not soft:
        meta["skipped"] = f"not_soft:{inv[:40]}"
        return direction_out, meta

    prev_tid = _safe_int(prev.get("locked_rec_target_id"), None)
    prev_way = _safe_int(prev.get("locked_way_id"), None)
    prev_kind = str(prev.get("locked_target_kind") or "").upper()
    if prev_tid is None:
        return direction_out, meta
    if prev_kind and prev_kind not in ("S", "SETTLE", "SETTLEMENT", "NEW_SETTLEMENT", ""):
        meta["skipped"] = f"prev_kind:{prev_kind}"
        return direction_out, meta

    new_way = _safe_int(
        direction_out.get("preferred_way_id") or direction_out.get("way_id"),
        None,
    )
    if prev_way is not None and new_way is not None and int(prev_way) != int(new_way):
        meta["skipped"] = "way_changed"
        return direction_out, meta

    new_tid = _safe_int(
        direction_out.get("recommendation_target_id")
        or direction_out.get("settlement_target_id")
        or direction_out.get("target_id"),
        None,
    )
    if new_tid is None or int(new_tid) == int(prev_tid):
        meta["skipped"] = "same_or_no_new_tid"
        return direction_out, meta

    if not _target_still_open_for_player(game, player, int(prev_tid)):
        meta["skipped"] = "prev_occupied"
        return direction_out, meta

    eta_prev = _settle_eta_from_audits_or_direction(audits, direction_out, int(prev_tid))
    eta_new = _settle_eta_from_audits_or_direction(audits, direction_out, int(new_tid))
    # Also compare direction's own preferred eta if present
    try:
        if eta_new is None and direction_out.get("eta_turns") is not None:
            eta_new = float(direction_out.get("eta_turns"))
    except Exception:
        pass

    improve = None
    if eta_prev is not None and eta_new is not None:
        improve = float(eta_prev) - float(eta_new)  # positive = new faster
        if improve >= float(STICKY1_ETA_IMPROVE_MIN):
            meta["skipped"] = "new_eta_clearly_better"
            meta["eta_prev"] = eta_prev
            meta["eta_new"] = eta_new
            meta["improve"] = improve
            return direction_out, meta

    # Preserve previous settle tip; refresh roads toward it if available
    direction_out["recommendation_target_id"] = int(prev_tid)
    direction_out["settlement_target_id"] = int(prev_tid)
    direction_out["supporting_action_type"] = "new_settlement"
    direction_out["wp_sticky1_preserved_target"] = int(prev_tid)
    direction_out["wp_sticky1_blocked_target"] = int(new_tid)
    # Prefer repath for prev tid from audits
    try:
        fixed = repath_roads_for_locked_target(
            audits,
            player,
            target_id=int(prev_tid),
            way_id=prev_way or new_way,
            fallback_roads=prev.get("locked_roads_to_build"),
        )
        if fixed:
            direction_out["roads_to_build"] = list(fixed)
        elif prev.get("locked_roads_to_build"):
            direction_out["roads_to_build"] = list(prev.get("locked_roads_to_build") or [])
    except Exception:
        if prev.get("locked_roads_to_build"):
            direction_out["roads_to_build"] = list(prev.get("locked_roads_to_build") or [])

    meta.update(
        {
            "preserved": True,
            "prev_tid": int(prev_tid),
            "blocked_tid": int(new_tid),
            "eta_prev": eta_prev,
            "eta_new": eta_new,
            "improve": improve,
            "invalidate_reason": inv,
        }
    )
    return direction_out, meta


def maybe_block_way_switch_worse_settle_eta(
    direction: Mapping[str, Any],
    prev_commitment: Optional[Mapping[str, Any]],
    game: Any,
    player: Any,
    audits: Sequence[Any],
    *,
    invalidate_reason: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """WP-STICKY2: keep prior way+settle when switch worsens next-settle ETA.

    Dig (g002 R6T4): Engine/way_switch to S61 while S47 still eta 0.8 ≪ 3.2.
    Allows switch when invalidate cites race/deny/occupied/board-fit/etc.
    """
    direction_out = dict(direction or {})
    meta: Dict[str, Any] = {}
    prev = prev_commitment if isinstance(prev_commitment, Mapping) else None
    if not prev:
        return direction_out, meta

    prev_way = _safe_int(prev.get("locked_way_id"), None)
    prev_tid = _safe_int(prev.get("locked_rec_target_id"), None)
    new_way = _safe_int(
        direction_out.get("preferred_way_id") or direction_out.get("way_id"),
        None,
    )
    new_tid = _safe_int(
        direction_out.get("recommendation_target_id")
        or direction_out.get("settlement_target_id")
        or direction_out.get("target_id")
        or direction_out.get("plan_se_pick_id"),
        None,
    )
    # plan_se_pick may be "S61"
    if new_tid is None:
        se = str(direction_out.get("plan_se_pick") or "")
        if se.upper().startswith("S"):
            try:
                new_tid = int(se[1:].split(":")[0])
            except Exception:
                new_tid = None

    if prev_way is None or new_way is None or int(prev_way) == int(new_way):
        meta["skipped"] = "same_or_missing_way"
        return direction_out, meta
    if prev_tid is None:
        meta["skipped"] = "no_prev_settle"
        return direction_out, meta

    inv = str(invalidate_reason or "").lower()
    if any(tok in inv for tok in _STICKY2_ALLOW_SWITCH_TOKENS):
        meta["skipped"] = f"allow_reason:{inv[:48]}"
        return direction_out, meta

    if not _target_still_open_for_player(game, player, int(prev_tid)):
        meta["skipped"] = "prev_occupied"
        return direction_out, meta

    eta_prev = _settle_eta_from_audits_or_direction(audits, direction_out, int(prev_tid))
    # Prefer new tip ETA; fall back to se_pick / catalog first settle on new way
    eta_new = None
    if new_tid is not None:
        eta_new = _settle_eta_from_audits_or_direction(audits, direction_out, int(new_tid))
    if eta_new is None:
        try:
            cat = str(direction_out.get("plan_catalog") or "")
            for part in cat.split(";"):
                if part.upper().startswith("S") and ":" in part:
                    bits = part.split(":")
                    if len(bits) >= 3:
                        eta_new = float(bits[2])
                        if new_tid is None:
                            try:
                                new_tid = int(bits[0][1:])
                            except Exception:
                                pass
                        break
        except Exception:
            eta_new = None

    if eta_prev is None or eta_new is None:
        meta["skipped"] = "missing_eta"
        meta["eta_prev"] = eta_prev
        meta["eta_new"] = eta_new
        return direction_out, meta

    worsen = float(eta_new) - float(eta_prev)
    meta["eta_prev"] = eta_prev
    meta["eta_new"] = eta_new
    meta["worsen"] = worsen
    if worsen < float(STICKY2_ETA_WORSEN_MIN):
        meta["skipped"] = "eta_ok"
        return direction_out, meta

    # Block switch: restore previous way + settle tip
    direction_out["preferred_way_id"] = int(prev_way)
    direction_out["way_id"] = int(prev_way)
    direction_out["recommendation_target_id"] = int(prev_tid)
    direction_out["settlement_target_id"] = int(prev_tid)
    direction_out["supporting_action_type"] = str(
        direction_out.get("supporting_action_type") or "new_settlement"
    )
    direction_out["wp_sticky2_blocked_way"] = int(new_way)
    direction_out["wp_sticky2_kept_way"] = int(prev_way)
    if prev.get("locked_roads_to_build"):
        direction_out["roads_to_build"] = list(prev.get("locked_roads_to_build") or [])
    try:
        fixed = repath_roads_for_locked_target(
            audits,
            player,
            target_id=int(prev_tid),
            way_id=int(prev_way),
            fallback_roads=prev.get("locked_roads_to_build"),
        )
        if fixed:
            direction_out["roads_to_build"] = list(fixed)
    except Exception:
        pass

    meta.update(
        {
            "blocked": True,
            "prev_way": int(prev_way),
            "new_way": int(new_way),
            "prev_tid": int(prev_tid),
            "new_tid": int(new_tid) if new_tid is not None else None,
            "invalidate_reason": inv,
            "reason": "wp_sticky2_worse_settle_eta",
        }
    )
    return direction_out, meta


def try_commit_settle_tip_before_specials(
    direction: Mapping[str, Any],
    game: Any,
    player: Any,
    audits: Sequence[Any],
) -> Optional[Dict[str, Any]]:
    """If settle residual remains and direction has no tid, lock best open settle tip.

    Prevents post-city ``sticky_commit_la_only`` while 1×S (e.g. S44) is still open.
    """
    if not isinstance(direction, Mapping):
        return None
    rem_s = _residual_new_settles(direction, player)
    need_next = False
    try:
        from core.strategy_reconsider import get_reconsider_flags

        flags = get_reconsider_flags(player) or {}
        need_next = bool(flags.get("need_next_target"))
    except Exception:
        need_next = bool(getattr(player, "force_strategy_recalc", False))
    if rem_s <= 0 and not need_next:
        return None
    # Already has a structure tid in direction — normal commit handles it
    existing_tid = _safe_int(
        direction.get("recommendation_target_id")
        or direction.get("settlement_target_id")
        or direction.get("target_id"),
        None,
    )
    if existing_tid is not None and rem_s <= 0:
        return None
    tip = _pick_best_open_settle_tip(game, player, audits, direction)
    if tip is None:
        return None
    enriched = dict(direction)
    enriched["recommendation_target_id"] = tip["target_id"]
    enriched["settlement_target_id"] = tip["target_id"]
    enriched["supporting_action_type"] = "new_settlement"
    if tip.get("roads"):
        enriched["roads_to_build"] = list(tip["roads"])
    enriched["sticky_settle_tip_source"] = "post_structure_geo_tip"
    return commit_from_direction(enriched, game, player)


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
    # S18: prefer portfolio roads for this tid; drop orphan edges for other sites.
    # Orient network→tip so roads_to_build[0] is the legal next directed step.
    roads = remaining_roads_for_player(
        player, direction_local.get("roads_to_build") or [], tip_id=tid
    )
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
    # S4: persist partial_plan / ignored_components on sticky for dig + re-lock gates
    try:
        from core.partial_way_salvage import stamp_commitment_partial_plan

        stamp_commitment_partial_plan(out_c, direction_local, None, game)
    except Exception:
        pass
    if isinstance(direction_local, Mapping):
        if direction_local.get("partial_plan"):
            out_c["partial_plan"] = True
        ign = direction_local.get("ignored_components")
        if ign:
            out_c["ignored_components"] = list(ign)
            if "LR" in ign or "lr" in {str(x).upper() for x in ign}:
                out_c.pop("lr_project", None)
            if "LA" in ign or "la" in {str(x).lower() for x in ign}:
                out_c.pop("la_progress", None)
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
            if feas in _FEAS_KILL or feas == "board_unfit":
                return True, "locked_way_infeasible"
        # WP2: locked way cannot realize structure / held specials
        try:
            from core.strategy_board_fit import is_board_fit_enabled, way_fits_player

            if is_board_fit_enabled(game) and not way_fits_player(
                way_id, player, game=game
            ):
                return True, "board_fit_unfit"
        except Exception:
            pass

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
        return remaining_roads_for_player(player, fallback_roads or [], tip_id=None)
    _audit, target = find_target_in_audits(
        audits, tid, preferred_way_id=_safe_int(way_id, None)
    )
    if target is not None:
        fresh = _target_field(target, "roads_to_build", [])
        return remaining_roads_for_player(player, fresh, tip_id=tid)
    # WP-R4: path_map before empty-fallback "at site" (empty fb ⇒ roads_serve_target True)
    try:
        from core.player_reachability import (
            SENTINEL,
            maps_are_fresh,
            path_to_target,
            remaining_roads_to_target,
        )

        if maps_are_fresh(player):
            rd = remaining_roads_to_target(player, int(tid))
            if rd == 0:
                return []
            if 0 < int(rd) < SENTINEL:
                mapped = path_to_target(player, int(tid))
                if mapped:
                    return remaining_roads_for_player(player, mapped, tip_id=tid)
    except Exception:
        pass
    fb = list(fallback_roads or [])
    if roads_serve_target(fb, tid):
        return remaining_roads_for_player(player, fb, tip_id=tid)
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


def _achieve_kind_from_invalidate(inv_reason: str) -> Optional[str]:
    r = str(inv_reason or "").lower()
    if "own_rec_settle_complete" in r or "settle_complete" in r:
        return "settle"
    if "own_rec_city_complete" in r or "city_complete" in r:
        return "city"
    return None


def _sticky_apply_action(
    meta: Mapping[str, Any],
    *,
    prev_way: Optional[int],
    cur_way: Optional[int],
    prev_tid: Optional[int],
    cur_tid: Optional[int],
    prev_roads_fp: Optional[str],
    cur_roads_fp: Optional[str],
) -> str:
    """Phase C: coarse sticky apply outcome for CS dig-in."""
    if bool(meta.get("held")):
        if (
            prev_tid is not None
            and cur_tid is not None
            and prev_tid == cur_tid
            and prev_roads_fp is not None
            and cur_roads_fp is not None
            and prev_roads_fp != cur_roads_fp
        ):
            return "repath"
        return "hold"
    if bool(meta.get("invalidated")) and cur_way is None and cur_tid is None:
        if not bool(meta.get("committed")):
            return "clear"
    if bool(meta.get("committed")) or cur_way is not None or cur_tid is not None:
        if prev_way is None and cur_way is not None:
            return "new_commitment"
        if prev_way is not None and cur_way is not None and prev_way != cur_way:
            return "way_switch"
        if prev_tid is not None and cur_tid is not None and prev_tid != cur_tid:
            return "retarget"
        if prev_tid is None and cur_tid is not None:
            return "retarget"
        return "new_commitment"
    if bool(meta.get("invalidated")):
        return "clear"
    return str(meta.get("reason") or "none") or "none"


def publish_last_sticky_cs_meta(
    player: Any,
    game: Any,
    meta: Optional[Mapping[str, Any]] = None,
    *,
    prev_commitment: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Phase C WP-C1: publish ``player.last_sticky_meta`` for CS schema v2.

    Safe no-op bag when inputs are thin. Call after every sticky apply outcome.
    """
    meta = meta if isinstance(meta, Mapping) else {}
    prev_c = prev_commitment if isinstance(prev_commitment, Mapping) else None
    cur_c = get_sticky_commitment(player)

    try:
        from core.batch.strategy_change_taxonomy import (
            roads_fingerprint,
            suggest_target_switch_cause_from_invalidate,
            suggest_way_switch_cause_from_invalidate,
        )
    except Exception:  # pragma: no cover
        def roads_fingerprint(roads: Any) -> Optional[str]:  # type: ignore[misc]
            return None

        def suggest_way_switch_cause_from_invalidate(*_a: Any, **_k: Any) -> str:  # type: ignore[misc]
            return "unknown"

        def suggest_target_switch_cause_from_invalidate(*_a: Any, **_k: Any) -> str:  # type: ignore[misc]
            return "unknown"

    prev_way = _safe_int((prev_c or {}).get("locked_way_id"), None)
    prev_tid = _safe_int((prev_c or {}).get("locked_rec_target_id"), None)
    prev_kind = str((prev_c or {}).get("locked_target_kind") or "") or None
    prev_roads_fp = roads_fingerprint((prev_c or {}).get("locked_roads_to_build"))

    cur_way = _safe_int(
        meta.get("locked_way_id"),
        _safe_int((cur_c or {}).get("locked_way_id"), None),
    )
    cur_tid = _safe_int(
        meta.get("locked_rec_target_id"),
        _safe_int((cur_c or {}).get("locked_rec_target_id"), None),
    )
    cur_kind = str(
        (cur_c or {}).get("locked_target_kind")
        or meta.get("locked_target_kind")
        or ""
    ) or None
    cur_roads = list(
        meta.get("locked_roads_to_build")
        or ((cur_c or {}).get("locked_roads_to_build") if cur_c else None)
        or []
    )
    cur_roads_fp = roads_fingerprint(cur_roads)

    inv = str(meta.get("invalidate_reason") or "")
    achieve_kind = _achieve_kind_from_invalidate(inv)

    is_first_way = prev_way is None and cur_way is not None
    is_first_target = prev_tid is None and cur_tid is not None
    way_changed = bool(
        (prev_way is None and cur_way is not None)
        or (prev_way is not None and cur_way is not None and prev_way != cur_way)
    )
    # first lock counts as way_changed=False for switch rates; flag separately
    target_changed = bool(
        (prev_tid is None and cur_tid is not None)
        or (prev_tid is not None and cur_tid is not None and prev_tid != cur_tid)
        or (prev_kind and cur_kind and prev_kind != cur_kind and prev_tid == cur_tid)
    )
    roads_changed = bool(
        prev_tid is not None
        and cur_tid is not None
        and prev_tid == cur_tid
        and prev_roads_fp is not None
        and cur_roads_fp is not None
        and prev_roads_fp != cur_roads_fp
    )

    q1_offway = bool(meta.get("s14_offway")) or "s14_2" in inv.lower() or "offway" in inv.lower()
    way_kill = "way_kill" in inv.lower() or "infeasible" in inv.lower()

    apply_action = _sticky_apply_action(
        meta,
        prev_way=prev_way,
        cur_way=cur_way,
        prev_tid=prev_tid,
        cur_tid=cur_tid,
        prev_roads_fp=prev_roads_fp,
        cur_roads_fp=cur_roads_fp,
    )

    way_switch_cause = None
    if is_first_way:
        way_switch_cause = "first_lock"
    elif way_changed and prev_way is not None:
        way_switch_cause = suggest_way_switch_cause_from_invalidate(
            inv,
            is_first_lock=False,
            q1_offway=q1_offway,
            way_kill=way_kill,
        )

    target_switch_cause = None
    if is_first_target:
        target_switch_cause = "first_lock"
    elif target_changed:
        target_switch_cause = suggest_target_switch_cause_from_invalidate(
            inv,
            is_first_lock=False,
            achieve_kind=str(achieve_kind or ""),
            way_changed=way_changed and prev_way is not None,
            q1_offway=q1_offway,
        )

    # L2 dig-in (optional)
    l2_bucket = None
    l2_force_reason = None
    try:
        st = getattr(player, "last_strategy_context_status", None) if player is not None else None
        if not isinstance(st, Mapping) and game is not None:
            st = getattr(game, "last_strategy_context_status", None)
        if isinstance(st, Mapping):
            pol = st.get("l2_policy")
            if isinstance(pol, Mapping):
                l2_bucket = str(pol.get("bucket") or "") or None
                l2_force_reason = str(pol.get("reason") or pol.get("force_reason") or "") or None
    except Exception:
        pass

    way_kill_kind = None
    try:
        wk = getattr(player, "last_way_kill", None) if player is not None else None
        if isinstance(wk, Mapping):
            way_kill_kind = str(wk.get("kind") or wk.get("type") or "") or None
    except Exception:
        pass

    switch_eta_gain = None  # filled by CS row when turns known

    bag: Dict[str, Any] = {
        "sticky_way_id": cur_way,
        "sticky_target_id": cur_tid,
        "sticky_target_kind": cur_kind,
        "sticky_roads_fp": cur_roads_fp,
        "prev_sticky_way_id": prev_way,
        "prev_sticky_target_id": prev_tid,
        "prev_sticky_target_kind": prev_kind,
        "prev_sticky_roads_fp": prev_roads_fp,
        "way_changed": bool(way_changed and prev_way is not None),
        "target_changed": bool(target_changed and not is_first_target),
        "roads_changed": roads_changed,
        "is_first_way_lock": is_first_way,
        "is_first_target_lock": is_first_target,
        "sticky_invalidate_reason": inv or None,
        "sticky_apply_action": apply_action,
        "way_switch_cause": way_switch_cause,
        "target_switch_cause": target_switch_cause,
        "switch_eta_gain": switch_eta_gain,
        "l2_bucket": l2_bucket,
        "l2_force_reason": l2_force_reason,
        "way_kill_kind": way_kill_kind,
        "q1_offway": bool(q1_offway) or None,
        "achieve_kind": achieve_kind,
        "held": bool(meta.get("held")),
        "committed": bool(meta.get("committed")),
        "invalidated": bool(meta.get("invalidated")),
        "sticky_reason": str(meta.get("reason") or "") or None,
        "round": _safe_int(getattr(game, "round", None), None) if game is not None else None,
        "turn": _safe_int(getattr(game, "turn", None), None) if game is not None else None,
        "player_id": _safe_int(getattr(player, "id", None), None) if player is not None else None,
    }

    try:
        if player is not None:
            setattr(player, "last_sticky_meta", dict(bag))
    except Exception:
        pass

    # Phase C2 dig: stamp refresh gate on sticky meta (for CS target-renew attribution)
    if game is not None:
        try:
            bag["refresh_mode"] = str(getattr(game, "_strategy_refresh_mode", None) or "") or None
            bag["refresh_mode_detail"] = (
                str(getattr(game, "_strategy_refresh_mode_detail", None) or "") or None
            )
            st = getattr(game, "last_strategy_context_status", None)
            if isinstance(st, Mapping):
                pol = st.get("l2_policy") if isinstance(st.get("l2_policy"), Mapping) else {}
                if pol:
                    bag["l2_bucket"] = bag.get("l2_bucket") or pol.get("bucket")
                    bag["l2_force_reason"] = bag.get("l2_force_reason") or pol.get("gate")
        except Exception:
            pass
        try:
            meta_live = getattr(player, "last_sticky_meta", None)
            if isinstance(meta_live, dict):
                meta_live["refresh_mode"] = bag.get("refresh_mode")
                meta_live["refresh_mode_detail"] = bag.get("refresh_mode_detail")
                if bag.get("l2_bucket") is not None:
                    meta_live["l2_bucket"] = bag.get("l2_bucket")
                if bag.get("l2_force_reason") is not None:
                    meta_live["l2_force_reason"] = bag.get("l2_force_reason")
                setattr(player, "last_sticky_meta", meta_live)
        except Exception:
            pass

    # Phase C2 WP-R5: snapshot first-way fit once at first Victory-Way lock
    if is_first_way and player is not None:
        try:
            from core.first_way_fit import maybe_snapshot_on_first_lock

            fit = maybe_snapshot_on_first_lock(
                game, player, is_first_way=True, way_id=cur_way
            )
            if isinstance(fit, Mapping):
                bag["first_way_fit"] = {
                    "way_id": fit.get("way_id"),
                    "fit_total": fit.get("fit_total"),
                    "fit_own": fit.get("fit_own"),
                    "fit_board": fit.get("fit_board"),
                    "fit_expand": fit.get("fit_expand"),
                }
                try:
                    meta_out = getattr(player, "last_sticky_meta", None)
                    if isinstance(meta_out, dict):
                        meta_out["first_way_fit"] = bag["first_way_fit"]
                        setattr(player, "last_sticky_meta", meta_out)
                except Exception:
                    pass
        except Exception:
            pass
    return bag


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

    roads = remaining_roads_for_player(
        player, commitment.get("locked_roads_to_build") or [], tip_id=tid
    )
    target = None
    preferred_audit = None
    if way_id is not None:
        preferred_audit = find_audit_for_way(audits, way_id)
    audit_hit, target_hit = find_target_in_audits(audits, tid, preferred_way_id=way_id)
    if target_hit is not None:
        target = target_hit
        fresh = remaining_roads_for_player(
            player, _target_field(target_hit, "roads_to_build", []), tip_id=tid
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
        roads = remaining_roads_for_player(player, prev_roads, tip_id=tid)
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


def _road_on_sticky_settle_path(
    road: Any,
    commitment: Mapping[str, Any],
    player: Any,
) -> bool:
    """True when ``road`` is (was) on the sticky settle route."""
    key = _road_key(road)
    if key is None:
        return False
    raw_roads = list(commitment.get("locked_roads_to_build") or [])
    for edge in _normalize_roads(raw_roads):
        if _road_key(edge) == key:
            return True
    # Also treat as path-related when the new edge touches the sticky settle
    tid = _safe_int(commitment.get("locked_rec_target_id"), None)
    if tid is not None and int(tid) in key:
        return True
    return False


def maybe_force_l2_after_lr_or_component_road(
    game: Any,
    player: Any,
    *,
    road: Any = None,
    length_before: Any = None,
    length_after: Any = None,
    holder_changed: bool = False,
    sticky_risk: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """WP-H: after LR grow / path complete / component road → need_next + L2.

    Dig (White 341→367): building LR road should retarget S@5 → S@44.
    Does not clear sticky here — explore recommit + settle-tip-before-LA does.
    """
    out: Dict[str, Any] = {"ok": True, "forced": False, "reasons": []}
    reasons: List[str] = []
    try:
        lb = int(length_before) if length_before is not None else None
        la = int(length_after) if length_after is not None else None
    except Exception:
        lb = la = None
    if lb is not None and la is not None and la > lb:
        reasons.append("lr_length_up")
    if holder_changed:
        reasons.append("lr_holder_changed")
    sr = dict(sticky_risk or {})
    rem = sr.get("own_dist")
    if rem is None and isinstance(sr.get("sticky_risk_refresh"), Mapping):
        rem = sr["sticky_risk_refresh"].get("own_dist")
    try:
        if rem is not None and int(rem) == 0 and sr.get("applied"):
            reasons.append("sticky_path_complete")
    except Exception:
        pass
    # Road on sticky path that shortened remaining
    try:
        c = get_sticky_commitment(player)
        if isinstance(c, Mapping) and road is not None:
            prev = list(c.get("locked_roads_to_build") or [])
            if prev and _road_on_sticky_settle_path(road, c, player):
                rem2 = remaining_roads_for_player(
                    player, prev, tip_id=c.get("locked_rec_target_id")
                )
                if len(rem2) < len(prev):
                    reasons.append("sticky_path_advanced")
                if not rem2:
                    reasons.append("sticky_path_complete")
    except Exception:
        pass

    if not reasons:
        out["reason"] = "no_trigger"
        return out

    out["reasons"] = reasons
    prefer_lr = bool(holder_changed) or "lr_holder_changed" in reasons
    # WP-H2: gaining public LR must pull Victory-Way toward LR ways (n3d Red).
    if prefer_lr:
        reasons.append("wp_h2_prefer_lr_ways")
        try:
            setattr(player, "prefer_lr_ways", True)
        except Exception:
            pass
        # Invalidate sticky if locked way does not include LR while we hold it
        try:
            c = get_sticky_commitment(player)
            way_has_lr = False
            if isinstance(c, Mapping):
                way_has_lr = bool(
                    c.get("way_lr")
                    or c.get("longest_road")
                    or c.get("locked_way_lr")
                )
            if not way_has_lr:
                # Soft clear — next explore recommits; keep target if possible
                clear_sticky_commitment(player)
                reasons.append("wp_h2_clear_non_lr_sticky")
                out["cleared_non_lr_sticky"] = True
        except Exception:
            pass

    out["reasons"] = reasons
    reason = "flag:lr_or_component_road:" + ",".join(reasons[:3])
    try:
        flag_strategy_recalc(
            player,
            reason,
            detail={
                "road": list(road) if road else None,
                "prefer_lr_ways": bool(prefer_lr),
            },
        )
    except Exception:
        pass
    try:
        setattr(player, "force_strategy_recalc", True)
    except Exception:
        pass
    try:
        from core.strategy_reconsider import set_reconsider_flag

        set_reconsider_flag(player, "need_next_target", reason=reason)
    except Exception:
        pass
    try:
        setattr(
            player,
            "pending_full_resolve",
            {
                "reason": reason,
                "trigger": "wp_h_lr_component_road",
                "detail": {"reasons": reasons, "prefer_lr_ways": bool(prefer_lr)},
                "prefer_lr_ways": bool(prefer_lr),
            },
        )
    except Exception:
        pass
    out["forced"] = True
    out["prefer_lr_ways"] = bool(prefer_lr)
    out["reason"] = reason
    return out


def refresh_sticky_settle_risk_after_own_road(
    game: Any,
    player: Any,
    *,
    road: Any = None,
) -> Dict[str, Any]:
    """Light risk reassess for sticky new_settlement after an own path road.

    No full L2: when the built road advances the sticky settle route, drop owned
    edges from ``locked_roads_to_build`` and recompute race/risk for that target
    only (R10T3 / R9T3 dig: White [31,32] toward S32 ends Red's soft race).

    Updates sticky commitment + strategic_direction risk fields and patches
    cached plan_settles row for Dig/CS without rebuilding the whole catalog.
    """
    out: Dict[str, Any] = {
        "ok": False,
        "applied": False,
        "reason": "no_sticky",
    }
    c = get_sticky_commitment(player)
    if not isinstance(c, Mapping) or not c:
        return out
    kind = str(c.get("locked_target_kind") or "").lower()
    tid = _safe_int(c.get("locked_rec_target_id"), None)
    if tid is None:
        out["reason"] = "no_sticky_target"
        return out
    if kind and ("city" in kind or kind in ("c", "la", "lr")):
        out["reason"] = f"not_settle_kind:{kind}"
        return out
    # Require settle-ish lock (empty kind still ok if roads/target present)
    if kind and not any(x in kind for x in ("settle", "s", "new_settlement", "next_settlement")):
        if not list(c.get("locked_roads_to_build") or []):
            out["reason"] = f"skip_kind:{kind}"
            return out

    prev_roads = list(c.get("locked_roads_to_build") or [])
    if road is not None and prev_roads and not _road_on_sticky_settle_path(road, c, player):
        # Road not on sticky path — still strip owned edges if any
        rem_only = remaining_roads_for_player(player, prev_roads, tip_id=tid)
        if rem_only == prev_roads:
            out["reason"] = "road_not_on_sticky_path"
            return out

    remaining = remaining_roads_for_player(player, prev_roads, tip_id=tid)
    try:
        from core.risk_assessment import (
            enrich_settlement_race_risk_with_eh_memory,
            opponent_settlement_race_risk,
        )

        risk_bag = opponent_settlement_race_risk(game, player, int(tid))
        # EH + RCARD_MEMORY_OPPONENTS for beat-risk vs threats
        risk_bag = enrich_settlement_race_risk_with_eh_memory(
            game,
            player,
            risk_bag,
            target_id=int(tid),
            own_distance_roads=len(remaining),
        )
    except Exception as exc:
        out["reason"] = f"risk_failed:{exc}"
        return out

    risk_level = str(risk_bag.get("risk_level") or "low").lower()
    if risk_level in ("medium",):
        risk_level = "med"
    threats = list(risk_bag.get("threat_opponents") or [])
    # Own remaining distance along sticky path (0 once path edges are owned)
    own_dist = len(remaining)

    new_c = dict(c)
    new_c["locked_roads_to_build"] = list(remaining)
    new_c["risk_level"] = risk_level
    new_c["locked_risk_level"] = risk_level
    new_c["sticky_risk_refresh"] = {
        "target_id": int(tid),
        "own_dist": int(own_dist),
        "risk_level": risk_level,
        "threat_count": len(threats),
        "reasons": list(risk_bag.get("reasons") or [])[:6],
    }
    set_sticky_commitment(player, new_c)

    # Mirror onto strategic_direction for BA / Dig consumers
    try:
        direction = dict(getattr(player, "strategic_direction", None) or {})
        direction["locked_roads_to_build"] = list(remaining)
        direction["roads_to_build"] = list(remaining)
        direction["risk_level"] = risk_level
        direction["locked_risk_level"] = risk_level
        # Patch target_portfolio entry for this settle if present
        port = list(direction.get("target_portfolio") or [])
        patched_port: List[Any] = []
        for t in port:
            if isinstance(t, Mapping):
                td = dict(t)
                t_id = _safe_int(td.get("target_id") or td.get("id"), None)
                if t_id is not None and int(t_id) == int(tid):
                    td["risk_level"] = risk_level
                    td["distance_roads"] = int(own_dist)
                    td["roads_to_build"] = list(remaining)
                    td["threat_opponents"] = threats
                patched_port.append(td)
            else:
                patched_port.append(t)
        if patched_port:
            direction["target_portfolio"] = patched_port
        direction["sticky_risk_refresh"] = dict(new_c["sticky_risk_refresh"])
        setattr(player, "strategic_direction", direction)
    except Exception:
        pass

    # Patch cached plan_settles row for Dig (no full catalog rebuild)
    try:
        from core.strategy_plan_snapshot import (
            _competitor_compact,
            _encode_settle_row,
            parse_plan_settles,
        )

        bag = getattr(player, "last_plan_bag", None) or getattr(game, "last_plan_snapshot", None)
        if isinstance(bag, Mapping):
            bag = dict(bag)
            cs = dict(bag.get("cs") or {})
            settles = parse_plan_settles(cs.get("plan_settles"))
            comp = _competitor_compact(threats)
            updated = False
            new_settles: List[Dict[str, Any]] = []
            for s in settles:
                row = dict(s)
                sid = _safe_int(row.get("id") or row.get("target_id"), None)
                if sid is not None and int(sid) == int(tid):
                    row["dist"] = int(own_dist)
                    row["distance_roads"] = int(own_dist)
                    row["risk"] = risk_level
                    row["risk_level"] = risk_level
                    row["competitors"] = comp
                    row["threats"] = threats
                    updated = True
                new_settles.append(row)
            if updated:
                cs["plan_settles"] = ";".join(_encode_settle_row(s) for s in new_settles) or None
                bag["cs"] = cs
                bag["settles"] = new_settles
                try:
                    setattr(player, "last_plan_bag", bag)
                except Exception:
                    pass
                try:
                    if int(getattr(game, "last_plan_snapshot_player_id", -1) or -1) == int(
                        getattr(player, "id", -2) or -2
                    ):
                        game.last_plan_snapshot = dict(bag)
                except Exception:
                    pass
                # Also stash on direction for CS writers that read preferred
                try:
                    direction = dict(getattr(player, "strategic_direction", None) or {})
                    direction["plan_settles"] = cs.get("plan_settles")
                    setattr(player, "strategic_direction", direction)
                except Exception:
                    pass
    except Exception:
        pass

    out.update(
        {
            "ok": True,
            "applied": True,
            "reason": "sticky_settle_risk_refreshed",
            "target_id": int(tid),
            "own_dist": int(own_dist),
            "risk_level": risk_level,
            "remaining_roads": list(remaining),
            "prev_roads": list(prev_roads),
            "threat_opponents": threats,
        }
    )
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

    # Phase C2 WP-R3: explicit L2 always-best — do not sticky-hold a worse way
    explicit_best = False
    try:
        from core.strategy_explicit_recalc import should_adopt_best_way

        explicit_best = bool(should_adopt_best_way(player))
    except Exception:
        explicit_best = False
    meta["explicit_best_way"] = bool(explicit_best)

    commitment = get_sticky_commitment(player)
    # S19: keep a copy before invalidate clears sticky (for last_sticky_switch)
    prev_commitment_snapshot: Optional[Dict[str, Any]] = (
        dict(commitment) if isinstance(commitment, Mapping) else None
    )

    # WP3: specials-dead episode — clear sticky still locked on dead LA/LR ways
    try:
        from core.specials_dead_episode import (
            commitment_blocked_by_episode,
            is_giveup_escape_enabled,
        )

        if is_giveup_escape_enabled() and commitment is not None:
            blocked, why = commitment_blocked_by_episode(commitment, player)
            if blocked:
                clear_sticky_commitment(player)
                commitment = None
                meta["invalidated"] = True
                meta["invalidate_reason"] = f"specials_dead_episode:{why}"
                meta["specials_dead_gate"] = True
                meta["specials_dead_gate_why"] = why
    except Exception as _sde_gate_exc:
        meta["specials_dead_gate_error"] = str(_sde_gate_exc)

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
            # Phase C2 WP-R3: hard-invalid sticky may latch explicit code 3
            try:
                inv_l = str(inv_reason or "").lower()
                if any(
                    n in inv_l
                    for n in (
                        "occupied",
                        "race_impossible",
                        "route",
                        "infeasible",
                        "hard_invalid",
                        "illegal",
                    )
                ):
                    from core.strategy_explicit_recalc import note_hard_invalid

                    note_hard_invalid(player, reason=str(inv_reason or ""))
            except Exception:
                pass
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
            # Phase C2 WP-R3: adopt L2 best way — skip hold when best ≠ locked
            if explicit_best:
                try:
                    from core.strategy_explicit_recalc import (
                        audit_way_id,
                        find_audit_eta_for_way,
                        record_way_reassess_compare,
                    )

                    locked_w = _safe_int(commitment.get("locked_way_id"), None)
                    best_w = None
                    if audits:
                        best_w = audit_way_id(audits[0])
                    if best_w is None:
                        best_w = _safe_int(
                            direction_out.get("preferred_way_id")
                            or direction_out.get("way_id"),
                            None,
                        )
                    eta_locked = find_audit_eta_for_way(audits, locked_w)
                    eta_best = find_audit_eta_for_way(audits, best_w)
                    switched = (
                        locked_w is not None
                        and best_w is not None
                        and int(locked_w) != int(best_w)
                    )
                    if switched:
                        clear_sticky_commitment(player)
                        commitment = None
                        meta["invalidated"] = True
                        meta["invalidate_reason"] = "explicit_142_recalc_best_way"
                        meta["explicit_switch"] = True
                        # fall through to re-commit from direction (already best)
                    else:
                        # same way — normal hold path below
                        pass
                    try:
                        rt = getattr(player, "explicit_recalc_runtime", None) or {}
                        trig = str(rt.get("session_reason") or "explicit_142_recalc")
                    except Exception:
                        trig = "explicit_142_recalc"
                    record_way_reassess_compare(
                        player,
                        game,
                        locked_way=locked_w,
                        best_alt_way=best_w,
                        eta_locked=eta_locked,
                        eta_alt=eta_best,
                        switched=bool(switched),
                        switch_reason=(
                            "switched_best"
                            if switched
                            else ("same_way" if best_w is not None else "no_alt")
                        ),
                        trigger=trig,
                    )
                    if not switched and commitment is not None:
                        # continue into normal hold
                        pass
                    elif switched:
                        # skip hold / offway; fall through to commit
                        pass
                except Exception as exp_exc:
                    meta["explicit_best_error"] = str(exp_exc)

            # S14-2: off-way opportunity with lower win-ETA → force one full re-solve
            # (skip when we already cleared sticky for explicit best switch)
            if commitment is not None:
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
                            {
                                "reason": off_reason,
                                "trigger": "s14_2",
                                "detail": dict(off_meta or {}),
                            },
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
                        if lr_meta.get("invalidated") and not get_stored_lr_project(
                            player, game
                        ):
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
                            commitment["opp_structures"] = list(
                                snap.get("opp_structures") or []
                            )
                            commitment["opp_roads_near"] = list(
                                snap.get("opp_roads_near") or []
                            )
                        # S13 refresh multi-target list on hold
                        try:
                            from core.strategy_target_format import (
                                collect_display_targets,
                                format_targets_line,
                            )

                            commitment["display_targets"] = collect_display_targets(
                                direction_out, player=player
                            )
                            direction_out["display_targets"] = list(
                                commitment["display_targets"]
                            )
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
                            direction_out["dense_pack"] = bool(
                                focus_info.get("dense_pack")
                            )
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
                        meta["sticky_hold_reason"] = "sticky_hold"
                        meta["locked_way_id"] = commitment.get("locked_way_id")
                        meta["locked_rec_target_id"] = commitment.get(
                            "locked_rec_target_id"
                        )
                        # WP-DIG2: record whether locked way matches last L2 winner
                        try:
                            dossier = getattr(player, "last_l2_way_dossier", None) or {}
                            winner = dossier.get("winner") if isinstance(dossier, Mapping) else None
                            locked_w = commitment.get("locked_way_id")
                            if winner is not None and locked_w is not None:
                                setattr(
                                    player,
                                    "l2_applied",
                                    int(winner) == int(locked_w),
                                )
                        except Exception:
                            pass
                        meta["locked_roads_to_build"] = list(
                            commitment.get("locked_roads_to_build") or []
                        )
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
                        publish_last_sticky_cs_meta(
                            player,
                            game,
                            meta,
                            prev_commitment=prev_commitment_snapshot,
                        )
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
        publish_last_sticky_cs_meta(
            player, game, meta, prev_commitment=prev_commitment_snapshot
        )
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
        publish_last_sticky_cs_meta(
            player, game, meta, prev_commitment=prev_commitment_snapshot
        )
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

    # WP3: do not sticky-commit a way that still needs a dead special
    try:
        from core.specials_dead_episode import (
            direction_blocked_by_episode,
            is_giveup_escape_enabled,
        )

        if is_giveup_escape_enabled():
            blocked_dir, why_dir = direction_blocked_by_episode(direction_out, player)
            if blocked_dir:
                # Prefer first non-blocked audit as commit source
                try:
                    from core.specials_dead_episode import (
                        filter_audits_for_specials_dead,
                        get_specials_dead_episode,
                    )
                    from core.ai_way_portfolio import board_audit_to_strategic_direction

                    ep = get_specials_dead_episode(player)
                    filtered, fmeta = filter_audits_for_specials_dead(
                        audits, episode=ep, player=player
                    )
                    if filtered and fmeta.get("mode") == "hard_filter":
                        alt_dir = board_audit_to_strategic_direction(
                            filtered[0],
                            abstract_preferred=direction_out,
                            override_applied=True,
                            override_reason="specials_dead_sticky_gate",
                        )
                        direction_out = dict(alt_dir)
                        direction_out["preference_source"] = (
                            str(direction_out.get("preference_source") or "")
                            + "+specials_dead_sticky_gate"
                        ).lstrip("+")
                        meta["specials_dead_sticky_rewrote"] = True
                        meta["specials_dead_sticky_to_way"] = direction_out.get(
                            "preferred_way_id"
                        )
                    else:
                        meta["specials_dead_block_commit"] = True
                        meta["specials_dead_block_why"] = why_dir
                        # Leave unlocked rather than re-lock dead special
                        new_c = None
                        meta["reason"] = f"specials_dead_block_commit:{why_dir}"
                        direction_out["sticky_meta"] = {
                            "held": False,
                            "committed": False,
                            "specials_dead_gate": True,
                            "reason": meta["reason"],
                        }
                        publish_last_sticky_cs_meta(
                            player,
                            game,
                            meta,
                            prev_commitment=prev_commitment_snapshot,
                        )
                        return direction_out, meta
                except Exception as _rew_exc:
                    meta["specials_dead_rewrite_error"] = str(_rew_exc)
                    meta["specials_dead_block_commit"] = True
                    clear_sticky_commitment(player)
                    new_c = None
                    meta["reason"] = f"specials_dead_block_commit:{why_dir}"
                    direction_out["sticky_meta"] = {
                        "held": False,
                        "committed": False,
                        "specials_dead_gate": True,
                        "reason": meta["reason"],
                    }
                    publish_last_sticky_cs_meta(
                        player,
                        game,
                        meta,
                        prev_commitment=prev_commitment_snapshot,
                    )
                    return direction_out, meta
    except Exception as _gate_exc:
        meta["specials_dead_commit_gate_error"] = str(_gate_exc)

    # WP-STICKY1: soft same-way rerank must not abandon an invested Fastest settle
    # (n3d Red 39→43 / g002 24→31) unless the new tip clearly improves ETA / legality.
    try:
        direction_out, sticky1_meta = maybe_preserve_prev_settle_on_soft_rerank(
            direction_out,
            prev_commitment_snapshot,
            game,
            player,
            audits,
            invalidate_reason=str(meta.get("invalidate_reason") or ""),
        )
        if sticky1_meta:
            meta["wp_sticky1"] = dict(sticky1_meta)
    except Exception as _s1_exc:
        meta["wp_sticky1_error"] = str(_s1_exc)

    # WP-STICKY2: way_switch that worsens next-settle ETA without race/deny → keep prior
    try:
        direction_out, sticky2_meta = maybe_block_way_switch_worse_settle_eta(
            direction_out,
            prev_commitment_snapshot,
            game,
            player,
            audits,
            invalidate_reason=str(meta.get("invalidate_reason") or ""),
        )
        if sticky2_meta:
            meta["wp_sticky2"] = dict(sticky2_meta)
            if sticky2_meta.get("blocked"):
                meta["sticky_hold_reason"] = "wp_sticky2_worse_settle_eta"
    except Exception as _s2_exc:
        meta["wp_sticky2_error"] = str(_s2_exc)

    # Commit from current direction (fresh, force, or post-invalidate with consume)
    new_c = commit_from_direction(direction_out, game, player)
    # Post-structure: if no tid (city-dev / empty portfolio), lock best settle tip
    # before falling through to LA-only sticky (S44 vs 10×DC dig).
    if new_c is None:
        try:
            tip_c = try_commit_settle_tip_before_specials(
                direction_out, game, player, audits
            )
            if tip_c is not None:
                new_c = tip_c
                meta["settle_tip_before_specials"] = True
                meta["settle_tip_id"] = tip_c.get("locked_rec_target_id")
                direction_out["recommendation_target_id"] = tip_c.get(
                    "locked_rec_target_id"
                )
                direction_out["settlement_target_id"] = tip_c.get("locked_rec_target_id")
                direction_out["supporting_action_type"] = "new_settlement"
                if tip_c.get("locked_roads_to_build"):
                    direction_out["roads_to_build"] = list(
                        tip_c.get("locked_roads_to_build") or []
                    )
        except Exception as _tip_exc:
            meta["settle_tip_before_specials_error"] = str(_tip_exc)
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

    # WP3: do not re-arm LR project while kill_lr episode is active
    try:
        from core.specials_dead_episode import episode_kill_flags, is_giveup_escape_enabled

        if is_giveup_escape_enabled():
            _kla, klr = episode_kill_flags(player)
            if klr:
                try:
                    from core.ai_lr_project import clear_lr_project_from_sticky

                    clear_lr_project_from_sticky(player, game)
                except Exception:
                    pass
                try:
                    direction_out.pop("lr_project", None)
                    direction_out["longest_road"] = False
                except Exception:
                    pass
                meta["lr_suppressed_specials_dead"] = True
    except Exception:
        pass

    # S-LA-A: arm LA progress alongside structure / LR
    la_meta: Dict[str, Any] = {}
    try:
        from core.ai_la_progress import ensure_la_progress_sticky

        la_meta = ensure_la_progress_sticky(game, player)
        meta["la"] = dict(la_meta)
    except Exception as la_exc:
        meta["la_error"] = str(la_exc)
        la_meta = {}

    # WP3: suppress LA progress while kill_la episode active
    try:
        from core.specials_dead_episode import episode_kill_flags, is_giveup_escape_enabled

        if is_giveup_escape_enabled():
            kla, _klr = episode_kill_flags(player)
            if kla:
                try:
                    from core.ai_la_progress import clear_la_progress_from_sticky

                    clear_la_progress_from_sticky(player, game)
                except Exception:
                    pass
                try:
                    player.la_progress = None
                except Exception:
                    pass
                try:
                    direction_out["biggest_army"] = False
                    direction_out["largest_army"] = False
                except Exception:
                    pass
                meta["la_suppressed_specials_dead"] = True
    except Exception:
        pass

    # S4: suppress LR/LA projects for any ignored_components (episode + expansion + stamp)
    try:
        from core.partial_way_salvage import (
            apply_s4_project_suppress,
            stamp_commitment_partial_plan,
        )

        if not isinstance(direction_out, dict):
            direction_out = dict(direction_out or {})
        s4_meta = apply_s4_project_suppress(
            player, game, direction_out, meta
        )
        meta["s4"] = dict(s4_meta)
    except Exception as _s4_exc:
        meta["s4_error"] = str(_s4_exc)

    if new_c is not None:
        # Merge any LR project / LA progress into the new structure commitment
        try:
            from core.ai_lr_project import get_stored_lr_project

            lr_now = get_stored_lr_project(player, game)
            if lr_now and not meta.get("lr_suppressed_specials_dead"):
                new_c["lr_project"] = lr_now
                new_c["sticky_version"] = max(3, int(new_c.get("sticky_version") or 0) or 3)
            elif meta.get("lr_suppressed_specials_dead"):
                new_c.pop("lr_project", None)
        except Exception:
            pass
        try:
            from core.ai_la_progress import get_stored_la_progress

            la_now = get_stored_la_progress(player, game)
            if la_now and not meta.get("la_suppressed_specials_dead"):
                new_c["la_progress"] = la_now
                new_c["sticky_version"] = max(3, int(new_c.get("sticky_version") or 0) or 3)
            elif meta.get("la_suppressed_specials_dead"):
                new_c.pop("la_progress", None)
        except Exception:
            pass
        # S4: stamp partial_plan / ignored_components on committed sticky
        try:
            from core.partial_way_salvage import stamp_commitment_partial_plan

            stamp_commitment_partial_plan(new_c, direction_out, player, game)
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
        # Phase C2 WP-R3: track distinct ways used this game
        try:
            from core.strategy_explicit_recalc import track_way_used

            prev_w = None
            if isinstance(prev_for_switch, Mapping):
                prev_w = _safe_int(prev_for_switch.get("locked_way_id"), None)
            new_w = _safe_int(new_c.get("locked_way_id"), None)
            switched_way = (
                prev_w is not None and new_w is not None and int(prev_w) != int(new_w)
            )
            track_way_used(
                player,
                new_w,
                switched=bool(switched_way) if prev_w is not None else False,
            )
        except Exception:
            pass
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
        if meta.get("explicit_switch"):
            meta["reason"] = "explicit_142_recalc_best_way"
        elif meta["invalidated"] and meta.get("flag_consumed"):
            meta["reason"] = "sticky_recommit_after_flag"
        elif meta["invalidated"]:
            meta["reason"] = "sticky_recommit_after_invalidate"
        else:
            meta["reason"] = "sticky_commit"
        if meta.get("wp_sticky2", {}).get("blocked"):
            meta["sticky_hold_reason"] = "wp_sticky2_worse_settle_eta"
        else:
            meta["sticky_hold_reason"] = str(meta.get("reason") or "")
        meta["locked_way_id"] = new_c.get("locked_way_id")
        meta["locked_rec_target_id"] = new_c.get("locked_rec_target_id")
        meta["locked_roads_to_build"] = list(new_c.get("locked_roads_to_build") or [])
        direction_out["locked_way_id"] = new_c.get("locked_way_id")
        direction_out["locked_rec_target_id"] = new_c.get("locked_rec_target_id")
        direction_out["locked_roads_to_build"] = list(new_c.get("locked_roads_to_build") or [])
        try:
            dossier = getattr(player, "last_l2_way_dossier", None) or {}
            winner = dossier.get("winner") if isinstance(dossier, Mapping) else None
            locked_w = new_c.get("locked_way_id")
            if winner is not None and locked_w is not None:
                setattr(player, "l2_applied", int(winner) == int(locked_w))
        except Exception:
            pass
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
                publish_last_sticky_cs_meta(
                    player, game, meta, prev_commitment=prev_commitment_snapshot
                )
                return direction_out, meta
        except Exception:
            pass
        meta["reason"] = "no_rec_target_to_lock"
        if meta["invalidated"]:
            meta["reason"] = "invalidated_no_new_target"
        if consume_flag:
            consume_strategy_recalc_flag(player)
            meta["flag_consumed"] = True
    publish_last_sticky_cs_meta(
        player, game, meta, prev_commitment=prev_commitment_snapshot
    )
    return direction_out, meta
