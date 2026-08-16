"""Phase L partial Victory-Way salvage — S0–S7 + S4 sticky (S8 pending).

Spec: ``docs/PhaseL_partial_way_salvage_plan.md``.

**S0:** component ids, enable gate.
**S1:** ``strip_components`` / residual need + EH ETA.
**S2–S3:** T1 expand + T2 residual rank.
**S4:** sticky/BA honor ``partial_plan`` + ``ignored_components``; suppress
dead LR/LA projects; bounce-guard after salvage escape.
**S5–S6:** expansion geometry + fair VP-DCard death.
**S7:** probe/result dig fields (salvage adopt events + KPIs).

Live SE must not call salvage **ranking** until ``salvage_ranking_available()``
(S3). S1 helpers are safe pure functions for tests and future wire-up.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple, Union

# Canonical dead-component ids (sticky / dig / strip masks)
COMPONENT_CITIES = "cities"
COMPONENT_SETTLES_EXPAND = "settles_expand"
COMPONENT_ROADS_EXPAND = "roads_expand"
COMPONENT_LR = "LR"
COMPONENT_LA = "LA"
COMPONENT_VP_DCARDS = "vp_dcards"

ALL_COMPONENTS: FrozenSet[str] = frozenset(
    {
        COMPONENT_CITIES,
        COMPONENT_SETTLES_EXPAND,
        COMPONENT_ROADS_EXPAND,
        COMPONENT_LR,
        COMPONENT_LA,
        COMPONENT_VP_DCARDS,
    }
)

# Salvage tier labels (meta / dig)
SALVAGE_T0 = "t0_full"
SALVAGE_T1 = "t1_nonspecial"  # ways that never needed dead components
SALVAGE_T2 = "t2_partial_residual"  # stripped templates, residual ETA
SALVAGE_T3 = "t3_vp_scrape"

SPEC_FREEZE_ID = "PARTIAL_WAY_SALVAGE_S0_v1"
S1_IMPL_ID = "PARTIAL_WAY_SALVAGE_S1_v1"
S2_IMPL_ID = "PARTIAL_WAY_SALVAGE_S2_v1"
S3_IMPL_ID = "PARTIAL_WAY_SALVAGE_S3_v1"
S4_IMPL_ID = "PARTIAL_WAY_SALVAGE_S4_v1"
S5_IMPL_ID = "PARTIAL_WAY_SALVAGE_S5_v1"
S5B_IMPL_ID = "PARTIAL_WAY_SALVAGE_S5b_v1"  # settles_expand gate (not “no settle yet”)
S5B_G6_IMPL_ID = "PARTIAL_WAY_SALVAGE_S5b_G6_v1"  # deferred vs dead dig KPIs
S6_IMPL_ID = "PARTIAL_WAY_SALVAGE_S6_v1"
S7_IMPL_ID = "PARTIAL_WAY_SALVAGE_S7_v1"
S7A_IMPL_ID = "PARTIAL_WAY_SALVAGE_S7a_v1"  # abstract_way_before resolver (D1+)

# S7 dig: salvage adopt event name (probe JSONL shares la_lr_probe sink)
EVENT_SALVAGE_ADOPT = "salvage_adopt"
MAX_SALVAGE_EVENTS_ON_GAME = 64
MAX_EXPANSION_SETTLES_DIG_EVENTS = 64
SETTLES_REASON_DEFERRED = "deferred_need_roads"
SETTLES_REASON_GATE_B = "no_settle_and_roads_closed"

# S7a pre-adopt way source labels (resolve_pre_adopt_way_id)
PRE_ADOPT_SOURCE_STICKY = "sticky_locked"
PRE_ADOPT_SOURCE_DIR_PREFERRED = "direction_preferred"
PRE_ADOPT_SOURCE_DIR_WAY = "direction_way"
PRE_ADOPT_SOURCE_REPORT = "report_preferred"
PRE_ADOPT_SOURCE_LAST_DIR = "last_direction"
PRE_ADOPT_SOURCE_WAYS_USED = "ways_used_last"
PRE_ADOPT_SOURCE_NONE = "none"
# When caller passes before-id without a source label (pre-D2 / unit tests)
PRE_ADOPT_SOURCE_EXPLICIT = "explicit"

# S7a way_change_kind enum (note_salvage_adopt dig records)
WAY_CHANGE_FIRST_LOCK = "first_lock"
WAY_CHANGE_SAME = "same"
WAY_CHANGE_SWITCH = "switch"
WAY_CHANGE_UNKNOWN = "unknown"

# EH / rank ceilings (align with portfolio)
INFINITE_TURNS = 9999.0

# Default number of non-dead-special ways injected into L2 eval (S2 T1)
DEFAULT_T1_EXPAND_N = 6

# Piece caps (match viable_action_scanner defaults)
_DEFAULT_MAX_SETTLEMENTS = 5
_DEFAULT_MAX_ROADS = 15

PathLikeReq = Any  # StrategyRequirement | Mapping


def is_giveup_salvage_partial_enabled(constants_module: Any = None) -> bool:
    """Operator flag ``GIVEUP_SALVAGE_PARTIAL`` (default False until S1+ ships)."""
    try:
        C = constants_module
        if C is None:
            from core import constants as C  # type: ignore
        return bool(getattr(C, "GIVEUP_SALVAGE_PARTIAL", False))
    except Exception:
        return False


def is_salvage_t1_expand_enabled(constants_module: Any = None) -> bool:
    """S2: inject non-dead-special ways into portfolio eval when episode kills specials.

    On when ``GIVEUP_SALVAGE_PARTIAL`` **or** ``GIVEUP_ESCAPE_ENABLED`` so lab
    escape can see T1 candidates without a separate flag flip.
    """
    try:
        C = constants_module
        if C is None:
            from core import constants as C  # type: ignore
        if bool(getattr(C, "GIVEUP_SALVAGE_PARTIAL", False)):
            return True
        if bool(getattr(C, "GIVEUP_ESCAPE_ENABLED", False)):
            return True
    except Exception:
        pass
    return False


def is_salvage_t2_enabled(constants_module: Any = None) -> bool:
    """S3: residual T2 ranking when T1 hard-filter is empty (soft demote path)."""
    return is_salvage_t1_expand_enabled(constants_module)


def salvage_ranking_available(constants_module: Any = None) -> bool:
    """True when S3 T2 residual ranking may run (escape or salvage flag on)."""
    return is_salvage_t2_enabled(constants_module)


def salvage_helpers_available() -> bool:
    """S1 residual strip + ETA helpers are always importable (no flag required)."""
    return True


def t1_expand_n(constants_module: Any = None) -> int:
    """Max non-dead-special ways to inject (operator override optional)."""
    try:
        C = constants_module
        if C is None:
            from core import constants as C  # type: ignore
        n = getattr(C, "GIVEUP_SALVAGE_T1_EXPAND_N", None)
        if n is not None:
            return max(0, min(20, int(n)))
    except Exception:
        pass
    return int(DEFAULT_T1_EXPAND_N)


def strategy_needs_dead_component(strategy: Any, dead: Set[str]) -> bool:
    """True if strategy still requires any currently dead component (S1–S5)."""
    if not dead or strategy is None:
        return False
    if COMPONENT_LR in dead and bool(getattr(strategy, "longest_road", False)):
        return True
    if COMPONENT_LA in dead and bool(
        getattr(strategy, "biggest_army", False)
        or getattr(strategy, "largest_army", False)
    ):
        return True
    if COMPONENT_VP_DCARDS in dead and int(
        getattr(strategy, "victory_point_cards", 0) or 0
    ) > 0:
        return True
    if COMPONENT_CITIES in dead and (
        int(getattr(strategy, "city_upgrades", 0) or 0) > 0
        or int(getattr(strategy, "cities", 0) or 0) > 0
    ):
        return True
    new_s = int(getattr(strategy, "new_settlements_to_build", 0) or 0)
    roads = int(getattr(strategy, "roads_to_build", 0) or 0)
    if COMPONENT_SETTLES_EXPAND in dead and new_s > 0:
        return True
    # Road geometry blocked: expansion roads and new settles that depend on them
    if COMPONENT_ROADS_EXPAND in dead and (roads > 0 or new_s > 0):
        return True
    return False


def strategy_needs_dead_special(strategy: Any, dead: Set[str]) -> bool:
    """Alias: historically LR/LA only; now full dead-component check."""
    return strategy_needs_dead_component(strategy, dead)


def way_avoids_dead_specials(way_id: int, dead: Set[str], *, strategy: Any = None) -> bool:
    """True if way does not require any currently dead component."""
    if not dead:
        return True
    s = strategy if strategy is not None else _load_strategy(int(way_id))
    if s is None:
        return False
    return not strategy_needs_dead_component(s, dead)


def detect_expansion_geometry_block(
    game: Any,
    player: Any,
    *,
    max_roads: int = _DEFAULT_MAX_ROADS,
    max_settlements: int = _DEFAULT_MAX_SETTLEMENTS,
) -> Dict[str, Any]:
    """Geometry-only expansion death (ignore hand / affordability).

    Fair-play: uses legal road/settle *targets* from the board network, same
    primitives as ``viable_action_scanner`` (not god-view deck).

    **S5b gate B:** ``settles_expand`` is dead only on settlement piece cap, or
    when settle-now is empty **and** roads are closed (no legal road / max
    roads). Empty settle targets with roads still legal → **not** dead
    (``settles_reason=deferred_need_roads``).
    """
    out: Dict[str, Any] = {
        "s5": True,
        "s5b": True,
        "impl_id": S5B_IMPL_ID,
        "s5_impl_id": S5_IMPL_ID,
        "roads_expand_dead": False,
        "settles_expand_dead": False,
        "roads_reason": "",
        "settles_reason": "",
        "n_legal_roads": None,
        "n_legal_settles": None,
        "settles_raw_empty": False,
        "roads_closed": False,
    }
    if player is None or game is None:
        out["roads_reason"] = out["settles_reason"] = "no_player_or_game"
        return out
    if str(getattr(game, "phase", "") or "") != "Execution":
        out["roads_reason"] = out["settles_reason"] = "not_execution"
        return out

    board = getattr(game, "board", None)
    try:
        from core.viable_action_scanner import (
            DEFAULT_MAX_ROADS,
            DEFAULT_MAX_SETTLEMENTS,
            _legal_road_targets,
            _legal_settlement_targets,
        )

        max_r = int(max_roads or DEFAULT_MAX_ROADS)
        max_s = int(max_settlements or DEFAULT_MAX_SETTLEMENTS)
    except Exception:
        _legal_road_targets = None  # type: ignore
        _legal_settlement_targets = None  # type: ignore
        max_r = int(max_roads)
        max_s = int(max_settlements)

    # Roads
    try:
        n_roads = len(list(getattr(player, "roads", None) or []))
    except Exception:
        n_roads = 0
    if n_roads >= max_r:
        out["roads_expand_dead"] = True
        out["roads_reason"] = f"max_roads:{n_roads}"
        out["n_legal_roads"] = 0
        out["roads_closed"] = True
    elif board is None or _legal_road_targets is None:
        out["roads_reason"] = "no_board_or_scanner"
    else:
        try:
            targets = list(_legal_road_targets(board, player) or [])
            out["n_legal_roads"] = len(targets)
            if not targets:
                out["roads_expand_dead"] = True
                out["roads_reason"] = "no_legal_road_target"
                out["roads_closed"] = True
            else:
                out["roads_reason"] = "ok"
                out["roads_closed"] = False
        except Exception as exc:
            out["roads_reason"] = f"scan_error:{exc}"

    roads_closed = bool(out.get("roads_closed")) or bool(out.get("roads_expand_dead"))
    out["roads_closed"] = roads_closed

    # Settlements (S5b gate A / B)
    try:
        n_set = len(list(getattr(player, "settlements", None) or []))
        n_city = len(list(getattr(player, "cities", None) or []))
        n_struct = max(n_set, n_set + n_city)
    except Exception:
        n_struct = 0
        n_city = 0
    try:
        n_settlements_only = len(
            [
                s
                for s in (getattr(player, "settlements", None) or [])
                if s not in set(getattr(player, "cities", None) or [])
            ]
        )
    except Exception:
        n_settlements_only = n_struct

    if n_settlements_only + n_city >= max_s:
        # Gate A: piece limit
        out["settles_expand_dead"] = True
        out["settles_reason"] = f"max_settlements:{n_settlements_only + n_city}"
        out["n_legal_settles"] = 0
        out["settles_raw_empty"] = True
    elif board is None or _legal_settlement_targets is None:
        out["settles_reason"] = "no_board_or_scanner"
    else:
        try:
            stargets = list(_legal_settlement_targets(board, player) or [])
            out["n_legal_settles"] = len(stargets)
            settle_empty = len(stargets) == 0
            out["settles_raw_empty"] = settle_empty
            if not settle_empty:
                out["settles_expand_dead"] = False
                out["settles_reason"] = "ok"
            elif roads_closed:
                # Gate B: no settle now and cannot grow roads
                out["settles_expand_dead"] = True
                out["settles_reason"] = "no_settle_and_roads_closed"
            else:
                # Need roads first — not permanent death
                out["settles_expand_dead"] = False
                out["settles_reason"] = "deferred_need_roads"
        except Exception as exc:
            out["settles_reason"] = f"scan_error:{exc}"

    return out


def update_player_expansion_dead(
    game: Any,
    player: Any,
    *,
    force_scan: bool = True,
) -> Dict[str, Any]:
    """Detect geometry block and store on ``player.expansion_dead_components``.

    Returns the stored snapshot (also sets ``game.last_expansion_dead`` for dig).
    """
    if not force_scan:
        raw = getattr(player, "expansion_dead_components", None) if player else None
        return dict(raw) if isinstance(raw, Mapping) else {}

    det = detect_expansion_geometry_block(game, player)
    payload = {
        "roads_expand": bool(det.get("roads_expand_dead")),
        "settles_expand": bool(det.get("settles_expand_dead")),
        "roads_reason": det.get("roads_reason"),
        "settles_reason": det.get("settles_reason"),
        "n_legal_roads": det.get("n_legal_roads"),
        "n_legal_settles": det.get("n_legal_settles"),
        "settles_raw_empty": bool(det.get("settles_raw_empty")),
        "roads_closed": bool(det.get("roads_closed")),
        "round": getattr(game, "round", None) if game is not None else None,
        "turn": getattr(game, "turn", None) if game is not None else None,
        "impl_id": S5B_IMPL_ID,
        "s5_impl_id": S5_IMPL_ID,
        "s5b": True,
    }
    if player is not None:
        try:
            player.expansion_dead_components = dict(payload)
        except Exception:
            pass
    if game is not None:
        try:
            game.last_expansion_dead = dict(payload)
            game.last_expansion_dead_player_id = getattr(player, "id", None)
        except Exception:
            pass
        # S5b G6: dig counters deferred vs dead settles
        try:
            note_expansion_settles_dig(game, player, payload)
        except Exception:
            pass
    return payload


def _ensure_expansion_dig_state(game: Any) -> Dict[str, Any]:
    """Mutable game-level S5b dig counters (deferred vs dead settles)."""
    state = getattr(game, "expansion_settles_dig_state", None) if game is not None else None
    if isinstance(state, dict) and "settles_deferred_scans" in state:
        return state
    state = {
        "settles_deferred_scans": 0,
        "settles_dead_scans": 0,
        "settles_ok_scans": 0,
        "settles_deferred_by_seat": {},  # str(pid) -> scan count
        "settles_dead_by_seat": {},
        "seats_ever_deferred": set(),  # or list after export
        "seats_ever_dead": set(),
        "events": [],
        "seen_keys": set(),  # (seat, kind, reason) first event only
    }
    if game is not None:
        try:
            game.expansion_settles_dig_state = state
        except Exception:
            pass
    return state


def note_expansion_settles_dig(
    game: Any,
    player: Any,
    payload: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """S5b G6: count settle deferred vs settle-dead geometry snapshots.

    Called from ``update_player_expansion_dead`` each refresh. Increments scan
    counters every time; appends a compact event only on first (seat, kind, reason).
    """
    if game is None or not isinstance(payload, Mapping):
        return None
    state = _ensure_expansion_dig_state(game)
    reason = str(payload.get("settles_reason") or "")
    settles_dead = bool(payload.get("settles_expand"))
    raw_empty = bool(payload.get("settles_raw_empty"))
    roads_closed = bool(payload.get("roads_closed"))

    kind: Optional[str] = None
    if settles_dead:
        kind = "dead"
        state["settles_dead_scans"] = int(state.get("settles_dead_scans") or 0) + 1
    elif reason == SETTLES_REASON_DEFERRED or (
        raw_empty and not settles_dead and not roads_closed and reason not in ("ok", "")
    ):
        kind = "deferred"
        state["settles_deferred_scans"] = int(state.get("settles_deferred_scans") or 0) + 1
    elif reason == "ok":
        state["settles_ok_scans"] = int(state.get("settles_ok_scans") or 0) + 1
        return None
    else:
        return None

    pid: Any = None
    try:
        pid = getattr(player, "id", None) if player is not None else None
        seat = str(pid) if pid is not None else "?"
    except Exception:
        pid = None
        seat = "?"

    if kind == "deferred":
        by = state.setdefault("settles_deferred_by_seat", {})
        if not isinstance(by, dict):
            by = {}
            state["settles_deferred_by_seat"] = by
        by[seat] = int(by.get(seat) or 0) + 1
        ever = state.setdefault("seats_ever_deferred", set())
        if isinstance(ever, set):
            ever.add(seat)
    else:
        by = state.setdefault("settles_dead_by_seat", {})
        if not isinstance(by, dict):
            by = {}
            state["settles_dead_by_seat"] = by
        by[seat] = int(by.get(seat) or 0) + 1
        ever = state.setdefault("seats_ever_dead", set())
        if isinstance(ever, set):
            ever.add(seat)

    key = (seat, kind, reason)
    seen = state.setdefault("seen_keys", set())
    if not isinstance(seen, set):
        seen = set()
        state["seen_keys"] = seen
    if key in seen:
        return None
    seen.add(key)

    record = {
        "event": "expansion_settles_dig",
        "kind": kind,  # deferred | dead
        "player_id": pid if seat != "?" else None,
        "round": payload.get("round"),
        "turn": payload.get("turn"),
        "settles_reason": reason,
        "settles_raw_empty": raw_empty,
        "roads_closed": roads_closed,
        "roads_expand": bool(payload.get("roads_expand")),
        "settles_expand": settles_dead,
        "n_legal_roads": payload.get("n_legal_roads"),
        "n_legal_settles": payload.get("n_legal_settles"),
        "impl_id": S5B_G6_IMPL_ID,
    }
    events = state.setdefault("events", [])
    if isinstance(events, list) and len(events) < MAX_EXPANSION_SETTLES_DIG_EVENTS:
        events.append(dict(record))
    return record


def collect_expansion_settles_dig_summary(game: Any) -> Dict[str, Any]:
    """Export S5b G6 KPIs for result.json / batch dig."""
    empty = {
        "settles_deferred_scans": 0,
        "settles_dead_scans": 0,
        "settles_ok_scans": 0,
        "settles_deferred_by_seat": {},
        "settles_dead_by_seat": {},
        "seats_ever_deferred": [],
        "seats_ever_dead": [],
        "seats_ever_deferred_count": 0,
        "seats_ever_dead_count": 0,
        "settles_deferred_events": [],
        "settles_dead_events": [],
        "expansion_settles_dig_events": [],
        "expansion_settles_dig_truncated": False,
        "s5b_g6_impl_id": S5B_G6_IMPL_ID,
    }
    if game is None:
        return empty
    state = getattr(game, "expansion_settles_dig_state", None)
    if not isinstance(state, Mapping):
        return empty
    events = (
        list(state.get("events") or [])
        if isinstance(state.get("events"), list)
        else []
    )
    deferred_ev = [e for e in events if isinstance(e, Mapping) and e.get("kind") == "deferred"]
    dead_ev = [e for e in events if isinstance(e, Mapping) and e.get("kind") == "dead"]
    ever_def = state.get("seats_ever_deferred") or set()
    ever_dead = state.get("seats_ever_dead") or set()
    if isinstance(ever_def, set):
        ever_def_list = sorted(str(x) for x in ever_def)
    else:
        ever_def_list = sorted(str(x) for x in list(ever_def or []))
    if isinstance(ever_dead, set):
        ever_dead_list = sorted(str(x) for x in ever_dead)
    else:
        ever_dead_list = sorted(str(x) for x in list(ever_dead or []))
    def_scans = int(state.get("settles_deferred_scans") or 0)
    dead_scans = int(state.get("settles_dead_scans") or 0)
    truncated = (def_scans + dead_scans) > 0 and len(events) >= MAX_EXPANSION_SETTLES_DIG_EVENTS
    def_by = (
        dict(state.get("settles_deferred_by_seat") or {})
        if isinstance(state.get("settles_deferred_by_seat"), Mapping)
        else {}
    )
    dead_by = (
        dict(state.get("settles_dead_by_seat") or {})
        if isinstance(state.get("settles_dead_by_seat"), Mapping)
        else {}
    )
    return {
        "settles_deferred_scans": def_scans,
        "settles_dead_scans": dead_scans,
        "settles_ok_scans": int(state.get("settles_ok_scans") or 0),
        "settles_deferred_by_seat": {str(k): int(v) for k, v in def_by.items()},
        "settles_dead_by_seat": {str(k): int(v) for k, v in dead_by.items()},
        "seats_ever_deferred": ever_def_list,
        "seats_ever_dead": ever_dead_list,
        "seats_ever_deferred_count": len(ever_def_list),
        "seats_ever_dead_count": len(ever_dead_list),
        "settles_deferred_events": deferred_ev,
        "settles_dead_events": dead_ev,
        "expansion_settles_dig_events": events,
        "expansion_settles_dig_truncated": bool(truncated),
        "s5b_g6_impl_id": S5B_G6_IMPL_ID,
    }


def public_dcard_deck_remaining(game: Any) -> Optional[int]:
    """Public count of cards left in the DCard bank stack (length only, not types).

    Fair-play: never inspect which cards remain — only whether the stack is empty.
    """
    if game is None:
        return None
    for attr in ("dcards_stack", "development_card_deck", "dcard_deck"):
        try:
            stack = getattr(game, attr, None)
            if isinstance(stack, (list, tuple)):
                return len(stack)
            if isinstance(stack, int):
                return max(0, int(stack))
        except Exception:
            continue
    try:
        n = getattr(game, "development_cards_remaining", None)
        if n is not None:
            return max(0, int(n))
    except Exception:
        pass
    return None


def _player_held_vp_cards(player: Any) -> int:
    """Own-seat VP development cards (AI knows own hand; not opponent dig)."""
    if player is None:
        return 0
    try:
        from core.victory import count_vp_development_cards

        return max(0, int(count_vp_development_cards(player) or 0))
    except Exception:
        pass
    try:
        n = 0
        for card in list(getattr(player, "development_cards", None) or []):
            if str(card).lower() in ("victory_point", "vp", "victory point"):
                n += 1
        if n:
            return n
    except Exception:
        pass
    try:
        for row in list(getattr(player, "dcard_summary", None) or []):
            if not row:
                continue
            if str(row[0]).lower() in ("victory_point", "vp", "victory point"):
                # summary often [type, new, playable, revealed]
                if len(row) >= 4:
                    n = max(n, int(row[3] or 0) + int(row[1] or 0) + int(row[2] or 0))
                else:
                    n += 1
        return max(0, n)
    except Exception:
        return 0


def _preferred_way_vp_card_need(player: Any) -> int:
    """Victory-point *card* count required by sticky/preferred Victory-Way (0 if unknown)."""
    wid = _direction_way_id(player)
    if wid is None or wid <= 0:
        return 0
    s = _load_strategy(int(wid))
    if s is None:
        return 0
    return max(0, int(getattr(s, "victory_point_cards", 0) or 0))


def detect_vp_dcards_dead(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """S6: fair-play VP-DCard component death.

    Dead when:
      - DCard deck stack length is **0** (public empty — cannot buy), or
      - preferred/sticky way's VP-card need is already met by **own** held VPs.

    Never uses remaining deck *composition* (which cards are left).
    """
    out: Dict[str, Any] = {
        "s6": True,
        "impl_id": S6_IMPL_ID,
        "vp_dcards_dead": False,
        "reason": "",
        "deck_remaining": None,
        "held_vp_cards": 0,
        "way_vp_need": 0,
        "way_id": _direction_way_id(player),
    }
    deck_n = public_dcard_deck_remaining(game)
    out["deck_remaining"] = deck_n
    held = _player_held_vp_cards(player)
    out["held_vp_cards"] = held
    need = _preferred_way_vp_card_need(player)
    out["way_vp_need"] = need

    if deck_n is not None and int(deck_n) <= 0:
        out["vp_dcards_dead"] = True
        out["reason"] = "deck_empty"
        return out
    if need > 0 and held >= need:
        out["vp_dcards_dead"] = True
        out["reason"] = "vp_need_already_met"
        return out
    if deck_n is None:
        out["reason"] = "deck_unknown"
    else:
        out["reason"] = "ok"
    return out


def update_player_vp_dcards_dead(
    game: Any,
    player: Any,
    *,
    force_scan: bool = True,
) -> Dict[str, Any]:
    """Detect and store ``player.vp_dcards_dead_components`` snapshot."""
    if not force_scan:
        raw = getattr(player, "vp_dcards_dead_components", None) if player else None
        return dict(raw) if isinstance(raw, Mapping) else {}

    det = detect_vp_dcards_dead(game, player)
    payload = {
        "vp_dcards": bool(det.get("vp_dcards_dead")),
        "reason": det.get("reason"),
        "deck_remaining": det.get("deck_remaining"),
        "held_vp_cards": det.get("held_vp_cards"),
        "way_vp_need": det.get("way_vp_need"),
        "way_id": det.get("way_id"),
        "round": getattr(game, "round", None) if game is not None else None,
        "turn": getattr(game, "turn", None) if game is not None else None,
        "impl_id": S6_IMPL_ID,
    }
    if player is not None:
        try:
            player.vp_dcards_dead_components = dict(payload)
        except Exception:
            pass
    if game is not None:
        try:
            game.last_vp_dcards_dead = dict(payload)
            game.last_vp_dcards_dead_player_id = getattr(player, "id", None)
        except Exception:
            pass
    return payload


def collect_all_dead_components(
    player: Any = None,
    game: Any = None,
    *,
    refresh_expansion: bool = False,
    refresh_vp_dcards: bool = False,
) -> Set[str]:
    """Union of specials-dead episode + expansion (S5) + VP DCards (S6)."""
    dead = dead_components_from_specials_episode(player)
    if refresh_expansion and game is not None and player is not None:
        update_player_expansion_dead(game, player)
    if refresh_vp_dcards and game is not None and player is not None:
        update_player_vp_dcards_dead(game, player)
    exp = getattr(player, "expansion_dead_components", None) if player is not None else None
    if isinstance(exp, Mapping):
        if exp.get("roads_expand"):
            dead.add(COMPONENT_ROADS_EXPAND)
            # Path length cannot grow → LR ambition is also dead for salvage
            dead.add(COMPONENT_LR)
        if exp.get("settles_expand"):
            dead.add(COMPONENT_SETTLES_EXPAND)
    vp = getattr(player, "vp_dcards_dead_components", None) if player is not None else None
    if isinstance(vp, Mapping) and vp.get("vp_dcards"):
        dead.add(COMPONENT_VP_DCARDS)
    return dead


def collect_nonspecial_way_ids(
    dead_set: Any,
    *,
    limit: int = DEFAULT_T1_EXPAND_N,
    abstract_turns_by_way: Optional[Mapping[Any, Any]] = None,
    exclude_way_ids: Optional[Sequence[Any]] = None,
) -> List[int]:
    """Top-N Victory-Ways that avoid all currently dead components (T1 expand).

    Used for T1 eval-set expansion. Does not strip residual (that is T2 / S3).
    """
    dead = normalize_dead_components(dead_set)
    if not dead:
        return []
    lim = max(0, min(20, int(limit or 0)))
    if lim <= 0:
        return []
    exclude: Set[int] = set()
    for x in list(exclude_way_ids or []):
        try:
            xi = int(x)
            if xi > 0:
                exclude.add(xi)
        except Exception:
            continue
    abs_map = dict(abstract_turns_by_way or {})
    scored: List[Tuple[float, int]] = []
    try:
        from core.strategy_timing import load_strategy_requirements

        strategies = list(load_strategy_requirements() or [])
    except Exception:
        strategies = []
    for s in strategies:
        try:
            wid = int(getattr(s, "way_id", -1))
        except Exception:
            continue
        if wid <= 0 or wid in exclude:
            continue
        if strategy_needs_dead_component(s, dead):
            continue
        turns = abs_map.get(wid)
        if turns is None:
            turns = abs_map.get(str(wid))
        if turns is not None:
            score = _safe_float(turns, INFINITE_TURNS)
        else:
            # Prefer lighter residual packages when no abstract ETA
            score = _safe_float(
                getattr(s, "article_min_cost", None),
                float(sum(getattr(s, "calculated_need", (0, 0, 0, 0, 0)) or (0,))),
            )
        scored.append((score, wid))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [wid for _sc, wid in scored[:lim]]


def expand_eval_way_ids_for_salvage_t1(
    way_ids: Sequence[Any],
    player: Any = None,
    game: Any = None,
    *,
    dead_set: Any = None,
    abstract_turns_by_way: Optional[Mapping[Any, Any]] = None,
    max_extra: Optional[int] = None,
    force: bool = False,
) -> Tuple[List[int], Dict[str, Any]]:
    """Append ways that avoid dead components when specials/expansion death active.

    Returns ``(expanded_ids, meta)``. Idempotent on already-present ids.
    """
    base: List[int] = []
    seen: Set[int] = set()
    for raw in list(way_ids or []):
        try:
            wid = int(raw)
        except Exception:
            continue
        if wid <= 0 or wid in seen:
            continue
        seen.add(wid)
        base.append(wid)

    meta: Dict[str, Any] = {
        "s2": True,
        "impl_id": S2_IMPL_ID,
        "expanded": False,
        "n_before": len(base),
        "n_after": len(base),
        "n_added": 0,
        "added_way_ids": [],
        "dead_components": [],
        "reason": "init",
    }

    if not force and not is_salvage_t1_expand_enabled():
        meta["reason"] = "expand_disabled"
        return base, meta

    dead = normalize_dead_components(dead_set)
    if not dead and player is not None:
        dead = collect_all_dead_components(player, game)
    meta["dead_components"] = sorted(dead)
    if not dead:
        meta["reason"] = "no_dead_components"
        return base, meta

    extra_n = int(max_extra) if max_extra is not None else t1_expand_n()
    if extra_n <= 0:
        meta["reason"] = "expand_n_zero"
        return base, meta

    # Already have enough ways that avoid dead components?
    ok_in_base = 0
    for wid in base:
        if way_avoids_dead_specials(wid, dead):
            ok_in_base += 1
    if ok_in_base >= extra_n:
        meta["reason"] = "already_enough_nonspecial"
        meta["nonspecial_in_base"] = ok_in_base
        return base, meta

    need = max(0, extra_n - ok_in_base)
    candidates = collect_nonspecial_way_ids(
        dead,
        limit=need + 4,  # small overfetch then filter exclude
        abstract_turns_by_way=abstract_turns_by_way,
        exclude_way_ids=base,
    )
    added: List[int] = []
    for wid in candidates:
        if wid in seen:
            continue
        seen.add(wid)
        base.append(wid)
        added.append(wid)
        if len(added) >= need:
            break

    meta["expanded"] = bool(added)
    meta["n_after"] = len(base)
    meta["n_added"] = len(added)
    meta["added_way_ids"] = list(added)
    meta["nonspecial_in_base"] = ok_in_base
    meta["reason"] = "expanded" if added else "no_candidates"
    return base, meta


def filter_audits_for_dead_components(
    audits: Sequence[Any],
    dead_set: Any,
    *,
    player: Any = None,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Hard-filter audits that still need dead components; soft-demote if empty.

    Parallel to specials_dead hard/soft modes for S3 tier selection.
    """
    dead = normalize_dead_components(dead_set)
    if not dead and player is not None:
        dead = collect_all_dead_components(player)
    src = list(audits or [])
    meta: Dict[str, Any] = {
        "applied": False,
        "mode": "none",
        "dead_components": sorted(dead),
        "n_before": len(src),
        "n_after": len(src),
        "reason": "no_dead",
        "kill_lr": COMPONENT_LR in dead,
        "kill_la": COMPONENT_LA in dead,
    }
    if not src or not dead:
        return src, meta

    kept: List[Any] = []
    for a in src:
        wid = None
        try:
            if isinstance(a, Mapping):
                wid = int(a.get("way_id") or 0)
            else:
                wid = int(getattr(a, "way_id", 0) or 0)
        except Exception:
            wid = None
        if wid and way_avoids_dead_specials(wid, dead):
            kept.append(a)

    if kept:
        meta.update(
            {
                "applied": True,
                "mode": "hard_filter",
                "n_after": len(kept),
                "reason": "filtered_non_dead",
            }
        )
        return kept, meta

    # Soft demote: keep original order (T2 residual will re-rank)
    meta.update(
        {
            "applied": True,
            "mode": "soft_demote",
            "n_after": len(src),
            "reason": "filter_empty_soft_demote",
        }
    )
    return src, meta


