"""MGlog: re-playable CSV event timeline (MGLOG_SPEC_v0).

**M1:** CSV header, append, event_index, process-wide path override.
**M2:** Snapshot helpers from Game → hands / VP / robber / board_blob / row fields.
**M3:** Safe hooks for game_start/board_init, IP, turn_start/end, dice, production.
**M4:** Safe hooks for builds, robber move, steal, discard_7.
**M5:** Safe hooks for TwB, TwP execute, DCard buy/play (exact type), activate.
**M6:** Safe hooks for longest_road_change, largest_army_change, game_over.
Does **not** implement re-play GUI or MGlog-only stats aggregation (later M-stats).

When ``MGLOG=True`` (core.constants), callers append ordered rows so a future
GUI-only re-play can rebuild from playboard + mglog.csv (from IP start).

See ``docs/MGlog_implementation_plan.md``.
"""

from __future__ import annotations

import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Union

PathLike = Union[str, Path]

SPEC_FREEZE_ID = "MGLOG_SPEC_v0"
SCHEMA_VERSION = 1

# Resource order: Wheat, Ore, Wood, Brick, Sheep (Gen3)
RESOURCE_KEYS = ("Wh", "O", "Wd", "B", "Sh")
NUM_RESOURCES = 5
MAX_PLAYERS_DEFAULT = 4

# Process-wide path override (batch: g00N/mglog.csv)
_mglog_path_override: Optional[str] = None

# Per-path state: event_index, header_written
_lock = threading.RLock()
_event_index_by_path: Dict[str, int] = {}
_header_written: set = set()


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


# ---------------------------------------------------------------------------
# Path override
# ---------------------------------------------------------------------------


def get_mglog_path_override() -> Optional[str]:
    return _mglog_path_override


def set_mglog_path(path: Optional[str]) -> Optional[str]:
    """Set process-wide MGlog CSV path (batch per-game). Returns previous override."""
    global _mglog_path_override
    prev = _mglog_path_override
    if path is None or str(path).strip() == "":
        _mglog_path_override = None
    else:
        _mglog_path_override = str(path)
    return prev


def batch_game_mglog_path(game_dir: PathLike) -> str:
    """Canonical per-game path: ``batch_dir/g00N/mglog.csv``."""
    return str(Path(game_dir) / "mglog.csv")


def begin_game_mglog(
    path: Optional[PathLike],
    *,
    max_players: int = MAX_PLAYERS_DEFAULT,
) -> Optional[str]:
    """Point override at a per-game CSV, start a fresh file, mark session open.

    Returns the **previous** path override (restore with ``set_mglog_path``).
    When ``MGLOG`` is False or ``path`` is empty, does not create a file and
    returns the previous override unchanged (or after a no-op set).
    """
    if not path or str(path).strip() == "":
        return get_mglog_path_override()
    resolved = str(path)
    prev = set_mglog_path(resolved)
    if not mglog_enabled():
        return prev
    with _lock:
        _session_started_paths.discard(resolved)
    try:
        init_mglog_file(resolved, max_players=max_players)
        with _lock:
            _session_started_paths.add(resolved)
    except Exception:
        pass
    return prev


def end_game_mglog(previous_override: Optional[str] = None) -> None:
    """Restore process-wide path after a batch/headless game finishes."""
    set_mglog_path(previous_override)


def resolve_mglog_path(filename: Optional[str] = None) -> str:
    """Absolute path for the active MGlog file (honours batch override)."""
    p = mglog_path(filename)
    try:
        return str(Path(p).resolve())
    except Exception:
        return str(p)


def default_mglog_path() -> str:
    try:
        from core.constants import FILENAME_MGLOG

        return str(FILENAME_MGLOG)
    except Exception:
        try:
            from core.constants import FILENAME_HELP

            return f"{FILENAME_HELP}_MGlog.csv"
        except Exception:
            return "Catan_MGlog.csv"


def mglog_path(filename: Optional[str] = None) -> str:
    if _mglog_path_override:
        return str(_mglog_path_override)
    if filename:
        return str(filename)
    return default_mglog_path()


def mglog_enabled() -> bool:
    try:
        from core import constants as C

        return bool(getattr(C, "MGLOG", True))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Column schema (wide CSV)
# ---------------------------------------------------------------------------


def mglog_fieldnames(max_players: int = MAX_PLAYERS_DEFAULT) -> List[str]:
    """Stable CSV header columns (v0)."""
    n = max(1, int(max_players))
    cols: List[str] = [
        "schema",
        "spec_freeze_id",
        "event_index",
        "ts",
        "game_id",
        "sequence_number",
        "batch_id",
        "round",
        "turn",
        "phase",
        "state",
        "event",
        "player_id",
        "opponent_id",
        "dice",
        "tw1",
        "tw2",
        "dcard_type",
        "payload",
        "robber_tile",
        "lr_holder",
        "la_holder",
        "board_blob",
    ]
    for i in range(NUM_RESOURCES):
        cols.append(f"rc_in_{i}")
    for i in range(NUM_RESOURCES):
        cols.append(f"rc_out_{i}")
    for p in range(1, n + 1):
        for i in range(NUM_RESOURCES):
            cols.append(f"hand_p{p}_{i}")
    for p in range(1, n + 1):
        cols.append(f"vp_{p}")
    return cols


# ---------------------------------------------------------------------------
# Event index
# ---------------------------------------------------------------------------


def get_event_index(path: Optional[str] = None) -> int:
    """Next event_index that will be written for this path (0-based before first append)."""
    p = str(path or mglog_path())
    with _lock:
        return int(_event_index_by_path.get(p, 0))


def reset_event_index(path: Optional[str] = None) -> None:
    """Reset event_index and header state for a path (start of a new game file)."""
    p = str(path or mglog_path())
    with _lock:
        _event_index_by_path[p] = 0
        _header_written.discard(p)


def _next_event_index(path: str) -> int:
    with _lock:
        cur = int(_event_index_by_path.get(path, 0))
        _event_index_by_path[path] = cur + 1
        return cur


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------


def ensure_header(
    path: Optional[str] = None,
    *,
    max_players: int = MAX_PLAYERS_DEFAULT,
    force: bool = False,
) -> str:
    """Write CSV header if not yet written for this path. Returns resolved path.

    ``force=True`` truncates and rewrites header (new game file).
    """
    resolved = str(path or mglog_path())
    with _lock:
        p = Path(resolved)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        need_write = force or resolved not in _header_written
        if need_write:
            empty_or_missing = (not p.is_file()) or p.stat().st_size == 0
            if force or empty_or_missing:
                with p.open("w", encoding="utf-8", newline="") as f:
                    f.write(f"# mglog schema={SCHEMA_VERSION} freeze={SPEC_FREEZE_ID}\n")
                    w = csv.DictWriter(
                        f,
                        fieldnames=mglog_fieldnames(max_players),
                        extrasaction="ignore",
                        lineterminator="\n",
                    )
                    w.writeheader()
            _header_written.add(resolved)
        return resolved


