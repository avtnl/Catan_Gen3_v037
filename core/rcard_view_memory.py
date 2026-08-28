"""Opponent RCard viewer-memory helpers for ResourceCardDashboard.

Row shape (length 10)::

    [viewer_id, viewed_id, Wheat, Ore, Wood, Brick, Sheep, Gold, QM_Added, QM_Discarded]

``player_view_now - player_view_lag[N]`` is the public evidence attributable to
the last ``N`` completed rounds (``RCARD_MEMORY_OPPONENTS``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

ViewRow = List[Any]
ViewTable = List[ViewRow]

RCARD_VIEW_ROW_LEN = 10
RCARD_VIEW_VALUE_SLICE = slice(2, 10)  # Wh..Gold, QM_Added, QM_Discarded
RCARD_MEMORY_LAG_MAX = 4


def normalize_rcard_memory_opponents(
    value: Any = None,
) -> Optional[int]:
    """Return memory window in rounds ``1..4``, or ``None`` for unlimited (``all``).

    Accepts ``1..4``, ``\"all\"`` / ``\"ALL\"``, ``0``/``None``/``\"\"`` → all.
    """
    if value is None:
        try:
            from core.constants import RCARD_MEMORY_OPPONENTS as cfg

            value = cfg
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("", "all", "full", "inf", "unlimited"):
            return None
        try:
            value = int(float(s))
        except Exception:
            return None
    try:
        n = int(value)
    except Exception:
        return None
    if n <= 0:
        return None
    return max(1, min(int(RCARD_MEMORY_LAG_MAX), n))


def copy_player_view(rows: Optional[Sequence[Sequence[Any]]]) -> ViewTable:
    """Deep-copy a player_view table; normalize row length to 10."""
    out: ViewTable = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        r = [int(row[0] or 0), int(row[1] or 0)]
        for i in range(2, RCARD_VIEW_ROW_LEN):
            try:
                r.append(int(row[i] or 0) if i < len(row) else 0)
            except Exception:
                r.append(0)
        out.append(r)
    return out


def empty_player_view_like(rows: Optional[Sequence[Sequence[Any]]]) -> ViewTable:
    """Zeroed value columns, same (viewer, viewed) pairs as ``rows``."""
    out: ViewTable = []
    for row in copy_player_view(rows):
        out.append([row[0], row[1], 0, 0, 0, 0, 0, 0, 0, 0])
    return out


def _row_key(row: Sequence[Any]) -> tuple:
    return (int(row[0] or 0), int(row[1] or 0))


def subtract_player_views(
    now: Optional[Sequence[Sequence[Any]]],
    lag: Optional[Sequence[Sequence[Any]]],
) -> ViewTable:
    """Element-wise ``max(0, now - lag)`` on value columns; keys from ``now``."""
    now_rows = copy_player_view(now)
    lag_map = {_row_key(r): r for r in copy_player_view(lag)}
    out: ViewTable = []
    for row in now_rows:
        key = _row_key(row)
        old = lag_map.get(key)
        if old is None:
            out.append(list(row))
            continue
        diff = [row[0], row[1]]
        for i in range(2, RCARD_VIEW_ROW_LEN):
            try:
                diff.append(max(0, int(row[i] or 0) - int(old[i] or 0)))
            except Exception:
                diff.append(0)
        out.append(diff)
    return out


def shift_lag_ring(
    lag: Optional[Sequence[Optional[Sequence[Sequence[Any]]]]],
    now: Optional[Sequence[Sequence[Any]]],
    *,
    max_lag: int = RCARD_MEMORY_LAG_MAX,
) -> List[ViewTable]:
    """Push ``now`` as new 1-round-ago snapshot; drop older than ``max_lag``.

    Index 0 = 1 round ago, index 3 = 4 rounds ago.
    """
    snap = copy_player_view(now)
    prev: List[ViewTable] = []
    for item in list(lag or [])[: max(0, int(max_lag) - 1)]:
        if item is None:
            prev.append(empty_player_view_like(snap))
        else:
            prev.append(copy_player_view(item))
    out = [snap] + prev
    while len(out) < int(max_lag):
        out.append(empty_player_view_like(snap))
    return out[: int(max_lag)]


def player_view_memory(
    now: Optional[Sequence[Sequence[Any]]],
    lag: Optional[Sequence[Optional[Sequence[Sequence[Any]]]]],
    rounds: Any = None,
) -> ViewTable:
    """Belief table for AI: full ``now`` if unlimited, else ``now - lag[N-1]``."""
    n = normalize_rcard_memory_opponents(rounds)
    now_rows = copy_player_view(now)
    if n is None:
        return now_rows
    lag_list = list(lag or [])
    idx = int(n) - 1
    if idx < 0 or idx >= len(lag_list) or lag_list[idx] is None:
        # Not enough round history yet → everything still "in memory"
        return now_rows
    return subtract_player_views(now_rows, lag_list[idx])


def lag_for_save(lag: Optional[Sequence[Optional[Sequence[Sequence[Any]]]]]) -> List[ViewTable]:
    """Serialize lag ring to plain lists (may be shorter than max until filled)."""
    out: List[ViewTable] = []
    for item in list(lag or [])[:RCARD_MEMORY_LAG_MAX]:
        out.append(copy_player_view(item) if item is not None else [])
    return out


def opponent_belief_hand5(
    game: Any,
    viewer: Any,
    opponent: Any,
    *,
    rounds: Any = None,
) -> tuple:
    """EH hand vector for *opponent* as seen by *viewer* under RCard memory.

    Returns ``(hand5_or_None, meta)``.
    - ``hand5 is None`` → caller should use truth ``Player.rcards`` (memory=all
      or no row). Typed counts come from the memory table Wh..Sh; capped by
      public ``number_of_rcards`` when present. ``QM_Added`` is not assigned to
      types (unknown mass does not help specific costs).
    """
    meta: dict = {"source": "truth", "memory_rounds": None, "qm_added": 0}
    n = normalize_rcard_memory_opponents(rounds)
    meta["memory_rounds"] = n
    if n is None:
        return None, meta
    try:
        viewer_id = int(getattr(viewer, "id", viewer) or 0)
        viewed_id = int(getattr(opponent, "id", opponent) or 0)
    except Exception:
        return None, meta
    if viewer_id <= 0 or viewed_id <= 0 or viewer_id == viewed_id:
        return None, meta

    rows: ViewTable = []
    try:
        fn = getattr(game, "get_rcard_player_view_memory", None)
        if callable(fn):
            rows = copy_player_view(fn(rounds))
        else:
            dashes = list(getattr(game, "resource_card_dashboard", []) or [])
            if dashes:
                rows = player_view_memory(
                    getattr(dashes[0], "resource_production_game_player_view", None),
                    getattr(dashes[0], "resource_production_game_player_view_lag", None),
                    rounds,
                )
    except Exception:
        rows = []

    hit = None
    for row in rows:
        if int(row[0] or 0) == viewer_id and int(row[1] or 0) == viewed_id:
            hit = row
            break
    if hit is None:
        meta["source"] = "memory_miss"
        return [0.0, 0.0, 0.0, 0.0, 0.0], meta

    hand = [float(hit[i] or 0) for i in range(2, 7)]  # Wh..Sh
    try:
        meta["qm_added"] = int(hit[8] or 0)
    except Exception:
        meta["qm_added"] = 0
    # Cap by public hand size so cumulative production memory cannot exceed cards held
    try:
        n_cards = getattr(opponent, "number_of_rcards", None)
        if n_cards is None:
            rc = getattr(opponent, "rcards", None) or {}
            if isinstance(rc, dict):
                n_cards = sum(int(v or 0) for v in rc.values())
        if n_cards is not None:
            n_cards_i = max(0, int(n_cards))
            s = sum(hand)
            if s > n_cards_i and s > 0:
                scale = float(n_cards_i) / float(s)
                hand = [round(x * scale, 4) for x in hand]
                meta["capped_to_public_count"] = n_cards_i
    except Exception:
        pass
    meta["source"] = f"rcard_memory_{n}"
    return hand, meta


__all__ = [
    "RCARD_MEMORY_LAG_MAX",
    "RCARD_VIEW_ROW_LEN",
    "copy_player_view",
    "empty_player_view_like",
    "lag_for_save",
    "normalize_rcard_memory_opponents",
    "opponent_belief_hand5",
    "player_view_memory",
    "shift_lag_ring",
    "subtract_player_views",
]
