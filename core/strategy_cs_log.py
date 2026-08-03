"""Change-Strategy (FILENAME_CS) log: write (CS-1) + read (CS-3).

Append-only JSON Lines inside the project ``FILENAME_CS`` ``.txt`` file
(e.g. ``Catan16Mar2026_v1_CS.txt``).  Each line is one JSON object.

- CS-1: build row + append
- CS-2: callers wire append into strategy refresh (see strategy_history)
- CS-3: parse JSONL and map rows back to STR history samples

Always on — no feature flag.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from core.constants import FILENAME_CS
except Exception:  # pragma: no cover
    FILENAME_CS = "Catan_CS.txt"

CS_SCHEMA_VERSION = 1
RESOURCE_ORDER = ("Wheat", "Ore", "Wood", "Brick", "Sheep")

# Module-level: ensure header written once per process/path
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
        if f != f:  # NaN
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


def cs_log_path(filename: Optional[str] = None) -> str:
    """Absolute path for the CS log (cwd / project, same style as other FILENAME_*)."""
    name = str(filename or FILENAME_CS or "Catan_CS.txt")
    if os.path.isabs(name):
        return name
    return os.path.abspath(name)


def _ensure_header(path: str) -> None:
    if path in _header_written_paths:
        return
    exists = os.path.isfile(path) and os.path.getsize(path) > 0
    _header_written_paths.add(path)
    if exists:
        return
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(
                f"# Catan strategy change log (CS) | schema={CS_SCHEMA_VERSION} | JSONL\n"
            )
    except Exception:
        pass


def _way_id(preferred: Mapping[str, Any]) -> Optional[int]:
    raw = preferred.get("preferred_way_id", preferred.get("way_id"))
    try:
        if raw is None or raw == "" or raw == "-":
            return None
        return int(float(raw))
    except Exception:
        return None


def _hand_vector(player: Any) -> Optional[List[float]]:
    try:
        from core.resource_time_estimator import get_player_resource_cards_vector

        vec = get_player_resource_cards_vector(player)
        return [float(x or 0) for x in list(vec)[:5]]
    except Exception:
        pass
    try:
        info = player.rcards_in_hand()
        if isinstance(info, (list, tuple)) and info:
            hand = info[0] if isinstance(info[0], (list, tuple)) else info
            return [float(x or 0) for x in list(hand)[:5]]
    except Exception:
        pass
    try:
        rcards = getattr(player, "rcards", {}) or {}
        if isinstance(rcards, Mapping):
            out = []
            for name in RESOURCE_ORDER:
                val = 0.0
                for k, v in rcards.items():
                    kn = getattr(k, "value", k)
                    if str(kn) == name:
                        val = float(v or 0)
                        break
                out.append(val)
            return out
    except Exception:
        pass
    return None


def _production_pips(game: Any, player: Any) -> Optional[List[float]]:
    board = getattr(game, "board", None) if game is not None else None
    try:
        from core.resource_time_estimator import get_player_production_pips

        if board is not None and player is not None:
            pips = get_player_production_pips(board, player)
            return [float(x or 0) for x in list(pips)[:5]]
    except Exception:
        pass
    try:
        if player is not None and board is not None and hasattr(player, "get_current_production_pips"):
            pips = player.get_current_production_pips(board)
            return [float(x or 0) for x in list(pips)[:5]]
    except Exception:
        pass
    return None


def _trade_rates(game: Any, player: Any) -> Optional[List[int]]:
    board = getattr(game, "board", None) if game is not None else None
    try:
        from core.resource_time_estimator import get_player_trade_rates

        if board is not None and player is not None:
            rates = get_player_trade_rates(board, player)
            return [int(x or 4) for x in list(rates)[:5]]
    except Exception:
        pass
    try:
        rates = getattr(player, "trade_rates", None)
        if isinstance(rates, (list, tuple)):
            return [int(x or 4) for x in list(rates)[:5]]
    except Exception:
        pass
    return None


def _dcard_summary_compact(player: Any) -> str:
    """Compact triplets: VP:n/p/r;knight:n/p/r;..."""
    parts: List[str] = []
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            if not row:
                continue
            name = str(row[0] or "")
            short = {
                "victory_point": "VP",
                "knight": "K",
                "two_free_roads": "TFR",
                "year_of_plenty": "YOP",
                "monopoly": "M",
            }.get(name, name[:4])
            n = int(row[1] or 0) if len(row) > 1 else 0
            p = int(row[2] or 0) if len(row) > 2 else 0
            r = int(row[3] or 0) if len(row) > 3 else 0
            if n or p or r:
                parts.append(f"{short}:{n}/{p}/{r}")
    except Exception:
        pass
    return ";".join(parts)


def _way_tags_and_reqs(preferred: Mapping[str, Any], way_id: Optional[int]) -> Dict[str, Any]:
    """Way composition tags + requirement counts when loadable."""
    out: Dict[str, Any] = {
        "way_tags": [],
        "req_cities": None,
        "req_settles": None,
        "req_roads": None,
        "req_dcards": None,
        "way_lr": None,
        "way_la": None,
    }
    # Tags from preferred strategy if present
    tags = preferred.get("tags")
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)):
        out["way_tags"] = [str(t) for t in tags][:12]
    # Requirements from strategy table (avoid GUI imports)
    try:
        from core.strategy_timing import load_strategy_requirements

        if way_id is not None:
            for strategy in load_strategy_requirements():
                if int(getattr(strategy, "way_id", -1)) != int(way_id):
                    continue
                out["req_cities"] = _safe_int(getattr(strategy, "city_upgrades", None))
                out["req_settles"] = _safe_int(getattr(strategy, "new_settlements_to_build", None))
                out["req_roads"] = _safe_int(getattr(strategy, "roads_to_build", None))
                out["req_dcards"] = _safe_int(getattr(strategy, "development_cards_to_buy", None))
                out["way_lr"] = bool(getattr(strategy, "longest_road", False))
                out["way_la"] = bool(
                    getattr(strategy, "biggest_army", False)
                    or getattr(strategy, "largest_army", False)
                )
                # Build compact tags from requirements when preferred.tags empty
                if not out["way_tags"]:
                    tag_bits = []
                    if out["way_la"]:
                        tag_bits.append("LA")
                    if out["way_lr"]:
                        tag_bits.append("LR")
                    if out["req_cities"]:
                        tag_bits.append(f"C{out['req_cities']}")
                    if out["req_settles"]:
                        tag_bits.append(f"S{out['req_settles']}")
                    if out["req_dcards"]:
                        tag_bits.append(f"DC{out['req_dcards']}")
                    out["way_tags"] = tag_bits
                break
    except Exception:
        pass
    # Prefer explicit fields on preferred
    for src, dst in (
        ("required_cities", "req_cities"),
        ("city_upgrades", "req_cities"),
        ("required_new_intersections", "req_settles"),
        ("new_settlements_to_build", "req_settles"),
        ("roads_to_build", "req_roads"),
        ("development_cards_to_buy", "req_dcards"),
    ):
        if preferred.get(src) is not None and out[dst] is None:
            out[dst] = _safe_int(preferred.get(src))
    return out


def _player_progress(player: Any) -> Dict[str, Any]:
    try:
        settles = len(list(getattr(player, "settlements", []) or []))
    except Exception:
        settles = None
    try:
        cities = len(list(getattr(player, "cities", []) or []))
    except Exception:
        cities = None
    try:
        roads = len(list(getattr(player, "roads", []) or []))
    except Exception:
        roads = None
    vp = None
    try:
        from core.victory import effective_vp

        vp = int(effective_vp(player))
    except Exception:
        vp = _safe_int(getattr(player, "victory_points", None) or getattr(player, "points", None))
    return {
        "settlements_owned": settles,
        "cities_owned": cities,
        "roads_owned": roads,
        "vp_effective": vp,
        "lr_flag": bool(getattr(player, "longest_route_tf", False)),
        "la_flag": bool(getattr(player, "largest_army_tf", False)),
        "size_longest_route": _safe_int(getattr(player, "size_longest_route", None), 0),
        "size_largest_army": _safe_int(getattr(player, "size_largest_army", None), 0),
        "number_of_dcards": _safe_int(getattr(player, "number_of_dcards", None), 0),
    }


def _specials(game: Any) -> Dict[str, Any]:
    def _pid(p: Any) -> Optional[int]:
        return _safe_int(getattr(p, "id", None)) if p is not None else None

    return {
        "lr_holder_id": _pid(getattr(game, "longest_road_player", None)) if game else None,
        "la_holder_id": _pid(getattr(game, "largest_army_player", None)) if game else None,
    }


def _turns_fields(preferred: Mapping[str, Any], game: Any) -> Dict[str, Any]:
    turns = None
    for key in (
        "risk_adjusted_total_expected_own_turns",
        "total_expected_own_turns",
        "board_expected_turns",
        "realistic_expected_turns",
        "baseline_best_expected_own_turns",
    ):
        turns = _safe_float(preferred.get(key))
        if turns is not None and turns < 9000:
            break
        turns = None
    # Prefer matching board audit
    if game is not None:
        try:
            way = _way_id(preferred)
            audits = list(getattr(game, "current_board_way_audits", None) or [])
            audit = getattr(game, "current_board_way_audit", None)
            if isinstance(audit, Mapping):
                audits = [audit] + audits
            for a in audits:
                if not isinstance(a, Mapping):
                    continue
                if way is not None and _safe_int(a.get("way_id"), -1) != way:
                    continue
                bt = _safe_float(
                    a.get("realistic_expected_turns") or a.get("board_expected_turns")
                )
                if bt is not None and bt < 9000:
                    turns = bt
                    break
        except Exception:
            pass
    abstract = _safe_float(
        preferred.get("abstract_expected_turns")
        or preferred.get("baseline_best_expected_own_turns")
    )
    return {"turns": turns, "abstract_turns": abstract if abstract and abstract < 9000 else None}


def _target_pack_summary(preferred: Mapping[str, Any], game: Any) -> Dict[str, Any]:
    """Optional risk/ETA summary for supporting / recommended settle target."""
    out: Dict[str, Any] = {
        "supporting_action_type": str(preferred.get("supporting_action_type") or "") or None,
        "supporting_target_id": preferred.get("supporting_action_target_id")
        or preferred.get("supporting_action_future_settlement_target_id"),
        "rec_target_id": None,
        "self_eta": None,
        "risk_level": None,
        "threat_summary": None,
        "win_span": None,
        "priority_score": None,
        "priority_reason": None,
    }
    # From board audit recommendation / supporting target
    try:
        audit = getattr(game, "current_board_way_audit", None) if game else None
        if isinstance(audit, Mapping):
            out["rec_target_id"] = audit.get("recommendation_target_id")
            portfolio = list(audit.get("target_portfolio") or [])
            candidates = []
            for key in (out["supporting_target_id"], out["rec_target_id"]):
                if key is not None:
                    candidates.append(_safe_int(key))
            # Prefer matching supporting/rec target; else first portfolio row with timing
            chosen = None
            for tid in candidates:
                for t in portfolio:
                    if isinstance(t, Mapping) and _safe_int(t.get("target_id"), -1) == tid:
                        chosen = t
                        break
                if chosen is not None:
                    break
            if chosen is None:
                for t in portfolio:
                    if isinstance(t, Mapping) and t.get("self_eta_own_turns") is not None:
                        chosen = t
                        break
            if isinstance(chosen, Mapping):
                out["self_eta"] = _safe_float(chosen.get("self_eta_own_turns"))
                out["risk_level"] = str(chosen.get("risk_level") or "") or None
                out["priority_score"] = _safe_float(chosen.get("priority_score"))
                out["priority_reason"] = str(chosen.get("priority_reason") or "")[:100] or None
                base = _safe_float(chosen.get("baseline_win_turns"))
                win_if = _safe_float(chosen.get("win_turns_if_target"))
                if base is not None and win_if is not None:
                    out["win_span"] = f"{base:.1f}→{win_if:.1f}"
                threats = chosen.get("threat_opponents") or []
                if threats:
                    try:
                        from core.risk_assessment import format_threat_opponents_short

                        out["threat_summary"] = format_threat_opponents_short(list(threats)) or None
                    except Exception:
                        out["threat_summary"] = None
    except Exception:
        pass
    return out


def build_strategy_cs_row(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
    *,
    reason: str = "",
    sample_kind: str = "refresh",
    prev_sample: Optional[Mapping[str, Any]] = None,
    ok: bool = True,
    error: str = "",
) -> Dict[str, Any]:
    """Build one CS log record (dict) — does not write to disk.

    Parameters
    ----------
    preferred
        Strategic direction / preferred_strategy mapping (may be empty).
    prev_sample
        Previous CS or history sample for the same player (for prev_way / delta).
    """
    preferred = preferred if isinstance(preferred, Mapping) else {}
    prev_sample = prev_sample if isinstance(prev_sample, Mapping) else {}

    way = _way_id(preferred)
    prev_way = _safe_int(prev_sample.get("way_id") or prev_sample.get("preferred_way_id"))
    turns_info = _turns_fields(preferred, game)
    prev_turns = _safe_float(prev_sample.get("turns"))
    turns = turns_info.get("turns")
    delta = None
    if turns is not None and prev_turns is not None:
        delta = round(float(turns) - float(prev_turns), 3)

    board_way = preferred.get("board_context_way_id") or preferred.get("board_rank_way_id")
    try:
        board_way_i = int(float(board_way)) if board_way not in (None, "", "-") else None
    except Exception:
        board_way_i = None

    way_pack = _way_tags_and_reqs(preferred, way)
    progress = _player_progress(player) if player is not None else {}
    specials = _specials(game)
    target_pack = _target_pack_summary(preferred, game)
    hand = _hand_vector(player) if player is not None else None
    pips = _production_pips(game, player) if player is not None else None

    row: Dict[str, Any] = {
        "schema": CS_SCHEMA_VERSION,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ok": bool(ok),
        "error": str(error or "") or None,
        "game_id": str(getattr(game, "id", "") or "") or None,
        "sequence_number": _safe_int(getattr(game, "sequence_number", None)),
        "round": _safe_int(getattr(game, "round", None), 0),
        "turn": _safe_int(getattr(game, "turn", None), 0),
        "state": str(getattr(game, "state", "") or "") or None,
        "phase": str(getattr(game, "phase", "") or "") or None,
        "player_id": _safe_int(getattr(player, "id", None)) if player is not None else None,
        "color": str(getattr(player, "color", "") or "") if player is not None else None,
        "is_human": bool(getattr(player, "is_human", False)) if player is not None else None,
        "reason": str(reason or preferred.get("strategy_context_reason") or "") or None,
        "sample_kind": str(sample_kind or "refresh"),
        # Strategy
        "way_id": way,
        "prev_way_id": prev_way if prev_way != way else None,
        "board_way_id": board_way_i,
        "preference_level": str(preferred.get("preference_level") or "") or None,
        "preference_reason": str(preferred.get("preference_reason") or "")[:120] or None,
        "turns": turns,
        "prev_turns": prev_turns,
        "delta_turns": delta,
        "abstract_turns": turns_info.get("abstract_turns"),
        # Way composition
        "way_tags": way_pack.get("way_tags") or [],
        "req_cities": way_pack.get("req_cities"),
        "req_settles": way_pack.get("req_settles"),
        "req_roads": way_pack.get("req_roads"),
        "req_dcards": way_pack.get("req_dcards"),
        "way_lr": way_pack.get("way_lr"),
        "way_la": way_pack.get("way_la"),
        # Player progress
        "settlements_owned": progress.get("settlements_owned"),
        "cities_owned": progress.get("cities_owned"),
        "roads_owned": progress.get("roads_owned"),
        "vp_effective": progress.get("vp_effective"),
        "lr_flag": progress.get("lr_flag"),
        "la_flag": progress.get("la_flag"),
        "size_longest_route": progress.get("size_longest_route"),
        "size_largest_army": progress.get("size_largest_army"),
        "number_of_dcards": progress.get("number_of_dcards"),
        # Resources / DCards
        "hand": hand,
        "hand_total": round(sum(hand), 3) if hand else None,
        "production_pips": pips,
        "trade_rates": _trade_rates(game, player) if player is not None else None,
        "dcard_summary": _dcard_summary_compact(player) if player is not None else "",
        "dcard_played_this_turn": None,  # filled below if known
        # Specials
        "lr_holder_id": specials.get("lr_holder_id"),
        "la_holder_id": specials.get("la_holder_id"),
        # Supporting / risk pack summary
        "supporting_action_type": target_pack.get("supporting_action_type"),
        "supporting_target_id": target_pack.get("supporting_target_id"),
        "rec_target_id": target_pack.get("rec_target_id"),
        "self_eta": target_pack.get("self_eta"),
        "risk_level": target_pack.get("risk_level"),
        "threat_summary": target_pack.get("threat_summary"),
        "win_span": target_pack.get("win_span"),
        "priority_score": target_pack.get("priority_score"),
        "priority_reason": target_pack.get("priority_reason"),
    }

    # DCard played this turn
    try:
        td = getattr(game, "myturn", None) or getattr(game, "turn_details", None)
        if td is not None:
            row["dcard_played_this_turn"] = bool(getattr(td, "dcard_played_in_turn_TF", False))
    except Exception:
        pass

    # Drop keys with empty lists that are pure noise? Keep structure stable for parsers.
    return row


def append_strategy_cs_line(
    row: Mapping[str, Any],
    *,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one JSONL row to FILENAME_CS. Returns {ok, path, error?}."""
    path = cs_log_path(filename)
    result: Dict[str, Any] = {"ok": False, "path": path, "error": ""}
    try:
        _ensure_header(path)
        line = json.dumps(dict(row), ensure_ascii=False, default=_json_default, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def log_strategy_cs(
    game: Any,
    player: Any,
    preferred: Optional[Mapping[str, Any]] = None,
    *,
    reason: str = "",
    sample_kind: str = "refresh",
    prev_sample: Optional[Mapping[str, Any]] = None,
    filename: Optional[str] = None,
    ok: bool = True,
    error: str = "",
) -> Dict[str, Any]:
    """CS-1 convenience: build row and append. Safe no-op on failure.

    Returns ``{ok, path, row, error}``.
    """
    row = build_strategy_cs_row(
        game,
        player,
        preferred,
        reason=reason,
        sample_kind=sample_kind,
        prev_sample=prev_sample,
        ok=ok,
        error=error,
    )
    written = append_strategy_cs_line(row, filename=filename)
    return {
        "ok": bool(written.get("ok")),
        "path": written.get("path"),
        "row": row,
        "error": written.get("error") or "",
    }


# ── CS-3: read / map ─────────────────────────────────────────────────────────


def iter_cs_log_rows(
    filename: Optional[str] = None,
    *,
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Parse FILENAME_CS JSONL into a list of row dicts (skips # comments / bad lines).

    Returns an empty list if the file is missing or unreadable.
    """
    file_path = path or cs_log_path(filename)
    out: List[Dict[str, Any]] = []
    try:
        if not os.path.isfile(file_path):
            return out
        with open(file_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except Exception:
        return out
    return out


def cs_row_to_history_sample(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Map one CS log row to a compact ``strategy_history_samples`` entry (PR-D shape)."""
    row = row if isinstance(row, Mapping) else {}
    reason_raw = str(row.get("reason") or "")
    # Keep short like live samples
    try:
        from core.strategy_history import _short_reason

        reason = _short_reason(reason_raw)
    except Exception:
        reason = reason_raw[:18] if reason_raw else "refresh"

    sample: Dict[str, Any] = {
        "round": _safe_int(row.get("round"), 0) or 0,
        "turn": _safe_int(row.get("turn"), 0) or 0,
        "state": str(row.get("state") or "") or "",
        "reason": reason or "refresh",
        "sample_kind": str(row.get("sample_kind") or "refresh"),
        "way_id": _safe_int(row.get("way_id")),
        "board_way_id": _safe_int(row.get("board_way_id")),
        "turns": _safe_float(row.get("turns")),
        "abstract_turns": _safe_float(row.get("abstract_turns")),
        "supporting_target_id": row.get("supporting_target_id"),
        "ts": str(row.get("ts") or "") or None,
        "source": "cs_log",
    }
    prev_way = _safe_int(row.get("prev_way_id"))
    if prev_way is not None:
        sample["prev_way_id"] = prev_way
    return sample


def filter_cs_rows_for_player(
    rows: Sequence[Mapping[str, Any]],
    *,
    game_id: Optional[str],
    player_id: Optional[int],
    sequence_number: Optional[int] = None,
    max_round: Optional[int] = None,
    max_turn: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Select CS rows for one player in one game, up to a round/turn ceiling.

    Matching rules
    --------------
    - ``game_id``: required when provided on the filter; row must match.
      Rows with missing/empty game_id never match a concrete game_id.
    - ``player_id``: required; row must match.
    - ``sequence_number``: when both filter and row have a non-null value, must match.
    - ``max_round`` / ``max_turn``: keep samples at or before this (R, T) so a
      mid-game load does not pull later-play history written after the save.
    """
    gid = str(game_id).strip() if game_id not in (None, "") else ""
    pid = _safe_int(player_id)
    if pid is None:
        return []
    seq = _safe_int(sequence_number)
    mr = _safe_int(max_round)
    mt = _safe_int(max_turn)

    matched: List[Dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, Mapping):
            continue
        row_gid = str(raw.get("game_id") or "").strip()
        if gid:
            if not row_gid or row_gid != gid:
                continue
        row_pid = _safe_int(raw.get("player_id"))
        if row_pid is None or int(row_pid) != int(pid):
            continue
        row_seq = _safe_int(raw.get("sequence_number"))
        if seq is not None and row_seq is not None and int(row_seq) != int(seq):
            continue
        r = _safe_int(raw.get("round"), 0) or 0
        t = _safe_int(raw.get("turn"), 0) or 0
        if mr is not None and mt is not None:
            if (r, t) > (int(mr), int(mt)):
                continue
        elif mr is not None and r > int(mr):
            continue
        matched.append(dict(raw))
    return matched


__all__ = [
    "CS_SCHEMA_VERSION",
    "cs_log_path",
    "build_strategy_cs_row",
    "append_strategy_cs_line",
    "log_strategy_cs",
    "iter_cs_log_rows",
    "cs_row_to_history_sample",
    "filter_cs_rows_for_player",
    "FILENAME_CS",
]
