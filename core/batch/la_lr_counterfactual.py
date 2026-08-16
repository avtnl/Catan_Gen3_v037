"""Phase L C: offline counterfactual sticky-switch oracle (light path).

Join probe samples to CS ``eta_locked`` / ``eta_alt`` / ``eta_gain_if_switch``.
Label ``should_have_switched`` when needs special, not holding, race gap high,
and ETA gain from switching is large enough.

Does **not** re-run portfolio (heavy C3 deferred). No SE mutation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from core.batch.la_lr_players_view_analyze import load_sample_rows, resolve_probe_path
from core.la_lr_public_giveup import (
    GATE_FGU_MAX,
    GATE_PRECISION_MIN,
    GATE_SOFT_PRECISION_MIN,
    THETA_LA_SAFE,
    THETA_LR_SAFE,
    build_teacher_record,
    public_giveup_flag_rule_a,
)
from core.la_lr_players_view import (
    apply_series_deltas,
    build_public_features_from_probe_row,
    SERIES_DELTA_K,
)

PathLike = Union[str, Path]

# --- C0 freeze ---
C_SPEC_FREEZE_ID: str = "L5_C_COUNTERFACTUAL_LIGHT_v0"
C_SCHEMA: int = 1

# ETA gain thresholds (own-turns): sticky worse than alt by this amount
C_X_MIN_DEFAULT: float = 1.0
# Race gap floors by special
C_G_MIN_LA: int = 2
C_G_MIN_LR: int = 3

# Labels
LABEL_SWITCH = "should_have_switched"
LABEL_HOLD = "ok_to_hold"
LABEL_UNLABELED = "unlabeled"


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


def _game_key_from_obj(o: Mapping[str, Any]) -> str:
    seq = _safe_int(o.get("sequence_number"), None)
    if seq is not None:
        return f"seq:{seq}"
    gid = str(o.get("game_id") or "").strip()
    return f"gid:{gid or '?'}"


def _join_key(o: Mapping[str, Any]) -> Tuple[str, int, int, int]:
    gk = _game_key_from_obj(o)
    pid = _safe_int(o.get("player_id"), -1) or -1
    rnd = _safe_int(o.get("round"), 0) or 0
    turn = _safe_int(o.get("turn"), 0) or 0
    return gk, int(pid), int(rnd), int(turn)


def load_cs_eta_index(cs_path: PathLike) -> Dict[Tuple[str, int, int, int], Dict[str, Any]]:
    """Index CS rows by (game, player, round, turn); last write wins."""
    idx: Dict[Tuple[str, int, int, int], Dict[str, Any]] = {}
    p = Path(cs_path)
    if not p.is_file():
        return idx
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not isinstance(o, Mapping):
                continue
            key = _join_key(o)
            idx[key] = {
                "eta_locked": _safe_float(o.get("eta_locked")),
                "eta_alt": _safe_float(o.get("eta_alt")),
                "eta_gain_if_switch": _safe_float(o.get("eta_gain_if_switch")),
                "self_eta": _safe_float(o.get("self_eta")),
                "way_id": _safe_int(o.get("sticky_way_id") or o.get("way_id")),
                "way_la": bool(o.get("way_la")),
                "way_lr": bool(o.get("way_lr")),
                "switch_eta_gain": _safe_float(o.get("switch_eta_gain")),
            }
    return idx


def resolve_cs_path(
    batch_dir: Optional[PathLike] = None,
    cs_path: Optional[PathLike] = None,
) -> Path:
    if cs_path is not None:
        return Path(cs_path)
    if batch_dir is None:
        raise ValueError("batch_dir or cs_path required")
    return Path(batch_dir) / "cs.jsonl"


def _gap_of(row: Mapping[str, Any], special: str) -> int:
    blk = row.get(special) if isinstance(row.get(special), Mapping) else {}
    g = _safe_int(blk.get("gap"), None)
    if g is not None:
        return max(0, int(g))
    return 0


def label_should_switch(
    *,
    needs: bool,
    holds: bool,
    gap: int,
    eta_gain: Optional[float],
    g_min: int,
    x_min: float,
) -> Tuple[str, str]:
    """Return (label, reason)."""
    if not needs:
        return LABEL_UNLABELED, "no_needs"
    if holds:
        return LABEL_HOLD, "holds"  # ok to hold special you have
    if eta_gain is None:
        return LABEL_UNLABELED, "missing_eta_gain"
    if gap < int(g_min):
        # still label hold if gain not enough would be unlabeled race; treat as hold-ok
        if float(eta_gain) >= float(x_min):
            return LABEL_UNLABELED, "gap_below_floor"
        return LABEL_HOLD, "gap_low_and_gain_low"
    if float(eta_gain) >= float(x_min):
        return LABEL_SWITCH, "eta_gain_and_gap"
    return LABEL_HOLD, "eta_gain_below"


def _agreement(tp: int, fp: int, tn: int, fn: int) -> Dict[str, Any]:
    prec = (tp / (tp + fp)) if (tp + fp) > 0 else None
    rec = (tp / (tp + fn)) if (tp + fn) > 0 else None
    f1 = (
        2 * prec * rec / (prec + rec)
        if prec is not None and rec is not None and (prec + rec) > 0
        else None
    )
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": None if prec is None else round(prec, 4),
        "recall": None if rec is None else round(rec, 4),
        "f1": None if f1 is None else round(f1, 4),
        "n": tp + fp + tn + fn,
    }


def _acc_binary(
    pairs: Sequence[Tuple[bool, bool]],
) -> Dict[str, Any]:
    """pairs of (pred, truth) for positive class."""
    tp = fp = tn = fn = 0
    for pred, truth in pairs:
        if pred and truth:
            tp += 1
        elif pred and not truth:
            fp += 1
        elif (not pred) and truth:
            fn += 1
        else:
            tn += 1
    return _agreement(tp, fp, tn, fn)


def iter_counterfactual_rows(
    probe_rows: Sequence[Mapping[str, Any]],
    cs_index: Mapping[Tuple[str, int, int, int], Mapping[str, Any]],
    *,
    special: str = "la",
    x_min: float = C_X_MIN_DEFAULT,
    g_min: Optional[int] = None,
    theta: Optional[float] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield labeled rows for one special (with public features for dig)."""
    sp = str(special or "la").strip().lower()
    if sp not in ("la", "lr"):
        sp = "la"
    gmin = int(g_min) if g_min is not None else (C_G_MIN_LA if sp == "la" else C_G_MIN_LR)

    # series deltas for public proxy
    by_seat: Dict[Tuple[str, int], List[Mapping[str, Any]]] = defaultdict(list)
    for row in probe_rows:
        gk = _game_key_from_obj(row)
        pid = _safe_int(row.get("player_id"), -1) or -1
        by_seat[(gk, int(pid))].append(row)

    for (gk, pid), series in by_seat.items():
        series = sorted(
            series,
            key=lambda r: (
                _safe_int(r.get("round"), 0) or 0,
                _safe_int(r.get("turn"), 0) or 0,
            ),
        )
        hist_a: List[int] = []
        hist_p: List[int] = []
        for row in series:
            key = _join_key(row)
            cs = cs_index.get(key) or {}
            feat = build_public_features_from_probe_row(row)
            feat = apply_series_deltas(
                feat,
                prior_army=hist_a[-1] if hist_a else None,
                prior_path=hist_p[-1] if hist_p else None,
                series_len=len(hist_a) + 1,
            )
            teacher = build_teacher_record(row, sp, theta=theta)
            pub = public_giveup_flag_rule_a(feat, sp)

            eta_locked = cs.get("eta_locked")
            eta_alt = cs.get("eta_alt")
            eta_gain = cs.get("eta_gain_if_switch")
            if eta_gain is None and eta_locked is not None and eta_alt is not None:
                try:
                    eta_gain = float(eta_locked) - float(eta_alt)
                except Exception:
                    eta_gain = None

            needs = bool(teacher.get("needs"))
            holds = bool(teacher.get("holds"))
            gap = _gap_of(row, sp)
            eg = None if eta_gain is None else float(eta_gain)
            label, reason = label_should_switch(
                needs=needs,
                holds=holds,
                gap=gap,
                eta_gain=eg,
                g_min=gmin,
                x_min=float(x_min),
            )

            yield {
                "game_key": gk,
                "player_id": pid,
                "round": _safe_int(row.get("round")),
                "turn": _safe_int(row.get("turn")),
                "special": sp,
                "needs": needs,
                "holds": holds,
                "gap": gap,
                "eta_locked": eta_locked,
                "eta_alt": eta_alt,
                "eta_gain": eta_gain,
                "cs_joined": bool(cs),
                "label": label,
                "label_reason": reason,
                "teacher_fire": bool(teacher.get("teacher_fire")),
                "teacher_score": teacher.get("score"),
                "public_giveup": bool(pub.get("public_giveup")),
                "public_reason": pub.get("reason"),
                "x_min": float(x_min),
                "g_min": gmin,
            }

            hist_a.append(int(feat.get("army") or 0))
            hist_p.append(int(feat.get("path") or 0))
            if len(hist_a) > int(SERIES_DELTA_K):
                hist_a = hist_a[-int(SERIES_DELTA_K) :]
                hist_p = hist_p[-int(SERIES_DELTA_K) :]