def normalize_dead_components(raw: Any) -> Set[str]:
    """Return a set of known component ids from a list/set/mapping."""
    out: Set[str] = set()
    if raw is None:
        return out
    if isinstance(raw, Mapping):
        for k, v in raw.items():
            key = str(k).strip()
            if key in ALL_COMPONENTS and v:
                out.add(key)
        return out
    if isinstance(raw, (list, tuple, set, frozenset)):
        for item in raw:
            key = str(item).strip()
            if key in ALL_COMPONENTS:
                out.add(key)
    return out


def dead_components_from_specials_episode(
    player: Any = None,
    *,
    episode: Optional[Mapping[str, Any]] = None,
) -> Set[str]:
    """Map specials-dead episode kill_la/kill_lr → component ids."""
    out: Set[str] = set()
    ep = episode
    if ep is None and player is not None:
        try:
            from core.specials_dead_episode import get_specials_dead_episode

            ep = get_specials_dead_episode(player)
        except Exception:
            ep = None
    if not isinstance(ep, Mapping) or not ep.get("active"):
        return out
    if ep.get("kill_lr"):
        out.add(COMPONENT_LR)
    if ep.get("kill_la"):
        out.add(COMPONENT_LA)
    return out


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        f = float(v)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _load_strategy(way_id: int, strategy: Any = None) -> Any:
    """Return StrategyRequirement for way_id."""
    if strategy is not None and int(getattr(strategy, "way_id", -1) or -1) == int(way_id):
        return strategy
    from core.strategy_timing import load_strategy_requirements

    for s in load_strategy_requirements() or []:
        try:
            if int(getattr(s, "way_id", -1)) == int(way_id):
                return s
        except Exception:
            continue
    return None


