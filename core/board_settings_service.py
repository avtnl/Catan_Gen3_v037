"""BS-4: Board Settings operations (random / load / save / blank).

Pure-ish helpers used by ``gui.gui_board_settings``. No menu layout here.

Also: Gen2 v045 Save-board composition validation (Empty/Edit Save).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Standard base-set composition (Gen2 settings_save_board)
EXPECTED_TILE_TYPES: Dict[str, int] = {
    "Field": 4,
    "Mountain": 3,
    "Forest": 4,
    "Hill": 3,
    "Pasture": 4,
    "Desert": 1,
}
# Counts for chits 2,3,4,5,6,8,9,10,11,12
EXPECTED_TILE_VALUES: Dict[int, int] = {
    2: 1,
    3: 2,
    4: 2,
    5: 2,
    6: 2,
    8: 2,
    9: 2,
    10: 2,
    11: 2,
    12: 1,
}
# Harbor multiset (one per pair): 4×3:1 + one of each 2:1
EXPECTED_HARBOR_TYPES: Dict[str, int] = {
    "3:1": 4,
    "2:1 Wheat": 1,
    "2:1 Ore": 1,
    "2:1 Wood": 1,
    "2:1 Brick": 1,
    "2:1 Sheep": 1,
}


def list_playboard_files(root: Optional[Path] = None) -> List[str]:
    """List playboard files in project root (locked: Playboard_*.txt + legacy)."""
    base = root if root is not None else Path.cwd()
    names: List[str] = []
    seen = set()
    patterns = (
        "Playboard_*.txt",
        "PlayBoard_*.txt",
        "PlayBoard *.txt",  # legacy space form from older save_board
    )
    try:
        for pat in patterns:
            for p in sorted(base.glob(pat)):
                if p.is_file() and p.name not in seen:
                    seen.add(p.name)
                    names.append(p.name)
    except Exception:
        pass
    return names


def make_playboard_filename(*, stamp: Optional[str] = None) -> str:
    """Product save name: ``Playboard_<d_b_Y_H_M_S>.txt``."""
    s = stamp or datetime.now().strftime("%d_%b_%Y_%H_%M_%S")
    if s.lower().endswith(".txt"):
        return s if s.startswith("Playboard") or s.startswith("PlayBoard") else f"Playboard_{s}"
    if s.startswith("Playboard") or s.startswith("PlayBoard"):
        return s if s.lower().endswith(".txt") else f"{s}.txt"
    return f"Playboard_{s}.txt"


def clear_player_pieces(game: Any) -> None:
    """Drop settlements/cities/roads on all players (board layout change)."""
    for p in list(getattr(game, "players", None) or []):
        try:
            p.settlements = []
            p.cities = []
            p.roads = []
        except Exception:
            pass
        for attr in ("sticky_commitment", "strategic_direction", "force_strategy_recalc"):
            try:
                if attr == "force_strategy_recalc":
                    setattr(p, attr, False)
                else:
                    setattr(p, attr, None)
            except Exception:
                pass


def clear_board_structures(board: Any) -> None:
    """Clear piece occupancy on intersections/roads (keep terrain if any)."""
    if board is None:
        return
    try:
        for inter in list(getattr(board, "intersections", []) or []):
            if inter is None:
                continue
            inter.occupied_tf = False
            if hasattr(inter, "face"):
                inter.face = "Blank"
            if hasattr(inter, "color"):
                inter.color = "Blank"
    except Exception:
        pass
    try:
        for road in list(getattr(board, "roads", []) or []):
            if road is None:
                continue
            if hasattr(road, "occupied_tf"):
                road.occupied_tf = False
            if hasattr(road, "occupiedYNX"):
                road.occupiedYNX = "N"
            if hasattr(road, "color"):
                road.color = "Blank"
            if hasattr(road, "type"):
                road.type = "Blank"
    except Exception:
        pass


def refresh_board_gui(game: Any) -> None:
    """Redraw playboard if GUI is present."""
    try:
        gui = getattr(game, "gui", None)
        board = getattr(game, "board", None)
        if gui is None or board is None:
            return
        if callable(getattr(gui, "display_fresh_board", None)):
            gui.display_fresh_board(board, scoreboard_tf=True)
        elif callable(getattr(gui, "draw_board_base", None)):
            gui.draw_board_base(board)
            if callable(getattr(gui, "draw_all_permanent_buildings", None)):
                gui.draw_all_permanent_buildings(board)
    except Exception:
        pass


def randomize_board(game: Any) -> Dict[str, Any]:
    """Generate a new Base_Random layout via Board._get_board()."""
    board = getattr(game, "board", None) if game is not None else None
    if board is None:
        return {"ok": False, "error": "no_board", "message": "No board on game."}
    try:
        getter = getattr(board, "_get_board", None)
        if not callable(getter):
            return {"ok": False, "error": "no_get_board", "message": "Board cannot randomize."}
        getter()
        clear_player_pieces(game)
        clear_board_structures(board)
        # Rebuild roads/ports already done inside _get_board; structures cleared after
        refresh_board_gui(game)
        return {
            "ok": True,
            "source": "random",
            "path": "",
            "message": "Random board ready. Exit and use… when finished (Save only via Edit→Save).",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "message": f"Random failed: {exc}"}


def load_playboard(game: Any, filename: str) -> Dict[str, Any]:
    """Load a Playboard/PlayBoard file into game.board."""
    board = getattr(game, "board", None) if game is not None else None
    if board is None:
        return {"ok": False, "error": "no_board", "message": "No board on game."}
    name = str(filename or "").strip()
    if not name:
        return {"ok": False, "error": "empty_name", "message": "No file selected."}
    # Resolve relative to cwd
    path = Path(name)
    if not path.is_file():
        path = Path.cwd() / name
    if not path.is_file():
        return {"ok": False, "error": "missing_file", "message": f"File not found: {name}"}
    try:
        # Ensure tile shells exist before load_board overwrites types/values
        if all(t is None for t in (getattr(board, "tiles", None) or [None])):
            if callable(getattr(board, "_add_tiles", None)):
                board._add_tiles()
            if callable(getattr(board, "_add_empty_edges_and_corners", None)):
                board._add_empty_edges_and_corners()
            if callable(getattr(board, "_add_intersections", None)):
                board._add_intersections()
        # load_board opens board_name as a filesystem path; prefix check uses basename
        board.load_board(str(path))
        clear_player_pieces(game)
        clear_board_structures(board)
        # Refresh intersection derived fields after terrain load
        try:
            if callable(getattr(board, "_add_intersections", None)):
                board._add_intersections()
            if callable(getattr(board, "_complete_edges", None)):
                board._complete_edges()
            if callable(getattr(board, "_add_roads", None)) and not list(
                getattr(board, "roads", None) or []
            ):
                board._add_roads()
            if callable(getattr(board, "_create_list_of_roads_connected_to_intersection", None)):
                board._create_list_of_roads_connected_to_intersection()
            if callable(getattr(board, "_update_intersection_types", None)):
                board._update_intersection_types()
            if callable(getattr(board, "_add_three_intersection_ids", None)):
                board._add_three_intersection_ids()
            if callable(getattr(board, "_add_two_tile_attributes", None)):
                board._add_two_tile_attributes()
        except Exception:
            pass
        refresh_board_gui(game)
        return {
            "ok": True,
            "source": "loaded",
            "path": path.name,
            "message": f"Loaded {path.name}. Exit and use… when ready.",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "message": f"Load failed: {exc}"}


def _board_layout(board: Any) -> List[List[int]]:
    layout = getattr(board, "BOARD_LAYOUT", None)
    if layout:
        return layout
    try:
        from core.board import Board

        return list(Board.BOARD_LAYOUT)
    except Exception:
        return []


def _land_tile_ids(board: Any) -> List[int]:
    ids = list(getattr(board, "LIST_OF_LAND_TILES", None) or [])
    if ids:
        return [int(x) for x in ids]
    try:
        from core.board import Board

        return list(Board.LIST_OF_LAND_TILES)
    except Exception:
        return []


def _normalize_harbor_type(port: str) -> str:
    """Map Gen2 Grain/Wool and loose aliases onto Gen3 LIST_OF_PORTTYPES labels."""
    p = str(port or "").strip()
    if not p or p.lower() in ("blank", "clear", "none", "", "?", " ?"):
        # Unset harbors default to 3:1 (empty-board product default)
        return "3:1"
    low = p.lower().replace(" ", "")
    if "3:1" in low or low in ("3/1", "three"):
        return "3:1"
    if "grain" in low or "wheat" in low or "field" in low:
        return "2:1 Wheat"
    if "ore" in low or "mountain" in low:
        return "2:1 Ore"
    if "wood" in low or "lumber" in low or "forest" in low:
        return "2:1 Wood"
    if "brick" in low or "hill" in low:
        return "2:1 Brick"
    if "sheep" in low or "wool" in low or "pasture" in low:
        return "2:1 Sheep"
    return p


def _neighbor_tile_ids(board: Any, tile_id: int) -> List[int]:
    """Adjacent tile ids via BOARD_LAYOUT (same geometry as Gen2 settings_save_board)."""
    layout = _board_layout(board)
    if not layout:
        return []
    found_r = found_c = -1
    for r, row in enumerate(layout):
        for c, tid in enumerate(row):
            if int(tid) == int(tile_id):
                found_r, found_c = r, c
                break
        if found_r >= 0:
            break
    if found_r < 0:
        return []
    r, c = found_r, found_c
    n_rows = len(layout)
    neighbors: List[int] = []

    def _add(rr: int, cc: int) -> None:
        if rr < 0 or rr >= n_rows:
            return
        row = layout[rr]
        if cc < 0 or cc >= len(row):
            return
        tid = int(row[cc])
        if tid != 0 and tid != int(tile_id):
            neighbors.append(tid)

    # Gen2: even rows 0,2,4,6 use offset neighbors; odd rows different offsets
    if r % 2 == 0:
        _add(r, c - 1)
        _add(r, c + 1)
        _add(r - 1, c - 1)
        _add(r - 1, c)
        _add(r + 1, c - 1)
        _add(r + 1, c)
    else:
        _add(r, c - 1)
        _add(r, c + 1)
        _add(r - 1, c)
        _add(r - 1, c + 1)
        _add(r + 1, c)
        _add(r + 1, c + 1)
    return neighbors


def _tiles_by_id(board: Any) -> Dict[int, Any]:
    out: Dict[int, Any] = {}
    for t in list(getattr(board, "tiles", []) or []):
        if t is None:
            continue
        try:
            out[int(getattr(t, "id", -1))] = t
        except Exception:
            pass
    return out


def validate_playboard_for_save(board: Any) -> Dict[str, Any]:
    """Gen2 v045 Save-board checks (all required before write).

    Checks:
      1. No blank land tiles
      2. Correct terrain multiset (4/3/4/3/4/1 Field…Desert)
      3. Correct number-token multiset (2×1 … 12×1; desert excluded)
      4. Exactly one Desert with value 0
      5. No adjacent 6 and 8 (layout neighbors)
      6. Correct harbor multiset (4×3:1 + five 2:1 types)

    Returns dict with ok, checks, issues, message, and count details.
    """
    if board is None:
        return {
            "ok": False,
            "checks": {},
            "issues": ["no board"],
            "message": "Cannot save: no board.",
        }

    by_id = _tiles_by_id(board)
    land_ids = _land_tile_ids(board)
    land_set = set(land_ids) if land_ids else set(by_id.keys())

    type_counts: Dict[str, int] = {k: 0 for k in EXPECTED_TILE_TYPES}
    value_counts: Dict[int, int] = {k: 0 for k in EXPECTED_TILE_VALUES}
    blank = 0
    desert_ok = False
    desert_count = 0

    for tid in sorted(land_set):
        tile = by_id.get(int(tid))
        if tile is None:
            blank += 1
            continue
        ty = str(getattr(tile, "type", "") or "")
        if ty in ("Sea", "Water"):
            continue
        if ty == "Blank" or ty == "":
            blank += 1
            continue
        if ty in type_counts:
            type_counts[ty] += 1
        elif ty not in ("Blank",):
            # Unknown land type — count toward failure via type_ok
            type_counts[ty] = type_counts.get(ty, 0) + 1
        try:
            val = int(getattr(tile, "value", 0) or 0)
        except Exception:
            val = 0
        if ty == "Desert":
            desert_count += 1
            if val == 0:
                desert_ok = True
        elif ty in EXPECTED_TILE_TYPES and ty != "Desert":
            if val in value_counts:
                value_counts[val] += 1
            elif val != 0:
                value_counts[val] = value_counts.get(val, 0) + 1

    # Also scan all tiles if land list empty / incomplete (Gen2 iterated all)
    if not land_ids:
        type_counts = {k: 0 for k in EXPECTED_TILE_TYPES}
        value_counts = {k: 0 for k in EXPECTED_TILE_VALUES}
        blank = 0
        desert_ok = False
        desert_count = 0
        for tile in list(getattr(board, "tiles", []) or []):
            if tile is None:
                continue
            ty = str(getattr(tile, "type", "") or "")
            if ty in ("Sea", "Water"):
                continue
            if ty == "Blank" or ty == "":
                blank += 1
                continue
            if ty in type_counts:
                type_counts[ty] += 1
            try:
                val = int(getattr(tile, "value", 0) or 0)
            except Exception:
                val = 0
            if ty == "Desert":
                desert_count += 1
                if val == 0:
                    desert_ok = True
            elif ty in EXPECTED_TILE_TYPES and val in value_counts:
                value_counts[val] += 1

    types_ok = blank == 0 and all(
        type_counts.get(k, 0) == exp for k, exp in EXPECTED_TILE_TYPES.items()
    )
    # No extra unexpected land types beyond the six
    extra_types = [
        k
        for k, v in type_counts.items()
        if k not in EXPECTED_TILE_TYPES and v > 0 and k not in ("Sea", "Water", "Blank")
    ]
    if extra_types:
        types_ok = False

    values_ok = all(
        value_counts.get(k, 0) == exp for k, exp in EXPECTED_TILE_VALUES.items()
    ) and blank == 0
    # No unexpected non-zero values on resource tiles
    for k, v in value_counts.items():
        if k not in EXPECTED_TILE_VALUES and v > 0:
            values_ok = False

    desert_check = desert_ok and desert_count == 1 and type_counts.get("Desert", 0) == 1

    # 6 / 8 adjacency
    six_eight_ok = True
    six_eight_pairs: List[Tuple[int, int]] = []
    for tid, tile in by_id.items():
        try:
            val = int(getattr(tile, "value", 0) or 0)
        except Exception:
            continue
        if val not in (6, 8):
            continue
        for nid in _neighbor_tile_ids(board, tid):
            nt = by_id.get(int(nid))
            if nt is None:
                continue
            try:
                nval = int(getattr(nt, "value", 0) or 0)
            except Exception:
                continue
            if nval in (6, 8):
                six_eight_ok = False
                a, b = sorted((int(tid), int(nid)))
                if (a, b) not in six_eight_pairs:
                    six_eight_pairs.append((a, b))

    # Harbors: one count per INTERSECTIONS_ARE_PORT pair
    harbor_counts: Dict[str, int] = {k: 0 for k in EXPECTED_HARBOR_TYPES}
    pairs = list(getattr(board, "INTERSECTIONS_ARE_PORT", None) or [])
    if not pairs:
        try:
            from core.board import Board

            pairs = list(Board.INTERSECTIONS_ARE_PORT)
        except Exception:
            pairs = []
    inters = list(getattr(board, "intersections", []) or [])

    def _inter(iid: int) -> Any:
        if 0 <= iid < len(inters):
            cand = inters[iid]
            if cand is not None:
                return cand
        for cand in inters:
            if cand is not None and int(getattr(cand, "id", -1)) == iid:
                return cand
        return None

    pairs_with_port = 0
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            a_id, b_id = int(pair[0]), int(pair[1])
        except Exception:
            continue
        a, b = _inter(a_id), _inter(b_id)
        port_a = _normalize_harbor_type(str(getattr(a, "port_type", "") or "")) if a else ""
        port_b = _normalize_harbor_type(str(getattr(b, "port_type", "") or "")) if b else ""
        port = port_a or port_b
        # Blank / unset harbor sites count as 3:1 (matches empty-board default + draw)
        if not port:
            port = "3:1"
        pairs_with_port += 1
        if port in harbor_counts:
            harbor_counts[port] += 1
        else:
            harbor_counts[port] = harbor_counts.get(port, 0) + 1

    harbors_ok = pairs_with_port == 9 and all(
        harbor_counts.get(k, 0) == exp for k, exp in EXPECTED_HARBOR_TYPES.items()
    )
    for k, v in harbor_counts.items():
        if k not in EXPECTED_HARBOR_TYPES and v > 0:
            harbors_ok = False

    blank_ok = blank == 0

    checks = {
        "blank": blank_ok,
        "tile_types": types_ok,
        "tile_values": values_ok,
        "desert": desert_check,
        "six_eight_adjacent": six_eight_ok,
        "harbors": harbors_ok,
    }

    issues: List[str] = []
    if not blank_ok:
        issues.append(f"{blank} blank land tile(s)")
    if not types_ok:
        got = ", ".join(f"{k}={type_counts.get(k, 0)}" for k in EXPECTED_TILE_TYPES)
        issues.append(f"terrain counts wrong (need 4/3/4/3/4/1; got {got})")
    if not values_ok:
        got = ", ".join(f"{k}×{value_counts.get(k, 0)}" for k in sorted(EXPECTED_TILE_VALUES))
        issues.append(f"number tokens wrong (need 2×1,3–11×2,12×1; got {got})")
    if not desert_check:
        issues.append("desert must be exactly one tile with value 0")
    if not six_eight_ok:
        pair_s = ", ".join(f"{a}-{b}" for a, b in six_eight_pairs[:4])
        issues.append(f"6 and 8 must not be adjacent ({pair_s or 'detected'})")
    if not harbors_ok:
        got = ", ".join(f"{k}={harbor_counts.get(k, 0)}" for k in EXPECTED_HARBOR_TYPES)
        issues.append(f"harbors wrong (need 4×3:1 + one each 2:1; pairs={pairs_with_port}/9; {got})")

    ok = all(checks.values())
    if ok:
        message = "Board meets all save requirements."
    else:
        message = "Cannot save — fix: " + "; ".join(issues)

    return {
        "ok": ok,
        "checks": checks,
        "issues": issues,
        "message": message,
        "blank": blank,
        "type_counts": type_counts,
        "value_counts": value_counts,
        "harbor_counts": harbor_counts,
        "port_pairs_set": pairs_with_port,
        "six_eight_pairs": six_eight_pairs,
        "desert_count": desert_count,
    }


def save_playboard(
    game: Any,
    filename: Optional[str] = None,
    *,
    validate: bool = False,
) -> Dict[str, Any]:
    """Save current board as Playboard_<stamp>.txt (or given name).

    If ``validate`` is True, run Gen2-style composition checks first and refuse
    to write on failure (Empty/Edit Save uses validate via validate_for_save).
    """
    board = getattr(game, "board", None) if game is not None else None
    if board is None:
        return {"ok": False, "error": "no_board", "message": "No board on game."}
    if validate:
        v = validate_playboard_for_save(board)
        if not v.get("ok"):
            return {
                "ok": False,
                "error": "validation_failed",
                "message": str(v.get("message") or "Board failed save validation."),
                "validation": v,
            }
    path = make_playboard_filename(stamp=filename) if filename else make_playboard_filename()
    try:
        # Board.save_board returns path when updated (BS-4)
        written = board.save_board(path)
        if written:
            path = str(written)
        return {
            "ok": True,
            "source": "saved",
            "path": Path(path).name,
            "message": f"Saved {Path(path).name}. Exit and use… when ready.",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "message": f"Save failed: {exc}"}


def _set_all_harbors(board: Any, port_type: str = "3:1") -> None:
    """Assign *port_type* to every INTERSECTIONS_ARE_PORT pair (both endpoints)."""
    pairs = list(getattr(board, "INTERSECTIONS_ARE_PORT", None) or [])
    inters = list(getattr(board, "intersections", []) or [])
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        for raw in pair:
            try:
                iid = int(raw)
            except Exception:
                continue
            inter = None
            if 0 <= iid < len(inters):
                inter = inters[iid]
            if inter is None:
                for cand in inters:
                    if cand is not None and int(getattr(cand, "id", -1)) == iid:
                        inter = cand
                        break
            if inter is None:
                continue
            inter.port_tf = True
            inter.port_type = str(port_type)


def blank_board(game: Any) -> Dict[str, Any]:
    """Set land tiles to Blank / 0 (Empty/Edit Cancel). Harbors default to 3:1 (not '?')."""
    board = getattr(game, "board", None) if game is not None else None
    if board is None:
        return {"ok": False, "error": "no_board", "message": "No board on game."}
    try:
        for tile in list(getattr(board, "tiles", []) or []):
            if tile is None:
                continue
            ty = str(getattr(tile, "type", "") or "")
            if ty in ("Sea", "Water"):
                continue
            tile.type = "Blank"
            tile.value = 0
            if hasattr(tile, "face"):
                tile.face = "Blank"
            if hasattr(tile, "color"):
                tile.color = "Blank"
        for inter in list(getattr(board, "intersections", []) or []):
            if inter is None:
                continue
            try:
                inter.port_tf = False
                inter.port_type = "Blank"
                inter.occupied_tf = False
                if hasattr(inter, "face"):
                    inter.face = "Blank"
                if hasattr(inter, "color"):
                    inter.color = "Blank"
            except Exception:
                pass
        # Product: default harbors to 3:1 (no "?" placeholders)
        _set_all_harbors(board, "3:1")
        clear_player_pieces(game)
        clear_board_structures(board)
        refresh_board_gui(game)
        return {
            "ok": True,
            "source": "blank",
            "path": "",
            "message": "Board blank. Exit and use… disabled.",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "message": f"Blank failed: {exc}"}


def prepare_empty_board(game: Any) -> Dict[str, Any]:
    """Start Empty board flow: blank land + default 3:1 harbors."""
    return blank_board(game)
