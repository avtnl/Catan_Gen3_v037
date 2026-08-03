"""
core/algorithms_initial_placement.py
Algorithms:
1 = _max_of_pips; acutally using _max_of_pips_and_optonal_port with use_port=False
2 = _max_of_pips_and_port; actually using _max_of_pips_and_optonal_port with use_port=True
3 = 5 Strategies (balanced, wood/brick, wheat/ore, wheat/ore/sheep, monopoly)
4 = Markov AI (strong probabilistic AI based on precomputed transition matrices)
5 = Expected-hand feasibility (EH): deterministic, Markov-free turns-to-afford scoring.
"""

from typing import List, Tuple, Dict, Optional, Any, Sequence
from collections import defaultdict
from itertools import groupby
from math import ceil

from core.board import Board
from core.player import Player
from core.constants import MG, FILENAME_MG, BLOCKED_WEIGHT, TOP_N
from core.resource_time_estimator import estimate_initial_placement_candidate_time


class InitialPlacementStrategies:

    @staticmethod
    def _safe_int(val: Any) -> int:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(val: Any) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _intersection_resource_pips(inter: Any) -> List[float]:
        """Return resource pips in strategy order: [wheat, ore, wood, brick, sheep]."""
        return [
            InitialPlacementStrategies._safe_float(v)
            for v in getattr(inter, "all_tile_pips", [0.0] * 5)
        ]

    @staticmethod
    def check_port(port_type: str, frame: List[int], three_types: List[int], three_probs: List[float]) -> float:
        if not three_probs or len(three_probs) != 5:
            return 0.0

        total_pips = sum(InitialPlacementStrategies._safe_float(p) for p in three_probs)

        if port_type == "3:1":
            return total_pips / 6.0

        resource_index = -1
        if port_type == "2:1 Wheat":
            resource_index = 0
        elif port_type == "2:1 Ore":
            resource_index = 1
        elif port_type == "2:1 Wood":
            resource_index = 2
        elif port_type == "2:1 Brick":
            resource_index = 3
        elif port_type in ("2:1 Sheep", "2:1 Wool"):
            resource_index = 4

        if resource_index != -1 and frame[resource_index] == 1:
            matching_pips = InitialPlacementStrategies._safe_float(three_probs[resource_index])
            return matching_pips / 2.0

        return 0.0

    @staticmethod
    def select_intersection(
        board: Board,
        player: Player,
        algorithm_id: int = 2,
        valid_intersections: List[int] = None,
        game_round: int = -2,
    ) -> int:
        if valid_intersections is None:
            valid_intersections = [
                i for i in range(len(board.intersections))
                if getattr(board.intersections[i], "canbuildYNX", "N") != "X"
            ]

        if algorithm_id == 1:
            # Pips/trading score, but every spot is evaluated as if it has no port.
            return InitialPlacementStrategies._max_of_pips_and_optional_port(
                board,
                valid_intersections,
                use_port=False,
                algorithm_label="1",
            )

        if algorithm_id == 2:
            # Same behavior as the old _max_of_pips_and_port(): ports are relevant.
            return InitialPlacementStrategies._max_of_pips_and_optional_port(
                board,
                valid_intersections,
                use_port=True,
                algorithm_label="2",
            )

        if algorithm_id == 3:
            return InitialPlacementStrategies._five_strategy_engine(
                board, player, valid_intersections, game_round=game_round
            )

        if algorithm_id == 4:
            # Markov is handled in initial_placement.py
            raise ValueError("algorithm_id 4 (Markov) must be called via game.markov")

        if algorithm_id == 5:
            # Expected-hand feasibility (EH): deterministic, Markov-free turns-to-afford scoring.
            return InitialPlacementStrategies._expected_hand_feasibility_engine(
                board, player, valid_intersections, game_round=game_round
            )

        raise ValueError(f"algorithm_id {algorithm_id} not supported")

    @staticmethod
    def _pips_from_roll_value(value: Any) -> float:
        """Convert a Catan dice value to pips/probability weight."""
        roll = InitialPlacementStrategies._safe_int(value)
        return {
            2: 1.0, 3: 2.0, 4: 3.0, 5: 4.0, 6: 5.0,
            8: 5.0, 9: 4.0, 10: 3.0, 11: 2.0, 12: 1.0,
        }.get(roll, 0.0)

    @staticmethod
    def _tile_pips(inter: Any, tile: Any, tile_index: int) -> float:
        """Return the pips for one adjacent tile without relying on a global helper."""
        pips = getattr(inter, "three_tile_pips", None)
        if pips is not None and tile_index < len(pips):
            return InitialPlacementStrategies._safe_float(pips[tile_index])

        for attr in ("pips", "prob", "probability"):
            if hasattr(tile, attr):
                return InitialPlacementStrategies._safe_float(getattr(tile, attr))

        return InitialPlacementStrategies._pips_from_roll_value(getattr(tile, "value", 0))

    @staticmethod
    def _resource_pips_for_intersection(board: "Board", inter: Any) -> Dict[str, float]:
        """Group an intersection's adjacent tile pips by resource."""
        terrain_to_res = {
            "Hill": "brick",
            "Hills": "brick",
            "Forest": "wood",
            "Pasture": "sheep",
            "Field": "wheat",
            "Fields": "wheat",
            "Mountain": "ore",
            "Mountains": "ore",
        }

        resource_pips: Dict[str, float] = {
            "brick": 0.0,
            "wood": 0.0,
            "sheep": 0.0,
            "wheat": 0.0,
            "ore": 0.0,
        }

        for idx, tile_id in enumerate(getattr(inter, "three_tile_ids", [])):
            if tile_id < 0 or tile_id >= len(board.tiles):
                continue

            tile = board.tiles[tile_id]
            tile_type = getattr(tile, "type", None)
            res = terrain_to_res.get(tile_type)
            if not res:
                continue

            resource_pips[res] += InitialPlacementStrategies._tile_pips(inter, tile, idx)

        return resource_pips

    @staticmethod
    def _port_ratio_dict(inter: Any, use_port: bool) -> Tuple[Dict[str, int], str]:
        """
        Return per-resource trade ratios.

        use_port=False means ports have no relevance whatsoever: every intersection
        keeps the same baseline 4:1 bank ratio regardless of port_tf / port_type.
        use_port=True keeps the current behavior: 3:1 applies to all resources;
        2:1 applies only to the matching resource.
        """
        ratio_dict = {"brick": 4, "wood": 4, "sheep": 4, "wheat": 4, "ore": 4}
        port_str = ""

        if not use_port:
            return ratio_dict, port_str

        if not getattr(inter, "port_tf", False):
            return ratio_dict, port_str

        port_type = getattr(inter, "port_type", "")
        if not port_type or port_type == "Blank":
            return ratio_dict, port_str

        if port_type == "3:1":
            return {res: 3 for res in ratio_dict}, "3:1"

        if port_type.startswith("2:1"):
            specific_res = port_type.split()[-1].lower()
            if specific_res == "wool":
                specific_res = "sheep"
            if specific_res in ratio_dict:
                ratio_dict[specific_res] = 2
                port_str = port_type

        return ratio_dict, port_str

    @staticmethod
    def _rank_by_pips_and_optional_port(
        board: "Board",
        valid_intersections: List[int],
        use_port: bool = True,
    ) -> List[Tuple[int, float, List[str], str]]:
        """
        Build the ranking used by algorithms 1 and 2.

        Score = Σ(pips_r + floor(pips_r / ratio_r)) over all resources.
        - use_port=False: all ratios stay 4, so ports cannot influence the score.
        - use_port=True: 3:1 and 2:1 ports adjust ratios exactly as before.
        """
        scores: List[Tuple[int, float, List[str], str]] = []

        for inter_id in valid_intersections:
            if inter_id < 0 or inter_id >= len(board.intersections):
                continue

            inter = board.intersections[inter_id]
            if inter is None:
                continue

            resource_pips = InitialPlacementStrategies._resource_pips_for_intersection(board, inter)
            ratio_dict, port_str = InitialPlacementStrategies._port_ratio_dict(inter, use_port=use_port)

            total_score = 0.0
            breakdown: List[str] = []
            for res, pips in resource_pips.items():
                if pips > 0:
                    bonus = pips // ratio_dict[res]
                    total_score += pips + bonus
                    breakdown.append(f"{res[:4]}:{pips:.0f}+{bonus:.0f}")

            scores.append((inter_id, total_score, breakdown, port_str))

        scores.sort(key=lambda item: (-item[1], item[0]))
        return scores

    @staticmethod
    def _max_of_pips_and_optional_port(
        board: "Board",
        valid_intersections: List[int],
        use_port: bool = True,
        algorithm_label: str = "?",
    ) -> int:
        """
        Return the best intersection by pips plus optional port-adjusted trading value.

        Call with use_port=False for algorithm 1 and use_port=True for algorithm 2.
        Score = Σ(pips_r + floor(pips_r / ratio_r)) over all resources.
        """
        if not valid_intersections:
            land_ids = [i.id for i in board.intersections if i is not None]
            return min(land_ids) if land_ids else -1

        scores = InitialPlacementStrategies._rank_by_pips_and_optional_port(
            board,
            valid_intersections,
            use_port=use_port,
        )

        if not scores:
            return valid_intersections[0] if valid_intersections else -1

        if MG:
            mode = "WITH ports" if use_port else "WITHOUT ports"
            with open(FILENAME_MG, "a", encoding="utf-8") as f:
                f.write(f"\n=== _max_of_pips_and_optional_port FULL RANKING ({mode}) ===\n")
                for rank, (iid, score, breakdown, port_str) in enumerate(scores[:12], 1):
                    port_info = f" + {port_str}" if port_str and use_port else ""
                    f.write(
                        f"   #{rank:2d} inter {iid:2d} | score={score:4.1f}"
                        f"{port_info} | {' '.join(breakdown)}\n"
                    )

        return scores[0][0]

    @staticmethod
    def get_top_k_by_pips_and_port(
        board: "Board",
        valid_intersections: List[int],
        k: int = 40,
    ) -> List[int]:
        """Return the top K intersections ranked by the port-aware pips/trading score."""
        scores = InitialPlacementStrategies._rank_by_pips_and_optional_port(
            board,
            valid_intersections,
            use_port=True,
        )
        return [iid for iid, _, _, _ in scores[:k]]

    @staticmethod
    def combined_port_bonus_round_minus1(
        board: Board,
        existing_settlements: List[int],   # usually just [first settlement id]
        candidate_id: int,
        candidate_port_type: str
    ) -> float:
        """
        Calculate combined port value for round -1 when adding second settlement.
        - 3:1 → total pips / 6 (once only)
        - 2:1 X → (X pips s1+s2)/2 + bonuses from existing ports (non-overlapping)
        """
        if not candidate_port_type or candidate_port_type == "Blank":
            return 0.0

        # Total pips from both settlements (existing + candidate)
        total_pips = [0.0] * 5  # [wheat, ore, wood, brick, sheep]
        for sid in existing_settlements + [candidate_id]:
            inter = board.intersections[sid]
            if inter:
                probs = InitialPlacementStrategies._intersection_resource_pips(inter)
                types = getattr(inter, "all_tile_types", [0] * 5)
                for idx in range(5):
                    if idx < len(types) and types[idx] > 0:
                        total_pips[idx] += probs[idx]

        total_prod = sum(total_pips)

        # ─── Existing ports ─────────────────────────────────────────────────────
        existing_ports = []
        for sid in existing_settlements:
            inter = board.intersections[sid]
            if inter and getattr(inter, "port_tf", False):
                t = getattr(inter, "port_type", "")
                if t and t != "Blank":
                    existing_ports.append(t)

        # ─── Candidate is 3:1 ──────────────────────────────────────────────────
        if "3:1" in candidate_port_type:
            return total_prod / 6.0

        # ─── Candidate is 2:1 specific ─────────────────────────────────────────
        res_map = {
            "2:1 Wheat": 0,
            "2:1 Ore":   1,
            "2:1 Wood":  2,
            "2:1 Brick": 3,
            "2:1 Sheep": 4,   # or Wool
        }

        if candidate_port_type not in res_map:
            return 0.0

        spec_idx = res_map[candidate_port_type]
        spec_pips = total_pips[spec_idx]
        bonus_new = spec_pips / 2.0

        # Add value from existing ports
        bonus_existing = 0.0
        for ep in existing_ports:
            if "3:1" in ep:
                # exclude the new 2:1 resource from 3:1 discount
                adjusted_total = total_prod - spec_pips
                bonus_existing += adjusted_total / 6.0

            elif ep in res_map:
                ep_idx = res_map[ep]
                if ep_idx != spec_idx:  # different resource → full add
                    ep_pips = total_pips[ep_idx]
                    bonus_existing += ep_pips / 2.0
                # same resource → skip (no extra stacking)

        return bonus_new + bonus_existing

    @staticmethod
    def _five_strategy_engine(
        board: Board,
        player: Player,
        valid_intersections: List[int],
        game_round: int = -2
    ) -> int:
        if not valid_intersections:
            return -1

        # ────────────────────────────────────────────────
        # Prepare raw TW probabilities (still needed for tiebreaker / fallback)
        # ────────────────────────────────────────────────
        list_of_TW_prob = []
        for inter_id, inter in enumerate(board.intersections):
            if inter is None or inter_id in board.INTERSECTION_IN_WATER:
                continue

            probs = InitialPlacementStrategies._intersection_resource_pips(inter)
            tw_prob = sum(probs)
            list_of_TW_prob.append([inter_id, tw_prob])

        frames = [
            [1, 1, 1, 1, 1],      # 0: Balanced
            [0, 0, 1, 1, 0],      # 1: WB (Wood+Brick)
            [1, 1, 0, 0, 0],      # 2: WO (Wheat+Ore)
            [1, 1, 0, 0, 1],      # 3: WOS (Wheat+Ore+Sheep)
            [0, 0, 0, 0, 0],      # 4: Monopoly
        ]

        # ────────────────────────────────────────────────
        # Use precomputed raw data (or compute on first use)
        # ────────────────────────────────────────────────
        if not hasattr(board, 'precomputed_pp_raw'):
            if hasattr(board, 'precompute_algorithm2_raw'):
                board.precompute_algorithm2_raw()
            else:
                InitialPlacementStrategies.precompute_algorithm2_raw(board)

        player.PP_balanced = []
        player.PP_WB = []
        player.PP_WO = []
        player.PP_WOS = []
        player.PP_monopoly = []

        for inter_id in valid_intersections:
            if inter_id not in board.precomputed_pp_raw:
                continue

            raw = board.precomputed_pp_raw[inter_id]
            three_types = raw['three_types']
            three_probs = raw['three_probs']

            for fr in range(5):
                frame = frames[fr]
                diversity, sum_prob, tiles_having_RP, min_prob, port_prob = raw['frames'][fr]

                entry = [inter_id, 0.0, diversity, sum_prob, tiles_having_RP, min_prob, port_prob]

                if fr == 0:
                    player.PP_balanced.append(entry)
                elif fr == 1:
                    player.PP_WB.append(entry)
                elif fr == 2:
                    player.PP_WO.append(entry)
                elif fr == 3:
                    player.PP_WOS.append(entry)
                elif fr == 4:
                    player.PP_monopoly.append(entry)

        # ────────────────────────────────────────────────
        # Round -1: Replace standalone port with combined/context-aware value
        # ────────────────────────────────────────────────
        if game_round == -1:
            existing_settlements = player.settlements[:]
            if existing_settlements:
                for pp_list in [
                    player.PP_balanced,
                    player.PP_WB,
                    player.PP_WO,
                    player.PP_WOS,
                    player.PP_monopoly
                ]:
                    for entry in pp_list:
                        inter_id = entry[0]
                        inter = board.intersections[inter_id]
                        if not inter:
                            continue

                        port_type = ""
                        if getattr(inter, "port_tf", False):
                            port_type = getattr(inter, "port_type", "")

                        combined_bonus = InitialPlacementStrategies.combined_port_bonus_round_minus1(
                            board,
                            existing_settlements,
                            inter_id,
                            port_type
                        )

                        entry[3] += combined_bonus   # add to pure production sum_prob

        # ────────────────────────────────────────────────
        # Add blocked bonus (positive — blocking opponents) — applies in both rounds
        # ────────────────────────────────────────────────
        for pp_list in [
            player.PP_balanced,
            player.PP_WB,
            player.PP_WO,
            player.PP_WOS,
            player.PP_monopoly
        ]:
            for entry in pp_list:
                inter_id = entry[0]
                inter = board.intersections[inter_id]
                if not inter:
                    continue

                neighbors = getattr(inter, "three_intersection_ids", [])
                blocked_pips = 0.0
                for nid in neighbors:
                    raw = board.precomputed_pp_raw.get(nid)
                    if raw:
                        blocked_pips += raw['tw_prob']  # raw neighbor production

                blocked_bonus = blocked_pips * BLOCKED_WEIGHT  # positive!
                entry[3] += blocked_bonus

        # ────────────────────────────────────────────────
        # Apply strict diversity requirement only in round -1
        # ────────────────────────────────────────────────
        def apply_diversity_filter(pp_list, fr):
            if game_round != -1:
                return
            for entry in pp_list:
                diversity = entry[2]
                if (fr == 0 and diversity != 5) or \
                (fr == 1 and diversity != 2) or \
                (fr == 2 and diversity != 2) or \
                (fr == 3 and diversity != 3):
                    entry[1] = 0.0          # zero the strategy points

        apply_diversity_filter(player.PP_balanced, 0)
        apply_diversity_filter(player.PP_WB,       1)
        apply_diversity_filter(player.PP_WO,       2)
        apply_diversity_filter(player.PP_WOS,      3)
        # Monopoly (fr=4) intentionally not filtered

        # ────────────────────────────────────────────────
        # Sorting (priorities preserved)
        # ────────────────────────────────────────────────
        s1 = sorted(player.PP_balanced, key=lambda x: x[4], reverse=True)   # tiles_having_RP
        s2 = sorted(s1,         key=lambda x: x[2], reverse=True)           # diversity
        player.PP_balanced = sorted(s2, key=lambda x: x[3], reverse=True)   # sum_prob

        for pp_list in [player.PP_WB, player.PP_WO, player.PP_WOS]:
            s1 = sorted(pp_list, key=lambda x: x[2], reverse=True)          # diversity
            s2 = sorted(s1,      key=lambda x: x[5], reverse=True)          # min_prob
            pp_list[:] = sorted(s2, key=lambda x: x[3], reverse=True)       # sum_prob

        s1 = sorted(player.PP_monopoly, key=lambda x: x[2], reverse=True)   # diversity (max count)
        player.PP_monopoly = sorted(s1, key=lambda x: x[3], reverse=True)   # sum_prob

        # ────────────────────────────────────────────────
        # Assign shared points on ties
        # ────────────────────────────────────────────────
        def assign_shared_points(pp_list, sort_keys_indices):
            def tie_key(entry):
                return tuple(entry[i] for i in sort_keys_indices)

            current_rank = 1
            for key, group_iter in groupby(pp_list, key=tie_key):
                group = list(group_iter)
                num_tied = len(group)
                start_rank = current_rank
                end_rank = min(current_rank + num_tied - 1, TOP_N)
                if start_rank > TOP_N:
                    points = 0.0
                else:
                    total_pts = sum(float(TOP_N - r + 1) for r in range(start_rank, end_rank + 1))
                    points = total_pts / num_tied
                for entry in group:
                    entry[1] = points
                current_rank += num_tied

        assign_shared_points(player.PP_balanced, [4, 2, 3])   # tiles_having_RP, diversity, sum_prob
        assign_shared_points(player.PP_WB,       [2, 5, 3])   # diversity, min_prob, sum_prob
        assign_shared_points(player.PP_WO,       [2, 5, 3])
        assign_shared_points(player.PP_WOS,      [2, 5, 3])
        assign_shared_points(player.PP_monopoly, [2, 3])      # diversity, sum_prob

        # ────────────────────────────────────────────────
        # Rank-sum across strategies + pure TW pips tiebreaker
        # ────────────────────────────────────────────────
        list_of_TWs = []
        TW_in_WO = []

        for entry in player.PP_balanced:
            if entry[1] > 0:
                list_of_TWs.append([entry[0], entry[1], "Balanced"])

        for entry in player.PP_WB:
            if entry[1] > 0:
                list_of_TWs.append([entry[0], entry[1], "WB"])

        for entry in player.PP_WO:
            if entry[1] > 0:
                iid = entry[0]
                list_of_TWs.append([iid, entry[1], "WO"])
                TW_in_WO.append(iid)

        for entry in player.PP_WOS:
            if entry[1] > 0:
                iid = entry[0]
                if iid not in TW_in_WO:
                    list_of_TWs.append([iid, entry[1], "WOS"])

        for entry in player.PP_monopoly:
            if entry[1] > 0:
                list_of_TWs.append([entry[0], entry[1], "Monopoly"])

        # Add pure TW pips as fallback for any position not ranked high enough
        sort_TW_prob = sorted(list_of_TW_prob, key=lambda x: x[1], reverse=True)
        for i in range(min(TOP_N, len(sort_TW_prob))):
            list_of_TWs.append([sort_TW_prob[i][0], float(TOP_N - i), "TW_prob"])

        # Aggregate by intersection (sum strategy points)
        sort_list_of_TWs = sorted(list_of_TWs, key=lambda x: x[0])
        list_of_unique_TWs = []
        if sort_list_of_TWs:
            current_id = sort_list_of_TWs[0][0]
            current_val = 0.0
            for entry in sort_list_of_TWs:
                iid = entry[0]
                if iid == current_id:
                    current_val += entry[1]
                else:
                    tw_prob = next((p[1] for p in list_of_TW_prob if p[0] == current_id), 0.0)
                    list_of_unique_TWs.append([current_id, current_val, tw_prob])
                    current_id = iid
                    current_val = entry[1]
            tw_prob = next((p[1] for p in list_of_TW_prob if p[0] == current_id), 0.0)
            list_of_unique_TWs.append([current_id, current_val, tw_prob])

        sort_list_of_unique_TWs = sorted(list_of_unique_TWs, key=lambda x: x[1], reverse=True)

        if not sort_list_of_unique_TWs:
            return valid_intersections[0] if valid_intersections else -1

        best_inter = sort_list_of_unique_TWs[0][0]

        # ────────────────────────────────────────────────
        # Fill player.PP_strategies (per-strategy scores of the chosen spot)
        # ────────────────────────────────────────────────
        inter = board.intersections[best_inter]
        raw = board.precomputed_pp_raw.get(best_inter, {})
        three_probs = list(raw.get("three_probs", []))

        if len(three_probs) != 5 or not any(three_probs):
            three_probs = InitialPlacementStrategies._intersection_resource_pips(inter)
            raw["three_probs"] = three_probs
            raw["tw_prob"] = sum(three_probs)

        three_types = list(raw.get("three_types", getattr(inter, "all_tile_types", [0] * 5)))

        strategy_scores = [0.0] * 5
        for fr in range(5):
            frame = frames[fr]
            if fr == 4:
                strategy_scores[fr] = max(three_probs) if three_probs else 0.0
            else:
                s = 0.0
                for idx, t in enumerate(three_types):
                    if t > 0 and idx < len(frame) and frame[idx] == 1:
                        s += three_probs[idx]
                port_prob = 0.0
                if getattr(inter, "port_tf", False):
                    port_type = getattr(inter, "port_type", "")
                    if port_type and port_type != "Blank":
                        port_prob = InitialPlacementStrategies.check_port(
                            port_type, frame, three_types, three_probs
                        )
                s += port_prob
                strategy_scores[fr] = s
        player.PP_strategies = strategy_scores[:]

        # ────────────────────────────────────────────────
        # Debug logging (enhanced with blocked bonus info)
        # ────────────────────────────────────────────────
        if MG:
            with open(FILENAME_MG, "a", encoding="utf-8") as f:
                f.write(f"\n=== FIVE STRATEGY ENGINE FULL DEBUG - Player {player.id} "
                        f"(algorithm=2, round={game_round}) ===\n")
                f.write("Columns: id | strategy_points | diversity | sum_prob | tiles_having_RP | "
                        f"min_prob | port_bonus | blocked_bonus\n")
                f.write("-" * 130 + "\n")

                for name, lst in [
                    ("Balanced", player.PP_balanced),
                    ("WB", player.PP_WB),
                    ("WO", player.PP_WO),
                    ("WOS", player.PP_WOS),
                    ("Monopoly", player.PP_monopoly),
                ]:
                    f.write(f"{name} (FULL list):\n")
                    for e in lst:
                        inter_id = e[0]
                        inter = board.intersections[inter_id]
                        blocked_bonus = 0.0
                        if inter:
                            neighbors = getattr(inter, "three_intersection_ids", [])
                            blocked_pips = 0.0
                            for nid in neighbors:
                                raw = board.precomputed_pp_raw.get(nid)
                                if raw:
                                    blocked_pips += raw['tw_prob']
                            blocked_bonus = blocked_pips * BLOCKED_WEIGHT

                        f.write(f"{inter_id:3d} | {e[1]:13.1f} | {e[2]:2d} | {e[3]:6.1f} | "
                                f"{e[4]:2d} | {e[5]:6.1f} | {e[6]:6.1f} | {blocked_bonus:6.1f}\n")
                    f.write("-" * 130 + "\n")

                f.write("\nRank-sum selection (top 10):\n")
                f.write("id | total_strategy_points | tw_prob\n")
                for e in sort_list_of_unique_TWs[:10]:
                    f.write(f"{e[0]:3d} | {e[1]:20.1f} | {e[2]:6.1f}\n")

                # Final chosen intersection (with blocked_bonus)
                blocked_bonus_final = 0.0
                blocked_sum = 0.0
                if inter:
                    neighbors = getattr(inter, "three_intersection_ids", [])
                    blocked_pips = 0.0
                    for nid in neighbors:
                        raw = board.precomputed_pp_raw.get(nid)
                        if raw:
                            blocked_pips += raw['tw_prob']
                    blocked_bonus_final = blocked_pips * BLOCKED_WEIGHT
                    blocked_sum = blocked_pips

                f.write(f"\nChosen: {best_inter}\n")
                f.write(f"  Blocked TW sum neighbours: {blocked_sum:.1f} "
                        f"(bonus added: +{blocked_bonus_final:.2f})\n")
                f.write(f"  Final PP_strategies: {[round(x,1) for x in strategy_scores]}\n")
                f.write("=== END DEBUG ===\n\n")

        return best_inter


    # ===================================================================
    # ALGORITHM 5 — EXPECTED-HAND FEASIBILITY (EH)
    # ===================================================================
    @staticmethod
    def _estimate_expected_hand_turns_for_candidate(
        board: Board,
        player: Player,
        candidate_id: int,
        game_round: int,
        max_turns: float = 60.0,
        step: float = 0.25,
        confidence_target: float = 0.85,
        require_confidence: bool = False,
    ) -> Dict[str, Any]:
        """
        Evaluate one initial-placement candidate with the shared EH estimator.

        The generic Expected-Hand / turns-to-afford logic lives in
        core.resource_time_estimator. This wrapper keeps the initial-placement
        algorithm API stable while preventing EH helpers from being duplicated
        inside algorithms_initial_placement.py.
        """
        estimate = estimate_initial_placement_candidate_time(
            board=board,
            player=player,
            candidate_id=int(candidate_id),
            game_round=int(game_round),
            max_turns=max_turns,
            step=step,
            confidence_target=confidence_target,
            require_confidence=require_confidence,
        )

        # Backward-compatible keys used by the existing debug/ranking code.
        estimate["candidate_id"] = int(candidate_id)
        estimate["vertices"] = list(estimate.get("initial_placement_vertices", []))
        estimate["ports"] = tuple(estimate.get("explanation", {}).get("ports", ()))

        return estimate

    @staticmethod
    def _expected_hand_feasibility_engine(
        board: Board,
        player: Player,
        valid_intersections: List[int],
        game_round: int = -2,
    ) -> int:
        """
        Algorithm 5: choose the initial-placement settlement with best EH timing.

        EH itself is delegated to core.resource_time_estimator. The scoring here
        remains initial-placement-specific: candidates are sorted by estimated
        turns, confidence, production coverage, pips/port fallback, then id.
        """
        if not valid_intersections:
            return -1

        pips_rank = InitialPlacementStrategies._rank_by_pips_and_optional_port(
            board=board,
            valid_intersections=valid_intersections,
            use_port=True,
        )
        pips_rank_index = {iid: rank for rank, (iid, _, _, _) in enumerate(pips_rank)}
        pips_score = {iid: score for iid, score, _, _ in pips_rank}
        ordered_candidates = [iid for iid, _, _, _ in pips_rank] or list(valid_intersections)

        evaluations: List[Dict[str, Any]] = []

        for inter_id in ordered_candidates:
            if inter_id not in valid_intersections:
                continue

            ev = InitialPlacementStrategies._estimate_expected_hand_turns_for_candidate(
                board=board,
                player=player,
                candidate_id=inter_id,
                game_round=game_round,
                max_turns=60.0,
                step=0.25,
                confidence_target=0.85,
                require_confidence=False,
            )

            ev["pips_rank"] = pips_rank_index.get(inter_id, 9999)
            ev["pips_port_score"] = pips_score.get(inter_id, 0.0)
            ev["coverage"] = sum(1 for value in ev.get("production_pips", []) if value > 0.0)
            evaluations.append(ev)

        if not evaluations:
            return valid_intersections[0]

        def sort_key(ev: Dict[str, Any]) -> Tuple[Any, ...]:
            return (
                not bool(ev.get("found", False)),
                float(ev.get("turns", 9999.0)),
                -float(ev.get("confidence", 0.0)),
                -float(ev.get("coverage", 0.0)),
                -float(ev.get("pips_port_score", 0.0)),
                int(ev.get("pips_rank", 9999)),
                int(ev.get("candidate_id", 9999)),
            )

        evaluations.sort(key=sort_key)
        best = evaluations[0]
        best_inter = int(best["candidate_id"])

        player.EH_initial_placement_candidates = evaluations[:]
        player.EH_initial_placement_choice = best.copy()

        if MG:
            with open(FILENAME_MG, "a", encoding="utf-8") as f:
                f.write(
                    f"\n=== EXPECTED-HAND INITIAL PLACEMENT DEBUG - Player {player.id} "
                    f"(algorithm=5, round={game_round}) ===\n"
                )
                f.write(
                    "id | found | turns | conf | pips_score | coverage | hand | pips | rates\n"
                )
                for ev in evaluations[:20]:
                    f.write(
                        f"{int(ev['candidate_id']):3d} | "
                        f"{str(bool(ev.get('found', False))):5s} | "
                        f"{float(ev.get('turns', 9999.0)):6.2f} | "
                        f"{float(ev.get('confidence', 0.0)):5.2f} | "
                        f"{float(ev.get('pips_port_score', 0.0)):10.1f} | "
                        f"{int(ev.get('coverage', 0)):8d} | "
                        f"{tuple(round(x, 2) for x in ev.get('current_hand', (0,0,0,0,0)))} | "
                        f"{tuple(round(x, 2) for x in ev.get('production_pips', (0,0,0,0,0)))} | "
                        f"{ev.get('trade_rates', ())}\n"
                    )
                f.write(
                    f"Chosen: {best_inter} | turns={float(best.get('turns', 9999.0)):.2f} | "
                    f"confidence={float(best.get('confidence', 0.0)):.2f}\n"
                )
                f.write("=== END EXPECTED-HAND DEBUG ===\n\n")

        return best_inter

    @staticmethod
    def find_best_road_having_port(
        board: Board,
        settlement_id: int,
        top_tws: List[int],
        blocked_tws: List[int],
        selected_tws: List[int]
    ) -> Tuple[int, int] | None:
        conn = board.list_of_roads_connected_to_intersection
        legs = conn[settlement_id] if isinstance(conn, list) and 0 <= settlement_id < len(conn) else conn.get(settlement_id, []) if isinstance(conn, dict) else []
        if not legs:
            return None
        best_score = -1
        best_road = None
        for leg in legs:
            a, b = leg
            next_tw = a if b == settlement_id else b
            if next_tw == settlement_id:
                continue
            next_inter = board.intersections[next_tw] if 0 <= next_tw < len(board.intersections) else None
            prob = sum(InitialPlacementStrategies._intersection_resource_pips(next_inter)) if next_inter else 0.0
            if prob > best_score:
                best_score = prob
                best_road = (settlement_id, next_tw)
        return best_road

    @staticmethod
    def find_best_road_missing_port(
        board: Board,
        settlement_id: int,
        player: Player,
        top_tws: List[int],
        blocked_tws: List[int],
        selected_tws: List[int]
    ) -> Tuple[int, int] | None:
        conn = board.list_of_roads_connected_to_intersection
        legs = conn[settlement_id] if isinstance(conn, list) and 0 <= settlement_id < len(conn) else conn.get(settlement_id, []) if isinstance(conn, dict) else []
        if not legs:
            return None
        tree = []
        for leg in legs:
            a, b = leg
            current = a if b == settlement_id else b
            if current == settlement_id:
                continue
            next_legs = conn.get(current, []) if isinstance(conn, dict) else (conn[current] if 0 <= current < len(conn) else [])
            for next_leg in next_legs:
                n1, n2 = next_leg
                next_tw = n1 if n2 == current else n2
                if next_tw in (settlement_id, current):
                    continue
                tree.append([current, next_tw, settlement_id])
        if not tree:
            for leg in legs:
                a, b = leg
                candidate = a if b == settlement_id else b
                if candidate != settlement_id:
                    return (settlement_id, candidate)
            return None
        tw_probs = {}
        for i, inter in enumerate(board.intersections):
            if inter:
                tw_probs[i] = sum(InitialPlacementStrategies._intersection_resource_pips(inter))
        direction_scores = defaultdict(float)
        for entry in tree:
            _, future_tw, _ = entry
            if future_tw in selected_tws or future_tw in blocked_tws:
                continue
            score = tw_probs.get(future_tw, 0)
            if future_tw in top_tws:
                score *= 1.5
            direction_scores[entry[0]] += score
        if not direction_scores:
            for leg in legs:
                a, b = leg
                candidate = a if b == settlement_id else b
                if candidate != settlement_id:
                    return (settlement_id, candidate)
        best_first = max(direction_scores, key=direction_scores.get)
        return (settlement_id, best_first)
    
    @staticmethod
    def precompute_algorithm2_raw(board: Board) -> None:
        """Moved from Board class — computes once all static raw metrics for algorithm=2."""
        if hasattr(board, 'precomputed_pp_raw'):
            return

        board.precomputed_pp_raw = {}

        frames = [
            [1,1,1,1,1], [0,0,1,1,0], [1,1,0,0,0],
            [1,1,0,0,1], [0,0,0,0,0]
        ]

        for inter_id in range(len(board.intersections)):
            inter = board.intersections[inter_id]
            if inter is None or inter.id in board.INTERSECTION_IN_WATER:
                continue

            three_types = list(getattr(inter, "all_tile_types", [0] * 5))
            three_probs = InitialPlacementStrategies._intersection_resource_pips(inter)

            raw_frames = []
            tw_prob = sum(InitialPlacementStrategies._safe_float(p) for p in three_probs)

            for fr, frame in enumerate(frames):
                if fr == 4:  # monopoly
                    diversity = max(three_types) if three_types else 0
                    tiles_having_RP = diversity
                    sum_prob = max(three_probs) if three_probs else 0.0
                    min_prob = sum_prob
                else:
                    contributing = set()
                    tiles_having_RP = 0
                    sum_prob = 0.0
                    min_prob = 99.0
                    for idx, t in enumerate(three_types):
                        if t > 0 and idx < len(frame) and frame[idx] == 1:
                            contributing.add(idx)
                            tiles_having_RP += 1
                            p = InitialPlacementStrategies._safe_float(three_probs[idx])
                            sum_prob += p
                            if p < min_prob:
                                min_prob = p
                    diversity = len(contributing)
                    if min_prob == 99.0:
                        min_prob = 0.0

                port_prob = 0.0
                if getattr(inter, "port_tf", False):
                    port_type = getattr(inter, "port_type", "")
                    if port_type and port_type != "Blank":
                        port_prob = InitialPlacementStrategies.check_port(
                            port_type, frame, three_types, three_probs
                        )
                # Note: do NOT add port_prob to sum_prob here (pure pips only)

                raw_frames.append([diversity, sum_prob, tiles_having_RP, min_prob, port_prob])

            board.precomputed_pp_raw[inter_id] = {
                'tw_prob': tw_prob,
                'frames': raw_frames,
                'three_types': three_types[:],
                'three_probs': [InitialPlacementStrategies._safe_float(p) for p in three_probs]
            }

        if MG:
            with open(FILENAME_MG, "a") as f:
                f.write(f"precompute_algorithm2_raw | Stored raw data for "
                        f"{len(board.precomputed_pp_raw)} intersections\n")    
