"""Multi-path / LR road choice (playboard-first).

Operator body (`docs/placeholders.txt` / `docs/P3_optimizers_spec.md`):

  (a) Toward a settle target — prefer path that
        (i)  defends own build strategy toward the target,
        (ii) blocks opponent path expansion (also helps LR contests),
        (iii) increases own path length (LR).

  (b) Sole purpose LR — prefer road that
        (i)  connects independent clusters when that supports LR, or
        (ii) increases expansion capability while avoiding tips opponents
             can easily block.

LR-priority pre-steps before answering (``prepare_lr_road_decision``):
  1) **This-turn claimability** — can LR be gained this turn? May call
     ``rcard_optimizer`` (TwB/TwP unlock roads) and ``dcard_optimizer``
     (TFR held? DCard still playable this turn?).
  2) **Post-LR next target** — ask ``strategy_coordinator.post_lr_settle_tips``
     (PLN2 / sticky shortlist) so dual-purpose roads can serve the next S/C.

Future board-only tasks (not implemented yet — keep scoring playboard-bound):
  3) Opponent (re)claim opportunities — edges that cut opp max path / deny.
  4) Future path-length growth — cluster connect / safe tip expand.
  5) Board-only LR race threat from playboard configuration (no hand god-view).

SE / coordinator (future, not this module): knowing current path_length,
potential path_length, and roads_to_build, assess whether LR + new-settlement
can combine, whether LR must race, whether to maximize length, and/or which
opponent to block — then pass a policy bag into the optimizer.

Related live code:
  - ``core.ai_road_planner`` — BA road allow / pick (calls prepare on LR priority)
  - ``core.strategy_min_road_cover`` — victory *count* of empty roads
  - ``core.strategy_race_ba`` — BA chase sticky race when risk M/H
  - ``core.ai_lr_project`` — LR claim/grow oracle (takes_now / length gain)
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

WIRING_STATUS = "partial_lr_dual_dead_edge"
WIRING_TODO = (
    "Board-only (4) future length clusters / (5) full race-threat matrix; "
    "SE policy bag (combine/race/block whom)."
)

Edge = Tuple[int, int]


def _norm_edge(raw: Any) -> Optional[Edge]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            a, b = int(raw[0]), int(raw[1])
            return (min(a, b), max(a, b))
        except Exception:
            return None
    if isinstance(raw, Mapping):
        return _norm_edge(
            raw.get("road")
            or raw.get("edge")
            or raw.get("road_id")
            or raw.get("next_road")
            or raw.get("path")
        )
    return None


def _path_edges(path: Any) -> List[Edge]:
    """Accept ``[[a,b],[b,c]]``, flat ``[a,b,c]``, fingerprint, or mapping."""
    if isinstance(path, Mapping):
        raw = path.get("roads") or path.get("path") or path.get("edges") or path.get("route")
        if raw is None and path.get("roads_to_build") is not None:
            raw = path.get("roads_to_build")
        return _path_edges(raw)
    if isinstance(path, str):
        s = path.strip()
        if not s:
            return []
        parts = []
        for part in s.replace(";", ",").split(","):
            part = part.strip()
            if "-" in part and part.count("-") == 1:
                a, b = part.split("-", 1)
                try:
                    parts.append((min(int(a), int(b)), max(int(a), int(b))))
                except Exception:
                    continue
        return parts
    if not isinstance(path, (list, tuple)) or not path:
        return []
    # list of edges
    if isinstance(path[0], (list, tuple)) and len(path[0]) >= 2:
        out: List[Edge] = []
        for e in path:
            ne = _norm_edge(e)
            if ne is not None:
                out.append(ne)
        return out
    # flat vertex chain a-b-c
    try:
        verts = [int(x) for x in path]
    except Exception:
        return []
    return [
        (min(verts[i], verts[i + 1]), max(verts[i], verts[i + 1]))
        for i in range(len(verts) - 1)
    ]


def _edge_set(path: Any) -> set:
    return set(_path_edges(path))


def _candidate_meta(c: Any) -> Dict[str, Any]:
    """Normalize a candidate into edge/path + optional flags."""
    if isinstance(c, Mapping):
        edges = _path_edges(c)
        if not edges:
            e = _norm_edge(c)
            edges = [e] if e else []
        return {
            "edges": edges,
            "takes_now": bool(c.get("takes_now") or c.get("claim_now") or c.get("takes")),
            "steals": bool(c.get("steals")),
            "gain": c.get("gain"),
            "length_after": c.get("length_after"),
            "raw": c,
        }
    edges = _path_edges(c) if isinstance(c, (list, tuple)) and c and isinstance(c[0], (list, tuple)) else []
    if not edges:
        e = _norm_edge(c)
        edges = [e] if e else []
    return {
        "edges": edges,
        "takes_now": False,
        "steals": False,
        "gain": None,
        "length_after": None,
        "raw": c,
    }


def _tip_ids(settle_tips: Sequence[Any]) -> List[int]:
    out: List[int] = []
    for t in list(settle_tips or []):
        if isinstance(t, Mapping):
            try:
                i = int(t.get("id"))
            except Exception:
                continue
            if str(t.get("kind") or "S").upper() in ("S", "SETTLE", "SETTLEMENT", ""):
                out.append(i)
        else:
            try:
                out.append(int(t))
            except Exception:
                continue
    return out


def rank_paths_to_target(
    game: Any,
    player: Any,
    target_id: Any,
    paths: Sequence[Any],
    *,
    threats: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Rank alternate empty-road paths to ``target_id``.

    WP-R4: when maps are fresh, prefer shorter ``real_distance`` / fewer edges.
    Politics scoring still light; map distance is the primary tie-break.
    """
    tid = None
    try:
        tid = int(target_id) if target_id is not None else None
    except Exception:
        tid = None

    path_list: List[Any] = list(paths or [])
    map_rem = None
    map_seeded = False
    try:
        from core.constants import REACHABILITY_MAPS
        from core.player_reachability import (
            SENTINEL,
            ensure_reachability_maps,
            maps_are_fresh,
            path_to_target,
            remaining_roads_to_target,
        )

        if bool(REACHABILITY_MAPS) and player is not None and game is not None:
            ensure_reachability_maps(game, player)
        if maps_are_fresh(player) and tid is not None:
            map_rem = remaining_roads_to_target(player, tid)
            if not path_list and 0 < int(map_rem) < SENTINEL:
                seeded = path_to_target(player, tid)
                if seeded:
                    path_list = [seeded]
                    map_seeded = True
    except Exception:
        map_rem = None
        map_seeded = False

    scored_rows: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for i, p in enumerate(path_list):
        edges = _path_edges(p)
        reason_tags = ["map_distance_rank"] if map_rem is not None else ["stub_preserve_order"]
        if map_seeded and i == 0:
            reason_tags.append("seeded_from_path_map")
        if threats:
            reason_tags.append("threats_present_unscored")
        # Prefer fewer remaining roads (map), then fewer edges, then input order
        rem_key = int(map_rem) if map_rem is not None else 99
        edge_n = len(edges)
        score = -float(rem_key) * 10.0 - float(edge_n)
        row = {
            "rank": i,
            "target_id": tid,
            "path": [[a, b] for a, b in edges],
            "score": score,
            "reasons": list(reason_tags),
            "mode": "toward_target",
            "map_real_distance": map_rem,
        }
        scored_rows.append(((rem_key, edge_n, i), row))

    scored_rows.sort(key=lambda t: t[0])
    ranked: List[Dict[str, Any]] = []
    for new_rank, (_key, row) in enumerate(scored_rows):
        row = dict(row)
        row["rank"] = new_rank
        ranked.append(row)

    return {
        "ok": True,
        "wired": bool(map_rem is not None or map_seeded),
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "mode": "toward_target",
        "target_id": tid,
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "note": (
            "map-ranked by real_distance then edge count"
            if map_rem is not None or map_seeded
            else "stub: order unchanged; politics scoring not implemented"
        ),
    }


