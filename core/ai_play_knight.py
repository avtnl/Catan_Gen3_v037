"""AI Play Knight — gates, MVP play/hold + timing, shared robber plan, execute.

Runtime pipeline:
  1. Gate legality
  2. MVP play/hold + timing
  3. If play → shared robber / steal planner
  4. Log reason codes
  5. Thin execute when play=True (pre_roll / post_roll AI turn hooks)

API:

  plan_ai_play_knight(game) -> {play, timing, reason, tile_id, steal_opponent_id, ...}
  execute_ai_play_knight(game, plan=...) -> {ok, timing, army_info, robber_result, ...}

Execute consumes the Knight, updates Largest Army, runs shared robber+steal,
and resumes AwaitingDiceRoll (pre) or ActionSelection (post). Weak placement
never blocks play; robber falls back to ``execute_basic_robber_strategy``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

# ── Reason codes (gates) ────────────────────────────────────────────────────
REASON_SKELETON_HOLD = "skeleton_hold"  # legacy; Stage 2 uses finer holds
REASON_NOT_EXECUTION = "not_execution_phase"
REASON_NO_PLAYER = "no_current_player"
REASON_HUMAN_PLAYER = "current_player_is_human"
REASON_ROBBER_ACTIVE = "robber_flow_already_active"
REASON_DCARD_ALREADY = "already_played_dcard_this_turn"
REASON_NO_KNIGHT = "no_playable_knight"
REASON_WRONG_STATE = "knight_not_legal_in_state"
REASON_DISCARD_PENDING = "discard_pending"
REASON_KNIGHT_PENDING = "knight_play_already_pending"

# ── Reason codes (MVP play / hold) ──────────────────────────────────────────
REASON_LA_CRIT = "la_crit"
REASON_LA_RACE = "la_race"
REASON_UNBLOCK_SELF = "unblock_self"
REASON_META_BLOCKED_PRE = "meta_self_blocked_promote_pre_roll"
REASON_DENY_LEADER = "deny_leader"
REASON_HOLD_LA_DELAY = "hold_la_delay"
REASON_HOLD_LOW_HEX = "hold_low_value_hex"
REASON_HOLD_WINNING_POST_ROLL = "hold_for_winning_post_roll_dcard"
REASON_SCORE_PLAY = "score_play"
REASON_HOLD_DETENTION = "hold_detention"
REASON_HOLD_FOR_SEVEN = "hold_for_seven"
REASON_HOLD_DEFAULT = "hold_default"
REASON_HOLD_WEAK_TARGETS = "hold_weak_targets"

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
DETENTION_HOLD_MIN = 3.0
SELF_BLOCK_SEVERITY_HIGH = 3.0
# Phase A: self-block below this is "low value hex" — prefer hold unless LA/deny
SELF_BLOCK_SEVERITY_LOW = 1.0
PLAY_SCORE_THRESHOLD = 4.0
LEADER_VP_THREAT = 8
WEAK_PLACEMENT_MAX = 1.5


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


def playable_knight_count(player: Any) -> int:
    """How many Knights the player may legally play (core-side, no GUI import).

    Prefers ``dcard_summary`` playable column (index 2). When a knight summary
    row exists, only that column counts (bought-this-turn / col1 is not
    playable). Falls back to counting ``development_cards`` named ``knight``
    only when no knight summary row is present.
    """
    if player is None:
        return 0
    found_knight_row = False
    try:
        summary = list(getattr(player, "dcard_summary", []) or [])
        for row in summary:
            row_list = list(row or [])
            if not row_list:
                continue
            if str(row_list[0]) != "knight":
                continue
            found_knight_row = True
            while len(row_list) < 4:
                row_list.append(0)
            return max(0, int(row_list[2] or 0))
    except Exception:
        found_knight_row = False
    if found_knight_row:
        return 0
    try:
        return sum(
            1 for c in (getattr(player, "development_cards", []) or []) if str(c) == "knight"
        )
    except Exception:
        return 0


def _resolve_window(game: Any, window: Optional[str]) -> str:
    """Return pre_roll | post_roll | unknown from explicit window or game state."""
    if window in ("pre_roll", "post_roll"):
        return str(window)
    state = str(getattr(game, "state", "") or "")
    if state == "AwaitingDiceRoll" or _dice_not_rolled(game):
        return "pre_roll"
    if state == "ActionSelection":
        return "post_roll"
    return "unknown"


def evaluate_ai_knight_gates(
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
        "dcard_slot_free": False,
        "has_playable_knight": False,
        "state_ok": False,
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

    if _dcard_already_played_this_turn(game):
        reasons_failed.append(REASON_DCARD_ALREADY)
    else:
        gates["dcard_slot_free"] = True

    k_count = playable_knight_count(player) if player is not None else 0
    gates["playable_knight_count"] = int(k_count)
    if k_count > 0:
        gates["has_playable_knight"] = True
    else:
        reasons_failed.append(REASON_NO_KNIGHT)

    if resolved == "pre_roll":
        state_ok = state == "AwaitingDiceRoll" or (
            _dice_not_rolled(game) and state not in ROBBER_FLOW_STATES
        )
    elif resolved == "post_roll":
        state_ok = state == "ActionSelection" and not _dice_not_rolled(game)
    else:
        state_ok = False
    gates["state_ok"] = bool(state_ok)
    if not state_ok:
        reasons_failed.append(REASON_WRONG_STATE)

    legal = (
        gates["phase_ok"]
        and gates["player_ok"]
        and gates["ai_ok"]
        and gates["not_robber_flow"]
        and gates["not_discard_pending"]
        and gates["not_knight_pending"]
        and gates["dcard_slot_free"]
        and gates["has_playable_knight"]
        and gates["state_ok"]
    )

    primary_reason = reasons_failed[0] if reasons_failed else REASON_HOLD_DEFAULT
    return {
        "legal": bool(legal),
        "gates": gates,
        "failed_reasons": reasons_failed,
        "primary_gate_reason": primary_reason if not legal else None,
        "window": resolved,
        "playable_knight_count": int(k_count),
        "state": state,
        "phase": phase,
    }


# ────────────────────────────────────────────────────────────────────────────
# Stage 2: features + MVP play/hold + timing
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


def _army_size(player: Any) -> int:
    try:
        return max(0, int(getattr(player, "size_largest_army", 0) or 0))
    except Exception:
        return 0


def _hand_size(player: Any) -> int:
    rcards = getattr(player, "rcards", None)
    if isinstance(rcards, Mapping):
        total = 0
        for v in rcards.values():
            try:
                total += int(v or 0)
            except Exception:
                pass
        return total
    try:
        return max(0, int(getattr(player, "number_of_rcards", 0) or 0))
    except Exception:
        return 0


def _preferred_wants_la(player: Any) -> bool:
    direction = getattr(player, "strategic_direction", None) or {}
    if not isinstance(direction, Mapping):
        return False
    if bool(direction.get("biggest_army") or direction.get("largest_army")):
        return True
    tags = direction.get("tags") or direction.get("way_tags") or []
    try:
        tag_text = " ".join(str(t).lower() for t in tags)
    except Exception:
        tag_text = str(tags).lower()
    if "largest army" in tag_text or "biggest_army" in tag_text or " la" in f" {tag_text}":
        return True
    summary = direction.get("strategy_summary") or direction.get("summary") or {}
    if isinstance(summary, Mapping) and bool(
        summary.get("largest_army") or summary.get("biggest_army")
    ):
        return True
    return False


def _pips(value: Any) -> float:
    try:
        from core.game_7logic import _pips_from_tile_value

        return float(_pips_from_tile_value(int(value)))
    except Exception:
        try:
            v = int(value)
        except Exception:
            return 0.0
        if not (2 <= v <= 12) or v == 7:
            return 0.0
        return float(6 - abs(7 - v))


def _current_robber_tile_id(game: Any) -> Optional[int]:
    try:
        from core.game_7logic import current_robber_tile_id

        tid = current_robber_tile_id(game)
        if tid is not None:
            return int(tid)
    except Exception:
        pass
    # Soft fallbacks for tests / partial boards
    for attr in ("robber_tile_id", "current_robber_tile_id"):
        try:
            v = getattr(game, attr, None)
            if v is not None:
                return int(v)
        except Exception:
            pass
    return None


def _robber_hex_impact(game: Any, player: Any, tile_id: Optional[int]) -> Dict[str, float]:
    """Return self/opponent production weights on the robber tile."""
    out = {
        "self_weight": 0.0,
        "self_pips_weight": 0.0,
        "opp_weight": 0.0,
        "opp_pips_weight": 0.0,
        "pips": 0.0,
        "tile_value": 0.0,
    }
    if tile_id is None:
        return out
    board = getattr(game, "board", None)
    tile = None
    try:
        for t in list(getattr(board, "tiles", []) or []):
            if t is None:
                continue
            if int(getattr(t, "id", -1)) == int(tile_id):
                tile = t
                break
    except Exception:
        tile = None
    if tile is None:
        return out

    pips = _pips(getattr(tile, "value", 0))
    out["pips"] = pips
    try:
        out["tile_value"] = float(getattr(tile, "value", 0) or 0)
    except Exception:
        out["tile_value"] = 0.0

    player_color = str(getattr(player, "color", "") or "")
    try:
        from core.game_7logic import _tile_buildings

        buildings = _tile_buildings(game, tile)
    except Exception:
        buildings = []
        # Minimal corner fallback for tests
        for corner in list(getattr(tile, "corners", []) or []):
            if isinstance(corner, Mapping):
                color = str(corner.get("color", "") or "")
                kind = str(corner.get("kind", corner.get("type", "")) or "").lower()
            else:
                color = str(getattr(corner, "color", "") or "")
                kind = str(getattr(corner, "kind", getattr(corner, "type", "")) or "").lower()
            if kind == "city":
                w = 2.0
            elif kind == "settlement":
                w = 1.0
            else:
                continue
            buildings.append({"color": color, "weight": w})

    for b in buildings:
        color = str(b.get("color", "") or "")
        w = _safe_float(b.get("weight"), 0.0)
        if w <= 0:
            continue
        if color and color == player_color:
            out["self_weight"] += w
            out["self_pips_weight"] += pips * w
        elif color and color not in {"", "Blank", "None"}:
            out["opp_weight"] += w
            out["opp_pips_weight"] += pips * w
    return out


def _best_placement_score(game: Any, player: Any) -> float:
    """Soft EV of moving robber via existing scorer; 0 if unavailable."""
    try:
        from core.game_7logic import score_robber_tiles

        candidates = score_robber_tiles(game, player, avoid_self_block=True)
        if not candidates:
            candidates = score_robber_tiles(game, player, avoid_self_block=False)
        if not candidates:
            return 0.0
        best = max(float(c.get("score", 0.0) or 0.0) for c in candidates)
        return best
    except Exception:
        return _safe_float(getattr(game, "_test_best_placement_score", 0.0), 0.0)


def collect_knight_features(
    game: Any,
    player: Any,
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Gather board/player signals for MVP Knight play/hold.

    ``features_override`` lets tests inject signals without a full board.
    Override keys replace computed values after collection.
    """
    players = list(getattr(game, "players", []) or [])
    pid = _safe_player_id(player)
    army_ai = _army_size(player)
    army_after = army_ai + 1
    opp_armies: List[int] = []
    max_opp_army = 0
    max_opp_vp = 0
    for p in players:
        if p is None:
            continue
        if _safe_player_id(p) == pid:
            continue
        a = _army_size(p)
        opp_armies.append(a)
        max_opp_army = max(max_opp_army, a)
        max_opp_vp = max(max_opp_vp, _vp(p))

    # Largest Army: need ≥3 and strictly more knights than every opponent.
    la_takes_now = army_after >= 3 and army_after > max_opp_army
    la_race_urgent = bool(
        _preferred_wants_la(player)
        or (army_ai >= 2 and max_opp_army >= 2)
        or (army_ai == 2 and max_opp_army >= 1 and army_after > max_opp_army)
    )

    robber_tile = _current_robber_tile_id(game)
    impact = _robber_hex_impact(game, player, robber_tile)
    self_block_severity = float(impact["self_pips_weight"])
    self_blocked = self_block_severity > 0.0
    detention_value = float(impact["opp_pips_weight"])
    # Detention only "good" if we are not also sitting on that hex.
    detention_good = (not self_blocked) and detention_value >= DETENTION_HOLD_MIN

    from core.ai_dcard_timing import virtual_vp

    vp_ai = _vp(player)
    max_opp_vvp = 0
    for p in players:
        if p is None or _safe_player_id(p) == pid:
            continue
        max_opp_vvp = max(max_opp_vvp, virtual_vp(p))
    # Virtual VP leaders count as near-win earlier (hidden DCards)
    leader_near_win = (
        max_opp_vp >= LEADER_VP_THREAT
        or vp_ai >= LEADER_VP_THREAT
        or max_opp_vvp >= LEADER_VP_THREAT + 1
    )
    placement_score = _best_placement_score(game, player)
    can_hurt = placement_score >= WEAK_PLACEMENT_MAX
    # Delay pure LA claim when no race and not late (community target management)
    la_delay = bool(
        la_takes_now
        and not la_race_urgent
        and not self_blocked
        and not leader_near_win
        and vp_ai < LEADER_VP_THREAT
        and max_opp_army < 2
    )

    features: Dict[str, Any] = {
        "robber_tile_id": robber_tile,
        "self_blocked": bool(self_blocked),
        "self_block_severity": self_block_severity,
        "self_block_high": self_block_severity >= SELF_BLOCK_SEVERITY_HIGH,
        "self_block_low": bool(
            self_blocked and 0.0 < self_block_severity < SELF_BLOCK_SEVERITY_LOW
        ),
        "detention_value": detention_value,
        "detention_good": bool(detention_good),
        "army_ai": army_ai,
        "army_after": army_after,
        "max_opp_army": max_opp_army,
        "la_takes_now": bool(la_takes_now),
        "la_race_urgent": bool(la_race_urgent),
        "la_delay": bool(la_delay),
        "preferred_wants_la": _preferred_wants_la(player),
        "vp_ai": vp_ai,
        "max_opp_vp": max_opp_vp,
        "max_opp_virtual_vp": max_opp_vvp,
        "leader_near_win": bool(leader_near_win),
        "placement_score": float(placement_score),
        "can_hurt_with_placement": bool(can_hurt),
        "hand_size": _hand_size(player),
        "playable_knights": playable_knight_count(player),
    }

    if features_override:
        for key, value in dict(features_override).items():
            features[key] = value
        # Re-derive dependent flags if caller only set severity.
        if "self_block_severity" in features_override and "self_blocked" not in features_override:
            features["self_blocked"] = float(features["self_block_severity"]) > 0.0
        if "self_block_severity" in features_override and "self_block_high" not in features_override:
            features["self_block_high"] = (
                float(features["self_block_severity"]) >= SELF_BLOCK_SEVERITY_HIGH
            )
        if "self_block_severity" in features_override and "self_block_low" not in features_override:
            sev = float(features["self_block_severity"] or 0)
            features["self_block_low"] = bool(
                bool(features.get("self_blocked")) and 0.0 < sev < SELF_BLOCK_SEVERITY_LOW
            )
        if "detention_value" in features_override and "detention_good" not in features_override:
            features["detention_good"] = (not bool(features.get("self_blocked"))) and (
                float(features["detention_value"]) >= DETENTION_HOLD_MIN
            )
        # Recompute la_delay if race/LA flags overridden
        if "la_delay" not in features_override:
            features["la_delay"] = bool(
                bool(features.get("la_takes_now"))
                and not bool(features.get("la_race_urgent"))
                and not bool(features.get("self_blocked"))
                and not bool(features.get("leader_near_win"))
                and int(features.get("vp_ai") or 0) < LEADER_VP_THREAT
                and int(features.get("max_opp_army") or 0) < 2
            )

    return features


