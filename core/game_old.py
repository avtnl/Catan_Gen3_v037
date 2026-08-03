"""
Manages the Catan game logic.

This module defines the Game class, handling game state, player management, board interactions,
turn details, and resource card tracking. It initializes all attributes for the initial empty
board state and includes methods for game progression, such as advancing turns and distributing
resources.

Key components:
    - Game: Manages game state, players, board, and GUI.
    - StrategyDashboard: Tracks player statistics for the scoreboard.
    - TurnDetails: Tracks per-turn details.
    - ResourceCardDashboard: Tracks resource card distribution.
    - Settings: Manages game settings.

Dependencies:
    - typing: For type hints.
    - gui.gui_constants: For player colors.
    - core.board: For board interactions.
    - core.player: For player management.
    - gui.gui: For GUI updates (forward reference).
    - core.constants: For game configuration constants.
"""
import pygame
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, TYPE_CHECKING
from datetime import datetime
import random
from core.board import Board
from core.player import Player
from core.constants import HUMAN_PLAYER, HP_ID, FNFREQ, FILENAME_FREQ, MG, FILENAME_MG, FILENAME_MGLOG, MEM_TWP, SAVE_PATH, PlayerColor, ResourceCard, TERRAIN_TO_RESOURCE
from core.markov_evaluator import MarkovEvaluator
from core.action_planner import ActionPlanner
try:
    from core.turn_event_ledger import (
        TurnEventLedger,
        CATEGORY_TO_LEGACY_ATTR,
        DISPLAY_CATEGORY_ORDER,
        RESOURCE_ORDER as TURN_EVENT_RESOURCE_ORDER,
    )
except Exception:  # pragma: no cover - keeps older partial installs importable
    TurnEventLedger = None
    CATEGORY_TO_LEGACY_ATTR = {
        "resource_production": "turn_details_resource_production",
        "resource_production_robber": "turn_details_resource_production_robber",
        "buy": "turn_details_buy",
        "steal": "turn_details_steal",
        "discard": "turn_details_discard",
        "TwP": "turn_details_TwP",
        "TwB": "turn_details_TwB",
        "dcard": "turn_details_dcard",
    }
    DISPLAY_CATEGORY_ORDER = [
        ("RP", "resource_production"),
        ("RP Corr", "resource_production_robber"),
        ("Buy", "buy"),
        ("Steal", "steal"),
        ("Discard", "discard"),
        ("TwP", "TwP"),
        ("TwB", "TwB"),
        ("Dcard", "dcard"),
    ]
    TURN_EVENT_RESOURCE_ORDER = ["Wheat", "Ore", "Wood", "Brick", "Sheep", "Gold"]

if TYPE_CHECKING:
    from gui.gui import GUI

class StrategyDashboard:
    """Tracks player statistics for the scoreboard."""
   
    def __init__(
        self,
        player_id: int,
        victory_points: int = 0,
        number_of_settlements: int = 0,
        number_of_cities: int = 0,
        victory_points_dcard: int = 0,
        longest_road: int = 0,
        largest_army: int = 0,
        number_of_rcards: int = 0,
        number_of_dcards: int = 0,
        distribution_of_tile_values: str = "00000X00000",
        distribution_of_tile_types: str = "000000"
    ) -> None:
        """Initialize a StrategyDashboard.

        Args:
            player_id: The player ID (1-4).
            victory_points: Total victory points.
            number_of_settlements: Number of settlements.
            number_of_cities: Number of cities.
            victory_points_dcard: Victory points from development cards.
            longest_road: Length of the longest road.
            largest_army: Number of knights played.
            number_of_rcards: Number of resource cards.
            number_of_dcards: Number of development cards.
            distribution_of_tile_values: Distribution of tile values as a string.
            distribution_of_tile_types: Distribution of tile types as a string.
        """
        self.player_id = player_id
        self.victory_points = victory_points
        self.number_of_settlements = number_of_settlements
        self.number_of_cities = number_of_cities
        self.victory_points_dcard = victory_points_dcard
        self.longest_road = longest_road
        self.largest_army = largest_army
        self.number_of_rcards = number_of_rcards
        self.number_of_dcards = number_of_dcards
        self.distribution_of_tile_values = distribution_of_tile_values
        self.distribution_of_tile_types = distribution_of_tile_types

class TurnDetails:
    """Keeps track of specific details to be renewed every turn."""
   
    def __init__(
        self,
        round_num: int,
        turn: int,
        dice_roll: int,
        validate_function_enough: bool,
        validate_function_TwP_Match: bool,
        validate_function_discard_rcards_by_HP: bool,
        validate_function_set_robber_by_HP: bool,
        validate_function_outlook_opponents_for_HP: bool,
        validate_function_built_two_roads: int,
        question_mark_button: List[int]
    ) -> None:
        """Initialize TurnDetails.

        Args:
            round_num: Current game round number.
            turn: Current player's turn number.
            dice_roll: Sum of the dice roll.
            validate_function_enough: Whether enough resources are available.
            validate_function_TwP_Match: Whether trade with player matches.
            validate_function_discard_rcards_by_HP: Whether human player must discard resource cards.
            validate_function_set_robber_by_HP: Whether human player must set the robber.
            validate_function_outlook_opponents_for_HP: Whether to outlook opponents for human player.
            validate_function_built_two_roads: Number of roads built this turn.
            question_mark_button: Status of question mark buttons per player.
        """
        self.round = round_num
        self.turn = turn
        self.dice_roll = dice_roll
        self.validate_function_enough = validate_function_enough
        self.validate_function_TwP_Match = validate_function_TwP_Match
        self.validate_function_discard_rcards_by_HP = validate_function_discard_rcards_by_HP
        self.validate_function_set_robber_by_HP = validate_function_set_robber_by_HP
        self.validate_function_outlook_opponents_for_HP = validate_function_outlook_opponents_for_HP
        self.validate_function_built_two_roads = validate_function_built_two_roads
        self.road_built_in_turn_TF = False
        self.roads_built_in_turn: List[Tuple[int, int]] = []
        self.settlement_built_in_turn_TF = False
        self.settlements_built_in_turn: List[int] = []
        self.city_built_in_turn_TF = False
        self.cities_built_in_turn: List[int] = []
        self.question_mark_button = question_mark_button
        self.dcard_played_in_turn = [0, 0, 0, 0, 0]
        self.dcard_played_in_turn_TF = False
        self.tile_type_selected_1 = [0, 0, 0, 0, 0]
        self.tile_type_selected_2 = [0, 0, 0, 0, 0]
        self.players_having_too_many_rcards = [0, 0, 0, 0, 0]
        self.rcard_give = [0, 0, 0, 0, 0]
        self.rcard_get = [0, 0, 0, 0, 0]
        self.list_of_TwP: List = []
        self.number_of_deals_offered = 0
        self.list_of_TwP_rejected_by_HP: List = []
        self.list_of_TwHP = [0, 0, 0, 0, 0]
        self.dcard_selected = [0, 0, 0, 0, 0]
        self.modes: List = []

    def clear_turn_details(self) -> None:
        """Clear all turn details to their initial values.

        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("turn_details.py | clear_turn_details\n")
        self.dice_roll = 0
        self.validate_function_enough = False
        self.validate_function_TwP_Match = False
        self.validate_function_discard_rcards_by_HP = False
        self.validate_function_set_robber_by_HP = False
        self.validate_function_outlook_opponents_for_HP = False
        self.road_built_in_turn_TF = False
        self.roads_built_in_turn = []
        self.settlement_built_in_turn_TF = False
        self.settlements_built_in_turn = []
        self.city_built_in_turn_TF = False
        self.cities_built_in_turn = []
        self.dcard_played_in_turn = [0, 0, 0, 0, 0]
        self.dcard_played_in_turn_TF = False
        self.tile_type_selected_1 = [0, 0, 0, 0, 0]
        self.tile_type_selected_2 = [0, 0, 0, 0, 0]
        self.question_mark_button = [0, 0, 0, 0, 0, 0]
        self.players_having_too_many_rcards = [0, 0, 0, 0, 0]
        self.rcard_give = [0, 0, 0, 0, 0]
        self.rcard_get = [0, 0, 0, 0, 0]
        self.list_of_TwP = []
        self.number_of_deals_offered = 0
        if not MEM_TWP:
            self.list_of_TwP_rejected_by_HP = []
        self.list_of_TwHP = []
        self.dcard_selected = [0, 0, 0, 0, 0]
        self.modes = []

    def validate_list_of_TwP(self, game: 'Game') -> None:
        """Validate the list of Trade with Players (TwP).

        Args:
            game: The game instance containing player data.
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{game.sequence_number} | {game.state} | turn_details.py | validate_list_of_TwP\n")
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write("turn_details.py | validate_list_of_TwP | Before\n")
                for deal in self.list_of_TwP:
                    f.write(f"{deal}\n")
        idx = 0
        while idx < len(self.list_of_TwP):
            deal = self.list_of_TwP[idx]
            for player in game.players:
                if player.id == deal[2]:
                    rcards = player.rcards_in_hand()
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            f.write(f"turn_details.py | validate_list_of_TwP | rcards_in_hand: {rcards[0]}\n")
                    for card_idx in range(5):
                        if rcards[0][card_idx] == 0 and deal[5] > 0:
                            self.list_of_TwP.pop(idx)
                            idx -= 1
                            break
            idx += 1
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write("turn_details.py | validate_list_of_TwP | After\n")
                for deal in self.list_of_TwP:
                    f.write(f"{deal}\n")

class ResourceCardDashboard:
    """Tracks resource card distribution across the game."""
   
    def __init__(
        self,
        resource_production_game_total: List[int],
        resource_production_game_player: List[List[int]],
        resource_production_game_player_view: List[List[int]]
    ) -> None:
        """Initialize a ResourceCardDashboard.

        Args:
            resource_production_game_total: Total resources distributed [Wheat, Ore, Wood, Brick, Sheep, Gold].
            resource_production_game_player: Per-player resources [[player_id, Wheat, Ore, Wood, Brick, Sheep, Gold], ...].
            resource_production_game_player_view: Each player's view of others' resources [[viewer_id, viewed_id, Wheat, Ore, Wood, Brick, Sheep , Gold, QM_Added, QM_Discarded], ...].
        """
        self.resource_production_game_total = resource_production_game_total
        self.resource_production_game_player = resource_production_game_player
        self.resource_production_game_player_view = resource_production_game_player_view

class Settings:
    """Manages game settings."""
   
    def __init__(
        self,
        human_player_tf: str,
        human_player_sequence: int,
        topx_tf: str,
        topx: int,
        weight_balanced: float,
        weight_wood_brick: float,
        weight_wheat_ore: float,
        weight_wheat_ore_sheep: float,
        weight_monopoly: float,
        weight_probability: float,
        weight_blocked: float,
        user_text1: str,
        user_text2: str,
        user_text3: str
    ) -> None:
        """Initialize Settings.

        Args:
            human_player_tf: Whether human player is enabled ('True' or 'False').
            human_player_sequence: Human player sequence (e.g., 3).
            topx_tf: Whether top-x is enabled ('True' or 'False').
            topx: Top-x value (e.g., 15).
            weight_balanced: Weight for balanced strategy.
            weight_wood_brick: Weight for wood/brick resource strategy.
            weight_wheat_ore: Weight for wheat/ore resource strategy.
            weight_wheat_ore_sheep: Weight for wheat/ore/sheep resource strategy.
            weight_monopoly: Weight for monopoly strategy.
            weight_probability: Weight for probability-based strategy.
            weight_blocked: Weight for blocked strategy.
            user_text1: Port user text 1 (e.g., '3').
            user_text2: Port user text 2 (e.g., '2').
            user_text3: Port user text 3 (e.g., '1').
        """
        self.human_player_tf = human_player_tf
        self.human_player_sequence = human_player_sequence
        self.topx_tf = topx_tf
        self.topx = topx
        self.weight_balanced = weight_balanced
        self.weight_wood_brick = weight_wood_brick
        self.weight_wheat_ore = weight_wheat_ore
        self.weight_wheat_sheep = weight_wheat_ore_sheep
        self.weight_monopoly = weight_monopoly
        self.weight_probability = weight_probability
        self.weight_blocked = weight_blocked
        self.user_text1 = user_text1
        self.user_text2 = user_text2
        self.user_text3 = user_text3