def init_mglog_file(
    path: Optional[str] = None,
    *,
    max_players: int = MAX_PLAYERS_DEFAULT,
) -> str:
    """Start a fresh MGlog file (header + event_index=0). Use at game start."""
    resolved = str(path or mglog_path())
    reset_event_index(resolved)
    return ensure_header(resolved, max_players=max_players, force=True)


def _blank_row(max_players: int = MAX_PLAYERS_DEFAULT) -> Dict[str, str]:
    return {k: "" for k in mglog_fieldnames(max_players)}


def _vec5(values: Any) -> List[str]:
    out: List[str] = []
    raw = list(values) if isinstance(values, (list, tuple)) else []
    for i in range(NUM_RESOURCES):
        try:
            v = raw[i] if i < len(raw) else ""
            if v is None or v == "":
                out.append("")
            else:
                out.append(str(int(float(v))))
        except Exception:
            out.append(str(v) if v is not None else "")
    return out


def build_row(
    event: str,
    *,
    event_index: Optional[int] = None,
    game_id: Any = "",
    sequence_number: Any = "",
    batch_id: Any = "",
    round: Any = "",  # noqa: A002 — column name matches plan
    turn: Any = "",
    phase: Any = "",
    state: Any = "",
    player_id: Any = "",
    opponent_id: Any = "",
    dice: Any = "",
    tw1: Any = "",
    tw2: Any = "",
    dcard_type: Any = "",
    payload: Any = "",
    robber_tile: Any = "",
    lr_holder: Any = "",
    la_holder: Any = "",
    board_blob: Any = "",
    rc_in: Optional[Sequence[Any]] = None,
    rc_out: Optional[Sequence[Any]] = None,
    hands: Optional[Sequence[Sequence[Any]]] = None,
    vps: Optional[Sequence[Any]] = None,
    max_players: int = MAX_PLAYERS_DEFAULT,
    ts: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """Build a CSV row dict (all values strings). Does not write."""
    n = max(1, int(max_players))
    row = _blank_row(n)
    row["schema"] = str(SCHEMA_VERSION)
    row["spec_freeze_id"] = SPEC_FREEZE_ID
    if event_index is not None:
        row["event_index"] = str(int(event_index))
    row["ts"] = ts or datetime.now().isoformat(timespec="seconds")
    row["game_id"] = _safe_str(game_id)
    row["sequence_number"] = "" if sequence_number in (None, "") else str(sequence_number)
    row["batch_id"] = _safe_str(batch_id)
    row["round"] = "" if round in (None, "") else str(round)
    row["turn"] = "" if turn in (None, "") else str(turn)
    row["phase"] = _safe_str(phase)
    row["state"] = _safe_str(state)
    row["event"] = _safe_str(event)
    row["player_id"] = "" if player_id in (None, "") else str(player_id)
    row["opponent_id"] = "" if opponent_id in (None, "") else str(opponent_id)
    row["dice"] = _safe_str(dice)
    row["tw1"] = "" if tw1 in (None, "") else str(tw1)
    row["tw2"] = "" if tw2 in (None, "") else str(tw2)
    row["dcard_type"] = _safe_str(dcard_type)
    row["payload"] = _safe_str(payload)
    row["robber_tile"] = "" if robber_tile in (None, "") else str(robber_tile)
    row["lr_holder"] = "" if lr_holder in (None, "") else str(lr_holder)
    row["la_holder"] = "" if la_holder in (None, "") else str(la_holder)
    row["board_blob"] = _safe_str(board_blob)

    vin = _vec5(rc_in)
    vout = _vec5(rc_out)
    for i in range(NUM_RESOURCES):
        row[f"rc_in_{i}"] = vin[i]
        row[f"rc_out_{i}"] = vout[i]

    hands_list = list(hands) if hands is not None else []
    for p in range(1, n + 1):
        h = hands_list[p - 1] if p - 1 < len(hands_list) else None
        hv = _vec5(h)
        for i in range(NUM_RESOURCES):
            row[f"hand_p{p}_{i}"] = hv[i]

    vps_list = list(vps) if vps is not None else []
    for p in range(1, n + 1):
        if p - 1 < len(vps_list) and vps_list[p - 1] not in (None, ""):
            try:
                row[f"vp_{p}"] = str(int(float(vps_list[p - 1])))
            except Exception:
                row[f"vp_{p}"] = str(vps_list[p - 1])
        else:
            row[f"vp_{p}"] = ""

    if extra:
        for k, v in extra.items():
            if k in row and v is not None:
                row[k] = str(v)
    return row


def append_event(
    event: str,
    *,
    path: Optional[str] = None,
    max_players: int = MAX_PLAYERS_DEFAULT,
    force: bool = False,
    **fields: Any,
) -> Optional[Dict[str, str]]:
    """Append one event row if MGLOG enabled (or force=True).

    Allocates the next ``event_index`` for the path. Returns the row written,
    or None if disabled / write failed.
    """
    if not force and not mglog_enabled():
        return None

    resolved = str(path or mglog_path())
    try:
        ensure_header(resolved, max_players=max_players, force=False)
    except Exception:
        return None

    idx = _next_event_index(resolved)
    row = build_row(event, event_index=idx, max_players=max_players, **fields)

    try:
        p = Path(resolved)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=mglog_fieldnames(max_players),
                extrasaction="ignore",
                lineterminator="\n",
            )
            w.writerow(row)
    except Exception:
        # Roll back index on failure so numbers stay contiguous for successful writes
        with _lock:
            cur = int(_event_index_by_path.get(resolved, 1))
            _event_index_by_path[resolved] = max(0, cur - 1)
        return None
    return row


