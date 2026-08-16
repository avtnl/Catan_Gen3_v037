"""core/phase0_baseline_hooks.py

Optional Phase 0 baseline capture hooks for F9 / F8 regression testing.

Installs on Game:
    game.save_phase0_baseline(...)
    game.maybe_save_phase0_baseline(...)

Captures current-player-focused strategy context plus a snapshot of all
players' strategic_direction so AI situations are discussable.

PR-Ph0: sticky, roads/LA-LR flags, dcard playable counts, DCard plans by
window, TwP skip / incoming offer keys, perf traces.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


def json_default(obj: Any) -> Any:
    """JSON serializer for WayBoardAudit and other custom objects."""
    if hasattr(obj, "as_dict") and callable(getattr(obj, "as_dict")):
        try:
            return obj.as_dict()
        except Exception:
            pass
    if isinstance(obj, set):
        try:
            return sorted(obj)
        except TypeError:
            return [json_default(x) for x in obj]
    if isinstance(obj, tuple):
        return [json_default(x) for x in obj]
    if hasattr(obj, "__dict__"):
        try:
            return {
                k: v
                for k, v in vars(obj).items()
                if not str(k).startswith("_") and not callable(v)
            }
        except Exception:
            pass
    return str(obj)


def _jsonable(value: Any) -> Any:
    """Best-effort deep convert for Phase0 JSON (sets/tuples/mappings)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            try:
                key = str(k) if not isinstance(k, (str, int, float, bool)) else k
            except Exception:
                key = str(k)
            out[str(key)] = _jsonable(v)
        return out
    if isinstance(value, set):
        try:
            return [_jsonable(x) for x in sorted(value)]
        except TypeError:
            return [_jsonable(x) for x in value]
    if isinstance(value, (list, tuple)):
        return [_jsonable(x) for x in value]
    if hasattr(value, "as_dict") and callable(value.as_dict):
        try:
            return _jsonable(value.as_dict())
        except Exception:
            pass
    try:
        # Keep small primitives only; stringify complex objects
        if type(value).__name__ in {"SimpleNamespace"} or hasattr(value, "__dict__"):
            return str(value)
    except Exception:
        pass
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _road_key(raw: Any) -> Optional[List[int]]:
    try:
        if isinstance(raw, Mapping):
            for k in ("road_id", "road", "edge", "target_road"):
                if k in raw:
                    return _road_key(raw.get(k))
            return None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            a, b = int(raw[0]), int(raw[1])
            if a == b:
                return None
            return [a, b] if a < b else [b, a]
    except Exception:
        return None
    return None


def _roads_list(player: Any) -> List[List[int]]:
    out: List[List[int]] = []
    seen = set()
    for raw in list(getattr(player, "roads", None) or []):
        key = _road_key(raw)
        if key is None:
            continue
        t = (key[0], key[1])
        if t in seen:
            continue
        seen.add(t)
        out.append(key)
    return out


def _sticky_commitment_snapshot(player: Any) -> Optional[Dict[str, Any]]:
    sticky = getattr(player, "sticky_commitment", None)
    if not isinstance(sticky, Mapping):
        return None
    return _jsonable(dict(sticky))


def _dcard_snapshot(player: Any) -> Dict[str, Any]:
    """dcard_summary + playable counts (x/y/z style)."""
    summary_rows: List[Any] = []
    try:
        for row in list(getattr(player, "dcard_summary", None) or []):
            summary_rows.append(list(row) if not isinstance(row, list) else list(row))
    except Exception:
        summary_rows = []

    playable: Dict[str, int] = {}
    new_counts: Dict[str, int] = {}
    revealed: Dict[str, int] = {}
    for row in summary_rows:
        try:
            name = str(row[0])
            while len(row) < 4:
                row.append(0)
            new_counts[name] = max(0, int(row[1] or 0))
            playable[name] = max(0, int(row[2] or 0))
            revealed[name] = max(0, int(row[3] or 0))
        except Exception:
            continue

    hand_cards: List[str] = []
    try:
        hand_cards = [str(c) for c in list(getattr(player, "development_cards", None) or [])]
    except Exception:
        hand_cards = []

    # Fallback playable from hand when summary empty
    if not playable and hand_cards:
        for c in hand_cards:
            playable[c] = playable.get(c, 0) + 1

    return {
        "dcard_summary": summary_rows,
        "playable_counts": playable,
        "new_counts": new_counts,
        "revealed_or_played_counts": revealed,
        "development_cards_hand": hand_cards,
        "playable_total": int(sum(playable.values())),
    }


