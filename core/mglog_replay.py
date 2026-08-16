"""MGlog re-play core (M-GUI G1) — no Strategy-Engine, no pygame.

Load playboard + mglog.csv, validate completeness (R-2T1 start / game_over end),
and rebuild board/player state by applying events ``0..cursor`` inclusive.

Plan: ``docs/MGlog_replay_gui_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

# Resource order: Wheat, Ore, Wood, Brick, Sheep
RESOURCE_KEYS = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
NUM_RESOURCES = 5

DEFAULT_COLORS = {1: "Blue", 2: "Red", 3: "White", 4: "Orange"}

DCARD_TYPES = (
    "victory_point",
    "knight",
    "two_free_roads",
    "year_of_plenty",
    "monopoly",
)

SPEC_ID = "MGLOG_REPLAY_G1"


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _vec5(row: Mapping[str, Any], prefix: str) -> List[int]:
    out: List[int] = []
    for i in range(NUM_RESOURCES):
        out.append(max(0, _safe_int(row.get(f"{prefix}_{i}"), 0) or 0))
    return out


def _normalize_dcard(name: Any) -> str:
    try:
        from core.mglog import normalize_dcard_type

        return str(normalize_dcard_type(name) or "unknown")
    except Exception:
        raw = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "yop": "year_of_plenty",
            "tfr": "two_free_roads",
            "road_building": "two_free_roads",
            "vp": "victory_point",
        }
        return aliases.get(raw, raw or "unknown")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class InputValidation:
    """Blocking input checks for playboard + mglog paths."""

    ok: bool = False
    playboard_path: str = ""
    mglog_path: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def message(self) -> str:
        if self.ok:
            return "inputs ok"
        return "; ".join(self.errors) if self.errors else "input validation failed"


@dataclass
class CompletenessReport:
    """MGlog completeness: starts at R-2T1, ends with game_over."""

    starts_ok: bool = False
    ends_ok: bool = False
    complete: bool = False
    start_reason: str = ""
    end_reason: str = ""
    first_event_index: int = 0
    last_event_index: int = -1
    game_over_index: Optional[int] = None
    start_round: Optional[int] = None
    start_turn: Optional[int] = None
    n_events: int = 0
    banner: str = ""
    # Forward nav: only meaningful when starts_ok
    forward_nav_allowed: bool = False

    def status_line(self) -> str:
        if self.complete:
            return "MGlog complete (IP R-2T1 → Game Over)"
        parts = []
        if not self.starts_ok:
            parts.append(self.start_reason or "does not start at R-2T1")
        if not self.ends_ok:
            parts.append(self.end_reason or "missing game_over")
        return "MGlog incomplete: " + "; ".join(parts)


def validate_inputs(
    playboard_path: Optional[PathLike],
    mglog_path: Optional[PathLike],
) -> InputValidation:
    """Blocking check: both files must exist and be non-empty readable."""
    v = InputValidation()
    errors: List[str] = []

    pb = Path(playboard_path) if playboard_path else None
    mg = Path(mglog_path) if mglog_path else None

    if pb is None or str(pb).strip() == "":
        errors.append("Playboard not provided")
    else:
        v.playboard_path = str(pb)
        if not pb.is_file():
            errors.append(f"Playboard not found: {pb}")
        elif pb.stat().st_size <= 0:
            errors.append(f"Playboard empty: {pb}")

    if mg is None or str(mg).strip() == "":
        errors.append("MGlog not provided")
    else:
        v.mglog_path = str(mg)
        if not mg.is_file():
            errors.append(f"MGlog not found: {mg}")
        elif mg.stat().st_size <= 0:
            errors.append(f"MGlog empty: {mg}")
        else:
            # Quick parse check
            try:
                from core.mglog_statistics import load_mglog_rows

                rows = load_mglog_rows(mg)
                if not rows:
                    errors.append(f"MGlog has no event rows: {mg}")
            except Exception as exc:
                errors.append(f"MGlog invalid: {exc}")

    v.errors = errors
    v.ok = len(errors) == 0
    return v


def _row_round_turn(row: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    return _safe_int(row.get("round"), None), _safe_int(row.get("turn"), None)


def assess_completeness(rows: Sequence[Mapping[str, Any]]) -> CompletenessReport:
    """Determine whether the log starts at R-2T1 and ends with game_over."""
    rep = CompletenessReport(n_events=len(rows))
    if not rows:
        rep.start_reason = "no events"
        rep.end_reason = "no events"
        rep.banner = rep.status_line()
        return rep

    rep.first_event_index = 0
    rep.last_event_index = len(rows) - 1

    # Ends OK: any game_over
    for i, row in enumerate(rows):
        if str(row.get("event") or "") == "game_over":
            rep.ends_ok = True
            rep.game_over_index = i
            rep.end_reason = f"game_over at event_index={i}"
            break
    if not rep.ends_ok:
        rep.end_reason = "missing game_over"

    # Starts OK: skip pure setup rows then require R-2 T1
    setup = frozenset({"game_start", "board_init"})
    first_gameplay: Optional[int] = None
    for i, row in enumerate(rows):
        ev = str(row.get("event") or "")
        if ev in setup or not ev:
            continue
        first_gameplay = i
        break

    if first_gameplay is None:
        # only setup events
        r0, t0 = _row_round_turn(rows[0])
        if r0 == -2 and (t0 is None or t0 == 1):
            rep.starts_ok = True
            rep.start_reason = "setup-only log at R-2"
            rep.start_round, rep.start_turn = -2, 1
        else:
            rep.start_reason = "no gameplay events after setup"
    else:
        # Search first few gameplay / any row with round=-2 turn=1
        found_ip = False
        for i, row in enumerate(rows):
            r, t = _row_round_turn(row)
            phase = str(row.get("phase") or "")
            ev = str(row.get("event") or "")
            if r == -2 and (t == 1 or t is None):
                found_ip = True
                rep.start_round, rep.start_turn = -2, int(t if t is not None else 1)
                rep.start_reason = f"R-2T1 at event_index={i} ({ev or phase})"
                break
            if phase.lower() in ("initialplacement", "initial_placement") and (
                r is None or r == -2
            ):
                # IP phase without explicit round: accept if early in file
                if i <= first_gameplay + 3 or i < 8:
                    found_ip = True
                    rep.start_round, rep.start_turn = -2, 1
                    rep.start_reason = f"InitialPlacement phase at event_index={i}"
                    break
        if not found_ip:
            # Check first gameplay row
            fr, ft = _row_round_turn(rows[first_gameplay])
            if fr == -2 and (ft == 1 or ft is None):
                found_ip = True
                rep.start_round, rep.start_turn = -2, 1
                rep.start_reason = f"first gameplay at R-2T1 event_index={first_gameplay}"
            else:
                rep.start_reason = (
                    f"does not start at R-2T1 "
                    f"(first gameplay event_index={first_gameplay} "
                    f"round={fr} turn={ft})"
                )
        rep.starts_ok = found_ip

    rep.complete = bool(rep.starts_ok and rep.ends_ok)
    rep.forward_nav_allowed = bool(rep.starts_ok)
    rep.banner = rep.status_line()
    return rep


# ---------------------------------------------------------------------------
# Replay state
# ---------------------------------------------------------------------------


@dataclass
class ReplayPlayer:
    id: int
    color: str = ""
    hand: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0])
    settlements: List[int] = field(default_factory=list)
    cities: List[int] = field(default_factory=list)
    roads: List[Tuple[int, int]] = field(default_factory=list)
    # DCard: held list + simple summary [name, new, playable, played]
    development_cards: List[str] = field(default_factory=list)
    dcard_summary: List[List[Any]] = field(default_factory=list)
    longest_route_tf: bool = False
    largest_army_tf: bool = False
    army_size: int = 0
    vp: int = 0

    def __post_init__(self) -> None:
        if not self.color:
            self.color = DEFAULT_COLORS.get(int(self.id), f"P{self.id}")
        if not self.dcard_summary:
            self.dcard_summary = [[n, 0, 0, 0] for n in DCARD_TYPES]


@dataclass
class ReplayState:
    """Board + seats after applying events 0..cursor."""

    cursor: int = -1  # -1 = nothing applied
    round: int = -2
    turn: int = 1
    phase: str = "InitialPlacement"
    state: str = ""
    dice: Optional[Tuple[int, int]] = None
    dice_sum: Optional[int] = None
    robber_tile: Optional[int] = None
    players: Dict[int, ReplayPlayer] = field(default_factory=dict)
    winner_id: Optional[int] = None
    game_over: bool = False
    skipped_events: int = 0
    last_event: str = ""
    # synthetic event lines applied so far (for G7)
    event_log: List[str] = field(default_factory=list)

    def player(self, pid: int) -> ReplayPlayer:
        p = int(pid)
        if p not in self.players:
            self.players[p] = ReplayPlayer(id=p)
        return self.players[p]

    def ensure_seats(self, n: int = 4) -> None:
        for i in range(1, n + 1):
            self.player(i)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class ReplaySession:
    """Loaded re-play session: rows + validation + mutable state."""

    playboard_path: str
    mglog_path: str
    rows: List[Dict[str, str]] = field(default_factory=list)
    input_validation: InputValidation = field(default_factory=InputValidation)
    completeness: CompletenessReport = field(default_factory=CompletenessReport)
    board_snapshot: Any = None  # BoardSnapshot from mglog_statistics
    state: ReplayState = field(default_factory=ReplayState)
    load_ok: bool = False
    load_errors: List[str] = field(default_factory=list)
    # R5: last nav kind + turn highlight for FX (R6–R9)
    last_nav_kind: str = ""
    highlight: Optional["TurnHighlight"] = None

    @property
    def n_events(self) -> int:
        return len(self.rows)

    @property
    def last_index(self) -> int:
        return len(self.rows) - 1 if self.rows else -1

    @property
    def cursor(self) -> int:
        return int(self.state.cursor)

    def message_block(self) -> str:
        lines: List[str] = []
        if not self.input_validation.ok:
            lines.append(self.input_validation.message())
        if self.load_errors:
            lines.extend(self.load_errors)
        lines.append(self.completeness.banner)
        return "\n".join(lines)


# Nav kinds for R5–R9 (sounds only when CONTINUE)
NAV_CONTINUE = "continue"
NAV_PREVIOUS = "previous"  # legacy event-step
NAV_FIRST = "first"
NAV_LAST = "last"
NAV_NEXT_TURN = "next_turn"
NAV_PREVIOUS_TURN = "previous_turn"
NAV_NEXT_ROUND = "next_round"
NAV_PREVIOUS_ROUND = "previous_round"
NAV_JUMP_KINDS = frozenset(
    {
        NAV_FIRST,
        NAV_LAST,
        NAV_NEXT_TURN,
        NAV_PREVIOUS_TURN,
        NAV_NEXT_ROUND,
        NAV_PREVIOUS_ROUND,
    }
)

STRUCTURE_EVENTS = frozenset(
    {
        "build_road",
        "build_settlement",
        "build_city",
        "ip_place_road",
        "ip_place_settlement",
    }
)
PLAY_DCARD_EVENTS = frozenset(
    {
        "play_knight",
        "play_yop",
        "play_monopoly",
        "play_tfr",
        "play_vp",
    }
)


@dataclass
class TurnHighlight:
    """R5: actions in the active seat-turn through the cursor (for FX).

    * Jumps land at end of a seat-turn ⇒ ``indices`` = full turn 0..last of R/T.
    * Continue ⇒ same R/T rows with index ≤ cursor (grows within the turn).

    ``seat_turn_changed`` is True when (R,T) differs from the previous highlight
    or the nav was a jump (Q4: clear prior FX).
    ``plays_sound`` is True only for Continue (R6).
    """

    round: Optional[int] = None
    turn: Optional[int] = None
    nav_kind: str = ""
    cursor: int = -1
    indices: List[int] = field(default_factory=list)
    seat_turn_changed: bool = True
    plays_sound: bool = False
    # Pre-classified indices within ``indices`` (still ≤ cursor)
    structure_indices: List[int] = field(default_factory=list)
    buy_dcard_indices: List[int] = field(default_factory=list)
    play_dcard_indices: List[int] = field(default_factory=list)
    dice_indices: List[int] = field(default_factory=list)
    set_robber_indices: List[int] = field(default_factory=list)
    steal_indices: List[int] = field(default_factory=list)
    # Robber tile ids along the turn (destinations of set_robber ≤ cursor)
    robber_destinations: List[int] = field(default_factory=list)
    # Origin robber tile before first set_robber in highlight (if known from prior state)
    robber_origin: Optional[int] = None

    @property
    def event_count(self) -> int:
        return len(self.indices)

    def events(self, rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        out: List[Mapping[str, Any]] = []
        for i in self.indices:
            if 0 <= i < len(rows):
                out.append(rows[i])
        return out


def load_replay_session(
    playboard_path: PathLike,
    mglog_path: PathLike,
    *,
    max_players: int = 4,
) -> ReplaySession:
    """Validate inputs, load rows + playboard snapshot, assess completeness.

    Does **not** apply events; call ``set_cursor`` / ``apply_through``.
    """
    session = ReplaySession(
        playboard_path=str(playboard_path),
        mglog_path=str(mglog_path),
    )
    iv = validate_inputs(playboard_path, mglog_path)
    session.input_validation = iv
    if not iv.ok:
        session.load_ok = False
        session.load_errors = list(iv.errors)
        return session

    try:
        from core.mglog_statistics import load_mglog_rows, load_playboard_for_stats

        session.rows = load_mglog_rows(mglog_path)
        session.board_snapshot = load_playboard_for_stats(playboard_path)
        if session.board_snapshot is not None and not session.board_snapshot.ok:
            session.load_errors.append(
                f"playboard load warning: {session.board_snapshot.error}"
            )
    except Exception as exc:
        session.load_ok = False
        session.load_errors.append(str(exc))
        return session

    session.completeness = assess_completeness(session.rows)
    session.state = ReplayState()
    session.state.ensure_seats(max_players)
    # Initial robber from board if known
    if session.board_snapshot is not None and session.board_snapshot.ok:
        for t in session.board_snapshot.tiles:
            if t.occupied_tf and str(t.type or "").lower() not in ("sea", "water"):
                session.state.robber_tile = int(t.id)
                break
        if session.state.robber_tile is None:
            for t in session.board_snapshot.tiles:
                if str(t.type or "").lower() == "desert":
                    session.state.robber_tile = int(t.id)
                    break
    session.load_ok = True
    return session


# ---------------------------------------------------------------------------
# Apply events
# ---------------------------------------------------------------------------


def _parse_dice_pair(dice_field: Any) -> Tuple[Optional[Tuple[int, int]], Optional[int]]:
    raw = str(dice_field or "").strip()
    if not raw:
        return None, None
    # 2+3=5
    if "+" in raw:
        left = raw.split("=")[0]
        parts = left.replace(" ", "").split("+")
        if len(parts) >= 2:
            a = _safe_int(parts[0], None)
            b = _safe_int(parts[1], None)
            if a is not None and b is not None:
                return (int(a), int(b)), int(a) + int(b)
    if "=" in raw:
        s = _safe_int(raw.split("=")[-1].split(";")[0], None)
        return None, s
    s = _safe_int(raw.split(";")[0], None)
    return None, s


def _hand_from_row(state: ReplayState, row: Mapping[str, Any]) -> None:
    """Resync hands from hand_p{n}_{i} columns when present."""
    for pid in list(state.players.keys()):
        vals = []
        any_set = False
        for i in range(NUM_RESOURCES):
            key = f"hand_p{pid}_{i}"
            if key in row and row.get(key) not in (None, ""):
                any_set = True
                vals.append(max(0, _safe_int(row.get(key), 0) or 0))
            else:
                vals.append(0)
        if any_set:
            state.player(pid).hand = vals


def _add_hand(pl: ReplayPlayer, vec: Sequence[int], sign: int = 1) -> None:
    for i in range(NUM_RESOURCES):
        try:
            d = int(vec[i] or 0) * sign
        except Exception:
            d = 0
        pl.hand[i] = max(0, int(pl.hand[i] or 0) + d)


def _dcard_row(pl: ReplayPlayer, ctype: str) -> List[Any]:
    for row in pl.dcard_summary:
        if row and str(row[0]) == ctype:
            return row
    row = [ctype, 0, 0, 0]
    pl.dcard_summary.append(row)
    return row


def _apply_one(state: ReplayState, row: Mapping[str, Any]) -> None:
    ev = str(row.get("event") or "")
    pid = _safe_int(row.get("player_id"), None)
    oid = _safe_int(row.get("opponent_id"), None)
    r, t = _row_round_turn(row)
    if r is not None:
        state.round = int(r)
    if t is not None:
        state.turn = int(t)
    phase = str(row.get("phase") or "")
    if phase:
        state.phase = phase
    st = str(row.get("state") or "")
    if st:
        state.state = st
    state.last_event = ev

    rc_in = _vec5(row, "rc_in")
    rc_out = _vec5(row, "rc_out")
    tw1 = _safe_int(row.get("tw1"), None)
    tw2 = _safe_int(row.get("tw2"), None)
    payload = str(row.get("payload") or "")

    def _line(msg: str) -> None:
        state.event_log.append(msg)

    if ev in ("game_start", "board_init"):
        rob = _safe_int(row.get("robber_tile"), None)
        if rob is not None:
            state.robber_tile = int(rob)
        blob = str(row.get("board_blob") or "")
        if "rob=" in blob:
            for part in blob.split(";"):
                if part.strip().lower().startswith("rob="):
                    state.robber_tile = _safe_int(part.split("=", 1)[-1], state.robber_tile)
        _line(ev)
        return

    if ev == "ip_place_settlement":
        if pid and tw1 is not None:
            pl = state.player(int(pid))
            if int(tw1) not in pl.settlements and int(tw1) not in pl.cities:
                pl.settlements.append(int(tw1))
            _line(f"P{pid} IP settlement @{tw1}")
        return

    if ev == "ip_place_road":
        if pid and tw1 is not None and tw2 is not None:
            a, b = int(tw1), int(tw2)
            if a > b:
                a, b = b, a
            pl = state.player(int(pid))
            edge = (a, b)
            if edge not in pl.roads:
                pl.roads.append(edge)
            _line(f"P{pid} IP road {a}-{b}")
        return

    if ev == "ip_complete":
        state.phase = "Execution"
        _line("IP complete")
        _hand_from_row(state, row)
        return

    if ev == "turn_start":
        _line(f"R{state.round}T{state.turn} start P{pid or '?'}")
        _hand_from_row(state, row)
        return

    if ev == "turn_end":
        _line(f"R{state.round}T{state.turn} end")
        return

    if ev == "dice_roll":
        pair, total = _parse_dice_pair(row.get("dice"))
        if pair:
            state.dice = pair
            state.dice_sum = pair[0] + pair[1]
        elif total is not None:
            state.dice_sum = total
        _line(f"P{pid or '?'} dice {row.get('dice')}")
        return

    if ev == "resource_production":
        if "ip_start" in payload.lower() and pid:
            pl = state.player(int(pid))
            _add_hand(pl, rc_in, +1)
            _line(f"P{pid} IP start resources")
        elif pid and any(rc_in):
            pl = state.player(int(pid))
            _add_hand(pl, rc_in, +1)
            _line(f"P{pid} production +{rc_in}")
        return

    if ev == "discard_7":
        if pid and any(rc_out):
            pl = state.player(int(pid))
            _add_hand(pl, rc_out, -1)
            _line(f"P{pid} discard {rc_out}")
        return

    if ev == "steal":
        if pid and any(rc_in):
            state.player(int(pid))
            _add_hand(state.player(int(pid)), rc_in, +1)
        if oid and any(rc_in):
            _add_hand(state.player(int(oid)), rc_in, -1)
        elif oid and payload:
            # one card fallback from payload resource=
            from core.mglog_statistics import _payload_resource_index  # type: ignore

            idx = _payload_resource_index(payload)
            if idx is not None and pid:
                vec = [0] * 5
                vec[idx] = 1
                _add_hand(state.player(int(pid)), vec, +1)
                if oid:
                    _add_hand(state.player(int(oid)), vec, -1)
        _line(f"P{pid} steals from P{oid} ({payload})")
        return

    if ev == "twb":
        if pid:
            pl = state.player(int(pid))
            _add_hand(pl, rc_out, -1)
            _add_hand(pl, rc_in, +1)
            _line(f"P{pid} TwB")
        return

    if ev == "twp":
        if pid:
            pl = state.player(int(pid))
            _add_hand(pl, rc_out, -1)
            _add_hand(pl, rc_in, +1)
        if oid:
            co = state.player(int(oid))
            # counterparty gives rc_in, receives rc_out
            _add_hand(co, rc_in, -1)
            _add_hand(co, rc_out, +1)
        _line(f"TwP P{pid}↔P{oid}")
        return

    if ev == "buy_dcard":
        if pid:
            pl = state.player(int(pid))
            _add_hand(pl, rc_out, -1)
            ctype = _normalize_dcard(row.get("dcard_type"))
            pl.development_cards.append(ctype)
            row_d = _dcard_row(pl, ctype)
            row_d[1] = int(row_d[1] or 0) + 1  # new
            _line(f"P{pid} buy {ctype}")
        return

    if ev == "activate_dcard":
        # maturity x→y: move new into playable (best-effort from summary)
        if pid:
            pl = state.player(int(pid))
            for row_d in pl.dcard_summary:
                new_n = int(row_d[1] or 0)
                if new_n:
                    row_d[2] = int(row_d[2] or 0) + new_n
                    row_d[1] = 0
            _line(f"P{pid} dcard activate")
        return

    if ev in (
        "play_knight",
        "play_yop",
        "play_monopoly",
        "play_tfr",
        "play_vp",
    ):
        if pid:
            pl = state.player(int(pid))
            ctype = _normalize_dcard(row.get("dcard_type"))
            if not ctype or ctype == "unknown":
                cmap = {
                    "play_knight": "knight",
                    "play_yop": "year_of_plenty",
                    "play_monopoly": "monopoly",
                    "play_tfr": "two_free_roads",
                    "play_vp": "victory_point",
                }
                ctype = cmap.get(ev, "unknown")
            if ctype in pl.development_cards:
                pl.development_cards.remove(ctype)
            row_d = _dcard_row(pl, ctype)
            if int(row_d[2] or 0) > 0:
                row_d[2] = int(row_d[2]) - 1
            elif int(row_d[1] or 0) > 0:
                row_d[1] = int(row_d[1]) - 1
            row_d[3] = int(row_d[3] or 0) + 1
            if any(rc_in):
                _add_hand(pl, rc_in, +1)
            if ctype == "knight":
                pl.army_size = int(pl.army_size or 0) + 1
            _line(f"P{pid} {ev}")
        return

    if ev == "build_settlement":
        if pid and tw1 is not None:
            pl = state.player(int(pid))
            _add_hand(pl, rc_out, -1)
            if int(tw1) not in pl.settlements and int(tw1) not in pl.cities:
                pl.settlements.append(int(tw1))
            _line(f"P{pid} settlement @{tw1}")
        return

    if ev == "build_city":
        if pid and tw1 is not None:
            pl = state.player(int(pid))
            _add_hand(pl, rc_out, -1)
            loc = int(tw1)
            if loc in pl.settlements:
                pl.settlements.remove(loc)
            if loc not in pl.cities:
                pl.cities.append(loc)
            _line(f"P{pid} city @{loc}")
        return

    if ev == "build_road":
        if pid:
            pl = state.player(int(pid))
            if "free" not in payload.lower():
                _add_hand(pl, rc_out, -1)
            if tw1 is not None and tw2 is not None:
                a, b = int(tw1), int(tw2)
                if a > b:
                    a, b = b, a
                edge = (a, b)
                if edge not in pl.roads:
                    pl.roads.append(edge)
            _line(f"P{pid} road")
        return

    if ev == "set_robber":
        rob = _safe_int(row.get("robber_tile"), None)
        if rob is not None:
            state.robber_tile = int(rob)
        _line(f"robber → {state.robber_tile}")
        return

    if ev == "longest_road_change":
        # clear all then set holder
        for pl in state.players.values():
            pl.longest_route_tf = False
        holder = pid
        if holder is None:
            # payload to=
            for part in payload.split(";"):
                if part.strip().lower().startswith("to="):
                    holder = _safe_int(part.split("=", 1)[-1], None)
        if holder:
            state.player(int(holder)).longest_route_tf = True
        _line(f"LR → P{holder}")
        return

    if ev == "largest_army_change":
        for pl in state.players.values():
            pl.largest_army_tf = False
        holder = pid
        for part in payload.split(";"):
            if part.strip().lower().startswith("to="):
                holder = _safe_int(part.split("=", 1)[-1], None)
        if holder:
            state.player(int(holder)).largest_army_tf = True
        _line(f"LA → P{holder}")
        return

    if ev == "game_over":
        state.game_over = True
        w = pid
        for part in payload.split(";"):
            if part.strip().lower().startswith("winner="):
                w = _safe_int(part.split("=", 1)[-1], w)
        state.winner_id = int(w) if w else None
        _line(f"Game Over winner=P{state.winner_id}")
        _hand_from_row(state, row)
        return

    # unknown — skip
    state.skipped_events += 1


def _recompute_vp(state: ReplayState) -> None:
    for pl in state.players.values():
        s = len(pl.settlements)
        c = len(pl.cities)
        vp_cards = sum(1 for x in pl.development_cards if x == "victory_point")
        # also count revealed in summary col3 for VP
        for row in pl.dcard_summary:
            if row and str(row[0]) == "victory_point":
                vp_cards = max(vp_cards, int(row[3] or 0) + int(row[1] or 0) + int(row[2] or 0))
        la = 2 if pl.largest_army_tf else 0
        lr = 2 if pl.longest_route_tf else 0
        pl.vp = s + 2 * c + vp_cards + la + lr


def empty_state(max_players: int = 4, robber: Optional[int] = None) -> ReplayState:
    st = ReplayState(robber_tile=robber)
    st.ensure_seats(max_players)
    return st


def apply_through(
    session: ReplaySession,
    cursor: int,
    *,
    max_players: int = 4,
    nav_kind: str = "",
    refresh_highlight: bool = True,
) -> ReplayState:
    """Rebuild state by applying rows[0..cursor] inclusive. Updates session.state.

    When ``refresh_highlight`` is True (default), recompute R5 ``session.highlight``
    using ``nav_kind`` (or ``session.last_nav_kind`` if empty).
    """
    if not session.rows:
        session.state = empty_state(max_players)
        if refresh_highlight:
            session.highlight = empty_turn_highlight(nav_kind or session.last_nav_kind)
        return session.state

    k = int(cursor)
    if k < -1:
        k = -1
    if k > session.last_index:
        k = session.last_index

    robber0 = None
    if session.board_snapshot is not None and getattr(session.board_snapshot, "ok", False):
        for t in session.board_snapshot.tiles:
            if t.occupied_tf and str(t.type or "").lower() not in ("sea", "water"):
                robber0 = int(t.id)
                break
        if robber0 is None:
            for t in session.board_snapshot.tiles:
                if str(t.type or "").lower() == "desert":
                    robber0 = int(t.id)
                    break

    # Robber origin for highlight: tile just before first set_robber in seat-turn
    # is derived after we know the seat-turn (in compute_turn_highlight).

    state = empty_state(max_players, robber=robber0)
    if k < 0:
        session.state = state
        if refresh_highlight:
            kind = nav_kind or session.last_nav_kind or ""
            if nav_kind:
                session.last_nav_kind = nav_kind
            session.highlight = empty_turn_highlight(kind)
        return state

    for i in range(0, k + 1):
        try:
            _apply_one(state, session.rows[i])
        except Exception:
            state.skipped_events += 1
    state.cursor = k
    _recompute_vp(state)
    session.state = state
    if refresh_highlight:
        kind = nav_kind or session.last_nav_kind or ""
        if nav_kind:
            session.last_nav_kind = nav_kind
        refresh_session_highlight(session, nav_kind=kind)
    return state


def set_cursor(
    session: ReplaySession,
    cursor: int,
    *,
    nav_kind: str = "",
    refresh_highlight: bool = True,
) -> ReplayState:
    """Set cursor and rebuild state; optionally stamp nav_kind for R5 highlight."""
    return apply_through(
        session,
        cursor,
        nav_kind=nav_kind,
        refresh_highlight=refresh_highlight,
    )


def find_cursor_for_event_index(
    session: ReplaySession, event_index: int
) -> int:
    """SE5: map enriched ``event_index`` column → list index for ``set_cursor``.

    Prefers matching ``row['event_index']``; falls back to treating
    ``event_index`` as a list index when in range.
    """
    target = int(event_index)
    rows = list(getattr(session, "rows", None) or [])
    for i, row in enumerate(rows):
        raw = row.get("event_index")
        if raw is None or raw == "":
            continue
        try:
            if int(float(raw)) == target:
                return i
        except Exception:
            continue
    if 0 <= target < len(rows):
        return target
    return int(getattr(session, "cursor", 0) or 0)


def set_cursor_to_event_index(
    session: ReplaySession,
    event_index: int,
    *,
    nav_kind: str = "",
    refresh_highlight: bool = True,
) -> ReplayState:
    """SE5: land re-play on the row with the given ``event_index``."""
    idx = find_cursor_for_event_index(session, event_index)
    return set_cursor(
        session,
        idx,
        nav_kind=nav_kind,
        refresh_highlight=refresh_highlight,
    )


def empty_turn_highlight(nav_kind: str = "") -> TurnHighlight:
    return TurnHighlight(
        nav_kind=str(nav_kind or ""),
        plays_sound=(str(nav_kind or "") == NAV_CONTINUE),
        seat_turn_changed=True,
    )


def _robber_tile_before_index(session: ReplaySession, index: int) -> Optional[int]:
    """Robber tile after applying rows[0..index-1] (for R9 origin green).

    Mirrors apply_one: board snapshot desert/occupied, then game_start /
    board_init robber_tile (+ board_blob rob=), then each set_robber.
    """
    tile: Optional[int] = None
    if session.board_snapshot is not None and getattr(session.board_snapshot, "ok", False):
        for t in session.board_snapshot.tiles:
            if t.occupied_tf and str(t.type or "").lower() not in ("sea", "water"):
                tile = int(t.id)
                break
        if tile is None:
            for t in session.board_snapshot.tiles:
                if str(t.type or "").lower() == "desert":
                    tile = int(t.id)
                    break
    end = min(max(0, index), len(session.rows))
    for i in range(0, end):
        row = session.rows[i]
        ev = str(row.get("event") or "")
        if ev in ("game_start", "board_init"):
            rob = _safe_int(row.get("robber_tile"), None)
            if rob is not None:
                tile = int(rob)
            blob = str(row.get("board_blob") or "")
            if "rob=" in blob:
                for part in blob.split(";"):
                    if part.strip().lower().startswith("rob="):
                        tile = _safe_int(part.split("=", 1)[-1], tile)
            continue
        if ev != "set_robber":
            continue
        rob = _safe_int(row.get("robber_tile"), None)
        if rob is not None:
            tile = int(rob)
    return tile


def compute_turn_highlight(
    session: ReplaySession,
    *,
    nav_kind: str = "",
    previous: Optional[TurnHighlight] = None,
) -> TurnHighlight:
    """Build R5 highlight for current cursor and nav kind.

    Highlight seat-turn = (round, turn) of the cursor row (or state).
    Indices = all rows with that R/T and index ≤ cursor.
    """
    kind = str(nav_kind or session.last_nav_kind or "")
    hl = TurnHighlight(
        nav_kind=kind,
        cursor=int(session.cursor),
        plays_sound=(kind == NAV_CONTINUE),
    )
    if not session.rows or session.cursor < 0:
        hl.seat_turn_changed = True
        return hl

    r, t = _seat_turn_at_index(session, session.cursor)
    hl.round, hl.turn = r, t
    if r is None or t is None:
        # No R/T on row — include only the cursor event if any
        if 0 <= session.cursor < len(session.rows):
            hl.indices = [session.cursor]
        hl.seat_turn_changed = True
        return hl

    for i, row in enumerate(session.rows):
        if i > session.cursor:
            break
        rr, tt = _row_round_turn(row)
        if rr is None or tt is None:
            continue
        if int(rr) == int(r) and int(tt) == int(t):
            hl.indices.append(i)

    prev_rt = None
    if previous is not None and previous.round is not None and previous.turn is not None:
        prev_rt = (int(previous.round), int(previous.turn))
    cur_rt = (int(r), int(t))
    jump = kind in NAV_JUMP_KINDS
    hl.seat_turn_changed = bool(jump or prev_rt is None or prev_rt != cur_rt)

    # Classify + robber path
    dests: List[int] = []
    first_robber_i: Optional[int] = None
    for i in hl.indices:
        row = session.rows[i]
        ev = str(row.get("event") or "")
        if ev in STRUCTURE_EVENTS:
            hl.structure_indices.append(i)
        if ev == "buy_dcard":
            hl.buy_dcard_indices.append(i)
        if ev in PLAY_DCARD_EVENTS:
            hl.play_dcard_indices.append(i)
        if ev == "dice_roll":
            hl.dice_indices.append(i)
        if ev == "set_robber":
            hl.set_robber_indices.append(i)
            if first_robber_i is None:
                first_robber_i = i
            rob = _safe_int(row.get("robber_tile"), None)
            if rob is not None:
                dests.append(int(rob))
        if ev == "steal":
            hl.steal_indices.append(i)
    hl.robber_destinations = dests
    if first_robber_i is not None:
        hl.robber_origin = _robber_tile_before_index(session, first_robber_i)
    return hl


def refresh_session_highlight(
    session: ReplaySession,
    *,
    nav_kind: str = "",
) -> TurnHighlight:
    """Recompute and store ``session.highlight`` (keeps previous for change detect)."""
    prev = session.highlight
    kind = str(nav_kind or session.last_nav_kind or "")
    if nav_kind:
        session.last_nav_kind = str(nav_kind)
    hl = compute_turn_highlight(session, nav_kind=kind, previous=prev)
    session.highlight = hl
    return hl


# ---------------------------------------------------------------------------
# Navigation helpers (for G3 buttons)
# ---------------------------------------------------------------------------


def nav_capabilities(session: ReplaySession) -> Dict[str, Any]:
    """Which nav actions are available at current cursor (R4 seat-turn landings)."""
    c = session.cursor
    last = session.last_index
    starts_ok = session.completeness.starts_ok
    at_end = c >= last if last >= 0 else True
    has_more = c < last

    # Forward requires starts_ok per plan
    forward_base = bool(starts_ok and has_more and session.load_ok)
    next_turn_land = _find_next_turn_land(session, c)
    next_round_land = _find_next_round_land(session, c)
    prev_turn_land = _find_previous_turn_land(session, c)
    prev_round_land = _find_previous_round_land(session, c)

    can_next_turn = bool(
        session.load_ok
        and starts_ok
        and next_turn_land is not None
        and next_turn_land != c
    )
    can_next_round = bool(
        session.load_ok
        and starts_ok
        and next_round_land is not None
        and next_round_land != c
    )
    can_prev_turn = bool(
        session.load_ok and prev_turn_land is not None and prev_turn_land != c
    )
    can_prev_round = bool(
        session.load_ok and prev_round_land is not None and prev_round_land != c
    )

    return {
        "load_ok": session.load_ok,
        "starts_ok": starts_ok,
        "ends_ok": session.completeness.ends_ok,
        "complete": session.completeness.complete,
        "cursor": c,
        "last_index": last,
        "at_end": at_end,
        "can_first": session.load_ok and c > 0,
        # legacy event-step (kept for digs / tests; not on R3 panel)
        "can_previous": session.load_ok and c > 0,
        "can_previous_turn": can_prev_turn,
        "can_previous_round": can_prev_round,
        "can_continue": forward_base,
        "can_next_turn": can_next_turn,
        "can_next_round": can_next_round,
        "can_last": bool(session.load_ok and starts_ok and last >= 0 and c < last),
        "forward_blocked_incomplete_start": session.load_ok and not starts_ok,
        "forward_blocked_no_more_data": starts_ok and at_end,
        "banner": session.completeness.banner,
        "input_errors": list(session.input_validation.errors) + list(session.load_errors),
    }


def _seat_turn_at_index(
    session: ReplaySession, index: int
) -> Tuple[Optional[int], Optional[int]]:
    """(round, turn) for row at index, falling back to state."""
    if 0 <= index < len(session.rows):
        r, t = _row_round_turn(session.rows[index])
        if r is not None and t is not None:
            return int(r), int(t)
    return (
        _safe_int(getattr(session.state, "round", None), None),
        _safe_int(getattr(session.state, "turn", None), None),
    )


def _last_index_of_seat_turn(
    session: ReplaySession, round_n: int, turn_n: int
) -> Optional[int]:
    """Last row index with matching (round, turn), or None.

    Prefer last ``turn_end`` for that R/T when present; else last any row.
    """
    last_any: Optional[int] = None
    last_end: Optional[int] = None
    for i, row in enumerate(session.rows):
        r, t = _row_round_turn(row)
        if r is None or t is None:
            continue
        if int(r) != int(round_n) or int(t) != int(turn_n):
            continue
        last_any = i
        if str(row.get("event") or "") == "turn_end":
            last_end = i
    return last_end if last_end is not None else last_any


def seat_turn_bounds(
    session: ReplaySession, round_n: int, turn_n: int
) -> Optional[Tuple[int, int]]:
    """Inclusive (first_i, last_i) for a seat-turn, or None if absent."""
    first: Optional[int] = None
    last = _last_index_of_seat_turn(session, round_n, turn_n)
    if last is None:
        return None
    for i, row in enumerate(session.rows):
        r, t = _row_round_turn(row)
        if r is not None and t is not None and int(r) == int(round_n) and int(t) == int(turn_n):
            first = i
            break
    if first is None:
        return None
    return int(first), int(last)


def reverse_ip_display_turn(
    round_n: Any,
    turn_n: Any,
    *,
    n_players: int = 4,
) -> Optional[int]:
    """F3: top-left Turn label for reverse IP (round == -1).

    MGlog keeps ``turn == player_id`` (chrono reverse: T4→T3→T2→T1).
    Display order for reverse placement is sequence 1..n, so:

        display_turn = (n_players + 1) - mglog_turn

    e.g. 4p: log T1 → show 4, log T4 → show 1. Other rounds: unchanged.
    Nav/lands always use raw MGlog (round, turn).
    """
    try:
        r = int(round_n)
        t = int(turn_n)
        n = int(n_players)
    except Exception:
        return _safe_int(turn_n, None)
    if n < 2:
        return t
    if r == -1 and 1 <= t <= n:
        return int(n + 1 - t)
    return t


def _player_id_for_seat_turn(
    session: ReplaySession, round_n: int, turn_n: int, first_i: int, last_i: int
) -> Optional[int]:
    """Acting player_id for a seat-turn (prefer turn_start / any non-empty player_id)."""
    rows = session.rows
    prefer: Optional[int] = None
    for i in range(int(first_i), int(last_i) + 1):
        if i < 0 or i >= len(rows):
            continue
        row = rows[i]
        rr, tt = _row_round_turn(row)
        if rr is None or tt is None:
            continue
        if int(rr) != int(round_n) or int(tt) != int(turn_n):
            continue
        pid = _safe_int(row.get("player_id"), None)
        if pid is None or pid <= 0:
            continue
        ev = str(row.get("event") or "")
        if ev == "turn_start":
            return int(pid)
        if prefer is None:
            prefer = int(pid)
    # Fallback: turn number often equals seat/player in Gen3
    if prefer is not None:
        return prefer
    try:
        return int(turn_n) if int(turn_n) > 0 else None
    except Exception:
        return None


def _ordered_seat_turns(session: ReplaySession) -> List[Tuple[int, int, int, int]]:
    """List of (round, turn, first_i, last_i) in first-seen chronological order.

    F3: order follows MGlog chronology (IP reverse is T4→T3→T2→T1, then R1T1…).
    """
    order: List[Tuple[int, int]] = []
    seen = set()
    for row in session.rows:
        r, t = _row_round_turn(row)
        if r is None or t is None:
            continue
        key = (int(r), int(t))
        if key not in seen:
            seen.add(key)
            order.append(key)
    out: List[Tuple[int, int, int, int]] = []
    for r, t in order:
        bounds = seat_turn_bounds(session, r, t)
        if bounds is not None:
            out.append((r, t, bounds[0], bounds[1]))
    return out


def _ordered_seat_turns_ex(
    session: ReplaySession,
) -> List[Tuple[int, int, int, int, Optional[int]]]:
    """(round, turn, first_i, last_i, player_id) chronological."""
    out: List[Tuple[int, int, int, int, Optional[int]]] = []
    for r, t, f, last in _ordered_seat_turns(session):
        pid = _player_id_for_seat_turn(session, r, t, f, last)
        out.append((r, t, f, last, pid))
    return out


def _find_next_turn_land(session: ReplaySession, cursor: int) -> Optional[int]:
    """R4/F3 Next Turn: end of current seat-turn, else end of next chrono seat-turn.

    Chronology includes IP reverse (e.g. R-1T4 → R-1T3 → R-1T2 → R-1T1 → R1T1).
    """
    turns = _ordered_seat_turns(session)
    if not turns:
        return None
    r, t = _seat_turn_at_index(session, cursor)
    if r is None or t is None:
        # Before any R/T: jump to end of first seat-turn if any
        return turns[0][3] if turns else None

    idx = None
    for i, (rr, tt, _f, last) in enumerate(turns):
        if rr == int(r) and tt == int(t):
            idx = i
            break
    if idx is None:
        return None
    _rr, _tt, _f, L = turns[idx]
    if cursor < L:
        return L
    if idx + 1 < len(turns):
        return turns[idx + 1][3]
    return None


def _find_previous_turn_land(session: ReplaySession, cursor: int) -> Optional[int]:
    """R4/F3 Previous Turn: last row of chronologically previous seat-turn.

    Example (g003 reverse IP): from R1T1 previous lands R-1T1 (P1's reverse
    seat-turn), not R-1T4 — T4 is earlier in reverse order (P4 then P3…).
    """
    turns = _ordered_seat_turns(session)
    if not turns:
        return None
    r, t = _seat_turn_at_index(session, cursor)
    if r is None or t is None:
        return None
    idx = None
    for i, (rr, tt, _f, last) in enumerate(turns):
        if rr == int(r) and tt == int(t):
            idx = i
            break
    if idx is None or idx <= 0:
        return None
    return turns[idx - 1][3]


def _seat_key_for_round_nav(
    session: ReplaySession, cursor: int
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(round, turn, player_id) for round jumps (same seat)."""
    r, t = _seat_turn_at_index(session, cursor)
    if r is None or t is None:
        return None, None, None
    bounds = seat_turn_bounds(session, int(r), int(t))
    pid = None
    if bounds is not None:
        pid = _player_id_for_seat_turn(session, int(r), int(t), bounds[0], bounds[1])
    if pid is None:
        pid = _safe_int(t, None)
    return int(r), int(t), int(pid) if pid is not None else None


