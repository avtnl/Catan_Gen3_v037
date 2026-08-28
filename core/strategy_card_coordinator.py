"""Shim: ``strategy_card_coordinator`` → ``strategy_coordinator``.

Prefer ``from core.strategy_coordinator import …``. This module remains for
older imports / docs that still say ``strategy_card_coordinator``.
"""

from __future__ import annotations

from core.strategy_coordinator import (  # noqa: F401
    LEGACY_MODULE,
    LEGACY_NAME,
    WIRING_STATUS,
    WIRING_TODO,
    advise,
    card_to_strategy_optimize,
    post_lr_settle_tips,
)

__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "LEGACY_NAME",
    "LEGACY_MODULE",
    "post_lr_settle_tips",
    "advise",
    "card_to_strategy_optimize",
]
