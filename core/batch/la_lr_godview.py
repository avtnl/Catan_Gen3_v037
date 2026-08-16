"""Phase L WP-L2a/L2b + WP-L3: god-view labels, θ fit, offline give-up backtest.

L2a: special=\"la\". L2b: special=\"lr\" (same label/θ pipeline).
L3 / L3b: sample-time backtest — if hopeless_score ≥ θ at t, mark would give-up L2;
compare to later claim / final holder (false give-up, false hold, time-to-fire).

Does not mutate game policy. Offline only on ``la_lr_probe.jsonl`` (+ optional
``g00N/result.json`` for final holders).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

# Label hyperparams (v1 global; stage splits deferred — Q2)
DEFAULT_MIN_NEEDS_SAMPLES = 2  # W: min samples with needs=True in episode
DEFAULT_GAP_SUSTAIN_K = 2  # K: last K needs-samples must have gap >= G for give-up
DEFAULT_GAP_GIVEUP_FLOOR = 2  # G: gap floor for "sustained lost race"
DEFAULT_HOLD_MAX_GAP = 1  # race still viable if final/last gap <= this

# L3 backtest hyperparams
DEFAULT_CLAIM_WINDOW_K = 4  # own-turn samples after fire still counting as "would claim"
DEFAULT_FIRE_DWELL = 1  # consecutive needs-samples with score>=θ before fire
DEFAULT_MIN_NEEDS_BACKTEST = 1  # min needs samples to include episode in backtest pool

# Hopeless score weights (LA / LR share structure; features differ)
W_GAP = 0.45
W_THREATS = 0.30
W_KILL = 0.15
W_S55_HOPELESS = 0.10


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _clamp01(x: float) -> float:
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return float(x)


def iter_probe_rows(
    path: PathLike,
    *,
    include_fire_events: bool = False,
) -> Iterable[Dict[str, Any]]:
    """Yield sample probe rows for offline L2/L3.

    Live L6 fire rows (``la_giveup_fire`` / ``lr_giveup_fire``) and S7
    ``salvage_adopt`` dig rows are excluded by default so they do not
    double-count needs-samples. Pass ``include_fire_events=True`` to keep them.
    """
    p = Path(path)
    if not p.is_file():
        return
    try:
        from core.la_lr_probe_log import PROBE_NON_SAMPLE_EVENTS

        skip_events = frozenset(PROBE_NON_SAMPLE_EVENTS)
    except Exception:
        skip_events = frozenset(
            {"la_giveup_fire", "lr_giveup_fire", "salvage_adopt"}
        )
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not isinstance(o, dict) or o.get("kind") not in (None, "la_lr_probe"):
                continue
            if not include_fire_events and str(o.get("event") or "") in skip_events:
                continue
            yield o


def load_final_holders(batch_dir: Path) -> Dict[str, Dict[str, Optional[int]]]:
    """game_id or sequence → {la_holder_id, lr_holder_id} from result.json."""
    out: Dict[str, Dict[str, Optional[int]]] = {}
    batch = Path(batch_dir)
    # Prefer g00N/result.json
    for rp in sorted(batch.glob("g*/result.json")):
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        seq = _safe_int(data.get("sequence_number"))
        gid = str(data.get("game_id") or "") or None
        holders = {
            "la_holder_id": _safe_int(data.get("la_holder_id")),
            "lr_holder_id": _safe_int(data.get("lr_holder_id")),
            "winner_id": _safe_int(data.get("winner_id")),
        }
        if seq is not None:
            out[f"seq:{seq}"] = holders
        if gid:
            out[f"gid:{gid}"] = holders
    # Fallback batch_summary compact games
    sp = batch / "batch_summary.json"
    if sp.is_file():
        try:
            summary = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            summary = {}
        for g in summary.get("games") or []:
            if not isinstance(g, dict):
                continue
            seq = _safe_int(g.get("sequence_number"))
            gid = str(g.get("game_id") or "") or None
            holders = {
                "la_holder_id": _safe_int(g.get("la_holder_id")),
                "lr_holder_id": _safe_int(g.get("lr_holder_id")),
                "winner_id": _safe_int(g.get("winner_id")),
            }
            if seq is not None and f"seq:{seq}" not in out:
                out[f"seq:{seq}"] = holders
            if gid and f"gid:{gid}" not in out:
                out[f"gid:{gid}"] = holders
    return out


def resolve_holders(
    row: Mapping[str, Any],
    final_map: Mapping[str, Dict[str, Optional[int]]],
) -> Dict[str, Optional[int]]:
    seq = _safe_int(row.get("sequence_number"))
    gid = str(row.get("game_id") or "") or None
    if seq is not None and f"seq:{seq}" in final_map:
        return dict(final_map[f"seq:{seq}"])
    if gid and f"gid:{gid}" in final_map:
        return dict(final_map[f"gid:{gid}"])
    return {
        "la_holder_id": _safe_int(row.get("la_holder_id")),
        "lr_holder_id": _safe_int(row.get("lr_holder_id")),
        "winner_id": None,
    }


def special_block(row: Mapping[str, Any], special: str) -> Dict[str, Any]:
    key = "la" if special == "la" else "lr"
    blk = row.get(key)
    return dict(blk) if isinstance(blk, Mapping) else {}


def hopeless_score_la(blk: Mapping[str, Any], *, gap_norm: float = 4.0) -> float:
    """Scalar ∈ [0,1]: higher = more hopeless LA race (global features)."""
    gap = float(_safe_int(blk.get("gap"), 0) or 0)
    threats = float(_safe_int(blk.get("n_threats"), 0) or 0)
    kill = 1.0 if blk.get("kill_recommended") else 0.0
    s55 = 1.0 if blk.get("hopeless") else 0.0
    # Slight boost if army still tiny while gap large
    army = float(_safe_int(blk.get("army"), 0) or 0)
    low_progress = 1.0 if army <= 1 and gap >= 2 else (0.5 if army <= 2 and gap >= 2 else 0.0)
    score = (
        W_GAP * _clamp01(gap / max(gap_norm, 1e-6))
        + W_THREATS * _clamp01(threats / 3.0)
        + W_KILL * kill
        + W_S55_HOPELESS * s55
    )
    # Fold low progress lightly without changing weight sum much
    score = 0.9 * score + 0.1 * low_progress
    return round(_clamp01(score), 4)


def hopeless_score_lr(blk: Mapping[str, Any], *, gap_norm: float = 5.0) -> float:
    """Scalar ∈ [0,1] for LR (L2b). Same structure as LA."""
    gap = float(_safe_int(blk.get("gap"), 0) or 0)
    threats = float(_safe_int(blk.get("n_threats"), 0) or 0)
    kill = 1.0 if blk.get("kill_recommended") else 0.0
    s55 = 1.0 if blk.get("hopeless") else 0.0
    path = float(_safe_int(blk.get("path"), 0) or 0)
    cap = float(_safe_int(blk.get("roads_remaining_cap"), 15) or 0)
    low_progress = 1.0 if path < 5 and gap >= 2 else 0.0
    cap_pressure = 1.0 if cap <= 2 and not blk.get("holds") else 0.0
    score = (
        W_GAP * _clamp01(gap / max(gap_norm, 1e-6))
        + W_THREATS * _clamp01(threats / 3.0)
        + W_KILL * kill
        + W_S55_HOPELESS * s55
    )
    score = 0.85 * score + 0.10 * low_progress + 0.05 * cap_pressure
    return round(_clamp01(score), 4)


def hopeless_score(blk: Mapping[str, Any], special: str) -> float:
    if special == "lr":
        return hopeless_score_lr(blk)
    return hopeless_score_la(blk)


def episode_key(row: Mapping[str, Any]) -> Tuple[str, int]:
    seq = _safe_int(row.get("sequence_number"))
    gid = str(row.get("game_id") or "")
    game_k = f"seq:{seq}" if seq is not None else f"gid:{gid or '?'}"
    pid = _safe_int(row.get("player_id"), -1) or -1
    return game_k, int(pid)


def build_episodes(
    rows: Sequence[Mapping[str, Any]],
    *,
    special: str = "la",
    final_holders: Optional[Mapping[str, Dict[str, Optional[int]]]] = None,
) -> List[Dict[str, Any]]:
    """Group probe rows into (game, player) episodes with LA or LR series."""
    final_holders = final_holders or {}
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        blk = special_block(row, special)
        # Keep all rows for seat; filter needs later
        ek = episode_key(row)
        sample = {
            "round": _safe_int(row.get("round"), 0) or 0,
            "turn": _safe_int(row.get("turn"), 0) or 0,
            "event": str(row.get("event") or ""),
            "needs": bool(blk.get("needs")),
            "holds": bool(blk.get("holds")),
            "gap": _safe_int(blk.get("gap"), 0) or 0,
            "n_threats": _safe_int(blk.get("n_threats"), 0) or 0,
            "kill_recommended": bool(blk.get("kill_recommended")),
            "hopeless_s55": bool(blk.get("hopeless")),
            "score": hopeless_score(blk, special),
            "army_or_path": _safe_int(
                blk.get("army") if special == "la" else blk.get("path"), 0
            )
            or 0,
        }
        buckets[ek].append(sample)

    episodes: List[Dict[str, Any]] = []
    holder_field = "la_holder_id" if special == "la" else "lr_holder_id"
    for (game_k, pid), samples in buckets.items():
        samples = sorted(
            samples, key=lambda s: (s["round"], s["turn"], s["event"])
        )
        needs_samples = [s for s in samples if s["needs"]]
        ever_holds = any(s["holds"] for s in samples)
        holders = final_holders.get(game_k) or {}
        final_holder = holders.get(holder_field)
        final_holds = final_holder is not None and int(final_holder) == int(pid)
        ever_holds = ever_holds or final_holds

        gaps_needs = [s["gap"] for s in needs_samples]
        scores_needs = [s["score"] for s in needs_samples]
        max_gap = max(gaps_needs) if gaps_needs else None
        max_score = max(scores_needs) if scores_needs else None
        last_gap = gaps_needs[-1] if gaps_needs else None
        last_score = scores_needs[-1] if scores_needs else None

        episodes.append(
            {
                "game_key": game_k,
                "player_id": pid,
                "special": special,
                "n_samples": len(samples),
                "n_needs": len(needs_samples),
                "ever_holds": ever_holds,
                "final_holds": final_holds,
                "max_gap": max_gap,
                "last_gap": last_gap,
                "max_score": max_score,
                "last_score": last_score,
                "needs_samples": needs_samples,
                "all_samples": samples,
            }
        )
    return episodes


def label_episode(
    ep: Mapping[str, Any],
    *,
    min_needs: int = DEFAULT_MIN_NEEDS_SAMPLES,
    gap_floor: int = DEFAULT_GAP_GIVEUP_FLOOR,
    sustain_k: int = DEFAULT_GAP_SUSTAIN_K,
    hold_max_gap: int = DEFAULT_HOLD_MAX_GAP,
) -> str:
    """Return should_give_up | should_hold | unlabeled."""
    n_needs = int(ep.get("n_needs") or 0)
    if n_needs < int(min_needs):
        return "unlabeled"
    ever = bool(ep.get("ever_holds"))
    needs_samples: List[Dict[str, Any]] = list(ep.get("needs_samples") or [])
    last_k = needs_samples[-max(1, int(sustain_k)) :]
    sustained_bad = bool(last_k) and all(
        int(s.get("gap") or 0) >= int(gap_floor) for s in last_k
    )
    last_gap = ep.get("last_gap")
    if last_gap is None:
        last_gap = 99

    if ever:
        return "should_hold"
    # never holds
    if sustained_bad:
        return "should_give_up"
    if int(last_gap) <= int(hold_max_gap):
        # still close — don't force give-up label
        return "unlabeled"
    # never held, not close, but not sustained K — still weak give-up if max gap high
    max_gap = int(ep.get("max_gap") or 0)
    if max_gap >= int(gap_floor) + 1 and n_needs >= int(min_needs) + 1:
        return "should_give_up"
    return "unlabeled"


def attach_labels(
    episodes: Sequence[Mapping[str, Any]], **label_kw: Any
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ep in episodes:
        e = dict(ep)
        e["label"] = label_episode(e, **label_kw)
        # sample-level for ROC: use max_score / last_score as score for episode
        out.append(e)
    return out


def confusion_at_threshold(
    labeled: Sequence[Mapping[str, Any]],
    theta: float,
    *,
    score_key: str = "max_score",
) -> Dict[str, Any]:
    """Predict give-up if score >= theta. Only labeled episodes."""
    tp = fp = tn = fn = 0
    for ep in labeled:
        lab = ep.get("label")
        if lab not in ("should_give_up", "should_hold"):
            continue
        score = _safe_float(ep.get(score_key), 0.0) or 0.0
        pred_give = score >= float(theta)
        truth_give = lab == "should_give_up"
        if pred_give and truth_give:
            tp += 1
        elif pred_give and not truth_give:
            fp += 1
        elif (not pred_give) and truth_give:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        (2 * prec * rec / (prec + rec))
        if prec is not None and rec is not None and (prec + rec) > 0
        else None
    )
    acc = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) else None
    return {
        "theta": theta,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(prec, 4) if prec is not None else None,
        "recall": round(rec, 4) if rec is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "accuracy": round(acc, 4) if acc is not None else None,
        "n_labeled": tp + tn + fp + fn,
    }


def fit_global_theta(
    labeled: Sequence[Mapping[str, Any]],
    *,
    score_key: str = "max_score",
    grid: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Grid-search θ maximizing F1 (then recall) on labeled episodes."""
    if grid is None:
        grid = [round(x * 0.05, 2) for x in range(0, 21)]  # 0.00 .. 1.00
    best = None
    curve = []
    for th in grid:
        c = confusion_at_threshold(labeled, float(th), score_key=score_key)
        curve.append(c)
        if c["n_labeled"] <= 0:
            continue
        f1 = c["f1"] if c["f1"] is not None else -1.0
        rec = c["recall"] if c["recall"] is not None else -1.0
        key = (f1, rec, -c["fp"])
        if best is None or key > best[0]:
            best = (key, c)
    chosen = best[1] if best else {
        "theta": 0.5,
        "tp": 0,
        "fp": 0,
        "tn": 0,
        "fn": 0,
        "precision": None,
        "recall": None,
        "f1": None,
        "accuracy": None,
        "n_labeled": 0,
        "note": "no_labeled_episodes",
    }
    return {
        "score_key": score_key,
        "chosen": chosen,
        "curve": curve,
    }


