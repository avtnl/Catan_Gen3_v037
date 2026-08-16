"""MGlog-only endgame statistics (M-stats).

**S0:** CSV load, thin playboard snapshot, empty S7-shaped snapshot.
**S1:** Dice histogram, rcards_drawn, dcards_drawn, activity DC_In / DC_Played.
**S2:** Resource TRC rows (production, discard, steal, TwB/TwP, builds, buy, YoP; monopoly thief).
**S3:** Structure timeline + Overview (S/C/DC/LA/LR/TVP/winner).
**S5:** Activity TrP=``*``, TrP_A, RC_Use (RC_Block from S4 when available).
**S4:** RC Block derived from robber + dice + structures + playboard.
**S8:** Optional Game Over path prefers MGlog when ``MGLOG_STATS_ON_GAME_OVER``.

Policy: ``docs/MGlog_statistics_plan.md`` / MGlog plan §0.4.
No Strategy-Engine; no live Game required for offline digs.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

PathLike = Union[str, Path]

# Unrecoverable cell (plan §0.4 / M-stats) — never invent 0 for missing fields.
MISSING: str = "*"

# Resource order: Wheat, Ore, Wood, Brick, Sheep (aligned with MGlog / S7)
RCARD_KEYS: tuple = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RCARD_SHORT: tuple = ("Wh", "O", "Wd", "B", "Sh")
NUM_RESOURCES: int = 5

DCARD_KEYS: tuple = (
    "victory_point",
    "knight",
    "two_free_roads",
    "year_of_plenty",
    "monopoly",
)

SPEC_ID = "MGLOG_STATS_v0"


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _resolve_path(path: Optional[PathLike]) -> Optional[Path]:
    if path is None or str(path).strip() == "":
        return None
    p = Path(path)
    try:
        return p.resolve()
    except Exception:
        return p


# ---------------------------------------------------------------------------
# CSV load
# ---------------------------------------------------------------------------


def load_mglog_rows(path: PathLike) -> List[Dict[str, str]]:
    """Load MGlog CSV rows (skip ``#`` comment lines). Values are strings.

    Raises:
        FileNotFoundError: path missing
        ValueError: empty / unreadable as CSV with header
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"mglog not found: {p}")
    with p.open(encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    if not lines:
        raise ValueError(f"mglog empty or comments only: {p}")
    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        raise ValueError(f"mglog missing header: {p}")
    rows: List[Dict[str, str]] = []
    for raw in reader:
        if not raw:
            continue
        # Normalize None → ""
        row = {str(k): ("" if v is None else str(v)) for k, v in raw.items() if k is not None}
        if not any(row.values()):
            continue
        rows.append(row)
    return rows


def mglog_event_names(rows: Sequence[Mapping[str, str]]) -> List[str]:
    return [str(r.get("event") or "") for r in rows if r.get("event")]


def mglog_event_indices(rows: Sequence[Mapping[str, str]]) -> List[int]:
    out: List[int] = []
    for r in rows:
        idx = _safe_int(r.get("event_index"), None)
        if idx is not None:
            out.append(int(idx))
    return out


# ---------------------------------------------------------------------------
# Thin playboard snapshot (geometry for later RC Block)
# ---------------------------------------------------------------------------


@dataclass
class TileSnap:
    """One land/sea hex for stats (S0 fields; S4 uses adjacency)."""

    id: int
    type: str = ""
    value: int = 0  # dice number 2–12, or 0
    occupied_tf: bool = False  # robber on tile at board load (static map only)
    intersection_ids: List[int] = field(default_factory=list)


@dataclass
class BoardSnapshot:
    """Minimal map for MGlog stats (not a full Game board)."""

    path: str = ""
    ok: bool = False
    error: str = ""
    tiles: List[TileSnap] = field(default_factory=list)
    tile_by_id: Dict[int, TileSnap] = field(default_factory=dict)
    # intersection_id → tile ids (for RC Block later)
    intersection_to_tiles: Dict[int, List[int]] = field(default_factory=dict)
    tile_count: int = 0
    land_tile_count: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "error": self.error,
            "tile_count": self.tile_count,
            "land_tile_count": self.land_tile_count,
            "tiles": [
                {
                    "id": t.id,
                    "type": t.type,
                    "value": t.value,
                    "occupied_tf": t.occupied_tf,
                    "intersection_ids": list(t.intersection_ids),
                }
                for t in self.tiles
            ],
        }


def _terrain_to_resource(tile_type: str) -> Optional[str]:
    """Map Gen3 terrain name → RCARD key (for later S4)."""
    t = str(tile_type or "").strip().lower()
    m = {
        "field": "Wheat",
        "fields": "Wheat",
        "wheat": "Wheat",
        "mountain": "Ore",
        "mountains": "Ore",
        "ore": "Ore",
        "forest": "Wood",
        "wood": "Wood",
        "lumber": "Wood",
        "hill": "Brick",
        "hills": "Brick",
        "brick": "Brick",
        "clay": "Brick",
        "pasture": "Sheep",
        "sheep": "Sheep",
        "wool": "Sheep",
    }
    return m.get(t)


def load_playboard_for_stats(path: PathLike) -> BoardSnapshot:
    """Load playboard into a thin ``BoardSnapshot`` (reuses ``Board.load_board``).

    On failure returns ``ok=False`` with ``error`` set (caller may still
    aggregate tables that do not need geometry; RC Block → MISSING later).
    """
    resolved = _resolve_path(path)
    snap = BoardSnapshot(path=str(resolved or path or ""))
    if resolved is None or not resolved.is_file():
        # Try cwd-relative / project-relative bare name
        cand = Path(str(path))
        if not cand.is_file():
            snap.error = f"playboard not found: {path}"
            return snap
        resolved = cand.resolve()
        snap.path = str(resolved)

    try:
        from core.board import Board

        # load_map=False: blank topology only — never load constants.SAVED_PLAYBOARD
        # first (MGlog re-play R1 / double-load fix).
        board = Board(board_name="Base_Random", load_map=False)
        load_ok = False
        for cand in (str(resolved), resolved.name):
            try:
                board.load_board(cand)
                load_ok = any(
                    t is not None
                    and str(getattr(t, "type", "") or "") not in ("", "Sea", "Blank")
                    for t in (board.tiles or [])
                )
                if load_ok:
                    break
            except Exception:
                continue
        if not load_ok:
            board.load_board(str(resolved))

        tiles_out: List[TileSnap] = []
        tile_by_id: Dict[int, TileSnap] = {}
        inter_to_tiles: Dict[int, List[int]] = {}

        for t in list(getattr(board, "tiles", None) or []):
            if t is None:
                continue
            try:
                tid = int(getattr(t, "id", -1))
            except Exception:
                continue
            if tid < 0:
                continue
            itype = str(getattr(t, "type", "") or "")
            try:
                val = int(getattr(t, "value", 0) or 0)
            except Exception:
                val = 0
            occ = bool(getattr(t, "occupied_tf", False))
            inter_ids: List[int] = []
            # Prefer reverse map from intersections
            for inter in list(getattr(board, "intersections", None) or []):
                if inter is None:
                    continue
                try:
                    iid = int(getattr(inter, "id", -1))
                except Exception:
                    continue
                tids = list(getattr(inter, "three_tile_ids", None) or [])
                if tid in [int(x) for x in tids if x is not None and str(x).strip() != ""]:
                    inter_ids.append(iid)
                    inter_to_tiles.setdefault(iid, [])
                    if tid not in inter_to_tiles[iid]:
                        inter_to_tiles[iid].append(tid)
            # Fallback: corners → vertex ids if present
            if not inter_ids:
                for c in list(getattr(t, "corners", None) or []):
                    try:
                        cid = int(getattr(c, "id", getattr(c, "intersection_id", -1)))
                        if cid >= 0:
                            inter_ids.append(cid)
                    except Exception:
                        continue

            ts = TileSnap(
                id=tid,
                type=itype,
                value=val,
                occupied_tf=occ,
                intersection_ids=sorted(set(inter_ids)),
            )
            tiles_out.append(ts)
            tile_by_id[tid] = ts

        snap.tiles = tiles_out
        snap.tile_by_id = tile_by_id
        snap.intersection_to_tiles = inter_to_tiles
        snap.tile_count = len(tiles_out)
        snap.land_tile_count = sum(
            1
            for t in tiles_out
            if t.type and t.type not in ("Sea", "sea", "Water")
        )
        snap.ok = snap.tile_count > 0
        if not snap.ok:
            snap.error = "playboard loaded but no tiles"
        return snap
    except Exception as exc:
        snap.ok = False
        snap.error = f"playboard load failed: {exc}"
        return snap


