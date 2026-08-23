"""Null presentation object for headless / no-window runs.

Used when ``NO_GUI_AT_ALL_TF`` is True (or when a caller attaches this as
``game.gui``). Core rules must keep running; draw, sound, screenshots, and
button chrome no-op safely.

This is not a full GUI stand-in for interactive play — only a crash shield so
IP / Execution core paths can call ``game.gui.*`` without a display surface.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def is_gui_presentation_enabled(
    game: Any = None,
    gui: Any = None,
) -> bool:
    """Return False when draw/sound/screenshot/button chrome should be skipped.

    Order of checks:
      1. ``NO_GUI_AT_ALL_TF`` (operator-owned)
      2. missing ``gui``
      3. ``NullGui`` / ``is_null_gui`` marker
    """
    try:
        from core.console import is_no_gui

        if is_no_gui():
            return False
    except Exception:
        try:
            from core.constants import NO_GUI_AT_ALL_TF

            if bool(NO_GUI_AT_ALL_TF):
                return False
        except Exception:
            pass

    g = gui
    if g is None and game is not None:
        g = getattr(game, "gui", None)
    if g is None:
        return False
    if bool(getattr(g, "is_null_gui", False)):
        return False
    if isinstance(g, NullGui):
        return False
    return True


class _NullHumanGuidance:
    """Minimal human-guidance stub so IP ``handle_click`` is safe."""

    def __init__(self) -> None:
        self.confirm_center = None
        try:
            from gui.gui_guidance import PlacementState

            self.state = PlacementState.IDLE
        except Exception:
            self.state = "IDLE"

    def start_settlement_phase(self, player: Any = None) -> None:
        return None

    def start_road_phase(self, player: Any = None) -> None:
        return None

    def on_board_click(self, pos: Any = None) -> bool:
        return False

    def draw(self) -> None:
        return None


class NullGui:
    """No-op GUI attached to ``game.gui`` during headless runs."""

    is_null_gui: bool = True

    def __init__(
        self,
        round_number: int = 0,
        turn: int = 0,
        game: Any = None,
    ) -> None:
        self.game = game
        self.round_number = int(round_number or 0)
        self.turn = int(turn or 0)
        self.buttons: Dict[str, bool] = {}
        self.twitter: list = []
        self.events_debug_revealed: bool = False
        self.ip_started_via_play: bool = True
        self.human_guidance = _NullHumanGuidance()
        # Animation queues some core/gui paths may clear
        self.animate_queue_elements: list = []
        self.animate_queue_intersections: list = []
        self.animate_queue_roads: list = []
        self.animate_queue_tiles: list = []

    # --- button registry (logic may query; never draw) ---

    def set_button(self, name: str, display_tf: bool = False) -> None:
        self.buttons[str(name)] = bool(display_tf)

    def check_button(self, name: str) -> bool:
        return bool(self.buttons.get(str(name), False))

    # --- board / chrome updates ---

    def update_round_turn(self, game: Any = None, special: bool = False) -> None:
        if game is not None:
            try:
                self.round_number = int(getattr(game, "round", self.round_number) or 0)
                self.turn = int(getattr(game, "turn", self.turn) or 0)
            except Exception:
                pass
        return None

    def update_board(self, board: Any = None, update_type: str = "") -> None:
        return None

    def update_scoreboard(self, game: Any = None) -> None:
        return None

    def display_fresh_board(self, board: Any = None, scoreboard_tf: bool = True) -> None:
        return None

    def draw_board_base(self, board: Any = None) -> None:
        return None

    def draw_all_permanent_buildings(self, board: Any = None) -> None:
        return None

    def draw_robber_from_board(self, board: Any = None) -> None:
        return None

    def draw_execution_debug_panel(self, game: Any = None) -> None:
        return None

    def show_dices(self, dice: Any = None) -> None:
        return None

    def play_dice_roll_sound(self) -> None:
        return None

    def play_robber_sound(self) -> None:
        return None

    def play_sound(self, name: str = "", fallback: str = "BUTTON") -> bool:
        """Always silent — headless NullGui never plays audio."""
        return False

    def save_screenshot(
        self,
        filename: str = "",
        *,
        name_prefix: str = "Catan_Screenshot",
    ) -> str:
        return ""

    # --- events feed ---

    def add_tweet(
        self,
        player_id: Any = None,
        message: str = "",
        update: bool = True,
    ) -> None:
        try:
            self.twitter.append(
                {"player_id": player_id, "message": str(message or "")}
            )
        except Exception:
            pass

    def update_twitter(self) -> None:
        return None

    def add_twitter(self, player_id: Any = None, message: str = "") -> None:
        self.add_tweet(player_id, message, update=False)

    def reveal_events_and_debug(self) -> None:
        self.events_debug_revealed = True

    # --- animation / session helpers ---

    def stop_all_animations(self, redraw_board: bool = False) -> None:
        for attr in (
            "animate_queue_elements",
            "animate_queue_intersections",
            "animate_queue_roads",
            "animate_queue_tiles",
        ):
            q = getattr(self, attr, None)
            if isinstance(q, list):
                q.clear()

    def resume_animations(self) -> None:
        return None

    def clear_gui(self) -> None:
        self.buttons.clear()
        self.twitter.clear()

    def on_play_or_seat_change(self, game: Any = None) -> None:
        return None

    def close_turn_detail_panel(self, restore_modal: bool = True) -> None:
        return None

    def __repr__(self) -> str:
        return f"NullGui(round={self.round_number}, turn={self.turn})"
