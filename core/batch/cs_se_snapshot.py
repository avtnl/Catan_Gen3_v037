"""SE1: CS JSONL row → SE field snapshot + diff (``__DEL__`` / ``se_tf``).

Product: ``docs/CS_mglog_se_dig_implementation_plan.md`` (``cs_mglog_se_v2``).

- Primary + secondary + L2 + way-reassess / progress fields (probe cats separate).
- Diff compares **value in force** before/after a CS sample.
- **Preserve-on-null:** optional dig fields (BA, self_eta, risk, …) keep the previous
  in-force value when the CS sample has JSON ``null`` (common in live CS writes).
  Only non-null CS values update those fields; explicit clear still via ``__DEL__``
  is not emitted for null (avoids wiping BA every sample without BA).
- Always-sync fields (reason, sticky, turns, …) still clear when CS null.
- ``se_tf``: any tracked field set, updated, or cleared.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ── Schema constants ─────────────────────────────────────────────────────────

ANNOT_SCHEMA_SE = "cs_mglog_se_v2"
SE_EVENT_UPDATE = "se_update"
DEL_TOKEN = "__DEL__"
COL_SE_TF = "se_tf"

# Stable column order for enriched MGlog (primary → secondary → L2 → reassess)
SE_PRIMARY_FIELDS: Tuple[str, ...] = (
    # 1 Way
    "sticky_way_id",
    "way_id",
    "way_tags",
    "way_la",
    "way_lr",
    # 2 Sticky target
    "sticky_target_id",
    "sticky_target_kind",
    "rec_target_id",
    # 3 Plan ETA
    "turns",
    "prev_turns",
    "delta_turns",
    # 4 Target ETA
    "self_eta",
    # 5 BA
    "ba_label",
    "ba_action",
    "ba_target_id",
    "ba_source",
    # 6 Supporting
    "supporting_action_type",
    "supporting_target_id",
    # 7 Causes (probe cats are separate columns)
    "reason",
    "sample_kind",
    "way_switch_cause",
    "target_switch_cause",
    "sticky_invalidate_reason",
    "achieve_kind",
    "way_changed",
    "target_changed",
)

SE_SECONDARY_FIELDS: Tuple[str, ...] = (
    "abstract_turns",
    "win_span",
    "risk_level",
    "priority_score",
    "priority_reason",
    "threat_summary",
    "prev_sticky_way_id",
    "prev_sticky_target_id",
    "prev_sticky_target_kind",
    "prev_way_id",
    "ba_roads_fp",
    "sticky_roads_fp",
    # Way composition / board progress (always on CS; useful on MORE)
    "req_cities",
    "req_settles",
    "req_roads",
    "req_dcards",
    "settlements_owned",
    "cities_owned",
    "roads_owned",
    "vp_effective",
    "roads_changed",
    "sticky_apply_action",
)

SE_L2_FIELDS: Tuple[str, ...] = (
    "refresh_mode",
    "refresh_mode_detail",
    "l2_gate",
    "l2_bucket_live",
    "l2_bucket",
    "l2_force_reason",
    "explicit_codes",
    "explicit_trigger",
    "sticky_apply_reason",
    "sticky_invalidate_reason_live",
)

# Way reassess / first-way fit (CS schema v2+; often populated)
SE_REASSESS_FIELDS: Tuple[str, ...] = (
    "locked_way",
    "best_alt_way",
    "eta_locked",
    "eta_alt",
    "way_switched",
    "way_compare_trigger",
    "eta_gain_if_switch",
    "first_way_id",
    "first_way_fit_own",
    "first_way_fit_board",
    "first_way_fit_expand",
    "first_way_fit_total",
    "first_way_fit_d2_count",
)

SE_FIELD_KEYS: Tuple[str, ...] = (
    SE_PRIMARY_FIELDS
    + SE_SECONDARY_FIELDS
    + SE_L2_FIELDS
    + SE_REASSESS_FIELDS
)

SE_FIELD_SET = frozenset(SE_FIELD_KEYS)

# CS often writes null for these even when last known value is still useful for dig.
# Null/empty CS → keep previous in-force (do not emit __DEL__).
SE_PRESERVE_ON_NULL: frozenset = frozenset(
    {
        "self_eta",
        "abstract_turns",
        "win_span",
        "risk_level",
        "priority_score",
        "priority_reason",
        "threat_summary",
        "ba_label",
        "ba_action",
        "ba_target_id",
        "ba_source",
        "ba_roads_fp",
        "supporting_target_id",
        "explicit_codes",
        "explicit_trigger",
        "l2_bucket",
        "l2_bucket_live",
        "l2_force_reason",
        "best_alt_way",
        "eta_alt",
        "eta_gain_if_switch",
        "eta_locked",
        "locked_way",
        "first_way_id",
        "first_way_fit_own",
        "first_way_fit_board",
        "first_way_fit_expand",
        "first_way_fit_total",
        "first_way_fit_d2_count",
    }
)


# ── Normalize ────────────────────────────────────────────────────────────────


def is_empty_se_value(value: Any) -> bool:
    """True if value means 'no value in force' (not a clear token)."""
    if value is None:
        return True
    if value is False:
        return False  # bool False is a real value for flags
    if isinstance(value, str):
        s = value.strip()
        if not s or s == DEL_TOKEN:
            # bare DEL_TOKEN is a change marker, not an in-force value
            return s != DEL_TOKEN and not s
        return False
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True
    return False


def is_del_token(value: Any) -> bool:
    return str(value).strip() == DEL_TOKEN if value is not None else False


def normalize_se_cell(value: Any) -> str:
    """Canonical CSV cell for an in-force value (never ``__DEL__``).

    Empty string = no value in force.
    """
    if value is None:
        return ""
    if is_del_token(value):
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        parts: List[str] = []
        for x in value:
            if x is None:
                continue
            parts.append(str(x).strip())
        # stable join for tags / codes
        return ";".join(parts)
    if isinstance(value, float):
        # trim noisy floats; keep ints clean
        if value != value:  # NaN
            return ""
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.6g}"
    if isinstance(value, int):
        return str(value)
    s = str(value).strip()
    if s.lower() in ("none", "null"):
        return ""
    return s


def parse_se_cell(raw: Any) -> str:
    """Normalize a cell read back from CSV (preserves ``__DEL__``)."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s == DEL_TOKEN:
        return DEL_TOKEN
    return s


