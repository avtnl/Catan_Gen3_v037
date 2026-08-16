"""Phase C WP-C2: offline CS strategy probe (setback + way + target + anomalies).

Reads Change-Strategy JSONL (schema v1 or v2), optionally scopes to batch
``game_id``s, classifies events via ``strategy_change_taxonomy``, and builds a
``CatanStrategyProbeReport`` dict.

Pure lab tooling — no Game mutation, no pygame requirement.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from core.batch.strategy_change_taxonomy import (
    ACHIEVE_TARGET_CLASSES,
    SETBACK_THRESHOLD_DEFAULT,
    TARGET_THRASH_PER_ROUND_DEFAULT,
    classify_setback,
    classify_target_change,
    classify_way_change,
    detect_anomalies,
    hard_board_evidence_from_classes,
    is_setback,
)

REPORT_SCHEMA = "CatanStrategyProbeReport"
REPORT_VERSION = 1
DEFAULT_MAX_EVENTS_PER_PROBE = 300

PathLike = Union[str, Path]


# ── Load / filter ────────────────────────────────────────────────────────────


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        if f != f:
            return default
        return f
    except Exception:
        return default


def load_cs_jsonl(
    path: PathLike,
    *,
    max_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Load CS JSONL. Returns ``{ok, path, rows, skipped_bad, skipped_comment, error}``."""
    p = Path(path)
    result: Dict[str, Any] = {
        "ok": False,
        "path": str(p.resolve()) if p.exists() else str(p),
        "rows": [],
        "skipped_bad": 0,
        "skipped_comment": 0,
        "error": "",
    }
    if not p.is_file():
        result["error"] = f"CS file not found: {p}"
        return result
    rows: List[Dict[str, Any]] = []
    bad = 0
    comments = 0
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                raw = line.strip()
                if not raw:
                    continue
                if raw.startswith("#"):
                    comments += 1
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    bad += 1
                    continue
                if not isinstance(obj, Mapping):
                    bad += 1
                    continue
                row = dict(obj)
                row["_file_index"] = line_no
                rows.append(row)
                if max_rows is not None and len(rows) >= int(max_rows):
                    break
    except Exception as exc:
        result["error"] = str(exc)
        return result
    result["ok"] = True
    result["rows"] = rows
    result["skipped_bad"] = bad
    result["skipped_comment"] = comments
    return result


def load_batch_game_ids(batch_dir: PathLike) -> Dict[str, Any]:
    """Load ``game_id``s (and optional winner map) from batch_summary / g*/result.json."""
    root = Path(batch_dir)
    out: Dict[str, Any] = {
        "ok": False,
        "batch_dir": str(root),
        "batch_id": None,
        "game_ids": [],
        "winners_by_game": {},
        "cs_paths": [],
        "error": "",
    }
    if not root.is_dir():
        out["error"] = f"batch dir not found: {root}"
        return out

    summary_path = root / "batch_summary.json"
    game_ids: List[str] = []
    winners: Dict[str, Any] = {}
    cs_paths: List[str] = []

    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary, Mapping):
                out["batch_id"] = summary.get("batch_id")
                # WP-C4: prefer batch-level CS path from summary
                if summary.get("cs_log_path"):
                    cs_paths.append(str(summary["cs_log_path"]))
                for g in list(summary.get("games") or []):
                    if not isinstance(g, Mapping):
                        continue
                    gid = str(g.get("game_id") or "").strip()
                    if gid:
                        game_ids.append(gid)
                        winners[gid] = g.get("winner_id")
                    rp = g.get("result_path")
                    if rp:
                        try:
                            rp_path = Path(str(rp))
                            if rp_path.is_file():
                                res = json.loads(rp_path.read_text(encoding="utf-8"))
                                if isinstance(res, Mapping) and res.get("cs_log_path"):
                                    cs_paths.append(str(res["cs_log_path"]))
                        except Exception:
                            pass
        except Exception as exc:
            out["error"] = f"batch_summary read failed: {exc}"

    # Also scan g00N/result.json
    for child in sorted(root.glob("g*/result.json")):
        try:
            res = json.loads(child.read_text(encoding="utf-8"))
            if not isinstance(res, Mapping):
                continue
            gid = str(res.get("game_id") or "").strip()
            if gid and gid not in game_ids:
                game_ids.append(gid)
            if gid and gid not in winners:
                winners[gid] = res.get("winner_id")
            if res.get("cs_log_path"):
                cs_paths.append(str(res["cs_log_path"]))
        except Exception:
            continue

    # Per-batch cs.jsonl if present (WP-C4 default name)
    for name in ("cs.jsonl", "cs.txt"):
        cand = root / name
        if cand.is_file():
            cs_paths.insert(0, str(cand.resolve()))

    # de-dupe preserve order
    seen: Set[str] = set()
    uniq_ids: List[str] = []
    for g in game_ids:
        if g not in seen:
            seen.add(g)
            uniq_ids.append(g)
    seen_cs: Set[str] = set()
    uniq_cs: List[str] = []
    for c in cs_paths:
        if c not in seen_cs:
            seen_cs.add(c)
            uniq_cs.append(c)

    out["ok"] = True
    out["game_ids"] = uniq_ids
    out["winners_by_game"] = winners
    out["cs_paths"] = uniq_cs
    return out


