"""Phase L give-up escape: durable specials-dead episode after LA/LR fire.

When L6 give-up fires, sticky is cleared once — but L2 can re-lock the same
LR/LA Victory-Way. An active episode tells portfolio (WP2) and sticky/divert
(WP3) to prefer ways that do **not** need the dead special.

See ``docs/PhaseL_giveup_escape_plan.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Soft demotion when every audit still needs the dead special (hard filter empty)
SPECIALS_DEAD_SOFT_RANK_PENALTY: float = 50.0


def _safe_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        return int(float(v))
    except Exception:
        return default


def is_giveup_escape_enabled(constants_module: Any = None) -> bool:
    """Operator gate for portfolio filter + episode policy (WP1/WP2)."""
    try:
        C = constants_module
        if C is None:
            from core import constants as C  # type: ignore
        return bool(getattr(C, "GIVEUP_ESCAPE_ENABLED", True))
    except Exception:
        return True


def get_specials_dead_episode(player: Any) -> Dict[str, Any]:
    """Return a copy of the player's specials-dead episode (or inactive empty)."""
    raw = getattr(player, "specials_dead_episode", None) if player is not None else None
    if isinstance(raw, Mapping) and raw:
        out = dict(raw)
        out.setdefault("active", False)
        out.setdefault("kill_la", False)
        out.setdefault("kill_lr", False)
        out.setdefault("la_giveup_fired", False)
        out.setdefault("lr_giveup_fired", False)
        return out
    return {
        "active": False,
        "kill_la": False,
        "kill_lr": False,
        "source": None,
        "from_way_id": None,
        "score": None,
        "theta": None,
        "round": None,
        "turn": None,
        "freeze_id": None,
        "released": False,
        "release_reason": None,
        # Option (2): at most one L6 give-up fire per special while that kill flag is active
        "la_giveup_fired": False,
        "lr_giveup_fired": False,
    }


def episode_kill_flags(player: Any) -> Tuple[bool, bool]:
    """``(kill_la, kill_lr)`` when episode active; else ``(False, False)``."""
    ep = get_specials_dead_episode(player)
    if not ep.get("active"):
        return False, False
    return bool(ep.get("kill_la")), bool(ep.get("kill_lr"))


def set_specials_dead_episode(
    player: Any,
    *,
    kill_la: bool = False,
    kill_lr: bool = False,
    source: str = "",
    from_way_id: Optional[int] = None,
    score: Optional[float] = None,
    theta: Optional[float] = None,
    freeze_id: Optional[str] = None,
    game: Any = None,
    reason: str = "",
) -> Dict[str, Any]:
    """Activate or merge specials-dead flags on the player.

    Merges with an existing active episode (OR of kill_la / kill_lr).
    """
    if player is None:
        return {"active": False, "reason": "no_player"}
    if not kill_la and not kill_lr:
        return {"active": False, "reason": "no_kill_flags"}

    prev = get_specials_dead_episode(player)
    if prev.get("active"):
        kill_la = bool(kill_la or prev.get("kill_la"))
        kill_lr = bool(kill_lr or prev.get("kill_lr"))

    payload: Dict[str, Any] = {
        "active": True,
        "kill_la": bool(kill_la),
        "kill_lr": bool(kill_lr),
        "source": str(source or prev.get("source") or "giveup")[:80],
        "from_way_id": _safe_int(from_way_id)
        if from_way_id is not None
        else prev.get("from_way_id"),
        "score": float(score) if score is not None else prev.get("score"),
        "theta": float(theta) if theta is not None else prev.get("theta"),
        "round": _safe_int(getattr(game, "round", None), 0) if game is not None else prev.get("round"),
        "turn": _safe_int(getattr(game, "turn", None), 0) if game is not None else prev.get("turn"),
        "freeze_id": str(freeze_id) if freeze_id else prev.get("freeze_id"),
        "reason": str(reason or "")[:120] or None,
        "released": False,
        "release_reason": None,
        # Preserve one-fire-per-episode markers across merges
        "la_giveup_fired": bool(prev.get("la_giveup_fired")) if prev.get("active") else False,
        "lr_giveup_fired": bool(prev.get("lr_giveup_fired")) if prev.get("active") else False,
    }
    try:
        player.specials_dead_episode = dict(payload)
    except Exception:
        pass
    if game is not None:
        try:
            game.last_specials_dead_episode = dict(payload)
            game.last_specials_dead_player_id = getattr(player, "id", None)
        except Exception:
            pass
    return dict(payload)


