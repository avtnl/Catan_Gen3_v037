"""Human TwP incoming-offer policy helpers.

This module is intentionally GUI-free.  It stores and evaluates the Human
Player's policy for incoming AI→HP Trade-with-Player proposals.

Modes
-----
* manual / red / ai / auto
* Red: reject all AI→HP offers
* AI: accept using the normal TwP candidate pool (no panel)
* Auto (T4): custom rules + built-in keep/ditch defaults
* Manual: pending/accepted/declined routing for the incoming offer panel

T4 also provides offer one-liners, decline cooldown, and debug/Phase0 snapshots.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MODE_MANUAL = "manual"
MODE_RED = "red"
MODE_AI = "ai"
MODE_AUTO = "auto"
VALID_HUMAN_TWP_MODES = {MODE_MANUAL, MODE_RED, MODE_AI, MODE_AUTO}

# Resource tokens used in Auto rule text (HP mini-language)
RESOURCE_TOKEN_TO_INDEX: Dict[str, int] = {
    "Wh": 0,
    "O": 1,
    "Wd": 2,
    "B": 3,
    "Sh": 4,
}
RESOURCE_INDEX_TO_TOKEN: Tuple[str, ...] = ("Wh", "O", "Wd", "B", "Sh")
RESOURCE_INDEX_TO_SHORT: Tuple[str, ...] = ("Wh", "Or", "Wd", "Br", "Sh")
RESOURCE_INDEX_TO_NAME: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")

# Decline the same give→get pattern this many times before cooling it down
DECLINE_COOLDOWN_THRESHOLD: int = 2
# S4: keep cooldown active for this many rounds after the last decline hit threshold
DECLINE_COOLDOWN_ROUNDS: int = 3

# T9: freeze TwP when either side is a potential winner (projected VP > threshold)
TWP_FREEZE_VP_THRESHOLD: int = 6


def normalize_human_twp_mode(mode: Any) -> str:
    """Return a safe Human TwP mode string."""
    value = str(mode or MODE_MANUAL).strip().lower()
    if value in {"none", "off", "", "manual_mode"}:
        return MODE_MANUAL
    if value in {"twp_red", "red", "reject"}:
        return MODE_RED
    if value in {"twp_ai", "ai"}:
        return MODE_AI
    if value in {"twp_auto", "auto", "green", "rules"}:
        return MODE_AUTO
    return MODE_MANUAL


def get_human_twp_mode(game: Any) -> str:
    """Return the game-level Human TwP incoming-offer mode."""
    try:
        return normalize_human_twp_mode(getattr(game, "human_twp_mode", MODE_MANUAL))
    except Exception:
        return MODE_MANUAL


def set_human_twp_mode(game: Any, mode: Any) -> str:
    """Set and return the Human TwP mode.

    Red / AI / Auto are mutually exclusive because a single string stores the
    selected mode.  Manual means none of those three mode icons is active.
    """
    value = normalize_human_twp_mode(mode)
    try:
        setattr(game, "human_twp_mode", value)
        setattr(game, "last_human_twp_mode_change", {"mode": value})
    except Exception:
        pass
    return value


def toggle_human_twp_mode(game: Any, mode: Any) -> str:
    """Toggle Red/AI/Auto; clicking the active mode returns to Manual."""
    requested = normalize_human_twp_mode(mode)
    if requested == MODE_MANUAL:
        return set_human_twp_mode(game, MODE_MANUAL)
    current = get_human_twp_mode(game)
    if current == requested:
        return set_human_twp_mode(game, MODE_MANUAL)
    return set_human_twp_mode(game, requested)



# ─────────────────────────────────────────────────────────────────────────────
# TwP Auto rule storage + lightweight Step-5 validation
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_RULE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789*#!,-> ")
_ALLOWED_RESOURCE_TOKENS = ("Wh", "Wd", "Sh", "O", "B")


def get_human_twp_auto_rules(game: Any) -> List[str]:
    """Return HP's raw TwP Auto rules as a normalized list of strings.

    Step 5 stores rule text only.  Semantic matching of these rules is reserved
    for Step 6, but keeping storage in core prevents the GUI from owning game
    state.
    """
    try:
        rules = list(getattr(game, "human_twp_auto_rules", []) or [])
    except Exception:
        rules = []
    cleaned: List[str] = []
    for rule in rules:
        text = normalize_twp_auto_rule_text(rule)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def set_human_twp_auto_rules(game: Any, rules: Sequence[Any]) -> List[str]:
    """Replace HP's raw TwP Auto rule list after lightweight validation.

    Invalid and duplicate rules are skipped.  The full rule parser/evaluator is
    intentionally not part of Step 5.
    """
    result: List[str] = []
    for rule in list(rules or []):
        checked = validate_twp_auto_rule(rule, existing_rules=result)
        if checked.get("ok"):
            result.append(str(checked.get("rule", "")))
    try:
        setattr(game, "human_twp_auto_rules", list(result))
        setattr(game, "last_human_twp_auto_rules_change", {"rules": list(result)})
    except Exception:
        pass
    return result


def add_human_twp_auto_rule(game: Any, raw_rule: Any) -> Dict[str, Any]:
    """Validate and append one HP TwP Auto rule if it is not a duplicate."""
    rules = get_human_twp_auto_rules(game)
    checked = validate_twp_auto_rule(raw_rule, existing_rules=rules)
    if not checked.get("ok"):
        return checked
    rules.append(str(checked.get("rule", "")))
    set_human_twp_auto_rules(game, rules)
    return {"ok": True, "rule": str(checked.get("rule", "")), "rules": list(rules)}


def delete_human_twp_auto_rule(game: Any, index: int) -> Dict[str, Any]:
    """Delete one HP TwP Auto rule by zero-based index."""
    rules = get_human_twp_auto_rules(game)
    try:
        idx = int(index)
    except Exception:
        return {"ok": False, "reason": "invalid_rule_index", "rules": list(rules)}
    if idx < 0 or idx >= len(rules):
        return {"ok": False, "reason": "rule_index_out_of_range", "rules": list(rules)}
    removed = rules.pop(idx)
    set_human_twp_auto_rules(game, rules)
    return {"ok": True, "removed": removed, "rules": list(rules)}


def normalize_twp_auto_rule_text(raw_rule: Any) -> str:
    """Return a compact raw-rule string used for display and duplicate checks."""
    text = str(raw_rule or "").strip()
    # Collapse spaces around the arrow and commas, but keep compact tokens such
    # as **!Wh,O unchanged.
    text = text.replace(" ", "")
    return text


def validate_twp_auto_rule(raw_rule: Any, *, existing_rules: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Lightweight Step-5 syntax validation for HP TwP Auto rules.

    This is intentionally conservative UI validation only:
    - exactly one ``->``
    - non-empty left and right sides
    - no duplicate rule text
    - only known resource tokens and rule symbols are used

    Full wildcard/identical/except semantics are Step 6.
    """
    rule = normalize_twp_auto_rule_text(raw_rule)
    if not rule:
        return {"ok": False, "reason": "empty_rule"}
    if rule.count("->") != 1:
        return {"ok": False, "reason": "rule_must_contain_exactly_one_arrow"}
    left, right = rule.split("->", 1)
    if not left or not right:
        return {"ok": False, "reason": "both_sides_required", "rule": rule}
    if any(ch not in _ALLOWED_RULE_CHARS for ch in rule):
        return {"ok": False, "reason": "unsupported_character", "rule": rule}
    if not _side_has_known_atoms(left) or not _side_has_known_atoms(right):
        return {"ok": False, "reason": "unknown_resource_token", "rule": rule}
    existing = {normalize_twp_auto_rule_text(x) for x in list(existing_rules or [])}
    if rule in existing:
        return {"ok": False, "reason": "duplicate_rule", "rule": rule}
    return {"ok": True, "rule": rule}


