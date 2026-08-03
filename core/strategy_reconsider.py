"""P3 strategy reconsider: L0/L1/L2 gates and significance flags.

Heavy L2 board-way portfolio runs only when significance warrants it:

  (a) need_next_target — target achieved; next target (now or start of next turn)
  (b) target_blocked / race_worse — opponent board threatens way
  (c) la_lr_shock — LA/LR acquired or meaningful progress against way
  (d) off_strategy_opportunity — legal buy/build not in current way, significant ETA gain

Default path is L0 hand_only (rescore sticky/preferred ETA, no way switch).
``mode="auto"`` is the primary entry: L2 iff ``should_run_l2_explore``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

# (*) Soft switch threshold — avoid thrashing on marginal ETA gains
STRATEGY_SWITCH_MIN_ETA_GAIN: float = 1.0

# Game-stage portfolio caps (max VP among players)
PORTFOLIO_TOP_N_EARLY: int = 3
PORTFOLIO_TOP_N_MID: int = 6
PORTFOLIO_TOP_N_END: int = 9
GAME_STAGE_EARLY_MAX_VP: int = 3
GAME_STAGE_MID_MAX_VP: int = 6

_FLAG_BOOL_KEYS = (
    "need_next_target",
    "target_blocked",
    "race_worse",
    "la_lr_shock",
    "off_strategy_opportunity",
    "hard_invalid",
)

# Sticky / milestone reason substrings → reconsider flag key
_REASON_TO_FLAG: Tuple[Tuple[str, str], ...] = (
    ("opponent_settlement", "target_blocked"),
    ("opponent_city", "target_blocked"),
    ("opponent_structure", "target_blocked"),
    ("target_blocked", "target_blocked"),
    ("target_occupied", "target_blocked"),
    ("race", "race_worse"),
    ("opponent_road", "la_lr_shock"),
    ("longest_road", "la_lr_shock"),
    ("largest_army", "la_lr_shock"),
    ("lost_longest", "la_lr_shock"),
    ("lost_largest", "la_lr_shock"),
    ("own_longest", "la_lr_shock"),
    ("own_largest", "la_lr_shock"),
    ("knight", "la_lr_shock"),
    ("la_lr", "la_lr_shock"),
    ("need_next", "need_next_target"),
    ("own_milestone", "need_next_target"),
    ("own_sett", "need_next_target"),
    ("own_city", "need_next_target"),
    ("rec_complete", "need_next_target"),
    ("target_complete", "need_next_target"),
    ("off_way", "off_strategy_opportunity"),
    ("off_strategy", "off_strategy_opportunity"),
    ("hard_invalid", "hard_invalid"),
    ("route_illegal", "hard_invalid"),
    ("sticky_dead", "hard_invalid"),
)


def empty_reconsider_flags() -> Dict[str, Any]:
    return {
        "need_next_target": False,
        "target_blocked": False,
        "race_worse": False,
        "la_lr_shock": False,
        "off_strategy_opportunity": False,
        "hard_invalid": False,
        "reasons": [],
        "generation": 0,
    }


def get_reconsider_flags(player: Any) -> Dict[str, Any]:
    """Return a normalized flag bag on the player (creates if missing)."""
    raw = getattr(player, "strategy_reconsider_flags", None) if player is not None else None
    if not isinstance(raw, dict):
        flags = empty_reconsider_flags()
        if player is not None:
            try:
                setattr(player, "strategy_reconsider_flags", flags)
            except Exception:
                pass
        return flags
    out = empty_reconsider_flags()
    for k in _FLAG_BOOL_KEYS:
        out[k] = bool(raw.get(k))
    reasons = raw.get("reasons")
    if isinstance(reasons, list):
        out["reasons"] = [str(r) for r in reasons[:24]]
    try:
        out["generation"] = int(raw.get("generation") or 0)
    except Exception:
        out["generation"] = 0
    return out


def set_reconsider_flag(
    player: Any,
    flag: str,
    *,
    reason: str = "",
    value: bool = True,
) -> Dict[str, Any]:
    """Set one significance flag (L1). Does not run portfolio work."""
    flags = get_reconsider_flags(player)
    key = str(flag or "").strip()
    if key in _FLAG_BOOL_KEYS:
        flags[key] = bool(value)
    if reason:
        reasons = list(flags.get("reasons") or [])
        reasons.append(str(reason)[:120])
        flags["reasons"] = reasons[-24:]
    try:
        flags["generation"] = int(flags.get("generation") or 0) + 1
    except Exception:
        flags["generation"] = 1
    if player is not None:
        try:
            setattr(player, "strategy_reconsider_flags", flags)
        except Exception:
            pass
    return flags


def clear_reconsider_flags(player: Any, *, reason: str = "") -> Dict[str, Any]:
    """Clear all flags after a successful L2 (or explicit hold)."""
    flags = empty_reconsider_flags()
    if reason:
        flags["reasons"] = [f"cleared:{reason}"]
    if player is not None:
        try:
            setattr(player, "strategy_reconsider_flags", flags)
        except Exception:
            pass
    return flags


def any_significant_flag(flags: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(flags, Mapping):
        return False
    return any(bool(flags.get(k)) for k in _FLAG_BOOL_KEYS)


def map_recalc_reason_to_flag(reason: str) -> str:
    """Map sticky/milestone reason strings onto a reconsider flag key."""
    r = str(reason or "").strip().lower()
    if not r:
        return "race_worse"
    for needle, flag in _REASON_TO_FLAG:
        if needle in r:
            return flag
    return "race_worse"


def clear_all_strategy_significance(player: Any, *, reason: str = "") -> Dict[str, Any]:
    """Clear reconsider bag + sticky batch flag + force/pending after successful L2."""
    out = clear_reconsider_flags(player, reason=reason or "after_l2")
    if player is None:
        return out
    try:
        from core.strategy_sticky import clear_strategy_recalc_flag

        clear_strategy_recalc_flag(player)
    except Exception:
        try:
            setattr(player, "strategy_recalc_flag", None)
            setattr(player, "force_strategy_recalc", False)
        except Exception:
            pass
    try:
        setattr(player, "force_strategy_recalc", False)
    except Exception:
        pass
    try:
        setattr(player, "pending_full_resolve", None)
    except Exception:
        pass
    return out


def _preferred_way_id(player: Any) -> Optional[int]:
    if player is None:
        return None
    for src in (
        getattr(player, "strategic_direction", None),
        getattr(player, "sticky_commitment", None),
    ):
        if not isinstance(src, Mapping):
            continue
        for key in ("preferred_way_id", "way_id", "locked_way_id"):
            raw = src.get(key)
            if raw is None:
                continue
            try:
                wid = int(raw)
            except Exception:
                continue
            if wid > 0:
                return wid
    return None


def _sticky_recalc_pending(player: Any) -> bool:
    if player is None:
        return False
    raw = getattr(player, "strategy_recalc_flag", None)
    if isinstance(raw, Mapping) and bool(raw.get("pending")):
        return True
    return False


def _pending_full_resolve(player: Any) -> bool:
    if player is None:
        return False
    raw = getattr(player, "pending_full_resolve", None)
    return isinstance(raw, Mapping) and bool(raw)


def should_run_l2_explore(
    game: Any,
    player: Any = None,
    *,
    reason: str = "",
) -> Tuple[bool, str]:
    """Whether refresh should run full portfolio (L2) vs L0 hand_only.

    L0 unless: hard force, missing way, significance flags, batched sticky
    recalc pending, deferred full resolve, or diagnostic reasons.
    """
    if player is None and game is not None:
        try:
            getter = getattr(game, "get_current_player", None)
            player = getter() if callable(getter) else None
        except Exception:
            player = None

    try:
        if bool(getattr(game, "force_l2_explore", False)):
            return True, "game.force_l2_explore"
    except Exception:
        pass

    if player is not None:
        try:
            if bool(getattr(player, "force_strategy_recalc", False)):
                return True, "force_strategy_recalc"
        except Exception:
            pass

        flags = get_reconsider_flags(player)
        if any_significant_flag(flags):
            for k in _FLAG_BOOL_KEYS:
                if flags.get(k):
                    return True, f"flag:{k}"
            return True, "strategy_reconsider_flags"

        if _sticky_recalc_pending(player):
            return True, "strategy_recalc_flag.pending"

        if _pending_full_resolve(player):
            return True, "pending_full_resolve"

        if _preferred_way_id(player) is None:
            return True, "no_preferred_or_sticky_way"

    # Reason-based hard explores (callers can still pass mode=explore explicitly)
    r = str(reason or "").lower()
    if r in {
        "force",
        "explore",
        "l2",
        "f9",
        "phase0_baseline",
        "start_execution_phase",
    }:
        return True, f"reason:{reason}"

    return False, "l0_default"


def resolve_refresh_mode(
    game: Any,
    player: Any = None,
    *,
    mode: Optional[str] = None,
    force: bool = False,
    reason: str = "",
) -> Tuple[str, str]:
    """Return (mode, detail) where mode is hand_only | explore.

    * ``mode="auto"`` — L2 iff should_run_l2_explore
    * ``mode="hand_only"`` / ``l0`` — force L0
    * ``mode="explore"`` / ``force`` / ``l2`` — force L2
    * ``force=True`` with no mode — L2 (explore)
    * default None + force False — **auto** (policy default; was legacy explore)
    """
    m = str(mode or "").strip().lower()
    if m in ("hand_only", "l0", "hand"):
        return "hand_only", "explicit_hand_only"
    if m in ("explore", "force", "l2", "full"):
        return "explore", "explicit_explore"
    if m in ("auto", "after_dice", "after_dice_roll"):
        run, why = should_run_l2_explore(game, player, reason=reason)
        return ("explore" if run else "hand_only"), why
    if force:
        return "explore", "force=True"
    # Policy default: gate via auto (not silent full explore)
    run, why = should_run_l2_explore(game, player, reason=reason)
    return ("explore" if run else "hand_only"), f"default_auto:{why}"


def max_vp_among_players(game: Any) -> int:
    """Best available VP total across seats (for game-stage top-N)."""
    best = 0
    try:
        from core.ai_dcard_timing import victory_points
    except Exception:
        victory_points = None  # type: ignore
    for p in list(getattr(game, "players", None) or []):
        vp = 0
        if victory_points is not None:
            try:
                vp = int(victory_points(game, p) or 0)
            except Exception:
                vp = 0
        if vp <= 0:
            try:
                vp = int(getattr(p, "victory_points", 0) or getattr(p, "vp", 0) or 0)
            except Exception:
                vp = 0
        if vp > best:
            best = vp
    return int(best)


def game_stage_label(game: Any) -> str:
    mvp = max_vp_among_players(game)
    if mvp <= GAME_STAGE_EARLY_MAX_VP:
        return "early"
    if mvp <= GAME_STAGE_MID_MAX_VP:
        return "mid"
    return "end"


def portfolio_top_n_for_game(game: Any) -> int:
    """L2 way-eval cap: Early 3 / Mid 6 / End 9."""
    stage = game_stage_label(game)
    if stage == "early":
        return int(PORTFOLIO_TOP_N_EARLY)
    if stage == "mid":
        return int(PORTFOLIO_TOP_N_MID)
    return int(PORTFOLIO_TOP_N_END)


def classify_refresh_kind(reason: str = "", *, kind: Optional[str] = None) -> str:
    """Map event reason / explicit kind → hand | turn_start | board | milestone | diagnostic."""
    if kind:
        k = str(kind).strip().lower()
        if k in ("hand", "turn_start", "board", "milestone", "diagnostic", "auto"):
            return k
    r = str(reason or "").lower()
    if any(x in r for x in ("phase0", "f8", "f9", "baseline", "diagnostic")):
        return "diagnostic"
    if any(
        x in r
        for x in (
            "after_dice",
            "roll_to_preview",
            "begin_execution",
            "start_of_turn",
            "turn_start",
            "after_basic_robber",
            "after_human_robber",
            "after_ai_robber",
            "robber_flow",
        )
    ):
        return "turn_start"
    if any(
        x in r
        for x in (
            "twp_support",
            "twb_support",
            "after_ai_twp",
            "after_ai_twb",
            "after_trade",
            "play_yop",
            "play_monopoly",
            "play_tfr",
            "buy_dcard",
            "buy_development",
        )
    ):
        return "hand"
    if any(
        x in r
        for x in (
            "build_road",
            "build_settlement",
            "build_city",
            "free_road",
            "milestone",
        )
    ):
        return "milestone"
    if any(x in r for x in ("structure", "opponent", "knight", "longest", "largest")):
        return "board"
    return "auto"


def mode_for_refresh_kind(
    game: Any,
    player: Any,
    kind: str,
    *,
    reason: str = "",
) -> Tuple[Optional[str], bool]:
    """Return (mode, force) kwargs for refresh_strategy_context.

    Never returns force=True except diagnostic.
    """
    k = classify_refresh_kind(reason, kind=kind)
    if k == "diagnostic":
        return "explore", True
    if k == "hand":
        run_l2, _ = should_run_l2_explore(game, player, reason=reason)
        if _preferred_way_id(player) is not None and not run_l2:
            return "hand_only", False
        return "auto", False
    if k in ("turn_start", "board", "milestone", "auto"):
        return "auto", False
    return "auto", False
