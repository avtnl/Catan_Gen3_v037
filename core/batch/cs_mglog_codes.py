"""CS → MGlog annotation codes (W0).

Closed integer maps for ``cs_cat1`` / ``cs_cat2`` and CSV list encode/decode.

Product locks: ``docs/CS_mglog_annotate_plan.md`` (annot_schema ``cs_mglog_v1``).

**Code 11 (and cat1 1):** first_lock for **Way-change and Target-change only**.
Other ``cs_cat2`` codes cover way/target fines, setback, and anomaly families.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ── Schema / defaults (W0) ───────────────────────────────────────────────────

ANNOT_SCHEMA = "cs_mglog_v1"
ANNOT_SUBDIR_DEFAULT = "cs_annot"
ANNOT_MGLOG_NAME = "mglog_cs.csv"
MANIFEST_NAME = "manifest.json"

# Attachment policy id (v1)
ATTACH_POLICY = "B_last_seat_turn"

# CSV list separator (no spaces)
LIST_SEP = ";"

# Column names written on annotated MGlog
COL_CS_TF = "cs_tf"
COL_CS_CAT1 = "cs_cat1"
COL_CS_CAT2 = "cs_cat2"
ANNOT_EXTRA_COLUMNS: Tuple[str, ...] = (COL_CS_TF, COL_CS_CAT1, COL_CS_CAT2)

# ── cat1 (coarse) ────────────────────────────────────────────────────────────

CAT1_FIRST_LOCK = 1
CAT1_SETBACK = 2
CAT1_WAY_CHANGE = 3
CAT1_TARGET_CHANGE = 4
CAT1_ANOMALY = 5

CAT1_NAME_TO_CODE: Dict[str, int] = {
    "first_lock": CAT1_FIRST_LOCK,
    "setback": CAT1_SETBACK,
    "way_change": CAT1_WAY_CHANGE,
    "target_change": CAT1_TARGET_CHANGE,
    "anomaly": CAT1_ANOMALY,
}

CAT1_CODE_TO_NAME: Dict[int, str] = {v: k for k, v in CAT1_NAME_TO_CODE.items()}
CAT1_CODES: frozenset = frozenset(CAT1_CODE_TO_NAME.keys())

# ── cat2 (fine) ──────────────────────────────────────────────────────────────
# 11 = first_lock for way and/or target first_lock only (not setback/anomaly).

CAT2_FIRST_LOCK = 11  # way_change_class / target_change_class first_lock only

# Way-change class (taxonomy names except first_lock → CAT2_FIRST_LOCK)
CAT2_WAY_UNKNOWN = 20
CAT2_WAY_RACE_ROAD = 211
CAT2_WAY_RACE_SETTLE = 212
CAT2_WAY_TARGET_BLOCKED = 23
CAT2_WAY_OFFWAY = 24
CAT2_WAY_KILL = 25
CAT2_WAY_SPECIALS_SHOCK = 26
CAT2_WAY_SOFT_ETA = 27
CAT2_WAY_HARD_INVALID = 28
CAT2_WAY_ENDGAME = 29

# Target-change class
CAT2_TGT_UNKNOWN = 30
CAT2_TGT_RACE_ROAD = 311
CAT2_TGT_RACE_SETTLE = 312
CAT2_TGT_RACE_IMPOSSIBLE = 313
CAT2_TGT_TARGET_BLOCKED = 33
CAT2_TGT_OFFWAY = 34
CAT2_TGT_ACHIEVE_SETTLE = 351
CAT2_TGT_ACHIEVE_CITY = 352
CAT2_TGT_ACHIEVE_COMPONENT = 353
CAT2_TGT_ROUTE_ILLEGAL = 36
CAT2_TGT_SAME_WAY_RERANK = 37
CAT2_TGT_SPECIALS_PROJECT = 38
CAT2_TGT_WAY_SWITCH_CASCADE = 39

# Setback class
CAT2_SB_UNKNOWN = 40
CAT2_SB_WAY_SWITCH = 41
CAT2_SB_SPECIALS_LA = 421
CAT2_SB_SPECIALS_LR = 422
CAT2_SB_ROBBER = 431
CAT2_SB_DISCARD_7 = 432
CAT2_SB_MONOPOLY = 44
CAT2_SB_DCARD_DRAW = 45
CAT2_SB_TRADE_REPRICE = 46
CAT2_SB_BUILD_SPENT = 47
CAT2_SB_PROGRESS_PARADOX = 48
CAT2_SB_ESTIMATOR_JUMP = 49

# Anomaly
CAT2_AN_WAY_ON_ACHIEVE = 51
CAT2_AN_WAY_HAND_ONLY = 52
CAT2_AN_Q2_WAY = 53
CAT2_AN_TARGET_THRASH = 54

# Taxonomy name → cat2 for each family (first_lock excluded from way/target maps)
WAY_CHANGE_NAME_TO_CAT2: Dict[str, int] = {
    "unknown": CAT2_WAY_UNKNOWN,
    "race_road": CAT2_WAY_RACE_ROAD,
    "race_settle": CAT2_WAY_RACE_SETTLE,
    "target_blocked": CAT2_WAY_TARGET_BLOCKED,
    "offway_opportunity": CAT2_WAY_OFFWAY,
    "way_kill": CAT2_WAY_KILL,
    "specials_shock": CAT2_WAY_SPECIALS_SHOCK,
    "soft_eta_switch": CAT2_WAY_SOFT_ETA,
    "hard_invalid": CAT2_WAY_HARD_INVALID,
    "endgame_reshape": CAT2_WAY_ENDGAME,
}

TARGET_CHANGE_NAME_TO_CAT2: Dict[str, int] = {
    "unknown": CAT2_TGT_UNKNOWN,
    "race_road": CAT2_TGT_RACE_ROAD,
    "race_settle": CAT2_TGT_RACE_SETTLE,
    "race_impossible": CAT2_TGT_RACE_IMPOSSIBLE,
    "target_blocked": CAT2_TGT_TARGET_BLOCKED,
    "offway_opportunity": CAT2_TGT_OFFWAY,
    "achieve_settle": CAT2_TGT_ACHIEVE_SETTLE,
    "achieve_city": CAT2_TGT_ACHIEVE_CITY,
    "achieve_component": CAT2_TGT_ACHIEVE_COMPONENT,
    "route_illegal": CAT2_TGT_ROUTE_ILLEGAL,
    "same_way_rerank": CAT2_TGT_SAME_WAY_RERANK,
    "specials_project": CAT2_TGT_SPECIALS_PROJECT,
    "way_switch_cascade": CAT2_TGT_WAY_SWITCH_CASCADE,
}

SETBACK_NAME_TO_CAT2: Dict[str, int] = {
    "unknown": CAT2_SB_UNKNOWN,
    "way_switch": CAT2_SB_WAY_SWITCH,
    "specials_la": CAT2_SB_SPECIALS_LA,
    "specials_lr": CAT2_SB_SPECIALS_LR,
    "robber": CAT2_SB_ROBBER,
    "discard_7": CAT2_SB_DISCARD_7,
    "monopoly": CAT2_SB_MONOPOLY,
    "dcard_draw_noise": CAT2_SB_DCARD_DRAW,
    "trade_reprice": CAT2_SB_TRADE_REPRICE,
    "build_spent": CAT2_SB_BUILD_SPENT,
    "progress_paradox": CAT2_SB_PROGRESS_PARADOX,
    "estimator_jump": CAT2_SB_ESTIMATOR_JUMP,
}

ANOMALY_NAME_TO_CAT2: Dict[str, int] = {
    "anomaly_way_change_on_achieve": CAT2_AN_WAY_ON_ACHIEVE,
    "anomaly_way_change_hand_only": CAT2_AN_WAY_HAND_ONLY,
    "anomaly_q2_way_change": CAT2_AN_Q2_WAY,
    "anomaly_target_thrash": CAT2_AN_TARGET_THRASH,
}

# Flat code → stable display name (family-prefixed where "unknown" collides)
CAT2_CODE_TO_NAME: Dict[int, str] = {
    CAT2_FIRST_LOCK: "first_lock",  # way/target first_lock only
    # way
    CAT2_WAY_UNKNOWN: "way:unknown",
    CAT2_WAY_RACE_ROAD: "way:race_road",
    CAT2_WAY_RACE_SETTLE: "way:race_settle",
    CAT2_WAY_TARGET_BLOCKED: "way:target_blocked",
    CAT2_WAY_OFFWAY: "way:offway_opportunity",
    CAT2_WAY_KILL: "way:way_kill",
    CAT2_WAY_SPECIALS_SHOCK: "way:specials_shock",
    CAT2_WAY_SOFT_ETA: "way:soft_eta_switch",
    CAT2_WAY_HARD_INVALID: "way:hard_invalid",
    CAT2_WAY_ENDGAME: "way:endgame_reshape",
    # target
    CAT2_TGT_UNKNOWN: "target:unknown",
    CAT2_TGT_RACE_ROAD: "target:race_road",
    CAT2_TGT_RACE_SETTLE: "target:race_settle",
    CAT2_TGT_RACE_IMPOSSIBLE: "target:race_impossible",
    CAT2_TGT_TARGET_BLOCKED: "target:target_blocked",
    CAT2_TGT_OFFWAY: "target:offway_opportunity",
    CAT2_TGT_ACHIEVE_SETTLE: "target:achieve_settle",
    CAT2_TGT_ACHIEVE_CITY: "target:achieve_city",
    CAT2_TGT_ACHIEVE_COMPONENT: "target:achieve_component",
    CAT2_TGT_ROUTE_ILLEGAL: "target:route_illegal",
    CAT2_TGT_SAME_WAY_RERANK: "target:same_way_rerank",
    CAT2_TGT_SPECIALS_PROJECT: "target:specials_project",
    CAT2_TGT_WAY_SWITCH_CASCADE: "target:way_switch_cascade",
    # setback
    CAT2_SB_UNKNOWN: "setback:unknown",
    CAT2_SB_WAY_SWITCH: "setback:way_switch",
    CAT2_SB_SPECIALS_LA: "setback:specials_la",
    CAT2_SB_SPECIALS_LR: "setback:specials_lr",
    CAT2_SB_ROBBER: "setback:robber",
    CAT2_SB_DISCARD_7: "setback:discard_7",
    CAT2_SB_MONOPOLY: "setback:monopoly",
    CAT2_SB_DCARD_DRAW: "setback:dcard_draw_noise",
    CAT2_SB_TRADE_REPRICE: "setback:trade_reprice",
    CAT2_SB_BUILD_SPENT: "setback:build_spent",
    CAT2_SB_PROGRESS_PARADOX: "setback:progress_paradox",
    CAT2_SB_ESTIMATOR_JUMP: "setback:estimator_jump",
    # anomaly
    CAT2_AN_WAY_ON_ACHIEVE: "anomaly_way_change_on_achieve",
    CAT2_AN_WAY_HAND_ONLY: "anomaly_way_change_hand_only",
    CAT2_AN_Q2_WAY: "anomaly_q2_way_change",
    CAT2_AN_TARGET_THRASH: "anomaly_target_thrash",
}

CAT2_CODES: frozenset = frozenset(CAT2_CODE_TO_NAME.keys())

# Families for validation / dig filters
CAT2_FIRST_LOCK_CODES: frozenset = frozenset({CAT2_FIRST_LOCK})
CAT2_WAY_CODES: frozenset = frozenset(WAY_CHANGE_NAME_TO_CAT2.values())
CAT2_TARGET_CODES: frozenset = frozenset(TARGET_CHANGE_NAME_TO_CAT2.values())
CAT2_SETBACK_CODES: frozenset = frozenset(SETBACK_NAME_TO_CAT2.values())
CAT2_ANOMALY_CODES: frozenset = frozenset(ANOMALY_NAME_TO_CAT2.values())


# ── Encode / decode ──────────────────────────────────────────────────────────


def sorted_unique_codes(codes: Iterable[int]) -> List[int]:
    out: Set[int] = set()
    for c in codes:
        try:
            out.add(int(c))
        except Exception:
            continue
    return sorted(out)


def encode_code_list(codes: Optional[Iterable[int]]) -> str:
    """CSV cell: empty or ``3;5`` (sorted unique)."""
    if not codes:
        return ""
    return LIST_SEP.join(str(c) for c in sorted_unique_codes(codes))


def decode_code_list(raw: Any) -> List[int]:
    """Parse ``3;5``, ``[3, 5]``, or empty → list of ints."""
    if raw is None:
        return []
    s = str(raw).strip()
    if not s or s in ("0", "false", "False", "[]"):
        return []
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
    else:
        parts = [p.strip() for p in s.replace(",", LIST_SEP).split(LIST_SEP)]
    out: List[int] = []
    for p in parts:
        if not p:
            continue
        try:
            out.append(int(p))
        except Exception:
            continue
    return sorted_unique_codes(out)


def encode_cs_tf(hit: bool) -> str:
    return "1" if hit else ""


def decode_cs_tf(raw: Any) -> bool:
    if raw is None:
        return False
    s = str(raw).strip().lower()
    return s in ("1", "true", "t", "yes", "y")


def lists_intersect(user: Sequence[int], row: Sequence[int]) -> bool:
    """Re-play dig: non-empty intersection (OR within family)."""
    if not user or not row:
        return False
    return bool(set(int(x) for x in user) & set(int(x) for x in row))


# ── Taxonomy → codes ─────────────────────────────────────────────────────────


def cat2_for_way_change_class(name: Optional[str]) -> Optional[int]:
    """Map way_change_class string → cat2. ``first_lock`` → 11."""
    if not name:
        return None
    key = str(name).strip()
    if key == "first_lock":
        return CAT2_FIRST_LOCK
    return WAY_CHANGE_NAME_TO_CAT2.get(key)


def cat2_for_target_change_class(name: Optional[str]) -> Optional[int]:
    """Map target_change_class string → cat2. ``first_lock`` → 11."""
    if not name:
        return None
    key = str(name).strip()
    if key == "first_lock":
        return CAT2_FIRST_LOCK
    return TARGET_CHANGE_NAME_TO_CAT2.get(key)


def cat2_for_setback_class(name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    return SETBACK_NAME_TO_CAT2.get(str(name).strip())


def cat2_for_anomaly_class(name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    return ANOMALY_NAME_TO_CAT2.get(str(name).strip())


def validate_maps_against_taxonomy() -> List[str]:
    """Return list of problems (empty = OK). Used by tests / W0 self-check."""
    problems: List[str] = []
    try:
        from core.batch.strategy_change_taxonomy import (
            ANOMALY_CLASSES,
            SETBACK_CLASSES,
            TARGET_CHANGE_CLASSES,
            WAY_CHANGE_CLASSES,
        )
    except Exception as exc:  # pragma: no cover
        return [f"import taxonomy failed: {exc}"]

    for name in WAY_CHANGE_CLASSES:
        if name == "first_lock":
            continue
        if name not in WAY_CHANGE_NAME_TO_CAT2:
            problems.append(f"missing way cat2 for {name!r}")
    for name in TARGET_CHANGE_CLASSES:
        if name == "first_lock":
            continue
        if name not in TARGET_CHANGE_NAME_TO_CAT2:
            problems.append(f"missing target cat2 for {name!r}")
    for name in SETBACK_CLASSES:
        if name not in SETBACK_NAME_TO_CAT2:
            problems.append(f"missing setback cat2 for {name!r}")
    for name in ANOMALY_CLASSES:
        if name not in ANOMALY_NAME_TO_CAT2:
            problems.append(f"missing anomaly cat2 for {name!r}")

    # No duplicate cat2 ints across families (11 only once)
    all_vals: List[int] = (
        list(WAY_CHANGE_NAME_TO_CAT2.values())
        + list(TARGET_CHANGE_NAME_TO_CAT2.values())
        + list(SETBACK_NAME_TO_CAT2.values())
        + list(ANOMALY_NAME_TO_CAT2.values())
        + [CAT2_FIRST_LOCK]
    )
    if len(all_vals) != len(set(all_vals)):
        problems.append("duplicate cat2 integer codes across families")

    if set(CAT2_CODE_TO_NAME.keys()) != set(all_vals):
        problems.append("CAT2_CODE_TO_NAME keys out of sync with family maps")

    return problems


__all__ = [
    "ANNOT_SCHEMA",
    "ANNOT_SUBDIR_DEFAULT",
    "ANNOT_MGLOG_NAME",
    "MANIFEST_NAME",
    "ATTACH_POLICY",
    "LIST_SEP",
    "COL_CS_TF",
    "COL_CS_CAT1",
    "COL_CS_CAT2",
    "ANNOT_EXTRA_COLUMNS",
    "CAT1_FIRST_LOCK",
    "CAT1_SETBACK",
    "CAT1_WAY_CHANGE",
    "CAT1_TARGET_CHANGE",
    "CAT1_ANOMALY",
    "CAT1_NAME_TO_CODE",
    "CAT1_CODE_TO_NAME",
    "CAT1_CODES",
    "CAT2_FIRST_LOCK",
    "CAT2_CODE_TO_NAME",
    "CAT2_CODES",
    "WAY_CHANGE_NAME_TO_CAT2",
    "TARGET_CHANGE_NAME_TO_CAT2",
    "SETBACK_NAME_TO_CAT2",
    "ANOMALY_NAME_TO_CAT2",
    "CAT2_WAY_CODES",
    "CAT2_TARGET_CODES",
    "CAT2_SETBACK_CODES",
    "CAT2_ANOMALY_CODES",
    "sorted_unique_codes",
    "encode_code_list",
    "decode_code_list",
    "encode_cs_tf",
    "decode_cs_tf",
    "lists_intersect",
    "cat2_for_way_change_class",
    "cat2_for_target_change_class",
    "cat2_for_setback_class",
    "cat2_for_anomaly_class",
    "validate_maps_against_taxonomy",
]