def append_row_dict(
    row: Mapping[str, Any],
    *,
    path: Optional[str] = None,
    max_players: int = MAX_PLAYERS_DEFAULT,
    force: bool = False,
    assign_event_index: bool = True,
) -> Optional[Dict[str, str]]:
    """Append a pre-built mapping (keys subset of fieldnames)."""
    if not force and not mglog_enabled():
        return None
    resolved = str(path or mglog_path())
    try:
        ensure_header(resolved, max_players=max_players, force=False)
    except Exception:
        return None

    out = _blank_row(max_players)
    for k, v in row.items():
        if k in out and v is not None:
            out[k] = str(v)
    out["schema"] = str(SCHEMA_VERSION)
    out["spec_freeze_id"] = SPEC_FREEZE_ID
    if assign_event_index or not out.get("event_index"):
        out["event_index"] = str(_next_event_index(resolved))
    if not out.get("ts"):
        out["ts"] = datetime.now().isoformat(timespec="seconds")

    try:
        p = Path(resolved)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=mglog_fieldnames(max_players),
                extrasaction="ignore",
                lineterminator="\n",
            )
            w.writerow(out)
    except Exception:
        with _lock:
            cur = int(_event_index_by_path.get(resolved, 1))
            _event_index_by_path[resolved] = max(0, cur - 1)
        return None
    return out


# ---------------------------------------------------------------------------
# M2: snapshots from Game / Board / Player
# ---------------------------------------------------------------------------


def player_hand_vector(player: Any) -> List[int]:
    """Return [Wh, O, Wd, B, Sh] counts for a player (zeros if missing)."""
    try:
        from core.constants import ResourceCard

        rcards = getattr(player, "rcards", None) or {}
        return [
            int(rcards.get(ResourceCard.WHEAT, 0) or 0),
            int(rcards.get(ResourceCard.ORE, 0) or 0),
            int(rcards.get(ResourceCard.WOOD, 0) or 0),
            int(rcards.get(ResourceCard.BRICK, 0) or 0),
            int(rcards.get(ResourceCard.SHEEP, 0) or 0),
        ]
    except Exception:
        pass
    # Fallback: already a 5-vector or rcards_in_hand()
    try:
        fn = getattr(player, "rcards_in_hand", None)
        if callable(fn):
            rc5, _, _ = fn()
            return [int(x or 0) for x in list(rc5)[:5]] + [0] * max(0, 5 - len(list(rc5)[:5]))
    except Exception:
        pass
    return [0, 0, 0, 0, 0]


def _players_sorted(game: Any) -> List[Any]:
    players = list(getattr(game, "players", None) or [])
    try:
        players.sort(key=lambda p: int(getattr(p, "id", 0) or 0))
    except Exception:
        pass
    return players


def collect_hands(game: Any, *, max_players: int = MAX_PLAYERS_DEFAULT) -> List[List[int]]:
    """Hands for seats 1..max_players (by player.id; missing seats are zeros)."""
    n = max(1, int(max_players))
    by_id: Dict[int, List[int]] = {}
    for p in _players_sorted(game):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None:
            continue
        by_id[int(pid)] = player_hand_vector(p)
    return [by_id.get(i, [0, 0, 0, 0, 0]) for i in range(1, n + 1)]


def collect_vps(game: Any, *, max_players: int = MAX_PLAYERS_DEFAULT) -> List[int]:
    """Effective VP for seats 1..max_players."""
    n = max(1, int(max_players))
    by_id: Dict[int, int] = {}
    for p in _players_sorted(game):
        pid = _safe_int(getattr(p, "id", None), None)
        if pid is None:
            continue
        try:
            if hasattr(p, "recalculate_victory_points"):
                # Avoid mutating mid-log unless cheap; prefer cached points
                pass
        except Exception:
            pass
        vp = getattr(p, "points", None)
        if vp is None:
            vp = getattr(p, "victory_points", 0)
        try:
            by_id[int(pid)] = int(float(vp or 0))
        except Exception:
            by_id[int(pid)] = 0
    return [by_id.get(i, 0) for i in range(1, n + 1)]


def robber_tile_id(game: Any) -> Optional[int]:
    """Current robber land tile id, if known."""
    try:
        from core.game_7logic import current_robber_tile_id

        tid = current_robber_tile_id(game)
        if tid is not None:
            return int(tid)
    except Exception:
        pass
    board = getattr(game, "board", None)
    if board is not None:
        for tile in getattr(board, "tiles", None) or []:
            if tile is None:
                continue
            if getattr(tile, "occupied_tf", False):
                return _safe_int(getattr(tile, "id", None), None)
    prev = getattr(game, "previous_tile_having_robber", None)
    if isinstance(prev, (list, tuple)) and prev:
        return _safe_int(prev[0], None)
    return _safe_int(prev, None)


def lr_la_holder_ids(game: Any) -> tuple:
    """Return (lr_holder_id or None, la_holder_id or None)."""
    lr_p = getattr(game, "longest_road_player", None)
    la_p = getattr(game, "largest_army_player", None)
    lr_id = _safe_int(getattr(lr_p, "id", None), None) if lr_p is not None else None
    la_id = _safe_int(getattr(la_p, "id", None), None) if la_p is not None else None
    if lr_id is None:
        for p in _players_sorted(game):
            if getattr(p, "longest_route_tf", False) or getattr(p, "longest_roadYN", None) == "Y":
                lr_id = _safe_int(getattr(p, "id", None), None)
                break
    if la_id is None:
        for p in _players_sorted(game):
            if getattr(p, "largest_army_tf", False) or getattr(p, "largest_armyYN", None) == "Y":
                la_id = _safe_int(getattr(p, "id", None), None)
                break
    return lr_id, la_id


def _color_to_player_id(game: Any) -> Dict[str, int]:
    m: Dict[str, int] = {}
    for p in _players_sorted(game):
        c = str(getattr(p, "color", "") or "").strip()
        pid = _safe_int(getattr(p, "id", None), None)
        if c and pid is not None:
            m[c] = int(pid)
            m[c.lower()] = int(pid)
    return m


