"""Phase L D: path typology cuts (LA-only / LR-only / both / neither).

Sample-time needs-based typology for offline dig reports. No SE mutation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

D_SPEC_FREEZE_ID: str = "L5_D_TYPOLOGY_v0"
TYPOLOGY_LABELS: Tuple[str, ...] = ("la_only", "lr_only", "both", "neither")


def typology_from_needs(needs_la: bool, needs_lr: bool) -> str:
    """Return typology id from boolean needs flags."""
    la = bool(needs_la)
    lr = bool(needs_lr)
    if la and lr:
        return "both"
    if la and not lr:
        return "la_only"
    if lr and not la:
        return "lr_only"
    return "neither"


def typology_from_probe_row(row: Mapping[str, Any]) -> str:
    """Extract needs from probe row (la/lr blocks or flat keys)."""
    la = row.get("la") if isinstance(row.get("la"), Mapping) else {}
    lr = row.get("lr") if isinstance(row.get("lr"), Mapping) else {}
    needs_la = bool(la.get("needs")) if la else bool(row.get("needs_la") or row.get("needs_LA"))
    needs_lr = bool(lr.get("needs")) if lr else bool(row.get("needs_lr") or row.get("needs_LR"))
    # annotated sample dicts
    if "needs_la" in row or "needs_lr" in row:
        needs_la = bool(row.get("needs_la", needs_la))
        needs_lr = bool(row.get("needs_lr", needs_lr))
    return typology_from_needs(needs_la, needs_lr)


def empty_typology_hist() -> Dict[str, int]:
    return {k: 0 for k in TYPOLOGY_LABELS}


def summarize_typology_counts(
    samples: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Histogram of typology over samples (needs from annotated or probe-shaped rows)."""
    hist = Counter({k: 0 for k in TYPOLOGY_LABELS})
    for s in samples:
        t = typology_from_probe_row(s)
        if t not in hist:
            hist[t] = 0
        hist[t] += 1
    n = sum(hist.values())
    rates = {
        k: (None if n == 0 else round(hist[k] / n, 4)) for k in TYPOLOGY_LABELS
    }
    return {
        "spec_freeze_id": D_SPEC_FREEZE_ID,
        "n_rows": n,
        "hist": {k: int(hist.get(k, 0)) for k in TYPOLOGY_LABELS},
        "rate": rates,
    }


def summarize_typology_with_flags(
    samples: Sequence[Mapping[str, Any]],
    *,
    teacher_key_la: str = "teacher_fire_la",
    teacher_key_lr: str = "teacher_fire_lr",
    public_key_la: str = "public_giveup_la",
    public_key_lr: str = "public_giveup_lr",
    chase_key_la: str = "public_chase_la",
    chase_key_lr: str = "public_chase_lr",
) -> Dict[str, Any]:
    """Per-typology rates for teacher fire / public fire / chase (when keys present)."""
    buckets: Dict[str, List[Mapping[str, Any]]] = {k: [] for k in TYPOLOGY_LABELS}
    for s in samples:
        t = typology_from_probe_row(s)
        buckets.setdefault(t, []).append(s)

    def _rate(xs: Sequence[Mapping[str, Any]], key: str) -> Optional[float]:
        if not xs:
            return None
        present = [x for x in xs if key in x]
        if not present:
            return None
        return round(sum(1 for x in present if x.get(key)) / len(present), 4)

    by_type: Dict[str, Any] = {}
    for t in TYPOLOGY_LABELS:
        xs = buckets.get(t) or []
        by_type[t] = {
            "n": len(xs),
            "teacher_fire_la_rate": _rate(xs, teacher_key_la),
            "teacher_fire_lr_rate": _rate(xs, teacher_key_lr),
            "public_giveup_la_rate": _rate(xs, public_key_la),
            "public_giveup_lr_rate": _rate(xs, public_key_lr),
            "public_chase_la_rate": _rate(xs, chase_key_la),
            "public_chase_lr_rate": _rate(xs, chase_key_lr),
            # convenience: any teacher / public for the typology's specials
            "teacher_fire_relevant_rate": _relevant_fire_rate(xs, t),
            "public_giveup_relevant_rate": _relevant_public_rate(xs, t),
        }

    base = summarize_typology_counts(samples)
    base["by_typology"] = by_type
    return base


