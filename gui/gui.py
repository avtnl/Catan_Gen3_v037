"""
Handles general GUI functionality for the Catan game.
Now includes HumanGuidance for settlement/road placement and confirmation.
"""
import pygame
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from core import board
from gui.gui_constants import (
    WIN, COLORS, Font, IMAGES, SOUNDS, POSITIONS, BOARD_OFFSET,
    UI_PANEL_LAYOUT, UI_PANEL_LAYOUT_NOTES, panel_layout_overview as constants_panel_layout_overview,
    PLAYBOARD_RECT, TWITTER_PANEL_RECT, LEFT_DICE_PANEL_RECT,
    ROUND_TURN_RECT, GUIDANCE_TEXT_RECT, GUIDANCE_TEXT_LINE0_Y, GUIDANCE_TEXT_LINE_SPACING,
    RESOURCE_POTENTIAL_RECT, RESOURCE_POTENTIAL_HEADER_Y, RESOURCE_POTENTIAL_LABEL_Y,
    RESOURCE_POTENTIAL_CURRENT_Y, RESOURCE_POTENTIAL_APPROX_Y,
    SCOREBOARD_RECT, TURN_DETAIL_PANEL_RECT,
    SCOREBOARD_HEADER_X_POSITIONS, RESOURCE_CARD_X_POSITIONS, DCARD_X_POSITIONS,
    SCOREBOARD_VERTICAL_LINES, TURN_DETAIL_BUTTON_X, TURN_DETAIL_BUTTON_SIZE,
    RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS, RESOURCE_PRODUCTION_HIGHLIGHT_WIDTH,
    RESOURCE_PRODUCTION_HIGHLIGHT_DELAY_MS,
    ROBBER_TILE_HIGHLIGHT_RADIUS, VICTIM_STEAL_HIGHLIGHT_RADIUS,
    ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS, ROBBER_AVAILABLE_STEAL_TARGET_RADIUS,
    DCARD_HEADER_PLAY_PULSE_RADIUS, DCARD_HEADER_ICON_CENTER_Y,
)
from gui.gui_guidance import HumanGuidance
from core.board import Board
from core.game import Game, Player
from core.constants import FNFREQ, FILENAME_FREQ, MG, FILENAME_MG, SAVE_PATH, ResourceCard

def convert_tile(tile_id: int) -> Optional[Tuple[int, int]]:
    """Convert a tile ID to its GUI midpoint coordinates."""
    coords = POSITIONS["tiles"].get(tile_id)
    if coords is None and MG:
        with open(FILENAME_MG, "a") as f:
            f.write(f"gui.py | convert_tile | Missing coordinates for tile ID: {tile_id}\n")
    return tuple(coords) if coords else None

# ─────────────────────────────────────────────────────────────────────────────
# GUI panel layout map
# ─────────────────────────────────────────────────────────────────────────────
# The canonical panel rectangles live in gui_constants.py. gui.py imports them
# and only draws against those named regions. This keeps layout documentation
# and coordinates in one obvious place for new contributors.

class Button:
    """Represents a button with name, display state, and switch status."""
    def __init__(self, name: str, display_tf: bool):
        self.name = name
        self.display_tf = display_tf
        self.switched_tf = False

