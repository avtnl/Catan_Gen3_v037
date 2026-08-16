"""Phase L J: thrash dashboard for LA/LR specials (probe digs + sample series).

KPIs: multi-fire, way_id churn while needs, needs re-enter after fire,
salvage-then-refire. Offline dig only — no SE mutation.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from core.batch.la_lr_players_view_analyze import resolve_probe_path
from core.la_lr_probe_log import iter_la_lr_probe_rows

PathLike = Union[str, Path]

J_SPEC_FREEZE_ID: str = "L5_J_THRASH_v0"
J_SCHEMA: int = 1


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except Exception:
        return default


def _seq(o: Mapping[str, Any]) -> Optional[int]:
    return _safe_int(o.get("sequence_number"), None)


def _pid(o: Mapping[str, Any]) -> Optional[int]:
    return _safe_int(o.get("player_id"), None)


def _time_ord(o: Mapping[str, Any]) -> Tuple[int, int, str]:
    return (
        _safe_int(o.get("round"), 0) or 0,
        _safe_int(o.get("turn"), 0) or 0,
        str(o.get("event") or ""),
    )


def _needs_holds(row: Mapping[str, Any], special: str) -> Tuple[bool, bool]:
    blk = row.get(special) if isinstance(row.get(special), Mapping) else {}
    return bool(blk.get("needs")), bool(blk.get("holds"))


def reduce_seat_special_thrash(
    rows: Sequence[Mapping[str, Any]],
    *,
    special: str,
) -> Dict[str, Any]:
    """Thrash KPIs for one (game, seat, special) probe series."""
    sp = str(special).lower()
    series = sorted(rows, key=_time_ord)

    n_fires = 0
    fire_times: List[Tuple[int, int]] = []
    salvage_times: List[Tuple[int, int]] = []
    way_ids_while_needs: set = set()
    needs_flips_up = 0  # false → true
    prev_needs: Optional[bool] = None
    saw_fire = False
    reenter_after_fire = 0
    needs_after_fire_seen_false = False

    for r in series:
        ev = str(r.get("event") or "sample")
        rnd = _safe_int(r.get("round"), 0) or 0
        turn = _safe_int(r.get("turn"), 0) or 0
        tkey = (rnd, turn)

        if ev == f"{sp}_giveup_fire" or (
            (sp == "la" and ev == "la_giveup_fire")
            or (sp == "lr" and ev == "lr_giveup_fire")
        ):
            n_fires += 1
            fire_times.append(tkey)
            saw_fire = True
            needs_after_fire_seen_false = False
            continue

        if ev == "salvage_adopt":
            # attribute if special matches payload or unknown
            sev = str(r.get("special") or "").lower()
            if sev in ("", sp, "both") or sev not in ("la", "lr"):
                salvage_times.append(tkey)
            continue

        # sample-like refreshes
        if ev not in (
            "after_strategy_refresh",
            "sample",
            "",
            "la_holder_changed",
            "lr_holder_changed",
        ):
            # still try needs from block
            pass

        needs, holds = _needs_holds(r, sp)
        if prev_needs is not None and (not prev_needs) and needs:
            needs_flips_up += 1
            if saw_fire and needs_after_fire_seen_false:
                reenter_after_fire += 1
        if saw_fire and not needs:
            needs_after_fire_seen_false = True
        prev_needs = needs

        if needs:
            wid = _safe_int(r.get("way_id"), None)
            if wid is not None and wid > 0:
                way_ids_while_needs.add(int(wid))

    # salvage then later fire
    salvage_then_refire = 0
    for st in salvage_times:
        if any(
            (ft[0] > st[0] or (ft[0] == st[0] and ft[1] > st[1]))
            for ft in fire_times
        ):
            salvage_then_refire += 1
            break  # count once per seat-special

    return {
        "special": sp,
        "n_fires": n_fires,
        "multi_fire": n_fires >= 2,
        "n_distinct_ways_while_needs": len(way_ids_while_needs),
        "way_churn": len(way_ids_while_needs) >= 2,
        "needs_flips_up": needs_flips_up,
        "reenter_after_fire": reenter_after_fire,
        "salvage_then_refire": salvage_then_refire > 0,
        "n_salvage_events": len(salvage_times),
        "way_ids": sorted(way_ids_while_needs)[:12],
    }


def analyze_thrash(
    batch_dir: PathLike,
    *,
    probe_path: Optional[PathLike] = None,
) -> Dict[str, Any]:
    """Build thrash_specials_report.json for a batch."""
    batch = Path(batch_dir)
    probe = resolve_probe_path(batch, probe_path)
    notes: List[str] = []
    report: Dict[str, Any] = {
        "schema": J_SCHEMA,
        "j": "J3_thrash",
        "spec_freeze_id": J_SPEC_FREEZE_ID,
        "batch_dir": str(batch.resolve()),
        "probe_path": str(probe),
        "probe_exists": probe.is_file(),
        "notes": notes,
    }
    if not probe.is_file():
        notes.append(f"probe missing: {probe}")
        return report

    rows = list(iter_la_lr_probe_rows(probe, include_fire_events=True))
    report["n_probe_rows"] = len(rows)

    by_key: Dict[Tuple[int, int], List[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        seq = _seq(r)
        pid = _pid(r)
        if seq is None or pid is None:
            continue
        by_key[(int(seq), int(pid))].append(r)

    records: List[Dict[str, Any]] = []
    for (seq, pid), seat_rows in sorted(by_key.items()):
        for sp in ("la", "lr"):
            red = reduce_seat_special_thrash(seat_rows, special=sp)
            red["sequence_number"] = seq
            red["player_id"] = pid
            records.append(red)

    report["n_seat_special_records"] = len(records)

    for sp in ("la", "lr"):
        sub = [r for r in records if r.get("special") == sp]
        n = len(sub)
        multi = [r for r in sub if r.get("multi_fire")]
        churn = [r for r in sub if r.get("way_churn")]
        reenter = [r for r in sub if int(r.get("reenter_after_fire") or 0) > 0]
        salv_refire = [r for r in sub if r.get("salvage_then_refire")]
        fires_total = sum(int(r.get("n_fires") or 0) for r in sub)
        fire_hist = Counter(int(r.get("n_fires") or 0) for r in sub)

        report[sp] = {
            "n_seats": n,
            "fires_total": fires_total,
            "seats_with_fire": sum(1 for r in sub if int(r.get("n_fires") or 0) > 0),
            "multi_fire_seats": len(multi),
            "multi_fire_rate": None if n == 0 else round(len(multi) / n, 4),
            "way_churn_seats": len(churn),
            "way_churn_rate": None if n == 0 else round(len(churn) / n, 4),
            "reenter_after_fire_seats": len(reenter),
            "reenter_after_fire_rate": None if n == 0 else round(len(reenter) / n, 4),
            "salvage_then_refire_seats": len(salv_refire),
            "salvage_then_refire_rate": None if n == 0 else round(len(salv_refire) / n, 4),
            "fires_per_seat_hist": {str(k): int(v) for k, v in sorted(fire_hist.items())},
            "mean_fires_given_fire": _mean(
                [int(r.get("n_fires") or 0) for r in sub if int(r.get("n_fires") or 0) > 0]
            ),
            "mean_ways_while_needs": _mean(
                [
                    int(r.get("n_distinct_ways_while_needs") or 0)
                    for r in sub
                    if int(r.get("n_distinct_ways_while_needs") or 0) > 0
                ]
            ),
        }

    # Overall multi_fire across specials (seat counts either special)
    seat_fire: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(lambda: {"la": 0, "lr": 0})
    for r in records:
        key = (int(r.get("sequence_number") or 0), int(r.get("player_id") or 0))
        seat_fire[key][str(r.get("special"))] = int(r.get("n_fires") or 0)

    multi_any = sum(
        1
        for v in seat_fire.values()
        if v.get("la", 0) >= 2 or v.get("lr", 0) >= 2
    )
    multi_both = sum(
        1 for v in seat_fire.values() if v.get("la", 0) >= 1 and v.get("lr", 0) >= 1
    )
    report["aggregate"] = {
        "n_game_seats": len(seat_fire),
        "multi_fire_seats_any_special": multi_any,
        "seats_with_both_la_and_lr_fire": multi_both,
        "la_multi_fire_seats": report["la"]["multi_fire_seats"],
        "lr_multi_fire_seats": report["lr"]["multi_fire_seats"],
    }

    # Top thrash samples
    ranked = sorted(
        records,
        key=lambda r: (
            -int(r.get("n_fires") or 0),
            -int(r.get("n_distinct_ways_while_needs") or 0),
            -int(r.get("reenter_after_fire") or 0),
        ),
    )
    report["top_thrash"] = [
        {
            "seq": r.get("sequence_number"),
            "player_id": r.get("player_id"),
            "special": r.get("special"),
            "n_fires": r.get("n_fires"),
            "ways": r.get("n_distinct_ways_while_needs"),
            "reenter": r.get("reenter_after_fire"),
            "salvage_refire": r.get("salvage_then_refire"),
            "way_ids": r.get("way_ids"),
        }
        for r in ranked[:25]
        if int(r.get("n_fires") or 0) >= 1
        or int(r.get("n_distinct_ways_while_needs") or 0) >= 2
    ]

    # Gate-ish note: multi_fire expectation
    la_m = report["la"]["multi_fire_seats"]
    lr_m = report["lr"]["multi_fire_seats"]
    if la_m + lr_m == 0:
        notes.append("no multi_fire seats (ideal one-fire world)")
    else:
        notes.append(
            f"multi_fire seats LA={la_m} LR={lr_m} — check one-fire episode release / dual specials"
        )

    report["notes"] = notes
    return report


def _mean(xs: Sequence[int]) -> Optional[float]:
    if not xs:
        return None
    return round(sum(xs) / len(xs), 4)


def write_report(report: Mapping[str, Any], out_path: PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def format_console_report(report: Mapping[str, Any]) -> str:
    lines = [
        f"J thrash  freeze={report.get('spec_freeze_id')}  "
        f"records={report.get('n_seat_special_records')}  "
        f"probe_rows={report.get('n_probe_rows')}",
    ]
    agg = report.get("aggregate") if isinstance(report.get("aggregate"), Mapping) else {}
    lines.append(
        f"  game_seats={agg.get('n_game_seats')}  "
        f"multi_fire_any={agg.get('multi_fire_seats_any_special')}  "
        f"both_LA_and_LR_fire={agg.get('seats_with_both_la_and_lr_fire')}"
    )
    for sp in ("la", "lr"):
        b = report.get(sp) if isinstance(report.get(sp), Mapping) else {}
        lines.append(
            f"  {sp.upper()}: fires={b.get('fires_total')}  "
            f"seats_fire={b.get('seats_with_fire')}  "
            f"multi={b.get('multi_fire_seats')}  "
            f"churn={b.get('way_churn_seats')}  "
            f"reenter={b.get('reenter_after_fire_seats')}  "
            f"salv_refire={b.get('salvage_then_refire_seats')}  "
            f"mean_fires|fire={b.get('mean_fires_given_fire')}  "
            f"hist={b.get('fires_per_seat_hist')}"
        )
    for n in list(report.get("notes") or [])[:6]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


__all__ = [
    "J_SPEC_FREEZE_ID",
    "analyze_thrash",
    "format_console_report",
    "reduce_seat_special_thrash",
    "write_report",
]