def _relevant_fire_rate(xs: Sequence[Mapping[str, Any]], typology: str) -> Optional[float]:
    if not xs:
        return None
    hits = 0
    n = 0
    for x in xs:
        if typology == "la_only":
            if "teacher_fire_la" not in x:
                continue
            n += 1
            if x.get("teacher_fire_la"):
                hits += 1
        elif typology == "lr_only":
            if "teacher_fire_lr" not in x:
                continue
            n += 1
            if x.get("teacher_fire_lr"):
                hits += 1
        elif typology == "both":
            if "teacher_fire_la" not in x and "teacher_fire_lr" not in x:
                continue
            n += 1
            if x.get("teacher_fire_la") or x.get("teacher_fire_lr"):
                hits += 1
        else:  # neither — teacher fire should be rare
            if "teacher_fire_la" not in x and "teacher_fire_lr" not in x:
                continue
            n += 1
            if x.get("teacher_fire_la") or x.get("teacher_fire_lr"):
                hits += 1
    return None if n == 0 else round(hits / n, 4)


def _relevant_public_rate(xs: Sequence[Mapping[str, Any]], typology: str) -> Optional[float]:
    if not xs:
        return None
    hits = 0
    n = 0
    for x in xs:
        if typology == "la_only":
            if "public_giveup_la" not in x:
                continue
            n += 1
            if x.get("public_giveup_la"):
                hits += 1
        elif typology == "lr_only":
            if "public_giveup_lr" not in x:
                continue
            n += 1
            if x.get("public_giveup_lr"):
                hits += 1
        elif typology == "both":
            if "public_giveup_la" not in x and "public_giveup_lr" not in x:
                continue
            n += 1
            if x.get("public_giveup_la") or x.get("public_giveup_lr"):
                hits += 1
        else:
            if "public_giveup_la" not in x and "public_giveup_lr" not in x:
                continue
            n += 1
            if x.get("public_giveup_la") or x.get("public_giveup_lr"):
                hits += 1
    return None if n == 0 else round(hits / n, 4)


def format_typology_console(block: Mapping[str, Any]) -> str:
    hist = block.get("hist") if isinstance(block.get("hist"), Mapping) else {}
    lines = [
        f"D typology  freeze={block.get('spec_freeze_id')}  n={block.get('n_rows')}",
        f"  hist: {dict(hist)}",
    ]
    by_t = block.get("by_typology") if isinstance(block.get("by_typology"), Mapping) else {}
    if by_t:
        lines.append(
            f"  {'type':8} {'n':>6} {'t_fire':>8} {'p_give':>8} {'chase_la':>8} {'chase_lr':>8}"
        )
        for t in TYPOLOGY_LABELS:
            b = by_t.get(t) if isinstance(by_t.get(t), Mapping) else {}
            lines.append(
                f"  {t:8} {str(b.get('n')):>6} "
                f"{str(b.get('teacher_fire_relevant_rate')):>8} "
                f"{str(b.get('public_giveup_relevant_rate')):>8} "
                f"{str(b.get('public_chase_la_rate')):>8} "
                f"{str(b.get('public_chase_lr_rate')):>8}"
            )
    return "\n".join(lines)


__all__ = [
    "D_SPEC_FREEZE_ID",
    "TYPOLOGY_LABELS",
    "empty_typology_hist",
    "format_typology_console",
    "summarize_typology_counts",
    "summarize_typology_with_flags",
    "typology_from_needs",
    "typology_from_probe_row",
]
