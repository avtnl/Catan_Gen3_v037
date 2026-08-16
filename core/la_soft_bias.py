"""Lab soft bias: nudge Victory-Way ranking toward LA + knight BA preference.

Modes (timing of when bias is active):
  off   — no effect (product default)
  early — from Execution start
  mid   — when max VP among players >= MID_VP or round >= MID_ROUND
  late  — when max VP >= LATE_VP or round >= LATE_ROUND

Does not ban non-LA ways. See Phase L experiment notes / MANUAL.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Timing gates (own global table state)
LA_SOFT_MID_VP: int = 4
LA_SOFT_MID_ROUND: int = 8
LA_SOFT_LATE_VP: int = 6
LA_SOFT_LATE_ROUND: int = 12

# Way ranking: subtract from rank_key / board ETA (lower is better)
LA_WAY_ETA_BONUS: float = 2.0

MODES = frozenset({"off", "early", "mid", "late", "on"})  # on == early


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def normalize_la_soft_bias_mode(raw: Any) -> str:
    m = str(raw or "off").strip().lower()
    if m in ("", "none", "0", "false", "no"):
        return "off"
    if m in ("on", "true", "yes", "always"):
        return "early"
    if m in MODES:
        return m
    return "off"


def get_la_soft_bias_mode(game: Any = None) -> str:
    """Resolve mode from game stamp, else constants."""
    if game is not None:
        try:
            m = getattr(game, "la_soft_bias_mode", None)
            if m is not None and str(m).strip() != "":
                return normalize_la_soft_bias_mode(m)
        except Exception:
            pass
    try:
        from core import constants as C

        return normalize_la_soft_bias_mode(getattr(C, "LA_SOFT_BIAS_MODE", "off"))
    except Exception:
        return "off"


def set_la_soft_bias_mode(game: Any, mode: str) -> str:
    m = normalize_la_soft_bias_mode(mode)
    if game is not None:
        try:
            game.la_soft_bias_mode = m
        except Exception:
            pass
    return m


def max_vp_among_players(game: Any) -> int:
    best = 0
    try:
        from core.ai_dcard_timing import victory_points
    except Exception:
        victory_points = None  # type: ignore
    for p in list(getattr(game, "players", None) or []):
        vp = 0
        if victory_points is not None:
            try:
                vp = int(victory_points(p))
            except Exception:
                vp = 0
        if vp <= 0:
            for attr in ("victory_points", "points", "vp"):
                try:
                    vp = max(vp, int(getattr(p, attr) or 0))
                except Exception:
                    pass
        best = max(best, vp)
    return int(best)


def la_soft_bias_active(game: Any, player: Any = None) -> Tuple[bool, str]:
    """Whether soft bias applies now. Returns (active, detail)."""
    mode = get_la_soft_bias_mode(game)
    if mode == "off":
        return False, "mode_off"
    if game is not None and str(getattr(game, "phase", "") or "") != "Execution":
        return False, "not_execution"
    if mode == "early":
        return True, "early"
    rnd = _safe_int(getattr(game, "round", 0), 0)
    mvp = max_vp_among_players(game)
    if mode == "mid":
        if mvp >= LA_SOFT_MID_VP or rnd >= LA_SOFT_MID_ROUND:
            return True, f"mid_vp={mvp}_r={rnd}"
        return False, f"mid_wait_vp={mvp}_r={rnd}"
    if mode == "late":
        if mvp >= LA_SOFT_LATE_VP or rnd >= LA_SOFT_LATE_ROUND:
            return True, f"late_vp={mvp}_r={rnd}"
        return False, f"late_wait_vp={mvp}_r={rnd}"
    return False, f"unknown_mode_{mode}"


def way_has_la_component(way_id: Any, audit: Any = None) -> bool:
    """True if way requires largest army (audit flags preferred, else table)."""
    wid = _safe_int(way_id, -1)
    if audit is not None:
        try:
            # Explicit audit attrs win (True or False) — do not fall through to table
            if isinstance(audit, Mapping):
                if "biggest_army" in audit or "largest_army" in audit:
                    return bool(audit.get("biggest_army") or audit.get("largest_army"))
            else:
                has_ba = hasattr(audit, "biggest_army")
                has_la = hasattr(audit, "largest_army")
                if has_ba or has_la:
                    return bool(
                        (getattr(audit, "biggest_army", False) if has_ba else False)
                        or (getattr(audit, "largest_army", False) if has_la else False)
                    )
            req = getattr(audit, "requirements", None) or getattr(
                audit, "way_requirements", None
            )
            if isinstance(req, Mapping) and (
                "biggest_army" in req or "largest_army" in req
            ):
                return bool(req.get("biggest_army") or req.get("largest_army"))
            if req is not None and (
                hasattr(req, "biggest_army") or hasattr(req, "largest_army")
            ):
                return bool(
                    getattr(req, "biggest_army", False)
                    or getattr(req, "largest_army", False)
                )
        except Exception:
            pass
    if wid <= 0:
        return False
    try:
        from core.strategy_timing import load_strategy_requirements

        for strategy in load_strategy_requirements() or []:
            try:
                if int(getattr(strategy, "way_id", -1)) != int(wid):
                    continue
                return bool(
                    getattr(strategy, "biggest_army", False)
                    or getattr(strategy, "largest_army", False)
                )
            except Exception:
                continue
    except Exception:
        pass
    return False


def _audit_way_id(audit: Any) -> int:
    try:
        if isinstance(audit, Mapping):
            return _safe_int(audit.get("way_id"), -1)
        return _safe_int(getattr(audit, "way_id", -1), -1)
    except Exception:
        return -1


def apply_la_way_rank_bias(
    game: Any,
    audits: Sequence[Any],
    *,
    player: Any = None,
    bonus: float = LA_WAY_ETA_BONUS,
) -> List[Any]:
    """Lower rank_key / board_expected_turns for LA-component ways when bias active.

    Mutates audits in place when possible; re-sorts by rank_key.
    """
    active, detail = la_soft_bias_active(game, player)
    if not active or not audits:
        return list(audits)
    boosted = 0
    for audit in audits:
        wid = _audit_way_id(audit)
        if not way_has_la_component(wid, audit):
            continue
        boosted += 1
        try:
            if isinstance(audit, Mapping):
                # rare path
                continue
            rk = float(getattr(audit, "rank_key", 0) or 0)
            be = float(getattr(audit, "board_expected_turns", 0) or 0)
            setattr(audit, "rank_key", max(0.0, rk - float(bonus)))
            setattr(audit, "board_expected_turns", max(0.0, be - float(bonus)))
            notes = list(getattr(audit, "notes", None) or [])
            notes.append(f"la_soft_bias:{detail}:-{bonus}")
            setattr(audit, "notes", notes)
        except Exception:
            continue
    try:
        sorted_audits = sorted(
            list(audits),
            key=lambda a: (
                float(getattr(a, "rank_key", 1e9) or 1e9),
                float(getattr(a, "board_expected_turns", 1e9) or 1e9),
                _audit_way_id(a),
            ),
        )
        # mutate original list order if it's a list
        if isinstance(audits, list):
            audits[:] = sorted_audits
            out = audits
        else:
            out = sorted_audits
    except Exception:
        out = list(audits)
    try:
        if game is not None:
            game.last_la_soft_bias_way = {
                "active": True,
                "detail": detail,
                "boosted_ways": boosted,
                "bonus": bonus,
            }
    except Exception:
        pass
    return list(out)


def apply_la_knight_ba_bias(
    game: Any,
    player: Any,
    plan: Mapping[str, Any],
    *,
    features: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """If bias active and knight plan is legal hold, tip to play.

    Does not override illegal plans or explicit win-hold reasons.
    """
    out = dict(plan or {})
    active, detail = la_soft_bias_active(game, player)
    if not active:
        out["la_soft_bias"] = {"active": False, "detail": detail}
        return out
    if not bool(out.get("legal", True)):
        out["la_soft_bias"] = {"active": True, "detail": detail, "applied": False, "why": "illegal"}
        return out
    if bool(out.get("play")):
        out["la_soft_bias"] = {"active": True, "detail": detail, "applied": False, "why": "already_play"}
        return out
    reason = str(out.get("reason") or "")
    # Respect critical holds
    hold_block = (
        "winning" in reason.lower()
        or "hold_for_winning" in reason.lower()
        or "la_delay" in reason.lower()
    )
    if hold_block:
        out["la_soft_bias"] = {"active": True, "detail": detail, "applied": False, "why": "hold_block"}
        return out
    # Tip hold → play
    window = str(out.get("window") or "")
    timing = window if window in ("pre_roll", "post_roll") else out.get("timing")
    out["play"] = True
    out["timing"] = timing
    out["reason"] = f"la_soft_bias_knight:{detail}"
    out["rule"] = "la_soft_bias_knight"
    try:
        score = float(out.get("score") or 0) + 3.0
        out["score"] = score
    except Exception:
        pass
    out["la_soft_bias"] = {
        "active": True,
        "detail": detail,
        "applied": True,
        "why": "tip_hold_to_play",
    }
    return out


def status_dict(game: Any, player: Any = None) -> Dict[str, Any]:
    active, detail = la_soft_bias_active(game, player)
    return {
        "mode": get_la_soft_bias_mode(game),
        "active": active,
        "detail": detail,
        "mid_vp": LA_SOFT_MID_VP,
        "mid_round": LA_SOFT_MID_ROUND,
        "late_vp": LA_SOFT_LATE_VP,
        "late_round": LA_SOFT_LATE_ROUND,
        "way_eta_bonus": LA_WAY_ETA_BONUS,
        "max_vp": max_vp_among_players(game) if game is not None else None,
        "round": _safe_int(getattr(game, "round", None), 0) if game is not None else None,
    }


__all__ = [
    "LA_SOFT_MID_VP",
    "LA_SOFT_MID_ROUND",
    "LA_SOFT_LATE_VP",
    "LA_SOFT_LATE_ROUND",
    "LA_WAY_ETA_BONUS",
    "normalize_la_soft_bias_mode",
    "get_la_soft_bias_mode",
    "set_la_soft_bias_mode",
    "la_soft_bias_active",
    "way_has_la_component",
    "apply_la_way_rank_bias",
    "apply_la_knight_ba_bias",
    "status_dict",
    "max_vp_among_players",
]
