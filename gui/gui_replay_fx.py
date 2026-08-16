"""M-GUI re-play FX (R6–R9 + Continue parity C1–C6).

Continue-only sounds (incl. STEAL); structure pulse; production green (clears
after build/buy/twb); white robber dest; steal victim reds (cycle-scoped).

Sounds respect ``is_audio_enabled`` / ``NO_GUI_AT_ALL_TF`` via ``play_sound``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Live SOUNDS registry keys (gui.gui_constants.Sound)
SOUND_DICE = "DICEROLL"
SOUND_SEVEN = "DANGER"
SOUND_ROAD = "BUILDROAD"
SOUND_SETTLE_CITY = "FANFARE"  # live execution: settle + city
SOUND_IP_PLACE = "BUTTON"  # live Initial Placement (gui_guidance OKY path)
SOUND_BUY_DCARD = "BUYDCARD"
SOUND_PLAY_DCARD = "PLAYDCARD"
SOUND_FANFARE = "FANFARE"  # LR / LA award
SOUND_STEAL = "STEAL"  # C1 Continue parity

# Events that clear production greens when they appear after a non-7 dice (C2)
_PRODUCTION_CLEAR_EVENTS = frozenset(
    {
        "build_road",
        "build_settlement",
        "build_city",
        "buy_dcard",
        "twb",
        "ip_place_road",
        "ip_place_settlement",
    }
)

# Default seat colors if player meta missing
_DEFAULT_COLORS = {1: "Blue", 2: "Red", 3: "White", 4: "Orange"}


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except Exception:
        return default


def parse_dice_total(dice_field: Any) -> Optional[int]:
    """Parse MGlog ``dice`` cell to total (e.g. ``2+3=5`` → 5)."""
    raw = str(dice_field or "").strip()
    if not raw:
        return None
    if "=" in raw:
        total = _safe_int(raw.split("=")[-1].split(";")[0], None)
        if total is not None:
            return total
    if "+" in raw:
        left = raw.split("=")[0]
        parts = left.replace(" ", "").split("+")
        if len(parts) >= 2:
            a, b = _safe_int(parts[0], None), _safe_int(parts[1], None)
            if a is not None and b is not None:
                return int(a) + int(b)
    return _safe_int(raw.split(";")[0], None)


def sound_key_for_mglog_event(row: Mapping[str, Any]) -> Optional[str]:
    """Return SOUNDS registry key for one MGlog row, or None if silent.

    Plan §5.4 / §5.6 (Continue only — caller must gate on nav kind).
    """
    ev = str(row.get("event") or "").strip()
    if not ev:
        return None

    if ev == "dice_roll":
        total = parse_dice_total(row.get("dice"))
        if total == 7:
            return SOUND_SEVEN
        return SOUND_DICE

    # Initial Placement: live uses BUTTON (confirm place), not execution build SFX
    if ev in ("ip_place_road", "ip_place_settlement"):
        return SOUND_IP_PLACE

    if ev == "build_road":
        return SOUND_ROAD

    if ev in ("build_settlement", "build_city"):
        # Match live execution buy/build: settle + city → fanfare
        return SOUND_SETTLE_CITY

    if ev == "buy_dcard":
        return SOUND_BUY_DCARD

    if ev in (
        "play_knight",
        "play_yop",
        "play_monopoly",
        "play_tfr",
        "play_vp",
    ):
        return SOUND_PLAY_DCARD

    if ev in ("longest_road_change", "largest_army_change"):
        return SOUND_FANFARE

    if ev == "steal":
        # C1: Continue parity — live steal SFX (still silent: twb/twp/discard)
        return SOUND_STEAL

    # Silent: twb, twp, discard_7, set_robber, resource_production,
    # activate_dcard, turn_start/end, game_start, board_init, ip_complete, game_over
    return None


def sound_key_for_continue_step(session: Any) -> Optional[str]:
    """Sound for the event at the current cursor if last nav was Continue."""
    try:
        from core.mglog_replay import NAV_CONTINUE

        hl = getattr(session, "highlight", None)
        kind = str(getattr(session, "last_nav_kind", "") or "")
        if hl is not None and hasattr(hl, "plays_sound"):
            if not bool(hl.plays_sound):
                return None
        elif kind != NAV_CONTINUE:
            return None
    except Exception:
        if str(getattr(session, "last_nav_kind", "") or "") != "continue":
            return None

    rows = getattr(session, "rows", None) or []
    cursor = int(getattr(session, "cursor", -1))
    if cursor < 0 or cursor >= len(rows):
        return None
    return sound_key_for_mglog_event(rows[cursor])


def play_continue_sound(session: Any) -> Tuple[bool, Optional[str]]:
    """Play Continue-step sound if any. Returns (played, sound_key)."""
    key = sound_key_for_continue_step(session)
    if not key:
        return False, None
    try:
        from gui.gui_constants import play_sound, is_audio_enabled, SOUNDS

        if not is_audio_enabled():
            return False, key
        # If bank empty (init raced display), try once more
        if not any(v is not None for v in SOUNDS.values()):
            try:
                from gui.gui_constants import ensure_replay_audio

                ensure_replay_audio()
            except Exception:
                pass
        ok = bool(play_sound(key, fallback="BUTTON"))
        return ok, key
    except Exception:
        return False, key


def play_sound_key(key: str, *, fallback: str = "BUTTON") -> bool:
    """Thin wrapper for tests / direct play."""
    try:
        from gui.gui_constants import play_sound

        return bool(play_sound(key, fallback=fallback))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# R7: structure animations (roads / settlements / cities in highlight turn)
# ---------------------------------------------------------------------------


def _player_color_name(session: Any, player_id: Optional[int]) -> str:
    if player_id is None:
        return "Green"
    try:
        from core.mglog_replay import DEFAULT_COLORS

        colors = DEFAULT_COLORS
    except Exception:
        colors = _DEFAULT_COLORS
    try:
        pl = (getattr(session, "state", None) and session.state.players or {}).get(
            int(player_id)
        )
        if pl is not None and getattr(pl, "color", None):
            return str(pl.color)
    except Exception:
        pass
    return str(colors.get(int(player_id), "Green"))


def structure_anim_specs_from_session(session: Any) -> List[Dict[str, Any]]:
    """Build execution-style animation dicts for structures in the highlight.

    Each dict matches ``GUI.show_execution_build_animation`` keys:
    ``action``, ``color``, ``target_id`` and/or ``road_id``, ``player_id``.
    """
    hl = getattr(session, "highlight", None)
    rows = getattr(session, "rows", None) or []
    if hl is None:
        return []
    indices = list(getattr(hl, "structure_indices", None) or [])
    if not indices and getattr(hl, "indices", None):
        # Fallback: scan all highlight indices
        indices = [
            i
            for i in hl.indices
            if 0 <= i < len(rows)
            and str(rows[i].get("event") or "")
            in (
                "build_road",
                "build_settlement",
                "build_city",
                "ip_place_road",
                "ip_place_settlement",
            )
        ]

    specs: List[Dict[str, Any]] = []
    for i in indices:
        if i < 0 or i >= len(rows):
            continue
        row = rows[i]
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        color = _player_color_name(session, pid)
        tw1 = _safe_int(row.get("tw1"), None)
        tw2 = _safe_int(row.get("tw2"), None)

        if ev in ("build_road", "ip_place_road"):
            if tw1 is None or tw2 is None:
                continue
            a, b = int(tw1), int(tw2)
            if a > b:
                a, b = b, a
            specs.append(
                {
                    "action": "Build road",
                    "road_id": [a, b],
                    "color": color,
                    "player_id": pid,
                    "event_index": i,
                }
            )
        elif ev in ("build_settlement", "ip_place_settlement"):
            if tw1 is None:
                continue
            specs.append(
                {
                    "action": "Build settlement",
                    "target_id": int(tw1),
                    "color": color,
                    "player_id": pid,
                    "event_index": i,
                }
            )
        elif ev == "build_city":
            if tw1 is None:
                continue
            specs.append(
                {
                    "action": "Build city",
                    "target_id": int(tw1),
                    "color": color,
                    "player_id": pid,
                    "event_index": i,
                }
            )
    return specs


def _queue_item_from_spec(spec: Mapping[str, Any]) -> Optional[Tuple]:
    """Map one build spec → ``(center, color, diameter, kind)`` or None."""
    try:
        from gui.gui_constants import COLORS, POSITIONS
    except Exception:
        return None

    action = str(spec.get("action") or "")
    color_name = str(spec.get("color") or "").upper()
    color = COLORS.get(color_name, COLORS.get("GREEN", (0, 180, 0)))

    try:
        if action in {"Build city", "Build settlement"}:
            target = int(spec.get("target_id"))
            center = POSITIONS["intersections"].get(target)
            if not center:
                return None
            kind = "city" if action == "Build city" else "settlement"
            return (tuple(center), color, 20, kind)
        if action == "Build road":
            raw = spec.get("road_id")
            a, b = tuple(raw)[:2]
            pos1 = POSITIONS["intersections"].get(int(a))
            pos2 = POSITIONS["intersections"].get(int(b))
            if not pos1 or not pos2:
                return None
            center = (
                (int(pos1[0]) + int(pos2[0])) // 2,
                (int(pos1[1]) + int(pos2[1])) // 2,
            )
            return (center, color, 20, "road")
    except Exception:
        return None
    return None


def structure_queue_items_from_session(session: Any) -> List[Tuple]:
    """Queue tuples for ``gui.animate_queue_elements``."""
    items: List[Tuple] = []
    for spec in structure_anim_specs_from_session(session):
        item = _queue_item_from_spec(spec)
        if item is not None:
            items.append(item)
    return items


def _tile_center(tile_id: int) -> Optional[Tuple[int, int]]:
    try:
        from gui.gui_constants import POSITIONS

        c = POSITIONS.get("tiles", {}).get(int(tile_id))
        if c is None:
            return None
        return (int(c[0]), int(c[1]))
    except Exception:
        return None


def _intersection_center(iid: int) -> Optional[Tuple[int, int]]:
    try:
        from gui.gui_constants import POSITIONS

        c = POSITIONS.get("intersections", {}).get(int(iid))
        if c is None:
            return None
        return (int(c[0]), int(c[1]))
    except Exception:
        return None


def _tiles_with_number(board: Any, number: int) -> List[int]:
    """Land tile ids with production number ``number`` (for dice green cue)."""
    out: List[int] = []
    tiles = getattr(board, "tiles", None) or []
    for t in tiles:
        if t is None:
            continue
        try:
            val = int(getattr(t, "value", 0) or 0)
            tid = int(getattr(t, "id", -1))
            typ = str(getattr(t, "type", "") or "").lower()
        except Exception:
            continue
        if tid < 0:
            continue
        if val == int(number) and typ not in ("sea", "water", "desert", "blank", ""):
            out.append(tid)
    return out


def _tiles_with_number_from_session(session: Any, board: Any, number: int) -> List[int]:
    ids = _tiles_with_number(board, number)
    if ids:
        return ids
    snap = getattr(session, "board_snapshot", None)
    if snap is None:
        return []
    out: List[int] = []
    for t in list(getattr(snap, "tiles", None) or []):
        try:
            val = int(getattr(t, "value", 0) or 0)
            tid = int(getattr(t, "id", -1))
            typ = str(getattr(t, "type", "") or "").lower()
        except Exception:
            continue
        if tid < 0:
            continue
        if val == int(number) and typ not in ("sea", "water", "desert", "blank", ""):
            out.append(tid)
    return out


def _latest_non7_dice_index(hl: Any, rows: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """Index of latest dice_roll in highlight with total ≠ 7, or None."""
    last: Optional[int] = None
    for i in list(getattr(hl, "dice_indices", None) or []):
        if i < 0 or i >= len(rows):
            continue
        total = parse_dice_total(rows[i].get("dice"))
        if total is None or int(total) == 7:
            continue
        last = int(i)
    return last


def _production_cleared_by_post_roll_action(
    hl: Any, rows: Sequence[Mapping[str, Any]], dice_index: int
) -> bool:
    """C2: True if a build/buy/twb appears in highlight after the dice_roll."""
    for i in list(getattr(hl, "indices", None) or []):
        if i <= dice_index or i >= len(rows):
            continue
        ev = str(rows[i].get("event") or "")
        if ev in _PRODUCTION_CLEAR_EVENTS:
            return True
    return False


def _latest_set_robber_index(hl: Any) -> Optional[int]:
    idxs = list(getattr(hl, "set_robber_indices", None) or [])
    if not idxs:
        return None
    return max(int(i) for i in idxs)


def _intersection_ids_adjacent_to_tile(board: Any, tile_id: int) -> set:
    """F4: intersection ids that touch land tile ``tile_id`` (three_tile_ids)."""
    out: set = set()
    try:
        tid = int(tile_id)
    except Exception:
        return out
    for inter in list(getattr(board, "intersections", None) or []):
        if inter is None:
            continue
        try:
            iid = int(getattr(inter, "id", -1))
            tids = [
                int(x)
                for x in (getattr(inter, "three_tile_ids", None) or [])
            ]
        except Exception:
            continue
        if iid < 0:
            continue
        if tid in tids:
            out.add(iid)
    return out


def _robber_tile_for_steal_cues(
    hl: Any, rows: Sequence[Mapping[str, Any]], state: Any
) -> Optional[int]:
    """Robber tile id for current steal cycle (last set_robber dest, else state)."""
    dests = list(getattr(hl, "robber_destinations", None) or [])
    if dests:
        try:
            return int(dests[-1])
        except Exception:
            pass
    rob = getattr(state, "robber_tile", None) if state is not None else None
    try:
        return int(rob) if rob is not None else None
    except Exception:
        return None


def board_cue_queue_items_from_session(
    session: Any, board: Any = None
) -> List[Tuple]:
    """Continue parity (C2–C4) + F4 steal adjacency.

    * Non-7 dice: green production tiles until first post-roll build/buy/twb (C2).
    * Robber: **white** ring on **last** ``set_robber`` destination only (D3).
    * Steal (D2a + F4): red only on victim settle/city **adjacent to the robber tile**.

    Returns animate_queue tuples ``(center, color, diameter, kind)``.
    """
    try:
        from gui.gui_constants import (
            COLORS,
            RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS,
            ROBBER_TILE_HIGHLIGHT_RADIUS,
            VICTIM_STEAL_HIGHLIGHT_RADIUS,
        )
    except Exception:
        return []

    hl = getattr(session, "highlight", None)
    rows = getattr(session, "rows", None) or []
    if hl is None:
        return []

    green = COLORS.get("GREEN", (0, 180, 0))
    red = COLORS.get("RED", (200, 40, 40))
    white = COLORS.get("WHITE", (255, 255, 255))
    items: List[Tuple] = []

    # --- Dice / production tiles (green), C2 clear after build/buy/twb ---
    dice_i = _latest_non7_dice_index(hl, rows)
    if dice_i is not None and not _production_cleared_by_post_roll_action(
        hl, rows, dice_i
    ):
        total = parse_dice_total(rows[dice_i].get("dice"))
        if total is not None and int(total) != 7:
            for tid in _tiles_with_number_from_session(session, board, int(total)):
                center = _tile_center(tid)
                if center:
                    items.append(
                        (
                            center,
                            green,
                            int(RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS),
                            "tile",
                        )
                    )

    # --- Robber: white destination only (D3; prior path pulses not kept) ---
    dests = list(getattr(hl, "robber_destinations", None) or [])
    if dests:
        final = dests[-1]
        c = _tile_center(int(final))
        if c:
            items.append(
                (c, white, int(ROBBER_TILE_HIGHLIGHT_RADIUS), "tile")
            )

    # --- Steal victims (D2a + F4): after latest set_robber; adj. to robber only ---
    state = getattr(session, "state", None)
    players = getattr(state, "players", None) or {}
    last_robber_i = _latest_set_robber_index(hl)
    floor = int(last_robber_i) if last_robber_i is not None else -1
    robber_tid = _robber_tile_for_steal_cues(hl, rows, state)
    adj_ids: Optional[set] = None
    if robber_tid is not None:
        adj_ids = _intersection_ids_adjacent_to_tile(board, robber_tid)
        if not adj_ids:
            # Live Board may not be on session; try board_snapshot shell
            snap = getattr(session, "board_snapshot", None)
            # board_snapshot is not a full Board; keep adj_ids empty → no victim
            # pulses unless caller passed a real board with three_tile_ids.
            pass

    for i in list(getattr(hl, "steal_indices", None) or []):
        if i < 0 or i >= len(rows):
            continue
        if int(i) <= floor:
            continue
        row = rows[i]
        oid = _safe_int(row.get("opponent_id"), None)
        if oid is None or oid <= 0:
            continue
        victim = players.get(int(oid))
        if victim is None:
            continue
        for loc in list(getattr(victim, "settlements", None) or []):
            try:
                lid = int(loc)
            except Exception:
                continue
            # F4: require adjacency when we know the robber tile graph
            if adj_ids is not None and robber_tid is not None:
                if not adj_ids:
                    # No adjacency data → do not pulse all buildings (false positives)
                    continue
                if lid not in adj_ids:
                    continue
            c = _intersection_center(lid)
            if c:
                items.append(
                    (c, red, int(VICTIM_STEAL_HIGHLIGHT_RADIUS), "settlement")
                )
        for loc in list(getattr(victim, "cities", None) or []):
            try:
                lid = int(loc)
            except Exception:
                continue
            if adj_ids is not None and robber_tid is not None:
                if not adj_ids or lid not in adj_ids:
                    continue
            c = _intersection_center(lid)
            if c:
                items.append(
                    (c, red, int(VICTIM_STEAL_HIGHLIGHT_RADIUS), "city")
                )

    return items


def apply_structure_animations(
    gui: Any,
    session: Any,
    board: Any = None,
    *,
    clear_if_empty: bool = True,
) -> int:
    """Sync GUI pulse queue: structures (R7) + board cues (Continue parity C2–C4).

    Rebuilds structure + production/robber/steal items from highlight every call.
    Returns total highlight FX items queued.
    """
    if gui is None:
        return 0
    struct_items = structure_queue_items_from_session(session)
    board_items = board_cue_queue_items_from_session(session, board)
    items = struct_items + board_items

    if not items:
        if clear_if_empty:
            try:
                gui.animate_queue_elements = []
            except Exception:
                pass
        return 0

    try:
        gui.animate_queue_elements = items
        gui.animations_enabled = True
    except Exception:
        return 0
    return len(items)


def draw_structure_animation_frame(gui: Any, board: Any = None) -> None:
    """Draw one non-blocking pulse frame for structure + board cue queue (R7/R9)."""
    if gui is None:
        return
    queue = getattr(gui, "animate_queue_elements", None) or []
    if not queue or not getattr(gui, "animations_enabled", True):
        return
    try:
        import pygame
        from gui.gui_constants import WIN
    except Exception:
        return

    draw_items = [
        it
        for it in queue
        if isinstance(it, (list, tuple))
        and len(it) >= 4
        and str(it[3]) in ("road", "settlement", "city", "tile")
    ]
    if not draw_items:
        return

    try:
        step = (pygame.time.get_ticks() // 100) % 4
    except Exception:
        step = 0
    quadrants = [
        (True, True, True, False),
        (True, False, True, True),
        (False, True, True, True),
        (True, True, False, True),
    ]
    draw_tr, draw_tl, draw_br, draw_bl = quadrants[step]

    for center, color, diameter, kind in draw_items:
        try:
            pygame.draw.circle(
                WIN,
                color,
                center,
                int(diameter),
                2,
                draw_top_right=draw_tr,
                draw_top_left=draw_tl,
                draw_bottom_right=draw_br,
                draw_bottom_left=draw_bl,
            )
        except TypeError:
            try:
                pygame.draw.circle(WIN, color, center, int(diameter), 2)
            except Exception:
                pass
        except Exception:
            pass


def sync_structure_fx_after_nav(gui: Any, session: Any, board: Any = None) -> int:
    """Call after successful nav: refresh structure + board cue queue from highlight."""
    return apply_structure_animations(gui, session, board, clear_if_empty=True)


def sync_dice_faces_from_session(gui: Any, session: Any) -> bool:
    """C6: mirror live dice faces from session state (last roll ≤ cursor)."""
    if gui is None:
        return False
    state = getattr(session, "state", None)
    dice = getattr(state, "dice", None) if state is not None else None
    if not dice:
        return False
    try:
        if isinstance(dice, (list, tuple)) and len(dice) >= 2:
            pair = (int(dice[0]), int(dice[1]))
        else:
            return False
    except Exception:
        return False
    try:
        gui.last_dice_roll = pair
    except Exception:
        pass
    show = getattr(gui, "show_dices", None)
    if callable(show):
        try:
            show(pair)
            return True
        except Exception:
            return False
    return True


# ---------------------------------------------------------------------------
# R8 / C5: DCard play ring + live play-red; buy-red off (D1a)
# ---------------------------------------------------------------------------

# Scoreboard type order (must match gui._normalise_dcard_scoreboard_triplets)
DCARD_TYPE_ORDER = (
    "victory_point",
    "knight",
    "two_free_roads",
    "year_of_plenty",
    "monopoly",
)

_PLAY_EVENT_TO_TYPE = {
    "play_knight": "knight",
    "play_yop": "year_of_plenty",
    "play_monopoly": "monopoly",
    "play_tfr": "two_free_roads",
    "play_vp": "victory_point",
}


def _normalize_dcard_type_name(raw: Any) -> str:
    try:
        from core.mglog_replay import _normalize_dcard

        return str(_normalize_dcard(raw) or "")
    except Exception:
        return str(raw or "").strip().lower().replace(" ", "_")


def dcard_buy_types_by_player(session: Any) -> Dict[int, set]:
    """player_id → set of dcard type names bought in the highlight seat-turn (Q8)."""
    out: Dict[int, set] = {}
    hl = getattr(session, "highlight", None)
    rows = getattr(session, "rows", None) or []
    if hl is None:
        return out
    for i in list(getattr(hl, "buy_dcard_indices", None) or []):
        if i < 0 or i >= len(rows):
            continue
        row = rows[i]
        if str(row.get("event") or "") != "buy_dcard":
            continue
        pid = _safe_int(row.get("player_id"), None)
        if pid is None or pid <= 0:
            continue
        ctype = _normalize_dcard_type_name(row.get("dcard_type"))
        if not ctype or ctype == "unknown":
            continue
        out.setdefault(int(pid), set()).add(ctype)
    return out


def dcard_play_types_by_player(session: Any) -> Dict[int, set]:
    """player_id → set of dcard type names played in the highlight seat-turn."""
    out: Dict[int, set] = {}
    hl = getattr(session, "highlight", None)
    rows = getattr(session, "rows", None) or []
    if hl is None:
        return out
    for i in list(getattr(hl, "play_dcard_indices", None) or []):
        if i < 0 or i >= len(rows):
            continue
        row = rows[i]
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        if pid is None or pid <= 0:
            continue
        ctype = _PLAY_EVENT_TO_TYPE.get(ev)
        if not ctype:
            ctype = _normalize_dcard_type_name(row.get("dcard_type"))
        if not ctype:
            continue
        out.setdefault(int(pid), set()).add(ctype)
    return out


def apply_dcard_highlights_to_players(players: Sequence[Any], session: Any) -> None:
    """Stamp play types for labels; buy-red empty (D1a). Header pulse is separate.

    Type-cell rings removed (D4): play feedback is shared header pulse only.
    """
    plays = dcard_play_types_by_player(session)
    for p in players or []:
        try:
            pid = int(getattr(p, "id", 0) or 0)
        except Exception:
            continue
        try:
            # C5 / D1a: no buy-red (live-like immature black x/y/z)
            setattr(p, "replay_dcard_buy_types", set())
            setattr(p, "replay_dcard_play_types", set(plays.get(pid) or set()))
        except Exception:
            pass


def last_play_dcard_in_highlight(
    session: Any,
) -> Optional[Tuple[int, str]]:
    """Return (player_id, card_type) for the last play_* in highlight, or None."""
    hl = getattr(session, "highlight", None)
    rows = getattr(session, "rows", None) or []
    if hl is None:
        return None
    last_pid: Optional[int] = None
    last_type: Optional[str] = None
    for i in list(getattr(hl, "play_dcard_indices", None) or []):
        if i < 0 or i >= len(rows):
            continue
        row = rows[i]
        ev = str(row.get("event") or "")
        pid = _safe_int(row.get("player_id"), None)
        ctype = _PLAY_EVENT_TO_TYPE.get(ev) or _normalize_dcard_type_name(
            row.get("dcard_type")
        )
        if pid is None or pid <= 0 or not ctype:
            continue
        last_pid, last_type = int(pid), str(ctype)
    if last_pid is None or not last_type:
        return None
    return last_pid, last_type


def sync_dcard_header_play_fx_from_session(gui: Any, session: Any) -> bool:
    """D4 re-play: arm/clear shared header pulse from highlight plays.

    Full seat-turn: active whenever a play_* is in highlight ≤ cursor.
    """
    if gui is None:
        return False
    clear = getattr(gui, "clear_dcard_header_play_fx", None)
    arm = getattr(gui, "arm_dcard_header_play_fx", None)
    last = last_play_dcard_in_highlight(session)
    if last is None:
        if callable(clear):
            try:
                clear()
            except Exception:
                pass
        return False
    pid, ctype = last
    color_name = None
    state = getattr(session, "state", None)
    players = getattr(state, "players", None) or {}
    pl = players.get(int(pid))
    if pl is not None:
        color_name = str(getattr(pl, "color", "") or "") or None
    if not color_name:
        color_name = {1: "Blue", 2: "Red", 3: "White", 4: "Orange"}.get(int(pid), "Blue")
    if callable(arm):
        try:
            return bool(
                arm(ctype, pl, player_id=int(pid), color_name=color_name)
            )
        except TypeError:
            try:
                return bool(arm(ctype, pl, player_id=int(pid)))
            except Exception:
                return False
        except Exception:
            return False
    return False


def myturn_stub_for_dcard_plays(session: Any) -> Optional[Any]:
    """Optional myturn-like object so live play-red path also fires for last play.

    Prefer ``replay_dcard_*`` sets on players; this helps when multiple plays
    need the played_index path for the most recent play in the highlight.
    """
    from types import SimpleNamespace

    plays = dcard_play_types_by_player(session)
    if not plays:
        return None
    # Use the chronologically last play in highlight for myturn vector
    hl = getattr(session, "highlight", None)
    rows = getattr(session, "rows", None) or []
    last_pid = None
    last_type = None
    for i in list(getattr(hl, "play_dcard_indices", None) or []):
        if i < 0 or i >= len(rows):
            continue
        row = rows[i]
        ev = str(row.get("event") or "")
        last_pid = _safe_int(row.get("player_id"), None)
        last_type = _PLAY_EVENT_TO_TYPE.get(ev) or _normalize_dcard_type_name(
            row.get("dcard_type")
        )
    if last_pid is None or not last_type:
        return None
    try:
        idx = list(DCARD_TYPE_ORDER).index(last_type)
    except ValueError:
        idx = -1
    if idx < 0:
        return None
    vec = [0, 0, 0, 0, 0]
    vec[idx] = 1
    return SimpleNamespace(
        dcard_played_in_turn_TF=True,
        dcard_played_in_turn=vec,
        dcard_played_in_turn_player_id=int(last_pid),
    )


__all__ = [
    "SOUND_DICE",
    "SOUND_SEVEN",
    "SOUND_ROAD",
    "SOUND_SETTLE_CITY",
    "SOUND_IP_PLACE",
    "SOUND_BUY_DCARD",
    "SOUND_PLAY_DCARD",
    "SOUND_FANFARE",
    "SOUND_STEAL",
    "parse_dice_total",
    "sound_key_for_mglog_event",
    "sound_key_for_continue_step",
    "play_continue_sound",
    "play_sound_key",
    "structure_anim_specs_from_session",
    "structure_queue_items_from_session",
    "board_cue_queue_items_from_session",
    "apply_structure_animations",
    "draw_structure_animation_frame",
    "sync_structure_fx_after_nav",
    "sync_dice_faces_from_session",
    "DCARD_TYPE_ORDER",
    "dcard_buy_types_by_player",
    "dcard_play_types_by_player",
    "apply_dcard_highlights_to_players",
    "last_play_dcard_in_highlight",
    "sync_dcard_header_play_fx_from_session",
    "myturn_stub_for_dcard_plays",
]
