"""P-pack: lightweight wall-clock spans + AI pipeline busy flag.

Design (see docs/plan_of_enhancements_after_test_28jul.md §PR-P):

* ``game.last_perf_trace`` — recent spans for the current/last pipeline (last N)
* ``game.perf_history`` — capped session ring for Phase0 / post-hoc top-K
* ``game.ai_pipeline_busy`` — Continue gate while AI strategy/plan work runs
* Optional Events spike when a span exceeds ``PERF_SPIKE_MS``

No separate post-game summarizer required for v1; ``summarize_perf`` is a pure
helper for F9 / optional GO dump.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

PERF_HISTORY_MAX: int = 200
PERF_LAST_TRACE_MAX: int = 40
PERF_SPIKE_MS: float = 200.0
# P2-C: auto Phase0 when any span in the current AI pipeline is this slow
PERF_AUTO_SAVE_MS: float = 2000.0
PHASE0_AUTO_SAVE_ENABLED: bool = True


def ensure_perf_fields(game: Any) -> None:
    """Idempotent init of runtime perf fields on a Game (or stub)."""
    if not hasattr(game, "last_perf_trace") or not isinstance(
        getattr(game, "last_perf_trace", None), list
    ):
        try:
            game.last_perf_trace = []
        except Exception:
            pass
    if not hasattr(game, "perf_history") or not isinstance(
        getattr(game, "perf_history", None), list
    ):
        try:
            game.perf_history = []
        except Exception:
            pass
    if not hasattr(game, "ai_pipeline_busy"):
        try:
            game.ai_pipeline_busy = False
        except Exception:
            pass
    if not hasattr(game, "ai_pipeline_busy_reason"):
        try:
            game.ai_pipeline_busy_reason = ""
        except Exception:
            pass
    if not hasattr(game, "_ai_pipeline_busy_depth"):
        try:
            game._ai_pipeline_busy_depth = 0
        except Exception:
            pass
    if not hasattr(game, "phase0_save_busy"):
        try:
            game.phase0_save_busy = False
        except Exception:
            pass
    if not hasattr(game, "last_perf_summary"):
        try:
            game.last_perf_summary = None
        except Exception:
            pass
    if not hasattr(game, "_perf_pipeline_gen"):
        try:
            game._perf_pipeline_gen = 0
        except Exception:
            pass
    if not hasattr(game, "_phase0_auto_saved_pipeline_gen"):
        try:
            game._phase0_auto_saved_pipeline_gen = None
        except Exception:
            pass
    if not hasattr(game, "last_phase0_auto_save"):
        try:
            game.last_phase0_auto_save = None
        except Exception:
            pass
    if not hasattr(game, "phase0_auto_save_enabled"):
        # Per-game override; module PHASE0_AUTO_SAVE_ENABLED is the global default
        try:
            game.phase0_auto_save_enabled = None  # None → use module default
        except Exception:
            pass
    if not hasattr(game, "ui_play_continue_latched"):
        try:
            game.ui_play_continue_latched = False
        except Exception:
            pass
    if not hasattr(game, "ui_play_continue_latch_reason"):
        try:
            game.ui_play_continue_latch_reason = ""
        except Exception:
            pass


def is_ai_pipeline_busy(game: Any) -> bool:
    """True while nested AI work or Phase0 save holds the UI gate (P2-A)."""
    try:
        if bool(getattr(game, "ai_pipeline_busy", False)):
            return True
    except Exception:
        pass
    try:
        if bool(getattr(game, "phase0_save_busy", False)):
            return True
    except Exception:
        pass
    return False


def is_ui_input_busy(game: Any) -> bool:
    """P2-A / P3-A: Play/Continue disabled for pipeline, Phase0 save, or press latch."""
    if is_ai_pipeline_busy(game):
        return True
    try:
        if bool(getattr(game, "ui_play_continue_latched", False)):
            return True
    except Exception:
        pass
    return False


def latch_play_continue_disabled(
    game: Any,
    reason: str = "",
    *,
    redraw: bool = False,
) -> None:
    """P3-A: force PLAY + Continue inactive in the button registry.

    Call at the start of a PLAY/Continue accept, *before* heavy work, so a
    second click cannot see an active button and the chrome can grey out.

    When ``redraw`` is True, attempt an immediate grey paint + display update
    so the user sees disabled state during a long synchronous freeze.
    """
    ensure_perf_fields(game)
    try:
        game.ui_play_continue_latched = True
        if reason:
            game.ui_play_continue_latch_reason = str(reason)
    except Exception:
        pass
    gui = getattr(game, "gui", None)
    if gui is not None and hasattr(gui, "set_button"):
        try:
            gui.set_button("next_turn2", False)
        except Exception:
            pass
        try:
            gui.set_button("continue_ai", False)
        except Exception:
            pass
    if redraw:
        try:
            from gui.gui_human_player import GUIHumanPlayer

            hp = GUIHumanPlayer()
            hp.button_next_turn2(game, False)
            # Grey the right slot as Continue (AI) without re-enabling it.
            # Human End is cleared by clear_right_action_slot inside button_continue.
            try:
                if str(getattr(game, "phase", "") or "") == "Execution":
                    hp.button_continue(game, False)
            except Exception:
                try:
                    if gui is not None:
                        gui.set_button("continue_ai", False)
                        gui.set_button("end_turn", False)
                except Exception:
                    pass
            # Immediate wait cue while the main thread freezes (Execution only).
            try:
                if str(getattr(game, "phase", "") or "") == "Execution":
                    hp.draw_busy_status(game)
            except Exception:
                pass
            try:
                import pygame

                pygame.display.update()
            except Exception:
                pass
        except Exception:
            pass


def clear_play_continue_latch(game: Any) -> None:
    """Clear the press latch (busy pipeline flag is independent)."""
    try:
        game.ui_play_continue_latched = False
        game.ui_play_continue_latch_reason = ""
    except Exception:
        pass


@contextmanager
def play_continue_busy_scope(game: Any, reason: str = "") -> Iterator[None]:
    """P3-A: latch + outer pipeline busy for a PLAY/Continue click body.

    Nested-safe with inner ``ai_pipeline_busy_scope`` / ``set_ai_pipeline_busy``.
    Clears the press latch on exit even if pipeline depth remains (should not).
    """
    latch_play_continue_disabled(game, reason=reason, redraw=True)
    with ai_pipeline_busy_scope(game, reason=reason or "play_continue"):
        try:
            yield
        finally:
            clear_play_continue_latch(game)


def set_ai_pipeline_busy(game: Any, busy: bool, reason: str = "") -> None:
    """Nested-safe busy flag: enter increments depth; exit decrements to zero."""
    ensure_perf_fields(game)
    try:
        depth = int(getattr(game, "_ai_pipeline_busy_depth", 0) or 0)
    except Exception:
        depth = 0
    if busy:
        depth += 1
        try:
            game._ai_pipeline_busy_depth = depth
            game.ai_pipeline_busy = True
            if reason:
                game.ai_pipeline_busy_reason = str(reason)
        except Exception:
            pass
    else:
        depth = max(0, depth - 1)
        try:
            game._ai_pipeline_busy_depth = depth
            if depth == 0:
                game.ai_pipeline_busy = False
                game.ai_pipeline_busy_reason = ""
            elif reason:
                # keep outer reason while nested
                pass
        except Exception:
            pass


def begin_perf_pipeline(game: Any, reason: str = "") -> int:
    """Start an outer AI pipeline: new generation + clear per-pipeline span list."""
    ensure_perf_fields(game)
    try:
        gen = int(getattr(game, "_perf_pipeline_gen", 0) or 0) + 1
    except Exception:
        gen = 1
    try:
        game._perf_pipeline_gen = gen
        game._perf_pipeline_reason = str(reason or "")
        game.last_perf_trace = []
    except Exception:
        pass
    return gen


def max_span_ms_from_trace(
    trace: Optional[Sequence[Mapping[str, Any]]] = None,
) -> tuple[float, Optional[Dict[str, Any]]]:
    """Return (max_ms, top_span_entry) from a span list."""
    best_ms = 0.0
    best: Optional[Dict[str, Any]] = None
    for row in list(trace or []):
        if not isinstance(row, Mapping):
            continue
        try:
            ms = float(row.get("ms") or 0.0)
        except Exception:
            ms = 0.0
        if ms >= best_ms:
            best_ms = ms
            best = dict(row)
    return best_ms, best


def should_auto_save_phase0_for_pipeline(
    game: Any,
    *,
    threshold_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Decide whether P2-C auto Phase0 should fire for the current pipeline.

    Does not write files. Pure gate used by tests and ``maybe_auto_save_*``.
    """
    ensure_perf_fields(game)
    thr = float(PERF_AUTO_SAVE_MS if threshold_ms is None else threshold_ms)
    enabled_global = bool(PHASE0_AUTO_SAVE_ENABLED)
    per_game = getattr(game, "phase0_auto_save_enabled", None)
    enabled = enabled_global if per_game is None else bool(per_game)
    out: Dict[str, Any] = {
        "should_save": False,
        "enabled": enabled,
        "threshold_ms": thr,
        "max_ms": 0.0,
        "top_span": None,
        "pipeline_gen": int(getattr(game, "_perf_pipeline_gen", 0) or 0),
        "reason": "",
    }
    if not enabled:
        out["reason"] = "disabled"
        return out
    try:
        if bool(getattr(game, "phase0_save_busy", False)):
            out["reason"] = "phase0_save_busy"
            return out
    except Exception:
        pass
    gen = out["pipeline_gen"]
    already = getattr(game, "_phase0_auto_saved_pipeline_gen", None)
    if already is not None and int(already) == int(gen) and gen > 0:
        out["reason"] = "already_saved_this_pipeline"
        return out
    max_ms, top = max_span_ms_from_trace(getattr(game, "last_perf_trace", None))
    out["max_ms"] = float(max_ms)
    out["top_span"] = top
    if max_ms < thr:
        out["reason"] = "below_threshold"
        return out
    out["should_save"] = True
    out["reason"] = "slow_span"
    return out


