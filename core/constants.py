"""
Defines constants and utility functions for the Catan game.

This module centralizes game configuration, file paths, and utility functions used across
other modules to ensure consistency and ease of maintenance.

Key components:
    - File paths for logs and saved playboards.
    - Game configuration flags (e.g., human player, victory points).
    - Window dimensions and game data (e.g., resource costs, development cards).
    - Enumerations for resources.
    - Utility functions for calculations like intersection probability.

User-facing guide for flags (LOAD_GAME, CHECK_MODE, HP_ID, reserved constants, …)
and player seat / initial_placement_algorithm setup:

    See MANUAL.md in the project root.

Dependencies:
    - os: For file path handling.
    - typing: For type hints.
    - enum: For resource enumeration.
"""
import os
from typing import Dict, List, Tuple
from enum import Enum

# File Paths
SAVE_PATH: str = os.path.join(
    os.path.expanduser("~"), "Documents", "Projecten", "Python", "Catan_Gen3", "Logs"
)

"""Directory path for saving game logs and screenshots (outside the repo)."""

# Project root = parent of core/ (this file lives in core/constants.py)
_PROJECT_ROOT: str = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

SAVED_GAMES_DIR: str = os.path.join(_PROJECT_ROOT, "saved_games")
"""Directory for full Saved_Game_*.txt session snapshots (IP end, game over, CHECK_MODE EndRound)."""

SAVED_PHASE0_DIR: str = os.path.join(_PROJECT_ROOT, "saved_phase0_files")
"""Directory for Phase0_AI_Baseline_*.json dig-in captures (F8/F9 / auto-slow)."""

# Game Configuration Flags
FNFREQ: str = "N"
"""Flag for frequency logging ('Y' or 'N')."""

NUM_PLAYERS: int = 4
"""Number of players in the game."""

#HUMAN_PLAYER: bool = True
HUMAN_PLAYER: bool = False
"""Whether human players are participating."""

INIT_HP: bool = False
"""Whether human player initialization has occurred."""

#HP_ID: List[int] = [3]
HP_ID: List[int] = []
"""List of human player IDs (for future multi-human support)."""

VICTORY: int = 10
"""Victory points required to win."""

GAME_MAX_ROUND: int = 50
"""Maximum number of game rounds."""

GAMES_TO_PLAY: int = 1
"""Default batch size for headless GameManager / ``run_headless --games``.

CLI ``--games N`` overrides this. Phase A single-game is ``1``; Phase B sets N>1.
"""

DICEROLL_SET_TF: bool = False
"""Whether to use a fixed dice roll sequence."""

NAME_DR_FILE: str = "DiceRolls_4_Players_13_Mar_2025_00_22_10.txt"
"""File name for dice roll sequence."""

NO_GUI_AT_ALL_TF: bool = True
"""Headless lab mode: when True, no interactive GUI presentation and no sounds.

False → normal product path (GUI + audio).
True  → no window-driven UI and no sound playback (batch / run_headless).
"""

LOAD_PLAYBOARD: bool = False
"""Whether to load a saved playboard."""

SAVED_PLAYBOARD: str = "PlayBoard 08_Apr_2026_13_33_06.txt"
#SAVED_PLAYBOARD: str = "Playboard_LA_lab_WhOSh_07_Aug_2026.txt"
#SAVED_PLAYBOARD = "Playboard_LR_lab_WdB_07_Aug_2026.txt"
#SAVED_PLAYBOARD = "Playboard_LR_lab_mild_08_Aug_2026.txt"
"""File name for saved playboard."""

LOAD_GAME: bool = False
"""Cold boot only (main.py): if True, load SAVED_GAME and skip Initial Placement.

New Game / Settings end-session always start a fresh game and ignore this flag.
On missing/invalid file the app falls back to Initial Placement with a warning.
"""

#SAVED_GAME: str = "Saved_Game_31_Jul_2026_23_23_09_EndRound5.txt"
"""File name (or path) for a full saved game created by Game.save_game().

Bare basenames resolve under ``saved_games/`` first, then project root / cwd
(legacy), then SAVE_PATH. Absolute paths are used as-is.
"""

