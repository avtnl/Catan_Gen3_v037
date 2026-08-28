"""WP5: hybrid PLAN / WHY2 snapshot for dig (CS-first, no dig-time SE).

Live: build compact plan rows on L2 / explore (and optional ETA-refresh), store on
player, write CS dig fields. Dig: parse CS strings into PLAN / WHY2 lines + Show
circle payload. Does not mutate the board.

See docs/SE_improvement_plan_v2.md §4, v3 §3.3.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Dig Show radii — v4 P0e: base = port black-dot radius 5; own ring 8, then +4
# per seat in turn order (12 / 16 / 20). Stroke ~2px leaves gray gap around dots.
_SHOW_COLORS: Tuple[str, ...] = ("Blue", "Red", "White", "Orange")
PORT_DOT_RADIUS = 5
SHOW_RING_OWN = 8
SHOW_RING_STEP = 4

def _build_show_radius_matrix() -> Dict[str, Dict[str, int]]:
    order = list(_SHOW_COLORS)
    n = len(order)
    out: Dict[str, Dict[str, int]] = {}
    for ti, turn in enumerate(order):
        row: Dict[str, int] = {}
        for oi, owner in enumerate(order):
            offset = (oi - ti) % n
            row[owner] = SHOW_RING_OWN + SHOW_RING_STEP * offset
        out[turn] = row
    return out


SHOW_RADIUS_MATRIX: Dict[str, Dict[str, int]] = _build_show_radius_matrix()

# Legacy fixed-by-owner table (stage3and4 absolute). Prefer radius_for_show.
PLAYER_RADIUS_BY_COLOR: Dict[str, int] = {
    "Blue": 8,
    "Red": 12,
    "White": 16,
    "Orange": 20,
}

# Legacy alias (PLAN risk text only; Show uses radius_for_show)
RISK_RADIUS: Dict[str, int] = {
    "low": 8,
    "med": 12,
    "medium": 12,
    "high": 16,
    "blocked": 20,
    "crit": 20,
}

PLAN_SETTLE_MAX = 6
PLAN_CITY_MAX = 4
# PLN2 Dig table: max 8 data rows (sort Tgt+ETA); 9th = overflow C/S labels
PLAN_CATALOG_DETAIL = 8


def _risk_letter(risk: Any) -> str:
    b = _risk_bucket(risk)
    return {"low": "-", "med": "M", "medium": "M", "high": "H", "blocked": "B", "crit": "H"}.get(
        b, "-"
    )


def _best_opp_eta_from_competitors(comp: Any, threats: Any = None) -> Optional[float]:
    """Smallest opponent ETA from compact ``pid@eta`` or threat list."""
    best: Optional[float] = None
    s = str(comp or "")
    for bit in s.split(","):
        bit = bit.strip()
        if "@" not in bit:
            continue
        eta = _safe_float(bit.split("@", 1)[1])
        if eta is None:
            continue
        best = eta if best is None else min(best, eta)
    for th in list(threats or []):
        if not isinstance(th, Mapping):
            continue
        eta = _safe_float(th.get("eta_own_turns") or th.get("eta") or th.get("turns"))
        if eta is None:
            continue
        best = eta if best is None else min(best, eta)
    return best


def _fmt_num(v: Optional[float]) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "-"


def resolve_se_pick_id(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
) -> Optional[int]:
    """Sticky ∪ rec ∪ BA target id (BA road → sticky/rec settle). Locked A."""
    preferred = preferred if isinstance(preferred, Mapping) else {}
    candidates: List[Optional[int]] = []

    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        if isinstance(c, Mapping):
            candidates.append(_safe_int(c.get("locked_rec_target_id")))
    except Exception:
        pass

    for key in (
        "locked_rec_target_id",
        "recommendation_target_id",
        "sticky_target_id",
        "supporting_action_target_id",
    ):
        candidates.append(_safe_int(preferred.get(key)))

    if game is not None:
        try:
            audit = getattr(game, "current_board_way_audit", None)
            if isinstance(audit, Mapping):
                candidates.append(_safe_int(audit.get("recommendation_target_id")))
            elif audit is not None:
                candidates.append(_safe_int(getattr(audit, "recommendation_target_id", None)))
        except Exception:
            pass
        try:
            ba = getattr(game, "current_best_action", None)
            if isinstance(ba, Mapping):
                act = str(ba.get("action") or ba.get("type") or "").lower()
                tid = _safe_int(
                    ba.get("target_id")
                    or ba.get("ba_target_id")
                    or ba.get("intersection_id")
                )
                if tid is not None:
                    if any(x in act for x in ("settle", "city", "upgrade")):
                        candidates.append(tid)
                    elif "road" in act:
                        # road toward settle — prefer sticky/rec already queued
                        pass
                    else:
                        candidates.append(tid)
        except Exception:
            pass

    for tid in candidates:
        if tid is not None and int(tid) >= 0:
            return int(tid)
    return None


def _catalog_sort_key(row: Mapping[str, Any]) -> Tuple:
    t = _safe_float(row.get("target") or row.get("eta"))
    w = _safe_float(row.get("eta_win"))
    # missing → large so timed rows sort first
    tt = float(t) if t is not None else 9000.0
    ww = float(w) if w is not None else 9000.0
    return (tt + ww, tt, int(row.get("id") or 0))


def encode_plan_catalog_row(row: Mapping[str, Any]) -> str:
    """``S{id}:{dist}:{target}:{eta_win}:{risk}:{delta}`` or ``C{id}:{target}:{eta_win}``."""
    kind = str(row.get("kind") or "S").upper()
    tid = _safe_int(row.get("id"), 0) or 0
    if kind == "C":
        return f"C{tid}:{_fmt_num(_safe_float(row.get('target') or row.get('eta')))}:{_fmt_num(_safe_float(row.get('eta_win')))}"
    dist = _safe_int(row.get("dist"), 0) or 0
    risk = _risk_letter(row.get("risk"))
    delta = row.get("delta_t")
    delta_s = _fmt_num(_safe_float(delta)) if delta is not None else "-"
    return (
        f"S{tid}:{dist}:{_fmt_num(_safe_float(row.get('target') or row.get('eta')))}:"
        f"{_fmt_num(_safe_float(row.get('eta_win')))}:{risk}:{delta_s}"
    )


def parse_plan_catalog(cs: Any) -> List[Dict[str, Any]]:
    """Parse ``plan_catalog`` CS blob into row dicts."""
    s = str(cs or "").strip()
    if not s or s in ("—", "null", "None"):
        return []
    out: List[Dict[str, Any]] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if part[0] in "Cc" and len(part) > 1 and part[1].isdigit():
            # C15:3.0:18.0
            body = part[1:]
            bits = body.split(":")
            tid = _safe_int(bits[0])
            if tid is None:
                continue
            out.append(
                {
                    "kind": "C",
                    "id": tid,
                    "label": f"C{tid}",
                    "dist": None,
                    "target": _safe_float(bits[1]) if len(bits) > 1 else None,
                    "eta_win": _safe_float(bits[2]) if len(bits) > 2 else None,
                    "risk": None,
                    "delta_t": None,
                }
            )
            continue
        if part[0] in "Ss" and len(part) > 1 and part[1].isdigit():
            body = part[1:]
        else:
            body = part
        bits = body.split(":")
        tid = _safe_int(bits[0])
        if tid is None:
            continue
        risk_raw = bits[4] if len(bits) > 4 else "-"
        risk_map = {"L": "low", "-": "low", "M": "med", "H": "high", "B": "blocked"}
        out.append(
            {
                "kind": "S",
                "id": tid,
                "label": f"S{tid}",
                "dist": _safe_int(bits[1], 0) if len(bits) > 1 else 0,
                "target": _safe_float(bits[2]) if len(bits) > 2 else None,
                "eta_win": _safe_float(bits[3]) if len(bits) > 3 else None,
                "risk": risk_map.get(str(risk_raw).upper(), _risk_bucket(risk_raw)),
                "delta_t": _safe_float(bits[5]) if len(bits) > 5 and bits[5] != "-" else None,
            }
        )
    return out


def why_for_se_pick(
    catalog: Sequence[Mapping[str, Any]],
    se_pick_label: Optional[str],
    **kwargs: Any,
) -> Optional[str]:
    """PLN2 Why on SE row (P6 complete mapping). Always non-empty when pick set."""
    try:
        from core.strategy_pln_words import why_for_se_pick as _why

        return _why(catalog, se_pick_label, **kwargs)
    except Exception:
        if not se_pick_label:
            return None
        rows = list(catalog or [])
        if rows and str(rows[0].get("label") or "") == str(se_pick_label):
            return "Fastest"
        return "Sticky"


def _canon_seat_color(color: Any) -> str:
    """Normalize to Blue|Red|White|Orange or ''."""
    key = str(color or "").strip()
    if not key:
        return ""
    for name in _SHOW_COLORS:
        if key.lower() == name.lower():
            return name
    return ""


def radius_for_show(
    turn_color: Any,
    owner_color: Any,
    *,
    path_distance: Any = None,
) -> int:
    """v4 P0e: Show circle radius from turn×owner matrix (ignore CS baked radii).

    Port black-dot base = 5; own seat ring = 8; next seats +4 (12/16/20).

    WP-R5: optional ``path_distance`` (empty-road / hop dist) soft-modulates the
    seat matrix — d=3 rings are +2px vs d=2 — without changing the seat ladder.
    Road path overlays remain **future** (Show draws circles only).
    """
    turn = _canon_seat_color(turn_color)
    owner = _canon_seat_color(owner_color)
    base = int(PORT_DOT_RADIUS)
    if turn and owner:
        row = SHOW_RADIUS_MATRIX.get(turn) or {}
        if owner in row:
            base = int(row[owner])
        elif owner:
            base = int(PLAYER_RADIUS_BY_COLOR.get(owner, SHOW_RING_OWN))
    elif owner:
        base = int(PLAYER_RADIUS_BY_COLOR.get(owner, SHOW_RING_OWN))
    elif turn:
        base = int(SHOW_RING_OWN)

    # Soft dist→radius (optional): only when caller passes a usable hop/empty dist
    d = _safe_int(path_distance, None)
    if d is not None and int(d) == 3:
        return int(base) + 2
    return int(base)


def radius_for_player_color(color: Any) -> int:
    """Legacy absolute radius by owner color only. Prefer ``radius_for_show``."""
    owner = _canon_seat_color(color)
    if owner:
        return int(PLAYER_RADIUS_BY_COLOR.get(owner, 5))
    return 5


def _player_color_name(game: Any, player: Any) -> str:
    try:
        c = str(getattr(player, "color", "") or "").strip()
        if c:
            return c
    except Exception:
        pass
    return ""


def _color_for_pid(game: Any, pid: Optional[int]) -> str:
    if pid is None or game is None:
        return ""
    try:
        for p in list(getattr(game, "players", []) or []):
            if p is None:
                continue
            if int(getattr(p, "id", -1) or -1) == int(pid):
                return str(getattr(p, "color", "") or "")
    except Exception:
        pass
    return ""


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _plan_snapshot_enabled() -> bool:
    try:
        from core import constants as C

        mode = str(getattr(C, "PLAN_SNAPSHOT", "on") or "on").lower()
        return mode not in ("off", "0", "false", "none")
    except Exception:
        return True


def _risk_bucket(raw: Any) -> str:
    s = str(raw or "low").strip().lower()
    if s in ("medium", "med"):
        return "med"
    if s in ("high", "blocked", "crit", "low", "med"):
        return s if s != "medium" else "med"
    if "block" in s:
        return "blocked"
    if "high" in s:
        return "high"
    if "med" in s:
        return "med"
    return "low"


def _radius_for_risk(risk: str) -> int:
    """Unused for Show paint (player color radii); kept for PLAN encode helpers."""
    return int(RISK_RADIUS.get(_risk_bucket(risk), 8))


def _portfolio_rows(game: Any, preferred: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Flatten target_portfolio from current board audit / preferred."""
    rows: List[Dict[str, Any]] = []
    sources: List[Any] = []
    if game is not None:
        try:
            a = getattr(game, "current_board_way_audit", None)
            if a is not None:
                sources.append(a)
            for a in list(getattr(game, "current_board_way_audits", None) or []):
                sources.append(a)
        except Exception:
            pass
    if isinstance(preferred, Mapping):
        if preferred.get("target_portfolio"):
            sources.append(preferred)
        # preferred may nest board audit
        ba = preferred.get("board_audit") or preferred.get("current_board_way_audit")
        if ba is not None:
            sources.append(ba)

    seen: set = set()
    for src in sources:
        port = None
        if isinstance(src, Mapping):
            port = src.get("target_portfolio")
        else:
            port = getattr(src, "target_portfolio", None)
        if not port:
            continue
        for t in list(port or []):
            if isinstance(t, Mapping):
                d = dict(t)
            else:
                try:
                    d = t.as_dict() if hasattr(t, "as_dict") else dict(t.__dict__)
                except Exception:
                    continue
            tid = _safe_int(d.get("target_id"))
            kind = str(d.get("kind") or d.get("target_kind") or "").lower()
            if tid is None:
                continue
            key = (tid, kind)
            if key in seen:
                continue
            seen.add(key)
            rows.append(d)
    return rows