def strip_components_from_strategy(
    strategy: Any,
    dead_set: Any,
) -> Any:
    """Return a new ``StrategyRequirement`` with dead components removed.

    Pure transform — does not mutate ``strategy``.
    """
    from core.strategy_timing import (
        StrategyRequirement,
        expected_development_card_buys,
        strategy_cost_from_components,
    )

    if not isinstance(strategy, StrategyRequirement):
        raise TypeError("strip_components_from_strategy expects StrategyRequirement")

    dead = normalize_dead_components(dead_set)
    if not dead:
        return strategy

    longest_road = bool(strategy.longest_road) and COMPONENT_LR not in dead
    biggest_army = bool(strategy.biggest_army) and COMPONENT_LA not in dead

    vp_cards = max(0, int(strategy.victory_point_cards or 0))
    if COMPONENT_VP_DCARDS in dead:
        vp_cards = 0

    cities = max(0, int(strategy.cities or 0))
    city_upgrades = max(0, int(strategy.city_upgrades or 0))
    if COMPONENT_CITIES in dead:
        cities = 0
        city_upgrades = 0

    settlements = max(0, int(strategy.settlements or 0))
    new_settlements = max(0, int(strategy.new_settlements_to_build or 0))
    if COMPONENT_SETTLES_EXPAND in dead:
        new_settlements = 0

    roads = max(0, int(strategy.roads_to_build or 0))
    if COMPONENT_ROADS_EXPAND in dead:
        roads = 0
        # Expansion blocked: cannot pursue new remote settles via road plan
        # (local 0-road settle still possible in rules; residual count stays 0 for safety)

    # Rebuild expected DCard buys from residual specials only (fair model)
    if COMPONENT_LA in dead or COMPONENT_VP_DCARDS in dead or not (biggest_army or vp_cards):
        listed = 0
    else:
        listed = 0
    dc_buys = expected_development_card_buys(
        victory_point_cards=vp_cards,
        largest_army=biggest_army,
        listed_development_cards=listed,
    )

    calculated = strategy_cost_from_components(
        new_settlements=new_settlements,
        city_upgrades=city_upgrades,
        roads=roads,
        dev_cards=dc_buys,
    )

    total_vp = max(0, int(strategy.total_victory_points or 0))
    if COMPONENT_LR in dead and bool(strategy.longest_road):
        total_vp = max(0, total_vp - 2)
    if COMPONENT_LA in dead and bool(strategy.biggest_army):
        total_vp = max(0, total_vp - 2)
    if COMPONENT_VP_DCARDS in dead:
        total_vp = max(0, total_vp - max(0, int(strategy.victory_point_cards or 0)))

    warn = list(strategy.validation_warnings or ())
    warn.append(f"salvage_strip:{','.join(sorted(dead))}")

    buildings = max(0, int(strategy.buildings or 0))
    if COMPONENT_CITIES in dead or COMPONENT_SETTLES_EXPAND in dead:
        # Target buildings = residual cities + settlements targets
        buildings = max(0, cities + settlements)

    return replace(
        strategy,
        longest_road=longest_road,
        biggest_army=biggest_army,
        victory_point_cards=vp_cards,
        cities=cities,
        settlements=settlements,
        city_upgrades=city_upgrades,
        new_settlements_to_build=new_settlements,
        roads_to_build=roads,
        development_cards_to_buy=dc_buys,
        calculated_need=calculated,
        static_need=calculated,
        total_victory_points=total_vp,
        buildings=buildings,
        validation_warnings=tuple(warn),
    )


