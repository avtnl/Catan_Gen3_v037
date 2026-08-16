"""Phase L L4: players_view public features + ambition labels (no SE mutation).

L4-1: public-only feature vectors for LA/LR race analysis.
L4-2: rule-based ambition ``none``/``L``/``M``/``H`` + public_chase (M/H).
L4-3: offline analyzer builds on this module.

Spec freeze: ``docs/PhaseL_L4_players_view_plan.md`` §0
(``L4_PLAYERS_VIEW_SPEC_v0``).

Public features must not depend on hands, DCard types, sticky way_id, or
god-view ``needs_*`` / hopeless scores as *inputs*.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

# ---------------------------------------------------------------------------
# L4-0 frozen metadata + ambition constants (used by L4-2; stored here once)
# ---------------------------------------------------------------------------

PLAYERS_VIEW_SCHEMA_VERSION: int = 1
SPEC_FREEZE_ID: str = "L4_PLAYERS_VIEW_SPEC_v0"

LA_CLAIM_BAR: int = 3
LR_LENGTH_BAR: int = 5
LA_H_GAP_MAX: int = 1
LA_M_ARMY_MIN: int = 2
LA_M_GAP_MAX: int = 2
LA_L_ARMY_MIN: int = 1
LA_L_GAP_MAX: int = 2
LA_L_THREATS_MIN: int = 2
LA_DELTA_OPP_ARMY_MIN: int = 2
LR_H_GAP_MAX: int = 1
LR_M_PATH_MIN: int = 4
LR_M_GAP_MAX: int = 2
LR_L_PATH_MIN: int = 3
LR_L_GAP_MAX: int = 3
LR_L_CAP_MIN: int = 2
LR_DELTA_OPP_PATH_MIN: int = 4
SERIES_DELTA_K: int = 3
PUBLIC_CHASE_LABELS: Tuple[str, ...] = ("M", "H")
AMBITION_LABELS: Tuple[str, ...] = ("none", "L", "M", "H")

try:
    from core.la_lr_probe_log import MAX_ROADS_CAP as _PROBE_MAX_ROADS
    from core.la_lr_probe_log import PROBE_NON_SAMPLE_EVENTS as _PROBE_NON_SAMPLE
except Exception:  # pragma: no cover
    _PROBE_MAX_ROADS = 15
    _PROBE_NON_SAMPLE = frozenset(
        {"la_giveup_fire", "lr_giveup_fire", "salvage_adopt"}
    )

MAX_ROADS_CAP: int = int(_PROBE_MAX_ROADS)
EXCLUDE_PROBE_EVENTS = frozenset(_PROBE_NON_SAMPLE)

# Keys that must never appear as *inputs* to public builders (teachers only offline)
FORBIDDEN_PUBLIC_INPUT_KEYS: frozenset = frozenset(
    {
        "way_id",
        "way_ids",
        "needs",
        "needs_la",
        "needs_lr",
        "needs_reason",
        "hopeless_score",
        "hopeless_score_la",
        "hopeless_score_lr",
        "should_give_up",
        "knight_new",
        "knight_playable",
        "knight_revealed",
        "dcard_summary",
        "hand",
        "resources",
        "la_progress",
        "lr_project",
        "lr_project_residual_roads",
        "la_progress_keys",
        "sticky_eta",
        "strategic_direction",
        "sticky_commitment",
    }
)

# Canonical public feature fields (ambition v0 required + context)
PUBLIC_FEATURE_KEYS: Tuple[str, ...] = (
    "schema",
    "spec_freeze_id",
    "source",
    "player_id",
    "round",
    "turn",
    "game_key",
    "event",
    "army",
    "path",
    "roads",
    "roads_remaining_cap",
    "holds_la",
    "holds_lr",
    "gap_la",
    "gap_lr",
    "n_threats_la",
    "n_threats_lr",
    "army_leader",
    "path_leader",
    "legal_roads",
    "delta_army",
    "delta_path",
    "delta_active",
    "n_settlements",
    "n_cities",
    "vp_public",
)


def ambition_constants_v0() -> Dict[str, Any]:
    """Snapshot of frozen constants for reports / digs."""
    return {
        "spec_freeze_id": SPEC_FREEZE_ID,
        "schema": PLAYERS_VIEW_SCHEMA_VERSION,
        "LA_CLAIM_BAR": LA_CLAIM_BAR,
        "LR_LENGTH_BAR": LR_LENGTH_BAR,
        "LA_H_GAP_MAX": LA_H_GAP_MAX,
        "LA_M_ARMY_MIN": LA_M_ARMY_MIN,
        "LA_M_GAP_MAX": LA_M_GAP_MAX,
        "LA_L_ARMY_MIN": LA_L_ARMY_MIN,
        "LA_L_GAP_MAX": LA_L_GAP_MAX,
        "LA_L_THREATS_MIN": LA_L_THREATS_MIN,
        "LA_DELTA_OPP_ARMY_MIN": LA_DELTA_OPP_ARMY_MIN,
        "LR_H_GAP_MAX": LR_H_GAP_MAX,
        "LR_M_PATH_MIN": LR_M_PATH_MIN,
        "LR_M_GAP_MAX": LR_M_GAP_MAX,
        "LR_L_PATH_MIN": LR_L_PATH_MIN,
        "LR_L_GAP_MAX": LR_L_GAP_MAX,
        "LR_L_CAP_MIN": LR_L_CAP_MIN,
        "LR_DELTA_OPP_PATH_MIN": LR_DELTA_OPP_PATH_MIN,
        "SERIES_DELTA_K": SERIES_DELTA_K,
        "PUBLIC_CHASE_LABELS": list(PUBLIC_CHASE_LABELS),
        "MAX_ROADS_CAP": MAX_ROADS_CAP,
    }


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_int0(value: Any, default: int = 0) -> int:
    v = _safe_int(value, None)
    return default if v is None else int(v)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def is_probe_sample_row(row: Mapping[str, Any]) -> bool:
    """True if row should enter L4 offline series (excludes fire/salvage dig events)."""
    ev = str(row.get("event") or "sample")
    return ev not in EXCLUDE_PROBE_EVENTS


def contains_forbidden_public_input(payload: Mapping[str, Any]) -> List[str]:
    """Return forbidden keys present at top level of *payload* (for tests / digs)."""
    hit: List[str] = []
    for k in payload.keys():
        if str(k) in FORBIDDEN_PUBLIC_INPUT_KEYS:
            hit.append(str(k))
    return sorted(hit)


def _game_key_from_row(row: Mapping[str, Any]) -> str:
    seq = _safe_int(row.get("sequence_number"), None)
    if seq is not None:
        return f"seq:{seq}"
    gid = str(row.get("game_id") or "").strip()
    if gid:
        return f"gid:{gid}"
    return "game:?"


def _block(row: Mapping[str, Any], name: str) -> Dict[str, Any]:
    raw = row.get(name)
    return dict(raw) if isinstance(raw, Mapping) else {}


def _focal_from_seats(
    seats: Sequence[Mapping[str, Any]],
    focal_id: Optional[int],
) -> Dict[str, Any]:
    if focal_id is None:
        return {}
    for s in seats:
        if not isinstance(s, Mapping):
            continue
        if _safe_int(s.get("player_id"), None) == int(focal_id):
            return dict(s)
    return {}


def _race_from_seats(
    seats: Sequence[Mapping[str, Any]],
    focal_id: Optional[int],
) -> Dict[str, Any]:
    """Mirror L1 ``_race_features`` so offline rows without race block still work."""
    try:
        from core.la_lr_probe_log import _race_features

        return dict(_race_features(list(seats), focal_id))
    except Exception:
        pass
    own = _focal_from_seats(seats, focal_id)
    own_army = _safe_int0(own.get("army"), 0)
    own_path = _safe_int0(own.get("path"), 0)
    opp_armies = [
        _safe_int0(s.get("army"), 0)
        for s in seats
        if isinstance(s, Mapping) and _safe_int(s.get("player_id"), None) != focal_id
    ]
    opp_paths = [
        _safe_int0(s.get("path"), 0)
        for s in seats
        if isinstance(s, Mapping) and _safe_int(s.get("player_id"), None) != focal_id
    ]
    army_leader = max(opp_armies) if opp_armies else 0
    path_leader = max(opp_paths) if opp_paths else 0
    return {
        "army_leader": army_leader,
        "path_leader": path_leader,
        "gap_la": max(0, army_leader - own_army),
        "gap_lr": max(0, path_leader - own_path),
        "n_threats_la": sum(1 for a in opp_armies if a >= max(0, own_army - 1)),
        "n_threats_lr": sum(1 for p in opp_paths if p >= max(0, own_path - 1)),
    }


def _empty_public_features(*, source: str = "empty") -> Dict[str, Any]:
    return {
        "schema": PLAYERS_VIEW_SCHEMA_VERSION,
        "spec_freeze_id": SPEC_FREEZE_ID,
        "source": source,
        "player_id": None,
        "round": None,
        "turn": None,
        "game_key": None,
        "event": None,
        "army": 0,
        "path": 0,
        "roads": 0,
        "roads_remaining_cap": MAX_ROADS_CAP,
        "holds_la": False,
        "holds_lr": False,
        "gap_la": 0,
        "gap_lr": 0,
        "n_threats_la": 0,
        "n_threats_lr": 0,
        "army_leader": 0,
        "path_leader": 0,
        "legal_roads": None,
        "delta_army": 0,
        "delta_path": 0,
        "delta_active": False,
        "n_settlements": None,
        "n_cities": None,
        "vp_public": None,
    }


def build_public_features_from_probe_row(
    row: Optional[Mapping[str, Any]],
    *,
    delta_army: Optional[int] = None,
    delta_path: Optional[int] = None,
    delta_active: Optional[bool] = None,
    legal_roads: Optional[int] = None,
) -> Dict[str, Any]:
    """Build public feature vector from one ``la_lr_probe`` JSONL row.

    Uses only public race fields on the row (``seats``, ``la``/``lr`` army/path/gap/
    threats/holds/cap). Does **not** copy ``needs``, ``way_id``, knight hand splits,
    or hopeless scores into the feature dict.
    """
    out = _empty_public_features(source="probe_row")
    if not isinstance(row, Mapping) or not row:
        return out

    la = _block(row, "la")
    lr = _block(row, "lr")
    seats_raw = row.get("seats")
    seats: List[Mapping[str, Any]] = (
        [s for s in seats_raw if isinstance(s, Mapping)]
        if isinstance(seats_raw, (list, tuple))
        else []
    )
    focal_id = _safe_int(row.get("player_id"), None)
    seat_own = _focal_from_seats(seats, focal_id)
    race = _race_from_seats(seats, focal_id)

    army = _safe_int0(la.get("army"), _safe_int0(seat_own.get("army"), 0))
    path = _safe_int0(lr.get("path"), _safe_int0(seat_own.get("path"), 0))
    roads = _safe_int0(lr.get("roads"), _safe_int0(seat_own.get("roads"), 0))
    cap = lr.get("roads_remaining_cap")
    if cap is None:
        cap = seat_own.get("roads_remaining_cap")
    if cap is None:
        cap = max(0, MAX_ROADS_CAP - roads)
    else:
        cap = max(0, _safe_int0(cap, MAX_ROADS_CAP))

    gap_la = la.get("gap")
    if gap_la is None:
        gap_la = race.get("gap_la")
    gap_lr = lr.get("gap")
    if gap_lr is None:
        gap_lr = race.get("gap_lr")

    n_threats_la = la.get("n_threats")
    if n_threats_la is None:
        n_threats_la = race.get("n_threats_la")
    n_threats_lr = lr.get("n_threats")
    if n_threats_lr is None:
        n_threats_lr = race.get("n_threats_lr")

    army_leader = la.get("army_leader")
    if army_leader is None:
        army_leader = race.get("army_leader")
    path_leader = lr.get("path_leader")
    if path_leader is None:
        path_leader = race.get("path_leader")

    holds_la = la.get("holds")
    if holds_la is None:
        holds_la = seat_own.get("holds_la")
    holds_lr = lr.get("holds")
    if holds_lr is None:
        holds_lr = seat_own.get("holds_lr")

    # Optional legal_roads: row-level override, then kwarg, else None (Q-F3)
    lr_legal = legal_roads
    if lr_legal is None and "legal_roads" in row:
        lr_legal = _safe_int(row.get("legal_roads"), None)
    if lr_legal is None and "legal_roads" in lr:
        lr_legal = _safe_int(lr.get("legal_roads"), None)

    d_army = 0 if delta_army is None else int(delta_army)
    d_path = 0 if delta_path is None else int(delta_path)
    d_act = bool(delta_active) if delta_active is not None else (
        delta_army is not None or delta_path is not None
    )

    out.update(
        {
            "player_id": focal_id,
            "round": _safe_int(row.get("round"), None),
            "turn": _safe_int(row.get("turn"), None),
            "game_key": _game_key_from_row(row),
            "event": str(row.get("event") or "sample"),
            "army": army,
            "path": path,
            "roads": roads,
            "roads_remaining_cap": cap,
            "holds_la": _safe_bool(holds_la, False),
            "holds_lr": _safe_bool(holds_lr, False),
            "gap_la": max(0, _safe_int0(gap_la, 0)),
            "gap_lr": max(0, _safe_int0(gap_lr, 0)),
            "n_threats_la": max(0, _safe_int0(n_threats_la, 0)),
            "n_threats_lr": max(0, _safe_int0(n_threats_lr, 0)),
            "army_leader": max(0, _safe_int0(army_leader, 0)),
            "path_leader": max(0, _safe_int0(path_leader, 0)),
            "legal_roads": lr_legal,
            "delta_army": d_army,
            "delta_path": d_path,
            "delta_active": d_act,
        }
    )

    # Context-only (not used by ambition v0 rules) if cheap public counts exist
    if "n_settlements" in row:
        out["n_settlements"] = _safe_int(row.get("n_settlements"), None)
    if "n_cities" in row:
        out["n_cities"] = _safe_int(row.get("n_cities"), None)
    if "vp_public" in row:
        out["vp_public"] = _safe_int(row.get("vp_public"), None)

    return out


def _try_legal_roads_count(game: Any, player: Any) -> Optional[int]:
    """Optional public board scan; None if unavailable (do not invent)."""
    if game is None or player is None:
        return None
    board = getattr(game, "board", None)
    if board is None:
        return None
    try:
        from core.partial_way_salvage import detect_expansion_geometry_block

        det = detect_expansion_geometry_block(game, player)
        if isinstance(det, Mapping) and det.get("n_legal_roads") is not None:
            return max(0, _safe_int0(det.get("n_legal_roads"), 0))
    except Exception:
        pass
    try:
        # Fallback scanner name used in some paths
        from core.viable_action_scanner import legal_road_edges  # type: ignore

        edges = legal_road_edges(board, player)
        return len(list(edges or []))
    except Exception:
        return None


def build_public_features_from_game(
    game: Any,
    player: Any,
    *,
    delta_army: Optional[int] = None,
    delta_path: Optional[int] = None,
    delta_active: Optional[bool] = None,
    legal_roads: Optional[int] = None,
    include_legal_roads_scan: bool = True,
) -> Dict[str, Any]:
    """Build public features from live ``game`` + ``player`` (no private needs/way).

    Reuses L1 seat snapshot + race helpers. Does not call needs resolvers or
    S5.5 assess.
    """
    out = _empty_public_features(source="game")
    if player is None and game is None:
        return out

    seats: List[Dict[str, Any]] = []
    race: Dict[str, Any] = {}
    focal_id = _safe_int(getattr(player, "id", None), None) if player is not None else None
    try:
        from core.la_lr_probe_log import _race_features, _seat_public_snapshot

        seats = list(_seat_public_snapshot(game) or [])
        race = dict(_race_features(seats, focal_id))
    except Exception:
        seats = []
        race = {}

    seat_own = _focal_from_seats(seats, focal_id)
    army = _safe_int0(seat_own.get("army"), 0)
    path = _safe_int0(seat_own.get("path"), 0)
    roads = _safe_int0(seat_own.get("roads"), 0)
    cap = seat_own.get("roads_remaining_cap")
    if cap is None:
        cap = max(0, MAX_ROADS_CAP - roads)
    else:
        cap = max(0, _safe_int0(cap, MAX_ROADS_CAP))

    lr_legal = legal_roads
    if lr_legal is None and include_legal_roads_scan:
        lr_legal = _try_legal_roads_count(game, player)

    d_army = 0 if delta_army is None else int(delta_army)
    d_path = 0 if delta_path is None else int(delta_path)
    d_act = bool(delta_active) if delta_active is not None else (
        delta_army is not None or delta_path is not None
    )

    out.update(
        {
            "player_id": focal_id,
            "round": _safe_int(getattr(game, "round", None), None) if game else None,
            "turn": _safe_int(getattr(game, "turn", None), None) if game else None,
            "game_key": (
                f"seq:{_safe_int(getattr(game, 'sequence_number', None), None)}"
                if game is not None
                and _safe_int(getattr(game, "sequence_number", None), None) is not None
                else (
                    f"gid:{getattr(game, 'id', '')}"
                    if game is not None and getattr(game, "id", None)
                    else None
                )
            ),
            "event": "live",
            "army": army,
            "path": path,
            "roads": roads,
            "roads_remaining_cap": cap,
            "holds_la": _safe_bool(seat_own.get("holds_la"), False),
            "holds_lr": _safe_bool(seat_own.get("holds_lr"), False),
            "gap_la": max(0, _safe_int0(race.get("gap_la"), 0)),
            "gap_lr": max(0, _safe_int0(race.get("gap_lr"), 0)),
            "n_threats_la": max(0, _safe_int0(race.get("n_threats_la"), 0)),
            "n_threats_lr": max(0, _safe_int0(race.get("n_threats_lr"), 0)),
            "army_leader": max(0, _safe_int0(race.get("army_leader"), 0)),
            "path_leader": max(0, _safe_int0(race.get("path_leader"), 0)),
            "legal_roads": lr_legal,
            "delta_army": d_army,
            "delta_path": d_path,
            "delta_active": d_act,
        }
    )

    # Optional structure counts (public) — never hands
    if player is not None:
        try:
            out["n_settlements"] = len(list(getattr(player, "settlements", None) or []))
        except Exception:
            pass
        try:
            out["n_cities"] = len(list(getattr(player, "cities", None) or []))
        except Exception:
            pass

    return out


def build_public_features(
    source: Union[Mapping[str, Any], None] = None,
    /,
    *,
    game: Any = None,
    player: Any = None,
    delta_army: Optional[int] = None,
    delta_path: Optional[int] = None,
    delta_active: Optional[bool] = None,
    legal_roads: Optional[int] = None,
) -> Dict[str, Any]:
    """Dispatcher: probe row mapping **or** live ``game``+``player``.

    Prefer ``build_public_features_from_probe_row`` / ``_from_game`` explicitly
    in new code; this helper is for call sites that branch.
    """
    if isinstance(source, Mapping):
        return build_public_features_from_probe_row(
            source,
            delta_army=delta_army,
            delta_path=delta_path,
            delta_active=delta_active,
            legal_roads=legal_roads,
        )
    if game is not None or player is not None:
        return build_public_features_from_game(
            game,
            player,
            delta_army=delta_army,
            delta_path=delta_path,
            delta_active=delta_active,
            legal_roads=legal_roads,
        )
    return _empty_public_features(source="empty")


def apply_series_deltas(
    features: Mapping[str, Any],
    *,
    prior_army: Optional[int] = None,
    prior_path: Optional[int] = None,
    series_len: int = 0,
) -> Dict[str, Any]:
    """Return a copy with Δ fields from a prior sample (analyzer helper for L4-2/3).

    ``delta_active`` is True when ``series_len >= 2`` and at least one prior
    metric was provided (L4-0: need ≥2 points; K lookback handled by caller).
    """
    out = dict(features)
    active = int(series_len) >= 2 and (
        prior_army is not None or prior_path is not None
    )
    out["delta_active"] = active
    if not active:
        out["delta_army"] = 0
        out["delta_path"] = 0
        return out
    cur_a = _safe_int0(out.get("army"), 0)
    cur_p = _safe_int0(out.get("path"), 0)
    if prior_army is not None:
        out["delta_army"] = cur_a - int(prior_army)
    else:
        out["delta_army"] = 0
    if prior_path is not None:
        out["delta_path"] = cur_p - int(prior_path)
    else:
        out["delta_path"] = 0
    return out


def assert_public_features_clean(features: Mapping[str, Any]) -> None:
    """Raise ``AssertionError`` if forbidden teacher keys leaked into features."""
    bad = list(contains_forbidden_public_input(features))
    # Reject probe-row shells if someone copied the whole sample
    for nest in ("la", "lr", "seats", "way_id", "way_ids", "s55_latched", "needs"):
        if nest in features:
            bad.append(nest)
    if bad:
        raise AssertionError(
            f"public features contain forbidden keys: {sorted(set(bad))}"
        )


# ---------------------------------------------------------------------------
# L4-2: ambition labels (first matching rule wins; constants §0.3)
# ---------------------------------------------------------------------------


def _feat_int(features: Mapping[str, Any], key: str, default: int = 0) -> int:
    return max(0, _safe_int0(features.get(key), default))


def _feat_bool(features: Mapping[str, Any], key: str, default: bool = False) -> bool:
    return _safe_bool(features.get(key), default)


def label_ambition_la(features: Mapping[str, Any]) -> str:
    """Public LA ambition: ``none`` | ``L`` | ``M`` | ``H`` (L4-0 rules §5.1)."""
    if not isinstance(features, Mapping):
        return "none"
    a = _feat_int(features, "army", 0)
    gap = _feat_int(features, "gap_la", 0)
    threats = _feat_int(features, "n_threats_la", 0)
    a_opp = _feat_int(features, "army_leader", 0)
    holds = _feat_bool(features, "holds_la", False)
    delta_active = _feat_bool(features, "delta_active", False)
    # signed delta: growth only counts when active
    try:
        d_army = int(features.get("delta_army") or 0)
    except Exception:
        d_army = 0

    if holds and a >= LA_CLAIM_BAR:
        return "H"
    if a >= LA_CLAIM_BAR and gap <= LA_H_GAP_MAX:
        return "H"
    if a >= LA_M_ARMY_MIN and gap <= LA_M_GAP_MAX:
        return "M"
    if a >= LA_L_ARMY_MIN and (gap <= LA_L_GAP_MAX or threats >= LA_L_THREATS_MIN):
        return "L"
    if delta_active and d_army > 0 and a_opp >= LA_DELTA_OPP_ARMY_MIN:
        return "L"
    return "none"


def label_ambition_lr(features: Mapping[str, Any]) -> str:
    """Public LR ambition: ``none`` | ``L`` | ``M`` | ``H`` (L4-0 rules §5.2)."""
    if not isinstance(features, Mapping):
        return "none"
    p = _feat_int(features, "path", 0)
    gap = _feat_int(features, "gap_lr", 0)
    p_opp = _feat_int(features, "path_leader", 0)
    cap = _feat_int(features, "roads_remaining_cap", MAX_ROADS_CAP)
    holds = _feat_bool(features, "holds_lr", False)
    delta_active = _feat_bool(features, "delta_active", False)
    try:
        d_path = int(features.get("delta_path") or 0)
    except Exception:
        d_path = 0
    legal = features.get("legal_roads")
    legal_n = _safe_int(legal, None)

    if holds and p >= LR_LENGTH_BAR:
        return "H"
    if p >= LR_LENGTH_BAR and gap <= LR_H_GAP_MAX:
        return "H"
    if p >= LR_M_PATH_MIN and gap <= LR_M_GAP_MAX:
        return "M"
    if (
        p >= LR_L_PATH_MIN
        and gap <= LR_L_GAP_MAX
        and cap >= LR_L_CAP_MIN
    ):
        return "L"
    if delta_active and d_path > 0 and p_opp >= LR_DELTA_OPP_PATH_MIN:
        return "L"
    # Q-F3: only when legal_roads is known (not None)
    if legal_n is not None and legal_n == 0 and p < LR_LENGTH_BAR:
        return "none"
    return "none"


def is_public_chase(ambition: Any) -> bool:
    """True when ambition is M or H (L4-0 Q-F5; primary agreement binary)."""
    return str(ambition or "") in PUBLIC_CHASE_LABELS


def public_chase_la(features: Mapping[str, Any]) -> bool:
    return is_public_chase(label_ambition_la(features))


def public_chase_lr(features: Mapping[str, Any]) -> bool:
    return is_public_chase(label_ambition_lr(features))


def label_ambitions(features: Mapping[str, Any]) -> Dict[str, Any]:
    """Both specials + chase flags for one public feature vector."""
    amb_la = label_ambition_la(features)
    amb_lr = label_ambition_lr(features)
    return {
        "ambition_la": amb_la,
        "ambition_lr": amb_lr,
        "public_chase_la": is_public_chase(amb_la),
        "public_chase_lr": is_public_chase(amb_lr),
        "spec_freeze_id": SPEC_FREEZE_ID,
        "schema": PLAYERS_VIEW_SCHEMA_VERSION,
    }


def annotate_public_features_with_ambition(
    features: Mapping[str, Any],
) -> Dict[str, Any]:
    """Copy of features plus ambition / chase fields (does not mutate input)."""
    out = dict(features)
    labels = label_ambitions(features)
    out.update(labels)
    return out


__all__ = [
    "AMBITION_LABELS",
    "EXCLUDE_PROBE_EVENTS",
    "FORBIDDEN_PUBLIC_INPUT_KEYS",
    "LA_CLAIM_BAR",
    "LA_DELTA_OPP_ARMY_MIN",
    "LA_H_GAP_MAX",
    "LA_L_ARMY_MIN",
    "LA_L_GAP_MAX",
    "LA_L_THREATS_MIN",
    "LA_M_ARMY_MIN",
    "LA_M_GAP_MAX",
    "LR_DELTA_OPP_PATH_MIN",
    "LR_H_GAP_MAX",
    "LR_L_CAP_MIN",
    "LR_L_GAP_MAX",
    "LR_L_PATH_MIN",
    "LR_LENGTH_BAR",
    "LR_M_GAP_MAX",
    "LR_M_PATH_MIN",
    "MAX_ROADS_CAP",
    "PLAYERS_VIEW_SCHEMA_VERSION",
    "PUBLIC_CHASE_LABELS",
    "PUBLIC_FEATURE_KEYS",
    "SERIES_DELTA_K",
    "SPEC_FREEZE_ID",
    "ambition_constants_v0",
    "annotate_public_features_with_ambition",
    "apply_series_deltas",
    "assert_public_features_clean",
    "build_public_features",
    "build_public_features_from_game",
    "build_public_features_from_probe_row",
    "contains_forbidden_public_input",
    "is_probe_sample_row",
    "is_public_chase",
    "label_ambition_la",
    "label_ambition_lr",
    "label_ambitions",
    "public_chase_la",
    "public_chase_lr",
]