def _specials_snapshot(player: Any) -> Dict[str, Any]:
    return {
        "size_longest_route": int(getattr(player, "size_longest_route", 0) or 0),
        "longest_route_tf": bool(
            getattr(player, "longest_route_tf", False)
            or getattr(player, "longest_road_tf", False)
        ),
        "size_largest_army": int(getattr(player, "size_largest_army", 0) or 0),
        "largest_army_tf": bool(
            getattr(player, "largest_army_tf", False)
            or getattr(player, "biggest_army_tf", False)
        ),
    }


def _safe_player_snapshot(player: Any) -> Dict[str, Any]:
    if player is None:
        return {}
    direction = getattr(player, "strategic_direction", None)
    if hasattr(direction, "as_dict") and callable(direction.as_dict):
        try:
            direction = direction.as_dict()
        except Exception:
            direction = dict(direction) if isinstance(direction, Mapping) else str(direction)
    elif isinstance(direction, Mapping):
        direction = dict(direction)
    else:
        direction = direction if direction in (None, "") else str(direction)

    hand = None
    try:
        info = player.rcards_in_hand()
        if isinstance(info, (list, tuple)) and info and isinstance(info[0], (list, tuple)):
            hand = [int(x or 0) for x in list(info[0])[:5]]
    except Exception:
        hand = None
    if hand is None:
        try:
            rcards = getattr(player, "rcards", {}) or {}
            if isinstance(rcards, Mapping):
                order = ["Wheat", "Ore", "Wood", "Brick", "Sheep"]
                hand = []
                for name in order:
                    val = 0
                    for k, v in rcards.items():
                        kn = getattr(k, "value", k)
                        if str(kn) == name:
                            val = int(v or 0)
                            break
                    hand.append(val)
        except Exception:
            hand = None

    roads = _roads_list(player)
    specials = _specials_snapshot(player)
    dcards = _dcard_snapshot(player)
    sticky = _sticky_commitment_snapshot(player)
    lr_project = None
    try:
        if isinstance(sticky, Mapping) and isinstance(sticky.get("lr_project"), Mapping):
            lr_project = dict(sticky.get("lr_project") or {})
        elif isinstance(getattr(player, "lr_project", None), Mapping):
            lr_project = dict(getattr(player, "lr_project") or {})
    except Exception:
        lr_project = None

    snap: Dict[str, Any] = {
        "player_id": getattr(player, "id", None),
        "color": getattr(player, "color", None),
        "is_human": bool(getattr(player, "is_human", False)),
        "victory_points": getattr(player, "victory_points", getattr(player, "points", None)),
        "hand": hand,
        "settlements": list(getattr(player, "settlements", []) or []),
        "cities": list(getattr(player, "cities", []) or []),
        "roads": roads,
        "roads_count": len(roads),
        "size_longest_route": specials["size_longest_route"],
        "longest_route_tf": specials["longest_route_tf"],
        "size_largest_army": specials["size_largest_army"],
        "largest_army_tf": specials["largest_army_tf"],
        "specials": specials,
        "sticky_commitment": sticky,
        "lr_project": lr_project,
        "dcard_summary": dcards["dcard_summary"],
        "dcard_playable_counts": dcards["playable_counts"],
        "dcard_new_counts": dcards["new_counts"],
        "dcard_revealed_or_played_counts": dcards["revealed_or_played_counts"],
        "development_cards_hand": dcards["development_cards_hand"],
        "dcard_playable_total": dcards["playable_total"],
        "strategic_direction": direction,
        "last_strategic_direction": (
            dict(getattr(player, "last_strategic_direction"))
            if isinstance(getattr(player, "last_strategic_direction", None), Mapping)
            else None
        ),
        "strategy_recalc_flag": getattr(player, "strategy_recalc_flag", None),
        "force_strategy_recalc": bool(getattr(player, "force_strategy_recalc", False)),
        # S5.5-C cadence + dig-in
        "specials_divert_checked_turn": getattr(
            player, "specials_divert_checked_turn", None
        ),
        "last_specials_divert": (
            dict(getattr(player, "last_specials_divert"))
            if isinstance(getattr(player, "last_specials_divert", None), Mapping)
            else getattr(player, "last_specials_divert", None)
        ),
        "last_specials_assess": (
            dict(getattr(player, "last_specials_assess"))
            if isinstance(getattr(player, "last_specials_assess", None), Mapping)
            else getattr(player, "last_specials_assess", None)
        ),
    }
    return snap