def clear_specials_dead_episode(
    player: Any,
    *,
    reason: str = "clear",
    game: Any = None,
) -> Dict[str, Any]:
    """Fully deactivate the episode."""
    prev = get_specials_dead_episode(player)
    payload = {
        "active": False,
        "kill_la": False,
        "kill_lr": False,
        "source": prev.get("source"),
        "from_way_id": prev.get("from_way_id"),
        "score": prev.get("score"),
        "theta": prev.get("theta"),
        "round": prev.get("round"),
        "turn": prev.get("turn"),
        "freeze_id": prev.get("freeze_id"),
        "released": True,
        "release_reason": str(reason or "clear")[:120],
        "la_giveup_fired": False,
        "lr_giveup_fired": False,
    }
    if player is not None:
        try:
            player.specials_dead_episode = dict(payload)
        except Exception:
            pass
    if game is not None:
        try:
            game.last_specials_dead_episode = dict(payload)
        except Exception:
            pass
    return payload


def release_specials_dead_flags(
    player: Any,
    *,
    release_la: bool = False,
    release_lr: bool = False,
    reason: str = "",
    game: Any = None,
) -> Dict[str, Any]:
    """Clear individual kill flags; deactivate when both clear."""
    ep = get_specials_dead_episode(player)
    if not ep.get("active"):
        return ep
    kill_la = bool(ep.get("kill_la")) and not release_la
    kill_lr = bool(ep.get("kill_lr")) and not release_lr
    if not kill_la and not kill_lr:
        return clear_specials_dead_episode(
            player, reason=reason or "flags_cleared", game=game
        )
    payload = dict(ep)
    payload["kill_la"] = kill_la
    payload["kill_lr"] = kill_lr
    payload["release_reason"] = str(reason or "")[:120] or None
    # Clear one-fire markers when that special's kill flag ends (new episode can fire again)
    if release_la:
        payload["la_giveup_fired"] = False
    if release_lr:
        payload["lr_giveup_fired"] = False
    if player is not None:
        try:
            player.specials_dead_episode = dict(payload)
        except Exception:
            pass
    return payload


def mark_giveup_fired_on_episode(
    player: Any,
    special: str,
    *,
    game: Any = None,
) -> Dict[str, Any]:
    """Stamp that L6 already fired for LA or LR on the active specials-dead episode.

    Used for option (2): at most one give-up fire per kill_* episode until release.
    """
    ep = get_specials_dead_episode(player)
    if not ep.get("active"):
        return ep
    sp = str(special or "").lower()
    payload = dict(ep)
    if sp == "la":
        payload["la_giveup_fired"] = True
    else:
        payload["lr_giveup_fired"] = True
    if player is not None:
        try:
            player.specials_dead_episode = dict(payload)
        except Exception:
            pass
    if game is not None:
        try:
            game.last_specials_dead_episode = dict(payload)
        except Exception:
            pass
    return payload


def episode_blocks_giveup_refire(
    player: Any,
    special: str,
) -> bool:
    """True if escape episode already consumed one L6 fire for this special.

    When True, ``maybe_*_giveup_l2`` must not fire again until the corresponding
    kill flag is released (holds special or needs_* false).
    """
    if not is_giveup_escape_enabled():
        return False
    ep = get_specials_dead_episode(player)
    if not ep.get("active"):
        return False
    sp = str(special or "").lower()
    if sp == "la":
        return bool(ep.get("kill_la")) and bool(ep.get("la_giveup_fired"))
    return bool(ep.get("kill_lr")) and bool(ep.get("lr_giveup_fired"))


