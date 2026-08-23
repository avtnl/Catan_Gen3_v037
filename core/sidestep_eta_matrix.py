"""Sidestep ETA v2 — observe-only NumPy timing (does **not** replace live EH).

Spec: ``Sidestep_v2.txt`` / ``docs/Sidestep_v2_QA.md``.

Pipeline at horizon H:
  credit = RP * (H/9)
  raw = credit - TRCards_res
  positives /= TR
  floor each component (math.floor, toward -inf)
  S = sum

Walk from phase start (early=27, mid=18, late=9):
  S < 0  → search H upward until S >= 0
  S >= 0 → search H downward to least H with S >= 0

Optional confidence gate: raise H until EH binomial confidence >= target
(empty hand, RemTR need, RP_after pips).
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

N_RES = 5
OWN_TURNS_PER_RP = 9.0
PHASE_START_H = {
    "early": 27.0,
    "mid": 18.0,
    "late": 9.0,
    "end": 9.0,
}
DEFAULT_MAX_TURNS = 60.0
DEFAULT_MIN_TURNS = 1.0

# DC buy cost lock (operator): Wheat, Ore, Wood, Brick, Sheep
try:
    from core.constants import RCARDS_FOR_DCARD as _DC_COST  # type: ignore

    DC_COST_VEC = tuple(float(x) for x in list(_DC_COST)[:5])
except Exception:
    DC_COST_VEC = (1.0, 1.0, 0.0, 0.0, 1.0)


def phase_start_horizon(phase: str) -> float:
    p = str(phase or "mid").strip().lower()
    return float(PHASE_START_H.get(p, PHASE_START_H["mid"]))


def horizon_grid(phase: str) -> Tuple[float, ...]:
    """Start horizon only (v2 walk does not use a prebuilt cascade list)."""
    h0 = phase_start_horizon(phase)
    return (h0,)


def mult_for_horizon(horizon: float) -> float:
    return float(horizon) / OWN_TURNS_PER_RP


def floor_component(x: float) -> int:
    """Sidestep_v2 worked example: floor toward −∞ (0.5→0, 5.8→5)."""
    return int(math.floor(float(x) + 1e-12))


def _as_tr_matrix(
    tr: Union[float, Sequence[float], np.ndarray],
    n_targets: int,
) -> np.ndarray:
    arr = np.asarray(tr, dtype=float)
    if arr.ndim == 0:
        return np.full((n_targets, N_RES), float(arr), dtype=float)
    if arr.ndim == 1:
        if arr.size == N_RES:
            return np.tile(arr.reshape(1, N_RES), (n_targets, 1))
        if arr.size == n_targets:
            return np.repeat(arr.reshape(n_targets, 1), N_RES, axis=1)
    if arr.shape == (n_targets, N_RES):
        return arr
    raise ValueError(f"tr shape unsupported: {arr.shape}")


def cell_components_v2(
    horizon: float,
    trcards: np.ndarray,
    rp: np.ndarray,
    tr: Union[float, Sequence[float], np.ndarray],
) -> Dict[str, np.ndarray]:
    """Compute raw / adjusted / floored components and scalar surplus S (W×T)."""
    need = np.asarray(trcards, dtype=float)
    pips = np.asarray(rp, dtype=float)
    if need.ndim != 2 or need.shape[1] != N_RES:
        raise ValueError(f"trcards expected (W,5), got {need.shape}")
    if pips.ndim != 2 or pips.shape[1] != N_RES:
        raise ValueError(f"rp expected (T,5), got {pips.shape}")
    w_n, t_n = need.shape[0], pips.shape[0]
    rates = _as_tr_matrix(tr, t_n)
    mult = mult_for_horizon(horizon)
    rp_scaled = pips * mult
    raw = rp_scaled[None, :, :] - need[:, None, :]
    adj = raw.copy()
    pos = adj > 0
    rates_b = np.broadcast_to(rates[None, :, :], adj.shape)
    adj = np.where(pos, adj / np.maximum(rates_b, 1e-12), adj)
    # Floor each resource component (v2)
    floored = np.floor(adj + 1e-12).astype(float)
    surplus = floored.sum(axis=2)
    return {
        "horizon": np.array(float(horizon), dtype=float),
        "mult": np.array(mult, dtype=float),
        "rp_scaled": rp_scaled,
        "raw": raw,
        "adjusted": adj,
        "floored": floored,
        "surplus": surplus,
        "denom": rp_scaled.sum(axis=1),
    }


def cell_surplus_scalar(
    horizon: float,
    trcards_1x5: Sequence[float],
    rp_1x5: Sequence[float],
    tr: Union[float, Sequence[float]],
) -> float:
    out = cell_components_v2(
        horizon,
        np.asarray(trcards_1x5, dtype=float).reshape(1, 5),
        np.asarray(rp_1x5, dtype=float).reshape(1, 5),
        tr,
    )
    return float(out["surplus"][0, 0])


def walk_turns_v2(
    trcards: Sequence[float],
    rp: Sequence[float],
    tr: Union[float, Sequence[float]],
    *,
    phase: str = "mid",
    start_h: Optional[float] = None,
    min_h: float = DEFAULT_MIN_TURNS,
    max_h: float = DEFAULT_MAX_TURNS,
    abort_h: Optional[float] = None,
) -> Dict[str, Any]:
    """Walk to least H with floored surplus S >= 0. Returns SideRaw.

    If ``abort_h`` is set and the walk goes **up** past that horizon while still
    negative, stop early (cannot beat a known better Side).
    """
    h0 = float(start_h) if start_h is not None else phase_start_horizon(phase)
    h0 = max(float(min_h), min(float(max_h), h0))
    need = [float(x) for x in list(trcards)[:5]]
    while len(need) < 5:
        need.append(0.0)
    pips = [float(x) for x in list(rp)[:5]]
    while len(pips) < 5:
        pips.append(0.0)
    abort = float(abort_h) if abort_h is not None else None

    s0 = cell_surplus_scalar(h0, need, pips, tr)
    if s0 < 0:
        h = h0
        s = s0
        aborted = False
        while h < float(max_h) - 1e-9 and s < 0:
            if abort is not None and h + 1e-9 >= abort and s < 0:
                aborted = True
                break
            h = round(h + 1.0, 1)
            s = cell_surplus_scalar(h, need, pips, tr)
            if abort is not None and h + 1e-9 >= abort and s < 0:
                aborted = True
                break
        return {
            "turns": float(h) if (s >= 0 and not aborted) else (
                float(abort) if aborted and abort is not None else float(max_h)
            ),
            "surplus": float(s),
            "start_h": h0,
            "start_surplus": float(s0),
            "direction": "up",
            "found": bool(s >= 0 and not aborted),
            "aborted": bool(aborted),
        }

    # S >= 0 at start: walk down to least H still >= 0
    h = h0
    s = s0
    last_ok = h
    last_s = s
    while h > float(min_h) + 1e-9:
        h_try = round(h - 1.0, 1)
        s_try = cell_surplus_scalar(h_try, need, pips, tr)
        if s_try < 0:
            break
        last_ok, last_s = h_try, s_try
        h = h_try
    return {
        "turns": float(last_ok),
        "surplus": float(last_s),
        "start_h": h0,
        "start_surplus": float(s0),
        "direction": "down",
        "found": True,
        "aborted": False,
    }


# Dice-roll anchors for H-dependent RP confidence (4p: H=2.5→10 rolls, H=15→60)
CONF_ROLLS_FULL_ADJUST = 10.0  # few rolls → apply full midpoint RP factor
CONF_ROLLS_NO_ADJUST = 60.0  # many rolls → factor 1.0 (mean already confident)
# "linear" (Test A) or "sqrt" (Test B — SE ~ 1/sqrt(n) fade)
CONF_RP_FADE_MODE = "sqrt"


def confidence_balance_factor(confidence_target: float) -> float:
    """Two-sided max factor between mean (1.0) and upper bar (1/target).

    Example target=0.85: mid=(1+1/0.85)/2 → RP 8.5→9.25 at *full* adjust.
    Actual apply strength is reduced when n_rolls is large (see
    ``confidence_rp_factor``).
    """
    t = float(confidence_target)
    if t <= 1e-12:
        return 1.0
    upper = 1.0 / t
    return (1.0 + upper) / 2.0


def confidence_rp_factor(
    confidence_target: float,
    n_rolls: float,
    *,
    n_full: float = CONF_ROLLS_FULL_ADJUST,
    n_none: float = CONF_ROLLS_NO_ADJUST,
    mode: Optional[str] = None,
) -> float:
    """RP scale depending on dice rolls until horizon.

    - n_rolls <= n_full (~10): full midpoint factor (end-game / short H)
    - n_rolls >= n_none (~60): 1.0 — no adjust (long horizon, mean already confident)
    - in between:
        * linear: weight (n_none - n) / (n_none - n_full)
        * sqrt: weight from 1/sqrt(n) normalized so n_full→1, n_none→0
          (matches CI margin ~ 1/sqrt(n))

    n_rolls ≈ H * num_players (own turns × rolls per own turn).
    """
    f_max = confidence_balance_factor(confidence_target)
    n = max(0.0, float(n_rolls))
    lo = float(n_full)
    hi = float(n_none)
    if hi <= lo + 1e-12:
        return f_max
    if n <= lo:
        return f_max
    if n >= hi:
        return 1.0

    fade = str(mode or CONF_RP_FADE_MODE or "sqrt").strip().lower()
    if fade == "linear":
        w = (hi - n) / (hi - lo)
    else:
        # Normalize 1/sqrt(n): at lo → 1, at hi → 0
        s_lo = 1.0 / math.sqrt(lo)
        s_hi = 1.0 / math.sqrt(hi)
        s_n = 1.0 / math.sqrt(n)
        denom = s_lo - s_hi
        w = (s_n - s_hi) / denom if abs(denom) > 1e-12 else 0.0
        w = max(0.0, min(1.0, w))
    return 1.0 + (f_max - 1.0) * w


def scale_rp_for_confidence(
    rp: Sequence[float],
    confidence_target: float,
    *,
    n_rolls: Optional[float] = None,
    num_players: int = 4,
    horizon: Optional[float] = None,
) -> List[float]:
    """Scale RP by H-dependent confidence factor.

    If ``n_rolls`` omitted, uses ``horizon * num_players`` when horizon given,
    else full midpoint factor (legacy).
    """
    if n_rolls is None:
        if horizon is not None:
            n_rolls = float(horizon) * max(1, int(num_players))
        else:
            n_rolls = CONF_ROLLS_FULL_ADJUST
    f = confidence_rp_factor(confidence_target, float(n_rolls))
    out = [max(0.0, float(x) * f) for x in list(rp)[:5]]
    while len(out) < 5:
        out.append(0.0)
    return out


def scale_remtr_for_confidence(
    trcards: Sequence[float],
    confidence_target: float,
) -> List[float]:
    """Deprecated helper: full upper RemTR/target (8.5→10). Prefer RP balance."""
    t = float(confidence_target)
    if t <= 1e-12:
        t = 1.0
    out = [max(0.0, float(x) / t) for x in list(trcards)[:5]]
    while len(out) < 5:
        out.append(0.0)
    return out


def side_with_confidence(
    trcards: Sequence[float],
    rp: Sequence[float],
    tr: Union[float, Sequence[float]],
    *,
    phase: str = "mid",
    start_h: Optional[float] = None,
    min_h: float = DEFAULT_MIN_TURNS,
    max_h: float = DEFAULT_MAX_TURNS,
    require_confidence: bool = True,
    confidence_target: Optional[float] = None,
    num_players: Optional[int] = None,
    abort_h: Optional[float] = None,
) -> Dict[str, Any]:
    """Side = walk with H-dependent RP confidence scale; Raw = unscaled RP.

    1) Walk Raw on true RP → H_raw, n_rolls = H_raw * num_players
    2) factor(n): full midpoint at ~10 rolls, → 1.0 by ~60 rolls
    3) RP_eff = RP * factor; walk again → Side

    End-game (few rolls) keeps adjustment; long horizons need little/none.
    """
    conf_target = confidence_target
    if conf_target is None:
        try:
            from core.constants import EXPECTED_HAND_CONFIDENCE_TARGET

            conf_target = float(EXPECTED_HAND_CONFIDENCE_TARGET)
        except Exception:
            conf_target = 0.85

    n_players = num_players
    if n_players is None:
        try:
            from core.constants import EXPECTED_HAND_ROLLS_PER_PLAYER_TURN

            n_players = int(EXPECTED_HAND_ROLLS_PER_PLAYER_TURN)
        except Exception:
            n_players = 4
    n_players = max(1, int(n_players))

    need = [float(x) for x in list(trcards)[:5]]
    while len(need) < 5:
        need.append(0.0)
    pips = [float(x) for x in list(rp)[:5]]
    while len(pips) < 5:
        pips.append(0.0)

    walk_raw = walk_turns_v2(
        need,
        pips,
        tr,
        phase=phase,
        start_h=start_h,
        min_h=min_h,
        max_h=max_h,
        abort_h=abort_h,
    )
    side_raw = float(walk_raw["turns"])
    aborted = bool(walk_raw.get("aborted"))
    n_rolls = float(side_raw) * float(n_players)
    bal_max = confidence_balance_factor(float(conf_target))
    factor = confidence_rp_factor(float(conf_target), n_rolls)

    if aborted:
        walk = walk_raw
        side = side_raw
        rp_used = pips
    elif require_confidence and abs(factor - 1.0) > 1e-12:
        pips_eff = [max(0.0, float(x) * factor) for x in pips]
        walk = walk_turns_v2(
            need,
            pips_eff,
            tr,
            phase=phase,
            start_h=start_h,
            min_h=min_h,
            max_h=max_h,
            abort_h=abort_h,
        )
        side = float(walk["turns"])
        rp_used = pips_eff
        aborted = bool(walk.get("aborted"))
    else:
        walk = walk_raw
        side = side_raw
        rp_used = pips
        if not require_confidence:
            factor = 1.0

    conf_info: Dict[str, Any] = {}
    try:
        from core.resource_time_estimator import estimate_direct_confidence

        conf_info = estimate_direct_confidence(
            [0.0] * 5,
            need,
            pips,
            float(side),
            num_players=int(n_players),
            confidence_target=float(conf_target),
        )
    except Exception as exc:
        conf_info = {"confidence": None, "label": "error", "error": str(exc)}

    return {
        "side": float(side),
        "side_raw": side_raw,
        "confidence": conf_info.get("confidence"),
        "confidence_target": float(conf_target),
        "confidence_label": str(conf_info.get("label") or ""),
        "confidence_info": conf_info,
        "confidence_balance_factor": float(bal_max),
        "confidence_rp_factor": float(factor),
        "n_rolls": float(n_rolls),
        "rp_effective": rp_used,
        "need_effective": need,
        "walk": walk,
        "walk_raw": walk_raw,
        "require_confidence": bool(require_confidence),
        "confidence_mode": "rp_balance_by_rolls" if require_confidence else "off",
        "aborted": bool(aborted),
    }


def compute_sides_matrix(
    trcards: np.ndarray,
    rp: np.ndarray,
    tr: Union[float, Sequence[float], np.ndarray],
    *,
    phase: str = "mid",
    require_confidence: bool = True,
    confidence_target: Optional[float] = None,
) -> Dict[str, Any]:
    """Per (way, target) Side / SideRaw / confidence."""
    need = np.asarray(trcards, dtype=float)
    pips = np.asarray(rp, dtype=float)
    w_n, t_n = need.shape[0], pips.shape[0]
    rates = _as_tr_matrix(tr, t_n)
    side = np.full((w_n, t_n), np.nan)
    side_raw = np.full((w_n, t_n), np.nan)
    conf = np.full((w_n, t_n), np.nan)
    for wi in range(w_n):
        for ti in range(t_n):
            bag = side_with_confidence(
                need[wi],
                pips[ti],
                rates[ti],
                phase=phase,
                require_confidence=require_confidence,
                confidence_target=confidence_target,
            )
            side[wi, ti] = bag["side"]
            side_raw[wi, ti] = bag["side_raw"]
            conf[wi, ti] = bag["confidence"]
    return {
        "phase": phase,
        "start_h": phase_start_horizon(phase),
        "side": side,
        "side_raw": side_raw,
        "confidence": conf,
    }


# ── Residual A′ (Parts I–III + DC lock) ───────────────────────────────────────


def residual_trcards_v2(
    comp_rem: Mapping[str, int],
    *,
    rem_dcards: Optional[int] = None,
) -> np.ndarray:
    """Remaining typed cost: structure rem + rem_dcards * [1,1,0,0,1]."""
    from core.strategy_timing import strategy_cost_from_components

    def _n(m: Mapping[str, int], *keys: str) -> int:
        for k in keys:
            if k in m:
                return max(0, int(m[k]))
        return 0

    rem_s = _n(comp_rem, "new_settlements", "settlements")
    rem_c = _n(comp_rem, "city_upgrades", "cities")
    rem_r = _n(comp_rem, "roads")
    rem_d = (
        max(0, int(rem_dcards))
        if rem_dcards is not None
        else _n(comp_rem, "dev_cards", "dcards")
    )
    struct = strategy_cost_from_components(
        new_settlements=rem_s,
        city_upgrades=rem_c,
        roads=rem_r,
        dev_cards=0,
    )
    dc = tuple(float(c) * rem_d for c in DC_COST_VEC)
    out = np.asarray(struct, dtype=float) + np.asarray(dc, dtype=float)
    return np.maximum(0.0, out)


def residual_trcards_v2_detail(
    comp_rem: Mapping[str, int],
    *,
    rem_dcards: Optional[int] = None,
) -> Dict[str, Any]:
    from core.strategy_timing import strategy_cost_from_components

    def _n(m: Mapping[str, int], *keys: str) -> int:
        for k in keys:
            if k in m:
                return max(0, int(m[k]))
        return 0

    rem_s = _n(comp_rem, "new_settlements", "settlements")
    rem_c = _n(comp_rem, "city_upgrades", "cities")
    rem_r = _n(comp_rem, "roads")
    rem_d = (
        max(0, int(rem_dcards))
        if rem_dcards is not None
        else _n(comp_rem, "dev_cards", "dcards")
    )
    struct = np.asarray(
        strategy_cost_from_components(
            new_settlements=rem_s,
            city_upgrades=rem_c,
            roads=rem_r,
            dev_cards=0,
        ),
        dtype=float,
    )
    dc = np.asarray([float(c) * rem_d for c in DC_COST_VEC], dtype=float)
    residual = np.maximum(0.0, struct + dc)
    return {
        "residual": residual,
        "structure": struct,
        "dc_cost": dc,
        "rem_settlements": rem_s,
        "rem_cities": rem_c,
        "rem_roads": rem_r,
        "rem_dcards": rem_d,
        "dc_unit": list(DC_COST_VEC),
        "absolute": residual,  # for compare AbsTR column = remaining need
        "subtracted": np.zeros(5, dtype=float),
    }


def load_abs_trcards_from_csv(
    path: Optional[Union[str, Path]] = None,
) -> Tuple[np.ndarray, List[int]]:
    """Optional CSV Abs cross-check (not used as live RemTR in v2)."""
    if path is None:
        path = Path(__file__).resolve().parent.parent / "catan_142_ways_resource_requirements.csv"
    path = Path(path)
    way_ids: List[int] = []
    rows: List[List[float]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                wid = int(row.get("Way_ID") or row.get("way_id") or 0)
            except Exception:
                continue
            if wid <= 0:
                continue
            vec = [
                float(row.get("Wheat_Needed") or 0),
                float(row.get("Ore_Needed") or 0),
                float(row.get("Wood_Needed") or 0),
                float(row.get("Brick_Needed") or 0),
                float(row.get("Wool_Needed") or 0),
            ]
            way_ids.append(wid)
            rows.append(vec)
    return np.asarray(rows, dtype=float), way_ids


# Back-compat aliases used by old compare imports during transition
def residual_trcards_proposal_a(
    abs_vec: Sequence[float],
    *,
    comp_abs: Mapping[str, int],
    comp_rem: Mapping[str, int],
) -> np.ndarray:
    """Deprecated: redirects to residual_trcards_v2(comp_rem)."""
    return residual_trcards_v2(comp_rem)


def residual_trcards_proposal_a_detail(
    abs_vec: Sequence[float],
    *,
    comp_abs: Mapping[str, int],
    comp_rem: Mapping[str, int],
) -> Dict[str, Any]:
    detail = residual_trcards_v2_detail(comp_rem)
    detail["done_settlements"] = 0
    detail["done_cities"] = 0
    detail["done_roads"] = 0
    detail["done_dcards"] = 0
    detail["comp_abs"] = dict(comp_abs)
    detail["comp_rem"] = dict(comp_rem)
    return detail


__all__ = [
    "N_RES",
    "OWN_TURNS_PER_RP",
    "PHASE_START_H",
    "DC_COST_VEC",
    "phase_start_horizon",
    "horizon_grid",
    "mult_for_horizon",
    "floor_component",
    "cell_components_v2",
    "cell_surplus_scalar",
    "walk_turns_v2",
    "CONF_ROLLS_FULL_ADJUST",
    "CONF_ROLLS_NO_ADJUST",
    "confidence_balance_factor",
    "confidence_rp_factor",
    "scale_rp_for_confidence",
    "scale_remtr_for_confidence",
    "side_with_confidence",
    "compute_sides_matrix",
    "residual_trcards_v2",
    "residual_trcards_v2_detail",
    "load_abs_trcards_from_csv",
    "residual_trcards_proposal_a",
    "residual_trcards_proposal_a_detail",
]
