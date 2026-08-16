"""Phase L L6: god-view LR give-up → clear ambition + force L2.

Uses frozen Domain C thresholds from ``core.lr_giveup_config`` / constants.
Gated by ``LR_GIVEUP_L2_ENABLED``.

Fire rule (safe profile)::

  needs_LR and not holds_LR
  hopeless_score_lr ≥ θ for D consecutive own-turn strategy samples
  → latch first fire: clear sticky, force L2 explore, LR way-kill latch
  → with escape: at most **one fire per specials-dead kill_lr episode**
    (until holds LR or needs_LR false releases the flag)

Mirror of ``core.la_giveup_l2`` (LA Domain A).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from core.lr_giveup_config import (
    FREEZE_ID,
    is_giveup_l2_enabled,
    resolve_profile,
)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _sticky_way_id(player: Any) -> Optional[int]:
    try:
        sticky = getattr(player, "sticky_commitment", None)
        if isinstance(sticky, Mapping):
            w = sticky.get("locked_way_id")
            if w is not None:
                return _safe_int(w, -1) if int(w) > 0 else None
    except Exception:
        pass
    try:
        direction = getattr(player, "strategic_direction", None) or {}
        if isinstance(direction, Mapping):
            w = direction.get("preferred_way_id") or direction.get("way_id")
            if w is not None and int(w) > 0:
                return int(w)
    except Exception:
        pass
    return None


def _get_latch(player: Any) -> Dict[str, Any]:
    raw = getattr(player, "lr_giveup_latch", None) if player is not None else None
    return dict(raw) if isinstance(raw, Mapping) else {}


def _set_latch(player: Any, payload: Optional[Mapping[str, Any]]) -> None:
    if player is None:
        return
    try:
        player.lr_giveup_latch = dict(payload) if payload else None
    except Exception:
        pass


def _clear_run_state(player: Any) -> None:
    if player is None:
        return
    try:
        player.lr_giveup_run_len = 0
    except Exception:
        pass
    try:
        player.lr_giveup_last_score = None
    except Exception:
        pass


def _apply_giveup_mutation(
    game: Any,
    player: Any,
    *,
    way_id: Optional[int],
    score: float,
    theta: float,
    detail: Mapping[str, Any],
) -> Dict[str, Any]:
    """Clear sticky LR path + force L2 (same spine as S5b LR way-kill)."""
    from core.strategy_sticky import clear_sticky_commitment, flag_strategy_recalc
    from core.strategy_way_kill import _set_latch as set_way_kill_latch

    reason = "lr_giveup_theta"
    flag_strategy_recalc(
        player,
        reason,
        detail=dict(detail)
        | {
            "way_id": way_id,
            "score": score,
            "theta": theta,
            "freeze_id": FREEZE_ID,
        },
    )
    try:
        player.force_strategy_recalc = True
    except Exception:
        pass
    clear_sticky_commitment(player)
    try:
        from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

        invalidate_board_way_portfolio_cache(game, f"lr_giveup:{reason}")
    except Exception:
        pass
    # Drop LR project residue on direction if present
    try:
        direction = getattr(player, "strategic_direction", None)
        if isinstance(direction, dict):
            direction = dict(direction)
            direction.pop("lr_project", None)
            direction["longest_road"] = False
            player.strategic_direction = direction
    except Exception:
        pass
    try:
        set_way_kill_latch(
            player,
            way_id=way_id,
            kind="LR",
            game=game,
            reason=f"lr_giveup_theta:{theta}",
        )
    except Exception:
        pass
    try:
        player.last_way_kill = {
            "killed": True,
            "kind": "LR",
            "reason": reason,
            "way_id": way_id,
            "source": "lr_giveup_l2",
            "score": score,
            "theta": theta,
        }
    except Exception:
        pass
    # WP1: durable specials-dead episode (portfolio filter WP2)
    try:
        from core.specials_dead_episode import (
            is_giveup_escape_enabled,
            set_specials_dead_episode,
        )

        if is_giveup_escape_enabled():
            set_specials_dead_episode(
                player,
                kill_la=False,
                kill_lr=True,
                source="lr_giveup_l2",
                from_way_id=way_id,
                score=score,
                theta=theta,
                freeze_id=FREEZE_ID,
                game=game,
                reason=reason,
            )
            from core.specials_dead_episode import mark_giveup_fired_on_episode

            mark_giveup_fired_on_episode(player, "lr", game=game)
    except Exception:
        pass
    # Hygiene: LR flags already cleared above; stamp pending escape source
    try:
        direction = getattr(player, "strategic_direction", None)
        if isinstance(direction, dict):
            direction = dict(direction)
            direction["preference_source"] = (
                str(direction.get("preference_source") or "") + "+lr_giveup_pending"
            ).lstrip("+")
            player.strategic_direction = direction
    except Exception:
        pass
    return {
        "cleared_sticky": True,
        "force_strategy_recalc": True,
        "way_id": way_id,
    }


def maybe_lr_giveup_l2(
    game: Any,
    player: Any,
    *,
    reason: str = "",
    force_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """Evaluate LR give-up on strategy refresh.

    Fire policy: latch (same way) + with escape enabled, **one fire per**
    specials-dead ``kill_lr`` episode until that flag is released.

    Call **before** ``resolve_refresh_mode`` so ``force_strategy_recalc`` upgrades
    the same refresh to L2 explore when possible.
    """
    out: Dict[str, Any] = {
        "l6": True,
        "special": "lr",
        "enabled": False,
        "fired": False,
        "skipped": True,
        "reason": "init",
    }
    try:
        from core import constants as C
    except Exception:
        C = None  # type: ignore

    enabled = (
        bool(force_enabled)
        if force_enabled is not None
        else is_giveup_l2_enabled(C)
    )
    out["enabled"] = enabled
    if not enabled:
        out["reason"] = "flag_off"
        return out

    if player is None:
        out["reason"] = "no_player"
        return out
    if game is not None and str(getattr(game, "phase", "") or "") != "Execution":
        out["reason"] = "not_execution"
        return out

    profile = resolve_profile(constants_module=C)
    theta = float(profile.get("theta") or 0.75)
    dwell = max(1, int(profile.get("dwell") or 1))
    latch_first = bool(profile.get("latch_first", True))
    out["profile"] = profile.get("profile")
    out["theta"] = theta
    out["dwell"] = dwell

    try:
        from core.la_lr_probe_log import build_la_lr_probe_row

        row = build_la_lr_probe_row(
            game,
            player,
            reason=str(reason or "lr_giveup_check"),
            event="lr_giveup_check",
        )
        lr = dict(row.get("lr") or {}) if isinstance(row, Mapping) else {}
    except Exception as exc:
        out["reason"] = f"probe_build_error:{exc}"
        return out

    needs = bool(lr.get("needs"))
    holds = bool(lr.get("holds"))
    out["needs_LR"] = needs
    out["holds_LR"] = holds
    out["needs_reason"] = lr.get("needs_reason")
    way_id = _sticky_way_id(player)
    out["way_id"] = way_id

    # WP1: release specials-dead episode when LR ambition ends or is held
    try:
        from core.specials_dead_episode import maybe_release_specials_dead_episode

        maybe_release_specials_dead_episode(
            game, player, holds_lr=holds, needs_lr=needs
        )
    except Exception:
        pass

    if not needs:
        _clear_run_state(player)
        if _get_latch(player):
            _set_latch(player, None)
        out["reason"] = "no_needs_LR"
        out["skipped"] = True
        return out

    if holds:
        _clear_run_state(player)
        out["reason"] = "already_holds_LR"
        out["skipped"] = True
        return out

    try:
        from core.batch.la_lr_godview import hopeless_score_lr

        score = float(hopeless_score_lr(lr))
    except Exception as exc:
        out["reason"] = f"score_error:{exc}"
        return out

    out["score"] = score
    try:
        player.lr_giveup_last_score = score
    except Exception:
        pass

    # Option (2): block re-fire while specials-dead kill_lr episode already fired
    try:
        from core.specials_dead_episode import episode_blocks_giveup_refire

        if episode_blocks_giveup_refire(player, "lr"):
            out["reason"] = "one_fire_per_episode"
            out["skipped"] = True
            out["one_fire_per_episode"] = True
            out["run_len"] = _safe_int(getattr(player, "lr_giveup_run_len", 0), 0)
            return out
    except Exception:
        pass

    latch = _get_latch(player)
    if latch_first and latch.get("active"):
        latched_way = latch.get("way_id")
        if latched_way is None or way_id is None or int(latched_way) == int(way_id):
            out["reason"] = "latched"
            out["skipped"] = True
            out["latched"] = True
            out["run_len"] = _safe_int(getattr(player, "lr_giveup_run_len", 0), 0)
            return out
        # Way changed: clear way-latch, but episode one-fire still applies above
        _set_latch(player, None)
        _clear_run_state(player)

    if score < theta:
        try:
            player.lr_giveup_run_len = 0
        except Exception:
            pass
        out["reason"] = "below_theta"
        out["skipped"] = True
        out["run_len"] = 0
        return out

    run_len = _safe_int(getattr(player, "lr_giveup_run_len", 0), 0) + 1
    try:
        player.lr_giveup_run_len = run_len
    except Exception:
        pass
    out["run_len"] = run_len
    out["skipped"] = False

    if run_len < dwell:
        out["reason"] = "dwell_wait"
        out["fired"] = False
        return out

    # Capture run_len before reset; probe fire row uses pre-mutation snapshot
    fire_run_len = run_len
    mut = _apply_giveup_mutation(
        game,
        player,
        way_id=way_id,
        score=score,
        theta=theta,
        detail={
            "reason_call": str(reason or ""),
            "needs_reason": lr.get("needs_reason"),
            "gap": lr.get("gap"),
            "n_threats": lr.get("n_threats"),
            "path": lr.get("path"),
            "kill_recommended": lr.get("kill_recommended"),
        },
    )
    _set_latch(
        player,
        {
            "active": True,
            "way_id": way_id,
            "score": score,
            "theta": theta,
            "round": _safe_int(getattr(game, "round", 0), 0) if game is not None else 0,
            "turn": _safe_int(getattr(game, "turn", 0), 0) if game is not None else 0,
            "profile": profile.get("profile"),
            "freeze_id": FREEZE_ID,
        },
    )
    try:
        player.lr_giveup_run_len = 0
    except Exception:
        pass
    try:
        player.last_lr_giveup = {
            "fired": True,
            "score": score,
            "theta": theta,
            "way_id": way_id,
            "profile": profile.get("profile"),
            "round": _safe_int(getattr(game, "round", 0), 0) if game is not None else 0,
            "reason": str(reason or ""),
        }
    except Exception:
        pass
    if game is not None:
        try:
            game.last_lr_giveup = dict(player.last_lr_giveup)
        except Exception:
            pass
    try:
        from core.la_lr_probe_log import log_giveup_fire_event

        log_giveup_fire_event(
            game,
            player,
            special="lr",
            score=score,
            theta=theta,
            way_id=way_id,
            profile=str(profile.get("profile") or "") or None,
            freeze_id=FREEZE_ID,
            dwell=dwell,
            run_len=fire_run_len,
            reason=str(reason or "lr_giveup_theta"),
            base_row=row if isinstance(row, Mapping) else None,
            special_block=lr,
        )
    except Exception:
        pass

    out.update(
        {
            "fired": True,
            "reason": "fired",
            "mutation": mut,
            "freeze_id": FREEZE_ID,
        }
    )
    return out


__all__ = [
    "maybe_lr_giveup_l2",
]
