"""Sidestep-only board ↔ 142-way sync + S142 (observe-only).

Embeds the **full** playboard sync predicate used by live SE
(``can_realize_way`` / Way_board_sync plan) **inside Sidestep**.

- Does **not** change live L2, sticky, ``maybe_force_board_fit``, or portfolio.
- Calls ``strategy_board_fit`` / ``strategy_way_residual`` as **read-only**
  helpers; Sidestep owns when/how the filter is applied for Side / S142.

S142 = argmin over sync-fit ways of (min Side over PLN2 catalog targets),
using the **identical** ``side_with_confidence`` walk as PLN2 Side columns.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.sidestep_eta_matrix import (
    load_abs_trcards_from_csv,
    residual_trcards_v2_detail,
    side_with_confidence,
)


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


def all_way_ids() -> List[int]:
    """Way IDs from the 142 CSV (Sidestep enumeration)."""
    try:
        _, ids = load_abs_trcards_from_csv()
        return [int(x) for x in ids if int(x) > 0]
    except Exception:
        return list(range(1, 143))


def evaluate_sidestep_way_sync(
    way_id: Any,
    player: Any,
    game: Any = None,
    *,
    allow_ignored_specials: Any = None,
) -> Dict[str, Any]:
    """Full sync check for one way (Sidestep wrapper; live code unchanged)."""
    from core.strategy_board_fit import can_realize_way

    return can_realize_way(
        way_id,
        player,
        game=game,
        allow_ignored_specials=allow_ignored_specials,
    )


def _way_passes(result: Mapping[str, Any]) -> bool:
    return bool(result.get("soft") or result.get("fit"))


def select_sync_fit_ways(
    game: Any,
    player: Any,
    *,
    way_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Return sync-fit way ids under the normative board-sync model.

    1. Strict ``can_realize_way`` (buildings, held LA/LR, VP, LA/LR feasibility).
    2. If **no** strict fits and seat has give-up LA/LR → carve-out re-score
       (same rule as live portfolio filter; buildings+VP never waived).
    3. Soft/unknown ways count as fit (predicate contract).
    """
    from core.strategy_board_fit import ignored_specials_from_player

    ids = [int(x) for x in (way_ids if way_ids is not None else all_way_ids())]
    out: Dict[str, Any] = {
        "ok": True,
        "n_total": len(ids),
        "fit_way_ids": [],
        "unfit_way_ids": [],
        "n_fit": 0,
        "n_unfit": 0,
        "giveup_carve_out": False,
        "ignored_specials": [],
        "all_unfit": False,
        "by_way": {},
    }
    if player is None:
        out["ok"] = False
        out["error"] = "no_player"
        return out

    strict_fit: List[int] = []
    strict_unfit: List[int] = []
    by_way: Dict[int, Dict[str, Any]] = {}
    for wid in ids:
        r = evaluate_sidestep_way_sync(wid, player, game, allow_ignored_specials=None)
        by_way[wid] = dict(r)
        if _way_passes(r):
            strict_fit.append(wid)
        else:
            strict_unfit.append(wid)

    fit_ids = list(strict_fit)
    unfit_ids = list(strict_unfit)
    carve = ignored_specials_from_player(player)
    if unfit_ids and not fit_ids and carve:
        out["giveup_carve_out"] = True
        out["ignored_specials"] = sorted(carve)
        fit_ids = []
        unfit_ids = []
        by_way = {}
        for wid in ids:
            r = evaluate_sidestep_way_sync(
                wid, player, game, allow_ignored_specials=carve
            )
            r = dict(r)
            r["giveup_carve_out"] = True
            by_way[wid] = r
            if _way_passes(r):
                fit_ids.append(wid)
            else:
                unfit_ids.append(wid)

    out["fit_way_ids"] = fit_ids
    out["unfit_way_ids"] = unfit_ids
    out["n_fit"] = len(fit_ids)
    out["n_unfit"] = len(unfit_ids)
    out["all_unfit"] = bool(unfit_ids and not fit_ids)
    out["by_way"] = by_way
    return out


