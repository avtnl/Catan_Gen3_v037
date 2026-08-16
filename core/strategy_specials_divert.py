"""S5.5 specials divert: assess (A) + pick (B) + own-turn cadence (C).

S5.5-A: board snapshot + enriched LA/LR hopeless/unstoppable assess.
S5.5-B: filter 142 without dead specials + win-ETA/realism pick + sticky clear.
S5.5-C: once-per-(round,turn,player) latch, PLAN/Phase0 dig-in, perf span.

Product parent: ``docs/s55_specials_divert_implementation_plan.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

# Align with S5b defaults (may re-export for dig-in)
LA_GAP_KILL: int = 3
LR_GAP_KILL: int = 4
DCARD_STACK_TINY: int = 2
LR_MIN_LENGTH: int = 5
MAX_RESIDUAL_SAMPLE: int = 40
MAX_LR_CLAIM_SCAN: int = 12


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _player_id(player: Any) -> int:
    return _safe_int(getattr(player, "id", None), 0)


def _army_size(player: Any) -> int:
    try:
        return max(0, int(getattr(player, "size_largest_army", 0) or 0))
    except Exception:
        return 0


def _holds_la(player: Any, game: Any = None) -> bool:
    if bool(getattr(player, "largest_army_tf", False) or getattr(player, "biggest_army_tf", False)):
        return True
    if game is None:
        return False
    holder = getattr(game, "largest_army_player", None)
    if holder is None:
        return False
    try:
        return int(getattr(holder, "id", -1)) == int(getattr(player, "id", -2))
    except Exception:
        return holder is player


def _holds_lr(player: Any, game: Any = None) -> bool:
    if bool(getattr(player, "longest_route_tf", False) or getattr(player, "longest_road_tf", False)):
        return True
    if game is None:
        return False
    holder = getattr(game, "longest_road_player", None)
    if holder is None:
        return False
    try:
        return int(getattr(holder, "id", -1)) == int(getattr(player, "id", -2))
    except Exception:
        return holder is player


def _dcard_stack_remaining(game: Any) -> Optional[int]:
    if game is None:
        return None
    for attr in ("dcards_stack", "development_card_deck", "dcard_deck"):
        stack = getattr(game, attr, None)
        if isinstance(stack, (list, tuple)):
            return len(stack)
    try:
        n = getattr(game, "number_of_dcards_left", None)
        if n is None:
            n = getattr(game, "development_cards_remaining", None)
        if n is not None:
            return max(0, int(n))
    except Exception:
        pass
    return None


def _dcard_row_counts(player: Any, card_type: str = "knight") -> Tuple[int, int, int]:
    """(new, playable, revealed/played) for one card type."""
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
    try:
        n = sum(1 for c in (getattr(player, "development_cards", []) or []) if str(c) == ct)
        return (0, n, 0)
    except Exception:
        return (0, 0, 0)


def _road_key(raw: Any) -> Optional[Tuple[int, int]]:
    try:
        from core.outlook_logic import _normalise_road_key

        key = _normalise_road_key(raw)
        if isinstance(key, tuple) and len(key) == 2 and key[0] != key[1]:
            return (int(key[0]), int(key[1]))
    except Exception:
        pass
    try:
        if isinstance(raw, Mapping):
            for k in ("road_id", "road", "edge", "id"):
                if k in raw:
                    return _road_key(raw.get(k))
            return None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            a, b = int(raw[0]), int(raw[1])
            if a == b:
                return None
            return (a, b) if a < b else (b, a)
    except Exception:
        return None
    return None


def _owned_road_keys(game: Any, player: Any) -> Set[Tuple[int, int]]:
    out: Set[Tuple[int, int]] = set()
    try:
        from core.outlook_logic import player_owned_road_keys

        for e in player_owned_road_keys(game, player) or []:
            key = _road_key(e)
            if key:
                out.add(key)
    except Exception:
        pass
    if not out:
        for raw in list(getattr(player, "roads", None) or []):
            key = _road_key(raw)
            if key:
                out.add(key)
    return out


def _road_length(game: Any, player: Any) -> int:
    stored = max(0, _safe_int(getattr(player, "size_longest_route", 0), 0))
    engine = 0
    try:
        from core.longest_road import compute_longest_road_for_player

        res = compute_longest_road_for_player(game, player)
        if isinstance(res, Mapping):
            engine = max(0, int(res.get("length", res.get("size", 0)) or 0))
        else:
            engine = max(0, int(getattr(res, "length", 0) or 0))
    except Exception:
        engine = 0
    # Prefer max so unit stubs with size_longest_route still work when
    # continuous engine under-counts without a full board.
    return max(stored, engine)


def residual_growth_cap(
    game: Any,
    player: Any,
    *,
    max_sample: int = MAX_RESIDUAL_SAMPLE,
) -> int:
    """Coarse count of empty board edges attached to own road graph.

    Does not model multi-opponent mutual blocks (S5.5 v1).
    """
    owned = _owned_road_keys(game, player)
    if not owned:
        # No roads: any single empty edge touching a settlement counts as 1 seed if found
        nodes: Set[int] = set()
        for sid in list(getattr(player, "settlements", None) or []) + list(
            getattr(player, "cities", None) or []
        ):
            try:
                nodes.add(int(sid))
            except Exception:
                continue
    else:
        nodes = set()
        for a, b in owned:
            nodes.add(a)
            nodes.add(b)

    if not nodes:
        return 0

    # Occupied edges by anyone
    occupied: Set[Tuple[int, int]] = set()
    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        occupied |= _owned_road_keys(game, p)

    count = 0
    checked = 0
    board = getattr(game, "board", None)

    # Prefer board.roads (empty = no owner)
    roads = list(getattr(board, "roads", None) or []) if board is not None else []
    for road in roads:
        if checked >= max_sample and count > 0:
            break
        try:
            rid = getattr(road, "id", None) or road
            key = _road_key(rid)
            if not key:
                continue
            checked += 1
            if key in occupied:
                continue
            if key[0] in nodes or key[1] in nodes:
                # Skip pure water if flagged
                if bool(getattr(road, "is_water", False)):
                    continue
                count += 1
        except Exception:
            continue

    # Fallback: board.edges list of dicts
    if count == 0 and board is not None:
        for edge in list(getattr(board, "edges", None) or [])[: max_sample * 2]:
            try:
                if isinstance(edge, Mapping):
                    key = _road_key(edge.get("id") or edge.get("nodes") or edge)
                else:
                    key = _road_key(edge)
                if not key or key in occupied:
                    continue
                if key[0] in nodes or key[1] in nodes:
                    count += 1
            except Exception:
                continue

    # Last resort: inject residual from direction/scan candidates touching nodes
    if count == 0:
        try:
            from core.ai_road_planner import _collect_lr_edge_candidates

            for raw in list(_collect_lr_edge_candidates(game, player) or [])[:max_sample]:
                key = _road_key(raw)
                if key and key not in occupied and (key[0] in nodes or key[1] in nodes):
                    count += 1
        except Exception:
            pass

    return int(count)


def collect_specials_board_snapshot(game: Any, player: Any) -> Dict[str, Any]:
    """Per-player army / LR length / residual + stack (dig-in + assess input)."""
    pid = _player_id(player)
    players_meta: List[Dict[str, Any]] = []
    armies: Dict[int, int] = {}
    lengths: Dict[int, int] = {}
    residuals: Dict[int, int] = {}

    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        opid = _player_id(p)
        army = _army_size(p)
        length = _road_length(game, p)
        res_cap = residual_growth_cap(game, p)
        new_k, play_k, rev_k = _dcard_row_counts(p, "knight")
        try:
            dcard_hand = len(list(getattr(p, "development_cards", None) or []))
        except Exception:
            dcard_hand = 0
        armies[opid] = army
        lengths[opid] = length
        residuals[opid] = res_cap
        players_meta.append(
            {
                "player_id": opid,
                "is_human": bool(getattr(p, "is_human", False)),
                "army": army,
                "holds_la": _holds_la(p, game),
                "lr_length": length,
                "holds_lr": _holds_lr(p, game),
                "residual_growth_cap": res_cap,
                "knight_new": new_k,
                "knight_playable": play_k,
                "knight_revealed_or_played": rev_k,
                "dcard_hand_count": dcard_hand,
                "roads_owned": len(_owned_road_keys(game, p)),
            }
        )

    own_new, own_play, own_rev = _dcard_row_counts(player, "knight")
    max_opp_army = max((a for i, a in armies.items() if i != pid), default=0)
    max_opp_len = max((L for i, L in lengths.items() if i != pid), default=0)

    return {
        "s55": True,
        "focus_player_id": pid,
        "stack_remaining": _dcard_stack_remaining(game),
        "players": players_meta,
        "armies": armies,
        "lr_lengths": lengths,
        "residual_caps": residuals,
        "own_army": armies.get(pid, _army_size(player)),
        "max_opp_army": max_opp_army,
        "own_lr_length": lengths.get(pid, _road_length(game, player)),
        "max_opp_lr_length": max_opp_len,
        "own_residual_growth_cap": residuals.get(pid, residual_growth_cap(game, player)),
        "own_knight_playable": own_play,
        "own_knight_new": own_new,
        "own_would_take_la": bool(
            own_play >= 1
            and _army_size(player) + 1 >= 3
            and _army_size(player) + 1 > max_opp_army
        ),
    }


def _direction_of(player: Any, direction: Any = None) -> Dict[str, Any]:
    if isinstance(direction, Mapping) and direction:
        return dict(direction)
    raw = getattr(player, "strategic_direction", None) if player is not None else None
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def assess_la_unstoppable(
    game: Any,
    player: Any,
    direction: Optional[Mapping[str, Any]] = None,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    gap_kill: int = LA_GAP_KILL,
    require_way_needs_la: bool = True,
) -> Dict[str, Any]:
    """Enriched LA hopeless / unstoppable_opp assessment (S5.5-A)."""
    d = _direction_of(player, direction)
    snap = dict(snapshot or collect_specials_board_snapshot(game, player))
    meta: Dict[str, Any] = {
        "kind": "LA",
        "s55": True,
        "hopeless": False,
        "unstoppable_opp": False,
        "still_live": True,
        "catch_up_impossible": False,
        "reason": "",
        "needs_la": False,
        "gap": 0,
        "own_army": int(snap.get("own_army") or 0),
        "max_opp_army": int(snap.get("max_opp_army") or 0),
        "stack_remaining": snap.get("stack_remaining"),
        "playable_knights": int(snap.get("own_knight_playable") or 0),
        "would_take_now": bool(snap.get("own_would_take_la")),
    }

    needs = False
    try:
        from core.strategy_way_kill import way_needs_largest_army

        needs = bool(way_needs_largest_army(d))
    except Exception:
        needs = bool(d.get("biggest_army") or d.get("largest_army"))
    meta["needs_la"] = needs
    if require_way_needs_la and not needs:
        meta["reason"] = "way_does_not_need_LA"
        meta["still_live"] = False
        return meta

    if _holds_la(player, game) and meta["own_army"] > meta["max_opp_army"]:
        meta["reason"] = "holding_LA_lead"
        meta["still_live"] = True
        return meta

    own = meta["own_army"]
    best_opp = meta["max_opp_army"]
    gap = max(0, best_opp - own)
    meta["gap"] = gap
    stack = meta["stack_remaining"]
    playable = meta["playable_knights"]
    new_k = int(snap.get("own_knight_new") or 0)

    # Optimistic catch-up to sole lead (≥3 and > opp)
    target = max(3, best_opp + 1)
    need_knights = max(0, target - own)
    banked = playable + new_k
    stack_knights_est = 0
    if stack is not None:
        stack_knights_est = max(0, min(int(stack) // 4, 3))  # mixed deck bound
    optimistic = banked + stack_knights_est
    meta["knights_needed"] = need_knights
    meta["optimistic_extra_knights"] = optimistic

    if meta["would_take_now"] or (playable >= 1 and own + 1 >= target):
        meta["reason"] = "LA_can_take_soon"
        return meta

    # S5b-compatible gap kill + richer unstoppable
    if gap >= int(gap_kill) and optimistic < need_knights:
        meta["hopeless"] = True
        meta["catch_up_impossible"] = True
        meta["still_live"] = False
        meta["reason"] = (
            f"s55: LA hopeless (gap={gap}, need={need_knights}, "
            f"optimistic+={optimistic}, stack={stack})"
        )
        if best_opp >= 3 and _opp_holds_la(game, best_opp):
            meta["unstoppable_opp"] = True
        return meta

    if (
        stack is not None
        and int(stack) <= int(DCARD_STACK_TINY)
        and gap >= 1
        and optimistic < need_knights
    ):
        meta["hopeless"] = True
        meta["unstoppable_opp"] = best_opp >= 3
        meta["catch_up_impossible"] = True
        meta["still_live"] = False
        meta["reason"] = (
            f"s55: LA unstoppable/stack_tiny (stack={stack}, gap={gap}, "
            f"own={own}, opp={best_opp})"
        )
        return meta

    # Opp already has LA and we cannot catch with remaining optimism
    if best_opp >= 3 and gap >= 2 and optimistic < need_knights:
        meta["unstoppable_opp"] = True
        meta["hopeless"] = gap >= int(gap_kill)
        meta["catch_up_impossible"] = meta["hopeless"]
        meta["still_live"] = not meta["hopeless"]
        meta["reason"] = (
            f"s55: LA opp entrenched (opp={best_opp}, own={own}, opt+={optimistic})"
        )
        return meta

    meta["reason"] = "LA_still_plausible"
    return meta


def _opp_holds_la(game: Any, best_opp_army: int) -> bool:
    holder = getattr(game, "largest_army_player", None)
    if holder is not None and _army_size(holder) >= 3:
        return True
    return best_opp_army >= 3


def assess_lr_unstoppable(
    game: Any,
    player: Any,
    direction: Optional[Mapping[str, Any]] = None,
    *,
    snapshot: Optional[Mapping[str, Any]] = None,
    gap_kill: int = LR_GAP_KILL,
    require_way_needs_lr: bool = True,
) -> Dict[str, Any]:
    """Enriched LR hopeless / unstoppable_opp assessment (S5.5-A)."""
    d = _direction_of(player, direction)
    snap = dict(snapshot or collect_specials_board_snapshot(game, player))
    own = int(snap.get("own_lr_length") or 0)
    best_opp = int(snap.get("max_opp_lr_length") or 0)
    residual = int(snap.get("own_residual_growth_cap") or 0)
    meta: Dict[str, Any] = {
        "kind": "LR",
        "s55": True,
        "hopeless": False,
        "unstoppable_opp": False,
        "still_live": True,
        "catch_up_impossible": False,
        "reason": "",
        "needs_lr": False,
        "gap": max(0, best_opp - own),
        "own_len": own,
        "max_opp_len": best_opp,
        "residual_growth_cap": residual,
        "live_claim": False,
        "claim_window": False,
    }

    needs = False
    try:
        from core.strategy_way_kill import way_needs_longest_road

        needs = bool(way_needs_longest_road(d))
    except Exception:
        tags = " ".join(str(t).lower() for t in list(d.get("tags") or []))
        needs = bool(d.get("longest_road") or ("longest" in tags and "road" in tags))
    meta["needs_lr"] = needs
    if require_way_needs_lr and not needs:
        meta["reason"] = "way_does_not_need_LR"
        meta["still_live"] = False
        return meta

    if _holds_lr(player, game) and own > best_opp:
        meta["reason"] = "holding_LR_lead"
        return meta

    live_claim = False
    try:
        from core.ai_road_planner import ai_road_longest_road_exception_active

        live_claim = bool(ai_road_longest_road_exception_active(game, player))
    except Exception:
        live_claim = False
    meta["live_claim"] = live_claim

    # Claim window: within a few edges of min length / steal
    need_to_claim = max(0, LR_MIN_LENGTH - own)
    if best_opp >= LR_MIN_LENGTH:
        need_to_pass = max(0, best_opp + 1 - own)
    else:
        need_to_pass = need_to_claim
    meta["edges_needed_est"] = need_to_pass
    meta["claim_window"] = need_to_pass <= 2 or live_claim

    if live_claim or (need_to_pass <= 2 and residual >= need_to_pass):
        meta["reason"] = "LR_claim_window_live"
        return meta

    gap = meta["gap"]
    if gap >= int(gap_kill) and residual < need_to_pass and not live_claim:
        meta["hopeless"] = True
        meta["catch_up_impossible"] = True
        meta["still_live"] = False
        meta["unstoppable_opp"] = best_opp >= LR_MIN_LENGTH
        meta["reason"] = (
            f"s55: LR hopeless (gap={gap}, own={own}, opp={best_opp}, "
            f"residual={residual}, need={need_to_pass})"
        )
        return meta

    if (
        best_opp >= LR_MIN_LENGTH
        and residual < need_to_pass
        and gap >= 2
        and not live_claim
    ):
        meta["unstoppable_opp"] = True
        meta["hopeless"] = gap >= int(gap_kill)
        meta["catch_up_impossible"] = meta["hopeless"]
        meta["still_live"] = not meta["hopeless"]
        meta["reason"] = (
            f"s55: LR opp entrenched (opp={best_opp}, residual={residual}, need={need_to_pass})"
        )
        return meta

    meta["reason"] = "LR_still_plausible"
    return meta


def assess_specials_for_player(
    game: Any,
    player: Any,
    direction: Optional[Mapping[str, Any]] = None,
    *,
    store: bool = True,
) -> Dict[str, Any]:
    """Full S5.5-A package: snapshot + LA + LR assess; optional store on player/game."""
    d = _direction_of(player, direction)
    snap = collect_specials_board_snapshot(game, player)
    la = assess_la_unstoppable(game, player, d, snapshot=snap)
    lr = assess_lr_unstoppable(game, player, d, snapshot=snap)

    # Latch awareness (anti-thrash dig-in)
    latched = False
    latch = getattr(player, "way_kill_latch", None)
    if isinstance(latch, Mapping) and latch.get("kind") in {"LA", "LR"}:
        latched = True

    meta = {
        "s55": True,
        "slice": "A",
        "snapshot": snap,
        "la": la,
        "lr": lr,
        "kill_la_recommended": bool(la.get("hopeless") or la.get("unstoppable_opp")),
        "kill_lr_recommended": bool(lr.get("hopeless") or lr.get("unstoppable_opp")),
        "latched_s5b": latched,
        "reason": "; ".join(
            x
            for x in (str(la.get("reason") or ""), str(lr.get("reason") or ""))
            if x
        ),
    }
    if store and player is not None:
        try:
            setattr(player, "last_specials_assess", dict(meta))
        except Exception:
            pass
        # Feed S-LA dig-in flags
        try:
            prog = getattr(player, "la_progress", None)
            if isinstance(prog, dict):
                prog = dict(prog)
                prog["catch_up_impossible"] = bool(la.get("catch_up_impossible"))
                prog["unstoppable_opp"] = bool(la.get("unstoppable_opp"))
                setattr(player, "la_progress", prog)
        except Exception:
            pass
    if store and game is not None:
        try:
            setattr(game, "last_specials_assess", dict(meta))
        except Exception:
            pass
    return meta


def format_specials_assess_dbg(meta: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(meta, Mapping) or not meta:
        return "s55: n/a"
    parts = []
    la = meta.get("la") if isinstance(meta.get("la"), Mapping) else {}
    lr = meta.get("lr") if isinstance(meta.get("lr"), Mapping) else {}
    if la.get("hopeless") or la.get("unstoppable_opp"):
        parts.append(str(la.get("reason") or "LA dead"))
    if lr.get("hopeless") or lr.get("unstoppable_opp"):
        parts.append(str(lr.get("reason") or "LR dead"))
    if not parts:
        return "s55: specials live"
    text = " | ".join(parts)
    return text if len(text) <= 72 else text[:69] + "..."


# ---------------------------------------------------------------------------
# S5.5-B: filter ways without dead specials + win-ETA / realism pick
# ---------------------------------------------------------------------------

REALISM_REJECT_THRESHOLD: float = 12.0
REALISM_ETA_WEIGHT: float = 0.5
# Access pips below this count as "poor" for a resource
ACCESS_POOR_PIPS: float = 1.5


def _audit_get(audit: Any, key: str, default: Any = None) -> Any:
    if isinstance(audit, Mapping):
        return audit.get(key, default)
    return getattr(audit, key, default)


def _way_id_of(audit_or_dir: Any) -> Optional[int]:
    try:
        if isinstance(audit_or_dir, Mapping):
            for k in ("way_id", "preferred_way_id", "locked_way_id"):
                if audit_or_dir.get(k) is not None and audit_or_dir.get(k) != "":
                    return int(float(audit_or_dir.get(k)))
        else:
            wid = getattr(audit_or_dir, "way_id", None)
            if wid is not None and wid != "":
                return int(float(wid))
    except Exception:
        return None
    return None


def _requirements_of(audit_or_dir: Any) -> Dict[str, Any]:
    if isinstance(audit_or_dir, Mapping):
        req = audit_or_dir.get("requirements") or audit_or_dir.get("way_requirements") or {}
        if isinstance(req, Mapping) and req:
            return dict(req)
        rem = audit_or_dir.get("remaining") if isinstance(audit_or_dir.get("remaining"), Mapping) else {}
        return {
            "required_cities": rem.get("cities", 0),
            "required_new_intersections": rem.get("new_settlements", 0),
            "required_dcards": rem.get("development_cards", 0),
            "required_roads_min": rem.get("roads", 0),
            "biggest_army": audit_or_dir.get("biggest_army") or audit_or_dir.get("largest_army"),
            "longest_road": audit_or_dir.get("longest_road"),
            "victory_point_cards": audit_or_dir.get("victory_point_cards"),
        }
    req = getattr(audit_or_dir, "requirements", None) or {}
    return dict(req) if isinstance(req, Mapping) else {}


def audit_or_dir_needs_la(audit_or_dir: Any) -> bool:
    req = _requirements_of(audit_or_dir)
    if bool(req.get("biggest_army") or req.get("largest_army")):
        return True
    try:
        from core.strategy_way_kill import way_needs_largest_army

        if isinstance(audit_or_dir, Mapping):
            return way_needs_largest_army(audit_or_dir)
        # synthetic direction from audit
        d = {
            "biggest_army": req.get("biggest_army"),
            "largest_army": req.get("largest_army"),
            "way_requirements": req,
            "tags": list(getattr(audit_or_dir, "tags", None) or []),
        }
        return way_needs_largest_army(d)
    except Exception:
        return False


def audit_or_dir_needs_lr(audit_or_dir: Any) -> bool:
    req = _requirements_of(audit_or_dir)
    if bool(req.get("longest_road") or req.get("longest_route")):
        return True
    try:
        from core.strategy_way_kill import way_needs_longest_road

        if isinstance(audit_or_dir, Mapping):
            return way_needs_longest_road(audit_or_dir)
        d = {
            "longest_road": req.get("longest_road"),
            "way_requirements": req,
            "tags": list(getattr(audit_or_dir, "tags", None) or []),
        }
        return way_needs_longest_road(d)
    except Exception:
        return False


def filter_ways_without_specials(
    audits: Sequence[Any],
    *,
    kill_la: bool = False,
    kill_lr: bool = False,
) -> List[Any]:
    """Keep audits that do not require killed specials."""
    out: List[Any] = []
    for a in list(audits or []):
        if kill_la and audit_or_dir_needs_la(a):
            continue
        if kill_lr and audit_or_dir_needs_lr(a):
            continue
        out.append(a)
    return out


def resource_access_pips(player: Any, game: Any = None) -> Dict[str, float]:
    """Approximate production access Wh/O/Wd/B/Sh (higher = better).

    Prefer explicit ``player.production_access`` / ``resource_pips`` (tests +
    future board wiring). Default medium access so empty boards do not reject
    all candidates.
    """
    names = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
    short = ("Wh", "O", "Wd", "B", "Sh")
    out = {n: 2.0 for n in names}
    # Explicit override for tests / dig-in
    for attr in ("production_access", "resource_pips", "specials_resource_access"):
        raw = getattr(player, attr, None) if player is not None else None
        if isinstance(raw, Mapping) and raw:
            for i, n in enumerate(names):
                for key in (n, n.lower(), short[i], short[i].lower()):
                    if key in raw:
                        try:
                            out[n] = float(raw[key] or 0)
                        except Exception:
                            pass
                        break
            return out
    # Hand as weak proxy (not production, but avoids total zero)
    try:
        from core.player_trade import _get_hand

        hand = list(_get_hand(player) or [])[:5]
        for i, n in enumerate(names):
            if i < len(hand) and int(hand[i] or 0) > 0:
                out[n] = max(out[n], 1.0 + 0.25 * int(hand[i]))
    except Exception:
        pass
    return out


def production_realism_penalty(
    audit_or_dir: Any,
    player: Any,
    game: Any = None,
) -> float:
    """0 = fine; large = fantasy package. Reject if ≥ REALISM_REJECT_THRESHOLD."""
    req = _requirements_of(audit_or_dir)
    access = resource_access_pips(player, game)
    cities = _safe_int(
        req.get("required_cities") or req.get("cities") or req.get("city_upgrades"), 0
    )
    new_s = _safe_int(
        req.get("required_new_intersections")
        or req.get("new_settlements")
        or req.get("new_settlements_to_build"),
        0,
    )
    dcards = _safe_int(
        req.get("required_dcards")
        or req.get("development_cards")
        or req.get("development_cards_to_buy"),
        0,
    )
    vp_cards = _safe_int(req.get("victory_point_cards") or req.get("required_vp_cards"), 0)
    wants_army = bool(req.get("biggest_army") or req.get("largest_army"))

    pen = 0.0
    wh_poor = float(access.get("Wheat", 0) or 0) < ACCESS_POOR_PIPS
    o_poor = float(access.get("Ore", 0) or 0) < ACCESS_POOR_PIPS
    sh_poor = float(access.get("Sheep", 0) or 0) < ACCESS_POOR_PIPS
    wd_poor = float(access.get("Wood", 0) or 0) < ACCESS_POOR_PIPS
    b_poor = float(access.get("Brick", 0) or 0) < ACCESS_POOR_PIPS

    if cities >= 2 and wh_poor and o_poor:
        pen += 8.0
    elif cities >= 2 and (wh_poor or o_poor):
        pen += 4.0
    if dcards >= 2 or vp_cards >= 1 or wants_army:
        if sh_poor:
            pen += 6.0
        if o_poor or wh_poor:
            pen += 3.0
    if new_s >= 2 and wd_poor and b_poor:
        pen += 4.0
    elif new_s >= 2 and (wd_poor or b_poor):
        pen += 2.0
    return float(pen)


def _eta_of(audit: Any) -> float:
    for key in (
        "realistic_expected_turns",
        "board_expected_turns",
        "rank_key",
        "abstract_expected_turns",
    ):
        try:
            v = _audit_get(audit, key, None)
            if v is not None and v != "":
                return float(v)
        except Exception:
            continue
    return 99.0


def score_divert_candidate(
    audit: Any,
    player: Any,
    game: Any = None,
    *,
    realism_weight: float = REALISM_ETA_WEIGHT,
) -> Dict[str, Any]:
    eta = _eta_of(audit)
    pen = production_realism_penalty(audit, player, game)
    score = float(eta) + float(realism_weight) * float(pen)
    return {
        "way_id": _way_id_of(audit),
        "eta": eta,
        "realism_pen": pen,
        "score": score,
        "rejected": pen >= REALISM_REJECT_THRESHOLD,
        "audit": audit,
    }


def pick_divert_way(
    audits: Sequence[Any],
    player: Any,
    game: Any = None,
    *,
    kill_la: bool = False,
    kill_lr: bool = False,
) -> Dict[str, Any]:
    """Filter + score audits; return best candidate meta (may be empty)."""
    filtered = filter_ways_without_specials(
        audits, kill_la=kill_la, kill_lr=kill_lr
    )
    scored: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for a in filtered:
        row = score_divert_candidate(a, player, game)
        if row.get("rejected"):
            rejected.append(row)
            continue
        scored.append(row)
    scored.sort(
        key=lambda r: (
            float(r.get("score") or 99),
            int(r.get("way_id") if r.get("way_id") is not None else 10**9),
        )
    )
    top3 = [
        {
            "way_id": r.get("way_id"),
            "eta": r.get("eta"),
            "realism_pen": r.get("realism_pen"),
            "score": r.get("score"),
        }
        for r in scored[:3]
    ]
    best = scored[0] if scored else None
    return {
        "filtered_count": len(filtered),
        "scored_count": len(scored),
        "rejected_count": len(rejected),
        "top3": top3,
        "best": best,
        "chosen_way_id": (best or {}).get("way_id"),
        "chosen_audit": (best or {}).get("audit"),
        "fallback": not bool(best),
    }


def _clear_specials_progress(player: Any, game: Any, *, kill_la: bool, kill_lr: bool) -> None:
    if kill_la:
        try:
            from core.ai_la_progress import clear_la_progress_from_sticky

            clear_la_progress_from_sticky(player, game)
        except Exception:
            try:
                setattr(player, "la_progress", None)
            except Exception:
                pass
    if kill_lr:
        try:
            from core.ai_lr_project import clear_lr_project_from_sticky

            clear_lr_project_from_sticky(player, game)
        except Exception:
            try:
                setattr(player, "lr_project", None)
            except Exception:
                pass


def specials_divert_turn_key(game: Any, player: Any) -> Tuple[Any, Any, int]:
    """Cadence key: (round, turn, player_id) for once-per-own-turn checks."""
    rnd = getattr(game, "round", None) if game is not None else None
    trn = getattr(game, "turn", None) if game is not None else None
    return (rnd, trn, _player_id(player))


def _normalize_turn_key(value: Any) -> Optional[Tuple[Any, Any, int]]:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) >= 3:
        return (value[0], value[1], _safe_int(value[2], 0))
    if isinstance(value, (list, Sequence)) and not isinstance(value, (str, bytes)):
        try:
            seq = list(value)
            if len(seq) >= 3:
                return (seq[0], seq[1], _safe_int(seq[2], 0))
        except Exception:
            return None
    return None


def is_specials_divert_checked_this_turn(game: Any, player: Any) -> bool:
    """True when own-turn / portfolio divert already ran for this (round, turn, player)."""
    if player is None:
        return False
    key = specials_divert_turn_key(game, player)
    checked = _normalize_turn_key(getattr(player, "specials_divert_checked_turn", None))
    return checked == key


def mark_specials_divert_checked(game: Any, player: Any) -> Tuple[Any, Any, int]:
    """Stamp latch so subsequent same-turn calls skip assess/divert."""
    key = specials_divert_turn_key(game, player)
    if player is not None:
        try:
            # List form is JSON-friendly for save/load
            setattr(player, "specials_divert_checked_turn", [key[0], key[1], key[2]])
        except Exception:
            pass
    return key


def resolve_divert_audits(game: Any, audits: Optional[Sequence[Any]] = None) -> List[Any]:
    """Prefer explicit audits; else cached board audits from last portfolio eval."""
    if audits is not None:
        return list(audits)
    if game is None:
        return []
    for attr in ("current_board_way_audits", "board_way_audits"):
        raw = getattr(game, attr, None)
        if raw:
            return list(raw)
    report = getattr(game, "last_action_timing_report", None)
    if isinstance(report, Mapping):
        raw = report.get("board_way_audits")
        if raw:
            return list(raw)
    return []


def maybe_specials_divert_on_turn_start(
    game: Any,
    player: Any,
    audits: Optional[Sequence[Any]] = None,
    direction: Optional[Mapping[str, Any]] = None,
    *,
    abstract_preferred: Optional[Mapping[str, Any]] = None,
    phase: str = "own_turn_start",
    store: bool = True,
    force: bool = False,
    apply_direction: bool = False,
    force_kill_la: Optional[bool] = None,
    force_kill_lr: Optional[bool] = None,
) -> Dict[str, Any]:
    """S5.5-C: run specials divert at most once per (round, turn, player).

    Latch prevents thrash across repeated ``refresh_strategy_context`` / portfolio
    calls on the same own turn. Skip path is cheap (no assess, no 142). Full
    divert work is timed under span ``specials_divert``.

    When ``apply_direction`` and divert fires with ``direction_out``, persists the
    new preferred way on the player (used from ``refresh_strategy_context``).
    Portfolio override passes ``apply_direction=False`` and applies itself.

    WP3: when give-up escape episode is active and ``GIVEUP_FORCE_DIVERT``, auto
    set ``force`` + episode kill flags unless the caller overrides them.
    """
    if player is None:
        return {
            "s55": True,
            "slice": "C",
            "phase": phase,
            "skipped": True,
            "reason": "no_player",
            "fired": False,
        }

    # WP3: episode-driven force divert (θ desync with S5.5 assess)
    try:
        from core.specials_dead_episode import (
            episode_kill_flags,
            get_specials_dead_episode,
            is_giveup_force_divert_enabled,
        )

        if is_giveup_force_divert_enabled():
            ep = get_specials_dead_episode(player)
            if ep.get("active"):
                kla_ep, klr_ep = episode_kill_flags(player)
                if force_kill_la is None:
                    force_kill_la = kla_ep
                if force_kill_lr is None:
                    force_kill_lr = klr_ep
                if kla_ep or klr_ep:
                    force = True
    except Exception:
        pass

    fk_la = bool(force_kill_la) if force_kill_la is not None else False
    fk_lr = bool(force_kill_lr) if force_kill_lr is not None else False

    key = specials_divert_turn_key(game, player)
    if not force and is_specials_divert_checked_this_turn(game, player):
        last = None
        try:
            last = getattr(player, "last_specials_divert", None)
        except Exception:
            last = None
        if last is None and game is not None:
            try:
                last = getattr(game, "last_specials_divert", None)
            except Exception:
                last = None
        meta: Dict[str, Any] = {
            "s55": True,
            "slice": "C",
            "phase": phase,
            "skipped": True,
            "reason": "already_checked_this_turn",
            "fired": bool(isinstance(last, Mapping) and last.get("fired")),
            "turn_key": list(key),
            "kill_la": bool(isinstance(last, Mapping) and last.get("kill_la")),
            "kill_lr": bool(isinstance(last, Mapping) and last.get("kill_lr")),
            "chosen_way_id": (last or {}).get("chosen_way_id") if isinstance(last, Mapping) else None,
            "dbg": format_specials_divert_dbg(last if isinstance(last, Mapping) else None),
        }
        if isinstance(last, Mapping):
            meta["cached"] = True
            # Surface key dig-in fields from last run without re-assess
            for k in (
                "preferred_way_before",
                "candidate_count",
                "top3",
                "fallback",
                "reason_la",
                "reason_lr",
            ):
                if k in last:
                    meta[k] = last[k]
        return meta

    # Latch before work so re-entrant calls on same tick skip
    mark_specials_divert_checked(game, player)

    resolved = resolve_divert_audits(game, audits)

    try:
        from core.performance_trace import timed_span
    except Exception:
        timed_span = None  # type: ignore
    from contextlib import nullcontext

    span_cm = (
        timed_span(
            game,
            "specials_divert",
            meta={
                "phase": str(phase),
                "force": bool(force),
                "audit_count": len(resolved),
                "player_id": _player_id(player),
            },
        )
        if timed_span is not None and game is not None
        else nullcontext({})
    )

    with span_cm:
        meta = run_specials_divert(
            game,
            player,
            resolved,
            direction,
            abstract_preferred=abstract_preferred,
            phase=phase,
            store=store,
            force_kill_la=fk_la,
            force_kill_lr=fk_lr,
        )

    meta = dict(meta) if isinstance(meta, Mapping) else {"fired": False, "reason": "run_failed"}
    meta["s55"] = True
    meta["slice"] = "C"
    meta["skipped"] = False
    meta["turn_key"] = list(key)
    meta["audit_count"] = len(resolved)
    meta["force"] = bool(force)
    meta["force_kill_la"] = fk_la
    meta["force_kill_lr"] = fk_lr
    if "dbg" not in meta or not meta.get("dbg"):
        meta["dbg"] = format_specials_divert_dbg(meta)

    if (
        apply_direction
        and meta.get("fired")
        and isinstance(meta.get("direction_out"), Mapping)
    ):
        try:
            from core.ai_way_portfolio import persist_strategic_direction

            persist_strategic_direction(player, dict(meta["direction_out"]))
            meta["direction_applied"] = True
        except Exception as exc:
            meta["direction_applied"] = False
            meta["direction_apply_error"] = str(exc)
            try:
                setattr(player, "strategic_direction", dict(meta["direction_out"]))
                meta["direction_applied"] = True
            except Exception:
                pass

    if store and game is not None:
        try:
            # Keep last_specials_divert in sync with C wrapper fields
            stored = dict(getattr(game, "last_specials_divert", None) or {})
            if not stored and isinstance(meta, Mapping):
                stored = {k: v for k, v in meta.items() if k != "direction_out"}
            stored["slice"] = "C"
            stored["phase"] = phase
            stored["turn_key"] = list(key)
            stored["skipped"] = False
            if meta.get("dbg"):
                stored["dbg"] = meta["dbg"]
            setattr(game, "last_specials_divert", stored)
        except Exception:
            pass

    return meta


def run_specials_divert(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Optional[Mapping[str, Any]] = None,
    *,
    abstract_preferred: Optional[Mapping[str, Any]] = None,
    phase: str = "portfolio_override",
    store: bool = True,
    force_kill_la: bool = False,
    force_kill_lr: bool = False,
) -> Dict[str, Any]:
    """S5.5-B: if preferred needs a dead special, pick best non-special way.

    Returns meta with ``fired``, ``direction_out`` (new preferred direction or None),
    candidate ranking, and assess payload. Does not call full 142 generator —
    post-filters existing audits (locked strategy B).

    Prefer :func:`maybe_specials_divert_on_turn_start` for live cadence (S5.5-C).

    ``force_kill_la`` / ``force_kill_lr`` (WP3 give-up escape): treat preferred
    specials as dead even when S5.5 assess is still soft (θ desync).
    """
    d = _direction_of(player, direction)
    assess = assess_specials_for_player(game, player, d, store=store)
    la = assess.get("la") if isinstance(assess.get("la"), Mapping) else {}
    lr = assess.get("lr") if isinstance(assess.get("lr"), Mapping) else {}

    pref_needs_la = audit_or_dir_needs_la(d)
    pref_needs_lr = audit_or_dir_needs_lr(d)
    # Way-table backup when direction flags stripped after give-up but way_id remains
    if not pref_needs_la or not pref_needs_lr:
        try:
            from core.specials_dead_episode import way_id_needs_specials

            wid = _way_id_of(d)
            t_la, t_lr = way_id_needs_specials(wid)
            pref_needs_la = pref_needs_la or t_la
            pref_needs_lr = pref_needs_lr or t_lr
        except Exception:
            pass
    kill_la = bool(
        pref_needs_la
        and (
            bool(force_kill_la)
            or la.get("hopeless")
            or la.get("unstoppable_opp")
        )
    )
    kill_lr = bool(
        pref_needs_lr
        and (
            bool(force_kill_lr)
            or lr.get("hopeless")
            or lr.get("unstoppable_opp")
        )
    )

    pref_id = _way_id_of(d)
    meta: Dict[str, Any] = {
        "s55": True,
        "slice": "B",
        "phase": phase,
        "fired": False,
        "kill_la": kill_la,
        "kill_lr": kill_lr,
        "force_kill_la": bool(force_kill_la),
        "force_kill_lr": bool(force_kill_lr),
        "reason_la": la.get("reason"),
        "reason_lr": lr.get("reason"),
        "preferred_way_before": pref_id,
        "chosen_way_id": None,
        "candidate_count": 0,
        "top3": [],
        "fallback": False,
        "direction_out": None,
        "assess": assess,
        "reason": "no_divert",
    }

    if not kill_la and not kill_lr:
        meta["reason"] = "specials_still_live_or_unneeded"
        if store and game is not None:
            try:
                setattr(game, "last_specials_divert", dict(meta))
            except Exception:
                pass
        return meta

    # Preferred still depends on a dead special → divert
    pick = pick_divert_way(
        audits, player, game, kill_la=kill_la, kill_lr=kill_lr
    )
    meta["candidate_count"] = int(pick.get("scored_count") or 0)
    meta["top3"] = list(pick.get("top3") or [])
    meta["fallback"] = bool(pick.get("fallback"))

    chosen_audit = pick.get("chosen_audit")
    if chosen_audit is None:
        # No filtered candidate — force re-rank flag; leave direction to caller
        meta["fired"] = True
        meta["reason"] = "no_filtered_candidate_fallback"
        meta["fallback"] = True
        try:
            setattr(player, "force_strategy_recalc", True)
            from core.strategy_sticky import clear_sticky_commitment, flag_strategy_recalc

            flag_strategy_recalc(
                player,
                "s55_divert_fallback",
                detail={"kill_la": kill_la, "kill_lr": kill_lr},
            )
            clear_sticky_commitment(player)
            try:
                from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

                invalidate_board_way_portfolio_cache(game, "s55_divert_fallback")
            except Exception:
                pass
        except Exception:
            pass
        _clear_specials_progress(player, game, kill_la=kill_la, kill_lr=kill_lr)
        if store and game is not None:
            try:
                setattr(game, "last_specials_divert", dict(meta))
            except Exception:
                pass
        if store and player is not None:
            try:
                setattr(player, "last_specials_divert", dict(meta))
            except Exception:
                pass
        return meta

    # Build new direction from chosen audit
    try:
        from core.ai_way_portfolio import board_audit_to_strategic_direction

        new_dir = board_audit_to_strategic_direction(
            chosen_audit,
            abstract_preferred=dict(abstract_preferred or d),
            override_applied=True,
            override_reason="s55_specials_divert",
        )
    except Exception:
        new_dir = {
            "preferred_way_id": pick.get("chosen_way_id"),
            "way_id": pick.get("chosen_way_id"),
            "preference_source": "s55_specials_divert",
        }

    new_dir["preference_source"] = (
        str(new_dir.get("preference_source") or "") + "+S55_divert"
    ).lstrip("+")
    new_dir["specials_divert"] = {
        "kill_la": kill_la,
        "kill_lr": kill_lr,
        "from_way": pref_id,
        "to_way": pick.get("chosen_way_id"),
        "reason_la": la.get("reason"),
        "reason_lr": lr.get("reason"),
    }

    # Full sticky clear then caller recommits (locked §13 #6)
    try:
        from core.strategy_sticky import clear_sticky_commitment, flag_strategy_recalc

        clear_sticky_commitment(player)
        flag_strategy_recalc(
            player,
            "s55_specials_divert",
            detail={
                "from_way": pref_id,
                "to_way": pick.get("chosen_way_id"),
                "kill_la": kill_la,
                "kill_lr": kill_lr,
            },
        )
        try:
            from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

            invalidate_board_way_portfolio_cache(game, "s55_specials_divert")
        except Exception:
            pass
    except Exception:
        pass
    try:
        setattr(player, "force_strategy_recalc", True)
    except Exception:
        pass

    _clear_specials_progress(player, game, kill_la=kill_la, kill_lr=kill_lr)

    # Align S5b latch so we do not re-fire thrash on same special
    try:
        from core.strategy_way_kill import _set_latch

        kind = "LA" if kill_la and not kill_lr else ("LR" if kill_lr and not kill_la else "LA")
        reason = str(la.get("reason") if kind == "LA" else lr.get("reason") or "s55_divert")
        _set_latch(player, way_id=pref_id, kind=kind, game=game, reason=reason)
    except Exception:
        try:
            setattr(
                player,
                "way_kill_latch",
                {
                    "way_id": pref_id,
                    "kind": "LA" if kill_la else "LR",
                    "reason": "s55_divert",
                },
            )
        except Exception:
            pass

    meta.update(
        {
            "fired": True,
            "chosen_way_id": pick.get("chosen_way_id"),
            "direction_out": new_dir,
            "reason": (
                f"divert from {pref_id} → {pick.get('chosen_way_id')} "
                f"(kill_la={kill_la}, kill_lr={kill_lr})"
            ),
        }
    )
    # Drop audit object from store-friendly copy
    store_meta = dict(meta)
    store_meta.pop("direction_out", None)
    store_meta["direction_out_way"] = new_dir.get("preferred_way_id")
    if isinstance(store_meta.get("assess"), Mapping):
        ass = dict(store_meta["assess"])
        # shrink snapshot for Phase0
        snap = ass.get("snapshot") if isinstance(ass.get("snapshot"), Mapping) else {}
        ass["snapshot"] = {
            k: snap.get(k)
            for k in (
                "own_army",
                "max_opp_army",
                "own_lr_length",
                "max_opp_lr_length",
                "own_residual_growth_cap",
                "stack_remaining",
            )
        }
        store_meta["assess"] = ass

    if store and game is not None:
        try:
            setattr(game, "last_specials_divert", store_meta)
        except Exception:
            pass
    if store and player is not None:
        try:
            setattr(player, "last_specials_divert", store_meta)
        except Exception:
            pass
    meta["dbg"] = format_specials_divert_dbg(meta)
    return meta


def format_specials_divert_dbg(meta: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(meta, Mapping) or not meta:
        return "Divert: n/a"
    if not meta.get("fired"):
        return "Divert: skip"
    fr = meta.get("preferred_way_before")
    to = meta.get("chosen_way_id")
    bits = []
    if meta.get("kill_la"):
        bits.append("LA")
    if meta.get("kill_lr"):
        bits.append("LR")
    left = "+".join(bits) or "?"
    if meta.get("fallback"):
        return f"Divert: left {left} (no alt; fallback)"
    top = ""
    try:
        t0 = (meta.get("top3") or [{}])[0]
        if t0.get("eta") is not None:
            top = f" η={float(t0['eta']):.1f}"
    except Exception:
        pass
    text = f"Divert: left {left} {fr}→{to}{top}"
    return text if len(text) <= 72 else text[:69] + "..."


__all__ = [
    "ACCESS_POOR_PIPS",
    "DCARD_STACK_TINY",
    "LA_GAP_KILL",
    "LR_GAP_KILL",
    "LR_MIN_LENGTH",
    "MAX_RESIDUAL_SAMPLE",
    "REALISM_ETA_WEIGHT",
    "REALISM_REJECT_THRESHOLD",
    "assess_la_unstoppable",
    "assess_lr_unstoppable",
    "assess_specials_for_player",
    "audit_or_dir_needs_la",
    "audit_or_dir_needs_lr",
    "collect_specials_board_snapshot",
    "filter_ways_without_specials",
    "format_specials_assess_dbg",
    "format_specials_divert_dbg",
    "is_specials_divert_checked_this_turn",
    "mark_specials_divert_checked",
    "maybe_specials_divert_on_turn_start",
    "pick_divert_way",
    "production_realism_penalty",
    "residual_growth_cap",
    "resolve_divert_audits",
    "resource_access_pips",
    "run_specials_divert",
    "score_divert_candidate",
    "specials_divert_turn_key",
]