def strip_components(
    req: Any,
    dead_set: Any,
) -> Any:
    """Strip dead components from a strategy or requirement-like mapping.

    - ``StrategyRequirement`` → new ``StrategyRequirement``
    - ``Mapping`` → new ``dict`` with residual fields (for dig / lightweight use)
    """
    from core.strategy_timing import StrategyRequirement

    dead = normalize_dead_components(dead_set)
    if isinstance(req, StrategyRequirement):
        return strip_components_from_strategy(req, dead)

    if isinstance(req, Mapping):
        d = dict(req)
        if COMPONENT_LR in dead:
            d["longest_road"] = False
            d["longest_route"] = False
        if COMPONENT_LA in dead:
            d["biggest_army"] = False
            d["largest_army"] = False
        if COMPONENT_VP_DCARDS in dead:
            d["victory_point_cards"] = 0
        if COMPONENT_CITIES in dead:
            d["cities"] = 0
            d["city_upgrades"] = 0
            d["required_cities"] = 0
        if COMPONENT_SETTLES_EXPAND in dead:
            d["new_settlements_to_build"] = 0
            d["required_new_intersections"] = 0
        if COMPONENT_ROADS_EXPAND in dead:
            d["roads_to_build"] = 0
            d["required_roads_min"] = 0
        d["ignored_components"] = sorted(dead)
        d["partial_plan"] = bool(dead)
        return d

    raise TypeError(f"strip_components unsupported type: {type(req)!r}")


def _feasibility_from_eta(
    eta: float,
    *,
    remaining_settles: int = 0,
    roads_expand_dead: bool = False,
) -> str:
    if roads_expand_dead and remaining_settles > 0:
        return "unrealistic"
    if eta >= INFINITE_TURNS / 2:
        return "unrealistic"
    if eta >= 40:
        return "medium"
    if eta >= 25:
        return "medium"
    return "high"


def _rank_key_residual(eta: float, feasibility: str) -> float:
    feas_pen = {
        "high": 0.0,
        "medium": 1.5,
        "fragile": 4.0,
        "low": 3.0,
        "unrealistic": 50.0,
        "impossible": 100.0,
    }.get(str(feasibility).lower(), 2.0)
    return float(eta) + float(feas_pen)


def rescore_way_residual(
    way_id: int,
    dead_set: Any = None,
    *,
    player: Any = None,
    game: Any = None,
    player_state: Any = None,
    strategy: Any = None,
    num_players: Optional[int] = None,
) -> Dict[str, Any]:
    """Strip dead components from a Victory-Way and estimate residual own-turns.

    Returns a dig-friendly dict (does not mutate game/player).

    Without ``player`` / ``player_state``, uses empty hand and zero pips → ETA
    may be infinite; still returns stripped remaining counts from static strategy.
    """
    dead = normalize_dead_components(dead_set)
    wid = int(way_id)
    base = _load_strategy(wid, strategy=strategy)
    out: Dict[str, Any] = {
        "s1": True,
        "impl_id": S1_IMPL_ID,
        "way_id": wid,
        "dead_components": sorted(dead),
        "ok": False,
        "partial_plan": bool(dead),
        "ignored_components": sorted(dead),
        "template_way_id": wid,
        "eta": INFINITE_TURNS,
        "turns": INFINITE_TURNS,
        "feasibility": "unrealistic",
        "rank_key": INFINITE_TURNS,
        "error": "",
    }
    if base is None:
        out["error"] = "way_not_found"
        return out

    try:
        stripped = strip_components_from_strategy(base, dead)
    except Exception as exc:
        out["error"] = f"strip_error:{exc}"
        return out

    out["stripped_summary"] = {
        "longest_road": bool(stripped.longest_road),
        "biggest_army": bool(stripped.biggest_army),
        "cities": int(stripped.cities),
        "settlements": int(stripped.settlements),
        "victory_point_cards": int(stripped.victory_point_cards),
        "new_settlements_to_build": int(stripped.new_settlements_to_build),
        "city_upgrades": int(stripped.city_upgrades),
        "roads_to_build": int(stripped.roads_to_build),
        "development_cards_to_buy": int(stripped.development_cards_to_buy),
        "total_victory_points": int(stripped.total_victory_points),
        "calculated_need": tuple(stripped.calculated_need),
        "tags": list(stripped.tags),
    }

    # Resolve player state
    ps = player_state
    if ps is None and player is not None:
        try:
            from core.strategy_timing import build_player_strategy_state

            board = getattr(game, "board", None) if game is not None else None
            if board is None and game is not None:
                board = game
            if board is not None:
                ps = build_player_strategy_state(board, player)
        except Exception as exc:
            out["player_state_error"] = str(exc)
            ps = None

    from core.strategy_timing import calculate_remaining_need, estimate_resource_requirement_time

    if ps is not None:
        remaining = calculate_remaining_need(stripped, ps)
        need = tuple(remaining.need_vector)
        out["remaining"] = remaining.as_dict()
        n_players = int(num_players or 0)
        if n_players <= 0 and game is not None:
            try:
                n_players = max(1, len(list(getattr(game, "players", []) or [])))
            except Exception:
                n_players = 4
        if n_players <= 0:
            n_players = 4
        try:
            est = estimate_resource_requirement_time(
                current_hand=ps.current_hand,
                production_pips=ps.production_pips,
                need=need,
                trade_rates=ps.trade_rates,
                num_players=n_players,
            )
            eta = _safe_float(est.get("turns", est.get("expected_turns")), INFINITE_TURNS)
            if not bool(est.get("found", True)) and eta <= 0:
                eta = INFINITE_TURNS
            out["estimate"] = {
                "turns": eta,
                "found": est.get("found"),
                "confidence": est.get("confidence"),
                "estimator": est.get("estimator"),
            }
        except Exception as exc:
            eta = INFINITE_TURNS
            out["estimate_error"] = str(exc)
    else:
        # Static residual (no player): remaining = full stripped component counts
        need = tuple(stripped.calculated_need)
        out["remaining"] = {
            "way_id": wid,
            "remaining_new_settlements": int(stripped.new_settlements_to_build),
            "remaining_city_upgrades": int(stripped.city_upgrades),
            "remaining_roads_to_build": int(stripped.roads_to_build),
            "remaining_dev_cards_to_buy": int(stripped.development_cards_to_buy),
            "need_vector": need,
            "total_cards": float(sum(need)),
            "static_only": True,
        }
        # Without production, cannot pay unless need is zero
        eta = 0.0 if sum(need) <= 1e-9 else INFINITE_TURNS
        out["estimate"] = {
            "turns": eta,
            "found": sum(need) <= 1e-9,
            "static_only": True,
        }

    rem_settles = int((out.get("remaining") or {}).get("remaining_new_settlements") or 0)
    feas = _feasibility_from_eta(
        eta,
        remaining_settles=rem_settles,
        roads_expand_dead=COMPONENT_ROADS_EXPAND in dead,
    )
    # Empty residual (nothing left to build) → already "done" residual
    if sum(need) <= 1e-9:
        eta = 0.0
        feas = "high"

    out["eta"] = float(eta)
    out["turns"] = float(eta)
    out["feasibility"] = feas
    out["rank_key"] = _rank_key_residual(float(eta), feas)
    out["ok"] = True
    out["error"] = ""
    return out


def _audit_way_id(audit: Any) -> Optional[int]:
    try:
        if isinstance(audit, Mapping):
            for k in ("way_id", "preferred_way_id", "locked_way_id"):
                if audit.get(k) is not None and audit.get(k) != "":
                    return int(float(audit.get(k)))
        else:
            wid = getattr(audit, "way_id", None)
            if wid is not None and wid != "":
                return int(float(wid))
    except Exception:
        return None
    return None


def pick_salvage_t2_winner(
    audits: Sequence[Any],
    player: Any = None,
    game: Any = None,
    *,
    dead_set: Any = None,
    max_candidates: int = 12,
) -> Tuple[Any, Dict[str, Any]]:
    """T2: among audits that need dead specials, pick best residual ETA.

    Returns ``(winner_audit_or_None, meta)``. Pure ranking — caller force-adopts.
    """
    dead = normalize_dead_components(dead_set)
    if not dead and player is not None:
        dead = collect_all_dead_components(player, game)

    meta: Dict[str, Any] = {
        "s3": True,
        "impl_id": S3_IMPL_ID,
        "salvage_mode": SALVAGE_T2,
        "tier": "t2",
        "dead_components": sorted(dead),
        "picked": False,
        "winner_way_id": None,
        "residual_eta": None,
        "residual_rank_key": None,
        "n_scored": 0,
        "top3": [],
        "reason": "init",
        "partial_plan": True,
        "ignored_components": sorted(dead),
    }
    if not dead:
        meta["reason"] = "no_dead_components"
        return None, meta
    if not is_salvage_t2_enabled():
        meta["reason"] = "t2_disabled"
        return None, meta

    src = list(audits or [])
    scored: List[Tuple[float, float, int, Any, Dict[str, Any]]] = []
    seen: Set[int] = set()
    for audit in src:
        if len(scored) >= max(1, int(max_candidates)):
            break
        wid = _audit_way_id(audit)
        if wid is None or wid <= 0 or wid in seen:
            continue
        seen.add(wid)
        # T2 templates: ways that still "want" a dead component (full package)
        if way_avoids_dead_specials(wid, dead):
            continue
        try:
            residual = rescore_way_residual(
                wid, dead, player=player, game=game
            )
        except Exception as exc:
            residual = {"ok": False, "error": str(exc), "rank_key": INFINITE_TURNS}
        if not residual.get("ok"):
            continue
        rk = _safe_float(residual.get("rank_key"), INFINITE_TURNS)
        eta = _safe_float(residual.get("eta"), INFINITE_TURNS)
        feas = str(residual.get("feasibility") or "")
        if feas == "impossible":
            continue
        scored.append((rk, eta, wid, audit, residual))

    # If audits empty of dead-component ways, try table templates that need them
    if not scored:
        try:
            from core.strategy_timing import load_strategy_requirements

            templates: List[int] = []
            for s in load_strategy_requirements() or []:
                if strategy_needs_dead_component(s, dead):
                    templates.append(int(s.way_id))
                if len(templates) >= max_candidates:
                    break
            for wid in templates:
                if wid in seen:
                    continue
                residual = rescore_way_residual(
                    wid, dead, player=player, game=game
                )
                if not residual.get("ok"):
                    continue
                if str(residual.get("feasibility") or "") == "impossible":
                    continue
                rk = _safe_float(residual.get("rank_key"), INFINITE_TURNS)
                eta = _safe_float(residual.get("eta"), INFINITE_TURNS)
                # Synthetic audit-like mapping if no board audit
                synth = {
                    "way_id": wid,
                    "rank_key": rk,
                    "board_expected_turns": eta,
                    "realistic_expected_turns": eta,
                    "feasibility": residual.get("feasibility"),
                    "salvage_t2_synthetic": True,
                }
                scored.append((rk, eta, wid, synth, residual))
                if len(scored) >= max_candidates:
                    break
        except Exception as exc:
            meta["template_error"] = str(exc)

    meta["n_scored"] = len(scored)
    if not scored:
        meta["reason"] = "no_t2_candidates"
        return None, meta

    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    meta["top3"] = [
        {
            "way_id": t[2],
            "eta": t[1],
            "rank_key": t[0],
            "feasibility": (t[4] or {}).get("feasibility"),
        }
        for t in scored[:3]
    ]
    best_rk, best_eta, best_wid, best_audit, best_res = scored[0]
    meta["picked"] = True
    meta["winner_way_id"] = best_wid
    meta["residual_eta"] = best_eta
    meta["residual_rank_key"] = best_rk
    meta["residual"] = {
        "feasibility": best_res.get("feasibility"),
        "remaining": best_res.get("remaining"),
        "stripped_summary": best_res.get("stripped_summary"),
    }
    meta["reason"] = "t2_residual_pick"
    meta["synthetic"] = bool(
        isinstance(best_audit, Mapping) and best_audit.get("salvage_t2_synthetic")
    )
    return best_audit, meta


