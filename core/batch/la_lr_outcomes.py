"""Phase L A: end-of-game specials outcomes from probe series + result.json.

Per (game, seat, special): claimed / stolen_lost / never_claimed_on_way /
never_on_way, plus flags gave_up_fired, still_on_way_end, abandoned_no_fire.

Offline dig only — no SE mutation.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from core.batch.la_lr_players_view_analyze import load_sample_rows, resolve_probe_path
from core.la_lr_probe_log import iter_la_lr_probe_rows

PathLike = Union[str, Path]

A_SPEC_FREEZE_ID: str = "L5_A_SPECIALS_OUTCOMES_v0"
A_SCHEMA: int = 1

# Primary race outcomes (mutually exclusive via precedence)
OUTCOME_CLAIMED = "claimed"
OUTCOME_STOLEN_LOST = "stolen_lost"
OUTCOME_NEVER_CLAIMED_ON_WAY = "never_claimed_on_way"
OUTCOME_NEVER_ON_WAY = "never_on_way"

PRIMARY_OUTCOMES: Tuple[str, ...] = (
    OUTCOME_CLAIMED,
    OUTCOME_STOLEN_LOST,
    OUTCOME_NEVER_CLAIMED_ON_WAY,
    OUTCOME_NEVER_ON_WAY,
)


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except Exception:
        return default


def _game_key(o: Mapping[str, Any]) -> str:
    seq = _safe_int(o.get("sequence_number"), None)
    if seq is not None:
        return f"seq:{seq}"
    gid = str(o.get("game_id") or "").strip()
    return f"gid:{gid or '?'}"


def _seq_of(o: Mapping[str, Any]) -> Optional[int]:
    return _safe_int(o.get("sequence_number"), None)


def load_all_probe_rows(probe_path: PathLike) -> List[Dict[str, Any]]:
    """All probe rows including dig events (fires, holder changes)."""
    return list(iter_la_lr_probe_rows(probe_path, include_fire_events=True))


def load_end_holders_from_batch(batch_dir: PathLike) -> Dict[int, Dict[str, Optional[int]]]:
    """seq → {la_holder_id, lr_holder_id} from gXXX/result.json."""
    batch = Path(batch_dir)
    out: Dict[int, Dict[str, Optional[int]]] = {}
    if not batch.is_dir():
        return out
    # Prefer batch_summary games list
    summary = batch / "batch_summary.json"
    if summary.is_file():
        try:
            raw = json.loads(summary.read_text(encoding="utf-8"))
            for g in list(raw.get("games") or []):
                if not isinstance(g, Mapping):
                    continue
                seq = _safe_int(g.get("sequence_number"))
                if seq is None:
                    continue
                out[int(seq)] = {
                    "la_holder_id": _safe_int(g.get("la_holder_id")),
                    "lr_holder_id": _safe_int(g.get("lr_holder_id")),
                }
        except Exception:
            pass
    # Fill gaps from per-game results
    for gdir in sorted(batch.glob("g*")):
        if not gdir.is_dir():
            continue
        rp = gdir / "result.json"
        if not rp.is_file():
            continue
        try:
            res = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        seq = _safe_int(res.get("sequence_number"))
        if seq is None:
            # g001 → 1
            try:
                seq = int(gdir.name.lstrip("g"))
            except Exception:
                continue
        if int(seq) in out:
            continue
        out[int(seq)] = {
            "la_holder_id": _safe_int(res.get("la_holder_id")),
            "lr_holder_id": _safe_int(res.get("lr_holder_id")),
        }
    return out


def _block_needs_holds(row: Mapping[str, Any], special: str) -> Tuple[bool, bool]:
    blk = row.get(special) if isinstance(row.get(special), Mapping) else {}
    needs = bool(blk.get("needs")) if blk else False
    holds = bool(blk.get("holds")) if blk else False
    return needs, holds


def reduce_seat_special(
    rows: Sequence[Mapping[str, Any]],
    *,
    player_id: int,
    special: str,
    end_holder_id: Optional[int],
) -> Dict[str, Any]:
    """Reduce chronological probe rows for one seat+special to outcome labels."""
    sp = str(special).lower()
    # Sort
    series = sorted(
        rows,
        key=lambda r: (
            _safe_int(r.get("round"), 0) or 0,
            _safe_int(r.get("turn"), 0) or 0,
            str(r.get("event") or ""),
        ),
    )
    ever_needs = False
    ever_holds = False
    last_needs = False
    last_holds = False
    n_samples = 0
    fired = False
    needs_true_then_false = False
    saw_needs_true = False

    for r in series:
        ev = str(r.get("event") or "sample")
        if ev in ("la_giveup_fire", "lr_giveup_fire"):
            if (sp == "la" and ev == "la_giveup_fire") or (
                sp == "lr" and ev == "lr_giveup_fire"
            ):
                fired = True
            continue
        if ev in ("salvage_adopt", "la_holder_changed", "lr_holder_changed"):
            # holder changes: treat as holds snapshot if in block
            needs, holds = _block_needs_holds(r, sp)
            if holds:
                ever_holds = True
            continue
        # sample-like
        needs, holds = _block_needs_holds(r, sp)
        n_samples += 1
        if needs:
            ever_needs = True
            saw_needs_true = True
        elif saw_needs_true:
            needs_true_then_false = True
        if holds:
            ever_holds = True
        last_needs = needs
        last_holds = holds

    end_holds = bool(
        last_holds
        or (
            end_holder_id is not None
            and player_id is not None
            and int(end_holder_id) == int(player_id)
        )
    )
    if end_holds:
        ever_holds = True

    # Primary outcome (precedence)
    if not ever_needs and not ever_holds:
        primary = OUTCOME_NEVER_ON_WAY
    elif end_holds:
        primary = OUTCOME_CLAIMED
    elif ever_holds and not end_holds:
        primary = OUTCOME_STOLEN_LOST
    elif ever_needs and not ever_holds:
        primary = OUTCOME_NEVER_CLAIMED_ON_WAY
    else:
        # needs sometime, held sometime, not end — already stolen_lost
        primary = OUTCOME_STOLEN_LOST if ever_holds else OUTCOME_NEVER_CLAIMED_ON_WAY

    abandoned_no_fire = bool(
        ever_needs
        and needs_true_then_false
        and not fired
        and not ever_holds
        and not last_needs
    )

    return {
        "primary": primary,
        "claimed_end": end_holds,
        "ever_needs": ever_needs,
        "ever_holds": ever_holds,
        "still_on_way_end": bool(last_needs),
        "gave_up_fired": fired,
        "abandoned_no_fire": abandoned_no_fire,
        "n_samples": n_samples,
        "end_holder_id": end_holder_id,
        "player_id": player_id,
        "special": sp,
    }


def build_game_seat_outcomes(
    probe_rows: Sequence[Mapping[str, Any]],
    end_holders: Mapping[int, Mapping[str, Optional[int]]],
) -> List[Dict[str, Any]]:
    """One record per (seq, player, special)."""
    by_game_seat: Dict[Tuple[int, int], List[Mapping[str, Any]]] = defaultdict(list)
    seats_seen: Dict[int, set] = defaultdict(set)

    for r in probe_rows:
        seq = _seq_of(r)
        pid = _safe_int(r.get("player_id"), None)
        if seq is None or pid is None:
            continue
        by_game_seat[(int(seq), int(pid))].append(r)
        seats_seen[int(seq)].add(int(pid))

    # Ensure seats 1..4 if present in end holders only — skip if no probe
    out: List[Dict[str, Any]] = []
    for (seq, pid), rows in sorted(by_game_seat.items()):
        holders = end_holders.get(int(seq)) or {}
        for sp in ("la", "lr"):
            hid = holders.get(f"{sp}_holder_id")
            red = reduce_seat_special(
                rows, player_id=int(pid), special=sp, end_holder_id=hid
            )
            red["sequence_number"] = int(seq)
            red["game_key"] = f"seq:{seq}"
            out.append(red)
    return out


def analyze_specials_outcomes(
    batch_dir: PathLike,
    *,
    probe_path: Optional[PathLike] = None,
) -> Dict[str, Any]:
    """Build specials_outcomes_report.json for a batch."""
    batch = Path(batch_dir)
    probe = resolve_probe_path(batch, probe_path)
    notes: List[str] = []
    report: Dict[str, Any] = {
        "schema": A_SCHEMA,
        "a": "A2_outcomes",
        "spec_freeze_id": A_SPEC_FREEZE_ID,
        "batch_dir": str(batch.resolve()),
        "probe_path": str(probe),
        "probe_exists": probe.is_file(),
        "notes": notes,
    }
    if not probe.is_file():
        notes.append(f"probe missing: {probe}")
        return report

    rows = load_all_probe_rows(probe)
    report["n_probe_rows"] = len(rows)
    holders = load_end_holders_from_batch(batch)
    report["n_games_with_holders"] = len(holders)

    outcomes = build_game_seat_outcomes(rows, holders)
    report["n_seat_special_records"] = len(outcomes)

    # Histograms per special
    for sp in ("la", "lr"):
        subset = [o for o in outcomes if o.get("special") == sp]
        prim = Counter(str(o.get("primary")) for o in subset)
        report[sp] = {
            "n": len(subset),
            "primary_hist": {k: int(prim.get(k, 0)) for k in PRIMARY_OUTCOMES},
            "flags": {
                "gave_up_fired": sum(1 for o in subset if o.get("gave_up_fired")),
                "still_on_way_end": sum(1 for o in subset if o.get("still_on_way_end")),
                "abandoned_no_fire": sum(1 for o in subset if o.get("abandoned_no_fire")),
                "ever_needs": sum(1 for o in subset if o.get("ever_needs")),
                "claimed_end": sum(1 for o in subset if o.get("claimed_end")),
            },
            # rates among ever_needs
            "among_ever_needs": _among_needs(subset),
            # fire vs outcome
            "fire_x_primary": _crosstab(
                subset,
                row_key=lambda o: bool(o.get("gave_up_fired")),
                col_key=lambda o: str(o.get("primary")),
                row_labels=("fired", "no_fire"),
                col_labels=PRIMARY_OUTCOMES,
            ),
        }

    # Compact sample records for dig (claimed / stolen / fired)
    samples = []
    for o in outcomes:
        if o.get("primary") in (OUTCOME_CLAIMED, OUTCOME_STOLEN_LOST) or o.get(
            "gave_up_fired"
        ):
            samples.append(
                {
                    "seq": o.get("sequence_number"),
                    "player_id": o.get("player_id"),
                    "special": o.get("special"),
                    "primary": o.get("primary"),
                    "fired": o.get("gave_up_fired"),
                    "still_on_way_end": o.get("still_on_way_end"),
                    "abandoned_no_fire": o.get("abandoned_no_fire"),
                }
            )
            if len(samples) >= 40:
                break
    report["sample_records"] = samples
    report["notes"] = notes
    return report


def _among_needs(subset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    need = [o for o in subset if o.get("ever_needs")]
    n = len(need)
    if n == 0:
        return {"n": 0}
    prim = Counter(str(o.get("primary")) for o in need)
    return {
        "n": n,
        "primary_hist": {k: int(prim.get(k, 0)) for k in PRIMARY_OUTCOMES},
        "claimed_rate": round(sum(1 for o in need if o.get("primary") == OUTCOME_CLAIMED) / n, 4),
        "stolen_lost_rate": round(
            sum(1 for o in need if o.get("primary") == OUTCOME_STOLEN_LOST) / n, 4
        ),
        "never_claimed_rate": round(
            sum(1 for o in need if o.get("primary") == OUTCOME_NEVER_CLAIMED_ON_WAY) / n,
            4,
        ),
        "fired_rate": round(sum(1 for o in need if o.get("gave_up_fired")) / n, 4),
        "abandoned_no_fire_rate": round(
            sum(1 for o in need if o.get("abandoned_no_fire")) / n, 4
        ),
        "still_on_way_end_rate": round(
            sum(1 for o in need if o.get("still_on_way_end")) / n, 4
        ),
    }


def _crosstab(
    rows: Sequence[Mapping[str, Any]],
    *,
    row_key,
    col_key,
    row_labels: Sequence[str],
    col_labels: Sequence[str],
) -> Dict[str, Any]:
    grid: Dict[str, Dict[str, int]] = {
        r: {c: 0 for c in col_labels} for r in row_labels
    }
    for o in rows:
        rk = "fired" if row_key(o) else "no_fire"
        ck = str(col_key(o))
        if rk not in grid:
            grid[rk] = {c: 0 for c in col_labels}
        if ck not in grid[rk]:
            grid[rk][ck] = 0
        grid[rk][ck] += 1
    return grid


def write_report(report: Mapping[str, Any], out_path: PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def format_console_report(report: Mapping[str, Any]) -> str:
    lines = [
        f"A specials outcomes  freeze={report.get('spec_freeze_id')}  "
        f"records={report.get('n_seat_special_records')}  "
        f"games_holders={report.get('n_games_with_holders')}",
    ]
    for sp in ("la", "lr"):
        blk = report.get(sp) if isinstance(report.get(sp), Mapping) else {}
        hist = blk.get("primary_hist") if isinstance(blk, Mapping) else {}
        flags = blk.get("flags") if isinstance(blk, Mapping) else {}
        among = blk.get("among_ever_needs") if isinstance(blk, Mapping) else {}
        lines.append(f"  {sp.upper()}: primary={dict(hist or {})}")
        lines.append(
            f"       flags fired={flags.get('gave_up_fired')} "
            f"still_on_way={flags.get('still_on_way_end')} "
            f"abandoned_no_fire={flags.get('abandoned_no_fire')}"
        )
        if isinstance(among, Mapping) and among.get("n"):
            lines.append(
                f"       among ever_needs n={among.get('n')}  "
                f"claimed={among.get('claimed_rate')}  "
                f"stolen={among.get('stolen_lost_rate')}  "
                f"never_claim={among.get('never_claimed_rate')}  "
                f"fired={among.get('fired_rate')}  "
                f"abandon_no_fire={among.get('abandoned_no_fire_rate')}"
            )
        fx = blk.get("fire_x_primary") if isinstance(blk, Mapping) else {}
        if fx:
            lines.append(f"       fire×primary={fx}")
    for n in list(report.get("notes") or [])[:6]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


__all__ = [
    "A_SPEC_FREEZE_ID",
    "OUTCOME_CLAIMED",
    "OUTCOME_NEVER_CLAIMED_ON_WAY",
    "OUTCOME_NEVER_ON_WAY",
    "OUTCOME_STOLEN_LOST",
    "PRIMARY_OUTCOMES",
    "analyze_specials_outcomes",
    "build_game_seat_outcomes",
    "format_console_report",
    "load_end_holders_from_batch",
    "reduce_seat_special",
    "write_report",
]
