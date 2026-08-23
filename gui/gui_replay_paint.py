"""M-GUI G4/G6: paint playboard + scoreboard + DCard + derived “?” turn details.

Reuses ``gui.GUI`` drawing helpers on the global ``WIN`` surface. No Strategy-Engine.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.constants import ResourceCard
from core.mglog_replay import (
    DEFAULT_COLORS,
    RESOURCE_KEYS,
    ReplaySession,
    ReplayState,
    apply_turn_details_to_paint_player,
    derive_turn_details,
    empty_turn_detail_vectors,
    turn_detail_rows_from_vectors,
)
from gui import gui_replay_fx as replay_fx


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _clear_board_structures(board: Any) -> None:
    """Reset buildings/roads/robber flags for a full re-apply paint."""
    for inter in getattr(board, "intersections", []) or []:
        if inter is None:
            continue
        try:
            inter.occupied_tf = False
            inter.face = "Blank"
            inter.color = None
            inter.can_build_tf = True
        except Exception:
            pass
    for road in getattr(board, "roads", []) or []:
        if road is None:
            continue
        try:
            road.occupied_tf = False
            road.kind = None
            road.color = None
        except Exception:
            pass
    for tile in getattr(board, "tiles", []) or []:
        if tile is None:
            continue
        try:
            tile.occupied_tf = False
            if hasattr(tile, "face") and str(getattr(tile, "face", "")) == "Robber":
                tile.face = ""
            tile.current_settlements = 0
        except Exception:
            pass


def _apply_state_to_board(board: Any, state: ReplayState) -> None:
    """Write settlements/cities/roads/robber onto board objects for GUI paint."""
    _clear_board_structures(board)
    for pid, pl in state.players.items():
        color = str(pl.color or DEFAULT_COLORS.get(int(pid), "Blue"))
        for sid in pl.settlements:
            try:
                iid = int(sid)
            except Exception:
                continue
            if 0 <= iid < len(board.intersections) and board.intersections[iid] is not None:
                inter = board.intersections[iid]
                inter.occupied_tf = True
                inter.face = "Settlement"
                inter.color = color
                inter.can_build_tf = False
        for cid in pl.cities:
            try:
                iid = int(cid)
            except Exception:
                continue
            if 0 <= iid < len(board.intersections) and board.intersections[iid] is not None:
                inter = board.intersections[iid]
                inter.occupied_tf = True
                inter.face = "City"
                inter.color = color
                inter.can_build_tf = False
        for edge in pl.roads:
            try:
                a, b = int(edge[0]), int(edge[1])
            except Exception:
                continue
            if a > b:
                a, b = b, a
            # find or create road object
            road_obj = None
            for road in board.roads:
                if road and tuple(sorted(road.id)) == (a, b):
                    road_obj = road
                    break
            if road_obj is None:
                try:
                    from core.board import Road

                    road_obj = Road((a, b))
                    board.roads.append(road_obj)
                except Exception:
                    continue
            road_obj.occupied_tf = True
            road_obj.kind = "Road"
            road_obj.color = color

    if state.robber_tile is not None:
        tid = int(state.robber_tile)
        for tile in board.tiles or []:
            if tile is not None and int(getattr(tile, "id", -1)) == tid:
                tile.occupied_tf = True
                break


def replay_continuous_road_lengths(state: Any) -> Dict[int, int]:
    """WP0.1: continuous path length per seat (not road piece count).

    Uses ``core.longest_road.compute_longest_road_for_edges`` with opponent
    settlements/cities as barrier nodes — same rules as live recompute.
    """
    from core.longest_road import compute_longest_road_for_edges

    players = getattr(state, "players", None) or {}
    out: Dict[int, int] = {}
    for pid, pl in players.items():
        try:
            ip = int(pid)
        except Exception:
            continue
        barriers = set()
        for oid, op in players.items():
            try:
                if int(oid) == ip:
                    continue
            except Exception:
                if op is pl:
                    continue
            for loc in list(getattr(op, "settlements", None) or []):
                try:
                    barriers.add(int(loc))
                except Exception:
                    pass
            for loc in list(getattr(op, "cities", None) or []):
                try:
                    barriers.add(int(loc))
                except Exception:
                    pass
        res = compute_longest_road_for_edges(
            list(getattr(pl, "roads", None) or []),
            barrier_nodes=barriers,
            player_id=ip,
        )
        out[ip] = int(getattr(res, "length", 0) or 0)
    return out


def _paint_player_from_replay(
    pl_src: Any,
    *,
    size_longest_route: Optional[int] = None,
) -> SimpleNamespace:
    """Build a Player-like stub for scoreboard / DCard paint.

    ``size_longest_route``: continuous path length (WP0.1). If omitted, falls
    back to stored attribute then edge-only length without barriers (last resort).
    """
    hand = list(pl_src.hand or [0, 0, 0, 0, 0])
    while len(hand) < 5:
        hand.append(0)
    rcards = {
        ResourceCard.WHEAT: int(hand[0] or 0),
        ResourceCard.ORE: int(hand[1] or 0),
        ResourceCard.WOOD: int(hand[2] or 0),
        ResourceCard.BRICK: int(hand[3] or 0),
        ResourceCard.SHEEP: int(hand[4] or 0),
    }
    dcard_summary = []
    for row in list(pl_src.dcard_summary or []):
        dcard_summary.append(list(row))
    if not dcard_summary:
        dcard_summary = [
            ["victory_point", 0, 0, 0],
            ["knight", 0, 0, 0],
            ["two_free_roads", 0, 0, 0],
            ["year_of_plenty", 0, 0, 0],
            ["monopoly", 0, 0, 0],
        ]
    n_dc = len(list(pl_src.development_cards or []))
    # also count summary totals
    try:
        n_dc = max(
            n_dc,
            sum(
                max(0, int(r[1] or 0) + int(r[2] or 0))
                for r in dcard_summary
                if r
            ),
        )
    except Exception:
        pass

    # Unplayed VP cards for scoreboard E (new + playable)
    unplayed_vp = 0
    try:
        for row in dcard_summary:
            if row and str(row[0]) == "victory_point":
                unplayed_vp += max(0, int(row[1] or 0)) + max(0, int(row[2] or 0))
    except Exception:
        unplayed_vp = 0

    lr_len = size_longest_route
    if lr_len is None:
        try:
            lr_len = int(getattr(pl_src, "size_longest_route", None))
        except Exception:
            lr_len = None
    if lr_len is None:
        # Last resort: path length without barriers (still better than piece count)
        try:
            from core.longest_road import compute_longest_road_for_edges

            lr_len = int(
                compute_longest_road_for_edges(
                    list(getattr(pl_src, "roads", None) or []),
                    barrier_nodes=[],
                    player_id=int(getattr(pl_src, "id", 0) or 0),
                ).length
                or 0
            )
        except Exception:
            lr_len = 0

    return SimpleNamespace(
        id=int(pl_src.id),
        color=str(pl_src.color or "Blue"),
        is_human=True,  # dig view: show full RCard + DCard detail for all seats
        rcards=rcards,
        settlements=list(pl_src.settlements or []),
        cities=list(pl_src.cities or []),
        roads=list(pl_src.roads or []),
        development_cards=list(pl_src.development_cards or []),
        dcard_summary=dcard_summary,
        victory_points=int(getattr(pl_src, "vp", 0) or 0),
        points=int(getattr(pl_src, "vp", 0) or 0),
        longest_route_tf=bool(pl_src.longest_route_tf),
        largest_army_tf=bool(pl_src.largest_army_tf),
        size_longest_route=int(lr_len or 0),
        size_largest_army=int(getattr(pl_src, "army_size", 0) or 0),
        number_of_rcards=sum(int(x or 0) for x in hand),
        number_of_dcards=int(n_dc),
        # Hint for scoreboard E if gui ever reads it; live gui uses dcard_summary
        _unplayed_vp_cards=int(unplayed_vp),
        # G6: filled by apply_turn_details_to_paint_player after construction
        turn_details_resource_production=[0, 0, 0, 0, 0, 0],
        turn_details_resource_production_robber=[0, 0, 0, 0, 0, 0],
        turn_details_buy=[0, 0, 0, 0, 0, 0],
        turn_details_steal=[0, 0, 0, 0, 0, 0],
        turn_details_discard=[0, 0, 0, 0, 0, 0],
        turn_details_TwP=[0, 0, 0, 0, 0, 0],
        turn_details_last_TwPdeal=[0, 0, 0, 0, 0, 0],
        turn_details_TwB=[0, 0, 0, 0, 0, 0],
        turn_details_dcard=[0, 0, 0, 0, 0, 0],
    )


class ReplayPainter:
    """Owns Board + GUI; paints current ReplayState each frame."""

    def __init__(self, playboard_path: str, session: Optional[ReplaySession] = None):
        import pygame

        # Ensure display exists before loading images in gui_constants
        if not pygame.display.get_init():
            pygame.init()
        if pygame.display.get_surface() is None:
            pygame.display.set_mode((1225, 800))

        from core.board import Board
        from gui.gui import GUI
        from gui.gui_constants import COLORS, WIN

        self.WIN = WIN
        self.COLORS = COLORS
        self.playboard_path = str(playboard_path)
        # R1: do not auto-load constants.SAVED_PLAYBOARD before the re-play map
        self.board = Board(board_name="Base_Random", load_map=False)
        self._load_playboard(playboard_path)
        self.session = session
        # GUI requires (round, turn, game) — stub game updated each paint
        self._game_stub = SimpleNamespace(
            board=self.board,
            players=[],
            round=-2,
            turn=1,
            phase="InitialPlacement",
            state="",
            gui=None,
            sequence_number=1,
            get_current_player=lambda: None,
        )
        self.gui = GUI(-2, 1, self._game_stub)
        self._game_stub.gui = self.gui
        self._ok = True
        self._error = ""

    def _load_playboard(self, path: str) -> None:
        p = Path(path)
        try:
            # Prefer basename if in cwd/project root
            try:
                self.board.load_board(str(p))
            except Exception:
                self.board.load_board(p.name)
            self._ok = True
        except Exception as exc:
            self._ok = False
            self._error = str(exc)

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def error(self) -> str:
        return self._error

    def _details_for_state(self, state: ReplayState) -> Dict[int, Dict[str, List[int]]]:
        """G6: derive per-seat turn-detail vectors for state's R/T through cursor."""
        rows: Sequence[Any] = []
        if self.session is not None:
            rows = self.session.rows or []
        try:
            return derive_turn_details(
                rows,
                round_n=int(state.round),
                turn_n=int(state.turn),
                through_index=int(state.cursor) if state.cursor is not None else None,
            )
        except Exception:
            return {}

    def paint(self, state: ReplayState) -> None:
        """Full frame paint: board + buildings + scoreboard + round/turn + ? details."""
        import pygame
        from gui.gui_constants import (
            COLORS,
            PLAYBOARD_RECT,
            SCOREBOARD_RECT,
            WIN,
        )

        # Tests may have quit the display after another module's fixture
        if not pygame.display.get_init():
            pygame.init()
        if pygame.display.get_surface() is None:
            try:
                pygame.display.set_mode((1225, 800))
            except Exception:
                pass

        # Soft background
        try:
            WIN.fill(COLORS.get("LGRAY", (200, 200, 200)))
        except pygame.error:
            try:
                pygame.display.set_mode((1225, 800))
                WIN.fill(COLORS.get("LGRAY", (200, 200, 200)))
            except Exception:
                return

        if not self._ok:
            font = pygame.font.SysFont("segoeui", 18)
            WIN.blit(
                font.render(f"Playboard paint error: {self._error}", True, (180, 0, 0)),
                (200, 200),
            )
            return

        _apply_state_to_board(self.board, state)

        # Board base + structures
        try:
            self.gui.draw_board_base(self.board)
            self.gui.draw_all_permanent_buildings(self.board, block_visual=False)
        except Exception as exc:
            font = pygame.font.SysFont("segoeui", 16)
            WIN.blit(
                font.render(f"Board draw error: {exc}", True, (180, 0, 0)),
                (PLAYBOARD_RECT.x + 10, PLAYBOARD_RECT.y + 10),
            )

        # G6: synthetic turn details for current R/T
        details_by_pid = self._details_for_state(state)

        # Paint players for scoreboard (WP0.1: continuous LR lengths)
        lr_lens = replay_continuous_road_lengths(state)
        players = []
        for pid in sorted(state.players.keys()):
            ip = int(pid)
            pl = _paint_player_from_replay(
                state.players[pid],
                size_longest_route=lr_lens.get(ip),
            )
            apply_turn_details_to_paint_player(
                pl, details_by_pid.get(ip) or empty_turn_detail_vectors()
            )
            players.append(pl)
        if not players:
            for i in range(1, 5):
                from core.mglog_replay import ReplayPlayer

                pl = _paint_player_from_replay(
                    ReplayPlayer(id=i),
                    size_longest_route=lr_lens.get(i, 0),
                )
                apply_turn_details_to_paint_player(
                    pl, details_by_pid.get(i) or empty_turn_detail_vectors()
                )
                players.append(pl)

        # R8/C5: play rings (buy-red off D1a); C6 dice faces from state
        if self.session is not None:
            try:
                # Ensure highlight matches current state/cursor if session has one
                if getattr(self.session, "highlight", None) is None and self.session.rows:
                    from core.mglog_replay import refresh_session_highlight

                    refresh_session_highlight(self.session)
                replay_fx.apply_dcard_highlights_to_players(players, self.session)
                replay_fx.sync_dice_faces_from_session(self.gui, self.session)
                replay_fx.sync_dcard_header_play_fx_from_session(
                    self.gui, self.session
                )
            except Exception:
                pass

        def _current():
            t = max(1, min(4, int(state.turn or 1)))
            for p in players:
                if int(p.id) == t:
                    return p
            return players[0]

        def _get_turn_detail_rows_for_player(player: Any):
            """Prefer derived vectors so live GUI popup path works in re-play."""
            try:
                pid = int(getattr(player, "id", 0) or 0)
            except Exception:
                return []
            vecs = details_by_pid.get(pid) or empty_turn_detail_vectors()
            return turn_detail_rows_from_vectors(vecs)

        myturn = None
        if self.session is not None:
            try:
                myturn = replay_fx.myturn_stub_for_dcard_plays(self.session)
            except Exception:
                myturn = None

        game = SimpleNamespace(
            board=self.board,
            players=players,
            round=state.round,
            turn=state.turn,
            phase=state.phase,
            state=state.state,
            gui=self.gui,
            sequence_number=1,
            dice_roll=state.dice,
            game_over=state.game_over,
            winner=None,
            get_current_player=_current,
            get_turn_detail_rows_for_player=_get_turn_detail_rows_for_player,
            myturn=myturn,
            turn_details=myturn,
            list_of_tiles_having_robber=[state.robber_tile]
            if state.robber_tile is not None
            else [],
        )
        if state.winner_id is not None:
            for p in players:
                if int(p.id) == int(state.winner_id):
                    game.winner = p
                    break

        # Link players back to game for GUI helpers that walk player.game
        for p in players:
            try:
                p.game = game
            except Exception:
                pass

        self._game_stub = game
        self.gui.game = game
        try:
            self.gui.round = state.round
            self.gui.turn = state.turn
        except Exception:
            pass

        try:
            self.gui.update_round_turn(game, special=False)
        except Exception:
            pass
        try:
            self.gui.update_scoreboard(game)
        except Exception as exc:
            font = pygame.font.SysFont("segoeui", 14)
            WIN.blit(
                font.render(f"Scoreboard error: {exc}", True, (180, 0, 0)),
                (SCOREBOARD_RECT.x + 10, SCOREBOARD_RECT.y + 10),
            )


def create_painter(session: ReplaySession) -> ReplayPainter:
    return ReplayPainter(session.playboard_path, session=session)


__all__ = [
    "ReplayPainter",
    "create_painter",
    "_apply_state_to_board",
    "_paint_player_from_replay",
]
