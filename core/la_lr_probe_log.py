"""Phase L WP-L1: god-view LA/LR probe JSONL sampler.

Logs multi-opponent race snapshots for offline give-up threshold work.
Does **not** change Strategy-Engine policy (no give-up → L2 here).

Sinks:
  - ``batch_dir/la_lr_probe.jsonl`` when GameManager sets path override
  - else ``{FILENAME_HELP}_LaLrProbe.jsonl``
  - ``player.last_la_lr_probe_row`` (dig-in)

See ``docs/PhaseL_la_lr_probe_plan.md``, ``docs/PhaseL_la_lr_field_matrix.md``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

PROBE_SCHEMA_VERSION = 1
MAX_ROADS_CAP = 15

# Live L6 give-up fire events (same JSONL as samples; filtered out of L2/L3 by default)
EVENT_LA_GIVEUP_FIRE = "la_giveup_fire"
EVENT_LR_GIVEUP_FIRE = "lr_giveup_fire"
GIVEUP_FIRE_EVENTS = frozenset({EVENT_LA_GIVEUP_FIRE, EVENT_LR_GIVEUP_FIRE})
MAX_GIVEUP_FIRE_EVENTS_ON_GAME = 64  # cap in-memory list for result.json

# Phase L S7: salvage adopt dig rows (same JSONL; offline L2/L3 may skip)
EVENT_SALVAGE_ADOPT = "salvage_adopt"
# Events excluded from god-view θ sample iterators by default
PROBE_NON_SAMPLE_EVENTS = frozenset(
    {EVENT_LA_GIVEUP_FIRE, EVENT_LR_GIVEUP_FIRE, EVENT_SALVAGE_ADOPT}
)

_la_lr_probe_log_path_override: Optional[str] = None
_header_written_paths: set = set()


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


def _json_default(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    return str(obj)


def get_la_lr_probe_log_path_override() -> Optional[str]:
    return _la_lr_probe_log_path_override


def set_la_lr_probe_log_path(path: Optional[str]) -> Optional[str]:
    """Set process-wide probe JSONL path (batch). Returns previous override."""
    global _la_lr_probe_log_path_override
    prev = _la_lr_probe_log_path_override
    if path is None or str(path).strip() == "":
        _la_lr_probe_log_path_override = None
    else:
        _la_lr_probe_log_path_override = str(path)
    return prev


def default_la_lr_probe_log_path() -> str:
    try:
        from core.constants import FILENAME_HELP

        base = str(FILENAME_HELP or "Catan")
    except Exception:
        base = "Catan"
    return f"{base}_LaLrProbe.jsonl"


def la_lr_probe_log_path(filename: Optional[str] = None) -> str:
    if _la_lr_probe_log_path_override:
        return str(_la_lr_probe_log_path_override)
    if filename:
        return str(filename)
    return default_la_lr_probe_log_path()


def log_la_lr_probe_enabled(game: Any = None) -> bool:
    try:
        from core import constants as C

        if hasattr(C, "LOG_LA_LR_PROBE"):
            return bool(getattr(C, "LOG_LA_LR_PROBE"))
    except Exception:
        pass
    return True


def _append_jsonl(path: str, row: Mapping[str, Any]) -> None:
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    write_header = str(p.resolve()) not in _header_written_paths and (
        not p.is_file() or p.stat().st_size == 0
    )
    with p.open("a", encoding="utf-8") as f:
        if write_header:
            f.write(
                f"# Catan LA/LR probe (god-view) | schema={PROBE_SCHEMA_VERSION} | JSONL\n"
            )
            _header_written_paths.add(str(p.resolve()))
        f.write(json.dumps(dict(row), ensure_ascii=False, default=_json_default) + "\n")


def append_la_lr_probe_row(path: PathLike, row: Mapping[str, Any]) -> None:
    """Public sink for dig events (give-up fire, salvage adopt, samples)."""
    _append_jsonl(str(path), row)


def _pid(p: Any) -> Optional[int]:
    return _safe_int(getattr(p, "id", None)) if p is not None else None


def _army_size(player: Any) -> int:
    try:
        return max(0, int(getattr(player, "size_largest_army", 0) or 0))
    except Exception:
        return 0


def _path_length(game: Any, player: Any) -> int:
    stored = max(0, _safe_int(getattr(player, "size_longest_route", 0), 0) or 0)
    engine = 0
    try:
        from core.longest_road import compute_longest_road_for_player

        res = compute_longest_road_for_player(game, player)
        if isinstance(res, Mapping):
            engine = max(0, int(res.get("length", res.get("size", 0)) or 0))
        else:
            engine = max(0, int(getattr(res, "length", 0) or 0))
    except Exception:
        engine = 0
    return max(stored, engine)


def _roads_owned(player: Any) -> int:
    try:
        return len(list(getattr(player, "roads", None) or []))
    except Exception:
        return 0


def _holds_la(player: Any, game: Any) -> bool:
    if bool(getattr(player, "largest_army_tf", False) or getattr(player, "biggest_army_tf", False)):
        return True
    holder = getattr(game, "largest_army_player", None) if game is not None else None
    if holder is None or player is None:
        return False
    try:
        return int(getattr(holder, "id", -1)) == int(getattr(player, "id", -2))
    except Exception:
        return holder is player


def _holds_lr(player: Any, game: Any) -> bool:
    if bool(getattr(player, "longest_route_tf", False) or getattr(player, "longest_road_tf", False)):
        return True
    holder = getattr(game, "longest_road_player", None) if game is not None else None
    if holder is None or player is None:
        return False
    try:
        return int(getattr(holder, "id", -1)) == int(getattr(player, "id", -2))
    except Exception:
        return holder is player


# way_id → (needs_la, needs_lr) from Victory-Way requirements table
_way_specials_cache: Optional[Dict[int, Tuple[bool, bool]]] = None


def _load_way_specials_table() -> Dict[int, Tuple[bool, bool]]:
    global _way_specials_cache
    if _way_specials_cache is not None:
        return _way_specials_cache
    out: Dict[int, Tuple[bool, bool]] = {}
    try:
        from core.strategy_timing import load_strategy_requirements

        for strategy in load_strategy_requirements() or []:
            try:
                wid = int(getattr(strategy, "way_id", -1))
            except Exception:
                continue
            if wid <= 0:
                continue
            la = bool(
                getattr(strategy, "biggest_army", False)
                or getattr(strategy, "largest_army", False)
            )
            lr = bool(
                getattr(strategy, "longest_road", False)
                or getattr(strategy, "longest_route", False)
            )
            out[wid] = (la, lr)
    except Exception:
        out = {}
    _way_specials_cache = out
    return out


def _way_ids_for_player(player: Any) -> List[int]:
    """Sticky lock first, then preferred / board way ids."""
    ids: List[int] = []
    seen = set()

    def _add(raw: Any) -> None:
        wid = _safe_int(raw)
        if wid is None or wid <= 0 or wid in seen:
            return
        seen.add(wid)
        ids.append(int(wid))

    if player is None:
        return ids
    try:
        sticky = getattr(player, "sticky_commitment", None) or {}
        if isinstance(sticky, Mapping):
            _add(sticky.get("locked_way_id"))
            _add(sticky.get("way_id"))
            _add(sticky.get("preferred_way_id"))
    except Exception:
        pass
    try:
        d = getattr(player, "strategic_direction", None) or {}
        if isinstance(d, Mapping):
            _add(d.get("preferred_way_id"))
            _add(d.get("way_id"))
            _add(d.get("board_way_id"))
            _add(d.get("board_context_way_id"))
            # nested preferred
            pref = d.get("preferred_strategy")
            if isinstance(pref, Mapping):
                _add(pref.get("preferred_way_id") or pref.get("way_id"))
    except Exception:
        pass
    return ids


def _tag_items(player: Any) -> List[str]:
    """Only explicit tags/way_tags lists — never preference_reason dumps (false positives)."""
    items: List[str] = []
    if player is None:
        return items
    for obj_name in ("strategic_direction", "sticky_commitment"):
        try:
            obj = getattr(player, obj_name, None) or {}
            if not isinstance(obj, Mapping):
                continue
            for key in ("tags", "way_tags"):
                tags = obj.get(key)
                if isinstance(tags, (list, tuple)):
                    items.extend(str(t).strip() for t in tags if t is not None and str(t).strip())
                elif isinstance(tags, str) and tags.strip():
                    items.append(tags.strip())
        except Exception:
            pass
    return items


def _tags_match_la(player: Any) -> Tuple[bool, str]:
    """Strict LA tag match: full phrases or exact token LA — not 'largest'+'army' loose."""
    for raw in _tag_items(player):
        t = raw.lower().strip()
        if t in ("la", "largest_army", "biggest_army", "largestarmy", "biggestarmy"):
            return True, "tags_la_token"
        if "largest army" in t or "biggest army" in t:
            return True, "tags_la_phrase"
        # Compact requirement-style tag from CS builder: exact "LA"
        if t == "la" or t.startswith("la ") or t.endswith(" la"):
            return True, "tags_la_token"
    return False, ""


def _tags_match_lr(player: Any) -> Tuple[bool, str]:
    """Strict LR tag match: full phrase or exact LR — not bare 'longest' alone."""
    for raw in _tag_items(player):
        t = raw.lower().strip()
        if t in ("lr", "longest_road", "longest_route", "longestroad"):
            return True, "tags_lr_token"
        if "longest road" in t or "longest route" in t:
            return True, "tags_lr_phrase"
    return False, ""


def _table_needs(way_ids: Sequence[int]) -> Tuple[bool, bool, Optional[int], Optional[int]]:
    """Return (any_la, any_lr, first_la_way_id, first_lr_way_id)."""
    table = _load_way_specials_table()
    any_la = any_lr = False
    la_wid = lr_wid = None
    for wid in way_ids:
        pair = table.get(int(wid))
        if not pair:
            continue
        la, lr = pair
        if la and not any_la:
            any_la = True
            la_wid = int(wid)
        if lr and not any_lr:
            any_lr = True
            lr_wid = int(wid)
    return any_la, any_lr, la_wid, lr_wid


def resolve_needs_la(player: Any) -> Tuple[bool, str]:
    """Canonical needs_LA + short reason (for probe dig-in)."""
    if player is None:
        return False, "no_player"
    way_ids = _way_ids_for_player(player)
    tab_la, _tab_lr, la_wid, _ = _table_needs(way_ids)
    if tab_la:
        return True, f"way_table_la:{la_wid}"

    try:
        from core.ai_la_progress import way_wants_largest_army

        if way_wants_largest_army(player):
            return True, "way_wants_largest_army"
    except Exception:
        pass
    try:
        from core.strategy_way_kill import way_needs_largest_army

        d = getattr(player, "strategic_direction", None) or {}
        if isinstance(d, Mapping) and way_needs_largest_army(d):
            return True, "direction_way_needs_la"
        sticky = getattr(player, "sticky_commitment", None) or {}
        if isinstance(sticky, Mapping) and way_needs_largest_army(sticky):
            return True, "sticky_way_needs_la"
    except Exception:
        pass

    # Sticky / direction explicit flags
    for obj_name, label in (
        ("strategic_direction", "direction"),
        ("sticky_commitment", "sticky"),
    ):
        try:
            obj = getattr(player, obj_name, None) or {}
            if not isinstance(obj, Mapping):
                continue
            if bool(
                obj.get("biggest_army")
                or obj.get("largest_army")
                or obj.get("wants_largest_army")
            ):
                return True, f"{label}_flag_la"
            summary = obj.get("strategy_summary")
            if isinstance(summary, Mapping) and bool(
                summary.get("biggest_army") or summary.get("largest_army")
            ):
                return True, f"{label}_summary_la"
        except Exception:
            pass

    # Active LA progress project implies pursuit
    try:
        from core.ai_la_progress import get_stored_la_progress

        prog = get_stored_la_progress(player, None)
        if isinstance(prog, Mapping) and prog:
            # ignore empty / killed markers
            if not prog.get("killed") and not prog.get("cleared"):
                return True, "la_progress_token"
    except Exception:
        pass

    hit, why = _tags_match_la(player)
    if hit:
        return True, why

    return False, "none"


def resolve_needs_lr(player: Any) -> Tuple[bool, str]:
    """Canonical needs_LR + short reason."""
    if player is None:
        return False, "no_player"
    way_ids = _way_ids_for_player(player)
    _tab_la, tab_lr, _, lr_wid = _table_needs(way_ids)
    if tab_lr:
        return True, f"way_table_lr:{lr_wid}"

    try:
        from core.ai_lr_project import way_wants_longest_road

        if way_wants_longest_road(player):
            return True, "way_wants_longest_road"
    except Exception:
        pass
    try:
        from core.ai_road_planner import way_wants_longest_road as _w_road

        if _w_road(player):
            return True, "road_planner_wants_lr"
    except Exception:
        pass
    try:
        from core.strategy_way_kill import way_needs_longest_road

        d = getattr(player, "strategic_direction", None) or {}
        if isinstance(d, Mapping) and way_needs_longest_road(d):
            return True, "direction_way_needs_lr"
        sticky = getattr(player, "sticky_commitment", None) or {}
        if isinstance(sticky, Mapping) and way_needs_longest_road(sticky):
            return True, "sticky_way_needs_lr"
    except Exception:
        pass

    for obj_name, label in (
        ("strategic_direction", "direction"),
        ("sticky_commitment", "sticky"),
    ):
        try:
            obj = getattr(player, obj_name, None) or {}
            if not isinstance(obj, Mapping):
                continue
            if bool(
                obj.get("longest_road")
                or obj.get("longest_route")
                or obj.get("wants_longest_road")
            ):
                return True, f"{label}_flag_lr"
            summary = obj.get("strategy_summary")
            if isinstance(summary, Mapping) and bool(summary.get("longest_road")):
                return True, f"{label}_summary_lr"
        except Exception:
            pass

    try:
        from core.ai_lr_project import get_stored_lr_project

        proj = get_stored_lr_project(player, None)
        if isinstance(proj, Mapping) and proj:
            if not proj.get("killed") and not proj.get("cleared"):
                return True, "lr_project_token"
    except Exception:
        pass

    hit, why = _tags_match_lr(player)
    if hit:
        return True, why

    return False, "none"


def _needs_la(player: Any) -> bool:
    return resolve_needs_la(player)[0]


def _needs_lr(player: Any) -> bool:
    return resolve_needs_lr(player)[0]


def _knight_counts(player: Any) -> Tuple[int, int, int]:
    try:
        from core.ai_la_progress import _dcard_row_counts

        return _dcard_row_counts(player, "knight")
    except Exception:
        pass
    try:
        for row in list(getattr(player, "dcard_summary", None) or []):
            row_list = list(row or [])
            if not row_list or str(row_list[0]) != "knight":
                continue
            while len(row_list) < 4:
                row_list.append(0)
            return (
                max(0, int(row_list[1] or 0)),
                max(0, int(row_list[2] or 0)),
                max(0, int(row_list[3] or 0)),
            )
    except Exception:
        pass
    return (0, 0, 0)


def _way_id(player: Any) -> Optional[int]:
    try:
        sticky = getattr(player, "sticky_commitment", None) or {}
        if isinstance(sticky, Mapping):
            wid = sticky.get("locked_way_id") or sticky.get("way_id")
            if wid is not None:
                return _safe_int(wid)
    except Exception:
        pass
    try:
        d = getattr(player, "strategic_direction", None) or {}
        if isinstance(d, Mapping):
            return _safe_int(d.get("preferred_way_id") or d.get("way_id"))
    except Exception:
        pass
    return None


def _sticky_eta(player: Any) -> Optional[float]:
    try:
        d = getattr(player, "strategic_direction", None) or {}
        if not isinstance(d, Mapping):
            return None
        for key in (
            "risk_adjusted_total_expected_own_turns",
            "total_expected_own_turns",
            "board_expected_turns",
            "realistic_expected_turns",
        ):
            v = _safe_float(d.get(key))
            if v is not None and v < 9000:
                return v
    except Exception:
        pass
    return None


def _seat_public_snapshot(game: Any) -> List[Dict[str, Any]]:
    """All seats: army, path, roads, holders flags (god-view race board)."""
    out: List[Dict[str, Any]] = []
    la_h = _pid(getattr(game, "largest_army_player", None)) if game else None
    lr_h = _pid(getattr(game, "longest_road_player", None)) if game else None
    for p in list(getattr(game, "players", None) or []):
        if p is None:
            continue
        pid = _pid(p)
        army = _army_size(p)
        path = _path_length(game, p)
        roads = _roads_owned(p)
        out.append(
            {
                "player_id": pid,
                "army": army,
                "path": path,
                "roads": roads,
                "roads_remaining_cap": max(0, MAX_ROADS_CAP - roads),
                "holds_la": bool(pid is not None and pid == la_h)
                or _holds_la(p, game),
                "holds_lr": bool(pid is not None and pid == lr_h)
                or _holds_lr(p, game),
            }
        )
    return out


def _race_features(
    seats: Sequence[Mapping[str, Any]],
    focal_id: Optional[int],
) -> Dict[str, Any]:
    """Multi-opponent race gaps and threat counts for focal seat."""
    own = None
    for s in seats:
        if s.get("player_id") == focal_id:
            own = s
            break
    if own is None:
        return {
            "army_leader": None,
            "path_leader": None,
            "gap_la": None,
            "gap_lr": None,
            "n_threats_la": 0,
            "n_threats_lr": 0,
            "opp_armies": [],
            "opp_paths": [],
        }
    own_army = int(own.get("army") or 0)
    own_path = int(own.get("path") or 0)
    opp_armies = [
        int(s.get("army") or 0)
        for s in seats
        if s.get("player_id") != focal_id
    ]
    opp_paths = [
        int(s.get("path") or 0)
        for s in seats
        if s.get("player_id") != focal_id
    ]
    army_leader = max(opp_armies) if opp_armies else 0
    path_leader = max(opp_paths) if opp_paths else 0
    gap_la = max(0, army_leader - own_army)
    gap_lr = max(0, path_leader - own_path)
    n_threats_la = sum(1 for a in opp_armies if a >= max(0, own_army - 1))
    n_threats_lr = sum(1 for pth in opp_paths if pth >= max(0, own_path - 1))
    return {
        "army_leader": army_leader,
        "path_leader": path_leader,
        "gap_la": gap_la,
        "gap_lr": gap_lr,
        "n_threats_la": n_threats_la,
        "n_threats_lr": n_threats_lr,
        "opp_armies": opp_armies,
        "opp_paths": opp_paths,
    }


def build_la_lr_probe_row(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    event: str = "sample",
) -> Dict[str, Any]:
    """Build one god-view probe row (no I/O)."""
    seats = _seat_public_snapshot(game) if game is not None else []
    focal_id = _pid(player)
    race = _race_features(seats, focal_id)
    if player is not None:
        needs_la, needs_la_reason = resolve_needs_la(player)
        needs_lr, needs_lr_reason = resolve_needs_lr(player)
    else:
        needs_la, needs_la_reason = False, "no_player"
        needs_lr, needs_lr_reason = False, "no_player"
    holds_la = _holds_la(player, game) if player is not None else False
    holds_lr = _holds_lr(player, game) if player is not None else False
    roads = _roads_owned(player) if player is not None else 0
    k_new, k_play, k_rev = _knight_counts(player) if player is not None else (0, 0, 0)
    way_ids = _way_ids_for_player(player) if player is not None else []

    # S5.5 assess (reuse product hopeless logic)
    s55: Dict[str, Any] = {}
    la_meta: Dict[str, Any] = {}
    lr_meta: Dict[str, Any] = {}
    try:
        from core.strategy_specials_divert import assess_specials_for_player

        # store=False so probe does not thrash player.last_specials_assess mid-turn
        s55 = assess_specials_for_player(game, player, store=False)
        if isinstance(s55, Mapping):
            la_meta = dict(s55.get("la") or {}) if isinstance(s55.get("la"), Mapping) else {}
            lr_meta = dict(s55.get("lr") or {}) if isinstance(s55.get("lr"), Mapping) else {}
    except Exception as exc:
        s55 = {"error": str(exc)}

    # Prefer S5.5 gap when available (aligned with product kill)
    gap_la = race.get("gap_la")
    gap_lr = race.get("gap_lr")
    if la_meta.get("gap") is not None:
        gap_la = _safe_int(la_meta.get("gap"), gap_la)
    if lr_meta.get("gap") is not None:
        gap_lr = _safe_int(lr_meta.get("gap"), gap_lr)

    la_block = {
        "needs": bool(needs_la),
        "needs_reason": needs_la_reason,
        "holds": bool(holds_la),
        "army": _army_size(player) if player is not None else 0,
        "gap": gap_la,
        "n_threats": race.get("n_threats_la"),
        "army_leader": race.get("army_leader"),
        "hopeless": bool(la_meta.get("hopeless")),
        "unstoppable_opp": bool(la_meta.get("unstoppable_opp")),
        "still_live": la_meta.get("still_live"),
        "kill_recommended": bool(
            (s55 or {}).get("kill_la_recommended")
            if isinstance(s55, Mapping)
            else False
        )
        or bool(la_meta.get("hopeless") or la_meta.get("unstoppable_opp")),
        "assess_reason": str(la_meta.get("reason") or "")[:160] or None,
        "knights_needed": la_meta.get("knights_needed"),
        "knight_new": k_new,
        "knight_playable": k_play,
        "knight_revealed": k_rev,
    }
    lr_block = {
        "needs": bool(needs_lr),
        "needs_reason": needs_lr_reason,
        "holds": bool(holds_lr),
        "path": _path_length(game, player) if player is not None else 0,
        "roads": roads,
        "roads_remaining_cap": max(0, MAX_ROADS_CAP - roads),
        "gap": gap_lr,
        "n_threats": race.get("n_threats_lr"),
        "path_leader": race.get("path_leader"),
        "hopeless": bool(lr_meta.get("hopeless")),
        "unstoppable_opp": bool(lr_meta.get("unstoppable_opp")),
        "still_live": lr_meta.get("still_live"),
        "kill_recommended": bool(
            (s55 or {}).get("kill_lr_recommended")
            if isinstance(s55, Mapping)
            else False
        )
        or bool(lr_meta.get("hopeless") or lr_meta.get("unstoppable_opp")),
        "assess_reason": str(lr_meta.get("reason") or "")[:160] or None,
    }

    # Residuals if present
    try:
        from core.ai_la_progress import get_stored_la_progress

        prog = get_stored_la_progress(player, game)
        if isinstance(prog, Mapping) and prog:
            la_block["la_progress_keys"] = list(prog.keys())[:12]
    except Exception:
        pass
    try:
        from core.ai_lr_project import get_stored_lr_project, remaining_lr_project_roads

        proj = get_stored_lr_project(player, game)
        if isinstance(proj, Mapping) and proj:
            rem = remaining_lr_project_roads(game, player)
            lr_block["lr_project_residual_roads"] = len(list(rem or []))
    except Exception:
        pass

    row: Dict[str, Any] = {
        "schema": PROBE_SCHEMA_VERSION,
        "kind": "la_lr_probe",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": str(event or "sample"),
        "reason": str(reason or "")[:120] or None,
        "game_id": str(getattr(game, "id", "") or "") or None,
        "sequence_number": _safe_int(getattr(game, "sequence_number", None)),
        "batch_id": str(getattr(game, "batch_id", "") or "") or None,
        "round": _safe_int(getattr(game, "round", None), 0),
        "turn": _safe_int(getattr(game, "turn", None), 0),
        "player_id": focal_id,
        "is_human": bool(getattr(player, "is_human", False)) if player is not None else None,
        "way_id": _way_id(player),
        "way_ids": way_ids,
        "sticky_eta": _sticky_eta(player),
        "la_holder_id": _pid(getattr(game, "largest_army_player", None)) if game else None,
        "lr_holder_id": _pid(getattr(game, "longest_road_player", None)) if game else None,
        "seats": seats,
        "la": la_block,
        "lr": lr_block,
        "s55_latched": bool((s55 or {}).get("latched_s5b"))
        if isinstance(s55, Mapping)
        else None,
    }
    return row


def _sample_latch_key(game: Any, player: Any, event: str) -> str:
    return (
        f"{getattr(game, 'id', '')}|"
        f"{_safe_int(getattr(game, 'round', 0), 0)}|"
        f"{_safe_int(getattr(game, 'turn', 0), 0)}|"
        f"{_pid(player)}|"
        f"{event}"
    )


def maybe_log_la_lr_probe(
    game: Any,
    player: Any = None,
    *,
    reason: str = "",
    event: str = "sample",
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Build + append probe row. Dedupes turn samples per seat unless force/event.

    Returns the row if written, else None.
    """
    if not log_la_lr_probe_enabled(game):
        return None
    if game is None:
        return None
    if str(getattr(game, "phase", "") or "") != "Execution":
        return None
    if player is None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else getattr(game, "current_player", None)
        except Exception:
            player = None
    if player is None:
        return None
    # Skip humans (Phase L lab); still allow if force for tests
    if bool(getattr(player, "is_human", False)) and not force:
        return None

    event_s = str(event or "sample")
    # Dedup routine samples once per (game,round,turn,player,event)
    if not force and event_s in ("sample", "after_strategy_refresh", "own_turn"):
        key = _sample_latch_key(game, player, event_s)
        seen = getattr(game, "_la_lr_probe_latch", None)
        if not isinstance(seen, set):
            seen = set()
            try:
                game._la_lr_probe_latch = seen
            except Exception:
                pass
        if key in seen:
            return None
        try:
            seen.add(key)
        except Exception:
            pass

    try:
        row = build_la_lr_probe_row(
            game, player, reason=reason, event=event_s
        )
    except Exception:
        return None

    path = la_lr_probe_log_path(
        str(getattr(game, "la_lr_probe_log_path", "") or "") or None
    )
    try:
        _append_jsonl(path, row)
    except Exception:
        pass
    try:
        setattr(player, "last_la_lr_probe_row", dict(row))
    except Exception:
        pass
    try:
        setattr(game, "last_la_lr_probe_row", dict(row))
    except Exception:
        pass
    return row


