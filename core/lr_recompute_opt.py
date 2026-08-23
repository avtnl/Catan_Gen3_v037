"""WP6: optional Longest Road recompute scoping (correctness-first).

Branch switch ``LR_RECOMPUTE_OPT``:

- ``full`` (default) — always recompute every seat's continuous length (legacy).
- ``threshold`` — skip opponent DFS when the mutation cannot change their graphs:

  * **Settlement** (new barrier): always **full** (WP6.2).
  * **Road / TFR free road**: only the **actor** graph gains an edge →
    recompute actor only; reuse cached lengths for others; still run award.
  * **City** (own upgrade): barriers for opponents unchanged → **cache_only**
    (refresh award from cached lengths; no DFS).

Equivalence note: opponent continuous length depends only on their edges +
foreign barriers. An actor road never adds barriers or opponent edges.
A new settlement at a node can split every opponent path through that node.

See docs/SE_improvement_plan_from_dig_observations.md WP6 / B-LR-RECOMPUTE.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def get_lr_recompute_opt_mode() -> str:
    try:
        from core import constants as C

        mode = str(getattr(C, "LR_RECOMPUTE_OPT", "full") or "full").lower().strip()
    except Exception:
        mode = "full"
    if mode in ("threshold", "opt", "actor", "scoped"):
        return "threshold"
    if mode in ("off", "0", "false", "none"):
        return "full"
    return "full"


def classify_lr_recompute_scope(
    game: Any,
    *,
    reason: str = "",
    actor: Any = None,
    force_full: bool = False,
) -> Dict[str, Any]:
    """Decide recompute scope for one ``recompute_longest_road`` call.

    Returns
    -------
    dict
        ``scope``: ``full`` | ``actor_only`` | ``cache_only``
        ``why``: short reason code
        ``mode``: configured opt mode
        ``actor_id``: optional int
    """
    mode = get_lr_recompute_opt_mode()
    out: Dict[str, Any] = {
        "scope": "full",
        "why": "default_full",
        "mode": mode,
        "actor_id": None,
    }
    try:
        if actor is not None:
            out["actor_id"] = int(getattr(actor, "id", 0) or 0) or None
    except Exception:
        out["actor_id"] = None

    if force_full:
        out["why"] = "force_full"
        return out
    if mode != "threshold":
        out["why"] = "opt_full"
        return out

    reason_l = str(reason or "").lower()

    # WP6.2 — settlements break chains for opponents
    if any(
        k in reason_l
        for k in (
            "settlement",
            "settle",
            "break",
            "barrier",
            "load",
            "init",
            "import",
            "special_award",
            "force",
        )
    ):
        out["scope"] = "full"
        out["why"] = "settlement_or_load_or_force"
        return out

    # City: own building upgrade — no new foreign barrier
    if "city" in reason_l:
        out["scope"] = "cache_only"
        out["why"] = "city_no_barrier_change"
        return out

    # Road / TFR / free road — actor graph only
    roadish = any(
        k in reason_l
        for k in (
            "road",
            "tfr",
            "free_road",
            "two_free",
        )
    )
    if roadish:
        if actor is None and out["actor_id"] is None:
            out["scope"] = "full"
            out["why"] = "road_without_actor"
            return out
        out["scope"] = "actor_only"
        out["why"] = "road_actor_only"
        return out

    # Unknown reason under threshold → full (safe)
    out["scope"] = "full"
    out["why"] = "unknown_reason_safe_full"
    return out


def actor_from_reason_players(game: Any, reason: str, actor: Any = None) -> Any:
    """Prefer explicit actor; else None (caller should pass actor)."""
    if actor is not None:
        return actor
    return None


__all__ = [
    "get_lr_recompute_opt_mode",
    "classify_lr_recompute_scope",
    "actor_from_reason_players",
]
