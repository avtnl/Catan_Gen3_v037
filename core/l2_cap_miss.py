"""Phase E: observe-only L2 cap-miss shadow dig (abstract turns over sync-fit).

After each L2 portfolio eval, compare the L2 eval set to an abstract rank of
**all** ``can_realize_way``-fit Victory-Ways. Log ``l2_cap_miss`` when a better
fit way sits outside the capped deep-score set.

Does **not** change sticky / BA. See ``docs/L2_sync_transparency_shadow_plan.md``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

_l2_cap_miss_log_path_override: Optional[str] = None
_header_written_paths: set = set()

INFINITE_TURNS = 9999.0


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
        if f != f:
            return default
        return f
    except Exception:
        return default


def _json_default(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    return str(obj)


def _flag_str(name: str, default: str = "off") -> str:
    try:
        from core import constants as C

        return str(getattr(C, name, default) or default).strip().lower()
    except Exception:
        return str(default).strip().lower()


def _flag_on(name: str, default: str = "on") -> bool:
    return _flag_str(name, default) in ("on", "true", "1", "yes")


def shadow_miss_enabled(game: Any = None) -> bool:
    if game is not None:
        try:
            raw = getattr(game, "l2_shadow_miss", None)
            if raw is not None and str(raw).strip() != "":
                return str(raw).strip().lower() in ("on", "true", "1", "yes")
        except Exception:
            pass
    return _flag_on("L2_SHADOW_MISS", "on")


def miss_min_gain(game: Any = None) -> float:
    if game is not None:
        try:
            raw = getattr(game, "l2_miss_min_gain", None)
            if raw is not None and str(raw).strip() != "":
                return float(raw)
        except Exception:
            pass
    try:
        from core import constants as C

        return float(getattr(C, "L2_MISS_MIN_GAIN", 1.0) or 1.0)
    except Exception:
        return 1.0


def shadow_every_n(game: Any = None) -> int:
    if game is not None:
        try:
            raw = getattr(game, "l2_shadow_every_n", None)
            if raw is not None and str(raw).strip() != "":
                return max(1, int(raw))
        except Exception:
            pass
    try:
        from core import constants as C

        return max(1, int(getattr(C, "L2_SHADOW_EVERY_N", 1) or 1))
    except Exception:
        return 1


def get_l2_cap_miss_log_path_override() -> Optional[str]:
    return _l2_cap_miss_log_path_override


def set_l2_cap_miss_log_path(path: Optional[str]) -> Optional[str]:
    """Set process-wide l2_cap_miss JSONL path (batch). Returns previous override."""
    global _l2_cap_miss_log_path_override
    prev = _l2_cap_miss_log_path_override
    if path is None or str(path).strip() == "":
        _l2_cap_miss_log_path_override = None
    else:
        _l2_cap_miss_log_path_override = str(path)
    return prev


def default_l2_cap_miss_log_path() -> str:
    try:
        from core.constants import FILENAME_HELP

        base = str(FILENAME_HELP or "Catan")
    except Exception:
        base = "Catan"
    return f"{base}_L2CapMiss.jsonl"


def l2_cap_miss_log_path(filename: Optional[str] = None) -> str:
    if _l2_cap_miss_log_path_override:
        return str(_l2_cap_miss_log_path_override)
    if filename:
        return str(filename)
    return default_l2_cap_miss_log_path()


def _ensure_header(path: str) -> None:
    if path in _header_written_paths:
        return
    try:
        p = Path(path)
        if p.is_file() and p.stat().st_size > 0:
            _header_written_paths.add(path)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")
        _header_written_paths.add(path)
    except Exception:
        pass


def append_l2_cap_miss_line(
    row: Mapping[str, Any],
    *,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    path = l2_cap_miss_log_path(filename)
    result: Dict[str, Any] = {"ok": False, "path": path, "error": ""}
    try:
        _ensure_header(path)
        line = json.dumps(
            dict(row), ensure_ascii=False, default=lambda o: str(o), separators=(",", ":")
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _board_fingerprint(game: Any, player: Any) -> Tuple[Any, ...]:
    """Invalidate fit cache on board/specials-relevant changes."""
    pid = _safe_int(getattr(player, "id", None), 0)
    board = getattr(game, "board", None) if game is not None else None
    try:
        n_s = len(getattr(board, "settlements", None) or []) if board else 0
        n_c = len(getattr(board, "cities", None) or []) if board else 0
        n_r = len(getattr(board, "roads", None) or []) if board else 0
    except Exception:
        n_s = n_c = n_r = -1
    la = lr = None
    try:
        la = getattr(game, "largest_army_owner_id", None) or getattr(
            game, "la_holder_id", None
        )
        lr = getattr(game, "longest_road_owner_id", None) or getattr(
            game, "lr_holder_id", None
        )
    except Exception:
        pass
    round_n = _safe_int(getattr(game, "round", None), 0)
    return (pid, n_s, n_c, n_r, la, lr, round_n)


def _get_cached_fit(
    game: Any, player: Any
) -> Optional[Dict[str, Any]]:
    if game is None or player is None:
        return None
    try:
        cache = getattr(game, "_l2_fit_cache", None)
        if not isinstance(cache, dict):
            return None
        fp = _board_fingerprint(game, player)
        if cache.get("fingerprint") != fp:
            return None
        bag = cache.get("fit_bag")
        return dict(bag) if isinstance(bag, dict) else None
    except Exception:
        return None


def _set_cached_fit(game: Any, player: Any, fit_bag: Mapping[str, Any]) -> None:
    if game is None or player is None:
        return
    try:
        game._l2_fit_cache = {
            "fingerprint": _board_fingerprint(game, player),
            "fit_bag": dict(fit_bag),
        }
    except Exception:
        pass


def _should_run_shadow(game: Any, player: Any) -> bool:
    if not shadow_miss_enabled(game):
        return False
    every = shadow_every_n(game)
    if every <= 1:
        return True
    try:
        rt = getattr(player, "_l2_shadow_counter", 0) or 0
        rt = int(rt) + 1
        setattr(player, "_l2_shadow_counter", rt)
        return (rt % every) == 0
    except Exception:
        return True


def _abstract_rank_fit_ways(
    game: Any,
    player: Any,
    fit_ids: Sequence[int],
) -> List[Tuple[int, float]]:
    """Return [(way_id, abstract_proxy_turns), ...] ascending (lower better)."""
    ids = [int(x) for x in fit_ids if int(x) > 0]
    if not ids or player is None:
        return []
    board = getattr(game, "board", None) if game is not None else None
    if board is None:
        return [(i, INFINITE_TURNS) for i in ids]

    try:
        from core.strategy_timing import (
            build_player_strategy_state,
            calculate_remaining_need,
            load_strategy_requirements,
            proxy_turns_for_need,
            evaluate_special_strategy_viability,
        )
    except Exception:
        return [(i, INFINITE_TURNS) for i in ids]

    try:
        player_state = build_player_strategy_state(board, player)
        requirements = load_strategy_requirements()
        req_by_id = {int(s.way_id): s for s in requirements}
        all_states = [player_state]
        try:
            for p in list(getattr(game, "players", []) or []):
                if _safe_int(getattr(p, "id", None)) == _safe_int(
                    getattr(player, "id", None)
                ):
                    continue
                all_states.append(build_player_strategy_state(board, p))
        except Exception:
            pass
        special_viability = evaluate_special_strategy_viability(
            player_state, all_states
        )
    except Exception:
        return [(i, INFINITE_TURNS) for i in ids]

    ranked: List[Tuple[int, float]] = []
    for wid in ids:
        strategy = req_by_id.get(int(wid))
        if strategy is None:
            ranked.append((int(wid), INFINITE_TURNS))
            continue
        # Mirror rank_strategies special filter (exclude non-viable LA/LR ways)
        try:
            if getattr(strategy, "longest_road", False):
                lr = special_viability.get("longest_road", {}) or {}
                if not bool(lr.get("viable", False)):
                    continue
            if getattr(strategy, "biggest_army", False):
                la = special_viability.get("largest_army", {}) or {}
                if not bool(la.get("viable", False)):
                    continue
        except Exception:
            pass
        try:
            remaining = calculate_remaining_need(
                strategy,
                player_state,
                subtract_current_roads=True,
                subtract_development_cards=False,
            )
            proxy = proxy_turns_for_need(
                remaining.need_vector,
                current_hand=player_state.current_hand,
                production_pips=player_state.production_pips,
                trade_rates=player_state.trade_rates,
            )
            ranked.append((int(wid), float(proxy)))
        except Exception:
            ranked.append((int(wid), INFINITE_TURNS))
    ranked.sort(key=lambda t: (t[1], t[0]))
    return ranked


def compute_l2_cap_miss(
    game: Any,
    player: Any,
    *,
    eval_ids: Optional[Sequence[int]] = None,
    winner_way_id: Optional[int] = None,
    dossier: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare L2 eval set to abstract-best among all sync-fit ways."""
    out: Dict[str, Any] = {
        "ok": False,
        "miss": False,
        "schema": "L2CapMiss",
        "shadow": "abstract_fit",
    }
    if player is None or game is None:
        out["error"] = "no_player_or_game"
        return out

    dos = dict(dossier or {})
    try:
        if not dos and game is not None:
            dos = dict(getattr(game, "_last_l2_way_dossier", None) or {})
    except Exception:
        dos = dict(dossier or {})

    eval_set = set()
    for x in list(eval_ids or dos.get("eval_ids") or []):
        try:
            i = int(x)
            if i > 0:
                eval_set.add(i)
        except Exception:
            continue

    winner = _safe_int(winner_way_id if winner_way_id is not None else dos.get("winner"), None)
    out["winner_way_id"] = winner
    out["eval_ids"] = sorted(eval_set)
    out["k_prime"] = _safe_int(dos.get("k_prime"), len(eval_set) or None)
    out["stage_top_n"] = _safe_int(dos.get("stage_top_n"), None)

    fit_bag = _get_cached_fit(game, player)
    if fit_bag is None:
        from core.strategy_board_fit import select_fit_ways

        fit_bag = select_fit_ways(game, player, way_ids=None)
        _set_cached_fit(game, player, fit_bag)
    fit_ids = [int(x) for x in (fit_bag.get("fit_way_ids") or [])]
    out["n_fit"] = len(fit_ids)
    out["giveup_carve_out"] = bool(fit_bag.get("giveup_carve_out"))

    ranked = _abstract_rank_fit_ways(game, player, fit_ids)
    out["n_ranked"] = len(ranked)
    if not ranked:
        out["ok"] = True
        out["reason"] = "no_ranked_fit"
        return out

    best_wid, best_t = ranked[0]
    out["best_fit_way_id"] = int(best_wid)
    out["best_fit_abstract_turns"] = round(float(best_t), 4)
    out["top_fit"] = [
        {"way_id": int(w), "abstract_turns": round(float(t), 4)} for w, t in ranked[:8]
    ]

    winner_t = None
    if winner is not None:
        for w, t in ranked:
            if int(w) == int(winner):
                winner_t = float(t)
                break
    if winner_t is None and winner is not None and winner in eval_set:
        # Winner may have been scored with board turns; fall back to dossier
        try:
            for row in list(dos.get("scored") or []):
                if int(row.get("way_id") or 0) == int(winner):
                    winner_t = float(row.get("abstract_turns") or INFINITE_TURNS)
                    break
        except Exception:
            winner_t = None
    out["winner_abstract_turns"] = (
        round(float(winner_t), 4) if winner_t is not None else None
    )

    min_gain = miss_min_gain(game)
    out["min_gain"] = float(min_gain)
    in_eval = int(best_wid) in eval_set
    out["best_in_eval"] = bool(in_eval)

    gain = None
    if winner_t is not None:
        gain = float(winner_t) - float(best_t)
    elif not in_eval:
        gain = float(min_gain)  # treat as miss by exclusion
    out["missed_gain"] = round(float(gain), 4) if gain is not None else None

    is_miss = False
    if not in_eval:
        is_miss = True
        out["miss_reason"] = "best_fit_outside_eval"
    elif gain is not None and gain >= float(min_gain) - 1e-12:
        is_miss = True
        out["miss_reason"] = "abstract_gain"
    else:
        out["miss_reason"] = "ok"

    out["miss"] = bool(is_miss)
    out["ok"] = True
    return out