MG: bool = False
"""Detailed verbose logging for debugging and code analysis (Gen2-style MG text).

When True, may write high-volume diagnostic lines to FILENAME_MG / related sinks.
Not required for board re-play; use MGLOG for re-playable event timelines.
Primarily for debugging, code analysis, and deep digs — keep False in normal play.
"""

MGLOG: bool = True
"""Write/update MGlog event timeline so a game can be re-played in a GUI viewer.

When True (GUI or headless / NO_GUI_AT_ALL_TF either way), core mutations append
ordered CSV rows to FILENAME_MGLOG (or batch_dir/g00N/mglog.csv). A separate
GUI-only re-play script (no Strategy-Engine) reconstructs the game from
**playboard file + mglog.csv from the start (IP→end)** — not from a mid-game
Saved_Game. See docs/MGlog_implementation_plan.md.
"""

MGLOG_STATS_ON_GAME_OVER: bool = False
"""When True, Game Over Statistics prefer offline MGlog aggregation
(``collect_endgame_statistics_from_mglog``) if a usable mglog.csv exists;
falls back to live ledger stats on failure. Default False keeps current
ledger-based Game Over tables. Offline digs still use ``scripts/mglog_stats.py``.
See docs/MGlog_statistics_plan.md S8.
"""

# MEM_TWP removed: HP TwP rejection bag always persists (former MEM_TWP=True).
# See TurnDetails.clear_turn_details — does not reset list_of_TwP_rejected_by_HP.

CHECK_MODE: bool = False
"""When False: normal play UI — hide opponent RCard breakdowns,
AI-hand leaks in TwP counter, Execution Debug panel, DBG/steal-detail Events,
opponent unplayed DCard triplets, and opponent DCard buy types in Events.
Human always sees full own DCard triplets. When True: full dig-in / Check-Mode UI.
(Overview term: Check-Mode; former constant name was DEBUG_MODE.)"""

SIDESTEP_COMPARE: bool = False
"""Legacy PLN2 Side compare dumps (R-cadence). Default off — S142 uses a/b/c triggers."""

SIDESTEP_S142_TRIGGERS: bool = False
"""When True, run S142 compute+log on a/b/c events (own public VP/LA/LR; deferred opp R/S/C)."""

SIDESTEP_S142_DRIVE: bool = False
"""Headless lab: on S142 fire, adopt s142_way_id into sticky (implies triggers).
Default False — product SE unchanged. Enable via ``--arm s142-drive``."""

SIDESTEP_REQUIRE_CONFIDENCE: bool = True
"""If True, Sidestep scales RP by an H-dependent confidence factor after Raw walk:
full midpoint (1+1/conf)/2 at ~10 dice rolls (e.g. 8.5→9.25), tapering to 1.0
by ~60 rolls (long horizon → little/no adjust). Side = second walk; Raw = first.
Binomial Conf column is informational only."""


# Expected-Hand (EH) data (algorithm_id=5)
ALGORITHM_ID_EXPECTED_HAND: int = 5
"""Initial placement algorithm id for Expected-Hand feasibility."""

EXPECTED_HAND_MAX_TURNS: float = 60.0
"""Maximum own turns searched by EH when estimating turns-to-afford."""

EXPECTED_HAND_STEP: float = 0.25
"""Search resolution in own turns for EH timing estimates."""

EXPECTED_HAND_CONFIDENCE_TARGET: float = 0.85
"""Optional confidence threshold for EH if confidence-gated timing is enabled."""

EXPECTED_HAND_REQUIRE_CONFIDENCE: bool = False
"""If True, EH only accepts a candidate once both affordability and confidence target are met."""

EXPECTED_HAND_ROLLS_PER_PLAYER_TURN: int = NUM_PLAYERS
"""Expected global dice rolls per own turn. In a 4-player game this is normally 4."""

EXPECTED_HAND_TARGET_EXTRA_ROADS: int = 1
"""EH initial-placement target is next settlement plus this many roads."""

EXPECTED_HAND_CONTINUOUS_TRADING: bool = True
"""Allow EH to use continuous expected surplus divided by trade rate as a timing heuristic."""

