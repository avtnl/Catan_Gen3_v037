"""BS-3: Board Settings main menu shell (pages, enable rules, stub actions).

Product menu (locked):
  1. Exit and use this playboard to play game  (disabled if blank)
  2. Random board
  3. Load board  → file list page (Playboard_*.txt in project root)
  4. Empty board → editor page (Save / Cancel shell; ops later)
  5. Edit board  → editor page
  6. CIBI        → metrics page (stub unless calc available)

No separate Exit Settings. Random does not save directly. No auto-exit after Random/Load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import (
    WIN,
    COLORS,
    Font,
    PLAYBOARD_RECT,
    SCOREBOARD_RECT,
    HUMAN_BUTTON_PANEL_RECT,
    TWITTER_PANEL_RECT,
    EXECUTION_DEBUG_PANEL_RECT,
    TRADE_BANK_PANEL_RECT,
    BOARD_SETTINGS_PANEL_RECT,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
)

# Pages
PAGE_MENU = "menu"
PAGE_LOAD = "load_picker"
PAGE_EDITOR = "editor"
PAGE_CIBI = "cibi"

# Board source (internal)
SRC_BOOT_RANDOM = "boot_random"
SRC_BOOT_LOADED = "boot_loaded"
SRC_RANDOM = "random"
SRC_LOADED = "loaded"
SRC_SAVED = "saved"
SRC_BLANK = "blank"
SRC_EDITING = "editing"

_PLAYABLE = frozenset(
    {SRC_BOOT_RANDOM, SRC_BOOT_LOADED, SRC_RANDOM, SRC_LOADED, SRC_SAVED}
)

MENU_IDS = (
    "exit_use",
    "random",
    "load",
    "empty",
    "edit",
    "cibi",
)

MENU_LABELS = {
    "exit_use": "Exit and use the playboard to play",
    "random": "Random board",
    "load": "Load board",
    "empty": "Empty board",
    "edit": "Edit board",
    "cibi": "CIBI",
}


def _font(size: str = "normal", bold: bool = False):
    key = "bold" if bold else "regular"
    try:
        enum = Font.LARGE if size == "large" else Font.NORMAL
        val = enum.value
        if isinstance(val, dict):
            return val[key]
    except Exception:
        pass
    return pygame.font.SysFont("Comic Sans MS", 24 if size == "large" else 16, bold=bold)


def _play_sound(name: str) -> None:
    try:
        from gui.gui_constants import SOUNDS

        snd = SOUNDS.get(name)
        if snd is not None:
            snd.play()
    except Exception:
        pass


def board_settings_panel_rect() -> pygame.Rect:
    """Right-side Board Settings column (canonical: BOARD_SETTINGS_PANEL_RECT).

    Playboard stays visible at ``PLAYBOARD_RECT``. Human TwP Mode / button panel
    are not drawn while Board Settings is open (see ``main._render_runtime_gui``).
    Defined in ``gui_constants`` so UI_PANEL_LAYOUT lists it for easy reference.
    """
    return pygame.Rect(BOARD_SETTINGS_PANEL_RECT)


def ensure_board_settings_fields(state: Dict[str, Any], game: Any = None) -> Dict[str, Any]:
    """Ensure BS-3 fields on ui_settings."""
    state.setdefault("board_settings_page", PAGE_MENU)
    state.setdefault("board_source", None)
    state.setdefault("board_source_path", "")
    state.setdefault("status_line", "")
    state.setdefault("load_files", [])
    state.setdefault("load_scroll", 0)
    state.setdefault("editor_kind", "")  # empty | edit
    state.setdefault("menu_hit_rects", {})
    state.setdefault("load_hit_rects", {})
    state.setdefault("editor_hit_rects", {})
    state.setdefault("cibi_hit_rects", {})
    state.setdefault("cibi_lines", [])
    if not state.get("board_source"):
        state["board_source"] = infer_boot_board_source(game)
    return state


def infer_boot_board_source(game: Any = None) -> str:
    """Boot default from constants.LOAD_PLAYBOARD."""
    try:
        from core.constants import LOAD_PLAYBOARD

        if bool(LOAD_PLAYBOARD):
            return SRC_BOOT_LOADED
    except Exception:
        pass
    return SRC_BOOT_RANDOM


def is_exit_use_enabled(state: Mapping[str, Any]) -> bool:
    src = str(state.get("board_source") or SRC_BLANK)
    if src in (SRC_BLANK, SRC_EDITING):
        return False
    return src in _PLAYABLE


def list_playboard_files(root: Optional[Path] = None) -> List[str]:
    """Project-root Playboard_*.txt (+ legacy names). BS-4 service is source of truth."""
    try:
        from core.board_settings_service import list_playboard_files as _list

        return list(_list(root))
    except Exception:
        base = root if root is not None else Path.cwd()
        out: List[str] = []
        try:
            for p in sorted(base.glob("Playboard_*.txt")):
                if p.is_file():
                    out.append(p.name)
        except Exception:
            pass
        return out


def open_board_settings_menu(game: Any, *, reason: str = "") -> Dict[str, Any]:
    """Enter Board Settings on main menu page."""
    from gui.gui_settings_button import MODE_BOARD_SETTINGS, ensure_ui_settings

    state = ensure_ui_settings(game)
    ensure_board_settings_fields(state, game)
    state["mode"] = MODE_BOARD_SETTINGS
    state["confirm_visible"] = False
    state["board_settings_open"] = True
    state["board_settings_page"] = PAGE_MENU
    state["message"] = str(reason or "Settings Board")
    state["status_line"] = str(reason or "")
    if not state.get("board_source"):
        state["board_source"] = infer_boot_board_source(game)
    # Leaving editor without save shouldn't stick
    if state["board_source"] == SRC_EDITING:
        state["board_source"] = SRC_BLANK
    return state


def close_board_settings(game: Any) -> None:
    """Exit Board Settings to normal UI (item 1) — menu must fully disappear."""
    from gui.gui_settings_button import MODE_OFF, ensure_ui_settings

    state = ensure_ui_settings(game)
    state["mode"] = MODE_OFF
    state["board_settings_open"] = False
    state["board_settings_page"] = PAGE_MENU
    state["confirm_visible"] = False
    state["message"] = ""
    state["status_line"] = ""
    state["editor_kind"] = ""
    state["menu_hit_rects"] = {}
    state["load_hit_rects"] = {}
    state["editor_hit_rects"] = {}
    state["cibi_hit_rects"] = {}
    # Keep board_source / path for dig-in
    # Immediately erase the right-column menu so it cannot leave ghost pixels
    # (Events/Debug may not repaint that full rect until later frames).
    try:
        panel = board_settings_panel_rect()
        pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), panel)
        pygame.display.update(panel)
    except Exception:
        pass
    # Restore right-column chrome when available
    try:
        gui = getattr(game, "gui", None)
        if gui is not None:
            if callable(getattr(gui, "update_twitter", None)):
                gui.update_twitter()
            if callable(getattr(gui, "draw_execution_debug_panel", None)):
                gui.draw_execution_debug_panel(game)
    except Exception:
        pass


def draw_board_settings(game: Any) -> None:
    """Draw Board Settings for current page (no-op if settings already closed)."""
    from gui.gui_settings_button import MODE_BOARD_SETTINGS, ensure_ui_settings, settings_mode

    state = ensure_ui_settings(game)
    # Hard guard: never paint menu after Exit item 1
    if str(state.get("mode") or "") != MODE_BOARD_SETTINGS:
        return
    if settings_mode(game) != MODE_BOARD_SETTINGS:
        return
    if not bool(state.get("board_settings_open")):
        return
    ensure_board_settings_fields(state, game)
    page = str(state.get("board_settings_page") or PAGE_MENU)
    if page == PAGE_LOAD:
        _draw_load_page(game, state)
    elif page == PAGE_EDITOR:
        _draw_editor_page(game, state)
    elif page == PAGE_CIBI:
        _draw_cibi_page(game, state)
    else:
        _draw_menu_page(game, state)


def handle_board_settings_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle click while Board Settings is open. Always consumes."""
    from gui.gui_settings_button import ensure_ui_settings

    state = ensure_ui_settings(game)
    ensure_board_settings_fields(state, game)
    page = str(state.get("board_settings_page") or PAGE_MENU)
    if page == PAGE_LOAD:
        return _click_load_page(game, state, pos)
    if page == PAGE_EDITOR:
        return _click_editor_page(game, state, pos)
    if page == PAGE_CIBI:
        return _click_cibi_page(game, state, pos)
    return _click_menu_page(game, state, pos)