def sticky_way_sync_status(
    way_id: Any,
    player: Any,
    game: Any = None,
) -> Dict[str, Any]:
    """Sync status for the seat's sticky/preferred way (dig header)."""
    from core.strategy_board_fit import ignored_specials_from_player

    wid = _safe_int(way_id, None)
    bag: Dict[str, Any] = {
        "way_id": wid,
        "fit": True,
        "soft": False,
        "reasons": [],
        "giveup_carve_out": False,
        "label": "no_way",
    }
    if wid is None or wid <= 0:
        return bag
    r = evaluate_sidestep_way_sync(wid, player, game, allow_ignored_specials=None)
    if _way_passes(r):
        bag.update(
            {
                "fit": bool(r.get("fit")),
                "soft": bool(r.get("soft")),
                "reasons": list(r.get("reasons") or []),
                "label": "FIT" if r.get("fit") else "SOFT",
            }
        )
        return bag
    carve = ignored_specials_from_player(player)
    if carve:
        r2 = evaluate_sidestep_way_sync(
            wid, player, game, allow_ignored_specials=carve
        )
        if _way_passes(r2):
            bag.update(
                {
                    "fit": bool(r2.get("fit")),
                    "soft": bool(r2.get("soft")),
                    "reasons": list(r2.get("reasons") or []),
                    "giveup_carve_out": True,
                    "ignored_specials": sorted(carve),
                    "label": "FIT_CARVE",
                }
            )
            return bag
    bag.update(
        {
            "fit": False,
            "soft": False,
            "reasons": list(r.get("reasons") or []),
            "label": "UNFIT",
        }
    )
    return bag


def _comp_rem_for_way(
    way_id: int,
    player: Any,
    board: Any,
) -> Dict[str, int]:
    try:
        from core.strategy_way_residual import compute_way_residual

        res = compute_way_residual(way_id, player, preferred={}, board=board)
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
) -> Tuple[List[float], List[float]]:
    """Same RP_after / TR definition as ``sidestep_compare._rp_tr_after_target``."""
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
    return rp, rates


