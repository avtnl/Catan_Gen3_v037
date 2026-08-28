"""WP4: tangible LA / LR race plan packages (pure plan dicts).

Builds coachable multi-turn specials plans without mutating the board:

- ``LrRacePlan`` — lengths, claim/grow edges, deny candidates, TFR value
- ``LaRacePlan`` — army gaps, knight play/hold, buys, deck

Refresh on Strategy-Engine refresh (L0 or L2). Optional sticky road merge when
LR confidence is high. Soft knight-before-TFR policy (improving_SE_v3 rules).

Does **not** execute cards or roads. See docs/SE_improvement_plan_v2.md §3.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

Edge = Tuple[int, int]

# Sticky merge knobs
LR_STICKY_MERGE_MIN_CONF: float = 0.55
LR_STICKY_MERGE_MAX_EDGES: int = 4

# Soft score bump when prefer_knight / prefer_tfr (chooser)
KNIGHT_TFR_POLICY_BUMP: float = 12.0


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _edge(raw: Any) -> Optional[Edge]:
    try:
        if isinstance(raw, Mapping):
            for k in ("road_id", "road", "edge", "target_road", "next_road"):
                if k in raw:
                    return _edge(raw.get(k))
            return None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            a, b = int(raw[0]), int(raw[1])
            if a == b:
                return None
            return (a, b) if a < b else (b, a)
    except Exception:
        return None
    return None


def _fmt_edges(edges: Sequence[Any]) -> str:
    bits: List[str] = []
    for e in edges or []:
        key = _edge(e)
        if key:
            bits.append(f"{key[0]}-{key[1]}")
    return ";".join(bits)


def build_lr_race_plan(
    game: Any,
    player: Any,
    *,
    candidates: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Coachable Longest Road race package (pure)."""
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    plan: Dict[str, Any] = {
        "kind": "lr_race_plan",
        "version": 1,
        "player_id": pid,
        "active": False,
        "wants_lr": False,
        "own_length": 0,
        "max_opp_length": 0,
        "holder_id": None,
        "we_hold": False,
        "contested": False,
        "claim_now": False,
        "grow_edges": [],
        "deny_edges": [],
        "project_edges": [],
        "tfr_edges": [],
        "has_tfr": False,
        "can_afford_road": False,
        "confidence": 0.0,
        "score": 0.0,
        "label": "",
        "reason": "",
        "sticky_roads_fp": "",
    }
    if player is None or game is None:
        plan["reason"] = "no_player_or_game"
        return plan

    wants = False
    try:
        from core.ai_lr_project import way_wants_longest_road

        wants = bool(way_wants_longest_road(player))
    except Exception:
        pass
    plan["wants_lr"] = wants

    try:
        from core.strategy_way_residual import unplayed_tfr

        plan["has_tfr"] = int(unplayed_tfr(player) or 0) > 0
    except Exception:
        plan["has_tfr"] = False

    try:
        from core.strategy_explicit_recalc import _can_afford_road

        plan["can_afford_road"] = bool(_can_afford_road(player))
    except Exception:
        # inline hand check
        try:
            rc = getattr(player, "rcards", None)
            if isinstance(rc, Mapping):
                plan["can_afford_road"] = int(rc.get("Wood", 0) or 0) >= 1 and int(
                    rc.get("Brick", 0) or 0
                ) >= 1
        except Exception:
            pass

    snap: Dict[str, Any] = {}
    race: Dict[str, Any] = {}
    project: Dict[str, Any] = {}
    try:
        from core.ai_lr_project import (
            build_lr_project,
            compute_lr_race_state,
            compute_lr_snapshot,
            get_stored_lr_project,
            remaining_lr_project_roads,
            tfr_edges_from_lr_project,
        )

        snap = compute_lr_snapshot(game, player)
        project = dict(get_stored_lr_project(player, game) or {})
        if not project.get("roads_to_build"):
            project = dict(build_lr_project(game, player, candidates) or {})
        race = compute_lr_race_state(game, player, project=project)
        rem = remaining_lr_project_roads(game, player)
        if rem:
            plan["project_edges"] = [list(e) for e in rem[:LR_STICKY_MERGE_MAX_EDGES]]
        elif project.get("roads_to_build"):
            plan["project_edges"] = [
                list(_edge(r) or r)
                for r in list(project.get("roads_to_build") or [])[:LR_STICKY_MERGE_MAX_EDGES]
                if _edge(r) or isinstance(r, (list, tuple))
            ]
        try:
            tfr_e = tfr_edges_from_lr_project(game, player, project) or []
            plan["tfr_edges"] = [list(_edge(e) or e) for e in tfr_e[:4] if e]
        except Exception:
            plan["tfr_edges"] = list(plan["project_edges"][:2])
    except Exception as exc:
        plan["reason"] = f"lr_build_error:{exc}"
        return plan

    plan["own_length"] = int(snap.get("own_length") or 0)
    plan["max_opp_length"] = int(snap.get("max_opp_length") or 0)
    plan["holder_id"] = snap.get("holder_id")
    plan["we_hold"] = bool(
        snap.get("holder_id") is not None
        and int(snap.get("holder_id") or 0) == pid
    ) or bool(
        getattr(player, "longest_route_tf", False)
        or getattr(player, "longest_road_tf", False)
    )
    plan["contested"] = bool(race.get("lr_race") or race.get("contested"))
    plan["claim_now"] = bool(project.get("takes_now"))

    # Grow = project edges (or first edge of grow kind)
    grow = list(plan["project_edges"] or [])
    if project.get("kind") == "lr_claim" and grow:
        plan["grow_edges"] = grow[:1]
    else:
        plan["grow_edges"] = grow[:LR_STICKY_MERGE_MAX_EDGES]

    # Deny: legal edges that touch sticky target neighborhood or opp path tips
    deny: List[List[int]] = []
    try:
        deny = _collect_deny_edges(game, player, snap=snap, project=project)
    except Exception:
        deny = []
    plan["deny_edges"] = deny[:6]

    # Confidence / score
    conf = 0.15 if wants else 0.05
    if plan["claim_now"]:
        conf = max(conf, 0.9)
    if plan["grow_edges"]:
        conf = max(conf, 0.5 if wants else 0.25)
    if plan["contested"] and wants:
        conf = max(conf, 0.65)
    if plan["has_tfr"] and (plan["grow_edges"] or plan["claim_now"]):
        conf = min(1.0, conf + 0.1)
    if plan["we_hold"] and not plan["contested"]:
        conf = max(conf, 0.4)
    plan["confidence"] = round(float(conf), 3)

    score = float(plan["own_length"]) * 2.0
    if plan["claim_now"]:
        score += 20.0
    if plan["contested"]:
        score += 8.0
    if plan["has_tfr"]:
        score += 5.0
    if deny:
        score += 3.0 * min(2, len(deny))
    plan["score"] = round(score, 2)

    if plan["claim_now"]:
        plan["label"] = "LR claim now"
        plan["reason"] = "one_edge_takes_longest_road"
    elif plan["grow_edges"] and plan["contested"]:
        plan["label"] = "LR race grow"
        plan["reason"] = "contested_grow_path"
    elif plan["grow_edges"] and wants:
        plan["label"] = "LR grow"
        plan["reason"] = "project_grow"
    elif deny and wants:
        plan["label"] = "LR deny"
        plan["reason"] = "block_opp_path"
    elif wants:
        plan["label"] = "LR watch"
        plan["reason"] = "wants_lr_no_path"
    else:
        plan["label"] = "LR idle"
        plan["reason"] = "way_not_lr"

    plan["active"] = bool(
        wants
        or plan["claim_now"]
        or plan["we_hold"]
        or (plan["grow_edges"] and plan["contested"])
    )
    roads_for_fp = plan["grow_edges"] or plan["deny_edges"][:2]
    plan["sticky_roads_fp"] = _fmt_edges(roads_for_fp)
    return plan