def handle_board_settings_keydown(game: Any, key: int) -> bool:
    """Esc: sub-page → menu; menu does not exit (must use item 1)."""
    from gui.gui_settings_button import ensure_ui_settings

    if key != getattr(pygame, "K_ESCAPE", 27):
        return False
    state = ensure_ui_settings(game)
    ensure_board_settings_fields(state, game)
    page = str(state.get("board_settings_page") or PAGE_MENU)
    if page in (PAGE_LOAD, PAGE_CIBI):
        state["board_settings_page"] = PAGE_MENU
        state["status_line"] = ""
        return True
    if page == PAGE_EDITOR:
        # Esc = Cancel (blank board)
        _editor_cancel(game, state)
        return True
    # Main menu: do not close via Esc
    return True


# ── Menu page ────────────────────────────────────────────────────────────────


def _wrap_text(font, text: str, max_width: int) -> List[str]:
    """Word-wrap *text* to fit *max_width* pixels."""
    words = str(text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        try:
            tw = font.size(trial)[0]
        except Exception:
            tw = len(trial) * 8
        if tw <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _menu_item_rects(panel: pygame.Rect) -> Dict[str, pygame.Rect]:
    """Menu rows on the right panel (narrower; taller rows for wrapped labels)."""
    x = panel.x + 12
    y0 = panel.y + 78
    w = max(120, panel.width - 24)
    h = 44
    gap = 8
    avail = panel.bottom - y0 - 44
    need = len(MENU_IDS) * h + (len(MENU_IDS) - 1) * gap
    if need > avail and len(MENU_IDS) > 0:
        h = max(34, (avail - (len(MENU_IDS) - 1) * gap) // len(MENU_IDS))
    out: Dict[str, pygame.Rect] = {}
    for i, mid in enumerate(MENU_IDS):
        out[mid] = pygame.Rect(x, y0 + i * (h + gap), w, h)
    return out


def _draw_menu_page(game: Any, state: Dict[str, Any]) -> None:
    panel = board_settings_panel_rect()
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), panel)
    pygame.draw.rect(WIN, COLORS.get("DRED", (139, 0, 0)), panel, 2)

    title_font = _font("large", bold=True)
    body = _font("normal")
    try:
        small = Font.SMALL.value["regular"] if isinstance(Font.SMALL.value, dict) else body
    except Exception:
        small = pygame.font.SysFont("Comic Sans MS", 10)

    # Main menu title (Empty/Edit use their own titles in the editor sub-page)
    title = title_font.render("Settings Board", True, COLORS.get("DRED", (139, 0, 0)))
    WIN.blit(title, (panel.x + 12, panel.y + 12))

    src = str(state.get("board_source") or "")
    path = str(state.get("board_source_path") or "")
    src_txt = f"Source: {src}" + (f" ({path})" if path else "")
    max_src_w = panel.width - 24
    while src_txt and small.size(src_txt)[0] > max_src_w and len(src_txt) > 8:
        src_txt = src_txt[:-4] + "…"
    WIN.blit(
        small.render(src_txt, True, COLORS.get("DGRAY", (80, 80, 80))),
        (panel.x + 12, panel.y + 48),
    )

    rects = _menu_item_rects(panel)
    state["menu_hit_rects"] = {k: (r.x, r.y, r.w, r.h) for k, r in rects.items()}

    for mid in MENU_IDS:
        r = rects[mid]
        enabled = True
        if mid == "exit_use":
            enabled = is_exit_use_enabled(state)
        fill = COLORS.get("WHITE", (255, 255, 255))
        border = (
            COLORS.get("GREEN", (0, 180, 0))
            if enabled
            else COLORS.get("GRAY", (140, 140, 140))
        )
        text_c = (
            COLORS.get("BLACK", (0, 0, 0))
            if enabled
            else COLORS.get("GRAY", (140, 140, 140))
        )
        pygame.draw.rect(WIN, fill, r)
        pygame.draw.rect(WIN, border, r, 2)
        label = MENU_LABELS.get(mid, mid)
        lines = _wrap_text(body, label, r.width - 16)
        use_font = body
        if len(lines) > 2:
            lines = _wrap_text(small, label, r.width - 16)[:3]
            use_font = small
        total_h = sum(use_font.size(ln)[1] for ln in lines) + 2 * max(0, len(lines) - 1)
        ty = r.y + max(2, (r.height - total_h) // 2)
        for ln in lines:
            t = use_font.render(ln, True, text_c)
            WIN.blit(t, (r.x + 8, ty))
            ty += t.get_height() + 2

    status = str(state.get("status_line") or "")
    if status:
        s_lines = _wrap_text(small, status, panel.width - 24)[:3]
        sy = panel.bottom - 10 - len(s_lines) * 14
        for ln in s_lines:
            WIN.blit(
                small.render(ln, True, COLORS.get("DRED", (139, 0, 0))),
                (panel.x + 12, sy),
            )
            sy += 14


def _click_menu_page(game: Any, state: Dict[str, Any], pos: Tuple[int, int]) -> bool:
    rects = _menu_item_rects(board_settings_panel_rect())
    for mid, r in rects.items():
        if not r.collidepoint(pos):
            continue
        if mid == "exit_use":
            if not is_exit_use_enabled(state):
                _play_sound("ERROR")
                state["status_line"] = "No playable board (blank). Random, Load, or Save first."
                return True
            _play_sound("BUTTON")
            close_board_settings(game)
            return True
        if mid == "random":
            _play_sound("BUTTON")
            _action_random_stub(game, state)
            return True
        if mid == "load":
            _play_sound("BUTTON")
            state["board_settings_page"] = PAGE_LOAD
            state["load_files"] = list_playboard_files()
            state["load_scroll"] = 0
            state["status_line"] = f"{len(state['load_files'])} file(s) in project root"
            return True
        if mid == "empty":
            _play_sound("BUTTON")
            try:
                from core.board_settings_service import prepare_empty_board

                prepare_empty_board(game)
            except Exception:
                pass
            state["board_settings_page"] = PAGE_EDITOR
            state["editor_kind"] = "empty"
            state["board_source"] = SRC_EDITING
            state["editor_tool"] = "terrain"
            state["editor_terrain"] = "No selection"
            state["editor_number"] = None
            state["editor_port"] = "No selection"
            # Empty always starts from a blanked board — Cancel keeps blanking semantics
            state["editor_dirty"] = True
            state["editor_entry_source"] = SRC_BLANK
            state["editor_entry_source_path"] = ""
            state["editor_status"] = "Paint blank tiles (Terrain / Number / Port). Save or Cancel."
            state["status_line"] = ""
            return True
        if mid == "edit":
            if str(state.get("board_source")) == SRC_BLANK:
                _play_sound("ERROR")
                state["status_line"] = "Nothing to edit (board is blank)."
                return True
            _play_sound("BUTTON")
            # Remember pre-edit source so Cancel with no edits can restore it
            state["editor_entry_source"] = str(
                state.get("board_source") or SRC_BOOT_RANDOM
            )
            state["editor_entry_source_path"] = str(state.get("board_source_path") or "")
            state["board_settings_page"] = PAGE_EDITOR
            state["editor_kind"] = "edit"
            state["board_source"] = SRC_EDITING
            state["editor_tool"] = "terrain"
            state["editor_terrain"] = "No selection"
            state["editor_number"] = None
            state["editor_port"] = "No selection"
            state["editor_dirty"] = False
            state["editor_status"] = "Edit current board. Save or Cancel."
            state["status_line"] = ""
            return True
        if mid == "cibi":
            _play_sound("BUTTON")
            state["board_settings_page"] = PAGE_CIBI
            state["cibi_lines"] = _collect_cibi_lines(game)
            state["status_line"] = ""
            return True
    _play_sound("ERROR")
    return True


def _action_random_stub(game: Any, state: Dict[str, Any]) -> None:
    """BS-4: regenerate via board_settings_service.randomize_board."""
    try:
        from core.board_settings_service import randomize_board

        result = randomize_board(game)
    except Exception as exc:
        result = {"ok": False, "message": f"Random failed: {exc}"}
    if result.get("ok"):
        state["board_source"] = SRC_RANDOM
        state["board_source_path"] = ""
        state["status_line"] = str(
            result.get("message")
            or "Random board ready. Exit and use… when finished (cannot Save until Edit→Save)."
        )
    else:
        state["status_line"] = str(result.get("message") or "Random failed.")


# ── Load picker ──────────────────────────────────────────────────────────────


def _draw_load_page(game: Any, state: Dict[str, Any]) -> None:
    panel = board_settings_panel_rect()
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), panel)
    pygame.draw.rect(WIN, COLORS.get("DRED", (139, 0, 0)), panel, 2)
    title_font = _font("large", bold=True)
    body = _font("normal")
    try:
        small = Font.SMALL.value["regular"] if isinstance(Font.SMALL.value, dict) else body
    except Exception:
        small = body
    WIN.blit(
        title_font.render("Load board", True, COLORS.get("DRED", (139, 0, 0))),
        (panel.x + 12, panel.y + 12),
    )
    for i, ln in enumerate(
        _wrap_text(small, "Playboard_*.txt in project root | Esc = back", panel.width - 24)
    ):
        WIN.blit(
            small.render(ln, True, COLORS.get("DGRAY", (80, 80, 80))),
            (panel.x + 12, panel.y + 48 + i * 14),
        )

    files = list(state.get("load_files") or [])
    hit: Dict[str, Tuple[int, int, int, int]] = {}
    y = panel.y + 90
    row_h = 30
    max_rows = max(1, (panel.bottom - y - 56) // (row_h + 4))
    scroll = int(state.get("load_scroll") or 0)
    scroll = max(0, min(scroll, max(0, len(files) - max_rows)))
    state["load_scroll"] = scroll
    visible = files[scroll : scroll + max_rows]
    row_w = max(80, panel.width - 24)

    if not files:
        for i, ln in enumerate(
            _wrap_text(small, "(no Playboard_*.txt found in project root)", row_w)
        ):
            WIN.blit(
                small.render(ln, True, COLORS.get("DRED", (139, 0, 0))),
                (panel.x + 12, y + i * 14),
            )
    for i, name in enumerate(visible):
        r = pygame.Rect(panel.x + 12, y + i * (row_h + 4), row_w, row_h)
        pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
        pygame.draw.rect(WIN, COLORS.get("GREEN", (0, 180, 0)), r, 2)
        # Truncate filename to fit
        display = name
        while small.size(display)[0] > row_w - 16 and len(display) > 6:
            display = display[:-4] + "…"
        WIN.blit(small.render(display, True, COLORS.get("BLACK", (0, 0, 0))), (r.x + 6, r.y + 7))
        hit[f"file:{scroll + i}"] = (r.x, r.y, r.w, r.h)

    back = pygame.Rect(panel.x + 12, panel.bottom - 44, 100, 32)
    pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), back)
    pygame.draw.rect(WIN, COLORS.get("DGRAY", (80, 80, 80)), back, 2)
    WIN.blit(body.render("Back", True, COLORS.get("BLACK", (0, 0, 0))), (back.x + 28, back.y + 6))
    hit["back"] = (back.x, back.y, back.w, back.h)
    state["load_hit_rects"] = hit


