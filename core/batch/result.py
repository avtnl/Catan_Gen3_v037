"""Headless / batch game result schema (Phase A WP2).

Pure helpers: build a JSON-serializable summary from a finished (or aborted)
``Game`` without pygame or GUI. Used by ``HeadlessGameRunner`` and later
``GameManager`` aggregation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

RESULT_SCHEMA_VERSION = 1

# Terminal statuses for one headless game (Phase A).
STATUS_WON = "won"
STATUS_MAX_ROUND = "max_round"
STATUS_STUCK = "stuck"
STATUS_ERROR = "error"

VALID_STATUSES = frozenset(
    {STATUS_WON, STATUS_MAX_ROUND, STATUS_STUCK, STATUS_ERROR}
)

REQUIRED_RESULT_KEYS = frozenset(
    {
        "schema",
        "status",
        "sequence_number",
        "game_id",
        "rounds",
        "turn",
        "winner_id",
        "vp_by_player",
        "lr_holder_id",
        "la_holder_id",
        "duration_s",
        "steps",
        "flags",
        "cs_log_path",
        "error",
        "overview",
    }
)


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
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def _player_id(player: Any) -> Optional[int]:
    if player is None:
        return None
    return _safe_int(getattr(player, "id", None))


def resolve_cs_log_path(filename: Optional[str] = None) -> str:
    """Absolute path for the Change-Strategy log (honours WP-C4 override)."""
    try:
        from core.strategy_cs_log import cs_log_path as _cs_log_path

        return str(_cs_log_path(filename))
    except Exception:
        pass
    try:
        from core.constants import FILENAME_CS

        name = str(filename or FILENAME_CS or "Catan_CS.txt")
    except Exception:
        name = str(filename or "Catan_CS.txt")
    if os.path.isabs(name):
        return name
    return os.path.abspath(name)


def resolve_mglog_path_for_result(game: Any = None) -> Optional[str]:
    """Absolute MGlog path for result.json (game stamp, then process override)."""
    if game is not None:
        try:
            raw = getattr(game, "mglog_path", None)
            if raw:
                return str(Path(str(raw)).resolve())
        except Exception:
            pass
    try:
        from core.mglog import resolve_mglog_path

        return str(resolve_mglog_path())
    except Exception:
        return None


def resolve_playboard_path_for_result(game: Any = None) -> Optional[str]:
    """Absolute playboard path for result.json (game stamp from headless snapshot)."""
    if game is None:
        return None
    try:
        raw = getattr(game, "playboard_path", None)
        if raw:
            return str(Path(str(raw)).resolve())
    except Exception:
        pass
    return None


def collect_operator_flags() -> Dict[str, Any]:
    """Snapshot of operator flags relevant to a headless/batch run."""
    flags: Dict[str, Any] = {}
    try:
        from core import constants as C

        for key in (
            "HUMAN_PLAYER",
            "HP_ID",
            "NO_GUI_AT_ALL_TF",
            "LOAD_PLAYBOARD",
            "SAVED_PLAYBOARD",
            "LOAD_GAME",
            "GAME_MAX_ROUND",
            "GAMES_TO_PLAY",
            "VICTORY",
            "NUM_PLAYERS",
            "CHECK_MODE",
            "MG",
            "MGLOG",
            "EXPLICIT_142_RECALC_BY_SEAT",
            "EXPLICIT_WAY_PICK",
            "LOG_WAY_COMPARE",
        ):
            if hasattr(C, key):
                val = getattr(C, key)
                if isinstance(val, (list, tuple)):
                    flags[key] = list(val)
                elif isinstance(val, dict):
                    flags[key] = {
                        str(k): (list(v) if isinstance(v, (list, tuple)) else v)
                        for k, v in val.items()
                    }
                else:
                    flags[key] = val
    except Exception as exc:
        flags["_error"] = str(exc)
    return flags


def collect_vp_by_player(game: Any) -> Dict[str, int]:
    """Map player_id (str keys for JSON stability) → effective VP.

    Prefers ``vp_breakdown`` / ``effective_vp`` when they yield a real total.
    Falls back to ``victory_points`` / ``points`` (useful for stubs and partial
    states where board lists are empty but counters exist).
    """
    out: Dict[str, int] = {}
    players = list(getattr(game, "players", None) or []) if game is not None else []

    vp_breakdown = None
    effective_vp = None
    try:
        from core.victory import effective_vp as _eff
        from core.victory import vp_breakdown as _br

        effective_vp = _eff
        vp_breakdown = _br
    except Exception:
        try:
            from core.victory import effective_vp as _eff

            effective_vp = _eff
        except Exception:
            pass

    for p in players:
        if p is None:
            continue
        pid = _player_id(p)
        if pid is None:
            continue

        stored = None
        for attr in ("victory_points", "points"):
            raw = getattr(p, attr, None)
            if raw is not None:
                stored = _safe_int(raw, 0)
                break

        computed = None
        if vp_breakdown is not None:
            try:
                br = dict(vp_breakdown(p))
                computed = _safe_int(br.get("total"), 0)
            except Exception:
                computed = None
        if computed is None and effective_vp is not None:
            try:
                computed = int(effective_vp(p))
            except Exception:
                computed = None

        # Prefer engine total when it is positive; else stored counters.
        if computed is not None and int(computed) > 0:
            vp = int(computed)
        elif stored is not None:
            vp = int(stored)
        else:
            vp = int(computed or 0)

        out[str(pid)] = vp
    return out


def collect_overview(game: Any) -> List[Dict[str, Any]]:
    """Best-effort overview rows from game_statistics (empty list on failure)."""
    if game is None:
        return []
    try:
        from core.game_statistics import collect_overview_rows

        rows = collect_overview_rows(game)
        if isinstance(rows, list):
            return [dict(r) for r in rows if isinstance(r, Mapping)]
    except Exception:
        pass
    return []


def _winner_id_from_game(game: Any) -> Optional[int]:
    if game is None:
        return None
    w = getattr(game, "winner", None)
    pid = _player_id(w)
    if pid is not None:
        return pid
    wr = getattr(game, "win_result", None)
    if isinstance(wr, Mapping):
        for key in ("winner_id", "player_id", "winner"):
            if key == "winner" and not isinstance(wr.get(key), (int, str)):
                continue
            cand = _safe_int(wr.get(key))
            if cand is not None:
                return cand
        standings = wr.get("standings")
        if isinstance(standings, Sequence) and standings:
            first = standings[0]
            if isinstance(first, Mapping):
                return _safe_int(first.get("player_id") or first.get("id"))
    return None


def _special_holder_id(game: Any, attr: str) -> Optional[int]:
    if game is None:
        return None
    return _player_id(getattr(game, attr, None))


def build_result(
    game: Any,
    *,
    status: str,
    steps: int = 0,
    duration_s: Optional[float] = None,
    error: Optional[str] = None,
    sequence_number: Optional[int] = None,
    extra: Optional[Mapping[str, Any]] = None,
    include_overview: bool = True,
) -> Dict[str, Any]:
    """Build a schema-v1 result dict for one headless/batch game.

    Args:
        game: Finished or aborted Game (may be None on early construction error).
        status: One of won | max_round | stuck | error.
        steps: Driver step counter (Play/Continue iterations).
        duration_s: Wall-clock seconds for the run.
        error: Error message when status is error (or optional note).
        sequence_number: Override; defaults to game.sequence_number.
        extra: Optional extra keys merged at top level (not validated).
        include_overview: When True, attach game_statistics overview rows.
    """
    st = str(status or "").strip().lower()
    if st not in VALID_STATUSES:
        # Keep payload usable; normalize unknown to error with note.
        note = f"invalid_status:{status!r}"
        st = STATUS_ERROR
        if error:
            error = f"{error}; {note}"
        else:
            error = note

    seq = sequence_number
    if seq is None and game is not None:
        seq = _safe_int(getattr(game, "sequence_number", None), 1)
    if seq is None:
        seq = 1

    game_id = ""
    rounds = None
    turn = None
    if game is not None:
        game_id = str(getattr(game, "id", "") or "")
        rounds = _safe_int(getattr(game, "round", None))
        turn = _safe_int(getattr(game, "turn", None))

    # Always report declared winner if any; status is independent (won vs max_round).
    winner_id = _winner_id_from_game(game) if game is not None else None

    # WP-C4: prefer per-game / process CS path + batch_id when set on Game
    cs_path = None
    batch_id = None
    seed = None
    mglog_path = None
    if game is not None:
        try:
            raw_cs = getattr(game, "cs_log_path", None)
            if raw_cs:
                cs_path = str(raw_cs)
        except Exception:
            pass
        try:
            batch_id = str(getattr(game, "batch_id", None) or "") or None
        except Exception:
            batch_id = None
        try:
            raw_seed = getattr(game, "seed", None)
            if raw_seed is None:
                raw_seed = getattr(game, "game_seed", None)
            if raw_seed is not None and raw_seed != "":
                seed = int(raw_seed)
        except Exception:
            seed = None
        mglog_path = resolve_mglog_path_for_result(game)
        playboard_path = resolve_playboard_path_for_result(game)
    else:
        playboard_path = None
    if not cs_path:
        cs_path = resolve_cs_log_path()
    if not mglog_path:
        mglog_path = resolve_mglog_path_for_result(None)
    if not playboard_path:
        playboard_path = resolve_playboard_path_for_result(game)

    result: Dict[str, Any] = {
        "schema": RESULT_SCHEMA_VERSION,
        "status": st,
        "sequence_number": int(seq),
        "game_id": game_id,
        "rounds": rounds,
        "turn": turn,
        "winner_id": winner_id,
        "vp_by_player": collect_vp_by_player(game) if game is not None else {},
        "lr_holder_id": _special_holder_id(game, "longest_road_player"),
        "la_holder_id": _special_holder_id(game, "largest_army_player"),
        "duration_s": _safe_float(duration_s),
        "steps": int(steps or 0),
        "flags": collect_operator_flags(),
        "cs_log_path": cs_path,
        "mglog_path": mglog_path,
        "playboard_path": playboard_path,
        "batch_id": batch_id,
        "seed": seed,
        "error": str(error) if error else None,
        "overview": collect_overview(game) if include_overview and game is not None else [],
        "phase": str(getattr(game, "phase", "") or "") if game is not None else "",
        "game_over": bool(getattr(game, "game_over", False)) if game is not None else False,
    }

    # WP-R2: ordered dice sequence actually used this game
    if game is not None:
        try:
            if hasattr(game, "finalize_dice_rolls"):
                game.finalize_dice_rolls()
        except Exception:
            pass
        try:
            if hasattr(game, "export_dice_payload"):
                dice_payload = game.export_dice_payload()
            else:
                from core.dice_script import dice_export_dict

                dice_payload = dice_export_dict(
                    getattr(game, "dice_rolls", None) or [],
                    seed=seed,
                )
            if isinstance(dice_payload, dict):
                result["dice_rolls"] = dice_payload.get("dice_rolls") or []
                result["dice_count"] = int(dice_payload.get("dice_count") or 0)
                result["dice_hash"] = dice_payload.get("dice_hash")
                if result.get("seed") is None and dice_payload.get("seed") is not None:
                    result["seed"] = dice_payload.get("seed")
        except Exception:
            result.setdefault("dice_rolls", [])
            result.setdefault("dice_count", 0)
            result.setdefault("dice_hash", None)

    # Phase C2 WP-R4: ways used / switch counts per seat
    if game is not None:
        try:
            from core.way_reassess_log import collect_ways_used_by_seat

            ways_pack = collect_ways_used_by_seat(game)
            if isinstance(ways_pack, dict):
                result["ways_used_by_seat"] = ways_pack.get("ways_used_by_seat") or {}
                result["unique_ways_count_by_seat"] = (
                    ways_pack.get("unique_ways_count_by_seat") or {}
                )
                result["way_switch_count_by_seat"] = (
                    ways_pack.get("way_switch_count_by_seat") or {}
                )
        except Exception:
            result.setdefault("ways_used_by_seat", {})
            result.setdefault("unique_ways_count_by_seat", {})
            result.setdefault("way_switch_count_by_seat", {})
        try:
            wr_path = getattr(game, "way_reassess_log_path", None)
            if wr_path:
                result["way_reassess_log_path"] = str(wr_path)
            else:
                from core.way_reassess_log import (
                    get_way_reassess_log_path_override,
                    way_reassess_log_path,
                )

                ov = get_way_reassess_log_path_override()
                result["way_reassess_log_path"] = str(ov or way_reassess_log_path())
        except Exception:
            result.setdefault("way_reassess_log_path", None)

        # Phase C2 WP-R5: first-way fit per seat
        try:
            from core.first_way_fit import collect_first_way_fit_by_seat

            result["first_way_fit_by_seat"] = collect_first_way_fit_by_seat(game)
        except Exception:
            result.setdefault("first_way_fit_by_seat", {})

        # Phase C2 WP-R6: arm / explicit_142_recalc seat map
        try:
            from core.batch.arm_config import collect_explicit_by_seat_from_players

            by_seat = collect_explicit_by_seat_from_players(
                getattr(game, "players", None) or []
            )
            result["explicit_142_recalc_by_seat"] = by_seat
            arm_name = getattr(game, "arm_name", None)
            result["arm_name"] = str(arm_name) if arm_name else None
            result["arm"] = {
                "arm_name": result["arm_name"],
                "explicit_142_recalc_by_seat": by_seat,
            }
        except Exception:
            result.setdefault("explicit_142_recalc_by_seat", {})
            result.setdefault("arm_name", None)

        # Lab LA soft bias mode stamp
        try:
            from core.la_soft_bias import get_la_soft_bias_mode, status_dict

            mode = get_la_soft_bias_mode(game)
            result["la_soft_bias_mode"] = mode
            result["la_soft_bias"] = status_dict(game)
        except Exception:
            result.setdefault("la_soft_bias_mode", "off")

        # Phase L L6: live give-up fire KPIs (probe also has fire event rows)
        try:
            from core.la_lr_probe_log import collect_giveup_fire_summary

            gu = collect_giveup_fire_summary(game)
            if isinstance(gu, dict):
                result["la_giveup_fires_total"] = int(gu.get("la_giveup_fires_total") or 0)
                result["lr_giveup_fires_total"] = int(gu.get("lr_giveup_fires_total") or 0)
                result["la_giveup_fires_by_seat"] = dict(
                    gu.get("la_giveup_fires_by_seat") or {}
                )
                result["lr_giveup_fires_by_seat"] = dict(
                    gu.get("lr_giveup_fires_by_seat") or {}
                )
                result["giveup_fires"] = list(gu.get("giveup_fires") or [])
                result["giveup_fires_truncated"] = bool(
                    gu.get("giveup_fires_truncated")
                )
        except Exception:
            result.setdefault("la_giveup_fires_total", 0)
            result.setdefault("lr_giveup_fires_total", 0)
            result.setdefault("la_giveup_fires_by_seat", {})
            result.setdefault("lr_giveup_fires_by_seat", {})
            result.setdefault("giveup_fires", [])
            result.setdefault("giveup_fires_truncated", False)

        # Phase L S7: salvage adopt dig KPIs (T1/T2 after give-up / dead components)
        try:
            from core.partial_way_salvage import collect_salvage_summary

            sal = collect_salvage_summary(game)
            if isinstance(sal, dict):
                result["salvage_t1_adopts_total"] = int(
                    sal.get("salvage_t1_adopts_total") or 0
                )
                result["salvage_t2_adopts_total"] = int(
                    sal.get("salvage_t2_adopts_total") or 0
                )
                result["salvage_adopts_total"] = int(
                    sal.get("salvage_adopts_total") or 0
                )
                result["salvage_t1_adopts_by_seat"] = dict(
                    sal.get("salvage_t1_adopts_by_seat") or {}
                )
                result["salvage_t2_adopts_by_seat"] = dict(
                    sal.get("salvage_t2_adopts_by_seat") or {}
                )
                result["salvage_adopts_by_seat"] = dict(
                    sal.get("salvage_adopts_by_seat") or {}
                )
                result["salvage_adopts"] = list(sal.get("salvage_adopts") or [])
                result["salvage_adopts_truncated"] = bool(
                    sal.get("salvage_adopts_truncated")
                )
                result["salvage_s7_impl_id"] = sal.get("salvage_s7_impl_id")
        except Exception:
            result.setdefault("salvage_t1_adopts_total", 0)
            result.setdefault("salvage_t2_adopts_total", 0)
            result.setdefault("salvage_adopts_total", 0)
            result.setdefault("salvage_t1_adopts_by_seat", {})
            result.setdefault("salvage_t2_adopts_by_seat", {})
            result.setdefault("salvage_adopts_by_seat", {})
            result.setdefault("salvage_adopts", [])
            result.setdefault("salvage_adopts_truncated", False)

        # Phase L S5b G6: expansion settles deferred vs dead dig KPIs
        try:
            from core.partial_way_salvage import collect_expansion_settles_dig_summary

            exp = collect_expansion_settles_dig_summary(game)
            if isinstance(exp, dict):
                result["settles_deferred_scans"] = int(
                    exp.get("settles_deferred_scans") or 0
                )
                result["settles_dead_scans"] = int(exp.get("settles_dead_scans") or 0)
                result["settles_ok_scans"] = int(exp.get("settles_ok_scans") or 0)
                result["settles_deferred_by_seat"] = dict(
                    exp.get("settles_deferred_by_seat") or {}
                )
                result["settles_dead_by_seat"] = dict(
                    exp.get("settles_dead_by_seat") or {}
                )
                result["seats_ever_deferred"] = list(
                    exp.get("seats_ever_deferred") or []
                )
                result["seats_ever_dead"] = list(exp.get("seats_ever_dead") or [])
                result["seats_ever_deferred_count"] = int(
                    exp.get("seats_ever_deferred_count") or 0
                )
                result["seats_ever_dead_count"] = int(
                    exp.get("seats_ever_dead_count") or 0
                )
                result["settles_deferred_events"] = list(
                    exp.get("settles_deferred_events") or []
                )
                result["settles_dead_events"] = list(
                    exp.get("settles_dead_events") or []
                )
                result["expansion_settles_dig_events"] = list(
                    exp.get("expansion_settles_dig_events") or []
                )
                result["expansion_settles_dig_truncated"] = bool(
                    exp.get("expansion_settles_dig_truncated")
                )
                result["s5b_g6_impl_id"] = exp.get("s5b_g6_impl_id")
        except Exception:
            result.setdefault("settles_deferred_scans", 0)
            result.setdefault("settles_dead_scans", 0)
            result.setdefault("settles_ok_scans", 0)
            result.setdefault("settles_deferred_events", [])
            result.setdefault("settles_dead_events", [])

    if extra:
        for k, v in dict(extra).items():
            if k in REQUIRED_RESULT_KEYS and k in result:
                # Do not silently overwrite core keys via extra
                continue
            result[k] = v

    return result


def default_result_path(
    *,
    sequence_number: int = 1,
    game_id: str = "",
    directory: Optional[Union[str, Path]] = None,
    timestamp: Optional[str] = None,
) -> Path:
    """Default path for ``result.json`` (project-relative batch_runs folder)."""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    gid = str(game_id or "game").replace(os.sep, "_").replace("/", "_")
    folder_name = f"{ts}_g{int(sequence_number):03d}"
    if directory is not None:
        base = Path(directory)
    else:
        base = Path.cwd() / "batch_runs" / folder_name
    base.mkdir(parents=True, exist_ok=True)
    # If directory was a full run dir already, write result.json there
    if directory is not None:
        return Path(directory) / "result.json"
    return base / "result.json"


def write_result(
    path: Union[str, Path],
    data: Mapping[str, Any],
    *,
    indent: int = 2,
) -> Path:
    """Write result dict as UTF-8 JSON; create parent dirs; return resolved path."""
    out = Path(path)
    if out.suffix.lower() != ".json":
        out = out / "result.json" if out.suffix == "" else out
    parent = out.parent
    if parent and str(parent) not in (".", ""):
        parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(data), indent=indent, ensure_ascii=False, default=str)
    out.write_text(text + "\n", encoding="utf-8")
    return out.resolve()


def build_and_write_result(
    game: Any,
    path: Optional[Union[str, Path]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Build result, write to path (auto default if None), attach ``result_path``."""
    result = build_result(game, **kwargs)
    if path is None:
        path = default_result_path(
            sequence_number=int(result.get("sequence_number") or 1),
            game_id=str(result.get("game_id") or ""),
        )
    written = write_result(path, result)
    result["result_path"] = str(written)
    # Rewrite with path included for self-description
    write_result(written, result)
    return result


def validate_result_shape(data: Mapping[str, Any]) -> List[str]:
    """Return list of missing required keys (empty if OK)."""
    missing = []
    for key in sorted(REQUIRED_RESULT_KEYS):
        if key not in data:
            missing.append(key)
    return missing
