"""Observe-only Sidestep v2 vs live PLN2 compare (does not replace ETA).

Cadence: R1 + every 4th round (R4/R8/R12/…) for the **player at turn only**.
Side = v2 walk + optional EH confidence gate; Dist/Rk/Δt from PLN2 race risk.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.sidestep_eta_matrix import (
    phase_start_horizon,
    residual_trcards_v2_detail,
    side_with_confidence,
)

# Dig cadence ≈ opt-in schedule ``EXPLICIT_142_RECALC_SCHEDULE_SETBACK_EVERY4``
# code-4 grid **plus R1 baseline**: own turns 1,4,8,12,… ≈ R1/R4/R8/R12/…
# (R1 is dig-only; code 4 alone would skip turn 1. Code 2 setback not mirrored.)
# Product L2 default is now [0] (a/b/c only); Sidestep dig still uses every-4.
# Sidestep runs for the **seat to move only** (never a 4-seat matrix fan-out).

SIDESTEP_EVERY_N_OWN_TURNS: int = 4  # matches schedule [4, 4]
SIDESTEP_INCLUDE_OWN_TURN_1: bool = True  # R1 baseline → R1/R4/R8/R12/…

CHECKPOINT_PHASE = {
    "exec_start": "early",  # legacy alias
    "r8_start": "mid",
    "r16_start": "late",
}

CHECKPOINT_LABEL = {
    "exec_start": "Execution start (legacy R1)",
    "r8_start": "Round 8 (legacy)",
    "r16_start": "Round 16 (legacy)",
}


def sidestep_every_n_own_turns() -> int:
    try:
        from core.explicit_142_recalc import (
            EXPLICIT_142_RECALC_SCHEDULE_SETBACK_EVERY4,
            every_n_periods,
            normalize_explicit_142_recalc,
        )

        periods = every_n_periods(
            normalize_explicit_142_recalc(EXPLICIT_142_RECALC_SCHEDULE_SETBACK_EVERY4)
        )
        if periods:
            return max(1, int(periods[0]))
    except Exception:
        pass
    return max(1, int(SIDESTEP_EVERY_N_OWN_TURNS))


def is_sidestep_cadence_round(round_no: int) -> bool:
    """Approx calendar: R1/R4/R8/R12/… Prefer own_turn_count gate."""
    try:
        rnd = int(round_no)
    except Exception:
        return False
    if rnd <= 0:
        return False
    if rnd == 1 and SIDESTEP_INCLUDE_OWN_TURN_1:
        return True
    n = sidestep_every_n_own_turns()
    return rnd % n == 0


def phase_for_round(round_no: int) -> str:
    """Map round → Sidestep start-H phase band."""
    try:
        rnd = int(round_no)
    except Exception:
        return "mid"
    if rnd <= 4:
        return "early"
    if rnd <= 12:
        return "mid"
    return "end"  # dig label; horizon uses late via phase_h


def checkpoint_for_round(round_no: int) -> Optional[str]:
    if not is_sidestep_cadence_round(round_no):
        return None
    rnd = int(round_no)
    if rnd == 1:
        return "exec_start"
    return f"r{rnd}_own"


def _own_turn_count(game: Any, player: Any) -> int:
    """Own Execution turns so far this game (after ``note_own_execution_turn``).

    Prefers explicit_142 runtime (treatment seats). Otherwise maintains a
    Sidestep-local counter so human/[0] seats still follow the [4,4] grid.
    """
    if player is None:
        return 0
    try:
        from core.strategy_explicit_recalc import (
            ensure_runtime,
            is_treatment_seat,
        )

        if is_treatment_seat(player):
            rt = ensure_runtime(player)
            return max(0, int(rt.get("own_turn_count") or 0))
    except Exception:
        pass
    try:
        key = (
            _safe_int(getattr(game, "round", None), 0),
            _safe_int(getattr(game, "turn", None), 0),
            _safe_int(getattr(player, "id", None), 0),
        )
        last = getattr(player, "_sidestep_last_turn_key", None)
        count = int(getattr(player, "_sidestep_own_turn_count", 0) or 0)
        if last != key:
            count += 1
            setattr(player, "_sidestep_own_turn_count", count)
            setattr(player, "_sidestep_last_turn_key", key)
        return count
    except Exception:
        return 0


def is_sidestep_own_turn_cadence(game: Any, player: Any) -> bool:
    """True on own turn 1 (optional) or multiples of PRODUCT_AI [4, 4] period."""
    n = sidestep_every_n_own_turns()
    count = _own_turn_count(game, player)
    if count <= 0:
        return False
    if count == 1 and SIDESTEP_INCLUDE_OWN_TURN_1:
        return True
    return count % n == 0


def checkpoint_for_own_turn(game: Any, player: Any) -> Optional[str]:
    if not is_sidestep_own_turn_cadence(game, player):
        return None
    count = _own_turn_count(game, player)
    try:
        rnd = int(getattr(game, "round", 0) or 0)
    except Exception:
        rnd = 0
    if count == 1:
        return "exec_start"
    return f"own{count}_r{rnd}"


def _turn_player(game: Any) -> Any:
    try:
        getter = getattr(game, "get_current_player", None)
        if callable(getter):
            p = getter()
            if p is not None:
                return p
    except Exception:
        pass
    try:
        return getattr(game, "current_player", None)
    except Exception:
        return None

RES_LABELS = ("W", "O", "Wd", "B", "Sh")


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "—"


def _fmt_vec5(v: Any) -> str:
    try:
        arr = [float(x) for x in list(v)[:5]]
        while len(arr) < 5:
            arr.append(0.0)
        return (
            "["
            + ",".join(
                f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}" for x in arr
            )
            + "]"
        )
    except Exception:
        return "[?,?,?,?,?]"


def _risk_letter(risk: Any) -> str:
    s = str(risk or "").strip().lower()
    if s in ("med", "medium", "m"):
        return "M"
    if s in ("high", "h", "crit"):
        return "H"
    if s in ("blocked", "b"):
        return "B"
    return "—"


def resolve_checkpoint(game: Any) -> Optional[str]:
    """Legacy R-cadence retired — S142 uses a/b/c triggers (``sidestep_s142_drive``).

    Returns None unless ``SIDESTEP_COMPARE`` explicitly re-enables dig cadence.
    """
    try:
        from core.constants import SIDESTEP_COMPARE

        if not SIDESTEP_COMPARE:
            return None
    except Exception:
        return None
    try:
        if str(getattr(game, "phase", "") or "") != "Execution":
            return None
    except Exception:
        return None
    player = _turn_player(game)
    if player is None:
        return None
    return checkpoint_for_own_turn(game, player)


def _fired_set(game: Any) -> set:
    s = getattr(game, "_sidestep_compare_fired", None)
    if not isinstance(s, set):
        s = set()
        try:
            game._sidestep_compare_fired = s
        except Exception:
            pass
    return s


def _fire_key(checkpoint: str, player: Any) -> str:
    pid = _safe_int(getattr(player, "id", None), 0) or 0
    return f"{checkpoint}:P{pid}"


def _preferred_for(player: Any) -> Dict[str, Any]:
    raw = getattr(player, "strategic_direction", None)
    return dict(raw) if isinstance(raw, Mapping) else {}


def _way_id_for(player: Any, preferred: Mapping[str, Any]) -> Optional[int]:
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        if isinstance(c, Mapping):
            wid = _safe_int(c.get("locked_way_id"))
            if wid and wid > 0:
                return wid
    except Exception:
        pass
    wid = _safe_int(preferred.get("preferred_way_id") or preferred.get("way_id"))
    if wid and wid > 0:
        return wid
    return None


def seats_missing_way_id(game: Any) -> List[Any]:
    missing: List[Any] = []
    for player in list(getattr(game, "players", []) or []):
        if _way_id_for(player, _preferred_for(player)) is None:
            missing.append(player)
    return missing


def bootstrap_seat_strategies_for_compare(
    game: Any,
    *,
    reason: str = "sidestep_compare_exec_start_bootstrap",
    only_missing: bool = True,
    players: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    bag: Dict[str, Any] = {
        "ok": True,
        "reason": reason,
        "refreshed": [],
        "errors": [],
        "skipped": False,
    }
    pool = list(players) if players is not None else list(getattr(game, "players", []) or [])
    if not pool:
        bag["ok"] = False
        bag["errors"].append("no_players")
        return bag
    if only_missing:
        targets = [
            p
            for p in pool
            if _way_id_for(p, _preferred_for(p)) is None
        ]
    else:
        targets = pool
    if not targets:
        bag["skipped"] = True
        bag["reason"] = "seat_has_way" if players is not None else "all_seats_have_way"
        return bag
    saved_turn = getattr(game, "turn", None)
    saved_state = getattr(game, "state", None)
    saved_current = getattr(game, "current_player", None)
    refresh = getattr(game, "refresh_strategy_context", None)
    if not callable(refresh):
        bag["ok"] = False
        bag["errors"].append("no_refresh_strategy_context")
        return bag
    try:
        for player in targets:
            pid = _safe_int(getattr(player, "id", None))
            if pid is None:
                continue
            try:
                game.turn = int(pid)
                game.get_current_player()
                status = refresh(
                    reason,
                    force=True,
                    mode="explore",
                    allow_during_forced_flow=True,
                )
                wid = None
                if isinstance(status, Mapping):
                    wid = status.get("preferred_way_id")
                if wid is None:
                    wid = _way_id_for(player, _preferred_for(player))
                bag["refreshed"].append(
                    {
                        "player_id": pid,
                        "preferred_way_id": wid,
                        "ok": bool(isinstance(status, Mapping) and status.get("ok")),
                    }
                )
            except Exception as exc:
                bag["errors"].append(f"P{pid}:{exc}")
                bag["ok"] = False
    finally:
        try:
            if saved_turn is not None:
                game.turn = saved_turn
            if saved_state is not None:
                game.state = saved_state
            if saved_current is not None:
                game.current_player = saved_current
            elif hasattr(game, "get_current_player"):
                game.get_current_player()
        except Exception:
            pass
    if bag["errors"]:
        bag["ok"] = False
    return bag


def _board_inventory(player: Any) -> Dict[str, int]:
    from core.strategy_way_residual import dcard_summary_rows, settlement_city_counts

    n_s, n_c = settlement_city_counts(player)
    try:
        n_r = len(list(getattr(player, "roads", []) or []))
    except Exception:
        n_r = 0
    dc_hand = 0
    dc_played = 0
    for row in dcard_summary_rows(player):
        dc_hand += max(0, int(row[1] or 0)) + max(0, int(row[2] or 0))
        dc_played += max(0, int(row[3] or 0))
    return {
        "board_S": int(n_s),
        "board_C": int(n_c),
        "board_R": int(n_r),
        "dc_hand": int(dc_hand),
        "dc_played": int(dc_played),
        "dc_ever": int(dc_hand + dc_played),
    }


def _comp_rem_for_way(
    way_id: Optional[int],
    player: Any,
    preferred: Mapping[str, Any],
    board: Any,
) -> Dict[str, int]:
    try:
        from core.strategy_way_residual import compute_way_residual

        res = compute_way_residual(way_id, player, preferred=preferred, board=board)
        return {
            "new_settlements": max(0, int(res.get("req_settles") or 0)),
            "city_upgrades": max(0, int(res.get("req_cities") or 0)),
            "roads": max(0, int(res.get("req_roads") or 0)),
            "dev_cards": max(0, int(res.get("req_dcards") or 0)),
        }
    except Exception:
        return {
            "new_settlements": 0,
            "city_upgrades": 0,
            "roads": 0,
            "dev_cards": 0,
        }


def _adjust_rem_for_target(rem0: Mapping[str, int], kind: str) -> Dict[str, int]:
    rem = {
        "new_settlements": max(0, int(rem0.get("new_settlements") or 0)),
        "city_upgrades": max(0, int(rem0.get("city_upgrades") or 0)),
        "roads": max(0, int(rem0.get("roads") or 0)),
        "dev_cards": max(0, int(rem0.get("dev_cards") or 0)),
    }
    if str(kind or "S").upper() == "C":
        rem["city_upgrades"] = max(0, rem["city_upgrades"] - 1)
    else:
        rem["new_settlements"] = max(0, rem["new_settlements"] - 1)
    return rem


def _rp_tr_after_target(
    board: Any,
    player: Any,
    *,
    kind: str,
    tid: int,
) -> Tuple[List[float], List[float], List[float], List[float]]:
    from core.resource_time_estimator import (
        get_intersection_resource_pips,
        get_player_production_pips,
        get_player_trade_rates,
        trade_rates_after_candidate,
    )

    base = [float(x) for x in get_player_production_pips(board, player)[:5]]
    while len(base) < 5:
        base.append(0.0)
    gain = [float(x) for x in get_intersection_resource_pips(board, int(tid))[:5]]
    while len(gain) < 5:
        gain.append(0.0)
    rp = [base[i] + gain[i] for i in range(5)]
    if str(kind or "S").upper() == "C":
        rates = [float(x) for x in get_player_trade_rates(board, player)[:5]]
    else:
        rates = [
            float(x) for x in trade_rates_after_candidate(board, player, int(tid))[:5]
        ]
    while len(rates) < 5:
        rates.append(4.0)
    return rp, rates, gain, base


def _require_confidence() -> bool:
    try:
        from core.constants import SIDESTEP_REQUIRE_CONFIDENCE

        return bool(SIDESTEP_REQUIRE_CONFIDENCE)
    except Exception:
        return True


def _normalize_stage_label(label: Any) -> str:
    """Map Sidestep late → end so dig matches live SE early/mid/end."""
    s = str(label or "").strip().lower()
    if s in ("late", "endgame", "ending"):
        return "end"
    if s in ("early", "mid", "end"):
        return s
    return s or "mid"


def _seat_vp(game: Any, player: Any) -> int:
    try:
        from core.ai_dcard_timing import victory_points

        return max(0, int(victory_points(game, player) or 0))
    except Exception:
        pass
    try:
        return max(0, int(getattr(player, "victory_points", 0) or 0))
    except Exception:
        return 0


def live_stage_bundle(game: Any, player: Any) -> Dict[str, Any]:
    """Capture before-Sidestep stage / way-cap (portfolio grows mid→end).

    Live L2 uses **max VP among seats** for ``game_stage_label`` / top_n
    (3 / 6 / 9). Per-seat VP stage is also logged — at the same round one
    color can still look early while another is mid.
    """
    out: Dict[str, Any] = {
        "live_stage": "early",
        "live_top_n": 3,
        "seat_stage": "early",
        "seat_vp": 0,
        "max_vp": 0,
    }
    try:
        from core.strategy_reconsider import (
            GAME_STAGE_EARLY_MAX_VP,
            GAME_STAGE_MID_MAX_VP,
            game_stage_label,
            max_vp_among_players,
            portfolio_top_n_for_game,
        )

        out["live_stage"] = _normalize_stage_label(game_stage_label(game))
        out["live_top_n"] = int(portfolio_top_n_for_game(game))
        out["max_vp"] = int(max_vp_among_players(game))
        early_max = int(GAME_STAGE_EARLY_MAX_VP)
        mid_max = int(GAME_STAGE_MID_MAX_VP)
    except Exception:
        early_max, mid_max = 3, 6
        try:
            from core.strategy_reconsider import game_stage_label, portfolio_top_n_for_game

            out["live_stage"] = _normalize_stage_label(game_stage_label(game))
            out["live_top_n"] = int(portfolio_top_n_for_game(game))
        except Exception:
            pass
    seat_vp = _seat_vp(game, player)
    out["seat_vp"] = seat_vp
    if seat_vp <= early_max:
        out["seat_stage"] = "early"
    elif seat_vp <= mid_max:
        out["seat_stage"] = "mid"
    else:
        out["seat_stage"] = "end"
    return out


def build_seat_compare(
    game: Any,
    player: Any,
    *,
    checkpoint: str,
    phase: Optional[str] = None,
) -> Dict[str, Any]:
    preferred = _preferred_for(player)
    board = getattr(game, "board", None)
    way_id = _way_id_for(player, preferred)
    raw_phase = str(
        phase
        or CHECKPOINT_PHASE.get(checkpoint)
        or phase_for_round(int(getattr(game, "round", 0) or 0))
        or "mid"
    )
    # Dig report vocab = early|mid|end (live SE). Horizon keys = early|mid|late.
    stage_phase = _normalize_stage_label(raw_phase)
    phase_h = "late" if stage_phase == "end" else stage_phase
    inv = _board_inventory(player)
    require_conf = _require_confidence()
    live_meta = live_stage_bundle(game, player)
    t_live = t_side = t_sync = 0.0

    bag: Dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        from core.strategy_plan_snapshot import build_plan_snapshot

        bag = build_plan_snapshot(
            game,
            player,
            preferred,
            reason=f"sidestep_compare_{checkpoint}",
            refresh_mode="explore",
            force=True,
        )
    except Exception as exc:
        bag = {"ok": False, "error": str(exc), "catalog_all": []}
    t_live = time.perf_counter() - t0

    catalog = list(bag.get("catalog_all") or bag.get("catalog") or [])
    se_pick = str(bag.get("se_pick") or "") or ""
    plan_why = str(bag.get("plan_why") or "") or ""

    out: Dict[str, Any] = {
        "player_id": getattr(player, "id", None),
        "color": getattr(player, "color", None),
        "way_id": way_id,
        "checkpoint": checkpoint,
        "phase": stage_phase,
        "phase_h": phase_h,
        "start_h": phase_start_horizon(phase_h),
        "sidestep": "v2",
        "se_pick": se_pick,
        "plan_why": plan_why,
        "inventory": inv,
        "live_stage": live_meta.get("live_stage"),
        "live_top_n": live_meta.get("live_top_n"),
        "seat_stage": live_meta.get("seat_stage"),
        "seat_vp": live_meta.get("seat_vp"),
        "max_vp": live_meta.get("max_vp"),
        "rows": [],
        "ok": True,
        "error": None,
        "timing_parts": {
            "live_pln2_eta_s": round(t_live, 4),
            "sidestep_side_s": 0.0,
            "sidestep_sync_s142_s": 0.0,
        },
    }
    if not catalog:
        out["ok"] = False
        out["error"] = "empty_pln2_catalog"
        return out

    # Sidestep-owned full board↔142 sync + S142 (does not mutate live SE).
    sync_bundle: Dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        from core.sidestep_board_sync import build_seat_sync_and_s142

        sync_bundle = build_seat_sync_and_s142(
            game,
            player,
            sticky_way_id=way_id,
            catalog=catalog,
            phase=phase_h,
            require_confidence=require_conf,
        )
    except Exception as exc:
        sync_bundle = {"ok": False, "error": str(exc)}
    t_sync = time.perf_counter() - t0
    out["board_sync"] = sync_bundle
    sticky_sync = (
        sync_bundle.get("sticky_sync")
        if isinstance(sync_bundle.get("sticky_sync"), Mapping)
        else {}
    )
    s142 = (
        sync_bundle.get("s142") if isinstance(sync_bundle.get("s142"), Mapping) else {}
    )
    out["sticky_sync_label"] = sticky_sync.get("label")
    out["sticky_sync_reasons"] = list(sticky_sync.get("reasons") or [])
    out["fit_ways"] = int(sync_bundle.get("n_fit") or 0)
    out["fit_ways_total"] = int(sync_bundle.get("n_total") or 0)
    out["s142_way_id"] = s142.get("s142_way_id")
    out["s142_side"] = s142.get("s142_side")
    out["s142_target"] = s142.get("s142_target")
    out["s142_giveup_carve_out"] = bool(s142.get("giveup_carve_out"))

    rem0 = _comp_rem_for_way(way_id, player, preferred, board)
    rows: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    for r in catalog:
        kind = str(r.get("kind") or "S").upper()
        tid = _safe_int(r.get("id"), 0) or 0
        lab = str(r.get("label") or (f"C{tid}" if kind == "C" else f"S{tid}"))
        is_se = bool(se_pick and lab == se_pick)
        rem = _adjust_rem_for_target(rem0, kind)
        detail = residual_trcards_v2_detail(rem)
        need = [float(x) for x in detail["residual"]]

        rp = [0.0] * 5
        tr = [4.0] * 5
        gain = [0.0] * 5
        base_rp = [0.0] * 5
        if board is not None and tid > 0:
            try:
                rp, tr, gain, base_rp = _rp_tr_after_target(
                    board, player, kind=kind, tid=tid
                )
            except Exception:
                pass

        side_bag = side_with_confidence(
            need,
            rp,
            tr,
            phase=phase_h,
            require_confidence=require_conf,
        )
        rows.append(
            {
                "new": lab,
                "target": _safe_float(r.get("target") or r.get("eta")),
                "eta": _safe_float(r.get("eta_win")),
                "side": side_bag.get("side"),
                "side_raw": side_bag.get("side_raw"),
                "confidence": side_bag.get("confidence"),
                "dist": r.get("dist") if kind != "C" else None,
                "risk": r.get("risk") if kind != "C" else None,
                "delta_t": r.get("delta_t") if kind != "C" else None,
                "why": plan_why if is_se else "",
                "se_pick": is_se,
                "kind": kind,
                "id": tid,
                "abs_trcards": need,
                "sub_trcards": [float(x) for x in detail["structure"]],
                "rem_trcards": need,
                "dc_cost": [float(x) for x in detail["dc_cost"]],
                "done_S": rem.get("new_settlements"),
                "done_C": rem.get("city_upgrades"),
                "done_R": rem.get("roads"),
                "done_DC": rem.get("dev_cards"),
                "rem_label": (
                    f"S{rem.get('new_settlements')}C{rem.get('city_upgrades')}"
                    f"R{rem.get('roads')}D{rem.get('dev_cards')}"
                ),
                "rp_after": rp,
                "rp_gain": gain,
                "rp_now": base_rp,
                "board_S": inv["board_S"],
                "board_C": inv["board_C"],
                "board_R": inv["board_R"],
                "dc_hand": inv["dc_hand"],
                "dc_played": inv["dc_played"],
                "residual_way_id": way_id,
            }
        )
    t_side = time.perf_counter() - t0
    out["rows"] = rows
    out["timing_parts"] = {
        "live_pln2_eta_s": round(t_live, 4),
        "sidestep_side_s": round(t_side, 4),
        "sidestep_sync_s142_s": round(t_sync, 4),
        "sidestep_total_s": round(t_side + t_sync, 4),
    }
    if way_id is None:
        out["ok"] = False
        out["error"] = "no_sticky_way_id"
    return out


def format_pln2_compare_table(seat: Mapping[str, Any]) -> str:
    pid = seat.get("player_id")
    color = seat.get("color") or ""
    wid = seat.get("way_id")
    raw_cp = str(seat.get("checkpoint") or "")
    cp = CHECKPOINT_LABEL.get(raw_cp)
    if not cp:
        if raw_cp.startswith("own") and "_r" in raw_cp:
            # own{N}_r{R}
            try:
                left, right = raw_cp.split("_r", 1)
                own_n = left.replace("own", "")
                cp = f"Own turn {own_n} (R{right}, turn player)"
            except Exception:
                cp = raw_cp
        elif raw_cp.startswith("r") and raw_cp.endswith("_own"):
            cp = f"Round {raw_cp[1:-4]} (turn player)"
        else:
            cp = raw_cp
    phase = seat.get("phase")
    inv = seat.get("inventory") if isinstance(seat.get("inventory"), Mapping) else {}
    sync_lab = seat.get("sticky_sync_label") or "?"
    sync_reasons = seat.get("sticky_sync_reasons") or []
    reason_s = ",".join(str(x) for x in sync_reasons[:4]) if sync_reasons else ""
    s142_wid = seat.get("s142_way_id")
    s142_side = seat.get("s142_side")
    s142_tgt = seat.get("s142_target") or "—"
    carve = " carve" if seat.get("s142_giveup_carve_out") else ""
    fit_n = seat.get("fit_ways", "?")
    fit_tot = seat.get("fit_ways_total", "?")
    live_stage = seat.get("live_stage") or "?"
    live_top_n = seat.get("live_top_n")
    seat_stage = seat.get("seat_stage") or "?"
    seat_vp = seat.get("seat_vp")
    max_vp = seat.get("max_vp")
    lines = [
        f"=== Sidestep v2 compare | {cp} | P{pid} {color} | sticky_way={wid} | "
        f"phase={phase} start_H={seat.get('start_h')} ===",
        (
            f"board: S={inv.get('board_S', '?')} C={inv.get('board_C', '?')} "
            f"R={inv.get('board_R', '?')} | "
            f"DCards hand={inv.get('dc_hand', '?')} played={inv.get('dc_played', '?')} | "
            f"RemTR order {list(RES_LABELS)} | DC unit [1,1,0,0,1]"
        ),
        (
            f"before_SE: live_stage={live_stage} top_n={live_top_n} maxVP={max_vp} | "
            f"seat_stage={seat_stage} seatVP={seat_vp} "
            f"(L2 portfolio ways early=3→mid=6→end=9)"
        ),
        (
            f"board_sync: sticky={sync_lab}"
            + (f" ({reason_s})" if reason_s else "")
            + f" | fit_ways={fit_n}/{fit_tot}{carve} | "
            f"S142={s142_wid if s142_wid is not None else '—'} "
            f"Side={_fmt(s142_side) if s142_side is not None else '—'} "
            f"via {s142_tgt}"
        ),
        (
            f"{'New':<6} {'Tgt':>5} {'ETA':>5} {'Side':>5} {'Raw':>5} {'Conf':>5} "
            f"{'Dist':>4} {'Rk':>2} {'Δt':>5} "
            f"{'RemTR':<18} {'remSCRDC':<11}  Why"
        ),
        "-" * 120,
    ]
    for r in list(seat.get("rows") or []):
        new = str(r.get("new") or "")
        if r.get("se_pick"):
            new = f"{new}*"
        dist = r.get("dist")
        dist_s = str(dist) if dist is not None else "—"
        risk = _risk_letter(r.get("risk"))
        dt = r.get("delta_t")
        dt_s = _fmt(dt) if dt is not None else "—"
        conf = r.get("confidence")
        conf_s = f"{float(conf):.2f}" if conf is not None else "—"
        rem_s = (
            _fmt_vec5(r.get("rem_trcards"))
            if r.get("rem_trcards") is not None
            else "—"
        )
        rem_lab = str(r.get("rem_label") or "—")
        lines.append(
            f"{new:<6} {_fmt(r.get('target')):>5} {_fmt(r.get('eta')):>5} "
            f"{_fmt(r.get('side')):>5} {_fmt(r.get('side_raw')):>5} {conf_s:>5} "
            f"{dist_s:>4} {risk:>2} {dt_s:>5} "
            f"{rem_s:<18} {rem_lab:<11}  {r.get('why') or ''}"
        )
    if seat.get("error"):
        lines.append(f"(note: {seat.get('error')})")
    lines.append(
        "Side=v2 walk; RP conf factor from Raw H rolls "
        "(full mid 8.5→9.25 at ~10 rolls, →1.0 by ~60 rolls). "
        "Raw=unscaled; Conf=info. RemTR=structure+DC×[1,1,0,0,1]. "
        "board_sync/S142=Sidestep-only full can_realize_way filter "
        "(live L2/sticky untouched); S142=min Side over fit ways × PLN2 tgts."
    )
    return "\n".join(lines)


def emit_compare_bundle(bundle: Mapping[str, Any]) -> None:
    text_blocks = list(bundle.get("tables") or [])
    blob = "\n\n".join(text_blocks)
    if not blob:
        return
    print(blob)
    try:
        from core.constants import FILENAME_HELP

        path = f"{FILENAME_HELP}_SidestepCompare.txt"
        with open(path, "a", encoding="utf-8") as f:
            f.write(blob)
            f.write("\n\n")
    except Exception:
        pass


def run_sidestep_compare(game: Any, checkpoint: str) -> Dict[str, Any]:
    """Observe-only Sidestep for the **player at turn** only."""
    t0 = time.perf_counter()
    try:
        rnd = int(getattr(game, "round", 0) or 0)
    except Exception:
        rnd = 0
    phase = CHECKPOINT_PHASE.get(checkpoint) or phase_for_round(rnd)
    player = _turn_player(game)
    bootstrap = None
    t_boot = 0.0
    # Bootstrap only the turn seat if sticky/preferred way is still missing.
    if player is not None and _way_id_for(player, _preferred_for(player)) is None:
        try:
            tb0 = time.perf_counter()
            bootstrap = bootstrap_seat_strategies_for_compare(
                game,
                players=[player],
                reason=f"sidestep_compare_{checkpoint}_bootstrap",
            )
            t_boot = time.perf_counter() - tb0
        except Exception as exc:
            bootstrap = {"ok": False, "errors": [str(exc)]}
            print(f"sidestep_compare bootstrap failed: {exc}")

    seats: List[Dict[str, Any]] = []
    tables: List[str] = []
    if player is None:
        seat = {
            "player_id": None,
            "color": None,
            "way_id": None,
            "checkpoint": checkpoint,
            "phase": phase,
            "rows": [],
            "inventory": {},
            "ok": False,
            "error": "no_turn_player",
            "sidestep": "v2",
        }
        seats.append(seat)
        tables.append(format_pln2_compare_table(seat))
    else:
        try:
            seat = build_seat_compare(
                game, player, checkpoint=checkpoint, phase=phase
            )
        except Exception as exc:
            seat = {
                "player_id": getattr(player, "id", None),
                "color": getattr(player, "color", None),
                "way_id": None,
                "checkpoint": checkpoint,
                "phase": phase,
                "rows": [],
                "inventory": {},
                "ok": False,
                "error": str(exc),
                "sidestep": "v2",
            }
        seats.append(seat)
        tables.append(format_pln2_compare_table(seat))

    elapsed = time.perf_counter() - t0
    live_s = side_s = sync_s = 0.0
    for s in seats:
        parts = s.get("timing_parts") if isinstance(s.get("timing_parts"), Mapping) else {}
        live_s += float(parts.get("live_pln2_eta_s") or 0)
        side_s += float(parts.get("sidestep_side_s") or 0)
        sync_s += float(parts.get("sidestep_sync_s142_s") or 0)
    timing = {
        "elapsed_s": round(elapsed, 3),
        "bootstrap_s": round(t_boot, 3),
        "compare_s": round(elapsed - t_boot, 3),
        "live_pln2_eta_s": round(live_s, 4),
        "sidestep_side_s": round(side_s, 4),
        "sidestep_sync_s142_s": round(sync_s, 4),
        "sidestep_only_s": round(side_s + sync_s, 4),
        "n_seats": len(seats),
        "n_rows": sum(len(s.get("rows") or []) for s in seats),
        "turn_player_id": getattr(player, "id", None) if player is not None else None,
    }
    timing_line = (
        f"[sidestep_timing] {checkpoint} total={timing['elapsed_s']:.3f}s "
        f"bootstrap={timing['bootstrap_s']:.3f}s "
        f"before_live_ETA={timing['live_pln2_eta_s']:.3f}s "
        f"sidestep_Side={timing['sidestep_side_s']:.3f}s "
        f"sidestep_S142={timing['sidestep_sync_s142_s']:.3f}s "
        f"sidestep_only={timing['sidestep_only_s']:.3f}s "
        f"seats={timing['n_seats']} rows={timing['n_rows']} "
        f"turn_P={timing['turn_player_id']}"
    )
    print(timing_line)
    tables = [timing_line, *tables]

    bundle = {
        "checkpoint": checkpoint,
        "label": CHECKPOINT_LABEL.get(checkpoint, checkpoint),
        "phase": phase,
        "sidestep": "v2",
        "round": getattr(game, "round", None),
        "turn": getattr(game, "turn", None),
        "bootstrap": bootstrap,
        "timing": timing,
        "seats": seats,
        "tables": tables,
    }
    try:
        hist = getattr(game, "_sidestep_compare_history", None)
        if not isinstance(hist, list):
            hist = []
            game._sidestep_compare_history = hist
        hist.append(
            {
                "checkpoint": checkpoint,
                "round": bundle["round"],
                "turn": bundle["turn"],
                "n_seats": len(seats),
                "sidestep": "v2",
                "timing": timing,
            }
        )
        game._sidestep_compare_last = bundle
        totals = getattr(game, "_sidestep_timing_totals", None)
        if not isinstance(totals, dict):
            totals = {
                "elapsed_s": 0.0,
                "bootstrap_s": 0.0,
                "compare_s": 0.0,
                "live_pln2_eta_s": 0.0,
                "sidestep_side_s": 0.0,
                "sidestep_sync_s142_s": 0.0,
                "sidestep_only_s": 0.0,
                "n": 0,
            }
            game._sidestep_timing_totals = totals
        for k in (
            "elapsed_s",
            "bootstrap_s",
            "compare_s",
            "live_pln2_eta_s",
            "sidestep_side_s",
            "sidestep_sync_s142_s",
            "sidestep_only_s",
        ):
            totals[k] = float(totals.get(k) or 0) + float(timing.get(k) or 0)
        totals["n"] = int(totals.get("n") or 0) + 1
    except Exception:
        pass
    emit_compare_bundle(bundle)
    return bundle


def maybe_run_sidestep_compare(game: Any) -> Optional[Dict[str, Any]]:
    try:
        from core.constants import SIDESTEP_COMPARE

        if not SIDESTEP_COMPARE:
            return None
    except Exception:
        pass
    cp = resolve_checkpoint(game)
    if cp is None:
        return None
    player = _turn_player(game)
    if player is None:
        return None
    key = _fire_key(cp, player)
    fired = _fired_set(game)
    if key in fired:
        return None
    fired.add(key)
    try:
        return run_sidestep_compare(game, cp)
    except Exception as exc:
        print(f"sidestep_compare failed ({cp}): {exc}")
        return None


__all__ = [
    "CHECKPOINT_PHASE",
    "CHECKPOINT_LABEL",
    "SIDESTEP_EVERY_N_OWN_TURNS",
    "SIDESTEP_INCLUDE_OWN_TURN_1",
    "sidestep_every_n_own_turns",
    "is_sidestep_cadence_round",
    "is_sidestep_own_turn_cadence",
    "phase_for_round",
    "checkpoint_for_round",
    "checkpoint_for_own_turn",
    "resolve_checkpoint",
    "live_stage_bundle",
    "seats_missing_way_id",
    "bootstrap_seat_strategies_for_compare",
    "build_seat_compare",
    "format_pln2_compare_table",
    "run_sidestep_compare",
    "maybe_run_sidestep_compare",
    "emit_compare_bundle",
]