def _click_load_page(game: Any, state: Dict[str, Any], pos: Tuple[int, int]) -> bool:
    hit = state.get("load_hit_rects") or {}
    for key, tup in hit.items():
        r = pygame.Rect(*tup)
        if not r.collidepoint(pos):
            continue
        if key == "back":
            _play_sound("BUTTON")
            state["board_settings_page"] = PAGE_MENU
            return True
        if str(key).startswith("file:"):
            try:
                idx = int(str(key).split(":")[1])
            except Exception:
                idx = -1
            files = list(state.get("load_files") or [])
            if 0 <= idx < len(files):
                _play_sound("BUTTON")
                _action_load_stub(game, state, files[idx])
                state["board_settings_page"] = PAGE_MENU
                return True
    _play_sound("ERROR")
    return True


def _action_load_stub(game: Any, state: Dict[str, Any], filename: str) -> None:
    """BS-4: load via board_settings_service.load_playboard."""
    try:
        from core.board_settings_service import load_playboard

        result = load_playboard(game, filename)
    except Exception as exc:
        result = {"ok": False, "message": f"Load failed: {exc}"}
    if result.get("ok"):
        state["board_source"] = SRC_LOADED
        state["board_source_path"] = str(result.get("path") or filename)
        state["status_line"] = str(result.get("message") or f"Loaded {filename}.")
    else:
        state["status_line"] = str(result.get("message") or "Load failed.")


