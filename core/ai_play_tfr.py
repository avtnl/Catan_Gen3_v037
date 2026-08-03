"""AI Play Two Free Roads (TFR) — gates, MVP, free-road path, thin execute.

Runtime pipeline:
  1. Gate legality
  2. MVP play/hold (S-Crit, LR-Crit, hold early, alt-DCard stub)
  3. If play → attach free-road path from existing AI road planner
  4. Thin execute + Continue re-scan so settle can follow
  5. Log reason codes

API:

  plan_ai_play_tfr(game) -> {play, timing, reason, road_ids, ...}
  execute_ai_play_tfr(game, plan=...) -> {ok, roads_placed, slice_d, ...}

TFR is **post-roll only**. Execute consumes the card, places free roads from
``road_ids`` (shared free-road path with human TFR), then re-scans so a
settlement can appear on the next AI Continue.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ── Reason codes (gates) ────────────────────────────────────────────────────
REASON_SKELETON_HOLD = "skeleton_hold"  # legacy Stage 1
REASON_NOT_EXECUTION = "not_execution_phase"
REASON_NO_PLAYER = "no_current_player"
REASON_HUMAN_PLAYER = "current_player_is_human"
REASON_ROBBER_ACTIVE = "robber_flow_already_active"
REASON_DCARD_ALREADY = "already_played_dcard_this_turn"
REASON_NO_TFR = "no_playable_tfr"
REASON_WRONG_STATE = "tfr_not_legal_in_state"
REASON_DISCARD_PENDING = "discard_pending"
REASON_KNIGHT_PENDING = "knight_play_already_pending"
REASON_TFR_PENDING = "tfr_play_already_pending"
REASON_NO_ROAD_PIECES = "no_road_pieces_remaining"
REASON_TFR_PRE_ROLL = "tfr_requires_dice_already_rolled"

# ── Reason codes (MVP play / hold) ──────────────────────────────────────────
REASON_S_CRIT = "s_crit"
REASON_LR_CRIT = "lr_crit"
REASON_SETTLE_PATH = "settle_path"
REASON_EARLY_PATH = "early_path"
REASON_HOLD_EARLY = "hold_early"
REASON_HOLD_ALT_DCARD = "hold_alt_dcard"
REASON_HOLD_DEFAULT = "hold_default"
REASON_HOLD_WEAK = "hold_weak_path"

CARD_TYPE = "two_free_roads"
MAX_PLAYER_ROADS = 15
MAX_FREE_ROADS = 2

ROBBER_FLOW_STATES = frozenset(
    {
        "MoveRobber",
        "RobberMoveRequired",
        "SetRobber",
        "StealSelectOpponent",
        "StealPickRCard",
        "DiscardPending",
    }
)

STAGE = "execute_thin"

# Tunable MVP thresholds
EARLY_VP_MAX = 3
EARLY_ROADS_MAX = 2
LR_MIN_LENGTH = 5
ALT_DCARD_BLOCK_MIN = 6.0  # stub score that beats non-critical TFR
SETTLE_PATH_SCORE_MIN = 4.0


def _safe_player_id(player: Any) -> Optional[int]:
    try:
        return int(getattr(player, "id", 0) or 0)
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _dice_not_rolled(game: Any) -> bool:
    dice_roll = getattr(game, "dice_roll", None)
    state = str(getattr(game, "state", "") or "")
    if state == "AwaitingDiceRoll":
        return True
    if dice_roll in (None, 0, "", []):
        return True
    if isinstance(dice_roll, (list, tuple)):
        return len(dice_roll) == 0
    try:
        return int(dice_roll) <= 0
    except Exception:
        return False


def _dcard_already_played_this_turn(game: Any) -> bool:
    for attr in ("myturn", "turn_details"):
        try:
            td = getattr(game, attr, None)
            if td is not None and bool(getattr(td, "dcard_played_in_turn_TF", False)):
                return True
        except Exception:
            pass
    return False


def _is_human_player(game: Any, player: Any) -> bool:
    try:
        if bool(getattr(player, "is_human", False)):
            return True
    except Exception:
        pass
    try:
        checker = getattr(game, "_is_current_player_human_for_execution", None)
        if callable(checker) and player is getattr(game, "current_player", None):
            return bool(checker())
        if callable(checker) and player is game.get_current_player():
            return bool(checker())
    except Exception:
        pass
    return False


def playable_tfr_count(player: Any) -> int:
    """How many TFR cards the player may legally play (core-side, no GUI)."""
    if player is None:
        return 0
    found_row = False
    try:
        summary = list(getattr(player, "dcard_summary", []) or [])
        for row in summary:
            row_list = list(row or [])
            if not row_list:
                continue
            if str(row_list[0]) != CARD_TYPE:
                continue
            found_row = True
            while len(row_list) < 4:
                row_list.append(0)
            return max(0, int(row_list[2] or 0))
    except Exception:
        found_row = False
    if found_row:
        return 0
    try:
        return sum(
            1 for c in (getattr(player, "development_cards", []) or []) if str(c) == CARD_TYPE
        )
    except Exception:
        return 0


def roads_remaining(game: Any, player: Any) -> int:
    """Unused road pieces (0..15). Prefer Game.player_roads_remaining when present."""
    if player is None:
        return 0
    fn = getattr(game, "player_roads_remaining", None)
    if callable(fn):
        try:
            return max(0, int(fn(player)))
        except Exception:
            pass
    try:
        max_roads = int(getattr(game, "MAX_PLAYER_ROADS", MAX_PLAYER_ROADS) or MAX_PLAYER_ROADS)
    except Exception:
        max_roads = MAX_PLAYER_ROADS
    try:
        placed = len(list(getattr(player, "roads", []) or []))
    except Exception:
        placed = 0
    return max(0, max_roads - int(placed))


def free_roads_available(game: Any, player: Any) -> int:
    """How many free roads this TFR play could place: min(2, pieces left)."""
    return min(MAX_FREE_ROADS, roads_remaining(game, player))


def _resolve_window(game: Any, window: Optional[str]) -> str:
    if window in ("pre_roll", "post_roll"):
        return str(window)
    state = str(getattr(game, "state", "") or "")
    if state == "AwaitingDiceRoll" or _dice_not_rolled(game):
        return "pre_roll"
    if state == "ActionSelection":
        return "post_roll"
    return "unknown"


def evaluate_ai_tfr_gates(
    game: Any,
    player: Any,
    *,
    window: Optional[str] = None,
) -> Dict[str, Any]:
    """Return gate evaluation without mutating game state."""
    resolved = _resolve_window(game, window)
    gates: Dict[str, Any] = {
        "phase_ok": False,
        "player_ok": False,
        "ai_ok": False,
        "not_robber_flow": False,
        "not_discard_pending": False,
        "not_knight_pending": False,
        "not_tfr_pending": False,
        "dcard_slot_free": False,
        "has_playable_tfr": False,
        "has_road_pieces": False,
        "state_ok": False,
        "post_roll_only": True,
        "window": resolved,
    }
    reasons_failed: List[str] = []

    phase = str(getattr(game, "phase", "") or "")
    gates["phase_ok"] = phase == "Execution"
    if not gates["phase_ok"]:
        reasons_failed.append(REASON_NOT_EXECUTION)

    if player is None:
        reasons_failed.append(REASON_NO_PLAYER)
    else:
        gates["player_ok"] = True

    if player is not None:
        human = _is_human_player(game, player)
        gates["ai_ok"] = not human
        if human:
            reasons_failed.append(REASON_HUMAN_PLAYER)

    state = str(getattr(game, "state", "") or "")
    if state in ROBBER_FLOW_STATES:
        reasons_failed.append(REASON_ROBBER_ACTIVE)
    else:
        gates["not_robber_flow"] = True

    pending_7 = getattr(game, "pending_seven_roll", None) or {}
    pending_steal = getattr(game, "pending_robber_steal", None) or {}
    if isinstance(pending_7, dict) and pending_7.get("active"):
        gates["not_robber_flow"] = False
        if REASON_ROBBER_ACTIVE not in reasons_failed:
            reasons_failed.append(REASON_ROBBER_ACTIVE)
    if isinstance(pending_steal, dict) and pending_steal.get("active"):
        gates["not_robber_flow"] = False
        if REASON_ROBBER_ACTIVE not in reasons_failed:
            reasons_failed.append(REASON_ROBBER_ACTIVE)

    pending_discard = list(getattr(game, "pending_discard_queue", None) or [])
    if pending_discard:
        reasons_failed.append(REASON_DISCARD_PENDING)
    else:
        gates["not_discard_pending"] = True

    pending_knight = getattr(game, "pending_knight_play", None) or {}
    if isinstance(pending_knight, dict) and pending_knight.get("active"):
        reasons_failed.append(REASON_KNIGHT_PENDING)
    else:
        gates["not_knight_pending"] = True

    pending_tfr = getattr(game, "pending_tfr_play", None) or {}
    if isinstance(pending_tfr, dict) and pending_tfr.get("active"):
        reasons_failed.append(REASON_TFR_PENDING)
    else:
        gates["not_tfr_pending"] = True

    if _dcard_already_played_this_turn(game):
        reasons_failed.append(REASON_DCARD_ALREADY)
    else:
        gates["dcard_slot_free"] = True

    tfr_count = playable_tfr_count(player) if player is not None else 0
    gates["playable_tfr_count"] = int(tfr_count)
    if tfr_count > 0:
        gates["has_playable_tfr"] = True
    else:
        reasons_failed.append(REASON_NO_TFR)

    pieces = roads_remaining(game, player) if player is not None else 0
    free_n = min(MAX_FREE_ROADS, pieces)
    gates["roads_remaining"] = int(pieces)
    gates["free_roads_available"] = int(free_n)
    if pieces > 0:
        gates["has_road_pieces"] = True
    else:
        reasons_failed.append(REASON_NO_ROAD_PIECES)

    if resolved == "pre_roll":
        state_ok = False
        if REASON_TFR_PRE_ROLL not in reasons_failed:
            reasons_failed.append(REASON_TFR_PRE_ROLL)
    elif resolved == "post_roll":
        state_ok = state == "ActionSelection" and not _dice_not_rolled(game)
        if not state_ok:
            reasons_failed.append(REASON_WRONG_STATE)
    else:
        state_ok = False
        reasons_failed.append(REASON_WRONG_STATE)
    gates["state_ok"] = bool(state_ok)

    legal = (
        gates["phase_ok"]
        and gates["player_ok"]
        and gates["ai_ok"]
        and gates["not_robber_flow"]
        and gates["not_discard_pending"]
        and gates["not_knight_pending"]
        and gates["not_tfr_pending"]
        and gates["dcard_slot_free"]
        and gates["has_playable_tfr"]
        and gates["has_road_pieces"]
        and gates["state_ok"]
    )

    primary_reason = reasons_failed[0] if reasons_failed else REASON_HOLD_DEFAULT
    return {
        "legal": bool(legal),
        "gates": gates,
        "failed_reasons": reasons_failed,
        "primary_gate_reason": primary_reason if not legal else None,
        "window": resolved,
        "playable_tfr_count": int(tfr_count),
        "roads_remaining": int(pieces),
        "free_roads_available": int(free_n),
        "state": state,
        "phase": phase,
    }


# ────────────────────────────────────────────────────────────────────────────
# Stage 2: features + MVP play/hold
# ────────────────────────────────────────────────────────────────────────────


def _vp(player: Any) -> int:
    if player is None:
        return 0
    for attr in ("victory_points", "points"):
        try:
            return int(getattr(player, attr) or 0)
        except Exception:
            pass
    return 0


def _road_length(player: Any, game: Any = None) -> int:
    """Continuous road length — prefer PR2 engine when game is available."""
    if game is not None and player is not None:
        try:
            from core.longest_road import compute_longest_road_for_player

            res = compute_longest_road_for_player(game, player)
            return max(0, int(res.length))
        except Exception:
            pass
    for attr in ("size_longest_route", "size_longest_road", "longest_road_length"):
        try:
            return max(0, int(getattr(player, attr, 0) or 0))
        except Exception:
            pass
    try:
        return len(list(getattr(player, "roads", []) or []))
    except Exception:
        return 0


def _holds_lr(player: Any) -> bool:
    try:
        return bool(getattr(player, "longest_route_tf", False) or getattr(player, "longest_road_tf", False))
    except Exception:
        return False


def _candidate_free_roads_for_lr(game: Any, player: Any, free_n: int) -> List[List[int]]:
    """Best-effort free-road edges for plan-time LR evaluation (no mutate).

    S-LR-B: prefer sticky/runtime **LR project** edges (minimal claim prefix).
    """
    free_n = max(0, min(MAX_FREE_ROADS, int(free_n or 0)))
    if free_n <= 0:
        return []
    roads: List[List[int]] = []
    seen = set()

    def _add(raw: Any) -> None:
        if len(roads) >= free_n:
            return
        rid = _normalize_road_id(raw)
        if rid is None:
            return
        key = tuple(rid)
        if key in seen:
            return
        seen.add(key)
        roads.append(rid)

    # 0) S-LR-B: LR project free-road prefix (claim-minimal)
    try:
        from core.ai_lr_project import tfr_edges_from_lr_project

        for rid in tfr_edges_from_lr_project(game, player, free_n=free_n):
            _add(rid)
    except Exception:
        pass

    # 1) Explicit strategy roads
    if len(roads) < free_n:
        for rid in _roads_from_direction(player):
            _add(rid)

    # 2) Settlement-route / LR planner (same as attach path)
    if len(roads) < free_n:
        try:
            from core.ai_road_planner import build_ai_road_plan

            candidates = _legal_road_candidates(game, player)
            plan = build_ai_road_plan(game, player, candidates) or {}
            for raw in list(plan.get("roads_to_build") or []):
                _add(raw)
            if plan.get("next_road") is not None:
                _add(plan.get("next_road"))
        except Exception:
            pass
    return roads


def evaluate_tfr_lr_claim(
    game: Any,
    player: Any,
    *,
    free_n: Optional[int] = None,
    extra_road_ids: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """PR4: real continuous-length LR claim check for TFR planning."""
    from core.longest_road import evaluate_lr_claim_after_edges

    n = free_n if free_n is not None else free_roads_available(game, player)
    extras = list(extra_road_ids) if extra_road_ids is not None else _candidate_free_roads_for_lr(
        game, player, int(n or 0)
    )
    return evaluate_lr_claim_after_edges(
        game, player, extras, min_length=LR_MIN_LENGTH
    )


def _preferred_wants_lr(player: Any) -> bool:
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return False
    if bool(direction.get("longest_road") or direction.get("longest_route")):
        return True
    tags = direction.get("tags") or direction.get("way_tags") or []
    try:
        tag_text = " ".join(str(t).lower() for t in tags)
    except Exception:
        tag_text = str(tags).lower()
    if "longest road" in tag_text or "longest_road" in tag_text:
        return True
    summary = direction.get("strategy_summary") or direction.get("summary") or {}
    if isinstance(summary, Mapping) and bool(summary.get("longest_road")):
        return True
    return False


def _preferred_wants_expand(player: Any) -> bool:
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return False
    if bool(direction.get("longest_road")):
        return True
    for key in (
        "required_roads_min",
        "roads_to_build",
        "remaining_roads_to_build",
        "roads_needed_for_settle",
        "next_roads_to_settle",
    ):
        if _safe_int(direction.get(key), 0) > 0:
            return True
    action = str(direction.get("supporting_action_type") or direction.get("action_type") or "").lower()
    if "settle" in action or "road" in action or "expand" in action:
        return True
    target = direction.get("preferred_settlement_target") or direction.get("new_settlement_target")
    if target is not None:
        return True
    return False


def _roads_needed_for_settle(player: Any) -> int:
    """Best-effort roads still needed to open preferred settle (0 = unknown/none)."""
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return 0
    for key in (
        "roads_needed_for_settle",
        "next_roads_to_settle",
        "roads_to_preferred_settle",
        "remaining_roads_to_build",
        "required_roads_min",
        "roads_to_build",
    ):
        v = _safe_int(direction.get(key), -1)
        if v >= 0:
            return v
    # Nested remaining / portfolio hints
    rem = direction.get("remaining") or direction.get("remaining_need") or {}
    if isinstance(rem, Mapping):
        for key in ("roads", "required_roads_min", "roads_to_build"):
            v = _safe_int(rem.get(key), -1)
            if v >= 0:
                return v
    return 0


def _playable_count_from_summary(player: Any, card_type: str) -> int:
    ct = str(card_type)
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            row_list = list(row or [])
            if not row_list or str(row_list[0]) != ct:
                continue
            while len(row_list) < 4:
                row_list.append(0)
            return max(0, int(row_list[2] or 0))
    except Exception:
        pass
    try:
        return sum(1 for c in (getattr(player, "development_cards", []) or []) if str(c) == ct)
    except Exception:
        return 0


def stub_alt_dcard_score(game: Any, player: Any) -> Dict[str, Any]:
    """Stub opportunity cost for other playable DCards (pre YOP/Monopoly/Knight full AI).

    Returns a soft score and which card drives it. Real cross-card EV comes later;
    this only blocks non-critical TFR when another card looks urgently valuable.
    """
    best = 0.0
    best_card = None
    details: Dict[str, float] = {}

    # Knight stub: high if 2 army already (LA-crit shape) or preferred LA
    k = _playable_count_from_summary(player, "knight")
    if k > 0:
        army = _safe_int(getattr(player, "size_largest_army", 0), 0)
        direction = getattr(player, "strategic_direction", None) or {}
        wants_la = False
        if isinstance(direction, Mapping):
            wants_la = bool(direction.get("biggest_army") or direction.get("largest_army"))
        score = 2.0
        if army >= 2:
            score = 8.0  # likely LA-crit competing with TFR
        elif wants_la and army >= 1:
            score = 5.0
        details["knight"] = score
        if score > best:
            best, best_card = score, "knight"

    yop = _playable_count_from_summary(player, "year_of_plenty")
    if yop > 0:
        # Mild stub — full YOP AI later
        score = 3.0
        details["year_of_plenty"] = score
        if score > best:
            best, best_card = score, "year_of_plenty"

    mono = _playable_count_from_summary(player, "monopoly")
    if mono > 0:
        score = 3.5
        details["monopoly"] = score
        if score > best:
            best, best_card = score, "monopoly"

    return {
        "score": float(best),
        "card": best_card,
        "details": details,
    }


def collect_tfr_features(
    game: Any,
    player: Any,
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Gather signals for MVP TFR play/hold.

    ``features_override`` lets tests inject S-Crit / LR-Crit without a full board.
    """
    free_n = free_roads_available(game, player)
    pieces = roads_remaining(game, player)
    try:
        roads_built = len(list(getattr(player, "roads", []) or []))
    except Exception:
        roads_built = 0

    # PR4: real continuous lengths (engine), not size_longest_route stubs
    lr_eval = evaluate_tfr_lr_claim(game, player, free_n=free_n)
    ai_len = int(lr_eval.get("length_now") or _road_length(player, game))
    length_after = int(lr_eval.get("length_after") or ai_len)
    max_opp_len = int(lr_eval.get("max_opp_length") or 0)
    holder_len = int(lr_eval.get("holder_length") or 0)
    someone_holds_lr = bool(lr_eval.get("someone_holds_lr"))
    lr_takes_now = bool(lr_eval.get("takes_now"))
    # Fallback if engine unavailable: never use naive +free_n for crit
    if not lr_eval.get("extra_edges") and free_n > 0 and not lr_takes_now:
        # Optimistic only as soft hint, not crit (length_after already real without extras)
        pass

    roads_needed = _roads_needed_for_settle(player)
    # S-Crit: free roads cover remaining path to preferred settle (1..free_n roads)
    s_crit = bool(roads_needed > 0 and free_n >= roads_needed)
    s_partial = bool(roads_needed > free_n > 0 and roads_needed <= free_n + 1)

    vp_ai = _vp(player)
    early = vp_ai <= EARLY_VP_MAX and roads_built <= EARLY_ROADS_MAX

    alt = stub_alt_dcard_score(game, player)

    features: Dict[str, Any] = {
        "free_roads_available": int(free_n),
        "roads_remaining": int(pieces),
        "roads_built": int(roads_built),
        "roads_needed_for_settle": int(roads_needed),
        "s_crit": bool(s_crit),
        "s_partial": bool(s_partial),
        "preferred_wants_expand": _preferred_wants_expand(player),
        "preferred_wants_lr": _preferred_wants_lr(player),
        "road_length_ai": int(ai_len),
        "road_length_after": int(length_after),
        "max_opp_road_length": int(max_opp_len),
        "lr_holder_length": int(holder_len),
        "someone_holds_lr": bool(someone_holds_lr),
        "lr_takes_now": bool(lr_takes_now),
        "lr_crit": bool(lr_takes_now),
        "lr_steals": bool(lr_eval.get("steals")),
        "lr_first_claim": bool(lr_eval.get("first_claim")),
        "lr_eval": dict(lr_eval),
        "lr_length_source": "engine",
        "vp_ai": int(vp_ai),
        "early_game": bool(early),
        "alt_dcard_score": float(alt.get("score") or 0),
        "alt_dcard_card": alt.get("card"),
        "alt_dcard_details": dict(alt.get("details") or {}),
        "playable_tfr": playable_tfr_count(player),
    }

    if features_override:
        for key, value in dict(features_override).items():
            features[key] = value
        # Re-derive dependents when callers only set primitives
        if "roads_needed_for_settle" in features_override and "s_crit" not in features_override:
            rn = _safe_int(features.get("roads_needed_for_settle"), 0)
            fn = _safe_int(features.get("free_roads_available"), free_n)
            features["s_crit"] = bool(rn > 0 and fn >= rn)
        if "lr_takes_now" in features_override and "lr_crit" not in features_override:
            features["lr_crit"] = bool(features.get("lr_takes_now"))
        if "vp_ai" in features_override or "roads_built" in features_override:
            if "early_game" not in features_override:
                features["early_game"] = (
                    _safe_int(features.get("vp_ai"), 0) <= EARLY_VP_MAX
                    and _safe_int(features.get("roads_built"), 0) <= EARLY_ROADS_MAX
                )

    return features


