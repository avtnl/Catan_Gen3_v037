"""P3 stub: multi-turn DCard *play order* (unwired; does not execute).

Operator body (`docs/placeholders.txt` / `docs/P3_optimizers_spec.md`):

  If the player holds several DCards, plan own turns to play them. Examples:
    a) 2×Knight + TFR and way needs LA+LR → at least 3 turns; if time allows,
       play Knights first, then chase LR (LA easier to defend than LR).
    b) Monopoly → usually wait for end-game + lots of the resource in play +
       favourable port TwB; if other DCards are held, postpone Monopoly.

This-turn legal pick/hold stays in ``core.ai_play_dcard_choice``.
This module is the **sequence planner** that may later soft-bias the chooser.

WIRING_TODO (near future):
  When ``plan_play_sequence`` head is legal this window, optionally nudge
  ``plan_ai_dcard_choice`` toward that card (soft). Dig ACT may show the
  planned order. Grow heuristics during dig testing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

WIRING_STATUS = "stub_unwired"
WIRING_TODO = (
    "Soft-bias ai_play_dcard_choice when sequence head is legal; Dig ACT "
    "may show planned order (docs/P3_optimizers_spec.md)."
)

# Stable card keys aligned with ai_play_dcard_choice.CARD_ORDER
CARD_KNIGHT = "knight"
CARD_TFR = "two_free_roads"
CARD_YOP = "year_of_plenty"
CARD_MONOPOLY = "monopoly"
CARD_VP = "victory_point"  # never "played" as an action


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _hand_dcard_counts(player: Any) -> Dict[str, int]:
    """Best-effort counts from common player shapes (no peek beyond own seat)."""
    counts = {
        CARD_KNIGHT: 0,
        CARD_TFR: 0,
        CARD_YOP: 0,
        CARD_MONOPOLY: 0,
        CARD_VP: 0,
    }
    if player is None:
        return counts
    # Mapping hand
    hand = getattr(player, "development_cards", None) or getattr(player, "dcards", None)
    if isinstance(hand, Mapping):
        for k, v in hand.items():
            key = str(k).strip().lower().replace(" ", "_")
            if "knight" in key:
                counts[CARD_KNIGHT] += _safe_int(v)
            elif "two" in key or "road" in key or key in ("tfr", "road_building"):
                counts[CARD_TFR] += _safe_int(v)
            elif "plenty" in key or key == "yop":
                counts[CARD_YOP] += _safe_int(v)
            elif "mono" in key:
                counts[CARD_MONOPOLY] += _safe_int(v)
            elif "vp" in key or "victory" in key:
                counts[CARD_VP] += _safe_int(v)
        return counts
    # List of card names / objects
    if isinstance(hand, (list, tuple)):
        for item in hand:
            name = str(getattr(item, "type", None) or getattr(item, "name", None) or item).lower()
            if "knight" in name:
                counts[CARD_KNIGHT] += 1
            elif "road" in name or "tfr" in name:
                counts[CARD_TFR] += 1
            elif "plenty" in name or "yop" in name:
                counts[CARD_YOP] += 1
            elif "mono" in name:
                counts[CARD_MONOPOLY] += 1
            elif "vp" in name or "victory" in name:
                counts[CARD_VP] += 1
    return counts


def _way_wants_la_lr(player: Any) -> Tuple[bool, bool]:
    want_la = want_lr = False
    try:
        from core.strategy_sticky import get_sticky_commitment

        c = get_sticky_commitment(player)
        tags = []
        if isinstance(c, Mapping):
            tags = list(c.get("way_tags") or c.get("tags") or [])
            summary = c.get("strategy_summary") if isinstance(c.get("strategy_summary"), Mapping) else {}
            want_la = bool(summary.get("largest_army") or c.get("largest_army"))
            want_lr = bool(summary.get("longest_road") or c.get("longest_road"))
        text = " ".join(str(t).lower() for t in tags)
        if "largest" in text and "army" in text:
            want_la = True
        if "longest" in text and "road" in text:
            want_lr = True
    except Exception:
        pass
    return want_la, want_lr


def plan_play_sequence(
    game: Any,
    player: Any,
) -> Dict[str, Any]:
    """Return a multi-turn DCard play order (no execution).

    Stub heuristic (minimal, documented):
      - If way wants LA+LR and hand has Knights + TFR → Knights first, then TFR.
      - Monopoly always after other playable DCards in the plan.
      - VP cards never scheduled as plays.
    """
    counts = _hand_dcard_counts(player)
    want_la, want_lr = _way_wants_la_lr(player)
    sequence: List[str] = []
    reasons: List[str] = []

    n_k = int(counts.get(CARD_KNIGHT) or 0)
    n_tfr = int(counts.get(CARD_TFR) or 0)
    n_yop = int(counts.get(CARD_YOP) or 0)
    n_mono = int(counts.get(CARD_MONOPOLY) or 0)

    if want_la and want_lr and n_k and n_tfr:
        for _ in range(n_k):
            sequence.append(CARD_KNIGHT)
        reasons.append("la_lr: knights_before_tfr")
        for _ in range(n_tfr):
            sequence.append(CARD_TFR)
        reasons.append("la_lr: tfr_after_knights")
    else:
        for _ in range(n_k):
            sequence.append(CARD_KNIGHT)
        for _ in range(n_tfr):
            sequence.append(CARD_TFR)
        if n_k or n_tfr:
            reasons.append("stub_default_knight_then_tfr")

    for _ in range(n_yop):
        sequence.append(CARD_YOP)
    if n_yop:
        reasons.append("yop_mid_plan_unscored")

    for _ in range(n_mono):
        sequence.append(CARD_MONOPOLY)
    if n_mono:
        reasons.append("monopoly_last_hold_for_endgame_twb")

    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "counts": dict(counts),
        "want_la": want_la,
        "want_lr": want_lr,
        "sequence": sequence,
        "min_turns": len(sequence),
        "reasons": reasons,
        "head": sequence[0] if sequence else None,
        "note": "stub sequence only; chooser still owns this-turn play",
    }


def next_preferred_play(
    game: Any,
    player: Any,
) -> Optional[str]:
    """Head of ``plan_play_sequence`` or None."""
    bag = plan_play_sequence(game, player)
    head = bag.get("head")
    return str(head) if head else None


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "CARD_KNIGHT",
    "CARD_TFR",
    "CARD_YOP",
    "CARD_MONOPOLY",
    "CARD_VP",
    "plan_play_sequence",
    "next_preferred_play",
]
