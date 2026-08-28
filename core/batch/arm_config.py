"""Phase C2 WP-R6: experiment arm config + CLI ``--explicit-recalc`` parsing.

Seat map syntax (repeatable / multi-token)::

    --explicit-recalc 2=1,2,3,[4,2]
    --explicit-recalc 2=dense 3=0
    --explicit-recalc 2=[1,2,3,[4,2]]

Presets (right-hand side)::

    0 / none / control / abc / sticky → [0]  (a/b/c L2 only)
    dense / explore    → [1, 2, 3, [4, 2]]
    product / product_ai / setback_every4 → [2, [4, 4]]  (opt-in schedule)
    vp                 → [1]
    setback            → [2]
    hard / invalid     → [3]
    every2             → [[4, 2]]
    every3             → [[4, 3]]
    every4             → [[4, 4]]
    milestones         → [5]

Named arm shortcuts (``--arm``)::

    control / abc → all seats [0] (product + lab a/b/c baseline)
    product / product_ai / setback_every4 → all seats [2, [4, 4]] (opt-in)
    treat-p2  → seat 2 dense, others [0]
    treat-p3  → seat 3 dense, others [0]
    treat-all → all seats dense
    s142-drive → all seats [0] sticky + SIDESTEP_S142_DRIVE (matched A/B treat)
    perf / perf-on → control seats + performance dig pack ON
    control+perf / control+perf-off → seat arm + perf pack

``--perf on|off`` is orthogonal to the seat map (same as ``+perf`` suffix).

No ``--arm``: Game init applies product defaults (AI + human ``[0]`` = a/b/c only).

Arm metadata is stored on batch_summary / result.json for matched analysis.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from core.explicit_142_recalc import (
    EXPLICIT_142_RECALC_BY_SEAT,
    EXPLICIT_RECALC_DEFAULT_RAW,
    apply_seat_map_to_players,
    normalize_explicit_142_recalc,
    to_raw_list,
)

RawList = List[Any]
SeatMap = Dict[int, RawList]

# ── Presets ──────────────────────────────────────────────────────────

PRESET_RAW: Dict[str, RawList] = {
    "0": [0],
    "none": [0],
    "control": [0],
    "sticky": [0],
    "abc": [0],  # Phase G: a/b/c L2 cadence only
    "l2-abc": [0],
    "l2_abc": [0],
    "dense": [1, 2, 3, [4, 2]],
    "explore": [1, 2, 3, [4, 2]],
    "pilot": [1, 2, 3, [4, 2]],
    "vp": [1],
    "setback": [2],
    "hard": [3],
    "invalid": [3],
    "every2": [[4, 2]],
    "every3": [[4, 3]],
    "every4": [[4, 4]],
    "every5": [[4, 5]],
    "milestones": [5],
    # Opt-in schedule (former product AI): setback + every 4
    "product": [2, [4, 4]],
    "product_ai": [2, [4, 4]],
    "setback_every4": [2, [4, 4]],
    "schedule_244": [2, [4, 4]],
}

# Named experiment arms → full seat map (1..4)
# control/abc = a/b/c-only (product default). product = opt-in [2,[4,4]] all seats.
_SCHEDULE_244 = [2, [4, 4]]
_ABC = [0]
ARM_PRESETS: Dict[str, SeatMap] = {
    "control": {1: _ABC, 2: _ABC, 3: _ABC, 4: _ABC},
    "abc": {1: _ABC, 2: _ABC, 3: _ABC, 4: _ABC},
    "l2-abc": {1: _ABC, 2: _ABC, 3: _ABC, 4: _ABC},
    "l2_abc": {1: _ABC, 2: _ABC, 3: _ABC, 4: _ABC},
    "product": {
        1: _SCHEDULE_244,
        2: _SCHEDULE_244,
        3: _SCHEDULE_244,
        4: _SCHEDULE_244,
    },
    "product_ai": {
        1: _SCHEDULE_244,
        2: _SCHEDULE_244,
        3: _SCHEDULE_244,
        4: _SCHEDULE_244,
    },
    "setback_every4": {
        1: _SCHEDULE_244,
        2: _SCHEDULE_244,
        3: _SCHEDULE_244,
        4: _SCHEDULE_244,
    },
    "schedule_244": {
        1: _SCHEDULE_244,
        2: _SCHEDULE_244,
        3: _SCHEDULE_244,
        4: _SCHEDULE_244,
    },
    "treat-p2": {1: [0], 2: [1, 2, 3, [4, 2]], 3: [0], 4: [0]},
    "treat_p2": {1: [0], 2: [1, 2, 3, [4, 2]], 3: [0], 4: [0]},
    "treat-p3": {1: [0], 2: [0], 3: [1, 2, 3, [4, 2]], 4: [0]},
    "treat_p3": {1: [0], 2: [0], 3: [1, 2, 3, [4, 2]], 4: [0]},
    "treat-all": {
        1: [1, 2, 3, [4, 2]],
        2: [1, 2, 3, [4, 2]],
        3: [1, 2, 3, [4, 2]],
        4: [1, 2, 3, [4, 2]],
    },
    "treat_all": {
        1: [1, 2, 3, [4, 2]],
        2: [1, 2, 3, [4, 2]],
        3: [1, 2, 3, [4, 2]],
        4: [1, 2, 3, [4, 2]],
    },
    # Lab: original sticky codes; S142 a/b/c drive stamped on game by runner
    "s142-drive": {1: [0], 2: [0], 3: [0], 4: [0]},
    "s142_drive": {1: [0], 2: [0], 3: [0], 4: [0]},
}


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


def parse_raw_list_spec(spec: str) -> RawList:
    """Parse a single seat's raw list from CLI text."""
    text = str(spec or "").strip()
    if not text:
        return list(EXPLICIT_RECALC_DEFAULT_RAW)
    key = text.lower()
    if key in PRESET_RAW:
        return list(PRESET_RAW[key])
    # JSON array
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return list(data)
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return [int(data)]
    except Exception:
        pass
    # Bare number
    try:
        if re.fullmatch(r"-?\d+", text):
            return [int(text)]
    except Exception:
        pass
    # Comma list possibly with nested [4,2] — wrap and JSON-parse
    wrapped = text if text.startswith("[") else f"[{text}]"
    try:
        data = json.loads(wrapped)
        if isinstance(data, list):
            return list(data)
    except Exception:
        pass
    # Last resort: split commas ignoring nested brackets (simple scanner)
    try:
        return _scan_list_tokens(text)
    except Exception:
        return list(EXPLICIT_RECALC_DEFAULT_RAW)