def _soft_tfr_score(features: Mapping[str, Any]) -> float:
    score = 0.0
    if bool(features.get("s_crit")):
        score += 12.0
    elif bool(features.get("s_partial")):
        score += 4.0
    if bool(features.get("lr_crit") or features.get("lr_takes_now")):
        score += 11.0
    if bool(features.get("preferred_wants_lr")):
        score += 2.0
    if bool(features.get("preferred_wants_expand")):
        score += 1.5
    rn = _safe_int(features.get("roads_needed_for_settle"), 0)
    free_n = _safe_int(features.get("free_roads_available"), 0)
    if rn > 0 and free_n > 0:
        score += max(0.0, 3.0 - 0.5 * max(0, rn - free_n))
    if bool(features.get("early_game")):
        score -= 3.0
    score -= 0.5 * _safe_float(features.get("alt_dcard_score"), 0.0)
    return score


def decide_mvp_play_hold(features: Mapping[str, Any], window: str = "post_roll") -> Dict[str, Any]:
    """MVP hard rules → play/hold for TFR (post-roll only in practice).

    Rule order (high → low):
      1. S-Crit — free roads complete preferred settle path
      2. LR-Crit — free roads take/steal Longest Road (real continuous length)
      3. Early-path override — short path (1–2 roads) even in early game
      4. Hold for stronger alt DCard (stub) when TFR is not critical
      5. Hold early game without path pressure
      6. Soft settle-path play when expand preferred and free roads help
      7. Default hold
    """
    window = str(window or "post_roll")
    soft = _soft_tfr_score(features)
    decision: Dict[str, Any] = {
        "play": False,
        "timing": None,
        "reason": REASON_HOLD_DEFAULT,
        "score": soft,
        "rule": "default",
        "available_timing_if_play": "post_roll" if window == "post_roll" else None,
    }

    def _play(reason: str, rule: str, score: float) -> Dict[str, Any]:
        decision.update(
            {
                "play": True,
                "timing": "post_roll" if window == "post_roll" else None,
                "reason": reason,
                "score": score,
                "rule": rule,
            }
        )
        return decision

    def _hold(reason: str, rule: str, score: float) -> Dict[str, Any]:
        decision.update(
            {
                "play": False,
                "timing": None,
                "reason": reason,
                "score": score,
                "rule": rule,
            }
        )
        return decision

    # Pre-roll should never play TFR (gates also block).
    if window != "post_roll":
        return _hold(REASON_TFR_PRE_ROLL, "pre_roll_blocked", soft)

    rn = _safe_int(features.get("roads_needed_for_settle"), 0)
    free_n = _safe_int(features.get("free_roads_available"), 0)

    # 1) Settlement critical path
    if bool(features.get("s_crit")):
        return _play(REASON_S_CRIT, "s_crit", max(soft, 12.0))

    # 2) Longest Road critical
    if bool(features.get("lr_crit") or features.get("lr_takes_now")):
        return _play(REASON_LR_CRIT, "lr_crit", max(soft, 11.0))

    # 3) Phase A: early-path override — distance 1–2 free-road steps
    #    Play even in early_game when path is short and expand preferred (or path known).
    short_path = bool(rn in (1, 2) and free_n >= rn)
    if short_path and (
        bool(features.get("preferred_wants_expand") or features.get("preferred_wants_lr"))
        or bool(features.get("s_partial"))
        or rn > 0
    ):
        # Still respect a very strong alt (LA knight) only if not path-critical distance 1
        alt_early = _safe_float(features.get("alt_dcard_score"), 0.0)
        if not (alt_early >= ALT_DCARD_BLOCK_MIN + 2.0 and rn > 1):
            return _play(REASON_EARLY_PATH, "early_path", max(soft, 8.0))

    # 4) Alt DCard stub — only blocks non-critical TFR
    alt = _safe_float(features.get("alt_dcard_score"), 0.0)
    if alt >= ALT_DCARD_BLOCK_MIN:
        return _hold(REASON_HOLD_ALT_DCARD, "hold_alt_dcard", soft)

    # 5) Early game option value (no short path)
    if bool(features.get("early_game")):
        return _hold(REASON_HOLD_EARLY, "hold_early", soft)

    # 6) Soft settle-path: preferred expand and free roads progress path
    if (
        bool(features.get("preferred_wants_expand") or features.get("preferred_wants_lr"))
        and rn > 0
        and free_n > 0
        and soft >= SETTLE_PATH_SCORE_MIN
    ):
        return _play(REASON_SETTLE_PATH, "settle_path", soft)

    if rn <= 0 and free_n > 0 and soft < SETTLE_PATH_SCORE_MIN:
        return _hold(REASON_HOLD_WEAK, "hold_weak_path", soft)

    return _hold(REASON_HOLD_DEFAULT, "hold_default", soft)