def _collect_deny_edges(
    game: Any,
    player: Any,
    *,
    snap: Mapping[str, Any],
    project: Mapping[str, Any],
) -> List[List[int]]:
    """Heuristic deny edges: empty edges adjacent to sticky settle target or opp tips."""
    out: List[List[int]] = []
    seen: set = set()
    pid = _safe_int(getattr(player, "id", 0), 0) or 0

    sticky_tid = None
    try:
        sticky = getattr(player, "sticky_commitment", None) or {}
        if isinstance(sticky, Mapping):
            sticky_tid = _safe_int(sticky.get("locked_rec_target_id"), None)
        direction = getattr(player, "strategic_direction", None) or {}
        if sticky_tid is None and isinstance(direction, Mapping):
            sticky_tid = _safe_int(
                direction.get("recommendation_target_id")
                or direction.get("settlement_target_id"),
                None,
            )
    except Exception:
        sticky_tid = None

    board = getattr(game, "board", None)
    if board is None:
        return out

    def _add_empty_incident(node: int) -> None:
        try:
            inter = board.intersections[int(node)]
        except Exception:
            return
        for road_tuple in list(getattr(inter, "three_roads", []) or []):
            key = _edge(road_tuple)
            if not key or key in seen:
                continue
            # empty or ours only — deny is building empty edge first
            try:
                from core.outlook_logic import road_is_empty_or_owned_by_player

                if not road_is_empty_or_owned_by_player(game, player, key):
                    # only empty edges for deny placement
                    road_map = {}
                    try:
                        from core.outlook_logic import board_road_map

                        road_map = board_road_map(board)
                    except Exception:
                        pass
                    r = road_map.get(key) if road_map else None
                    color = str(getattr(r, "color", "Blank") or "Blank") if r else "Blank"
                    if color not in ("", "Blank", "None"):
                        continue
            except Exception:
                pass
            seen.add(key)
            out.append([key[0], key[1]])

    if sticky_tid is not None:
        _add_empty_incident(int(sticky_tid))
        try:
            inter = board.intersections[int(sticky_tid)]
            for nb in list(getattr(inter, "three_intersection_ids", []) or []):
                _add_empty_incident(int(nb))
        except Exception:
            pass

    # Opp road endpoints when contested
    if bool(snap.get("max_opp_length") or 0) >= 3:
        for opp in list(getattr(game, "players", []) or []):
            if opp is None:
                continue
            opid = _safe_int(getattr(opp, "id", 0), 0) or 0
            if opid == pid:
                continue
            for raw in list(getattr(opp, "roads", []) or [])[:12]:
                e = _edge(raw)
                if not e:
                    continue
                _add_empty_incident(e[0])
                _add_empty_incident(e[1])
                if len(out) >= 6:
                    break
            if len(out) >= 6:
                break

    return out[:6]