def baseline_s55_kill_confusion(
    labeled: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Use any needs-sample with kill_recommended as episode-level pred give-up."""
    tp = fp = tn = fn = 0
    for ep in labeled:
        lab = ep.get("label")
        if lab not in ("should_give_up", "should_hold"):
            continue
        needs = list(ep.get("needs_samples") or [])
        pred = any(bool(s.get("kill_recommended")) for s in needs)
        truth = lab == "should_give_up"
        if pred and truth:
            tp += 1
        elif pred and not truth:
            fp += 1
        elif (not pred) and truth:
            fn += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    return {
        "name": "s55_kill_recommended_any",
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(prec, 4) if prec is not None else None,
        "recall": round(rec, 4) if rec is not None else None,
        "n_labeled": n,
    }


def score_distributions(labeled: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_lab: Dict[str, List[float]] = defaultdict(list)
    for ep in labeled:
        lab = str(ep.get("label") or "unlabeled")
        sc = _safe_float(ep.get("max_score"), None)
        if sc is not None:
            by_lab[lab].append(sc)

    def _summ(xs: List[float]) -> Dict[str, Any]:
        if not xs:
            return {"n": 0}
        xs = sorted(xs)
        return {
            "n": len(xs),
            "mean": round(sum(xs) / len(xs), 4),
            "min": xs[0],
            "max": xs[-1],
            "p50": xs[len(xs) // 2],
        }

    return {k: _summ(v) for k, v in by_lab.items()}


def analyze_special(
    rows: Sequence[Mapping[str, Any]],
    *,
    special: str = "la",
    final_holders: Optional[Mapping[str, Dict[str, Optional[int]]]] = None,
    min_needs: int = DEFAULT_MIN_NEEDS_SAMPLES,
    gap_floor: int = DEFAULT_GAP_GIVEUP_FLOOR,
    sustain_k: int = DEFAULT_GAP_SUSTAIN_K,
    hold_max_gap: int = DEFAULT_HOLD_MAX_GAP,
) -> Dict[str, Any]:
    """Full L2a/L2b analysis for one special."""
    special = str(special or "la").lower()
    if special not in ("la", "lr"):
        raise ValueError("special must be 'la' or 'lr'")

    episodes = build_episodes(rows, special=special, final_holders=final_holders)
    labeled = attach_labels(
        episodes,
        min_needs=min_needs,
        gap_floor=gap_floor,
        sustain_k=sustain_k,
        hold_max_gap=hold_max_gap,
    )
    label_counts = defaultdict(int)
    for ep in labeled:
        label_counts[str(ep.get("label"))] += 1

    fit_max = fit_global_theta(labeled, score_key="max_score")
    fit_last = fit_global_theta(labeled, score_key="last_score")
    # Prefer max_score θ as primary global θ
    primary = fit_max["chosen"]
    theta_name = "theta_LA" if special == "la" else "theta_LR"

    # Separation: mean score give_up vs hold
    dist = score_distributions(labeled)
    separation = None
    if dist.get("should_give_up", {}).get("n", 0) and dist.get("should_hold", {}).get(
        "n", 0
    ):
        separation = round(
            float(dist["should_give_up"]["mean"]) - float(dist["should_hold"]["mean"]),
            4,
        )

    # Compact episode table (no full sample dumps in report)
    ep_table = []
    for ep in labeled:
        ep_table.append(
            {
                "game_key": ep.get("game_key"),
                "player_id": ep.get("player_id"),
                "label": ep.get("label"),
                "n_needs": ep.get("n_needs"),
                "ever_holds": ep.get("ever_holds"),
                "final_holds": ep.get("final_holds"),
                "max_gap": ep.get("max_gap"),
                "last_gap": ep.get("last_gap"),
                "max_score": ep.get("max_score"),
                "last_score": ep.get("last_score"),
            }
        )

    return {
        "special": special,
        "n_rows": len(rows),
        "n_episodes": len(episodes),
        "label_counts": dict(label_counts),
        "label_params": {
            "min_needs": min_needs,
            "gap_floor": gap_floor,
            "sustain_k": sustain_k,
            "hold_max_gap": hold_max_gap,
        },
        "score_distributions": dist,
        "separation_mean_give_minus_hold": separation,
        theta_name: primary.get("theta"),
        "theta_primary": primary,
        "fit_max_score": fit_max,
        "fit_last_score": {
            "score_key": "last_score",
            "chosen": fit_last["chosen"],
            # omit full curve for last to keep report smaller; include chosen only
        },
        "baseline_s55_kill": baseline_s55_kill_confusion(labeled),
        "product_gap_kill_const": 3 if special == "la" else 4,
        "episodes": ep_table,
        "note": (
            "L2a" if special == "la" else "L2b"
        )
        + ": global θ on hopeless_score; stage early/mid/end deferred (Q2).",
    }


def analyze_batch(
    batch_dir: PathLike,
    *,
    special: str = "la",
    probe_path: Optional[PathLike] = None,
    **label_kw: Any,
) -> Dict[str, Any]:
    batch = Path(batch_dir)
    path = Path(probe_path) if probe_path else batch / "la_lr_probe.jsonl"
    rows = list(iter_probe_rows(path))
    holders = load_final_holders(batch)
    analysis = analyze_special(
        rows, special=special, final_holders=holders, **label_kw
    )
    analysis["batch_dir"] = str(batch)
    analysis["probe_path"] = str(path)
    analysis["probe_exists"] = path.is_file()
    analysis["n_holder_keys"] = len(holders)
    return analysis


def format_console_la(report: Mapping[str, Any]) -> str:
    """Human-readable summary for L2a (LA)."""
    lines = [
        "=== Phase L WP-L2a: LA god-view labels + θ_LA ===",
        f"batch={report.get('batch_dir')}  probe_exists={report.get('probe_exists')}",
        f"rows={report.get('n_rows')}  episodes={report.get('n_episodes')}  "
        f"labels={report.get('label_counts')}",
        f"label_params={report.get('label_params')}",
        f"score_distributions={report.get('score_distributions')}",
        f"separation (give_up mean − hold mean)={report.get('separation_mean_give_minus_hold')}",
        f"θ_LA (primary, max_score)={report.get('theta_LA')}  "
        f"metrics={report.get('theta_primary')}",
        f"baseline S5.5 kill_recommended={report.get('baseline_s55_kill')}",
        f"product LA_GAP_KILL const={report.get('product_gap_kill_const')}",
        f"note: {report.get('note')}",
        "================================================",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WP-L3 / L3b — sample-time give-up backtest (offline; no SE mutation)
# ---------------------------------------------------------------------------


def _sample_time_key(s: Mapping[str, Any]) -> Tuple[int, int]:
    return (int(s.get("round") or 0), int(s.get("turn") or 0))


def find_fire_index(
    needs_samples: Sequence[Mapping[str, Any]],
    theta: float,
    *,
    dwell: int = DEFAULT_FIRE_DWELL,
) -> Optional[int]:
    """First index i where score>=θ for ``dwell`` consecutive needs-samples ending at i."""
    d = max(1, int(dwell))
    run = 0
    for i, s in enumerate(needs_samples):
        sc = _safe_float(s.get("score"), 0.0) or 0.0
        if sc >= float(theta):
            run += 1
            if run >= d:
                return i
        else:
            run = 0
    return None


def claims_after_fire(
    needs_samples: Sequence[Mapping[str, Any]],
    fire_idx: int,
    *,
    claim_window_k: int = DEFAULT_CLAIM_WINDOW_K,
    final_holds: bool = False,
    ever_holds: bool = False,
) -> Dict[str, Any]:
    """Whether the seat still claims the special after a give-up fire at fire_idx."""
    k = max(0, int(claim_window_k))
    window = list(needs_samples[fire_idx + 1 : fire_idx + 1 + k]) if fire_idx is not None else []
    after_all = list(needs_samples[fire_idx + 1 :]) if fire_idx is not None else []
    holds_in_window = any(bool(s.get("holds")) for s in window)
    holds_any_after = any(bool(s.get("holds")) for s in after_all)
    # Final / ever hold still counts as "would claim" for false give-up
    # even if holds flag missing from later probe rows
    claimed_later = bool(holds_in_window or holds_any_after or final_holds)
    # If fire was after already holding, that is not a classic false give-up of future claim
    held_at_or_before = False
    if fire_idx is not None:
        held_at_or_before = any(
            bool(s.get("holds")) for s in needs_samples[: fire_idx + 1]
        )
    return {
        "holds_in_window": holds_in_window,
        "holds_any_after": holds_any_after,
        "final_holds": bool(final_holds),
        "ever_holds": bool(ever_holds),
        "held_at_or_before_fire": held_at_or_before,
        "claimed_later": claimed_later and not held_at_or_before,
        "claimed_any_after_including_held": claimed_later or held_at_or_before,
    }


def backtest_episode_at_theta(
    ep: Mapping[str, Any],
    theta: float,
    *,
    claim_window_k: int = DEFAULT_CLAIM_WINDOW_K,
    dwell: int = DEFAULT_FIRE_DWELL,
    gap_floor: int = DEFAULT_GAP_GIVEUP_FLOOR,
    min_needs: int = DEFAULT_MIN_NEEDS_BACKTEST,
) -> Dict[str, Any]:
    """Replay one (game, seat) episode at a fixed θ.

    Outcomes (mutually exclusive for primary class):
      true_give_up   — fire, never claims after (dead special abandoned correctly)
      false_give_up  — fire, then still claims within window / final (premature)
      true_hold      — no fire, and seat claims special (or ends holding)
      false_hold     — no fire, never claims, race looks lost (gap/max)
      skip           — too few needs samples
      neutral_no_fire — no fire, never claims, but race not clearly lost
    """
    needs = list(ep.get("needs_samples") or [])
    n_needs = len(needs)
    ever_holds = bool(ep.get("ever_holds"))
    final_holds = bool(ep.get("final_holds"))
    max_gap = int(ep.get("max_gap") or 0)
    last_gap = int(ep.get("last_gap") if ep.get("last_gap") is not None else 99)
    label = str(ep.get("label") or "unlabeled")

    base = {
        "game_key": ep.get("game_key"),
        "player_id": ep.get("player_id"),
        "theta": float(theta),
        "n_needs": n_needs,
        "label": label,
        "ever_holds": ever_holds,
        "final_holds": final_holds,
        "max_gap": ep.get("max_gap"),
        "last_gap": ep.get("last_gap"),
        "max_score": ep.get("max_score"),
        "fired": False,
        "fire_idx": None,
        "fire_round": None,
        "fire_score": None,
        "time_to_fire_needs": None,
        "outcome": "skip",
    }
    if n_needs < int(min_needs):
        return base

    fire_idx = find_fire_index(needs, theta, dwell=dwell)
    if fire_idx is not None:
        s_fire = needs[fire_idx]
        claim = claims_after_fire(
            needs,
            fire_idx,
            claim_window_k=claim_window_k,
            final_holds=final_holds,
            ever_holds=ever_holds,
        )
        base.update(
            {
                "fired": True,
                "fire_idx": fire_idx,
                "fire_round": s_fire.get("round"),
                "fire_score": s_fire.get("score"),
                "time_to_fire_needs": fire_idx + 1,
                "claim_after": claim,
            }
        )
        # Already holding when fire → treat as true_hold-ish (policy wouldn't need give-up)
        if claim.get("held_at_or_before_fire"):
            base["outcome"] = "true_hold"
        elif claim.get("claimed_later") or (
            final_holds and not claim.get("held_at_or_before_fire")
        ):
            # Fire then still end as holder or claim after → false give-up
            base["outcome"] = "false_give_up"
        else:
            base["outcome"] = "true_give_up"
        return base

    # No fire
    base["fired"] = False
    if ever_holds or final_holds:
        base["outcome"] = "true_hold"
        return base
    # Never claimed: is holding on a dead race a mistake?
    race_lost = max_gap >= int(gap_floor) or last_gap >= int(gap_floor)
    if race_lost and n_needs >= max(2, int(min_needs)):
        base["outcome"] = "false_hold"
    else:
        base["outcome"] = "neutral_no_fire"
    return base


def summarize_backtest_outcomes(
    episode_results: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    counts: Dict[str, int] = defaultdict(int)
    fire_times: List[int] = []
    fire_rounds: List[int] = []
    for r in episode_results:
        oc = str(r.get("outcome") or "skip")
        counts[oc] += 1
        if r.get("fired") and r.get("time_to_fire_needs") is not None:
            fire_times.append(int(r["time_to_fire_needs"]))
        if r.get("fired") and r.get("fire_round") is not None:
            fire_rounds.append(int(r["fire_round"]))

    n_eval = sum(
        counts[k]
        for k in (
            "true_give_up",
            "false_give_up",
            "true_hold",
            "false_hold",
            "neutral_no_fire",
        )
    )
    n_fire = counts["true_give_up"] + counts["false_give_up"]
    # Also count true_hold fires that were "already holding"
    n_fire_raw = sum(1 for r in episode_results if r.get("fired"))
    fgu = counts["false_give_up"]
    tgu = counts["true_give_up"]
    fh = counts["false_hold"]
    th = counts["true_hold"]

    def _rate(num: int, den: int) -> Optional[float]:
        if den <= 0:
            return None
        return round(num / den, 4)

    # Precision of fire: true give-up / all fires that are give-up class
    fire_prec = _rate(tgu, tgu + fgu)
    # Recall of dead races: true give-up / (true give-up + false hold)
    dead_rec = _rate(tgu, tgu + fh)
    f1 = None
    if fire_prec is not None and dead_rec is not None and (fire_prec + dead_rec) > 0:
        f1 = round(2 * fire_prec * dead_rec / (fire_prec + dead_rec), 4)

    return {
        "counts": dict(counts),
        "n_episodes_in": len(episode_results),
        "n_eval": n_eval,
        "n_fire": n_fire,
        "n_fire_raw": n_fire_raw,
        "false_give_up_rate": _rate(fgu, tgu + fgu),  # among give-up fires
        "false_hold_rate": _rate(fh, fh + th + counts.get("neutral_no_fire", 0)),
        "false_hold_among_dead": _rate(fh, tgu + fh),
        "fire_precision_true_give_up": fire_prec,
        "dead_race_recall": dead_rec,
        "f1_give_up": f1,
        "time_to_fire_needs_mean": (
            round(sum(fire_times) / len(fire_times), 3) if fire_times else None
        ),
        "fire_round_mean": (
            round(sum(fire_rounds) / len(fire_rounds), 3) if fire_rounds else None
        ),
    }


def pick_operating_point(
    curve: Sequence[Mapping[str, Any]],
    *,
    max_false_give_up_rate: float = 0.25,
    fallback_theta: float = 0.5,
) -> Dict[str, Any]:
    """Choose θ: max F1, then max dead_race_recall, with FGU rate constraint if possible.

    If the curve has no dead-race signal (no true_give_up / false_hold at any θ),
    return ``fallback_theta`` (usually L2 θ) instead of max θ.
    """
    if not curve:
        return {
            "theta": fallback_theta,
            "note": "empty_curve",
            "metrics": {},
        }

    def _dead_signal(m: Mapping[str, Any]) -> int:
        counts = m.get("counts") or {}
        return int(counts.get("true_give_up") or 0) + int(
            counts.get("false_hold") or 0
        )

    any_dead = any(_dead_signal(c.get("metrics") or {}) > 0 for c in curve)
    any_f1 = any((c.get("metrics") or {}).get("f1_give_up") is not None for c in curve)

    if not any_dead and not any_f1:
        # Prefer mid curve entry nearest fallback
        nearest = min(
            curve,
            key=lambda c: abs(float(c.get("theta") or 0) - float(fallback_theta)),
        )
        return {
            "theta": float(fallback_theta),
            "metrics": nearest.get("metrics") or {},
            "constrained_fgu_le": max_false_give_up_rate,
            "used_fgu_constraint": False,
            "n_curve": len(curve),
            "n_viable": 0,
            "note": "no_dead_race_signal_use_fallback_theta",
        }

    viable: List[Mapping[str, Any]] = []
    for c in curve:
        m = c.get("metrics") or {}
        fgu = m.get("false_give_up_rate")
        if fgu is None or fgu <= float(max_false_give_up_rate):
            viable.append(c)
    pool = viable if viable else list(curve)

    def _key(c: Mapping[str, Any]) -> Tuple[float, float, float, float]:
        m = c.get("metrics") or {}
        f1 = m.get("f1_give_up")
        rec = m.get("dead_race_recall")
        fgu = m.get("false_give_up_rate")
        # Prefer higher f1, higher recall, lower fgu; mild preference for lower θ
        # only when scores tie (earlier give-up is useful) — use -theta last.
        return (
            float(f1) if f1 is not None else -1.0,
            float(rec) if rec is not None else -1.0,
            -(float(fgu) if fgu is not None else 1.0),
            -float(c.get("theta") or 0.0),
        )

    best = max(pool, key=_key)
    return {
        "theta": best.get("theta"),
        "metrics": best.get("metrics"),
        "constrained_fgu_le": max_false_give_up_rate,
        "used_fgu_constraint": bool(viable),
        "n_curve": len(curve),
        "n_viable": len(viable),
        "note": None,
    }


def backtest_at_theta(
    labeled_episodes: Sequence[Mapping[str, Any]],
    theta: float,
    **bt_kw: Any,
) -> Dict[str, Any]:
    results = [
        backtest_episode_at_theta(ep, theta, **bt_kw) for ep in labeled_episodes
    ]
    metrics = summarize_backtest_outcomes(results)
    return {
        "theta": float(theta),
        "metrics": metrics,
        "episodes": results,
    }


def backtest_theta_curve(
    labeled_episodes: Sequence[Mapping[str, Any]],
    *,
    grid: Optional[Sequence[float]] = None,
    max_false_give_up_rate: float = 0.25,
    include_episode_details: bool = False,
    fallback_theta: float = 0.5,
    **bt_kw: Any,
) -> Dict[str, Any]:
    if grid is None:
        grid = [round(x * 0.05, 2) for x in range(0, 21)]
    curve: List[Dict[str, Any]] = []
    for th in grid:
        run = backtest_at_theta(labeled_episodes, float(th), **bt_kw)
        entry: Dict[str, Any] = {
            "theta": run["theta"],
            "metrics": run["metrics"],
        }
        if include_episode_details:
            entry["episodes"] = run["episodes"]
        curve.append(entry)
    operating = pick_operating_point(
        curve,
        max_false_give_up_rate=max_false_give_up_rate,
        fallback_theta=float(fallback_theta),
    )
    return {
        "curve": curve,
        "operating_point": operating,
        "grid": list(grid),
        "backtest_params": {
            "claim_window_k": bt_kw.get("claim_window_k", DEFAULT_CLAIM_WINDOW_K),
            "dwell": bt_kw.get("dwell", DEFAULT_FIRE_DWELL),
            "gap_floor": bt_kw.get("gap_floor", DEFAULT_GAP_GIVEUP_FLOOR),
            "min_needs": bt_kw.get("min_needs", DEFAULT_MIN_NEEDS_BACKTEST),
            "max_false_give_up_rate": max_false_give_up_rate,
            "fallback_theta": float(fallback_theta),
        },
    }


def baseline_s55_sample_backtest(
    labeled_episodes: Sequence[Mapping[str, Any]],
    *,
    claim_window_k: int = DEFAULT_CLAIM_WINDOW_K,
    gap_floor: int = DEFAULT_GAP_GIVEUP_FLOOR,
    min_needs: int = DEFAULT_MIN_NEEDS_BACKTEST,
) -> Dict[str, Any]:
    """Fire at first needs-sample with kill_recommended (product S5.5 proxy)."""
    results: List[Dict[str, Any]] = []
    for ep in labeled_episodes:
        needs = list(ep.get("needs_samples") or [])
        n_needs = len(needs)
        base = {
            "game_key": ep.get("game_key"),
            "player_id": ep.get("player_id"),
            "theta": None,
            "rule": "s55_kill_recommended",
            "n_needs": n_needs,
            "label": ep.get("label"),
            "ever_holds": ep.get("ever_holds"),
            "final_holds": ep.get("final_holds"),
            "fired": False,
            "outcome": "skip",
        }
        if n_needs < int(min_needs):
            results.append(base)
            continue
        fire_idx = None
        for i, s in enumerate(needs):
            if bool(s.get("kill_recommended")):
                fire_idx = i
                break
        # Reuse outcome logic via a synthetic theta path
        if fire_idx is None:
            # mirror no-fire branch
            faux = dict(ep)
            # force no fire by huge theta
            r = backtest_episode_at_theta(
                faux,
                theta=1e9,
                claim_window_k=claim_window_k,
                dwell=1,
                gap_floor=gap_floor,
                min_needs=min_needs,
            )
            r["rule"] = "s55_kill_recommended"
            r["theta"] = None
            results.append(r)
            continue
        # Build episode that fires only via kill: set scores so only kill index fires
        # Easier: manually classify like backtest_episode_at_theta fire branch
        s_fire = needs[fire_idx]
        claim = claims_after_fire(
            needs,
            fire_idx,
            claim_window_k=claim_window_k,
            final_holds=bool(ep.get("final_holds")),
            ever_holds=bool(ep.get("ever_holds")),
        )
        base.update(
            {
                "fired": True,
                "fire_idx": fire_idx,
                "fire_round": s_fire.get("round"),
                "fire_score": s_fire.get("score"),
                "time_to_fire_needs": fire_idx + 1,
                "claim_after": claim,
            }
        )
        if claim.get("held_at_or_before_fire"):
            base["outcome"] = "true_hold"
        elif claim.get("claimed_later") or (
            bool(ep.get("final_holds")) and not claim.get("held_at_or_before_fire")
        ):
            base["outcome"] = "false_give_up"
        else:
            base["outcome"] = "true_give_up"
        results.append(base)
    return {
        "name": "s55_kill_recommended_first",
        "metrics": summarize_backtest_outcomes(results),
        "n_episodes": len(results),
    }


def analyze_backtest(
    rows: Sequence[Mapping[str, Any]],
    *,
    special: str = "lr",
    final_holders: Optional[Mapping[str, Dict[str, Optional[int]]]] = None,
    theta: Optional[float] = None,
    grid: Optional[Sequence[float]] = None,
    claim_window_k: int = DEFAULT_CLAIM_WINDOW_K,
    dwell: int = DEFAULT_FIRE_DWELL,
    max_false_give_up_rate: float = 0.25,
    include_episode_details: bool = False,
    # label params (for episode labels in tables)
    min_needs_label: int = DEFAULT_MIN_NEEDS_SAMPLES,
    gap_floor: int = DEFAULT_GAP_GIVEUP_FLOOR,
    sustain_k: int = DEFAULT_GAP_SUSTAIN_K,
    hold_max_gap: int = DEFAULT_HOLD_MAX_GAP,
    min_needs_backtest: int = DEFAULT_MIN_NEEDS_BACKTEST,
) -> Dict[str, Any]:
    """Full L3 backtest for one special (L3b when special='lr')."""
    special = str(special or "lr").lower()
    if special not in ("la", "lr"):
        raise ValueError("special must be 'la' or 'lr'")

    episodes = build_episodes(rows, special=special, final_holders=final_holders)
    labeled = attach_labels(
        episodes,
        min_needs=min_needs_label,
        gap_floor=gap_floor,
        sustain_k=sustain_k,
        hold_max_gap=hold_max_gap,
    )
    # L2 θ as reference
    l2 = analyze_special(
        rows,
        special=special,
        final_holders=final_holders,
        min_needs=min_needs_label,
        gap_floor=gap_floor,
        sustain_k=sustain_k,
        hold_max_gap=hold_max_gap,
    )
    theta_l2 = l2.get("theta_LR" if special == "lr" else "theta_LA")

    bt_kw = {
        "claim_window_k": claim_window_k,
        "dwell": dwell,
        "gap_floor": gap_floor,
        "min_needs": min_needs_backtest,
    }
    fallback_th = (
        float(theta_l2)
        if theta_l2 is not None
        else (float(theta) if theta is not None else 0.5)
    )
    curve_pack = backtest_theta_curve(
        labeled,
        grid=grid,
        max_false_give_up_rate=max_false_give_up_rate,
        include_episode_details=False,
        fallback_theta=fallback_th,
        **bt_kw,
    )
    op = curve_pack["operating_point"]
    theta_op = _safe_float(op.get("theta"), fallback_th) or fallback_th
    theta_ref = float(theta) if theta is not None else float(theta_op)

    detail_op = backtest_at_theta(labeled, theta_op, **bt_kw)
    detail_ref = backtest_at_theta(labeled, theta_ref, **bt_kw)
    detail_l2 = (
        backtest_at_theta(labeled, float(theta_l2), **bt_kw)
        if theta_l2 is not None
        else None
    )
    s55 = baseline_s55_sample_backtest(
        labeled,
        claim_window_k=claim_window_k,
        gap_floor=gap_floor,
        min_needs=min_needs_backtest,
    )

    # Compact episode table at operating point
    ep_table = []
    for r in detail_op["episodes"]:
        if r.get("outcome") == "skip" and not include_episode_details:
            continue
        ep_table.append(
            {
                "game_key": r.get("game_key"),
                "player_id": r.get("player_id"),
                "outcome": r.get("outcome"),
                "fired": r.get("fired"),
                "fire_round": r.get("fire_round"),
                "fire_score": r.get("fire_score"),
                "time_to_fire_needs": r.get("time_to_fire_needs"),
                "n_needs": r.get("n_needs"),
                "label": r.get("label"),
                "ever_holds": r.get("ever_holds"),
                "final_holds": r.get("final_holds"),
                "max_gap": r.get("max_gap"),
                "max_score": r.get("max_score"),
            }
        )

    wp = "L3b" if special == "lr" else "L3a"
    op_counts = (detail_op.get("metrics") or {}).get("counts") or {}
    data_quality = {
        "n_needs_episodes": sum(
            1 for e in labeled if int(e.get("n_needs") or 0) >= 1
        ),
        "n_true_give_up_at_op": int(op_counts.get("true_give_up") or 0),
        "n_false_give_up_at_op": int(op_counts.get("false_give_up") or 0),
        "n_false_hold_at_op": int(op_counts.get("false_hold") or 0),
        "n_true_hold_at_op": int(op_counts.get("true_hold") or 0),
        "selection_note": op.get("note"),
        "sufficient_for_l6": bool(
            int(op_counts.get("true_give_up") or 0)
            + int(op_counts.get("false_hold") or 0)
            >= 5
        ),
    }
    return {
        "schema": 1,
        "wp": wp,
        "special": special,
        "n_rows": len(rows),
        "n_episodes": len(episodes),
        "label_counts": l2.get("label_counts"),
        "l2_theta": theta_l2,
        "l2_theta_primary": l2.get("theta_primary"),
        "data_quality": data_quality,
        "operating_point": {
            "theta": theta_op,
            "metrics": detail_op["metrics"],
            "selection": {
                k: op.get(k)
                for k in (
                    "constrained_fgu_le",
                    "used_fgu_constraint",
                    "n_curve",
                    "n_viable",
                    "note",
                )
            },
        },
        "theta_ref": {
            "theta": theta_ref,
            "source": "cli" if theta is not None else "operating_point",
            "metrics": detail_ref["metrics"],
        },
        "theta_l2_backtest": (
            {"theta": theta_l2, "metrics": detail_l2["metrics"]}
            if detail_l2 is not None
            else None
        ),
        "baseline_s55_sample": s55,
        "curve": [
            {"theta": c["theta"], "metrics": c["metrics"]} for c in curve_pack["curve"]
        ],
        "backtest_params": curve_pack["backtest_params"],
        "episodes_at_operating_point": ep_table,
        "product_gap_kill_const": 3 if special == "la" else 4,
        "note": (
            f"{wp}: sample-time give-up backtest on hopeless_score; "
            "no SE mutation. Operating point prefers F1 then dead-race recall "
            "with false_give_up_rate cap."
        ),
    }


def analyze_backtest_batch(
    batch_dir: PathLike,
    *,
    special: str = "lr",
    probe_path: Optional[PathLike] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    batch = Path(batch_dir)
    path = Path(probe_path) if probe_path else batch / "la_lr_probe.jsonl"
    rows = list(iter_probe_rows(path))
    holders = load_final_holders(batch)
    report = analyze_backtest(
        rows, special=special, final_holders=holders, **kwargs
    )
    report["batch_dir"] = str(batch)
    report["probe_path"] = str(path)
    report["probe_exists"] = path.is_file()
    report["n_holder_keys"] = len(holders)
    return report


def format_console_backtest(report: Mapping[str, Any]) -> str:
    wp = report.get("wp") or "L3"
    special = str(report.get("special") or "").upper()
    op = report.get("operating_point") or {}
    m = op.get("metrics") or {}
    s55 = report.get("baseline_s55_sample") or {}
    lines = [
        f"=== Phase L {wp}: {special} sample-time give-up backtest ===",
        f"batch={report.get('batch_dir')}  probe_exists={report.get('probe_exists')}",
        f"rows={report.get('n_rows')}  episodes={report.get('n_episodes')}  "
        f"labels={report.get('label_counts')}",
        f"L2 θ_{special}={report.get('l2_theta')}",
        f"operating θ={op.get('theta')}  metrics={m}",
        f"  counts={m.get('counts')}",
        f"  FGU_rate={m.get('false_give_up_rate')}  "
        f"dead_recall={m.get('dead_race_recall')}  "
        f"F1={m.get('f1_give_up')}",
        f"  time_to_fire_needs_mean={m.get('time_to_fire_needs_mean')}  "
        f"fire_round_mean={m.get('fire_round_mean')}",
        f"data_quality={report.get('data_quality')}",
        f"L2-θ backtest={report.get('theta_l2_backtest')}",
        f"S5.5 sample baseline={s55.get('metrics')}",
        f"params={report.get('backtest_params')}",
        f"note: {report.get('note')}",
        "================================================",
    ]
    return "\n".join(lines)


__all__ = [
    "DEFAULT_MIN_NEEDS_SAMPLES",
    "DEFAULT_GAP_SUSTAIN_K",
    "DEFAULT_GAP_GIVEUP_FLOOR",
    "DEFAULT_HOLD_MAX_GAP",
    "DEFAULT_CLAIM_WINDOW_K",
    "DEFAULT_FIRE_DWELL",
    "DEFAULT_MIN_NEEDS_BACKTEST",
    "iter_probe_rows",
    "load_final_holders",
    "hopeless_score_la",
    "hopeless_score_lr",
    "hopeless_score",
    "build_episodes",
    "label_episode",
    "attach_labels",
    "confusion_at_threshold",
    "fit_global_theta",
    "analyze_special",
    "analyze_batch",
    "format_console_la",
    "find_fire_index",
    "claims_after_fire",
    "backtest_episode_at_theta",
    "summarize_backtest_outcomes",
    "pick_operating_point",
    "backtest_at_theta",
    "backtest_theta_curve",
    "baseline_s55_sample_backtest",
    "analyze_backtest",
    "analyze_backtest_batch",
    "format_console_backtest",
]