def _find_next_round_land(session: ReplaySession, cursor: int) -> Optional[int]:
    """F2 Next Round: same seat, next *existing* round (skip missing R0 etc.).

    Seat key: prefer ``player_id``; also match same ``turn`` number when pid missing.
    Example: R-2T1 → R-1T1 → R1T1 → R2T1 (never R0).
    """
    r, t, pid = _seat_key_for_round_nav(session, cursor)
    if r is None or t is None:
        return None
    turns = _ordered_seat_turns_ex(session)
    # Candidates after current round with same seat
    candidates: List[Tuple[int, int]] = []  # (round, last_i)
    for rr, tt, _f, last, ppid in turns:
        if int(rr) <= int(r):
            continue
        same_seat = False
        if pid is not None and ppid is not None and int(ppid) == int(pid):
            same_seat = True
        elif int(tt) == int(t):
            same_seat = True
        if same_seat:
            candidates.append((int(rr), int(last)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])  # smallest round > r
    return candidates[0][1]


def _find_previous_round_land(session: ReplaySession, cursor: int) -> Optional[int]:
    """F2 Previous Round: same seat, previous *existing* round (skip missing R0).

    Example: R2T1 → R1T1 → R-1T1 → R-2T1.
    """
    r, t, pid = _seat_key_for_round_nav(session, cursor)
    if r is None or t is None:
        return None
    turns = _ordered_seat_turns_ex(session)
    candidates: List[Tuple[int, int]] = []
    for rr, tt, _f, last, ppid in turns:
        if int(rr) >= int(r):
            continue
        same_seat = False
        if pid is not None and ppid is not None and int(ppid) == int(pid):
            same_seat = True
        elif int(tt) == int(t):
            same_seat = True
        if same_seat:
            candidates.append((int(rr), int(last)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])  # largest round < r
    return candidates[-1][1]


