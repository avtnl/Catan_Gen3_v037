"""H-A: Human TwP outgoing-offer scan audit (HP→AI).

Instrumentation helpers only — does not change willingness math.
See ``docs/human_twp_offer_audit_plan.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Keep aligned with core.player_trade.RESOURCE_ABBR / RESOURCE_NAMES
_RESOURCE_ABBR: Tuple[str, str, str, str, str] = ("Wh", "O", "Wd", "B", "Sh")
_RESOURCE_NAMES: Tuple[str, str, str, str, str] = (
    "Wheat",
    "Ore",
    "Wood",
    "Brick",
    "Sheep",
)

# Cap package-level decline dig-in per AI
MAX_DECLINED_PACKAGES_PER_AI: int = 3

# Reason codes (plan §4.4)
REASON_SKIPPED_SELF = "skipped_self"
REASON_SKIPPED_HUMAN = "skipped_human"
REASON_DECLINED_CANNOT_PAY = "declined_cannot_pay"
REASON_DECLINED_WILLINGNESS = "declined_willingness"
REASON_DECLINED_NO_OFFER_APPETITE = "declined_no_offer_appetite"
REASON_DECLINED_NO_ACCEPT_APPETITE = "declined_no_accept_appetite"
REASON_DECLINED_SCORE_FLOOR = "declined_score_floor"
REASON_DECLINED_SAME_RESOURCE = "declined_same_resource_both_sides"
REASON_DECLINED_EMPTY_PACKAGE = "declined_empty_package"
REASON_DECLINED_T9_FREEZE = "declined_t9_endgame_freeze"
REASON_ACCEPTED = "accepted"
REASON_ERROR_PROFILE = "error_profile"
REASON_SCAN_NOTHING_OFFERED = "nothing_offered"
REASON_SCAN_NOTHING_REQUESTED = "nothing_requested"
REASON_SCAN_PROPOSER_LACKS = "proposer_lacks_exact_offer_cards"
REASON_SCAN_NO_OFFER_WC_ALLOWED = "offer_wildcard_has_no_allowed_resources"
REASON_SCAN_NO_REQUEST_WC_ALLOWED = "request_wildcard_has_no_allowed_resources"
REASON_SCAN_PROPOSER_NOT_FOUND = "proposer_not_found"
REASON_SCAN_T9_FREEZE_PROPOSER = "t9_freeze_proposer_potential_winner"


def _list5_int(values: Optional[Sequence[Any]], default: int = 0) -> List[int]:
    out: List[int] = []
    raw = list(values or [])
    for i in range(5):
        try:
            out.append(int(raw[i] if i < len(raw) else default) or 0)
        except Exception:
            out.append(int(default))
    return out


def format_vector_compact(values: Optional[Sequence[Any]]) -> str:
    """e.g. [1,0,0,0,0] → '1Wh'; multi → '1Wh+2O'."""
    vec = _list5_int(values, default=0)
    parts = [f"{vec[i]}{_RESOURCE_ABBR[i]}" for i in range(5) if vec[i] > 0]
    return "+".join(parts) if parts else "0"


def human_twp_offer_label_compact(
    offer_exact: Optional[Sequence[Any]] = None,
    request_exact: Optional[Sequence[Any]] = None,
    *,
    offer_wildcard_count: int = 0,
    request_wildcard_count: int = 0,
) -> str:
    """Compact label: '1Wh→1O' or '1Wh+?→1O'."""
    left = format_vector_compact(offer_exact)
    right = format_vector_compact(request_exact)
    ow = max(0, int(offer_wildcard_count or 0))
    rw = max(0, int(request_wildcard_count or 0))
    if ow > 0:
        left = f"{left}+?" if left != "0" else f"{ow}?"
    if rw > 0:
        right = f"{right}+?" if right != "0" else f"{rw}?"
    return f"{left}→{right}"


def classify_human_twp_willingness_reason(
    reason_text: str,
    *,
    willing: bool,
) -> str:
    """Map free-text willingness reason to a stable reason_code."""
    if willing:
        return REASON_ACCEPTED
    text = str(reason_text or "").strip().lower()
    if not text:
        return REASON_DECLINED_WILLINGNESS
    if "does not want to offer" in text or "not want to offer" in text:
        return REASON_DECLINED_NO_OFFER_APPETITE
    if "does not want the offered" in text or "not want the offered" in text:
        return REASON_DECLINED_NO_ACCEPT_APPETITE
    if "score too low" in text or "score floor" in text:
        return REASON_DECLINED_SCORE_FLOOR
    if "same resource" in text or "both sides" in text:
        return REASON_DECLINED_SAME_RESOURCE
    if "empty" in text and "package" in text:
        return REASON_DECLINED_EMPTY_PACKAGE
    if "cannot pay" in text or "lacks" in text or "lack cards" in text:
        return REASON_DECLINED_CANNOT_PAY
    if "freeze" in text or "potential winner" in text or "endgame_twp" in text:
        return REASON_DECLINED_T9_FREEZE
    return REASON_DECLINED_WILLINGNESS


def profile_digest_from_trade_profile(profile: Any) -> Optional[Dict[str, Any]]:
    """Compact profile dig-in for exportability (H-A optional)."""
    if profile is None:
        return None
    dig: Dict[str, Any] = {}
    try:
        dig["primary_action"] = str(getattr(profile, "primary_action", None) or "") or None
    except Exception:
        dig["primary_action"] = None
    for attr, key in (
        ("primary_missing", "demand"),
        ("accept_appetite", "accept_appetite"),
        ("offer_appetite", "offer_appetite"),
        ("ditch_resource_vector", "ditch"),
        ("clear_surplus", "clear_surplus"),
        ("keep_resource_vector", "keep"),
        ("hand", "hand"),
    ):
        try:
            raw = getattr(profile, attr, None)
            if raw is None:
                dig[key] = None
            else:
                dig[key] = _list5_int(raw, default=0)
        except Exception:
            dig[key] = None
    # supply-style: prefer clear_surplus / ditch max per resource if present
    try:
        ditch = dig.get("ditch") or [0, 0, 0, 0, 0]
        clear = dig.get("clear_surplus") or [0, 0, 0, 0, 0]
        dig["supply"] = [max(int(ditch[i] or 0), int(clear[i] or 0)) for i in range(5)]
    except Exception:
        dig["supply"] = None
    return dig


def build_human_twp_offer_request(
    game: Any,
    *,
    proposer_id: int,
    proposer_color: str = "",
    proposer_hand: Optional[Sequence[Any]] = None,
    offer_exact: Optional[Sequence[Any]] = None,
    request_exact: Optional[Sequence[Any]] = None,
    offer_wildcard_count: int = 0,
    request_wildcard_count: int = 0,
    offer_wildcard_allowed: Optional[Sequence[Any]] = None,
    request_wildcard_allowed: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Build the request snapshot for a scan."""
    offer = _list5_int(offer_exact, default=0)
    request = _list5_int(request_exact, default=0)
    hand = _list5_int(proposer_hand, default=0)

    def _flags5(flags: Optional[Sequence[Any]]) -> Optional[List[bool]]:
        if flags is None:
            return None
        out: List[bool] = []
        raw = list(flags)
        for i in range(5):
            try:
                out.append(bool(raw[i]) if i < len(raw) else False)
            except Exception:
                out.append(False)
        return out

    try:
        rnd = int(getattr(game, "round", 0) or 0)
    except Exception:
        rnd = 0
    try:
        turn = int(getattr(game, "turn", 0) or 0)
    except Exception:
        turn = 0
    return {
        "proposer_id": int(proposer_id),
        "proposer_color": str(proposer_color or ""),
        "round": rnd,
        "turn": turn,
        "phase": str(getattr(game, "phase", "") or ""),
        "state": str(getattr(game, "state", "") or ""),
        "offer_exact": offer,
        "request_exact": request,
        "offer_wildcard_count": max(0, int(offer_wildcard_count or 0)),
        "request_wildcard_count": max(0, int(request_wildcard_count or 0)),
        "offer_wildcard_allowed": _flags5(offer_wildcard_allowed),
        "request_wildcard_allowed": _flags5(request_wildcard_allowed),
        "proposer_hand": hand,
        "label_compact": human_twp_offer_label_compact(
            offer,
            request,
            offer_wildcard_count=offer_wildcard_count,
            request_wildcard_count=request_wildcard_count,
        ),
        "resource_order": list(_RESOURCE_NAMES),
    }