def maybe_auto_save_phase0_after_pipeline(game: Any) -> Dict[str, Any]:
    """P2-C: after outer pipeline exits, save one Phase0 if max span ≥ threshold.

    Debounced to one file per ``_perf_pipeline_gen``. Uses
    ``refresh_before_capture=False`` so capture does not re-run strategy work
    or recurse into another pipeline.
    """
    decision = should_auto_save_phase0_for_pipeline(game)
    if not decision.get("should_save"):
        return {
            "ok": False,
            "skipped": True,
            **decision,
        }
    gen = int(decision.get("pipeline_gen") or 0)
    # Latch before write so a nested failure cannot double-fire
    try:
        game._phase0_auto_saved_pipeline_gen = gen
    except Exception:
        pass

    max_ms = float(decision.get("max_ms") or 0.0)
    top = decision.get("top_span") if isinstance(decision.get("top_span"), Mapping) else {}
    top_name = str((top or {}).get("name") or "span")
    try:
        r = int(getattr(game, "round", 0) or 0)
        t = int(getattr(game, "turn", 0) or 0)
    except Exception:
        r, t = 0, 0
    pid = "?"
    try:
        getter = getattr(game, "get_current_player", None)
        player = getter() if callable(getter) else None
        if player is not None and getattr(player, "id", None) is not None:
            pid = str(int(player.id))
            color = str(getattr(player, "color", "") or "")
            if color:
                pid = f"{pid}{color}"
    except Exception:
        pass
    label = f"auto_slow_{int(max_ms)}ms_R{r}T{t}_P{pid}"
    result: Dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "auto": True,
        "label": label,
        "max_ms": max_ms,
        "top_span_name": top_name,
        "pipeline_gen": gen,
        "threshold_ms": decision.get("threshold_ms"),
    }
    try:
        from core.phase0_baseline_hooks import save_phase0_baseline

        save_out = save_phase0_baseline(
            game,
            label=label,
            reason="auto_slow_span",
            refresh_before_capture=False,
            force_refresh=False,
        )
        if isinstance(save_out, Mapping):
            result.update(dict(save_out))
        result["auto"] = True
        result["max_ms"] = max_ms
        result["top_span_name"] = top_name
        result["pipeline_gen"] = gen
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)

    try:
        game.last_phase0_auto_save = dict(result)
    except Exception:
        pass

    # Quiet Events line (same style as span spikes)
    try:
        path = result.get("baseline_path") or ""
        msg = f"DBG: auto Phase0 {int(max_ms)}ms ({top_name})"
        if path:
            # basename only to keep tweet short
            try:
                from pathlib import Path

                msg = f"{msg} → {Path(str(path)).name}"
            except Exception:
                pass
        emit = getattr(game, "emit_twitter_event", None)
        if callable(emit):
            emit(None, msg[:180])
    except Exception:
        pass
    return result


