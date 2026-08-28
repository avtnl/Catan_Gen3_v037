"""Victory-Way resource need façade (Player One–style RCard accounting).

Single place for:
  - remaining structure counts (S / C / R / DC) from CSV + board progress
  - component → RCard vector via ``strategy_cost_from_components``
  - optional playboard min-road cover (Proposal A) + TFR road credit
  - optional ``consider_hand`` (self = truth; opponent = RCARD_MEMORY belief)

EH search stays in ``resource_time_estimator`` / ``strategy_timing``. Callers must
not double-subtract hand (use ``need_vector`` + hand in EH, **or**
``need_after_hand`` + empty hand).

See ``docs/way_resource_need_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RESOURCE_ORDER: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")

# Player One / 142-way table historically budgets ~2 empty roads per expand.
# Proposal A: whole-way residual uses min-road cover; per-target EH uses raw d
# via settlement_Nr. This constant is informational (Dig / meta), not Proposal B algebra.
CSV_ASSUMED_ROADS_PER_EXPAND: int = 2


@dataclass(frozen=True)
class WayComponents:
    way_id: int
    new_settlements: int = 0
    city_upgrades: int = 0
    roads: int = 0
    dev_cards: int = 0
    longest_road: bool = False
    largest_army: bool = False
    victory_point_cards: int = 0
    cities_abs: int = 0
    settlements_abs: int = 0
    roads_abs: int = 0


@dataclass(frozen=True)
class WayNeedResult:
    way_id: int
    components: WayComponents
    need_vector: Tuple[float, float, float, float, float]
    need_after_hand: Tuple[float, float, float, float, float]
    hand_vector: Optional[Tuple[float, float, float, float, float]]
    hand_source: str
    consider_hand: bool
    road_basis: str
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def req_settles(self) -> int:
        return int(self.components.new_settlements)

    @property
    def req_cities(self) -> int:
        return int(self.components.city_upgrades)

    @property
    def req_roads(self) -> int:
        return int(self.components.roads)

    @property
    def req_dcards(self) -> int:
        return int(self.components.dev_cards)


def _tuple5(values: Sequence[Any]) -> Tuple[float, float, float, float, float]:
    out: List[float] = []
    for i in range(5):
        try:
            out.append(float(values[i]) if i < len(values) else 0.0)
        except Exception:
            out.append(0.0)
    return (out[0], out[1], out[2], out[3], out[4])


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_way_id(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        w = int(float(value))
        return w if w > 0 else None
    except Exception:
        return None


def _player_id(player: Any) -> Optional[int]:
    try:
        pid = int(getattr(player, "id", 0) or 0)
        return pid if pid > 0 else None
    except Exception:
        return None


def load_way_components(way_id: Any) -> Optional[WayComponents]:
    """Absolute CSV components for one way (definition, not residual)."""
    wid = _safe_way_id(way_id)
    if wid is None:
        return None
    try:
        from core.strategy_way_residual import load_way_requirement

        strategy = load_way_requirement(wid)
    except Exception:
        strategy = None
    if strategy is None:
        return None
    return WayComponents(
        way_id=int(wid),
        new_settlements=max(0, _safe_int(getattr(strategy, "new_settlements_to_build", 0), 0)),
        city_upgrades=max(0, _safe_int(getattr(strategy, "city_upgrades", 0), 0)),
        roads=max(0, _safe_int(getattr(strategy, "roads_to_build", 0), 0)),
        dev_cards=max(0, _safe_int(getattr(strategy, "development_cards_to_buy", 0), 0)),
        longest_road=bool(getattr(strategy, "longest_road", False)),
        largest_army=bool(
            getattr(strategy, "biggest_army", False)
            or getattr(strategy, "largest_army", False)
        ),
        victory_point_cards=max(0, _safe_int(getattr(strategy, "victory_point_cards", 0), 0)),
        cities_abs=max(0, _safe_int(getattr(strategy, "cities", 0), 0)),
        settlements_abs=max(0, _safe_int(getattr(strategy, "settlements", 0), 0)),
        roads_abs=max(0, _safe_int(getattr(strategy, "roads_to_build", 0), 0)),
    )


def need_vector_from_components(
    components: WayComponents,
) -> Tuple[float, float, float, float, float]:
    """Player One–style RCard vector from remaining structure counts."""
    from core.strategy_timing import strategy_cost_from_components

    return _tuple5(
        strategy_cost_from_components(
            new_settlements=int(components.new_settlements),
            city_upgrades=int(components.city_upgrades),
            roads=int(components.roads),
            dev_cards=int(components.dev_cards),
        )
    )


def clamp_settle_path_distance(path_distance: Any) -> int:
    """Empty-road path length to a new settle (0 = already on network).

    Catalog/legal expands are typically d∈{2,3}; d=1 is illegal under the Catan
    distance rule relative to existing buildings, but we still accept any d≥0
    so callers can pass measured BFS distances unchanged.
    """
    try:
        d = int(float(path_distance))
    except Exception:
        d = 0
    return max(0, d)


def next_settle_target_type(path_distance: Any) -> str:
    """RTE / EH target name aligned with ``settlement_Nr`` / ``extra_roads_needed``."""
    d = clamp_settle_path_distance(path_distance)
    return f"settlement_{d}r"


def next_settle_path_components(
    path_distance: Any,
    *,
    way_id: int = 0,
) -> WayComponents:
    """One expand at path distance d → 1 settlement + d roads (Proposal A per-target)."""
    d = clamp_settle_path_distance(path_distance)
    return WayComponents(
        way_id=int(way_id or 0),
        new_settlements=1,
        city_upgrades=0,
        roads=int(d),
        dev_cards=0,
    )


def next_settle_path_need_vector(
    path_distance: Any,
) -> Tuple[float, float, float, float, float]:
    """RCard need for one settle at distance d — same as EH ``settlement_Nr``."""
    d = clamp_settle_path_distance(path_distance)
    try:
        from core.resource_time_estimator import target_cost_vector

        return _tuple5(target_cost_vector("settlement", extra_roads_needed=d))
    except Exception:
        return need_vector_from_components(next_settle_path_components(d))


def path_vs_csv_extra_roads(
    path_distance: Any,
    *,
    assumed_per_expand: int = CSV_ASSUMED_ROADS_PER_EXPAND,
) -> int:
    """How many road packages d exceeds the CSV ~2-road expand assumption (info only)."""
    d = clamp_settle_path_distance(path_distance)
    assume = max(0, int(assumed_per_expand))
    return max(0, d - assume)


def describe_next_settle_path(path_distance: Any, *, way_id: int = 0) -> Dict[str, Any]:
    """Dig/EH helper bag for one next-settle path under Proposal A."""
    d = clamp_settle_path_distance(path_distance)
    comps = next_settle_path_components(d, way_id=way_id)
    need = next_settle_path_need_vector(d)
    return {
        "path_distance": d,
        "target_type": next_settle_target_type(d),
        "roads": d,
        "components": comps,
        "need_vector": need,
        "csv_assumed_roads_per_expand": int(CSV_ASSUMED_ROADS_PER_EXPAND),
        "path_vs_csv_extra_roads": path_vs_csv_extra_roads(d),
        "policy": "proposal_a_per_target_settlement_Nr",
        "note": (
            "Whole-way residual roads stay on min_road_cover; "
            "use this vector for single-target EH (settlement_Nr)."
        ),
    }


def _truth_hand5(player: Any) -> Tuple[float, float, float, float, float]:
    rc = getattr(player, "rcards", None) or {}
    if isinstance(rc, Mapping) and rc:
        return _tuple5([rc.get(n, 0) for n in RESOURCE_ORDER])
    try:
        from core.resource_time_estimator import get_player_resource_cards_vector

        return _tuple5(get_player_resource_cards_vector(player))
    except Exception:
        pass
    return (0.0, 0.0, 0.0, 0.0, 0.0)


def resolve_hand_vector(
    game: Any,
    subject: Any,
    *,
    viewer: Any = None,
    consider_hand: bool = False,
    rounds: Any = None,
) -> Tuple[Optional[Tuple[float, float, float, float, float]], str, Dict[str, Any]]:
    """Return ``(hand5, source, meta)``.

    - ``consider_hand=False`` → ``(None, \"none\", {})``
    - Self (viewer is subject / omitted) → truth ``Player.rcards``
    - Opponent → ``opponent_belief_hand5`` under ``RCARD_MEMORY_OPPONENTS``
      (``rounds`` overrides the constant when provided)
    """
    meta: Dict[str, Any] = {}
    if not consider_hand:
        return None, "none", meta
    view = viewer if viewer is not None else subject
    vid = _player_id(view)
    sid = _player_id(subject)
    if vid is None or sid is None:
        hand = _truth_hand5(subject)
        meta["viewer_id"] = vid
        meta["subject_id"] = sid
        return hand, "truth", meta
    if vid == sid:
        return _truth_hand5(subject), "truth", {"viewer_id": vid, "subject_id": sid}
    try:
        from core.rcard_view_memory import opponent_belief_hand5

        hand, bel_meta = opponent_belief_hand5(game, view, subject, rounds=rounds)
        bel_meta = dict(bel_meta or {})
        meta.update(bel_meta)
        meta["viewer_id"] = vid
        meta["subject_id"] = sid
        src = str(bel_meta.get("source") or "memory_miss")
        if hand is None:
            # memory=all → truth for opponent (same policy as beat-risk)
            return _truth_hand5(subject), "truth", meta
        return _tuple5(hand), src, meta
    except Exception as exc:
        meta["belief_error"] = str(exc)
        return _truth_hand5(subject), "truth", meta


def _subtract_hand(
    need: Tuple[float, float, float, float, float],
    hand: Optional[Tuple[float, float, float, float, float]],
) -> Tuple[float, float, float, float, float]:
    if hand is None:
        return need
    return _tuple5([max(0.0, float(need[i]) - float(hand[i])) for i in range(5)])


def apply_tfr_road_credit(
    roads: int,
    player: Any,
    *,
    longest_road: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    """WP2: each unplayed TFR ≈ 2 free roads toward residual road mass.

    Applied when the way wants LR or there are still roads to build.
    Single source for façade and Dig residual (after preferred.remaining overrides).
    """
    meta: Dict[str, Any] = {"tfr_unplayed": 0, "tfr_credit_roads": 0}
    n_r = max(0, int(roads or 0))
    try:
        from core.strategy_way_residual import unplayed_tfr

        tfr_n = int(unplayed_tfr(player) or 0)
    except Exception:
        tfr_n = 0
    credit = 2 * max(0, tfr_n)
    meta["tfr_unplayed"] = max(0, tfr_n)
    meta["tfr_credit_roads"] = credit
    if credit and (bool(longest_road) or n_r > 0):
        n_r = max(0, n_r - credit)
    return n_r, meta


def remaining_components(
    game: Any,
    player: Any,
    way_id: Any,
    *,
    use_min_road_cover: bool = True,
    subtract_development_cards: bool = True,
    apply_tfr_credit: bool = True,
    board: Any = None,
) -> Tuple[WayComponents, str, Dict[str, Any]]:
    """Mid-game remaining S/C/R/DC counts + road_basis + meta."""
    meta: Dict[str, Any] = {}
    abs_comp = load_way_components(way_id)
    wid = _safe_way_id(way_id) or (abs_comp.way_id if abs_comp else 0)
    if abs_comp is None:
        empty = WayComponents(way_id=int(wid or 0))
        return empty, "none", {"error": "way_not_found"}

    road_basis = "csv_minus_count"
    try:
        from core.strategy_timing import (
            PlayerStrategyState,
            build_player_strategy_state,
            calculate_remaining_need,
        )
        from core.strategy_way_residual import (
            dcard_ever_count,
            load_way_requirement,
            settlement_city_counts,
        )

        strategy = load_way_requirement(wid)
        if strategy is None:
            return abs_comp, road_basis, {"error": "strategy_missing"}

        board_obj = board
        if board_obj is None and game is not None:
            board_obj = getattr(game, "board", None)
        if board_obj is not None:
            pstate = build_player_strategy_state(board_obj, player)
        else:
            n_s, n_c = settlement_city_counts(player)
            city_ids: List[int] = []
            try:
                city_ids = [int(x) for x in list(getattr(player, "cities", []) or [])]
            except Exception:
                pass
            settle_ids: List[int] = []
            try:
                settle_ids = [
                    int(x)
                    for x in list(getattr(player, "settlements", []) or [])
                    if int(x) not in set(city_ids)
                ]
            except Exception:
                settle_ids = []
            pstate = PlayerStrategyState(
                player_id=_safe_int(getattr(player, "id", 0), 0),
                color=str(getattr(player, "color", "") or ""),
                current_hand=(0.0, 0.0, 0.0, 0.0, 0.0),
                production_pips=(0.0, 0.0, 0.0, 0.0, 0.0),
                trade_rates=(4, 4, 4, 4, 4),
                ports=tuple(),
                settlements=tuple(settle_ids),
                cities=tuple(city_ids),
                roads_count=len(list(getattr(player, "roads", []) or [])),
                dev_card_progress=dcard_ever_count(player),
            )
            meta["n_s"], meta["n_c"] = n_s, n_c

        rem = calculate_remaining_need(
            strategy,
            pstate,
            subtract_current_roads=True,
            subtract_development_cards=bool(subtract_development_cards),
        )
        n_s = int(rem.remaining_new_settlements)
        n_c = int(rem.remaining_city_upgrades)
        n_r = int(rem.remaining_roads_to_build)
        n_dc = int(rem.remaining_dev_cards_to_buy)
        meta["progress"] = dict(getattr(rem, "progress", {}) or {})
        meta["warnings"] = list(getattr(rem, "warnings", ()) or [])
    except Exception as exc:
        meta["error"] = f"remaining_failed:{exc}"
        return abs_comp, road_basis, meta

    # Proposal A / WP2: playboard min empty-road cover for remaining settles
    meta["roads_before_min_cover"] = int(n_r)
    if use_min_road_cover and player is not None and n_s > 0:
        game_for_cover = game
        if game_for_cover is None and board_obj is not None:
            game_for_cover = type("G", (), {"board": board_obj, "players": [player]})()
        if game_for_cover is not None:
            try:
                from core.strategy_min_road_cover import victory_structure_road_need

                cover = victory_structure_road_need(
                    game_for_cover,
                    player,
                    remaining_new_settlements=int(n_s),
                    remaining_city_upgrades=int(n_c),
                )
                if cover.get("ok") or int(cover.get("roads_needed") or 0) >= 0:
                    n_r = int(cover.get("roads_needed") or 0)
                    road_basis = "min_road_cover"
                    meta["min_road_cover"] = {
                        "roads_needed": n_r,
                        "sites": list(cover.get("sites") or [])[:8],
                        "ok": bool(cover.get("ok")),
                        "unreachable": int(cover.get("unreachable") or 0),
                    }
            except Exception as exc:
                meta["min_road_cover_error"] = str(exc)

    if apply_tfr_credit:
        n_r, tfr_meta = apply_tfr_road_credit(
            n_r, player, longest_road=bool(abs_comp.longest_road)
        )
        meta.update(tfr_meta)

    comps = WayComponents(
        way_id=int(wid),
        new_settlements=max(0, n_s),
        city_upgrades=max(0, n_c),
        roads=max(0, n_r),
        dev_cards=max(0, n_dc),
        longest_road=bool(abs_comp.longest_road),
        largest_army=bool(abs_comp.largest_army),
        victory_point_cards=int(abs_comp.victory_point_cards),
        cities_abs=int(abs_comp.cities_abs),
        settlements_abs=int(abs_comp.settlements_abs),
        roads_abs=int(abs_comp.roads_abs),
    )
    return comps, road_basis, meta


def way_resource_need(
    game: Any,
    player: Any,
    way_id: Any,
    *,
    consider_hand: Optional[bool] = None,
    viewer: Any = None,
    use_min_road_cover: bool = True,
    subtract_development_cards: bool = True,
    apply_tfr_credit: bool = True,
    path_distance_for_next_settle: Optional[int] = None,
    board: Any = None,
    memory_rounds: Any = None,
) -> WayNeedResult:
    """Compose remaining way need; optional hand subtraction (self truth / opp belief).

    ``consider_hand`` defaults to ``WAY_NEED_CONSIDER_HAND_DEFAULT`` when None.
    ``memory_rounds`` overrides ``RCARD_MEMORY_OPPONENTS`` for opponent belief.
    ``path_distance_for_next_settle`` (WP4 / Proposal A): does **not** rewrite
    whole-way ``req_roads`` (still min-road cover); attaches ``meta["next_settle"]``
    with ``settlement_Nr`` need aligned to EH ``target_cost_vector``.
    """
    if consider_hand is None:
        try:
            from core.constants import WAY_NEED_CONSIDER_HAND_DEFAULT

            consider_hand = bool(WAY_NEED_CONSIDER_HAND_DEFAULT)
        except Exception:
            consider_hand = False
    consider_hand = bool(consider_hand)

    comps, road_basis, meta = remaining_components(
        game,
        player,
        way_id,
        use_min_road_cover=use_min_road_cover,
        subtract_development_cards=subtract_development_cards,
        apply_tfr_credit=apply_tfr_credit,
        board=board,
    )

    # WP-R4: if caller omitted path distance, resolve from sticky tip via maps
    path_distance_source = "caller"
    if path_distance_for_next_settle is None and player is not None:
        try:
            from core.constants import REACHABILITY_MAPS
            from core.player_reachability import (
                SENTINEL,
                ensure_reachability_maps,
                maps_are_fresh,
                remaining_roads_to_target,
            )

            sticky = getattr(player, "sticky_commitment", None) or {}
            if not isinstance(sticky, Mapping):
                sticky = {}
            tip = sticky.get("locked_rec_target_id")
            tip_i = None
            try:
                tip_i = int(tip) if tip is not None and tip != "" else None
            except Exception:
                tip_i = None
            if tip_i is not None and bool(REACHABILITY_MAPS):
                g = game
                if g is None and board is not None:
                    g = type("G", (), {"board": board, "players": [player]})()
                if g is not None:
                    ensure_reachability_maps(g, player)
                if maps_are_fresh(player):
                    rd = remaining_roads_to_target(player, tip_i)
                    if rd is not None and 0 <= int(rd) < SENTINEL:
                        path_distance_for_next_settle = int(rd)
                        path_distance_source = "reachability_map_sticky"
                        meta["next_settle_target_id"] = int(tip_i)
        except Exception:
            pass

    if path_distance_for_next_settle is not None:
        d = clamp_settle_path_distance(path_distance_for_next_settle)
        meta["path_distance_for_next_settle"] = d
        meta["path_distance_source"] = path_distance_source
        meta["distance_policy"] = "proposal_a_min_cover_whole_way"
        next_bag = describe_next_settle_path(d, way_id=int(comps.way_id))
        # Keep components serializable in meta
        next_bag = dict(next_bag)
        next_bag["components"] = {
            "new_settlements": next_bag["components"].new_settlements,
            "roads": next_bag["components"].roads,
        }
        meta["next_settle"] = next_bag

    need = need_vector_from_components(comps)
    hand, hand_source, hand_meta = resolve_hand_vector(
        game,
        player,
        viewer=viewer,
        consider_hand=consider_hand,
        rounds=memory_rounds,
    )
    if hand_meta:
        meta["hand"] = hand_meta
    after = _subtract_hand(need, hand) if consider_hand else need
    return WayNeedResult(
        way_id=int(comps.way_id),
        components=comps,
        need_vector=need,
        need_after_hand=after,
        hand_vector=hand,
        hand_source=hand_source,
        consider_hand=consider_hand,
        road_basis=road_basis,
        meta=meta,
    )


__all__ = [
    "CSV_ASSUMED_ROADS_PER_EXPAND",
    "WayComponents",
    "WayNeedResult",
    "apply_tfr_road_credit",
    "clamp_settle_path_distance",
    "describe_next_settle_path",
    "load_way_components",
    "need_vector_from_components",
    "next_settle_path_components",
    "next_settle_path_need_vector",
    "next_settle_target_type",
    "path_vs_csv_extra_roads",
    "remaining_components",
    "resolve_hand_vector",
    "way_resource_need",
    "RESOURCE_ORDER",
]
