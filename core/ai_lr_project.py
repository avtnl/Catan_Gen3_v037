"""S-LR: executable Longest Road project planner + turn focus.

Builds multi-edge grow/claim paths using the real continuous-length engine
(``core.longest_road``). Does not mutate game state.

Consumed by ``ai_road_planner.build_ai_road_plan`` / ``road_allowed_for_ai``.
Sticky multi-turn hold is S-LR-A2; TFR/E coach use project edges.
S-LR-C adds dense-pack leader caution, LA race deferral of LR grow, and BA priority.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

Edge = Tuple[int, int]

MAX_LR_PROJECT_EDGES: int = 4
LR_MIN_LENGTH: int = 5
LR_GROW_MIN_GAIN: int = 1
MAX_PATH_EXPANSIONS: int = 200
MAX_LEGAL_EDGES: int = 24
MAX_LR_TURN_SUGGESTIONS: int = 4

# S-LR-C race / dense-pack knobs (tune in playtest)
LR_RACE_CLAIM_EDGES: int = 2
LA_RACE_ARMY_GAP: int = 1
DENSE_PACK_NEAR_DELTA: int = 2
DENSE_PACK_MIN_NEAR_OPPS: int = 2
DENSE_PACK_SOLE_LEADER_VP: int = 8
DENSE_PACK_PACK_FLOOR: int = 6


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _road_key(road: Any) -> Optional[Edge]:
    try:
        from core.outlook_logic import _normalise_road_key

        key = _normalise_road_key(road)
        if isinstance(key, tuple) and len(key) == 2 and key[0] != key[1]:
            return (int(key[0]), int(key[1]))
    except Exception:
        pass
    try:
        if isinstance(road, Mapping):
            for k in ("road_id", "road", "edge", "target_road"):
                if k in road:
                    return _road_key(road.get(k))
            return None
        if isinstance(road, (list, tuple)) and len(road) >= 2:
            a, b = int(road[0]), int(road[1])
            if a == b:
                return None
            return (a, b) if a < b else (b, a)
    except Exception:
        return None
    return None


def _owned_edges(game: Any, player: Any) -> Set[Edge]:
    out: Set[Edge] = set()
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


def _nodes_from_edges(edges: Sequence[Edge]) -> Set[int]:
    nodes: Set[int] = set()
    for e in edges:
        if not e or len(e) < 2:
            continue
        nodes.add(int(e[0]))
        nodes.add(int(e[1]))
    return nodes


def way_wants_longest_road(player: Any) -> bool:
    try:
        from core.ai_road_planner import way_wants_longest_road as _w

        return bool(_w(player))
    except Exception:
        pass
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return False
    if bool(direction.get("longest_road") or direction.get("longest_route")):
        return True
    tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
    return "longest" in tags and "road" in tags


def compute_lr_snapshot(game: Any, player: Any) -> Dict[str, Any]:
    """own_len, holder, opp max, using real continuous lengths."""
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    snap: Dict[str, Any] = {
        "player_id": pid,
        "own_length": 0,
        "max_opp_length": 0,
        "holder_id": None,
        "holder_length": 0,
        "someone_holds": False,
    }
    try:
        from core.longest_road import compute_longest_road_for_player, compute_longest_road_lengths

        own = compute_longest_road_for_player(game, player)
        snap["own_length"] = int(own.length)
        all_lens = compute_longest_road_lengths(game)
        max_opp = 0
        holder_id = None
        holder_len = 0
        for p in list(getattr(game, "players", []) or []):
            if p is None:
                continue
            opid = _safe_int(getattr(p, "id", 0), 0) or 0
            olen = int((all_lens.get(opid) or type(own)(opid)).length)
            if bool(getattr(p, "longest_route_tf", False) or getattr(p, "longest_road_tf", False)):
                snap["someone_holds"] = True
                holder_id = opid
                holder_len = olen
            if opid != pid:
                max_opp = max(max_opp, olen)
        if not snap["someone_holds"]:
            best = 0
            best_id = None
            for opid, res in all_lens.items():
                if int(res.length) > best:
                    best = int(res.length)
                    best_id = opid
            if best >= LR_MIN_LENGTH:
                snap["someone_holds"] = True
                holder_id = best_id
                holder_len = best
        snap["max_opp_length"] = int(max_opp)
        snap["holder_id"] = holder_id
        snap["holder_length"] = int(holder_len)
    except Exception as exc:
        snap["error"] = str(exc)
    return snap


def _player_vp(player: Any) -> int:
    if player is None:
        return 0
    try:
        from core.ai_dcard_timing import victory_points

        return int(victory_points(player))
    except Exception:
        pass
    for attr in ("victory_points", "points", "vp"):
        try:
            return max(0, int(getattr(player, attr) or 0))
        except Exception:
            pass
    return 0


def way_wants_largest_army(player: Any) -> bool:
    """True if preferred way / tags still pursue Largest Army."""
    if player is None:
        return False
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
    if bool(direction.get("biggest_army") or direction.get("largest_army")):
        return True
    tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
    if "largest army" in tags or "biggest army" in tags:
        return True
    if "army" in tags and "largest" in tags:
        return True
    return False


def _army_size(player: Any) -> int:
    try:
        return max(0, int(getattr(player, "size_largest_army", 0) or 0))
    except Exception:
        return 0


def _playable_knight(player: Any) -> bool:
    return _playable_count(player, "knight") > 0


def compute_vp_pack_snapshot(game: Any, player: Any) -> Dict[str, Any]:
    """S-LR-C: VP density for leader-caution soft bias."""
    own = _player_vp(player)
    opp_vps: List[int] = []
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    for opp in list(getattr(game, "players", None) or []):
        if opp is None:
            continue
        opid = _safe_int(getattr(opp, "id", 0), 0) or 0
        if opid == pid:
            continue
        opp_vps.append(_player_vp(opp))
    # Opponents within 1–2 VP of us (catching up or tied pack)
    near_count = sum(1 for v in opp_vps if abs(int(v) - own) <= DENSE_PACK_NEAR_DELTA)
    max_opp = max(opp_vps) if opp_vps else 0
    pack_at_floor = sum(1 for v in opp_vps if v >= DENSE_PACK_PACK_FLOOR)
    sole_leader_risk = bool(
        own >= DENSE_PACK_SOLE_LEADER_VP
        and own > max_opp
        and pack_at_floor >= 1
    )
    dense = bool(
        near_count >= DENSE_PACK_MIN_NEAR_OPPS
        or sole_leader_risk
        or (
            own >= DENSE_PACK_SOLE_LEADER_VP - 1
            and near_count >= 1
            and max_opp >= own - DENSE_PACK_NEAR_DELTA
        )
    )
    return {
        "own_vp": own,
        "opp_vps": list(opp_vps),
        "max_opp_vp": int(max_opp),
        "near_opp_count": int(near_count),
        "dense_pack": bool(dense),
        "sole_leader_risk": bool(sole_leader_risk),
    }


def compute_la_race_state(game: Any, player: Any) -> Dict[str, Any]:
    """S-LR-C: LA race when way wants LA and army gap ≤ LA_RACE_ARMY_GAP."""
    army_ai = _army_size(player)
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    max_opp = 0
    for opp in list(getattr(game, "players", None) or []):
        if opp is None:
            continue
        opid = _safe_int(getattr(opp, "id", 0), 0) or 0
        if opid == pid:
            continue
        max_opp = max(max_opp, _army_size(opp))
    gap = max(0, max_opp - army_ai)
    wants = way_wants_largest_army(player)
    # Race live: way wants LA, both deep enough (own≥2 or opp≥2), gap ≤ knob
    race_gap = abs(army_ai - max_opp) if max_opp or army_ai else 99
    live = bool(
        wants
        and (army_ai >= 2 or max_opp >= 2)
        and race_gap <= LA_RACE_ARMY_GAP
    )
    # Taking LA this knight: own+1 ≥ 3 and own+1 > max_opp
    would_take = bool(army_ai + 1 >= 3 and army_ai + 1 > max_opp)
    return {
        "army_ai": int(army_ai),
        "max_opp_army": int(max_opp),
        "army_gap": int(gap),
        "race_gap": int(race_gap if race_gap != 99 else gap),
        "wants_la": bool(wants),
        "la_race": bool(live),
        "would_take_la": bool(would_take),
        "knight_playable": bool(_playable_knight(player)),
    }


def compute_lr_race_state(
    game: Any,
    player: Any,
    *,
    project: Optional[Mapping[str, Any]] = None,
    rem: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """S-LR-C: LR race when opp length threatens claim window."""
    snap = compute_lr_snapshot(game, player)
    own = int(snap.get("own_length") or 0)
    max_opp = int(snap.get("max_opp_length") or 0)
    holder_id = snap.get("holder_id")
    pid = _safe_int(getattr(player, "id", 0), 0) or 0
    we_hold = bool(holder_id is not None and int(holder_id) == pid) or bool(
        getattr(player, "longest_route_tf", False) or getattr(player, "longest_road_tf", False)
    )
    claim_n = None
    if isinstance(project, Mapping):
        claim_n = project.get("claim_after_n")
        if claim_n is None and project.get("takes_now"):
            claim_n = len(list(project.get("roads_to_build") or []) or [1])
    if rem is not None and claim_n is None:
        # estimate edges left on remaining path
        claim_n = len(list(rem)) if rem else None
    try:
        claim_n_i = int(claim_n) if claim_n is not None else None
    except Exception:
        claim_n_i = None

    # Opp within claim window of min length / beating us
    opp_to_claim = max(0, LR_MIN_LENGTH - max_opp)
    we_to_claim = max(0, LR_MIN_LENGTH - own)
    if we_hold:
        # Opp needs to beat our length
        opp_to_claim = max(0, own + 1 - max_opp)

    # Plan §4.3.3: race when opp length ≥ own (or nearly) *and* someone is inside
    # the claim-edge window — not merely "we could claim first while pack is calm."
    race = False
    contested = bool(max_opp >= own or max_opp >= max(0, own - 1))
    lengths_live = max(own, max_opp) >= max(3, LR_MIN_LENGTH - LR_RACE_CLAIM_EDGES)
    if contested and lengths_live:
        if claim_n_i is not None and claim_n_i <= LR_RACE_CLAIM_EDGES:
            race = True
        if we_to_claim <= LR_RACE_CLAIM_EDGES and max_opp >= own:
            race = True
        if opp_to_claim <= LR_RACE_CLAIM_EDGES:
            race = True
    # Defend / deny: opp can claim or steal soon even if we still lead slightly
    if we_hold and opp_to_claim <= LR_RACE_CLAIM_EDGES and max_opp >= LR_MIN_LENGTH - 1:
        race = True
    if (not we_hold) and opp_to_claim <= LR_RACE_CLAIM_EDGES and max_opp >= LR_MIN_LENGTH - LR_RACE_CLAIM_EDGES:
        race = True

    return {
        "own_length": own,
        "max_opp_length": max_opp,
        "we_hold_lr": bool(we_hold),
        "claim_after_n": claim_n_i,
        "opp_edges_to_claim": int(opp_to_claim),
        "lr_race": bool(race),
        "snapshot": snap,
    }


def assess_leader_caution(
    game: Any,
    player: Any,
    *,
    live_claim: bool = False,
    steals: bool = False,
    project: Optional[Mapping[str, Any]] = None,
    rem: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """S-LR-C: combine dense-pack + race flags for optional-claim deferral."""
    pack = compute_vp_pack_snapshot(game, player)
    la = compute_la_race_state(game, player)
    lr = compute_lr_race_state(game, player, project=project, rem=rem)
    # Optional live claim: dense pack, not LR race, not steal, not already in win paint race
    optional_claim = bool(
        live_claim
        and pack.get("dense_pack")
        and not lr.get("lr_race")
        and not steals
    )
    defer_optional_claim = bool(optional_claim)
    defer_lr_grow_for_la = bool(
        la.get("la_race")
        and (la.get("knight_playable") or la.get("would_take_la"))
        and not live_claim
    )
    return {
        "dense_pack": bool(pack.get("dense_pack")),
        "sole_leader_risk": bool(pack.get("sole_leader_risk")),
        "vp_pack": pack,
        "la_race": bool(la.get("la_race")),
        "la": la,
        "lr_race": bool(lr.get("lr_race")),
        "lr": lr,
        "optional_claim": bool(optional_claim),
        "defer_optional_claim": bool(defer_optional_claim),
        "defer_lr_grow_for_la": bool(defer_lr_grow_for_la),
        "live_claim": bool(live_claim),
        "steals": bool(steals),
    }


def apply_slr_c_action_priority(
    base_priority: Mapping[str, int],
    focus_info: Optional[Mapping[str, Any]] = None,
) -> Dict[str, int]:
    """Elevate BA family from pick_turn_focus / S-LR-C race modes.

    Lower int = higher priority (same convention as continue-plan tables).
    """
    out = {str(k): int(v) for k, v in dict(base_priority or {}).items()}
    if not isinstance(focus_info, Mapping) or not focus_info:
        return out
    focus = str(focus_info.get("focus") or "").lower()
    if focus == "lr":
        out["Build road"] = 0
    elif focus == "city":
        out["Build city"] = 0
        if focus_info.get("defer_optional_claim") or focus_info.get("dense_pack"):
            # Soft demote optional claim road under leader caution
            if "Build road" in out:
                out["Build road"] = max(int(out.get("Build road") or 3), 4)
    elif focus == "la":
        out["Buy development_card"] = 0
        # Defer LR grow while LA race is the BA focus
        if "Build road" in out:
            out["Build road"] = max(int(out.get("Build road") or 3), 5)
    elif focus == "settle":
        out["Build settlement"] = 0
        if "Build road" in out and not focus_info.get("lr_race"):
            # Keep settle-path roads useful
            out["Build road"] = min(int(out.get("Build road") or 2), 1)
    return out


def should_arm_lr_project(game: Any, player: Any) -> bool:
    """Activation A1–A4 (minimal): wants LR, not forced flow, AI only checked by caller."""
    if player is None:
        return False
    if not way_wants_longest_road(player):
        return False
    state = str(getattr(game, "state", "") or "")
    if state in {
        "MoveRobber",
        "RobberMoveRequired",
        "SetRobber",
        "StealSelectOpponent",
        "DiscardPending",
        "AwaitingDiceRoll",
    }:
        return False
    pending_7 = getattr(game, "pending_seven_roll", None)
    if isinstance(pending_7, Mapping) and pending_7.get("active"):
        return False
    return True


def _collect_legal_edges(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Any]] = None,
) -> List[Edge]:
    edges: List[Edge] = []
    seen: Set[Edge] = set()

    def add(raw: Any) -> None:
        key = _road_key(raw)
        if key and key not in seen:
            seen.add(key)
            edges.append(key)

    for c in list(candidates or []):
        add(c)
        if isinstance(c, Mapping):
            for k in ("road_id", "road", "edge", "target_road"):
                if k in c:
                    add(c.get(k))
    if not edges:
        try:
            from core.ai_road_planner import _collect_lr_edge_candidates

            for raw in _collect_lr_edge_candidates(game, player):
                add(raw)
        except Exception:
            pass
    owned = _owned_edges(game, player)
    edges = [e for e in edges if e not in owned]
    return edges[:MAX_LEGAL_EDGES]


def _eval_path(game: Any, player: Any, path: Sequence[Edge]) -> Dict[str, Any]:
    try:
        from core.longest_road import evaluate_lr_claim_after_edges

        return dict(
            evaluate_lr_claim_after_edges(
                game, player, list(path), min_length=LR_MIN_LENGTH
            )
        )
    except Exception as exc:
        return {"takes_now": False, "length_after": 0, "length_now": 0, "error": str(exc)}


def build_lr_project(
    game: Any,
    player: Any,
    candidates: Optional[Sequence[Any]] = None,
    *,
    max_edges: int = MAX_LR_PROJECT_EDGES,
) -> Dict[str, Any]:
    """Prefer: (1) 1-edge live claim, (2) shortest claim path, (3) max length-gain.

    Empty dict = no project.
    """
    if not should_arm_lr_project(game, player):
        return {}

    owned = _owned_edges(game, player)
    legal = _collect_legal_edges(game, player, candidates)
    if not legal:
        return {}

    snap = compute_lr_snapshot(game, player)
    own_now = int(snap.get("own_length") or 0)
    max_depth = max(1, min(int(max_edges or MAX_LR_PROJECT_EDGES), MAX_LR_PROJECT_EDGES))

    # --- (1) Live single-edge claim ---
    live_claim_project: Optional[Dict[str, Any]] = None
    for e in legal:
        ev = _eval_path(game, player, [e])
        if bool(ev.get("takes_now")):
            live_claim_project = _project_dict(
                kind="lr_claim",
                roads=[e],
                snap=snap,
                ev=ev,
                route_source="slr_live_claim",
                strategy_reason="S-LR-A: live Longest Road claim/steal edge",
            )
            # S-LR-C: under dense pack + optional (no race / steal), fall through to
            # prefer a grow-not-claim path if one exists; else keep claim project.
            try:
                caution = assess_leader_caution(
                    game,
                    player,
                    live_claim=True,
                    steals=bool(ev.get("steals")),
                    project=live_claim_project,
                    rem=[e],
                )
                if not caution.get("defer_optional_claim"):
                    return live_claim_project
                live_claim_project["strategy_reason"] = (
                    "S-LR-C: live claim available (dense-pack optional; prefer grow if any)"
                )
                live_claim_project["optional_under_dense_pack"] = True
            except Exception:
                return live_claim_project
            break

    # --- (2)/(3) Multi-edge BFS attached to owned graph ---
    if not owned and not legal:
        return {}

    # Seed nodes: owned graph; if no owned roads, allow any legal edge as start
    base_nodes = _nodes_from_edges(list(owned))
    best: Optional[Dict[str, Any]] = None
    best_score: Optional[Tuple] = None
    best_grow: Optional[Dict[str, Any]] = None
    best_grow_score: Optional[Tuple] = None
    dense_optional = bool(
        live_claim_project and live_claim_project.get("optional_under_dense_pack")
    )

    # queue items: (path_list, nodes, used_set)
    from collections import deque

    q: Any = deque()
    if base_nodes:
        q.append(([], set(base_nodes), set()))
    else:
        # No owned roads: each legal edge can start a path
        for e in legal:
            q.append(([], set(), set()))
        # degenerate: try each single edge as path start below via empty nodes + touch check

    expansions = 0
    # Also seed empty path with empty nodes if no owned — handled by allowing
    # first edge freely when base_nodes empty
    if not base_nodes:
        q.clear()
        q.append(([], set(), set()))

    while q and expansions < MAX_PATH_EXPANSIONS:
        path, nodes, used = q.popleft()
        if len(path) >= max_depth:
            continue
        for e in legal:
            if e in used:
                continue
            # Must attach to current component (or free start if no nodes yet)
            if nodes and e[0] not in nodes and e[1] not in nodes:
                continue
            if not nodes and path:
                continue
            new_path = list(path) + [e]
            expansions += 1
            if expansions > MAX_PATH_EXPANSIONS:
                break
            ev = _eval_path(game, player, new_path)
            length_after = int(ev.get("length_after") or 0)
            takes = bool(ev.get("takes_now"))
            gain = length_after - own_now
            # claim_after_n estimate: path length if takes, else large
            claim_n = len(new_path) if takes else 99
            # score: prefer takes, fewer edges to claim, more length, fewer edges
            score = (
                0 if takes else 1,
                claim_n,
                -length_after,
                -gain,
                len(new_path),
            )
            eligible = takes or gain >= LR_GROW_MIN_GAIN
            if eligible and (best_score is None or score < best_score):
                best_score = score
                kind = "lr_claim" if takes else "lr_grow"
                best = _project_dict(
                    kind=kind,
                    roads=new_path,
                    snap=snap,
                    ev=ev,
                    route_source="slr_grow" if not takes else "slr_claim_path",
                    strategy_reason=(
                        "S-LR-A: multi-edge path claims LR"
                        if takes
                        else f"S-LR-A: grow continuous length +{gain}"
                    ),
                )
            # Track pure grow for S-LR-C dense optional claim
            if (not takes) and gain >= LR_GROW_MIN_GAIN:
                grow_score = (-length_after, -gain, len(new_path))
                if best_grow_score is None or grow_score < best_grow_score:
                    best_grow_score = grow_score
                    best_grow = _project_dict(
                        kind="lr_grow",
                        roads=new_path,
                        snap=snap,
                        ev=ev,
                        route_source="slr_grow_dense",
                        strategy_reason=(
                            f"S-LR-C: grow continuous length +{gain} "
                            "(dense-pack grow-not-claim)"
                        ),
                    )
            # Prefer shorter claim paths: if we already have a 1-edge claim we returned;
            # stop expanding past a found claim with longer paths of worse score
            new_nodes = set(nodes) | {e[0], e[1]}
            new_used = set(used) | {e}
            if len(new_path) < max_depth:
                q.append((new_path, new_nodes, new_used))

    # S-LR-C: dense-pack optional live claim → prefer pure grow if any, else claim
    if dense_optional and live_claim_project:
        if best_grow:
            out = dict(best_grow)
            out["deferred_live_claim"] = live_claim_project
            return out
        return dict(live_claim_project)

    if live_claim_project and not best:
        return dict(live_claim_project)

    return dict(best or {})


def _project_dict(
    *,
    kind: str,
    roads: Sequence[Edge],
    snap: Mapping[str, Any],
    ev: Mapping[str, Any],
    route_source: str,
    strategy_reason: str,
) -> Dict[str, Any]:
    road_list = [list(e) for e in roads]
    next_road = road_list[0] if road_list else None
    takes = bool(ev.get("takes_now"))
    claim_after_n = len(road_list) if takes else None
    # estimate edges to claim if not takes: leave None or heuristic
    if not takes:
        claim_after_n = None
    return {
        "kind": str(kind),
        "roads_to_build": road_list,
        "next_road": next_road,
        "expected_length_after": int(ev.get("length_after") or 0),
        "claim_after_n": claim_after_n,
        "own_length_now": int(snap.get("own_length") or ev.get("length_now") or 0),
        "holder_id": snap.get("holder_id"),
        "holder_length": int(snap.get("holder_length") or 0),
        "max_opp_length": int(snap.get("max_opp_length") or 0),
        "gap": max(
            0,
            LR_MIN_LENGTH - int(snap.get("own_length") or 0),
        ),
        "takes_now": takes,
        "steals": bool(ev.get("steals")),
        "first_claim": bool(ev.get("first_claim")),
        "route_source": route_source,
        "strategy_reason": strategy_reason,
        "target_label": "LR claim" if kind == "lr_claim" else "LR grow",
        "blocked": False,
        "sticky_version": 1,
    }


def lr_project_to_road_plan(project: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Shape compatible with ``build_ai_road_plan`` consumers."""
    if not isinstance(project, Mapping) or not project:
        return {}
    roads = []
    for r in list(project.get("roads_to_build") or []):
        key = _road_key(r)
        if key:
            roads.append(key)
    if not roads:
        return {}
    kind = str(project.get("kind") or "lr_grow")
    return {
        "kind": kind,
        "roads_to_build": roads,
        "next_road": roads[0],
        "route_source": project.get("route_source") or "slr_project",
        "strategy_reason": project.get("strategy_reason") or "S-LR-A LR project",
        "target_label": project.get("target_label") or "LR",
        "blocked": False,
        "lr_project": dict(project),
        "claim_after_n": project.get("claim_after_n"),
        "expected_length_after": project.get("expected_length_after"),
    }