def maybe_run_l2_cap_miss_shadow(
    game: Any,
    player: Any,
    *,
    dossier: Optional[Mapping[str, Any]] = None,
    write_log: bool = True,
) -> Dict[str, Any]:
    """Run shadow miss dig if enabled / every_N. Observe-only."""
    out: Dict[str, Any] = {"ok": False, "skipped": True}
    if not shadow_miss_enabled(game):
        out["reason"] = "shadow_off"
        return out
    if not _should_run_shadow(game, player):
        out["reason"] = "every_n_skip"
        return out

    dos = dict(dossier or {})
    try:
        if not dos and game is not None:
            dos = dict(getattr(game, "_last_l2_way_dossier", None) or {})
    except Exception:
        dos = {}

    bag = compute_l2_cap_miss(
        game,
        player,
        eval_ids=dos.get("eval_ids"),
        winner_way_id=dos.get("winner"),
        dossier=dos,
    )
    bag["skipped"] = False
    if game is not None:
        try:
            from core.strategy_reconsider import game_stage_label

            bag["live_stage"] = game_stage_label(game)
        except Exception:
            bag["live_stage"] = dos.get("live_stage")
        bag["round"] = _safe_int(getattr(game, "round", None))
        bag["turn"] = _safe_int(getattr(game, "turn", None))
        bag["game_id"] = str(getattr(game, "id", "") or "") or None
        bag["batch_id"] = str(getattr(game, "batch_id", None) or "") or None
        bag["sequence_number"] = _safe_int(getattr(game, "sequence_number", None))
    if player is not None:
        bag["player_id"] = _safe_int(getattr(player, "id", None))
    bag["ts"] = datetime.now().isoformat(timespec="seconds")

    try:
        setattr(player, "last_l2_cap_miss", dict(bag))
        setattr(game, "_last_l2_cap_miss", dict(bag))
    except Exception:
        pass

    if write_log and bag.get("ok"):
        # Always log when miss; also log non-miss at low rate for baselines? Log all ok rows.
        path_override = None
        if game is not None:
            try:
                path_override = getattr(game, "l2_cap_miss_log_path", None)
            except Exception:
                path_override = None
        written = append_l2_cap_miss_line(
            bag, filename=str(path_override) if path_override else None
        )
        bag["log_ok"] = bool(written.get("ok"))
        bag["log_path"] = written.get("path")
        if written.get("error"):
            bag["log_error"] = written.get("error")
    out.update(bag)
    out["skipped"] = False
    return out


def maybe_run_l2_cap_miss_after_portfolio(
    game: Any,
    player: Any,
    *,
    hand_only: bool = False,
) -> Dict[str, Any]:
    """Convenience hook after L2 portfolio layer (skips L0 hand-only)."""
    if hand_only:
        return {"ok": False, "skipped": True, "reason": "l0_hand_only"}
    return maybe_run_l2_cap_miss_shadow(game, player)


# Re-export flag helpers used by tests / hooks
# (defined above)

__all__ = [
    "shadow_miss_enabled",
    "miss_min_gain",
    "shadow_every_n",
    "set_l2_cap_miss_log_path",
    "get_l2_cap_miss_log_path_override",
    "l2_cap_miss_log_path",
    "append_l2_cap_miss_line",
    "compute_l2_cap_miss",
    "maybe_run_l2_cap_miss_shadow",
    "maybe_run_l2_cap_miss_after_portfolio",
]