def step_continue(session: ReplaySession) -> Optional[int]:
    """Advance one event; return new cursor or None if blocked."""
    cap = nav_capabilities(session)
    if not cap["can_continue"]:
        return None
    return set_cursor(session, session.cursor + 1, nav_kind=NAV_CONTINUE).cursor


def step_previous(session: ReplaySession) -> Optional[int]:
    """Legacy: one event back (not exposed on R3 panel)."""
    cap = nav_capabilities(session)
    if not cap["can_previous"]:
        return None
    return set_cursor(session, session.cursor - 1, nav_kind=NAV_PREVIOUS).cursor


def step_first(session: ReplaySession) -> Optional[int]:
    if not session.load_ok or not session.rows:
        return None
    return set_cursor(session, 0, nav_kind=NAV_FIRST).cursor


def step_last(session: ReplaySession) -> Optional[int]:
    """>> : last event in log (R4); R5 highlight = last seat-turn through end."""
    cap = nav_capabilities(session)
    if not cap["starts_ok"] or session.last_index < 0:
        return None
    if session.cursor >= session.last_index:
        return None
    return set_cursor(session, session.last_index, nav_kind=NAV_LAST).cursor


def step_next_turn(session: ReplaySession) -> Optional[int]:
    """R4: finish current seat-turn, else land end of next player's seat-turn."""
    cap = nav_capabilities(session)
    if not cap["can_next_turn"]:
        return None
    idx = _find_next_turn_land(session, session.cursor)
    if idx is None or idx == session.cursor:
        return None
    return set_cursor(session, idx, nav_kind=NAV_NEXT_TURN).cursor


