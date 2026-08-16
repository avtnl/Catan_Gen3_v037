"""Phase C2 WP-R0: per-seat explicit Victory-Way / L2 reassess trigger codes.

Product default (new games):
  - AI seats: ``[2, [4, 4]]`` (ETA setback OR every 4 own turns)
  - Human seats: ``[0]`` (sticky only; closed-table L2 still applies)

Lab sticky baseline: ``run_headless --arm control`` (all seats ``[0]``).
CLI ``--explicit-recalc`` / ``--arm`` override by seat id.

Codes
-----
0  none — no explicit extra L2 (ignore if mixed with others)
1  on_vp_gain — after own VP increases (settle/city/specials VP)
2  on_eta_setback — sticky ETA rose by ≥ EXPLICIT_RECALC_SETBACK_THR
3  on_target_hard_invalid — sticky target hard-invalid / blocked race
4  every_n_own_turns — form ``[4, n]`` (n ≥ 1); bare ``4`` → n default
5  milestones — first cross of EXPLICIT_RECALC_MILESTONES VP values

9  reserved (every_own_turn) — not implemented

Multi-entry lists are OR'd. See docs/PhaseC2_way_reassess_experiment_plan.md.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

# ── Codes ────────────────────────────────────────────────────────────────────

EXPLICIT_RECALC_NONE: int = 0
EXPLICIT_RECALC_ON_VP_GAIN: int = 1
EXPLICIT_RECALC_ON_ETA_SETBACK: int = 2
EXPLICIT_RECALC_ON_TARGET_HARD_INVALID: int = 3
EXPLICIT_RECALC_EVERY_N_OWN_TURNS: int = 4
EXPLICIT_RECALC_MILESTONES: int = 5
# Reserved — do not implement in v1
EXPLICIT_RECALC_EVERY_OWN_TURN_RESERVED: int = 9

EXPLICIT_RECALC_CODE_NAMES: Dict[int, str] = {
    EXPLICIT_RECALC_NONE: "none",
    EXPLICIT_RECALC_ON_VP_GAIN: "on_vp_gain",
    EXPLICIT_RECALC_ON_ETA_SETBACK: "on_eta_setback",
    EXPLICIT_RECALC_ON_TARGET_HARD_INVALID: "on_target_hard_invalid",
    EXPLICIT_RECALC_EVERY_N_OWN_TURNS: "every_n_own_turns",
    EXPLICIT_RECALC_MILESTONES: "milestones",
    EXPLICIT_RECALC_EVERY_OWN_TURN_RESERVED: "every_own_turn_reserved",
}

EXPLICIT_RECALC_VALID_CODES = frozenset(
    {
        EXPLICIT_RECALC_NONE,
        EXPLICIT_RECALC_ON_VP_GAIN,
        EXPLICIT_RECALC_ON_ETA_SETBACK,
        EXPLICIT_RECALC_ON_TARGET_HARD_INVALID,
        EXPLICIT_RECALC_EVERY_N_OWN_TURNS,
        EXPLICIT_RECALC_MILESTONES,
    }
)

# ── Defaults ─────────────────────────────────────────────────────────────────

EXPLICIT_RECALC_SETBACK_THR: float = 1.0
"""ETA rise (own turns) to fire code 2."""

EXPLICIT_RECALC_EVERY_N_DEFAULT: int = 2
"""Used when code 4 appears as bare ``4`` without ``[4, n]``."""

EXPLICIT_RECALC_MILESTONE_VPS: Tuple[int, ...] = (2, 4, 6, 8)
"""VP values that fire code 5 on first crossing."""

EXPLICIT_RECALC_DEFAULT_RAW: List[Any] = [0]
"""Player field default before Game apply (also human product / sticky control)."""

EXPLICIT_142_RECALC_PRODUCT_AI: List[Any] = [2, [4, 4]]
"""AI product policy: setback + every 4 own turns."""

EXPLICIT_142_RECALC_PRODUCT_HUMAN: List[Any] = [0]
"""Human product policy: no explicit extra L2."""

# All-AI template (docs / fallback). Live init prefers is_human helpers.
EXPLICIT_142_RECALC_BY_SEAT: Dict[int, List[Any]] = {
    1: [2, [4, 4]],
    2: [2, [4, 4]],
    3: [2, [4, 4]],
    4: [2, [4, 4]],
}

# Way pick: product sticky; lab can set constants.EXPLICIT_WAY_PICK = "best"
EXPLICIT_WAY_PICK_BEST: str = "best"
EXPLICIT_WAY_PICK_STICKY: str = "sticky"
EXPLICIT_WAY_PICK_DEFAULT: str = EXPLICIT_WAY_PICK_STICKY
"""Default when constants.EXPLICIT_WAY_PICK missing: sticky + min-ETA-gain."""

RawEntry = Union[int, Sequence[Any]]
NormalizedEntry = Dict[str, Any]  # {"code": int, "n"?: int}


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def normalize_explicit_142_recalc(
    raw: Any,
    *,
    every_n_default: int = EXPLICIT_RECALC_EVERY_N_DEFAULT,
    warn: bool = False,
) -> List[NormalizedEntry]:
    """Normalize mixed raw list to ``[{code, n?}, ...]``.

    Examples
    --------
    ``[0]`` → ``[{"code": 0}]``
    ``[1, [4, 5]]`` → ``[{"code": 1}, {"code": 4, "n": 5}]``
    ``[4]`` bare → ``[{"code": 4, "n": every_n_default}]``
    Invalid entries are skipped (optional warn).
    """
    if raw is None:
        return [{"code": EXPLICIT_RECALC_NONE}]
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        if warn:
            print(f"explicit_142_recalc: invalid type {type(raw)!r}, using [0]")
        return [{"code": EXPLICIT_RECALC_NONE}]

    out: List[NormalizedEntry] = []
    for entry in raw:
        parsed = _normalize_one_entry(entry, every_n_default=every_n_default, warn=warn)
        if parsed is not None:
            out.append(parsed)
    if not out:
        return [{"code": EXPLICIT_RECALC_NONE}]
    # If only nones, keep single none
    if all(int(e.get("code", 0)) == EXPLICIT_RECALC_NONE for e in out):
        return [{"code": EXPLICIT_RECALC_NONE}]
    # Drop pure none when mixed with real codes
    filtered = [e for e in out if int(e.get("code", 0)) != EXPLICIT_RECALC_NONE]
    return filtered if filtered else [{"code": EXPLICIT_RECALC_NONE}]


def _normalize_one_entry(
    entry: Any,
    *,
    every_n_default: int,
    warn: bool,
) -> Optional[NormalizedEntry]:
    # Parameterized: [4, n] or (4, n)
    if isinstance(entry, (list, tuple)):
        if len(entry) < 1:
            if warn:
                print("explicit_142_recalc: skip empty list entry")
            return None
        code = _safe_int(entry[0])
        if code is None:
            if warn:
                print(f"explicit_142_recalc: skip bad list entry {entry!r}")
            return None
        if code == EXPLICIT_RECALC_EVERY_N_OWN_TURNS:
            if len(entry) < 2:
                if warn:
                    print(f"explicit_142_recalc: [4] needs n; using default n={every_n_default}")
                n = max(1, int(every_n_default))
            else:
                n = _safe_int(entry[1])
                if n is None or n < 1:
                    if warn:
                        print(f"explicit_142_recalc: skip invalid [4, n] {entry!r}")
                    return None
                n = int(n)
            return {"code": EXPLICIT_RECALC_EVERY_N_OWN_TURNS, "n": n}
        # Other codes as list first element only — ignore extra params in v1
        if code not in EXPLICIT_RECALC_VALID_CODES:
            if warn:
                print(f"explicit_142_recalc: skip unknown code {code}")
            return None
        if code == EXPLICIT_RECALC_EVERY_OWN_TURN_RESERVED:
            if warn:
                print("explicit_142_recalc: code 9 reserved, not implemented — skip")
            return None
        return {"code": int(code)}

    code = _safe_int(entry)
    if code is None:
        if warn:
            print(f"explicit_142_recalc: skip non-int entry {entry!r}")
        return None
    if code == EXPLICIT_RECALC_EVERY_OWN_TURN_RESERVED:
        if warn:
            print("explicit_142_recalc: code 9 reserved, not implemented — skip")
        return None
    if code not in EXPLICIT_RECALC_VALID_CODES:
        if warn:
            print(f"explicit_142_recalc: skip unknown code {code}")
        return None
    if code == EXPLICIT_RECALC_EVERY_N_OWN_TURNS:
        return {
            "code": EXPLICIT_RECALC_EVERY_N_OWN_TURNS,
            "n": max(1, int(every_n_default)),
        }
    return {"code": int(code)}


def has_explicit_recalc(normalized: Sequence[Mapping[str, Any]]) -> bool:
    """True if any non-none code is present."""
    for e in normalized or []:
        try:
            if int(e.get("code", 0)) != EXPLICIT_RECALC_NONE:
                return True
        except Exception:
            continue
    return False


def codes_present(normalized: Sequence[Mapping[str, Any]]) -> List[int]:
    """Sorted unique codes (excluding 0 unless only none)."""
    codes = set()
    for e in normalized or []:
        try:
            c = int(e.get("code", 0))
        except Exception:
            continue
        codes.add(c)
    if codes == {EXPLICIT_RECALC_NONE} or not codes:
        return [EXPLICIT_RECALC_NONE]
    return sorted(c for c in codes if c != EXPLICIT_RECALC_NONE)


def every_n_periods(normalized: Sequence[Mapping[str, Any]]) -> List[int]:
    """All n values for code-4 entries (may be empty)."""
    out: List[int] = []
    for e in normalized or []:
        try:
            if int(e.get("code", -1)) != EXPLICIT_RECALC_EVERY_N_OWN_TURNS:
                continue
            n = _safe_int(e.get("n"), EXPLICIT_RECALC_EVERY_N_DEFAULT)
            if n is not None and n >= 1:
                out.append(int(n))
        except Exception:
            continue
    return out


def to_raw_list(normalized: Sequence[Mapping[str, Any]]) -> List[Any]:
    """Round-trip normalized → raw form for save/JSON (``[1, [4, 5]]`` style)."""
    raw: List[Any] = []
    for e in normalized or []:
        try:
            code = int(e.get("code", 0))
        except Exception:
            continue
        if code == EXPLICIT_RECALC_EVERY_N_OWN_TURNS:
            n = _safe_int(e.get("n"), EXPLICIT_RECALC_EVERY_N_DEFAULT) or EXPLICIT_RECALC_EVERY_N_DEFAULT
            raw.append([4, int(n)])
        else:
            raw.append(code)
    return raw if raw else [0]


def set_player_explicit_142_recalc(player: Any, raw: Any, *, warn: bool = False) -> List[NormalizedEntry]:
    """Normalize, store raw + normalized on player; return normalized."""
    norm = normalize_explicit_142_recalc(raw, warn=warn)
    raw_out = to_raw_list(norm)
    try:
        setattr(player, "explicit_142_recalc", list(raw_out))
        setattr(player, "explicit_142_recalc_norm", list(norm))
    except Exception:
        pass
    return norm


def _product_ai_raw() -> List[Any]:
    try:
        from core import constants as C

        raw = getattr(C, "EXPLICIT_142_RECALC_PRODUCT_AI", None)
        if raw is not None:
            return list(raw)
    except Exception:
        pass
    return list(EXPLICIT_142_RECALC_PRODUCT_AI)


def _product_human_raw() -> List[Any]:
    try:
        from core import constants as C

        raw = getattr(C, "EXPLICIT_142_RECALC_PRODUCT_HUMAN", None)
        if raw is not None:
            return list(raw)
    except Exception:
        pass
    return list(EXPLICIT_142_RECALC_PRODUCT_HUMAN)


def product_raw_for_player(player: Any) -> List[Any]:
    """Product policy for one seat: AI ``[2,[4,4]]``, human ``[0]``."""
    if bool(getattr(player, "is_human", False)):
        return _product_human_raw()
    return _product_ai_raw()


def apply_product_defaults_to_players(
    players: Sequence[Any],
    *,
    warn: bool = False,
) -> None:
    """Apply product AI/human explicit_142_recalc to each player."""
    for p in players or []:
        if p is None:
            continue
        set_player_explicit_142_recalc(p, product_raw_for_player(p), warn=warn)


def build_product_seat_map(players: Sequence[Any]) -> Dict[int, List[Any]]:
    """Seat id → raw list after product rules (for batch meta)."""
    out: Dict[int, List[Any]] = {}
    for p in players or []:
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None))
        if pid is None:
            continue
        out[int(pid)] = list(product_raw_for_player(p))
    return out


def apply_seat_map_to_players(
    players: Sequence[Any],
    seat_map: Optional[Mapping[Any, Any]] = None,
    *,
    warn: bool = False,
) -> None:
    """Apply an override seat map, or product AI/human defaults when map is None.

    * ``seat_map is None`` → ``apply_product_defaults_to_players`` (is_human).
    * Non-empty map → per seat id (CLI ``--arm`` / ``--explicit-recalc``).
    """
    if seat_map is None:
        apply_product_defaults_to_players(players, warn=warn)
        return
    # Explicit map (CLI / arm): unlisted seats stay sticky [0], not product AI.
    # Callers that want product on unlisted seats should omit the map entirely.
    for p in players or []:
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None))
        raw = seat_map.get(pid, seat_map.get(str(pid), None))
        if raw is None:
            raw = list(EXPLICIT_RECALC_DEFAULT_RAW)  # [0]
        set_player_explicit_142_recalc(p, raw, warn=warn)


def code_name(code: int) -> str:
    return EXPLICIT_RECALC_CODE_NAMES.get(int(code), f"code_{code}")


__all__ = [
    "EXPLICIT_RECALC_NONE",
    "EXPLICIT_RECALC_ON_VP_GAIN",
    "EXPLICIT_RECALC_ON_ETA_SETBACK",
    "EXPLICIT_RECALC_ON_TARGET_HARD_INVALID",
    "EXPLICIT_RECALC_EVERY_N_OWN_TURNS",
    "EXPLICIT_RECALC_MILESTONES",
    "EXPLICIT_RECALC_EVERY_OWN_TURN_RESERVED",
    "EXPLICIT_RECALC_CODE_NAMES",
    "EXPLICIT_RECALC_VALID_CODES",
    "EXPLICIT_RECALC_SETBACK_THR",
    "EXPLICIT_RECALC_EVERY_N_DEFAULT",
    "EXPLICIT_RECALC_MILESTONE_VPS",
    "EXPLICIT_RECALC_DEFAULT_RAW",
    "EXPLICIT_142_RECALC_PRODUCT_AI",
    "EXPLICIT_142_RECALC_PRODUCT_HUMAN",
    "EXPLICIT_142_RECALC_BY_SEAT",
    "EXPLICIT_WAY_PICK_BEST",
    "EXPLICIT_WAY_PICK_STICKY",
    "EXPLICIT_WAY_PICK_DEFAULT",
    "normalize_explicit_142_recalc",
    "has_explicit_recalc",
    "codes_present",
    "every_n_periods",
    "to_raw_list",
    "set_player_explicit_142_recalc",
    "product_raw_for_player",
    "apply_product_defaults_to_players",
    "build_product_seat_map",
    "apply_seat_map_to_players",
    "code_name",
]
