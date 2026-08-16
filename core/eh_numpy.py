"""P5: NumPy Expected-Hand kernels (single + batch).

Matches continuous-trading payability of ``resource_time_estimator`` for the
common strategy-rank path. Falls back to Python for integer-trade zero-turn
shortcut parity via the public estimator API.

Resource order: [Wheat, Ore, Wood, Brick, Sheep].
"""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, List, Optional, Sequence, Tuple

_EPS = 1e-9
INFINITE_TURNS = 9999.0

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except Exception:  # pragma: no cover
    np = None  # type: ignore
    NUMPY_AVAILABLE = False


def numpy_eh_available() -> bool:
    if not NUMPY_AVAILABLE:
        return False
    try:
        from core.constants import USE_NUMPY_EH

        return bool(USE_NUMPY_EH)
    except Exception:
        return True


def _as_f5(x: Sequence[Any]) -> "np.ndarray":
    a = np.asarray(list(x)[:5], dtype=np.float64)
    if a.shape[0] < 5:
        a = np.pad(a, (0, 5 - a.shape[0]))
    return a


def _as_i5(x: Sequence[Any], default: int = 4) -> "np.ndarray":
    vals = [max(1, int(float(v))) for v in list(x or [])[:5]]
    while len(vals) < 5:
        vals.append(default)
    return np.asarray(vals, dtype=np.float64)


def expected_hand_after_turns_np(
    hand: "np.ndarray",
    pips: "np.ndarray",
    turns: "np.ndarray",
    num_players: int,
) -> "np.ndarray":
    """
    hand, pips: (5,)
    turns: (T,) or scalar
    returns: (T, 5) or (5,)
    """
    factor = float(max(0, int(num_players))) / 36.0
    t = np.asarray(turns, dtype=np.float64)
    # expected_added = pips * turns * players / 36
    if t.ndim == 0:
        return hand + pips * (float(t) * factor)
    return hand[None, :] + pips[None, :] * (t[:, None] * factor)


def payability_continuous_np(
    hand: "np.ndarray",
    need: "np.ndarray",
    rates: "np.ndarray",
) -> Tuple["np.ndarray", "np.ndarray", "np.ndarray", "np.ndarray", "np.ndarray"]:
    """
    Continuous bank/port payability (same idea as compute_payability continuous).

    hand: (5,) or (N,5) or (T,5)
    need: broadcastable to hand
    rates: (5,)
    returns payable, short, surplus, trades_needed, trades_available
    """
    short = np.maximum(0.0, need - hand)
    surplus = np.maximum(0.0, hand - need)
    trades_needed = short.sum(axis=-1)
    rates_safe = np.maximum(rates, 1.0)
    trades_available = (surplus / rates_safe).sum(axis=-1)
    payable_direct = short.max(axis=-1) <= _EPS
    payable = payable_direct | (trades_available + _EPS >= trades_needed)
    return payable, short, surplus, trades_needed, trades_available


def _confidence_joint_np(
    hand: "np.ndarray",
    required: "np.ndarray",
    pips: "np.ndarray",
    turns: float,
    num_players: int,
) -> Tuple[float, List[float], List[int]]:
    """Binomial joint confidence (matches estimate_confidence_for_requirement spirit)."""
    from core.resource_time_estimator import (
        probability_at_least_k,
        true_probability_from_pips,
    )

    n_rolls = int(max(0, round(float(turns) * max(0, int(num_players)))))
    per: List[float] = []
    needed: List[int] = []
    for i in range(5):
        missing = max(0.0, float(required[i]) - float(hand[i]))
        k = int(ceil(missing - _EPS))
        needed.append(max(0, k))
        p = true_probability_from_pips(float(pips[i]))
        if k <= 0:
            per.append(1.0)
        else:
            per.append(float(probability_at_least_k(n_rolls, p, k)))
    active = [per[i] for i in range(5) if needed[i] > 0]
    if not active:
        return 1.0, per, needed
    joint = 1.0
    for v in active:
        joint *= max(0.0, min(1.0, v))
    return float(joint), per, needed


def _required_pretrade_continuous(
    hand: "np.ndarray",
    need: "np.ndarray",
    rates: "np.ndarray",
    imports_received: "np.ndarray",
    exports_used: "np.ndarray",
) -> "np.ndarray":
    return np.maximum(0.0, need - imports_received) + exports_used