def dice_independent_play_desire(features: Mapping[str, Any]) -> Dict[str, Any]:
    """Would we play Knight for reasons that do not depend on this dice roll?

    Used by the meta-rule: self_blocked ∧ would_play_post → promote to pre_roll.
    """
    f = features
    if bool(f.get("la_takes_now")) and not bool(f.get("la_delay")):
        return {"want": True, "reason": REASON_LA_CRIT, "score": 12.0}
    # Low-value self-block does not force dice-independent desire
    if bool(f.get("self_blocked")) and not bool(f.get("self_block_low")) and (
        bool(f.get("self_block_high")) or float(f.get("self_block_severity") or 0) > 0
    ):
        sev = float(f.get("self_block_severity") or 0)
        score = 6.0 + min(4.0, sev)
        return {"want": True, "reason": REASON_UNBLOCK_SELF, "score": score}
    if bool(f.get("la_race_urgent")) and int(f.get("army_ai") or 0) >= 2:
        return {"want": True, "reason": REASON_LA_RACE, "score": 7.0}
    if bool(f.get("leader_near_win")) and bool(f.get("can_hurt_with_placement")):
        return {"want": True, "reason": REASON_DENY_LEADER, "score": 8.0}
    if bool(f.get("leader_near_win")) and float(f.get("placement_score") or 0) > 0:
        return {"want": True, "reason": REASON_DENY_LEADER, "score": 5.5}
    # Soft: strong placement alone is dice-independent board control.
    place = float(f.get("placement_score") or 0)
    if place >= PLAY_SCORE_THRESHOLD + 2:
        return {"want": True, "reason": REASON_SCORE_PLAY, "score": place}
    return {"want": False, "reason": REASON_HOLD_DEFAULT, "score": 0.0}


