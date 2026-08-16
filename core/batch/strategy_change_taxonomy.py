"""Phase C WP-C0: closed taxonomies for CS strategy probes (pure, no Game).

Classifies:
  - Victory-Way changes (way_change_class)
  - Sticky rec-target changes (target_change_class)
  - ETA setbacks (setback_class)
  - Cross-probe anomalies (anomaly_*)

Writers (schema v2) may pre-assign ``way_switch_cause`` / ``target_switch_cause``;
classifiers prefer those when present and valid. Offline heuristics use CS-like
row dicts + optional previous sample / context.

Does not mutate board state or call strategy engines.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ── Schema / defaults ────────────────────────────────────────────────────────

SETBACK_THRESHOLD_DEFAULT = 1.0
TARGET_THRASH_PER_ROUND_DEFAULT = 3

# ── Closed tables ────────────────────────────────────────────────────────────

WAY_CHANGE_CLASSES = frozenset(
    {
        "first_lock",
        "race_road",
        "race_settle",
        "target_blocked",
        "offway_opportunity",
        "way_kill",
        "specials_shock",
        "soft_eta_switch",
        "hard_invalid",
        "endgame_reshape",
        "unknown",
    }
)

# Priority for primary_class (first match wins among fired tags)
WAY_CHANGE_PRIORITY: Tuple[str, ...] = (
    "first_lock",
    "way_kill",
    "target_blocked",
    "race_settle",
    "race_road",
    "offway_opportunity",
    "specials_shock",
    "hard_invalid",
    "soft_eta_switch",
    "endgame_reshape",
    "unknown",
)

TARGET_CHANGE_CLASSES = frozenset(
    {
        "first_lock",
        "achieve_settle",
        "achieve_city",
        "achieve_component",
        "race_road",
        "race_settle",
        "target_blocked",
        "offway_opportunity",
        "race_impossible",
        "route_illegal",
        "same_way_rerank",
        "specials_project",
        "way_switch_cascade",
        "unknown",
    }
)

TARGET_CHANGE_PRIORITY: Tuple[str, ...] = (
    "first_lock",
    "achieve_settle",
    "achieve_city",
    "achieve_component",
    "target_blocked",
    "race_settle",
    "race_road",
    "route_illegal",
    "race_impossible",
    "offway_opportunity",
    "specials_project",
    "way_switch_cascade",
    "same_way_rerank",
    "unknown",
)

ACHIEVE_TARGET_CLASSES = frozenset(
    {"achieve_settle", "achieve_city", "achieve_component"}
)

SETBACK_CLASSES = frozenset(
    {
        "way_switch",
        "specials_la",
        "specials_lr",
        "robber",
        "discard_7",
        "monopoly",
        "dcard_draw_noise",
        "trade_reprice",
        "build_spent",
        "progress_paradox",
        "estimator_jump",
        "unknown",
    }
)

SETBACK_PRIORITY: Tuple[str, ...] = (
    "way_switch",
    "specials_la",
    "specials_lr",
    "robber",
    "discard_7",
    "monopoly",
    "build_spent",
    "progress_paradox",
    "trade_reprice",
    "dcard_draw_noise",
    "estimator_jump",
    "unknown",
)

ANOMALY_CLASSES = frozenset(
    {
        "anomaly_way_change_on_achieve",
        "anomaly_way_change_hand_only",
        "anomaly_q2_way_change",
        "anomaly_target_thrash",
    }
)

# Sticky invalidate / engine reason → candidate classes
# More specific needles first (substring match).
_INVALIDATE_TO_WAY: Tuple[Tuple[str, str], ...] = (
    ("own_rec_settle_complete", "unknown"),  # should not force way alone
    ("own_rec_city_complete", "unknown"),
    ("target_occupied", "target_blocked"),
    ("target_blocked", "target_blocked"),
    ("target_race_impossible", "race_settle"),
    ("opponent_road", "race_road"),
    ("race_road", "race_road"),
    ("race_settle", "race_settle"),
    ("likely_lost", "race_settle"),
    ("route_illegal", "hard_invalid"),
    ("route", "hard_invalid"),
    ("illegal", "hard_invalid"),
    ("locked_way_infeasible", "way_kill"),
    ("way_kill", "way_kill"),
    ("infeasible", "way_kill"),
    ("s14_2", "offway_opportunity"),
    ("offway", "offway_opportunity"),
    ("q1", "offway_opportunity"),
    ("hard_invalid", "hard_invalid"),
    ("sticky_dead", "hard_invalid"),
    ("no_commitment", "hard_invalid"),
    ("la_lr", "specials_shock"),
    ("specials", "specials_shock"),
    ("opponent_settlement", "target_blocked"),
    ("opponent_city", "target_blocked"),
    ("opponent_structure", "target_blocked"),
    ("endgame", "endgame_reshape"),
)

_INVALIDATE_TO_TARGET: Tuple[Tuple[str, str], ...] = (
    ("own_rec_settle_complete", "achieve_settle"),
    ("own_rec_city_complete", "achieve_city"),
    ("settle_complete", "achieve_settle"),
    ("city_complete", "achieve_city"),
    ("target_occupied", "target_blocked"),
    ("target_blocked", "target_blocked"),
    ("target_race_impossible", "race_impossible"),
    ("race_impossible", "race_impossible"),
    ("opponent_road", "race_road"),
    ("race_road", "race_road"),
    ("route_illegal", "route_illegal"),
    ("route", "route_illegal"),
    ("illegal", "route_illegal"),
    ("s14_2", "offway_opportunity"),
    ("offway", "offway_opportunity"),
    ("q1", "offway_opportunity"),
    ("lr_project", "specials_project"),
    ("la_progress", "specials_project"),
    ("opponent_settlement", "target_blocked"),
    ("opponent_city", "target_blocked"),
    ("strategy_recalc", "same_way_rerank"),
)

_HAND_ONLY_REASON_TOKENS = (
    "twp",
    "twb",
    "trade_with_bank",
    "trade_with_player",
    "dice_roll",
    "post_dice",
    "production",
    "hand",
    "q2",
    "offway_dcard",
    "buy_development",  # alone often hand-ish; used carefully
)

_Q2_REASON_TOKENS = ("q2", "offway_dcard", "off_way_dcard")

_ROBBER_TOKENS = ("robber", "steal", "move_robber", "basic_robber")
_MONOPOLY_TOKENS = ("monopoly",)
_DISCARD_TOKENS = ("discard", "dr7", "dice_7", "roll_7")
_BUILD_TOKENS = ("build_road", "build_settlement", "build_city", "build_")
_TRADE_TOKENS = ("twp", "twb", "trade_with")
_DCARD_TOKENS = ("buy_development", "play_yop", "play_tfr", "dcard", "development")


# ── Small helpers ────────────────────────────────────────────────────────────


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def _s(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _s(value).lower()


def _has_token(text: str, tokens: Sequence[str]) -> bool:
    t = text.lower()
    return any(tok in t for tok in tokens)


def _pick_primary(tags: Sequence[str], priority: Sequence[str]) -> str:
    tag_set = {str(t) for t in tags if t}
    for code in priority:
        if code in tag_set:
            return code
    return "unknown"


def _map_invalidate(reason: str, table: Sequence[Tuple[str, str]]) -> Optional[str]:
    r = reason.lower()
    if not r:
        return None
    for needle, code in table:
        if needle in r:
            return code
    return None


def is_hand_only_reason(reason: Any, *, allow_buy_dcard: bool = True) -> bool:
    """True when refresh reason looks like pure hand / trade / dice (no structure)."""
    r = _lower(reason)
    if not r:
        return False
    # Structure / board shocks disqualify hand-only
    if _has_token(
        r,
        (
            "build_",
            "opponent_",
            "robber",
            "way_kill",
            "q1",
            "offway_structure",
            "force_explore",
            "sticky",
            "start_execution",
            "move_robber",
        ),
    ):
        # Robber is not hand-only for anomaly hand_only (it's board-ish)
        if _has_token(r, _ROBBER_TOKENS) and not _has_token(r, ("twp", "twb", "dice")):
            return False
        if _has_token(r, ("build_", "opponent_", "way_kill", "q1", "offway_structure")):
            return False
    tokens = list(_HAND_ONLY_REASON_TOKENS)
    if not allow_buy_dcard:
        tokens = [t for t in tokens if t != "buy_development"]
    # Must match at least one hand-ish token and not look like structure refresh
    if not _has_token(r, tokens):
        return False
    if _has_token(r, ("build_settlement", "build_city", "build_road", "opponent_")):
        return False
    return True


def is_q2_reason(reason: Any) -> bool:
    return _has_token(_lower(reason), _Q2_REASON_TOKENS)


def roads_fingerprint(roads: Any) -> Optional[str]:
    """Stable short fingerprint for locked_roads_to_build (C1/C2 shared)."""
    if roads is None:
        return None
    edges: List[Tuple[int, int]] = []
    try:
        for edge in list(roads or []):
            if isinstance(edge, Mapping):
                a = edge.get("a", edge.get(0))
                b = edge.get("b", edge.get(1))
                if a is None or b is None:
                    vals = list(edge.values())[:2]
                    if len(vals) < 2:
                        continue
                    a, b = vals[0], vals[1]
            elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                a, b = edge[0], edge[1]
            else:
                continue
            try:
                pair = tuple(sorted((int(a), int(b))))
            except Exception:
                continue
            edges.append(pair)  # type: ignore[arg-type]
    except Exception:
        return None
    if not edges:
        return ""
    edges = sorted(set(edges))
    return ";".join(f"{a}-{b}" for a, b in edges)


# ── Writer-cause validation ──────────────────────────────────────────────────


def normalize_way_cause(code: Any) -> Optional[str]:
    c = _s(code)
    if c in WAY_CHANGE_CLASSES:
        return c
    return None


def normalize_target_cause(code: Any) -> Optional[str]:
    c = _s(code)
    if c in TARGET_CHANGE_CLASSES:
        return c
    return None


def normalize_setback_class(code: Any) -> Optional[str]:
    c = _s(code)
    if c in SETBACK_CLASSES:
        return c
    return None


# ── Classify: way ────────────────────────────────────────────────────────────


def classify_way_change(
    row: Mapping[str, Any],
    prev: Optional[Mapping[str, Any]] = None,
    *,
    ctx: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify a Victory-Way change event.

    ``row`` is a CS-like dict (v1 or v2). ``prev`` is previous sample same player.
    ``ctx`` optional: la_holder_changed, lr_holder_changed, etc.

    Returns ``{primary_class, tags, confidence, evidence, is_first_lock}``.
    """
    ctx = dict(ctx or {})
    prev = prev if isinstance(prev, Mapping) else {}
    evidence: List[str] = []
    tags: List[str] = []

    # Prefer writer cause
    writer = normalize_way_cause(row.get("way_switch_cause"))
    if writer:
        return {
            "primary_class": writer,
            "tags": [writer],
            "confidence": "high",
            "evidence": ["writer:way_switch_cause"],
            "is_first_lock": writer == "first_lock",
        }

    way = _safe_int(row.get("sticky_way_id"), _safe_int(row.get("way_id")))
    prev_way = _safe_int(
        row.get("prev_sticky_way_id"),
        _safe_int(row.get("prev_way_id"), _safe_int(prev.get("sticky_way_id"), _safe_int(prev.get("way_id")))),
    )
    inv = _lower(row.get("sticky_invalidate_reason") or row.get("invalidate_reason") or "")
    reason = _lower(row.get("reason") or "")
    achieve = _lower(row.get("achieve_kind") or "")

    is_first = bool(row.get("is_first_way_lock")) or (
        prev_way is None and way is not None
    )
    if is_first and (prev_way is None or bool(row.get("is_first_way_lock"))):
        # first lock only when prev truly empty
        if prev_way is None:
            tags.append("first_lock")
            evidence.append("prev_way=null")

    mapped = _map_invalidate(inv, _INVALIDATE_TO_WAY)
    if mapped and mapped != "unknown":
        tags.append(mapped)
        evidence.append(f"invalidate={inv[:80]}")

    if row.get("q1_offway") or _has_token(reason, ("q1", "offway_structure", "off_strategy")):
        tags.append("offway_opportunity")
        evidence.append("q1/offway")

    kill = _lower(row.get("way_kill_kind") or "")
    if kill or _has_token(inv, ("way_kill", "infeasible")) or _has_token(reason, ("way_kill",)):
        tags.append("way_kill")
        evidence.append(f"way_kill={kill or 'flag'}")

    if ctx.get("la_holder_changed") or ctx.get("lr_holder_changed"):
        tags.append("specials_shock")
        evidence.append("specials_holder_changed")
    elif _has_token(inv, ("la_lr", "specials")) or _has_token(reason, ("largest_army", "longest_road", "la_lr")):
        tags.append("specials_shock")
        evidence.append("specials_token")

    if _has_token(inv, ("target_occupied", "target_blocked", "opponent_settlement", "opponent_city")):
        tags.append("target_blocked")
        evidence.append("blocked_token")

    if _has_token(inv, ("opponent_road", "race_road")):
        tags.append("race_road")
        evidence.append("race_road_token")
    elif _has_token(inv, ("race_settle", "target_race", "likely_lost")):
        tags.append("race_settle")
        evidence.append("race_settle_token")

    if _has_token(inv, ("hard_invalid", "route", "illegal", "sticky_dead", "no_commitment")):
        tags.append("hard_invalid")
        evidence.append("hard_invalid_token")

    if _has_token(reason, ("endgame",)) or _has_token(inv, ("endgame",)):
        tags.append("endgame_reshape")
        evidence.append("endgame")

    # Soft ETA: way changed, L2/explore, no hard tags yet
    l2 = _lower(row.get("l2_bucket") or row.get("l2_force_reason") or "")
    delta = _safe_float(row.get("delta_turns"))
    switch_gain = _safe_float(row.get("switch_eta_gain"))
    hardish = bool(
        set(tags)
        & {
            "way_kill",
            "target_blocked",
            "race_settle",
            "race_road",
            "offway_opportunity",
            "specials_shock",
            "hard_invalid",
            "first_lock",
        }
    )
    if not hardish and (way is not None and prev_way is not None and way != prev_way):
        if switch_gain is not None and switch_gain >= 1.0:
            tags.append("soft_eta_switch")
            evidence.append(f"switch_eta_gain={switch_gain}")
        elif "explore" in l2 or "l2" in l2 or _has_token(reason, ("force_explore", "portfolio")):
            tags.append("soft_eta_switch")
            evidence.append("l2/explore_soft")
        elif delta is not None and delta <= -1.0:
            tags.append("soft_eta_switch")
            evidence.append(f"delta_turns={delta}")

    if achieve and not hardish:
        # achieve alone is not a way class — leave for anomaly
        evidence.append(f"achieve_kind={achieve}")

    primary = _pick_primary(tags, WAY_CHANGE_PRIORITY)
    confidence = "medium" if evidence else "low"
    if inv and primary != "unknown":
        confidence = "medium"
    if primary == "unknown" and not evidence:
        confidence = "low"
        evidence.append("no_rule")

    return {
        "primary_class": primary,
        "tags": sorted(set(tags)) if tags else ([primary] if primary != "unknown" else []),
        "confidence": confidence,
        "evidence": evidence,
        "is_first_lock": primary == "first_lock" or (is_first and primary == "first_lock"),
    }


