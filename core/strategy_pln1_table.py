"""V5-D + refinements v1: PLN1 absolute component table (Comp / Tag / Need / Why / Target)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _risk_from_row(row: Mapping[str, Any]) -> str:
    r = str(row.get("risk_level") or row.get("sticky_risk") or "").strip().lower()
    if r in ("m", "med", "medium"):
        return "med"
    if r in ("h", "high", "blocked", "crit"):
        return "high"
    return "low"


def pln1_component_table(
    row: Mapping[str, Any],
    *,
    game: Any = None,
    player: Any = None,
) -> Dict[str, Any]:
    """Build Dig table model under PLN1 Way.

    Refinements v1:
      - Need fractions for R (rem/total) and LR (rem/claim_len)
      - Why: Calm / Prio / Race / Engine / Hot
      - Target roads compact ``50-51, 51-62``
      - DC row under R; spacer + red next-buy/build hint row
    """
    headers = ("Comp", "Tag", "Need", "Why", "Target")
    wid = row.get("sticky_way_id") or row.get("way_id")
    rows_out: List[Dict[str, str]] = []
    try:
        from core.strategy_way_residual import load_way_requirement
        from core.strategy_pln_words import (
            format_road_path_compact,
            pln1_why_for_structure,
        )
    except Exception:
        return {"headers": headers, "rows": [], "empty": True, "way_id": wid}

    strat = load_way_requirement(wid)
    if strat is None:
        return {"headers": headers, "rows": [], "empty": True, "way_id": wid}

    csv_c = _safe_int(getattr(strat, "cities", 0), 0)
    csv_s = _safe_int(getattr(strat, "settlements", 0), 0)
    csv_vp = _safe_int(getattr(strat, "victory_point_cards", 0), 0)
    csv_r = _safe_int(getattr(strat, "roads_to_build", 0), 0)
    has_lr = bool(getattr(strat, "longest_road", False))
    has_la = bool(
        getattr(strat, "biggest_army", False)
        or getattr(strat, "largest_army", False)
    )

    res: Dict[str, Any] = {}
    try:
        res = {
            "req_cities": _safe_int(row.get("req_cities"), csv_c),
            "req_settles": _safe_int(row.get("req_settles"), csv_s),
            "req_roads": _safe_int(row.get("req_roads"), csv_r),
            "req_dcards": _safe_int(row.get("req_dcards"), 0),
            "remaining_vp_cards": _safe_int(row.get("remaining_vp_cards"), csv_vp),
            "need_la": bool(has_la),
            "need_lr": bool(has_lr),
        }
        n_c = _safe_int(row.get("cities_owned"), 0)
        n_s = _safe_int(row.get("settlements_owned"), 0)
        s_need = max(0, csv_c + csv_s - n_c - n_s)
        res["s_need_v5"] = s_need
    except Exception:
        n_c, n_s = 0, 0
        res["s_need_v5"] = max(0, csv_c + csv_s)

    word = str(row.get("pln1_word") or "").strip()
    sticky_tgt = str(row.get("sticky_target_id") or row.get("ba_target_id") or "").strip()
    roads_fp = str(row.get("sticky_roads_fp") or row.get("ba_roads_fp") or "").strip()
    risk = _risk_from_row(row)
    path_compact = format_road_path_compact(roads_fp)
    rem_r = max(0, _safe_int(res.get("req_roads"), csv_r))
    # total dist from fingerprint edge count when present
    total_r = rem_r
    if path_compact:
        total_r = max(rem_r, path_compact.count("-"))
    elif csv_r:
        total_r = max(rem_r, csv_r)

    # Engine: sticky settle path that also delivers LR claim
    engine = False
    if has_lr and sticky_tgt and word.lower() in ("engine",):
        engine = True
    if has_lr and str(row.get("pln1_now") or "").upper() in ("S", "SETTLE", "SETTLEMENT"):
        if risk == "low" and rem_r <= 2:
            # soft: short remaining path toward sticky often engines LR
            pass

    struct_why = pln1_why_for_structure(risk=risk, engine=engine)
    if word.lower() == "engine":
        struct_why = "Engine"

    def add(
        comp: str,
        tag: str,
        need: str,
        why: str,
        target: str = "",
        *,
        red: bool = False,
        spacer: bool = False,
    ) -> None:
        rows_out.append(
            {
                "comp": comp,
                "tag": tag,
                "need": need,
                "why": why,
                "target": target,
                "red": "1" if red else "",
                "spacer": "1" if spacer else "",
            }
        )

    # LA: Need = statistical DCard buys (stub: 2× knights still needed ≈ 6 DC)
    if has_la:
        la_flag = str(row.get("way_la") or "").lower()
        held_la = la_flag in ("0", "false", "no")  # confusing; prefer army size
        army = _safe_int(row.get("size_largest_army") or row.get("army_size"), 0)
        knights_need = max(0, 3 - army)
        # statistical buys: ~2 draws per knight needed (conservative stub)
        dc_buy = knights_need * 2 if knights_need else 0
        need_la = f"{dc_buy}xDC" if dc_buy else ""
        why_la = "Calm" if army == 0 and knights_need >= 3 else (struct_why if dc_buy else "")
        if held_la and army >= 3:
            need_la = ""
            why_la = ""
        add("LA", "", need_la, why_la, "")

    # LR: Need rem/claim — claim length default 5
    if has_lr:
        own_path = _safe_int(row.get("size_longest_route") or row.get("longest_path"), 0)
        claim = 5
        rem_lr = max(0, claim - own_path)
        need_lr = f"{rem_lr}/{claim}" if rem_lr else ""
        why_lr = "Engine" if engine or (rem_lr and sticky_tgt) else ("Calm" if rem_lr else "")
        if rem_lr and risk in ("med", "high"):
            why_lr = pln1_why_for_structure(risk=risk)
        add("LR", "", need_lr, why_lr if rem_lr else "", "")

    if csv_c:
        add(
            "C",
            str(csv_c),
            str(max(0, _safe_int(res.get("req_cities"), csv_c))),
            "Expand first" if max(0, _safe_int(res.get("req_cities"), 0)) else "",
            "",
        )
    if csv_s or res.get("s_need_v5", 0):
        add(
            "S",
            str(csv_s) if csv_s else "",
            str(int(res.get("s_need_v5") or 0)),
            struct_why if sticky_tgt or int(res.get("s_need_v5") or 0) else "",
            sticky_tgt if sticky_tgt else "",
        )
    if csv_vp:
        rem_vp = max(0, _safe_int(res.get("remaining_vp_cards"), csv_vp))
        dc = max(0, _safe_int(res.get("req_dcards"), 0))
        need_s = f"{dc}xDC" if dc else str(rem_vp)
        add("VP", str(csv_vp), need_s, "", "VP" if rem_vp else "")

    # Roads
    if rem_r or path_compact or csv_r:
        add("=", "", "", "", "")
        need_r = f"{rem_r}/{total_r}" if total_r else (str(rem_r) if rem_r else "")
        add("R", "", need_r, struct_why if rem_r else "", path_compact)

    # DC play / buy row under R (LA and/or VP)
    if has_la or csv_vp:
        army = _safe_int(row.get("size_largest_army") or row.get("army_size"), 0)
        knights_need = max(0, 3 - army) if has_la else 0
        rem_vp = max(0, _safe_int(res.get("remaining_vp_cards"), csv_vp)) if csv_vp else 0
        dc_buy = max(0, _safe_int(res.get("req_dcards"), 0))
        if not dc_buy and knights_need:
            dc_buy = knights_need * 2
        tag = ""
        if has_la and rem_vp:
            tag = "LA+VP"
        elif has_la:
            tag = "LA"
        elif rem_vp:
            tag = "VP"
        need_dc = ""
        if dc_buy and knights_need:
            need_dc = f"{dc_buy}xDC {knights_need}/3"
        elif dc_buy:
            need_dc = f"{dc_buy}xDC"
        elif knights_need:
            need_dc = f"{knights_need}/3"
        tgt = "VP" if tag == "LA+VP" else ("LA" if tag == "LA" else ("VP" if tag == "VP" else ""))
        why_dc = struct_why if (dc_buy or knights_need) else ""
        if tag == "LA" and army == 0:
            why_dc = "Calm"
        if need_dc or tag:
            add("DC", tag, need_dc, why_dc, tgt)

    # Spacer + red next buy/build line (ignores TwB/TwP)
    next_lab = ""
    if sticky_tgt and rem_r == 0:
        next_lab = "New: Settle" if risk == "low" else "New: Settle (Race)"
    elif sticky_tgt and rem_r > 0:
        # equal prio when also need DC buys
        dc_need = max(0, _safe_int(res.get("req_dcards"), 0))
        if dc_need and rem_r:
            next_lab = "Build road or buy DCard"
        else:
            next_lab = "Build road"
    elif max(0, _safe_int(res.get("req_dcards"), 0)):
        next_lab = "Buy DCard"
    if next_lab:
        add("", "", "", "", "", spacer=True)
        add("New", "", next_lab, "", "", red=True)

    return {
        "headers": headers,
        "rows": rows_out,
        "empty": not rows_out,
        "way_id": wid,
        "next_action": next_lab,
    }


__all__ = ["pln1_component_table"]
