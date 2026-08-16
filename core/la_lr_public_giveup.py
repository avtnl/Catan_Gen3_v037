"""Phase L L5: public give-up proxies vs god-view teacher fire@θ (offline).

L5-1: teacher construction from probe rows (score ≥ θ, needs, not holds).
L5-2: public rule family A (MVP) + optional score family B (parallel dig).

Spec: ``docs/PhaseL_L5_players_view_proxy_plan.md`` (``L5_PUBLIC_GIVEUP_SPEC_v0``).
No Strategy-Engine mutation. Public inputs only (L4 features / ambition).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# L5-0 frozen constants
# ---------------------------------------------------------------------------

SPEC_FREEZE_ID: str = "L5_PUBLIC_GIVEUP_SPEC_v0"
PUBLIC_GIVEUP_SCHEMA_VERSION: int = 1

# Teacher θ (safe freezes)
try:
    from core.la_giveup_config import THETA_SAFE as _THETA_LA
except Exception:  # pragma: no cover
    _THETA_LA = 0.6
try:
    from core.lr_giveup_config import THETA_SAFE as _THETA_LR
except Exception:  # pragma: no cover
    _THETA_LR = 0.75

THETA_LA_SAFE: float = float(_THETA_LA)
THETA_LR_SAFE: float = float(_THETA_LR)

# L5-5 gate bars (needs-conditioned)
GATE_PRECISION_MIN: float = 0.70
GATE_FGU_MAX: float = 0.20
GATE_SOFT_PRECISION_MIN: float = 0.60

# MVP proxy family (L5-2 / Q5-1). LA stays rule_a; LR default may be retuned by G.
PROXY_MVP_VARIANT: str = "rule_a"
# G-track: default LR profile name (see LR_RULE_PROFILES). Baseline rule_a until G4 freeze.
LR_PROXY_DEFAULT_VARIANT: str = "rule_a"

# Q5-4: teacher requires not holds
TEACHER_REQUIRE_NOT_HOLDS: bool = True

# --- Rule family A constants (public give-up) ---
RULE_A_LA_GAP_WEAK: int = 3
RULE_A_LA_ARMY_WEAK_MAX: int = 1
RULE_A_LA_GAP_HARD: int = 4
RULE_A_LA_ARMY_HARD_MAX: int = 2  # army < 3  →  army <= 2

RULE_A_LR_GAP_WEAK: int = 4
RULE_A_LR_PATH_BAR: int = 5  # path < 5
RULE_A_LR_PATH_MAX: int = 4  # short-path branch: path <= this (default path_bar-1)
RULE_A_LR_BOXED_GAP_MIN: int = 2
RULE_A_LR_STAGNANT_GAP: int = 4
RULE_A_LR_USE_STAGNANT: bool = True
RULE_A_LR_USE_BOXED: bool = True
RULE_A_LR_AND_SCORE_PHI: Optional[float] = None  # if set, AND with score_b >= phi

# Weak ambition set for stagnation branch
RULE_A_WEAK_AMBITION: Tuple[str, ...] = ("none", "L")

# G1 named LR profiles (retune grid)
LR_RULE_PROFILES: Dict[str, Dict[str, Any]] = {
    "rule_a": {
        "gap_weak": 4,
        "path_bar": 5,
        "path_max": 4,
        "boxed_gap_min": 2,
        "stagnant_gap": 4,
        "use_stagnant": True,
        "use_boxed": True,
        "and_score_phi": None,
        "desc": "L5-2 baseline (over-eager on product)",
    },
    "lr_gap5": {
        "gap_weak": 5,
        "path_bar": 5,
        "path_max": 4,
        "boxed_gap_min": 2,
        "stagnant_gap": 5,
        "use_stagnant": True,
        "use_boxed": True,
        "and_score_phi": None,
        "desc": "Raise gap floors to 5",
    },
    "lr_path3": {
        "gap_weak": 4,
        "path_bar": 5,
        "path_max": 3,
        "boxed_gap_min": 2,
        "stagnant_gap": 4,
        "use_stagnant": True,
        "use_boxed": True,
        "and_score_phi": None,
        "desc": "Short-path only when path<=3",
    },
    "lr_no_stagnant": {
        "gap_weak": 4,
        "path_bar": 5,
        "path_max": 4,
        "boxed_gap_min": 2,
        "stagnant_gap": 4,
        "use_stagnant": False,
        "use_boxed": True,
        "and_score_phi": None,
        "desc": "Drop stagnant branch (main FP source)",
    },
    "lr_tight": {
        "gap_weak": 5,
        "path_bar": 5,
        "path_max": 3,
        "boxed_gap_min": 3,
        "stagnant_gap": 5,
        "use_stagnant": False,
        "use_boxed": True,
        "and_score_phi": None,
        "desc": "gap>=5, path<=3, no stagnant",
    },
    "lr_tight_stag5": {
        "gap_weak": 5,
        "path_bar": 5,
        "path_max": 3,
        "boxed_gap_min": 3,
        "stagnant_gap": 5,
        "use_stagnant": True,
        "use_boxed": True,
        "and_score_phi": None,
        "desc": "tight short-path + stagnant only gap>=5",
    },
    "lr_and_s70": {
        "gap_weak": 4,
        "path_bar": 5,
        "path_max": 4,
        "boxed_gap_min": 2,
        "stagnant_gap": 4,
        "use_stagnant": True,
        "use_boxed": True,
        "and_score_phi": 0.70,
        "desc": "baseline AND score_b>=0.70",
    },
    "lr_tight_and_s70": {
        "gap_weak": 5,
        "path_bar": 5,
        "path_max": 3,
        "boxed_gap_min": 3,
        "stagnant_gap": 5,
        "use_stagnant": False,
        "use_boxed": True,
        "and_score_phi": 0.70,
        "desc": "tight AND score_b>=0.70",
    },
    "lr_and_s75": {
        "gap_weak": 4,
        "path_bar": 5,
        "path_max": 4,
        "boxed_gap_min": 2,
        "stagnant_gap": 4,
        "use_stagnant": True,
        "use_boxed": True,
        "and_score_phi": 0.75,
        "desc": "baseline AND score_b>=0.75",
    },
    "lr_score_only_70": {
        "gap_weak": 99,
        "path_bar": 5,
        "path_max": 0,
        "boxed_gap_min": 99,
        "stagnant_gap": 99,
        "use_stagnant": False,
        "use_boxed": False,
        "and_score_phi": 0.70,
        "score_only": True,
        "desc": "score_b>=0.70 only (no rule_a branches)",
    },
    "lr_score_only_75": {
        "gap_weak": 99,
        "path_bar": 5,
        "path_max": 0,
        "boxed_gap_min": 99,
        "stagnant_gap": 99,
        "use_stagnant": False,
        "use_boxed": False,
        "and_score_phi": 0.75,
        "score_only": True,
        "desc": "score_b>=0.75 only",
    },
}


def list_lr_rule_variants() -> List[str]:
    return list(LR_RULE_PROFILES.keys())


def resolve_lr_profile(name: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    key = str(name or LR_PROXY_DEFAULT_VARIANT or "rule_a").strip().lower()
    if key not in LR_RULE_PROFILES:
        key = "rule_a"
    return key, dict(LR_RULE_PROFILES[key])

# --- Score family B (parallel dig; not gate MVP) ---
SCORE_B_PHI_DEFAULT: float = 0.65
SCORE_B_LA_GAP_NORM: float = 4.0
SCORE_B_LR_GAP_NORM: float = 5.0
SCORE_B_W_GAP: float = 0.50
SCORE_B_W_WEAK_AMB: float = 0.25
SCORE_B_W_STAGNANT: float = 0.15
SCORE_B_W_THREATS: float = 0.10
# LR extra: cap pressure folded into threats slot slightly via optional term
SCORE_B_W_LR_CAP: float = 0.05  # taken from threats weight for LR only


def l5_freeze_snapshot() -> Dict[str, Any]:
    """Constants for reports / digs."""
    return {
        "spec_freeze_id": SPEC_FREEZE_ID,
        "schema": PUBLIC_GIVEUP_SCHEMA_VERSION,
        "theta_la": THETA_LA_SAFE,
        "theta_lr": THETA_LR_SAFE,
        "gate_precision_min": GATE_PRECISION_MIN,
        "gate_fgu_max": GATE_FGU_MAX,
        "gate_soft_precision_min": GATE_SOFT_PRECISION_MIN,
        "proxy_mvp": PROXY_MVP_VARIANT,
        "lr_proxy_default": LR_PROXY_DEFAULT_VARIANT,
        "lr_rule_variants": list_lr_rule_variants(),
        "teacher_require_not_holds": TEACHER_REQUIRE_NOT_HOLDS,
        "rule_a": {
            "la_gap_weak": RULE_A_LA_GAP_WEAK,
            "la_army_weak_max": RULE_A_LA_ARMY_WEAK_MAX,
            "la_gap_hard": RULE_A_LA_GAP_HARD,
            "la_army_hard_max": RULE_A_LA_ARMY_HARD_MAX,
            "lr_gap_weak": RULE_A_LR_GAP_WEAK,
            "lr_path_bar": RULE_A_LR_PATH_BAR,
            "lr_boxed_gap_min": RULE_A_LR_BOXED_GAP_MIN,
            "weak_ambition": list(RULE_A_WEAK_AMBITION),
        },
        "score_b": {
            "phi_default": SCORE_B_PHI_DEFAULT,
            "la_gap_norm": SCORE_B_LA_GAP_NORM,
            "lr_gap_norm": SCORE_B_LR_GAP_NORM,
        },
        "q5": {
            "Q5-1": "rule_a_first_score_b_parallel",
            "Q5-2": "gate_needs_conditioned_primary",
            "Q5-3": f"P>={GATE_PRECISION_MIN}_FGU<={GATE_FGU_MAX}",
            "Q5-4": "not_holds_required",
            "Q5-5": "sample_time_fire_theta_only",
            "Q5-6": "no_product_map_before_gate",
        },
    }


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None or v == "":
        return default
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def _block(row: Mapping[str, Any], special: str) -> Dict[str, Any]:
    raw = row.get(special)
    return dict(raw) if isinstance(raw, Mapping) else {}


def resolve_theta(special: str, theta: Optional[float] = None) -> float:
    """Return θ for special; override if provided."""
    if theta is not None:
        return float(theta)
    sp = str(special or "la").strip().lower()
    if sp == "lr":
        return float(THETA_LR_SAFE)
    return float(THETA_LA_SAFE)


def special_block_from_row(row: Mapping[str, Any], special: str) -> Dict[str, Any]:
    """``la`` / ``lr`` sub-object from a probe sample row."""
    sp = str(special or "la").strip().lower()
    if sp not in ("la", "lr"):
        sp = "la"
    return _block(row, sp)


def probe_needs(row: Mapping[str, Any], special: str) -> bool:
    blk = special_block_from_row(row, special)
    if "needs" in blk:
        return bool(blk.get("needs"))
    sp = str(special or "la").strip().lower()
    if sp == "lr":
        return bool(row.get("needs_lr") or row.get("needs_LR"))
    return bool(row.get("needs_la") or row.get("needs_LA"))


def probe_holds(row: Mapping[str, Any], special: str) -> bool:
    blk = special_block_from_row(row, special)
    if "holds" in blk:
        return bool(blk.get("holds"))
    sp = str(special or "la").strip().lower()
    if sp == "lr":
        return bool(row.get("holds_lr") or row.get("holds_LR"))
    return bool(row.get("holds_la") or row.get("holds_LA"))


def hopeless_score_from_row(
    row: Mapping[str, Any],
    special: str,
) -> float:
    """God-view hopeless score from probe special block (reuse L2 formula)."""
    from core.batch.la_lr_godview import hopeless_score

    blk = special_block_from_row(row, special)
    sp = str(special or "la").strip().lower()
    if sp not in ("la", "lr"):
        sp = "la"
    try:
        return float(hopeless_score(blk, sp))
    except Exception:
        return 0.0


def teacher_fire_at_theta(
    row: Mapping[str, Any],
    special: str,
    *,
    theta: Optional[float] = None,
    require_needs: bool = False,
    require_not_holds: Optional[bool] = None,
) -> Dict[str, Any]:
    """Sample-time god-view teacher: would L6 fire at frozen θ?

    L5-0 / Q5-4: by default ``require_not_holds=True`` (align L6).
    ``require_needs``: when True, force needs (for needs-conditioned slices the
    caller usually filters; when False, teacher_fire is still False if not needs
    only if require_needs is set — default False so score≥θ & not holds is the
    raw teacher; L6 also requires needs — use ``require_needs=True`` for L6-aligned
    teacher, or filter needs outside.

    **L6-aligned teacher (recommended for agreement):**
    ``require_needs=True``, ``require_not_holds=True`` (defaults for
    ``build_teacher_record``).
    """
    sp = str(special or "la").strip().lower()
    if sp not in ("la", "lr"):
        sp = "la"
    th = resolve_theta(sp, theta)
    needs = probe_needs(row, sp)
    holds = probe_holds(row, sp)
    score = hopeless_score_from_row(row, sp)
    not_holds_req = (
        TEACHER_REQUIRE_NOT_HOLDS
        if require_not_holds is None
        else bool(require_not_holds)
    )

    reasons: list = []
    fire = True
    if score < th:
        fire = False
        reasons.append("below_theta")
    if not_holds_req and holds:
        fire = False
        reasons.append("holds")
    if require_needs and not needs:
        fire = False
        reasons.append("no_needs")

    return {
        "special": sp,
        "score": score,
        "theta": th,
        "needs": needs,
        "holds": holds,
        "teacher_fire": bool(fire),
        "teacher_fire_l6_aligned": bool(
            fire
            if require_needs
            else (score >= th and (not holds if not_holds_req else True) and needs)
        ),
        "skip_reasons": reasons,
        "spec_freeze_id": SPEC_FREEZE_ID,
    }


def build_teacher_record(
    row: Mapping[str, Any],
    special: str,
    *,
    theta: Optional[float] = None,
) -> Dict[str, Any]:
    """L6-aligned teacher for L5 agreement (needs & not holds & score≥θ)."""
    return teacher_fire_at_theta(
        row,
        special,
        theta=theta,
        require_needs=True,
        require_not_holds=True,
    )


def teacher_pair_from_row(
    row: Mapping[str, Any],
    *,
    theta_la: Optional[float] = None,
    theta_lr: Optional[float] = None,
) -> Dict[str, Any]:
    """Both specials' L6-aligned teacher records on one probe row."""
    la = build_teacher_record(row, "la", theta=theta_la)
    lr = build_teacher_record(row, "lr", theta=theta_lr)
    return {
        "la": la,
        "lr": lr,
        "teacher_fire_la": bool(la.get("teacher_fire")),
        "teacher_fire_lr": bool(lr.get("teacher_fire")),
        "needs_la": bool(la.get("needs")),
        "needs_lr": bool(lr.get("needs")),
        "holds_la": bool(la.get("holds")),
        "holds_lr": bool(lr.get("holds")),
        "score_la": la.get("score"),
        "score_lr": lr.get("score"),
        "spec_freeze_id": SPEC_FREEZE_ID,
    }


def is_needs_conditioned_row(row: Mapping[str, Any], special: str) -> bool:
    """Q5-2 primary gate population: needs==True (holds may still be true; teacher then False)."""
    return probe_needs(row, special)


def filter_reason_teacher(
    teacher: Mapping[str, Any],
) -> str:
    """Short dig string for why teacher did/didn't fire."""
    if teacher.get("teacher_fire"):
        return "fire"
    reasons = teacher.get("skip_reasons") or []
    if not reasons:
        return "no_fire"
    return "+".join(str(r) for r in reasons)


# ---------------------------------------------------------------------------
# L5-2: public give-up proxies (features = L4 public vector + ambition)
# ---------------------------------------------------------------------------


def _fi(features: Mapping[str, Any], key: str, default: int = 0) -> int:
    try:
        if features.get(key) is None or features.get(key) == "":
            return default
        return int(float(features.get(key)))
    except Exception:
        return default


def _fb(features: Mapping[str, Any], key: str, default: bool = False) -> bool:
    v = features.get(key)
    if v is None:
        return default
    return bool(v)


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def ensure_ambition_on_features(features: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy features; fill ambition_* / public_chase_* via L4 if missing."""
    out = dict(features or {})
    need_la = "ambition_la" not in out
    need_lr = "ambition_lr" not in out
    if need_la or need_lr:
        try:
            from core.la_lr_players_view import label_ambitions

            labels = label_ambitions(out)
            if need_la:
                out["ambition_la"] = labels.get("ambition_la", "none")
                out["public_chase_la"] = labels.get("public_chase_la", False)
            if need_lr:
                out["ambition_lr"] = labels.get("ambition_lr", "none")
                out["public_chase_lr"] = labels.get("public_chase_lr", False)
        except Exception:
            out.setdefault("ambition_la", "none")
            out.setdefault("ambition_lr", "none")
            out.setdefault("public_chase_la", False)
            out.setdefault("public_chase_lr", False)
    else:
        # Derive chase if only ambition present
        try:
            from core.la_lr_players_view import is_public_chase

            if "public_chase_la" not in out:
                out["public_chase_la"] = is_public_chase(out.get("ambition_la"))
            if "public_chase_lr" not in out:
                out["public_chase_lr"] = is_public_chase(out.get("ambition_lr"))
        except Exception:
            out.setdefault("public_chase_la", False)
            out.setdefault("public_chase_lr", False)
    return out


def public_giveup_flag_la_rule_a(
    features: Mapping[str, Any],
) -> Dict[str, Any]:
    """Rule family A — LA public give-up flag (MVP). First match wins."""
    f = ensure_ambition_on_features(features)
    holds = _fb(f, "holds_la", False)
    gap = max(0, _fi(f, "gap_la", 0))
    army = max(0, _fi(f, "army", 0))
    amb = str(f.get("ambition_la") or "none")
    chase = _fb(f, "public_chase_la", False)
    delta_active = _fb(f, "delta_active", False)
    try:
        d_army = int(f.get("delta_army") or 0)
    except Exception:
        d_army = 0

    reason = "no_rule"
    fire = False
    if holds:
        reason = "holds"
        fire = False
    elif (
        gap >= RULE_A_LA_GAP_WEAK
        and army <= RULE_A_LA_ARMY_WEAK_MAX
        and not chase
    ):
        reason = "dead_race_weak_army"
        fire = True
    elif (
        gap >= RULE_A_LA_GAP_WEAK
        and amb in RULE_A_WEAK_AMBITION
        and delta_active
        and d_army <= 0
    ):
        reason = "gap_stagnant_weak_ambition"
        fire = True
    elif gap >= RULE_A_LA_GAP_HARD and army <= RULE_A_LA_ARMY_HARD_MAX:
        reason = "hard_gap_low_army"
        fire = True
    else:
        reason = "no_rule"
        fire = False

    return {
        "special": "la",
        "variant": "rule_a",
        "public_giveup": bool(fire),
        "reason": reason,
        "gap": gap,
        "army": army,
        "ambition": amb,
        "public_chase": chase,
        "spec_freeze_id": SPEC_FREEZE_ID,
    }


def public_giveup_flag_lr_rule_a(
    features: Mapping[str, Any],
    *,
    variant: Optional[str] = None,
    profile: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """LR public give-up flag (rule A family). Supports G retune profiles.

    First matching branch wins; optional AND with score_b >= phi.
    """
    vname, prof = resolve_lr_profile(variant)
    if profile is not None:
        prof = {**prof, **dict(profile)}
        vname = str(variant or vname)

    gap_weak = int(prof.get("gap_weak", RULE_A_LR_GAP_WEAK))
    path_bar = int(prof.get("path_bar", RULE_A_LR_PATH_BAR))
    path_max = int(prof.get("path_max", max(0, path_bar - 1)))
    boxed_gap = int(prof.get("boxed_gap_min", RULE_A_LR_BOXED_GAP_MIN))
    stag_gap = int(prof.get("stagnant_gap", gap_weak))
    use_stagnant = bool(prof.get("use_stagnant", True))
    use_boxed = bool(prof.get("use_boxed", True))
    and_phi = prof.get("and_score_phi", None)
    score_only = bool(prof.get("score_only", False))

    f = ensure_ambition_on_features(features)
    holds = _fb(f, "holds_lr", False)
    gap = max(0, _fi(f, "gap_lr", 0))
    path = max(0, _fi(f, "path", 0))
    amb = str(f.get("ambition_lr") or "none")
    chase = _fb(f, "public_chase_lr", False)
    delta_active = _fb(f, "delta_active", False)
    try:
        d_path = int(f.get("delta_path") or 0)
    except Exception:
        d_path = 0
    legal = f.get("legal_roads")
    legal_n: Optional[int]
    try:
        legal_n = None if legal is None or legal == "" else int(float(legal))
    except Exception:
        legal_n = None

    reason = "no_rule"
    fire = False
    if holds:
        reason = "holds"
        fire = False
    elif score_only:
        # Pure score gate (still never fire on holds)
        sb = public_giveup_score_lr(f)
        phi = float(and_phi) if and_phi is not None else SCORE_B_PHI_DEFAULT
        sc = float(sb.get("score") or 0.0)
        fire = sc >= phi
        reason = "score_only" if fire else "no_rule"
    elif gap >= gap_weak and path <= path_max and not chase:
        reason = "dead_race_short_path"
        fire = True
    elif (
        use_stagnant
        and gap >= stag_gap
        and amb in RULE_A_WEAK_AMBITION
        and delta_active
        and d_path <= 0
    ):
        reason = "gap_stagnant_weak_ambition"
        fire = True
    elif (
        use_boxed
        and legal_n is not None
        and legal_n == 0
        and path < path_bar
        and gap >= boxed_gap
    ):
        reason = "boxed_roads"
        fire = True
    else:
        reason = "no_rule"
        fire = False

    # Optional AND with score_b
    score_val = None
    if fire and and_phi is not None and not score_only:
        sb = public_giveup_score_lr(f)
        score_val = float(sb.get("score") or 0.0)
        if score_val < float(and_phi):
            fire = False
            reason = f"and_score_fail_{reason}"

    return {
        "special": "lr",
        "variant": vname,
        "public_giveup": bool(fire),
        "reason": reason,
        "gap": gap,
        "path": path,
        "ambition": amb,
        "public_chase": chase,
        "legal_roads": legal_n,
        "score_b": score_val,
        "and_score_phi": and_phi,
        "profile": {
            "gap_weak": gap_weak,
            "path_max": path_max,
            "use_stagnant": use_stagnant,
            "use_boxed": use_boxed,
        },
        "spec_freeze_id": SPEC_FREEZE_ID,
    }


def public_giveup_flag_rule_a(
    features: Mapping[str, Any],
    special: str,
    *,
    lr_variant: Optional[str] = None,
) -> Dict[str, Any]:
    sp = str(special or "la").strip().lower()
    if sp == "lr":
        return public_giveup_flag_lr_rule_a(features, variant=lr_variant)
    return public_giveup_flag_la_rule_a(features)


def public_giveup_score_la(
    features: Mapping[str, Any],
) -> Dict[str, Any]:
    """Score family B — LA public give-up score ∈ [0,1] (parallel dig)."""
    f = ensure_ambition_on_features(features)
    if _fb(f, "holds_la", False):
        return {
            "special": "la",
            "variant": "score_b",
            "score": 0.0,
            "public_giveup": False,
            "phi": SCORE_B_PHI_DEFAULT,
            "reason": "holds",
            "spec_freeze_id": SPEC_FREEZE_ID,
        }
    gap = max(0, _fi(f, "gap_la", 0))
    amb = str(f.get("ambition_la") or "none")
    threats = max(0, _fi(f, "n_threats_la", 0))
    delta_active = _fb(f, "delta_active", False)
    try:
        d_army = int(f.get("delta_army") or 0)
    except Exception:
        d_army = 0
    weak_amb = 1.0 if amb in RULE_A_WEAK_AMBITION else 0.0
    stagnant = 1.0 if (delta_active and d_army <= 0) else 0.0
    score = (
        SCORE_B_W_GAP * _clamp01(gap / max(SCORE_B_LA_GAP_NORM, 1e-6))
        + SCORE_B_W_WEAK_AMB * weak_amb
        + SCORE_B_W_STAGNANT * stagnant
        + SCORE_B_W_THREATS * _clamp01(threats / 3.0)
    )
    score = round(_clamp01(score), 4)
    return {
        "special": "la",
        "variant": "score_b",
        "score": score,
        "public_giveup": score >= SCORE_B_PHI_DEFAULT,
        "phi": SCORE_B_PHI_DEFAULT,
        "reason": "score",
        "spec_freeze_id": SPEC_FREEZE_ID,
    }


def public_giveup_score_lr(
    features: Mapping[str, Any],
) -> Dict[str, Any]:
    """Score family B — LR public give-up score ∈ [0,1] (parallel dig)."""
    f = ensure_ambition_on_features(features)
    if _fb(f, "holds_lr", False):
        return {
            "special": "lr",
            "variant": "score_b",
            "score": 0.0,
            "public_giveup": False,
            "phi": SCORE_B_PHI_DEFAULT,
            "reason": "holds",
            "spec_freeze_id": SPEC_FREEZE_ID,
        }
    gap = max(0, _fi(f, "gap_lr", 0))
    amb = str(f.get("ambition_lr") or "none")
    threats = max(0, _fi(f, "n_threats_lr", 0))
    cap = max(0, _fi(f, "roads_remaining_cap", 15))
    delta_active = _fb(f, "delta_active", False)
    try:
        d_path = int(f.get("delta_path") or 0)
    except Exception:
        d_path = 0
    weak_amb = 1.0 if amb in RULE_A_WEAK_AMBITION else 0.0
    stagnant = 1.0 if (delta_active and d_path <= 0) else 0.0
    cap_pressure = 1.0 if cap <= 2 else 0.0
    w_threats = SCORE_B_W_THREATS - SCORE_B_W_LR_CAP
    score = (
        SCORE_B_W_GAP * _clamp01(gap / max(SCORE_B_LR_GAP_NORM, 1e-6))
        + SCORE_B_W_WEAK_AMB * weak_amb
        + SCORE_B_W_STAGNANT * stagnant
        + w_threats * _clamp01(threats / 3.0)
        + SCORE_B_W_LR_CAP * cap_pressure
    )
    score = round(_clamp01(score), 4)
    return {
        "special": "lr",
        "variant": "score_b",
        "score": score,
        "public_giveup": score >= SCORE_B_PHI_DEFAULT,
        "phi": SCORE_B_PHI_DEFAULT,
        "reason": "score",
        "spec_freeze_id": SPEC_FREEZE_ID,
    }


def public_giveup_score(
    features: Mapping[str, Any],
    special: str,
    *,
    phi: Optional[float] = None,
) -> Dict[str, Any]:
    """Score family B for one special; optional φ override for grids."""
    sp = str(special or "la").strip().lower()
    rec = public_giveup_score_lr(features) if sp == "lr" else public_giveup_score_la(features)
    if phi is not None:
        th = float(phi)
        rec = dict(rec)
        rec["phi"] = th
        rec["public_giveup"] = float(rec.get("score") or 0.0) >= th
    return rec


def public_giveup_mvp(
    features: Mapping[str, Any],
    special: str,
    *,
    lr_variant: Optional[str] = None,
) -> Dict[str, Any]:
    """MVP proxy: LA rule_a; LR uses ``lr_variant`` or default."""
    return public_giveup_flag_rule_a(
        features, special, lr_variant=lr_variant or LR_PROXY_DEFAULT_VARIANT
    )


def public_giveup_pair(
    features: Mapping[str, Any],
    *,
    include_score_b: bool = True,
    lr_variant: Optional[str] = None,
) -> Dict[str, Any]:
    """Both specials: rule A flags (+ optional score B for dig)."""
    f = ensure_ambition_on_features(features)
    la_a = public_giveup_flag_la_rule_a(f)
    lr_a = public_giveup_flag_lr_rule_a(f, variant=lr_variant)
    out: Dict[str, Any] = {
        "rule_a_la": la_a,
        "rule_a_lr": lr_a,
        "public_giveup_la": bool(la_a.get("public_giveup")),
        "public_giveup_lr": bool(lr_a.get("public_giveup")),
        "variant_mvp": PROXY_MVP_VARIANT,
        "spec_freeze_id": SPEC_FREEZE_ID,
    }
    if include_score_b:
        la_b = public_giveup_score_la(f)
        lr_b = public_giveup_score_lr(f)
        out["score_b_la"] = la_b
        out["score_b_lr"] = lr_b
        out["public_giveup_score_b_la"] = bool(la_b.get("public_giveup"))
        out["public_giveup_score_b_lr"] = bool(lr_b.get("public_giveup"))
    return out


__all__ = [
    "GATE_FGU_MAX",
    "GATE_PRECISION_MIN",
    "GATE_SOFT_PRECISION_MIN",
    "LR_PROXY_DEFAULT_VARIANT",
    "LR_RULE_PROFILES",
    "PROXY_MVP_VARIANT",
    "PUBLIC_GIVEUP_SCHEMA_VERSION",
    "RULE_A_LA_ARMY_HARD_MAX",
    "RULE_A_LA_ARMY_WEAK_MAX",
    "RULE_A_LA_GAP_HARD",
    "RULE_A_LA_GAP_WEAK",
    "RULE_A_LR_BOXED_GAP_MIN",
    "RULE_A_LR_GAP_WEAK",
    "RULE_A_LR_PATH_BAR",
    "RULE_A_WEAK_AMBITION",
    "SCORE_B_PHI_DEFAULT",
    "SPEC_FREEZE_ID",
    "TEACHER_REQUIRE_NOT_HOLDS",
    "THETA_LA_SAFE",
    "THETA_LR_SAFE",
    "build_teacher_record",
    "ensure_ambition_on_features",
    "filter_reason_teacher",
    "hopeless_score_from_row",
    "is_needs_conditioned_row",
    "l5_freeze_snapshot",
    "list_lr_rule_variants",
    "probe_holds",
    "probe_needs",
    "public_giveup_flag_la_rule_a",
    "public_giveup_flag_lr_rule_a",
    "public_giveup_flag_rule_a",
    "public_giveup_mvp",
    "public_giveup_pair",
    "public_giveup_score",
    "public_giveup_score_la",
    "public_giveup_score_lr",
    "resolve_lr_profile",
    "resolve_theta",
    "special_block_from_row",
    "teacher_fire_at_theta",
    "teacher_pair_from_row",
]
