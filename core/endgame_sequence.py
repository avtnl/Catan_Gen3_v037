"""S6: endgame city vs settle/road sequence pick (this turn only).

S6a — hard settlement-cap priority (no ETA math):
  when settlements >= 5, city legal+affordable, and the way needs cities → prefer city.

S6b — cheap win-ETA compare among C / S / R using cached ETA + credits + δ.
  Never re-solves the way portfolio (reuse S2b cache spirit).

Does not unlock AUTH (S2a/S2b). Only reorders BA / continue-plan priority when
the endgame gate fires and city wins (or hard-cap forces city).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.strategy_city_probe import (
    INFINITE_TURNS,
    city_legal_in_scan,
    collect_cached_board_audits,
    current_way_eta,
    player_can_afford_city,
)

# Plan §8 knobs
SETTLE_CAP_SOFT = 4
HARD_SETTLE_CAP = 5  # viable_action_scanner.DEFAULT_MAX_SETTLEMENTS
CITY_ETA_CREDIT = 2.0
SETTLE_ETA_CREDIT = 1.0
ROAD_ETA_CREDIT = 0.5
DELTA_ENDGAME = 1.25
HUGE_ETA_SKIP = 500.0

_HIGH_RISK = frozenset({"medium", "med", "high", "blocked"})

ACTION_CITY = "Build city"
ACTION_SETTLE = "Build settlement"
ACTION_ROAD = "Build road"

PICK_TO_ACTION = {
    "C": ACTION_CITY,
    "S": ACTION_SETTLE,
    "R": ACTION_ROAD,
    "Hold": "",
}


def _safe_float(value: Any, default: float = INFINITE_TURNS) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
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


def settlement_count(player: Any) -> int:
    """Number of settlement pieces currently on the board (not cities)."""
    return len(list(getattr(player, "settlements", None) or []))


def city_count(player: Any) -> int:
    return len(list(getattr(player, "cities", None) or []))


def structure_count(player: Any) -> int:
    return settlement_count(player) + city_count(player)


def _action_legal_in_scan(scan: Any, *name_bits: str) -> bool:
    if scan is None:
        return False
    bits = tuple(b.lower() for b in name_bits)
    flags = getattr(scan, "action_flags", None)
    if isinstance(flags, Mapping):
        for key, val in flags.items():
            if not val:
                continue
            k = str(key).lower()
            if all(b in k for b in bits):
                return True
    cands = getattr(scan, "candidates", None)
    if isinstance(cands, Mapping):
        for key, val in cands.items():
            k = str(key).lower()
            if all(b in k for b in bits) and val:
                return True
    try:
        viable = scan.viable_actions() if hasattr(scan, "viable_actions") else []
        for a in list(viable or []):
            text = str(a).lower()
            if all(b in text for b in bits):
                return True
    except Exception:
        pass
    return False


def settle_legal_in_scan(scan: Any) -> bool:
    return _action_legal_in_scan(scan, "build", "settlement") or _action_legal_in_scan(
        scan, "settlement"
    )


def road_legal_in_scan(scan: Any) -> bool:
    return _action_legal_in_scan(scan, "build", "road") or _action_legal_in_scan(scan, "road")


def roads_remaining(direction: Mapping[str, Any]) -> int:
    rem = _as_mapping(direction.get("remaining"))
    n = _safe_int(rem.get("roads"), -1)
    if n >= 0:
        return n
    for key in ("roads_to_build", "sticky_path_edges", "path_edges"):
        raw = direction.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, Mapping)):
            return len([x for x in raw if x not in (None, "", [], ())])
    return 0


def way_needs_new_settlements(direction: Mapping[str, Any]) -> bool:
    rem = _as_mapping(direction.get("remaining"))
    if _safe_float(rem.get("new_settlements"), 0.0) > 0:
        return True
    wr = _as_mapping(direction.get("way_requirements"))
    if _safe_float(wr.get("new_settlements"), 0.0) > 0:
        return True
    support = str(direction.get("supporting_action_type") or "").strip().lower()
    if support in {"new_settlement", "next_settlement", "build_settlement"}:
        return True
    return False


def _way_needs_cities(direction: Mapping[str, Any]) -> Tuple[bool, float]:
    try:
        from core.execution_phase_manager import way_needs_cities

        needs, _, n = way_needs_cities(direction)
        return bool(needs), float(n or 0.0)
    except Exception:
        rem = _as_mapping(direction.get("remaining"))
        n = _safe_float(rem.get("cities") or rem.get("city_upgrades"), 0.0)
        return n > 0, n


def _rec_risk_fields(direction: Mapping[str, Any]) -> Tuple[str, str, str]:
    try:
        from core.execution_phase_manager import rec_target_risk_fields

        return rec_target_risk_fields(direction)
    except Exception:
        pt = _as_mapping(direction.get("project_target"))
        risk = str(pt.get("risk_level") or "low").lower()
        race = str(pt.get("race_status") or "safe").lower()
        role = str(pt.get("portfolio_role") or "").lower()
        return risk, race, role


def is_forced_robber_state(game: Any) -> bool:
    state = str(getattr(game, "state", "") or "")
    if state in {"MoveRobber", "RobberMoveRequired", "SetRobber", "StealSelectOpponent"}:
        return True
    pending = getattr(game, "pending_seven_roll", None) or {}
    if isinstance(pending, Mapping) and pending.get("active"):
        return True
    return False


def should_run_endgame_city_settle(
    game: Any,
    player: Any,
    direction: Any,
    scan: Any = None,
    *,
    settle_cap_soft: int = SETTLE_CAP_SOFT,
    hard_cap: int = HARD_SETTLE_CAP,
) -> Dict[str, Any]:
    """Hard gate for S6. Does not decide the pick — only whether S6 may run."""
    meta: Dict[str, Any] = {
        "run": False,
        "reason": "",
        "settlements": 0,
        "cities": 0,
        "structures": 0,
        "needs_cities": False,
        "city_remaining": 0.0,
        "city_legal": False,
        "city_affordable": False,
        "hard_cap": int(hard_cap),
        "soft_cap": int(settle_cap_soft),
    }
    if player is None:
        meta["reason"] = "no_player"
        return meta
    if game is not None and is_forced_robber_state(game):
        meta["reason"] = "forced_robber"
        return meta

    d = _as_mapping(direction)
    n_s = settlement_count(player)
    n_c = city_count(player)
    meta["settlements"] = n_s
    meta["cities"] = n_c
    meta["structures"] = n_s + n_c

    needs_city, city_n = _way_needs_cities(d) if d else (False, 0.0)
    meta["needs_cities"] = needs_city
    meta["city_remaining"] = city_n

    city_legal = city_legal_in_scan(scan)
    city_affordable = player_can_afford_city(player, game)
    meta["city_legal"] = city_legal
    meta["city_affordable"] = city_affordable

    # Gate: soft endgame, hard settle cap, or way needs cities+expand
    soft = (n_s + n_c) >= int(settle_cap_soft)
    hard = n_s >= int(hard_cap)
    expand_open = way_needs_new_settlements(d) or roads_remaining(d) > 0
    way_fork = needs_city and expand_open

    if not (soft or hard or way_fork):
        meta["reason"] = (
            f"gate_early:settlements={n_s},cities={n_c},soft={settle_cap_soft}"
        )
        return meta

    # City must be a real option this turn for S6 to choose C;
    # still allow run for settle-cap demotion when city unavailable (meta only).
    if not city_legal and not hard:
        meta["reason"] = "city_not_legal_in_scan"
        return meta

    meta["run"] = True
    meta["reason"] = (
        f"gate_ok:soft={soft},hard={hard},way_fork={way_fork},"
        f"city_legal={city_legal},affordable={city_affordable}"
    )
    return meta


def score_endgame_sequences(
    *,
    eta_current: float,
    city_ok: bool,
    settle_ok: bool,
    road_ok: bool,
    needs_cities: bool,
    roads_left: int,
    settlements: int,
    hard_cap: int = HARD_SETTLE_CAP,
    city_credit: float = CITY_ETA_CREDIT,
    settle_credit: float = SETTLE_ETA_CREDIT,
    road_credit: float = ROAD_ETA_CREDIT,
) -> Dict[str, float]:
    """Return eta proxies for C/S/R (lower better). Illegal sequences → +inf."""
    scores: Dict[str, float] = {
        "C": INFINITE_TURNS,
        "S": INFINITE_TURNS,
        "R": INFINITE_TURNS,
    }
    if city_ok and needs_cities:
        scores["C"] = max(0.0, float(eta_current) - float(city_credit))

    if settle_ok and settlements < int(hard_cap):
        sc = float(settle_credit)
        if roads_left >= 2:
            sc = 0.0  # far settle: no ETA credit for settle-now
        scores["S"] = max(0.0, float(eta_current) - sc)

    if road_ok and roads_left > 0:
        scores["R"] = max(0.0, float(eta_current) - float(road_credit))

    return scores


def pick_endgame_immediate_action(
    game: Any,
    player: Any,
    direction: Any,
    scan: Any = None,
    *,
    settle_cap_soft: int = SETTLE_CAP_SOFT,
    hard_cap: int = HARD_SETTLE_CAP,
    city_credit: float = CITY_ETA_CREDIT,
    settle_credit: float = SETTLE_ETA_CREDIT,
    road_credit: float = ROAD_ETA_CREDIT,
    delta: float = DELTA_ENDGAME,
) -> Dict[str, Any]:
    """Choose this-turn action among C/S/R under S6a/S6b rules.

    Returns meta with ``pick`` in {C,S,R,Hold,None}, ``immediate_action``, mode.
    """
    meta: Dict[str, Any] = {
        "pick": None,
        "immediate_action": "",
        "skipped": True,
        "reason": "",
        "mode": None,
        "gate": False,
        "s6a": False,
        "s6b": False,
        "eta_current": None,
        "eta_city": None,
        "eta_settle": None,
        "eta_road": None,
        "delta": float(delta),
        "race_blocked": False,
    }

    gate = should_run_endgame_city_settle(
        game,
        player,
        direction,
        scan,
        settle_cap_soft=settle_cap_soft,
        hard_cap=hard_cap,
    )
    meta["gate_meta"] = dict(gate)
    meta["settlements"] = gate.get("settlements")
    meta["cities"] = gate.get("cities")
    if not gate.get("run"):
        meta["reason"] = str(gate.get("reason") or "gate_fail")
        return meta

    meta["gate"] = True
    d = _as_mapping(direction)
    n_s = int(gate.get("settlements") or 0)
    needs_cities = bool(gate.get("needs_cities"))
    city_legal = bool(gate.get("city_legal"))
    city_affordable = bool(gate.get("city_affordable"))
    city_ok = city_legal and city_affordable

    settle_ok = settle_legal_in_scan(scan) and n_s < int(hard_cap)
    road_ok = road_legal_in_scan(scan)
    roads_left = roads_remaining(d)

    # ── S6a: hard settle-cap free priority ─────────────────────────────
    if n_s >= int(hard_cap) and city_ok and needs_cities:
        meta["pick"] = "C"
        meta["immediate_action"] = ACTION_CITY
        meta["skipped"] = False
        meta["mode"] = "s6a_hard_cap"
        meta["s6a"] = True
        meta["reason"] = f"s6a_hard_cap:settlements={n_s}>={hard_cap},needs_cities"
        return meta

    if n_s >= int(hard_cap) and not needs_cities:
        meta["reason"] = "s6a_no_force:way_needs_0_cities"
        # Fall through — may still S6b only for expand demotion; without city need, skip
        meta["skipped"] = True
        return meta

    if not city_ok:
        meta["reason"] = (
            "city_not_actionable:"
            f"legal={city_legal},affordable={city_affordable}"
        )
        return meta

    if not needs_cities:
        meta["reason"] = "way_needs_0_cities"
        return meta

    # ── Race block: keep path progress under pressure ──────────────────
    risk, race, role = _rec_risk_fields(d)
    meta["rec_risk"] = risk
    meta["rec_race"] = race
    meta["rec_role"] = role
    high_race = risk in _HIGH_RISK or (
        race == "contested" and role in ("critical", "important")
    )
    if high_race:
        meta["race_blocked"] = True
        meta["reason"] = f"race_block:risk={risk},race={race},role={role}"
        # Prefer path if available
        if road_ok and roads_left > 0:
            meta["pick"] = "R"
            meta["immediate_action"] = ACTION_ROAD
            meta["skipped"] = False
            meta["mode"] = "s6_race_path"
            meta["s6b"] = True
            return meta
        if settle_ok:
            meta["pick"] = "S"
            meta["immediate_action"] = ACTION_SETTLE
            meta["skipped"] = False
            meta["mode"] = "s6_race_path"
            meta["s6b"] = True
            return meta
        return meta

    # ── S6b: cheap win-ETA sequence pick ───────────────────────────────
    audits = collect_cached_board_audits(game, player) if game is not None else []
    eta_cur = current_way_eta(d, audits) if d else INFINITE_TURNS
    if eta_cur >= HUGE_ETA_SKIP or eta_cur >= INFINITE_TURNS:
        # No usable ETA: at soft endgame still prefer city when way needs cities
        # and city is affordable (weaker than hard-cap but better than thrash).
        meta["eta_current"] = eta_cur
        if city_ok and needs_cities and n_s >= int(settle_cap_soft):
            meta["pick"] = "C"
            meta["immediate_action"] = ACTION_CITY
            meta["skipped"] = False
            meta["mode"] = "s6b_no_eta_soft_city"
            meta["s6b"] = True
            meta["reason"] = f"s6b_soft_city_no_eta:eta={eta_cur},settlements={n_s}"
            return meta
        meta["reason"] = f"eta_unusable:{eta_cur}"
        return meta

    scores = score_endgame_sequences(
        eta_current=eta_cur,
        city_ok=city_ok,
        settle_ok=settle_ok,
        road_ok=road_ok,
        needs_cities=needs_cities,
        roads_left=roads_left,
        settlements=n_s,
        hard_cap=hard_cap,
        city_credit=city_credit,
        settle_credit=settle_credit,
        road_credit=road_credit,
    )
    meta["eta_current"] = eta_cur
    meta["eta_city"] = scores["C"]
    meta["eta_settle"] = scores["S"]
    meta["eta_road"] = scores["R"]
    meta["s6b"] = True

    expand_etas = [
        scores[k] for k in ("S", "R") if scores[k] < INFINITE_TURNS
    ]
    best_expand = min(expand_etas) if expand_etas else INFINITE_TURNS
    eta_city = scores["C"]

    if eta_city >= INFINITE_TURNS:
        meta["reason"] = "city_sequence_illegal"
        return meta

    # City must beat expand by ≥ δ (when expand is legal)
    if best_expand < INFINITE_TURNS:
        if not (eta_city + float(delta) < best_expand):
            # Expand wins or gap too small
            best_pick = "R" if scores["R"] <= scores["S"] else "S"
            if scores[best_pick] >= INFINITE_TURNS:
                best_pick = "S" if scores["S"] < INFINITE_TURNS else "R"
            if scores.get(best_pick, INFINITE_TURNS) >= INFINITE_TURNS:
                meta["reason"] = (
                    f"no_city_delta:eta_city={eta_city}+δ{delta}>="
                    f"expand={best_expand}"
                )
                return meta
            meta["pick"] = best_pick
            meta["immediate_action"] = PICK_TO_ACTION.get(best_pick, "")
            meta["skipped"] = False
            meta["mode"] = "s6b_expand"
            meta["reason"] = (
                f"s6b_expand:{best_pick} eta={scores[best_pick]} "
                f"city={eta_city}+δ{delta} not better"
            )
            return meta

    # City wins (no expand, or beats expand by δ)
    meta["pick"] = "C"
    meta["immediate_action"] = ACTION_CITY
    meta["skipped"] = False
    meta["mode"] = "s6b_eta"
    meta["reason"] = (
        f"s6b_city:eta_city={eta_city}+δ{delta}<expand={best_expand},"
        f"eta_cur={eta_cur}"
    )
    return meta


def format_endgame_sequence_dbg(meta: Mapping[str, Any]) -> str:
    """One-line DBG / R7-style summary."""
    if not meta:
        return "endgame: n/a"
    if meta.get("skipped") and not meta.get("pick"):
        return f"endgame: skip {meta.get('reason') or 'unknown'}"
    pick = meta.get("pick") or "?"
    act = meta.get("immediate_action") or ""
    mode = meta.get("mode") or ""
    bits = [f"endgame: {pick}"]
    if act:
        bits.append(act)
    if mode:
        bits.append(f"mode={mode}")
    if meta.get("eta_city") is not None:
        bits.append(
            f"ηc={meta.get('eta_city')}/ηs={meta.get('eta_settle')}/ηr={meta.get('eta_road')}"
        )
    if meta.get("reason"):
        bits.append(str(meta.get("reason"))[:80])
    return " ".join(bits)


def apply_endgame_action_priority(
    base_priority: Mapping[str, int],
    endgame_meta: Mapping[str, Any],
) -> Dict[str, int]:
    """Return a copy of action_priority with S6 pick boosted to rank 0.

    Only elevates the chosen immediate action; does not demote others when S6
    skips (callers keep road-first sticky defaults).
    """
    out = {str(k): int(v) for k, v in dict(base_priority or {}).items()}
    if not endgame_meta or endgame_meta.get("skipped"):
        return out
    action = str(endgame_meta.get("immediate_action") or "")
    if not action:
        return out
    # Boost pick to top; shift others that were better or equal
    out[action] = 0
    # Cap thrash: at hard settle cap, never prefer settlement
    if endgame_meta.get("s6a") or (
        int(endgame_meta.get("settlements") or 0) >= HARD_SETTLE_CAP
    ):
        if ACTION_SETTLE in out:
            out[ACTION_SETTLE] = max(out.get(ACTION_SETTLE, 99), 10)
    return out
