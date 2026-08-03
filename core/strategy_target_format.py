"""S-pack: sticky / PROJ / WAYS target display tokens (S@ / C@) + multi-target.

S11/S12: never show bare ``Target: —`` when city/settle intent exists; format
as ``S@id`` / ``C@id``.
S13: multi-target lines e.g. ``S@6 | C@42 | Buy DCard``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Kind tags used in sticky / UI
KIND_SETTLE = "S"
KIND_CITY = "C"
KIND_ROAD = "R"
KIND_DCARD = "DCard"
KIND_LA = "LA"
KIND_LR = "LR"
KIND_UNKNOWN = ""

MAX_DISPLAY_TARGETS = 3


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def race_suffix_from_row(target_row: Any = None) -> str:
    """S17: append competitor note only when contested; empty for free S@."""
    if target_row is None:
        return ""
    try:
        from core.strategy_sticky import race_competitor_annotation

        return race_competitor_annotation(target_row)
    except Exception:
        pass
    if isinstance(target_row, Mapping):
        race = str(target_row.get("race_status") or "").lower()
        if race == "contested":
            return " race"
        if race == "likely_lost":
            return " lost?"
    return ""


def format_target_token(
    kind: str,
    target_id: Any = None,
    *,
    label: str = "",
    race_suffix: str = "",
) -> str:
    """Return a compact display token: S@6, C@42, Buy DCard, etc.

    S17: optional ``race_suffix`` (e.g. `` race P3``) only for contested sites.
    """
    k = str(kind or "").strip().upper()
    suffix = str(race_suffix or "")
    if k in ("S", "SETTLE", "SETTLEMENT", "NEW_SETTLEMENT", "NEXT_SETTLEMENT"):
        tid = _safe_int(target_id, None)
        base = f"S@{tid}" if tid is not None else (label or "S@?")
        return base + suffix
    if k in ("C", "CITY", "CITY_UPGRADE", "BUILD_CITY"):
        tid = _safe_int(target_id, None)
        return f"C@{tid}" if tid is not None else (label or "C@?")
    if k in ("R", "ROAD", "BUILD_ROAD"):
        if label:
            return str(label)
        tid = _safe_int(target_id, None)
        return f"Road {tid}" if tid is not None else "Road"
    if k in ("DCARD", "BUY_DCARD", "BUY_DEVELOPMENT_CARD", "DEVELOPMENT_CARD", "D"):
        return "Buy DCard"
    if k in ("LA", "LARGEST_ARMY", "ARMY"):
        # S-LA-A: optional rich label e.g. LA 2/3, LA take, LA hold
        if label and str(label).strip().upper().startswith("LA"):
            return str(label).strip()
        return "LA"
    if k in ("LR", "LONGEST_ROAD", "LONGEST"):
        return "LR"
    if label:
        return str(label)
    tid = _safe_int(target_id, None)
    if tid is not None:
        return f"@{tid}"
    return "—"


def infer_target_kind_from_support(support: Any) -> str:
    text = str(support or "").strip().lower()
    if not text:
        return KIND_UNKNOWN
    if "city" in text:
        return KIND_CITY
    if "settle" in text or "settlement" in text:
        return KIND_SETTLE
    if "road" in text:
        return KIND_ROAD
    if "dcard" in text or "development" in text:
        return KIND_DCARD
    if "army" in text or text == "la":
        return KIND_LA
    if "longest" in text or text == "lr":
        return KIND_LR
    return KIND_UNKNOWN


def infer_target_kind(
    direction: Optional[Mapping[str, Any]] = None,
    *,
    player: Any = None,
    target_id: Any = None,
    target_row: Any = None,
) -> str:
    """Best-effort kind for a target id / portfolio row."""
    # Explicit on row
    if isinstance(target_row, Mapping):
        for key in ("target_kind", "kind", "portfolio_role", "project_type", "type"):
            raw = str(target_row.get(key) or "").lower()
            if "city" in raw:
                return KIND_CITY
            if "settle" in raw or "new_s" in raw or raw in ("new", "critical", "important", "useful"):
                # portfolio settle targets often use role critical/important
                if "city" not in raw:
                    # prefer settle for portfolio new targets
                    if "city" not in raw and raw not in ("city_upgrade",):
                        if "city" in str(target_row.get("target_kind") or ""):
                            return KIND_CITY
                        if raw in ("city_upgrade",):
                            return KIND_CITY
            if "city_upgrade" in raw:
                return KIND_CITY
            if raw in ("new_settlement", "settlement", "new", "expand"):
                return KIND_SETTLE
        tk = str(target_row.get("target_kind") or "").lower()
        if "city" in tk:
            return KIND_CITY
        if "settle" in tk or "new" in tk:
            return KIND_SETTLE

    direction = direction if isinstance(direction, Mapping) else {}
    locked_kind = str(direction.get("locked_target_kind") or direction.get("target_kind") or "")
    if locked_kind:
        k = infer_target_kind_from_support(locked_kind)
        if k:
            return k

    support = direction.get("supporting_action_type") or direction.get("supporting_action")
    k = infer_target_kind_from_support(support)
    if k in (KIND_CITY, KIND_SETTLE, KIND_ROAD, KIND_DCARD):
        # If city support but id is still a settlement (to upgrade) — still C
        return k

    tid = _safe_int(target_id, None)
    if tid is not None and player is not None:
        try:
            cities = {int(x) for x in list(getattr(player, "cities", []) or [])}
            settlements = {int(x) for x in list(getattr(player, "settlements", []) or [])}
            if tid in cities:
                return KIND_CITY
            if tid in settlements:
                # Own settlement without city → city candidate if way wants cities
                rem = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
                cities_left = 0
                try:
                    cities_left = int((rem or {}).get("cities") or 0)
                except Exception:
                    cities_left = 0
                tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
                if cities_left > 0 or "city" in tags or "cities" in tags:
                    return KIND_CITY
                return KIND_SETTLE
        except Exception:
            pass

    if k:
        return k
    return KIND_SETTLE  # default display as settle when unknown id


def settlement_ids_upgradable(player: Any) -> List[int]:
    """Settlement ids that are not yet cities (city_upgrade candidates)."""
    if player is None:
        return []
    try:
        cities = {int(x) for x in list(getattr(player, "cities", []) or [])}
    except Exception:
        cities = set()
    out: List[int] = []
    seen = set()
    for item in list(getattr(player, "settlements", []) or []):
        try:
            sid = int(item)
        except Exception:
            continue
        if sid in cities or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def pick_city_upgrade_target(player: Any, *, preferred_id: Any = None) -> Optional[int]:
    """Pick best settlement to lock as C@id for city paths (S11)."""
    cands = settlement_ids_upgradable(player)
    if not cands:
        return None
    pref = _safe_int(preferred_id, None)
    if pref is not None and pref in cands:
        return pref
    # Prefer higher production later; for now stable lowest id (deterministic)
    return sorted(cands)[0]


def _way_wants_cities(direction: Mapping[str, Any]) -> bool:
    rem = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
    try:
        if int((rem or {}).get("cities") or 0) > 0:
            return True
    except Exception:
        pass
    tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
    if "city" in tags:
        return True
    support = str(direction.get("supporting_action_type") or "").lower()
    return "city" in support


def _way_wants_settle(direction: Mapping[str, Any]) -> bool:
    rem = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
    try:
        if int((rem or {}).get("new_settlements") or 0) > 0:
            return True
    except Exception:
        pass
    tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
    if "settle" in tags:
        return True
    support = str(direction.get("supporting_action_type") or "").lower()
    return "settle" in support


def _way_wants_dcard_or_la(direction: Mapping[str, Any]) -> bool:
    rem = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
    try:
        if int((rem or {}).get("development_cards") or 0) > 0:
            return True
    except Exception:
        pass
    tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
    if "army" in tags or "largest" in tags or "vp card" in tags:
        return True
    support = str(direction.get("supporting_action_type") or "").lower()
    return "dcard" in support or "development" in support


def _way_wants_lr(direction: Mapping[str, Any]) -> bool:
    tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
    if "longest" in tags and "road" in tags:
        return True
    if bool(direction.get("longest_road") or direction.get("longest_route")):
        return True
    roads = list(direction.get("roads_to_build") or direction.get("locked_roads_to_build") or [])
    return bool(roads)


def primary_target_id(direction: Mapping[str, Any]) -> Optional[int]:
    if not isinstance(direction, Mapping):
        return None
    for key in (
        "locked_rec_target_id",
        "recommendation_target_id",
        "settlement_target_id",
        "new_settlement_target_id",
        "target_id",
        "supporting_action_target_id",
        "supporting_action_future_settlement_target_id",
    ):
        tid = _safe_int(direction.get(key), None)
        if tid is not None:
            return tid
    pt = direction.get("project_target")
    if isinstance(pt, Mapping):
        return _safe_int(pt.get("target_id"), None)
    return None


def enrich_direction_city_target(
    direction: Mapping[str, Any],
    player: Any,
) -> Dict[str, Any]:
    """S11: when city intent exists without rec target, lock best C@id."""
    out = dict(direction or {})
    support = str(out.get("supporting_action_type") or "").lower()
    wants_city = _way_wants_cities(out) or "city" in support
    tid = primary_target_id(out)
    if wants_city and tid is None:
        picked = pick_city_upgrade_target(player)
        if picked is not None:
            out["recommendation_target_id"] = picked
            out["target_id"] = picked
            out["locked_rec_target_id"] = picked
            out["city_upgrade_target_id"] = picked
            out["locked_target_kind"] = KIND_CITY
            out["target_kind"] = KIND_CITY
            out["supporting_action_type"] = out.get("supporting_action_type") or "city_upgrade"
            out["recommendation"] = out.get("recommendation") or f"city C@{picked}"
            out["supporting_action"] = out.get("supporting_action") or out["recommendation"]
            out["target_label"] = f"city_upgrade@C@{picked}"
            return out
    if wants_city and tid is not None:
        # Tag existing id as city when way wants cities and id is own settlement
        try:
            settlements = {int(x) for x in list(getattr(player, "settlements", []) or [])}
            cities = {int(x) for x in list(getattr(player, "cities", []) or [])}
            if tid in settlements and tid not in cities:
                out["locked_target_kind"] = KIND_CITY
                out["target_kind"] = KIND_CITY
                out["city_upgrade_target_id"] = tid
                if "city" not in str(out.get("supporting_action_type") or "").lower():
                    if not _way_wants_settle(out):
                        out["supporting_action_type"] = "city_upgrade"
        except Exception:
            pass
    return out


def collect_display_targets(
    direction: Optional[Mapping[str, Any]] = None,
    *,
    player: Any = None,
    max_targets: int = MAX_DISPLAY_TARGETS,
) -> List[Dict[str, Any]]:
    """Build ordered list of {kind, target_id, token} for sticky/PROJ (S13)."""
    direction = dict(direction or {}) if isinstance(direction, Mapping) else {}
    if player is not None:
        direction = enrich_direction_city_target(direction, player)

    items: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(
        kind: str,
        tid: Any = None,
        *,
        label: str = "",
        target_row: Any = None,
    ) -> None:
        race_s = ""
        if str(kind).upper() in ("S", "SETTLE", "SETTLEMENT") or kind == KIND_SETTLE:
            race_s = race_suffix_from_row(target_row)
        token = format_target_token(kind, tid, label=label, race_suffix=race_s)
        key = (str(kind).upper(), _safe_int(tid, -1), token)
        if key in seen:
            return
        if token in ("—", ""):
            return
        seen.add(key)
        items.append({
            "kind": kind,
            "target_id": _safe_int(tid, None),
            "token": token,
            "race_suffix": race_s or None,
        })

    # 1) Primary locked / recommendation target
    primary = primary_target_id(direction)
    primary_kind = infer_target_kind(direction, player=player, target_id=primary)
    primary_row = direction.get("project_target")
    if not isinstance(primary_row, Mapping):
        primary_row = {
            "race_status": direction.get("rec_race_status"),
            "risk_level": direction.get("rec_risk_level"),
            "threat_opponents": direction.get("threat_opponents"),
        }
    if primary is not None:
        _add(primary_kind or KIND_SETTLE, primary, target_row=primary_row)
    elif primary_kind == KIND_DCARD:
        _add(KIND_DCARD)

    # 2) Portfolio secondaries (other settle/city targets)
    portfolio = list(direction.get("target_portfolio") or [])
    for row in portfolio:
        if len(items) >= max(1, int(max_targets)):
            break
        if not isinstance(row, Mapping):
            continue
        tid = _safe_int(row.get("target_id"), None)
        if tid is None or tid == primary:
            continue
        kind = infer_target_kind(direction, player=player, target_id=tid, target_row=row)
        # Only add settle/city portfolio peers for multi-target density
        if kind not in (KIND_SETTLE, KIND_CITY):
            # role-based settle portfolio
            role = str(row.get("portfolio_role") or "").lower()
            if role in ("critical", "important", "useful", "new"):
                kind = KIND_SETTLE
            else:
                continue
        _add(kind, tid, target_row=row)

    # 3) City path secondary if primary is settle and way also wants cities
    if _way_wants_cities(direction) and player is not None:
        city_tid = _safe_int(direction.get("city_upgrade_target_id"), None)
        if city_tid is None:
            city_tid = pick_city_upgrade_target(player, preferred_id=primary)
        if city_tid is not None and city_tid != primary:
            _add(KIND_CITY, city_tid)

    # 4) LA progress token (S-LA-A) — prefer rich label over generic Buy DCard
    la_label = ""
    la_prog = direction.get("la_progress")
    if not isinstance(la_prog, Mapping) and player is not None:
        try:
            sticky = getattr(player, "sticky_commitment", None)
            if isinstance(sticky, Mapping) and isinstance(sticky.get("la_progress"), Mapping):
                la_prog = sticky.get("la_progress")
            elif isinstance(getattr(player, "la_progress", None), Mapping):
                la_prog = getattr(player, "la_progress")
        except Exception:
            la_prog = None
    if isinstance(la_prog, Mapping) and la_prog:
        try:
            from core.ai_la_progress import format_la_progress_token

            la_label = format_la_progress_token(la_prog)
        except Exception:
            la_label = str(la_prog.get("target_label") or "LA")
        _add(KIND_LA, label=la_label or "LA")
    elif _way_wants_dcard_or_la(direction):
        # Prefer LA over Buy DCard when way tags army
        tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
        if (
            bool(direction.get("biggest_army") or direction.get("largest_army"))
            or "army" in tags
            or "largest" in tags
        ):
            _add(KIND_LA, label="LA")
        else:
            _add(KIND_DCARD)

    # 5) LR project / way tag (S-LR-A2: prefer explicit project token)
    lr_proj = direction.get("lr_project")
    if isinstance(lr_proj, Mapping) and lr_proj.get("roads_to_build"):
        _add(KIND_LR)
    elif player is not None:
        try:
            sticky = getattr(player, "sticky_commitment", None)
            if isinstance(sticky, Mapping):
                sp = sticky.get("lr_project")
                if isinstance(sp, Mapping) and sp.get("roads_to_build"):
                    _add(KIND_LR)
        except Exception:
            pass
    if not any(str(i.get("kind") or "").upper() == "LR" for i in items):
        if _way_wants_lr(direction):
            roads = list(
                direction.get("roads_to_build") or direction.get("locked_roads_to_build") or []
            )
            if roads:
                _add(KIND_ROAD, label="Road")
            else:
                _add(KIND_LR)

    return items[: max(1, int(max_targets or MAX_DISPLAY_TARGETS))]


def format_targets_line(
    direction: Optional[Mapping[str, Any]] = None,
    *,
    player: Any = None,
    max_targets: int = MAX_DISPLAY_TARGETS,
    empty: str = "—",
) -> str:
    """S13 display: ``S@6 | C@42 | Buy DCard`` or empty placeholder."""
    items = collect_display_targets(direction, player=player, max_targets=max_targets)
    if not items:
        return empty
    return " | ".join(str(i.get("token") or "") for i in items if i.get("token"))


def format_sticky_target_line(
    direction: Optional[Mapping[str, Any]] = None,
    *,
    player: Any = None,
) -> str:
    """Full sticky row: ``Target: S@6 | C@42``."""
    body = format_targets_line(direction, player=player, empty="—")
    return f"Target: {body}"


def format_proj_target_label(
    target_id: Any,
    *,
    direction: Optional[Mapping[str, Any]] = None,
    player: Any = None,
    target_row: Any = None,
) -> str:
    """PROJ/WAYS cell label with S@ / C@ (S17 race suffix when contested)."""
    kind = infer_target_kind(
        direction, player=player, target_id=target_id, target_row=target_row
    )
    race_s = ""
    if (kind or KIND_SETTLE) == KIND_SETTLE:
        row = target_row
        if row is None and isinstance(direction, Mapping):
            pt = direction.get("project_target")
            if isinstance(pt, Mapping) and _safe_int(pt.get("target_id"), None) == _safe_int(
                target_id, None
            ):
                row = pt
        race_s = race_suffix_from_row(row)
    return format_target_token(kind or KIND_SETTLE, target_id, race_suffix=race_s)