def analyze_counterfactual(
    batch_dir: Optional[PathLike] = None,
    *,
    probe_path: Optional[PathLike] = None,
    cs_path: Optional[PathLike] = None,
    special: str = "both",
    x_min: float = C_X_MIN_DEFAULT,
    g_min_la: int = C_G_MIN_LA,
    g_min_lr: int = C_G_MIN_LR,
    theta_la: Optional[float] = None,
    theta_lr: Optional[float] = None,
) -> Dict[str, Any]:
    """Build counterfactual switch report for a batch."""
    batch = Path(batch_dir) if batch_dir is not None else None
    probe = resolve_probe_path(batch_dir, probe_path)
    cs = resolve_cs_path(batch_dir, cs_path)
    notes: List[str] = []

    report: Dict[str, Any] = {
        "schema": C_SCHEMA,
        "c": "C2_light",
        "spec_freeze_id": C_SPEC_FREEZE_ID,
        "batch_dir": str(batch.resolve()) if batch is not None else None,
        "probe_path": str(probe),
        "cs_path": str(cs),
        "probe_exists": probe.is_file(),
        "cs_exists": cs.is_file(),
        "x_min": float(x_min),
        "g_min_la": int(g_min_la),
        "g_min_lr": int(g_min_lr),
        "theta_la": float(theta_la) if theta_la is not None else THETA_LA_SAFE,
        "theta_lr": float(theta_lr) if theta_lr is not None else THETA_LR_SAFE,
        "la": {},
        "lr": {},
        "notes": notes,
    }

    if not probe.is_file():
        notes.append(f"probe missing: {probe}")
        return report
    if not cs.is_file():
        notes.append(f"cs missing: {cs} — light oracle requires CS ETAs")

    rows = load_sample_rows(probe)
    report["n_probe_samples"] = len(rows)
    cs_idx = load_cs_eta_index(cs)
    report["n_cs_index"] = len(cs_idx)

    specials = ["la", "lr"] if str(special).lower() == "both" else [str(special).lower()]
    for sp in specials:
        if sp not in ("la", "lr"):
            continue
        gmin = g_min_la if sp == "la" else g_min_lr
        th = report["theta_la"] if sp == "la" else report["theta_lr"]
        labeled = list(
            iter_counterfactual_rows(
                rows,
                cs_idx,
                special=sp,
                x_min=x_min,
                g_min=gmin,
                theta=th,
            )
        )
        n = len(labeled)
        n_join = sum(1 for r in labeled if r.get("cs_joined"))
        n_switch = sum(1 for r in labeled if r.get("label") == LABEL_SWITCH)
        n_hold = sum(1 for r in labeled if r.get("label") == LABEL_HOLD)
        n_unlab = sum(1 for r in labeled if r.get("label") == LABEL_UNLABELED)
        n_needs = sum(1 for r in labeled if r.get("needs"))

        # Restrict agreement to labeled needs rows (switch or hold)
        labeled_needs = [
            r
            for r in labeled
            if r.get("needs") and r.get("label") in (LABEL_SWITCH, LABEL_HOLD)
        ]
        # teacher_fire predicts switch?
        t_pairs = [
            (bool(r.get("teacher_fire")), r.get("label") == LABEL_SWITCH)
            for r in labeled_needs
        ]
        # public_giveup predicts switch?
        p_pairs = [
            (bool(r.get("public_giveup")), r.get("label") == LABEL_SWITCH)
            for r in labeled_needs
        ]
        # reverse: switch predicts teacher_fire (oracle as detector of dead race)
        o_pairs = [
            (r.get("label") == LABEL_SWITCH, bool(r.get("teacher_fire")))
            for r in labeled_needs
        ]

        gains_switch = [
            float(r["eta_gain"])
            for r in labeled_needs
            if r.get("label") == LABEL_SWITCH and r.get("eta_gain") is not None
        ]
        gains_hold = [
            float(r["eta_gain"])
            for r in labeled_needs
            if r.get("label") == LABEL_HOLD and r.get("eta_gain") is not None
        ]

        def _mean(xs: List[float]) -> Optional[float]:
            return None if not xs else round(sum(xs) / len(xs), 4)

        # Separation: mean gain switch vs hold among needs with eta
        sep = None
        if gains_switch and gains_hold:
            sep = round(_mean(gains_switch) - _mean(gains_hold), 4)  # type: ignore

        # Usefulness gate (C5): labeled rate + separation
        labeled_rate = (n_switch + n_hold) / n if n else 0.0
        useful = bool(
            labeled_rate >= 0.15
            and n_switch >= 20
            and n_hold >= 20
            and (sep is None or sep > 0)
        )

        report[sp] = {
            "n_rows": n,
            "n_cs_joined": n_join,
            "join_rate": None if n == 0 else round(n_join / n, 4),
            "n_needs": n_needs,
            "label_hist": {
                LABEL_SWITCH: n_switch,
                LABEL_HOLD: n_hold,
                LABEL_UNLABELED: n_unlab,
            },
            "labeled_rate": round(labeled_rate, 4),
            "n_labeled_needs": len(labeled_needs),
            "teacher_predicts_switch": _acc_binary(t_pairs),
            "public_predicts_switch": _acc_binary(p_pairs),
            "switch_predicts_teacher_fire": _acc_binary(o_pairs),
            "mean_eta_gain_switch": _mean(gains_switch),
            "mean_eta_gain_hold": _mean(gains_hold),
            "eta_gain_separation": sep,
            "oracle_useful": useful,
            "g_min": gmin,
            "x_min": float(x_min),
        }
        if n_join < 0.5 * n:
            notes.append(f"{sp}: low CS join rate {n_join}/{n}")
        if n_switch < 20:
            notes.append(f"{sp}: few should_have_switched labels ({n_switch})")

    report["notes"] = notes
    # overall usefulness
    report["oracle_useful_any"] = any(
        bool((report.get(sp) or {}).get("oracle_useful")) for sp in ("la", "lr")
    )
    return report


