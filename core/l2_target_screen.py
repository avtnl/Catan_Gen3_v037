"""Phase R/P: simple RP / RemTR / bottleneck / TR target screen.

Modes (``L2_TARGET_SCREEN`` / ``game.l2_target_screen``):
  - ``off`` — no-op
  - ``mark_only`` — annotate hopeless / Pareto-dom; keep combo pool
  - ``prune`` — drop annotated targets before EH combo (safety floor)

See ``docs/L2_target_screen_research_R.md`` and Phase P plan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_EPS = 1e-12
N_RES = 5
_VALID_MODES = frozenset({"off", "mark_only", "prune"})


def _vec5(x: Sequence[Any]) -> List[float]:
    out = [max(0.0, float(v)) for v in list(x)[:5]]
    while len(out) < 5:
        out.append(0.0)
    return out


def bottleneck_resource(
    need: Sequence[float],
    rp: Sequence[float],
) -> Tuple[int, float]:
    """r* = argmax need_r / max(rp_r, eps); returns (index, ratio)."""
    n = _vec5(need)
    p = _vec5(rp)
    best_i = 0
    best_r = -1.0
    for i in range(N_RES):
        ratio = n[i] / max(p[i], _EPS)
        if ratio > best_r:
            best_r = ratio
            best_i = i
    return best_i, float(best_r)


def per_resource_ub(need: Sequence[float], rp: Sequence[float]) -> float:
    """No-trade horizon UB: max_r 9*need_r/rp_r (inf if need>0 and rp=0)."""
    n = _vec5(need)
    p = _vec5(rp)
    worst = 0.0
    for i in range(N_RES):
        if n[i] <= _EPS:
            continue
        if p[i] <= _EPS:
            return 1e9
        worst = max(worst, 9.0 * n[i] / p[i])
    return float(worst)


def mass_lb(need: Sequence[float], rp: Sequence[float], *, min_h: float = 0.0) -> float:
    n = _vec5(need)
    p = _vec5(rp)
    sn = sum(n)
    sp = sum(p)
    if sn <= _EPS:
        return float(min_h)
    if sp <= _EPS:
        return 1e9
    return max(float(min_h), 9.0 * sn / sp)


def target_screen_at_H(
    need: Sequence[float],
    rp_after: Sequence[float],
    rates: Sequence[float],
    H: float,
) -> Dict[str, Any]:
    """Fixed-H screen: short vs tradeable surplus at port rates.

    Same spirit as EH continuous trade step, evaluated at one horizon only.
    """
    n = _vec5(need)
    p = _vec5(rp_after)
    rates_v = _vec5(rates)
    for i in range(N_RES):
        rates_v[i] = max(2.0, float(rates_v[i] or 4.0))
    H = max(0.0, float(H))
    mult = H / 9.0
    credit = [p[i] * mult for i in range(N_RES)]
    short = [max(0.0, n[i] - credit[i]) for i in range(N_RES)]
    surplus = [max(0.0, credit[i] - n[i]) for i in range(N_RES)]
    tradeable = sum(surplus[i] / rates_v[i] for i in range(N_RES))
    short_sum = sum(short)
    ok = short_sum <= tradeable + 1e-9
    r_star, ratio = bottleneck_resource(n, p)
    return {
        "ok": bool(ok),
        "H": float(H),
        "short": tuple(short),
        "surplus": tuple(surplus),
        "short_sum": float(short_sum),
        "tradeable": float(tradeable),
        "bottleneck": int(r_star),
        "bottleneck_ratio": float(ratio),
        "per_resource_ub": per_resource_ub(n, p),
        "mass_lb": mass_lb(n, p, min_h=0.0),
        "reason": "ok" if ok else "hopeless_at_H",
    }


def target_is_inferior(
    need_a: Sequence[float],
    rp_a: Sequence[float],
    need_b: Sequence[float],
    rp_b: Sequence[float],
) -> bool:
    """Pareto: A inferior to B if need_A >= need_B and rp_A <= rp_B (strict somewhere)."""
    na, pa = _vec5(need_a), _vec5(rp_a)
    nb, pb = _vec5(need_b), _vec5(rp_b)
    ge_need = all(na[i] >= nb[i] - 1e-9 for i in range(N_RES))
    le_rp = all(pa[i] <= pb[i] + 1e-9 for i in range(N_RES))
    strict = any(na[i] > nb[i] + 1e-9 for i in range(N_RES)) or any(
        pa[i] < pb[i] - 1e-9 for i in range(N_RES)
    )
    return bool(ge_need and le_rp and strict)


def screen_target_pair(
    need: Sequence[float],
    rp_after: Sequence[float],
    rates: Sequence[float],
    *,
    horizons: Sequence[float] = (9.0, 18.0, 27.0),
) -> Dict[str, Any]:
    """Run fixed-H screens; hopeless if failing the largest H that is still finite-UB relevant."""
    screens = [target_screen_at_H(need, rp_after, rates, H) for H in horizons]
    # Prefer mid then early then late for dig
    primary = screens[1] if len(screens) > 1 else screens[0]
    # Hopeless if fails at H=27 (or max horizon) when UB is finite
    worst = screens[-1] if screens else primary
    hopeless = not bool(worst.get("ok"))
    return {
        "hopeless": bool(hopeless),
        "primary": primary,
        "screens": screens,
        "per_resource_ub": primary.get("per_resource_ub"),
        "mass_lb": primary.get("mass_lb"),
        "bottleneck": primary.get("bottleneck"),
        "reason": "hopeless_at_H" if hopeless else "ok",
    }


def l2_target_screen_mode(game: Any = None) -> str:
    """Return ``off`` | ``mark_only`` | ``prune``."""
    raw = None
    if game is not None:
        try:
            raw = getattr(game, "l2_target_screen", None)
        except Exception:
            raw = None
    if raw is None or str(raw).strip() == "":
        try:
            from core import constants as C

            raw = getattr(C, "L2_TARGET_SCREEN", "off")
        except Exception:
            raw = "off"
    mode = str(raw or "off").strip().lower()
    if mode in ("false", "0", "no", ""):
        return "off"
    if mode in ("true", "1", "yes", "on"):
        return "mark_only"
    if mode not in _VALID_MODES:
        return "off"
    return mode


def remtr_need_after_target(
    game: Any,
    player: Any,
    way_id: int,
    kind: str = "S",
) -> List[float]:
    """5-vector RemTR need after claiming one S/C (same as R2 harness)."""
    from core.sidestep_board_sync import _adjust_rem_for_target, _comp_rem_for_way
    from core.sidestep_eta_matrix import residual_trcards_v2_detail

    board = getattr(game, "board", None) if game is not None else None
    rem0 = _comp_rem_for_way(int(way_id), player, board)
    rem = _adjust_rem_for_target(rem0, kind)
    detail = residual_trcards_v2_detail(rem)
    return [float(x) for x in detail["residual"]]


def _target_id_of(cand: Any) -> Optional[int]:
    if cand is None:
        return None
    if isinstance(cand, Mapping):
        for k in ("target_id", "id", "tid"):
            try:
                v = int(cand.get(k))
                if v > 0:
                    return v
            except Exception:
                continue
        return None
    try:
        v = int(getattr(cand, "target_id", 0) or 0)
        return v if v > 0 else None
    except Exception:
        return None


def _kind_of(cand: Any, default: str = "S") -> str:
    if isinstance(cand, Mapping):
        k = str(cand.get("kind") or default)
    else:
        k = str(getattr(cand, "kind", default) or default)
    k = k.strip().upper()
    if k.startswith("C") or "CITY" in k:
        return "C"
    return "S"


def screen_portfolio_targets(
    game: Any,
    player: Any,
    candidates: Sequence[Any],
    *,
    way_id: int,
    requirements: Any = None,
    default_kind: str = "S",
    stash: bool = True,
) -> Dict[str, Any]:
    """Screen settle/city candidates for one way.

    Returns::
        {
          mode, applied, kept, inferior, dropped, by_id,
          floor, way_id
        }

    ``kept`` is the list to pass to combo EH (all candidates in mark_only/off).
    When ``stash`` is False, do not overwrite ``game._last_l2_target_screen``.
    """
    mode = l2_target_screen_mode(game)
    cands = list(candidates or [])
    meta: Dict[str, Any] = {
        "mode": mode,
        "applied": False,
        "kept": cands,
        "inferior": [],
        "dropped": [],
        "by_id": {},
        "floor": 1,
        "way_id": int(way_id) if way_id else 0,
        "reason": "off" if mode == "off" else "ok",
    }
    if mode == "off" or not cands or player is None or game is None:
        return meta
    try:
        wid = int(way_id)
    except Exception:
        meta["reason"] = "bad_way_id"
        return meta
    if wid <= 0:
        meta["reason"] = "no_way_id"
        return meta

    floor = 1
    try:
        if requirements is not None:
            floor = max(
                1, int(getattr(requirements, "required_new_intersections", 0) or 0)
            )
    except Exception:
        floor = 1
    # Never require more than available
    floor = max(1, min(floor, len(cands)))
    meta["floor"] = int(floor)

    board = getattr(game, "board", None)
    if board is None:
        meta["reason"] = "no_board"
        return meta

    from core.sidestep_board_sync import _rp_tr_after_target

    # Precompute need per kind (S vs C) — same RemTR for all same-kind targets
    need_by_kind: Dict[str, List[float]] = {}
    vectors: Dict[int, Dict[str, Any]] = {}
    ordered: List[Tuple[Any, int, str]] = []

    for cand in cands:
        tid = _target_id_of(cand)
        if tid is None:
            continue
        kind = _kind_of(cand, default_kind)
        if kind not in need_by_kind:
            try:
                need_by_kind[kind] = remtr_need_after_target(game, player, wid, kind)
            except Exception:
                need_by_kind[kind] = [0.0] * 5
        need = need_by_kind[kind]
        try:
            rp_after, rates = _rp_tr_after_target(
                board, player, kind=kind, tid=int(tid)
            )
        except Exception:
            continue
        screen = screen_target_pair(need, rp_after, rates)
        vectors[int(tid)] = {
            "need": list(need),
            "rp": list(rp_after),
            "rates": list(rates),
            "kind": kind,
            "hopeless": bool(screen.get("hopeless")),
            "screen_reason": str(screen.get("reason") or "ok"),
        }
        ordered.append((cand, int(tid), kind))

    # Hopeless marks
    by_id: Dict[int, Dict[str, Any]] = {}
    for _cand, tid, kind in ordered:
        v = vectors.get(tid) or {}
        reasons: List[str] = []
        if v.get("hopeless"):
            reasons.append("hopeless_at_H")
        by_id[tid] = {
            "id": tid,
            "kind": kind,
            "reasons": reasons,
            "inferior": bool(reasons),
        }

    # Pareto pairwise (same kind only)
    ids = [tid for _c, tid, _k in ordered]
    for i, tid_a in enumerate(ids):
        va = vectors.get(tid_a)
        if not va:
            continue
        for tid_b in ids[i + 1 :]:
            vb = vectors.get(tid_b)
            if not vb or va.get("kind") != vb.get("kind"):
                continue
            if target_is_inferior(va["need"], va["rp"], vb["need"], vb["rp"]):
                by_id[tid_a]["reasons"].append("pareto_dom")
                by_id[tid_a]["inferior"] = True
                by_id[tid_a]["dominated_by"] = tid_b
            elif target_is_inferior(vb["need"], vb["rp"], va["need"], va["rp"]):
                by_id[tid_b]["reasons"].append("pareto_dom")
                by_id[tid_b]["inferior"] = True
                by_id[tid_b]["dominated_by"] = tid_a

    # Dedupe reasons
    for tid, bag in by_id.items():
        seen = []
        for r in list(bag.get("reasons") or []):
            if r not in seen:
                seen.append(r)
        bag["reasons"] = seen
        bag["reason"] = "+".join(seen) if seen else "ok"
        bag["inferior"] = bool(seen)

    inferior = [
        {
            "id": tid,
            "kind": bag.get("kind"),
            "reason": bag.get("reason"),
            "reasons": list(bag.get("reasons") or []),
        }
        for tid, bag in by_id.items()
        if bag.get("inferior")
    ]

    kept = list(cands)
    dropped: List[Dict[str, Any]] = []
    if mode == "prune" and inferior:
        inferior_ids = {int(x["id"]) for x in inferior}
        survivors = [
            c
            for c in cands
            if (_target_id_of(c) is None or int(_target_id_of(c)) not in inferior_ids)
        ]
        # Safety floor: keep best-scoring inferior back if needed
        if len(survivors) < floor:
            # restore inferior in original order until floor
            for c in cands:
                tid = _target_id_of(c)
                if tid is None or int(tid) not in inferior_ids:
                    continue
                if c in survivors:
                    continue
                survivors.append(c)
                if len(survivors) >= floor:
                    break
        dropped_ids = {
            int(t)
            for t in inferior_ids
            if all((_target_id_of(c) is None or int(_target_id_of(c)) != t) for c in survivors)
        }
        dropped = [x for x in inferior if int(x["id"]) in dropped_ids]
        kept = survivors

    meta.update(
        {
            "applied": True,
            "kept": kept,
            "inferior": inferior,
            "dropped": dropped,
            "by_id": by_id,
            "reason": "ok",
        }
    )

    # Stash for PLN2 / dossier (optional — city supplemental screens set stash=False)
    if stash:
        try:
            bag = {
                "mode": mode,
                "way_id": wid,
                "inferior": list(inferior),
                "dropped": list(dropped),
                "by_id": dict(by_id),
            }
            if game is not None:
                # Merge into existing bag so settle+city marks coexist
                prev = getattr(game, "_last_l2_target_screen", None)
                if isinstance(prev, Mapping) and prev.get("way_id") == wid:
                    merged_by = dict(prev.get("by_id") or {})
                    merged_by.update(by_id)
                    bag["by_id"] = merged_by
                    bag["inferior"] = [
                        x
                        for x in (
                            list(prev.get("inferior") or []) + list(inferior)
                        )
                        if isinstance(x, Mapping)
                    ]
                game._last_l2_target_screen = bag
            if player is not None:
                setattr(player, "last_l2_target_screen", dict(bag))
        except Exception:
            pass
    return meta


def annotate_plan_rows_with_screen(
    rows: Sequence[Mapping[str, Any]],
    screen_bag: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Copy plan rows and attach inferior fields from a screen bag."""
    by_id = {}
    if isinstance(screen_bag, Mapping):
        raw = screen_bag.get("by_id") or {}
        if isinstance(raw, Mapping):
            by_id = {int(k): v for k, v in raw.items() if str(k).lstrip("-").isdigit()}
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, Mapping):
            continue
        row = dict(r)
        try:
            tid = int(row.get("id") or row.get("target_id") or 0)
        except Exception:
            tid = 0
        bag = by_id.get(tid) if tid else None
        if isinstance(bag, Mapping) and bag.get("inferior"):
            row["inferior"] = 1
            row["inferior_reason"] = str(bag.get("reason") or "inferior")
            # Dig Why hint without ETA rewrite
            why = str(row.get("reason") or "")
            tag = f"inf:{row['inferior_reason']}"
            if tag not in why:
                row["reason"] = f"{why}; {tag}".strip("; ")
        else:
            row.setdefault("inferior", 0)
        out.append(row)
    return out


__all__ = [
    "bottleneck_resource",
    "per_resource_ub",
    "mass_lb",
    "target_screen_at_H",
    "target_is_inferior",
    "screen_target_pair",
    "l2_target_screen_mode",
    "remtr_need_after_target",
    "screen_portfolio_targets",
    "annotate_plan_rows_with_screen",
]
