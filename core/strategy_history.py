"""Strategy history samples for STR tab (PR-D) + CS-3 reload from file.

Records compact snapshots whenever strategy context is refreshed so the UI can
show the last ~5 turns of way_id / expected-turns changes, including mid-turn
way flips.

CS-3 rebuilds ``player.strategy_history_samples`` from FILENAME_CS JSONL after
a game load (samples are runtime-only and not stored in Saved_Game).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MAX_SAMPLES_PER_PLAYER = 40
MAX_TURNS_IN_HIST = 5


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        f = float(value)
        if f >= 9000:
            return None
        return f
    except Exception:
        return None


def _way_id_from(preferred: Mapping[str, Any]) -> Optional[int]:
    raw = preferred.get("preferred_way_id", preferred.get("way_id"))
    try:
        if raw is None or raw == "" or raw == "-":
            return None
        return int(float(raw))
    except Exception:
        return None


def _short_reason(reason: str) -> str:
    text = str(reason or "").strip()
    if not text:
        return "refresh"
    # Keep tail after last meaningful segment
    for prefix in (
        "after_",
        "slice_d:",
        "continue_action_selection_after_action",
        "refresh_strategy_context",
    ):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.replace("human_", "").replace("ai_", "").replace(" ", "_")
    if len(text) > 18:
        text = text[:16] + "…"
    return text or "refresh"


def _turns_from_preferred(preferred: Mapping[str, Any], game: Any = None) -> Tuple[Optional[float], Optional[float]]:
    """Return (display_turns, abstract_turns). Prefer risk-adjusted / total own turns."""
    display = None
    for key in (
        "risk_adjusted_total_expected_own_turns",
        "total_expected_own_turns",
        "board_expected_turns",
        "realistic_expected_turns",
        "baseline_best_expected_own_turns",
    ):
        display = _safe_float(preferred.get(key))
        if display is not None:
            break

    # Prefer board audit realistic turns when way matches
    if game is not None:
        try:
            way = _way_id_from(preferred)
            audit = getattr(game, "current_board_way_audit", None)
            if isinstance(audit, Mapping) and way is not None:
                aw = audit.get("way_id") or audit.get("preferred_way_id")
                if _safe_int(aw, -1) == way:
                    board_t = _safe_float(
                        audit.get("realistic_expected_turns")
                        or audit.get("board_expected_turns")
                    )
                    if board_t is not None:
                        display = board_t
            # list of audits
            audits = getattr(game, "current_board_way_audits", None)
            if way is not None and isinstance(audits, Sequence):
                for a in audits:
                    if not isinstance(a, Mapping):
                        continue
                    if _safe_int(a.get("way_id"), -1) == way:
                        board_t = _safe_float(
                            a.get("realistic_expected_turns")
                            or a.get("board_expected_turns")
                        )
                        if board_t is not None:
                            display = board_t
                        break
        except Exception:
            pass

    abstract = _safe_float(
        preferred.get("abstract_expected_turns")
        or preferred.get("baseline_best_expected_own_turns")
    )
    return display, abstract


def make_strategy_history_sample(
    game: Any,
    player: Any,
    preferred: Mapping[str, Any],
    *,
    reason: str = "",
    sample_kind: str = "refresh",
) -> Dict[str, Any]:
    """Build one compact STR history sample."""
    preferred = preferred if isinstance(preferred, Mapping) else {}
    display_turns, abstract_turns = _turns_from_preferred(preferred, game)
    board_way = preferred.get("board_context_way_id") or preferred.get("board_rank_way_id")
    try:
        board_way_i = int(float(board_way)) if board_way not in (None, "", "-") else None
    except Exception:
        board_way_i = None

    # Phase C WP-C1: sticky target subset for STR / CS-3 alignment
    def _opt_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except Exception:
            return None

    sticky_target_id = None
    sticky_way_id = None
    sticky_invalidate_reason = None
    target_changed = None
    way_changed = None
    try:
        meta = getattr(player, "last_sticky_meta", None) if player is not None else None
        if isinstance(meta, Mapping):
            sticky_target_id = _opt_int(meta.get("sticky_target_id"))
            sticky_way_id = _opt_int(meta.get("sticky_way_id"))
            sticky_invalidate_reason = (
                str(meta.get("sticky_invalidate_reason") or "")[:80] or None
            )
            if meta.get("target_changed") is not None:
                target_changed = bool(meta.get("target_changed"))
            if meta.get("way_changed") is not None:
                way_changed = bool(meta.get("way_changed"))
        if sticky_target_id is None:
            sticky_target_id = _opt_int(
                preferred.get("locked_rec_target_id")
                or preferred.get("recommendation_target_id")
            )
        if sticky_way_id is None:
            sticky_way_id = _way_id_from(preferred)
    except Exception:
        pass

    kind = str(sample_kind or "refresh")
    if way_changed and kind in ("refresh", "post_dice", "end_turn"):
        kind = "way_change"
    elif target_changed and kind in ("refresh", "post_dice", "end_turn"):
        kind = "target_change"

    return {
        "round": _safe_int(getattr(game, "round", 0), 0),
        "turn": _safe_int(getattr(game, "turn", 0), 0),
        "state": str(getattr(game, "state", "") or ""),
        "reason": _short_reason(reason),
        "sample_kind": kind,
        "way_id": _way_id_from(preferred),
        "board_way_id": board_way_i,
        "turns": display_turns,
        "abstract_turns": abstract_turns,
        "supporting_target_id": preferred.get("supporting_action_target_id")
        or preferred.get("supporting_action_future_settlement_target_id"),
        "sticky_way_id": sticky_way_id,
        "sticky_target_id": sticky_target_id,
        "sticky_invalidate_reason": sticky_invalidate_reason,
        "target_changed": target_changed,
        "way_changed": way_changed,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }


def record_strategy_history_sample(
    player: Any,
    sample: Mapping[str, Any],
    *,
    max_samples: int = MAX_SAMPLES_PER_PLAYER,
) -> None:
    """Append sample to player.strategy_history_samples (ring buffer)."""
    if player is None or not isinstance(sample, Mapping):
        return
    try:
        hist = list(getattr(player, "strategy_history_samples", None) or [])
    except Exception:
        hist = []
    # Deduplicate rapid identical refreshes (same R/T/way/turns/reason)
    if hist:
        last = hist[-1]
        if (
            isinstance(last, Mapping)
            and last.get("round") == sample.get("round")
            and last.get("turn") == sample.get("turn")
            and last.get("way_id") == sample.get("way_id")
            and last.get("turns") == sample.get("turns")
            and last.get("reason") == sample.get("reason")
        ):
            # Refresh timestamp only
            try:
                hist[-1] = dict(sample)
                setattr(player, "strategy_history_samples", hist[-max_samples:])
            except Exception:
                pass
            return
    hist.append(dict(sample))
    try:
        setattr(player, "strategy_history_samples", hist[-max(1, int(max_samples)) :])
    except Exception:
        pass


def _prev_history_sample(player: Any) -> Optional[Dict[str, Any]]:
    try:
        hist = list(getattr(player, "strategy_history_samples", []) or [])
        if hist and isinstance(hist[-1], Mapping):
            return dict(hist[-1])
    except Exception:
        pass
    return None


def _emit_strategy_cs_log(
    game: Any,
    player: Any,
    preferred: Mapping[str, Any],
    sample: Mapping[str, Any],
    *,
    prev_sample: Optional[Mapping[str, Any]] = None,
) -> None:
    """CS-2: durable JSONL line for every strategy history sample (always on)."""
    try:
        from core.strategy_cs_log import log_strategy_cs

        log_strategy_cs(
            game,
            player,
            preferred,
            reason=str(sample.get("reason") or ""),
            sample_kind=str(sample.get("sample_kind") or "refresh"),
            prev_sample=prev_sample,
        )
    except Exception:
        # Logging must never break gameplay / strategy refresh.
        pass


def record_from_refresh(
    game: Any,
    player: Any,
    preferred: Mapping[str, Any],
    *,
    reason: str = "",
) -> Optional[Dict[str, Any]]:
    """Convenience: build + record a refresh sample (+ CS-2 file log)."""
    if not preferred:
        return None
    kind = "refresh"
    r = str(reason or "").lower()
    if "dice" in r:
        kind = "post_dice"
    elif "end" in r or "advance" in r:
        kind = "end_turn"
    sample = make_strategy_history_sample(
        game, player, preferred, reason=reason, sample_kind=kind
    )
    prev = _prev_history_sample(player)
    # Detect mid-turn way change vs previous sample this turn
    try:
        if prev:
            if (
                prev.get("round") == sample.get("round")
                and prev.get("turn") == sample.get("turn")
                and prev.get("way_id") != sample.get("way_id")
                and sample.get("way_id") is not None
            ):
                sample["sample_kind"] = "way_change"
                sample["prev_way_id"] = prev.get("way_id")
    except Exception:
        pass
    record_strategy_history_sample(player, sample)
    # CS-2: always append detailed line (even if memory ring deduped the sample)
    _emit_strategy_cs_log(game, player, preferred, sample, prev_sample=prev)
    return sample


def mark_end_of_turn_sample(game: Any, player: Any) -> Optional[Dict[str, Any]]:
    """Stamp an end-of-turn sample from current strategic_direction (before advance)."""
    if player is None:
        return None
    preferred = getattr(player, "strategic_direction", None)
    if not isinstance(preferred, Mapping) or not preferred:
        return None
    sample = make_strategy_history_sample(
        game,
        player,
        preferred,
        reason="end_turn",
        sample_kind="end_turn",
    )
    prev = _prev_history_sample(player)
    record_strategy_history_sample(player, sample)
    _emit_strategy_cs_log(game, player, preferred, sample, prev_sample=prev)
    return sample


def _format_turns_delta(prev: Optional[float], cur: Optional[float]) -> str:
    if prev is None or cur is None:
        return ""
    d = cur - prev
    if abs(d) < 0.05:
        return "(=)"
    if d > 0:
        return f"(+{d:.1f}t worse)"
    return f"({d:.1f}t better)"


def _group_key(sample: Mapping[str, Any]) -> Tuple[int, int]:
    return (_safe_int(sample.get("round"), 0), _safe_int(sample.get("turn"), 0))


def reload_strategy_history_from_cs_log(
    game: Any,
    *,
    filename: Optional[str] = None,
    max_samples: int = MAX_SAMPLES_PER_PLAYER,
    replace: bool = True,
) -> Dict[str, Any]:
    """CS-3: rebuild each player's STR history samples from FILENAME_CS JSONL.

    Safe no-op when the log is missing, game_id is empty, or parse fails.
    Only includes rows for this ``game.id`` (and matching sequence_number when
    present), per player, up to the loaded ``(round, turn)`` so post-save play
    does not leak into a mid-game reload.

    Returns ``{ok, path, loaded_by_player, error, rows_scanned}``.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "path": "",
        "loaded_by_player": {},
        "error": "",
        "rows_scanned": 0,
    }
    if game is None:
        result["error"] = "no game"
        return result

    game_id = str(getattr(game, "id", "") or "").strip()
    if not game_id:
        result["error"] = "game has no id"
        return result

    try:
        from core.strategy_cs_log import (
            cs_log_path,
            cs_row_to_history_sample,
            filter_cs_rows_for_player,
            iter_cs_log_rows,
        )
    except Exception as exc:
        result["error"] = f"import: {exc}"
        return result

    path = cs_log_path(filename)
    result["path"] = path
    try:
        rows = iter_cs_log_rows(filename=filename)
    except Exception as exc:
        result["error"] = str(exc)
        return result
    result["rows_scanned"] = len(rows)
    if not rows:
        result["ok"] = True
        result["error"] = "empty or missing log"
        return result

    seq = None
    try:
        seq = int(getattr(game, "sequence_number"))
    except Exception:
        seq = None
    try:
        max_r = int(getattr(game, "round", 0) or 0)
        max_t = int(getattr(game, "turn", 0) or 0)
    except Exception:
        max_r, max_t = 0, 0

    loaded: Dict[str, int] = {}
    for player in list(getattr(game, "players", []) or []):
        if player is None:
            continue
        try:
            pid = int(getattr(player, "id"))
        except Exception:
            continue
        matched = filter_cs_rows_for_player(
            rows,
            game_id=game_id,
            player_id=pid,
            sequence_number=seq,
            max_round=max_r,
            max_turn=max_t,
        )
        samples = [cs_row_to_history_sample(r) for r in matched]
        # Keep tail of ring buffer
        cap = max(1, int(max_samples or MAX_SAMPLES_PER_PLAYER))
        samples = samples[-cap:]
        try:
            existing = list(getattr(player, "strategy_history_samples", None) or [])
        except Exception:
            existing = []
        if replace or not existing:
            try:
                setattr(player, "strategy_history_samples", samples)
            except Exception:
                continue
        else:
            # Merge: append only samples not already present (by R/T/way/ts)
            seen = set()
            merged: List[Dict[str, Any]] = []
            for s in existing + samples:
                if not isinstance(s, Mapping):
                    continue
                key = (
                    s.get("round"),
                    s.get("turn"),
                    s.get("way_id"),
                    s.get("turns"),
                    s.get("reason"),
                    s.get("ts"),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(dict(s))
            try:
                setattr(player, "strategy_history_samples", merged[-cap:])
            except Exception:
                continue
        loaded[str(pid)] = len(samples)

    result["ok"] = True
    result["loaded_by_player"] = loaded
    return result


def format_strategy_history_for_str(
    player: Any,
    *,
    current_round: int,
    current_turn: int,
    max_turns: int = MAX_TURNS_IN_HIST,
    max_rounds: int = 6,
) -> Dict[str, str]:
    """Build compact Hist lines for the STR tab (S3: **round-level only**).

    Format: ``Hist: R1: 29 34.2t | R2: 29 33.2t``
    Optional second hist row when many rounds (3 + 3).
    No default R1T1 noise; mid-turn flips stay off the hist line.
    """
    out = {
        "hist_line": "",
        "hist_line_2": "",
        "this_turn_line": "",
        "now_line": "",
    }
    del current_turn  # turn-level hist removed in S3
    try:
        samples = [
            dict(s)
            for s in list(getattr(player, "strategy_history_samples", []) or [])
            if isinstance(s, Mapping)
        ]
    except Exception:
        samples = []
    if not samples:
        # Fallback: raw strategic_direction_history (way_id only)
        try:
            raw = list(getattr(player, "strategic_direction_history", []) or [])
            for d in raw[-12:]:
                if not isinstance(d, Mapping):
                    continue
                samples.append(
                    {
                        "round": d.get("strategy_context_round") or d.get("round"),
                        "turn": d.get("strategy_context_turn") or d.get("turn"),
                        "way_id": _way_id_from(d),
                        "turns": _safe_float(
                            d.get("risk_adjusted_total_expected_own_turns")
                            or d.get("total_expected_own_turns")
                        ),
                        "reason": _short_reason(
                            str(d.get("strategy_context_reason") or d.get("reason") or "")
                        ),
                        "sample_kind": "legacy",
                    }
                )
        except Exception:
            pass
    if not samples:
        return out

    # Group samples by round; prefer last sample of each round (end-of-round-ish)
    by_round: Dict[int, List[Dict[str, Any]]] = {}
    order: List[int] = []
    for s in samples:
        r = _safe_int(s.get("round"), 0)
        if r not in by_round:
            by_round[r] = []
            order.append(r)
        by_round[r].append(s)

    # One representative sample per round: prefer end_turn, else last sample
    round_reps: List[Tuple[int, Dict[str, Any]]] = []
    for r in order:
        items = by_round.get(r) or []
        if not items:
            continue
        chosen = items[-1]
        for s in reversed(items):
            if str(s.get("sample_kind") or "") == "end_turn":
                chosen = s
                break
        if chosen.get("way_id") is None and chosen.get("turns") is None:
            continue
        round_reps.append((r, chosen))

    # Keep last max_rounds rounds
    cap = max(1, int(max_rounds or 6))
    window = round_reps[-cap:]

    def _seg(r: int, s: Mapping[str, Any]) -> str:
        way = s.get("way_id")
        turns = s.get("turns")
        if way is None and turns is None:
            return f"R{r}: -"
        if way is None:
            try:
                return f"R{r}: {float(turns):.1f}t"
            except Exception:
                return f"R{r}: -"
        if turns is None:
            return f"R{r}: {way}"
        try:
            return f"R{r}: {way} {float(turns):.1f}t"
        except Exception:
            return f"R{r}: {way}"

    segs = [_seg(r, s) for r, s in window]
    if not segs:
        pass
    elif len(segs) <= 3:
        out["hist_line"] = "Hist: " + " | ".join(segs)
    else:
        # Two rows × up to 3 rounds each when many rounds
        mid = (len(segs) + 1) // 2
        if mid > 3:
            mid = 3
        # Prefer last 6: first row older 3, second row newer 3
        older = segs[:-3] if len(segs) > 3 else []
        newer = segs[-3:] if len(segs) > 3 else segs
        if older:
            out["hist_line"] = "Hist: " + " | ".join(older[-3:])
            # G7: indent line 2 so content aligns under first segment after "Hist: "
            out["hist_line_2"] = "      " + " | ".join(newer)  # 6 spaces == len("Hist: ")
        else:
            out["hist_line"] = "Hist: " + " | ".join(segs)

    # Now line from latest sample (compact; no turn-level this_turn by default)
    last = samples[-1]
    way = last.get("way_id")
    turns = last.get("turns")
    bits = []
    if way is not None:
        bits.append(f"now way {way}")
    if turns is not None:
        try:
            bits.append(f"{float(turns):.1f}t")
        except Exception:
            pass
    # Δ vs previous sample turns
    if len(samples) >= 2:
        prev_t = samples[-2].get("turns")
        dtxt = _format_turns_delta(
            _safe_float(prev_t) if prev_t is not None else None,
            _safe_float(turns) if turns is not None else None,
        )
        if dtxt:
            bits.append(dtxt)
    if bits:
        out["now_line"] = " | ".join(bits)

    return out


__all__ = [
    "make_strategy_history_sample",
    "record_strategy_history_sample",
    "record_from_refresh",
    "mark_end_of_turn_sample",
    "reload_strategy_history_from_cs_log",
    "format_strategy_history_for_str",
    "MAX_SAMPLES_PER_PLAYER",
    "MAX_TURNS_IN_HIST",
]
