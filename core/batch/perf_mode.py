"""Batch performance mode — lean digs vs full dig instrumentation.

Use for dual runs: same ``--arm`` seat map / dice, once with ``--perf on``
(speed / ditch-S142 evidence on wall) and once with ``--perf off`` (full
transparency digs). Does **not** enable S142 drive.

``on``  = dig scaffolding off (shadow, way_reassess, LA/LR probe, MGLOG,
         plan snapshot, dossier, target screen). SE sync-first + adaptive kept.
``off`` = dig scaffolding on (lab transparency defaults).
``None`` / omit = leave ``core.constants`` unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

PERF_ON = "on"
PERF_OFF = "off"

# Dig / I/O pack — SE policy (sync-first, adaptive, a/b/c [0]) left alone.
PERF_FLAG_PACK: Dict[str, Dict[str, Any]] = {
    PERF_ON: {
        "L2_SHADOW_MISS": "off",
        "L2_SHADOW_EVERY_N": 1,
        "L2_DOSSIER": "off",
        "L2_TARGET_SCREEN": "off",
        "LOG_WAY_COMPARE": False,
        "LOG_LA_LR_PROBE": False,
        "MGLOG": False,
        "PLAN_SNAPSHOT": "off",
        "SIDESTEP_S142_DRIVE": False,
        "SIDESTEP_S142_TRIGGERS": False,
        # Keep product SE spine
        "L2_SYNC_FIRST": "on",
        "L2_ADAPTIVE_K": "on",
    },
    PERF_OFF: {
        "L2_SHADOW_MISS": "on",
        "L2_SHADOW_EVERY_N": 1,
        "L2_DOSSIER": "cs",
        "L2_TARGET_SCREEN": "mark_only",
        "LOG_WAY_COMPARE": True,
        "LOG_LA_LR_PROBE": True,
        "MGLOG": True,
        "PLAN_SNAPSHOT": "on",
        "SIDESTEP_S142_DRIVE": False,
        "SIDESTEP_S142_TRIGGERS": False,
        "L2_SYNC_FIRST": "on",
        "L2_ADAPTIVE_K": "on",
    },
}

# Game attribute mirrors (runtime readers that check game.* first)
_GAME_ATTR_MAP = {
    "L2_SHADOW_MISS": "l2_shadow_miss",
    "L2_SHADOW_EVERY_N": "l2_shadow_every_n",
    "L2_DOSSIER": "l2_dossier",
    "L2_TARGET_SCREEN": "l2_target_screen",
    "L2_SYNC_FIRST": "l2_sync_first",
    "L2_ADAPTIVE_K": "l2_adaptive_k",
    "SIDESTEP_S142_DRIVE": "sidestep_s142_drive",
}


def normalize_perf_mode(raw: Any) -> Optional[str]:
    """Return ``on`` / ``off`` / None."""
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("_", "-")
    if s in ("", "none", "default", "auto"):
        return None
    if s in ("on", "true", "1", "yes", "perf", "perf-on", "speed", "lean"):
        return PERF_ON
    if s in ("off", "false", "0", "no", "perf-off", "digs", "full", "dig"):
        return PERF_OFF
    return None


def parse_arm_perf_suffix(arm: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split ``control+perf`` / ``control+perf-off`` → (base_arm, perf_mode).

    Also accepts trailing ``/perf`` or ``/perf-on``.
    """
    text = str(arm or "").strip()
    if not text:
        return None, None
    low = text.lower().replace("_", "-")
    # Whole-arm aliases
    if low in ("perf", "perf-on", "speed"):
        return "control", PERF_ON
    if low in ("perf-off", "digs"):
        return "control", PERF_OFF

    base = text
    mode = None
    for sep in ("+", "/"):
        if sep not in low:
            continue
        # split from right once
        idx = low.rfind(sep)
        left, right = low[:idx], low[idx + 1 :]
        m = normalize_perf_mode(right)
        if m is not None or right in ("perf",):
            mode = m or PERF_ON
            # preserve original casing/spacing of left from text
            base = text[:idx]
            break
        if right in ("perf-on", "perf-off", "speed", "digs", "full"):
            mode = normalize_perf_mode(right)
            base = text[:idx]
            break
    return (base or None), mode


def perf_flag_pack(mode: Optional[str]) -> Dict[str, Any]:
    m = normalize_perf_mode(mode)
    if m is None:
        return {}
    return dict(PERF_FLAG_PACK.get(m) or {})


def apply_perf_mode_to_constants(mode: Optional[str]) -> Dict[str, Any]:
    """Mutate ``core.constants`` for this process. Returns applied {name: value}."""
    m = normalize_perf_mode(mode)
    if m is None:
        return {}
    pack = perf_flag_pack(m)
    applied: Dict[str, Any] = {"perf_mode": m}
    try:
        from core import constants as C

        for key, val in pack.items():
            if hasattr(C, key):
                setattr(C, key, val)
                applied[key] = val
    except Exception as exc:
        applied["error"] = str(exc)[:160]
    return applied


def apply_perf_mode_to_game(game: Any, mode: Optional[str]) -> Dict[str, Any]:
    """Stamp game attrs for readers that prefer game.* over constants."""
    m = normalize_perf_mode(mode)
    if m is None or game is None:
        return {}
    pack = perf_flag_pack(m)
    applied: Dict[str, Any] = {"perf_mode": m}
    try:
        setattr(game, "perf_mode", m)
    except Exception:
        pass
    for const_key, attr in _GAME_ATTR_MAP.items():
        if const_key not in pack:
            continue
        try:
            setattr(game, attr, pack[const_key])
            applied[attr] = pack[const_key]
        except Exception:
            pass
    return applied


def apply_perf_mode(mode: Optional[str], game: Any = None) -> Dict[str, Any]:
    """Apply to constants (+ optional game). Safe no-op when mode is None."""
    bag = apply_perf_mode_to_constants(mode)
    if game is not None and bag.get("perf_mode"):
        gbag = apply_perf_mode_to_game(game, bag.get("perf_mode"))
        bag["game"] = gbag
    return bag


def enrich_arm_config_with_perf(
    arm_config: Optional[Mapping[str, Any]],
    *,
    perf: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach perf_mode + flags to arm config; optionally rename arm_name."""
    cfg = dict(arm_config or {})
    mode = normalize_perf_mode(perf)
    if mode is None:
        mode = normalize_perf_mode(cfg.get("perf_mode"))
    if mode is None:
        return cfg
    cfg["perf_mode"] = mode
    cfg["perf_flags"] = perf_flag_pack(mode)
    name = str(cfg.get("arm_name") or "").strip()
    suffix = f"+perf_{mode}"
    if name:
        if "+perf" not in name.lower():
            cfg["arm_name"] = f"{name}{suffix}"
    else:
        cfg["arm_name"] = f"control{suffix}"
    return cfg


__all__ = [
    "PERF_ON",
    "PERF_OFF",
    "PERF_FLAG_PACK",
    "normalize_perf_mode",
    "parse_arm_perf_suffix",
    "perf_flag_pack",
    "apply_perf_mode_to_constants",
    "apply_perf_mode_to_game",
    "apply_perf_mode",
    "enrich_arm_config_with_perf",
]