def get_stored_lr_project(player: Any, game: Any = None) -> Dict[str, Any]:
    """Read LR project from sticky / player / game (A2-ready; used by allowlist)."""
    if player is not None:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            proj = sticky.get("lr_project")
            if isinstance(proj, Mapping) and proj.get("roads_to_build"):
                return dict(proj)
        proj = getattr(player, "lr_project", None)
        if isinstance(proj, Mapping) and proj.get("roads_to_build"):
            return dict(proj)
        direction = getattr(player, "strategic_direction", None)
        if isinstance(direction, Mapping):
            proj = direction.get("lr_project")
            if isinstance(proj, Mapping) and proj.get("roads_to_build"):
                return dict(proj)
    if game is not None:
        proj = getattr(game, "last_lr_project", None)
        if isinstance(proj, Mapping) and proj.get("roads_to_build"):
            # Only if same player
            try:
                if int(proj.get("player_id") or 0) in (
                    0,
                    int(getattr(player, "id", 0) or 0),
                ):
                    return dict(proj)
            except Exception:
                return dict(proj)
    return {}


def remaining_lr_project_roads(game: Any, player: Any) -> List[Edge]:
    """Project edges not yet owned (allowlist for S5a)."""
    proj = get_stored_lr_project(player, game)
    if not proj:
        return []
    owned = _owned_edges(game, player)
    out: List[Edge] = []
    for r in list(proj.get("roads_to_build") or []):
        key = _road_key(r)
        if key and key not in owned and key not in out:
            out.append(key)
    return out