def step_next_round(session: ReplaySession) -> Optional[int]:
    """F2: land end of same seat, next *existing* round (skip gaps e.g. R0)."""
    cap = nav_capabilities(session)
    if not cap["can_next_round"]:
        return None
    idx = _find_next_round_land(session, session.cursor)
    if idx is None or idx == session.cursor:
        return None
    return set_cursor(session, idx, nav_kind=NAV_NEXT_ROUND).cursor


def step_previous_turn(session: ReplaySession) -> Optional[int]:
    """R4: land end of previous seat-turn (never snap current first — Q2)."""
    cap = nav_capabilities(session)
    if not cap.get("can_previous_turn"):
        return None
    idx = _find_previous_turn_land(session, session.cursor)
    if idx is None or idx == session.cursor:
        return None
    return set_cursor(session, idx, nav_kind=NAV_PREVIOUS_TURN).cursor


def step_previous_round(session: ReplaySession) -> Optional[int]:
    """F2: land end of same seat, previous *existing* round (skip gaps e.g. R0)."""
    cap = nav_capabilities(session)
    if not cap.get("can_previous_round"):
        return None
    idx = _find_previous_round_land(session, session.cursor)
    if idx is None or idx == session.cursor:
        return None
    return set_cursor(session, idx, nav_kind=NAV_PREVIOUS_ROUND).cursor