def _scan_list_tokens(text: str) -> RawList:
    """Parse ``1,2,3,[4,2]`` without full JSON."""
    out: RawList = []
    i = 0
    s = text.strip()
    n = len(s)
    while i < n:
        while i < n and s[i] in " \t,":
            i += 1
        if i >= n:
            break
        if s[i] == "[":
            depth = 0
            j = i
            while j < n:
                if s[j] == "[":
                    depth += 1
                elif s[j] == "]":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            chunk = s[i:j]
            try:
                out.append(json.loads(chunk))
            except Exception:
                # [4, 2] with spaces
                inner = chunk.strip("[]")
                parts = [p.strip() for p in inner.split(",") if p.strip()]
                out.append([int(float(p)) for p in parts])
            i = j
        else:
            j = i
            while j < n and s[j] not in ",":
                j += 1
            tok = s[i:j].strip()
            if tok:
                out.append(int(float(tok)))
            i = j
    return out if out else list(EXPLICIT_RECALC_DEFAULT_RAW)


def parse_seat_assignment(token: str) -> Tuple[Optional[int], Optional[RawList], str]:
    """Parse ``2=1,2,3,[4,2]`` → (2, [1,2,3,[4,2]], error)."""
    text = str(token or "").strip()
    if not text:
        return None, None, "empty assignment"
    if "=" not in text:
        return None, None, f"expected SEAT=SPEC, got {text!r}"
    left, right = text.split("=", 1)
    seat = _safe_int(left.strip())
    if seat is None or seat < 1:
        return None, None, f"bad seat id in {text!r}"
    raw = parse_raw_list_spec(right.strip())
    # Normalize round-trip for stable storage
    norm = normalize_explicit_142_recalc(raw)
    return int(seat), to_raw_list(norm), ""