def _side_has_known_atoms(side: str) -> bool:
    """Return True when a lightweight rule side uses only known atoms.

    The accepted symbols are deliberately broad enough for the planned mini
    language: resource tokens (Wh/O/Wd/B/Sh), wildcards (*), identical markers
    (#), except markers (!), and comma-separated parts.
    """
    rest = str(side or "")
    for token in _ALLOWED_RESOURCE_TOKENS:
        rest = rest.replace(token, "")
    rest = rest.replace("*", "").replace("#", "").replace("!", "").replace(",", "")
    return rest == ""

def _player_by_id(game: Any, player_id: Any) -> Optional[Any]:
    try:
        wanted = int(player_id)
    except Exception:
        return None
    for player in list(getattr(game, "players", []) or []):
        try:
            if int(getattr(player, "id", 0) or 0) == wanted:
                return player
        except Exception:
            continue
    return None


def _proposal_mapping(proposal: Any) -> Mapping[str, Any]:
    if isinstance(proposal, Mapping):
        return proposal
    try:
        as_dict = getattr(proposal, "as_dict", None)
        if callable(as_dict):
            data = as_dict()
            if isinstance(data, Mapping):
                return data
    except Exception:
        pass
    return {}


def proposal_key(proposal: Any) -> tuple:
    """Return a stable key for a concrete TwP proposal within one AI turn.

    The key is deliberately resource/direction specific.  It lets Manual mode
    remember whether HP has accepted or declined this exact AI→HP proposal while
    still allowing a different proposal to be offered afterwards.

    T8: always normalize to a 6-int tuple so pending keys match re-found proposals.
    """
    data = _proposal_mapping(proposal)
    try:
        return (
            int(data.get("active_player_id", 0) or 0),
            int(data.get("counterparty_id", 0) or 0),
            int(data.get("active_give_index", 0) or 0),
            int(data.get("active_give_count", 0) or 0),
            int(data.get("active_receive_index", 0) or 0),
            int(data.get("active_receive_count", 0) or 0),
        )
    except Exception:
        try:
            return (
                int(data.get("active_player_id") or 0),
                int(data.get("counterparty_id") or 0),
                int(data.get("active_give_index") or 0),
                int(data.get("active_give_count") or 0),
                int(data.get("active_receive_index") or 0),
                int(data.get("active_receive_count") or 0),
            )
        except Exception:
            return (0, 0, 0, 0, 0, 0)


def normalize_proposal_key(key: Any) -> tuple:
    """Coerce a stored proposal_key (list/tuple/mixed) to the canonical 6-int key."""
    try:
        seq = list(key) if not isinstance(key, (str, bytes)) else []
        if len(seq) >= 6:
            return tuple(int(seq[i] or 0) for i in range(6))
    except Exception:
        pass
    if isinstance(key, Mapping):
        return proposal_key(key)
    return (0, 0, 0, 0, 0, 0)


def is_proposal_declined_this_turn(game: Any, proposal: Any) -> bool:
    """T8: True when this exact deal key was declined earlier this AI turn.

    Checks ``human_twp_declined_this_turn`` and the v045-style
    ``list_of_TwP_rejected_by_HP`` bag (keys or full proposal mappings).
    """
    key = normalize_proposal_key(proposal_key(proposal))
    if key == (0, 0, 0, 0, 0, 0):
        # Empty key — do not treat as universally declined
        pass
    else:
        declined = _turn_set(game, "human_twp_declined_this_turn")
        if key in declined:
            return True
        # Also match any stored non-normalized entries
        for item in list(declined):
            if normalize_proposal_key(item) == key:
                return True
    # v045 dual-write bag (list of keys or deal dicts)
    try:
        bag = list(getattr(game, "list_of_TwP_rejected_by_HP", None) or [])
    except Exception:
        bag = []
    for item in bag:
        try:
            if isinstance(item, Mapping):
                if normalize_proposal_key(proposal_key(item)) == key and key != (0, 0, 0, 0, 0, 0):
                    return True
            else:
                if normalize_proposal_key(item) == key and key != (0, 0, 0, 0, 0, 0):
                    return True
        except Exception:
            continue
    return False


def remember_human_twp_decline(game: Any, proposal: Any) -> tuple:
    """T8-complete: record exact-key decline for this AI turn (set + v045 list).

    Returns the normalized 6-int proposal key.
    """
    key = normalize_proposal_key(proposal_key(proposal))
    try:
        declined = getattr(game, "human_twp_declined_this_turn", None)
        if not isinstance(declined, set):
            declined = set(list(declined or []) if declined is not None else [])
        if key != (0, 0, 0, 0, 0, 0):
            declined.add(key)
        setattr(game, "human_twp_declined_this_turn", declined)
    except Exception:
        pass
    try:
        bag = list(getattr(game, "list_of_TwP_rejected_by_HP", None) or [])
        if key != (0, 0, 0, 0, 0, 0) and key not in bag:
            # Prefer storing the key (membership cheap); also keep proposal dig-in
            bag.append(key)
        setattr(game, "list_of_TwP_rejected_by_HP", bag)
    except Exception:
        pass
    return key


# ─────────────────────────────────────────────────────────────────────────────
# T9: Endgame TwP freeze (projected VP > 6 on either side)
# ─────────────────────────────────────────────────────────────────────────────


def projected_vp_for_twp_freeze(player: Any) -> int:
    """Conservative projected VP for freeze: board/specials + unplayed DCards.

    Prefer Oxley-style ``virtual_vp`` (effective VP + unplayed hand cards).
    Falls back to ``effective_vp`` / stored points.
    """
    if player is None:
        return 0
    try:
        from core.ai_dcard_timing import virtual_vp

        return int(virtual_vp(player))
    except Exception:
        pass
    try:
        from core.victory import effective_vp

        return int(effective_vp(player))
    except Exception:
        pass
    for attr in ("victory_points", "points"):
        try:
            raw = getattr(player, attr, None)
            if raw is not None:
                return int(raw)
        except Exception:
            continue
    return 0


def is_potential_winner_twp_freeze(
    player: Any,
    *,
    threshold: int = TWP_FREEZE_VP_THRESHOLD,
) -> bool:
    """True when projected VP is strictly greater than ``threshold`` (default 6)."""
    try:
        return int(projected_vp_for_twp_freeze(player)) > int(threshold)
    except Exception:
        return False


def proposal_hits_twp_endgame_freeze(
    game: Any,
    proposal: Any,
    *,
    threshold: int = TWP_FREEZE_VP_THRESHOLD,
) -> Tuple[bool, str, Dict[str, Any]]:
    """T9: freeze if active or counterparty is a potential winner.

    Returns (hits, reason, meta).
    """
    data = _proposal_mapping(proposal)
    active = _player_by_id(game, data.get("active_player_id"))
    counter = _player_by_id(game, data.get("counterparty_id"))
    meta: Dict[str, Any] = {
        "threshold": int(threshold),
        "active_id": data.get("active_player_id"),
        "counterparty_id": data.get("counterparty_id"),
        "active_projected_vp": projected_vp_for_twp_freeze(active),
        "counterparty_projected_vp": projected_vp_for_twp_freeze(counter),
    }
    active_hit = is_potential_winner_twp_freeze(active, threshold=threshold)
    counter_hit = is_potential_winner_twp_freeze(counter, threshold=threshold)
    meta["active_freeze"] = bool(active_hit)
    meta["counterparty_freeze"] = bool(counter_hit)
    if active_hit and counter_hit:
        return True, "endgame_twp_freeze_both_sides", meta
    if active_hit:
        return True, "endgame_twp_freeze_active", meta
    if counter_hit:
        return True, "endgame_twp_freeze_counterparty", meta
    return False, "", meta