def rank_lr_only_roads(
    game: Any,
    player: Any,
    candidates: Sequence[Any],
) -> Dict[str, Any]:
    """Rank roads whose sole purpose is Longest Road (no settle tips)."""
    ranked: List[Dict[str, Any]] = []
    for i, c in enumerate(list(candidates or [])):
        meta = _candidate_meta(c)
        edge = meta["edges"][0] if meta["edges"] else None
        ranked.append(
            {
                "rank": i,
                "edge": [edge[0], edge[1]] if edge else None,
                "path": [[a, b] for a, b in meta["edges"]],
                "candidate": c,
                "score": 0.0,
                "reasons": ["stub_preserve_order", "lr_only"],
                "mode": "lr_only",
            }
        )
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "mode": "lr_only",
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "note": "use rank_lr_priority_roads when settle tips are available",
    }


def _dcard_already_played_this_turn(game: Any) -> bool:
    try:
        from core.ai_play_dcard_choice import _dcard_already_played

        return bool(_dcard_already_played(game))
    except Exception:
        pass
    try:
        td = getattr(game, "turn_data", None)
        if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
            return True
    except Exception:
        pass
    return False


def _roads_from_hand(game: Any, player: Any) -> int:
    """How many roads the hand can pay for now (min wood, brick)."""
    try:
        from core.rcard_optimizer import _hand_vector

        hand = _hand_vector(game, player)
        wood = int(hand[2] if len(hand) > 2 else 0)
        brick = int(hand[3] if len(hand) > 3 else 0)
        return max(0, min(wood, brick))
    except Exception:
        return 0