# ── Editor (BS-5 paint tools) ────────────────────────────────────────────────


def _draw_editor_page(game: Any, state: Dict[str, Any]) -> None:
    try:
        from gui.gui_board_editor import draw_editor, ensure_editor_state

        ensure_editor_state(state)
        draw_editor(game, state)
    except Exception as exc:
        # Fallback shell if editor import/draw fails
        panel = board_settings_panel_rect()
        pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), panel)
        body = _font("normal")
        WIN.blit(
            body.render(f"Editor error: {exc}", True, COLORS.get("DRED", (139, 0, 0))),
            (panel.x + 20, panel.y + 40),
        )


def _click_editor_page(game: Any, state: Dict[str, Any], pos: Tuple[int, int]) -> bool:
    try:
        from gui.gui_board_editor import handle_editor_click

        action = handle_editor_click(game, state, pos)
    except Exception:
        action = "none"
    if action == "save":
        _play_sound("BUTTON")
        _editor_save(game, state)
        return True
    if action == "cancel":
        _play_sound("BUTTON")
        _editor_cancel(game, state)
        return True
    if action == "handled":
        _play_sound("BUTTON")
        return True
    _play_sound("ERROR")
    return True


def _editor_save(game: Any, state: Dict[str, Any]) -> None:
    """BS-5: validate + save Playboard_*.txt."""
    board = getattr(game, "board", None)
    try:
        from gui.gui_board_editor import validate_for_save

        ok, msg = validate_for_save(board, allow_incomplete=False)
    except Exception:
        ok, msg = True, ""
    if not ok:
        state["status_line"] = msg
        state["editor_status"] = msg
        return
    try:
        from core.board_settings_service import save_playboard

        result = save_playboard(game)
    except Exception as exc:
        result = {"ok": False, "message": f"Save failed: {exc}"}
    if not result.get("ok"):
        state["status_line"] = str(result.get("message") or "Save failed.")
        state["editor_status"] = state["status_line"]
        return
    # Return to main Settings Board menu (sub-menu closed)
    state["board_settings_page"] = PAGE_MENU
    state["editor_kind"] = ""
    state["editor_hit_rects"] = {}
    state["editor_dirty"] = False
    state["editor_entry_source"] = ""
    state["editor_entry_source_path"] = ""
    state["board_source"] = SRC_SAVED
    state["board_source_path"] = str(result.get("path") or "")
    note = f" {msg}" if msg and "complete" in msg.lower() else ""
    if msg and "note" in msg.lower():
        note = f" ({msg})"
    state["status_line"] = str(result.get("message") or "Saved.") + note
    state["editor_status"] = ""