# ---------------------------------------------------------------------------
# Empty / skeleton snapshot (S7 keys)
# ---------------------------------------------------------------------------


def empty_dice_stats() -> Dict[str, Any]:
    hist = [0] * 13
    return {
        "total": 0,
        "hist": list(hist),
        "by_face": {n: 0 for n in range(2, 13)},
    }


def empty_rcards_drawn() -> Dict[str, Any]:
    by = {k: 0 for k in RCARD_KEYS}
    return {
        "by_resource": dict(by),
        "short": {RCARD_SHORT[i]: 0 for i in range(NUM_RESOURCES)},
        "total": 0,
        "source": "mglog",
    }


def empty_dcards_drawn() -> Dict[str, Any]:
    by = {k: 0 for k in DCARD_KEYS}
    return {
        "by_type": dict(by),
        "total_drawn": 0,
        "source": "mglog",
    }


# ---------------------------------------------------------------------------
# S1: dice / production / dcard aggregates from rows
# ---------------------------------------------------------------------------

_PLAY_EVENTS = frozenset(
    {
        "play_knight",
        "play_yop",
        "play_monopoly",
        "play_tfr",
        "play_vp",
    }
)

_DEFAULT_COLORS = {1: "Blue", 2: "Red", 3: "White", 4: "Orange"}


def parse_dice_sum(dice_field: Any) -> Optional[int]:
    """Parse MGlog ``dice`` cell → sum in 2..12, or None.

    Accepts ``2+3=5``, ``2+3``, ``5``, ``2+3=5;extra``.
    """
    raw = str(dice_field or "").strip()
    if not raw:
        return None
    # Prefer explicit sum after '='
    if "=" in raw:
        tail = raw.split("=")[-1].strip()
        # strip trailing payload bits
        for sep in (";", " ", ","):
            if sep in tail:
                tail = tail.split(sep)[0].strip()
        n = _safe_int(tail, None)
        if n is not None and 2 <= n <= 12:
            return int(n)
    # d1+d2
    if "+" in raw:
        left = raw.split("=")[0] if "=" in raw else raw
        parts = left.replace(" ", "").split("+")
        if len(parts) >= 2:
            a = _safe_int(parts[0], None)
            b = _safe_int(parts[1], None)
            if a is not None and b is not None:
                s = int(a) + int(b)
                if 2 <= s <= 12:
                    return s
    n = _safe_int(raw.split(";")[0].strip(), None)
    if n is not None and 2 <= n <= 12:
        return int(n)
    return None


def row_rc_in_vector(row: Mapping[str, Any]) -> List[int]:
    """5-vector rc_in_0..4 from a CSV row."""
    out: List[int] = []
    for i in range(NUM_RESOURCES):
        out.append(max(0, _safe_int(row.get(f"rc_in_{i}"), 0) or 0))
    return out


def row_rc_out_vector(row: Mapping[str, Any]) -> List[int]:
    """5-vector rc_out_0..4 from a CSV row."""
    out: List[int] = []
    for i in range(NUM_RESOURCES):
        out.append(max(0, _safe_int(row.get(f"rc_out_{i}"), 0) or 0))
    return out


def _vec_sum(vec: Sequence[int]) -> int:
    return int(sum(max(0, int(x or 0)) for x in list(vec)[:NUM_RESOURCES]))