def assess_lr_claimable_this_turn(
    game: Any,
    player: Any,
    *,
    roads_needed: int = 1,
    candidates: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """(1) Can LR be gained this turn? Board claim + TFR + trade unlock probe.

    Does not execute TwB/TFR. Calls ``dcard_optimizer`` / ``rcard_optimizer``
    for playability / unlock hints only.
    """
    need = max(1, int(roads_needed or 1))
    reasons: List[str] = []
    live_claim_edges: List[List[int]] = []

    # Board: live 1-edge claims
    try:
        from core.ai_road_planner import road_is_live_lr_claim_edge, _collect_lr_edge_candidates

        edges: List[Edge] = []
        for c in list(candidates or []):
            e = _norm_edge(c)
            if e and e not in edges:
                edges.append(e)
        if not edges:
            for raw in _collect_lr_edge_candidates(game, player):
                e = _norm_edge(raw)
                if e and e not in edges:
                    edges.append(e)
        for e in edges[:12]:
            if road_is_live_lr_claim_edge(game, player, e):
                live_claim_edges.append([e[0], e[1]])
    except Exception:
        pass

    project_takes_now = False
    project_edges_remaining = 0
    try:
        from core.ai_lr_project import get_stored_lr_project, remaining_lr_project_roads

        stored = get_stored_lr_project(player, game)
        rem = remaining_lr_project_roads(game, player) if stored else []
        project_edges_remaining = len(rem or [])
        if isinstance(stored, Mapping):
            project_takes_now = bool(
                stored.get("takes_now") or str(stored.get("kind") or "") == "lr_claim"
            )
    except Exception:
        pass

    roads_affordable_now = _roads_from_hand(game, player)

    # DCard: TFR
    tfr_held = 0
    tfr_playable_this_turn = False
    dcard_already = _dcard_already_played_this_turn(game)
    dcard_bag: Dict[str, Any] = {}
    try:
        from core.dcard_optimizer import CARD_TFR, plan_play_sequence, _hand_dcard_counts

        counts = _hand_dcard_counts(player)
        tfr_held = int(counts.get(CARD_TFR) or 0)
        dcard_bag = plan_play_sequence(game, player)
        tfr_playable_this_turn = bool(tfr_held > 0 and not dcard_already)
        if tfr_playable_this_turn:
            reasons.append("tfr_playable_this_turn")
        elif tfr_held and dcard_already:
            reasons.append("tfr_held_but_dcard_already_played")
    except Exception as exc:
        dcard_bag = {"ok": False, "error": str(exc)}

    roads_via_tfr = 2 if tfr_playable_this_turn else 0

    # RCard: can trades unlock Build road toward need?
    roads_via_trade = 0
    rcard_bag: Dict[str, Any] = {}
    try:
        from core.rcard_optimizer import suggest_trades_for_targets

        # Synthetic road target — optimizer looks at live support need when game set
        rcard_bag = suggest_trades_for_targets(
            game,
            player,
            targets=[{"id": "LR", "kind": "road", "roads_needed": need}],
        )
        twb = list((rcard_bag or {}).get("twb") or [])
        twp = list((rcard_bag or {}).get("twp") or [])
        if twb or twp:
            # Conservative: each unlocking trade contributes at most one extra road
            unlock = sum(1 for t in twb + twp if t.get("fully_unlocks") or t.get("reason"))
            roads_via_trade = max(1, min(need, unlock or 1))
            reasons.append("rcard_trade_may_unlock_road")
    except Exception as exc:
        rcard_bag = {"ok": False, "error": str(exc)}

    roads_budget = int(roads_affordable_now) + int(roads_via_tfr) + int(roads_via_trade)

    board_claim_ready = bool(live_claim_edges) or (
        project_takes_now and project_edges_remaining > 0
    )
    edges_for_claim = 1 if live_claim_edges else max(1, project_edges_remaining or need)
    claimable_this_turn = bool(
        board_claim_ready and roads_budget >= min(need, edges_for_claim)
    ) or bool(live_claim_edges and roads_budget >= 1)

    if live_claim_edges:
        reasons.append("live_claim_edge")
    if project_takes_now:
        reasons.append("project_takes_now")
    if claimable_this_turn:
        reasons.append("claimable_this_turn")
    else:
        reasons.append("not_claimable_this_turn")

    return {
        "ok": True,
        "claimable_this_turn": claimable_this_turn,
        "roads_needed": need,
        "roads_affordable_now": roads_affordable_now,
        "roads_via_tfr": roads_via_tfr,
        "roads_via_trade": roads_via_trade,
        "roads_budget": roads_budget,
        "tfr_held": tfr_held,
        "tfr_playable_this_turn": tfr_playable_this_turn,
        "dcard_already_played": dcard_already,
        "live_claim_edges": live_claim_edges,
        "project_takes_now": project_takes_now,
        "project_edges_remaining": project_edges_remaining,
        "rcard": rcard_bag,
        "dcard": dcard_bag,
        "reasons": reasons,
    }


def prepare_lr_road_decision(
    game: Any,
    player: Any,
    *,
    lr_candidates: Optional[Sequence[Any]] = None,
    sticky_path: Optional[Any] = None,
    roads_needed: Optional[int] = None,
) -> Dict[str, Any]:
    """LR-priority façade: (1) claimability → (2) post-LR tips → rank.

    Future (doc only): (3) opponent deny, (4) future length, (5) board race threat;
    SE policy (combine / race / block whom) via coordinator.
    """
    sticky_edges = _path_edges(sticky_path)
    need = int(roads_needed) if roads_needed is not None else max(1, len(sticky_edges) or 1)

    claim_bag = assess_lr_claimable_this_turn(
        game,
        player,
        roads_needed=need,
        candidates=lr_candidates,
    )

    tips_bag: Dict[str, Any] = {"ok": False, "tips": []}
    try:
        from core.strategy_coordinator import post_lr_settle_tips

        tips_bag = post_lr_settle_tips(game, player)
    except Exception as exc:
        tips_bag = {"ok": False, "tips": [], "error": str(exc)}

    rank_bag = rank_lr_priority_roads(
        game,
        player,
        lr_candidates=lr_candidates,
        settle_tips=tips_bag.get("tips") or [],
        sticky_path=sticky_path,
        claimability=claim_bag,
    )

    return {
        "ok": True,
        "wired": True,
        "wiring_status": WIRING_STATUS,
        "claimability": claim_bag,
        "tips": tips_bag,
        "ranked": rank_bag.get("ranked") or [],
        "best": rank_bag.get("best"),
        "rank": rank_bag,
        "note": "prepare: claimability + post_lr tips + dual-purpose rank",
    }


def _opp_structure_nodes(game: Any, player: Any) -> set:
    """Intersection ids with opponent settlements/cities."""
    out: set = set()
    try:
        pid = int(getattr(player, "id", -1) or -1)
    except Exception:
        pid = -1
    for opp in list(getattr(game, "players", None) or []):
        try:
            if int(getattr(opp, "id", -2) or -2) == pid:
                continue
        except Exception:
            continue
        for attr in ("settlements", "cities"):
            for n in list(getattr(opp, attr, None) or []):
                try:
                    out.add(int(n))
                except Exception:
                    continue
    return out


def _edge_is_dead_for_opponents(edge: Edge, opp_nodes: set, board: Any = None) -> bool:
    """True if neither endpoint is an opp structure or adjacent to one (WP-G).

    Dig: roads like 49-50 / 50-39 that add own length but give opponents
    little expansion value.
    """
    a, b = edge[0], edge[1]
    if a in opp_nodes or b in opp_nodes:
        return False
    if board is None:
        return True
    try:
        from core.strategy_sticky import _intersection_neighbors

        for n in (a, b):
            for nb in _intersection_neighbors(board, int(n)) or []:
                if int(nb) in opp_nodes:
                    return False
    except Exception:
        # Without adjacency, treat as dead if endpoints themselves are free
        return True
    return True


def rank_lr_priority_roads(
    game: Any,
    player: Any,
    *,
    lr_candidates: Optional[Sequence[Any]] = None,
    settle_tips: Optional[Sequence[Any]] = None,
    sticky_path: Optional[Any] = None,
    claimability: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Rank LR-successful candidates preferring dual-purpose settle progress.

    Scoring (higher better):
      - contested steal claim that only a non-dual edge can take → force that edge
      - dual_purpose_sticky (+200); dual+takes_now (+500)
      - dual_purpose_tip / path-to-tip (+80..; stronger when edge hits tip)
      - dead_edge_for_opp (+35) for pure length that opponents can't use
      - pure takes_now (+100), steals (+50)
      - Anticipation: dual sticky/tip without takes_now still beats optional
        pure claim (not steals) so S48 path can win over tip-only 13-24
      - If claimability says dual path is not finishable this turn while a
        shorter claim is, penalize dual (``defer_dual_not_finishable_this_turn``)
      - shorter path preferred; earlier tips weigh more
    """
    sticky_edges = _edge_set(sticky_path)
    tip_ids = _tip_ids(list(settle_tips or []))
    tip_nodes = set(tip_ids)

    # Optional sticky tip id from first sticky path endpoint not owned — tips[0]
    sticky_tip = tip_ids[0] if tip_ids else None

    metas = [_candidate_meta(c) for c in list(lr_candidates or [])]
    metas = [m for m in metas if m["edges"]]

    claim = dict(claimability or {})
    roads_budget = int(claim.get("roads_budget") or 0)
    claimable = bool(claim.get("claimable_this_turn"))

    opp_nodes = set()
    board = getattr(game, "board", None) if game is not None else None
    try:
        opp_nodes = _opp_structure_nodes(game, player)
    except Exception:
        opp_nodes = set()

    def _is_dual(m: Mapping[str, Any]) -> bool:
        es = set(m.get("edges") or [])
        if sticky_edges and (es & sticky_edges):
            return True
        if tip_nodes and any(n in tip_nodes for e in es for n in e):
            return True
        # Path-to-tip: sticky path edge toward tip (not only tip vertex)
        if sticky_edges and es and (es & sticky_edges):
            return True
        return False

    # Steal override detection
    steal_claimers = [m for m in metas if m["takes_now"] and m["steals"]]
    dual_that_claim = [m for m in metas if m["takes_now"] and _is_dual(m)]
    force_steal = bool(steal_claimers) and not dual_that_claim

    ranked: List[Dict[str, Any]] = []
    for m in metas:
        edges = m["edges"]
        es = set(edges)
        reasons: List[str] = []
        score = 0.0
        is_dual = False
        path_len = max(1, len(edges))

        if force_steal and m["steals"] and m["takes_now"]:
            score += 1000.0
            reasons.append("contested_steal_claim")
        elif force_steal:
            score -= 200.0
            reasons.append("defer_non_steal_while_contested")

        if sticky_edges and (es & sticky_edges):
            is_dual = True
            # Stronger when sticky path also reaches a tip node (last S + LR)
            hits_tip = bool(tip_nodes) and any(
                n in tip_nodes for e in sticky_edges for n in e
            ) or any(n in tip_nodes for e in es for n in e)
            base = 500.0 if m["takes_now"] else 200.0
            if hits_tip:
                base += 80.0
                reasons.append("dual_settle_and_lr")
            score += base
            reasons.append("dual_purpose_sticky")
            if sticky_tip is not None:
                reasons.append(f"dual_purpose_s{sticky_tip}")

        # Tip node overlap (edge endpoints match tip ids) — prefer 43-44 over 43-54
        tip_hit = None
        for idx, tid in enumerate(tip_ids):
            if any(tid in e for e in edges):
                tip_hit = tid
                is_dual = True
                tip_base = max(50.0, 100.0 - 12.0 * idx)
                score += (450.0 if m["takes_now"] else tip_base)
                reasons.append(f"dual_purpose_tip_s{tid}")
                break
        # Soft: edge shares a vertex with sticky path toward tip (branch toward tip)
        if tip_hit is None and sticky_edges:
            sticky_verts = {n for e in sticky_edges for n in e}
            if any(a in sticky_verts or b in sticky_verts for a, b in es):
                if tip_nodes and any(
                    n in sticky_verts for n in tip_nodes
                ):
                    score += 40.0
                    reasons.append("on_path_toward_tip")

        if m["takes_now"]:
            score += 100.0
            reasons.append("lr_claim")
        if m["steals"]:
            score += 50.0
            reasons.append("steals")
        try:
            gain = float(m["gain"]) if m["gain"] is not None else 0.0
        except Exception:
            gain = 0.0
        if gain > 0:
            score += min(20.0, gain * 2.0)
            reasons.append("lr_grow")

        # WP-G dead-edge: own length with little opp expansion value
        head = edges[0]
        if _edge_is_dead_for_opponents(head, opp_nodes, board):
            score += 35.0 if not is_dual else 15.0
            reasons.append("dead_edge_for_opp")

        if not reasons:
            reasons.append("lr_only")
        if is_dual and not m["takes_now"] and not m["steals"]:
            reasons.append("anticipate_post_lr_settle")

        # (1) Finishability this turn: long dual paths lose to short claims
        if claim and roads_budget > 0 and path_len > roads_budget:
            if is_dual and not m["takes_now"]:
                score -= 250.0
                reasons.append("defer_dual_not_finishable_this_turn")
            elif m["takes_now"] and path_len <= roads_budget:
                score += 40.0
                reasons.append("finishable_claim_this_turn")
        elif claimable and m["takes_now"] and path_len <= max(1, roads_budget):
            score += 15.0
            reasons.append("within_roads_budget")

        # Prefer fewer edges
        score -= 2.0 * max(0, path_len - 1)

        next_e = edges[0]
        ranked.append(
            {
                "rank": 0,  # filled after sort
                "edge": [next_e[0], next_e[1]],
                "next_road": [next_e[0], next_e[1]],
                "path": [[a, b] for a, b in edges],
                "score": round(score, 3),
                "reasons": reasons,
                "takes_now": bool(m["takes_now"]),
                "steals": bool(m["steals"]),
                "tip_id": tip_hit or (sticky_tip if "dual_purpose_sticky" in reasons else None),
                "mode": "lr_priority",
                "candidate": m["raw"],
            }
        )

    ranked.sort(key=lambda r: (-float(r["score"]), len(r.get("path") or []), str(r.get("edge"))))
    for i, r in enumerate(ranked):
        r["rank"] = i

    return {
        "ok": True,
        "wired": True,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "mode": "lr_priority",
        "sticky_edges": [[a, b] for a, b in sorted(sticky_edges)],
        "tip_ids": tip_ids,
        "force_steal": force_steal,
        "claimability": claim or None,
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "note": "prefer dual-purpose sticky/tip among LR-successful options",
    }


def optimize_road_choice(
    game: Any,
    player: Any,
    *,
    target_id: Any = None,
    paths: Optional[Sequence[Any]] = None,
    lr_candidates: Optional[Sequence[Any]] = None,
    settle_tips: Optional[Sequence[Any]] = None,
    sticky_path: Optional[Any] = None,
) -> Dict[str, Any]:
    """Façade: target paths if given; else LR prepare/rank; else LR-only."""
    if paths:
        return rank_paths_to_target(game, player, target_id, paths)
    if lr_candidates is not None:
        return prepare_lr_road_decision(
            game,
            player,
            lr_candidates=lr_candidates,
            sticky_path=sticky_path,
        )
    return rank_lr_only_roads(game, player, list(lr_candidates or []))


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "assess_lr_claimable_this_turn",
    "prepare_lr_road_decision",
    "rank_paths_to_target",
    "rank_lr_only_roads",
    "rank_lr_priority_roads",
    "optimize_road_choice",
]
