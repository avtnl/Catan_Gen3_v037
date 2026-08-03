"""BS-1: Settings gear chrome + mid-game “End current game?” confirm.

Product (locked):
- Gear bottom-left under scoreboard; always visible.
- Enabled until Game Over (then visible + disabled).
- Before first PLAY that starts Initial Placement → open Board Settings (stub until BS-3).
- After that first PLAY → confirm End current game? Yes/No to the right of gear.
- Yes → hard-cancel flag for BS-2 session reset (request_end_session_for_settings).
- No → dismiss confirm.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, Tuple

import pygame

from gui.gui_constants import (
    WIN,
    COLORS,
    Font,
    IMAGES,
    SOUNDS,
    SETTINGS_BUTTON_RECT,
    SETTINGS_END_GAME_CONFIRM_STRIP_RECT,
    settings_end_game_confirm_rects,
)

MODE_OFF = "off"
MODE_CONFIRM_END = "confirm_end"
MODE_BOARD_SETTINGS = "board_settings"  # shell for BS-3+

_VALID_MODES = frozenset({MODE_OFF, MODE_CONFIRM_END, MODE_BOARD_SETTINGS})


def _empty_ui_settings() -> Dict[str, Any]:
    return {
        "mode": MODE_OFF,
        "confirm_visible": False,
        "board_settings_page": "menu",
        "message": "",
        # BS-2: main loop consumes this to recreate session like normal start-up
        "request_end_session_for_settings": False,
        # BS-3: Board Settings menu open
        "board_settings_open": False,
        "board_source": None,
        "board_source_path": "",
        "status_line": "",
    }


def ensure_ui_settings(game: Any) -> Dict[str, Any]:
    """Return mutable ``game.ui_settings`` dict (create if missing)."""
    if game is None:
        return _empty_ui_settings()
    state = getattr(game, "ui_settings", None)
    if not isinstance(state, dict):
        state = _empty_ui_settings()
        try:
            game.ui_settings = state
        except Exception:
            pass
    base = _empty_ui_settings()
    for key, default in base.items():
        state.setdefault(key, default)
    mode = str(state.get("mode") or MODE_OFF)
    if mode not in _VALID_MODES:
        state["mode"] = MODE_OFF
    state["confirm_visible"] = mode == MODE_CONFIRM_END
    # Mirror first-play flag on gui for easy access
    try:
        gui = getattr(game, "gui", None)
        if gui is not None and not hasattr(gui, "ip_started_via_play"):
            gui.ip_started_via_play = False
    except Exception:
        pass
    return state


def is_first_play_done(game: Any) -> bool:
    """True after first successful PLAY that starts / advances Initial Placement."""
    try:
        gui = getattr(game, "gui", None)
        if gui is not None and bool(getattr(gui, "ip_started_via_play", False)):
            return True
    except Exception:
        pass
    try:
        return bool(getattr(game, "ip_started_via_play", False))
    except Exception:
        return False


def mark_first_play_started(game: Any) -> None:
    """Call when PLAY successfully starts Initial Placement progression."""
    try:
        if game is not None:
            game.ip_started_via_play = True
    except Exception:
        pass
    try:
        gui = getattr(game, "gui", None)
        if gui is not None:
            gui.ip_started_via_play = True
    except Exception:
        pass


def is_settings_enabled(game: Any) -> bool:
    """Gear clickable unless Game Over, post-game UI, or End-game confirm is open."""
    try:
        if bool(getattr(game, "game_over", False)):
            return False
    except Exception:
        pass
    try:
        from gui.gui_game_over_panel import is_post_game_ui_active

        if is_post_game_ui_active(game):
            return False
    except Exception:
        pass
    # While "End current game?" is showing, gear is disabled (Yes/No only)
    try:
        if settings_mode(game) == MODE_CONFIRM_END:
            return False
    except Exception:
        pass
    try:
        if settings_mode(game) == MODE_BOARD_SETTINGS:
            return False
    except Exception:
        pass
    return True


def settings_mode(game: Any) -> str:
    return str(ensure_ui_settings(game).get("mode") or MODE_OFF)


def dismiss_settings_confirm(game: Any) -> None:
    """No → hide confirm, re-enable Settings gear, erase prompt/Yes/No pixels."""
    state = ensure_ui_settings(game)
    if state.get("mode") == MODE_CONFIRM_END:
        state["mode"] = MODE_OFF
        state["confirm_visible"] = False
        state["message"] = ""
        # Immediate erase — next draw may only repaint the gear rect
        _clear_end_game_confirm_area(update_display=True)


def open_board_settings(game: Any, *, reason: str = "") -> Dict[str, Any]:
    """Enter Board Settings main menu (BS-3)."""
    try:
        from gui.gui_board_settings import open_board_settings_menu

        return open_board_settings_menu(game, reason=reason)
    except Exception:
        state = ensure_ui_settings(game)
        state["mode"] = MODE_BOARD_SETTINGS
        state["confirm_visible"] = False
        state["board_settings_open"] = True
        state["board_settings_page"] = "menu"
        state["message"] = str(reason or "Settings Board")
        return state


def request_end_session_for_settings(game: Any) -> Dict[str, Any]:
    """BS-2: hard-cancel + one-shot flag; main recreates session like normal boot.

    Does **not** show win UI. Does **not** auto-open Board Settings after reset
    (same as normal start-up / New Game).
    """
    # Hard-cancel hooks (best-effort)
    try:
        game.ai_pipeline_busy = False
        game._ai_pipeline_busy_depth = 0
        game.phase0_save_busy = False
        game.ai_pipeline_busy_reason = ""
    except Exception:
        pass
    for attr in (
        "pending_human_twp_offer",
        "pending_twp_counter",
        "pending_seven_roll",
        "pending_robber_steal",
        "pending_tfr_play",
    ):
        try:
            val = getattr(game, attr, None)
            if isinstance(val, dict):
                val["active"] = False
                if "awaiting_human_target" in val:
                    val["awaiting_human_target"] = False
        except Exception:
            pass
    # Suppress any in-flight post-game chrome on abort
    try:
        game.game_over = False
        pgui = getattr(game, "post_game_ui", None)
        if isinstance(pgui, dict):
            pgui["active"] = False
            pgui["request_new_game"] = False
            pgui["confirm_new_game"] = False
    except Exception:
        pass
    try:
        gui = getattr(game, "gui", None)
        if gui is not None:
            for attr in ("twb_panel_state", "play_dcard_panel_state", "human_buy_road_state"):
                st = getattr(gui, attr, None)
                if isinstance(st, dict):
                    st["active"] = False
            # Stop IP / robber / resource animations immediately (GUI is reused)
            if callable(getattr(gui, "stop_all_animations", None)):
                try:
                    gui.stop_all_animations(redraw_board=False)
                except TypeError:
                    gui.stop_all_animations()
            for qname in (
                "animate_queue_elements",
                "animate_queue_intersections",
                "animate_queue_roads",
                "animate_queue_tiles",
            ):
                q = getattr(gui, qname, None)
                if isinstance(q, list):
                    q.clear()
    except Exception:
        pass

    state = ensure_ui_settings(game)
    state["request_end_session_for_settings"] = True
    state["mode"] = MODE_OFF
    state["confirm_visible"] = False
    state["board_settings_open"] = False
    state["message"] = "Ending game…"
    return state


def consume_end_session_for_settings_request(game: Any) -> bool:
    """BS-2: consume one-shot abort request (main loop)."""
    state = ensure_ui_settings(game)
    if not bool(state.get("request_end_session_for_settings")):
        return False
    state["request_end_session_for_settings"] = False
    return True


def apply_end_session_for_settings(
    game: Any,
    gui: Any,
    *,
    create_session,
    start_ip,
    gui_hp: Any = None,
) -> Tuple[Any, Any]:
    """BS-2: recreate session like New Game / normal start-up (no auto menu).

    Args:
        create_session: callable(gui) -> (game, gui)  e.g. main._create_fresh_game_session
        start_ip: callable(game, gui, gui_hp) -> None  e.g. main._start_initial_placement

    Returns:
        (new_game, new_gui)
    """
    # Flag already consumed by caller, or consume here if still set
    try:
        consume_end_session_for_settings_request(game)
    except Exception:
        pass
    try:
        if gui is not None and callable(getattr(gui, "stop_all_animations", None)):
            try:
                gui.stop_all_animations(redraw_board=False)
            except TypeError:
                gui.stop_all_animations()
    except Exception:
        pass
    new_game, new_gui = create_session(gui)
    if gui_hp is not None:
        start_ip(new_game, new_gui, gui_hp)
    else:
        start_ip(new_game, new_gui)
    # Product: abort = normal reboot look — do NOT open Board Settings
    state = ensure_ui_settings(new_game)
    state["mode"] = MODE_OFF
    state["board_settings_open"] = False
    state["confirm_visible"] = False
    try:
        if new_gui is not None and callable(getattr(new_gui, "resume_animations", None)):
            new_gui.resume_animations()
    except Exception:
        pass
    return new_game, new_gui


def _play_sound(name: str) -> None:
    try:
        snd = SOUNDS.get(name)
        if snd is not None:
            snd.play()
    except Exception:
        pass


def _blit_settings_image(enabled: bool, rect: pygame.Rect) -> None:
    key = "SETTINGS_ON" if enabled else "SETTINGS_OFF"
    bag = IMAGES.get(key) or {}
    surf = bag.get("default") if isinstance(bag, Mapping) else None
    if surf is not None:
        try:
            WIN.blit(surf, (rect.x, rect.y))
            return
        except Exception:
            pass
    # Fallback: labeled square
    color = COLORS.get("DGRAY" if not enabled else "GREEN", (80, 80, 80))
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), rect)
    pygame.draw.rect(WIN, color, rect, 2)


def _end_game_confirm_union_rect() -> pygame.Rect:
    """Bounding box of gear + prompt + Yes + No (canonical strip, padded)."""
    try:
        return SETTINGS_END_GAME_CONFIRM_STRIP_RECT.inflate(4, 4)
    except Exception:
        rects = settings_end_game_confirm_rects()
        return (
            SETTINGS_BUTTON_RECT.union(rects["prompt"])
            .union(rects["yes"])
            .union(rects["no"])
            .inflate(4, 4)
        )


def _clear_end_game_confirm_area(*, update_display: bool = False) -> None:
    """Paint over End-game confirm strip with background (remove ghost UI).

    Clears prompt + Yes + No (and pad). Gear is redrawn by ``draw_settings_button``.
    """
    try:
        # Erase only the confirm controls to the right of the gear (keep gear art)
        rects = settings_end_game_confirm_rects()
        area = (
            rects["prompt"].union(rects["yes"]).union(rects["no"]).inflate(4, 4)
        )
        bg = COLORS.get("LGRAY", (200, 200, 200))
        pygame.draw.rect(WIN, bg, area)
        if update_display:
            pygame.display.update(area)
    except Exception:
        pass


def draw_settings_button(game: Any) -> None:
    """Draw gear (+ optional End-current-game confirm) every frame."""
    ensure_ui_settings(game)
    rect = SETTINGS_BUTTON_RECT
    mode = settings_mode(game)
    # Gear looks disabled during confirm / board settings / game over
    gear_enabled = is_settings_enabled(game)
    _blit_settings_image(gear_enabled, rect)
    border = (
        COLORS.get("GREEN", (0, 200, 0))
        if gear_enabled
        else COLORS.get("GRAY", (128, 128, 128))
    )
    try:
        pygame.draw.rect(WIN, border, rect, 2)
    except Exception:
        pass

    # Confirm draws even though gear is disabled
    if mode == MODE_CONFIRM_END:
        _draw_end_game_confirm()
    else:
        # Always erase leftover confirm pixels when not in confirm mode
        # (No / Esc / Yes leave ghosts otherwise — only gear is repainted)
        _clear_end_game_confirm_area(update_display=False)
        if mode == MODE_BOARD_SETTINGS:
            try:
                from gui.gui_board_settings import draw_board_settings

                draw_board_settings(game)
            except Exception:
                _draw_board_settings_stub(game)


def _draw_end_game_confirm() -> None:
    """Prompt + Yes/No (both enabled). Prompt has no border."""
    rects = settings_end_game_confirm_rects()
    prompt_r = rects["prompt"]
    yes_r = rects["yes"]
    no_r = rects["no"]
    font = (
        Font.NORMAL.value["regular"]
        if isinstance(Font.NORMAL.value, dict)
        else pygame.font.SysFont("Comic Sans MS", 16)
    )
    # Prompt: fill only, no border
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), prompt_r)
    text = font.render("End current game?", True, COLORS.get("DRED", (139, 0, 0)))
    WIN.blit(
        text,
        (prompt_r.x + 6, prompt_r.y + max(2, (prompt_r.height - text.get_height()) // 2)),
    )

    # Both Yes and No look enabled (active border, not gray-disabled)
    for r, label, border_col in (
        (yes_r, "Yes", COLORS.get("GREEN", (0, 160, 0))),
        (no_r, "No", COLORS.get("GREEN", (0, 160, 0))),
    ):
        pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
        pygame.draw.rect(WIN, border_col, r, 2)
        t = font.render(label, True, COLORS.get("BLACK", (0, 0, 0)))
        WIN.blit(
            t,
            (
                r.x + max(4, (r.width - t.get_width()) // 2),
                r.y + max(2, (r.height - t.get_height()) // 2),
            ),
        )


def _draw_board_settings_stub(game: Any) -> None:
    """BS-1: lightweight overlay note until BS-3 menu ships."""
    state = ensure_ui_settings(game)
    msg = str(state.get("message") or "Board Settings")
    font = Font.NORMAL.value["regular"] if isinstance(Font.NORMAL.value, dict) else pygame.font.SysFont("Comic Sans MS", 16)
    # Small banner above gear
    banner = pygame.Rect(
        SETTINGS_BUTTON_RECT.x,
        max(0, SETTINGS_BUTTON_RECT.y - 28),
        320,
        24,
    )
    pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), banner)
    pygame.draw.rect(WIN, COLORS.get("DRED", (139, 0, 0)), banner, 1)
    t = font.render(msg[:48], True, COLORS.get("DRED", (139, 0, 0)))
    WIN.blit(t, (banner.x + 4, banner.y + 2))
    # Hint: click gear again or Esc to close stub (BS-1 only)
    hint = font.render("Gear again / Esc closes stub", True, COLORS.get("DGRAY", (80, 80, 80)))
    WIN.blit(hint, (banner.x + 4, banner.y - 18))


def handle_settings_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle gear / Yes / No. Returns True if click consumed."""
    state = ensure_ui_settings(game)
    mode = str(state.get("mode") or MODE_OFF)
    gear = SETTINGS_BUTTON_RECT
    rects = settings_end_game_confirm_rects()

    # Confirm Yes / No take priority when visible (gear is disabled)
    if mode == MODE_CONFIRM_END:
        if rects["yes"].collidepoint(pos):
            _play_sound("BUTTON")
            request_end_session_for_settings(game)
            return True
        if rects["no"].collidepoint(pos):
            # Hide prompt + Yes/No; re-enable Settings gear
            _play_sound("BUTTON")
            dismiss_settings_confirm(game)
            return True
        # Gear disabled while confirm is open
        if gear.collidepoint(pos):
            _play_sound("ERROR")
            return True
        # Other clicks while confirm open: swallow (modal-ish)
        _play_sound("ERROR")
        return True

    if mode == MODE_BOARD_SETTINGS:
        # BS-3: sole normal exit is menu item 1; gear does not close menu
        try:
            from gui.gui_board_settings import handle_board_settings_click

            return bool(handle_board_settings_click(game, pos))
        except Exception:
            _play_sound("ERROR")
            return True

    # mode == off
    if not gear.collidepoint(pos):
        return False

    if not is_settings_enabled(game):
        _play_sound("ERROR")
        return True

    _play_sound("BUTTON")
    if not is_first_play_done(game):
        open_board_settings(game, reason="Settings Board")
    else:
        state["mode"] = MODE_CONFIRM_END
        state["confirm_visible"] = True
    return True


def handle_settings_keydown(game: Any, key: int) -> bool:
    """Esc dismisses confirm; Board Settings Esc = back-page / not full exit."""
    state = ensure_ui_settings(game)
    mode = str(state.get("mode") or MODE_OFF)
    if key != getattr(pygame, "K_ESCAPE", 27):
        return False
    if mode == MODE_CONFIRM_END:
        dismiss_settings_confirm(game)
        return True
    if mode == MODE_BOARD_SETTINGS:
        try:
            from gui.gui_board_settings import handle_board_settings_keydown

            return bool(handle_board_settings_keydown(game, key))
        except Exception:
            return True
    return False
