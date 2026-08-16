"""Phase L L4-3: offline players_view ambition vs god-view needs agreement.

Reads ``la_lr_probe.jsonl`` (sample rows only), builds public features + ambition
labels, measures agreement with teacher ``needs_*``. No SE mutation.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from core.la_lr_players_view import (
    AMBITION_LABELS,
    PLAYERS_VIEW_SCHEMA_VERSION,
    SERIES_DELTA_K,
    SPEC_FREEZE_ID,
    ambition_constants_v0,
    apply_series_deltas,
    build_public_features_from_probe_row,
    is_probe_sample_row,
    label_ambitions,
)
from core.la_lr_probe_log import iter_la_lr_probe_rows

PathLike = Union[str, Path]


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except Exception:
        return default


def _game_seat_key(row: Mapping[str, Any]) -> Tuple[str, int]:
    seq = _safe_int(row.get("sequence_number"), None)
    if seq is not None:
        gk = f"seq:{seq}"
    else:
        gid = str(row.get("game_id") or "").strip() or "?"
        gk = f"gid:{gid}"
    pid = _safe_int(row.get("player_id"), -1)
    return gk, int(pid if pid is not None else -1)


def _sort_key(row: Mapping[str, Any]) -> Tuple[int, int, int]:
    return (
        _safe_int(row.get("round"), 0) or 0,
        _safe_int(row.get("turn"), 0) or 0,
        _safe_int(row.get("player_id"), 0) or 0,
    )


def _needs_of(row: Mapping[str, Any], special: str) -> bool:
    blk = row.get(special)
    if isinstance(blk, Mapping) and "needs" in blk:
        return bool(blk.get("needs"))
    # flat fallbacks
    if special == "la":
        return bool(row.get("needs_la") or row.get("needs_LA"))
    return bool(row.get("needs_lr") or row.get("needs_LR"))


def _prf(tp: int, fp: int, tn: int, fn: int) -> Dict[str, Any]:
    prec = (tp / (tp + fp)) if (tp + fp) > 0 else None
    rec = (tp / (tp + fn)) if (tp + fn) > 0 else None
    if prec is not None and rec is not None and (prec + rec) > 0:
        f1 = 2.0 * prec * rec / (prec + rec)
    else:
        f1 = None
    return {
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "precision": None if prec is None else round(prec, 4),
        "recall": None if rec is None else round(rec, 4),
        "f1": None if f1 is None else round(f1, 4),
        "n": int(tp + fp + tn + fn),
        "support_needs_true": int(tp + fn),
        "support_needs_false": int(fp + tn),
    }


def _empty_special_block() -> Dict[str, Any]:
    return {
        "ambition_hist": {lab: 0 for lab in AMBITION_LABELS},
        "agreement_vs_needs": _prf(0, 0, 0, 0),
        "confusion_ambition_x_needs": {},
        "n_rows": 0,
    }


def resolve_probe_path(
    batch_dir: Optional[PathLike] = None,
    probe_path: Optional[PathLike] = None,
) -> Path:
    if probe_path is not None:
        return Path(probe_path)
    if batch_dir is None:
        raise ValueError("batch_dir or probe_path required")
    return Path(batch_dir) / "la_lr_probe.jsonl"


def load_sample_rows(probe: PathLike) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in iter_la_lr_probe_rows(probe, include_fire_events=False):
        if not isinstance(row, dict):
            continue
        if not is_probe_sample_row(row):
            continue
        rows.append(row)
    return rows


def iter_annotated_samples(
    rows: Sequence[Mapping[str, Any]],
) -> Iterable[Dict[str, Any]]:
    """Yield public features + ambition + teachers, with per-seat series Δ."""
    by_key: Dict[Tuple[str, int], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_key[_game_seat_key(row)].append(row)

    for key in sorted(by_key.keys(), key=lambda k: (k[0], k[1])):
        series = sorted(by_key[key], key=_sort_key)
        hist_army: List[int] = []
        hist_path: List[int] = []
        for row in series:
            feat = build_public_features_from_probe_row(row)
            # Prior = previous sample within K window (L4-0 SERIES_DELTA_K)
            prior_a = hist_army[-1] if hist_army else None
            prior_p = hist_path[-1] if hist_path else None
            series_len = len(hist_army) + 1
            feat = apply_series_deltas(
                feat,
                prior_army=prior_a,
                prior_path=prior_p,
                series_len=series_len,
            )
            labels = label_ambitions(feat)
            needs_la = _needs_of(row, "la")
            needs_lr = _needs_of(row, "lr")
            rec = {
                **feat,
                **labels,
                "needs_la": needs_la,
                "needs_lr": needs_lr,
                "teacher_way_id": row.get("way_id"),  # dig only; not a public feature input
            }
            # Optional secondary teachers if present on row blocks
            la = row.get("la") if isinstance(row.get("la"), Mapping) else {}
            lr = row.get("lr") if isinstance(row.get("lr"), Mapping) else {}
            rec["teacher_kill_la"] = bool(la.get("kill_recommended"))
            rec["teacher_kill_lr"] = bool(lr.get("kill_recommended"))
            rec["teacher_hopeless_la"] = bool(la.get("hopeless"))
            rec["teacher_hopeless_lr"] = bool(lr.get("hopeless"))
            yield rec

            hist_army.append(int(feat.get("army") or 0))
            hist_path.append(int(feat.get("path") or 0))
            if len(hist_army) > int(SERIES_DELTA_K):
                hist_army = hist_army[-int(SERIES_DELTA_K) :]
                hist_path = hist_path[-int(SERIES_DELTA_K) :]


def _accumulate_special(
    samples: Sequence[Mapping[str, Any]],
    special: str,
) -> Dict[str, Any]:
    amb_key = f"ambition_{special}"
    chase_key = f"public_chase_{special}"
    needs_key = f"needs_{special}"
    hist = Counter({lab: 0 for lab in AMBITION_LABELS})
    conf: Counter = Counter()
    tp = fp = tn = fn = 0
    n = 0
    for s in samples:
        amb = str(s.get(amb_key) or "none")
        if amb not in hist:
            hist[amb] = 0
        hist[amb] += 1
        needs = bool(s.get(needs_key))
        chase = bool(s.get(chase_key))
        conf[f"{amb}|needs={int(needs)}"] += 1
        if chase and needs:
            tp += 1
        elif chase and not needs:
            fp += 1
        elif (not chase) and needs:
            fn += 1
        else:
            tn += 1
        n += 1
    return {
        "ambition_hist": {lab: int(hist.get(lab, 0)) for lab in AMBITION_LABELS},
        "agreement_vs_needs": _prf(tp, fp, tn, fn),
        "confusion_ambition_x_needs": dict(sorted(conf.items())),
        "n_rows": n,
    }


def analyze_players_view(
    batch_dir: Optional[PathLike] = None,
    *,
    probe_path: Optional[PathLike] = None,
    special: str = "both",
) -> Dict[str, Any]:
    """Build L4 agreement report for a batch or probe file.

    ``special``: ``la`` | ``lr`` | ``both`` (both always fills la+lr blocks;
    filter only affects ``focus`` metadata).
    """
    batch = Path(batch_dir) if batch_dir is not None else None
    probe = resolve_probe_path(batch_dir, probe_path)
    notes: List[str] = []
    sp = str(special or "both").strip().lower()
    if sp not in ("la", "lr", "both"):
        sp = "both"
        notes.append(f"unknown special; using both")

    report: Dict[str, Any] = {
        "schema": PLAYERS_VIEW_SCHEMA_VERSION,
        "spec_freeze_id": SPEC_FREEZE_ID,
        "l4": "L4-3",
        "batch_dir": str(batch.resolve()) if batch is not None else None,
        "probe_path": str(probe.resolve()) if probe.exists() else str(probe),
        "probe_exists": probe.is_file(),
        "special_focus": sp,
        "n_sample_rows": 0,
        "n_annotated": 0,
        "ambition_constants": ambition_constants_v0(),
        "la": _empty_special_block(),
        "lr": _empty_special_block(),
        "notes": notes,
    }

    if not probe.is_file():
        notes.append(f"probe file missing: {probe}")
        report["notes"] = notes
        return report

    rows = load_sample_rows(probe)
    report["n_sample_rows"] = len(rows)
    if not rows:
        notes.append("no sample rows after excluding fire/salvage events")
        report["notes"] = notes
        return report

    samples = list(iter_annotated_samples(rows))
    report["n_annotated"] = len(samples)
    report["la"] = _accumulate_special(samples, "la")
    report["lr"] = _accumulate_special(samples, "lr")

    # D: typology cuts (needs_la / needs_lr)
    try:
        from core.batch.la_lr_typology import summarize_typology_with_flags

        report["typology"] = summarize_typology_with_flags(samples)
    except Exception as exc:
        notes.append(f"typology_error:{exc}")
        report["typology"] = {}

    # Brief face-validity hints
    for side in ("la", "lr"):
        agr = report[side]["agreement_vs_needs"]
        hist = report[side]["ambition_hist"]
        if agr.get("support_needs_true", 0) == 0:
            notes.append(f"{side}: no needs=True samples (agreement vs needs uninformative)")
        if sum(hist.values()) > 0 and hist.get("none", 0) == sum(hist.values()):
            notes.append(f"{side}: all ambition=none (rules never fired)")

    report["notes"] = notes
    return report


def write_report(report: Mapping[str, Any], out_path: PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def write_samples_csv(
    batch_dir: Optional[PathLike] = None,
    *,
    probe_path: Optional[PathLike] = None,
    out_path: Optional[PathLike] = None,
) -> Optional[Path]:
    """Optional per-sample CSV (public features + ambition + teachers)."""
    probe = resolve_probe_path(batch_dir, probe_path)
    if not probe.is_file():
        return None
    rows = load_sample_rows(probe)
    samples = list(iter_annotated_samples(rows))
    if out_path is None:
        base = Path(batch_dir) if batch_dir else probe.parent
        out = base / "players_view_samples.csv"
    else:
        out = Path(out_path)
    if not samples:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("", encoding="utf-8")
        return out

    # Stable column order
    preferred = [
        "game_key",
        "player_id",
        "round",
        "turn",
        "event",
        "army",
        "path",
        "gap_la",
        "gap_lr",
        "n_threats_la",
        "n_threats_lr",
        "army_leader",
        "path_leader",
        "holds_la",
        "holds_lr",
        "roads_remaining_cap",
        "legal_roads",
        "delta_army",
        "delta_path",
        "delta_active",
        "ambition_la",
        "ambition_lr",
        "public_chase_la",
        "public_chase_lr",
        "needs_la",
        "needs_lr",
        "teacher_kill_la",
        "teacher_kill_lr",
        "teacher_hopeless_la",
        "teacher_hopeless_lr",
        "teacher_way_id",
    ]
    fieldnames = list(preferred)
    for s in samples:
        for k in s.keys():
            if k not in fieldnames:
                fieldnames.append(k)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for s in samples:
            w.writerow({k: s.get(k) for k in fieldnames})
    return out


def format_console_report(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append(
        f"L4 players_view  freeze={report.get('spec_freeze_id')}  "
        f"samples={report.get('n_sample_rows')}  annotated={report.get('n_annotated')}"
    )
    lines.append(f"probe={report.get('probe_path')}  exists={report.get('probe_exists')}")
    for side in ("la", "lr"):
        blk = report.get(side) if isinstance(report.get(side), Mapping) else {}
        agr = blk.get("agreement_vs_needs") if isinstance(blk.get("agreement_vs_needs"), Mapping) else {}
        hist = blk.get("ambition_hist") if isinstance(blk.get("ambition_hist"), Mapping) else {}
        lines.append(
            f"  {side.upper()}: hist={dict(hist)}  "
            f"chase_vs_needs P={agr.get('precision')} R={agr.get('recall')} "
            f"F1={agr.get('f1')}  "
            f"tp/fp/tn/fn={agr.get('tp')}/{agr.get('fp')}/{agr.get('tn')}/{agr.get('fn')}"
        )
    typ = report.get("typology") if isinstance(report.get("typology"), Mapping) else None
    if typ:
        try:
            from core.batch.la_lr_typology import format_typology_console

            lines.append(format_typology_console(typ))
        except Exception:
            lines.append(f"  typology hist={typ.get('hist')}")
    for n in list(report.get("notes") or [])[:8]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


__all__ = [
    "analyze_players_view",
    "format_console_report",
    "iter_annotated_samples",
    "load_sample_rows",
    "resolve_probe_path",
    "write_report",
    "write_samples_csv",
]