def _editor_cancel(game: Any, state: Dict[str, Any]) -> None:
    """Leave editor: blank if dirty/Empty; keep board if Edit with no changes."""
    kind = str(state.get("editor_kind") or "")
    dirty = bool(state.get("editor_dirty"))
    # Edit + no mutations → keep playboard, restore prior source, return to menu
    if kind == "edit" and not dirty:
        entry = str(state.get("editor_entry_source") or "")
        if entry and entry not in (SRC_EDITING, SRC_BLANK, ""):
            state["board_source"] = entry
        else:
            state["board_source"] = SRC_BOOT_RANDOM
        state["board_source_path"] = str(state.get("editor_entry_source_path") or "")
        state["board_settings_page"] = PAGE_MENU
        state["editor_kind"] = ""
        state["editor_hit_rects"] = {}
        state["editor_dirty"] = False
        state["editor_entry_source"] = ""
        state["editor_entry_source_path"] = ""
        state["editor_status"] = ""
        state["status_line"] = "Edit cancelled — board unchanged."
        return

    # Empty always, or Edit after any paint → blank board (existing product rule)
    try:
        from core.board_settings_service import blank_board

        result = blank_board(game)
    except Exception as exc:
        result = {"ok": False, "message": f"Cancel failed: {exc}"}
    state["board_source"] = SRC_BLANK
    state["board_source_path"] = ""
    state["board_settings_page"] = PAGE_MENU
    state["editor_kind"] = ""
    state["editor_hit_rects"] = {}
    state["editor_dirty"] = False
    state["editor_entry_source"] = ""
    state["editor_entry_source_path"] = ""
    state["editor_status"] = ""
    state["status_line"] = str(
        result.get("message") or "Cancelled — board blank. Exit and use… disabled."
    )