def is_giveup_fire_event(event: Any) -> bool:
    """True if event name is a live L6 give-up fire marker."""
    return str(event or "") in GIVEUP_FIRE_EVENTS


def is_probe_non_sample_event(event: Any) -> bool:
    """True for dig events excluded from offline θ sample series (fires + S7 salvage)."""
    return str(event or "") in PROBE_NON_SAMPLE_EVENTS


def iter_la_lr_probe_rows(
    path: PathLike,
    *,
    include_fire_events: bool = True,
):
    """Yield dict rows from a probe JSONL file.

    Args:
        include_fire_events: When False, skip give-up fire and S7 salvage_adopt
            rows (use for offline L2/L3 sample series).
    """
    p = Path(path)
    if not p.is_file():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not isinstance(o, dict):
                continue
            if not include_fire_events and is_probe_non_sample_event(o.get("event")):
                continue
            yield o


def iter_giveup_fire_rows(path: PathLike):
    """Yield only live L6 give-up fire rows from a probe JSONL."""
    for row in iter_la_lr_probe_rows(path, include_fire_events=True):
        if is_giveup_fire_event(row.get("event")):
            yield row


def iter_salvage_adopt_rows(path: PathLike):
    """Yield S7 salvage_adopt dig rows from a probe JSONL."""
    for row in iter_la_lr_probe_rows(path, include_fire_events=True):
        if str(row.get("event") or "") == EVENT_SALVAGE_ADOPT:
            yield row


