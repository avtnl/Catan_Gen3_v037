"""P5: PLN1 — way residual components + Now/Word + DC posture×focus.

Live sample on L2 (via refresh_plan_snapshot). Dig displays CS only.
Product: docs/changes_PLAN_v1_impl.md §2; coding: changes_PLAN_v2_coding.md P5.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _as_map(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _hand_owg(player: Any) -> Tuple[int, int, int]:
    """Ore, Wheat, Sheep counts from rcards (best-effort)."""
    rc = getattr(player, "rcards", None)
    if not isinstance(rc, Mapping):
        return 0, 0, 0
    def _n(*keys: str) -> int:
        for k in keys:
            if k in rc:
                try:
                    return max(0, int(rc.get(k) or 0))
                except Exception:
                    return 0
        return 0
    return (
        _n("Ore", "ore", "O"),
        _n("Wheat", "wheat", "Grain", "grain", "W"),
        _n("Sheep", "sheep", "Wool", "wool", "S"),
    )


def _can_buy_dcard(player: Any) -> bool:
    o, w, s = _hand_owg(player)
    return o >= 1 and w >= 1 and s >= 1


def _held_la(player: Any) -> bool:
    return bool(
        getattr(player, "largest_army_tf", False)
        or getattr(player, "largest_army", False)
    )


def _held_lr(player: Any) -> bool:
    return bool(
        getattr(player, "longest_route_tf", False)
        or getattr(player, "longest_road_tf", False)
    )


def _explicit_tfr_intent(player: Any, preferred: Mapping[str, Any]) -> bool:
    """Focus LR only on explicit TFR targeting (locked F) — not mere way_lr+TFR."""
    try:
        kt = getattr(player, "knight_tfr_policy", None)
        if isinstance(kt, Mapping) and kt.get("prefer_knight") is False:
            # prefer TFR from race policy
            lr = getattr(player, "lr_race_plan", None)
            if isinstance(lr, Mapping) and (
                lr.get("has_tfr") or lr.get("claim_now") or lr.get("contested")
            ):
                return True
    except Exception:
        pass
    support = str(preferred.get("supporting_action_type") or "").lower()
    if "tfr" in support or "two_free" in support:
        return True
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        if isinstance(c, Mapping):
            if str(c.get("locked_target_kind") or "").upper() == "LR" and c.get(
                "lr_race_label"
            ):
                lr = getattr(player, "lr_race_plan", None)
                if isinstance(lr, Mapping) and lr.get("has_tfr"):
                    return True
    except Exception:
        pass
    return False


def build_pln1_snapshot(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
    *,
    plan_bag: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build PLN1 narrative bag + CS fields."""
    preferred = preferred if isinstance(preferred, Mapping) else {}
    if not preferred:
        preferred = _as_map(getattr(player, "strategic_direction", None))

    bag: Dict[str, Any] = {
        "ok": False,
        "residual": "",
        "now": None,
        "word": None,
        "also": None,
        "parked": None,
        "dc_posture": None,
        "dc_focus": None,
        "dc_clause": None,
        "cs": {},
        "req_cities": 0,
        "req_settles": 0,
        "req_roads": 0,
        "req_dcards": 0,
    }
    if player is None:
        bag["reason"] = "no_player"
        return bag

    way_id = preferred.get("preferred_way_id") or preferred.get("way_id")
    res: Dict[str, Any] = {}
    try:
        from core.strategy_way_residual import compute_way_residual

        board = getattr(game, "board", None) if game is not None else None
        pref = dict(preferred) if isinstance(preferred, dict) else {}
        if game is not None and "_game" not in pref:
            pref = dict(pref)
            pref["_game"] = game
        res = compute_way_residual(
            way_id, player, preferred=pref, board=board
        ) or {}
    except Exception:
        res = {}

    req_c = _safe_int(res.get("req_cities"), 0) or 0
    req_s = _safe_int(res.get("req_settles"), 0) or 0
    req_r = _safe_int(res.get("req_roads"), 0) or 0
    req_d = _safe_int(res.get("req_dcards"), 0) or 0
    rem_vp = _safe_int(res.get("remaining_vp_cards"), 0) or 0
    way_la = bool(res.get("way_la") or res.get("need_la"))
    way_lr = bool(res.get("way_lr") or res.get("need_lr"))
    held_la = _held_la(player)
    held_lr = _held_lr(player)
    need_la = bool(way_la and not held_la)
    need_lr = bool(way_lr and not held_lr)

    # Residual display — same order/format as STR way_tags (v4)
    try:
        from core.strategy_way_residual import format_residual_tags_v4, format_tags_join

        residual = format_residual_tags_v4(
            need_la=need_la,
            need_lr=need_lr,
            req_cities=req_c,
            req_settles=req_s,
            rem_vp=rem_vp,
            req_dcards=req_d,
        )
        # Append held specials / roads for PLN1 detail (not in STR tags)
        extras: List[str] = []
        if req_r:
            extras.append(f"R×{req_r}")
        if way_lr and held_lr and not need_lr:
            extras.append("LR held")
        if way_la and held_la and not need_la:
            extras.append("LA held")
        if extras:
            residual = (residual + " · " if residual else "") + " · ".join(extras)
    except Exception:
        bits = []
        if need_la:
            bits.append("LA")
        if need_lr:
            bits.append("LR")
        bits.append(f"{req_c}×C")
        bits.append(f"{req_s}×S")
        if rem_vp:
            bits.append(f"{rem_vp}×VP")
        residual = " · ".join(bits)

    support = str(preferred.get("supporting_action_type") or "").lower()
    sticky_kind = ""
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        if isinstance(c, Mapping):
            sticky_kind = str(c.get("locked_target_kind") or "").upper()
    except Exception:
        pass

    # Contested expand from plan bag
    contested = False
    if isinstance(plan_bag, Mapping):
        for s in list(plan_bag.get("settles") or plan_bag.get("catalog") or []):
            if not isinstance(s, Mapping):
                continue
            risk = str(s.get("risk") or "").lower()
            if risk in ("med", "medium", "high", "blocked", "crit"):
                contested = True
                break

    la_race = False
    try:
        la = getattr(player, "la_race_plan", None)
        if isinstance(la, Mapping):
            la_race = bool(la.get("la_race") or la.get("play_knight") or la.get("would_take_now"))
    except Exception:
        pass

    # Primary component
    now = "Settle"
    if "city" in support or sticky_kind == "C":
        now = "City"
    elif "road" in support or sticky_kind in ("ROAD", "R"):
        now = "Road"
    elif sticky_kind == "LR" or ("lr" in support and "settle" not in support):
        now = "LR"
    elif sticky_kind == "LA" or "army" in support or "knight" in support:
        now = "LA"
    elif "dcard" in support or "dev" in support:
        now = "DC"
    elif req_s > 0:
        now = "Settle"
    elif req_c > 0:
        now = "City"
    elif need_la:
        now = "LA"
    elif need_lr:
        now = "LR"
    elif req_d > 0 or rem_vp > 0:
        now = "DC"

    # Word (P6 shared mapper)
    role = ""
    se_vs_fast = False
    if isinstance(plan_bag, Mapping):
        cat = list(plan_bag.get("catalog") or [])
        for s in cat:
            if isinstance(s, Mapping) and s.get("se_pick"):
                role = str(s.get("role") or "").lower()
                break
        if cat and plan_bag.get("se_pick"):
            se_vs_fast = str(plan_bag.get("se_pick")) != str(cat[0].get("label") or "")
    try:
        from core.strategy_pln_words import pln1_word_for_now

        word = pln1_word_for_now(
            now,
            req_settles=req_s,
            contested=contested,
            role=role,
            se_pick_vs_fastest=se_vs_fast,
            support=support,
        )
    except Exception:
        word = "Sticky"
        if now == "City" and req_s == 0:
            word = "Cap"
        elif now == "City":
            word = "Calm"
        elif now in ("Settle", "Road") and contested:
            word = "Race"
        elif now in ("LA", "LR", "DC"):
            word = "Specials"

    # DC posture × focus (locked D: always when residual)
    has_la = need_la
    has_vp = rem_vp > 0
    has_tfr = _explicit_tfr_intent(player, preferred)
    dc_residual = bool(req_d > 0 or has_la or has_vp or has_tfr)

    dc_posture = None
    dc_focus = None
    dc_clause = None
    if dc_residual:
        can_buy = _can_buy_dcard(player)
        expand_primary = req_s > 0 and now in ("Settle", "Road")
        vp_eff = _safe_int(
            getattr(player, "victory_points", None) or getattr(player, "points", None), 0
        ) or 0
        hard_la = has_la and (la_race or True)  # soft: if need_la treat as at least M/H path
        # Tighten hard_la: race or army < 3
        army = _safe_int(getattr(player, "size_largest_army", 0), 0) or 0
        hard_la = has_la and (la_race or army < 2)
        hard_vp = has_vp and (vp_eff >= 8 or (10 - vp_eff) <= 2)

        if hard_la or hard_vp:
            dc_posture = "H"
            dc_clause = "trade for OWG" if not can_buy else "buy now"
            if hard_la and has_vp:
                dc_clause = "Knight first"
            elif hard_la:
                dc_clause = "Knight / army"
            elif hard_vp:
                dc_clause = "VP race"
        elif can_buy and (req_d > 0 or has_la or has_vp):
            dc_posture = "M"
            dc_clause = "buy if OWG"
        elif expand_primary:
            dc_posture = "L"
            dc_clause = "settle first"
        else:
            dc_posture = "M"
            dc_clause = "opportunistic"

        if has_tfr and not has_la and not has_vp:
            dc_focus = "LR"
            if not dc_clause:
                dc_clause = "TFR / LR"
        elif has_la and has_vp:
            dc_focus = "LA/VP"
            if hard_la and dc_clause != "Knight first":
                dc_clause = "Knight first"
        elif has_la:
            dc_focus = "LA"
        elif has_vp:
            dc_focus = "VP"
        elif has_tfr:
            dc_focus = "LR"
        else:
            dc_focus = "LA/VP" if (has_la or has_vp) else None
            if req_d > 0 and not dc_focus:
                dc_focus = "LA/VP"  # generic DC residual

    also = None
    parked = None
    if dc_residual and now != "DC" and dc_posture:
        also = f"DC: {dc_posture} · focus {dc_focus or '—'}"
        if dc_clause:
            also = f"{also} — {dc_clause}"
    if need_la and now != "LA" and not (dc_focus and "LA" in str(dc_focus)):
        parked = "LA until army gap tightens" if not la_race else None

    bag.update(
        {
            "ok": True,
            "residual": residual,
            "now": now,
            "word": word,
            "also": also,
            "parked": parked,
            "dc_posture": dc_posture,
            "dc_focus": dc_focus,
            "dc_clause": dc_clause,
            "req_cities": req_c,
            "req_settles": req_s,
            "req_roads": req_r,
            "req_dcards": req_d,
        }
    )
    bag["cs"] = {
        "pln1_residual": residual[:200] if residual else None,
        "pln1_now": now,
        "pln1_word": word,
        "pln1_also": (also[:120] if also else None),
        "pln1_parked": (parked[:120] if parked else None),
        "pln1_dc_posture": dc_posture,
        "pln1_dc_focus": dc_focus,
        "pln1_dc_clause": (dc_clause[:80] if dc_clause else None),
    }
    return bag


