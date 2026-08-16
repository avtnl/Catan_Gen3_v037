"""
Manages the Catan game board.

This module defines the Board class, handling the initialization of tiles, intersections,
roads, and ports. It ensures correct tile ordering (tiles[0].id == 9, etc.) for land tiles
and initializes sea tiles with type "Sea". The board state is empty initially (no settlements,
cities, or roads).
Key components:
    - Tile: Represents a hexagonal tile with type and value.
    - Intersection: Represents a vertex with building status and port info.
    - Road: Represents an edge with occupancy status.
    - Board: Manages the game board layout and state.
Dependencies:
    - typing: For type hints.
    - datetime: For retrieving a timestamp.
    - copy: For random port locations.
    - random: For random board generation.
    - core.constants: For game configuration constants.
"""
from typing import List, Optional, Tuple, Dict, Any, Set
from datetime import datetime
import random
import copy

from matplotlib.pylab import tile
from sklearn.base import defaultdict
from core.constants import FNFREQ, FILENAME_FREQ, MG, FILENAME_MG

# board.py (near the top, after imports)

def pips_from_tile_value(value: int) -> float:
    """
    Classic Catan pip/dot count (number token strength).

    Returns:
        0    for desert / sea / invalid
        1    for 2 & 12
        2    for 3 & 11
        3    for 4 & 10
        4    for 5 & 9
        5    for 6 & 8
    """
    if not (2 <= value <= 12):
        return 0.0
    return 6 - abs(7 - value)

def true_probability_from_pips(pips: float) -> float:
    """Convert pip count to actual 2d6 roll probability."""
    return pips / 36.0

def true_probability_from_dice_value(value: int) -> float:
    """Direct: dice value → real probability (0–1)."""
    return pips_from_tile_value(value) / 36.0

class Edge:
    """Represents an edge of a tile on the Catan board."""
   
    def __init__(self, location: str, kind: str = "Blank", color: str = "Blank", road: List[int] = [0, 0]) -> None:
        """Initialize an Edge.
     
        Args:
            location: Edge position (e.g., 'NE', 'E', 'SE', 'SW', 'W', 'NW').
            kind: Type of structure ('Blank' or 'Road').
            color: Player color or 'Blank'.
            road: List of two intersection IDs defining the road.
        """
        self.location = location
        self.kind = kind
        self.color = color
        self.road = road


class Corner:
    """Represents a corner of a tile on the Catan board."""
   
    def __init__(self, location: str, kind: str = "Blank", color: str = "Blank", port_type: str = "Blank", intersection: int = 0) -> None:
        """Initialize a Corner.
     
        Args:
            location: Corner position (e.g., 'N', 'EH', 'EL', 'S', 'WL', 'WH').
            kind: Type of structure ('Blank', 'Settlement', 'City').
            color: Player color or 'Blank'.
            port_type: Port type if applicable (e.g., '3:1', '2:1 Brick').
            intersection: Intersection ID associated with the corner.
        """
        self.location = location
        self.kind = kind
        self.color = color
        self.port_type = port_type
        self.intersection = intersection
   

class Tile:
    """Represents a hexagonal tile on the Catan board."""
 
    def __init__(self, id_: int, type_: str = "Blank", value: int = 0, color: str = "Blank") -> None:
        """Initialize a Tile.
     
        Args:
            id_: Unique tile ID.
            type_: Resource type (e.g., 'Field', 'Desert', 'Sea').
            value: Tile number (2-12 for land tiles, 0 for Desert/Sea).
            color: Tile color (e.g., 'Blank', 'Sea', or player color).
        """
        self.id = id_
        self.type = type_
        self.value = value
        self.color = color
        self.occupied_tf = False  # To check placement of Robber
        self.current_settlements: int = 0  # Used by resource_exploration()
        self.edges: List[dict] = []
        self.corners: List[dict] = []


class Intersection:
    """Represents a vertex on the Catan board."""
   
    def __init__(self, id_: int) -> None:
        """Initialize an Intersection.
     
        Args:
            id_: Unique intersection ID.
        """
        self.id = id_
        self.face = "Blank"
        self.occupied_tf = False
        self.color = "Blank"
        self.type: Optional[str] = "Vertex"  # Default to "Vertex" for buildable intersections
        self.can_build_tf: bool = True       # Default True for land intersections
        self.three_tile_ids: List[int] = []
        self.three_tile_pips: List[float] = []
        self.three_tile_types: List[str] = []
        self.three_tile_values: List[int] = []
        self.all_tile_types: List[int] = [0, 0, 0, 0, 0]  # [Grain, Ore, Wood, Brick, Sheep]
        self.all_tile_pips: List[float] = [0, 0, 0, 0, 0]
        self.all_tile_values: List[int] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.three_roads: List[Tuple[int, int]] = []
        self.three_intersection_ids: List[int] = []
        self.port_tf = False
        self.port_type = "Blank"
        self.game_round: int = 0
        self.game_turn: int = 0
        self.placement_step: int = -1


class Road:
    """Represents an edge on the Catan board."""
 
    def __init__(self, id_: Tuple[int, int]) -> None:
        """Initialize a Road.
     
        Args:
            id_: Tuple of two intersection IDs defining the road.
        """
        self.id = id_
        self.kind = "Blank"
        self.color = "Blank"
        self.occupied_tf = False
        self.two_tiles: List[List[any]] = []
        self.game_round: int = 0
        self.game_turn: int = 0
        self.placement_step: int = -1


