"""Phase L E: unified specials process timeline (CS + la_lr_probe).

Loads probe dig/sample events and CS rows into per-(game, seat) timelines
and computes process KPIs (fires, kills, setbacks, salvage sequencing).

Offline dig only — no SE mutation.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

E_SPEC_FREEZE_ID: str = "L5_E_SPECIALS_PROCESS_v0"
E_SCHEMA: int = 1
SETBACK_THR: float = 1.0  # delta_turns ≥ this → eta_setback


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


def _game_key(o: Mapping[str, Any]) -> str:
    seq = _safe_int(o.get("sequence_number"), None)
    if seq is not None:
        return f"seq:{seq}"
    gid = str(o.get("game_id") or "").strip()
    return f"gid:{gid or '?'}"


def _seat_key(o: Mapping[str, Any]) -> Tuple[str, int]:
    pid = _safe_int(o.get("player_id"), -1) or -1
    return _game_key(o), int(pid)


def _time_key(o: Mapping[str, Any]) -> Tuple[int, int]:
    return (_safe_int(o.get("round"), 0) or 0, _safe_int(o.get("turn"), 0) or 0)


def _iter_jsonl(path: PathLike) -> Iterable[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if isinstance(o, dict):
                yield o


def load_probe_events(probe_path: PathLike) -> List[Dict[str, Any]]:
    """All probe rows as timeline events."""
    out: List[Dict[str, Any]] = []
    for o in _iter_jsonl(probe_path):
        ev = str(o.get("event") or "sample")
        # Normalize sample-like strategy refreshes
        if ev in ("after_strategy_refresh", "sample", ""):
            kind = "sample"
        elif ev in ("la_giveup_fire", "lr_giveup_fire"):
            kind = ev
        elif ev == "salvage_adopt":
            kind = "salvage_adopt"
        elif ev in ("la_holder_changed", "lr_holder_changed"):
            kind = ev
        else:
            kind = ev
        la = o.get("la") if isinstance(o.get("la"), Mapping) else {}
        lr = o.get("lr") if isinstance(o.get("lr"), Mapping) else {}
        special = None
        if kind == "la_giveup_fire":
            special = "la"
        elif kind == "lr_giveup_fire":
            special = "lr"
        elif kind == "salvage_adopt":
            # try payload
            special = str(o.get("special") or o.get("kill_special") or "").lower() or None
            if special not in ("la", "lr"):
                special = None
        out.append(
            {
                "source": "probe",
                "kind": kind,
                "raw_event": ev,
                "game_key": _game_key(o),
                "player_id": _safe_int(o.get("player_id"), -1),
                "round": _safe_int(o.get("round"), 0) or 0,
                "turn": _safe_int(o.get("turn"), 0) or 0,
                "special": special,
                "needs_la": bool(la.get("needs")) if la else None,
                "needs_lr": bool(lr.get("needs")) if lr else None,
                "gap_la": _safe_int(la.get("gap")),
                "gap_lr": _safe_int(lr.get("gap")),
                "way_id": _safe_int(o.get("way_id")),
                "sequence_number": _safe_int(o.get("sequence_number")),
            }
        )
    return out


def load_cs_events(
    cs_path: PathLike,
    *,
    setback_thr: float = SETBACK_THR,
) -> List[Dict[str, Any]]:
    """CS rows → process events (setback, way_kill, light divert hints)."""
    out: List[Dict[str, Any]] = []
    for o in _iter_jsonl(cs_path):
        base = {
            "source": "cs",
            "game_key": _game_key(o),
            "player_id": _safe_int(o.get("player_id"), -1),
            "round": _safe_int(o.get("round"), 0) or 0,
            "turn": _safe_int(o.get("turn"), 0) or 0,
            "way_id": _safe_int(o.get("sticky_way_id") or o.get("way_id")),
            "sequence_number": _safe_int(o.get("sequence_number")),
            "delta_turns": _safe_float(o.get("delta_turns")),
            "eta_locked": _safe_float(o.get("eta_locked")),
            "way_la": bool(o.get("way_la")),
            "way_lr": bool(o.get("way_lr")),
        }
        # Always emit a lightweight CS tick for optional dense timelines? Skip — too many.
        # way_kill
        wkk = o.get("way_kill_kind") or o.get("way_kill")
        if wkk:
            kind_s = str(wkk).upper()
            special = "la" if "LA" in kind_s else ("lr" if "LR" in kind_s else None)
            ev = dict(base)
            ev.update(
                {
                    "kind": "way_kill",
                    "special": special,
                    "way_kill_kind": str(wkk),
                    "raw_event": "way_kill",
                }
            )
            out.append(ev)
        # eta setback
        dt = _safe_float(o.get("delta_turns"))
        if dt is not None and float(dt) >= float(setback_thr):
            ev = dict(base)
            special = None
            if o.get("way_la") and not o.get("way_lr"):
                special = "la"
            elif o.get("way_lr") and not o.get("way_la"):
                special = "lr"
            elif o.get("way_la") and o.get("way_lr"):
                special = "both"
            ev.update(
                {
                    "kind": "eta_setback",
                    "special": special,
                    "raw_event": "eta_setback",
                    "delta_turns": dt,
                }
            )
            out.append(ev)
        # divert / specials hints from reasons
        inv = str(o.get("sticky_invalidate_reason") or "").lower()
        cause = str(o.get("way_switch_cause") or "").lower()
        pref = str(o.get("preference_source") or o.get("refresh_mode_detail") or "").lower()
        blob = inv + " " + cause + " " + pref
        if any(
            t in blob
            for t in (
                "specials_divert",
                "s55",
                "divert",
                "giveup",
                "lr_giveup",
                "la_giveup",
                "specials_dead",
            )
        ):
            ev = dict(base)
            special = None
            if "la" in blob and "lr" not in blob:
                special = "la"
            elif "lr" in blob and "la" not in blob:
                special = "lr"
            ev.update(
                {
                    "kind": "specials_divert_hint",
                    "special": special,
                    "raw_event": "specials_divert_hint",
                    "hint": blob[:120],
                }
            )
            out.append(ev)
    return out


def build_timelines(
    events: Sequence[Mapping[str, Any]],
) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
    """Group events by (game_key, player_id), sort by time then source priority."""
    # probe dig events slightly after cs at same tick for sequencing
    source_pri = {"cs": 0, "probe": 1}
    bags: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for e in events:
        gk = str(e.get("game_key") or "?")
        pid = int(e.get("player_id") if e.get("player_id") is not None else -1)
        bags[(gk, pid)].append(dict(e))
    for key in bags:
        bags[key].sort(
            key=lambda e: (
                int(e.get("round") or 0),
                int(e.get("turn") or 0),
                source_pri.get(str(e.get("source")), 5),
                str(e.get("kind") or ""),
            )
        )
    return dict(bags)


def _time_ord(e: Mapping[str, Any]) -> int:
    """Rough global order: round*10 + turn."""
    return int(e.get("round") or 0) * 10 + int(e.get("turn") or 0)


def compute_seat_kpis(
    timeline: Sequence[Mapping[str, Any]],
    *,
    special: Optional[str] = None,
) -> Dict[str, Any]:
    """KPIs for one seat timeline; optional filter special la|lr."""
    sp = str(special).lower() if special else None

    def _match(e: Mapping[str, Any]) -> bool:
        if sp is None:
            return True
        es = e.get("special")
        if es is None:
            # include unscoped setbacks/kills that might still matter
            if e.get("kind") in ("eta_setback", "specials_divert_hint"):
                return True
            return False
        return str(es).lower() == sp or str(es).lower() == "both"

    tl = [e for e in timeline if _match(e)]
    kinds = Counter(str(e.get("kind")) for e in tl)

    fires = [
        e
        for e in tl
        if e.get("kind") in ("la_giveup_fire", "lr_giveup_fire")
        and (sp is None or (sp == "la" and e.get("kind") == "la_giveup_fire") or (sp == "lr" and e.get("kind") == "lr_giveup_fire"))
    ]
    kills = [e for e in tl if e.get("kind") == "way_kill"]
    setbacks = [e for e in tl if e.get("kind") == "eta_setback"]
    salvages = [e for e in tl if e.get("kind") == "salvage_adopt"]
    diverts = [e for e in tl if e.get("kind") == "specials_divert_hint"]

    first_fire_t = _time_ord(fires[0]) if fires else None
    first_kill_t = _time_ord(kills[0]) if kills else None
    first_salvage_t = _time_ord(salvages[0]) if salvages else None

    # fire without prior kill/divert in timeline
    fire_without_prior_kill = 0
    fire_without_prior_divert = 0
    for f in fires:
        ft = _time_ord(f)
        if not any(_time_ord(k) <= ft for k in kills):
            fire_without_prior_kill += 1
        if not any(_time_ord(d) <= ft for d in diverts):
            fire_without_prior_divert += 1

    # setback within K turns of a kill (K=2 rounds-ish → order delta <= 20)
    setback_near_kill = 0
    for s in setbacks:
        st = _time_ord(s)
        if any(abs(_time_ord(k) - st) <= 20 for k in kills):
            setback_near_kill += 1

    # salvage after fire
    salvage_after_fire = 0
    if first_fire_t is not None:
        salvage_after_fire = sum(1 for s in salvages if _time_ord(s) >= first_fire_t)

    return {
        "n_events": len(tl),
        "kind_hist": dict(kinds),
        "n_fires": len(fires),
        "n_way_kills": len(kills),
        "n_eta_setbacks": len(setbacks),
        "n_salvage_adopts": len(salvages),
        "n_divert_hints": len(diverts),
        "first_fire_time": first_fire_t,
        "first_kill_time": first_kill_t,
        "first_salvage_time": first_salvage_t,
        "fires_without_prior_kill": fire_without_prior_kill,
        "fires_without_prior_divert_hint": fire_without_prior_divert,
        "setbacks_near_kill": setback_near_kill,
        "salvage_after_fire": salvage_after_fire,
        "has_fire": len(fires) > 0,
        "has_kill": len(kills) > 0,
        "has_salvage": len(salvages) > 0,
        "multi_fire": len(fires) >= 2,
    }


def analyze_specials_process(
    batch_dir: Optional[PathLike] = None,
    *,
    probe_path: Optional[PathLike] = None,
    cs_path: Optional[PathLike] = None,
    special: str = "both",
    setback_thr: float = SETBACK_THR,
    max_timeline_seats: int = 8,
) -> Dict[str, Any]:
    """Build process_specials_report for a batch."""
    batch = Path(batch_dir) if batch_dir is not None else None
    if probe_path is None:
        if batch is None:
            raise ValueError("batch_dir or probe_path required")
        probe = batch / "la_lr_probe.jsonl"
    else:
        probe = Path(probe_path)
    if cs_path is None:
        cs = (batch / "cs.jsonl") if batch is not None else Path("cs.jsonl")
    else:
        cs = Path(cs_path)

    notes: List[str] = []
    report: Dict[str, Any] = {
        "schema": E_SCHEMA,
        "e": "E3_process",
        "spec_freeze_id": E_SPEC_FREEZE_ID,
        "batch_dir": str(batch.resolve()) if batch is not None else None,
        "probe_path": str(probe),
        "cs_path": str(cs),
        "probe_exists": probe.is_file(),
        "cs_exists": cs.is_file(),
        "setback_thr": float(setback_thr),
        "special_focus": special,
        "notes": notes,
    }

    if not probe.is_file():
        notes.append(f"probe missing: {probe}")
    if not cs.is_file():
        notes.append(f"cs missing: {cs}")

    probe_ev = load_probe_events(probe) if probe.is_file() else []
    cs_ev = load_cs_events(cs, setback_thr=setback_thr) if cs.is_file() else []
    report["n_probe_events"] = len(probe_ev)
    report["n_cs_events"] = len(cs_ev)

    all_ev = list(probe_ev) + list(cs_ev)
    timelines = build_timelines(all_ev)
    report["n_seat_timelines"] = len(timelines)

    # Aggregate KPIs
    seats_all: List[Dict[str, Any]] = []
    for (gk, pid), tl in sorted(timelines.items()):
        kpi = compute_seat_kpis(tl, special=None)
        kpi.update({"game_key": gk, "player_id": pid})
        seats_all.append(kpi)

    def _agg(seat_kpis: Sequence[Mapping[str, Any]], prefix: str = "") -> Dict[str, Any]:
        n = len(seat_kpis)
        if n == 0:
            return {"n_seats": 0}
        return {
            "n_seats": n,
            "seats_with_fire": sum(1 for s in seat_kpis if s.get("has_fire")),
            "seats_with_kill": sum(1 for s in seat_kpis if s.get("has_kill")),
            "seats_with_salvage": sum(1 for s in seat_kpis if s.get("has_salvage")),
            "seats_multi_fire": sum(1 for s in seat_kpis if s.get("multi_fire")),
            "total_fires": sum(int(s.get("n_fires") or 0) for s in seat_kpis),
            "total_way_kills": sum(int(s.get("n_way_kills") or 0) for s in seat_kpis),
            "total_eta_setbacks": sum(int(s.get("n_eta_setbacks") or 0) for s in seat_kpis),
            "total_salvage": sum(int(s.get("n_salvage_adopts") or 0) for s in seat_kpis),
            "total_divert_hints": sum(int(s.get("n_divert_hints") or 0) for s in seat_kpis),
            "fires_without_prior_kill": sum(
                int(s.get("fires_without_prior_kill") or 0) for s in seat_kpis
            ),
            "fires_without_prior_divert_hint": sum(
                int(s.get("fires_without_prior_divert_hint") or 0) for s in seat_kpis
            ),
            "setbacks_near_kill": sum(int(s.get("setbacks_near_kill") or 0) for s in seat_kpis),
            "salvage_after_fire": sum(int(s.get("salvage_after_fire") or 0) for s in seat_kpis),
        }

    report["aggregate"] = _agg(seats_all)

    # Per-special seat KPIs
    for sp in ("la", "lr"):
        sk: List[Dict[str, Any]] = []
        for (gk, pid), tl in timelines.items():
            k = compute_seat_kpis(tl, special=sp)
            if (
                k.get("n_fires")
                or k.get("n_way_kills")
                or k.get("n_salvage_adopts")
                or k.get("n_eta_setbacks")
            ):
                k.update({"game_key": gk, "player_id": pid})
                sk.append(k)
        report[f"aggregate_{sp}"] = _agg(sk)
        report[f"n_active_seats_{sp}"] = len(sk)

    # Global kind hist
    kh: Counter = Counter()
    for e in all_ev:
        kh[str(e.get("kind"))] += 1
    report["kind_hist"] = dict(sorted(kh.items(), key=lambda x: -x[1]))

    # Sample timelines: seats with most fires
    ranked = sorted(seats_all, key=lambda s: (-int(s.get("n_fires") or 0), -int(s.get("n_way_kills") or 0)))
    samples = []
    for s in ranked[: max(0, int(max_timeline_seats))]:
        key = (str(s.get("game_key")), int(s.get("player_id")))
        tl = timelines.get(key) or []
        # compact event list
        compact = [
            {
                "r": e.get("round"),
                "t": e.get("turn"),
                "kind": e.get("kind"),
                "special": e.get("special"),
                "src": e.get("source"),
            }
            for e in tl
            if e.get("kind")
            not in (
                # keep setbacks but could be many — keep all for short timelines
            )
        ]
        # cap length
        if len(compact) > 80:
            compact = compact[:40] + [{"kind": "...truncated", "n": len(compact) - 80}] + compact[-40:]
        samples.append(
            {
                "game_key": s.get("game_key"),
                "player_id": s.get("player_id"),
                "kpi": {
                    k: s.get(k)
                    for k in (
                        "n_fires",
                        "n_way_kills",
                        "n_eta_setbacks",
                        "n_salvage_adopts",
                        "multi_fire",
                        "fires_without_prior_kill",
                        "salvage_after_fire",
                    )
                },
                "timeline": compact,
            }
        )
    report["sample_timelines"] = samples
    report["notes"] = notes
    return report


def write_report(report: Mapping[str, Any], out_path: PathLike) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def format_console_report(report: Mapping[str, Any]) -> str:
    lines = [
        f"E specials process  freeze={report.get('spec_freeze_id')}  "
        f"probe_ev={report.get('n_probe_events')} cs_ev={report.get('n_cs_events')}  "
        f"seats={report.get('n_seat_timelines')}",
        f"probe_exists={report.get('probe_exists')} cs_exists={report.get('cs_exists')}",
    ]
    agg = report.get("aggregate") if isinstance(report.get("aggregate"), Mapping) else {}
    lines.append(
        f"  ALL seats: fires={agg.get('total_fires')} kills={agg.get('total_way_kills')} "
        f"setbacks={agg.get('total_eta_setbacks')} salvage={agg.get('total_salvage')} "
        f"divert_hints={agg.get('total_divert_hints')}"
    )
    lines.append(
        f"       seats_with_fire={agg.get('seats_with_fire')} multi_fire={agg.get('seats_multi_fire')} "
        f"fire_wo_prior_kill={agg.get('fires_without_prior_kill')} "
        f"salvage_after_fire={agg.get('salvage_after_fire')}"
    )
    for sp in ("la", "lr"):
        a = report.get(f"aggregate_{sp}") if isinstance(report.get(f"aggregate_{sp}"), Mapping) else {}
        lines.append(
            f"  {sp.upper()}: active_seats={report.get(f'n_active_seats_{sp}')} "
            f"fires={a.get('total_fires')} kills={a.get('total_way_kills')} "
            f"salvage={a.get('total_salvage')} multi_fire={a.get('seats_multi_fire')}"
        )
    kh = report.get("kind_hist") if isinstance(report.get("kind_hist"), Mapping) else {}
    top = list(kh.items())[:8]
    lines.append(f"  kind_hist_top: {top}")
    for n in list(report.get("notes") or [])[:6]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


__all__ = [
    "E_SPEC_FREEZE_ID",
    "SETBACK_THR",
    "analyze_specials_process",
    "build_timelines",
    "compute_seat_kpis",
    "format_console_report",
    "load_cs_events",
    "load_probe_events",
    "write_report",
]
