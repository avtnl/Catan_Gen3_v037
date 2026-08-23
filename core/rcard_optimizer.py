"""P3 stub: resource (RCard) trade/spend ladder toward targets (unwired).

Operator body (`docs/placeholders.txt` / `docs/P3_optimizers_spec.md`):

  2.1 TwB **and TwP** that help the player hit target(s) sooner.
  2.2 Playing DCards (touch ``dcard_optimizer``):
        a) Knight — steal supports winning a race; only when steal odds
           for the needed type look substantial (knowledge stub later).
        b) YOP — race win or unlock action(s) that yield ≥1 new VP.
        c) Monopoly — same bar as YOP.
  2.3 Combinations of 2.1 + 2.2 (e.g. Monopoly scarce type → TwB into need).

Name note: **RCard** = resource cards. DCard play sequencing lives in
``dcard_optimizer``; this module only *suggests when* a play helps the
resource/target ladder.

Related live code:
  - ``core.player_trade`` / human TwP policy
  - ``core.ai_hand_risk`` (risk TwB/TwP)
  - portfolio / EH TwB for Tgt & ETA
  - ``core.ai_play_*`` + ``ai_play_dcard_choice`` for actual plays

WIRING_TODO (near future):
  Surface trade suggestions in Dig ACT; optionally bias BA TwB/TwP when
  they clearly shorten sticky Tgt. Combo Monopoly→TwB remains dig-first.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

WIRING_STATUS = "stub_unwired"
WIRING_TODO = (
    "Wire suggest_* into Dig ACT / optional BA trade ordering; keep DCard "
    "execution in dcard_optimizer + ai_play_dcard_choice "
    "(docs/P3_optimizers_spec.md)."
)


def suggest_trades_for_targets(
    game: Any,
    player: Any,
    targets: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Suggest TwB/TwP that shorten acquire-Tgt for sticky / listed targets.

    Stub: empty suggestions; documents intent only.
    """
    tgt_ids: List[Any] = []
    for t in list(targets or []):
        if isinstance(t, Mapping):
            tid = t.get("id") or t.get("target_id") or t.get("label")
            if tid is not None:
                tgt_ids.append(tid)
        else:
            tgt_ids.append(t)
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "targets": tgt_ids,
        "twb": [],
        "twp": [],
        "note": "stub: TwB+TwP ladder not scored yet",
    }


def suggest_dcard_touchpoints(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """When Knight/YOP/Monopoly would support race or ≥1 VP.

    Stub: defers to ``dcard_optimizer.plan_play_sequence`` for order;
    does not execute.
    """
    sequence: Dict[str, Any] = {}
    try:
        from core.dcard_optimizer import plan_play_sequence

        sequence = plan_play_sequence(game, player)
    except Exception as exc:  # pragma: no cover - import/runtime soft
        sequence = {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "knight": {"want": False, "reason": "stub_unscored"},
        "yop": {"want": False, "reason": "stub_unscored"},
        "monopoly": {"want": False, "reason": "stub_unscored"},
        "dcard_sequence": sequence,
        "note": "stub: race/VP bars not evaluated; see dcard_optimizer",
    }


def suggest_combo(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """Combined trade + DCard ideas (e.g. Monopoly → TwB).

    Stub only — illustrative end-game Monopoly+port pattern documented in
    ``strategy_card_coordinator``.
    """
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "combos": [],
        "note": "stub: Monopoly→TwB and similar combos not enumerated yet",
    }


def optimize_rcard_actions(
    game: Any,
    player: Any,
    *,
    targets: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Façade bag: trades + DCard touchpoints + combos (all stub)."""
    trades = suggest_trades_for_targets(game, player, targets)
    dc = suggest_dcard_touchpoints(game, player)
    combo = suggest_combo(game, player)
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "trades": trades,
        "dcard_touchpoints": dc,
        "combo": combo,
    }


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "suggest_trades_for_targets",
    "suggest_dcard_touchpoints",
    "suggest_combo",
    "optimize_rcard_actions",
]