def _collect_dcard_plans(game: Any) -> Dict[str, Any]:
    """Knight / TFR / YOP / Monopoly plans (latest + by window)."""
    def _g(name: str) -> Any:
        return _jsonable(getattr(game, name, None))

    return {
        "last_ai_dcard_choice": _g("last_ai_dcard_choice"),
        "knight": {
            "last": _g("last_ai_knight_plan"),
            "pre_roll": _g("last_ai_knight_plan_pre_roll"),
            "post_roll": _g("last_ai_knight_plan_post_roll"),
            "by_window": _g("last_ai_knight_plan_by_window") or {},
            "execute_result": _g("last_ai_knight_execute_result"),
        },
        "tfr": {
            "last": _g("last_ai_tfr_plan"),
            "pre_roll": _g("last_ai_tfr_plan_pre_roll"),
            "post_roll": _g("last_ai_tfr_plan_post_roll"),
            "by_window": _g("last_ai_tfr_plan_by_window") or {},
            "execute_result": _g("last_ai_tfr_execute_result"),
        },
        "yop": {
            "last": _g("last_ai_yop_plan"),
            "pre_roll": _g("last_ai_yop_plan_pre_roll"),
            "post_roll": _g("last_ai_yop_plan_post_roll"),
            "by_window": _g("last_ai_yop_plan_by_window") or {},
            "execute_result": _g("last_ai_yop_execute_result"),
        },
        "monopoly": {
            "last": _g("last_ai_monopoly_plan"),
            "pre_roll": _g("last_ai_monopoly_plan_pre_roll"),
            "post_roll": _g("last_ai_monopoly_plan_post_roll"),
            "by_window": _g("last_ai_monopoly_plan_by_window") or {},
            "execute_result": _g("last_ai_monopoly_execute_result"),
        },
        # Flat aliases for dig-in / older greps
        "last_ai_knight_plan": _g("last_ai_knight_plan"),
        "last_ai_tfr_plan": _g("last_ai_tfr_plan"),
        "last_ai_yop_plan": _g("last_ai_yop_plan"),
        "last_ai_monopoly_plan": _g("last_ai_monopoly_plan"),
        "last_ai_knight_plan_by_window": _g("last_ai_knight_plan_by_window") or {},
        "last_ai_tfr_plan_by_window": _g("last_ai_tfr_plan_by_window") or {},
        "last_ai_yop_plan_by_window": _g("last_ai_yop_plan_by_window") or {},
        "last_ai_monopoly_plan_by_window": _g("last_ai_monopoly_plan_by_window") or {},
    }


def _offer_key_from_proposal(proposal: Any) -> Any:
    if not isinstance(proposal, Mapping):
        return None
    if proposal.get("proposal_key") is not None:
        return _jsonable(proposal.get("proposal_key"))
    try:
        return _jsonable(
            (
                int(proposal.get("active_player_id", 0) or 0),
                int(proposal.get("counterparty_id", 0) or 0),
                int(proposal.get("active_give_index", 0) or 0),
                int(proposal.get("active_give_count", 0) or 0),
                int(proposal.get("active_receive_index", 0) or 0),
                int(proposal.get("active_receive_count", 0) or 0),
            )
        )
    except Exception:
        return None


def _collect_twp_snapshot(game: Any) -> Dict[str, Any]:
    """TwP skip reasons, pending/binding offers, decline keys."""
    pending = getattr(game, "pending_human_twp_offer", None)
    pending_dict = dict(pending) if isinstance(pending, Mapping) else pending
    pending_key = None
    if isinstance(pending_dict, Mapping):
        pending_key = pending_dict.get("proposal_key")
        if pending_key is None:
            prop = pending_dict.get("proposal")
            pending_key = _offer_key_from_proposal(prop if isinstance(prop, Mapping) else pending_dict)

    binding = getattr(game, "accepted_binding_proposal", None)
    binding_key = _offer_key_from_proposal(binding)

    policy = getattr(game, "last_human_twp_policy_decision", None)
    policy_key = None
    if isinstance(policy, Mapping):
        policy_key = policy.get("proposal_key") or _offer_key_from_proposal(policy.get("proposal") or policy)

    # T10 counter dig-in
    counter = getattr(game, "pending_twp_counter", None)
    counter_d = dict(counter) if isinstance(counter, Mapping) else None
    last_ctr = getattr(game, "last_twp_counter_result", None)
    try:
        from core.human_twp_policy import build_twp_debug_snapshot

        twp_debug = build_twp_debug_snapshot(game)
    except Exception:
        twp_debug = getattr(game, "last_twp_debug", None)

    return {
        "last_twp_skip_reasons": _jsonable(
            list(getattr(game, "last_twp_skip_reasons", None) or [])
        ),
        "last_twp_debug": _jsonable(twp_debug),
        # T1-A package quality dig-in
        "last_twp_package_rank": _jsonable(
            getattr(game, "last_twp_package_rank", None)
        ),
        "last_human_twp_policy_decision": _jsonable(policy),
        "last_human_twp_response_result": _jsonable(
            getattr(game, "last_human_twp_response_result", None)
        ),
        "pending_human_twp_offer": _jsonable(pending_dict),
        "last_incoming_offer_key": _jsonable(pending_key or policy_key),
        "accepted_binding_proposal": _jsonable(binding),
        "accepted_binding_offer_key": _jsonable(binding_key),
        "human_twp_declined_this_turn": _jsonable(
            getattr(game, "human_twp_declined_this_turn", None) or []
        ),
        "human_twp_accepted_this_turn": _jsonable(
            getattr(game, "human_twp_accepted_this_turn", None) or []
        ),
        "human_twp_mode": getattr(game, "human_twp_mode", None),
        "human_twp_auto_rules": _jsonable(
            list(getattr(game, "human_twp_auto_rules", None) or [])
        ),
        # T10-C
        "pending_twp_counter": _jsonable(counter_d),
        "last_twp_counter_result": _jsonable(last_ctr),
        "twp_counter_active": bool(
            isinstance(counter_d, Mapping) and counter_d.get("active")
        ),
        # S5.5-A/B/C specials assess + divert dig-in
        "last_specials_assess": _jsonable(
            getattr(game, "last_specials_assess", None)
        ),
        "last_specials_divert": _jsonable(
            getattr(game, "last_specials_divert", None)
        ),
        # H-B: HP→AI offer scan (outgoing) — distinct from Incoming AI→HP fields
        "last_human_twp_offer_scan": _jsonable(
            getattr(game, "last_human_twp_offer_scan", None)
        ),
        "last_human_twp_offer_grant": _jsonable(
            getattr(game, "last_human_twp_offer_grant", None)
        ),
        "human_twp_offer_scan_history_tail": _jsonable(
            list(getattr(game, "human_twp_offer_scan_history", None) or [])[-3:]
        ),
    }


