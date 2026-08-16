"""Main entry point for the Catan game.

Updated for the modular Execution-phase flow:
- InitialPlacement still starts exactly as before (unless LOAD_GAME at cold boot).
- LOAD_GAME + SAVED_GAME (core.constants) resume a full Saved_Game and skip IP.
- New Game / Settings end-session always start a fresh IP session (ignore LOAD_GAME).
- Execution turn scans are triggered by Game.begin_execution_turn() / Game.advance_turn().
- GUI buttons are refreshed every loop so Roll Dices / End Turn state can change.
- F9 can write a Phase-0 AI baseline capture when phase0_baseline_hooks is installed.
- Closing the window no longer runs the "game over" celebration by accident.
- W3: after game_over the loop stays alive for Statistics ↔ Playboard / New Game.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pygame

from core.game import Game

try:
    from core.phase0_baseline_hooks import install_phase0_baseline_hooks
except Exception:  # pragma: no cover - Phase-0 module is optional until installed.
    install_phase0_baseline_hooks = None
from gui.gui import GUI
from gui.gui_human_player import GUIHumanPlayer
from gui.gui_constants import WIN, COLORS, POSITIONS, initialize_sounds
from core.initial_placement_phase_manager import InitialPlacement
from gui.event_handler import EventHandler

try:
    from gui.gui_game_over_panel import (
        draw_game_over_panel,
        ensure_post_game_ui,
        is_post_game_ui_active,
        consume_new_game_request,
    )
except Exception:  # pragma: no cover
    def draw_game_over_panel(game):
        return None

    def ensure_post_game_ui(game):
        return {}

    def is_post_game_ui_active(game):
        return False

    def consume_new_game_request(game):
        return False


def _install_phase0_baseline_support() -> None:
    """Install Phase-0 AI baseline hooks if the optional module is available."""
    if install_phase0_baseline_hooks is None:
        print("Phase0 baseline hooks module not available (import failed).")
        return
    try:
        install_phase0_baseline_hooks(Game)
    except Exception as exc:
        print(f"Phase-0 baseline hooks could not be installed: {exc}")


def _emit_phase0_event(game: Game, player_id, message: str) -> None:
    """Show F9/F8 result in the Events / twitter panel (and keep console in sync)."""
    text = str(message or "").strip()
    if not text:
        return
    print(text)
    # Prefer Game.emit_twitter_event → gui.add_tweet (canonical event feed).
    try:
        emit = getattr(game, "emit_twitter_event", None)
        if callable(emit):
            emit(player_id, text, update=True)
            return
    except Exception:
        pass
    try:
        gui = getattr(game, "gui", None)
        if gui is None:
            return
        if hasattr(gui, "add_tweet"):
            try:
                gui.add_tweet(player_id, text, update=True)
            except TypeError:
                gui.add_tweet(player_id, text)
        elif hasattr(gui, "add_twitter"):
            gui.add_twitter(player_id, text)
        elif hasattr(gui, "update_twitter"):
            if not isinstance(getattr(gui, "twitter", None), list):
                gui.twitter = []
            gui.twitter.append({"player_id": player_id, "message": text})
            gui.update_twitter()
    except Exception:
        pass


def _capture_phase0_baseline_from_hotkey(game: Game, *, hotkey: str = "F9") -> None:
    """Capture a Phase0 baseline for the *current turn player* (focus player).

    Notes:
    - Focus is always the current-turn player from game.get_current_player().
    - JSON also includes every player's strategic_direction snapshot.
    - Prefer focusing the pygame window before pressing F9/F8.
    - In VS Code, F9 is often "Toggle Breakpoint" — use F8 if F9 does nothing.
    - On success/failure a short line is written to the Events (twitter) panel.
    """
    try:
        player = game.get_current_player()
    except Exception:
        player = getattr(game, "current_player", None)
    player_id = getattr(player, "id", None) if player is not None else None
    player_color = str(getattr(player, "color", "") or "")
    focus_label = f"P{player_id}{player_color}" if player_id is not None else "P?"

    saver = getattr(game, "save_phase0_baseline", None)
    if not callable(saver):
        msg = (
            f"{hotkey}: Phase0 capture unavailable (hooks not installed). "
            "Check startup for 'Phase0 baseline hooks installed successfully.'"
        )
        _emit_phase0_event(game, player_id, msg)
        return

    # Build a readable label (filename stem). Hooks take label/reason only —
    # they always focus the *current* player (no player_id kwarg).
    try:
        r = int(getattr(game, "round", 0) or 0)
        t = int(getattr(game, "turn", 0) or 0)
    except Exception:
        r, t = 0, 0
    label = f"manual_{hotkey}_R{r}T{t}_{focus_label}"

    try:
        # Prefer force_refresh=True so strategy/scanner are current.
        try:
            result = saver(
                label=label,
                reason=f"hotkey_{hotkey}",
                refresh_before_capture=True,
                force_refresh=True,
            )
        except TypeError:
            # Older hooks without force_refresh=
            try:
                result = saver(
                    label=label,
                    reason=f"hotkey_{hotkey}",
                    refresh_before_capture=True,
                )
            except TypeError:
                result = saver(label=label, reason=f"hotkey_{hotkey}")
    except Exception as exc:
        _emit_phase0_event(
            game,
            player_id,
            f"{hotkey}: Phase0 capture failed ({exc})",
        )
        return

    if isinstance(result, dict) and result.get("ok"):
        path = (
            result.get("baseline_path")
            or result.get("path")
            or result.get("file")
            or "?"
        )
        # Short path for the feed; full path on console via _emit print
        try:
            from pathlib import Path as _Path

            short = _Path(str(path)).name
        except Exception:
            short = str(path)
        hints = result.get("empty_hints") if isinstance(result, dict) else None
        msg = f"{hotkey}: Phase0 saved for {focus_label} → {short}"
        _emit_phase0_event(game, player_id, msg)
        if hints:
            print(f"  empty_hints: {hints}")
            try:
                # Second line if strategy/snapshot looks thin (useful while testing)
                hint_text = ", ".join(str(h) for h in list(hints)[:2])
                if hint_text:
                    _emit_phase0_event(
                        game,
                        player_id,
                        f"{hotkey}: notes — {hint_text}",
                    )
            except Exception:
                pass
        print(f"  full path: {path}")
        print(f"  focus player: {focus_label}")
    else:
        err = ""
        if isinstance(result, dict):
            err = str(result.get("error") or result.get("reason") or "")
        _emit_phase0_event(
            game,
            player_id,
            f"{hotkey}: Phase0 capture failed{(' — ' + err) if err else ''}",
        )


def _ensure_execution_scan(game: Game) -> None:
    if game.phase != "Execution":
        return
    if bool(getattr(game, "game_over", False)):
        return
    if getattr(game, "current_viable_action_scan", None) is None:
        try:
            game.refresh_viable_actions("main_loop_ensure_execution_scan")
        except Exception as exc:
            print(f"Could not refresh viable actions: {exc}")


def _board_settings_open(game: Game) -> bool:
    """True while Board Settings menu/editor/CIBI occupies the right column."""
    try:
        from gui.gui_settings_button import MODE_BOARD_SETTINGS, settings_mode

        return settings_mode(game) == MODE_BOARD_SETTINGS
    except Exception:
        return False


def _render_runtime_gui(game: Game, gui: GUI, gui_hp: GUIHumanPlayer) -> None:
    gui.update_round_turn(game, special=False)
    gui.update_scoreboard(game)
    bs_open = _board_settings_open(game)
    # While Board Settings is open: keep playboard + scoreboard; hide TwP Mode /
    # Human button panel and right-side Events/Debug (menu uses that column).
    if not bs_open:
        try:
            if hasattr(gui, "update_twitter"):
                gui.update_twitter()
        except Exception:
            pass
        try:
            gui.draw_execution_debug_panel(game)
        except Exception:
            pass
        gui_hp.show_buttons_HP(game, analysis_tf=False)
    # BS-1: Settings gear (+ end-game confirm / board-settings on right)
    # When mode is off, draw_settings_button must not paint the Board Settings menu.
    try:
        from gui.gui_settings_button import draw_settings_button

        draw_settings_button(game)
    except Exception:
        pass
    # W3 post-game chrome (strip + optional Statistics body)
    try:
        if bool(getattr(game, "game_over", False)) or is_post_game_ui_active(game):
            ensure_post_game_ui(game)
            draw_game_over_panel(game)
    except Exception:
        pass


def _create_fresh_game_session(gui=None):
    """Build a new Game + InitialPlacement + GUI bindings for New Game."""
    today = datetime.now().strftime("%Y%m%d")
    game = Game(
        sequence_number=1,
        id_=today,
        phase="InitialPlacement",
        state="None",
        state_1="0",
        state_2="0",
        myplayers=None,
        board_name="Base_Random",
    )
    game.ip = InitialPlacement(game)
    if gui is None:
        gui = GUI(round_number=game.round, turn=game.turn, game=game)
    else:
        try:
            gui.game = game
            gui.round_number = game.round
            gui.turn = game.turn
        except Exception:
            gui = GUI(round_number=game.round, turn=game.turn, game=game)
    game.gui = gui
    return game, gui


def resolve_saved_game_path(filename: str) -> Optional[Path]:
    """Locate a Saved_Game file.

    Search order for relative names:
      1. as given under cwd (supports ``saved_games/foo.txt`` or legacy root)
      2. ``saved_games/<basename>`` under cwd and project root (new default)
      3. project root / basename (legacy location)
      4. optional SAVE_PATH (Logs) for older copies
    Absolute paths are used as-is.
    """
    name = str(filename or "").strip()
    if not name:
        return None
    candidates: list[Path] = []
    p = Path(name)
    if p.is_absolute():
        candidates.append(p)
    else:
        basename = p.name
        cwd = Path.cwd()
        candidates.append(cwd / name)
        candidates.append(cwd / "saved_games" / basename)
        try:
            root = Path(__file__).resolve().parent
            candidates.append(root / name)
            candidates.append(root / "saved_games" / basename)
            candidates.append(root / basename)  # legacy root dumps
        except Exception:
            pass
        try:
            from core.constants import SAVE_PATH, SAVED_GAMES_DIR

            candidates.append(Path(SAVED_GAMES_DIR) / basename)
            candidates.append(Path(SAVE_PATH) / name)
            candidates.append(Path(SAVE_PATH) / basename)
        except Exception:
            pass
    seen: set[str] = set()
    for cand in candidates:
        try:
            key = str(cand.resolve()) if cand.exists() else str(cand)
        except Exception:
            key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        try:
            if cand.is_file():
                return cand
        except Exception:
            continue
    return None


def try_load_game_at_boot(game: Game) -> Dict[str, Any]:
    """Cold-boot only: if LOAD_GAME, restore SAVED_GAME into ``game``.

    Returns a result dict:
      ok, skipped, reason?, filename?, path?, load_result?
    Does not paint UI. New Game paths must not call this.
    """
    try:
        from core.constants import LOAD_GAME, SAVED_GAME
    except Exception as exc:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"constants_import_failed: {exc}",
        }

    if not bool(LOAD_GAME):
        return {"ok": False, "skipped": True, "reason": "LOAD_GAME=False"}

    filename = str(SAVED_GAME or "").strip()
    if not filename:
        return {
            "ok": False,
            "skipped": False,
            "reason": "SAVED_GAME empty",
            "filename": filename,
        }

    path = resolve_saved_game_path(filename)
    if path is None:
        return {
            "ok": False,
            "skipped": False,
            "reason": f"saved game file not found: {filename}",
            "filename": filename,
        }

    try:
        load_result = game.load_game(str(path), strict=True)
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "reason": f"load_game failed: {exc}",
            "filename": filename,
            "path": str(path),
        }

    if not isinstance(load_result, dict) or not load_result.get("ok"):
        return {
            "ok": False,
            "skipped": False,
            "reason": "load_game returned not ok",
            "filename": filename,
            "path": str(path),
            "load_result": load_result,
        }

    return {
        "ok": True,
        "skipped": False,
        "filename": filename,
        "path": str(path),
        "load_result": load_result,
        "round": getattr(game, "round", None),
        "turn": getattr(game, "turn", None),
        "phase": getattr(game, "phase", None),
        "state": getattr(game, "state", None),
        "game_over": bool(getattr(game, "game_over", False)),
    }


def _enter_loaded_session(
    game: Game, gui: GUI, gui_hp: GUIHumanPlayer, *, boot_info: Optional[Dict[str, Any]] = None
) -> None:
    """Paint UI after a successful load_game; never runs Initial Placement."""
    WIN.fill(COLORS["LGRAY"])
    try:
        if hasattr(gui, "stop_all_animations"):
            gui.stop_all_animations(redraw_board=False)
        if hasattr(gui, "resume_animations"):
            gui.resume_animations()
        for attr in (
            "animate_queue_elements",
            "animate_queue_intersections",
            "animate_queue_roads",
            "animate_queue_tiles",
        ):
            q = getattr(gui, attr, None)
            if isinstance(q, list):
                q.clear()
    except Exception:
        pass

    # Treat load as mid-game: show Events/Debug; Settings first-PLAY gate satisfied.
    try:
        gui.events_debug_revealed = True
    except Exception:
        pass
    try:
        gui.ip_started_via_play = True
        game.ip_started_via_play = True
    except Exception:
        pass
    try:
        from gui.gui_settings_button import ensure_ui_settings

        ensure_ui_settings(game)
        game.ui_settings["mode"] = "off"
        game.ui_settings["board_settings_open"] = False
        game.ui_settings["board_settings_page"] = "menu"
        game.ui_settings["confirm_visible"] = False
        game.ui_settings["request_end_session_for_settings"] = False
        game.ui_settings["message"] = ""
        game.ui_settings["status_line"] = ""
    except Exception:
        pass

    try:
        gui.game = game
        gui.round_number = game.round
        gui.turn = game.turn
    except Exception:
        pass
    game.gui = gui

    # Terrain/ports first, then permanent pieces. display_fresh_board alone is the
    # empty IP board (no roads/settlements/cities/robber).
    try:
        if hasattr(gui, "draw_board_base"):
            gui.draw_board_base(game.board)
        else:
            gui.display_fresh_board(game.board, scoreboard_tf=False)
    except Exception:
        try:
            gui.display_fresh_board(game.board, scoreboard_tf=False)
        except Exception:
            pass
    try:
        if hasattr(gui, "draw_all_permanent_buildings"):
            gui.draw_all_permanent_buildings(game.board)
    except Exception as exc:
        print(f"Loaded session: draw permanent buildings failed: {exc}")
    try:
        if hasattr(gui, "draw_robber_from_board"):
            gui.draw_robber_from_board(game.board)
    except Exception:
        pass

    try:
        gui.update_round_turn(game, special=False)
    except Exception:
        pass
    try:
        gui.update_scoreboard(game)
    except Exception:
        pass

    game_over = bool(getattr(game, "game_over", False))
    if game_over:
        try:
            ensure_post_game_ui(game)
            draw_game_over_panel(game)
        except Exception:
            pass
    else:
        try:
            if str(getattr(game, "phase", "") or "") == "Execution":
                if getattr(game, "current_viable_action_scan", None) is None:
                    game.refresh_viable_actions("enter_loaded_session")
        except Exception as exc:
            print(f"Loaded session: viable scan failed: {exc}")
        try:
            gui_hp.show_buttons_HP(game, analysis_tf=False)
        except Exception:
            pass
        try:
            gui.draw_execution_debug_panel(game)
        except Exception:
            pass
        try:
            if hasattr(gui, "update_twitter"):
                gui.update_twitter()
        except Exception:
            pass

    try:
        from gui.gui_settings_button import draw_settings_button

        draw_settings_button(game)
    except Exception:
        pass

    info = boot_info or {}
    print(
        "DEBUG: Loaded session ready — "
        f"R{getattr(game, 'round', '?')}T{getattr(game, 'turn', '?')} "
        f"phase={getattr(game, 'phase', None)} state={getattr(game, 'state', None)} "
        f"game_over={game_over} "
        f"file={info.get('path') or info.get('filename') or '?'}"
    )
    _render_runtime_gui(game, gui, gui_hp)
    pygame.display.update()


def _start_session(game: Game, gui: GUI, gui_hp: GUIHumanPlayer, *, allow_load_game: bool) -> bool:
    """Start either loaded Execution/GameOver or Initial Placement.

    Returns True if a saved game was loaded (caller may set game_over_announced).
    ``allow_load_game`` is True only on cold boot — New Game must pass False.
    """
    if allow_load_game:
        boot = try_load_game_at_boot(game)
        if boot.get("ok"):
            _enter_loaded_session(game, gui, gui_hp, boot_info=boot)
            return True
        if not boot.get("skipped"):
            print(
                "WARNING: LOAD_GAME requested but load failed — "
                f"{boot.get('reason') or 'unknown'}. Falling back to Initial Placement."
            )
    _start_initial_placement(game, gui, gui_hp)
    return False


def _start_initial_placement(game: Game, gui: GUI, gui_hp: GUIHumanPlayer) -> None:
    WIN.fill(COLORS["LGRAY"])
    # Clear any leftover placement/robber animations from a prior aborted session
    # (GUI object is often reused across New Game / Settings abort).
    try:
        if hasattr(gui, "stop_all_animations"):
            gui.stop_all_animations(redraw_board=False)
        if hasattr(gui, "resume_animations"):
            gui.resume_animations()
        for attr in (
            "animate_queue_elements",
            "animate_queue_intersections",
            "animate_queue_roads",
            "animate_queue_tiles",
        ):
            q = getattr(gui, attr, None)
            if isinstance(q, list):
                q.clear()
    except Exception:
        pass
    # G1: Events + Debug stay hidden until first PLAY
    try:
        gui.events_debug_revealed = False
    except Exception:
        pass
    # BS-1: first-PLAY gate for Settings confirm (reset each session)
    try:
        gui.ip_started_via_play = False
        game.ip_started_via_play = False
        from gui.gui_settings_button import ensure_ui_settings

        ensure_ui_settings(game)
        game.ui_settings["mode"] = "off"
        game.ui_settings["board_settings_open"] = False
        game.ui_settings["board_settings_page"] = "menu"
        game.ui_settings["confirm_visible"] = False
        game.ui_settings["request_end_session_for_settings"] = False
        game.ui_settings["message"] = ""
        game.ui_settings["status_line"] = ""
    except Exception:
        pass
    gui.display_fresh_board(game.board, scoreboard_tf=True)
    gui.update_round_turn(game, special=True)
    gui.update_scoreboard(game)
    try:
        gui.draw_execution_debug_panel(game)
    except Exception:
        pass
    gui_hp.show_buttons_HP(game, analysis_tf=False)
    try:
        from gui.gui_settings_button import draw_settings_button

        draw_settings_button(game)
    except Exception:
        pass
    pygame.display.update()

    print("DEBUG: Starting Initial Placement...")
    game.ip.current_step = 0
    game.ip.run()
    print("DEBUG: Initial Placement started. Use Play button to advance turns (including human P3).")
    _ensure_execution_scan(game)
    _render_runtime_gui(game, gui, gui_hp)
    pygame.display.update()


def _run_game_over_animation(game: Game, gui: GUI) -> None:
    """Legacy stub — W3 keeps the interactive post-game UI in the main loop."""
    print("Game over – post-game UI active (Statistics / Playboard / New Game)")
    try:
        ensure_post_game_ui(game)
        draw_game_over_panel(game)
        pygame.display.update()
    except Exception:
        pass


def main():
    """Main entry point for the Catan game."""
    print("DEBUG: main() STARTED - first line")

    _install_phase0_baseline_support()
    print("DEBUG: phase0_baseline_support installed")

    pygame.init()
    print("DEBUG: pygame initialized")

    initialize_sounds()
    print("DEBUG: sounds initialized")
    clock = pygame.time.Clock()

    game, gui = _create_fresh_game_session()
    gui_hp = GUIHumanPlayer()
    event_handler = EventHandler()

    # Cold boot only: honor LOAD_GAME / SAVED_GAME (skip IP when load succeeds).
    loaded_at_boot = _start_session(game, gui, gui_hp, allow_load_game=True)

    running = True
    user_quit = False
    # Avoid re-firing game-over chrome if we already entered a finished save.
    game_over_announced = bool(loaded_at_boot and getattr(game, "game_over", False))

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                user_quit = True
                running = False
                break

            if event.type == pygame.KEYDOWN:
                # Phase0 capture: F9 preferred, F8 fallback (VS Code steals F9 for breakpoints).
                if event.key in (pygame.K_F9, pygame.K_F8):
                    hotkey = "F9" if event.key == pygame.K_F9 else "F8"
                    _capture_phase0_baseline_from_hotkey(game, hotkey=hotkey)
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)
                    pygame.display.update()
                    continue

                handled = False
                if hasattr(event_handler, "handle_keydown"):
                    handled = event_handler.handle_keydown(event, game)
                if handled:
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)

            if event.type == pygame.MOUSEWHEEL:
                handled = False
                if hasattr(event_handler, "handle_mousewheel"):
                    handled = event_handler.handle_mousewheel(event, game)
                if handled:
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)

            if event.type == pygame.MOUSEBUTTONDOWN:
                handled = event_handler.handle_click(event.pos, game)
                if handled:
                    _ensure_execution_scan(game)
                    _render_runtime_gui(game, gui, gui_hp)

        if not running:
            break

        # BS-2: Settings “End current game?” Yes — abort without win UI, fresh
        # session like normal start-up (no auto Board Settings menu).
        try:
            from gui.gui_settings_button import consume_end_session_for_settings_request

            if consume_end_session_for_settings_request(game):
                print("DEBUG: End session for settings — fresh session (no win UI, no menu)")
                try:
                    if hasattr(gui, "stop_all_animations"):
                        gui.stop_all_animations(redraw_board=False)
                except Exception:
                    pass
                game, gui = _create_fresh_game_session(gui)
                game_over_announced = False
                # Always fresh IP — do not re-apply LOAD_GAME
                _start_session(game, gui, gui_hp, allow_load_game=False)
                # Like normal boot: mode off, no Board Settings auto-open
                try:
                    if hasattr(gui, "resume_animations"):
                        gui.resume_animations()
                except Exception:
                    pass
                _render_runtime_gui(game, gui, gui_hp)
                pygame.display.update()
                continue
        except Exception as exc:
            print(f"End session for settings failed: {exc}")

        # W3/W4: New Game — screenshots already taken in request_new_game();
        # recreate the session in-place.
        try:
            if consume_new_game_request(game):
                paths = getattr(game, "last_endgame_screenshots", None) or (
                    (getattr(game, "post_game_ui", None) or {}).get("screenshot_paths")
                )
                if paths:
                    print(f"DEBUG: Endgame screenshots saved: {paths}")
                print("DEBUG: New Game requested — starting a fresh session")
                game, gui = _create_fresh_game_session(gui)
                game_over_announced = False
                # Always fresh IP — do not re-apply LOAD_GAME
                _start_session(game, gui, gui_hp, allow_load_game=False)
                continue
        except Exception as exc:
            print(f"New Game failed: {exc}")

        # Keep the loop alive after game_over so Statistics/Playboard stay usable.
        if game.game_over:
            if not game_over_announced:
                _run_game_over_animation(game, gui)
                game_over_announced = True
            try:
                ensure_post_game_ui(game)
            except Exception:
                pass
            # G8: avoid scoreboard/button thrash under Statistics (reduces flicker).
            view = "statistics"
            try:
                pgui = getattr(game, "post_game_ui", None) or {}
                view = str(pgui.get("view") or "statistics")
            except Exception:
                pass
            if view != "statistics":
                try:
                    gui.update_scoreboard(game)
                except Exception:
                    pass
                try:
                    gui_hp.show_buttons_HP(game, analysis_tf=False)
                except Exception:
                    pass
            try:
                draw_game_over_panel(game)
            except Exception:
                pass
            pygame.display.update()
            clock.tick(60)
            continue

        _ensure_execution_scan(game)

        game.gui.human_guidance.draw()
        game.gui.animate_continuous()

        gui_hp.show_buttons_HP(game, analysis_tf=False)
        try:
            gui.draw_execution_debug_panel(game)
        except Exception:
            pass
        # Keep gear + confirm chrome in sync every frame (No must erase prompt)
        try:
            from gui.gui_settings_button import draw_settings_button

            draw_settings_button(game)
        except Exception:
            pass
        try:
            if is_post_game_ui_active(game):
                draw_game_over_panel(game)
        except Exception:
            pass

        pygame.display.update()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()