def apply_salvage_tier_to_audits(
    audits: Sequence[Any],
    player: Any = None,
    game: Any = None,
    *,
    specials_dead_meta: Optional[Mapping[str, Any]] = None,
    dead_set: Any = None,
) -> Tuple[List[Any], Dict[str, Any]]:
    """After specials-dead filter: tag T1 or run T2 residual reorder.

    Returns ``(audits_out, salvage_meta)``.
    """
    src = list(audits or [])
    meta: Dict[str, Any] = {
        "s3": True,
        "impl_id": S3_IMPL_ID,
        "salvage_mode": None,
        "tier": None,
        "applied": False,
        "reason": "init",
    }
    sde = dict(specials_dead_meta or {})
    if not sde.get("applied"):
        meta["reason"] = "no_specials_dead_filter"
        return src, meta

    dead = normalize_dead_components(dead_set)
    if not dead and player is not None:
        dead = collect_all_dead_components(player, game)
    mode = str(sde.get("mode") or "")

    # T1: hard filter already preferred ways avoiding dead components
    if mode == "hard_filter":
        # Expansion-only death still counts as partial (no specials flags)
        partial = bool(
            dead
            & {
                COMPONENT_ROADS_EXPAND,
                COMPONENT_SETTLES_EXPAND,
                COMPONENT_CITIES,
                COMPONENT_VP_DCARDS,
            }
        )
        meta.update(
            {
                "applied": True,
                "salvage_mode": SALVAGE_T1,
                "tier": "t1",
                "reason": "t1_hard_filter",
                "dead_components": sorted(dead),
                "ignored_components": sorted(dead),
                "partial_plan": partial,
                "winner_way_id": _audit_way_id(src[0]) if src else None,
                "n_audits": len(src),
            }
        )
        return src, meta

    # T2: soft demote / empty hard filter — residual rank specials templates
    if mode == "soft_demote" or "soft" in mode:
        if not is_salvage_t2_enabled():
            meta["reason"] = "t2_disabled"
            return src, meta
        winner, t2 = pick_salvage_t2_winner(
            src, player, game, dead_set=dead
        )
        if not t2.get("picked") or winner is None:
            meta.update(t2)
            meta["applied"] = False
            meta["salvage_mode"] = SALVAGE_T2
            meta["tier"] = "t2"
            meta["reason"] = t2.get("reason") or "t2_no_pick"
            return src, meta
        # Put winner first
        win_id = _audit_way_id(winner)
        rest = [
            a
            for a in src
            if _audit_way_id(a) != win_id
        ]
        # If synthetic mapping, keep as head of list for direction builder
        out = [winner] + rest
        meta = dict(t2)
        meta["applied"] = True
        meta["n_audits"] = len(out)
        return out, meta

    meta["reason"] = f"unhandled_filter_mode:{mode}"
    return src, meta


def patch_direction_for_salvage(
    direction: Mapping[str, Any],
    salvage_meta: Mapping[str, Any],
    *,
    dead_set: Any = None,
) -> Dict[str, Any]:
    """Stamp direction with partial-plan / ignored specials for T1/T2 (S3+S4)."""
    d = dict(direction or {})
    meta = dict(salvage_meta or {})
    if not meta.get("applied") and not meta.get("picked"):
        return d
    dead = normalize_dead_components(
        dead_set if dead_set is not None else meta.get("dead_components")
    )
    tier = str(meta.get("tier") or "")
    d["salvage_mode"] = meta.get("salvage_mode")
    d["salvage_tier"] = tier
    d["salvage"] = {
        k: meta.get(k)
        for k in (
            "impl_id",
            "tier",
            "salvage_mode",
            "winner_way_id",
            "residual_eta",
            "reason",
            "dead_components",
        )
    }
    # S4: always stamp ignored set; partial_plan when T2 or any specials stripped
    specials_dead = bool(dead & {COMPONENT_LR, COMPONENT_LA})
    force_partial = bool(
        tier == "t2" or meta.get("partial_plan") or specials_dead
    )
    if dead:
        d = stamp_partial_plan_fields(d, dead, force_partial=force_partial)
        d["s4_impl_id"] = S4_IMPL_ID
    if tier == "t2" or meta.get("partial_plan") or (force_partial and specials_dead):
        d["partial_plan"] = True
        d["preference_source"] = (
            str(d.get("preference_source") or "") + "+salvage_t2"
            if tier == "t2" or meta.get("partial_plan")
            else str(d.get("preference_source") or "") + "+salvage_partial_s4"
        ).lstrip("+")
    elif tier == "t1":
        # Full non-special way — not a residual strip unless specials were ignored
        if not force_partial:
            d["partial_plan"] = False
        d["preference_source"] = (
            str(d.get("preference_source") or "") + "+salvage_t1"
        ).lstrip("+")
    return d


def _direction_way_id(player: Any) -> Optional[int]:
    try:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            w = sticky.get("locked_way_id")
            if w is not None and int(w) > 0:
                return int(w)
    except Exception:
        pass
    try:
        d = getattr(player, "strategic_direction", None)
        if isinstance(d, Mapping):
            w = d.get("preferred_way_id") or d.get("way_id")
            if w is not None and int(w) > 0:
                return int(w)
    except Exception:
        pass
    return None


# ── S4: sticky / BA partial_plan + bounce guard ───────────────────────────────


def collect_ignored_components_for_player(
    player: Any = None,
    game: Any = None,
) -> Set[str]:
    """Union of dead components for sticky/BA (episode + expansion + VP + stamps)."""
    dead = set(collect_all_dead_components(player, game))
    if player is None:
        return dead
    for attr in ("strategic_direction", "sticky_commitment"):
        try:
            raw = getattr(player, attr, None)
            if isinstance(raw, Mapping):
                for c in list(raw.get("ignored_components") or []):
                    n = normalize_dead_components([c])
                    dead |= n
        except Exception:
            pass
    return dead


def stamp_partial_plan_fields(
    mapping: Any,
    ignored: Any,
    *,
    force_partial: bool = True,
) -> Dict[str, Any]:
    """Write ``partial_plan`` + ``ignored_components``; strip dead special flags."""
    d = dict(mapping or {}) if isinstance(mapping, Mapping) else {}
    dead = normalize_dead_components(ignored)
    if dead:
        d["ignored_components"] = sorted(dead)
    if force_partial and dead:
        d["partial_plan"] = True
    if COMPONENT_LR in dead:
        d["longest_road"] = False
        d["longest_route"] = False
        try:
            d.pop("lr_project", None)
        except Exception:
            pass
    if COMPONENT_LA in dead:
        d["biggest_army"] = False
        d["largest_army"] = False
        try:
            d.pop("la_progress", None)
        except Exception:
            pass
    summary = d.get("strategy_summary")
    if isinstance(summary, dict) and dead:
        summary = dict(summary)
        if COMPONENT_LR in dead:
            summary["longest_road"] = False
        if COMPONENT_LA in dead:
            summary["largest_army"] = False
            summary["biggest_army"] = False
        d["strategy_summary"] = summary
    return d


def apply_s4_project_suppress(
    player: Any,
    game: Any = None,
    direction: Any = None,
    meta: Any = None,
) -> Dict[str, Any]:
    """Never re-arm LR/LA projects for ignored specials (S4 + WP3).

    Mutates ``direction`` (if mapping) and sticky LR/LA stores when components
    are ignored. Returns a dig meta dict.
    """
    out: Dict[str, Any] = {
        "s4": True,
        "impl_id": S4_IMPL_ID,
        "lr_suppressed": False,
        "la_suppressed": False,
        "ignored": [],
    }
    ignored = collect_ignored_components_for_player(player, game)
    out["ignored"] = sorted(ignored)
    if not ignored:
        return out

    if COMPONENT_LR in ignored:
        out["lr_suppressed"] = True
        try:
            from core.ai_lr_project import clear_lr_project_from_sticky

            clear_lr_project_from_sticky(player, game)
        except Exception:
            pass
        if isinstance(direction, dict):
            direction.pop("lr_project", None)
            direction["longest_road"] = False
            direction["longest_route"] = False
        if isinstance(meta, dict):
            meta["lr_suppressed_s4"] = True
            meta["lr_suppressed_specials_dead"] = True

    if COMPONENT_LA in ignored:
        out["la_suppressed"] = True
        try:
            from core.ai_la_progress import clear_la_progress_from_sticky

            clear_la_progress_from_sticky(player, game)
        except Exception:
            pass
        try:
            if player is not None:
                player.la_progress = None
        except Exception:
            pass
        if isinstance(direction, dict):
            direction["biggest_army"] = False
            direction["largest_army"] = False
            direction.pop("la_progress", None)
        if isinstance(meta, dict):
            meta["la_suppressed_s4"] = True
            meta["la_suppressed_specials_dead"] = True

    if isinstance(direction, dict) and ignored:
        stamped = stamp_partial_plan_fields(direction, ignored)
        direction.update(stamped)
    return out


def stamp_commitment_partial_plan(
    commitment: Any,
    direction: Any = None,
    player: Any = None,
    game: Any = None,
) -> Optional[Dict[str, Any]]:
    """Copy S4 partial_plan / ignored_components onto sticky commitment."""
    if not isinstance(commitment, dict):
        return None
    ignored = set()
    if isinstance(direction, Mapping):
        ignored |= normalize_dead_components(direction.get("ignored_components"))
        if direction.get("partial_plan"):
            commitment["partial_plan"] = True
    ignored |= collect_ignored_components_for_player(player, game)
    if ignored:
        commitment["ignored_components"] = sorted(ignored)
        commitment["partial_plan"] = True
        if COMPONENT_LR in ignored:
            commitment.pop("lr_project", None)
        if COMPONENT_LA in ignored:
            commitment.pop("la_progress", None)
        commitment["s4_impl_id"] = S4_IMPL_ID
    return commitment


