"""
Defines the Player class for the Catan game.

This module manages player state, including resource cards, structures (settlements, roads, cities),
development cards, and game statistics. It supports both human and AI players, with attributes
initialized for the initial empty board state and methods for game interactions like building
and trading.

Key components:
    - Player: Represents a player with ID, color, resources, and game statistics.
    - Methods: Handle resource management, building, trade rate updates, and debugging.

Dependencies:
    - typing: For type hints.
    - math: For trade ratio calculations.
    - gui.gui_constants: For player colors.
    - core.constants: For resource and cost constants.
    - core.board: For board interactions (forward reference).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any, Optional
import math
from core.constants import PlayerColor
from core.constants import ResourceCard, COSTS, FNFREQ, FILENAME_FREQ, MG, FILENAME_MG
from core.board import Board

@dataclass
class Outlook:
    """Compat with Gen2 v045 Outlook for summary (9 char flags B/Y/A/N/X for R1/R2/R3/S1/S2/C1/C2/NewS1/NewS2),
    specific next targets, distances, risks, prios etc. + modern targets list for clarity.
    Mutated by outlook_logic.update_outlook / after_ etc.
    """
    summary: str = "BBBBBBBBB"
    next_roads: List = field(default_factory=list)
    next_road1: List = field(default_factory=list)
    ratio_road: str = "B"
    next_road2: List = field(default_factory=list)
    next_road3: List = field(default_factory=list)
    next_settlements: List = field(default_factory=list)
    # Target-specific next-settlement records enriched with EH timing.
    # Each record uses JSON-friendly lists and includes expected_turns when calculated.
    next_settlement_plans: List[Dict] = field(default_factory=list)
    next_settlement1: List = field(default_factory=list)
    next_settlement2: List = field(default_factory=list)
    next_settlement_to_city1: List = field(default_factory=list)
    next_settlement_to_city2: List = field(default_factory=list)
    new_settlements: List = field(default_factory=list)
    # Target-specific new-settlement path/build-plan records.
    # Each record uses JSON-friendly lists:
    # {
    #     "intersection_id": 51,
    #     "path": [[30, 41], [41, 52], [52, 51]],        # directed road_in_path steps
    #     "roads_to_build": [[30, 41], [41, 52], [51, 52]],  # canonical road_id lists
    #     "distance": 3,
    # }
    new_settlement_paths: List[Dict] = field(default_factory=list)
    new_settlement1: List = field(default_factory=list)
    distance_new_settlement1: int = 99
    new_settlement2: List = field(default_factory=list)
    distance_new_settlement2: int = 99
    next_settlement_or_new_settlement: int = 0
    settlement_to_city_or_new_settlement: int = 0
    new_settlement_for_defence: List = field(default_factory=list)
    overall_prio: List = field(default_factory=lambda: [99])
    number_of_unique_roads_to_build: int = 99
    risk_for_next_settlement: List = field(default_factory=lambda: ["None", "None"])
    risk_for_new_settlement: List = field(default_factory=lambda: ["None", "None", "None"])
    path_to_longest_road: List = field(default_factory=list)
    table_TWcbo: List = field(default_factory=list)
    # modern extension (recommended for new code; list of target dicts or simple tuples)
    targets: List[Dict] = field(default_factory=list)

class Player:
    """Represents a player in the Catan game."""

    def __init__(self, id_: int, color: str, sequence: int, 
                 is_human: bool = False, 
                 initial_placement_algorithm: int = 1,
                 human_like_placement: bool = True) -> None:
        """Initialize a Player.
        Args:
            id_: Unique player ID (e.g., 1, 2, 3, or 4).
            color: Player color (e.g., 'Blue', 'Red', 'White', 'Orange').
            sequence: Turn order (1-4).
            is_human: Whether the player is human (True) or AI (False, default).
        Raises:
            ValueError: If the provided color is not a valid PlayerColor.
        """
        valid_colors = [pc.color_name for pc in PlayerColor]
        if color not in valid_colors:
            raise ValueError(f"Invalid color: {color}. Must be one of {valid_colors}")
        self.game = None
        self.color = color
        self.color2 = color
        self.id = id_
        self.is_human = is_human  # Added
        self.gameover_tf = False
        self.sequence = sequence
        self.initial_placement_algorithm = initial_placement_algorithm
        self.human_like_placement = human_like_placement
        self.points = 0
        self.longest_route_tf = False
        self.size_longest_route = 0
        self.structure_longest_route: List[Tuple[int, int]] = []
        self.number_of_clusters = 0
        self.structure_of_clusters: List = []
        self.largest_army_tf = False
        self.size_largest_army = 0
        self.number_of_rcards = 0
        self.number_of_dcards = 0
        self.rcards: Dict[ResourceCard, int] = {rc: 0 for rc in ResourceCard}
        self.dcard_summary = [
            ["victory_point", 0, 0, 0],
            ["knight", 0, 0, 0],
            ["two_free_roads", 0, 0, 0],
            ["year_of_plenty", 0, 0, 0],
            ["monopoly", 0, 0, 0]
        ]
        self.development_cards: List[str] = []
        self.victory_points: int = 0
        self.settlements: List[int] = []
        self.cities: List[int] = []
        self.roads: List[Tuple[int, int]] = []
        self.turn_details_resource_production = [0, 0, 0, 0, 0, 0]
        self.turn_details_resource_production_robber = [0, 0, 0, 0, 0, 0]
        self.turn_details_buy = [0, 0, 0, 0, 0, 0]
        self.turn_details_steal = [0, 0, 0, 0, 0, 0]
        self.turn_details_discard = [0, 0, 0, 0, 0, 0]
        self.turn_details_TwP = [0, 0, 0, 0, 0, 0]
        self.turn_details_last_TwPdeal = [0, 0, 0, 0, 0, 0]
        self.turn_details_TwB = [0, 0, 0, 0, 0, 0]
        self.turn_details_dcard = [0, 0, 0, 0, 0, 0]
        # S7e lifetime Activity counters (persisted; endgame Statistics)
        self.stats_twp_proposed: int = 0  # offers presented / initiated
        self.stats_twp_accepted: int = 0  # completed TwP deals this player was in
        self.stats_dcards_bought: int = 0  # development cards bought from bank
        # Bank trade rates in fixed order: [Wheat, Ore, Wood, Brick, Sheep].
        self.trade_rates: List[int] = [4, 4, 4, 4, 4]
        self.port_access: Dict[str, bool] = {
            "3:1": False,
            "2:1 Wheat": False,
            "2:1 Ore": False,
            "2:1 Wood": False,
            "2:1 Brick": False,
            "2:1 Sheep": False
        }
        self.last_action: str = "None"

        # Execution / outlook maps & powers (from Gen2 player_v045 for strategy/outlook; 67 TWs)
        self.pips: List[int] = [0, 0, 0, 0, 0]  # G O W B Wo probs
        self.buying_power: List[float] = [0.0, 0.0, 0.0, 0.0]  # road/sett/city/dcard
        self.trading_power: List[float] = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.new_settlement_as_primary_strategy: List = []
        self.primary_strategy: int = 0  # 0 none, 2 sett, 8 mono, 9 quick
        self.resource_production: List = []
        self.strategy: List = []
        self.outlook: List[Outlook] = [Outlook()]  # list of Outlook (compat + modern targets)

        # Player-level strategic direction, produced by action_planner Stage 4E.
        # This is intentionally NOT stored in Outlook: Outlook describes board
        # targets; strategic_direction describes which 142-way victory strategy
        # this player is currently trying to pursue.
        self.strategic_direction: Optional[Dict[str, Any]] = None
        self.last_strategic_direction: Optional[Dict[str, Any]] = None
        self.strategic_direction_history: List[Dict[str, Any]] = []
        # PR-D / CS-3: compact STR samples (runtime; rebuilt from FILENAME_CS on load)
        self.strategy_history_samples: List[Dict[str, Any]] = []
        # S1 sticky target/route commitment (way + rec target + roads_to_build)
        self.sticky_commitment: Optional[Dict[str, Any]] = None
        # S1 batched strategy re-rank flag (opponent settle/city; own milestones)
        self.strategy_recalc_flag: Optional[Dict[str, Any]] = None
        self.force_strategy_recalc: bool = False
        # S5b: one-shot LA/LR way kill latch + last kill payload
        self.way_kill_latch: Optional[Dict[str, Any]] = None
        self.last_way_kill: Optional[Dict[str, Any]] = None
        # S5.5-C: once-per-(round, turn, player) specials divert cadence latch
        self.specials_divert_checked_turn: Optional[List[Any]] = None
        self.last_specials_divert: Optional[Dict[str, Any]] = None
        self.last_specials_assess: Optional[Dict[str, Any]] = None

        # Strategy instances (Gen2 style) populated by core/strategy.initialize or on first update_strategy
        # self.strategy.append(Strategy(...))  # done post-init to avoid import cycles
        w = h = 67
        self.distance_map = [[99 for _ in range(w)] for _ in range(h)]
        self.min_distance_map_for_targeted_TWs: List = [99] * h
        self.path_map = [[[] for _ in range(w)] for _ in range(h)]
        self.pathlength_map = [[99 for _ in range(w)] for _ in range(h)]
        self.min_pathlength_map_for_targeted_TWs: List = [99] * h
        self.real_distance_map = [[99 for _ in range(w)] for _ in range(h)]
        self.min_real_distance_map_for_targeted_TWs: List = [99] * h

    def add_rcard(self, resource: ResourceCard, amount: int) -> None:
        """Add resource cards to the player's hand.

        Args:
            resource: The resource card type to add (e.g., ResourceCard.WHEAT).
            amount: The number of resource cards to add.

        Examples:
            >>> player.add_rcard(ResourceCard.WOOD, 2)
        """
        self.rcards[resource] = self.rcards.get(resource, 0) + amount
        self.number_of_rcards = sum(self.rcards.get(rc, 0) for rc in ResourceCard)

    def can_afford(self, structure: str) -> bool:
        """Check if the player has enough resource cards to build a structure.

        Args:
            structure: The structure type ('settlement', 'city', 'road', 'development_card').

        Returns:
            bool: True if the player has enough resource cards, False otherwise.
        """
        costs = COSTS.get(structure, {})
        return all(self.rcards.get(res, 0) >= amt for res, amt in costs.items())

    def build_structure(self, structure: str, location: int | Tuple[int, int], board: 'Board') -> bool:
        """Build a structure on the board and update player state.

        Now correctly updates self.settlements and self.cities (including settlement → city upgrade).
        """
        if not self.can_afford(structure):
            return False

        if structure in ["settlement", "city"]:
            if not board.can_build_intersection(location):
                return False

            # Let the board handle the visual / tile state
            board.occupy_intersection(location, structure.capitalize(), self.color)

            if structure == "settlement":
                # First settlement
                if location not in self.settlements:
                    self.settlements.append(location)
                self.victory_points += 1

            elif structure == "city":
                # Upgrade: remove from settlements, add to cities
                if location in self.settlements:
                    self.settlements.remove(location)
                if location not in self.cities:
                    self.cities.append(location)
                self.victory_points += 2   # city gives +2 total (replaces the +1 from settlement)

            self.points = self.victory_points

        elif structure == "road":
            if not board.can_build_road_for_color_tf(list(location), self.color):
                return False
            board.occupy_road(list(location), "Road", self.color)
            self.roads.append(location)

        # Deduct resources
        for rc, amt in COSTS[structure].items():
            self.rcards[rc] -= amt

        self.number_of_rcards = sum(self.rcards.get(rc, 0) for rc in ResourceCard)
        self.last_action = f"Built {structure} at {location}"

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"player.py | build_structure | {structure} at {location} by player {self.id} "
                        f"(settlements: {len(self.settlements)}, cities: {len(self.cities)})\n")

        return True

    def recalculate_victory_points(self) -> int:
        """
        Recalculate victory points from the player's actual current state.

        Settlement = 1 VP
        City       = 2 VP
        Longest road = 2 VP
        Largest army = 2 VP
        Victory-point development card = 1 VP each (held or revealed)
        """
        try:
            from core.victory import vp_breakdown

            br = vp_breakdown(self)
            total = int(br.get("total") or 0)
            self.victory_points = total
            self.points = total
            try:
                self.victory_points_dcard = int(br.get("vp_cards") or 0)
            except Exception:
                pass
            return total
        except Exception:
            pass

        settlement_points = len(getattr(self, "settlements", []))
        city_points = 2 * len(getattr(self, "cities", []))

        dcard_vp = 0
        try:
            from core.victory import count_vp_development_cards

            dcard_vp = int(count_vp_development_cards(self))
        except Exception:
            for row in getattr(self, "dcard_summary", []):
                if row and row[0] == "victory_point":
                    try:
                        dcard_vp += int(row[3])
                    except (TypeError, ValueError, IndexError):
                        pass

        longest_road_points = 2 if getattr(self, "longest_route_tf", False) else 0
        largest_army_points = 2 if getattr(self, "largest_army_tf", False) else 0

        total = (
            settlement_points
            + city_points
            + dcard_vp
            + longest_road_points
            + largest_army_points
        )

        self.victory_points = total
        self.points = total
        return total
    
    def _clean_trade_rates_vector(self, values: Any = None) -> List[int]:
        """Return trade rates in fixed [Wheat, Ore, Wood, Brick, Sheep] order.

        Older saved games used a dictionary with keys like "grain" and
        "lumber".  Runtime code now uses a simple 5-item vector, but this
        helper keeps older saves and hot-swapped objects safe.
        """
        if values is None:
            values = getattr(self, "trade_rates", [4, 4, 4, 4, 4])

        if isinstance(values, (list, tuple)):
            out: List[int] = []
            for value in list(values)[:5]:
                try:
                    rate = int(value or 4)
                except Exception:
                    rate = 4
                out.append(rate if rate > 0 else 4)
            while len(out) < 5:
                out.append(4)
            return out

        if isinstance(values, dict):
            aliases = [
                (ResourceCard.WHEAT, "Wheat", "wheat", "grain"),
                (ResourceCard.ORE, "Ore", "ore"),
                (ResourceCard.WOOD, "Wood", "wood", "lumber"),
                (ResourceCard.BRICK, "Brick", "brick"),
                (ResourceCard.SHEEP, "Sheep", "sheep", "wool"),
            ]
            out = []
            for keys in aliases:
                value = None
                for key in keys:
                    if key in values:
                        value = values[key]
                        break
                if value is None:
                    for raw_key, raw_value in values.items():
                        raw_text = str(getattr(raw_key, "value", raw_key)).strip().lower()
                        if raw_text in {str(k).strip().lower() for k in keys}:
                            value = raw_value
                            break
                try:
                    rate = int(value or 4)
                except Exception:
                    rate = 4
                out.append(rate if rate > 0 else 4)
            return out

        return [4, 4, 4, 4, 4]

    def update_trade_rates(self, board) -> None:
        """Update this player's bank trade rates from owned port intersections.

        The only runtime representation is a 5-item vector in this order:
        [Wheat, Ore, Wood, Brick, Sheep]..
        """
        rates = [4, 4, 4, 4, 4]

        # Keep the older port_access diagnostic dictionary in sync, but do not
        # introduce any additional Player port-list state.
        self.port_access = {
            "3:1": False,
            "2:1 Wheat": False,
            "2:1 Ore": False,
            "2:1 Wood": False,
            "2:1 Brick": False,
            "2:1 Sheep": False,
        }

        owned_intersections = list(getattr(self, "settlements", []) or [])
        owned_intersections.extend(getattr(self, "cities", []) or [])

        def _intersection_by_id(intersection_id: int):
            try:
                inter = board.intersections[int(intersection_id)]
                if inter is not None and int(getattr(inter, "id", intersection_id)) == int(intersection_id):
                    return inter
            except Exception:
                pass
            for inter in getattr(board, "intersections", []) or []:
                try:
                    if inter is not None and int(getattr(inter, "id", -1)) == int(intersection_id):
                        return inter
                except Exception:
                    continue
            return None

        def _normalize_port_type(port_type: Any) -> str:
            text = str(port_type or "").strip()
            if not text or text.lower() == "blank":
                return ""
            lowered = text.lower().replace("wool", "sheep").replace("grain", "wheat").replace("lumber", "wood")
            if lowered == "3:1":
                return "3:1"
            if lowered.startswith("2:1"):
                parts = lowered.split(maxsplit=1)
                if len(parts) == 2:
                    resource = parts[1].strip()
                    display = {
                        "wheat": "Wheat",
                        "ore": "Ore",
                        "wood": "Wood",
                        "brick": "Brick",
                        "sheep": "Sheep",
                    }.get(resource)
                    if display:
                        return f"2:1 {display}"
            return text

        for intersection_id in owned_intersections:
            try:
                inter_id = int(intersection_id)
            except Exception:
                continue
            inter = _intersection_by_id(inter_id)
            if inter is None:
                continue

            has_port = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
            if not has_port:
                continue

            port_type = _normalize_port_type(getattr(inter, "port_type", ""))
            if not port_type:
                continue

            if port_type == "3:1":
                rates = [min(rate, 3) for rate in rates]
                self.port_access["3:1"] = True
            elif port_type == "2:1 Wheat":
                rates[0] = min(rates[0], 2)
                self.port_access["2:1 Wheat"] = True
            elif port_type == "2:1 Ore":
                rates[1] = min(rates[1], 2)
                self.port_access["2:1 Ore"] = True
            elif port_type == "2:1 Wood":
                rates[2] = min(rates[2], 2)
                self.port_access["2:1 Wood"] = True
            elif port_type == "2:1 Brick":
                rates[3] = min(rates[3], 2)
                self.port_access["2:1 Brick"] = True
            elif port_type == "2:1 Sheep":
                rates[4] = min(rates[4], 2)
                self.port_access["2:1 Sheep"] = True

        self.trade_rates = rates

    def get_resource_production_probability(self, board: 'Board') -> Dict[ResourceCard, int]:
        """Calculate the total resource production probability for each resource.

        Args:
            board: The game board instance.

        Returns:
            Dict[ResourceCard, int]: Dictionary mapping resource types to total probability (dots).
        """
        probabilities = {rc: 0 for rc in ResourceCard}
        for intersection_id in self.settlements + self.cities:
            for intersection in board.intersections:
                if intersection.id == intersection_id:
                    for tile_id, prob in zip(intersection.three_tile_ids, intersection.three_tile_probabilities_v2):
                        for tile in board.tiles:
                            if tile and tile.id == tile_id:
                                resource = next((r for r in ResourceCard if r.value == tile.type), None)
                                if resource:
                                    multiplier = 2 if intersection_id in self.cities else 1
                                    probabilities[resource] += prob * multiplier
        return probabilities

    def rcards_in_hand(self) -> Tuple[List[int], List[int], List[int]]:
        """Retrieve resource cards and bank trade ratios.

        Returns:
            Tuple containing:
                - Resource counts [Wheat, Ore, Wood, Brick, Sheep].
                - Trade ratios [Wheat, Ore, Wood, Brick, Sheep].
                - Number of bank trades affordable for each resource.
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"{self.game.sequence_number} | {self.game.state} | player.py | rcards_in_hand\n")
        rcards5 = [
            self.rcards.get(ResourceCard.WHEAT, 0),
            self.rcards.get(ResourceCard.ORE, 0),
            self.rcards.get(ResourceCard.WOOD, 0),
            self.rcards.get(ResourceCard.BRICK, 0),
            self.rcards.get(ResourceCard.SHEEP, 0),
        ]
        trade_ratio = self._clean_trade_rates_vector(getattr(self, "trade_rates", [4, 4, 4, 4, 4]))
        self.trade_rates = list(trade_ratio)
        trade_ratio_in_rcards5 = [int(math.floor(int(rcards5[i] or 0) / max(1, trade_ratio[i]))) for i in range(5)]
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"player.py | rcards_in_hand for Player: {self.id} | rcards5: {rcards5} | TR: {trade_ratio} | TRinR5: {trade_ratio_in_rcards5}\n")
        return rcards5, trade_ratio, trade_ratio_in_rcards5
   
    def set_strategic_direction(
        self,
        preferred_strategy: Optional[Dict[str, Any]],
        *,
        append_history: bool = True,
        max_history: int = 20,
    ) -> None:
        """
        Store the player's current strategic direction.

        The expected input is player_block["preferred_strategy"] from
        core.action_planner.apply_strategy_preference_layer(...).

        This method deliberately stores strategic intent on Player, not Outlook:
        - Outlook = board/geometry opportunities.
        - strategic_direction = player-level plan / preferred way_id.
        """
        if preferred_strategy is None:
            self.last_strategic_direction = self.strategic_direction
            self.strategic_direction = None
            return

        if not isinstance(preferred_strategy, dict):
            try:
                preferred_strategy = dict(preferred_strategy)  # type: ignore[arg-type]
            except Exception:
                return

        previous = self.strategic_direction
        self.last_strategic_direction = previous
        self.strategic_direction = dict(preferred_strategy)

        if append_history:
            self.strategic_direction_history.append(dict(preferred_strategy))
            if max_history > 0 and len(self.strategic_direction_history) > max_history:
                self.strategic_direction_history = self.strategic_direction_history[-max_history:]

    def preferred_way_id(self) -> Optional[int]:
        """Return the currently preferred way_id, if one is known."""
        direction = self.strategic_direction or {}
        raw_value = direction.get("preferred_way_id", direction.get("way_id"))
        try:
            if raw_value is None or raw_value == "":
                return None
            return int(float(raw_value))
        except Exception:
            return None

    def clear_strategic_direction(self, *, append_history: bool = False) -> None:
        """Clear the current strategic direction while preserving last direction."""
        self.set_strategic_direction(None, append_history=append_history)

    def save_player(self) -> Dict[str, Any]:
        """
        Serialize this player for Game.save_game().

        The saved representation is JSON-friendly:
            - ResourceCard enum keys are stored as their string values.
            - Road tuples are stored as two-item lists.
            - Outlook dataclass objects are stored as dictionaries.

        The goal is to preserve all player state that affects continuing a game:
            resources, development cards, structures, victory/army/road state,
            trade/port state, turn-detail counters, strategy/outlook maps, and
            initial-placement settings.
        """
        def _json_safe(value: Any) -> Any:
            if isinstance(value, ResourceCard):
                return value.value
            if isinstance(value, tuple):
                return [_json_safe(v) for v in value]
            if isinstance(value, list):
                return [_json_safe(v) for v in value]
            if isinstance(value, dict):
                safe_dict = {}
                for key, item in value.items():
                    if isinstance(key, ResourceCard):
                        safe_key = key.value
                    else:
                        safe_key = str(key)
                    safe_dict[safe_key] = _json_safe(item)
                return safe_dict
            if hasattr(value, "__dataclass_fields__"):
                return {k: _json_safe(getattr(value, k)) for k in value.__dataclass_fields__}
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return str(value)

        return {
            "id": self.id,
            "color": self.color,
            "color2": getattr(self, "color2", self.color),
            "sequence": self.sequence,
            "is_human": self.is_human,
            "gameover_tf": self.gameover_tf,
            "initial_placement_algorithm": self.initial_placement_algorithm,
            "human_like_placement": self.human_like_placement,
            "points": self.points,
            "victory_points": self.victory_points,
            "longest_route_tf": self.longest_route_tf,
            "size_longest_route": self.size_longest_route,
            "structure_longest_route": _json_safe(self.structure_longest_route),
            "number_of_clusters": self.number_of_clusters,
            "structure_of_clusters": _json_safe(self.structure_of_clusters),
            "largest_army_tf": self.largest_army_tf,
            "size_largest_army": self.size_largest_army,
            "number_of_rcards": self.number_of_rcards,
            "number_of_dcards": self.number_of_dcards,
            "rcards": _json_safe(self.rcards),
            "dcard_summary": _json_safe(self.dcard_summary),
            "development_cards": _json_safe(self.development_cards),
            "settlements": _json_safe(self.settlements),
            "cities": _json_safe(self.cities),
            "roads": _json_safe(self.roads),
            "turn_details_resource_production": _json_safe(self.turn_details_resource_production),
            "turn_details_resource_production_robber": _json_safe(self.turn_details_resource_production_robber),
            "turn_details_buy": _json_safe(self.turn_details_buy),
            "turn_details_steal": _json_safe(self.turn_details_steal),
            "turn_details_discard": _json_safe(self.turn_details_discard),
            "turn_details_TwP": _json_safe(self.turn_details_TwP),
            "turn_details_last_TwPdeal": _json_safe(self.turn_details_last_TwPdeal),
            "turn_details_TwB": _json_safe(self.turn_details_TwB),
            "turn_details_dcard": _json_safe(self.turn_details_dcard),
            "stats_twp_proposed": int(getattr(self, "stats_twp_proposed", 0) or 0),
            "stats_twp_accepted": int(getattr(self, "stats_twp_accepted", 0) or 0),
            "stats_dcards_bought": int(getattr(self, "stats_dcards_bought", 0) or 0),
            "trade_rates": _json_safe(self.trade_rates),
            "port_access": _json_safe(self.port_access),
            "last_action": self.last_action,
            "pips": _json_safe(self.pips),
            "buying_power": _json_safe(self.buying_power),
            "trading_power": _json_safe(self.trading_power),
            "new_settlement_as_primary_strategy": _json_safe(self.new_settlement_as_primary_strategy),
            "primary_strategy": self.primary_strategy,
            "resource_production": _json_safe(self.resource_production),
            "strategy": _json_safe(self.strategy),
            "outlook": _json_safe(self.outlook),
            "strategic_direction": _json_safe(self.strategic_direction),
            "last_strategic_direction": _json_safe(self.last_strategic_direction),
            "strategic_direction_history": _json_safe(self.strategic_direction_history),
            "sticky_commitment": _json_safe(self.sticky_commitment),
            "strategy_recalc_flag": _json_safe(self.strategy_recalc_flag),
            "force_strategy_recalc": bool(self.force_strategy_recalc),
            "way_kill_latch": _json_safe(self.way_kill_latch),
            "last_way_kill": _json_safe(self.last_way_kill),
            "specials_divert_checked_turn": _json_safe(
                getattr(self, "specials_divert_checked_turn", None)
            ),
            "last_specials_divert": _json_safe(
                getattr(self, "last_specials_divert", None)
            ),
            "last_specials_assess": _json_safe(
                getattr(self, "last_specials_assess", None)
            ),
            "distance_map": _json_safe(self.distance_map),
            "min_distance_map_for_targeted_TWs": _json_safe(self.min_distance_map_for_targeted_TWs),
            "path_map": _json_safe(self.path_map),
            "pathlength_map": _json_safe(self.pathlength_map),
            "min_pathlength_map_for_targeted_TWs": _json_safe(self.min_pathlength_map_for_targeted_TWs),
            "real_distance_map": _json_safe(self.real_distance_map),
            "min_real_distance_map_for_targeted_TWs": _json_safe(self.min_real_distance_map_for_targeted_TWs),
        }

    def load_player(self, data: Dict[str, Any], board: Optional['Board'] = None) -> None:
        """
        Restore this player from a Game.save_game() player block.

        Missing fields are treated as defaults from Player.__init__(), so older
        saved games remain loadable. Board consistency is finalized by
        Board.load_game_board_state(...) and Game.load_game(...), but this method
        restores all player-owned counters, cards, settings, and strategy maps.
        """
        if not isinstance(data, dict):
            return

        def _get(name: str, default: Any) -> Any:
            return data.get(name, default)

        def _as_int_list(value: Any) -> List[int]:
            if not isinstance(value, list):
                return []
            result: List[int] = []
            for item in value:
                try:
                    result.append(int(item))
                except Exception:
                    pass
            return result

        def _as_road_list(value: Any) -> List[Tuple[int, int]]:
            if not isinstance(value, list):
                return []
            result: List[Tuple[int, int]] = []
            for item in value:
                try:
                    a, b = item
                    road_id = tuple(sorted((int(a), int(b))))
                except Exception:
                    continue
                if len(road_id) == 2 and road_id not in result:
                    result.append(road_id)
            return result

        def _as_optional_dict(value: Any) -> Optional[Dict[str, Any]]:
            if value is None:
                return None
            if isinstance(value, dict):
                return dict(value)
            return None

        def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
            if not isinstance(value, list):
                return []
            return [dict(item) for item in value if isinstance(item, dict)]

        def _resource_from_key(key: Any) -> Optional[ResourceCard]:
            if isinstance(key, ResourceCard):
                return key
            key_text = str(key).strip()
            for rc in ResourceCard:
                if key_text in (rc.name, rc.value, rc.name.lower(), rc.value.lower()):
                    return rc
            return None

        self.id = int(_get("id", self.id))
        self.color = str(_get("color", self.color))
        self.color2 = str(_get("color2", self.color))
        self.sequence = int(_get("sequence", self.sequence))
        self.is_human = bool(_get("is_human", self.is_human))
        self.gameover_tf = bool(_get("gameover_tf", self.gameover_tf))
        self.initial_placement_algorithm = int(_get("initial_placement_algorithm", self.initial_placement_algorithm))
        self.human_like_placement = bool(_get("human_like_placement", self.human_like_placement))

        self.points = int(_get("points", self.points))
        self.victory_points = int(_get("victory_points", self.victory_points))
        self.longest_route_tf = bool(_get("longest_route_tf", self.longest_route_tf))
        self.size_longest_route = int(_get("size_longest_route", self.size_longest_route))
        self.structure_longest_route = _as_road_list(_get("structure_longest_route", self.structure_longest_route))
        self.number_of_clusters = int(_get("number_of_clusters", self.number_of_clusters))
        self.structure_of_clusters = _get("structure_of_clusters", self.structure_of_clusters)
        self.largest_army_tf = bool(_get("largest_army_tf", self.largest_army_tf))
        self.size_largest_army = int(_get("size_largest_army", self.size_largest_army))

        saved_rcards = _get("rcards", {})
        self.rcards = {rc: 0 for rc in ResourceCard}
        if isinstance(saved_rcards, dict):
            for key, value in saved_rcards.items():
                rc = _resource_from_key(key)
                if rc is not None:
                    try:
                        self.rcards[rc] = int(value)
                    except Exception:
                        self.rcards[rc] = 0

        self.dcard_summary = _get("dcard_summary", self.dcard_summary)
        self.development_cards = list(_get("development_cards", self.development_cards) or [])
        self.settlements = _as_int_list(_get("settlements", self.settlements))
        self.cities = _as_int_list(_get("cities", self.cities))
        self.roads = _as_road_list(_get("roads", self.roads))

        self.turn_details_resource_production = _get("turn_details_resource_production", self.turn_details_resource_production)
        self.turn_details_resource_production_robber = _get("turn_details_resource_production_robber", self.turn_details_resource_production_robber)
        self.turn_details_buy = _get("turn_details_buy", self.turn_details_buy)
        self.turn_details_steal = _get("turn_details_steal", self.turn_details_steal)
        self.turn_details_discard = _get("turn_details_discard", self.turn_details_discard)
        self.turn_details_TwP = _get("turn_details_TwP", self.turn_details_TwP)
        self.turn_details_last_TwPdeal = _get("turn_details_last_TwPdeal", self.turn_details_last_TwPdeal)
        self.turn_details_TwB = _get("turn_details_TwB", self.turn_details_TwB)
        self.turn_details_dcard = _get("turn_details_dcard", self.turn_details_dcard)

        try:
            self.stats_twp_proposed = int(_get("stats_twp_proposed", getattr(self, "stats_twp_proposed", 0)) or 0)
        except Exception:
            self.stats_twp_proposed = 0
        try:
            self.stats_twp_accepted = int(_get("stats_twp_accepted", getattr(self, "stats_twp_accepted", 0)) or 0)
        except Exception:
            self.stats_twp_accepted = 0
        try:
            self.stats_dcards_bought = int(_get("stats_dcards_bought", getattr(self, "stats_dcards_bought", 0)) or 0)
        except Exception:
            self.stats_dcards_bought = 0

        saved_trade_rates = _get("trade_rates", self.trade_rates)
        self.trade_rates = self._clean_trade_rates_vector(saved_trade_rates)

        saved_port_access = _get("port_access", self.port_access)
        if isinstance(saved_port_access, dict):
            self.port_access = {str(k): bool(v) for k, v in saved_port_access.items()}

        self.last_action = str(_get("last_action", self.last_action))
        self.pips = _get("pips", self.pips)
        self.buying_power = _get("buying_power", self.buying_power)
        self.trading_power = _get("trading_power", self.trading_power)
        self.new_settlement_as_primary_strategy = _get("new_settlement_as_primary_strategy", self.new_settlement_as_primary_strategy)
        self.primary_strategy = int(_get("primary_strategy", self.primary_strategy))
        self.resource_production = _get("resource_production", self.resource_production)
        self.strategy = _get("strategy", self.strategy)
        self.strategic_direction = _as_optional_dict(_get("strategic_direction", self.strategic_direction))
        self.last_strategic_direction = _as_optional_dict(_get("last_strategic_direction", self.last_strategic_direction))
        self.strategic_direction_history = _as_dict_list(_get("strategic_direction_history", self.strategic_direction_history))
        self.sticky_commitment = _as_optional_dict(_get("sticky_commitment", self.sticky_commitment))
        self.strategy_recalc_flag = _as_optional_dict(_get("strategy_recalc_flag", self.strategy_recalc_flag))
        self.force_strategy_recalc = bool(_get("force_strategy_recalc", self.force_strategy_recalc))
        self.way_kill_latch = _as_optional_dict(_get("way_kill_latch", self.way_kill_latch))
        self.last_way_kill = _as_optional_dict(_get("last_way_kill", self.last_way_kill))
        _sdt = _get("specials_divert_checked_turn", getattr(self, "specials_divert_checked_turn", None))
        if isinstance(_sdt, (list, tuple)):
            self.specials_divert_checked_turn = list(_sdt)
        else:
            self.specials_divert_checked_turn = None
        self.last_specials_divert = _as_optional_dict(
            _get("last_specials_divert", getattr(self, "last_specials_divert", None))
        )
        self.last_specials_assess = _as_optional_dict(
            _get("last_specials_assess", getattr(self, "last_specials_assess", None))
        )

        # Outlook is optional. Rehydrate one Outlook object when possible.
        saved_outlooks = _get("outlook", None)
        if isinstance(saved_outlooks, list) and saved_outlooks:
            loaded_outlooks: List[Outlook] = []
            for outlook_data in saved_outlooks:
                outlook = Outlook()
                if isinstance(outlook_data, dict):
                    for field_name in outlook.__dataclass_fields__:
                        if field_name in outlook_data:
                            setattr(outlook, field_name, outlook_data[field_name])
                loaded_outlooks.append(outlook)
            self.outlook = loaded_outlooks

        self.distance_map = _get("distance_map", self.distance_map)
        self.min_distance_map_for_targeted_TWs = _get("min_distance_map_for_targeted_TWs", self.min_distance_map_for_targeted_TWs)
        self.path_map = _get("path_map", self.path_map)
        self.pathlength_map = _get("pathlength_map", self.pathlength_map)
        self.min_pathlength_map_for_targeted_TWs = _get("min_pathlength_map_for_targeted_TWs", self.min_pathlength_map_for_targeted_TWs)
        self.real_distance_map = _get("real_distance_map", self.real_distance_map)
        self.min_real_distance_map_for_targeted_TWs = _get("min_real_distance_map_for_targeted_TWs", self.min_real_distance_map_for_targeted_TWs)

        self.number_of_rcards = sum(self.rcards.get(rc, 0) for rc in ResourceCard)
        self.number_of_dcards = len(self.development_cards)

        if board is not None:
            try:
                self.update_trade_rates(board)
            except Exception:
                pass

    def write_debug_info(self) -> None:
        """Write player attributes to FILENAME_MG for debugging.

        Args:
            None
        """
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"player.py | write_debug_info | Player ID: {self.id}\n")
                f.write(f" Color: {self.color}, Sequence: {self.sequence}\n")
                f.write(f" Victory Points: {self.victory_points}, Points: {self.points}\n")
                f.write(f" Longest Route: {self.longest_route_tf}, Size: {self.size_longest_route}, "
                        f"Structure: {self.structure_longest_route}\n")
                f.write(f" Largest Army: {self.largest_army_tf}, Size: {self.size_largest_army}\n")
                f.write(f" Number of Resource Cards: {self.number_of_rcards}, Number of Dev Cards: {self.number_of_dcards}\n")
                f.write(f" Resource Cards: {self.rcards}\n")
                f.write(f" Development Cards: {self.development_cards}, DCard Summary: {self.dcard_summary}\n")
                f.write(f" Settlements: {self.settlements}, Cities: {self.cities}, Roads: {self.roads}\n")
                f.write(f" Port Access: {self.port_access}\n")
                f.write(f" Last Action: {self.last_action}\n")
                rcards, trade_ratio, trade_ratio_in_rcards = self.rcards_in_hand()
                f.write(f" Resouce Cards in Hand: {rcards}, Trade Ratio: {trade_ratio}, "
                        f"Trade Ratio in RCards: {trade_ratio_in_rcards}\n")

    @staticmethod
    def _safe_float(val: Any) -> float:
        """Safe conversion to float, returns 0.0 on failure."""
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def has_port(self) -> bool:
        """Return True if the player owns at least one settlement or city on a port intersection."""
        for inter_id in self.settlements + self.cities:
            inter = self.game.board.intersections[inter_id]
            if inter and (getattr(inter, "port_tf", False) or getattr(inter, "portYN", "N") == "Y"):
                return True
        return False

    def get_current_production_pips(self, board: 'Board') -> List[float]:
        pips = [0.0] * 5
        for inter_id in self.settlements + self.cities:
            inter = board.intersections[inter_id]
            if not inter:
                continue
            probs = getattr(inter, "all_tile_probabilities",
                            getattr(inter, "three_tile_probabilities_v2",
                                    getattr(inter, "three_tile_probabilities", [0.0]*5)))
            types = getattr(inter, "all_tile_types", [0]*5)
            multiplier = 2 if inter_id in self.cities else 1
            for idx in range(5):
                if types[idx] > 0:
                    pips[idx] += Player._safe_float(probs[idx]) * multiplier
        return pips
    