def parse_explicit_recalc_cli(
    tokens: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Parse one or more ``SEAT=SPEC`` tokens into a seat map.

    Returns ``{ok, seat_map, errors, raw_tokens}``.
    """
    result: Dict[str, Any] = {
        "ok": True,
        "seat_map": {},
        "errors": [],
        "raw_tokens": list(tokens or []),
    }
    seat_map: SeatMap = {}
    for tok in tokens or []:
        # Allow semicolon-separated multi-assign in one token
        parts = [p for p in re.split(r"[;]+", str(tok)) if p.strip()]
        for part in parts:
            seat, raw, err = parse_seat_assignment(part)
            if err:
                result["errors"].append(err)
                result["ok"] = False
                continue
            if seat is not None and raw is not None:
                seat_map[int(seat)] = list(raw)
    result["seat_map"] = seat_map
    if seat_map and result["errors"]:
        # partial success still ok if any seat mapped
        result["ok"] = True
    return result


def arm_preset_seat_map(name: str) -> Optional[SeatMap]:
    key = str(name or "").strip().lower().replace(" ", "-")
    if key in ARM_PRESETS:
        return {int(k): list(v) for k, v in ARM_PRESETS[key].items()}
    return None


def merge_seat_maps(
    base: Optional[Mapping[Any, Any]] = None,
    override: Optional[Mapping[Any, Any]] = None,
) -> SeatMap:
    """Merge seat maps; override wins. Keys coerced to int."""
    out: SeatMap = {}
    for src in (base, override):
        if not src:
            continue
        for k, v in dict(src).items():
            seat = _safe_int(k)
            if seat is None:
                continue
            if isinstance(v, list):
                out[int(seat)] = list(v)
            else:
                out[int(seat)] = parse_raw_list_spec(str(v))
    return out


def default_seat_map_from_constants() -> SeatMap:
    try:
        from core import constants as C

        raw = getattr(C, "EXPLICIT_142_RECALC_BY_SEAT", None)
        if isinstance(raw, Mapping):
            return merge_seat_maps(None, raw)
    except Exception:
        pass
    return merge_seat_maps(None, EXPLICIT_142_RECALC_BY_SEAT)


def resolve_arm_config(
    *,
    arm: Optional[str] = None,
    explicit_recalc_tokens: Optional[Sequence[str]] = None,
    seat_map_override: Optional[Mapping[Any, Any]] = None,
    dice_from_batch: Optional[str] = None,
    seed: Optional[int] = None,
    seed_base: Optional[int] = None,
    arm_name: Optional[str] = None,
    perf: Optional[str] = None,
) -> Dict[str, Any]:
    """Build full arm config for GameManager / result / batch_summary.

    Priority for seat map:
      1. ``seat_map_override``
      2. ``--explicit-recalc`` tokens (merged onto constants base)
      3. ``--arm`` preset (replaces full map when no tokens)
      4. constants ``EXPLICIT_142_RECALC_BY_SEAT``

    ``perf`` / ``--arm control+perf``: performance dig pack (see ``perf_mode``).
    """
    from core.batch.perf_mode import (
        enrich_arm_config_with_perf,
        normalize_perf_mode,
        parse_arm_perf_suffix,
    )

    base = default_seat_map_from_constants()
    errors: List[str] = []
    source = "constants"

    arm_raw = str(arm or "").strip()
    arm_key, arm_perf = parse_arm_perf_suffix(arm_raw)
    if arm_key is None and arm_raw:
        arm_key = arm_raw
    perf_mode = normalize_perf_mode(perf)
    if perf_mode is None:
        perf_mode = arm_perf

    if arm_key:
        preset = arm_preset_seat_map(arm_key)
        if preset is not None:
            base = merge_seat_maps(None, preset)
            source = f"arm:{arm_key}"
        else:
            errors.append(f"unknown arm preset {arm_key!r}")

    parsed = parse_explicit_recalc_cli(explicit_recalc_tokens)
    if parsed.get("errors"):
        errors.extend(list(parsed["errors"]))
    token_map = parsed.get("seat_map") or {}
    if token_map:
        base = merge_seat_maps(base, token_map)
        source = (source + "+cli") if source != "constants" else "cli"

    if seat_map_override:
        base = merge_seat_maps(base, seat_map_override)
        source = source + "+override"

    # Ensure seats 1..4 present
    for s in (1, 2, 3, 4):
        base.setdefault(s, list(EXPLICIT_RECALC_DEFAULT_RAW))

    # Stable string keys for JSON
    by_seat_str = {str(k): list(v) for k, v in sorted(base.items())}

    name = str(arm_name or arm_key or arm or "").strip() or None
    if name is None and source.startswith("arm:"):
        name = source.split(":", 1)[-1]
    if name is None and token_map:
        # auto name from treated seats
        treated = [
            k
            for k, v in base.items()
            if to_raw_list(normalize_explicit_142_recalc(v)) != [0]
        ]
        if treated:
            name = "treat_" + "_".join(f"p{s}" for s in sorted(treated))
        else:
            name = "control"

    s142_drive = False
    if str(arm_key or "").strip().lower().replace("_", "-") in (
        "s142-drive",
        "s142drive",
    ):
        s142_drive = True
    if name and str(name).strip().lower().replace("_", "-") in (
        "s142-drive",
        "s142drive",
    ):
        s142_drive = True

    cfg: Dict[str, Any] = {
        "ok": not errors or bool(base),
        "errors": errors,
        "arm_name": name,
        "source": source,
        "explicit_142_recalc_by_seat": by_seat_str,
        "seat_map": base,  # int keys for apply
        "dice_from_batch": str(dice_from_batch).strip() if dice_from_batch else None,
        "seed": int(seed) if seed is not None else None,
        "seed_base": int(seed_base) if seed_base is not None else None,
        "sidestep_s142_drive": bool(s142_drive),
        "perf_mode": perf_mode,
    }
    if perf_mode:
        cfg = enrich_arm_config_with_perf(cfg, perf=perf_mode)
    return cfg


def apply_arm_to_players(
    players: Sequence[Any],
    seat_map: Optional[Mapping[Any, Any]] = None,
    *,
    warn: bool = False,
) -> None:
    """Apply resolved seat map onto player list (CLI / arm override)."""
    apply_seat_map_to_players(players, seat_map, warn=warn)


def collect_explicit_by_seat_from_players(players: Sequence[Any]) -> Dict[str, Any]:
    """Read current raw lists from players for result.json."""
    out: Dict[str, Any] = {}
    for p in players or []:
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None))
        if pid is None:
            continue
        raw = getattr(p, "explicit_142_recalc", None)
        if raw is None:
            raw = [0]
        out[str(pid)] = list(raw) if isinstance(raw, list) else to_raw_list(
            normalize_explicit_142_recalc(raw)
        )
    return out


def arm_metadata_for_export(arm: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Compact arm block for batch_summary / result."""
    if not isinstance(arm, Mapping):
        return {}
    return {
        "arm_name": arm.get("arm_name"),
        "source": arm.get("source"),
        "explicit_142_recalc_by_seat": arm.get("explicit_142_recalc_by_seat"),
        "dice_from_batch": arm.get("dice_from_batch"),
        "seed": arm.get("seed"),
        "seed_base": arm.get("seed_base"),
        "sidestep_s142_drive": arm.get("sidestep_s142_drive"),
        "perf_mode": arm.get("perf_mode"),
        "perf_flags": arm.get("perf_flags"),
        "la_soft_bias_mode": arm.get("la_soft_bias_mode"),
    }


__all__ = [
    "PRESET_RAW",
    "ARM_PRESETS",
    "parse_raw_list_spec",
    "parse_seat_assignment",
    "parse_explicit_recalc_cli",
    "arm_preset_seat_map",
    "merge_seat_maps",
    "default_seat_map_from_constants",
    "resolve_arm_config",
    "apply_arm_to_players",
    "collect_explicit_by_seat_from_players",
    "arm_metadata_for_export",
]