# ── CS row → snapshot ────────────────────────────────────────────────────────


def cs_row_to_se_snapshot(cs_row: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Map one CS JSONL object to SE field → normalized in-force string.

    Missing / null CS keys → field omitted (not present) or empty string.
    Returns a dict with **all** ``SE_FIELD_KEYS``; empty string = no value.
    """
    row = dict(cs_row or {})
    out: Dict[str, str] = {}
    for key in SE_FIELD_KEYS:
        if key not in row:
            out[key] = ""
            continue
        raw = row.get(key)
        # Explicit JSON null
        if raw is None:
            out[key] = ""
            continue
        out[key] = normalize_se_cell(raw)
    return out


def se_snapshot_nonempty(snap: Mapping[str, str]) -> Dict[str, str]:
    """Drop empty fields (sparse-friendly view of a full snapshot)."""
    return {k: v for k, v in snap.items() if k in SE_FIELD_SET and str(v).strip() and not is_del_token(v)}


# ── Diff ─────────────────────────────────────────────────────────────────────


def diff_se_snapshots(
    prev_in_force: Optional[Mapping[str, str]],
    new_snapshot: Mapping[str, str],
) -> Dict[str, Any]:
    """Compare previous **in-force** state to a new CS snapshot.

    Parameters
    ----------
    prev_in_force:
        Last known values (empty string = no value). None = no prior state.
    new_snapshot:
        Output of ``cs_row_to_se_snapshot`` (empty = no value in CS sample).

    Returns
    -------
    dict with:
      - ``se_tf``: bool
      - ``changes``: field → new cell value or ``__DEL__`` (only changed fields)
      - ``in_force``: full state after applying new_snapshot (empties allowed)
      - ``sparse_cells``: same as changes (for sparse row write)
      - ``dense_cells``: full in_force after apply (for dense row write)
    """
    prev: Dict[str, str] = {k: "" for k in SE_FIELD_KEYS}
    if prev_in_force:
        for k in SE_FIELD_KEYS:
            raw = parse_se_cell(prev_in_force.get(k, ""))
            prev[k] = "" if is_del_token(raw) else raw

    # Accept raw CS mappings or already-normalized snapshots
    if all(
        k in (new_snapshot or {}) and isinstance(new_snapshot.get(k), str)
        for k in SE_FIELD_KEYS
    ):
        new_full = {
            k: ("" if is_del_token(parse_se_cell(new_snapshot.get(k, ""))) else parse_se_cell(new_snapshot.get(k, "")))
            for k in SE_FIELD_KEYS
        }
    else:
        new_full = cs_row_to_se_snapshot(new_snapshot)

    changes: Dict[str, str] = {}
    in_force: Dict[str, str] = {}

    for k in SE_FIELD_KEYS:
        old_v = prev.get(k, "") or ""
        new_v = new_full.get(k, "") or ""

        if old_v == new_v:
            in_force[k] = old_v
            continue

        # Changed
        if old_v and not new_v:
            changes[k] = DEL_TOKEN
            in_force[k] = ""
        else:
            # set or updated (including empty → value)
            changes[k] = new_v
            in_force[k] = new_v

    se_tf = bool(changes)
    return {
        "se_tf": se_tf,
        "changes": changes,
        "in_force": in_force,
        "sparse_cells": dict(changes),
        "dense_cells": dict(in_force),
    }


def apply_changes_to_state(
    prev_in_force: Optional[Mapping[str, str]],
    changes: Mapping[str, str],
) -> Dict[str, str]:
    """Apply a sparse change map (values or ``__DEL__``) onto previous state."""
    state = {k: "" for k in SE_FIELD_KEYS}
    if prev_in_force:
        for k in SE_FIELD_KEYS:
            v = parse_se_cell(prev_in_force.get(k, ""))
            state[k] = "" if is_del_token(v) else v
    for k, cell in changes.items():
        if k not in SE_FIELD_SET:
            continue
        if is_del_token(cell):
            state[k] = ""
        else:
            state[k] = parse_se_cell(cell)
    return state


def encode_se_tf(hit: bool) -> str:
    return "1" if hit else ""


def decode_se_tf(raw: Any) -> bool:
    if raw is None:
        return False
    s = str(raw).strip().lower()
    return s in ("1", "true", "t", "yes", "y")


def merge_cs_into_state(
    prev_in_force: Optional[Mapping[str, str]],
    cs_row: Mapping[str, Any],
) -> Dict[str, Any]:
    """One-shot: CS row → snapshot → diff vs prev. Convenience for annotate.

    Optional fields listed in ``SE_PRESERVE_ON_NULL`` keep the previous value
    when the CS sample has null/empty (avoids wiping BA every hand-only refresh).
    """
    snap = cs_row_to_se_snapshot(cs_row)
    if prev_in_force:
        for k in SE_PRESERVE_ON_NULL:
            if k not in SE_FIELD_SET:
                continue
            new_v = (snap.get(k) or "").strip()
            old_v = parse_se_cell(prev_in_force.get(k, ""))
            if is_del_token(old_v):
                old_v = ""
            if not new_v and old_v:
                snap[k] = old_v
    return diff_se_snapshots(prev_in_force, snap)


__all__ = [
    "ANNOT_SCHEMA_SE",
    "SE_EVENT_UPDATE",
    "DEL_TOKEN",
    "COL_SE_TF",
    "SE_PRIMARY_FIELDS",
    "SE_SECONDARY_FIELDS",
    "SE_L2_FIELDS",
    "SE_REASSESS_FIELDS",
    "SE_FIELD_KEYS",
    "SE_FIELD_SET",
    "SE_PRESERVE_ON_NULL",
    "is_empty_se_value",
    "is_del_token",
    "normalize_se_cell",
    "parse_se_cell",
    "cs_row_to_se_snapshot",
    "se_snapshot_nonempty",
    "diff_se_snapshots",
    "apply_changes_to_state",
    "encode_se_tf",
    "decode_se_tf",
    "merge_cs_into_state",
]
