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
    # Dig CS often leaves risk_level empty — fall back to plan_why / catalog tip.
    why = str(row.get("plan_why") or "").strip().lower()
    if why == "hot":
        return "high"
    if why == "race":
        return "med"
    tip = str(row.get("sticky_target_id") or row.get("ba_target_id") or "").strip()
    cat = str(row.get("plan_catalog") or "")
    if tip and cat:
        # ``S36:2:6.8:19.5:H:2.8`` → risk letter before last fields
        for part in cat.split(";"):
            part = part.strip()
            if not part:
                continue
            if part.upper().startswith(f"S{tip}:") or part.upper().startswith(f"C{tip}:"):
                bits = part.split(":")
                for b in bits:
                    bu = b.strip().upper()
                    if bu in ("H", "HIGH"):
                        return "high"
                    if bu in ("M", "MED", "MEDIUM"):
                        return "med"
                break
    return "low"


def _parse_owned_road_edges(row: Mapping[str, Any], player_id: Any = None) -> set:
    """Owned undirected edges from board_blob ``R=pid:a-b,...`` when present."""
    out: set = set()
    blob = str(row.get("board_blob") or "").strip()
    if not blob:
        return out
    pid = None
    try:
        if player_id is not None and str(player_id).strip() != "":
            pid = int(float(player_id))
        elif row.get("player_id") not in (None, ""):
            pid = int(float(row.get("player_id")))
    except Exception:
        pid = None
    for chunk in blob.split(";"):
        chunk = chunk.strip()
        if not chunk.upper().startswith("R="):
            continue
        body = chunk[2:]
        for piece in body.split(","):
            piece = piece.strip()
            if ":" not in piece or "-" not in piece:
                continue
            owner_s, edge_s = piece.split(":", 1)
            try:
                owner = int(float(owner_s))
            except Exception:
                continue
            if pid is not None and owner != pid:
                continue
            if edge_s.count("-") != 1:
                continue
            a_s, b_s = edge_s.split("-", 1)
            try:
                a, b = int(a_s), int(b_s)
            except Exception:
                continue
            out.add((min(a, b), max(a, b)))
    return out


def _forward_road_target(path_compact: str, rem_r: int, owned_edges: set) -> str:
    """Drop owned (or already-built prefix) edges so R Target is forward-looking."""
    if not path_compact:
        return ""
    segs: List[Tuple[int, int]] = []
    for part in path_compact.replace(";", ",").split(","):
        part = part.strip()
        if "-" not in part or part.count("-") != 1:
            continue
        a_s, b_s = part.split("-", 1)
        try:
            a, b = int(a_s), int(b_s)
        except Exception:
            continue
        segs.append((min(a, b), max(a, b)))
    if not segs:
        return path_compact
    if owned_edges:
        segs = [e for e in segs if e not in owned_edges]
    elif rem_r > 0 and len(segs) > rem_r:
        # No ownership map: keep the last rem_r segments (prefix assumed built).
        segs = segs[-int(rem_r) :]
    elif rem_r == 0:
        return ""
    return ", ".join(f"{a}-{b}" for a, b in segs)


def _next_settle_from_catalog(row: Mapping[str, Any]) -> str:
    """First settle tip id from plan_catalog (forward S target when sticky is C/DC)."""
    cat = str(row.get("plan_catalog") or "")
    for part in cat.split(";"):
        part = part.strip()
        if len(part) < 2 or part[0] not in "Ss":
            continue
        body = part[1:]
        tid_s = body.split(":", 1)[0]
        try:
            return str(int(tid_s))
        except Exception:
            continue
    return ""


