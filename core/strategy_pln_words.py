"""P6: PLN1 Words + PLN2 Why mapping (shared vocabulary).

Priority when several Why tags match (product plan):
  Race > Hot > Engine > Deny > Closer > City/Calm/Cap > Opportunity > Specials > Wayfit > Sticky

Fastest is exclusive when SE pick == PLN2 #1.

Refinements v1 locks (2026-08-21):
  - risk=L → Why **Prio** (not Race) on settle/road rows
  - **Calm** when no pressure (e.g. no opp knights for LA)
  - **Engine** when sticky settle automatically delivers LR
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


PLN2_WHY_WORDS = (
    "Fastest",
    "Race",
    "Hot",
    "Engine",
    "Deny",
    "Closer",
    "City",
    "Calm",
    "Cap",
    "Prio",
    "Opportunity",
    "Specials",
    "Wayfit",
    "Sticky",
    "Now",
)

# PLN1 component Why tokens (refinements v1)
PLN1_WHY_WORDS = (
    "Race",
    "Hot",
    "Engine",
    "Calm",
    "Prio",
    "Expand first",
    "Cap",
)

# Evaluation order for non-Fastest (first match wins).
# Cap/Calm outrank generic City when PLN1 supplies them.
_WHY_PRIORITY = (
    "Race",
    "Hot",
    "Engine",
    "Deny",
    "Closer",
    "Cap",
    "Calm",
    "City",
    "Opportunity",
    "Specials",
    "Prio",  # refinements: risk=L settle — below Specials/City
    "Wayfit",
    "Sticky",
)


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


def _risk_bucket(raw: Any) -> str:
    s = str(raw or "low").strip().lower()
    if s in ("medium", "med"):
        return "med"
    if s in ("high", "blocked", "crit", "low", "med"):
        return s
    if "block" in s:
        return "blocked"
    if "high" in s or "crit" in s:
        return "high"
    if "med" in s:
        return "med"
    return "low"


def collect_why_candidates(
    catalog: Sequence[Mapping[str, Any]],
    se_pick_label: str,
    *,
    pln1_word: Optional[str] = None,
    sticky_held: bool = False,
    board_fit_force: bool = False,
    specials_drive: bool = False,
    city_probe: bool = False,
    deny_hint: bool = False,
) -> List[str]:
    """Return matching Why tags for SE≠Fastest (unordered; apply priority after)."""
    rows = list(catalog or [])
    if not rows or not se_pick_label:
        return ["Sticky"]
    fastest = str(rows[0].get("label") or "")
    if se_pick_label == fastest:
        return ["Fastest"]

    pick = next((r for r in rows if str(r.get("label")) == se_pick_label), None)
    hits: List[str] = []
    if pick is None:
        hits.append("Sticky")
        return hits

    kind = str(pick.get("kind") or "S").upper()
    risk = _risk_bucket(pick.get("risk"))
    delta = _safe_float(pick.get("delta_t"))
    role = str(pick.get("role") or "").lower()

    # Hot vs Race vs Prio (refinements: risk=L on settle → Prio, not Race)
    if risk in ("high", "blocked", "crit"):
        hits.append("Hot")
    elif risk in ("med", "medium"):
        hits.append("Race")
    elif risk in ("low", "safe", "") and kind == "S":
        hits.append("Prio")
    elif delta is not None and float(delta) > 0 and kind == "S":
        # locked delta = self - opp; opp earlier ⇒ positive
        hits.append("Race")

    if role in ("critical", "important"):
        hits.append("Engine")

    if deny_hint:
        hits.append("Deny")

    try:
        fast_dist = int(rows[0].get("dist") if rows[0].get("dist") is not None else 99)
        pick_dist = int(pick.get("dist") if pick.get("dist") is not None else 99)
        if kind == "S" and pick_dist < fast_dist:
            hits.append("Closer")
    except Exception:
        pass

    if kind == "C":
        hits.append("City")
        pw = str(pln1_word or "").strip()
        if pw in ("Calm", "Cap"):
            hits.append(pw)

    if city_probe:
        hits.append("Opportunity")

    if specials_drive:
        hits.append("Specials")

    if board_fit_force:
        hits.append("Wayfit")

    if sticky_held or se_pick_label != fastest:
        hits.append("Sticky")

    if not hits:
        hits.append("Sticky")
    return hits


def pick_why_word(candidates: Sequence[str]) -> str:
    """Apply product priority; never empty."""
    if "Fastest" in candidates:
        return "Fastest"
    cand_set = {str(c) for c in candidates if c}
    for w in _WHY_PRIORITY:
        if w in cand_set:
            return w
    return "Sticky"


def why_for_se_pick(
    catalog: Sequence[Mapping[str, Any]],
    se_pick_label: Optional[str],
    *,
    pln1_word: Optional[str] = None,
    sticky_held: bool = False,
    board_fit_force: bool = False,
    specials_drive: bool = False,
    city_probe: bool = False,
    deny_hint: bool = False,
) -> Optional[str]:
    """PLN2 Why on SE row — always non-empty when se_pick_label set."""
    if not se_pick_label:
        return None
    hits = collect_why_candidates(
        catalog,
        str(se_pick_label),
        pln1_word=pln1_word,
        sticky_held=sticky_held,
        board_fit_force=board_fit_force,
        specials_drive=specials_drive,
        city_probe=city_probe,
        deny_hint=deny_hint,
    )
    return pick_why_word(hits)


def infer_why_context(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
    *,
    pln1: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Best-effort flags for Why refinement after PLN1."""
    preferred = preferred if isinstance(preferred, Mapping) else {}
    pln1 = pln1 if isinstance(pln1, Mapping) else {}
    ctx = {
        "pln1_word": str(pln1.get("word") or (pln1.get("cs") or {}).get("pln1_word") or "")
        or None,
        "sticky_held": False,
        "board_fit_force": False,
        "specials_drive": False,
        "city_probe": False,
        "deny_hint": False,
    }
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        ctx["sticky_held"] = bool(isinstance(c, Mapping) and c.get("locked_rec_target_id"))
    except Exception:
        pass
    try:
        # board-fit force markers on preferred / last sticky meta
        meta = getattr(player, "last_sticky_meta", None)
        if isinstance(meta, Mapping):
            reason = str(meta.get("sticky_invalidate_reason") or meta.get("l2_force_reason") or "")
            if "board_fit" in reason.lower() or "fit" in reason.lower():
                ctx["board_fit_force"] = True
        if str(preferred.get("preference_reason") or "").lower().find("board_fit") >= 0:
            ctx["board_fit_force"] = True
    except Exception:
        pass
    try:
        la = getattr(player, "la_race_plan", None)
        lr = getattr(player, "lr_race_plan", None)
        if isinstance(la, Mapping) and (la.get("la_race") or la.get("play_knight")):
            ctx["specials_drive"] = True
        if isinstance(lr, Mapping) and (lr.get("claim_now") or lr.get("contested")):
            ctx["specials_drive"] = True
        now = str(pln1.get("now") or "")
        if now in ("LA", "LR", "DC"):
            ctx["specials_drive"] = True
    except Exception:
        pass
    try:
        probe = getattr(game, "last_s2b_city_probe", None) if game is not None else None
        if isinstance(probe, Mapping) and probe.get("unlock_city"):
            ctx["city_probe"] = True
        if str(preferred.get("supporting_action_type") or "").lower().find("city") >= 0:
            # opportunity-ish if pln1 Calm from probe path — soft
            pass
    except Exception:
        pass
    # Deny: high risk with competitors listed on pick — handled via Hot/Race mostly
    return ctx


