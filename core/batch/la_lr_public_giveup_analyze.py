"""Phase L L5-3: offline public give-up proxy vs god-view teacher fire@θ.

Reads ``la_lr_probe.jsonl`` sample rows, builds L4 public features + ambition,
L5-2 rule A (MVP) and score B, L5-1 teacher fire@θ. Agreement + FGU tables.
No SE mutation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from core.batch.la_lr_players_view_analyze import (
    load_sample_rows,
    resolve_probe_path,
)
from core.la_lr_players_view import (
    SERIES_DELTA_K,
    apply_series_deltas,
    build_public_features_from_probe_row,
)
from core.la_lr_public_giveup import (
    GATE_FGU_MAX,
    GATE_PRECISION_MIN,
    GATE_SOFT_PRECISION_MIN,
    LR_PROXY_DEFAULT_VARIANT,
    PROXY_MVP_VARIANT,
    PUBLIC_GIVEUP_SCHEMA_VERSION,
    SPEC_FREEZE_ID,
    THETA_LA_SAFE,
    THETA_LR_SAFE,
    build_teacher_record,
    l5_freeze_snapshot,
    list_lr_rule_variants,
    public_giveup_flag_rule_a,
    public_giveup_score,
)

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


def _agreement(tp: int, fp: int, tn: int, fn: int) -> Dict[str, Any]:
    prec = (tp / (tp + fp)) if (tp + fp) > 0 else None
    rec = (tp / (tp + fn)) if (tp + fn) > 0 else None
    if prec is not None and rec is not None and (prec + rec) > 0:
        f1 = 2.0 * prec * rec / (prec + rec)
    else:
        f1 = None
    # FGU among teacher negatives (public fire when teacher says no)
    fgu = (fp / (fp + tn)) if (fp + tn) > 0 else None
    return {
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "precision": None if prec is None else round(prec, 4),
        "recall": None if rec is None else round(rec, 4),
        "f1": None if f1 is None else round(f1, 4),
        "fgu_rate": None if fgu is None else round(fgu, 4),
        "n": int(tp + fp + tn + fn),
        "n_teacher_fire": int(tp + fn),
        "n_teacher_hold": int(fp + tn),
    }


def _empty_agreement() -> Dict[str, Any]:
    return _agreement(0, 0, 0, 0)


def iter_joined_samples(
    rows: Sequence[Mapping[str, Any]],
    *,
    theta_la: Optional[float] = None,
    theta_lr: Optional[float] = None,
    score_b_phi: Optional[float] = None,
    lr_variant: Optional[str] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield joined public features + proxies + teacher per sample (with series Δ)."""
    lr_v = lr_variant or LR_PROXY_DEFAULT_VARIANT
    by_key: Dict[Tuple[str, int], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_key[_game_seat_key(row)].append(row)

    for key in sorted(by_key.keys(), key=lambda k: (k[0], k[1])):
        series = sorted(by_key[key], key=_sort_key)
        hist_army: List[int] = []
        hist_path: List[int] = []
        for row in series:
            feat = build_public_features_from_probe_row(row)
            prior_a = hist_army[-1] if hist_army else None
            prior_p = hist_path[-1] if hist_path else None
            feat = apply_series_deltas(
                feat,
                prior_army=prior_a,
                prior_path=prior_p,
                series_len=len(hist_army) + 1,
            )
            t_la = build_teacher_record(row, "la", theta=theta_la)
            t_lr = build_teacher_record(row, "lr", theta=theta_lr)
            ra_la = public_giveup_flag_rule_a(feat, "la")
            ra_lr = public_giveup_flag_rule_a(feat, "lr", lr_variant=lr_v)
            sb_la = public_giveup_score(feat, "la", phi=score_b_phi)
            sb_lr = public_giveup_score(feat, "lr", phi=score_b_phi)
            try:
                from core.la_lr_players_view import label_ambitions

                amb = label_ambitions(feat)
            except Exception:
                amb = {}

            yield {
                "game_key": key[0],
                "player_id": key[1],
                "round": feat.get("round"),
                "turn": feat.get("turn"),
                "features": feat,
                "needs_la": bool(t_la.get("needs")),
                "needs_lr": bool(t_lr.get("needs")),
                "holds_la": bool(t_la.get("holds")),
                "holds_lr": bool(t_lr.get("holds")),
                "score_la": t_la.get("score"),
                "score_lr": t_lr.get("score"),
                "teacher_fire_la": bool(t_la.get("teacher_fire")),
                "teacher_fire_lr": bool(t_lr.get("teacher_fire")),
                "teacher_skip_la": list(t_la.get("skip_reasons") or []),
                "teacher_skip_lr": list(t_lr.get("skip_reasons") or []),
                "public_giveup_la": bool(ra_la.get("public_giveup")),
                "public_giveup_lr": bool(ra_lr.get("public_giveup")),
                "public_reason_la": ra_la.get("reason"),
                "public_reason_lr": ra_lr.get("reason"),
                "score_b_la": sb_la.get("score"),
                "score_b_lr": sb_lr.get("score"),
                "public_giveup_score_b_la": bool(sb_la.get("public_giveup")),
                "public_giveup_score_b_lr": bool(sb_lr.get("public_giveup")),
                "ambition_la": amb.get("ambition_la"),
                "ambition_lr": amb.get("ambition_lr"),
                "public_chase_la": bool(amb.get("public_chase_la")),
                "public_chase_lr": bool(amb.get("public_chase_lr")),
            }

            hist_army.append(int(feat.get("army") or 0))
            hist_path.append(int(feat.get("path") or 0))
            if len(hist_army) > int(SERIES_DELTA_K):
                hist_army = hist_army[-int(SERIES_DELTA_K) :]
                hist_path = hist_path[-int(SERIES_DELTA_K) :]


def _accumulate(
    samples: Sequence[Mapping[str, Any]],
    special: str,
    *,
    public_key: str,
    teacher_key: str,
    needs_key: str,
    needs_only: bool,
) -> Dict[str, Any]:
    tp = fp = tn = fn = 0
    n_needs = 0
    n_pub = 0
    n_teach = 0
    n = 0
    reason_hist: Dict[str, int] = defaultdict(int)
    for s in samples:
        needs = bool(s.get(needs_key))
        if needs_only and not needs:
            continue
        if needs:
            n_needs += 1
        pub = bool(s.get(public_key))
        teach = bool(s.get(teacher_key))
        if pub:
            n_pub += 1
        if teach:
            n_teach += 1
        n += 1
        if pub and teach:
            tp += 1
        elif pub and not teach:
            fp += 1
        elif (not pub) and teach:
            fn += 1
        else:
            tn += 1
        rk = f"public_reason_{special}"
        reason_hist[str(s.get(rk) or "?")] += 1

    agr = _agreement(tp, fp, tn, fn)
    return {
        "n_rows": n,
        "n_needs": n_needs if not needs_only else n,
        "teacher_fire_count": n_teach,
        "public_fire_count": n_pub,
        "teacher_fire_rate": None if n == 0 else round(n_teach / n, 4),
        "public_fire_rate": None if n == 0 else round(n_pub / n, 4),
        "agreement": agr,
        "public_reason_hist": dict(sorted(reason_hist.items())),
    }


def _gate_eval(agr: Mapping[str, Any]) -> Dict[str, Any]:
    """Preliminary L5-5 style gate on one agreement block (needs-conditioned)."""
    prec = agr.get("precision")
    fgu = agr.get("fgu_rate")
    n = int(agr.get("n") or 0)
    if n <= 0 or prec is None:
        return {"status": "no_data", "pass": False, "soft_pass": False}
    hard = float(prec) >= GATE_PRECISION_MIN and (
        fgu is None or float(fgu) <= GATE_FGU_MAX
    )
    soft = float(prec) >= GATE_SOFT_PRECISION_MIN
    if hard:
        status = "pass"
    elif soft:
        status = "soft_pass"
    else:
        status = "fail"
    return {
        "status": status,
        "pass": hard,
        "soft_pass": soft and not hard,
        "precision": prec,
        "fgu_rate": fgu,
        "bars": {
            "precision_min": GATE_PRECISION_MIN,
            "fgu_max": GATE_FGU_MAX,
            "soft_precision_min": GATE_SOFT_PRECISION_MIN,
        },
    }


def analyze_public_giveup(
    batch_dir: Optional[PathLike] = None,
    *,
    probe_path: Optional[PathLike] = None,
    special: str = "both",
    theta_la: Optional[float] = None,
    theta_lr: Optional[float] = None,
    score_b_phi: Optional[float] = None,
    lr_variant: Optional[str] = None,
) -> Dict[str, Any]:
    """Build L5 public_giveup_report for a batch or probe file."""
    batch = Path(batch_dir) if batch_dir is not None else None
    probe = resolve_probe_path(batch_dir, probe_path)
    notes: List[str] = []
    sp = str(special or "both").strip().lower()
    if sp not in ("la", "lr", "both"):
        sp = "both"
        notes.append("unknown special; using both")

    th_la = float(theta_la) if theta_la is not None else THETA_LA_SAFE
    th_lr = float(theta_lr) if theta_lr is not None else THETA_LR_SAFE
    lr_v = lr_variant or LR_PROXY_DEFAULT_VARIANT

    report: Dict[str, Any] = {
        "schema": PUBLIC_GIVEUP_SCHEMA_VERSION,
        "l5": "L5-3",
        "spec_freeze_id": SPEC_FREEZE_ID,
        "batch_dir": str(batch.resolve()) if batch is not None else None,
        "probe_path": str(probe.resolve()) if probe.exists() else str(probe),
        "probe_exists": probe.is_file(),
        "special_focus": sp,
        "theta_la": th_la,
        "theta_lr": th_lr,
        "proxy_variant": PROXY_MVP_VARIANT,
        "lr_variant": lr_v,
        "n_sample_rows": 0,
        "n_annotated": 0,
        "freeze": l5_freeze_snapshot(),
        "la": {
            "rule_a_needs_conditioned": {
                "n_rows": 0,
                "agreement": _empty_agreement(),
            },
            "rule_a_all_samples": {
                "n_rows": 0,
                "agreement": _empty_agreement(),
            },
            "score_b_needs_conditioned": {
                "n_rows": 0,
                "agreement": _empty_agreement(),
            },
            "gate_rule_a_needs": {"status": "no_data"},
        },
        "lr": {
            "rule_a_needs_conditioned": {
                "n_rows": 0,
                "agreement": _empty_agreement(),
            },
            "rule_a_all_samples": {
                "n_rows": 0,
                "agreement": _empty_agreement(),
            },
            "score_b_needs_conditioned": {
                "n_rows": 0,
                "agreement": _empty_agreement(),
            },
            "gate_rule_a_needs": {"status": "no_data"},
        },
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

    samples = list(
        iter_joined_samples(
            rows,
            theta_la=th_la,
            theta_lr=th_lr,
            score_b_phi=score_b_phi,
            lr_variant=lr_v,
        )
    )
    report["n_annotated"] = len(samples)

    # D: typology cuts
    try:
        from core.batch.la_lr_typology import summarize_typology_with_flags

        report["typology"] = summarize_typology_with_flags(samples)
    except Exception as exc:
        notes.append(f"typology_error:{exc}")
        report["typology"] = {}

    for side in ("la", "lr"):
        ra_needs = _accumulate(
            samples,
            side,
            public_key=f"public_giveup_{side}",
            teacher_key=f"teacher_fire_{side}",
            needs_key=f"needs_{side}",
            needs_only=True,
        )
        ra_all = _accumulate(
            samples,
            side,
            public_key=f"public_giveup_{side}",
            teacher_key=f"teacher_fire_{side}",
            needs_key=f"needs_{side}",
            needs_only=False,
        )
        sb_needs = _accumulate(
            samples,
            side,
            public_key=f"public_giveup_score_b_{side}",
            teacher_key=f"teacher_fire_{side}",
            needs_key=f"needs_{side}",
            needs_only=True,
        )
        gate = _gate_eval(ra_needs.get("agreement") or {})
        report[side] = {
            "rule_a_needs_conditioned": ra_needs,
            "rule_a_all_samples": ra_all,
            "score_b_needs_conditioned": sb_needs,
            "gate_rule_a_needs": gate,
        }
        if ra_needs.get("n_rows", 0) == 0:
            notes.append(f"{side}: no needs-conditioned rows (gate uninformative)")
        elif int((ra_needs.get("agreement") or {}).get("n_teacher_fire") or 0) == 0:
            notes.append(f"{side}: no teacher_fire among needs rows")

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


def analyze_lr_variant_grid(
    batch_dir: Optional[PathLike] = None,
    *,
    probe_path: Optional[PathLike] = None,
    variants: Optional[Sequence[str]] = None,
    theta_lr: Optional[float] = None,
) -> Dict[str, Any]:
    """G1/G2: evaluate all (or listed) LR rule profiles on one batch."""
    batch = Path(batch_dir) if batch_dir is not None else None
    probe = resolve_probe_path(batch_dir, probe_path)
    names = list(variants) if variants else list_lr_rule_variants()
    rows_out: List[Dict[str, Any]] = []
    best_pass: Optional[Dict[str, Any]] = None
    best_soft: Optional[Dict[str, Any]] = None
    best_f1: Optional[Dict[str, Any]] = None

    for name in names:
        rep = analyze_public_giveup(
            batch,
            probe_path=probe,
            special="lr",
            theta_lr=theta_lr,
            lr_variant=name,
        )
        lr = rep.get("lr") if isinstance(rep.get("lr"), Mapping) else {}
        needs = lr.get("rule_a_needs_conditioned") if isinstance(lr, Mapping) else {}
        agr = (needs or {}).get("agreement") if isinstance(needs, Mapping) else {}
        gate = lr.get("gate_rule_a_needs") if isinstance(lr, Mapping) else {}
        row = {
            "variant": name,
            "n_rows": (needs or {}).get("n_rows"),
            "teacher_fire_count": (needs or {}).get("teacher_fire_count"),
            "public_fire_count": (needs or {}).get("public_fire_count"),
            "precision": (agr or {}).get("precision"),
            "recall": (agr or {}).get("recall"),
            "f1": (agr or {}).get("f1"),
            "fgu_rate": (agr or {}).get("fgu_rate"),
            "gate": (gate or {}).get("status"),
            "pass": bool((gate or {}).get("pass")),
            "soft_pass": bool((gate or {}).get("soft_pass")),
        }
        rows_out.append(row)
        if row["pass"]:
            if best_pass is None or float(row["f1"] or 0) > float(best_pass.get("f1") or 0):
                best_pass = row
        if row["soft_pass"] or row["pass"]:
            if best_soft is None or float(row["f1"] or 0) > float(best_soft.get("f1") or 0):
                best_soft = row
        if row.get("f1") is not None:
            if best_f1 is None or float(row["f1"]) > float(best_f1.get("f1") or 0):
                best_f1 = row

    return {
        "schema": PUBLIC_GIVEUP_SCHEMA_VERSION,
        "g": "G1_lr_grid",
        "spec_freeze_id": SPEC_FREEZE_ID,
        "batch_dir": str(batch.resolve()) if batch is not None else None,
        "probe_path": str(probe),
        "probe_exists": probe.is_file(),
        "theta_lr": float(theta_lr) if theta_lr is not None else THETA_LR_SAFE,
        "variants": rows_out,
        "best_pass": best_pass,
        "best_soft_or_pass": best_soft,
        "best_f1": best_f1,
        "gate_bars": {
            "precision_min": GATE_PRECISION_MIN,
            "fgu_max": GATE_FGU_MAX,
            "soft_precision_min": GATE_SOFT_PRECISION_MIN,
        },
    }


def format_console_report(report: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append(
        f"L5 public_giveup  freeze={report.get('spec_freeze_id')}  "
        f"proxy={report.get('proxy_variant')}  lr_variant={report.get('lr_variant')}  "
        f"samples={report.get('n_sample_rows')}  annotated={report.get('n_annotated')}"
    )
    lines.append(
        f"θ_LA={report.get('theta_la')}  θ_LR={report.get('theta_lr')}  "
        f"probe_exists={report.get('probe_exists')}"
    )
    for side in ("la", "lr"):
        blk = report.get(side) if isinstance(report.get(side), Mapping) else {}
        needs = blk.get("rule_a_needs_conditioned") if isinstance(blk, Mapping) else {}
        agr = (needs or {}).get("agreement") if isinstance(needs, Mapping) else {}
        gate = blk.get("gate_rule_a_needs") if isinstance(blk, Mapping) else {}
        lines.append(
            f"  {side.upper()} rule_a needs: n={needs.get('n_rows') if isinstance(needs, Mapping) else 0}  "
            f"P={agr.get('precision') if isinstance(agr, Mapping) else None}  "
            f"R={agr.get('recall') if isinstance(agr, Mapping) else None}  "
            f"FGU={agr.get('fgu_rate') if isinstance(agr, Mapping) else None}  "
            f"gate={gate.get('status') if isinstance(gate, Mapping) else '?'}"
        )
        sb = blk.get("score_b_needs_conditioned") if isinstance(blk, Mapping) else {}
        sba = (sb or {}).get("agreement") if isinstance(sb, Mapping) else {}
        if isinstance(sba, Mapping) and sba.get("n"):
            lines.append(
                f"       score_b needs: P={sba.get('precision')}  "
                f"R={sba.get('recall')}  FGU={sba.get('fgu_rate')}"
            )
    for n in list(report.get("notes") or [])[:8]:
        lines.append(f"  note: {n}")
    typ = report.get("typology") if isinstance(report.get("typology"), Mapping) else None
    if typ:
        try:
            from core.batch.la_lr_typology import format_typology_console

            lines.append(format_typology_console(typ))
        except Exception:
            lines.append(f"  typology hist={typ.get('hist')}")
    return "\n".join(lines)


def format_lr_grid_console(grid: Mapping[str, Any]) -> str:
    lines = [
        f"G LR variant grid  batch={grid.get('batch_dir')}  "
        f"θ_LR={grid.get('theta_lr')}",
        f"{'variant':20} {'n':>6} {'P':>7} {'R':>7} {'F1':>7} {'FGU':>7} gate",
    ]
    for row in list(grid.get("variants") or []):
        lines.append(
            f"{str(row.get('variant')):20} "
            f"{str(row.get('n_rows')):>6} "
            f"{str(row.get('precision')):>7} "
            f"{str(row.get('recall')):>7} "
            f"{str(row.get('f1')):>7} "
            f"{str(row.get('fgu_rate')):>7} "
            f"{row.get('gate')}"
        )
    if grid.get("best_pass"):
        lines.append(f"best_pass: {grid['best_pass']}")
    elif grid.get("best_soft_or_pass"):
        lines.append(f"best_soft: {grid['best_soft_or_pass']}")
    else:
        lines.append(f"best_f1 (no pass): {grid.get('best_f1')}")
    return "\n".join(lines)


__all__ = [
    "analyze_lr_variant_grid",
    "analyze_public_giveup",
    "format_console_report",
    "format_lr_grid_console",
    "iter_joined_samples",
    "write_report",
]