def filter_rows_by_game_ids(
    rows: Sequence[Mapping[str, Any]],
    game_ids: Optional[Sequence[str]],
) -> List[Dict[str, Any]]:
    if not game_ids:
        return [dict(r) for r in rows]
    allow = {str(g) for g in game_ids if g}
    if not allow:
        return [dict(r) for r in rows]
    out: List[Dict[str, Any]] = []
    for r in rows:
        gid = str(r.get("game_id") or "").strip()
        if gid in allow:
            out.append(dict(r))
    return out


def default_cs_path() -> str:
    try:
        from core.batch.result import resolve_cs_log_path

        return resolve_cs_log_path()
    except Exception:
        try:
            from core.constants import FILENAME_CS

            return os.path.abspath(str(FILENAME_CS))
        except Exception:
            return os.path.abspath("Catan_CS.txt")


# ── Ordering / grouping ──────────────────────────────────────────────────────


def _sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        _safe_int(row.get("round"), -1) if _safe_int(row.get("round"), -1) is not None else -1,
        _safe_int(row.get("turn"), -1) if _safe_int(row.get("turn"), -1) is not None else -1,
        str(row.get("ts") or ""),
        _safe_int(row.get("_file_index"), 0) or 0,
    )


def group_rows_by_player(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
    """Group by (game_id, player_id); each group sorted in time order."""
    groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        gid = str(r.get("game_id") or "") or "_nogame"
        pid = _safe_int(r.get("player_id"))
        if pid is None:
            continue
        groups[(gid, int(pid))].append(dict(r))
    for key in groups:
        groups[key].sort(key=_sort_key)
    return dict(groups)


def _way_ids(row: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    way = _safe_int(row.get("sticky_way_id"), _safe_int(row.get("way_id")))
    prev = _safe_int(
        row.get("prev_sticky_way_id"),
        _safe_int(row.get("prev_way_id")),
    )
    return way, prev


def _target_ids(row: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    tid = _safe_int(row.get("sticky_target_id"), _safe_int(row.get("rec_target_id")))
    prev = _safe_int(row.get("prev_sticky_target_id"))
    return tid, prev


def _detect_way_event(row: Mapping[str, Any], prev: Optional[Mapping[str, Any]]) -> bool:
    """True only when preferred/sticky way actually appears or changes in the stream.

    Do **not** trust stale ``is_first_way_lock`` alone — sticky apply may leave
    that flag on ``last_sticky_meta`` for many subsequent CS rows.
    """
    if row.get("way_changed") is True:
        return True
    if str(row.get("sample_kind") or "") == "way_change":
        return True
    way, row_prev_way = _way_ids(row)
    if row_prev_way is not None and way is not None and row_prev_way != way:
        return True
    if prev is None:
        # First sample for this seat/game: count as first_lock if a way exists
        return way is not None
    pway = _safe_int(prev.get("sticky_way_id"), _safe_int(prev.get("way_id")))
    if pway is not None and way is not None and pway != way:
        return True
    # True first lock in stream: prev had no way, now has one
    if pway is None and way is not None:
        return True
    return False


def _detect_target_event(row: Mapping[str, Any], prev: Optional[Mapping[str, Any]]) -> bool:
    """True only when sticky/rec target appears or changes in the stream.

    Stale ``is_first_target_lock`` alone is not enough (same as way).
    """
    if row.get("target_changed") is True:
        return True
    if str(row.get("sample_kind") or "") == "target_change":
        return True
    tid, row_prev_tid = _target_ids(row)
    if row_prev_tid is not None and tid is not None and row_prev_tid != tid:
        return True
    if prev is None:
        return tid is not None
    ptid = _safe_int(prev.get("sticky_target_id"), _safe_int(prev.get("rec_target_id")))
    if ptid is not None and tid is not None and ptid != tid:
        return True
    if ptid is None and tid is not None:
        return True
    return False


def _holder_ctx(
    row: Mapping[str, Any], prev: Optional[Mapping[str, Any]]
) -> Dict[str, bool]:
    ctx = {"la_holder_changed": False, "lr_holder_changed": False}
    if not prev:
        return ctx
    la_a = _safe_int(row.get("la_holder_id"))
    la_b = _safe_int(prev.get("la_holder_id"))
    lr_a = _safe_int(row.get("lr_holder_id"))
    lr_b = _safe_int(prev.get("lr_holder_id"))
    if la_a != la_b and not (la_a is None and la_b is None):
        ctx["la_holder_changed"] = True
    if lr_a != lr_b and not (lr_a is None and lr_b is None):
        ctx["lr_holder_changed"] = True
    return ctx


def _base_event(
    row: Mapping[str, Any],
    *,
    event_type: str,
    primary_class: str,
    tags: Sequence[str],
    confidence: str,
    evidence: Sequence[str],
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    way, prev_way = _way_ids(row)
    tid, prev_tid = _target_ids(row)
    ev: Dict[str, Any] = {
        "event_type": event_type,
        "game_id": str(row.get("game_id") or "") or None,
        "sequence_number": _safe_int(row.get("sequence_number")),
        "player_id": _safe_int(row.get("player_id")),
        "color": str(row.get("color") or "") or None,
        "round": _safe_int(row.get("round")),
        "turn": _safe_int(row.get("turn")),
        "reason": str(row.get("reason") or "") or None,
        "sample_kind": str(row.get("sample_kind") or "") or None,
        "primary_class": primary_class,
        "tags": list(tags or []),
        "confidence": confidence,
        "evidence": list(evidence or []),
        "way_id": way,
        "prev_way_id": prev_way,
        "sticky_target_id": tid,
        "prev_sticky_target_id": prev_tid,
        "turns": _safe_float(row.get("turns")),
        "prev_turns": _safe_float(row.get("prev_turns")),
        "delta_turns": _safe_float(row.get("delta_turns")),
        "way_switch_cause": row.get("way_switch_cause"),
        "target_switch_cause": row.get("target_switch_cause"),
        "sticky_invalidate_reason": row.get("sticky_invalidate_reason"),
        "achieve_kind": row.get("achieve_kind"),
        "file_index": row.get("_file_index"),
    }
    if extra:
        ev.update(dict(extra))
    return ev


# ── Probe pipeline ───────────────────────────────────────────────────────────


def analyze_player_stream(
    rows: Sequence[Mapping[str, Any]],
    *,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
) -> Dict[str, List[Dict[str, Any]]]:
    """Run three probes + anomalies on one (game_id, player_id) ordered stream."""
    events_setback: List[Dict[str, Any]] = []
    events_way: List[Dict[str, Any]] = []
    events_target: List[Dict[str, Any]] = []
    events_anomaly: List[Dict[str, Any]] = []

    # track target changes per round for thrash
    target_changes_by_round: Counter = Counter()
    target_events_this_round: Dict[int, int] = defaultdict(int)

    prev: Optional[Dict[str, Any]] = None
    for row in rows:
        row_d = dict(row)
        # fill prev sticky from previous sample when missing (v1)
        if prev is not None:
            if row_d.get("prev_sticky_way_id") is None and row_d.get("prev_way_id") is None:
                row_d.setdefault(
                    "prev_sticky_way_id",
                    prev.get("sticky_way_id", prev.get("way_id")),
                )
            if row_d.get("prev_sticky_target_id") is None:
                row_d.setdefault(
                    "prev_sticky_target_id",
                    prev.get("sticky_target_id", prev.get("rec_target_id")),
                )
            if row_d.get("prev_turns") is None and prev.get("turns") is not None:
                row_d.setdefault("prev_turns", prev.get("turns"))

        ctx = _holder_ctx(row_d, prev)
        rnd = _safe_int(row_d.get("round"), 0) or 0

        # Drop stale first_lock writer labels when this seat already had a way/target
        if prev is not None:
            pway = _safe_int(prev.get("sticky_way_id"), _safe_int(prev.get("way_id")))
            if pway is not None:
                if str(row_d.get("way_switch_cause") or "") == "first_lock":
                    row_d["way_switch_cause"] = None
                row_d["is_first_way_lock"] = False
            ptid = _safe_int(
                prev.get("sticky_target_id"), _safe_int(prev.get("rec_target_id"))
            )
            if ptid is not None:
                if str(row_d.get("target_switch_cause") or "") == "first_lock":
                    row_d["target_switch_cause"] = None
                row_d["is_first_target_lock"] = False

        way_cls: Optional[Dict[str, Any]] = None
        tgt_cls: Optional[Dict[str, Any]] = None
        way_changed = False
        target_changed = False

        if _detect_way_event(row_d, prev):
            way_changed = True
            way_cls = classify_way_change(row_d, prev, ctx=ctx)
            events_way.append(
                _base_event(
                    row_d,
                    event_type="way",
                    primary_class=str(way_cls.get("primary_class") or "unknown"),
                    tags=list(way_cls.get("tags") or []),
                    confidence=str(way_cls.get("confidence") or "low"),
                    evidence=list(way_cls.get("evidence") or []),
                    extra={
                        "is_first_lock": bool(way_cls.get("is_first_lock")),
                    },
                )
            )

        if _detect_target_event(row_d, prev):
            target_changed = True
            tgt_cls = classify_target_change(row_d, prev, ctx=ctx)
            primary_t = str(tgt_cls.get("primary_class") or "unknown")
            # Thrash counts real churn only (not first_lock / stream start)
            if primary_t not in ("first_lock",):
                target_events_this_round[rnd] += 1
            events_target.append(
                _base_event(
                    row_d,
                    event_type="target",
                    primary_class=primary_t,
                    tags=list(tgt_cls.get("tags") or []),
                    confidence=str(tgt_cls.get("confidence") or "low"),
                    evidence=list(tgt_cls.get("evidence") or []),
                    extra={
                        "is_first_lock": bool(tgt_cls.get("is_first_lock")),
                        "is_achieve": bool(tgt_cls.get("is_achieve")),
                    },
                )
            )

        ok_sb, delta = is_setback(row_d, threshold=setback_threshold, prev=prev)
        if ok_sb:
            sb = classify_setback(
                row_d, prev, ctx=ctx, threshold=setback_threshold
            )
            events_setback.append(
                _base_event(
                    row_d,
                    event_type="setback",
                    primary_class=str(sb.get("primary_class") or "unknown"),
                    tags=list(sb.get("tags") or []),
                    confidence=str(sb.get("confidence") or "low"),
                    evidence=list(sb.get("evidence") or []),
                    extra={"delta_turns": sb.get("delta_turns", delta)},
                )
            )

        # Anomalies on this sample when way and/or target moved
        if way_changed or target_changed:
            wc = str((way_cls or {}).get("primary_class") or "") or None
            tc = str((tgt_cls or {}).get("primary_class") or "") or None
            # If way changed but we only have target event class from same row without way cls
            if way_changed and way_cls is None:
                way_cls = classify_way_change(row_d, prev, ctx=ctx)
                wc = str(way_cls.get("primary_class") or "") or None
            if target_changed and tgt_cls is None:
                tgt_cls = classify_target_change(row_d, prev, ctx=ctx)
                tc = str(tgt_cls.get("primary_class") or "") or None

            hard = hard_board_evidence_from_classes(
                wc, list((way_cls or {}).get("tags") or [])
            )
            thrash_n = target_events_this_round.get(rnd, 0)
            # Emit thrash at most once per round when threshold crossed
            emit_thrash = thrash_n >= thrash_threshold and target_changed and (
                thrash_n == thrash_threshold
            )
            anomalies = detect_anomalies(
                way_changed=way_changed,
                way_class=wc,
                target_class=tc,
                reason=row_d.get("reason"),
                hard_board_evidence=hard,
                target_changes_this_round=thrash_n if emit_thrash else 0,
                thrash_threshold=thrash_threshold,
                row=row_d,
            )
            for a in anomalies:
                events_anomaly.append(
                    _base_event(
                        row_d,
                        event_type="anomaly",
                        primary_class=str(a.get("primary_class") or "unknown"),
                        tags=[],
                        confidence=str(a.get("confidence") or "medium"),
                        evidence=list(a.get("evidence") or []),
                        extra={
                            "related_way_class": wc,
                            "related_target_class": tc,
                        },
                    )
                )

        prev = row_d

    return {
        "events_setback": events_setback,
        "events_way": events_way,
        "events_target": events_target,
        "events_anomaly": events_anomaly,
    }


def _count_by_class(events: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    c: Counter = Counter()
    for e in events:
        c[str(e.get("primary_class") or "unknown")] += 1
    return dict(c)


def _unknown_rate(by_class: Mapping[str, int]) -> float:
    total = sum(int(v) for v in by_class.values())
    if total <= 0:
        return 0.0
    unk = int(by_class.get("unknown", 0)) + int(by_class.get("estimator_jump", 0))
    # for setbacks plan mentions unknown+estimator_jump; for way/target only unknown
    return round(unk / total, 4)


def _unknown_rate_strict(by_class: Mapping[str, int]) -> float:
    total = sum(int(v) for v in by_class.values())
    if total <= 0:
        return 0.0
    return round(int(by_class.get("unknown", 0)) / total, 4)


def _rank_events(
    events: Sequence[Mapping[str, Any]],
    *,
    max_events: int,
    prefer_unknown: bool = True,
) -> List[Dict[str, Any]]:
    def score(e: Mapping[str, Any]) -> Tuple[Any, ...]:
        cls = str(e.get("primary_class") or "")
        unk = 1 if prefer_unknown and (
            cls == "unknown" or cls.startswith("anomaly_") or cls == "estimator_jump"
        ) else 0
        delta = abs(_safe_float(e.get("delta_turns"), 0.0) or 0.0)
        return (-unk, -delta, _safe_int(e.get("round"), 0) or 0, _safe_int(e.get("turn"), 0) or 0)

    ordered = sorted((dict(e) for e in events), key=score)
    if max_events is not None and max_events > 0:
        return ordered[: int(max_events)]
    return ordered


def build_probe_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    cs_path: str = "",
    batch_id: Optional[str] = None,
    game_ids: Optional[Sequence[str]] = None,
    winners_by_game: Optional[Mapping[str, Any]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
    max_events_per_probe: int = DEFAULT_MAX_EVENTS_PER_PROBE,
    notes: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Full offline analysis → strategy probe report dict."""
    filtered = filter_rows_by_game_ids(rows, game_ids)
    groups = group_rows_by_player(filtered)

    all_sb: List[Dict[str, Any]] = []
    all_way: List[Dict[str, Any]] = []
    all_tgt: List[Dict[str, Any]] = []
    all_anom: List[Dict[str, Any]] = []

    for _key, stream in groups.items():
        part = analyze_player_stream(
            stream,
            setback_threshold=setback_threshold,
            thrash_threshold=thrash_threshold,
        )
        all_sb.extend(part["events_setback"])
        all_way.extend(part["events_way"])
        all_tgt.extend(part["events_target"])
        all_anom.extend(part["events_anomaly"])

    by_sb = _count_by_class(all_sb)
    by_way = _count_by_class(all_way)
    by_tgt = _count_by_class(all_tgt)
    by_anom = _count_by_class(all_anom)

    first_lock_way = int(by_way.get("first_lock", 0))
    way_switches = max(0, len(all_way) - first_lock_way)

    achieve_n = sum(1 for e in all_tgt if e.get("primary_class") in ACHIEVE_TARGET_CLASSES)
    tgt_non_first = [
        e for e in all_tgt if e.get("primary_class") != "first_lock"
    ]
    achieve_rate = (
        round(achieve_n / len(tgt_non_first), 4) if tgt_non_first else 0.0
    )

    deltas = [
        _safe_float(e.get("delta_turns"))
        for e in all_sb
        if _safe_float(e.get("delta_turns")) is not None
    ]
    deltas_f = [float(d) for d in deltas if d is not None]
    mean_delta = round(sum(deltas_f) / len(deltas_f), 4) if deltas_f else None
    p95_delta = None
    if deltas_f:
        ordered = sorted(deltas_f)
        idx = min(len(ordered) - 1, max(0, int(round(0.95 * (len(ordered) - 1)))))
        p95_delta = ordered[idx]

    # per-game rollup
    per_game_map: Dict[str, Dict[str, Any]] = {}
    winners = dict(winners_by_game or {})

    def _ensure_game(gid: str) -> Dict[str, Any]:
        if gid not in per_game_map:
            per_game_map[gid] = {
                "game_id": gid,
                "setback_count": 0,
                "way_change_count": 0,
                "target_change_count": 0,
                "anomaly_count": 0,
                "by_class_setback": Counter(),
                "by_class_way": Counter(),
                "by_class_target": Counter(),
                "max_delta": None,
                "winner_id": winners.get(gid),
            }
        return per_game_map[gid]

    for e in all_sb:
        gid = str(e.get("game_id") or "_nogame")
        g = _ensure_game(gid)
        g["setback_count"] += 1
        g["by_class_setback"][str(e.get("primary_class") or "unknown")] += 1
        d = _safe_float(e.get("delta_turns"))
        if d is not None:
            if g["max_delta"] is None or d > g["max_delta"]:
                g["max_delta"] = d
    for e in all_way:
        gid = str(e.get("game_id") or "_nogame")
        g = _ensure_game(gid)
        g["way_change_count"] += 1
        g["by_class_way"][str(e.get("primary_class") or "unknown")] += 1
    for e in all_tgt:
        gid = str(e.get("game_id") or "_nogame")
        g = _ensure_game(gid)
        g["target_change_count"] += 1
        g["by_class_target"][str(e.get("primary_class") or "unknown")] += 1
    for e in all_anom:
        gid = str(e.get("game_id") or "_nogame")
        g = _ensure_game(gid)
        g["anomaly_count"] += 1

    per_game: List[Dict[str, Any]] = []
    for gid, g in sorted(per_game_map.items(), key=lambda kv: (-kv[1]["setback_count"], kv[0])):
        per_game.append(
            {
                "game_id": gid,
                "setback_count": g["setback_count"],
                "way_change_count": g["way_change_count"],
                "target_change_count": g["target_change_count"],
                "anomaly_count": g["anomaly_count"],
                "by_class_setback": dict(g["by_class_setback"]),
                "by_class_way": dict(g["by_class_way"]),
                "by_class_target": dict(g["by_class_target"]),
                "max_delta": g["max_delta"],
                "winner_id": g["winner_id"],
            }
        )

    # games count
    game_id_set: Set[str] = set()
    for r in filtered:
        gid = str(r.get("game_id") or "").strip()
        if gid:
            game_id_set.add(gid)
    if game_ids:
        # report filter size
        games_n = len({str(g) for g in game_ids if g})
    else:
        games_n = len(game_id_set)

    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "version": REPORT_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cs_path": cs_path or None,
        "batch_id": batch_id,
        "filters": {
            "game_ids": list(game_ids or []),
            "setback_threshold": float(setback_threshold),
            "thrash_threshold": int(thrash_threshold),
            "max_events_per_probe": int(max_events_per_probe),
        },
        "summary": {
            "cs_rows": len(filtered),
            "games": games_n,
            "setbacks": {
                "count": len(all_sb),
                "by_class": by_sb,
                "unknown_rate": _unknown_rate(by_sb),
                "mean_delta_when_setback": mean_delta,
                "p95_delta": p95_delta,
            },
            "way_changes": {
                "count": len(all_way),
                "by_class": by_way,
                "exclude_first_lock": way_switches,
                "first_lock": first_lock_way,
                "unknown_rate": _unknown_rate_strict(by_way),
            },
            "target_changes": {
                "count": len(all_tgt),
                "by_class": by_tgt,
                "achieve_rate": achieve_rate,
                "achieve_count": achieve_n,
                "unknown_rate": _unknown_rate_strict(by_tgt),
            },
            "anomalies": {
                "count": len(all_anom),
                "by_class": by_anom,
                "way_change_on_achieve": int(by_anom.get("anomaly_way_change_on_achieve", 0)),
                "way_change_hand_only": int(by_anom.get("anomaly_way_change_hand_only", 0)),
                "q2_way_change": int(by_anom.get("anomaly_q2_way_change", 0)),
                "target_thrash": int(by_anom.get("anomaly_target_thrash", 0)),
            },
        },
        "per_game": per_game,
        "events_setback": _rank_events(all_sb, max_events=max_events_per_probe),
        "events_way": _rank_events(all_way, max_events=max_events_per_probe),
        "events_target": _rank_events(all_tgt, max_events=max_events_per_probe),
        "events_anomaly": _rank_events(all_anom, max_events=max_events_per_probe),
        "notes": list(notes or []),
    }
    return report


def analyze_cs_path(
    cs_path: PathLike,
    *,
    batch_dir: Optional[PathLike] = None,
    game_ids: Optional[Sequence[str]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
    max_events_per_probe: int = DEFAULT_MAX_EVENTS_PER_PROBE,
    max_cs_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """High-level: load CS (+ optional batch filter) → probe report.

    Returns ``{ok, report, error, load, batch}``.
    """
    batch_info: Dict[str, Any] = {}
    ids = list(game_ids) if game_ids else None
    winners: Dict[str, Any] = {}
    batch_id = None
    path = Path(cs_path) if cs_path else Path(default_cs_path())

    if batch_dir is not None:
        batch_info = load_batch_game_ids(batch_dir)
        if batch_info.get("ok"):
            batch_id = batch_info.get("batch_id")
            winners = dict(batch_info.get("winners_by_game") or {})
            if ids is None and batch_info.get("game_ids"):
                ids = list(batch_info["game_ids"])
            # WP-C4: prefer per-batch CS when analyzing a batch dir
            # (unless caller passed an existing explicit --cs file).
            prefer_batch_cs = True
            try:
                # If path is the default FILENAME_CS and batch has cs.jsonl, use batch
                default_p = Path(default_cs_path())
                if path.resolve() == default_p.resolve() and batch_info.get("cs_paths"):
                    prefer_batch_cs = True
                elif path.is_file() and path.resolve() != default_p.resolve():
                    prefer_batch_cs = False
            except Exception:
                prefer_batch_cs = not path.is_file()
            if prefer_batch_cs and batch_info.get("cs_paths"):
                for cand in batch_info["cs_paths"]:
                    if Path(cand).is_file():
                        path = Path(cand)
                        break
            elif not path.is_file() and batch_info.get("cs_paths"):
                for cand in batch_info["cs_paths"]:
                    if Path(cand).is_file():
                        path = Path(cand)
                        break

    loaded = load_cs_jsonl(path, max_rows=max_cs_rows)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "report": None,
            "error": loaded.get("error") or "load failed",
            "load": loaded,
            "batch": batch_info,
        }

    notes: List[str] = []
    if loaded.get("skipped_bad"):
        notes.append(f"skipped_bad_lines={loaded['skipped_bad']}")
    if ids is not None and not ids:
        notes.append("batch game_ids empty — no filter applied" if not game_ids else "empty game_ids filter")

    report = build_probe_report(
        loaded["rows"],
        cs_path=str(loaded.get("path") or path),
        batch_id=str(batch_id) if batch_id else None,
        game_ids=ids,
        winners_by_game=winners,
        setback_threshold=setback_threshold,
        thrash_threshold=thrash_threshold,
        max_events_per_probe=max_events_per_probe,
        notes=notes,
    )
    return {
        "ok": True,
        "report": report,
        "error": "",
        "load": {
            "path": loaded.get("path"),
            "rows": len(loaded.get("rows") or []),
            "skipped_bad": loaded.get("skipped_bad"),
            "skipped_comment": loaded.get("skipped_comment"),
        },
        "batch": batch_info,
    }


def format_console_summary(report: Mapping[str, Any]) -> str:
    """One-pager for CLI (WP-C3 also uses this)."""
    s = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    sb = s.get("setbacks") if isinstance(s.get("setbacks"), Mapping) else {}
    wy = s.get("way_changes") if isinstance(s.get("way_changes"), Mapping) else {}
    tg = s.get("target_changes") if isinstance(s.get("target_changes"), Mapping) else {}
    an = s.get("anomalies") if isinstance(s.get("anomalies"), Mapping) else {}

    def _top(by_class: Any, n: int = 5) -> str:
        if not isinstance(by_class, Mapping) or not by_class:
            return "-"
        items = sorted(by_class.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
        return " ".join(f"{k}={v}" for k, v in items[:n])

    lines = [
        (
            f"Strategy probe | games={s.get('games')} cs_rows={s.get('cs_rows')} "
            f"thr={report.get('filters', {}).get('setback_threshold', SETBACK_THRESHOLD_DEFAULT)}"
        ),
        (
            f"SETBACK  n={sb.get('count', 0)}  top: {_top(sb.get('by_class'))}  "
            f"(unknown_rate={sb.get('unknown_rate', 0)})"
        ),
        (
            f"WAY      n={wy.get('count', 0)}  top: {_top(wy.get('by_class'))}  "
            f"(switches excl. first_lock={wy.get('exclude_first_lock', 0)})"
        ),
        (
            f"TARGET   n={tg.get('count', 0)}  top: {_top(tg.get('by_class'))}  "
            f"(achieve_rate={tg.get('achieve_rate', 0)})"
        ),
        (
            f"ANOMALY  way_on_achieve={an.get('way_change_on_achieve', 0)}  "
            f"hand_only_way={an.get('way_change_hand_only', 0)}  "
            f"q2_way={an.get('q2_way_change', 0)}  thrash={an.get('target_thrash', 0)}"
        ),
    ]
    per = list(report.get("per_game") or [])
    if per:
        worst = max(
            per,
            key=lambda g: (
                int(g.get("anomaly_count") or 0),
                int(g.get("setback_count") or 0),
                float(g.get("max_delta") or 0),
            ),
        )
        lines.append(
            f"worst_game: {worst.get('game_id')} "
            f"(setbacks={worst.get('setback_count')} "
            f"maxΔ={worst.get('max_delta')} "
            f"anomalies={worst.get('anomaly_count')})"
        )
    # sample anomalies
    for e in list(report.get("events_anomaly") or [])[:3]:
        lines.append(
            f"  anomaly {e.get('primary_class')} "
            f"g={e.get('game_id')} P{e.get('player_id')} "
            f"R{e.get('round')}T{e.get('turn')} "
            f"{e.get('reason')}"
        )
    return "\n".join(lines)


def write_probe_report(path: PathLike, report: Mapping[str, Any]) -> Path:
    """Write report JSON; return resolved path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, ensure_ascii=False, default=str)
    out.write_text(text + "\n", encoding="utf-8")
    return out.resolve()


__all__ = [
    "REPORT_SCHEMA",
    "REPORT_VERSION",
    "DEFAULT_MAX_EVENTS_PER_PROBE",
    "load_cs_jsonl",
    "load_batch_game_ids",
    "filter_rows_by_game_ids",
    "default_cs_path",
    "group_rows_by_player",
    "analyze_player_stream",
    "build_probe_report",
    "analyze_cs_path",
    "format_console_summary",
    "write_probe_report",
]