# ---------------------------------------------------------------------------
# G6: derived “?” turn details from MGlog events (current R/T)
# ---------------------------------------------------------------------------

# Scoreboard order: Wheat, Ore, Wood, Brick, Sheep, Gold (unused in MGlog)
TURN_DETAIL_CATEGORIES = (
    "resource_production",
    "resource_production_robber",
    "buy",
    "steal",
    "discard",
    "TwP",
    "TwB",
    "dcard",
)

# Legacy player attr names (gui/scoreboard)
TURN_DETAIL_ATTR = {
    "resource_production": "turn_details_resource_production",
    "resource_production_robber": "turn_details_resource_production_robber",
    "buy": "turn_details_buy",
    "steal": "turn_details_steal",
    "discard": "turn_details_discard",
    "TwP": "turn_details_TwP",
    "TwB": "turn_details_TwB",
    "dcard": "turn_details_dcard",
}

# Popup row labels matching live GUI
TURN_DETAIL_LABELS = (
    ("RP", "resource_production"),
    ("RP Corr", "resource_production_robber"),
    ("Buy", "buy"),
    ("Steal", "steal"),
    ("Discard", "discard"),
    ("TwP", "TwP"),
    ("TwB", "TwB"),
    ("Dcard", "dcard"),
)


def empty_turn_detail_vectors() -> Dict[str, List[int]]:
    return {k: [0, 0, 0, 0, 0, 0] for k in TURN_DETAIL_CATEGORIES}