def compute_s142(
    game: Any,
    player: Any,
    *,
    catalog: Sequence[Mapping[str, Any]],
    phase: str,
    require_confidence: bool = True,
    fit_pack: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Least Side among **sync-fit** ways vs PLN2 catalog targets.

    Side math is identical to PLN2 compare columns (``side_with_confidence``,
    RemTR after claiming the catalog target, RP_after = current + gain).
    Unfit ways are never scored.

    Pruning (same RP/TR per target): RemTR Pareto, need dedupe, mass LB,
    walk abort when H cannot beat best Side so far.
    """
    from core.sidestep_s142_prune import (
        mass_bottleneck_lb,
        need_key,
        pareto_prune_ways,
    )

    board = getattr(game, "board", None) if game is not None else None
    pack = dict(fit_pack) if isinstance(fit_pack, Mapping) else select_sync_fit_ways(
        game, player
    )
    fit_ids = [int(x) for x in list(pack.get("fit_way_ids") or [])]
    rows_cat = [r for r in list(catalog or []) if _safe_int(r.get("id"), 0)]
    prune_stats = {
        "pareto": 0,
        "dedupe": 0,
        "lb": 0,
        "aborted": 0,
        "walked": 0,
        "cells": 0,
    }
    out: Dict[str, Any] = {
        "ok": True,
        "s142_way_id": None,
        "s142_side": None,
        "s142_side_raw": None,
        "s142_target": None,
        "s142_kind": None,
        "n_fit": len(fit_ids),
        "n_scored": 0,
        "giveup_carve_out": bool(pack.get("giveup_carve_out")),
        "per_way": [],
        "prune": prune_stats,
        "sync": {
            "n_total": pack.get("n_total"),
            "n_fit": pack.get("n_fit"),
            "n_unfit": pack.get("n_unfit"),
            "all_unfit": pack.get("all_unfit"),
            "giveup_carve_out": pack.get("giveup_carve_out"),
            "ignored_specials": list(pack.get("ignored_specials") or []),
        },
    }
    if not fit_ids:
        out["ok"] = False
        out["error"] = "no_sync_fit_ways"
        return out
    if not rows_cat or board is None:
        out["ok"] = False
        out["error"] = "no_pln2_targets_or_board"
        return out

    # Precompute rem0 per way (shared across targets)
    rem0_by_way: Dict[int, Dict[str, int]] = {
        wid: _comp_rem_for_way(wid, player, board) for wid in fit_ids
    }

    best_way: Optional[int] = None
    best_side: Optional[float] = None
    best_raw: Optional[float] = None
    best_tgt: Optional[str] = None
    best_kind: Optional[str] = None
    # Best Side per way across targets
    way_best: Dict[int, Dict[str, Any]] = {}

    for r in rows_cat:
        kind = str(r.get("kind") or "S").upper()
        tid = _safe_int(r.get("id"), 0) or 0
        if tid <= 0:
            continue
        try:
            rp, tr = _rp_tr_after_target(board, player, kind=kind, tid=tid)
        except Exception:
            continue
        lab = str(r.get("label") or (f"C{tid}" if kind == "C" else f"S{tid}"))

        # Build (wid, need) for this target
        items: List[Tuple[int, List[float]]] = []
        for wid in fit_ids:
            rem = _adjust_rem_for_target(rem0_by_way[wid], kind)
            detail = residual_trcards_v2_detail(rem)
            need = [float(x) for x in detail["residual"]]
            items.append((wid, need))
            prune_stats["cells"] += 1

        kept, n_pareto = pareto_prune_ways(items, tr=tr)
        prune_stats["pareto"] += int(n_pareto)

        # Dedupe identical RemTR → one walk, fan out to all ways with that need
        groups: Dict[Tuple[float, ...], List[Tuple[int, List[float]]]] = {}
        for wid, need in kept:
            groups.setdefault(need_key(need), []).append((wid, need))
        prune_stats["dedupe"] += max(0, len(kept) - len(groups))

        # Order groups by mass LB (cheapest first)
        ordered = []
        for key, members in groups.items():
            need0 = members[0][1]
            lb = mass_bottleneck_lb(need0, rp)
            ordered.append((lb, key, members, need0))
        ordered.sort(key=lambda x: (float(x[0]), x[1]))

        for lb, _key, members, need0 in ordered:
            if best_side is not None and lb >= float(best_side) - 1e-12:
                prune_stats["lb"] += len(members)
                continue
            abort_h = best_side
            side_bag = side_with_confidence(
                need0,
                rp,
                tr,
                phase=phase,
                require_confidence=require_confidence,
                abort_h=abort_h,
            )
            prune_stats["walked"] += 1
            if side_bag.get("aborted"):
                prune_stats["aborted"] += 1
                continue
            side = _safe_float(side_bag.get("side"))
            raw = _safe_float(side_bag.get("side_raw"))
            if side is None:
                continue
            for wid, _need in members:
                prev = way_best.get(wid)
                if prev is None or side < float(prev["side"]):
                    way_best[wid] = {
                        "side": side,
                        "side_raw": raw,
                        "target": lab,
                        "kind": kind,
                    }
                if best_side is None or side < best_side:
                    best_side = side
                    best_raw = raw
                    best_way = wid
                    best_tgt = lab
                    best_kind = kind

    per_way: List[Dict[str, Any]] = []
    for wid, bag in way_best.items():
        per_way.append(
            {
                "way_id": wid,
                "side": bag["side"],
                "side_raw": bag["side_raw"],
                "target": bag["target"],
                "kind": bag["kind"],
            }
        )
        out["n_scored"] += 1
    per_way.sort(key=lambda x: (float(x["side"]), int(x["way_id"])))
    out["per_way"] = per_way[:12]
    out["s142_way_id"] = best_way
    out["s142_side"] = best_side
    out["s142_side_raw"] = best_raw
    out["s142_target"] = best_tgt
    out["s142_kind"] = best_kind
    out["prune"] = prune_stats
    if best_way is None:
        out["ok"] = False
        out["error"] = "no_side_scores"
    return out


def build_seat_sync_and_s142(
    game: Any,
    player: Any,
    *,
    sticky_way_id: Any,
    catalog: Sequence[Mapping[str, Any]],
    phase: str,
    require_confidence: bool = True,
) -> Dict[str, Any]:
    """One-shot Sidestep sync filter + S142 for a seat."""
    fit_pack = select_sync_fit_ways(game, player)
    sticky = sticky_way_sync_status(sticky_way_id, player, game)
    s142 = compute_s142(
        game,
        player,
        catalog=catalog,
        phase=phase,
        require_confidence=require_confidence,
        fit_pack=fit_pack,
    )
    return {
        "sticky_sync": sticky,
        "sync": fit_pack,
        "s142": s142,
        "fit_way_ids": list(fit_pack.get("fit_way_ids") or []),
        "n_fit": int(fit_pack.get("n_fit") or 0),
        "n_total": int(fit_pack.get("n_total") or 0),
    }


__all__ = [
    "all_way_ids",
    "evaluate_sidestep_way_sync",
    "select_sync_fit_ways",
    "sticky_way_sync_status",
    "compute_s142",
    "build_seat_sync_and_s142",
]
