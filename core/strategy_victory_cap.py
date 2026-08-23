"""P1: prefer Victory-Ways that hit ``VICTORY`` without overshoot.

Ways whose table ``Total_Victory_Points`` exceeds the game victory threshold
(e.g. way 117 = 11 when ``VICTORY=10``) are soft-demoted in board-way ranking
so exact-10 ways (38, 66, 102, …) win when ETA is comparable.

Does not delete overshooting ways from dig audits — only raises ``rank_key``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Large enough to lose to a slightly worse ETA on an exact-VP way, small enough
# that a vastly better overshoot way can still win if everything else is broken.
VICTORY_OVERSHOOT_PENALTY = 75.0
INFINITE_TURNS = 9999.0


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def resolve_victory_threshold(game: Any = None, victory: Any = None) -> int:
    if victory is not None:
        v = _safe_int(victory, None)
        if v is not None and v > 0:
            return int(v)
    if game is not None:
        v = _safe_int(getattr(game, "victory", None), None)
        if v is not None and v > 0:
            return int(v)
        v = _safe_int(getattr(game, "VICTORY", None), None)
        if v is not None and v > 0:
            return int(v)
    try:
        from core.constants import VICTORY as _V

        return max(1, int(_V))
    except Exception:
        return 10


def way_table_total_vp(way_id: Any) -> Optional[int]:
    """``Total_Victory_Points`` from the 142-ways table."""
    try:
        from core.strategy_way_residual import load_way_requirement

        strat = load_way_requirement(way_id)
        if strat is None:
            return None
        tvp = _safe_int(getattr(strat, "total_victory_points", None), None)
        if tvp is not None and tvp > 0:
            return int(tvp)
    except Exception:
        pass
    return None


def way_overshoots_victory(
    way_id: Any, *, game: Any = None, victory: Any = None
) -> bool:
    thr = resolve_victory_threshold(game, victory)
    tvp = way_table_total_vp(way_id)
    return tvp is not None and int(tvp) > int(thr)


def _audit_way_id(audit: Any) -> Optional[int]:
    try:
        if isinstance(audit, Mapping):
            return _safe_int(audit.get("way_id"), None)
        return _safe_int(getattr(audit, "way_id", None), None)
    except Exception:
        return None


def _get_rank_key(audit: Any) -> float:
    try:
        if isinstance(audit, Mapping):
            return float(audit.get("rank_key", INFINITE_TURNS) or INFINITE_TURNS)
        return float(getattr(audit, "rank_key", INFINITE_TURNS) or INFINITE_TURNS)
    except Exception:
        return INFINITE_TURNS


def _set_rank_key(audit: Any, value: float) -> None:
    try:
        if isinstance(audit, dict):
            audit["rank_key"] = float(value)
            return
        if hasattr(audit, "rank_key"):
            audit.rank_key = float(value)  # type: ignore[attr-defined]
    except Exception:
        pass


def _append_note(audit: Any, note: str) -> None:
    try:
        if isinstance(audit, dict):
            notes = list(audit.get("notes") or [])
            notes.append(note)
            audit["notes"] = notes
            return
        notes = list(getattr(audit, "notes", None) or [])
        notes.append(note)
        audit.notes = notes  # type: ignore[attr-defined]
    except Exception:
        pass


def apply_victory_cap_to_audits(
    audits: Sequence[Any],
    *,
    game: Any = None,
    victory: Any = None,
    penalty: float = VICTORY_OVERSHOOT_PENALTY,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Soft-demote ways with table VP > victory threshold; re-sort."""
    thr = resolve_victory_threshold(game, victory)
    items = list(audits or [])
    meta: Dict[str, Any] = {
        "applied": False,
        "victory": thr,
        "penalty": float(penalty),
        "n_before": len(items),
        "overshoot_way_ids": [],
        "ok_way_ids": [],
    }
    if not items:
        return items, meta

    meta["applied"] = True
    for audit in items:
        wid = _audit_way_id(audit)
        tvp = way_table_total_vp(wid) if wid is not None else None
        if tvp is not None and int(tvp) > int(thr):
            meta["overshoot_way_ids"].append(int(wid))
            _set_rank_key(audit, _get_rank_key(audit) + float(penalty))
            _append_note(audit, f"victory_cap:overshoot_{tvp}>{thr}")
        elif wid is not None:
            meta["ok_way_ids"].append(int(wid))
            if tvp is not None:
                _append_note(audit, f"victory_cap:ok_{tvp}<={thr}")

    def _be(a: Any) -> float:
        try:
            if isinstance(a, Mapping):
                return float(a.get("board_expected_turns", INFINITE_TURNS) or INFINITE_TURNS)
            return float(getattr(a, "board_expected_turns", INFINITE_TURNS) or INFINITE_TURNS)
        except Exception:
            return INFINITE_TURNS

    def _wid(a: Any) -> int:
        w = _audit_way_id(a)
        return int(w) if w is not None else 10**9

    items.sort(key=lambda a: (_get_rank_key(a), _be(a), _wid(a)))
    meta["n_after"] = len(items)
    meta["winner_way_id"] = _audit_way_id(items[0]) if items else None
    return items, meta


def maybe_force_victory_cap_sticky(
    game: Any,
    player: Any,
    audits: Sequence[Any],
    *,
    victory: Any = None,
) -> Dict[str, Any]:
    """If sticky way overshoots and a non-overshoot winner exists, clear sticky."""
    out: Dict[str, Any] = {
        "checked": False,
        "cleared_sticky": False,
        "sticky_way_id": None,
        "winner_way_id": None,
        "sticky_overshoot": False,
    }
    if player is None or not audits:
        return out
    thr = resolve_victory_threshold(game, victory)
    out["victory"] = thr
    try:
        from core.strategy_board_fit import sticky_or_direction_way_id

        sticky_w = sticky_or_direction_way_id(player)
    except Exception:
        sticky_w = None
    out["sticky_way_id"] = sticky_w
    out["checked"] = True
    if sticky_w is None:
        return out
    if not way_overshoots_victory(sticky_w, game=game, victory=thr):
        return out
    out["sticky_overshoot"] = True
    winner = list(audits)[0]
    win_id = _audit_way_id(winner)
    out["winner_way_id"] = win_id
    if win_id is None or int(win_id) == int(sticky_w):
        return out
    if way_overshoots_victory(win_id, game=game, victory=thr):
        # Best remaining still overshoots — keep sticky
        return out
    try:
        from core.strategy_sticky import clear_sticky_commitment, flag_strategy_recalc

        clear_sticky_commitment(player)
        out["cleared_sticky"] = True
        try:
            flag_strategy_recalc(
                player,
                "victory_cap_overshoot",
                detail={
                    "sticky_way_id": int(sticky_w),
                    "winner_way_id": int(win_id),
                    "victory": thr,
                },
            )
        except Exception:
            pass
        try:
            player.force_strategy_recalc = True
        except Exception:
            pass
    except Exception:
        pass
    return out


__all__ = [
    "VICTORY_OVERSHOOT_PENALTY",
    "resolve_victory_threshold",
    "way_table_total_vp",
    "way_overshoots_victory",
    "apply_victory_cap_to_audits",
    "maybe_force_victory_cap_sticky",
]
