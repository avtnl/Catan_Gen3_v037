"""
Handles button rendering for human player interactions in the Catan game.

This module defines the GUIHumanPlayer class, responsible for rendering buttons
for human player actions (e.g., buying settlements, rolling dice) within a panel.
Buttons are conditionally displayed based on game phase, human player status, and modes.

Classes:
    GUIHumanPlayer: Manages button rendering for human player interactions.

Dependencies:
    - pygame: For rendering graphics.
    - gui.gui_constants: For fonts, colors, images, and positions.
    - core.game: For game state.
    - core.player: For player attributes.
    - core.constants: For logging and configuration constants.
"""
import pygame
from core import game
from gui.gui_constants import WIN, COLORS, Font, IMAGES
try:
    from gui.gui_constants import HUMAN_BUTTON_PANEL_RECT, HUMAN_BUTTON_RECTS, HUMAN_TWP_MODE_LABEL_POS
except Exception:  # pragma: no cover - supports older gui_constants while testing.
    HUMAN_BUTTON_PANEL_RECT = pygame.Rect(10, 265, 330, 255)
    HUMAN_TWP_MODE_LABEL_POS = (25, 224)
    HUMAN_BUTTON_RECTS = {
        "twp_mode_red": pygame.Rect(140, 215, 40, 40),
        "twp_mode_ai": pygame.Rect(190, 215, 40, 40),
        "twp_mode_auto": pygame.Rect(240, 215, 40, 40),
        "edit_twp_auto": pygame.Rect(290, 215, 40, 40),
        "buy_city": pygame.Rect(140, 275, 40, 40),
        "buy_settlement": pygame.Rect(190, 275, 40, 40),
        "buy_road": pygame.Rect(240, 275, 40, 40),
        "buy_dcard": pygame.Rect(290, 275, 40, 40),
        "twp": pygame.Rect(200, 330, 60, 40),
        "twb": pygame.Rect(270, 330, 60, 40),
        "roll_dices": pygame.Rect(200, 405, 130, 40),
        "end_turn": pygame.Rect(200, 470, 130, 40),
        "continue_ai": pygame.Rect(200, 470, 130, 40),
        "cancel": pygame.Rect(200, 470, 130, 40),
        "next_turn2": pygame.Rect(20, 470, 130, 40),
    }
from core.game import Game
from core.player import ResourceCard
from core.constants import FNFREQ, MG, FILENAME_FREQ, FILENAME_MG, HP_ID, HUMAN_PLAYER, FILENAME_SPEC2

RIGHT_ACTION_SLOT_RECT = HUMAN_BUTTON_RECTS.get("end_turn", pygame.Rect(200, 470, 130, 40))

# Option A: fixed wait copy — Execution only, under Roll Dices, static red SMALL.
BUSY_STATUS_TEXT = "AI is thinking..."


def _play_or_continue_button_active(game: Game | object) -> bool:
    """True when Play or Continue is registered active (user can click)."""
    try:
        gui = getattr(game, "gui", None)
        if gui is None or not hasattr(gui, "check_button"):
            return False
        if bool(gui.check_button("next_turn2")):
            return True
        if bool(gui.check_button("continue_ai")):
            return True
    except Exception:
        return False
    return False


def should_draw_busy_status(game: Game | object) -> bool:
    """True only in Execution while busy *and* Play/Continue are both off.

    As soon as either button is enabled, the wait cue must not show (and the
    strip is cleared by ``update_busy_status_line`` every redraw).
    """
    try:
        if str(getattr(game, "phase", "") or "") != "Execution":
            return False
    except Exception:
        return False
    try:
        if bool(getattr(game, "game_over", False)):
            return False
    except Exception:
        pass
    # Hard rule: never show wait text when the user can press Play or Continue.
    if _play_or_continue_button_active(game):
        return False
    try:
        from core.performance_trace import is_ui_input_busy

        if not bool(is_ui_input_busy(game)):
            return False
    except Exception:
        try:
            if not (
                bool(getattr(game, "ai_pipeline_busy", False))
                or bool(getattr(game, "phase0_save_busy", False))
                or bool(getattr(game, "ui_play_continue_latched", False))
            ):
                return False
        except Exception:
            return False
    return True


def busy_status_base_text(game: Game | object = None) -> str:
    """Fixed Option-A label (game arg kept for call-site compatibility)."""
    return BUSY_STATUS_TEXT


def busy_status_label(game: Game | object = None, ticks_ms: int | None = None) -> str:
    """Static label (no animated ellipsis)."""
    return BUSY_STATUS_TEXT