def tfr_edges_from_lr_project(
    game: Any,
    player: Any,
    *,
    free_n: int = 2,
) -> List[List[int]]:
    """S-LR-B: ordered free-road edges for TFR from the LR project.

    Prefer the **shortest prefix** of remaining project edges that claims/steals
    LR (engine). Otherwise return up to ``free_n`` project edges for grow.
    Empty if no project / no remaining edges.
    """
    free_n = max(0, min(2, int(free_n or 0)))
    if free_n <= 0:
        return []
    rem = remaining_lr_project_roads(game, player)
    if not rem:
        return []
    # Minimal claim prefix — then pad to free_n so TFR still places both free
    # roads when the project has more edges (WP-TFR1 / Dig n3d Orange R3).
    claim_n = None
    for n in range(1, min(free_n, len(rem)) + 1):
        prefix = rem[:n]
        ev = _eval_path(game, player, prefix)
        if bool(ev.get("takes_now")):
            claim_n = n
            break
    if claim_n is not None:
        take = min(free_n, len(rem))
        return [list(e) for e in rem[:take]]
    # Grow: take up to free_n project edges
    return [list(e) for e in rem[:free_n]]


def store_lr_project(
    game: Any,
    player: Any,
    project: Mapping[str, Any],
    *,
    merge_sticky: bool = True,
) -> None:
    """Runtime attach for allowlist / Phase0; S-LR-A2 merges into sticky portfolio."""
    if not isinstance(project, Mapping) or not project:
        return
    data = dict(project)
    try:
        data["player_id"] = int(getattr(player, "id", 0) or 0)
    except Exception:
        pass
    # Trim owned edges
    rem = []
    owned = _owned_edges(game, player)
    for r in list(data.get("roads_to_build") or []):
        key = _road_key(r)
        if key and key not in owned:
            rem.append(list(key))
    if rem:
        data["roads_to_build"] = rem
        data["next_road"] = list(rem[0])
    try:
        if player is not None:
            setattr(player, "lr_project", data)
    except Exception:
        pass
    try:
        if game is not None:
            setattr(game, "last_lr_project", data)
    except Exception:
        pass
    if merge_sticky and player is not None:
        try:
            merge_lr_project_into_sticky(player, data, game=game)
        except Exception:
            pass