def cs_fields_from_pln1(player: Any) -> Dict[str, Any]:
    keys = (
        "pln1_residual",
        "pln1_now",
        "pln1_word",
        "pln1_also",
        "pln1_parked",
        "pln1_dc_posture",
        "pln1_dc_focus",
        "pln1_dc_clause",
    )
    out: Dict[str, Any] = {k: None for k in keys}
    snap = getattr(player, "pln1_snapshot", None) if player is not None else None
    if not isinstance(snap, Mapping):
        # also accept nested on plan_snapshot
        ps = getattr(player, "plan_snapshot", None) if player is not None else None
        if isinstance(ps, Mapping):
            nested = ps.get("pln1")
            if isinstance(nested, Mapping):
                snap = nested
            elif isinstance(ps.get("cs"), Mapping):
                # fields may already be merged into plan cs
                for k in keys:
                    v = (ps.get("cs") or {}).get(k)
                    if v is not None and str(v).strip() != "":
                        out[k] = str(v)[:200]
                return out
    if not isinstance(snap, Mapping):
        return out
    cs = snap.get("cs") if isinstance(snap.get("cs"), Mapping) else snap
    if not isinstance(cs, Mapping):
        return out
    for k in keys:
        v = cs.get(k)
        if v is not None and str(v).strip() != "":
            out[k] = str(v)[:200]
    return out


