"""P1+Q2: opportunistic off-way DCard buy — no L2.

When Buy development_card is legal but not on the sticky/preferred way path,
AI may buy only if starve + race guards pass. Never runs full strategy explore.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Deck remaining at or below this + LA race → block soft buy (plan D1)
DECK_THIN_K: int = 3

try:
    from core.ai_dcard_timing import COST_CITY, COST_DCARD, COST_ROAD, COST_SETTLE
except Exception:  # pragma: no cover
    COST_CITY = [2, 3, 0, 0, 0]
    COST_SETTLE = [1, 0, 1, 1, 1]
    COST_ROAD = [0, 0, 1, 1, 0]
    COST_DCARD = [1, 1, 0, 0, 1]


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _norm_action(name: Any) -> str:
    return str(name or "").strip().lower().replace("_", " ")


def _vec5(seq: Any) -> List[int]:
    out = [0, 0, 0, 0, 0]
    try:
        for i, v in enumerate(list(seq or [])[:5]):
            out[i] = max(0, int(v or 0))
    except Exception:
        pass
    return out


def _hand_vector(player: Any) -> List[int]:
    if player is None:
        return [0, 0, 0, 0, 0]
    try:
        fn = getattr(player, "rcards_in_hand", None)
        if callable(fn):
            rcards5, _, _ = fn()
            return _vec5(rcards5)
    except Exception:
        pass
    try:
        # Wheat, Ore, Wood, Brick, Sheep
        from core.constants import ResourceCard  # type: ignore

        rc = getattr(player, "rcards", None) or {}
        return [
            int(rc.get(ResourceCard.WHEAT, 0) or 0),
            int(rc.get(ResourceCard.ORE, 0) or 0),
            int(rc.get(ResourceCard.WOOD, 0) or 0),
            int(rc.get(ResourceCard.BRICK, 0) or 0),
            int(rc.get(ResourceCard.SHEEP, 0) or 0),
        ]
    except Exception:
        return [0, 0, 0, 0, 0]


def _can_pay(hand: Sequence[int], cost: Sequence[int]) -> bool:
    h = _vec5(hand)
    c = _vec5(cost)
    return all(h[i] >= c[i] for i in range(5))


def _subtract(hand: Sequence[int], cost: Sequence[int]) -> List[int]:
    h = _vec5(hand)
    c = _vec5(cost)
    return [max(0, h[i] - c[i]) for i in range(5)]


def _deck_remaining(game: Any) -> Optional[int]:
    if game is None:
        return None
    for attr in ("dcards_stack", "development_card_deck", "dcard_deck"):
        try:
            stack = getattr(game, attr, None)
            if isinstance(stack, (list, tuple)):
                return len(stack)
            if isinstance(stack, int):
                return max(0, stack)
        except Exception:
            pass
    try:
        n = getattr(game, "development_cards_remaining", None)
        if n is not None:
            return max(0, int(n))
    except Exception:
        pass
    return None


def _row_viable_dcard(row: Mapping[str, Any]) -> bool:
    if not isinstance(row, Mapping):
        return False
    name = _norm_action(row.get("action") or row.get("name"))
    if "development" not in name and "dcard" not in name.replace(" ", ""):
        if name not in {"buy development card", "buy development_card"}:
            # Buy development_card → "buy development card" after replace
            if "buy development" not in name:
                return False
    if "viable" in row and not bool(row.get("viable")):
        return False
    if "legal" in row and not bool(row.get("legal")):
        return False
    return True


def dcard_buy_viable(game: Any) -> bool:
    if game is None:
        return False
    deck = _deck_remaining(game)
    if deck is not None and deck <= 0:
        return False
    for attr in ("current_execution_choices", "current_actionable_choices"):
        for row in list(getattr(game, attr, None) or []):
            if _row_viable_dcard(row):
                return True
    scan = getattr(game, "current_viable_action_scan", None)
    if isinstance(scan, Mapping):
        cands = scan.get("candidates")
        if isinstance(cands, Mapping):
            for aname, clist in cands.items():
                if "development" in _norm_action(aname) and list(clist or []):
                    return True
        flags = scan.get("action_flags") or scan.get("actions")
        if isinstance(flags, Mapping):
            for k, v in flags.items():
                if "development" in _norm_action(k) and v:
                    return True
    return False


def dcard_is_on_way(player: Any) -> Tuple[bool, str]:
    """True if preferred/sticky path already wants DCard buys."""
    if player is None:
        return False, "no_player"
    direction = getattr(player, "strategic_direction", None)
    if isinstance(direction, Mapping):
        for key in ("supporting_action_type", "supporting_action", "preferred_supporting_action"):
            sup = _norm_action(direction.get(key))
            if "dcard" in sup.replace(" ", "") or "development" in sup:
                return True, f"supporting:{key}"
        if bool(direction.get("largest_army") or direction.get("biggest_army")):
            return True, "direction.largest_army"
        tags = [str(t).lower() for t in list(direction.get("tags") or [])]
        if any("army" in t or "dcard" in t or "development" in t for t in tags):
            return True, "direction.tags"
        rem = direction.get("remaining")
        if isinstance(rem, Mapping):
            for k, v in rem.items():
                kl = str(k).lower()
                if ("dcard" in kl or "development" in kl or "army" in kl) and _safe_int(v, 0):
                    if int(v or 0) > 0:
                        return True, f"remaining.{k}"
        summary = direction.get("strategy_summary")
        if isinstance(summary, Mapping):
            if bool(summary.get("largest_army") or summary.get("biggest_army")):
                return True, "strategy_summary.largest_army"
            for k in ("dcards", "development_cards", "remaining_dcards"):
                if _safe_int(summary.get(k), 0) and int(summary.get(k) or 0) > 0:
                    return True, f"summary.{k}"

    sticky = getattr(player, "sticky_commitment", None)
    if isinstance(sticky, Mapping):
        la = sticky.get("la_progress")
        if isinstance(la, Mapping) and la:
            return True, "sticky.la_progress"
        if bool(sticky.get("wants_largest_army") or sticky.get("largest_army")):
            return True, "sticky.largest_army"

    try:
        from core.ai_la_progress import way_wants_largest_army

        if way_wants_largest_army(player):
            return True, "way_wants_largest_army"
    except Exception:
        pass

    return False, ""


def _structure_cost_for_action(action: str) -> Optional[List[int]]:
    n = _norm_action(action)
    if "city" in n:
        return list(COST_CITY)
    if "settlement" in n:
        return list(COST_SETTLE)
    return None


def _iter_viable_structure_rows(game: Any) -> List[Mapping[str, Any]]:
    rows: List[Mapping[str, Any]] = []
    for attr in ("current_execution_choices", "current_actionable_choices"):
        for row in list(getattr(game, attr, None) or []):
            if not isinstance(row, Mapping):
                continue
            n = _norm_action(row.get("action") or row.get("name"))
            if "city" not in n and "settlement" not in n:
                continue
            if "road" in n and "settlement" not in n:
                continue
            if "viable" in row and not bool(row.get("viable")):
                continue
            rows.append(row)
    return rows


def _on_way_structure_ids(game: Any, player: Any) -> set:
    try:
        from core.strategy_offway_q1 import collect_on_way_structure_ids

        return set(collect_on_way_structure_ids(player, game))
    except Exception:
        return set()


def _target_from_row(row: Mapping[str, Any]) -> Optional[int]:
    tid = _safe_int(row.get("target_id"), None)
    if tid is not None:
        return tid
    tid = _safe_int(row.get("intersection_id"), None)
    if tid is not None:
        return tid
    for c in list(row.get("candidates") or []):
        if isinstance(c, Mapping):
            tid = _safe_int(
                c.get("target_id") or c.get("intersection_id") or c.get("settlement_id"),
                None,
            )
            if tid is not None:
                return tid
    return None


def guard_starve_sticky_structure(
    game: Any,
    player: Any,
    *,
    hand: Optional[Sequence[int]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """True if blocked: buying DCard would starve a viable on-way city/settle."""
    meta: Dict[str, Any] = {}
    h = _vec5(hand if hand is not None else _hand_vector(player))
    cost_d = list(COST_DCARD)
    if not _can_pay(h, cost_d):
        # Not actually affordable — caller should not allow for other reasons
        return False, "", meta
    post = _subtract(h, cost_d)
    on_way = _on_way_structure_ids(game, player)
    for row in _iter_viable_structure_rows(game):
        tid = _target_from_row(row)
        # If we have on-way set, only guard those; if empty, still guard any viable sticky rec
        if on_way and tid is not None and tid not in on_way:
            continue
        if on_way and tid is None:
            # structure family on-way but no id — still check if sticky has any structure lock
            sticky = getattr(player, "sticky_commitment", None)
            if not (isinstance(sticky, Mapping) and sticky.get("locked_rec_target_id") is not None):
                if not on_way:
                    continue
        cost_s = _structure_cost_for_action(str(row.get("action") or ""))
        if cost_s is None:
            continue
        # Only care if currently affordable (or was) — viable row implies can build now
        if not _can_pay(h, cost_s):
            continue
        if _can_pay(post, cost_s):
            continue
        meta = {
            "target_id": tid,
            "action": row.get("action"),
            "hand": h,
            "post_hand": post,
            "cost_structure": cost_s,
        }
        return True, f"starve_structure_{tid if tid is not None else 'family'}", meta
    return False, "", meta


def _road_actionable_toward_sticky(game: Any, player: Any) -> bool:
    """True if a strategic road on sticky/LR path is legal now."""
    sticky = getattr(player, "sticky_commitment", None)
    has_road_project = False
    if isinstance(sticky, Mapping):
        roads = sticky.get("locked_roads_to_build") or []
        lr = sticky.get("lr_project")
        if roads:
            has_road_project = True
        if isinstance(lr, Mapping) and (lr.get("roads_to_build") or lr.get("active")):
            has_road_project = True
    direction = getattr(player, "strategic_direction", None)
    if isinstance(direction, Mapping):
        sup = _norm_action(direction.get("supporting_action_type"))
        if "road" in sup:
            has_road_project = True
        if list(direction.get("roads_to_build") or []):
            has_road_project = True

    for attr in ("current_actionable_choices", "current_execution_choices"):
        for row in list(getattr(game, attr, None) or []):
            if not isinstance(row, Mapping):
                continue
            if "road" not in _norm_action(row.get("action")):
                continue
            if attr == "current_execution_choices" and "viable" in row and not row.get("viable"):
                continue
            # actionable preferred for strategic road
            if attr == "current_actionable_choices" and not bool(
                row.get("actionable", row.get("viable", False))
            ):
                continue
            if has_road_project or bool(row.get("actionable")):
                return True
    return False


def guard_active_races(
    game: Any,
    player: Any,
    *,
    deck_remaining: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """True if blocked by LA/LR/road/settle/last-DCard race."""
    meta: Dict[str, Any] = {"deck_remaining": deck_remaining}

    # Specific settle / city already covered partly by starve; also block if
    # on-way settle/city is actionable strategically (prefer build over soft DCard)
    for row in list(getattr(game, "current_actionable_choices", None) or []):
        if not isinstance(row, Mapping):
            continue
        if not bool(row.get("actionable", row.get("viable", False))):
            continue
        n = _norm_action(row.get("action"))
        if "city" in n or "settlement" in n:
            on_way = _on_way_structure_ids(game, player)
            tid = _target_from_row(row)
            if not on_way or (tid is not None and tid in on_way) or tid is None:
                return True, "race_onway_structure_actionable", {
                    **meta,
                    "action": row.get("action"),
                    "target_id": tid,
                }

    # Specific road / LR path
    if _road_actionable_toward_sticky(game, player):
        return True, "race_specific_road", meta

    la_race = False
    lr_race = False
    try:
        from core.ai_lr_project import pick_turn_focus

        focus = pick_turn_focus(game, player) if player is not None else {}
        if isinstance(focus, Mapping):
            la_race = bool(focus.get("la_race"))
            lr_race = bool(focus.get("lr_race"))
            foc = str(focus.get("focus") or "").lower()
            if foc == "lr":
                lr_race = True
            if foc == "la":
                la_race = True
            meta["turn_focus"] = foc
    except Exception:
        pass

    try:
        from core.ai_lr_project import compute_la_race_state

        race = compute_la_race_state(game, player)
        if isinstance(race, Mapping) and bool(race.get("la_race")):
            la_race = True
            meta["la_race_state"] = True
    except Exception:
        pass

    if lr_race:
        return True, "race_lr", meta

    deck = deck_remaining if deck_remaining is not None else _deck_remaining(game)
    meta["deck_remaining"] = deck
    if la_race:
        if deck is not None and deck <= int(DECK_THIN_K):
            return True, "race_la_last_dcards", meta
        # Live LA race with non-thin deck: still block soft *off-way* buy so on-way
        # path (if any) owns buys — soft buy dilutes contest. Plan: block when race live
        # and deck thin hard; when race live and deck thick allow unless G1.
        # Soften: only thin deck blocks for last DCards; pure la_race without thin
        # does not block (plan D1 table). Keep la_race alone as soft allow.
        pass

    # Last DCards: thin deck + any LA-shaped pressure on the table
    if deck is not None and deck <= int(DECK_THIN_K):
        table_la = la_race
        if not table_la:
            try:
                # Opponent deep army heuristic
                for p in list(getattr(game, "players", None) or []):
                    if p is player:
                        continue
                    army = int(getattr(p, "largest_army_size", 0) or getattr(p, "army_size", 0) or 0)
                    if army >= 2:
                        table_la = True
                        break
            except Exception:
                pass
        if table_la:
            return True, "last_dcards_contested", meta

    return False, "", meta


def evaluate_q2_offway_dcard(game: Any, player: Any = None) -> Dict[str, Any]:
    """Pure evaluate: eligible off-way DCard + allow after guards."""
    out: Dict[str, Any] = {
        "eligible": False,
        "allow": False,
        "on_way_dcard": False,
        "dcard_viable": False,
        "blocked_by": [],
        "meta": {},
        "reason": "",
    }
    if game is None:
        out["reason"] = "no_game"
        return out
    if player is None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None
    if player is None:
        out["reason"] = "no_player"
        return out

    try:
        phase = str(getattr(game, "phase", "") or "")
        if phase != "Execution":
            out["reason"] = "not_execution"
            return out
    except Exception:
        pass

    viable = dcard_buy_viable(game)
    out["dcard_viable"] = bool(viable)
    out["meta"]["deck_remaining"] = _deck_remaining(game)
    if not viable:
        out["reason"] = "dcard_not_viable"
        return out

    on_way, on_reason = dcard_is_on_way(player)
    out["on_way_dcard"] = bool(on_way)
    out["meta"]["on_way_reason"] = on_reason
    if on_way:
        out["reason"] = f"on_way:{on_reason}"
        # Strategic path owns buy — Q2 idle
        return out

    out["eligible"] = True
    blocked: List[str] = []

    starve, starve_why, starve_meta = guard_starve_sticky_structure(game, player)
    if starve:
        blocked.append(starve_why or "starve_structure")
        out["meta"]["starve"] = starve_meta

    race_block, race_why, race_meta = guard_active_races(
        game, player, deck_remaining=out["meta"].get("deck_remaining")
    )
    if race_block:
        blocked.append(race_why or "race")
        out["meta"]["race"] = race_meta

    out["blocked_by"] = blocked
    if blocked:
        out["allow"] = False
        out["reason"] = "blocked:" + ",".join(blocked)
    else:
        out["allow"] = True
        out["reason"] = "allow_offway_dcard"
    return out


def apply_q2_offway_dcard_permission(
    game: Any,
    player: Any = None,
    *,
    reason: str = "",
) -> Dict[str, Any]:
    """Evaluate and store permission; never calls L2 / refresh_strategy_context."""
    if player is None and game is not None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None

    try:
        from core.performance_trace import timed_span
    except Exception:
        timed_span = None  # type: ignore
    from contextlib import nullcontext

    span_cm = (
        timed_span(
            game,
            "q2_offway_dcard",
            meta={"reason": str(reason or "")},
        )
        if timed_span is not None and game is not None
        else nullcontext({"meta": {}})
    )

    with span_cm as span_bag:
        ev = evaluate_q2_offway_dcard(game, player)
        status = {
            "allow": bool(ev.get("allow")),
            "eligible": bool(ev.get("eligible")),
            "on_way_dcard": bool(ev.get("on_way_dcard")),
            "dcard_viable": bool(ev.get("dcard_viable")),
            "blocked_by": list(ev.get("blocked_by") or []),
            "reason": str(ev.get("reason") or ""),
            "meta": dict(ev.get("meta") or {}),
            "hook_reason": str(reason or ""),
            "no_l2": True,
        }
        bag = {
            "allow": status["allow"],
            "eligible": status["eligible"],
            "reason": status["reason"],
            "blocked_by": list(status["blocked_by"]),
            "on_way_dcard": status["on_way_dcard"],
        }
        if player is not None:
            try:
                setattr(player, "q2_offway_dcard", bag)
            except Exception:
                pass
        if game is not None:
            try:
                game.last_q2_offway_status = dict(status)
            except Exception:
                pass
        try:
            if isinstance(span_bag, dict):
                meta = span_bag.get("meta")
                if not isinstance(meta, dict):
                    meta = {}
                    span_bag["meta"] = meta
                meta.update({
                    "allow": status["allow"],
                    "eligible": status["eligible"],
                    "blocked_by": list(status["blocked_by"]),
                    "on_way": status["on_way_dcard"],
                    "deck_remaining": status["meta"].get("deck_remaining"),
                    "path": "q2_permission",
                })
        except Exception:
            pass
    return status


def q2_dcard_allowed(game: Any, player: Any = None) -> bool:
    """Read last permission (re-evaluate if missing)."""
    if player is None and game is not None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None
    bag = getattr(player, "q2_offway_dcard", None) if player is not None else None
    if isinstance(bag, Mapping) and "allow" in bag:
        return bool(bag.get("allow"))
    st = getattr(game, "last_q2_offway_status", None) if game is not None else None
    if isinstance(st, Mapping) and "allow" in st:
        return bool(st.get("allow"))
    return False


def q2_dcard_blocked(game: Any, player: Any = None) -> bool:
    """True when soft DCard must not be used as unguarded legal fallback."""
    if player is None and game is not None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None
    bag = getattr(player, "q2_offway_dcard", None) if player is not None else None
    if isinstance(bag, Mapping):
        if bag.get("on_way_dcard"):
            return False  # on-way uses normal strategic path
        if bag.get("eligible") and not bag.get("allow"):
            return True
        if bag.get("allow"):
            return False
    st = getattr(game, "last_q2_offway_status", None) if game is not None else None
    if isinstance(st, Mapping):
        if st.get("on_way_dcard"):
            return False
        if st.get("eligible") and not st.get("allow"):
            return True
    return False
