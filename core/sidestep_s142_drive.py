"""Headless S142 drive: a/b/c triggers → compute S142 → adopt way (lab arm).

Does not rewrite SE. Observe/compute stays in ``sidestep_board_sync``;
this module latches events, runs S142 for one seat, and stashes an external
preferred way_id for the next L2/sticky commit.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

REASON_OWN_VP = "a_own_public_vp"  # settle / city / LA / LR
REASON_OPP_BUILD = "b_opp_rsc"  # deferred opponent R/S/C
REASON_OWN_SPECIAL = "a_own_la_lr"


def is_s142_drive_enabled(game: Any = None) -> bool:
    if game is not None:
        try:
            v = getattr(game, "sidestep_s142_drive", None)
            if v is not None:
                return bool(v)
        except Exception:
            pass
    try:
        from core import constants as C

        return bool(getattr(C, "SIDESTEP_S142_DRIVE", False))
    except Exception:
        return False


def is_s142_triggers_enabled(game: Any = None) -> bool:
    """Compute+log S142 on a/b/c even without adopt (drive implies triggers)."""
    if is_s142_drive_enabled(game):
        return True
    try:
        from core import constants as C

        return bool(getattr(C, "SIDESTEP_S142_TRIGGERS", False))
    except Exception:
        return False


def get_external_preferred_way_id(player: Any) -> Optional[int]:
    if player is None:
        return None
    try:
        wid = getattr(player, "_external_preferred_way_id", None)
        if wid is None:
            return None
        i = int(wid)
        return i if i > 0 else None
    except Exception:
        return None


def set_external_preferred_way_id(player: Any, way_id: Any) -> Optional[int]:
    try:
        i = int(way_id)
    except Exception:
        i = 0
    if player is None or i <= 0:
        return None
    try:
        setattr(player, "_external_preferred_way_id", i)
    except Exception:
        return None
    return i


def clear_external_preferred_way_id(player: Any) -> None:
    if player is None:
        return
    try:
        setattr(player, "_external_preferred_way_id", None)
    except Exception:
        pass


def adopt_external_way(
    game: Any,
    player: Any,
    way_id: Any,
    *,
    reason: str = "sidestep_s142_drive",
) -> Dict[str, Any]:
    """Stash way for next L2; clear sticky so hold cannot block adopt."""
    out: Dict[str, Any] = {
        "ok": False,
        "way_id": None,
        "reason": reason,
        "cleared_sticky": False,
    }
    wid = set_external_preferred_way_id(player, way_id)
    out["way_id"] = wid
    if wid is None:
        out["error"] = "bad_way_id"
        return out
    try:
        from core.strategy_sticky import clear_sticky_commitment

        clear_sticky_commitment(player)
        out["cleared_sticky"] = True
    except Exception as exc:
        out["clear_error"] = str(exc)[:120]
    try:
        setattr(player, "force_strategy_recalc", True)
    except Exception:
        pass
    try:
        from core.strategy_explicit_recalc import mark_explicit_l2_session

        mark_explicit_l2_session(
            player,
            {"active": True, "reason": reason, "codes": [], "primary": None},
        )
    except Exception:
        pass
    out["ok"] = True
    return out


def latch_own_public_milestone(
    game: Any,
    player: Any,
    *,
    kind: str = "structure",
) -> Dict[str, Any]:
    """(a)/(c) — own settle/city or LA/LR. Immediate fire when triggers on."""
    out: Dict[str, Any] = {"ok": False, "fired": False}
    if player is None or not is_s142_triggers_enabled(game):
        return out
    reason = REASON_OWN_SPECIAL if kind in ("la", "lr", "special") else REASON_OWN_VP
    bag = run_s142_for_seat(game, player, reason=reason)
    out["ok"] = True
    out["fired"] = True
    out["result"] = bag
    return out


def latch_opp_build_for_opponents(
    game: Any,
    builder: Any,
    *,
    kind: str = "structure",
) -> Dict[str, Any]:
    """(b) — mark all other seats deferred S142 for their next own turn."""
    out: Dict[str, Any] = {"ok": False, "latched": []}
    if not is_s142_triggers_enabled(game):
        return out
    bid = getattr(builder, "id", None)
    for p in list(getattr(game, "players", None) or []):
        if p is None or getattr(p, "id", None) == bid:
            continue
        try:
            setattr(p, "_s142_pending_opp_build", True)
            setattr(p, "_s142_pending_opp_kind", str(kind or "structure"))
            out["latched"].append(getattr(p, "id", None))
        except Exception:
            continue
    out["ok"] = True
    return out


def consume_deferred_opp_build(game: Any, player: Any) -> Dict[str, Any]:
    """At own turn start: if opp-build pending, run S142 once."""
    out: Dict[str, Any] = {"ok": False, "fired": False}
    if player is None or not is_s142_triggers_enabled(game):
        return out
    pending = bool(getattr(player, "_s142_pending_opp_build", False))
    if not pending:
        out["ok"] = True
        out["skipped"] = "no_pending"
        return out
    try:
        setattr(player, "_s142_pending_opp_build", False)
    except Exception:
        pass
    bag = run_s142_for_seat(game, player, reason=REASON_OPP_BUILD)
    out["ok"] = True
    out["fired"] = True
    out["result"] = bag
    return out


def _sticky_way_id(player: Any) -> Optional[int]:
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        if isinstance(c, Mapping):
            wid = c.get("locked_way_id")
            if wid is not None:
                return int(wid)
    except Exception:
        pass
    try:
        d = getattr(player, "strategic_direction", None)
        if isinstance(d, Mapping):
            for k in ("preferred_way_id", "way_id"):
                if d.get(k) is not None:
                    return int(d.get(k))
    except Exception:
        pass
    return None


def _pln2_catalog(game: Any, player: Any) -> List[Mapping[str, Any]]:
    preferred = getattr(player, "strategic_direction", None)
    if not isinstance(preferred, Mapping):
        preferred = {}
    try:
        from core.strategy_plan_snapshot import build_plan_snapshot

        bag = build_plan_snapshot(
            game,
            player,
            preferred,
            reason="sidestep_s142_catalog",
            refresh_mode="explore",
            force=True,
        )
        return list(bag.get("catalog_all") or bag.get("catalog") or [])
    except Exception:
        return []


def _phase_for_game(game: Any) -> str:
    try:
        from core.sidestep_compare import live_stage_bundle, phase_for_round

        live = live_stage_bundle(game, None)
        # Prefer live_stage for H when available; else round band
        ls = str(live.get("live_stage") or "")
        if ls == "end":
            return "late"
        if ls in ("early", "mid"):
            return ls
    except Exception:
        pass
    try:
        from core.sidestep_compare import phase_for_round

        p = phase_for_round(int(getattr(game, "round", 0) or 0))
        return "late" if p == "end" else p
    except Exception:
        return "mid"


def run_s142_for_seat(
    game: Any,
    player: Any,
    *,
    reason: str,
) -> Dict[str, Any]:
    """Compute S142 for one seat; optionally adopt into sticky path."""
    t0 = time.perf_counter()
    out: Dict[str, Any] = {
        "ok": False,
        "reason": reason,
        "player_id": getattr(player, "id", None),
        "sticky_way_id": _sticky_way_id(player),
        "s142_way_id": None,
        "s142_side": None,
        "s142_target": None,
        "fit_n": 0,
        "fit_total": 0,
        "adopted": False,
        "elapsed_s": 0.0,
    }
    if player is None or game is None:
        out["error"] = "no_player_or_game"
        return out

    try:
        from core.sidestep_compare import live_stage_bundle

        live = live_stage_bundle(game, player)
        out["live_stage"] = live.get("live_stage")
        out["live_top_n"] = live.get("live_top_n")
        out["seat_stage"] = live.get("seat_stage")
        out["seat_vp"] = live.get("seat_vp")
    except Exception:
        pass

    phase = _phase_for_game(game)
    catalog = _pln2_catalog(game, player)
    try:
        from core.sidestep_board_sync import build_seat_sync_and_s142

        sync = build_seat_sync_and_s142(
            game,
            player,
            sticky_way_id=out["sticky_way_id"],
            catalog=catalog,
            phase=phase,
            require_confidence=True,
        )
        s142 = sync.get("s142") if isinstance(sync.get("s142"), Mapping) else {}
        out["fit_n"] = int(sync.get("n_fit") or 0)
        out["fit_total"] = int(sync.get("n_total") or 0)
        out["s142_way_id"] = s142.get("s142_way_id")
        out["s142_side"] = s142.get("s142_side")
        out["s142_target"] = s142.get("s142_target")
        out["prune"] = dict(s142.get("prune") or {})
        out["sticky_sync"] = (sync.get("sticky_sync") or {}).get("label")
        out["ok"] = bool(s142.get("ok") or out["s142_way_id"])
    except Exception as exc:
        out["error"] = str(exc)[:200]
        out["elapsed_s"] = round(time.perf_counter() - t0, 4)
        _emit_s142_line(out)
        _record_history(game, out)
        return out

    adopted = False
    if (
        is_s142_drive_enabled(game)
        and out.get("s142_way_id") is not None
    ):
        prev = out.get("sticky_way_id")
        new = out.get("s142_way_id")
        if prev is None or int(prev) != int(new):
            ad = adopt_external_way(
                game, player, new, reason=f"sidestep_s142:{reason}"
            )
            adopted = bool(ad.get("ok"))
            out["adopt"] = ad
            # Force refresh so sticky picks up external way this turn
            try:
                refresh = getattr(game, "refresh_strategy_context", None)
                if callable(refresh):
                    refresh(
                        f"sidestep_s142:{reason}",
                        force=True,
                        mode="explore",
                        allow_during_forced_flow=True,
                    )
            except Exception as exc:
                out["refresh_error"] = str(exc)[:120]
        else:
            out["adopt_skipped"] = "same_as_sticky"
    out["adopted"] = adopted
    out["elapsed_s"] = round(time.perf_counter() - t0, 4)
    _emit_s142_line(out)
    _record_history(game, out)
    return out


def _emit_s142_line(bag: Mapping[str, Any]) -> None:
    try:
        pid = bag.get("player_id")
        sticky = bag.get("sticky_way_id")
        s142 = bag.get("s142_way_id")
        prune = bag.get("prune") if isinstance(bag.get("prune"), dict) else {}
        prune_s = ""
        if prune:
            prune_s = (
                f" prune=pareto:{prune.get('pareto', 0)}"
                f"/dedupe:{prune.get('dedupe', 0)}"
                f"/lb:{prune.get('lb', 0)}"
                f"/abort:{prune.get('aborted', 0)}"
                f"/walk:{prune.get('walked', 0)}"
            )
        line = (
            f"[s142] P{pid} reason={bag.get('reason')} "
            f"live_stage={bag.get('live_stage')} seat_stage={bag.get('seat_stage')} "
            f"sticky={sticky}→S142={s142} Side={bag.get('s142_side')} "
            f"via {bag.get('s142_target')} "
            f"fit={bag.get('fit_n')}/{bag.get('fit_total')} "
            f"elapsed={bag.get('elapsed_s')}s adopted={1 if bag.get('adopted') else 0}"
            f"{prune_s}"
        )
        print(line)
        try:
            from core.constants import FILENAME_HELP

            path = f"{FILENAME_HELP}_S142.txt"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    except Exception:
        pass


def _record_history(game: Any, bag: Mapping[str, Any]) -> None:
    try:
        hist = getattr(game, "_s142_history", None)
        if not isinstance(hist, list):
            hist = []
            setattr(game, "_s142_history", hist)
        hist.append(dict(bag))
        totals = getattr(game, "_s142_timing_totals", None)
        if not isinstance(totals, dict):
            totals = {"n": 0, "elapsed_s": 0.0, "adopted": 0}
            setattr(game, "_s142_timing_totals", totals)
        totals["n"] = int(totals.get("n") or 0) + 1
        totals["elapsed_s"] = float(totals.get("elapsed_s") or 0) + float(
            bag.get("elapsed_s") or 0
        )
        if bag.get("adopted"):
            totals["adopted"] = int(totals.get("adopted") or 0) + 1
    except Exception:
        pass


__all__ = [
    "REASON_OWN_VP",
    "REASON_OPP_BUILD",
    "REASON_OWN_SPECIAL",
    "is_s142_drive_enabled",
    "is_s142_triggers_enabled",
    "get_external_preferred_way_id",
    "set_external_preferred_way_id",
    "clear_external_preferred_way_id",
    "adopt_external_way",
    "latch_own_public_milestone",
    "latch_opp_build_for_opponents",
    "consume_deferred_opp_build",
    "run_s142_for_seat",
]