def pln1_lines_for_dig(row: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Dig PLN1 display lines from CS columns.

    Way line = ``way_id |`` absolute 142-way composition from CSV
    (same as STR Tags: Cities/Settlements, not residual).
    """
    lines: List[Tuple[str, str]] = []
    residual = str(row.get("pln1_residual") or "").strip()
    now = str(row.get("pln1_now") or "").strip()
    word = str(row.get("pln1_word") or "").strip()
    also = str(row.get("pln1_also") or "").strip()
    parked = str(row.get("pln1_parked") or "").strip()
    posture = str(row.get("pln1_dc_posture") or "").strip()
    focus = str(row.get("pln1_dc_focus") or "").strip()
    clause = str(row.get("pln1_dc_clause") or "").strip()

    wid = str(row.get("sticky_way_id") or row.get("way_id") or "").strip()
    def_comp = ""
    try:
        from core.strategy_way_residual import (
            format_tags_join,
            load_way_requirement,
            way_def_tags,
        )

        strat = load_way_requirement(wid or row.get("way_id"))
        tags = way_def_tags(strat) if strat is not None else []
        if tags:
            def_comp = format_tags_join(tags)
    except Exception:
        def_comp = ""
    # Fallback: CS way_def_tags cell / residual only if CSV load failed
    if not def_comp:
        def_comp = str(row.get("way_def_tags") or "").strip() or residual

    if not def_comp and not now and not posture:
        return [("note", "PLN1 not sampled (L0 or PLAN_SNAPSHOT off)")]

    if def_comp or wid:
        way_line = f"{wid} | {def_comp}" if wid and def_comp else (wid or def_comp)
        lines.append(("Way", way_line))
    # Dig §6: PLN1 panel draws the component table + one red priority line.
    # Do **not** emit Now/Also/Parked/DC prose here — Dig used to reprint them
    # under R/DC and look unfinished.
    _ = (now, word, also, parked, posture, focus, clause)
    return lines


__all__ = [
    "build_pln1_snapshot",
    "cs_fields_from_pln1",
    "pln1_lines_for_dig",
]