def maybe_apply_s4_bounce_guard(
    game: Any,
    player: Any,
    *,
    reason: str = "",
) -> Optional[Dict[str, Any]]:
    """S4: detect post-escape LR/LA re-ambition and **harden** sticky/direction.

    When the seat had escaped dead specials (T1/T2 / partial_plan) then
    re-acquires LR/LA need while the specials-dead episode is still active:

      1. Stamp ``partial_plan`` + ``ignored_components`` on direction
      2. Suppress LR/LA projects
      3. Clear sticky if still locked on a dead-special way
      4. Log once per seat (``S4_APPLIED bounce_guard``)

    Returns the payload if a new guard was applied, else None.
    """
    if player is None:
        return None
    try:
        from core.specials_dead_episode import (
            commitment_blocked_by_episode,
            get_specials_dead_episode,
            is_giveup_escape_enabled,
        )
    except Exception:
        return None

    if not is_giveup_escape_enabled():
        return None

    ep = get_specials_dead_episode(player)
    if not ep.get("active"):
        return None
    kill_lr = bool(ep.get("kill_lr"))
    kill_la = bool(ep.get("kill_la"))
    if not kill_lr and not kill_la:
        return None

    needs_lr = False
    needs_la = False
    try:
        from core.la_lr_probe_log import resolve_needs_la, resolve_needs_lr

        if kill_lr:
            needs_lr, _ = resolve_needs_lr(player)
        if kill_la:
            needs_la, _ = resolve_needs_la(player)
    except Exception:
        wid = _direction_way_id(player)
        if wid is not None:
            try:
                from core.specials_dead_episode import way_id_needs_specials

                la, lr = way_id_needs_specials(wid)
                needs_lr = bool(kill_lr and lr)
                needs_la = bool(kill_la and la)
            except Exception:
                pass

    dead_need_now = (kill_lr and needs_lr) or (kill_la and needs_la)
    escaped_key = "_salvage_escaped_dead_special"
    applied_key = "_s4_bounce_guard_applied"

    # Mark escape seen when under episode and currently free of dead-special need
    if not dead_need_now:
        try:
            setattr(player, escaped_key, True)
        except Exception:
            pass
        try:
            d = getattr(player, "strategic_direction", None)
            if isinstance(d, Mapping) and (
                d.get("partial_plan")
                or str(d.get("salvage_tier") or "") in ("t1", "t2")
                or "salvage_t" in str(d.get("preference_source") or "")
            ):
                setattr(player, escaped_key, True)
        except Exception:
            pass
        return None

    if not bool(getattr(player, escaped_key, False)):
        return None
    if bool(getattr(player, applied_key, False)):
        return None

    wid = _direction_way_id(player)
    rnd = getattr(game, "round", None) if game is not None else None
    trn = getattr(game, "turn", None) if game is not None else None
    pid = getattr(player, "id", None)
    kinds: List[str] = []
    if kill_lr and needs_lr:
        kinds.append(COMPONENT_LR)
    if kill_la and needs_la:
        kinds.append(COMPONENT_LA)

    ignored = collect_ignored_components_for_player(player, game)
    ignored |= set(kinds)

    # Harden direction
    try:
        d = getattr(player, "strategic_direction", None)
        d = dict(d) if isinstance(d, Mapping) else {}
        d = stamp_partial_plan_fields(d, ignored, force_partial=True)
        d["preference_source"] = (
            str(d.get("preference_source") or "") + "+s4_bounce_guard"
        ).lstrip("+")
        d["s4_bounce_guard"] = True
        player.strategic_direction = d
    except Exception:
        d = {}

    suppress_meta: Dict[str, Any] = {}
    apply_s4_project_suppress(player, game, d if isinstance(d, dict) else None, suppress_meta)
    try:
        if isinstance(d, dict) and d:
            player.strategic_direction = dict(d)
    except Exception:
        pass

    sticky_cleared = False
    try:
        from core.strategy_sticky import clear_sticky_commitment, get_sticky_commitment

        sticky = get_sticky_commitment(player)
        blocked, why = commitment_blocked_by_episode(sticky, player)
        if blocked:
            clear_sticky_commitment(player)
            sticky_cleared = True
            suppress_meta["sticky_clear_why"] = why
        elif isinstance(sticky, Mapping) and sticky:
            # Still stamp partial on sticky if kept
            st = dict(sticky)
            stamp_commitment_partial_plan(st, d, player, game)
            try:
                from core.strategy_sticky import set_sticky_commitment

                set_sticky_commitment(player, st)
            except Exception:
                pass
    except Exception:
        pass

    payload = {
        "s4_needed": False,
        "s4_implemented": True,
        "s4_applied": True,
        "impl_id": S4_IMPL_ID,
        "player_id": pid,
        "round": rnd,
        "turn": trn,
        "way_id": wid,
        "dead_specials_returned": kinds,
        "ignored_components": sorted(ignored),
        "sticky_cleared": sticky_cleared,
        "episode_source": ep.get("source"),
        "reason": str(reason or "strategy_refresh")[:80],
        "hint": (
            "S4 bounce-guard: partial_plan + ignored_components hardened; "
            "dead special projects suppressed"
        ),
        "suppress": suppress_meta,
    }
    try:
        setattr(player, applied_key, True)
        # legacy key so old tests/attributes still see one-shot
        setattr(player, "_s4_reminder_emitted", True)
        setattr(player, "last_s4_reminder", dict(payload))
        setattr(player, "last_s4_applied", dict(payload))
    except Exception:
        pass
    if game is not None:
        try:
            n = int(getattr(game, "s4_applied_count", 0) or 0) + 1
            game.s4_applied_count = n
            game.s4_reminder_count = n  # dig alias
            game.last_s4_reminder = dict(payload)
            game.last_s4_applied = dict(payload)
        except Exception:
            pass

    line = (
        f"S4_APPLIED bounce_guard: P{pid} r{rnd}t{trn} way={wid} "
        f"re-acquired dead special(s) {kinds} after salvage escape "
        f"[episode={ep.get('source') or '?'}]; "
        f"partial_plan + ignored={sorted(ignored)}; "
        f"sticky_cleared={sticky_cleared}. "
        f"impl={S4_IMPL_ID}"
    )
    try:
        from core import console

        console.warn(line)
    except Exception:
        try:
            print(line)
        except Exception:
            pass
    return payload


def maybe_signal_s4_needed(
    game: Any,
    player: Any,
    *,
    reason: str = "",
) -> Optional[Dict[str, Any]]:
    """Backward-compatible name: runs S4 bounce-guard (implemented)."""
    return maybe_apply_s4_bounce_guard(game, player, reason=reason)


# ── S7: salvage adopt dig fields (probe + result.json) ──────────────────────


def _positive_way_id(value: Any) -> Optional[int]:
    """Return int way id if value is a positive Victory-Way id, else None."""
    if value is None or value == "":
        return None
    try:
        wid = int(float(value))
    except Exception:
        return None
    if wid <= 0:
        return None
    return wid


def _way_id_from_mapping(raw: Any, *keys: str) -> Optional[int]:
    if not isinstance(raw, Mapping):
        return None
    for key in keys:
        wid = _positive_way_id(raw.get(key))
        if wid is not None:
            return wid
    return None


def resolve_pre_adopt_way_id(
    player: Any = None,
    report: Any = None,
    abstract: Any = None,
    *,
    include_candidates: bool = False,
) -> Dict[str, Any]:
    """S7a D1: best pre-adopt Victory-Way id for dig ``abstract_way_before``.

    Resolution order (first positive id wins) — see
    ``docs/PhaseL_S7a_abstract_way_before_plan.md``:

      1. sticky_commitment.locked_way_id      → sticky_locked
      2. strategic_direction.preferred_way_id → direction_preferred
      3. strategic_direction.way_id           → direction_way
      4. abstract / report preferred_strategy → report_preferred
      5. last_strategic_direction             → last_direction
      6. ways_used_this_game[-1]              → ways_used_last
      7. none                                 → none

    Pure function: does not mutate player/report. Not used for ranking (D1 only).
    """
    candidates: Dict[str, Optional[int]] = {
        PRE_ADOPT_SOURCE_STICKY: None,
        PRE_ADOPT_SOURCE_DIR_PREFERRED: None,
        PRE_ADOPT_SOURCE_DIR_WAY: None,
        PRE_ADOPT_SOURCE_REPORT: None,
        PRE_ADOPT_SOURCE_LAST_DIR: None,
        PRE_ADOPT_SOURCE_WAYS_USED: None,
    }

    sticky = getattr(player, "sticky_commitment", None) if player is not None else None
    candidates[PRE_ADOPT_SOURCE_STICKY] = _way_id_from_mapping(sticky, "locked_way_id")

    direction = getattr(player, "strategic_direction", None) if player is not None else None
    if isinstance(direction, Mapping):
        candidates[PRE_ADOPT_SOURCE_DIR_PREFERRED] = _positive_way_id(
            direction.get("preferred_way_id")
        )
        candidates[PRE_ADOPT_SOURCE_DIR_WAY] = _positive_way_id(direction.get("way_id"))

    # Report preferred_strategy (by_player block) or explicit abstract mapping
    report_pref: Any = None
    if isinstance(abstract, Mapping) and abstract:
        report_pref = abstract
    elif report is not None and player is not None:
        try:
            by = report.get("by_player") if isinstance(report, Mapping) else None
            if isinstance(by, Mapping):
                pid = getattr(player, "id", None)
                block = by.get(str(pid)) if pid is not None else None
                if not isinstance(block, Mapping) and pid is not None:
                    block = by.get(pid)
                if isinstance(block, Mapping):
                    report_pref = block.get("preferred_strategy")
        except Exception:
            report_pref = None
    candidates[PRE_ADOPT_SOURCE_REPORT] = _way_id_from_mapping(
        report_pref, "preferred_way_id", "way_id"
    )

    last_dir = (
        getattr(player, "last_strategic_direction", None) if player is not None else None
    )
    candidates[PRE_ADOPT_SOURCE_LAST_DIR] = _way_id_from_mapping(
        last_dir, "preferred_way_id", "way_id"
    )

    ways_used_last: Optional[int] = None
    if player is not None:
        try:
            used = list(getattr(player, "ways_used_this_game", None) or [])
            if used:
                ways_used_last = _positive_way_id(used[-1])
        except Exception:
            ways_used_last = None
    candidates[PRE_ADOPT_SOURCE_WAYS_USED] = ways_used_last

    order = (
        (PRE_ADOPT_SOURCE_STICKY, candidates[PRE_ADOPT_SOURCE_STICKY]),
        (PRE_ADOPT_SOURCE_DIR_PREFERRED, candidates[PRE_ADOPT_SOURCE_DIR_PREFERRED]),
        (PRE_ADOPT_SOURCE_DIR_WAY, candidates[PRE_ADOPT_SOURCE_DIR_WAY]),
        (PRE_ADOPT_SOURCE_REPORT, candidates[PRE_ADOPT_SOURCE_REPORT]),
        (PRE_ADOPT_SOURCE_LAST_DIR, candidates[PRE_ADOPT_SOURCE_LAST_DIR]),
        (PRE_ADOPT_SOURCE_WAYS_USED, candidates[PRE_ADOPT_SOURCE_WAYS_USED]),
    )
    way_id: Optional[int] = None
    source = PRE_ADOPT_SOURCE_NONE
    for label, cand in order:
        if cand is not None:
            way_id = cand
            source = label
            break

    out: Dict[str, Any] = {
        "way_id": way_id,
        "source": source,
        "s7a": True,
        "impl_id": S7A_IMPL_ID,
    }
    if include_candidates:
        out["candidates"] = dict(candidates)
    return out


def _ensure_salvage_event_state(game: Any) -> Dict[str, Any]:
    """Mutable game-level salvage adopt counters / event list."""
    state = getattr(game, "salvage_event_state", None) if game is not None else None
    if isinstance(state, dict) and "t1_total" in state and "t2_total" in state:
        return state
    state = {
        "t1_total": 0,
        "t2_total": 0,
        "t1_by_seat": {},  # str(pid) -> int
        "t2_by_seat": {},
        "adopts_by_seat": {},  # any tier
        "events": [],
    }
    if game is not None:
        try:
            game.salvage_event_state = state
        except Exception:
            pass
    return state


def _salvage_adopt_dedupe_key(
    player_id: Any,
    tier: str,
    way_id: Any,
    dead: Sequence[Any],
) -> Tuple[Any, ...]:
    return (
        player_id,
        str(tier or ""),
        int(way_id) if way_id is not None else None,
        tuple(sorted(str(x) for x in (dead or []))),
    )


