"""
Lean Markov evaluator for Catan initial placement.

This version is intentionally focused on the initial-placement phase.
It keeps the useful v11 architecture:
- full-position scoring from all owned / candidate vertices
- duplicate-preserving position keys
- clear conversion between game hand order and Markov internal order
- lazy caches for combined positions

It deliberately avoids the heavy trading layer:
- no bank / port trade simulation in the Markov matrix
- no opponent-trade anticipation
- no trade-plan explanation machinery

Most important fix compared with the previous lean version:
- unreachable targets no longer score as 0.00
- exact target scoring uses expected hitting time, not a target-vector projection
- round -2 single-vertex opening choices use a setup-appropriate production score
- round -1 combined positions can automatically include simulated starting resources

Resource orders
---------------
Markov internal order used by this file and Board.get_vertex_to_rolls():
    0 = brick   / Hill
    1 = lumber  / Forest
    2 = sheep    / Pasture
    3 = wheat   / Field
    4 = ore     / Mountain

Game hand order used elsewhere in your game:
    [Wheat, Ore, Wood, Brick, Sheep]

Public API kept for compatibility
---------------------------------
- precompute_game(vertex_to_rolls)
- get_expected_turns(vertices, hand=None, player_ports=None, strategy="best", ...)
- get_expected_turns_fast_initial(...)
- get_expected_time_to_event_fast(...)
- build_matrix(...) and expected_vectors(...) remain available for older callers,
  but initial-placement scoring does not depend on the matrix solve anymore.
"""

from __future__ import annotations

from collections import defaultdict
import math
import time
from typing import Dict, List, Sequence, Tuple

import torch