def _vec5_to_delta6(vec5: Sequence[int], sign: int = 1) -> List[int]:
    """MGlog 5-vector → 6-slot scoreboard delta (Gold always 0)."""
    out = [0, 0, 0, 0, 0, 0]
    for i in range(min(5, len(vec5))):
        try:
            out[i] = int(vec5[i] or 0) * int(sign)
        except Exception:
            out[i] = 0
    return out


def _add_delta6(dst: List[int], src: Sequence[int]) -> None:
    for i in range(6):
        try:
            dst[i] = int(dst[i] or 0) + int(src[i] or 0)
        except Exception:
            pass


def _ensure_detail_bucket(
    by_pid: Dict[int, Dict[str, List[int]]], pid: int
) -> Dict[str, List[int]]:
    p = int(pid)
    if p not in by_pid:
        by_pid[p] = empty_turn_detail_vectors()
    return by_pid[p]


def _steal_one_card_vec5(row: Mapping[str, Any]) -> List[int]:
    """One-card steal as 5-vector (prefer rc_in; fallback payload resource=)."""
    vin = _vec5(row, "rc_in")
    if any(vin):
        return vin
    try:
        from core.mglog_statistics import _payload_resource_index  # type: ignore

        idx = _payload_resource_index(row.get("payload"))
    except Exception:
        idx = None
    if idx is not None and 0 <= int(idx) < 5:
        v = [0, 0, 0, 0, 0]
        v[int(idx)] = 1
        return v
    return [0, 0, 0, 0, 0]


