"""Frozen LA give-up thresholds for Phase L L6 (Domain A lab map).

Source: FT0–FT5 on ``batch_runs/la_lab_whosh_n100``
(Playboard_LA_lab_WhOSh_07_Aug_2026.txt, product sticky [2,[4,4]], lib_ip2 dice).

**Does not change Strategy-Engine behavior by itself.** L6 must read these
constants behind ``LA_GIVEUP_L2_ENABLED`` (default off).

Domain of validity
------------------
- **Domain A (frozen):** LA lab Wh/O/Sh board + product sticky.
- **Domain B (not frozen):** standard product map — do not apply θ without re-fit.

See ``docs/PhaseL_LA_theta_lock.md``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# --- Freeze metadata ---
FREEZE_ID: str = "LA_GIVEUP_DOMAIN_A_v1"
FREEZE_DATE: str = "2026-08-07"
FREEZE_BATCH: str = "batch_runs/la_lab_whosh_n100"
FREEZE_PLAYBOARD: str = "Playboard_LA_lab_WhOSh_07_Aug_2026.txt"
FREEZE_DOCS: str = "docs/PhaseL_LA_theta_lock.md"

# --- L2a label params (v0, kept after FT1/FT2) ---
LABEL_MIN_NEEDS: int = 2
LABEL_GAP_FLOOR: int = 2
LABEL_SUSTAIN_K: int = 2
LABEL_HOLD_MAX_GAP: int = 1

# --- Named θ profiles (hopeless_score_la, max_score / sample-time) ---
THETA_SAFE: float = 0.6
THETA_BALANCED: float = 0.5
THETA_AGGRESSIVE: float = 0.4

# --- Fire policy (FT5) ---
FIRE_DWELL: int = 1
FIRE_CLAIM_WINDOW_K: int = 4  # offline FGU metric only
FIRE_LATCH_FIRST: bool = True

# --- Score formula ---
SCORE_FORMULA_VERSION: str = "hopeless_score_la_v0"
# No weight change after FT0–FT5 (FT3 skipped / keep v0).

# --- Stage policy (FT4 / Q2) ---
USE_STAGE_THETAS: bool = False  # KEEP_GLOBAL

# --- L6 wiring defaults (operator may override via constants.py) ---
DEFAULT_PROFILE: str = "safe"
DEFAULT_ENABLED: bool = True  # lab L6 on; set constants.LA_GIVEUP_L2_ENABLED=False for product

PROFILES: Dict[str, Dict[str, Any]] = {
    "safe": {
        "theta": THETA_SAFE,
        "dwell": FIRE_DWELL,
        "claim_window_k": FIRE_CLAIM_WINDOW_K,
        "latch_first": FIRE_LATCH_FIRST,
        "intent": "FGU≈0 on lab batch; default L6 candidate",
    },
    "balanced": {
        "theta": THETA_BALANCED,
        "dwell": FIRE_DWELL,
        "claim_window_k": FIRE_CLAIM_WINDOW_K,
        "latch_first": FIRE_LATCH_FIRST,
        "intent": "mid trade-off; not primary L6 default",
    },
    "aggressive": {
        "theta": THETA_AGGRESSIVE,
        "dwell": FIRE_DWELL,
        "claim_window_k": FIRE_CLAIM_WINDOW_K,
        "latch_first": FIRE_LATCH_FIRST,
        "intent": "max dead-race recall; lab A/B only",
    },
}

# Reference metrics at freeze (full batch, D=1, K=4) — for verify script
FREEZE_REFERENCE_METRICS: Dict[str, Dict[str, Any]] = {
    "safe": {
        "theta": 0.6,
        "f1_give_up": 0.7579,
        "false_give_up_rate": 0.0,
        "dead_race_recall": 0.6102,
        "true_give_up": 36,
        "false_give_up": 0,
        "false_hold": 23,
    },
    "aggressive": {
        "theta": 0.4,
        "f1_give_up": 0.944,
        "false_give_up_rate": 0.1061,
        "dead_race_recall": 1.0,
        "true_give_up": 59,
        "false_give_up": 7,
        "false_hold": 0,
    },
    "balanced": {
        "theta": 0.5,
        "f1_give_up": 0.8907,
        "false_give_up_rate": 0.1167,
        "dead_race_recall": 0.8983,
        "true_give_up": 53,
        "false_give_up": 7,
        "false_hold": 6,
    },
    "l2a_full_batch": {
        "theta_LA": 0.6,
        "f1": 0.8919,
        "separation": 0.5077,
        "n_labeled": 145,
        "n_give_up": 41,
        "n_hold": 104,
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
    """Resolve active profile from arg or core.constants."""
    name = profile
    if name is None and constants_module is not None:
        name = getattr(constants_module, "LA_GIVEUP_PROFILE", None)
    name = normalize_profile(name)
    base = dict(PROFILES[name])
    # Optional per-field overrides from constants
    if constants_module is not None:
        th = getattr(constants_module, "LA_GIVEUP_THETA", None)
        if th is not None and str(th).strip() != "":
            try:
                base["theta"] = float(th)
            except Exception:
                pass
        dw = getattr(constants_module, "LA_GIVEUP_DWELL", None)
        if dw is not None and str(dw).strip() != "":
            try:
                base["dwell"] = int(dw)
            except Exception:
                pass
        k = getattr(constants_module, "LA_GIVEUP_CLAIM_WINDOW_K", None)
        if k is not None and str(k).strip() != "":
            try:
                base["claim_window_k"] = int(k)
            except Exception:
                pass
    base["profile"] = name
    base["freeze_id"] = FREEZE_ID
    base["domain"] = "A_lab_whosh"
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
        return bool(getattr(constants_module, "LA_GIVEUP_L2_ENABLED", DEFAULT_ENABLED))
    except Exception:
        return DEFAULT_ENABLED


def status_dict(constants_module: Any = None) -> Dict[str, Any]:
    try:
        from core import constants as C

        constants_module = constants_module or C
    except Exception:
        constants_module = constants_module
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
        "wp": "FT6",
        "freeze_id": FREEZE_ID,
        "freeze_date": FREEZE_DATE,
        "batch": FREEZE_BATCH,
        "playboard": FREEZE_PLAYBOARD,
        "domain": "A_lab_whosh",
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
        "note": (
            "DEFAULT_ENABLED True for lab Domain A testing; "
            "turn off for standard product maps."
        ),
        "reference_metrics": FREEZE_REFERENCE_METRICS,
        "docs": [
            FREEZE_DOCS,
            "docs/PhaseL_FT5_la_fire_policy.md",
            "docs/PhaseL_FT2_la_holdout.md",
            "docs/PhaseL_FT4_la_stage_slices.md",
            "docs/PhaseL_L2a_L3a_fine_tune_plan.md",
        ],
        "rule_safe": (
            "When needs_LA and not holding LA: if hopeless_score_la ≥ 0.6 for "
            "1 consecutive own-turn needs sample, fire give-up once (latch) → "
            "clear LA ambition + force L2. Domain A lab map only until re-fit."
        ),
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
