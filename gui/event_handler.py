"""
Handles mouse click events for the Catan game.

Adds Execution-phase click handling for:
- Play / next_turn2
- Roll Dices
- End Turn
- basic robber tile selection after rolling 7
"""

import pygame
from typing import Tuple

from gui.gui_constants import SOUNDS, POSITIONS, IMAGES, WIN, COLORS, ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS
try:
    from gui.gui_constants import HUMAN_BUTTON_RECTS
except Exception:  # pragma: no cover - supports older gui_constants while testing.
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
        "next_turn2": pygame.Rect(20, 470, 130, 40),
    }
from gui.gui_guidance import PlacementState
from gui.gui_human_player import GUIHumanPlayer
try:
    from gui.gui_trade_bank_panel import (
        open_trade_bank_panel,
        draw_trade_bank_panel,
        handle_trade_bank_panel_click,
        is_trade_bank_panel_active,
    )
except Exception:  # pragma: no cover - keeps partial installs importable
    def open_trade_bank_panel(game):
        return None

    def draw_trade_bank_panel(game):
        return None

    def handle_trade_bank_panel_click(game, pos):
        return False

    def is_trade_bank_panel_active(game):
        return False


try:
    from gui.gui_discard_panel import (
        open_discard_panel,
        draw_discard_panel,
        handle_discard_panel_click,
        is_discard_panel_active,
        close_discard_panel,
    )
except Exception:
    def open_discard_panel(game, **kwargs):
        return None
    def draw_discard_panel(game):
        return None
    def handle_discard_panel_click(game, pos):
        return False
    def is_discard_panel_active(game):
        return False
    def close_discard_panel(game):
        return None


try:
    from gui.gui_trade_player_panel import (
        open_trade_player_panel,
        draw_trade_player_panel,
        handle_trade_player_panel_click,
        is_trade_player_panel_active,
        draw_incoming_twp_panel,
        handle_incoming_twp_panel_click,
        is_incoming_twp_panel_active,
        draw_twp_counter_panel,
        handle_twp_counter_panel_click,
        is_twp_counter_panel_active,
    )
except Exception:  # pragma: no cover - keeps partial installs importable
    def open_trade_player_panel(game):
        return None

    def draw_trade_player_panel(game):
        return None

    def handle_trade_player_panel_click(game, pos):
        return False

    def is_trade_player_panel_active(game):
        return False

    def draw_incoming_twp_panel(game):
        return None

    def handle_incoming_twp_panel_click(game, pos):
        return False

    def is_incoming_twp_panel_active(game):
        return False

    def draw_twp_counter_panel(game):
        return None

    def handle_twp_counter_panel_click(game, pos):
        return False

    def is_twp_counter_panel_active(game):
        return False

try:
    from gui.gui_twp_auto_rules_panel import (
        open_twp_auto_rules_panel,
        draw_twp_auto_rules_panel,
        handle_twp_auto_rules_panel_click,
        handle_twp_auto_rules_key,
        handle_twp_auto_rules_mousewheel,
        is_twp_auto_rules_panel_active,
    )
except Exception:  # pragma: no cover - keeps partial installs importable
    def open_twp_auto_rules_panel(game):
        return None

    def draw_twp_auto_rules_panel(game):
        return None

    def handle_twp_auto_rules_panel_click(game, pos):
        return False

    def handle_twp_auto_rules_key(game, event):
        return False

    def handle_twp_auto_rules_mousewheel(game, y):
        return False

    def is_twp_auto_rules_panel_active(game):
        return False


try:
    from gui.gui_play_dcard_panel import (
        open_play_dcard_panel,
        close_play_dcard_panel,
        draw_play_dcard_panel,
        handle_play_dcard_panel_click,
        is_play_dcard_panel_active,
        handle_scoreboard_dcard_click,
    )
except Exception:  # pragma: no cover
    def open_play_dcard_panel(game, card_type, **kwargs):
        return False

    def close_play_dcard_panel(game):
        return None

    def draw_play_dcard_panel(game):
        return None

    def handle_play_dcard_panel_click(game, pos):
        return False

    def is_play_dcard_panel_active(game):
        return False

    def handle_scoreboard_dcard_click(game, pos):
        return False


try:
    from gui.gui_game_over_panel import (
        draw_game_over_panel,
        handle_game_over_click,
        handle_game_over_key,
        is_post_game_ui_active,
        ensure_post_game_ui,
        consume_new_game_request,
    )
except Exception:  # pragma: no cover
    def draw_game_over_panel(game):
        return None

    def handle_game_over_click(game, pos):
        return False

    def handle_game_over_key(game, key):
        return False

    def is_post_game_ui_active(game):
        return False

    def ensure_post_game_ui(game):
        return {}

    def consume_new_game_request(game):
        return False

try:
    from gui.gui_human_road_guidance import (
        open_human_road_guidance,
        draw_human_road_guidance,
        handle_human_road_guidance_click,
        is_human_road_guidance_active,
    )
except Exception:  # pragma: no cover - keeps partial installs importable
    def open_human_road_guidance(game):
        return False

    def draw_human_road_guidance(game):
        return None

    def handle_human_road_guidance_click(game, pos):
        return False

    def is_human_road_guidance_active(game):
        return False

try:
    from gui.gui_human_buy_guidance import (
        open_human_city_guidance,
        open_human_settlement_guidance,
        open_human_dcard_confirmation,
        draw_human_buy_guidance,
        handle_human_buy_guidance_click,
        is_human_buy_guidance_active,
    )
except Exception:  # pragma: no cover - keeps partial installs importable
    def open_human_city_guidance(game):
        return False

    def open_human_settlement_guidance(game):
        return False

    def open_human_dcard_confirmation(game):
        return False

    def draw_human_buy_guidance(game):
        return None

    def handle_human_buy_guidance_click(game, pos):
        return False

    def is_human_buy_guidance_active(game):
        return False

from core.game import Game
from core.constants import FNFREQ, FILENAME_FREQ, HUMAN_PLAYER, HP_ID