def encode_board_blob(
    game: Any,
    *,
    include_tiles: bool = False,
) -> str:
    """Compact parseable board encoding for CSV ``board_blob`` (no JSON file).

    Format (semicolon sections):
      tiles=id:type:value,...   (optional keyframe)
      ports=inter:port_type,...
      S=player:inter,...        settlements
      C=player:inter,...        cities
      R=player:a-b,...          roads (edge endpoints sorted)
      rob=tile_id
    """
    board = getattr(game, "board", None)
    if board is None:
        return ""
    color_map = _color_to_player_id(game)
    parts: List[str] = []

    if include_tiles:
        tile_bits: List[str] = []
        for tile in getattr(board, "tiles", None) or []:
            if tile is None:
                continue
            tid = _safe_int(getattr(tile, "id", None), None)
            if tid is None:
                continue
            ttype = str(getattr(tile, "type", "") or "Blank")
            if ttype == "Sea":
                continue
            val = _safe_int(getattr(tile, "value", 0), 0) or 0
            tile_bits.append(f"{tid}:{ttype}:{val}")
        if tile_bits:
            parts.append("tiles=" + ",".join(tile_bits))
        port_bits: List[str] = []
        for inter in getattr(board, "intersections", None) or []:
            if inter is None or not getattr(inter, "port_tf", False):
                continue
            iid = _safe_int(getattr(inter, "id", None), None)
            if iid is None:
                continue
            pt = str(getattr(inter, "port_type", "Blank") or "Blank")
            port_bits.append(f"{iid}:{pt}")
        if port_bits:
            parts.append("ports=" + ",".join(port_bits))

    settles: List[str] = []
    cities: List[str] = []
    for inter in getattr(board, "intersections", None) or []:
        if inter is None or not getattr(inter, "occupied_tf", False):
            continue
        iid = _safe_int(getattr(inter, "id", None), None)
        if iid is None:
            continue
        color = str(getattr(inter, "color", "") or "")
        pid = color_map.get(color) or color_map.get(color.lower())
        if pid is None:
            continue
        face = str(getattr(inter, "face", "Settlement") or "Settlement").lower()
        if "city" in face:
            cities.append(f"{pid}:{iid}")
        else:
            settles.append(f"{pid}:{iid}")
    if settles:
        parts.append("S=" + ",".join(settles))
    if cities:
        parts.append("C=" + ",".join(cities))

    roads: List[str] = []
    for road in getattr(board, "roads", None) or []:
        if road is None or not getattr(road, "occupied_tf", False):
            continue
        rid = getattr(road, "id", None)
        if isinstance(rid, (list, tuple)) and len(rid) >= 2:
            a, b = int(rid[0]), int(rid[1])
            if a > b:
                a, b = b, a
        else:
            continue
        color = str(getattr(road, "color", "") or "")
        pid = color_map.get(color) or color_map.get(color.lower())
        if pid is None:
            continue
        roads.append(f"{pid}:{a}-{b}")
    if roads:
        parts.append("R=" + ",".join(roads))

    rob = robber_tile_id(game)
    if rob is not None:
        parts.append(f"rob={rob}")

    return ";".join(parts)


def parse_board_blob(blob: str) -> Dict[str, Any]:
    """Parse ``encode_board_blob`` output (best-effort; for tests / re-play later)."""
    out: Dict[str, Any] = {
        "tiles": [],
        "ports": [],
        "settlements": [],
        "cities": [],
        "roads": [],
        "robber": None,
    }
    text = str(blob or "").strip()
    if not text:
        return out
    for section in text.split(";"):
        section = section.strip()
        if not section or "=" not in section:
            continue
        key, _, body = section.partition("=")
        key = key.strip()
        body = body.strip()
        if not body:
            continue
        if key == "rob":
            out["robber"] = _safe_int(body, None)
            continue
        items = [x.strip() for x in body.split(",") if x.strip()]
        if key == "tiles":
            for it in items:
                bits = it.split(":")
                if len(bits) >= 3:
                    out["tiles"].append(
                        {
                            "id": _safe_int(bits[0]),
                            "type": bits[1],
                            "value": _safe_int(bits[2], 0),
                        }
                    )
        elif key == "ports":
            for it in items:
                bits = it.split(":")
                if len(bits) >= 2:
                    out["ports"].append(
                        {"intersection_id": _safe_int(bits[0]), "port_type": bits[1]}
                    )
        elif key == "S":
            for it in items:
                bits = it.split(":")
                if len(bits) >= 2:
                    out["settlements"].append(
                        {"player_id": _safe_int(bits[0]), "intersection_id": _safe_int(bits[1])}
                    )
        elif key == "C":
            for it in items:
                bits = it.split(":")
                if len(bits) >= 2:
                    out["cities"].append(
                        {"player_id": _safe_int(bits[0]), "intersection_id": _safe_int(bits[1])}
                    )
        elif key == "R":
            for it in items:
                # pid:a-b
                if ":" not in it or "-" not in it:
                    continue
                pid_s, _, edge = it.partition(":")
                a_s, _, b_s = edge.partition("-")
                out["roads"].append(
                    {
                        "player_id": _safe_int(pid_s),
                        "a": _safe_int(a_s),
                        "b": _safe_int(b_s),
                    }
                )
    return out


def snapshot_from_game(
    game: Any,
    *,
    keyframe: bool = False,
    include_tiles: bool = False,
    max_players: int = MAX_PLAYERS_DEFAULT,
) -> Dict[str, Any]:
    """Collect MGlog field values from a live Game (no I/O).

    Returns kwargs suitable for ``build_row`` / ``append_event``:
    round, turn, phase, state, game_id, sequence_number, hands, vps,
    robber_tile, lr_holder, la_holder, board_blob (if keyframe), dice.
    """
    n = max(1, int(max_players))
    if hasattr(game, "players") and game.players:
        try:
            n = max(n, len(list(game.players)))
        except Exception:
            pass

    lr_id, la_id = lr_la_holder_ids(game)
    rob = robber_tile_id(game)

    dice_s = ""
    dr = getattr(game, "dice_roll", None)
    if isinstance(dr, (list, tuple)) and len(dr) >= 2:
        try:
            dice_s = f"{int(dr[0])}+{int(dr[1])}"
        except Exception:
            dice_s = str(dr)
    elif dr not in (None, ""):
        dice_s = str(dr)
    elif getattr(game, "dice_rolls", None):
        try:
            last = game.dice_rolls[-1]
            if isinstance(last, (list, tuple)) and len(last) >= 2:
                dice_s = f"{int(last[0])}+{int(last[1])}"
            else:
                dice_s = str(last)
        except Exception:
            pass

    fields: Dict[str, Any] = {
        "game_id": getattr(game, "id", "") or getattr(game, "game_id", "") or "",
        "sequence_number": getattr(game, "sequence_number", ""),
        "batch_id": getattr(game, "batch_id", "") or "",
        "round": getattr(game, "round", ""),
        "turn": getattr(game, "turn", ""),
        "phase": getattr(game, "phase", ""),
        "state": getattr(game, "state", ""),
        "hands": collect_hands(game, max_players=n),
        "vps": collect_vps(game, max_players=n),
        "robber_tile": rob if rob is not None else "",
        "lr_holder": lr_id if lr_id is not None else "",
        "la_holder": la_id if la_id is not None else "",
        "dice": dice_s,
        "max_players": n,
    }
    if keyframe:
        fields["board_blob"] = encode_board_blob(
            game, include_tiles=bool(include_tiles)
        )
    else:
        fields["board_blob"] = ""
    return fields