EXPECTED_HAND_USE_PORTS: bool = True
"""Allow EH to use current candidate ports when estimating trade rates."""

EXPECTED_HAND_STORE_PLAYER_DEBUG: bool = True
"""Store EH candidate diagnostics on the player object for later inspection/logging."""

EXPECTED_HAND_DEBUG_TOP_N: int = 20
"""Number of EH-ranked candidates written to MG debug logging."""

# ── Phase C2 / product: explicit Victory-Way / L2 reassess ───────────────────
# Product (new games): AI seats [2, [4, 4]] (setback OR every 4 own turns);
# human seats [0] (sticky + closed-table L2 only). Applied by is_human in
# core/explicit_142_recalc.apply_product_defaults_to_players.
# Lab sticky baseline: run_headless --arm control (all [0]).
# Mixed list: ints and [4, n]. Codes: 0=none 1=vp 2=setback 3=hard 4=[4,n] 5=milestones
# CLI: --explicit-recalc / --arm  (MANUAL.md Phase C2)

EXPLICIT_RECALC_SETBACK_THR: float = 1.0
"""ETA rise (own turns) to fire code 2 (on_eta_setback)."""

EXPLICIT_RECALC_EVERY_N_DEFAULT: int = 2
"""Default n when code 4 is bare ``4`` (prefer ``[4, n]`` explicitly)."""

EXPLICIT_RECALC_MILESTONE_VPS: tuple = (2, 4, 6, 8)
"""VP milestones for code 5."""

EXPLICIT_142_RECALC_PRODUCT_AI: list = [2, [4, 4]]
"""Default explicit_142_recalc for AI seats (setback + every 4 own turns).

WP3 codes 6/7 are **not** included (opt-in via arm / seat map / LAB_WP3).
"""

EXPLICIT_142_RECALC_PRODUCT_HUMAN: list = [0]
"""Humans: no explicit extra L2 (sticky + P1–P3 closed-table gates only)."""

EXPLICIT_142_RECALC_LAB_WP3: list = [2, [4, 4], 6, 7]
"""Lab arm: product AI + sticky-target threat (6) + LR tooling (7)."""

EXPLICIT_L2_CODE6_MAX_PER_GAME: int = 4
"""Max code-6 (threat) latches per seat per game."""

EXPLICIT_L2_CODE7_MAX_PER_GAME: int = 4
"""Max code-7 (LR tooling) latches per seat per game."""

EXPLICIT_L2_WP3_MAX_PER_GAME: int = 6
"""Max combined code 6+7 latches per seat per game."""

EXPLICIT_142_RECALC_BY_SEAT: dict = {
    1: [2, [4, 4]],
    2: [2, [4, 4]],
    3: [2, [4, 4]],
    4: [2, [4, 4]],
}
"""Documentation / all-AI template seat map (same as product AI).

Live Game init uses **is_human** via ``apply_product_defaults_to_players`` when
no CLI seat map is passed — humans get ``EXPLICIT_142_RECALC_PRODUCT_HUMAN``.
CLI ``--arm`` / ``--explicit-recalc`` still override by seat id.
"""

EXPLICIT_WAY_PICK: str = "sticky"
"""On explicit L2: ``sticky`` keeps sticky + min-ETA-gain (product default).

Use ``best`` for lab explore (always adopt rank-1 way on explicit L2).
"""

LOG_WAY_COMPARE: bool = True
"""Phase C2 WP-R4: write WayReassessCompare JSONL on L2 (lab default).

Seats with non-zero ``explicit_142_recalc`` always log regardless.
Batch path: ``batch_dir/way_reassess.jsonl`` via GameManager.
"""

LOG_LA_LR_PROBE: bool = True
"""Phase L WP-L1: god-view LA/LR race probe JSONL (lab default on).

Batch path: ``batch_dir/la_lr_probe.jsonl`` via GameManager.
Does not change Strategy-Engine policy (observe only).
"""

