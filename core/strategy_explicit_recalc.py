"""Phase C2 WP-R3 + WP3: evaluate explicit_142_recalc triggers + always-best way pick.

Seats with non-default ``explicit_142_recalc`` can force L2 explore when a
trigger is active, then adopt the L2 rank-1 Victory-Way without the sticky
min-ETA-gain floor.

Trigger codes (OR): 1 VP gain, 2 ETA setback, 3 hard-invalid target,
4 every n own turns, 5 VP milestones, **6 sticky-target threat**, **7 LR tooling**.
See ``core/explicit_142_recalc.py`` and ``docs/PhaseC2_way_reassess_experiment_plan.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.explicit_142_recalc import (
    EXPLICIT_L2_CODE6_MAX_PER_GAME,
    EXPLICIT_L2_CODE7_MAX_PER_GAME,
    EXPLICIT_L2_WP3_MAX_PER_GAME,
    EXPLICIT_L2_WP3_ONCE_PER_OWN_TURN,
    EXPLICIT_RECALC_EVERY_N_OWN_TURNS,
    EXPLICIT_RECALC_MILESTONE_VPS,
    EXPLICIT_RECALC_MILESTONES,
    EXPLICIT_RECALC_NONE,
    EXPLICIT_RECALC_ON_ETA_SETBACK,
    EXPLICIT_RECALC_ON_LR_TOOLING,
    EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT,
    EXPLICIT_RECALC_ON_TARGET_HARD_INVALID,
    EXPLICIT_RECALC_ON_VP_GAIN,
    EXPLICIT_RECALC_SETBACK_THR,
    EXPLICIT_WAY_PICK_BEST,
    EXPLICIT_WAY_PICK_DEFAULT,
    code_name,
    codes_present,
    every_n_periods,
    has_explicit_recalc,
    normalize_explicit_142_recalc,
)

# Reconsider / sticky hard-invalid needles (lowercase)
_HARD_INVALID_REASONS = (
    "hard_invalid",
    "route_illegal",
    "sticky_dead",
    "target_occupied",
    "target_race_impossible",
    "locked_way_infeasible",
    "route_edges",
    "target_blocked",
    "board_fit",
)

_THREAT_FLAG_NEEDLES = (
    "target_blocked",
    "race_worse",
    "target_race",
    "opponent_settlement",
    "opponent_city",
    "opp_structure",
    "sticky_target_threat",
    "threat",
)


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        if f != f:
            return default
        return f
    except Exception:
        return default


def get_norm(player: Any) -> List[Dict[str, Any]]:
    """Normalized explicit_142_recalc entries for ``player``."""
    if player is None:
        return [{"code": EXPLICIT_RECALC_NONE}]
    raw_norm = getattr(player, "explicit_142_recalc_norm", None)
    if isinstance(raw_norm, list) and raw_norm:
        return list(raw_norm)
    return normalize_explicit_142_recalc(getattr(player, "explicit_142_recalc", [0]))


def is_treatment_seat(player: Any) -> bool:
    """True when seat has any non-zero explicit recalc code."""
    return has_explicit_recalc(get_norm(player))


def _setback_threshold() -> float:
    try:
        from core import constants as C

        return float(getattr(C, "EXPLICIT_RECALC_SETBACK_THR", EXPLICIT_RECALC_SETBACK_THR) or 1.0)
    except Exception:
        return float(EXPLICIT_RECALC_SETBACK_THR)


def _milestone_vps() -> Tuple[int, ...]:
    try:
        from core import constants as C

        raw = getattr(C, "EXPLICIT_RECALC_MILESTONE_VPS", None)
        if raw is not None:
            return tuple(int(x) for x in raw)
    except Exception:
        pass
    return tuple(int(x) for x in EXPLICIT_RECALC_MILESTONE_VPS)


def _way_pick_mode() -> str:
    try:
        from core import constants as C

        mode = str(getattr(C, "EXPLICIT_WAY_PICK", EXPLICIT_WAY_PICK_DEFAULT) or EXPLICIT_WAY_PICK_DEFAULT)
        return mode.strip().lower() or EXPLICIT_WAY_PICK_DEFAULT
    except Exception:
        return str(EXPLICIT_WAY_PICK_DEFAULT or EXPLICIT_WAY_PICK_BEST).lower()


def ensure_runtime(player: Any) -> Dict[str, Any]:
    """Ensure and return mutable runtime latch bag on player."""
    if player is None:
        return {}
    rt = getattr(player, "explicit_recalc_runtime", None)
    if not isinstance(rt, dict):
        rt = {}
        try:
            setattr(player, "explicit_recalc_runtime", rt)
        except Exception:
            return rt
    rt.setdefault("own_turn_count", 0)
    rt.setdefault("last_turn_key", None)
    rt.setdefault("last_vp", None)
    rt.setdefault("milestones_crossed", [])
    rt.setdefault("last_sticky_eta", None)
    rt.setdefault("pending_codes", [])
    rt.setdefault("session_active", False)
    rt.setdefault("session_codes", [])
    rt.setdefault("session_reason", "")
    rt.setdefault("last_eval", {})
    # WP3 caps / once-per-turn
    rt.setdefault("code6_fires", 0)
    rt.setdefault("code7_fires", 0)
    rt.setdefault("wp3_fires", 0)
    rt.setdefault("last_code6_turn_key", None)
    rt.setdefault("last_code7_turn_key", None)
    rt.setdefault("last_tfr_count", None)
    return rt


def _wp3_cap(name: str, default: int) -> int:
    try:
        from core import constants as C

        return max(0, int(getattr(C, name, default) or default))
    except Exception:
        return max(0, int(default))


def _own_turn_key(game: Any, player: Any) -> Optional[List[int]]:
    try:
        return [
            int(_safe_int(getattr(game, "round", None), 0) or 0),
            int(_safe_int(getattr(game, "turn", None), 0) or 0),
            int(_safe_int(getattr(player, "id", None), 0) or 0),
        ]
    except Exception:
        return None


def _can_latch_wp3(rt: Dict[str, Any], code: int, turn_key: Optional[List[int]]) -> bool:
    """Thrash guards for codes 6/7."""
    if code == EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT:
        max_c = _wp3_cap("EXPLICIT_L2_CODE6_MAX_PER_GAME", EXPLICIT_L2_CODE6_MAX_PER_GAME)
        if int(rt.get("code6_fires") or 0) >= max_c:
            return False
        if EXPLICIT_L2_WP3_ONCE_PER_OWN_TURN and turn_key is not None:
            if rt.get("last_code6_turn_key") == list(turn_key):
                return False
    elif code == EXPLICIT_RECALC_ON_LR_TOOLING:
        max_c = _wp3_cap("EXPLICIT_L2_CODE7_MAX_PER_GAME", EXPLICIT_L2_CODE7_MAX_PER_GAME)
        if int(rt.get("code7_fires") or 0) >= max_c:
            return False
        if EXPLICIT_L2_WP3_ONCE_PER_OWN_TURN and turn_key is not None:
            if rt.get("last_code7_turn_key") == list(turn_key):
                return False
    else:
        return True
    max_wp3 = _wp3_cap("EXPLICIT_L2_WP3_MAX_PER_GAME", EXPLICIT_L2_WP3_MAX_PER_GAME)
    if int(rt.get("wp3_fires") or 0) >= max_wp3:
        return False
    return True


def _record_wp3_fire(rt: Dict[str, Any], code: int, turn_key: Optional[List[int]]) -> None:
    if code == EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT:
        rt["code6_fires"] = int(rt.get("code6_fires") or 0) + 1
        if turn_key is not None:
            rt["last_code6_turn_key"] = list(turn_key)
    elif code == EXPLICIT_RECALC_ON_LR_TOOLING:
        rt["code7_fires"] = int(rt.get("code7_fires") or 0) + 1
        if turn_key is not None:
            rt["last_code7_turn_key"] = list(turn_key)
    if code in (
        EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT,
        EXPLICIT_RECALC_ON_LR_TOOLING,
    ):
        rt["wp3_fires"] = int(rt.get("wp3_fires") or 0) + 1


def _sticky_wants_lr(player: Any) -> bool:
    try:
        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping):
            if bool(direction.get("longest_road") or direction.get("way_lr")):
                return True
            tags = " ".join(str(t).lower() for t in list(direction.get("tags") or []))
            if "longest road" in tags or tags.strip() == "lr":
                return True
        sticky = getattr(player, "sticky_commitment", None) or {}
        if isinstance(sticky, Mapping) and sticky.get("wants_lr"):
            return True
    except Exception:
        pass
    try:
        from core.ai_road_planner import way_wants_longest_road

        return bool(way_wants_longest_road(player))
    except Exception:
        return False


def _has_tfr_tooling(player: Any) -> bool:
    try:
        from core.strategy_way_residual import unplayed_tfr

        return int(unplayed_tfr(player) or 0) > 0
    except Exception:
        pass
    try:
        for c in list(getattr(player, "development_cards", []) or []):
            s = str(c or "").lower()
            if "two_free" in s or s in ("tfr", "road_building"):
                return True
    except Exception:
        pass
    return False


def _can_afford_road(player: Any) -> bool:
    """Rough hand check: 1 wood + 1 brick (or bank rates ignored for latch)."""
    try:
        rc = getattr(player, "rcards", None)
        if isinstance(rc, Mapping):
            w = int(rc.get("Wood", rc.get("wood", 0)) or 0)
            b = int(rc.get("Brick", rc.get("brick", 0)) or 0)
            return w >= 1 and b >= 1
        if isinstance(rc, (list, tuple)) and len(rc) >= 5:
            # game order Wh,O,Wd,B,Sh
            return int(rc[2] or 0) >= 1 and int(rc[3] or 0) >= 1
    except Exception:
        pass
    return False


def note_sticky_target_threat(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """WP3 code 6: latch when sticky path/target is under opponent threat."""
    out: Dict[str, Any] = {"ok": False, "latched": [], "code": 6}
    if player is None or not is_treatment_seat(player):
        return out
    norm = get_norm(player)
    if EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT not in _policy_codes(norm):
        out["ok"] = True
        out["skipped"] = "no_code_6"
        return out

    threatened = bool(force)
    if not threatened:
        try:
            from core.strategy_reconsider import get_reconsider_flags

            flags = get_reconsider_flags(player)
            if bool(flags.get("target_blocked") or flags.get("race_worse")):
                threatened = True
            for r in list(flags.get("reasons") or []):
                rs = str(r or "").lower()
                if any(n in rs for n in _THREAT_FLAG_NEEDLES):
                    threatened = True
                    break
        except Exception:
            pass
        try:
            meta = getattr(player, "last_sticky_meta", None)
            if isinstance(meta, Mapping):
                inv = str(meta.get("invalidate_reason") or meta.get("reason") or "").lower()
                if any(n in inv for n in _THREAT_FLAG_NEEDLES):
                    threatened = True
        except Exception:
            pass
        # plan-relevant opponent structure flags on strategy_recalc_flag
        try:
            fl = getattr(player, "strategy_recalc_flag", None)
            if isinstance(fl, Mapping) and fl.get("pending"):
                for r in list(fl.get("reasons") or []):
                    rs = str(r or "").lower()
                    if any(n in rs for n in _THREAT_FLAG_NEEDLES):
                        threatened = True
                        break
        except Exception:
            pass

    if not threatened:
        out["ok"] = True
        out["skipped"] = "no_threat"
        return out

    rt = ensure_runtime(player)
    turn_key = _own_turn_key(game, player)
    if not _can_latch_wp3(rt, EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT, turn_key):
        out["ok"] = True
        out["skipped"] = "cap"
        return out

    _latch_code(rt, EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT)
    _record_wp3_fire(rt, EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT, turn_key)
    if reason:
        rt["threat_reason"] = str(reason)[:120]
    out["latched"] = [EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT]
    out["ok"] = True
    return out


def note_lr_tooling(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """WP3 code 7: latch when LR-pursuing seat gains TFR/road tooling."""
    out: Dict[str, Any] = {"ok": False, "latched": [], "code": 7}
    if player is None or not is_treatment_seat(player):
        return out
    norm = get_norm(player)
    if EXPLICIT_RECALC_ON_LR_TOOLING not in _policy_codes(norm):
        out["ok"] = True
        out["skipped"] = "no_code_7"
        return out

    wants_lr = _sticky_wants_lr(player)
    has_tfr = _has_tfr_tooling(player)
    can_road = _can_afford_road(player)
    rt = ensure_runtime(player)
    tfr_n = 0
    try:
        from core.strategy_way_residual import unplayed_tfr

        tfr_n = int(unplayed_tfr(player) or 0)
    except Exception:
        tfr_n = 1 if has_tfr else 0
    last_tfr = rt.get("last_tfr_count")
    tfr_increased = last_tfr is not None and tfr_n > int(last_tfr)
    rt["last_tfr_count"] = tfr_n

    tooling = bool(force)
    if not tooling and wants_lr and (has_tfr or can_road):
        # Prefer latch when TFR count rose (2nd TFR buy) or TFR+road cash
        if tfr_increased or (has_tfr and can_road) or (has_tfr and tfr_n >= 2):
            tooling = True
        elif has_tfr and reason:
            tooling = True

    if not tooling:
        out["ok"] = True
        out["skipped"] = "no_tooling"
        out["wants_lr"] = wants_lr
        out["has_tfr"] = has_tfr
        return out

    turn_key = _own_turn_key(game, player)
    if not _can_latch_wp3(rt, EXPLICIT_RECALC_ON_LR_TOOLING, turn_key):
        out["ok"] = True
        out["skipped"] = "cap"
        return out

    _latch_code(rt, EXPLICIT_RECALC_ON_LR_TOOLING)
    _record_wp3_fire(rt, EXPLICIT_RECALC_ON_LR_TOOLING, turn_key)
    if reason:
        rt["lr_tooling_reason"] = str(reason)[:120]
    out["latched"] = [EXPLICIT_RECALC_ON_LR_TOOLING]
    out["ok"] = True
    out["tfr_n"] = tfr_n
    return out


def _policy_codes(norm: Sequence[Mapping[str, Any]]) -> set:
    return set(codes_present(norm)) - {EXPLICIT_RECALC_NONE}


def _latch_code(rt: Dict[str, Any], code: int) -> None:
    try:
        c = int(code)
    except Exception:
        return
    if c <= 0:
        return
    pending = list(rt.get("pending_codes") or [])
    if c not in pending:
        pending.append(c)
    rt["pending_codes"] = pending


def _player_vp(game: Any, player: Any) -> int:
    if player is None:
        return 0
    # Prefer stored VP fields (tests / saves); fall back to effective_vp helpers.
    for attr in ("victory_points", "points", "vp"):
        try:
            v = getattr(player, attr, None)
            if v is not None and v != "":
                return max(0, int(v))
        except Exception:
            continue
    if game is not None:
        try:
            fn = getattr(game, "effective_vp", None)
            if callable(fn):
                return max(0, int(fn(player) or 0))
        except Exception:
            pass
    try:
        from core.victory import effective_vp

        return max(0, int(effective_vp(player) or 0))
    except Exception:
        pass
    return 0


def _current_sticky_eta(player: Any) -> Optional[float]:
    if player is None:
        return None
    for src in (
        getattr(player, "strategic_direction", None),
        getattr(player, "sticky_commitment", None),
    ):
        if not isinstance(src, Mapping):
            continue
        for key in (
            "realistic_expected_turns",
            "board_expected_turns",
            "expected_turns",
            "rank_key",
            "eta",
        ):
            eta = _safe_float(src.get(key), None)
            if eta is not None and eta < 9000:
                return float(eta)
    return None


def note_own_execution_turn(game: Any, player: Any) -> Dict[str, Any]:
    """Call at begin_execution_turn: count own turns; latch code 4 when due.

    Returns a small status dict for dig-in.
    """
    out: Dict[str, Any] = {"ok": False, "latched": []}
    if player is None or not is_treatment_seat(player):
        return out
    norm = get_norm(player)
    if EXPLICIT_RECALC_EVERY_N_OWN_TURNS not in _policy_codes(norm):
        out["ok"] = True
        out["skipped"] = "no_code_4"
        return out
    rt = ensure_runtime(player)
    try:
        key = (
            _safe_int(getattr(game, "round", None), 0),
            _safe_int(getattr(game, "turn", None), 0),
            _safe_int(getattr(player, "id", None), 0),
        )
    except Exception:
        key = None
    if key is not None and rt.get("last_turn_key") == list(key):
        out["ok"] = True
        out["skipped"] = "same_turn"
        return out
    if key is not None:
        rt["last_turn_key"] = list(key)
    count = int(rt.get("own_turn_count") or 0) + 1
    rt["own_turn_count"] = count
    out["own_turn_count"] = count
    latched: List[int] = []
    for n in every_n_periods(norm):
        n_i = max(1, int(n))
        if count % n_i == 0:
            _latch_code(rt, EXPLICIT_RECALC_EVERY_N_OWN_TURNS)
            latched.append(EXPLICIT_RECALC_EVERY_N_OWN_TURNS)
            break
    out["latched"] = latched
    out["ok"] = True
    return out


def note_vp_and_milestones(game: Any, player: Any) -> Dict[str, Any]:
    """Compare VP to last sample; latch code 1 (gain) and 5 (milestones)."""
    out: Dict[str, Any] = {"ok": False, "latched": [], "vp": None}
    if player is None or not is_treatment_seat(player):
        return out
    norm = get_norm(player)
    codes = _policy_codes(norm)
    if not codes & {
        EXPLICIT_RECALC_ON_VP_GAIN,
        EXPLICIT_RECALC_MILESTONES,
    }:
        out["ok"] = True
        out["skipped"] = "no_vp_codes"
        return out
    rt = ensure_runtime(player)
    vp = _player_vp(game, player)
    out["vp"] = vp
    last = rt.get("last_vp")
    latched: List[int] = []
    if last is not None:
        try:
            last_i = int(last)
        except Exception:
            last_i = vp
        if vp > last_i:
            if EXPLICIT_RECALC_ON_VP_GAIN in codes:
                _latch_code(rt, EXPLICIT_RECALC_ON_VP_GAIN)
                latched.append(EXPLICIT_RECALC_ON_VP_GAIN)
            if EXPLICIT_RECALC_MILESTONES in codes:
                crossed = [int(x) for x in (rt.get("milestones_crossed") or [])]
                for m in _milestone_vps():
                    if last_i < m <= vp and m not in crossed:
                        crossed.append(m)
                        _latch_code(rt, EXPLICIT_RECALC_MILESTONES)
                        if EXPLICIT_RECALC_MILESTONES not in latched:
                            latched.append(EXPLICIT_RECALC_MILESTONES)
                rt["milestones_crossed"] = crossed
    rt["last_vp"] = vp
    out["latched"] = latched
    out["ok"] = True
    return out


def note_eta_sample(player: Any, eta: Optional[float] = None) -> Dict[str, Any]:
    """Record sticky ETA; latch code 2 if rise ≥ setback threshold."""
    out: Dict[str, Any] = {"ok": False, "latched": [], "eta": None, "prev": None}
    if player is None or not is_treatment_seat(player):
        return out
    norm = get_norm(player)
    if EXPLICIT_RECALC_ON_ETA_SETBACK not in _policy_codes(norm):
        # still keep last eta if provided for dig-in
        if eta is not None:
            rt = ensure_runtime(player)
            rt["last_sticky_eta"] = float(eta)
        out["ok"] = True
        out["skipped"] = "no_code_2"
        return out
    rt = ensure_runtime(player)
    cur = _safe_float(eta, None)
    if cur is None:
        cur = _current_sticky_eta(player)
    out["eta"] = cur
    prev = _safe_float(rt.get("last_sticky_eta"), None)
    out["prev"] = prev
    thr = _setback_threshold()
    latched: List[int] = []
    if cur is not None and prev is not None and cur >= prev + thr - 1e-9:
        _latch_code(rt, EXPLICIT_RECALC_ON_ETA_SETBACK)
        latched.append(EXPLICIT_RECALC_ON_ETA_SETBACK)
        out["delta"] = float(cur - prev)
        out["thr"] = thr
    if cur is not None:
        # Update baseline after check so a single rise latches once
        rt["last_sticky_eta"] = float(cur)
    out["latched"] = latched
    out["ok"] = True
    return out


def note_hard_invalid(player: Any, reason: str = "") -> Dict[str, Any]:
    """Latch code 3 when sticky/target hard-invalid and policy includes 3."""
    out: Dict[str, Any] = {"ok": False, "latched": []}
    if player is None or not is_treatment_seat(player):
        return out
    norm = get_norm(player)
    if EXPLICIT_RECALC_ON_TARGET_HARD_INVALID not in _policy_codes(norm):
        out["ok"] = True
        out["skipped"] = "no_code_3"
        return out
    rt = ensure_runtime(player)
    _latch_code(rt, EXPLICIT_RECALC_ON_TARGET_HARD_INVALID)
    if reason:
        rt["hard_invalid_reason"] = str(reason)[:120]
    out["latched"] = [EXPLICIT_RECALC_ON_TARGET_HARD_INVALID]
    out["ok"] = True
    return out


def _hard_invalid_from_flags(player: Any) -> bool:
    try:
        from core.strategy_reconsider import get_reconsider_flags

        flags = get_reconsider_flags(player)
        if bool(flags.get("hard_invalid")):
            return True
        for r in list(flags.get("reasons") or []):
            rs = str(r or "").lower()
            if any(n in rs for n in _HARD_INVALID_REASONS):
                return True
    except Exception:
        pass
    # Sticky last invalidate
    try:
        meta = getattr(player, "last_sticky_meta", None)
        if isinstance(meta, Mapping):
            inv = str(meta.get("invalidate_reason") or "").lower()
            if any(n in inv for n in _HARD_INVALID_REASONS):
                return True
    except Exception:
        pass
    return False


def evaluate_explicit_triggers(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    sample_eta: bool = True,
    sample_vp: bool = True,
) -> Dict[str, Any]:
    """Return whether any explicit trigger is active and which codes.

    Side effects: VP/ETA sampling may latch pending codes; hard-invalid may latch.
    Does **not** clear pending (consume after successful explicit L2).
    """
    result: Dict[str, Any] = {
        "active": False,
        "codes": [],
        "primary": None,
        "reason": "",
        "pending": [],
        "treatment": False,
    }
    if player is None:
        return result
    if not is_treatment_seat(player):
        return result
    result["treatment"] = True
    norm = get_norm(player)
    policy = _policy_codes(norm)
    if sample_vp:
        note_vp_and_milestones(game, player)
    if sample_eta:
        note_eta_sample(player, None)
    if EXPLICIT_RECALC_ON_TARGET_HARD_INVALID in policy and _hard_invalid_from_flags(player):
        note_hard_invalid(player, reason=reason or "reconsider_hard_invalid")
    # WP3: sample threat + LR tooling on each evaluate (capped)
    if EXPLICIT_RECALC_ON_STICKY_TARGET_THREAT in policy:
        note_sticky_target_threat(game, player, reason=reason or "eval_threat")
    if EXPLICIT_RECALC_ON_LR_TOOLING in policy:
        note_lr_tooling(game, player, reason=reason or "eval_lr_tooling")

    rt = ensure_runtime(player)
    pending = [int(c) for c in (rt.get("pending_codes") or []) if int(c) in policy]
    # de-dupe preserve order
    seen = set()
    ordered: List[int] = []
    for c in pending:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    rt["pending_codes"] = list(ordered)
    result["pending"] = list(ordered)
    if not ordered:
        rt["last_eval"] = dict(result)
        return result
    primary = ordered[0]
    result["active"] = True
    result["codes"] = list(ordered)
    result["primary"] = primary
    result["reason"] = f"explicit_142_recalc:{primary}"
    result["code_names"] = [code_name(c) for c in ordered]
    rt["last_eval"] = dict(result)
    return result


def should_force_explicit_l2(
    game: Any,
    player: Any,
    *,
    reason: str = "",
) -> Tuple[bool, str]:
    """Gate helper: (True, why) when explicit trigger forces L2 explore."""
    ev = evaluate_explicit_triggers(game, player, reason=reason)
    if ev.get("active"):
        return True, str(ev.get("reason") or "explicit_142_recalc")
    return False, ""


def mark_explicit_l2_session(player: Any, eval_result: Optional[Mapping[str, Any]] = None) -> None:
    """Mark that this L2 explore is an explicit reassess (always-best may apply)."""
    if player is None:
        return
    rt = ensure_runtime(player)
    if eval_result is None:
        eval_result = rt.get("last_eval") or {}
    if not isinstance(eval_result, Mapping):
        eval_result = {}
    rt["session_active"] = True
    rt["session_codes"] = list(eval_result.get("codes") or eval_result.get("pending") or [])
    rt["session_reason"] = str(eval_result.get("reason") or "explicit_142_recalc")
    try:
        setattr(player, "explicit_l2_session", True)
        setattr(player, "last_explicit_trigger", dict(eval_result))
    except Exception:
        pass


def clear_explicit_l2_session(player: Any, *, consume_pending: bool = True) -> None:
    """Clear session flag after L2; optionally drop pending latches that fired."""
    if player is None:
        return
    rt = ensure_runtime(player)
    fired = list(rt.get("session_codes") or [])
    rt["session_active"] = False
    rt["session_codes"] = []
    rt["session_reason"] = ""
    if consume_pending and fired:
        pending = [int(c) for c in (rt.get("pending_codes") or [])]
        rt["pending_codes"] = [c for c in pending if c not in set(fired)]
    try:
        setattr(player, "explicit_l2_session", False)
    except Exception:
        pass


def is_explicit_l2_session(player: Any) -> bool:
    if player is None:
        return False
    if bool(getattr(player, "explicit_l2_session", False)):
        return True
    rt = getattr(player, "explicit_recalc_runtime", None)
    return isinstance(rt, dict) and bool(rt.get("session_active"))


def should_adopt_best_way(player: Any) -> bool:
    """True when treatment seat + explicit L2 session + way pick = best."""
    if not is_treatment_seat(player):
        return False
    if not is_explicit_l2_session(player):
        return False
    mode = _way_pick_mode()
    return mode in ("best", "best_way", EXPLICIT_WAY_PICK_BEST, "always_best")


def track_way_used(player: Any, way_id: Any, *, switched: Optional[bool] = None) -> List[int]:
    """Append way_id to ways_used_this_game (ordered unique); bump switch count."""
    if player is None:
        return []
    wid = _safe_int(way_id, None)
    if wid is None or wid <= 0:
        return list(getattr(player, "ways_used_this_game", None) or [])
    used = list(getattr(player, "ways_used_this_game", None) or [])
    if wid not in used:
        used.append(wid)
        try:
            setattr(player, "ways_used_this_game", used)
        except Exception:
            pass
        if switched is None:
            switched = len(used) > 1
    if switched:
        try:
            setattr(
                player,
                "way_switch_count",
                int(getattr(player, "way_switch_count", 0) or 0) + 1,
            )
        except Exception:
            pass
    return list(used)


def record_way_reassess_compare(
    player: Any,
    game: Any,
    *,
    locked_way: Any,
    best_alt_way: Any,
    eta_locked: Any = None,
    eta_alt: Any = None,
    switched: bool = False,
    switch_reason: str = "",
    trigger: str = "",
    write_log: bool = True,
) -> Dict[str, Any]:
    """Store compare bag on player and append JSONL (WP-R4).

    Uses ``core.way_reassess_log.publish_way_reassess_compare`` for path/dedupe.
    """
    bag: Dict[str, Any] = {
        "schema": "WayReassessCompare",
        "player_id": _safe_int(getattr(player, "id", None), None),
        "round": _safe_int(getattr(game, "round", None), None) if game is not None else None,
        "turn": _safe_int(getattr(game, "turn", None), None) if game is not None else None,
        "trigger": str(trigger or ""),
        "locked_way": _safe_int(locked_way, None),
        "best_alt_way": _safe_int(best_alt_way, None),
        "eta_locked": _safe_float(eta_locked, None),
        "eta_alt": _safe_float(eta_alt, None),
        "switched": bool(switched),
        "switch_reason": str(switch_reason or ""),
        "explicit_codes": list(
            (getattr(player, "explicit_recalc_runtime", None) or {}).get("session_codes") or []
        ),
        "ways_used_so_far": list(getattr(player, "ways_used_this_game", None) or []),
    }
    el = bag.get("eta_locked")
    ea = bag.get("eta_alt")
    if el is not None and ea is not None:
        bag["eta_gain_if_switch"] = round(float(el) - float(ea), 3)
    try:
        from core.way_reassess_log import publish_way_reassess_compare

        return publish_way_reassess_compare(
            player, game, bag, write_log=bool(write_log)
        )
    except Exception:
        try:
            setattr(player, "last_way_reassess_compare", bag)
        except Exception:
            pass
        return bag


def force_direction_to_best_audit(
    direction: Mapping[str, Any],
    audits: Sequence[Any],
    *,
    reason: str = "explicit_142_recalc_best_way",
) -> Tuple[Dict[str, Any], Optional[Any], Dict[str, Any]]:
    """Rewrite direction to L2 audits[0] (rank-1). Returns (direction, audit, meta)."""
    meta: Dict[str, Any] = {"applied": False, "reason": reason}
    direction_out = dict(direction or {})
    if not audits:
        meta["reason"] = "no_audits"
        return direction_out, None, meta
    winner = audits[0]
    try:
        from core.ai_way_portfolio import board_audit_to_strategic_direction, _audit_get, _safe_int as _si

        new_dir = board_audit_to_strategic_direction(
            winner,
            abstract_preferred=direction_out,
            override_applied=True,
            override_reason=reason,
        )
        if isinstance(new_dir, Mapping):
            direction_out = dict(new_dir)
        direction_out["preference_source"] = (
            str(direction_out.get("preference_source") or "") + "+explicit_best_way"
        ).lstrip("+")
        direction_out["explicit_best_way"] = True
        direction_out["explicit_best_way_reason"] = reason
        meta["applied"] = True
        meta["best_way_id"] = _si(_audit_get(winner, "way_id"), None)
        meta["eta"] = _safe_float(
            _audit_get(winner, "realistic_expected_turns")
            or _audit_get(winner, "board_expected_turns"),
            None,
        )
    except Exception as exc:
        meta["error"] = str(exc)
        # Minimal fallback: copy way id fields
        try:
            from core.ai_way_portfolio import _audit_get, _safe_int as _si

            wid = _si(_audit_get(winner, "way_id"), None)
            if wid is not None:
                direction_out["preferred_way_id"] = wid
                direction_out["way_id"] = wid
                direction_out["explicit_best_way"] = True
                meta["applied"] = True
                meta["best_way_id"] = wid
        except Exception:
            pass
    return direction_out, winner, meta


def audit_eta(audit: Any) -> Optional[float]:
    try:
        from core.ai_way_portfolio import _audit_get

        return _safe_float(
            _audit_get(audit, "realistic_expected_turns")
            or _audit_get(audit, "board_expected_turns")
            or _audit_get(audit, "rank_key"),
            None,
        )
    except Exception:
        if isinstance(audit, Mapping):
            return _safe_float(
                audit.get("realistic_expected_turns")
                or audit.get("board_expected_turns")
                or audit.get("rank_key"),
                None,
            )
    return None


def audit_way_id(audit: Any) -> Optional[int]:
    try:
        from core.ai_way_portfolio import _audit_get, _safe_int as _si

        return _si(_audit_get(audit, "way_id"), None)
    except Exception:
        if isinstance(audit, Mapping):
            return _safe_int(audit.get("way_id"), None)
    return None


def find_audit_eta_for_way(audits: Sequence[Any], way_id: Any) -> Optional[float]:
    wid = _safe_int(way_id, None)
    if wid is None:
        return None
    for a in list(audits or []):
        if audit_way_id(a) == wid:
            return audit_eta(a)
    return None


__all__ = [
    "get_norm",
    "is_treatment_seat",
    "ensure_runtime",
    "note_own_execution_turn",
    "note_vp_and_milestones",
    "note_eta_sample",
    "note_hard_invalid",
    "note_sticky_target_threat",
    "note_lr_tooling",
    "evaluate_explicit_triggers",
    "should_force_explicit_l2",
    "mark_explicit_l2_session",
    "clear_explicit_l2_session",
    "is_explicit_l2_session",
    "should_adopt_best_way",
    "track_way_used",
    "record_way_reassess_compare",
    "force_direction_to_best_audit",
    "audit_eta",
    "audit_way_id",
    "find_audit_eta_for_way",
]