def _collect_players_snapshot(game: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in list(getattr(game, "players", []) or []):
        try:
            out.append(_safe_player_snapshot(p))
        except Exception as exc:
            out.append({"error": str(exc), "player_id": getattr(p, "id", None)})
    return out


def _serialize_audit(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "as_dict") and callable(value.as_dict):
        try:
            return value.as_dict()
        except Exception:
            pass
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return [_serialize_audit(v) for v in value]
    return str(value)


def save_phase0_baseline(
    game: Any,
    label: str = "",
    reason: str = "manual",
    expected_future: Optional[Dict[str, Any]] = None,
    refresh_before_capture: bool = True,
    force_refresh: bool = True,
) -> Dict[str, Any]:
    """Save a Phase 0 baseline for the current game situation.

    Focus player = current turn player. Also stores all players' strategy
    snapshots so AI-vs-AI moments remain inspectable.

    P2-A: holds ``phase0_save_busy`` for the whole capture (refresh + JSON write)
    so Play/Continue stay disabled.
    """
    try:
        from core.performance_trace import phase0_save_busy_scope
    except Exception:
        from contextlib import nullcontext

        phase0_save_busy_scope = lambda _g, reason="": nullcontext()  # type: ignore

    with phase0_save_busy_scope(game, reason=f"phase0_{reason or 'save'}"):
        return _save_phase0_baseline_body(
            game,
            label=label,
            reason=reason,
            expected_future=expected_future,
            refresh_before_capture=refresh_before_capture,
            force_refresh=force_refresh,
        )


def _save_phase0_baseline_body(
    game: Any,
    label: str = "",
    reason: str = "manual",
    expected_future: Optional[Dict[str, Any]] = None,
    refresh_before_capture: bool = True,
    force_refresh: bool = True,
) -> Dict[str, Any]:
    """Inner Phase0 capture (caller holds phase0_save_busy)."""
    refresh_status: Dict[str, Any] = {"attempted": bool(refresh_before_capture)}
    if refresh_before_capture:
        # Always allow planner during Phase0 even in MoveRobber / discard / pre-dice.
        # This is diagnostic-only; normal turn logic still skips those states.
        try:
            refresh_status["result"] = game.refresh_strategy_context(
                "phase0_baseline",
                force=bool(force_refresh),
                allow_during_forced_flow=True,
            )
        except TypeError:
            # Older Game signature without force=/allow_during_forced_flow=
            try:
                refresh_status["result"] = game.refresh_strategy_context(
                    "phase0_baseline",
                    force=bool(force_refresh),
                )
            except TypeError:
                try:
                    refresh_status["result"] = game.refresh_strategy_context("phase0_baseline")
                except Exception as exc:
                    refresh_status["error"] = str(exc)
            except Exception as exc:
                refresh_status["error"] = str(exc)
        except Exception as exc:
            refresh_status["error"] = str(exc)

    current_player = None
    try:
        current_player = game.get_current_player()
    except Exception:
        current_player = None

    current_player_id = getattr(current_player, "id", None) if current_player is not None else None
    current_player_color = getattr(current_player, "color", None) if current_player is not None else None

    # Preferred strategy block for current player from last report, if present
    preferred_from_report = None
    report = getattr(game, "last_action_timing_report", None)
    if isinstance(report, Mapping) and current_player_id is not None:
        by_player = report.get("by_player", {}) or {}
        block = by_player.get(str(current_player_id)) or by_player.get(current_player_id)
        if isinstance(block, Mapping):
            preferred_from_report = {
                "preferred_strategy": block.get("preferred_strategy"),
                "baseline_top_strategies": block.get("baseline_top_strategies"),
                "board_preferred_strategy": block.get("board_preferred_strategy"),
                "abstract_preferred_strategy": block.get("abstract_preferred_strategy"),
            }

    baseline: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "label": label or "unnamed",
        "reason": reason,
        "round": getattr(game, "round", None),
        "turn": getattr(game, "turn", None),
        "phase": getattr(game, "phase", None),
        "state": getattr(game, "state", None),
        "dice_roll": getattr(game, "dice_roll", None),
        "focus_player_id": current_player_id,
        "focus_player_color": current_player_color,
        "current_player_id": current_player_id,
        "focus_player": _safe_player_snapshot(current_player),
        "players": _collect_players_snapshot(game),
        "last_strategy_context_status": getattr(game, "last_strategy_context_status", None),
        "last_strategy_context_reason": getattr(game, "last_strategy_context_reason", None),
        "last_strategy_context_error": getattr(game, "last_strategy_context_error", None),
        "refresh_before_capture": refresh_status,
        "last_action_timing_report": report,
        "preferred_from_report": preferred_from_report,
        "current_board_way_audit": _serialize_audit(getattr(game, "current_board_way_audit", None)),
        "current_board_way_audits": _serialize_audit(getattr(game, "current_board_way_audits", None)),
        "board_rank_order": getattr(game, "last_action_timing_report", {}) and (
            (getattr(game, "last_action_timing_report", {}) or {}).get("board_rank_order")
            if isinstance(getattr(game, "last_action_timing_report", None), Mapping)
            else None
        ),
        "board_way_override": (
            (getattr(game, "last_action_timing_report", {}) or {}).get("board_way_override")
            if isinstance(getattr(game, "last_action_timing_report", None), Mapping)
            else None
        ),
        "pending_seven_roll": getattr(game, "pending_seven_roll", None),
        "pending_discard_queue": getattr(game, "pending_discard_queue", None),
        "execution_debug_active_tab": getattr(game, "execution_debug_active_tab", None),
        "expected_future_behavior": expected_future or {},
        "current_best_action": getattr(game, "current_best_action", None),
        "current_hand_risk_profile": getattr(game, "current_hand_risk_profile", None),
        # P0-R7: one-line support + trade choice trail
        "last_support_trade_debug": getattr(game, "last_support_trade_debug", None),
        "current_ai_execution_plan": getattr(game, "current_ai_execution_plan", None),
        "last_risk_twb_skip": getattr(game, "last_risk_twb_skip", None),
        # T1-A
        "last_twp_package_rank": getattr(game, "last_twp_package_rank", None),
        # P-pack (P3): wall-clock spans + Continue busy gate
        "ai_pipeline_busy": bool(getattr(game, "ai_pipeline_busy", False)),
        "ai_pipeline_busy_reason": str(getattr(game, "ai_pipeline_busy_reason", "") or ""),
        "last_perf_trace": list(getattr(game, "last_perf_trace", None) or []),
        "perf_history_tail": list(getattr(game, "perf_history", None) or [])[-40:],
        "perf_snapshot": None,
        # S-LR-A/B/E/C
        "last_lr_project": getattr(game, "last_lr_project", None),
        "lr_turn_suggestions": list(getattr(game, "last_lr_turn_suggestions", None) or []),
        # S-LA-A
        "last_la_progress": getattr(game, "last_la_progress", None),
        "la_progress": None,
        # S5.5-A/B/C
        "last_specials_assess": getattr(game, "last_specials_assess", None),
        "last_specials_divert": getattr(game, "last_specials_divert", None),
        "specials_divert_checked_turn": None,
        # 30-S: sticky thrash + city probe dig-in
        "last_sticky_switch": getattr(game, "last_sticky_switch", None),
        "sticky_probe_city": getattr(game, "last_sticky_probe_city", None)
        or getattr(game, "sticky_probe_city", None),
        # 30-T / T11: live_need TwP dig-in
        "last_twp_live_need": getattr(game, "last_twp_live_need", None),
        "last_twp_support_action": getattr(game, "last_twp_support_action", None),
        "last_twp_empty_diagnosis": getattr(game, "last_twp_empty_diagnosis", None),
        "last_twp_executed_events_line": getattr(
            game, "last_twp_executed_events_line", None
        ),
        # PR-Ph0: DCard plans + TwP dig-in (also expanded focus_player sticky/roads/LA)
        "dcard_plans": {},
        "twp": {},
    }

    # Prefer focus-player sticky switch / city probe when present
    try:
        if current_player is not None:
            sw = getattr(current_player, "last_sticky_switch", None)
            if sw:
                baseline["last_sticky_switch"] = sw
            probe = getattr(current_player, "last_sticky_probe_city", None) or getattr(
                current_player, "sticky_probe_city", None
            )
            if probe:
                baseline["sticky_probe_city"] = probe
    except Exception:
        pass

    # PR-Ph0: DCard planner dump (knight/TFR/YOP/mono by window)
    try:
        baseline["dcard_plans"] = _collect_dcard_plans(game)
        # Flat keys for grepping playtest notes
        for flat_key in (
            "last_ai_knight_plan",
            "last_ai_tfr_plan",
            "last_ai_yop_plan",
            "last_ai_monopoly_plan",
            "last_ai_dcard_choice",
            "last_ai_knight_plan_by_window",
            "last_ai_tfr_plan_by_window",
            "last_ai_yop_plan_by_window",
            "last_ai_monopoly_plan_by_window",
        ):
            if flat_key in baseline["dcard_plans"]:
                baseline[flat_key] = baseline["dcard_plans"][flat_key]
            elif flat_key == "last_ai_dcard_choice":
                baseline[flat_key] = baseline["dcard_plans"].get("last_ai_dcard_choice")
    except Exception as exc:
        baseline["dcard_plans_error"] = str(exc)

    # PR-Ph0: TwP skip + incoming offer keys
    try:
        twp_block = _collect_twp_snapshot(game)
        baseline["twp"] = twp_block
        # Flat aliases (keep prior T4 field names)
        baseline["human_twp_mode"] = twp_block.get("human_twp_mode")
        baseline["human_twp_auto_rules"] = twp_block.get("human_twp_auto_rules") or []
        baseline["last_human_twp_policy_decision"] = twp_block.get(
            "last_human_twp_policy_decision"
        )
        baseline["last_twp_skip_reasons"] = twp_block.get("last_twp_skip_reasons") or []
        baseline["last_twp_debug"] = twp_block.get("last_twp_debug")
        baseline["last_incoming_offer_key"] = twp_block.get("last_incoming_offer_key")
        baseline["pending_human_twp_offer"] = twp_block.get("pending_human_twp_offer")
        baseline["accepted_binding_proposal"] = twp_block.get("accepted_binding_proposal")
        baseline["accepted_binding_offer_key"] = twp_block.get("accepted_binding_offer_key")
        baseline["human_twp_declined_this_turn"] = twp_block.get(
            "human_twp_declined_this_turn"
        )
        baseline["last_human_twp_response_result"] = twp_block.get(
            "last_human_twp_response_result"
        )
        baseline["pending_twp_counter"] = twp_block.get("pending_twp_counter")
        baseline["last_twp_counter_result"] = twp_block.get("last_twp_counter_result")
        baseline["twp_counter_active"] = bool(twp_block.get("twp_counter_active"))
        # H-B flat aliases for HP→AI offer audit
        baseline["last_human_twp_offer_scan"] = twp_block.get(
            "last_human_twp_offer_scan"
        )
        baseline["last_human_twp_offer_grant"] = twp_block.get(
            "last_human_twp_offer_grant"
        )
        baseline["human_twp_offer_scan_history_tail"] = twp_block.get(
            "human_twp_offer_scan_history_tail"
        ) or []
    except Exception as exc:
        baseline["twp_error"] = str(exc)
        baseline["human_twp_mode"] = getattr(game, "human_twp_mode", None)
        baseline["human_twp_auto_rules"] = list(
            getattr(game, "human_twp_auto_rules", None) or []
        )
        baseline["last_human_twp_policy_decision"] = getattr(
            game, "last_human_twp_policy_decision", None
        )
        baseline["last_twp_skip_reasons"] = list(
            getattr(game, "last_twp_skip_reasons", None) or []
        )
        baseline["last_twp_debug"] = getattr(game, "last_twp_debug", None)
        baseline["pending_twp_counter"] = getattr(game, "pending_twp_counter", None)
        baseline["last_twp_counter_result"] = getattr(game, "last_twp_counter_result", None)
        baseline["last_human_twp_offer_scan"] = getattr(
            game, "last_human_twp_offer_scan", None
        )
        baseline["last_human_twp_offer_grant"] = getattr(
            game, "last_human_twp_offer_grant", None
        )
        baseline["human_twp_offer_scan_history_tail"] = list(
            getattr(game, "human_twp_offer_scan_history", None) or []
        )[-3:]
    try:
        from core.performance_trace import snapshot_perf_for_phase0

        baseline["perf_snapshot"] = snapshot_perf_for_phase0(game)
        # Keep flat keys in sync with snapshot summary
        if isinstance(baseline["perf_snapshot"], dict):
            baseline["perf_summary"] = baseline["perf_snapshot"].get("perf_summary")
    except Exception as exc:
        baseline["perf_snapshot_error"] = str(exc)
    # Refresh LR suggestions for capture if project present
    try:
        from core.ai_lr_project import (
            build_lr_turn_suggestions,
            get_stored_lr_project,
            pick_turn_focus,
        )

        cur = current_player
        if cur is not None:
            focus_info = pick_turn_focus(game, cur)
            focus = focus_info.get("focus")
            baseline["turn_focus"] = focus
            baseline["turn_focus_reason"] = focus_info.get("reason")
            baseline["dense_pack"] = bool(focus_info.get("dense_pack"))
            baseline["la_race"] = bool(focus_info.get("la_race"))
            baseline["lr_race"] = bool(focus_info.get("lr_race"))
            baseline["defer_optional_claim"] = bool(focus_info.get("defer_optional_claim"))
            caution = focus_info.get("caution") if isinstance(focus_info.get("caution"), dict) else {}
            if caution:
                baseline["slr_c_caution"] = {
                    "dense_pack": caution.get("dense_pack"),
                    "la_race": caution.get("la_race"),
                    "lr_race": caution.get("lr_race"),
                    "optional_claim": caution.get("optional_claim"),
                    "defer_lr_grow_for_la": caution.get("defer_lr_grow_for_la"),
                    "vp_pack": caution.get("vp_pack"),
                    "la": caution.get("la"),
                    "lr": {
                        k: caution.get("lr", {}).get(k)
                        for k in (
                            "own_length",
                            "max_opp_length",
                            "we_hold_lr",
                            "claim_after_n",
                            "lr_race",
                        )
                    }
                    if isinstance(caution.get("lr"), dict)
                    else caution.get("lr"),
                }
            if get_stored_lr_project(cur, game):
                baseline["lr_turn_suggestions"] = build_lr_turn_suggestions(
                    game, cur, focus=str(focus) if focus else None
                )
                baseline["lr_project"] = get_stored_lr_project(cur, game)
            try:
                from core.ai_la_progress import (
                    build_la_turn_suggestions,
                    ensure_la_progress_sticky,
                    get_stored_la_progress,
                )

                ensure_la_progress_sticky(game, cur)
                la_prog = get_stored_la_progress(cur, game)
                if la_prog:
                    baseline["la_progress"] = la_prog
                    baseline["last_la_progress"] = la_prog
                    baseline["la_turn_suggestions"] = build_la_turn_suggestions(
                        game, cur, progress=la_prog, focus=str(focus) if focus else None
                    )
            except Exception as la_exc:
                baseline["la_progress_error"] = str(la_exc)
            # S5.5-A refresh assess for capture; C cadence latch dig-in
            try:
                from core.strategy_specials_divert import assess_specials_for_player

                baseline["last_specials_assess"] = assess_specials_for_player(
                    game, cur, store=True
                )
            except Exception as s55_exc:
                baseline["specials_assess_error"] = str(s55_exc)
            try:
                baseline["specials_divert_checked_turn"] = getattr(
                    cur, "specials_divert_checked_turn", None
                )
                if baseline.get("last_specials_divert") is None:
                    baseline["last_specials_divert"] = getattr(
                        cur, "last_specials_divert", None
                    ) or getattr(game, "last_specials_divert", None)
            except Exception:
                pass
    except Exception as exc:
        baseline["lr_suggestions_error"] = str(exc)

    # PR-Ph0: top-level focus sticky / specials for one-glance dig-in
    try:
        focus = baseline.get("focus_player") if isinstance(baseline.get("focus_player"), Mapping) else {}
        baseline["sticky_commitment"] = focus.get("sticky_commitment")
        baseline["focus_roads"] = focus.get("roads")
        baseline["focus_size_longest_route"] = focus.get("size_longest_route")
        baseline["focus_longest_route_tf"] = focus.get("longest_route_tf")
        baseline["focus_size_largest_army"] = focus.get("size_largest_army")
        baseline["focus_largest_army_tf"] = focus.get("largest_army_tf")
        baseline["focus_dcard_playable_counts"] = focus.get("dcard_playable_counts")
        baseline["focus_dcard_summary"] = focus.get("dcard_summary")
        if baseline.get("lr_project") is None and focus.get("lr_project"):
            baseline["lr_project"] = focus.get("lr_project")
    except Exception as exc:
        baseline["focus_enrich_error"] = str(exc)

    # Also attach report-level board_way_audits if present
    if isinstance(report, Mapping):
        baseline["report_board_way_audits"] = report.get("board_way_audits")
        baseline["report_board_recommendation"] = report.get("board_recommendation")
        baseline["report_board_fragility"] = report.get("board_fragility")

    safe_label = str(label or datetime.now().strftime("%Y%m%d_%H%M%S"))
    for ch in '<>:"/\\|?*':
        safe_label = safe_label.replace(ch, "_")

    # Write under saved_phase0_files/ (project root) so the repo root stays tidy.
    try:
        from core.constants import SAVED_PHASE0_DIR

        out_dir = Path(SAVED_PHASE0_DIR)
    except Exception:
        out_dir = Path("saved_phase0_files")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = (out_dir / f"Phase0_AI_Baseline_{safe_label}.json").resolve()
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False, default=json_default)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"json_write_failed: {exc}",
            "label": label,
            "baseline_path": str(path),
        }

    # Lightweight emptiness diagnostics so users know why strategy looks empty
    empty_hints: List[str] = []
    status = baseline.get("last_strategy_context_status") or {}
    if isinstance(status, Mapping) and status.get("error"):
        empty_hints.append(f"strategy_refresh: {status.get('error')}")
    if not baseline.get("current_board_way_audit"):
        empty_hints.append("no current_board_way_audit")
    if not baseline.get("last_action_timing_report"):
        empty_hints.append("no last_action_timing_report")
    focus = baseline.get("focus_player") or {}
    if not focus.get("strategic_direction"):
        empty_hints.append("focus_player has empty strategic_direction")
    if not focus.get("sticky_commitment"):
        empty_hints.append("focus_player has no sticky_commitment")
    if not baseline.get("last_perf_trace") and not (
        isinstance(baseline.get("perf_snapshot"), Mapping)
        and baseline["perf_snapshot"].get("last_perf_trace")
    ):
        empty_hints.append("no last_perf_trace")
    if (
        not baseline.get("last_twp_skip_reasons")
        and not baseline.get("last_incoming_offer_key")
        and not baseline.get("last_human_twp_offer_scan")
        and not (
            isinstance(baseline.get("twp"), Mapping)
            and baseline["twp"].get("last_human_twp_offer_scan")
        )
    ):
        empty_hints.append(
            "no twp skip/offer keys this capture "
            "(Incoming AI→HP or HP→AI offer_scan both empty)"
        )

    return {
        "ok": True,
        "baseline_path": str(path),
        "label": label,
        "focus_player_id": current_player_id,
        "focus_player_color": current_player_color,
        "empty_hints": empty_hints,
        "refresh_status": refresh_status,
        "ph0_enriched": True,
    }