def _ensure_giveup_fire_state(game: Any) -> Dict[str, Any]:
    """Return mutable game-level give-up fire counters / event list."""
    state = getattr(game, "giveup_fire_state", None) if game is not None else None
    if isinstance(state, dict) and "la_by_seat" in state and "lr_by_seat" in state:
        return state
    state = {
        "la_total": 0,
        "lr_total": 0,
        "la_by_seat": {},  # str(pid) -> int
        "lr_by_seat": {},
        "events": [],  # compact fire records
    }
    if game is not None:
        try:
            game.giveup_fire_state = state
        except Exception:
            pass
    return state


def note_giveup_fire(
    game: Any,
    player: Any,
    *,
    special: str,
    score: float,
    theta: float,
    way_id: Optional[int] = None,
    profile: Optional[str] = None,
    freeze_id: Optional[str] = None,
    dwell: Optional[int] = None,
    run_len: Optional[int] = None,
    reason: str = "",
    round_n: Optional[int] = None,
    turn_n: Optional[int] = None,
) -> Dict[str, Any]:
    """Increment in-memory fire counters on ``game`` for result.json summary.

    Safe if game is None (returns compact record only).
    """
    special_s = "lr" if str(special or "").lower() == "lr" else "la"
    pid = _pid(player)
    rnd = round_n
    trn = turn_n
    if game is not None:
        if rnd is None:
            rnd = _safe_int(getattr(game, "round", None), 0)
        if trn is None:
            trn = _safe_int(getattr(game, "turn", None), 0)
    record: Dict[str, Any] = {
        "special": special_s,
        "player_id": pid,
        "round": rnd,
        "turn": trn,
        "way_id": way_id if way_id is not None and int(way_id) > 0 else None,
        "score": round(float(score), 4) if score is not None else None,
        "theta": round(float(theta), 4) if theta is not None else None,
        "profile": str(profile) if profile else None,
        "freeze_id": str(freeze_id) if freeze_id else None,
        "dwell": _safe_int(dwell),
        "run_len": _safe_int(run_len),
        "reason": str(reason or "")[:120] or None,
    }
    if game is None:
        return record
    state = _ensure_giveup_fire_state(game)
    seat_key = str(pid) if pid is not None else "?"
    if special_s == "lr":
        state["lr_total"] = int(state.get("lr_total") or 0) + 1
        by = state.setdefault("lr_by_seat", {})
        if not isinstance(by, dict):
            by = {}
            state["lr_by_seat"] = by
        by[seat_key] = int(by.get(seat_key) or 0) + 1
    else:
        state["la_total"] = int(state.get("la_total") or 0) + 1
        by = state.setdefault("la_by_seat", {})
        if not isinstance(by, dict):
            by = {}
            state["la_by_seat"] = by
        by[seat_key] = int(by.get(seat_key) or 0) + 1
    events = state.setdefault("events", [])
    if isinstance(events, list) and len(events) < MAX_GIVEUP_FIRE_EVENTS_ON_GAME:
        events.append(dict(record))
    return record