def _allocate_continuous_np(
    short: "np.ndarray",
    surplus: "np.ndarray",
    rates: "np.ndarray",
) -> Tuple["np.ndarray", "np.ndarray"]:
    """Greedy continuous trade plan (single 5-vector)."""
    imports_received = np.zeros(5, dtype=np.float64)
    exports_used = np.zeros(5, dtype=np.float64)
    remaining = float(short.sum())
    if remaining <= _EPS:
        return imports_received, exports_used
    exporters = sorted(range(5), key=lambda i: (float(rates[i]), -float(surplus[i]), i))
    importers = [i for i in range(5) if short[i] > _EPS]
    for exp in exporters:
        if remaining <= _EPS:
            break
        if surplus[exp] <= _EPS:
            continue
        max_imp = float(surplus[exp] / max(rates[exp], 1.0))
        take = min(remaining, max_imp)
        if take <= _EPS:
            continue
        exports_used[exp] += take * rates[exp]
        remaining -= take
        left = take
        for imp in importers:
            if left <= _EPS:
                break
            still = max(0.0, short[imp] - imports_received[imp])
            if still <= _EPS:
                continue
            add = min(still, left)
            imports_received[imp] += add
            left -= add
    return imports_received, exports_used


def estimate_first_payable_turn_np(
    current_hand: Sequence[Any],
    production_pips: Sequence[Any],
    need: Sequence[Any],
    trade_rates: Sequence[Any],
    *,
    confidence_target: float = 0.85,
    num_players: int = 4,
    step: float = 0.25,
    max_turns: float = 60.0,
    continuous_trading: bool = True,
    require_confidence: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    NumPy single-vector EH search. Returns None if NumPy unavailable or
    continuous_trading is False (caller should use Python integer path).
    """
    if not NUMPY_AVAILABLE or not continuous_trading:
        return None

    hand = _as_f5(current_hand)
    pips = _as_f5(production_pips)
    need_v = _as_f5(need)
    rates = _as_i5(trade_rates)

    # Zero-turn integer shortcut: use Python payability for exact parity
    from core.resource_time_estimator import (
        compute_payability_with_trades,
        confidence_label,
    )

    zero_pay = compute_payability_with_trades(
        hand.tolist(), need_v.tolist(), [int(r) for r in rates], continuous=False
    )
    if bool(zero_pay.get("payable_direct")) or bool(zero_pay.get("payable_after_trades")):
        return {
            "turns": 0.0,
            "found": True,
            "confidence": 1.0,
            "confidence_target": float(confidence_target),
            "confidence_label": "exact",
            "expected_hand": tuple(float(x) for x in hand),
            "current_hand": tuple(float(x) for x in hand),
            "production_pips": tuple(float(x) for x in pips),
            "need": tuple(float(x) for x in need_v),
            "trade_rates": tuple(int(r) for r in rates),
            "payability": zero_pay,
            "confidence_info": {
                "confidence": 1.0,
                "label": "exact",
                "reason": "current_hand_payable_now_exact_integer_trades",
            },
            "zero_turn_shortcut": True,
            "zero_turn_reason": "current_hand_payable_now_exact_integer_trades",
            "estimator": "expected_hand_numpy",
        }

    step = max(0.01, float(step))
    max_turns = max(0.0, float(max_turns))
    confidence_target = float(confidence_target)
    iterations = int(ceil(max_turns / step)) + 1
    turns_grid = np.minimum(max_turns, np.round(np.arange(iterations + 1) * step, 10))
    hands = expected_hand_after_turns_np(hand, pips, turns_grid, num_players)  # (T,5)

    payable, _, _, _, _ = payability_continuous_np(hands, need_v[None, :], rates)

    # Fast path: no confidence gate — first payable index only
    if not require_confidence:
        idxs = np.flatnonzero(payable)
        if idxs.size > 0:
            idx = int(idxs[0])
            turns = float(turns_grid[idx])
            expected = hands[idx]
            short = np.maximum(0.0, need_v - expected)
            surplus = np.maximum(0.0, expected - need_v)
            return {
                "turns": turns,
                "found": True,
                "confidence": 1.0,
                "confidence_target": confidence_target,
                "confidence_label": "high",
                "expected_hand": tuple(float(x) for x in expected),
                "current_hand": tuple(float(x) for x in hand),
                "production_pips": tuple(float(x) for x in pips),
                "need": tuple(float(x) for x in need_v),
                "trade_rates": tuple(int(r) for r in rates),
                "payability": {
                    "payable_direct": bool(short.max() <= _EPS),
                    "payable_after_trades": True,
                    "short": tuple(float(x) for x in short),
                    "surplus": tuple(float(x) for x in surplus),
                    "trade_rates": tuple(int(r) for r in rates),
                    "trades_needed": float(short.sum()),
                    "trades_available": float((surplus / np.maximum(rates, 1.0)).sum()),
                    "continuous_trading": True,
                },
                "confidence_info": {"confidence": 1.0, "label": "high"},
                "zero_turn_shortcut": False,
                "estimator": "expected_hand_numpy",
            }
        expected = hands[-1]
        short = np.maximum(0.0, need_v - expected)
        return {
            "turns": INFINITE_TURNS,
            "found": False,
            "confidence": 0.0,
            "confidence_target": confidence_target,
            "confidence_label": "very_low",
            "expected_hand": tuple(float(x) for x in expected),
            "current_hand": tuple(float(x) for x in hand),
            "production_pips": tuple(float(x) for x in pips),
            "need": tuple(float(x) for x in need_v),
            "trade_rates": tuple(int(r) for r in rates),
            "payability": {
                "payable_after_trades": False,
                "short": tuple(float(x) for x in short),
                "continuous_trading": True,
            },
            "confidence_info": {"confidence": 0.0, "label": "very_low"},
            "zero_turn_shortcut": False,
            "estimator": "expected_hand_numpy",
        }

    # Confidence-gated: scan steps with trade plan + binomial confidence
    last_info: Dict[str, Any] = {}
    for idx in range(len(turns_grid)):
        turns = float(turns_grid[idx])
        expected = hands[idx]
        pay_ok = bool(payable[idx])
        short = np.maximum(0.0, need_v - expected)
        surplus = np.maximum(0.0, expected - need_v)
        imp, exp = _allocate_continuous_np(short, surplus, rates)
        required = _required_pretrade_continuous(expected, need_v, rates, imp, exp)
        payability = {
            "payable_direct": bool(short.max() <= _EPS),
            "payable_after_trades": pay_ok,
            "short": tuple(float(x) for x in short),
            "surplus": tuple(float(x) for x in surplus),
            "trade_rates": tuple(int(r) for r in rates),
            "trades_needed": float(short.sum()),
            "trades_available": float((surplus / np.maximum(rates, 1.0)).sum()),
            "imports_received": tuple(float(x) for x in imp),
            "exports_used": tuple(float(x) for x in exp),
            "required_pretrade_hand": tuple(float(x) for x in required),
            "continuous_trading": True,
        }
        conf, per, needed = _confidence_joint_np(hand, required, pips, turns, num_players)
        confident_enough = conf + _EPS >= confidence_target
        found = bool(pay_ok and confident_enough)
        last_info = {
            "turns": turns,
            "found": found,
            "confidence": conf,
            "confidence_target": confidence_target,
            "confidence_label": confidence_label(conf, confidence_target),
            "expected_hand": tuple(float(x) for x in expected),
            "current_hand": tuple(float(x) for x in hand),
            "production_pips": tuple(float(x) for x in pips),
            "need": tuple(float(x) for x in need_v),
            "trade_rates": tuple(int(r) for r in rates),
            "payability": payability,
            "confidence_info": {
                "confidence": conf,
                "label": confidence_label(conf, confidence_target),
                "per_resource_confidence": tuple(per),
                "needed_produced_cards": tuple(needed),
                "required_pretrade_hand": tuple(float(x) for x in required),
            },
            "zero_turn_shortcut": False,
            "estimator": "expected_hand_numpy",
        }
        if found:
            return last_info
        if turns >= max_turns - _EPS:
            break

    expected = hands[-1]
    short = np.maximum(0.0, need_v - expected)
    surplus = np.maximum(0.0, expected - need_v)
    imp, exp = _allocate_continuous_np(short, surplus, rates)
    required = _required_pretrade_continuous(expected, need_v, rates, imp, exp)
    conf, per, needed = _confidence_joint_np(hand, required, pips, max_turns, num_players)
    return {
        "turns": INFINITE_TURNS,
        "found": False,
        "confidence": conf,
        "confidence_target": confidence_target,
        "confidence_label": confidence_label(conf, confidence_target),
        "expected_hand": tuple(float(x) for x in expected),
        "current_hand": tuple(float(x) for x in hand),
        "production_pips": tuple(float(x) for x in pips),
        "need": tuple(float(x) for x in need_v),
        "trade_rates": tuple(int(r) for r in rates),
        "payability": {
            "payable_after_trades": False,
            "required_pretrade_hand": tuple(float(x) for x in required),
            "continuous_trading": True,
        },
        "confidence_info": {
            "confidence": conf,
            "label": confidence_label(conf, confidence_target),
            "per_resource_confidence": tuple(per),
            "needed_produced_cards": tuple(needed),
        },
        "last_checked": last_info,
        "zero_turn_shortcut": False,
        "estimator": "expected_hand_numpy",
    }


def estimate_first_payable_turn_batch_np(
    current_hand: Sequence[Any],
    production_pips: Sequence[Any],
    needs: Sequence[Sequence[Any]],
    trade_rates: Sequence[Any],
    *,
    confidence_target: float = 0.85,
    num_players: int = 4,
    step: float = 0.25,
    max_turns: float = 60.0,
    continuous_trading: bool = True,
    require_confidence: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """
    Batch EH for many need vectors sharing hand/pips/rates.

    Returns list of result dicts (same keys as single) or None if unavailable.
    """
    if not NUMPY_AVAILABLE or not continuous_trading:
        return None
    need_list = list(needs or [])
    if not need_list:
        return []

    # Fast path: vectorized first-payable without confidence gate
    if not require_confidence:
        hand = _as_f5(current_hand)
        pips = _as_f5(production_pips)
        rates = _as_i5(trade_rates)
        need_m = np.vstack([_as_f5(n) for n in need_list])  # (N,5)
        step = max(0.01, float(step))
        max_turns = max(0.0, float(max_turns))
        iterations = int(ceil(max_turns / step)) + 1
        turns_grid = np.minimum(max_turns, np.round(np.arange(iterations + 1) * step, 10))
        hands = expected_hand_after_turns_np(hand, pips, turns_grid, num_players)  # (T,5)

        # zero-turn integer for all needs via python once? use continuous at t=0 + int zero check
        from core.resource_time_estimator import compute_payability_with_trades, confidence_label

        results: List[Dict[str, Any]] = []
        n_needs = need_m.shape[0]
        found_at = np.full(n_needs, -1, dtype=np.int32)

        # Integer zero-turn
        for i in range(n_needs):
            zp = compute_payability_with_trades(
                hand.tolist(), need_m[i].tolist(), [int(r) for r in rates], continuous=False
            )
            if bool(zp.get("payable_direct")) or bool(zp.get("payable_after_trades")):
                found_at[i] = 0
                results.append(None)  # type: ignore
            else:
                results.append(None)  # type: ignore

        # Vectorized scan over steps for remaining
        pending = found_at < 0
        for t_idx, turns in enumerate(turns_grid):
            if not pending.any():
                break
            if t_idx == 0:
                # skip continuous t=0 if integer already handled; still check continuous for non-int-zero
                pass
            eh = hands[t_idx]  # (5,)
            # broadcast need pending
            pay, _, _, _, _ = payability_continuous_np(eh[None, :], need_m, rates)
            newly = pending & pay
            found_at[newly] = t_idx
            pending = found_at < 0
            if float(turns) >= max_turns - _EPS:
                break

        out: List[Dict[str, Any]] = []
        for i in range(n_needs):
            if found_at[i] == 0:
                # recompute integer zero result
                zp = compute_payability_with_trades(
                    hand.tolist(), need_m[i].tolist(), [int(r) for r in rates], continuous=False
                )
                if bool(zp.get("payable_direct")) or bool(zp.get("payable_after_trades")):
                    out.append({
                        "turns": 0.0,
                        "found": True,
                        "confidence": 1.0,
                        "confidence_target": float(confidence_target),
                        "confidence_label": "exact",
                        "expected_hand": tuple(float(x) for x in hand),
                        "need": tuple(float(x) for x in need_m[i]),
                        "payability": zp,
                        "zero_turn_shortcut": True,
                        "estimator": "expected_hand_numpy_batch",
                    })
                    continue
            if found_at[i] >= 0:
                t = float(turns_grid[found_at[i]])
                eh = hands[found_at[i]]
                short = np.maximum(0.0, need_m[i] - eh)
                surplus = np.maximum(0.0, eh - need_m[i])
                out.append({
                    "turns": t,
                    "found": True,
                    "confidence": 1.0,  # not evaluated when require_confidence=False
                    "confidence_target": float(confidence_target),
                    "confidence_label": "high",
                    "expected_hand": tuple(float(x) for x in eh),
                    "need": tuple(float(x) for x in need_m[i]),
                    "payability": {
                        "payable_after_trades": True,
                        "short": tuple(float(x) for x in short),
                        "surplus": tuple(float(x) for x in surplus),
                        "continuous_trading": True,
                    },
                    "zero_turn_shortcut": False,
                    "estimator": "expected_hand_numpy_batch",
                })
            else:
                eh = hands[-1]
                out.append({
                    "turns": INFINITE_TURNS,
                    "found": False,
                    "confidence": 0.0,
                    "confidence_target": float(confidence_target),
                    "confidence_label": "very_low",
                    "expected_hand": tuple(float(x) for x in eh),
                    "need": tuple(float(x) for x in need_m[i]),
                    "payability": {"payable_after_trades": False, "continuous_trading": True},
                    "zero_turn_shortcut": False,
                    "estimator": "expected_hand_numpy_batch",
                })
        return out

    # require_confidence: fall back to single np loop per need
    out2: List[Dict[str, Any]] = []
    for need in need_list:
        r = estimate_first_payable_turn_np(
            current_hand,
            production_pips,
            need,
            trade_rates,
            confidence_target=confidence_target,
            num_players=num_players,
            step=step,
            max_turns=max_turns,
            continuous_trading=continuous_trading,
            require_confidence=require_confidence,
        )
        if r is None:
            return None
        out2.append(r)
    return out2
