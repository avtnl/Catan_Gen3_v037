"""S2b: cheap city opportunity probe (cached win-ETA only).

When expand is primary and the current way does **not** already need cities,
optionally unlock Build city if a cached board-way audit for a city-using alt
beats the current way's win-ETA by ≥ δ turns.

Hard caps (never full 142-way re-solve):
  - max 2 alt ways from cached board_way_audits
  - only if city is legal in scan and hand can pay this turn
  - skip on high rec-target risk / missing cache / huge ETA
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Product defaults (plan §10 / S2 doc)
CITY_OPPORTUNITY_DELTA = 2.5
CITY_OPPORTUNITY_MAX_ALTS = 2
INFINITE_TURNS = 9999.0
HUGE_ETA_SKIP = 500.0

_EXPAND_SUPPORT = frozenset({
    "new_settlement",
    "next_settlement",
    "build_settlement",
    "road",
    "build_road",
    "",  # empty treated carefully below
})

_HIGH_RISK = frozenset({"medium", "med", "high", "blocked"})


def _safe_float(value: Any, default: float = INFINITE_TURNS) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _audit_get(audit: Any, key: str, default: Any = None) -> Any:
    if audit is None:
        return default
    if isinstance(audit, Mapping):
        return audit.get(key, default)
    return getattr(audit, key, default)


def _audit_eta(audit: Any) -> float:
    for key in (
        "board_expected_turns",
        "realistic_expected_turns",
        "rank_key",
        "abstract_expected_turns",
    ):
        val = _audit_get(audit, key, None)
        if val is None or val == "":
            continue
        eta = _safe_float(val, INFINITE_TURNS)
        if eta < INFINITE_TURNS:
            return eta
    return INFINITE_TURNS


def _audit_way_id(audit: Any) -> Optional[int]:
    return _safe_int(_audit_get(audit, "way_id", None), None)


def _audit_needs_cities(audit: Any) -> bool:
    req = _audit_get(audit, "requirements", None)
    if not isinstance(req, Mapping):
        req = _audit_get(audit, "way_requirements", None)
    req = _as_mapping(req)
    for key in (
        "required_cities",
        "cities",
        "city_upgrades",
        "required_city_upgrades",
    ):
        if _safe_float(req.get(key), 0.0) > 0:
            return True
    # Nested remaining-style on audit notes
    rem = _as_mapping(_audit_get(audit, "remaining", None))
    if _safe_float(rem.get("cities"), 0.0) > 0:
        return True
    return False


def collect_cached_board_audits(game: Any, player: Any = None) -> List[Any]:
    """Pull cached board-way audits without re-solving the portfolio."""
    sources: List[Any] = []
    if game is not None:
        for attr in ("current_board_way_audits", "board_way_audits"):
            raw = getattr(game, attr, None)
            if raw:
                sources.append(raw)
        report = getattr(game, "last_action_timing_report", None)
        if isinstance(report, Mapping):
            raw = report.get("board_way_audits")
            if raw:
                sources.append(raw)
            # by_player board preferred may embed audits rarely — skip deep walk
    out: List[Any] = []
    seen_ways = set()
    for src in sources:
        for audit in list(src or []):
            wid = _audit_way_id(audit)
            if wid is not None and wid in seen_ways:
                continue
            if wid is not None:
                seen_ways.add(wid)
            out.append(audit)
        if out:
            break  # prefer first non-empty source (game cache first)
    return out


def city_legal_in_scan(scan: Any) -> bool:
    if scan is None:
        return False
    city_names = ("Build city", "build city", "BUILD_CITY", "city")
    flags = getattr(scan, "action_flags", None)
    if isinstance(flags, Mapping):
        for key, val in flags.items():
            if not val:
                continue
            k = str(key)
            if k in city_names or ("city" in k.lower() and "build" in k.lower()):
                return True
    cands = getattr(scan, "candidates", None)
    if isinstance(cands, Mapping):
        for key, val in cands.items():
            k = str(key).lower()
            if "city" in k and val:
                return True
    try:
        viable = scan.viable_actions() if hasattr(scan, "viable_actions") else []
        for a in list(viable or []):
            text = str(a).lower()
            if "city" in text and "build" in text:
                return True
    except Exception:
        pass
    return False


def player_can_afford_city(player: Any, game: Any = None) -> bool:
    if player is None:
        return False
    try:
        if callable(getattr(player, "can_afford", None)):
            return bool(player.can_afford("city") or player.can_afford("City"))
    except Exception:
        pass
    # Fallback: hand counts vs standard 2 wheat + 3 ore
    try:
        from core.constants import ResourceCard, COSTS

        cost = COSTS.get("city") or COSTS.get("City") or {}
        rcards = getattr(player, "rcards", {}) or {}
        for res, amt in cost.items():
            have = rcards.get(res, 0)
            if isinstance(have, (list, tuple)):
                have = 0
            if int(have or 0) < int(amt or 0):
                return False
        return bool(cost)
    except Exception:
        pass
    # Vector hand [Wh, Or, Wd, Br, Sh] if present via game helper
    try:
        getter = getattr(game, "_execution_cost_vector_for_action", None)
        can_pay = getattr(game, "_can_player_pay_execution_cost", None)
        if callable(getter) and callable(can_pay):
            cost = getter("Build city")
            return bool(can_pay(player, cost))
    except Exception:
        pass
    return False


def is_expand_primary(direction: Mapping[str, Any]) -> bool:
    support = str(direction.get("supporting_action_type") or "").strip().lower()
    if support in _EXPAND_SUPPORT and support != "":
        return True
    # No explicit support: treat settle/road remaining as expand
    rem = _as_mapping(direction.get("remaining"))
    if _safe_float(rem.get("new_settlements"), 0.0) > 0:
        return True
    if _safe_float(rem.get("roads"), 0.0) > 0 and _safe_float(rem.get("cities"), 0.0) <= 0:
        return True
    return False


def current_way_eta(direction: Mapping[str, Any], audits: Sequence[Any]) -> float:
    for key in (
        "board_expected_turns",
        "realistic_expected_turns",
        "rank_key",
    ):
        eta = _safe_float(direction.get(key), -1.0)
        if 0 <= eta < INFINITE_TURNS:
            return eta
    way_id = _safe_int(direction.get("preferred_way_id") or direction.get("way_id"), None)
    if way_id is not None:
        for a in audits:
            if _audit_way_id(a) == way_id:
                return _audit_eta(a)
    if audits:
        return _audit_eta(audits[0])
    return INFINITE_TURNS


def pick_city_alt_audits(
    audits: Sequence[Any],
    *,
    locked_way_id: Optional[int],
    max_alts: int = CITY_OPPORTUNITY_MAX_ALTS,
) -> List[Any]:
    """First max_alts cached audits that need cities and differ from locked way."""
    out: List[Any] = []
    for audit in list(audits or []):
        wid = _audit_way_id(audit)
        if locked_way_id is not None and wid == locked_way_id:
            continue
        if not _audit_needs_cities(audit):
            continue
        feas = str(_audit_get(audit, "feasibility", "") or "").lower()
        if feas in ("unrealistic", "impossible"):
            continue
        out.append(audit)
        if len(out) >= max(0, int(max_alts)):
            break
    return out


def should_opportunity_unlock_city(
    game: Any,
    player: Any,
    direction: Any,
    scan: Any = None,
    *,
    delta: float = CITY_OPPORTUNITY_DELTA,
    max_alts: int = CITY_OPPORTUNITY_MAX_ALTS,
    s2a_already_unlocks_city: bool = False,
) -> Dict[str, Any]:
    """Return probe meta; ``unlock_city`` True only on a clear cached ETA win.

    Never re-evaluates ways — cache only.
    """
    meta: Dict[str, Any] = {
        "unlock_city": False,
        "probed": False,
        "skipped": True,
        "reason": "",
        "delta": float(delta),
        "eta_current": None,
        "eta_alt": None,
        "alt_way_id": None,
        "gap": None,
        "alts_considered": 0,
        "s2b": True,
    }
    d = _as_mapping(direction)
    if not d:
        meta["reason"] = "no_direction"
        return meta
    if s2a_already_unlocks_city:
        meta["reason"] = "s2a_already_unlocks_city"
        return meta

    # Import helpers from EPM without circular import at module load if possible
    try:
        from core.execution_phase_manager import (
            rec_target_risk_fields,
            way_needs_cities,
        )
    except Exception:
        rec_target_risk_fields = None  # type: ignore
        way_needs_cities = None  # type: ignore

    if way_needs_cities is not None:
        needs_city, _, _ = way_needs_cities(d)
        if needs_city:
            meta["reason"] = "way_already_needs_cities"
            return meta

    if not is_expand_primary(d):
        meta["reason"] = "expand_not_primary"
        return meta

    risk, race, role = ("low", "safe", "")
    if rec_target_risk_fields is not None:
        risk, race, role = rec_target_risk_fields(d)
    else:
        pt = _as_mapping(d.get("project_target"))
        risk = str(pt.get("risk_level") or "low").lower()
        race = str(pt.get("race_status") or "safe").lower()
        role = str(pt.get("portfolio_role") or "").lower()
    meta["rec_risk"] = risk
    meta["rec_race"] = race
    if risk in _HIGH_RISK or (race == "contested" and role in ("critical", "important")):
        meta["reason"] = f"high_race_pressure:risk={risk},race={race},role={role}"
        return meta

    if not city_legal_in_scan(scan):
        meta["reason"] = "city_not_legal_in_scan"
        return meta

    if not player_can_afford_city(player, game):
        meta["reason"] = "city_not_affordable_this_turn"
        return meta

    audits = collect_cached_board_audits(game, player)
    if not audits:
        meta["reason"] = "no_cached_board_audits"
        return meta

    eta_cur = current_way_eta(d, audits)
    meta["eta_current"] = eta_cur
    if eta_cur >= HUGE_ETA_SKIP:
        meta["reason"] = f"current_eta_huge:{eta_cur}"
        return meta

    locked_way = _safe_int(d.get("preferred_way_id") or d.get("way_id") or d.get("locked_way_id"), None)
    alts = pick_city_alt_audits(audits, locked_way_id=locked_way, max_alts=max_alts)
    meta["alts_considered"] = len(alts)
    meta["probed"] = True
    if not alts:
        meta["reason"] = "no_city_alt_in_cache"
        return meta

    best_gap = None
    best_alt = None
    best_eta = None
    for alt in alts:
        eta_alt = _audit_eta(alt)
        if eta_alt >= INFINITE_TURNS:
            continue
        # Unlock if alt is at least δ turns faster: eta_alt + δ < eta_current
        if eta_alt + float(delta) < eta_cur:
            gap = eta_cur - eta_alt
            if best_gap is None or gap > best_gap:
                best_gap = gap
                best_alt = alt
                best_eta = eta_alt

    if best_alt is None:
        meta["skipped"] = True
        meta["reason"] = f"no_alt_beats_delta:{delta}"
        # Record closest for DBG
        try:
            closest = min((_audit_eta(a), _audit_way_id(a)) for a in alts)
            meta["eta_alt"] = closest[0]
            meta["alt_way_id"] = closest[1]
            meta["gap"] = eta_cur - closest[0]
        except Exception:
            pass
        return meta

    meta["unlock_city"] = True
    meta["skipped"] = False
    meta["eta_alt"] = best_eta
    meta["alt_way_id"] = _audit_way_id(best_alt)
    meta["gap"] = best_gap
    meta["reason"] = (
        f"opportunity_city_way_{meta['alt_way_id']}:"
        f"eta_alt={best_eta}+δ{delta}<eta_cur={eta_cur}"
    )
    return meta


def format_city_probe_dbg(meta: Mapping[str, Any]) -> str:
    """One-line DBG/R7-style summary."""
    if not meta:
        return "city_probe: n/a"
    if meta.get("s16") and meta.get("unlock_city"):
        return (
            f"city_probe: S16 unlock city_eta={meta.get('eta_city')} "
            f"settle_eta={meta.get('eta_settle')} rp={meta.get('rp_credit')} "
            f"({meta.get('reason')})"
        )
    if meta.get("unlock_city"):
        return (
            f"city_probe: unlock way={meta.get('alt_way_id')} "
            f"gap={meta.get('gap')} δ={meta.get('delta')} "
            f"eta={meta.get('eta_alt')}<{meta.get('eta_current')}"
        )
    if meta.get("s16"):
        return f"city_probe: S16 skip {meta.get('reason') or 'unknown'}"
    return f"city_probe: skip {meta.get('reason') or 'unknown'}"


# ── S16: mid-game low-risk settle vs city (not endgame-only / not VP≥4) ─────

LOW_RISK_LEVELS = frozenset({"low", "safe", ""})
CITY_RP_CREDIT = 2.0  # instant production / RP ETA credit for city-now
CITY_NEAR_TIE_TURNS = 1.25
ONE_TRADE_MISSING_MAX = 1  # cards short of city still "near" unlock


def is_low_risk_settle_target(direction: Mapping[str, Any]) -> Tuple[bool, str]:
    """S16/S17: low race risk on sticky/rec settle (not contested-critical)."""
    d = _as_mapping(direction)
    try:
        from core.execution_phase_manager import rec_target_risk_fields

        risk, race, role = rec_target_risk_fields(d)
    except Exception:
        pt = _as_mapping(d.get("project_target"))
        risk = str(pt.get("risk_level") or d.get("rec_risk_level") or "low").lower()
        race = str(pt.get("race_status") or d.get("rec_race_status") or "safe").lower()
        role = str(pt.get("portfolio_role") or "").lower()
    if race == "likely_lost" or risk in _HIGH_RISK:
        return False, f"high_pressure:risk={risk},race={race}"
    if race == "contested" and role in ("critical", "important"):
        return False, f"contested_critical:role={role}"
    if risk not in LOW_RISK_LEVELS and race not in ("safe", ""):
        return False, f"not_low_risk:risk={risk},race={race}"
    return True, "low_risk_safe"


def city_cards_missing(player: Any, game: Any = None) -> int:
    """How many resource cards short of a standard city cost (2Wh+3Ore)."""
    if player is None:
        return 99
    if player_can_afford_city(player, game):
        return 0
    need = {"Wheat": 2, "Ore": 3}
    try:
        from core.constants import ResourceCard, COSTS

        cost = COSTS.get("city") or COSTS.get("City") or {}
        if cost:
            need = {}
            for res, amt in cost.items():
                name = getattr(res, "value", res)
                need[str(name)] = int(amt or 0)
    except Exception:
        pass
    missing = 0
    rcards = getattr(player, "rcards", None) or {}
    if not isinstance(rcards, Mapping):
        rcards = {}
    for name, amt in need.items():
        have = 0
        if name in rcards:
            try:
                have = int(rcards.get(name) or 0)
            except Exception:
                have = 0
        else:
            for k, v in rcards.items():
                kn = getattr(k, "value", k)
                if str(kn) == name:
                    try:
                        have = int(v or 0)
                    except Exception:
                        have = 0
                    break
        missing += max(0, int(amt) - have)
    return int(missing)


def player_has_city_upgrade_site(player: Any) -> bool:
    try:
        settles = list(getattr(player, "settlements", None) or [])
        return len(settles) > 0
    except Exception:
        return False


def should_low_risk_city_support(
    game: Any,
    player: Any,
    direction: Any,
    scan: Any = None,
    *,
    s2a_already_unlocks_city: bool = False,
    s2b_already_unlocks_city: bool = False,
) -> Dict[str, Any]:
    """S16: when settle support is low-risk, always compare city RP; unlock if competitive.

    Does **not** wipe sticky settle — only unlocks city as support/AUTH option.
    Logs ``sticky_probe_city`` on player/game for Phase0 dig-in.
    """
    meta: Dict[str, Any] = {
        "unlock_city": False,
        "probed": False,
        "skipped": True,
        "reason": "",
        "s16": True,
        "eta_settle": None,
        "eta_city": None,
        "rp_credit": CITY_RP_CREDIT,
        "near_tie": CITY_NEAR_TIE_TURNS,
        "cards_missing": None,
        "city_legal": False,
        "city_affordable": False,
        "one_trade_away": False,
    }
    d = _as_mapping(direction)
    if not d:
        meta["reason"] = "no_direction"
        return meta
    if s2a_already_unlocks_city or s2b_already_unlocks_city:
        meta["reason"] = "already_unlocked"
        meta["skipped"] = True
        return meta

    if not is_expand_primary(d):
        support = str(d.get("supporting_action_type") or "").lower()
        if "settle" not in support and "road" not in support:
            meta["reason"] = "not_settle_or_expand_primary"
            return meta

    low, low_reason = is_low_risk_settle_target(d)
    meta["low_risk_reason"] = low_reason
    if not low:
        meta["reason"] = low_reason
        return meta

    if not player_has_city_upgrade_site(player):
        meta["reason"] = "no_settlement_to_upgrade"
        return meta

    legal = city_legal_in_scan(scan)
    affordable = player_can_afford_city(player, game)
    missing = city_cards_missing(player, game)
    one_trade = missing <= int(ONE_TRADE_MISSING_MAX)
    meta["city_legal"] = bool(legal)
    meta["city_affordable"] = bool(affordable)
    meta["cards_missing"] = int(missing)
    meta["one_trade_away"] = bool(one_trade)
    meta["probed"] = True

    if not legal and not affordable and not one_trade:
        meta["reason"] = "city_not_near_legal"
        _store_sticky_probe_city(player, game, meta)
        return meta

    audits = collect_cached_board_audits(game, player)
    eta_settle = current_way_eta(d, audits)
    meta["eta_settle"] = eta_settle
    if eta_settle >= HUGE_ETA_SKIP:
        meta["reason"] = f"settle_eta_huge:{eta_settle}"
        _store_sticky_probe_city(player, game, meta)
        return meta

    # City-now proxy: RP credit; one trade adds ~1 turn friction
    if affordable:
        eta_city = max(0.0, float(eta_settle) - float(CITY_RP_CREDIT))
    elif one_trade:
        eta_city = max(0.0, float(eta_settle) - float(CITY_RP_CREDIT) + 1.0)
    else:
        # Legal in scan but not near-affordable — weak compare
        eta_city = float(eta_settle)
    meta["eta_city"] = eta_city

    # Better or near-tie → unlock city support (sticky settle kept)
    near = float(CITY_NEAR_TIE_TURNS)
    competitive = eta_city + near < float(eta_settle) or (
        affordable and eta_city <= float(eta_settle)
    )
    # Always unlock when affordable on low-risk settle (instant RP available)
    if affordable and legal:
        competitive = True
    if competitive and (legal or affordable or one_trade):
        meta["unlock_city"] = True
        meta["skipped"] = False
        meta["reason"] = (
            f"s16_low_risk_city:eta_city={eta_city}+tie{near}"
            f"<=?eta_settle={eta_settle};miss={missing}"
        )
    else:
        meta["reason"] = (
            f"s16_city_not_competitive:eta_city={eta_city},eta_settle={eta_settle}"
        )

    _store_sticky_probe_city(player, game, meta)
    return meta


def _store_sticky_probe_city(player: Any, game: Any, meta: Mapping[str, Any]) -> None:
    payload = dict(meta)
    try:
        if player is not None:
            setattr(player, "sticky_probe_city", payload)
            setattr(player, "last_sticky_probe_city", payload)
    except Exception:
        pass
    try:
        if game is not None:
            setattr(game, "last_sticky_probe_city", payload)
            setattr(game, "sticky_probe_city", payload)
    except Exception:
        pass


def run_city_support_probes(
    game: Any,
    player: Any,
    direction: Any,
    scan: Any = None,
    *,
    s2a_already_unlocks_city: bool = False,
) -> Dict[str, Any]:
    """S2b then S16; combined meta for EPM unlock + dig-in."""
    s2b = should_opportunity_unlock_city(
        game,
        player,
        direction,
        scan,
        s2a_already_unlocks_city=s2a_already_unlocks_city,
    )
    if s2b.get("unlock_city"):
        s2b = dict(s2b)
        s2b["probe_source"] = "s2b"
        return s2b
    s16 = should_low_risk_city_support(
        game,
        player,
        direction,
        scan,
        s2a_already_unlocks_city=s2a_already_unlocks_city,
        s2b_already_unlocks_city=bool(s2b.get("unlock_city")),
    )
    if s16.get("unlock_city"):
        out = dict(s16)
        out["probe_source"] = "s16"
        out["s2b"] = dict(s2b)
        return out
    # Prefer richer skip reason: S16 probed low-risk path vs S2b skip
    if s16.get("probed"):
        out = dict(s16)
        out["probe_source"] = "s16"
        out["s2b"] = dict(s2b)
        return out
    out = dict(s2b)
    out["probe_source"] = "s2b"
    out["s16"] = dict(s16)
    return out