def maybe_release_specials_dead_episode(
    game: Any,
    player: Any,
    *,
    holds_la: Optional[bool] = None,
    holds_lr: Optional[bool] = None,
    needs_la: Optional[bool] = None,
    needs_lr: Optional[bool] = None,
) -> Dict[str, Any]:
    """Release episode flags when ambition ends or special is held.

    WP1 rules:
    - own hold of LA/LR → release that flag
    - needs_* False → release that flag (way no longer requires special)
    Does **not** release solely because sticky way_id changed.
    """
    ep = get_specials_dead_episode(player)
    if not ep.get("active"):
        return ep

    release_la = False
    release_lr = False
    reasons: List[str] = []

    if ep.get("kill_la"):
        if holds_la is True:
            release_la = True
            reasons.append("holds_LA")
        elif needs_la is False:
            release_la = True
            reasons.append("no_needs_LA")
    if ep.get("kill_lr"):
        if holds_lr is True:
            release_lr = True
            reasons.append("holds_LR")
        elif needs_lr is False:
            release_lr = True
            reasons.append("no_needs_LR")

    if not release_la and not release_lr:
        return ep
    return release_specials_dead_flags(
        player,
        release_la=release_la,
        release_lr=release_lr,
        reason="+".join(reasons) or "release",
        game=game,
    )


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


def _audit_rank_key(audit: Any) -> float:
    try:
        if isinstance(audit, Mapping):
            return float(audit.get("rank_key") or 0)
        return float(getattr(audit, "rank_key", 0) or 0)
    except Exception:
        return 0.0


def way_id_needs_specials(way_id: Optional[int]) -> Tuple[bool, bool]:
    """Return ``(needs_la, needs_lr)`` from the Victory-Way requirements table."""
    wid = _safe_int(way_id)
    if wid is None or wid <= 0:
        return False, False
    try:
        from core.strategy_timing import load_strategy_requirements

        for strategy in load_strategy_requirements() or []:
            try:
                sid = int(getattr(strategy, "way_id", -1))
            except Exception:
                continue
            if sid != int(wid):
                continue
            la = bool(
                getattr(strategy, "biggest_army", False)
                or getattr(strategy, "largest_army", False)
            )
            lr = bool(
                getattr(strategy, "longest_road", False)
                or getattr(strategy, "longest_route", False)
            )
            return la, lr
    except Exception:
        pass
    return False, False


