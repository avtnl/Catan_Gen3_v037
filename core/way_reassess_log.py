"""Phase C2 WP-R4: WayReassessCompare JSONL log + helpers.

Sinks:
  - ``batch_dir/way_reassess.jsonl`` when GameManager sets path override
  - else sibling of FILENAME_CS: ``{FILENAME_HELP}_WayReassess.jsonl``
  - ``player.last_way_reassess_compare`` (dig-in)
  - CS row fields via strategy_cs_log enrichment
  - end-of-game ``result.json`` seat aggregates

See docs/PhaseC2_way_reassess_experiment_plan.md §5.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

# Process-wide path override (batch isolation)
_way_reassess_log_path_override: Optional[str] = None
_header_written_paths: set = set()


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
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


def _json_default(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "as_dict") and callable(obj.as_dict):
        try:
            return obj.as_dict()
        except Exception:
            pass
    return str(obj)


def get_way_reassess_log_path_override() -> Optional[str]:
    return _way_reassess_log_path_override


def set_way_reassess_log_path(path: Optional[str]) -> Optional[str]:
    """Set process-wide way-reassess JSONL path (batch). Returns previous override."""
    global _way_reassess_log_path_override
    prev = _way_reassess_log_path_override
    if path is None or str(path).strip() == "":
        _way_reassess_log_path_override = None
    else:
        _way_reassess_log_path_override = str(path)
    return prev


def default_way_reassess_log_path() -> str:
    """Default file next to FILENAME_CS (project root / CWD)."""
    try:
        from core.constants import FILENAME_HELP

        base = str(FILENAME_HELP or "Catan")
    except Exception:
        base = "Catan"
    return f"{base}_WayReassess.jsonl"


def way_reassess_log_path(filename: Optional[str] = None) -> str:
    if _way_reassess_log_path_override:
        return str(_way_reassess_log_path_override)
    if filename:
        return str(filename)
    # Prefer game attribute if a caller set it on a thread-local game? no — use default
    return default_way_reassess_log_path()


def log_way_compare_enabled(game: Any = None) -> bool:
    """Whether to log compare bags for any L2 (not only treatment)."""
    try:
        from core import constants as C

        if hasattr(C, "LOG_WAY_COMPARE"):
            return bool(getattr(C, "LOG_WAY_COMPARE"))
    except Exception:
        pass
    # Batch runs: default on when batch_id present
    if game is not None and getattr(game, "batch_id", None):
        return True
    return True  # lab default on; operators can set LOG_WAY_COMPARE=False


def should_log_way_compare(player: Any, game: Any = None) -> bool:
    """Treatment seats always; others when LOG_WAY_COMPARE (or batch)."""
    try:
        from core.strategy_explicit_recalc import is_treatment_seat

        if is_treatment_seat(player):
            return True
    except Exception:
        pass
    return log_way_compare_enabled(game)


def _ensure_header(path: str) -> None:
    if path in _header_written_paths:
        return
    try:
        p = Path(path)
        if p.is_file() and p.stat().st_size > 0:
            _header_written_paths.add(path)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        # No multi-line header — pure JSONL; first write creates file
        if not p.exists():
            p.write_text("", encoding="utf-8")
        _header_written_paths.add(path)
    except Exception:
        pass


def append_way_reassess_line(
    row: Mapping[str, Any],
    *,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one WayReassessCompare JSONL row. Returns {ok, path, error}."""
    path = way_reassess_log_path(filename)
    result: Dict[str, Any] = {"ok": False, "path": path, "error": ""}
    try:
        _ensure_header(path)
        line = json.dumps(
            dict(row), ensure_ascii=False, default=_json_default, separators=(",", ":")
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _dedupe_token(bag: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        bag.get("game_id"),
        bag.get("sequence_number"),
        bag.get("player_id"),
        bag.get("round"),
        bag.get("turn"),
        bag.get("trigger"),
        bag.get("locked_way"),
        bag.get("best_alt_way"),
        bag.get("switched"),
        bag.get("switch_reason"),
    )


def enrich_compare_bag(
    bag: Mapping[str, Any],
    game: Any = None,
    player: Any = None,
) -> Dict[str, Any]:
    """Fill game_id / batch_id / ts / codes if missing."""
    out = dict(bag or {})
    out.setdefault("schema", "WayReassessCompare")
    if game is not None:
        if out.get("game_id") in (None, ""):
            out["game_id"] = str(getattr(game, "id", "") or "") or None
        if out.get("sequence_number") is None:
            out["sequence_number"] = _safe_int(getattr(game, "sequence_number", None))
        if out.get("batch_id") in (None, ""):
            out["batch_id"] = str(getattr(game, "batch_id", None) or "") or None
        if out.get("round") is None:
            out["round"] = _safe_int(getattr(game, "round", None))
        if out.get("turn") is None:
            out["turn"] = _safe_int(getattr(game, "turn", None))
        # Refresh mode detail as secondary trigger hint
        if not out.get("refresh_mode_detail"):
            try:
                out["refresh_mode_detail"] = str(
                    getattr(game, "_strategy_refresh_mode_detail", None) or ""
                ) or None
            except Exception:
                pass
    if player is not None and out.get("player_id") is None:
        out["player_id"] = _safe_int(getattr(player, "id", None))
    if player is not None and not out.get("explicit_codes"):
        try:
            from core.strategy_explicit_recalc import codes_present, get_norm

            # Prefer session codes; else policy codes
            rt = getattr(player, "explicit_recalc_runtime", None) or {}
            session = list(rt.get("session_codes") or [])
            if session:
                out["explicit_codes"] = session
            else:
                out["explicit_codes"] = list(codes_present(get_norm(player)))
        except Exception:
            pass
    if player is not None:
        out["ways_used_so_far"] = list(getattr(player, "ways_used_this_game", None) or [])
    el = _safe_float(out.get("eta_locked"), None)
    ea = _safe_float(out.get("eta_alt"), None)
    if el is not None and ea is not None and out.get("eta_gain_if_switch") is None:
        out["eta_gain_if_switch"] = round(float(el) - float(ea), 3)
    if not out.get("ts"):
        out["ts"] = datetime.now().isoformat(timespec="seconds")
    return out


def publish_way_reassess_compare(
    player: Any,
    game: Any,
    bag: Mapping[str, Any],
    *,
    write_log: bool = True,
    force_write: bool = False,
) -> Dict[str, Any]:
    """Store on player and optionally append JSONL (deduped per token)."""
    full = enrich_compare_bag(bag, game=game, player=player)
    try:
        setattr(player, "last_way_reassess_compare", dict(full))
    except Exception:
        pass

    if not write_log:
        return full

    # Dedupe: same compare token within process for this player
    token = _dedupe_token(full)
    try:
        last_tok = getattr(player, "_way_reassess_log_token", None)
        if not force_write and last_tok == token:
            full["log_deduped"] = True
            return full
        setattr(player, "_way_reassess_log_token", token)
    except Exception:
        pass

    # Prefer game.way_reassess_log_path when set
    path_override = None
    if game is not None:
        try:
            path_override = getattr(game, "way_reassess_log_path", None)
        except Exception:
            path_override = None
    written = append_way_reassess_line(
        full, filename=str(path_override) if path_override else None
    )
    full["log_ok"] = bool(written.get("ok"))
    full["log_path"] = written.get("path")
    if written.get("error"):
        full["log_error"] = written.get("error")
    return full


def build_compare_from_l2(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Mapping[str, Any],
    *,
    sticky_meta: Optional[Mapping[str, Any]] = None,
    abstract: Optional[Mapping[str, Any]] = None,
    locked_way: Any = None,
) -> Dict[str, Any]:
    """Build a compare bag from L2 portfolio + sticky outcome."""
    from core.strategy_explicit_recalc import (
        audit_eta,
        audit_way_id,
        find_audit_eta_for_way,
        is_explicit_l2_session,
        is_treatment_seat,
    )

    sticky_meta = sticky_meta if isinstance(sticky_meta, Mapping) else {}
    abstract = abstract if isinstance(abstract, Mapping) else {}

    best_w = audit_way_id(audits[0]) if audits else None
    if best_w is None:
        best_w = _safe_int(
            direction.get("preferred_way_id") or direction.get("way_id"), None
        )

    locked = _safe_int(locked_way, None)
    if locked is None:
        locked = _safe_int(sticky_meta.get("locked_way_id"), None)
    if locked is None:
        prev = getattr(player, "last_sticky_meta", None)
        if isinstance(prev, Mapping):
            locked = _safe_int(
                prev.get("prev_sticky_way_id") or prev.get("sticky_way_id"), None
            )
    if locked is None:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            locked = _safe_int(sticky.get("locked_way_id"), None)
    if locked is None:
        locked = _safe_int(
            abstract.get("preferred_way_id") or abstract.get("way_id"), None
        )
    # After sticky clear / LA-only: prefer previous commitment way as locked baseline
    if locked is None:
        prev_c = getattr(player, "_prev_sticky_for_switch", None) or getattr(
            player, "prev_sticky_commitment", None
        )
        if isinstance(prev_c, Mapping):
            locked = _safe_int(prev_c.get("locked_way_id"), None)
    # If best == locked, expose true #2 as alt when available (honest Dig gain)
    if (
        locked is not None
        and best_w is not None
        and int(locked) == int(best_w)
        and len(list(audits or [])) >= 2
    ):
        alt2 = audit_way_id(audits[1])
        if alt2 is not None and int(alt2) != int(best_w):
            best_w = alt2

    # After sticky commit, locked may already be best — use sticky switch meta
    prev_locked = None
    if isinstance(sticky_meta.get("last_sticky_switch"), Mapping):
        prev_locked = _safe_int(sticky_meta["last_sticky_switch"].get("from_way"), None)
    if prev_locked is None and sticky_meta.get("explicit_switch"):
        # compare bag may already be on player from sticky
        existing = getattr(player, "last_way_reassess_compare", None)
        if isinstance(existing, Mapping) and existing.get("locked_way") is not None:
            locked = _safe_int(existing.get("locked_way"), locked)

    eta_locked = find_audit_eta_for_way(audits, locked)
    eta_best = find_audit_eta_for_way(audits, best_w)
    if eta_best is None and audits:
        eta_best = audit_eta(audits[0])

    switched = False
    if locked is not None and best_w is not None:
        switched = int(locked) != int(best_w)
    # Prefer sticky outcome after commit (direction may already equal best)
    if sticky_meta.get("explicit_switch"):
        switched = True
    elif sticky_meta.get("committed") and sticky_meta.get("locked_way_id") is not None:
        final_w = _safe_int(sticky_meta.get("locked_way_id"), None)
        # if we had abstract locked different from final
        abs_w = _safe_int(
            abstract.get("preferred_way_id") or abstract.get("way_id"), None
        )
        if abs_w is not None and final_w is not None and int(abs_w) != int(final_w):
            switched = True
            if locked is None:
                locked = abs_w

    # Prefer existing sticky compare for locked/best if richer
    existing = getattr(player, "last_way_reassess_compare", None)
    if isinstance(existing, Mapping) and existing.get("locked_way") is not None:
        # Reuse sticky-time locked/best when this L2 already recorded
        if sticky_meta.get("explicit_best_way") or sticky_meta.get("explicit_switch"):
            locked = _safe_int(existing.get("locked_way"), locked)
            best_w = _safe_int(existing.get("best_alt_way"), best_w)
            switched = bool(existing.get("switched"))
            eta_locked = _safe_float(existing.get("eta_locked"), eta_locked)
            eta_best = _safe_float(existing.get("eta_alt"), eta_best)

    if switched:
        switch_reason = "switched_best"
    elif best_w is None:
        switch_reason = "no_alt"
    else:
        switch_reason = "same_way"

    trigger = ""
    try:
        rt = getattr(player, "explicit_recalc_runtime", None) or {}
        trigger = str(rt.get("session_reason") or "")
    except Exception:
        trigger = ""
    if not trigger and is_explicit_l2_session(player):
        trigger = "explicit_142_recalc"
    if not trigger:
        try:
            detail = str(getattr(game, "_strategy_refresh_mode_detail", None) or "")
            if "explicit_142_recalc" in detail:
                trigger = detail
            elif detail:
                trigger = f"l2:{detail}"
            else:
                trigger = "l2"
        except Exception:
            trigger = "l2"

    bag: Dict[str, Any] = {
        "schema": "WayReassessCompare",
        "trigger": trigger,
        "locked_way": locked,
        "best_alt_way": best_w,
        "eta_locked": eta_locked,
        "eta_alt": eta_best,
        "switched": bool(switched),
        "switch_reason": switch_reason,
        "treatment": bool(is_treatment_seat(player)),
        "explicit_session": bool(is_explicit_l2_session(player)),
        "sticky_reason": str(sticky_meta.get("reason") or "") or None,
        "sticky_held": bool(sticky_meta.get("held")),
        "sticky_committed": bool(sticky_meta.get("committed")),
    }
    return bag


def maybe_emit_way_reassess_after_l2(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    direction: Mapping[str, Any],
    *,
    sticky_meta: Optional[Mapping[str, Any]] = None,
    abstract: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """If logging enabled for this seat, build + publish compare bag. Else None."""
    if player is None:
        return None
    if not should_log_way_compare(player, game):
        return None
    if not audits and not direction:
        return None
    bag = build_compare_from_l2(
        game,
        player,
        audits,
        direction,
        sticky_meta=sticky_meta,
        abstract=abstract,
    )
    return publish_way_reassess_compare(player, game, bag, write_log=True)


def collect_ways_used_by_seat(game: Any) -> Dict[str, Any]:
    """End-of-game aggregates for result.json."""
    ways_used: Dict[str, List[int]] = {}
    unique_counts: Dict[str, int] = {}
    switch_counts: Dict[str, int] = {}
    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None:
            continue
        key = str(pid)
        used = []
        for w in list(getattr(p, "ways_used_this_game", None) or []):
            wi = _safe_int(w, None)
            if wi is not None and wi > 0 and wi not in used:
                used.append(wi)
        ways_used[key] = used
        unique_counts[key] = len(used)
        try:
            switch_counts[key] = int(getattr(p, "way_switch_count", 0) or 0)
        except Exception:
            switch_counts[key] = max(0, len(used) - 1) if used else 0
    return {
        "ways_used_by_seat": ways_used,
        "unique_ways_count_by_seat": unique_counts,
        "way_switch_count_by_seat": switch_counts,
    }


def cs_fields_from_compare(player: Any) -> Dict[str, Any]:
    """Additive CS fields from last compare bag (WP-R4)."""
    out = {
        "locked_way": None,
        "best_alt_way": None,
        "eta_locked": None,
        "eta_alt": None,
        "way_switched": None,
        "way_compare_trigger": None,
        "eta_gain_if_switch": None,
    }
    bag = getattr(player, "last_way_reassess_compare", None) if player is not None else None
    if not isinstance(bag, Mapping):
        return out
    out["locked_way"] = _safe_int(bag.get("locked_way"), None)
    out["best_alt_way"] = _safe_int(bag.get("best_alt_way"), None)
    out["eta_locked"] = _safe_float(bag.get("eta_locked"), None)
    out["eta_alt"] = _safe_float(bag.get("eta_alt"), None)
    if bag.get("switched") is not None:
        out["way_switched"] = bool(bag.get("switched"))
    out["way_compare_trigger"] = str(bag.get("trigger") or "") or None
    out["eta_gain_if_switch"] = _safe_float(bag.get("eta_gain_if_switch"), None)
    return out


def iter_way_reassess_rows(
    path: Optional[PathLike] = None,
) -> List[Dict[str, Any]]:
    """Read all JSONL rows from way_reassess log (best-effort)."""
    p = Path(path) if path else Path(way_reassess_log_path())
    rows: List[Dict[str, Any]] = []
    if not p.is_file():
        return rows
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


__all__ = [
    "set_way_reassess_log_path",
    "get_way_reassess_log_path_override",
    "way_reassess_log_path",
    "default_way_reassess_log_path",
    "log_way_compare_enabled",
    "should_log_way_compare",
    "append_way_reassess_line",
    "enrich_compare_bag",
    "publish_way_reassess_compare",
    "build_compare_from_l2",
    "maybe_emit_way_reassess_after_l2",
    "collect_ways_used_by_seat",
    "cs_fields_from_compare",
    "iter_way_reassess_rows",
]