class EventHandler:
    """Manages mouse click events for the Catan game."""

    def __init__(self) -> None:
        """Initialize the EventHandler."""
        pass

    def _play_sound(self, name: str, fallback: str = "BUTTON") -> None:
        """Play a sound safely even when a sound asset is missing."""
        try:
            sound = SOUNDS.get(name) or SOUNDS.get(fallback)
            if sound is not None:
                pygame.mixer.Sound.play(sound)
        except Exception:
            pass

    def _is_ui_input_busy(self, game: Game) -> bool:
        """P2-A / P3-A: pipeline, Phase0 save, or PLAY/Continue press latch."""
        try:
            from core.performance_trace import is_ui_input_busy

            return bool(is_ui_input_busy(game))
        except Exception:
            try:
                if bool(getattr(game, "ui_play_continue_latched", False)):
                    return True
            except Exception:
                pass
            try:
                return bool(getattr(game, "ai_pipeline_busy", False)) or bool(
                    getattr(game, "phase0_save_busy", False)
                )
            except Exception:
                return False

    def _play_continue_busy_scope(self, game: Game, reason: str = ""):
        """P3-A outer busy + immediate PLAY/Continue disable for click body."""
        try:
            from core.performance_trace import play_continue_busy_scope

            return play_continue_busy_scope(game, reason=reason)
        except Exception:
            from contextlib import nullcontext

            try:
                from core.performance_trace import latch_play_continue_disabled

                latch_play_continue_disabled(game, reason=reason, redraw=True)
            except Exception:
                try:
                    if game.gui is not None:
                        game.gui.set_button("next_turn2", False)
                        game.gui.set_button("continue_ai", False)
                except Exception:
                    pass
            return nullcontext()

    @staticmethod
    def _dice_total_from_value(value: object) -> int | None:
        """Return the dice total from an int or a 2-dice tuple/list."""
        try:
            if isinstance(value, (list, tuple)):
                return sum(int(x) for x in value)
            if value in (None, "", []):
                return None
            return int(value)
        except Exception:
            return None

    def _current_dice_total(self, game: Game) -> int | None:
        """Best-effort current dice total used to guard same-turn UI fallbacks."""
        try:
            total = self._dice_total_from_value(getattr(game, "dice_roll", None))
            if total is not None:
                return total
        except Exception:
            pass
        try:
            last = getattr(game, "last_dice_roll_result", None) or {}
            if isinstance(last, dict):
                total = self._dice_total_from_value(last.get("total"))
                if total is not None:
                    return total
                return self._dice_total_from_value(last.get("dice"))
        except Exception:
            pass
        return None

    def _clear_completed_turn_snapshot(self, game: Game) -> None:
        """Clear previous completed-turn UI details when a new dice roll starts."""
        try:
            game.last_completed_turn_detail_rows_by_player = {}
            game.last_completed_turn_detail_context = {}
        except Exception:
            pass

    def _clear_stale_resource_production_state(self, game: Game) -> None:
        """A rolled 7 has no RP; do not let older RP fallbacks leak into the UI."""
        for attr_name in ("last_resource_production_result", "_pending_resource_production_animation"):
            try:
                if hasattr(game, attr_name):
                    setattr(game, attr_name, None if attr_name.startswith("_") else {})
            except Exception:
                pass

    def _ensure_robber_steal_event_visible(self, game: Game, robber_result: object) -> None:
        """Ensure the final 'steals X from PY' line is present in the event feed.

        game_7logic normally emits this line itself. This guard avoids the visible
        Events pane ending at the target-selection line when the non-human robber
        flow immediately advances and redraws the UI.
        """
        try:
            if not isinstance(robber_result, dict):
                return
            steal = robber_result.get("steal") or {}
            if not isinstance(steal, dict) or not steal.get("ok"):
                return
            player_id = int(steal.get("player_id") or 0)
            opponent_id = int(steal.get("opponent_id") or 0)
            resource = str(steal.get("stolen_resource") or "resource")
            if not player_id or not opponent_id:
                return
            # CHECK_MODE=False: option A — no resource name in Events
            try:
                from core.debug_mode import is_check_mode

                if is_check_mode():
                    message = f"steals {resource} from P{opponent_id}"
                else:
                    message = f"steals a card from P{opponent_id}"
            except Exception:
                message = f"steals {resource} from P{opponent_id}"
            gui = getattr(game, "gui", None)
            if gui is None:
                return

            for entry in list(getattr(gui, "twitter", []) or [])[-12:]:
                try:
                    if isinstance(entry, dict):
                        existing_player = int(entry.get("player_id") or 0)
                        existing_message = str(entry.get("message") or "")
                    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        existing_player = int(entry[0] or 0)
                        existing_message = str(entry[1] or "")
                    else:
                        existing_player = 0
                        existing_message = str(entry)
                    if existing_player == player_id and existing_message == message:
                        return
                except Exception:
                    continue

            if hasattr(gui, "add_tweet"):
                gui.add_tweet(player_id, message, update=False)
            else:
                if not hasattr(gui, "twitter") or not isinstance(getattr(gui, "twitter", None), list):
                    gui.twitter = []
                gui.twitter.append([player_id, message])
        except Exception:
            pass

    def _stop_execution_animations(self, game: Game) -> None:
        """Stop all GUI animations before continuing Execution."""
        try:
            if game.gui is not None and hasattr(game.gui, "stop_all_animations"):
                game.gui.stop_all_animations(redraw_board=True)
            elif game.gui is not None:
                game.gui.animate_queue_elements.clear()
                game.gui.draw_board_base(game.board)
                game.gui.draw_all_permanent_buildings(game.board)
                pygame.display.update()
        except Exception:
            pass

    def _execute_roll_dice_with_feedback(self, game: Game) -> dict:
        """Roll dice, play sound, and display the two dice images."""
        try:
            if game.gui is not None and hasattr(game.gui, "play_dice_roll_sound"):
                game.gui.play_dice_roll_sound()
            else:
                self._play_sound("DICEROLL")
        except Exception:
            self._play_sound("DICEROLL")

        # A fresh dice roll starts a fresh visible-turn window. Older completed
        # snapshots are useful only until the next dice roll begins.
        self._clear_completed_turn_snapshot(game)

        result = game.execute_roll_dice_action()

        try:
            game.last_dice_roll_result = dict(result or {})
        except Exception:
            pass

        try:
            if result.get("total") == 7:
                # Dice total 7 never produces resources. Clear stale RP fallbacks
                # from the previous roll before any popup/RCΔ snapshot is made.
                self._clear_stale_resource_production_state(game)
                if game.gui is not None and hasattr(game.gui, "play_robber_sound"):
                    game.gui.play_robber_sound()
                else:
                    self._play_sound("DANGER", fallback="ERROR")
        except Exception:
            self._play_sound("DANGER", fallback="ERROR")

        try:
            if result.get("total") != 7 and result.get("producing_tile_ids"):
                setattr(game, "_pending_resource_production_animation", result)
        except Exception:
            pass

        try:
            dice = result.get("dice")
            if game.gui is not None and hasattr(game.gui, "show_dices"):
                game.gui.show_dices(dice if dice else result.get("total"))
        except Exception:
            pass

        return result

    def _redraw_after_execution_event(self, game: Game) -> None:
        """Best-effort GUI refresh after an Execution-phase state change."""
        try:
            if game.gui is None:
                return
            confirmation_active = self._has_human_robber_confirmation(game)
            if confirmation_active:
                self._clear_human_robber_visual_queue(game)

            game.gui.draw_board_base(game.board)
            game.gui.draw_all_permanent_buildings(game.board)
            game.gui.update_round_turn(game, special=False)
            game.gui.update_scoreboard(game)
            try:
                if hasattr(game.gui, "draw_execution_debug_panel"):
                    game.gui.draw_execution_debug_panel(game)
            except Exception:
                pass
            try:
                GUIHumanPlayer().show_buttons_HP(game, analysis_tf=False)
            except Exception:
                # Button redraw is helpful but should not crash click handling.
                pass
            self._disable_buttons_during_human_robber_flow(game)
            game.gui.draw_guidance()
            try:
                if is_human_road_guidance_active(game):
                    draw_human_road_guidance(game)
            except Exception:
                pass
            try:
                if is_human_buy_guidance_active(game):
                    draw_human_buy_guidance(game)
            except Exception:
                pass
            try:
                if is_discard_panel_active(game):
                    draw_discard_panel(game)
            except Exception:
                pass
            try:
                if is_trade_bank_panel_active(game):
                    draw_trade_bank_panel(game)
            except Exception:
                pass
            try:
                if is_trade_player_panel_active(game):
                    draw_trade_player_panel(game)
            except Exception:
                pass
            try:
                if is_play_dcard_panel_active(game):
                    draw_play_dcard_panel(game)
            except Exception:
                pass
            try:
                if is_twp_counter_panel_active(game):
                    draw_twp_counter_panel(game)
                elif is_incoming_twp_panel_active(game):
                    draw_incoming_twp_panel(game)
            except Exception:
                pass
            try:
                if is_twp_auto_rules_panel_active(game):
                    draw_twp_auto_rules_panel(game)
            except Exception:
                pass
            # W3: post-game strip + Statistics (priority over trade/DCard panels).
            try:
                if bool(getattr(game, "game_over", False)) or is_post_game_ui_active(game):
                    ensure_post_game_ui(game)
                    draw_game_over_panel(game)
            except Exception:
                pass
            try:
                if not confirmation_active and hasattr(game.gui, "draw_robber_from_board"):
                    game.gui.draw_robber_from_board(game.board)
            except Exception:
                pass
            pygame.display.update()

            # v045-inspired green radius-60 production highlight. This runs after
            # the normal redraw so the circles remain visible instead of being
            # immediately erased by the board refresh.
            try:
                pending = getattr(game, "_pending_resource_production_animation", None)
                if pending and hasattr(game.gui, "show_tiles_providing_RP"):
                    setattr(game, "_pending_resource_production_animation", None)
                    game.gui.show_tiles_providing_RP(
                        game.board,
                        int(pending.get("total", 0)),
                        "N",
                        tile_ids=list(pending.get("producing_tile_ids", []) or []),
                    )
            except Exception:
                pass

            # Execution-phase buy/build feedback: animate the newly built
            # road/settlement/city using the same queue/reveal mechanics as
            # Initial Placement.  The Game object sets this pending item at the
            # exact mutation point; the redraw consumes it once.
            try:
                pending_build = getattr(game, "_pending_execution_build_animation", None)
                if pending_build and hasattr(game.gui, "show_execution_build_animation"):
                    setattr(game, "_pending_execution_build_animation", None)
                    game.gui.show_execution_build_animation(pending_build, getattr(game, "board", None))
            except Exception:
                pass

            # Repaint v045-style human robber guidance after the normal redraw.
            # While a confirmation is active, _show_pending_robber_human_guidance()
            # draws only the selected tile/victim and OKY/NOK. Do not add the
            # previous final-victim feedback on top of that selected-only view.
            self._show_pending_robber_human_guidance(game)
            try:
                suppress_victim_feedback = bool(getattr(game, "_suppress_robber_victim_feedback", False))
            except Exception:
                suppress_victim_feedback = False
            try:
                build_guidance_active = bool(is_human_road_guidance_active(game) or is_human_buy_guidance_active(game))
            except Exception:
                build_guidance_active = False
            if not confirmation_active and not suppress_victim_feedback and not build_guidance_active:
                self._show_last_robber_victim_feedback(game)
            try:
                if hasattr(game.gui, "update_twitter"):
                    game.gui.update_twitter()
            except Exception:
                pass

            # Last-pass repaint for human build guidance.  Some redraw steps
            # intentionally clear old robber/steal visuals or refresh panels.
            # Draw city/settlement/road guidance at the very end so highlighted
            # options remain visible and clickable.
            try:
                if is_human_road_guidance_active(game):
                    try:
                        game.gui.animations_enabled = True
                    except Exception:
                        pass
                    draw_human_road_guidance(game)
            except Exception:
                pass
            try:
                if is_human_buy_guidance_active(game):
                    try:
                        game.gui.animations_enabled = True
                    except Exception:
                        pass
                    draw_human_buy_guidance(game)
            except Exception:
                pass
        except Exception:
            pass

    def _find_clicked_tile(self, pos: Tuple[int, int]):
        """Return tile id if the click is close to a rendered tile center."""
        for tile_id, center in POSITIONS.get("tiles", {}).items():
            if center is None:
                continue
            dx = pos[0] - center[0]
            dy = pos[1] - center[1]
            if dx * dx + dy * dy <= 22 * 22:
                return tile_id
        return None

    def _find_clicked_intersection(self, pos: Tuple[int, int]):
        """Return intersection id if the click is close to a rendered intersection."""
        for inter_id, center in POSITIONS.get("intersections", {}).items():
            if center is None:
                continue
            dx = pos[0] - center[0]
            dy = pos[1] - center[1]
            if dx * dx + dy * dy <= 24 * 24:
                return inter_id
        return None

    def _steal_opponent_for_intersection(self, game: Game, intersection_id: int):
        """Map a clicked candidate victim intersection to its opponent id."""
        pending = getattr(game, "pending_robber_steal", {}) or {}
        for row in list(pending.get("stealable_opponents", []) or []):
            try:
                ids = {int(x) for x in list(row.get("adjacent_intersections", []) or [])}
                if int(intersection_id) in ids:
                    return int(row.get("opponent_id"))
            except Exception:
                continue
        return None

    def _human_current_player(self, game: Game) -> bool:
        try:
            player = game.get_current_player()
        except Exception:
            player = None
        try:
            return bool(getattr(player, "is_human", False))
        except Exception:
            return False

    def _show_pending_robber_human_guidance(self, game: Game) -> None:
        """Repaint v045-style robber choice highlights after a normal redraw."""
        try:
            if game.gui is None or not self._human_current_player(game):
                return

            confirmation = self._human_robber_confirmation(game)
            if confirmation:
                self._draw_human_robber_confirmation(game, confirmation)
                return

            state = str(getattr(game, "state", ""))
            if state in {"MoveRobber", "RobberMoveRequired", "SetRobber"}:
                tile_ids = self._legal_human_robber_tiles(game)
                if tile_ids and hasattr(game.gui, "show_available_robber_tiles"):
                    game.gui.show_available_robber_tiles(game.board, tile_ids)
            elif state == "StealSelectOpponent":
                pending = getattr(game, "pending_robber_steal", {}) or {}
                opponents = list(pending.get("stealable_opponents", []) or [])
                if opponents and hasattr(game.gui, "show_available_steal_opponents"):
                    game.gui.show_available_steal_opponents(game.board, opponents)
        except Exception:
            pass

    def _show_last_robber_victim_feedback(self, game: Game) -> None:
        """Keep the red victim highlight visible after scoreboard/board redraws."""
        try:
            if game.gui is None or not hasattr(game.gui, "show_victim_of_steal"):
                return

            intersections = []

            # First try the explicit select-opponent result.
            sel = getattr(game, "last_robber_steal_selection", None) or {}
            if isinstance(sel, dict):
                selected = sel.get("selected_opponent") or {}
                if isinstance(selected, dict):
                    intersections = list(selected.get("adjacent_intersections", []) or [])

            # Exact-one-target auto steals may not have a separate selection result;
            # keep the pending robber-steal record as the fallback source.
            if not intersections:
                pending = getattr(game, "pending_robber_steal", {}) or {}
                selected_id = pending.get("selected_opponent_id")
                for row in list(pending.get("stealable_opponents", []) or []):
                    try:
                        if int(row.get("opponent_id")) == int(selected_id):
                            intersections = list(row.get("adjacent_intersections", []) or [])
                            break
                    except Exception:
                        continue

            if intersections:
                game.gui.show_victim_of_steal(game.board, intersections)
        except Exception:
            pass


    def _human_robber_confirmation(self, game: Game) -> dict | None:
        """Return the pending human robber OKY/OKN confirmation, if any."""
        try:
            data = getattr(game, "pending_human_robber_confirmation", None)
            if isinstance(data, dict) and data.get("active"):
                return data
        except Exception:
            pass
        return None

    def _set_human_robber_confirmation(self, game: Game, *, stage: str, **values) -> None:
        """Store a human robber-flow confirmation in a small dictionary."""
        try:
            game.pending_human_robber_confirmation = {"active": True, "stage": str(stage), **values}
        except Exception:
            pass

    def _clear_human_robber_confirmation(self, game: Game) -> None:
        """Clear pending human robber confirmation and its OKY/OKN click center."""
        try:
            game.pending_human_robber_confirmation = {"active": False}
        except Exception:
            pass
        try:
            if getattr(game, "gui", None) is not None and hasattr(game.gui, "human_guidance"):
                game.gui.human_guidance.confirm_center = None
        except Exception:
            pass
        self._clear_human_robber_visual_queue(game)

    def _clear_human_robber_visual_queue(self, game: Game, *, disable_animations: bool = True) -> None:
        """Remove transient robber/victim guidance animations from the GUI queue.

        Robber confirmation screens are intentionally exclusive: after the human
        selects a robber tile or a victim, only that selected item should pulse.
        Clearing the queue before rendering the selected item prevents old legal
        tile choices, the old robber-tile ring, and old victim-choice rings from
        leaking into the confirmation view.

        When normal build guidance starts after a steal, we still need to clear
        the stale victim animation, but we must *not* leave animations disabled.
        City/settlement/road guidance uses the same animate_queue_elements path
        as Initial Placement; if animations_enabled remains False, the Road
        button opens a selector that has no visible road guidance.
        """
        try:
            gui = getattr(game, "gui", None)
            if gui is not None and hasattr(gui, "animate_queue_elements"):
                gui.animate_queue_elements.clear()
                if bool(disable_animations):
                    gui.animations_enabled = False
        except Exception:
            pass

    def _has_human_robber_confirmation(self, game: Game) -> bool:
        """Return True if a human robber/victim confirmation screen is active."""
        return self._human_robber_confirmation(game) is not None

    def _draw_ok_confirmation_icons(self, game: Game, center: tuple[int, int] | None) -> None:
        """Draw the existing OKY / NOK png icons around a selected robber item."""
        if center is None:
            return
        try:
            x, y = center
            if hasattr(game.gui, "human_guidance"):
                game.gui.human_guidance.confirm_center = (int(x), int(y))
            WIN.blit(IMAGES["OKY"]["default"], (int(x) + 35, int(y) - 45))
            WIN.blit(IMAGES["NOK"]["default"], (int(x) + 35, int(y) + 10))
            pygame.display.update()
        except Exception:
            pass

    def _draw_selected_robber_tile_guidance(self, game: Game, tile_id: int) -> None:
        """Draw the selected robber tile with the same small radius as guidance.

        The large radius-60 robber ring belongs to the final robber-placement
        animation.  While the human is still confirming OKY/OKN, keep the visual
        consistent with the available-tile guidance radius.
        """
        try:
            tile_id = int(tile_id)
        except Exception:
            return

        center = POSITIONS.get("tiles", {}).get(tile_id)
        if center is None:
            return

        try:
            # Draw the robber image only; do not ask GUI.show_tile_having_robber()
            # for its final radius-60 highlight yet.
            if hasattr(game.gui, "show_tile_having_robber"):
                game.gui.show_tile_having_robber(game.board, tile_id, "N")
        except Exception:
            pass

        try:
            color = COLORS.get("WHITE", (255, 255, 255))
            radius = int(ROBBER_AVAILABLE_TILE_HIGHLIGHT_RADIUS)
            pygame.draw.circle(
                WIN,
                color,
                center,
                radius,
                2,
                draw_top_right=True,
                draw_top_left=True,
                draw_bottom_right=True,
                draw_bottom_left=True,
            )
            if hasattr(game.gui, "animate_queue_elements"):
                game.gui.animate_queue_elements.append((tuple(center), color, radius, "tile"))
                game.gui.animations_enabled = True
            if hasattr(game.gui, "_animate_elements"):
                game.gui._animate_elements(getattr(game, "board", None))
        except Exception:
            pass

    def _clear_steal_animation_for_build_guidance(self, game: Game) -> None:
        """Stop lingering steal/victim animation before buy/build guidance starts.

        The previous implementation reused the robber-confirmation clear helper,
        which also set gui.animations_enabled=False.  That correctly stopped the
        steal/victim pulse, but it accidentally disabled the next human guidance
        animation.  Road guidance then opened without visible highlighted roads.
        """
        try:
            game._suppress_robber_victim_feedback = True
        except Exception:
            pass
        self._clear_human_robber_visual_queue(game, disable_animations=False)
        try:
            gui = getattr(game, "gui", None)
            if gui is not None:
                gui.animations_enabled = True
        except Exception:
            pass


    def _legal_human_robber_tiles(self, game: Game) -> list[int]:
        """Return legal new robber tiles for the current pending human 7-flow."""
        tile_ids: list[int] = []
        try:
            pending = getattr(game, "pending_seven_roll", {}) or {}
            tile_ids = [int(x) for x in list(pending.get("legal_robber_tile_ids", []) or [])]
        except Exception:
            tile_ids = []
        if not tile_ids:
            try:
                from core.game_7logic import legal_robber_tile_ids
                tile_ids = [int(x) for x in list(legal_robber_tile_ids(game) or [])]
            except Exception:
                tile_ids = []
        return tile_ids

    def _steal_intersections_for_opponent(self, game: Game, opponent_id: int) -> list[int]:
        """Return highlighted adjacent intersections for one pending steal opponent."""
        pending = getattr(game, "pending_robber_steal", {}) or {}
        for row in list(pending.get("stealable_opponents", []) or []):
            try:
                if int(row.get("opponent_id")) == int(opponent_id):
                    return [int(x) for x in list(row.get("adjacent_intersections", []) or [])]
            except Exception:
                continue
        return []

    def _draw_human_robber_confirmation(self, game: Game, confirmation: dict) -> None:
        """Render only the selected robber tile/victim plus OKY/NOK icons."""
        try:
            # Selected-only rule: old robber guidance, legal-tile rings and
            # victim-choice rings must not remain visible while OKY/NOK is shown.
            self._clear_human_robber_visual_queue(game)
            stage = str(confirmation.get("stage") or "")
            if stage == "tile":
                tile_id = int(confirmation.get("tile_id"))
                center = POSITIONS.get("tiles", {}).get(tile_id)
                # This is a temporary visual choice only. The board state is
                # not changed until OKY confirms execute_move_robber_action().
                self._draw_selected_robber_tile_guidance(game, tile_id)
                if hasattr(game.gui, "draw_guidance_text"):
                    game.gui.draw_guidance_text("Confirm robber placement?", y_offset=25)
                self._draw_ok_confirmation_icons(game, center)
                return

            if stage == "victim":
                opponent_id = int(confirmation.get("opponent_id"))
                inter_id = confirmation.get("intersection_id")
                intersections = self._steal_intersections_for_opponent(game, opponent_id)
                if hasattr(game.gui, "show_victim_of_steal") and intersections:
                    # Red final-looking cue means: this victim is selected, but the
                    # random steal itself is still not executed until OKY.
                    game.gui.show_victim_of_steal(game.board, intersections)
                center = POSITIONS.get("intersections", {}).get(int(inter_id)) if inter_id is not None else None
                if hasattr(game.gui, "draw_guidance_text"):
                    game.gui.draw_guidance_text(f"Confirm steal from P{opponent_id}?", y_offset=25)
                self._draw_ok_confirmation_icons(game, center)
                return
        except Exception:
            pass

    def _select_human_robber_tile_for_confirmation(self, game: Game, tile_id: int) -> None:
        """Select a robber tile and wait for OKY/NOK instead of moving immediately."""
        try:
            tile_id = int(tile_id)
        except Exception:
            self._play_sound("ERROR")
            return
        legal_tiles = self._legal_human_robber_tiles(game)
        if legal_tiles and tile_id not in set(legal_tiles):
            self._play_sound("ERROR")
            return
        self._set_human_robber_confirmation(game, stage="tile", tile_id=tile_id)
        self._play_sound("BUTTON")
        self._redraw_after_execution_event(game)

    def _select_human_robber_victim_for_confirmation(self, game: Game, intersection_id: int, opponent_id: int) -> None:
        """Select a steal victim in the multi-opponent case and wait for OKY/NOK."""
        self._set_human_robber_confirmation(
            game,
            stage="victim",
            intersection_id=int(intersection_id),
            opponent_id=int(opponent_id),
        )
        self._play_sound("BUTTON")
        self._redraw_after_execution_event(game)

    def _confirm_human_robber_tile(self, game: Game, confirmation: dict) -> None:
        """OKY for selected robber tile: now move robber and continue the 7-flow."""
        try:
            tile_id = int(confirmation.get("tile_id"))
        except Exception:
            self._play_sound("ERROR")
            return

        self._clear_human_robber_confirmation(game)
        result = game.execute_move_robber_action(tile_id)
        steal_result = None
        if result.get("ok"):
            self._play_sound("BUTTON")
            selected_opponent_id = result.get("selected_opponent_id")
            if selected_opponent_id and hasattr(game, "execute_robber_random_steal_action"):
                # Exactly one adjacent opponent remains automatic for now.
                try:
                    steal_result = game.execute_robber_random_steal_action(int(selected_opponent_id))
                    if steal_result and steal_result.get("ok"):
                        self._play_sound("STEAL", fallback="BELL")
                except Exception as exc:
                    steal_result = {"ok": False, "warnings": [str(exc)]}
        else:
            self._play_sound("ERROR")

        print(f"Robber tile OKY → {result}; steal → {steal_result}")

        try:
            move_ok = bool((result or {}).get("ok"))
            state_after = str((result or {}).get("state_after") or getattr(game, "state", ""))
            selected_opponent_id = (result or {}).get("selected_opponent_id")
            opponents = list((result or {}).get("stealable_opponents") or [])
        except Exception:
            move_ok = False
            state_after = str(getattr(game, "state", ""))
            selected_opponent_id = None
            opponents = []

        if move_ok and (selected_opponent_id is not None or not opponents or state_after == "ActionSelection"):
            if steal_result is not None:
                self._ensure_robber_steal_event_visible(game, {"steal": steal_result})
            self._resume_human_action_selection_after_robber_flow(game)

        self._redraw_after_execution_event(game)

    def _confirm_human_robber_victim(self, game: Game, confirmation: dict) -> None:
        """OKY for selected victim: execute random steal and finish the human 7-flow."""
        try:
            opponent_id = int(confirmation.get("opponent_id"))
        except Exception:
            self._play_sound("ERROR")
            return

        self._clear_human_robber_confirmation(game)
        result = game.execute_select_steal_opponent_action(int(opponent_id), execute_steal=True)
        if result.get("ok"):
            self._play_sound("STEAL", fallback="BELL")
        else:
            self._play_sound("ERROR")
        print(f"Robber victim OKY → opponent={opponent_id}, result={result}")

        try:
            select_ok = bool((result or {}).get("select", {}).get("ok"))
        except Exception:
            select_ok = False
        if select_ok:
            self._ensure_robber_steal_event_visible(game, {"steal": (result or {}).get("steal")})
            self._resume_human_action_selection_after_robber_flow(game)

        self._redraw_after_execution_event(game)

    def _cancel_human_robber_confirmation(self, game: Game, confirmation: dict) -> None:
        """OKN for robber confirmation: return to tile or victim choices."""
        stage = str((confirmation or {}).get("stage") or "")
        self._clear_human_robber_confirmation(game)
        self._play_sound("BUTTON")
        # No game-state mutation is reversed here because tile/victim choices are
        # only committed after OKY.  If victim selection is cancelled, the robber
        # remains on the already-confirmed new tile and choices are shown again.
        print(f"Robber confirmation OKN → cancelled {stage}")
        self._redraw_after_execution_event(game)

    def _handle_human_robber_confirmation_click(self, game: Game, pos: Tuple[int, int]) -> bool:
        """Handle OKY/NOK for pending robber tile/victim confirmations."""
        confirmation = self._human_robber_confirmation(game)
        if not confirmation:
            return False

        conf = None
        try:
            conf = game.gui.handle_confirmation_click(pos)
        except Exception:
            conf = None

        if conf == "OKY":
            stage = str(confirmation.get("stage") or "")
            if stage == "tile":
                self._confirm_human_robber_tile(game, confirmation)
            elif stage == "victim":
                self._confirm_human_robber_victim(game, confirmation)
            else:
                self._play_sound("ERROR")
                return True
            # G3: clear "Confirm robber / steal …?" after OKY
            try:
                game.gui.clear_guidance_text(y_offset=25)
            except Exception:
                pass
            return True

        if conf == "OKN":
            self._cancel_human_robber_confirmation(game, confirmation)
            try:
                game.gui.clear_guidance_text(y_offset=25)
            except Exception:
                pass
            return True

        # While a confirmation is active, all other clicks are intentionally ignored.
        self._play_sound("ERROR")
        return True

    @staticmethod
    def _normalise_turn_detail_vector(value: object) -> list[int]:
        """Return a safe 6-slot resource delta vector for UI snapshots."""
        if not isinstance(value, (list, tuple)):
            return [0, 0, 0, 0, 0, 0]
        result: list[int] = []
        for item in list(value)[:6]:
            try:
                result.append(int(item or 0))
            except Exception:
                result.append(0)
        while len(result) < 6:
            result.append(0)
        return result

    @staticmethod
    def _resource_delta_vector_for_snapshot(resource_name: object, amount: int) -> list[int]:
        """Build a 6-slot resource delta vector for snapshot fallbacks."""
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

    def _snapshot_turn_details_for_popup(self, game: Game) -> None:
        """Preserve the just-completed turn details before advance_turn clears them.

        begin_execution_turn() correctly clears the live current-turn ledger for
        the next player. The '?' popup, however, is often inspected immediately
        after a non-human turn auto-advances. Store a compact per-player copy so
        that the popup shows the just-completed turn instead of falling back to
        stale older production data.
        """
        rows_by_player: dict[int, list[tuple[str, list[int]]]] = {}
        dice_total = self._current_dice_total(game)
        is_robber_roll = dice_total == 7

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

        for player in list(getattr(game, "players", []) or []):
            try:
                player_id = int(getattr(player, "id", 0) or 0)
            except Exception:
                continue

            rows: list[tuple[str, list[int]]] = []
            if hasattr(game, "get_turn_detail_rows_for_player"):
                try:
                    for label, vector in list(game.get_turn_detail_rows_for_player(player) or []):
                        vec = self._normalise_turn_detail_vector(vector)
                        if any(vec):
                            rows.append((str(label), vec))
                except Exception:
                    rows = []

            if not rows:
                for label, attr_name in row_specs:
                    vec = self._normalise_turn_detail_vector(getattr(player, attr_name, None))
                    if any(vec):
                        rows.append((label, vec))

            # A rolled 7 cannot produce resources. If stale player fields or an
            # older ledger still contain RP rows, strip them before freezing the
            # completed-turn snapshot.
            if is_robber_roll and rows:
                rows = [
                    (label, vector)
                    for label, vector in rows
                    if not str(label).strip().lower().startswith("rp")
                ]

            # Add robust same-turn fallbacks before advance_turn() clears state.
            # These mirror the GUI fallbacks, but freeze them into the completed
            # turn snapshot so both the '?' popup and the red RCΔ scoreboard line
            # can still show the just-completed rcard changes after auto-advance.
            try:
                existing_labels = {str(label).strip().lower() for label, _ in rows}
            except Exception:
                existing_labels = set()

            try:
                last_rp = getattr(game, "last_resource_production_result", None) or {}
                if (not is_robber_roll) and isinstance(last_rp, dict):
                    produced_by_player = dict(last_rp.get("produced_by_player") or {})
                    blocked_by_player = dict(last_rp.get("blocked_by_player") or {})
                    produced_vec = self._normalise_turn_detail_vector(
                        produced_by_player.get(player_id) or produced_by_player.get(str(player_id))
                    )
                    blocked_vec = self._normalise_turn_detail_vector(
                        blocked_by_player.get(player_id) or blocked_by_player.get(str(player_id))
                    )
                    rp_rows: list[tuple[str, list[int]]] = []
                    if any(produced_vec) and "rp" not in existing_labels:
                        rp_rows.append(("RP", produced_vec))
                        existing_labels.add("rp")
                    if any(blocked_vec) and "rp corr" not in existing_labels:
                        rp_rows.append(("RP Corr", blocked_vec))
                        existing_labels.add("rp corr")
                    if rp_rows:
                        rows = rp_rows + rows
            except Exception:
                pass

            try:
                last_steal = getattr(game, "last_robber_steal_result", None) or {}
                if isinstance(last_steal, dict) and last_steal.get("ok") and "steal" not in existing_labels:
                    thief_id = int(last_steal.get("player_id") or 0)
                    victim_id = int(last_steal.get("opponent_id") or 0)
                    amount = 1 if player_id == thief_id else -1 if player_id == victim_id else 0
                    if amount:
                        steal_vec = self._resource_delta_vector_for_snapshot(last_steal.get("stolen_resource"), amount)
                        if any(steal_vec):
                            rows.append(("Steal", steal_vec))
                            existing_labels.add("steal")
            except Exception:
                pass

            if rows:
                rows_by_player[player_id] = rows

        try:
            game.last_completed_turn_detail_rows_by_player = rows_by_player
            game.last_completed_turn_detail_context = {
                "round": int(getattr(game, "round", 0) or 0),
                "turn": int(getattr(game, "turn", 0) or 0),
                "dice_roll": getattr(game, "dice_roll", None),
                "dice_total": dice_total,
                "is_robber_roll": is_robber_roll,
                "current_player_id": int(getattr(game.get_current_player(), "id", 0) or 0) if hasattr(game, "get_current_player") else None,
            }
        except Exception:
            pass

    @staticmethod
    def _normalised_human_player_ids() -> list[int]:
        """Return HP_ID as a flat list of integer player ids."""
        ids = HP_ID
        if ids is None:
            return []
        if isinstance(ids, int):
            return [int(ids)]
        try:
            result: list[int] = []
            for item in list(ids):
                if isinstance(item, (list, tuple, set)):
                    for sub in item:
                        try:
                            result.append(int(sub))
                        except Exception:
                            pass
                else:
                    try:
                        result.append(int(item))
                    except Exception:
                        pass
            return result
        except Exception:
            return []

    def _is_current_player_human(self, game: Game) -> bool:
        """Return True when the current turn belongs to a configured human player."""
        try:
            player = game.get_current_player() if hasattr(game, "get_current_player") else game.players[game.turn - 1]
        except Exception:
            player = None

        try:
            if bool(getattr(player, "is_human", False)):
                return True
        except Exception:
            pass

        if not HUMAN_PLAYER:
            return False

        try:
            current_turn = int(getattr(game, "turn", 0) or 0)
        except Exception:
            current_turn = 0

        return current_turn in self._normalised_human_player_ids()

    def _finish_basic_human_execution_turn_after_roll(self, game: Game) -> None:
        """Resume the same human player's ActionSelection after a non-7 roll.

        A normal human Execution turn does not end immediately after rolling dice.
        The dice roll produces resources, then the same human player must be able
        to Trade with Bank, buy/build, or explicitly press End Turn.  Therefore
        this helper leaves the turn on the same player, refreshes scanner output,
        and lets the button panel activate TwB / Buy / Build from the fresh scan.
        """
        try:
            if hasattr(game, "continue_action_selection_after_action"):
                game.continue_action_selection_after_action(
                    "after_human_non7_roll",
                    player=game.get_current_player() if hasattr(game, "get_current_player") else None,
                    action_result={"action": "Roll Dices", "ok": True, "total": self._current_dice_total(game)},
                    clear_forced_locks=True,
                )
            else:
                # execute_roll_dice_action() already sets this on non-7 rolls, but keep
                # this as a safety net for older saved/runtime states.
                game.state = "ActionSelection"
                game.state_1 = ""
                game.state_2 = ""
                if isinstance(getattr(game, "pending_seven_roll", None), dict):
                    game.pending_seven_roll["active"] = False
                if isinstance(getattr(game, "pending_robber_steal", None), dict):
                    game.pending_robber_steal["active"] = False
                    game.pending_robber_steal["awaiting_human_target"] = False
                if hasattr(game, "refresh_strategy_context"):
                    game.refresh_strategy_context("after_human_non7_roll", force=True)
                if hasattr(game, "refresh_viable_actions"):
                    game.refresh_viable_actions("after_human_non7_roll")
        except Exception:
            pass

        # Do not snapshot or advance here.  The turn snapshot belongs to the
        # later explicit End Turn click after the human has optionally traded or
        # bought/built.
        try:
            if getattr(game, "gui", None) is not None:
                GUIHumanPlayer.button_next_turn2(game.gui, game, active=False)
                GUIHumanPlayer().button_roll_dices(game, False)
                GUIHumanPlayer().button_end_turn(game, True)
        except Exception:
            pass

    def _is_human_robber_flow_active(self, game: Game) -> bool:
        """Return True while a human rolled-7 robber/steal decision is pending."""
        try:
            if not self._is_current_player_human(game):
                return False
        except Exception:
            return False

        if self._human_robber_confirmation(game):
            return True

        state = str(getattr(game, "state", ""))
        if state in {"MoveRobber", "RobberMoveRequired", "SetRobber", "StealSelectOpponent"}:
            return True

        try:
            pending_7 = getattr(game, "pending_seven_roll", {}) or {}
            if isinstance(pending_7, dict) and pending_7.get("active"):
                return True
        except Exception:
            pass

        try:
            pending_steal = getattr(game, "pending_robber_steal", {}) or {}
            if isinstance(pending_steal, dict) and pending_steal.get("awaiting_human_target"):
                return True
        except Exception:
            pass

        return False

    def _disable_buttons_during_human_robber_flow(self, game: Game) -> None:
        """Disable normal action buttons while human robber guidance is active."""
        if not self._is_human_robber_flow_active(game):
            return
        try:
            GUIHumanPlayer.button_next_turn2(game.gui, game, active=False)
            GUIHumanPlayer().button_roll_dices(game, False)
            GUIHumanPlayer().button_end_turn(game, False)
        except Exception:
            pass

    def _begin_human_robber_flow_after_7(self, game: Game) -> None:
        """Pause after a human rolled 7 and show robber tile guidance."""
        try:
            game._suppress_robber_victim_feedback = False
        except Exception:
            pass
        try:
            if getattr(game, "gui", None) is not None:
                GUIHumanPlayer.button_next_turn2(game.gui, game, active=False)
                GUIHumanPlayer().button_roll_dices(game, False)
                GUIHumanPlayer().button_end_turn(game, False)
        except Exception:
            pass
        self._show_pending_robber_human_guidance(game)

    def _resume_human_action_selection_after_robber_flow(self, game: Game) -> None:
        """Resume after human robber/steal (7-flow or pre-roll Knight).

        - After **7**: ActionSelection (buy/trade/end open).
        - After **Knight before roll**: AwaitingDiceRoll (only Roll Dices).
        """
        self._clear_human_robber_confirmation(game)

        resume_result = None
        try:
            if hasattr(game, "resume_action_selection_after_human_robber_flow"):
                resume_result = game.resume_action_selection_after_human_robber_flow("after_human_robber_flow")
            else:
                if isinstance(getattr(game, "pending_seven_roll", None), dict):
                    game.pending_seven_roll["active"] = False
                if isinstance(getattr(game, "pending_robber_steal", None), dict):
                    game.pending_robber_steal["active"] = False
                    game.pending_robber_steal["awaiting_human_target"] = False
                game.state = "ActionSelection"
                game.state_1 = ""
                game.state_2 = ""
                try:
                    game.refresh_strategy_context("after_human_robber_flow", force=True)
                except Exception:
                    pass
                try:
                    game.refresh_viable_actions("after_human_robber_flow")
                except Exception:
                    pass
        except Exception as exc:
            resume_result = {"ok": False, "reason": str(exc)}
            try:
                if isinstance(getattr(game, "pending_seven_roll", None), dict):
                    game.pending_seven_roll["active"] = False
                if isinstance(getattr(game, "pending_robber_steal", None), dict):
                    game.pending_robber_steal["active"] = False
                    game.pending_robber_steal["awaiting_human_target"] = False
                game.state = "ActionSelection"
                game.state_1 = ""
                game.state_2 = ""
            except Exception:
                pass

        resume_to = ""
        try:
            resume_to = str((resume_result or {}).get("resume_to") or getattr(game, "state", "") or "")
        except Exception:
            resume_to = str(getattr(game, "state", "") or "")

        # Button panel: after Knight → only roll dice; after 7 → End Turn etc.
        try:
            if getattr(game, "gui", None) is not None:
                hp = GUIHumanPlayer()
                if resume_to == "AwaitingDiceRoll" or str((resume_result or {}).get("only_action", "")) == "Roll Dices":
                    # Humans roll via Roll Dices only; PLAY stays off in Execution.
                    hp.button_next_turn2(game, False)
                    hp.button_roll_dices(game, True)
                    hp.button_end_turn(game, False)
                    hp.button_buy_city(game, False)
                    hp.button_buy_settlement(game, False)
                    hp.button_buy_road(game, False)
                    hp.button_buy_dcard(game, False)
                    hp.button_twp(game, False)
                    hp.button_twb(game, False)
                    print("Knight robber complete → only Roll Dices is available")
                else:
                    hp.button_next_turn2(game, False)
                    hp.button_roll_dices(game, False)
                    hp.button_end_turn(game, True)
        except Exception:
            pass

        try:
            game.last_human_robber_resume_result = resume_result
        except Exception:
            pass

    def _finish_human_execution_turn_after_robber_flow(self, game: Game) -> None:
        """Backward-compatible alias; robber completion now resumes ActionSelection."""
        self._resume_human_action_selection_after_robber_flow(game)

    def _handle_human_roll_result(self, game: Game, result: dict) -> None:
        """Advance human non-7 rolls, but pause for robber guidance on 7."""
        try:
            total = int((result or {}).get("total", 0) or 0)
        except Exception:
            total = 0

        if total == 7:
            print("Human rolled 7 → wait for robber tile / steal target selection")
            self._begin_human_robber_flow_after_7(game)
        else:
            print("Human rolled non-7 → resume ActionSelection for same human player")
            self._finish_basic_human_execution_turn_after_roll(game)

    def _minimal_nonhuman_execution_play(self, game: Game) -> None:
        """Compatibility wrapper for the old one-click AI flow.

        The new visible AI flow is two clicks:
        Play -> roll dice and preview; Continue -> consume preview and advance.
        """
        self._roll_nonhuman_to_preview(game)

    def _roll_nonhuman_to_preview(self, game: Game) -> dict:
        """AI Play step: roll dice only and leave the turn on the preview panel."""
        try:
            if game.gui is not None and hasattr(game.gui, "play_dice_roll_sound"):
                game.gui.play_dice_roll_sound()
            else:
                self._play_sound("DICEROLL")
        except Exception:
            self._play_sound("DICEROLL")

        self._clear_completed_turn_snapshot(game)

        if hasattr(game, "ai_roll_to_preview"):
            result = game.ai_roll_to_preview()
            roll_result = result.get("roll_result") if isinstance(result, dict) else None
            if isinstance(roll_result, dict):
                try:
                    game.last_dice_roll_result = dict(roll_result)
                except Exception:
                    pass
                if roll_result.get("total") == 7:
                    self._play_sound("DANGER", fallback="ERROR")
                if roll_result.get("total") != 7 and roll_result.get("producing_tile_ids"):
                    setattr(game, "_pending_resource_production_animation", roll_result)
                try:
                    dice = roll_result.get("dice")
                    if game.gui is not None and hasattr(game.gui, "show_dices"):
                        game.gui.show_dices(dice if dice else roll_result.get("total"))
                except Exception:
                    pass
            return result

        # Fallback for older Game copies.
        result = self._execute_roll_dice_with_feedback(game)
        return {"ok": True, "fallback": True, "roll_result": result}

    def _continue_nonhuman_execution_turn(self, game: Game) -> dict:
        """AI Continue step: consume preview; Slice 1 then advances the turn."""
        self._snapshot_turn_details_for_popup(game)
        if hasattr(game, "continue_ai_execution_turn"):
            result = game.continue_ai_execution_turn()
            robber_result = result.get("robber_result") if isinstance(result, dict) else None
            if robber_result:
                self._ensure_robber_steal_event_visible(game, robber_result)
            return result

        game.advance_turn()
        return {"ok": True, "fallback": True, "action": "advance_turn"}

    def handle_keydown(self, event: pygame.event.Event, game: Game) -> bool:
        """Handle keyboard input for modal panels that need text entry."""
        # BS-1: Esc dismisses Settings confirm / Board Settings stub
        try:
            from gui.gui_settings_button import handle_settings_keydown

            if handle_settings_keydown(game, getattr(event, "key", None)):
                return True
        except Exception:
            pass
        # W3: ESC switches post-game UI to Playboard (review board).
        try:
            if bool(getattr(game, "game_over", False)) or is_post_game_ui_active(game):
                if handle_game_over_key(game, getattr(event, "key", None)):
                    self._redraw_after_execution_event(game)
                    return True
        except Exception:
            pass
        try:
            if is_twp_auto_rules_panel_active(game):
                handled = handle_twp_auto_rules_key(game, event)
                if handled:
                    self._redraw_after_execution_event(game)
                    return True
        except Exception:
            self._play_sound("ERROR")
            return True
        return False

    def handle_mousewheel(self, event: pygame.event.Event, game: Game) -> bool:
        """Handle mouse-wheel scrolling for modal panels."""
        try:
            if is_twp_auto_rules_panel_active(game):
                handled = handle_twp_auto_rules_mousewheel(game, getattr(event, "y", 0))
                if handled:
                    self._redraw_after_execution_event(game)
                    return True
        except Exception:
            self._play_sound("ERROR")
            return True
        return False

    def handle_click(self, pos: Tuple[int, int], game: Game) -> bool:
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(
                    f"{game.id} | {game.state} | event_handler.py | "
                    f"handle_click | pos={pos}\n"
                )

        guidance = game.gui.human_guidance

        # Common button rectangles.  The Human button-panel coordinates live in
        # gui_constants so drawing and click detection stay aligned.
        PLAY_RECT = HUMAN_BUTTON_RECTS.get("next_turn2", pygame.Rect(20, 470, 130, 40))
        ROLL_RECT = HUMAN_BUTTON_RECTS.get("roll_dices", pygame.Rect(200, 405, 130, 40))
        END_RECT = HUMAN_BUTTON_RECTS.get("end_turn", pygame.Rect(200, 470, 130, 40))
        TWP_RECT = HUMAN_BUTTON_RECTS.get("twp", pygame.Rect(200, 330, 60, 40))
        TWB_RECT = HUMAN_BUTTON_RECTS.get("twb", pygame.Rect(270, 330, 60, 40))
        BUY_CITY_RECT = HUMAN_BUTTON_RECTS.get("buy_city", pygame.Rect(140, 275, 40, 40))
        BUY_SETTLEMENT_RECT = HUMAN_BUTTON_RECTS.get("buy_settlement", pygame.Rect(190, 275, 40, 40))
        BUY_ROAD_RECT = HUMAN_BUTTON_RECTS.get("buy_road", pygame.Rect(240, 275, 40, 40))
        BUY_DCARD_RECT = HUMAN_BUTTON_RECTS.get("buy_dcard", pygame.Rect(290, 275, 40, 40))
        TWP_MODE_RED_RECT = HUMAN_BUTTON_RECTS.get("twp_mode_red", pygame.Rect(140, 215, 40, 40))
        TWP_MODE_AI_RECT = HUMAN_BUTTON_RECTS.get("twp_mode_ai", pygame.Rect(190, 215, 40, 40))
        TWP_MODE_AUTO_RECT = HUMAN_BUTTON_RECTS.get("twp_mode_auto", pygame.Rect(240, 215, 40, 40))
        EDIT_TWP_AUTO_RECT = HUMAN_BUTTON_RECTS.get("edit_twp_auto", pygame.Rect(290, 215, 40, 40))

        # BS-1: Settings gear / End-current-game confirm (before most other routing)
        try:
            from gui.gui_settings_button import handle_settings_click

            if handle_settings_click(game, pos):
                return True
        except Exception:
            pass

        # Scoreboard '?' turn-detail toggles. These are active in all phases
        # after the scoreboard has been rendered once. The GUI owns the whole
        # toggle mechanic: same '?' opens/closes the details; there is no
        # separate close button inside the popup.
        try:
            if hasattr(game.gui, "handle_turn_detail_click") and game.gui.handle_turn_detail_click(pos):
                return True
        except Exception:
            pass

        # W3: post-game strip / Statistics owns clicks while game_over.
        # Must run before Execution buy/trade/AI Continue routing.
        try:
            if bool(getattr(game, "game_over", False)) or is_post_game_ui_active(game):
                ensure_post_game_ui(game)
                if handle_game_over_click(game, pos):
                    self._redraw_after_execution_event(game)
                    return True
                # While game is over, swallow remaining clicks (frozen board review
                # still allows ? toggles above; strip/panel already handled).
                return True
        except Exception:
            pass

        # ────────────────────────────────────────────────
        # 1. Confirmation clicks first: robber OKY/NOK, then placement OKY/NOK
        # ────────────────────────────────────────────────
        if self._handle_human_robber_confirmation_click(game, pos):
            return True

        if guidance.state in (
            PlacementState.SETTLEMENT_SELECTED,
            PlacementState.ROAD_SELECTED,
        ):
            conf = game.gui.handle_confirmation_click(pos)

            if conf:
                print(f"Confirmation clicked: {conf}")
                guidance.on_confirmation(conf)
                return True

            # Clicked during confirmation but not on OKY / OKN.
            self._play_sound("ERROR")
            return True

        # TwP Mode row uses the same x-columns as the Buy buttons but lives one
        # row above them.  Even outside Execution the row is visible/inactive;
        # clicking it should be acknowledged with ERROR rather than falling
        # through silently.
        TWP_MODE_RECTS = (
            TWP_MODE_RED_RECT,
            TWP_MODE_AI_RECT,
            TWP_MODE_AUTO_RECT,
            EDIT_TWP_AUTO_RECT,
        )
        if any(rect.collidepoint(pos) for rect in TWP_MODE_RECTS) and game.phase != "Execution":
            self._play_sound("ERROR")
            return True

        # ────────────────────────────────────────────────
        # 2. PLAY / next_turn2 button during InitialPlacement
        # ────────────────────────────────────────────────
        if game.phase == "InitialPlacement" and PLAY_RECT.collidepoint(pos):
            # P3-A: busy / latched → silent reject (no ERROR spam)
            if self._is_ui_input_busy(game):
                return True

            is_placing = guidance.state != PlacementState.IDLE
            button_active = game.gui.check_button("next_turn2")

            if is_placing:
                print("PLAY clicked while still placing → rejected")
                self._play_sound("ERROR")
                return True

            if button_active:
                print("PLAY clicked → advancing initial-placement turn")
                self._play_sound("BUTTON")

                # G1: first PLAY reveals Events + Execution Debug panes
                try:
                    game.gui.reveal_events_and_debug()
                except Exception:
                    try:
                        game.gui.events_debug_revealed = True
                    except Exception:
                        pass

                # BS-1: first PLAY that starts IP → gear needs End-game confirm thereafter
                try:
                    from gui.gui_settings_button import mark_first_play_started

                    mark_first_play_started(game)
                except Exception:
                    try:
                        game.ip_started_via_play = True
                        game.gui.ip_started_via_play = True
                    except Exception:
                        pass

                # P3-A: latch + busy before AI / Markov placement work
                with self._play_continue_busy_scope(game, "ip_play"):
                    print("event_handler calling InitialPlacement.advance_turn")
                    game.ip.advance_turn()
                self._redraw_after_execution_event(game)
                return True

            # PLAY area was clicked, but the button is inactive (idle).
            self._play_sound("ERROR")
            return True

        # ────────────────────────────────────────────────
        # 3. Execution-phase buttons / basic 7 robber click
        # ────────────────────────────────────────────────
        if game.phase == "Execution":

            # Human discard panel is modal during DiscardPending (after a 7).
            # Must run before TwB/TwP/robber so -/+ OK work deterministically.
            try:
                if is_discard_panel_active(game):
                    if handle_discard_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # Execution Debug tabs are display-only (switch diagnostic layer).
            # Handle before TwP/TwB so trade modals do not swallow debug-tab clicks.
            # CHECK_MODE=False: panel is hidden — ignore clicks.
            try:
                from core.debug_mode import should_show_execution_debug

                _dbg_ok = bool(should_show_execution_debug())
            except Exception:
                _dbg_ok = True
            if _dbg_ok:
                try:
                    from gui.gui_execution_debug_panel import handle_execution_debug_panel_click
                    if handle_execution_debug_panel_click(game, pos):
                        try:
                            self._play_sound("BUTTON")
                        except Exception:
                            pass
                        self._redraw_after_execution_event(game)
                        return True
                except Exception:
                    pass

            # The TwP Auto rules editor is modal and owns its clicks while open.
            try:
                if is_twp_auto_rules_panel_active(game):
                    if handle_twp_auto_rules_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # T10 counter builder and Incoming AI→HP TwP offers are modal.
            # Manual mode must wait for HP response before AI continues.
            try:
                if is_twp_counter_panel_active(game):
                    if handle_twp_counter_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
                elif is_incoming_twp_panel_active(game):
                    if handle_incoming_twp_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # If the Trade-with-Player panel is already open, it owns the click.
            # It is modal like TwB: outside clicks are swallowed.
            try:
                if is_trade_player_panel_active(game):
                    if handle_trade_player_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # If the Trade-with-Bank panel is already open, it owns the click.
            # This must run before normal board/button routing so the +/−, OK,
            # NOK and X controls respond deterministically.
            try:
                if is_trade_bank_panel_active(game):
                    if handle_trade_bank_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # Play DCard panel (shared slot with TwB/TwP/discard): Confirm / Cancel /
            # RCard picks for Monopoly and Year of Plenty.
            try:
                if is_play_dcard_panel_active(game):
                    if handle_play_dcard_panel_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # Scoreboard DCard type icons (green border = playable for HP).
            # Opens Play DCard panel; VP is never playable.
            try:
                if handle_scoreboard_dcard_click(game, pos):
                    self._play_sound("BUTTON")
                    self._redraw_after_execution_event(game)
                    return True
            except Exception:
                pass

            # Human Buy Road guidance is modal during Execution: choose one legal
            # scanner road, then confirm with OKY / OKN.
            try:
                if is_human_road_guidance_active(game):
                    if handle_human_road_guidance_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # Human City/Settlement/DCard guidance is modal as well.
            try:
                if is_human_buy_guidance_active(game):
                    if handle_human_buy_guidance_click(game, pos):
                        self._redraw_after_execution_event(game)
                        return True
            except Exception:
                self._play_sound("ERROR")
                return True

            # Incoming Human TwP policy mode row.  These can be changed during
            # Execution, including while it is an AI player's turn.  Red/AI/Auto
            # are mutually exclusive; Edit only opens the future rule editor.
            mode_clicks = (
                # Red and AI are implemented now.  Auto remains visible but
                # inactive until Step 6 adds rule evaluation; including it here
                # makes an Auto click play ERROR instead of being silently ignored.
                (TWP_MODE_RED_RECT, "twp_mode_red", "red"),
                (TWP_MODE_AI_RECT, "twp_mode_ai", "ai"),
                (TWP_MODE_AUTO_RECT, "twp_mode_auto", "auto"),
            )
            for mode_rect, button_name, mode_name in mode_clicks:
                if mode_rect.collidepoint(pos):
                    if game.gui.check_button(button_name):
                        self._play_sound("BUTTON")
                        try:
                            if hasattr(game, "toggle_human_twp_mode"):
                                game.toggle_human_twp_mode(mode_name)
                            else:
                                current = str(getattr(game, "human_twp_mode", "manual") or "manual").lower()
                                setattr(game, "human_twp_mode", "manual" if current == mode_name else mode_name)
                        except Exception:
                            self._play_sound("ERROR")
                        self._redraw_after_execution_event(game)
                        return True
                    self._play_sound("ERROR")
                    return True

            if EDIT_TWP_AUTO_RECT.collidepoint(pos):
                if game.gui.check_button("edit_twp_auto"):
                    self._play_sound("BUTTON")
                    try:
                        open_twp_auto_rules_panel(game)
                        if hasattr(game, "emit_twitter_event"):
                            game.emit_twitter_event(None, "Edit TwP Auto rules opened.")
                    except Exception:
                        self._play_sound("ERROR")
                    self._redraw_after_execution_event(game)
                    return True
                self._play_sound("ERROR")
                return True

            # Human TwP button. GUIHumanPlayer draws this button at the canonical
            # HUMAN_BUTTON_RECTS["twp"] location and stores its active state under
            # the lower-case key "twp".
            if TWP_RECT.collidepoint(pos):
                is_human = self._is_current_player_human(game)
                if is_human and game.gui.check_button("twp"):
                    self._play_sound("BUTTON")
                    if not is_discard_panel_active(game):
                        try:
                            close_play_dcard_panel(game)
                        except Exception:
                            pass
                        open_trade_player_panel(game)
                    self._redraw_after_execution_event(game)
                    return True

                self._play_sound("ERROR")
                return True

            # Human TwB button. GUIHumanPlayer draws this button at HUMAN_BUTTON_RECTS["twb"].
            # and stores its active state under the lower-case key "twb".
            if TWB_RECT.collidepoint(pos):
                is_human = self._is_current_player_human(game)
                if is_human and game.gui.check_button("twb"):
                    self._play_sound("BUTTON")
                    if not is_discard_panel_active(game):
                        try:
                            close_play_dcard_panel(game)
                        except Exception:
                            pass
                        open_trade_bank_panel(game)
                    self._redraw_after_execution_event(game)
                    return True

                self._play_sound("ERROR")
                return True

            if BUY_CITY_RECT.collidepoint(pos):
                if self._is_current_player_human(game) and game.gui.check_button("buy_city"):
                    self._play_sound("BUTTON")
                    self._clear_steal_animation_for_build_guidance(game)
                    opened = open_human_city_guidance(game)
                    if not opened:
                        self._play_sound("ERROR")
                    self._redraw_after_execution_event(game)
                    if opened:
                        try:
                            game.gui.animations_enabled = True
                            draw_human_buy_guidance(game)
                        except Exception:
                            pass
                    return True
                self._play_sound("ERROR")
                return True

            if BUY_SETTLEMENT_RECT.collidepoint(pos):
                if self._is_current_player_human(game) and game.gui.check_button("buy_settlement"):
                    self._play_sound("BUTTON")
                    self._clear_steal_animation_for_build_guidance(game)
                    opened = open_human_settlement_guidance(game)
                    if not opened:
                        self._play_sound("ERROR")
                    self._redraw_after_execution_event(game)
                    if opened:
                        try:
                            game.gui.animations_enabled = True
                            draw_human_buy_guidance(game)
                        except Exception:
                            pass
                    return True
                self._play_sound("ERROR")
                return True

            if BUY_ROAD_RECT.collidepoint(pos):
                if self._is_current_player_human(game) and game.gui.check_button("buy_road"):
                    self._play_sound("BUTTON")
                    self._clear_steal_animation_for_build_guidance(game)
                    opened = open_human_road_guidance(game)
                    if not opened:
                        self._play_sound("ERROR")
                    self._redraw_after_execution_event(game)
                    if opened:
                        try:
                            game.gui.animations_enabled = True
                            draw_human_road_guidance(game)
                        except Exception:
                            pass
                    return True
                self._play_sound("ERROR")
                return True

            if BUY_DCARD_RECT.collidepoint(pos):
                if self._is_current_player_human(game) and game.gui.check_button("buy_dcard"):
                    # Buy DCard is now immediate: button click executes the buy.
                    # No OKY/OKN confirmation panel is opened.
                    self._play_sound("BUTTON")
                    result = game.execute_human_buy_dcard_action() if hasattr(game, "execute_human_buy_dcard_action") else {"ok": False, "reason": "missing_execute_human_buy_dcard_action"}
                    if not bool((result or {}).get("ok")):
                        self._play_sound("ERROR")
                    self._redraw_after_execution_event(game)
                    return True
                self._play_sound("ERROR")
                return True

            # PLAY is the left button at [20, 470, 130, 40].
            # For AI/non-human players it now rolls dice only and stops on the
            # Execution Debug preview.  The right slot Continue consumes that
            # preview and advances the turn.
            if PLAY_RECT.collidepoint(pos):
                # P3-A: while busy/latched, never ERROR — silent swallow
                if self._is_ui_input_busy(game):
                    return True

                if game.gui.check_button("next_turn2"):
                    self._play_sound("BUTTON")
                    # G1: first PLAY (IP or Execution) reveals Events + Debug
                    try:
                        game.gui.reveal_events_and_debug()
                    except Exception:
                        try:
                            game.gui.events_debug_revealed = True
                        except Exception:
                            pass
                    # G10 + G12: close '?' panel; Events seat banner; focus Debug
                    try:
                        on_play = getattr(game.gui, "on_play_or_seat_change", None)
                        if callable(on_play):
                            on_play(game)
                        else:
                            closer = getattr(game.gui, "close_turn_detail_panel", None)
                            if callable(closer):
                                closer(restore_modal=True)
                    except Exception:
                        pass
                    self._stop_execution_animations(game)
                    is_human = self._is_current_player_human(game)

                    dice_roll = getattr(game, "dice_roll", None)
                    dice_not_rolled = dice_roll in (None, 0, "", [])

                    if is_human:
                        if dice_not_rolled and hasattr(game, "execute_roll_dice_action"):
                            print("PLAY clicked in Execution by human → roll dice")
                            with self._play_continue_busy_scope(game, "human_play_roll"):
                                result = self._execute_roll_dice_with_feedback(game)
                                self._handle_human_roll_result(game, result)
                        else:
                            if self._is_human_robber_flow_active(game):
                                print("PLAY clicked during human robber flow → rejected")
                                self._play_sound("ERROR")
                            else:
                                print("PLAY clicked in Execution by human → advance_turn")
                                with self._play_continue_busy_scope(game, "human_play_advance"):
                                    self._snapshot_turn_details_for_popup(game)
                                    game.advance_turn()
                                    # New seat after human end-turn: banner for next player
                                    try:
                                        on_play = getattr(game.gui, "on_play_or_seat_change", None)
                                        if callable(on_play):
                                            on_play(game)
                                    except Exception:
                                        pass
                    else:
                        if dice_not_rolled:
                            print("PLAY clicked in Execution by non-human → roll dice and preview")
                            # P3-A: disable PLAY immediately; outer busy covers roll+strategy
                            with self._play_continue_busy_scope(game, "ai_play_roll"):
                                self._roll_nonhuman_to_preview(game)
                        else:
                            print("PLAY clicked in Execution by non-human after dice → use Continue")
                            self._play_sound("ERROR")

                    self._redraw_after_execution_event(game)
                    return True

                self._play_sound("ERROR")
                return True

            if ROLL_RECT.collidepoint(pos):
                if game.gui.check_button("roll_dices"):
                    self._stop_execution_animations(game)
                    result = self._execute_roll_dice_with_feedback(game)
                    print(f"Roll Dices clicked → {result}")

                    if self._is_current_player_human(game):
                        self._handle_human_roll_result(game, result)

                    self._redraw_after_execution_event(game)
                    return True

                self._play_sound("ERROR")
                return True

            if END_RECT.collidepoint(pos):
                is_human = self._is_current_player_human(game)

                # Forced human discard (7-roll): never End/Continue while panel open.
                try:
                    if is_discard_panel_active(game):
                        self._play_sound("ERROR")
                        return True
                except Exception:
                    pass

                # P3-A: Continue (AI) — busy first (silent), then active gate
                if not is_human:
                    if self._is_ui_input_busy(game):
                        # Swallow re-clicks during pipeline (no ERROR buffer feel)
                        return True
                    if game.gui.check_button("continue_ai"):
                        self._play_sound("BUTTON")
                        print("Continue clicked in Execution by non-human → consume preview")
                        with self._play_continue_busy_scope(game, "ai_continue"):
                            self._continue_nonhuman_execution_turn(game)
                            # After AI turn advances seat, banner next seat (G10)
                            try:
                                on_play = getattr(game.gui, "on_play_or_seat_change", None)
                                if callable(on_play) and str(getattr(game, "phase", "")) == "Execution":
                                    # Only when turn advanced to a new player awaiting PLAY
                                    dice = getattr(game, "dice_roll", None)
                                    if dice in (None, 0, "", []):
                                        on_play(game)
                            except Exception:
                                pass
                        self._redraw_after_execution_event(game)
                        return True

                if is_human and game.gui.check_button("end_turn"):
                    self._play_sound("BUTTON")
                    self._snapshot_turn_details_for_popup(game)
                    game.advance_turn()
                    self._redraw_after_execution_event(game)
                    return True

                self._play_sound("ERROR")
                return True

            # Human robber steal target selection. This branch is reached only
            # after the robber tile has been OKY-confirmed and multiple adjacent
            # stealable opponents are available.  Clicking a victim now selects
            # that victim and waits for OKY/NOK; it does not steal immediately.
            if str(getattr(game, "state", "")) == "StealSelectOpponent":
                inter_id = self._find_clicked_intersection(pos)
                if inter_id is not None:
                    opponent_id = self._steal_opponent_for_intersection(game, int(inter_id))
                    if opponent_id is None:
                        self._play_sound("ERROR")
                        return True
                    self._select_human_robber_victim_for_confirmation(game, int(inter_id), int(opponent_id))
                    return True

            # After rolling a 7, clicking a valid land tile selects the robber
            # destination and waits for OKY/NOK.  The board state is not changed
            # until OKY confirms execute_move_robber_action(tile_id).
            if str(getattr(game, "state", "")) in {"MoveRobber", "RobberMoveRequired", "SetRobber"}:
                tile_id = self._find_clicked_tile(pos)
                if tile_id is not None:
                    self._select_human_robber_tile_for_confirmation(game, int(tile_id))
                    return True

        # ────────────────────────────────────────────────
        # 4. Board clicks during InitialPlacement
        # ────────────────────────────────────────────────
        if game.phase == "InitialPlacement":
            if game.ip.handle_click(pos):
                return True

            if guidance.state != PlacementState.IDLE:
                if guidance.on_board_click(pos):
                    return True

        return False