# ── Classify: target ─────────────────────────────────────────────────────────


def classify_target_change(
    row: Mapping[str, Any],
    prev: Optional[Mapping[str, Any]] = None,
    *,
    ctx: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify a sticky rec-target change event."""
    ctx = dict(ctx or {})
    prev = prev if isinstance(prev, Mapping) else {}
    evidence: List[str] = []
    tags: List[str] = []

    writer = normalize_target_cause(row.get("target_switch_cause"))
    if writer:
        return {
            "primary_class": writer,
            "tags": [writer],
            "confidence": "high",
            "evidence": ["writer:target_switch_cause"],
            "is_first_lock": writer == "first_lock",
            "is_achieve": writer in ACHIEVE_TARGET_CLASSES,
        }

    tid = _safe_int(row.get("sticky_target_id"), _safe_int(row.get("rec_target_id")))
    prev_tid = _safe_int(
        row.get("prev_sticky_target_id"),
        _safe_int(prev.get("sticky_target_id"), _safe_int(prev.get("rec_target_id"))),
    )
    way = _safe_int(row.get("sticky_way_id"), _safe_int(row.get("way_id")))
    prev_way = _safe_int(
        row.get("prev_sticky_way_id"),
        _safe_int(row.get("prev_way_id"), _safe_int(prev.get("sticky_way_id"), _safe_int(prev.get("way_id")))),
    )
    inv = _lower(row.get("sticky_invalidate_reason") or row.get("invalidate_reason") or "")
    reason = _lower(row.get("reason") or "")
    achieve = _lower(row.get("achieve_kind") or "")
    kind = _lower(row.get("sticky_target_kind") or row.get("target_kind") or "")

    is_first = bool(row.get("is_first_target_lock")) or (prev_tid is None and tid is not None)
    if is_first and prev_tid is None:
        tags.append("first_lock")
        evidence.append("prev_target=null")

    if achieve in ("settle", "settlement", "s"):
        tags.append("achieve_settle")
        evidence.append("achieve_kind=settle")
    elif achieve in ("city", "c"):
        tags.append("achieve_city")
        evidence.append("achieve_kind=city")
    elif achieve in ("component", "roads", "knight", "other"):
        tags.append("achieve_component")
        evidence.append(f"achieve_kind={achieve}")

    mapped = _map_invalidate(inv, _INVALIDATE_TO_TARGET)
    if mapped:
        tags.append(mapped)
        evidence.append(f"invalidate={inv[:80]}")

    if row.get("q1_offway") or _has_token(reason, ("q1", "offway_structure")):
        tags.append("offway_opportunity")
        evidence.append("q1/offway")

    # Way changed alongside target → cascade (unless first lock / achieve only)
    way_changed = bool(row.get("way_changed"))
    if not way_changed and way is not None and prev_way is not None and way != prev_way:
        way_changed = True
    if way_changed and "first_lock" not in tags:
        tags.append("way_switch_cascade")
        evidence.append("way_changed")

    if _has_token(inv, ("lr_project", "la_progress", "specials_project")) or ctx.get(
        "specials_project"
    ):
        tags.append("specials_project")
        evidence.append("specials_project")

    # Same way, new target, no hard story → rerank
    hardish = bool(
        set(tags)
        & (
            ACHIEVE_TARGET_CLASSES
            | {
                "first_lock",
                "target_blocked",
                "race_settle",
                "race_road",
                "route_illegal",
                "race_impossible",
                "offway_opportunity",
            }
        )
    )
    if (
        not hardish
        and tid is not None
        and prev_tid is not None
        and tid != prev_tid
        and way is not None
        and prev_way is not None
        and way == prev_way
    ):
        tags.append("same_way_rerank")
        evidence.append("same_way_new_target")

    # Infer achieve from build reason + progress bump
    if "achieve_settle" not in tags and "achieve_city" not in tags:
        if "build_settlement" in reason and _progress_up(row, prev, "settlements_owned"):
            tags.append("achieve_settle")
            evidence.append("build_settlement+settlements_up")
        if "build_city" in reason and _progress_up(row, prev, "cities_owned"):
            tags.append("achieve_city")
            evidence.append("build_city+cities_up")

    primary = _pick_primary(tags, TARGET_CHANGE_PRIORITY)
    confidence = "medium" if evidence else "low"
    if inv and primary != "unknown":
        confidence = "medium"

    return {
        "primary_class": primary,
        "tags": sorted(set(tags)) if tags else [],
        "confidence": confidence,
        "evidence": evidence,
        "is_first_lock": primary == "first_lock",
        "is_achieve": primary in ACHIEVE_TARGET_CLASSES,
    }


def _progress_up(
    row: Mapping[str, Any], prev: Mapping[str, Any], key: str
) -> bool:
    cur = _safe_int(row.get(key))
    old = _safe_int(prev.get(key)) if prev else None
    if cur is None or old is None:
        return False
    return cur > old


# ── Classify: setback ────────────────────────────────────────────────────────


def is_setback(
    row: Mapping[str, Any],
    *,
    threshold: float = SETBACK_THRESHOLD_DEFAULT,
    prev: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, Optional[float]]:
    """Return (is_setback, delta_turns) using logged or recomputed Δ."""
    delta = _safe_float(row.get("delta_turns"))
    if delta is None and prev is not None:
        turns = _safe_float(row.get("turns"))
        prev_turns = _safe_float(prev.get("turns"), _safe_float(row.get("prev_turns")))
        if turns is not None and prev_turns is not None:
            delta = turns - prev_turns
    if delta is None:
        # try prev_turns on same row
        turns = _safe_float(row.get("turns"))
        prev_turns = _safe_float(row.get("prev_turns"))
        if turns is not None and prev_turns is not None:
            delta = turns - prev_turns
    if delta is None:
        return False, None
    return float(delta) >= float(threshold), float(delta)


def classify_setback(
    row: Mapping[str, Any],
    prev: Optional[Mapping[str, Any]] = None,
    *,
    ctx: Optional[Mapping[str, Any]] = None,
    threshold: float = SETBACK_THRESHOLD_DEFAULT,
) -> Dict[str, Any]:
    """Classify an ETA setback (call after is_setback is True)."""
    ctx = dict(ctx or {})
    prev = prev if isinstance(prev, Mapping) else {}
    evidence: List[str] = []
    tags: List[str] = []

    ok, delta = is_setback(row, threshold=threshold, prev=prev)
    if not ok:
        return {
            "primary_class": "unknown",
            "tags": [],
            "confidence": "low",
            "evidence": ["not_a_setback"],
            "delta_turns": delta,
            "is_setback": False,
        }

    reason = _lower(row.get("reason") or "")
    way = _safe_int(row.get("sticky_way_id"), _safe_int(row.get("way_id")))
    prev_way = _safe_int(
        row.get("prev_sticky_way_id"),
        _safe_int(row.get("prev_way_id"), _safe_int(prev.get("way_id"))),
    )
    way_changed = bool(row.get("way_changed")) or (
        way is not None and prev_way is not None and way != prev_way
    )

    if way_changed:
        tags.append("way_switch")
        evidence.append("way_changed")

    if ctx.get("la_holder_changed") or _holder_changed(row, prev, "la_holder_id"):
        tags.append("specials_la")
        evidence.append("la_holder_changed")
    if ctx.get("lr_holder_changed") or _holder_changed(row, prev, "lr_holder_id"):
        tags.append("specials_lr")
        evidence.append("lr_holder_changed")

    if _has_token(reason, _ROBBER_TOKENS):
        tags.append("robber")
        evidence.append("reason_robber")

    if _has_token(reason, _DISCARD_TOKENS) or (
        _has_token(reason, ("dice",)) and _hand_drop(row, prev) >= 4
    ):
        # discard_7: large hand drop without clear build reason
        if not _has_token(reason, _BUILD_TOKENS):
            tags.append("discard_7")
            evidence.append("discard_or_hand_drop")

    if _has_token(reason, _MONOPOLY_TOKENS):
        tags.append("monopoly")
        evidence.append("monopoly")

    if _has_token(reason, _TRADE_TOKENS):
        tags.append("trade_reprice")
        evidence.append("trade")

    if _has_token(reason, _DCARD_TOKENS) and not way_changed:
        tags.append("dcard_draw_noise")
        evidence.append("dcard")

    if _has_token(reason, _BUILD_TOKENS):
        tags.append("build_spent")
        evidence.append("build")

    if _progress_up(row, prev, "vp_effective") or _progress_up(
        row, prev, "settlements_owned"
    ) or _progress_up(row, prev, "cities_owned"):
        if delta is not None and delta > 0:
            tags.append("progress_paradox")
            evidence.append("progress_up_eta_worse")

    hardish = bool(
        set(tags)
        & {
            "way_switch",
            "specials_la",
            "specials_lr",
            "robber",
            "discard_7",
            "monopoly",
            "build_spent",
            "trade_reprice",
            "dcard_draw_noise",
            "progress_paradox",
        }
    )
    if not hardish and delta is not None and delta >= max(threshold, 2.0):
        tags.append("estimator_jump")
        evidence.append(f"large_delta={delta}")
    elif not hardish:
        tags.append("estimator_jump")
        evidence.append("thin_story")

    primary = _pick_primary(tags, SETBACK_PRIORITY)
    confidence = "medium" if hardish else "low"

    return {
        "primary_class": primary,
        "tags": sorted(set(tags)),
        "confidence": confidence,
        "evidence": evidence,
        "delta_turns": delta,
        "is_setback": True,
    }


def _holder_changed(
    row: Mapping[str, Any], prev: Mapping[str, Any], key: str
) -> bool:
    a = _safe_int(row.get(key))
    b = _safe_int(prev.get(key)) if prev else None
    if a is None and b is None:
        return False
    return a != b


def _hand_drop(row: Mapping[str, Any], prev: Mapping[str, Any]) -> float:
    cur = _safe_float(row.get("hand_total"))
    old = _safe_float(prev.get("hand_total")) if prev else _safe_float(row.get("prev_hand_total"))
    if cur is None or old is None:
        return 0.0
    return max(0.0, old - cur)


# ── Anomalies ────────────────────────────────────────────────────────────────


def detect_anomalies(
    *,
    way_changed: bool,
    way_class: Optional[str] = None,
    target_class: Optional[str] = None,
    reason: Any = "",
    hard_board_evidence: bool = False,
    target_changes_this_round: int = 0,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
    row: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return list of anomaly dicts ``{primary_class, confidence, evidence}``."""
    out: List[Dict[str, Any]] = []
    r = _lower(reason)
    tc = _s(target_class)
    wc = _s(way_class)
    row = row if isinstance(row, Mapping) else {}

    if way_changed and tc in ACHIEVE_TARGET_CLASSES and not hard_board_evidence:
        # hard board evidence = block/race/kill/offway on way side
        if wc not in (
            "target_blocked",
            "race_settle",
            "race_road",
            "way_kill",
            "offway_opportunity",
            "specials_shock",
            "hard_invalid",
        ):
            out.append(
                {
                    "primary_class": "anomaly_way_change_on_achieve",
                    "confidence": "high",
                    "evidence": [
                        f"way_class={wc or 'n/a'}",
                        f"target_class={tc}",
                    ],
                }
            )

    if way_changed and is_q2_reason(r):
        out.append(
            {
                "primary_class": "anomaly_q2_way_change",
                "confidence": "high",
                "evidence": [f"reason={r[:80]}"],
            }
        )

    if way_changed and is_hand_only_reason(r) and not is_q2_reason(r):
        # q2 already covered; hand-only is softer
        if wc in ("", "unknown", "soft_eta_switch") or not wc:
            out.append(
                {
                    "primary_class": "anomaly_way_change_hand_only",
                    "confidence": "medium",
                    "evidence": [f"reason={r[:80]}", f"way_class={wc or 'n/a'}"],
                }
            )

    if target_changes_this_round >= thrash_threshold:
        # thrash only if not mostly achieve/block
        out.append(
            {
                "primary_class": "anomaly_target_thrash",
                "confidence": "medium",
                "evidence": [f"target_changes_this_round={target_changes_this_round}"],
            }
        )

    # Writer achieve_kind with way_changed
    if way_changed and _lower(row.get("achieve_kind") or "") in (
        "settle",
        "settlement",
        "city",
        "component",
        "s",
        "c",
    ):
        if not any(a["primary_class"] == "anomaly_way_change_on_achieve" for a in out):
            if wc not in (
                "target_blocked",
                "race_settle",
                "race_road",
                "way_kill",
                "offway_opportunity",
            ):
                out.append(
                    {
                        "primary_class": "anomaly_way_change_on_achieve",
                        "confidence": "medium",
                        "evidence": [
                            f"achieve_kind={row.get('achieve_kind')}",
                            f"way_class={wc or 'n/a'}",
                        ],
                    }
                )

    return out


def hard_board_evidence_from_classes(
    way_class: Optional[str] = None,
    way_tags: Optional[Sequence[str]] = None,
) -> bool:
    codes = set(way_tags or [])
    if way_class:
        codes.add(way_class)
    return bool(
        codes
        & {
            "target_blocked",
            "race_settle",
            "race_road",
            "way_kill",
            "offway_opportunity",
            "specials_shock",
            "hard_invalid",
        }
    )


# ── Engine invalidate → suggested writer codes (for C1) ──────────────────────


def suggest_way_switch_cause_from_invalidate(
    invalidate_reason: str,
    *,
    is_first_lock: bool = False,
    q1_offway: bool = False,
    way_kill: bool = False,
) -> str:
    """Best-effort writer-side code when sticky apply changes way."""
    if is_first_lock:
        return "first_lock"
    if way_kill:
        return "way_kill"
    if q1_offway:
        return "offway_opportunity"
    mapped = _map_invalidate(_lower(invalidate_reason), _INVALIDATE_TO_WAY)
    if mapped and mapped != "unknown":
        return mapped
    if not invalidate_reason:
        return "soft_eta_switch"
    return "unknown"


def suggest_target_switch_cause_from_invalidate(
    invalidate_reason: str,
    *,
    is_first_lock: bool = False,
    achieve_kind: str = "",
    way_changed: bool = False,
    q1_offway: bool = False,
) -> str:
    if is_first_lock:
        return "first_lock"
    ak = _lower(achieve_kind)
    if ak in ("settle", "settlement", "s"):
        return "achieve_settle"
    if ak in ("city", "c"):
        return "achieve_city"
    if ak in ("component", "roads", "knight"):
        return "achieve_component"
    if q1_offway:
        return "offway_opportunity"
    mapped = _map_invalidate(_lower(invalidate_reason), _INVALIDATE_TO_TARGET)
    if mapped:
        if mapped == "same_way_rerank" and way_changed:
            return "way_switch_cascade"
        return mapped
    if way_changed:
        return "way_switch_cascade"
    inv = _lower(invalidate_reason)
    if "own_rec_settle" in inv:
        return "achieve_settle"
    if "own_rec_city" in inv:
        return "achieve_city"
    return "unknown"


__all__ = [
    "SETBACK_THRESHOLD_DEFAULT",
    "TARGET_THRASH_PER_ROUND_DEFAULT",
    "WAY_CHANGE_CLASSES",
    "WAY_CHANGE_PRIORITY",
    "TARGET_CHANGE_CLASSES",
    "TARGET_CHANGE_PRIORITY",
    "ACHIEVE_TARGET_CLASSES",
    "SETBACK_CLASSES",
    "SETBACK_PRIORITY",
    "ANOMALY_CLASSES",
    "roads_fingerprint",
    "normalize_way_cause",
    "normalize_target_cause",
    "normalize_setback_class",
    "is_hand_only_reason",
    "is_q2_reason",
    "is_setback",
    "classify_way_change",
    "classify_target_change",
    "classify_setback",
    "detect_anomalies",
    "hard_board_evidence_from_classes",
    "suggest_way_switch_cause_from_invalidate",
    "suggest_target_switch_cause_from_invalidate",
]