def _resource_name_to_index(name: Any) -> Optional[int]:
    raw = str(name or "").strip().lower()
    m = {
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
    return m.get(raw)


def _payload_resource_index(payload: Any) -> Optional[int]:
    """Extract resource index from payload like ``resource=wood`` / ``resource=wh``."""
    text = str(payload or "")
    if "resource=" not in text.lower():
        return None
    # resource=wood;taken=3
    lower = text.lower()
    idx = lower.find("resource=")
    if idx < 0:
        return None
    rest = text[idx + len("resource=") :]
    token = rest.split(";")[0].split(",")[0].strip()
    return _resource_name_to_index(token)


def normalize_dcard_type_stats(card_name: Any) -> str:
    """Canonical dcard type for stats (reuse mglog normalizer when available)."""
    try:
        from core.mglog import normalize_dcard_type

        return str(normalize_dcard_type(card_name) or "unknown")
    except Exception:
        raw = str(card_name or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "yop": "year_of_plenty",
            "tfr": "two_free_roads",
            "road_building": "two_free_roads",
            "vp": "victory_point",
        }
        return aliases.get(raw, raw or "unknown")


def collect_dice_from_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """S7b dice histogram from ``dice_roll`` events."""
    hist = [0] * 13
    for row in rows:
        if str(row.get("event") or "") != "dice_roll":
            continue
        s = parse_dice_sum(row.get("dice"))
        if s is not None and 2 <= s <= 12:
            hist[s] += 1
    total = sum(hist[2:13])
    return {
        "total": int(total),
        "hist": list(hist),
        "by_face": {n: hist[n] for n in range(2, 13)},
        "source": "mglog",
    }


def collect_rcards_drawn_from_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Game-level dice production totals (exclude ``payload`` ip_start)."""
    totals = {k: 0 for k in RCARD_KEYS}
    event_count = 0
    for row in rows:
        if str(row.get("event") or "") != "resource_production":
            continue
        payload = str(row.get("payload") or "")
        if "ip_start" in payload.lower():
            continue
        vec = row_rc_in_vector(row)
        if not any(vec):
            continue
        event_count += 1
        for i, key in enumerate(RCARD_KEYS):
            totals[key] += int(vec[i] or 0)
    return {
        "by_resource": dict(totals),
        "short": {RCARD_SHORT[i]: totals[RCARD_KEYS[i]] for i in range(NUM_RESOURCES)},
        "total": int(sum(totals.values())),
        "ledger_events_used": int(event_count),
        "source": "mglog_resource_production",
    }


def collect_dcards_drawn_from_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """DCards drawn = count of ``buy_dcard`` by exact type."""
    by_type = {k: 0 for k in DCARD_KEYS}
    other: Dict[str, int] = {}
    for row in rows:
        if str(row.get("event") or "") != "buy_dcard":
            continue
        ctype = normalize_dcard_type_stats(row.get("dcard_type"))
        if ctype in by_type:
            by_type[ctype] += 1
        else:
            other[ctype] = other.get(ctype, 0) + 1
    total = int(sum(by_type.values()) + sum(other.values()))
    out: Dict[str, Any] = {
        "by_type": dict(by_type),
        "total_drawn": total,
        "source": "mglog_buy_dcard",
    }
    if other:
        out["by_type_other"] = dict(other)
    return out


def discover_player_ids(rows: Sequence[Mapping[str, Any]]) -> List[int]:
    """Stable seat ids seen in the log (player_id / opponent_id), default 1..4."""
    found: set = set()
    for row in rows:
        for key in ("player_id", "opponent_id"):
            pid = _safe_int(row.get(key), None)
            if pid is not None and pid > 0:
                found.add(int(pid))
    if not found:
        return [1, 2, 3, 4]
    return sorted(found)


def collect_activity_rows_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_vp_played: bool = False,
    player_ids: Optional[Sequence[int]] = None,
    rc_block_by_seat: Optional[Mapping[int, Any]] = None,
) -> List[Dict[str, Any]]:
    """S7d–e activity rows from MGlog (S1 DC + S5 TrP_A / RC_Use).

    **TrP** always ``*`` (proposals not logged).
    **RC_Block** from ``rc_block_by_seat`` when provided (S4); else ``*``.
    """
    seats = list(player_ids) if player_ids is not None else discover_player_ids(rows)
    dc_in: Dict[int, int] = {int(p): 0 for p in seats}
    dc_play: Dict[int, int] = {int(p): 0 for p in seats}
    trp_a: Dict[int, int] = {int(p): 0 for p in seats}
    rc_use: Dict[int, int] = {int(p): 0 for p in seats}

    def _touch(pid: int) -> None:
        p = int(pid)
        if p not in dc_in:
            dc_in[p] = 0
            dc_play[p] = 0
            trp_a[p] = 0
            rc_use[p] = 0
            if p not in seats:
                seats.append(p)

    for row in rows:
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        oid = _safe_int(row.get("opponent_id"), None)

        if ev == "buy_dcard":
            if pid is None or pid <= 0:
                continue
            _touch(int(pid))
            dc_in[int(pid)] += 1
            spent = _vec_sum(row_rc_out_vector(row))
            if spent:
                rc_use[int(pid)] += spent
            continue

        if ev in ("build_road", "build_settlement", "build_city"):
            if pid is None or pid <= 0:
                continue
            _touch(int(pid))
            spent = _vec_sum(row_rc_out_vector(row))
            if spent:
                rc_use[int(pid)] += spent
            continue

        if ev == "twp":
            if pid is not None and pid > 0:
                _touch(int(pid))
                trp_a[int(pid)] += 1
            if oid is not None and oid > 0:
                _touch(int(oid))
                trp_a[int(oid)] += 1
            continue

        if ev in _PLAY_EVENTS:
            if pid is None or pid <= 0:
                continue
            if ev == "play_vp" and not include_vp_played:
                continue
            _touch(int(pid))
            dc_play[int(pid)] += 1
            continue

    seats = sorted(set(int(p) for p in seats if int(p) > 0))
    block_map = dict(rc_block_by_seat or {})
    rows_out: List[Dict[str, Any]] = []
    for pid in seats:
        if pid in block_map and block_map[pid] is not None:
            rc_block: Any = block_map[pid]
            block_src = "mglog_derived"
        else:
            rc_block = MISSING
            block_src = "pending_s4"
        rows_out.append(
            {
                "player_id": int(pid),
                "color": _DEFAULT_COLORS.get(int(pid), MISSING),
                "TVP": MISSING,  # patched by S3 when overview exists
                "winner": False,
                "TrP": MISSING,  # proposals not in MGlog
                "TrP_A": int(trp_a.get(pid, 0)),
                "RC_Use": int(rc_use.get(pid, 0)),
                "RC_Block": rc_block,
                "DC_In": int(dc_in.get(pid, 0)),
                "DC_Played": int(dc_play.get(pid, 0)),
                "sources": {
                    "TrP": "unavailable",
                    "TrP_A": "mglog_twp",
                    "RC_Use": "mglog_build_buy_rc_out",
                    "RC_Block": block_src,
                    "DC_In": "mglog_buy_dcard",
                    "DC_Played": "mglog_play_*",
                },
            }
        )
    return rows_out


def collect_dc_activity_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_vp_played: bool = False,
    player_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """Alias for ``collect_activity_rows_from_rows`` (S1 name kept for callers)."""
    return collect_activity_rows_from_rows(
        rows,
        include_vp_played=include_vp_played,
        player_ids=player_ids,
    )


def _empty_resource_bucket(pid: int) -> Dict[str, Any]:
    return {
        "player_id": int(pid),
        "color": _DEFAULT_COLORS.get(int(pid), MISSING),
        "TVP": MISSING,  # S3 overview
        "winner": False,
        "TRC_In": 0,
        "TRC_Loss": 0,
        "TRC_Nett": 0,
        "in_DR": 0,
        "in_Rob": 0,
        "in_DC": 0,
        "in_Tr": 0,
        "loss_DR7": 0,
        "loss_Rob": 0,
        "loss_DC": 0,
        "loss_Tr": 0,
        "loss_Buy": 0,
    }


def _ensure_resource_bucket(
    by_pid: Dict[int, Dict[str, Any]], order: List[int], pid: int
) -> Dict[str, Any]:
    if pid not in by_pid:
        by_pid[pid] = _empty_resource_bucket(pid)
        order.append(pid)
    return by_pid[pid]


def collect_resource_rows_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    player_ids: Optional[Sequence[int]] = None,
) -> tuple:
    """S7c resource TRC rows from MGlog events.

    Returns ``(resource_rows, meta_extra)`` where meta_extra may note monopoly
    victim split unavailability.
    """
    seats = list(player_ids) if player_ids is not None else discover_player_ids(rows)
    by_pid: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for pid in seats:
        _ensure_resource_bucket(by_pid, order, int(pid))

    meta_extra: Dict[str, Any] = {
        "monopoly_victim_split": "unavailable",  # plan v0
        "resource_source": "mglog",
    }

    for row in rows:
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        payload = str(row.get("payload") or "")
        rc_in = row_rc_in_vector(row)
        rc_out = row_rc_out_vector(row)
        in_n = _vec_sum(rc_in)
        out_n = _vec_sum(rc_out)

        if ev == "resource_production":
            if "ip_start" in payload.lower():
                continue
            if pid is None or pid <= 0:
                continue
            b = _ensure_resource_bucket(by_pid, order, int(pid))
            if in_n:
                b["in_DR"] += in_n
                b["TRC_In"] += in_n
            continue

        if ev == "steal":
            # Thief gains
            if pid is not None and pid > 0:
                b = _ensure_resource_bucket(by_pid, order, int(pid))
                gained = in_n
                if gained <= 0:
                    # fallback: one card from payload resource=
                    gained = 1 if _payload_resource_index(payload) is not None else 0
                if gained:
                    b["in_Rob"] += gained
                    b["TRC_In"] += gained
            # Victim loses one card of stolen type
            vid = _safe_int(row.get("opponent_id"), None)
            if vid is not None and vid > 0:
                vb = _ensure_resource_bucket(by_pid, order, int(vid))
                lost = in_n if in_n > 0 else (
                    1 if _payload_resource_index(payload) is not None else 0
                )
                if lost:
                    vb["loss_Rob"] += lost
                    vb["TRC_Loss"] += lost
            continue

        if ev == "discard_7":
            if pid is None or pid <= 0:
                continue
            b = _ensure_resource_bucket(by_pid, order, int(pid))
            if out_n:
                b["loss_DR7"] += out_n
                b["TRC_Loss"] += out_n
            continue

        if ev == "twb":
            if pid is None or pid <= 0:
                continue
            b = _ensure_resource_bucket(by_pid, order, int(pid))
            if in_n:
                b["in_Tr"] += in_n
                b["TRC_In"] += in_n
            if out_n:
                b["loss_Tr"] += out_n
                b["TRC_Loss"] += out_n
            continue

        if ev == "twp":
            # Proposer: rc_out give, rc_in get
            if pid is not None and pid > 0:
                b = _ensure_resource_bucket(by_pid, order, int(pid))
                if in_n:
                    b["in_Tr"] += in_n
                    b["TRC_In"] += in_n
                if out_n:
                    b["loss_Tr"] += out_n
                    b["TRC_Loss"] += out_n
            # Counterparty: inverted vectors
            oid = _safe_int(row.get("opponent_id"), None)
            if oid is not None and oid > 0:
                cb = _ensure_resource_bucket(by_pid, order, int(oid))
                # counterparty gives what proposer receives
                if in_n:
                    cb["loss_Tr"] += in_n
                    cb["TRC_Loss"] += in_n
                if out_n:
                    cb["in_Tr"] += out_n
                    cb["TRC_In"] += out_n
            continue

        if ev in ("buy_dcard", "build_road", "build_settlement", "build_city"):
            if pid is None or pid <= 0:
                continue
            b = _ensure_resource_bucket(by_pid, order, int(pid))
            # free roads: rc_out all zero
            if out_n:
                b["loss_Buy"] += out_n
                b["TRC_Loss"] += out_n
            continue

        if ev == "play_yop":
            if pid is None or pid <= 0:
                continue
            b = _ensure_resource_bucket(by_pid, order, int(pid))
            gained = in_n
            if gained <= 0:
                # resource_indices in payload res=O+Wd style
                gained = 0
            if gained:
                b["in_DC"] += gained
                b["TRC_In"] += gained
            continue

        if ev == "play_monopoly":
            # Thief only (victims not split in v0)
            if pid is None or pid <= 0:
                continue
            b = _ensure_resource_bucket(by_pid, order, int(pid))
            gained = in_n
            if gained <= 0:
                # payload taken=N
                if "taken=" in payload.lower():
                    try:
                        part = payload.lower().split("taken=")[-1]
                        tok = part.split(";")[0].split(",")[0].strip()
                        gained = max(0, int(float(tok)))
                    except Exception:
                        gained = 0
            if gained:
                b["in_DC"] += gained
                b["TRC_In"] += gained
            continue

    rows_out: List[Dict[str, Any]] = []
    for pid in order:
        b = by_pid[pid]
        b["TRC_Nett"] = int(b["TRC_In"]) - int(b["TRC_Loss"])
        rows_out.append(dict(b))
    # Stable: player_id ascending until TVP known (S3)
    rows_out.sort(key=lambda r: int(r.get("player_id") or 0))
    return rows_out, meta_extra


def apply_s1_aggregates(
    snap: Dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    include_vp_played: bool = False,
) -> Dict[str, Any]:
    """Fill dice / rcards_drawn / dcards_drawn / activity skeleton (mutates snap)."""
    snap["dice"] = collect_dice_from_rows(rows)
    snap["rcards_drawn"] = collect_rcards_drawn_from_rows(rows)
    snap["dcards_drawn"] = collect_dcards_drawn_from_rows(rows)
    # Full activity (incl. S5 TrP_A / RC_Use); S5 apply only refreshes meta tags
    activity = collect_activity_rows_from_rows(
        rows, include_vp_played=include_vp_played
    )
    snap["activity_rows"] = activity
    meta = dict(snap.get("meta") or {})
    meta["wp"] = "S1"
    meta["filled"] = True
    meta["filled_tables"] = [
        "dice",
        "rcards_drawn",
        "dcards_drawn",
        "activity_rows.DC_In",
        "activity_rows.DC_Played",
        "activity_rows.TrP_A",
        "activity_rows.RC_Use",
    ]
    meta["player_count"] = len(activity)
    meta["include_vp_played"] = bool(include_vp_played)
    snap["meta"] = meta
    return snap


def apply_s5_aggregates(
    snap: Dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    include_vp_played: bool = False,
    rc_block_by_seat: Optional[Mapping[int, Any]] = None,
) -> Dict[str, Any]:
    """Refresh activity_rows with TrP/TrP_A/RC_Use/(optional RC_Block); keep overview TVP."""
    overview = list(snap.get("overview_rows") or [])
    # Prefer block map from snap private cache (S4) if not passed
    block = rc_block_by_seat
    if block is None and isinstance(snap.get("_rc_block_by_seat"), dict):
        block = snap["_rc_block_by_seat"]
    activity = collect_activity_rows_from_rows(
        rows,
        include_vp_played=include_vp_played,
        rc_block_by_seat=block,
    )
    if overview:
        _patch_rows_from_overview(activity, overview)
        activity.sort(
            key=lambda r: (
                -int(r["TVP"]) if isinstance(r.get("TVP"), int) else 0,
                int(r.get("player_id") or 0),
            )
        )
    snap["activity_rows"] = activity
    meta = dict(snap.get("meta") or {})
    filled = list(meta.get("filled_tables") or [])
    for key in (
        "activity_rows",
        "activity_rows.TrP",
        "activity_rows.TrP_A",
        "activity_rows.RC_Use",
        "activity_rows.DC_In",
        "activity_rows.DC_Played",
    ):
        if key not in filled:
            filled.append(key)
    # RC_Block only marked filled when numeric values present
    if block is not None and any(
        isinstance(r.get("RC_Block"), int) for r in activity
    ):
        if "activity_rows.RC_Block" not in filled:
            filled.append("activity_rows.RC_Block")
    meta["filled_tables"] = filled
    meta["wp"] = "S5" if block is None else meta.get("wp", "S5")
    # If S4 already ran, keep higher wp label when set to S4
    if meta.get("wp") not in ("S4",) or block is None:
        meta["wp"] = "S5"
    meta["filled"] = True
    meta["trp_status"] = "unavailable"  # always *
    meta["player_count"] = len(activity)
    # Keep rc_block status from S4 if present
    if block is not None and any(isinstance(r.get("RC_Block"), int) for r in activity):
        meta["rc_block"] = meta.get("rc_block") or "derived"
    snap["meta"] = meta
    return snap


def apply_s2_aggregates(
    snap: Dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Fill resource_rows (S7c TRC) from MGlog events (mutates snap)."""
    resource_rows, extra = collect_resource_rows_from_rows(rows)
    snap["resource_rows"] = resource_rows
    meta = dict(snap.get("meta") or {})
    filled = list(meta.get("filled_tables") or [])
    if "resource_rows" not in filled:
        filled.append("resource_rows")
    meta["filled_tables"] = filled
    meta["wp"] = "S2"
    meta["filled"] = True
    meta["monopoly_victim_split"] = extra.get("monopoly_victim_split")
    meta["resource_source"] = extra.get("resource_source", "mglog")
    if not meta.get("player_count"):
        meta["player_count"] = len(resource_rows)
    snap["meta"] = meta
    return snap


# ---------------------------------------------------------------------------
# S3: structures + Overview (S/C/DC/LA/LR/TVP/winner)
# ---------------------------------------------------------------------------


def _payload_kv(payload: Any) -> Dict[str, str]:
    """Parse ``a=b;c=d`` payload fragments into a dict (lowercase keys)."""
    out: Dict[str, str] = {}
    text = str(payload or "")
    if not text:
        return out
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        out[str(k).strip().lower()] = str(v).strip()
    return out


def _parse_standings_payload(payload: Any) -> Dict[int, int]:
    """Parse ``standings=P2:10,P1:7`` → {2: 10, 1: 7}."""
    kv = _payload_kv(payload)
    raw = kv.get("standings") or ""
    if not raw and "standings=" in str(payload or "").lower():
        # already in kv usually
        pass
    result: Dict[int, int] = {}
    if not raw:
        return result
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # P2:10 or 2:10
        if ":" not in chunk:
            continue
        left, _, right = chunk.partition(":")
        left = left.strip().upper().lstrip("P")
        pid = _safe_int(left, None)
        vp = _safe_int(right.strip(), None)
        if pid is not None and pid > 0 and vp is not None:
            result[int(pid)] = int(vp)
    return result


def collect_overview_rows_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    player_ids: Optional[Sequence[int]] = None,
) -> tuple:
    """Build S7 overview rows from structure + specials + game_over events.

    Returns ``(overview_rows, meta_extra)``.
    """
    seats = list(player_ids) if player_ids is not None else discover_player_ids(rows)
    # Track intersection ownership for settle/city
    settlements: Dict[int, set] = {int(p): set() for p in seats}
    cities: Dict[int, set] = {int(p): set() for p in seats}
    roads: Dict[int, int] = {int(p): 0 for p in seats}
    vp_cards: Dict[int, int] = {int(p): 0 for p in seats}
    colors: Dict[int, str] = {
        int(p): _DEFAULT_COLORS.get(int(p), MISSING) for p in seats
    }

    lr_holder: Optional[int] = None
    la_holder: Optional[int] = None
    winner_id: Optional[int] = None
    standings_vp: Dict[int, int] = {}
    game_over_vp: Optional[int] = None  # winner final_vp from payload

    def _touch(pid: int) -> None:
        if pid not in settlements:
            settlements[pid] = set()
            cities[pid] = set()
            roads[pid] = 0
            vp_cards[pid] = 0
            colors.setdefault(pid, _DEFAULT_COLORS.get(pid, MISSING))
            if pid not in seats:
                seats.append(pid)

    for row in rows:
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        tw1 = _safe_int(row.get("tw1"), None)
        payload = str(row.get("payload") or "")

        if ev == "game_start":
            # optional colors=1:Blue,2:Red in payload (future-proof)
            kv = _payload_kv(payload)
            if "colors" in kv:
                for chunk in kv["colors"].split(","):
                    if ":" not in chunk:
                        continue
                    a, _, b = chunk.partition(":")
                    p = _safe_int(a.strip().lstrip("Pp"), None)
                    if p is not None and p > 0:
                        _touch(int(p))
                        colors[int(p)] = b.strip() or colors.get(int(p), MISSING)
            continue

        if ev in ("ip_place_settlement", "build_settlement"):
            if pid is None or pid <= 0:
                continue
            _touch(int(pid))
            loc = tw1 if tw1 is not None else None
            if loc is not None:
                settlements[int(pid)].add(int(loc))
            else:
                # no id: still count as anonymous settle using synthetic id
                settlements[int(pid)].add(
                    -1000 - len(settlements[int(pid)]) - 10 * int(pid)
                )
            continue

        if ev == "build_city":
            if pid is None or pid <= 0:
                continue
            _touch(int(pid))
            loc = tw1 if tw1 is not None else None
            if loc is not None:
                settlements[int(pid)].discard(int(loc))
                cities[int(pid)].add(int(loc))
            else:
                # upgrade one settle if possible
                if settlements[int(pid)]:
                    settlements[int(pid)].pop()
                cities[int(pid)].add(
                    -2000 - len(cities[int(pid)]) - 10 * int(pid)
                )
            continue

        if ev in ("ip_place_road", "build_road"):
            if pid is None or pid <= 0:
                continue
            _touch(int(pid))
            roads[int(pid)] = int(roads.get(int(pid), 0)) + 1
            continue

        if ev == "buy_dcard":
            if pid is None or pid <= 0:
                continue
            _touch(int(pid))
            ctype = normalize_dcard_type_stats(row.get("dcard_type"))
            if ctype == "victory_point":
                vp_cards[int(pid)] = int(vp_cards.get(int(pid), 0)) + 1
            continue

        if ev == "longest_road_change":
            # holder is player_id or payload to=
            kv = _payload_kv(payload)
            to_raw = kv.get("to", "")
            if to_raw == "" and pid is not None:
                lr_holder = int(pid) if pid > 0 else None
            elif to_raw == "":
                lr_holder = None
            else:
                lr_holder = _safe_int(to_raw, None)
            if lr_holder is not None and lr_holder > 0:
                _touch(int(lr_holder))
            continue

        if ev == "largest_army_change":
            kv = _payload_kv(payload)
            to_raw = kv.get("to", "")
            if to_raw == "" and pid is not None:
                la_holder = int(pid) if pid > 0 else None
            elif to_raw == "":
                la_holder = None
            else:
                la_holder = _safe_int(to_raw, None)
            if la_holder is not None and la_holder > 0:
                _touch(int(la_holder))
            continue

        if ev == "game_over":
            kv = _payload_kv(payload)
            w = _safe_int(kv.get("winner"), None)
            if w is None:
                w = pid
            if w is not None and w > 0:
                winner_id = int(w)
                _touch(winner_id)
            if "vp" in kv:
                game_over_vp = _safe_int(kv.get("vp"), None)
            standings_vp = _parse_standings_payload(payload)
            for sp in standings_vp:
                _touch(int(sp))
            continue

    # Ensure default seats present
    for p in list(seats):
        _touch(int(p))
    seat_list = sorted(set(int(p) for p in seats if int(p) > 0))

    overview: List[Dict[str, Any]] = []
    for pid in seat_list:
        s_n = len(settlements.get(pid, set()))
        c_n = len(cities.get(pid, set()))
        dc_n = int(vp_cards.get(pid, 0))
        la_pts = 2 if la_holder is not None and int(la_holder) == int(pid) else 0
        lr_pts = 2 if lr_holder is not None and int(lr_holder) == int(pid) else 0
        computed = s_n * 1 + c_n * 2 + dc_n + la_pts + lr_pts
        # Prefer game_over standings when present
        if pid in standings_vp:
            tvp = int(standings_vp[pid])
            tvp_source = "game_over_standings"
        elif winner_id is not None and int(pid) == int(winner_id) and game_over_vp is not None:
            tvp = int(game_over_vp)
            tvp_source = "game_over_vp"
        else:
            tvp = int(computed)
            tvp_source = "structures"
        overview.append(
            {
                "player_id": int(pid),
                "color": colors.get(pid, MISSING),
                "TVP": int(tvp),
                "S": int(s_n),
                "C": int(c_n),
                "DC": int(dc_n),
                "LA": int(la_pts),
                "LR": int(lr_pts),
                "roads": int(roads.get(pid, 0)),
                "winner": bool(winner_id is not None and int(pid) == int(winner_id)),
                "tvp_source": tvp_source,
                "computed_tvp": int(computed),
            }
        )

    overview.sort(
        key=lambda r: (-int(r.get("TVP") or 0), int(r.get("player_id") or 0))
    )
    meta_extra = {
        "lr_holder_id": lr_holder,
        "la_holder_id": la_holder,
        "winner_id": winner_id,
        "overview_source": "mglog_structures",
    }
    return overview, meta_extra