LA_SOFT_BIAS_MODE: str = "off"
"""Lab soft bias toward LA Victory-Ways + knight BA preference.

Values: ``off`` | ``early`` | ``mid`` | ``late``
  - early: bias from Execution start
  - mid: when max VP >= 4 or round >= 8
  - late: when max VP >= 6 or round >= 12
CLI: ``run_headless --la-soft-bias early`` overrides per run.
Does not ban non-LA ways (soft rank/ETA boost + knight hold→play tip).
"""

# WP2: Victory-Way must match board structure + held specials (see strategy_board_fit)
WAY_BOARD_FIT_MODE: str = "filter_and_force_switch"
"""Board-fit filter for preferred Victory-Way vs live pieces/specials.

Values:
  - ``off`` — historical: no structure/specials hold filter
  - ``filter`` — demote unfit ways in L2 portfolio (rank ∞); sticky not auto-cleared
  - ``filter_and_force_switch`` — filter + clear sticky / adopt best fit when sticky unfit
    (also on own LA/LR gain when sticky way omits that special)

Default product intent: ``filter_and_force_switch`` (operator lock improving_SE_v3).
Set ``off`` for A/B control arms.
"""

# WP6: Longest Road recompute scoping (see lr_recompute_opt / game.recompute_longest_road)
LR_RECOMPUTE_OPT: str = "full"
"""Live Longest Road recompute policy after board mutations.

Values:
  - ``full`` — always recompute continuous length for every seat (default; proven).
  - ``threshold`` — scope DFS: settlement → full; road/TFR → actor only; city → cache.

Product default stays ``full`` until threshold is lab-proven. Set ``threshold`` for
perf A/B. Never skips settlement recompute (opponent path breaks).
"""

# WP5: hybrid PLAN/WHY2 snapshot on L2 (see strategy_plan_snapshot)
PLAN_SNAPSHOT: str = "on"
"""Write dig PLAN/WHY2 snapshot fields on L2/explore strategy refresh.

Values:
  - ``on`` — sample plan_settles/cities/knight/TFR/LA-LR packages into CS
  - ``off`` — no plan snapshot (dig PLAN stays empty / note)

Hand-only L0 never writes settlement ETA catalog (cost). Dig Show reads CS.
"""

# WP4: soft knight vs TFR chooser bias (see specials_race_plans.prefer_knight_before_tfr)
KNIGHT_TFR_POLICY: str = "rules_v1"
"""Knight-before-TFR soft policy for DCard chooser + dig PLAN.

Values:
  - ``off`` — no WP4 score bump/demote (existing S-LR/S-LA / early TFR logic only)
  - ``rules_v1`` — prefer_knight True/False from LA/LR race plans (improving_SE_v3 a–g)

Default product: ``rules_v1``. Soft bias only; never hard-blocks legal plays.
"""

# ---------------------------------------------------------------------------
# Phase L FT6 — LA give-up → L2 (lab freeze; Strategy-Engine wiring = L6 later)
# Source of truth details: core/la_giveup_config.py, docs/PhaseL_LA_theta_lock.md
# Domain A only: Playboard_LA_lab_WhOSh_07_Aug_2026.txt (+ product sticky).
# ---------------------------------------------------------------------------
LA_GIVEUP_L2_ENABLED: bool = True
"""When True, SE fires god-view LA give-up → clear ambition + L2 (L6).

Lab default **True** for Domain A A/B batches (Wh/O/Sh lab board).
Set **False** for product / standard-map runs until Domain B is re-fit.
"""

LA_GIVEUP_PROFILE: str = "safe"
"""Named profile: ``safe`` (θ=0.6) | ``balanced`` (0.5) | ``aggressive`` (0.4)."""

LA_GIVEUP_THETA: float = 0.6
"""Hopeless-score threshold for give-up fire. Override profile if set intentionally.

Freeze defaults: safe=0.6, balanced=0.5, aggressive=0.4.
"""

LA_GIVEUP_DWELL: int = 1
"""Consecutive own-turn needs samples with score≥θ before fire (FT5: D=1)."""

LA_GIVEUP_CLAIM_WINDOW_K: int = 4
"""Offline FGU window (own-turn samples after fire). Not a live SE timer."""