# ── CIBI ─────────────────────────────────────────────────────────────────────


def _collect_cibi_lines(game: Any) -> List[str]:
    """Build CIBI page lines: headline composite + six normalized components."""
    board = getattr(game, "board", None) if game is not None else None
    if board is None:
        return [
            "Catan Island Board Index (CIBI)",
            "No board available.",
        ]
    try:
        from core.cibi import compute_cibi, format_cibi_lines

        return format_cibi_lines(compute_cibi(board))
    except Exception as exc:
        # Fallback: Gen2-style raw six via board.calc_cibi if present
        if callable(getattr(board, "calc_cibi", None)):
            try:
                from core.cibi import COMPONENT_LABELS, composite_cibi

                raw = board.calc_cibi()
                if isinstance(raw, (list, tuple)) and len(raw) >= 6:
                    cibi, norms = composite_cibi(raw[:6])
                    lines = [
                        "Catan Island Board Index (CIBI)",
                        f"CIBI Index:  {cibi:.3f}",
                        "",
                    ]
                    for i, lab in enumerate(COMPONENT_LABELS):
                        lines.append(f"{lab}: {norms[i]:.3f}  (raw {raw[i]})")
                    lines.append("Lower is better · random mean ≈ 0.24")
                    return lines
            except Exception:
                pass
        return ["CIBI", f"calc failed: {exc}"]