def build_la_race_plan(game: Any, player: Any) -> Dict[str, Any]:
    """Coachable Largest Army race package (pure)."""
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    plan: Dict[str, Any] = {
        "kind": "la_race_plan",
        "version": 1,
        "player_id": pid,
        "active": False,
        "wants_la": False,
        "army_ai": 0,
        "max_opp_army": 0,
        "target_army": 3,
        "la_race": False,
        "we_hold": False,
        "would_take_now": False,
        "playable_knights": 0,
        "buys_remaining_est": 0,
        "can_buy_dcard_now": False,
        "deck_remaining_est": None,
        "play_knight": False,
        "postpone_knight": True,
        "confidence": 0.0,
        "score": 0.0,
        "label": "",
        "reason": "",
        "prefer_knight_vs_tfr": None,
    }
    if player is None or game is None:
        plan["reason"] = "no_player_or_game"
        return plan

    progress: Dict[str, Any] = {}
    race: Dict[str, Any] = {}
    try:
        from core.ai_la_progress import compute_la_progress, way_wants_largest_army
        from core.ai_lr_project import compute_la_race_state

        progress = compute_la_progress(game, player)
        race = compute_la_race_state(game, player)
        plan["wants_la"] = bool(
            way_wants_largest_army(player) or progress.get("wants_la")
        )
    except Exception as exc:
        plan["reason"] = f"la_build_error:{exc}"
        return plan

    plan["army_ai"] = int(progress.get("army_ai") or 0)
    plan["max_opp_army"] = int(progress.get("max_opp_army") or 0)
    plan["target_army"] = int(progress.get("target_army") or 3)
    plan["la_race"] = bool(progress.get("la_race") or race.get("la_race"))
    plan["we_hold"] = bool(progress.get("we_hold_la"))
    plan["would_take_now"] = bool(progress.get("would_take_now") or race.get("would_take_la"))
    plan["playable_knights"] = int(progress.get("knights_in_hand_playable") or 0)
    plan["buys_remaining_est"] = int(progress.get("buys_remaining_est") or 0)
    plan["can_buy_dcard_now"] = bool(progress.get("can_buy_dcard_now"))
    plan["deck_remaining_est"] = progress.get("deck_remaining_est")

    play = bool(plan["would_take_now"] and plan["playable_knights"] >= 1)
    if plan["la_race"] and plan["playable_knights"] >= 1 and plan["army_ai"] >= 2:
        play = True
    plan["play_knight"] = play
    plan["postpone_knight"] = not play and plan["playable_knights"] >= 1

    conf = 0.15 if plan["wants_la"] else 0.05
    if plan["would_take_now"]:
        conf = 0.95
    elif plan["la_race"]:
        conf = 0.7
    elif plan["wants_la"] and plan["playable_knights"]:
        conf = 0.45
    plan["confidence"] = round(float(conf), 3)

    score = float(plan["army_ai"]) * 3.0
    if plan["would_take_now"]:
        score += 25.0
    if plan["la_race"]:
        score += 10.0
    plan["score"] = round(score, 2)

    if plan["would_take_now"]:
        plan["label"] = "LA take now"
        plan["reason"] = "playable_knight_takes_la"
    elif plan["la_race"]:
        plan["label"] = "LA race"
        plan["reason"] = "army_race_live"
    elif plan["wants_la"]:
        plan["label"] = "LA chase"
        plan["reason"] = f"need_knights:{progress.get('knights_needed_to_take')}"
    else:
        plan["label"] = "LA idle"
        plan["reason"] = "way_not_la"

    plan["active"] = bool(
        plan["wants_la"] or plan["we_hold"] or plan["la_race"] or plan["would_take_now"]
    )
    return plan