LA_GIVEUP_LATCH_FIRST: bool = True
"""Latch first fire per needs episode (do not multi-fire on re-cross)."""

# ---------------------------------------------------------------------------
# Phase L FT6 — LR give-up → L2 (Domain C LR lab freeze + SE wiring)
# Source: core/lr_giveup_config.py, docs/PhaseL_LR_theta_lock.md
# Domain C: Playboard_LR_lab_WdB_07_Aug_2026.txt (+ product sticky).
# ---------------------------------------------------------------------------
LR_GIVEUP_L2_ENABLED: bool = True
"""When True, SE fires god-view LR give-up → clear ambition + L2 (L6).

Lab default **True** for Domain C (Wd/B lab board). Set **False** on LA lab
or standard product maps unless you intentionally want dual specials.
"""

LR_GIVEUP_PROFILE: str = "safe"
"""Named profile: ``safe`` (θ=0.75) | ``balanced`` (0.65) | ``aggressive`` (0.55)."""

LR_GIVEUP_THETA: float = 0.75
"""Hopeless-score threshold for LR give-up fire."""

LR_GIVEUP_DWELL: int = 1
"""Consecutive own-turn needs samples with score≥θ before fire (FT5 LR: D=1)."""

LR_GIVEUP_CLAIM_WINDOW_K: int = 4
"""Offline FGU window (own-turn samples after fire). Not a live SE timer."""

LR_GIVEUP_LATCH_FIRST: bool = True
"""Latch first fire per needs episode (LR thrash high without latch)."""

# ---------------------------------------------------------------------------
# Phase L give-up escape (WP0–WP2): specials-dead episode + portfolio filter
# See docs/PhaseL_giveup_escape_plan.md
# ---------------------------------------------------------------------------
GIVEUP_ESCAPE_ENABLED: bool = True
"""When True, after LA/LR give-up fire set a specials-dead episode and filter
portfolio ways that still need the dead special (hard filter; soft demote if
empty). Lab default **True**. Set **False** to restore pre-escape re-lock
behavior (smoke A/B control). Does not change θ / dwell freezes.
"""

GIVEUP_FORCE_DIVERT: bool = True
"""WP3: when escape is on and a specials-dead episode is active, force S5.5
divert with episode kill_la/kill_lr (even if S5.5 assess is still soft). Also
gates sticky from re-locking dead-special ways. Requires GIVEUP_ESCAPE_ENABLED.
"""

# ---------------------------------------------------------------------------
# Phase L partial Victory-Way salvage (S0 frozen; S1+ not wired)
# Spec: docs/PhaseL_partial_way_salvage_plan.md
# ---------------------------------------------------------------------------
GIVEUP_SALVAGE_PARTIAL: bool = False
"""When True (S3+), after dead components rank T1 non-dead-component ways, else
T2 residual (strip dead components, min own-turns).

Default **False**. S1 helpers always available; S2 T1 eval expand runs when this
**or** ``GIVEUP_ESCAPE_ENABLED`` is True and a specials-dead episode is active.
Fair-play: never use god-view DCard-deck VP counts for VP-DCard death.
"""

GIVEUP_SALVAGE_T1_EXPAND_N: int = 6
"""S2: max non-LR/non-LA Victory-Ways injected into L2 portfolio eval when
specials-dead episode has kill_lr / kill_la. 0 disables expand.
"""

USE_NUMPY_EH: bool = True
"""P5: use NumPy Expected-Hand kernel when available; falls back to pure Python."""

# Window Dimensions
WIN_WIDTH: int = 800
"""Game window width in pixels."""

WIN_HEIGHT: int = 600
"""Game window height in pixels."""


# Game Data
LIST_OF_DCARDS: List[str] = ["knight"] * 14 + ["victory_point"] * 5 + ["two_free_roads"] * 2 + ["year_of_plenty"] * 2 + ["monopoly"] * 2
"""List of development cards in the deck."""

RCARDS_FOR_CITY: List[int] = [2, 3, 0, 0, 0]
"""Resources needed for a city: [grain, ore, wood, brick, sheep]."""