def direction_blocked_by_episode(
    direction: Optional[Mapping[str, Any]],
    player: Any = None,
    *,
    episode: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
    """True if direction/way still needs a special marked dead on the episode."""
    if not is_giveup_escape_enabled():
        return False, "escape_off"
    ep = dict(episode) if isinstance(episode, Mapping) else get_specials_dead_episode(player)
    if not ep.get("active"):
        return False, "no_episode"
    kla = bool(ep.get("kill_la"))
    klr = bool(ep.get("kill_lr"))
    if not kla and not klr:
        return False, "no_flags"

    d = dict(direction or {}) if isinstance(direction, Mapping) else {}
    # Prefer explicit direction flags / requirements, then way table
    needs_la = False
    needs_lr = False
    try:
        from core.strategy_specials_divert import (
            audit_or_dir_needs_la,
            audit_or_dir_needs_lr,
        )

        if d:
            needs_la = bool(audit_or_dir_needs_la(d))
            needs_lr = bool(audit_or_dir_needs_lr(d))
    except Exception:
        pass
    wid = _safe_int(d.get("preferred_way_id") or d.get("way_id") or d.get("locked_way_id"))
    if wid is not None and (not needs_la or not needs_lr):
        t_la, t_lr = way_id_needs_specials(wid)
        needs_la = needs_la or t_la
        needs_lr = needs_lr or t_lr
    if kla and needs_la:
        return True, "needs_dead_LA"
    if klr and needs_lr:
        return True, "needs_dead_LR"
    return False, "ok"


def commitment_blocked_by_episode(
    commitment: Optional[Mapping[str, Any]],
    player: Any = None,
    *,
    episode: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
    """True if sticky lock is still on a dead-special Victory-Way."""
    if not isinstance(commitment, Mapping) or not commitment:
        return False, "no_commitment"
    synth = {
        "preferred_way_id": commitment.get("locked_way_id"),
        "way_id": commitment.get("locked_way_id"),
        "longest_road": bool(commitment.get("lr_project")),
        "biggest_army": bool(commitment.get("la_progress")),
    }
    return direction_blocked_by_episode(synth, player, episode=episode)


def is_giveup_force_divert_enabled(constants_module: Any = None) -> bool:
    """When True, episode kill flags force S5.5 divert even if assess is soft."""
    try:
        C = constants_module
        if C is None:
            from core import constants as C  # type: ignore
        if not is_giveup_escape_enabled(C):
            return False
        return bool(getattr(C, "GIVEUP_FORCE_DIVERT", True))
    except Exception:
        return True


def filter_audits_for_specials_dead(
    audits: Sequence[Any],
    episode: Optional[Mapping[str, Any]] = None,
    *,
    player: Any = None,
    kill_la: Optional[bool] = None,
    kill_lr: Optional[bool] = None,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Hard-filter audits that need dead specials; soft-demote if filter empties.

    Returns ``(audits_out, meta)``.
    """
    from core.strategy_specials_divert import filter_ways_without_specials

    if episode is None and player is not None:
        episode = get_specials_dead_episode(player)
    ep = dict(episode or {})
    kla = bool(kill_la) if kill_la is not None else bool(ep.get("kill_la"))
    klr = bool(kill_lr) if kill_lr is not None else bool(ep.get("kill_lr"))

    src = list(audits or [])
    meta: Dict[str, Any] = {
        "applied": False,
        "mode": "none",
        "kill_la": kla,
        "kill_lr": klr,
        "n_before": len(src),
        "n_after": len(src),
        "n_filtered": 0,
        "chosen_way_id": _audit_way_id(src[0]) if src else None,
        "reason": "no_flags",
    }
    if not src:
        meta["reason"] = "no_audits"
        return src, meta
    if not kla and not klr:
        return src, meta
    if not is_giveup_escape_enabled():
        meta["reason"] = "escape_flag_off"
        return src, meta

    filtered = filter_ways_without_specials(src, kill_la=kla, kill_lr=klr)
    meta["n_filtered"] = len(filtered)

    if filtered:
        # Preserve relative rank among survivors
        try:
            filtered = sorted(
                filtered,
                key=lambda a: (_audit_rank_key(a), _audit_way_id(a) or 0),
            )
        except Exception:
            pass
        meta["applied"] = True
        meta["mode"] = "hard_filter"
        meta["n_after"] = len(filtered)
        meta["chosen_way_id"] = _audit_way_id(filtered[0])
        meta["reason"] = "filtered_non_special"
        return list(filtered), meta

    # Soft fallback: demote specials-requiring ways (all may require special)
    try:
        from core.strategy_specials_divert import (
            audit_or_dir_needs_la,
            audit_or_dir_needs_lr,
        )

        def _is_dead_special(a: Any) -> bool:
            if kla and audit_or_dir_needs_la(a):
                return True
            if klr and audit_or_dir_needs_lr(a):
                return True
            return False

        def _soft_key(a: Any) -> Tuple[int, float, int]:
            dead = 1 if _is_dead_special(a) else 0
            rk = _audit_rank_key(a)
            if dead:
                rk = rk + SPECIALS_DEAD_SOFT_RANK_PENALTY
            return (dead, rk, _audit_way_id(a) or 0)

        ordered = sorted(src, key=_soft_key)
    except Exception:
        ordered = list(src)

    meta["applied"] = True
    meta["mode"] = "soft_demote"
    meta["n_after"] = len(ordered)
    meta["chosen_way_id"] = _audit_way_id(ordered[0]) if ordered else None
    meta["reason"] = "filter_empty_soft_demote"
    return list(ordered), meta


__all__ = [
    "SPECIALS_DEAD_SOFT_RANK_PENALTY",
    "is_giveup_escape_enabled",
    "is_giveup_force_divert_enabled",
    "get_specials_dead_episode",
    "episode_kill_flags",
    "set_specials_dead_episode",
    "clear_specials_dead_episode",
    "release_specials_dead_flags",
    "mark_giveup_fired_on_episode",
    "episode_blocks_giveup_refire",
    "maybe_release_specials_dead_episode",
    "way_id_needs_specials",
    "direction_blocked_by_episode",
    "commitment_blocked_by_episode",
    "filter_audits_for_specials_dead",
]