def write_report(report: Mapping[str, Any], out_path: PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def format_console_report(report: Mapping[str, Any]) -> str:
    lines = [
        f"C counterfactual light  freeze={report.get('spec_freeze_id')}  "
        f"x_min={report.get('x_min')}  "
        f"samples={report.get('n_probe_samples')}  cs_idx={report.get('n_cs_index')}",
        f"probe_exists={report.get('probe_exists')} cs_exists={report.get('cs_exists')}",
    ]
    for sp in ("la", "lr"):
        blk = report.get(sp)
        if not isinstance(blk, Mapping) or not blk:
            continue
        hist = blk.get("label_hist") or {}
        t = blk.get("teacher_predicts_switch") or {}
        p = blk.get("public_predicts_switch") or {}
        o = blk.get("switch_predicts_teacher_fire") or {}
        lines.append(
            f"  {sp.upper()}: join={blk.get('join_rate')}  "
            f"labels switch/hold/unlab="
            f"{hist.get(LABEL_SWITCH)}/{hist.get(LABEL_HOLD)}/{hist.get(LABEL_UNLABELED)}  "
            f"useful={blk.get('oracle_useful')}"
        )
        lines.append(
            f"       teacher→switch P={t.get('precision')} R={t.get('recall')} F1={t.get('f1')}  "
            f"public→switch P={p.get('precision')} R={p.get('recall')}  "
            f"switch→teacher P={o.get('precision')} R={o.get('recall')}"
        )
        lines.append(
            f"       mean η_gain switch={blk.get('mean_eta_gain_switch')} "
            f"hold={blk.get('mean_eta_gain_hold')} sep={blk.get('eta_gain_separation')}"
        )
    for n in list(report.get("notes") or [])[:8]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


__all__ = [
    "C_G_MIN_LA",
    "C_G_MIN_LR",
    "C_SPEC_FREEZE_ID",
    "C_X_MIN_DEFAULT",
    "LABEL_HOLD",
    "LABEL_SWITCH",
    "LABEL_UNLABELED",
    "analyze_counterfactual",
    "format_console_report",
    "iter_counterfactual_rows",
    "label_should_switch",
    "load_cs_eta_index",
    "resolve_cs_path",
    "write_report",
]