def _opp_threat_risk_level(th: Mapping[str, Any]) -> str:
    """Per-opponent threat risk for Show (not site aggregate)."""
    explicit = _risk_bucket(th.get("risk_level") or th.get("risk"))
    if explicit in ("med", "high", "blocked", "crit"):
        return explicit
    roads = _safe_int(th.get("roads_needed") or th.get("dist") or th.get("distance"), None)
    if roads is None:
        return "low"
    # Soft race / spoiler by empty-road distance
    if int(roads) <= 1:
        return "high"
    if int(roads) in (2, 3):
        return "med"
    return "low"


def _opp_threat_showable(th: Mapping[str, Any]) -> bool:
    """Show opp ring only if that opp's threat is M/H and roads∈{2,3}."""
    roads = _safe_int(th.get("roads_needed") or th.get("dist") or th.get("distance"), None)
    if roads is None or int(roads) not in (2, 3):
        return False
    return _opp_threat_risk_level(th) in ("med", "high", "blocked", "crit")


def _competitor_compact(threats: Any) -> str:
    """Encode competitors: ``pid@eta@dN`` (roads_needed); Dig/Show parse dN."""
    bits: List[str] = []
    if not threats:
        return ""
    for th in list(threats or [])[:6]:
        if not isinstance(th, Mapping):
            continue
        pid = _safe_int(th.get("player_id") or th.get("id") or th.get("pid"))
        if pid is None:
            continue
        eta = _safe_float(th.get("eta_own_turns") or th.get("eta") or th.get("turns"))
        roads = _safe_int(th.get("roads_needed") or th.get("dist"), None)
        if eta is not None and roads is not None:
            bits.append(f"{pid}@{eta:.1f}@{int(roads)}")
        elif roads is not None:
            bits.append(f"{pid}@@{int(roads)}")
        elif eta is not None:
            bits.append(f"{pid}@{eta:.1f}")
        else:
            bits.append(str(pid))
    return ",".join(bits)


def _parse_competitor_bits(comp: Any) -> List[Dict[str, Any]]:
    """Parse ``pid[@eta][@roads]`` competitor cells into threat-like dicts."""
    out: List[Dict[str, Any]] = []
    for bit in str(comp or "").split(","):
        bit = bit.strip()
        if not bit:
            continue
        parts = bit.split("@")
        pid = _safe_int(parts[0] if parts else None)
        if pid is None:
            continue
        eta = _safe_float(parts[1]) if len(parts) > 1 and parts[1] != "" else None
        roads = _safe_int(parts[2], None) if len(parts) > 2 else None
        th: Dict[str, Any] = {"player_id": int(pid)}
        if eta is not None:
            th["eta_own_turns"] = float(eta)
        if roads is not None:
            th["roads_needed"] = int(roads)
        out.append(th)
    return out


def _encode_settle_row(row: Mapping[str, Any]) -> str:
    tid = _safe_int(row.get("id") or row.get("target_id"), 0) or 0
    dist = _safe_int(row.get("dist") or row.get("distance_roads"), 0) or 0
    eta = _safe_float(row.get("eta") or row.get("self_eta_own_turns"))
    risk = _risk_bucket(row.get("risk") or row.get("risk_level"))
    comp = str(row.get("competitors") or row.get("comp") or "")
    eta_s = f"{eta:.1f}" if eta is not None else "-"
    base = f"{tid}:{dist}:{eta_s}:{risk}"
    if comp:
        return f"{base}:{comp}"
    return base


def _encode_city_row(row: Mapping[str, Any]) -> str:
    tid = _safe_int(row.get("id") or row.get("target_id"), 0) or 0
    eta = _safe_float(row.get("target") or row.get("eta") or row.get("self_eta_own_turns"))
    eta_win = _safe_float(row.get("eta_win"))
    return f"{tid}:{_fmt_num(eta)}:{_fmt_num(eta_win)}"


def parse_plan_settles(cs: Any) -> List[Dict[str, Any]]:
    """Parse ``id:dist:eta:risk[:comp]`` semi-colon list."""
    s = str(cs or "").strip()
    if not s or s in ("—", "null", "None"):
        return []
    out: List[Dict[str, Any]] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) < 2:
            continue
        tid = _safe_int(bits[0])
        dist = _safe_int(bits[1], 0) if len(bits) > 1 else 0
        eta = _safe_float(bits[2]) if len(bits) > 2 and bits[2] != "-" else None
        risk = _risk_bucket(bits[3]) if len(bits) > 3 else "low"
        comp = bits[4] if len(bits) > 4 else ""
        if tid is None:
            continue
        out.append(
            {
                "id": tid,
                "dist": dist,
                "eta": eta,
                "risk": risk,
                "competitors": comp,
            }
        )
    return out


def parse_plan_cities(cs: Any) -> List[Dict[str, Any]]:
    s = str(cs or "").strip()
    if not s or s in ("—", "null", "None"):
        return []
    out: List[Dict[str, Any]] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        tid = _safe_int(bits[0])
        eta = _safe_float(bits[1]) if len(bits) > 1 and bits[1] != "-" else None
        if tid is None:
            continue
        out.append({"id": tid, "eta": eta})
    return out


def parse_plan_show(cs: Any) -> List[Dict[str, Any]]:
    """Parse Show payload (P1: radii optional / ignored at paint).

    New: ``id:kind[:color]`` or ``opp:pid@id[:color]``
    Legacy: ``id:radius:kind[:color]`` or ``opp:pid@id:radius[:color]``
    Dig paint uses ``radius_for_show(turn, owner)`` and ignores stored radius.
    """
    s = str(cs or "").strip()
    if not s or s in ("—", "null", "None"):
        return []
    out: List[Dict[str, Any]] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        if part.startswith("opp:"):
            body = part[4:]
            bits = body.split(":")
            left = bits[0] if bits else ""
            col = ""
            rad: Optional[int] = None
            if len(bits) >= 2:
                # legacy radius digit vs color name
                maybe_rad = _safe_int(bits[1], None)
                if maybe_rad is not None and str(bits[1]).strip().lstrip("-").isdigit():
                    rad = maybe_rad
                    col = bits[2] if len(bits) > 2 else ""
                else:
                    col = bits[1]
            if "@" in left:
                pid_s, iid_s = left.split("@", 1)
                out.append(
                    {
                        "kind": "opp",
                        "player_id": _safe_int(pid_s),
                        "id": _safe_int(iid_s),
                        "radius": rad,  # optional legacy; dig ignores
                        "color": col or "",
                    }
                )
            continue
        bits = part.split(":")
        tid = _safe_int(bits[0])
        if tid is None:
            continue
        k = "settle"
        col = ""
        rad = None
        if len(bits) >= 2:
            maybe_rad = _safe_int(bits[1], None)
            if maybe_rad is not None and str(bits[1]).strip().lstrip("-").isdigit():
                # legacy id:radius:kind[:color]
                rad = maybe_rad
                k = bits[2] if len(bits) > 2 else "settle"
                col = bits[3] if len(bits) > 3 else ""
            else:
                # P1 id:kind[:color]
                k = bits[1] or "settle"
                col = bits[2] if len(bits) > 2 else ""
        out.append(
            {
                "kind": k,
                "id": tid,
                "radius": rad,
                "color": col or "",
            }
        )
    return out


def parse_why2_lines(cs: Any) -> List[str]:
    s = str(cs or "").strip()
    if not s or s in ("—", "null", "None"):
        return []
    # Prefer | then ; for multi-line packing
    if "|" in s:
        parts = s.split("|")
    else:
        parts = s.split(";")
    return [p.strip() for p in parts if p.strip()]