@contextmanager
def ai_pipeline_busy_scope(game: Any, reason: str = "") -> Iterator[None]:
    """Mark AI pipeline busy for the duration of a heavy block (nested-safe).

    Outer enter (depth 0→1) starts a new perf pipeline generation and clears
    ``last_perf_trace``. Outer exit (depth 1→0) may auto-save Phase0 (P2-C).
    """
    ensure_perf_fields(game)
    try:
        depth_before = int(getattr(game, "_ai_pipeline_busy_depth", 0) or 0)
    except Exception:
        depth_before = 0
    outer = depth_before == 0
    if outer:
        begin_perf_pipeline(game, reason=reason)
    set_ai_pipeline_busy(game, True, reason=reason)
    try:
        yield
    finally:
        set_ai_pipeline_busy(game, False)
        try:
            depth_after = int(getattr(game, "_ai_pipeline_busy_depth", 0) or 0)
        except Exception:
            depth_after = 0
        if outer and depth_after == 0:
            try:
                maybe_auto_save_phase0_after_pipeline(game)
            except Exception:
                pass


@contextmanager
def phase0_save_busy_scope(game: Any, reason: str = "phase0_save") -> Iterator[None]:
    """P2-A: hold Play/Continue for entire Phase0 capture (refresh + write)."""
    ensure_perf_fields(game)
    try:
        game.phase0_save_busy = True
        if reason:
            # Surface on same reason field when not already mid-pipeline
            if not bool(getattr(game, "ai_pipeline_busy", False)):
                game.ai_pipeline_busy_reason = str(reason)
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            game.phase0_save_busy = False
            if not bool(getattr(game, "ai_pipeline_busy", False)):
                if str(getattr(game, "ai_pipeline_busy_reason", "") or "") == str(reason):
                    game.ai_pipeline_busy_reason = ""
        except Exception:
            pass