def derive_turn_details(
    rows: Sequence[Mapping[str, Any]],
    *,
    round_n: int,
    turn_n: int,
    through_index: Optional[int] = None,
) -> Dict[int, Dict[str, List[int]]]:
    """Aggregate MGlog events for one Gen3 R/T into per-player turn-detail vectors.

    Vectors are 6-slot deltas in scoreboard order (Wheat…Sheep, Gold=0), same
    sign convention as live play: production/gains positive, buys/discards
    negative, trades net get−give.

    Only rows with matching ``round``/``turn`` and index ``<= through_index``
    (when set) are included so re-play details grow as the cursor advances.

    ``resource_production_robber`` (RP Corr) is left zero — MGlog does not log
    blocked production (same gap as plan §2.3).
    """
    by_pid: Dict[int, Dict[str, List[int]]] = {}
    if not rows:
        return by_pid

    end = len(rows) - 1
    if through_index is not None:
        end = min(end, int(through_index))

    target_r = int(round_n)
    target_t = int(turn_n)

    for i in range(0, end + 1):
        row = rows[i]
        r, t = _row_round_turn(row)
        if r is None or t is None:
            continue
        if int(r) != target_r or int(t) != target_t:
            continue

        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        oid = _safe_int(row.get("opponent_id"), None)
        payload = str(row.get("payload") or "")
        rc_in = _vec5(row, "rc_in")
        rc_out = _vec5(row, "rc_out")

        if ev == "resource_production":
            if "ip_start" in payload.lower():
                continue
            if pid is None or pid <= 0 or not any(rc_in):
                continue
            b = _ensure_detail_bucket(by_pid, int(pid))
            _add_delta6(b["resource_production"], _vec5_to_delta6(rc_in, +1))
            continue

        if ev == "discard_7":
            if pid is None or pid <= 0 or not any(rc_out):
                continue
            b = _ensure_detail_bucket(by_pid, int(pid))
            _add_delta6(b["discard"], _vec5_to_delta6(rc_out, -1))
            continue

        if ev == "steal":
            stolen = _steal_one_card_vec5(row)
            if not any(stolen):
                continue
            if pid is not None and pid > 0:
                b = _ensure_detail_bucket(by_pid, int(pid))
                _add_delta6(b["steal"], _vec5_to_delta6(stolen, +1))
            if oid is not None and oid > 0:
                vb = _ensure_detail_bucket(by_pid, int(oid))
                _add_delta6(vb["steal"], _vec5_to_delta6(stolen, -1))
            continue

        if ev == "twb":
            if pid is None or pid <= 0:
                continue
            b = _ensure_detail_bucket(by_pid, int(pid))
            # net = get − give
            net = _vec5_to_delta6(rc_in, +1)
            _add_delta6(net, _vec5_to_delta6(rc_out, -1))
            if any(net):
                _add_delta6(b["TwB"], net)
            continue

        if ev == "twp":
            # Proposer: +rc_in −rc_out; counterparty inverted
            if pid is not None and pid > 0:
                b = _ensure_detail_bucket(by_pid, int(pid))
                net = _vec5_to_delta6(rc_in, +1)
                _add_delta6(net, _vec5_to_delta6(rc_out, -1))
                if any(net):
                    _add_delta6(b["TwP"], net)
            if oid is not None and oid > 0:
                cb = _ensure_detail_bucket(by_pid, int(oid))
                cnet = _vec5_to_delta6(rc_out, +1)  # receives proposer's give
                _add_delta6(cnet, _vec5_to_delta6(rc_in, -1))  # gives proposer's get
                if any(cnet):
                    _add_delta6(cb["TwP"], cnet)
            continue

        if ev in ("buy_dcard", "build_road", "build_settlement", "build_city"):
            if pid is None or pid <= 0:
                continue
            if "free" in payload.lower() and ev == "build_road":
                continue
            if not any(rc_out):
                continue
            b = _ensure_detail_bucket(by_pid, int(pid))
            _add_delta6(b["buy"], _vec5_to_delta6(rc_out, -1))
            continue

        if ev in ("play_yop", "play_monopoly"):
            if pid is None or pid <= 0:
                continue
            if not any(rc_in):
                # monopoly may only have taken=N without per-resource split
                continue
            b = _ensure_detail_bucket(by_pid, int(pid))
            _add_delta6(b["dcard"], _vec5_to_delta6(rc_in, +1))
            continue

    return by_pid


def turn_detail_rows_from_vectors(
    vectors: Mapping[str, Sequence[int]],
) -> List[Tuple[str, List[int]]]:
    """Non-empty labeled rows for the live '?' popup renderer."""
    rows_out: List[Tuple[str, List[int]]] = []
    for label, key in TURN_DETAIL_LABELS:
        raw = list(vectors.get(key) or [0, 0, 0, 0, 0, 0])
        vec = [0, 0, 0, 0, 0, 0]
        for i in range(min(6, len(raw))):
            try:
                vec[i] = int(raw[i] or 0)
            except Exception:
                vec[i] = 0
        if any(v != 0 for v in vec):
            rows_out.append((label, vec))
    return rows_out


def derive_turn_details_at_cursor(
    session: ReplaySession,
) -> Dict[int, Dict[str, List[int]]]:
    """Details for session.state's current round/turn, through the cursor."""
    st = session.state
    return derive_turn_details(
        session.rows,
        round_n=int(st.round),
        turn_n=int(st.turn),
        through_index=int(st.cursor) if st.cursor is not None else None,
    )


def apply_turn_details_to_paint_player(
    paint_player: Any, vectors: Optional[Mapping[str, Sequence[int]]]
) -> None:
    """Copy derived vectors onto a paint-side player namespace (legacy attrs)."""
    src = vectors or empty_turn_detail_vectors()
    for cat, attr in TURN_DETAIL_ATTR.items():
        raw = list(src.get(cat) or [0, 0, 0, 0, 0, 0])
        vec = [0, 0, 0, 0, 0, 0]
        for i in range(min(6, len(raw))):
            try:
                vec[i] = int(raw[i] or 0)
            except Exception:
                vec[i] = 0
        try:
            setattr(paint_player, attr, vec)
        except Exception:
            pass
    # Optional last TwP deal mirror (not derived separately in v0)
    try:
        if not getattr(paint_player, "turn_details_last_TwPdeal", None):
            setattr(paint_player, "turn_details_last_TwPdeal", [0, 0, 0, 0, 0, 0])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# G7: synthetic event lines for re-play Events strip (from MGlog only)
# ---------------------------------------------------------------------------

_RC_SHORT = ("Wh", "O", "Wd", "B", "Sh")


@dataclass
class SyntheticEvent:
    """One short line for the re-play Events panel."""

    index: int
    event: str
    message: str
    player_id: Optional[int] = None
    round: Optional[int] = None
    turn: Optional[int] = None

    def display(self, *, with_rt: bool = False) -> str:
        """Human line; optionally prefix R#T# for dig context."""
        if with_rt and self.round is not None and self.turn is not None:
            return f"R{self.round}T{self.turn} {self.message}"
        return self.message


def format_rc_short(vec5: Sequence[int], *, sign: str = "") -> str:
    """Compact resource summary, e.g. ``+Wh+Wd`` or ``-O×2-Sh``."""
    parts: List[str] = []
    for i, name in enumerate(_RC_SHORT):
        try:
            n = int(vec5[i] or 0) if i < len(vec5) else 0
        except Exception:
            n = 0
        if n <= 0:
            continue
        if n == 1:
            parts.append(f"{sign}{name}")
        else:
            parts.append(f"{sign}{name}×{n}")
    return "".join(parts) if parts else ""


