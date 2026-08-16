"""Batch / headless lab infrastructure (Phase A+).

Presentation stubs and runners live here so interactive ``main.py`` / ``gui/``
stay the product path while multi-game lab code reuses core APIs only.

Imports are **lazy** so offline tools (Phase C CS probe) can use
``core.batch.cs_setback_analyzer`` without pulling pygame / Game via
``headless_runner``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "NullGui",
    "is_gui_presentation_enabled",
    "HeadlessGameRunner",
    "run_one_headless_game",
    "GameManager",
    "run_batch",
    "build_batch_summary",
    "write_batch_summary",
    "BATCH_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "STATUS_WON",
    "STATUS_MAX_ROUND",
    "STATUS_STUCK",
    "STATUS_ERROR",
    "build_result",
    "write_result",
    "build_and_write_result",
]


def __getattr__(name: str) -> Any:
    if name in ("NullGui", "is_gui_presentation_enabled"):
        from core.batch import null_gui as m

        return getattr(m, name)
    if name in ("HeadlessGameRunner", "run_one_headless_game"):
        from core.batch import headless_runner as m

        return getattr(m, name)
    if name in (
        "GameManager",
        "run_batch",
        "build_batch_summary",
        "write_batch_summary",
        "BATCH_SCHEMA_VERSION",
    ):
        from core.batch import game_manager as m

        return getattr(m, name)
    if name in (
        "RESULT_SCHEMA_VERSION",
        "STATUS_WON",
        "STATUS_MAX_ROUND",
        "STATUS_STUCK",
        "STATUS_ERROR",
        "build_result",
        "write_result",
        "build_and_write_result",
    ):
        from core.batch import result as m

        return getattr(m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