def maybe_save_phase0_baseline(game: Any, reason: str = "auto") -> None:
    """Legacy unconditional auto-capture (Execution only). Prefer P2-C gate."""
    try:
        if getattr(game, "phase", None) == "Execution":
            save_phase0_baseline(
                game,
                label=f"auto_{reason}",
                reason=reason,
                refresh_before_capture=False,
                force_refresh=False,
            )
    except Exception:
        pass


def maybe_auto_save_phase0_for_pipeline(game: Any) -> Dict[str, Any]:
    """P2-C entry: one Phase0 file per AI pipeline when max span ≥ 2000 ms."""
    try:
        from core.performance_trace import maybe_auto_save_phase0_after_pipeline

        return maybe_auto_save_phase0_after_pipeline(game)
    except Exception as exc:
        return {"ok": False, "skipped": True, "error": str(exc)}


def install_phase0_baseline_hooks(GameClass: type) -> None:
    """Install the hooks on the Game class as proper instance methods."""

    def _bound_save(
        self: Any,
        label: str = "",
        reason: str = "manual",
        expected_future: Optional[Dict[str, Any]] = None,
        refresh_before_capture: bool = True,
        force_refresh: bool = True,
    ) -> Dict[str, Any]:
        return save_phase0_baseline(
            self,
            label=label,
            reason=reason,
            expected_future=expected_future,
            refresh_before_capture=refresh_before_capture,
            force_refresh=force_refresh,
        )

    def _bound_maybe(self: Any, reason: str = "auto") -> None:
        return maybe_save_phase0_baseline(self, reason=reason)

    def _bound_maybe_auto_pipeline(self: Any) -> Dict[str, Any]:
        return maybe_auto_save_phase0_for_pipeline(self)

    GameClass.save_phase0_baseline = _bound_save  # type: ignore[attr-defined]
    GameClass.maybe_save_phase0_baseline = _bound_maybe  # type: ignore[attr-defined]
    GameClass.maybe_auto_save_phase0_for_pipeline = _bound_maybe_auto_pipeline  # type: ignore[attr-defined]
    print("Phase0 baseline hooks installed successfully.")
