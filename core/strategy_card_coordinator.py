"""P3 stub: SE façade for road / RCard / DCard helpers (unwired).

Better name for draft ``card_to_strategy_optimizer`` in ``docs/placeholders.txt``.

Role:
  Coordinate when Strategy-Engine should consult:
    - ``road_optimizer``
    - ``rcard_optimizer`` (TwB+TwP + DCard touchpoints)
    - ``dcard_optimizer`` (multi-turn play order)
  and record offense vs defense *stance* for end-game trade-offs.

Operator illustration (defensive → later offensive):
  Player has 2:1 Wheat port + Monopoly, but opponents hold little Wheat now.
  A 6 or 8 will flood Wheat. While waiting, a **defensive** TwP (even
  violating late-game TwP restrictions) can help a non-leader take LR from
  the leader so the leader drops LR VP — buying another own turn hoping
  for 6/8, then switching **offensive** (Monopoly + port TwB).

Also notes future desire for more honest L2 when game-state / strategy is stale.

WIRING_TODO (near future):
  Call ``advise()`` from SE / Continue pre-step; Dig ACT one-liner for stance.
  Do **not** auto-violate TwP rules until a product flag exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

WIRING_STATUS = "stub_unwired"
WIRING_TODO = (
    "Wire advise() into SE/Continue pre-step + Dig ACT stance line; "
    "TwP restriction overrides need an explicit product flag "
    "(docs/P3_optimizers_spec.md)."
)

# Alias kept for docs / searches that still say card_to_strategy_optimizer
LEGACY_NAME = "card_to_strategy_optimizer"


def advise(
    game: Any,
    player: Any,
    *,
    targets: Optional[List[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return coordination bag (stance unset; sub-calls are stubs).

    Does not mutate state. Sub-optimizer results are informational only.
    """
    road_bag: Dict[str, Any] = {"skipped": True, "reason": "no_paths_passed"}
    try:
        from core.road_optimizer import WIRING_STATUS as road_ws

        road_bag = {
            "module": "road_optimizer",
            "wiring_status": road_ws,
            "consult": False,
            "note": "pass paths/candidates into rank_* when wiring",
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
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "legacy_name": LEGACY_NAME,
        # unset until end-game policy is fine-tuned
        "stance": "unset",
        "stance_reasons": [
            "stub: offense vs defense fine-tuned later",
            "example: monopoly+2:1 Wh wait for 6/8; optional defensive TwP to strip leader LR",
        ],
        "consult": {
            "road_optimizer": False,
            "rcard_optimizer": False,
            "dcard_optimizer": bool((dcard_bag or {}).get("sequence")),
        },
        "road": road_bag,
        "rcard": rcard_bag,
        "dcard": dcard_bag,
        "want_more_l2": False,
        "want_more_l2_note": "stub: trigger extra L2 when strategy stale — not implemented",
        "note": "façade only; Best-Action unchanged",
    }


# Back-compat alias name used in older notes
def card_to_strategy_optimize(game: Any, player: Any, **kwargs: Any) -> Dict[str, Any]:
    """Deprecated alias → ``advise``."""
    return advise(game, player, **kwargs)


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "LEGACY_NAME",
    "advise",
    "card_to_strategy_optimize",
]