RCARDS_FOR_SETTLEMENT: List[int] = [1, 0, 1, 1, 1]
"""Resources needed for a settlement: [grain, ore, wood, brick, sheep]."""

RCARDS_FOR_ROAD: List[int] = [0, 0, 1, 1, 0]
"""Resources needed for a road: [grain, ore, wood, brick, sheep]."""

RCARDS_FOR_DCARD: List[int] = [1, 1, 0, 0, 1]
"""Resources needed for a development card: [grain, ore, wood, brick, sheep]."""


# Resource Enumeration
class ResourceCard(Enum):
    """Enumeration of resource card types in Catan."""
   
    WHEAT = "Wheat"
    ORE = "Ore"
    WOOD = "Wood"
    BRICK = "Brick"
    SHEEP = "Sheep"


# Order used for lists, indices, dashboards, etc.
RESOURCE_ORDER: List[ResourceCard] = [
    ResourceCard.WHEAT,
    ResourceCard.ORE,
    ResourceCard.WOOD,
    ResourceCard.BRICK,
    ResourceCard.SHEEP,
]


# Tile terrain name -> resource card produced (used for production, initial placement, robber logic, etc.)
TERRAIN_TO_RESOURCE: Dict[str, ResourceCard] = {
    "Field":    ResourceCard.WHEAT,
    "Mountain": ResourceCard.ORE,
    "Forest":   ResourceCard.WOOD,
    "Hill":     ResourceCard.BRICK,
    "Pasture":  ResourceCard.SHEEP,
    # "Desert":   None    # ← no need to map (already filtered out)
}


# Optional: reverse mapping (useful for debugging / logging / UI)
RESOURCE_TO_TERRAIN: Dict[ResourceCard, str] = {
    v: k for k, v in TERRAIN_TO_RESOURCE.items()
}


# File Names
FILENAME_HELP: str = "Catan01Aug2026_v1"
"""Base filename for logs."""

FILENAME: str = f"{FILENAME_HELP}.txt"
"""Main log file."""

FILENAME_CS: str = f"{FILENAME_HELP}_CS.txt"
"""Change strategy log file."""

FILENAME_MG: str = f"{FILENAME_HELP}_MG.txt"
"""Path for detailed MG debug text log when MG=True (not the re-play timeline)."""

FILENAME_MG2: str = f"{FILENAME_HELP}_MG2.txt"
"""Secondary MG debug log file (legacy Gen2 naming)."""

FILENAME_MGLOG: str = f"{FILENAME_HELP}_MGlog.csv"
"""Re-playable MGlog event timeline (CSV) when MGLOG=True.

Headless batches should prefer per-game files under batch_dir/g00N/ so game 67
of n=100 is addressable alone. See docs/MGlog_implementation_plan.md.
"""

FILENAME_MGLOG2: str = f"{FILENAME_HELP}_MGlog2.csv"
"""Optional secondary MGlog export (legacy Gen2 MGlog2-style columns); v0 may use one CSV only."""

FILENAME_SUM: str = f"{FILENAME_HELP}_Sum.txt"
"""Summary log file."""

FILENAME_SPEC: str = f"{FILENAME_HELP}_Spec.txt"
"""Special log file."""

FILENAME_SPEC2: str = f"{FILENAME_HELP}_Spec2.txt"
"""Secondary special log file."""

FILENAME_LOG: str = f"{FILENAME_HELP}_Log.txt"
"""General log file."""

FILENAME_FREQ: str = f"{FILENAME_HELP}_Freq.txt"
"""Frequency log file."""

FILENAME_MAPPING: str = f"{FILENAME_HELP}_Mapping.txt"
"""Mapping log for distance and path maps."""

FILENAME_MINDMAP: str = f"{FILENAME_HELP}_MindMap.txt"
"""Mind map log file."""

FILENAME_MINDMAP2: str = f"{FILENAME_HELP}_MindMap2.txt"
"""Secondary mind map log file."""

FILENAME_FOUNDPATH: str = f"{FILENAME_HELP}_FoundPath.txt"
"""Found path log file."""