class Game:
    """Represents a Catan game instance."""
   
    def __init__(
        self,
        sequence_number: int,
        id_: str,
        phase: str,
        state: str,
        state_1: str,
        state_2: str,
        myplayers: List[Player],
        board_name: str
    ) -> None:
        """Initialize a Game.

        Args:
            sequence_number: Game sequence number (e.g., 1).
            id_: Unique game ID (e.g., timestamp-based string).
            phase: Game phase (e.g., 'Initial Placement', 'Execution').
            state: Game state (e.g., 'None').
            state_1: Additional state information (e.g., '0').
            state_2: Additional state information (e.g., '0').
            myplayers: List of players or None to initialize new players.
            board_name: Name of the board (e.g., 'Base_Random').
        """
        self.manager = None # Placeholder for game manager
        self.sequence_number = sequence_number
        self.id = id_
        self.time_ended: Optional[str] = None
        self.phase = phase
        self.state = state
        self.state_1 = state_1
        self.state_2 = state_2
        self.round: int = -2
        self.turn: int = 1
        self.players = myplayers or self._initialize_players()
        self.board = Board(board_name)

        # ──────────────────────────────────────────────────────────────
        # LOAD SAVED PLAYBOARD (controlled from constants.py)
        #    - When LOAD_PLAYBOARD=True → completely deterministic board
        #    - Skips all randomness in _get_board()
        #    - Then runs all post-load steps automatically
        # ──────────────────────────────────────────────────────────────
        # from core.constants import LOAD_PLAYBOARD, SAVED_PLAYBOARD
        # if LOAD_PLAYBOARD:
        #     print(f"📂 Loading saved playboard: {SAVED_PLAYBOARD}")
        #     self.board.load_board(SAVED_PLAYBOARD)
        # else:
        #     print("🎲 Generating random board (Base_Random)")

        # ──────────────────────────────────────────────────────────────
        # MARKOV EVALUATOR
        # ──────────────────────────────────────────────────────────────
        # Markov is algorithm_id == 4. Do not precompute it unless an AI
        # player actually uses algorithm 4; this keeps normal 5-Strategies
        # runs fast and quiet.
        self.vertex_to_rolls = None
        self.markov = None

        uses_markov = any(
            getattr(player, "initial_placement_algorithm", None) == 4
            and not getattr(player, "is_human", False)
            for player in self.players
        )

        if uses_markov:
            import contextlib
            import io

            self.vertex_to_rolls = self.board.get_vertex_to_rolls()
            with contextlib.redirect_stdout(io.StringIO()):
                self.markov = MarkovEvaluator()
                self.markov.precompute_game(self.vertex_to_rolls)
            self.markov.board = self.board
        
        self.gui: Optional['GUI'] = None
        self.ip = None # Placeholder for InitialPlacement
        self.dice_roll: Optional[Tuple[int, int]] = None
        self.dice_rolls: List[Tuple[int, int]] = []
        self.dice_roll_history = [0] * 13 # Indices 0-12

        # Structured event ledger. This is the source of truth for
        # current-turn deltas; legacy player.turn_details_* fields are mirrors
        # used by the existing scoreboard and saved-game compatibility.
        self.turn_event_ledger = TurnEventLedger() if TurnEventLedger is not None else None

        # ──────────────────────────────────────────────────────────────
        # Execution-phase orchestration / viable-action scanning
        # ──────────────────────────────────────────────────────────────
        # Runtime-only fields. These are rebuilt after load and are not saved.
        self._execution_phase_manager = None
        self.current_viable_action_scan = None
        self.current_execution_choices = []
        self.current_strategic_needs = []
        self.current_actionable_choices = []
        # Canonical immediate action for the active turn.  Execution Debug and
        # AI Continue both use this exact object so the displayed BEST NOW target
        # cannot drift away from the mutation target.
        self.current_best_now_action = None
        self.last_execution_scan_report = None
        self.last_rescan_reason = ""
        self.last_execution_result = None
        self.execution_debug_print_tf = True

        # Runtime-only AI two-click Execution flow.  These fields are deliberately
        # not saved; they are rebuilt for the active turn.
        self.ai_execution_preview_ready = False
        self.ai_execution_preview_player_id = None
        self.ai_execution_stage = ""
        self.current_ai_execution_plan = []
        self.current_ai_decision_trace = []
        try:
            self.pending_human_twp_offer = None
            self.human_twp_accepted_this_turn = set()
            self.human_twp_declined_this_turn = set()
        except Exception:
            pass
        self.last_ai_preview_result = None
        self.last_ai_continue_result = None

        # Runtime-only Human TwP incoming-offer policy.  This controls how the
        # human player responds when an AI player wants a TwP with HP.  Save/load
        # support is a later step; for now a new game starts in Manual mode.
        self.human_twp_mode = "manual"
        self.human_twp_auto_rules = []
        self.pending_human_twp_offer = None
        self.human_twp_accepted_this_turn = set()
        self.human_twp_declined_this_turn = set()
        self.last_human_twp_response_result = {}
        self.pending_twp_auto_rules_editor = {"active": False}
        self.last_human_twp_policy_decision = {}

        # Runtime-only strategy-planner bridge.  action_planner.py owns the
        # heavy strategic report; Game persists only the current player's
        # preferred direction and a compact status for the debug panel.
        self.last_action_timing_report = None
        self.last_strategy_context_status = {
            "ok": False,
            "reason": "not_run_yet",
            "player_id": None,
        }
        self.last_strategy_context_reason = ""
        self.last_strategy_context_error = ""

        # Runtime-only 7-roll / robber flow state.
        self.pending_seven_roll = {"active": False}
        self.pending_robber_steal = {"active": False}
        self.last_7_result = None
        self.last_robber_plan = None
        self.last_robber_move_result = None
        self.last_robber_steal_selection = None
        self.last_robber_steal_result = None
        self.dice_roll_matrix: List = [] # Placeholder for dice roll matrix

        # Development-card stack.  The viable-action scanner only exposes
        # "Buy development_card" when this stack is non-empty.  Older copies
        # left this as [], which made buying dcards impossible to detect even
        # when the player had Wheat/Ore/Sheep.
        try:
            from core.constants import LIST_OF_DCARDS
            self.dcards_stack: List = list(LIST_OF_DCARDS)
            random.shuffle(self.dcards_stack)
        except Exception:
            self.dcards_stack: List = []
        self.robber_tile_probabilities = [[tile, 0.0] for tile in self.board.LIST_OF_LAND_TILES]
        self.previous_tile_having_robber = [0, 0, 0]
        self.list_of_tiles_having_robber: List = []
        self.last_total_turn_with_dr7: int = 0
        self.settings_tf = False
        self.settings = Settings(
            human_player_tf=True,
            human_player_sequence=3,
            topx_tf=True,
            topx=15,
            weight_balanced=1,
            weight_wood_brick=0.1,
            weight_wheat_ore=1,
            weight_wheat_ore_sheep=0.15,
            weight_monopoly=1,
            weight_probability=1,
            weight_blocked=0.2,
            user_text1="3",
            user_text2="2",
            user_text3="1"
        )
        self.initial_placement_balanced: List = []
        self.initial_placement_wood_brick: List = []
        self.initial_placement_wheat_ore: List = []
        self.initial_placement_wheat_ore_sheep: List = []
        self.initial_placement_monopoly: List = []
        self.resource_production_probability = [[0, 0, 0, 0, 0, 0]] + [[i, 0, 0, 0, 0, 0] for i in range(1, 5)]
        self.tile_type: List = []
        self.resource_type_available: List = []
        self.resource_type_occupied: List = []
        self.resource_type_players: List = []
        self.players_impacted = [False] * 4
        self.common_next_settlements: List = []
        self.common_new_settlements: List = []
        self.common_next_roads: List = []
        self.last_known_strategies = [[[0] * 8, 0] for _ in range(4)]
        self.last_known_outlooks = [["BBBBBBBBB", [], [], [], 0, 0, 0, 0, 0, 0, 0, [], 0, [], []] for _ in range(4)]
        self.current_player: Optional[Player] = None
        self.winner: Optional[Player] = None
        self.game_over: bool = False
        self.longest_road_player: Optional[Player] = None
        self.largest_army_player: Optional[Player] = None
        self.strategy_dashboard = [
            StrategyDashboard(i, 0, 0, 0, 0, 0, 0, 0, 0, "00000X00000", "000000")
            for i in range(1, 5)
        ]
        self.resource_card_dashboard = [
            ResourceCardDashboard(
                resource_production_game_total=[0, 0, 0, 0, 0, 0],
                resource_production_game_player=[
                    [1, 0, 0, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0, 0, 0],
                    [3, 0, 0, 0, 0, 0, 0],
                    [4, 0, 0, 0, 0, 0, 0]
                ],
                resource_production_game_player_view=[
                    [1, 2, 0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 3, 0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 4, 0, 0, 0, 0, 0, 0, 0, 0],
                    [2, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                    [2, 3, 0, 0, 0, 0, 0, 0, 0, 0],
                    [2, 4, 0, 0, 0, 0, 0, 0, 0, 0],
                    [3, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                    [3, 2, 0, 0, 0, 0, 0, 0, 0, 0],
                    [3, 4, 0, 0, 0, 0, 0, 0, 0, 0],
                    [4, 1, 0, 0, 0, 0, 0, 0, 0, 0],
                    [4, 2, 0, 0, 0, 0, 0, 0, 0, 0],
                    [4, 3, 0, 0, 0, 0, 0, 0, 0, 0]
                ]
            )
        ]
        self.myturn = TurnDetails(
            round_num=self.round,
            turn=self.turn,
            dice_roll=0,
            validate_function_enough=False,
            validate_function_TwP_Match=False,
            validate_function_discard_rcards_by_HP=False,
            validate_function_set_robber_by_HP=False,
            validate_function_outlook_opponents_for_HP=False,
            validate_function_built_two_roads=0,
            question_mark_button=[0, 0, 0, 0, 0, 0]
        )

    def _initialize_players(self) -> List[Player]:
        """
        Initialize players for the game.

        Algorithms:
        1 = _max_of_pips; acutally using _max_of_pips_and_optonal_port with use_port=False
        2 = _max_of_pips_and_port; actually using _max_of_pips_and_optonal_port with use_port=True
        3 = 5 Strategies (balanced, wood/brick, wheat/ore, wheat/ore/sheep, monopoly)
        4 = Markov AI (strong probabilistic AI based on precomputed transition matrices)

        New flag:
            human_like_placement=True  → random from top 8 best spots (more natural/human-like)
            human_like_placement=False → always pick the absolute best remaining spot (deterministic)
        """
        players = [
            Player(
                id_=1,
                color=PlayerColor.BLUE.color_name,
                sequence=1,
                is_human=(HUMAN_PLAYER and 1 in HP_ID),
                initial_placement_algorithm=1,
                human_like_placement=False           # human-like (recommended)
            ),
            Player(
                id_=2,
                color=PlayerColor.RED.color_name,
                sequence=2,
                is_human=(HUMAN_PLAYER and 2 in HP_ID),
                initial_placement_algorithm=3,
                human_like_placement=False           # human-like (recommended)
            ),
            Player(
                id_=3,
                color=PlayerColor.WHITE.color_name,
                sequence=3,
                is_human=(HUMAN_PLAYER and 3 in HP_ID),
                initial_placement_algorithm=4,
                human_like_placement=False          # doesn't matter for human
            ),
            Player(
                id_=4,
                color=PlayerColor.ORANGE.color_name,
                sequence=4,
                is_human=(HUMAN_PLAYER and 4 in HP_ID),
                initial_placement_algorithm=5,
                human_like_placement=False           # human-like (recommended)
            ),
        ]

        # Link each Player back to this Game instance
        for player in players:
            player.game = self

        return players

    def handle_oky_click(self, board: Board, player: Player) -> None:
        """Handle OKY button click for human player/operator.

        Args:
            board: The game board instance.
            player: The current player instance.
        """
        # Placeholder: Implement OKY logic
        pass

    def handle_okn_click(self, board: Board, player: Player) -> None:
        """Handle OKN button click for human player/operator.

        Args:
            board: The game board instance.
            player: The current player instance.
        """
        # Placeholder: Implement OKN logic
        pass
    
    def _is_connected_to_road(self, intersection_id: int, player: Player) -> bool:
        """Return True if intersection_id touches one of player's roads."""
        inter = self.board.intersections[intersection_id]
        if inter is None:
            return False

        for road_tuple in inter.three_roads:
            road_id = tuple(sorted(road_tuple))
            road = next((r for r in self.board.roads if r and r.id == road_id), None)
            if road and road.occupied_tf and road.color == player.color:
                return True

        return False

    def can_build_intersection_tf(self, intersection_id: int, player: Optional[Player] = None) -> bool:
        """Return True if a settlement/city can be built at the intersection.

        Distance rule is always enforced. Road connection is required only in
        normal game rounds >= 0. During initial placement, player may be None.
        """
        inter = self.board.intersections[intersection_id]

        if inter is None:
            return False
        if intersection_id in self.board.INTERSECTION_IN_WATER:
            return False
        if inter.occupied_tf:
            return False
        if self.round >= 0 and not inter.can_build_tf:
            return False

        # Distance rule: reject if adjacent to any occupied intersection.
        for other in self.board.intersections:
            if other and other.occupied_tf and other.id != intersection_id:
                dist = self.board._distance_between_intersections(intersection_id, other.id)
                if dist <= 1:
                    return False

        # Road connection is required only during the normal game.
        if self.round >= 0:
            if player is None:
                return False
            if not self._is_connected_to_road(intersection_id, player):
                return False

        return True

    def get_player_ports_dict(self, player: Player) -> dict:
        """Convert player's port_access into the dict format required by apply_trading_layer.
        Example output: {"sheep": 2, "generic": 3}"""
        if not hasattr(player, 'port_access') or not player.port_access:
            return {}

        ports_dict = {}
        for port_name, has_port in player.port_access.items():
            if not has_port:
                continue
            if port_name == "3:1":
                ports_dict["generic"] = 3
            elif port_name.startswith("2:1-"):
                # e.g. "2:1-sheep" → {"sheep": 2}
                res = port_name.split("-")[1].lower()
                if res in self.markov.RES_NAMES:   # safety
                    ports_dict[res] = 2
            # 4:1 bank is always available by default in apply_trading_layer
        return ports_dict

    def roll_dice(self) -> Tuple[int, int]:
        """Simulate rolling two dice.

        Args:
            None

        Returns:
            Tuple[int, int]: Tuple of two dice values (1-6).
        """
        return (random.randint(1, 6), random.randint(1, 6))

    def _turn_delta_category_to_attr(self) -> Dict[str, str]:
        """Return event-ledger category → legacy player vector mapping."""
        return dict(CATEGORY_TO_LEGACY_ATTR or {})

    def _canonical_turn_category(self, category: str) -> str:
        text = str(category or "").strip()
        aliases = {
            "rp": "resource_production",
            "resource production": "resource_production",
            "resource_production": "resource_production",
            "rp corr": "resource_production_robber",
            "rp_corr": "resource_production_robber",
            "resource_production_robber": "resource_production_robber",
            "buy": "buy",
            "steal": "steal",
            "discard": "discard",
            "twp": "TwP",
            "twb": "TwB",
            "dcard": "dcard",
            "development_card": "dcard",
        }
        return aliases.get(text, aliases.get(text.lower(), text))

    def _legacy_attr_for_turn_category(self, category: str) -> Optional[str]:
        category = self._canonical_turn_category(category)
        mapping = self._turn_delta_category_to_attr()
        return mapping.get(category) or mapping.get(category.lower())

    def _resource_delta_index(self, resource: Any) -> Optional[int]:
        """Return the scoreboard/delta index for a resource card.

        Delta vectors use the v045-compatible order:
            [Wheat, Ore, Wood, Brick, Sheep, Gold/unused]
        """
        normalized = self._resource_name_for_turn_delta(resource)
        for index, name in enumerate(TURN_EVENT_RESOURCE_ORDER):
            if normalized == name:
                return index
        return None

    def _resource_name_for_turn_delta(self, resource: Any) -> str:
        value = getattr(resource, "value", None)
        if value is not None:
            resource = value
        name = getattr(resource, "name", None)
        if name is not None and not isinstance(resource, str):
            resource = name
        text = str(resource).strip()
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
        return aliases.get(text.lower(), text[:1].upper() + text[1:])

    def _resource_delta_dict(self, resource: Any, amount: int) -> Dict[str, int]:
        name = self._resource_name_for_turn_delta(resource)
        if name not in TURN_EVENT_RESOURCE_ORDER:
            return {}
        try:
            amt = int(amount or 0)
        except Exception:
            amt = 0
        return {name: amt} if amt else {}

    def _ensure_turn_event_ledger(self):
        """Create/repair the event ledger if the game was loaded from older code."""
        ledger = getattr(self, "turn_event_ledger", None)
        if ledger is None and TurnEventLedger is not None:
            ledger = TurnEventLedger()
            self.turn_event_ledger = ledger
        if ledger is not None:
            try:
                if getattr(ledger, "current_round", None) is None or getattr(ledger, "current_turn", None) is None:
                    ledger.start_turn(int(getattr(self, "round", 0)), int(getattr(self, "turn", 0)))
            except Exception:
                pass
        return ledger

    def _ensure_turn_delta_vector(self, player: Player, attr_name: str) -> List[int]:
        """Return a safe 6-slot player turn-delta vector."""
        value = getattr(player, attr_name, None)
        if not isinstance(value, list):
            value = [0, 0, 0, 0, 0, 0]
        if len(value) < 6:
            value = list(value) + [0] * (6 - len(value))
        elif len(value) > 6:
            value = list(value[:6])
        setattr(player, attr_name, value)
        return value

    def _sync_player_turn_detail_from_ledger(self, player: Player, category: str) -> None:
        """Refresh one legacy player.turn_details_* vector from the ledger."""
        attr_name = self._legacy_attr_for_turn_category(category)
        if not attr_name:
            return
        ledger = self._ensure_turn_event_ledger()
        if ledger is None:
            return
        try:
            vector = ledger.resource_delta_vector(int(player.id), self._canonical_turn_category(category))
        except Exception:
            return
        setattr(player, attr_name, list(vector[:6]) + [0] * max(0, 6 - len(vector)))

    def _sync_all_turn_detail_mirrors_from_ledger(self) -> None:
        """Refresh all legacy turn_details_* mirrors from the structured ledger."""
        ledger = self._ensure_turn_event_ledger()
        if ledger is None:
            return
        categories = [category for _, category in DISPLAY_CATEGORY_ORDER]
        for player in self.players:
            for category in categories:
                self._sync_player_turn_detail_from_ledger(player, category)

    def record_turn_event(
        self,
        *,
        player: Optional[Player] = None,
        player_id: Optional[int] = None,
        event_type: str,
        category: Optional[str] = None,
        target_player_id: Optional[int] = None,
        resource_delta: Optional[Dict[Any, Any]] = None,
        public: bool = True,
        source: str = "",
        reason: str = "",
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Record one structured event in the current-turn ledger.

        This is intentionally GUI-agnostic. The twitter pane and scoreboard are
        different views over the same facts.
        """
        ledger = self._ensure_turn_event_ledger()
        if ledger is None:
            return None
        if player_id is None and player is not None:
            player_id = getattr(player, "id", None)
        try:
            current_round = int(getattr(self, "round", 0))
            current_turn = int(getattr(self, "turn", 0))
            # Keep the ledger's active turn synchronized with the events we
            # are about to append. Without this, events may be recorded with
            # the right round/turn but queried against a stale active turn.
            try:
                ledger.start_turn(current_round, current_turn)
            except Exception:
                pass
            event = ledger.add_event(
                round_num=current_round,
                turn=current_turn,
                player_id=player_id,
                event_type=event_type,
                category=category,
                target_player_id=target_player_id,
                resource_delta=resource_delta or {},
                public=public,
                source=source,
                reason=reason,
                message=message,
                metadata=metadata or {},
            )
            if player is not None and category:
                self._sync_player_turn_detail_from_ledger(player, category)
            return event
        except Exception:
            return None

    def record_turn_delta(
        self,
        player: Player,
        category: str,
        resource_delta: Optional[Dict[Any, Any]] = None,
        *,
        resource: Any = None,
        amount: Optional[int] = None,
        event_type: Optional[str] = None,
        target_player_id: Optional[int] = None,
        public: bool = True,
        source: str = "",
        reason: str = "",
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Record a resource delta and sync the legacy player vector mirror."""
        if resource_delta is None:
            resource_delta = self._resource_delta_dict(resource, int(amount or 0))
        category = self._canonical_turn_category(category)
        event = self.record_turn_event(
            player=player,
            event_type=event_type or category,
            category=category,
            target_player_id=target_player_id,
            resource_delta=resource_delta,
            public=public,
            source=source,
            reason=reason,
            message=message,
            metadata=metadata,
        )
        if event is None:
            # Fallback for older/partial installs: update the legacy vector directly.
            attr_name = self._legacy_attr_for_turn_category(category)
            if attr_name and resource_delta:
                for res, amt in resource_delta.items():
                    self.add_player_turn_resource_delta(player, attr_name, res, int(amt or 0), record_event=False)
        return event

    def add_player_turn_resource_delta(
        self,
        player: Player,
        attr_name: str,
        resource: Any,
        amount: int,
        *,
        record_event: bool = True,
        event_type: Optional[str] = None,
        source: str = "",
        reason: str = "",
        target_player_id: Optional[int] = None,
    ) -> None:
        """Add one resource delta to a player-level turn-details bucket.

        New code should prefer record_turn_delta(...). This method remains as a
        v045-compatible adapter for existing action code.
        """
        reverse_mapping = {v: k for k, v in self._turn_delta_category_to_attr().items()}
        category = reverse_mapping.get(attr_name)
        if record_event and category:
            self.record_turn_delta(
                player,
                category,
                resource=resource,
                amount=amount,
                event_type=event_type,
                source=source,
                reason=reason,
                target_player_id=target_player_id,
            )
            return

        index = self._resource_delta_index(resource)
        if index is None:
            return
        vector = self._ensure_turn_delta_vector(player, attr_name)
        vector[index] += int(amount or 0)

    def get_turn_delta_vector(self, player: Player, category: str) -> List[int]:
        """Return one player's current-turn vector for a category.

        The ledger is preferred. If no ledger data exists, fall back to the old
        player.turn_details_* field so older code remains visible.
        """
        category = self._canonical_turn_category(category)
        attr_name = self._legacy_attr_for_turn_category(category)
        ledger = self._ensure_turn_event_ledger()
        if ledger is not None:
            try:
                vector = ledger.resource_delta_vector(int(player.id), category)
                if any(int(x or 0) != 0 for x in vector):
                    return vector
            except Exception:
                pass
        if attr_name:
            return self._ensure_turn_delta_vector(player, attr_name)
        return [0, 0, 0, 0, 0, 0]

    def get_turn_detail_rows_for_player(self, player: Player) -> List[Tuple[str, List[int]]]:
        """Return display rows for the player's non-zero current-turn deltas."""
        rows: List[Tuple[str, List[int]]] = []
        for label, category in DISPLAY_CATEGORY_ORDER:
            vector = self.get_turn_delta_vector(player, category)
            if any(int(x or 0) != 0 for x in vector):
                rows.append((label, vector))
        return rows

    def clear_player_turn_details(self, player: Player) -> None:
        """Clear per-player legacy turn detail vectors for a new turn."""
        for attr_name in (
            "turn_details_resource_production",
            "turn_details_resource_production_robber",
            "turn_details_buy",
            "turn_details_steal",
            "turn_details_discard",
            "turn_details_TwP",
            "turn_details_last_TwPdeal",
            "turn_details_TwB",
            "turn_details_dcard",
        ):
            setattr(player, attr_name, [0, 0, 0, 0, 0, 0])

    def clear_all_player_turn_details(self) -> None:
        """Clear all player-level turn details at the start of each turn."""
        ledger = self._ensure_turn_event_ledger()
        if ledger is not None:
            try:
                ledger.start_turn(int(getattr(self, "round", 0)), int(getattr(self, "turn", 0)))
            except Exception:
                pass
        for player in self.players:
            self.clear_player_turn_details(player)

    def _resource_from_tile_type(self, tile_type: Any) -> Optional[ResourceCard]:
        """Map a board terrain name to the ResourceCard it produces.

        The board stores terrain names such as "Field" or "Mountain" while
        ResourceCard values are "Wheat" or "Ore". Comparing those directly
        silently prevents resource production, so production must use the
        terrain-to-resource mapping from core.constants.
        """
        resource = TERRAIN_TO_RESOURCE.get(str(tile_type))
        if resource is not None:
            return resource
        for candidate in ResourceCard:
            if str(tile_type) in (candidate.name, candidate.value, candidate.name.lower(), candidate.value.lower()):
                return candidate
        return None

    def _resource_vector_from_delta(self, resource_delta: Dict[Any, Any]) -> List[int]:
        """Return [Wheat, Ore, Wood, Brick, Sheep, Gold/unused] from a delta dict."""
        order = [ResourceCard.WHEAT, ResourceCard.ORE, ResourceCard.WOOD, ResourceCard.BRICK, ResourceCard.SHEEP]
        result = [0, 0, 0, 0, 0, 0]
        for index, resource in enumerate(order):
            try:
                result[index] = int(resource_delta.get(resource, resource_delta.get(resource.value, 0)) or 0)
            except Exception:
                result[index] = 0
        return result

    def _format_resource_vector_for_twitter(self, vector: List[int], *, absolute: bool = False) -> str:
        """Format a 6-slot resource vector for compact event-feed messages."""
        labels = [
            ("Wheat", 0),
            ("Ore", 1),
            ("Wood", 2),
            ("Brick", 3),
            ("Sheep", 4),
        ]
        parts: List[str] = []
        for label, index in labels:
            try:
                value = int(vector[index] or 0)
            except Exception:
                value = 0
            if value == 0:
                continue
            shown = abs(value) if absolute else value
            prefix = "+" if shown > 0 and not absolute else ""
            parts.append(f"{prefix}{shown} {label}")
        return ", ".join(parts) if parts else "no resources"

    def distribute_rcards(self, roll: int) -> Dict[str, Any]:
        """Distribute resource cards to players based on the dice roll.

        Returns a production summary used by the scoreboard, twitter pane, and
        v045-inspired green tile highlight animation.
        """
        try:
            roll = int(roll)
        except Exception:
            return {
                "roll": roll,
                "produced_by_player": {},
                "blocked_by_player": {},
                "producing_tile_ids": [],
                "blocked_tile_ids": [],
                "produced_total": 0,
                "blocked_total": 0,
            }

        intersections_by_id = {
            getattr(intersection, "id", None): intersection
            for intersection in getattr(self.board, "intersections", []) or []
            if intersection is not None
        }
        tiles_by_id = {
            getattr(tile, "id", None): tile
            for tile in getattr(self.board, "tiles", []) or []
            if tile is not None
        }

        produced_by_player: Dict[int, List[int]] = {}
        blocked_by_player: Dict[int, List[int]] = {}
        producing_tile_ids = set()
        blocked_tile_ids = set()
        produced_total = 0
        blocked_total = 0

        resource_order = [ResourceCard.WHEAT, ResourceCard.ORE, ResourceCard.WOOD, ResourceCard.BRICK, ResourceCard.SHEEP]

        for player in self.players:
            player_id = int(getattr(player, "id", 0) or 0)
            produced_by_player.setdefault(player_id, [0, 0, 0, 0, 0, 0])
            blocked_by_player.setdefault(player_id, [0, 0, 0, 0, 0, 0])

            city_ids = {int(x) for x in getattr(player, "cities", []) or []}
            settlement_ids = {int(x) for x in getattr(player, "settlements", []) or []}
            production_vertices = [(intersection_id, 2) for intersection_id in sorted(city_ids)]
            production_vertices.extend((intersection_id, 1) for intersection_id in sorted(settlement_ids - city_ids))

            for intersection_id, multiplier in production_vertices:
                intersection = intersections_by_id.get(intersection_id)
                if intersection is None:
                    continue

                for tile_id in getattr(intersection, "three_tile_ids", []) or []:
                    tile = tiles_by_id.get(tile_id)
                    if tile is None:
                        continue
                    if getattr(tile, "value", None) != roll:
                        continue

                    resource = self._resource_from_tile_type(getattr(tile, "type", None))
                    if resource is None:
                        continue

                    try:
                        resource_index = resource_order.index(resource)
                    except ValueError:
                        continue

                    tile_id_int = int(getattr(tile, "id", tile_id))
                    resource_delta = {resource: int(multiplier)}

                    # Robber-blocked tiles must not produce resources, but the
                    # missed production is useful turn-detail data.
                    if getattr(tile, "occupied_tf", False) or str(getattr(tile, "face", "")) == "Robber":
                        blocked_by_player[player_id][resource_index] -= int(multiplier)
                        blocked_total += int(multiplier)
                        blocked_tile_ids.add(tile_id_int)
                        self.record_turn_delta(
                            player,
                            "resource_production_robber",
                            resource=resource,
                            amount=-int(multiplier),
                            event_type="robber_blocked_production",
                            source="dice_roll",
                            reason=f"rolled {roll}; tile {tile_id_int} blocked by robber",
                            metadata={
                                "roll": roll,
                                "tile_id": tile_id_int,
                                "intersection_id": intersection_id,
                                "multiplier": int(multiplier),
                            },
                        )
                        continue

                    if hasattr(player, "add_rcard"):
                        player.add_rcard(resource, int(multiplier))
                    elif hasattr(player, "add_resource"):
                        player.add_resource(resource, int(multiplier))
                    else:
                        player.rcards[resource] = player.rcards.get(resource, 0) + int(multiplier)
                        player.number_of_rcards = sum(player.rcards.get(rc, 0) for rc in ResourceCard)

                    produced_by_player[player_id][resource_index] += int(multiplier)
                    produced_total += int(multiplier)
                    producing_tile_ids.add(tile_id_int)
                    self.record_turn_delta(
                        player,
                        "resource_production",
                        resource_delta=resource_delta,
                        event_type="resource_production",
                        source="dice_roll",
                        reason=f"rolled {roll}",
                        metadata={
                            "roll": roll,
                            "tile_id": tile_id_int,
                            "intersection_id": intersection_id,
                            "multiplier": int(multiplier),
                        },
                    )

        # Ensure the v045-compatible per-player vectors mirror the aggregate
        # production result immediately. This makes the scoreboard red row and
        # '?' detail panel show P3 +2 Wood even if a future edit temporarily
        # breaks ledger querying.
        for player in self.players:
            try:
                pid = int(getattr(player, "id", 0) or 0)
                player.turn_details_resource_production = list(produced_by_player.get(pid, [0, 0, 0, 0, 0, 0]))[:6]
                player.turn_details_resource_production_robber = list(blocked_by_player.get(pid, [0, 0, 0, 0, 0, 0]))[:6]
            except Exception:
                pass

        # Narrative feedback in the twitter/event pane, aggregated per player.
        for player in self.players:
            player_id = int(getattr(player, "id", 0) or 0)
            produced_vector = produced_by_player.get(player_id, [0, 0, 0, 0, 0, 0])
            blocked_vector = blocked_by_player.get(player_id, [0, 0, 0, 0, 0, 0])
            if any(produced_vector):
                self.emit_twitter_event(
                    player_id,
                    f"receives {self._format_resource_vector_for_twitter(produced_vector)}",
                )
            if any(blocked_vector):
                self.emit_twitter_event(
                    player_id,
                    f"robber blocks {self._format_resource_vector_for_twitter(blocked_vector, absolute=True)}",
                )

        return {
            "roll": roll,
            "produced_by_player": produced_by_player,
            "blocked_by_player": blocked_by_player,
            "producing_tile_ids": sorted(producing_tile_ids),
            "blocked_tile_ids": sorted(blocked_tile_ids),
            "produced_total": produced_total,
            "blocked_total": blocked_total,
        }

    def sync_round_turn(self) -> None:
        """Synchronize round and turn with Board.

        Args:
            None
        """
        self.board.round = self.round
        self.board.turn = self.turn

    def get_current_player(self) -> Optional[Player]:
        """
        Return the player whose turn it currently is.

        Keeps self.current_player synchronized with self.turn.
        """
        for player in self.players:
            if getattr(player, "id", None) == self.turn:
                self.current_player = player
                return player

        if self.players:
            index = max(0, min(len(self.players) - 1, int(self.turn or 1) - 1))
            self.current_player = self.players[index]
            return self.current_player

        self.current_player = None
        return None

    def execution_manager(self):
        """
        Lazy-load the ExecutionPhaseManager.

        This avoids importing execution_phase_manager.py at module import time,
        which reduces circular-import risk.
        """
        if self._execution_phase_manager is None:
            from core.execution_phase_manager import ExecutionPhaseManager
            self._execution_phase_manager = ExecutionPhaseManager(self)
        return self._execution_phase_manager

    def refresh_strategy_context(self, reason: str = "", *, force: bool = False) -> Dict[str, Any]:
        """Refresh and persist the current player's strategic direction.

        This is the live Execution bridge to core.action_planner.  The action
        planner is deliberately called by Game, not by the GUI and not by
        ExecutionPhaseManager:

        - Game owns the real player state and resource changes.
        - action_planner.py builds the strategic projection/preferred way.
        - ExecutionPhaseManager later reads player.strategic_direction and
          intersects it with the viable-action scan.

        The method is defensive: planner failures are reported to the debug
        panel but never break dice rolling or normal execution.
        """
        status: Dict[str, Any] = {
            "ok": False,
            "reason": reason or "refresh_strategy_context",
            "player_id": None,
            "preferred_way_id": None,
            "preference_level": "",
            "preference_reason": "",
            "supporting_action_type": "",
            "supporting_action_target_id": None,
            "error": "",
        }

        if str(getattr(self, "phase", "")) != "Execution":
            status["error"] = "not_execution_phase"
            self.last_strategy_context_status = status
            return status

        player = self.get_current_player()
        if player is None:
            status["error"] = "no_current_player"
            self.last_strategy_context_status = status
            return status

        # Call action planner
        planner = ActionPlanner(self)
        preferred = planner.get_best_action(player)

        # Phase 4G-A board audit hook
        try:
            board_audit = getattr(self, "current_board_way_audit", None)
            if board_audit:
                preferred["board_way_audit"] = board_audit.as_dict() if hasattr(board_audit, "as_dict") else board_audit
                preferred["board_way_audit_compact"] = format_audit_compact(board_audit)
        except Exception as e:
            preferred["board_way_audit_error"] = str(e)

        # Persist
        try:
            previous = getattr(player, "strategic_direction", None)
            setattr(player, "last_strategic_direction", previous)
            setattr(player, "strategic_direction", preferred)
            history = list(getattr(player, "strategic_direction_history", []) or [])
            history.append(preferred)
            setattr(player, "strategic_direction_history", history[-20:])
        except Exception as exc:
            status["error"] = f"persist_failed: {exc}"

        status.update({
            "ok": bool(preferred),
            "preferred_way_id": preferred.get("preferred_way_id", preferred.get("way_id")) if preferred else None,
            "preference_level": str(preferred.get("preference_level", "") if preferred else ""),
            "preference_reason": str(preferred.get("preference_reason", "") if preferred else ""),
            "supporting_action_type": str(preferred.get("supporting_action_type", "") if preferred else ""),
            "supporting_action_target_id": preferred.get("supporting_action_target_id") if preferred else None,
            "error": status.get("error", ""),
        })
        self.last_strategy_context_status = status
        return status

    def refresh_viable_actions(self, reason: str = ""):
        """
        Refresh current viable actions for the current execution state.

        Use this after every real mutation:
        - dice roll / resource production
        - robber movement / steal flow
        - bank trade / player trade
        - build road/settlement/city
        - buy/play development card
        """
        if self.phase != "Execution":
            return None

        self.get_current_player()
        self.last_rescan_reason = reason

        manager = self.execution_manager()
        scan = manager.refresh_viable_actions(reason=reason)

        try:
            self.current_viable_action_scan = scan.as_dict()
        except Exception:
            self.current_viable_action_scan = scan

        self.current_execution_choices = [
            choice.as_dict() for choice in getattr(manager, "current_choices", [])
        ]
        self.current_strategic_needs = list(getattr(manager, "current_strategic_needs", []) or [])
        self.current_actionable_choices = [
            choice.as_dict() for choice in getattr(manager, "current_actionable_choices", [])
        ]
        self.last_execution_scan_report = dict(getattr(manager, "last_report", {}) or {})

        # Freeze the exact BEST NOW action immediately after the scanner refresh.
        # The panel displays this object and AI Continue executes this object.
        # Do not select a different candidate later at click time.
        try:
            self.current_best_now_action = self._compute_current_best_executable_action()
            if isinstance(self.last_execution_scan_report, dict):
                self.last_execution_scan_report["canonical_best_now_action"] = dict(self.current_best_now_action or {})
        except Exception as exc:
            self.current_best_now_action = None
            if isinstance(self.last_execution_scan_report, dict):
                self.last_execution_scan_report["canonical_best_now_error"] = str(exc)

        return scan

    def begin_execution_turn(self):
        """
        Start or restart the current player's Execution turn.

        At this point the player must roll dice unless a forced action already exists.
        """
        if self.phase != "Execution":
            return None

        self.get_current_player()
        self.clear_all_player_turn_details()
        self.state = "AwaitingDiceRoll"
        self.state_1 = ""
        self.state_2 = ""
        self.dice_roll = None
        self.pending_seven_roll = {"active": False}
        self.pending_robber_steal = {"active": False}
        self.last_7_result = None
        self.last_robber_plan = None
        self.last_robber_move_result = None
        self.last_robber_steal_selection = None
        self.last_robber_steal_result = None

        # New execution turn: Play must roll dice first, then Continue becomes
        # available for AI players after the roll.  Also reset the GUI button
        # registry so stale Continue/End states cannot leak across turn changes.
        self.ai_execution_preview_ready = False
        self.ai_execution_preview_player_id = getattr(self.current_player, "id", None) if self.current_player is not None else None
        self.ai_execution_stage = "awaiting_dice"
        self.current_ai_execution_plan = []
        self.current_ai_decision_trace = []
        self.last_ai_preview_result = None
        self.last_ai_continue_result = None
        try:
            if self.gui is not None:
                self.gui.set_button("continue_ai", False)
                self.gui.set_button("end_turn", False)
                self.gui.set_button("cancel", False)
                self.gui.set_button("next_turn2", True)
        except Exception:
            pass

        try:
            self.myturn.clear_turn_details()
            self.myturn.round = self.round
            self.myturn.turn = self.turn
            self.myturn.dice_roll = 0
        except Exception:
            pass

        return self.refresh_viable_actions("begin_execution_turn")

    def emit_twitter_event(self, player_id: Optional[int], message: str, *, update: bool = True) -> None:
        """Emit one top-right event-feed message if a GUI is attached.

        This is intentionally tiny and defensive: game logic must keep running
        in tests / no-GUI mode even if the visual feed is unavailable.
        """
        gui = getattr(self, "gui", None)
        if gui is None:
            return

        try:
            if hasattr(gui, "add_tweet"):
                try:
                    gui.add_tweet(player_id, message, update=update)
                except TypeError:
                    gui.add_tweet(player_id, message)
            else:
                if not hasattr(gui, "twitter") or not isinstance(getattr(gui, "twitter", None), list):
                    gui.twitter = []
                gui.twitter.append([player_id, message])
                if update and hasattr(gui, "update_twitter"):
                    gui.update_twitter()
        except Exception:
            # Event feed is visual/logging only; never break game logic.
            pass

    def emit_dice_roll_twitter_event(self, player: Optional[Player], dice: Tuple[int, int], total: int) -> None:
        """Show the execution dice roll in the v045-inspired twitter pane."""
        player_id = getattr(player, "id", None)
        try:
            d1, d2 = int(dice[0]), int(dice[1])
            message = f"rolled {d1} + {d2} = {int(total)}"
        except Exception:
            message = f"rolled {int(total)}"
        self.emit_twitter_event(player_id, message)

    def execute_roll_dice_action(self) -> Dict[str, Any]:
        """
        Execute the Roll Dices action during the Execution phase.

        If total != 7:
            distribute resources and rescan normal action candidates.

        If total == 7:
            delegate basic 7-flow setup to game_7logic.py, skip production,
            force Move robber, and rescan.
        """
        if self.phase != "Execution":
            raise RuntimeError("Cannot roll execution dice outside the Execution phase.")

        player = self.get_current_player()
        dice = self.roll_dice()
        total = int(sum(dice))

        self.dice_roll = dice
        self.dice_rolls.append(dice)

        if 0 <= total < len(self.dice_roll_history):
            self.dice_roll_history[total] += 1

        try:
            self.myturn.dice_roll = total
        except Exception:
            pass

        self.emit_dice_roll_twitter_event(player, dice, total)
        self.record_turn_event(
            player=player,
            event_type="dice_roll",
            source="dice",
            message=f"rolled {int(dice[0])} + {int(dice[1])} = {total}",
            metadata={"dice": [int(dice[0]), int(dice[1])], "total": total},
        )

        production_result = None

        if total == 7:
            from core.game_7logic import handle_roll_seven_no_discard

            seven_result = handle_roll_seven_no_discard(self, player)
            self.last_7_result = seven_result
            resources_produced = False
        else:
            production_result = self.distribute_rcards(total)
            self.last_resource_production_result = production_result
            self.state = "ActionSelection"
            self.state_1 = ""
            self.state_2 = ""
            self.pending_seven_roll = {"active": False}
            self.pending_robber_steal = {"active": False}
            resources_produced = bool((production_result or {}).get("produced_total", 0))
            seven_result = None

            for p in self.players:
                self.update_strategy_dashboard(p)

        # Refresh the strategic direction after the dice/resources are known and
        # before Slice A/B interprets strategy needs.  On a 7, publish an
        # explicit "paused for robber" planner status instead; the real planner
        # refresh runs after Continue resolves the robber/steal.
        if total != 7:
            self.refresh_strategy_context("after_dice_roll", force=True)
        else:
            self.refresh_strategy_context("after_dice_roll_forced_robber", force=True)

        scan = self.refresh_viable_actions("execute_roll_dice_action")

        # If this roll belongs to an AI player, the AI turn has reached the
        # visible preview checkpoint.  Continue must be available even when the
        # scanner found no legal buy/build action.
        if not self._is_current_player_human_for_execution():
            self._mark_ai_preview_ready(reason="execute_roll_dice_action")

        result = {
            "action": "Roll Dices",
            "player_id": getattr(player, "id", None),
            "dice": dice,
            "total": total,
            "resources_produced": resources_produced,
            "production": production_result,
            "producing_tile_ids": (production_result or {}).get("producing_tile_ids", []),
            "blocked_tile_ids": (production_result or {}).get("blocked_tile_ids", []),
            "seven_result": seven_result,
            "state_after": self.state,
            "viable_actions_after": scan.viable_actions() if scan is not None and hasattr(scan, "viable_actions") else [],
            "buy_build_choices_after": list(self.current_execution_choices or []),
            "strategic_needs_after": list(self.current_strategic_needs or []),
            "actionable_choices_after": list(self.current_actionable_choices or []),
            "slice_ab_note": "Slice A/B preview checkpoint: Continue will consume/pass this AI turn.",
            "ai_execution_preview_ready": bool(getattr(self, "ai_execution_preview_ready", False)),
            "current_ai_execution_plan": list(getattr(self, "current_ai_execution_plan", []) or []),
        }

        self.last_execution_result = result
        return result

    # ──────────────────────────────────────────────────────────────
    # AI two-click Execution flow
    # ──────────────────────────────────────────────────────────────

    def _dice_has_been_rolled_for_execution(self) -> bool:
        """Return True once the current Execution turn has a dice value."""
        dice_roll = getattr(self, "dice_roll", None)
        if dice_roll in (None, 0, "", []):
            return False
        if isinstance(dice_roll, (list, tuple)):
            return len(dice_roll) > 0
        try:
            return int(dice_roll) > 0
        except Exception:
            return True

    def _normalised_human_player_ids_for_execution(self) -> List[int]:
        """Return configured human player ids as a flat list of ints.

        HP_ID may be configured either as one integer, e.g. 3, or as a
        collection, e.g. [3].  Game-side AI helpers must support both forms;
        otherwise a human player can be misclassified as AI after advance_turn().
        """
        raw_ids = HP_ID
        if isinstance(raw_ids, (list, tuple, set)):
            values = list(raw_ids)
        elif raw_ids in (None, ""):
            values = []
        else:
            values = [raw_ids]

        result: List[int] = []
        for value in values:
            try:
                result.append(int(value))
            except (TypeError, ValueError):
                pass
        return result

    def _is_current_player_human_for_execution(self) -> bool:
        """Best-effort human/AI check for the current player."""
        player = self.get_current_player()
        if player is None:
            return False

        try:
            if bool(getattr(player, "is_human", False)):
                return True
        except Exception:
            pass

        if not HUMAN_PLAYER:
            return False

        try:
            player_id = int(getattr(player, "id", 0) or 0)
        except Exception:
            player_id = 0

        return player_id in self._normalised_human_player_ids_for_execution()

    def ai_continue_is_available(self) -> bool:
        """Return True when an AI player may press Continue.

        This is intentionally independent from viable buy/build actions. No
        viable actions simply means Continue will pass and advance the turn.

        Important turn-boundary rule:
            AwaitingDiceRoll always means Continue is unavailable. This prevents
            a stale Continue button from leaking from the previous AI turn into
            the next player's fresh turn.
        """
        if str(getattr(self, "phase", "")) != "Execution":
            return False
        if self._is_current_player_human_for_execution():
            return False
        if str(getattr(self, "state", "") or "") == "AwaitingDiceRoll":
            return False
        return self._dice_has_been_rolled_for_execution()

    def _format_ai_plan_label(self, choice: Dict[str, Any]) -> str:
        action = str(choice.get("action", "") or "")
        candidates = list(choice.get("candidates", []) or [])
        target = None
        if candidates and isinstance(candidates[0], dict):
            target = candidates[0].get("target_id") or candidates[0].get("intersection_id") or candidates[0].get("road_id")
        if action == "Build city":
            return f"City @{target}" if target is not None else "City"
        if action == "Build settlement":
            return f"Settle @{target}" if target is not None else "Settlement"
        if action == "Build road":
            return f"Road {target}" if target is not None else "Road"
        if action == "Buy development_card":
            return "DCard"
        if action == "TwB":
            give = choice.get("give") or choice.get("give_vector") or []
            get = choice.get("get") or choice.get("get_vector") or []
            try:
                names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]
                return f"TwB {self._format_twb_amounts(give, names)} -> {self._format_twb_amounts(get, names)}"
            except Exception:
                return "TwB"
        if action == "TwP":
            proposal = choice.get("proposal") or choice.get("twp_proposal") or choice.get("candidate") or {}
            if isinstance(proposal, Mapping):
                return str(proposal.get("legacy_short_text") or proposal.get("description") or "TwP")
            return "TwP"
        return action or "Action"

    def _build_ai_continue_plan(self) -> List[Dict[str, Any]]:
        """Build the AI Continue plan for the current post-dice checkpoint.

        Selection order for Slice C2:
            1. Use legal actions that are also strategic/actionable.
            2. If no strategic action is available, fall back to the first legal
               buy/build action.  This prevents an AI from passing while it has
               enough cards simply because player.strategic_direction is empty.
            3. If no legal buy/build action exists, pass/end turn.
        """
        plan: List[Dict[str, Any]] = []

        state = str(getattr(self, "state", "") or "")
        pending_7 = getattr(self, "pending_seven_roll", {}) or {}
        if state in {"MoveRobber", "RobberMoveRequired", "SetRobber", "StealSelectOpponent"} or (isinstance(pending_7, dict) and pending_7.get("active")):
            return [{
                "step": 1,
                "action": "Resolve robber",
                "label": "Resolve robber / steal",
                "status": "ready",
                "reason": "Dice total 7 forces robber handling before normal actions.",
                "source": "forced",
            }]

        priority = {"Build city": 1, "Build settlement": 2, "Build road": 3, "Buy development_card": 4}

        actionable = [
            c for c in list(getattr(self, "current_actionable_choices", []) or [])
            if isinstance(c, dict) and bool(c.get("actionable", c.get("viable", False)))
        ]
        legal = [
            c for c in list(getattr(self, "current_execution_choices", []) or [])
            if isinstance(c, dict) and bool(c.get("viable", False))
        ]

        # Road strategy guard: an AI may not use the generic "first legal road"
        # fallback.  Build-road remains selectable only when it is the next road
        # on a validated route toward a strategy-approved new settlement.
        actionable = [c for c in actionable if not self._should_suppress_ai_strategic_road_choice(c)]
        legal = [c for c in legal if not self._should_suppress_ai_strategic_road_choice(c)]

        action_keys = {str(c.get("action", "") or "") for c in actionable}
        fallback_legal = [c for c in legal if str(c.get("action", "") or "") not in action_keys]

        selected: List[Dict[str, Any]] = []
        for c in sorted(actionable, key=lambda row: priority.get(str(row.get("action", "") or ""), 99)):
            selected.append((dict(c) | {"_execution_source": "strategic"}))
        if not selected:
            for c in sorted(fallback_legal, key=lambda row: priority.get(str(row.get("action", "") or ""), 99)):
                selected.append((dict(c) | {"_execution_source": "legal_fallback"}))

        for idx, choice in enumerate(selected[:3], start=1):
            source = str(choice.get("_execution_source", "strategic") or "strategic")
            if source == "legal_fallback":
                reason = "Legal now; no strategic action was available, so Slice C2 uses legal fallback."
            else:
                reason = str(choice.get("strategic_reason") or choice.get("reason") or "Strategic and legal now.")
            choice = dict(choice)
            choice["reason"] = reason
            plan.append(self._plan_item_from_execution_choice(choice, source=source, step=idx))

        if not plan:
            twp_plan = self._plan_ai_trade_with_player_for_strategy(step=1)
            if isinstance(twp_plan, Mapping) and twp_plan.get("action"):
                plan.append(dict(twp_plan))
            else:
                twb_plan = self._plan_ai_trade_with_bank_for_strategy(step=1)
                if isinstance(twb_plan, Mapping) and twb_plan.get("action"):
                    plan.append(dict(twb_plan))
                else:
                    plan.append({
                        "step": 1,
                        "action": "End turn",
                        "label": "Pass / End turn",
                        "status": "ready",
                        "reason": self._ai_pass_reason_after_strategy_lock(),
                        "source": "pass",
                    })
        return plan

    def _mark_ai_preview_ready(self, reason: str = "") -> None:
        """Mark the current AI turn as being at the Continue checkpoint."""
        player = self.get_current_player()
        self.ai_execution_preview_ready = True
        self.ai_execution_preview_player_id = getattr(player, "id", None) if player is not None else None
        self.ai_execution_stage = "preview_ready"
        self.current_ai_execution_plan = self._build_ai_continue_plan()
        self.current_ai_decision_trace = []

    def ai_roll_to_preview(self) -> Dict[str, Any]:
        """AI Play step: roll dice once, refresh scanners, and stop before Continue."""
        if str(getattr(self, "phase", "")) != "Execution":
            return {"ok": False, "reason": "not_execution_phase"}
        if self._is_current_player_human_for_execution():
            return {"ok": False, "reason": "current_player_is_human"}

        if self._dice_has_been_rolled_for_execution():
            roll_result = dict(getattr(self, "last_execution_result", {}) or {})
            try:
                self.refresh_strategy_context("ai_roll_to_preview_already_rolled", force=True)
                self.refresh_viable_actions("ai_roll_to_preview_already_rolled")
            except Exception:
                pass
        else:
            roll_result = self.execute_roll_dice_action()

        self._mark_ai_preview_ready(reason="ai_roll_to_preview")
        result = {
            "ok": True,
            "action": "ai_roll_to_preview",
            "player_id": getattr(self.get_current_player(), "id", None),
            "roll_result": roll_result,
            "continue_available": self.ai_continue_is_available(),
            "current_ai_execution_plan": list(getattr(self, "current_ai_execution_plan", []) or []),
        }
        self.last_ai_preview_result = result
        self.last_execution_result = result
        return result

    def _clean_trade_rates_vector(self, rates: Any = None) -> List[int]:
        """Return trade rates in fixed [Wheat, Ore, Wood, Brick, Sheep] order."""
        if isinstance(rates, (list, tuple)):
            clean: List[int] = []
            for value in list(rates)[:5]:
                try:
                    rate = int(value or 4)
                except Exception:
                    rate = 4
                clean.append(rate if rate > 0 else 4)
            while len(clean) < 5:
                clean.append(4)
            return clean

        if isinstance(rates, dict):
            aliases = [
                (ResourceCard.WHEAT, "Wheat", "wheat", "grain"),
                (ResourceCard.ORE, "Ore", "ore"),
                (ResourceCard.WOOD, "Wood", "wood", "lumber"),
                (ResourceCard.BRICK, "Brick", "brick"),
                (ResourceCard.SHEEP, "Sheep", "sheep", "wool"),
            ]
            out: List[int] = []
            for keys in aliases:
                value = None
                for key in keys:
                    if key in rates:
                        value = rates[key]
                        break
                if value is None:
                    key_texts = {str(getattr(k, "value", k)).strip().lower() for k in keys}
                    key_texts.update({str(getattr(k, "name", k)).strip().lower() for k in keys})
                    for raw_key, raw_value in rates.items():
                        raw_text = str(getattr(raw_key, "value", raw_key)).strip().lower()
                        raw_name = str(getattr(raw_key, "name", raw_key)).strip().lower()
                        if raw_text in key_texts or raw_name in key_texts:
                            value = raw_value
                            break
                try:
                    rate = int(value or 4)
                except Exception:
                    rate = 4
                out.append(rate if rate > 0 else 4)
            return out

        return [4, 4, 4, 4, 4]

    def get_player_bank_trade_rates(self, player: Optional[Player]) -> List[int]:
        """Return current bank/port trade rates from the player's actual ports.

        Source of truth is the player's owned settlements/cities on the board.
        The runtime representation is [Wheat, Ore, Wood, Brick, Sheep].
        """
        if player is None:
            return [4, 4, 4, 4, 4]

        # Refresh from board when possible so TwB execution cannot use stale port
        # data after a settlement was built/loaded.
        try:
            player.update_trade_rates(self.board)
        except Exception:
            pass

        rates = getattr(player, "trade_rates", None)
        clean = self._clean_trade_rates_vector(rates)
        try:
            player.trade_rates = list(clean)
        except Exception:
            pass
        return clean

    def _trade_rates_for_player(self, player: Player) -> List[int]:
        """Backward-compatible wrapper used by existing TwB and scanner code."""
        return self.get_player_bank_trade_rates(player)

    def _normalize_twb_vector(self, values: Any) -> List[int]:
        """Return a clean 5-item non-negative TwB vector."""
        clean: List[int] = []
        try:
            iterable = list(values or [])
        except Exception:
            iterable = []
        for value in iterable[:5]:
            try:
                clean.append(max(0, int(value or 0)))
            except Exception:
                clean.append(0)
        while len(clean) < 5:
            clean.append(0)
        return clean

    def _format_twb_amounts(self, amounts: Sequence[int], names: Sequence[str]) -> str:
        """Format a TwB vector as compact human text."""
        parts: List[str] = []
        for amount, name in zip(list(amounts)[:5], list(names)[:5]):
            try:
                value = int(amount or 0)
            except Exception:
                value = 0
            if value > 0:
                parts.append(f"{value} {name}")
        return ", ".join(parts) if parts else "0"

    def continue_action_selection_after_action(
        self,
        reason: str,
        *,
        player: Optional[Player] = None,
        action_result: Optional[Dict[str, Any]] = None,
        clear_forced_locks: bool = True,
    ) -> Dict[str, Any]:
        """Slice D: keep the same player in ActionSelection after one action.

        This is the canonical same-turn continuation step.  Any successful
        Execution mutation (TwB, buy/build, robber/steal resolution, and later
        development-card play) makes the old scanner rows and BEST NOW object
        stale.  Slice D normalizes the state, refreshes strategy context,
        refreshes viable-action scanner output, recomputes BEST NOW, and then
        leaves the turn on the same player.  It never calls advance_turn().
        """
        reason_text = str(reason or "after_action")
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None

        result: Dict[str, Any] = {
            "ok": False,
            "action": "Slice D continuation",
            "reason": reason_text,
            "player_id": getattr(player, "id", None) if player is not None else None,
            "state_before": str(getattr(self, "state", "") or ""),
        }
        if action_result is not None:
            try:
                result["action_result"] = dict(action_result)
            except Exception:
                result["action_result"] = action_result

        if str(getattr(self, "phase", "")) != "Execution":
            result["reason"] = "not_execution_phase"
            self.last_slice_d_result = result
            return result

        # A completed action returns to normal action selection for the same
        # player.  Robber-flow locks may legitimately exist while the robber is
        # unresolved, so callers can opt out, but all completed actions opt in.
        try:
            self.state = "ActionSelection"
            self.state_1 = ""
            self.state_2 = ""
        except Exception:
            pass

        if clear_forced_locks:
            try:
                if isinstance(getattr(self, "pending_seven_roll", None), dict):
                    self.pending_seven_roll["active"] = False
                else:
                    self.pending_seven_roll = {"active": False}
            except Exception:
                self.pending_seven_roll = {"active": False}

            try:
                if isinstance(getattr(self, "pending_robber_steal", None), dict):
                    self.pending_robber_steal["active"] = False
                    self.pending_robber_steal["awaiting_human_target"] = False
                else:
                    self.pending_robber_steal = {"active": False, "awaiting_human_target": False}
            except Exception:
                self.pending_robber_steal = {"active": False, "awaiting_human_target": False}

        try:
            if player is not None:
                player.update_trade_rates(self.board)
        except Exception:
            pass

        try:
            for p in list(getattr(self, "players", []) or []):
                self.update_strategy_dashboard(p)
        except Exception:
            pass

        strategy_ok = True
        strategy_error = ""
        try:
            self.refresh_strategy_context(reason_text, force=True)
        except Exception as exc:
            strategy_ok = False
            strategy_error = str(exc)

        scan = None
        scan_ok = True
        scan_error = ""
        try:
            scan = self.refresh_viable_actions(reason_text)
        except Exception as exc:
            scan_ok = False
            scan_error = str(exc)

        try:
            viable_actions = scan.viable_actions() if scan is not None and hasattr(scan, "viable_actions") else []
        except Exception:
            viable_actions = []

        best_now = None
        try:
            best_now = self.get_current_best_executable_action()
        except Exception:
            best_now = None

        is_human = False
        try:
            is_human = bool(self._is_current_player_human_for_execution())
        except Exception:
            is_human = bool(getattr(player, "is_human", False)) if player is not None else False

        if is_human:
            try:
                self.ai_execution_preview_ready = False
                self.ai_execution_preview_player_id = None
                self.ai_execution_stage = "human_action_selection"
                self.current_ai_execution_plan = []
                self.current_ai_decision_trace = []
            except Exception:
                pass
        else:
            try:
                self._mark_ai_preview_ready(reason=reason_text)
            except Exception:
                try:
                    self.ai_execution_preview_ready = True
                    self.ai_execution_preview_player_id = getattr(player, "id", None) if player is not None else None
                    self.ai_execution_stage = "preview_ready"
                    self.current_ai_execution_plan = self._build_ai_continue_plan()
                except Exception:
                    pass

        result.update({
            "ok": True,
            "state_after": str(getattr(self, "state", "") or ""),
            "same_turn": True,
            "advanced_turn": False,
            "is_human_turn": is_human,
            "pending_seven_active": bool((getattr(self, "pending_seven_roll", {}) or {}).get("active")),
            "pending_steal_active": bool((getattr(self, "pending_robber_steal", {}) or {}).get("active")),
            "strategy_refresh_ok": strategy_ok,
            "strategy_refresh_error": strategy_error,
            "scan_refresh_ok": scan_ok,
            "scan_refresh_error": scan_error,
            "viable_actions_after": viable_actions,
            "buy_build_choices_after": list(getattr(self, "current_execution_choices", []) or []),
            "actionable_choices_after": list(getattr(self, "current_actionable_choices", []) or []),
            "current_best_now_action": dict(best_now) if isinstance(best_now, Mapping) else best_now,
            "current_ai_execution_plan": list(getattr(self, "current_ai_execution_plan", []) or []),
        })
        self.last_slice_d_result = result
        return result

    def execute_trade_with_bank_vector_action(
        self,
        give: Sequence[int],
        get: Sequence[int],
        *,
        source: str = "human_twb_panel",
        reason: str = "human_trade_with_bank",
    ) -> Dict[str, Any]:
        """Execute one or more Trade-with-Bank exchanges.

        ``give`` and ``get`` are 5-item vectors in execution resource order:
        Wheat, Ore, Wood, Brick, Sheep.

        Examples:
            give=[8,0,0,0,0], get=[0,1,0,1,0]
                -> 8 Wheat for 1 Ore + 1 Brick, if Wheat trades at 4:1.

            give=[0,0,0,2,0], get=[1,0,0,0,0]
                -> 2 Brick for 1 Wheat, if Brick trades at 2:1.
        """
        player = self.get_current_player()
        give_vec = self._normalize_twb_vector(give)
        get_vec = self._normalize_twb_vector(get)
        result: Dict[str, Any] = {
            "ok": False,
            "action": "Trade with Bank",
            "give": give_vec,
            "get": get_vec,
            "reason": "",
        }

        if str(getattr(self, "phase", "")) != "Execution":
            result["reason"] = "not_execution_phase"
            return result
        if str(getattr(self, "state", "")) != "ActionSelection":
            result["reason"] = f"state_not_action_selection:{getattr(self, 'state', '')}"
            return result
        if player is None:
            result["reason"] = "no_current_player"
            return result

        resources = self._execution_resource_order()
        rates = self._trade_rates_for_player(player)
        names = [self._resource_name_for_turn_delta(resource) for resource in resources[:5]]

        give_units = 0
        get_units = sum(int(x or 0) for x in get_vec)
        for idx in range(5):
            rate = max(1, int(rates[idx] or 4))
            available = int(player.rcards.get(resources[idx], 0) or 0)
            give_amount = int(give_vec[idx] or 0)
            get_amount = int(get_vec[idx] or 0)

            if give_amount < 0 or get_amount < 0:
                result["reason"] = "negative_twb_amount"
                return result
            if give_amount > available:
                result.update({
                    "reason": f"not_enough_{names[idx]}",
                    "resource": names[idx],
                    "available": available,
                    "requested": give_amount,
                })
                self.emit_twitter_event(
                    getattr(player, "id", None),
                    f"DBG: TwB rejected; need {give_amount} {names[idx]}, have {available}.",
                )
                return result
            if give_amount % rate != 0:
                result.update({
                    "reason": f"give_not_multiple_of_rate_{names[idx]}",
                    "resource": names[idx],
                    "rate": rate,
                    "requested": give_amount,
                })
                return result
            if give_amount > 0 and get_amount > 0:
                result.update({
                    "reason": f"same_resource_in_give_and_get_{names[idx]}",
                    "resource": names[idx],
                })
                return result
            give_units += give_amount // rate

        if give_units <= 0:
            result["reason"] = "no_give_cards_selected"
            return result
        if get_units <= 0:
            result["reason"] = "no_get_cards_selected"
            return result
        if give_units != get_units:
            result.update({
                "reason": "give_get_balance_invalid",
                "give_units": give_units,
                "get_units": get_units,
            })
            self.emit_twitter_event(
                getattr(player, "id", None),
                f"DBG: TwB rejected; give/get balance invalid ({give_units}:{get_units}).",
            )
            return result

        # Apply all deductions first, then all additions.  Validation above has
        # already guaranteed this cannot make any resource count negative.
        for idx, resource in enumerate(resources[:5]):
            player.rcards[resource] = int(player.rcards.get(resource, 0) or 0) - int(give_vec[idx] or 0)
        for idx, resource in enumerate(resources[:5]):
            player.rcards[resource] = int(player.rcards.get(resource, 0) or 0) + int(get_vec[idx] or 0)

        try:
            player.number_of_rcards = sum(int(player.rcards.get(rc, 0) or 0) for rc in ResourceCard)
        except Exception:
            pass

        delta: Dict[str, int] = {}
        for idx, name in enumerate(names):
            amount = int(get_vec[idx] or 0) - int(give_vec[idx] or 0)
            if amount:
                delta[name] = amount

        give_text = self._format_twb_amounts(give_vec, names)
        get_text = self._format_twb_amounts(get_vec, names)
        message = f"TwB {give_text} -> {get_text}"
        self.record_turn_delta(
            player,
            "TwB",
            resource_delta=delta,
            event_type="trade_with_bank",
            source=str(source or "human_twb_panel"),
            reason=str(reason or "human_trade_with_bank"),
            message=message,
            metadata={
                "give": list(give_vec),
                "get": list(get_vec),
                "trade_rates": list(rates[:5]),
                "give_units": give_units,
                "get_units": get_units,
            },
        )
        self.emit_twitter_event(getattr(player, "id", None), message)
        self._play_execution_action_sound("TwB")

        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass

        result.update({
            "ok": True,
            "reason": "executed",
            "give_units": give_units,
            "get_units": get_units,
            "resource_delta": delta,
            "message": message,
        })
        try:
            result["slice_d"] = self.continue_action_selection_after_action(
                "after_trade_with_bank",
                player=player,
                action_result=result,
            )
        except Exception as exc:
            result["slice_d"] = {"ok": False, "reason": str(exc)}
        self.last_execution_result = result
        return result


    def find_human_twp_responder_options(
        self,
        *,
        offer_exact: Sequence[int],
        offer_wildcard_count: int = 0,
        offer_wildcard_allowed: Optional[Sequence[Any]] = None,
        request_exact: Sequence[int],
        request_wildcard_count: int = 0,
        request_wildcard_allowed: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        """Return concrete AI opponent options for the Human TwP panel.

        This is a thin orchestration wrapper.  Processing/wildcard expansion lives
        in ``core.player_trade`` where the TwP logic already resides.
        """
        player = self.get_current_player()
        result: Dict[str, Any] = {
            "ok": False,
            "action": "TwP",
            "reason": "",
            "options": [],
        }
        if str(getattr(self, "phase", "")) != "Execution":
            result["reason"] = "not_execution_phase"
            return result
        if str(getattr(self, "state", "")) != "ActionSelection":
            result["reason"] = f"state_not_action_selection:{getattr(self, 'state', '')}"
            return result
        if player is None:
            result["reason"] = "no_current_player"
            return result
        try:
            from core.player_trade import find_human_twp_responder_options as _find_human_twp_options
        except Exception as exc:
            result["reason"] = f"player_trade_import_failed:{exc}"
            return result
        try:
            found = _find_human_twp_options(
                self,
                proposer_id=getattr(player, "id", None),
                offer_exact=offer_exact,
                offer_wildcard_count=offer_wildcard_count,
                offer_wildcard_allowed=offer_wildcard_allowed,
                request_exact=request_exact,
                request_wildcard_count=request_wildcard_count,
                request_wildcard_allowed=request_wildcard_allowed,
                include_human_counterparties=False,  # Layer 4C deliberately deferred.
            )
        except Exception as exc:
            result["reason"] = f"twp_option_scan_failed:{exc}"
            return result
        if isinstance(found, Mapping):
            result.update(dict(found))
            result.setdefault("action", "TwP")
            return result
        result["reason"] = "invalid_twp_option_scan_result"
        return result

    def execute_human_twp_selected_option(self, option: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute one concrete TwP option after the human presses OKY."""
        result: Dict[str, Any] = {
            "ok": False,
            "action": "TwP",
            "reason": "",
        }
        if str(getattr(self, "phase", "")) != "Execution":
            result["reason"] = "not_execution_phase"
            return result
        if str(getattr(self, "state", "")) != "ActionSelection":
            result["reason"] = f"state_not_action_selection:{getattr(self, 'state', '')}"
            return result
        if not isinstance(option, Mapping):
            result["reason"] = "invalid_twp_option"
            return result
        try:
            from core.player_trade import execute_human_twp_vector_trade
        except Exception as exc:
            result["reason"] = f"player_trade_import_failed:{exc}"
            return result
        try:
            executed = execute_human_twp_vector_trade(
                self,
                proposer_id=int(option.get("proposer_id", option.get("active_player_id", getattr(self.get_current_player(), "id", 0))) or 0),
                counterparty_id=int(option.get("counterparty_id", 0) or 0),
                proposer_gives=list(option.get("proposer_gives", option.get("human_gives", [0, 0, 0, 0, 0])) or [0, 0, 0, 0, 0]),
                counterparty_gives=list(option.get("counterparty_gives", option.get("human_receives", [0, 0, 0, 0, 0])) or [0, 0, 0, 0, 0]),
                source="human_twp_panel",
                reason="human_trade_with_player",
            )
        except Exception as exc:
            result["reason"] = f"twp_execute_failed:{exc}"
            return result
        if isinstance(executed, Mapping):
            result.update(dict(executed))
        if bool(result.get("ok")):
            try:
                self.emit_twitter_event(result.get("proposer_id"), str(result.get("message") or "TwP executed"))
            except Exception:
                pass
            try:
                player = self.get_current_player()
                if player is not None:
                    self.update_strategy_dashboard(player)
            except Exception:
                pass
            try:
                player = self.get_current_player()
                result["slice_d"] = self.continue_action_selection_after_action(
                    "after_trade_with_player",
                    player=player,
                    action_result=result,
                )
            except Exception as exc:
                result["slice_d"] = {"ok": False, "reason": str(exc)}
            self.last_execution_result = result
        return result

    def execute_trade_with_bank_action(self, give_index: int, get_index: int) -> Dict[str, Any]:
        """Backward-compatible wrapper for a single TwB exchange."""
        try:
            give_index = int(give_index)
            get_index = int(get_index)
        except Exception:
            return {
                "ok": False,
                "action": "Trade with Bank",
                "reason": "invalid_resource_index",
                "give_index": give_index,
                "get_index": get_index,
            }
        if give_index not in range(5) or get_index not in range(5):
            return {
                "ok": False,
                "action": "Trade with Bank",
                "reason": "resource_index_out_of_range",
                "give_index": give_index,
                "get_index": get_index,
            }
        player = self.get_current_player()
        rates = self._trade_rates_for_player(player) if player is not None else [4, 4, 4, 4, 4]
        give = [0, 0, 0, 0, 0]
        get = [0, 0, 0, 0, 0]
        give[give_index] = max(1, int(rates[give_index] or 4))
        get[get_index] = 1
        result = self.execute_trade_with_bank_vector_action(give, get)
        result["give_index"] = give_index
        result["get_index"] = get_index
        return result

    def _execution_resource_order(self) -> List[ResourceCard]:
        """Return the resource order used by scanner cost vectors."""
        return [
            ResourceCard.WHEAT,
            ResourceCard.ORE,
            ResourceCard.WOOD,
            ResourceCard.BRICK,
            ResourceCard.SHEEP,
        ]

    def _execution_cost_vector_for_action(self, action: str) -> List[int]:
        """Return the buy/build cost vector in Wheat/Ore/Wood/Brick/Sheep order."""
        if action == "Build city":
            return [2, 3, 0, 0, 0]
        if action == "Build settlement":
            return [1, 0, 1, 1, 1]
        if action == "Build road":
            return [0, 0, 1, 1, 0]
        if action == "Buy development_card":
            return [1, 1, 0, 0, 1]
        return [0, 0, 0, 0, 0]

    def _can_player_pay_execution_cost(self, player: Player, cost: Sequence[int]) -> bool:
        """Return True if player has the cards for cost right now."""
        for resource, needed in zip(self._execution_resource_order(), list(cost or [])):
            try:
                if int(player.rcards.get(resource, 0) or 0) < int(needed or 0):
                    return False
            except Exception:
                return False
        return True

    def _resource_delta_from_cost(self, cost: Sequence[int]) -> Dict[str, int]:
        """Convert a positive cost vector into a negative turn-detail delta."""
        delta: Dict[str, int] = {}
        for resource, needed in zip(self._execution_resource_order(), list(cost or [])):
            amount = int(needed or 0)
            if amount:
                delta[self._resource_name_for_turn_delta(resource)] = -amount
        return delta

    def _deduct_execution_cost(
        self,
        player: Player,
        cost: Sequence[int],
        *,
        category: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "ai_continue",
        reason: str = "slice_c2_execute_one_legal_action",
    ) -> None:
        """Deduct cards and record the visible red turn-detail delta."""
        for resource, needed in zip(self._execution_resource_order(), list(cost or [])):
            amount = int(needed or 0)
            if amount:
                player.rcards[resource] = int(player.rcards.get(resource, 0) or 0) - amount
        player.number_of_rcards = sum(int(player.rcards.get(rc, 0) or 0) for rc in ResourceCard)
        self.record_turn_delta(
            player,
            category,
            resource_delta=self._resource_delta_from_cost(cost),
            event_type=category,
            source=str(source or "ai_continue"),
            reason=str(reason or "slice_c2_execute_one_legal_action"),
            message=message,
            metadata=metadata or {},
        )

    def _first_candidate_from_plan_item(self, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        """Return the concrete scanner candidate stored in a plan item.

        Older Continue code used the first candidate from the plan.  The Execution
        Debug panel, however, displays the best candidate from the scanner row
        (for example the highest-pip city target).  This helper now honours an
        explicitly stored ``candidate`` first, so Continue can execute exactly the
        same target that BEST NOW displays.
        """
        if not isinstance(plan_item, Mapping):
            return {}

        candidate = plan_item.get("candidate")
        if isinstance(candidate, Mapping):
            return dict(candidate)

        choice = plan_item.get("choice", {})
        if isinstance(choice, Mapping):
            candidate = choice.get("candidate")
            if isinstance(candidate, Mapping):
                return dict(candidate)
            candidates = list(choice.get("candidates", []) or [])
            if candidates and isinstance(candidates[0], Mapping):
                return dict(candidates[0])

        candidates = list(plan_item.get("candidates", []) or [])
        if candidates and isinstance(candidates[0], Mapping):
            return dict(candidates[0])
        return {}

    def _target_from_plan_item(self, plan_item: Mapping[str, Any]) -> Optional[int]:
        """Extract a settlement/city target id from a concrete plan item."""
        candidate = self._first_candidate_from_plan_item(plan_item)
        for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
            if key in candidate:
                try:
                    return int(candidate.get(key))
                except Exception:
                    continue
        return None

    def _road_from_plan_item(self, plan_item: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
        """Extract a road tuple from a concrete plan item."""
        candidate = self._first_candidate_from_plan_item(plan_item)
        road = None
        for key in ("road_id", "road", "edge", "target_road"):
            if key in candidate:
                road = candidate.get(key)
                break
        try:
            a, b = tuple(road)
            return tuple(sorted((int(a), int(b))))
        except Exception:
            return None

    def _candidate_target_id(self, candidate: Mapping[str, Any]) -> Optional[int]:
        """Return an intersection id from a scanner candidate, if present."""
        if not isinstance(candidate, Mapping):
            return None
        for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
            if key in candidate:
                try:
                    return int(candidate.get(key))
                except Exception:
                    continue
        return None

    def _candidate_pips(self, candidate: Mapping[str, Any]) -> float:
        """Return board production pips for a settlement/city candidate.

        This intentionally mirrors gui_execution_debug_panel._intersection_pips:
        prefer the board intersection's all_tile_pips / three_tile_pips.  Candidate
        score fields are not used for target selection, because they can represent
        planner scores rather than the displayed production pips.
        """
        if not isinstance(candidate, Mapping):
            return 0.0

        target = self._candidate_target_id(candidate)
        if target is None:
            return 0.0
        try:
            inter = self.board.intersections[int(target)]
        except Exception:
            return 0.0
        if inter is None:
            return 0.0

        for attr in ("all_tile_pips", "three_tile_pips"):
            values = getattr(inter, attr, None)
            if isinstance(values, (list, tuple)):
                try:
                    return float(sum(float(v or 0) for v in values))
                except Exception:
                    pass

        # Safe fallback for boards that do not expose all_tile_pips yet.
        total = 0.0
        try:
            for tile, _corner in self.board.intersection_to_corners.get(int(target), []) or []:
                if tile is None:
                    continue
                for attr in ("pips", "pip", "production_pips"):
                    value = getattr(tile, attr, None)
                    if value not in (None, ""):
                        total += float(value)
                        break
        except Exception:
            pass
        return total


    def _current_player_strategic_direction(self) -> Dict[str, Any]:
        """Return the current player's persisted strategic direction, if any."""
        try:
            player = self.get_current_player()
        except Exception:
            player = None
        if player is None:
            return {}
        for attr in ("strategic_direction", "last_strategic_direction"):
            value = getattr(player, attr, None)
            if isinstance(value, Mapping) and value:
                return dict(value)
        return {}

    def _normalise_supporting_action_type(self, value: Any) -> str:
        """Normalise planner support-action labels into route-lock friendly names."""
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "city": "city_upgrade",
            "build_city": "city_upgrade",
            "city_upgrade": "city_upgrade",
            "next_settlement": "next_settlement",
            "next_settle": "next_settlement",
            "build_next_settlement": "next_settlement",
            "new_settlement": "new_settlement",
            "new_settle": "new_settlement",
            "build_new_settlement": "new_settlement",
            "settlement": "build_settlement",
            "settle": "build_settlement",
            "build_settlement": "build_settlement",
            "road": "build_road",
            "build_road": "build_road",
            "dcard": "buy_dcard",
            "development_card": "buy_dcard",
            "buy_dcard": "buy_dcard",
            "buy_development_card": "buy_dcard",
        }
        return aliases.get(text, text)

    def _first_int_from_nested_mapping(self, mapping: Mapping[str, Any], keys: Sequence[str]) -> Optional[int]:
        """Find the first integer-like value for any key, checking one nested level."""
        if not isinstance(mapping, Mapping):
            return None
        for key in keys:
            value = mapping.get(key)
            if value not in (None, ""):
                try:
                    return int(value)
                except Exception:
                    pass
        for value in mapping.values():
            if isinstance(value, Mapping):
                found = self._first_int_from_nested_mapping(value, keys)
                if found is not None:
                    return found
        return None

    def _road_key_from_any(self, road: Any) -> Tuple[int, int]:
        """Return a stable sorted road key from lists, tuples, or candidate dicts."""
        if isinstance(road, Mapping):
            for key in ("road_id", "road", "edge", "target_road", "road_to_build"):
                if key in road:
                    return self._road_key_from_any(road.get(key))
            return ()
        try:
            values = list(road)[:2]
            if len(values) < 2:
                return ()
            a, b = int(values[0]), int(values[1])
            return tuple(sorted((a, b)))
        except Exception:
            return ()

    def _road_from_candidate(self, candidate: Mapping[str, Any]) -> Tuple[int, int]:
        """Return a road key from a scanner road candidate."""
        if not isinstance(candidate, Mapping):
            return ()
        for key in ("road_id", "road", "edge", "target_road", "road_to_build"):
            if key in candidate:
                return self._road_key_from_any(candidate.get(key))
        return ()

    def _route_roads_from_direction(self, direction: Mapping[str, Any]) -> List[Tuple[int, int]]:
        """Extract ordered roads-to-build from a strategic direction."""
        roads: List[Tuple[int, int]] = []

        def add_road(value: Any) -> None:
            key = self._road_key_from_any(value)
            if key and key not in roads:
                roads.append(key)

        def scan_value(value: Any) -> None:
            if value in (None, ""):
                return
            if isinstance(value, Mapping):
                for road_key in ("road_id", "road", "edge", "target_road", "road_to_build"):
                    if road_key in value:
                        add_road(value.get(road_key))
                        return
                for nested_key in ("roads_to_build", "supporting_action_roads_to_build", "supporting_action_path", "path", "road_path", "route_roads"):
                    if nested_key in value:
                        scan_value(value.get(nested_key))
                return
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                # A single road pair, e.g. [15, 16], or a node path, e.g.
                # [15, 16, 42] meaning roads [15,16] then [16,42].
                if len(value) >= 2 and all(not isinstance(x, (list, tuple, dict)) for x in value):
                    try:
                        nodes = [int(x) for x in list(value)]
                        if len(nodes) == 2:
                            add_road(nodes)
                        else:
                            for a, b in zip(nodes, nodes[1:]):
                                add_road([a, b])
                        return
                    except Exception:
                        pass
                for item in value:
                    scan_value(item)

        for key in (
            "supporting_action_roads_to_build",
            "roads_to_build",
            "supporting_action_path",
            "road_path",
            "path",
            "route_roads",
            "new_settlement_roads_to_build",
        ):
            if key in direction:
                scan_value(direction.get(key))
        return roads

    def _settlement_route_plan(self) -> Dict[str, Any]:
        """Return target-lock / route-lock metadata for next/new settlements.

        The planner can express a target as next_settlement@X or new_settlement@X
        with one or more roads_to_build.  This helper normalises those variants so
        BEST NOW can execute the exact targeted road or settlement instead of a
        generic legal candidate.
        """
        direction = self._current_player_strategic_direction()
        if not direction:
            return {}

        support = self._normalise_supporting_action_type(direction.get("supporting_action_type"))
        target = self._first_int_from_nested_mapping(
            direction,
            (
                "supporting_action_target_id",
                "target_id",
                "intersection_id",
                "target_intersection_id",
                "settlement_target_id",
                "new_settlement_target_id",
                "next_settlement_target_id",
                "target",
                "location",
            ),
        )
        roads = self._route_roads_from_direction(direction)

        kind = ""
        if support in {"new_settlement"}:
            kind = "new_settlement"
        elif support in {"next_settlement", "build_settlement"}:
            kind = "next_settlement"
        elif roads and target is not None:
            kind = "new_settlement"

        if not kind and target is None and not roads:
            return {}
        if not kind and target is not None:
            # Conservative default: a known settlement target without route roads is
            # a target-locked next settlement.
            kind = "next_settlement"

        label = "new_settle" if kind == "new_settlement" else "next_settle"
        return {
            "kind": kind,
            "target_settlement_id": target,
            "roads_to_build": roads,
            "target_label": f"{label}@{target}" if target is not None else label,
            "supporting_action_type": support,
        }

    def _target_locked_settlement_candidate(self, route_plan: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        """Return the route/target settlement candidate, never a different one."""
        target = route_plan.get("target_settlement_id") if isinstance(route_plan, Mapping) else None
        if target in (None, ""):
            return {}
        try:
            wanted = int(target)
        except Exception:
            return {}
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            cid = self._candidate_target_id(candidate)
            if cid is not None and int(cid) == wanted:
                return dict(candidate)
        return {}

    def _route_locked_road_candidate(self, route_plan: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        """Return the next legal road in the strategic new-settlement route."""
        if not isinstance(route_plan, Mapping):
            return {}
        route_roads = [self._road_key_from_any(r) for r in list(route_plan.get("roads_to_build", []) or [])]
        route_roads = [r for r in route_roads if r]
        if not route_roads:
            return {}

        by_road: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            key = self._road_from_candidate(candidate)
            if key:
                by_road[key] = dict(candidate)

        for idx, road in enumerate(route_roads, start=1):
            if road in by_road:
                candidate = dict(by_road[road])
                candidate["route_step"] = idx
                candidate["route_steps_total"] = len(route_roads)
                candidate["route_target_id"] = route_plan.get("target_settlement_id")
                candidate["route_target_label"] = route_plan.get("target_label")
                return candidate
        return {}

    def _route_blocked_plan_item(
        self,
        *,
        action: str,
        route_plan: Mapping[str, Any],
        source: str,
        step: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Return a frozen pass/wait item when the targeted route is not legal now."""
        target_label = str(route_plan.get("target_label") or "target") if isinstance(route_plan, Mapping) else "target"
        return {
            "step": step,
            "action": "End turn",
            "label": f"Wait / Prio: {target_label}",
            "status": "blocked",
            "reason": reason,
            "source": source,
            "route_blocked": True,
            "blocked_action": action,
            "route_target_id": route_plan.get("target_settlement_id") if isinstance(route_plan, Mapping) else None,
            "route_target_label": target_label,
            "best_now_label": target_label,
            "best_now_text": f"Wait / Prio: {target_label}",
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(self.get_current_player(), "id", None),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # AI road strategy guard — Step 2 delegation
    # ─────────────────────────────────────────────────────────────────────────

    def _execution_player_is_human(self, player: Optional[Player]) -> bool:
        """Return True when *player* should be treated as human in Execution.

        Kept as a small Game-facing compatibility wrapper; the implementation
        lives in core.ai_road_planner.
        """
        try:
            from core.ai_road_planner import execution_player_is_human
            return bool(execution_player_is_human(self, player))
        except Exception:
            if player is None:
                return False
            try:
                return bool(getattr(player, "is_human", False))
            except Exception:
                return False

    def _ai_road_longest_road_exception_active(self, player: Optional[Player]) -> bool:
        """Placeholder wrapper for the later Longest Road exception."""
        try:
            from core.ai_road_planner import ai_road_longest_road_exception_active
            return bool(ai_road_longest_road_exception_active(self, player))
        except Exception:
            return False

    def _ai_road_guard_applies(self, player: Optional[Player]) -> bool:
        """Return True when settlement-route road filtering should protect player."""
        try:
            from core.ai_road_planner import ai_road_guard_applies
            return bool(ai_road_guard_applies(self, player))
        except Exception:
            return False

    def _ai_strategic_road_route_plan(
        self,
        candidates: Optional[Sequence[Mapping[str, Any]]] = None,
        *,
        player: Optional[Player] = None,
    ) -> Dict[str, Any]:
        """Return the validated settlement-driven AI road plan.

        The actual path discovery, risk scoring, and optional EH timing live in
        core.ai_road_planner / core.outlook_logic / core.risk_assessment.
        """
        try:
            from core.ai_road_planner import build_ai_road_plan
            player = player if player is not None else self.get_current_player()
            return dict(build_ai_road_plan(self, player, candidates or []))
        except Exception:
            return {}

    def _ai_strategic_road_block_reason(self, candidates: Sequence[Mapping[str, Any]]) -> str:
        """Return a short explanation when an AI legal road is suppressed."""
        try:
            from core.ai_road_planner import ai_road_block_reason
            return str(ai_road_block_reason(self, self.get_current_player(), candidates))
        except Exception:
            return "AI road guard: planner unavailable; do not build a generic legal road."

    def _should_suppress_ai_strategic_road_choice(self, choice: Mapping[str, Any]) -> bool:
        """Return True when an AI Build-road choice has no valid strategy route."""
        try:
            from core.ai_road_planner import should_suppress_ai_strategic_road_choice
            return bool(should_suppress_ai_strategic_road_choice(self, choice, player=self.get_current_player()))
        except Exception:
            return False

    def _plan_item_road_is_allowed_for_ai(self, player: Player, road: Tuple[int, int]) -> bool:
        """Last-moment execution guard for stale AI road plan items."""
        try:
            from core.ai_road_planner import road_allowed_for_ai
            return bool(road_allowed_for_ai(self, player, road))
        except Exception:
            return False

    def _best_candidate_for_execution_choice(self, choice: Mapping[str, Any]) -> Dict[str, Any]:
        """Choose the same concrete candidate that BEST NOW should execute.

        For next_settlement/new_settlement strategies this is target-locked:
        - Build settlement uses the planned settlement target only.
        - Build road uses the next legal road in the planned route only.
        """
        if not isinstance(choice, Mapping):
            return {}
        candidates = [dict(c) for c in list(choice.get("candidates", []) or []) if isinstance(c, Mapping)]
        if not candidates:
            return {}

        action = str(choice.get("action", "") or "")
        route_plan = self._settlement_route_plan()

        if action == "Build settlement":
            if route_plan and route_plan.get("target_settlement_id") not in (None, ""):
                return self._target_locked_settlement_candidate(route_plan, candidates)
            return max(
                candidates,
                key=lambda c: (self._candidate_pips(c), -int(self._candidate_target_id(c) or 9999)),
            )

        if action == "Build city":
            return max(
                candidates,
                key=lambda c: (self._candidate_pips(c), -int(self._candidate_target_id(c) or 9999)),
            )

        if action == "Build road":
            player = self.get_current_player()
            if self._ai_road_guard_applies(player):
                strategic_route_plan = self._ai_strategic_road_route_plan(candidates, player=player)
                if strategic_route_plan and strategic_route_plan.get("roads_to_build"):
                    return self._route_locked_road_candidate(strategic_route_plan, candidates)
                return {}
            if route_plan and route_plan.get("kind") == "new_settlement" and route_plan.get("roads_to_build"):
                return self._route_locked_road_candidate(route_plan, candidates)
            return candidates[0]

        return candidates[0]

    def _format_candidate_pips_label(self, pips: float) -> str:
        """Return canonical human display for production pips."""
        try:
            value = float(pips or 0)
        except Exception:
            value = 0.0
        if value <= 0:
            return ""
        if abs(value - int(value)) < 1e-9:
            text = str(int(value))
        else:
            text = f"{value:.2f}".rstrip("0").rstrip(".")
        return f"({text} pips)"

    def _best_now_display_label(self, action: str, candidate: Mapping[str, Any]) -> str:
        """Return the canonical label displayed by Execution Debug."""
        action = str(action or "")
        if action == "Buy development_card":
            try:
                count = candidate.get("dcards_stack_count") if isinstance(candidate, Mapping) else None
                return f"stack {count}" if count not in (None, "") else "buy"
            except Exception:
                return "buy"
        if action in {"Build city", "Build settlement"}:
            target = self._candidate_target_id(candidate) if isinstance(candidate, Mapping) else None
            parts = [str(target)] if target not in (None, "") else []
            pips_label = self._format_candidate_pips_label(self._candidate_pips(candidate))
            if pips_label:
                parts.append(pips_label)
            try:
                inter = self.board.intersections[int(target)] if target is not None else None
                port_tf = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
                port_type = str(getattr(inter, "port_type", "") or "").strip()
                if port_tf and port_type.lower() not in {"", "blank"}:
                    parts.append(port_type.replace("Wool", "Sheep"))
            except Exception:
                pass
            return " ".join(parts)
        if action == "Build road":
            road = None
            if isinstance(candidate, Mapping):
                for key in ("road_id", "road", "edge", "target_road"):
                    if key in candidate:
                        road = candidate.get(key)
                        break
            try:
                a, b = tuple(road)
                return f"[{int(a)}, {int(b)}]"
            except Exception:
                return ""
        return ""

    def _plan_item_from_execution_choice(
        self,
        choice: Mapping[str, Any],
        *,
        source: str = "scanner_best_now",
        step: int = 1,
    ) -> Dict[str, Any]:
        """Wrap a scanner choice into the canonical BEST NOW plan-item shape.

        This is the single place where target/route locks are applied, so the
        Execution Debug label and the AI Continue mutation cannot drift apart.
        """
        concrete_choice = dict(choice or {})
        action = str(concrete_choice.get("action", "") or "")
        route_plan = self._settlement_route_plan()
        if action == "Build road":
            strategic_route_plan = self._ai_strategic_road_route_plan(
                [dict(c) for c in list(concrete_choice.get("candidates", []) or []) if isinstance(c, Mapping)]
            )
            if strategic_route_plan:
                route_plan = strategic_route_plan
        candidate = self._best_candidate_for_execution_choice(concrete_choice)

        if not candidate and action == "Build settlement" and route_plan and route_plan.get("target_settlement_id") not in (None, ""):
            return self._route_blocked_plan_item(
                action=action,
                route_plan=route_plan,
                source="canonical_settlement_target_blocked",
                step=step,
                reason=f"Target settlement {route_plan.get('target_settlement_id')} is not legal/buildable now; do not build a different settlement.",
            )

        if not candidate and action == "Build road":
            player = self.get_current_player()
            if self._ai_road_guard_applies(player):
                return self._route_blocked_plan_item(
                    action=action,
                    route_plan=route_plan if isinstance(route_plan, Mapping) else {},
                    source="ai_strategic_road_guard",
                    step=step,
                    reason=self._ai_strategic_road_block_reason(
                        [dict(c) for c in list(concrete_choice.get("candidates", []) or []) if isinstance(c, Mapping)]
                    ),
                )
            if route_plan and route_plan.get("kind") == "new_settlement" and route_plan.get("roads_to_build"):
                return self._route_blocked_plan_item(
                    action=action,
                    route_plan=route_plan,
                    source="canonical_route_road_blocked",
                    step=step,
                    reason="No legal road candidate matches the planned new-settlement route; do not build a different road.",
                )

        if candidate:
            concrete_choice["candidate"] = dict(candidate)
            concrete_choice["candidates"] = [dict(candidate)]

        pips = self._candidate_pips(candidate) if action in {"Build city", "Build settlement"} else 0.0
        target_id = self._candidate_target_id(candidate) if action in {"Build city", "Build settlement"} else None
        display_label = self._best_now_display_label(action, candidate)
        verb = {
            "Build city": "Build City",
            "Build settlement": "Build Settle",
            "Build road": "Build Road",
            "Buy development_card": "Buy DCard",
        }.get(action, action)

        route_meta: Dict[str, Any] = {}
        if action == "Build road" and candidate and route_plan and route_plan.get("kind") == "new_settlement":
            step_no = int(candidate.get("route_step") or 0)
            total_steps = int(candidate.get("route_steps_total") or len(route_plan.get("roads_to_build", []) or []) or 0)
            target_label = str(route_plan.get("target_label") or "new_settle")
            if step_no and total_steps and target_label:
                display_label = f"{display_label} / Step {step_no} of {total_steps} toward {target_label}".strip()
            route_meta.update({
                "route_kind": route_plan.get("kind"),
                "route_target_id": route_plan.get("target_settlement_id"),
                "route_target_label": target_label,
                "route_step": step_no,
                "route_steps_total": total_steps,
                "route_roads_to_build": [list(r) for r in list(route_plan.get("roads_to_build", []) or [])],
            })
        elif action == "Build settlement" and route_plan and route_plan.get("target_settlement_id") not in (None, ""):
            route_meta.update({
                "route_kind": route_plan.get("kind"),
                "route_target_id": route_plan.get("target_settlement_id"),
                "route_target_label": route_plan.get("target_label"),
                "target_locked": True,
            })

        plan_item: Dict[str, Any] = {
            "step": step,
            "action": action,
            "label": self._format_ai_plan_label(concrete_choice),
            "status": "will_try",
            "reason": str(concrete_choice.get("strategic_reason") or concrete_choice.get("reason") or "Canonical BEST NOW scanner choice."),
            "choice": concrete_choice,
            "candidate": dict(candidate) if candidate else {},
            "source": source,
            "best_now_label": display_label,
            "best_now_text": f"{verb} {display_label}".strip(),
            "target_id": target_id,
            "pips": pips,
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(self.get_current_player(), "id", None),
        }
        plan_item.update(route_meta)
        return plan_item

    def _execution_hand_vector_for_player(self, player: Player) -> List[int]:
        """Return the current hand in Wheat/Ore/Wood/Brick/Sheep order."""
        hand: List[int] = []
        for resource in self._execution_resource_order()[:5]:
            try:
                hand.append(int(player.rcards.get(resource, 0) or 0))
            except Exception:
                hand.append(0)
        return hand

    def _vector_subtract_floor_zero(self, left: Sequence[int], right: Sequence[int]) -> List[int]:
        """Return max(0, left - right) per resource for 5-item vectors."""
        out: List[int] = []
        for a, b in zip((list(left or []) + [0] * 5)[:5], (list(right or []) + [0] * 5)[:5]):
            try:
                out.append(max(0, int(a or 0) - int(b or 0)))
            except Exception:
                out.append(0)
        return out

    def _vector_can_pay(self, hand: Sequence[int], cost: Sequence[int]) -> bool:
        """Return True if hand vector covers cost vector."""
        for have, need in zip((list(hand or []) + [0] * 5)[:5], (list(cost or []) + [0] * 5)[:5]):
            try:
                if int(have or 0) < int(need or 0):
                    return False
            except Exception:
                return False
        return True

    def _first_positive_index(self, values: Sequence[int]) -> Optional[int]:
        """Return the first positive index in a short vector."""
        for idx, value in enumerate(list(values or [])[:5]):
            try:
                if int(value or 0) > 0:
                    return idx
            except Exception:
                continue
        return None

    def _clean_twb_candidate_vectors(self, candidate: Mapping[str, Any]) -> Tuple[List[int], List[int]]:
        """Extract clean give/get vectors from one scanner TwB candidate."""
        give = candidate.get("give_vector", candidate.get("give", [])) if isinstance(candidate, Mapping) else []
        get = candidate.get("get_vector", candidate.get("get", [])) if isinstance(candidate, Mapping) else []
        return self._normalize_twb_vector(give), self._normalize_twb_vector(get)

    def _target_action_from_strategic_direction(self, direction: Mapping[str, Any]) -> str:
        """Map the preferred action-planner support action to an execution action."""
        support = self._normalise_supporting_action_type(direction.get("supporting_action_type")) if isinstance(direction, Mapping) else ""
        if support == "city_upgrade":
            return "Build city"
        if support in {"next_settlement", "new_settlement", "build_settlement"}:
            return "Build settlement"
        if support == "build_road":
            return "Build road"
        if support == "buy_dcard":
            return "Buy development_card"

        # Fallback: current_strategic_needs already stores execution action names.
        for row in list(getattr(self, "current_strategic_needs", []) or []):
            if not isinstance(row, Mapping):
                continue
            action = str(row.get("action", "") or "")
            if action in {"Build city", "Build settlement", "Build road", "Buy development_card"}:
                return action
        return ""

    def _report_need_vector_from_direction(self, direction: Mapping[str, Any]) -> List[int]:
        """Return action-planner/strategy-timing need_vector when available."""
        if not isinstance(direction, Mapping):
            return [0, 0, 0, 0, 0]
        for key in ("need_vector", "supporting_action_need_vector", "continuation_need_vector"):
            value = direction.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return self._normalize_twb_vector(value)
        for nested_key in ("preferred_strategy", "continuation", "strategy", "supporting_action"):
            nested = direction.get(nested_key)
            if isinstance(nested, Mapping):
                value = nested.get("need_vector")
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    return self._normalize_twb_vector(value)
        return [0, 0, 0, 0, 0]

    def _candidate_for_ai_twb_target(self, player: Player, action: str, direction: Mapping[str, Any]) -> Dict[str, Any]:
        """Build a concrete follow-up candidate for the strategic TwB target."""
        if action == "Buy development_card":
            return {
                "description": "Buy one development card after TwB",
                "cost_vector": self._execution_cost_vector_for_action(action),
                "resource_order": [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]],
            }

        if action == "Build city":
            target = self._first_int_from_nested_mapping(
                direction,
                ("supporting_action_target_id", "target_id", "city_target_id", "intersection_id", "target", "location"),
            ) if isinstance(direction, Mapping) else None
            settlements = [int(x) for x in list(getattr(player, "settlements", []) or [])]
            if target is None and settlements:
                # Fallback to the highest-pip owned settlement; the strategic report
                # should normally provide a target, but this keeps older reports usable.
                target = max(settlements, key=lambda sid: self._candidate_pips({"target_id": sid}))
            if target is None or int(target) not in settlements:
                return {}
            return {
                "description": f"Upgrade settlement {int(target)} to city after TwB",
                "target_id": int(target),
                "cost_vector": self._execution_cost_vector_for_action(action),
                "resource_order": [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]],
            }

        if action == "Build settlement":
            route_plan = self._settlement_route_plan()
            target = route_plan.get("target_settlement_id") if isinstance(route_plan, Mapping) else None
            if target in (None, "") and isinstance(direction, Mapping):
                target = self._first_int_from_nested_mapping(
                    direction,
                    ("supporting_action_target_id", "target_id", "settlement_target_id", "intersection_id", "target", "location"),
                )
            try:
                target_int = int(target)
            except Exception:
                return {}
            try:
                if not self.can_build_intersection_tf(target_int, player):
                    return {}
            except Exception:
                return {}
            return {
                "description": f"Build settlement {target_int} after TwB",
                "target_id": target_int,
                "cost_vector": self._execution_cost_vector_for_action(action),
                "resource_order": [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]],
            }

        if action == "Build road":
            route_plan = self._ai_strategic_road_route_plan(player=player)
            roads = list(route_plan.get("roads_to_build", []) or []) if isinstance(route_plan, Mapping) else []
            road: Tuple[int, int] = ()
            for raw in roads:
                candidate = self._road_key_from_any(raw)
                if not candidate:
                    continue
                try:
                    if self.board.can_build_road_for_color_tf(list(candidate), player.color):
                        road = candidate
                        break
                except Exception:
                    continue
            if not road:
                return {}
            return {
                "description": f"Build road {list(road)} after TwB toward {route_plan.get('target_label', 'new_settle')}",
                "road_id": list(road),
                "route_target_id": route_plan.get("target_settlement_id"),
                "route_target_label": route_plan.get("target_label"),
                "route_roads_to_build": [list(r) for r in list(route_plan.get("roads_to_build", []) or [])],
                "cost_vector": self._execution_cost_vector_for_action(action),
                "resource_order": [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]],
            }

        return {}

    def _ai_twb_followup_plan_item(self, player: Player, action: str, candidate: Mapping[str, Any]) -> Dict[str, Any]:
        """Wrap the after-TwB build/buy candidate in normal plan-item shape."""
        if not action or not isinstance(candidate, Mapping) or not candidate:
            return {}
        choice = {
            "action": action,
            "viable": True,
            "actionable": True,
            "priority": 1,
            "reason": "Strategic target unlocked by AI Trade-with-Bank.",
            "strategic_reason": "Strategic target unlocked by AI Trade-with-Bank.",
            "candidates": [dict(candidate)],
        }
        return self._plan_item_from_execution_choice(choice, source="ai_twb_followup", step=2)

    def _resource_names_for_execution(self) -> List[str]:
        """Return the five execution resource names in display order."""
        return [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]

    def get_human_twp_mode(self) -> str:
        """Return the current Human TwP incoming-offer mode."""
        try:
            from core.human_twp_policy import get_human_twp_mode
            return get_human_twp_mode(self)
        except Exception:
            return str(getattr(self, "human_twp_mode", "manual") or "manual").lower()

    def set_human_twp_mode(self, mode: str) -> str:
        """Set the Human TwP incoming-offer mode and emit light feedback."""
        try:
            from core.human_twp_policy import set_human_twp_mode
            new_mode = set_human_twp_mode(self, mode)
        except Exception:
            new_mode = str(mode or "manual").lower()
            if new_mode not in {"manual", "red", "ai", "auto"}:
                new_mode = "manual"
            self.human_twp_mode = new_mode

        try:
            self.emit_twitter_event(None, f"Human TwP Mode: {new_mode.upper() if new_mode != 'manual' else 'Manual'}")
        except Exception:
            pass
        return new_mode

    def toggle_human_twp_mode(self, mode: str) -> str:
        """Toggle Red/AI/Auto; clicking the active mode returns to Manual."""
        try:
            from core.human_twp_policy import toggle_human_twp_mode
            new_mode = toggle_human_twp_mode(self, mode)
        except Exception:
            requested = str(mode or "manual").lower()
            if requested not in {"red", "ai", "auto"}:
                requested = "manual"
            current = str(getattr(self, "human_twp_mode", "manual") or "manual").lower()
            new_mode = "manual" if current == requested else requested
            self.human_twp_mode = new_mode

        try:
            self.emit_twitter_event(None, f"Human TwP Mode: {new_mode.upper() if new_mode != 'manual' else 'Manual'}")
        except Exception:
            pass
        return new_mode

    def _format_twp_proposal_label(self, proposal: Mapping[str, Any]) -> str:
        """Return a compact TwP display label from a proposal dictionary."""
        if not isinstance(proposal, Mapping):
            return "TwP"
        short = str(proposal.get("legacy_short_text") or "").strip()
        if short:
            return short
        desc = str(proposal.get("description") or "").strip()
        if desc:
            return desc
        try:
            names = self._resource_names_for_execution()
            active_id = proposal.get("active_player_id")
            counter_id = proposal.get("counterparty_id")
            give_idx = int(proposal.get("active_give_index", 0) or 0)
            get_idx = int(proposal.get("active_receive_index", 0) or 0)
            give_count = int(proposal.get("active_give_count", 0) or 0)
            get_count = int(proposal.get("active_receive_count", 0) or 0)
            return f"P{active_id}: {give_count}{names[give_idx]}->{get_count}{names[get_idx]} with P{counter_id}"
        except Exception:
            return "TwP"

    def _hand_after_twp_proposal(self, hand: Sequence[int], proposal: Mapping[str, Any]) -> List[int]:
        """Return active player's hand after one TwP proposal dictionary."""
        after = [int(x or 0) for x in (list(hand or []) + [0] * 5)[:5]]
        try:
            give_idx = int(proposal.get("active_give_index", 0) or 0)
            get_idx = int(proposal.get("active_receive_index", 0) or 0)
            give_count = int(proposal.get("active_give_count", 0) or 0)
            get_count = int(proposal.get("active_receive_count", 0) or 0)
            after[give_idx] -= give_count
            after[get_idx] += get_count
        except Exception:
            pass
        return after

    def _first_action_unlocked_by_hand_delta(self, before: Sequence[int], after: Sequence[int]) -> str:
        """Return the first buy/build family payable after but not before a trade."""
        before_vec = [int(x or 0) for x in (list(before or []) + [0] * 5)[:5]]
        after_vec = [int(x or 0) for x in (list(after or []) + [0] * 5)[:5]]

        direction = self._current_player_strategic_direction()
        strategic_action = self._target_action_from_strategic_direction(direction)

        route_plan = self._settlement_route_plan()
        if route_plan.get("kind") == "new_settlement":
            fallback_priority = ["Build road", "Build settlement", "Build city", "Buy development_card"]
        elif route_plan.get("kind") == "next_settlement":
            fallback_priority = ["Build settlement", "Build city", "Build road", "Buy development_card"]
        else:
            fallback_priority = ["Build city", "Build settlement", "Build road", "Buy development_card"]

        priority: List[str] = []
        if strategic_action in {"Build city", "Build settlement", "Build road", "Buy development_card"}:
            priority.append(strategic_action)
        for action in fallback_priority:
            if action not in priority:
                priority.append(action)

        for action in priority:
            cost = self._execution_cost_vector_for_action(action)
            if not self._vector_can_pay(before_vec, cost) and self._vector_can_pay(after_vec, cost):
                return action
        return ""


    def _human_twp_offer_key(self, proposal: Mapping[str, Any]) -> tuple:
        """Return a stable key for one concrete incoming AI→HP TwP proposal."""
        try:
            from core.human_twp_policy import proposal_key
            return tuple(proposal_key(proposal))
        except Exception:
            try:
                return (
                    int(proposal.get("active_player_id", 0) or 0),
                    int(proposal.get("counterparty_id", 0) or 0),
                    int(proposal.get("active_give_index", 0) or 0),
                    int(proposal.get("active_give_count", 0) or 0),
                    int(proposal.get("active_receive_index", 0) or 0),
                    int(proposal.get("active_receive_count", 0) or 0),
                )
            except Exception:
                return tuple()

    def _play_project_sound(self, *sound_names: str) -> bool:
        """Best-effort project sound playback with ordered fallbacks.

        Returns True when a concrete sound object was found and play was requested.
        Game logic must never fail because pygame/mixer/sound assets are unavailable.
        """
        keys = [str(name or "").strip() for name in sound_names if str(name or "").strip()]
        if not keys:
            return False

        # Prefer a future GUI-level sound API when available.
        try:
            gui = getattr(self, "gui", None)
            play_sound = getattr(gui, "play_sound", None)
            if callable(play_sound):
                for key in keys:
                    try:
                        result = play_sound(key)
                        if result is not False:
                            return True
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            from gui.gui_constants import SOUNDS, initialize_sounds  # local import avoids hard GUI dependency

            if not SOUNDS:
                try:
                    initialize_sounds()
                except Exception:
                    pass

            for key in keys:
                sound = SOUNDS.get(key)
                if sound is None:
                    continue
                try:
                    play = getattr(sound, "play", None)
                    if callable(play):
                        play()
                        return True
                    pygame.mixer.Sound.play(sound)
                    return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def _play_twp_found_sound(self) -> bool:
        """Play TwP_Found for an AI-found/manual incoming TwP opportunity."""
        return self._play_project_sound("TWPFOUND", "TWPFOUND2", "BUTTON")

    def _play_human_twp_found_sound(self) -> None:
        """Play the incoming TwP offer sound without making core depend on GUI success."""
        self._play_twp_found_sound()

    def _make_incoming_human_twp_plan_item(
        self,
        proposal: Mapping[str, Any],
        policy_decision: Mapping[str, Any],
        *,
        step: int = 1,
    ) -> Dict[str, Any]:
        """Build the frozen AI plan row that waits for HP's manual response."""
        label = self._format_twp_proposal_label(proposal)
        return {
            "step": step,
            "action": "Incoming TwP",
            "label": f"Incoming TwP {label}",
            "status": "pending_human_response",
            "reason": "Manual Human TwP Mode: waiting for HP to accept or decline before AI chooses a TwP counterparty.",
            "source": "incoming_ai_twp_manual",
            "proposal": dict(proposal),
            "twp_proposal": dict(proposal),
            "human_twp_policy_decision": dict(policy_decision),
            "best_now_label": label,
            "best_now_text": f"Offer HP TwP {label}",
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": proposal.get("active_player_id"),
        }

    def _set_pending_human_twp_offer(
        self,
        proposal: Mapping[str, Any],
        policy_decision: Optional[Mapping[str, Any]] = None,
        *,
        play_sound: bool = True,
    ) -> Dict[str, Any]:
        """Store one pending Manual-mode AI→HP TwP offer and optionally chime."""
        proposal_dict = dict(proposal or {})
        decision_dict = dict(policy_decision or {})
        key = self._human_twp_offer_key(proposal_dict)
        old = getattr(self, "pending_human_twp_offer", None)
        old_key = None
        if isinstance(old, Mapping):
            old_key = tuple(old.get("proposal_key") or ())

        pending = {
            "active": True,
            "proposal": proposal_dict,
            "proposal_key": key,
            "policy_decision": decision_dict,
            "ai_player_id": proposal_dict.get("active_player_id"),
            "human_player_id": proposal_dict.get("counterparty_id"),
            "label": self._format_twp_proposal_label(proposal_dict),
            "description": str(proposal_dict.get("description") or ""),
            "status": "pending_human_response",
        }
        self.pending_human_twp_offer = pending
        self.last_human_twp_policy_decision = dict(decision_dict)

        if play_sound and key and key != old_key:
            self._play_human_twp_found_sound()
            try:
                self.emit_twitter_event(
                    proposal_dict.get("active_player_id"),
                    f"TwP offer to HP: {pending['label']}",
                )
            except Exception:
                pass
        return pending

    def _pending_human_twp_response_plan(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Return a wait plan if an incoming HP TwP panel is already open."""
        pending = getattr(self, "pending_human_twp_offer", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return None
        proposal = pending.get("proposal") or {}
        if not isinstance(proposal, Mapping):
            return None
        return self._make_incoming_human_twp_plan_item(
            proposal,
            pending.get("policy_decision") or {},
            step=step,
        )

    def respond_to_pending_human_twp_offer(self, accepted: bool) -> Dict[str, Any]:
        """Handle HP ACCEPT/DECLINE for the incoming AI→HP TwP panel.

        ACCEPT means HP is willing to take this concrete offer.  The AI player
        still chooses the best TwP counterparty after all candidates are ranked;
        no extra HP confirmation is needed.  DECLINE blocks this exact proposal
        for the rest of the current AI turn.
        """
        pending = getattr(self, "pending_human_twp_offer", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            result = {"ok": False, "reason": "no_pending_human_twp_offer"}
            self.last_human_twp_response_result = result
            return result

        proposal = dict(pending.get("proposal") or {})
        key = tuple(pending.get("proposal_key") or self._human_twp_offer_key(proposal))
        if not isinstance(getattr(self, "human_twp_accepted_this_turn", None), set):
            self.human_twp_accepted_this_turn = set(getattr(self, "human_twp_accepted_this_turn", []) or [])
        if not isinstance(getattr(self, "human_twp_declined_this_turn", None), set):
            self.human_twp_declined_this_turn = set(getattr(self, "human_twp_declined_this_turn", []) or [])

        hp_id = proposal.get("counterparty_id")
        ai_id = proposal.get("active_player_id")
        label = self._format_twp_proposal_label(proposal)
        if accepted:
            self.human_twp_accepted_this_turn.add(key)
            self.human_twp_declined_this_turn.discard(key)
            response_text = "accepted"
        else:
            self.human_twp_declined_this_turn.add(key)
            self.human_twp_accepted_this_turn.discard(key)
            response_text = "declined"

        self.pending_human_twp_offer = None
        try:
            self.emit_twitter_event(hp_id, f"P{hp_id} {response_text} TwP offer from P{ai_id}: {label}")
        except Exception:
            pass

        continue_result = self._continue_ai_twp_after_human_response(
            accepted=bool(accepted),
            original_proposal=proposal,
            original_label=label,
        )
        result = {
            "ok": True,
            "action": "Human TwP response",
            "accepted": bool(accepted),
            "response": response_text,
            "proposal": proposal,
            "proposal_key": key,
            "continue_result": dict(continue_result or {}),
        }
        self.last_human_twp_response_result = result
        return result

    def _continue_ai_twp_after_human_response(
        self,
        *,
        accepted: bool,
        original_proposal: Mapping[str, Any],
        original_label: str,
    ) -> Dict[str, Any]:
        """Let the AI choose/execute TwP after HP responds, or show the next offer."""
        player = self.get_current_player()
        if player is None:
            return {"ok": False, "reason": "no_current_player_after_human_twp_response"}
        if self._is_current_player_human_for_execution():
            return {"ok": False, "reason": "current_player_is_human_after_human_twp_response"}

        plan = self._plan_ai_trade_with_player_for_strategy(step=1)
        if isinstance(plan, Mapping) and str(plan.get("action", "") or "") == "Incoming TwP":
            try:
                self.current_ai_execution_plan = [dict(plan)]
            except Exception:
                pass
            return {
                "ok": True,
                "action": "Incoming TwP",
                "status": "pending_human_response",
                "reason": "next_manual_human_twp_offer_opened",
                "plan": dict(plan),
            }

        if isinstance(plan, Mapping) and str(plan.get("action", "") or "") == "TwP":
            try:
                self.emit_twitter_event(
                    getattr(player, "id", None),
                    f"DBG: Human TwP response received; AI chooses {self._format_twp_proposal_label(plan.get('proposal') or {})}.",
                )
            except Exception:
                pass
            executed = self._execute_ai_twp_support_plan(player, plan)
            # HP accepted only the pending offer that unlocked this AI choice.
            # Once the AI has chosen a counterparty, require a fresh HP response
            # for any later Manual-mode HP offer in the same turn.
            try:
                self.human_twp_accepted_this_turn = set()
            except Exception:
                pass
            slice_d_result = None
            if bool(executed.get("ok")):
                try:
                    slice_d_result = self.continue_action_selection_after_action(
                        "after_human_twp_response",
                        player=player,
                        action_result=dict(executed),
                        clear_forced_locks=True,
                    )
                except Exception as exc:
                    slice_d_result = {"ok": False, "reason": str(exc)}
            return {
                "ok": bool(executed.get("ok")),
                "action": "AI TwP choice after human response",
                "accepted_by_hp": bool(accepted),
                "original_offer": dict(original_proposal),
                "original_label": original_label,
                "chosen_plan": dict(plan),
                "executed_result": dict(executed),
                "slice_d": dict(slice_d_result or {}),
            }

        # No TwP remains.  Rebuild the displayed AI plan; Continue can now choose
        # TwB or pass/end turn using the normal flow.
        try:
            self.current_ai_execution_plan = self._build_ai_continue_plan()
            self.ai_execution_preview_ready = True
            self.ai_execution_preview_player_id = getattr(player, "id", None)
            self.ai_execution_stage = "preview_ready_after_human_twp_response"
        except Exception:
            pass
        return {
            "ok": True,
            "action": "No TwP after human response",
            "accepted_by_hp": bool(accepted),
            "reason": "no_executable_twp_remains_after_human_response",
        }

    def _plan_ai_trade_with_player_for_strategy(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Plan one automatic AI-vs-AI TwP support action.

        This is Layer 3 of the TwP design: the TwP engine already finds/scans
        candidates; this method decides whether the AI Continue button should
        actually execute one.  It is deliberately placed before TwB planning, so
        a player trade such as 1 Ore -> 1 Wheat can beat a wasteful 4:1 bank
        trade.
        """
        if str(getattr(self, "phase", "")) != "Execution":
            return None
        if str(getattr(self, "state", "")) != "ActionSelection":
            return None
        if self._is_current_player_human_for_execution():
            return None

        pending_plan = self._pending_human_twp_response_plan(step=step)
        if isinstance(pending_plan, Mapping):
            return dict(pending_plan)

        player = self.get_current_player()
        if player is None:
            return None

        scan = getattr(self, "current_viable_action_scan", None)
        if isinstance(scan, Mapping) and scan.get("forced_action_mode"):
            return None

        try:
            from core.player_trade import find_twp_proposals
            from core.human_twp_policy import resolve_incoming_human_twp_offer
        except Exception:
            return None

        try:
            # Include HP in the candidate scan, then route any HP-involved offer
            # through the Human TwP Mode policy.  Red mode rejects those offers;
            # AI mode allows the normal TwP algorithm to decide for HP; Auto mode
            # is conservative until the rule editor/parser is implemented.
            proposals = find_twp_proposals(
                self,
                player,
                max_candidates=20,
                include_human_counterparties=True,
            )
        except Exception as exc:
            try:
                self.emit_twitter_event(getattr(player, "id", None), f"DBG: TwP planner failed ({exc})."[:180])
            except Exception:
                pass
            return None

        policy_routed = []
        skipped_policy = []
        for proposal in list(proposals or []):
            try:
                decision = resolve_incoming_human_twp_offer(self, proposal)
            except Exception:
                decision = {"status": "error", "accepted": False, "reason": "human_policy_error"}
            involves_human = bool(decision.get("involves_human", False))
            if involves_human:
                self.last_human_twp_policy_decision = dict(decision)
                if bool(decision.get("requires_human_panel", False)):
                    try:
                        p_dict = proposal.as_dict()
                    except Exception:
                        p_dict = dict(decision.get("proposal") or {})
                    self._set_pending_human_twp_offer(p_dict, decision, play_sound=True)
                    return self._make_incoming_human_twp_plan_item(p_dict, decision, step=step)

                if not bool(decision.get("accepted", False)):
                    skipped_policy.append(dict(decision))
                    continue
                policy_routed.append((proposal, dict(decision)))
            else:
                if bool(getattr(proposal, "auto_executable", False)):
                    policy_routed.append((proposal, dict(decision)))

        if not policy_routed:
            if skipped_policy:
                try:
                    self.last_human_twp_policy_decision = dict(skipped_policy[0])
                except Exception:
                    pass
            return None

        hand_before = self._execution_hand_vector_for_player(player)
        ranked: List[Tuple[Tuple[int, float, int, int, int, int], Any, Dict[str, Any], List[int], str, Dict[str, Any]]] = []
        for proposal, policy_decision in policy_routed:
            try:
                p_dict = proposal.as_dict()
            except Exception:
                continue
            hand_after = self._hand_after_twp_proposal(hand_before, p_dict)
            if any(int(x or 0) < 0 for x in hand_after):
                continue
            unlocked_action = self._first_action_unlocked_by_hand_delta(hand_before, hand_after)
            unlock_rank = 0 if unlocked_action else 1
            try:
                total_score = float(p_dict.get("total_score", 0.0) or 0.0)
            except Exception:
                total_score = 0.0
            try:
                give_count = int(p_dict.get("active_give_count", 0) or 0)
                receive_count = int(p_dict.get("active_receive_count", 0) or 0)
                counterparty_id = int(p_dict.get("counterparty_id", 0) or 0)
                give_idx = int(p_dict.get("active_give_index", 0) or 0)
                receive_idx = int(p_dict.get("active_receive_index", 0) or 0)
            except Exception:
                give_count = receive_count = counterparty_id = give_idx = receive_idx = 0
            # Lower tuple is better.  Prioritize trades that unlock an immediate
            # action, then highest TwP score, then stable/resource ordering.
            rank = (unlock_rank, -total_score, counterparty_id, give_idx, receive_idx, give_count - receive_count)
            ranked.append((rank, proposal, p_dict, hand_after, unlocked_action, dict(policy_decision)))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0])
        _rank, _proposal_obj, proposal, hand_after, unlocked_action, policy_decision = ranked[0]
        label = self._format_twp_proposal_label(proposal)
        follow_text = self._short_execution_action_label(unlocked_action) if unlocked_action else "rescan"
        best_text = f"TwP {label}"
        if unlocked_action:
            best_text = f"{best_text}; then {follow_text}"

        return {
            "step": step,
            "action": "TwP",
            "label": f"TwP {label}",
            "status": "will_try",
            "reason": (
                f"AI TwP support: player trade before bank trade"
                + (f" unlocks {follow_text}." if unlocked_action else " improves hand before pass/TwB.")
                + (f" Human TwP mode={policy_decision.get('mode')}." if policy_decision.get('involves_human') else "")
            ),
            "source": "ai_twp_support",
            "choice": {
                "action": "TwP",
                "viable": True,
                "actionable": True,
                "reason": "Best executable TwP candidate after Human TwP Mode routing.",
                "candidates": [dict(proposal)],
            },
            "candidate": dict(proposal),
            "proposal": dict(proposal),
            "twp_proposal": dict(proposal),
            "human_twp_policy_decision": dict(policy_decision),
            "hand_before": list(hand_before),
            "hand_after": list(hand_after),
            "unlocked_action": unlocked_action,
            "best_now_label": label,
            "best_now_text": best_text,
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(player, "id", None),
        }

    def _execute_ai_twp_support_plan(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute AI TwP, rescan, then execute an unlocked buy/build if available."""
        proposal = plan_item.get("proposal") or plan_item.get("twp_proposal") or plan_item.get("candidate") or {}
        if not isinstance(proposal, Mapping):
            return {"ok": False, "action": "TwP", "reason": "missing_twp_proposal"}

        label = self._format_twp_proposal_label(proposal)
        try:
            policy_decision = dict(plan_item.get("human_twp_policy_decision", {}) or {})
            if policy_decision:
                self.last_human_twp_policy_decision = dict(policy_decision)
        except Exception:
            policy_decision = {}
        try:
            from core.player_trade import execute_twp_trade_from_dict
        except Exception as exc:
            return {"ok": False, "action": "TwP", "reason": f"twp_import_failed:{exc}"}

        # AI-executed TwP should sound like one completed trade only.
        # Do not play TwP_Found here; successful execution below plays
        # DEAL/CashRegister through core.player_trade / Game.
        decision = execute_twp_trade_from_dict(
            self,
            proposal,
            require_human_confirmation=False,
        )
        decision_dict = decision.as_dict() if hasattr(decision, "as_dict") else dict(decision or {})
        if not bool(decision_dict.get("executed")):
            return {
                "ok": False,
                "action": "TwP",
                "reason": f"twp_failed:{decision_dict.get('reason', 'unknown')}",
                "twp_decision": dict(decision_dict),
                "proposal": dict(proposal),
            }

        try:
            self.emit_twitter_event(getattr(player, "id", None), f"TwP {label}")
        except Exception:
            pass
        try:
            for p in list(getattr(self, "players", []) or []):
                self.update_strategy_dashboard(p)
        except Exception:
            pass

        try:
            self.refresh_strategy_context("after_ai_twp_support", force=True)
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_ai_twp_support")
        except Exception:
            pass

        followup_item = self.get_current_best_executable_action()
        if not isinstance(followup_item, Mapping):
            followup_item = {}
        followup_action = str(followup_item.get("action", "") or "")
        if followup_action not in {"Buy development_card", "Build city", "Build settlement", "Build road"}:
            return {
                "ok": True,
                "action": "TwP",
                "support_action": "TwP",
                "reason": "twp_executed_no_followup_available_after_rescan",
                "message": f"TwP {label}",
                "twp_decision": dict(decision_dict),
                "proposal": dict(proposal),
            }

        followup_result = self._execute_one_ai_plan_item(player, followup_item)
        if bool(followup_result.get("ok")):
            return {
                "ok": True,
                "action": str(followup_result.get("action", followup_action) or followup_action),
                "support_action": "TwP",
                "combined_action": f"TwP + {followup_result.get('action', followup_action)}",
                "reason": "twp_unlocked_and_executed_followup",
                "message": f"TwP {label}; then {followup_result.get('action', followup_action)}",
                "twp_decision": dict(decision_dict),
                "proposal": dict(proposal),
                "followup_result": dict(followup_result),
                "followup_plan_item": dict(followup_item),
            }

        return {
            "ok": True,
            "action": "TwP",
            "support_action": "TwP",
            "reason": f"twp_executed_followup_failed:{followup_result.get('reason', 'unknown')}",
            "message": f"TwP {label}; follow-up failed",
            "twp_decision": dict(decision_dict),
            "proposal": dict(proposal),
            "followup_result": dict(followup_result),
            "followup_plan_item": dict(followup_item),
        }

    def _plan_ai_trade_with_bank_for_strategy(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Plan one AI TwB support action that immediately unlocks the strategic target.

        This deliberately uses three sources:
        - viable_action_scanner TwB candidates = legal menu;
        - live need_vector from current hand and target cost = execution truth;
        - action-planner need_vector = strategic hint / debug evidence.
        """
        if str(getattr(self, "phase", "")) != "Execution":
            return None
        if str(getattr(self, "state", "")) != "ActionSelection":
            return None
        if self._is_current_player_human_for_execution():
            return None

        player = self.get_current_player()
        if player is None:
            return None

        scan = getattr(self, "current_viable_action_scan", None)
        if not isinstance(scan, Mapping):
            return None
        if scan.get("forced_action_mode"):
            return None
        candidates_by_action = dict(scan.get("candidates", {}) or {})
        twb_candidates = [dict(c) for c in list(candidates_by_action.get("TwB", []) or []) if isinstance(c, Mapping)]
        if not twb_candidates:
            return None

        direction = self._current_player_strategic_direction()
        action = self._target_action_from_strategic_direction(direction)
        if action not in {"Build city", "Build settlement", "Build road", "Buy development_card"}:
            return None

        target_candidate = self._candidate_for_ai_twb_target(player, action, direction)
        if not target_candidate:
            return None

        cost = self._execution_cost_vector_for_action(action)
        hand = self._execution_hand_vector_for_player(player)
        if self._vector_can_pay(hand, cost):
            # Direct execution should be handled by normal BEST NOW, not TwB.
            return None

        live_need = self._vector_subtract_floor_zero(cost, hand)
        if sum(live_need) <= 0:
            return None
        report_need = self._report_need_vector_from_direction(direction)
        surplus = self._vector_subtract_floor_zero(hand, cost)
        rates = self.get_player_bank_trade_rates(player)
        names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]

        ranked: List[Tuple[Tuple[int, int, int, int], Dict[str, Any], List[int], List[int], List[int]]] = []
        for candidate in twb_candidates:
            give, get = self._clean_twb_candidate_vectors(candidate)
            give_idx = self._first_positive_index(give)
            get_idx = self._first_positive_index(get)
            if give_idx is None or get_idx is None:
                continue
            if int(live_need[get_idx] or 0) <= 0:
                continue
            if int(give[give_idx] or 0) > int(surplus[give_idx] or 0):
                continue
            if any(int(give[i] or 0) > int(surplus[i] or 0) for i in range(5)):
                continue

            after = [int(hand[i] or 0) - int(give[i] or 0) + int(get[i] or 0) for i in range(5)]
            if not self._vector_can_pay(after, cost):
                continue

            # Ranking: best rate, largest surplus used, strategic/report need served,
            # stable resource order.  Lower tuple is better.
            try:
                rate = int(candidate.get("rate", rates[give_idx]) or rates[give_idx] or 4)
            except Exception:
                rate = int(rates[give_idx] or 4)
            served_report_need = 1 if int(report_need[get_idx] or 0) > 0 else 0
            rank = (
                rate,
                -int(surplus[give_idx] or 0),
                -served_report_need,
                int(give_idx),
            )
            ranked.append((rank, candidate, give, get, after))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0])
        _rank, candidate, give, get, after = ranked[0]
        followup = self._ai_twb_followup_plan_item(player, action, target_candidate)
        if not followup:
            return None

        give_text = self._format_twb_amounts(give, names)
        get_text = self._format_twb_amounts(get, names)
        follow_text = str(followup.get("best_now_text", "") or followup.get("label", action))
        best_text = f"TwB {give_text} -> {get_text}; then {follow_text}".strip()

        plan_item: Dict[str, Any] = {
            "step": step,
            "action": "TwB",
            "label": f"TwB {give_text} -> {get_text}",
            "status": "will_try",
            "reason": f"AI TwB support: unlocks {follow_text}.",
            "source": "ai_twb_support",
            "choice": {
                "action": "TwB",
                "viable": True,
                "actionable": True,
                "reason": "Legal scanner TwB candidate unlocks current strategic target.",
                "candidates": [dict(candidate)],
            },
            "candidate": dict(candidate),
            "give": list(give),
            "get": list(get),
            "rates": list(rates[:5]),
            "hand_before": list(hand),
            "hand_after": list(after),
            "target_action": action,
            "target_cost_vector": list(cost),
            "live_need_vector": list(live_need),
            "report_need_vector": list(report_need),
            "surplus_vector": list(surplus),
            "then_plan_item": dict(followup),
            "best_now_label": f"{give_text} -> {get_text}",
            "best_now_text": best_text,
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(player, "id", None),
        }
        return plan_item

    def _execute_ai_twb_support_plan(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute AI TwB, rescan, then execute the unlocked strategic build/buy."""
        give = self._normalize_twb_vector(plan_item.get("give", []))
        get = self._normalize_twb_vector(plan_item.get("get", []))
        names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]
        give_text = self._format_twb_amounts(give, names)
        get_text = self._format_twb_amounts(get, names)

        twb_result = self.execute_trade_with_bank_vector_action(
            give,
            get,
            source="ai_twb_planner",
            reason="ai_twb_unlocks_strategic_target",
        )
        if not bool(twb_result.get("ok")):
            return {
                "ok": False,
                "action": "TwB",
                "reason": f"twb_failed:{twb_result.get('reason', 'unknown')}",
                "twb_result": dict(twb_result),
            }

        try:
            self.refresh_strategy_context("after_ai_twb_support", force=True)
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_ai_twb_support")
        except Exception:
            pass

        planned_followup = plan_item.get("then_plan_item", {})
        followup_item = dict(planned_followup) if isinstance(planned_followup, Mapping) else {}
        current_best = self.get_current_best_executable_action()
        if isinstance(current_best, Mapping) and str(current_best.get("action", "") or "") == str(followup_item.get("action", "") or ""):
            followup_item = dict(current_best)

        if not followup_item or str(followup_item.get("action", "") or "") == "TwB":
            return {
                "ok": True,
                "action": "TwB",
                "reason": "twb_executed_no_followup_available_after_rescan",
                "message": f"TwB {give_text} -> {get_text}",
                "twb_result": dict(twb_result),
            }

        followup_result = self._execute_one_ai_plan_item(player, followup_item)
        if bool(followup_result.get("ok")):
            return {
                "ok": True,
                "action": str(followup_result.get("action", followup_item.get("action", "")) or ""),
                "support_action": "TwB",
                "combined_action": f"TwB + {followup_result.get('action', followup_item.get('action', 'Action'))}",
                "reason": "twb_unlocked_and_executed_followup",
                "message": f"TwB {give_text} -> {get_text}; then {followup_result.get('action')}",
                "twb_result": dict(twb_result),
                "followup_result": dict(followup_result),
                "followup_plan_item": dict(followup_item),
            }

        return {
            "ok": True,
            "action": "TwB",
            "support_action": "TwB",
            "reason": f"twb_executed_followup_failed:{followup_result.get('reason', 'unknown')}",
            "message": f"TwB {give_text} -> {get_text}; follow-up failed",
            "twb_result": dict(twb_result),
            "followup_result": dict(followup_result),
            "followup_plan_item": dict(followup_item),
        }

    def _compute_current_best_executable_action(self) -> Optional[Dict[str, Any]]:
        """Compute the current canonical BEST NOW action from existing scan rows."""
        executable_actions = {"Buy development_card", "Build city", "Build settlement", "Build road"}
        route_plan = self._settlement_route_plan()
        if route_plan.get("kind") == "new_settlement":
            action_priority = {"Build road": 1, "Build settlement": 2, "Build city": 3, "Buy development_card": 4}
        elif route_plan.get("kind") == "next_settlement":
            action_priority = {"Build settlement": 1, "Build city": 2, "Build road": 3, "Buy development_card": 4}
        else:
            action_priority = {"Build city": 1, "Build settlement": 2, "Build road": 3, "Buy development_card": 4}

        rows = [row for row in list(getattr(self, "current_actionable_choices", []) or []) if isinstance(row, Mapping)]
        rows = [row for row in rows if str(row.get("action", "") or "") in executable_actions and bool(row.get("actionable", row.get("viable", False)))]

        if not rows:
            # Fallback keeps older/no-strategy turns usable, but still reads from
            # scanner rows rather than from stale preview-plan rows.
            rows = [row for row in list(getattr(self, "current_execution_choices", []) or []) if isinstance(row, Mapping)]
            rows = [row for row in rows if str(row.get("action", "") or "") in executable_actions and bool(row.get("viable", False))]

        if not rows:
            twp_plan = self._plan_ai_trade_with_player_for_strategy(step=1)
            if isinstance(twp_plan, Mapping) and twp_plan.get("action"):
                return dict(twp_plan)
            twb_plan = self._plan_ai_trade_with_bank_for_strategy(step=1)
            if isinstance(twb_plan, Mapping) and twb_plan.get("action"):
                return dict(twb_plan)
            return None

        def _sort_key(row: Mapping[str, Any]) -> Tuple[int, int]:
            try:
                row_priority = int(row.get("priority", 99) or 99)
            except Exception:
                row_priority = 99
            return (row_priority, action_priority.get(str(row.get("action", "") or ""), 99))

        choice = dict(sorted(rows, key=_sort_key)[0])
        return self._plan_item_from_execution_choice(choice, source="canonical_best_now", step=1)

    def _best_now_action_is_current(self, plan_item: Any) -> bool:
        """Return True when a stored BEST NOW object belongs to this live turn."""
        if not isinstance(plan_item, Mapping):
            return False
        try:
            if int(plan_item.get("round")) != int(getattr(self, "round", 0) or 0):
                return False
            if int(plan_item.get("turn")) != int(getattr(self, "turn", 0) or 0):
                return False
        except Exception:
            return False
        if str(plan_item.get("state", "") or "") != str(getattr(self, "state", "") or ""):
            return False
        try:
            player = self.get_current_player()
            if player is not None and int(plan_item.get("player_id")) != int(getattr(player, "id", 0) or 0):
                return False
        except Exception:
            return False
        return True

    def get_current_best_executable_action(self) -> Optional[Dict[str, Any]]:
        """Return the canonical buy/build action that Continue should execute now.

        Execution Debug displays this same object.  AI Continue executes this same
        object.  The method does not refresh the scanner at click time, because a
        refresh can reorder candidates and make the executed target differ from
        the displayed BEST NOW target.
        """
        stored = getattr(self, "current_best_now_action", None)
        if self._best_now_action_is_current(stored):
            return dict(stored)

        plan_item = self._compute_current_best_executable_action()
        self.current_best_now_action = dict(plan_item) if isinstance(plan_item, Mapping) else None
        return dict(plan_item) if isinstance(plan_item, Mapping) else None

    def _dcard_type_order(self) -> List[str]:
        """Return the canonical scoreboard order for development-card types."""
        return ["victory_point", "knight", "two_free_roads", "year_of_plenty", "monopoly"]

    def _default_dcard_summary(self) -> List[List[Any]]:
        """Return a fresh empty DCard summary in scoreboard order.

        Row format: [card_name, new_this_turn, playable_later, played_or_vp].
        This is used as a defensive normalizer so AI and human players always
        have the same DCard state shape, including after loading older saves.
        """
        return [[card_name, 0, 0, 0] for card_name in self._dcard_type_order()]

    def _ensure_player_dcard_state(self, player: Player) -> None:
        """Ensure every player has a complete DCard state model.

        Older experimental saves/modules may have partial or malformed
        ``dcard_summary`` data.  Normalizing here keeps AI DCard buys and human
        DCard buys on the same state model before the GUI reads the dashboard.
        """
        if player is None:
            return

        try:
            cards = getattr(player, "development_cards", [])
            if cards is None:
                cards = []
            if isinstance(cards, tuple):
                cards = list(cards)
            elif not isinstance(cards, list):
                cards = list(cards) if isinstance(cards, (set, tuple)) else [cards]
            player.development_cards = [str(card) for card in cards]
        except Exception:
            player.development_cards = []

        existing_by_name: Dict[str, List[Any]] = {}
        try:
            for row in list(getattr(player, "dcard_summary", []) or []):
                row_list = list(row)
                if not row_list:
                    continue
                name = str(row_list[0])
                while len(row_list) < 4:
                    row_list.append(0)
                clean_row: List[Any] = [name]
                for value in row_list[1:4]:
                    try:
                        clean_row.append(max(0, int(value or 0)))
                    except Exception:
                        clean_row.append(0)
                existing_by_name[name] = clean_row
        except Exception:
            existing_by_name = {}

        normalized: List[List[Any]] = []
        for name in self._dcard_type_order():
            row = list(existing_by_name.get(name, [name, 0, 0, 0]))
            row[0] = name
            while len(row) < 4:
                row.append(0)
            normalized.append(row[:4])
        player.dcard_summary = normalized

        try:
            player.number_of_dcards = len(getattr(player, "development_cards", []) or [])
        except Exception:
            player.number_of_dcards = 0

    def _execution_dcard_summary_index(self, card_name: str) -> int:
        try:
            return self._dcard_type_order().index(str(card_name))
        except Exception:
            return -1

    def _player_dcard_vp_count(self, player: Player) -> int:
        """Return visible VP points coming from victory-point development cards."""
        try:
            summary = getattr(player, "dcard_summary", []) or []
            for row in summary:
                if row and str(row[0]) == "victory_point":
                    try:
                        return max(0, int(row[3] or 0))
                    except Exception:
                        break
        except Exception:
            pass

        try:
            return sum(1 for card in (getattr(player, "development_cards", []) or []) if str(card) == "victory_point")
        except Exception:
            return 0

    def _record_dcard_buy_detail(self, player: Player, card_name: str) -> None:
        """Keep a small optional buy-history trail for the dcard dashboard/detail UI."""
        try:
            marker = f"R{int(getattr(self, 'round', 0) or 0)}/T{int(getattr(self, 'turn', 0) or 0)}"
        except Exception:
            marker = "R?/T?"

        try:
            details = getattr(player, "dcard_buy_details", None)
            if not isinstance(details, dict):
                details = {}
                setattr(player, "dcard_buy_details", details)
            details.setdefault(str(card_name or "unknown"), []).append(marker)
        except Exception:
            pass

        try:
            turn_details = getattr(self, "turn_details", None)
            if turn_details is not None:
                setattr(turn_details, "dcard_bought_in_turn_TF", True)
        except Exception:
            pass

    def _add_development_card_to_player(self, player: Player, card_name: str) -> None:
        """Add a bought development card to the player's hidden card state.

        This helper is intentionally shared by AI and human DCard buy flows.
        It updates the hidden card list, the v045-style DCard triplet summary,
        the total DCard count, and victory points for VP cards.
        """
        card_name = str(card_name or "").strip() or "unknown"
        self._ensure_player_dcard_state(player)

        try:
            player.development_cards.append(card_name)
        except Exception:
            player.development_cards = [card_name]

        idx = self._execution_dcard_summary_index(card_name)
        if idx >= 0:
            try:
                while len(player.dcard_summary[idx]) < 4:
                    player.dcard_summary[idx].append(0)
                # Column 1 = bought-this-turn / not-yet-playable count.
                # Column 2 remains playable count, so a card bought this turn
                # is not immediately playable.  Column 3 is played/VP count.
                player.dcard_summary[idx][1] = int(player.dcard_summary[idx][1] or 0) + 1
                if card_name == "victory_point":
                    # Victory-point dcards count as VP immediately, while still
                    # remaining hidden in the player's development-card state.
                    player.dcard_summary[idx][3] = int(player.dcard_summary[idx][3] or 0) + 1
            except Exception:
                pass

        self._record_dcard_buy_detail(player, card_name)

        player.number_of_dcards = len(getattr(player, "development_cards", []) or [])
        try:
            player.recalculate_victory_points()
        except Exception:
            pass

    def _refresh_gui_scoreboard_after_dcard_change(self, reason: str = "") -> None:
        """Best-effort scoreboard refresh after a DCard state mutation.

        The game logic is the source of truth; the GUI is a view.  This helper
        keeps AI DCard buys visually aligned with human DCard buys without
        making action execution depend on Pygame being available.
        """
        try:
            gui = getattr(self, "gui", None)
            if gui is None:
                return

            update_scoreboard = getattr(gui, "update_scoreboard", None)
            if callable(update_scoreboard):
                update_scoreboard(self)
            else:
                display_scoreboard = getattr(gui, "display_scoreboard", None)
                if callable(display_scoreboard):
                    display_scoreboard()

            try:
                pygame.display.update()
            except Exception:
                pass
        except Exception:
            pass

    def _execution_sound_name_for_action(self, action: str) -> str:
        """Return the GUI sound key for a successful execution buy/build action.

        Gen2 used the fanfare for settlements/cities, BuildRoad.wav for roads,
        and BuyDCard2.wav for development-card buys.  Keep those semantics while
        using the Gen3 gui.gui_constants.SOUNDS registry.
        """
        normalized = str(action or "").strip().lower()
        if normalized == "build road":
            return "BUILDROAD"
        if normalized in {"build settlement", "build city"}:
            return "FANFARE"
        if normalized == "buy development_card":
            return "BUYDCARD"
        if normalized in {"twb", "trade with bank", "trade_with_bank"}:
            return "DEAL"
        if normalized in {
            "twp",
            "trade with player",
            "trade_with_player",
            "twp - make offer",
            "make twp offer",
        }:
            # Successful TwP deals should sound like a completed trade, not like
            # informational feedback.  TwP_Found remains reserved for discovered
            # offers / incoming manual proposals.
            return "DEAL"
        return ""

    def _play_execution_action_sound(self, action: str) -> bool:
        """Play a successful execution action sound safely.

        TwP and TwB successes use DEAL/CashRegister.  STEAL is kept as a
        compatibility fallback because it points to the same CashRegister asset
        in older gui_constants copies.
        """
        sound_name = self._execution_sound_name_for_action(action)
        if not sound_name:
            return False

        if sound_name == "DEAL":
            return self._play_project_sound("DEAL", "STEAL")
        return self._play_project_sound(sound_name)

    def _set_pending_execution_build_animation(
        self,
        action: str,
        player: Player,
        *,
        target_id: Optional[int] = None,
        road_id: Optional[Sequence[int]] = None,
    ) -> None:
        """Store one newly built object for GUI animation after redraw.

        This intentionally mirrors the Initial Placement animation mechanism:
        the GUI will queue a settlement/city/road pulse using the same
        animate_queue_elements + _animate_elements path. Game only records the
        immutable identity of the object that was just built.
        """
        try:
            item: Dict[str, Any] = {
                "action": str(action or ""),
                "player_id": int(getattr(player, "id", 0) or 0),
                "color": str(getattr(player, "color", "") or ""),
                "round": int(getattr(self, "round", 0) or 0),
                "turn": int(getattr(self, "turn", 0) or 0),
            }
            if target_id is not None:
                item["target_id"] = int(target_id)
            if road_id is not None:
                a, b = tuple(road_id)[:2]
                item["road_id"] = [int(a), int(b)]
            self._pending_execution_build_animation = item
        except Exception:
            pass

    def _execute_ai_buy_dcard(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        action = "Buy development_card"
        cost = self._execution_cost_vector_for_action(action)
        if not self._can_player_pay_execution_cost(player, cost):
            return {"ok": False, "action": action, "reason": "cannot_pay_cost"}
        if not list(getattr(self, "dcards_stack", []) or []):
            return {"ok": False, "action": action, "reason": "empty_dcards_stack"}

        try:
            card_name = str(self.dcards_stack.pop(0))
        except Exception:
            return {"ok": False, "action": action, "reason": "failed_to_draw_card"}

        self._deduct_execution_cost(
            player,
            cost,
            category="dcard",
            message="bought a development card",
            metadata={"card_name": card_name},
        )
        self._add_development_card_to_player(player, card_name)
        self.update_strategy_dashboard(player)
        self._refresh_gui_scoreboard_after_dcard_change("after_ai_buy_dcard")
        self.emit_twitter_event(getattr(player, "id", None), f"bought a DCard ({card_name})")
        self._play_execution_action_sound(action)
        return {"ok": True, "action": action, "card_name": card_name}

    def _execute_ai_build_city(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        action = "Build city"
        target = self._target_from_plan_item(plan_item)
        cost = self._execution_cost_vector_for_action(action)
        if target is None:
            return {"ok": False, "action": action, "reason": "missing_target"}
        if target not in list(getattr(player, "settlements", []) or []):
            return {"ok": False, "action": action, "reason": "target_not_owned_settlement", "target_id": target}
        if not self._can_player_pay_execution_cost(player, cost):
            return {"ok": False, "action": action, "reason": "cannot_pay_cost", "target_id": target}

        inter = self.board.intersections[target] if 0 <= target < len(self.board.intersections) else None
        if inter is None:
            return {"ok": False, "action": action, "reason": "invalid_intersection", "target_id": target}

        # Upgrade the existing settlement without increasing tile.current_settlements.
        inter.occupied_tf = True
        inter.face = "City"
        inter.color = player.color
        inter.game_round = self.round
        inter.game_turn = self.turn
        try:
            for tile, corner_loc in self.board.intersection_to_corners.get(target, []) or []:
                corner = next((c for c in tile.corners if c.location == corner_loc), None)
                if corner is not None:
                    corner.kind = "City"
                    corner.color = player.color
        except Exception:
            pass

        player.settlements = [sid for sid in list(getattr(player, "settlements", []) or []) if int(sid) != int(target)]
        if target not in list(getattr(player, "cities", []) or []):
            player.cities.append(target)
        self._deduct_execution_cost(player, cost, category="buy", message=f"built City @{target}", metadata={"target_id": target})
        self.update_strategy_dashboard(player)
        self.emit_twitter_event(getattr(player, "id", None), f"built City @{target}")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, target_id=target)
        return {"ok": True, "action": action, "target_id": target}

    def _execute_ai_build_settlement(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        action = "Build settlement"
        target = self._target_from_plan_item(plan_item)
        cost = self._execution_cost_vector_for_action(action)
        if target is None:
            return {"ok": False, "action": action, "reason": "missing_target"}
        if not self._can_player_pay_execution_cost(player, cost):
            return {"ok": False, "action": action, "reason": "cannot_pay_cost", "target_id": target}
        if not self.can_build_intersection_tf(target, player):
            return {"ok": False, "action": action, "reason": "not_legal_settlement_target", "target_id": target}

        self.board.occupy_intersection(target, "Settlement", player.color)
        if target not in list(getattr(player, "settlements", []) or []):
            player.settlements.append(target)
        self._deduct_execution_cost(player, cost, category="buy", message=f"built Settlement @{target}", metadata={"target_id": target})
        try:
            player.update_trade_rates(self.board)
        except Exception:
            pass
        self.update_strategy_dashboard(player)
        self.emit_twitter_event(getattr(player, "id", None), f"built Settlement @{target}")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, target_id=target)
        return {"ok": True, "action": action, "target_id": target}

    def _execute_ai_build_road(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        action = "Build road"
        road = self._road_from_plan_item(plan_item)
        cost = self._execution_cost_vector_for_action(action)
        if road is None:
            return {"ok": False, "action": action, "reason": "missing_road"}
        if not self._can_player_pay_execution_cost(player, cost):
            return {"ok": False, "action": action, "reason": "cannot_pay_cost", "road_id": list(road)}
        if not self.board.can_build_road_for_color_tf(list(road), player.color):
            return {"ok": False, "action": action, "reason": "not_legal_road", "road_id": list(road)}
        if not self._plan_item_road_is_allowed_for_ai(player, road):
            return {
                "ok": False,
                "action": action,
                "reason": "road_not_on_strategy_new_settlement_route",
                "road_id": list(road),
            }

        self.board.occupy_road(road, "Road", player.color)
        if road not in list(getattr(player, "roads", []) or []):
            player.roads.append(road)
        self._deduct_execution_cost(player, cost, category="buy", message=f"built Road {list(road)}", metadata={"road_id": list(road)})
        self.update_strategy_dashboard(player)
        self.emit_twitter_event(getattr(player, "id", None), f"built Road [{road[0]},{road[1]}]")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, road_id=road)
        return {"ok": True, "action": action, "road_id": list(road)}

    def _refresh_after_human_buy_build_action(self, reason: str, action_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run Slice D after a confirmed human buy/build action."""
        try:
            return self.continue_action_selection_after_action(
                str(reason),
                player=self.get_current_player(),
                action_result=action_result,
            )
        except Exception as exc:
            # Backward-safe fallback if Slice D is temporarily unavailable.
            try:
                self.refresh_strategy_context(str(reason), force=True)
            except Exception:
                pass
            try:
                self.refresh_viable_actions(str(reason))
            except Exception:
                pass
            return {"ok": False, "reason": f"slice_d_failed:{exc}"}

    def _base_human_buy_result(self, action: str, source: str, **extra: Any) -> Dict[str, Any]:
        """Small common result skeleton for confirmed human buy/build methods."""
        result: Dict[str, Any] = {
            "ok": False,
            "action": str(action),
            "reason": "",
            "source": str(source),
        }
        result.update(extra)
        return result

    def _validate_human_action_selection_context(self, result: Dict[str, Any]) -> Optional[Player]:
        """Return the current human player or set result['reason'] and return None."""
        if str(getattr(self, "phase", "")) != "Execution":
            result["reason"] = "not_execution_phase"
            return None
        if str(getattr(self, "state", "")) != "ActionSelection":
            result["reason"] = f"state_not_action_selection:{getattr(self, 'state', '')}"
            return None
        player = self.get_current_player()
        if player is None:
            result["reason"] = "no_current_player"
            return None
        try:
            if not bool(self._is_current_player_human_for_execution()):
                result["reason"] = "current_player_not_human"
                return None
        except Exception:
            pass
        return player

    def execute_human_buy_dcard_action(self) -> Dict[str, Any]:
        """Execute a confirmed human Buy Development Card action."""
        action = "Buy development_card"
        source = "human_buy_dcard"
        result = self._base_human_buy_result(action, source)
        player = self._validate_human_action_selection_context(result)
        if player is None:
            return result

        cost = self._execution_cost_vector_for_action(action)
        if not self._can_player_pay_execution_cost(player, cost):
            result["reason"] = "cannot_pay_cost"
            return result
        if not list(getattr(self, "dcards_stack", []) or []):
            result["reason"] = "empty_dcards_stack"
            return result

        try:
            card_name = str(self.dcards_stack.pop(0))
        except Exception:
            result["reason"] = "failed_to_draw_card"
            return result

        self._deduct_execution_cost(
            player,
            cost,
            category="dcard",
            message="bought a development card",
            metadata={"card_name": card_name, "human_selected": True},
            source=source,
            reason="human_confirmed_buy_dcard",
        )
        self._add_development_card_to_player(player, card_name)
        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass
        self._refresh_gui_scoreboard_after_dcard_change("after_human_buy_dcard")
        self.emit_twitter_event(getattr(player, "id", None), f"bought a DCard ({card_name})")
        self._play_execution_action_sound(action)

        result.update({"ok": True, "reason": "executed", "card_name": card_name})
        try:
            result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_buy_dcard", result)
        except Exception as exc:
            result["slice_d"] = {"ok": False, "reason": str(exc)}
        self.last_execution_result = result
        return result

    def execute_human_build_city_action(self, target_id: int) -> Dict[str, Any]:
        """Execute a confirmed human Build City action at one owned settlement."""
        action = "Build city"
        source = "human_buy_city"
        try:
            target = int(target_id)
        except Exception:
            target = -1
        result = self._base_human_buy_result(action, source, target_id=target)
        player = self._validate_human_action_selection_context(result)
        if player is None:
            return result

        cost = self._execution_cost_vector_for_action(action)
        if target < 0:
            result["reason"] = "missing_target"
            return result
        if target not in [int(x) for x in list(getattr(player, "settlements", []) or [])]:
            result["reason"] = "target_not_owned_settlement"
            return result
        if not self._can_player_pay_execution_cost(player, cost):
            result["reason"] = "cannot_pay_cost"
            return result

        inter = self.board.intersections[target] if 0 <= target < len(self.board.intersections) else None
        if inter is None:
            result["reason"] = "invalid_intersection"
            return result
        if str(getattr(inter, "color", "") or "") not in {"", str(getattr(player, "color", ""))}:
            result["reason"] = "target_owned_by_other_player"
            return result

        inter.occupied_tf = True
        inter.face = "City"
        inter.color = player.color
        inter.game_round = self.round
        inter.game_turn = self.turn
        try:
            for tile, corner_loc in self.board.intersection_to_corners.get(target, []) or []:
                corner = next((c for c in tile.corners if c.location == corner_loc), None)
                if corner is not None:
                    corner.kind = "City"
                    corner.color = player.color
        except Exception:
            pass

        player.settlements = [sid for sid in list(getattr(player, "settlements", []) or []) if int(sid) != int(target)]
        if target not in list(getattr(player, "cities", []) or []):
            player.cities.append(target)

        self._deduct_execution_cost(
            player,
            cost,
            category="buy",
            message=f"built City @{target}",
            metadata={"target_id": target, "human_selected": True},
            source=source,
            reason="human_confirmed_build_city",
        )
        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass
        self.emit_twitter_event(getattr(player, "id", None), f"built City @{target}")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, target_id=target)

        result.update({"ok": True, "reason": "executed", "target_id": target})
        try:
            result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_build_city", result)
        except Exception as exc:
            result["slice_d"] = {"ok": False, "reason": str(exc)}
        self.last_execution_result = result
        self._post_check_executed_action(
            player,
            {"action": action, "choice": {"candidates": [{"target_id": target}]}},
            result,
        )
        return result

    def execute_human_build_settlement_action(self, target_id: int) -> Dict[str, Any]:
        """Execute a confirmed human Build Settlement action at one legal target."""
        action = "Build settlement"
        source = "human_buy_settlement"
        try:
            target = int(target_id)
        except Exception:
            target = -1
        result = self._base_human_buy_result(action, source, target_id=target)
        player = self._validate_human_action_selection_context(result)
        if player is None:
            return result

        cost = self._execution_cost_vector_for_action(action)
        if target < 0:
            result["reason"] = "missing_target"
            return result
        if not self._can_player_pay_execution_cost(player, cost):
            result["reason"] = "cannot_pay_cost"
            return result
        try:
            if not bool(self.can_build_intersection_tf(target, player)):
                result["reason"] = "not_legal_settlement_target"
                return result
        except Exception:
            result["reason"] = "not_legal_settlement_target"
            return result

        self.board.occupy_intersection(target, "Settlement", player.color)
        if target not in list(getattr(player, "settlements", []) or []):
            player.settlements.append(target)
        self._deduct_execution_cost(
            player,
            cost,
            category="buy",
            message=f"built Settlement @{target}",
            metadata={"target_id": target, "human_selected": True},
            source=source,
            reason="human_confirmed_build_settlement",
        )
        try:
            player.update_trade_rates(self.board)
        except Exception:
            pass
        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass
        self.emit_twitter_event(getattr(player, "id", None), f"built Settlement @{target}")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, target_id=target)

        result.update({"ok": True, "reason": "executed", "target_id": target})
        try:
            result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_build_settlement", result)
        except Exception as exc:
            result["slice_d"] = {"ok": False, "reason": str(exc)}
        self.last_execution_result = result
        self._post_check_executed_action(
            player,
            {"action": action, "choice": {"candidates": [{"target_id": target}]}},
            result,
        )
        return result

    def execute_human_build_road_action(self, road_id: Sequence[int]) -> Dict[str, Any]:
        """Execute a confirmed human Build Road action.

        Human road selection uses the shared viable_action_scanner candidates for
        the visible choices.  This method is the final law: it re-checks phase,
        turn state, resources, board legality, and human-network adjacency before
        mutating the board.
        """
        action = "Build road"
        player = self.get_current_player()
        road = self._road_from_raw_value(road_id)
        cost = self._execution_cost_vector_for_action(action)
        result: Dict[str, Any] = {
            "ok": False,
            "action": action,
            "road_id": list(road) if road is not None else [],
            "reason": "",
            "source": "human_buy_road",
        }

        if str(getattr(self, "phase", "")) != "Execution":
            result["reason"] = "not_execution_phase"
            return result
        if str(getattr(self, "state", "")) != "ActionSelection":
            result["reason"] = f"state_not_action_selection:{getattr(self, 'state', '')}"
            return result
        if player is None:
            result["reason"] = "no_current_player"
            return result
        if road is None:
            result["reason"] = "missing_road"
            return result
        if not self._can_player_pay_execution_cost(player, cost):
            result["reason"] = "cannot_pay_cost"
            return result
        try:
            if not self.board.can_build_road_for_color_tf(list(road), player.color):
                result["reason"] = "not_legal_road"
                return result
        except Exception:
            result["reason"] = "not_legal_road"
            return result
        if not self._road_touches_player_network_without_crossing_opponent(player, road):
            result["reason"] = "road_not_adjacent_to_player_network"
            return result

        self.board.occupy_road(road, "Road", player.color)
        if road not in list(getattr(player, "roads", []) or []):
            player.roads.append(road)

        self._deduct_execution_cost(
            player,
            cost,
            category="buy",
            message=f"built Road {list(road)}",
            metadata={"road_id": list(road), "human_selected": True},
            source="human_buy_road",
            reason="human_confirmed_build_road",
        )

        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass
        self.emit_twitter_event(getattr(player, "id", None), f"built Road [{road[0]},{road[1]}]")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, road_id=road)

        result.update({"ok": True, "reason": "executed", "road_id": list(road)})
        try:
            result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_build_road", result)
        except Exception as exc:
            result["slice_d"] = {"ok": False, "reason": str(exc)}
        self.last_execution_result = result
        self._post_check_human_build_road(player, road)
        return result

    def _road_from_raw_value(self, value: Any) -> Optional[Tuple[int, int]]:
        """Normalize any two-value road id to a sorted tuple."""
        try:
            a, b = tuple(value)[:2]
            return tuple(sorted((int(a), int(b))))
        except Exception:
            return None

    def _road_touches_player_network_without_crossing_opponent(self, player: Player, road: Tuple[int, int]) -> bool:
        """Return True if a road extends this player's own network.

        A candidate may touch one of the player's settlements/cities directly.
        Or it may extend from one of the player's own roads, unless an opponent's
        structure occupies that endpoint and blocks the connection.
        """
        player_color = str(getattr(player, "color", ""))
        try:
            structures = {int(x) for x in list(getattr(player, "settlements", []) or [])}
            structures.update(int(x) for x in list(getattr(player, "cities", []) or []))
        except Exception:
            structures = set()
        owned_roads: List[Tuple[int, int]] = []
        for raw in list(getattr(player, "roads", []) or []):
            normalized = self._road_from_raw_value(raw)
            if normalized is not None:
                owned_roads.append(normalized)

        for endpoint in tuple(road):
            if int(endpoint) in structures:
                return True
            if self._endpoint_has_opponent_structure(int(endpoint), player_color):
                continue
            for owned_road in owned_roads:
                if int(endpoint) in owned_road:
                    return True
        return False

    def _endpoint_has_opponent_structure(self, intersection_id: int, player_color: str) -> bool:
        """Return True if an endpoint is blocked by another player's building."""
        try:
            inter = self.board.intersections[int(intersection_id)]
        except Exception:
            return False
        if inter is None or not bool(getattr(inter, "occupied_tf", False)):
            return False
        return str(getattr(inter, "color", "")) != str(player_color)

    def _post_check_human_build_road(self, player: Player, road: Tuple[int, int]) -> None:
        """Emit DBG lines if a human road build reported OK but did not persist."""
        try:
            if road not in list(getattr(player, "roads", []) or []):
                self.emit_twitter_event(getattr(player, "id", None), f"DBG: Road {list(road)} execution returned ok, but road not in player.roads.")
        except Exception:
            pass
        try:
            found = False
            for road_obj in list(getattr(self.board, "roads", []) or []):
                if tuple(sorted(getattr(road_obj, "id", ()) or ())) == tuple(road):
                    found = bool(getattr(road_obj, "occupied_tf", False)) and str(getattr(road_obj, "color", "")) == str(getattr(player, "color", ""))
                    break
            if not found:
                self.emit_twitter_event(getattr(player, "id", None), f"DBG: Road {list(road)} execution returned ok, but board road/color did not persist.")
        except Exception:
            pass

    def _execute_one_ai_plan_item(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute one concrete buy/build action from a plan/scanner item."""
        action = str(plan_item.get("action", "") or "")
        if action == "Buy development_card":
            return self._execute_ai_buy_dcard(player, plan_item)
        if action == "Build city":
            return self._execute_ai_build_city(player, plan_item)
        if action == "Build settlement":
            return self._execute_ai_build_settlement(player, plan_item)
        if action == "Build road":
            return self._execute_ai_build_road(player, plan_item)
        if action == "TwB":
            return self._execute_ai_twb_support_plan(player, plan_item)
        if action == "TwP":
            return self._execute_ai_twp_support_plan(player, plan_item)
        if action == "Incoming TwP":
            proposal = plan_item.get("proposal") or plan_item.get("twp_proposal") or {}
            decision = plan_item.get("human_twp_policy_decision") or {}
            if isinstance(proposal, Mapping):
                self._set_pending_human_twp_offer(proposal, decision, play_sound=True)
            return {
                "ok": True,
                "action": "Incoming TwP",
                "status": "pending_human_response",
                "reason": "waiting_for_human_twp_manual_response",
                "proposal": dict(proposal or {}) if isinstance(proposal, Mapping) else {},
            }
        return {"ok": False, "action": action or "none", "reason": "no_executable_plan_item"}

    def _execution_target_debug_label(self, plan_item: Mapping[str, Any]) -> str:
        """Return a compact target label for Continue execution DBG lines."""
        action = str(plan_item.get("action", "") or "")
        if action in {"Build city", "Build settlement"}:
            target = self._target_from_plan_item(plan_item)
            return f" @{target}" if target is not None else ""
        if action == "Build road":
            road = self._road_from_plan_item(plan_item)
            if road is None:
                return ""
            base = f" [{road[0]}, {road[1]}]"
            target_label = str(plan_item.get("route_target_label") or "")
            step = plan_item.get("route_step")
            total = plan_item.get("route_steps_total")
            if target_label and step and total:
                base += f" toward {target_label} step {step}/{total}"
            return base
        if action == "TwB":
            try:
                names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]
                give = self._format_twb_amounts(plan_item.get("give", []), names)
                get = self._format_twb_amounts(plan_item.get("get", []), names)
                return f" {give} -> {get}"
            except Exception:
                return ""
        if action == "TwP":
            proposal = plan_item.get("proposal") or plan_item.get("twp_proposal") or plan_item.get("candidate") or {}
            if isinstance(proposal, Mapping):
                label = self._format_twp_proposal_label(proposal)
                return f" {label}" if label else ""
        return ""

    def _post_check_executed_action(self, player: Player, plan_item: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        """Emit a DBG line if a successful mutation did not persist as expected."""
        if not isinstance(result, Mapping) or not bool(result.get("ok")):
            return
        action = str(result.get("action", plan_item.get("action", "")) or "")

        if action == "Build city":
            target = result.get("target_id")
            try:
                target = int(target)
            except Exception:
                target = self._target_from_plan_item(plan_item)
            if target is None:
                return
            try:
                if target not in list(getattr(player, "cities", []) or []):
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: City @{target} execution returned ok, but target not in player.cities.")
                if target in list(getattr(player, "settlements", []) or []):
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: City @{target} execution returned ok, but target still in settlements.")
            except Exception:
                pass
            return

        if action == "Build settlement":
            target = result.get("target_id")
            try:
                target = int(target)
            except Exception:
                target = self._target_from_plan_item(plan_item)
            if target is None:
                return
            try:
                if target not in list(getattr(player, "settlements", []) or []):
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: Settlement @{target} execution returned ok, but target not in player.settlements.")
                inter = self.board.intersections[int(target)]
                if str(getattr(inter, "face", "") or "") != "Settlement" or getattr(inter, "color", None) != player.color:
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: Settlement @{target} board state does not match player after execution.")
            except Exception:
                pass
            return

        if action == "Build road":
            road = self._road_from_plan_item(plan_item)
            if road is None:
                return
            try:
                roads = [self._road_key_from_any(r) for r in list(getattr(player, "roads", []) or [])]
                if road not in roads:
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: Road [{road[0]},{road[1]}] execution returned ok, but road not in player.roads.")
            except Exception:
                pass
            try:
                board_road = next((r for r in list(getattr(self.board, "roads", []) or []) if self._road_key_from_any(getattr(r, "id", None)) == road), None)
                if board_road is not None and getattr(board_road, "color", None) != player.color:
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: Road [{road[0]},{road[1]}] board color does not match player after execution.")
            except Exception:
                pass
            return

    def _first_executable_ai_plan_item(self, plan: Sequence[Any]) -> Optional[Dict[str, Any]]:
        for item in list(plan or []):
            if not isinstance(item, Mapping):
                continue
            if str(item.get("action", "") or "") in {"Buy development_card", "Build city", "Build settlement", "Build road", "TwP", "TwB"}:
                return dict(item)
        return None

    def _short_execution_action_label(self, action: str) -> str:
        """Return a compact action label for debug lines and panels."""
        action = str(action or "")
        if action == "Build city":
            return "City"
        if action == "Build settlement":
            return "Settle"
        if action == "Build road":
            return "Road"
        if action == "Buy development_card":
            return "DCard"
        if action == "TwB":
            return "TwB"
        if action == "TwP":
            return "TwP"
        return action.replace("Build ", "") or "action"

    def _choice_debug_target_label(self, choice: Mapping[str, Any]) -> str:
        """Return a compact target/candidate label for one execution choice."""
        try:
            candidates = list(choice.get("candidates", []) or [])
            if not candidates:
                return ""
            candidate = candidates[0]
            if not isinstance(candidate, Mapping):
                return ""
            action = str(choice.get("action", "") or "")
            if action == "Build road":
                road = candidate.get("road_id") or candidate.get("road") or candidate.get("edge")
                return f" {list(road)}" if road is not None else ""
            target = candidate.get("target_id") or candidate.get("intersection_id") or candidate.get("target")
            return f" @{target}" if target not in (None, "") else ""
        except Exception:
            return ""

    def _preferred_strategy_action_text(self) -> str:
        """Return compact text for the currently preferred strategic action family."""
        actions: List[str] = []
        for row in list(getattr(self, "current_strategic_needs", []) or []):
            if isinstance(row, Mapping):
                action = str(row.get("action", "") or "")
                if action:
                    label = self._short_execution_action_label(action)
                    if label not in actions:
                        actions.append(label)
        return ", ".join(actions) if actions else "current strategy"

    def _current_legal_buy_build_actions(self) -> List[str]:
        """Return executable buy/build actions from the current manager choices."""
        out: List[str] = []
        for row in list(getattr(self, "current_execution_choices", []) or []):
            if isinstance(row, Mapping) and bool(row.get("viable", False)):
                action = str(row.get("action", "") or "")
                if action:
                    out.append(action)
        return out

    def _current_strategy_locked_buy_build_choices(self) -> List[Dict[str, Any]]:
        """Return raw-legal actions intentionally blocked by strategy priority.

        execution_phase_manager.py keeps scan_viable=True when the raw scanner
        found a legal action, but sets strategy_locked=True and viable=False when
        that action is deliberately passed because the planner prefers another
        support action.  These rows are important: they are not execution options,
        but they deserve a DBG line so the pass is understandable.
        """
        locked: List[Dict[str, Any]] = []
        for row in list(getattr(self, "current_execution_choices", []) or []):
            if not isinstance(row, Mapping):
                continue
            if bool(row.get("scan_viable", False)) and bool(row.get("strategy_locked", False)):
                locked.append(dict(row))
        return locked

    def _ai_pass_reason_after_strategy_lock(self) -> str:
        """Explain why the AI Continue plan is Pass / End turn."""
        locked = self._current_strategy_locked_buy_build_choices()
        if locked:
            first = locked[0]
            action = self._short_execution_action_label(str(first.get("action", "") or ""))
            preferred = self._preferred_strategy_action_text()
            return f"Legal {action} skipped; preferred strategy is {preferred}."
        return "No legal buy/build action after the dice roll."

    def _emit_ai_legal_not_chosen_debug(self, player: Player, executed_action: str = "") -> Optional[str]:
        """Emit one concise DBG line when an action is intentionally not chosen.

        Two cases matter:
        1. A normal legal action exists but is not chosen.
        2. A raw-legal action exists but was deliberately strategy-locked because
           the planner prefers another support action.  This is the important
           transparency line discussed earlier: a pass is OK, but the Events
           panel must say why.
        """
        legal = self._current_legal_buy_build_actions()
        skipped = [action for action in legal if action and action != executed_action]
        if skipped:
            first = "Buy development_card" if "Buy development_card" in skipped else skipped[0]
            short = self._short_execution_action_label(first)
            if executed_action:
                message = f"DBG: {short} legal, not chosen; executed {executed_action}."
            else:
                message = f"DBG: {short} legal, not chosen; pass."
            self.emit_twitter_event(getattr(player, "id", None), message[:180])
            return message

        locked = self._current_strategy_locked_buy_build_choices()
        if locked:
            first = locked[0]
            short = self._short_execution_action_label(str(first.get("action", "") or ""))
            target = self._choice_debug_target_label(first)
            preferred = self._preferred_strategy_action_text()
            if executed_action:
                message = f"DBG: {short}{target} legal but skipped; preferred {preferred}; executed {executed_action}."
            else:
                message = f"DBG: {short}{target} legal but skipped; preferred {preferred}; pass."
            self.emit_twitter_event(getattr(player, "id", None), message[:180])
            return message

        if not executed_action:
            message = "DBG: no legal buy/build action after roll; pass."
            self.emit_twitter_event(getattr(player, "id", None), message)
            return message
        return None

    def _freeze_completed_turn_details_for_scoreboard(self) -> None:
        """Store current turn-detail rows before advance_turn() starts the next turn."""
        rows_by_player: Dict[int, List[Tuple[str, List[int]]]] = {}
        for player in list(getattr(self, "players", []) or []):
            try:
                rows = []
                for label, vector in list(self.get_turn_detail_rows_for_player(player) or []):
                    vec = list(vector or [])[:6]
                    vec = vec + [0] * max(0, 6 - len(vec))
                    if any(int(x or 0) != 0 for x in vec):
                        rows.append((str(label), [int(x or 0) for x in vec]))
                if rows:
                    rows_by_player[int(getattr(player, "id", 0) or 0)] = rows
            except Exception:
                pass
        try:
            dice_roll = getattr(self, "dice_roll", None)
            dice_total = int(sum(dice_roll)) if isinstance(dice_roll, (list, tuple)) else int(dice_roll or 0)
        except Exception:
            dice_total = 0
        self.last_completed_turn_detail_rows_by_player = rows_by_player
        self.last_completed_turn_detail_context = {
            "round": int(getattr(self, "round", 0) or 0),
            "turn": int(getattr(self, "turn", 0) or 0),
            "dice_roll": getattr(self, "dice_roll", None),
            "dice_total": dice_total,
            "is_robber_roll": dice_total == 7,
            "current_player_id": int(getattr(self.get_current_player(), "id", 0) or 0),
        }

    def continue_ai_execution_turn(self) -> Dict[str, Any]:
        """AI Continue step for Slice C2/C2R.

        Normal AI turn:
            Play -> roll dice / preview
            Continue -> execute one legal buy/build action or pass, then advance.

        Rolled-7 AI turn:
            Play -> roll 7 / preview robber
            Continue #1 -> resolve robber/steal and stay on the same player
            Continue #2 -> execute one legal buy/build action or pass, then advance.
        """
        player = self.get_current_player()
        if not self.ai_continue_is_available():
            result = {
                "ok": False,
                "reason": "continue_not_available",
                "phase": getattr(self, "phase", None),
                "state": getattr(self, "state", None),
                "dice_roll": getattr(self, "dice_roll", None),
                "player_id": getattr(player, "id", None) if player is not None else None,
            }
            self.last_ai_continue_result = result
            return result

        if player is None:
            result = {"ok": False, "reason": "no_current_player"}
            self.last_ai_continue_result = result
            return result

        plan_before = list(getattr(self, "current_ai_execution_plan", []) or self._build_ai_continue_plan())
        robber_result = None
        executed_result: Optional[Dict[str, Any]] = None

        state = str(getattr(self, "state", "") or "")
        pending_7 = getattr(self, "pending_seven_roll", {}) or {}
        forced_robber = state in {"MoveRobber", "RobberMoveRequired", "SetRobber", "StealSelectOpponent"} or (isinstance(pending_7, dict) and pending_7.get("active"))

        if forced_robber:
            try:
                robber_result = self.execute_basic_robber_strategy(execute_steal=True)
            except TypeError:
                robber_result = self.execute_basic_robber_strategy()
            except Exception as exc:
                robber_result = {"ok": False, "error": str(exc)}

            # Important: resolving robber is only the first Continue checkpoint for
            # a rolled-7 AI turn.  Do not advance yet.  Slice D re-scans now so a
            # city/buy/build action that is possible after the steal can appear in
            # the panel and be executed by the next Continue click.
            try:
                slice_d_result = self.continue_action_selection_after_action(
                    "after_basic_robber_strategy",
                    player=player,
                    action_result={"action": "Resolve robber", "ok": True, "robber_result": robber_result},
                    clear_forced_locks=True,
                )
            except Exception as exc:
                slice_d_result = {"ok": False, "reason": str(exc)}
                try:
                    if isinstance(getattr(self, "pending_seven_roll", None), dict):
                        self.pending_seven_roll["active"] = False
                    if isinstance(getattr(self, "pending_robber_steal", None), dict):
                        self.pending_robber_steal["active"] = False
                        self.pending_robber_steal["awaiting_human_target"] = False
                    self.state = "ActionSelection"
                    self.state_1 = ""
                    self.state_2 = ""
                    self._mark_ai_preview_ready(reason="after_basic_robber_strategy")
                except Exception:
                    pass

            result = {
                "ok": True,
                "action": "AI Continue",
                "player_id": getattr(player, "id", None),
                "plan_preview_before_continue": plan_before,
                "executed_result": {},
                "robber_result": robber_result,
                "debug_pass_message": None,
                "advance_turn": False,
                "slice_d": slice_d_result,
                "note": "Robber/steal resolved. Press Continue again to execute buy/build or pass.",
            }
            self.last_ai_continue_result = result
            self.last_execution_result = result
            return result

        # Do not rescan here.  Continue must execute the canonical BEST NOW
        # object that was frozen by the latest refresh_viable_actions() call and
        # displayed in Execution Debug.  A click-time rescan can reorder city
        # candidates and cause a displayed target like @40 to execute as @26.
        plan_item = self.get_current_best_executable_action()
        execution_source = "canonical_best_now" if plan_item is not None else "preview_plan_fallback"
        if plan_item is None:
            plan_item = self._first_executable_ai_plan_item(plan_before)

        if plan_item is not None and str(plan_item.get("action", "") or "") == "End turn":
            reason = str(plan_item.get("reason") or "No executable BEST NOW action.")
            self.emit_twitter_event(
                getattr(player, "id", None),
                f"DBG: {reason} pass."[:180],
            )
            executed_result = {"ok": True, "action": "End turn", "reason": reason}
            execution_source = str(plan_item.get("source") or execution_source)
        elif plan_item is not None:
            action_label = str(plan_item.get("action", "") or "action")
            target_label = self._execution_target_debug_label(plan_item)
            self.emit_twitter_event(
                getattr(player, "id", None),
                f"DBG: Continue executing {action_label}{target_label}.",
            )
            executed_result = self._execute_one_ai_plan_item(player, plan_item)
            if not bool(executed_result.get("ok")):
                self.emit_twitter_event(
                    getattr(player, "id", None),
                    f"DBG: planned {executed_result.get('action')} not executed ({executed_result.get('reason')}); pass.",
                )
            else:
                self._post_check_executed_action(player, plan_item, executed_result)
        else:
            executed_result = {"ok": True, "action": "End turn", "reason": "no_executable_plan_item"}
            execution_source = "pass"

        if (
            isinstance(executed_result, Mapping)
            and str(executed_result.get("action", "") or "") == "Incoming TwP"
            and str(executed_result.get("status", "") or "") == "pending_human_response"
        ):
            result = {
                "ok": True,
                "action": "AI Continue",
                "player_id": getattr(player, "id", None),
                "plan_preview_before_continue": plan_before,
                "executed_result": dict(executed_result or {}),
                "robber_result": robber_result,
                "debug_pass_message": None,
                "advance_turn": False,
                "execution_source": execution_source,
                "slice_d": None,
                "note": "Incoming TwP offer is waiting for HP ACCEPT/DECLINE.",
            }
            self.last_ai_continue_result = result
            self.last_execution_result = result
            try:
                self.ai_execution_stage = "waiting_for_human_twp_response"
            except Exception:
                pass
            return result

        executed_action = ""
        if isinstance(executed_result, Mapping) and bool(executed_result.get("ok")):
            action_name = str(executed_result.get("action", "") or "")
            if action_name in {"Buy development_card", "Build city", "Build settlement", "Build road"}:
                executed_action = action_name
            else:
                followup = executed_result.get("followup_result", {})
                if isinstance(followup, Mapping):
                    followup_action = str(followup.get("action", "") or "")
                    if followup_action in {"Buy development_card", "Build city", "Build settlement", "Build road"}:
                        executed_action = followup_action

        debug_pass_message = self._emit_ai_legal_not_chosen_debug(player, executed_action=executed_action)

        executed_action_name = str((executed_result or {}).get("action", "") or "")
        should_end_turn = executed_action_name == "End turn" or not bool((executed_result or {}).get("ok"))

        slice_d_result = None
        if not should_end_turn:
            try:
                slice_d_result = self.continue_action_selection_after_action(
                    f"after_ai_{executed_action_name.strip().lower().replace(' ', '_') or 'action'}",
                    player=player,
                    action_result=dict(executed_result or {}),
                    clear_forced_locks=True,
                )
            except Exception as exc:
                slice_d_result = {"ok": False, "reason": str(exc)}

        result = {
            "ok": True,
            "action": "AI Continue",
            "player_id": getattr(player, "id", None),
            "plan_preview_before_continue": plan_before,
            "executed_result": dict(executed_result or {}),
            "robber_result": robber_result,
            "debug_pass_message": debug_pass_message,
            "advance_turn": bool(should_end_turn),
            "execution_source": execution_source,
            "slice_d": slice_d_result,
            "note": (
                "Slice D: Continue executed one action, rescanned, and left the AI on the same turn for the next Continue."
                if not should_end_turn
                else "Slice D: no executable continuation remained, so Continue ended the turn."
            ),
        }
        self.last_ai_continue_result = result
        self.last_execution_result = result

        if should_end_turn:
            self._freeze_completed_turn_details_for_scoreboard()
            self.ai_execution_preview_ready = False
            self.ai_execution_stage = "continued_end_turn"
            self.current_ai_execution_plan = []
            self.current_ai_decision_trace = []
            self.advance_turn()
        else:
            try:
                self.ai_execution_stage = "preview_ready_after_action"
            except Exception:
                pass
        return result

    def plan_basic_robber_action(self, preferred_opponent_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Build a basic robber placement / steal-opponent plan.

        This does not mutate the board. It is useful for AI/debug before calling
        execute_basic_robber_strategy() or execute_move_robber_action(...).
        """
        if self.phase != "Execution":
            raise RuntimeError("Cannot plan robber action outside the Execution phase.")

        from core.game_7logic import plan_basic_robber_action

        player = self.get_current_player()
        plan = plan_basic_robber_action(
            self,
            player,
            preferred_opponent_id=preferred_opponent_id,
        )
        self.last_robber_plan = plan
        return plan

    def execute_basic_robber_strategy(
        self,
        preferred_opponent_id: Optional[int] = None,
        *,
        execute_steal: bool = False,
    ) -> Dict[str, Any]:
        """
        Plan and execute a basic robber move.

        First implementation:
        - choose a tile using simple production-pain scoring;
        - choose an adjacent opponent to steal from;
        - move robber;
        - optionally execute one random steal when execute_steal=True.
        """
        if self.phase != "Execution":
            raise RuntimeError("Cannot execute robber strategy outside the Execution phase.")

        from core.game_7logic import execute_basic_robber_strategy

        player = self.get_current_player()
        result = execute_basic_robber_strategy(
            self,
            player,
            preferred_opponent_id=preferred_opponent_id,
            execute_steal=execute_steal,
        )
        self.last_robber_plan = result.get("plan")
        self.last_robber_move_result = result.get("move")
        self.last_robber_steal_result = result.get("steal")
        self.last_execution_result = {
            "action": "Basic robber strategy",
            "player_id": getattr(player, "id", None),
            "result": result,
            "state_after": self.state,
        }
        self.refresh_strategy_context("after_basic_robber_strategy", force=True)
        self.refresh_viable_actions("execute_basic_robber_strategy")
        return result

    def execute_move_robber_action(
        self,
        tile_id: int,
        opponent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute a robber move after a 7 or Knight.

        If opponent_id is provided, that opponent is preselected when valid.
        If opponent_id is omitted, game_7logic chooses a basic steal target.
        """
        if self.phase != "Execution":
            raise RuntimeError("Cannot move robber outside the Execution phase.")

        from core.game_7logic import move_robber_basic

        player = self.get_current_player()
        result = move_robber_basic(
            self,
            player,
            int(tile_id),
            opponent_id=opponent_id,
        )
        self.last_robber_move_result = result
        self.last_execution_result = {
            "action": "Move robber",
            "player_id": getattr(player, "id", None),
            "tile_id": int(tile_id),
            "opponent_id": opponent_id,
            "robber_result": result,
            "state_after": self.state,
        }

        self.refresh_viable_actions("execute_move_robber_action")
        return result

    def execute_select_steal_opponent_action(
        self,
        opponent_id: int,
        *,
        execute_steal: bool = False,
    ) -> Dict[str, Any]:
        """
        Select an opponent after the robber has moved.

        If execute_steal=True, immediately execute one random steal.
        Otherwise the state becomes StealPickRCard and the scanner exposes the
        pick-card step.
        """
        if self.phase != "Execution":
            raise RuntimeError("Cannot select steal opponent outside the Execution phase.")

        from core.game_7logic import select_robber_steal_opponent_basic, steal_random_resource_basic

        player = self.get_current_player()
        select_result = select_robber_steal_opponent_basic(self, player, int(opponent_id))
        steal_result = None
        if execute_steal and select_result.get("ok"):
            steal_result = steal_random_resource_basic(self, player, int(opponent_id))

        result = {
            "ok": bool(select_result.get("ok")) and (steal_result is None or bool(steal_result.get("ok"))),
            "select": select_result,
            "steal": steal_result,
            "state_after": self.state,
        }
        self.last_robber_steal_selection = select_result
        self.last_robber_steal_result = steal_result
        self.last_execution_result = {
            "action": "Steal - Select Opponent",
            "player_id": getattr(player, "id", None),
            "opponent_id": int(opponent_id),
            "result": result,
            "state_after": self.state,
        }
        self.refresh_viable_actions("execute_select_steal_opponent_action")
        return result

    def execute_robber_random_steal_action(self, opponent_id: Optional[int] = None) -> Dict[str, Any]:
        """Execute one random resource steal from the selected/passed opponent."""
        if self.phase != "Execution":
            raise RuntimeError("Cannot steal outside the Execution phase.")

        from core.game_7logic import steal_random_resource_basic

        player = self.get_current_player()
        result = steal_random_resource_basic(self, player, opponent_id)
        self.last_robber_steal_result = result
        self.last_execution_result = {
            "action": "Steal - Pick rcard",
            "player_id": getattr(player, "id", None),
            "opponent_id": opponent_id,
            "result": result,
            "state_after": self.state,
        }
        self.refresh_viable_actions("execute_robber_random_steal_action")
        return result

    def resume_action_selection_after_human_robber_flow(self, reason: str = "after_human_robber_flow") -> Dict[str, Any]:
        """Return a human player to normal ActionSelection after a resolved 7-flow.

        This is now a small compatibility wrapper around Slice D.  Rolling a 7
        forces robber movement and possibly a steal, but it does not end the
        player's turn.  Once the forced work is complete, Slice D clears robber
        locks, refreshes strategy/scanner output, and keeps the same player active.
        """
        return self.continue_action_selection_after_action(
            str(reason or "after_human_robber_flow"),
            player=self.get_current_player(),
            action_result={"action": "Resolve robber", "ok": True},
            clear_forced_locks=True,
        )

    def rescan_after_action_execution(self, reason: str = ""):
        """
        Call this after any exact action executor mutates the real game.
        """
        if self.phase != "Execution":
            return None

        player = self.get_current_player()
        if player is not None:
            self.update_strategy_dashboard(player)

        self.refresh_strategy_context(reason or "action_executed", force=True)
        return self.refresh_viable_actions(reason or "action_executed")

    def advance_turn(self) -> None:
        """Advance to the next player's turn and update game state.

        Handles the initial placement sequence (1,2,3,4,4,3,2,1)
        and transitions to Execution phase. When an Execution turn starts,
        refresh the scanner so Roll Dices becomes the first viable action.
        """
        print("game.advance_turn executed")
        # Leaving the current turn invalidates any AI preview checkpoint.
        self.ai_execution_preview_ready = False
        self.ai_execution_preview_player_id = None
        self.ai_execution_stage = ""
        self.current_ai_execution_plan = []
        self.current_ai_decision_trace = []
        try:
            self.pending_human_twp_offer = None
            self.human_twp_accepted_this_turn = set()
            self.human_twp_declined_this_turn = set()
        except Exception:
            pass
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{self.id} | {self.state} | game.py | advance_turn\n")

        entered_execution = False

        if self.phase == "InitialPlacement":
            if self.round == -2:
                self.turn += 1
                if self.turn > 4:
                    self.round = -1
                    self.turn = 4

            elif self.round == -1:
                self.turn -= 1
                if self.turn < 1:
                    self.round = 1
                    self.turn = 1
                    self.phase = "Execution"
                    self.game_over = False
                    entered_execution = True

                    # Initial placement has just completed. Save a full game
                    # snapshot immediately so test.py can load this position.
                    self.sync_round_turn()
                    saved_game_name = self.save_game()
                    if MG:
                        with open(FILENAME_MG, "a", encoding="utf-8") as f:
                            f.write(
                                "game.py | advance_turn | saved game after "
                                f"initial placement: {saved_game_name}\n"
                            )

                    self.save_screenshot()

        else:
            self.turn = (self.turn % len(self.players)) + 1
            if self.turn == 1:
                self.round += 1

            if self.phase == "Execution":
                entered_execution = True

        self.sync_round_turn()
        self.get_current_player()

        if self.gui is not None:
            self.gui.update_round_turn(self, special=False)

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(
                    f"game.py | advance_turn | Round: {self.round}, "
                    f"Turn: {self.turn}, Phase: {self.phase}\n"
                )

        if entered_execution and self.phase == "Execution":
            self.begin_execution_turn()

    def start_execution_phase(self) -> None:
        """Start of Execution Phase - re-calculate best strategy for ALL AI players (complete function)."""
        self.phase = "Execution"
        
        # Re-calculate strategy for every AI player at start of Round 1 / Execution
        for player in self.players:
            if getattr(player, "is_human", False) is False:  # Only AI players
                try:
                    planner = ActionPlanner(self)
                    preferred = planner.get_best_action(player)
                    # Persist
                    setattr(player, "strategic_direction", preferred)
                    history = list(getattr(player, "strategic_direction_history", []) or [])
                    history.append(preferred)
                    setattr(player, "strategic_direction_history", history[-20:])
                except Exception as e:
                    print(f"Strategy recalc for player {getattr(player, 'id', '?')} failed: {e}")
        
        # Refresh for current player (with FEAS)
        self.refresh_strategy_context("start_execution_phase")
        
        print(f"Execution Phase started (Round {getattr(self, 'round', '?')}) - strategy re-calculated for all AI players.")

    def update_strategy_dashboard(self, player: Player) -> None:
        """Sync StrategyDashboard with the current real player state.

        Call this after every settlement/city/road build or resource change.
        """
        for sd in self.strategy_dashboard:
            if sd.player_id == player.id:
                sd.number_of_settlements = len(player.settlements)
                sd.number_of_cities      = len(player.cities)
                sd.number_of_rcards      = player.number_of_rcards
                sd.number_of_dcards      = player.number_of_dcards
                sd.victory_points        = player.recalculate_victory_points()
                sd.victory_points_dcard  = self._player_dcard_vp_count(player)
                # sd.longest_road = ...                           # update only when longest road changes
                # sd.largest_army = ...                           # update only when largest army changes
                break

    def log_event(self, event: List) -> None:
        """Log a game event to FILENAME_MGlog in CSV format.

        Args:
            event: List of [index, value] pairs for logging (indices 1-33).
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{self.id} | {self.state} | game.py | log_event\n")

        with open(FILENAME_MGLOG, "a") as f:
            x = 2
            for i in event:
                if i[0] == 1:
                    log = str(i[1])
                    f.write(f'"{log}",')
                elif i[0] == x:
                    x += 1
                    f.write(str(i[1]) + ",")
                elif i[0] > x:
                    for y in range(x, i[0]):
                        f.write(",")
                    x = i[0] + 1
                    f.write(str(i[1]))
                    if i[0] == 33:
                        continue
                    f.write(",")
            for y in range(x, 34):
                f.write(",")
            f.write("\n")

    def save_screenshot(self) -> None:
        """Save a screenshot of the game window via the GUI."""
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{self.id} | {self.state} | game.py | save_screenshot\n")
        self.gui.save_screenshot()


    def _json_safe(self, value: Any) -> Any:
        """Convert common game objects into JSON-serializable values."""
        if isinstance(value, ResourceCard):
            return value.value
        if isinstance(value, tuple):
            return [self._json_safe(v) for v in value]
        if isinstance(value, list):
            return [self._json_safe(v) for v in value]
        if isinstance(value, dict):
            safe_dict: Dict[str, Any] = {}
            for key, item in value.items():
                safe_key = key.value if isinstance(key, ResourceCard) else str(key)
                safe_dict[safe_key] = self._json_safe(item)
            return safe_dict
        if hasattr(value, "__dict__") and value.__class__.__module__ != "builtins":
            return {
                key: self._json_safe(item)
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _player_id_or_none(self, player: Optional[Player]) -> Optional[int]:
        """Return a player's id, or None for absent special-player fields."""
        return getattr(player, "id", None) if player is not None else None

    def _player_by_id(self, player_id: Optional[int]) -> Optional[Player]:
        """Return a player object by id, or None."""
        if player_id is None:
            return None
        for player in self.players:
            if getattr(player, "id", None) == player_id:
                return player
        return None

    def _save_strategy_dashboard(self) -> List[Dict[str, Any]]:
        """Serialize StrategyDashboard rows."""
        return [self._json_safe(vars(item)) for item in getattr(self, "strategy_dashboard", [])]

    def _load_strategy_dashboard(self, rows: Any) -> None:
        """Restore StrategyDashboard rows, defaulting missing values."""
        if not isinstance(rows, list):
            return
        restored: List[StrategyDashboard] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            restored.append(StrategyDashboard(
                player_id=int(row.get("player_id", len(restored) + 1)),
                victory_points=int(row.get("victory_points", 0)),
                number_of_settlements=int(row.get("number_of_settlements", 0)),
                number_of_cities=int(row.get("number_of_cities", 0)),
                victory_points_dcard=int(row.get("victory_points_dcard", 0)),
                longest_road=int(row.get("longest_road", 0)),
                largest_army=int(row.get("largest_army", 0)),
                number_of_rcards=int(row.get("number_of_rcards", 0)),
                number_of_dcards=int(row.get("number_of_dcards", 0)),
                distribution_of_tile_values=str(row.get("distribution_of_tile_values", "00000X00000")),
                distribution_of_tile_types=str(row.get("distribution_of_tile_types", "000000")),
            ))
        if restored:
            self.strategy_dashboard = restored

    def _save_resource_card_dashboard(self) -> List[Dict[str, Any]]:
        """Serialize ResourceCardDashboard rows."""
        return [self._json_safe(vars(item)) for item in getattr(self, "resource_card_dashboard", [])]

    def _load_resource_card_dashboard(self, rows: Any) -> None:
        """Restore ResourceCardDashboard rows, defaulting missing values."""
        if not isinstance(rows, list):
            return
        restored: List[ResourceCardDashboard] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            restored.append(ResourceCardDashboard(
                resource_production_game_total=row.get("resource_production_game_total", [0, 0, 0, 0, 0, 0]),
                resource_production_game_player=row.get(
                    "resource_production_game_player",
                    [[1, 0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0, 0], [3, 0, 0, 0, 0, 0, 0], [4, 0, 0, 0, 0, 0, 0]],
                ),
                resource_production_game_player_view=row.get("resource_production_game_player_view", []),
            ))
        if restored:
            self.resource_card_dashboard = restored

    def _save_turn_details(self) -> Dict[str, Any]:
        """Serialize current TurnDetails."""
        return self._json_safe(vars(self.myturn))

    def _load_turn_details(self, data: Any) -> None:
        """Restore current TurnDetails values when present."""
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if hasattr(self.myturn, key):
                setattr(self.myturn, key, value)

    def _save_turn_event_ledger(self) -> Dict[str, Any]:
        """Serialize the structured turn-event ledger."""
        ledger = self._ensure_turn_event_ledger()
        if ledger is not None and hasattr(ledger, "to_dict"):
            try:
                return ledger.to_dict()
            except Exception:
                return {}
        return {}

    def _load_turn_event_ledger(self, data: Any) -> None:
        """Restore the structured turn-event ledger when available."""
        if TurnEventLedger is None:
            self.turn_event_ledger = None
            return
        if isinstance(data, dict) and hasattr(TurnEventLedger, "from_dict"):
            try:
                self.turn_event_ledger = TurnEventLedger.from_dict(data)
            except Exception:
                self.turn_event_ledger = TurnEventLedger()
        else:
            self.turn_event_ledger = TurnEventLedger()
        try:
            self.turn_event_ledger.start_turn(int(getattr(self, "round", 0)), int(getattr(self, "turn", 0)))
        except Exception:
            pass

    def save_game(self, filename: str = "") -> str:
        """
        Save the complete game state to a Saved_Game txt file.

        Filename format when filename is omitted:
            Saved_Game_23_Apr_2025_09_53_50_R2T1.txt

        The saved file is JSON inside a .txt file. It contains game state,
        board state, player state, dashboards, turn details, development-card
        stack, dice history, robber state, and outlook/common-target state.
        """
        timestamp = datetime.now().strftime("%d_%b_%Y_%H_%M_%S")
        if not filename:
            filename = f"Saved_Game_{timestamp}_R{self.round}T{self.turn}.txt"

        for player in self.players:
            player.recalculate_victory_points()
            self.update_strategy_dashboard(player)

        payload: Dict[str, Any] = {
            "schema": "CatanSavedGame",
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "filename": filename,
            "game": {
                "sequence_number": self.sequence_number,
                "id": self.id,
                "time_ended": self.time_ended,
                "phase": self.phase,
                "state": self.state,
                "state_1": self.state_1,
                "state_2": self.state_2,
                "round": self.round,
                "turn": self.turn,
                "dice_roll": self._json_safe(self.dice_roll),
                "dice_rolls": self._json_safe(self.dice_rolls),
                "dice_roll_history": self._json_safe(self.dice_roll_history),
                "dice_roll_matrix": self._json_safe(self.dice_roll_matrix),
                "dcards_stack": self._json_safe(self.dcards_stack),
                "robber_tile_probabilities": self._json_safe(self.robber_tile_probabilities),
                "previous_tile_having_robber": self._json_safe(self.previous_tile_having_robber),
                "list_of_tiles_having_robber": self._json_safe(self.list_of_tiles_having_robber),
                "last_total_turn_with_dr7": self.last_total_turn_with_dr7,
                "settings_tf": self.settings_tf,
                "settings": self._json_safe(vars(self.settings)),
                "initial_placement_balanced": self._json_safe(self.initial_placement_balanced),
                "initial_placement_wood_brick": self._json_safe(self.initial_placement_wood_brick),
                "initial_placement_wheat_ore": self._json_safe(self.initial_placement_wheat_ore),
                "initial_placement_wheat_ore_sheep": self._json_safe(self.initial_placement_wheat_ore_sheep),
                "initial_placement_monopoly": self._json_safe(self.initial_placement_monopoly),
                "resource_production_probability": self._json_safe(self.resource_production_probability),
                "tile_type": self._json_safe(self.tile_type),
                "resource_type_available": self._json_safe(self.resource_type_available),
                "resource_type_occupied": self._json_safe(self.resource_type_occupied),
                "resource_type_players": self._json_safe(self.resource_type_players),
                "players_impacted": self._json_safe(self.players_impacted),
                "common_next_settlements": self._json_safe(self.common_next_settlements),
                "common_new_settlements": self._json_safe(self.common_new_settlements),
                "common_next_roads": self._json_safe(self.common_next_roads),
                "last_known_strategies": self._json_safe(self.last_known_strategies),
                "last_known_outlooks": self._json_safe(self.last_known_outlooks),
                "current_player_id": self._player_id_or_none(self.current_player),
                "winner_id": self._player_id_or_none(self.winner),
                "game_over": self.game_over,
                "longest_road_player_id": self._player_id_or_none(self.longest_road_player),
                "largest_army_player_id": self._player_id_or_none(self.largest_army_player),
            },
            "board": self.board.save_game_board_state(),
            "players": [player.save_player() for player in self.players],
            "strategy_dashboard": self._save_strategy_dashboard(),
            "resource_card_dashboard": self._save_resource_card_dashboard(),
            "turn_details": self._save_turn_details(),
            "turn_event_ledger": self._save_turn_event_ledger(),
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        print(f"✅ Saved game to {filename}")
        return filename

    def load_game(self, filename: str, *, strict: bool = True) -> Dict[str, Any]:
        """
        Load a full game state created by save_game().

        Delegation:
            - Player state is restored via Player.load_player(...).
            - Board state is restored via Board.load_game_board_state(...).

        Missing fields are given safe defaults so older saved games remain
        loadable. After loading, this method refreshes dashboards, trade rates,
        round/turn mirrors, and optional Markov evaluator state.
        """
        try:
            with open(filename, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            if strict:
                raise
            return {"ok": False, "errors": [f"Saved game not found: {filename}"], "warnings": []}

        if not isinstance(payload, dict) or payload.get("schema") != "CatanSavedGame":
            message = f"{filename!r} is not a Catan Saved_Game file."
            if strict:
                raise ValueError(message)
            return {"ok": False, "errors": [message], "warnings": []}

        game_data = payload.get("game", {}) if isinstance(payload.get("game", {}), dict) else {}

        self.sequence_number = int(game_data.get("sequence_number", self.sequence_number))
        self.id = str(game_data.get("id", self.id))
        self.time_ended = game_data.get("time_ended", self.time_ended)
        self.phase = str(game_data.get("phase", self.phase))
        self.state = str(game_data.get("state", self.state))
        self.state_1 = str(game_data.get("state_1", self.state_1))
        self.state_2 = str(game_data.get("state_2", self.state_2))
        self.round = int(game_data.get("round", self.round))
        self.turn = int(game_data.get("turn", self.turn))
        self.dice_roll = tuple(game_data["dice_roll"]) if isinstance(game_data.get("dice_roll"), list) else game_data.get("dice_roll", self.dice_roll)
        self.dice_rolls = [tuple(x) if isinstance(x, list) else x for x in game_data.get("dice_rolls", self.dice_rolls)]
        self.dice_roll_history = game_data.get("dice_roll_history", self.dice_roll_history)
        self.dice_roll_matrix = game_data.get("dice_roll_matrix", self.dice_roll_matrix)
        self.dcards_stack = game_data.get("dcards_stack", self.dcards_stack)
        self.robber_tile_probabilities = game_data.get("robber_tile_probabilities", self.robber_tile_probabilities)
        self.previous_tile_having_robber = game_data.get("previous_tile_having_robber", self.previous_tile_having_robber)
        self.list_of_tiles_having_robber = game_data.get("list_of_tiles_having_robber", self.list_of_tiles_having_robber)
        self.last_total_turn_with_dr7 = int(game_data.get("last_total_turn_with_dr7", self.last_total_turn_with_dr7))
        self.settings_tf = bool(game_data.get("settings_tf", self.settings_tf))

        settings_data = game_data.get("settings", {})
        if isinstance(settings_data, dict):
            for key, value in settings_data.items():
                if hasattr(self.settings, key):
                    setattr(self.settings, key, value)

        self.initial_placement_balanced = game_data.get("initial_placement_balanced", self.initial_placement_balanced)
        self.initial_placement_wood_brick = game_data.get("initial_placement_wood_brick", self.initial_placement_wood_brick)
        self.initial_placement_wheat_ore = game_data.get("initial_placement_wheat_ore", self.initial_placement_wheat_ore)
        self.initial_placement_wheat_ore_sheep = game_data.get("initial_placement_wheat_ore_sheep", self.initial_placement_wheat_ore_sheep)
        self.initial_placement_monopoly = game_data.get("initial_placement_monopoly", self.initial_placement_monopoly)
        self.resource_production_probability = game_data.get("resource_production_probability", self.resource_production_probability)
        self.tile_type = game_data.get("tile_type", self.tile_type)
        self.resource_type_available = game_data.get("resource_type_available", self.resource_type_available)
        self.resource_type_occupied = game_data.get("resource_type_occupied", self.resource_type_occupied)
        self.resource_type_players = game_data.get("resource_type_players", self.resource_type_players)
        self.players_impacted = game_data.get("players_impacted", self.players_impacted)
        self.common_next_settlements = game_data.get("common_next_settlements", self.common_next_settlements)
        self.common_new_settlements = game_data.get("common_new_settlements", self.common_new_settlements)
        self.common_next_roads = [tuple(x) if isinstance(x, list) else x for x in game_data.get("common_next_roads", self.common_next_roads)]
        self.last_known_strategies = game_data.get("last_known_strategies", self.last_known_strategies)
        self.last_known_outlooks = game_data.get("last_known_outlooks", self.last_known_outlooks)
        self.game_over = bool(game_data.get("game_over", self.game_over))

        players_payload = payload.get("players", [])
        if isinstance(players_payload, list):
            existing_by_id = {player.id: player for player in self.players}
            for player_data in players_payload:
                if not isinstance(player_data, dict):
                    continue
                try:
                    player_id = int(player_data.get("id"))
                except Exception:
                    continue
                player = existing_by_id.get(player_id)
                if player is None:
                    player = Player(
                        id_=player_id,
                        color=str(player_data.get("color", "Blue")),
                        sequence=int(player_data.get("sequence", player_id)),
                        is_human=bool(player_data.get("is_human", False)),
                        initial_placement_algorithm=int(player_data.get("initial_placement_algorithm", 1)),
                        human_like_placement=bool(player_data.get("human_like_placement", False)),
                    )
                    self.players.append(player)
                player.game = self
                player.load_player(player_data, board=self.board)

        for player in self.players:
            player.recalculate_victory_points()
            self.update_strategy_dashboard(player)

        board_result = self.board.load_game_board_state(payload.get("board", {}), players=self.players, strict=strict)
        self.board.round = self.round
        self.board.turn = self.turn

        for player in self.players:
            player.recalculate_victory_points()
            self.update_strategy_dashboard(player)

        # Player object references must be resolved after all players exist.
        self.current_player = self._player_by_id(game_data.get("current_player_id"))
        self.winner = self._player_by_id(game_data.get("winner_id"))
        self.longest_road_player = self._player_by_id(game_data.get("longest_road_player_id"))
        self.largest_army_player = self._player_by_id(game_data.get("largest_army_player_id"))

        self._load_strategy_dashboard(payload.get("strategy_dashboard"))
        self._load_resource_card_dashboard(payload.get("resource_card_dashboard"))
        self._load_turn_details(payload.get("turn_details"))
        self._load_turn_event_ledger(payload.get("turn_event_ledger"))

        for player in self.players:
            player.game = self
            try:
                player.update_trade_rates(self.board)
            except Exception:
                pass
            self.update_strategy_dashboard(player)

        self.sync_round_turn()

        # Runtime-only execution manager / scanner / 7-flow state is rebuilt after load.
        self._execution_phase_manager = None
        self.current_viable_action_scan = None
        self.current_execution_choices = []
        self.current_strategic_needs = []
        self.current_actionable_choices = []
        self.current_best_now_action = None
        self.last_execution_scan_report = None
        self.last_rescan_reason = "load_game"
        self.last_execution_result = None
        self.execution_debug_print_tf = True
        self.ai_execution_preview_ready = False
        self.ai_execution_preview_player_id = None
        self.ai_execution_stage = ""
        self.current_ai_execution_plan = []
        self.current_ai_decision_trace = []
        self.last_ai_preview_result = None
        self.last_ai_continue_result = None
        self.pending_seven_roll = getattr(self, "pending_seven_roll", {"active": False}) or {"active": False}
        self.pending_robber_steal = getattr(self, "pending_robber_steal", {"active": False}) or {"active": False}
        self.last_7_result = None
        self.last_robber_move_result = None
        self._ensure_turn_event_ledger()
        try:
            self.turn_event_ledger.start_turn(int(self.round), int(self.turn))
        except Exception:
            pass
        self._sync_all_turn_detail_mirrors_from_ledger()
        self.get_current_player()

        if self.phase == "Execution":
            try:
                self.refresh_viable_actions("load_game")
            except Exception as exc:
                if MG:
                    with open(FILENAME_MG, "a", encoding="utf-8") as f:
                        f.write(f"game.py | load_game | refresh_viable_actions failed: {exc}\n")

        # Rebuild optional Markov evaluator only when required.
        self.vertex_to_rolls = None
        self.markov = None
        uses_markov = any(
            getattr(player, "initial_placement_algorithm", None) == 4
            and not getattr(player, "is_human", False)
            for player in self.players
        )
        if uses_markov:
            import contextlib
            import io
            self.vertex_to_rolls = self.board.get_vertex_to_rolls()
            with contextlib.redirect_stdout(io.StringIO()):
                self.markov = MarkovEvaluator()
                self.markov.precompute_game(self.vertex_to_rolls)
            self.markov.board = self.board

        print(f"✅ Loaded saved game from {filename}")
        print(f"   • round={self.round}, turn={self.turn}, phase={self.phase}, state={self.state}")
        print(f"   • players={len(self.players)}, buildings={board_result.get('buildings_loaded', 0)}, roads={board_result.get('roads_loaded', 0)}")

        return {
            "ok": True,
            "errors": [],
            "warnings": board_result.get("warnings", []),
            "filename": filename,
            "board": board_result,
        }

    def write_debug_info(self) -> None:
        """Write game attributes to FILENAME_MG for debugging.

        Args:
            None
        """
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"game.py | write_debug_info | Game ID: {self.id}\n")
                f.write(f" Sequence Number: {self.sequence_number}, Phase: {self.phase}, State: {self.state}, "
                        f"State 1: {self.state_1}, State 2: {self.state_2}\n")
                f.write(f" Round: {self.round}, Turn: {self.turn}, Game Over: {self.game_over}\n")
                f.write(f" Current Player: {self.current_player.id if self.current_player else None}, "
                        f"Winner: {self.winner.id if self.winner else None}\n")
                f.write(f" Longest Road Player: {self.longest_road_player.id if self.longest_road_player else None}, "
                        f"Largest Army Player: {self.largest_army_player.id if self.largest_army_player else None}\n")
                f.write(f" Dice Roll: {self.dice_roll}, Dice Roll History: {self.dice_roll_history}\n")
                f.write(f" Development Cards Stack: {self.dcards_stack}, dice_roll Matrix: {self.dice_roll_matrix}\n")
                f.write(f" Robber Tile Probabilities: {self.robber_tile_probabilities}\n")
                f.write(f" Previous Tile Having Robber: {self.previous_tile_having_robber}, "
                        f"List of Tiles Having Robber: {self.list_of_tiles_having_robber}\n")
                f.write(f" Last Total Turn with dice roll 7: {self.last_total_turn_with_dr7}\n")
                f.write(f" Settings TF (True/ False): {self.settings_tf}, Settings: {vars(self.settings)}\n")
                f.write(f" IP Balanced: {self.initial_placement_balanced}, IP WB: {self.initial_placement_wood_brick}, IP WO: {self.initial_placement_wheat_ore}, "
                        f"IP WOW: {self.initial_placement_wheat_ore_sheep}, IP Monopoly: {self.initial_placement_monopoly}\n")
                f.write(f" Tile Type: {self.tile_type}, Resource Type Available: {self.resource_type_available}, "
                        f"Resource Type Occupied: {self.resource_type_occupied}, Resource Type Players: {self.resource_type_players}\n")
                f.write(f" Players Impacted: {self.players_impacted}\n")
                f.write(f" Common Next Settlements: {self.common_next_settlements}, "
                        f"Common New Settlements: {self.common_new_settlements}, "
                        f"Common Next Roads: {self.common_next_roads}\n")
                f.write(f" Last Known Strategies: {self.last_known_strategies}, "
                        f"Last Known Outlooks: {self.last_known_outlooks}\n")
                f.write("game.py | write_debug_info | Strategy Dashboard\n")
                for sd in self.strategy_dashboard:
                    f.write(f" Player {sd.player_id}: Victory Points: {sd.victory_points}, "
                            f"Settlements: {sd.number_of_settlements}, Cities: {sd.number_of_cities}, "
                            f"Dev Card VP: {sd.victory_points_dcard}, Longest Road: {sd.longest_road}, "
                            f"Largest Army: {sd.largest_army}, RCards: {sd.number_of_rcards}, "
                            f"DCards: {sd.number_of_dcards}, Distribution of Tile Values: {sd.distribution_of_tile_values}, "
                            f"Distribution of Tile Types: {sd.distribution_of_tile_types}\n")
                f.write("game.py | write_debug_info | Resource Card Dashboard\n")
                rcd = self.resource_card_dashboard[0]
                f.write(f" Total Resources: {rcd.resource_production_game_total}\n")
                f.write(f" Player Resources: {rcd.resource_production_game_player}\n")
                f.write(f" Player Resource Views: {rcd.resource_production_game_player_view}\n")
                f.write("game.py | write_debug_info | Turn Details\n")
                f.write(f" Round: {self.myturn.round}, Turn: {self.myturn.turn}, Dice Roll: {self.myturn.dice_roll}, "
                        f"Validate Enough: {self.myturn.validate_function_enough}, "
                        f"Validate TwP Match: {self.myturn.validate_function_TwP_Match}, "
                        f"Validate Discard RCards: {self.myturn.validate_function_discard_rcards_by_HP}, "
                        f"Validate Set Robber: {self.myturn.validate_function_set_robber_by_HP}, "
                        f"Validate Outlook Opponents: {self.myturn.validate_function_outlook_opponents_for_HP}, "
                        f"Built Two Roads: {self.myturn.validate_function_built_two_roads}\n")
                f.write(f" Road Built TF: {self.myturn.road_built_in_turn_TF}, "
                        f"Roads Built: {self.myturn.roads_built_in_turn}\n")
                f.write(f" Settlement Built TF: {self.myturn.settlement_built_in_turn_TF}, "
                        f"Settlements Built: {self.myturn.settlements_built_in_turn}\n")
                f.write(f" City Built TF: {self.myturn.city_built_in_turn_TF}, "
                        f"Cities Built: {self.myturn.cities_built_in_turn}\n")
                f.write(f" DCard Played: {self.myturn.dcard_played_in_turn}, "
                        f"DCard Played TF: {self.myturn.dcard_played_in_turn_TF}\n")
                f.write(f" Tile Type Selected 1: {self.myturn.tile_type_selected_1}, "
                        f"Tile Type Selected 2: {self.myturn.tile_type_selected_2}\n")
                f.write(f" Players Too Many RCards: {self.myturn.players_having_too_many_rcards}\n")
                f.write(f" RCard Give: {self.myturn.rcard_give}, RCard Get: {self.myturn.rcard_get}\n")
                f.write(f" List of TwP: {self.myturn.list_of_TwP}, Deals Offered: {self.myturn.number_of_deals_offered}\n")
                f.write(f" TwP Rejected by HP: {self.myturn.list_of_TwP_rejected_by_HP}, "
                        f"TwHP: {self.myturn.list_of_TwHP}, DCard Selected: {self.myturn.dcard_selected}\n")
                f.write(f" Modes: {self.myturn.modes}\n")
