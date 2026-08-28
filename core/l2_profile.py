"""P4: L2 quality profiles — fast (cheap AI) vs full (dig-in / Phase0).

Does not decide *whether* L2 runs (P3); only how much work an explore does.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

# Fast-mode defaults (plan P4-2 / P4-3)
# Portfolio depth uses stage Early3/Mid6/End9 (None → stage table). Historical
# flat-3 cap kept as named constant for digs/docs only — not applied to live fast.
PORTFOLIO_TOP_N_FAST: int = 3  # legacy flat cap; unused by fast_l2_profile
ABSTRACT_PREFILTER_K_FAST: int = 12
# Full dig-in: no prefilter (None) or large K
ABSTRACT_PREFILTER_K_FULL: Optional[int] = None


@dataclass(frozen=True)
class L2Profile:
    name: str  # "fast" | "full"
    abstract_prefilter_k: Optional[int]
    portfolio_top_n: Optional[int]  # None → stage 3/6/9
    stage1_include_all: bool
    stage1_current_player_only: bool
    enable_continuations: bool
    continuation_per_action: bool
    enable_risk: bool
    enable_player_trades: bool
    enable_projections: bool
    enable_action_projections: bool = True  # alias clarity

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def fast_l2_profile() -> L2Profile:
    """Cheap AI explore: prefilter K=12; portfolio K follows stage 3/6/9.

    Stage caps (not flat-3) so Mid/End adaptive-K / sync-first pool widen work
    as in ``docs/L2_sync_transparency_shadow_plan.md`` Phase F. Speed levers
    remain: abstract prefilter, no Stage3/risk/TwP/continuations.
    """
    return L2Profile(
        name="fast",
        abstract_prefilter_k=int(ABSTRACT_PREFILTER_K_FAST),
        portfolio_top_n=None,  # stage Early3 / Mid6 / End9
        stage1_include_all=False,
        stage1_current_player_only=True,
        enable_continuations=False,
        continuation_per_action=False,
        enable_risk=False,
        enable_player_trades=False,
        enable_projections=False,
        enable_action_projections=False,
    )


def full_l2_profile() -> L2Profile:
    return L2Profile(
        name="full",
        abstract_prefilter_k=ABSTRACT_PREFILTER_K_FULL,
        portfolio_top_n=None,  # stage table
        stage1_include_all=True,
        stage1_current_player_only=False,
        enable_continuations=True,
        continuation_per_action=True,
        enable_risk=True,
        enable_player_trades=True,
        enable_projections=True,
        enable_action_projections=True,
    )


def resolve_l2_profile(
    game: Any = None,
    *,
    reason: str = "",
    force: bool = False,
    mode: str = "",
) -> L2Profile:
    """Pick fast vs full for an explore-class refresh.

    - Explicit game.l2_quality_mode / _l2_quality_mode: "fast"|"full"
    - CHECK dig-in / phase0 / f9 / diagnostic force → full
    - Else fast (normal AI dirt / Q1 explore)
    """
    # Explicit override on game
    for attr in ("l2_quality_mode", "_l2_quality_mode"):
        try:
            raw = getattr(game, attr, None) if game is not None else None
            s = str(raw or "").strip().lower()
            if s in ("fast", "full"):
                return fast_l2_profile() if s == "fast" else full_l2_profile()
            if s == "auto":
                break
        except Exception:
            pass

    r = str(reason or "").lower()
    m = str(mode or "").lower()

    # Dig-in / diagnostic → full
    if any(x in r for x in ("phase0", "f9", "baseline", "diagnostic", "f8")):
        return full_l2_profile()
    if m in ("force",) and force:
        # bare force without dig-in reason still often diagnostic
        if "phase0" in r or "f9" in r:
            return full_l2_profile()

    try:
        from core.debug_mode import is_check_mode

        if is_check_mode() and any(x in r for x in ("check", "debug", "dig", "f9", "phase0")):
            return full_l2_profile()
        # Optional: entire CHECK_MODE session wants full L2 — product default is
        # still fast for play speed even with CHECK_MODE; dig-in reasons only.
    except Exception:
        pass

    try:
        if bool(getattr(game, "force_l2_full_quality", False)):
            return full_l2_profile()
    except Exception:
        pass

    return fast_l2_profile()


def profile_from_game(game: Any) -> Optional[L2Profile]:
    """Return profile attached for current explore, if any."""
    if game is None:
        return None
    raw = getattr(game, "_l2_profile", None)
    if isinstance(raw, L2Profile):
        return raw
    if isinstance(raw, Mapping):
        name = str(raw.get("name") or "fast").lower()
        return full_l2_profile() if name == "full" else fast_l2_profile()
    return None