def record_perf_span(
    game: Any,
    name: str,
    ms: float,
    meta: Optional[Mapping[str, Any]] = None,
    *,
    emit_spike: bool = True,
    spike_ms: float = PERF_SPIKE_MS,
) -> Dict[str, Any]:
    """Append one span to last_perf_trace + perf_history; optional Events spike."""
    ensure_perf_fields(game)
    entry: Dict[str, Any] = {
        "name": str(name or "span"),
        "ms": round(float(ms), 2),
        "meta": dict(meta) if isinstance(meta, Mapping) else {},
    }
    try:
        entry["round"] = getattr(game, "round", None)
        entry["turn"] = getattr(game, "turn", None)
        entry["phase"] = getattr(game, "phase", None)
        entry["state"] = getattr(game, "state", None)
    except Exception:
        pass

    try:
        trace = list(getattr(game, "last_perf_trace", []) or [])
        trace.append(entry)
        game.last_perf_trace = trace[-int(PERF_LAST_TRACE_MAX) :]
    except Exception:
        pass

    try:
        hist = list(getattr(game, "perf_history", []) or [])
        hist.append(entry)
        game.perf_history = hist[-int(PERF_HISTORY_MAX) :]
    except Exception:
        pass

    if emit_spike and float(ms) >= float(spike_ms):
        _emit_spike_event(game, entry)

    return entry