def players_hit_twp_endgame_freeze(
    game: Any,
    active: Any,
    counterparty: Any,
    *,
    threshold: int = TWP_FREEZE_VP_THRESHOLD,
) -> bool:
    """T9 pair-level freeze for find_twp_proposals loops."""
    return bool(
        is_potential_winner_twp_freeze(active, threshold=threshold)
        or is_potential_winner_twp_freeze(counterparty, threshold=threshold)
    )


def _turn_set(game: Any, attr_name: str) -> set:
    """Return a mutable per-turn proposal-key set on game."""
    try:
        value = getattr(game, attr_name, None)
        if not isinstance(value, set):
            value = set(value or [])
            setattr(game, attr_name, value)
        return value
    except Exception:
        return set()


def proposal_involves_human(game: Any, proposal: Any) -> bool:
    """Return True if either side of the TwP proposal is a human player."""
    data = _proposal_mapping(proposal)
    for key in ("active_player_is_human", "counterparty_is_human"):
        try:
            if bool(data.get(key)):
                return True
        except Exception:
            pass

    for key in ("active_player_id", "counterparty_id"):
        player = _player_by_id(game, data.get(key))
        try:
            if player is not None and bool(getattr(player, "is_human", False)):
                return True
        except Exception:
            pass
    return False


def resolve_incoming_human_twp_offer(game: Any, proposal: Any) -> Dict[str, Any]:
    """Resolve an incoming AI→HP TwP proposal against the current HP policy.

    Returned status values:
    * not_human_involved: normal AI-vs-AI proposal
    * rejected: Red mode, Auto reject, decline memory (T8), endgame freeze (T9)
    * accepted_ai: AI mode says the existing TwP algorithm may accept for HP
    * accepted_auto: reserved for future HP auto-rules
    * pending_human_response: Manual mode, to be handled by the future popup
    """
    data = dict(_proposal_mapping(proposal))
    mode = get_human_twp_mode(game)
    involves_human = proposal_involves_human(game, proposal)
    result: Dict[str, Any] = {
        "ok": True,
        "mode": mode,
        "involves_human": bool(involves_human),
        "status": "not_human_involved",
        "accepted": False,
        "requires_human_panel": False,
        "reason": "not_human_involved",
        "proposal": data,
    }

    # T9: freeze before mode routing (applies to human-involved and AI↔AI)
    freeze, freeze_reason, freeze_meta = proposal_hits_twp_endgame_freeze(game, proposal)
    if freeze:
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": freeze_reason or "endgame_twp_freeze",
            "endgame_freeze": dict(freeze_meta),
            "involves_human": bool(involves_human),
            "explain": format_twp_offer_explanation(game, proposal, for_human=True),
        })
        return result

    if not involves_human:
        result["accepted"] = bool(data.get("auto_executable", True))
        return result

    # T8: exact declined key never returns to Incoming this turn
    key = normalize_proposal_key(proposal_key(proposal))
    if is_proposal_declined_this_turn(game, proposal):
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": "human_twp_manual_mode_hp_declined_this_offer",
            "proposal_key": key,
            "explain": format_twp_offer_explanation(game, proposal, for_human=True),
        })
        return result

    if mode == MODE_RED:
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": "human_twp_red_mode_rejects_incoming_offer",
            "explain": format_twp_offer_explanation(game, proposal, for_human=True),
        })
        return result

    if mode == MODE_AI:
        # The proposal reached this function only after core.player_trade built a
        # normal candidate with the same AI guard rails used for AI counterparties
        # (card availability, protected/bottleneck resources, same-turn locks and
        # strategy-fit scoring).  TwP_AI therefore means: include HP in the
        # ordinary candidate pool without opening the Manual-mode panel.
        result.update({
            "status": "accepted_ai",
            "accepted": True,
            "requires_human_panel": False,
            "reason": "human_twp_ai_mode_accepts_existing_ai_twp_candidate",
            "explain": format_twp_offer_explanation(game, proposal, for_human=True),
        })
        return result

    if mode == MODE_AUTO:
        # T4: cooldown first, then custom rules, else keep/ditch defaults
        cooled, cool_reason = is_pattern_cooled_down(game, proposal)
        if cooled:
            result.update({
                "status": "rejected",
                "accepted": False,
                "requires_human_panel": False,
                "reason": cool_reason,
                "explain": format_twp_offer_explanation(game, proposal, for_human=True),
            })
            return result
        auto_decision = evaluate_auto_mode_offer(game, proposal)
        result.update(auto_decision)
        result["mode"] = mode
        result["involves_human"] = True
        result["requires_human_panel"] = False
        result["proposal"] = data
        result["explain"] = format_twp_offer_explanation(game, proposal, for_human=True)
        result["ok"] = True
        return result

    # Manual mode: accept memory is for T7 binding only — do **not** auto-accept
    # soft re-plans of the same key as a free-pass to re-rank partners (T7).
    # Declined keys already handled above (T8).
    accepted = _turn_set(game, "human_twp_accepted_this_turn")
    # If key was accepted this turn, still require execute of that concrete deal
    # via accepted_binding_proposal; treat further routing as non-panel reject
    # so re-plan cannot open Incoming for K again, but also cannot silently
    # treat K as a free auto-accept for ranking other partners.
    if key in accepted or any(normalize_proposal_key(x) == key for x in list(accepted)):
        result.update({
            "status": "accepted_manual_bound",
            "accepted": False,  # T7: do not soft-accept into ranked pool
            "requires_human_panel": False,
            "reason": "human_twp_manual_mode_hp_accepted_binding_only",
            "proposal_key": key,
            "binding_only": True,
            "explain": format_twp_offer_explanation(game, proposal, for_human=True),
        })
        return result

    # Manual: skip re-offering cooled patterns (fewer spam panels)
    cooled, cool_reason = is_pattern_cooled_down(game, proposal)
    if cooled:
        result.update({
            "status": "rejected",
            "accepted": False,
            "requires_human_panel": False,
            "reason": cool_reason,
            "proposal_key": key,
            "explain": format_twp_offer_explanation(game, proposal, for_human=True),
        })
        return result

    result.update({
        "status": "pending_human_response",
        "accepted": False,
        "requires_human_panel": True,
        "reason": "human_twp_manual_mode_requires_incoming_offer_panel",
        "proposal_key": key,
        "explain": format_twp_offer_explanation(game, proposal, for_human=True),
    })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# T4: Auto rules (keep/ditch defaults + custom matcher)
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_auto_mode_offer(game: Any, proposal: Any) -> Dict[str, Any]:
    """Decide Auto-mode accept/reject for one AI→HP proposal."""
    data = dict(_proposal_mapping(proposal))
    rules = get_human_twp_auto_rules(game)
    hp_give_idx, hp_give_n, hp_recv_idx, hp_recv_n = _hp_trade_legs(data)

    if rules:
        for rule in rules:
            matched, detail = match_auto_rule(
                rule,
                hp_give_idx=hp_give_idx,
                hp_give_count=hp_give_n,
                hp_recv_idx=hp_recv_idx,
                hp_recv_count=hp_recv_n,
            )
            if matched:
                return {
                    "status": "accepted_auto",
                    "accepted": True,
                    "reason": f"human_twp_auto_rule_match:{rule}",
                    "matched_rule": rule,
                    "match_detail": detail,
                }
        return {
            "status": "rejected",
            "accepted": False,
            "reason": "human_twp_auto_no_matching_rule",
            "matched_rule": None,
            "rules_checked": list(rules),
        }

    # No custom rules → built-in keep/ditch policy
    ok, reason, meta = evaluate_keep_ditch_auto_default(game, proposal)
    return {
        "status": "accepted_auto" if ok else "rejected",
        "accepted": bool(ok),
        "reason": reason,
        "matched_rule": "builtin:keep_ditch",
        "keep_ditch": dict(meta),
    }