def classify_way_change_kind(
    abstract_way_before: Any,
    winner_way_id: Any,
) -> str:
    """S7a D3: map (before, win) → way_change_kind enum.

    | Kind        | When                                      |
    |-------------|-------------------------------------------|
    | first_lock  | before unknown, win known                 |
    | same        | both known and equal                      |
    | switch      | both known and different                  |
    | unknown     | win missing / unreadable                  |
    """
    before = _positive_way_id(abstract_way_before)
    win = _positive_way_id(winner_way_id)
    if win is None:
        return WAY_CHANGE_UNKNOWN
    if before is None:
        return WAY_CHANGE_FIRST_LOCK
    if before == win:
        return WAY_CHANGE_SAME
    return WAY_CHANGE_SWITCH


def note_salvage_adopt(
    game: Any,
    player: Any,
    *,
    salvage_meta: Optional[Mapping[str, Any]] = None,
    abstract_way_before: Optional[int] = None,
    abstract_way_before_source: Optional[str] = None,
    forced_adopt: bool = False,
    reason: str = "",
    round_n: Optional[int] = None,
    turn_n: Optional[int] = None,
    dedupe: bool = True,
) -> Optional[Dict[str, Any]]:
    """Record a T1/T2 salvage adopt for result.json KPIs.

    Dedupes consecutive identical (seat, tier, way, dead set) so L2 refresh
    spam does not inflate counts. Returns the compact record when counted,
    else None (skipped / invalid).

    S7a D3 fields:
      - ``abstract_way_before_source`` — sticky_locked / direction_* / explicit / none
      - ``way_change_kind`` — first_lock | same | switch | unknown
      - ``way_changed`` — True **only** when kind is ``switch`` (compat bool)
    """
    meta = dict(salvage_meta or {})
    tier_raw = str(meta.get("tier") or meta.get("salvage_mode") or "").lower()
    if "t2" in tier_raw or "partial" in tier_raw or "residual" in tier_raw:
        tier = "t2"
    elif "t1" in tier_raw or "nonspecial" in tier_raw:
        tier = "t1"
    else:
        # specials-dead escape without salvage tier still counts as T1-like
        if forced_adopt or meta.get("applied") or meta.get("forced_adopt"):
            tier = "t1" if meta.get("applied") else "escape"
        else:
            return None
        if tier == "escape":
            tier = "t1"

    if not (meta.get("applied") or meta.get("picked") or forced_adopt or meta.get("forced_adopt")):
        return None

    pid = None
    try:
        pid = int(getattr(player, "id", None)) if player is not None else None
    except Exception:
        pid = getattr(player, "id", None) if player is not None else None

    rnd = round_n
    trn = turn_n
    if game is not None:
        if rnd is None:
            try:
                rnd = int(getattr(game, "round", 0) or 0)
            except Exception:
                rnd = None
        if trn is None:
            try:
                trn = int(getattr(game, "turn", 0) or 0)
            except Exception:
                trn = None

    way_id = meta.get("winner_way_id") or meta.get("forced_adopt_way")
    way_id = _positive_way_id(way_id)
    if way_id is None and player is not None:
        way_id = _direction_way_id(player)
        way_id = _positive_way_id(way_id)

    dead = list(meta.get("dead_components") or meta.get("ignored_components") or [])
    dead = [str(x) for x in dead]
    abs_before = abstract_way_before
    if abs_before is None:
        abs_before = meta.get("abstract_way_before")
    abs_before = _positive_way_id(abs_before)

    before_source = abstract_way_before_source
    if before_source is None or str(before_source).strip() == "":
        before_source = meta.get("abstract_way_before_source")
    if before_source is None or str(before_source).strip() == "":
        before_source = (
            PRE_ADOPT_SOURCE_EXPLICIT
            if abs_before is not None
            else PRE_ADOPT_SOURCE_NONE
        )
    else:
        before_source = str(before_source).strip()

    residual_eta = meta.get("residual_eta")
    try:
        residual_eta = float(residual_eta) if residual_eta is not None else None
    except Exception:
        residual_eta = None

    way_change_kind = classify_way_change_kind(abs_before, way_id)
    way_changed = way_change_kind == WAY_CHANGE_SWITCH
    partial_plan = bool(meta.get("partial_plan") or tier == "t2")

    record: Dict[str, Any] = {
        "event": EVENT_SALVAGE_ADOPT,
        "impl_id": S7_IMPL_ID,
        "s7a_impl_id": S7A_IMPL_ID,
        "player_id": pid,
        "round": rnd,
        "turn": trn,
        "salvage_mode": meta.get("salvage_mode") or (SALVAGE_T2 if tier == "t2" else SALVAGE_T1),
        "tier": tier,
        "template_way_id": way_id,
        "winner_way_id": way_id,
        "abstract_way_before": abs_before,
        "abstract_way_before_source": before_source,
        "way_change_kind": way_change_kind,
        "way_changed": way_changed,
        "ignored_components": sorted(dead),
        "dead_components": sorted(dead),
        "residual_eta": residual_eta,
        "partial_plan": partial_plan,
        "forced_adopt": bool(forced_adopt or meta.get("forced_adopt")),
        "reason": str(reason or meta.get("reason") or "")[:120] or None,
    }

    if game is None:
        return record

    key = _salvage_adopt_dedupe_key(pid, tier, way_id, dead)
    if dedupe:
        last_key = getattr(player, "_last_salvage_adopt_key", None) if player else None
        if last_key == key:
            return None
        if player is not None:
            try:
                player._last_salvage_adopt_key = key
            except Exception:
                pass

    state = _ensure_salvage_event_state(game)
    seat_key = str(pid) if pid is not None else "?"
    if tier == "t2":
        state["t2_total"] = int(state.get("t2_total") or 0) + 1
        by = state.setdefault("t2_by_seat", {})
        if not isinstance(by, dict):
            by = {}
            state["t2_by_seat"] = by
        by[seat_key] = int(by.get(seat_key) or 0) + 1
    else:
        state["t1_total"] = int(state.get("t1_total") or 0) + 1
        by = state.setdefault("t1_by_seat", {})
        if not isinstance(by, dict):
            by = {}
            state["t1_by_seat"] = by
        by[seat_key] = int(by.get(seat_key) or 0) + 1
    adopts = state.setdefault("adopts_by_seat", {})
    if not isinstance(adopts, dict):
        adopts = {}
        state["adopts_by_seat"] = adopts
    adopts[seat_key] = int(adopts.get(seat_key) or 0) + 1

    events = state.setdefault("events", [])
    if isinstance(events, list) and len(events) < MAX_SALVAGE_EVENTS_ON_GAME:
        events.append(dict(record))

    try:
        game.last_salvage_adopt = dict(record)
        game.last_salvage_adopt_player_id = pid
    except Exception:
        pass
    if player is not None:
        try:
            player.last_salvage_adopt = dict(record)
        except Exception:
            pass
    return record


def log_salvage_adopt_event(
    game: Any,
    player: Any,
    *,
    salvage_meta: Optional[Mapping[str, Any]] = None,
    abstract_way_before: Optional[int] = None,
    abstract_way_before_source: Optional[str] = None,
    forced_adopt: bool = False,
    reason: str = "",
) -> Optional[Dict[str, Any]]:
    """Note salvage adopt counters and append a probe JSONL dig row when enabled."""
    record = note_salvage_adopt(
        game,
        player,
        salvage_meta=salvage_meta,
        abstract_way_before=abstract_way_before,
        abstract_way_before_source=abstract_way_before_source,
        forced_adopt=forced_adopt,
        reason=reason,
    )
    if record is None or game is None:
        return record

    # Probe JSONL (same sink as LA/LR give-up fires)
    try:
        from core.la_lr_probe_log import (
            PROBE_SCHEMA_VERSION,
            append_la_lr_probe_row,
            la_lr_probe_log_path,
            log_la_lr_probe_enabled,
        )
    except Exception:
        return record

    try:
        if not log_la_lr_probe_enabled(game):
            return record
    except Exception:
        return record

    row: Dict[str, Any] = {
        "schema": PROBE_SCHEMA_VERSION,
        "kind": "la_lr_probe",
        "event": EVENT_SALVAGE_ADOPT,
        "reason": str(record.get("reason") or "salvage_adopt")[:120],
        "player_id": record.get("player_id"),
        "round": record.get("round"),
        "turn": record.get("turn"),
        "way_id": record.get("template_way_id"),
        "salvage": {
            "adopted": True,
            "salvage_mode": record.get("salvage_mode"),
            "tier": record.get("tier"),
            "template_way_id": record.get("template_way_id"),
            "abstract_way_before": record.get("abstract_way_before"),
            "abstract_way_before_source": record.get("abstract_way_before_source"),
            "way_change_kind": record.get("way_change_kind"),
            "way_changed": record.get("way_changed"),
            "ignored_components": list(record.get("ignored_components") or []),
            "ignored_specials": [
                c
                for c in (record.get("ignored_components") or [])
                if c in (COMPONENT_LR, COMPONENT_LA)
            ],
            "residual_eta": record.get("residual_eta"),
            "partial_plan": record.get("partial_plan"),
            "forced_adopt": record.get("forced_adopt"),
            "impl_id": S7_IMPL_ID,
            "s7a_impl_id": S7A_IMPL_ID,
        },
    }
    try:
        row["ts"] = datetime.now().isoformat(timespec="seconds")
    except Exception:
        pass
    try:
        path = la_lr_probe_log_path(
            str(getattr(game, "la_lr_probe_log_path", "") or "") or None
        )
        append_la_lr_probe_row(path, row)
    except Exception:
        pass
    try:
        setattr(player, "last_salvage_adopt_row", dict(row))
    except Exception:
        pass
    try:
        setattr(game, "last_salvage_adopt_row", dict(row))
    except Exception:
        pass
    return record


def collect_salvage_summary(game: Any) -> Dict[str, Any]:
    """Export S7 salvage adopt KPIs for ``result.json`` / batch compact rows."""
    empty = {
        "salvage_t1_adopts_total": 0,
        "salvage_t2_adopts_total": 0,
        "salvage_adopts_total": 0,
        "salvage_t1_adopts_by_seat": {},
        "salvage_t2_adopts_by_seat": {},
        "salvage_adopts_by_seat": {},
        "salvage_adopts": [],
        "salvage_adopts_truncated": False,
        "salvage_s7_impl_id": S7_IMPL_ID,
    }
    if game is None:
        return empty
    state = getattr(game, "salvage_event_state", None)
    if not isinstance(state, Mapping):
        return empty
    events = (
        list(state.get("events") or [])
        if isinstance(state.get("events"), list)
        else []
    )
    t1 = int(state.get("t1_total") or 0)
    t2 = int(state.get("t2_total") or 0)
    total = t1 + t2
    truncated = total > len(events)
    t1_by = (
        dict(state.get("t1_by_seat") or {})
        if isinstance(state.get("t1_by_seat"), Mapping)
        else {}
    )
    t2_by = (
        dict(state.get("t2_by_seat") or {})
        if isinstance(state.get("t2_by_seat"), Mapping)
        else {}
    )
    adopts_by = (
        dict(state.get("adopts_by_seat") or {})
        if isinstance(state.get("adopts_by_seat"), Mapping)
        else {}
    )
    return {
        "salvage_t1_adopts_total": t1,
        "salvage_t2_adopts_total": t2,
        "salvage_adopts_total": total,
        "salvage_t1_adopts_by_seat": {str(k): int(v) for k, v in t1_by.items()},
        "salvage_t2_adopts_by_seat": {str(k): int(v) for k, v in t2_by.items()},
        "salvage_adopts_by_seat": {str(k): int(v) for k, v in adopts_by.items()},
        "salvage_adopts": events,
        "salvage_adopts_truncated": bool(truncated),
        "salvage_s7_impl_id": S7_IMPL_ID,
    }


def _event_way_change_kind(ev: Mapping[str, Any]) -> str:
    """Normalize adopt event → way_change_kind (S7a; fallback for pre-D3 rows)."""
    kind = str(ev.get("way_change_kind") or "").strip().lower()
    if kind in (
        WAY_CHANGE_SWITCH,
        WAY_CHANGE_SAME,
        WAY_CHANGE_FIRST_LOCK,
        WAY_CHANGE_UNKNOWN,
    ):
        return kind
    # Legacy: only way_changed bool was stored
    if ev.get("way_changed"):
        return WAY_CHANGE_SWITCH
    before = _positive_way_id(ev.get("abstract_way_before"))
    win = _positive_way_id(
        ev.get("template_way_id") or ev.get("winner_way_id")
    )
    return classify_way_change_kind(before, win)