def _owned_structure_ids(row: Mapping[str, Any], player_id: Any = None) -> set:
    """Owned S/C intersection ids from board_blob when present."""
    out: set = set()
    blob = str(row.get("board_blob") or "").strip()
    if not blob:
        return out
    pid = None
    try:
        if player_id is not None and str(player_id).strip() != "":
            pid = int(float(player_id))
        elif row.get("player_id") not in (None, ""):
            pid = int(float(row.get("player_id")))
    except Exception:
        pid = None
    for chunk in blob.split(";"):
        chunk = chunk.strip()
        if not (chunk.upper().startswith("S=") or chunk.upper().startswith("C=")):
            continue
        body = chunk[2:]
        for piece in body.split(","):
            piece = piece.strip()
            if ":" not in piece:
                continue
            owner_s, id_s = piece.split(":", 1)
            try:
                owner = int(float(owner_s))
                nid = int(float(id_s))
            except Exception:
                continue
            if pid is None or owner == pid:
                out.add(nid)
    return out


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
      - DC row under R; Dig §6: no Comp=New / Now/Also below R/DC
      - Dig §6: mark priority Buy/Build component row(s) with ``prio`` (Dig paints red)
      - R Target: LR tips when LR owns Why; settle-path when S owns Why
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
    # Dig / CS row may stamp way_lr even when CSV load is sparse
    if not has_lr:
        has_lr = str(row.get("way_lr") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "lr",
        )
    has_la = bool(
        getattr(strat, "biggest_army", False)
        or getattr(strat, "largest_army", False)
    )
    if not has_la:
        has_la = str(row.get("way_la") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "la",
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
    sticky_kind = str(row.get("sticky_target_kind") or "").strip().upper()
    roads_fp = str(row.get("sticky_roads_fp") or row.get("ba_roads_fp") or "").strip()
    risk = _risk_from_row(row)
    path_compact = format_road_path_compact(roads_fp)
    rem_r = max(0, _safe_int(res.get("req_roads"), csv_r))
    owned_edges = _parse_owned_road_edges(row, row.get("player_id"))
    owned_structs = _owned_structure_ids(row, row.get("player_id"))
    # Forward-looking road Target (WP-A): drop owned / built prefix edges
    path_forward = _forward_road_target(path_compact, rem_r, owned_edges)
    # total dist from fingerprint edge count when present
    total_r = rem_r
    if path_forward:
        total_r = max(rem_r, path_forward.count("-"))
    elif path_compact:
        total_r = max(rem_r, path_compact.count("-"))
    elif csv_r:
        total_r = max(rem_r, csv_r)
    # Forward S Target (WP-A): never paint owned S or city-upgrade id on S row
    s_need_n = int(res.get("s_need_v5") or 0)
    s_target = ""
    if sticky_kind in ("S", "SETTLE", "SETTLEMENT", "NEW_SETTLEMENT", ""):
        try:
            tid_i = int(float(sticky_tgt)) if sticky_tgt else None
        except Exception:
            tid_i = None
        if tid_i is not None and tid_i in owned_structs:
            s_target = _next_settle_from_catalog(row) if s_need_n > 0 else ""
        elif sticky_kind in ("S", "SETTLE", "SETTLEMENT", "NEW_SETTLEMENT") and sticky_tgt:
            s_target = sticky_tgt if s_need_n > 0 else ""
        elif sticky_tgt and sticky_kind == "" and s_need_n > 0:
            s_target = sticky_tgt
    elif sticky_kind in ("C", "CITY", "DCARD", "LA", "LR", "VP"):
        # City/DC sticky: S Target = next settle tip if still need expand
        s_target = _next_settle_from_catalog(row) if s_need_n > 0 else ""
    elif s_need_n > 0:
        s_target = _next_settle_from_catalog(row) or (sticky_tgt if sticky_kind.startswith("S") else "")

    # Engine: sticky settle path that also delivers LR claim
    engine = False
    if has_lr and sticky_tgt and word.lower() in ("engine",):
        engine = True
    if has_lr and str(row.get("pln1_now") or "").upper() in ("S", "SETTLE", "SETTLEMENT"):
        if risk == "low" and rem_r <= 2:
            # soft: short remaining path toward sticky often engines LR
            pass

    # LR owns main focus when word=Engine or live LR claim/grow plan is claim-now.
    lr_label = str(row.get("lr_plan_label") or row.get("plan_lr_pkg") or "").strip().lower()
    lr_claim_now = bool(
        lr_label.startswith("lr claim")
        or "|claim|" in lr_label
        or str(row.get("lr_plan_claim") or "").strip().lower() in ("1", "true", "yes")
    )
    lr_engine_focus = bool(
        has_lr
        and (
            word.lower() == "engine"
            or engine
            or lr_claim_now
        )
    )

    # WP-ARB1: exactly one component owns Why (Race/Hot/Engine/Prio).
    # Priority: LR Engine/claim → Hot/Race settle → sticky C/DC → expand S → LR rem → C → DC.
    settle_focus = sticky_kind in ("S", "SETTLE", "SETTLEMENT", "NEW_SETTLEMENT", "")
    hot_settle = bool(settle_focus and sticky_tgt and risk in ("high", "med") and s_need_n > 0)
    city_focus = sticky_kind in ("C", "CITY", "CITY_UPGRADE")
    dc_focus = sticky_kind in ("DCARD", "DC", "LA", "VP")
    why_owner = "S"
    if lr_engine_focus or lr_claim_now:
        why_owner = "LR"
    elif hot_settle or (settle_focus and s_need_n > 0 and sticky_tgt):
        why_owner = "S"
    elif city_focus and max(0, _safe_int(res.get("req_cities"), csv_c)) > 0:
        why_owner = "C"
    elif dc_focus or (s_need_n <= 0 and (has_la or csv_vp)):
        why_owner = "DC"
    elif s_need_n > 0:
        why_owner = "S"
    elif has_lr and _safe_int(row.get("size_longest_route") or row.get("longest_path"), 0) < 5:
        why_owner = "LR"
    elif max(0, _safe_int(res.get("req_cities"), csv_c)) > 0:
        why_owner = "C"
    elif has_la or csv_vp:
        why_owner = "DC"

    struct_why = pln1_why_for_structure(risk=risk, engine=engine and why_owner != "LR")
    if word.lower() == "engine" and why_owner != "LR":
        struct_why = "Engine"
    if why_owner == "LR":
        struct_why = ""

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
        # WP-ARB1: blank Why on non-owners (Expand first only set on C by caller)
        why_out = why
        if why and why not in ("",) and comp not in ("", "New", "="):
            owner_comps = {
                "LR": ("LR",),
                "S": ("S",),
                "C": ("C",),
                "DC": ("DC", "LA"),
            }.get(why_owner, (why_owner,))
            if comp not in owner_comps:
                why_out = ""
        rows_out.append(
            {
                "comp": comp,
                "tag": tag,
                "need": need,
                "why": why_out,
                "target": target,
                "red": "1" if red else "",
                "spacer": "1" if spacer else "",
                "why_owner": why_owner if comp not in ("", "=", "New") else "",
            }
        )

    # LA / VP buy paths (WP-D): Dig Need uses min(knight×2, rem_vp×5) when both apply
    army = _safe_int(row.get("size_largest_army") or row.get("army_size"), 0)
    la_flag = str(row.get("way_la") or "").lower()
    held_la = la_flag in ("0", "false", "no") or army >= 3
    need_la_chase = bool(has_la and not held_la)
    knights_need = max(0, 3 - army) if need_la_chase else 0
    rem_vp_n = max(0, _safe_int(res.get("remaining_vp_cards"), csv_vp)) if csv_vp else 0
    try:
        from core.strategy_timing import (
            EXPECTED_DEV_CARD_BUYS_PER_KNIGHT,
            EXPECTED_DEV_CARD_BUYS_PER_VP_CARD,
        )

        k_mult = int(EXPECTED_DEV_CARD_BUYS_PER_KNIGHT)
        vp_mult = int(EXPECTED_DEV_CARD_BUYS_PER_VP_CARD)
    except Exception:
        k_mult, vp_mult = 2, 5
    knight_buys = knights_need * k_mult if knights_need else 0
    vp_buys = rem_vp_n * vp_mult if rem_vp_n else 0

    if has_la:
        # LA row: show knight-path buys while still chasing army
        need_la = f"{knight_buys}xDC" if knight_buys else ""
        why_la = ""
        if why_owner == "DC" and not held_la:
            why_la = "Calm" if army == 0 and knights_need >= 3 else (struct_why if knight_buys else "")
        if held_la:
            need_la = ""
            why_la = ""
        add("LA", "", need_la, why_la, "")

    # LR: Need rem/claim — claim length default 5
    lr_path_tgt = ""
    rem_lr = 0
    if has_lr:
        own_path = _safe_int(row.get("size_longest_route") or row.get("longest_path"), 0)
        claim = 5
        rem_lr = max(0, claim - own_path)
        need_lr = f"{rem_lr}/{claim}" if rem_lr else ""
        why_lr = ""
        lr_red = False
        if why_owner == "LR":
            if lr_engine_focus or lr_claim_now or word.lower() == "engine":
                why_lr = "Engine"
                lr_red = True
            elif rem_lr and risk in ("med", "high"):
                why_lr = pln1_why_for_structure(risk=risk)
            elif rem_lr:
                why_lr = "Calm"
            # Guidance: next LR roads (Dig v7 — specify next 2–3 when LR owns Why)
            lr_path_tgt = format_road_path_compact(
                row.get("lr_plan_roads_fp") or row.get("plan_lr_roads") or path_forward
            )
        add("LR", "", need_lr, why_lr if (rem_lr or why_lr) else "", lr_path_tgt if why_owner == "LR" else "", red=lr_red)

    req_c_n = max(0, _safe_int(res.get("req_cities"), csv_c))
    if csv_c:
        # WP-ARB1: Expand first only while settle expand still remains
        c_why = ""
        if why_owner == "C":
            if s_need_n > 0:
                c_why = "Expand first"
            elif req_c_n > 0:
                c_why = struct_why or "Prio"
        elif why_owner != "C" and s_need_n > 0 and req_c_n > 0:
            # Non-owner: never paint Expand first (was the Dig false signal)
            c_why = ""
        add(
            "C",
            str(csv_c),
            str(req_c_n),
            c_why,
            "",
        )
    if csv_s or res.get("s_need_v5", 0) or s_target or sticky_tgt:
        s_why = ""
        if why_owner == "S" and s_need_n > 0:
            s_why = struct_why if (s_target or sticky_tgt or s_need_n) else ""
        add(
            "S",
            str(csv_s) if csv_s else "",
            str(s_need_n),
            s_why,
            s_target,
        )
    if csv_vp:
        rem_vp = rem_vp_n
        # VP row: show VP-path buys (rem_vp×5), not joint 10
        need_s = f"{vp_buys}xDC" if vp_buys else (str(rem_vp) if rem_vp else "")
        add("VP", str(csv_vp), need_s, "", "VP" if rem_vp else "")

    # Roads — Dig §6: R Target guides LR tips OR settle path (by why_owner)
    if rem_r or path_forward or path_compact or csv_r or (why_owner == "LR" and lr_path_tgt):
        add("=", "", "", "", "")
        need_r = f"{rem_r}/{total_r}" if total_r else (str(rem_r) if rem_r else "")
        r_why = ""
        if why_owner == "LR":
            # Dig §6: R Target = next LR road tips when LR has priority
            r_tgt = lr_path_tgt or path_forward
        elif why_owner == "S":
            # Dig §6: R Target = remaining settle-path (forward only; not built prefix)
            r_tgt = path_forward
            if not r_tgt and rem_r > 0 and sticky_tgt:
                r_tgt = (
                    f"→S@{sticky_tgt}"
                    if not str(sticky_tgt).upper().startswith("S")
                    else f"→{sticky_tgt}"
                )
        else:
            r_tgt = ""  # city/DC owner: no settle/LR guidance on R
        add(
            "R",
            "",
            need_r if rem_r or path_forward or (why_owner == "LR" and lr_path_tgt) else "",
            r_why,
            r_tgt,
        )

    # DC play / buy row under R (LA and/or VP)
    # WP-D: Dig Need = min(knight×2, rem_vp×5) when both paths apply (e.g. 6 not 10)
    if has_la or csv_vp:
        rem_vp = rem_vp_n
        csv_dc = max(0, _safe_int(res.get("req_dcards"), 0))
        candidates = [c for c in (knight_buys, vp_buys, csv_dc) if c and c > 0]
        if need_la_chase and rem_vp > 0 and knight_buys and vp_buys:
            dc_buy = min(knight_buys, vp_buys)
            # Never show worse than residual CSV if CSV already tightened
            if csv_dc > 0:
                dc_buy = min(dc_buy, csv_dc)
        elif need_la_chase and knight_buys:
            dc_buy = min(csv_dc, knight_buys) if csv_dc else knight_buys
        elif rem_vp > 0 and vp_buys:
            dc_buy = min(csv_dc, vp_buys) if csv_dc else vp_buys
        else:
            dc_buy = csv_dc or (knight_buys or vp_buys)
        tag = ""
        if need_la_chase and rem_vp:
            tag = "LA+VP"
        elif need_la_chase or (has_la and not held_la):
            tag = "LA"
        elif has_la and held_la and rem_vp:
            tag = "VP"
        elif rem_vp:
            tag = "VP"
        elif has_la and held_la:
            tag = "LA"
        need_dc = ""
        if dc_buy and knights_need:
            need_dc = f"{dc_buy}xDC {knights_need}/3"
        elif dc_buy:
            need_dc = f"{dc_buy}xDC"
        elif knights_need:
            need_dc = f"{knights_need}/3"
        tgt = "VP" if tag == "LA+VP" else ("LA" if tag == "LA" else ("VP" if tag == "VP" else ""))
        why_dc = ""
        if why_owner == "DC" and (dc_buy or knights_need):
            why_dc = struct_why
            if tag == "LA" and army == 0:
                why_dc = "Calm"
        if need_dc or tag:
            add("DC", tag, need_dc, why_dc, tgt)

    # Dig §6: mark best Buy/Build component row(s) — Dig paints those rows red.
    # No prose banner below R/DC (that was mistaken for Best-Action).
    prio_comps: set = set()
    if why_owner == "LR":
        prio_comps.add("LR")
        prio_comps.add("R")  # roads are the build vehicle for LR
    elif why_owner == "S":
        prio_comps.add("S")
        if rem_r > 0 or path_forward:
            prio_comps.add("R")  # road(s) still needed toward settle
    elif why_owner == "C":
        prio_comps.add("C")
        if s_need_n > 0:
            prio_comps.add("S")  # expand-first still needs a settle
    elif why_owner == "DC":
        prio_comps.add("DC")
        if need_la_chase and not held_la:
            prio_comps.add("LA")
        elif rem_vp_n > 0:
            prio_comps.add("VP")

    for r in rows_out:
        comp = str(r.get("comp") or "")
        if comp in prio_comps:
            r["prio"] = "1"
            r["red"] = "1"

    return {
        "headers": headers,
        "rows": rows_out,
        "empty": not rows_out,
        "way_id": wid,
        "why_owner": why_owner,
        "priority_comps": sorted(prio_comps),
    }


__all__ = ["pln1_component_table"]