def _draw_cibi_page(game: Any, state: Dict[str, Any]) -> None:
    panel = board_settings_panel_rect()
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), panel)
    pygame.draw.rect(WIN, COLORS.get("DRED", (139, 0, 0)), panel, 2)
    title_font = _font("large", bold=True)
    body = _font("normal")
    try:
        small = Font.SMALL.value["regular"] if isinstance(Font.SMALL.value, dict) else body
    except Exception:
        small = body
    WIN.blit(
        title_font.render("CIBI", True, COLORS.get("DRED", (139, 0, 0))),
        (panel.x + 12, panel.y + 12),
    )
    back = pygame.Rect(panel.x + 12, panel.bottom - 44, 100, 32)
    max_w = panel.width - 24
    lines = list(state.get("cibi_lines") or [])
    # Footnote drawn at bottom (above Back); main metrics above it
    footnote = "Lower is better · random mean ≈ 0.24"
    body_lines = [ln for ln in lines if str(ln).strip() != footnote and not str(ln).startswith("Composition")]

    y = panel.y + 50
    y_limit = panel.bottom - 72  # leave room for footnote + Back
    for line in body_lines:
        if y > y_limit:
            break
        text = str(line)
        is_headline = text.startswith("CIBI Index:")
        # Long component labels use small font (same as Probability Distribution…)
        use_font = title_font if is_headline else (small if len(text) > 28 else body)
        for part in _wrap_text(use_font, text, max_w)[:3]:
            if y > y_limit:
                break
            col = COLORS.get("DRED", (139, 0, 0)) if is_headline else COLORS.get("BLACK", (0, 0, 0))
            surf = use_font.render(part, True, col)
            WIN.blit(surf, (panel.x + 12, y))
            y += surf.get_height() + (4 if is_headline else 2)
        if is_headline:
            y += 4

    # Footnote in small font at bottom (former Composition row area)
    fy = panel.bottom - 62
    for part in _wrap_text(small, footnote, max_w)[:2]:
        surf = small.render(part, True, COLORS.get("DGRAY", (80, 80, 80)))
        WIN.blit(surf, (panel.x + 12, fy))
        fy += surf.get_height() + 1

    pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), back)
    pygame.draw.rect(WIN, COLORS.get("DGRAY", (80, 80, 80)), back, 2)
    WIN.blit(body.render("Back", True, COLORS.get("BLACK", (0, 0, 0))), (back.x + 28, back.y + 6))
    state["cibi_hit_rects"] = {"back": (back.x, back.y, back.w, back.h)}


def _click_cibi_page(game: Any, state: Dict[str, Any], pos: Tuple[int, int]) -> bool:
    hit = state.get("cibi_hit_rects") or {}
    for key, tup in hit.items():
        r = pygame.Rect(*tup)
        if r.collidepoint(pos) and key == "back":
            _play_sound("BUTTON")
            state["board_settings_page"] = PAGE_MENU
            return True
    _play_sound("ERROR")
    return True
