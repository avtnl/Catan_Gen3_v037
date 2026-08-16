"""
Core package for the Catan game.

Exports Board, Player, Game, InitialPlacement. Imports are **lazy** so lab tools
(e.g. Phase C CS probe under ``core.batch``) can import without pulling pygame
via ``core.game``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Board", "Player", "Game", "InitialPlacement"]


def __getattr__(name: str) -> Any:
    if name == "Board":
        from .board import Board

        return Board
    if name == "Player":
        from .player import Player

        return Player
    if name == "Game":
        from .game import Game

        return Game
    if name == "InitialPlacement":
        from .initial_placement_phase_manager import InitialPlacement

        return InitialPlacement
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