class MarkovEvaluator:
    """Markov evaluator focused on initial placement."""

    N_STATES = 5 ** 5  # resources are capped at 0..4
    UNREACHABLE_SCORE = 9999.0

    # Internal Markov resource order
    RES_NAMES = ["brick", "lumber", "sheep", "wheat", "ore"]

    # Dice-roll weights out of 36
    DIE_WEIGHT = {
        2: 1,
        3: 2,
        4: 3,
        5: 4,
        6: 5,
        7: 6,
        8: 5,
        9: 4,
        10: 3,
        11: 2,
        12: 1,
    }

    # Compatibility with older port dictionaries. Ports are not used for
    # trading anticipation, but keeping this attribute avoids external breakage.
    port_to_mode = {
        "": 0,
        "4:1": 0,
        "3:1": 1,
        "2:1 Wheat": 2,
        "2:1 Ore": 3,
        "2:1 Wood": 4,
        "2:1 Brick": 5,
        "2:1 Sheep": 6,
    }

    def __init__(self, device=None, verbose: bool = True) -> None:
        self.device = device or "cpu"
        self.verbose = verbose

        if self.verbose:
            print(f"✅ MarkovEvaluator using {str(self.device).upper()}")

        self.resource_poss: List[List[int]] = self._generate_states()
        self.state_to_index: Dict[Tuple[int, int, int, int, int], int] = {
            tuple(state): idx for idx, state in enumerate(self.resource_poss)
        }

        # Process high-resource states before low-resource states.
        # The Markov production process is monotone, so this enables exact
        # dynamic programming for expected hitting times.
        self.reverse_state_indices = sorted(
            range(self.N_STATES),
            key=lambda i: (sum(self.resource_poss[i]), *self.resource_poss[i]),
            reverse=True,
        )

        # Matrix-related compatibility caches. The initial-placement scorer uses
        # the faster dynamic-programming path instead.
        self.M_template = torch.zeros(
            (self.N_STATES, self.N_STATES),
            dtype=torch.float32,
            device="cpu",
        )
        self.precomp_cache: Dict[int, torch.Tensor] = {}
        self.position_matrix_cache: Dict[Tuple[int, ...], torch.Tensor] = {}

        # Roll and scoring caches
        self.vertex_rolls: Dict[int, List[List[int]]] = {}
        self.position_rolls_cache: Dict[Tuple[int, ...], List[List[int]]] = {}
        self.hitting_time_cache: Dict[Tuple[Tuple[int, ...], str], torch.Tensor] = {}
        self.target_vector_cache: Dict[str, torch.Tensor] = {}

        # Set externally by Game after construction: self.markov.board = self.board
        self.board = None

        # Optional compatibility hooks used by some fast-forward code.
        self.game = None
        self.ignore_resource_cards = False

    # ============================================================
    # Core helpers
    # ============================================================
    def _generate_states(self) -> List[List[int]]:
        states = []
        for brick in range(5):
            for lumber in range(5):
                for sheep in range(5):
                    for wheat in range(5):
                        for ore in range(5):
                            states.append([brick, lumber, sheep, wheat, ore])
        return states

    def _empty_rolls(self) -> List[List[int]]:
        return [[], [], [], [], []]

    def _normalize_rolls(self, rolls) -> List[List[int]]:
        """Ensure exactly five resource roll lists, preserving duplicates."""
        out = self._empty_rolls()
        if not isinstance(rolls, (list, tuple)):
            return out

        for i in range(min(5, len(rolls))):
            rlist = rolls[i]
            if not isinstance(rlist, (list, tuple)):
                continue
            normalized = []
            for value in rlist:
                try:
                    roll = int(value)
                except Exception:
                    continue
                if 2 <= roll <= 12 and roll != 7:
                    normalized.append(roll)
            out[i] = normalized
        return out

    def _position_key(self, vertices: Sequence[int] | None) -> Tuple[int, ...]:
        """
        Order-insensitive but duplicate-preserving key.

        Example:
            [12, 8, 12] -> (8, 12, 12)
        """
        if not vertices:
            return ()
        return tuple(sorted(int(v) for v in vertices))

    def _vec_to_state(self, vec: Sequence[int]) -> int:
        """Convert [brick, lumber, sheep, wheat, ore] to the linear state index."""
        brick, lumber, sheep, wheat, ore = [min(max(0, int(x)), 4) for x in vec]
        return brick * 625 + lumber * 125 + sheep * 25 + wheat * 5 + ore

    def _state_to_vec(self, state_idx: int) -> List[int]:
        """Convert linear state index to [brick, lumber, sheep, wheat, ore]."""
        state_idx = int(state_idx)
        vec = [0] * 5
        for i in range(4, -1, -1):
            vec[i] = state_idx % 5
            state_idx //= 5
        return vec

    def _game_hand_to_markov_vec(self, hand: Sequence[int] | None) -> List[int]:
        """
        Convert game hand order:
            [Wheat, Ore, Wood, Brick, Sheep]
        to Markov internal order:
            [Brick, Lumber/Wood, Sheep, Wheat, Ore]
        """
        if hand is None:
            hand = [0, 0, 0, 0, 0]

        h = [0, 0, 0, 0, 0]
        for i in range(min(5, len(hand))):
            try:
                h[i] = min(max(0, int(hand[i])), 4)
            except Exception:
                h[i] = 0

        wheat, ore, wood, brick, sheep = h
        return [brick, wood, sheep, wheat, ore]

    def _markov_vec_to_game_hand(self, vec: Sequence[int]) -> List[int]:
        """Convert internal [brick, lumber, sheep, wheat, ore] to game hand order."""
        brick, lumber, sheep, wheat, ore = [int(x) for x in vec]
        return [wheat, ore, lumber, brick, sheep]

    def _hand_to_state_index(self, hand: Sequence[int] | None) -> int:
        return self._vec_to_state(self._game_hand_to_markov_vec(hand))

    def _ignore_resource_cards(self) -> bool:
        game = getattr(self, "game", None)
        if game is not None and hasattr(game, "ff_ignore_resource_cards"):
            return bool(game.ff_ignore_resource_cards)
        return bool(getattr(self, "ignore_resource_cards", False))

    # ============================================================
    # Target definitions
    # ============================================================
    def _normalize_strategy(self, strategy: str, extra_roads_needed: int = 0) -> str:
        """Normalize external strategy names into internal target names."""
        s = str(strategy or "best").strip().lower()

        alias = {
            "new_settlement": "settlement",
            "upgrade_to_city": "city",
            "buy_discovery_card": "dev_card",
            "buy_4_discovery_cards": "dev_card_4",
            "development_card": "dev_card",
            "dcard": "dev_card",
        }
        s = alias.get(s, s)

        if s == "best":
            # Existing initial_placement_phase_manager.py may call get_expected_turns(...)
            # without specifying a strategy. For setup, the most useful default
            # is readiness for a settlement plus one connecting road.
            return "settlement_1r"

        if s == "settlement":
            if extra_roads_needed <= 0:
                return "settlement_0r"
            if extra_roads_needed == 1:
                return "settlement_1r"
            if extra_roads_needed == 2:
                return "settlement_2r"
            return "settlement_2r"

        if s in {
            "settlement_0r",
            "settlement_1r",
            "settlement_2r",
            "city",
            "dev_card",
            "dev_card_4",
        }:
            return s

        return "settlement_1r"

    def _get_target_requirements(self, target_type: str) -> List[int]:
        """Return requirements in internal order [brick, lumber, sheep, wheat, ore]."""
        target_type = self._normalize_strategy(target_type)

        if target_type == "settlement_0r":
            return [1, 1, 1, 1, 0]
        if target_type == "settlement_1r":
            return [2, 2, 1, 1, 0]
        if target_type == "settlement_2r":
            return [3, 3, 1, 1, 0]
        if target_type == "city":
            return [0, 0, 0, 2, 3]
        if target_type == "dev_card":
            return [0, 0, 1, 1, 1]
        if target_type == "dev_card_4":
            return [4, 4, 4, 4, 4]

        raise ValueError(f"Unknown target_type: {target_type}")

    def _state_satisfies(self, state: Sequence[int], req: Sequence[int]) -> bool:
        return all(int(state[i]) >= int(req[i]) for i in range(5))

    def _build_target_vector(self, target_type: str) -> torch.Tensor:
        """Compatibility helper: 1.0 where states satisfy the target."""
        target_type = self._normalize_strategy(target_type)
        if target_type in self.target_vector_cache:
            return self.target_vector_cache[target_type]

        req = self._get_target_requirements(target_type)
        vector = torch.zeros(self.N_STATES, dtype=torch.float32, device=self.device)
        for idx, state in enumerate(self.resource_poss):
            if self._state_satisfies(state, req):
                vector[idx] = 1.0

        self.target_vector_cache[target_type] = vector
        return vector

    # ============================================================
    # Precompute and roll aggregation
    # ============================================================
    def precompute_game(self, vertex_to_rolls: Dict[int, List[List[int]]]) -> None:
        """
        Cache single-vertex roll profiles.

        Unlike older versions, this does not eagerly build 54 dense 3125x3125
        matrices. Initial-placement scoring uses exact dynamic programming from
        the roll profiles, which is faster and avoids the 0.00-unreachable bug.
        """
        start_time = time.time()

        if self.verbose:
            print(
                f"🚀 Precomputing Markov roll profiles for {len(vertex_to_rolls)} vertices... "
                f"started at {time.strftime('%H:%M:%S')}"
            )

        self.vertex_rolls.clear()
        self.precomp_cache.clear()
        self.position_rolls_cache.clear()
        self.position_matrix_cache.clear()
        self.hitting_time_cache.clear()
        self.target_vector_cache.clear()

        for raw_vid, raw_rolls in vertex_to_rolls.items():
            vid = int(raw_vid)
            self.vertex_rolls[vid] = self._normalize_rolls(raw_rolls)

        if self.verbose:
            duration = time.time() - start_time
            print(
                f"✅ Precomputation finished at {time.strftime('%H:%M:%S')} — "
                f"Duration: {duration:.1f} seconds"
            )
            print(f"   {len(self.vertex_rolls)} vertices ready (roll profiles cached)")

    def _combine_vertex_rolls(self, vertices: Sequence[int]) -> List[List[int]]:
        """Combine production rolls from the full duplicate-preserving vertex multiset."""
        key = self._position_key(vertices)
        if key in self.position_rolls_cache:
            return self.position_rolls_cache[key]

        combined = self._empty_rolls()
        for vid in key:
            vrolls = self.vertex_rolls.get(int(vid), self._empty_rolls())
            for r in range(5):
                combined[r].extend(vrolls[r])

        self.position_rolls_cache[key] = combined
        return combined

    def _roll_gain_table(self, rolls: List[List[int]]) -> List[Tuple[int, List[int]]]:
        """
        Return [(dice_weight, gains), ...] for rolls 2..12.

        gains are in internal Markov order. Roll 7 is included as a zero-gain
        transition because it consumes a game turn but produces no resources.
        """
        roll_to_gains = {roll: [0, 0, 0, 0, 0] for roll in range(2, 13)}

        for res_idx, resource_rolls in enumerate(rolls):
            for roll in resource_rolls:
                if 2 <= int(roll) <= 12 and int(roll) != 7:
                    roll_to_gains[int(roll)][res_idx] += 1

        table = []
        for roll in range(2, 13):
            table.append((self.DIE_WEIGHT[roll], roll_to_gains[roll]))
        return table

    def _pips_from_rolls(self, rolls: List[List[int]]) -> List[float]:
        """Return pip strength by internal resource order."""
        pips = [0.0] * 5
        for res_idx, resource_rolls in enumerate(rolls):
            for roll in resource_rolls:
                pips[res_idx] += float(self.DIE_WEIGHT.get(int(roll), 0))
        return pips

    # ============================================================
    # Exact expected hitting time via monotone dynamic programming
    # ============================================================
    def _get_hitting_time_vector(self, vertices: Sequence[int], target_type: str) -> torch.Tensor:
        """
        Expected rolls/turns until the target is first reached for every state.

        Because resources only increase and are capped at 4, every non-self
        transition moves to a state that is greater-or-equal resource-wise.
        Processing states from high total resources to low total resources gives
        an exact Bellman solution:

            t(s) = 1 + Σ P(s->s') t(s')

        Rearranged for self-loops:

            t(s) = (1 + Σ_nonself P(s->s') t(s')) / (1 - P_self)

        If a state can never reach the target, it remains UNREACHABLE_SCORE.
        """
        key = self._position_key(vertices)
        target_type = self._normalize_strategy(target_type)
        cache_key = (key, target_type)

        if cache_key in self.hitting_time_cache:
            return self.hitting_time_cache[cache_key]

        req = self._get_target_requirements(target_type)
        rolls = self._combine_vertex_rolls(key)
        gain_table = self._roll_gain_table(rolls)

        times = [self.UNREACHABLE_SCORE] * self.N_STATES

        for idx in self.reverse_state_indices:
            state = self.resource_poss[idx]

            if self._state_satisfies(state, req):
                times[idx] = 0.0
                continue

            numerator = 36.0  # one turn passes
            self_weight = 0
            impossible_successor = False

            for weight, gains in gain_table:
                next_state = [
                    min(4, state[r] + int(gains[r]))
                    for r in range(5)
                ]
                next_idx = self.state_to_index[tuple(next_state)]

                if next_idx == idx:
                    self_weight += int(weight)
                    continue

                next_time = times[next_idx]
                if next_time >= self.UNREACHABLE_SCORE:
                    impossible_successor = True
                    break

                numerator += float(weight) * float(next_time)

            if impossible_successor:
                times[idx] = self.UNREACHABLE_SCORE
                continue

            denom = 36.0 - float(self_weight)
            if denom <= 1e-12:
                times[idx] = self.UNREACHABLE_SCORE
            else:
                value = numerator / denom
                if not math.isfinite(value) or value >= self.UNREACHABLE_SCORE:
                    value = self.UNREACHABLE_SCORE
                times[idx] = float(value)

        vector = torch.tensor(times, dtype=torch.float32, device=self.device)
        self.hitting_time_cache[cache_key] = vector
        return vector

    # ============================================================
    # Initial-placement scoring helpers
    # ============================================================
    def simulate_initial_resource_hand_from_vertex(self, intersection_id: int) -> List[int]:
        """
        Return the starting resources from a candidate second settlement.

        Game hand order returned:
            [Wheat, Ore, Wood, Brick, Sheep]

        This mirrors Catan setup: after the second settlement, receive one
        resource from each adjacent producing land tile.
        """
        hand = [0, 0, 0, 0, 0]
        if self.board is None:
            return hand

        try:
            iid = int(intersection_id)
        except Exception:
            return hand

        if iid < 0 or iid >= len(self.board.intersections):
            return hand

        inter = self.board.intersections[iid]
        if inter is None:
            return hand

        terrain_to_game_idx = {
            "Field": 0,     # Wheat
            "Mountain": 1,  # Ore
            "Forest": 2,    # Wood
            "Hill": 3,      # Brick
            "Pasture": 4,   # Sheep
        }

        for tile_id in getattr(inter, "three_tile_ids", []):
            if not (0 <= int(tile_id) < len(self.board.tiles)):
                continue
            tile = self.board.tiles[int(tile_id)]
            if tile is None:
                continue
            tile_type = getattr(tile, "type", None)
            tile_value = int(getattr(tile, "value", 0) or 0)
            if tile_type in terrain_to_game_idx and tile_value > 0:
                hand[terrain_to_game_idx[tile_type]] += 1

        return hand

    def _add_game_hands(self, a: Sequence[int] | None, b: Sequence[int] | None) -> List[int]:
        out = [0, 0, 0, 0, 0]
        for i in range(5):
            av = int(a[i]) if a is not None and i < len(a) else 0
            bv = int(b[i]) if b is not None and i < len(b) else 0
            out[i] = min(4, max(0, av + bv))
        return out

    def _maybe_add_initial_resources(
        self,
        vertices: Sequence[int],
        hand: Sequence[int] | None,
        auto_initial_resources: bool,
    ) -> Tuple[List[int], List[int]]:
        """
        Add candidate-second-settlement resources when requested.

        Returns:
            (effective_hand, added_hand)
        """
        base_hand = [0, 0, 0, 0, 0] if hand is None else [
            min(4, max(0, int(hand[i]))) if i < len(hand) else 0
            for i in range(5)
        ]

        if not auto_initial_resources or not vertices or len(vertices) < 2:
            return base_hand, [0, 0, 0, 0, 0]

        candidate_vertex = int(vertices[-1])
        added = self.simulate_initial_resource_hand_from_vertex(candidate_vertex)
        effective = self._add_game_hands(base_hand, added)
        return effective, added

    def _light_port_presence_bonus(self, vertices: Sequence[int], player_ports: dict | None) -> float:
        """
        Optional tiny port-access bonus, not a trading simulation.

        It is disabled by default. Kept for later experimentation.
        """
        if not player_ports or not vertices or self.board is None:
            return 0.0

        try:
            last_vid = int(vertices[-1])
        except Exception:
            return 0.0

        if last_vid < 0 or last_vid >= len(self.board.intersections):
            return 0.0

        inter = self.board.intersections[last_vid]
        if inter is None or not getattr(inter, "port_tf", False):
            return 0.0

        port_type = str(getattr(inter, "port_type", "")).strip()
        if port_type == "3:1":
            return 0.25
        if port_type.startswith("2:1"):
            return 0.40
        return 0.0

    def _opening_site_score(
        self,
        vertices: Sequence[int],
        player_ports: dict | None = None,
        use_light_port_bonus: bool = False,
    ) -> Tuple[float, dict]:
        """
        Setup-appropriate score for round -2 single-settlement candidates.

        A single vertex usually cannot produce the full settlement+road target
        without trading or the second settlement. Therefore exact target hitting
        time is too strict in round -2. This score ranks opening sites by:
        - production quality
        - early-resource coverage
        - brick/lumber usefulness
        - modest diversity
        - optional tiny port-access bonus

        Lower is better, matching the exact expected-turn score convention.
        """
        rolls = self._combine_vertex_rolls(vertices)
        pips = self._pips_from_rolls(rolls)

        # Internal order: brick, lumber, sheep, wheat, ore
        brick, lumber, sheep, wheat, ore = pips

        # Early game values brick/lumber a little more, but still values wheat,
        # sheep, and some ore for city/development-card potential.
        weighted_pips = (
            1.30 * brick
            + 1.30 * lumber
            + 1.00 * sheep
            + 1.05 * wheat
            + 0.70 * ore
        )

        early_presence = [brick > 0, lumber > 0, sheep > 0, wheat > 0]
        distinct_early = sum(1 for x in early_presence if x)
        distinct_all = sum(1 for x in pips if x > 0)

        missing_penalty = 0.0
        if brick <= 0:
            missing_penalty += 2.4
        if lumber <= 0:
            missing_penalty += 2.4
        if sheep <= 0:
            missing_penalty += 1.4
        if wheat <= 0:
            missing_penalty += 1.5
        if ore <= 0:
            missing_penalty += 0.4

        # Penalize extreme concentration a bit. A good opening settlement should
        # usually create options, not only one resource stream.
        max_pips = max(pips) if pips else 0.0
        total_pips = sum(pips)
        concentration_penalty = 0.0
        if total_pips > 0:
            concentration_penalty = max(0.0, (max_pips / total_pips) - 0.55) * 4.0

        diversity_bonus = 0.35 * distinct_early + 0.15 * max(0, distinct_all - distinct_early)
        port_bonus = self._light_port_presence_bonus(vertices, player_ports) if use_light_port_bonus else 0.0

        if weighted_pips <= 0:
            score = self.UNREACHABLE_SCORE
        else:
            score = (
                36.0 / weighted_pips
                + missing_penalty
                + concentration_penalty
                - diversity_bonus
                - port_bonus
            )
            score = max(0.25, float(score))

        details = {
            "pips_internal": pips,
            "weighted_pips": weighted_pips,
            "total_pips": total_pips,
            "distinct_early": distinct_early,
            "distinct_all": distinct_all,
            "missing_penalty": missing_penalty,
            "concentration_penalty": concentration_penalty,
            "diversity_bonus": diversity_bonus,
            "port_bonus": port_bonus,
        }
        return float(score), details

    def _unreachable_fallback_score(
        self,
        vertices: Sequence[int],
        effective_hand: Sequence[int],
        target_type: str,
    ) -> Tuple[float, dict]:
        """
        Graded fallback for exact no-trading targets that cannot be reached.

        This is intentionally worse than any normal reachable score, but it
        still ranks unreachable candidates sensibly when the top-N heuristic
        gives Markov no exact reachable option.

        The fallback rewards:
        - useful production toward the target resources
        - immediate setup hand contribution
        - broad target coverage

        It penalizes:
        - missing target resource categories
        - missing target card amounts

        Lower is better, but the score is floored high enough that reachable
        candidates should still beat unreachable candidates.
        """
        target_type = self._normalize_strategy(target_type)
        req = self._get_target_requirements(target_type)
        hand_internal = self._game_hand_to_markov_vec(effective_hand or [0, 0, 0, 0, 0])
        rolls = self._combine_vertex_rolls(vertices)
        pips = self._pips_from_rolls(rolls)

        target_resource_count = 0
        covered_target_resources = 0
        missing_resource_count = 0
        missing_card_amount = 0
        useful_pips = 0.0
        useful_hand_cards = 0

        for r in range(5):
            need = int(req[r])
            if need <= 0:
                continue

            target_resource_count += 1
            have = int(hand_internal[r])
            can_produce = float(pips[r]) > 0.0

            useful_hand_cards += min(have, need)

            if have >= need:
                covered_target_resources += 1
                # Already covered by starting resources; production is still
                # mildly useful, but less critical than for missing resources.
                useful_pips += 0.35 * float(pips[r])
            elif can_produce:
                covered_target_resources += 1
                useful_pips += float(pips[r])
            else:
                missing_resource_count += 1
                missing_card_amount += max(0, need - have)

        total_pips = float(sum(pips))
        coverage_ratio = (
            covered_target_resources / target_resource_count
            if target_resource_count > 0
            else 0.0
        )

        # Keep unreachable results clearly worse than reachable results, while
        # allowing meaningful ordering among unreachable candidates.
        raw_score = (
            2000.0
            + 220.0 * missing_resource_count
            + 45.0 * missing_card_amount
            - 11.0 * useful_pips
            - 18.0 * useful_hand_cards
            - 3.0 * total_pips
            - 85.0 * coverage_ratio
        )

        score = max(1500.0, min(self.UNREACHABLE_SCORE, float(raw_score)))

        details = {
            "missing_resource_count": missing_resource_count,
            "missing_card_amount": missing_card_amount,
            "useful_pips": useful_pips,
            "useful_hand_cards": useful_hand_cards,
            "total_pips": total_pips,
            "covered_target_resources": covered_target_resources,
            "target_resource_count": target_resource_count,
            "coverage_ratio": coverage_ratio,
            "pips_internal": pips,
            "hand_internal": hand_internal,
        }
        return score, details

    # ============================================================
    # Public scoring API
    # ============================================================
    def get_expected_turns_fast_initial(
        self,
        vertices: Sequence[int],
        hand: Sequence[int] | None = None,
        player_ports: dict | None = None,
        strategy: str = "settlement_1r",
        extra_roads_needed: int = 1,
        use_light_port_bonus: bool = False,
        print_details: bool = True,
        use_opening_site_score: bool | None = None,
        auto_initial_resources: bool = True,
        use_unreachable_fallback: bool = True,
    ) -> float:
        """
        Score an initial-placement candidate.

        Behavior:
        - one vertex + settlement-family target -> opening-site score by default
        - two or more vertices -> exact no-trading expected hitting time
        - unreachable exact targets get a graded fallback score, never 0.00
        - when scoring a likely second settlement, optionally add the resources
          that the candidate settlement would immediately grant

        Lower is better.
        """
        if not vertices:
            return self.UNREACHABLE_SCORE

        if self._ignore_resource_cards():
            base_hand = [0, 0, 0, 0, 0]
        else:
            base_hand = hand or [0, 0, 0, 0, 0]

        player_ports = player_ports or {}
        target = self._normalize_strategy(strategy, extra_roads_needed=extra_roads_needed)
        key = self._position_key(vertices)

        if use_opening_site_score is None:
            use_opening_site_score = (
                len(key) == 1
                and target in {"settlement_0r", "settlement_1r", "settlement_2r"}
            )

        if use_opening_site_score:
            score, details = self._opening_site_score(
                vertices=vertices,
                player_ports=player_ports,
                use_light_port_bonus=use_light_port_bonus,
            )
            if print_details:
                print(
                    f"   Markov INIT {key} | target=opening_site "
                    f"| quality={details['weighted_pips']:.2f} "
                    f"| total_pips={details['total_pips']:.1f} "
                    f"| coverage={details['distinct_early']}/4 "
                    f"| final={score:.2f}"
                )
            return float(score)

        effective_hand, added_initial_hand = self._maybe_add_initial_resources(
            vertices=vertices,
            hand=base_hand,
            auto_initial_resources=auto_initial_resources,
        )

        state_idx = self._hand_to_state_index(effective_hand)
        hitting_vector = self._get_hitting_time_vector(vertices, target)
        base_score = float(hitting_vector[state_idx])

        unreachable = base_score >= self.UNREACHABLE_SCORE or not math.isfinite(base_score)
        fallback_details = None
        fallback_score = self.UNREACHABLE_SCORE

        if unreachable:
            base_score = self.UNREACHABLE_SCORE
            fallback_score, fallback_details = self._unreachable_fallback_score(
                vertices=vertices,
                effective_hand=effective_hand,
                target_type=target,
            )
            final_score = fallback_score if use_unreachable_fallback else self.UNREACHABLE_SCORE
        else:
            bonus = self._light_port_presence_bonus(vertices, player_ports) if use_light_port_bonus else 0.0
            final_score = max(0.0, base_score - bonus)

        if print_details:
            added_txt = ""
            if auto_initial_resources and len(key) >= 2 and any(added_initial_hand):
                added_txt = f" | init_hand+={added_initial_hand}"

            if unreachable:
                if fallback_details is None:
                    fallback_details = {}
                print(
                    f"   Markov INIT {key} | target={target} "
                    f"| base=9999.00 | unreachable=True"
                    f" | missing={fallback_details.get('missing_resource_count', 0)}"
                    f" | useful_pips={fallback_details.get('useful_pips', 0.0):.1f}"
                    f" | fallback={fallback_score:.2f}"
                    f"{added_txt} | final={final_score:.2f}"
                )
            else:
                port_bonus = self._light_port_presence_bonus(vertices, player_ports) if use_light_port_bonus else 0.0
                print(
                    f"   Markov INIT {key} | target={target} "
                    f"| base={base_score:.2f} | port_bonus={port_bonus:.2f}"
                    f"{added_txt} | final={final_score:.2f}"
                )

        return float(final_score)

    def get_expected_turns(
        self,
        vertices: Sequence[int],
        hand: Sequence[int] | None = None,
        player_ports: dict | None = None,
        strategy: str = "best",
        extra_roads_needed: int = 1,
    ) -> float:
        """
        Backward-compatible wrapper used by current initial_placement_phase_manager.py.

        Deliberate behavior changes from the old evaluator:
        - scores the full vertex position, not vertices[:1]
        - does not anticipate trading
        - unreachable exact targets get a graded fallback instead of 0.0
        - single first-round candidates use opening-site scoring by default
        - likely second-round candidates include simulated starting resources
        """
        return self.get_expected_turns_fast_initial(
            vertices=vertices,
            hand=hand,
            player_ports=player_ports,
            strategy=strategy,
            extra_roads_needed=extra_roads_needed,
            use_light_port_bonus=False,
            print_details=True,
            use_opening_site_score=None,
            auto_initial_resources=True,
            use_unreachable_fallback=True,
        )

    def get_expected_time_to_event_fast(
        self,
        vertices: Sequence[int],
        hand: Sequence[int] | None = None,
        player_ports: dict | None = None,
        auto_initial_resources: bool = False,
    ) -> Dict[str, float]:
        """
        Diagnostic event timing without trading.

        This uses exact target timing, not the round -2 opening-site heuristic.
        """
        if not vertices:
            return {
                "settlement": self.UNREACHABLE_SCORE,
                "settlement_0r": self.UNREACHABLE_SCORE,
                "settlement_1r": self.UNREACHABLE_SCORE,
                "settlement_2r": self.UNREACHABLE_SCORE,
                "city": self.UNREACHABLE_SCORE,
                "dev_card": self.UNREACHABLE_SCORE,
                "dev_card_4": self.UNREACHABLE_SCORE,
            }

        base_hand = [0, 0, 0, 0, 0] if self._ignore_resource_cards() else (hand or [0, 0, 0, 0, 0])

        def score(target: str, roads: int = 0) -> float:
            return float(
                self.get_expected_turns_fast_initial(
                    vertices=vertices,
                    hand=base_hand,
                    player_ports=player_ports,
                    strategy=target,
                    extra_roads_needed=roads,
                    print_details=False,
                    use_opening_site_score=False,
                    auto_initial_resources=auto_initial_resources,
                    use_unreachable_fallback=False,
                )
            )

        settlement_0r = score("settlement_0r", 0)
        return {
            "settlement": settlement_0r,
            "settlement_0r": settlement_0r,
            "settlement_1r": score("settlement_1r", 1),
            "settlement_2r": score("settlement_2r", 2),
            "city": score("city", 0),
            "dev_card": score("dev_card", 0),
            "dev_card_4": score("dev_card_4", 0),
        }

    # ============================================================
    # Matrix compatibility methods
    # ============================================================
    def build_matrix(self, die_num) -> torch.Tensor:
        """
        Build a dense production transition matrix from resource roll lists.

        Kept for compatibility. The initial-placement scorer does not need this.
        """
        die_num = self._normalize_rolls(die_num)
        matrix = self.M_template.clone().to(self.device)

        roll_list = defaultdict(lambda: [0] * 5)
        for res_idx, rolls in enumerate(die_num):
            for roll in rolls:
                roll_list[int(roll)][res_idx] += 1

        grouped_rolls = [[] for _ in range(6)]
        for roll, gains in roll_list.items():
            count = sum(1 for g in gains if g > 0)
            grouped_rolls[count].append((roll, gains))

        for idx, current in enumerate(self.resource_poss):
            probability_weight_used = 0
            for n_res in range(1, 6):
                for roll, gains in grouped_rolls[n_res]:
                    next_state = current[:]
                    for r in range(5):
                        if gains[r]:
                            next_state[r] = min(4, next_state[r] + int(gains[r]))
                    next_idx = self.state_to_index[tuple(next_state)]
                    weight = self.DIE_WEIGHT.get(int(roll), 0)
                    matrix[idx, next_idx] += weight
                    probability_weight_used += weight

            matrix[idx, idx] += 36 - probability_weight_used

        return matrix / 36.0

    def _get_position_matrix(self, vertices: Sequence[int]) -> torch.Tensor:
        """Build or fetch a dense production matrix for older callers."""
        key = self._position_key(vertices)
        if key in self.position_matrix_cache:
            return self.position_matrix_cache[key]

        if len(key) == 1 and int(key[0]) in self.precomp_cache:
            matrix = self.precomp_cache[int(key[0])]
            self.position_matrix_cache[key] = matrix
            return matrix

        rolls = self._combine_vertex_rolls(key)
        matrix = self.build_matrix(rolls)
        self.position_matrix_cache[key] = matrix
        if len(key) == 1:
            self.precomp_cache[int(key[0])] = matrix
        return matrix

    def expected_vectors(self, matrix: torch.Tensor) -> Tuple[torch.Tensor, ...]:
        """
        Compatibility method returning correct expected hitting-time vectors.

        If the matrix contains unreachable states for a target, singular solves may
        still be conservative-capped at UNREACHABLE_SCORE.
        """
        matrix = matrix.to(self.device).float()
        row_sums = matrix.sum(dim=1, keepdim=True)
        matrix = torch.where(row_sums > 1e-12, matrix / row_sums, matrix)

        outputs = []
        for target_name in (
            "settlement_0r",
            "settlement_1r",
            "settlement_2r",
            "city",
            "dev_card",
            "dev_card_4",
        ):
            target_vec = self._build_target_vector(target_name)
            target_mask = target_vec > 0.5
            non_mask = ~target_mask
            non_idx = torch.nonzero(non_mask, as_tuple=False).flatten()

            full = torch.zeros(self.N_STATES, dtype=torch.float32, device=self.device)
            if len(non_idx) == 0:
                outputs.append(full)
                continue

            q = matrix[non_idx][:, non_idx]
            i_mat = torch.eye(q.shape[0], dtype=torch.float32, device=self.device)
            ones = torch.ones(q.shape[0], dtype=torch.float32, device=self.device)

            try:
                values = torch.linalg.solve(i_mat - q, ones)
            except Exception:
                try:
                    values = torch.linalg.pinv(i_mat - q) @ ones
                except Exception:
                    values = torch.full_like(ones, self.UNREACHABLE_SCORE)

            values = torch.nan_to_num(
                values,
                nan=self.UNREACHABLE_SCORE,
                posinf=self.UNREACHABLE_SCORE,
                neginf=self.UNREACHABLE_SCORE,
            )
            values = torch.clamp(values, min=0.0, max=self.UNREACHABLE_SCORE)
            full[non_idx] = values
            outputs.append(full[:-1])

        return tuple(outputs)
