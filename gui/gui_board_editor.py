"""BS-5: Empty/Edit board paint tools (terrain, numbers, ports).

UX:
- Playboard stays visible at its normal location.
- Title + tool sub-menu on the **right** column (same slot as Settings Board).
- Titles: "Settings Empty Board" / "Settings Edit Board".
- Tools: Terrain | Number | Port; each palette starts with "No selection".
- Click land tile → apply terrain or number (only if a brush is selected).
- Click port-site (or harbor sea hex) → set/clear port for that harbor pair.
- Save / Cancel return to main Settings Board menu.
- Blank land tiles are not drawn as Sea (LGRAY placeholders; Gen2 parity).
- Empty board defaults all harbors to 3:1 (not "?").
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import (
    WIN,
    COLORS,
    Font,
    POSITIONS,
    PLAYBOARD_RECT,
    HUMAN_BUTTON_PANEL_RECT,
    SCOREBOARD_RECT,
    IMAGES,
)

# Sentinel for palette "no brush" (must appear first in each list UI)
NO_SELECTION = "No selection"
# Number brush: None means no selection; chits 2–12 only (no zero)
NUMBER_NONE = None

# Land terrain cycle (Sea not editable)
TERRAIN_TYPES: Tuple[str, ...] = (
    NO_SELECTION,
    "Field",
    "Mountain",
    "Forest",
    "Hill",
    "Pasture",
    "Desert",
    "Blank",
)
NUMBER_VALUES: Tuple[Optional[int], ...] = (
    NUMBER_NONE,
    2,
    3,
    4,
    5,
    6,
    8,
    9,
    10,
    11,
    12,
)
PORT_TYPES: Tuple[str, ...] = (
    NO_SELECTION,
    "3:1",
    "2:1 Wheat",
    "2:1 Ore",
    "2:1 Wood",
    "2:1 Brick",
    "2:1 Sheep",
    "Clear",
)

TOOL_TERRAIN = "terrain"
TOOL_NUMBER = "number"
TOOL_PORT = "port"
TOOLS = (TOOL_TERRAIN, TOOL_NUMBER, TOOL_PORT)

TILE_HIT_RADIUS = 28
PORT_HIT_RADIUS = 22  # larger: port dots are small


def _font(size: str = "normal", bold: bool = False):
    key = "bold" if bold else "regular"
    try:
        enum = Font.LARGE if size == "large" else (
            Font.SMALL if size == "small" else Font.NORMAL
        )
        val = enum.value
        if isinstance(val, dict):
            return val[key]
    except Exception:
        pass
    sz = 24 if size == "large" else (10 if size == "small" else 16)
    return pygame.font.SysFont("Comic Sans MS", sz, bold=bold)


def _reset_palette_to_no_selection(state: Dict[str, Any]) -> None:
    """When switching Terrain/Number/Port tool, enable No selection."""
    state["editor_terrain"] = NO_SELECTION
    state["editor_number"] = NUMBER_NONE
    state["editor_port"] = NO_SELECTION


def ensure_editor_state(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault("editor_tool", TOOL_TERRAIN)
    state.setdefault("editor_terrain", NO_SELECTION)
    state.setdefault("editor_number", NUMBER_NONE)
    state.setdefault("editor_port", NO_SELECTION)
    state.setdefault("editor_status", "")
    state.setdefault("editor_hit_rects", {})
    state.setdefault("editor_kind", "edit")
    # True after any board mutation in this editor session (terrain/number/port paint)
    state.setdefault("editor_dirty", False)
    # board_source before entering Edit (restored on Cancel if not dirty)
    state.setdefault("editor_entry_source", "")
    state.setdefault("editor_entry_source_path", "")
    return state


def mark_editor_dirty(state: Dict[str, Any]) -> None:
    state["editor_dirty"] = True


def land_tile_ids(board: Any) -> List[int]:
    ids = list(getattr(board, "LIST_OF_LAND_TILES", None) or [])
    if ids:
        return [int(x) for x in ids]
    out = []
    for t in list(getattr(board, "tiles", []) or []):
        if t is None:
            continue
        ty = str(getattr(t, "type", "") or "")
        if ty not in ("Sea", "Water", ""):
            try:
                out.append(int(t.id))
            except Exception:
                pass
    return out


def port_pairs(board: Any) -> List[List[int]]:
    pairs = list(getattr(board, "INTERSECTIONS_ARE_PORT", None) or [])
    return [list(p) for p in pairs if isinstance(p, (list, tuple)) and len(p) >= 2]


def port_site_ids(board: Any) -> List[int]:
    out = []
    for pair in port_pairs(board):
        for x in pair:
            try:
                out.append(int(x))
            except Exception:
                pass
    return out


def hit_test_tile(board: Any, pos: Tuple[int, int]) -> Optional[int]:
    """Return land tile id under pos, or None."""
    best_id = None
    best_d = TILE_HIT_RADIUS + 1
    px, py = int(pos[0]), int(pos[1])
    tiles_pos = POSITIONS.get("tiles") or {}
    land = set(land_tile_ids(board))
    for tid, coords in tiles_pos.items():
        try:
            tid_i = int(tid)
        except Exception:
            continue
        if land and tid_i not in land:
            continue
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        cx, cy = int(coords[0]), int(coords[1])
        d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if d <= TILE_HIT_RADIUS and d < best_d:
            best_d = d
            best_id = tid_i
    return best_id


def hit_test_port_intersection(board: Any, pos: Tuple[int, int]) -> Optional[int]:
    """Hit port-site intersection dots, or the sea-hex center of a harbor pair."""
    best_id = None
    best_d = PORT_HIT_RADIUS + 1
    px, py = int(pos[0]), int(pos[1])
    inter_pos = POSITIONS.get("intersections") or {}
    tiles_pos = POSITIONS.get("tiles") or {}
    for iid in port_site_ids(board):
        coords = inter_pos.get(iid) or inter_pos.get(str(iid))
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        cx, cy = int(coords[0]), int(coords[1])
        d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if d <= PORT_HIT_RADIUS and d < best_d:
            best_d = d
            best_id = iid
    # Also accept clicks near the sea tile that hosts each harbor icon
    for pair in port_pairs(board):
        if len(pair) < 2:
            continue
        a_id, b_id = int(pair[0]), int(pair[1])
        sea_tid = _sea_tile_for_port_pair(board, a_id, b_id)
        if sea_tid is None:
            continue
        coords = tiles_pos.get(sea_tid) or tiles_pos.get(str(sea_tid))
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        cx, cy = int(coords[0]), int(coords[1])
        d = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if d <= TILE_HIT_RADIUS and d < best_d:
            best_d = d
            best_id = a_id
    return best_id


def _sea_tile_for_port_pair(board: Any, a_id: int, b_id: int) -> Optional[int]:
    """Find sea hex id spanning harbor endpoints (same logic as gui._draw_ports)."""
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        if str(getattr(tile, "type", "")) not in ("Sea", "Water"):
            continue
        try:
            corners = list(getattr(tile, "corners", []) or [])
            ids = [int(getattr(c, "intersection", 0) or 0) for c in corners]
        except Exception:
            continue
        if a_id in ids and b_id in ids:
            try:
                return int(tile.id)
            except Exception:
                return None
    return None


def get_tile(board: Any, tile_id: int) -> Any:
    for t in list(getattr(board, "tiles", []) or []):
        if t is not None and int(getattr(t, "id", -1)) == int(tile_id):
            return t
    return None


def apply_terrain(board: Any, tile_id: int, terrain: str) -> bool:
    if str(terrain) in (NO_SELECTION, "", "None"):
        return False
    tile = get_tile(board, tile_id)
    if tile is None:
        return False
    if int(tile_id) not in set(land_tile_ids(board)):
        return False
    tile.type = str(terrain)
    # No auto number chit: Desert/Blank clear value; resource terrain keeps
    # existing value (or 0) until the Number tool sets it.
    if terrain in ("Desert", "Blank"):
        tile.value = 0
    return True


def apply_number(board: Any, tile_id: int, number: Any) -> bool:
    """Set chit on a land tile. Terrain may still be Blank (numbers first, then types)."""
    if number is None or number is NUMBER_NONE or str(number) in (NO_SELECTION, "None", ""):
        return False
    tile = get_tile(board, tile_id)
    if tile is None:
        return False
    if int(tile_id) not in set(land_tile_ids(board)):
        return False
    ty = str(getattr(tile, "type", "") or "")
    if ty in ("Sea", "Water"):
        return False
    # Desert never carries a production number
    if ty == "Desert":
        tile.value = 0
        return True
    n = int(number)
    if n == 0:
        tile.value = 0
    else:
        tile.value = n
    return True


def apply_port(board: Any, intersection_id: int, port_type: str) -> bool:
    """Set port type on the harbor pair containing intersection_id."""
    if str(port_type) in (NO_SELECTION, "", "None"):
        return False
    pairs = port_pairs(board)
    pair = None
    for p in pairs:
        if int(intersection_id) in [int(x) for x in p]:
            pair = p
            break
    if pair is None:
        return False
    clear = str(port_type) in ("Clear", "Blank")
    inters = list(getattr(board, "intersections", []) or [])
    applied = False
    for iid in pair:
        inter = None
        if 0 <= int(iid) < len(inters):
            inter = inters[int(iid)]
        if inter is None:
            for cand in inters:
                if cand is not None and int(getattr(cand, "id", -1)) == int(iid):
                    inter = cand
                    break
        if inter is None:
            continue
        if clear:
            inter.port_tf = False
            inter.port_type = "Blank"
        else:
            inter.port_tf = True
            inter.port_type = str(port_type)
        applied = True
        # Keep tile corner port_type in sync (used by some board helpers)
        try:
            for tile in list(getattr(board, "tiles", []) or []):
                if tile is None:
                    continue
                for c in list(getattr(tile, "corners", []) or []):
                    if int(getattr(c, "intersection", -1) or -1) == int(iid):
                        c.port_type = "Blank" if clear else str(port_type)
        except Exception:
            pass
    return applied


def composition_report(board: Any) -> Dict[str, Any]:
    """Summary + Gen2-style save validity (for editor feedback)."""
    try:
        from core.board_settings_service import validate_playboard_for_save

        v = validate_playboard_for_save(board)
        return {
            "type_counts": dict(v.get("type_counts") or {}),
            "value_counts": dict(v.get("value_counts") or {}),
            "blank": int(v.get("blank") or 0),
            "port_pairs_set": int(v.get("port_pairs_set") or 0),
            "type_ok": bool((v.get("checks") or {}).get("tile_types")),
            "values_ok": bool((v.get("checks") or {}).get("tile_values")),
            "desert_ok": bool((v.get("checks") or {}).get("desert")),
            "six_eight_ok": bool((v.get("checks") or {}).get("six_eight_adjacent")),
            "harbors_ok": bool((v.get("checks") or {}).get("harbors")),
            "playable": bool(v.get("ok")),
            "issues": list(v.get("issues") or []),
            "checks": dict(v.get("checks") or {}),
            "message": str(v.get("message") or ""),
        }
    except Exception:
        # Minimal fallback if service import fails
        blank = 0
        type_counts: Dict[str, int] = {}
        for t in list(getattr(board, "tiles", []) or []):
            if t is None:
                continue
            ty = str(getattr(t, "type", "") or "")
            if ty in ("Sea", "Water"):
                continue
            type_counts[ty] = type_counts.get(ty, 0) + 1
            if ty == "Blank":
                blank += 1
        return {
            "type_counts": type_counts,
            "value_counts": {},
            "blank": blank,
            "port_pairs_set": 0,
            "type_ok": False,
            "playable": blank == 0,
            "issues": [f"{blank} blank"] if blank else ["validation unavailable"],
        }


def editor_tools_panel_rect() -> pygame.Rect:
    """Right-column rect for Empty/Edit tools (same slot as Board Settings menu)."""
    try:
        from gui.gui_board_settings import board_settings_panel_rect

        return board_settings_panel_rect()
    except Exception:
        return pygame.Rect(PLAYBOARD_RECT.right + 10, PLAYBOARD_RECT.y, 280, 420)


def draw_editor(game: Any, state: Dict[str, Any]) -> None:
    """Paint playboard (normal place) + right-side Empty/Edit sub-menu."""
    ensure_editor_state(state)
    board = getattr(game, "board", None)
    gui = getattr(game, "gui", None)

    # Playboard only — same drawing as normal play (no extra port text overlays)
    if gui is not None and board is not None:
        try:
            gui.draw_board_base(board)
            if callable(getattr(gui, "draw_all_permanent_buildings", None)):
                gui.draw_all_permanent_buildings(board, block_visual=False)
            # Empty-board only: outline blank land tiles (not on Edit of a full board)
            if str(state.get("editor_kind") or "") == "empty":
                _draw_blank_highlights(board)
        except Exception:
            pass

    # Right-column sub-menu (title + tools + Save/Cancel)
    tools_rect = editor_tools_panel_rect()
    pygame.draw.rect(WIN, COLORS.get("LGRAY", (200, 200, 200)), tools_rect)
    pygame.draw.rect(WIN, COLORS.get("DRED", (139, 0, 0)), tools_rect, 2)

    kind = str(state.get("editor_kind") or "edit")
    title = (
        "Settings Empty Board"
        if kind == "empty"
        else "Settings Edit Board"
    )
    tf = _font("large", bold=True)
    body = _font("normal")
    try:
        small = Font.SMALL.value["regular"] if isinstance(Font.SMALL.value, dict) else body
    except Exception:
        small = body

    # Title may wrap in narrow right panel
    title_lines = []
    words = title.split()
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if tf.size(trial)[0] <= tools_rect.width - 20:
            cur = trial
        else:
            if cur:
                title_lines.append(cur)
            cur = w
    if cur:
        title_lines.append(cur)
    ty = tools_rect.y + 10
    for ln in title_lines[:2]:
        WIN.blit(tf.render(ln, True, COLORS.get("DRED", (139, 0, 0))), (tools_rect.x + 10, ty))
        ty += tf.get_height() + 2

    status = str(state.get("editor_status") or state.get("status_line") or "")
    if status:
        # Status under title inside right panel
        s = status
        while small.size(s)[0] > tools_rect.width - 20 and len(s) > 8:
            s = s[:-4] + "…"
        WIN.blit(
            small.render(s, True, COLORS.get("DRED", (139, 0, 0))),
            (tools_rect.x + 10, ty + 2),
        )
        ty += 16

    # Tools start below title
    content_top = max(ty + 8, tools_rect.y + 52)
    content_rect = pygame.Rect(
        tools_rect.x,
        content_top,
        tools_rect.width,
        tools_rect.bottom - content_top,
    )
    hit = _draw_tool_panel(state, content_rect, board)
    state["editor_hit_rects"] = hit


def _draw_blank_highlights(board: Any) -> None:
    tiles_pos = POSITIONS.get("tiles") or {}
    for tid in land_tile_ids(board):
        tile = get_tile(board, tid)
        if tile is None or str(getattr(tile, "type", "")) != "Blank":
            continue
        coords = tiles_pos.get(tid) or tiles_pos.get(str(tid))
        if not coords:
            continue
        cx, cy = int(coords[0]), int(coords[1])
        pygame.draw.circle(WIN, COLORS.get("DRED", (180, 0, 0)), (cx, cy), 22, 2)


def _draw_tool_panel(state: Dict[str, Any], tools_rect: pygame.Rect, board: Any) -> Dict[str, Tuple[int, int, int, int]]:
    """Draw tools/palette/Save-Cancel inside *tools_rect* (right column content area)."""
    hit: Dict[str, Tuple[int, int, int, int]] = {}
    body = _font("normal")
    small = _font("small")
    x0 = tools_rect.x + 8
    y = tools_rect.y + 4
    inner_w = max(80, tools_rect.width - 16)

    # Save / Cancel fixed at bottom of right panel first (reserve space)
    save_h = 32
    gap_btn = 6
    cancel_r = pygame.Rect(x0, tools_rect.bottom - save_h - 8, inner_w, save_h)
    save_r = pygame.Rect(x0, cancel_r.y - save_h - gap_btn, inner_w, save_h)
    checks_bottom = save_r.y - 8

    WIN.blit(small.render("Tool", True, COLORS.get("BLACK", (0, 0, 0))), (x0, y))
    y += 16
    tool = str(state.get("editor_tool") or TOOL_TERRAIN)
    # Three tool buttons in a row if wide enough, else stack
    btn_w = max(70, (inner_w - 8) // 3)
    for i, (name, label) in enumerate(
        ((TOOL_TERRAIN, "Terrain"), (TOOL_NUMBER, "Number"), (TOOL_PORT, "Port"))
    ):
        r = pygame.Rect(x0 + i * (btn_w + 4), y, btn_w, 26)
        border = COLORS.get("GREEN", (0, 180, 0)) if tool == name else COLORS.get("DGRAY", (90, 90, 90))
        pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
        pygame.draw.rect(WIN, border, r, 2)
        WIN.blit(small.render(label, True, COLORS.get("BLACK", (0, 0, 0))), (r.x + 4, r.y + 5))
        hit[f"tool:{name}"] = (r.x, r.y, r.w, r.h)
    y += 32

    WIN.blit(small.render("Palette", True, COLORS.get("BLACK", (0, 0, 0))), (x0, y))
    y += 16

    if tool == TOOL_TERRAIN:
        selected = str(state.get("editor_terrain") or NO_SELECTION)
        for terr in TERRAIN_TYPES:
            if y + 24 > checks_bottom - 90:
                break
            r = pygame.Rect(x0, y, inner_w, 24)
            border = COLORS.get("GREEN", (0, 180, 0)) if terr == selected else COLORS.get("DGRAY", (90, 90, 90))
            pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
            pygame.draw.rect(WIN, border, r, 2)
            WIN.blit(small.render(terr, True, COLORS.get("BLACK", (0, 0, 0))), (r.x + 6, r.y + 4))
            hit[f"terrain:{terr}"] = (r.x, r.y, r.w, r.h)
            y += 26
    elif tool == TOOL_NUMBER:
        selected = state.get("editor_number", NUMBER_NONE)
        row_y = y
        # First row: full-width "None" / No selection, then chit grid
        none_r = pygame.Rect(x0, row_y, inner_w, 24)
        none_sel = selected is None or selected is NUMBER_NONE
        border = COLORS.get("GREEN", (0, 180, 0)) if none_sel else COLORS.get("DGRAY", (90, 90, 90))
        pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), none_r)
        pygame.draw.rect(WIN, border, none_r, 2)
        WIN.blit(small.render("None", True, COLORS.get("BLACK", (0, 0, 0))), (none_r.x + 6, none_r.y + 4))
        hit["number:none"] = (none_r.x, none_r.y, none_r.w, none_r.h)
        row_y += 28
        cols = max(3, min(4, inner_w // 40))
        cell = max(32, (inner_w - (cols - 1) * 4) // cols)
        chits = [n for n in NUMBER_VALUES if n is not None]
        for i, num in enumerate(chits):
            r = pygame.Rect(
                x0 + (i % cols) * (cell + 4),
                row_y + (i // cols) * 30,
                cell,
                26,
            )
            if r.bottom > checks_bottom - 90:
                break
            border = COLORS.get("GREEN", (0, 180, 0)) if num == selected else COLORS.get("DGRAY", (90, 90, 90))
            pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
            pygame.draw.rect(WIN, border, r, 2)
            WIN.blit(small.render(str(num), True, COLORS.get("BLACK", (0, 0, 0))), (r.x + 8, r.y + 5))
            hit[f"number:{num}"] = (r.x, r.y, r.w, r.h)
        y = row_y + ((len(chits) + cols - 1) // cols) * 30
    else:
        selected = str(state.get("editor_port") or NO_SELECTION)
        for pt in PORT_TYPES:
            if y + 24 > checks_bottom - 90:
                break
            r = pygame.Rect(x0, y, inner_w, 24)
            border = COLORS.get("GREEN", (0, 180, 0)) if pt == selected else COLORS.get("DGRAY", (90, 90, 90))
            pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
            pygame.draw.rect(WIN, border, r, 2)
            WIN.blit(small.render(pt, True, COLORS.get("BLACK", (0, 0, 0))), (r.x + 6, r.y + 4))
            hit[f"port:{pt}"] = (r.x, r.y, r.w, r.h)
            y += 26

    # Composition mini status (Gen2 save checks) above Save/Cancel
    if board is not None:
        rep = composition_report(board)
        cy = max(y + 6, checks_bottom - 100)
        WIN.blit(small.render("Save checks", True, COLORS.get("DGRAY", (80, 80, 80))), (x0, cy))
        cy += 14
        checks = rep.get("checks") or {}
        flags = (
            ("blank", checks.get("blank", rep.get("blank", 1) == 0)),
            ("types", checks.get("tile_types", rep.get("type_ok"))),
            ("nums", checks.get("tile_values", rep.get("values_ok"))),
            ("desert", checks.get("desert", rep.get("desert_ok"))),
            ("6/8", checks.get("six_eight_adjacent", rep.get("six_eight_ok"))),
            ("ports", checks.get("harbors", rep.get("harbors_ok"))),
        )
        for lab, okf in flags:
            if cy + 12 > save_r.y - 4:
                break
            col = COLORS.get("GREEN", (0, 140, 0)) if okf else COLORS.get("DRED", (139, 0, 0))
            WIN.blit(small.render(f"{lab}:{'OK' if okf else 'NO'}", True, col), (x0, cy))
            cy += 12

    body_f = _font("normal")
    for r, lab, col in (
        (save_r, "Save board", COLORS.get("GREEN", (0, 160, 0))),
        (cancel_r, "Cancel", COLORS.get("DGRAY", (90, 90, 90))),
    ):
        pygame.draw.rect(WIN, COLORS.get("WHITE", (255, 255, 255)), r)
        pygame.draw.rect(WIN, col, r, 2)
        t = body_f.render(lab, True, COLORS.get("BLACK", (0, 0, 0)))
        WIN.blit(t, (r.x + max(6, (r.width - t.get_width()) // 2), r.y + max(4, (r.height - t.get_height()) // 2)))
    hit["save"] = (save_r.x, save_r.y, save_r.w, save_r.h)
    hit["cancel"] = (cancel_r.x, cancel_r.y, cancel_r.w, cancel_r.h)
    return hit


def handle_editor_click(game: Any, state: Dict[str, Any], pos: Tuple[int, int]) -> str:
    """Handle click in editor. Returns action: 'save'|'cancel'|'handled'|'none'."""
    ensure_editor_state(state)
    board = getattr(game, "board", None)
    hit = state.get("editor_hit_rects") or {}

    for key, tup in hit.items():
        r = pygame.Rect(*tup)
        if not r.collidepoint(pos):
            continue
        if key == "save":
            return "save"
        if key == "cancel":
            return "cancel"
        if key.startswith("tool:"):
            state["editor_tool"] = key.split(":", 1)[1]
            _reset_palette_to_no_selection(state)
            state["editor_status"] = f"Tool: {state['editor_tool']} (No selection)"
            return "handled"
        if key.startswith("terrain:"):
            state["editor_terrain"] = key.split(":", 1)[1]
            state["editor_tool"] = TOOL_TERRAIN
            state["editor_status"] = f"Terrain brush: {state['editor_terrain']}"
            return "handled"
        if key.startswith("number:"):
            raw = key.split(":", 1)[1]
            if raw in ("none", "None", NO_SELECTION, ""):
                state["editor_number"] = NUMBER_NONE
            else:
                try:
                    state["editor_number"] = int(raw)
                except Exception:
                    state["editor_number"] = NUMBER_NONE
            state["editor_tool"] = TOOL_NUMBER
            lab = "None" if state["editor_number"] is NUMBER_NONE else str(state["editor_number"])
            state["editor_status"] = f"Number brush: {lab}"
            return "handled"
        if key.startswith("port:"):
            state["editor_port"] = key.split(":", 1)[1]
            state["editor_tool"] = TOOL_PORT
            state["editor_status"] = f"Port brush: {state['editor_port']}"
            return "handled"

    if board is None:
        return "none"

    tool = str(state.get("editor_tool") or TOOL_TERRAIN)

    # Port tool: only ports (never fall through to terrain paint)
    if tool == TOOL_PORT:
        brush = str(state.get("editor_port") or NO_SELECTION)
        if brush in (NO_SELECTION, "", "None"):
            state["editor_status"] = "Select a port type first"
            return "handled"
        iid = hit_test_port_intersection(board, pos)
        if iid is not None:
            ok = apply_port(board, iid, brush)
            if ok:
                mark_editor_dirty(state)
            state["editor_status"] = (
                f"Port @{iid} → {brush}" if ok else "Port apply failed (not a harbor site)"
            )
            _refresh_board_view(game)
            return "handled"
        state["editor_status"] = "Click a harbor site (black dots or sea port hex)"
        return "handled"

    tid = hit_test_tile(board, pos)
    if tid is not None:
        if tool == TOOL_TERRAIN:
            brush = str(state.get("editor_terrain") or NO_SELECTION)
            if brush in (NO_SELECTION, "", "None"):
                state["editor_status"] = "Select a terrain type first"
                return "handled"
            ok = apply_terrain(board, tid, brush)
            if ok:
                mark_editor_dirty(state)
            state["editor_status"] = f"Tile {tid} → {brush}" if ok else "Terrain failed"
        elif tool == TOOL_NUMBER:
            brush = state.get("editor_number", NUMBER_NONE)
            if brush is None or brush is NUMBER_NONE:
                state["editor_status"] = "Select a number first"
                return "handled"
            ok = apply_number(board, tid, brush)
            if ok:
                mark_editor_dirty(state)
            state["editor_status"] = (
                f"Tile {tid} number → {brush}" if ok else "Number failed (Sea/Desert?)"
            )
        else:
            state["editor_status"] = "Unknown tool"
            return "handled"
        _refresh_board_view(game)
        return "handled"

    return "none"


def _refresh_board_view(game: Any) -> None:
    try:
        from core.board_settings_service import refresh_board_gui

        # Avoid full display_fresh_board (display.update) thrash; just redraw base next frame
        gui = getattr(game, "gui", None)
        board = getattr(game, "board", None)
        if gui is not None and board is not None and callable(getattr(gui, "draw_board_base", None)):
            gui.draw_board_base(board)
    except Exception:
        pass


def validate_for_save(board: Any, *, allow_incomplete: bool = False) -> Tuple[bool, str]:
    """Return (ok, message). Full Gen2 v045 Save checks (unless allow_incomplete).

    Hard requirements when allow_incomplete is False:
      blank land, terrain multiset, number tokens, desert value 0,
      no 6/8 adjacency, harbor multiset.
    """
    try:
        from core.board_settings_service import validate_playboard_for_save

        v = validate_playboard_for_save(board)
    except Exception as exc:
        return False, f"Cannot save: validation error ({exc})"

    if allow_incomplete:
        # Dev/test escape hatch only — still report issues
        if v.get("ok"):
            return True, str(v.get("message") or "Board meets all save requirements.")
        issues = list(v.get("issues") or [])
        return True, "Saved (incomplete allowed): " + ("; ".join(issues) if issues else "ok")

    if v.get("ok"):
        return True, str(v.get("message") or "Board meets all save requirements.")
    return False, str(v.get("message") or "Cannot save — board failed validation.")
