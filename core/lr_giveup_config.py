"""Frozen LR give-up thresholds for Phase L L6 (Domain C LR lab map).

Source: FT2 + FT5 + full-batch L2b/L3b on ``batch_runs/lr_lab_wdb_n100``
(Playboard_LR_lab_WdB_07_Aug_2026.txt, product sticky [2,[4,4]]).

**SE wiring:** ``core/lr_giveup_l2.py`` behind ``LR_GIVEUP_L2_ENABLED``.

Domain of validity
------------------
- **Domain C (frozen):** LR lab Wd/B board + product sticky.
- **Not frozen:** standard product map, LA lab Wh/O/Sh board.

See ``docs/PhaseL_LR_theta_lock.md``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# --- Freeze metadata ---
FREEZE_ID: str = "LR_GIVEUP_DOMAIN_C_v1"
FREEZE_DATE: str = "2026-08-07"
FREEZE_BATCH: str = "batch_runs/lr_lab_wdb_n100"
FREEZE_PLAYBOARD: str = "Playboard_LR_lab_WdB_07_Aug_2026.txt"
FREEZE_DOCS: str = "docs/PhaseL_LR_theta_lock.md"

# --- L2b label params (same v0 as LA oracle labels) ---
LABEL_MIN_NEEDS: int = 2
LABEL_GAP_FLOOR: int = 2
LABEL_SUSTAIN_K: int = 2
LABEL_HOLD_MAX_GAP: int = 1

# --- Named θ profiles (hopeless_score_lr) ---
THETA_SAFE: float = 0.75
THETA_BALANCED: float = 0.65
THETA_AGGRESSIVE: float = 0.55

# --- Fire policy (FT5 LR) ---
FIRE_DWELL: int = 1
FIRE_CLAIM_WINDOW_K: int = 4
FIRE_LATCH_FIRST: bool = True

SCORE_FORMULA_VERSION: str = "hopeless_score_lr_v0"
USE_STAGE_THETAS: bool = False

DEFAULT_PROFILE: str = "safe"
DEFAULT_ENABLED: bool = True  # lab Domain C; False on product / LA lab if pure LA run

PROFILES: Dict[str, Dict[str, Any]] = {
    "safe": {
        "theta": THETA_SAFE,
        "dwell": FIRE_DWELL,
        "claim_window_k": FIRE_CLAIM_WINDOW_K,
        "latch_first": FIRE_LATCH_FIRST,
        "intent": "lower FGU on LR lab; default L6 candidate",
    },
    "balanced": {
        "theta": THETA_BALANCED,
        "dwell": FIRE_DWELL,
        "claim_window_k": FIRE_CLAIM_WINDOW_K,
        "latch_first": FIRE_LATCH_FIRST,
        "intent": "L2b primary θ; mid trade-off",
    },
    "aggressive": {
        "theta": THETA_AGGRESSIVE,
        "dwell": FIRE_DWELL,
        "claim_window_k": FIRE_CLAIM_WINDOW_K,
        "latch_first": FIRE_LATCH_FIRST,
        "intent": "max dead-race recall; lab A/B only (high thrash without latch)",
    },
}

# Full-batch D=1 K=4 reference (lr_lab_wdb_n100)
FREEZE_REFERENCE_METRICS: Dict[str, Dict[str, Any]] = {
    "safe": {
        "theta": 0.75,
        "f1_give_up": 0.6643,
        "false_give_up_rate": 0.1455,
        "dead_race_recall": 0.5434,
        "true_give_up": 94,
        "false_give_up": 16,
        "false_hold": 79,
    },
    "balanced": {
        "theta": 0.65,
        "f1_give_up": 0.7733,
        "false_give_up_rate": 0.2822,
        "dead_race_recall": 0.8382,
        "true_give_up": 145,
        "false_give_up": 57,
        "false_hold": 28,
    },
    "aggressive": {
        "theta": 0.55,
        "f1_give_up": 0.7889,
        "false_give_up_rate": 0.3411,
        "dead_race_recall": 0.9827,
        "true_give_up": 170,
        "false_give_up": 88,
        "false_hold": 3,
    },
    "l2b_full_batch": {
        "theta_LR": 0.65,
        "f1": 0.7362,
        "separation": 0.2117,
        "n_labeled": 375,
        "n_give_up": 148,
        "n_hold": 227,
    },
}


def normalize_profile(name: Any) -> str:
    n = str(name or DEFAULT_PROFILE).strip().lower()
    if n in ("default", "l6", "prod"):
        return "safe"
    if n in PROFILES:
        return n
    return DEFAULT_PROFILE


def resolve_profile(
    profile: Optional[str] = None,
    *,
    constants_module: Any = None,
) -> Dict[str, Any]:
    name = profile
    if name is None and constants_module is not None:
        name = getattr(constants_module, "LR_GIVEUP_PROFILE", None)
    name = normalize_profile(name)
    base = dict(PROFILES[name])
    if constants_module is not None:
        th = getattr(constants_module, "LR_GIVEUP_THETA", None)
        if th is not None and str(th).strip() != "":
            try:
                base["theta"] = float(th)
            except Exception:
                pass
        dw = getattr(constants_module, "LR_GIVEUP_DWELL", None)
        if dw is not None and str(dw).strip() != "":
            try:
                base["dwell"] = int(dw)
            except Exception:
                pass
        k = getattr(constants_module, "LR_GIVEUP_CLAIM_WINDOW_K", None)
        if k is not None and str(k).strip() != "":
            try:
                base["claim_window_k"] = int(k)
            except Exception:
                pass
    base["profile"] = name
    base["freeze_id"] = FREEZE_ID
    base["domain"] = "C_lab_wdb"
    base["use_stage_thetas"] = USE_STAGE_THETAS
    base["score_formula"] = SCORE_FORMULA_VERSION
    base["label_params"] = {
        "min_needs": LABEL_MIN_NEEDS,
        "gap_floor": LABEL_GAP_FLOOR,
        "sustain_k": LABEL_SUSTAIN_K,
        "hold_max_gap": LABEL_HOLD_MAX_GAP,
    }
    return base


def is_giveup_l2_enabled(constants_module: Any = None) -> bool:
    if constants_module is None:
        try:
            from core import constants as C

            constants_module = C
        except Exception:
            return DEFAULT_ENABLED
    try:
        return bool(getattr(constants_module, "LR_GIVEUP_L2_ENABLED", DEFAULT_ENABLED))
    except Exception:
        return DEFAULT_ENABLED


def status_dict(constants_module: Any = None) -> Dict[str, Any]:
    try:
        from core import constants as C

        constants_module = constants_module or C
    except Exception:
        pass
    prof = resolve_profile(constants_module=constants_module)
    return {
        "enabled": is_giveup_l2_enabled(constants_module),
        "freeze_id": FREEZE_ID,
        "freeze_date": FREEZE_DATE,
        "freeze_batch": FREEZE_BATCH,
        "playboard": FREEZE_PLAYBOARD,
        "profile": prof,
        "use_stage_thetas": USE_STAGE_THETAS,
        "docs": FREEZE_DOCS,
    }


def freeze_manifest() -> Dict[str, Any]:
    return {
        "schema": 1,
        "wp": "FT6_LR",
        "freeze_id": FREEZE_ID,
        "freeze_date": FREEZE_DATE,
        "batch": FREEZE_BATCH,
        "playboard": FREEZE_PLAYBOARD,
        "domain": "C_lab_wdb",
        "use_stage_thetas": USE_STAGE_THETAS,
        "score_formula": SCORE_FORMULA_VERSION,
        "label_params": {
            "min_needs": LABEL_MIN_NEEDS,
            "gap_floor": LABEL_GAP_FLOOR,
            "sustain_k": LABEL_SUSTAIN_K,
            "hold_max_gap": LABEL_HOLD_MAX_GAP,
        },
        "profiles": PROFILES,
        "fire_policy": {
            "dwell": FIRE_DWELL,
            "claim_window_k": FIRE_CLAIM_WINDOW_K,
            "latch_first": FIRE_LATCH_FIRST,
        },
        "l6_default_profile": DEFAULT_PROFILE,
        "l6_enabled_default": DEFAULT_ENABLED,
        "reference_metrics": FREEZE_REFERENCE_METRICS,
        "docs": [
            FREEZE_DOCS,
            "docs/PhaseL_FT5_lr_fire_policy.md",
            "docs/PhaseL_FT2_lr_holdout.md",
            "docs/PhaseL_lab_playboards.md",
        ],
        "rule_safe": (
            "When needs_LR and not holding LR: if hopeless_score_lr ≥ 0.75 for "
            "1 consecutive own-turn needs sample, fire give-up once (latch) → "
            "clear LR ambition + force L2. Domain C LR lab map only until re-fit."
        ),
        "note": "Latch mandatory (thrash ~24–39% without latch on lab batch).",
    }


__all__ = [
    "FREEZE_ID",
    "FREEZE_DATE",
    "FREEZE_BATCH",
    "FREEZE_PLAYBOARD",
    "THETA_SAFE",
    "THETA_BALANCED",
    "THETA_AGGRESSIVE",
    "FIRE_DWELL",
    "FIRE_CLAIM_WINDOW_K",
    "FIRE_LATCH_FIRST",
    "USE_STAGE_THETAS",
    "PROFILES",
    "DEFAULT_PROFILE",
    "DEFAULT_ENABLED",
    "FREEZE_REFERENCE_METRICS",
    "normalize_profile",
    "resolve_profile",
    "is_giveup_l2_enabled",
    "status_dict",
    "freeze_manifest",
]