def append_event_from_game(
    event: str,
    game: Any,
    *,
    path: Optional[str] = None,
    keyframe: bool = False,
    include_tiles: bool = False,
    force: bool = False,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Snapshot game state into an MGlog event row (M2 helper for M3 hooks).

    ``overrides`` win over snapshot (e.g. player_id, rc_in, dcard_type, payload).
    """
    snap = snapshot_from_game(
        game,
        keyframe=keyframe,
        include_tiles=include_tiles,
    )
    max_players = int(overrides.pop("max_players", None) or snap.pop("max_players", MAX_PLAYERS_DEFAULT))
    fields: Dict[str, Any] = dict(snap)
    fields.update(overrides)
    # Don't pass max_players twice
    fields.pop("max_players", None)
    return append_event(
        event,
        path=path,
        max_players=max_players,
        force=force,
        **fields,
    )


# ---------------------------------------------------------------------------
# M3: safe hooks (never raise into Game)
# ---------------------------------------------------------------------------

_session_started_paths: set = set()


def _safe_hook(fn: Any, *args: Any, **kwargs: Any) -> Optional[Dict[str, str]]:
    if not mglog_enabled():
        return None
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def ensure_game_session(game: Any, *, path: Optional[str] = None) -> Optional[str]:
    """Init CSV for this game file once. Returns path or None if disabled."""
    if not mglog_enabled():
        return None
    try:
        resolved = str(path or mglog_path())
        with _lock:
            if resolved in _session_started_paths and Path(resolved).is_file():
                return resolved
        n = MAX_PLAYERS_DEFAULT
        try:
            n = max(1, len(list(getattr(game, "players", []) or [])) or MAX_PLAYERS_DEFAULT)
        except Exception:
            pass
        init_mglog_file(resolved, max_players=n)
        with _lock:
            _session_started_paths.add(resolved)
        return resolved
    except Exception:
        return None


def log_game_start(game: Any, **overrides: Any) -> Optional[Dict[str, str]]:
    """game_start + board_init keyframe (tiles). Call when IP or game begins."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        seed = getattr(game, "seed", None)
        pb = ""
        try:
            from core import constants as C

            pb = str(getattr(C, "SAVED_PLAYBOARD", "") or "")
        except Exception:
            pass
        append_event_from_game(
            "game_start",
            game,
            keyframe=False,
            payload=f"seed={seed};playboard={pb}",
            **overrides,
        )
        return append_event_from_game(
            "board_init",
            game,
            keyframe=True,
            include_tiles=True,
            **{k: v for k, v in overrides.items() if k not in ("payload",)},
        )

    return _safe_hook(_do)


def log_ip_place_settlement(
    game: Any, player: Any, intersection_id: Any, **overrides: Any
) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        pid = getattr(player, "id", "")
        return append_event_from_game(
            "ip_place_settlement",
            game,
            player_id=pid,
            tw1=intersection_id,
            **overrides,
        )

    return _safe_hook(_do)


def log_ip_place_road(
    game: Any, player: Any, road: Any, **overrides: Any
) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        a = b = ""
        try:
            if isinstance(road, (list, tuple)) and len(road) >= 2:
                a, b = int(road[0]), int(road[1])
                if a > b:
                    a, b = b, a
        except Exception:
            a, b = str(road), ""
        return append_event_from_game(
            "ip_place_road",
            game,
            player_id=getattr(player, "id", ""),
            tw1=a,
            tw2=b,
            **overrides,
        )

    return _safe_hook(_do)


def log_ip_resources(
    game: Any, player: Any, resource_counts: Sequence[Any], **overrides: Any
) -> Optional[Dict[str, str]]:
    """Starting resources from second IP settlement (rc_in 5-vector)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        raw = list(resource_counts or [])
        # counts may be 5 or 6 (gold)
        rc_in = [int(raw[i] or 0) if i < len(raw) else 0 for i in range(5)]
        return append_event_from_game(
            "resource_production",
            game,
            player_id=getattr(player, "id", ""),
            rc_in=rc_in,
            payload="ip_start",
            **overrides,
        )

    return _safe_hook(_do)


def log_ip_complete(game: Any, **overrides: Any) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        return append_event_from_game(
            "ip_complete",
            game,
            keyframe=True,
            include_tiles=False,
            **overrides,
        )

    return _safe_hook(_do)


def log_turn_start(game: Any, **overrides: Any) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        player = None
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)
        pid = getattr(player, "id", "") if player is not None else overrides.get("player_id", "")
        return append_event_from_game(
            "turn_start",
            game,
            keyframe=True,
            include_tiles=False,
            player_id=pid,
            **{k: v for k, v in overrides.items() if k != "player_id"},
        )

    return _safe_hook(_do)


def log_turn_end(game: Any, **overrides: Any) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        if not mglog_enabled():
            return None
        ensure_game_session(game)
        player = None
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)
        pid = getattr(player, "id", "") if player is not None else ""
        return append_event_from_game(
            "turn_end",
            game,
            keyframe=False,
            player_id=pid,
            **overrides,
        )

    return _safe_hook(_do)


def log_dice_roll(
    game: Any,
    dice: Any,
    total: Any = None,
    *,
    player: Any = None,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        dice_s = ""
        try:
            if isinstance(dice, (list, tuple)) and len(dice) >= 2:
                dice_s = f"{int(dice[0])}+{int(dice[1])}"
                if total is not None:
                    dice_s = f"{dice_s}={int(total)}"
            else:
                dice_s = str(dice)
        except Exception:
            dice_s = str(dice)
        pid = getattr(player, "id", "") if player is not None else ""
        if not pid:
            try:
                cur = game.get_current_player()
                pid = getattr(cur, "id", "") if cur else ""
            except Exception:
                pass
        return append_event_from_game(
            "dice_roll",
            game,
            player_id=pid,
            dice=dice_s,
            **overrides,
        )

    return _safe_hook(_do)


def log_resource_production(
    game: Any,
    production_result: Optional[Mapping[str, Any]] = None,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """One ``resource_production`` row per player with positive production."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        last_row = None
        prod = dict(production_result or {})
        by_p = prod.get("produced_by_player") or {}
        if not by_p:
            # single optional override
            if overrides.get("rc_in") is not None:
                return append_event_from_game(
                    "resource_production",
                    game,
                    **overrides,
                )
            return None
        for pid, vec in sorted(by_p.items(), key=lambda kv: int(kv[0] or 0)):
            try:
                v5 = [int(x or 0) for x in list(vec)[:5]]
            except Exception:
                continue
            if not any(v5):
                continue
            last_row = append_event_from_game(
                "resource_production",
                game,
                player_id=pid,
                rc_in=v5,
                dice=str(prod.get("roll", "")),
                **{k: v for k, v in overrides.items() if k not in ("player_id", "rc_in", "dice")},
            )
        return last_row

    return _safe_hook(_do)


# ---------------------------------------------------------------------------
# M4: builds, robber, steal, discard
# ---------------------------------------------------------------------------

# Standard execution costs [Wh, O, Wd, B, Sh] (Gen3 cost vectors)
_COST_ROAD = [0, 0, 1, 1, 0]
_COST_SETTLEMENT = [1, 0, 1, 1, 1]
_COST_CITY = [2, 3, 0, 0, 0]


def log_build(
    game: Any,
    structure: str,
    player: Any,
    *,
    target_id: Any = None,
    road: Any = None,
    rc_out: Optional[Sequence[Any]] = None,
    free: bool = False,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log build_road / build_settlement / build_city after successful mutation."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        s = str(structure or "").lower().strip()
        if s in ("road", "build_road", "build road"):
            event = "build_road"
            default_cost = _COST_ROAD
        elif s in ("settlement", "build_settlement", "build settlement"):
            event = "build_settlement"
            default_cost = _COST_SETTLEMENT
        elif s in ("city", "build_city", "build city"):
            event = "build_city"
            default_cost = _COST_CITY
        else:
            event = "build_" + s.replace(" ", "_")
            default_cost = [0, 0, 0, 0, 0]

        tw1 = target_id
        tw2 = ""
        if road is not None:
            try:
                if isinstance(road, (list, tuple)) and len(road) >= 2:
                    a, b = int(road[0]), int(road[1])
                    if a > b:
                        a, b = b, a
                    tw1, tw2 = a, b
            except Exception:
                tw1, tw2 = str(road), ""
        elif target_id is not None:
            tw1 = target_id

        cost = list(rc_out) if rc_out is not None else (
            [0, 0, 0, 0, 0] if free else list(default_cost)
        )
        payload = "free" if free else ""
        return append_event_from_game(
            event,
            game,
            player_id=getattr(player, "id", ""),
            tw1=tw1 if tw1 is not None else "",
            tw2=tw2 if tw2 != "" else "",
            rc_out=cost,
            payload=payload or overrides.get("payload", ""),
            **{k: v for k, v in overrides.items() if k not in ("payload", "tw1", "tw2", "rc_out", "player_id")},
        )

    return _safe_hook(_do)


def log_set_robber(
    game: Any,
    player: Any,
    tile_id: Any,
    *,
    from_tile_id: Any = None,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        payload = ""
        if from_tile_id is not None and from_tile_id != "":
            payload = f"from={from_tile_id}"
        return append_event_from_game(
            "set_robber",
            game,
            player_id=getattr(player, "id", ""),
            robber_tile=tile_id,
            payload=payload,
            **{k: v for k, v in overrides.items() if k not in ("payload", "player_id", "robber_tile")},
        )

    return _safe_hook(_do)


def log_steal(
    game: Any,
    thief: Any,
    victim_id: Any,
    resource_name: Any,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log steal with exact resource type (analysis; no fair-play redaction)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        name = str(resource_name or "").strip().lower()
        # Map to rc_in/out indices Wh,O,Wd,B,Sh
        idx_map = {
            "wheat": 0,
            "grain": 0,
            "ore": 1,
            "wood": 2,
            "lumber": 2,
            "brick": 3,
            "sheep": 4,
            "wool": 4,
        }
        rc_in = [0, 0, 0, 0, 0]
        rc_out = [0, 0, 0, 0, 0]
        i = idx_map.get(name)
        if i is not None:
            rc_in[i] = 1
            rc_out[i] = 1  # from victim perspective we only log thief row with rc_in
        # Thief gains; victim loss is implied by opponent_id + resource in payload
        return append_event_from_game(
            "steal",
            game,
            player_id=getattr(thief, "id", ""),
            opponent_id=victim_id,
            rc_in=rc_in,
            rc_out=[0, 0, 0, 0, 0],
            payload=f"resource={name}",
            dcard_type="",  # not a dcard
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "opponent_id", "rc_in", "rc_out", "payload")
            },
        )

    return _safe_hook(_do)


def log_discard_7(
    game: Any,
    player: Any,
    discard_vector: Sequence[Any],
    *,
    source: str = "discard",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        vec = [max(0, int(x or 0)) for x in list(discard_vector or [])[:5]]
        while len(vec) < 5:
            vec.append(0)
        if sum(vec) <= 0:
            return None
        return append_event_from_game(
            "discard_7",
            game,
            player_id=getattr(player, "id", ""),
            rc_out=vec,
            payload=str(source or "discard"),
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "rc_out", "payload")
            },
        )

    return _safe_hook(_do)


# ---------------------------------------------------------------------------
# M5: TwB, TwP, DCard buy/play (exact type), activate
# ---------------------------------------------------------------------------

_COST_DCARD = [1, 1, 0, 0, 1]

# Canonical type names used in dcard_type column and play_* events
_DCARD_CANON = {
    "knight": "knight",
    "knights": "knight",
    "year_of_plenty": "year_of_plenty",
    "yop": "year_of_plenty",
    "yearofplenty": "year_of_plenty",
    "monopoly": "monopoly",
    "two_free_roads": "two_free_roads",
    "road_building": "two_free_roads",
    "tfr": "two_free_roads",
    "twofreeroads": "two_free_roads",
    "victory_point": "victory_point",
    "victorypoint": "victory_point",
    "vp": "victory_point",
    "victory points": "victory_point",
}

_PLAY_EVENT_BY_TYPE = {
    "knight": "play_knight",
    "year_of_plenty": "play_yop",
    "monopoly": "play_monopoly",
    "two_free_roads": "play_tfr",
    "victory_point": "play_vp",
}

_RESOURCE_ABBR = ("Wh", "O", "Wd", "B", "Sh")
_RESOURCE_NAME_TO_IDX = {
    "wheat": 0,
    "grain": 0,
    "wh": 0,
    "ore": 1,
    "o": 1,
    "wood": 2,
    "lumber": 2,
    "wd": 2,
    "brick": 3,
    "b": 3,
    "sheep": 4,
    "wool": 4,
    "sh": 4,
}


def normalize_dcard_type(card_name: Any) -> str:
    """Map deck/stack names to locked MGlog dcard_type strings."""
    raw = str(card_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return "unknown"
    if raw in _DCARD_CANON:
        return _DCARD_CANON[raw]
    compact = raw.replace("_", "")
    if compact in _DCARD_CANON:
        return _DCARD_CANON[compact]
    return raw


def _vec5_int(values: Any) -> List[int]:
    out: List[int] = []
    raw = list(values) if isinstance(values, (list, tuple)) else []
    for i in range(NUM_RESOURCES):
        try:
            out.append(max(0, int(raw[i] or 0)) if i < len(raw) else 0)
        except Exception:
            out.append(0)
    return out


def _format_vec_payload(vec: Sequence[int], *, prefix: str = "") -> str:
    parts: List[str] = []
    for i, n in enumerate(list(vec)[:5]):
        try:
            n_i = int(n or 0)
        except Exception:
            n_i = 0
        if n_i:
            parts.append(f"{n_i}{_RESOURCE_ABBR[i]}")
    body = "".join(parts) if parts else "0"
    return f"{prefix}{body}" if prefix else body


def log_twb(
    game: Any,
    player: Any,
    give: Sequence[Any],
    get: Sequence[Any],
    *,
    source: str = "twb",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log one executed Trade-with-Bank (give/get 5-vectors Wh,O,Wd,B,Sh)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        give_v = _vec5_int(give)
        get_v = _vec5_int(get)
        if not any(give_v) and not any(get_v):
            return None
        payload = (
            f"{_format_vec_payload(give_v, prefix='give=')}"
            f";{_format_vec_payload(get_v, prefix='get=')}"
        )
        if source:
            payload = f"{payload};src={source}"
        return append_event_from_game(
            "twb",
            game,
            player_id=getattr(player, "id", ""),
            rc_out=give_v,
            rc_in=get_v,
            payload=payload,
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "rc_out", "rc_in", "payload")
            },
        )

    return _safe_hook(_do)


def log_twp(
    game: Any,
    proposer: Any,
    counterparty_id: Any,
    proposer_gives: Sequence[Any],
    counterparty_gives: Sequence[Any],
    *,
    source: str = "twp",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log one executed TwP deal (one row; vectors from proposer's view).

    ``rc_out`` = proposer gives, ``rc_in`` = counterparty gives (proposer receives).
    """

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        give_v = _vec5_int(proposer_gives)
        get_v = _vec5_int(counterparty_gives)
        if not any(give_v) and not any(get_v):
            return None
        payload = (
            f"{_format_vec_payload(give_v, prefix='give=')}"
            f";{_format_vec_payload(get_v, prefix='get=')}"
        )
        if source:
            payload = f"{payload};src={source}"
        return append_event_from_game(
            "twp",
            game,
            player_id=getattr(proposer, "id", ""),
            opponent_id=counterparty_id,
            rc_out=give_v,
            rc_in=get_v,
            payload=payload,
            **{
                k: v
                for k, v in overrides.items()
                if k
                not in ("player_id", "opponent_id", "rc_out", "rc_in", "payload")
            },
        )

    return _safe_hook(_do)


def log_buy_dcard(
    game: Any,
    player: Any,
    dcard_type: Any,
    *,
    rc_out: Optional[Sequence[Any]] = None,
    source: str = "buy_dcard",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log buy_dcard with exact dcard_type (analysis; no fair-play redaction)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        ctype = normalize_dcard_type(dcard_type)
        cost = _vec5_int(rc_out) if rc_out is not None else list(_COST_DCARD)
        payload = f"src={source}" if source else ""
        return append_event_from_game(
            "buy_dcard",
            game,
            player_id=getattr(player, "id", ""),
            dcard_type=ctype,
            rc_out=cost,
            payload=payload,
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "dcard_type", "rc_out", "payload")
            },
        )

    return _safe_hook(_do)


def log_play_dcard(
    game: Any,
    player: Any,
    dcard_type: Any,
    *,
    payload: Any = "",
    rc_in: Optional[Sequence[Any]] = None,
    rc_out: Optional[Sequence[Any]] = None,
    resource_index: Any = None,
    resource_indices: Optional[Sequence[Any]] = None,
    resource_name: Any = None,
    total_taken: Any = None,
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log play_knight / play_yop / play_monopoly / play_tfr / play_vp + exact type."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        ctype = normalize_dcard_type(dcard_type)
        event = _PLAY_EVENT_BY_TYPE.get(ctype, f"play_{ctype}")

        rc_in_v = _vec5_int(rc_in) if rc_in is not None else [0, 0, 0, 0, 0]
        rc_out_v = _vec5_int(rc_out) if rc_out is not None else [0, 0, 0, 0, 0]
        bits: List[str] = []
        if payload not in (None, ""):
            bits.append(str(payload))

        # YoP: two resources
        if resource_indices is not None and ctype == "year_of_plenty":
            try:
                idxs = [int(x) for x in list(resource_indices)[:2]]
                while len(idxs) < 2:
                    idxs.append(0)
                for idx in idxs:
                    if 0 <= idx < 5:
                        rc_in_v[idx] = int(rc_in_v[idx] or 0) + 1
                bits.append(
                    "res="
                    + "+".join(
                        _RESOURCE_ABBR[i] if 0 <= i < 5 else str(i) for i in idxs
                    )
                )
            except Exception:
                pass

        # Monopoly: one resource + taken count
        if ctype == "monopoly":
            idx = None
            if resource_index is not None:
                try:
                    idx = int(resource_index)
                except Exception:
                    idx = None
            if idx is None and resource_name not in (None, ""):
                idx = _RESOURCE_NAME_TO_IDX.get(str(resource_name).strip().lower())
            if idx is not None and 0 <= idx < 5:
                taken = 0
                try:
                    taken = int(total_taken or 0)
                except Exception:
                    taken = 0
                if rc_in is None and taken > 0:
                    rc_in_v = [0, 0, 0, 0, 0]
                    rc_in_v[idx] = taken
                bits.append(f"resource={_RESOURCE_ABBR[idx].lower()}")
                if total_taken is not None:
                    bits.append(f"taken={taken}")

        if resource_name not in (None, "") and ctype != "monopoly":
            bits.append(f"resource={str(resource_name).strip().lower()}")

        return append_event_from_game(
            event,
            game,
            player_id=getattr(player, "id", ""),
            dcard_type=ctype,
            rc_in=rc_in_v,
            rc_out=rc_out_v,
            payload=";".join(bits) if bits else "",
            **{
                k: v
                for k, v in overrides.items()
                if k
                not in (
                    "player_id",
                    "dcard_type",
                    "rc_in",
                    "rc_out",
                    "payload",
                )
            },
        )

    return _safe_hook(_do)


def log_activate_dcard(
    game: Any,
    player: Any,
    *,
    moved: Any = 0,
    types: Optional[Sequence[Any]] = None,
    source: str = "maturity",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log activate_dcard when new-this-turn cards become playable (x→y)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        try:
            n_moved = int(moved or 0)
        except Exception:
            n_moved = 0
        if n_moved <= 0 and not types:
            return None
        type_bits = []
        for t in list(types or []):
            nt = normalize_dcard_type(t)
            if nt and nt != "unknown":
                type_bits.append(nt)
        payload = f"moved={n_moved};src={source}"
        if type_bits:
            payload = f"{payload};types={','.join(type_bits)}"
        dcard = type_bits[0] if len(type_bits) == 1 else ""
        return append_event_from_game(
            "activate_dcard",
            game,
            player_id=getattr(player, "id", ""),
            dcard_type=dcard,
            payload=payload,
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "dcard_type", "payload")
            },
        )

    return _safe_hook(_do)


# ---------------------------------------------------------------------------
# M6: LR / LA holder changes, game_over
# ---------------------------------------------------------------------------


def log_longest_road_change(
    game: Any,
    *,
    previous_holder_id: Any = None,
    holder_id: Any = None,
    best_length: Any = None,
    reason: str = "",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log longest_road_change when LR special holder changes (incl. vacant)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        bits: List[str] = []
        if previous_holder_id not in (None, ""):
            bits.append(f"from={previous_holder_id}")
        if holder_id not in (None, ""):
            bits.append(f"to={holder_id}")
        else:
            bits.append("to=")
        if best_length not in (None, ""):
            bits.append(f"best={best_length}")
        if reason:
            bits.append(f"reason={reason}")
        return append_event_from_game(
            "longest_road_change",
            game,
            player_id=holder_id if holder_id not in (None, "") else "",
            opponent_id=previous_holder_id if previous_holder_id not in (None, "") else "",
            payload=";".join(bits),
            keyframe=False,
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "opponent_id", "payload")
            },
        )

    return _safe_hook(_do)


def log_largest_army_change(
    game: Any,
    *,
    previous_holder_id: Any = None,
    holder_id: Any = None,
    best_size: Any = None,
    reason: str = "",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log largest_army_change when LA special holder changes (incl. vacant)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        bits: List[str] = []
        if previous_holder_id not in (None, ""):
            bits.append(f"from={previous_holder_id}")
        if holder_id not in (None, ""):
            bits.append(f"to={holder_id}")
        else:
            bits.append("to=")
        if best_size not in (None, ""):
            bits.append(f"best={best_size}")
        if reason:
            bits.append(f"reason={reason}")
        return append_event_from_game(
            "largest_army_change",
            game,
            player_id=holder_id if holder_id not in (None, "") else "",
            opponent_id=previous_holder_id if previous_holder_id not in (None, "") else "",
            payload=";".join(bits),
            keyframe=False,
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "opponent_id", "payload")
            },
        )

    return _safe_hook(_do)


def log_game_over(
    game: Any,
    winner: Any = None,
    *,
    win_result: Optional[Mapping[str, Any]] = None,
    reason: str = "",
    **overrides: Any,
) -> Optional[Dict[str, str]]:
    """Log game_over with winner + final VP snapshot (keyframe for re-play end)."""

    def _do() -> Optional[Dict[str, str]]:
        ensure_game_session(game)
        wr = dict(win_result or {})
        wid = overrides.get("player_id")
        if wid in (None, ""):
            if winner is not None:
                wid = getattr(winner, "id", None)
            if wid in (None, ""):
                wid = wr.get("winner_id")
            if wid in (None, ""):
                try:
                    w = getattr(game, "winner", None)
                    wid = getattr(w, "id", None) if w is not None else None
                except Exception:
                    wid = None
        final_vp = wr.get("final_vp")
        if final_vp in (None, "") and winner is not None:
            try:
                final_vp = getattr(winner, "victory_points", None) or getattr(
                    winner, "points", None
                )
            except Exception:
                final_vp = None
        threshold = wr.get("threshold", "")
        bits = [f"winner={wid}" if wid not in (None, "") else "winner="]
        if final_vp not in (None, ""):
            bits.append(f"vp={final_vp}")
        if threshold not in (None, ""):
            bits.append(f"threshold={threshold}")
        rsn = reason or wr.get("reason") or ""
        if rsn:
            bits.append(f"reason={rsn}")
        # Compact standings: P1:vp,P2:vp,...
        standings = wr.get("standings")
        if isinstance(standings, (list, tuple)) and standings:
            parts: List[str] = []
            for row in standings:
                if not isinstance(row, Mapping):
                    continue
                try:
                    pid = row.get("player_id") or row.get("id")
                    vp = row.get("total") or row.get("vp") or row.get("TVP")
                    if pid is not None:
                        parts.append(f"P{int(pid)}:{int(vp or 0)}")
                except Exception:
                    continue
            if parts:
                bits.append("standings=" + ",".join(parts))
        return append_event_from_game(
            "game_over",
            game,
            player_id=wid if wid not in (None, "") else "",
            payload=";".join(bits),
            keyframe=True,
            include_tiles=False,
            **{
                k: v
                for k, v in overrides.items()
                if k not in ("player_id", "payload")
            },
        )

    return _safe_hook(_do)


__all__ = [
    "SPEC_FREEZE_ID",
    "SCHEMA_VERSION",
    "RESOURCE_KEYS",
    "MAX_PLAYERS_DEFAULT",
    "get_mglog_path_override",
    "set_mglog_path",
    "batch_game_mglog_path",
    "begin_game_mglog",
    "end_game_mglog",
    "resolve_mglog_path",
    "default_mglog_path",
    "mglog_path",
    "mglog_enabled",
    "mglog_fieldnames",
    "get_event_index",
    "reset_event_index",
    "ensure_header",
    "init_mglog_file",
    "build_row",
    "append_event",
    "append_row_dict",
    "player_hand_vector",
    "collect_hands",
    "collect_vps",
    "robber_tile_id",
    "lr_la_holder_ids",
    "encode_board_blob",
    "parse_board_blob",
    "snapshot_from_game",
    "append_event_from_game",
    "ensure_game_session",
    "log_game_start",
    "log_ip_place_settlement",
    "log_ip_place_road",
    "log_ip_resources",
    "log_ip_complete",
    "log_turn_start",
    "log_turn_end",
    "log_dice_roll",
    "log_resource_production",
    "log_build",
    "log_set_robber",
    "log_steal",
    "log_discard_7",
    "normalize_dcard_type",
    "log_twb",
    "log_twp",
    "log_buy_dcard",
    "log_play_dcard",
    "log_activate_dcard",
    "log_longest_road_change",
    "log_largest_army_change",
    "log_game_over",
]
