"""W1: CS JSONL stream → multi-label interest events (``cs_cat1`` / ``cs_cat2``).

Reuses the offline CS-probe classifier (``analyze_player_stream``) so codes stay
aligned with setback / way / target / anomaly reports. Does **not** write MGlog
(annotation attach is W2–W3).

Product locks: ``docs/CS_mglog_annotate_plan.md``.
Code maps: ``core/batch/cs_mglog_codes.py``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from core.batch.cs_mglog_codes import (
    CAT1_ANOMALY,
    CAT1_FIRST_LOCK,
    CAT1_SETBACK,
    CAT1_TARGET_CHANGE,
    CAT1_WAY_CHANGE,
    cat2_for_anomaly_class,
    cat2_for_setback_class,
    cat2_for_target_change_class,
    cat2_for_way_change_class,
    sorted_unique_codes,
)
from core.batch.cs_setback_analyzer import (
    analyze_player_stream,
    filter_rows_by_game_ids,
    group_rows_by_player,
    load_cs_jsonl,
)
from core.batch.strategy_change_taxonomy import (
    SETBACK_THRESHOLD_DEFAULT,
    TARGET_THRASH_PER_ROUND_DEFAULT,
)

PathLike = Union[str, Path]

INTEREST_SCHEMA = "CSInterestEvent"
INTEREST_VERSION = 1


@dataclass
class CSInterestEvent:
    """One interesting CS sample (or seat-turn merge) with multi-label codes."""

    game_id: str
    player_id: int
    round: Optional[int] = None
    turn: Optional[int] = None
    cat1: List[int] = field(default_factory=list)
    cat2: List[int] = field(default_factory=list)
    file_index: Optional[int] = None
    sequence_number: Optional[int] = None
    # Diagnostics (not written to MGlog columns)
    event_types: List[str] = field(default_factory=list)
    primary_classes: List[str] = field(default_factory=list)

    @property
    def cs_tf(self) -> bool:
        return bool(self.cat1)

    def seat_turn_key(self) -> Tuple[str, int, Optional[int], Optional[int]]:
        return (self.game_id, int(self.player_id), self.round, self.turn)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["cs_tf"] = self.cs_tf
        d["schema"] = INTEREST_SCHEMA
        d["version"] = INTEREST_VERSION
        return d


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _merge_key(ev: Mapping[str, Any]) -> Tuple[Any, ...]:
    """Group probe events from the same CS sample when possible."""
    fi = ev.get("file_index")
    gid = str(ev.get("game_id") or "") or "_nogame"
    pid = _safe_int(ev.get("player_id"), -1)
    rnd = _safe_int(ev.get("round"))
    turn = _safe_int(ev.get("turn"))
    if fi is not None:
        return ("fi", gid, pid, fi)
    # Fallback: seat-turn (may over-merge multiple samples same turn)
    return ("st", gid, pid, rnd, turn)


def apply_probe_event_to_codes(
    event: Mapping[str, Any],
    cat1: Set[int],
    cat2: Set[int],
) -> None:
    """Map one probe event (setback/way/target/anomaly) into code sets (in-place).

    **first_lock** (way or target): cat1 ``1`` + cat2 ``11`` only — not 3/4.
    Real way/target change: cat1 3/4 + fine family code.
    """
    et = str(event.get("event_type") or "").strip().lower()
    pc = str(event.get("primary_class") or "unknown").strip()
    is_fl = bool(event.get("is_first_lock")) or pc == "first_lock"

    if et == "way":
        if is_fl:
            cat1.add(CAT1_FIRST_LOCK)
            code = cat2_for_way_change_class("first_lock")
            if code is not None:
                cat2.add(code)
        else:
            cat1.add(CAT1_WAY_CHANGE)
            code = cat2_for_way_change_class(pc)
            if code is not None:
                cat2.add(code)
        return

    if et == "target":
        if is_fl:
            cat1.add(CAT1_FIRST_LOCK)
            code = cat2_for_target_change_class("first_lock")
            if code is not None:
                cat2.add(code)
        else:
            cat1.add(CAT1_TARGET_CHANGE)
            code = cat2_for_target_change_class(pc)
            if code is not None:
                cat2.add(code)
        return

    if et == "setback":
        cat1.add(CAT1_SETBACK)
        code = cat2_for_setback_class(pc)
        if code is not None:
            cat2.add(code)
        return

    if et == "anomaly":
        cat1.add(CAT1_ANOMALY)
        code = cat2_for_anomaly_class(pc)
        if code is not None:
            cat2.add(code)
        return


def interest_events_from_probe_parts(
    parts: Mapping[str, Sequence[Mapping[str, Any]]],
) -> List[CSInterestEvent]:
    """Merge analyze_player_stream event lists into multi-label interest events."""
    buckets: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

    def _ingest(events: Sequence[Mapping[str, Any]]) -> None:
        for ev in events:
            key = _merge_key(ev)
            slot = buckets.get(key)
            if slot is None:
                slot = {
                    "game_id": str(ev.get("game_id") or "") or "_nogame",
                    "player_id": _safe_int(ev.get("player_id"), -1) or -1,
                    "round": _safe_int(ev.get("round")),
                    "turn": _safe_int(ev.get("turn")),
                    "file_index": ev.get("file_index"),
                    "sequence_number": _safe_int(ev.get("sequence_number")),
                    "cat1": set(),
                    "cat2": set(),
                    "event_types": [],
                    "primary_classes": [],
                }
                buckets[key] = slot
            apply_probe_event_to_codes(ev, slot["cat1"], slot["cat2"])
            et = str(ev.get("event_type") or "")
            pc = str(ev.get("primary_class") or "")
            if et and et not in slot["event_types"]:
                slot["event_types"].append(et)
            if pc and pc not in slot["primary_classes"]:
                slot["primary_classes"].append(pc)

    _ingest(parts.get("events_setback") or [])
    _ingest(parts.get("events_way") or [])
    _ingest(parts.get("events_target") or [])
    _ingest(parts.get("events_anomaly") or [])

    out: List[CSInterestEvent] = []
    for slot in buckets.values():
        c1 = sorted_unique_codes(slot["cat1"])
        if not c1:
            continue
        out.append(
            CSInterestEvent(
                game_id=str(slot["game_id"]),
                player_id=int(slot["player_id"]),
                round=slot["round"],
                turn=slot["turn"],
                cat1=c1,
                cat2=sorted_unique_codes(slot["cat2"]),
                file_index=_safe_int(slot.get("file_index")),
                sequence_number=slot.get("sequence_number"),
                event_types=list(slot["event_types"]),
                primary_classes=list(slot["primary_classes"]),
            )
        )

    out.sort(
        key=lambda e: (
            e.game_id,
            e.player_id,
            e.round if e.round is not None else -1,
            e.turn if e.turn is not None else -1,
            e.file_index if e.file_index is not None else -1,
        )
    )
    return out


def interest_events_from_player_stream(
    rows: Sequence[Mapping[str, Any]],
    *,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
) -> List[CSInterestEvent]:
    """Classify one ordered (game_id, player_id) CS stream → interest events."""
    parts = analyze_player_stream(
        rows,
        setback_threshold=setback_threshold,
        thrash_threshold=thrash_threshold,
    )
    return interest_events_from_probe_parts(parts)


def classify_cs_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    game_ids: Optional[Sequence[str]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
) -> List[CSInterestEvent]:
    """Full multi-player CS row list → interest events (shared core for annotate)."""
    scoped = filter_rows_by_game_ids(rows, game_ids)
    groups = group_rows_by_player(scoped)
    all_ev: List[CSInterestEvent] = []
    for _key, stream in groups.items():
        all_ev.extend(
            interest_events_from_player_stream(
                stream,
                setback_threshold=setback_threshold,
                thrash_threshold=thrash_threshold,
            )
        )
    all_ev.sort(
        key=lambda e: (
            e.game_id,
            e.player_id,
            e.round if e.round is not None else -1,
            e.turn if e.turn is not None else -1,
            e.file_index if e.file_index is not None else -1,
        )
    )
    return all_ev


def merge_interest_by_seat_turn(
    events: Sequence[CSInterestEvent],
) -> List[CSInterestEvent]:
    """Union codes for Policy B attach: one event per (game, player, round, turn)."""
    buckets: Dict[Tuple[str, int, Optional[int], Optional[int]], CSInterestEvent] = {}
    for ev in events:
        key = ev.seat_turn_key()
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = CSInterestEvent(
                game_id=ev.game_id,
                player_id=ev.player_id,
                round=ev.round,
                turn=ev.turn,
                cat1=list(ev.cat1),
                cat2=list(ev.cat2),
                file_index=ev.file_index,
                sequence_number=ev.sequence_number,
                event_types=list(ev.event_types),
                primary_classes=list(ev.primary_classes),
            )
            continue
        cur.cat1 = sorted_unique_codes(list(cur.cat1) + list(ev.cat1))
        cur.cat2 = sorted_unique_codes(list(cur.cat2) + list(ev.cat2))
        for et in ev.event_types:
            if et not in cur.event_types:
                cur.event_types.append(et)
        for pc in ev.primary_classes:
            if pc not in cur.primary_classes:
                cur.primary_classes.append(pc)
        # Prefer later file_index when merging
        if ev.file_index is not None and (
            cur.file_index is None or int(ev.file_index) >= int(cur.file_index)
        ):
            cur.file_index = ev.file_index
    out = list(buckets.values())
    out.sort(
        key=lambda e: (
            e.game_id,
            e.player_id,
            e.round if e.round is not None else -1,
            e.turn if e.turn is not None else -1,
        )
    )
    return out


def classify_cs_path(
    path: PathLike,
    *,
    game_ids: Optional[Sequence[str]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
    merge_seat_turn: bool = False,
) -> Dict[str, Any]:
    """Load CS JSONL and classify. Returns ``{ok, path, events, error, ...}``."""
    loaded = load_cs_jsonl(path)
    result: Dict[str, Any] = {
        "ok": False,
        "path": loaded.get("path"),
        "events": [],
        "cs_rows": 0,
        "error": loaded.get("error") or "",
        "setback_threshold": float(setback_threshold),
        "thrash_threshold": int(thrash_threshold),
        "interest_schema": INTEREST_SCHEMA,
        "interest_version": INTEREST_VERSION,
    }
    if not loaded.get("ok"):
        return result
    rows = list(loaded.get("rows") or [])
    result["cs_rows"] = len(rows)
    events = classify_cs_rows(
        rows,
        game_ids=game_ids,
        setback_threshold=setback_threshold,
        thrash_threshold=thrash_threshold,
    )
    if merge_seat_turn:
        events = merge_interest_by_seat_turn(events)
    result["ok"] = True
    result["events"] = events
    result["n_events"] = len(events)
    result["game_ids"] = sorted({e.game_id for e in events})
    return result


def interest_events_to_dicts(events: Iterable[CSInterestEvent]) -> List[Dict[str, Any]]:
    return [e.to_dict() for e in events]


__all__ = [
    "INTEREST_SCHEMA",
    "INTEREST_VERSION",
    "CSInterestEvent",
    "apply_probe_event_to_codes",
    "interest_events_from_probe_parts",
    "interest_events_from_player_stream",
    "classify_cs_rows",
    "classify_cs_path",
    "merge_interest_by_seat_turn",
    "interest_events_to_dicts",
]