def collect_giveup_fire_summary(game: Any) -> Dict[str, Any]:
    """Export give-up fire KPIs for ``result.json`` / batch compact rows."""
    empty = {
        "la_giveup_fires_total": 0,
        "lr_giveup_fires_total": 0,
        "la_giveup_fires_by_seat": {},
        "lr_giveup_fires_by_seat": {},
        "giveup_fires": [],
        "giveup_fires_truncated": False,
    }
    if game is None:
        return empty
    state = getattr(game, "giveup_fire_state", None)
    if not isinstance(state, Mapping):
        return empty
    events = list(state.get("events") or []) if isinstance(state.get("events"), list) else []
    la_total = int(state.get("la_total") or 0)
    lr_total = int(state.get("lr_total") or 0)
    truncated = (la_total + lr_total) > len(events)
    la_by = dict(state.get("la_by_seat") or {}) if isinstance(state.get("la_by_seat"), Mapping) else {}
    lr_by = dict(state.get("lr_by_seat") or {}) if isinstance(state.get("lr_by_seat"), Mapping) else {}
    return {
        "la_giveup_fires_total": la_total,
        "lr_giveup_fires_total": lr_total,
        "la_giveup_fires_by_seat": {str(k): int(v) for k, v in la_by.items()},
        "lr_giveup_fires_by_seat": {str(k): int(v) for k, v in lr_by.items()},
        "giveup_fires": events,
        "giveup_fires_truncated": bool(truncated),
    }