def synthesize_event_line(
    row: Mapping[str, Any],
    index: int = 0,
) -> SyntheticEvent:
    """Build one short synthetic line from an MGlog CSV row (no SE / no BA)."""
    ev = str(row.get("event") or "").strip() or "unknown"
    pid = _safe_int(row.get("player_id"), None)
    oid = _safe_int(row.get("opponent_id"), None)
    r, t = _row_round_turn(row)
    payload = str(row.get("payload") or "")
    rc_in = _vec5(row, "rc_in")
    rc_out = _vec5(row, "rc_out")
    tw1 = _safe_int(row.get("tw1"), None)
    tw2 = _safe_int(row.get("tw2"), None)
    who = f"P{pid}" if pid else ""

    def _mk(msg: str) -> SyntheticEvent:
        return SyntheticEvent(
            index=int(index),
            event=ev,
            message=msg,
            player_id=pid,
            round=r,
            turn=t,
        )

    if ev in ("game_start", "board_init"):
        return _mk(ev.replace("_", " "))

    if ev == "ip_place_settlement":
        return _mk(f"{who} IP settle @{tw1}" if tw1 is not None else f"{who} IP settle")

    if ev == "ip_place_road":
        if tw1 is not None and tw2 is not None:
            return _mk(f"{who} IP road {tw1}-{tw2}")
        return _mk(f"{who} IP road")

    if ev == "ip_complete":
        return _mk("IP complete")

    if ev == "turn_start":
        return _mk(f"R{r if r is not None else '?'}T{t if t is not None else '?'} start {who}".strip())

    if ev == "turn_end":
        return _mk(f"R{r if r is not None else '?'}T{t if t is not None else '?'} end")

    if ev == "dice_roll":
        pair, total = _parse_dice_pair(row.get("dice"))
        if pair:
            return _mk(f"{who} dice {pair[0]}+{pair[1]}={pair[0]+pair[1]}".strip())
        if total is not None:
            return _mk(f"{who} dice {total}".strip())
        raw = str(row.get("dice") or payload or "?")
        return _mk(f"{who} dice {raw}".strip())

    if ev == "resource_production":
        if "ip_start" in payload.lower():
            got = format_rc_short(rc_in, sign="+")
            return _mk(f"{who} IP start {got or 'rc'}".strip())
        got = format_rc_short(rc_in, sign="+")
        return _mk(f"{who} prod {got or '—'}".strip())

    if ev == "discard_7":
        lost = format_rc_short(rc_out, sign="-")
        return _mk(f"{who} discard {lost or 'rc'}".strip())

    if ev == "steal":
        got = format_rc_short(rc_in, sign="+")
        if not got:
            try:
                from core.mglog_statistics import _payload_resource_index  # type: ignore

                idx = _payload_resource_index(payload)
            except Exception:
                idx = None
            if idx is not None and 0 <= int(idx) < 5:
                got = f"+{_RC_SHORT[int(idx)]}"
        victim = f"P{oid}" if oid else "?"
        return _mk(f"{who} steals {got or '1'} from {victim}".strip())

    if ev == "twb":
        give = format_rc_short(rc_out, sign="-")
        get = format_rc_short(rc_in, sign="+")
        return _mk(f"{who} TwB {give or '—'}→{get or '—'}".strip())

    if ev == "twp":
        give = format_rc_short(rc_out, sign="-")
        get = format_rc_short(rc_in, sign="+")
        other = f"P{oid}" if oid else "?"
        return _mk(f"{who}↔{other} TwP {give or '—'}→{get or '—'}".strip())

    if ev == "buy_dcard":
        ctype = _normalize_dcard(row.get("dcard_type"))
        cost = format_rc_short(rc_out, sign="-")
        return _mk(f"{who} buy {ctype} {cost}".strip())

    if ev == "activate_dcard":
        return _mk(f"{who} dcard activate".strip())

    if ev in ("play_knight", "play_yop", "play_monopoly", "play_tfr", "play_vp"):
        short = {
            "play_knight": "knight",
            "play_yop": "YoP",
            "play_monopoly": "monopoly",
            "play_tfr": "TFR",
            "play_vp": "VP",
        }.get(ev, ev)
        got = format_rc_short(rc_in, sign="+")
        if got:
            return _mk(f"{who} play {short} {got}".strip())
        return _mk(f"{who} play {short}".strip())

    if ev == "build_settlement":
        return _mk(f"{who} settle @{tw1}" if tw1 is not None else f"{who} settle")

    if ev == "build_city":
        return _mk(f"{who} city @{tw1}" if tw1 is not None else f"{who} city")

    if ev == "build_road":
        free = "free " if "free" in payload.lower() else ""
        if tw1 is not None and tw2 is not None:
            return _mk(f"{who} {free}road {tw1}-{tw2}".strip())
        return _mk(f"{who} {free}road".strip())

    if ev == "set_robber":
        rob = _safe_int(row.get("robber_tile"), None)
        return _mk(f"{who} robber → {rob if rob is not None else '?'}".strip())

    if ev == "longest_road_change":
        holder = pid
        for part in payload.split(";"):
            if part.strip().lower().startswith("to="):
                holder = _safe_int(part.split("=", 1)[-1], holder)
        return _mk(f"LR → P{holder}" if holder else "LR change")

    if ev == "largest_army_change":
        holder = pid
        for part in payload.split(";"):
            if part.strip().lower().startswith("to="):
                holder = _safe_int(part.split("=", 1)[-1], holder)
        return _mk(f"LA → P{holder}" if holder else "LA change")

    if ev == "game_over":
        w = pid
        for part in payload.split(";"):
            if part.strip().lower().startswith("winner="):
                w = _safe_int(part.split("=", 1)[-1], w)
        return _mk(f"Game Over P{w}" if w else "Game Over")

    # Fallback: short event name + optional player
    if who:
        return _mk(f"{who} {ev}")
    return _mk(ev)


def synthesize_event_lines(
    rows: Sequence[Mapping[str, Any]],
    *,
    through_index: Optional[int] = None,
    from_index: int = 0,
) -> List[SyntheticEvent]:
    """Synthesize event lines for rows ``from_index..through_index`` inclusive.

    Default ``through_index=None`` uses the full list. Re-play typically passes
    the cursor so the strip shows history up to the current moment.
    """
    if not rows:
        return []
    start = max(0, int(from_index))
    end = len(rows) - 1
    if through_index is not None:
        end = min(end, int(through_index))
    if start > end:
        return []
    out: List[SyntheticEvent] = []
    for i in range(start, end + 1):
        try:
            out.append(synthesize_event_line(rows[i], index=i))
        except Exception:
            out.append(
                SyntheticEvent(
                    index=i,
                    event=str(rows[i].get("event") or "error"),
                    message=f"#{i} (parse error)",
                )
            )
    return out


def synthesize_events_at_cursor(session: ReplaySession) -> List[SyntheticEvent]:
    """Lines for events ``0..cursor`` (history through current re-play position)."""
    st = session.state
    k = int(st.cursor) if st.cursor is not None else -1
    if k < 0 or not session.rows:
        return []
    return synthesize_event_lines(session.rows, through_index=k)


def event_messages(
    lines: Sequence[SyntheticEvent],
    *,
    with_rt: bool = False,
) -> List[str]:
    """Plain message strings from synthetic events."""
    return [e.display(with_rt=with_rt) for e in lines]


__all__ = [
    "SPEC_ID",
    "RESOURCE_KEYS",
    "DEFAULT_COLORS",
    "InputValidation",
    "CompletenessReport",
    "ReplayPlayer",
    "ReplayState",
    "ReplaySession",
    "TurnHighlight",
    "NAV_CONTINUE",
    "NAV_JUMP_KINDS",
    "STRUCTURE_EVENTS",
    "PLAY_DCARD_EVENTS",
    "validate_inputs",
    "assess_completeness",
    "load_replay_session",
    "apply_through",
    "set_cursor",
    "find_cursor_for_event_index",
    "set_cursor_to_event_index",
    "empty_state",
    "empty_turn_highlight",
    "compute_turn_highlight",
    "refresh_session_highlight",
    "nav_capabilities",
    "step_continue",
    "step_previous",
    "step_first",
    "step_last",
    "step_next_turn",
    "step_next_round",
    "step_previous_turn",
    "step_previous_round",
    "seat_turn_bounds",
    "reverse_ip_display_turn",
    "TURN_DETAIL_CATEGORIES",
    "TURN_DETAIL_ATTR",
    "TURN_DETAIL_LABELS",
    "empty_turn_detail_vectors",
    "derive_turn_details",
    "derive_turn_details_at_cursor",
    "turn_detail_rows_from_vectors",
    "apply_turn_details_to_paint_player",
    "SyntheticEvent",
    "format_rc_short",
    "synthesize_event_line",
    "synthesize_event_lines",
    "synthesize_events_at_cursor",
    "event_messages",
]