def make_ai_evaluation(
    *,
    counterparty_id: int,
    counterparty_color: str = "",
    outcome: str,
    reason_code: str,
    reason_text: str = "",
    score: Optional[float] = None,
    hand: Optional[Sequence[Any]] = None,
    can_pay_request: bool = False,
    packages_tried: int = 0,
    best_package: Optional[Mapping[str, Any]] = None,
    declined_packages: Optional[Sequence[Mapping[str, Any]]] = None,
    profile_digest: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """One per-AI evaluation row."""
    declined = list(declined_packages or [])[: int(MAX_DECLINED_PACKAGES_PER_AI)]
    return {
        "counterparty_id": int(counterparty_id),
        "counterparty_color": str(counterparty_color or ""),
        "outcome": str(outcome or "declined"),
        "reason_code": str(reason_code or REASON_DECLINED_WILLINGNESS),
        "reason_text": str(reason_text or ""),
        "score": (round(float(score), 4) if score is not None else None),
        "hand": _list5_int(hand, default=0),
        "can_pay_request": bool(can_pay_request),
        "packages_tried": max(0, int(packages_tried or 0)),
        "best_package": dict(best_package) if isinstance(best_package, Mapping) else None,
        "declined_packages": [dict(x) for x in declined if isinstance(x, Mapping)],
        "profile_digest": dict(profile_digest) if isinstance(profile_digest, Mapping) else None,
    }


def build_human_twp_offer_scan(
    *,
    request: Mapping[str, Any],
    evaluations: Sequence[Mapping[str, Any]],
    accepted_options: Sequence[Mapping[str, Any]],
    scan_reason: str,
    scan_id: str = "",
    skipped_human_counterparties: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Assemble the full offer_scan object."""
    evals = [dict(e) for e in evaluations if isinstance(e, Mapping)]
    accepted = [dict(a) for a in accepted_options if isinstance(a, Mapping)]
    accepted_ids: List[int] = []
    declined_ids: List[int] = []
    for e in evals:
        try:
            cid = int(e.get("counterparty_id", 0) or 0)
        except Exception:
            continue
        if cid <= 0:
            continue
        outcome = str(e.get("outcome") or "")
        if outcome == "accepted":
            if cid not in accepted_ids:
                accepted_ids.append(cid)
        elif outcome == "declined":
            if cid not in declined_ids:
                declined_ids.append(cid)
    n_ai = sum(1 for e in evals if str(e.get("outcome")) != "skipped")
    # Prefer counting non-skipped seats
    n_considered = 0
    for e in evals:
        if str(e.get("outcome")) in {"accepted", "declined"}:
            n_considered += 1
    ok = bool(accepted)
    sid = str(scan_id or "").strip()
    if not sid:
        try:
            pid = int((request or {}).get("proposer_id", 0) or 0)
            r = int((request or {}).get("round", 0) or 0)
            t = int((request or {}).get("turn", 0) or 0)
            sid = f"R{r}T{t}_P{pid}"
        except Exception:
            sid = "scan"
    return {
        "scan_id": sid,
        "request": dict(request) if isinstance(request, Mapping) else {},
        "evaluations": evals,
        "accepted": accepted,
        "accepted_counterparty_ids": accepted_ids,
        "declined_counterparty_ids": declined_ids,
        "skipped_human_counterparties": [
            int(x) for x in list(skipped_human_counterparties or []) if x is not None
        ],
        "summary": {
            "n_ai_considered": int(n_considered),
            "n_evaluations": len(evals),
            "n_accepted_options": len(accepted),
            "n_accepted_ais": len(accepted_ids),
            "n_declined_ais": len(declined_ids),
            "ok": ok,
            "scan_reason": str(scan_reason or ("options_found" if ok else "no_willing_counterparty")),
        },
    }


def empty_offer_scan_for_early_exit(
    game: Any,
    *,
    proposer_id: int = 0,
    proposer_color: str = "",
    proposer_hand: Optional[Sequence[Any]] = None,
    offer_exact: Optional[Sequence[Any]] = None,
    request_exact: Optional[Sequence[Any]] = None,
    offer_wildcard_count: int = 0,
    request_wildcard_count: int = 0,
    offer_wildcard_allowed: Optional[Sequence[Any]] = None,
    request_wildcard_allowed: Optional[Sequence[Any]] = None,
    scan_reason: str,
    evaluations: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Minimal offer_scan when scan aborts before the AI loop."""
    req = build_human_twp_offer_request(
        game,
        proposer_id=proposer_id,
        proposer_color=proposer_color,
        proposer_hand=proposer_hand,
        offer_exact=offer_exact,
        request_exact=request_exact,
        offer_wildcard_count=offer_wildcard_count,
        request_wildcard_count=request_wildcard_count,
        offer_wildcard_allowed=offer_wildcard_allowed,
        request_wildcard_allowed=request_wildcard_allowed,
    )
    return build_human_twp_offer_scan(
        request=req,
        evaluations=list(evaluations or []),
        accepted_options=[],
        scan_reason=scan_reason,
    )


def next_scan_id(game: Any, proposer_id: int) -> str:
    """Monotonic scan id on game if available."""
    try:
        seq = int(getattr(game, "_human_twp_offer_scan_seq", 0) or 0) + 1
        setattr(game, "_human_twp_offer_scan_seq", seq)
    except Exception:
        seq = 1
    try:
        r = int(getattr(game, "round", 0) or 0)
        t = int(getattr(game, "turn", 0) or 0)
    except Exception:
        r, t = 0, 0
    return f"R{r}T{t}_P{int(proposer_id)}_{seq:03d}"


# H-B: how many past scans to keep on the game
HUMAN_TWP_OFFER_SCAN_HISTORY_MAX: int = 12


def persist_human_twp_offer_scan(
    game: Any,
    offer_scan: Optional[Mapping[str, Any]],
    *,
    history_max: int = HUMAN_TWP_OFFER_SCAN_HISTORY_MAX,
) -> Optional[Dict[str, Any]]:
    """H-B: store last scan on game + append capped history.

    Returns a plain dict copy of the scan, or None if nothing to store.
    """
    if game is None or not isinstance(offer_scan, Mapping) or not offer_scan:
        return None
    try:
        snap = dict(offer_scan)
    except Exception:
        return None
    try:
        setattr(game, "last_human_twp_offer_scan", snap)
    except Exception:
        pass
    try:
        hist = list(getattr(game, "human_twp_offer_scan_history", None) or [])
        # Prefer unique by scan_id: replace if same id re-persisted
        sid = str(snap.get("scan_id") or "")
        if sid:
            hist = [h for h in hist if not (isinstance(h, Mapping) and str(h.get("scan_id") or "") == sid)]
        hist.append(snap)
        cap = max(1, int(history_max or HUMAN_TWP_OFFER_SCAN_HISTORY_MAX))
        setattr(game, "human_twp_offer_scan_history", hist[-cap:])
    except Exception:
        pass
    # Ensure seq field exists for next_scan_id continuity
    try:
        if not hasattr(game, "_human_twp_offer_scan_seq"):
            setattr(game, "_human_twp_offer_scan_seq", 0)
    except Exception:
        pass
    return snap


# ── H-C: grant / selection audit ─────────────────────────────────────────────

SELECTION_HUMAN = "human_selected"
SELECTION_SOLE = "sole_option"
SELECTION_RANDOM_TIES = "random_among_ties"
SELECTION_NONE = "none"
SELECTION_CANCELLED = "cancelled"


def _vectors5_equal(a: Any, b: Any) -> bool:
    try:
        av = _list5_int(a, default=0)
        bv = _list5_int(b, default=0)
        return av == bv
    except Exception:
        return False


def _option_vectors(option: Mapping[str, Any]) -> Tuple[List[int], List[int], int]:
    gives = option.get("proposer_gives") or option.get("human_gives") or [0, 0, 0, 0, 0]
    gets = (
        option.get("counterparty_gives")
        or option.get("human_receives")
        or [0, 0, 0, 0, 0]
    )
    try:
        cid = int(option.get("counterparty_id", 0) or 0)
    except Exception:
        cid = 0
    return _list5_int(gives, default=0), _list5_int(gets, default=0), cid


def candidates_from_scan(scan: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize accepted options from a scan for grant dig-in."""
    if not isinstance(scan, Mapping):
        return []
    out: List[Dict[str, Any]] = []
    for raw in list(scan.get("accepted") or []):
        if not isinstance(raw, Mapping):
            continue
        gives, gets, cid = _option_vectors(raw)
        try:
            score = float(raw.get("score")) if raw.get("score") is not None else None
        except Exception:
            score = None
        out.append(
            {
                "counterparty_id": cid,
                "proposer_gives": gives,
                "counterparty_gives": gets,
                "score": score,
                "reason_text": str(raw.get("reason") or raw.get("reason_text") or ""),
            }
        )
    return out


def build_human_twp_offer_grant(
    game: Any,
    *,
    option: Mapping[str, Any],
    scan: Optional[Mapping[str, Any]] = None,
    selection_mode: Optional[str] = None,
    executed: bool = False,
    execute_ok: Optional[bool] = None,
    execute_reason: str = "",
) -> Dict[str, Any]:
    """H-C: grant/selection record for a human TwP OKY (or cancel).

    Default selection for multi-accept is ``human_selected`` (GUI pick). Sole
    accept uses ``sole_option``. Does not invent random auto-grant.
    """
    scan = scan if isinstance(scan, Mapping) else None
    if scan is None and game is not None:
        try:
            raw = getattr(game, "last_human_twp_offer_scan", None)
            if isinstance(raw, Mapping):
                scan = raw
        except Exception:
            scan = None

    candidates = candidates_from_scan(scan)
    gives, gets, selected_cid = _option_vectors(option if isinstance(option, Mapping) else {})
    try:
        opt_score = float(option.get("score")) if option.get("score") is not None else None
    except Exception:
        opt_score = None

    # If selected package not in candidates, still record it (stale scan / mismatch)
    selected = None
    if selected_cid > 0 or any(gives) or any(gets):
        selected = {
            "counterparty_id": selected_cid,
            "proposer_gives": gives,
            "counterparty_gives": gets,
            "score": opt_score,
        }

    scan_mismatch = False
    if selected is not None and candidates:
        matched = False
        for c in candidates:
            if (
                int(c.get("counterparty_id") or 0) == selected_cid
                and _vectors5_equal(c.get("proposer_gives"), gives)
                and _vectors5_equal(c.get("counterparty_gives"), gets)
            ):
                matched = True
                if selected.get("score") is None and c.get("score") is not None:
                    selected["score"] = c.get("score")
                break
        if not matched:
            # Match by counterparty only
            for c in candidates:
                if int(c.get("counterparty_id") or 0) == selected_cid:
                    matched = True
                    break
            if not matched:
                scan_mismatch = True
    elif selected is not None and scan is not None and not candidates:
        scan_mismatch = True

    n_accept = len(candidates)
    if not n_accept and selected is not None:
        # Execute without prior scan still records selection
        n_accept = 1

    mode = str(selection_mode or "").strip()
    if not mode:
        if selected is None:
            mode = SELECTION_NONE
        elif n_accept <= 1:
            mode = SELECTION_SOLE
        else:
            mode = SELECTION_HUMAN

    why_not: List[Dict[str, Any]] = []
    for c in candidates:
        cid = int(c.get("counterparty_id") or 0)
        if cid <= 0 or cid == selected_cid:
            continue
        sc = c.get("score")
        sc_s = f"score={sc}" if sc is not None else "score=?"
        if mode == SELECTION_HUMAN:
            note = f"not_selected_by_human; {sc_s}"
        elif mode == SELECTION_SOLE:
            note = f"not_sole_option; {sc_s}"
        else:
            note = f"not_selected; {sc_s}"
        why_not.append({"counterparty_id": cid, "note": note})

    try:
        rnd = int(getattr(game, "round", 0) or 0) if game is not None else 0
        turn = int(getattr(game, "turn", 0) or 0) if game is not None else 0
    except Exception:
        rnd, turn = 0, 0

    scan_id = ""
    if isinstance(scan, Mapping):
        scan_id = str(scan.get("scan_id") or "")
    label = ""
    try:
        if isinstance(scan, Mapping):
            req = scan.get("request") or {}
            if isinstance(req, Mapping):
                label = str(req.get("label_compact") or "")
        if not label:
            label = human_twp_offer_label_compact(gives, gets)
    except Exception:
        label = human_twp_offer_label_compact(gives, gets)

    try:
        proposer_id = int(
            (option or {}).get("proposer_id")
            or (option or {}).get("active_player_id")
            or ((scan or {}).get("request") or {}).get("proposer_id")
            or 0
        )
    except Exception:
        proposer_id = 0

    grant: Dict[str, Any] = {
        "scan_id": scan_id,
        "selection_mode": mode,
        "selected": selected,
        "candidates_accepted": candidates,
        "selection_detail": {
            "human_ui": mode in {SELECTION_HUMAN, SELECTION_SOLE},
            "rank_by": "human_click" if mode == SELECTION_HUMAN else (
                "score_desc" if mode == SELECTION_SOLE else "none"
            ),
            "tie_group": None,
            "rng_seed": None,
            "why_not_others": why_not,
            "scan_mismatch": bool(scan_mismatch),
        },
        "executed": bool(executed),
        "execute_ok": execute_ok if execute_ok is None else bool(execute_ok),
        "execute_reason": str(execute_reason or ""),
        "round": rnd,
        "turn": turn,
        "proposer_id": proposer_id,
        "label_compact": label,
        "events_line": "",
    }
    grant["events_line"] = format_human_twp_offer_grant_events_line(grant)
    return grant


def format_human_twp_offer_grant_events_line(grant: Mapping[str, Any]) -> str:
    """Public/Events dig-in: ``TwP: P3 1Wh→1O with P2 (HP offer; sole accept)``."""
    if not isinstance(grant, Mapping):
        return ""
    mode = str(grant.get("selection_mode") or "")
    label = str(grant.get("label_compact") or "")
    try:
        pid = int(grant.get("proposer_id") or 0)
    except Exception:
        pid = 0
    selected = grant.get("selected") if isinstance(grant.get("selected"), Mapping) else None
    cid = 0
    if selected:
        try:
            cid = int(selected.get("counterparty_id") or 0)
        except Exception:
            cid = 0
        if not label:
            label = human_twp_offer_label_compact(
                selected.get("proposer_gives"),
                selected.get("counterparty_gives"),
            )
    if mode == SELECTION_CANCELLED:
        n = len(list(grant.get("candidates_accepted") or []))
        return f"DBG: HP TwP cancelled ({n} accept(s) on scan)"
    if mode == SELECTION_NONE or selected is None:
        return "DBG: HP TwP grant none"
    who = f"P{pid}" if pid else "HP"
    with_p = f" with P{cid}" if cid else ""
    n_cand = len(list(grant.get("candidates_accepted") or []))
    if mode == SELECTION_SOLE or n_cand <= 1:
        how = "sole accept"
    elif mode == SELECTION_RANDOM_TIES:
        how = "random among ties"
    else:
        others = [
            int(c.get("counterparty_id") or 0)
            for c in list(grant.get("candidates_accepted") or [])
            if isinstance(c, Mapping) and int(c.get("counterparty_id") or 0) != cid
        ]
        if others:
            how = "chosen among " + ",".join(f"P{x}" for x in [cid] + others if x) + "; human pick"
        else:
            how = "human pick"
    ok = grant.get("execute_ok")
    if grant.get("executed") and ok is False:
        why = str(grant.get("execute_reason") or "failed")
        return f"TwP: {who} {label}{with_p} (HP offer; {how}; execute failed: {why})"
    return f"TwP: {who} {label}{with_p} (HP offer; {how})"


def persist_human_twp_offer_grant(
    game: Any,
    grant: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """H-C: store last grant on game."""
    if game is None or not isinstance(grant, Mapping) or not grant:
        return None
    try:
        snap = dict(grant)
    except Exception:
        return None
    try:
        setattr(game, "last_human_twp_offer_grant", snap)
    except Exception:
        pass
    return snap


# ── H-D: cancel + debug strip ────────────────────────────────────────────────


def build_human_twp_offer_cancel_grant(
    game: Any,
    *,
    reason: str = "panel_closed",
) -> Optional[Dict[str, Any]]:
    """H-D: grant record when HP closes TwP panel without OKY after a scan.

    Returns None if there is no scan to cancel, or if last grant already
    executed successfully for the same scan.
    """
    try:
        scan = getattr(game, "last_human_twp_offer_scan", None)
    except Exception:
        scan = None
    if not isinstance(scan, Mapping) or not scan:
        return None

    scan_id = str(scan.get("scan_id") or "")
    try:
        prev = getattr(game, "last_human_twp_offer_grant", None)
        if (
            isinstance(prev, Mapping)
            and prev.get("executed")
            and prev.get("execute_ok")
            and str(prev.get("scan_id") or "") == scan_id
            and scan_id
        ):
            return None
        # Already cancelled this scan
        if (
            isinstance(prev, Mapping)
            and str(prev.get("selection_mode") or "") == SELECTION_CANCELLED
            and str(prev.get("scan_id") or "") == scan_id
            and scan_id
        ):
            return None
    except Exception:
        pass

    candidates = candidates_from_scan(scan)
    try:
        rnd = int(getattr(game, "round", 0) or 0)
        turn = int(getattr(game, "turn", 0) or 0)
    except Exception:
        rnd, turn = 0, 0
    try:
        proposer_id = int((scan.get("request") or {}).get("proposer_id") or 0)
    except Exception:
        proposer_id = 0
    label = ""
    try:
        label = str((scan.get("request") or {}).get("label_compact") or "")
    except Exception:
        label = ""

    grant: Dict[str, Any] = {
        "scan_id": scan_id,
        "selection_mode": SELECTION_CANCELLED,
        "selected": None,
        "candidates_accepted": candidates,
        "selection_detail": {
            "human_ui": True,
            "rank_by": "none",
            "tie_group": None,
            "rng_seed": None,
            "why_not_others": [],
            "scan_mismatch": False,
            "cancel_reason": str(reason or "panel_closed"),
        },
        "executed": False,
        "execute_ok": None,
        "execute_reason": str(reason or "panel_closed"),
        "round": rnd,
        "turn": turn,
        "proposer_id": proposer_id,
        "label_compact": label,
        "events_line": "",
    }
    grant["events_line"] = format_human_twp_offer_grant_events_line(grant)
    return grant


def human_offer_debug_strip(game: Any) -> Dict[str, Any]:
    """Compact human_offer block for last_twp_debug / PLAN dig-in."""
    scan = getattr(game, "last_human_twp_offer_scan", None)
    grant = getattr(game, "last_human_twp_offer_grant", None)
    if not isinstance(scan, Mapping):
        scan = None
    if not isinstance(grant, Mapping):
        grant = None

    if scan is None and grant is None:
        return {}

    label = ""
    scan_id = ""
    accepted_ids: List[int] = []
    declined: List[Dict[str, Any]] = []
    if scan is not None:
        scan_id = str(scan.get("scan_id") or "")
        try:
            label = str((scan.get("request") or {}).get("label_compact") or "")
        except Exception:
            label = ""
        for cid in list(scan.get("accepted_counterparty_ids") or []):
            try:
                accepted_ids.append(int(cid))
            except Exception:
                pass
        for e in list(scan.get("evaluations") or []):
            if not isinstance(e, Mapping):
                continue
            if str(e.get("outcome") or "") != "declined":
                continue
            try:
                declined.append(
                    {
                        "id": int(e.get("counterparty_id") or 0),
                        "code": str(e.get("reason_code") or ""),
                        "text": str(e.get("reason_text") or "")[:48],
                    }
                )
            except Exception:
                pass

    grant_bit = None
    if grant is not None:
        selected = grant.get("selected") if isinstance(grant.get("selected"), Mapping) else None
        to_id = None
        if selected:
            try:
                to_id = int(selected.get("counterparty_id") or 0)
            except Exception:
                to_id = None
        grant_bit = {
            "mode": str(grant.get("selection_mode") or ""),
            "to": to_id,
            "executed": bool(grant.get("executed")),
            "execute_ok": grant.get("execute_ok"),
            "scan_id": str(grant.get("scan_id") or ""),
            "events_line": str(grant.get("events_line") or "")[:80],
        }
        if not label:
            label = str(grant.get("label_compact") or "")

    # One-line summary for PLAN
    line = ""
    if grant_bit and grant_bit.get("mode") == SELECTION_CANCELLED:
        n = len(list((scan or {}).get("accepted") or []) if scan else [])
        line = f"HP offer {label or '?'}: cancelled ({n} accept)"
    elif grant_bit and grant_bit.get("executed") and grant_bit.get("to"):
        line = f"HP offer {label or '?'}: →P{grant_bit['to']} ({grant_bit.get('mode')})"
    elif scan is not None:
        n_acc = len(accepted_ids)
        n_dec = len(declined)
        if n_acc:
            ids = ",".join(f"P{i}" for i in accepted_ids[:4])
            line = f"HP offer {label or '?'}: accept {ids}"
            if n_dec:
                line += f"; decline×{n_dec}"
        else:
            codes = ",".join(
                str(d.get("code") or "")[:18] for d in declined[:2] if d.get("code")
            )
            line = f"HP offer {label or '?'}: no accept"
            if codes:
                line += f" ({codes})"
    else:
        line = "HP offer: -"

    return {
        "scan_id": scan_id or None,
        "label": label or None,
        "accepted_ids": accepted_ids,
        "declined": declined[:6],
        "grant": grant_bit,
        "line": line[:72],
    }


def format_human_twp_offer_scan_dbg_line(scan: Optional[Mapping[str, Any]]) -> str:
    """Optional DBG after FIND: accept/decline summary."""
    if not isinstance(scan, Mapping):
        return ""
    req = scan.get("request") if isinstance(scan.get("request"), Mapping) else {}
    label = str(req.get("label_compact") or "?")
    acc = list(scan.get("accepted_counterparty_ids") or [])
    dec_bits: List[str] = []
    for e in list(scan.get("evaluations") or []):
        if not isinstance(e, Mapping):
            continue
        if str(e.get("outcome") or "") != "declined":
            continue
        try:
            cid = int(e.get("counterparty_id") or 0)
        except Exception:
            continue
        code = str(e.get("reason_code") or "")
        # Shorten common codes for Events
        short = code.replace("declined_", "").replace("cannot_pay", "no cards")
        short = short.replace("no_offer_appetite", "won't give")
        short = short.replace("no_accept_appetite", "won't take")
        dec_bits.append(f"P{cid}({short})" if short else f"P{cid}")
    if acc:
        acc_s = ",".join(f"P{int(x)}" for x in acc)
        line = f"DBG: HP TwP scan {label}: accept {acc_s}"
        if dec_bits:
            line += "; decline " + ",".join(dec_bits[:4])
        return line[:180]
    if dec_bits:
        return f"DBG: HP TwP scan {label}: no accept; " + ",".join(dec_bits[:5])
    return f"DBG: HP TwP scan {label}: no willing counterparty"