def log_giveup_fire_event(
    game: Any,
    player: Any,
    *,
    special: str,
    score: float,
    theta: float,
    way_id: Optional[int] = None,
    profile: Optional[str] = None,
    freeze_id: Optional[str] = None,
    dwell: Optional[int] = None,
    run_len: Optional[int] = None,
    reason: str = "",
    base_row: Optional[Mapping[str, Any]] = None,
    special_block: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Append a live give-up fire row to probe JSONL and note counters on game.

    Prefer ``base_row`` / ``special_block`` captured **before** sticky clear so
    needs/gap/score features match the fire decision.
    """
    special_s = "lr" if str(special or "").lower() == "lr" else "la"
    event = EVENT_LR_GIVEUP_FIRE if special_s == "lr" else EVENT_LA_GIVEUP_FIRE

    # Always update in-memory summary (even if JSONL disabled)
    note_giveup_fire(
        game,
        player,
        special=special_s,
        score=score,
        theta=theta,
        way_id=way_id,
        profile=profile,
        freeze_id=freeze_id,
        dwell=dwell,
        run_len=run_len,
        reason=reason,
    )

    if game is None:
        return None
    if not log_la_lr_probe_enabled(game):
        return None

    # Build row: clone pre-fire snapshot when available
    row: Dict[str, Any]
    if isinstance(base_row, Mapping) and base_row:
        row = dict(base_row)
    else:
        try:
            row = build_la_lr_probe_row(
                game,
                player,
                reason=str(reason or "giveup_fire"),
                event=event,
            )
        except Exception:
            return None

    if isinstance(special_block, Mapping) and special_block:
        key = "lr" if special_s == "lr" else "la"
        row[key] = dict(special_block)

    row["schema"] = PROBE_SCHEMA_VERSION
    row["kind"] = "la_lr_probe"
    row["event"] = event
    row["reason"] = str(reason or "giveup_fire")[:120] or "giveup_fire"
    if way_id is not None and int(way_id) > 0:
        row["way_id"] = int(way_id)
    row["giveup"] = {
        "fired": True,
        "special": special_s,
        "score": round(float(score), 4) if score is not None else None,
        "theta": round(float(theta), 4) if theta is not None else None,
        "profile": str(profile) if profile else None,
        "freeze_id": str(freeze_id) if freeze_id else None,
        "dwell": _safe_int(dwell),
        "run_len": _safe_int(run_len),
        "way_id": int(way_id) if way_id is not None and int(way_id) > 0 else None,
        "source": f"{special_s}_giveup_l2",
    }
    try:
        row["ts"] = datetime.now().isoformat(timespec="seconds")
    except Exception:
        pass

    path = la_lr_probe_log_path(
        str(getattr(game, "la_lr_probe_log_path", "") or "") or None
    )
    try:
        _append_jsonl(path, row)
    except Exception:
        pass
    try:
        setattr(player, "last_giveup_fire_row", dict(row))
    except Exception:
        pass
    try:
        setattr(game, "last_giveup_fire_row", dict(row))
    except Exception:
        pass
    return row


def clear_way_specials_cache() -> None:
    """Test helper: drop cached Victory-Way LA/LR flags."""
    global _way_specials_cache
    _way_specials_cache = None


__all__ = [
    "PROBE_SCHEMA_VERSION",
    "MAX_ROADS_CAP",
    "EVENT_LA_GIVEUP_FIRE",
    "EVENT_LR_GIVEUP_FIRE",
    "EVENT_SALVAGE_ADOPT",
    "GIVEUP_FIRE_EVENTS",
    "PROBE_NON_SAMPLE_EVENTS",
    "get_la_lr_probe_log_path_override",
    "set_la_lr_probe_log_path",
    "default_la_lr_probe_log_path",
    "la_lr_probe_log_path",
    "log_la_lr_probe_enabled",
    "append_la_lr_probe_row",
    "resolve_needs_la",
    "resolve_needs_lr",
    "build_la_lr_probe_row",
    "maybe_log_la_lr_probe",
    "iter_la_lr_probe_rows",
    "iter_giveup_fire_rows",
    "iter_salvage_adopt_rows",
    "is_giveup_fire_event",
    "is_probe_non_sample_event",
    "note_giveup_fire",
    "collect_giveup_fire_summary",
    "log_giveup_fire_event",
    "clear_way_specials_cache",
]