def busy_status_strip_rect() -> pygame.Rect:
    """Band under the Roll Dices button (right column), above Continue/End."""
    roll = HUMAN_BUTTON_RECTS.get("roll_dices", pygame.Rect(200, 405, 130, 40))
    play_right = HUMAN_BUTTON_RECTS.get("continue_ai", RIGHT_ACTION_SLOT_RECT)
    x = int(roll.x)
    y = int(roll.bottom) + 2
    # Stay clear of the Continue/End row.
    max_bottom = int(play_right.y) - 2
    h = max(12, min(18, max_bottom - y))
    if h < 12:
        # Fallback if layout constants collapse: sit just under roll.
        y = int(roll.bottom) + 1
        h = 14
    return pygame.Rect(x, y, int(roll.w), h)


def clear_busy_status_strip() -> None:
    """Erase the wait-text band so prior frames cannot ghost after busy ends."""
    try:
        rect = busy_status_strip_rect()
        bg = COLORS.get("LGRAY", (200, 200, 200))
        pygame.draw.rect(WIN, bg, rect)
    except Exception:
        pass


def draw_busy_status_line(game: Game | object, *, ticks_ms: int | None = None) -> str:
    """Paint static red 'AI is thinking...' under Roll Dices (or clear strip).

    Always clears the strip first so the label disappears as soon as Play or
    Continue is enabled. Non-clickable. Returns the label drawn, or "".
    """
    clear_busy_status_strip()
    if not should_draw_busy_status(game):
        return ""
    label = BUSY_STATUS_TEXT
    text_color = COLORS.get("RED", (255, 0, 0))
    try:
        rect = busy_status_strip_rect()
        font_bag = Font.SMALL.value
        if isinstance(font_bag, dict):
            font = font_bag.get("regular")
        else:
            font = None
        if font is None:
            font = pygame.font.SysFont("Comic Sans MS", 10, bold=False)
        text_surf = font.render(label, True, text_color)
        text_pos = text_surf.get_rect(midleft=(rect.x + 2, rect.centery))
        WIN.blit(text_surf, text_pos)
    except Exception:
        pass
    return label


