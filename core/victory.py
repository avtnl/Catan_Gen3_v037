"""Win check + VP breakdown (W1 — core only, no game-over panel).

Standard Catan: first player to reach VICTORY points **on their turn** wins.
Victory-point development cards each give +1 VP and may be revealed all at once
when claiming the win.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    from core.constants import VICTORY as _DEFAULT_VICTORY
except Exception:  # pragma: no cover
    _DEFAULT_VICTORY = 10

VICTORY_POINTS: int = int(_DEFAULT_VICTORY or 10)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _player_id(player: Any) -> Optional[int]:
    try:
        pid = int(getattr(player, "id", 0) or 0)
        return pid if pid > 0 else None
    except Exception:
        return None


def victory_point_threshold(game: Any = None) -> int:
    """Points required to win (game override or constants.VICTORY)."""
    if game is not None:
        try:
            raw = getattr(game, "victory_points_to_win", None)
            if raw is not None:
                return max(1, int(raw))
        except Exception:
            pass
    return max(1, int(VICTORY_POINTS))


def count_vp_development_cards(player: Any) -> int:
    """How many victory-point DCards the player owns (each = 1 VP).

    Prefer the hidden hand list. Fall back to dcard_summary as
    ``max(revealed z, new x + playable y)`` so legacy saves that double-counted
    buy into both x and z do not inflate VP, and correct buys (x-only until
    reveal) still count from the hand/new/playable columns.
    """
    if player is None:
        return 0
    hand = 0
    try:
        hand = sum(
            1
            for c in list(getattr(player, "development_cards", []) or [])
            if str(c) == "victory_point"
        )
    except Exception:
        hand = 0

    new_n = playable_n = revealed_n = 0
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            if not row or str(row[0]) != "victory_point":
                continue
            row_list = list(row)
            while len(row_list) < 4:
                row_list.append(0)
            new_n = max(0, _safe_int(row_list[1], 0))
            playable_n = max(0, _safe_int(row_list[2], 0))
            revealed_n = max(0, _safe_int(row_list[3], 0))
            break
    except Exception:
        pass

    held = new_n + playable_n
    # Prefer hand when present; else max(revealed, held) covers legacy double-book
    # (buy wrote both x and z) and correct x/y-only books.
    if hand > 0:
        return hand
    if revealed_n > 0 or held > 0:
        return max(revealed_n, held)
    return 0


def vp_breakdown(player: Any) -> Dict[str, Any]:
    """Public board VP + VP DCards breakdown for one player."""
    try:
        settlements = len(list(getattr(player, "settlements", []) or []))
    except Exception:
        settlements = 0
    try:
        cities = len(list(getattr(player, "cities", []) or []))
    except Exception:
        cities = 0
    settlement_points = int(settlements)
    city_points = 2 * int(cities)
    lr_points = 2 if bool(getattr(player, "longest_route_tf", False)) else 0
    la_points = 2 if bool(getattr(player, "largest_army_tf", False)) else 0
    vp_cards = count_vp_development_cards(player)
    board_points = settlement_points + city_points + lr_points + la_points
    total = board_points + vp_cards
    return {
        "player_id": _player_id(player),
        "settlements": settlement_points,
        "cities": city_points,
        "cities_count": cities,
        "settlements_count": settlements,
        "longest_road": lr_points,
        "largest_army": la_points,
        "vp_cards": vp_cards,
        "board_points": board_points,
        "total": total,
    }


def effective_vp(player: Any) -> int:
    """Victory points used for the win check (board + all VP DCards)."""
    return int(vp_breakdown(player).get("total") or 0)


def standings_snapshot(game: Any) -> List[Dict[str, Any]]:
    """Compact standings for all players (sorted by total VP desc)."""
    rows: List[Dict[str, Any]] = []
    for p in list(getattr(game, "players", []) or []):
        if p is None:
            continue
        br = vp_breakdown(p)
        rows.append(
            {
                "player_id": br.get("player_id"),
                "color": str(getattr(p, "color", "") or ""),
                "total": int(br.get("total") or 0),
                "breakdown": br,
            }
        )
    rows.sort(key=lambda r: (-int(r.get("total") or 0), int(r.get("player_id") or 0)))
    return rows


def reveal_all_vp_cards(game: Any, player: Any) -> Dict[str, Any]:
    """Reveal all victory-point DCards for the winner (claim-win bookkeeping).

    Ensures every owned VP card is counted in summary col3 (revealed/played),
    clears hidden new/playable cols for that type, and recalculates VP.
    Does **not** require one-per-turn DCard slot (all revealed at once).
    """
    out: Dict[str, Any] = {
        "ok": True,
        "player_id": _player_id(player),
        "revealed_count": 0,
        "already_revealed": 0,
    }
    if player is None:
        out["ok"] = False
        out["reason"] = "no_player"
        return out

    ensure = getattr(game, "_ensure_player_dcard_state", None) if game is not None else None
    if callable(ensure):
        try:
            ensure(player)
        except Exception:
            pass

    owned = count_vp_development_cards(player)
    out["revealed_count"] = int(owned)

    # Normalize summary row: [victory_point, new, playable, revealed]
    try:
        summary = list(getattr(player, "dcard_summary", []) or [])
        found = False
        for i, row in enumerate(summary):
            if not row or str(row[0]) != "victory_point":
                continue
            row_list = list(row)
            while len(row_list) < 4:
                row_list.append(0)
            prev_revealed = max(0, _safe_int(row_list[3], 0))
            out["already_revealed"] = prev_revealed
            row_list[1] = 0  # new
            row_list[2] = 0  # playable / hidden
            row_list[3] = max(owned, prev_revealed)  # all revealed
            summary[i] = row_list
            found = True
            break
        if not found and owned > 0:
            # Insert / extend summary
            while len(summary) < 1:
                summary.append(["victory_point", 0, 0, 0])
            # Prefer index 0 convention
            if summary and str(summary[0][0]) == "victory_point":
                summary[0] = ["victory_point", 0, 0, owned]
            else:
                summary.insert(0, ["victory_point", 0, 0, owned])
        player.dcard_summary = summary
    except Exception as exc:
        out["ok"] = False
        out["reason"] = f"summary_error:{exc}"

    try:
        setattr(player, "vp_cards_revealed", True)
        setattr(player, "vp_cards_revealed_count", int(owned))
    except Exception:
        pass

    # Keep cards in development_cards for hand history; they remain "revealed"
    try:
        player.number_of_dcards = len(list(getattr(player, "development_cards", []) or []))
    except Exception:
        pass

    try:
        player.recalculate_victory_points()
    except Exception:
        # Fallback: set totals from breakdown
        br = vp_breakdown(player)
        try:
            player.victory_points = int(br["total"])
            player.points = int(br["total"])
        except Exception:
            pass

    return out


def check_and_declare_winner(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    require_current_player: bool = True,
    emit_events: bool = True,
    refresh_ui: bool = True,
) -> Dict[str, Any]:
    """If ``player`` has ≥ victory threshold on their turn, declare them winner.

    Returns a result dict always:
      - won: bool
      - already_over: bool
      - win_result: snapshot when won (or previous if already over)

    Idempotent when ``game.game_over`` is already True.
    """
    threshold = victory_point_threshold(game)
    result: Dict[str, Any] = {
        "ok": True,
        "won": False,
        "already_over": False,
        "threshold": threshold,
        "reason": str(reason or "check_and_declare_winner"),
        "player_id": _player_id(player),
        "effective_vp": 0,
        "win_result": None,
    }

    if game is None:
        result["ok"] = False
        result["reason"] = "no_game"
        return result

    if bool(getattr(game, "game_over", False)):
        result["already_over"] = True
        result["won"] = False
        result["win_result"] = getattr(game, "win_result", None)
        try:
            w = getattr(game, "winner", None)
            result["player_id"] = _player_id(w) or result["player_id"]
        except Exception:
            pass
        return result

    if player is None:
        result["ok"] = False
        result["reason"] = "no_player"
        return result

    if require_current_player:
        current = None
        try:
            getter = getattr(game, "get_current_player", None)
            current = getter() if callable(getter) else getattr(game, "current_player", None)
        except Exception:
            current = getattr(game, "current_player", None)
        if current is not None and current is not player:
            try:
                if _player_id(current) != _player_id(player):
                    result["reason"] = "not_current_player"
                    result["effective_vp"] = effective_vp(player)
                    return result
            except Exception:
                result["reason"] = "not_current_player"
                return result

    # Sync board VP first (LR/LA flags, buildings)
    try:
        player.recalculate_victory_points()
    except Exception:
        pass

    br = vp_breakdown(player)
    total = int(br.get("total") or 0)
    result["effective_vp"] = total
    result["breakdown"] = br

    if total < threshold:
        result["reason"] = "below_threshold"
        return result

    # ── Claim win ──────────────────────────────────────────────────────────
    reveal = reveal_all_vp_cards(game, player)
    br_after = vp_breakdown(player)
    total_after = int(br_after.get("total") or 0)
    # Safety: ensure we still meet threshold after bookkeeping
    if total_after < threshold:
        total_after = max(total_after, total)

    standings = standings_snapshot(game)
    win_result: Dict[str, Any] = {
        "winner_id": _player_id(player),
        "color": str(getattr(player, "color", "") or ""),
        "final_vp": total_after,
        "threshold": threshold,
        "breakdown": br_after,
        "revealed_vp_cards": int(reveal.get("revealed_count") or br_after.get("vp_cards") or 0),
        "reveal": reveal,
        "standings": standings,
        "reason": str(reason or "reached_victory_points"),
        "round": _safe_int(getattr(game, "round", 0), 0),
        "turn": _safe_int(getattr(game, "turn", 0), 0),
        "declared_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        game.winner = player
        game.game_over = True
        game.win_result = win_result
        try:
            game.time_ended = win_result["declared_at"]
        except Exception:
            pass
    except Exception as exc:
        result["ok"] = False
        result["reason"] = f"set_game_over_failed:{exc}"
        return result

    result["won"] = True
    result["win_result"] = win_result
    result["effective_vp"] = total_after
    result["reason"] = "declared_winner"

    if emit_events:
        try:
            emit = getattr(game, "emit_twitter_event", None)
            if callable(emit):
                n_vp = int(win_result.get("revealed_vp_cards") or 0)
                extra = f" (reveals {n_vp} VP card(s))" if n_vp > 0 else ""
                emit(
                    _player_id(player),
                    f"wins the game with {total_after} VP!{extra}",
                )
        except Exception:
            pass
        try:
            rec = getattr(game, "record_turn_event", None)
            if callable(rec):
                rec(
                    player=player,
                    event_type="game_over",
                    source="check_and_declare_winner",
                    message=f"Player {_player_id(player)} wins with {total_after} VP",
                    metadata=dict(win_result),
                )
        except Exception:
            pass

    # W4: Gen2-style win fanfare once per declare (panel open skips a second blare).
    try:
        if not bool(getattr(game, "win_fanfare_played", False)):
            setattr(game, "win_fanfare_played", True)
            from gui.gui_constants import SOUNDS

            sound = SOUNDS.get("FANFARE") or SOUNDS.get("ENDGAME") or SOUNDS.get("BELL")
            if sound is not None:
                sound.play()
    except Exception:
        try:
            setattr(game, "win_fanfare_played", True)
        except Exception:
            pass

    if refresh_ui:
        try:
            refresh = getattr(game, "_refresh_gui_scoreboard_after_dcard_change", None)
            if callable(refresh):
                refresh("after_game_over")
        except Exception:
            pass

    # W3: open Statistics / Playboard / New Game post-game UI (best-effort).
    try:
        opener = getattr(game, "open_game_over_panel", None)
        if callable(opener):
            opener(win_result=win_result)
        else:
            from gui.gui_game_over_panel import open_game_over_panel as _open_go

            _open_go(game, win_result=win_result)
    except Exception:
        pass

    return result


__all__ = [
    "VICTORY_POINTS",
    "victory_point_threshold",
    "count_vp_development_cards",
    "vp_breakdown",
    "effective_vp",
    "standings_snapshot",
    "reveal_all_vp_cards",
    "check_and_declare_winner",
]