def dig_salvage_fire_switch_kpis(
    results: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Batch dig: give-up fire → salvage T1/T2 adopt rates + S7a switch kinds.

    Per game:
      - has_fire = la or lr give-up fires > 0
      - has_salvage = salvage_adopts_total > 0
      - has_t1 / has_t2 similarly
      - has_switch / has_first_lock from salvage_adopts events (S7a)
    Rates are over games_with_fire (or None if none).

    Prefer ``way_change_kind`` for switch KPIs; ``games_with_salvage_way_change``
    is an alias of ``games_with_salvage_switch``.
    """
    games = 0
    with_fire = 0
    with_salvage = 0
    with_t1 = 0
    with_t2 = 0
    with_switch = 0
    with_first_lock = 0
    with_same = 0
    fire_and_salvage = 0
    fire_and_switch = 0
    lr_fires = 0
    la_fires = 0
    t1_adopts = 0
    t2_adopts = 0
    n_switch_events = 0
    n_same_events = 0
    n_first_lock_events = 0
    n_unknown_events = 0
    n_kind_events = 0
    # S5b G6 expansion dig aggregates
    settles_deferred_scans = 0
    settles_dead_scans = 0
    games_with_settles_deferred = 0
    games_with_settles_dead_geom = 0
    settles_deferred_events_n = 0
    settles_dead_events_n = 0

    for raw in results or []:
        if not isinstance(raw, Mapping):
            continue
        games += 1
        la_n = int(raw.get("la_giveup_fires_total") or 0)
        lr_n = int(raw.get("lr_giveup_fires_total") or 0)
        t1 = int(raw.get("salvage_t1_adopts_total") or 0)
        t2 = int(raw.get("salvage_t2_adopts_total") or 0)
        total_ad = int(raw.get("salvage_adopts_total") or (t1 + t2))
        la_fires += la_n
        lr_fires += lr_n
        t1_adopts += t1
        t2_adopts += t2
        has_fire = (la_n + lr_n) > 0
        has_salvage = total_ad > 0
        if has_fire:
            with_fire += 1
        if has_salvage:
            with_salvage += 1
        if t1 > 0:
            with_t1 += 1
        if t2 > 0:
            with_t2 += 1
        if has_fire and has_salvage:
            fire_and_salvage += 1

        game_has_switch = False
        game_has_first = False
        game_has_same = False
        for ev in list(raw.get("salvage_adopts") or []):
            if not isinstance(ev, Mapping):
                continue
            kind = _event_way_change_kind(ev)
            n_kind_events += 1
            if kind == WAY_CHANGE_SWITCH:
                n_switch_events += 1
                game_has_switch = True
            elif kind == WAY_CHANGE_SAME:
                n_same_events += 1
                game_has_same = True
            elif kind == WAY_CHANGE_FIRST_LOCK:
                n_first_lock_events += 1
                game_has_first = True
            else:
                n_unknown_events += 1
        if game_has_switch:
            with_switch += 1
        if game_has_first:
            with_first_lock += 1
        if game_has_same:
            with_same += 1
        if has_fire and game_has_switch:
            fire_and_switch += 1

        # S5b G6: deferred vs dead settles geometry
        def_scans = int(raw.get("settles_deferred_scans") or 0)
        dead_scans = int(raw.get("settles_dead_scans") or 0)
        settles_deferred_scans += def_scans
        settles_dead_scans += dead_scans
        if def_scans > 0 or int(raw.get("seats_ever_deferred_count") or 0) > 0:
            games_with_settles_deferred += 1
        if dead_scans > 0 or int(raw.get("seats_ever_dead_count") or 0) > 0:
            games_with_settles_dead_geom += 1
        settles_deferred_events_n += len(
            list(raw.get("settles_deferred_events") or [])
        )
        settles_dead_events_n += len(list(raw.get("settles_dead_events") or []))

    def _rate(num: int, den: int) -> Optional[float]:
        if den <= 0:
            return None
        return round(float(num) / float(den), 4)

    with_before = n_switch_events + n_same_events  # excludes first_lock / unknown

    fire_with_t1 = sum(
        1
        for r in (results or [])
        if isinstance(r, Mapping)
        and (int(r.get("la_giveup_fires_total") or 0) + int(r.get("lr_giveup_fires_total") or 0))
        > 0
        and int(r.get("salvage_t1_adopts_total") or 0) > 0
    )
    fire_with_t2 = sum(
        1
        for r in (results or [])
        if isinstance(r, Mapping)
        and (int(r.get("la_giveup_fires_total") or 0) + int(r.get("lr_giveup_fires_total") or 0))
        > 0
        and int(r.get("salvage_t2_adopts_total") or 0) > 0
    )

    return {
        "impl_id": S7_IMPL_ID,
        "s7a_impl_id": S7A_IMPL_ID,
        "games": games,
        "games_with_giveup_fire": with_fire,
        "games_with_salvage_adopt": with_salvage,
        "games_with_salvage_t1": with_t1,
        "games_with_salvage_t2": with_t2,
        "games_with_fire_and_salvage": fire_and_salvage,
        # S7a switch / first_lock dig
        "games_with_salvage_switch": with_switch,
        "games_with_salvage_first_lock": with_first_lock,
        "games_with_salvage_same": with_same,
        "games_with_fire_and_switch": fire_and_switch,
        # Alias (plan): way_change == switch after S7a
        "games_with_salvage_way_change": with_switch,
        "la_giveup_fires_total": la_fires,
        "lr_giveup_fires_total": lr_fires,
        "salvage_t1_adopts_total": t1_adopts,
        "salvage_t2_adopts_total": t2_adopts,
        "adopt_events_classified": n_kind_events,
        "adopt_events_switch": n_switch_events,
        "adopt_events_same": n_same_events,
        "adopt_events_first_lock": n_first_lock_events,
        "adopt_events_unknown": n_unknown_events,
        "salvage_adopt_rate_given_fire": _rate(fire_and_salvage, with_fire),
        "salvage_t1_rate_given_fire": _rate(fire_with_t1, with_fire),
        "salvage_t2_rate_given_fire": _rate(fire_with_t2, with_fire),
        "switch_rate_given_fire": _rate(fire_and_switch, with_fire),
        "switch_rate_among_adopts_with_before": _rate(n_switch_events, with_before),
        "first_lock_share_of_classified": _rate(n_first_lock_events, n_kind_events),
        "go_criterion_salvage_ge_60pct_of_fire": (
            (_rate(fire_and_salvage, with_fire) or 0.0) >= 0.60
            if with_fire > 0
            else None
        ),
        # S5b G6: expansion settles deferred vs dead
        "s5b_g6_impl_id": S5B_G6_IMPL_ID,
        "settles_deferred_scans": settles_deferred_scans,
        "settles_dead_scans": settles_dead_scans,
        "games_with_settles_deferred": games_with_settles_deferred,
        "games_with_settles_dead_geom": games_with_settles_dead_geom,
        "settles_deferred_events_count": settles_deferred_events_n,
        "settles_dead_events_count": settles_dead_events_n,
        "settles_deferred_share_of_geom_scans": _rate(
            settles_deferred_scans,
            settles_deferred_scans + settles_dead_scans,
        ),
    }


def status_dict(constants_module: Any = None) -> Dict[str, Any]:
    """Dig-in / batch stamp for salvage S0–S7."""
    return {
        "spec_freeze_id": SPEC_FREEZE_ID,
        "s1_impl_id": S1_IMPL_ID,
        "s2_impl_id": S2_IMPL_ID,
        "s3_impl_id": S3_IMPL_ID,
        "flag_enabled": is_giveup_salvage_partial_enabled(constants_module),
        "t1_expand_enabled": is_salvage_t1_expand_enabled(constants_module),
        "t2_enabled": is_salvage_t2_enabled(constants_module),
        "t1_expand_n": t1_expand_n(constants_module),
        "ranking_available": salvage_ranking_available(constants_module),
        "helpers_available": salvage_helpers_available(),
        "s0_only": False,
        "s1_helpers": True,
        "s2_t1_expand": True,
        "s3_t2_residual": True,
        "s4_sticky_partial": True,
        "s4_bounce_guard": True,
        "s4_implemented": True,
        "s4_impl_id": S4_IMPL_ID,
        "s5_expansion_dead": True,
        "s5_impl_id": S5_IMPL_ID,
        "s5b_settles_gate": True,
        "s5b_impl_id": S5B_IMPL_ID,
        "s5b_g6_dig": True,
        "s5b_g6_impl_id": S5B_G6_IMPL_ID,
        "s6_vp_dcards_dead": True,
        "s6_impl_id": S6_IMPL_ID,
        "s7_dig_fields": True,
        "s7_impl_id": S7_IMPL_ID,
        "s7a_pre_adopt_resolver": True,
        "s7a_way_change_kind": True,
        "s7a_dig_kpis": True,
        "s7a_impl_id": S7A_IMPL_ID,
        "components": sorted(ALL_COMPONENTS),
    }


__all__ = [
    "COMPONENT_CITIES",
    "COMPONENT_SETTLES_EXPAND",
    "COMPONENT_ROADS_EXPAND",
    "COMPONENT_LR",
    "COMPONENT_LA",
    "COMPONENT_VP_DCARDS",
    "ALL_COMPONENTS",
    "SALVAGE_T0",
    "SALVAGE_T1",
    "SALVAGE_T2",
    "SALVAGE_T3",
    "SPEC_FREEZE_ID",
    "S1_IMPL_ID",
    "S2_IMPL_ID",
    "S3_IMPL_ID",
    "DEFAULT_T1_EXPAND_N",
    "INFINITE_TURNS",
    "is_giveup_salvage_partial_enabled",
    "is_salvage_t1_expand_enabled",
    "is_salvage_t2_enabled",
    "t1_expand_n",
    "salvage_ranking_available",
    "salvage_helpers_available",
    "normalize_dead_components",
    "dead_components_from_specials_episode",
    "strategy_needs_dead_special",
    "strategy_needs_dead_component",
    "way_avoids_dead_specials",
    "detect_expansion_geometry_block",
    "update_player_expansion_dead",
    "collect_all_dead_components",
    "collect_nonspecial_way_ids",
    "expand_eval_way_ids_for_salvage_t1",
    "filter_audits_for_dead_components",
    "strip_components",
    "strip_components_from_strategy",
    "rescore_way_residual",
    "pick_salvage_t2_winner",
    "apply_salvage_tier_to_audits",
    "patch_direction_for_salvage",
    "S4_IMPL_ID",
    "collect_ignored_components_for_player",
    "stamp_partial_plan_fields",
    "apply_s4_project_suppress",
    "stamp_commitment_partial_plan",
    "maybe_apply_s4_bounce_guard",
    "maybe_signal_s4_needed",
    "status_dict",
    "S5_IMPL_ID",
    "S5B_IMPL_ID",
    "S5B_G6_IMPL_ID",
    "SETTLES_REASON_DEFERRED",
    "SETTLES_REASON_GATE_B",
    "note_expansion_settles_dig",
    "collect_expansion_settles_dig_summary",
    "S6_IMPL_ID",
    "S7_IMPL_ID",
    "S7A_IMPL_ID",
    "EVENT_SALVAGE_ADOPT",
    "MAX_SALVAGE_EVENTS_ON_GAME",
    "PRE_ADOPT_SOURCE_STICKY",
    "PRE_ADOPT_SOURCE_DIR_PREFERRED",
    "PRE_ADOPT_SOURCE_DIR_WAY",
    "PRE_ADOPT_SOURCE_REPORT",
    "PRE_ADOPT_SOURCE_LAST_DIR",
    "PRE_ADOPT_SOURCE_WAYS_USED",
    "PRE_ADOPT_SOURCE_NONE",
    "PRE_ADOPT_SOURCE_EXPLICIT",
    "WAY_CHANGE_FIRST_LOCK",
    "WAY_CHANGE_SAME",
    "WAY_CHANGE_SWITCH",
    "WAY_CHANGE_UNKNOWN",
    "public_dcard_deck_remaining",
    "detect_vp_dcards_dead",
    "update_player_vp_dcards_dead",
    "resolve_pre_adopt_way_id",
    "classify_way_change_kind",
    "note_salvage_adopt",
    "log_salvage_adopt_event",
    "collect_salvage_summary",
    "dig_salvage_fire_switch_kpis",
]