def _emit_spike_event(game: Any, entry: Mapping[str, Any]) -> None:
    """Optional DBG line when a span is slow (Events feed)."""
    try:
        name = str(entry.get("name") or "span")
        ms = entry.get("ms")
        msg = f"DBG: {name} {ms}ms"
        emit = getattr(game, "emit_twitter_event", None)
        if callable(emit):
            emit(None, msg[:180])
    except Exception:
        pass


@contextmanager
def timed_span(
    game: Any,
    name: str,
    meta: Optional[Mapping[str, Any]] = None,
    *,
    emit_spike: bool = True,
) -> Iterator[Dict[str, Any]]:
    """Context manager: time a block and record a span.

    Yields a mutable dict so callers can attach meta before exit::

        with timed_span(game, "refresh_strategy_context") as span:
            ...
            span["meta"]["reason"] = reason
    """
    ensure_perf_fields(game)
    bag: Dict[str, Any] = {"meta": dict(meta) if isinstance(meta, Mapping) else {}}
    t0 = time.perf_counter()
    try:
        yield bag
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        extra = bag.get("meta") if isinstance(bag.get("meta"), dict) else {}
        record_perf_span(
            game,
            name,
            ms,
            meta=extra,
            emit_spike=emit_spike,
        )


def summarize_perf(
    history: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    top_n: int = 10,
) -> Dict[str, Any]:
    """Distill span history into top names by max/total ms (pure helper)."""
    rows = [dict(x) for x in (history or []) if isinstance(x, Mapping)]
    by_name: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        name = str(r.get("name") or "span")
        try:
            ms = float(r.get("ms") or 0.0)
        except Exception:
            ms = 0.0
        bucket = by_name.setdefault(
            name, {"name": name, "count": 0, "total_ms": 0.0, "max_ms": 0.0}
        )
        bucket["count"] += 1
        bucket["total_ms"] = round(float(bucket["total_ms"]) + ms, 2)
        bucket["max_ms"] = round(max(float(bucket["max_ms"]), ms), 2)

    ranked = sorted(
        by_name.values(),
        key=lambda b: (float(b.get("max_ms") or 0), float(b.get("total_ms") or 0)),
        reverse=True,
    )
    return {
        "span_count": len(rows),
        "unique_names": len(by_name),
        "top_spans": ranked[: max(1, int(top_n or 10))],
        "total_ms": round(sum(float(r.get("ms") or 0) for r in rows), 2),
    }


def snapshot_perf_for_phase0(game: Any) -> Dict[str, Any]:
    """Compact payload for F9 / Phase0 JSON."""
    ensure_perf_fields(game)
    history = list(getattr(game, "perf_history", []) or [])
    last = list(getattr(game, "last_perf_trace", []) or [])
    summary = summarize_perf(history, top_n=10)
    max_ms, top = max_span_ms_from_trace(last)
    try:
        game.last_perf_summary = summary
    except Exception:
        pass
    return {
        "ai_pipeline_busy": bool(getattr(game, "ai_pipeline_busy", False)),
        "ai_pipeline_busy_reason": str(getattr(game, "ai_pipeline_busy_reason", "") or ""),
        "ai_pipeline_busy_depth": int(getattr(game, "_ai_pipeline_busy_depth", 0) or 0),
        "phase0_save_busy": bool(getattr(game, "phase0_save_busy", False)),
        "ui_input_busy": is_ui_input_busy(game),
        "last_perf_trace": last,
        "perf_history_tail": history[-40:],
        "perf_summary": summary,
        # P2-C
        "perf_pipeline_gen": int(getattr(game, "_perf_pipeline_gen", 0) or 0),
        "perf_auto_save_ms": float(PERF_AUTO_SAVE_MS),
        "phase0_auto_save_enabled": bool(PHASE0_AUTO_SAVE_ENABLED)
        if getattr(game, "phase0_auto_save_enabled", None) is None
        else bool(getattr(game, "phase0_auto_save_enabled")),
        "pipeline_max_span_ms": float(max_ms),
        "pipeline_top_span": top,
        "last_phase0_auto_save": getattr(game, "last_phase0_auto_save", None),
    }