def _has_unplayed(player: Any, card: str) -> bool:
    try:
        from core.strategy_way_residual import unplayed_tfr, unplayed_vp_cards

        if card == "two_free_roads":
            return int(unplayed_tfr(player) or 0) > 0
        if card == "victory_point":
            return int(unplayed_vp_cards(player) or 0) > 0
    except Exception:
        pass
    try:
        summary = list(getattr(player, "dcard_summary", None) or [])
        for row in summary:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            if str(row[0]) == card and int(row[1] or 0) + int(row[2] or 0) > 0:
                return True
    except Exception:
        pass
    # knights often in size_largest_army / playable
    if card == "knight":
        try:
            devs = list(getattr(player, "development_cards", None) or [])
            for d in devs:
                name = str(d if not isinstance(d, Mapping) else d.get("type") or d.get("name") or "")
                if "knight" in name.lower():
                    return True
        except Exception:
            pass
        try:
            summary = list(getattr(player, "dcard_summary", None) or [])
            for row in summary:
                if isinstance(row, (list, tuple)) and str(row[0]) == "knight":
                    if int(row[1] or 0) + int(row[2] or 0) > 0:
                        return True
        except Exception:
            pass
    return False


def _merge_geometry_settles_for_pln2(
    game: Any,
    player: Any,
    settles: List[Dict[str, Any]],
    *,
    se_pick_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Ensure every legal hop-distance 2/3 settle appears for PLN2 Dig + Show.

    Operator lock (Missing_S / 2026-08-21):
      - dist = graph hops from an owned S/C to the site ∈ {2, 3} (not d=1).
      - Path roads empty or own; intermediate opponent S/C block.
      - Site must satisfy Catan distance rule.
    Portfolio top-N often drops sites; geometry fills gaps. Prefer **hop**
    ``distance`` over ``roads_remaining`` for the ∈{2,3} gate. Existing
    portfolio rows keep ETA/risk but have ``dist`` corrected to hop length.
    """
    out = list(settles or [])
    by_id: Dict[int, Dict[str, Any]] = {}
    for s in out:
        tid = _safe_int(s.get("id"))
        if tid is not None:
            by_id[int(tid)] = s
    if game is None or player is None:
        return out
    try:
        from core.outlook_logic import (
            find_reachable_new_settlement_paths,
            new_settlement_spots,
        )
    except Exception:
        return out

    # Explicit full d=2/3 target set (fixed new_settlement_spots: no path_map cut)
    try:
        pid = int(getattr(player, "id"))
        target_ids = list(new_settlement_spots(game, pid) or [])
    except Exception:
        target_ids = []

    # WP-R3: prefer fresh reachability maps (never hard-exclude candidacy)
    try:
        from core.constants import REACHABILITY_MAPS
        from core.player_reachability import ensure_reachability_maps

        if bool(REACHABILITY_MAPS):
            ensure_reachability_maps(game, player)
    except Exception:
        pass

    try:
        paths = list(
            find_reachable_new_settlement_paths(
                game, player, target_ids=target_ids or None, max_distance=3
            )
            or []
        )
    except Exception:
        paths = []

    best: Dict[int, Dict[str, Any]] = {}
    # Map-first hop hints: pathlength from own S/C only (PLN2 ∈{2,3} is from
    # buildings, not road-network tips).
    try:
        from core.constants import REACHABILITY_MAPS
        from core.player_reachability import SENTINEL, maps_are_fresh

        if bool(REACHABILITY_MAPS) and maps_are_fresh(player):
            sc_starts: List[int] = []
            try:
                sc_starts.extend(
                    int(x) for x in list(getattr(player, "settlements", []) or [])
                )
                sc_starts.extend(
                    int(x) for x in list(getattr(player, "cities", []) or [])
                )
            except Exception:
                sc_starts = []
            pl_map = getattr(player, "pathlength_map", None)
            rd_map = getattr(player, "real_distance_map", None)
            path_map = getattr(player, "path_map", None)
            for raw_tid in target_ids:
                tid = _safe_int(raw_tid)
                if tid is None or not sc_starts:
                    continue
                hop = SENTINEL
                best_start = None
                for s in sc_starts:
                    try:
                        pl = int(pl_map[int(s)][int(tid)])
                    except Exception:
                        continue
                    if pl in (2, 3) and pl < hop:
                        hop = pl
                        best_start = int(s)
                if hop not in (2, 3) or best_start is None:
                    continue
                roads = []
                rem = hop
                try:
                    roads = list(path_map[best_start][int(tid)] or [])
                    rem = int(rd_map[best_start][int(tid)])
                    if rem >= SENTINEL:
                        rem = hop
                except Exception:
                    roads = []
                    rem = hop
                best[int(tid)] = {
                    "dist": int(hop),
                    "path": {
                        "target_settlement_id": int(tid),
                        "start_intersection_id": best_start,
                        "roads_to_build": list(roads),
                        "roads_remaining": int(rem),
                        "distance": int(hop),
                        "route_source": "player_reachability.path_map",
                    },
                }
    except Exception:
        pass

    for path in paths:
        if not isinstance(path, Mapping):
            continue
        tid = _safe_int(
            path.get("target_settlement_id")
            or path.get("intersection_id")
            or path.get("target_id")
        )
        if tid is None:
            continue
        # Hop distance from owned S/C (operator d=2/d=3); fall back to empty roads
        hop = _safe_int(path.get("distance"), None)
        if hop is None:
            hop = _safe_int(path.get("roads_remaining"), 99) or 99
        if hop not in (2, 3):
            continue
        prev = best.get(int(tid))
        if prev is None or hop < int(prev.get("dist") or 99):
            best[int(tid)] = {"dist": int(hop), "path": path}

    # Spots that pathfinder missed (should be rare): still force into catalog with
    # hop dist from spots membership — prefer shortest hop recorded if any path later.
    for raw_tid in target_ids:
        tid = _safe_int(raw_tid)
        if tid is None or int(tid) in best:
            continue
        # Unknown hop among {2,3}: leave as 3 so site survives catalog filter;
        # Dig Dist may be refined on a later L2 when a path is found.
        best[int(tid)] = {"dist": 3, "path": {}}

    for tid, info in best.items():
        dist = int(info["dist"])
        path = info.get("path") or {}
        roads = list(path.get("roads_to_build") or []) if isinstance(path, Mapping) else []
        if int(tid) in by_id:
            # Correct portfolio dist to hop length so catalog/Show keep the site
            row = by_id[int(tid)]
            row["dist"] = dist
            if roads and not row.get("roads"):
                row["roads"] = roads
            continue

        risk = "low"
        threats: List[Any] = []
        comp = ""
        best_opp = None
        delta_t = None
        try:
            from core.risk_assessment import (
                assess_new_settlement_path_risk,
                opponent_settlement_race_risk,
            )

            risk_pack = (
                assess_new_settlement_path_risk(game, player, int(tid), roads)
                if roads
                else opponent_settlement_race_risk(game, player, int(tid))
            )
            risk = _risk_bucket(
                risk_pack.get("risk_level") or risk_pack.get("race_status")
            )
            threats = list(risk_pack.get("threat_opponents") or [])
            if str(risk).lower() in ("low", "safe", ""):
                threats = []
            comp = _competitor_compact(threats)
            best_opp = _best_opp_eta_from_competitors(comp, threats)
        except Exception:
            pass

        tgt = None
        empty_roads = (
            len(roads)
            if roads
            else _safe_int(
                path.get("roads_remaining") if isinstance(path, Mapping) else None,
                dist,
            )
            or dist
        )
        try:
            from core.resource_time_estimator import estimate_action_time

            try:
                est = estimate_action_time(
                    getattr(game, "board", None),
                    player,
                    "settlement",
                    target_id=int(tid),
                    extra_roads_needed=int(empty_roads),
                    continuous_trading=False,
                )
            except TypeError:
                est = estimate_action_time(
                    getattr(game, "board", None),
                    player,
                    "settlement",
                    target_id=int(tid),
                    extra_roads_needed=int(empty_roads),
                )
            turns = est.get("turns") if isinstance(est, Mapping) else getattr(est, "turns", None)
            if turns is not None and float(turns) < 9000:
                tgt = round(float(turns), 2)
        except Exception:
            tgt = None
        if tgt is not None and best_opp is not None:
            try:
                delta_t = float(f"{(float(tgt) - float(best_opp)):.1f}")
            except Exception:
                delta_t = round(float(tgt) - float(best_opp), 1)

        eta_win = None
        row = {
            "kind": "S",
            "id": int(tid),
            "label": f"S{tid}",
            "dist": dist,
            "eta": tgt,
            "target": tgt,
            "eta_win": eta_win,
            "risk": risk,
            "competitors": comp,
            "threats": list(threats) if isinstance(threats, list) else [],
            "best_opp_eta": best_opp,
            "delta_t": delta_t,
            "reason": f"geometry_d{dist}",
            "role": "geometry",
        }
        out.append(row)
        by_id[int(tid)] = row
    return out


def build_plan_snapshot(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
    *,
    reason: str = "",
    refresh_mode: str = "explore",
    force: bool = False,
) -> Dict[str, Any]:
    """Build coachable PLAN rows + compact CS encodings.

    Intended for L2/explore (and forced ETA-refresh). Returns empty/inactive bag
    when ``PLAN_SNAPSHOT=off`` or pure L0 unless ``force``.
    """
    bag: Dict[str, Any] = {
        "ok": False,
        "active": False,
        "reason": reason or "plan_snapshot",
        "refresh_mode": str(refresh_mode or ""),
        "settles": [],
        "cities": [],
        "knight": None,
        "tfr": None,
        "vp_dc": None,
        "lr_package": None,
        "la_package": None,
        "why2": [],
        "show": [],
        "asof_round": None,
        "asof_turn": None,
        "cs": {},
    }
    if not force and not _plan_snapshot_enabled():
        bag["reason"] = "plan_snapshot_off"
        return bag
    mode = str(refresh_mode or "").lower()
    if not force and mode in ("hand_only", "l0", "hand"):
        bag["reason"] = "l0_skip"
        return bag
    if player is None:
        bag["reason"] = "no_player"
        return bag

    preferred = preferred if isinstance(preferred, Mapping) else {}
    if not preferred:
        raw = getattr(player, "strategic_direction", None)
        if isinstance(raw, Mapping):
            preferred = raw

    rnd = _safe_int(getattr(game, "round", None)) if game is not None else None
    turn = _safe_int(getattr(game, "turn", None)) if game is not None else None
    bag["asof_round"] = rnd
    bag["asof_turn"] = turn

    # ── Settles / cities from portfolio ──────────────────────────────────
    settles: List[Dict[str, Any]] = []
    cities: List[Dict[str, Any]] = []
    for t in _portfolio_rows(game, preferred):
        kind = str(t.get("kind") or t.get("target_kind") or "").lower()
        tid = _safe_int(t.get("target_id"))
        if tid is None:
            continue
        dist = _safe_int(t.get("distance_roads") or t.get("dist"), 0) or 0
        eta = _safe_float(t.get("self_eta_own_turns") or t.get("eta"))
        risk = _risk_bucket(t.get("risk_level") or t.get("race_status"))
        threats = t.get("threat_opponents") or []
        comp = _competitor_compact(threats)
        role = str(t.get("portfolio_role") or "")
        prio_why = str(t.get("priority_reason") or t.get("reason") or "")[:80]

        is_city = "city" in kind or kind in ("upgrade", "city_upgrade")
        is_settle = (
            not is_city
            and (
                "settle" in kind
                or kind in ("next_settlement", "new_settlement", "settlement", "")
                or dist >= 0
            )
        )
        eta_win = _safe_float(t.get("win_turns_if_target") or t.get("eta_win"))
        best_opp = _best_opp_eta_from_competitors(comp, threats)
        # v5 Dt = own Tgt − best legal opp Tgt (known-hand acquire ETAs)
        delta_t = None
        if eta is not None and best_opp is not None:
            delta_t = round(float(eta) - float(best_opp), 1)
            # Avoid float dust (e.g. 0.7000001 → 0.7); keep one decimal
            try:
                delta_t = float(f"{float(delta_t):.1f}")
            except Exception:
                pass

        if is_city:
            cities.append(
                {
                    "kind": "C",
                    "id": tid,
                    "label": f"C{tid}",
                    "eta": eta,
                    "target": eta,
                    "eta_win": eta_win,
                    "reason": prio_why or "city_upgrade",
                    "role": role,
                }
            )
        elif is_settle and dist in (0, 1, 2, 3):
            if dist > 3:
                continue
            settles.append(
                {
                    "kind": "S",
                    "id": tid,
                    "label": f"S{tid}",
                    "dist": dist,
                    "eta": eta,
                    "target": eta,
                    "eta_win": eta_win,
                    "risk": risk,
                    "competitors": comp,
                    "threats": list(threats) if isinstance(threats, list) else [],
                    "best_opp_eta": best_opp,
                    "delta_t": delta_t,
                    "reason": prio_why or f"settle_d{dist}",
                    "role": role,
                }
            )

    # SE pick (sticky ∪ rec ∪ BA) — locked A
    se_pick_id = resolve_se_pick_id(game, player, preferred)
    sticky_tid = se_pick_id
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        if isinstance(c, Mapping) and sticky_tid is None:
            sticky_tid = _safe_int(c.get("locked_rec_target_id"))
            se_pick_id = sticky_tid if se_pick_id is None else se_pick_id
    except Exception:
        pass

    # Own settlements as city-upgrade candidates (v4: all upgrades get victory ETA)
    try:
        rem = preferred.get("remaining")
        rem_cities = rem.get("cities") if isinstance(rem, Mapping) else None
        req_c = _safe_int(preferred.get("req_cities") or rem_cities, 0) or 0
        way_wants_cities = req_c > 0 or bool(preferred.get("way_cities"))
        if not way_wants_cities:
            # Table / residual may still need cities
            try:
                from core.strategy_way_residual import compute_way_residual

                wid0 = preferred.get("preferred_way_id") or preferred.get("way_id")
                res0 = compute_way_residual(
                    wid0,
                    player,
                    preferred=preferred,
                    board=getattr(game, "board", None),
                )
                req_c = max(req_c, _safe_int(res0.get("req_cities"), 0) or 0)
                way_wants_cities = req_c > 0 or bool(res0.get("way_def_tags") and any(
                    "city" in str(t).lower() for t in (res0.get("way_def_tags") or [])
                ))
            except Exception:
                pass
        if (
            way_wants_cities
            or req_c > 0
            or "city" in str(preferred.get("supporting_action_type") or "").lower()
        ):
            have = {int(x.get("id")) for x in cities if x.get("id") is not None}
            # Shared WayRequirements (with player residual when possible)
            req = None
            try:
                from core.ai_way_portfolio import (
                    PortfolioTarget,
                    WayRequirements,
                    estimate_victory_eta_after_acquiring_target,
                    parse_way_requirements,
                )
                from core.strategy_timing import build_player_strategy_state

                wid = preferred.get("preferred_way_id") or preferred.get("way_id")
                board = getattr(game, "board", None)
                pstate = None
                if board is not None and player is not None:
                    try:
                        pstate = build_player_strategy_state(board, player)
                    except Exception:
                        pstate = None
                if wid is not None:
                    # WP5: optional façade when player present (csv residual; Dig)
                    req = parse_way_requirements(
                        wid,
                        player_state=pstate,
                        game=game,
                        player=player,
                        use_min_road_cover=False,
                    )
                if req is None and isinstance(preferred.get("way_requirements"), WayRequirements):
                    req = preferred.get("way_requirements")
                # Overlay residual counts when present (keeps post-upgrade need honest)
                if req is not None and req_c > 0:
                    try:
                        req = WayRequirements(
                            way_id=int(req.way_id),
                            required_new_intersections=max(
                                0,
                                _safe_int(
                                    preferred.get("req_settles")
                                    or getattr(req, "required_new_intersections", 0),
                                    getattr(req, "required_new_intersections", 0),
                                ),
                            ),
                            required_cities=max(1, int(req_c)),
                            required_dcards=max(
                                0,
                                _safe_int(
                                    preferred.get("req_dcards")
                                    or getattr(req, "required_dcards", 0),
                                    getattr(req, "required_dcards", 0),
                                ),
                            ),
                            required_roads_min=max(
                                0,
                                _safe_int(
                                    preferred.get("req_roads")
                                    or getattr(req, "required_roads_min", 0),
                                    getattr(req, "required_roads_min", 0),
                                ),
                            ),
                            needed_rcards=dict(getattr(req, "needed_rcards", None) or {}),
                            resource_engines_needed=list(
                                getattr(req, "resource_engines_needed", None) or []
                            ),
                            longest_road=bool(getattr(req, "longest_road", False)),
                            biggest_army=bool(getattr(req, "biggest_army", False)),
                            abstract_expected_turns=float(
                                getattr(req, "abstract_expected_turns", 9999) or 9999
                            ),
                            need_vector=tuple(getattr(req, "need_vector", (0, 0, 0, 0, 0))),
                        )
                    except Exception:
                        pass
            except Exception:
                req = None

            for sid in list(getattr(player, "settlements", None) or []):
                try:
                    iid = int(sid)
                except Exception:
                    continue
                if iid in have:
                    continue
                if iid in {
                    int(c)
                    for c in (getattr(player, "cities", None) or [])
                    if c is not None
                }:
                    continue
                city_target = None
                city_eta_win = None
                try:
                    from core.resource_time_estimator import estimate_action_time

                    board = getattr(game, "board", None)
                    if board is not None:
                        # v5 Tgt: known hand + discrete TwB
                        try:
                            est = estimate_action_time(
                                board,
                                player,
                                "city",
                                target_id=int(iid),
                                continuous_trading=False,
                            )
                        except TypeError:
                            est = estimate_action_time(
                                board, player, "city", target_id=int(iid)
                            )
                        turns = None
                        if isinstance(est, Mapping):
                            turns = est.get("turns")
                        else:
                            turns = getattr(est, "turns", None)
                        if turns is not None and float(turns) < 9000:
                            city_target = round(float(turns), 2)
                except Exception:
                    city_target = None
                if req is not None:
                    try:
                        from core.ai_way_portfolio import (
                            PortfolioTarget,
                            estimate_victory_eta_after_acquiring_target,
                            _pips_named,
                        )

                        gain = {}
                        try:
                            gain = _pips_named(getattr(game, "board", None), int(iid))
                        except Exception:
                            gain = {}
                        forced = PortfolioTarget(
                            target_id=int(iid),
                            kind="city_upgrade",
                            resource_gain_named=gain,
                            roads_to_build=[],
                            distance_roads=0,
                            race_status="safe",
                            portfolio_role="useful",
                            reason="own_settle_city_slot",
                        )
                        ew = estimate_victory_eta_after_acquiring_target(
                            game, player, req, forced, empty_hand=True
                        )
                        if ew is not None and float(ew) < 9000:
                            city_eta_win = round(float(ew), 2)
                            # 0.0 with remaining cities is not credible — keep None for Dig
                            if city_eta_win <= 0.0 and req_c > 0:
                                city_eta_win = None
                    except Exception:
                        city_eta_win = None
                cities.append(
                    {
                        "kind": "C",
                        "id": iid,
                        "label": f"C{iid}",
                        "eta": city_target,
                        "target": city_target,
                        "eta_win": city_eta_win,
                        "reason": "own_settle_city_slot",
                        "role": "",
                    }
                )
                have.add(iid)
    except Exception:
        pass

    # v5 / operator: PLN2 must include ALL legal d=2 and d=3 settles on the
    # playboard — not only portfolio top-N (score truncation dropped d=3 twice).
    try:
        settles = _merge_geometry_settles_for_pln2(game, player, settles, se_pick_id=se_pick_id)
    except Exception:
        pass

    # Phase P: mark inferior S/C after all merges (portfolio + own cities + geometry)
    try:
        from core.l2_target_screen import (
            annotate_plan_rows_with_screen,
            l2_target_screen_mode,
            screen_portfolio_targets,
        )

        if l2_target_screen_mode(game) != "off":
            screen_bag = None
            try:
                screen_bag = getattr(player, "last_l2_target_screen", None)
            except Exception:
                screen_bag = None
            if not isinstance(screen_bag, Mapping):
                try:
                    screen_bag = getattr(game, "_last_l2_target_screen", None)
                except Exception:
                    screen_bag = None
            wid = None
            try:
                wid = _safe_int(preferred.get("preferred_way_id") or preferred.get("way_id"))
            except Exception:
                wid = None
            # Screen any S/C ids not already in bag (geometry / city merges)
            if wid:
                known = set()
                if isinstance(screen_bag, Mapping):
                    known = {
                        int(k)
                        for k in dict(screen_bag.get("by_id") or {}).keys()
                        if str(k).lstrip("-").isdigit()
                    }
                extra = []
                for row in list(settles) + list(cities):
                    tid = _safe_int(row.get("id"))
                    if tid and int(tid) not in known:
                        extra.append(
                            {
                                "target_id": int(tid),
                                "kind": str(row.get("kind") or "S"),
                            }
                        )
                if extra:
                    try:
                        extra_screen = screen_portfolio_targets(
                            game,
                            player,
                            extra,
                            way_id=int(wid),
                            default_kind="S",
                            stash=False,
                        )
                        base = dict(screen_bag) if isinstance(screen_bag, Mapping) else {}
                        by_id = dict(base.get("by_id") or {})
                        for k, v in dict(extra_screen.get("by_id") or {}).items():
                            by_id[int(k)] = v
                        base["by_id"] = by_id
                        base["inferior"] = list(base.get("inferior") or []) + list(
                            extra_screen.get("inferior") or []
                        )
                        screen_bag = base
                    except Exception:
                        pass
            settles = annotate_plan_rows_with_screen(settles, screen_bag)
            cities = annotate_plan_rows_with_screen(cities, screen_bag)
            # Inferior rows may omit ETA (operator OK) — but never blank the SE pick.
            se_lab = None
            if se_pick_id is not None:
                se_lab = f"S{int(se_pick_id)}"
                # City pick uses C{id}
                for row in cities:
                    if int(row.get("id") or 0) == int(se_pick_id):
                        se_lab = f"C{int(se_pick_id)}"
                        break
            for row in settles + cities:
                if int(row.get("inferior") or 0) != 1:
                    continue
                lab = str(row.get("label") or "")
                if se_lab and lab == se_lab:
                    # Keep Tgt/ETA for sticky SE New; drop inferior tag for dig clarity
                    row["inferior"] = 0
                    row.pop("inferior_reason", None)
                    continue
                row["eta"] = None
                row["target"] = None
                row["eta_win"] = None
    except Exception:
        pass

    # P2 catalog: S with dist∈{2,3} (+ SE pick even if d=0/1), all C
    catalog: List[Dict[str, Any]] = []
    seen_lab: set = set()
    for s in settles:
        d = int(s.get("dist") or 0)
        tid = int(s.get("id") or 0)
        if d in (2, 3) or (se_pick_id is not None and tid == int(se_pick_id)):
            lab = str(s.get("label") or f"S{tid}")
            if lab in seen_lab:
                continue
            seen_lab.add(lab)
            catalog.append(dict(s))
    for c in cities:
        lab = str(c.get("label") or f"C{c.get('id')}")
        if lab in seen_lab:
            continue
        seen_lab.add(lab)
        catalog.append(dict(c))

    catalog.sort(key=_catalog_sort_key)
    # Top 8 by Tgt+ETA; keep SE pick in the eight when present
    cap = max(1, int(PLAN_CATALOG_DETAIL))
    detail: List[Dict[str, Any]] = []
    seen_d: set = set()
    se_lab = None
    if se_pick_id is not None:
        for r in catalog:
            if int(r.get("id") or -1) == int(se_pick_id):
                se_lab = str(r.get("label") or f"S{se_pick_id}")
                break
    for r in catalog:
        lab = str(r.get("label") or r.get("id"))
        if lab in seen_d:
            continue
        if len(detail) >= cap:
            break
        seen_d.add(lab)
        detail.append(r)
    if se_lab and se_lab not in seen_d:
        # Force SE pick into the eight (replace last)
        for r in catalog:
            if str(r.get("label") or r.get("id")) == se_lab:
                if len(detail) >= cap and detail:
                    dropped = detail.pop()
                    seen_d.discard(str(dropped.get("label") or dropped.get("id")))
                detail.append(r)
                seen_d.add(se_lab)
                break
    overflow_rows = [
        r for r in catalog if str(r.get("label") or r.get("id")) not in seen_d
    ]
    # Overflow text: list omitted C's and S's (operator Dig 9th row)
    overflow_cs = [
        str(r.get("label") or r.get("id"))
        for r in overflow_rows
        if str(r.get("kind") or "S").upper() in ("C", "S")
    ]
    overflow_ids = overflow_cs

    se_pick_label = None
    if se_pick_id is not None:
        for r in catalog:
            if int(r.get("id") or -1) == int(se_pick_id):
                se_pick_label = str(r.get("label"))
                r["se_pick"] = True
                break
        if se_pick_label is None:
            # pick not in catalog — still record label heuristically
            se_pick_label = f"S{se_pick_id}"

    sticky_held = False
    try:
        from core.strategy_sticky import get_sticky_commitment

        _sc = get_sticky_commitment(player)
        sticky_held = bool(isinstance(_sc, Mapping) and _sc.get("locked_rec_target_id"))
    except Exception:
        pass
    plan_why = why_for_se_pick(
        detail if detail else catalog,
        se_pick_label,
        sticky_held=sticky_held,
    )
    # Guarantee: SE pick that is not Fastest still gets a Why
    if se_pick_label and not plan_why:
        plan_why = "Sticky"

    bag["catalog"] = detail
    bag["catalog_all"] = catalog
    bag["overflow"] = overflow_ids
    bag["se_pick"] = se_pick_label
    bag["plan_why"] = plan_why
    bag["se_pick_id"] = se_pick_id

    # Show / legacy settles: catalog S detail (d=2/3 focus)
    bag["settles"] = [r for r in detail if str(r.get("kind") or "S").upper() == "S"][
        :PLAN_SETTLE_MAX
    ]
    bag["cities"] = [r for r in detail if str(r.get("kind") or "").upper() == "C"][
        :PLAN_CITY_MAX
    ]

    # ── Knight / TFR from WP4 race plans ─────────────────────────────────
    kt = getattr(player, "knight_tfr_policy", None)
    if not isinstance(kt, Mapping):
        kt = {}
    la = getattr(player, "la_race_plan", None)
    if not isinstance(la, Mapping):
        la = {}
    lr = getattr(player, "lr_race_plan", None)
    if not isinstance(lr, Mapping):
        lr = {}

    prefer = kt.get("prefer_knight") if isinstance(kt, Mapping) else None
    rule = str((kt or {}).get("rule") or "") or None

    if _has_unplayed(player, "knight") or la.get("playable_knights") or la.get("play_knight"):
        play = bool(la.get("play_knight") or la.get("would_take_now"))
        if prefer is True:
            play = True
        if prefer is False and not la.get("would_take_now"):
            play = False
        bag["knight"] = {
            "action": "play" if play else "postpone",
            "prefer": prefer,
            "rule": rule,
            "label": str(la.get("label") or "LA"),
        }

    if _has_unplayed(player, "two_free_roads") or lr.get("has_tfr"):
        play_tfr = bool(lr.get("claim_now") or (prefer is False and lr.get("contested")))
        if prefer is True and not lr.get("claim_now"):
            play_tfr = False
        edges = list(lr.get("tfr_edges") or lr.get("grow_edges") or [])[:3]
        edge_fp = ";".join(
            f"{min(int(e[0]), int(e[1]))}-{max(int(e[0]), int(e[1]))}"
            for e in edges
            if isinstance(e, (list, tuple)) and len(e) >= 2
        )
        bag["tfr"] = {
            "action": "play" if play_tfr else "postpone",
            "prefer": prefer,
            "rule": rule,
            "edges": edge_fp,
            "label": str(lr.get("label") or "LR"),
        }

    if la:
        bag["la_package"] = {
            "label": la.get("label"),
            "conf": la.get("confidence"),
            "play_knight": la.get("play_knight"),
            "army_ai": la.get("army_ai"),
            "max_opp_army": la.get("max_opp_army"),
        }
    if lr:
        bag["lr_package"] = {
            "label": lr.get("label"),
            "conf": lr.get("confidence"),
            "claim_now": lr.get("claim_now"),
            "roads_fp": lr.get("sticky_roads_fp"),
            "own_length": lr.get("own_length"),
            "max_opp_length": lr.get("max_opp_length"),
        }

    # ── Late VP race ─────────────────────────────────────────────────────
    vp = _safe_int(getattr(player, "victory_points", None) or getattr(player, "points", None), 0) or 0
    max_opp = 0
    if game is not None:
        for opp in list(getattr(game, "players", []) or []):
            if opp is None or getattr(opp, "id", None) == getattr(player, "id", None):
                continue
            max_opp = max(
                max_opp,
                _safe_int(getattr(opp, "victory_points", None) or getattr(opp, "points", None), 0)
                or 0,
            )
    if vp >= 8 or max_opp >= 8 or (10 - vp) <= 2:
        has_vp = _has_unplayed(player, "victory_point")
        bag["vp_dc"] = {
            "action": "hold" if has_vp and vp >= 9 else ("buy" if vp >= 7 else "hold"),
            "eta": max(0.0, float(10 - vp)),
            "vp": vp,
            "max_opp": max_opp,
        }

    # ── WHY2 one line per PLAN row ───────────────────────────────────────
    why2: List[str] = []
    for s in bag["settles"]:
        eta_s = f"eta={s['eta']:.1f}" if s.get("eta") is not None else "eta=?"
        line = f"S{s['id']} d={s.get('dist')} {eta_s} risk={s.get('risk')}"
        if s.get("competitors"):
            line += f" vs {s['competitors']}"
        if s.get("reason"):
            line += f" ({s['reason'][:40]})"
        why2.append(line)
    for c in bag["cities"]:
        eta_s = f"eta={c['eta']:.1f}" if c.get("eta") is not None else "eta=?"
        why2.append(f"C{c['id']} {eta_s} city upgrade")
    if bag.get("knight"):
        k = bag["knight"]
        why2.append(
            f"Knight {k.get('action')} rule={k.get('rule') or '-'} {k.get('label') or ''}".strip()
        )
    if bag.get("tfr"):
        t = bag["tfr"]
        edges = f" edges={t['edges']}" if t.get("edges") else ""
        why2.append(
            f"TFR {t.get('action')} rule={t.get('rule') or '-'}{edges} {t.get('label') or ''}".strip()
        )
    if bag.get("lr_package"):
        lp = bag["lr_package"]
        why2.append(
            f"LR pkg {lp.get('label')} conf={lp.get('conf')} roads={lp.get('roads_fp') or '-'}"
        )
    if bag.get("la_package"):
        ap = bag["la_package"]
        why2.append(
            f"LA pkg {ap.get('label')} conf={ap.get('conf')} army={ap.get('army_ai')}/{ap.get('max_opp_army')}"
        )
    if bag.get("vp_dc"):
        v = bag["vp_dc"]
        why2.append(f"VP-DC {v.get('action')} vp={v.get('vp')} opp={v.get('max_opp')}")
    bag["why2"] = why2[:16]

    # ── Show circles (P3) ───────────────────────────────────────────────
    # Turn-player new-settlements d∈{2,3} (+ SE pick); opp rings only if risk M/H.
    # No cities, no roads. Radii recomputed at dig paint (P1 matrix).
    bag["show"] = build_plan_show_entries(
        game,
        player,
        catalog_rows=list(bag.get("catalog_all") or catalog),
        se_pick_id=se_pick_id,
    )

    bag["cs"] = encode_plan_cs_fields(bag)
    bag["ok"] = True
    bag["active"] = bool(
        bag.get("catalog")
        or bag["settles"]
        or bag["cities"]
        or bag["knight"]
        or bag["tfr"]
        or bag["lr_package"]
        or bag["la_package"]
        or bag["vp_dc"]
    )
    return bag


def build_plan_show_entries(
    game: Any,
    player: Any,
    *,
    catalog_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    se_pick_id: Optional[int] = None,
    max_entries: int = 48,
) -> List[Dict[str, Any]]:
    """Show payload: own S (d=2/3 or SE pick); opp rings per-opponent.

    Own settle circles always for dist∈{2,3} (operator: independent of opp risk).
    Opp ring only when **that** opponent's threat is M/H **and** their empty-road
    distance to the site is 2 or 3. Own settles are emitted **before** opp rings
    so a soft max_entries cannot drop missing S sites.
    """
    own_color = _player_color_name(game, player)
    own_pid = _safe_int(getattr(player, "id", None))
    own_entries: List[Dict[str, Any]] = []
    opp_entries: List[Dict[str, Any]] = []
    seen_own: set = set()

    # WP-R5: freshen maps so Show dist / opp roads_needed can use reachability
    try:
        from core.constants import REACHABILITY_MAPS
        from core.player_reachability import ensure_dig_seat_maps, maps_are_fresh, sc_hop_distance

        if bool(REACHABILITY_MAPS):
            ensure_dig_seat_maps(game, player)
        maps_ok = maps_are_fresh(player)
    except Exception:
        maps_ok = False
        sc_hop_distance = None  # type: ignore

    rows = list(catalog_rows or [])
    for s in rows:
        if str(s.get("kind") or "S").upper() != "S":
            continue
        tid = _safe_int(s.get("id"))
        if tid is None:
            continue
        dist = _safe_int(s.get("dist"), 0) or 0
        map_dist = None
        if maps_ok and sc_hop_distance is not None:
            try:
                map_dist = sc_hop_distance(player, int(tid))
            except Exception:
                map_dist = None
            if map_dist in (2, 3):
                dist = int(map_dist)
        is_pick = se_pick_id is not None and int(tid) == int(se_pick_id)
        if dist not in (2, 3) and not is_pick:
            continue
        if tid in seen_own:
            continue
        # Refinements v1: never emit Show for already-occupied intersections
        try:
            board = getattr(game, "board", None)
            inter = (
                board.intersections[int(tid)]
                if board is not None and 0 <= int(tid) < len(board.intersections)
                else None
            )
            if inter is not None and getattr(inter, "occupied_tf", False):
                continue
        except Exception:
            pass
        seen_own.add(tid)
        own_rad = radius_for_show(own_color, own_color, path_distance=dist)
        entry_own: Dict[str, Any] = {
            "kind": "settle",
            "id": tid,
            "player_id": own_pid,
            "color": own_color,
            "radius": own_rad,
            "dist": dist,
            "risk": s.get("risk"),
        }
        if map_dist is not None:
            entry_own["map_dist"] = int(map_dist)
        own_entries.append(entry_own)
        threats: List[Any] = []
        raw_th = s.get("threats") or s.get("threat_opponents")
        if isinstance(raw_th, (list, tuple)):
            threats = [t for t in raw_th if isinstance(t, Mapping)]
        if not threats:
            threats = _parse_competitor_bits(s.get("competitors") or s.get("comp"))
        seen_opp: set = set()
        for th in threats:
            if not isinstance(th, Mapping):
                continue
            th_local = dict(th)
            pid = _safe_int(th_local.get("player_id") or th_local.get("id") or th_local.get("pid"))
            # WP-R5: refresh opp roads_needed from their reachability maps when possible
            if pid is not None:
                try:
                    from core.player_reachability import (
                        SENTINEL,
                        ensure_dig_seat_maps,
                        maps_are_fresh,
                        remaining_roads_to_target,
                    )

                    opp_pl = None
                    for p in list(getattr(game, "players", []) or []):
                        if p is None:
                            continue
                        if int(getattr(p, "id", -1) or -1) == int(pid):
                            opp_pl = p
                            break
                    if opp_pl is not None:
                        ensure_dig_seat_maps(game, opp_pl)
                        if maps_are_fresh(opp_pl):
                            rd = remaining_roads_to_target(opp_pl, int(tid))
                            if rd is not None and 0 <= int(rd) < SENTINEL:
                                th_local["roads_needed"] = int(rd)
                except Exception:
                    pass
            if not _opp_threat_showable(th_local):
                continue
            if pid is None or (own_pid is not None and int(pid) == int(own_pid)):
                continue
            if int(pid) in seen_opp:
                continue
            seen_opp.add(int(pid))
            opp_color = _color_for_pid(game, pid)
            roads_n = _safe_int(th_local.get("roads_needed"), None)
            opp_entries.append(
                {
                    "kind": "opp",
                    "player_id": int(pid),
                    "id": tid,
                    "color": opp_color,
                    "radius": radius_for_show(
                        own_color, opp_color, path_distance=roads_n
                    ),
                    "roads_needed": roads_n,
                    "risk": _opp_threat_risk_level(th_local),
                }
            )
    # Never drop own d=2/3 settles for the soft cap; trim opp rings first
    cap = max(1, int(max_entries))
    if len(own_entries) >= cap:
        return own_entries[:cap]
    remain = cap - len(own_entries)
    return own_entries + opp_entries[:remain]


def encode_plan_cs_fields(bag: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact dig/CS strings (stable keys)."""
    settles = list(bag.get("settles") or [])
    cities = list(bag.get("cities") or [])
    show = list(bag.get("show") or [])
    why2 = list(bag.get("why2") or [])
    catalog = list(bag.get("catalog") or [])

    plan_settles = ";".join(_encode_settle_row(s) for s in settles) or None
    plan_cities = ";".join(_encode_city_row(c) for c in cities) or None
    plan_catalog = ";".join(encode_plan_catalog_row(r) for r in catalog) or None
    overflow = list(bag.get("overflow") or [])
    plan_overflow = ",".join(str(x) for x in overflow) if overflow else None
    plan_se_pick = str(bag.get("se_pick") or "") or None
    plan_why = str(bag.get("plan_why") or "") or None

    k = bag.get("knight")
    plan_knight = None
    if isinstance(k, Mapping):
        plan_knight = f"{k.get('action') or '?'}|{k.get('rule') or '-'}|{k.get('label') or ''}"

    t = bag.get("tfr")
    plan_tfr = None
    if isinstance(t, Mapping):
        plan_tfr = (
            f"{t.get('action') or '?'}|{t.get('rule') or '-'}|{t.get('edges') or ''}"
        )

    v = bag.get("vp_dc")
    plan_vp = None
    if isinstance(v, Mapping):
        plan_vp = f"{v.get('action') or '?'}|{v.get('eta') if v.get('eta') is not None else '-'}"

    lp = bag.get("lr_package")
    plan_lr = None
    if isinstance(lp, Mapping) and lp.get("label"):
        plan_lr = (
            f"{lp.get('label')}|{lp.get('conf') if lp.get('conf') is not None else '-'}|"
            f"{'claim' if lp.get('claim_now') else 'grow'}|{lp.get('roads_fp') or ''}"
        )

    ap = bag.get("la_package")
    plan_la = None
    if isinstance(ap, Mapping) and ap.get("label"):
        plan_la = (
            f"{ap.get('label')}|{ap.get('conf') if ap.get('conf') is not None else '-'}|"
            f"{'play' if ap.get('play_knight') else 'hold'}"
        )

    rnd = bag.get("asof_round")
    turn = bag.get("asof_turn")
    plan_asof = None
    if rnd is not None and turn is not None:
        plan_asof = f"R{rnd}T{turn}"
    elif rnd is not None:
        plan_asof = f"R{rnd}"

    # plan_show: no baked radius (P1 dig recomputes). id:kind[:color] | opp:pid@id[:color]
    show_bits: List[str] = []
    for s in show:
        col = str(s.get("color") or "").strip()
        if s.get("kind") == "opp":
            bit = f"opp:{s.get('player_id')}@{s.get('id')}"
            if col:
                bit += f":{col}"
            show_bits.append(bit)
        else:
            kind = s.get("kind") or "settle"
            if str(kind).upper() == "C":
                kind = "city"
            elif str(kind).upper() == "S":
                kind = "settle"
            bit = f"{s.get('id')}:{kind}"
            if col:
                bit += f":{col}"
            show_bits.append(bit)
    plan_show = ";".join(show_bits) or None
    plan_why2 = "|".join(why2) if why2 else None

    return {
        "plan_settles": plan_settles,
        "plan_cities": plan_cities,
        "plan_catalog": plan_catalog,
        "plan_overflow": plan_overflow,
        "plan_se_pick": plan_se_pick,
        "plan_why": plan_why,
        "plan_knight": plan_knight,
        "plan_tfr": plan_tfr,
        "plan_vp_dc": plan_vp,
        "plan_lr_pkg": plan_lr,
        "plan_la_pkg": plan_la,
        "plan_asof_rt": plan_asof,
        "plan_why2": plan_why2,
        "plan_show": plan_show,
    }


def cs_fields_from_plan_snapshot(player: Any) -> Dict[str, Any]:
    """CS dig fields from player.plan_snapshot (or empty defaults)."""
    keys = (
        "plan_settles",
        "plan_cities",
        "plan_catalog",
        "plan_overflow",
        "plan_se_pick",
        "plan_why",
        "plan_knight",
        "plan_tfr",
        "plan_vp_dc",
        "plan_lr_pkg",
        "plan_la_pkg",
        "plan_asof_rt",
        "plan_why2",
        "plan_show",
    )
    out: Dict[str, Any] = {k: None for k in keys}
    snap = getattr(player, "plan_snapshot", None) if player is not None else None
    if not isinstance(snap, Mapping):
        return out
    cs = snap.get("cs") if isinstance(snap.get("cs"), Mapping) else snap
    if not isinstance(cs, Mapping):
        return out
    for k in keys:
        v = cs.get(k)
        if v is not None and str(v).strip() != "":
            out[k] = str(v)[:500] if k in ("plan_why2", "plan_catalog") else str(v)[:240]
    # P5 PLN1 fields (also merged into plan cs)
    try:
        from core.strategy_pln1 import cs_fields_from_pln1

        out.update(cs_fields_from_pln1(player))
    except Exception:
        pass
    return out


def refresh_plan_snapshot(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
    *,
    reason: str = "",
    refresh_mode: str = "explore",
    force: bool = False,
) -> Dict[str, Any]:
    """Build PLN2 (+ Show) and PLN1, store on player/game, CS fields."""
    bag = build_plan_snapshot(
        game,
        player,
        preferred,
        reason=reason,
        refresh_mode=refresh_mode,
        force=force,
    )
    if not bag.get("ok"):
        return bag

    # P5: PLN1 way components / DC posture
    pln1: Dict[str, Any] = {}
    try:
        from core.strategy_pln1 import build_pln1_snapshot

        pref = preferred
        if not isinstance(pref, Mapping):
            pref = getattr(player, "strategic_direction", None)
        pln1 = build_pln1_snapshot(game, player, pref, plan_bag=bag)
        if pln1.get("ok") and isinstance(pln1.get("cs"), Mapping):
            cs = dict(bag.get("cs") or {})
            cs.update({k: v for k, v in pln1["cs"].items() if v is not None})
            bag["cs"] = cs
            bag["pln1"] = pln1
            # P6: refine PLN2 Why with PLN1 word + context (City→Calm/Cap, Specials, …)
            try:
                from core.strategy_pln_words import infer_why_context, why_for_se_pick as _why

                ctx = infer_why_context(game, player, pref, pln1=pln1)
                refined = _why(
                    list(bag.get("catalog") or bag.get("catalog_all") or []),
                    bag.get("se_pick"),
                    **ctx,
                )
                if refined:
                    bag["plan_why"] = refined
                    cs["plan_why"] = refined
                    bag["cs"] = cs
            except Exception:
                pass
    except Exception as exc:
        bag["pln1"] = {"ok": False, "error": str(exc)[:120]}

    try:
        player.plan_snapshot = dict(bag)
        if pln1.get("ok"):
            player.pln1_snapshot = dict(pln1)
        player.last_plan_asof_round = bag.get("asof_round")
        player.last_plan_asof_turn = bag.get("asof_turn")
        # MyQ2-style L2 stamp when this is a real explore snapshot
        mode = str(refresh_mode or "").lower()
        if mode not in ("hand_only", "l0", "hand"):
            player.last_l2_round = bag.get("asof_round")
            player.last_l2_turn = bag.get("asof_turn")
            player.last_l2_reason = str(reason or mode or "plan_snapshot")[:80]
    except Exception:
        pass
    try:
        if game is not None:
            game.last_plan_snapshot = dict(bag)
            game.last_plan_snapshot_player_id = getattr(player, "id", None)
    except Exception:
        pass
    try:
        direction = getattr(player, "strategic_direction", None)
        if isinstance(direction, dict):
            direction = dict(direction)
            direction["plan_snapshot_cs"] = dict(bag.get("cs") or {})
            direction["plan_asof_rt"] = (bag.get("cs") or {}).get("plan_asof_rt")
            player.strategic_direction = direction
    except Exception:
        pass
    return bag


def plan_stale_tf(
    row: Mapping[str, Any],
    *,
    cursor_round: Optional[int] = None,
    cursor_turn: Optional[int] = None,
) -> bool:
    """True when cursor R/T is after plan_asof_rt (ETA may be stale)."""
    asof = str(row.get("plan_asof_rt") or "").strip()
    if not asof or not asof.startswith("R"):
        return False
    # R5T2 or R5
    try:
        body = asof[1:]
        if "T" in body:
            rs, ts = body.split("T", 1)
            ar, at = int(rs), int(ts)
        else:
            ar, at = int(body), 0
    except Exception:
        return False
    cr = cursor_round if cursor_round is not None else _safe_int(row.get("round"))
    ct = cursor_turn if cursor_turn is not None else _safe_int(row.get("turn"))
    if cr is None:
        return False
    if int(cr) > ar:
        return True
    if int(cr) == ar and ct is not None and int(ct) > at:
        return True
    return False


def pln2_table_for_dig(row: Mapping[str, Any]) -> Dict[str, Any]:
    """P4: structured PLN2 table model for dig UI.

    Returns ``headers``, ``rows`` (each: new, target, eta, dist, risk, delta, why, se_pick),
    ``asof``, ``overflow``, ``empty``.
    """
    headers = ("New", "Tgt", "ETA", "Dist", "Risk", "△t", "Why")
    se_pick = str(row.get("plan_se_pick") or "").strip()
    plan_why = str(row.get("plan_why") or "").strip()
    asof = str(row.get("plan_asof_rt") or "").strip()
    if asof and plan_stale_tf(row):
        asof = f"{asof} (stale)"

    catalog = parse_plan_catalog(row.get("plan_catalog"))
    table_rows: List[Dict[str, Any]] = []

    if catalog:
        for r in catalog:
            lab = str(r.get("label") or "")
            is_se = bool(se_pick and lab == se_pick)
            kind = str(r.get("kind") or "S").upper()
            tgt = _fmt_num(_safe_float(r.get("target")))
            ew = _fmt_num(_safe_float(r.get("eta_win")))
            if tgt == "-":
                tgt = "—"
            if ew == "-":
                ew = "—"
            if kind == "C":
                table_rows.append(
                    {
                        "new": lab,
                        "target": tgt,
                        "eta": ew,
                        "dist": "—",
                        "risk": "—",
                        "delta": "—",
                        "why": (plan_why if is_se else ""),
                        "se_pick": is_se,
                        "kind": "C",
                    }
                )
            else:
                rl = _risk_letter(r.get("risk"))
                if rl in ("-", "L"):
                    rl = "—"  # hide low
                dt = r.get("delta_t")
                dts = _fmt_num(_safe_float(dt)) if dt is not None else "—"
                if dts == "-":
                    dts = "—"
                dist = r.get("dist")
                dist_s = str(dist) if dist is not None else "—"
                table_rows.append(
                    {
                        "new": lab,
                        "target": tgt,
                        "eta": ew,
                        "dist": dist_s,
                        "risk": rl,
                        "delta": dts,
                        "why": (plan_why if is_se else ""),
                        "se_pick": is_se,
                        "kind": "S",
                    }
                )
    else:
        # Legacy fallback from plan_settles / plan_cities
        for s in parse_plan_settles(row.get("plan_settles")):
            lab = f"S{s['id']}"
            is_se = bool(se_pick and lab == se_pick)
            eta = _fmt_num(_safe_float(s.get("eta")))
            rl = _risk_letter(s.get("risk"))
            if rl in ("-", "L"):
                rl = "—"
            table_rows.append(
                {
                    "new": lab,
                    "target": eta if eta != "-" else "—",
                    "eta": "—",
                    "dist": str(s.get("dist") if s.get("dist") is not None else "—"),
                    "risk": rl,
                    "delta": "—",
                    "why": (plan_why if is_se else ""),
                    "se_pick": is_se,
                    "kind": "S",
                }
            )
        for c in parse_plan_cities(row.get("plan_cities")):
            lab = f"C{c['id']}"
            is_se = bool(se_pick and lab == se_pick)
            eta = _fmt_num(_safe_float(c.get("eta")))
            table_rows.append(
                {
                    "new": lab,
                    "target": eta if eta != "-" else "—",
                    "eta": "—",
                    "dist": "—",
                    "risk": "—",
                    "delta": "—",
                    "why": (plan_why if is_se else ""),
                    "se_pick": is_se,
                    "kind": "C",
                }
            )

    overflow = str(row.get("plan_overflow") or "").strip()
    # Dig: max 8 data rows (already sorted Tgt+ETA in CS); 9th lists omitted C/S
    cap = max(1, int(PLAN_CATALOG_DETAIL))
    if len(table_rows) > cap:
        # Re-sort by Tgt+ETA if legacy blob had more than 8
        def _row_sort_key(r: Mapping[str, Any]) -> Tuple:
            t = _safe_float(r.get("target"))
            e = _safe_float(r.get("eta"))
            tt = float(t) if t is not None else 9000.0
            ee = float(e) if e is not None else 9000.0
            lab = str(r.get("new") or "")
            try:
                nid = int("".join(ch for ch in lab if ch.isdigit()) or 0)
            except Exception:
                nid = 0
            return (tt + ee, tt, nid)

        table_rows = sorted(table_rows, key=_row_sort_key)
        omitted = table_rows[cap:]
        table_rows = table_rows[:cap]
        extra = [str(r.get("new") or "") for r in omitted if r.get("new")]
        if extra:
            overflow = ",".join(extra) if not overflow else overflow
    if overflow:
        table_rows.append(
            {
                "new": "…",
                "target": "—",
                "eta": "—",
                "dist": "—",
                "risk": "—",
                "delta": "—",
                "why": overflow.replace(",", ", "),
                "se_pick": False,
                "kind": "OV",
                "overflow": True,
            }
        )
    empty = not table_rows
    return {
        "headers": headers,
        "rows": table_rows,
        "asof": asof or None,
        "overflow": overflow or None,
        "se_pick": se_pick or None,
        "plan_why": plan_why or None,
        "empty": empty,
    }


def plan_lines_for_dig(row: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Compact PLN2 lines (tests / fallback). Prefer ``pln2_table_for_dig`` for UI."""
    tbl = pln2_table_for_dig(row)
    lines: List[Tuple[str, str]] = []
    if tbl.get("asof"):
        lines.append(("asof", str(tbl["asof"])))
    if tbl.get("empty"):
        lines.append(("note", "No PLN2 catalog at this sample (L0 or PLAN_SNAPSHOT off)"))
        return lines
    # Header-ish summary
    lines.append(("hdr", "New  Tgt  ETA  Dist  Risk  △t  Why"))
    for r in tbl.get("rows") or []:
        why = r.get("why") or ""
        mark = "*" if r.get("se_pick") else ""
        text = (
            f"{r.get('target')}  {r.get('eta')}  {r.get('dist')}  "
            f"{r.get('risk')}  {r.get('delta')}"
        )
        if why:
            text = f"{text}  {why}"
        lines.append((f"{r.get('new')}{mark}", text))
    if tbl.get("overflow"):
        lines.append(("more", str(tbl["overflow"])))
    return lines


def why2_lines_for_dig(row: Mapping[str, Any]) -> List[Tuple[str, str]]:
    raw = parse_why2_lines(row.get("plan_why2"))
    if not raw:
        # Fallback: synthesize short WHY2 from PLAN encodes
        for lab, text in plan_lines_for_dig(row):
            if lab == "note":
                continue
            raw.append(f"{lab}: {text}")
    if not raw:
        return [("note", "No WHY2 reasons (need L2 plan snapshot)")]
    out: List[Tuple[str, str]] = []
    for i, line in enumerate(raw[:14], start=1):
        out.append((f"w{i}", line))
    return out


def str_field_slots(row: Optional[Mapping[str, Any]]) -> List[Tuple[str, str]]:
    """STR slots (refinements v1): sticky chip + ETA Plan/Previous table.

    Skips redundant Type=target row. Given-up only when LA/LR actually given up.
    """
    base: List[Tuple[str, str]] = [
        ("Way sticky", "sticky_way_id"),
        ("Way id", "way_id"),
        ("Tags", "way_def_tags"),
        ("Given up", "_given_up"),
        ("Sticky", "_sticky_chip"),
        ("Rec tgt", "rec_target_id"),
        # Dig §5: single block marker (Dig draws title+hdr+Plan+Prev)
        ("ETA-Table", "_eta_block"),
    ]
    if not row:
        return base
    sw = str(row.get("sticky_way_id") or "").strip()
    wid = str(row.get("way_id") or "").strip()
    st = str(row.get("sticky_target_id") or "").strip()
    rt = str(row.get("rec_target_id") or "").strip()
    out: List[Tuple[str, str]] = []
    for lab, key in base:
        if key == "way_id" and sw and wid and sw == wid:
            continue
        if key == "rec_target_id" and st and rt and st == rt:
            continue
        if key == "_given_up":
            # omit slot unless we can show something (filled in format_se_value)
            continue
        out.append((lab, key))
    # Insert Given up only when non-empty
    gu = _format_given_up(row)
    if gu:
        # after Tags
        inserted = False
        final: List[Tuple[str, str]] = []
        for lab, key in out:
            final.append((lab, key))
            if key == "way_def_tags" and not inserted:
                final.append(("Given up", "_given_up"))
                inserted = True
        if not inserted:
            final.insert(3, ("Given up", "_given_up"))
        out = final
    return out


def _format_given_up(row: Mapping[str, Any]) -> str:
    """Only LA and/or LR that are actually given up."""
    parts: List[str] = []
    # CS / episode hints
    for key, lab in (
        ("gave_up_la", "LA"),
        ("kill_la", "LA"),
        ("gave_up_lr", "LR"),
        ("kill_lr", "LR"),
    ):
        v = str(row.get(key) or "").strip().lower()
        if v in ("1", "true", "yes", "y"):
            if lab not in parts:
                parts.append(lab)
    # ignored_components cell
    raw = str(row.get("ignored_components") or row.get("partial_ignored") or "")
    low = raw.lower()
    if ("la" in low or "army" in low) and "LA" not in parts:
        parts.append("LA")
    if ("lr" in low or "longest" in low) and "LR" not in parts:
        parts.append("LR")
    return " · ".join(parts)


def _sticky_chip(row: Mapping[str, Any]) -> str:
    """Combine sticky tgt + kind → ``S62`` / ``C62``."""
    tid = str(row.get("sticky_target_id") or "").strip()
    kind = str(row.get("sticky_target_kind") or "").strip().lower()
    if not tid or tid in ("—", "-", "none", "null"):
        return ""
    # already prefixed
    if tid.upper().startswith(("S", "C")) and tid[1:].isdigit():
        return tid.upper() if tid[0].isalpha() else tid
    try:
        n = int(float(tid))
    except Exception:
        return tid
    if kind in ("c", "city", "cities"):
        return f"C{n}"
    return f"S{n}"


def _plan_eta_from_pln2_sticky(row: Mapping[str, Any]) -> Optional[float]:
    """Plan ETA = PLN2 Tgt + ETA for sticky New (refinements Q4)."""
    chip = _sticky_chip(row)
    tid = None
    if chip:
        try:
            tid = int("".join(ch for ch in chip if ch.isdigit()))
        except Exception:
            tid = None
    if tid is None:
        try:
            tid = int(float(row.get("sticky_target_id")))
        except Exception:
            return None
    try:
        catalog = parse_plan_catalog(row.get("plan_catalog"))
    except Exception:
        catalog = []
    for r in catalog:
        try:
            if int(r.get("id") or -1) != int(tid):
                continue
        except Exception:
            continue
        tgt = _safe_float(r.get("target") or r.get("eta"), None)
        eta = _safe_float(r.get("eta_win") or r.get("eta"), None)
        if tgt is not None and eta is not None:
            return round(float(tgt) + float(eta), 1)
        if tgt is not None:
            return round(float(tgt), 1)
        if eta is not None:
            return round(float(eta), 1)
    # fallback: CS turns
    return _safe_float(row.get("turns"), None)


def is_str_eta_commit_row(row: Mapping[str, Any]) -> bool:
    """True when STR ETA-Table may refresh (Way change or VP/L2 explore).

    Operator lock (improving_SE_v6): table stays static except Way change, or
    same Way with VP gained that triggers L2.
    """
    wc = str(row.get("way_changed") or "").strip().lower()
    if wc in ("1", "true", "yes", "y"):
        return True
    mode = str(row.get("refresh_mode") or "").strip().lower()
    detail = " ".join(
        str(row.get(k) or "")
        for k in (
            "refresh_mode_detail",
            "l2_force_reason",
            "l2_gate",
            "sticky_invalidate_reason",
            "way_switch_cause",
            "target_switch_cause",
        )
    ).lower()
    if mode in ("explore", "explicit", "l2"):
        # VP / TFR endgame L2, forced recalc, explicit 142, structure milestone
        needles = (
            "dcard_vp",
            "dcard_tfr",
            "vp_drawn",
            "force_strategy_recalc",
            "explicit_142",
            "explicit_explore",
            "need_next_target",
            "own_city",
            "own_settlement",
            "own_largest_army",
            "own_longest_road",
            "way_change",
        )
        if any(n in detail for n in needles):
            return True
        if wc in ("1", "true", "yes"):
            return True
    return False


def _fmt_eta_num(v: Any) -> str:
    try:
        if v is None or v == "" or v == "—":
            return "—"
        f = float(v)
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        # Dig §5 examples use two decimals (4.25); strip trailing zeros
        return f"{f:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "—"


def _fmt_eta_dt(v: Any) -> str:
    try:
        if v is None or v == "" or v == "—":
            return "—"
        f = float(v)
        if abs(f) < 1e-9:
            return "0"
        # Match Plan/Prev precision (e.g. +0.5, +0.25)
        s = f"{f:+.2f}".rstrip("0").rstrip(".")
        if s in ("+", "-", "+.", "-."):
            return "0"
        return s
    except Exception:
        return "—"


def str_eta_table_model(
    row: Mapping[str, Any],
    *,
    rows: Optional[Sequence[Mapping[str, Any]]] = None,
    cursor: Optional[int] = None,
) -> Dict[str, Any]:
    """Static Plan/Prev victory-ETA snapshot for Dig STR (WP-J).

    Prefers last commit row (Way change / VP+L2 explore) ≤ cursor for the seat.
    Does **not** recompute from live PLN2 sticky (that washed the table every scrub).

    Plan: Old=prev_turns, New=turns|eta_locked, Dt=New−Old  
    Prev: after commit, Plan-old copied → Old=New=that value, Dt=0  
    Summary △t: Plan.New − Prev.New
    """
    commit = dict(row or {})
    if rows is not None and cursor is not None and 0 <= int(cursor) < len(rows):
        try:
            pid = None
            try:
                pid = int(float((row or {}).get("player_id")))
            except Exception:
                try:
                    pid = int(float(rows[int(cursor)].get("player_id")))
                except Exception:
                    pid = None
            found = None
            for i in range(int(cursor), -1, -1):
                r = rows[i]
                if pid is not None:
                    try:
                        if int(float(r.get("player_id"))) != int(pid):
                            continue
                    except Exception:
                        continue
                if is_str_eta_commit_row(r):
                    found = r
                    break
            if found is not None:
                commit = dict(found)
        except Exception:
            pass

    plan_new = _safe_float(commit.get("eta_locked"), None)
    if plan_new is None:
        plan_new = _safe_float(commit.get("turns"), None)
    plan_old = _safe_float(commit.get("prev_turns"), None)
    if plan_old is None and plan_new is not None:
        # No prev sample — treat as flat
        plan_old = plan_new
    plan_dt = None
    if plan_old is not None and plan_new is not None:
        plan_dt = round(float(plan_new) - float(plan_old), 1)

    # Prev holds the pre-update Plan value (static until next commit)
    prev_val = plan_old
    prev_dt = 0.0 if prev_val is not None else None
    summary_dt = None
    if plan_new is not None and prev_val is not None:
        summary_dt = round(float(plan_new) - float(prev_val), 1)

    return {
        "plan_old": plan_old,
        "plan_new": plan_new,
        "plan_dt": plan_dt,
        "prev_old": prev_val,
        "prev_new": prev_val,
        "prev_dt": prev_dt,
        "summary_dt": summary_dt,
        "commit": commit,
    }


# Dig §5: triangle+t column mark (Dig GUI draws a real triangle; string keeps △).
ETA_DT_MARK = "△t"


def format_str_eta_table_line(
    key: str,
    row: Mapping[str, Any],
    *,
    rows: Optional[Sequence[Mapping[str, Any]]] = None,
    cursor: Optional[int] = None,
) -> str:
    """Format one STR ETA-Table data line (hdr / Plan / Prev).

    Dig §5 layout (no duplicated Type/Plan/Prev labels in Dig — Dig draws the
    title separately and uses empty field labels for these keys):

        ETA-Table
        Type    Old     New     △t
        Plan    4.25    4.7     +0.5
        Prev    4.25    4.25    0
    """
    model = str_eta_table_model(row, rows=rows, cursor=cursor)
    # Fixed columns so Dig doesn't smash Prev/New together (was "Prev Prev4.25")
    if key == "_eta_hdr":
        return f"{'Type':<6} {'Old':>6} {'New':>6}  {ETA_DT_MARK}"
    if key == "_eta_plan":
        return (
            f"{'Plan':<6} {_fmt_eta_num(model['plan_old']):>6} "
            f"{_fmt_eta_num(model['plan_new']):>6}  {_fmt_eta_dt(model['plan_dt'])}"
        )
    if key == "_eta_prev":
        return (
            f"{'Prev':<6} {_fmt_eta_num(model['prev_old']):>6} "
            f"{_fmt_eta_num(model['prev_new']):>6}  {_fmt_eta_dt(model['prev_dt'])}"
        )
    # Legacy key kept for older Dig builds / tests
    if key == "_eta_delta":
        return f"{ETA_DT_MARK:<6} {_fmt_eta_dt(model['summary_dt'])}"
    return ""


__all__ = [
    "SHOW_RADIUS_MATRIX",
    "PLAYER_RADIUS_BY_COLOR",
    "RISK_RADIUS",
    "PORT_DOT_RADIUS",
    "SHOW_RING_OWN",
    "SHOW_RING_STEP",
    "PLAN_CATALOG_DETAIL",
    "radius_for_show",
    "radius_for_player_color",
    "resolve_se_pick_id",
    "encode_plan_catalog_row",
    "parse_plan_catalog",
    "why_for_se_pick",
    "build_plan_show_entries",
    "build_plan_snapshot",
    "refresh_plan_snapshot",
    "encode_plan_cs_fields",
    "cs_fields_from_plan_snapshot",
    "parse_plan_settles",
    "parse_plan_cities",
    "parse_plan_show",
    "parse_why2_lines",
    "plan_stale_tf",
    "pln2_table_for_dig",
    "plan_lines_for_dig",
    "why2_lines_for_dig",
    "str_field_slots",
    "is_str_eta_commit_row",
    "str_eta_table_model",
    "format_str_eta_table_line",
    "ETA_DT_MARK",
]