def _patch_rows_from_overview(
    rows: List[Dict[str, Any]], overview: Sequence[Mapping[str, Any]]
) -> None:
    """Copy TVP / winner / color from overview into resource or activity rows."""
    by = {}
    for o in overview:
        try:
            by[int(o["player_id"])] = o
        except Exception:
            continue
    for r in rows:
        try:
            pid = int(r.get("player_id"))
        except Exception:
            continue
        o = by.get(pid)
        if not o:
            continue
        r["TVP"] = o.get("TVP", r.get("TVP"))
        r["winner"] = bool(o.get("winner"))
        if o.get("color") not in (None, ""):
            r["color"] = o.get("color")


def apply_s3_aggregates(
    snap: Dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Fill overview_rows; patch TVP/winner onto resource/activity rows."""
    overview, extra = collect_overview_rows_from_rows(rows)
    snap["overview_rows"] = overview
    # Sort resource/activity by TVP like live S7
    if snap.get("resource_rows"):
        _patch_rows_from_overview(snap["resource_rows"], overview)
        snap["resource_rows"].sort(
            key=lambda r: (
                -int(r["TVP"]) if isinstance(r.get("TVP"), int) else 0,
                int(r.get("player_id") or 0),
            )
        )
    if snap.get("activity_rows"):
        _patch_rows_from_overview(snap["activity_rows"], overview)
        snap["activity_rows"].sort(
            key=lambda r: (
                -int(r["TVP"]) if isinstance(r.get("TVP"), int) else 0,
                int(r.get("player_id") or 0),
            )
        )
    meta = dict(snap.get("meta") or {})
    filled = list(meta.get("filled_tables") or [])
    if "overview_rows" not in filled:
        filled.append("overview_rows")
    meta["filled_tables"] = filled
    meta["wp"] = "S3"
    meta["filled"] = True
    meta["player_count"] = len(overview)
    meta["lr_holder_id"] = extra.get("lr_holder_id")
    meta["la_holder_id"] = extra.get("la_holder_id")
    meta["winner_id"] = extra.get("winner_id")
    meta["overview_source"] = extra.get("overview_source")
    snap["meta"] = meta
    return snap


# ---------------------------------------------------------------------------
# S4: RC Block derivation
# ---------------------------------------------------------------------------


def _initial_robber_from_board(board: BoardSnapshot) -> Optional[int]:
    """Prefer occupied_tf tile, else first Desert."""
    for t in board.tiles:
        if t.occupied_tf and t.type not in ("Sea", "sea", "Water"):
            return int(t.id)
    for t in board.tiles:
        if str(t.type or "").lower() == "desert":
            return int(t.id)
    return None


def _robber_from_board_blob(blob: Any) -> Optional[int]:
    text = str(blob or "")
    if "rob=" not in text:
        return None
    for part in text.split(";"):
        part = part.strip()
        if part.lower().startswith("rob="):
            return _safe_int(part.split("=", 1)[-1].strip(), None)
    return None


def derive_rc_block_from_rows(
    rows: Sequence[Mapping[str, Any]],
    board: Optional[BoardSnapshot],
    *,
    player_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Derive per-seat RC_Block card counts (plan §5).

    Returns dict:
      ok, by_seat {pid: int}, by_seat_resources {pid: {Wh..}}, total,
      error, rolls_considered, block_events
    """
    seats = list(player_ids) if player_ids is not None else discover_player_ids(rows)
    by_seat: Dict[int, int] = {int(p): 0 for p in seats}
    by_seat_res: Dict[int, Dict[str, int]] = {
        int(p): {k: 0 for k in RCARD_KEYS} for p in seats
    }
    out: Dict[str, Any] = {
        "ok": False,
        "by_seat": by_seat,
        "by_seat_resources": by_seat_res,
        "total": 0,
        "error": "",
        "rolls_considered": 0,
        "block_events": 0,
        "status": "unavailable",
    }

    if board is None or not board.ok or not board.tiles:
        out["error"] = (board.error if board else "") or "playboard unavailable"
        out["status"] = "unavailable"
        # Mark seats as MISSING for activity layer
        out["by_seat_missing"] = True
        return out

    # Index tiles by id; need intersection lists
    tile_by_id = dict(board.tile_by_id)
    if not tile_by_id:
        for t in board.tiles:
            tile_by_id[int(t.id)] = t
    # Sanity: at least one land tile with number and intersections
    usable = [
        t
        for t in board.tiles
        if 2 <= int(t.value or 0) <= 12 and t.intersection_ids
    ]
    if not usable:
        out["error"] = "playboard has no numbered tiles with adjacency"
        out["status"] = "unavailable"
        out["by_seat_missing"] = True
        return out

    # Structure ownership: inter -> (pid, kind settle|city)
    settle_at: Dict[int, int] = {}  # inter -> pid
    city_at: Dict[int, int] = {}

    robber: Optional[int] = _initial_robber_from_board(board)
    rolls = 0
    blocks = 0

    def _touch_seat(pid: int) -> None:
        p = int(pid)
        if p not in by_seat:
            by_seat[p] = 0
            by_seat_res[p] = {k: 0 for k in RCARD_KEYS}

    for row in rows:
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        tw1 = _safe_int(row.get("tw1"), None)

        if ev == "board_init":
            rob = _robber_from_board_blob(row.get("board_blob"))
            if rob is None:
                rob = _safe_int(row.get("robber_tile"), None)
            if rob is not None:
                robber = int(rob)
            continue

        if ev == "set_robber":
            rob = _safe_int(row.get("robber_tile"), None)
            if rob is not None:
                robber = int(rob)
            continue

        if ev in ("ip_place_settlement", "build_settlement"):
            if pid is None or pid <= 0 or tw1 is None:
                continue
            _touch_seat(int(pid))
            loc = int(tw1)
            city_at.pop(loc, None)
            settle_at[loc] = int(pid)
            continue

        if ev == "build_city":
            if pid is None or pid <= 0:
                continue
            _touch_seat(int(pid))
            if tw1 is not None:
                loc = int(tw1)
                settle_at.pop(loc, None)
                city_at[loc] = int(pid)
            else:
                # upgrade one settle of this player
                for loc, owner in list(settle_at.items()):
                    if owner == int(pid):
                        settle_at.pop(loc, None)
                        city_at[loc] = int(pid)
                        break
            continue

        if ev != "dice_roll":
            continue

        s = parse_dice_sum(row.get("dice"))
        if s is None or s == 7:
            continue
        rolls += 1
        if robber is None:
            continue
        tile = tile_by_id.get(int(robber))
        if tile is None:
            continue
        if int(tile.value or 0) != int(s):
            continue
        res_name = _terrain_to_resource(tile.type)
        if not res_name:
            continue  # desert / sea

        for inter in tile.intersection_ids:
            mult = 0
            owner: Optional[int] = None
            if inter in city_at:
                mult = 2
                owner = city_at[inter]
            elif inter in settle_at:
                mult = 1
                owner = settle_at[inter]
            if not mult or owner is None:
                continue
            _touch_seat(int(owner))
            by_seat[int(owner)] += mult
            by_seat_res[int(owner)][res_name] = (
                int(by_seat_res[int(owner)].get(res_name, 0)) + mult
            )
            blocks += 1

    out["ok"] = True
    out["status"] = "derived"
    out["by_seat"] = {int(k): int(v) for k, v in by_seat.items()}
    out["by_seat_resources"] = {
        int(k): dict(v) for k, v in by_seat_res.items()
    }
    out["total"] = int(sum(by_seat.values()))
    out["rolls_considered"] = int(rolls)
    out["block_events"] = int(blocks)
    out["by_seat_missing"] = False
    return out


def apply_s4_aggregates(
    snap: Dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
    board: Optional[BoardSnapshot] = None,
) -> Dict[str, Any]:
    """Derive RC_Block map onto snap; S5 will merge into activity_rows."""
    if board is None:
        board = snap.get("_board") if isinstance(snap.get("_board"), BoardSnapshot) else None
    result = derive_rc_block_from_rows(rows, board)
    meta = dict(snap.get("meta") or {})

    if result.get("by_seat_missing") or not result.get("ok"):
        snap["_rc_block_by_seat"] = None
        meta["rc_block"] = "unavailable"
        meta["rc_block_error"] = result.get("error") or "unavailable"
        meta["wp"] = "S4"
    else:
        snap["_rc_block_by_seat"] = dict(result.get("by_seat") or {})
        meta["rc_block"] = "derived"
        meta["rc_block_total"] = result.get("total")
        meta["rc_block_rolls"] = result.get("rolls_considered")
        meta["rc_block_by_seat"] = dict(result.get("by_seat") or {})
        meta["rc_block_by_seat_resources"] = result.get("by_seat_resources")
        meta["wp"] = "S4"
        filled = list(meta.get("filled_tables") or [])
        if "rc_block" not in filled:
            filled.append("rc_block")
        meta["filled_tables"] = filled

    meta["filled"] = True
    snap["meta"] = meta
    snap["_rc_block_detail"] = result
    return snap


def empty_statistics_snapshot(
    *,
    mglog_path: Any = "",
    playboard_path: Any = "",
    event_count: int = 0,
    board_ok: Optional[bool] = None,
    board_error: str = "",
    extra_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """S7-shaped dict with empty tables and ``meta.source == 'mglog'``."""
    meta: Dict[str, Any] = {
        "source": "mglog",
        "spec": SPEC_ID,
        "mglog_path": str(mglog_path or ""),
        "playboard_path": str(playboard_path or ""),
        "event_count": int(event_count or 0),
        "s7b": True,
        "s7c": True,
        "s7d": True,
        "s7e": True,
        "player_count": 0,
        "resource_source": "mglog",
        "filled": False,  # S0 skeleton; S1+ set True when populated
        "wp": "S0",
    }
    if board_ok is not None:
        meta["playboard_ok"] = bool(board_ok)
    if board_error:
        meta["playboard_error"] = str(board_error)
    if extra_meta:
        for k, v in dict(extra_meta).items():
            meta[k] = v
    return {
        "overview_rows": [],
        "activity_rows": [],
        "dice": empty_dice_stats(),
        "rcards_drawn": empty_rcards_drawn(),
        "dcards_drawn": empty_dcards_drawn(),
        "resource_rows": [],
        "meta": meta,
    }


def collect_endgame_statistics_from_mglog(
    mglog_path: PathLike,
    playboard_path: Optional[PathLike] = None,
    *,
    result_path: Optional[PathLike] = None,
    include_vp_played: bool = False,
) -> Dict[str, Any]:
    """Aggregate endgame stats from playboard + mglog.

    **S0:** load CSV / playboard.  
    **S1:** dice, rcards_drawn, dcards_drawn, activity DC_In / DC_Played.  
    **S2:** resource_rows (TRC breakdowns).  
    **S3:** overview_rows (S/C/DC/LA/LR/TVP/winner).  
    **S4:** RC_Block derivation (needs playboard).  
    **S5:** activity TrP/TrP_A/RC_Use/RC_Block.
    """
    mg_resolved = _resolve_path(mglog_path)
    pb_resolved = _resolve_path(playboard_path) if playboard_path else None

    rows: List[Dict[str, str]] = []
    load_error = ""
    try:
        rows = load_mglog_rows(mg_resolved or mglog_path)
    except Exception as exc:
        load_error = str(exc)

    board = BoardSnapshot(path=str(pb_resolved or playboard_path or ""))
    if playboard_path:
        board = load_playboard_for_stats(playboard_path)

    snap = empty_statistics_snapshot(
        mglog_path=str(mg_resolved or mglog_path or ""),
        playboard_path=str(board.path or pb_resolved or playboard_path or ""),
        event_count=len(rows),
        board_ok=board.ok if playboard_path else None,
        board_error=board.error if playboard_path else "",
        extra_meta={
            "mglog_load_ok": not bool(load_error),
            "mglog_load_error": load_error or None,
            "result_path": str(_resolve_path(result_path) or result_path or "")
            or None,
            "event_index_monotone": _indices_monotone(rows) if rows else None,
            "land_tile_count": board.land_tile_count if board.ok else None,
        },
    )
    if rows and not load_error:
        apply_s1_aggregates(
            snap, rows, include_vp_played=include_vp_played
        )
        apply_s2_aggregates(snap, rows)
        apply_s3_aggregates(snap, rows)
        apply_s4_aggregates(snap, rows, board=board)
        apply_s5_aggregates(
            snap, rows, include_vp_played=include_vp_played
        )
        # Final wp label: S5 if activity done; S4 detail remains in meta.rc_block
        meta = dict(snap.get("meta") or {})
        if meta.get("rc_block") == "derived":
            meta["wp"] = "S5"
            filled = list(meta.get("filled_tables") or [])
            if "activity_rows.RC_Block" not in filled:
                filled.append("activity_rows.RC_Block")
            meta["filled_tables"] = filled
        else:
            meta["wp"] = "S5"
        snap["meta"] = meta
    # Attach non-serialized helpers for in-process callers; JSON dumps strip these
    snap["_rows"] = rows
    snap["_board"] = board
    return snap


def _indices_monotone(rows: Sequence[Mapping[str, str]]) -> bool:
    idxs = mglog_event_indices(rows)
    return idxs == list(range(len(idxs))) if idxs else True


def snapshot_to_jsonable(snap: Mapping[str, Any]) -> Dict[str, Any]:
    """Drop private ``_rows`` / ``_board`` keys for JSON export."""
    out: Dict[str, Any] = {}
    for k, v in dict(snap).items():
        if str(k).startswith("_"):
            continue
        out[k] = v
    return out


def write_statistics_json(path: PathLike, snap: Mapping[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        snapshot_to_jsonable(snap),
        indent=2,
        ensure_ascii=False,
        default=str,
    )
    out.write_text(text + "\n", encoding="utf-8")
    return out.resolve()


# ---------------------------------------------------------------------------
# S8: Game Over / dig prefer-MGlog selector
# ---------------------------------------------------------------------------


def mglog_stats_on_game_over_enabled() -> bool:
    try:
        from core import constants as C

        return bool(getattr(C, "MGLOG_STATS_ON_GAME_OVER", False))
    except Exception:
        return False


def resolve_mglog_stats_paths_from_game(
    game: Any = None,
) -> Dict[str, Any]:
    """Locate mglog.csv + playboard for a live Game (best-effort).

    Returns ``{ok, mglog_path, playboard_path, reason}``.
    """
    out: Dict[str, Any] = {
        "ok": False,
        "mglog_path": None,
        "playboard_path": None,
        "reason": "",
    }
    # MGlog path: explicit game stamp first (if set but missing → fail, no silent default).
    explicit: List[str] = []
    if game is not None:
        for attr in ("mglog_path", "mglog_csv", "mglog_file"):
            try:
                raw = getattr(game, attr, None)
                if raw:
                    explicit.append(str(raw))
            except Exception:
                pass

    mglog_file: Optional[Path] = None
    if explicit:
        for c in explicit:
            p = Path(c)
            if p.is_file() and p.stat().st_size > 0:
                mglog_file = p
                break
        if mglog_file is None:
            out["reason"] = "mglog_file_missing"
            out["mglog_path"] = explicit[0]
            return out
    else:
        candidates: List[str] = []
        try:
            from core.mglog import (
                get_mglog_path_override,
                default_mglog_path,
                resolve_mglog_path,
            )

            ov = get_mglog_path_override()
            if ov:
                candidates.append(str(ov))
            candidates.append(str(resolve_mglog_path()))
            candidates.append(str(default_mglog_path()))
        except Exception:
            pass
        for c in candidates:
            if not c:
                continue
            p = Path(c)
            if p.is_file() and p.stat().st_size > 0:
                mglog_file = p
                break
        if mglog_file is None:
            out["reason"] = "mglog_file_missing"
            return out

    # Playboard: constants SAVED_PLAYBOARD if LOAD_PLAYBOARD or file exists
    pb: Optional[Path] = None
    try:
        from core import constants as C

        name = str(getattr(C, "SAVED_PLAYBOARD", "") or "")
        if name:
            root = Path(__file__).resolve().parents[1]
            for cand in (root / name, Path(name)):
                if cand.is_file():
                    pb = cand
                    break
    except Exception:
        pass

    out["ok"] = True
    out["mglog_path"] = str(mglog_file.resolve())
    out["playboard_path"] = str(pb.resolve()) if pb is not None else None
    out["reason"] = "ok"
    return out


def collect_endgame_statistics_for_ui(
    game: Any = None,
    *,
    post_game_state: Optional[Mapping[str, Any]] = None,
    prefer_mglog: Optional[bool] = None,
    force_live: bool = False,
) -> Dict[str, Any]:
    """Game Over / dig statistics: live ledger by default; optional MGlog path.

    When ``prefer_mglog`` is True (or ``MGLOG_STATS_ON_GAME_OVER`` and not
    forced live), tries offline MGlog aggregation if the CSV exists, then
    falls back to live ``collect_endgame_statistics(game)``.
    """
    use_mglog = prefer_mglog
    if use_mglog is None:
        use_mglog = mglog_stats_on_game_over_enabled()
    if force_live:
        use_mglog = False

    if use_mglog:
        paths = resolve_mglog_stats_paths_from_game(game)
        if paths.get("ok") and paths.get("mglog_path"):
            try:
                snap = collect_endgame_statistics_from_mglog(
                    paths["mglog_path"],
                    playboard_path=paths.get("playboard_path"),
                )
                meta = dict(snap.get("meta") or {})
                if meta.get("mglog_load_ok") is not False:
                    meta["ui_source"] = "mglog"
                    meta["ui_fallback"] = False
                    snap["meta"] = meta
                    # Drop private in-process keys before UI cache
                    return snapshot_to_jsonable(snap)
            except Exception as exc:
                # fall through to live
                live_err = str(exc)
            else:
                live_err = paths.get("reason") or "mglog_rejected"
        else:
            live_err = paths.get("reason") or "mglog_unavailable"
    else:
        live_err = None

    try:
        from core.game_statistics import collect_endgame_statistics

        live = collect_endgame_statistics(
            game, post_game_state=post_game_state
        )
        meta = dict(live.get("meta") or {})
        meta["ui_source"] = "live_ledger"
        meta["ui_fallback"] = bool(use_mglog)
        if live_err:
            meta["mglog_ui_error"] = live_err
        live["meta"] = meta
        return live
    except Exception as exc:
        # Last resort empty mglog-shaped snap
        empty = empty_statistics_snapshot(
            extra_meta={
                "ui_source": "error",
                "error": str(exc),
                "mglog_ui_error": live_err,
            }
        )
        empty["meta"]["filled"] = False
        return empty


__all__ = [
    "MISSING",
    "RCARD_KEYS",
    "RCARD_SHORT",
    "DCARD_KEYS",
    "SPEC_ID",
    "TileSnap",
    "BoardSnapshot",
    "load_mglog_rows",
    "mglog_event_names",
    "mglog_event_indices",
    "load_playboard_for_stats",
    "empty_dice_stats",
    "empty_rcards_drawn",
    "empty_dcards_drawn",
    "empty_statistics_snapshot",
    "parse_dice_sum",
    "row_rc_in_vector",
    "normalize_dcard_type_stats",
    "collect_dice_from_rows",
    "collect_rcards_drawn_from_rows",
    "collect_dcards_drawn_from_rows",
    "discover_player_ids",
    "collect_activity_rows_from_rows",
    "collect_dc_activity_from_rows",
    "apply_s1_aggregates",
    "apply_s5_aggregates",
    "row_rc_out_vector",
    "collect_resource_rows_from_rows",
    "apply_s2_aggregates",
    "collect_overview_rows_from_rows",
    "apply_s3_aggregates",
    "derive_rc_block_from_rows",
    "apply_s4_aggregates",
    "collect_endgame_statistics_from_mglog",
    "snapshot_to_jsonable",
    "write_statistics_json",
    "mglog_stats_on_game_over_enabled",
    "resolve_mglog_stats_paths_from_game",
    "collect_endgame_statistics_for_ui",
    "_terrain_to_resource",
]