def refresh_lr_project_roads(
    game: Any,
    player: Any,
    project: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Drop owned edges; empty dict if nothing left."""
    proj = dict(project or get_stored_lr_project(player, game) or {})
    if not proj:
        return {}
    owned = _owned_edges(game, player)
    rem: List[List[int]] = []
    for r in list(proj.get("roads_to_build") or []):
        key = _road_key(r)
        if key and key not in owned:
            rem.append(list(key))
    if not rem:
        return {}
    proj["roads_to_build"] = rem
    proj["next_road"] = list(rem[0])
    return proj


def should_invalidate_lr_project(
    game: Any,
    player: Any,
    project: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
    """S-LR-A2: when to drop the LR project (city lock can remain)."""
    proj = dict(project or get_stored_lr_project(player, game) or {})
    if not proj or not proj.get("roads_to_build"):
        return True, "no_lr_project"
    # Way no longer wants LR
    if not way_wants_longest_road(player):
        return True, "way_kill_lr"
    # Own claim already held and project was claim-only with nothing left to grow
    try:
        if bool(getattr(player, "longest_route_tf", False) or getattr(player, "longest_road_tf", False)):
            # Still allow grow if project improves length, but if takes_now was only goal and we hold — drop
            rem = remaining_lr_project_roads(game, player)
            if not rem:
                return True, "own_longest_road"
    except Exception:
        pass
    refreshed = refresh_lr_project_roads(game, player, proj)
    if not refreshed:
        # All edges built — check if we claimed
        try:
            if bool(getattr(player, "longest_route_tf", False)):
                return True, "own_longest_road"
        except Exception:
            pass
        return True, "lr_route_complete"
    # Path hopeless: remaining path cannot beat holder
    rem_keys = remaining_lr_project_roads(game, player)
    if rem_keys:
        ev = _eval_path(game, player, rem_keys)
        length_after = int(ev.get("length_after") or 0)
        snap = compute_lr_snapshot(game, player)
        holder_len = int(snap.get("holder_length") or 0)
        someone = bool(snap.get("someone_holds"))
        hold_id = snap.get("holder_id")
        pid = _safe_int(getattr(player, "id", 0), 0)
        if someone and hold_id is not None and hold_id != pid:
            if length_after <= holder_len and length_after < LR_MIN_LENGTH:
                return True, "lr_race_lost"
            if length_after <= holder_len and not bool(ev.get("takes_now")):
                # still might grow later with longer path — only kill if full project can't win
                if length_after <= holder_len:
                    # If max path length still <= holder, lost
                    if length_after <= holder_len and len(rem_keys) >= MAX_LR_PROJECT_EDGES:
                        return True, "lr_race_lost"
        # Re-eval takes_now with full remaining — if we already hold LR and no grow, ok
    return False, "hold"


def merge_lr_project_into_sticky(
    player: Any,
    project: Mapping[str, Any],
    *,
    game: Any = None,
) -> Dict[str, Any]:
    """S-LR-A2: attach LR project without wiping city/settle locks."""
    data = refresh_lr_project_roads(game, player, project) or dict(project)
    if not data.get("roads_to_build"):
        return {}
    raw = getattr(player, "sticky_commitment", None)
    commitment: Dict[str, Any] = dict(raw) if isinstance(raw, Mapping) else {}
    commitment["lr_project"] = data
    commitment["sticky_version"] = max(3, int(commitment.get("sticky_version") or 0) or 3)
    # Portfolio focus hint: keep C/S if present; else LR
    if commitment.get("locked_rec_target_id") is None and not commitment.get("locked_target_kind"):
        commitment["locked_target_kind"] = "LR"
    # Roads for guards: prefer settle path if set, else LR remaining
    if not commitment.get("locked_roads_to_build"):
        commitment["locked_roads_to_build"] = list(data.get("roads_to_build") or [])
    try:
        setattr(player, "sticky_commitment", commitment)
        setattr(player, "lr_project", data)
    except Exception:
        pass
    return commitment


def clear_lr_project_from_sticky(player: Any, game: Any = None) -> None:
    """Drop LR project; keep city/settle locks."""
    try:
        if player is not None:
            setattr(player, "lr_project", None)
    except Exception:
        pass
    try:
        if game is not None:
            # only clear last if same player
            last = getattr(game, "last_lr_project", None)
            if isinstance(last, Mapping):
                if int(last.get("player_id") or 0) == int(getattr(player, "id", 0) or 0):
                    setattr(game, "last_lr_project", None)
    except Exception:
        pass
    raw = getattr(player, "sticky_commitment", None)
    if not isinstance(raw, Mapping):
        return
    commitment = dict(raw)
    commitment.pop("lr_project", None)
    # If only LR was the commitment, clear sticky entirely
    if commitment.get("locked_rec_target_id") is None and not commitment.get("locked_roads_to_build"):
        try:
            setattr(player, "sticky_commitment", None)
        except Exception:
            pass
        return
    try:
        setattr(player, "sticky_commitment", commitment)
    except Exception:
        pass


def apply_lr_project_to_direction(
    direction: Mapping[str, Any],
    player: Any,
    game: Any = None,
) -> Dict[str, Any]:
    """Copy LR project fields onto strategic_direction for UI / planner."""
    out = dict(direction or {})
    proj = get_stored_lr_project(player, game)
    if not proj:
        return out
    refreshed = refresh_lr_project_roads(game, player, proj)
    if not refreshed:
        return out
    out["lr_project"] = refreshed
    out["lr_roads_to_build"] = list(refreshed.get("roads_to_build") or [])
    # Don't overwrite settle path roads_to_build if settle-focused; attach parallel field
    if not out.get("roads_to_build") or str(out.get("locked_target_kind") or "").upper() == "LR":
        out["roads_to_build"] = list(refreshed.get("roads_to_build") or [])
    out["longest_road"] = True
    tags = list(out.get("tags") or [])
    tag_text = " ".join(str(t).lower() for t in tags)
    if "longest" not in tag_text:
        tags.append("Longest Road")
        out["tags"] = tags
    return out


def pick_turn_focus(
    game: Any,
    player: Any,
    *,
    city_legal: Optional[bool] = None,
    city_affordable: Optional[bool] = None,
    settle_legal: Optional[bool] = None,
    road_legal: Optional[bool] = None,
    knight_legal: Optional[bool] = None,
    buy_dcard_legal: Optional[bool] = None,
) -> Dict[str, Any]:
    """This-turn focus (city|lr|settle|la|pass) without wiping portfolio.

    S-LR-A2 base + S-LR-C race/dense-pack (§4.3.3–4.3.5):
      win-now (caller) → mandatory live LR claim → city efficiency →
      LA race (knight/DCard) before LR grow → settle → LR grow → fallbacks.
    Dense pack makes optional claims defer to city.
    """
    result: Dict[str, Any] = {
        "focus": "pass",
        "reason": "default",
        "lr_project": get_stored_lr_project(player, game),
        "dense_pack": False,
        "la_race": False,
        "lr_race": False,
        "defer_optional_claim": False,
        "defer_lr_grow_for_la": False,
    }
    direction = {}
    try:
        d = getattr(player, "strategic_direction", None)
        if isinstance(d, Mapping):
            direction = dict(d)
    except Exception:
        pass

    # Scan fallbacks
    def _has_action(substr: str) -> bool:
        for attr in ("current_actionable_choices", "current_execution_choices"):
            for row in list(getattr(game, attr, None) or []):
                if not isinstance(row, Mapping):
                    continue
                name = str(row.get("action") or "").lower()
                if substr in name and bool(row.get("viable", row.get("actionable", True))):
                    return True
        return False

    if city_legal is None:
        city_legal = _has_action("city")
    if settle_legal is None:
        settle_legal = _has_action("settlement")
    if road_legal is None:
        road_legal = _has_action("road")
    if buy_dcard_legal is None:
        buy_dcard_legal = _has_action("development")
    if knight_legal is None:
        knight_legal = bool(_playable_knight(player))

    # Live LR claim detection
    proj = result["lr_project"]
    rem = remaining_lr_project_roads(game, player) if proj else []
    live_claim = False
    steals = False
    if rem:
        ev = _eval_path(game, player, rem[:1])
        live_claim = bool(ev.get("takes_now"))
        steals = bool(ev.get("steals"))
    if not live_claim and rem:
        try:
            from core.ai_road_planner import road_is_live_lr_claim_edge

            live_claim = bool(road_is_live_lr_claim_edge(game, player, rem[0]))
        except Exception:
            pass
    if isinstance(proj, Mapping):
        if proj.get("takes_now") and (not rem or len(rem) <= 1):
            live_claim = live_claim or bool(proj.get("takes_now"))
        steals = steals or bool(proj.get("steals"))

    caution = assess_leader_caution(
        game,
        player,
        live_claim=bool(live_claim),
        steals=bool(steals),
        project=proj if isinstance(proj, Mapping) else None,
        rem=rem,
    )
    result.update(
        {
            "dense_pack": bool(caution.get("dense_pack")),
            "la_race": bool(caution.get("la_race")),
            "lr_race": bool(caution.get("lr_race")),
            "defer_optional_claim": bool(caution.get("defer_optional_claim")),
            "defer_lr_grow_for_la": bool(caution.get("defer_lr_grow_for_la")),
            "optional_claim": bool(caution.get("optional_claim")),
            "caution": caution,
        }
    )

    # City want signal (portfolio)
    wants_city = False
    try:
        rem_c = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
        wants_city = int((rem_c or {}).get("cities") or 0) > 0
        tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
        if "city" in tags:
            wants_city = True
        if "city" in str(direction.get("supporting_action_type") or "").lower():
            wants_city = True
    except Exception:
        pass
    sticky = getattr(player, "sticky_commitment", None)
    if isinstance(sticky, Mapping):
        if str(sticky.get("locked_target_kind") or "").upper() in ("C", "CITY"):
            wants_city = True
        if sticky.get("locked_rec_target_id") is not None and str(
            sticky.get("locked_target_kind") or ""
        ).upper() in ("C", "CITY", ""):
            if sticky.get("city_upgrade_target_id") or str(sticky.get("locked_target_kind") or "").upper() == "C":
                wants_city = True

    city_ready = bool(wants_city and city_legal and city_affordable is not False)

    # 1) Mandatory live LR claim (race / steal / not optional dense deferral)
    if live_claim and (road_legal or rem):
        if caution.get("defer_optional_claim") and city_ready:
            result.update(
                {
                    "focus": "city",
                    "reason": "dense_pack_defer_optional_claim",
                }
            )
            return result
        result.update({"focus": "lr", "reason": "live_lr_claim"})
        return result

    # 2) City efficiency when legal
    if city_ready:
        reason = "city_legal_efficiency"
        if caution.get("dense_pack"):
            reason = "city_dense_pack_efficiency"
        result.update({"focus": "city", "reason": reason})
        return result

    # 3) LA race: knight / DCard path before LR grow (project stays sticky)
    la_path_live = bool(knight_legal or buy_dcard_legal or caution.get("la", {}).get("knight_playable"))
    if caution.get("la_race") and la_path_live and not live_claim:
        result.update(
            {
                "focus": "la",
                "reason": "la_race_defer_lr_grow",
                "defer_lr_grow_for_la": True,
            }
        )
        return result

    # 4) Settle path
    wants_settle = "settle" in str(direction.get("supporting_action_type") or "").lower()
    if settle_legal and wants_settle and not live_claim:
        result.update({"focus": "settle", "reason": "settle_path"})
        return result

    # 5) LR grow (deferred when LA race already handled above)
    if rem and not caution.get("defer_lr_grow_for_la"):
        result.update({"focus": "lr", "reason": "lr_project_grow"})
        return result
    if rem and caution.get("la_race") and not la_path_live:
        # LA race but no knight/DCard this turn — allow grow
        result.update({"focus": "lr", "reason": "lr_grow_la_path_cold"})
        return result

    # Fallbacks
    if city_legal:
        result.update({"focus": "city", "reason": "city_fallback"})
        return result
    if settle_legal:
        result.update({"focus": "settle", "reason": "settle_fallback"})
        return result
    if road_legal or rem:
        result.update({"focus": "lr", "reason": "road_legal_fallback"})
        return result
    if buy_dcard_legal or knight_legal:
        result.update({"focus": "la", "reason": "dcard_fallback"})
        return result
    result.update({"focus": "pass", "reason": "nothing_legal"})
    return result


# Resource order matches player_trade / hand vectors: Wh, O, Wd, B, Sh
_RES_WD, _RES_B, _RES_SH = 2, 3, 4


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


def _playable_count(player: Any, card_type: str) -> int:
    if player is None:
        return 0
    ct = str(card_type or "")
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            row_list = list(row or [])
            if not row_list:
                continue
            if str(row_list[0]) != ct:
                continue
            while len(row_list) < 4:
                row_list.append(0)
            return max(0, int(row_list[2] or 0))
    except Exception:
        pass
    try:
        return sum(1 for c in (getattr(player, "development_cards", []) or []) if str(c) == ct)
    except Exception:
        return 0


def _road_affordable(hand: Sequence[int], n: int = 1) -> bool:
    n = max(1, int(n or 1))
    return int(hand[_RES_WD] or 0) >= n and int(hand[_RES_B] or 0) >= n


def _missing_for_roads(hand: Sequence[int], n: int = 1) -> Dict[str, int]:
    n = max(1, int(n or 1))
    need_wd = max(0, n - int(hand[_RES_WD] or 0))
    need_b = max(0, n - int(hand[_RES_B] or 0))
    out: Dict[str, int] = {}
    if need_wd:
        out["Wd"] = need_wd
    if need_b:
        out["B"] = need_b
    return out


def _format_edge(edge: Any) -> str:
    key = _road_key(edge)
    if not key:
        return "?"
    return f"[{key[0]}-{key[1]}]"


def build_lr_turn_suggestions(
    game: Any,
    player: Any,
    *,
    project: Optional[Mapping[str, Any]] = None,
    focus: Optional[str] = None,
    max_suggestions: int = MAX_LR_TURN_SUGGESTIONS,
) -> List[Dict[str, Any]]:
    """S-LR-E: ranked coach actions for advancing the LR project this turn.

    Does not execute multi-step scripts. Codes are fixed (see plan §5.8).
    """
    proj = dict(project or get_stored_lr_project(player, game) or {})
    rem = remaining_lr_project_roads(game, player)
    if not rem and not proj:
        # Still may hold_wait_city with empty project if focus city — skip
        return []

    if focus is None:
        try:
            focus = str(pick_turn_focus(game, player).get("focus") or "pass")
        except Exception:
            focus = "pass"
    focus = str(focus or "pass").lower()

    hand = _hand_vector5(player)
    tfr_n = _playable_count(player, "two_free_roads")
    yop_n = _playable_count(player, "year_of_plenty")
    mono_n = _playable_count(player, "monopoly")

    next_edge = rem[0] if rem else None
    n_rem = len(rem)
    live_claim_1 = False
    if next_edge:
        ev1 = _eval_path(game, player, [next_edge])
        live_claim_1 = bool(ev1.get("takes_now"))
    tfr_edges = tfr_edges_from_lr_project(game, player, free_n=2) if rem else []
    tfr_claims = False
    if tfr_edges:
        tfr_claims = bool(_eval_path(game, player, [_road_key(e) for e in tfr_edges if _road_key(e)]).get("takes_now"))

    missing_1 = _missing_for_roads(hand, 1)
    missing_2 = _missing_for_roads(hand, min(2, max(1, n_rem)))
    can_road_1 = _road_affordable(hand, 1) and next_edge is not None
    can_road_2 = _road_affordable(hand, 2) and n_rem >= 2

    # City id for hold label
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
        edges: Any = None,
        resources: Any = None,
        secondary: bool = False,
    ) -> None:
        candidates.append(
            {
                "action": action,
                "label": label,
                "rank": int(rank),
                "reason": reason,
                "edges": edges,
                "resources": resources,
                "secondary": bool(secondary),
            }
        )

    # --- Catalog ---
    if focus == "city" and (city_id is not None or True):
        cid = city_id if city_id is not None else "?"
        add(
            "hold_wait_city",
            f"Hold LR; city first (C@{cid})",
            rank=5 if rem else 1,
            reason="city_efficiency_focus",
            secondary=False,
        )

    if live_claim_1 and next_edge:
        if can_road_1:
            add(
                "build_road_next",
                f"Road {_format_edge(next_edge)} (LR claim now)",
                rank=1,
                reason="live_claim_paid_road",
                edges=[list(next_edge)],
            )
        if tfr_n > 0:
            add(
                "play_tfr",
                f"Play TFR → free road {_format_edge(next_edge)} (LR claim)",
                rank=1,
                reason="live_claim_tfr",
                edges=[list(next_edge)],
            )

    if tfr_n > 0 and tfr_edges and not live_claim_1:
        n_free = len(tfr_edges)
        label = (
            f"Play TFR → {n_free} free road(s) on LR path"
            + (" (claim)" if tfr_claims else "")
        )
        add(
            "play_tfr",
            label,
            rank=2 if tfr_claims or n_rem >= 2 else 4,
            reason="tfr_project_edges",
            edges=[list(_road_key(e) or e) for e in tfr_edges],
        )

    if next_edge and can_road_1 and not live_claim_1:
        claim_in = n_rem if n_rem else "?"
        add(
            "build_road_next",
            f"Road {_format_edge(next_edge)} (LR +1, {claim_in} left)",
            rank=3,
            reason="paid_next_project_edge",
            edges=[list(next_edge)],
        )

    if yop_n > 0 and missing_1 and n_rem >= 1:
        parts = "+".join(f"{v}{k}" if v > 1 else k for k, v in missing_1.items())
        # Prefer Wd+B phrasing
        if set(missing_1.keys()) <= {"Wd", "B"}:
            parts = "+".join(k for k in ("Wd", "B") if k in missing_1)
        add(
            "play_yop_road_res",
            f"Play YOP → {parts} for LR roads",
            rank=4,
            reason="yop_fund_next_edge",
            resources=dict(missing_1),
        )

    if mono_n > 0 and n_rem >= 2 and (missing_2 or not can_road_2):
        # Bottleneck resource for multi-road
        if int(hand[_RES_SH] or 0) < 2 and (missing_2.get("Wd") or missing_2.get("B")):
            add(
                "play_mono_sheep",
                "Play Monopoly → Sheep (fund roads)",
                rank=5,
                reason="mono_sheep_multi_road",
                resources={"Sh": "bank"},
            )
        elif missing_2.get("Wd", 0) >= missing_2.get("B", 0) and missing_2.get("Wd", 0) > 0:
            add(
                "play_mono_wood",
                "Play Monopoly → Wd (fund roads)",
                rank=5,
                reason="mono_wood_bottleneck",
                resources={"Wd": "bank"},
            )
        elif missing_2.get("B", 0) > 0:
            add(
                "play_mono_brick",
                "Play Monopoly → B (fund roads)",
                rank=5,
                reason="mono_brick_bottleneck",
                resources={"B": "bank"},
            )

    # TwB unlock: if missing exactly for 1 road and have surplus other goods — hint only
    if missing_1 and next_edge and not can_road_1:
        add(
            "twb_unlock_road",
            f"TwB → complete road cost for {_format_edge(next_edge)}",
            rank=6,
            reason="twb_hint_road_cost",
            resources=dict(missing_1),
            edges=[list(next_edge)],
        )

    if can_road_2 or (n_rem >= 2 and sum(hand) >= 4):
        add(
            "buy_roads_min_n",
            f"Buy min {min(2, n_rem)} roads (LR project)",
            rank=7,
            reason="multi_road_plan_hint",
            edges=[list(e) for e in rem[:2]],
        )

    # When focus is city, mark LR actions secondary and boost hold_wait_city
    if focus == "city":
        for c in candidates:
            if c.get("action") == "hold_wait_city":
                c["rank"] = 0
                c["secondary"] = False
            else:
                c["secondary"] = True
                c["rank"] = int(c.get("rank") or 9) + 10
                # Prefixed label for PLAN
                if not str(c.get("label") or "").startswith("After city"):
                    c["label"] = f"After city: {c.get('label')}"
    elif focus == "lr":
        for c in candidates:
            if c.get("action") == "hold_wait_city":
                c["rank"] = 20
                c["secondary"] = True

    candidates.sort(key=lambda c: (int(c.get("rank") or 99), str(c.get("action") or "")))
    # Deduplicate by action keeping best rank
    seen_act = set()
    out: List[Dict[str, Any]] = []
    for c in candidates:
        act = str(c.get("action") or "")
        if act in seen_act:
            continue
        seen_act.add(act)
        out.append(c)
        if len(out) >= max(1, int(max_suggestions or MAX_LR_TURN_SUGGESTIONS)):
            break

    # Store for Phase0 / UI
    try:
        if game is not None:
            setattr(game, "last_lr_turn_suggestions", list(out))
        if player is not None:
            setattr(player, "lr_turn_suggestions", list(out))
    except Exception:
        pass
    return out


def format_lr_suggestions_lines(
    suggestions: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    max_lines: int = 2,
) -> List[str]:
    """PLAN/DBG lines from suggestion list."""
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
            rows.append("LR: " + " · ".join(labels)[:62])
    if secondary and len(rows) < max_lines:
        labels = [str(s.get("label") or "") for s in secondary[:2]]
        labels = [x for x in labels if x]
        if labels:
            rows.append(_fit62(" · ".join(labels)))
    return rows[: max(1, int(max_lines or 2))]


def _fit62(text: str) -> str:
    t = str(text or "")
    return t if len(t) <= 62 else t[:59] + "..."


def ensure_lr_project_sticky(
    game: Any,
    player: Any,
    *,
    candidates: Optional[Sequence[Any]] = None,
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    """S-LR-A2: hold/refresh or arm LR project on sticky portfolio.

    Returns meta: {held, armed, invalidated, reason, project}.
    """
    meta: Dict[str, Any] = {
        "held": False,
        "armed": False,
        "invalidated": False,
        "reason": "",
        "project": {},
    }
    if player is None or not should_arm_lr_project(game, player):
        # Drop LR if way no longer wants it
        if get_stored_lr_project(player, game):
            inv, reason = should_invalidate_lr_project(game, player)
            if inv:
                clear_lr_project_from_sticky(player, game)
                meta.update({"invalidated": True, "reason": reason or "not_armed"})
        return meta

    existing = get_stored_lr_project(player, game)
    if existing and not force_rebuild:
        inv, reason = should_invalidate_lr_project(game, player, existing)
        if inv:
            clear_lr_project_from_sticky(player, game)
            meta["invalidated"] = True
            meta["reason"] = reason
            existing = {}
        else:
            refreshed = refresh_lr_project_roads(game, player, existing)
            if refreshed:
                store_lr_project(game, player, refreshed, merge_sticky=True)
                meta.update({"held": True, "reason": "lr_hold", "project": refreshed})
                return meta
            clear_lr_project_from_sticky(player, game)
            meta["invalidated"] = True
            meta["reason"] = "lr_route_complete"
            existing = {}

    # Arm fresh project
    project = build_lr_project(game, player, candidates)
    if project:
        store_lr_project(game, player, project, merge_sticky=True)
        meta.update({"armed": True, "reason": "lr_arm", "project": dict(project)})
    else:
        meta["reason"] = "no_lr_path"
    return meta


__all__ = [
    "DENSE_PACK_NEAR_DELTA",
    "LA_RACE_ARMY_GAP",
    "LR_MIN_LENGTH",
    "LR_RACE_CLAIM_EDGES",
    "MAX_LR_PROJECT_EDGES",
    "MAX_LR_TURN_SUGGESTIONS",
    "apply_lr_project_to_direction",
    "apply_slr_c_action_priority",
    "assess_leader_caution",
    "build_lr_project",
    "build_lr_turn_suggestions",
    "clear_lr_project_from_sticky",
    "compute_la_race_state",
    "compute_lr_race_state",
    "compute_lr_snapshot",
    "compute_vp_pack_snapshot",
    "ensure_lr_project_sticky",
    "format_lr_suggestions_lines",
    "get_stored_lr_project",
    "lr_project_to_road_plan",
    "merge_lr_project_into_sticky",
    "pick_turn_focus",
    "refresh_lr_project_roads",
    "remaining_lr_project_roads",
    "should_arm_lr_project",
    "should_invalidate_lr_project",
    "store_lr_project",
    "tfr_edges_from_lr_project",
    "way_wants_largest_army",
    "way_wants_longest_road",
]