def pln1_word_for_now(
    now: str,
    *,
    req_settles: int = 0,
    contested: bool = False,
    role: str = "",
    se_pick_vs_fastest: bool = False,
    board_fit_force: bool = False,
    support: str = "",
) -> str:
    """PLN1 component Word (never empty)."""
    now = str(now or "Settle")
    support = str(support or "").lower()
    role = str(role or "").lower()

    if now == "City" and int(req_settles or 0) == 0:
        return "Cap"
    if now == "City" and not contested:
        return "Calm"
    if now == "City":
        return "Calm"
    if now in ("Settle", "Road") and contested:
        return "Race"
    if now == "Settle" and role in ("critical", "important"):
        return "Engine"
    if now in ("LA", "LR", "DC"):
        return "Specials"
    if board_fit_force:
        return "Wayfit"
    if se_pick_vs_fastest:
        return "Sticky"
    if "city" in support:
        return "Calm" if int(req_settles or 0) > 0 else "Cap"
    if "road" in support or "settle" in support:
        return "Race" if contested else "Sticky"
    return "Sticky"


def pln1_why_for_structure(*, risk: Any = None, engine: bool = False) -> str:
    """Refinements v1: risk=L → Prio; M → Race; H → Hot; Engine overrides."""
    if engine:
        return "Engine"
    b = _risk_bucket(risk)
    if b in ("high", "blocked", "crit"):
        return "Hot"
    if b in ("med", "medium"):
        return "Race"
    return "Prio"


def format_road_path_compact(roads_fp: Any) -> str:
    """Compact ``50-51, 51-62`` from sticky fingerprint / list forms."""
    if roads_fp is None:
        return ""
    if isinstance(roads_fp, (list, tuple)):
        segs = []
        for edge in roads_fp:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                try:
                    a, b = int(edge[0]), int(edge[1])
                    segs.append(f"{a}-{b}")
                except Exception:
                    continue
        return ", ".join(segs)
    s = str(roads_fp).strip()
    if not s:
        return ""
    # Already compact
    if "-" in s and "[[" not in s and ";" not in s and "," in s:
        return s.replace(" ", "")
    # fingerprint a-b;c-d
    if ";" in s or ("-" in s and "[" not in s):
        parts = []
        for part in s.replace(";", ",").split(","):
            part = part.strip()
            if "-" in part and part.count("-") == 1:
                parts.append(part.replace(" ", ""))
        if parts:
            return ", ".join(parts)
    # [[a, b], [b, c]]
    import re

    pairs = re.findall(r"\[?\s*(\d+)\s*,\s*(\d+)\s*\]?", s)
    if pairs:
        return ", ".join(f"{a}-{b}" for a, b in pairs)
    return s


def dt_color_favourable(delta: Any, *, invert: bool = False) -> str:
    """STR / PLN2 Dig convention: green if △t≤0 (ahead/tied), red if △t>0.

    Dig §7 (v7): PLN2 uses the same polarity as STR (``invert=False``).
    ``invert=True`` kept for experiments only.
    """
    try:
        if delta is None or delta == "" or delta == "—":
            return ""
        v = float(delta)
    except Exception:
        return ""
    tone = "green" if v <= 0 else "red"
    if invert:
        if tone == "green":
            return "red"
        if tone == "red":
            return "green"
    return tone


__all__ = [
    "PLN2_WHY_WORDS",
    "PLN1_WHY_WORDS",
    "why_for_se_pick",
    "collect_why_candidates",
    "pick_why_word",
    "infer_why_context",
    "pln1_word_for_now",
    "pln1_why_for_structure",
    "format_road_path_compact",
    "dt_color_favourable",
]