def _empty_plan(
    *,
    play: bool = False,
    timing: Optional[str] = None,
    reason: str,
    legal: bool = False,
    window: str = "unknown",
    player_id: Optional[int] = None,
    gates: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "ok": True,
        "action": "plan_ai_play_tfr",
        "card": CARD_TYPE,
        "stage": STAGE,
        "play": bool(play),
        "timing": timing,
        "reason": str(reason or ""),
        "legal": bool(legal),
        "window": window,
        "player_id": player_id,
        "free_roads_available": int((gates or {}).get("free_roads_available") or 0),
        "roads_remaining": int((gates or {}).get("roads_remaining") or 0),
        "road_ids": [],
        "roads_to_place": 0,
        "road_path": None,
        "road_path_ok": None,
        "target_settlement_id": None,
        "gates": dict(gates or {}),
        "failed_reasons": [],
        "playable_tfr_count": int((gates or {}).get("playable_tfr_count") or 0),
        "score": None,
        "features": {},
        "rule": None,
        "warnings": [],
        "executed": False,
        "notes": (
            "Thin pipeline: plan play/hold + free-road path; "
            "execute_ai_play_tfr places free roads and re-scans."
        ),
    }
    if extra:
        plan.update(extra)
    return plan


def log_ai_tfr_plan(game: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Persist plan on game and append a compact decision-trace row."""
    plan = dict(plan or {})
    window = str(plan.get("window") or "unknown")

    try:
        game.last_ai_tfr_plan = plan
    except Exception:
        pass

    try:
        by_window = getattr(game, "last_ai_tfr_plan_by_window", None)
        if not isinstance(by_window, dict):
            by_window = {}
        by_window[window] = plan
        game.last_ai_tfr_plan_by_window = by_window
    except Exception:
        pass

    if window == "pre_roll":
        try:
            game.last_ai_tfr_plan_pre_roll = plan
        except Exception:
            pass
    elif window == "post_roll":
        try:
            game.last_ai_tfr_plan_post_roll = plan
        except Exception:
            pass

    trace_row = {
        "kind": "play_tfr",
        "stage": plan.get("stage"),
        "window": window,
        "play": bool(plan.get("play")),
        "timing": plan.get("timing"),
        "reason": plan.get("reason"),
        "legal": bool(plan.get("legal")),
        "player_id": plan.get("player_id"),
        "playable_tfr_count": plan.get("playable_tfr_count"),
        "free_roads_available": plan.get("free_roads_available"),
        "roads_remaining": plan.get("roads_remaining"),
        "score": plan.get("score"),
        "rule": plan.get("rule"),
        "road_ids": list(plan.get("road_ids") or []),
        "roads_to_place": plan.get("roads_to_place"),
        "road_path_ok": plan.get("road_path_ok"),
        "target_settlement_id": plan.get("target_settlement_id"),
    }
    try:
        trace = getattr(game, "current_ai_decision_trace", None)
        if not isinstance(trace, list):
            trace = []
            game.current_ai_decision_trace = trace
        trace.append(trace_row)
    except Exception:
        pass

    try:
        if bool(getattr(game, "execution_debug_print_tf", False)):
            print(
                "AI TFR plan "
                f"[P{plan.get('player_id')}] window={window} "
                f"legal={plan.get('legal')} play={plan.get('play')} "
                f"timing={plan.get('timing')} reason={plan.get('reason')} "
                f"score={plan.get('score')} rule={plan.get('rule')} "
                f"free_roads={plan.get('free_roads_available')} "
                f"roads={plan.get('road_ids')} path_ok={plan.get('road_path_ok')}"
            )
    except Exception:
        pass

    return plan


def _normalize_road_id(road: Any) -> Optional[List[int]]:
    """Return a sorted 2-int road edge ``[a, b]`` or None."""
    try:
        if isinstance(road, Mapping):
            for key in ("road_id", "road", "edge", "target_road", "id"):
                if key in road:
                    return _normalize_road_id(road.get(key))
            return None
        if isinstance(road, (list, tuple)) and len(road) >= 2:
            a, b = int(road[0]), int(road[1])
            return [a, b] if a <= b else [b, a]
    except Exception:
        return None
    return None


def _legal_road_candidates(game: Any, player: Any) -> List[Dict[str, Any]]:
    """Best-effort legal Build-road candidates from the execution scanner."""
    out: List[Dict[str, Any]] = []
    for attr in ("current_execution_choices", "current_actionable_choices"):
        try:
            rows = list(getattr(game, attr, None) or [])
        except Exception:
            rows = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            action = str(row.get("action", "") or "")
            if action not in {"Build road", "Build Road", "build_road"}:
                # Nested candidates on a build-road choice
                pass
            else:
                cands = list(row.get("candidates") or [])
                if cands:
                    for c in cands:
                        if isinstance(c, Mapping):
                            out.append(dict(c))
                else:
                    rid = _normalize_road_id(row)
                    if rid is not None:
                        out.append({"road_id": rid, "action": "Build road"})
                continue
            # Also accept raw road candidates without action label
            rid = _normalize_road_id(row)
            if rid is not None and (
                "road_id" in row or "road" in row or "edge" in row
            ):
                out.append(dict(row))
    # Deduplicate by edge
    seen = set()
    unique: List[Dict[str, Any]] = []
    for c in out:
        key = tuple(_normalize_road_id(c) or ())
        if len(key) != 2 or key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


def _roads_from_direction(player: Any) -> List[List[int]]:
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return []
    raw: Any = None
    for key in (
        "roads_to_build",
        "route_roads",
        "road_path",
        "roads",
        "next_roads",
    ):
        if key in direction and direction.get(key) is not None:
            raw = direction.get(key)
            break
    if raw is None:
        return []
    roads: List[List[int]] = []
    try:
        for item in list(raw):
            rid = _normalize_road_id(item)
            if rid is not None:
                roads.append(rid)
    except Exception:
        pass
    return roads


def attach_free_road_path(
    game: Any,
    player: Any,
    plan: Dict[str, Any],
    *,
    features: Optional[Mapping[str, Any]] = None,
    max_roads: Optional[int] = None,
) -> Dict[str, Any]:
    """Attach best free-road path when TFR play is decided.

    Uses ``core.ai_road_planner.build_ai_road_plan`` (same settlement-route
    intelligence as paid AI roads). Falls back to explicit
    ``strategic_direction`` road lists.

    Important: a weak or empty path **does not** set ``play=False``.
    """
    plan = dict(plan or {})
    if not bool(plan.get("play")):
        plan["road_path"] = None
        plan["road_path_ok"] = None
        plan["road_ids"] = []
        plan["roads_to_place"] = 0
        plan["target_settlement_id"] = None
        return plan

    warnings = list(plan.get("warnings") or [])
    features = features if features is not None else (plan.get("features") or {})
    free_n = _safe_int(
        max_roads
        if max_roads is not None
        else plan.get("free_roads_available")
        or features.get("free_roads_available")
        or free_roads_available(game, player),
        0,
    )
    free_n = max(0, min(MAX_FREE_ROADS, free_n))

    road_plan: Dict[str, Any] = {}
    source = "none"
    roads_raw: List[Any] = []

    # Optional test/injection override (highest priority)
    if features.get("road_ids_override") is not None:
        roads_raw = list(features.get("road_ids_override") or [])
        source = "features_override"
        road_plan = {
            "kind": "features_override",
            "roads_to_build": roads_raw,
            "route_source": source,
        }
    else:
        # S-LR-B: LR project edges first (claim-minimal free roads)
        try:
            from core.ai_lr_project import tfr_edges_from_lr_project

            lr_edges = tfr_edges_from_lr_project(game, player, free_n=free_n)
            if lr_edges:
                roads_raw = list(lr_edges)
                source = "slr_lr_project"
                road_plan = {
                    "kind": "lr_project",
                    "roads_to_build": roads_raw,
                    "next_road": roads_raw[0] if roads_raw else None,
                    "route_source": source,
                    "strategy_reason": "S-LR-B: free roads follow LR project",
                    "target_label": "LR project",
                }
        except Exception as exc:
            warnings.append(f"lr_project_path_error: {exc}")

        if not roads_raw:
            try:
                from core.ai_road_planner import build_ai_road_plan

                candidates = _legal_road_candidates(game, player)
                road_plan = build_ai_road_plan(game, player, candidates) or {}
                if not isinstance(road_plan, dict):
                    road_plan = {}
                if road_plan:
                    source = str(road_plan.get("route_source") or "build_ai_road_plan")
            except Exception as exc:
                warnings.append(f"road_planner_error: {exc}")
                road_plan = {}

            roads_raw = list(road_plan.get("roads_to_build") or [])
            if not roads_raw and road_plan.get("next_road") is not None:
                roads_raw = [road_plan.get("next_road")]

        # Fallback: explicit strategy direction roads (useful for LR/tests)
        if not roads_raw:
            direction_roads = _roads_from_direction(player)
            if direction_roads:
                roads_raw = direction_roads
                source = "strategic_direction_roads"
                road_plan = {
                    "kind": "direction_fallback",
                    "roads_to_build": direction_roads,
                    "route_source": source,
                    "target_settlement_id": (
                        (getattr(player, "strategic_direction", None) or {}).get(
                            "preferred_settlement_target"
                        )
                        if isinstance(getattr(player, "strategic_direction", None), Mapping)
                        else None
                    ),
                }

    road_ids: List[List[int]] = []
    seen = set()
    for raw in roads_raw:
        if len(road_ids) >= free_n:
            break
        rid = _normalize_road_id(raw)
        if rid is None:
            continue
        key = tuple(rid)
        if key in seen:
            continue
        seen.add(key)
        road_ids.append(rid)

    target_id = None
    try:
        target_id = road_plan.get("target_settlement_id")
        if target_id is not None:
            target_id = int(target_id)
    except Exception:
        target_id = None

    plan["road_path"] = road_plan if road_plan else None
    plan["road_path_source"] = source
    plan["road_ids"] = road_ids
    plan["roads_to_place"] = len(road_ids)
    plan["road_path_ok"] = bool(road_ids)
    plan["target_settlement_id"] = target_id
    plan["play"] = True  # never cancel on weak path

    if not road_ids:
        warnings.append("play_without_perfect_path")
        if free_n <= 0:
            warnings.append("no_free_road_slots")
        else:
            warnings.append("road_planner_returned_no_path")

    # PR4: re-evaluate LR-crit with the concrete free-road edges
    try:
        lr_eval = evaluate_tfr_lr_claim(
            game, player, free_n=free_n, extra_road_ids=road_ids
        )
        plan["lr_eval"] = dict(lr_eval)
        plan["road_length_after"] = int(lr_eval.get("length_after") or 0)
        plan["lr_takes_now"] = bool(lr_eval.get("takes_now"))
        if bool(lr_eval.get("takes_now")):
            # Promote reason when path actually claims LR (unless already s_crit)
            if str(plan.get("reason") or "") not in {REASON_S_CRIT}:
                plan["reason"] = REASON_LR_CRIT
                plan["rule"] = "lr_crit_after_path"
                try:
                    plan["score"] = max(float(plan.get("score") or 0), 11.0)
                except Exception:
                    plan["score"] = 11.0
            # Keep play True
            features = dict(plan.get("features") or {})
            features["lr_crit"] = True
            features["lr_takes_now"] = True
            features["road_length_after"] = int(lr_eval.get("length_after") or 0)
            plan["features"] = features
    except Exception as exc:
        warnings.append(f"lr_eval_error: {exc}")

    plan["warnings"] = warnings
    return plan


def plan_ai_play_tfr(
    game: Any,
    player: Any = None,
    *,
    window: Optional[str] = None,
    log: bool = True,
    features_override: Optional[Mapping[str, Any]] = None,
    skip_road_path: bool = False,
) -> Dict[str, Any]:
    """Plan whether the AI should play TFR (gates + MVP + free-road path).

    Parameters
    ----------
    features_override :
        Optional feature dict for tests / debugging.
    skip_road_path :
        When True, skip path attach (play/hold-only tests).
    """
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    player_id = _safe_player_id(player)
    gate_info = evaluate_ai_tfr_gates(game, player, window=window)
    resolved = str(gate_info.get("window") or "unknown")
    gates = dict(gate_info.get("gates") or {})

    if not gate_info.get("legal"):
        reason = str(
            gate_info.get("primary_gate_reason")
            or (gate_info.get("failed_reasons") or [REASON_WRONG_STATE])[0]
        )
        plan = _empty_plan(
            play=False,
            timing=None,
            reason=reason,
            legal=False,
            window=resolved,
            player_id=player_id,
            gates=gates,
            extra={
                "failed_reasons": list(gate_info.get("failed_reasons") or []),
                "playable_tfr_count": int(gate_info.get("playable_tfr_count") or 0),
                "roads_remaining": int(gate_info.get("roads_remaining") or 0),
                "free_roads_available": int(gate_info.get("free_roads_available") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
            },
        )
    else:
        features = collect_tfr_features(
            game, player, features_override=features_override
        )
        features.setdefault("free_roads_available", int(gate_info.get("free_roads_available") or 0))
        features.setdefault("roads_remaining", int(gate_info.get("roads_remaining") or 0))
        decision = decide_mvp_play_hold(features, resolved)
        plan = _empty_plan(
            play=bool(decision.get("play")),
            timing=decision.get("timing"),
            reason=str(decision.get("reason") or REASON_HOLD_DEFAULT),
            legal=True,
            window=resolved,
            player_id=player_id,
            gates=gates,
            extra={
                "failed_reasons": [],
                "playable_tfr_count": int(gate_info.get("playable_tfr_count") or 0),
                "roads_remaining": int(gate_info.get("roads_remaining") or 0),
                "free_roads_available": int(gate_info.get("free_roads_available") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
                "available_timing_if_play": decision.get("available_timing_if_play"),
                "score": decision.get("score"),
                "features": features,
                "rule": decision.get("rule"),
            },
        )
        if bool(plan.get("play")) and not skip_road_path:
            plan = attach_free_road_path(game, player, plan, features=features)

    if log:
        plan = log_ai_tfr_plan(game, plan)
    return plan


def _consume_tfr_card(game: Any, player: Any) -> Dict[str, Any]:
    """Remove one playable TFR from the player via Game helpers when possible."""
    remover = getattr(game, "_remove_development_card_from_player", None)
    if callable(remover):
        if remover(player, CARD_TYPE):
            return {"ok": True, "source": "game_remove"}
        try:
            idx_fn = getattr(game, "_execution_dcard_summary_index", None)
            idx = int(idx_fn(CARD_TYPE)) if callable(idx_fn) else 2
            row = player.dcard_summary[idx]
            if int(row[2] or 0) <= 0:
                return {"ok": False, "reason": REASON_NO_TFR}
            row[2] = int(row[2]) - 1
            row[3] = int(row[3] or 0) + 1
            cards = list(getattr(player, "development_cards", []) or [])
            for i, c in enumerate(cards):
                if str(c) == CARD_TYPE:
                    cards.pop(i)
                    break
            player.development_cards = cards
            player.number_of_dcards = len(cards)
            return {"ok": True, "source": "summary_force"}
        except Exception:
            return {"ok": False, "reason": "could_not_consume_tfr"}

    cards = list(getattr(player, "development_cards", []) or [])
    for i, c in enumerate(cards):
        if str(c) == CARD_TYPE:
            cards.pop(i)
            player.development_cards = cards
            try:
                for row in list(getattr(player, "dcard_summary", []) or []):
                    if row and str(row[0]) == CARD_TYPE:
                        while len(row) < 4:
                            row.append(0)
                        if int(row[2] or 0) > 0:
                            row[2] = int(row[2]) - 1
                        row[3] = int(row[3] or 0) + 1
                        break
            except Exception:
                pass
            return {"ok": True, "source": "fallback_list"}
    return {"ok": False, "reason": REASON_NO_TFR}


def _place_one_free_road(game: Any, player: Any, road_id: Sequence[int]) -> Dict[str, Any]:
    """Place one free TFR road via shared human free-road executor when present."""
    builder = getattr(game, "execute_human_build_road_action", None)
    if callable(builder):
        try:
            return dict(builder(road_id, free=True) or {})
        except TypeError:
            try:
                return dict(builder(road_id) or {})
            except Exception as exc:
                return {"ok": False, "reason": str(exc), "road_id": list(road_id)}
        except Exception as exc:
            return {"ok": False, "reason": str(exc), "road_id": list(road_id)}

    # Minimal fallback for pure unit tests without board
    rid = _normalize_road_id(road_id)
    if rid is None:
        return {"ok": False, "reason": "missing_road"}
    try:
        roads = list(getattr(player, "roads", []) or [])
        key = tuple(rid)
        if key not in {tuple(sorted(r[:2])) if isinstance(r, (list, tuple)) else r for r in roads}:
            roads.append(rid)
            player.roads = roads
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "road_id": rid}

    pending = getattr(game, "pending_tfr_play", None) or {}
    if isinstance(pending, dict) and pending.get("active"):
        placed = int(pending.get("roads_placed", 0) or 0) + 1
        remaining = max(0, int(pending.get("roads_remaining_to_place", 0) or 0) - 1)
        placed_ids = list(pending.get("placed_road_ids") or [])
        placed_ids.append(list(rid))
        pending["roads_placed"] = placed
        pending["roads_remaining_to_place"] = remaining
        pending["placed_road_ids"] = placed_ids
        game.pending_tfr_play = pending
        need_more = remaining > 0
        out = {
            "ok": True,
            "reason": "executed_fallback",
            "road_id": list(rid),
            "free": True,
            "tfr_roads_placed": placed,
            "tfr_roads_remaining": remaining,
            "tfr_need_another_road": need_more,
        }
        if not need_more:
            game.pending_tfr_play = {"active": False}
            out["tfr_complete"] = {"ok": True, "early": False}
            try:
                recompute = getattr(game, "recompute_longest_road", None)
                if callable(recompute):
                    recompute(
                        reason="after_ai_tfr_fallback_complete",
                        emit_events=True,
                        refresh_scoreboard=True,
                    )
            except Exception:
                pass
        else:
            try:
                recompute = getattr(game, "recompute_longest_road", None)
                if callable(recompute):
                    recompute(
                        reason="after_ai_tfr_fallback_road",
                        emit_events=True,
                        refresh_scoreboard=False,
                    )
            except Exception:
                pass
        return out
    return {"ok": True, "reason": "executed_fallback", "road_id": list(rid), "free": True}


def execute_ai_play_tfr(
    game: Any,
    player: Any = None,
    *,
    plan: Optional[Mapping[str, Any]] = None,
    window: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Thin execute: consume TFR, place free roads from plan, re-scan for Continue.

    After roads are placed, calls ``continue_action_selection_after_action`` so
    a settlement (or other buy) unlocked by the free roads can appear in the
    AI Continue plan.
    """
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    result: Dict[str, Any] = {
        "ok": False,
        "action": "Play Two Free Roads",
        "source": "ai",
        "stage": STAGE,
        "reason": "",
        "player_id": _safe_player_id(player),
        "plan": None,
        "roads_placed": [],
        "roads_failed": [],
        "slice_d": None,
        "executed": False,
    }

    if plan is None:
        plan = plan_ai_play_tfr(game, player, window=window or "post_roll", log=True)
    plan = dict(plan or {})
    result["plan"] = plan

    if not bool(plan.get("legal")) and not force:
        result["reason"] = str(plan.get("reason") or "not_legal")
        return result
    if not bool(plan.get("play")) and not force:
        result["reason"] = str(plan.get("reason") or "plan_hold")
        return result

    gate_window = "post_roll"
    gates = evaluate_ai_tfr_gates(game, player, window=gate_window)
    if not gates.get("legal") and not force:
        result["reason"] = str(gates.get("primary_gate_reason") or "not_legal_at_execute")
        result["gates"] = gates.get("gates")
        return result

    if _is_human_player(game, player):
        result["reason"] = REASON_HUMAN_PLAYER
        return result

    ensure = getattr(game, "_ensure_player_dcard_state", None)
    if callable(ensure):
        try:
            ensure(player)
        except Exception:
            pass

    consumed = _consume_tfr_card(game, player)
    if not consumed.get("ok"):
        result["reason"] = str(consumed.get("reason") or "could_not_consume_tfr")
        return result

    mark = getattr(game, "_mark_dcard_played_this_turn", None)
    if callable(mark):
        try:
            mark(CARD_TYPE, player)
        except TypeError:
            try:
                mark(CARD_TYPE)
            except Exception:
                pass
        except Exception:
            pass
    else:
        try:
            td = getattr(game, "myturn", None) or getattr(game, "turn_details", None)
            if td is not None:
                td.dcard_played_in_turn_TF = True
                try:
                    td.dcard_played_in_turn_player_id = _safe_player_id(player)
                except Exception:
                    pass
        except Exception:
            pass

    free_n = _safe_int(plan.get("free_roads_available"), 0) or free_roads_available(game, player)
    free_n = max(1, min(MAX_FREE_ROADS, free_n)) if free_roads_available(game, player) > 0 else 0
    # Prefer planned free count / roads_to_place
    planned_ids = list(plan.get("road_ids") or [])
    if not planned_ids:
        # Last chance: re-attach path
        try:
            plan = attach_free_road_path(game, player, plan, features=plan.get("features") or {})
            planned_ids = list(plan.get("road_ids") or [])
        except Exception:
            pass
    roads_total = min(free_n if free_n > 0 else MAX_FREE_ROADS, max(len(planned_ids), 1) if planned_ids else free_n)
    if roads_total <= 0:
        roads_total = min(MAX_FREE_ROADS, free_roads_available(game, player))
    if roads_total <= 0:
        # No pieces — should have been gated; complete empty
        roads_total = 0

    pieces_left = roads_remaining(game, player)
    roads_total = min(roads_total if roads_total > 0 else len(planned_ids) or 0, pieces_left, MAX_FREE_ROADS)
    if not planned_ids:
        roads_total = 0

    # Prefer placing exactly the planned edges (cap by pieces)
    to_place = planned_ids[: min(len(planned_ids), pieces_left, MAX_FREE_ROADS)]
    roads_total = len(to_place) if to_place else 0

    try:
        game.pending_tfr_play = {
            "active": True,
            "player_id": _safe_player_id(player),
            "roads_total": int(max(roads_total, 1) if to_place else 0) or max(len(to_place), 0),
            "roads_placed": 0,
            "roads_remaining_to_place": int(len(to_place)),
            "placed_road_ids": [],
            "pieces_at_start": int(pieces_left),
            "source": "ai",
        }
        if not to_place:
            game.pending_tfr_play = {"active": False}
    except Exception:
        pass

    try:
        emit = getattr(game, "emit_twitter_event", None)
        if callable(emit):
            emit(
                _safe_player_id(player),
                f"AI plays Two Free Roads — place {len(to_place)} free road(s)",
            )
    except Exception:
        pass
    try:
        rec = getattr(game, "record_turn_event", None)
        if callable(rec):
            rec(
                player=player,
                event_type="play_dcard",
                source="ai_play_tfr",
                message=f"AI plays Two Free Roads ({len(to_place)} free)",
                metadata={
                    "card": CARD_TYPE,
                    "roads_total": len(to_place),
                    "road_ids": list(to_place),
                    "plan_reason": plan.get("reason"),
                },
            )
    except Exception:
        pass

    placed: List[List[int]] = []
    failed: List[Dict[str, Any]] = []
    for rid in to_place:
        place_res = _place_one_free_road(game, player, rid)
        if bool(place_res.get("ok")):
            placed.append(list(place_res.get("road_id") or rid))
        else:
            failed.append(
                {
                    "road_id": list(rid),
                    "reason": place_res.get("reason") or "place_failed",
                }
            )

    # Ensure pending TFR is cleared even if some placements failed
    pending = getattr(game, "pending_tfr_play", None) or {}
    if isinstance(pending, dict) and pending.get("active"):
        complete = getattr(game, "_complete_tfr_play", None)
        if callable(complete):
            try:
                complete(player, early=True)
            except Exception:
                game.pending_tfr_play = {"active": False}
        else:
            game.pending_tfr_play = {"active": False}

    # Continue re-scan so settle / builds unlocked by free roads can follow
    slice_d = None
    cont = getattr(game, "continue_action_selection_after_action", None)
    if callable(cont):
        try:
            slice_d = cont(
                "after_ai_play_tfr",
                player=player,
                action_result={
                    "action": "Play Two Free Roads",
                    "ok": True,
                    "roads_placed": list(placed),
                    "roads_failed": list(failed),
                },
                clear_forced_locks=True,
            )
        except Exception as exc:
            slice_d = {"ok": False, "reason": str(exc)}
    else:
        try:
            ref = getattr(game, "refresh_strategy_after_event", None)
            if callable(ref):
                ref("after_ai_play_tfr", kind="hand")
            else:
                ref2 = getattr(game, "refresh_strategy_context", None)
                if callable(ref2):
                    ref2("after_ai_play_tfr", mode="auto")
        except Exception:
            pass
        try:
            refa = getattr(game, "refresh_viable_actions", None)
            if callable(refa):
                refa("after_ai_play_tfr")
        except Exception:
            pass
        try:
            game.state = "ActionSelection"
        except Exception:
            pass
        slice_d = {"ok": True, "reason": "after_ai_play_tfr_fallback", "state": "ActionSelection"}

    result.update(
        {
            "ok": True,
            "executed": True,
            "reason": str(plan.get("reason") or "executed"),
            "timing": "post_roll",
            "roads_placed": placed,
            "roads_failed": failed,
            "roads_placed_count": len(placed),
            "target_settlement_id": plan.get("target_settlement_id"),
            "slice_d": slice_d,
            "state_after": str(getattr(game, "state", "") or ""),
        }
    )
    if failed:
        result.setdefault("warnings", [])
        if isinstance(result["warnings"], list):
            result["warnings"].append("some_free_roads_failed")
    if not placed:
        result.setdefault("warnings", [])
        if isinstance(result["warnings"], list):
            result["warnings"].append("play_without_perfect_path")

    try:
        game.last_ai_tfr_execute_result = result
    except Exception:
        pass
    try:
        plan["executed"] = True
        plan["execute_result"] = {
            "ok": True,
            "roads_placed": placed,
            "roads_failed": failed,
        }
        game.last_ai_tfr_plan = plan
    except Exception:
        pass

    try:
        refresh = getattr(game, "_refresh_gui_scoreboard_after_dcard_change", None)
        if callable(refresh):
            refresh("after_ai_play_tfr")
    except Exception:
        pass

    try:
        if bool(getattr(game, "execution_debug_print_tf", False)):
            print(
                "AI TFR EXECUTE "
                f"[P{result.get('player_id')}] reason={result.get('reason')} "
                f"placed={placed} failed={len(failed)} "
                f"state={result.get('state_after')}"
            )
    except Exception:
        pass

    return result


def maybe_execute_ai_tfr_for_window(
    game: Any,
    window: str = "post_roll",
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan for window; if play+post_roll, execute thin and return result."""
    plan = plan_ai_play_tfr(
        game,
        window=window,
        log=True,
        features_override=features_override,
    )
    out: Dict[str, Any] = {
        "planned": plan,
        "executed": False,
        "executed_result": None,
    }
    if str(window) != "post_roll":
        return out
    if not bool(plan.get("play")):
        return out
    if str(plan.get("timing") or "") != "post_roll":
        return out
    executed = execute_ai_play_tfr(game, plan=plan, window=window)
    out["executed"] = bool(executed.get("executed"))
    out["executed_result"] = executed
    return out


__all__ = [
    "STAGE",
    "CARD_TYPE",
    "REASON_SKELETON_HOLD",
    "REASON_S_CRIT",
    "REASON_LR_CRIT",
    "REASON_EARLY_PATH",
    "REASON_SETTLE_PATH",
    "REASON_HOLD_EARLY",
    "REASON_HOLD_ALT_DCARD",
    "REASON_TFR_PRE_ROLL",
    "REASON_NO_ROAD_PIECES",
    "playable_tfr_count",
    "roads_remaining",
    "free_roads_available",
    "evaluate_ai_tfr_gates",
    "evaluate_tfr_lr_claim",
    "collect_tfr_features",
    "stub_alt_dcard_score",
    "decide_mvp_play_hold",
    "attach_free_road_path",
    "plan_ai_play_tfr",
    "log_ai_tfr_plan",
    "execute_ai_play_tfr",
    "maybe_execute_ai_tfr_for_window",
]
