"""Cheap S142 pruning: Pareto RemTR, dedupe, mass bottleneck LB, walk abort.

Within one PLN2 target, RP and TR are shared by all ways — only RemTR differs.
So need_j >= need_i (elementwise, strict somewhere) ⇒ Side(j) >= Side(i).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def need_key(need: Sequence[float], ndigits: int = 3) -> Tuple[float, ...]:
    arr = [float(x) for x in list(need)[:5]]
    while len(arr) < 5:
        arr.append(0.0)
    return tuple(round(x, ndigits) for x in arr)


def tr_key(tr: Sequence[float], ndigits: int = 3) -> Tuple[float, ...]:
    arr = [float(x) for x in list(tr)[:5]]
    while len(arr) < 5:
        arr.append(4.0)
    return tuple(round(x, ndigits) for x in arr)


def dominates_need(
    need_i: Sequence[float],
    need_j: Sequence[float],
    *,
    tr_i: Optional[Sequence[float]] = None,
    tr_j: Optional[Sequence[float]] = None,
) -> bool:
    """True if i dominates j (j can be pruned): need_j >= need_i, TR_j >= TR_i.

    When TR omitted (same target), only RemTR Pareto is required.
    """
    a = [float(x) for x in list(need_i)[:5]]
    b = [float(x) for x in list(need_j)[:5]]
    while len(a) < 5:
        a.append(0.0)
    while len(b) < 5:
        b.append(0.0)
    if any(b[r] + 1e-12 < a[r] for r in range(5)):
        return False
    if all(abs(b[r] - a[r]) < 1e-12 for r in range(5)):
        return False  # equal → dedupe, not dominate
    if tr_i is not None and tr_j is not None:
        ti = [float(x) for x in list(tr_i)[:5]]
        tj = [float(x) for x in list(tr_j)[:5]]
        while len(ti) < 5:
            ti.append(4.0)
        while len(tj) < 5:
            tj.append(4.0)
        # Higher TR = worse conversion; j dominated only if tj >= ti
        if any(tj[r] + 1e-12 < ti[r] for r in range(5)):
            return False
    return True


def pareto_prune_ways(
    items: Sequence[Tuple[int, Sequence[float]]],
    *,
    tr: Optional[Sequence[float]] = None,
) -> Tuple[List[Tuple[int, List[float]]], int]:
    """Keep non-dominated (wid, need) pairs. Returns (kept, n_pruned)."""
    prepared: List[Tuple[int, List[float]]] = []
    for wid, need in items:
        arr = [float(x) for x in list(need)[:5]]
        while len(arr) < 5:
            arr.append(0.0)
        prepared.append((int(wid), arr))

    kept: List[Tuple[int, List[float]]] = []
    pruned = 0
    for wid_j, need_j in prepared:
        dominated = False
        for wid_i, need_i in prepared:
            if wid_i == wid_j:
                continue
            if dominates_need(need_i, need_j, tr_i=tr, tr_j=tr):
                dominated = True
                break
        if dominated:
            pruned += 1
        else:
            kept.append((wid_j, need_j))
    return kept, pruned


def mass_bottleneck_lb(
    need: Sequence[float],
    rp: Sequence[float],
    *,
    min_h: float = 0.0,
) -> float:
    """Weak valid LB: total cards / total pips (trade can only help mass balance).

    H >= 9 * sum(need) / sum(rp) when sum(rp) > 0.
    """
    n = [max(0.0, float(x)) for x in list(need)[:5]]
    while len(n) < 5:
        n.append(0.0)
    p = [max(0.0, float(x)) for x in list(rp)[:5]]
    while len(p) < 5:
        p.append(0.0)
    sn = sum(n)
    sp = sum(p)
    if sn <= 1e-12:
        return float(min_h)
    if sp <= 1e-12:
        return 1e9
    return max(float(min_h), 9.0 * sn / sp)


def per_resource_prod_ub(
    need: Sequence[float],
    rp: Sequence[float],
) -> float:
    """No-trade horizon (upper bound on Side). Useful for dig, not for prune."""
    n = [max(0.0, float(x)) for x in list(need)[:5]]
    p = [max(0.0, float(x)) for x in list(rp)[:5]]
    while len(n) < 5:
        n.append(0.0)
    while len(p) < 5:
        p.append(0.0)
    worst = 0.0
    for r in range(5):
        if n[r] <= 1e-12:
            continue
        if p[r] <= 1e-12:
            return 1e9
        worst = max(worst, 9.0 * n[r] / p[r])
    return worst


__all__ = [
    "need_key",
    "tr_key",
    "dominates_need",
    "pareto_prune_ways",
    "mass_bottleneck_lb",
    "per_resource_prod_ub",
]
