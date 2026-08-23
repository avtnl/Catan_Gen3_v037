"""P2: when sticky settle/road race risk is M/H, BA should chase the race.

Operator lock (improving_SE_v4 / Dig):
  - risk=L → keep current live BA ordering (no change)
  - risk=M or H → BA family points at the race (settlement and/or key road
    on the sticky path), not opportunistic Buy DCard

This is a soft priority overlay on top of route / S-LR-C / S6 tables.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_MED_HIGH = frozenset({"med", "medium", "high", "blocked", "crit", "critical"})


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _norm_risk(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in ("m", "med", "medium"):
        return "med"
    if s in ("h", "high", "blocked", "crit", "critical"):
        return "high"
    if s in ("l", "low", "safe", ""):
        return "low"
    return s


def _risk_is_race(level: str) -> bool:
    return _norm_risk(level) in _MED_HIGH or _norm_risk(level) in ("med", "high")


def _sticky_race_context(game: Any, player: Any) -> Dict[str, Any]:
    """Collect sticky target id/kind/risk + remaining race roads."""
    out: Dict[str, Any] = {
        "target_id": None,
        "target_kind": "",
        "risk_level": "low",
        "roads": [],
        "next_road": None,
        "way_id": None,
    }
    if player is None:
        return out
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
    except Exception:
        c = None
    if not isinstance(c, Mapping):
        c = {}
    out["target_id"] = _safe_int(c.get("locked_rec_target_id"), None)
    out["target_kind"] = str(c.get("locked_target_kind") or "").strip().lower()
    out["way_id"] = _safe_int(c.get("locked_way_id"), None)
    roads = []
    raw_roads = c.get("locked_roads_to_build") or []
    if isinstance(raw_roads, (list, tuple)):
        for edge in raw_roads:
            if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                try:
                    a, b = int(edge[0]), int(edge[1])
                    roads.append([min(a, b), max(a, b)])
                except Exception:
                    continue
    out["roads"] = roads
    if roads:
        out["next_road"] = list(roads[0])

    # Risk from sticky target / direction / last audit portfolio
    risk = str(c.get("risk_level") or c.get("locked_risk_level") or "").lower()
    if not risk or risk in ("low", "safe", ""):
        try:
            d = getattr(player, "strategic_direction", None)
            if isinstance(d, Mapping):
                risk = str(d.get("risk_level") or "").lower()
                if out["target_id"] is None:
                    out["target_id"] = _safe_int(
                        d.get("locked_rec_target_id")
                        or d.get("supporting_action_target_id")
                        or d.get("recommendation_target_id"),
                        None,
                    )
                if not out["target_kind"]:
                    out["target_kind"] = str(
                        d.get("locked_target_kind")
                        or d.get("supporting_action_type")
                        or ""
                    ).lower()
        except Exception:
            pass
    if (not risk or risk in ("low", "safe", "")) and game is not None:
        try:
            audits = list(getattr(game, "current_board_way_audits", None) or [])
            tid = out["target_id"]
            for audit in audits:
                port = getattr(audit, "target_portfolio", None)
                if port is None and isinstance(audit, Mapping):
                    port = audit.get("target_portfolio")
                for t in list(port or []):
                    t_id = None
                    if isinstance(t, Mapping):
                        t_id = _safe_int(t.get("target_id"), None)
                        rl = str(t.get("risk_level") or "").lower()
                    else:
                        t_id = _safe_int(getattr(t, "target_id", None), None)
                        rl = str(getattr(t, "risk_level", "") or "").lower()
                    if tid is not None and t_id == tid and rl:
                        risk = rl
                        break
                    if tid is None and rl in _MED_HIGH:
                        risk = rl
                        if t_id is not None:
                            out["target_id"] = t_id
                        break
                if risk in _MED_HIGH:
                    break
        except Exception:
            pass
    out["risk_level"] = _norm_risk(risk)
    if not out["target_kind"] and out["target_id"] is not None:
        out["target_kind"] = "settlement"
    return out


def race_ba_focus(game: Any, player: Any) -> Dict[str, Any]:
    """Return focus bag; ``apply`` False when risk=L (keep current BA order)."""
    ctx = _sticky_race_context(game, player)
    risk = _norm_risk(ctx.get("risk_level"))
    out: Dict[str, Any] = {
        "apply": False,
        "focus": "pass",
        "risk_level": risk,
        "target_id": ctx.get("target_id"),
        "next_road": ctx.get("next_road"),
        "reason": "risk_low_keep_current_ba",
        "dig_note": "",
    }
    if not _risk_is_race(risk):
        out["dig_note"] = "Race risk=L → current BA ordering"
        return out

    roads = list(ctx.get("roads") or [])
    tid = ctx.get("target_id")
    kind = str(ctx.get("target_kind") or "").lower()

    # Prefer next sticky road when path remains (race for connectivity / block)
    if roads:
        out["apply"] = True
        out["focus"] = "road"
        out["next_road"] = list(roads[0])
        out["reason"] = f"race_{risk}_key_road"
        out["dig_note"] = (
            f"Race risk={risk} → BA chase key road {roads[0]}"
            + (f" toward S{tid}" if tid is not None else "")
        )
        return out

    if tid is not None and ("settle" in kind or kind in ("", "new_settlement", "next_settlement")):
        out["apply"] = True
        out["focus"] = "settle"
        out["reason"] = f"race_{risk}_settlement"
        out["dig_note"] = f"Race risk={risk} → BA chase settlement S{tid}"
        return out

    if tid is not None and "city" in kind:
        out["apply"] = True
        out["focus"] = "city"
        out["reason"] = f"race_{risk}_city"
        out["dig_note"] = f"Race risk={risk} → BA chase city C{tid}"
        return out

    out["dig_note"] = f"Race risk={risk} but no sticky target/road"
    return out


def apply_race_ba_action_priority(
    base_priority: Mapping[str, int],
    focus_info: Optional[Mapping[str, Any]] = None,
) -> Dict[str, int]:
    """Elevate BA family when ``focus_info.apply`` (risk M/H). Lower int = higher priority."""
    out = {str(k): int(v) for k, v in dict(base_priority or {}).items()}
    if not isinstance(focus_info, Mapping) or not focus_info.get("apply"):
        return out
    focus = str(focus_info.get("focus") or "").lower()
    # Soft demote DCard while racing structure
    if "Buy development_card" in out:
        out["Buy development_card"] = max(int(out.get("Buy development_card") or 4), 5)
    if focus == "road":
        out["Build road"] = 0
        # Keep settle available if already adjacent
        if "Build settlement" in out:
            out["Build settlement"] = min(int(out.get("Build settlement") or 2), 1)
    elif focus == "settle":
        out["Build settlement"] = 0
        if "Build road" in out:
            out["Build road"] = min(int(out.get("Build road") or 2), 1)
    elif focus == "city":
        out["Build city"] = 0
    return out


def race_ba_sort_bonus(
    row: Mapping[str, Any],
    focus_info: Optional[Mapping[str, Any]],
) -> int:
    """0 = preferred race target match; 1 = same family; 2 = other."""
    if not isinstance(focus_info, Mapping) or not focus_info.get("apply"):
        return 1
    action = str(row.get("action") or "").strip()
    focus = str(focus_info.get("focus") or "").lower()
    tid = _safe_int(focus_info.get("target_id"), None)
    next_road = focus_info.get("next_road")

    def _row_tid() -> Optional[int]:
        for k in ("target_id", "intersection_id", "settlement_id", "city_id"):
            v = _safe_int(row.get(k), None)
            if v is not None:
                return v
        cands = list(row.get("candidates") or [])
        if cands and isinstance(cands[0], Mapping):
            return _safe_int(
                cands[0].get("target_id")
                or cands[0].get("intersection_id")
                or cands[0].get("road_id"),
                None,
            )
        return None

    def _row_road() -> Optional[List[int]]:
        for k in ("road_id", "road", "edge", "target_road"):
            raw = row.get(k)
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                try:
                    a, b = int(raw[0]), int(raw[1])
                    return [min(a, b), max(a, b)]
                except Exception:
                    pass
        cands = list(row.get("candidates") or [])
        if cands and isinstance(cands[0], Mapping):
            raw = cands[0].get("road_id") or cands[0].get("road")
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                try:
                    a, b = int(raw[0]), int(raw[1])
                    return [min(a, b), max(a, b)]
                except Exception:
                    pass
        return None

    if focus == "road" and action == "Build road":
        rr = _row_road()
        if next_road and rr and list(rr) == list(next_road):
            return 0
        return 1
    if focus == "settle" and action == "Build settlement":
        if tid is not None and _row_tid() == tid:
            return 0
        return 1
    if focus == "city" and action == "Build city":
        if tid is not None and _row_tid() == tid:
            return 0
        return 1
    if action == "Buy development_card":
        return 3
    return 2


__all__ = [
    "race_ba_focus",
    "apply_race_ba_action_priority",
    "race_ba_sort_bonus",
]
