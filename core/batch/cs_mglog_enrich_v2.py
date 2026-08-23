"""SE2: enrich MGlog with SE columns + probe cats → **dense** CSV only.

Read-only on source mglog/CS. Inserts ``se_update`` rows when CS is not
attached to a same seat-turn rules row (policy a/b).

Carry-forward locked **dense** (lab: ~300 kB vs sparse ~200 kB; dig UX simpler).
Output name: ``mglog_cs.csv`` (variant=dense in header).

See ``docs/CS_mglog_se_dig_implementation_plan.md``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from core.batch.cs_interest import CSInterestEvent, classify_cs_rows
from core.batch.cs_mglog_codes import (
    COL_CS_CAT1,
    COL_CS_CAT2,
    COL_CS_TF,
    encode_code_list,
    encode_cs_tf,
    sorted_unique_codes,
)
from core.batch.cs_se_snapshot import (
    ANNOT_SCHEMA_SE,
    COL_SE_TF,
    DEL_TOKEN,
    SE_EVENT_UPDATE,
    SE_FIELD_KEYS,
    apply_changes_to_state,
    encode_se_tf,
    merge_cs_into_state,
)
from core.batch.strategy_change_taxonomy import (
    SETBACK_THRESHOLD_DEFAULT,
    TARGET_THRASH_PER_ROUND_DEFAULT,
)

PathLike = Union[str, Path]

# Canonical dig file (dense carry-forward only; sparse retired after lab compare)
MGLOG_CS_NAME = "mglog_cs.csv"
MGLOG_CS_DENSE_NAME = MGLOG_CS_NAME  # alias
MGLOG_CS_SPARSE_NAME = "mglog_cs_sparse.csv"  # retired; not written
CARRY_FORWARD = "dense"
# Dig honesty: prefer reason→event affinity, else last same-seat row, else se_update.
ATTACH_POLICY_SE = "a_reason_or_last_seat_or_b_se_update"
# Back-compat alias (old header / docs).
ATTACH_POLICY_SE_LEGACY = "a_same_step_or_b_se_update"

# Reasons that often coincide with a rules MGlog event (heuristic for policy a)
_REASON_HINTS = frozenset(
    {
        "dice_roll",
        "basic_robber",
        "build_settlement",
        "build_city",
        "build_road",
        "buy_dcard",
        "buy_development",
        "play_dcard",
        "play_knight",
        "play_monopoly",
        "play_yop",
        "play_tfr",
        "discard",
        "steal",
        "trade",
        "twp",
        "twb",
        "end_turn",
        "start_execution",
        "opponent_settlement",
        "opponent_city",
        "opponent_road",
    }
)

# CS reason substring → preferred MGlog event name(s). First matching rule wins.
_REASON_EVENT_AFFINITY: Tuple[Tuple[Tuple[str, ...], Tuple[str, ...]], ...] = (
    (("buy_development", "buy_dcard"), ("buy_dcard",)),
    (("end_turn",), ("turn_end",)),
    (("dice_roll",), ("dice_roll", "dice")),
    (("build_road",), ("build_road",)),
    (("build_settlement",), ("build_settlement",)),
    (("build_city",), ("build_city",)),
    (("basic_robber", "set_robber"), ("set_robber",)),
    (("steal",), ("steal",)),
    (("activate_dcard",), ("activate_dcard",)),
    (("play_knight",), ("play_knight", "activate_dcard", "play_dcard")),
    (("play_monopoly",), ("play_monopoly", "play_dcard")),
    (("play_yop",), ("play_yop", "play_dcard")),
    (("play_tfr",), ("play_tfr", "play_dcard")),
    (("discard",), ("discard",)),
    (("twp", "trade_player"), ("twp", "trade_player", "trade")),
    (("twb", "trade_bank"), ("twb", "trade_bank", "trade")),
)


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _seat_key(row: Mapping[str, Any]) -> Optional[Tuple[int, int, int]]:
    r = _safe_int(row.get("round"))
    t = _safe_int(row.get("turn"))
    p = _safe_int(row.get("player_id"))
    if r is None or t is None or p is None:
        return None
    return (int(r), int(t), int(p))


def _cs_sort_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        _safe_int(row.get("round"), -1) if _safe_int(row.get("round"), -1) is not None else -1,
        _safe_int(row.get("turn"), -1) if _safe_int(row.get("turn"), -1) is not None else -1,
        _safe_int(row.get("player_id"), -1) if _safe_int(row.get("player_id"), -1) is not None else -1,
        _safe_int(row.get("_file_index"), 0) or 0,
        str(row.get("ts") or ""),
    )


@dataclass
class _Node:
    """One timeline slot (original or inserted se_update)."""

    base: Dict[str, Any]
    is_insert: bool = False
    se_sparse: Dict[str, str] = field(default_factory=dict)
    se_tf: bool = False
    cat1: List[int] = field(default_factory=list)
    cat2: List[int] = field(default_factory=list)
    cs_tf: bool = False


def _empty_se_cols() -> Dict[str, str]:
    return {k: "" for k in SE_FIELD_KEYS}


def _base_fieldnames(fieldnames: Sequence[str]) -> List[str]:
    cols = [c for c in fieldnames if c]
    # strip any prior annot columns if re-annotating an enriched file
    skip = {COL_CS_TF, COL_CS_CAT1, COL_CS_CAT2, COL_SE_TF, *SE_FIELD_KEYS}
    return [c for c in cols if c not in skip]


def v2_fieldnames(base_fields: Sequence[str]) -> List[str]:
    cols = list(_base_fieldnames(base_fields))
    for c in (COL_SE_TF, *SE_FIELD_KEYS, COL_CS_TF, COL_CS_CAT1, COL_CS_CAT2):
        if c not in cols:
            cols.append(c)
    return cols


def _interest_by_file_index(
    events: Sequence[CSInterestEvent],
) -> Dict[int, CSInterestEvent]:
    """Union interest events that share the same CS ``_file_index``."""
    out: Dict[int, CSInterestEvent] = {}
    for ev in events:
        if ev.file_index is None:
            continue
        fi = int(ev.file_index)
        if fi not in out:
            out[fi] = CSInterestEvent(
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
        else:
            cur = out[fi]
            cur.cat1 = sorted_unique_codes(list(cur.cat1) + list(ev.cat1))
            cur.cat2 = sorted_unique_codes(list(cur.cat2) + list(ev.cat2))
            for et in ev.event_types:
                if et not in cur.event_types:
                    cur.event_types.append(et)
            for pc in ev.primary_classes:
                if pc not in cur.primary_classes:
                    cur.primary_classes.append(pc)
    return out


def _stamp_probe_on_node(node: _Node, iev: CSInterestEvent) -> bool:
    """Union probe cats onto a node. Returns True if newly set cs_tf."""
    if not iev.cat1 and not iev.cat2:
        return False
    newly = not node.cs_tf
    node.cs_tf = True
    node.cat1 = sorted_unique_codes(list(node.cat1) + list(iev.cat1))
    node.cat2 = sorted_unique_codes(list(node.cat2) + list(iev.cat2))
    return newly


def collect_probe_rows_from_nodes(
    nodes: Sequence[_Node],
) -> List[Dict[str, Any]]:
    """SE3 helper: list rows with cs_tf for parity checks."""
    out: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if not n.cs_tf:
            continue
        sk = _seat_key(n.base)
        out.append(
            {
                "node_index": i,
                "round": sk[0] if sk else None,
                "turn": sk[1] if sk else None,
                "player_id": sk[2] if sk else None,
                "cat1": list(n.cat1),
                "cat2": list(n.cat2),
                "is_insert": n.is_insert,
            }
        )
    return out


def probe_code_multiset(events: Sequence[CSInterestEvent]) -> Dict[str, int]:
    """Bag counts of all cat1/cat2 codes across interest events (W1 multiset)."""
    from collections import Counter

    c: Counter = Counter()
    for ev in events:
        for code in ev.cat1:
            c[f"c1:{int(code)}"] += 1
        for code in ev.cat2:
            c[f"c2:{int(code)}"] += 1
    return dict(c)


def probe_code_multiset_from_nodes(nodes: Sequence[_Node]) -> Dict[str, int]:
    """Bag counts on stamped nodes (may under-count if multiple events merged)."""
    from collections import Counter

    c: Counter = Counter()
    for n in nodes:
        if not n.cs_tf:
            continue
        for code in n.cat1:
            c[f"c1:{int(code)}"] += 1
        for code in n.cat2:
            c[f"c2:{int(code)}"] += 1
    return dict(c)


def probe_code_set_from_events(events: Sequence[CSInterestEvent]) -> set:
    """Set of all cat codes present in W1 events."""
    s: set = set()
    for ev in events:
        for code in ev.cat1:
            s.add(("c1", int(code)))
        for code in ev.cat2:
            s.add(("c2", int(code)))
    return s


def probe_code_set_from_nodes(nodes: Sequence[_Node]) -> set:
    s: set = set()
    for n in nodes:
        if not n.cs_tf:
            continue
        for code in n.cat1:
            s.add(("c1", int(code)))
        for code in n.cat2:
            s.add(("c2", int(code)))
    return s


def _reason_suggests_rules_event(reason: str) -> bool:
    r = str(reason or "").strip().lower()
    if not r:
        return False
    if r in _REASON_HINTS:
        return True
    for hint in _REASON_HINTS:
        if hint in r:
            return True
    return False


def preferred_events_for_reason(reason: Any) -> Tuple[str, ...]:
    """Map a CS ``reason`` to preferred MGlog ``event`` names (may be empty)."""
    r = str(reason or "").strip().lower()
    if not r:
        return ()
    for needles, events in _REASON_EVENT_AFFINITY:
        for needle in needles:
            if needle in r:
                return tuple(events)
    return ()


def _event_name(node: _Node) -> str:
    return str(node.base.get("event") or "").strip().lower()


def _find_attach_index(nodes: Sequence[_Node], cs_row: Mapping[str, Any]) -> Optional[int]:
    """Policy (a): same seat-turn rules row — affinity first, else last row.

    Dig honesty: ``buy_development_*`` prefers ``buy_dcard``, ``end_turn``
    prefers ``turn_end``, etc. Fallback remains last non-insert same-seat row
    (legacy). Multiple CS samples may stamp the same affinity row; later SE
    diffs merge onto it.
    """
    key = _seat_key(cs_row)
    if key is None:
        return None
    matches = [
        i
        for i, n in enumerate(nodes)
        if (not n.is_insert) and _seat_key(n.base) == key
    ]
    if not matches:
        matches_any = [i for i, n in enumerate(nodes) if _seat_key(n.base) == key]
        if matches_any and _reason_suggests_rules_event(str(cs_row.get("reason") or "")):
            # only inserts so far — force policy (b) insert
            return None
        return None

    preferred = preferred_events_for_reason(cs_row.get("reason"))
    if preferred:
        pref_set = {str(e).strip().lower() for e in preferred if str(e).strip()}
        affinity = [i for i in matches if _event_name(nodes[i]) in pref_set]
        if affinity:
            return affinity[-1]
    return matches[-1]


def _insert_after_index(nodes: Sequence[_Node], cs_row: Mapping[str, Any]) -> int:
    """Index after which to insert se_update (policy b)."""
    key = _seat_key(cs_row)
    if key is None:
        return len(nodes) - 1 if nodes else -1
    r, t, p = key
    last = -1
    for i, n in enumerate(nodes):
        sk = _seat_key(n.base)
        if sk is None:
            continue
        nr, nt, np = sk
        if (nr, nt, np) <= (r, t, p):
            last = i
    return last


def _make_se_update_base(cs_row: Mapping[str, Any], template: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if template:
        for k, v in template.items():
            if k in SE_FIELD_KEYS or k in (
                COL_SE_TF,
                COL_CS_TF,
                COL_CS_CAT1,
                COL_CS_CAT2,
            ):
                continue
            base[k] = ""
    base["event"] = SE_EVENT_UPDATE
    base["round"] = cs_row.get("round", "")
    base["turn"] = cs_row.get("turn", "")
    base["player_id"] = cs_row.get("player_id", "")
    base["phase"] = cs_row.get("phase", "") or "Execution"
    base["state"] = cs_row.get("state", "") or ""
    base["game_id"] = cs_row.get("game_id", "")
    base["event_index"] = ""  # renumber later
    if cs_row.get("ts"):
        base["ts"] = cs_row.get("ts")
    return base


def build_enriched_nodes(
    base_rows: Sequence[Mapping[str, Any]],
    cs_rows: Sequence[Mapping[str, Any]],
    *,
    interest_events: Optional[Sequence[CSInterestEvent]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
) -> Dict[str, Any]:
    """Build timeline nodes with SE sparse patches + probe cats.

    Returns ``{ok, nodes, n_se_updates, n_se_tf, n_cs_tf, error}``.
    """
    nodes: List[_Node] = [
        _Node(base=dict(r), is_insert=False) for r in base_rows
    ]
    if not cs_rows:
        return {
            "ok": True,
            "nodes": nodes,
            "n_se_updates": 0,
            "n_se_tf": 0,
            "n_cs_tf": 0,
            "error": "",
        }

    # SE3: always use W1 interest pipeline on these CS rows when not provided
    if interest_events is None:
        interest = classify_cs_rows(
            cs_rows,
            setback_threshold=setback_threshold,
            thrash_threshold=thrash_threshold,
        )
    else:
        interest = list(interest_events)

    by_fi = _interest_by_file_index(interest)

    se_state: Dict[int, Dict[str, str]] = {}
    n_insert = 0
    n_se_tf = 0
    # CS sample _file_index → node index after attach (SE3 probe join key)
    attach_by_fi: Dict[int, int] = {}
    # last attach node index per seat-turn (fallback when interest lacks file_index)
    last_attach_by_seat: Dict[Tuple[int, int, int], int] = {}

    for cs in sorted(cs_rows, key=_cs_sort_key):
        pid = _safe_int(cs.get("player_id"))
        if pid is None:
            continue
        prev = se_state.get(int(pid))
        diff = merge_cs_into_state(prev, cs)
        se_state[int(pid)] = diff["in_force"]

        attach_i = _find_attach_index(nodes, cs)
        if attach_i is None:
            after = _insert_after_index(nodes, cs)
            tmpl = nodes[after].base if after >= 0 and nodes else (nodes[0].base if nodes else {})
            new_base = _make_se_update_base(cs, tmpl)
            node = _Node(base=new_base, is_insert=True)
            insert_at = after + 1
            nodes.insert(insert_at, node)
            attach_i = insert_at
            n_insert += 1
            # shift recorded indices after insert point
            for fi_k, idx in list(attach_by_fi.items()):
                if idx >= insert_at:
                    attach_by_fi[fi_k] = idx + 1
            for sk, idx in list(last_attach_by_seat.items()):
                if idx >= insert_at:
                    last_attach_by_seat[sk] = idx + 1

        node = nodes[attach_i]
        fi = _safe_int(cs.get("_file_index"))
        if fi is not None:
            attach_by_fi[int(fi)] = attach_i
        sk = _seat_key(cs)
        if sk is not None:
            last_attach_by_seat[sk] = attach_i

        if diff.get("se_tf"):
            node.se_tf = True
            n_se_tf += 1
            for k, v in (diff.get("changes") or {}).items():
                node.se_sparse[k] = v

    # SE3: stamp probe cats on the **same node** each CS sample attached to
    n_cs_tf = 0
    stamped_fi: set = set()
    for fi, iev in by_fi.items():
        idx = attach_by_fi.get(int(fi))
        if idx is None or idx < 0 or idx >= len(nodes):
            continue
        if _stamp_probe_on_node(nodes[idx], iev):
            n_cs_tf += 1
        else:
            # already cs_tf; still counted as probe row once
            if nodes[idx].cs_tf:
                pass
        stamped_fi.add(int(fi))

    # Interest without file_index (or unmatched fi): seat-turn → last CS attach node
    for iev in interest:
        if iev.file_index is not None and int(iev.file_index) in stamped_fi:
            continue
        if iev.file_index is not None and int(iev.file_index) in attach_by_fi:
            # had fi but not in by_fi union path — stamp directly
            idx = attach_by_fi[int(iev.file_index)]
            _stamp_probe_on_node(nodes[idx], iev)
            continue
        if iev.round is None or iev.turn is None:
            continue
        sk = (int(iev.round), int(iev.turn), int(iev.player_id))
        idx = last_attach_by_seat.get(sk)
        if idx is None:
            continue
        _stamp_probe_on_node(nodes[idx], iev)

    n_cs_tf = sum(1 for n in nodes if n.cs_tf)

    return {
        "ok": True,
        "nodes": nodes,
        "n_se_updates": n_insert,
        "n_se_tf": n_se_tf,
        "n_cs_tf": n_cs_tf,
        "n_interest_events": len(interest),
        "attach_by_file_index": dict(attach_by_fi),
        "interest_events": interest,
        "error": "",
    }


def _row_has_se_values(row: Mapping[str, Any]) -> bool:
    for k in SE_FIELD_KEYS:
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and s != DEL_TOKEN:
            return True
    return False


def _backfill_seat_turn_se(dense_rows: List[Dict[str, Any]]) -> int:
    """Per-field backfill within each same-seat-turn segment.

    Dig honesty (v4 E1): sticky/STR may stamp early (dice_roll) while PLN
    arrives later (buy/end_turn). For each SE column, copy the **first
    non-empty** value in the segment onto earlier empty cells. Never crosses
    seats. Does not move ``se_tf``.
    """
    n_filled = 0
    i = 0
    n = len(dense_rows)
    while i < n:
        sk = _seat_key(dense_rows[i])
        if sk is None:
            i += 1
            continue
        j = i + 1
        while j < n and _seat_key(dense_rows[j]) == sk:
            j += 1
        # segment [i, j) — per-column first-hit backfill
        for col in SE_FIELD_KEYS:
            first_k: Optional[int] = None
            first_val = ""
            for k in range(i, j):
                v = dense_rows[k].get(col)
                s = str(v).strip() if v is not None else ""
                if s and s != DEL_TOKEN:
                    first_k = k
                    first_val = dense_rows[k].get(col, "")
                    break
            if first_k is None or first_k <= i:
                continue
            for k in range(i, first_k):
                cur = dense_rows[k].get(col)
                cs = str(cur).strip() if cur is not None else ""
                if cs and cs != DEL_TOKEN:
                    continue
                dense_rows[k][col] = first_val
                n_filled += 1
        i = j
    return n_filled


def emit_dense_rows(
    nodes: Sequence[_Node],
    *,
    base_fieldnames: Sequence[str],
) -> Dict[str, Any]:
    """Materialize **dense** row list + fieldnames (sparse retired).

    Forward per-player carry, then same-seat-turn backfill for Dig honesty.
    """
    fields = v2_fieldnames(base_fieldnames)
    dense_rows: List[Dict[str, Any]] = []

    # per-player in-force for dense carry
    in_force: Dict[int, Dict[str, str]] = {}

    for ei, node in enumerate(nodes):
        pid = _safe_int(node.base.get("player_id"))
        pid_i = int(pid) if pid is not None else -1

        if node.se_tf and node.se_sparse:
            prev = in_force.get(pid_i) or _empty_se_cols()
            in_force[pid_i] = apply_changes_to_state(prev, node.se_sparse)

        state = in_force.get(pid_i) or _empty_se_cols()

        drow = {k: node.base.get(k, "") for k in _base_fieldnames(base_fieldnames)}
        drow["event_index"] = str(ei)
        if node.is_insert:
            drow["event"] = SE_EVENT_UPDATE
        drow[COL_SE_TF] = encode_se_tf(node.se_tf)
        for k in SE_FIELD_KEYS:
            if node.se_tf and k in node.se_sparse and node.se_sparse[k] == DEL_TOKEN:
                drow[k] = DEL_TOKEN
            else:
                drow[k] = state.get(k, "")
        drow[COL_CS_TF] = encode_cs_tf(node.cs_tf)
        drow[COL_CS_CAT1] = encode_code_list(node.cat1) if node.cs_tf else ""
        drow[COL_CS_CAT2] = encode_code_list(node.cat2) if node.cs_tf else ""
        dense_rows.append(drow)

    n_backfill = _backfill_seat_turn_se(dense_rows)

    return {
        "fieldnames": fields,
        "dense_rows": dense_rows,
        "n_rows": len(dense_rows),
        "carry_forward": CARRY_FORWARD,
        "n_seat_turn_backfill": n_backfill,
    }


# Back-compat name
emit_dense_sparse_rows = emit_dense_rows


def write_enriched_csv(
    path: PathLike,
    *,
    preamble: Sequence[str],
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    variant: str,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cols = list(fieldnames)
    with p.open("w", encoding="utf-8", newline="") as f:
        for line in preamble:
            f.write(line.rstrip("\n") + "\n")
        f.write(
            f"# cs_annot schema={ANNOT_SCHEMA_SE} attach={ATTACH_POLICY_SE} "
            f"variant={variant} carry={CARRY_FORWARD} se_event={SE_EVENT_UPDATE}\n"
        )
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in cols})
    return p.resolve()


def enrich_mglog_file_v2(
    mglog_path: PathLike,
    cs_rows: Sequence[Mapping[str, Any]],
    *,
    out_dir: PathLike,
    interest_events: Optional[Sequence[CSInterestEvent]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
) -> Dict[str, Any]:
    """Enrich one game: write dense ``mglog_cs.csv`` under ``out_dir``."""
    from core.batch.cs_mglog_annotate import read_mglog_csv

    src = Path(mglog_path).resolve()
    out_root = Path(out_dir).resolve()
    result: Dict[str, Any] = {
        "ok": False,
        "source_mglog": str(src),
        "error": "",
        "dense_path": None,
        "out_path": None,
        "n_rows": 0,
        "n_se_updates": 0,
        "n_se_tf": 0,
        "n_cs_tf": 0,
        "carry_forward": CARRY_FORWARD,
    }
    if not src.is_file():
        result["error"] = f"mglog not found: {src}"
        return result

    loaded = read_mglog_csv(src)
    if not loaded.get("ok"):
        result["error"] = loaded.get("error") or "read failed"
        return result

    built = build_enriched_nodes(
        loaded["rows"],
        cs_rows,
        interest_events=interest_events,
        setback_threshold=setback_threshold,
        thrash_threshold=thrash_threshold,
    )
    emitted = emit_dense_rows(
        built["nodes"],
        base_fieldnames=loaded["fieldnames"],
    )
    out_root.mkdir(parents=True, exist_ok=True)
    out_p = out_root / MGLOG_CS_NAME
    if out_p.resolve() == src:
        result["error"] = "refuse to overwrite source mglog"
        return result

    write_enriched_csv(
        out_p,
        preamble=loaded["preamble"],
        fieldnames=emitted["fieldnames"],
        rows=emitted["dense_rows"],
        variant=CARRY_FORWARD,
    )
    result["ok"] = True
    result["dense_path"] = str(out_p.resolve())
    result["out_path"] = str(out_p.resolve())
    result["n_rows"] = emitted["n_rows"]
    result["n_se_updates"] = built["n_se_updates"]
    result["n_se_tf"] = built["n_se_tf"]
    result["n_cs_tf"] = built["n_cs_tf"]
    result["fieldnames"] = emitted["fieldnames"]
    return result


__all__ = [
    "MGLOG_CS_NAME",
    "MGLOG_CS_DENSE_NAME",
    "MGLOG_CS_SPARSE_NAME",
    "CARRY_FORWARD",
    "ATTACH_POLICY_SE",
    "ATTACH_POLICY_SE_LEGACY",
    "preferred_events_for_reason",
    "v2_fieldnames",
    "build_enriched_nodes",
    "emit_dense_rows",
    "emit_dense_sparse_rows",
    "write_enriched_csv",
    "enrich_mglog_file_v2",
    "collect_probe_rows_from_nodes",
    "probe_code_multiset",
    "probe_code_multiset_from_nodes",
    "probe_code_set_from_events",
    "probe_code_set_from_nodes",
]