class GUI:
    """Manages button states, modes, board rendering, and human guidance."""
    def __init__(self, round_number: int, turn: int, game: 'Game'):  # Add game parameter with forward reference
        """Initialize the GUI with game round and turn."""
        if not pygame.font.get_init():
            pygame.font.init()
        Font.initialize_fonts()
        self.game = game  # Set the attribute here
        self.round = round_number
        self.turn = turn
        self.buttons: List[Button] = []
        self.modes: List[any] = []
        # Persistent queue for continuous subtle highlight of last placement
        self.animate_queue_elements: List[Tuple[Tuple[int,int], Tuple[int,int,int], int, str]] = []
        self.animations_enabled: bool = True
        self.last_dice_roll: Optional[Tuple[int, int]] = None
        # D1: shared DCard header play pulse (full seat-turn; independent of board queue)
        self.dcard_header_play_fx: Optional[Dict[str, Any]] = None

        # Lightweight v045-inspired event feed in the top-right pane.
        # Entries are kept as dicts, but add_tweet also accepts the old
        # v045 shape [player_id, message].
        self.twitter: List[dict] = []
        self.twitter_max_items: int = 12
        # G1: Events + Execution Debug stay hidden until first PLAY click.
        self.events_debug_revealed: bool = False
        # BS-1: first PLAY that starts Initial Placement (Settings confirm gate).
        self.ip_started_via_play: bool = False
        # G9: stash closed right-slot modal while '?' turn detail is open.
        self.modal_restore_after_turn_detail: Optional[Dict[str, Any]] = None

        # v045-inspired turn-details overlay for the scoreboard.
        # The GUI owns only toggle/render state; game/player objects own data.
        self.turn_detail_expanded_player_id: Optional[int] = None
        self.turn_detail_button_rects: Dict[int, pygame.Rect] = {}
        # No separate close button: the visible '?' itself is the toggle.
        self.turn_detail_panel_rect: Optional[pygame.Rect] = None

        # Human guidance system
        self.human_guidance = HumanGuidance(self)

        # Pre-register all buttons so they exist from the start
        for name in [
            "next_turn2",
            "roll_dices",
            "end_turn",
            "continue_ai",
            "buy_city",
            "buy_settlement",
            "buy_road",
            "buy_dcard",
            "twp",
            "twb",
            "twb_panel",
            "play_dcard_panel",
            "text_buy",
            "text_trade",
            "cancel",
        ]:
            self.set_button(name, False)

        # UI-only state for the Human Trade-with-Bank panel.  The selected
        # resources are not saved with the game; only confirmed trades mutate
        # Game/player state.
        self.twb_panel_state = {
            "active": False,
            "give": [0, 0, 0, 0, 0],
            "get": [0, 0, 0, 0, 0],
            "rects": {},
        }

        # UI-only Play DCard panel (same screen slot as TwB/TwP/discard).
        self.play_dcard_panel_state = {
            "active": False,
            "card_type": None,
            "player_id": None,
            "mono_selected": None,
            "yop_first": None,
            "yop_second": None,
            "rects": {},
            "message": "",
            "confirmed_stub": False,
        }
        self.dcard_scoreboard_hit_rects: List[Dict[str, Any]] = []

        # UI-only state for human Execution-phase road buying.  Legal road
        # candidates come from viable_action_scanner / execution manager; this
        # state stores only the visible selection and confirmation workflow.
        self.human_buy_road_state = {
            "active": False,
            "candidates": [],
            "selected_road": None,
        }

    def print_queues(self) -> None:
        """Log the contents of animation queues for debugging."""
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui.py | print_queues | Elements: {self.animate_queue_elements}\n")

    def write_queues(self) -> None:
        """Compatibility alias used by gui_human_player.log_spec2().

        Older code calls GUI.write_queues(), while this v031 GUI currently
        exposes GUI.print_queues(). Keep both names so debug logging does not
        crash the runtime GUI refresh loop.
        """
        self.print_queues()

    def add_tweet(self, player_or_message, message: Optional[str] = None, *, update: bool = True) -> None:
        """Append one message to the top-right event feed.

        Supported call styles:
            self.add_tweet("message")
            self.add_tweet(player_id, "message")
            self.add_tweet([player_id, "message"])  # v045-compatible shape
        """
        player_id = None
        text = ""

        if isinstance(player_or_message, (list, tuple)) and len(player_or_message) >= 2:
            player_id = player_or_message[0]
            text = str(player_or_message[1])
        elif message is None:
            text = str(player_or_message)
        else:
            player_id = player_or_message
            text = str(message)

        try:
            player_id = int(player_id) if player_id not in (None, "", 0) else None
        except Exception:
            player_id = None

        # Suppress noisy first-robber/debug line when there is no known previous
        # robber tile yet.  Useful events such as "rolled 7" and final robber
        # placement/steal remain visible.
        if "removed robber from tile ?" in text:
            return

        # CHECK_MODE=False: drop DBG; anonymize steal + opponent DCard buys.
        try:
            from core.debug_mode import filter_event_feed_message

            filtered = filter_event_feed_message(
                text,
                getattr(self, "game", None),
                player_id=player_id,
            )
            if filtered is None:
                return
            text = filtered
        except Exception:
            pass

        entry = {
            "player_id": player_id,
            "message": text,
            "round": getattr(self.game, "round", None),
            "turn": getattr(self.game, "turn", None),
        }
        self.twitter.append(entry)
        if len(self.twitter) > 50:
            self.twitter = self.twitter[-50:]

        if update:
            self.update_twitter()

    def clear_twitter(self) -> None:
        """Clear the event feed pane."""
        self.twitter.clear()
        self.update_twitter()

    def panel_layout_overview(self) -> Dict[str, Tuple[int, int, int, int]]:
        """Return major GUI panel rectangles from gui_constants.py.

        This is meant for contributors/debugging: a caller can print
        `game.gui.panel_layout_overview()` and immediately see which screen
        regions are reserved.
        """
        return constants_panel_layout_overview()

    def reveal_events_and_debug(self) -> None:
        """G1: allow Events + Execution Debug after the first PLAY press."""
        self.events_debug_revealed = True

    def draw_execution_debug_panel(self, game: Optional[Game] = None) -> None:
        """Draw the mid-right Slice A/B Execution debug panel.

        The actual renderer lives in gui_execution_debug_panel.py so gui.py stays
        focused on general board/scoreboard rendering.  Import lazily to avoid
        adding startup/circular-import fragility.

        G1: suppressed until first PLAY (``events_debug_revealed``).
        CHECK_MODE=False: dig-in panel fully hidden for normal play.
        """
        try:
            from core.debug_mode import should_show_execution_debug

            if not should_show_execution_debug():
                return
        except Exception:
            pass
        if not bool(getattr(self, "events_debug_revealed", False)):
            return
        try:
            from gui.gui_execution_debug_panel import draw_execution_debug_panel
            draw_execution_debug_panel(game or self.game)
        except Exception as exc:
            # Debug panels must never crash the game loop.
            try:
                print(f"Execution debug panel draw failed: {exc}")
            except Exception:
                pass

    def _player_event_color(self, player_id: Optional[int]):
        """Return the player's RGB color for event-feed markers."""
        if player_id is None:
            return None

        try:
            player_id_int = int(player_id)
        except Exception:
            return None

        try:
            for player in getattr(self.game, "players", []) or []:
                if int(getattr(player, "id", 0) or 0) == player_id_int:
                    return COLORS.get(str(getattr(player, "color", "")).upper(), COLORS["BLACK"])
        except Exception:
            pass
        return COLORS["BLACK"]

    def _draw_event_player_diamond(
        self,
        player_id: Optional[int],
        center: Tuple[int, int],
        *,
        size: int = 6,
        border_width: int = 1,
    ) -> None:
        """Draw the small player-color diamond used in the Events pane."""
        fill = self._player_event_color(player_id)
        if fill is None:
            return

        x, y = center
        points = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
        pygame.draw.polygon(WIN, fill, points)
        pygame.draw.polygon(WIN, COLORS.get("BLACK", (0, 0, 0)), points, border_width)

    def _normalise_tweet(self, entry) -> Tuple[Optional[int], str]:
        """Support dict entries, old v045 [player_id, message], and prefixed text."""
        player_id = None
        message = ""

        if isinstance(entry, dict):
            player_id = entry.get("player_id")
            message = str(entry.get("message", ""))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            player_id = entry[0]
            message = str(entry[1])
        else:
            message = str(entry)

        try:
            player_id = int(player_id) if player_id not in (None, "", 0) else None
        except Exception:
            player_id = None

        # Some older call sites may already pass "P2: ..." as message text.
        # Use that prefix for the diamond, but do not add a second prefix.
        if player_id is None:
            match = re.match(r"^\s*P([1-9][0-9]*)\s*:\s*", message)
            if match:
                try:
                    player_id = int(match.group(1))
                except Exception:
                    player_id = None

        return player_id, message

    def _event_text_for_display(self, player_id: Optional[int], message: str) -> str:
        """Return event text with exactly one Pn prefix for player events."""
        text = str(message or "")
        if re.match(r"^\s*P[1-9][0-9]*\s*:\s*", text):
            return text.strip()
        if player_id is not None:
            return f"P{int(player_id)}: {text}"
        return text

    def _wrap_tweet_text_pixels(self, text: str, font, max_width: int) -> List[str]:
        """Word-wrap event text using real pixel width instead of character count."""
        words = str(text or "").split()
        if not words:
            return [""]

        lines: List[str] = []
        current = ""

        for word in words:
            candidate = word if not current else f"{current} {word}"
            try:
                candidate_w = font.size(candidate)[0]
            except Exception:
                candidate_w = len(candidate) * 6

            if candidate_w <= max_width:
                current = candidate
                continue

            if current:
                lines.append(current)
                current = word
            else:
                # A single very long token: keep it rather than dropping text.
                lines.append(word)
                current = ""

        if current:
            lines.append(current)
        return lines or [str(text)]

    def update_twitter(self) -> None:
        """Draw the v045-inspired event feed in the top-right pane.

        The renderer works from the newest events backward, then draws the
        selected entries in chronological order. This prevents wrapped earlier
        lines from hiding the latest placement/robber/resource events until the
        next PLAY click.

        G1: blank until first PLAY (``events_debug_revealed``).
        G11 (30-G): always opaque fill + clip so no ghost text under the surface.
        """
        pane = TWITTER_PANEL_RECT.copy()
        # G11: full opaque fill every frame (no bleed from prior frame / underlay)
        pygame.draw.rect(WIN, COLORS["LGRAY"], pane)
        if not bool(getattr(self, "events_debug_revealed", False)):
            # Keep background clear so the right column does not show an empty
            # Events chrome before first PLAY.
            try:
                pygame.display.update(pane)
            except Exception:
                pass
            return

        old_clip = None
        try:
            old_clip = WIN.get_clip()
            WIN.set_clip(pane)
        except Exception:
            old_clip = None

        try:
            pygame.draw.rect(WIN, COLORS["LGRAY"], pane)
            pygame.draw.rect(WIN, COLORS["BLACK"], pane, 1)

            title_font = Font.NORMAL.value["bold"]
            line_font = Font.SMALL.value["regular"]
            WIN.blit(title_font.render("Events", True, COLORS["BLACK"]), (pane.x + 8, pane.y + 4))

            line_height = 13
            max_lines = max(1, (pane.height - 34) // line_height)
            diamond_area_w = 17
            text_x = pane.x + 8 + diamond_area_w
            text_max_w = max(40, pane.width - (text_x - pane.x) - 8)

            selected: List[Tuple[Optional[int], str, List[str]]] = []
            used_lines = 0

            for entry in reversed(list(self.twitter or [])):
                player_id, raw_message = self._normalise_tweet(entry)
                text = self._event_text_for_display(player_id, raw_message)
                wrapped = self._wrap_tweet_text_pixels(text, line_font, text_max_w)
                needed = max(1, len(wrapped))

                # Always show at least the newest event, even if it wraps too much.
                if selected and used_lines + needed > max_lines:
                    break

                selected.append((player_id, text, wrapped))
                used_lines += needed

                if used_lines >= max_lines:
                    break

            y = pane.y + 28
            drawn_lines = 0

            for player_id, _text, wrapped in reversed(selected):
                if drawn_lines >= max_lines:
                    break

                first_line_y = y + drawn_lines * line_height
                # Seat-change banners (player_id None) have no diamond
                if player_id is not None:
                    self._draw_event_player_diamond(
                        player_id, (pane.x + 15, first_line_y + 7), size=5, border_width=1
                    )

                for line_index, line in enumerate(wrapped):
                    if drawn_lines >= max_lines:
                        break
                    x = text_x if line_index == 0 else text_x + 10
                    text_surface = line_font.render(line, True, COLORS["BLACK"])
                    WIN.blit(text_surface, (x, y + drawn_lines * line_height))
                    drawn_lines += 1
        finally:
            if old_clip is not None:
                try:
                    WIN.set_clip(old_clip)
                except Exception:
                    pass
            try:
                pygame.display.update(pane)
            except Exception:
                pass

    def close_turn_detail_panel(self, *, restore_modal: bool = True) -> bool:
        """G12: force-close '?' turn-detail overlay. Returns True if it was open."""
        if self.turn_detail_expanded_player_id is None:
            return False
        previous_panel_rect = (
            self.turn_detail_panel_rect.copy() if self.turn_detail_panel_rect else None
        )
        self.turn_detail_expanded_player_id = None
        self.turn_detail_panel_rect = None
        if restore_modal:
            try:
                self._restore_right_modal_after_turn_detail(self.game)
            except Exception:
                pass
        if previous_panel_rect is not None:
            try:
                pygame.draw.rect(WIN, COLORS["LGRAY"], previous_panel_rect.inflate(4, 4))
            except Exception:
                pass
        return True

    def note_seat_turn_banner(self, game: Any = None) -> None:
        """G10: append Events banner for the current seat (history kept)."""
        game = game if game is not None else getattr(self, "game", None)
        if game is None:
            return
        player = None
        try:
            getter = getattr(game, "get_current_player", None)
            if callable(getter):
                player = getter()
        except Exception:
            player = None
        if player is None:
            try:
                players = list(getattr(game, "players", []) or [])
                turn = int(getattr(game, "turn", 0) or 0)
                for p in players:
                    if int(getattr(p, "id", -1) or -1) == turn:
                        player = p
                        break
            except Exception:
                player = None
        pid = getattr(player, "id", None) if player is not None else None
        color = str(getattr(player, "color", "") or "") if player is not None else ""
        try:
            rnd = int(getattr(game, "round", 0) or 0)
        except Exception:
            rnd = 0
        try:
            trn = int(getattr(game, "turn", 0) or 0)
        except Exception:
            trn = 0
        if pid is not None:
            label = f"— P{pid} {color} turn (R{rnd}T{trn}) —".strip()
        else:
            label = f"— seat turn (R{rnd}T{trn}) —"
        # Avoid duplicate consecutive banners for the same seat/turn
        try:
            last = (self.twitter or [])[-1] if self.twitter else None
            last_msg = ""
            if isinstance(last, dict):
                last_msg = str(last.get("message") or last.get("text") or "")
            elif isinstance(last, (list, tuple)) and len(last) >= 2:
                last_msg = str(last[1])
            if label in last_msg:
                return
        except Exception:
            pass
        try:
            # player_id None = system/seat banner (no diamond)
            self.add_tweet(None, label)
        except Exception:
            try:
                self.twitter.append({"player_id": None, "message": label})
            except Exception:
                pass
        try:
            # Mark which seat last strategy UI should prefer
            setattr(game, "execution_debug_focus_player_id", pid)
        except Exception:
            pass

    def on_play_or_seat_change(self, game: Any = None) -> None:
        """G10+G12: close '?', banner Events, mark debug focus for current seat."""
        game = game if game is not None else getattr(self, "game", None)
        try:
            self.close_turn_detail_panel(restore_modal=True)
        except Exception:
            pass
        try:
            self.note_seat_turn_banner(game)
        except Exception:
            pass
        try:
            if game is not None:
                setattr(game, "execution_debug_stale_until_refresh", True)
        except Exception:
            pass
        try:
            self.update_twitter()
        except Exception:
            pass

    def stop_all_animations(self, *, redraw_board: bool = True) -> None:
        """Stop/clear all animation queues immediately.

        Use this when the Execution-phase Play button is clicked so the
        InitialPlacement pulse/highlight does not keep running during dice roll
        and normal execution.

        Does **not** clear ``dcard_header_play_fx`` (full seat-turn one-play cue).
        """
        self.animations_enabled = False
        self.animate_queue_elements.clear()

        if redraw_board:
            try:
                self.draw_board_base(self.game.board)
                self.draw_all_permanent_buildings(self.game.board)
            except Exception:
                pass

        try:
            pygame.display.update()
        except Exception:
            pass

    def resume_animations(self) -> None:
        """Allow animation again for future placement/selection flows."""
        self.animations_enabled = True

    def play_dice_roll_sound(self) -> None:
        """Play dice-roll sound if the asset was loaded (no-op when headless)."""
        try:
            from gui.gui_constants import play_sound

            play_sound("DICEROLL")
        except Exception:
            pass

    def _dice_surface(self, value: int):
        """Return the pygame surface for die value 1..6."""
        key = f"DICE_{int(value)}"
        image_info = IMAGES.get(key, {})
        return image_info.get("default")

    def _dice_pair_from_total(self, total: int) -> Tuple[int, int]:
        """Fallback for callers that only know the dice total."""
        total = int(total)
        pairs = [(a, total - a) for a in range(1, 7) if 1 <= total - a <= 6]
        if not pairs:
            return (1, 1)
        # Deterministic middle pair, not random; real rolls should pass (d1, d2).
        return pairs[len(pairs) // 2]

    def show_dices(self, dice_or_total, second_die: Optional[int] = None) -> None:
        """Display two dice in the left panel, v045-style.

        Preferred call:
            gui.show_dices((die1, die2))

        Compatibility call:
            gui.show_dices(total)
        """
        if second_die is not None:
            dice = (int(dice_or_total), int(second_die))
        elif isinstance(dice_or_total, (tuple, list)) and len(dice_or_total) >= 2:
            dice = (int(dice_or_total[0]), int(dice_or_total[1]))
        else:
            dice = self._dice_pair_from_total(int(dice_or_total or 2))

        self.last_dice_roll = dice

        # Same general location as v045: left panel, y≈380, two dice side by side.
        x1, x2, y = 20, 110, 380
        clear_rect = LEFT_DICE_PANEL_RECT.copy()
        pygame.draw.rect(WIN, COLORS["LGRAY"], clear_rect)

        surface1 = self._dice_surface(dice[0])
        surface2 = self._dice_surface(dice[1])

        if surface1 is not None:
            WIN.blit(surface1, (x1, y))
        else:
            text = Font.LARGE.value["regular"].render(str(dice[0]), True, COLORS["BLACK"])
            WIN.blit(text, (x1 + 25, y + 20))

        if surface2 is not None:
            WIN.blit(surface2, (x2, y))
        else:
            text = Font.LARGE.value["regular"].render(str(dice[1]), True, COLORS["BLACK"])
            WIN.blit(text, (x2 + 25, y + 20))

        pygame.display.update(clear_rect)

    def _tile_is_robber_blocked(self, tile: Any) -> bool:
        """Return True when the tile currently holds the robber."""
        return bool(
            getattr(tile, "occupied_tf", False)
            or str(getattr(tile, "face", "")) == "Robber"
        )

    def show_tiles_providing_RP(
        self,
        myboard: Board,
        DR: int,
        clearYN: str = "N",
        *,
        tile_ids: Optional[List[int]] = None,
    ) -> None:
        """Highlight tiles that produced resources for the latest dice roll.

        v045 used show_tiles_providing_RP() to append [tile_center, GREEN, 60]
        to a tile animation queue. This version does the same conceptual thing:
        it leaves resource tiles in the normal active animation queue so the
        existing road/intersection animator keeps rotating the white 25% gap.
        """
        if myboard is None:
            return

        try:
            roll = int(DR)
        except Exception:
            return

        selected_tile_ids = set()
        if tile_ids is not None:
            for item in tile_ids:
                try:
                    selected_tile_ids.add(int(item))
                except Exception:
                    continue

        highlights: List[Tuple[Tuple[int, int], Tuple[int, int, int], int, str]] = []
        for tile in getattr(myboard, "tiles", []) or []:
            if tile is None:
                continue
            tile_id = getattr(tile, "id", None)
            if selected_tile_ids:
                try:
                    if int(tile_id) not in selected_tile_ids:
                        continue
                except Exception:
                    continue
            elif getattr(tile, "value", None) != roll:
                continue

            if self._tile_is_robber_blocked(tile):
                continue
            if getattr(tile, "type", None) in (None, "Sea", "Desert", "Blank"):
                continue

            center = convert_tile(int(tile_id)) if tile_id is not None else None
            if center is not None:
                highlights.append((center, COLORS["GREEN"], RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS, "tile"))

        if not highlights:
            return

        if str(clearYN).upper() == "Y":
            try:
                self.draw_board_base(myboard)
                self.draw_all_permanent_buildings(myboard)
            except Exception:
                pass

        self._animate_resource_production_highlights(highlights)

    def _animate_resource_production_highlights(
        self,
        highlights: List[Tuple[Tuple[int, int], Tuple[int, int, int], int, str]],
    ) -> None:
        """Queue resource-production tiles using the exact normal animation mechanics.

        Consistency rule: intersections, roads and tiles all use the same
        self.animate_queue_elements list and the same _animate_elements /
        animate_continuous drawing loop. Resource production is therefore not a
        separate animation kind anymore. It is just a normal tile highlight:

            (tile_center, GREEN, 60, "tile")

        The only visual difference is the larger radius and green color. The
        animator recognises that visual combination only to clear the moving
        25% gap in white, preserving the intended green/white RP cue while
        keeping the same queue, timing, persistence and line width mechanics as
        roads/intersections.
        """
        if not highlights:
            return

        def _is_resource_production_tile(item) -> bool:
            try:
                center, color, radius, kind = item
                return (
                    kind == "tile"
                    and tuple(color) == tuple(COLORS["GREEN"])
                    and int(radius) == int(RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS)
                )
            except Exception:
                return False

        # Remove only previous RP tile highlights; keep current road/intersection
        # highlights if they are still intentionally visible.
        existing = [
            item for item in (getattr(self, "animate_queue_elements", []) or [])
            if not _is_resource_production_tile(item)
        ]

        resource_items = [
            (tuple(center), tuple(color), int(radius), "tile")
            for center, color, radius, _kind in highlights
        ]

        self.animate_queue_elements = existing + resource_items
        self.animations_enabled = True

        # Same immediate reveal mechanic as queue_latest_placement(): queue first,
        # then run _animate_elements once. The main loop can keep pulsing via
        # animate_continuous() because the queue persists.
        self._animate_elements(getattr(self.game, "board", None))

    def _remove_matching_animation_items(self, predicate) -> None:
        """Remove queued animation items matching a predicate, defensively."""
        try:
            self.animate_queue_elements = [
                item for item in (getattr(self, "animate_queue_elements", []) or [])
                if not predicate(item)
            ]
        except Exception:
            pass

    def _draw_robber_on_tile(self, tile_id: int) -> None:
        """Draw the robber image centered on a tile, v045 style."""
        center = convert_tile(int(tile_id))
        if center is None:
            return

        image = IMAGES.get("ROBBER", {}).get("default")
        if image is not None:
            rect = image.get_rect(center=center)
            WIN.blit(image, rect)
        else:
            # Fallback if the PNG is unavailable: keep a visible robber marker.
            pygame.draw.circle(WIN, COLORS["BLACK"], center, 18, 2)
            marker = Font.SMALL.value["bold"].render("R", True, COLORS["BLACK"])
            WIN.blit(marker, marker.get_rect(center=center))

    def draw_robber_from_board(self, board: Board) -> None:
        """Draw the current robber image from board tile state, if present."""
        if board is None:
            return
        for tile in getattr(board, "tiles", []) or []:
            if tile is None:
                continue
            if self._tile_is_robber_blocked(tile):
                tile_id = getattr(tile, "id", None)
                if tile_id is not None:
                    try:
                        self._draw_robber_on_tile(int(tile_id))
                    except Exception:
                        pass
                return

    def show_tile_having_robber(self, myboard: Board, tile_id: int, newYN: str = "Y") -> None:
        """Show robber.png on a tile and animate a v045-style white radius-60 tile ring.

        v045 look-and-feel:
            WIN.blit(IMAGE_Robber, tile_center - 20)
            animate_queue_tiles.append([tile_center, WHITE, 60])

        New implementation:
            use the same normal animate_queue_elements mechanics as roads/intersections:
            (tile_center, WHITE, ROBBER_TILE_HIGHLIGHT_RADIUS, "tile")
        """
        try:
            tile_id = int(tile_id)
        except Exception:
            return

        center = convert_tile(tile_id)
        if center is None:
            return

        self._draw_robber_on_tile(tile_id)

        if str(newYN).upper() == "Y":
            def _is_old_robber_tile(item) -> bool:
                try:
                    _center, color, radius, kind = item
                    return (
                        kind == "tile"
                        and tuple(color) == tuple(COLORS["WHITE"])
                        and int(radius) == int(ROBBER_TILE_HIGHLIGHT_RADIUS)
                    )
                except Exception:
                    return False

            self._remove_matching_animation_items(_is_old_robber_tile)
            self.animate_queue_elements.append((tuple(center), COLORS["WHITE"], ROBBER_TILE_HIGHLIGHT_RADIUS, "tile"))
            self.animations_enabled = True
            self._animate_elements(myboard or getattr(self.game, "board", None))

        try:
            pygame.display.update(PLAYBOARD_RECT)
        except Exception:
            pygame.display.flip()

    def show_victim_of_steal(self, myboard: Board, intersection_ids) -> None:
        """Animate red radius-20 rings on intersections belonging to the robbed player.

        v045 drew a red circle and appended the corner/intersection to the TW animation
        queue. This version uses the normal intersection animation mechanics:
        (intersection_pos, RED, VICTIM_STEAL_HIGHLIGHT_RADIUS, "settlement").
        """
        if intersection_ids is None:
            return
        if not isinstance(intersection_ids, (list, tuple, set)):
            intersection_ids = [intersection_ids]

        # A final victim cue replaces the temporary player-colored choice cues.
        # Remove old red victim cues too so redraws do not duplicate queue items.
        try:
            self._remove_available_robber_choice_highlights()
            self._remove_matching_animation_items(
                lambda item: (
                    len(item) >= 4
                    and item[3] in {"settlement", "city"}
                    and int(item[2]) == int(VICTIM_STEAL_HIGHLIGHT_RADIUS)
                    and tuple(item[1]) == tuple(COLORS["RED"])
                )
            )
        except Exception:
            pass

        queued = False
        for inter_id in intersection_ids:
            try:
                inter_id = int(inter_id)
            except Exception:
                continue
            pos = POSITIONS["intersections"].get(inter_id)
            if not pos:
                continue
            pygame.draw.circle(WIN, COLORS["RED"], pos, VICTIM_STEAL_HIGHLIGHT_RADIUS, 2,
                               draw_top_right=True, draw_top_left=True,
                               draw_bottom_right=True, draw_bottom_left=True)
            self.animate_queue_elements.append((tuple(pos), COLORS["RED"], VICTIM_STEAL_HIGHLIGHT_RADIUS, "settlement"))
            queued = True

        if queued:
            self.animations_enabled = True
            self._animate_elements(myboard or getattr(self.game, "board", None))
            try:
                pygame.display.update(PLAYBOARD_RECT)
            except Exception:
                pygame.display.flip()

    def _current_player_animation_color(self):
        """Return the current player's RGB color for v045-style human choices."""
        try:
            player = self.game.get_current_player()
        except Exception:
            player = None
        color = getattr(player, "color", None)
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            try:
                return tuple(int(x) for x in color[:3])
            except Exception:
                pass
        name = str(color or "").upper()
        if name in COLORS:
            return COLORS[name]
        title_name = str(color or "").title().upper()
        if title_name in COLORS:
            return COLORS[title_name]
        return COLORS.get("BLUE", (0, 0, 255))

    def _remove_available_robber_choice_highlights(self) -> None:
        """Remove transient human-choice highlights, keeping final robber/victim cues."""
        def _is_available_choice(item) -> bool:
            try:
                _center, color, radius, kind = item
                radius = int(radius)
                if kind == "tile" and radius == int(ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS):
                    return True
                if kind in {"settlement", "city"} and radius == int(ROBBER_AVAILABLE_STEAL_TARGET_RADIUS) and tuple(color) != tuple(COLORS["RED"]):
                    return True
            except Exception:
                return False
            return False
        self._remove_matching_animation_items(_is_available_choice)

    def show_available_robber_tiles(self, myboard: Board, tile_ids) -> None:
        """Show legal human robber-tile choices using v045 player-colored tile rings.

        v045 mode "Show_available_tiles_for_steal" drew radius-35 circles in
        the current player's color and queued them as tile animations. This is
        the same look & feel, now through animate_queue_elements.
        """
        if tile_ids is None:
            return
        if not isinstance(tile_ids, (list, tuple, set)):
            tile_ids = [tile_ids]

        self._remove_available_robber_choice_highlights()
        color = self._current_player_animation_color()
        queued = False
        seen = set()
        for tile_id in tile_ids:
            try:
                tile_id = int(tile_id)
            except Exception:
                continue
            if tile_id in seen:
                continue
            seen.add(tile_id)
            center = convert_tile(tile_id)
            if center is None:
                continue
            pygame.draw.circle(WIN, color, center, ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS, 2,
                               draw_top_right=True, draw_top_left=True,
                               draw_bottom_right=True, draw_bottom_left=True)
            self.animate_queue_elements.append((tuple(center), color, ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS, "tile"))
            queued = True

        if queued:
            self.animations_enabled = True
            self._animate_elements(myboard or getattr(self.game, "board", None))
            try:
                pygame.display.update(PLAYBOARD_RECT)
            except Exception:
                pygame.display.flip()

    def show_available_steal_opponents(self, myboard: Board, opponents) -> None:
        """Show human steal-target choices using player-colored intersection rings.

        This mirrors v045's "Show_available_TWs_for_steal": the current
        player's color marks clickable victim intersections. After a target is
        chosen, show_victim_of_steal() changes the selected victim to red.
        """
        if not opponents:
            return

        self._remove_available_robber_choice_highlights()
        color = self._current_player_animation_color()
        queued = False
        seen = set()
        for row in list(opponents or []):
            if not isinstance(row, dict):
                continue
            for inter_id in list(row.get("adjacent_intersections", []) or []):
                try:
                    inter_id = int(inter_id)
                except Exception:
                    continue
                if inter_id in seen:
                    continue
                seen.add(inter_id)
                pos = POSITIONS["intersections"].get(inter_id)
                if not pos:
                    continue
                pygame.draw.circle(WIN, color, pos, ROBBER_AVAILABLE_STEAL_TARGET_RADIUS, 2,
                                   draw_top_right=True, draw_top_left=True,
                                   draw_bottom_right=True, draw_bottom_left=True)
                self.animate_queue_elements.append((tuple(pos), color, ROBBER_AVAILABLE_STEAL_TARGET_RADIUS, "settlement"))
                queued = True

        if queued:
            self.animations_enabled = True
            self._animate_elements(myboard or getattr(self.game, "board", None))
            try:
                pygame.display.update(PLAYBOARD_RECT)
            except Exception:
                pygame.display.flip()

    def play_robber_sound(self) -> None:
        """Play the special 7/robber sound. Uses DANGER, matching existing assets."""
        try:
            from gui.gui_constants import play_sound

            play_sound("DANGER", fallback="ERROR")
        except Exception:
            pass

    def _animate_elements(self, board: Board) -> None:
        """Unified animation for settlements, cities, roads and tiles using quarter-circle reveal."""
        if not self.animations_enabled:
            return
        if not self.animate_queue_elements:
            return

        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"gui.py | _animate_elements | Queue size: {len(self.animate_queue_elements)}\n")

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui.py | _animate_elements | Animating {len(self.animate_queue_elements)} elements\n")

        for step in range(4):
            quadrants = [
                (True,  True,  True,  False),   # 0: top-right
                (True,  False, True,  True),    # 1: top-left
                (False, True,  True,  True),    # 2: bottom-right
                (True,  True,  False, True),    # 3: bottom-left
            ]

            draw_tr, draw_tl, draw_br, draw_bl = quadrants[step]

            for center, color, diameter, kind in self.animate_queue_elements:
                width = 2  # same thickness for intersections, roads and tiles

                # Clear previous animation frame (use background-appropriate color).
                # Resource production is a normal tile animation. Its green/radius-60
                # visual clears with white to keep the RP cue; otherwise all items
                # use the same road/intersection clear logic.
                is_resource_production_tile = (
                    kind == "tile"
                    and tuple(color) == tuple(COLORS["GREEN"])
                    and int(diameter) == int(RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS)
                )
                clear_color = COLORS["WHITE"] if is_resource_production_tile else (COLORS["WHITE"] if color == COLORS["BLUE"] else COLORS["BLUE"])
                pygame.draw.circle(WIN, clear_color, center, diameter, width,
                                draw_top_right=True, draw_top_left=True,
                                draw_bottom_right=True, draw_bottom_left=True)

                # Draw current quadrant
                pygame.draw.circle(WIN, color, center, diameter, width,
                                draw_top_right=draw_tr, draw_top_left=draw_tl,
                                draw_bottom_right=draw_br, draw_bottom_left=draw_bl)

    def animate_continuous(self):
        """Very conservative continuous animation.
        - Disabled completely during InitialPlacement
        - Only animates newest-looking items
        - Auto-clears queue when suspicious
        - Always redraws DCard header play pulse when armed (full seat-turn)
        """
        # Header play pulse is independent of board queue / animations_enabled
        # so robber/build clears never kill the one-play-per-turn cue.
        try:
            self.draw_dcard_header_play_pulse()
        except Exception:
            pass

        if not self.animations_enabled:
            return
        if not self.animate_queue_elements:
            return

        # Disable pulsing entirely during setup phase (cleanest look)
        # if self.game.phase == "InitialPlacement":
        #     return

        # Quick check: does queue look like it contains current game objects?
        has_valid = any(
            len(item) >= 4 and item[3] in ("settlement", "city", "road", "tile")
            for item in self.animate_queue_elements
        )

        if not has_valid:
            self.animate_queue_elements.clear()
            print("Cleared animate_queue_elements due to invalid contents")
            return

        quadrants = [
            (True,  True,  True,  False),
            (True,  False, True,  True),
            (False, True,  True,  True),
            (True,  True,  False, True),
        ]

        # Normal smooth quadrant animation
        # step = (pygame.time.get_ticks() // 80) % 4
        for step in range(4):

            draw_tr, draw_tl, draw_br, draw_bl = quadrants[step]

            for center, color, diameter, kind in self.animate_queue_elements:
                width = 2  # same thickness for intersections, roads and tiles

                # Clear previous animation frame (use background-appropriate color).
                # Resource production is a normal tile animation. Its green/radius-60
                # visual clears with white to keep the RP cue; otherwise all items
                # use the same road/intersection clear logic.
                is_resource_production_tile = (
                    kind == "tile"
                    and tuple(color) == tuple(COLORS["GREEN"])
                    and int(diameter) == int(RESOURCE_PRODUCTION_HIGHLIGHT_RADIUS)
                )
                clear_color = COLORS["WHITE"] if is_resource_production_tile else (COLORS["WHITE"] if color == COLORS["BLUE"] else COLORS["BLUE"])
                pygame.draw.circle(WIN, clear_color, center, diameter, width,
                                draw_top_right=True, draw_top_left=True,
                                draw_bottom_right=True, draw_bottom_left=True)

                # Draw current quadrant
                pygame.draw.circle(WIN, color, center, diameter, width,
                                draw_top_right=draw_tr, draw_top_left=draw_tl,
                                draw_bottom_right=draw_br, draw_bottom_left=draw_bl)

            pygame.display.flip() 
            pygame.time.delay(100)

    def set_button(self, name: str, display_tf: bool) -> None:
        """Set button state. Creates the button if it does not exist yet."""

        if FNFREQ=="Y":
            f= open(FILENAME_Freq,"a")
            f.write("gui.py | set_button"+"\n")
            f.close()

        found=False
        for button in self.buttons:
            if button.name == name:
                if button.display_tf==display_tf:
                    button.switched_tf=False
                else:
                    button.switched_tf=True
                button.display_tf=display_tf
                found=True
        if found == False:
            self.buttons.append(Button(name, display_tf))

    def check_button(self, name: str) -> bool:
        """Check if a button is set to display."""
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("gui.py | check_button\n")
        for button in self.buttons:
            if button.name == name:
                return button.display_tf
        return False

    def check_mode(self, name: str) -> bool:
        """Return True when a named UI mode is active."""
        try:
            return str(name) in {str(mode) for mode in list(getattr(self, "modes", []) or [])}
        except Exception:
            return False

    def set_mode(self, name: str, active: bool = True, source: str = "") -> None:
        """Enable or disable a named UI mode.

        The old v045 UI used lightweight named modes such as
        ``Show_available_roads``.  The modern GUI had a stub check_mode(),
        which meant guidance modes could not reliably disable normal buttons.
        Keep this tiny and generic so older mode names keep working.
        """
        mode = str(name or "")
        if not mode:
            return
        try:
            current = [str(x) for x in list(getattr(self, "modes", []) or [])]
        except Exception:
            current = []
        if bool(active):
            if mode not in current:
                current.append(mode)
        else:
            current = [x for x in current if x != mode]
        self.modes = current

    def set_mode_duo(self, mode1: str, mode2: str, source: str) -> None:
        """Compatibility helper: disable one mode and enable another."""
        self.set_mode(mode1, False, source)
        self.set_mode(mode2, True, source)

    def display_fresh_board(self, board: Board, scoreboard_tf: bool = False) -> None:
        """Render the initial empty board and optionally the scoreboard."""
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("gui.py | display_fresh_board\n")
        WIN.fill(COLORS["LGRAY"], PLAYBOARD_RECT)
        self._draw_hexagon_lines(board)
        self._draw_tiles(board)
        self._draw_tile_values(board)
        self._draw_ports(board)
        self._draw_intersections(board)
        if scoreboard_tf:
            self.display_scoreboard()
        pygame.display.update()
        self.draw_guidance()

    def _draw_hexagon_lines(self, board: Board) -> None:
        """Draw lines connecting intersections to form hexagons."""
        if not pygame.display.get_init():
            return
        for road in board.roads:
            if road and road.id:
                start_id, end_id = road.id
                start_pos = POSITIONS["intersections"].get(start_id, None)
                end_pos = POSITIONS["intersections"].get(end_id, None)
                if start_pos is None or end_pos is None:
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            if start_pos is None:
                                f.write(f"gui.py | _draw_hexagon_lines | No coordinates for intersection ID: {start_id}\n")
                            if end_pos is None:
                                f.write(f"gui.py | _draw_hexagon_lines | No coordinates for intersection ID: {end_id}\n")
                    continue
                pygame.draw.line(WIN, COLORS["BLACK"], start_pos, end_pos, 2)

    def _draw_tiles(self, board: Board) -> None:
        """Draw hexagonal tiles on the board."""
        rendered_tiles = []
        for tile in board.tiles:
            if tile and tile.id in POSITIONS["tiles"]:
                pos = convert_tile(tile.id)
                if pos is None:
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            f.write(f"gui.py | _draw_tiles | No coordinates for tile ID: {tile.id}\n")
                    continue
                # Gen2 empty-board: Blank land = LGRAY placeholder (not Sea art)
                ty = str(getattr(tile, "type", "") or "")
                if ty in ("Blank", "", "None"):
                    try:
                        pygame.draw.rect(
                            WIN,
                            COLORS.get("LGRAY", (200, 200, 200)),
                            (pos[0] - 18, pos[1] - 18, 36, 36),
                        )
                        pygame.draw.rect(
                            WIN,
                            COLORS.get("DGRAY", (100, 100, 100)),
                            (pos[0] - 18, pos[1] - 18, 36, 36),
                            1,
                        )
                        rendered_tiles.append(tile.id)
                    except Exception:
                        pass
                    continue
                image_key = {
                    "Field": "FIELD",
                    "Mountain": "MOUNTAIN",
                    "Forest": "FOREST",
                    "Hill": "HILL",
                    "Pasture": "PASTURE",
                    "Desert": "DESERT",
                    "Sea": "SEA",
                    "Water": "SEA",
                }.get(ty, "SEA")
                image = IMAGES[image_key]["40x40"] if image_key in ["FIELD", "MOUNTAIN", "FOREST", "HILL", "PASTURE"] else IMAGES[image_key]["default"]
                if image is not None:
                    WIN.blit(image, (pos[0] - 20, pos[1] - 20))
                    rendered_tiles.append(tile.id)
                else:
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            f.write(f"gui.py | _draw_tiles | Failed to render tile ID: {tile.id}, Type: {tile.type}, Pos: {pos}\n")
            else:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_tiles | Skipped tile ID: {tile.id if tile else None}, Pos: {convert_tile(tile.id) if tile else None}\n")
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui.py | _draw_tiles | Rendered tile IDs: {rendered_tiles}\n")

    def _draw_tile_values(self, board: Board) -> None:
        """Draw number chits on tiles."""
        font = Font.LARGE.value["regular"]
        for tile in board.tiles:
            if tile and tile.id in POSITIONS["tiles"] and tile.value != 0:
                pos = convert_tile(tile.id)
                if pos is None:
                    continue
                color = COLORS["RED"] if tile.value in [6, 8] else COLORS["BLACK"]
                text = font.render(str(tile.value), True, color)
                WIN.blit(text, (pos[0] - 8, pos[1] + 15))

    def _draw_ports(self, board: Board) -> None:
        """Draw port icons, circles, and lines on the board."""
        font = Font.SMALL.value["regular"]
        port_intersection_ids = set()
        for port_pair in board.INTERSECTIONS_ARE_PORT:
            port_intersection_ids.update(port_pair)
        for intersection_id in port_intersection_ids:
            if intersection_id in board.INTERSECTION_IN_WATER or board.intersections[intersection_id] is None:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_ports | Skipping None or water intersection ID: {intersection_id}\n")
                continue
            pos = POSITIONS["intersections"].get(intersection_id, None)
            if pos is None:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_ports | No coordinates for intersection ID: {intersection_id}\n")
                continue
            pygame.draw.circle(WIN, COLORS["BLACK"], pos, 5, 0)
        for port_pair in board.INTERSECTIONS_ARE_PORT:
            first_intersection_id = port_pair[0]
            second_intersection_id = port_pair[1]
            if (first_intersection_id in board.INTERSECTION_IN_WATER or 
                second_intersection_id in board.INTERSECTION_IN_WATER or
                board.intersections[first_intersection_id] is None or
                board.intersections[second_intersection_id] is None):
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_ports | Skipping port pair {port_pair} due to None or water intersections\n")
                continue
            first_intersection = next((i for i in board.intersections if i is not None and i.id == first_intersection_id), None)
            if not first_intersection:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_ports | No valid intersection found for ID: {first_intersection_id}\n")
                continue
            sea_tile_id = None
            for tile in board.tiles:
                if tile and tile.type == "Sea":
                    corner_intersections = [corner.intersection for corner in tile.corners]
                    if first_intersection_id in corner_intersections and second_intersection_id in corner_intersections:
                        sea_tile_id = tile.id
                        break
            if sea_tile_id is None:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_ports | No sea tile found for port pair: {port_pair}\n")
                continue
            pos = convert_tile(sea_tile_id)
            if pos is None:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui.py | _draw_ports | No coordinates for sea tile id: {sea_tile_id}\n")
                continue
            first_intersection_pos = POSITIONS["intersections"].get(first_intersection_id, None)
            second_intersection_pos = POSITIONS["intersections"].get(second_intersection_id, None)
            if first_intersection_pos:
                pygame.draw.line(WIN, COLORS["BLACK"], first_intersection_pos, pos, 2)
            if second_intersection_pos:
                pygame.draw.line(WIN, COLORS["BLACK"], second_intersection_pos, pos, 2)
            # Normalize legacy aliases so "2:1 Wool" still draws the pasture icon.
            port_type = str(getattr(first_intersection, "port_type", "") or "Blank")
            if port_type in {"2:1 Wool", "2:1 wool", "2:1 sheep"}:
                port_type = "2:1 Sheep"
            elif port_type in {"2:1 Grain", "2:1 grain", "2:1 wheat"}:
                port_type = "2:1 Wheat"
            elif port_type in {"2:1 Lumber", "2:1 lumber", "2:1 wood"}:
                port_type = "2:1 Wood"
            elif port_type in {"2:1 Clay", "2:1 clay", "2:1 brick"}:
                port_type = "2:1 Brick"
            elif port_type in {"2:1 ore"}:
                port_type = "2:1 Ore"

            # Default unset / Blank harbors as 3:1 (no "?" placeholder)
            if port_type in ("Blank", "", "None", "?", " ?"):
                port_type = "3:1"
            if port_type == "3:1":
                pygame.draw.rect(WIN, COLORS["WHITE"], [pos[0] - 10, pos[1] - 10, 20, 20])
                text = font.render("3:1", True, COLORS["BLACK"])
                WIN.blit(text, (pos[0] - 7, pos[1] - 8))
            else:
                image_key = {
                    "2:1 Wheat": "FIELD",
                    "2:1 Ore": "MOUNTAIN",
                    "2:1 Wood": "FOREST",
                    "2:1 Brick": "HILL",
                    "2:1 Sheep": "PASTURE",
                }.get(port_type)
                if image_key:
                    image = IMAGES[image_key]["20x20"]
                    if image is not None:
                        WIN.blit(image, (pos[0] - 10, pos[1] - 10))
                    else:
                        if MG:
                            with open(FILENAME_MG, "a") as f:
                                f.write(
                                    f"gui.py | _draw_ports | Missing image for port type: "
                                    f"{port_type}, Tile ID: {sea_tile_id}\n"
                                )
                else:
                    # Unknown type: fall back to 3:1 label (not "?")
                    pygame.draw.rect(WIN, COLORS["WHITE"], [pos[0] - 10, pos[1] - 10, 20, 20])
                    text = font.render("3:1", True, COLORS["BLACK"])
                    WIN.blit(text, (pos[0] - 7, pos[1] - 8))

    def _draw_intersections(self, board: Board) -> None:
        """Draw intersections (vertices) on the board with bold IDs."""
        font = Font.SMALL.value["bold"]
        offset_minus_3 = {4, 6, 8}
        offset_minus_6 = {59, 61, 63}
        for intersection in board.intersections:
            if intersection is None or intersection.id in board.INTERSECTION_IN_WATER:
                continue
            if intersection.id in POSITIONS["intersections"]:
                pos = POSITIONS["intersections"][intersection.id]
                text = font.render(str(intersection.id), True, COLORS["DGRAY"])
                y_offset = -16 if intersection.id in {14, 16, 18, 20, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 58, 60, 62, 64} else 2
                x_offset = -3 if intersection.id in offset_minus_3 else -6 if intersection.id in offset_minus_6 else 4
                WIN.blit(text, (pos[0] + x_offset, pos[1] + y_offset))

    def display_scoreboard(self) -> None:
        """Display the empty scoreboard (placeholder)."""
        pass

    def _occupy_settlement_in_gui(self, board: Board, intersection_id: int, color: str) -> None:
        pos = POSITIONS["intersections"].get(intersection_id)
        if not pos: return
        image = IMAGES.get(f"SETTLEMENT_{color.upper()}", {}).get("30x30")
        if image:
            WIN.blit(image, (pos[0] - 15, pos[1] - 15))

    def _occupy_road_in_gui(self, board: Board, road_id: Tuple[int, int], color: str) -> None:
        pos1 = POSITIONS["intersections"].get(road_id[0])
        pos2 = POSITIONS["intersections"].get(road_id[1])
        if pos1 and pos2:
            pygame.draw.line(WIN, COLORS[color.upper()], pos1, pos2, 5)

    def _occupy_city_in_gui(self, board: Board, intersection_id: int, color: str) -> None:
        pos = POSITIONS["intersections"].get(intersection_id)
        if not pos: return
        image = IMAGES.get(f"CITY_{color.upper()}", {}).get("30x30")
        if image:
            WIN.blit(image, (pos[0] - 15, pos[1] - 15))

    def draw_board_base(self, board: Board) -> None:
        """Static empty board only (tiles, lines, numbers, ports, intersection IDs)."""
        WIN.fill(COLORS["LGRAY"], PLAYBOARD_RECT)
        self._draw_hexagon_lines(board)
        self._draw_tiles(board)
        self._draw_tile_values(board)
        self._draw_ports(board)
        self._draw_intersections(board)

    def draw_all_permanent_buildings(self, board: Board, block_visual: bool = False):
        """Draw EVERY currently placed road/settlement/city + blocked dots."""
        # Roads
        for road in board.roads:
            if road and road.occupied_tf:
                self._occupy_road_in_gui(board, road.id, road.color)  # simplified version below

        # Settlements & Cities
        for inter in board.intersections:
            if inter and inter.occupied_tf:
                if inter.face == "Settlement":
                    self._occupy_settlement_in_gui(board, inter.id, inter.color)
                elif inter.face == "City":
                    self._occupy_city_in_gui(board, inter.id, inter.color)

        # Blocked dots (adjacent to any settlement)
        for inter in board.intersections:
                if inter and inter.occupied_tf:
                    self._block_adjacent_in_gui(board, inter.id, block_visual=block_visual)

        # Robber image is a permanent board element once placed.
        self.draw_robber_from_board(board)

    def save_screenshot(self, filename: str = "", *, name_prefix: str = "Catan_Screenshot") -> str:
        """Save a screenshot of the game window to SAVE_PATH with a timestamp.

        Returns the path written (empty string on failure).
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(SAVE_PATH, f"{name_prefix}_{timestamp}.png")
        Path(SAVE_PATH).mkdir(parents=True, exist_ok=True)
        try:
            pygame.image.save(WIN, filename)
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"gui.py | save_screenshot | Saved to {filename}\n")
            return str(filename)
        except pygame.error as e:
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"gui.py | save_screenshot | Error saving screenshot to {filename}: {e}\n")
            return ""

    def update_round_turn(self, game: Game, special: bool) -> None:
        """
        Update the round and turn display in the GUI.
        Also syncs internal round/turn values used for animation filtering.

        F3: for reverse IP (round == -1), the **displayed** turn is
        ``(n_players+1) - mglog_turn`` so sequence order reads 1..n left-to-right
        while MGlog still stores turn=player_id (chrono T4→…→T1). Color follows
        the acting seat (player_id), not the remapped display turn.
        """
        # Critical: sync GUI's round & turn with game state (raw MGlog / engine)
        # This makes sure update_board's "this turn only" filter works correctly
        self.round = game.round
        self.turn = game.turn

        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"gui.py | update_round_turn\n")

        # Clear only the Round/Turn band (do not wipe guidance or Resource Potential)
        pygame.draw.rect(WIN, COLORS["LGRAY"], ROUND_TURN_RECT)

        help_round = game.round
        help_turn = game.turn
        try:
            n_players = len(list(getattr(game, "players", None) or [])) or 4
        except Exception:
            n_players = 4
        try:
            from core.mglog_replay import reverse_ip_display_turn

            disp_turn = reverse_ip_display_turn(
                help_round, help_turn, n_players=n_players
            )
            if disp_turn is not None:
                help_turn = disp_turn
        except Exception:
            pass

        # Color by acting player (structure seat), not by remapped display turn
        seat_for_color = None
        try:
            cur = game.get_current_player()
            if cur is not None:
                seat_for_color = int(getattr(cur, "id", 0) or 0) or None
        except Exception:
            seat_for_color = None
        if seat_for_color is None:
            try:
                # MGlog: turn field is player_id even in reverse IP
                seat_for_color = int(game.turn)
            except Exception:
                seat_for_color = None
        color = {1: "BLUE", 2: "RED", 3: "WHITE", 4: "ORANGE"}.get(
            seat_for_color, "BLACK"
        )
        font = Font.LARGE.value["regular"]
        turn_text = font.render(f"Turn: {help_turn}", True, COLORS[color])
        round_text = font.render(f"Round: {help_round}", True, COLORS[color])
        WIN.blit(turn_text, (165, 5))
        WIN.blit(round_text, (15, 5))
        # pygame.display.update()

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(
                    f"gui.py | update_round_turn | Actual: {self.round}, {self.turn} | "
                    f"Display: {help_round}, {help_turn}, Color: {color}, Special: {special}\n"
                )

    def _block_adjacent_in_gui(self, board: Board, intersection_id: int, block_visual: bool = False) -> None:
        """
            Optionally render visual indication of blocked (forbidden) adjacent intersections.

            This method does nothing unless `block_visual=True` is explicitly passed.
            It is meant to highlight intersections that cannot be built on due to adjacency rules.

            Args:
                board: The current game board instance.
                intersection_id: ID of the occupied intersection whose neighbors should be checked.
                block_visual: If True, draw blocking indicators on adjacent valid intersections.
                            Defaults to False (no visual change).
            """
        if not block_visual:
            return  # do nothing by default
        
        # existing blocking/highlighting logic
        intersection = board.intersections[intersection_id]
        if intersection:
            for neighbor_id in intersection.three_intersection_ids:
                if (neighbor_id not in board.INTERSECTION_IN_WATER and
                    board.intersections[neighbor_id] is not None and
                    board.intersections[neighbor_id].can_build_tf):
                    pos = POSITIONS["intersections"].get(neighbor_id)
                    if pos:
                        pygame.draw.circle(WIN, COLORS["BLACK"], pos, 10)

    def queue_latest_placement(self) -> None:
        """
        Populate self.animate_queue_elements with the most recent placement
        using placement_step (works for both AI and human, no more round/turn bugs).
        """
        temp_queue = []
        max_step = -1

        # Find the highest placement_step that was used
        for inter in self.game.board.intersections:
            if inter and inter.occupied_tf and inter.face in ("Settlement", "City"):
                max_step = max(max_step, inter.placement_step)
        for road in self.game.board.roads:
            if road and road.occupied_tf:
                max_step = max(max_step, road.placement_step)

        if max_step == -1:
            print("No placement found to add to animation queue")
            self.animate_queue_elements = []
            return

        # ── Latest settlement/city with this step ─────────────────────────────
        latest_inter = None
        for inter in self.game.board.intersections:
            if (inter and inter.occupied_tf and inter.face in ("Settlement", "City") and
                inter.placement_step == max_step):
                latest_inter = inter
                break

        if latest_inter:
            pos = POSITIONS["intersections"].get(latest_inter.id)
            if pos:
                kind = "settlement" if latest_inter.face == "Settlement" else "city"
                color = COLORS[latest_inter.color.upper()]
                temp_queue.append((pos, color, 20, kind))

                # Second settlement -> highlight resource tiles (setup phase)
                if self.game.round == -1:
                    for tile_id in latest_inter.three_tile_ids:
                        tile = self.game.board.tiles[tile_id]
                        if tile and tile.type not in ("Sea", "Desert"):
                            tile_pos = convert_tile(tile_id)
                            if tile_pos:
                                temp_queue.append((tile_pos, color, 26, "tile"))

        # ── Latest road with this step ───────────────────────────────────────
        latest_road = None
        for road in self.game.board.roads:
            if road and road.occupied_tf and road.placement_step == max_step:
                latest_road = road
                break

        if latest_road:
            pos1 = POSITIONS["intersections"].get(latest_road.id[0])
            pos2 = POSITIONS["intersections"].get(latest_road.id[1])
            if pos1 and pos2:
                mid = ((pos1[0] + pos2[0]) // 2, (pos1[1] + pos2[1]) // 2)
                color = COLORS[latest_road.color.upper()]
                temp_queue.append((mid, color, 20, "road"))

        print(f"Queueing {len(temp_queue)} items for animation queue (step {max_step})")
        for item in temp_queue:
            print(f"  -> {item}")

        self.animate_queue_elements = temp_queue


    def show_execution_build_animation(self, animation: Dict[str, Any], board: Optional[Board] = None) -> None:
        """Animate one newly built Execution-phase road/settlement/city.

        Initial Placement already uses the normal animate_queue_elements +
        _animate_elements mechanics. Execution builds should look the same,
        so this method queues exactly one newly built object and runs the same
        quarter-circle reveal animation.
        """
        if not isinstance(animation, dict):
            return

        board = board or getattr(self.game, "board", None)
        action = str(animation.get("action", "") or "")
        color_name = str(animation.get("color", "") or "").upper()
        color = COLORS.get(color_name, COLORS.get("GREEN", (0, 180, 0)))
        item = None

        try:
            if action in {"Build city", "Build settlement"}:
                target = int(animation.get("target_id"))
                center = POSITIONS["intersections"].get(target)
                if center:
                    kind = "city" if action == "Build city" else "settlement"
                    item = (tuple(center), color, 20, kind)
            elif action == "Build road":
                raw = animation.get("road_id")
                a, b = tuple(raw)[:2]
                pos1 = POSITIONS["intersections"].get(int(a))
                pos2 = POSITIONS["intersections"].get(int(b))
                if pos1 and pos2:
                    center = ((int(pos1[0]) + int(pos2[0])) // 2, (int(pos1[1]) + int(pos2[1])) // 2)
                    item = (center, color, 20, "road")
        except Exception:
            item = None

        if item is None:
            return

        try:
            self.animate_queue_elements = [item]
            self.animations_enabled = True
            self._animate_elements(board)
            pygame.display.update()
        except Exception:
            pass

    def update_board(self, board: Board, update_type: str) -> None:
        """Update the board display based on an action."""
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"gui.py | update_board | type={update_type}\n")

        if update_type == "All":
            # Full board redraw
            self.display_fresh_board(board, scoreboard_tf=True)
        
            # Block adjacent intersections for all existing settlements
            for intersection in board.intersections:
                if intersection and intersection.occupied_tf:
                    self._block_adjacent_in_gui(board, intersection.id)
        
            # Draw all existing roads (permanent)
            for road in board.roads:
                if road.occupied_tf:
                    self._occupy_road_in_gui(board, road.id, road.color)
        
            # Draw all existing settlements and cities (permanent)
            for intersection in board.intersections:
                if intersection and intersection.occupied_tf:
                    if intersection.face == "Settlement":
                        self._occupy_settlement_in_gui(board, intersection.id, intersection.color)
                    elif intersection.face == "City":
                        self._occupy_city_in_gui(board, intersection.id, intersection.color)

        else:  # "Last" — animate and draw only the most recent placement
            self.draw_board_base(board)
            self.draw_all_permanent_buildings(board)

            # ── Find highest placement_step used so far ───────────────────────────
            max_step = -1
            for inter in board.intersections:
                if inter and inter.occupied_tf and inter.face in ("Settlement", "City"):
                    max_step = max(max_step, inter.placement_step)
            for road in board.roads:
                if road and road.occupied_tf:
                    max_step = max(max_step, road.placement_step)

            temp_queue = []

            if max_step == -1:
                print("No placement found to animate this turn (update_board 'Last')")
            else:
                print(f"Animating items for latest placement (step {max_step})")

                # ── Latest settlement/city with this step ─────────────────────────
                latest_inter = None
                for inter in board.intersections:
                    if (inter is not None and
                        inter.occupied_tf and
                        inter.face in ("Settlement", "City") and
                        inter.placement_step == max_step):
                        latest_inter = inter
                        break  # usually only one per step

                if latest_inter:
                    pos = POSITIONS["intersections"].get(latest_inter.id)
                    if pos:
                        kind = "settlement" if latest_inter.face == "Settlement" else "city"
                        color = COLORS[latest_inter.color.upper()]
                        temp_queue.append((pos, color, 20, kind))
                        print(f"  -> {pos} {color} 20 '{kind}'")

                        # Draw it permanently right away
                        if latest_inter.face == "Settlement":
                            self._occupy_settlement_in_gui(board, latest_inter.id, latest_inter.color)
                        else:
                            self._occupy_city_in_gui(board, latest_inter.id, latest_inter.color)

                        # ── Resource tiles highlight on second settlement (round -1) ──
                        if self.round == -1:
                            for tile_id in latest_inter.three_tile_ids:
                                tile = board.tiles[tile_id]
                                if tile and tile.type not in ("Sea", "Desert"):
                                    tile_pos = convert_tile(tile_id)
                                    if tile_pos:
                                        temp_queue.append((tile_pos, color, 26, "tile"))
                                        print(f"  -> {tile_pos} {color} 26 'tile'")

                # ── Latest road with this step ────────────────────────────────────
                latest_road = None
                for road in board.roads:
                    if (road is not None and
                        road.occupied_tf and
                        road.placement_step == max_step):
                        latest_road = road
                        break

                if latest_road:
                    pos1 = POSITIONS["intersections"].get(latest_road.id[0])
                    pos2 = POSITIONS["intersections"].get(latest_road.id[1])
                    if pos1 and pos2:
                        mid = ((pos1[0] + pos2[0]) // 2, (pos1[1] + pos2[1]) // 2)
                        color = COLORS[latest_road.color.upper()]
                        temp_queue.append((mid, color, 20, "road"))
                        print(f"  -> {mid} {color} 20 'road'")

                        # Draw permanently
                        self._occupy_road_in_gui(board, latest_road.id, latest_road.color)

            # Set animation queue (will be used by _animate_elements and animate_continuous)
            self.animate_queue_elements = temp_queue

            # Run the reveal animation immediately (quarter circles)
            if temp_queue:
                self._animate_elements(board)

    # DCard header types (shared strip order) — must match update_scoreboard icons
    DCARD_HEADER_TYPES: Tuple[str, ...] = (
        "victory_point",
        "knight",
        "two_free_roads",
        "year_of_plenty",
        "monopoly",
    )

    def arm_dcard_header_play_fx(
        self,
        card_type: str,
        player: Any = None,
        *,
        player_id: Optional[int] = None,
        color_name: Optional[str] = None,
    ) -> bool:
        """Arm full seat-turn pulse on the shared header icon for ``card_type``.

        Color = structure seat color (same as roads/settles/cities).
        """
        ctype = str(card_type or "").strip().lower().replace(" ", "_")
        aliases = {
            "vp": "victory_point",
            "victorypoint": "victory_point",
            "road_building": "two_free_roads",
            "roads": "two_free_roads",
            "yop": "year_of_plenty",
            "yearofplenty": "year_of_plenty",
        }
        ctype = aliases.get(ctype, ctype)
        if ctype not in self.DCARD_HEADER_TYPES:
            return False

        pid = player_id
        cname = (color_name or "").strip().upper() if color_name else ""
        if player is not None:
            try:
                if pid is None:
                    pid = int(getattr(player, "id", 0) or 0) or None
            except Exception:
                pass
            if not cname:
                cname = str(getattr(player, "color", "") or "").upper()
        if not cname and pid:
            cname = {1: "BLUE", 2: "RED", 3: "WHITE", 4: "ORANGE"}.get(int(pid), "")
        # F5: same structure colors as roads/settles/cities (include WHITE; no DGRAY remap)
        rgb = COLORS.get(cname, COLORS.get("GREEN", (0, 180, 0)))
        try:
            diameter = int(DCARD_HEADER_PLAY_PULSE_RADIUS)
        except Exception:
            diameter = 24
        self.dcard_header_play_fx = {
            "card_type": ctype,
            "player_id": int(pid) if pid else None,
            "color": tuple(int(x) for x in rgb[:3]),
            "diameter": diameter,
            "active": True,
        }
        return True

    def clear_dcard_header_play_fx(self) -> None:
        """Clear header play pulse (seat-turn boundary only)."""
        self.dcard_header_play_fx = None

    def dcard_header_icon_center(self, card_type_or_index: Any) -> Optional[Tuple[int, int]]:
        """Center of a shared DCard header icon."""
        idx = -1
        if isinstance(card_type_or_index, int):
            idx = int(card_type_or_index)
        else:
            ctype = str(card_type_or_index or "").strip().lower().replace(" ", "_")
            try:
                idx = list(self.DCARD_HEADER_TYPES).index(ctype)
            except ValueError:
                return None
        if idx < 0 or idx >= len(DCARD_X_POSITIONS):
            return None
        try:
            cy = int(DCARD_HEADER_ICON_CENTER_Y)
        except Exception:
            cy = 560
        return (int(DCARD_X_POSITIONS[idx]) + 15, cy)

    def draw_dcard_header_play_pulse(self) -> None:
        """Draw one pulse frame on the armed shared header DCard icon."""
        fx = getattr(self, "dcard_header_play_fx", None)
        if not isinstance(fx, dict) or not fx.get("active"):
            return
        center = self.dcard_header_icon_center(fx.get("card_type"))
        if not center:
            return
        color = fx.get("color") or COLORS.get("GREEN", (0, 180, 0))
        try:
            diameter = int(fx.get("diameter") or DCARD_HEADER_PLAY_PULSE_RADIUS)
        except Exception:
            diameter = 24
        try:
            step = (pygame.time.get_ticks() // 100) % 4
        except Exception:
            step = 0
        quadrants = [
            (True, True, True, False),
            (True, False, True, True),
            (False, True, True, True),
            (True, True, False, True),
        ]
        draw_tr, draw_tl, draw_br, draw_bl = quadrants[step]
        try:
            pygame.draw.circle(
                WIN,
                color,
                center,
                int(diameter),
                2,
                draw_top_right=draw_tr,
                draw_top_left=draw_tl,
                draw_bottom_right=draw_br,
                draw_bottom_left=draw_bl,
            )
        except TypeError:
            try:
                pygame.draw.circle(WIN, color, center, int(diameter), 2)
            except Exception:
                pass
        except Exception:
            pass

    def update_scoreboard(self, game: Game) -> None:
        """Render the entire scoreboard with headers and player statistics.

        Args:
            game: The game instance containing player data.
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{game.sequence_number} | {game.state} | gui_game.py | update_scoreboard\n")

        # Resource_exploration (=pips summary
        self.update_resource_exploration(game.board)

        # Scoreboard area
        pygame.draw.rect(WIN, COLORS["LGRAY"], SCOREBOARD_RECT)
       
        # Header: Small "VP" above C, S, R (Longest Route), A, E
        font_small = Font.SMALL.value["regular"]
        vp_columns = [1, 2, 4, 5, 6] # Indices for C, S, R (Longest Route), A, E
        header_x_positions = SCOREBOARD_HEADER_X_POSITIONS
        for i in vp_columns:
            vp_header = font_small.render("VP", True, COLORS["BLACK"])
            vp_rect = vp_header.get_rect(center=(header_x_positions[i] + 10, 550)) # Center for 20-pixel column
            WIN.blit(vp_header, vp_rect)
       
        # Header: Main text and images
        font = Font.NORMAL.value["regular"]
        header_parts = ["VP", "C", "S", "R", "R", "A", "E", "LR", "LA", "RC", "DC"]
        for i, part in enumerate(header_parts):
            text = font.render(part, True, COLORS["BLACK"])
            text_rect = text.get_rect(center=(header_x_positions[i] + 10, 560)) # Center for 20-pixel column
            WIN.blit(text, text_rect)
       
        # RC images (Wheat, Ore, Wood, Brick, Sheep) at 40x40, 5 pixels apart
        rc_images = ["FIELD", "MOUNTAIN", "FOREST", "HILL", "PASTURE"]
        rc_x_positions = RESOURCE_CARD_X_POSITIONS # 40x40 images + 5-pixel gaps
        for i, img_key in enumerate(rc_images):
            try:
                image = IMAGES[img_key]["40x40"]
                if image is not None:
                    img_rect = image.get_rect(center=(rc_x_positions[i] + 20, 560)) # Center for 40x40
                    WIN.blit(image, img_rect)
                else:
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            f.write(f"gui_game.py | update_scoreboard | Missing RC image: {img_key}\n")
            except KeyError:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui_game.py | update_scoreboard | KeyError: No '40x40' for RC image: {img_key}\n")
       
        # Named vertical lines from gui_constants.py. The '?' buttons sit
        # between the resource dashboard and the development-card statistics.
        y1, y2 = SCOREBOARD_RECT.y, SCOREBOARD_RECT.bottom
        pygame.draw.line(WIN, COLORS["BLACK"], (SCOREBOARD_VERTICAL_LINES["before_resource_dashboard"], y1), (SCOREBOARD_VERTICAL_LINES["before_resource_dashboard"], y2), 2)
        pygame.draw.line(WIN, COLORS["BLACK"], (SCOREBOARD_VERTICAL_LINES["after_resource_dashboard"], y1), (SCOREBOARD_VERTICAL_LINES["after_resource_dashboard"], y2), 2)
        pygame.draw.line(WIN, COLORS["BLACK"], (SCOREBOARD_VERTICAL_LINES["before_dcard_statistics"], y1), (SCOREBOARD_VERTICAL_LINES["before_dcard_statistics"], y2), 2)
       
        # DC images (VP, Knight, Road, Plenty, Monopoly) at 30x30, 5 pixels apart.
        # Playable types for the current human get a green border; open panel type gets gold.
        dc_images = ["DC_VPOINT", "DC_KNIGHT", "DC_ROAD", "DC_PLENTY", "DC_MONOPOLY"]
        dc_types = ["victory_point", "knight", "two_free_roads", "year_of_plenty", "monopoly"]
        dc_x_positions = DCARD_X_POSITIONS # 30x30 images + 5-pixel gaps
        try:
            from gui.gui_play_dcard_panel import (
                clear_scoreboard_dcard_hits,
                is_dcard_type_playable_now,
                get_open_play_dcard_type,
                register_scoreboard_dcard_hit,
                DCARD_PLAYABLE_BORDER,
                DCARD_PANEL_OPEN_BORDER,
            )
            clear_scoreboard_dcard_hits(game)
            open_type = get_open_play_dcard_type(game)
        except Exception:
            clear_scoreboard_dcard_hits = None  # type: ignore
            is_dcard_type_playable_now = None  # type: ignore
            open_type = None
            register_scoreboard_dcard_hit = None  # type: ignore
            DCARD_PLAYABLE_BORDER = (0, 200, 0)
            DCARD_PANEL_OPEN_BORDER = (255, 196, 0)

        human_current = None
        try:
            cur = game.get_current_player()
            if cur is not None and bool(getattr(cur, "is_human", False)):
                human_current = cur
        except Exception:
            human_current = None

        for i, img_key in enumerate(dc_images):
            try:
                image = IMAGES[img_key]["30x30"]
                if image is not None:
                    img_rect = image.get_rect(
                        center=(dc_x_positions[i] + 15, int(DCARD_HEADER_ICON_CENTER_Y))
                    )  # Center for 30x30
                    WIN.blit(image, img_rect)
                    card_type = dc_types[i] if i < len(dc_types) else ""
                    playable = False
                    if human_current is not None and is_dcard_type_playable_now is not None:
                        try:
                            playable = bool(is_dcard_type_playable_now(game, human_current, card_type))
                        except Exception:
                            playable = False
                    # VP never playable (no green border)
                    if card_type == "victory_point":
                        playable = False
                    border_color = None
                    if open_type and card_type == open_type:
                        border_color = DCARD_PANEL_OPEN_BORDER
                    elif playable:
                        border_color = DCARD_PLAYABLE_BORDER
                    if border_color is not None:
                        border_rect = img_rect.inflate(6, 6)
                        pygame.draw.rect(WIN, border_color, border_rect, 3)
                    if register_scoreboard_dcard_hit is not None and human_current is not None:
                        try:
                            register_scoreboard_dcard_hit(
                                game,
                                player_id=int(getattr(human_current, "id", 0) or 0),
                                card_type=card_type,
                                rect=img_rect.inflate(8, 8),
                                playable=playable,
                            )
                        except Exception:
                            pass
                else:
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            f.write(f"gui_game.py | update_scoreboard | Missing DC image: {img_key}\n")
            except KeyError:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"gui_game.py | update_scoreboard | KeyError: No '30x30' for DC image: {img_key}\n")
       
        # Player rows
        self.turn_detail_button_rects.clear()
        for i, player in enumerate(game.players):
            self._render_scoreboard_row(player, game, 15, 560 + (i + 1) * 40 - 10, 560 + (i + 1) * 40)

        if self.turn_detail_expanded_player_id is not None:
            self._draw_turn_detail_panel(game, self.turn_detail_expanded_player_id)

        # Full seat-turn header play pulse (after static icons / borders)
        try:
            self.draw_dcard_header_play_pulse()
        except Exception:
            pass
       
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_game.py | update_scoreboard | Rendered scoreboard for {len(game.players)} players\n")

    def _normalise_turn_delta_vector(self, value: Any) -> List[int]:
        """Return a safe 6-slot resource delta vector.

        The current order follows the v045 scoreboard convention:
        [Wheat, Ore, Wood, Brick, Sheep, Gold/unused].
        """
        if not isinstance(value, (list, tuple)):
            return [0, 0, 0, 0, 0, 0]
        result = []
        for item in list(value)[:6]:
            try:
                result.append(int(item or 0))
            except Exception:
                result.append(0)
        while len(result) < 6:
            result.append(0)
        return result

    def _append_missing_resource_production_detail_rows(self, player: Player, rows: List[Tuple[str, List[int]]]) -> List[Tuple[str, List[int]]]:
        """Ensure the '?' popup keeps RP rows even when another row exists.

        The popup is meant to be a detail view, so it must show separate rows
        for resource production, robber-blocked production, steals, buys, etc.
        A structured ledger row such as Steal should never hide the immediate
        RP fallback stored on Game.last_resource_production_result.
        """
        merged: List[Tuple[str, List[int]]] = list(rows or [])
        try:
            existing = {str(label).strip().lower() for label, _ in merged}
        except Exception:
            existing = set()

        produced, blocked = self._last_resource_production_vectors_for_player(player)
        rp_rows: List[Tuple[str, List[int]]] = []
        if any(int(v or 0) != 0 for v in produced) and "rp" not in existing:
            rp_rows.append(("RP", produced))
        if any(int(v or 0) != 0 for v in blocked) and "rp corr" not in existing:
            rp_rows.append(("RP Corr", blocked))

        if not rp_rows:
            return merged

        # Keep production at the top of the details panel, followed by the
        # other current-turn rows such as Steal. This makes a turn with both
        # production and a steal read as two separate lines: RP, then Steal.
        return rp_rows + merged

    # Marker for '?' Steal rows when CHECK_MODE hides AI↔AI resource vectors.
    TURN_DETAIL_STEAL_HIDDEN = "__steal_not_revealing__"

    def _apply_steal_privacy_to_detail_rows(
        self, rows: List[Any], game: Any = None
    ) -> List[Any]:
        """Keep Steal rows but hide vectors when human was not a party.

        CHECK_MODE True → unchanged full vectors.
        Human thief or victim → full vectors.
        AI↔AI only → label Steal with TURN_DETAIL_STEAL_HIDDEN (UI text).
        """
        try:
            from core.debug_mode import should_show_steal_detail

            if should_show_steal_detail(game or getattr(self, "game", None)):
                return list(rows or [])
        except Exception:
            return list(rows or [])

        out: List[Any] = []
        for item in list(rows or []):
            try:
                label, vector = item[0], item[1]
            except Exception:
                continue
            if str(label).strip().lower() == "steal":
                # Preserve that a steal happened without resource leakage
                out.append((str(label), self.TURN_DETAIL_STEAL_HIDDEN))
            else:
                out.append((label, vector))
        return out

    def _turn_detail_rows_for_player(self, player: Player) -> List[Tuple[str, List[int]]]:
        """Return non-empty per-turn detail rows for a player.

        Prefer the live structured turn-event ledger. If a turn has just been
        auto-advanced, use the frozen last-completed-turn snapshot. This avoids
        the popup showing stale resource production from the previous turn after
        a rolled 7 cleared the live ledger for the next player.
        """
        game = getattr(player, "game", None) or getattr(self, "game", None)
        if game is not None and hasattr(game, "get_turn_detail_rows_for_player"):
            try:
                rows = list(game.get_turn_detail_rows_for_player(player) or [])
                rows = self._append_missing_resource_production_detail_rows(player, rows)
                rows = self._append_missing_steal_detail_row(player, rows)
                rows = self._apply_steal_privacy_to_detail_rows(rows, game)
                if rows:
                    return rows
            except Exception:
                pass

        # If the just-completed turn was snapshotted before advance_turn(), use
        # it as the fallback and stop there. Returning [] for players with no
        # snapshot row is important: it prevents older last_resource_production
        # data from appearing one turn late.
        if game is not None:
            try:
                dice_roll = getattr(game, "dice_roll", None)
                dice_not_rolled = dice_roll in (None, 0, "", [])
                snapshot = getattr(game, "last_completed_turn_detail_rows_by_player", None)
                if dice_not_rolled and isinstance(snapshot, dict):
                    pid = int(getattr(player, "id", 0) or 0)
                    rows_from_snapshot = snapshot.get(pid) or snapshot.get(str(pid)) or []
                    context = getattr(game, "last_completed_turn_detail_context", None) or {}
                    is_robber_roll = False
                    if isinstance(context, dict):
                        try:
                            is_robber_roll = bool(context.get("is_robber_roll")) or int(context.get("dice_total") or 0) == 7
                        except Exception:
                            is_robber_roll = bool(context.get("is_robber_roll"))
                    normalised_rows: List[Tuple[str, List[int]]] = []
                    for label, vector in list(rows_from_snapshot):
                        label_text = str(label)
                        if is_robber_roll and label_text.strip().lower().startswith("rp"):
                            continue
                        vec = self._normalise_turn_delta_vector(vector)
                        if any(vec):
                            normalised_rows.append((label_text, vec))
                    return self._apply_steal_privacy_to_detail_rows(normalised_rows, game)
            except Exception:
                pass

        # Strong fallback for the immediate dice-roll production path before the
        # turn is advanced. This is intentionally skipped once a completed-turn
        # snapshot exists, so old RP data cannot leak into a later turn.
        if game is not None:
            try:
                pid = int(getattr(player, "id", 0) or 0)
                last = getattr(game, "last_resource_production_result", None) or {}
                prod = dict((last.get("produced_by_player") or {}))
                block = dict((last.get("blocked_by_player") or {}))
                rows_from_last: List[Tuple[str, List[int]]] = []
                vec = self._normalise_turn_delta_vector(prod.get(pid) or prod.get(str(pid)))
                if any(vec):
                    rows_from_last.append(("RP", vec))
                bvec = self._normalise_turn_delta_vector(block.get(pid) or block.get(str(pid)))
                if any(bvec):
                    rows_from_last.append(("RP Corr", bvec))
                rows_from_last = self._append_missing_steal_detail_row(player, rows_from_last)
                rows_from_last = self._apply_steal_privacy_to_detail_rows(rows_from_last, game)
                if rows_from_last:
                    return rows_from_last
            except Exception:
                pass

        row_specs = [
            ("RP", "turn_details_resource_production"),
            ("RP Corr", "turn_details_resource_production_robber"),
            ("Buy", "turn_details_buy"),
            ("Steal", "turn_details_steal"),
            ("Discard", "turn_details_discard"),
            ("TwP", "turn_details_TwP"),
            ("TwB", "turn_details_TwB"),
            ("Dcard", "turn_details_dcard"),
        ]
        rows: List[Tuple[str, List[int]]] = []
        for label, attr_name in row_specs:
            vector = self._normalise_turn_delta_vector(getattr(player, attr_name, None))
            if any(v != 0 for v in vector):
                rows.append((label, vector))
        rows = self._append_missing_resource_production_detail_rows(player, rows)
        rows = self._append_missing_steal_detail_row(player, rows)
        return self._apply_steal_privacy_to_detail_rows(rows, game)

    def _turn_delta_vector_from_resource_name(self, resource_name: Any, amount: int) -> List[int]:
        """Build a 6-slot delta vector in scoreboard resource order."""
        names = ["Wheat", "Ore", "Wood", "Brick", "Sheep", "Gold"]
        value = getattr(resource_name, "value", None)
        if value is not None:
            resource_name = value
        name_attr = getattr(resource_name, "name", None)
        if name_attr is not None and not isinstance(resource_name, str):
            resource_name = name_attr
        text = str(resource_name or "").strip()
        aliases = {
            "grain": "Wheat",
            "wheat": "Wheat",
            "ore": "Ore",
            "wood": "Wood",
            "lumber": "Wood",
            "brick": "Brick",
            "sheep": "Sheep",
            "wool": "Sheep",
            "gold": "Gold",
        }
        canonical = aliases.get(text.lower(), text[:1].upper() + text[1:])
        vector = [0, 0, 0, 0, 0, 0]
        try:
            vector[names.index(canonical)] = int(amount or 0)
        except Exception:
            pass
        return vector

    def _last_robber_steal_vector_for_player(self, player: Player) -> List[int]:
        """Return the latest robber-steal delta for this player as a fallback.

        The event ledger is the normal source of truth. This fallback keeps the
        scoreboard/popup correct even if an older install path executes the
        steal but does not refresh the ledger mirror before redraw.
        """
        game = getattr(player, "game", None) or getattr(self, "game", None)
        if game is None:
            return [0, 0, 0, 0, 0, 0]
        try:
            dice_roll = getattr(game, "dice_roll", None)
            dice_not_rolled = dice_roll in (None, 0, "", [])
            dice_total = None
            if isinstance(dice_roll, (list, tuple)):
                dice_total = sum(int(x) for x in dice_roll)
            elif not dice_not_rolled:
                dice_total = int(dice_roll)
            # A robber steal fallback is valid during the rolled-7 turn, or just
            # after an auto-advance while dice are not rolled yet. Once a later
            # non-7 dice roll starts, do not leak the older steal row.
            if (not dice_not_rolled) and dice_total != 7:
                return [0, 0, 0, 0, 0, 0]
        except Exception:
            pass

        result = getattr(game, "last_robber_steal_result", None) or {}
        if not isinstance(result, dict) or not result.get("ok"):
            return [0, 0, 0, 0, 0, 0]

        try:
            pid = int(getattr(player, "id", 0) or 0)
            thief_id = int(result.get("player_id") or 0)
            victim_id = int(result.get("opponent_id") or 0)
        except Exception:
            return [0, 0, 0, 0, 0, 0]

        if pid == thief_id:
            amount = +1
        elif pid == victim_id:
            amount = -1
        else:
            return [0, 0, 0, 0, 0, 0]
        return self._turn_delta_vector_from_resource_name(result.get("stolen_resource"), amount)

    def _last_resource_production_vectors_for_player(self, player: Player) -> Tuple[List[int], List[int]]:
        """Return immediate production/block deltas from the latest dice result.

        The compact red RCΔ row previously had this fallback when it was RP-only.
        Keep it here too, because the ledger/legacy mirrors can be stale during
        the same redraw cycle in which resource production was just applied.
        """
        zero = [0, 0, 0, 0, 0, 0]
        game = getattr(player, "game", None) or getattr(self, "game", None)
        if game is None:
            return zero[:], zero[:]
        try:
            dice_roll = getattr(game, "dice_roll", None)
            if dice_roll in (None, 0, "", []):
                return zero[:], zero[:]
            try:
                dice_total = sum(int(x) for x in dice_roll) if isinstance(dice_roll, (list, tuple)) else int(dice_roll)
            except Exception:
                dice_total = None
            if dice_total == 7:
                return zero[:], zero[:]

            pid = int(getattr(player, "id", 0) or 0)
            last = getattr(game, "last_resource_production_result", None) or {}
            if not isinstance(last, dict):
                return zero[:], zero[:]
            prod = dict((last.get("produced_by_player") or {}))
            block = dict((last.get("blocked_by_player") or {}))
            produced = self._normalise_turn_delta_vector(prod.get(pid) or prod.get(str(pid)))
            blocked = self._normalise_turn_delta_vector(block.get(pid) or block.get(str(pid)))
            return produced, blocked
        except Exception:
            return zero[:], zero[:]

    def _turn_delta_vector_for_category(self, player: Player, category: str, attr_name: Optional[str] = None) -> List[int]:
        """Read one current-turn delta vector from Game/ledger, then legacy field."""
        game = getattr(player, "game", None) or getattr(self, "game", None)
        if game is not None and hasattr(game, "get_turn_delta_vector"):
            try:
                return self._normalise_turn_delta_vector(game.get_turn_delta_vector(player, category))
            except Exception:
                pass
        if attr_name:
            return self._normalise_turn_delta_vector(getattr(player, attr_name, None))
        return [0, 0, 0, 0, 0, 0]

    def _completed_turn_rc_delta_vector_for_player(self, player: Player) -> List[int]:
        """Return the net rcard delta from the frozen completed-turn snapshot.

        Non-human turns can auto-advance immediately after a dice roll, robber
        steal, trade or build. advance_turn() correctly clears the live turn
        ledger for the next player, but the scoreboard should still show the
        red RCΔ row for the just-completed turn until the next dice roll starts.
        The '?' popup already reads this snapshot as detailed rows; this helper
        sums the same rows for the compact scoreboard line.
        """
        zero = [0, 0, 0, 0, 0, 0]
        game = getattr(player, "game", None) or getattr(self, "game", None)
        if game is None:
            return zero[:]

        try:
            dice_roll = getattr(game, "dice_roll", None)
            dice_not_rolled = dice_roll in (None, 0, "", [])
            if not dice_not_rolled:
                return zero[:]

            snapshot = getattr(game, "last_completed_turn_detail_rows_by_player", None)
            if not isinstance(snapshot, dict):
                return zero[:]

            pid = int(getattr(player, "id", 0) or 0)
            rows_from_snapshot = snapshot.get(pid) or snapshot.get(str(pid)) or []
            if not rows_from_snapshot:
                return zero[:]

            context = getattr(game, "last_completed_turn_detail_context", None) or {}
            is_robber_roll = False
            if isinstance(context, dict):
                try:
                    is_robber_roll = bool(context.get("is_robber_roll")) or int(context.get("dice_total") or 0) == 7
                except Exception:
                    is_robber_roll = bool(context.get("is_robber_roll"))

            show_steal = True
            try:
                from core.debug_mode import should_show_steal_detail

                show_steal = bool(should_show_steal_detail(game))
            except Exception:
                show_steal = True

            total = zero[:]
            for row in list(rows_from_snapshot):
                try:
                    label, vector = row
                except Exception:
                    continue
                if is_robber_roll and str(label).strip().lower().startswith("rp"):
                    continue
                if not show_steal and str(label).strip().lower() == "steal":
                    continue
                vec = self._normalise_turn_delta_vector(vector)
                for i in range(6):
                    total[i] += int(vec[i] or 0)
            return total
        except Exception:
            return zero[:]

    def _current_turn_rc_delta_vector(self, player: Player) -> List[int]:
        """Return the net resource-card delta for the compact red scoreboard row.

        Roads/settlements/cities, trades, discards, dcard buys, production and
        robber steals all mutate resource cards. The red second line should show
        the net current-turn rcard delta, while the '?' popup keeps the separate
        event rows such as RP and Steal.
        """
        categories = [
            ("resource_production", "turn_details_resource_production"),
            ("resource_production_robber", "turn_details_resource_production_robber"),
            ("steal", "turn_details_steal"),
            ("discard", "turn_details_discard"),
            ("buy", "turn_details_buy"),
            ("TwP", "turn_details_TwP"),
            ("TwB", "turn_details_TwB"),
            ("dcard", "turn_details_dcard"),
        ]
        total = [0, 0, 0, 0, 0, 0]
        steal_vector = [0, 0, 0, 0, 0, 0]
        production_vector = [0, 0, 0, 0, 0, 0]
        production_block_vector = [0, 0, 0, 0, 0, 0]
        show_steal = True
        try:
            from core.debug_mode import should_show_steal_detail

            show_steal = bool(should_show_steal_detail(getattr(self, "game", None)))
        except Exception:
            show_steal = True

        for category, attr_name in categories:
            if category == "steal" and not show_steal:
                continue
            vec = self._turn_delta_vector_for_category(player, category, attr_name)
            if category == "resource_production":
                production_vector = vec
            elif category == "resource_production_robber":
                production_block_vector = vec
            elif category == "steal":
                steal_vector = vec
            for i in range(min(6, len(vec))):
                total[i] += int(vec[i] or 0)

        # Restore the old RP-row fallback for the new net RCΔ row. If the ledger
        # and legacy player fields are still empty during the immediate redraw,
        # use Game.last_resource_production_result so production is visible now.
        if not any(production_vector) and not any(production_block_vector):
            fallback_prod, fallback_block = self._last_resource_production_vectors_for_player(player)
            for i in range(6):
                total[i] += int(fallback_prod[i] or 0) + int(fallback_block[i] or 0)

        # Fallback for the immediate robber path if the actual card transfer has
        # happened but the ledger/legacy mirror has not been refreshed yet.
        if show_steal and not any(steal_vector):
            fallback_steal = self._last_robber_steal_vector_for_player(player)
            if any(fallback_steal):
                for i in range(6):
                    total[i] += int(fallback_steal[i] or 0)

        if any(total):
            return total

        # If the turn auto-advanced, the live current-turn ledger has been
        # cleared for the next player. Reuse the same completed-turn snapshot as
        # the '?' popup, but sum the rows because the scoreboard is compact.
        completed_total = self._completed_turn_rc_delta_vector_for_player(player)
        if any(completed_total):
            return completed_total

        return total

    def _append_missing_steal_detail_row(self, player: Player, rows: List[Tuple[str, List[int]]]) -> List[Tuple[str, List[int]]]:
        """Ensure the '?' popup has a separate Steal row after robber steal.

        Privacy (CHECK_MODE=False, AI↔AI): still adds/keeps a Steal row; resource
        vectors are replaced later by ``_apply_steal_privacy_to_detail_rows``.
        """
        try:
            if any(str(label).strip().lower() == "steal" for label, _ in rows):
                return rows
        except Exception:
            return rows
        steal_vec = self._last_robber_steal_vector_for_player(player)
        if any(int(v or 0) != 0 for v in steal_vec):
            return list(rows) + [("Steal", steal_vec)]
        return rows

    def _format_turn_delta_value(self, value: int) -> str:
        """Format one small red delta value for the scoreboard."""
        if value == 0:
            return ""
        return f"+{value}" if value > 0 else str(value)

    def _render_scoreboard_turn_delta_row(self, player: Player, stats_y: int) -> None:
        """Render compact red current-turn resource-card deltas.

        This row is now a net rcard delta row, not RP-only. The '?' popup still
        shows separate rows such as RP, Steal, Discard, Buy, TwP/TwB and Dcard.
        """
        vector = self._current_turn_rc_delta_vector(player)
        if not any(vector):
            return

        font_small = Font.SMALL.value["bold"]
        resource_x_positions = RESOURCE_CARD_X_POSITIONS
        delta_y = stats_y + 13

        # General current-turn resource-card delta label. It intentionally sits
        # in the same compact column as the RC total, matching the previous RP
        # label placement but no longer implying that only production is shown.
        label = font_small.render("RCΔ", True, COLORS["RED"])
        label_rect = label.get_rect(center=(340, delta_y))
        WIN.blit(label, label_rect)

        for i, x_pos in enumerate(resource_x_positions):
            value = int(vector[i] or 0)
            formatted = self._format_turn_delta_value(value)
            if not formatted:
                continue
            text = font_small.render(formatted, True, COLORS["RED"])
            text_rect = text.get_rect(center=(x_pos + 20, delta_y))
            WIN.blit(text, text_rect)

    def _render_turn_detail_button(self, player: Player, stats_y: int) -> None:
        """Render a small '?' toggle button for per-player turn details."""
        rect = pygame.Rect(TURN_DETAIL_BUTTON_X, stats_y - 11, TURN_DETAIL_BUTTON_SIZE, TURN_DETAIL_BUTTON_SIZE)
        self.turn_detail_button_rects[int(player.id)] = rect

        is_expanded = self.turn_detail_expanded_player_id == int(player.id)
        border_color = COLORS["GREEN"] if is_expanded else COLORS["DGRAY"]
        pygame.draw.rect(WIN, COLORS["LGRAY"], rect)
        pygame.draw.rect(WIN, border_color, rect, 2)
        font = Font.NORMAL.value["bold"]
        text = font.render("?", True, COLORS["BLACK"])
        text_rect = text.get_rect(center=rect.center)
        WIN.blit(text, text_rect)

    def _stash_and_close_right_modals_for_turn_detail(self, game: Any) -> None:
        """G9: close TwP/TwB/discard/Play DCard and remember which was open.

        Incoming TwP is only hidden (not declined) so restore can reopen it
        while ``pending_human_twp_offer`` remains active.
        """
        stash: Dict[str, Any] = {"kind": None}
        try:
            from gui.gui_trade_player_panel import (
                is_incoming_twp_panel_active,
                is_trade_player_panel_active,
                is_twp_counter_panel_active,
                close_trade_player_panel,
                clear_trade_player_panel_area,
            )

            if is_twp_counter_panel_active(game):
                # Park counter draft; do not abandon negotiation on '?'
                stash["kind"] = "twp_counter"
                try:
                    clear_trade_player_panel_area()
                except Exception:
                    pass
            elif is_incoming_twp_panel_active(game):
                # Do NOT decline — keep pending offer; only hide chrome for '?'
                stash["kind"] = "twp_incoming"
                try:
                    clear_trade_player_panel_area()
                except Exception:
                    pass
            elif is_trade_player_panel_active(game):
                stash["kind"] = "twp"
                try:
                    close_trade_player_panel(game)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from gui.gui_trade_bank_panel import is_trade_bank_panel_active, close_trade_bank_panel

            if is_trade_bank_panel_active(game):
                stash["kind"] = stash.get("kind") or "twb"
                close_trade_bank_panel(game)
        except Exception:
            pass
        try:
            from gui.gui_discard_panel import is_discard_panel_active, close_discard_panel

            if is_discard_panel_active(game):
                # Keep pending discard queue; panel can recompute on reopen
                gui_obj = getattr(game, "gui", None)
                dstate = getattr(gui_obj, "discard_panel_state", None) if gui_obj else None
                if isinstance(dstate, dict):
                    stash["player_id"] = dstate.get("player_id")
                    stash["discard_count"] = dstate.get("discard_count")
                stash["kind"] = stash.get("kind") or "discard"
                close_discard_panel(game)
        except Exception:
            pass
        try:
            from gui.gui_play_dcard_panel import (
                is_play_dcard_panel_active,
                close_play_dcard_panel,
                get_open_play_dcard_type,
            )

            if is_play_dcard_panel_active(game):
                stash["kind"] = stash.get("kind") or "play_dcard"
                stash["card_type"] = get_open_play_dcard_type(game)
                try:
                    gui_obj = getattr(game, "gui", None)
                    pstate = (
                        getattr(gui_obj, "play_dcard_panel_state", None) if gui_obj else None
                    )
                    if isinstance(pstate, dict):
                        stash["player_id"] = pstate.get("player_id")
                except Exception:
                    pass
                close_play_dcard_panel(game)
        except Exception:
            pass
        if stash.get("kind"):
            self.modal_restore_after_turn_detail = stash

    def _restore_right_modal_after_turn_detail(self, game: Any) -> None:
        """G9: re-open stashed modal when '?' is toggled off (if still valid)."""
        stash = getattr(self, "modal_restore_after_turn_detail", None)
        self.modal_restore_after_turn_detail = None
        if not isinstance(stash, dict) or not stash.get("kind"):
            return
        kind = str(stash.get("kind") or "")
        try:
            if kind in ("twp_incoming", "twp", "twp_counter"):
                from gui.gui_trade_player_panel import (
                    open_incoming_twp_panel,
                    draw_incoming_twp_panel,
                    open_trade_player_panel,
                    draw_trade_player_panel,
                    draw_twp_counter_panel,
                    is_twp_counter_panel_active,
                )

                pending = getattr(game, "pending_human_twp_offer", None)
                if kind == "twp_counter" and is_twp_counter_panel_active(game):
                    draw_twp_counter_panel(game)
                elif kind == "twp_incoming" or (
                    isinstance(pending, dict) and pending.get("active")
                ):
                    if isinstance(pending, dict) and pending.get("active"):
                        open_incoming_twp_panel(game, pending)
                        draw_incoming_twp_panel(game)
                    # else offer expired → no restore (plan edge case)
                else:
                    open_trade_player_panel(game)
                    draw_trade_player_panel(game)
            elif kind == "twb":
                from gui.gui_trade_bank_panel import open_trade_bank_panel, draw_trade_bank_panel

                open_trade_bank_panel(game)
                draw_trade_bank_panel(game)
            elif kind == "discard":
                from gui.gui_discard_panel import open_discard_panel, draw_discard_panel

                kwargs: Dict[str, Any] = {}
                if stash.get("player_id") is not None:
                    kwargs["player_id"] = stash.get("player_id")
                if stash.get("discard_count") is not None:
                    kwargs["discard_count"] = stash.get("discard_count")
                open_discard_panel(game, **kwargs)
                draw_discard_panel(game)
            elif kind == "play_dcard":
                card_type = stash.get("card_type")
                if card_type:
                    from gui.gui_play_dcard_panel import open_play_dcard_panel, draw_play_dcard_panel

                    ok = open_play_dcard_panel(
                        game,
                        str(card_type),
                        player_id=stash.get("player_id"),
                    )
                    if ok:
                        draw_play_dcard_panel(game)
        except Exception:
            pass

    def handle_turn_detail_click(self, pos: Tuple[int, int]) -> bool:
        """Toggle the per-player turn-detail overlay from the '?' buttons.

        The '?' button is now the only control: click once to show that
        player's details; click the same '?' again to close. If a detail panel
        is open, clicks inside the panel are consumed so they do not leak
        through to board/buttons underneath.

        G9: opening '?' closes right-slot modals (TwP/TwB/…) and restores them
        when the same '?' is toggled off.
        """
        # First check the persistent '?' buttons. This must happen before
        # panel-hit testing, so the same '?' remains a true toggle even when
        # the detail panel is open.
        for player_id, rect in list(self.turn_detail_button_rects.items()):
            if rect.collidepoint(pos):
                previous_panel_rect = self.turn_detail_panel_rect.copy() if self.turn_detail_panel_rect else None
                opening = self.turn_detail_expanded_player_id != player_id
                closing = self.turn_detail_expanded_player_id == player_id
                self.turn_detail_expanded_player_id = (
                    None if closing else player_id
                )
                self.turn_detail_panel_rect = None
                try:
                    sound = SOUNDS.get("BELL") or SOUNDS.get("BUTTON")
                    if sound is not None:
                        pygame.mixer.Sound.play(sound)
                except Exception:
                    pass

                if opening:
                    try:
                        self._stash_and_close_right_modals_for_turn_detail(self.game)
                    except Exception:
                        pass
                elif closing:
                    try:
                        self._restore_right_modal_after_turn_detail(self.game)
                    except Exception:
                        pass

                # Defensive cleanup: if an older/wider popup was visible, clear
                # its full previous rectangle before the scoreboard is redrawn.
                # This prevents a right-side strip from remaining visible when
                # the popup is closed.
                if previous_panel_rect is not None:
                    pygame.draw.rect(WIN, COLORS["LGRAY"], previous_panel_rect.inflate(4, 4))

                self.update_scoreboard(self.game)
                pygame.display.update()
                return True

        # A click inside the open panel itself should not leak through to the
        # board underneath. Closing is done only by clicking the same '?'.
        if self.turn_detail_expanded_player_id is not None:
            if self.turn_detail_panel_rect is not None and self.turn_detail_panel_rect.collidepoint(pos):
                return True

        return False

    def _draw_turn_detail_panel(self, game: Game, player_id: int) -> None:
        """Draw the v045-inspired turn-detail overlay in the right panel area."""
        player = next((p for p in getattr(game, "players", []) if getattr(p, "id", None) == player_id), None)
        if player is None:
            return

        rows = self._turn_detail_rows_for_player(player)
        previous_panel_rect = self.turn_detail_panel_rect.copy() if self.turn_detail_panel_rect else None
        panel_rect = TURN_DETAIL_PANEL_RECT.copy()
        self.turn_detail_panel_rect = panel_rect

        if previous_panel_rect is not None and previous_panel_rect != panel_rect:
            pygame.draw.rect(WIN, COLORS["LGRAY"], previous_panel_rect.inflate(4, 4))
        pygame.draw.rect(WIN, COLORS["LGRAY"], panel_rect)
        pygame.draw.rect(WIN, COLORS["BLACK"], panel_rect, 1)

        font = Font.SMALL.value["bold"]
        header = font.render(f"P{player_id} turn details", True, COLORS["BLACK"])
        WIN.blit(header, (panel_rect.x + 8, panel_rect.y + 6))

        if not rows:
            empty = font.render("No turn deltas", True, COLORS["DGRAY"])
            WIN.blit(empty, (panel_rect.x + 8, panel_rect.y + 26))
            return

        resource_column_x = [
            panel_rect.x + 91,
            panel_rect.x + 119,
            panel_rect.x + 147,
            panel_rect.x + 175,
            panel_rect.x + 203,
        ]
        for header_text, header_x in zip(["Wh", "O", "Wd", "B", "Sh"], resource_column_x):
            header_surf = font.render(header_text, True, COLORS["DGRAY"])
            header_rect = header_surf.get_rect(center=(header_x, panel_rect.y + 28))
            WIN.blit(header_surf, header_rect)

        y = panel_rect.y + 44
        for row_label, vector in rows[:6]:
            label_surf = font.render(f"{row_label:<7}:", True, COLORS["RED"])
            WIN.blit(label_surf, (panel_rect.x + 8, y))

            # AI↔AI steal under normal play: keep the row, hide resource vector.
            if vector == self.TURN_DETAIL_STEAL_HIDDEN or (
                isinstance(vector, str) and vector == self.TURN_DETAIL_STEAL_HIDDEN
            ):
                note = font.render("Not revealing details", True, COLORS["DGRAY"])
                WIN.blit(note, (panel_rect.x + 74, y))
                y += 18
                continue

            open_bracket = font.render("[", True, COLORS["RED"])
            close_bracket = font.render("]", True, COLORS["RED"])
            WIN.blit(open_bracket, (panel_rect.x + 74, y))
            WIN.blit(close_bracket, (panel_rect.x + 208, y))

            compact_vector = self._normalise_turn_delta_vector(vector)[:5]
            for value_index, (value, value_x) in enumerate(zip(compact_vector, resource_column_x)):
                value_surf = font.render(str(int(value or 0)), True, COLORS["RED"])
                value_rect = value_surf.get_rect(center=(value_x, y + 6))
                WIN.blit(value_surf, value_rect)
                if value_index < 4:
                    comma_surf = font.render(",", True, COLORS["RED"])
                    WIN.blit(comma_surf, (value_x + 9, y))
            y += 18

    def _normalise_dcard_type_counts(self, player: Player) -> List[int]:
        """Return compact total counts for VP, Knight, Road, Plenty, Monopoly.

        Kept as a small compatibility helper for older debug views.  The main
        scoreboard now uses _normalise_dcard_scoreboard_triplets(), because the
        v045 dashboard showed the more useful new/playable/played detail.
        """
        totals: List[int] = []
        for _card_name, triplet in self._normalise_dcard_scoreboard_triplets(player):
            totals.append(max(0, sum(int(v or 0) for v in triplet)))
        return totals

    def _normalise_dcard_scoreboard_triplets(self, player: Player) -> List[Tuple[str, List[int]]]:
        """Return v045-style dcard dashboard triplets for one player.

        Each triplet is [new/received (x), playable (y), played/revealed (z)].
        Buy increments only x; end-of-turn maturity moves x→y; play moves y→z.
        The card order is VP, Knight, Road, Plenty, Monopoly.  Defensive: a
        malformed/missing dcard_summary must never break the scoreboard.
        """
        expected = ["victory_point", "knight", "two_free_roads", "year_of_plenty", "monopoly"]
        fallback_counts = {name: 0 for name in expected}
        try:
            for card in getattr(player, "development_cards", []) or []:
                card_name = str(card or "").strip()
                if card_name in fallback_counts:
                    fallback_counts[card_name] += 1
        except Exception:
            pass

        try:
            summary = list(getattr(player, "dcard_summary", []) or [])
        except Exception:
            summary = []

        result: List[Tuple[str, List[int]]] = []
        for index, card_name in enumerate(expected):
            triplet = [0, 0, 0]
            try:
                row = list(summary[index])
                if not row or str(row[0]) != card_name:
                    raise ValueError("summary_row_mismatch")
                while len(row) < 4:
                    row.append(0)
                for col_index in range(3):
                    try:
                        triplet[col_index] = max(0, int(row[col_index + 1] or 0))
                    except Exception:
                        triplet[col_index] = 0
            except Exception:
                # Last-resort fallback: we know the player owns the card type,
                # but not whether it is new/playable/played, so put it in the
                # first column rather than hiding it.
                triplet = [max(0, int(fallback_counts.get(card_name, 0) or 0)), 0, 0]
            result.append((card_name, triplet))
        return result

    def _normalise_human_player_ids(self) -> List[int]:
        """Return configured human player ids as a flat list of ints."""
        try:
            from core import constants as core_constants
            raw_ids = getattr(core_constants, "HP_ID", [])
        except Exception:
            raw_ids = []

        if isinstance(raw_ids, int):
            raw_values = [raw_ids]
        elif isinstance(raw_ids, (list, tuple, set)):
            raw_values = list(raw_ids)
        else:
            raw_values = [raw_ids]

        result: List[int] = []
        for item in raw_values:
            try:
                result.append(int(item))
            except Exception:
                pass
        return result

    def _show_dcard_detail_for_player(self, player: Player) -> bool:
        """Return whether this row may show detailed dcard information.

        v033 policy: show the v045-style DCard triplets for every player row,
        including AI players.  The previous privacy rule only showed these
        triplets for human-player rows unless DEV_ANALYSIS was enabled.  That
        made an AI DCard buy update the underlying player state, but the right
        side of the scoreboard stayed visually empty for the AI row.

        Optional compatibility switch:
            core.constants.SHOW_DCARD_DETAILS_FOR_ALL_PLAYERS = False

        When that optional constant is explicitly set to False, the old privacy
        behavior is restored: DEV_ANALYSIS shows all rows, otherwise only human
        rows show DCard type triplets.  If the constant is absent, the new v033
        default is True.
        """
        try:
            from core import constants as core_constants
        except Exception:
            core_constants = None

        try:
            if core_constants is not None and bool(getattr(core_constants, "DEV_ANALYSIS", False)):
                return True
        except Exception:
            pass

        try:
            show_all = True if core_constants is None else bool(
                getattr(core_constants, "SHOW_DCARD_DETAILS_FOR_ALL_PLAYERS", True)
            )
        except Exception:
            show_all = True

        if show_all:
            return True

        # Explicit opt-out: restore the former human-only detail rule.
        try:
            player_id = int(getattr(player, "id", 0) or 0)
        except Exception:
            player_id = 0
        return player_id in self._normalise_human_player_ids()

    def _dcard_played_this_turn_index(self, game: Game) -> int:
        """Return the dcard type index played this turn, or -1 when none."""
        try:
            turn_details = getattr(game, "turn_details", None) or getattr(game, "myturn", None)
            if not bool(getattr(turn_details, "dcard_played_in_turn_TF", False)):
                return -1
            vector = list(getattr(turn_details, "dcard_played_in_turn", []) or [])
            for index, value in enumerate(vector[:5]):
                try:
                    if int(value or 0) > 0:
                        return index
                except Exception:
                    pass
        except Exception:
            pass
        return -1

    def _dcard_played_this_turn_player_id(self, game: Game) -> Optional[int]:
        """Return player id who played a DCard this turn, or None if unknown."""
        try:
            turn_details = getattr(game, "turn_details", None) or getattr(game, "myturn", None)
            if not bool(getattr(turn_details, "dcard_played_in_turn_TF", False)):
                return None
            raw = getattr(turn_details, "dcard_played_in_turn_player_id", None)
            if raw is None:
                raw = getattr(game, "dcard_played_in_turn_player_id", None)
            if raw is None:
                return None
            pid = int(raw)
            return pid if pid > 0 else None
        except Exception:
            return None

    def _render_dcard_statistics_row(self, player: Player, game: Game, stats_y: int) -> None:
        """Render v045-style dcard triplets: new/playable/played-or-VP.

        The existing DC column still shows the total number of development cards.
        This right-side detail area shows type-level details only when allowed by
        _show_dcard_detail_for_player().

        When a DCard was played this turn, the three-number triplet for that type
        is drawn in RED only on the scoreboard row of the player who played it.

        Live + re-play: play feedback pulse is on the **shared header icon**
        (``dcard_header_play_fx``), not on type-cell numbers. Type-cell red text
        still marks the actor's played type this turn.
        """
        if not self._show_dcard_detail_for_player(player):
            return

        font = Font.SMALL.value["regular"]
        played_index = self._dcard_played_this_turn_index(game)
        played_player_id = self._dcard_played_this_turn_player_id(game)
        try:
            row_player_id = int(getattr(player, "id", 0) or 0)
        except Exception:
            row_player_id = 0
        # Per-player highlight: only the acting player's row goes red.
        # If player id was not recorded (legacy), fall back to type-global red.
        highlight_this_row = bool(
            played_index >= 0
            and (
                played_player_id is None
                or row_player_id == int(played_player_id)
            )
        )

        # Re-play may stamp play types for empty-label edge cases (no cell ring).
        try:
            buy_types = set(getattr(player, "replay_dcard_buy_types", None) or set())
        except Exception:
            buy_types = set()
        try:
            play_types = set(getattr(player, "replay_dcard_play_types", None) or set())
        except Exception:
            play_types = set()

        try:
            dcard_triplets = self._normalise_dcard_scoreboard_triplets(player)
        except Exception:
            dcard_triplets = []

        # Human: always full x/y/z. Opponents: full only in CHECK_MODE; else played only.
        full_triplets = True
        try:
            from core.debug_mode import should_show_full_dcard_triplets

            full_triplets = bool(should_show_full_dcard_triplets(player))
        except Exception:
            full_triplets = True

        for index, (card_name, triplet) in enumerate(dcard_triplets[:5]):
            try:
                values = [max(0, int(v or 0)) for v in list(triplet)[:3]]
                while len(values) < 3:
                    values.append(0)
                cname = str(card_name or "")
                if full_triplets:
                    if not any(values) and cname not in buy_types and cname not in play_types:
                        continue
                    if not any(values) and (cname in buy_types or cname in play_types):
                        label = "0/0/0"
                    else:
                        label = f"{values[0]}/{values[1]}/{values[2]}"
                else:
                    # Opponent, normal play: only played/revealed (z).
                    played = int(values[2] or 0)
                    if played <= 0 and cname not in buy_types and cname not in play_types:
                        continue
                    label = str(played) if played > 0 else "0"
                buy_red = cname in buy_types
                play_red = bool(highlight_this_row and index == played_index)
                text_color = (
                    COLORS["RED"]
                    if (buy_red or play_red)
                    else COLORS["BLACK"]
                )
                value_text = font.render(label, True, text_color)
                cx = DCARD_X_POSITIONS[index] + 15
                value_rect = value_text.get_rect(center=(cx, stats_y))
                WIN.blit(value_text, value_rect)
                # No type-cell ring: play pulse is on shared header only (D1–D4).
            except Exception:
                pass

    def _render_scoreboard_row(self, player: Player, game: Game, x: int, name_y: int, stats_y: int) -> None:
        """Render a single player's scoreboard row with statistics and resource counts.

        Args:
            player: The player whose statistics to render.
            game: The game instance containing player data.
            x: X-coordinate for the player name.
            name_y: Y-coordinate for the player name.
            stats_y: Y-coordinate for the player's statistics and resource counts.
        """
        font = Font.NORMAL.value["regular"]
        font_large = Font.LARGE.value["regular"]
        x_positions = [115, 145, 165, 185, 205, 225, 245, 270, 300, 330, 360, 390, 435, 480, 525, 570]
       
        # Player name in color, large font, at x=15
        player_colors = {
            1: COLORS["BLUE"],
            2: COLORS["RED"],
            3: COLORS["WHITE"],
            4: COLORS["ORANGE"]
        }
        player_name = f"Player {player.id}"
        name_text = font_large.render(player_name, True, player_colors.get(player.id, COLORS["BLACK"]))
        WIN.blit(name_text, (x, name_y))
       
        # Player stats
        extra_vp = 0
        for dcard in getattr(player, "dcard_summary", []) or []:
            try:
                if dcard and str(dcard[0]) == "victory_point":
                    extra_vp += int(dcard[3] or 0)
            except Exception:
                pass
        stats = [
            str(player.victory_points), # VP
            str(len(player.cities)), # C
            str(len(player.settlements)), # S
            str(len(player.roads)), # R (roads)
            str(2 if player.longest_route_tf == True else 0), # R (longest route points)
            str(2 if player.largest_army_tf == True else 0), # A
            str(extra_vp), # E
            str(player.size_longest_route), # LR
            str(player.size_largest_army), # LA
            str(player.number_of_rcards), # RC
            str(player.number_of_dcards), # DC
        ]
        for i, stat in enumerate(stats):
            text = font.render(stat, True, COLORS["BLACK"])
            text_rect = text.get_rect(center=(x_positions[i] + 10, stats_y))
            WIN.blit(text, text_rect)
       
        # Resource cards (Wheat, Ore, Wood, Brick, Sheep).
        # CHECK_MODE=False: only human seat shows per-type breakdown (RC total still shown above).
        show_breakdown = True
        try:
            from core.debug_mode import should_show_opponent_rcard_breakdown

            show_breakdown = bool(should_show_opponent_rcard_breakdown(player))
        except Exception:
            show_breakdown = True
        if show_breakdown:
            rc_stats = [
                player.rcards.get(ResourceCard.WHEAT, 0),
                player.rcards.get(ResourceCard.ORE, 0),
                player.rcards.get(ResourceCard.WOOD, 0),
                player.rcards.get(ResourceCard.BRICK, 0),
                player.rcards.get(ResourceCard.SHEEP, 0)
            ]
            for i, stat in enumerate(rc_stats):
                text = font.render(str(stat), True, COLORS["BLACK"])
                text_rect = text.get_rect(center=(x_positions[i + 11] + 20, stats_y))
                WIN.blit(text, text_rect)
        else:
            rc_stats = []

        self._render_scoreboard_turn_delta_row(player, stats_y)
        self._render_turn_detail_button(player, stats_y)
        self._render_dcard_statistics_row(player, game, stats_y)
       
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"gui_game.py | _render_scoreboard_row | Player {player.id}: {player_name} {stats} RC: {rc_stats}\n")

    def draw_guidance(self):
        self.human_guidance.draw()

    def clear_guidance_text(self, y_offset: int = 25) -> None:
        """G3: blank the human guidance strip after OKY / cancel.

        ``y_offset`` is accepted for call-site compatibility; position is fixed
        to ``GUIDANCE_TEXT_RECT`` (raised under Round/Turn, above Resource Potential).
        """
        try:
            pygame.draw.rect(WIN, COLORS["LGRAY"], GUIDANCE_TEXT_RECT)
            if getattr(self, "human_guidance", None) is not None:
                self.human_guidance.confirm_center = None
        except Exception:
            pass

    def draw_guidance_text(self, lines: list[str] | str, y_offset: int = 0, font_size: str = "normal"):
        """
        Draw one or more lines of guidance text in ``GUIDANCE_TEXT_RECT``.

        - lines: can be a single string or a list of strings
        - y_offset: legacy; values ≥ 20 (old default 25) map to the raised band
          so callers need not change. Small offsets (0–8) still fine-tune within the band.
        """
        if isinstance(lines, str):
            lines = [lines]  # convert single string to list

        # Raised under Round/Turn (ROUND_TURN_RECT ends ~y=34); never enter RP band
        fine = 0 if int(y_offset or 0) >= 20 else max(0, int(y_offset or 0))
        clear_r = GUIDANCE_TEXT_RECT
        pygame.draw.rect(WIN, COLORS["LGRAY"], clear_r)

        font = Font.NORMAL.value["regular"] if font_size == "normal" else Font.LARGE.value["regular"]
        y = int(GUIDANCE_TEXT_LINE0_Y) + fine
        max_bottom = clear_r.bottom - 2
        for line in lines:
            if not line:
                continue
            if y + 14 > max_bottom:
                break
            surf = font.render(line, True, COLORS["BLACK"])
            WIN.blit(surf, (clear_r.x + 5, y))
            y += int(GUIDANCE_TEXT_LINE_SPACING)

        # optional — can be removed if called from elsewhere
        try:
            pygame.display.update(clear_r)
        except Exception:
            pass

    def handle_confirmation_click(self, pos: Tuple[int, int]) -> str | None:
        """Check if click was on the dynamic OKY / OKN icons."""
        if not self.human_guidance.confirm_center:
            return None

        x, y = self.human_guidance.confirm_center
        
        # OKY is drawn at (x + 35, y - 45), size 40×40
        oky_rect = pygame.Rect(x + 35, y - 45, 40, 40)
        
        # OKN is drawn at (x + 35, y + 10), size 40×40
        okn_rect = pygame.Rect(x + 35, y + 10, 40, 40)

        if oky_rect.collidepoint(pos):
            return "OKY"
        if okn_rect.collidepoint(pos):
            return "OKN"
        
        return None               

    def update_resource_exploration(self, board: Board):
        """Display resource exploration (= pip summary left column).

        Layout is canonical in ``gui_constants``:
          ROUND_TURN → GUIDANCE_TEXT → RESOURCE_POTENTIAL → TwP Mode (y≈215).
        """
        
        # ─── Display Constants (from gui_constants; do not hardcode y) ───────
        bg = RESOURCE_POTENTIAL_RECT
        AREA_X            = bg.x + 5
        HEADER_Y          = RESOURCE_POTENTIAL_HEADER_Y
        LABEL_Y           = RESOURCE_POTENTIAL_LABEL_Y
        CURRENT_Y         = RESOURCE_POTENTIAL_CURRENT_Y
        APPROX_Y          = RESOURCE_POTENTIAL_APPROX_Y
        BG_COLOR          = COLORS["LGRAY"]
        
        COL_WIDTH         = 50
        COL_WHEAT         = 150
        COL_ORE           = COL_WHEAT + COL_WIDTH
        COL_WOOD          = COL_ORE   + COL_WIDTH
        COL_BRICK         = COL_WOOD  + COL_WIDTH
        COL_SHEEP         = COL_BRICK + COL_WIDTH
        
        RESOURCE_COLUMNS = {
            "wheat": COL_WHEAT,
            "ore":   COL_ORE,
            "wood":  COL_WOOD,
            "brick": COL_BRICK,
            "sheep": COL_SHEEP,
        }
        
        FONT_HEADER = Font.NORMAL.value["bold"]
        FONT_NORMAL = Font.NORMAL.value["regular"]
        FONT_SMALL  = Font.SMALL.value["regular"]
        # ─────────────────────────────────────────────────────────────────────

        # Clear background rectangle (canonical panel)
        pygame.draw.rect(WIN, BG_COLOR, bg)

        # Header
        header_surf = FONT_HEADER.render("Resource Potential:", 
                                        True, COLORS["BLACK"])
        WIN.blit(header_surf, (AREA_X, HEADER_Y))

        # Resource labels (Wheat, Ore, etc. — now on their own row above numbers)
        for res, cx in RESOURCE_COLUMNS.items():
            label_surf = FONT_SMALL.render(res.capitalize(), True, COLORS["DGRAY"])
            WIN.blit(label_surf, (cx - label_surf.get_width() // 2, LABEL_Y))

        # ── Current factual row ──────────────────────────────────────────────
        current = board.get_current_settlement_pips()
        
        current_text = FONT_NORMAL.render("Current:", True, COLORS["BLACK"])
        WIN.blit(current_text, (AREA_X, CURRENT_Y))

        for res, cx in RESOURCE_COLUMNS.items():
            val = current.get(res, 0.0)
            txt = FONT_NORMAL.render(f"{val:.1f}", True, COLORS["BLACK"])
            WIN.blit(txt, (cx - txt.get_width() // 2, CURRENT_Y))

        # ── Approximation row ────────────────────────────────────────────────
        approx = board.resource_exploration()
        
        approx_text = FONT_NORMAL.render("Remaining:", True, COLORS["BLACK"])
        WIN.blit(approx_text, (AREA_X, APPROX_Y))

        for res, cx in RESOURCE_COLUMNS.items():
            if res not in approx:
                continue
            mi = approx[res]["min"]
            ma = approx[res]["max"]
            if abs(mi - ma) < 0.5:
                display_str = f"{mi:.1f}"
            else:
                display_str = f"{mi:.0f}–{ma:.0f}"
            txt = FONT_NORMAL.render(display_str, True, COLORS["BLACK"])
            WIN.blit(txt, (cx - txt.get_width() // 2, APPROX_Y))