def prefer_knight_before_tfr(
    game: Any,
    player: Any,
    *,
    lr_plan: Optional[Mapping[str, Any]] = None,
    la_plan: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """WP3/v3 soft policy: knight vs TFR when both LA and LR matter.

    Returns ``{prefer_knight: bool|None, rule: str, reason: str}``.
    ``prefer_knight is None`` → no bias (policy off or insufficient signal).
    """
    out: Dict[str, Any] = {
        "prefer_knight": None,
        "rule": "none",
        "reason": "",
        "enabled": True,
    }
    try:
        from core import constants as C

        mode = str(getattr(C, "KNIGHT_TFR_POLICY", "rules_v1") or "rules_v1").lower()
        if mode in ("off", "0", "false", "none"):
            out["enabled"] = False
            out["reason"] = "policy_off"
            return out
    except Exception:
        pass

    la = dict(la_plan or {})
    lr = dict(lr_plan or {})
    if not la:
        la = build_la_race_plan(game, player)
    if not lr:
        lr = build_lr_race_plan(game, player)

    wants_la = bool(la.get("wants_la") or la.get("active"))
    wants_lr = bool(lr.get("wants_lr") or lr.get("active"))
    la_race = bool(la.get("la_race") or la.get("would_take_now"))
    lr_contested = bool(lr.get("contested") or lr.get("claim_now"))

    # Engine strength proxies: residual buys / path length
    la_good = bool(
        la.get("would_take_now")
        or (int(la.get("army_ai") or 0) >= 2 and int(la.get("buys_remaining_est") or 99) <= 2)
        or (la_race and int(la.get("playable_knights") or 0) >= 1)
    )
    lr_good = bool(
        lr.get("claim_now")
        or (int(lr.get("own_length") or 0) >= 4 and (lr.get("has_tfr") or lr.get("grow_edges")))
        or (lr_contested and lr.get("has_tfr"))
    )
    la_hopeless = bool(
        wants_la
        and int(la.get("buys_remaining_est") or 0) >= 4
        and int(la.get("army_ai") or 0) <= 1
        and not la_race
    )
    lr_hopeless = bool(
        wants_lr
        and int(lr.get("own_length") or 0) <= 2
        and int(lr.get("max_opp_length") or 0) >= 5
        and not lr.get("has_tfr")
        and not lr.get("claim_now")
    )

    # b) LA only
    if wants_la and not wants_lr:
        out["prefer_knight"] = True
        out["rule"] = "b"
        out["reason"] = "la_only"
        return out
    # f) LR only
    if wants_lr and not wants_la:
        out["prefer_knight"] = False
        out["rule"] = "f"
        out["reason"] = "lr_only"
        return out
    # d) behind LA, still LR realistic
    if wants_la and wants_lr and la_hopeless and lr_good:
        out["prefer_knight"] = False
        out["rule"] = "d"
        out["reason"] = "la_hopeless_lr_good"
        return out
    # g) behind LR, still LA realistic
    if wants_la and wants_lr and lr_hopeless and la_good:
        out["prefer_knight"] = True
        out["rule"] = "g"
        out["reason"] = "lr_hopeless_la_good"
        return out
    # c / a) LA race or both and LA stronger
    if wants_la and wants_lr:
        if la_race and (la_good or not lr_good):
            out["prefer_knight"] = True
            out["rule"] = "c" if la_race else "a"
            out["reason"] = "la_race_or_strong"
            return out
        # e) both and LR stronger
        if lr_good and not la_good:
            out["prefer_knight"] = False
            out["rule"] = "e"
            out["reason"] = "lr_engine_strong"
            return out
        if lr_contested and not la_race:
            out["prefer_knight"] = False
            out["rule"] = "e"
            out["reason"] = "lr_contested_no_la_race"
            return out
        # soft default both contested similar → knight (easier to hold LA)
        if la_race or lr_contested:
            out["prefer_knight"] = True
            out["rule"] = "a"
            out["reason"] = "both_contested_prefer_la_hold"
            return out

    out["reason"] = "no_signal"
    return out


def refresh_specials_race_plans(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    apply_sticky: bool = True,
    candidates: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Build LA/LR plans, store on player/game, optional sticky road merge.

    Returns bag with ``lr``, ``la``, ``knight_tfr``, ``sticky_merged``.
    """
    bag: Dict[str, Any] = {
        "ok": False,
        "reason": reason or "refresh",
        "lr": {},
        "la": {},
        "knight_tfr": {},
        "sticky_merged": False,
    }
    if player is None or game is None:
        bag["reason"] = "no_player_or_game"
        return bag

    lr = build_lr_race_plan(game, player, candidates=candidates)
    la = build_la_race_plan(game, player)
    kt = prefer_knight_before_tfr(game, player, lr_plan=lr, la_plan=la)
    la["prefer_knight_vs_tfr"] = kt.get("prefer_knight")
    la["knight_tfr_rule"] = kt.get("rule")
    lr["prefer_knight_vs_tfr"] = kt.get("prefer_knight")

    bag["lr"] = lr
    bag["la"] = la
    bag["knight_tfr"] = kt
    bag["ok"] = True

    try:
        player.lr_race_plan = dict(lr)
        player.la_race_plan = dict(la)
        player.knight_tfr_policy = dict(kt)
    except Exception:
        pass
    try:
        game.last_lr_race_plan = dict(lr)
        game.last_la_race_plan = dict(la)
        game.last_specials_race_player_id = getattr(player, "id", None)
    except Exception:
        pass

    if apply_sticky:
        bag["sticky_merged"] = bool(
            maybe_merge_lr_plan_into_sticky(game, player, lr)
        )

    # Attach compact fields onto strategic_direction for CS/dig
    try:
        direction = getattr(player, "strategic_direction", None)
        if isinstance(direction, dict):
            direction = dict(direction)
            direction["lr_race_plan"] = {
                "label": lr.get("label"),
                "confidence": lr.get("confidence"),
                "claim_now": lr.get("claim_now"),
                "contested": lr.get("contested"),
                "sticky_roads_fp": lr.get("sticky_roads_fp"),
                "own_length": lr.get("own_length"),
                "max_opp_length": lr.get("max_opp_length"),
            }
            direction["la_race_plan"] = {
                "label": la.get("label"),
                "confidence": la.get("confidence"),
                "play_knight": la.get("play_knight"),
                "la_race": la.get("la_race"),
                "army_ai": la.get("army_ai"),
                "max_opp_army": la.get("max_opp_army"),
            }
            direction["knight_tfr_policy"] = {
                "prefer_knight": kt.get("prefer_knight"),
                "rule": kt.get("rule"),
                "reason": kt.get("reason"),
            }
            player.strategic_direction = direction
    except Exception:
        pass

    return bag


def maybe_merge_lr_plan_into_sticky(
    game: Any,
    player: Any,
    lr_plan: Optional[Mapping[str, Any]] = None,
) -> bool:
    """When LR confidence high, set sticky roads from grow path (keep C/S locks)."""
    plan = dict(lr_plan or getattr(player, "lr_race_plan", None) or {})
    if not plan.get("active") and not plan.get("wants_lr"):
        return False
    conf = float(plan.get("confidence") or 0)
    if conf < LR_STICKY_MERGE_MIN_CONF and not plan.get("claim_now"):
        return False
    edges = list(plan.get("grow_edges") or plan.get("project_edges") or [])
    if not edges and plan.get("deny_edges") and conf >= 0.7:
        edges = list(plan.get("deny_edges") or [])[:2]
    if not edges:
        return False

    roads = []
    for e in edges[:LR_STICKY_MERGE_MAX_EDGES]:
        key = _edge(e)
        if key:
            roads.append([key[0], key[1]])
    if not roads:
        return False

    # Prefer existing LR project store when claim/grow project exists
    try:
        from core.ai_lr_project import (
            build_lr_project,
            get_stored_lr_project,
            merge_lr_project_into_sticky,
            store_lr_project,
        )

        stored = get_stored_lr_project(player, game)
        if not stored or not stored.get("roads_to_build"):
            proj = build_lr_project(game, player)
            if proj:
                store_lr_project(game, player, proj, merge_sticky=True)
                stored = proj
        if stored and stored.get("roads_to_build"):
            # Align sticky roads with plan grow if empty settle path.
            # Do NOT wipe an existing settle path on claim_now when that path
            # is dual-purpose (or simply already locked toward S/C).
            raw = getattr(player, "sticky_commitment", None)
            commitment = dict(raw) if isinstance(raw, Mapping) else {}
            has_settle_lock = bool(
                commitment.get("locked_roads_to_build")
                and (
                    commitment.get("locked_rec_target_id") is not None
                    or str(commitment.get("locked_target_kind") or "").upper()
                    in ("S", "SETTLE", "SETTLEMENT", "C", "CITY")
                )
            )
            if has_settle_lock:
                commitment["lr_race_plan_fp"] = plan.get("sticky_roads_fp")
                commitment["lr_race_label"] = plan.get("label")
                commitment["lr_deny_edges"] = list(plan.get("deny_edges") or [])[:4]
                try:
                    player.sticky_commitment = commitment
                except Exception:
                    pass
                return True
            if not commitment.get("locked_roads_to_build") or plan.get("claim_now"):
                commitment["locked_roads_to_build"] = list(
                    stored.get("roads_to_build") or roads
                )
                commitment["lr_race_plan_fp"] = plan.get("sticky_roads_fp")
                commitment["lr_race_label"] = plan.get("label")
                try:
                    player.sticky_commitment = commitment
                except Exception:
                    pass
            return True
        # No project engine path — write roads only
        raw = getattr(player, "sticky_commitment", None)
        commitment = dict(raw) if isinstance(raw, Mapping) else {}
        if commitment.get("locked_rec_target_id") and commitment.get(
            "locked_roads_to_build"
        ):
            # Keep settle path; only attach lr hint
            commitment["lr_race_plan_fp"] = plan.get("sticky_roads_fp")
            commitment["lr_deny_edges"] = list(plan.get("deny_edges") or [])[:4]
        else:
            commitment["locked_roads_to_build"] = roads
            if not commitment.get("locked_target_kind"):
                commitment["locked_target_kind"] = "LR"
            commitment["lr_race_plan_fp"] = plan.get("sticky_roads_fp")
            commitment["lr_race_label"] = plan.get("label")
        try:
            player.sticky_commitment = commitment
        except Exception:
            return False
        return True
    except Exception:
        return False


def apply_knight_tfr_policy_to_candidates(
    candidates: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    *,
    bump: float = KNIGHT_TFR_POLICY_BUMP,
) -> List[Dict[str, Any]]:
    """Soft score bump on knight or TFR rows per prefer_knight policy."""
    prefer = policy.get("prefer_knight")
    if prefer is None or not policy.get("enabled", True):
        return [dict(c) for c in candidates]
    out: List[Dict[str, Any]] = []
    for row in candidates:
        r = dict(row)
        card = str(r.get("card") or "")
        if not bool(r.get("play")) or not bool(r.get("legal")):
            out.append(r)
            continue
        score = float(r.get("norm_score") or 0)
        if prefer is True and card == "knight":
            r["norm_score"] = round(score + float(bump), 3)
            r["wp4_knight_tfr_boost"] = float(bump)
            r["wp4_rule"] = policy.get("rule")
        elif prefer is True and card == "two_free_roads":
            # mild demote soft TFR only
            tier = str(r.get("tier") or "")
            if tier in ("soft", "weak", "hold_plan"):
                r["norm_score"] = round(score - float(bump) * 0.45, 3)
                r["wp4_knight_tfr_demote"] = True
        elif prefer is False and card == "two_free_roads":
            r["norm_score"] = round(score + float(bump), 3)
            r["wp4_knight_tfr_boost"] = float(bump)
            r["wp4_rule"] = policy.get("rule")
        elif prefer is False and card == "knight":
            tier = str(r.get("tier") or "")
            reason = str(r.get("reason") or "")
            if tier not in ("crit", "win_now") and "la_crit" not in reason:
                r["norm_score"] = round(score - float(bump) * 0.45, 3)
                r["wp4_knight_tfr_demote"] = True
        out.append(r)
    return out


def cs_fields_from_race_plans(player: Any) -> Dict[str, Any]:
    """Compact CS dig fields for MORE / PLAN snapshots."""
    lr = getattr(player, "lr_race_plan", None) if player is not None else None
    la = getattr(player, "la_race_plan", None) if player is not None else None
    kt = getattr(player, "knight_tfr_policy", None) if player is not None else None
    out: Dict[str, Any] = {
        "lr_plan_label": None,
        "lr_plan_conf": None,
        "lr_plan_roads_fp": None,
        "lr_plan_claim": None,
        "la_plan_label": None,
        "la_plan_conf": None,
        "la_plan_play_knight": None,
        "knight_tfr_prefer": None,
        "knight_tfr_rule": None,
    }
    if isinstance(lr, Mapping):
        out["lr_plan_label"] = str(lr.get("label") or "") or None
        out["lr_plan_conf"] = lr.get("confidence")
        out["lr_plan_roads_fp"] = str(lr.get("sticky_roads_fp") or "") or None
        out["lr_plan_claim"] = bool(lr.get("claim_now")) if lr.get("claim_now") is not None else None
    if isinstance(la, Mapping):
        out["la_plan_label"] = str(la.get("label") or "") or None
        out["la_plan_conf"] = la.get("confidence")
        out["la_plan_play_knight"] = (
            bool(la.get("play_knight")) if la.get("play_knight") is not None else None
        )
    if isinstance(kt, Mapping):
        pk = kt.get("prefer_knight")
        if pk is True:
            out["knight_tfr_prefer"] = "knight"
        elif pk is False:
            out["knight_tfr_prefer"] = "tfr"
        out["knight_tfr_rule"] = str(kt.get("rule") or "") or None
    return out


__all__ = [
    "build_lr_race_plan",
    "build_la_race_plan",
    "prefer_knight_before_tfr",
    "refresh_specials_race_plans",
    "maybe_merge_lr_plan_into_sticky",
    "apply_knight_tfr_policy_to_candidates",
    "cs_fields_from_race_plans",
    "LR_STICKY_MERGE_MIN_CONF",
    "KNIGHT_TFR_POLICY_BUMP",
]