def _soft_play_score(features: Mapping[str, Any]) -> float:
    """Simple additive score when hard rules do not fire."""
    score = 0.0
    if bool(features.get("la_takes_now")):
        score += 12.0
    if bool(features.get("la_race_urgent")):
        score += 3.0
    if bool(features.get("self_blocked")):
        score += 4.0 + min(4.0, float(features.get("self_block_severity") or 0))
    if bool(features.get("leader_near_win")):
        score += 3.5
    score += 0.5 * float(features.get("placement_score") or 0)
    if bool(features.get("detention_good")):
        score -= 5.0  # releasing a good camp is costly
    if int(features.get("army_ai") or 0) == 2 and not bool(features.get("la_race_urgent")):
        score -= 1.0  # mild preference to time 3rd knight
    return score


def decide_mvp_play_hold(
    features: Mapping[str, Any],
    window: str,
) -> Dict[str, Any]:
    """MVP hard rules + soft score → play/hold and timing.

    Rule order (high → low):
      1. LA-crit → play now
      2. Hold detention (good enemy camp, not self-blocked, not LA-crit)
      3. Meta: would_play_dice_indep ∧ self_blocked ∧ pre_roll → play pre_roll
      4. Self-blocked (high / any) → play in current window
      5. Pre-roll only: hold_for_seven when not forced to play
      6. Deny leader / LA race / soft score
      7. Default hold
    """
    window = str(window or "unknown")
    desire = dice_independent_play_desire(features)
    soft = _soft_play_score(features)

    decision: Dict[str, Any] = {
        "play": False,
        "timing": None,
        "reason": REASON_HOLD_DEFAULT,
        "score": soft,
        "rule": "default",
        "dice_independent_desire": dict(desire),
        "available_timing_if_play": window if window in ("pre_roll", "post_roll") else None,
    }

    def _play(reason: str, rule: str, score: float) -> Dict[str, Any]:
        timing = window if window in ("pre_roll", "post_roll") else None
        # Meta promotion is only meaningful in pre_roll window (already there).
        decision.update(
            {
                "play": True,
                "timing": timing,
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

    # 1) LA-crit — play unless Phase-A delay (no race, not late, not blocked)
    if bool(features.get("la_takes_now")):
        if bool(features.get("la_delay")):
            return _hold(REASON_HOLD_LA_DELAY, "hold_la_delay", soft)
        return _play(REASON_LA_CRIT, "la_crit", max(soft, 12.0))

    # 2) Detention hold — do not release a good enemy camp without need.
    if bool(features.get("detention_good")) and not bool(features.get("self_blocked")):
        return _hold(REASON_HOLD_DETENTION, "hold_detention", soft)

    # 3) Meta-rule (pre_roll): if we would play post-roll for dice-independent
    #    reasons and we are self-blocked, play pre-roll to free production.
    if (
        window == "pre_roll"
        and bool(features.get("self_blocked"))
        and not bool(features.get("self_block_low"))
        and bool(desire.get("want"))
    ):
        # desire already includes pure unblock; tag meta when unblock is not the
        # sole reason OR always tag meta when blocked+want for clarity.
        meta_reason = REASON_META_BLOCKED_PRE
        if str(desire.get("reason")) == REASON_UNBLOCK_SELF:
            meta_reason = REASON_META_BLOCKED_PRE
        return _play(
            meta_reason,
            "meta_self_blocked_promote_pre_roll",
            max(soft, float(desire.get("score") or 0)),
        )

    # 4) Self-blocked → play, unless low-value hex without LA/deny urgency
    if bool(features.get("self_blocked")):
        sev = float(features.get("self_block_severity") or 0)
        low = bool(features.get("self_block_low")) or (
            0.0 < sev < SELF_BLOCK_SEVERITY_LOW
        )
        if low and not bool(features.get("la_race_urgent")) and not bool(
            features.get("leader_near_win")
        ):
            return _hold(REASON_HOLD_LOW_HEX, "hold_low_value_hex", soft)
        return _play(
            REASON_UNBLOCK_SELF,
            "unblock_self",
            max(soft, 6.0 + min(4.0, sev)),
        )

    # 5) Pre-roll: prefer hold through dice (free robber on 7) when not forced.
    if window == "pre_roll":
        # Exception: strong dice-independent desire that is not unblock (already handled)
        if bool(desire.get("want")) and str(desire.get("reason")) in {
            REASON_LA_RACE,
            REASON_DENY_LEADER,
            REASON_SCORE_PLAY,
        }:
            # Still allow hold_for_seven if placement is weak and reason is soft score only?
            if str(desire.get("reason")) == REASON_DENY_LEADER:
                return _play(REASON_DENY_LEADER, "deny_leader_pre", float(desire.get("score") or soft))
            if str(desire.get("reason")) == REASON_LA_RACE:
                return _play(REASON_LA_RACE, "la_race_pre", float(desire.get("score") or soft))
            if float(desire.get("score") or 0) >= PLAY_SCORE_THRESHOLD + 2:
                return _play(REASON_SCORE_PLAY, "score_play_pre", float(desire.get("score") or soft))
        return _hold(REASON_HOLD_FOR_SEVEN, "hold_for_seven", soft)

    # 6) Post-roll: race / leader / soft score
    if bool(features.get("la_race_urgent")) and int(features.get("army_ai") or 0) >= 2:
        return _play(REASON_LA_RACE, "la_race", max(soft, 7.0))

    if bool(features.get("leader_near_win")) and (
        bool(features.get("can_hurt_with_placement"))
        or float(features.get("placement_score") or 0) > 0
    ):
        return _play(REASON_DENY_LEADER, "deny_leader", max(soft, 5.5))

    if soft >= PLAY_SCORE_THRESHOLD and float(features.get("placement_score") or 0) >= WEAK_PLACEMENT_MAX:
        return _play(REASON_SCORE_PLAY, "score_play", soft)

    if float(features.get("placement_score") or 0) < WEAK_PLACEMENT_MAX and soft < PLAY_SCORE_THRESHOLD:
        return _hold(REASON_HOLD_WEAK_TARGETS, "hold_weak_targets", soft)

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
        "action": "plan_ai_play_knight",
        "stage": STAGE,
        "play": bool(play),
        "timing": timing,
        "reason": str(reason or ""),
        "legal": bool(legal),
        "window": window,
        "player_id": player_id,
        "tile_id": None,
        "steal_opponent_id": None,
        "robber_plan": None,
        "robber_plan_ok": None,
        "gates": dict(gates or {}),
        "failed_reasons": [],
        "playable_knight_count": int((gates or {}).get("playable_knight_count") or 0),
        "score": None,
        "features": {},
        "rule": None,
        "warnings": [],
        "notes": (
            "Thin pipeline: plan play/hold + shared robber; "
            "execute_ai_play_knight mutates when play=True."
        ),
        "executed": False,
    }
    if extra:
        plan.update(extra)
    return plan


def log_ai_knight_plan(game: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Persist plan on game and append a compact decision-trace row."""
    plan = dict(plan or {})
    window = str(plan.get("window") or "unknown")

    try:
        game.last_ai_knight_plan = plan
    except Exception:
        pass

    try:
        by_window = getattr(game, "last_ai_knight_plan_by_window", None)
        if not isinstance(by_window, dict):
            by_window = {}
        by_window[window] = plan
        game.last_ai_knight_plan_by_window = by_window
    except Exception:
        pass

    if window == "pre_roll":
        try:
            game.last_ai_knight_plan_pre_roll = plan
        except Exception:
            pass
    elif window == "post_roll":
        try:
            game.last_ai_knight_plan_post_roll = plan
        except Exception:
            pass

    trace_row = {
        "kind": "play_knight",
        "stage": plan.get("stage"),
        "window": window,
        "play": bool(plan.get("play")),
        "timing": plan.get("timing"),
        "reason": plan.get("reason"),
        "legal": bool(plan.get("legal")),
        "player_id": plan.get("player_id"),
        "playable_knight_count": plan.get("playable_knight_count"),
        "score": plan.get("score"),
        "rule": plan.get("rule"),
        "tile_id": plan.get("tile_id"),
        "steal_opponent_id": plan.get("steal_opponent_id"),
        "robber_plan_ok": plan.get("robber_plan_ok"),
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
        from core.console import execution_debug_print

        execution_debug_print(
            game,
            "AI Knight plan "
            f"[P{plan.get('player_id')}] window={window} "
            f"legal={plan.get('legal')} play={plan.get('play')} "
            f"timing={plan.get('timing')} reason={plan.get('reason')} "
            f"score={plan.get('score')} rule={plan.get('rule')} "
            f"tile={plan.get('tile_id')} steal={plan.get('steal_opponent_id')}",
        )
    except Exception:
        pass

    return plan


def _preferred_steal_opponent_id(
    game: Any,
    player: Any,
    features: Mapping[str, Any],
    reason: str,
) -> Optional[int]:
    """Soft preferred steal target for the shared robber planner (never required)."""
    # Bias toward highest-VP opponent when denying a race / taking LA.
    if str(reason) not in {
        REASON_DENY_LEADER,
        REASON_LA_CRIT,
        REASON_LA_RACE,
        REASON_META_BLOCKED_PRE,
        REASON_UNBLOCK_SELF,
    }:
        return None
    pid = _safe_player_id(player)
    best_id: Optional[int] = None
    best_vp = -1
    for p in list(getattr(game, "players", []) or []):
        if p is None:
            continue
        oid = _safe_player_id(p)
        if oid is None or oid == pid:
            continue
        vp = _vp(p)
        if vp > best_vp:
            best_vp = vp
            best_id = oid
    return best_id


def attach_shared_robber_plan(
    game: Any,
    player: Any,
    plan: Dict[str, Any],
    *,
    preferred_opponent_id: Optional[int] = None,
    features: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach shared 7-logic robber plan when Knight play is decided.

    Uses ``game.plan_basic_robber_action`` when present, else
    ``core.game_7logic.plan_basic_robber_action``.

    Important: a weak or failed placement **does not** set ``play=False``.
    Knight AI still commits to play; execute path can fall back later.
    """
    plan = dict(plan or {})
    if not bool(plan.get("play")):
        plan["robber_plan"] = None
        plan["robber_plan_ok"] = None
        plan["tile_id"] = None
        plan["steal_opponent_id"] = None
        return plan

    warnings = list(plan.get("warnings") or [])
    features = features if features is not None else (plan.get("features") or {})
    if preferred_opponent_id is None:
        preferred_opponent_id = _preferred_steal_opponent_id(
            game, player, features, str(plan.get("reason") or "")
        )

    robber: Dict[str, Any]
    try:
        planner = getattr(game, "plan_basic_robber_action", None)
        if callable(planner):
            # Game wrapper signature: preferred_opponent_id only (uses current player).
            try:
                robber = planner(preferred_opponent_id=preferred_opponent_id)
            except TypeError:
                robber = planner()
        else:
            from core.game_7logic import plan_basic_robber_action

            robber = plan_basic_robber_action(
                game,
                player,
                preferred_opponent_id=preferred_opponent_id,
            )
        if not isinstance(robber, dict):
            robber = {
                "ok": False,
                "reason": "robber_planner_returned_non_dict",
                "tile_id": None,
                "opponent_id": None,
            }
    except Exception as exc:
        robber = {
            "ok": False,
            "reason": f"robber_planner_error: {exc}",
            "tile_id": None,
            "opponent_id": None,
            "score": 0.0,
            "warnings": [str(exc)],
        }

    tile_id = robber.get("tile_id")
    try:
        tile_id = int(tile_id) if tile_id is not None else None
    except Exception:
        tile_id = None

    steal_id = robber.get("opponent_id")
    if steal_id is None and isinstance(robber.get("selected_opponent"), Mapping):
        steal_id = robber["selected_opponent"].get("opponent_id")
    try:
        steal_id = int(steal_id) if steal_id is not None else None
    except Exception:
        steal_id = None

    plan["robber_plan"] = robber
    plan["robber_plan_ok"] = bool(robber.get("ok"))
    plan["tile_id"] = tile_id
    plan["steal_opponent_id"] = steal_id
    plan["preferred_robber_opponent_id"] = preferred_opponent_id

    if not bool(robber.get("ok")) or tile_id is None:
        warnings.append("play_without_perfect_placement")
        if not bool(robber.get("ok")):
            warnings.append(str(robber.get("reason") or "robber_plan_failed"))
        # Keep play=True — Stage 3 must not block Knight on placement quality.
        plan["play"] = True

    plan["warnings"] = warnings
    return plan


def plan_ai_play_knight(
    game: Any,
    player: Any = None,
    *,
    window: Optional[str] = None,
    log: bool = True,
    features_override: Optional[Mapping[str, Any]] = None,
    skip_robber_plan: bool = False,
) -> Dict[str, Any]:
    """Plan whether the AI should play a Knight (gates + MVP + shared robber).

    Parameters
    ----------
    game :
        Active Game instance.
    player :
        Defaults to ``game.get_current_player()``.
    window :
        ``\"pre_roll\"``, ``\"post_roll\"``, or None to infer from state.
    log :
        When True (default), store plan on the game and append decision trace.
    features_override :
        Optional feature dict for tests / debugging (merged onto collected features).
    skip_robber_plan :
        When True, skip shared robber attach (tests for play/hold only).

    Returns
    -------
    dict
        Always includes ``play``, ``timing``, ``reason``, ``legal``, ``window``.
        When ``play`` is True, also attaches ``tile_id`` / ``steal_opponent_id``
        from the shared robber planner when available (never cancels play).
    """
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    player_id = _safe_player_id(player)
    gate_info = evaluate_ai_knight_gates(game, player, window=window)
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
                "playable_knight_count": int(gate_info.get("playable_knight_count") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
            },
        )
    else:
        features = collect_knight_features(
            game, player, features_override=features_override
        )
        decision = decide_mvp_play_hold(features, resolved)
        play = bool(decision.get("play"))
        reason = str(decision.get("reason") or REASON_HOLD_DEFAULT)
        rule = decision.get("rule")
        post_roll_win_hold: Optional[Dict[str, Any]] = None

        # End game: never spend the one-DCard slot on pre-roll Knight if
        # Mono/YOP/TFR would likely win this turn after the dice.
        if play and resolved == "pre_roll":
            try:
                from core.ai_dcard_timing import should_hold_preroll_knight_for_winning_dcard

                post_roll_win_hold = should_hold_preroll_knight_for_winning_dcard(
                    game, player, features=features
                )
                if bool(post_roll_win_hold.get("hold")):
                    play = False
                    reason = REASON_HOLD_WINNING_POST_ROLL
                    rule = "hold_for_winning_post_roll_dcard"
            except Exception:
                post_roll_win_hold = {"hold": False, "reason": "scan_error"}

        # Lab soft bias: tip legal hold → play when LA timing window is open
        la_soft_meta: Optional[Dict[str, Any]] = None
        try:
            from core.la_soft_bias import apply_la_knight_ba_bias

            biased = apply_la_knight_ba_bias(
                game,
                player,
                {
                    "play": play,
                    "timing": decision.get("timing") if play else None,
                    "reason": reason,
                    "legal": True,
                    "window": resolved,
                    "score": decision.get("score"),
                    "rule": rule,
                },
                features=features,
            )
            la_soft_meta = (
                dict(biased.get("la_soft_bias") or {})
                if isinstance(biased, Mapping)
                else None
            )
            if isinstance(biased, Mapping) and biased.get("la_soft_bias", {}).get(
                "applied"
            ):
                play = bool(biased.get("play"))
                reason = str(biased.get("reason") or reason)
                rule = biased.get("rule") or rule
                if play and biased.get("timing") is not None:
                    decision = dict(decision)
                    decision["timing"] = biased.get("timing")
        except Exception:
            la_soft_meta = None

        plan = _empty_plan(
            play=play,
            timing=decision.get("timing") if play else None,
            reason=reason,
            legal=True,
            window=resolved,
            player_id=player_id,
            gates=gates,
            extra={
                "failed_reasons": [],
                "playable_knight_count": int(gate_info.get("playable_knight_count") or 0),
                "state": gate_info.get("state"),
                "phase": gate_info.get("phase"),
                "available_timing_if_play": decision.get("available_timing_if_play"),
                "score": decision.get("score"),
                "features": features,
                "rule": rule,
                "dice_independent_desire": decision.get("dice_independent_desire"),
                "post_roll_win_hold": post_roll_win_hold,
                "la_soft_bias": la_soft_meta,
                "winning_post_roll_card": (
                    (post_roll_win_hold or {}).get("winning_card")
                    if post_roll_win_hold
                    else None
                ),
            },
        )
        if bool(plan.get("play")) and not skip_robber_plan:
            plan = attach_shared_robber_plan(game, player, plan, features=features)

    if log:
        plan = log_ai_knight_plan(game, plan)
    return plan


def _consume_knight_card(game: Any, player: Any) -> Dict[str, Any]:
    """Remove one playable knight from the player via Game helpers when possible."""
    remover = getattr(game, "_remove_development_card_from_player", None)
    if callable(remover):
        if remover(player, "knight"):
            return {"ok": True, "source": "game_remove"}
        # Summary-only force path (mirrors human executor)
        try:
            idx_fn = getattr(game, "_execution_dcard_summary_index", None)
            idx = int(idx_fn("knight")) if callable(idx_fn) else 1
            row = player.dcard_summary[idx]
            # Only playable column (y); same-turn buys stay in col1 until maturity
            if int(row[2] or 0) <= 0:
                return {"ok": False, "reason": REASON_NO_KNIGHT}
            row[2] = int(row[2]) - 1
            row[3] = int(row[3] or 0) + 1
            # Drop one from hand list if present
            cards = list(getattr(player, "development_cards", []) or [])
            for i, c in enumerate(cards):
                if str(c) == "knight":
                    cards.pop(i)
                    break
            player.development_cards = cards
            player.number_of_dcards = len(cards)
            return {"ok": True, "source": "summary_force"}
        except Exception:
            return {"ok": False, "reason": "could_not_consume_knight"}

    # Minimal fallback for pure unit tests
    cards = list(getattr(player, "development_cards", []) or [])
    for i, c in enumerate(cards):
        if str(c) == "knight":
            cards.pop(i)
            player.development_cards = cards
            try:
                summary = list(getattr(player, "dcard_summary", []) or [])
                for row in summary:
                    if row and str(row[0]) == "knight":
                        while len(row) < 4:
                            row.append(0)
                        if int(row[2] or 0) > 0:
                            row[2] = int(row[2]) - 1
                        row[3] = int(row[3] or 0) + 1
                        break
            except Exception:
                pass
            return {"ok": True, "source": "fallback_list"}
    return {"ok": False, "reason": REASON_NO_KNIGHT}


def _run_shared_robber_execute(
    game: Any,
    player: Any,
    plan: Mapping[str, Any],
) -> Dict[str, Any]:
    """Move robber + optional steal using planned tile or basic strategy fallback."""
    tile_id = plan.get("tile_id")
    steal_id = plan.get("steal_opponent_id")
    if steal_id is None:
        steal_id = plan.get("preferred_robber_opponent_id")
    preferred = steal_id

    warnings: List[str] = []

    # Path A: honor planned tile when present
    if tile_id is not None:
        try:
            from core.game_7logic import move_robber_basic, steal_random_resource_basic

            move = move_robber_basic(
                game,
                player,
                int(tile_id),
                opponent_id=int(steal_id) if steal_id is not None else None,
                plan=dict(plan.get("robber_plan") or {}),
                auto_select_multiple=True,
            )
            steal = None
            sel = move.get("selected_opponent_id") if isinstance(move, Mapping) else None
            if bool(move.get("ok")) and sel is not None:
                try:
                    steal = steal_random_resource_basic(game, player, int(sel))
                except Exception as exc:
                    warnings.append(f"steal_failed: {exc}")
                    steal = {"ok": False, "reason": str(exc)}
            if bool(move.get("ok")):
                return {
                    "ok": True,
                    "source": "planned_tile",
                    "move": move,
                    "steal": steal,
                    "tile_id": int(tile_id),
                    "steal_opponent_id": int(sel) if sel is not None else None,
                    "warnings": warnings,
                }
            warnings.append(str((move or {}).get("reason") or "planned_tile_move_failed"))
        except Exception as exc:
            warnings.append(f"planned_tile_error: {exc}")

    # Path B: shared 7 strategy (re-plan + move + steal)
    try:
        executor = getattr(game, "execute_basic_robber_strategy", None)
        if callable(executor):
            try:
                result = executor(
                    preferred_opponent_id=int(preferred) if preferred is not None else None,
                    execute_steal=True,
                )
            except TypeError:
                result = executor()
        else:
            from core.game_7logic import execute_basic_robber_strategy

            result = execute_basic_robber_strategy(
                game,
                player,
                preferred_opponent_id=int(preferred) if preferred is not None else None,
                execute_steal=True,
            )
        move = (result or {}).get("move") if isinstance(result, Mapping) else None
        steal = (result or {}).get("steal") if isinstance(result, Mapping) else None
        tid = None
        sid = None
        if isinstance(move, Mapping):
            tid = move.get("tile_id")
            sid = move.get("selected_opponent_id")
        if tid is None and isinstance(result, Mapping):
            rplan = result.get("plan") or {}
            if isinstance(rplan, Mapping):
                tid = rplan.get("tile_id")
                sid = rplan.get("opponent_id") if sid is None else sid
        return {
            "ok": bool((result or {}).get("ok")) if isinstance(result, Mapping) else False,
            "source": "basic_robber_strategy",
            "move": move,
            "steal": steal,
            "plan": (result or {}).get("plan") if isinstance(result, Mapping) else None,
            "tile_id": int(tid) if tid is not None else None,
            "steal_opponent_id": int(sid) if sid is not None else None,
            "warnings": warnings,
            "result": result,
        }
    except Exception as exc:
        warnings.append(f"basic_robber_error: {exc}")
        return {
            "ok": False,
            "source": "basic_robber_strategy",
            "move": None,
            "steal": None,
            "tile_id": None,
            "steal_opponent_id": None,
            "warnings": warnings,
            "reason": str(exc),
        }


def _resume_after_ai_knight(game: Any, timing: str, *, reason: str = "") -> Dict[str, Any]:
    """Clear robber/knight pending flags and restore pre- or post-roll state."""
    timing_norm = str(timing or "")
    # Accept both plan timing and human-style labels
    is_pre = timing_norm in ("pre_roll", "before_roll")

    try:
        game.pending_knight_play = {"active": False}
    except Exception:
        pass
    try:
        if isinstance(getattr(game, "pending_seven_roll", None), dict):
            game.pending_seven_roll["active"] = False
        elif not hasattr(game, "pending_seven_roll"):
            game.pending_seven_roll = {"active": False}
    except Exception:
        pass
    try:
        if isinstance(getattr(game, "pending_robber_steal", None), dict):
            game.pending_robber_steal["active"] = False
            game.pending_robber_steal["awaiting_human_target"] = False
    except Exception:
        pass
    try:
        td = getattr(game, "myturn", None)
        if td is not None:
            td.validate_function_set_robber_by_HP = False
    except Exception:
        pass

    if is_pre:
        try:
            game.state = "AwaitingDiceRoll"
            game.state_1 = ""
            game.state_2 = ""
        except Exception:
            pass
        try:
            # Robber tile changed: board (not pure hand) — P1 WP3
            ref = getattr(game, "refresh_strategy_after_event", None)
            if callable(ref):
                ref("after_ai_knight_pre_roll", kind="board")
            else:
                ref2 = getattr(game, "refresh_strategy_context", None)
                if callable(ref2):
                    ref2("after_ai_knight_pre_roll", mode="auto")
        except Exception:
            pass
        try:
            refa = getattr(game, "refresh_viable_actions", None)
            if callable(refa):
                refa("after_ai_knight_pre_roll")
        except Exception:
            pass
        return {
            "ok": True,
            "resume_to": "AwaitingDiceRoll",
            "timing": "pre_roll",
            "reason": reason or "after_ai_knight_pre_roll",
            "only_action": "Roll Dices",
        }

    # Post-roll
    try:
        game.state = "ActionSelection"
        game.state_1 = ""
        game.state_2 = ""
    except Exception:
        pass
    cont = getattr(game, "continue_action_selection_after_action", None)
    if callable(cont):
        try:
            out = cont(
                reason or "after_ai_knight_post_roll",
                player=game.get_current_player() if callable(getattr(game, "get_current_player", None)) else getattr(game, "current_player", None),
                action_result={"action": "Play Knight", "ok": True, "timing": "post_roll"},
                clear_forced_locks=True,
            )
            if isinstance(out, dict):
                out = dict(out)
                out.setdefault("resume_to", "ActionSelection")
                out.setdefault("timing", "post_roll")
                return out
        except Exception:
            pass
    try:
        refa = getattr(game, "refresh_viable_actions", None)
        if callable(refa):
            refa("after_ai_knight_post_roll")
    except Exception:
        pass
    return {
        "ok": True,
        "resume_to": "ActionSelection",
        "timing": "post_roll",
        "reason": reason or "after_ai_knight_post_roll",
    }


def execute_ai_play_knight(
    game: Any,
    player: Any = None,
    *,
    plan: Optional[Mapping[str, Any]] = None,
    window: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Thin execute: consume Knight, LA update, shared robber+steal, resume state.

    Parameters
    ----------
    plan :
        Prefer a plan from ``plan_ai_play_knight``. If omitted, plans now.
    force :
        When True, execute even if plan.play is False (tests / debug only),
        still requiring legal gates.
    """
    if player is None:
        try:
            player = game.get_current_player()
        except Exception:
            player = getattr(game, "current_player", None)

    result: Dict[str, Any] = {
        "ok": False,
        "action": "Play Knight",
        "source": "ai",
        "stage": STAGE,
        "reason": "",
        "player_id": _safe_player_id(player),
        "plan": None,
        "army_info": None,
        "robber_result": None,
        "resume": None,
        "executed": False,
    }

    if plan is None:
        plan = plan_ai_play_knight(game, player, window=window, log=True)
    plan = dict(plan or {})
    result["plan"] = plan

    if not bool(plan.get("legal")) and not force:
        result["reason"] = str(plan.get("reason") or "not_legal")
        return result
    if not bool(plan.get("play")) and not force:
        result["reason"] = str(plan.get("reason") or "plan_hold")
        return result

    # Re-check critical gates at execute time (state may have shifted)
    timing = str(plan.get("timing") or plan.get("window") or window or "")
    if timing in ("pre_roll", "before_roll"):
        gate_window = "pre_roll"
    elif timing in ("post_roll", "after_roll"):
        gate_window = "post_roll"
    else:
        gate_window = _resolve_window(game, window)

    gates = evaluate_ai_knight_gates(game, player, window=gate_window)
    if not gates.get("legal") and not force:
        result["reason"] = str(gates.get("primary_gate_reason") or "not_legal_at_execute")
        result["gates"] = gates.get("gates")
        return result

    # Human safety
    if _is_human_player(game, player):
        result["reason"] = REASON_HUMAN_PLAYER
        return result

    # Consume knight
    ensure = getattr(game, "_ensure_player_dcard_state", None)
    if callable(ensure):
        try:
            ensure(player)
        except Exception:
            pass

    consumed = _consume_knight_card(game, player)
    if not consumed.get("ok"):
        result["reason"] = str(consumed.get("reason") or "could_not_consume_knight")
        return result

    mark = getattr(game, "_mark_dcard_played_this_turn", None)
    if callable(mark):
        try:
            mark("knight", player)
        except TypeError:
            try:
                mark("knight")
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

    army_info: Dict[str, Any] = {}
    la = getattr(game, "_update_largest_army_after_knight", None)
    if callable(la):
        try:
            army_info = dict(la(player) or {})
        except Exception as exc:
            army_info = {"error": str(exc)}
    else:
        try:
            player.size_largest_army = int(getattr(player, "size_largest_army", 0) or 0) + 1
            army_info = {"army_size": int(player.size_largest_army)}
        except Exception:
            army_info = {}
    result["army_info"] = army_info

    try:
        emit = getattr(game, "emit_twitter_event", None)
        if callable(emit):
            emit(_safe_player_id(player), f"AI plays Knight ({gate_window})")
    except Exception:
        pass
    try:
        rec = getattr(game, "record_turn_event", None)
        if callable(rec):
            rec(
                player=player,
                event_type="play_dcard",
                source="ai_play_knight",
                message=f"AI plays Knight ({gate_window})",
                metadata={
                    "card": "knight",
                    "timing": gate_window,
                    "army_size": army_info.get("army_size"),
                    "plan_reason": plan.get("reason"),
                },
            )
    except Exception:
        pass
    try:
        from core import mglog

        mglog.log_play_dcard(
            game,
            player,
            "knight",
            payload=f"timing={gate_window}",
        )
    except Exception:
        pass

    # W2: LA award can end the game; skip robber/resume pipeline if so.
    if bool(getattr(game, "game_over", False)):
        result["ok"] = True
        result["executed"] = True
        result["timing"] = gate_window
        result["reason"] = "executed_and_won"
        result["game_over"] = True
        result["robber_skipped"] = True
        result["win_check"] = army_info.get("win_check") if isinstance(army_info, dict) else None
        result["robber_result"] = {"ok": False, "reason": "game_over", "skipped": True}
        result["resume"] = {"ok": False, "reason": "game_over", "skipped": True}
        try:
            game.last_ai_knight_execute_result = result
        except Exception:
            pass
        return result

    # Robber + steal (shared path); never abort the knight over weak placement
    robber_result = _run_shared_robber_execute(game, player, plan)
    result["robber_result"] = robber_result

    resume = _resume_after_ai_knight(
        game,
        gate_window,
        reason="after_ai_play_knight",
    )
    result["resume"] = resume
    result["ok"] = True
    result["executed"] = True
    result["timing"] = gate_window
    result["reason"] = str(plan.get("reason") or "executed")
    result["tile_id"] = robber_result.get("tile_id")
    result["steal_opponent_id"] = robber_result.get("steal_opponent_id")
    if not bool(robber_result.get("ok")):
        result["robber_warning"] = "play_without_perfect_placement"
        result.setdefault("warnings", [])
        if isinstance(result["warnings"], list):
            result["warnings"].extend(list(robber_result.get("warnings") or []))
            result["warnings"].append("play_without_perfect_placement")

    try:
        game.last_ai_knight_execute_result = result
    except Exception:
        pass
    try:
        if isinstance(plan, dict):
            plan["executed"] = True
            plan["execute_result"] = {
                "ok": True,
                "timing": gate_window,
                "tile_id": result.get("tile_id"),
                "steal_opponent_id": result.get("steal_opponent_id"),
            }
            game.last_ai_knight_plan = plan
    except Exception:
        pass

    try:
        from core.console import execution_debug_print

        execution_debug_print(
            game,
            "AI Knight EXECUTE "
            f"[P{result.get('player_id')}] timing={gate_window} "
            f"reason={result.get('reason')} tile={result.get('tile_id')} "
            f"steal={result.get('steal_opponent_id')} "
            f"robber_ok={bool(robber_result.get('ok'))}",
        )
    except Exception:
        pass

    try:
        refresh = getattr(game, "_refresh_gui_scoreboard_after_dcard_change", None)
        if callable(refresh):
            refresh("after_ai_play_knight")
    except Exception:
        pass

    return result


def maybe_execute_ai_knight_for_window(
    game: Any,
    window: str,
    *,
    features_override: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan for ``window``; if play+matching timing, execute thin and return result.

    Used by AI turn hooks. Always returns a dict with ``planned`` and optional
    ``executed_result``.
    """
    plan = plan_ai_play_knight(
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
    if not bool(plan.get("play")):
        return out
    timing = str(plan.get("timing") or "")
    if timing != str(window):
        # Safety: only auto-execute when plan commits to this window
        return out
    executed = execute_ai_play_knight(game, plan=plan, window=window)
    out["executed"] = bool(executed.get("executed"))
    out["executed_result"] = executed
    return out


__all__ = [
    "STAGE",
    "REASON_SKELETON_HOLD",
    "REASON_LA_CRIT",
    "REASON_META_BLOCKED_PRE",
    "REASON_HOLD_FOR_SEVEN",
    "REASON_HOLD_DETENTION",
    "REASON_HOLD_LA_DELAY",
    "REASON_HOLD_LOW_HEX",
    "REASON_HOLD_WINNING_POST_ROLL",
    "REASON_UNBLOCK_SELF",
    "playable_knight_count",
    "evaluate_ai_knight_gates",
    "collect_knight_features",
    "dice_independent_play_desire",
    "decide_mvp_play_hold",
    "attach_shared_robber_plan",
    "plan_ai_play_knight",
    "log_ai_knight_plan",
    "execute_ai_play_knight",
    "maybe_execute_ai_knight_for_window",
]
