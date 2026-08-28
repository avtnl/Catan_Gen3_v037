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
from core.constants import HUMAN_PLAYER, HP_ID, FNFREQ, FILENAME_FREQ, MG, FILENAME_MG, FILENAME_MGLOG, SAVE_PATH, SAVED_GAMES_DIR, PlayerColor, ResourceCard, TERRAIN_TO_RESOURCE
from core.markov_evaluator import MarkovEvaluator
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
        # Player id who played a DCard this turn (for scoreboard per-row red highlight)
        self.dcard_played_in_turn_player_id: Optional[int] = None
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
        self.dcard_played_in_turn_player_id = None
        self.tile_type_selected_1 = [0, 0, 0, 0, 0]
        self.tile_type_selected_2 = [0, 0, 0, 0, 0]
        self.question_mark_button = [0, 0, 0, 0, 0, 0]
        self.players_having_too_many_rcards = [0, 0, 0, 0, 0]
        self.rcard_give = [0, 0, 0, 0, 0]
        self.rcard_get = [0, 0, 0, 0, 0]
        self.list_of_TwP = []
        self.number_of_deals_offered = 0
        # HP TwP rejection memory (legacy bag dual-written with T8): keep across
        # clear_turn_details / seat changes. Was gated by MEM_TWP (default False);
        # product default is permanent memory (v045 MEM_TWP=True). Attribute is
        # always created in __init__; do not reset here.
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
    """Tracks resource card distribution across the game.

    ``resource_production_game_player_view`` is the cumulative public viewer→viewed
    table (now). ``resource_production_game_player_view_lag`` holds up to 4
    round-end snapshots (index 0 = 1 round ago … index 3 = 4 rounds ago).
    AI belief for ``RCARD_MEMORY_OPPONENTS=N`` is ``now − lag[N-1]``.
    """

    def __init__(
        self,
        resource_production_game_total: List[int],
        resource_production_game_player: List[List[int]],
        resource_production_game_player_view: List[List[int]],
        resource_production_game_player_view_lag: Optional[List[List[List[int]]]] = None,
    ) -> None:
        """Initialize a ResourceCardDashboard.

        Args:
            resource_production_game_total: Total resources distributed [Wheat, Ore, Wood, Brick, Sheep, Gold].
            resource_production_game_player: Per-player resources [[player_id, Wheat, Ore, Wood, Brick, Sheep, Gold], ...].
            resource_production_game_player_view: Each player's view of others' resources [[viewer_id, viewed_id, Wheat, Ore, Wood, Brick, Sheep , Gold, QM_Added, QM_Discarded], ...].
            resource_production_game_player_view_lag: Optional ring of prior round-end views.
        """
        self.resource_production_game_total = resource_production_game_total
        self.resource_production_game_player = resource_production_game_player
        self.resource_production_game_player_view = resource_production_game_player_view
        try:
            from core.rcard_view_memory import copy_player_view

            self.resource_production_game_player_view_lag = [
                copy_player_view(item)
                for item in (resource_production_game_player_view_lag or [])
            ]
        except Exception:
            self.resource_production_game_player_view_lag = list(
                resource_production_game_player_view_lag or []
            )

    def snapshot_player_view_end_of_round(self) -> None:
        """Push current player_view into the lag ring (call at round boundary)."""
        from core.rcard_view_memory import shift_lag_ring

        self.resource_production_game_player_view_lag = shift_lag_ring(
            getattr(self, "resource_production_game_player_view_lag", None),
            self.resource_production_game_player_view,
        )

    def player_view_memory(self, rounds: Any = None) -> List[List[int]]:
        """AI belief table: full now, or now − lag for last N rounds."""
        from core.rcard_view_memory import player_view_memory as _mem

        return _mem(
            self.resource_production_game_player_view,
            getattr(self, "resource_production_game_player_view_lag", None),
            rounds,
        )

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
        board_name: str,
        seed: Optional[int] = None,
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
            seed: Optional RNG seed (Phase C2 WP-R1). None = unseeded residual RNG.
                When set, ``random.seed(seed)`` is applied and ``game.seed`` /
                ``game.game_seed`` are stored for TwP Stage D and dig-in.
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
        # Phase C2 WP-R1: master seed for residual RNG / experiment arms
        self.seed: Optional[int] = None
        self.game_seed: Optional[int] = None  # alias used by Stage D / hand-risk
        self.apply_seed(seed)
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
        # Phase C2 WP-R2: optional ordered dice script for replay (same playboard + dice)
        self.dice_script: Optional[List[Tuple[int, int]]] = None
        self.dice_script_index: int = 0
        self.dice_rolls_used: int = 0  # rolls actually consumed this game

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
        # AI Continue both use this exact object so the displayed Best-Action target
        # cannot drift away from the mutation target.
        self.current_best_action = None
        self.last_execution_scan_report = None
        self.last_rescan_reason = ""
        self.last_execution_result = None
        self.execution_debug_print_tf = True
        # S6 endgame city vs settle/road pick (runtime; not saved)
        self.last_endgame_sequence = None
        self._endgame_sequence_cache_key = None

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
            # T7: concrete deal HP accepted — execute this, not a re-ranked alt
            self.accepted_binding_proposal = None
            # T10: human counter builder state
            self.pending_twp_counter = None
            self.last_twp_counter_result = None
        except Exception:
            pass
        # P-pack: wall-clock spans + Continue busy gate (not saved).
        self.last_perf_trace: List[Any] = []
        self.perf_history: List[Any] = []
        self.ai_pipeline_busy: bool = False
        self.ai_pipeline_busy_reason: str = ""
        self._ai_pipeline_busy_depth: int = 0
        self.last_perf_summary = None
        self.last_ai_preview_result = None
        self.last_ai_continue_result = None
        # Stage 1 AI Knight planner (gates + logging; play always False until Stage 2).
        self.last_ai_knight_plan = None
        self.last_ai_knight_plan_pre_roll = None
        self.last_ai_knight_plan_post_roll = None
        self.last_ai_knight_plan_by_window = {}
        self.last_ai_knight_execute_result = None
        # Stage 1 AI TFR planner (gates + logging; play always False until Stage 2).
        self.last_ai_tfr_plan = None
        self.last_ai_tfr_plan_pre_roll = None
        self.last_ai_tfr_plan_post_roll = None
        self.last_ai_tfr_plan_by_window = {}
        self.last_ai_tfr_execute_result = None
        # Stage 1 AI YOP planner (gates + logging; play always False until Stage 2).
        self.last_ai_yop_plan = None
        self.last_ai_yop_plan_pre_roll = None
        self.last_ai_yop_plan_post_roll = None
        self.last_ai_yop_plan_by_window = {}
        self.last_ai_yop_execute_result = None
        # Stage 1 AI Monopoly planner (gates + logging; play always False until Stage 2).
        self.last_ai_monopoly_plan = None
        self.last_ai_monopoly_plan_pre_roll = None
        self.last_ai_monopoly_plan_post_roll = None
        self.last_ai_monopoly_plan_by_window = {}
        self.last_ai_monopoly_execute_result = None
        # Cross-card DCard chooser (PR0 shell: at most one execute per turn).
        self.last_ai_dcard_choice = None

        # Runtime-only Human TwP incoming-offer policy.  This controls how the
        # human player responds when an AI player wants a TwP with HP.  Save/load
        # support is a later step; for now a new game starts in Manual mode.
        self.human_twp_mode = "manual"
        self.human_twp_auto_rules = []
        self.human_twp_decline_patterns = {}  # T4/S4: light reputation / cooldown
        self.human_twp_decline_log = []  # S4: recent decline trail
        self.last_twp_skip_reasons = []  # T4: debug why TwP was skipped
        self.last_twp_debug = {}  # T4: PLAN / Phase0 strip
        self.pending_human_twp_offer = None
        self.human_twp_accepted_this_turn = set()
        self.human_twp_declined_this_turn = set()
        self.last_human_twp_response_result = {}
        self.pending_twp_counter = None  # T10 counter builder
        self.last_twp_counter_result = None
        self.pending_twp_auto_rules_editor = {"active": False}
        self.last_human_twp_policy_decision = {}
        # H-B: HP→AI offer scan audit (last + short history; grant in H-C)
        self.last_human_twp_offer_scan = None
        self.human_twp_offer_scan_history = []
        self._human_twp_offer_scan_seq = 0
        self.last_human_twp_offer_grant = None  # reserved H-C
        # S4 / P0-R1: cap chained support TwP/TwB per turn (partial need-fill)
        self.support_trades_this_turn = 0

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
        self.pending_knight_play = {"active": False}  # pre-roll Knight → robber → AwaitingDiceRoll
        self.pending_tfr_play = {"active": False}  # Two Free Roads placement (0–2 free builds)
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
        self.win_result: Optional[Dict[str, Any]] = None
        # W3 will use post_game_ui; W1 only reserves the field
        self.post_game_ui: Optional[Dict[str, Any]] = None
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

    def apply_seed(self, seed: Optional[int] = None) -> Optional[int]:
        """Set ``game.seed`` / ``game.game_seed`` and seed Python ``random`` (WP-R1).

        Returns the applied integer seed, or None if unseeded.
        """
        if seed is None or seed == "":
            self.seed = None
            self.game_seed = None
            return None
        try:
            s = int(seed)
        except Exception:
            self.seed = None
            self.game_seed = None
            return None
        self.seed = s
        self.game_seed = s
        try:
            random.seed(s)
        except Exception:
            pass
        return s

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
                initial_placement_algorithm=2,
                human_like_placement=False           # human-like (recommended)
            ),
            Player(
                id_=2,
                color=PlayerColor.RED.color_name,
                sequence=2,
                is_human=(HUMAN_PLAYER and 2 in HP_ID),
                initial_placement_algorithm=2,
                human_like_placement=False           # human-like (recommended)
            ),
            Player(
                id_=3,
                color=PlayerColor.WHITE.color_name,
                sequence=3,
                is_human=(HUMAN_PLAYER and 3 in HP_ID),
                initial_placement_algorithm=2,
                human_like_placement=False          # doesn't matter for human
            ),
            Player(
                id_=4,
                color=PlayerColor.ORANGE.color_name,
                sequence=4,
                is_human=(HUMAN_PLAYER and 4 in HP_ID),
                initial_placement_algorithm=2,
                human_like_placement=False           # human-like (recommended)
            ),
        ]

        # Link each Player back to this Game instance
        for player in players:
            player.game = self

        # Phase C2 WP-R0: per-seat explicit_142_recalc from constants map
        try:
            from core.explicit_142_recalc import apply_seat_map_to_players

            apply_seat_map_to_players(players, warn=False)
        except Exception:
            pass

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

    def set_dice_script(
        self,
        rolls: Optional[Any] = None,
        *,
        reset_index: bool = True,
    ) -> int:
        """Install an ordered dice script for replay (WP-R2).

        Returns number of valid pairs installed. Empty/None clears the script.
        """
        try:
            from core.dice_script import normalize_dice_list

            pairs = normalize_dice_list(rolls)
        except Exception:
            pairs = []
        if not pairs:
            self.dice_script = None
            if reset_index:
                self.dice_script_index = 0
            return 0
        self.dice_script = list(pairs)
        if reset_index:
            self.dice_script_index = 0
        return len(self.dice_script)

    def roll_dice(self) -> Tuple[int, int]:
        """Roll two dice: consume ``dice_script`` when available, else true random.

        WP-R2: If a script is set and the next index is in range, return that
        pair and advance the index. Past the end of the script (or with no
        script), roll truly with ``random`` and return the new pair.
        Callers (``execute_roll_dice_action``) append to ``dice_rolls``.
        """
        script = getattr(self, "dice_script", None)
        idx = int(getattr(self, "dice_script_index", 0) or 0)
        if isinstance(script, list) and 0 <= idx < len(script):
            try:
                pair = script[idx]
                d1, d2 = int(pair[0]), int(pair[1])
                if 1 <= d1 <= 6 and 1 <= d2 <= 6:
                    self.dice_script_index = idx + 1
                    return (d1, d2)
            except Exception:
                pass
            # bad entry — fall through to true roll but still advance to avoid loop
            self.dice_script_index = idx + 1
        return (random.randint(1, 6), random.randint(1, 6))

    def finalize_dice_rolls(self) -> List[Tuple[int, int]]:
        """Keep only dice rolls actually used this game (WP-R2).

        Truncates ``dice_rolls`` to ``dice_rolls_used`` (or len if counter unset).
        Safe to call at game end / before export. Returns the kept list.
        """
        used = int(getattr(self, "dice_rolls_used", 0) or 0)
        rolls = list(getattr(self, "dice_rolls", None) or [])
        if used <= 0:
            used = len(rolls)
        if used < len(rolls):
            self.dice_rolls = rolls[:used]
        else:
            self.dice_rolls = rolls
        return list(self.dice_rolls)

    def export_dice_payload(self) -> Dict[str, Any]:
        """Dice + seed fragment for result.json (after finalize when possible)."""
        try:
            from core.dice_script import dice_export_dict

            return dice_export_dict(
                getattr(self, "dice_rolls", None) or [],
                seed=getattr(self, "seed", None),
            )
        except Exception:
            rolls = list(getattr(self, "dice_rolls", None) or [])
            return {
                "dice_rolls": [list(x) if isinstance(x, (list, tuple)) else x for x in rolls],
                "dice_count": len(rolls),
                "dice_hash": None,
                "seed": getattr(self, "seed", None),
            }

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

        # Keep ResourceCardDashboard totals / player_view in sync with public production
        # (same shape as IP distribute_initial_resources) so lag/memory deltas work.
        try:
            self.apply_production_to_rcard_dashboard(produced_by_player)
        except Exception:
            pass

        return {
            "roll": roll,
            "produced_by_player": produced_by_player,
            "blocked_by_player": blocked_by_player,
            "producing_tile_ids": sorted(producing_tile_ids),
            "blocked_tile_ids": sorted(blocked_tile_ids),
            "produced_total": produced_total,
            "blocked_total": blocked_total,
        }

    def apply_production_to_rcard_dashboard(
        self, produced_by_player: Mapping[int, Sequence[int]]
    ) -> None:
        """Add known production into dashboard totals, per-player, and all viewer rows."""
        dashes = list(getattr(self, "resource_card_dashboard", []) or [])
        if not dashes:
            return
        for player_id, vec in (produced_by_player or {}).items():
            try:
                pid = int(player_id)
            except Exception:
                continue
            counts = [int(x or 0) for x in list(vec or [])[:6]]
            while len(counts) < 6:
                counts.append(0)
            if not any(counts):
                continue
            for dash in dashes:
                total = list(getattr(dash, "resource_production_game_total", None) or [0] * 6)
                while len(total) < 6:
                    total.append(0)
                for i, c in enumerate(counts):
                    total[i] = int(total[i] or 0) + int(c)
                dash.resource_production_game_total = total

                for p in list(getattr(dash, "resource_production_game_player", None) or []):
                    if not p or int(p[0] or 0) != pid:
                        continue
                    for i, c in enumerate(counts):
                        idx = i + 1
                        if idx < len(p):
                            p[idx] = int(p[idx] or 0) + int(c)

                for view in list(getattr(dash, "resource_production_game_player_view", None) or []):
                    # Public production: every viewer updates the viewed seat's known counts
                    if not view or int(view[1] or 0) != pid:
                        continue
                    for i, c in enumerate(counts):
                        idx = i + 2
                        if idx < len(view):
                            view[idx] = int(view[idx] or 0) + int(c)

    def snapshot_rcard_player_view_end_of_round(self) -> None:
        """Freeze current player_view into the lag ring (end of a completed round)."""
        for dash in list(getattr(self, "resource_card_dashboard", []) or []):
            try:
                dash.snapshot_player_view_end_of_round()
            except Exception:
                pass

    def get_rcard_player_view_memory(self, rounds: Any = None) -> List[List[int]]:
        """AI belief opponent-view table under ``RCARD_MEMORY_OPPONENTS`` (or override)."""
        dashes = list(getattr(self, "resource_card_dashboard", []) or [])
        if not dashes:
            return []
        try:
            return dashes[0].player_view_memory(rounds)
        except Exception:
            from core.rcard_view_memory import copy_player_view

            return copy_player_view(
                getattr(dashes[0], "resource_production_game_player_view", None)
            )

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

    def refresh_strategy_context(
        self,
        reason: str = "",
        *,
        force: bool = False,
        allow_during_forced_flow: bool = False,
        mode: str | None = None,
    ) -> Dict[str, Any]:
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

        allow_during_forced_flow:
            When True (Phase0 / diagnostics only), still run the planner during
            AwaitingDiceRoll, MoveRobber, discard, etc.  Normal gameplay keeps
            this False so forced flows are not interrupted by strategy work.

        mode (P3-C):
            ``hand_only`` / ``l0`` — rescore sticky/preferred way only (no way switch).
            ``explore`` / ``force`` / ``l2`` — full portfolio + behavior override.
            ``auto`` — L2 only when ``should_run_l2_explore`` (flags / no way / force).
            ``None`` — policy default: same as ``auto`` (not silent full explore).
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
            "diagnostic_forced_flow": bool(allow_during_forced_flow),
            "refresh_mode": "",
            "refresh_mode_detail": "",
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

        player_id = getattr(player, "id", None)
        status["player_id"] = player_id

        state_text = str(getattr(self, "state", "") or "")
        pending_7 = getattr(self, "pending_seven_roll", {}) or {}
        in_forced_flow = (
            state_text in {
                "AwaitingDiceRoll",
                "MoveRobber",
                "RobberMoveRequired",
                "SetRobber",
                "StealSelectOpponent",
                "DiscardPending",
            }
            or (isinstance(pending_7, dict) and bool(pending_7.get("active")))
        )

        # Phase L S5/S6: expansion geometry death + fair VP-DCard death
        if not in_forced_flow or allow_during_forced_flow:
            try:
                from core.partial_way_salvage import (
                    update_player_expansion_dead,
                    update_player_vp_dcards_dead,
                )

                if str(getattr(self, "phase", "") or "") == "Execution":
                    exp = update_player_expansion_dead(self, player)
                    status["expansion_dead"] = {
                        "roads_expand": exp.get("roads_expand"),
                        "settles_expand": exp.get("settles_expand"),
                        "roads_reason": exp.get("roads_reason"),
                        "settles_reason": exp.get("settles_reason"),
                    }
                    vp_d = update_player_vp_dcards_dead(self, player)
                    status["vp_dcards_dead"] = {
                        "vp_dcards": vp_d.get("vp_dcards"),
                        "reason": vp_d.get("reason"),
                        "deck_remaining": vp_d.get("deck_remaining"),
                        "held_vp_cards": vp_d.get("held_vp_cards"),
                        "way_vp_need": vp_d.get("way_vp_need"),
                    }
            except Exception as exp_exc:
                status["expansion_dead"] = {"error": str(exp_exc)}

        # Phase L L6: LA/LR give-up before mode resolve so force_strategy_recalc
        # upgrades this refresh to L2 explore (flag-gated Domain A / C freezes).
        if not in_forced_flow or allow_during_forced_flow:
            try:
                from core.la_giveup_l2 import maybe_la_giveup_l2

                gu = maybe_la_giveup_l2(
                    self, player, reason=str(reason or "refresh_strategy_context")
                )
                status["la_giveup"] = gu
                if isinstance(gu, dict) and gu.get("fired"):
                    force = True
                    status["la_giveup_force_explore"] = True
            except Exception as gu_exc:
                status["la_giveup"] = {
                    "enabled": None,
                    "fired": False,
                    "error": str(gu_exc),
                }
            try:
                from core.lr_giveup_l2 import maybe_lr_giveup_l2

                gu_lr = maybe_lr_giveup_l2(
                    self, player, reason=str(reason or "refresh_strategy_context")
                )
                status["lr_giveup"] = gu_lr
                if isinstance(gu_lr, dict) and gu_lr.get("fired"):
                    force = True
                    status["lr_giveup_force_explore"] = True
            except Exception as gu_lr_exc:
                status["lr_giveup"] = {
                    "enabled": None,
                    "fired": False,
                    "error": str(gu_lr_exc),
                }

        # Before dice / during robber-discard: skip heavy planner in normal play.
        # Phase0 capture may pass allow_during_forced_flow=True to still snapshot.
        if in_forced_flow and not allow_during_forced_flow:
            if state_text == "AwaitingDiceRoll":
                status["error"] = "awaiting_dice_roll"
            elif state_text == "DiscardPending":
                status["error"] = "forced_discard_before_strategy_refresh"
            else:
                status["error"] = "forced_robber_before_strategy_refresh"
            self.last_strategy_context_status = status
            return status

        if in_forced_flow and allow_during_forced_flow:
            status["note"] = f"diagnostic_refresh_during_{state_text or 'forced_flow'}"

        # P3-C: resolve hand_only vs full explore before planner / portfolio
        try:
            from core.strategy_reconsider import resolve_refresh_mode

            resolved_mode, mode_detail = resolve_refresh_mode(
                self,
                player,
                mode=mode,
                force=bool(force),
                reason=str(reason or ""),
            )
        except Exception:
            resolved_mode = "explore" if force else "hand_only"
            mode_detail = "resolve_fallback"
        status["refresh_mode"] = resolved_mode
        status["refresh_mode_detail"] = mode_detail
        try:
            self._strategy_refresh_mode = resolved_mode
            self._strategy_refresh_mode_detail = mode_detail
        except Exception:
            pass

        # PR-3: skip duplicate full/auto refresh in the same pipeline generation
        # (e.g. robber force + Slice D same reason).
        try:
            reason_s = str(reason or "")
            gen = int(getattr(self, "_portfolio_cache_generation", 0) or 0)
            token = (
                int(player_id) if player_id is not None else -1,
                reason_s,
                str(resolved_mode),
                gen,
            )
            last = getattr(self, "_strategy_refresh_dedupe_token", None)
            last_status = getattr(self, "last_strategy_context_status", None)
            if (
                last == token
                and isinstance(last_status, dict)
                and last_status.get("ok") is not None
                and str(last_status.get("reason") or "") == reason_s
            ):
                status = dict(last_status)
                status["deduped"] = True
                status["reason"] = reason_s
                self.last_strategy_context_status = status
                return status
        except Exception:
            pass

        try:
            from core.performance_trace import ai_pipeline_busy_scope, timed_span
        except Exception:
            timed_span = None  # type: ignore
            ai_pipeline_busy_scope = None  # type: ignore

        from contextlib import nullcontext

        # P2-A: heavy planner work greys Play/Continue (nested-safe with roll/continue)
        busy_cm = (
            ai_pipeline_busy_scope(self, f"refresh_strategy:{reason or 'refresh'}")
            if ai_pipeline_busy_scope is not None
            else nullcontext()
        )
        span_cm = (
            timed_span(
                self,
                "refresh_strategy_context",
                meta={
                    "reason": str(reason or ""),
                    "force": bool(force),
                    "mode": str(resolved_mode),
                    "mode_detail": str(mode_detail),
                    "allow_during_forced_flow": bool(allow_during_forced_flow),
                },
            )
            if timed_span is not None
            else nullcontext({})
        )

        with busy_cm, span_cm as _span_bag:
            report: Any = None
            # P1 true-light L0: skip full Stage1–4 / 142 planner when only hand changed.
            if resolved_mode == "hand_only":
                try:
                    from core.ai_way_portfolio import build_l0_hand_strategy_report

                    report = build_l0_hand_strategy_report(
                        self,
                        player,
                        reason=str(reason or ""),
                    )
                    # P1 WP4: bubble L0 meta onto outer refresh_strategy_context span
                    try:
                        from core.performance_trace import attach_span_meta

                        l0 = (report.get("l0_hand_only") if isinstance(report, Mapping) else None) or {}
                        attach_span_meta(
                            _span_bag,
                            path="true_light",
                            l0_true_light=True,
                            ways=list(l0.get("ways") or []),
                            way_count=int(l0.get("way_count") or len(l0.get("ways") or [])),
                            matched_way=l0.get("matched_way"),
                            geo_cache_hit=bool(l0.get("geo_cache_hit")),
                            hand_rescore=bool(l0.get("hand_rescore")),
                            full_cache_hit=bool(l0.get("full_cache_hit")),
                            audit_count=int(l0.get("audit_count") or 0),
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    status["error"] = f"l0_strategy_failed: {exc}"
                    # Do not silently fall back to L2 explore (X4).
                    self.last_strategy_context_error = status["error"]
                    self.last_strategy_context_status = status
                    try:
                        from core.performance_trace import attach_span_meta

                        attach_span_meta(
                            _span_bag,
                            path="true_light",
                            l0_true_light=True,
                            l0_error=True,
                        )
                    except Exception:
                        pass
                    try:
                        self._strategy_refresh_mode = None
                    except Exception:
                        pass
                    return status
            else:
                try:
                    from inspect import signature
                    from core.action_planner import build_action_timing_report
                except Exception as exc:
                    status["error"] = f"planner_import_failed: {exc}"
                    self.last_strategy_context_error = status["error"]
                    self.last_strategy_context_status = status
                    try:
                        self._strategy_refresh_mode = None
                    except Exception:
                        pass
                    return status

                # P4: fast vs full L2 quality profile (does not change whether L2 runs)
                try:
                    from core.l2_profile import resolve_l2_profile

                    l2_prof = resolve_l2_profile(
                        self,
                        reason=str(reason or ""),
                        force=bool(force),
                        mode=str(resolved_mode),
                    )
                    self._l2_profile = l2_prof
                except Exception:
                    l2_prof = None
                    try:
                        self._l2_profile = None
                    except Exception:
                        pass

                # Only pass keyword arguments that the installed action_planner accepts.
                # This keeps the bridge stable if you temporarily test with an older
                # planner file.
                if l2_prof is not None and str(getattr(l2_prof, "name", "") or "") == "fast":
                    desired_kwargs = {
                        "top_n_actions": 3,
                        "include_all": bool(l2_prof.stage1_include_all),
                        "include_debug": False,
                        "enable_player_trades": bool(l2_prof.enable_player_trades),
                        "enable_action_projections": bool(l2_prof.enable_projections),
                        "enable_continuation_strategies": bool(l2_prof.enable_continuations),
                        "continuation_top_n": 3,
                        "stage3_player_scope": "current",
                        "enable_risk_assessment": bool(l2_prof.enable_risk),
                        "stage4_risk_player_scope": "current",
                        "enable_strategy_preference": True,
                        "persist_strategy_preference_to_player": False,
                    }
                else:
                    desired_kwargs = {
                        "top_n_actions": 3,
                        "include_all": True,
                        "include_debug": False,
                        "enable_player_trades": True,
                        "enable_action_projections": True,
                        "enable_continuation_strategies": True,
                        "continuation_top_n": 3,
                        "stage3_player_scope": "current",
                        "enable_risk_assessment": True,
                        "stage4_risk_player_scope": "current",
                        "enable_strategy_preference": True,
                        # Persist manually below for the current player only.  The report has
                        # by_player rows for all players, while Stage 3/4 is current-player
                        # scoped; automatic persistence could overwrite opponents with
                        # "No strategy candidate".
                        "persist_strategy_preference_to_player": False,
                    }

                try:
                    accepted = set(signature(build_action_timing_report).parameters)
                    # MagicMock / tiny signatures: pass full kwargs (tests + future params)
                    if len(accepted) >= 5 and "top_n_actions" in accepted:
                        kwargs = {k: v for k, v in desired_kwargs.items() if k in accepted}
                    else:
                        kwargs = dict(desired_kwargs)
                except Exception:
                    kwargs = dict(desired_kwargs)

                try:
                    report = build_action_timing_report(self, **kwargs)
                    try:
                        from core.performance_trace import attach_span_meta

                        prof_meta = {}
                        if l2_prof is not None:
                            try:
                                prof_meta = {
                                    "l2_profile": getattr(l2_prof, "name", None),
                                    "prefilter_k": getattr(l2_prof, "abstract_prefilter_k", None),
                                    "portfolio_top_n": getattr(l2_prof, "portfolio_top_n", None),
                                }
                            except Exception:
                                prof_meta = {}
                        attach_span_meta(
                            _span_bag,
                            path="l2_full" if not prof_meta or prof_meta.get("l2_profile") == "full" else "l2_fast",
                            l0_true_light=False,
                            mode=str(resolved_mode),
                            **prof_meta,
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    status["error"] = f"planner_failed: {exc}"
                    self.last_action_timing_report = None
                    self.last_strategy_context_error = status["error"]
                    self.last_strategy_context_status = status
                    try:
                        self._strategy_refresh_mode = None
                    except Exception:
                        pass
                    return status

            self.last_action_timing_report = report
            self.last_strategy_context_reason = reason or "refresh_strategy_context"
            self.last_strategy_context_error = ""

            player_block = None
            try:
                by_player = report.get("by_player", {}) if isinstance(report, Mapping) else {}
                player_block = by_player.get(str(int(player_id))) or by_player.get(str(player_id))
            except Exception:
                player_block = None

            preferred: Dict[str, Any] = {}
            if isinstance(player_block, Mapping):
                raw_preferred = player_block.get("preferred_strategy", {})
                if isinstance(raw_preferred, Mapping):
                    preferred = dict(raw_preferred)
            # L0 may have already written strategic_direction; reuse if block empty
            if not preferred and resolved_mode == "hand_only":
                raw_dir = getattr(player, "strategic_direction", None)
                if isinstance(raw_dir, Mapping):
                    preferred = dict(raw_dir)

            if preferred:
                preferred["strategy_context_reason"] = reason or "refresh_strategy_context"
                preferred["strategy_context_round"] = getattr(self, "round", None)
                preferred["strategy_context_turn"] = getattr(self, "turn", None)
                try:
                    previous = getattr(player, "strategic_direction", None)
                    setattr(player, "last_strategic_direction", previous)
                    setattr(player, "strategic_direction", preferred)
                    history = list(getattr(player, "strategic_direction_history", []) or [])
                    history.append(preferred)
                    setattr(player, "strategic_direction_history", history[-20:])
                except Exception as exc:
                    status["error"] = f"persist_failed: {exc}"
                    self.last_strategy_context_error = status["error"]
                # PR-D: compact STR history samples (way_id + expected turns over turns)
                try:
                    from core.strategy_history import record_from_refresh

                    record_from_refresh(
                        self,
                        player,
                        preferred,
                        reason=str(reason or "refresh_strategy_context"),
                    )
                except Exception:
                    pass

            status.update({
                "ok": bool(preferred),
                "preferred_way_id": preferred.get("preferred_way_id", preferred.get("way_id")) if preferred else None,
                "preference_level": str(preferred.get("preference_level", "") if preferred else ""),
                "preference_reason": str(preferred.get("preference_reason", "") if preferred else ""),
                "supporting_action_type": str(preferred.get("supporting_action_type", "") if preferred else ""),
                "supporting_action_target_id": preferred.get("supporting_action_target_id") if preferred else None,
                "error": status.get("error", ""),
                "refresh_mode": resolved_mode,
                "refresh_mode_detail": mode_detail,
            })
            # P3: closed L2 policy bag for dig-in / tests
            try:
                from core.strategy_reconsider import build_l2_policy_status

                status["l2_policy"] = build_l2_policy_status(
                    self,
                    player,
                    reason=str(reason or ""),
                    mode=str(resolved_mode),
                    mode_detail=str(mode_detail),
                )
            except Exception:
                status["l2_policy"] = {
                    "allowed": resolved_mode == "explore",
                    "bucket": None,
                    "gate": str(mode_detail or ""),
                    "mode": str(resolved_mode),
                }
            # Phase L WP-L1: god-view LA/LR probe (observe only; no SE change)
            try:
                from core.la_lr_probe_log import maybe_log_la_lr_probe

                maybe_log_la_lr_probe(
                    self,
                    player,
                    reason=str(reason or "refresh_strategy_context"),
                    event="after_strategy_refresh",
                )
            except Exception:
                pass
            # WP4: tangible LA/LR race plans + knight/TFR soft policy (no board mutation)
            try:
                from core.specials_race_plans import refresh_specials_race_plans

                race_bag = refresh_specials_race_plans(
                    self,
                    player,
                    reason=str(reason or "refresh_strategy_context"),
                    apply_sticky=True,
                )
                status["specials_race"] = {
                    "ok": bool(race_bag.get("ok")),
                    "lr_label": (race_bag.get("lr") or {}).get("label"),
                    "la_label": (race_bag.get("la") or {}).get("label"),
                    "prefer_knight": (race_bag.get("knight_tfr") or {}).get(
                        "prefer_knight"
                    ),
                    "knight_tfr_rule": (race_bag.get("knight_tfr") or {}).get("rule"),
                    "sticky_merged": bool(race_bag.get("sticky_merged")),
                }
            except Exception as _wp4_exc:
                status["specials_race"] = {
                    "ok": False,
                    "error": str(_wp4_exc)[:120],
                }
            # WP5: PLAN/WHY2 snapshot (L2/explore only; CS dig fields)
            try:
                from core.strategy_plan_snapshot import refresh_plan_snapshot

                plan_bag = refresh_plan_snapshot(
                    self,
                    player,
                    preferred if preferred else getattr(player, "strategic_direction", None),
                    reason=str(reason or "refresh_strategy_context"),
                    refresh_mode=str(resolved_mode or ""),
                    force=False,
                )
                status["plan_snapshot"] = {
                    "ok": bool(plan_bag.get("ok")),
                    "active": bool(plan_bag.get("active")),
                    "asof": (plan_bag.get("cs") or {}).get("plan_asof_rt"),
                    "n_settles": len(plan_bag.get("settles") or []),
                    "n_why2": len(plan_bag.get("why2") or []),
                    "reason": plan_bag.get("reason"),
                }
            except Exception as _wp5_exc:
                status["plan_snapshot"] = {
                    "ok": False,
                    "error": str(_wp5_exc)[:120],
                }
            # If this pass was L0 but a/b/c flags are now set (often latched mid/after
            # refresh), re-enter once as explore so PLN2 ETAs are not frozen forever
            # (dig symptom: P1/P3 plan_asof stuck at R1 with empty Tgt/ETA).
            try:
                if (
                    str(resolved_mode) == "hand_only"
                    and not bool(getattr(self, "_l2_flag_reentry", False))
                    and player is not None
                ):
                    from core.strategy_reconsider import (
                        any_significant_flag,
                        get_reconsider_flags,
                    )

                    if any_significant_flag(get_reconsider_flags(player)):
                        self._l2_flag_reentry = True
                        try:
                            return self.refresh_strategy_context(
                                reason=str(reason or "flag_reentry_explore"),
                                allow_during_forced_flow=allow_during_forced_flow,
                                mode="explore",
                                force=True,
                            )
                        finally:
                            try:
                                self._l2_flag_reentry = False
                            except Exception:
                                pass
            except Exception:
                try:
                    self._l2_flag_reentry = False
                except Exception:
                    pass
            # Phase L salvage: terminal reminder if S4 would help (bounce after escape)
            try:
                from core.partial_way_salvage import maybe_signal_s4_needed

                s4 = maybe_signal_s4_needed(
                    self,
                    player,
                    reason=str(reason or "refresh_strategy_context"),
                )
                if s4:
                    status["s4_needed"] = s4
            except Exception:
                pass
            # Surface portfolio L0/L2 diagnostics when present
            try:
                if isinstance(report, Mapping):
                    settings = report.get("settings") or {}
                    status["portfolio_hand_only"] = bool(
                        settings.get("board_way_portfolio_hand_only")
                        or settings.get("l0_true_light")
                    )
                    status["l0_true_light"] = bool(settings.get("l0_true_light"))
                    if report.get("l0_hand_only"):
                        status["l0_hand_only"] = dict(report.get("l0_hand_only") or {})
                    if settings.get("skipped_layers"):
                        status["skipped_layers"] = list(settings.get("skipped_layers") or [])
            except Exception:
                pass

            # S5.5-C: own-turn specials divert cadence (once per round/turn/player).
            # Portfolio override may already have latched during the planner; this
            # call then skips unless force=True. If portfolio did not run, assess + divert here.
            # Skip divert on pure L0 hand_only (way locked) **unless** WP3 give-up
            # escape episode is active (force divert / unstick dead specials).
            try:
                force_escape_divert = False
                try:
                    from core.specials_dead_episode import (
                        episode_kill_flags,
                        get_specials_dead_episode,
                        is_giveup_force_divert_enabled,
                    )

                    if is_giveup_force_divert_enabled():
                        ep = get_specials_dead_episode(player)
                        kla_ep, klr_ep = episode_kill_flags(player)
                        force_escape_divert = bool(
                            ep.get("active") and (kla_ep or klr_ep)
                        )
                except Exception:
                    force_escape_divert = False

                # Also force when this refresh just fired L6 give-up
                if not force_escape_divert:
                    try:
                        gu = status.get("lr_giveup") or status.get("la_giveup") or {}
                        if isinstance(gu, Mapping) and gu.get("fired"):
                            force_escape_divert = True
                    except Exception:
                        pass
                    try:
                        if (status.get("lr_giveup") or {}).get("fired") or (
                            status.get("la_giveup") or {}
                        ).get("fired"):
                            force_escape_divert = True
                    except Exception:
                        pass

                if resolved_mode == "hand_only" and not force_escape_divert:
                    status["specials_divert"] = {
                        "skipped": True,
                        "fired": False,
                        "reason": "l0_hand_only",
                    }
                else:
                    from core.strategy_specials_divert import maybe_specials_divert_on_turn_start

                    s55 = maybe_specials_divert_on_turn_start(
                        self,
                        player,
                        None,
                        preferred if preferred else getattr(player, "strategic_direction", None),
                        abstract_preferred=preferred if preferred else None,
                        phase=(
                            "own_turn_start_escape"
                            if force_escape_divert
                            else "own_turn_start"
                        ),
                        store=True,
                        apply_direction=True,
                        force=bool(force_escape_divert),
                    )
                    status["specials_divert"] = {
                        "skipped": bool(s55.get("skipped")),
                        "fired": bool(s55.get("fired")),
                        "reason": s55.get("reason"),
                        "chosen_way_id": s55.get("chosen_way_id"),
                        "kill_la": s55.get("kill_la"),
                        "kill_lr": s55.get("kill_lr"),
                        "force": bool(s55.get("force")),
                        "force_kill_la": s55.get("force_kill_la"),
                        "force_kill_lr": s55.get("force_kill_lr"),
                        "dbg": s55.get("dbg"),
                        "phase": s55.get("phase"),
                        "escape_divert": bool(force_escape_divert),
                    }
                    if (
                        s55.get("fired")
                        and not s55.get("skipped")
                        and s55.get("direction_applied")
                    ):
                        new_pref = getattr(player, "strategic_direction", None)
                        if isinstance(new_pref, Mapping):
                            status["preferred_way_id"] = new_pref.get(
                                "preferred_way_id", new_pref.get("way_id")
                            )
                            status["specials_divert_applied"] = True
                            preferred = dict(new_pref)
            except Exception as s55_exc:
                status["specials_divert"] = {
                    "error": str(s55_exc),
                    "skipped": True,
                    "fired": False,
                }

            # Phase C2 WP-R3: sample sticky ETA after refresh (setback latch for next gate)
            try:
                from core.strategy_explicit_recalc import note_eta_sample

                note_eta_sample(player, None)
            except Exception:
                pass

            # After successful L2, clear significance so next quiet dice stays L0.
            if resolved_mode == "explore" and not status.get("error"):
                try:
                    from core.strategy_reconsider import clear_all_strategy_significance

                    clear_all_strategy_significance(
                        player, reason=str(reason or "after_l2")
                    )
                    status["significance_cleared"] = True
                except Exception:
                    status["significance_cleared"] = False

            self.last_strategy_context_status = status
            try:
                # Dedupe token for same reason+mode within pipeline generation
                gen = int(getattr(self, "_portfolio_cache_generation", 0) or 0)
                self._strategy_refresh_dedupe_token = (
                    int(player_id) if player_id is not None else -1,
                    str(reason or ""),
                    str(resolved_mode),
                    gen,
                )
            except Exception:
                pass
            try:
                self._strategy_refresh_mode = None
            except Exception:
                pass
            try:
                # P4: profile only applies to the explore we just ran
                if resolved_mode != "hand_only":
                    pass  # keep _l2_profile on status consumers until next refresh
            except Exception:
                pass
            return status

    def refresh_strategy_after_event(
        self,
        reason: str = "",
        *,
        kind: str = "auto",
        allow_during_forced_flow: bool = False,
    ) -> Dict[str, Any]:
        """Policy-aware strategy refresh (hand / turn_start / milestone / …).

        Prefer this over ``force=True`` so TwP/hand changes stay L0 when sticky
        exists, and L2 runs only via ``should_run_l2_explore`` (flags a–d).
        """
        try:
            from core.strategy_reconsider import mode_for_refresh_kind

            player = self.get_current_player()
            mode, force = mode_for_refresh_kind(
                self, player, kind, reason=str(reason or "")
            )
        except Exception:
            mode, force = "auto", False
        return self.refresh_strategy_context(
            reason,
            force=bool(force),
            mode=mode,
            allow_during_forced_flow=allow_during_forced_flow,
        )

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

        try:
            from core.performance_trace import timed_span
        except Exception:
            timed_span = None  # type: ignore

        span_cm = (
            timed_span(
                self,
                "scanning_viable_actions",
                meta={"reason": str(reason or "")},
            )
            if timed_span is not None
            else None
        )
        if span_cm is None:
            from contextlib import nullcontext

            span_cm = nullcontext({})

        with span_cm:
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

            # Freeze the exact Best-Action action immediately after the scanner refresh.
            # The panel displays this object and AI Continue executes this object.
            # Do not select a different candidate later at click time.
            try:
                self.current_best_action = self._compute_current_best_executable_action()
                if isinstance(self.last_execution_scan_report, dict):
                    self.last_execution_scan_report["canonical_best_action"] = dict(self.current_best_action or {})
            except Exception as exc:
                self.current_best_action = None
                if isinstance(self.last_execution_scan_report, dict):
                    self.last_execution_scan_report["canonical_best_action_error"] = str(exc)

            # Stage A: keep/ditch hand-risk profile for discard + Execution Debug
            try:
                from core.ai_hand_risk import refresh_hand_risk_profile

                player = self.get_current_player()
                profile = refresh_hand_risk_profile(self, player)
                if isinstance(self.last_execution_scan_report, dict):
                    self.last_execution_scan_report["hand_risk_profile"] = dict(profile or {})
            except Exception as exc:
                try:
                    self.current_hand_risk_profile = {"stage": "A", "error": str(exc), "policy": "accept"}
                except Exception:
                    pass

            # T4: TwP debug strip for PLAN + Phase0
            try:
                from core.human_twp_policy import refresh_twp_debug

                twp_snap = refresh_twp_debug(self)
                if isinstance(self.last_execution_scan_report, dict):
                    self.last_execution_scan_report["twp_debug"] = dict(twp_snap or {})
            except Exception as exc:
                try:
                    self.last_twp_debug = {"stage": "T4", "error": str(exc), "line": "TwP: -"}
                except Exception:
                    pass

            return scan

    def begin_execution_turn(self):
        """
        Start or restart the current player's Execution turn.

        At this point the player must roll dice unless a forced action already exists.
        """
        if self.phase != "Execution":
            return None

        # Seed per-player reachability maps once when Execution begins (post-IP / load).
        if not bool(getattr(self, "_reachability_maps_seeded", False)):
            try:
                from core.player_reachability import rebuild_all_maintained_seats

                self.last_reachability_seed = rebuild_all_maintained_seats(self)
                self._reachability_maps_seeded = True
            except Exception:
                self.last_reachability_seed = {"ok": False}

        self.get_current_player()
        self.clear_all_player_turn_details()
        self.state = "AwaitingDiceRoll"
        self.state_1 = ""
        self.state_2 = ""
        self.dice_roll = None
        self.pending_seven_roll = {"active": False}
        self.pending_robber_steal = {"active": False}
        self.pending_knight_play = {"active": False}
        self.pending_tfr_play = {"active": False}
        self.last_7_result = None
        self.last_robber_plan = None
        self.last_robber_move_result = None
        self.last_robber_steal_selection = None
        self.last_robber_steal_result = None

        # New execution turn: dice must be rolled first (or pre-roll Knight).
        # Humans use Roll Dices (not PLAY); AI still uses PLAY to start a roll
        # preview. Reset GUI button registry so stale Continue/End cannot leak.
        self.ai_execution_preview_ready = False
        self.ai_execution_preview_player_id = getattr(self.current_player, "id", None) if self.current_player is not None else None
        self.ai_execution_stage = "awaiting_dice"
        self.current_ai_execution_plan = []
        self.current_ai_decision_trace = []
        self.last_ai_preview_result = None
        self.last_ai_continue_result = None
        self.last_ai_knight_plan = None
        self.last_ai_knight_plan_pre_roll = None
        self.last_ai_knight_plan_post_roll = None
        self.last_ai_knight_plan_by_window = {}
        self.last_ai_knight_execute_result = None
        self.last_ai_tfr_plan = None
        self.last_ai_tfr_plan_pre_roll = None
        self.last_ai_tfr_plan_post_roll = None
        self.last_ai_tfr_plan_by_window = {}
        self.last_ai_tfr_execute_result = None
        self.last_ai_yop_plan = None
        self.last_ai_yop_plan_pre_roll = None
        self.last_ai_yop_plan_post_roll = None
        self.last_ai_yop_plan_by_window = {}
        self.last_ai_yop_execute_result = None
        self.last_ai_monopoly_plan = None
        self.last_ai_monopoly_plan_pre_roll = None
        self.last_ai_monopoly_plan_post_roll = None
        self.last_ai_monopoly_plan_by_window = {}
        self.last_ai_monopoly_execute_result = None
        self.last_ai_dcard_choice = None
        try:
            if self.gui is not None:
                self.gui.set_button("continue_ai", False)
                self.gui.set_button("end_turn", False)
                self.gui.set_button("cancel", False)
                # Human: Roll Dices only. AI: PLAY starts roll/preview.
                is_human_seat = bool(getattr(self.current_player, "is_human", False))
                self.gui.set_button("next_turn2", not is_human_seat)
                self.gui.set_button("roll_dices", is_human_seat)
        except Exception:
            pass

        try:
            self.myturn.clear_turn_details()
            self.myturn.round = self.round
            self.myturn.turn = self.turn
            self.myturn.dice_roll = 0
        except Exception:
            pass

        # Full seat-turn DCard header pulse ends when the next seat begins
        try:
            self.clear_dcard_header_play_fx()
        except Exception:
            pass

        # Idempotent maturity for the seat that is about to act (covers load /
        # first Execution turn if end-of-previous-turn maturity was missed).
        try:
            self._mature_player_dcard_new_to_playable(self.get_current_player())
        except Exception:
            pass
        try:
            from core import mglog

            mglog.log_turn_start(self)
        except Exception:
            pass

        # Phase C2 WP-R3: count own Execution turns for every_n explicit recalc
        try:
            from core.strategy_explicit_recalc import note_own_execution_turn

            note_own_execution_turn(self, self.get_current_player())
        except Exception:
            pass

        # Sidestep S142: consume deferred opp R/S/C (trigger b) for seat to move
        try:
            from core.sidestep_s142_drive import consume_deferred_opp_build

            consume_deferred_opp_build(self, self.get_current_player())
        except Exception:
            pass

        # Legacy Sidestep PLN2 compare (off by default; cadence retired unless flag)
        try:
            from core.sidestep_compare import maybe_run_sidestep_compare

            maybe_run_sidestep_compare(self)
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
        if bool(getattr(self, "game_over", False)):
            return {
                "ok": False,
                "action": "Roll Dices",
                "reason": "game_over",
                "already_over": True,
            }
        if self.phase != "Execution":
            raise RuntimeError("Cannot roll execution dice outside the Execution phase.")

        player = self.get_current_player()
        dice = self.roll_dice()
        total = int(sum(dice))

        self.dice_roll = dice
        self.dice_rolls.append(dice)
        try:
            self.dice_rolls_used = int(getattr(self, "dice_rolls_used", 0) or 0) + 1
        except Exception:
            self.dice_rolls_used = len(self.dice_rolls)

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
        try:
            from core import mglog

            mglog.log_dice_roll(self, dice, total, player=player)
        except Exception:
            pass

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
            try:
                from core import mglog

                mglog.log_resource_production(self, production_result)
            except Exception:
                pass

        # Refresh the strategic direction after the dice/resources are known and
        # before Slice A/B interprets strategy needs.  On a 7, publish an
        # explicit "paused for robber" planner status instead; the real planner
        # refresh runs after Continue resolves the robber/steal.
        #
        # P3-C: non-7 rolls use mode=auto → L0 hand_only rescore of sticky/preferred
        # way unless significance flags / force_strategy_recalc require L2 explore.
        if total != 7:
            self.refresh_strategy_context("after_dice_roll", mode="auto")
        else:
            # P3: do not force full explore during 7 forced-flow (usually skips anyway).
            # Robber resolution + P2 dirty flags open L2 on the next auto path.
            self.refresh_strategy_context(
                "after_dice_roll_forced_robber",
                mode="auto",
            )

        scan = self.refresh_viable_actions("execute_roll_dice_action")

        # P1+Q1: after scan, off-way settle/city may force one L2 before BA/preview
        # P1+Q2: off-way DCard permission (no L2) after Q1
        if total != 7:
            try:
                from core.strategy_offway_q1 import maybe_q1_offway_structure_l2

                maybe_q1_offway_structure_l2(
                    self,
                    player,
                    reason="after_dice_roll",
                    rescan=True,
                )
            except Exception:
                pass
            try:
                from core.strategy_offway_q2 import apply_q2_offway_dcard_permission

                apply_q2_offway_dcard_permission(
                    self, player, reason="after_dice_roll"
                )
            except Exception:
                pass

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

    def _ai_continue_logic_available(self) -> bool:
        """Return True when AI Continue may *execute* (phase/seat/dice gates only).

        Does **not** consult pipeline / Phase0 / press-latch busy flags. Those
        gate the *button and re-clicks* via ``ai_continue_is_available`` and the
        event handler. Execution itself is often already inside
        ``play_continue_busy_scope`` (P3-A); treating busy as unavailable there
        made Continue a permanent no-op (R1T1 stuck, 2026-07-31).

        Forced discard (7-roll): Continue must stay off while any player still
        owes a discard or the human discard panel is waiting — even on an AI
        seat — until the queue is clear and robber may proceed.
        """
        if bool(getattr(self, "game_over", False)):
            return False
        if str(getattr(self, "phase", "")) != "Execution":
            return False
        if self._is_current_player_human_for_execution():
            return False
        state_text = str(getattr(self, "state", "") or "")
        if state_text == "AwaitingDiceRoll":
            return False
        if state_text == "DiscardPending":
            return False
        try:
            queue = list(getattr(self, "pending_discard_queue", None) or [])
            if queue:
                return False
        except Exception:
            pass
        try:
            # Human discard flag (set while panel is open / queue paused).
            myturn = getattr(self, "myturn", None)
            if myturn is not None and bool(
                getattr(myturn, "validate_function_discard_rcards_by_HP", False)
            ):
                return False
        except Exception:
            pass
        return self._dice_has_been_rolled_for_execution()

    def ai_continue_is_available(self) -> bool:
        """Return True when the AI Continue *button* should be active.

        This is intentionally independent from viable buy/build actions. No
        viable actions simply means Continue will pass and advance the turn.

        Important turn-boundary rule:
            AwaitingDiceRoll always means Continue is unavailable. This prevents
            a stale Continue button from leaking from the previous AI turn into
            the next player's fresh turn.

        P2-A / P3-A: while ``is_ui_input_busy`` (pipeline, Phase0 save, or press
        latch) Continue stays grey even if dice are already rolled. The execute
        path uses ``_ai_continue_logic_available`` so an in-flight Continue click
        is not rejected by its own outer busy scope.
        """
        if not self._ai_continue_logic_available():
            return False
        try:
            from core.performance_trace import is_ui_input_busy

            if is_ui_input_busy(self):
                return False
        except Exception:
            try:
                from core.performance_trace import is_ai_pipeline_busy

                if is_ai_pipeline_busy(self):
                    return False
            except Exception:
                if bool(getattr(self, "ai_pipeline_busy", False)) or bool(
                    getattr(self, "phase0_save_busy", False)
                ):
                    return False
        return True

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
        try:
            from core.performance_trace import timed_span
        except Exception:
            timed_span = None  # type: ignore

        span_cm = (
            timed_span(self, "_build_ai_continue_plan", meta={})
            if timed_span is not None
            else None
        )
        if span_cm is None:
            from contextlib import nullcontext

            span_cm = nullcontext({})

        with span_cm:
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
            # S6: endgame city vs expand — boost pick when gate fires
            try:
                s6_meta = self._run_endgame_sequence_pick()
                from core.endgame_sequence import apply_endgame_action_priority

                priority = apply_endgame_action_priority(priority, s6_meta or {})
            except Exception:
                s6_meta = None
            # S-LR-C: race / dense-pack turn focus elevates BA family
            try:
                from core.ai_lr_project import apply_slr_c_action_priority, pick_turn_focus

                _p = self.get_current_player()
                if _p is not None:
                    priority = apply_slr_c_action_priority(priority, pick_turn_focus(self, _p))
            except Exception:
                pass
            # WP-ARB1: when LR claim owns Dig Why / plan label, BA family = Build road
            # (not city TwB divert while LR claim is live).
            try:
                _p = self.get_current_player()
                lr_pkg = ""
                if _p is not None:
                    d = getattr(_p, "strategic_direction", None) or {}
                    if isinstance(d, Mapping):
                        lr_pkg = str(
                            d.get("lr_plan_label")
                            or d.get("plan_lr_pkg")
                            or (d.get("lr_plan") or {}).get("label")
                            or ""
                        ).lower()
                    snap = getattr(_p, "last_plan_snapshot", None) or {}
                    if not lr_pkg and isinstance(snap, Mapping):
                        lr_pkg = str(
                            snap.get("lr_plan_label") or snap.get("plan_lr_pkg") or ""
                        ).lower()
                if (
                    "claim" in lr_pkg
                    or lr_pkg.startswith("lr claim")
                    or "|claim|" in lr_pkg
                ):
                    priority = dict(priority)
                    priority["Build road"] = 0
                    # Soft demote city so LR tip roads win Continue
                    if "Build city" in priority:
                        priority["Build city"] = max(int(priority.get("Build city") or 1), 3)
            except Exception:
                pass
            # P2: sticky race risk M/H → chase settle/key road
            try:
                from core.strategy_race_ba import (
                    apply_race_ba_action_priority,
                    race_ba_focus,
                )

                _p = self.get_current_player()
                if _p is not None:
                    priority = apply_race_ba_action_priority(
                        priority, race_ba_focus(self, _p)
                    )
            except Exception:
                pass

            # WP-TFR1 / WP-DCARD2: while a DCard still wants play this turn, defer
            # paid Build / Buy so preview can execute play first (n3d Orange R3,
            # v6 Blue knight-before-buy).
            _defer_paid_road_for_tfr = False
            _defer_spend_for_dcard_play = False
            try:
                _p = self.get_current_player()
                tfr_plan = getattr(self, "last_ai_tfr_plan", None) or {}
                if not isinstance(tfr_plan, Mapping):
                    tfr_plan = {}
                knight_plan = getattr(self, "last_ai_knight_plan", None) or {}
                if not isinstance(knight_plan, Mapping):
                    knight_plan = getattr(self, "last_ai_knight_plan_post_roll", None) or {}
                if not isinstance(knight_plan, Mapping):
                    knight_plan = {}
                dcard_choice = getattr(self, "last_ai_dcard_choice", None) or {}
                if not isinstance(dcard_choice, Mapping):
                    dcard_choice = {}
                dcard_played = False
                for _td_attr in ("myturn", "turn_details"):
                    _td = getattr(self, _td_attr, None)
                    if _td is not None and bool(getattr(_td, "dcard_played_in_turn_TF", False)):
                        dcard_played = True
                        break
                tfr_wants = (
                    bool(tfr_plan.get("play"))
                    and bool(tfr_plan.get("legal"))
                    and (
                        list(tfr_plan.get("road_ids") or [])
                        or int(tfr_plan.get("free_roads_available") or 0) > 0
                    )
                )
                knight_wants = bool(knight_plan.get("play")) and bool(
                    knight_plan.get("legal", True)
                )
                choice_wants = bool(dcard_choice.get("play")) and bool(
                    dcard_choice.get("chosen")
                )
                # Also: HOLD won but context still wants play
                ctx = dcard_choice.get("context") if isinstance(dcard_choice.get("context"), Mapping) else {}
                prefer_play = bool(
                    ctx.get("wp_tfr1_prefer_play")
                    or ctx.get("wp_dcard2_prefer_play")
                    or ctx.get("wp_dcard2_forced_over_hold")
                )
                if not dcard_played and (tfr_wants or knight_wants or choice_wants or prefer_play):
                    priority = dict(priority)
                    priority["Build road"] = max(int(priority.get("Build road", 3)), 8)
                    priority["Buy development_card"] = max(
                        int(priority.get("Buy development_card", 4)), 9
                    )
                    priority["Build settlement"] = max(
                        int(priority.get("Build settlement", 2)), 7
                    )
                    priority["Build city"] = max(int(priority.get("Build city", 1)), 6)
                    _defer_paid_road_for_tfr = bool(tfr_wants)
                    _defer_spend_for_dcard_play = True
            except Exception:
                _defer_paid_road_for_tfr = False
                _defer_spend_for_dcard_play = False

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

            # WP-TFR1 / WP-DCARD2: drop paid spend rows while DCard play is pending
            if _defer_paid_road_for_tfr or _defer_spend_for_dcard_play:
                _block = {"build road", "buy development_card"}
                if _defer_spend_for_dcard_play:
                    _block |= {"build settlement", "build city"}

                def _is_deferred_spend_row(row: Mapping[str, Any]) -> bool:
                    return str(row.get("action", "") or "").strip().lower() in _block

                actionable = [c for c in actionable if not _is_deferred_spend_row(c)]
                legal = [c for c in legal if not _is_deferred_spend_row(c)]
                try:
                    trace = getattr(self, "current_ai_decision_trace", None)
                    if not isinstance(trace, list):
                        trace = []
                        self.current_ai_decision_trace = trace
                    trace.append(
                        {
                            "kind": (
                                "wp_dcard2_defer_spend"
                                if _defer_spend_for_dcard_play
                                else "wp_tfr1_defer_paid_road"
                            ),
                            "reason": "dcard_plan_play_before_buy_build",
                        }
                    )
                except Exception:
                    pass

            # P1+Q2: off-way DCard — allow soft pick / block unguarded DCard fallback
            q2_allow = False
            q2_block_fallback = False
            try:
                from core.strategy_offway_q2 import q2_dcard_allowed, q2_dcard_blocked

                q2_allow = bool(q2_dcard_allowed(self))
                q2_block_fallback = bool(q2_dcard_blocked(self))
            except Exception:
                q2_allow = False
                q2_block_fallback = False

            def _is_dcard_row(row: Mapping[str, Any]) -> bool:
                n = str(row.get("action", "") or "").strip().lower()
                return "development" in n

            action_keys = {str(c.get("action", "") or "") for c in actionable}
            fallback_legal = [c for c in legal if str(c.get("action", "") or "") not in action_keys]
            if q2_block_fallback:
                fallback_legal = [c for c in fallback_legal if not _is_dcard_row(c)]

            # WP-RISK1: hand > 7 → prefer any spend (city/settle/road/buy) over waiting
            _hand_total = 0
            try:
                _p = self.get_current_player()
                if _p is not None:
                    hv = self._execution_hand_vector_for_player(_p)
                    _hand_total = int(sum(int(x or 0) for x in list(hv or [])[:5]))
                if _hand_total > 7:
                    priority = dict(priority)
                    for act in (
                        "Build city",
                        "Build settlement",
                        "Build road",
                        "Buy development_card",
                    ):
                        if act in priority:
                            priority[act] = min(int(priority.get(act) or 9), 2)
            except Exception:
                _hand_total = 0

            selected: List[Dict[str, Any]] = []
            for c in sorted(actionable, key=lambda row: priority.get(str(row.get("action", "") or ""), 99)):
                selected.append((dict(c) | {"_execution_source": "strategic"}))
            # P1+Q2: if nothing strategic, soft off-way DCard before other legal fallbacks
            if not selected and q2_allow:
                for c in legal:
                    if _is_dcard_row(c):
                        selected.append(
                            dict(c)
                            | {
                                "_execution_source": "q2_offway_dcard",
                                "strategic_reason": "P1+Q2 opportunistic off-way DCard (guards passed).",
                            }
                        )
                        break
            if not selected:
                for c in sorted(fallback_legal, key=lambda row: priority.get(str(row.get("action", "") or ""), 99)):
                    selected.append((dict(c) | {"_execution_source": "legal_fallback"}))
            # WP-RISK1: if still empty but hand>7, force first legal spend from full legal list
            if not selected and _hand_total > 7:
                for c in sorted(legal, key=lambda row: priority.get(str(row.get("action", "") or ""), 99)):
                    act = str(c.get("action", "") or "").strip().lower()
                    if act in (
                        "build city",
                        "build settlement",
                        "build road",
                        "buy development_card",
                    ):
                        selected.append(
                            dict(c)
                            | {
                                "_execution_source": "wp_risk1_discard_aversion",
                                "strategic_reason": "WP-RISK1: spend before end with hand>7",
                            }
                        )
                        break

            for idx, choice in enumerate(selected[:3], start=1):
                source = str(choice.get("_execution_source", "strategic") or "strategic")
                if source == "legal_fallback":
                    reason = "Legal now; no strategic action was available, so Slice C2 uses legal fallback."
                elif source == "q2_offway_dcard":
                    reason = str(
                        choice.get("strategic_reason")
                        or "P1+Q2 opportunistic off-way DCard (no L2)."
                    )
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
                        # Risk package only after strategy TwP/TwB (P0-R4 order)
                        risk_package = self._plan_ai_risk_package(step=1)
                        if isinstance(risk_package, Mapping) and risk_package.get("action"):
                            plan.append(dict(risk_package))
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
        self.current_ai_decision_trace = []
        # Post-roll DCard chooser (PR0): plan all cards, execute at most one
        # (fixed order knight→TFR→YOP→monopoly), then rebuild Continue plan.
        try:
            from core.ai_play_dcard_choice import maybe_execute_ai_dcard_choice

            maybe_execute_ai_dcard_choice(self, "post_roll")
        except Exception:
            pass
        self.current_ai_execution_plan = self._build_ai_continue_plan()
        # P0-R7: one-line support/trade trail for Events + Phase0
        try:
            self._record_support_trade_debug(
                plan=list(getattr(self, "current_ai_execution_plan", None) or []),
                emit_twitter=True,
            )
        except Exception:
            pass

    def plan_ai_play_knight(
        self,
        player: Optional[Player] = None,
        *,
        window: Optional[str] = None,
        log: bool = True,
        features_override: Optional[Mapping[str, Any]] = None,
        skip_robber_plan: bool = False,
    ) -> Dict[str, Any]:
        """AI Knight planner: gates + MVP play/hold/timing + shared robber plan."""
        from core.ai_play_knight import plan_ai_play_knight as _plan_ai_play_knight

        return _plan_ai_play_knight(
            self,
            player,
            window=window,
            log=log,
            features_override=features_override,
            skip_robber_plan=skip_robber_plan,
        )

    def execute_ai_play_knight_action(
        self,
        player: Optional[Player] = None,
        *,
        plan: Optional[Mapping[str, Any]] = None,
        window: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Thin AI Knight execute: consume card, LA, shared robber+steal, resume state."""
        from core.ai_play_knight import execute_ai_play_knight as _execute_ai_play_knight

        return _execute_ai_play_knight(
            self,
            player,
            plan=plan,
            window=window,
            force=force,
        )

    def plan_ai_play_tfr(
        self,
        player: Optional[Player] = None,
        *,
        window: Optional[str] = None,
        log: bool = True,
        features_override: Optional[Mapping[str, Any]] = None,
        skip_road_path: bool = False,
    ) -> Dict[str, Any]:
        """AI TFR planner: gates + MVP play/hold + free-road path attach."""
        from core.ai_play_tfr import plan_ai_play_tfr as _plan_ai_play_tfr

        return _plan_ai_play_tfr(
            self,
            player,
            window=window,
            log=log,
            features_override=features_override,
            skip_road_path=skip_road_path,
        )

    def execute_ai_play_tfr_action(
        self,
        player: Optional[Player] = None,
        *,
        plan: Optional[Mapping[str, Any]] = None,
        window: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Thin AI TFR execute: consume card, place free roads, re-scan for Continue."""
        from core.ai_play_tfr import execute_ai_play_tfr as _execute_ai_play_tfr

        return _execute_ai_play_tfr(
            self,
            player,
            plan=plan,
            window=window,
            force=force,
        )

    def plan_ai_play_yop(
        self,
        player: Optional[Player] = None,
        *,
        window: Optional[str] = None,
        log: bool = True,
        features_override: Optional[Mapping[str, Any]] = None,
        skip_resource_pair: bool = False,
    ) -> Dict[str, Any]:
        """AI YOP planner: gates + MVP play/hold + resource pair attach."""
        from core.ai_play_yop import plan_ai_play_yop as _plan_ai_play_yop

        return _plan_ai_play_yop(
            self,
            player,
            window=window,
            log=log,
            features_override=features_override,
            skip_resource_pair=skip_resource_pair,
        )

    def execute_ai_play_yop_action(
        self,
        player: Optional[Player] = None,
        *,
        plan: Optional[Mapping[str, Any]] = None,
        window: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Thin AI YOP execute: consume card, add two resources, re-scan for Continue."""
        from core.ai_play_yop import execute_ai_play_yop as _execute_ai_play_yop

        return _execute_ai_play_yop(
            self,
            player,
            plan=plan,
            window=window,
            force=force,
        )

    def plan_ai_play_monopoly(
        self,
        player: Optional[Player] = None,
        *,
        window: Optional[str] = None,
        log: bool = True,
        features_override: Optional[Mapping[str, Any]] = None,
        skip_resource_choice: bool = False,
    ) -> Dict[str, Any]:
        """AI Monopoly planner: gates + MVP play/hold + resource choice."""
        from core.ai_play_monopoly import plan_ai_play_monopoly as _plan_ai_play_monopoly

        return _plan_ai_play_monopoly(
            self,
            player,
            window=window,
            log=log,
            features_override=features_override,
            skip_resource_choice=skip_resource_choice,
        )

    def execute_ai_play_monopoly_action(
        self,
        player: Optional[Player] = None,
        *,
        plan: Optional[Mapping[str, Any]] = None,
        window: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Thin AI Monopoly execute: consume card, strip resource, re-scan for Continue."""
        from core.ai_play_monopoly import execute_ai_play_monopoly as _execute_ai_play_monopoly

        return _execute_ai_play_monopoly(
            self,
            player,
            plan=plan,
            window=window,
            force=force,
        )

    def plan_ai_dcard_choice(
        self,
        player: Optional[Player] = None,
        *,
        window: str = "post_roll",
        log: bool = True,
        allowed_cards: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Cross-card DCard chooser plan (normalized scores + HOLD; ≤1 play)."""
        from core.ai_play_dcard_choice import plan_ai_dcard_choice as _plan

        return _plan(
            self,
            player,
            window=window,
            log=log,
            allowed_cards=allowed_cards,
        )

    def maybe_execute_ai_dcard_choice(
        self,
        window: str = "post_roll",
        *,
        log: bool = True,
        allowed_cards: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Plan DCard choice and execute at most one card this turn."""
        from core.ai_play_dcard_choice import maybe_execute_ai_dcard_choice as _maybe

        return _maybe(
            self,
            window=window,
            log=log,
            allowed_cards=allowed_cards,
        )

    def ai_roll_to_preview(self) -> Dict[str, Any]:
        """AI Play step: optional pre-roll Knight, roll dice, stop before Continue."""
        if bool(getattr(self, "game_over", False)):
            return {"ok": False, "reason": "game_over", "already_over": True}
        if str(getattr(self, "phase", "")) != "Execution":
            return {"ok": False, "reason": "not_execution_phase"}
        if self._is_current_player_human_for_execution():
            return {"ok": False, "reason": "current_player_is_human"}

        try:
            from core.performance_trace import ai_pipeline_busy_scope, timed_span
        except Exception:
            ai_pipeline_busy_scope = None  # type: ignore
            timed_span = None  # type: ignore

        from contextlib import nullcontext

        busy_cm = (
            ai_pipeline_busy_scope(self, "ai_roll_to_preview")
            if ai_pipeline_busy_scope is not None
            else nullcontext()
        )
        span_cm = (
            timed_span(self, "ai_roll_to_preview", meta={})
            if timed_span is not None
            else nullcontext({})
        )

        with busy_cm, span_cm:
            knight_plan_pre = None
            knight_exec_pre = None
            if self._dice_has_been_rolled_for_execution():
                roll_result = dict(getattr(self, "last_execution_result", {}) or {})
                try:
                    self.refresh_strategy_after_event(
                        "ai_roll_to_preview_already_rolled", kind="turn_start"
                    )
                    self.refresh_viable_actions("ai_roll_to_preview_already_rolled")
                except Exception:
                    pass
            else:
                # Pre-roll DCard sub-chooser (PR4): Knight-only vs HOLD, then roll.
                try:
                    from core.ai_play_dcard_choice import maybe_execute_ai_dcard_choice

                    pre = maybe_execute_ai_dcard_choice(
                        self,
                        "pre_roll",
                        allowed_cards=("knight",),
                    )
                    knight_plan_pre = (pre.get("winner_plan") if isinstance(pre, dict) else None) or pre
                    knight_exec_pre = pre.get("execute_result") if isinstance(pre, dict) else None
                    if isinstance(pre, dict) and not pre.get("play"):
                        knight_exec_pre = None
                except Exception as exc:
                    knight_plan_pre = {"ok": False, "reason": str(exc), "window": "pre_roll"}
                    try:
                        from core.ai_play_knight import maybe_execute_ai_knight_for_window

                        pre = maybe_execute_ai_knight_for_window(self, "pre_roll")
                        knight_plan_pre = pre.get("planned")
                        knight_exec_pre = pre.get("executed_result")
                    except Exception:
                        try:
                            knight_plan_pre = self.plan_ai_play_knight(window="pre_roll")
                        except Exception:
                            pass
                roll_result = self.execute_roll_dice_action()

            self._mark_ai_preview_ready(reason="ai_roll_to_preview")
            result = {
                "ok": True,
                "action": "ai_roll_to_preview",
                "player_id": getattr(self.get_current_player(), "id", None),
                "roll_result": roll_result,
                "continue_available": self.ai_continue_is_available(),
                "current_ai_execution_plan": list(getattr(self, "current_ai_execution_plan", []) or []),
                "ai_knight_plan_pre_roll": knight_plan_pre
                if knight_plan_pre is not None
                else getattr(self, "last_ai_knight_plan_pre_roll", None),
                "ai_knight_execute_pre_roll": knight_exec_pre
                if knight_exec_pre is not None
                else None,
                "ai_knight_plan_post_roll": getattr(self, "last_ai_knight_plan_post_roll", None),
                "ai_knight_execute_post_roll": getattr(self, "last_ai_knight_execute_result", None)
                if knight_exec_pre is None
                else getattr(self, "last_ai_knight_execute_result", None),
                "ai_knight_plan": getattr(self, "last_ai_knight_plan", None),
            }
            # Prefer the execute result that belongs to post-roll when pre did not run.
            if knight_exec_pre is not None and bool(
                (knight_exec_pre or {}).get("executed") if isinstance(knight_exec_pre, dict) else False
            ):
                # Post-roll plan should not re-execute (dcard already played); keep last execute as pre.
                result["ai_knight_execute_post_roll"] = None
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

    def _apply_own_strategy_milestones_for_slice_d(
        self,
        reason: str,
        *,
        player: Optional[Player] = None,
        action_result: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """S1: own settle/city/LA/LR → force re-rank if legal actions remain else flag.

        Opponent settle/city is handled at build time via
        ``flag_opponents_after_structure`` (batched, one re-rank when consumed).
        """
        from core.strategy_sticky import (
            get_sticky_commitment,
            note_own_strategy_milestone,
            player_has_legal_actions,
        )

        out: Dict[str, Any] = {
            "ok": True,
            "modes": [],
            "reasons": [],
            "has_legal_actions": None,
        }
        if player is None:
            out["ok"] = False
            out["error"] = "no_player"
            return out

        reason_l = str(reason or "").lower()
        ar = dict(action_result or {}) if isinstance(action_result, Mapping) else {}
        milestone_hints: List[str] = []

        explicit = ar.get("own_strategy_milestone")
        if explicit:
            milestone_hints.append(str(explicit))

        # Settlement
        if (
            "own_settlement" in milestone_hints
            or "build_settlement" in reason_l
            or "build settlement" in reason_l
        ):
            tid = ar.get("target_id")
            sticky = get_sticky_commitment(player) or {}
            locked = sticky.get("locked_rec_target_id")
            try:
                is_rec = locked is not None and tid is not None and int(locked) == int(tid)
            except Exception:
                is_rec = False
            milestone_hints.append("own_rec_settle_complete" if is_rec else "own_settlement")

        # City
        if (
            "own_city" in milestone_hints
            or "build_city" in reason_l
            or "build city" in reason_l
        ):
            milestone_hints.append("own_city")

        # LA / LR acquisition (also set from recompute hooks)
        if ar.get("gained_largest_army") or "largest_army" in reason_l and "gain" in reason_l:
            milestone_hints.append("own_largest_army")
        if ar.get("gained_longest_road") or "longest_road" in reason_l and "gain" in reason_l:
            milestone_hints.append("own_longest_road")
        if ar.get("own_strategy_milestone") in ("own_largest_army", "own_longest_road"):
            milestone_hints.append(str(ar.get("own_strategy_milestone")))

        # De-dupe preserving order
        seen = set()
        reasons: List[str] = []
        for h in milestone_hints:
            key = str(h)
            if key in seen:
                continue
            if key in (
                "own_rec_settle_complete",
                "own_settlement",
                "own_city",
                "own_largest_army",
                "own_longest_road",
            ):
                seen.add(key)
                reasons.append(key)

        if not reasons:
            out["skipped"] = True
            return out

        has_acts = player_has_legal_actions(self, player)
        out["has_legal_actions"] = has_acts
        out["reasons"] = reasons
        for rsn in reasons:
            mode = note_own_strategy_milestone(
                self,
                player,
                rsn,
                has_legal_actions=has_acts,
                detail={"slice_d_reason": reason, "target_id": ar.get("target_id")},
            )
            out["modes"].append({"reason": rsn, "mode": mode})
        out["recalc_now"] = any(m.get("mode") == "recalc_now" for m in out["modes"])
        return out

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
        development-card play) makes the old scanner rows and Best-Action object
        stale.  Slice D normalizes the state, refreshes strategy context,
        refreshes viable-action scanner output, recomputes Best-Action, and then
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

        # W2: once a winner is declared, freeze further action-selection refresh.
        if bool(getattr(self, "game_over", False)):
            result["reason"] = "game_over"
            result["already_over"] = True
            result["ok"] = False
            result["win_result"] = getattr(self, "win_result", None)
            self.last_slice_d_result = result
            return result

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

        # S1: pre-scan so own milestones know whether legal actions remain.
        # Opponent settle/city only set a batched flag at build time; own
        # settle/city/LA/LR force re-rank only when actions remain, else flag.
        milestone_meta: Dict[str, Any] = {}
        scan = None
        scan_ok = True
        scan_error = ""
        try:
            scan = self.refresh_viable_actions(reason_text + "+s1_pre_scan")
        except Exception as exc:
            scan_ok = False
            scan_error = str(exc)

        try:
            milestone_meta = self._apply_own_strategy_milestones_for_slice_d(
                reason_text,
                player=player,
                action_result=action_result if isinstance(action_result, Mapping) else None,
            )
        except Exception as exc:
            milestone_meta = {"ok": False, "error": str(exc)}

        strategy_ok = True
        strategy_error = ""
        try:
            self.refresh_strategy_after_event(reason_text, kind="auto")
        except Exception as exc:
            strategy_ok = False
            strategy_error = str(exc)

        # Final scan after strategy (Best-Action / plan consumers)
        try:
            scan = self.refresh_viable_actions(reason_text)
            scan_ok = True
            scan_error = ""
        except Exception as exc:
            scan_ok = False
            scan_error = str(exc)

        # P1+Q1: affordable off-way settle/city → L2 once before BA (restricts L2)
        q1_status: Dict[str, Any] = {}
        try:
            from core.strategy_offway_q1 import maybe_q1_offway_structure_l2

            q1_status = maybe_q1_offway_structure_l2(
                self,
                player,
                reason=reason_text,
                rescan=True,  # inner post-L2 rescan rebuilds BA
            )
        except Exception as exc:
            q1_status = {"fired": False, "skipped": True, "reason": f"q1_error:{exc}"}

        # P1+Q2: opportunistic off-way DCard (no L2) after Q1
        q2_status: Dict[str, Any] = {}
        try:
            from core.strategy_offway_q2 import apply_q2_offway_dcard_permission

            q2_status = apply_q2_offway_dcard_permission(
                self, player, reason=reason_text
            )
        except Exception as exc:
            q2_status = {"allow": False, "reason": f"q2_error:{exc}"}

        try:
            viable_actions = scan.viable_actions() if scan is not None and hasattr(scan, "viable_actions") else []
        except Exception:
            viable_actions = []

        best_action = None
        try:
            best_action = self.get_current_best_executable_action()
        except Exception:
            best_action = None

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

        # Optional safety-net win check after any post-action package (W2).
        win_check: Dict[str, Any] = {}
        try:
            win_check = self._maybe_declare_winner_after(
                f"slice_d:{reason_text}",
                player,
            )
        except Exception:
            win_check = {"ok": False, "won": False, "reason": "win_check_exception"}

        result.update({
            "ok": not bool(getattr(self, "game_over", False)),
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
            "strategy_milestone": milestone_meta,
            "q1_offway_l2": dict(q1_status) if isinstance(q1_status, dict) else q1_status,
            "q2_offway_dcard": dict(q2_status) if isinstance(q2_status, dict) else q2_status,
            "viable_actions_after": viable_actions,
            "buy_build_choices_after": list(getattr(self, "current_execution_choices", []) or []),
            "actionable_choices_after": list(getattr(self, "current_actionable_choices", []) or []),
            "current_best_action": dict(best_action) if isinstance(best_action, Mapping) else best_action,
            "current_ai_execution_plan": list(getattr(self, "current_ai_execution_plan", []) or []),
            "win_check": win_check,
            "game_over": bool(getattr(self, "game_over", False)),
        })
        if bool(getattr(self, "game_over", False)):
            result["reason"] = "game_over"
            result["ok"] = False
            # Clear AI continue so the next frame cannot advance.
            try:
                self.ai_execution_preview_ready = False
                self.current_ai_execution_plan = []
                self.ai_execution_stage = "game_over"
            except Exception:
                pass
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
            from core import mglog

            mglog.log_twb(
                self,
                player,
                give_vec,
                get_vec,
                source=str(source or "twb"),
            )
        except Exception:
            pass

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

        H-B: persists ``offer_scan`` from the finder onto
        ``last_human_twp_offer_scan`` + history for Phase0/F9 dig-in.
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
            # H-B: always persist scan when present (including empty / no willing)
            try:
                from core.human_twp_offer_audit import (
                    format_human_twp_offer_scan_dbg_line,
                    persist_human_twp_offer_scan,
                )

                scan = found.get("offer_scan")
                if isinstance(scan, Mapping):
                    persist_human_twp_offer_scan(self, scan)
                    result["offer_scan"] = dict(
                        getattr(self, "last_human_twp_offer_scan", None) or scan
                    )
                    # H-D: quiet DBG summary + refresh PLAN strip
                    try:
                        dbg = format_human_twp_offer_scan_dbg_line(scan)
                        if dbg:
                            self.emit_twitter_event(
                                getattr(player, "id", None), dbg[:180]
                            )
                    except Exception:
                        pass
                    try:
                        from core.human_twp_policy import refresh_twp_debug_on_game

                        refresh_twp_debug_on_game(self)
                    except Exception:
                        pass
            except Exception:
                pass
            return result
        result["reason"] = "invalid_twp_option_scan_result"
        return result

    def cancel_human_twp_offer(self, reason: str = "panel_closed") -> Dict[str, Any]:
        """H-D: record cancel when HP closes TwP panel without OKY after a FIND scan.

        Safe no-op if no scan, or if the same scan already executed successfully.
        """
        result: Dict[str, Any] = {
            "ok": False,
            "action": "Human TwP cancel",
            "reason": str(reason or "panel_closed"),
        }
        try:
            from core.human_twp_offer_audit import (
                build_human_twp_offer_cancel_grant,
                format_human_twp_offer_grant_events_line,
                persist_human_twp_offer_grant,
            )

            grant = build_human_twp_offer_cancel_grant(self, reason=reason)
            if grant is None:
                result["reason"] = "nothing_to_cancel"
                return result
            persist_human_twp_offer_grant(self, grant)
            result["ok"] = True
            result["offer_grant"] = dict(grant)
            try:
                self.emit_twitter_event(
                    grant.get("proposer_id"),
                    format_human_twp_offer_grant_events_line(grant)[:180],
                )
            except Exception:
                pass
            try:
                from core.human_twp_policy import refresh_twp_debug_on_game

                refresh_twp_debug_on_game(self)
            except Exception:
                pass
            return result
        except Exception as exc:
            result["reason"] = f"cancel_failed:{exc}"
            return result

    def execute_human_twp_selected_option(self, option: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute one concrete TwP option after the human presses OKY.

        H-C: builds ``last_human_twp_offer_grant`` (selection mode, candidates,
        why-not-others) linked to ``last_human_twp_offer_scan``.
        """
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

        # H-C: pre-build grant skeleton from scan + selected option
        grant: Optional[Dict[str, Any]] = None
        try:
            from core.human_twp_offer_audit import (
                build_human_twp_offer_grant,
                persist_human_twp_offer_grant,
            )

            grant = build_human_twp_offer_grant(
                self,
                option=option,
                scan=getattr(self, "last_human_twp_offer_scan", None),
                executed=False,
                execute_ok=None,
                execute_reason="",
            )
        except Exception:
            grant = None

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
            if grant is not None:
                try:
                    from core.human_twp_offer_audit import (
                        build_human_twp_offer_grant,
                        format_human_twp_offer_grant_events_line,
                        persist_human_twp_offer_grant,
                    )

                    grant = build_human_twp_offer_grant(
                        self,
                        option=option,
                        scan=getattr(self, "last_human_twp_offer_scan", None),
                        executed=True,
                        execute_ok=False,
                        execute_reason=str(exc),
                    )
                    persist_human_twp_offer_grant(self, grant)
                    result["offer_grant"] = dict(grant)
                    try:
                        self.emit_twitter_event(
                            grant.get("proposer_id"),
                            format_human_twp_offer_grant_events_line(grant)[:180],
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
            return result
        if isinstance(executed, Mapping):
            result.update(dict(executed))

        # H-C: finalize grant with execute outcome
        try:
            from core.human_twp_offer_audit import (
                build_human_twp_offer_grant,
                format_human_twp_offer_grant_events_line,
                persist_human_twp_offer_grant,
            )

            ok = bool(result.get("ok"))
            grant = build_human_twp_offer_grant(
                self,
                option=option,
                scan=getattr(self, "last_human_twp_offer_scan", None),
                executed=True,
                execute_ok=ok,
                execute_reason=str(result.get("reason") or ("executed" if ok else "failed")),
            )
            persist_human_twp_offer_grant(self, grant)
            result["offer_grant"] = dict(grant)
            try:
                from core.human_twp_policy import refresh_twp_debug_on_game

                refresh_twp_debug_on_game(self)
            except Exception:
                pass
        except Exception:
            grant = None

        if bool(result.get("ok")):
            # Prefer H-C dig-in Events line; fall back to executor message
            try:
                line = ""
                if isinstance(grant, Mapping):
                    from core.human_twp_offer_audit import (
                        format_human_twp_offer_grant_events_line,
                    )

                    line = format_human_twp_offer_grant_events_line(grant)
                if not line:
                    line = str(result.get("message") or "TwP executed")
                self.emit_twitter_event(result.get("proposer_id"), line[:180])
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
        else:
            # Execute returned not-ok — still emit grant dig-in if built
            try:
                if isinstance(grant, Mapping):
                    from core.human_twp_offer_audit import (
                        format_human_twp_offer_grant_events_line,
                    )

                    self.emit_twitter_event(
                        grant.get("proposer_id") or result.get("proposer_id"),
                        format_human_twp_offer_grant_events_line(grant)[:180],
                    )
            except Exception:
                pass
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
        same target that Best-Action displays.
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

    def _filter_unowned_route_roads(
        self,
        roads: Sequence[Any],
        player: Optional[Player] = None,
    ) -> List[Tuple[int, int]]:
        """Drop path edges the seat already owns (stale sticky roads_fp).

        Without this, BA keeps preferring Build road → road-guard Wait even when
        the sticky settle is already connected and only needs a TwB/TwP unlock.
        """
        raw = [self._road_key_from_any(r) for r in list(roads or [])]
        keys = [r for r in raw if r]
        if not keys:
            return []
        player = player if player is not None else self.get_current_player()
        owned: set = set()
        try:
            from core.outlook_logic import player_owned_road_keys

            owned = set(player_owned_road_keys(self, player) or [])
        except Exception:
            for edge in list(getattr(player, "roads", None) or []):
                key = self._road_key_from_any(edge)
                if key:
                    owned.add(key)
        out: List[Tuple[int, int]] = []
        for r in keys:
            if r in owned:
                continue
            if r not in out:
                out.append(r)
        return out

    def _settlement_route_plan(self) -> Dict[str, Any]:
        """Return target-lock / route-lock metadata for next/new settlements.

        The planner can express a target as next_settlement@X or new_settlement@X
        with one or more roads_to_build.  This helper normalises those variants so
        Best-Action can execute the exact targeted road or settlement instead of a
        generic legal candidate. Owned path edges are stripped so a completed
        route promotes to settle-now (TwB/TwP can unlock the settle this turn).
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
        roads = self._filter_unowned_route_roads(
            self._route_roads_from_direction(direction)
        )

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
        # Path complete → settle now (same BA priority as next_settlement)
        if kind == "new_settlement" and not roads and target is not None:
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
            "best_action_label": target_label,
            "best_action_text": f"Wait / Prio: {target_label}",
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
        """Choose the same concrete candidate that Best-Action should execute.

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

    def _best_action_display_label(self, action: str, candidate: Mapping[str, Any]) -> str:
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
        source: str = "scanner_best_action",
        step: int = 1,
    ) -> Dict[str, Any]:
        """Wrap a scanner choice into the canonical Best-Action plan-item shape.

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
        display_label = self._best_action_display_label(action, candidate)
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
            "reason": str(concrete_choice.get("strategic_reason") or concrete_choice.get("reason") or "Canonical Best-Action scanner choice."),
            "choice": concrete_choice,
            "candidate": dict(candidate) if candidate else {},
            "source": source,
            "best_action_label": display_label,
            "best_action_text": f"{verb} {display_label}".strip(),
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
        """Map the preferred action-planner support action to an execution action.

        For ``new_settlement`` with remaining ``roads_to_build``, the immediate
        target is **Build road** (first route edge), not Build settlement.
        Settlement is only the target once the route is empty / already connected.
        This drives TwB / TwP unlock planning so bank/player trades buy Wood for
        the road instead of failing on an unplaceable distant settlement.
        """
        support = self._normalise_supporting_action_type(direction.get("supporting_action_type")) if isinstance(direction, Mapping) else ""
        if support == "city_upgrade":
            return "Build city"
        if support == "new_settlement":
            roads = self._route_roads_from_direction(direction) if isinstance(direction, Mapping) else []
            if not roads and isinstance(direction, Mapping):
                raw = direction.get("roads_to_build")
                if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, Mapping)):
                    roads = [r for r in list(raw) if r not in (None, "", [], ())]
            roads = self._filter_unowned_route_roads(roads)
            if roads:
                return "Build road"
            return "Build settlement"
        if support in {"next_settlement", "build_settlement"}:
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
            from core.human_twp_policy import normalize_proposal_key, proposal_key
            return normalize_proposal_key(proposal_key(proposal))
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

    def _plan_item_is_declined_incoming_twp(self, plan_item: Any) -> bool:
        """True when plan_item is Incoming TwP for a deal HP already declined this turn."""
        if not isinstance(plan_item, Mapping):
            return False
        if str(plan_item.get("action", "") or "") != "Incoming TwP":
            return False
        proposal = (
            plan_item.get("proposal")
            or plan_item.get("twp_proposal")
            or plan_item.get("candidate")
            or {}
        )
        try:
            from core.human_twp_policy import is_proposal_declined_this_turn

            return bool(is_proposal_declined_this_turn(self, proposal))
        except Exception:
            return False

    def _invalidate_stale_incoming_twp_after_decline(
        self,
        key: Any = None,
        proposal: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """T8-complete: drop frozen Best-Action / plan rows that re-open a declined deal.

        After HP declines, Continue must not re-execute a stale Incoming TwP item
        left in ``current_best_action`` or ``current_ai_execution_plan``.
        """
        try:
            from core.human_twp_policy import (
                is_proposal_declined_this_turn,
                normalize_proposal_key,
                proposal_key,
            )
        except Exception:
            is_proposal_declined_this_turn = None  # type: ignore
            normalize_proposal_key = None  # type: ignore
            proposal_key = None  # type: ignore

        def _matches(item: Any) -> bool:
            if not isinstance(item, Mapping):
                return False
            if str(item.get("action", "") or "") != "Incoming TwP":
                return False
            prop = item.get("proposal") or item.get("twp_proposal") or {}
            if is_proposal_declined_this_turn is not None:
                try:
                    if is_proposal_declined_this_turn(self, prop):
                        return True
                except Exception:
                    pass
            if key is not None and normalize_proposal_key is not None:
                try:
                    item_key = normalize_proposal_key(
                        item.get("proposal_key")
                        or (proposal_key(prop) if proposal_key else ())
                    )
                    return item_key == normalize_proposal_key(key)
                except Exception:
                    pass
            return False

        # Clear frozen Best-Action if it is the declined Incoming
        try:
            best = getattr(self, "current_best_action", None)
            if _matches(best):
                self.current_best_action = None
        except Exception:
            pass

        # Strip declined Incoming rows from the AI plan
        try:
            plan = list(getattr(self, "current_ai_execution_plan", None) or [])
            cleaned = [dict(x) for x in plan if isinstance(x, Mapping) and not _matches(x)]
            if not cleaned:
                # Prefer a non-TwP pass so Continue does not re-fire Incoming
                cleaned = [
                    {
                        "step": 1,
                        "action": "End turn",
                        "label": "Pass / End turn",
                        "status": "ready",
                        "reason": "T8: declined Incoming blocked; Continue for next AI action.",
                        "source": "pass_after_decline",
                        "round": getattr(self, "round", None),
                        "turn": getattr(self, "turn", None),
                        "state": getattr(self, "state", None),
                        "player_id": getattr(self.get_current_player(), "id", None)
                        if callable(getattr(self, "get_current_player", None))
                        else None,
                    }
                ]
            self.current_ai_execution_plan = cleaned
        except Exception:
            pass

        # Ensure no pending panel remains for the declined key
        try:
            pending = getattr(self, "pending_human_twp_offer", None)
            if isinstance(pending, Mapping) and pending.get("active"):
                p = pending.get("proposal") or {}
                if is_proposal_declined_this_turn is not None and is_proposal_declined_this_turn(
                    self, p
                ):
                    self.pending_human_twp_offer = None
        except Exception:
            pass

    def _play_project_sound(self, *sound_names: str) -> bool:
        """Best-effort project sound playback with ordered fallbacks.

        Returns True when a concrete sound object was found and play was requested.
        Game logic must never fail because pygame/mixer/sound assets are unavailable.

        Headless policy: ``NO_GUI_AT_ALL_TF=True`` → no sounds (same as no GUI).
        """
        keys = [str(name or "").strip() for name in sound_names if str(name or "").strip()]
        if not keys:
            return False

        # NO_GUI_AT_ALL_TF=True → silent (operator-owned; run_headless requires True).
        try:
            from core.console import is_no_gui

            if is_no_gui():
                return False
        except Exception:
            try:
                from core.constants import NO_GUI_AT_ALL_TF

                if bool(NO_GUI_AT_ALL_TF):
                    return False
            except Exception:
                pass

        # Prefer GUI-level sound API when available (NullGui no-ops).
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

        # Canonical choke-point (also re-checks NO_GUI / missing assets).
        try:
            from gui.gui_constants import play_sound as play_named_sound

            for i, key in enumerate(keys):
                fb = "BUTTON" if i == len(keys) - 1 else ""
                try:
                    if play_named_sound(key, fallback=fb):
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
            "best_action_label": label,
            "best_action_text": f"Offer HP TwP {label}",
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
        """Store one pending Manual-mode AI→HP TwP offer and optionally chime.

        T8-complete: refused when this exact deal was declined earlier this AI turn.
        """
        proposal_dict = dict(proposal or {})
        decision_dict = dict(policy_decision or {})
        key = self._human_twp_offer_key(proposal_dict)
        try:
            from core.human_twp_policy import is_proposal_declined_this_turn

            if is_proposal_declined_this_turn(self, proposal_dict):
                return {
                    "active": False,
                    "refused": True,
                    "reason": "human_twp_declined_this_turn",
                    "proposal_key": key,
                    "proposal": proposal_dict,
                }
        except Exception:
            pass
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

        # S7e: count a presented offer once when the key changes (surfaced to HP)
        if key and key != old_key:
            try:
                from core.game_statistics import bump_player_stat

                ai = self._player_by_id(proposal_dict.get("active_player_id"))
                if ai is not None:
                    counted = getattr(self, "_s7e_twp_proposed_keys", None)
                    if not isinstance(counted, set):
                        counted = set()
                        self._s7e_twp_proposed_keys = counted
                    if key not in counted:
                        bump_player_stat(ai, "stats_twp_proposed", 1)
                        counted.add(key)
            except Exception:
                pass

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

    def begin_human_twp_counter(self) -> Dict[str, Any]:
        """T10: open counter builder; park Incoming K0 (do not T8-decline yet)."""
        from core.human_twp_policy import (
            MODE_MANUAL,
            draft_from_proposal,
            get_human_twp_mode,
            normalize_proposal_key,
            proposal_hits_twp_endgame_freeze,
            proposal_key,
        )

        if get_human_twp_mode(self) != MODE_MANUAL:
            return {"ok": False, "reason": "not_manual_mode"}
        pending = getattr(self, "pending_human_twp_offer", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return {"ok": False, "reason": "no_pending_incoming"}
        proposal = dict(pending.get("proposal") or {})
        if not proposal:
            return {"ok": False, "reason": "empty_proposal"}
        hit, why, _meta = proposal_hits_twp_endgame_freeze(self, proposal)
        if hit:
            return {"ok": False, "reason": why or "t9_freeze"}
        try:
            key = normalize_proposal_key(
                pending.get("proposal_key") or proposal_key(proposal)
            )
        except Exception:
            key = proposal_key(proposal)
        draft = draft_from_proposal(proposal)
        self.pending_twp_counter = {
            "active": True,
            "original_proposal": proposal,
            "original_key": list(key),
            "parked_incoming": dict(pending),
            "draft": dict(draft),
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
        }
        # Incoming inactive while builder open (parked in counter state)
        self.pending_human_twp_offer = None
        result = {
            "ok": True,
            "reason": "counter_opened",
            "action": "counter_opened",
            "draft": dict(draft),
            "original_key": list(key),
        }
        self.last_twp_counter_result = dict(result)
        # T10-C: quiet dig-in (DBG) + refresh PLAN snapshot
        try:
            hp_id = proposal.get("counterparty_id")
            ai_id = proposal.get("active_player_id")
            self.emit_twitter_event(
                hp_id,
                f"DBG: opened TwP counter vs P{ai_id}",
            )
        except Exception:
            pass
        try:
            from core.human_twp_policy import refresh_twp_debug_on_game

            refresh_twp_debug_on_game(self)
        except Exception:
            pass
        return result

    def reset_human_twp_counter_draft(self) -> Dict[str, Any]:
        """T10: Reset Counter — draft back to original K0 values."""
        from core.human_twp_policy import draft_from_proposal

        pending = getattr(self, "pending_twp_counter", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return {"ok": False, "reason": "no_active_counter"}
        original = dict(pending.get("original_proposal") or {})
        draft = draft_from_proposal(original)
        pending = dict(pending)
        pending["draft"] = dict(draft)
        self.pending_twp_counter = pending
        result = {"ok": True, "reason": "draft_reset", "action": "draft_reset", "draft": dict(draft)}
        self.last_twp_counter_result = dict(result)
        try:
            from core.human_twp_policy import refresh_twp_debug_on_game

            refresh_twp_debug_on_game(self)
        except Exception:
            pass
        return result

    def back_from_human_twp_counter(self) -> Dict[str, Any]:
        """T10: Back — restore Incoming with original K0 (COUNTER never pressed)."""
        pending = getattr(self, "pending_twp_counter", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return {"ok": False, "reason": "no_active_counter"}
        parked = pending.get("parked_incoming")
        original = dict(pending.get("original_proposal") or {})
        if isinstance(parked, Mapping) and parked:
            restore = dict(parked)
            restore["active"] = True
            if not restore.get("proposal"):
                restore["proposal"] = original
            self.pending_human_twp_offer = restore
        else:
            self.pending_human_twp_offer = {
                "active": True,
                "proposal": original,
                "proposal_key": pending.get("original_key"),
                "policy_decision": {"status": "pending_manual", "restored_from_counter": True},
            }
        self.pending_twp_counter = None
        result = {
            "ok": True,
            "reason": "back_to_incoming",
            "action": "back_to_incoming",
            "restored": True,
        }
        self.last_twp_counter_result = dict(result)
        try:
            from core.human_twp_policy import refresh_twp_debug_on_game

            refresh_twp_debug_on_game(self)
        except Exception:
            pass
        return result

    def return_human_twp_counter(self, draft: Any = None) -> Dict[str, Any]:
        """T10: Return Counter — send draft to AI; Accept (T7) or Decline from scratch."""
        from core.human_twp_policy import (
            build_counter_proposal,
            evaluate_ai_response_to_human_counter,
            normalize_proposal_key,
            proposal_key,
            register_human_twp_accept,
            register_human_twp_decline,
            validate_twp_counter_draft,
        )

        pending = getattr(self, "pending_twp_counter", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return {"ok": False, "reason": "no_active_counter"}
        original = dict(pending.get("original_proposal") or {})
        if draft is None:
            draft = pending.get("draft") or {}
        draft = dict(draft or {})
        # Keep draft on state for dig-in
        try:
            p2 = dict(pending)
            p2["draft"] = draft
            self.pending_twp_counter = p2
        except Exception:
            pass

        v = validate_twp_counter_draft(self, original, draft)
        if not v.get("ok"):
            result = {
                "ok": False,
                "reason": v.get("reason") or "invalid_draft",
                "validation": dict(v),
            }
            self.last_twp_counter_result = dict(result)
            return result

        proposal = dict(v.get("proposal") or build_counter_proposal(original, draft))
        same = bool(v.get("same_as_original"))

        # Clear counter UI state before continue (avoid re-entry)
        self.pending_twp_counter = None
        self.pending_human_twp_offer = None

        label = self._format_twp_proposal_label(proposal)
        orig_label = self._format_twp_proposal_label(original)
        hp_id = proposal.get("counterparty_id")
        ai_id = proposal.get("active_player_id")

        if same:
            # Locked: Return of identical draft = ACCEPT original (T7)
            try:
                self.accepted_binding_proposal = dict(original)
                self.human_twp_accepted_this_turn.add(
                    normalize_proposal_key(proposal_key(original))
                )
                register_human_twp_accept(self, original)
            except Exception:
                pass
            try:
                self.emit_twitter_event(
                    hp_id,
                    f"returned original TwP (accept) to P{ai_id}: {orig_label}",
                )
            except Exception:
                pass
            cont = self._continue_ai_twp_after_human_response(
                accepted=True,
                original_proposal=original,
                original_label=orig_label,
            )
            result = {
                "ok": True,
                "action": "return_counter_same_as_original",
                "accepted": True,
                "same_as_original": True,
                "proposal": dict(original),
                "continue_result": dict(cont or {}),
            }
            self.last_twp_counter_result = dict(result)
            self.last_human_twp_response_result = dict(result)
            try:
                from core.human_twp_policy import refresh_twp_debug_on_game

                refresh_twp_debug_on_game(self)
            except Exception:
                pass
            return result

        decision = evaluate_ai_response_to_human_counter(self, proposal)
        if bool(decision.get("accept")):
            try:
                self.accepted_binding_proposal = dict(proposal)
                k1 = normalize_proposal_key(proposal_key(proposal))
                self.human_twp_accepted_this_turn.add(k1)
                register_human_twp_accept(self, proposal)
            except Exception:
                pass
            try:
                self.emit_twitter_event(
                    hp_id, f"countered TwP to P{ai_id}: {label}"
                )
                self.emit_twitter_event(
                    ai_id, f"accepted counter from P{hp_id}: {label}"
                )
            except Exception:
                pass
            try:
                self.record_turn_event(
                    player_id=ai_id,
                    event_type="TwP counter accepted",
                    category="TwP",
                    target_player_id=hp_id,
                    resource_delta={},
                    public=True,
                    source="return_human_twp_counter",
                    reason="ai_accepted_counter",
                    message=f"P{ai_id} accepted counter from P{hp_id}: {label}",
                    metadata={"proposal": dict(proposal), "decision": dict(decision)},
                )
            except Exception:
                pass
            cont = self._continue_ai_twp_after_human_response(
                accepted=True,
                original_proposal=proposal,
                original_label=label,
            )
            result = {
                "ok": True,
                "action": "return_counter_accepted",
                "accepted": True,
                "proposal": dict(proposal),
                "decision": dict(decision),
                "continue_result": dict(cont or {}),
            }
            self.last_twp_counter_result = dict(result)
            self.last_human_twp_response_result = dict(result)
            try:
                from core.human_twp_policy import refresh_twp_debug_on_game

                refresh_twp_debug_on_game(self)
            except Exception:
                pass
            return result

        # AI declined counter — block K1 and K0 (locked Q1); continue from scratch
        try:
            if not isinstance(getattr(self, "human_twp_declined_this_turn", None), set):
                self.human_twp_declined_this_turn = set(
                    getattr(self, "human_twp_declined_this_turn", []) or []
                )
            k0 = normalize_proposal_key(proposal_key(original))
            k1 = normalize_proposal_key(proposal_key(proposal))
            self.human_twp_declined_this_turn.add(k0)
            self.human_twp_declined_this_turn.add(k1)
            register_human_twp_decline(self, proposal)
            register_human_twp_decline(self, original)
        except Exception:
            pass
        try:
            self.emit_twitter_event(
                hp_id, f"countered TwP to P{ai_id}: {label}"
            )
            self.emit_twitter_event(
                ai_id, f"declined counter from P{hp_id}: {label}"
            )
        except Exception:
            pass
        # T10-C: public ledger note (no resource delta)
        try:
            self.record_turn_event(
                player_id=hp_id,
                event_type="TwP counter declined",
                category="TwP",
                target_player_id=ai_id,
                resource_delta={},
                public=True,
                source="return_human_twp_counter",
                reason="ai_declined_counter",
                message=f"P{ai_id} declined counter from P{hp_id}: {label}",
                metadata={
                    "proposal": dict(proposal),
                    "original": dict(original),
                    "decision": dict(decision),
                },
            )
        except Exception:
            pass
        cont = self._continue_ai_twp_after_human_response(
            accepted=False,
            original_proposal=proposal,
            original_label=label,
        )
        result = {
            "ok": True,
            "action": "return_counter_declined",
            "accepted": False,
            "proposal": dict(proposal),
            "decision": dict(decision),
            "continue_result": dict(cont or {}),
            "reason": "ai_declined_counter_start_from_scratch",
        }
        self.last_twp_counter_result = dict(result)
        self.last_human_twp_response_result = dict(result)
        try:
            from core.human_twp_policy import refresh_twp_debug_on_game

            refresh_twp_debug_on_game(self)
        except Exception:
            pass
        return result

    def update_human_twp_counter_draft(self, draft: Mapping[str, Any]) -> Dict[str, Any]:
        """Update in-progress counter draft (GUI steppers)."""
        pending = getattr(self, "pending_twp_counter", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return {"ok": False, "reason": "no_active_counter"}
        pending = dict(pending)
        pending["draft"] = dict(draft or {})
        self.pending_twp_counter = pending
        try:
            from core.human_twp_policy import refresh_twp_debug_on_game

            refresh_twp_debug_on_game(self)
        except Exception:
            pass
        return {"ok": True, "draft": dict(pending["draft"])}

    def respond_to_pending_human_twp_offer(self, accepted: bool) -> Dict[str, Any]:
        """Handle HP ACCEPT/DECLINE for the incoming AI→HP TwP panel.

        T7 ACCEPT: binds this concrete deal (resources + partner). AI executes
        that binding if still legal; does not silently re-rank to another package.
        T8 DECLINE: blocks this exact proposal key for the rest of the AI turn.
        """
        pending = getattr(self, "pending_human_twp_offer", None)
        if not isinstance(pending, Mapping) or not pending.get("active"):
            result = {"ok": False, "reason": "no_pending_human_twp_offer"}
            self.last_human_twp_response_result = result
            return result

        proposal = dict(pending.get("proposal") or {})
        try:
            from core.human_twp_policy import normalize_proposal_key, proposal_key as _pk

            key = normalize_proposal_key(
                pending.get("proposal_key") or _pk(proposal) or self._human_twp_offer_key(proposal)
            )
        except Exception:
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
            # T7: stash the exact accepted deal for execute-first
            try:
                self.accepted_binding_proposal = dict(proposal)
            except Exception:
                pass
            response_text = "accepted"
            try:
                from core.human_twp_policy import register_human_twp_accept

                register_human_twp_accept(self, proposal)
            except Exception:
                pass
        else:
            # T8-complete: exact-key set + v045 dual-write + invalidate Best-Action
            try:
                from core.human_twp_policy import remember_human_twp_decline

                key = remember_human_twp_decline(self, proposal) or key
            except Exception:
                self.human_twp_declined_this_turn.add(key)
            self.human_twp_accepted_this_turn.discard(key)
            try:
                self.accepted_binding_proposal = None
            except Exception:
                pass
            response_text = "declined"
            try:
                from core.human_twp_policy import register_human_twp_decline

                register_human_twp_decline(self, proposal)
            except Exception:
                pass
            try:
                self._invalidate_stale_incoming_twp_after_decline(key, proposal)
            except Exception:
                pass

        self.pending_human_twp_offer = None

        # Events / Twitter: always surface HP decline (and accept) clearly.
        # G6: do not prefix a second "P4:" — strip leading actor from label.
        try:
            short = str(label or "").strip()
            for prefix in (f"P{ai_id}:", f"P{ai_id} "):
                if short.startswith(prefix):
                    short = short[len(prefix) :].strip()
                    break
            if accepted:
                tweet = f"accepted TwP from P{ai_id}: {short}"
            else:
                tweet = f"declined TwP from P{ai_id}: {short}"
            self.emit_twitter_event(hp_id, tweet)
        except Exception:
            pass

        # Ledger: public note for decline (zero resource delta; feed/history only)
        if not accepted:
            try:
                self.record_turn_event(
                    player_id=hp_id,
                    event_type="TwP declined",
                    category="TwP",
                    target_player_id=ai_id,
                    resource_delta={},
                    public=True,
                    source="respond_to_pending_human_twp_offer",
                    reason="human_declined_incoming_twp",
                    message=f"P{hp_id} declined TwP from P{ai_id}: {label}",
                    metadata={
                        "declined": True,
                        "proposal": dict(proposal),
                        "proposal_key": list(key) if key else [],
                        "label": label,
                    },
                )
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

    def _make_bound_twp_plan_item(
        self,
        proposal: Mapping[str, Any],
        *,
        step: int = 1,
        reason: str = "T7: execute HP-accepted binding",
    ) -> Dict[str, Any]:
        """Build an executable TwP plan row for a concrete accepted binding."""
        p = dict(proposal or {})
        label = self._format_twp_proposal_label(p)
        return {
            "step": step,
            "action": "TwP",
            "label": f"TwP {label}",
            "status": "will_try",
            "reason": reason,
            "source": "accepted_binding_t7",
            "proposal": p,
            "twp_proposal": p,
            "candidate": p,
            "human_twp_policy_decision": {
                "status": "accepted_manual_bound",
                "accepted": True,
                "binding": True,
                "reason": "t7_execute_bound_deal",
            },
            "best_action_label": label,
            "best_action_text": f"TwP {label} (HP accepted)",
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": p.get("active_player_id"),
        }

    def _continue_ai_twp_after_human_response(
        self,
        *,
        accepted: bool,
        original_proposal: Mapping[str, Any],
        original_label: str,
    ) -> Dict[str, Any]:
        """After HP responds: T7 execute binding on accept; T8 no re-offer on decline.

        On **decline**: never auto-execute a TwP deal in the same click (that would
        play CashRegister / DEAL and look like the declined trade succeeded).
        Only open a *different* Incoming offer, or rebuild the Continue plan.
        On **accept (T7)**: execute the exact accepted proposal if still legal;
        only re-plan if the binding is no longer executable.
        """
        player = self.get_current_player()
        if player is None:
            return {"ok": False, "reason": "no_current_player_after_human_twp_response"}
        if self._is_current_player_human_for_execution():
            return {"ok": False, "reason": "current_player_is_human_after_human_twp_response"}

        # T7: ACCEPT binds the concrete deal — execute first, no partner switch
        if accepted:
            binding = dict(
                getattr(self, "accepted_binding_proposal", None)
                or original_proposal
                or {}
            )
            if binding:
                bound_plan = self._make_bound_twp_plan_item(binding, step=1)
                try:
                    self.emit_twitter_event(
                        getattr(player, "id", None),
                        f"DBG: HP accepted binding; AI executes {self._format_twp_proposal_label(binding)}.",
                    )
                except Exception:
                    pass
                executed = self._execute_ai_twp_support_plan(player, bound_plan)
                if bool(executed.get("ok")):
                    try:
                        self.accepted_binding_proposal = None
                        self.human_twp_accepted_this_turn = set()
                    except Exception:
                        pass
                    slice_d_result = None
                    try:
                        slice_d_result = self.continue_action_selection_after_action(
                            "after_human_twp_binding_accept",
                            player=player,
                            action_result=dict(executed),
                            clear_forced_locks=True,
                        )
                    except Exception as exc:
                        slice_d_result = {"ok": False, "reason": str(exc)}
                    return {
                        "ok": True,
                        "action": "AI TwP bound execute after human accept",
                        "accepted_by_hp": True,
                        "binding_used": True,
                        "original_offer": dict(original_proposal or {}),
                        "original_label": original_label,
                        "chosen_plan": dict(bound_plan),
                        "executed_result": dict(executed),
                        "slice_d": dict(slice_d_result or {}),
                        "reason": "t7_executed_accepted_binding",
                    }
                # Binding illegal (cards moved / freeze) — clear and fall through
                try:
                    self.accepted_binding_proposal = None
                    from core.human_twp_policy import normalize_proposal_key, proposal_key

                    k = normalize_proposal_key(proposal_key(binding))
                    self.human_twp_accepted_this_turn.discard(k)
                except Exception:
                    pass
                try:
                    self.emit_twitter_event(
                        getattr(player, "id", None),
                        f"DBG: accepted TwP binding not executable ({executed.get('reason')}); re-planning.",
                    )
                except Exception:
                    pass

        plan = self._plan_ai_trade_with_player_for_strategy(step=1)
        # T8: never re-open Incoming for the same declined key
        if isinstance(plan, Mapping) and str(plan.get("action", "") or "") == "Incoming TwP":
            try:
                from core.human_twp_policy import (
                    is_proposal_declined_this_turn,
                    normalize_proposal_key,
                    proposal_key,
                )

                next_prop = plan.get("proposal") or {}
                if (not accepted) and is_proposal_declined_this_turn(self, next_prop):
                    plan = None  # force rebuild without this Incoming
                elif accepted:
                    # After accept re-plan, do not re-open Incoming for the same binding key
                    orig_k = normalize_proposal_key(proposal_key(original_proposal))
                    next_k = normalize_proposal_key(proposal_key(next_prop))
                    if orig_k and orig_k == next_k:
                        plan = None
            except Exception:
                pass

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
                "accepted_by_hp": bool(accepted),
            }

        # Decline: do not auto-execute TwP (no CashRegister on decline).
        if not accepted:
            try:
                # Re-assert decline memory + clear stale Incoming Best-Action before replan
                try:
                    from core.human_twp_policy import (
                        normalize_proposal_key,
                        proposal_key,
                        remember_human_twp_decline,
                    )

                    remember_human_twp_decline(self, original_proposal)
                    self._invalidate_stale_incoming_twp_after_decline(
                        normalize_proposal_key(proposal_key(original_proposal)),
                        original_proposal,
                    )
                except Exception:
                    pass
                self.current_ai_execution_plan = self._build_ai_continue_plan()
                # If rebuild still surfaces declined Incoming, strip to non-TwP plan
                try:
                    from core.human_twp_policy import is_proposal_declined_this_turn

                    cur = list(getattr(self, "current_ai_execution_plan", []) or [])
                    if cur and str(cur[0].get("action", "") or "") == "Incoming TwP":
                        prop0 = cur[0].get("proposal") or {}
                        if is_proposal_declined_this_turn(self, prop0):
                            self.current_ai_execution_plan = [{
                                "step": 1,
                                "action": "End turn",
                                "label": "Pass / End turn",
                                "status": "ready",
                                "reason": "T8: declined deal blocked; no alternate TwP this click.",
                                "source": "pass_after_decline",
                            }]
                            self.current_best_action = None
                except Exception:
                    pass
                # Final sweep: never leave declined Incoming as Best-Action
                try:
                    self._invalidate_stale_incoming_twp_after_decline(
                        None, original_proposal
                    )
                except Exception:
                    pass
                self.ai_execution_preview_ready = True
                self.ai_execution_preview_player_id = getattr(player, "id", None)
                self.ai_execution_stage = "preview_ready_after_human_twp_decline"
            except Exception:
                pass
            try:
                self.emit_twitter_event(
                    getattr(player, "id", None),
                    "DBG: HP declined TwP; no auto-deal this click (Continue for next AI action).",
                )
            except Exception:
                pass
            return {
                "ok": True,
                "action": "No auto TwP after human decline",
                "accepted_by_hp": False,
                "original_offer": dict(original_proposal or {}),
                "original_label": original_label,
                "reason": "decline_skips_auto_twp_execute_no_cash_register",
                "plan_after": (
                    dict(self.current_ai_execution_plan[0])
                    if list(getattr(self, "current_ai_execution_plan", None) or [])
                    else None
                ),
            }

        # Accept fallback: re-plan only when binding failed (AI↔AI only preferred)
        if isinstance(plan, Mapping) and str(plan.get("action", "") or "") == "TwP":
            try:
                self.emit_twitter_event(
                    getattr(player, "id", None),
                    f"DBG: binding failed; AI re-plan chooses {self._format_twp_proposal_label(plan.get('proposal') or {})}.",
                )
            except Exception:
                pass
            executed = self._execute_ai_twp_support_plan(player, plan)
            try:
                self.human_twp_accepted_this_turn = set()
                self.accepted_binding_proposal = None
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
                "binding_used": False,
                "original_offer": dict(original_proposal),
                "original_label": original_label,
                "chosen_plan": dict(plan),
                "executed_result": dict(executed),
                "slice_d": dict(slice_d_result or {}),
                "reason": "t7_binding_failed_replanned",
            }

        # No TwP remains.  Rebuild the displayed AI plan; Continue can now choose
        # TwB or pass/end turn using the normal flow.
        try:
            self.current_ai_execution_plan = self._build_ai_continue_plan()
            self.ai_execution_preview_ready = True
            self.ai_execution_preview_player_id = getattr(player, "id", None)
            self.ai_execution_stage = "preview_ready_after_human_twp_response"
            self.accepted_binding_proposal = None
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

        try:
            from core.human_twp_policy import clear_twp_skip_reasons, record_twp_skip_reason
        except Exception:
            def clear_twp_skip_reasons(_g):  # type: ignore
                return None

            def record_twp_skip_reason(_g, _r):  # type: ignore
                return None

        clear_twp_skip_reasons(self)

        pending_plan = self._pending_human_twp_response_plan(step=step)
        if isinstance(pending_plan, Mapping):
            return dict(pending_plan)

        player = self.get_current_player()
        if player is None:
            record_twp_skip_reason(self, "no_current_player")
            return None

        scan = getattr(self, "current_viable_action_scan", None)
        if isinstance(scan, Mapping) and scan.get("forced_action_mode"):
            record_twp_skip_reason(self, "forced_action_mode")
            return None

        try:
            from core.player_trade import find_twp_proposals
            from core.human_twp_policy import resolve_incoming_human_twp_offer
        except Exception:
            record_twp_skip_reason(self, "twp_import_failed")
            return None

        try:
            from core.performance_trace import timed_span as _twp_span
        except Exception:
            _twp_span = None  # type: ignore
        from contextlib import nullcontext as _null_cm

        with (
            _twp_span(self, "twp_find", meta={"player_id": getattr(player, "id", None)})
            if _twp_span is not None
            else _null_cm({})
        ):
            try:
                # Include HP in the candidate scan, then route any HP-involved offer
                # through the Human TwP Mode policy (T4: Auto keep/ditch + rules).
                proposals = find_twp_proposals(
                    self,
                    player,
                    max_candidates=20,
                    include_human_counterparties=True,
                )
            except Exception as exc:
                record_twp_skip_reason(self, f"find_twp_failed:{exc}")
                try:
                    self.emit_twitter_event(getattr(player, "id", None), f"DBG: TwP planner failed ({exc})."[:180])
                except Exception:
                    pass
                return None

            if not proposals:
                # T11: structured diagnosis instead of bare no_mutual only
                diag = list(getattr(self, "last_twp_empty_diagnosis", None) or [])
                if diag:
                    for r in diag:
                        record_twp_skip_reason(self, str(r))
                else:
                    record_twp_skip_reason(self, "no_mutual")
                # T1-B/T11: belt-and-suspenders unlock with live_need override
                try:
                    from core.player_trade import (
                        find_unlock_twp_proposals,
                        resolve_live_need_for_twp,
                    )

                    _act, cost_v, need_v = resolve_live_need_for_twp(self, player)
                    proposals = list(
                        find_unlock_twp_proposals(
                            self,
                            player,
                            max_candidates=12,
                            include_human_counterparties=True,
                            live_need=need_v if sum(need_v) > 0 else None,
                            primary_cost=cost_v if sum(need_v) > 0 else None,
                            primary_action=_act or None,
                        )
                        or []
                    )
                    if proposals:
                        record_twp_skip_reason(self, "unlock_fallback")
                except Exception:
                    pass
                # WP-TWP2: invent surplus→need unlocks when scanner still empty
                if not proposals:
                    try:
                        from core.rcard_optimizer import invent_unlock_twp_offers

                        inv = invent_unlock_twp_offers(self, player)
                        proposals = list(inv.get("proposals") or [])
                        if proposals:
                            record_twp_skip_reason(self, "wp_twp2_invent")
                            try:
                                self.last_twp_invent = {
                                    "n": len(proposals),
                                    "note": inv.get("note"),
                                    "fully_unlocks_any": inv.get("fully_unlocks_any"),
                                }
                            except Exception:
                                pass
                    except Exception:
                        pass
            else:
                # Dig-in: note when pool includes unlock-sourced packages
                try:
                    if any(
                        str((getattr(p, "market_snapshot", None) or {}).get("source") or "")
                        in {"unlock", "both", "unlock_fallback"}
                        for p in proposals
                    ):
                        # Soft note only; do not override stronger skip reasons later
                        pass
                except Exception:
                    pass

            # WP-TWP2: always merge invented unlocks into the candidate pool
            try:
                from core.rcard_optimizer import invent_unlock_twp_offers

                inv = invent_unlock_twp_offers(self, player)
                extra = list(inv.get("proposals") or [])
                if extra:
                    seen_k = set()
                    for p in list(proposals or []):
                        try:
                            d = p.as_dict() if hasattr(p, "as_dict") else {}
                            seen_k.add(
                                (
                                    int(d.get("counterparty_id") or -1),
                                    int(d.get("active_give_index") or -1),
                                    int(d.get("active_receive_index") or -1),
                                )
                            )
                        except Exception:
                            continue
                    added = 0
                    for p in extra:
                        try:
                            d = p.as_dict() if hasattr(p, "as_dict") else {}
                            key = (
                                int(d.get("counterparty_id") or -1),
                                int(d.get("active_give_index") or -1),
                                int(d.get("active_receive_index") or -1),
                            )
                        except Exception:
                            continue
                        if key in seen_k:
                            continue
                        seen_k.add(key)
                        proposals.append(p)
                        added += 1
                    if added:
                        record_twp_skip_reason(self, f"wp_twp2_invent_merge:{added}")
            except Exception:
                pass

        policy_routed = []
        skipped_policy = []
        try:
            from core.human_twp_policy import (
                is_proposal_declined_this_turn,
                proposal_hits_twp_endgame_freeze,
            )
        except Exception:
            def is_proposal_declined_this_turn(_g, _p):  # type: ignore
                return False

            def proposal_hits_twp_endgame_freeze(_g, _p, **_k):  # type: ignore
                return False, "", {}

        for proposal in list(proposals or []):
            # T8 hard filter before policy (belt + suspenders vs key mismatch)
            try:
                if is_proposal_declined_this_turn(self, proposal):
                    record_twp_skip_reason(self, "declined_this_turn")
                    skipped_policy.append({
                        "status": "rejected",
                        "reason": "human_twp_manual_mode_hp_declined_this_offer",
                    })
                    continue
            except Exception:
                pass
            # T9 hard filter for AI↔AI too (resolve also freezes human path)
            try:
                freeze, freeze_reason, _meta = proposal_hits_twp_endgame_freeze(self, proposal)
                if freeze:
                    record_twp_skip_reason(self, freeze_reason or "endgame_twp_freeze")
                    skipped_policy.append({
                        "status": "rejected",
                        "reason": freeze_reason or "endgame_twp_freeze",
                    })
                    continue
            except Exception:
                pass
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
                    # T8: never open Incoming for a declined key
                    if is_proposal_declined_this_turn(self, p_dict):
                        record_twp_skip_reason(self, "declined_this_turn")
                        skipped_policy.append(dict(decision))
                        continue
                    self._set_pending_human_twp_offer(p_dict, decision, play_sound=True)
                    return self._make_incoming_human_twp_plan_item(p_dict, decision, step=step)

                if not bool(decision.get("accepted", False)):
                    skipped_policy.append(dict(decision))
                    reason = str(decision.get("reason") or "human_policy_reject")
                    if "red" in reason:
                        record_twp_skip_reason(self, "human_red")
                    elif "cooldown" in reason:
                        record_twp_skip_reason(self, "pattern_cooldown")
                    elif "freeze" in reason:
                        record_twp_skip_reason(self, reason[:48])
                    elif "auto" in reason:
                        record_twp_skip_reason(self, f"human_auto:{reason.split(':')[-1][:40]}")
                    else:
                        record_twp_skip_reason(self, reason[:48])
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
            if not proposals:
                pass  # already recorded no_mutual (and unlock fallback empty)
            elif skipped_policy and not any(
                str(s.get("reason", "")).startswith("human") for s in skipped_policy
            ):
                record_twp_skip_reason(self, "no_auto_executable")
            elif skipped_policy:
                record_twp_skip_reason(self, "all_filtered_by_policy")
            else:
                record_twp_skip_reason(self, "no_executable_twp")
            return None

        hand_before = self._execution_hand_vector_for_player(player)
        # T1: keep/ditch for ranking (prefer ditch-funded unlocks over keep-funded)
        keep_vec = [0, 0, 0, 0, 0]
        ditch_vec = [0, 0, 0, 0, 0]
        try:
            from core.ai_hand_risk import get_hand_risk_profile

            risk = get_hand_risk_profile(self, player)
            keep_vec = [max(0, int(x or 0)) for x in list(risk.get("keep") or [])[:5]]
            ditch_vec = [max(0, int(x or 0)) for x in list(risk.get("ditch") or [])[:5]]
            while len(keep_vec) < 5:
                keep_vec.append(0)
            while len(ditch_vec) < 5:
                ditch_vec.append(0)
        except Exception:
            pass

        # Supporting-action cost for partial-unlock ranking (road-first, etc.)
        support_action = self._target_action_from_strategic_direction(
            self._current_player_strategic_direction()
        )
        support_cost = (
            self._execution_cost_vector_for_action(support_action)
            if support_action
            else [0, 0, 0, 0, 0]
        )
        need_before = int(
            sum(
                max(0, int(support_cost[i] or 0) - int(hand_before[i] or 0))
                for i in range(5)
            )
        )

        # WP-TWP2 wait gate: small hand + no unlock-now → skip TwP (Dig White R4T3)
        try:
            from core.rcard_optimizer import twp_wait_gate

            # Peek whether any auto proposal fully fills support cost
            unlocks_peek = False
            for proposal in list(policy_routed or []):
                prop = proposal[0] if isinstance(proposal, tuple) else proposal
                try:
                    p_dict = prop.as_dict() if hasattr(prop, "as_dict") else {}
                    recv_i = int(p_dict.get("active_receive_index", -1) or -1)
                    recv_n = int(p_dict.get("active_receive_count", 0) or 0)
                    give_i = int(p_dict.get("active_give_index", -1) or -1)
                    give_n = int(p_dict.get("active_give_count", 0) or 0)
                    trial = list(hand_before)
                    if 0 <= give_i < 5:
                        trial[give_i] = max(0, int(trial[give_i]) - give_n)
                    if 0 <= recv_i < 5:
                        trial[recv_i] = int(trial[recv_i]) + recv_n
                    if all(int(trial[i]) >= int(support_cost[i] or 0) for i in range(5)):
                        unlocks_peek = True
                        break
                except Exception:
                    continue
            gate = twp_wait_gate(
                self, player, hand=hand_before, unlocks_now=unlocks_peek
            )
            if bool(gate.get("wait")):
                record_twp_skip_reason(self, str(gate.get("reason") or "wp_twp2_wait"))
                try:
                    self.last_twp_wait_gate = dict(gate)
                except Exception:
                    pass
                return None
        except Exception:
            pass

        ranked: List[
            Tuple[Tuple[Any, ...], Any, Dict[str, Any], List[int], Any, Dict[str, Any]]
        ] = []
        try:
            from core.player_trade import (
                build_package_quality_rank_meta,
                package_quality_rank_key,
            )
        except Exception:
            package_quality_rank_key = None  # type: ignore
            build_package_quality_rank_meta = None  # type: ignore

        for proposal, policy_decision in policy_routed:
            try:
                p_dict = proposal.as_dict()
            except Exception:
                continue
            hand_after = self._hand_after_twp_proposal(hand_before, p_dict)
            if any(int(x or 0) < 0 for x in hand_after):
                continue
            unlocked_action = self._first_action_unlocked_by_hand_delta(hand_before, hand_after)
            need_after = int(
                sum(
                    max(0, int(support_cost[i] or 0) - int(hand_after[i] or 0))
                    for i in range(5)
                )
            )
            need_reduced = max(0, need_before - need_after)
            # 0 = full unlock, 1 = partial need fill, 2 = no project progress
            if unlocked_action:
                unlock_rank = 0
            elif need_reduced > 0:
                unlock_rank = 1
            else:
                unlock_rank = 2
            try:
                give_count = int(p_dict.get("active_give_count", 0) or 0)
                give_idx = int(p_dict.get("active_give_index", 0) or 0)
            except Exception:
                give_count = give_idx = 0
            # Prefer ditch-funded offers (0) over keep-spending (1)
            spends_keep = give_idx < 5 and give_count > int(ditch_vec[give_idx] or 0)
            ditch_rank = 1 if spends_keep else 0
            bank_rate = 4
            try:
                rates = list(self.get_player_bank_trade_rates(player) or [])
                if rates and 0 <= give_idx < len(rates):
                    bank_rate = max(1, int(rates[give_idx] or 4))
            except Exception:
                bank_rate = 4

            # T1-A/B: shared package-quality key (lowest VP + RNG; escalate from snap)
            escalate_rank = 1
            try:
                snap = p_dict.get("market_snapshot") if isinstance(p_dict.get("market_snapshot"), Mapping) else {}
                if snap.get("pq_escalate") or snap.get("escalate_after_1for1_decline"):
                    escalate_rank = 0
                else:
                    for r in list(p_dict.get("reasons") or ()):
                        if "escalate after 1:1" in str(r or "").lower():
                            escalate_rank = 0
                            break
            except Exception:
                escalate_rank = 1
            if package_quality_rank_key is not None:
                rank = package_quality_rank_key(
                    p_dict,
                    game=self,
                    unlock_rank=unlock_rank,
                    need_reduced=need_reduced,
                    ditch_rank=ditch_rank,
                    escalate_rank=escalate_rank,
                    ditch_vec=ditch_vec,
                    bank_rate_give=bank_rate,
                )
            else:
                # Fallback if import fails (should not happen in normal runs)
                try:
                    total_score = float(p_dict.get("total_score", 0.0) or 0.0)
                except Exception:
                    total_score = 0.0
                try:
                    counterparty_id = int(p_dict.get("counterparty_id", 0) or 0)
                    receive_idx = int(p_dict.get("active_receive_index", 0) or 0)
                    receive_count = int(p_dict.get("active_receive_count", 0) or 0)
                except Exception:
                    counterparty_id = receive_idx = receive_count = 0
                # Prefer 1:1 before 2:1 when unlock/need/ditch match (give-recv net)
                rank = (
                    unlock_rank,
                    -need_reduced,
                    ditch_rank,
                    max(0, int(give_count) - int(receive_count)),
                    -total_score,
                    counterparty_id,
                    give_idx,
                    receive_idx,
                    -receive_count,
                    give_count,
                )
            ranked.append((rank, proposal, p_dict, hand_after, unlocked_action, dict(policy_decision)))

        # WP-E2: prefer rcard_optimizer unlock / mutual / O→need offers
        try:
            from core.rcard_optimizer import optimize_rcard_actions

            rbag = optimize_rcard_actions(self, player)
            pref = list((rbag or {}).get("preferred_twp") or [])
            pref_keys = set()
            for off in pref:
                if not isinstance(off, Mapping):
                    continue
                pref_keys.add(
                    (
                        int(off.get("counterparty_id") or -1),
                        int(off.get("give_index") or -1),
                        int(off.get("get_index") or -1),
                    )
                )
            if pref_keys and ranked:
                reranked = []
                for item in ranked:
                    rank, proposal, p_dict, hand_after, unlocked_action, pol = item
                    try:
                        key = (
                            int(p_dict.get("counterparty_id") or -1),
                            int(p_dict.get("active_give_index") or -1),
                            int(p_dict.get("active_receive_index") or -1),
                        )
                    except Exception:
                        key = (-1, -1, -1)
                    # Prepend: 0 = rcard preferred unlock, 1 = other
                    rcard_pref = 0 if key in pref_keys else 1
                    if isinstance(rank, tuple):
                        new_rank = (rcard_pref,) + tuple(rank)
                    else:
                        new_rank = (rcard_pref, rank)
                    reranked.append(
                        (new_rank, proposal, p_dict, hand_after, unlocked_action, pol)
                    )
                ranked = reranked
                try:
                    self.last_rcard_twp_bias = {
                        "preferred": len(pref_keys),
                        "note": (rbag or {}).get("note"),
                    }
                except Exception:
                    pass
        except Exception:
            pass

        # RCard near-complete: if no ranked TwP fully unlocks the support
        # action, try a single two-leg bridge chain (e.g. B→Wd then O→B).
        chain_plan = None
        try:
            any_full = any(
                bool(item[4])  # unlocked_action
                for item in ranked
            )
            if not any_full:
                from core.rcard_optimizer import enumerate_two_leg_unlock_chains

                bag = enumerate_two_leg_unlock_chains(self, player)
                chosen = bag.get("chosen") if isinstance(bag, Mapping) else None
                if isinstance(chosen, Mapping) and chosen.get("leg1") and chosen.get("leg2"):
                    chain_plan = dict(chosen)
        except Exception:
            chain_plan = None

        if not ranked and chain_plan is None:
            return None

        def _chain_rank_entry(chosen_chain: Mapping[str, Any]):
            leg1 = dict(chosen_chain.get("leg1") or {})
            # Skip non-auto human legs here (Incoming panel path not wired for chains yet)
            if bool(leg1.get("requires_human_confirmation")) or bool(
                leg1.get("counterparty_is_human")
            ):
                if not bool(leg1.get("auto_executable")):
                    return None
            leg2 = dict(chosen_chain.get("leg2") or {})
            if bool(leg2.get("requires_human_confirmation")) or (
                bool(leg2.get("counterparty_is_human")) and not bool(leg2.get("auto_executable"))
            ):
                return None
            hand_after_chain = list(chosen_chain.get("hand_after") or [])
            unlocked_from_chain = self._first_action_unlocked_by_hand_delta(
                hand_before, hand_after_chain
            )
            return (
                (-1, -3, 0, 0, -100.0, 0, 0, 0, 0, 0),
                None,
                leg1,
                hand_after_chain,
                unlocked_from_chain,
                {},
            )

        top_was_chain = False
        if not ranked and chain_plan is not None:
            entry = _chain_rank_entry(chain_plan)
            if entry is not None:
                ranked = [entry]
                top_was_chain = True

        ranked.sort(key=lambda item: item[0])

        # Prefer explicit two-leg chain over a partial one-leg TwP when the chain
        # fully unlocks and the top ranked TwP does not.
        if chain_plan is not None and ranked and not top_was_chain:
            top_unlocked = ranked[0][4]
            if not top_unlocked and chain_plan.get("fully_unlocks"):
                entry = _chain_rank_entry(chain_plan)
                if entry is not None:
                    ranked.insert(0, entry)
                    top_was_chain = True

        # T1-A: pick best after shared sort (VP + RNG already in rank key).
        # Keep T5 near-tie only when rank prefixes match except RNG (band of true equals).
        pick_items: List[Tuple[Any, Dict[str, Any]]] = []
        for rank, proposal_obj, p_dict, hand_after_i, unlocked_i, policy_i in ranked:
            pick_items.append(
                (
                    rank,
                    {
                        "rank": rank,
                        "proposal_obj": proposal_obj,
                        "proposal": dict(p_dict),
                        "hand_after": list(hand_after_i),
                        "unlocked_action": unlocked_i,
                        "policy_decision": dict(policy_i),
                    },
                )
            )
        rng_meta: Dict[str, Any] = {
            "rng_used": False,
            "band_size": 1,
            "stage": "T1-A",
            "pq": True,
        }
        # Strict argmax on package_quality key (includes seeded RNG at end)
        picked = pick_items[0][1] if pick_items else None
        if isinstance(picked, Mapping) and isinstance(picked.get("rank"), tuple):
            rk = picked["rank"]
            # Note if multiple candidates share unlock/need/ditch/escalate/attractiveness/vp
            band = 1
            if len(rk) >= 6:
                prefix = rk[:6]
                for other_rank, _item in pick_items[1:]:
                    if isinstance(other_rank, tuple) and len(other_rank) >= 6 and other_rank[:6] == prefix:
                        band += 1
                    else:
                        break
            rng_meta["band_size"] = band
            rng_meta["rng_used"] = band > 1  # seed broke the tie among equal VP partners

        if not isinstance(picked, Mapping):
            return None

        proposal = dict(picked.get("proposal") or {})
        hand_after = list(picked.get("hand_after") or [])
        unlocked_action = picked.get("unlocked_action")
        policy_decision = dict(picked.get("policy_decision") or {})
        label = self._format_twp_proposal_label(proposal)
        follow_text = self._short_execution_action_label(unlocked_action) if unlocked_action else "rescan"
        best_text = f"TwP {label}"
        if unlocked_action:
            best_text = f"{best_text}; then {follow_text}"

        # T1 metadata for debug / Phase0
        try:
            gi = int(proposal.get("active_give_index", 0) or 0)
            gc = int(proposal.get("active_give_count", 0) or 0)
            ditch_safe = gc <= int(ditch_vec[gi] or 0) if 0 <= gi < 5 else False
        except Exception:
            ditch_safe = False

        # T1-A dig-in: last_twp_package_rank
        pq_meta: Dict[str, Any] = {}
        try:
            if build_package_quality_rank_meta is not None:
                pq_ranked = [
                    (rank, p_dict)
                    for rank, _obj, p_dict, _ha, _ua, _pol in ranked
                ]
                pq_meta = build_package_quality_rank_meta(pq_ranked, chosen_index=0)
                pq_meta["ditch_safe"] = ditch_safe
                pq_meta["unlocks"] = bool(unlocked_action)
                self.last_twp_package_rank = dict(pq_meta)
        except Exception as pq_exc:
            pq_meta = {"pq": True, "slice": "T1-A", "error": str(pq_exc)}
            try:
                self.last_twp_package_rank = dict(pq_meta)
            except Exception:
                pass

        pq_note = ""
        if pq_meta.get("dbg"):
            pq_note = f" {pq_meta.get('dbg')}."
        elif bool(rng_meta.get("rng_used")) and int(rng_meta.get("band_size", 0) or 0) > 1:
            pq_note = f" T1-A partner VP-tie RNG (band {rng_meta.get('band_size')})."

        then_twp_chain: List[Dict[str, Any]] = []
        chain_meta: Dict[str, Any] = {}
        try:
            if isinstance(chain_plan, Mapping) and chain_plan.get("leg2"):
                leg1_ref = dict(chain_plan.get("leg1") or {})
                # Attach leg2 when the picked proposal is the chain's first leg
                same_leg1 = (
                    int(proposal.get("active_give_index", -9))
                    == int(leg1_ref.get("active_give_index", -8))
                    and int(proposal.get("active_receive_index", -9))
                    == int(leg1_ref.get("active_receive_index", -8))
                    and int(proposal.get("counterparty_id", -9))
                    == int(leg1_ref.get("counterparty_id", -8))
                )
                if same_leg1 or not ranked or top_was_chain:
                    then_twp_chain = [dict(chain_plan.get("leg2") or {})]
                    chain_meta = {
                        "label": chain_plan.get("label"),
                        "sweetened": bool(chain_plan.get("sweetened")),
                        "bridge_index": chain_plan.get("bridge_index"),
                        "miss_index": chain_plan.get("miss_index"),
                        "restorer_index": chain_plan.get("restorer_index"),
                        "reason": "two_leg_near_complete_unlock",
                    }
                    if chain_plan.get("label"):
                        best_text = f"TwP chain: {chain_plan.get('label')}"
                        if unlocked_action:
                            best_text = f"{best_text}; then {follow_text}"
        except Exception:
            then_twp_chain = []
            chain_meta = {}

        return {
            "step": step,
            "action": "TwP",
            "label": f"TwP {label}" if not chain_meta else f"TwP chain {chain_meta.get('label')}",
            "status": "will_try",
            "reason": (
                (
                    f"AI TwP two-leg unlock chain: {chain_meta.get('label')}."
                    if chain_meta
                    else (
                        f"AI TwP support (T1-C): package-quality rank before bank"
                        + (f" unlocks {follow_text}." if unlocked_action else " improves hand before pass/TwB.")
                        + (" ditch-funded." if ditch_safe else " keep-exception unlock." if unlocked_action else "")
                    )
                )
                + (f" Human TwP mode={policy_decision.get('mode')}." if policy_decision.get('involves_human') else "")
                + pq_note
            ),
            "source": "ai_twp_support" if not chain_meta else "ai_twp_support_chain2",
            "twp_t1": {
                "ditch_safe": ditch_safe,
                "unlocks": bool(unlocked_action),
                "prefer_over_bank": bool(unlocked_action),
                "slice": "T1-C",
            },
            "twp_package_quality": dict(pq_meta) if pq_meta else {},
            "last_twp_package_rank": dict(pq_meta) if pq_meta else {},
            "twp_t5": {
                "partner_rng": bool(rng_meta.get("rng_used")),
                "band_size": int(rng_meta.get("band_size", 1) or 1),
                "stage": "T1-A",
                "pq": True,
            },
            "rng_meta": dict(rng_meta),
            "twp_chain2": dict(chain_meta) if chain_meta else {},
            "then_twp_chain": list(then_twp_chain),
            "choice": {
                "action": "TwP",
                "viable": True,
                "actionable": True,
                "reason": "Best executable TwP candidate after package-quality rank.",
                "candidates": [dict(proposal)],
            },
            "candidate": dict(proposal),
            "proposal": dict(proposal),
            "twp_proposal": dict(proposal),
            "human_twp_policy_decision": dict(policy_decision),
            "hand_before": list(hand_before),
            "hand_after": list(hand_after),
            "unlocked_action": unlocked_action,
            "best_action_label": label if not chain_meta else str(chain_meta.get("label") or label),
            "best_action_text": best_text,
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(player, "id", None),
        }

    def _bump_support_trade_count(self) -> int:
        """S4/R1: count support TwP/TwB this turn for multi-step chaining."""
        try:
            n = int(getattr(self, "support_trades_this_turn", 0) or 0) + 1
        except Exception:
            n = 1
        try:
            self.support_trades_this_turn = n
        except Exception:
            pass
        return n

    def _support_trade_budget_remaining(self, *, max_per_turn: int = 3) -> bool:
        try:
            return int(getattr(self, "support_trades_this_turn", 0) or 0) < int(max_per_turn)
        except Exception:
            return True

    def _chain_next_support_trade_plan(self) -> Optional[Dict[str, Any]]:
        """After a partial unlock trade, plan another TwP/TwB before risk/pass."""
        if not self._support_trade_budget_remaining():
            return None
        try:
            twp = self._plan_ai_trade_with_player_for_strategy(step=1)
            if isinstance(twp, Mapping) and twp.get("action"):
                return dict(twp)
        except Exception:
            pass
        try:
            twb = self._plan_ai_trade_with_bank_for_strategy(step=1)
            if isinstance(twb, Mapping) and twb.get("action"):
                return dict(twb)
        except Exception:
            pass
        return None

    def _arm_support_trade_chain(self, next_plan: Mapping[str, Any], *, source: str) -> None:
        """Queue the next support trade for AI Continue (same turn)."""
        try:
            item = dict(next_plan)
            item["step"] = 1
            item["source"] = str(item.get("source") or source)
            item["chain_from"] = source
            self.current_ai_execution_plan = [item]
            self.ai_execution_preview_ready = True
            self.ai_execution_stage = "preview_ready"
        except Exception:
            pass

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

        self._bump_support_trade_count()

        # T11: Events dig-in line with package + unlock/fill reason + score
        try:
            from core.player_trade import format_twp_executed_events_line

            snap = (
                proposal.get("market_snapshot")
                if isinstance(proposal.get("market_snapshot"), Mapping)
                else {}
            )
            need_red = 0
            try:
                need_red = int(snap.get("need_reduced") or snap.get("live_need_filled") or 0)
            except Exception:
                need_red = 0
            events_line = format_twp_executed_events_line(
                proposal,
                unlocked_action=str(plan_item.get("unlocked_action") or ""),
                need_reduced=need_red,
                fills_live_need=bool(snap.get("fills_live_need") or need_red > 0),
                total_score=proposal.get("total_score"),
            )
            self.emit_twitter_event(getattr(player, "id", None), events_line)
            try:
                self.last_twp_executed_events_line = events_line
            except Exception:
                pass
        except Exception:
            try:
                self.emit_twitter_event(getattr(player, "id", None), f"TwP {label}")
            except Exception:
                pass

        # Same-Continue: execute planned two-leg restore (e.g. O→B after B→Wd)
        chain_results: List[Dict[str, Any]] = []
        then_chain = list(plan_item.get("then_twp_chain") or [])
        for leg in then_chain:
            if not isinstance(leg, Mapping) or not leg:
                continue
            if not self._support_trade_budget_remaining():
                break
            try:
                from core.player_trade import execute_twp_trade_from_dict

                leg_decision = execute_twp_trade_from_dict(
                    self, leg, require_human_confirmation=False
                )
                leg_dict = (
                    leg_decision.as_dict()
                    if hasattr(leg_decision, "as_dict")
                    else dict(leg_decision or {})
                )
            except Exception as exc:
                leg_dict = {"executed": False, "reason": str(exc)}
            chain_results.append({"proposal": dict(leg), "decision": dict(leg_dict)})
            if not bool(leg_dict.get("executed")):
                break
            self._bump_support_trade_count()
            try:
                self.emit_twitter_event(
                    getattr(player, "id", None),
                    f"TwP chain leg: {self._format_twp_proposal_label(leg)}",
                )
            except Exception:
                pass

        try:
            for p in list(getattr(self, "players", []) or []):
                self.update_strategy_dashboard(p)
        except Exception:
            pass

        try:
            self.refresh_strategy_after_event("after_ai_twp_support", kind="hand")
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_ai_twp_support")
        except Exception:
            pass
        try:
            from core.strategy_offway_q1 import maybe_q1_offway_structure_l2

            maybe_q1_offway_structure_l2(
                self,
                player,
                reason="after_ai_twp_support",
                rescan=True,
            )
        except Exception:
            pass
        try:
            from core.strategy_offway_q2 import apply_q2_offway_dcard_permission

            apply_q2_offway_dcard_permission(
                self, player, reason="after_ai_twp_support"
            )
        except Exception:
            pass

        followup_item = self.get_current_best_executable_action()
        if not isinstance(followup_item, Mapping):
            followup_item = {}
        followup_action = str(followup_item.get("action", "") or "")
        chain_note = ""
        if chain_results:
            n_ok = sum(1 for c in chain_results if bool((c.get("decision") or {}).get("executed")))
            chain_note = f"; +{n_ok} chain TwP"

        if followup_action not in {"Buy development_card", "Build city", "Build settlement", "Build road"}:
            # S4/R1: partial TwP → chain another support trade before risk/pass
            # (skip if we already ran a planned then_twp_chain this pass)
            if not then_chain:
                chain = self._chain_next_support_trade_plan()
                if isinstance(chain, Mapping) and chain.get("action"):
                    self._arm_support_trade_chain(chain, source="ai_twp_partial_chain")
                    return {
                        "ok": True,
                        "action": "TwP",
                        "support_action": "TwP",
                        "reason": "twp_partial_chain_ready",
                        "message": f"TwP {label}; chain {chain.get('action')}",
                        "twp_decision": dict(decision_dict),
                        "proposal": dict(proposal),
                        "chain_next": dict(chain),
                        "then_twp_chain_results": list(chain_results),
                    }
            return {
                "ok": True,
                "action": "TwP",
                "support_action": "TwP",
                "reason": "twp_executed_no_followup_available_after_rescan",
                "message": f"TwP {label}{chain_note}",
                "twp_decision": dict(decision_dict),
                "proposal": dict(proposal),
                "then_twp_chain_results": list(chain_results),
            }

        followup_result = self._execute_one_ai_plan_item(player, followup_item)
        if bool(followup_result.get("ok")):
            return {
                "ok": True,
                "action": str(followup_result.get("action", followup_action) or followup_action),
                "support_action": "TwP",
                "combined_action": f"TwP{chain_note} + {followup_result.get('action', followup_action)}",
                "reason": "twp_unlocked_and_executed_followup",
                "message": f"TwP {label}{chain_note}; then {followup_result.get('action', followup_action)}",
                "twp_decision": dict(decision_dict),
                "proposal": dict(proposal),
                "followup_result": dict(followup_result),
                "followup_plan_item": dict(followup_item),
                "then_twp_chain_results": list(chain_results),
            }

        return {
            "ok": True,
            "action": "TwP",
            "support_action": "TwP",
            "reason": f"twp_executed_followup_failed:{followup_result.get('reason', 'unknown')}",
            "message": f"TwP {label}{chain_note}; follow-up failed",
            "twp_decision": dict(decision_dict),
            "proposal": dict(proposal),
            "followup_result": dict(followup_result),
            "followup_plan_item": dict(followup_item),
            "then_twp_chain_results": list(chain_results),
        }

    def _hand_risk_rng_context(self, player: Any = None, *, tag: str = "hand_risk") -> Dict[str, Any]:
        """Seed context for Stage D near-tie RNG (reproducible with game seed)."""
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None
        base = getattr(self, "game_seed", None)
        if base is None:
            base = getattr(self, "seed", None)
        if base is None:
            base = getattr(self, "sequence_number", 0)
        return {
            "base_seed": base,
            "game_seed": base,
            "round": getattr(self, "round", 0),
            "turn": getattr(self, "turn", 0),
            "player_id": getattr(player, "id", 0) if player is not None else 0,
            "tag": tag,
        }

    def _plan_ai_risk_package(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Stage C + B + D: secondary helpful, risk TwP (T2), or risk TwB.

        Called only when no strategic actionable buy/build and unlock trades failed.
        Prefers on-strategy secondary builds that spend ditch; otherwise risk trades
        (prefer mutual TwP over bank TwB when value is similar). Stage D may
        coin-flip near-ties under soft_reduce only.
        """
        secondary = self._plan_ai_secondary_helpful(step=step)
        risk_twp = self._plan_ai_risk_twp(step=step)
        risk_twb = self._plan_ai_risk_twb(step=step)
        policy = "soft_reduce"
        t5_soft_pass_meta: Dict[str, Any] = {}
        try:
            from core.ai_hand_risk import (
                compare_risk_package_scores,
                get_hand_risk_profile,
                maybe_soft_pass_risk_twp,
            )

            player = self.get_current_player()
            profile = get_hand_risk_profile(self, player)
            policy = str((profile or {}).get("policy") or "soft_reduce")

            # T5: soft-pass marginal risk TwP (never unlock path)
            if isinstance(risk_twp, Mapping) and risk_twp.get("action") == "TwP":
                score_probe = {
                    "mode": "risk_twp",
                    "action": "TwP",
                    "size_delta": risk_twp.get("size_delta", 0),
                    "keep_at_risk_before": risk_twp.get("keep_at_risk_before", 0),
                    "keep_at_risk_after": risk_twp.get("keep_at_risk_after", 0),
                    "get_need_bonus": risk_twp.get("get_need_bonus", 0)
                    if risk_twp.get("get_need_bonus") is not None
                    else (3 if "fills need" in str(risk_twp.get("reason", "")) else 0),
                    "give_count": risk_twp.get("give_count", 0),
                    "get_count": risk_twp.get("get_count", 0),
                }
                kept, t5_soft_pass_meta = maybe_soft_pass_risk_twp(
                    score_probe,
                    policy=policy,
                    rng_context=self._hand_risk_rng_context(player, tag="twp_risk_soft_pass"),
                )
                if kept is None and t5_soft_pass_meta.get("soft_passed"):
                    try:
                        from core.human_twp_policy import record_twp_skip_reason

                        record_twp_skip_reason(self, "t5_soft_pass_risk_twp")
                    except Exception:
                        pass
                    risk_twp = None

            twp_score = None
            if isinstance(risk_twp, Mapping) and risk_twp.get("action") == "TwP":
                twp_score = {
                    "mode": "risk_twp",
                    "action": "TwP",
                    "size_delta": risk_twp.get("size_delta", 0),
                    "keep_at_risk_before": risk_twp.get("keep_at_risk_before", 0),
                    "keep_at_risk_after": risk_twp.get("keep_at_risk_after", 0),
                    "get_need_bonus": risk_twp.get("get_need_bonus", 0)
                    if risk_twp.get("get_need_bonus") is not None
                    else (3 if "fills need" in str(risk_twp.get("reason", "")) else 0),
                    "give_count": risk_twp.get("give_count", 0),
                    "get_count": risk_twp.get("get_count", 0),
                    "proposal": risk_twp.get("proposal") or risk_twp.get("twp_proposal"),
                }
            twb_score = None
            if isinstance(risk_twb, Mapping) and risk_twb.get("action") == "TwB":
                twb_score = {
                    "mode": "risk_twb",
                    "action": "TwB",
                    "size_delta": risk_twb.get("size_delta", 0),
                    "keep_at_risk_before": risk_twb.get("keep_at_risk_before", 0),
                    "keep_at_risk_after": risk_twb.get("keep_at_risk_after", 0),
                    "get_need_bonus": risk_twb.get("get_need_bonus", 0)
                    if risk_twb.get("get_need_bonus") is not None
                    else (1 if "fills need" in str(risk_twb.get("reason", "")) else 0),
                }
            sec_score = None
            if isinstance(secondary, Mapping) and secondary.get("action"):
                sec_score = {
                    "action": secondary.get("action"),
                    "progress": secondary.get("progress", 0),
                    "strategy_fit": secondary.get("strategy_fit", 0),
                    "size_delta": secondary.get("size_delta", 0),
                    "keep_at_risk_before": secondary.get("keep_at_risk_before", 0),
                    "keep_at_risk_after": secondary.get("keep_at_risk_after", 0),
                }
            winner = compare_risk_package_scores(
                sec_score,
                twb_score,
                risk_twp=twp_score,
                policy=policy,
                rng_context=self._hand_risk_rng_context(player, tag="risk_package"),
            )
        except Exception:
            if secondary:
                winner = "secondary"
            elif risk_twp:
                winner = "risk_twp"
            elif risk_twb:
                winner = "risk_twb"
            else:
                winner = ""

        if winner == "secondary" and isinstance(secondary, Mapping):
            out = dict(secondary)
            out["package_pick"] = "secondary"
            return out
        if winner == "risk_twp" and isinstance(risk_twp, Mapping):
            out = dict(risk_twp)
            out["package_pick"] = "risk_twp"
            if t5_soft_pass_meta:
                out.setdefault("twp_t5", {})["soft_pass_checked"] = True
            return out
        if winner == "risk_twb" and isinstance(risk_twb, Mapping):
            out = dict(risk_twb)
            out["package_pick"] = "risk_twb"
            return out
        if isinstance(secondary, Mapping) and secondary.get("action"):
            return dict(secondary)
        if isinstance(risk_twp, Mapping) and risk_twp.get("action"):
            return dict(risk_twp)
        if isinstance(risk_twb, Mapping) and risk_twb.get("action"):
            return dict(risk_twb)
        return None

    def _plan_ai_risk_twp(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """T2 Stage B peer: ditch-only TwP under soft/hard hand-risk policy.

        Does not unlock a preferred build (that is ``_plan_ai_trade_with_player_for_strategy``).
        Only runs under soft_reduce / hard_reduce, exports ditch only, prefers mutual
        1:1 that fills project shortfall over wasteful bank dumps.
        """
        if str(getattr(self, "phase", "")) != "Execution":
            return None
        if str(getattr(self, "state", "")) != "ActionSelection":
            return None
        if self._is_current_player_human_for_execution():
            return None

        # Don't steal pending Manual-mode HP offer flow
        pending_plan = self._pending_human_twp_response_plan(step=step)
        if isinstance(pending_plan, Mapping):
            return None

        player = self.get_current_player()
        if player is None:
            return None

        scan = getattr(self, "current_viable_action_scan", None)
        if isinstance(scan, Mapping) and scan.get("forced_action_mode"):
            return None

        try:
            from core.ai_hand_risk import get_hand_risk_profile, select_risk_twp_candidate
            from core.player_trade import find_twp_proposals
            from core.human_twp_policy import resolve_incoming_human_twp_offer
        except Exception:
            return None

        profile = get_hand_risk_profile(self, player)
        if not isinstance(profile, Mapping) or not profile:
            return None
        if str(profile.get("policy", "accept")) not in {"soft_reduce", "hard_reduce"}:
            return None
        if int(profile.get("total", 0) or 0) <= 7:
            return None

        try:
            proposals = find_twp_proposals(
                self,
                player,
                max_candidates=24,
                include_human_counterparties=True,
            )
        except Exception:
            return None

        # Route HP offers through Human TwP Mode (same as unlock TwP planner)
        policy_routed = []
        for proposal in list(proposals or []):
            try:
                decision = resolve_incoming_human_twp_offer(self, proposal)
            except Exception:
                decision = {"status": "error", "accepted": False, "involves_human": False}
            involves_human = bool(decision.get("involves_human", False))
            if involves_human:
                # Risk package must not open Manual panel; only auto-accepted HP deals
                if bool(decision.get("requires_human_panel", False)):
                    continue
                if not bool(decision.get("accepted", False)):
                    continue
                policy_routed.append(proposal)
            else:
                if bool(getattr(proposal, "auto_executable", False)):
                    policy_routed.append(proposal)

        if not policy_routed:
            return None

        selected = select_risk_twp_candidate(
            profile,
            policy_routed,
            rng_context=self._hand_risk_rng_context(player, tag="risk_twp"),
        )
        if not isinstance(selected, Mapping) or not selected:
            return None

        proposal = selected.get("proposal") or selected.get("candidate") or {}
        if not isinstance(proposal, Mapping) or not proposal:
            return None

        label = self._format_twp_proposal_label(proposal)
        reason = str(selected.get("reason") or "Stage B risk TwP: ditch-funded mutual trade")
        rng_meta = dict(selected.get("rng_meta") or {})
        if bool(rng_meta.get("rng_used")) and int(rng_meta.get("band_size", 0) or 0) > 1:
            reason = f"{reason}; T5 near-tie partner (band {rng_meta.get('band_size')})"
        best_text = f"TwP {label} (hand risk)"

        return {
            "step": step,
            "action": "TwP",
            "label": f"TwP {label}",
            "status": "will_try",
            "reason": reason,
            "source": "ai_risk_twp",
            "mode": "risk_twp",
            "twp_t2": {
                "ditch_safe": True,
                "risk_valve": True,
                "get_need_bonus": selected.get("get_need_bonus", 0),
                "size_delta": selected.get("size_delta", 0),
            },
            "twp_t5": {
                "partner_rng": bool(rng_meta.get("rng_used")),
                "band_size": int(rng_meta.get("band_size", 1) or 1),
                "stage": "T5",
            },
            "rng_meta": rng_meta,
            "choice": {
                "action": "TwP",
                "viable": True,
                "actionable": True,
                "reason": "Stage B risk TwP — ditch export under hand-risk policy.",
                "candidates": [dict(proposal)],
            },
            "candidate": dict(proposal),
            "proposal": dict(proposal),
            "twp_proposal": dict(proposal),
            "hand_before": list(selected.get("hand_before") or []),
            "hand_after": list(selected.get("hand_after") or []),
            "unlocked_action": None,  # pure risk valve — no build follow-up required
            "best_action_label": label,
            "best_action_text": best_text,
            "hand_risk_policy": selected.get("policy"),
            "size_delta": selected.get("size_delta"),
            "keep_at_risk_before": selected.get("keep_at_risk_before"),
            "keep_at_risk_after": selected.get("keep_at_risk_after"),
            "get_need_bonus": selected.get("get_need_bonus"),
            "give_count": selected.get("give_count"),
            "get_count": selected.get("get_count"),
            "give": list(selected.get("give") or []),
            "get": list(selected.get("get") or []),
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(player, "id", None),
        }

    def _plan_ai_secondary_helpful(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Stage C: plan a non-preferred buy/build paid from ditch cards."""
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
        if isinstance(scan, Mapping) and scan.get("forced_action_mode"):
            return None

        try:
            from core.ai_hand_risk import get_hand_risk_profile, select_secondary_helpful_action
        except Exception:
            return None

        profile = get_hand_risk_profile(self, player)
        if not isinstance(profile, Mapping) or not profile:
            return None
        if str(profile.get("policy", "accept")) not in {"soft_reduce", "hard_reduce"}:
            return None

        direction = self._current_player_strategic_direction()
        preferred = self._target_action_from_strategic_direction(direction)
        options = self._secondary_helpful_options(player, direction, profile)
        selected = select_secondary_helpful_action(
            profile,
            options,
            preferred_action=preferred,
            rng_context=self._hand_risk_rng_context(player, tag="secondary"),
        )
        if not isinstance(selected, Mapping) or not selected.get("action"):
            return None

        action = str(selected.get("action") or "")
        choice = selected.get("choice") if isinstance(selected.get("choice"), Mapping) else {}
        if not choice:
            choice = {
                "action": action,
                "viable": True,
                "actionable": True,
                "priority": 50,
                "candidates": [dict(selected.get("candidate") or {})] if selected.get("candidate") else [],
                "reason": selected.get("reason"),
            }
        else:
            choice = dict(choice)
            choice["actionable"] = True
            choice.setdefault("viable", True)

        plan_item = self._plan_item_from_execution_choice(
            choice,
            source="ai_secondary_helpful",
            step=step,
        )
        if not isinstance(plan_item, Mapping) or not plan_item.get("action"):
            return None
        # Ensure we didn't get a blocked placeholder
        if str(plan_item.get("status", "") or "") in {"blocked", "route_blocked"}:
            return None
        if str(plan_item.get("action", "") or "") not in {
            "Buy development_card",
            "Build city",
            "Build settlement",
            "Build road",
        }:
            return None

        plan_item = dict(plan_item)
        plan_item["source"] = "ai_secondary_helpful"
        plan_item["mode"] = "secondary_helpful"
        plan_item["reason"] = str(selected.get("reason") or "Stage C secondary helpful action")
        plan_item["strategy_fit"] = selected.get("strategy_fit")
        plan_item["progress"] = selected.get("progress")
        plan_item["size_delta"] = selected.get("size_delta")
        plan_item["keep_at_risk_before"] = selected.get("keep_at_risk_before")
        plan_item["keep_at_risk_after"] = selected.get("keep_at_risk_after")
        plan_item["hand_risk_policy"] = selected.get("policy")
        # Label for BA display
        bn = str(plan_item.get("best_action_text") or plan_item.get("label") or action)
        if "(secondary)" not in bn.lower():
            plan_item["best_action_text"] = f"{bn} (secondary)".strip()
        return plan_item

    def _secondary_helpful_options(
        self,
        player: Player,
        direction: Mapping[str, Any],
        profile: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        """Build Stage C option list from viable (not necessarily actionable) scan rows."""
        options: List[Dict[str, Any]] = []
        fit_hints = self._secondary_strategy_fit_hints(player, direction)

        rows = [row for row in list(getattr(self, "current_execution_choices", []) or []) if isinstance(row, Mapping)]
        if not rows:
            # Fall back to scan candidates if choices missing
            scan = getattr(self, "current_viable_action_scan", None)
            if isinstance(scan, Mapping):
                flags = dict(scan.get("action_flags", {}) or {})
                cands = dict(scan.get("candidates", {}) or {})
                for action in ("Build city", "Build settlement", "Build road", "Buy development_card"):
                    if not flags.get(action) and not cands.get(action):
                        continue
                    rows.append(
                        {
                            "action": action,
                            "viable": True,
                            "candidates": list(cands.get(action) or []),
                        }
                    )

        for row in rows:
            action = str(row.get("action", "") or "")
            if action not in {"Build city", "Build settlement", "Build road", "Buy development_card"}:
                continue
            # Must be legal/viable (not merely strategic)
            if not bool(row.get("viable", row.get("scan_viable", False))):
                # If candidates exist and we can pay, still consider
                if not list(row.get("candidates") or []):
                    continue

            cost = self._execution_cost_vector_for_action(action)
            if not self._can_player_pay_execution_cost(player, cost):
                continue

            strategy_fit = int(fit_hints.get(action, 0) or 0)
            if strategy_fit <= 0:
                continue

            # Pick a concrete candidate for the choice
            choice = dict(row)
            choice["action"] = action
            candidate = self._best_candidate_for_execution_choice(choice)
            if action != "Buy development_card" and not candidate:
                # Roads/settlements/cities need a target
                if action == "Build road" and self._ai_road_guard_applies(player):
                    continue
                if action in {"Build city", "Build settlement"}:
                    continue

            # Road: prefer on-route; if not on route, lower fit
            if action == "Build road" and candidate:
                route_plan = self._settlement_route_plan()
                on_route = False
                if isinstance(route_plan, Mapping):
                    roads = list(route_plan.get("roads_to_build") or [])
                    cand_road = self._road_key_from_any(
                        candidate.get("road_id") or candidate.get("road") or candidate.get("edge")
                    )
                    for r in roads:
                        if self._road_key_from_any(r) == cand_road and cand_road:
                            on_route = True
                            break
                    if route_plan.get("kind") == "new_settlement" and not on_route:
                        strategy_fit = min(strategy_fit, 1)
                        if strategy_fit <= 0:
                            continue

            label = action
            if candidate:
                tid = candidate.get("target_id") or candidate.get("intersection_id")
                if tid not in (None, ""):
                    label = f"{action} @{tid}"
                elif candidate.get("road_id") or candidate.get("road"):
                    label = f"{action} {candidate.get('road_id') or candidate.get('road')}"

            options.append(
                {
                    "action": action,
                    "cost": list(cost),
                    "strategy_fit": strategy_fit,
                    "label": label,
                    "candidate": dict(candidate) if candidate else {},
                    "choice": choice,
                }
            )
        return options

    def _secondary_strategy_fit_hints(self, player: Player, direction: Mapping[str, Any]) -> Dict[str, int]:
        """How well each action family fits the way (0 = reject secondary)."""
        hints = {
            "Build city": 0,
            "Build settlement": 0,
            "Build road": 0,
            "Buy development_card": 0,
        }
        if not isinstance(direction, Mapping):
            direction = {}
        remaining = direction.get("remaining") if isinstance(direction.get("remaining"), Mapping) else {}
        tags = " ".join(str(t) for t in list(direction.get("tags") or [])).lower()
        summary = direction.get("strategy_summary") if isinstance(direction.get("strategy_summary"), Mapping) else {}
        support = str(direction.get("supporting_action_type") or "").lower()

        cities_left = 0
        try:
            cities_left = int(remaining.get("cities") or remaining.get("city_upgrades") or 0)
        except Exception:
            cities_left = 0
        if cities_left <= 0:
            cities_left = 1 if ("city" in tags or bool(summary.get("cities"))) else 0
        # Always allow city secondary if player has settlements to upgrade and way has cities
        settlements = list(getattr(player, "settlements", []) or [])
        cities = list(getattr(player, "cities", []) or [])
        upgradable = [s for s in settlements if s not in cities]
        if cities_left > 0 and upgradable:
            hints["Build city"] = 3 if "city" in support or cities_left >= 2 else 2

        news = 0
        try:
            news = int(remaining.get("new_settlements") or 0)
        except Exception:
            news = 0
        route = self._settlement_route_plan()
        if isinstance(route, Mapping) and route.get("kind") == "next_settlement":
            hints["Build settlement"] = 3
        elif news > 0 and isinstance(route, Mapping) and route.get("kind") == "new_settlement":
            # Settlement only when route done (no roads left)
            roads = list(route.get("roads_to_build") or [])
            if not roads:
                hints["Build settlement"] = 2

        if isinstance(route, Mapping) and route.get("kind") == "new_settlement" and list(route.get("roads_to_build") or []):
            hints["Build road"] = 3
        elif "longest road" in tags or bool(summary.get("longest_road")):
            hints["Build road"] = 2
        elif "road" in support:
            hints["Build road"] = 2

        la = "largest army" in tags or bool(summary.get("largest_army") or summary.get("biggest_army"))
        vp = "vp" in tags or int(summary.get("victory_point_cards") or 0) > 0
        if la or vp or "dcard" in support or "development" in support:
            hints["Buy development_card"] = 3 if la else 2

        return hints

    def _supporting_action_live_need_vector(
        self, player: Optional[Player] = None
    ) -> Tuple[str, List[int], List[int]]:
        """P0-R4/R7: immediate supporting action, cost, and live_need (cost−hand).

        Returns ``(action_name, cost_vector, live_need_vector)``.
        """
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None
        direction = self._current_player_strategic_direction()
        action = self._target_action_from_strategic_direction(direction)
        if action not in {
            "Build city",
            "Build settlement",
            "Build road",
            "Buy development_card",
        }:
            return "", [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]
        cost = self._execution_cost_vector_for_action(action)
        hand = (
            self._execution_hand_vector_for_player(player)
            if player is not None
            else [0, 0, 0, 0, 0]
        )
        live_need = self._vector_subtract_floor_zero(cost, hand)
        return str(action), list(cost), list(live_need)

    def format_support_trade_debug_line(
        self,
        plan: Optional[Sequence[Mapping[str, Any]]] = None,
        *,
        player: Optional[Player] = None,
    ) -> str:
        """P0-R7: one-line Support | TwP | TwB | RiskTwB trail for DBG/Phase0."""
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None
        action, _cost, live_need = self._supporting_action_live_need_vector(player)
        names = ["Wh", "O", "Wd", "B", "Sh"]
        need_bits = [
            f"{names[i]}{int(live_need[i])}"
            for i in range(5)
            if int(live_need[i] or 0) > 0
        ]
        need_txt = ",".join(need_bits) if need_bits else "—"
        support_txt = f"Support: {action or '—'} need=[{need_txt}]"

        plan_list = list(plan or getattr(self, "current_ai_execution_plan", None) or [])
        twp_txt = "TwP: —"
        twb_txt = "TwB: —"
        risk_txt = "RiskTwB: —"
        for item in plan_list:
            if not isinstance(item, Mapping):
                continue
            act = str(item.get("action") or "")
            src = str(item.get("source") or "")
            mode = str(item.get("mode") or "")
            label = str(
                item.get("best_action_text")
                or item.get("label")
                or item.get("best_action_label")
                or act
            ).strip()
            if act == "TwP":
                fb = ""
                prop = item.get("proposal") or item.get("twp_proposal") or {}
                if isinstance(prop, Mapping):
                    reasons = prop.get("reasons") or []
                    if any("unlock_fallback" in str(r) for r in reasons) or (
                        isinstance(prop.get("market_snapshot"), Mapping)
                        and prop.get("market_snapshot", {}).get("source") == "unlock_fallback"
                    ):
                        fb = " unlock_fallback"
                twp_txt = f"TwP:{fb} {label}"[:80]
            elif act == "TwB":
                if src == "ai_risk_twb" or mode == "risk_twb":
                    risk_txt = f"RiskTwB: {label}"[:70]
                else:
                    mode_bit = mode or ("partial" if "partial" in str(item.get("reason") or "").lower() else "support")
                    twb_txt = f"TwB: {mode_bit} {label}"[:80]

        if twp_txt == "TwP: —":
            skips = list(getattr(self, "last_twp_skip_reasons", None) or [])
            if skips:
                # T11: show richest structured skip (last is often most specific)
                show = skips[-1]
                if len(skips) > 1:
                    # Prefer live_need / counterparty / freeze over bare no_mutual
                    for pref in (
                        "T9_freeze",
                        "no_counterparty_for_live_need",
                        "no_offerable",
                        "empty_hand",
                        "live_need=",
                        "appetite_or_floor",
                    ):
                        hit = next((s for s in skips if pref in str(s)), None)
                        if hit:
                            show = hit
                            break
                twp_txt = f"TwP: skipped ({show})"
            exec_line = getattr(self, "last_twp_executed_events_line", None)
            if exec_line:
                twp_txt = str(exec_line)[:80]
        if risk_txt == "RiskTwB: —" and twb_txt == "TwB: —":
            # Neither trade in plan — note if strategy need remains
            if sum(int(x or 0) for x in live_need) > 0:
                risk_txt = "RiskTwB: skipped (or no candidate)"

        endgame_txt = ""
        try:
            s6 = getattr(self, "last_endgame_sequence", None) or {}
            if isinstance(s6, Mapping) and not s6.get("skipped") and s6.get("pick"):
                endgame_txt = f" | endgame: {s6.get('pick')}"
                if s6.get("mode"):
                    endgame_txt += f"/{s6.get('mode')}"
        except Exception:
            endgame_txt = ""

        return f"{support_txt} | {twp_txt} | {twb_txt} | {risk_txt}{endgame_txt}"

    def _record_support_trade_debug(
        self,
        plan: Optional[Sequence[Mapping[str, Any]]] = None,
        *,
        emit_twitter: bool = False,
    ) -> str:
        """Store last support/trade debug line; optionally emit DBG twitter."""
        try:
            line = self.format_support_trade_debug_line(plan)
        except Exception as exc:
            line = f"Support: debug_error ({exc})"
        try:
            setattr(self, "last_support_trade_debug", line)
        except Exception:
            pass
        if emit_twitter and line:
            try:
                pid = None
                p = self.get_current_player()
                if p is not None:
                    pid = getattr(p, "id", None)
                # Only for AI seats — avoid spam on human turns
                if p is not None and not bool(getattr(p, "is_human", False)):
                    self.emit_twitter_event(pid, f"DBG: {line}"[:200])
            except Exception:
                pass
        return line

    def _plan_ai_risk_twb(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Stage B: plan a ditch-only TwB to reduce discard exposure.

        Does not unlock a build (that is ``_plan_ai_trade_with_bank_for_strategy``).
        Only runs under soft_reduce / hard_reduce hand-risk policy, exports ditch
        only, and never spends keep units for the active project.

        P0-R4: when supporting-action live_need is non-empty, prefer (and if
        possible only choose) bank gets that fill that need.
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

        try:
            from core.ai_hand_risk import get_hand_risk_profile, select_risk_twb_candidate
        except Exception:
            return None

        profile = get_hand_risk_profile(self, player)
        if not isinstance(profile, Mapping) or not profile:
            return None
        rates = self.get_player_bank_trade_rates(player)
        _act, _cost, live_need = self._supporting_action_live_need_vector(player)
        selected = select_risk_twb_candidate(
            profile,
            twb_candidates,
            rates=rates,
            rng_context=self._hand_risk_rng_context(player, tag="risk_twb"),
            live_need=live_need,
        )
        if not isinstance(selected, Mapping) or not selected:
            try:
                setattr(self, "last_risk_twb_skip", "no_candidate_after_live_need_filter")
            except Exception:
                pass
            return None

        give = self._normalize_twb_vector(selected.get("give", []))
        get = self._normalize_twb_vector(selected.get("get", []))
        names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]
        give_text = self._format_twb_amounts(give, names)
        get_text = self._format_twb_amounts(get, names)
        best_text = f"TwB {give_text} -> {get_text} (hand risk)"
        reason = str(selected.get("reason") or "Stage B risk TwB: dump ditch to reduce discard exposure")

        return {
            "step": step,
            "action": "TwB",
            "label": f"TwB {give_text} -> {get_text}",
            "status": "will_try",
            "reason": reason,
            "source": "ai_risk_twb",
            "mode": "risk_twb",
            "choice": {
                "action": "TwB",
                "viable": True,
                "actionable": True,
                "reason": "Stage B risk TwB — ditch export under hand-risk policy.",
                "candidates": [dict(selected.get("candidate") or {})],
            },
            "candidate": dict(selected.get("candidate") or {}),
            "give": list(give),
            "get": list(get),
            "rates": list(rates[:5]) if isinstance(rates, Sequence) else [4, 4, 4, 4, 4],
            "hand_before": list(selected.get("hand_before") or []),
            "hand_after": list(selected.get("hand_after") or []),
            "then_plan_item": {},  # no build follow-up — pure risk valve
            "best_action_label": f"{give_text} -> {get_text}",
            "best_action_text": best_text,
            "hand_risk_policy": selected.get("policy"),
            "size_delta": selected.get("size_delta"),
            "keep_at_risk_before": selected.get("keep_at_risk_before"),
            "keep_at_risk_after": selected.get("keep_at_risk_after"),
            "get_need_bonus": selected.get("get_need_bonus"),
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(player, "id", None),
        }

    def _plan_sticky_structure_if_affordable_now(
        self, *, step: int = 1
    ) -> Optional[Dict[str, Any]]:
        """If sticky/SE settle or city is legal+affordable now, BA that build.

        Used when road-guard Wait would otherwise fire with a completed path
        (owned sticky roads) and a full settle cost in hand — no TwB needed.
        """
        if str(getattr(self, "phase", "")) != "Execution":
            return None
        if str(getattr(self, "state", "")) != "ActionSelection":
            return None
        player = self.get_current_player()
        if player is None or self._is_current_player_human_for_execution():
            return None

        direction = self._current_player_strategic_direction()
        action = self._target_action_from_strategic_direction(direction)
        if action not in {"Build settlement", "Build city"}:
            # Path may still look like "road" if callers didn't filter — prefer
            # settle when route remaining is empty.
            route = self._settlement_route_plan()
            if (
                isinstance(route, Mapping)
                and route.get("target_settlement_id") not in (None, "")
                and not list(route.get("roads_to_build") or [])
            ):
                action = "Build settlement"
            else:
                return None

        target_candidate = self._candidate_for_ai_twb_target(player, action, direction)
        if not target_candidate:
            return None
        cost = self._execution_cost_vector_for_action(action)
        hand = self._execution_hand_vector_for_player(player)
        if not self._vector_can_pay(hand, cost):
            return None

        tid = None
        try:
            tid = int(target_candidate.get("target_id"))
        except Exception:
            tid = None
        # Prefer a live scanner candidate for the same target when present
        scan = getattr(self, "current_viable_action_scan", None)
        cand = dict(target_candidate)
        if isinstance(scan, Mapping) and tid is not None:
            for c in list((scan.get("candidates") or {}).get(action, []) or []):
                if not isinstance(c, Mapping):
                    continue
                try:
                    if int(c.get("target_id") or c.get("intersection_id") or -1) == tid:
                        cand = dict(c)
                        break
                except Exception:
                    continue

        choice = {
            "action": action,
            "viable": True,
            "actionable": True,
            "priority": 0,
            "reason": "Sticky/SE structure affordable now (complete target this turn).",
            "candidates": [cand],
            "candidate": cand,
        }
        plan_item = self._plan_item_from_execution_choice(
            choice, source="sticky_structure_now", step=step
        )
        if not isinstance(plan_item, Mapping) or not plan_item.get("action"):
            return None
        if str(plan_item.get("status") or "") in {"blocked", "route_blocked"}:
            return None
        if str(plan_item.get("action") or "") not in {"Build settlement", "Build city"}:
            return None
        plan_item = dict(plan_item)
        plan_item["reason"] = (
            f"Complete sticky target now: {action}"
            + (f" @{tid}" if tid is not None else "")
        )
        return plan_item

    def _synthesize_live_need_twb_candidates(
        self,
        *,
        live_need: Sequence[int],
        surplus: Sequence[int],
        rates: Sequence[int],
        names: Sequence[str],
    ) -> List[Dict[str, Any]]:
        """S4/R6: legal 4:1/port rows for each positive live_need resource."""
        out: List[Dict[str, Any]] = []
        need = [max(0, int(x or 0)) for x in list(live_need)[:5]]
        surp = [max(0, int(x or 0)) for x in list(surplus)[:5]]
        rate_v = [max(1, int(x or 4)) for x in list(rates)[:5]]
        while len(need) < 5:
            need.append(0)
        while len(surp) < 5:
            surp.append(0)
        while len(rate_v) < 5:
            rate_v.append(4)
        name_v = [str(n) for n in list(names)[:5]]
        while len(name_v) < 5:
            name_v.append("?")
        for get_idx in range(5):
            if need[get_idx] <= 0:
                continue
            for give_idx in range(5):
                if give_idx == get_idx:
                    continue
                rate = rate_v[give_idx]
                if surp[give_idx] < rate:
                    continue
                give = [0, 0, 0, 0, 0]
                get = [0, 0, 0, 0, 0]
                give[give_idx] = rate
                get[get_idx] = 1
                out.append(
                    {
                        "description": (
                            f"Trade {rate} {name_v[give_idx]} for 1 {name_v[get_idx]}"
                        ),
                        "give_resource": name_v[give_idx],
                        "get_resource": name_v[get_idx],
                        "give_index": give_idx,
                        "get_index": get_idx,
                        "rate": rate,
                        "give_vector": list(give),
                        "get_vector": list(get),
                        "source": "s4_live_need_synth",
                    }
                )
        return out

    def _merge_twb_candidate_lists(
        self,
        primary: Sequence[Mapping[str, Any]],
        extra: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge TwB candidate lists without duplicate give/get index pairs."""
        out: List[Dict[str, Any]] = []
        seen = set()

        def _key(c: Mapping[str, Any]) -> Tuple[int, int, int]:
            try:
                gi = int(c.get("give_index", -1))
                ri = int(c.get("get_index", -1))
                rate = int(c.get("rate", 0) or 0)
                return (gi, ri, rate)
            except Exception:
                return (-1, -1, 0)

        for src in (primary, extra):
            for c in list(src or []):
                if not isinstance(c, Mapping):
                    continue
                k = _key(c)
                if k in seen and k != (-1, -1, 0):
                    continue
                seen.add(k)
                out.append(dict(c))
        return out

    def _plan_ai_trade_with_bank_for_strategy(self, *, step: int = 1) -> Optional[Dict[str, Any]]:
        """Plan one AI TwB support action that immediately unlocks the strategic target.

        This deliberately uses three sources:
        - viable_action_scanner TwB candidates = legal menu;
        - live need_vector from current hand and target cost = execution truth;
        - action-planner need_vector = strategic hint / debug evidence.
        - S4: synthesized live_need rows when the scanner menu is incomplete.
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
            # Direct execution should be handled by normal Best-Action, not TwB.
            return None

        live_need = self._vector_subtract_floor_zero(cost, hand)
        need_units_before = int(sum(live_need))
        if need_units_before <= 0:
            return None
        report_need = self._report_need_vector_from_direction(direction)
        surplus = self._vector_subtract_floor_zero(hand, cost)
        rates = self.get_player_bank_trade_rates(player)
        names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]

        # S4 / P0-R6: ensure at least one legal bank row exists for each live_need
        # resource when surplus funds a rate (scanner menu may be capped/thin).
        try:
            synth = self._synthesize_live_need_twb_candidates(
                live_need=live_need,
                surplus=surplus,
                rates=rates,
                names=names,
            )
            if synth:
                twb_candidates = self._merge_twb_candidate_lists(twb_candidates, synth)
        except Exception:
            pass
        if not twb_candidates:
            return None

        # Allow *partial* need-fill TwB (e.g. need Wood+Brick for road, only buy Wood
        # this trade). Previously required full unlock in one bank trade, so strategy
        # TwB often failed and Stage B risk TwB dumped into Ore/Wheat instead.
        ranked: List[
            Tuple[Tuple[int, int, int, int, int], Dict[str, Any], List[int], List[int], List[int], bool, int]
        ] = []
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
            if any(v < 0 for v in after):
                continue
            need_after_vec = self._vector_subtract_floor_zero(cost, after)
            need_units_after = int(sum(need_after_vec))
            need_reduced = need_units_before - need_units_after
            if need_reduced <= 0:
                continue
            fully_unlocks = self._vector_can_pay(after, cost)

            # Ranking (lower better): full unlock first, then better rate, more need
            # filled, larger surplus dump, stable give index.
            try:
                rate = int(candidate.get("rate", rates[give_idx]) or rates[give_idx] or 4)
            except Exception:
                rate = int(rates[give_idx] or 4)
            served_report_need = 1 if int(report_need[get_idx] or 0) > 0 else 0
            rank = (
                0 if fully_unlocks else 1,
                rate,
                -need_reduced,
                -served_report_need,
                -int(surplus[give_idx] or 0),
                int(give_idx),
            )
            ranked.append((rank, candidate, give, get, after, fully_unlocks, need_reduced))

        if not ranked:
            return None

        ranked.sort(key=lambda item: item[0])
        _rank, candidate, give, get, after, fully_unlocks, need_reduced = ranked[0]
        followup: Dict[str, Any] = {}
        if fully_unlocks:
            followup = self._ai_twb_followup_plan_item(player, action, target_candidate) or {}

        give_text = self._format_twb_amounts(give, names)
        get_text = self._format_twb_amounts(get, names)
        if fully_unlocks and followup:
            follow_text = str(followup.get("best_action_text", "") or followup.get("label", action))
            best_text = f"TwB {give_text} -> {get_text}; then {follow_text}".strip()
            reason = f"AI TwB support: unlocks {follow_text}."
            choice_reason = "Legal scanner TwB candidate unlocks current strategic target."
        else:
            best_text = f"TwB {give_text} -> {get_text} (need -{need_reduced} toward {action})"
            reason = (
                f"AI TwB support: fills {need_reduced} missing card(s) toward {action}"
                + (" (full cost, follow-up pending)." if fully_unlocks else " (partial).")
            )
            choice_reason = (
                "Legal scanner TwB reduces live need for current supporting action."
            )

        plan_item: Dict[str, Any] = {
            "step": step,
            "action": "TwB",
            "label": f"TwB {give_text} -> {get_text}",
            "status": "will_try",
            "reason": reason,
            "source": "ai_twb_support",
            "mode": "unlock_full" if fully_unlocks else "unlock_partial",
            "choice": {
                "action": "TwB",
                "viable": True,
                "actionable": True,
                "reason": choice_reason,
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
            "need_reduced": int(need_reduced),
            "fully_unlocks": bool(fully_unlocks),
            "then_plan_item": dict(followup),
            "best_action_label": f"{give_text} -> {get_text}",
            "best_action_text": best_text,
            "round": getattr(self, "round", None),
            "turn": getattr(self, "turn", None),
            "state": getattr(self, "state", None),
            "player_id": getattr(player, "id", None),
        }
        return plan_item

    def _execute_ai_twb_support_plan(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        """Execute AI TwB, rescan, then execute the unlocked strategic build/buy.

        Stage B risk TwB uses the same path with empty ``then_plan_item`` (no follow-up).
        """
        give = self._normalize_twb_vector(plan_item.get("give", []))
        get = self._normalize_twb_vector(plan_item.get("get", []))
        names = [self._resource_name_for_turn_delta(r) for r in self._execution_resource_order()[:5]]
        give_text = self._format_twb_amounts(give, names)
        get_text = self._format_twb_amounts(get, names)

        is_risk = str(plan_item.get("source", "") or "") == "ai_risk_twb" or str(plan_item.get("mode", "") or "") == "risk_twb"
        twb_result = self.execute_trade_with_bank_vector_action(
            give,
            get,
            source="ai_risk_twb" if is_risk else "ai_twb_planner",
            reason=str(plan_item.get("reason") or ("ai_risk_twb" if is_risk else "ai_twb_unlocks_strategic_target")),
        )
        if not bool(twb_result.get("ok")):
            return {
                "ok": False,
                "action": "TwB",
                "reason": f"twb_failed:{twb_result.get('reason', 'unknown')}",
                "twb_result": dict(twb_result),
            }

        if not is_risk:
            self._bump_support_trade_count()

        try:
            self.refresh_strategy_after_event("after_ai_twb_support", kind="hand")
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_ai_twb_support")
        except Exception:
            pass
        try:
            from core.strategy_offway_q1 import maybe_q1_offway_structure_l2

            maybe_q1_offway_structure_l2(
                self,
                player,
                reason="after_ai_twb_support",
                rescan=True,
            )
        except Exception:
            pass
        try:
            from core.strategy_offway_q2 import apply_q2_offway_dcard_permission

            apply_q2_offway_dcard_permission(
                self, player, reason="after_ai_twb_support"
            )
        except Exception:
            pass

        planned_followup = plan_item.get("then_plan_item", {})
        followup_item = dict(planned_followup) if isinstance(planned_followup, Mapping) else {}
        current_best = self.get_current_best_executable_action()
        if isinstance(current_best, Mapping) and str(current_best.get("action", "") or "") == str(followup_item.get("action", "") or ""):
            followup_item = dict(current_best)

        if not followup_item or str(followup_item.get("action", "") or "") == "TwB":
            # S4/R1: partial strategy TwB → chain another support trade (not risk dump)
            if not is_risk:
                chain = self._chain_next_support_trade_plan()
                if isinstance(chain, Mapping) and chain.get("action"):
                    self._arm_support_trade_chain(chain, source="ai_twb_partial_chain")
                    return {
                        "ok": True,
                        "action": "TwB",
                        "support_action": "TwB",
                        "reason": "twb_partial_chain_ready",
                        "message": f"TwB {give_text} -> {get_text}; chain {chain.get('action')}",
                        "twb_result": dict(twb_result),
                        "chain_next": dict(chain),
                    }
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

    def _resolve_endgame_scan(self) -> Any:
        """Best available viable-action scan for S6 (no re-scan)."""
        for attr in (
            "current_viable_action_scan",
            "last_viable_scan",
        ):
            scan = getattr(self, attr, None)
            if scan is not None:
                return scan
        epm = getattr(self, "_execution_phase_manager", None)
        if epm is not None:
            scan = getattr(epm, "last_scan", None)
            if scan is not None:
                return scan
        report = getattr(self, "last_execution_scan_report", None)
        if isinstance(report, Mapping):
            return report.get("scan")
        return None

    def _run_endgame_sequence_pick(self, *, force: bool = False) -> Dict[str, Any]:
        """S6a/S6b: pick city vs settle/road for this turn; cache per round/turn/player."""
        from core.endgame_sequence import (
            format_endgame_sequence_dbg,
            pick_endgame_immediate_action,
        )

        player = None
        try:
            player = self.get_current_player()
        except Exception:
            player = None
        try:
            cache_key = (
                int(getattr(self, "round", 0) or 0),
                int(getattr(self, "turn", 0) or 0),
                int(getattr(player, "id", -1) or -1) if player is not None else -1,
                str(getattr(self, "state", "") or ""),
            )
        except Exception:
            cache_key = None
        if (
            not force
            and cache_key is not None
            and getattr(self, "_endgame_sequence_cache_key", None) == cache_key
            and isinstance(getattr(self, "last_endgame_sequence", None), Mapping)
        ):
            return dict(self.last_endgame_sequence)

        direction = {}
        if player is not None:
            direction = getattr(player, "strategic_direction", None) or {}
            if not isinstance(direction, Mapping):
                direction = {}
        scan = self._resolve_endgame_scan()
        try:
            meta = pick_endgame_immediate_action(self, player, direction, scan)
        except Exception as exc:
            meta = {
                "pick": None,
                "immediate_action": "",
                "skipped": True,
                "reason": f"endgame_error:{exc}",
                "mode": None,
                "gate": False,
            }
        meta = dict(meta or {})
        meta["dbg"] = format_endgame_sequence_dbg(meta)
        try:
            self.last_endgame_sequence = dict(meta)
            self._endgame_sequence_cache_key = cache_key
        except Exception:
            pass
        try:
            report = getattr(self, "last_execution_scan_report", None)
            if isinstance(report, dict):
                report["s6_endgame_sequence"] = dict(meta)
                report["s6_endgame_dbg"] = meta.get("dbg")
        except Exception:
            pass
        return dict(meta)

    def _compute_current_best_executable_action(self) -> Optional[Dict[str, Any]]:
        """Compute the current canonical Best-Action action from existing scan rows."""
        executable_actions = {"Buy development_card", "Build city", "Build settlement", "Build road"}
        route_plan = self._settlement_route_plan()
        if route_plan.get("kind") == "new_settlement":
            action_priority = {"Build road": 1, "Build settlement": 2, "Build city": 3, "Buy development_card": 4}
        elif route_plan.get("kind") == "next_settlement":
            action_priority = {"Build settlement": 1, "Build city": 2, "Build road": 3, "Buy development_card": 4}
        else:
            action_priority = {"Build city": 1, "Build settlement": 2, "Build road": 3, "Buy development_card": 4}

        # S6: elevate city (or path) when endgame sequence says so — fixes road-first
        # new_settlement BA thrashing a 5th settle while a city is better.
        s6_meta: Dict[str, Any] = {}
        try:
            s6_meta = self._run_endgame_sequence_pick()
            from core.endgame_sequence import apply_endgame_action_priority

            action_priority = apply_endgame_action_priority(action_priority, s6_meta or {})
        except Exception:
            s6_meta = {}
        # S-LR-C: live claim / LA race / dense-pack deferral from pick_turn_focus
        slr_c_focus: Dict[str, Any] = {}
        try:
            from core.ai_lr_project import apply_slr_c_action_priority, pick_turn_focus

            _p = self.get_current_player()
            if _p is not None:
                slr_c_focus = pick_turn_focus(self, _p)
                action_priority = apply_slr_c_action_priority(action_priority, slr_c_focus)
        except Exception:
            slr_c_focus = {}
        # P2: risk M/H sticky race → BA chase settle/key road (risk=L unchanged)
        race_ba: Dict[str, Any] = {}
        try:
            from core.strategy_race_ba import (
                apply_race_ba_action_priority,
                race_ba_focus,
            )

            _p = self.get_current_player()
            if _p is not None:
                race_ba = race_ba_focus(self, _p)
                action_priority = apply_race_ba_action_priority(action_priority, race_ba)
        except Exception:
            race_ba = {}

        rows = [row for row in list(getattr(self, "current_actionable_choices", []) or []) if isinstance(row, Mapping)]
        rows = [row for row in rows if str(row.get("action", "") or "") in executable_actions and bool(row.get("actionable", row.get("viable", False)))]

        q2_allow = False
        q2_block_fallback = False
        try:
            from core.strategy_offway_q2 import q2_dcard_allowed, q2_dcard_blocked

            q2_allow = bool(q2_dcard_allowed(self))
            q2_block_fallback = bool(q2_dcard_blocked(self))
        except Exception:
            pass

        if not rows:
            # Fallback keeps older/no-strategy turns usable, but still reads from
            # scanner rows rather than from stale preview-plan rows.
            rows = [row for row in list(getattr(self, "current_execution_choices", []) or []) if isinstance(row, Mapping)]
            rows = [row for row in rows if str(row.get("action", "") or "") in executable_actions and bool(row.get("viable", False))]
            # P1+Q2: prefer soft off-way DCard when allowed; strip blocked DCard fallback
            if q2_allow:
                dcard_rows = [r for r in rows if str(r.get("action", "") or "") == "Buy development_card"]
                if dcard_rows:
                    rows = dcard_rows
            elif q2_block_fallback:
                rows = [r for r in rows if str(r.get("action", "") or "") != "Buy development_card"]

        if not rows:
            twp_plan = self._plan_ai_trade_with_player_for_strategy(step=1)
            if isinstance(twp_plan, Mapping) and twp_plan.get("action"):
                return dict(twp_plan)
            # Unlock TwB first (make preferred action affordable)
            twb_plan = self._plan_ai_trade_with_bank_for_strategy(step=1)
            if isinstance(twb_plan, Mapping) and twb_plan.get("action"):
                return dict(twb_plan)
            # Stage C + B: secondary helpful build/buy vs risk TwB
            risk_package = self._plan_ai_risk_package(step=1)
            if isinstance(risk_package, Mapping) and risk_package.get("action"):
                return dict(risk_package)
            return None

        def _action_wins_now(action_name: str) -> bool:
            """W4: prefer city/settlement that pushes effective_vp ≥ threshold."""
            try:
                from core.victory import effective_vp, victory_point_threshold

                player = self.get_current_player()
                if player is None:
                    return False
                vp = int(effective_vp(player))
                thr = int(victory_point_threshold(self))
                if action_name == "Build city":
                    return vp + 1 >= thr  # city net +1
                if action_name == "Build settlement":
                    return vp + 1 >= thr
            except Exception:
                return False
            return False

        def _sort_key(row: Mapping[str, Any]) -> Tuple[int, int, int, int]:
            action_name = str(row.get("action", "") or "")
            # 0 = winning action first
            win_rank = 0 if _action_wins_now(action_name) else 1
            try:
                row_priority = int(row.get("priority", 99) or 99)
            except Exception:
                row_priority = 99
            try:
                from core.strategy_race_ba import race_ba_sort_bonus

                race_bonus = int(race_ba_sort_bonus(row, race_ba))
            except Exception:
                race_bonus = 1
            # Family priority (route + S6 + P2 race) before per-row scanner priority
            return (
                win_rank,
                action_priority.get(action_name, 99),
                race_bonus,
                row_priority,
            )

        choice = dict(sorted(rows, key=_sort_key)[0])
        ba_source = "canonical_best_action"
        try:
            if (
                q2_allow
                and str(choice.get("action") or "") == "Buy development_card"
                and not any(
                    bool(r.get("actionable", False))
                    for r in list(getattr(self, "current_actionable_choices", []) or [])
                    if isinstance(r, Mapping)
                )
            ):
                ba_source = "canonical_best_action_q2_offway_dcard"
        except Exception:
            pass
        plan = self._plan_item_from_execution_choice(choice, source=ba_source, step=1)
        try:
            if ba_source.endswith("q2_offway_dcard"):
                plan["q2_offway_dcard"] = True
                plan["reason"] = str(
                    plan.get("reason")
                    or "P1+Q2 opportunistic off-way DCard (guards passed; no L2)."
                )
        except Exception:
            pass
        try:
            if _action_wins_now(str(choice.get("action") or "")):
                plan["win_now"] = True
                plan["source"] = "canonical_best_action_win"
        except Exception:
            pass
        try:
            if s6_meta and not s6_meta.get("skipped") and s6_meta.get("immediate_action"):
                plan["endgame_sequence"] = {
                    "pick": s6_meta.get("pick"),
                    "mode": s6_meta.get("mode"),
                    "reason": s6_meta.get("reason"),
                }
                if str(choice.get("action") or "") == str(s6_meta.get("immediate_action") or ""):
                    plan["source"] = str(plan.get("source") or "canonical_best_action") + "_s6"
        except Exception:
            pass
        try:
            if slr_c_focus and slr_c_focus.get("focus"):
                plan["turn_focus"] = slr_c_focus.get("focus")
                plan["turn_focus_reason"] = slr_c_focus.get("reason")
                plan["dense_pack"] = bool(slr_c_focus.get("dense_pack"))
                plan["la_race"] = bool(slr_c_focus.get("la_race"))
                plan["lr_race"] = bool(slr_c_focus.get("lr_race"))
                if str(slr_c_focus.get("focus") or "") in {"lr", "la", "city"}:
                    plan["source"] = str(plan.get("source") or "canonical_best_action") + "_slr_c"
        except Exception:
            pass
        try:
            if race_ba and race_ba.get("apply"):
                plan["race_ba"] = {
                    "focus": race_ba.get("focus"),
                    "risk_level": race_ba.get("risk_level"),
                    "target_id": race_ba.get("target_id"),
                    "next_road": race_ba.get("next_road"),
                    "reason": race_ba.get("reason"),
                    "dig_note": race_ba.get("dig_note"),
                }
                plan["source"] = str(plan.get("source") or "canonical_best_action") + "_race_ba"
        except Exception:
            pass
        # Complete sticky/SE target this turn: never leave a road-guard Wait when
        # the settle/city is already buildable, or TwP/TwB can unlock it.
        try:
            status = str((plan or {}).get("status") or "")
            action = str((plan or {}).get("action") or "")
            blocked = bool((plan or {}).get("route_blocked")) or status in {
                "blocked",
                "route_blocked",
            }
            is_wait = action in {"End turn", "Wait", "Pass"} or (
                "Wait / Prio" in str((plan or {}).get("label") or "")
            )
            if blocked or is_wait:
                # 1) Affordable sticky settle/city now (no TwB needed) — build it
                direct = self._plan_sticky_structure_if_affordable_now(step=1)
                if isinstance(direct, Mapping) and direct.get("action"):
                    direct = dict(direct)
                    direct["replaced_wait"] = True
                    direct["prior_ba_source"] = (plan or {}).get("source")
                    return direct
                # 2) Unlock via TwP / TwB
                twp_plan = self._plan_ai_trade_with_player_for_strategy(step=1)
                if isinstance(twp_plan, Mapping) and twp_plan.get("action"):
                    twp_plan = dict(twp_plan)
                    twp_plan["replaced_wait"] = True
                    twp_plan["prior_ba_source"] = (plan or {}).get("source")
                    return twp_plan
                twb_plan = self._plan_ai_trade_with_bank_for_strategy(step=1)
                if isinstance(twb_plan, Mapping) and twb_plan.get("action"):
                    twb_plan = dict(twb_plan)
                    twb_plan["replaced_wait"] = True
                    twb_plan["prior_ba_source"] = (plan or {}).get("source")
                    return twb_plan
        except Exception:
            pass
        return plan

    def _best_action_is_current(self, plan_item: Any) -> bool:
        """Return True when a stored Best-Action object belongs to this live turn.

        T8-complete: declined Incoming TwP is never “current” (forces recompute /
        fall-through so Continue cannot re-open the same panel).
        """
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
        # T8: stale Incoming after HP decline
        if self._plan_item_is_declined_incoming_twp(plan_item):
            return False
        return True

    def get_current_best_executable_action(self) -> Optional[Dict[str, Any]]:
        """Return the canonical buy/build action that Continue should execute now.

        Execution Debug displays this same object.  AI Continue executes this same
        object.  The method does not refresh the scanner at click time, because a
        refresh can reorder candidates and make the executed target differ from
        the displayed Best-Action target.

        T8-complete: never returns a declined Incoming TwP plan item.
        """
        stored = getattr(self, "current_best_action", None)
        if self._best_action_is_current(stored):
            return dict(stored)
        # Drop stale declined Incoming so we do not keep returning it
        if self._plan_item_is_declined_incoming_twp(stored):
            try:
                self.current_best_action = None
            except Exception:
                pass

        plan_item = self._compute_current_best_executable_action()
        if self._plan_item_is_declined_incoming_twp(plan_item):
            plan_item = None
        self.current_best_action = dict(plan_item) if isinstance(plan_item, Mapping) else None
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
        """Return VP points from victory-point development cards (each card = 1)."""
        try:
            from core.victory import count_vp_development_cards

            return int(count_vp_development_cards(player))
        except Exception:
            pass
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

    def effective_vp(self, player: Optional[Player] = None) -> int:
        """Board + specials + VP DCards for win check."""
        from core.victory import effective_vp as _effective_vp

        p = player if player is not None else self.get_current_player()
        return int(_effective_vp(p))

    def vp_breakdown(self, player: Optional[Player] = None) -> Dict[str, Any]:
        """Structured VP breakdown for one player."""
        from core.victory import vp_breakdown as _vp_breakdown

        p = player if player is not None else self.get_current_player()
        return dict(_vp_breakdown(p))

    def reveal_all_vp_cards(self, player: Optional[Player] = None) -> Dict[str, Any]:
        """Reveal all victory-point DCards (claim-win bookkeeping)."""
        from core.victory import reveal_all_vp_cards as _reveal

        p = player if player is not None else self.get_current_player()
        return dict(_reveal(self, p))

    def check_and_declare_winner(
        self,
        player: Optional[Player] = None,
        *,
        reason: str = "",
        require_current_player: bool = True,
        emit_events: bool = True,
        refresh_ui: bool = True,
    ) -> Dict[str, Any]:
        """Declare winner if player has ≥ VICTORY points on their turn (W1).

        Idempotent when ``game_over`` is already set. Does not open the W3 panel.
        """
        from core.victory import check_and_declare_winner as _check

        p = player if player is not None else self.get_current_player()
        return dict(
            _check(
                self,
                p,
                reason=reason,
                require_current_player=require_current_player,
                emit_events=emit_events,
                refresh_ui=refresh_ui,
            )
        )

    def open_game_over_panel(self, win_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """W3: open post-game Statistics / Playboard / New Game UI."""
        try:
            from gui.gui_game_over_panel import open_game_over_panel as _open

            return dict(_open(self, win_result=win_result))
        except Exception as exc:
            return {"active": False, "reason": f"open_failed:{exc}"}

    def is_game_over(self) -> bool:
        """True when a winner has been declared (W2 gate)."""
        return bool(getattr(self, "game_over", False))

    def _maybe_declare_winner_after(
        self,
        reason: str = "",
        player: Optional[Player] = None,
        *,
        require_current_player: bool = True,
    ) -> Dict[str, Any]:
        """W2: after a VP-affecting mutation, check whether the actor won.

        Central hook used by builds, free roads / TFR complete, LA after knight,
        DCard buy, and optional Slice D continuation.  Idempotent and safe when
        already over.  UI scoreboard refresh + twitter live inside
        ``check_and_declare_winner``.
        """
        if bool(getattr(self, "game_over", False)):
            return {
                "ok": True,
                "won": False,
                "already_over": True,
                "reason": "already_over",
                "player_id": getattr(getattr(self, "winner", None), "id", None),
                "win_result": getattr(self, "win_result", None),
            }
        p = player if player is not None else None
        if p is None:
            try:
                p = self.get_current_player()
            except Exception:
                p = getattr(self, "current_player", None)
        try:
            return self.check_and_declare_winner(
                p,
                reason=str(reason or "after_action"),
                require_current_player=require_current_player,
                emit_events=True,
                refresh_ui=True,
            )
        except Exception as exc:
            return {
                "ok": False,
                "won": False,
                "already_over": False,
                "reason": f"win_check_failed:{exc}",
                "player_id": getattr(p, "id", None) if p is not None else None,
                "win_result": None,
            }

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

    def _mature_player_dcard_new_to_playable(self, player: Optional[Player]) -> Dict[str, Any]:
        """Move scoreboard x→y for one player: new_this_turn into playable.

        Triplet columns: ``[name, new/received (x), playable (y), played (z)]``.
        At the end of a player's turn (or start of their next), cards bought
        that turn become playable: ``y += x; x = 0``. Never touches *z*.
        """
        out: Dict[str, Any] = {"ok": False, "player_id": None, "moved": 0}
        if player is None:
            return out
        try:
            out["player_id"] = int(getattr(player, "id", 0) or 0)
        except Exception:
            out["player_id"] = None
        try:
            self._ensure_player_dcard_state(player)
        except Exception:
            pass
        moved = 0
        matured_types: List[str] = []
        try:
            summary = list(getattr(player, "dcard_summary", []) or [])
            for i, row in enumerate(summary):
                if not row:
                    continue
                row_list = list(row)
                while len(row_list) < 4:
                    row_list.append(0)
                try:
                    new_n = max(0, int(row_list[1] or 0))
                    play_n = max(0, int(row_list[2] or 0))
                except Exception:
                    continue
                if new_n <= 0:
                    summary[i] = row_list[:4]
                    continue
                row_list[2] = play_n + new_n
                row_list[1] = 0
                # col3 (played/revealed) intentionally unchanged
                summary[i] = row_list[:4]
                moved += new_n
                try:
                    matured_types.append(str(row_list[0]))
                except Exception:
                    pass
            player.dcard_summary = summary
            out["ok"] = True
            out["moved"] = int(moved)
            out["types"] = list(matured_types)
            if moved > 0:
                try:
                    from core import mglog

                    mglog.log_activate_dcard(
                        self,
                        player,
                        moved=moved,
                        types=matured_types,
                        source="maturity",
                    )
                except Exception:
                    pass
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def _add_development_card_to_player(self, player: Player, card_name: str) -> None:
        """Add a bought development card to the player's hidden card state.

        This helper is intentionally shared by AI and human DCard buy flows.
        It updates the hidden card list, the v045-style DCard triplet summary,
        the total DCard count, and victory points for VP cards.

        Scoreboard triplet: ``x/y/z`` = new-this-turn / playable / played.
        A buy always increments *x* only. VP cards count for score via the
        hidden ``development_cards`` list — *z* is only for played progress
        cards or revealed VPs at win claim (never incremented on buy).
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
                # Column 1 (x) = received this turn / not yet playable.
                # Column 2 (y) = playable later (maturity moves x→y after turn).
                # Column 3 (z) = played (or revealed VP) — never touched on buy.
                player.dcard_summary[idx][1] = int(player.dcard_summary[idx][1] or 0) + 1
            except Exception:
                pass

        self._record_dcard_buy_detail(player, card_name)

        player.number_of_dcards = len(getattr(player, "development_cards", []) or [])
        try:
            player.recalculate_victory_points()
        except Exception:
            pass

    def _remove_development_card_from_player(self, player: Player, card_name: str) -> bool:
        """Remove one *playable* development card from hidden hand + summary.

        Only decrements playable (col2 / y). Same-turn buys live in col1 (x)
        until maturity and cannot be spent here. Increments played (col3 / z).
        """
        card_name = str(card_name or "").strip()
        if not card_name or player is None:
            return False
        self._ensure_player_dcard_state(player)

        idx = self._execution_dcard_summary_index(card_name)
        playable = 0
        if idx >= 0:
            try:
                while len(player.dcard_summary[idx]) < 4:
                    player.dcard_summary[idx].append(0)
                playable = int(player.dcard_summary[idx][2] or 0)
            except Exception:
                playable = 0
        if playable <= 0:
            return False

        cards = list(getattr(player, "development_cards", []) or [])
        removed = False
        for i, c in enumerate(cards):
            if str(c) == card_name:
                cards.pop(i)
                removed = True
                break
        if not removed:
            # Summary said playable but hand empty — still clear one playable
            # slot so UI bookkeeping does not stick forever.
            removed = True
        player.development_cards = cards

        if idx >= 0:
            try:
                player.dcard_summary[idx][2] = max(0, playable - 1)
                player.dcard_summary[idx][3] = int(player.dcard_summary[idx][3] or 0) + 1
            except Exception:
                pass

        player.number_of_dcards = len(getattr(player, "development_cards", []) or [])
        return True

    def _mark_dcard_played_this_turn(
        self,
        card_name: str,
        player: Optional[Player] = None,
    ) -> None:
        """Mark one development card type as played for this active turn.

        Also records which player played it so the scoreboard can highlight
        that player's DCard type triplet in red (not every row).
        """
        idx = self._execution_dcard_summary_index(card_name)
        player_id: Optional[int] = None
        try:
            if player is not None:
                player_id = int(getattr(player, "id", 0) or 0) or None
        except Exception:
            player_id = None
        if player_id is None:
            try:
                current = self.get_current_player()
                if current is not None:
                    player_id = int(getattr(current, "id", 0) or 0) or None
            except Exception:
                player_id = None

        for owner in (getattr(self, "myturn", None), getattr(self, "turn_details", None)):
            if owner is None:
                continue
            try:
                setattr(owner, "dcard_played_in_turn_TF", True)
                vec = list(getattr(owner, "dcard_played_in_turn", None) or [0, 0, 0, 0, 0])
                while len(vec) < 5:
                    vec.append(0)
                if 0 <= idx < 5:
                    vec[idx] = int(vec[idx] or 0) + 1
                setattr(owner, "dcard_played_in_turn", vec[:5])
                setattr(owner, "dcard_played_in_turn_player_id", player_id)
            except Exception:
                pass
        try:
            self.dcard_played_in_turn_player_id = player_id
        except Exception:
            pass

        # D2: arm full seat-turn header play pulse (human Confirm + AI after mark)
        try:
            gui = getattr(self, "gui", None)
            arm = getattr(gui, "arm_dcard_header_play_fx", None) if gui is not None else None
            if callable(arm):
                pl = player
                if pl is None and player_id:
                    try:
                        for p in list(getattr(self, "players", []) or []):
                            if p is not None and int(getattr(p, "id", 0) or 0) == int(player_id):
                                pl = p
                                break
                    except Exception:
                        pl = None
                arm(str(card_name or ""), pl, player_id=player_id)
        except Exception:
            pass

    def clear_dcard_header_play_fx(self) -> None:
        """Clear shared DCard header play pulse (seat-turn boundary)."""
        try:
            gui = getattr(self, "gui", None)
            clear = getattr(gui, "clear_dcard_header_play_fx", None) if gui is not None else None
            if callable(clear):
                clear()
        except Exception:
            pass

    def recompute_largest_army(
        self,
        *,
        reason: str = "",
        emit_events: bool = True,
    ) -> Dict[str, Any]:
        """Recompute Largest Army holder from all players' played-knight counts.

        Rules (standard Catan):
          - Need ≥3 played knights to claim the special.
          - On an exact size tie, the **current holder keeps** the special
            (steal requires strictly more knights).
          - If nobody has ≥3, the special is vacant (no holder).

        Updates ``player.largest_army_tf``, ``game.largest_army_player``, and
        recalculates VP for any player whose holder flag changed. Optionally
        emits twitter only when the holder actually changes.
        """
        info: Dict[str, Any] = {
            "ok": True,
            "reason": str(reason or "recompute_largest_army"),
            "threshold": 3,
            "best_size": 0,
            "previous_holder_id": None,
            "holder_id": None,
            "holder_changed": False,
            "gained_largest_army": False,
            "lost_largest_army": False,
            "cleared": False,
            "army_sizes": {},
        }

        players = [p for p in list(getattr(self, "players", []) or []) if p is not None]
        previous = getattr(self, "largest_army_player", None)
        try:
            if previous is not None:
                info["previous_holder_id"] = int(getattr(previous, "id", 0) or 0) or None
        except Exception:
            info["previous_holder_id"] = None

        # List of (player, army_size) — do not use player as dict key (tests use
        # SimpleNamespace which is unhashable).
        sized: List[Tuple[Any, int]] = []
        best = 0
        for p in players:
            try:
                n = max(0, int(getattr(p, "size_largest_army", 0) or 0))
            except Exception:
                n = 0
            try:
                p.size_largest_army = n
            except Exception:
                pass
            sized.append((p, n))
            try:
                pid = int(getattr(p, "id", 0) or 0)
                info["army_sizes"][pid] = n
            except Exception:
                pass
            if n > best:
                best = n
        info["best_size"] = int(best)

        def _same_player(a: Any, b: Any) -> bool:
            if a is None or b is None:
                return False
            if a is b:
                return True
            try:
                return int(getattr(a, "id", 0) or 0) == int(getattr(b, "id", 0) or 0) and int(
                    getattr(a, "id", 0) or 0
                ) > 0
            except Exception:
                return False

        new_holder: Optional[Player] = None
        if best >= 3:
            candidates = [p for p, n in sized if n == best]
            # Tie: keep current holder if they are among the max
            if previous is not None and any(_same_player(previous, c) for c in candidates):
                # Prefer the actual object from players list
                new_holder = next((c for c in candidates if _same_player(previous, c)), previous)
            elif len(candidates) == 1:
                new_holder = candidates[0]
            elif candidates:
                # No prior holder (or prior not at max): stable pick by lowest player id
                def _pid(pl: Any) -> int:
                    try:
                        return int(getattr(pl, "id", 0) or 0)
                    except Exception:
                        return 0

                candidates.sort(key=_pid)
                new_holder = candidates[0]
            else:
                new_holder = None
        else:
            info["cleared"] = True
            new_holder = None

        changed_players: List[Any] = []
        for p in players:
            should_hold = new_holder is not None and _same_player(p, new_holder)
            try:
                had = bool(getattr(p, "largest_army_tf", False))
            except Exception:
                had = False
            if had != should_hold:
                try:
                    p.largest_army_tf = should_hold
                except Exception:
                    pass
                changed_players.append(p)

        try:
            self.largest_army_player = new_holder
        except Exception:
            pass

        for p in changed_players:
            try:
                p.recalculate_victory_points()
            except Exception:
                pass

        # Also refresh VP if flags unchanged but army size changed (scoreboard LA count)
        # — only when reason is after knight for the acting player path; keep cheap:
        # recalc all is fine (4 players).
        if not changed_players:
            # Still sync VP in case flags were already correct but totals drifted
            pass

        try:
            if new_holder is not None:
                info["holder_id"] = int(getattr(new_holder, "id", 0) or 0) or None
        except Exception:
            info["holder_id"] = None

        prev_id = info.get("previous_holder_id")
        new_id = info.get("holder_id")
        info["holder_changed"] = prev_id != new_id
        info["gained_largest_army"] = bool(new_id is not None and new_id != prev_id)
        info["lost_largest_army"] = bool(prev_id is not None and prev_id != new_id)

        if emit_events and info["holder_changed"]:
            try:
                if new_holder is not None and prev_id is None:
                    self.emit_twitter_event(
                        new_id,
                        f"takes Largest Army ({best} knights)",
                    )
                elif new_holder is not None and prev_id is not None:
                    self.emit_twitter_event(
                        new_id,
                        f"steals Largest Army ({best} knights)",
                    )
                    self.emit_twitter_event(
                        prev_id,
                        "loses Largest Army",
                    )
                elif new_holder is None and prev_id is not None:
                    self.emit_twitter_event(
                        prev_id,
                        "Largest Army special is vacant",
                    )
            except Exception:
                pass

        # MGlog: LA holder flip (even if twitter emit skipped; only when changed)
        if info.get("holder_changed"):
            try:
                from core import mglog

                mglog.log_largest_army_change(
                    self,
                    previous_holder_id=prev_id,
                    holder_id=new_id,
                    best_size=best,
                    reason=str(reason or "recompute_largest_army"),
                )
            except Exception:
                pass

        # Scoreboard after LA holder change (knight path also refreshes via DCard)
        if info["holder_changed"]:
            try:
                self._refresh_gui_scoreboard_after_dcard_change(
                    str(reason or "after_recompute_largest_army")
                )
            except Exception:
                pass
            # S1: acquiring LA → own milestone (force if legal acts); loser gets flag
            try:
                from core.strategy_sticky import flag_strategy_recalc, note_own_strategy_milestone

                prev_id = info.get("previous_holder_id")
                new_id = info.get("holder_id")
                current = self.get_current_player()
                try:
                    cur_id = int(getattr(current, "id", 0) or 0) or None if current else None
                except Exception:
                    cur_id = None
                for p in list(getattr(self, "players", []) or []):
                    try:
                        pid = int(getattr(p, "id", 0) or 0) or None
                    except Exception:
                        pid = None
                    if pid is None:
                        continue
                    if new_id is not None and pid == new_id:
                        if cur_id is not None and pid == cur_id:
                            note_own_strategy_milestone(
                                self,
                                p,
                                "own_largest_army",
                                detail={"reason": reason},
                            )
                        else:
                            flag_strategy_recalc(p, "own_largest_army")
                        # WP2: sticky way must account for held LA
                        try:
                            from core.strategy_board_fit import (
                                maybe_force_board_fit_after_specials,
                            )

                            maybe_force_board_fit_after_specials(
                                self, p, reason="own_largest_army"
                            )
                        except Exception:
                            pass
                        try:
                            from core.sidestep_s142_drive import (
                                latch_own_public_milestone,
                            )

                            latch_own_public_milestone(self, p, kind="la")
                        except Exception:
                            pass
                    elif prev_id is not None and pid == prev_id and pid != new_id:
                        flag_strategy_recalc(p, "lost_largest_army", detail={"reason": reason})
            except Exception:
                pass

        try:
            self.last_la_recompute_result = dict(info)
        except Exception:
            pass

        return info

    def recompute_longest_road(
        self,
        *,
        reason: str = "",
        emit_events: bool = True,
        refresh_scoreboard: bool = True,
        actor: Any = None,
        force_full: bool = False,
    ) -> Dict[str, Any]:
        """Recompute continuous road lengths and Longest Road award (≥5).

        Uses ``core.longest_road`` (PR2 engine). Rules:
          - Continuous road of ≥5 segments required to claim.
          - Exact length ties: current holder keeps the special.
          - If nobody has ≥5, special is vacant.
          - Opponent settlements/cities break continuity (engine).

        WP6 (``LR_RECOMPUTE_OPT``):
          - ``full`` (default): every seat DFS.
          - ``threshold``: settlement → full; road/TFR → actor only; city → cache.
            Pass ``actor=`` on road/TFR hooks. ``force_full=True`` always full.

        Updates each player's ``size_longest_route``, ``structure_longest_route``,
        ``longest_route_tf``, ``game.longest_road_player``, and VP for flag changes.
        """
        info: Dict[str, Any] = {
            "ok": True,
            "reason": str(reason or "recompute_longest_road"),
            "threshold": 5,
            "best_length": 0,
            "previous_holder_id": None,
            "holder_id": None,
            "holder_changed": False,
            "gained_longest_road": False,
            "lost_longest_road": False,
            "cleared": False,
            "lengths": {},
            "previous_lengths": {},
            "length_changes": {},
            "recompute_scope": "full",
            "recompute_scope_why": "default_full",
            "recompute_opt_mode": "full",
        }

        players = [p for p in list(getattr(self, "players", []) or []) if p is not None]
        previous = getattr(self, "longest_road_player", None)
        try:
            if previous is not None:
                info["previous_holder_id"] = int(getattr(previous, "id", 0) or 0) or None
        except Exception:
            info["previous_holder_id"] = None

        def _same_player(a: Any, b: Any) -> bool:
            if a is None or b is None:
                return False
            if a is b:
                return True
            try:
                return int(getattr(a, "id", 0) or 0) == int(getattr(b, "id", 0) or 0) and int(
                    getattr(a, "id", 0) or 0
                ) > 0
            except Exception:
                return False

        def _pid_of(p: Any) -> int:
            try:
                return int(getattr(p, "id", 0) or 0)
            except Exception:
                return 0

        # Snapshot lengths before recompute (hardening / debug)
        prev_lengths: Dict[int, int] = {}
        for p in players:
            try:
                pid = _pid_of(p)
                if pid > 0:
                    prev_lengths[pid] = max(0, int(getattr(p, "size_longest_route", 0) or 0))
            except Exception:
                pass
        info["previous_lengths"] = dict(prev_lengths)

        # WP6 scope decision
        scope = "full"
        scope_why = "default_full"
        try:
            from core.lr_recompute_opt import classify_lr_recompute_scope

            decision = classify_lr_recompute_scope(
                self,
                reason=str(reason or ""),
                actor=actor,
                force_full=bool(force_full),
            )
            scope = str(decision.get("scope") or "full")
            scope_why = str(decision.get("why") or "")
            info["recompute_scope"] = scope
            info["recompute_scope_why"] = scope_why
            info["recompute_opt_mode"] = str(decision.get("mode") or "full")
        except Exception:
            scope = "full"
            scope_why = "classify_failed_full"

        lengths_by_player: List[Tuple[Any, int, List]] = []
        best = 0
        computed: Dict[Any, Any] = {}

        if scope == "cache_only":
            # Reuse cached continuous lengths (city upgrade: graphs unchanged)
            for p in players:
                pid = _pid_of(p)
                try:
                    length = max(0, int(getattr(p, "size_longest_route", 0) or 0))
                except Exception:
                    length = 0
                try:
                    path = list(getattr(p, "structure_longest_route", []) or [])
                except Exception:
                    path = []
                lengths_by_player.append((p, length, path))
                if pid > 0:
                    info["lengths"][pid] = length
                if length > best:
                    best = length
            info["best_length"] = int(best)
        else:
            try:
                from core.longest_road import (
                    compute_longest_road_for_player,
                    compute_longest_road_lengths,
                )

                if scope == "actor_only" and actor is not None:
                    # Only actor graph changed (road/TFR). Opponents reuse cache.
                    actor_res = compute_longest_road_for_player(self, actor)
                    actor_pid = _pid_of(actor)
                    for p in players:
                        pid = _pid_of(p)
                        if _same_player(p, actor) or (actor_pid > 0 and pid == actor_pid):
                            length = max(0, int(getattr(actor_res, "length", 0) or 0))
                            path = list(getattr(actor_res, "path_edges", []) or [])
                            try:
                                p.size_longest_route = length
                                p.structure_longest_route = [list(e) for e in path]
                            except Exception:
                                pass
                        else:
                            try:
                                length = max(
                                    0, int(getattr(p, "size_longest_route", 0) or 0)
                                )
                            except Exception:
                                length = 0
                            try:
                                path = list(
                                    getattr(p, "structure_longest_route", []) or []
                                )
                            except Exception:
                                path = []
                        lengths_by_player.append((p, length, path))
                        if pid > 0:
                            info["lengths"][pid] = length
                            old_len = int(prev_lengths.get(pid, length))
                            if old_len != length:
                                info["length_changes"][pid] = {
                                    "from": old_len,
                                    "to": length,
                                }
                        if length > best:
                            best = length
                    info["best_length"] = int(best)
                else:
                    # full (default)
                    if scope != "full":
                        # actor missing under actor_only → fall through to full
                        info["recompute_scope"] = "full"
                        info["recompute_scope_why"] = scope_why + "+fallback_full"
                    computed = compute_longest_road_lengths(self)
                    for p in players:
                        pid = _pid_of(p)
                        res = computed.get(pid) if computed else None
                        length = 0
                        path: List = []
                        if res is not None:
                            try:
                                length = max(0, int(getattr(res, "length", 0) or 0))
                                path = list(getattr(res, "path_edges", []) or [])
                            except Exception:
                                length, path = 0, []
                        try:
                            p.size_longest_route = length
                            p.structure_longest_route = [list(e) for e in path]
                        except Exception:
                            pass
                        lengths_by_player.append((p, length, path))
                        if pid > 0:
                            info["lengths"][pid] = length
                            old_len = int(prev_lengths.get(pid, length))
                            if old_len != length:
                                info["length_changes"][pid] = {
                                    "from": old_len,
                                    "to": length,
                                }
                        if length > best:
                            best = length
                    info["best_length"] = int(best)
            except Exception as exc:
                info["ok"] = False
                info["error"] = str(exc)
                computed = {}
                # Fall back to empty lengths if engine failed mid-path
                if not lengths_by_player:
                    for p in players:
                        pid = _pid_of(p)
                        lengths_by_player.append((p, 0, []))
                        if pid > 0:
                            info["lengths"][pid] = 0
                    info["best_length"] = 0

        new_holder: Optional[Player] = None
        if best >= 5:
            candidates = [p for p, n, _ in lengths_by_player if n == best]
            if previous is not None and any(_same_player(previous, c) for c in candidates):
                new_holder = next((c for c in candidates if _same_player(previous, c)), previous)
            elif len(candidates) == 1:
                new_holder = candidates[0]
            elif candidates:

                def _pid(pl: Any) -> int:
                    try:
                        return int(getattr(pl, "id", 0) or 0)
                    except Exception:
                        return 0

                candidates.sort(key=_pid)
                new_holder = candidates[0]
        else:
            info["cleared"] = True
            new_holder = None

        changed_players: List[Any] = []
        for p in players:
            should_hold = new_holder is not None and _same_player(p, new_holder)
            try:
                had = bool(getattr(p, "longest_route_tf", False))
            except Exception:
                had = False
            if had != should_hold:
                try:
                    p.longest_route_tf = should_hold
                except Exception:
                    pass
                changed_players.append(p)

        try:
            self.longest_road_player = new_holder
        except Exception:
            pass

        for p in changed_players:
            try:
                p.recalculate_victory_points()
            except Exception:
                pass

        try:
            if new_holder is not None:
                info["holder_id"] = int(getattr(new_holder, "id", 0) or 0) or None
        except Exception:
            info["holder_id"] = None

        prev_id = info.get("previous_holder_id")
        new_id = info.get("holder_id")
        info["holder_changed"] = prev_id != new_id
        info["gained_longest_road"] = bool(new_id is not None and new_id != prev_id)
        info["lost_longest_road"] = bool(prev_id is not None and prev_id != new_id)

        # Phase L: sample on LR holder change
        if info.get("holder_changed"):
            try:
                from core.la_lr_probe_log import maybe_log_la_lr_probe

                focal = new_holder if new_holder is not None else self._player_by_id(prev_id)
                maybe_log_la_lr_probe(
                    self,
                    focal,
                    reason=str(reason or "recompute_longest_road"),
                    event="lr_holder_changed",
                    force=True,
                )
            except Exception:
                pass

        if emit_events and info["holder_changed"]:
            try:
                if new_holder is not None and prev_id is None:
                    self.emit_twitter_event(
                        new_id,
                        f"takes Longest Road ({best})",
                    )
                elif new_holder is not None and prev_id is not None:
                    self.emit_twitter_event(
                        new_id,
                        f"steals Longest Road ({best})",
                    )
                    self.emit_twitter_event(
                        prev_id,
                        "loses Longest Road",
                    )
                elif new_holder is None and prev_id is not None:
                    self.emit_twitter_event(
                        prev_id,
                        "Longest Road special is vacant",
                    )
            except Exception:
                pass

        # MGlog: LR holder flip (independent of twitter / emit_events noise)
        if info.get("holder_changed"):
            try:
                from core import mglog

                mglog.log_longest_road_change(
                    self,
                    previous_holder_id=prev_id,
                    holder_id=new_id,
                    best_length=best,
                    reason=str(reason or "recompute_longest_road"),
                )
            except Exception:
                pass

        # DBG: length deltas (execution debug / optional twitter)
        length_changes = info.get("length_changes") or {}
        if length_changes:
            try:
                if bool(getattr(self, "execution_debug_print_tf", False)):
                    parts = [
                        f"P{pid}:{ch.get('from')}→{ch.get('to')}"
                        for pid, ch in sorted(length_changes.items())
                    ]
                    print(
                        f"DBG recompute_longest_road [{info.get('reason')}] "
                        f"best={best} holder={new_id} lengths {', '.join(parts)}"
                    )
            except Exception:
                pass
            if emit_events and bool(getattr(self, "execution_debug_print_tf", False)):
                try:
                    # Quiet DBG line in event feed only when debug is on
                    self.emit_twitter_event(
                        None,
                        f"DBG LR lengths {info.get('reason')}: "
                        + ", ".join(
                            f"P{pid} {ch.get('from')}→{ch.get('to')}"
                            for pid, ch in sorted(length_changes.items())
                        ),
                    )
                except Exception:
                    pass

        if refresh_scoreboard and (
            info["holder_changed"]
            or bool(changed_players)
            or bool(length_changes)
            or str(reason or "")
        ):
            try:
                self._refresh_gui_scoreboard_after_dcard_change(
                    str(reason or "after_recompute_longest_road")
                )
            except Exception:
                pass

        # S1: acquiring LR → own milestone; loser flagged (batched re-rank)
        if info.get("holder_changed"):
            try:
                from core.strategy_sticky import flag_strategy_recalc, note_own_strategy_milestone

                prev_id = info.get("previous_holder_id")
                new_id = info.get("holder_id")
                current = self.get_current_player()
                try:
                    cur_id = int(getattr(current, "id", 0) or 0) or None if current else None
                except Exception:
                    cur_id = None
                for p in list(getattr(self, "players", []) or []):
                    try:
                        pid = int(getattr(p, "id", 0) or 0) or None
                    except Exception:
                        pid = None
                    if pid is None:
                        continue
                    if new_id is not None and pid == new_id:
                        if cur_id is not None and pid == cur_id:
                            note_own_strategy_milestone(
                                self,
                                p,
                                "own_longest_road",
                                detail={"reason": reason},
                            )
                        else:
                            flag_strategy_recalc(p, "own_longest_road")
                        # WP2: sticky way must account for held LR
                        try:
                            from core.strategy_board_fit import (
                                maybe_force_board_fit_after_specials,
                            )

                            maybe_force_board_fit_after_specials(
                                self, p, reason="own_longest_road"
                            )
                        except Exception:
                            pass
                        try:
                            from core.sidestep_s142_drive import (
                                latch_own_public_milestone,
                            )

                            latch_own_public_milestone(self, p, kind="lr")
                        except Exception:
                            pass
                    elif prev_id is not None and pid == prev_id and pid != new_id:
                        flag_strategy_recalc(p, "lost_longest_road", detail={"reason": reason})
            except Exception:
                pass

        try:
            self.last_lr_recompute_result = dict(info)
        except Exception:
            pass

        return info

    def recompute_special_awards(
        self,
        *,
        reason: str = "",
        emit_events: bool = True,
        refresh_scoreboard: bool = True,
        include_largest_army: bool = False,
    ) -> Dict[str, Any]:
        """Recompute board specials after a rules mutation.

        Default: Longest Road (roads/settlements change). Optionally also
        Largest Army (e.g. after load). Scoreboard refreshes once at the end.
        """
        out: Dict[str, Any] = {
            "ok": True,
            "reason": str(reason or "recompute_special_awards"),
            "longest_road": None,
            "largest_army": None,
        }
        lr = self.recompute_longest_road(
            reason=reason or "recompute_special_awards",
            emit_events=emit_events,
            refresh_scoreboard=False,
            force_full=True,  # WP6: bulk awards always full multi-seat DFS
        )
        out["longest_road"] = lr
        if include_largest_army:
            la = self.recompute_largest_army(
                reason=reason or "recompute_special_awards",
                emit_events=emit_events,
            )
            out["largest_army"] = la
            # Keep LA scoreboard column in sync after load / full recompute
            if refresh_scoreboard is False and bool((la or {}).get("holder_changed")):
                pass
        if refresh_scoreboard:
            try:
                self._refresh_gui_scoreboard_after_dcard_change(
                    str(reason or "after_recompute_special_awards")
                )
            except Exception:
                pass
        try:
            self.last_specials_recompute_result = dict(out)
        except Exception:
            pass
        return out

    def _update_largest_army_after_knight(self, player: Player) -> Dict[str, Any]:
        """Increment played-knight count, then recompute Largest Army award.

        Award / steal / VP / events live in ``recompute_largest_army`` so knight
        play cannot drift from load-game or other recompute entry points.
        """
        info: Dict[str, Any] = {
            "army_size": 0,
            "gained_largest_army": False,
            "holder_changed": False,
        }
        if player is None:
            return info
        try:
            player.size_largest_army = int(getattr(player, "size_largest_army", 0) or 0) + 1
        except Exception:
            player.size_largest_army = 1
        info["army_size"] = int(player.size_largest_army)

        recompute = self.recompute_largest_army(
            reason="after_knight",
            emit_events=True,
        )
        info.update(
            {
                "gained_largest_army": bool(recompute.get("gained_largest_army")),
                "holder_changed": bool(recompute.get("holder_changed")),
                "holder_id": recompute.get("holder_id"),
                "previous_holder_id": recompute.get("previous_holder_id"),
                "best_size": recompute.get("best_size"),
                "recompute": recompute,
            }
        )
        # S1 ext: LA-pursuing opponents batch-flag even when holder did not flip
        try:
            from core.strategy_sticky import flag_opponents_after_knight

            info["strategy_recalc_flagged_opponents"] = flag_opponents_after_knight(
                self,
                player,
                army_size=info.get("army_size"),
            )
        except Exception:
            info["strategy_recalc_flagged_opponents"] = {}
        # Keep acting player's VP field in sync even if they did not take/lose LA.
        try:
            player.recalculate_victory_points()
        except Exception:
            pass
        # W2: knight can award Largest Army (+2 VP) and end the game.
        try:
            info["win_check"] = self._maybe_declare_winner_after(
                "after_knight_largest_army",
                player,
            )
        except Exception:
            info["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        # Phase L: sample on LA holder change
        try:
            if info.get("holder_changed"):
                from core.la_lr_probe_log import maybe_log_la_lr_probe

                maybe_log_la_lr_probe(
                    self,
                    player,
                    reason="after_knight_la",
                    event="la_holder_changed",
                    force=True,
                )
        except Exception:
            pass
        return info

    def execute_human_play_knight_action(self) -> Dict[str, Any]:
        """Play a Knight (human): consume card and start the robber/steal flow.

        Two legal timings (standard Catan):

        a) **Before dice** (``AwaitingDiceRoll``): after robber/steal, resume to
           ``AwaitingDiceRoll`` so only Roll Dices remains.
        b) **After dice** (``ActionSelection``, including after a resolved 7):
           after robber/steal, resume to ``ActionSelection`` for buy/trade/end.

        Not allowed mid-robber/discard, or if a DCard was already played this turn.
        """
        result: Dict[str, Any] = {
            "ok": False,
            "action": "Play Knight",
            "reason": "",
        }
        if bool(getattr(self, "game_over", False)):
            result["reason"] = "game_over"
            return result
        if str(getattr(self, "phase", "") or "") != "Execution":
            result["reason"] = "not_execution_phase"
            return result

        player = self.get_current_player()
        if player is None or not bool(getattr(player, "is_human", False)):
            result["reason"] = "not_human_current_player"
            return result

        dice_roll = getattr(self, "dice_roll", None)
        state = str(getattr(self, "state", "") or "")
        dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"

        if state in {
            "MoveRobber",
            "RobberMoveRequired",
            "SetRobber",
            "StealSelectOpponent",
            "StealPickRCard",
            "DiscardPending",
        }:
            result["reason"] = "robber_flow_already_active"
            return result

        # (a) pre-roll or (b) post-roll ActionSelection
        if dice_not_rolled:
            timing = "before_roll"
            resume_state = "AwaitingDiceRoll"
        else:
            if state != "ActionSelection":
                result["reason"] = "knight_after_roll_requires_action_selection"
                return result
            timing = "after_roll"
            resume_state = "ActionSelection"

        try:
            td = getattr(self, "myturn", None) or getattr(self, "turn_details", None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                result["reason"] = "already_played_dcard_this_turn"
                return result
        except Exception:
            pass

        self._ensure_player_dcard_state(player)
        if "knight" not in [str(c) for c in (getattr(player, "development_cards", []) or [])]:
            # Allow summary-only bookkeeping if list empty but playable count exists
            try:
                from gui.gui_play_dcard_panel import playable_count_for_type

                if playable_count_for_type(player, "knight") <= 0:
                    result["reason"] = "no_knight_in_hand"
                    return result
            except Exception:
                result["reason"] = "no_knight_in_hand"
                return result

        if not self._remove_development_card_from_player(player, "knight"):
            # Force-remove via summary if list had no knight but playable col2 did
            try:
                idx = self._execution_dcard_summary_index("knight")
                row = player.dcard_summary[idx]
                if int(row[2] or 0) <= 0:
                    result["reason"] = "no_knight_in_hand"
                    return result
                row[2] = int(row[2]) - 1
                row[3] = int(row[3] or 0) + 1
            except Exception:
                result["reason"] = "could_not_consume_knight"
                return result

        self._mark_dcard_played_this_turn("knight", player)
        army_info = self._update_largest_army_after_knight(player)

        try:
            self.emit_twitter_event(getattr(player, "id", None), f"plays Knight ({timing})")
        except Exception:
            pass
        try:
            self.record_turn_event(
                player=player,
                event_type="play_dcard",
                source="human_play_knight",
                message=f"plays Knight ({timing})",
                metadata={
                    "card": "knight",
                    "timing": timing,
                    "army_size": army_info.get("army_size"),
                },
            )
        except Exception:
            pass
        try:
            from core import mglog

            mglog.log_play_dcard(
                self,
                player,
                "knight",
                payload=f"timing={timing}",
            )
        except Exception:
            pass

        # W2: LA award can end the game; skip robber flow if so.
        if bool(getattr(self, "game_over", False)):
            result.update(
                {
                    "ok": True,
                    "reason": "executed_and_won",
                    "timing": timing,
                    "army_info": army_info,
                    "win_check": army_info.get("win_check"),
                    "game_over": True,
                    "robber_skipped": True,
                }
            )
            self.last_execution_result = result
            return result

        # Start robber flow (no discards — knight is not a 7)
        from core.game_7logic import (
            current_robber_tile_id,
            legal_robber_tile_ids,
        )

        robber_before = current_robber_tile_id(self)
        legal_tiles = legal_robber_tile_ids(self)
        self.pending_knight_play = {
            "active": True,
            "player_id": getattr(player, "id", None),
            "timing": timing,
            "resume_state": resume_state,
            "robber_tile_before": robber_before,
            "legal_robber_tile_ids": list(legal_tiles),
        }
        # Reuse seven-roll visual flags without discard queue
        self.pending_seven_roll = {
            "active": True,
            "source": "knight",
            "timing": timing,
            "player_id": getattr(player, "id", None),
            "discard_required_later": False,
            "players_to_discard": [],
            "robber_tile_before": robber_before,
            "legal_robber_tile_ids": list(legal_tiles),
        }
        self.pending_discard_queue = []
        try:
            self.state = "MoveRobber"
            self.state_1 = "MoveRobber"
            self.state_2 = ""
            self.myturn.validate_function_set_robber_by_HP = True
            self.myturn.validate_function_discard_rcards_by_HP = False
        except Exception:
            pass

        try:
            from core.game_7logic import _show_available_robber_tiles_visual, _show_robber_tile_visual

            _show_robber_tile_visual(self, robber_before)
            _show_available_robber_tiles_visual(self, legal_tiles)
        except Exception:
            pass

        try:
            self.emit_twitter_event(getattr(player, "id", None), "must move robber (Knight)")
        except Exception:
            pass

        self._refresh_gui_scoreboard_after_dcard_change("after_play_knight")
        try:
            self.refresh_viable_actions("after_human_play_knight")
        except Exception:
            pass

        result.update(
            {
                "ok": True,
                "reason": "knight_played_robber_pending",
                "timing": timing,
                "resume_state": resume_state,
                "army": army_info,
                "state_after": str(getattr(self, "state", "")),
                "legal_robber_tile_ids": list(legal_tiles),
            }
        )
        self.last_execution_result = dict(result)
        return result

    def execute_human_play_yop_action(
        self,
        resource_index_a: int,
        resource_index_b: int,
    ) -> Dict[str, Any]:
        """Play Year of Plenty: take two resource cards (from the bank).

        Standard timing: after dice, during ActionSelection. Consumes the YOP
        card, marks DCard played this turn (blocks a second DCard), adds both
        resources to the hand, updates scoreboard / twitter / turn ledger.
        """
        result: Dict[str, Any] = {
            "ok": False,
            "action": "Play Year of Plenty",
            "reason": "",
        }
        if str(getattr(self, "phase", "") or "") != "Execution":
            result["reason"] = "not_execution_phase"
            return result

        player = self.get_current_player()
        if player is None or not bool(getattr(player, "is_human", False)):
            result["reason"] = "not_human_current_player"
            return result

        state = str(getattr(self, "state", "") or "")
        dice_roll = getattr(self, "dice_roll", None)
        dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"
        if dice_not_rolled:
            result["reason"] = "yop_requires_dice_already_rolled"
            return result
        if state != "ActionSelection":
            result["reason"] = "yop_requires_action_selection"
            return result

        try:
            a = int(resource_index_a)
            b = int(resource_index_b)
        except Exception:
            result["reason"] = "invalid_resource_indices"
            return result
        if not (0 <= a < 5 and 0 <= b < 5):
            result["reason"] = "resource_index_out_of_range"
            return result

        try:
            td = getattr(self, "myturn", None) or getattr(self, "turn_details", None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                result["reason"] = "already_played_dcard_this_turn"
                return result
        except Exception:
            pass

        self._ensure_player_dcard_state(player)
        has_yop = "year_of_plenty" in [str(c) for c in (getattr(player, "development_cards", []) or [])]
        if not has_yop:
            try:
                from gui.gui_play_dcard_panel import playable_count_for_type

                if playable_count_for_type(player, "year_of_plenty") <= 0:
                    result["reason"] = "no_yop_in_hand"
                    return result
            except Exception:
                result["reason"] = "no_yop_in_hand"
                return result

        if not self._remove_development_card_from_player(player, "year_of_plenty"):
            try:
                idx = self._execution_dcard_summary_index("year_of_plenty")
                row = player.dcard_summary[idx]
                if int(row[2] or 0) <= 0:
                    result["reason"] = "no_yop_in_hand"
                    return result
                row[2] = int(row[2]) - 1
                row[3] = int(row[3] or 0) + 1
            except Exception:
                result["reason"] = "could_not_consume_yop"
                return result

        self._mark_dcard_played_this_turn("year_of_plenty", player)

        resources = self._execution_resource_order()
        names = [self._resource_name_for_turn_delta(r) for r in resources[:5]]
        gain_vec = [0, 0, 0, 0, 0]
        gain_vec[a] += 1
        gain_vec[b] += 1

        # Add resources to hand (bank is unlimited for YOP in this ruleset)
        try:
            if not isinstance(getattr(player, "rcards", None), dict):
                player.rcards = {}
            for idx in range(5):
                amount = int(gain_vec[idx] or 0)
                if amount <= 0:
                    continue
                resource = resources[idx]
                player.rcards[resource] = int(player.rcards.get(resource, 0) or 0) + amount
            player.number_of_rcards = sum(int(player.rcards.get(rc, 0) or 0) for rc in ResourceCard)
        except Exception as exc:
            result["reason"] = f"could_not_add_resources:{exc}"
            return result

        delta: Dict[str, int] = {}
        for idx, name in enumerate(names):
            if gain_vec[idx]:
                delta[name] = int(gain_vec[idx])

        pick_text = f"{names[a]} + {names[b]}" if a != b else f"2× {names[a]}"
        message = f"plays Year of Plenty → {pick_text}"

        try:
            self.record_turn_delta(
                player,
                "dcard",
                resource_delta=delta,
                event_type="play_dcard",
                source="human_play_yop",
                reason="year_of_plenty",
                message=message,
                metadata={
                    "card": "year_of_plenty",
                    "resource_indices": [a, b],
                    "resource_names": [names[a], names[b]],
                    "gain_vector": list(gain_vec),
                },
            )
        except Exception:
            try:
                self.record_turn_event(
                    player=player,
                    event_type="play_dcard",
                    source="human_play_yop",
                    message=message,
                    metadata={"card": "year_of_plenty", "resource_indices": [a, b]},
                )
            except Exception:
                pass

        try:
            from core import mglog

            mglog.log_play_dcard(
                self,
                player,
                "year_of_plenty",
                resource_indices=[a, b],
                rc_in=list(gain_vec),
            )
        except Exception:
            pass

        try:
            self.emit_twitter_event(getattr(player, "id", None), message)
        except Exception:
            pass

        try:
            self._play_execution_action_sound("Play development_card")
        except Exception:
            pass

        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass

        self._refresh_gui_scoreboard_after_dcard_change("after_play_yop")
        try:
            self.refresh_strategy_after_event("after_human_play_yop", kind="hand")
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_human_play_yop")
        except Exception:
            pass

        result.update(
            {
                "ok": True,
                "reason": "executed",
                "resource_indices": [a, b],
                "resource_names": [names[a], names[b]],
                "gain_vector": list(gain_vec),
                "resource_delta": delta,
                "message": message,
                "hand_total": int(getattr(player, "number_of_rcards", 0) or 0),
                "state_after": str(getattr(self, "state", "")),
            }
        )
        self.last_execution_result = dict(result)
        print(message)
        return result

    def execute_human_play_monopoly_action(self, resource_index: int) -> Dict[str, Any]:
        """Play Monopoly: take all cards of one resource type from every opponent.

        Timing: after dice, ActionSelection. Consumes Monopoly, marks DCard
        played this turn, moves all matching RCards from each opponent to the
        active human, updates scoreboard / twitter / turn ledger.
        """
        result: Dict[str, Any] = {
            "ok": False,
            "action": "Play Monopoly",
            "reason": "",
        }
        if str(getattr(self, "phase", "") or "") != "Execution":
            result["reason"] = "not_execution_phase"
            return result

        player = self.get_current_player()
        if player is None or not bool(getattr(player, "is_human", False)):
            result["reason"] = "not_human_current_player"
            return result

        state = str(getattr(self, "state", "") or "")
        dice_roll = getattr(self, "dice_roll", None)
        dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"
        if dice_not_rolled:
            result["reason"] = "monopoly_requires_dice_already_rolled"
            return result
        if state != "ActionSelection":
            result["reason"] = "monopoly_requires_action_selection"
            return result

        try:
            ridx = int(resource_index)
        except Exception:
            result["reason"] = "invalid_resource_index"
            return result
        if not (0 <= ridx < 5):
            result["reason"] = "resource_index_out_of_range"
            return result

        try:
            td = getattr(self, "myturn", None) or getattr(self, "turn_details", None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                result["reason"] = "already_played_dcard_this_turn"
                return result
        except Exception:
            pass

        self._ensure_player_dcard_state(player)
        has_mono = "monopoly" in [str(c) for c in (getattr(player, "development_cards", []) or [])]
        if not has_mono:
            try:
                from gui.gui_play_dcard_panel import playable_count_for_type

                if playable_count_for_type(player, "monopoly") <= 0:
                    result["reason"] = "no_monopoly_in_hand"
                    return result
            except Exception:
                result["reason"] = "no_monopoly_in_hand"
                return result

        if not self._remove_development_card_from_player(player, "monopoly"):
            try:
                idx = self._execution_dcard_summary_index("monopoly")
                row = player.dcard_summary[idx]
                if int(row[2] or 0) <= 0:
                    result["reason"] = "no_monopoly_in_hand"
                    return result
                row[2] = int(row[2]) - 1
                row[3] = int(row[3] or 0) + 1
            except Exception:
                result["reason"] = "could_not_consume_monopoly"
                return result

        self._mark_dcard_played_this_turn("monopoly", player)

        resources = self._execution_resource_order()
        resource = resources[ridx]
        res_name = self._resource_name_for_turn_delta(resource)
        total_taken = 0
        taken_by_opponent: List[Dict[str, Any]] = []

        try:
            if not isinstance(getattr(player, "rcards", None), dict):
                player.rcards = {}
        except Exception:
            player.rcards = {}

        active_id = int(getattr(player, "id", 0) or 0)
        for opponent in list(getattr(self, "players", []) or []):
            if opponent is None:
                continue
            try:
                oid = int(getattr(opponent, "id", -1) or -1)
            except Exception:
                oid = -1
            if oid == active_id:
                continue

            # Count cards of this type (ResourceCard key or string name)
            amount = 0
            try:
                rcards = getattr(opponent, "rcards", None) or {}
                if not isinstance(rcards, dict):
                    rcards = {}
                amount = int(rcards.get(resource, 0) or 0)
                if amount <= 0:
                    # Fallback string keys
                    for key, val in list(rcards.items()):
                        kn = getattr(key, "value", str(key))
                        if str(kn).lower() == str(res_name).lower():
                            amount = int(val or 0)
                            resource_key = key
                            break
                    else:
                        resource_key = resource
                        amount = 0
                else:
                    resource_key = resource
            except Exception:
                amount = 0
                resource_key = resource

            if amount <= 0:
                continue

            try:
                opponent.rcards[resource_key] = 0
                # Also zero the enum/string twin if both exist
                if resource_key is not resource:
                    try:
                        opponent.rcards[resource] = 0
                    except Exception:
                        pass
                opponent.number_of_rcards = sum(
                    int(opponent.rcards.get(rc, 0) or 0) for rc in ResourceCard
                )
                if opponent.number_of_rcards == 0:
                    # Fallback recount for non-enum keys
                    try:
                        opponent.number_of_rcards = sum(
                            max(0, int(v or 0)) for v in (opponent.rcards or {}).values()
                        )
                    except Exception:
                        pass
            except Exception as exc:
                result["reason"] = f"could_not_take_from_p{oid}:{exc}"
                return result

            try:
                player.rcards[resource] = int(player.rcards.get(resource, 0) or 0) + amount
            except Exception as exc:
                result["reason"] = f"could_not_give_to_player:{exc}"
                return result

            total_taken += amount
            taken_by_opponent.append({"opponent_id": oid, "amount": amount})

            # Per-opponent loss on their turn delta / events
            try:
                self.record_turn_delta(
                    opponent,
                    "dcard",
                    resource_delta={res_name: -amount},
                    event_type="monopoly_loss",
                    target_player_id=active_id,
                    source="human_play_monopoly",
                    reason="monopoly",
                    message=f"loses {amount} {res_name} to Monopoly",
                    metadata={"thief_id": active_id, "resource": res_name, "amount": amount},
                )
            except Exception:
                try:
                    self.record_turn_event(
                        player=opponent,
                        event_type="monopoly_loss",
                        target_player_id=active_id,
                        source="human_play_monopoly",
                        message=f"loses {amount} {res_name} to Monopoly",
                        metadata={"amount": amount, "resource": res_name},
                    )
                except Exception:
                    pass

            try:
                self.emit_twitter_event(oid, f"gives {amount} {res_name} (Monopoly)")
            except Exception:
                pass
            try:
                self.update_strategy_dashboard(opponent)
            except Exception:
                pass

        try:
            player.number_of_rcards = sum(int(player.rcards.get(rc, 0) or 0) for rc in ResourceCard)
        except Exception:
            pass

        delta = {res_name: total_taken} if total_taken else {}
        if total_taken > 0:
            message = f"plays Monopoly on {res_name} → takes {total_taken}"
        else:
            message = f"plays Monopoly on {res_name} → takes 0 (none held)"

        try:
            self.record_turn_delta(
                player,
                "dcard",
                resource_delta=delta if delta else None,
                event_type="play_dcard",
                source="human_play_monopoly",
                reason="monopoly",
                message=message,
                metadata={
                    "card": "monopoly",
                    "resource_index": ridx,
                    "resource_name": res_name,
                    "total_taken": total_taken,
                    "taken_by_opponent": list(taken_by_opponent),
                },
            )
        except Exception:
            try:
                self.record_turn_event(
                    player=player,
                    event_type="play_dcard",
                    source="human_play_monopoly",
                    message=message,
                    metadata={
                        "card": "monopoly",
                        "resource_name": res_name,
                        "total_taken": total_taken,
                    },
                )
            except Exception:
                pass

        try:
            self.emit_twitter_event(getattr(player, "id", None), message)
        except Exception:
            pass

        try:
            from core import mglog

            mono_rc_in = [0, 0, 0, 0, 0]
            if total_taken > 0 and 0 <= ridx < 5:
                mono_rc_in[ridx] = int(total_taken)
            mglog.log_play_dcard(
                self,
                player,
                "monopoly",
                resource_index=ridx,
                resource_name=res_name,
                total_taken=total_taken,
                rc_in=mono_rc_in,
            )
        except Exception:
            pass

        try:
            self._play_execution_action_sound("Play development_card")
        except Exception:
            pass

        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass

        self._refresh_gui_scoreboard_after_dcard_change("after_play_monopoly")
        try:
            self.refresh_strategy_after_event("after_human_play_monopoly", kind="hand")
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_human_play_monopoly")
        except Exception:
            pass

        result.update(
            {
                "ok": True,
                "reason": "executed",
                "resource_index": ridx,
                "resource_name": res_name,
                "total_taken": total_taken,
                "taken_by_opponent": list(taken_by_opponent),
                "resource_delta": delta,
                "message": message,
                "hand_total": int(getattr(player, "number_of_rcards", 0) or 0),
                "state_after": str(getattr(self, "state", "")),
            }
        )
        self.last_execution_result = dict(result)
        print(message)
        return result

    # Official Catan: each player has 15 road, 5 settlement, and 4 city pieces.
    MAX_PLAYER_ROADS: int = 15
    MAX_PLAYER_SETTLEMENTS: int = 5
    MAX_PLAYER_CITIES: int = 4

    def player_roads_remaining(self, player: Optional[Player] = None) -> int:
        """How many unused road pieces the player still has (0..15)."""
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None
        if player is None:
            return 0
        try:
            placed = len(list(getattr(player, "roads", []) or []))
        except Exception:
            placed = 0
        return max(0, int(self.MAX_PLAYER_ROADS) - int(placed))

    def player_settlements_remaining(self, player: Optional[Player] = None) -> int:
        """Unused settlement pieces (0..5). Cities free a settlement piece on upgrade."""
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None
        if player is None:
            return 0
        try:
            placed = len(list(getattr(player, "settlements", []) or []))
        except Exception:
            placed = 0
        return max(0, int(self.MAX_PLAYER_SETTLEMENTS) - int(placed))

    def player_cities_remaining(self, player: Optional[Player] = None) -> int:
        """Unused city pieces (0..4)."""
        if player is None:
            try:
                player = self.get_current_player()
            except Exception:
                player = None
        if player is None:
            return 0
        try:
            placed = len(list(getattr(player, "cities", []) or []))
        except Exception:
            placed = 0
        return max(0, int(self.MAX_PLAYER_CITIES) - int(placed))

    def execute_human_play_tfr_action(self) -> Dict[str, Any]:
        """Play Two Free Roads: consume card and start free road placement (1 or 2).

        Number of free roads = min(2, road pieces still available).  If the
        player has 0 pieces left, the play is rejected (GUI should not offer it).
        """
        result: Dict[str, Any] = {
            "ok": False,
            "action": "Play Two Free Roads",
            "reason": "",
        }
        if str(getattr(self, "phase", "") or "") != "Execution":
            result["reason"] = "not_execution_phase"
            return result

        player = self.get_current_player()
        if player is None or not bool(getattr(player, "is_human", False)):
            result["reason"] = "not_human_current_player"
            return result

        state = str(getattr(self, "state", "") or "")
        dice_roll = getattr(self, "dice_roll", None)
        dice_not_rolled = dice_roll in (None, 0, "", []) or state == "AwaitingDiceRoll"
        if dice_not_rolled:
            result["reason"] = "tfr_requires_dice_already_rolled"
            return result
        if state != "ActionSelection":
            result["reason"] = "tfr_requires_action_selection"
            return result

        try:
            td = getattr(self, "myturn", None) or getattr(self, "turn_details", None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                result["reason"] = "already_played_dcard_this_turn"
                return result
        except Exception:
            pass

        pieces_left = self.player_roads_remaining(player)
        if pieces_left <= 0:
            result["reason"] = "no_road_pieces_remaining"
            return result

        roads_to_place = min(2, pieces_left)

        self._ensure_player_dcard_state(player)
        has_tfr = "two_free_roads" in [str(c) for c in (getattr(player, "development_cards", []) or [])]
        if not has_tfr:
            try:
                from gui.gui_play_dcard_panel import playable_count_for_type

                if playable_count_for_type(player, "two_free_roads") <= 0:
                    result["reason"] = "no_tfr_in_hand"
                    return result
            except Exception:
                result["reason"] = "no_tfr_in_hand"
                return result

        if not self._remove_development_card_from_player(player, "two_free_roads"):
            try:
                idx = self._execution_dcard_summary_index("two_free_roads")
                row = player.dcard_summary[idx]
                if int(row[2] or 0) <= 0:
                    result["reason"] = "no_tfr_in_hand"
                    return result
                row[2] = int(row[2]) - 1
                row[3] = int(row[3] or 0) + 1
            except Exception:
                result["reason"] = "could_not_consume_tfr"
                return result

        self._mark_dcard_played_this_turn("two_free_roads", player)

        self.pending_tfr_play = {
            "active": True,
            "player_id": getattr(player, "id", None),
            "roads_total": int(roads_to_place),
            "roads_placed": 0,
            "roads_remaining_to_place": int(roads_to_place),
            "placed_road_ids": [],
            "pieces_at_start": int(pieces_left),
        }

        note = ""
        if roads_to_place == 1:
            note = " (only 1 road piece left)"
        message = f"plays Two Free Roads — place {roads_to_place} free road(s){note}"
        try:
            self.record_turn_event(
                player=player,
                event_type="play_dcard",
                source="human_play_tfr",
                message=message,
                metadata={
                    "card": "two_free_roads",
                    "roads_total": roads_to_place,
                    "pieces_at_start": pieces_left,
                },
            )
        except Exception:
            pass
        try:
            from core import mglog

            mglog.log_play_dcard(
                self,
                player,
                "two_free_roads",
                payload=f"roads_total={roads_to_place}",
            )
        except Exception:
            pass
        try:
            self.emit_twitter_event(getattr(player, "id", None), message)
        except Exception:
            pass

        try:
            self._play_execution_action_sound("Play development_card")
        except Exception:
            pass

        self._refresh_gui_scoreboard_after_dcard_change("after_play_tfr")
        try:
            self.refresh_strategy_after_event("after_human_play_tfr", kind="hand")
        except Exception:
            pass
        try:
            self.refresh_viable_actions("after_human_play_tfr")
        except Exception:
            pass

        result.update(
            {
                "ok": True,
                "reason": "tfr_played_place_free_roads",
                "roads_total": roads_to_place,
                "roads_remaining_to_place": roads_to_place,
                "pieces_at_start": pieces_left,
                "message": message,
                "state_after": str(getattr(self, "state", "")),
                "open_free_road_guidance": True,
            }
        )
        self.last_execution_result = dict(result)
        print(message)
        return result

    def _tfr_pending_for_player(self, player: Optional[Player]) -> Optional[Dict[str, Any]]:
        pending = getattr(self, "pending_tfr_play", None) or {}
        if not isinstance(pending, Mapping) or not pending.get("active"):
            return None
        if player is None:
            return dict(pending)
        try:
            if int(pending.get("player_id", -1)) != int(getattr(player, "id", -2)):
                return None
        except Exception:
            return None
        return dict(pending)

    def _complete_tfr_play(self, player: Player, *, early: bool = False) -> Dict[str, Any]:
        pending = getattr(self, "pending_tfr_play", None) or {}
        placed = int(pending.get("roads_placed", 0) or 0)
        total = int(pending.get("roads_total", 0) or 0)
        self.pending_tfr_play = {"active": False}
        msg = (
            f"Two Free Roads complete ({placed}/{total})"
            if not early
            else f"Two Free Roads ends early ({placed}/{total})"
        )
        try:
            self.emit_twitter_event(getattr(player, "id", None), msg)
        except Exception:
            pass
        # Final LR recompute after the free-road batch (roads already recomputed per place)
        try:
            self.recompute_longest_road(
                reason="after_tfr_complete",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
            )
        except Exception:
            pass
        # W2: TFR batch may award Longest Road and end the game.
        win_check: Dict[str, Any] = {}
        try:
            win_check = self._maybe_declare_winner_after("after_tfr_complete", player)
        except Exception:
            win_check = {"ok": False, "won": False, "reason": "win_check_exception"}
        try:
            if not bool(getattr(self, "game_over", False)):
                self.refresh_viable_actions("after_tfr_complete")
        except Exception:
            pass
        return {
            "ok": True,
            "tfr_complete": True,
            "roads_placed": placed,
            "roads_total": total,
            "message": msg,
            "win_check": win_check,
        }

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

    def _seat_in_endgame_for_dcard_l2(self, player: Any) -> bool:
        """Soft endgame gate for VP/TFR buy → L2 (structures≥4 or effective VP≥7)."""
        try:
            from core.endgame_sequence import SETTLE_CAP_SOFT

            n_s = len(list(getattr(player, "settlements", []) or []))
            n_c = len(list(getattr(player, "cities", []) or []))
            if (n_s + n_c) >= int(SETTLE_CAP_SOFT):
                return True
        except Exception:
            pass
        try:
            vp = int(getattr(player, "victory_points", 0) or 0)
            # Include public specials roughly via game helper if present
            fn = getattr(self, "_victory_points_for_player", None)
            if callable(fn):
                vp = int(fn(player) or vp)
            return vp >= 7
        except Exception:
            return False

    def _maybe_force_l2_after_endgame_dcard_buy(
        self, player: Any, card_name: Any
    ) -> Dict[str, Any]:
        """Endgame only: VP or TFR draw forces explore (residual / LR reconsider)."""
        out: Dict[str, Any] = {"ok": False, "forced": False, "reason": ""}
        cn = str(card_name or "").strip().lower()
        is_vp = "victory" in cn or cn in ("vp", "victory_point", "victorypoint")
        is_tfr = (
            "two_free" in cn
            or "road_building" in cn
            or cn in ("tfr", "two_free_roads")
        )
        if not (is_vp or is_tfr):
            out["reason"] = "not_vp_or_tfr"
            return out
        if not self._seat_in_endgame_for_dcard_l2(player):
            out["reason"] = "not_endgame"
            return out
        reason = "flag:dcard_vp_drawn" if is_vp else "flag:dcard_tfr_drawn"
        try:
            from core.strategy_sticky import flag_strategy_recalc

            flag_strategy_recalc(player, reason, detail={"card_name": card_name})
            try:
                setattr(player, "force_strategy_recalc", True)
            except Exception:
                pass
            try:
                from core.strategy_reconsider import set_reconsider_flag

                set_reconsider_flag(player, "need_next_target", reason=reason)
            except Exception:
                pass
            # Light milestone-style pending resolve (do not clear sticky for knight-like)
            try:
                setattr(
                    player,
                    "pending_full_resolve",
                    {
                        "reason": reason,
                        "trigger": "endgame_dcard_vp_tfr",
                        "detail": {"card_name": card_name},
                    },
                )
            except Exception:
                pass
            out.update({"ok": True, "forced": True, "reason": reason})
        except Exception as exc:
            out["error"] = str(exc)
        return out

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
        try:
            from core.game_statistics import bump_player_stat

            bump_player_stat(player, "stats_dcards_bought", 1)
        except Exception:
            pass
        # P2-7: opp DCard dirty only for LA-relevant seats (not global)
        try:
            from core.strategy_sticky import flag_opponents_after_dcard_buy

            out_flag = flag_opponents_after_dcard_buy(self, player)
        except Exception:
            out_flag = {}
        # P2-5: own Q2 opportunistic buy is analytics only — never sets L2 flags
        try:
            src = str(plan_item.get("source") or "")
            if "q2" in src.lower():
                from core.strategy_dirty import mark_q2_bought_this_turn

                mark_q2_bought_this_turn(player)
        except Exception:
            pass
        self.update_strategy_dashboard(player)
        self._refresh_gui_scoreboard_after_dcard_change("after_ai_buy_dcard")
        self.emit_twitter_event(getattr(player, "id", None), f"bought a DCard ({card_name})")
        self._play_execution_action_sound(action)
        try:
            from core import mglog

            mglog.log_buy_dcard(
                self, player, card_name, rc_out=cost, source="ai_buy_dcard"
            )
        except Exception:
            pass
        # WP3 code 7: TFR buy while pursuing LR
        try:
            cn = str(card_name or "").lower()
            if "two_free" in cn or cn in ("tfr", "road_building"):
                from core.strategy_explicit_recalc import note_lr_tooling

                note_lr_tooling(self, player, reason="buy_tfr", force=True)
            else:
                from core.strategy_explicit_recalc import note_lr_tooling

                note_lr_tooling(self, player, reason="after_buy_dcard")
        except Exception:
            pass
        # Endgame: VP or TFR buy → force L2 explore (shrink VP/DC residual / reconsider LR)
        try:
            out_l2 = self._maybe_force_l2_after_endgame_dcard_buy(player, card_name)
        except Exception:
            out_l2 = {"ok": False}
        out: Dict[str, Any] = {
            "ok": True,
            "action": action,
            "card_name": card_name,
            "strategy_recalc_flagged_opponents": out_flag,
            "endgame_dcard_l2": out_l2,
        }
        # W2: buying a VP card can push total ≥ threshold.
        try:
            out["win_check"] = self._maybe_declare_winner_after("after_ai_buy_dcard", player)
        except Exception:
            out["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        return out

    def _execute_ai_build_city(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        action = "Build city"
        target = self._target_from_plan_item(plan_item)
        cost = self._execution_cost_vector_for_action(action)
        if target is None:
            return {"ok": False, "action": action, "reason": "missing_target"}
        if self.player_cities_remaining(player) <= 0:
            return {"ok": False, "action": action, "reason": "no_city_pieces_remaining", "target_id": target}
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
        try:
            player.recalculate_victory_points()
        except Exception:
            pass
        # Own city does not break LR continuity; recompute still refreshes award fields
        try:
            self.recompute_longest_road(
                reason="after_ai_build_city",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
            )
        except Exception:
            pass
        self.update_strategy_dashboard(player)
        self.emit_twitter_event(getattr(player, "id", None), f"built City @{target}")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, target_id=target)
        try:
            from core import mglog

            mglog.log_build(self, "city", player, target_id=target, rc_out=cost)
        except Exception:
            pass
        # S1: flag opponents once; own city milestone handled in Slice D after scan
        try:
            from core.strategy_sticky import flag_opponents_after_structure

            out_flag = flag_opponents_after_structure(
                self, player, "city", target_id=target
            )
        except Exception:
            out_flag = {}
        try:
            from core.sidestep_s142_drive import (
                latch_opp_build_for_opponents,
                latch_own_public_milestone,
            )

            latch_opp_build_for_opponents(self, player, kind="city")
            latch_own_public_milestone(self, player, kind="city")
        except Exception:
            pass
        board_fit_force: Dict[str, Any] = {}
        try:
            from core.strategy_board_fit import maybe_force_board_fit

            board_fit_force = maybe_force_board_fit(self, player, reason="own_city") or {}
        except Exception:
            board_fit_force = {}
        out: Dict[str, Any] = {
            "ok": True,
            "action": action,
            "target_id": target,
            "strategy_recalc_flagged_opponents": out_flag,
            "own_strategy_milestone": "own_city",
            "board_fit_force": board_fit_force,
        }
        try:
            out["win_check"] = self._maybe_declare_winner_after("after_ai_build_city", player)
        except Exception:
            out["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        return out

    def _execute_ai_build_settlement(self, player: Player, plan_item: Mapping[str, Any]) -> Dict[str, Any]:
        action = "Build settlement"
        target = self._target_from_plan_item(plan_item)
        cost = self._execution_cost_vector_for_action(action)
        if target is None:
            return {"ok": False, "action": action, "reason": "missing_target"}
        if self.player_settlements_remaining(player) <= 0:
            return {"ok": False, "action": action, "reason": "no_settlement_pieces_remaining", "target_id": target}
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
        try:
            player.recalculate_victory_points()
        except Exception:
            pass
        # Settlement can break opponent continuous roads → full LR recompute (WP6.2)
        try:
            self.recompute_longest_road(
                reason="after_ai_build_settlement",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
                force_full=True,
            )
        except Exception:
            pass
        self.update_strategy_dashboard(player)
        self.emit_twitter_event(getattr(player, "id", None), f"built Settlement @{target}")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, target_id=target)
        try:
            from core import mglog

            mglog.log_build(self, "settlement", player, target_id=target, rc_out=cost)
        except Exception:
            pass
        try:
            from core.strategy_sticky import flag_opponents_after_structure

            out_flag = flag_opponents_after_structure(
                self, player, "settlement", target_id=target
            )
        except Exception:
            out_flag = {}
        try:
            from core.sidestep_s142_drive import (
                latch_opp_build_for_opponents,
                latch_own_public_milestone,
            )

            latch_opp_build_for_opponents(self, player, kind="settlement")
            latch_own_public_milestone(self, player, kind="settlement")
        except Exception:
            pass
        # WP2 / Way sync P1: settlement can create structure_surplus vs sticky way
        board_fit_force: Dict[str, Any] = {}
        try:
            from core.strategy_board_fit import maybe_force_board_fit

            board_fit_force = maybe_force_board_fit(
                self, player, reason="own_settlement"
            ) or {}
        except Exception:
            board_fit_force = {}
        # Own rec-settle vs any settle: milestone reason refined in Slice D
        out: Dict[str, Any] = {
            "ok": True,
            "action": action,
            "target_id": target,
            "strategy_recalc_flagged_opponents": out_flag,
            "own_strategy_milestone": "own_settlement",
            "board_fit_force": board_fit_force,
        }
        try:
            out["win_check"] = self._maybe_declare_winner_after("after_ai_build_settlement", player)
        except Exception:
            out["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        return out

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

        # Capture own LR length before mutate (WP-H)
        length_before = None
        try:
            from core.longest_road import compute_longest_road_for_player

            length_before = int(compute_longest_road_for_player(self, player) or 0)
        except Exception:
            try:
                length_before = int(getattr(player, "size_longest_route", 0) or 0)
            except Exception:
                length_before = None

        self.board.occupy_road(road, "Road", player.color)
        if road not in list(getattr(player, "roads", []) or []):
            player.roads.append(road)
        self._deduct_execution_cost(player, cost, category="buy", message=f"built Road {list(road)}", metadata={"road_id": list(road)})
        lr_info: Dict[str, Any] = {}
        try:
            lr_info = self.recompute_longest_road(
                reason="after_ai_build_road",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
            ) or {}
        except Exception:
            lr_info = {}
        # S1 ext: LR-pursuing opponents batch-flag (road can change race without flip)
        try:
            from core.strategy_sticky import flag_opponents_after_road

            out_flag = flag_opponents_after_road(self, player, road_id=list(road))
        except Exception:
            out_flag = {}
        # Light sticky-settle risk refresh (no L2): path road can end soft races
        sticky_risk: Dict[str, Any] = {}
        try:
            from core.strategy_sticky import refresh_sticky_settle_risk_after_own_road

            sticky_risk = refresh_sticky_settle_risk_after_own_road(
                self, player, road=list(road)
            )
        except Exception:
            sticky_risk = {}
        # WP-H: LR grow / sticky path complete → force L2 retarget (S5→S44 dig)
        l2_road: Dict[str, Any] = {}
        try:
            from core.strategy_sticky import maybe_force_l2_after_lr_or_component_road

            length_after = None
            try:
                ch = (lr_info or {}).get("length_changes") or {}
                pid = int(getattr(player, "id", 0) or 0)
                if pid in ch:
                    length_after = int((ch[pid] or {}).get("to") or 0)
            except Exception:
                length_after = None
            if length_after is None:
                try:
                    length_after = int(getattr(player, "size_longest_route", 0) or 0)
                except Exception:
                    length_after = None
            holder_changed = bool((lr_info or {}).get("holder_changed"))
            # Own gain of LR also counted via holder_changed + actor
            try:
                if holder_changed and int((lr_info or {}).get("holder_id") or -1) == int(
                    getattr(player, "id", -2) or -2
                ):
                    holder_changed = True
            except Exception:
                pass
            l2_road = maybe_force_l2_after_lr_or_component_road(
                self,
                player,
                road=list(road),
                length_before=length_before,
                length_after=length_after,
                holder_changed=holder_changed,
                sticky_risk=sticky_risk,
            )
        except Exception:
            l2_road = {}
        try:
            from core.sidestep_s142_drive import latch_opp_build_for_opponents

            latch_opp_build_for_opponents(self, player, kind="road")
        except Exception:
            pass
        self.update_strategy_dashboard(player)
        self.emit_twitter_event(getattr(player, "id", None), f"built Road [{road[0]},{road[1]}]")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, road_id=road)
        try:
            from core import mglog

            mglog.log_build(self, "road", player, road=road, rc_out=cost)
        except Exception:
            pass
        out: Dict[str, Any] = {
            "ok": True,
            "action": action,
            "road_id": list(road),
            "strategy_recalc_flagged_opponents": out_flag,
            "sticky_settle_risk_refresh": dict(sticky_risk) if sticky_risk else {},
            "lr_component_l2": dict(l2_road) if l2_road else {},
        }
        try:
            out["win_check"] = self._maybe_declare_winner_after("after_ai_build_road", player)
        except Exception:
            out["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        return out

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
                self.refresh_strategy_after_event(str(reason), kind="auto")
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
        if bool(getattr(self, "game_over", False)):
            result["reason"] = "game_over"
            return None
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
            from core.game_statistics import bump_player_stat

            bump_player_stat(player, "stats_dcards_bought", 1)
        except Exception:
            pass
        try:
            from core.strategy_sticky import flag_opponents_after_dcard_buy

            result["strategy_recalc_flagged_opponents"] = flag_opponents_after_dcard_buy(
                self, player
            )
        except Exception:
            result["strategy_recalc_flagged_opponents"] = {}
        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass
        self._refresh_gui_scoreboard_after_dcard_change("after_human_buy_dcard")
        self.emit_twitter_event(getattr(player, "id", None), f"bought a DCard ({card_name})")
        self._play_execution_action_sound(action)
        try:
            from core import mglog

            mglog.log_buy_dcard(
                self, player, card_name, rc_out=cost, source="human_buy_dcard"
            )
        except Exception:
            pass

        result.update({"ok": True, "reason": "executed", "card_name": card_name})
        try:
            result["endgame_dcard_l2"] = self._maybe_force_l2_after_endgame_dcard_buy(
                player, card_name
            )
        except Exception:
            result["endgame_dcard_l2"] = {"ok": False}
        try:
            result["win_check"] = self._maybe_declare_winner_after("after_human_buy_dcard", player)
        except Exception:
            result["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        if not bool(getattr(self, "game_over", False)):
            try:
                result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_buy_dcard", result)
            except Exception as exc:
                result["slice_d"] = {"ok": False, "reason": str(exc)}
        else:
            result["slice_d"] = {"ok": False, "reason": "game_over", "skipped": True}
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
        if self.player_cities_remaining(player) <= 0:
            result["reason"] = "no_city_pieces_remaining"
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
        try:
            player.recalculate_victory_points()
        except Exception:
            pass

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
        try:
            from core import mglog

            mglog.log_build(self, "city", player, target_id=target, rc_out=cost)
        except Exception:
            pass
        # Own city does not interrupt continuous road; recompute keeps award in sync
        try:
            self.recompute_longest_road(
                reason="after_human_build_city",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
            )
        except Exception:
            pass

        try:
            from core.strategy_sticky import flag_opponents_after_structure

            result["strategy_recalc_flagged_opponents"] = flag_opponents_after_structure(
                self, player, "city", target_id=target
            )
        except Exception:
            result["strategy_recalc_flagged_opponents"] = {}
        try:
            from core.strategy_board_fit import maybe_force_board_fit

            result["board_fit_force"] = maybe_force_board_fit(
                self, player, reason="own_city"
            ) or {}
        except Exception:
            result["board_fit_force"] = {}
        result.update({
            "ok": True,
            "reason": "executed",
            "target_id": target,
            "own_strategy_milestone": "own_city",
        })
        try:
            result["win_check"] = self._maybe_declare_winner_after("after_human_build_city", player)
        except Exception:
            result["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        if not bool(getattr(self, "game_over", False)):
            try:
                result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_build_city", result)
            except Exception as exc:
                result["slice_d"] = {"ok": False, "reason": str(exc)}
        else:
            result["slice_d"] = {"ok": False, "reason": "game_over", "skipped": True}
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
        if self.player_settlements_remaining(player) <= 0:
            result["reason"] = "no_settlement_pieces_remaining"
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
        try:
            from core import mglog

            mglog.log_build(self, "settlement", player, target_id=target, rc_out=cost)
        except Exception:
            pass
        # Settlement can break opponent continuous roads → full LR recompute (WP6.2)
        try:
            self.recompute_longest_road(
                reason="after_human_build_settlement",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
                force_full=True,
            )
        except Exception:
            pass

        try:
            from core.strategy_sticky import flag_opponents_after_structure

            result["strategy_recalc_flagged_opponents"] = flag_opponents_after_structure(
                self, player, "settlement", target_id=target
            )
        except Exception:
            result["strategy_recalc_flagged_opponents"] = {}
        try:
            from core.strategy_board_fit import maybe_force_board_fit

            result["board_fit_force"] = maybe_force_board_fit(
                self, player, reason="own_settlement"
            ) or {}
        except Exception:
            result["board_fit_force"] = {}
        result.update({
            "ok": True,
            "reason": "executed",
            "target_id": target,
            "own_strategy_milestone": "own_settlement",
        })
        try:
            result["win_check"] = self._maybe_declare_winner_after("after_human_build_settlement", player)
        except Exception:
            result["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        if not bool(getattr(self, "game_over", False)):
            try:
                result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_build_settlement", result)
            except Exception as exc:
                result["slice_d"] = {"ok": False, "reason": str(exc)}
        else:
            result["slice_d"] = {"ok": False, "reason": "game_over", "skipped": True}
        self.last_execution_result = result
        self._post_check_executed_action(
            player,
            {"action": action, "choice": {"candidates": [{"target_id": target}]}},
            result,
        )
        return result

    def execute_human_build_road_action(
        self,
        road_id: Sequence[int],
        *,
        free: bool = False,
    ) -> Dict[str, Any]:
        """Execute a confirmed human Build Road action.

        Human road selection uses the shared viable_action_scanner candidates for
        the visible choices.  This method is the final law: it re-checks phase,
        turn state, resources, board legality, and human-network adjacency before
        mutating the board.

        ``free=True`` (or an active ``pending_tfr_play``) places a free road for
        Two Free Roads — no resource cost; counts against the 15-piece limit.
        """
        action = "Build road"
        player = self.get_current_player()
        road = self._road_from_raw_value(road_id)
        tfr = self._tfr_pending_for_player(player)
        free_tfr = bool(free) or bool(tfr)
        cost = [0, 0, 0, 0, 0] if free_tfr else self._execution_cost_vector_for_action(action)
        result: Dict[str, Any] = {
            "ok": False,
            "action": action,
            "road_id": list(road) if road is not None else [],
            "reason": "",
            "source": "human_tfr_free_road" if free_tfr else "human_buy_road",
            "free": free_tfr,
        }

        if bool(getattr(self, "game_over", False)):
            result["reason"] = "game_over"
            return result
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
        if free_tfr:
            if not tfr:
                result["reason"] = "no_active_tfr"
                return result
            if int(tfr.get("roads_remaining_to_place", 0) or 0) <= 0:
                result["reason"] = "tfr_no_roads_left_to_place"
                return result
            if self.player_roads_remaining(player) <= 0:
                result["reason"] = "no_road_pieces_remaining"
                return result
        else:
            if self.player_roads_remaining(player) <= 0:
                result["reason"] = "no_road_pieces_remaining"
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

        if free_tfr:
            # Free road: ledger as dcard placement, no resource deduct
            try:
                self.record_turn_event(
                    player=player,
                    event_type="build_road_free",
                    source="human_tfr_free_road",
                    message=f"built free Road [{road[0]},{road[1]}]",
                    metadata={"road_id": list(road), "free": True},
                )
            except Exception:
                pass
            # Update pending TFR counters
            pending = getattr(self, "pending_tfr_play", None) or {}
            if isinstance(pending, dict) and pending.get("active"):
                placed = int(pending.get("roads_placed", 0) or 0) + 1
                remaining = max(0, int(pending.get("roads_remaining_to_place", 0) or 0) - 1)
                placed_ids = list(pending.get("placed_road_ids") or [])
                placed_ids.append(list(road))
                pending["roads_placed"] = placed
                pending["roads_remaining_to_place"] = remaining
                pending["placed_road_ids"] = placed_ids
                self.pending_tfr_play = pending
                result["tfr_roads_placed"] = placed
                result["tfr_roads_remaining"] = remaining
                result["tfr_roads_total"] = int(pending.get("roads_total", 0) or 0)
                # More free roads? (piece limit may stop early)
                need_more = remaining > 0 and self.player_roads_remaining(player) > 0
                result["tfr_need_another_road"] = bool(need_more)
                if not need_more:
                    done = self._complete_tfr_play(player, early=remaining > 0)
                    result["tfr_complete"] = done
                else:
                    n = int(pending.get("roads_total", 2) or 2)
                    self.emit_twitter_event(
                        getattr(player, "id", None),
                        f"built free Road [{road[0]},{road[1]}] ({placed}/{n}) — place next",
                    )
        else:
            self._deduct_execution_cost(
                player,
                cost,
                category="buy",
                message=f"built Road {list(road)}",
                metadata={"road_id": list(road), "human_selected": True},
                source="human_buy_road",
                reason="human_confirmed_build_road",
            )

        # LR recompute after every committed road (paid or free TFR)
        try:
            lr_info = self.recompute_longest_road(
                reason="after_human_build_road" if not free_tfr else "after_human_free_road",
                emit_events=True,
                refresh_scoreboard=True,
                actor=player,
            )
            result["longest_road"] = {
                "holder_id": lr_info.get("holder_id"),
                "best_length": lr_info.get("best_length"),
                "holder_changed": lr_info.get("holder_changed"),
                "recompute_scope": lr_info.get("recompute_scope"),
            }
        except Exception:
            pass

        # S1 ext: flag LR-pursuing AIs after any committed human road (incl. free TFR)
        try:
            from core.strategy_sticky import flag_opponents_after_road

            result["strategy_recalc_flagged_opponents"] = flag_opponents_after_road(
                self, player, road_id=list(road)
            )
        except Exception:
            result["strategy_recalc_flagged_opponents"] = {}

        # Light sticky-settle risk refresh (no L2) when path road advances settle race
        try:
            from core.strategy_sticky import refresh_sticky_settle_risk_after_own_road

            result["sticky_settle_risk_refresh"] = refresh_sticky_settle_risk_after_own_road(
                self, player, road=list(road)
            )
        except Exception:
            result["sticky_settle_risk_refresh"] = {}

        try:
            self.update_strategy_dashboard(player)
        except Exception:
            pass
        if not free_tfr:
            self.emit_twitter_event(getattr(player, "id", None), f"built Road [{road[0]},{road[1]}]")
        elif free_tfr and not result.get("tfr_need_another_road"):
            self.emit_twitter_event(getattr(player, "id", None), f"built free Road [{road[0]},{road[1]}]")
        self._play_execution_action_sound(action)
        self._set_pending_execution_build_animation(action, player, road_id=road)

        result.update({"ok": True, "reason": "executed", "road_id": list(road)})
        try:
            from core import mglog

            mglog.log_build(
                self,
                "road",
                player,
                road=road,
                free=bool(free_tfr),
                rc_out=[0, 0, 0, 0, 0] if free_tfr else cost,
            )
        except Exception:
            pass
        # W2: paid road or free TFR road may award Longest Road and end the game.
        try:
            win_reason = (
                "after_human_build_road"
                if not free_tfr
                else "after_human_free_road"
            )
            result["win_check"] = self._maybe_declare_winner_after(win_reason, player)
        except Exception:
            result["win_check"] = {"ok": False, "won": False, "reason": "win_check_exception"}
        if bool(getattr(self, "game_over", False)):
            result["slice_d"] = {"ok": False, "reason": "game_over", "skipped": True}
        elif not free_tfr:
            try:
                result["slice_d"] = self._refresh_after_human_buy_build_action("after_human_build_road", result)
            except Exception as exc:
                result["slice_d"] = {"ok": False, "reason": str(exc)}
        else:
            try:
                self.refresh_strategy_after_event("after_human_free_road", kind="milestone")
                self.refresh_viable_actions("after_human_free_road")
            except Exception:
                pass
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
            # T8-complete: never re-open a deal HP already declined this turn
            try:
                from core.human_twp_policy import is_proposal_declined_this_turn

                if isinstance(proposal, Mapping) and is_proposal_declined_this_turn(
                    self, proposal
                ):
                    try:
                        self._invalidate_stale_incoming_twp_after_decline(None, proposal)
                    except Exception:
                        pass
                    try:
                        self.emit_twitter_event(
                            getattr(player, "id", None),
                            "DBG: blocked re-offer of HP-declined TwP (T8).",
                        )
                    except Exception:
                        pass
                    return {
                        "ok": False,
                        "action": "Incoming TwP",
                        "status": "blocked_declined",
                        "reason": "human_twp_declined_this_turn",
                        "proposal": dict(proposal),
                    }
            except Exception:
                pass
            if isinstance(proposal, Mapping):
                pending = self._set_pending_human_twp_offer(
                    proposal, decision, play_sound=True
                )
                if isinstance(pending, Mapping) and pending.get("refused"):
                    return {
                        "ok": False,
                        "action": "Incoming TwP",
                        "status": "blocked_declined",
                        "reason": str(pending.get("reason") or "refused_pending"),
                        "proposal": dict(proposal),
                    }
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
        if bool(getattr(self, "game_over", False)):
            result = {
                "ok": False,
                "reason": "game_over",
                "already_over": True,
                "advance_turn": False,
                "player_id": getattr(player, "id", None) if player is not None else None,
                "win_result": getattr(self, "win_result", None),
            }
            self.last_ai_continue_result = result
            return result
        # Use logic gate only — not ai_continue_is_available(). The GUI wraps
        # this call in play_continue_busy_scope (P3-A); the UI-busy check would
        # return continue_not_available and never advance the turn.
        if not self._ai_continue_logic_available():
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

        # P2 / P3-A: gate Continue while this step (and nested Slice D) runs.
        # Prefer nested-safe busy scope so outer PLAY/Continue click scopes compose.
        try:
            from core.performance_trace import ai_pipeline_busy_scope
        except Exception:
            ai_pipeline_busy_scope = None  # type: ignore

        if ai_pipeline_busy_scope is not None:
            with ai_pipeline_busy_scope(self, "continue_ai_execution_turn"):
                return self._continue_ai_execution_turn_body(player)

        try:
            from core.performance_trace import set_ai_pipeline_busy as _set_ai_busy
        except Exception:
            def _set_ai_busy(_g, _b, reason=""):  # type: ignore
                try:
                    _g.ai_pipeline_busy = bool(_b)
                except Exception:
                    pass

        _set_ai_busy(self, True, "continue_ai_execution_turn")
        try:
            return self._continue_ai_execution_turn_body(player)
        finally:
            _set_ai_busy(self, False)

    def _continue_ai_execution_turn_body(self, player: Any) -> Dict[str, Any]:
        """Inner AI Continue work (called under ai_pipeline_busy)."""
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

        # Do not rescan here.  Continue must execute the canonical Best-Action
        # object that was frozen by the latest refresh_viable_actions() call and
        # displayed in Execution Debug.  A click-time rescan can reorder city
        # candidates and cause a displayed target like @40 to execute as @26.
        plan_item = self.get_current_best_executable_action()
        execution_source = "canonical_best_action" if plan_item is not None else "preview_plan_fallback"
        if plan_item is None:
            plan_item = self._first_executable_ai_plan_item(plan_before)
        # T8-complete: never Continue-execute a declined Incoming TwP (stale plan)
        if self._plan_item_is_declined_incoming_twp(plan_item):
            try:
                prop = (plan_item or {}).get("proposal") or {}
                self._invalidate_stale_incoming_twp_after_decline(None, prop)
            except Exception:
                pass
            plan_item = self._first_executable_ai_plan_item(
                list(getattr(self, "current_ai_execution_plan", None) or [])
            )
            if plan_item is None:
                plan_item = {
                    "step": 1,
                    "action": "End turn",
                    "reason": "T8: declined Incoming blocked on Continue.",
                    "source": "pass_after_decline_continue",
                }
            execution_source = "t8_declined_incoming_blocked"

        if plan_item is not None and str(plan_item.get("action", "") or "") == "End turn":
            reason = str(plan_item.get("reason") or "No executable Best-Action action.")
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
            # BA None + plan only Pass/End turn (common early-game) — still pass.
            reason = "no_executable_plan_item"
            try:
                for row in list(plan_before or []):
                    if isinstance(row, Mapping) and str(row.get("action", "") or "") == "End turn":
                        reason = str(row.get("reason") or reason)
                        break
            except Exception:
                pass
            self.emit_twitter_event(
                getattr(player, "id", None),
                f"DBG: {reason} pass."[:180],
            )
            executed_result = {"ok": True, "action": "End turn", "reason": reason}
            execution_source = "pass"

        # W2: winning buy/build must freeze the AI pipeline (no Slice D / advance).
        if bool(getattr(self, "game_over", False)):
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
                "slice_d": {"ok": False, "reason": "game_over", "skipped": True},
                "game_over": True,
                "win_result": getattr(self, "win_result", None),
                "note": "Game over after executed action; AI turn pipeline stopped.",
            }
            self.last_ai_continue_result = result
            self.last_execution_result = result
            try:
                self.ai_execution_preview_ready = False
                self.current_ai_execution_plan = []
                self.ai_execution_stage = "game_over"
            except Exception:
                pass
            return result

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
        # P2-B: robber tile / steal changes board fingerprint
        try:
            from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

            invalidate_board_way_portfolio_cache(self, "basic_robber_strategy")
        except Exception:
            pass
        # P2-8: dirty only seats for whom robber tile is plan/production relevant
        try:
            from core.strategy_dirty import flag_opponents_after_robber

            tile = None
            move = result.get("move") if isinstance(result, Mapping) else None
            if isinstance(move, Mapping):
                tile = move.get("tile_id") or move.get("robber_tile_id")
            if tile is None:
                tile = getattr(self, "robber_tile_id", None) or getattr(
                    getattr(self, "board", None), "robber_tile_id", None
                )
            result["strategy_recalc_flagged_opponents"] = flag_opponents_after_robber(
                self, player, tile_id=tile
            )
        except Exception:
            pass
        # Single strategy refresh for robber path (Slice D may dedupe same reason).
        self.refresh_strategy_after_event(
            "after_basic_robber_strategy", kind="turn_start"
        )
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

        # P2-B: robber tile change invalidates portfolio cache
        try:
            from core.ai_way_portfolio import invalidate_board_way_portfolio_cache

            invalidate_board_way_portfolio_cache(self, "move_robber")
        except Exception:
            pass
        # P2-8: plan/production-relevant dirty flags only
        try:
            from core.strategy_dirty import flag_opponents_after_robber

            result["strategy_recalc_flagged_opponents"] = flag_opponents_after_robber(
                self, player, tile_id=int(tile_id)
            )
        except Exception:
            pass
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
        """Return after a resolved human robber/steal flow.

        - After a **7**, resume normal ActionSelection (buy/trade/end still open).
        - After a **pre-roll Knight**, resume **AwaitingDiceRoll** (only Roll Dices).
        - After a **post-roll Knight**, resume **ActionSelection** (normal turn continues).
        """
        knight = getattr(self, "pending_knight_play", None) or {}
        if isinstance(knight, Mapping) and knight.get("active"):
            resume_state = str(knight.get("resume_state") or "ActionSelection")
            timing = str(knight.get("timing") or "")
            try:
                self.pending_knight_play = {"active": False}
            except Exception:
                pass
            try:
                if isinstance(getattr(self, "pending_seven_roll", None), dict):
                    self.pending_seven_roll["active"] = False
                if isinstance(getattr(self, "pending_robber_steal", None), dict):
                    self.pending_robber_steal["active"] = False
                    self.pending_robber_steal["awaiting_human_target"] = False
            except Exception:
                pass
            try:
                self.myturn.validate_function_set_robber_by_HP = False
            except Exception:
                pass

            if resume_state == "AwaitingDiceRoll" or timing == "before_roll":
                try:
                    self.state = "AwaitingDiceRoll"
                    self.state_1 = ""
                    self.state_2 = ""
                except Exception:
                    pass
                try:
                    # Knight moved robber: board geometry, not pure hand (P1 WP3)
                    self.refresh_strategy_after_event(
                        "after_human_knight_robber_pre_roll", kind="board"
                    )
                except Exception:
                    pass
                try:
                    self.refresh_viable_actions("after_human_knight_robber_pre_roll")
                except Exception:
                    pass
                try:
                    self.emit_twitter_event(
                        getattr(self.get_current_player(), "id", None),
                        "Knight done — roll the dice",
                    )
                except Exception:
                    pass
                out = {
                    "ok": True,
                    "resume_to": "AwaitingDiceRoll",
                    "timing": "before_roll",
                    "reason": str(reason or "after_human_knight_robber_pre_roll"),
                    "only_action": "Roll Dices",
                }
                self.last_slice_d_result = out
                return out

            # Post-roll knight: same as finishing any forced robber — ActionSelection
            try:
                self.emit_twitter_event(
                    getattr(self.get_current_player(), "id", None),
                    "Knight done — continue your turn",
                )
            except Exception:
                pass
            out = self.continue_action_selection_after_action(
                str(reason or "after_human_knight_robber_post_roll"),
                player=self.get_current_player(),
                action_result={"action": "Resolve knight robber", "ok": True, "timing": "after_roll"},
                clear_forced_locks=True,
            )
            if isinstance(out, dict):
                out["resume_to"] = "ActionSelection"
                out["timing"] = "after_roll"
                out["only_action"] = None
            return out

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

        self.refresh_strategy_after_event(reason or "action_executed", kind="auto")
        return self.refresh_viable_actions(reason or "action_executed")

    def advance_turn(self) -> None:
        """Advance to the next player's turn and update game state.

        Handles the initial placement sequence (1,2,3,4,4,3,2,1)
        and transitions to Execution phase. When an Execution turn starts,
        refresh the scanner so Roll Dices becomes the first viable action.
        """
        # W2: do not start another player's turn after a winner was declared.
        if bool(getattr(self, "game_over", False)) and str(getattr(self, "phase", "") or "") == "Execution":
            try:
                from core.console import digin, DEBUG

                digin("game.advance_turn skipped — game_over", level=DEBUG)
            except Exception:
                print("game.advance_turn skipped — game_over")
            try:
                self.ai_execution_preview_ready = False
                self.ai_execution_preview_player_id = None
                self.ai_execution_stage = "game_over"
                self.current_ai_execution_plan = []
                self.current_ai_decision_trace = []
            except Exception:
                pass
            return

        try:
            from core.console import digin, DEBUG

            digin("game.advance_turn executed", level=DEBUG)
        except Exception:
            print("game.advance_turn executed")
        # MGlog: close Execution turn before seat advances
        try:
            if str(getattr(self, "phase", "") or "") == "Execution":
                from core import mglog

                mglog.log_turn_end(self)
        except Exception:
            pass
        # DCard scoreboard: end of this player's turn → move x (new) into y (playable).
        # Must run while the finishing player is still current.
        try:
            if str(getattr(self, "phase", "") or "") == "Execution":
                self._mature_player_dcard_new_to_playable(self.get_current_player())
        except Exception:
            pass
        # PR-D: stamp end-of-turn strategy sample before seat advances
        try:
            from core.strategy_history import mark_end_of_turn_sample

            mark_end_of_turn_sample(self, self.get_current_player())
        except Exception:
            pass
        # Leaving the current turn invalidates any AI preview checkpoint.
        self.ai_execution_preview_ready = False
        self.ai_execution_preview_player_id = None
        self.ai_execution_stage = ""
        self.current_ai_execution_plan = []
        self.current_ai_decision_trace = []
        # P2: clear ephemeral Q2 markers on the seat that just finished
        try:
            from core.strategy_dirty import clear_turn_ephemeral_dirty

            leaving = self.get_current_player()
            clear_turn_ephemeral_dirty(leaving)
        except Exception:
            pass
        try:
            self.pending_human_twp_offer = None
            self.human_twp_accepted_this_turn = set()
            self.human_twp_declined_this_turn = set()
            self.accepted_binding_proposal = None
            self.support_trades_this_turn = 0
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
                    try:
                        from core import mglog

                        mglog.log_ip_complete(self)
                    except Exception:
                        pass
                    saved_game_name = self.save_game()
                    if MG:
                        with open(FILENAME_MG, "a", encoding="utf-8") as f:
                            f.write(
                                "game.py | advance_turn | saved game after "
                                f"initial placement: {saved_game_name}\n"
                            )

                    self.save_screenshot()

        else:
            # Execution (and any non-IP) turn advance: 1→2→…→N→1 (next round).
            n_players = max(1, len(list(getattr(self, "players", []) or [])) or 1)
            try:
                finished_last_player = (
                    str(getattr(self, "phase", "") or "") == "Execution"
                    and int(getattr(self, "turn", 0) or 0) >= n_players
                )
                completed_round = int(getattr(self, "round", 0) or 0)
            except Exception:
                finished_last_player = False
                completed_round = 0

            self.turn = (self.turn % n_players) + 1
            if self.turn == 1:
                self.round += 1

            if self.phase == "Execution":
                entered_execution = True

            # Auto-save once per full round: after player N (P4) fully ends,
            # once the table has advanced to P1 of the next round.
            if finished_last_player and completed_round > 0:
                try:
                    # Lag ring: capture player_view as of end of completed_round
                    self.snapshot_rcard_player_view_end_of_round()
                except Exception as exc:
                    print(f"game.advance_turn | rcard view lag snapshot failed: {exc}")
                try:
                    self._auto_save_end_of_round(completed_round)
                except Exception as exc:
                    print(f"game.advance_turn | end-of-round auto-save failed: {exc}")

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
        """Save a screenshot of the game window via the GUI.

        No-op when headless / no presentation GUI is attached (Phase A).
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{self.id} | {self.state} | game.py | save_screenshot\n")
        try:
            from core.batch.null_gui import is_gui_presentation_enabled

            if not is_gui_presentation_enabled(self):
                return
        except Exception:
            pass
        gui = getattr(self, "gui", None)
        if gui is None:
            return
        saver = getattr(gui, "save_screenshot", None)
        if callable(saver):
            saver()


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
                resource_production_game_player_view_lag=row.get(
                    "resource_production_game_player_view_lag",
                    [],
                ),
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

    def _should_auto_save_completed_round(self, completed_round: int) -> bool:
        """Whether to snapshot after this Execution round finishes.

        Policy:
          - ``CHECK_MODE=True`` (dig-in): every completed Execution round.
          - ``CHECK_MODE=False`` (normal / headless lab): **no** mid-game
            end-of-round saves (not every 5 rounds either).
          - IP-end and game-over saves are handled elsewhere (always),
            including when ``NO_GUI_AT_ALL_TF=True``.
        """
        try:
            r = int(completed_round or 0)
        except Exception:
            return False
        if r <= 0:
            return False
        try:
            from core.debug_mode import is_check_mode

            return bool(is_check_mode())
        except Exception:
            return False

    def _auto_save_end_of_round(self, completed_round: int) -> str:
        """Persist a full snapshot after the last player finishes a round.

        Called from ``advance_turn`` when Execution turn N (player 4 of 4)
        completes and the game has already stepped to the next round / P1.
        Safe no-op when game_over or round is not on the save cadence
        (``CHECK_MODE`` dig-in only). Also takes a screenshot when a save
        runs (NullGui no-ops headless).
        """
        if bool(getattr(self, "game_over", False)):
            return ""
        try:
            r = int(completed_round or 0)
        except Exception:
            r = 0
        if r <= 0:
            return ""
        if not self._should_auto_save_completed_round(r):
            return ""

        timestamp = datetime.now().strftime("%d_%b_%Y_%H_%M_%S")
        filename = f"Saved_Game_{timestamp}_EndRound{r}.txt"
        try:
            path = self.save_game(filename)
        except Exception as exc:
            print(f"Auto-save end of round {r} failed: {exc}")
            try:
                self.emit_twitter_event(
                    None,
                    f"Auto-save failed after round {r}",
                )
            except Exception:
                pass
            return ""

        try:
            self.save_screenshot()
        except Exception:
            pass

        try:
            self.last_auto_save_path = path
            self.last_auto_save_round = r
        except Exception:
            pass

        print(f"✅ Auto-saved end of round {r}: {path}")
        try:
            self.emit_twitter_event(
                None,
                f"Auto-saved end of round {r}",
            )
        except Exception:
            pass
        if MG:
            try:
                with open(FILENAME_MG, "a", encoding="utf-8") as f:
                    f.write(
                        f"game.py | _auto_save_end_of_round | R{r} → {path}\n"
                    )
            except Exception:
                pass
        return str(path or "")

    def _auto_save_game_over(self, win_result: Optional[Mapping[str, Any]] = None) -> str:
        """Persist a full snapshot when a winner is declared.

        Always runs (GUI and headless / ``NO_GUI_AT_ALL_TF``). Idempotent:
        skips if ``last_game_over_save_path`` is already set for this game.
        Screenshot is best-effort (NullGui no-ops).
        """
        if bool(getattr(self, "_game_over_save_done", False)):
            return str(getattr(self, "last_game_over_save_path", "") or "")

        winner_id = None
        try:
            if isinstance(win_result, Mapping):
                winner_id = win_result.get("winner_id")
        except Exception:
            winner_id = None
        if winner_id is None:
            try:
                winner_id = self._player_id_or_none(getattr(self, "winner", None))
            except Exception:
                winner_id = None

        timestamp = datetime.now().strftime("%d_%b_%Y_%H_%M_%S")
        if winner_id is not None:
            filename = f"Saved_Game_{timestamp}_GameOver_P{int(winner_id)}.txt"
        else:
            filename = f"Saved_Game_{timestamp}_GameOver.txt"

        try:
            path = self.save_game(filename)
        except Exception as exc:
            print(f"Auto-save game over failed: {exc}")
            try:
                self.emit_twitter_event(None, "Auto-save failed at game over")
            except Exception:
                pass
            return ""

        try:
            self._game_over_save_done = True
            self.last_game_over_save_path = path
            self.last_auto_save_path = path
        except Exception:
            pass

        try:
            self.save_screenshot()
        except Exception:
            pass

        print(f"✅ Auto-saved game over: {path}")
        try:
            self.emit_twitter_event(None, "Auto-saved game over")
        except Exception:
            pass
        if MG:
            try:
                with open(FILENAME_MG, "a", encoding="utf-8") as f:
                    f.write(f"game.py | _auto_save_game_over | → {path}\n")
            except Exception:
                pass
        return str(path or "")

    def save_game(self, filename: str = "") -> str:
        """
        Save the complete game state to a Saved_Game txt file.

        Filename format when filename is omitted:
            Saved_Game_23_Apr_2025_09_53_50_R2T1.txt

        End-of-round auto-saves (CHECK_MODE dig-in only) use:
            Saved_Game_<timestamp>_EndRound{N}.txt

        Game-over auto-saves (always, including headless) use:
            Saved_Game_<timestamp>_GameOver_P{id}.txt

        Bare basenames (and omitted names) are written under ``saved_games/``
        (see ``SAVED_GAMES_DIR``). Absolute paths or paths with a directory
        component are respected as given.

        The saved file is JSON inside a .txt file. It contains game state,
        board state, player state, dashboards, turn details, development-card
        stack, dice history, robber state, and outlook/common-target state.
        """
        timestamp = datetime.now().strftime("%d_%b_%Y_%H_%M_%S")
        if not filename:
            filename = f"Saved_Game_{timestamp}_R{self.round}T{self.turn}.txt"

        # Route bare basenames into saved_games/ so the project root stays tidy.
        try:
            from pathlib import Path as _Path

            _p = _Path(str(filename))
            if _p.is_absolute() or len(_p.parts) > 1:
                out_path = _p if _p.is_absolute() else (_Path.cwd() / _p)
            else:
                out_path = _Path(SAVED_GAMES_DIR) / _p.name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            write_path = str(out_path)
            meta_filename = out_path.name
        except Exception:
            write_path = str(filename)
            meta_filename = os.path.basename(write_path) or str(filename)

        for player in self.players:
            player.recalculate_victory_points()
            self.update_strategy_dashboard(player)

        payload: Dict[str, Any] = {
            "schema": "CatanSavedGame",
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "filename": meta_filename,
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
                "seed": getattr(self, "seed", None),
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
                # W4: full win snapshot for resume / post-game UI
                "win_result": self._json_safe(getattr(self, "win_result", None)),
                "win_fanfare_played": bool(getattr(self, "win_fanfare_played", False)),
                "post_game_ui": self._json_safe(
                    {
                        k: v
                        for k, v in dict(getattr(self, "post_game_ui", None) or {}).items()
                        if k not in {"rects"}
                    }
                )
                if isinstance(getattr(self, "post_game_ui", None), dict)
                else None,
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

        with open(write_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        print(f"✅ Saved game to {write_path}")
        return write_path

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
        # WP-R1: restore seed metadata (do not re-seed RNG on load — replay uses dice list later)
        try:
            raw_seed = game_data.get("seed", game_data.get("game_seed", None))
            if raw_seed is None or raw_seed == "":
                self.seed = None
                self.game_seed = None
            else:
                self.seed = int(raw_seed)
                self.game_seed = self.seed
        except Exception:
            self.seed = getattr(self, "seed", None)
            self.game_seed = getattr(self, "game_seed", self.seed)
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
        # W4: restore win snapshot (players resolved below for winner object)
        wr = game_data.get("win_result")
        self.win_result = dict(wr) if isinstance(wr, dict) else getattr(self, "win_result", None)
        try:
            self.win_fanfare_played = bool(game_data.get("win_fanfare_played", False))
        except Exception:
            self.win_fanfare_played = False
        pgui = game_data.get("post_game_ui")
        if isinstance(pgui, dict):
            self.post_game_ui = dict(pgui)
        elif not self.game_over:
            self.post_game_ui = None

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

        # Authoritative LR/LA from board + knight counts (overrides stale save flags)
        # Skip re-award noise when the game is already over (keep saved winner).
        if not bool(getattr(self, "game_over", False)):
            try:
                self.recompute_special_awards(
                    reason="after_load",
                    emit_events=False,
                    refresh_scoreboard=False,
                    include_largest_army=True,
                )
            except Exception:
                pass
        else:
            try:
                self.recompute_special_awards(
                    reason="after_load_game_over",
                    emit_events=False,
                    refresh_scoreboard=False,
                    include_largest_army=True,
                )
            except Exception:
                pass
            # W4: re-open post-game UI without replaying fanfare
            try:
                setattr(self, "win_fanfare_played", True)
                self.open_game_over_panel(win_result=getattr(self, "win_result", None))
            except Exception:
                pass

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
            try:
                player.recalculate_victory_points()
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
        self.current_best_action = None
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
        self.last_ai_knight_plan = None
        self.last_ai_knight_plan_pre_roll = None
        self.last_ai_knight_plan_post_roll = None
        self.last_ai_knight_plan_by_window = {}
        self.last_ai_knight_execute_result = None
        self.last_ai_tfr_plan = None
        self.last_ai_tfr_plan_pre_roll = None
        self.last_ai_tfr_plan_post_roll = None
        self.last_ai_tfr_plan_by_window = {}
        self.last_ai_tfr_execute_result = None
        self.last_ai_yop_plan = None
        self.last_ai_yop_plan_pre_roll = None
        self.last_ai_yop_plan_post_roll = None
        self.last_ai_yop_plan_by_window = {}
        self.last_ai_yop_execute_result = None
        self.last_ai_monopoly_plan = None
        self.last_ai_monopoly_plan_pre_roll = None
        self.last_ai_monopoly_plan_post_roll = None
        self.last_ai_monopoly_plan_by_window = {}
        self.last_ai_monopoly_execute_result = None
        self.last_ai_dcard_choice = None
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

        # Reachability maps: do not trust saved matrices / leftover freshness.
        # Gen2 reseeded after IP; Gen3 reseeds at begin_execution_turn — clear
        # the once-flag and dirty seats so the next Execution turn (or ensure_*)
        # rebuilds from the restored board.
        try:
            self._reachability_maps_seeded = False
            from core.player_reachability import mark_dirty, rebuild_all_maintained_seats

            for p in list(getattr(self, "players", None) or []):
                mark_dirty(p)
            if str(getattr(self, "phase", "") or "") == "Execution":
                self.last_reachability_seed = rebuild_all_maintained_seats(self)
                self._reachability_maps_seeded = True
        except Exception:
            self._reachability_maps_seeded = False

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

        # CS-3: rebuild STR history samples from FILENAME_CS (not in Saved_Game)
        cs3_result = None
        try:
            from core.strategy_history import reload_strategy_history_from_cs_log

            cs3_result = reload_strategy_history_from_cs_log(self)
        except Exception as exc:
            cs3_result = {"ok": False, "error": str(exc)}
            if MG:
                try:
                    with open(FILENAME_MG, "a", encoding="utf-8") as f:
                        f.write(f"game.py | load_game | CS-3 reload failed: {exc}\n")
                except Exception:
                    pass

        print(f"✅ Loaded saved game from {filename}")
        print(f"   • round={self.round}, turn={self.turn}, phase={self.phase}, state={self.state}")
        print(f"   • players={len(self.players)}, buildings={board_result.get('buildings_loaded', 0)}, roads={board_result.get('roads_loaded', 0)}")
        if isinstance(cs3_result, dict) and cs3_result.get("ok") and cs3_result.get("loaded_by_player"):
            try:
                bits = [
                    f"P{pid}:{n}"
                    for pid, n in sorted(
                        (cs3_result.get("loaded_by_player") or {}).items(),
                        key=lambda x: str(x[0]),
                    )
                    if n
                ]
                if bits:
                    print(f"   • STR history from CS log: {', '.join(bits)}")
            except Exception:
                pass

        return {
            "ok": True,
            "errors": [],
            "warnings": board_result.get("warnings", []),
            "filename": filename,
            "board": board_result,
            "cs_history": cs3_result,
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