class GUIHumanPlayer:
    """Manages button rendering for human player interactions."""
    
    def __init__(self) -> None:
        """Initialize the GUIHumanPlayer with an empty state.

        Args:
            None
        """
        pass

    def _rect(self, name: str) -> pygame.Rect:
        """Return one canonical Human button-panel rectangle."""
        return HUMAN_BUTTON_RECTS.get(name, pygame.Rect(0, 0, 0, 0))

    def _get_twp_mode(self, game: Game) -> str:
        """Return current Human TwP Mode without requiring core imports."""
        try:
            return str(getattr(game, "human_twp_mode", "manual") or "manual").lower()
        except Exception:
            return "manual"

    def _modal_trade_or_rules_panel_active(self, game: Game) -> bool:
        """Return True when a modal trade/rules/discard panel should block Continue.

        CONTINUE advances AI execution.  While HP is answering an incoming TwP,
        editing TwP-Auto rules, using TwP/TwB, or forced to discard on a 7, the
        modal decision must be finished first.  This helper intentionally uses
        only state dictionaries already owned by the GUI/Game so it stays
        import-safe.
        """
        try:
            gui = getattr(game, "gui", None)
            for attr_name in (
                "twb_panel_state",
                "twp_panel_state",
                "twp_auto_rules_panel_state",
                "discard_panel_state",
                "play_dcard_panel_state",
            ):
                state = getattr(gui, attr_name, None) if gui is not None else None
                if isinstance(state, dict) and bool(state.get("active", False)):
                    return True
        except Exception:
            pass
        try:
            if getattr(game, "pending_human_twp_offer", None):
                return True
        except Exception:
            pass
        # Core queue still owes discards even if panel state was not set yet.
        try:
            if list(getattr(game, "pending_discard_queue", None) or []):
                return True
        except Exception:
            pass
        try:
            if str(getattr(game, "state", "") or "") == "DiscardPending":
                return True
        except Exception:
            pass
        return False

    def button_twp_mode_row(self, game: Game, active: bool) -> None:
        """Render the compact incoming-TwP policy row above the normal buttons.

        Red / AI / Auto are mutually exclusive modes.  Edit opens the future
        HP auto-rule editor and is not itself a mode.
        """
        mode = self._get_twp_mode(game)
        label_color = COLORS["BLACK"] if active else COLORS["GRAY"]
        text = Font.NORMAL.value["regular"].render("TwP Mode ->", True, label_color)
        WIN.blit(text, HUMAN_TWP_MODE_LABEL_POS)

        specs = [
            # Red and AI are active policy modes now.  Auto is visible but
            # remains a placeholder until Step 6 adds rule evaluation.
            # Edit opens the Step-5 raw-rule editor and is not itself a mode.
            ("twp_mode_red", "TWP_MODE_RED", "R", mode == "red", True),
            ("twp_mode_ai", "TWP_MODE_AI", "AI", mode == "ai", True),
            ("twp_mode_auto", "TWP_MODE_AUTO", "Au", mode == "auto", False),
            ("edit_twp_auto", "TWP_MODE_EDIT_AUTO", "E", False, True),
        ]
        for button_name, image_key, fallback_text, selected, clickable in specs:
            rect = self._rect(button_name)
            button_active = bool(active and clickable)
            game.gui.set_button(button_name, button_active)
            image = IMAGES.get(image_key, {}).get("default")
            if image is None:
                pygame.draw.rect(WIN, COLORS["LGRAY"], rect)
                small = Font.NORMAL.value["regular"].render(
                    fallback_text, True, COLORS["BLACK"] if button_active else COLORS["GRAY"]
                )
                WIN.blit(small, small.get_rect(center=rect.center))
            else:
                # The TwP Mode asset itself remains 30x30, but the border/click
                # target is 40x40, just like the Buy buttons.  Center the image
                # inside the larger slot.
                WIN.blit(image, image.get_rect(center=rect.center))
            # Match Buy button columns exactly: Red/AI/Auto/Edit use the same
            # x-coordinates as City/Settlement/Road/DCard one row lower.
            # Every TwP Mode image has a 40x40 border; active mode only changes color.
            border_color = COLORS["GREEN"] if selected and active else (COLORS["BLACK"] if button_active else COLORS["GRAY"])
            pygame.draw.rect(WIN, border_color, rect, 2)

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_twp_mode_row | active={active} mode={mode}\n")

    def text_buy(self, game: Game, active: bool) -> None:
        """Render 'Buy -->' text with active or inactive styling.

        Args:
            game: The game instance.
            active: Whether the text is active (black) or inactive (gray).
        """
        font = Font.LARGE.value["regular"]
        color = COLORS["BLACK"] if active else COLORS["GRAY"]
        game.gui.set_button("text_buy", active)
        text = font.render("Buy -->", True, color)
        WIN.blit(text, (25, HUMAN_BUTTON_RECTS["buy_city"].y + 2))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | text_buy | Active: {active}\n")

    def text_trade(self, game: Game, active: bool) -> None:
        """Render 'Trade -->' text with active or inactive styling.

        Args:
            game: The game instance.
            active: Whether the text is active (black) or inactive (gray).
        """
        font = Font.LARGE.value["regular"]
        color = COLORS["BLACK"] if active else COLORS["GRAY"]
        game.gui.set_button("text_trade", active)
        text = font.render("Trade -->", True, color)
        WIN.blit(text, (25, HUMAN_BUTTON_RECTS["twp"].y + 2))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | text_trade | Active: {active}\n")

    def button_buy_city(self, game: Game, active: bool) -> None:
        """Render 'Buy City' button with image and border.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, CITY_GREEN) or inactive (gray border, CITY_DGRAY).
        """
        game.gui.set_button("buy_city", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        image_key = "CITY_GREEN" if active else "CITY_DGRAY"
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["buy_city"], 2)
        image = IMAGES.get(image_key, {}).get("30x30")
        if image is not None:
            WIN.blit(image, (HUMAN_BUTTON_RECTS["buy_city"].x + 5, HUMAN_BUTTON_RECTS["buy_city"].y + 5))
        else:
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"gui_human_player.py | button_buy_city | Missing image: {image_key}\n")
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_buy_city | Active: {active}\n")

    def button_buy_settlement(self, game: Game, active: bool) -> None:
        """Render 'Buy Settlement' button with image and border.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, SETTLEMENT_GREEN) or inactive (gray border, SETTLEMENT_DGRAY).
        """
        game.gui.set_button("buy_settlement", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        image_key = "SETTLEMENT_GREEN" if active else "SETTLEMENT_DGRAY"
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["buy_settlement"], 2)
        image = IMAGES.get(image_key, {}).get("30x30")
        if image is not None:
            WIN.blit(image, (HUMAN_BUTTON_RECTS["buy_settlement"].x + 5, HUMAN_BUTTON_RECTS["buy_settlement"].y + 5))
        else:
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"gui_human_player.py | button_buy_settlement | Missing image: {image_key}\n")
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_buy_settlement | Active: {active}\n")

    def button_buy_road(self, game: Game, active: bool) -> None:
        """Render 'Buy Road' button with image and border.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, ROAD_GREEN) or inactive (gray border, ROAD_DGRAY).
        """
        game.gui.set_button("buy_road", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        image_key = "ROAD_GREEN" if active else "ROAD_DGRAY"
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["buy_road"], 2)
        image = IMAGES.get(image_key, {}).get("30x30")
        if image is not None:
            WIN.blit(image, (HUMAN_BUTTON_RECTS["buy_road"].x + 5, HUMAN_BUTTON_RECTS["buy_road"].y + 5))
        else:
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"gui_human_player.py | button_buy_road | Missing image: {image_key}\n")
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_buy_road | Active: {active}\n")

    def button_buy_dcard(self, game: Game, active: bool) -> None:
        """Render 'Buy DCard' button with image and border, checking resource availability.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, DCARD_GREEN) or inactive (gray border, DCARD_DGRAY), modified by resource availability.
        """
        human_player = game.players[game.turn - 1]
        resources = [
            human_player.rcards.get(ResourceCard.WHEAT, 0),
            human_player.rcards.get(ResourceCard.ORE, 0),
            human_player.rcards.get(ResourceCard.SHEEP, 0)
        ]
        can_buy = (resources[0] >= 1 and resources[1] >= 1 and resources[2] >= 1 and len(game.dcards_stack) > 0)
        game.gui.set_button("buy_dcard", active and can_buy)
        border_color = COLORS["GREEN"] if active and can_buy else COLORS["GRAY"]
        image_key = "DCARD_GREEN" if active and can_buy else "DCARD_DGRAY"
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["buy_dcard"], 2)
        image = IMAGES.get(image_key, {}).get("30x30")
        if image is not None:
            WIN.blit(image, (HUMAN_BUTTON_RECTS["buy_dcard"].x + 5, HUMAN_BUTTON_RECTS["buy_dcard"].y + 5))
        else:
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"gui_human_player.py | button_buy_dcard | Missing image: {image_key}\n")
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_buy_dcard | Active: {active and can_buy}\n")

    def button_twp(self, game: Game, active: bool) -> None:
        """Render 'Trade w/ Player' button with text and border.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, white text) or inactive (gray border, gray text).
        """
        game.gui.set_button("twp", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        text_color = COLORS["WHITE"] if active else COLORS["GRAY"]
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["twp"], 2)
        text = Font.LARGE.value["regular"].render("TwP", True, text_color)
        WIN.blit(text, (HUMAN_BUTTON_RECTS["twp"].x + 5, HUMAN_BUTTON_RECTS["twp"].y + 2))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_twp | Active: {active}\n")

    def button_twb(self, game: Game, active: bool) -> None:
        """Render 'Trade w/ Bank' button with text and border.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, white text) or inactive (gray border, gray text).
        """
        game.gui.set_button("twb", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        text_color = COLORS["WHITE"] if active else COLORS["GRAY"]
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["twb"], 2)
        text = Font.LARGE.value["regular"].render("TwB", True, text_color)
        WIN.blit(text, (HUMAN_BUTTON_RECTS["twb"].x + 5, HUMAN_BUTTON_RECTS["twb"].y + 2))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_twb | Active: {active}\n")

    def button_roll_dices(self, game: Game, active: bool) -> None:
        """Render 'Roll Dices' button with text and border.

        Args:
            game: The game instance.
            active: Whether the button is active (green border, white text) or inactive (gray border, gray text).
        """
        game.gui.set_button("roll_dices", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        text_color = COLORS["WHITE"] if active else COLORS["GRAY"]
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["roll_dices"], 2)
        text = Font.LARGE.value["regular"].render("Roll Dices", True, text_color)
        WIN.blit(text, (HUMAN_BUTTON_RECTS["roll_dices"].x + 5, HUMAN_BUTTON_RECTS["roll_dices"].y + 2))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_roll_dices | Active: {active}\n")

    def clear_right_action_slot(self, game: Game) -> None:
        """Clear the shared right-side action slot.

        The old End Turn and Cancel buttons both used this same rectangle.  The
        slot is now exclusive: AI shows Continue, human shows End, and Cancel is
        deliberately removed.
        """
        game.gui.set_button("end_turn", False)
        game.gui.set_button("continue_ai", False)
        game.gui.set_button("cancel", False)
        pygame.draw.rect(WIN, COLORS["LGRAY"], RIGHT_ACTION_SLOT_RECT)

    def _button_right_action(self, game: Game, label: str, active: bool, button_name: str) -> None:
        """Render the exclusive right action slot as Continue or End."""
        self.clear_right_action_slot(game)
        game.gui.set_button(button_name, bool(active))
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        text_color = COLORS["WHITE"] if active else COLORS["GRAY"]
        pygame.draw.rect(WIN, border_color, RIGHT_ACTION_SLOT_RECT, 2)
        text = Font.LARGE.value["regular"].render(label, True, text_color)
        rect = pygame.Rect(*RIGHT_ACTION_SLOT_RECT)
        WIN.blit(text, text.get_rect(center=rect.center))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | _button_right_action | {label}: {active}\n")

    def button_end_turn(self, game: Game, active: bool) -> None:
        """Render the human-player right action slot as 'End'."""
        self._button_right_action(game, "End", active, "end_turn")

    def button_continue(self, game: Game, active: bool) -> None:
        """Render the AI-player right action slot as 'Continue'."""
        self._button_right_action(game, "Continue", active, "continue_ai")

    def draw_busy_status(self, game: Game, *, ticks_ms: int | None = None) -> str:
        """Update wait status under Roll Dices: clear always; draw only if busy.

        Call every Execution redraw (not only when busy) so enabling Play or
        Continue removes any leftover red text immediately.
        """
        return draw_busy_status_line(game, ticks_ms=ticks_ms)

    def button_cancel(self, game: Game, active: bool) -> None:
        """Deprecated: Cancel is intentionally removed from the Execution UI."""
        game.gui.set_button("cancel", False)

    def button_next_turn2(self, game: Game, active: bool) -> None:
        """Render 'Play' button with text and border

        Args:
            game: The game instance.
            active: Whether the button is active (green border, white text) or inactive (gray border, gray text).
        """        
        game.gui.set_button("next_turn2", active)
        border_color = COLORS["GREEN"] if active else COLORS["GRAY"]
        text_color = COLORS["WHITE"] if active else COLORS["GRAY"]
        pygame.draw.rect(WIN, border_color, HUMAN_BUTTON_RECTS["next_turn2"], 2)
        text = Font.LARGE.value["regular"].render("Play", True, text_color)
        WIN.blit(text, (HUMAN_BUTTON_RECTS["next_turn2"].x + 5, HUMAN_BUTTON_RECTS["next_turn2"].y + 2))
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | button_next_turn2 | Active: {active}\n")

        # Optional debug (you can delete later)
        ### print(f"DEBUG: button_next_turn2 | active={active} | registered={game.gui.check_button('next_turn2')}")

    def _current_player(self, game: Game):
        try:
            return game.get_current_player()
        except Exception:
            try:
                return game.players[game.turn - 1]
            except Exception:
                return None

    def _hand_and_trade_rates(self, game: Game, player) -> tuple[list[int], list[int]]:
        """Return hand and bank/port trade rates in Wh/O/Wd/B/Sh order."""
        hand = [0, 0, 0, 0, 0]
        rates = [4, 4, 4, 4, 4]
        try:
            info = player.rcards_in_hand()
            if isinstance(info, (list, tuple)):
                if len(info) >= 1 and isinstance(info[0], (list, tuple)):
                    hand = [int(x or 0) for x in list(info[0])[:5]]
                if len(info) >= 2 and isinstance(info[1], (list, tuple)):
                    rates = [int(x or 4) for x in list(info[1])[:5]]
        except Exception:
            try:
                # Fallback for the current dict-based resource-card model.
                order = game._execution_resource_order() if hasattr(game, "_execution_resource_order") else []
                if order:
                    hand = [int(player.rcards.get(res, 0) or 0) for res in order[:5]]
            except Exception:
                pass

        if rates == [4, 4, 4, 4, 4]:
            for attr in ("trade_rates", "trade_ratio"):
                try:
                    candidate = getattr(player, attr, None)
                    if isinstance(candidate, (list, tuple)) and len(candidate) >= 5:
                        rates = [int(x or 4) for x in list(candidate)[:5]]
                        break
                except Exception:
                    pass
        rates = [(r if r > 0 else 4) for r in (rates + [4, 4, 4, 4, 4])[:5]]
        return hand, rates

    def _scan_viable_map(self, game: Game) -> dict[str, bool]:
        """Return raw legal buy/build viability by action.

        Human buttons should show what is legally possible.  Strategy locks are
        AI-priority decisions and should not disable a human's legal button.
        """
        result = {
            "Build city": False,
            "Build settlement": False,
            "Build road": False,
            "Buy development_card": False,
        }
        for row in list(getattr(game, "current_execution_choices", []) or []):
            if not isinstance(row, dict):
                continue
            action = str(row.get("action", "") or "")
            if action not in result:
                continue
            result[action] = bool(row.get("scan_viable", row.get("viable", False)))
        # Fallback to the raw scan object/dict when choices are not available yet.
        scan = getattr(game, "current_viable_action_scan", None)
        flags = {}
        try:
            if isinstance(scan, dict):
                flags = dict(scan.get("action_flags", {}) or {})
            else:
                flags = dict(getattr(scan, "action_flags", {}) or {})
        except Exception:
            flags = {}
        for action in result:
            if not result[action] and action in flags:
                result[action] = bool(flags.get(action))
        return result

    def _execution_human_button_state(self, game: Game) -> dict:
        """Compute the Human Execution button panel from current game state."""
        state = str(getattr(game, "state", "") or "")
        dice_roll = getattr(game, "dice_roll", None)
        dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"
        forced = state in {
            "MoveRobber",
            "RobberMoveRequired",
            "SetRobber",
            "StealSelectOpponent",
            "DiscardPending",
        }
        player = self._current_player(game)

        buttons = {
            "play": False,
            "roll_dices": False,
            "end": False,
            "buy_city": False,
            "buy_settlement": False,
            "buy_road": False,
            "buy_dcard": False,
            "twp": False,
            "twb": False,
        }

        # W2: freeze buy/trade/roll/end once a winner is declared.
        if bool(getattr(game, "game_over", False)):
            return buttons

        if player is None:
            return buttons
        # Forced discard panel / queue: no End, buy, or trade until OK.
        try:
            gui = getattr(game, "gui", None)
            dstate = getattr(gui, "discard_panel_state", None) if gui is not None else None
            if isinstance(dstate, dict) and bool(dstate.get("active", False)):
                return buttons
        except Exception:
            pass
        try:
            if list(getattr(game, "pending_discard_queue", None) or []):
                return buttons
        except Exception:
            pass
        if dice_not_rolled:
            # Before dice: only Roll Dices. PLAY is not used in Execution for
            # humans (legacy gate that used to unlock roll+knight). Knight is
            # offered via scoreboard DCard icons when playable.
            buttons["play"] = False
            buttons["roll_dices"] = True
            return buttons
        if forced:
            return buttons
        if state != "ActionSelection":
            return buttons

        buttons["end"] = True
        viable = self._scan_viable_map(game)
        buttons["buy_city"] = bool(viable.get("Build city", False))
        buttons["buy_settlement"] = bool(viable.get("Build settlement", False))
        buttons["buy_road"] = bool(viable.get("Build road", False))
        buttons["buy_dcard"] = bool(viable.get("Buy development_card", False))

        hand, rates = self._hand_and_trade_rates(game, player)
        buttons["twb"] = any(int(h or 0) >= int(r or 4) for h, r in zip(hand, rates))

        # Layer 4 Human TwP panel.  TwP becomes clickable only after dice/RP,
        # while the game is in ActionSelection, the human has at least one card,
        # and there is at least one non-human counterparty.  HP-to-HP TwP
        # confirmation is intentionally deferred to Layer 4C.
        try:
            current_id = int(getattr(player, "id", 0) or 0)
            has_ai_counterparty = any(
                int(getattr(other, "id", 0) or 0) != current_id
                and not bool(getattr(other, "is_human", False))
                for other in list(getattr(game, "players", []) or [])
                if other is not None
            )
        except Exception:
            has_ai_counterparty = True
        buttons["twp"] = bool(sum(int(x or 0) for x in hand) > 0 and has_ai_counterparty)
        return buttons

    def show_buttons_HP(self, game: Game, analysis_tf: bool = False) -> None:
        """Render buttons for human player actions based on game phase and status.

        Args:
            game: The game instance containing phase and player data.
            analysis_tf: Whether analysis mode is active (True) or not (False, default).
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{game.sequence_number} | {game.state} | gui_human_player.py | show_buttons_HP\n")
       
        # Draw button panel with black border
        pygame.draw.rect(WIN, COLORS["BLACK"], HUMAN_BUTTON_PANEL_RECT, 2)
        twp_mode_row_active = bool(str(getattr(game, "phase", "") or "") == "Execution" and not analysis_tf)
        self.button_twp_mode_row(game, twp_mode_row_active)
 
        # Helper functions
        def log_spec2(nr: int, txt: str) -> None:
            """Log button modes and states to FILENAME_SPEC2.

            Args:
                nr: Log entry number for identification.
                txt: Descriptive text for the log entry.
            """
            with open(FILENAME_SPEC2, "a") as f:
                f.write(f"{nr} {txt}\n")
                for mode in list(getattr(game.gui, "modes", []) or []):
                    # Modern GUI modes are plain strings, while older copies
                    # used tiny mode objects with .name/.true_false.  Support
                    # both so SPEC2 logging never crashes gameplay redraws.
                    mode_name = getattr(mode, "name", str(mode))
                    mode_tf = getattr(mode, "true_false", True)
                    f.write(f"{mode_name} {mode_tf}\n")
                game.gui.write_queues()
       
        def get_hp_sequence_hp(game: Game) -> list:
            """Return configured human player ids as a flat list of ints.

            HP_ID is configured in core.constants and may be either a single
            integer or a list such as [3].  The old code returned [HP_ID],
            which turns [3] into [[3]] and makes membership checks fail.
            """
            raw_ids = HP_ID
            if isinstance(raw_ids, (list, tuple, set)):
                values = list(raw_ids)
            elif raw_ids in (None, ""):
                values = []
            else:
                values = [raw_ids]

            result = []
            for value in values:
                try:
                    result.append(int(value))
                except (TypeError, ValueError):
                    pass
            return result

        # Used by both InitialPlacement and Execution branches.  Keep this
        # outside the phase-specific blocks so show_buttons_HP() never reads an
        # unassigned local variable when the game starts directly in Execution.
        hp_sequence = get_hp_sequence_hp(game)
       
        def check_modes1() -> bool:
            """Check if any button is set to display.

            Args:
                None

            Returns:
                bool: True if any button is set to display, False otherwise.
            """
            for button in game.gui.buttons:
                if button.display_yn:
                    return True
            return False
       
        def check_modes2() -> bool:
            """Check if specific modes are active.

            Args:
                None

            Returns:
                bool: True if modes like Show_availableintersectionss or Show_available_roads are active, False otherwise.
            """
            return (game.gui.check_mode("Show_availableintersectionss") or
                    game.gui.check_mode("Show_available_roads") or
                    game.gui.check_mode("TwP_OpponentFoundAndSelected"))

        # ────────────────────────────────────────────────
        # Main logic – tightened for initial placement
        # ────────────────────────────────────────────────
        if game.phase == "InitialPlacement" and not analysis_tf:
            self.text_buy(game, False)
            self.text_trade(game, False)
            self.button_buy_city(game, False)
            self.button_buy_settlement(game, False)
            self.button_buy_road(game, False)
            self.button_buy_dcard(game, False)
            self.button_twp(game, False)
            self.button_twb(game, False)
            self.clear_right_action_slot(game)

            is_placing = game.gui.human_guidance.is_placing() if hasattr(game.gui, 'human_guidance') else False

            # Initial placement is driven by the Play button for both AI and
            # human players:
            #   - AI turn: Play executes settlement + road automatically.
            #   - human turn, before placement starts: Play starts guidance.
            #   - human is actively choosing/confirming: Play must be disabled
            #     so the user finishes OKY/NOK first.
            # The earlier HP_ID fix made P3 correctly recognised as human, but
            # the old branch then disabled Play before guidance could start.
            self.button_roll_dices(game, False)
            self.clear_right_action_slot(game)
            # P3-A: never light PLAY while pipeline / Phase0 / press latch busy
            try:
                from core.performance_trace import is_ui_input_busy

                ip_busy = bool(is_ui_input_busy(game))
            except Exception:
                ip_busy = bool(getattr(game, "ai_pipeline_busy", False)) or bool(
                    getattr(game, "phase0_save_busy", False)
                ) or bool(getattr(game, "ui_play_continue_latched", False))
            if is_placing or ip_busy:
                self.button_next_turn2(game, False)
                # Option A: no busy wait text during Initial Placement.
            else:
                self.button_next_turn2(game, True)

        elif game.phase == "Planning" and analysis_tf:
            self.button_next_turn2(game, True) # Analysis button not fully implemented
            log_spec2(260, "show_buttons_HP | Analysis mode")
       
        elif game.phase == "Execution" and not analysis_tf:
            # Playable DCard green/gold borders are drawn in gui.update_scoreboard
            # (canonical DCARD_X_POSITIONS + hit-test for Play DCard panel).
            if check_modes2():
                self.text_buy(game, False)
                self.text_trade(game, False)
                self.button_buy_city(game, False)
                self.button_buy_settlement(game, False)
                self.button_buy_road(game, False)
                self.button_buy_dcard(game, False)
                self.button_twp(game, False)
                self.button_twb(game, False)
                self.button_roll_dices(game, False)
                self.button_next_turn2(game, False)
                self.clear_right_action_slot(game)
            else:
                log_spec2(270, "show_buttons_HP")
                pygame.draw.rect(WIN, COLORS["BLACK"], HUMAN_BUTTON_PANEL_RECT, 2)
                self.button_twp_mode_row(game, True)
                self.text_buy(game, False)
                self.text_trade(game, False)
                self.button_buy_city(game, False)
                self.button_buy_settlement(game, False)
                self.button_buy_road(game, False)
                self.button_buy_dcard(game, False)
                self.button_twp(game, False)
                self.button_twb(game, False)
               
                # Turn-boundary safety: this shared button area must be rebuilt
                # from the current game state on every redraw.  Do not let an
                # active AI Continue button from P2 remain visible for P3's fresh
                # AwaitingDiceRoll turn.
                self.button_roll_dices(game, False)
                self.button_next_turn2(game, False)
                self.clear_right_action_slot(game)

                state = str(getattr(game, "state", "") or "")
                dice_roll = getattr(game, "dice_roll", None)
                dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"
                is_human_turn = bool(HUMAN_PLAYER and game.turn in hp_sequence)
                game_is_over = bool(getattr(game, "game_over", False))

                if game_is_over:
                    # W2/W3: freeze buy/trade/roll; post-game strip is drawn by
                    # gui_game_over_panel (Statistics / Playboard / New Game).
                    self.button_next_turn2(game, False)
                    self.button_continue(game, False)
                    self.button_roll_dices(game, False)
                    self.button_end_turn(game, False)
                    try:
                        from gui.gui_game_over_panel import (
                            ensure_post_game_ui,
                            draw_post_game_strip,
                        )

                        ensure_post_game_ui(game)
                        draw_post_game_strip(game)
                    except Exception:
                        pass
                elif not is_human_turn:
                    if hasattr(game, "ai_continue_is_available"):
                        continue_active = bool(game.ai_continue_is_available())
                    else:
                        # Safe fallback for older Game copies: once an AI has
                        # rolled dice, Continue means pass/advance even if there
                        # are no legal buy/build actions.
                        continue_active = bool(not dice_not_rolled)
                    play_active = bool(dice_not_rolled)
                    # P2-A / 30-G: Play+Continue off while pipeline or Phase0 save busy
                    try:
                        from core.performance_trace import is_ui_input_busy

                        busy = is_ui_input_busy(game)
                    except Exception:
                        try:
                            busy = bool(getattr(game, "ai_pipeline_busy", False)) or bool(
                                getattr(game, "phase0_save_busy", False)
                            )
                        except Exception:
                            busy = False
                    if busy:
                        continue_active = False
                        play_active = False
                    if self._modal_trade_or_rules_panel_active(game):
                        continue_active = False
                    self.button_next_turn2(game, play_active)
                    self.button_continue(game, continue_active)
                    # Always refresh strip: draw when busy+both off, else clear ghost text
                    self.draw_busy_status(game)
                else:
                    # Human Execution panel: rebuild from the current game state
                    # and raw scanner legality on every redraw.  This is the
                    # modern replacement for v045 validate_buttons_HP(...).
                    #
                    # Pre-roll: Roll Dices + (optional) scoreboard Knight only.
                    # PLAY stays off in Execution for humans.
                    human_buttons = self._execution_human_button_state(game)
                    # P2-A: also grey human Play during Phase0 save / nested AI work
                    try:
                        from core.performance_trace import is_ui_input_busy

                        human_busy = is_ui_input_busy(game)
                    except Exception:
                        human_busy = bool(getattr(game, "phase0_save_busy", False))
                    human_play = bool(human_buttons["play"]) and not human_busy

                    self.button_next_turn2(game, human_play)
                    self.button_roll_dices(
                        game, bool(human_buttons.get("roll_dices")) and not human_busy
                    )
                    self.button_end_turn(game, bool(human_buttons["end"]) and not human_busy)
                    # Always refresh strip (clear when idle / any action button on)
                    self.draw_busy_status(game)

                    self.button_buy_city(game, bool(human_buttons["buy_city"]))
                    self.button_buy_settlement(game, bool(human_buttons["buy_settlement"]))
                    self.button_buy_road(game, bool(human_buttons["buy_road"]))
                    self.button_buy_dcard(game, bool(human_buttons["buy_dcard"]))
                    self.button_twp(game, bool(human_buttons["twp"]))
                    self.button_twb(game, bool(human_buttons["twb"]))

                    self.text_buy(
                        game,
                        bool(human_buttons["buy_city"] or human_buttons["buy_settlement"] or human_buttons["buy_road"] or human_buttons["buy_dcard"]),
                    )
                    self.text_trade(game, bool(human_buttons["twb"] or human_buttons["twp"]))
       
        # Keep the incoming AI→HP TwP panel visible during the normal main-loop
        # redraw as well as event-handler redraws.  Incoming and outgoing TwP
        # panels now share gui_trade_player_panel.py so their layout stays aligned.
        try:
            from gui.gui_trade_player_panel import (
                draw_incoming_twp_panel,
                is_incoming_twp_panel_active,
            )
            if is_incoming_twp_panel_active(game):
                draw_incoming_twp_panel(game)
        except Exception:
            pass

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_human_player.py | show_buttons_HP | Rendered buttons for phase: {game.phase}, analysis_tf: {analysis_tf}\n")

        pygame.display.update()