class Board:
    """Represents the Catan game board."""
    NUM_TILES = 46
    NUM_INTERSECTIONS = 67
    LIST_OF_LAND_TILES = [9, 10, 11, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30, 31, 35, 36, 37]
    LIST_OF_SKIPPED_TILE_IDS = [0, 1, 6, 7, 13, 33, 39, 40, 45]
    INTERSECTION_IN_WATER = [0, 1, 2, 10, 11, 12, 22, 45, 55, 56, 57, 65, 66]
    LIST_OF_PORTTYPES = ["3:1", "3:1", "3:1", "3:1", "2:1 Wheat", "2:1 Ore", "2:1 Wood", "2:1 Brick", "2:1 Sheep"]
    INTERSECTIONS_ARE_PORT = [[3, 4], [6, 7], [13, 24], [20, 21], [33, 44], [35, 46], [53, 54], [58, 59], [61, 62]]
    BOARD_LAYOUT = [
        [0,1,2,3,4,5,6,0], ##### list of Tile.id's in every row
        [7,8,9,10,11,12,13],
        [0,14,15,16,17,18,19,0],
        [20,21,22,23,24,25,26],
        [0,27,28,29,30,31,32,0],
        [33,34,35,36,37,38,39],
        [0,40,41,42,43,44,45,0]
    ]
    ALL_TILE_IDS = set(range(0, 46))

    def __init__(self, board_name: str = "Base_Random", *, load_map: bool = True) -> None:
        """Initialize the Board.

        Args:
            board_name: Map mode name (e.g. ``Base_Random``) when generating.
            load_map: When True (default), apply ``LOAD_PLAYBOARD`` / random
                generation as today. When False, build a blank topology only
                and **do not** load ``SAVED_PLAYBOARD`` or generate a random
                map — caller must ``load_board(path)`` once (MGlog re-play /
                offline stats). Avoids the double-load print and wrong first
                map when ``LOAD_PLAYBOARD=True`` in constants.
        """
        self.board_name = board_name
        self.round = -2
        self.turn = 1

        # Initialize empty board structures
        self.intersections = [None] * self.NUM_INTERSECTIONS
        for i in range(67):
            if i not in self.INTERSECTION_IN_WATER:
                self.intersections[i] = Intersection(i)

        self.tiles = [None] * self.NUM_TILES
        self.roads = []
        self.list_of_roads_connected_to_intersection = [[] for _ in range(67)]

        # ──────────────────────────────────────────────────────────────
        # Deferred map load (re-play / stats): blank topology only
        # ──────────────────────────────────────────────────────────────
        if not load_map:
            self._init_blank_topology_for_file_load()
            return

        # ──────────────────────────────────────────────────────────────
        # LOAD SAVED PLAYBOARD or generate random
        # ──────────────────────────────────────────────────────────────
        from core.constants import LOAD_PLAYBOARD, SAVED_PLAYBOARD
        if LOAD_PLAYBOARD:
            print(f"📂 Loading saved playboard: {SAVED_PLAYBOARD}")
            self._add_tiles()                    # create empty tiles first
            self._add_empty_edges_and_corners()
            self._add_intersections()            # ← important: creates empty intersections
            self.load_board(SAVED_PLAYBOARD)     # overwrite tiles + ports

            # === CRITICAL: refresh ALL intersection data after loading tiles ===
            self._add_intersections()            # ← re-populates three_tile_pips, three_tile_types, etc.

            # Reconstruct roads/edges for GUI
            self._complete_edges()
            self._add_roads()

            self._create_list_of_roads_connected_to_intersection()
            self._update_intersection_types()
            self._add_three_intersection_ids()
            self._add_two_tile_attributes()

            print(f"   → Reconstructed {len(self.roads)} roads/edges and refreshed 54 intersections")

        else:
            print("🎲 Generating random board")
            if board_name == "Base_Random":
                self._get_board()
                self.save_board("")
            else:
                self._initialize_board()

        # Post-load / post-generation steps (always required)
        self._create_list_of_roads_connected_to_intersection()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_two_tile_attributes()

        # Build reverse mapping for intersections → corners
        from collections import defaultdict
        self.intersection_to_corners = defaultdict(list)
        for tile in self.tiles:
            if tile:
                for corner in tile.corners:
                    iid = corner.intersection
                    if iid > 0:
                        self.intersection_to_corners[iid].append((tile, corner.location))

        # Precompute algorithm=2 raw data (needed for fallback to algo 4)
        from core.algorithms_initial_placement import InitialPlacementStrategies
        InitialPlacementStrategies.precompute_algorithm2_raw(self)

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"board.py | __init__ completed | Loaded {len(self.tiles)} tiles and {sum(1 for i in self.intersections if i and i.port_tf)} ports\n")

    def _init_blank_topology_for_file_load(self) -> None:
        """Create tile/intersection/road shells without reading any playboard file.

        Used when ``load_map=False`` so callers can ``load_board(explicit_path)``
        once without first loading ``constants.SAVED_PLAYBOARD``.
        """
        self._add_tiles()
        self._add_empty_edges_and_corners()
        self._add_intersections()
        self._complete_edges()
        self._add_roads()
        self._create_list_of_roads_connected_to_intersection()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_two_tile_attributes()

    def _initialize_board(self) -> None:
        """Initialize the board based on the board name."""
        self._add_tiles()
        self._add_empty_edges_and_corners()
        self._add_intersections()
        self._complete_edges()
        self._add_roads()
        self._create_list_of_roads_connected_to_intersection()
        self._add_three_tile_values()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_ports()
        self._add_two_tile_attributes()
        self.load_board(self.board_name)

    def _add_tiles(self) -> None:
        """Add tiles to the board based on BOARD_LAYOUT."""
        tile_id_map = {tid: i for i, tid in enumerate(self.ALL_TILE_IDS)}
        for tile_id in self.ALL_TILE_IDS:
            idx = tile_id_map[tile_id]
            if idx not in self.LIST_OF_SKIPPED_TILE_IDS:
                if tile_id in self.LIST_OF_LAND_TILES:
                    self.tiles[idx] = Tile(tile_id)  # Land tile
                else:
                    self.tiles[idx] = Tile(tile_id, type_="Sea", value=0, color="Blank")  # Sea tile

    def _add_intersections(self) -> None:
        """Add intersections with tile associations based on BOARD_LAYOUT.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | _add_intersections\n")
   
        corner_indices = {"N": 0, "EH": 1, "EL": 2, "S": 3, "WL": 4, "WH": 5}
   
        # Process odd-numbered intersections (1, 3, 5, ...)
        for i in range(1, 67, 2):
            if i in self.INTERSECTION_IN_WATER:
                continue
            intersection = self.intersections[i]
            if intersection is None:
                continue
            intersection.three_tile_ids = []
            intersection.three_tile_pips = []
            intersection.three_tile_types = []
            intersection.three_tile_values = []
            intersection.all_tile_values = [0] * 11 # Counts for tile values 2–12
            intersection.all_tile_types = [0, 0, 0, 0, 0]  # [Field, Mountain, Forest, Hill, Pasture]
            intersection.all_tile_pips = [0, 0, 0, 0, 0]
       
            # Find row and column in BOARD_LAYOUT
            for r in range(6):
                c = i - r * 11
                if i <= (r + 1) * 11:
                    break
       
            # Calculate tile IDs and corresponding corners
            if r % 2 == 0: # Even rows
                col = int((c + 1) / 2)
                tile_ids = [
                    self.BOARD_LAYOUT[r + 1][col - 1] if r + 1 < 7 and col - 1 >= 0 else 0,
                    self.BOARD_LAYOUT[r][col] if col < len(self.BOARD_LAYOUT[r]) else 0,
                    self.BOARD_LAYOUT[r + 1][col] if r + 1 < 7 and col < len(self.BOARD_LAYOUT[r + 1]) else 0
                ]
                corners = [1, 3, 5] # EH, S, WH
            else: # Odd rows
                col = int(c / 2)
                tile_ids = [
                    self.BOARD_LAYOUT[r + 1][col] if r + 1 < 7 and col < len(self.BOARD_LAYOUT[r + 1]) else 0,
                    self.BOARD_LAYOUT[r][col] if col < len(self.BOARD_LAYOUT[r]) else 0,
                    self.BOARD_LAYOUT[r + 1][col + 1] if r + 1 < 7 and col + 1 < len(self.BOARD_LAYOUT[r + 1]) else 0
                ]
                corners = [1, 3, 5] # EH, S, WH
       
            # Assign tile IDs and update tile corners
            for tile_id, corner_idx in zip(tile_ids, corners):
                if tile_id != 0:
                    intersection.three_tile_ids.append(tile_id)
                    tile = self.tiles[tile_id] if tile_id < len(self.tiles) and self.tiles[tile_id] else None
                    if tile:
                        intersection.three_tile_types.append(tile.type)
                        pips = pips_from_tile_value(tile.value)
                        intersection.three_tile_pips.append(pips)
                        if tile.type == "Field":
                            intersection.all_tile_types[0] += 1
                            intersection.all_tile_pips[0] += pips
                        elif tile.type == "Mountain":
                            intersection.all_tile_types[1] += 1
                            intersection.all_tile_pips[1] += pips
                        elif tile.type == "Forest":
                            intersection.all_tile_types[2] += 1
                            intersection.all_tile_pips[2] += pips
                        elif tile.type == "Hill":
                            intersection.all_tile_types[3] += 1
                            intersection.all_tile_pips[3] += pips
                        elif tile.type == "Pasture":
                            intersection.all_tile_types[4] += 1
                            intersection.all_tile_pips[4] += pips

                        # Assign intersection to tile corner, skip if intersection_id in INTERSECTION_IN_WATER
                        for corner in tile.corners:
                            if corner_indices[corner.location] == corner_idx and corner.intersection == 0 and i not in self.INTERSECTION_IN_WATER:
                                corner.intersection = intersection.id
                                break
   
        # Process even-numbered intersections (2, 4, 6, ...)
        for i in range(2, 67, 2):
            if i in self.INTERSECTION_IN_WATER:
                continue
            intersection = self.intersections[i]
            if intersection is None:
                continue
            intersection.three_tile_ids = []
            intersection.three_tile_pips = []
            intersection.three_tile_types = []
            intersection.three_tile_values = []
            intersection.all_tile_values = [0] * 11 # Counts for tile values 2–12
            intersection.all_tile_types = [0, 0, 0, 0, 0]  # [Field, Mountain, Forest, Hill, Pasture]
            intersection.all_tile_pips = [0, 0, 0, 0, 0]
       
            # Find row and column in BOARD_LAYOUT
            for r in range(6):
                c = i - r * 11
                if i <= (r + 1) * 11:
                    break
       
            # Calculate tile IDs and corresponding corners
            if r % 2 == 0: # Even rows
                col = int(c / 2)
                tile_ids = [
                    self.BOARD_LAYOUT[r][col] if col < len(self.BOARD_LAYOUT[r]) else 0,
                    self.BOARD_LAYOUT[r + 1][col] if r + 1 < 7 and col < len(self.BOARD_LAYOUT[r + 1]) else 0,
                    self.BOARD_LAYOUT[r][col + 1] if col + 1 < len(self.BOARD_LAYOUT[r]) else 0
                ]
                corners = [2, 0, 4] # EL, N, WL
            else: # Odd rows
                col = int((c + 1) / 2)
                tile_ids = [
                    self.BOARD_LAYOUT[r][col - 1] if col - 1 >= 0 else 0,
                    self.BOARD_LAYOUT[r + 1][col] if r + 1 < 7 and col < len(self.BOARD_LAYOUT[r + 1]) else 0,
                    self.BOARD_LAYOUT[r][col] if col < len(self.BOARD_LAYOUT[r]) else 0
                ]
                corners = [2, 0, 4] # EL, N, WL
       
            # Assign tile IDs and update tile corners
            for tile_id, corner_idx in zip(tile_ids, corners):
                if tile_id != 0:
                    intersection.three_tile_ids.append(tile_id)
                    tile = self.tiles[tile_id] if tile_id < len(self.tiles) and self.tiles[tile_id] else None
                    if tile:
                        intersection.three_tile_types.append(tile.type)
                        intersection.three_tile_values.append(tile.value)
                        pips = pips_from_tile_value(tile.value)
                        intersection.three_tile_pips.append(pips)
                        if tile.value >= 2 and tile.value <= 12:
                            intersection.all_tile_values[tile.value - 2] += 1
                        if tile.type == "Field":
                            intersection.all_tile_types[0] += 1
                            intersection.all_tile_pips[0] += pips
                        elif tile.type == "Mountain":
                            intersection.all_tile_types[1] += 1
                            intersection.all_tile_pips[1] += pips
                        elif tile.type == "Forest":
                            intersection.all_tile_types[2] += 1
                            intersection.all_tile_pips[2] += pips
                        elif tile.type == "Hill":
                            intersection.all_tile_types[3] += 1
                            intersection.all_tile_pips[3] += pips
                        elif tile.type == "Pasture":
                            intersection.all_tile_types[4] += 1
                            intersection.all_tile_pips[4] += pips
                   
                        # Assign intersection to tile corner, skip if intersection_id in INTERSECTION_IN_WATER
                        for corner in tile.corners:
                            if corner_indices[corner.location] == corner_idx and corner.intersection == 0 and i not in self.INTERSECTION_IN_WATER:
                                corner.intersection = intersection.id
                                break
   
        self._create_list_of_roads_connected_to_intersection()

    def _add_empty_edges_and_corners(self) -> None:
        """Initialize empty edges and corners for each tile.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | add_empty_edges_and_corners\n")
        for tile in self.tiles:
            if tile:
                tile.edges = [
                    Edge("NE"), Edge("E"), Edge("SE"), Edge("SW"), Edge("W"), Edge("NW")
                ]
                tile.corners = [
                    Corner("N"), Corner("EH"), Corner("EL"), Corner("S"), Corner("WL"), Corner("WH")
                ]

    def _create_list_of_roads_connected_to_intersection(self) -> None:
        """Create a list of roads connected to each intersection.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | create_list_of_roads_connected_to_intersection\n")
        for i, intersection in enumerate(self.intersections):
            if intersection is None:
                self.list_of_roads_connected_to_intersection[i] = []
                continue
            help_list: List[Tuple[int, int]] = []
            for road in self.roads:
                if road: # Only check non-None roads
                    road_id = road.id
                    if road_id[0] == intersection.id or road_id[1] == intersection.id:
                        # Skip roads involving intersections in INTERSECTION_IN_WATER
                        if road_id[0] in self.INTERSECTION_IN_WATER or road_id[1] in self.INTERSECTION_IN_WATER:
                            continue
                        help_list.append(road_id)
            self.list_of_roads_connected_to_intersection[intersection.id] = help_list
            intersection.three_roads = help_list

    def _add_three_tile_values(self) -> None:
        """Add tile values for each intersection's neighboring tiles.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | add_three_tile_values\n")
   
        for intersection in self.intersections:
            if intersection is None:
                continue
            # Initialize lists for tile values
            intersection.three_tile_values = []
            # Initialize count of tile values (2 to 12, indices 0 to 10)
            NT_value = [0] * 11 # [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
       
            for tile_id in intersection.three_tile_ids:
                tile = self.tiles[tile_id] if tile_id < len(self.tiles) else None
                if tile and tile.type != "Sea":
                    intersection.three_tile_values.append(tile.value)
                    if tile.value >= 2 and tile.value <= 12:
                        NT_value[tile.value - 2] += 1

            self.intersection_to_corners = defaultdict(list)  # int → list[(tile, corner_location)]       

            intersection.all_tile_values = NT_value

    def _add_three_intersection_ids(self) -> None:
        """Add neighboring intersection IDs for each intersection based on connected roads.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | add_three_intersection_ids\n")
        for intersection in self.intersections:
            if intersection is None:
                continue

            # Rebuild from scratch. This method is called multiple times during
            # board generation/loading, so appending without clearing creates
            # duplicate neighbor ids.
            intersection.three_intersection_ids = []

            if self.list_of_roads_connected_to_intersection[intersection.id]:
                for road in self.list_of_roads_connected_to_intersection[intersection.id]:
                    if road[0] == intersection.id:
                        intersection.three_intersection_ids.append(road[1])
                    elif road[1] == intersection.id:
                        intersection.three_intersection_ids.append(road[0])

    def _add_two_tile_attributes(self) -> None:
        """Add tile attributes to roads based on adjacent tiles.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | add_two_tile_attributes\n")
   
        # Assign tiles to roads
        for road in self.roads:
            if road:
                road.two_tiles = []
                for tile in self.tiles:
                    if tile:
                        for edge in tile.edges:
                            if edge.road == road.id:
                                road.two_tiles.append([tile.id, tile.type, tile.value])

    def _update_intersection_types(self) -> None:
        """Update intersection types for intersections in water.
 
        Sets the type attribute to None for intersections that are not adjacent to any land tiles.
 
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | update_intersection_types\n")
        for intersection in self.intersections:
            if intersection is None:
                continue
            if intersection.id in self.INTERSECTION_IN_WATER:
                intersection.type = None # Set type to None for non-buildable intersections

    def _add_ports(self) -> None:
        """Add ports to intersections with randomized port types.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | _add_ports\n")
   
        # Shuffle port types for random assignment
        port_types = copy.copy(self.LIST_OF_PORTTYPES)
        random.shuffle(port_types)
   
        # Assign port types to intersection pairs
        for i, port_pair in enumerate(self.INTERSECTIONS_ARE_PORT):
            if i < len(port_types):
                port_type = port_types[i]
                for intersection_id in port_pair:
                    if 0 <= intersection_id < len(self.intersections) and self.intersections[intersection_id] is not None:
                        self.intersections[intersection_id].port_tf = True
                        self.intersections[intersection_id].port_type = port_type
                    else:
                        if FNFREQ == "Y":
                            with open(FILENAME_FREQ, "a") as f:
                                f.write(f"board.py | _add_ports | Invalid or None intersection ID: {intersection_id}\n")
   
        # Update tile corners for port intersections
        port_intersection_ids = []
        for portpair in self.INTERSECTIONS_ARE_PORT:
            port_intersection_ids.extend(portpair)
        for intersection in self.intersections:
            if intersection is None:
                continue
            if intersection.id in port_intersection_ids:
                for tile in self.tiles:
                    if tile:
                        for c in tile.corners:
                            if c.intersection == intersection.id:
                                c.port_type = intersection.port_type

    def _complete_edges(self) -> None:
        """Assign road IDs to tile edges based on corner intersections.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | complete_edges\n")
   
        for tile in self.tiles:
            if tile:
                list_of_corners = [corner.intersection for corner in tile.corners]
                for edge in tile.edges:
                    if edge.location == "NE":
                        road = tuple(sorted([list_of_corners[0], list_of_corners[1]]))
                        if road[0] in self.INTERSECTION_IN_WATER or road[1] in self.INTERSECTION_IN_WATER:
                            edge.road = (0, 0) # Invalid road
                        else:
                            edge.road = road
                    elif edge.location == "E":
                        road = tuple(sorted([list_of_corners[1], list_of_corners[2]]))
                        if road[0] in self.INTERSECTION_IN_WATER or road[1] in self.INTERSECTION_IN_WATER:
                            edge.road = (0, 0)
                        else:
                            edge.road = road
                    elif edge.location == "SE":
                        road = tuple(sorted([list_of_corners[2], list_of_corners[3]]))
                        if road[0] in self.INTERSECTION_IN_WATER or road[1] in self.INTERSECTION_IN_WATER:
                            edge.road = (0, 0)
                        else:
                            edge.road = road
                    elif edge.location == "SW":
                        road = tuple(sorted([list_of_corners[3], list_of_corners[4]]))
                        if road[0] in self.INTERSECTION_IN_WATER or road[1] in self.INTERSECTION_IN_WATER:
                            edge.road = (0, 0)
                        else:
                            edge.road = road
                    elif edge.location == "W":
                        road = tuple(sorted([list_of_corners[4], list_of_corners[5]]))
                        if road[0] in self.INTERSECTION_IN_WATER or road[1] in self.INTERSECTION_IN_WATER:
                            edge.road = (0, 0)
                        else:
                            edge.road = road
                    elif edge.location == "NW":
                        road = tuple(sorted([list_of_corners[5], list_of_corners[0]]))
                        if road[0] in self.INTERSECTION_IN_WATER or road[1] in self.INTERSECTION_IN_WATER:
                            edge.road = (0, 0)
                        else:
                            edge.road = road

    def _add_roads(self) -> None:
        """Add roads to the board.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | add_roads\n")
   
        added_roads = set()  # Track added road IDs to avoid duplicates
        for tile in self.tiles:
            if tile:
                for edge in tile.edges:
                    road_id = tuple(sorted(edge.road))
                    if (road_id[0] in self.INTERSECTION_IN_WATER or
                        road_id[1] in self.INTERSECTION_IN_WATER or
                        road_id == (0, 0)):  # Skip invalid roads
                        continue
                    if road_id not in added_roads:
                        self.roads.append(Road(road_id))
                        added_roads.add(road_id)
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"board.py | add_roads | Added {len(self.roads)} roads\n")

    def _is_valid_tile_value_placement(self) -> bool:
        """Check if tiles with values 6 or 8 are not adjacent by ensuring each intersection has at most one tile with value 6 or 8.
     
        Args:
            None
        Returns:
            bool: True if no tiles with values 6 or 8 are adjacent, False otherwise.
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | _is_valid_tile_value_placement\n")
   
        for intersection in self.intersections:
            if intersection is None:
                continue
            count_six_or_eight = sum(1 for value in intersection.three_tile_values if value in [6, 8])
            if count_six_or_eight > 1:
                if MG:
                    with open(FILENAME_MG, "a") as f:
                        f.write(f"board.py | _is_valid_tile_value_placement | Invalid: Intersection {intersection.id} has {count_six_or_eight} tiles with values 6 or 8: {intersection.three_tile_values}\n")
                return False
        return True

    def _get_board(self) -> None:
        """Generate a random board ensuring tiles with values 6 and 8 are not adjacent.
     
        Args:
            None
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | _get_board\n")
   
        tile_types = ["Field"] * 4 + ["Mountain"] * 3 + ["Forest"] * 4 + ["Hill"] * 3 + ["Pasture"] * 4 + ["Desert"]
        tile_values = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]
        max_attempts = 100 # Limit retries to prevent infinite loops
        attempt = 0
   
        while attempt < max_attempts:
            # Reset intersections to clear previous attempt's state
            self.intersections = [None] * 67
            for i in range(67):
                if i not in self.INTERSECTION_IN_WATER:
                    self.intersections[i] = Intersection(i)
            self.tiles = [None] * len(self.ALL_TILE_IDS)
            self.roads = [] # Reset roads to empty list
            self.list_of_roads_connected_to_intersection = [[] for _ in range(67)]
       
            # Shuffle tile types
            random.shuffle(tile_types)
            current_tile_values = tile_values.copy()
            random.shuffle(current_tile_values)
       
            # Assign tile types and values
            type_index = 0
            tile_id_map = {tid: i for i, tid in enumerate(self.ALL_TILE_IDS)}
            for tile_id in self.ALL_TILE_IDS:
                idx = tile_id_map[tile_id]
                if tile_id in self.LIST_OF_LAND_TILES:
                    if type_index < len(tile_types):
                        random_tile_type = tile_types[type_index]
                        type_index += 1
                        if random_tile_type == "Desert":
                            random_tile_value = 0
                        else:
                            random_tile_value = current_tile_values.pop(0) if current_tile_values else 0
                        self.tiles[idx] = Tile(tile_id, random_tile_type, random_tile_value, "Blank")
                elif tile_id in self.LIST_OF_SKIPPED_TILE_IDS:
                    continue
                else:
                    self.tiles[idx] = Tile(tile_id, type_="Sea", value=0, color="Blank")
       
            # Initialize intersections for tile value validation
            self._add_empty_edges_and_corners()
            self._add_intersections()
            self._complete_edges()
       
            # Check if tile value placement is valid
            if self._is_valid_tile_value_placement():
                break
       
            attempt += 1
            if MG:
                with open(FILENAME_MG, "a") as f:
                    f.write(f"board.py | _get_board | Attempt {attempt} failed: Retrying tile value placement\n")
   
        if attempt >= max_attempts:
            raise RuntimeError("Failed to generate a valid board after maximum attempts: 6 and 8 tiles are adjacent")
   
        # Complete board initialization
        self._add_roads()
        self._create_list_of_roads_connected_to_intersection()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_ports()
        self._add_two_tile_attributes()

    def calc_cibi(self) -> List[float]:
        """CIBI six raw imbalance scores (Gen2-compatible order).

        Full composite + norms: ``core.cibi.compute_cibi(self)``.
        """
        from core.cibi import compute_cibi

        return list(compute_cibi(self).as_raw_tuple())

    def save_board(self, filename_save: str = "") -> str:
        """Save the board's tile and port data to a file.

        Args:
            filename_save: Optional path/stem. If empty, writes
                ``Playboard_<timestamp>.txt`` (BS-4 / product naming).
                If it already ends with ``.txt`` or starts with Playboard/PlayBoard,
                used as the full filename.

        Returns:
            Path string written.
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | save_board\n")
        raw = str(filename_save or "").strip()
        if raw == "":
            today = datetime.now().strftime("%d_%b_%Y_%H_%M_%S")
            path = f"Playboard_{today}.txt"
        elif raw.lower().endswith(".txt") or raw.startswith("Playboard") or raw.startswith("PlayBoard"):
            path = raw
        else:
            # Stem only → product underscore naming
            path = f"Playboard_{raw}.txt"
        with open(path, "w", encoding="utf-8") as f:
            for tile in self.tiles:
                if tile:
                    f.write(f"{tile.id}\n")
                    f.write(f"{tile.type}\n")
                    f.write(f"{tile.value}\n")
            for intersection in self.intersections:
                if intersection and intersection.port_tf:
                    f.write(f"{intersection.id}\n")
                    f.write(f"{intersection.port_type}\n")
        return path

    def _board_file_name(self, board_name: str) -> str:
        """
        Return only the filename part of a board path.

        Examples:
            'C:/x/PlayBoard abc.txt' -> 'PlayBoard abc.txt'
            'TestBoard_001.txt'      -> 'TestBoard_001.txt'
        """
        return str(board_name).replace("\\", "/").split("/")[-1]

    def _require_board_file_prefix(
        self,
        board_name: str,
        expected_prefix: str,
        loader_name: str,
    ) -> None:
        """
        Enforce the project naming convention for board files.

        Rules:
            Board.load_board(...) accepts 'PlayBoard…' or 'Playboard…' (BS-4).
            Board.load_test_board(...) only accepts filenames starting with 'TestBoard'.
        """
        filename = self._board_file_name(board_name)

        # PlayBoard loaders: allow both historical "PlayBoard" and product "Playboard_"
        if expected_prefix in ("PlayBoard", "Playboard"):
            if not (
                filename.startswith("PlayBoard")
                or filename.startswith("Playboard")
            ):
                raise ValueError(
                    f"{loader_name} expected a filename starting with "
                    f"'PlayBoard' or 'Playboard', got {filename!r}."
                )
            return

        if not filename.startswith(expected_prefix):
            raise ValueError(
                f"{loader_name} expected a filename starting with "
                f"{expected_prefix!r}, got {filename!r}."
            )

    def _contains_test_board_sections(self, lines: List[str]) -> bool:
        """
        Return True if a file contains TestBoard-only sections.

        PlayBoard files must not contain any of these sections:
            CITIES
            SETTLEMENTS
            ROADS

        TestBoard files may contain them.
        """
        test_sections = {
            "CITIES",
            "[CITIES]",
            "TEST_CITIES",
            "[TEST_CITIES]",
            "SETTLEMENTS",
            "[SETTLEMENTS]",
            "TEST_SETTLEMENTS",
            "[TEST_SETTLEMENTS]",
            "ROADS",
            "[ROADS]",
            "TEST_ROADS",
            "[TEST_ROADS]",
        }

        return any(str(line).strip().upper() in test_sections for line in lines)

    def load_board(self, board_name: str) -> None:
        """
        Load a base PlayBoard file.

        Naming rule:
            This function only accepts filenames starting with 'PlayBoard'.

        PlayBoard purpose:
            A PlayBoard file stores the static board layout only:
                - tile_id
                - tile_type
                - tile_value
                - port_intersection_id
                - port_type

            A PlayBoard file must not contain:
                - CITIES
                - SETTLEMENTS
                - ROADS

        Use Board.load_test_board(...) for TestBoard files that include
        cities, settlements, and/or roads.

        Expected PlayBoard format:
            tile_id
            tile_type
            tile_value
            ...
            port_intersection_id
            port_type
            ...

        Why this parser is deliberately strict:
            Port rows such as ``3 / 3:1 / 4`` can accidentally look like a
            tile block if we only parse ``int / str / int``. Therefore a block
            is accepted as a tile only when the middle line is a valid terrain
            type. Once a non-terrain middle line is found, parsing switches to
            ports.
        """
        self._require_board_file_prefix(
            board_name=board_name,
            expected_prefix="PlayBoard",
            loader_name="Board.load_board()",
        )

        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"board.py | load_board | Loading {board_name}\n")

        valid_tile_types = {
            "Sea",
            "Desert",
            "Mountain",
            "Hill",
            "Forest",
            "Pasture",
            "Field",
        }
        valid_port_types = set(self.LIST_OF_PORTTYPES)
        # Historical / alternate spellings in older PlayBoard files.
        # GUI + trade logic use LIST_OF_PORTTYPES ("2:1 Sheep", not "Wool").
        port_type_aliases = {
            "2:1 Wool": "2:1 Sheep",
            "2:1 wool": "2:1 Sheep",
            "2:1 sheep": "2:1 Sheep",
            "2:1 Grain": "2:1 Wheat",
            "2:1 grain": "2:1 Wheat",
            "2:1 wheat": "2:1 Wheat",
            "2:1 Lumber": "2:1 Wood",
            "2:1 lumber": "2:1 Wood",
            "2:1 wood": "2:1 Wood",
            "2:1 Clay": "2:1 Brick",
            "2:1 clay": "2:1 Brick",
            "2:1 brick": "2:1 Brick",
            "2:1 ore": "2:1 Ore",
            "3:1 ": "3:1",
            "?": "Blank",
        }

        try:
            with open(board_name, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]

            if self._contains_test_board_sections(lines):
                raise ValueError(
                    "Board.load_board() only accepts PlayBoard files. "
                    "A PlayBoard file must contain only tiles and ports. "
                    "It must not contain CITIES, SETTLEMENTS, or ROADS sections. "
                    "Use Board.load_test_board() with a TestBoard file instead."
                )

            print(f"📄 Loaded {len(lines)} non-empty lines from {board_name}")

            idx = 0
            tiles_loaded = 0
            ports_loaded = 0

            # Reset any previous port state. This makes load_board safe even if
            # it is called after _add_ports() or after loading another board.
            for inter in self.intersections:
                if inter is not None:
                    inter.port_tf = False
                    inter.port_type = "Blank"

            for tile in self.tiles:
                if tile:
                    for corner in tile.corners:
                        corner.port_type = "Blank"

            # ──────────────────────────────────────────────────────────
            # 1. Load tile blocks: id / type / value
            # ──────────────────────────────────────────────────────────
            while idx + 2 < len(lines):
                try:
                    tile_id = int(lines[idx])
                    tile_type = lines[idx + 1]

                    # Critical guard:
                    # If the middle line is not a terrain type, we reached
                    # the port section. Example: 3 / 3:1 / 4.
                    if tile_type not in valid_tile_types:
                        break

                    tile_value = int(lines[idx + 2])

                except ValueError:
                    # Malformed tile block or start of port section.
                    break

                updated = False
                for tile in self.tiles:
                    if tile and tile.id == tile_id:
                        tile.type = tile_type
                        tile.value = tile_value
                        tile.color = "Blank"
                        tile.occupied_tf = False
                        tiles_loaded += 1
                        updated = True
                        break

                if not updated:
                    print(f"⚠️  Tile id {tile_id} not found in board structure")

                idx += 3

            # ──────────────────────────────────────────────────────────
            # 2. Load port pairs: intersection_id / port_type
            # ──────────────────────────────────────────────────────────
            while idx + 1 < len(lines):
                try:
                    inter_id = int(lines[idx])
                except ValueError:
                    print(f"⚠️  Skipping malformed port intersection id: {lines[idx]}")
                    idx += 1
                    continue

                port_type = str(lines[idx + 1] or "").strip()
                if port_type in port_type_aliases:
                    aliased = port_type_aliases[port_type]
                    if port_type != aliased:
                        print(
                            f"ℹ️  Port type alias at intersection {inter_id}: "
                            f"{port_type!r} → {aliased!r}"
                        )
                    port_type = aliased

                if port_type not in valid_port_types:
                    print(f"⚠️  Invalid port type for intersection {inter_id}: {port_type}")
                    idx += 2
                    continue

                if 0 <= inter_id < len(self.intersections) and self.intersections[inter_id] is not None:
                    inter = self.intersections[inter_id]
                    inter.port_tf = True
                    inter.port_type = port_type
                    ports_loaded += 1
                else:
                    print(f"⚠️  Invalid intersection id {inter_id} for port")

                idx += 2

            # Sync loaded intersection port data back to tile corners.
            for tile in self.tiles:
                if not tile:
                    continue
                for corner in tile.corners:
                    iid = corner.intersection
                    if 0 <= iid < len(self.intersections):
                        inter = self.intersections[iid]
                        if inter and inter.port_tf:
                            corner.port_type = inter.port_type
                        else:
                            corner.port_type = "Blank"

            print(f"✅ Successfully loaded board from {board_name}")
            print(f"   • {tiles_loaded} tiles updated")
            print(f"   • {ports_loaded} port entries processed")

            if ports_loaded != 18:
                print(
                    f"⚠️  Expected 18 port entries, loaded {ports_loaded}. "
                    "Check the PlayBoard file if this is unexpected."
                )

            # Refresh intersection pip/type aggregates after tile types change
            # (needed after blank topology + explicit playboard load).
            try:
                self._add_intersections()
            except Exception:
                pass

            # Re-run necessary post-load steps. These methods are now safe to
            # call repeatedly because _add_three_intersection_ids clears before
            # rebuilding neighbor ids.
            self._create_list_of_roads_connected_to_intersection()
            self._update_intersection_types()
            self._add_three_intersection_ids()
            self._add_two_tile_attributes()

            if MG:
                with open(FILENAME_MG, "a", encoding="utf-8") as f:
                    f.write(
                        f"board.py | load_board | Successfully loaded {board_name} "
                        f"({tiles_loaded} tiles + {ports_loaded} ports)\n"
                    )

        except FileNotFoundError:
            print(f"❌ load_board: File not found → {board_name}")
            if MG:
                with open(FILENAME_MG, "a", encoding="utf-8") as f:
                    f.write(f"board.py | load_board | File not found: {board_name}\n")

        except Exception as e:
            print(f"❌ load_board error: {e}")
            if MG:
                with open(FILENAME_MG, "a", encoding="utf-8") as f:
                    f.write(f"board.py | load_board | ERROR: {e}\n")
            raise

    def load_test_board(
        self,
        board_name: str,
        players: Optional[List["Player"]] = None,
        *,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """
        Load a TestBoard file.

        Naming rule:
            This function only accepts filenames starting with 'TestBoard'.

        TestBoard purpose:
            A TestBoard file is a standalone test setup used to bypass loading
            a true saved game.

            It contains:
                1. the same base tile/port data as a PlayBoard file
                2. optional CITIES section
                3. optional SETTLEMENTS section
                4. optional ROADS section

        Important distinction:
            PlayBoard files are base-board files only and must be loaded with:
                Board.load_board(...)

            TestBoard files may contain cities, settlements, and roads and must
            be loaded with:
                Board.load_test_board(...)

        Expected TestBoard format:

            tile_id
            tile_type
            tile_value
            ...
            port_intersection_id
            port_type
            ...

            CITIES
            intersection_id
            color
            ...

            SETTLEMENTS
            intersection_id
            color
            ...

            ROADS
            road_id
            color
            ...

        Sections are optional, but when present they must use the exact
        two-line format:
            id
            color

        Accepted road id examples:
            24,25
            24-25
            24 25
            (24, 25)
            [24, 25]

        Behavior:
            1. loads base tile/port data
            2. parses optional CITIES / SETTLEMENTS / ROADS sections
            3. calls validate_test_board(...)
            4. applies valid cities, settlements, and roads to board/player state
        """
        self._require_board_file_prefix(
            board_name=board_name,
            expected_prefix="TestBoard",
            loader_name="Board.load_test_board()",
        )

        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"board.py | load_test_board | Loading {board_name}\n")

        valid_tile_types = {
            "Sea",
            "Desert",
            "Mountain",
            "Hill",
            "Forest",
            "Pasture",
            "Field",
        }

        valid_port_types = set(self.LIST_OF_PORTTYPES)

        section_markers = {
            "CITIES",
            "[CITIES]",
            "TEST_CITIES",
            "[TEST_CITIES]",
            "SETTLEMENTS",
            "[SETTLEMENTS]",
            "TEST_SETTLEMENTS",
            "[TEST_SETTLEMENTS]",
            "ROADS",
            "[ROADS]",
            "TEST_ROADS",
            "[TEST_ROADS]",
        }

        errors: List[str] = []
        warnings: List[str] = []

        def _fail(message: str) -> Dict[str, Any]:
            errors.append(message)

            result = {
                "ok": False,
                "errors": errors,
                "warnings": warnings,
                "cities": [],
                "settlements": [],
                "roads": [],
                "tiles_loaded": 0,
                "ports_loaded": 0,
            }

            if strict:
                raise ValueError(
                    "Invalid TestBoard file:\n"
                    + "\n".join(f"- {err}" for err in errors)
                )

            return result

        def _clean_line(line: str) -> str:
            """
            Remove comments and surrounding whitespace.

            Supports:
                # comment
                // comment
            """
            line = line.strip()

            if "#" in line:
                line = line.split("#", 1)[0].strip()

            if "//" in line:
                line = line.split("//", 1)[0].strip()

            return line

        def _normalize_section_name(line: str) -> str:
            return line.strip().upper()

        def _is_section_marker(line: str) -> bool:
            return _normalize_section_name(line) in section_markers

        def _is_cities_marker(line: str) -> bool:
            return _normalize_section_name(line) in {
                "CITIES",
                "[CITIES]",
                "TEST_CITIES",
                "[TEST_CITIES]",
            }

        def _is_settlements_marker(line: str) -> bool:
            return _normalize_section_name(line) in {
                "SETTLEMENTS",
                "[SETTLEMENTS]",
                "TEST_SETTLEMENTS",
                "[TEST_SETTLEMENTS]",
            }

        def _is_roads_marker(line: str) -> bool:
            return _normalize_section_name(line) in {
                "ROADS",
                "[ROADS]",
                "TEST_ROADS",
                "[TEST_ROADS]",
            }

        def _parse_road_id(text: str) -> Optional[Tuple[int, int]]:
            """
            Parse road id from flexible textual forms.

            Accepted examples:
                24,25
                24-25
                24 25
                (24, 25)
                [24, 25]
            """
            cleaned = str(text).strip()
            cleaned = cleaned.replace("(", "")
            cleaned = cleaned.replace(")", "")
            cleaned = cleaned.replace("[", "")
            cleaned = cleaned.replace("]", "")
            cleaned = cleaned.replace(";", ",")
            cleaned = cleaned.replace("-", ",")
            cleaned = cleaned.replace("|", ",")
            cleaned = cleaned.replace("/", ",")
            cleaned = cleaned.replace("\\", ",")

            if "," in cleaned:
                parts = [p.strip() for p in cleaned.split(",") if p.strip()]
            else:
                parts = [p.strip() for p in cleaned.split() if p.strip()]

            if len(parts) != 2:
                return None

            try:
                a = int(parts[0])
                b = int(parts[1])
            except Exception:
                return None

            if a == b:
                return None

            return tuple(sorted((a, b)))

        def _parse_optional_inline_record(line: str) -> Optional[Tuple[str, str]]:
            """
            Parse optional one-line records.

            Supported:
                24 Blue
                24,25 Blue
                (24,25) Blue

            This is only a convenience. The preferred format remains:
                id
                color
            """
            parts = line.split()

            if len(parts) < 2:
                return None

            color = parts[-1].strip()
            id_part = " ".join(parts[:-1]).strip()

            if not id_part:
                return None

            return id_part, color

        def _parse_intersection_section(
            lines: List[str],
            start_idx: int,
            section_name: str,
        ) -> Tuple[List[Tuple[int, str]], int]:
            """
            Parse CITIES or SETTLEMENTS section.

            Expected two-line format:
                intersection_id
                color

            Also accepts optional inline format:
                intersection_id color
            """
            parsed: List[Tuple[int, str]] = []
            idx = start_idx

            while idx < len(lines):
                line = lines[idx]

                if _is_section_marker(line):
                    break

                inline = _parse_optional_inline_record(line)
                if inline is not None:
                    raw_inter_id, color = inline

                    try:
                        inter_id = int(raw_inter_id)
                    except Exception:
                        errors.append(
                            f"{section_name} line {idx + 1}: invalid intersection id "
                            f"{raw_inter_id!r}; expected integer."
                        )
                        idx += 1
                        continue

                    parsed.append((inter_id, color))
                    idx += 1
                    continue

                if idx + 1 >= len(lines):
                    errors.append(
                        f"{section_name} line {idx + 1}: missing color after "
                        f"intersection id {line!r}."
                    )
                    break

                raw_inter_id = line
                color = lines[idx + 1]

                if _is_section_marker(color):
                    errors.append(
                        f"{section_name} line {idx + 1}: missing color before "
                        f"section {color!r}."
                    )
                    break

                try:
                    inter_id = int(raw_inter_id)
                except Exception:
                    errors.append(
                        f"{section_name} line {idx + 1}: invalid intersection id "
                        f"{raw_inter_id!r}; expected integer."
                    )
                    idx += 2
                    continue

                parsed.append((inter_id, color))
                idx += 2

            return parsed, idx

        def _parse_roads_section(
            lines: List[str],
            start_idx: int,
        ) -> Tuple[List[Tuple[Tuple[int, int], str]], int]:
            """
            Parse ROADS section.

            Returns:
                parsed_roads, next_index
            """
            parsed: List[Tuple[Tuple[int, int], str]] = []
            idx = start_idx

            while idx < len(lines):
                line = lines[idx]

                if _is_section_marker(line):
                    break

                inline = _parse_optional_inline_record(line)
                if inline is not None:
                    raw_road_id, color = inline
                    road_id = _parse_road_id(raw_road_id)

                    if road_id is None:
                        errors.append(
                            f"ROADS line {idx + 1}: invalid road id {raw_road_id!r}; "
                            "expected two intersection ids."
                        )
                        idx += 1
                        continue

                    parsed.append((road_id, color))
                    idx += 1
                    continue

                if idx + 1 >= len(lines):
                    errors.append(
                        f"ROADS line {idx + 1}: missing color after road id {line!r}."
                    )
                    break

                raw_road_id = line
                color = lines[idx + 1]

                if _is_section_marker(color):
                    errors.append(
                        f"ROADS line {idx + 1}: missing color before section {color!r}."
                    )
                    break

                road_id = _parse_road_id(raw_road_id)

                if road_id is None:
                    errors.append(
                        f"ROADS line {idx + 1}: invalid road id {raw_road_id!r}; "
                        "expected two intersection ids."
                    )
                    idx += 2
                    continue

                parsed.append((road_id, color))
                idx += 2

            return parsed, idx

        try:
            with open(board_name, "r", encoding="utf-8") as f:
                lines = [_clean_line(line) for line in f.readlines()]

            lines = [line for line in lines if line]

        except FileNotFoundError:
            message = f"load_test_board: file not found → {board_name}"

            if strict:
                raise FileNotFoundError(message)

            return {
                "ok": False,
                "errors": [message],
                "warnings": [],
                "cities": [],
                "settlements": [],
                "roads": [],
                "tiles_loaded": 0,
                "ports_loaded": 0,
            }

        print(f"📄 Loaded {len(lines)} non-empty TestBoard lines from {board_name}")

        idx = 0
        tiles_loaded = 0
        ports_loaded = 0
        parsed_cities: List[Tuple[int, str]] = []
        parsed_settlements: List[Tuple[int, str]] = []
        parsed_roads: List[Tuple[Tuple[int, int], str]] = []

        # ────────────────────────────────────────────────
        # Reset port state before loading board data
        # ────────────────────────────────────────────────
        for inter in self.intersections:
            if inter is not None:
                inter.port_tf = False
                inter.port_type = "Blank"

        for tile in self.tiles:
            if tile:
                for corner in tile.corners:
                    corner.port_type = "Blank"

        # ────────────────────────────────────────────────
        # 1. Load tile blocks: tile_id / tile_type / tile_value
        # ────────────────────────────────────────────────
        while idx < len(lines):
            if _is_section_marker(lines[idx]):
                break

            if idx + 2 >= len(lines):
                return _fail(
                    f"Unexpected end of file while reading tile block near line {idx + 1}."
                )

            try:
                tile_id = int(lines[idx])
                tile_type = lines[idx + 1]

                if tile_type not in valid_tile_types:
                    # This means we reached port rows.
                    break

                tile_value = int(lines[idx + 2])

            except ValueError:
                break

            updated = False
            for tile in self.tiles:
                if tile and tile.id == tile_id:
                    tile.type = tile_type
                    tile.value = tile_value
                    tile.color = "Blank"
                    tile.occupied_tf = False
                    updated = True
                    tiles_loaded += 1
                    break

            if not updated:
                warnings.append(f"Tile id {tile_id} not found in board structure.")

            idx += 3

        # ────────────────────────────────────────────────
        # 2. Load port pairs until CITIES, SETTLEMENTS, or ROADS
        # ────────────────────────────────────────────────
        while idx < len(lines):
            if _is_section_marker(lines[idx]):
                break

            if idx + 1 >= len(lines):
                return _fail(
                    f"Unexpected end of file while reading port block near line {idx + 1}."
                )

            try:
                inter_id = int(lines[idx])
            except ValueError:
                return _fail(
                    f"Unexpected format near line {idx + 1}: {lines[idx]!r}. "
                    "Expected port intersection id or a section marker like CITIES, "
                    "SETTLEMENTS, or ROADS."
                )

            port_type = lines[idx + 1]

            if port_type not in valid_port_types:
                return _fail(
                    f"Invalid port type near line {idx + 2}: {port_type!r}. "
                    f"Expected one of {sorted(valid_port_types)} or a section marker."
                )

            if 0 <= inter_id < len(self.intersections) and self.intersections[inter_id] is not None:
                inter = self.intersections[inter_id]
                inter.port_tf = True
                inter.port_type = port_type
                ports_loaded += 1
            else:
                warnings.append(f"Invalid intersection id {inter_id} for port; skipped.")

            idx += 2

        # ────────────────────────────────────────────────
        # 3. Load optional CITIES / SETTLEMENTS / ROADS sections
        # ────────────────────────────────────────────────
        seen_cities_section = False
        seen_settlement_section = False
        seen_roads_section = False

        while idx < len(lines):
            marker = lines[idx]

            if _is_cities_marker(marker):
                if seen_cities_section:
                    errors.append(f"Duplicate CITIES section near line {idx + 1}.")
                seen_cities_section = True

                section_items, next_idx = _parse_intersection_section(
                    lines,
                    idx + 1,
                    "CITIES",
                )
                parsed_cities.extend(section_items)
                idx = next_idx
                continue

            if _is_settlements_marker(marker):
                if seen_settlement_section:
                    errors.append(f"Duplicate SETTLEMENTS section near line {idx + 1}.")
                seen_settlement_section = True

                section_items, next_idx = _parse_intersection_section(
                    lines,
                    idx + 1,
                    "SETTLEMENTS",
                )
                parsed_settlements.extend(section_items)
                idx = next_idx
                continue

            if _is_roads_marker(marker):
                if seen_roads_section:
                    errors.append(f"Duplicate ROADS section near line {idx + 1}.")
                seen_roads_section = True

                section_items, next_idx = _parse_roads_section(lines, idx + 1)
                parsed_roads.extend(section_items)
                idx = next_idx
                continue

            return _fail(
                f"Unexpected section marker or line near line {idx + 1}: {marker!r}. "
                "Expected CITIES, SETTLEMENTS, or ROADS."
            )

        if errors:
            result = {
                "ok": False,
                "errors": errors,
                "warnings": warnings,
                "cities": parsed_cities,
                "settlements": parsed_settlements,
                "roads": parsed_roads,
                "tiles_loaded": tiles_loaded,
                "ports_loaded": ports_loaded,
            }

            if strict:
                raise ValueError(
                    "Invalid TestBoard file:\n"
                    + "\n".join(f"- {err}" for err in errors)
                )

            return result

        # ────────────────────────────────────────────────
        # 4. Sync port data back to tile corners
        # ────────────────────────────────────────────────
        for tile in self.tiles:
            if not tile:
                continue

            for corner in tile.corners:
                iid = corner.intersection

                if 0 <= iid < len(self.intersections):
                    inter = self.intersections[iid]
                    if inter and inter.port_tf:
                        corner.port_type = inter.port_type
                    else:
                        corner.port_type = "Blank"

        # Re-run post-load board data steps before validating buildings/roads.
        self._create_list_of_roads_connected_to_intersection()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_two_tile_attributes()

        # Rebuild reverse mapping for intersections -> corners if needed.
        from collections import defaultdict

        self.intersection_to_corners = defaultdict(list)
        for tile in self.tiles:
            if tile:
                for corner in tile.corners:
                    iid = corner.intersection
                    if iid > 0:
                        self.intersection_to_corners[iid].append((tile, corner.location))

        # ────────────────────────────────────────────────
        # 5. Validate and apply cities/settlements/roads
        # ────────────────────────────────────────────────
        result = self.validate_test_board(
            settlements=parsed_settlements,
            roads=parsed_roads,
            players=players,
            cities=parsed_cities,
            apply_to_board=True,
            strict=strict,
        )

        result["tiles_loaded"] = tiles_loaded
        result["ports_loaded"] = ports_loaded
        result["cities_loaded"] = len(parsed_cities)
        result["settlements_loaded"] = len(parsed_settlements)
        result["roads_loaded"] = len(parsed_roads)
        result["cities_section_found"] = seen_cities_section
        result["settlement_section_found"] = seen_settlement_section
        result["roads_section_found"] = seen_roads_section

        print(f"✅ Successfully loaded TestBoard from {board_name}")
        print(f"   • {tiles_loaded} tiles updated")
        print(f"   • {ports_loaded} port entries processed")
        print(f"   • {len(parsed_cities)} test cities parsed")
        print(f"   • {len(parsed_settlements)} test settlements parsed")
        print(f"   • {len(parsed_roads)} test roads parsed")

        if MG:
            with open(FILENAME_MG, "a", encoding="utf-8") as f:
                f.write(
                    f"board.py | load_test_board | Successfully loaded {board_name} "
                    f"({tiles_loaded} tiles + {ports_loaded} ports + "
                    f"{len(parsed_cities)} cities + "
                    f"{len(parsed_settlements)} settlements + "
                    f"{len(parsed_roads)} roads)\n"
                )

        return result

    def validate_test_board(
        self,
        settlements: List[Tuple[int, str]],
        roads: List[Tuple[Tuple[int, int], str]],
        players: Optional[List["Player"]] = None,
        *,
        cities: Optional[List[Tuple[int, str]]] = None,
        apply_to_board: bool = True,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate and optionally apply a TestBoard position.

        Expected already-parsed input:
            cities:
                [
                    (intersection_id, color),
                    ...
                ]

            settlements:
                [
                    (intersection_id, color),
                    ...
                ]

            roads:
                [
                    ((intersection_id_a, intersection_id_b), color),
                    ...
                ]

        Validation rules:
            - all occupied building intersection IDs must be unique
            - no city/settlement may be placed on water or a nonexistent intersection
            - all road IDs must be unique after normalization
            - all colors must belong to an existing player when players are supplied
            - all roads must exist as valid board roads
            - Catan distance rule must hold between all loaded cities/settlements
            - every city/settlement must touch at least one same-color loaded road
            - every road must touch at least one same-color loaded road or one
              same-color loaded city/settlement
            - malformed input raises/returns an appropriate error message

        If apply_to_board=True and validation succeeds:
            - resets test city/settlement/road state on the board
            - applies cities and settlements with occupy_intersection(...)
            - applies roads with occupy_road(...)
            - updates player.cities / player.settlements / player.roads
            - updates tile corners and tile edges for consistency

        Returns:
            {
                "ok": bool,
                "errors": List[str],
                "warnings": List[str],
                "cities": List[Tuple[int, str]],
                "settlements": List[Tuple[int, str]],
                "roads": List[Tuple[Tuple[int, int], str]],
            }

        Raises:
            ValueError when strict=True and validation fails.
        """

        errors: List[str] = []
        warnings: List[str] = []

        # ────────────────────────────────────────────────
        # Local helpers
        # ────────────────────────────────────────────────
        def _normalize_color(color: Any) -> str:
            return str(color).strip()

        def _normalize_road_id(raw_road_id: Any) -> Optional[Tuple[int, int]]:
            try:
                a, b = tuple(raw_road_id)
                a = int(a)
                b = int(b)
            except Exception:
                return None

            if a == b:
                return None

            return tuple(sorted((a, b)))

        def _road_exists_on_board(road_id: Tuple[int, int]) -> bool:
            road_id = tuple(sorted(road_id))

            # Preferred: check board.roads.
            for road in getattr(self, "roads", []) or []:
                if road is None:
                    continue
                if tuple(sorted(getattr(road, "id", ()))) == road_id:
                    return True

            # Fallback: check tile edges.
            for tile in getattr(self, "tiles", []) or []:
                if tile is None:
                    continue
                for edge in getattr(tile, "edges", []) or []:
                    if tuple(sorted(getattr(edge, "road", (0, 0)))) == road_id:
                        return True

            return False

        def _get_road_object(road_id: Tuple[int, int]):
            road_id = tuple(sorted(road_id))
            for road in getattr(self, "roads", []) or []:
                if road is not None and tuple(sorted(getattr(road, "id", ()))) == road_id:
                    return road
            return None

        def _settlement_distance_ok(a: int, b: int) -> bool:
            """
            True if occupied intersections at a and b do not violate the
            Catan distance rule.
            """
            inter_a = self.intersections[a]
            inter_b = self.intersections[b]

            if inter_a is None or inter_b is None:
                return False

            if b in getattr(inter_a, "three_intersection_ids", []):
                return False

            if a in getattr(inter_b, "three_intersection_ids", []):
                return False

            if hasattr(self, "_distance_between_intersections"):
                try:
                    return self._distance_between_intersections(a, b) > 1
                except Exception:
                    pass

            return True

        def _sync_corner_for_intersection(inter_id: int, kind: str, color: str) -> None:
            """
            Ensure tile corners mirror intersection state.
            """
            if hasattr(self, "intersection_to_corners"):
                for tile, corner_loc in getattr(self, "intersection_to_corners", {}).get(inter_id, []):
                    corner = next(
                        (c for c in getattr(tile, "corners", []) if getattr(c, "location", None) == corner_loc),
                        None,
                    )
                    if corner is not None:
                        corner.kind = kind
                        corner.color = color

            # Fallback: scan all corners by intersection id.
            for tile in getattr(self, "tiles", []) or []:
                if tile is None:
                    continue
                for corner in getattr(tile, "corners", []) or []:
                    if getattr(corner, "intersection", None) == inter_id:
                        corner.kind = kind
                        corner.color = color

        def _sync_edge_for_road(road_id: Tuple[int, int], kind: str, color: str) -> None:
            """
            Ensure tile edges mirror road state.
            """
            road_id = tuple(sorted(road_id))

            for tile in getattr(self, "tiles", []) or []:
                if tile is None:
                    continue
                for edge in getattr(tile, "edges", []) or []:
                    if tuple(sorted(getattr(edge, "road", (0, 0)))) == road_id:
                        edge.kind = kind
                        edge.color = color

        def _reset_test_board_state() -> None:
            """
            Reset only building/ownership state, not tile types/values/ports.
            """
            # Reset intersections.
            for inter in getattr(self, "intersections", []) or []:
                if inter is None:
                    continue

                inter.face = "Blank"
                inter.occupied_tf = False
                inter.color = "Blank"
                inter.can_build_tf = True
                inter.game_round = getattr(self, "round", 0)
                inter.game_turn = getattr(self, "turn", 0)
                inter.placement_step = -1

            # Water intersections should remain unavailable.
            for inter_id in getattr(self, "INTERSECTION_IN_WATER", []) or []:
                if 0 <= inter_id < len(self.intersections) and self.intersections[inter_id] is not None:
                    self.intersections[inter_id].can_build_tf = False
                    self.intersections[inter_id].type = None

            # Reset roads.
            for road in getattr(self, "roads", []) or []:
                if road is None:
                    continue

                road.kind = "Blank"
                road.color = "Blank"
                road.occupied_tf = False
                road.game_round = getattr(self, "round", 0)
                road.game_turn = getattr(self, "turn", 0)
                road.placement_step = -1

            # Reset tile corners/edges and settlement counts.
            for tile in getattr(self, "tiles", []) or []:
                if tile is None:
                    continue

                tile.current_settlements = 0

                for corner in getattr(tile, "corners", []) or []:
                    corner.kind = "Blank"
                    corner.color = "Blank"

                for edge in getattr(tile, "edges", []) or []:
                    edge.kind = "Blank"
                    edge.color = "Blank"

        def _reset_player_state() -> None:
            if not players:
                return

            for player in players:
                player.settlements = []
                player.cities = []
                player.roads = []

        def _player_by_color() -> Dict[str, "Player"]:
            if not players:
                return {}
            return {
                getattr(player, "color", ""): player
                for player in players
                if getattr(player, "color", "")
            }

        def _same_color_loaded_roads_touching_intersection(
            inter_id: int,
            color: str,
            loaded_roads_by_id: Dict[Tuple[int, int], str],
        ) -> List[Tuple[int, int]]:
            connected: List[Tuple[int, int]] = []

            inter = self.intersections[inter_id]
            if inter is None:
                return connected

            for road_id in getattr(inter, "three_roads", []) or []:
                rid = _normalize_road_id(road_id)
                if rid is None:
                    continue
                if loaded_roads_by_id.get(rid) == color:
                    connected.append(rid)

            return connected

        def _same_color_loaded_road_neighbors(
            road_id: Tuple[int, int],
            color: str,
            loaded_roads_by_id: Dict[Tuple[int, int], str],
        ) -> List[Tuple[int, int]]:
            neighbors: List[Tuple[int, int]] = []
            a, b = road_id

            for other_road_id, other_color in loaded_roads_by_id.items():
                if other_road_id == road_id:
                    continue
                if other_color != color:
                    continue

                if a in other_road_id or b in other_road_id:
                    neighbors.append(other_road_id)

            return neighbors

        def _same_color_loaded_buildings_touching_road(
            road_id: Tuple[int, int],
            color: str,
            loaded_buildings_by_id: Dict[int, str],
        ) -> List[int]:
            a, b = road_id
            touching: List[int] = []

            if loaded_buildings_by_id.get(a) == color:
                touching.append(a)

            if loaded_buildings_by_id.get(b) == color:
                touching.append(b)

            return touching

        def _format_errors() -> str:
            return "Invalid TestBoard:\n" + "\n".join(f"- {err}" for err in errors)

        def _normalize_buildings(
            raw_items: List[Tuple[int, str]],
            label: str,
            allowed_colors: Set[str],
        ) -> List[Tuple[int, str]]:
            normalized: List[Tuple[int, str]] = []

            for idx, item in enumerate(raw_items):
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    errors.append(
                        f"{label}[{idx}] has unexpected format {item!r}; "
                        "expected (intersection_id, color)."
                    )
                    continue

                raw_inter_id, raw_color = item

                try:
                    inter_id = int(raw_inter_id)
                except Exception:
                    errors.append(
                        f"{label}[{idx}] has invalid intersection id "
                        f"{raw_inter_id!r}; expected int."
                    )
                    continue

                color = _normalize_color(raw_color)

                if color not in allowed_colors:
                    errors.append(
                        f"{label}[{idx}] uses invalid color {color!r}; "
                        f"expected one of {sorted(allowed_colors)}."
                    )
                    continue

                if not (0 <= inter_id < len(self.intersections)):
                    errors.append(
                        f"{label}[{idx}] intersection id {inter_id} is outside "
                        f"valid range 0..{len(self.intersections) - 1}."
                    )
                    continue

                if inter_id in getattr(self, "INTERSECTION_IN_WATER", []):
                    errors.append(f"{label}[{idx}] intersection id {inter_id} is in water.")
                    continue

                if self.intersections[inter_id] is None:
                    errors.append(
                        f"{label}[{idx}] intersection id {inter_id} does not exist on this board."
                    )
                    continue

                normalized.append((inter_id, color))

            return normalized

        # ────────────────────────────────────────────────
        # 1. Validate input container shape
        # ────────────────────────────────────────────────
        if cities is None:
            cities = []

        if settlements is None:
            errors.append("settlements is None; expected List[Tuple[int, str]].")
            settlements = []

        if roads is None:
            errors.append("roads is None; expected List[Tuple[Tuple[int, int], str]].")
            roads = []

        if not isinstance(cities, list):
            errors.append(f"cities has unexpected type {type(cities).__name__}; expected list.")
            cities = []

        if not isinstance(settlements, list):
            errors.append(f"settlements has unexpected type {type(settlements).__name__}; expected list.")
            settlements = []

        if not isinstance(roads, list):
            errors.append(f"roads has unexpected type {type(roads).__name__}; expected list.")
            roads = []

        # ────────────────────────────────────────────────
        # 2. Determine allowed colors
        # ────────────────────────────────────────────────
        color_to_player = _player_by_color()

        if players:
            allowed_colors: Set[str] = set(color_to_player.keys())
        else:
            # Fallback for board-only testing.
            allowed_colors = {"Blue", "Red", "White", "Orange"}

        # ────────────────────────────────────────────────
        # 3. Normalize cities and settlements
        # ────────────────────────────────────────────────
        normalized_cities = _normalize_buildings(cities, "cities", allowed_colors)
        normalized_settlements = _normalize_buildings(settlements, "settlements", allowed_colors)

        all_buildings = [
            ("City", inter_id, color)
            for inter_id, color in normalized_cities
        ] + [
            ("Settlement", inter_id, color)
            for inter_id, color in normalized_settlements
        ]

        seen_building_intersections: Set[int] = set()

        for kind, inter_id, color in all_buildings:
            if inter_id in seen_building_intersections:
                errors.append(
                    f"Duplicate building intersection id: {inter_id}. "
                    "An intersection cannot contain both a city and a settlement."
                )
            seen_building_intersections.add(inter_id)

        loaded_buildings_by_id: Dict[int, str] = {
            inter_id: color
            for _, inter_id, color in all_buildings
        }

        # ────────────────────────────────────────────────
        # 4. Normalize roads
        # ────────────────────────────────────────────────
        normalized_roads: List[Tuple[Tuple[int, int], str]] = []
        seen_roads: Set[Tuple[int, int]] = set()

        for idx, item in enumerate(roads):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                errors.append(
                    f"roads[{idx}] has unexpected format {item!r}; "
                    "expected ((intersection_id_a, intersection_id_b), color)."
                )
                continue

            raw_road_id, raw_color = item
            road_id = _normalize_road_id(raw_road_id)
            color = _normalize_color(raw_color)

            if road_id is None:
                errors.append(
                    f"roads[{idx}] has invalid road id {raw_road_id!r}; "
                    "expected two different intersection ids."
                )
                continue

            if color not in allowed_colors:
                errors.append(
                    f"roads[{idx}] uses invalid color {color!r}; "
                    f"expected one of {sorted(allowed_colors)}."
                )
                continue

            if road_id in seen_roads:
                errors.append(f"Duplicate road id: {road_id}.")
                continue

            seen_roads.add(road_id)

            a, b = road_id

            if not (0 <= a < len(self.intersections)) or self.intersections[a] is None or a in self.INTERSECTION_IN_WATER:
                errors.append(f"Road {road_id} has invalid endpoint {a}.")
                continue

            if not (0 <= b < len(self.intersections)) or self.intersections[b] is None or b in self.INTERSECTION_IN_WATER:
                errors.append(f"Road {road_id} has invalid endpoint {b}.")
                continue

            if not _road_exists_on_board(road_id):
                errors.append(f"Road {road_id} is not a valid board road.")
                continue

            normalized_roads.append((road_id, color))

        loaded_roads_by_id: Dict[Tuple[int, int], str] = {
            road_id: color for road_id, color in normalized_roads
        }

        # ────────────────────────────────────────────────
        # 5. Distance rule across loaded cities/settlements
        # ────────────────────────────────────────────────
        building_ids = [inter_id for _, inter_id, _ in all_buildings]

        for i in range(len(building_ids)):
            for j in range(i + 1, len(building_ids)):
                a = building_ids[i]
                b = building_ids[j]

                if not _settlement_distance_ok(a, b):
                    errors.append(
                        f"Distance rule violated between occupied intersections {a} and {b}."
                    )

        # ────────────────────────────────────────────────
        # 6. Every city/settlement must touch same-color road
        # ────────────────────────────────────────────────
        for kind, inter_id, color in all_buildings:
            same_color_roads = _same_color_loaded_roads_touching_intersection(
                inter_id,
                color,
                loaded_roads_by_id,
            )

            if not same_color_roads:
                errors.append(
                    f"{kind} {inter_id} ({color}) has no connected road with the same color."
                )

        # ────────────────────────────────────────────────
        # 7. Every road must touch same-color road or building
        # ────────────────────────────────────────────────
        for road_id, color in normalized_roads:
            same_color_road_neighbors = _same_color_loaded_road_neighbors(
                road_id,
                color,
                loaded_roads_by_id,
            )

            same_color_buildings = _same_color_loaded_buildings_touching_road(
                road_id,
                color,
                loaded_buildings_by_id,
            )

            if not same_color_road_neighbors and not same_color_buildings:
                errors.append(
                    f"Road {road_id} ({color}) is isolated: it touches no same-color "
                    "road and no same-color city/settlement."
                )

        # ────────────────────────────────────────────────
        # 8. Stop before mutation if invalid
        # ────────────────────────────────────────────────
        if errors:
            result = {
                "ok": False,
                "errors": errors,
                "warnings": warnings,
                "cities": normalized_cities,
                "settlements": normalized_settlements,
                "roads": normalized_roads,
            }

            if strict:
                raise ValueError(_format_errors())

            return result

        # ────────────────────────────────────────────────
        # 9. Apply board/player state
        # ────────────────────────────────────────────────
        if apply_to_board:
            _reset_test_board_state()
            _reset_player_state()

            # Rebuild road/intersection helper maps before applying.
            if hasattr(self, "_create_list_of_roads_connected_to_intersection"):
                self._create_list_of_roads_connected_to_intersection()

            if hasattr(self, "_add_three_intersection_ids"):
                self._add_three_intersection_ids()

            placement_step = 0

            # Apply cities first, then settlements.
            for inter_id, color in normalized_cities:
                self.occupy_intersection(
                    intersection_id=inter_id,
                    kind="City",
                    color=color,
                    placement_step=placement_step,
                )
                _sync_corner_for_intersection(inter_id, "City", color)

                if players:
                    player = color_to_player.get(color)
                    if player is not None and inter_id not in player.cities:
                        player.cities.append(inter_id)

                placement_step += 1

            for inter_id, color in normalized_settlements:
                self.occupy_intersection(
                    intersection_id=inter_id,
                    kind="Settlement",
                    color=color,
                    placement_step=placement_step,
                )
                _sync_corner_for_intersection(inter_id, "Settlement", color)

                if players:
                    player = color_to_player.get(color)
                    if player is not None and inter_id not in player.settlements:
                        player.settlements.append(inter_id)

                placement_step += 1

            # Apply roads.
            for road_id, color in normalized_roads:
                self.occupy_road(
                    road_id=road_id,
                    kind="Road",
                    color=color,
                    placement_step=placement_step,
                )
                _sync_edge_for_road(road_id, "Road", color)

                if players:
                    player = color_to_player.get(color)
                    if player is not None and road_id not in player.roads:
                        player.roads.append(road_id)

                placement_step += 1

            # Rebuild board helper lists after mutation.
            if hasattr(self, "_create_list_of_roads_connected_to_intersection"):
                self._create_list_of_roads_connected_to_intersection()

            if hasattr(self, "_add_three_intersection_ids"):
                self._add_three_intersection_ids()

            if hasattr(self, "_add_two_tile_attributes"):
                self._add_two_tile_attributes()

            # Update ports/trade rates if players were provided.
            if players:
                for player in players:
                    if hasattr(player, "update_trade_rates"):
                        player.update_trade_rates(self)

        # ────────────────────────────────────────────────
        # 10. Final post-apply consistency checks
        # ────────────────────────────────────────────────
        post_errors: List[str] = []

        if apply_to_board:
            for inter_id, color in normalized_cities:
                inter = self.intersections[inter_id]
                if inter is None or not getattr(inter, "occupied_tf", False):
                    post_errors.append(f"Post-check failed: city {inter_id} is not occupied.")
                elif getattr(inter, "color", None) != color:
                    post_errors.append(
                        f"Post-check failed: city {inter_id} color is "
                        f"{getattr(inter, 'color', None)!r}, expected {color!r}."
                    )
                elif getattr(inter, "face", None) != "City":
                    post_errors.append(
                        f"Post-check failed: city {inter_id} face is "
                        f"{getattr(inter, 'face', None)!r}, expected 'City'."
                    )

            for inter_id, color in normalized_settlements:
                inter = self.intersections[inter_id]
                if inter is None or not getattr(inter, "occupied_tf", False):
                    post_errors.append(f"Post-check failed: settlement {inter_id} is not occupied.")
                elif getattr(inter, "color", None) != color:
                    post_errors.append(
                        f"Post-check failed: settlement {inter_id} color is "
                        f"{getattr(inter, 'color', None)!r}, expected {color!r}."
                    )
                elif getattr(inter, "face", None) != "Settlement":
                    post_errors.append(
                        f"Post-check failed: settlement {inter_id} face is "
                        f"{getattr(inter, 'face', None)!r}, expected 'Settlement'."
                    )

            for road_id, color in normalized_roads:
                road = _get_road_object(road_id)
                if road is None or not getattr(road, "occupied_tf", False):
                    post_errors.append(f"Post-check failed: road {road_id} is not occupied.")
                elif getattr(road, "color", None) != color:
                    post_errors.append(
                        f"Post-check failed: road {road_id} color is "
                        f"{getattr(road, 'color', None)!r}, expected {color!r}."
                    )

            if players:
                for inter_id, color in normalized_cities:
                    player = color_to_player.get(color)
                    if player is not None and inter_id not in player.cities:
                        post_errors.append(
                            f"Post-check failed: city {inter_id} ({color}) is not in player.cities."
                        )

                for inter_id, color in normalized_settlements:
                    player = color_to_player.get(color)
                    if player is not None and inter_id not in player.settlements:
                        post_errors.append(
                            f"Post-check failed: settlement {inter_id} ({color}) is not in player.settlements."
                        )

                for road_id, color in normalized_roads:
                    player = color_to_player.get(color)
                    if player is not None and road_id not in player.roads:
                        post_errors.append(
                            f"Post-check failed: road {road_id} ({color}) is not in player.roads."
                        )

        if post_errors:
            errors.extend(post_errors)

            result = {
                "ok": False,
                "errors": errors,
                "warnings": warnings,
                "cities": normalized_cities,
                "settlements": normalized_settlements,
                "roads": normalized_roads,
            }

            if strict:
                raise ValueError(_format_errors())

            return result

        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "cities": normalized_cities,
            "settlements": normalized_settlements,
            "roads": normalized_roads,
        }

    def occupy_intersection(self, intersection_id: int, kind: str, color: str, 
                           placement_step: int = -1) -> None:
        """Occupy an intersection with a settlement or city.
        
        Board-only operation:
        - Updates intersection state
        - Blocks adjacent intersections
        - Updates tile corners and current_settlement count
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write(f"board.py | occupy_intersection\n")

        if intersection_id < 0 or intersection_id >= len(self.intersections):
            return
        inter = self.intersections[intersection_id]
        if inter is None:
            return

        # Update intersection
        inter.occupied_tf = True
        inter.face = kind
        inter.can_build_tf = False
        inter.color = color
        inter.game_round = self.round
        inter.game_turn = self.turn
        inter.placement_step = placement_step

        # Block adjacent intersections
        self._block_adjacent_intersections(intersection_id)
        if self.round >= 0:  # permanent block after setup phase
            self._block_adjacent_intersections(intersection_id)

        # Update tile corners + increment settlement count per affected tile
        affected_tiles = self.intersection_to_corners.get(intersection_id, [])
        for tile, corner_loc in affected_tiles:
            corner = next((c for c in tile.corners if c.location == corner_loc), None)
            if corner is not None:
                corner.kind = kind
                corner.color = color
                tile.current_settlements += 1   # important for later resource calculations

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"board.py | occupy_intersection | {kind} at {intersection_id} by {color} "
                        f"(step={placement_step})\n")


    def occupy_road(
        self,
        road_id: Tuple[int, int],
        kind: str,
        color: str,
        placement_step: int = -1
    ) -> None:
        """
        Occupy a road.

        Board-only operation:
            - updates or creates the Road object
            - updates tile edge kind/color
            - keeps board.roads and tile.edges consistent

        Important:
            Existing roads must still update tile edges. The old version returned
            immediately after updating the Road object, which could leave tile.edges
            stale.
        """
        if FNFREQ == "Y":
            with open(FILENAME_FREQ, "a") as f:
                f.write("board.py | occupy_road\n")

        road_id_tuple = tuple(sorted(road_id))

        road_obj = None

        for road in self.roads:
            if road and tuple(sorted(road.id)) == road_id_tuple:
                road_obj = road
                break

        if road_obj is None:
            road_obj = Road(road_id_tuple)
            self.roads.append(road_obj)

        # Update Road object
        road_obj.occupied_tf = True
        road_obj.kind = kind
        road_obj.color = color
        road_obj.game_round = self.round
        road_obj.game_turn = self.turn
        road_obj.placement_step = placement_step

        # Always update tile edges as well
        for tile in self.tiles:
            if tile:
                for edge in tile.edges:
                    if tuple(sorted(edge.road)) == road_id_tuple:
                        edge.kind = kind
                        edge.color = color

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(
                    f"board.py | occupy_road | {road_id_tuple} {kind} {color} "
                    f"(step={placement_step})\n"
                )

    def can_build_road_for_color_tf(self, road_id: List[int], color: str) -> bool:
        """Check if a road can be built by a player.
    
        Args:
            road_id: List of two intersection IDs.
            color: Player color.
        Returns:
            str: True if buildable, False if occupied or if invalid.
        """
        road_id_tuple = tuple(sorted(road_id))
        # Check if road is valid by looking at tile edges
        valid_road = False
        for tile in self.tiles:
            if tile:
                for edge in tile.edges:
                    if tuple(sorted(edge.road)) == road_id_tuple:
                        valid_road = True
                        break
            if valid_road:
                break

        if not valid_road or road_id_tuple[0] in self.INTERSECTION_IN_WATER or road_id_tuple[1] in self.INTERSECTION_IN_WATER:
            return False

        # Check if road is already occupied
        for road in self.roads:
            if road and road.id == road_id_tuple and road.occupied_tf:
                return False

        return valid_road and not any(
            r and r.id == road_id_tuple and r.occupied_tf for r in self.roads
        )

    def _block_adjacent_intersections(self, intersection_id: int) -> None:
        """Block adjacent intersections from being built on."""
        intersection = self.intersections[intersection_id]
        if intersection:
            for neighbor_id in intersection.three_intersection_ids:
                if (neighbor_id not in self.INTERSECTION_IN_WATER and
                        self.intersections[neighbor_id] is not None and
                        self.intersections[neighbor_id].can_build_tf):
                    self.intersections[neighbor_id].can_build_tf = False
                    if MG:
                        with open(FILENAME_MG, "a") as f:
                            f.write(f"board.py | _block_adjacent_intersections | "
                                    f"Blocked neighbor {neighbor_id} for {intersection_id}\n")


    def save_game_board_state(self) -> Dict[str, Any]:
        """
        Serialize the complete board state for Game.save_game().

        This is different from save_board()/load_board():
            - save_board()/load_board() are for PlayBoard files only
              and store tiles + ports.
            - save_game_board_state()/load_game_board_state() are for full
              Saved_Game files and include occupied intersections, cities,
              settlements, roads, robber state, and turn metadata.
        """
        tiles: List[Dict[str, Any]] = []
        for tile in getattr(self, "tiles", []) or []:
            if tile is None:
                continue
            tiles.append({
                "id": tile.id,
                "type": tile.type,
                "value": tile.value,
                "color": tile.color,
                "occupied_tf": tile.occupied_tf,
                "current_settlements": getattr(tile, "current_settlements", 0),
            })

        ports: List[Dict[str, Any]] = []
        for inter in getattr(self, "intersections", []) or []:
            if inter is None:
                continue
            if getattr(inter, "port_tf", False):
                ports.append({
                    "intersection_id": inter.id,
                    "port_type": getattr(inter, "port_type", "Blank"),
                })

        buildings: List[Dict[str, Any]] = []
        for inter in getattr(self, "intersections", []) or []:
            if inter is None:
                continue
            if getattr(inter, "occupied_tf", False):
                buildings.append({
                    "intersection_id": inter.id,
                    "kind": getattr(inter, "face", "Settlement"),
                    "color": getattr(inter, "color", "Blank"),
                    "game_round": getattr(inter, "game_round", 0),
                    "game_turn": getattr(inter, "game_turn", 0),
                    "placement_step": getattr(inter, "placement_step", -1),
                })

        roads: List[Dict[str, Any]] = []
        for road in getattr(self, "roads", []) or []:
            if road is None:
                continue
            if getattr(road, "occupied_tf", False):
                roads.append({
                    "road_id": list(tuple(sorted(getattr(road, "id", (0, 0))))),
                    "kind": getattr(road, "kind", "Road"),
                    "color": getattr(road, "color", "Blank"),
                    "game_round": getattr(road, "game_round", 0),
                    "game_turn": getattr(road, "game_turn", 0),
                    "placement_step": getattr(road, "placement_step", -1),
                })

        return {
            "board_name": getattr(self, "board_name", ""),
            "round": getattr(self, "round", 0),
            "turn": getattr(self, "turn", 1),
            "tiles": tiles,
            "ports": ports,
            "buildings": buildings,
            "roads": roads,
        }

    def load_game_board_state(
        self,
        data: Dict[str, Any],
        players: Optional[List["Player"]] = None,
        *,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """
        Restore board state from a Saved_Game file block.

        This method is used by Game.load_game(). It expects the structured
        board payload created by save_game_board_state(). Missing optional
        fields receive safe defaults.

        Consistency work performed here:
            - tile values/types and robber occupancy are restored
            - ports are restored to intersections and tile corners
            - occupied intersections are restored to intersections and corners
            - occupied roads are restored to Road objects and tile edges
            - player settlement/city/road lists are rebuilt from board colors
            - derived road/intersection metadata is refreshed
        """
        if not isinstance(data, dict):
            if strict:
                raise ValueError("Board.load_game_board_state expected a dict payload.")
            return {"ok": False, "errors": ["Invalid board payload"], "warnings": []}

        warnings: List[str] = []

        self.board_name = str(data.get("board_name", getattr(self, "board_name", "LoadedSavedGame")))
        self.round = int(data.get("round", getattr(self, "round", 0)))
        self.turn = int(data.get("turn", getattr(self, "turn", 1)))

        # Restore tiles.
        for tile_data in data.get("tiles", []) or []:
            try:
                tile_id = int(tile_data.get("id"))
            except Exception:
                warnings.append(f"Skipped malformed tile payload: {tile_data!r}")
                continue

            tile = next((t for t in self.tiles if t is not None and t.id == tile_id), None)
            if tile is None:
                warnings.append(f"Saved tile id {tile_id} does not exist on this board.")
                continue

            tile.type = str(tile_data.get("type", tile.type))
            tile.value = int(tile_data.get("value", tile.value))
            tile.color = str(tile_data.get("color", "Blank"))
            tile.occupied_tf = bool(tile_data.get("occupied_tf", False))
            tile.current_settlements = int(tile_data.get("current_settlements", 0))

        # Clear ports and building ownership state.
        for inter in getattr(self, "intersections", []) or []:
            if inter is None:
                continue
            inter.port_tf = False
            inter.port_type = "Blank"
            inter.face = "Blank"
            inter.occupied_tf = False
            inter.color = "Blank"
            inter.can_build_tf = True
            inter.game_round = self.round
            inter.game_turn = self.turn
            inter.placement_step = -1

        for inter_id in getattr(self, "INTERSECTION_IN_WATER", []) or []:
            if 0 <= inter_id < len(self.intersections) and self.intersections[inter_id] is not None:
                self.intersections[inter_id].can_build_tf = False
                self.intersections[inter_id].type = None

        for tile in getattr(self, "tiles", []) or []:
            if tile is None:
                continue
            tile.current_settlements = 0
            for corner in getattr(tile, "corners", []) or []:
                corner.kind = "Blank"
                corner.color = "Blank"
                corner.port_type = "Blank"
            for edge in getattr(tile, "edges", []) or []:
                edge.kind = "Blank"
                edge.color = "Blank"

        for road in getattr(self, "roads", []) or []:
            if road is None:
                continue
            road.kind = "Blank"
            road.color = "Blank"
            road.occupied_tf = False
            road.game_round = self.round
            road.game_turn = self.turn
            road.placement_step = -1

        # Restore ports.
        for port_data in data.get("ports", []) or []:
            try:
                inter_id = int(port_data.get("intersection_id"))
            except Exception:
                warnings.append(f"Skipped malformed port payload: {port_data!r}")
                continue
            if 0 <= inter_id < len(self.intersections) and self.intersections[inter_id] is not None:
                self.intersections[inter_id].port_tf = True
                self.intersections[inter_id].port_type = str(port_data.get("port_type", "Blank"))

        # Rebuild derived topology after tile/port restore.
        self._create_list_of_roads_connected_to_intersection()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_two_tile_attributes()

        from collections import defaultdict
        self.intersection_to_corners = defaultdict(list)
        for tile in self.tiles:
            if tile:
                for corner in tile.corners:
                    iid = corner.intersection
                    if iid > 0:
                        self.intersection_to_corners[iid].append((tile, corner.location))
                    if 0 <= iid < len(self.intersections):
                        inter = self.intersections[iid]
                        if inter and inter.port_tf:
                            corner.port_type = inter.port_type

        if players:
            for player in players:
                player.settlements = []
                player.cities = []
                player.roads = []

        color_to_player = {
            getattr(player, "color", None): player
            for player in (players or [])
            if getattr(player, "color", None)
        }

        # Restore buildings before roads.
        buildings = sorted(
            data.get("buildings", []) or [],
            key=lambda item: int(item.get("placement_step", 9999)) if isinstance(item, dict) else 9999,
        )
        for building in buildings:
            try:
                inter_id = int(building.get("intersection_id"))
            except Exception:
                warnings.append(f"Skipped malformed building payload: {building!r}")
                continue
            if not (0 <= inter_id < len(self.intersections)) or self.intersections[inter_id] is None:
                warnings.append(f"Saved building intersection {inter_id} does not exist.")
                continue

            kind = str(building.get("kind", "Settlement"))
            if kind not in ("Settlement", "City"):
                kind = "Settlement"
            color = str(building.get("color", "Blank"))
            placement_step = int(building.get("placement_step", -1))

            self.occupy_intersection(inter_id, kind, color, placement_step=placement_step)
            inter = self.intersections[inter_id]
            inter.game_round = int(building.get("game_round", self.round))
            inter.game_turn = int(building.get("game_turn", self.turn))

            player = color_to_player.get(color)
            if player is not None:
                if kind == "City":
                    if inter_id not in player.cities:
                        player.cities.append(inter_id)
                else:
                    if inter_id not in player.settlements:
                        player.settlements.append(inter_id)

        # Restore roads.
        roads = sorted(
            data.get("roads", []) or [],
            key=lambda item: int(item.get("placement_step", 9999)) if isinstance(item, dict) else 9999,
        )
        for road_data in roads:
            try:
                a, b = road_data.get("road_id")
                road_id = tuple(sorted((int(a), int(b))))
            except Exception:
                warnings.append(f"Skipped malformed road payload: {road_data!r}")
                continue

            kind = str(road_data.get("kind", "Road"))
            color = str(road_data.get("color", "Blank"))
            placement_step = int(road_data.get("placement_step", -1))

            self.occupy_road(road_id, kind, color, placement_step=placement_step)
            for road in self.roads:
                if road is not None and tuple(sorted(road.id)) == road_id:
                    road.game_round = int(road_data.get("game_round", self.round))
                    road.game_turn = int(road_data.get("game_turn", self.turn))
                    break

            player = color_to_player.get(color)
            if player is not None and road_id not in player.roads:
                player.roads.append(road_id)

        # Final refresh after occupancy restore.
        self._create_list_of_roads_connected_to_intersection()
        self._update_intersection_types()
        self._add_three_intersection_ids()
        self._add_two_tile_attributes()

        for player in players or []:
            try:
                player.update_trade_rates(self)
            except Exception:
                pass

        return {
            "ok": True,
            "errors": [],
            "warnings": warnings,
            "buildings_loaded": len(buildings),
            "roads_loaded": len(roads),
        }

    def write_debug_info(self) -> None:
        """Write all board, tile, intersection, and road attributes to FILENAME_MG for debugging."""
        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write("board.py | write_debug_info | Board\n")
                board_dict = {k: v for k, v in self.__dict__.items() if k not in ['intersections', 'roads', 'tiles', 'list_of_roads_connected_to_intersection']}
                f.write(f"Board Attributes: {board_dict}\n")
                f.write(f" Intersection IDs: {[i.id for i in self.intersections if i is not None]}\n")
                f.write(f" Road IDs: {[road.id for road in self.roads if road]}\n")
                f.write(f" Tile IDs: {[tile.id for tile in self.tiles if tile]}\n")
        
                f.write("board.py | write_debug_info | Tiles\n")
                for tile in self.tiles:
                    if tile:
                        tile_dict = {k: v for k, v in tile.__dict__.items() if k not in ['edges', 'corners']}
                        f.write(f"Tile Attributes: {tile_dict}\n")
                        f.write(" Edges:\n")
                        for edge in tile.edges:
                            f.write(f" Edge (road={edge.road}): {edge.__dict__}\n")
                        f.write(" Corners:\n")
                        for corner in tile.corners:
                            f.write(f" Corner (intersection={corner.intersection}): {corner.__dict__}\n")
                    else:
                        f.write("Tile: None\n")
        
                f.write("board.py | write_debug_info | Intersections\n")
                for i, intersection in enumerate(self.intersections):
                    if intersection is None:
                        f.write(f"Intersection: None\n")
                    else:
                        intersection_dict = intersection.__dict__.copy()
                        f.write(f"Intersection Attributes: {intersection_dict}\n")
        
                f.write("board.py | write_debug_info | Roads\n")
                for road in self.roads:
                    if road:
                        f.write(f"Road Attributes: {road.__dict__}\n")
                    else:
                        f.write("Road: None\n")

    def _distance_between_intersections(self, id1: int, id2: int) -> int:
        """Return shortest road distance between two intersections (BFS). Used for initial placement distance-2 rule."""
        if id1 == id2:
            return 0
        from collections import deque
        visited = set()
        queue = deque([(id1, 0)])
        while queue:
            curr, dist = queue.popleft()
            if curr in visited:
                continue
            visited.add(curr)
            inter = self.intersections[curr]
            if inter:
                for nid in inter.three_intersection_ids:
                    if nid == id2:
                        return dist + 1
                    if nid not in visited and nid not in self.INTERSECTION_IN_WATER:
                        queue.append((nid, dist + 1))
        return 999  # unreachable

    def _get_settlement_intersections_on_tile(self, tile_id: int) -> list[int]:
        """Return list of intersection IDs that have a settlement or city on this tile."""
        inter_ids = []
        tile = self.tiles[tile_id] if 0 <= tile_id < len(self.tiles) else None
        if not tile:
            return inter_ids
        for corner in tile.corners:
            iid = corner.intersection
            if iid > 0 and self.intersections[iid] is not None:
                inter = self.intersections[iid]
                if inter.occupied_tf and inter.face in ("Settlement", "City"):
                    inter_ids.append(iid)
        return inter_ids

    def get_current_settlement_pips(self) -> dict[str, float]:
        """Sum pips from tiles touched by at least one settlement/city (cities count as 1  NOT as 2)."""
        resource_map = {
            "Field":   "wheat",
            "Mountain": "ore",
            "Forest":  "wood",
            "Hill":    "brick",
            "Pasture": "sheep"
        }
        current = {res: 0.0 for res in resource_map.values()}
        visited = set()

        for inter in self.intersections:
            if inter and inter.occupied_tf and inter.face in ("Settlement", "City"):
                for tid in inter.three_tile_ids:
                    if tid in visited:
                        continue
                    tile = self.tiles[tid] if 0 <= tid < len(self.tiles) else None
                    if tile and tile.type in resource_map:
                        p = pips_from_tile_value(tile.value)
                        if p > 0:
                            current[resource_map[tile.type]] += p
                            visited.add(tid)
        return current

    def resource_exploration(self) -> dict[str, dict[str, float]]:
        """
        Approximate remaining pip potential per resource (min / max).
        
        Uses:
        - 2.75 avg settlements per tile when 0–1 real settlement present
        - When 2 real settlements: check distance between them
        → allow 1 more if distance >= 2, else 0 more
        - When 3: 0 remaining
        """
        resource_map = {
            "Field":   "wheat",
            "Mountain": "ore",
            "Forest":  "wood",
            "Hill":    "brick",
            "Pasture": "sheep"
        }

        totals = {res: {"min": 0.0, "max": 0.0} for res in resource_map.values()}

        for tile in self.tiles:
            if not tile or tile.type not in resource_map:
                continue

            pips = pips_from_tile_value(tile.value)
            if pips == 0:
                continue

            res = resource_map[tile.type]
            count = tile.current_settlements

            if count >= 3:
                min_mult = max_mult = 0.0

            elif count <= 1:
                min_mult = 2.0
                max_mult = 2.75

            else:  # exactly 2 settlements → check if third is possible
                inter_ids = self._get_settlement_intersections_on_tile(tile.id)
                if len(inter_ids) != 2:
                    # inconsistency → be conservative
                    min_mult = max_mult = 0.0
                else:
                    dist = self._distance_between_intersections(inter_ids[0], inter_ids[1])
                    if dist >= 2:
                        min_mult = max_mult = 1.0   # one more possible
                    else:
                        min_mult = max_mult = 0.0   # blocked

            contrib_min = pips * min_mult
            contrib_max = pips * max_mult

            totals[res]["min"] += contrib_min
            totals[res]["max"] += contrib_max

        # Optional: round for nicer output
        for res in totals:
            totals[res]["min"] = round(totals[res]["min"], 1)
            totals[res]["max"] = round(totals[res]["max"], 1)

        return totals
    
    def get_vertex_to_rolls(self) -> dict[int, list[list[int]]]:
        """Maps each intersection ID to the dice numbers that produce each resource.
        
        Resource order used by MarkovEvaluator (must match internal matrix):
            0 = Brick   (Hill)
            1 = Wood    (Forest)
            2 = Sheep   (Pasture)
            3 = Wheat   (Field)
            4 = Ore     (Mountain)
        
        Uses your exact constants.py terrain names. Works with both three_tile_ids and legs.
        """
        terrain_to_idx = {
            "Hill":     0,   # Brick
            "Forest":   1,   # Wood
            "Pasture":  2,   # Sheep
            "Field":    3,   # Wheat
            "Mountain": 4    # Ore
        }

        vertex_to_rolls: dict[int, list[list[int]]] = {}
        for inter in self.intersections:
            if inter is None or not hasattr(inter, 'id'):
                continue
            vid = inter.id
            rolls = [[] for _ in range(5)]   # exactly 5 resources

            # Support both storage styles used in your Board
            if hasattr(inter, 'three_tile_ids') and inter.three_tile_ids is not None:
                tile_ids = inter.three_tile_ids
            elif hasattr(inter, 'legs') and inter.legs:
                tile_ids = [getattr(leg, 'tile_id', None) for leg in inter.legs 
                        if getattr(leg, 'tile_id', None) is not None]
            else:
                tile_ids = []

            for tile_id in tile_ids:
                if not (0 <= tile_id < len(self.tiles)):
                    continue
                tile = self.tiles[tile_id]
                if tile is None:
                    continue
                ttype = getattr(tile, 'type', None)
                value = getattr(tile, 'value', 0)
                if ttype in terrain_to_idx and value > 0:
                    idx = terrain_to_idx[ttype]
                    rolls[idx].append(value)

            vertex_to_rolls[vid] = [sorted(set(r)) for r in rolls]

        print(f"✅ get_vertex_to_rolls generated for {len(vertex_to_rolls)} intersections")
        return vertex_to_rolls