def evaluate_keep_ditch_auto_default(
    game: Any,
    proposal: Any,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Accept if HP gives only ditch and receives keep-need (or unlocks primary).

    This is the T4 default Auto policy when no custom rules are configured.
    """
    data = dict(_proposal_mapping(proposal))
    hp = _human_player_from_proposal(game, data)
    meta: Dict[str, Any] = {"policy": "keep_ditch_default"}
    if hp is None:
        return False, "human_twp_auto_no_human_player", meta

    hp_give_idx, hp_give_n, hp_recv_idx, hp_recv_n = _hp_trade_legs(data)
    if hp_give_idx is None or hp_recv_idx is None:
        return False, "human_twp_auto_invalid_proposal_legs", meta

    keep, ditch, missing, primary = _hp_keep_ditch_missing(game, hp)
    meta.update({
        "keep": list(keep),
        "ditch": list(ditch),
        "missing": list(missing),
        "primary": primary,
        "hp_give_idx": hp_give_idx,
        "hp_recv_idx": hp_recv_idx,
    })

    # Completes HP primary?
    completes = False
    try:
        from core.player_trade import build_trade_profile, _trade_completes_primary_action

        profile = build_trade_profile(game, hp)
        completes = _trade_completes_primary_action(
            profile,
            give_idx=int(hp_give_idx),
            give_count=int(hp_give_n),
            receive_idx=int(hp_recv_idx),
            receive_count=int(hp_recv_n),
        )
        meta["primary"] = str(getattr(profile, "primary_action", primary) or primary)
    except Exception:
        completes = False

    spends_keep = int(hp_give_n) > int(ditch[hp_give_idx] or 0)
    if spends_keep and not completes:
        return (
            False,
            "human_twp_auto_rejects_keep_spend_without_unlock",
            meta,
        )
    if spends_keep and completes:
        return True, "human_twp_auto_accepts_keep_for_primary_unlock", meta

    # Ditch-funded: require receive fills need (or soft unlock already handled)
    fills_need = int(missing[hp_recv_idx] or 0) > 0
    meta["fills_need"] = fills_need
    meta["ditch_funded"] = not spends_keep
    if not spends_keep and fills_need:
        return True, "human_twp_auto_accepts_ditch_for_need", meta
    if not spends_keep and completes:
        return True, "human_twp_auto_accepts_ditch_unlock", meta

    return False, "human_twp_auto_rejects_no_need_or_unlock", meta


def match_auto_rule(
    rule: str,
    *,
    hp_give_idx: Optional[int],
    hp_give_count: int,
    hp_recv_idx: Optional[int],
    hp_recv_count: int,
) -> Tuple[bool, str]:
    """Match one Auto rule string against HP give/receive legs.

    Convention: ``give->receive`` from the human's perspective
    (e.g. ``Wh->Wd`` = HP gives Wheat, receives Wood).

    Supported atoms per side (comma-OR of parts):
      Wh O Wd B Sh  — exact resource
      *             — any resource
      #             — same resource as the other side (identity swap rare)
      !Wh           — any except Wh (on a single-token side)

    Counts: 1:1 default; multi-card proposals still match resource identity only
    in T4 (quantity gates stay in the TwP engine).
    """
    text = normalize_twp_auto_rule_text(rule)
    if "->" not in text:
        return False, "no_arrow"
    left, right = text.split("->", 1)
    if hp_give_idx is None or hp_recv_idx is None:
        return False, "missing_legs"
    if not _side_matches(left, int(hp_give_idx), other_idx=int(hp_recv_idx)):
        return False, f"give_side_mismatch:{left}"
    if not _side_matches(right, int(hp_recv_idx), other_idx=int(hp_give_idx)):
        return False, f"recv_side_mismatch:{right}"
    _ = (hp_give_count, hp_recv_count)
    return True, f"matched {text}"


def _side_matches(side: str, resource_idx: int, *, other_idx: int) -> bool:
    parts = [p for p in str(side or "").split(",") if p]
    if not parts:
        return False
    for part in parts:
        if part == "*":
            return True
        if part == "#":
            if int(resource_idx) == int(other_idx):
                return True
            continue
        if part.startswith("!") and len(part) > 1:
            # except-list: match if resource is NOT any excepted token
            excepted = part[1:]
            # allow !Wh,O style only as separate comma parts; here single except
            if excepted in RESOURCE_TOKEN_TO_INDEX:
                if int(resource_idx) != int(RESOURCE_TOKEN_TO_INDEX[excepted]):
                    return True
            continue
        if part in RESOURCE_TOKEN_TO_INDEX:
            if int(resource_idx) == int(RESOURCE_TOKEN_TO_INDEX[part]):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# T4: offer explain + decline cooldown
# ─────────────────────────────────────────────────────────────────────────────


def format_twp_offer_explanation(
    game: Any,
    proposal: Any,
    *,
    for_human: bool = True,
) -> str:
    """One-line human-readable offer summary.

    Example: ``Gives ditch Wh, fills Wd for road``
    """
    data = dict(_proposal_mapping(proposal))
    if for_human:
        give_idx, give_n, recv_idx, recv_n = _hp_trade_legs(data)
        actor = "You"
        hp = _human_player_from_proposal(game, data)
    else:
        try:
            give_idx = int(data.get("active_give_index"))
            give_n = int(data.get("active_give_count") or 1)
            recv_idx = int(data.get("active_receive_index"))
            recv_n = int(data.get("active_receive_count") or 1)
        except Exception:
            return "TwP offer"
        actor = f"P{data.get('active_player_id', '?')}"
        hp = _player_by_id(game, data.get("active_player_id"))

    if give_idx is None or recv_idx is None:
        return "TwP offer"

    g_tok = RESOURCE_INDEX_TO_SHORT[give_idx] if 0 <= give_idx < 5 else "?"
    r_tok = RESOURCE_INDEX_TO_SHORT[recv_idx] if 0 <= recv_idx < 5 else "?"
    give_tag = ""
    recv_tag = ""
    primary = ""
    if hp is not None:
        keep, ditch, missing, primary = _hp_keep_ditch_missing(game, hp)
        if int(give_n) <= int(ditch[give_idx] or 0):
            give_tag = "ditch "
        elif int(keep[give_idx] or 0) > 0:
            give_tag = "keep "
        if int(missing[recv_idx] or 0) > 0:
            recv_tag = "fills "
        else:
            recv_tag = "gets "

    give_txt = f"{give_n} {g_tok}" if int(give_n) != 1 else g_tok
    recv_txt = f"{recv_n} {r_tok}" if int(recv_n) != 1 else r_tok
    bits = [f"{actor}: give {give_tag}{give_txt} → {recv_tag}{recv_txt}"]
    if primary:
        bits.append(f"for {primary}")
    partner = data.get("active_player_id") if for_human else data.get("counterparty_id")
    if partner is not None:
        bits.append(f"vs P{partner}")
    return "; ".join(bits)


def pattern_key_hp_view(proposal: Any) -> Tuple[Any, ...]:
    """Stable HP-perspective pattern (give_idx, recv_idx) for cooldown."""
    data = _proposal_mapping(proposal)
    gi, _, ri, _ = _hp_trade_legs(data)
    return (gi, ri)


def _decline_entry_count(entry: Any) -> int:
    if isinstance(entry, Mapping):
        try:
            return int(entry.get("count", 0) or 0)
        except Exception:
            return 0
    try:
        return int(entry or 0)
    except Exception:
        return 0


def _decline_entry_last_round(entry: Any) -> int:
    if isinstance(entry, Mapping):
        try:
            return int(entry.get("last_round", 0) or 0)
        except Exception:
            return 0
    return 0


def register_human_twp_decline(game: Any, proposal: Any) -> Dict[str, Any]:
    """Record a decline pattern for multi-turn cooldown (T4/S4).

    Same-turn exact-key memory (T8) is owned by
    ``Game.respond_to_pending_human_twp_offer`` so multi-round cooldown tests and
    pattern bookkeeping stay independent of the per-turn set.

    Stores ``{count, last_round, last_turn}`` per HP give→get pattern and appends
    a short trail on ``game.human_twp_decline_log`` / turn details when present.
    """
    key = pattern_key_hp_view(proposal)
    try:
        bag = getattr(game, "human_twp_decline_patterns", None)
        if not isinstance(bag, dict):
            bag = {}
        prev = bag.get(key)
        count = _decline_entry_count(prev) + 1
        rnd = 0
        turn = 0
        try:
            rnd = int(getattr(game, "round", 0) or 0)
            turn = int(getattr(game, "turn", 0) or 0)
        except Exception:
            pass
        bag[key] = {
            "count": count,
            "last_round": rnd,
            "last_turn": turn,
        }
        setattr(game, "human_twp_decline_patterns", bag)

        # S4: durable short log for turn details / Phase0
        try:
            log = list(getattr(game, "human_twp_decline_log", None) or [])
            log.append(
                {
                    "pattern": list(key) if isinstance(key, tuple) else key,
                    "count": count,
                    "round": rnd,
                    "turn": turn,
                    "active_player_id": _proposal_mapping(proposal).get("active_player_id"),
                    "counterparty_id": _proposal_mapping(proposal).get("counterparty_id"),
                }
            )
            setattr(game, "human_twp_decline_log", log[-24:])
        except Exception:
            pass
        try:
            # Optional turn_details vector bump on HP if present
            hp = None
            for p in list(getattr(game, "players", []) or []):
                if bool(getattr(p, "is_human", False)):
                    hp = p
                    break
            if hp is not None:
                details = list(getattr(hp, "turn_details_last_TwPdeal", None) or [0, 0, 0, 0, 0, 0])
                while len(details) < 6:
                    details.append(0)
                # slot 5: decline count this session (soft)
                details[5] = int(details[5] or 0) + 1
                setattr(hp, "turn_details_last_TwPdeal", details[:6])
        except Exception:
            pass
        return {"ok": True, "pattern": key, "count": count, "last_round": rnd}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def register_human_twp_accept(game: Any, proposal: Any) -> Dict[str, Any]:
    """Clear or soften decline count when HP accepts a pattern."""
    key = pattern_key_hp_view(proposal)
    try:
        bag = getattr(game, "human_twp_decline_patterns", None)
        if not isinstance(bag, dict):
            return {"ok": True, "pattern": key, "count": 0}
        if key in bag:
            entry = bag[key]
            count = max(0, _decline_entry_count(entry) - 1)
            if count <= 0:
                bag.pop(key, None)
            elif isinstance(entry, Mapping):
                bag[key] = {
                    "count": count,
                    "last_round": entry.get("last_round", 0),
                    "last_turn": entry.get("last_turn", 0),
                }
            else:
                bag[key] = count
        setattr(game, "human_twp_decline_patterns", bag)
        left = _decline_entry_count(bag.get(key)) if key in bag else 0
        return {"ok": True, "pattern": key, "count": left}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def is_pattern_cooled_down(game: Any, proposal: Any) -> Tuple[bool, str]:
    """True when HP has repeatedly declined this give→get pattern recently.

    S4: threshold hits arm a multi-round cooldown (``DECLINE_COOLDOWN_ROUNDS``)
    from the last decline, so identical AI→HP spam stops for a few rounds.
    """
    key = pattern_key_hp_view(proposal)
    try:
        bag = getattr(game, "human_twp_decline_patterns", None) or {}
        entry = bag.get(key) if isinstance(bag, Mapping) else None
        count = _decline_entry_count(entry)
        last_round = _decline_entry_last_round(entry)
    except Exception:
        count = 0
        last_round = 0
    if count < DECLINE_COOLDOWN_THRESHOLD:
        return False, ""
    try:
        cur_round = int(getattr(game, "round", 0) or 0)
    except Exception:
        cur_round = 0
    # If last_round unknown (legacy int bag), treat as active cooldown
    age = cur_round - last_round if last_round > 0 else 0
    if last_round > 0 and age >= int(DECLINE_COOLDOWN_ROUNDS):
        # Cooldown expired — soft-decay count so a single new decline re-arms
        try:
            if isinstance(bag, dict) and key in bag:
                bag[key] = {
                    "count": max(1, count - 1),
                    "last_round": last_round,
                    "last_turn": 0,
                }
                setattr(game, "human_twp_decline_patterns", bag)
        except Exception:
            pass
        return False, ""
    g = RESOURCE_INDEX_TO_SHORT[key[0]] if key[0] is not None and 0 <= int(key[0]) < 5 else "?"
    r = RESOURCE_INDEX_TO_SHORT[key[1]] if key[1] is not None and 0 <= int(key[1]) < 5 else "?"
    return True, f"human_twp_pattern_cooldown:{g}->{r}_declined_x{count}"


# ─────────────────────────────────────────────────────────────────────────────
# T10: Human counter builder (Incoming AI→HP)
# ─────────────────────────────────────────────────────────────────────────────

TWP_COUNTER_MAX_COUNT: int = 4


def _player_by_id_local(game: Any, player_id: Any) -> Any:
    try:
        pid = int(player_id or 0)
    except Exception:
        return None
    for p in list(getattr(game, "players", None) or []):
        try:
            if int(getattr(p, "id", 0) or 0) == pid:
                return p
        except Exception:
            continue
    return None


def _hand_counts(player: Any) -> List[int]:
    hand = [0, 0, 0, 0, 0]
    if player is None:
        return hand
    try:
        from core.player_trade import _get_hand

        h = [max(0, int(x or 0)) for x in list(_get_hand(player) or [])[:5]]
        while len(h) < 5:
            h.append(0)
        return h[:5]
    except Exception:
        pass
    try:
        rc = getattr(player, "rcards", None)
        if isinstance(rc, Mapping):
            names = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
            return [max(0, int(rc.get(n, rc.get(n.lower(), 0)) or 0)) for n in names]
        if isinstance(rc, (list, tuple)) and len(rc) >= 5:
            return [max(0, int(rc[i] or 0)) for i in range(5)]
    except Exception:
        pass
    return hand


def draft_from_proposal(proposal: Any) -> Dict[str, int]:
    """AI-active draft: ai_give_* / hp_give_*."""
    data = _proposal_mapping(proposal)
    return {
        "ai_give_index": int(data.get("active_give_index", 0) or 0),
        "ai_give_count": max(0, int(data.get("active_give_count", 0) or 0)),
        "hp_give_index": int(data.get("active_receive_index", 0) or 0),
        "hp_give_count": max(0, int(data.get("active_receive_count", 0) or 0)),
    }


def build_counter_proposal(
    original: Mapping[str, Any],
    draft: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build AI-active proposal from counter draft + original partner ids."""
    orig = dict(original or {})
    d = dict(draft or {})
    ai_idx = max(0, min(4, int(d.get("ai_give_index", 0) or 0)))
    hp_idx = max(0, min(4, int(d.get("hp_give_index", 0) or 0)))
    ai_n = max(0, int(d.get("ai_give_count", 0) or 0))
    hp_n = max(0, int(d.get("hp_give_count", 0) or 0))
    ai_id = int(orig.get("active_player_id", 0) or 0)
    hp_id = int(orig.get("counterparty_id", 0) or 0)
    names = RESOURCE_INDEX_TO_TOKEN
    label = (
        f"P{ai_id}: {ai_n}{names[ai_idx]}->{hp_n}{names[hp_idx]} with P{hp_id}"
    )
    return {
        "active_player_id": ai_id,
        "counterparty_id": hp_id,
        "active_player_is_human": False,
        "counterparty_is_human": True,
        "active_give_index": ai_idx,
        "active_give_count": ai_n,
        "active_receive_index": hp_idx,
        "active_receive_count": hp_n,
        "auto_executable": False,
        "requires_human_confirmation": True,
        "source": "human_counter_t10",
        "parent_proposal_key": list(proposal_key(orig)),
        "legacy_short_text": label,
        "description": label,
        "total_score": 0.0,
    }


def validate_twp_counter_draft(
    game: Any,
    original: Mapping[str, Any],
    draft: Mapping[str, Any],
    *,
    max_count: int = TWP_COUNTER_MAX_COUNT,
) -> Dict[str, Any]:
    """Validate HP counter draft. Does not mutate game."""
    orig = dict(original or {})
    d = dict(draft or {})
    ai = _player_by_id_local(game, orig.get("active_player_id"))
    hp = _player_by_id_local(game, orig.get("counterparty_id"))
    if ai is None or hp is None:
        return {"ok": False, "reason": "bad_roles", "same_as_original": False}
    if bool(getattr(ai, "is_human", False)) or not bool(getattr(hp, "is_human", False)):
        return {"ok": False, "reason": "bad_roles", "same_as_original": False}

    hit, why, meta = proposal_hits_twp_endgame_freeze(game, orig)
    if hit:
        return {"ok": False, "reason": why or "t9_freeze", "same_as_original": False, "meta": meta}

    try:
        ai_idx = int(d.get("ai_give_index", 0) or 0)
        hp_idx = int(d.get("hp_give_index", 0) or 0)
        ai_n = int(d.get("ai_give_count", 0) or 0)
        hp_n = int(d.get("hp_give_count", 0) or 0)
    except Exception:
        return {"ok": False, "reason": "bad_index", "same_as_original": False}

    if not (0 <= ai_idx <= 4 and 0 <= hp_idx <= 4):
        return {"ok": False, "reason": "bad_index", "same_as_original": False}
    if ai_n < 1 or hp_n < 1:
        return {"ok": False, "reason": "empty_side", "same_as_original": False}
    if ai_n > int(max_count) or hp_n > int(max_count):
        return {"ok": False, "reason": "count_cap", "same_as_original": False}

    ai_hand = _hand_counts(ai)
    hp_hand = _hand_counts(hp)
    if ai_hand[ai_idx] < ai_n:
        return {"ok": False, "reason": "ai_cannot_pay", "same_as_original": False}
    if hp_hand[hp_idx] < hp_n:
        return {"ok": False, "reason": "hp_cannot_pay", "same_as_original": False}

    proposal = build_counter_proposal(orig, d)
    hit2, why2, meta2 = proposal_hits_twp_endgame_freeze(game, proposal)
    if hit2:
        return {"ok": False, "reason": why2 or "t9_freeze", "same_as_original": False, "meta": meta2}

    if is_proposal_declined_this_turn(game, proposal):
        return {"ok": False, "reason": "declined_key", "same_as_original": False}

    same = proposal_key(proposal) == proposal_key(orig)
    return {
        "ok": True,
        "reason": "ok",
        "same_as_original": bool(same),
        "proposal": proposal,
        "ai_hand": ai_hand,
        "hp_hand": hp_hand,
    }


def evaluate_ai_response_to_human_counter(
    game: Any,
    proposal: Mapping[str, Any],
) -> Dict[str, Any]:
    """AI Accept/Decline for a human counter (AI is active on the package).

    Uses existing TwP score floors when scorer is available; same floors as
    self-generated offers (locked T10 Q3).
    """
    prop = dict(proposal or {})
    hit, why, meta = proposal_hits_twp_endgame_freeze(game, prop)
    if hit:
        return {
            "accept": False,
            "reason": why or "t9_freeze",
            "score": None,
            "proposal": prop,
            "meta": meta,
        }

    # Hands still legal
    ai = _player_by_id_local(game, prop.get("active_player_id"))
    hp = _player_by_id_local(game, prop.get("counterparty_id"))
    if ai is None or hp is None:
        return {"accept": False, "reason": "bad_roles", "score": None, "proposal": prop}
    ai_hand = _hand_counts(ai)
    hp_hand = _hand_counts(hp)
    gi = int(prop.get("active_give_index", 0) or 0)
    gn = int(prop.get("active_give_count", 0) or 0)
    ri = int(prop.get("active_receive_index", 0) or 0)
    rn = int(prop.get("active_receive_count", 0) or 0)
    if ai_hand[gi] < gn or hp_hand[ri] < rn:
        return {"accept": False, "reason": "hands_illegal", "score": None, "proposal": prop}

    score: Optional[float] = None
    trade_type = "normal_1_for_1"
    try:
        from core.player_trade import (
            MIN_ACTIVE_SCORE_BY_TRADE_TYPE,
            TRADE_NORMAL_1_FOR_1,
            TRADE_SCARCITY_PREMIUM_1_FOR_2,
            TRADE_TEMPTING_2_FOR_1,
            _classify_quantity_pattern,
            _score_trade_for_profile,
            build_resource_market,
            build_trade_profile,
        )

        tt = _classify_quantity_pattern(gn, rn)
        if tt is None:
            if gn == rn:
                tt = TRADE_NORMAL_1_FOR_1
            elif gn == 2 * rn:
                tt = TRADE_TEMPTING_2_FOR_1
            elif rn == 2 * gn:
                tt = TRADE_SCARCITY_PREMIUM_1_FOR_2
            else:
                tt = TRADE_NORMAL_1_FOR_1
        trade_type = str(tt)
        market = build_resource_market(game)
        ap = build_trade_profile(game, ai, market=market)
        score = float(
            _score_trade_for_profile(
                profile=ap,
                give_idx=gi,
                give_count=gn,
                receive_idx=ri,
                receive_count=rn,
                trade_type=trade_type,
                market=market,
                is_active=True,
            )
        )
        floor = float(MIN_ACTIVE_SCORE_BY_TRADE_TYPE.get(trade_type, 0.20))
        if score < floor:
            return {
                "accept": False,
                "reason": f"ai_score_below_floor:{score:.3f}<{floor:.3f}",
                "score": score,
                "trade_type": trade_type,
                "proposal": prop,
            }
        return {
            "accept": True,
            "reason": "ai_score_ok",
            "score": score,
            "trade_type": trade_type,
            "proposal": prop,
        }
    except Exception as exc:
        # Fallback: accept if AI receives at least as many cards as given,
        # or only one more given than received (mild 2:1).
        if gn <= rn + 1:
            return {
                "accept": True,
                "reason": f"fallback_net_ok:{exc}",
                "score": score,
                "proposal": prop,
            }
        return {
            "accept": False,
            "reason": f"fallback_net_bad:{exc}",
            "score": score,
            "proposal": prop,
        }


def is_twp_counter_active(game: Any) -> bool:
    pending = getattr(game, "pending_twp_counter", None)
    return isinstance(pending, Mapping) and bool(pending.get("active"))


def get_pending_twp_counter(game: Any) -> Dict[str, Any]:
    pending = getattr(game, "pending_twp_counter", None)
    return dict(pending) if isinstance(pending, Mapping) else {}


# ─────────────────────────────────────────────────────────────────────────────
# T4: debug / Phase0 snapshot
# ─────────────────────────────────────────────────────────────────────────────


def _format_counter_draft_label(draft: Any) -> str:
    """Short label for counter draft (AI give → HP give)."""
    if not isinstance(draft, Mapping):
        return "?"
    try:
        ai_i = int(draft.get("ai_give_index", 0) or 0)
        hp_i = int(draft.get("hp_give_index", 0) or 0)
        ai_n = int(draft.get("ai_give_count", 0) or 0)
        hp_n = int(draft.get("hp_give_count", 0) or 0)
        ai_t = RESOURCE_INDEX_TO_TOKEN[ai_i] if 0 <= ai_i < 5 else "?"
        hp_t = RESOURCE_INDEX_TO_TOKEN[hp_i] if 0 <= hp_i < 5 else "?"
        return f"{ai_n}{ai_t}->{hp_n}{hp_t}"
    except Exception:
        return "?"


def build_twp_debug_snapshot(game: Any) -> Dict[str, Any]:
    """Compact TwP status for Execution Debug PLAN + Phase0 baselines."""
    mode = get_human_twp_mode(game)
    best = getattr(game, "current_best_action", None)
    best_d = dict(best) if isinstance(best, Mapping) else {}
    policy = getattr(game, "last_human_twp_policy_decision", None)
    policy_d = dict(policy) if isinstance(policy, Mapping) else {}
    skip = list(getattr(game, "last_twp_skip_reasons", None) or [])

    action = str(best_d.get("action", "") or "")
    mode_src = str(best_d.get("mode", "") or best_d.get("source", "") or "")
    label = str(best_d.get("best_action_text") or best_d.get("label") or action or "none")

    # T10: counter builder / last result take priority for PLAN line
    counter = get_pending_twp_counter(game)
    last_ctr = getattr(game, "last_twp_counter_result", None)
    last_ctr_d = dict(last_ctr) if isinstance(last_ctr, Mapping) else {}
    counter_active = bool(counter.get("active"))
    counter_draft_label = (
        _format_counter_draft_label(counter.get("draft")) if counter_active else ""
    )

    line = "TwP: none"
    if counter_active:
        line = f"TwP: counter draft {counter_draft_label or '?'}"
    elif last_ctr_d.get("action") == "return_counter_accepted":
        line = "TwP: counter accepted"
    elif last_ctr_d.get("action") == "return_counter_declined":
        line = "TwP: counter declined"
    elif last_ctr_d.get("action") == "return_counter_same_as_original":
        line = "TwP: counter=original (accept)"
    elif last_ctr_d.get("reason") == "back_to_incoming":
        line = "TwP: counter back→Incoming"
    elif action == "TwP":
        if mode_src in {"risk_twp", "ai_risk_twp"} or "risk" in str(best_d.get("reason", "")).lower():
            line = f"TwP: risk {label}"
        elif best_d.get("unlocked_action") or best_d.get("twp_t1", {}).get("unlocks"):
            line = f"TwP: unlock {label}"
        else:
            line = f"TwP: {label}"
    elif action == "Incoming TwP":
        line = f"TwP: pending HP {label}"
    elif action == "TwB":
        line = f"TwP: none (BEST=TwB)"
    elif skip:
        line = f"TwP: none ({skip[0]})"
    elif mode:
        line = f"TwP: none (mode={mode})"

    explain = ""
    proposal = best_d.get("proposal") or best_d.get("twp_proposal") or best_d.get("candidate")
    if counter_active:
        orig = counter.get("original_proposal")
        if isinstance(orig, Mapping) and orig:
            explain = format_twp_offer_explanation(game, orig, for_human=False)
            if counter_draft_label:
                explain = f"Counter {counter_draft_label}" + (f" | was {explain}" if explain else "")
    elif isinstance(proposal, Mapping) and proposal:
        explain = format_twp_offer_explanation(game, proposal, for_human=False)

    rules = get_human_twp_auto_rules(game)
    decline_bag = getattr(game, "human_twp_decline_patterns", None)
    decline_n = len(decline_bag) if isinstance(decline_bag, Mapping) else 0

    # T11: prefer structured empty diagnosis / last executed Events line
    empty_diag = list(getattr(game, "last_twp_empty_diagnosis", None) or [])
    live_need = list(getattr(game, "last_twp_live_need", None) or [])
    exec_line = getattr(game, "last_twp_executed_events_line", None)
    if exec_line and action == "TwP":
        line = str(exec_line)
    elif not action and empty_diag and (not skip or skip == ["no_mutual"]):
        line = f"TwP: none ({empty_diag[0]})"

    snap: Dict[str, Any] = {
        "stage": "T4+T10+T11",
        "human_twp_mode": mode,
        "line": line,
        "explain": explain,
        "best_action_kind": action or None,
        "best_action_mode": mode_src or None,
        "best_action_label": label if action else None,
        "skip_reasons": list(skip)[:8],
        "empty_diagnosis": list(empty_diag)[:8],
        "live_need": list(live_need)[:5],
        "support_action": getattr(game, "last_twp_support_action", None),
        "executed_events_line": exec_line,
        "policy_status": policy_d.get("status"),
        "policy_reason": policy_d.get("reason"),
        "policy_accepted": policy_d.get("accepted"),
        "auto_rules_count": len(rules),
        "auto_rules": list(rules)[:12],
        "decline_patterns_active": decline_n,
        "package_pick": best_d.get("package_pick"),
        "twp_t1": dict(best_d.get("twp_t1") or {}) if isinstance(best_d.get("twp_t1"), Mapping) else {},
        "twp_t2": dict(best_d.get("twp_t2") or {}) if isinstance(best_d.get("twp_t2"), Mapping) else {},
        "twp_t5": dict(best_d.get("twp_t5") or {}) if isinstance(best_d.get("twp_t5"), Mapping) else {},
        # T10 dig-in
        "twp_t10": {
            "counter_active": counter_active,
            "draft_label": counter_draft_label or None,
            "original_key": list(counter.get("original_key") or []) if counter_active else None,
            "last_result_action": last_ctr_d.get("action") or last_ctr_d.get("reason"),
            "last_accepted": last_ctr_d.get("accepted"),
            "last_reason": last_ctr_d.get("reason"),
        },
        "counter_active": counter_active,
        "last_twp_counter_action": last_ctr_d.get("action") or last_ctr_d.get("reason"),
    }
    # H-D: human outgoing TwP offer audit strip
    try:
        from core.human_twp_offer_audit import human_offer_debug_strip

        human_offer = human_offer_debug_strip(game)
        if human_offer:
            snap["human_offer"] = human_offer
            # Prefer human-offer line when more recent / informative than AI none
            ho_line = str(human_offer.get("line") or "")
            grant = human_offer.get("grant") if isinstance(human_offer.get("grant"), Mapping) else {}
            if ho_line and (
                grant.get("executed")
                or grant.get("mode") == "cancelled"
                or human_offer.get("scan_id")
            ):
                # Keep AI BEST line if it is an active TwP; else surface HP offer
                if action not in {"TwP", "Incoming TwP"} or "none" in str(line).lower():
                    snap["line"] = f"TwP: {ho_line}" if not ho_line.startswith("HP") else f"TwP: {ho_line}"
                    # Avoid double "TwP: TwP:"
                    if snap["line"].startswith("TwP: TwP:"):
                        snap["line"] = snap["line"].replace("TwP: TwP:", "TwP:", 1)
    except Exception:
        pass
    try:
        snap["stage"] = "T4+T10+T11+H"
    except Exception:
        pass
    return snap


def format_twp_debug_rows(snapshot: Optional[Mapping[str, Any]], *, max_rows: int = 3) -> List[str]:
    """PLAN-panel lines from a TwP debug snapshot."""
    if not isinstance(snapshot, Mapping) or not snapshot:
        return []
    rows = [str(snapshot.get("line") or "TwP: -")]
    explain = str(snapshot.get("explain") or "")
    if explain:
        rows.append(_fit(explain, 56))
    # H-D: second row for human offer detail when present
    human_offer = snapshot.get("human_offer") if isinstance(snapshot.get("human_offer"), Mapping) else {}
    if human_offer and len(rows) < max_rows:
        ho = str(human_offer.get("line") or "")
        if ho and ho not in rows[0]:
            rows.append(_fit(ho, 56))
        elif human_offer.get("declined") and len(rows) < max_rows:
            d0 = (human_offer.get("declined") or [None])[0]
            if isinstance(d0, Mapping) and d0.get("id"):
                rows.append(_fit(f"HP decline P{d0.get('id')}: {d0.get('code')}", 56))
    t10 = snapshot.get("twp_t10") if isinstance(snapshot.get("twp_t10"), Mapping) else {}
    if t10.get("counter_active") and t10.get("draft_label") and len(rows) < max_rows:
        rows.append(_fit(f"T10 draft {t10.get('draft_label')}", 56))
    elif t10.get("last_result_action") and not t10.get("counter_active") and len(rows) < max_rows:
        rows.append(_fit(f"T10 last: {t10.get('last_result_action')}", 56))
    skip = list(snapshot.get("skip_reasons") or [])
    if skip and "none" in str(snapshot.get("line", "")).lower() and len(rows) < max_rows:
        rows.append(_fit(f"Skip: {skip[0]}", 56))
    elif snapshot.get("policy_reason") and snapshot.get("best_action_kind") == "Incoming TwP":
        if len(rows) < max_rows:
            rows.append(_fit(f"Policy: {snapshot.get('policy_reason')}", 56))
    mode = snapshot.get("human_twp_mode")
    if mode and mode != "manual" and len(rows) < max_rows:
        rows.append(f"HP mode: {mode}" + (f" rules={snapshot.get('auto_rules_count', 0)}" if mode == "auto" else ""))
    return rows[:max_rows]


def refresh_twp_debug_on_game(game: Any) -> Dict[str, Any]:
    """Recompute last_twp_debug snapshot (T10 / PLAN)."""
    try:
        snap = build_twp_debug_snapshot(game)
        setattr(game, "last_twp_debug", snap)
        return snap
    except Exception:
        return {}


def record_twp_skip_reason(game: Any, reason: str) -> None:
    """Append a short skip reason for debug (deduped, capped)."""
    text = str(reason or "").strip()
    if not text:
        return
    try:
        bag = list(getattr(game, "last_twp_skip_reasons", None) or [])
        if text not in bag:
            bag.append(text)
        setattr(game, "last_twp_skip_reasons", bag[-12:])
    except Exception:
        pass


def clear_twp_skip_reasons(game: Any) -> None:
    try:
        setattr(game, "last_twp_skip_reasons", [])
    except Exception:
        pass


def refresh_twp_debug(game: Any) -> Dict[str, Any]:
    """Build snapshot, store on game, return it."""
    snap = build_twp_debug_snapshot(game)
    try:
        setattr(game, "last_twp_debug", dict(snap))
    except Exception:
        pass
    return snap


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


def _hp_trade_legs(data: Mapping[str, Any]) -> Tuple[Optional[int], int, Optional[int], int]:
    """From proposal dict: HP give/receive indices and counts.

    AI active gives X / receives Y  ⇒  HP receives X / gives Y.
    """
    try:
        # Default AI→HP: human is counterparty
        if bool(data.get("counterparty_is_human")) or not bool(data.get("active_player_is_human")):
            hp_give_idx = int(data.get("active_receive_index"))
            hp_give_n = int(data.get("active_receive_count") or 1)
            hp_recv_idx = int(data.get("active_give_index"))
            hp_recv_n = int(data.get("active_give_count") or 1)
            return hp_give_idx, hp_give_n, hp_recv_idx, hp_recv_n
        # Human is active (rare for this resolver)
        hp_give_idx = int(data.get("active_give_index"))
        hp_give_n = int(data.get("active_give_count") or 1)
        hp_recv_idx = int(data.get("active_receive_index"))
        hp_recv_n = int(data.get("active_receive_count") or 1)
        return hp_give_idx, hp_give_n, hp_recv_idx, hp_recv_n
    except Exception:
        return None, 0, None, 0


def _human_player_from_proposal(game: Any, data: Mapping[str, Any]) -> Optional[Any]:
    for key in ("counterparty_id", "active_player_id"):
        p = _player_by_id(game, data.get(key))
        if p is not None and bool(getattr(p, "is_human", False)):
            return p
    # Fallback: any human on game
    for p in list(getattr(game, "players", []) or []):
        if bool(getattr(p, "is_human", False)):
            return p
    return None


def _hp_keep_ditch_missing(
    game: Any,
    player: Any,
) -> Tuple[List[int], List[int], List[int], str]:
    keep = [0, 0, 0, 0, 0]
    ditch = [0, 0, 0, 0, 0]
    missing = [0, 0, 0, 0, 0]
    primary = "unknown"
    try:
        from core.ai_hand_risk import build_hand_risk_profile

        risk = build_hand_risk_profile(game, player)
        keep = [max(0, int(x or 0)) for x in list(risk.get("keep") or [])[:5]]
        ditch = [max(0, int(x or 0)) for x in list(risk.get("ditch") or [])[:5]]
        while len(keep) < 5:
            keep.append(0)
        while len(ditch) < 5:
            ditch.append(0)
    except Exception:
        pass
    try:
        from core.player_trade import build_trade_profile

        profile = build_trade_profile(game, player)
        missing = [max(0, int(x or 0)) for x in list(profile.primary_missing)[:5]]
        while len(missing) < 5:
            missing.append(0)
        primary = str(profile.primary_action or "unknown")
        # Prefer profile keep/ditch when risk was empty
        if sum(keep) + sum(ditch) == 0:
            keep = [max(0, int(x or 0)) for x in list(profile.keep_resource_vector)[:5]]
            ditch = [max(0, int(x or 0)) for x in list(profile.ditch_resource_vector)[:5]]
            while len(keep) < 5:
                keep.append(0)
            while len(ditch) < 5:
                ditch.append(0)
    except Exception:
        pass
    return keep, ditch, missing, primary


def _fit(text: str, n: int) -> str:
    s = str(text or "")
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"