FILENAME_DATAMAP: str = f"{FILENAME_HELP}_DataMap.txt"
"""Data map log file."""


class PlayerColor(Enum):
    """Enumeration for player color mappings in game logic."""
    BLUE = (1, "Blue", (0, 0, 255))
    RED = (2, "Red", (255, 0, 0))
    WHITE = (3, "White", (255, 255, 255))
    ORANGE = (4, "Orange", (255, 165, 0))

    def __init__(self, code: int, color_name: str, rgb: Tuple[int, int, int]) -> None:
        """Initialize a PlayerColor instance.

        Args:
            code: Unique player ID (1-4).
            color_name: Name of the color (e.g., 'Blue').
            rgb: RGB tuple for the color.
        """
        self.code = code
        self.color_name = color_name
        self.rgb = rgb

REVERSE_COLOR_MAPPING: Dict[str, str] = {
    "Blue": "Orange",
    "Red": "White",
    "White": "Red",
    "Orange": "Blue"
}
"""Dictionary mapping player colors to their opposites for game logic."""


# Planning Phase
# BLOCKED_EMPTY: float = 0.2
BLOCKED_WEIGHT = 0.1
TOP_N = 15


# Utility Functions
def intersection_probability(dice_roll: int) -> int:
    """Calculate the probability of a dice roll for an intersection.

    Args:
        dice_roll: The sum of two dice (2-12).

    Returns:
        int: The probability value (dots) for the dice roll.

    Examples:
        >>> intersection_probability(6)
        5
        >>> intersection_probability(7)
        6
    """
    prob_map: Dict[int, int] = {2: 1, 12: 1, 3: 2, 11: 2, 4: 3, 10: 3, 5: 4, 9: 4, 6: 5, 8: 5, 7: 6}
    return prob_map.get(dice_roll, 0)


def get_rcard_costs() -> Dict[str, Dict[ResourceCard, int]]:
    """Generate a dictionary of resource costs for building actions.

    Args:
        None

    Returns:
        Dict[str, Dict[ResourceCard, int]]: A dictionary mapping building types to their resource costs.

    Examples:
        >>> costs = get_resource_costs()
        >>> costs["settlement"][ResourceCard.GRAIN]
        1
    """
    return {
        "settlement": {
            ResourceCard.WHEAT: RCARDS_FOR_SETTLEMENT[0],
            ResourceCard.ORE: RCARDS_FOR_SETTLEMENT[1],
            ResourceCard.WOOD: RCARDS_FOR_SETTLEMENT[2],
            ResourceCard.BRICK: RCARDS_FOR_SETTLEMENT[3],
            ResourceCard.SHEEP: RCARDS_FOR_SETTLEMENT[4]
        },
        "city": {
            ResourceCard.WHEAT: RCARDS_FOR_CITY[0],
            ResourceCard.ORE: RCARDS_FOR_CITY[1],
            ResourceCard.WOOD: RCARDS_FOR_CITY[2],
            ResourceCard.BRICK: RCARDS_FOR_CITY[3],
            ResourceCard.SHEEP: RCARDS_FOR_CITY[4]
        },
        "road": {
            ResourceCard.WHEAT: RCARDS_FOR_ROAD[0],
            ResourceCard.ORE: RCARDS_FOR_ROAD[1],
            ResourceCard.WOOD: RCARDS_FOR_ROAD[2],
            ResourceCard.BRICK: RCARDS_FOR_ROAD[3],
            ResourceCard.SHEEP: RCARDS_FOR_ROAD[4]
        },
        "development_card": {
            ResourceCard.WHEAT: RCARDS_FOR_DCARD[0],
            ResourceCard.ORE: RCARDS_FOR_DCARD[1],
            ResourceCard.WOOD: RCARDS_FOR_DCARD[2],
            ResourceCard.BRICK: RCARDS_FOR_DCARD[3],
            ResourceCard.SHEEP: RCARDS_FOR_DCARD[4]
        }
    }


# Cached resource costs
COSTS: Dict[str, Dict[ResourceCard, int]] = get_rcard_costs()
"""Cached dictionary of resource costs for building actions."""