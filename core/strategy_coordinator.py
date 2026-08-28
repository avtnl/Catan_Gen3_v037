"""SE façade for road / RCard / DCard helpers (ex ``strategy_card_coordinator``).

Role:
  Coordinate when Strategy-Engine should consult:
    - ``road_optimizer``
    - ``rcard_optimizer`` (TwB+TwP + DCard touchpoints)
    - ``dcard_optimizer`` (multi-turn play order)
  and record offense vs defense *stance* for end-game trade-offs.

Keep this module thin. LR this-turn claimability (TFR / trades) lives on
``road_optimizer.assess_lr_claimable_this_turn`` (may call RCard/DCard itself).

First wiring (LR priority):
  ``post_lr_settle_tips`` — what SE would chase next once LR is achieved
  (PLN2 / plan_catalog settle shortlist). ``road_optimizer`` uses this to
  prefer dual-purpose roads among LR-successful options.

Future SE policy bag (not implemented): from current path_length, potential
path_length, and roads_to_build — decide combine_lr_settle / race_mode /
maximize_length / block_player_id and pass into ``road_optimizer`` without
putting that politics inside board geometry scoring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

WIRING_STATUS = "partial_lr_road"
WIRING_TODO = (
    "Wire advise() into SE/Continue pre-step + Dig ACT stance line; "
    "TwP restriction overrides need an explicit product flag "
    "(docs/P3_optimizers_spec.md)."
)

# Alias kept for docs / searches that still say card_to_strategy_optimizer
LEGACY_NAME = "card_to_strategy_optimizer"
LEGACY_MODULE = "strategy_card_coordinator"

_MAX_TIPS = 5


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def post_lr_settle_tips(
    game: Any,
    player: Any,
    *,
    max_tips: int = _MAX_TIPS,
) -> Dict[str, Any]:
    """Ordered settle (and city) tips SE considers after / alongside LR.

    Sources (first hit wins per id, order preserved):
      1. Sticky SE pick if settle
      2. ``last_plan_bag`` / ``last_plan_snapshot`` catalog S rows
      3. ``plan_catalog`` / ``plan_settles`` string attrs on player
      4. Sticky commitment target id
    """
    tips: List[Dict[str, Any]] = []
    seen: set = set()
    se_pick: Optional[str] = None

    def _add(tid: Any, *, kind: str = "S", dist: Any = None, source: str = "") -> None:
        i = _safe_int(tid)
        if i is None or i in seen:
            return
        seen.add(i)
        tips.append(
            {
                "id": i,
                "kind": str(kind or "S").upper(),
                "label": f"{str(kind or 'S').upper()}{i}",
                "dist": _safe_int(dist),
                "source": source,
            }
        )

    bag: Any = None
    try:
        bag = getattr(player, "last_plan_bag", None)
        if not isinstance(bag, Mapping):
            bag = getattr(game, "last_plan_snapshot", None)
    except Exception:
        bag = None

    if isinstance(bag, Mapping):
        se_pick = str(bag.get("se_pick") or bag.get("plan_se_pick") or "").strip() or None
        if se_pick and se_pick[0].upper() == "S":
            _add(se_pick[1:], kind="S", source="se_pick")
        catalog = bag.get("catalog") or bag.get("plan_catalog_rows")
        if isinstance(catalog, Sequence) and not isinstance(catalog, (str, bytes)):
            for row in catalog:
                if not isinstance(row, Mapping):
                    continue
                kind = str(row.get("kind") or "S").upper()
                if kind != "S":
                    continue
                _add(row.get("id"), kind="S", dist=row.get("dist"), source="plan_bag")
        elif bag.get("plan_catalog"):
            try:
                from core.strategy_plan_snapshot import parse_plan_catalog

                for row in parse_plan_catalog(bag.get("plan_catalog")):
                    if str(row.get("kind") or "").upper() != "S":
                        continue
                    _add(row.get("id"), kind="S", dist=row.get("dist"), source="plan_catalog")
            except Exception:
                pass

    # Player/game string fields (CS-shaped)
    for attr_owner in (player, game):
        if attr_owner is None:
            continue
        raw_cat = getattr(attr_owner, "plan_catalog", None)
        if raw_cat and len(tips) < max_tips:
            try:
                from core.strategy_plan_snapshot import parse_plan_catalog

                for row in parse_plan_catalog(raw_cat):
                    if str(row.get("kind") or "").upper() != "S":
                        continue
                    _add(row.get("id"), kind="S", dist=row.get("dist"), source="attr_catalog")
            except Exception:
                pass
        raw_se = getattr(attr_owner, "plan_se_pick", None)
        if raw_se and not se_pick:
            se_pick = str(raw_se).strip() or None
            if se_pick and se_pick[0].upper() == "S":
                _add(se_pick[1:], kind="S", source="attr_se_pick")

    # Sticky commitment / direction
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player) if player is not None else None
    except Exception:
        c = getattr(player, "sticky_commitment", None) if player is not None else None
    if isinstance(c, Mapping):
        kind = str(c.get("locked_target_kind") or c.get("target_kind") or "S").upper()
        tid = c.get("locked_rec_target_id") or c.get("locked_target_id") or c.get("target_id")
        if kind in ("S", "SETTLE", "SETTLEMENT", ""):
            _add(tid, kind="S", source="sticky")

    tips = tips[: max(1, int(max_tips or _MAX_TIPS))]
    return {
        "ok": True,
        "tips": tips,
        "se_pick": se_pick,
        "top_id": tips[0]["id"] if tips else None,
        "note": "post-LR settle shortlist for road_optimizer",
    }


def advise(
    game: Any,
    player: Any,
    *,
    targets: Optional[List[Mapping[str, Any]]] = None,
    consult_road: bool = False,
    lr_candidates: Optional[Sequence[Any]] = None,
    sticky_path: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Return coordination bag.

    When ``consult_road`` is True (LR priority), call ``road_optimizer`` with
    post-LR settle tips. Does not mutate state.
    """
    tips_bag = post_lr_settle_tips(game, player)
    road_bag: Dict[str, Any] = {"skipped": True, "reason": "no_paths_passed"}
    try:
        from core.road_optimizer import WIRING_STATUS as road_ws
        from core.road_optimizer import rank_lr_priority_roads

        if consult_road:
            road_bag = rank_lr_priority_roads(
                game,
                player,
                lr_candidates=list(lr_candidates or []),
                settle_tips=tips_bag.get("tips") or [],
                sticky_path=sticky_path,
            )
            road_bag["tips"] = tips_bag
        else:
            road_bag = {
                "module": "road_optimizer",
                "wiring_status": road_ws,
                "consult": False,
                "tips": tips_bag,
                "note": "pass consult_road=True + lr_candidates when LR priority",
            }
    except Exception as exc:  # pragma: no cover
        road_bag = {"ok": False, "error": str(exc)}

    rcard_bag: Dict[str, Any] = {}
    try:
        from core.rcard_optimizer import optimize_rcard_actions

        rcard_bag = optimize_rcard_actions(game, player, targets=targets)
    except Exception as exc:  # pragma: no cover
        rcard_bag = {"ok": False, "error": str(exc)}

    dcard_bag: Dict[str, Any] = {}
    try:
        from core.dcard_optimizer import plan_play_sequence

        dcard_bag = plan_play_sequence(game, player)
    except Exception as exc:  # pragma: no cover
        dcard_bag = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "wired": bool(consult_road and road_bag.get("wired")),
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "legacy_name": LEGACY_NAME,
        "legacy_module": LEGACY_MODULE,
        "stance": "unset",
        "stance_reasons": [
            "stub: offense vs defense fine-tuned later",
            "example: monopoly+2:1 Wh wait for 6/8; optional defensive TwP to strip leader LR",
        ],
        "consult": {
            "road_optimizer": bool(consult_road),
            "rcard_optimizer": False,
            "dcard_optimizer": bool((dcard_bag or {}).get("sequence")),
        },
        "post_lr_tips": tips_bag,
        "road": road_bag,
        "rcard": rcard_bag,
        "dcard": dcard_bag,
        "want_more_l2": False,
        "want_more_l2_note": "stub: trigger extra L2 when strategy stale — not implemented",
        "note": "façade; LR-priority road consult when consult_road=True",
    }


def card_to_strategy_optimize(game: Any, player: Any, **kwargs: Any) -> Dict[str, Any]:
    """Deprecated alias → ``advise``."""
    return advise(game, player, **kwargs)


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "LEGACY_NAME",
    "LEGACY_MODULE",
    "post_lr_settle_tips",
    "advise",
    "card_to_strategy_optimize",
]
