"""gui/gui_execution_debug_panel.py

Display-only Execution Debug panel.

This panel intentionally does not mutate game state.  It only explains the
current execution checkpoint:
- scan legality from viable_action_scanner / ExecutionPhaseManager
- strategic direction persisted by action_planner.py
- actionable intersection of strategy and legality
- best immediate action, wait reason, or forced-flow instruction
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pygame

from gui.gui_constants import COLORS, EXECUTION_DEBUG_PANEL_RECT, Font, POSITIONS, WIN


BUY_DCARD = "Buy development_card"
BUILD_CITY = "Build city"
BUILD_SETTLEMENT = "Build settlement"
BUILD_ROAD = "Build road"
TWB = "TwB"
TWP = "TwP"
SCORE_SECTION_TITLE = "WAYS"
DEBUG_PANEL_BUILD = "S3"  # Execution Debug UI density
MAX_PLANNED_SCAN_STEPS = 5

ACTION_ROWS: Tuple[Tuple[str, str], ...] = (
    (BUILD_CITY, "City"),
    (BUILD_SETTLEMENT, "Settle"),
    (BUILD_ROAD, "Road"),
    (BUY_DCARD, "DCard"),
    (TWB, "TwB"),
)

RESOURCE_NAMES: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RESOURCE_SHORT: Tuple[str, ...] = ("Wh", "O", "Wd", "B", "Sh")

ROBBER_STATES = {"MoveRobber", "RobberMoveRequired", "SetRobber", "StealSelectOpponent"}


# ──────────────────────────────────────────────────────────────────────────────
# Public renderer
# ──────────────────────────────────────────────────────────────────────────────


def handle_execution_debug_panel_click(game: Any, pos: Tuple[int, int]) -> bool:
    """Handle bottom-tab clicks for the Execution Debug panel.

    The panel is display-only: clicks only change which diagnostic layer is
    visible.  They never mutate Game/Board/Player strategy state.
    """
    panel = EXECUTION_DEBUG_PANEL_RECT.copy()
    if not panel.collidepoint(pos):
        return False
    for tab_key, rect in _debug_tab_rects(panel).items():
        if rect.collidepoint(pos):
            try:
                setattr(game, "execution_debug_active_tab", tab_key)
            except Exception:
                pass
            try:
                draw_execution_debug_panel(game)
            except Exception:
                pass
            return True
    return False


def draw_execution_debug_panel(game: Any) -> None:
    """Draw the tabbed Execution Debug panel for the current-turn player.

    Layout contract:
    - Best-Action and cross-layer consistency are always visible at the top.
    - Only one detail layer is shown at a time, selected by bottom tabs.
    - Dice/robber forcing is intentionally not explained here; the button panel
      owns those control-flow affordances.
    """

    panel = EXECUTION_DEBUG_PANEL_RECT.copy()
    pygame.draw.rect(WIN, COLORS["LGRAY"], panel)
    pygame.draw.rect(WIN, COLORS["BLACK"], panel, 1)

    title_font = Font.NORMAL.value["bold"]
    font = Font.SMALL.value["regular"]
    bold = Font.SMALL.value["bold"]

    x = panel.x + 8
    y = panel.y + 5
    line_h = 13  # match Events (Twitter) panel density
    detail_bottom = panel.bottom - 31

    _blit(title_font, f"Execution Debug {DEBUG_PANEL_BUILD}", x, y)

    if game is None:
        y += 20
        _blit(font, "No game object", x, y, COLORS["DGRAY"])
        _update(panel)
        return

    player = _current_player(game)
    if player is None:
        _blit_right(font, "—", panel.right - 8, y + 3, COLORS["DGRAY"])
        y += 20
        _blit(font, "No current player", x, y, COLORS["DGRAY"])
        _update(panel)
        return

    if str(getattr(game, "phase", "")) != "Execution":
        _blit_right(font, "—", panel.right - 8, y + 3, COLORS["DGRAY"])
        y += 20
        _blit(font, "Waiting for Execution phase", x, y, COLORS["DGRAY"])
        _update(panel)
        return

    # G10: if last strategy refresh was for another seat, show seat focus line
    # instead of prior-seat pipeline as "current" (R10T1 class).
    try:
        cur_id = int(getattr(player, "id", -1) or -1)
        status = getattr(game, "last_strategy_context_status", None) or {}
        status_pid = None
        if isinstance(status, Mapping):
            try:
                status_pid = int(status.get("player_id")) if status.get("player_id") is not None else None
            except Exception:
                status_pid = None
        focus_pid = getattr(game, "execution_debug_focus_player_id", None)
        try:
            focus_pid = int(focus_pid) if focus_pid is not None else None
        except Exception:
            focus_pid = None
        stale = bool(getattr(game, "execution_debug_stale_until_refresh", False))
        if status_pid is not None and status_pid != cur_id:
            stale = True
        if focus_pid is not None and focus_pid != cur_id:
            stale = True
        if stale and status_pid != cur_id:
            color = str(getattr(player, "color", "") or "")
            _blit_right(font, f"P{cur_id}", panel.right - 8, y + 3, COLORS["DGRAY"])
            y += 20
            _blit(
                bold,
                _fit_text(f"Seat focus: P{cur_id} {color} (await PLAY/refresh)", 48),
                x,
                y,
                COLORS["DGRAY"],
            )
            y += line_h
            _blit(
                font,
                "Prior-seat dig-in hidden until this seat's strategy runs.",
                x,
                y,
                COLORS["DGRAY"],
            )
            _draw_debug_tab_buttons(panel, _selected_debug_tab(game), {}, font, bold)
            _update(panel)
            return
        if status_pid == cur_id:
            try:
                setattr(game, "execution_debug_stale_until_refresh", False)
            except Exception:
                pass
    except Exception:
        pass

    report = _current_player_report(game, player)
    choices = _current_player_choices(game, player)
    needs = _current_player_needs(game, player)
    direction = _strategy_direction(player)
    bridge = _current_execution_bridge(game, report)
    authority = _project_authority(game, report)
    best_action = _canonical_best_action(game)
    turn_plan = _current_ai_turn_plan(game, report)
    portfolio_audit = _current_way_portfolio_audit(game, report, direction, player)
    active_project = _active_project_from_context(game, report, authority, best_action, direction)
    warnings = _collect_execution_debug_warnings(game, player, report, choices, direction, authority, best_action, turn_plan, active_project, portfolio_audit)
    tab_status = _debug_tab_statuses(warnings, direction, authority, best_action, turn_plan, active_project, portfolio_audit)

    warning_count = len(warnings)
    _blit_right(
        bold if warning_count else font,
        f"!{warning_count}" if warning_count else "OK",
        panel.right - 8,
        y + 3,
        COLORS["RED"] if warning_count else COLORS["GREEN"],
    )
    y += 20

    # Sticky micro-status (S3/S11–S13): Target always visible (S@/C@ multi), BA, way, WARN
    target_sticky = _sticky_target_text(direction, player)
    _blit(
        font,
        _fit_text(target_sticky, 56),
        x,
        y,
        COLORS["BLACK"] if "@" in target_sticky else COLORS["DGRAY"],
    )
    y += line_h

    best_text = _best_action_display_text(game, player, direction, choices, report)
    _blit(
        bold if best_text and best_text != "—" else font,
        _fit_text(f"BA: {best_text or '—'}", 56),
        x,
        y,
        COLORS["DGRAY"] if not best_text or best_text == "—" else COLORS["BLACK"],
    )
    y += line_h

    sticky = _sticky_status_text(direction, portfolio_audit, authority)
    _blit(
        font,
        _fit_text(sticky, 62),
        x,
        y,
        COLORS["BLACK"] if sticky and not sticky.startswith("Way -") else COLORS["DGRAY"],
    )
    y += line_h

    warning_strip = _warning_strip_text(warnings)
    _blit(
        bold if warnings else font,
        _fit_text(warning_strip, 60),
        x,
        y,
        COLORS["RED"] if warnings else COLORS["DGRAY"],
    )
    y += line_h + 4

    pygame.draw.line(WIN, COLORS["DGRAY"], (panel.x + 5, y - 2), (panel.right - 5, y - 2), 1)

    selected = _selected_debug_tab(game)
    if y < detail_bottom - line_h:
        clip_panel = pygame.Rect(panel.x, panel.y, panel.width, max(0, detail_bottom - panel.y))
        if selected == "SCAN":
            _draw_tab_scan(game, player, report, choices, warnings, x, y, line_h, font, bold, clip_panel)
        elif selected == "STR":
            _draw_tab_strategy(game, player, direction, needs, warnings, x, y, line_h, font, bold, clip_panel)
        elif selected == "PROJ":
            _draw_tab_project(game, player, direction, portfolio_audit, active_project, authority, warnings, x, y, line_h, font, bold, clip_panel)
        elif selected == "AUTH":
            _draw_tab_authority(authority, warnings, x, y, line_h, font, bold, clip_panel)
        elif selected == "SCORE":
            _draw_tab_score(game, player, direction, portfolio_audit, active_project, authority, choices, warnings, x, y, line_h, font, bold, clip_panel)
        elif selected == "PLAN":
            _draw_tab_plan(game, report, best_action, turn_plan, direction, portfolio_audit, warnings, x, y, line_h, font, bold, clip_panel)
        else:
            _blit(font, "Unknown debug tab", x, y, COLORS["DGRAY"])

    _draw_debug_tab_buttons(panel, selected, tab_status, font, bold)
    _update(panel)


# ──────────────────────────────────────────────────────────────────────────────
# Tabbed panel layout and diagnostics
# ──────────────────────────────────────────────────────────────────────────────

DEBUG_TABS: Tuple[Tuple[str, str], ...] = (
    ("SCAN", "SCAN"),
    ("STR", "STR"),
    ("PROJ", "PROJ"),
    ("AUTH", "AUTH"),
    ("SCORE", "WAYS"),
    ("PLAN", "PLAN"),
)
DEFAULT_DEBUG_TAB = "SCAN"


def _selected_debug_tab(game: Any) -> str:
    tab = str(getattr(game, "execution_debug_active_tab", DEFAULT_DEBUG_TAB) or DEFAULT_DEBUG_TAB).upper()
    allowed = {key for key, _label in DEBUG_TABS}
    if tab not in allowed:
        tab = DEFAULT_DEBUG_TAB
        try:
            setattr(game, "execution_debug_active_tab", tab)
        except Exception:
            pass
    return tab


def _debug_tab_rects(panel: pygame.Rect) -> Dict[str, pygame.Rect]:
    left = panel.x + 6
    right = panel.right - 6
    gap = 3
    height = 19
    top = panel.bottom - height - 6
    total_gap = gap * (len(DEBUG_TABS) - 1)
    width = max(36, int((right - left - total_gap) / max(1, len(DEBUG_TABS))))
    rects: Dict[str, pygame.Rect] = {}
    x = left
    for key, _label in DEBUG_TABS:
        rects[key] = pygame.Rect(x, top, width, height)
        x += width + gap
    return rects


def _draw_debug_tab_buttons(panel: pygame.Rect, selected: str, statuses: Mapping[str, str], font: Any, bold: Any) -> None:
    for key, label in DEBUG_TABS:
        rect = _debug_tab_rects(panel).get(key)
        if rect is None:
            continue
        active = key == selected
        pygame.draw.rect(WIN, COLORS["WHITE"] if active else COLORS["GRAY"], rect)
        pygame.draw.rect(WIN, COLORS["BLACK"], rect, 1)
        status = str(statuses.get(key, "✓") or "✓")
        text = f"{label}{status}"
        color = COLORS["RED"] if status not in {"✓", "–"} else (COLORS["DGRAY"] if status == "–" else COLORS["BLACK"])
        _blit_center(bold if active else font, text, rect, color)


def _draw_tab_header_warnings(tab: str, warnings: Sequence[Mapping[str, Any]], x: int, y: int, line_h: int, font: Any, bold: Any, panel: pygame.Rect) -> int:
    tab_warnings = [w for w in warnings if str(w.get("tab", "")).upper() == tab]
    # PROJ needs space for portfolio rows, so show one compact warning line there.
    visible_count = 1 if str(tab).upper() == "PROJ" else 2
    for warning in tab_warnings[:visible_count]:
        if y > panel.bottom - line_h:
            return y
        _blit(bold, _fit_text(f"! {warning.get('text', warning.get('code', 'warning'))}", 60), x, y, COLORS["RED"])
        y += line_h
    if len(tab_warnings) > visible_count and y <= panel.bottom - line_h:
        _blit(font, f"More warnings: +{len(tab_warnings) - visible_count}", x, y, COLORS["RED"])
        y += line_h
    return y


def _plan_item_display_label(item: Mapping[str, Any]) -> str:
    """Human-readable label for one continue-plan / Best-Action item."""
    if not isinstance(item, Mapping):
        return "—"
    for key in ("best_action_text", "label", "message", "best_action_label"):
        text = str(item.get(key) or "").strip()
        if text:
            return text
    action = str(item.get("action") or "").strip()
    return action or "—"


def _plan_action_to_family(action: str) -> str:
    """Map plan item action string to SCAN family key (or special names)."""
    raw = str(action or "").strip()
    low = raw.lower().replace("_", " ")
    if raw in {BUILD_CITY, BUILD_SETTLEMENT, BUILD_ROAD, BUY_DCARD, TWB, TWP}:
        return raw
    if "resolve robber" in low or (low.startswith("resolve") and "robber" in low):
        return "Resolve robber"
    if low in {"end turn", "pass", "pass / end turn"} or low.startswith("end "):
        return "End turn"
    if "twp" in low or low == "trade with player":
        return TWP
    if "twb" in low or "trade with bank" in low or low.startswith("trade-with-bank"):
        return TWB
    if "city" in low:
        return BUILD_CITY
    if "settlement" in low or "settle" in low:
        return BUILD_SETTLEMENT
    if "road" in low:
        return BUILD_ROAD
    if "development" in low or "dcard" in low:
        return BUY_DCARD
    if "robber" in low or "steal" in low:
        return "Resolve robber"
    return raw


def _execution_plan_is_forced(game: Any, plan_rows: Sequence[Mapping[str, Any]]) -> bool:
    state = str(getattr(game, "state", "") or "")
    if state in ROBBER_STATES:
        return True
    pending_7 = getattr(game, "pending_seven_roll", None) or {}
    if isinstance(pending_7, Mapping) and pending_7.get("active"):
        return True
    for row in plan_rows or []:
        if not isinstance(row, Mapping):
            continue
        fam = str(row.get("family") or "")
        act = str(row.get("action") or "").lower()
        if fam == "Resolve robber" or "robber" in act or "discard" in act:
            return True
        if str(row.get("source") or "") == "forced":
            return True
    return False


def _planned_sequence_rows(game: Any) -> List[Dict[str, Any]]:
    """Normalize AI continue plan (or Best-Action fallback) for SCAN Section A.

    Display-only. Does not invent a plan for humans when none exists.
    Each row: step, action, family, label, source, status, marker.
    """
    rows: List[Dict[str, Any]] = []
    raw_plan = list(getattr(game, "current_ai_execution_plan", None) or [])

    def _append_item(item: Mapping[str, Any], step_fallback: int) -> None:
        if not isinstance(item, Mapping):
            return
        action = str(item.get("action") or "").strip()
        if not action:
            return
        try:
            step_no = int(item.get("step") or step_fallback)
        except Exception:
            step_no = step_fallback
        label = _plan_item_display_label(item)
        family = _plan_action_to_family(action)
        rows.append(
            {
                "step": step_no,
                "action": action,
                "family": family,
                "label": label,
                "source": str(item.get("source") or ""),
                "status": str(item.get("status") or ""),
                "marker": "Y",
            }
        )

    if raw_plan:
        for idx, item in enumerate(raw_plan):
            if not isinstance(item, Mapping):
                continue
            _append_item(item, idx + 1)
            if len(rows) >= MAX_PLANNED_SCAN_STEPS:
                break
    else:
        # Single-step fallback from frozen Best-Action (AI checkpoint), not human invent.
        canonical = _canonical_best_action(game)
        if isinstance(canonical, Mapping) and canonical.get("action"):
            action = str(canonical.get("action") or "").strip()
            text = str(canonical.get("best_action_text") or "").strip()
            if action and action not in {"Roll dice", "Roll Dices", "AwaitingDiceRoll"}:
                if not text.startswith(("Wait", "No ", "Roll")):
                    _append_item(canonical, 1)

    forced = _execution_plan_is_forced(game, rows)
    if forced:
        # Plan section: only the forced step (no buy/TwB clutter as "about to happen").
        forced_rows = [
            r
            for r in rows
            if str(r.get("family") or "") == "Resolve robber"
            or "robber" in str(r.get("action") or "").lower()
            or "discard" in str(r.get("action") or "").lower()
            or str(r.get("source") or "") == "forced"
        ]
        if forced_rows:
            rows = forced_rows[:1]
        else:
            rows = [
                {
                    "step": 1,
                    "action": "Resolve robber",
                    "family": "Resolve robber",
                    "label": "Resolve robber / steal",
                    "source": "forced",
                    "status": "ready",
                    "marker": "Y",
                }
            ]
    else:
        # Drop trailing pure pass if earlier real steps exist (noise).
        if len(rows) > 1:
            filtered = [
                r
                for r in rows
                if str(r.get("family") or "") != "End turn"
                and str(r.get("action") or "").lower() not in {"end turn", "pass", "pass / end turn"}
            ]
            if filtered:
                rows = filtered[:MAX_PLANNED_SCAN_STEPS]

    # Re-number display steps 1..n
    for i, r in enumerate(rows):
        r["step"] = i + 1
    return rows


def _scan_marker_for_family(
    family_action: str,
    plan_rows: Sequence[Mapping[str, Any]],
    *,
    display_viable: bool,
    strategy_locked: bool,
) -> str:
    """Y = in plan, L = legal not planned (or locked), N = blocked.

    When *no* plan rows: legality-only mode — Y if viable, L if locked viable, N else.
    """
    plan_list = [r for r in (plan_rows or []) if isinstance(r, Mapping)]
    if plan_list:
        planned = {str(r.get("family") or "") for r in plan_list}
        # TwP is plan-only family; TwB matrix row matches TwB family only
        if family_action in planned:
            return "Y"
        if not display_viable:
            return "N"
        return "L"
    # No AI plan
    if not display_viable:
        return "N"
    if strategy_locked:
        return "L"
    return "Y"


def _plan_label_for_family(
    plan_rows: Sequence[Mapping[str, Any]], family_action: str
) -> str:
    for r in plan_rows or []:
        if not isinstance(r, Mapping):
            continue
        if str(r.get("family") or "") == family_action:
            return str(r.get("label") or r.get("action") or "")
    return ""


def _draw_tab_scan(
    game: Any,
    player: Any,
    report: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    """SCAN: planned AI sequence (primary) + plan-aware family matrix (secondary)."""
    y = _draw_tab_header_warnings("SCAN", warnings, x, y, line_h, font, bold, panel)
    scan = getattr(game, "current_viable_action_scan", None)
    total_candidates = _scan_candidate_total(scan)
    stale = _scan_stale_label(game, report)
    plan_rows = _planned_sequence_rows(game)
    n_plan = len(plan_rows)
    header = f"Scan: plan {n_plan}" if n_plan else "Scan: no AI plan"
    if total_candidates:
        header += f" | choices {len(choices)}/{total_candidates}"
    else:
        header += f" | choices {len(choices)}"
    if stale:
        header += f" | {stale}"
    _blit(font, _fit_text(header, 60), x, y, COLORS["DGRAY"])
    y += line_h

    # ── Section A: planned sequence ───────────────────────────────────────
    if plan_rows:
        _blit(bold, "Plan:", x, y, COLORS["BLACK"])
        y += line_h
        for row in plan_rows:
            if y > panel.bottom - (line_h * 3):
                return y
            step = int(row.get("step") or 0)
            label = str(row.get("label") or row.get("action") or "—")
            marker = str(row.get("marker") or "Y")
            line = f"{step}. {label}"
            _blit(bold, "Y", x, y, COLORS["GREEN"])
            _blit(font, _fit_text(line, 52), x + 14, y, COLORS["BLACK"])
            # trailing marker for readability
            _blit(font, marker, panel.right - 18, y, COLORS["GREEN"])
            y += line_h
    else:
        _blit(font, "No AI plan — legality only", x, y, COLORS["DGRAY"])
        y += line_h

    if y > panel.bottom - (line_h * 3):
        return y

    # ── Section B: family matrix (plan-aware markers) ─────────────────────
    _blit(font, "Families:", x, y, COLORS["DGRAY"])
    y += line_h

    choices_by_action = {str(row.get("action", "")): row for row in choices if isinstance(row, Mapping)}
    flags, candidates_by_action, blockers_by_action = _scan_parts(scan)
    canonical = _canonical_best_action(game)
    has_plan = bool(plan_rows)

    for action, label in ACTION_ROWS:
        if y > panel.bottom - (line_h * 2):
            return y
        choice = choices_by_action.get(action, {})
        candidates = _action_candidates(choice, candidates_by_action, action)
        blockers = _action_blockers(choice, blockers_by_action, action)
        candidate_count = _action_candidate_count(choice, candidates)
        canonical_marks_actionable = _canonical_scan_row_is_best_action(canonical, action)
        strategy_locked = _is_strategy_locked_choice(choice, blockers)
        raw_viable = bool(
            (isinstance(choice, Mapping) and choice.get("scan_viable", False))
            or flags.get(action, False)
            or (strategy_locked and candidate_count > 0)
        )
        display_viable = bool(
            raw_viable
            or (isinstance(choice, Mapping) and choice.get("viable", False))
            or canonical_marks_actionable
        )
        # Family in plan counts as viable for display
        if _scan_marker_for_family(action, plan_rows, display_viable=True, strategy_locked=False) == "Y":
            if any(str(r.get("family") or "") == action for r in plan_rows):
                display_viable = True

        marker = _scan_marker_for_family(
            action,
            plan_rows,
            display_viable=display_viable,
            strategy_locked=strategy_locked,
        )
        if marker == "Y":
            row_color = COLORS["GREEN"]
        elif marker == "L":
            row_color = COLORS["ORANGE"]
        else:
            row_color = COLORS["DGRAY"]

        left = f"{marker} {label:<6} {candidate_count:>2}"
        _blit(bold, left, x, y, row_color)

        # Detail: plan label when Y; never invent rival "best TwB" when a plan exists
        if marker == "Y":
            detail = _plan_label_for_family(plan_rows, action)
            if not detail and has_plan:
                detail = "in plan"
            elif not detail:
                # legality-only: optional best label
                if str(canonical.get("action", "") or "") == action and str(
                    canonical.get("best_action_label", "") or ""
                ):
                    detail = f"best {canonical.get('best_action_label')}"
                else:
                    detail = f"best {_best_label_for_action(game, player, action, candidates)}".strip()
        elif marker == "L":
            if strategy_locked:
                detail = "locked by AUTH/strategy"
            elif has_plan:
                detail = "legal, not planned"
            else:
                detail = "locked by AUTH/strategy" if strategy_locked else "legal"
        else:
            detail = _short_blocker(blockers) or "blocked"

        if detail:
            _blit(
                font,
                _fit_text(detail, 38),
                x + 78,
                y,
                COLORS["BLACK"] if marker == "Y" else (COLORS["DGRAY"] if marker == "N" else COLORS["BLACK"]),
            )
        y += line_h

    if y <= panel.bottom - line_h:
        if has_plan:
            _blit(font, "Y in plan | L legal not planned | N blocked", x, y, COLORS["DGRAY"])
        else:
            _blit(font, "Y legal | L locked | N blocked (no AI plan)", x, y, COLORS["DGRAY"])
        y += line_h
    return y


def _draw_tab_strategy(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    needs: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    """STR owns way identity + abstract composition + PR-D history."""
    y = _draw_tab_header_warnings("STR", warnings, x, y, line_h, font, bold, panel)
    if not isinstance(direction, Mapping) or not direction:
        _blit(font, "Strategy: no current strategic_direction", x, y, COLORS["DGRAY"])
        return y + line_h

    way = _way_id(direction)
    tags = _strategy_tags(direction)
    board_ctx = _first_nonempty(direction, ("board_context_way_id", "board_rank_way_id"), "")
    rows: List[str] = []
    # Identity warning only when preferred way != board-ranked way
    if board_ctx not in (None, "", "-") and way not in (None, "", "-") and str(board_ctx) != str(way):
        rows.append(_fit_text(f"! Preferred way {way} != board#1 way {board_ctx}", 60))
        reason = str(direction.get("override_reason", "") or direction.get("preference_source", "") or "")
        if reason:
            rows.append(_fit_text(f"  keep-abstract | {reason}", 60))
    tag_text = " | ".join(tags) if tags else "-"
    rows.append(f"Way: {way if way not in (None, '') else '-'} | {tag_text}")
    # Family/Weak/Pref only when non-empty (hide perpetual "-")
    family = _first_nonempty(direction, ("strategy_policy_family", "strategy_family", "family"), "")
    if family not in (None, "", "-"):
        rows.append(f"Family: {family}")
    weak = _join_values(direction.get("strategy_policy_weak_engines"), "")
    if weak not in (None, "", "-"):
        rows.append(f"Weak: {weak}")
    pref = _join_values(direction.get("strategy_policy_preferred_action_families"), "")
    if pref not in (None, "", "-"):
        rows.append(f"Pref: {pref}")
    # Abstract action family need (Settle+Road), not Road|NewS|City|DC remaining
    rows.append(f"Need: {_strategy_needs_text(direction, needs)}")
    switch = _strategy_switch_text(direction)
    if switch and str(switch).lower() not in {"", "no", "none", "-"}:
        rows.append(f"Switch: {switch}")
    elif _direction_switched_way(direction):
        rows.append("Switch: yes")

    # S3: round-only STR history (no R1T1 noise by default)
    try:
        from core.strategy_history import format_strategy_history_for_str

        hist = format_strategy_history_for_str(
            player,
            current_round=int(getattr(game, "round", 0) or 0),
            current_turn=int(getattr(game, "turn", 0) or 0),
        )
        if hist.get("now_line"):
            rows.append(_fit_text(str(hist["now_line"]), 62))
        if hist.get("hist_line"):
            rows.append(_fit_text(str(hist["hist_line"]), 62))
        if hist.get("hist_line_2"):
            rows.append(_fit_text(str(hist["hist_line_2"]), 62))
        # this_turn_line intentionally omitted from default STR (S3 density)
    except Exception:
        pass
    return _draw_rows(rows, x, y, line_h, font, panel)


def _draw_tab_project(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
    warnings: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    """PROJ owns concrete board portfolio for the shown way (not way ranking)."""
    y = _draw_tab_header_warnings("PROJ", warnings, x, y, line_h, font, bold, panel)

    rows: List[str] = []
    preferred_way = _way_id(direction) if isinstance(direction, Mapping) else None
    board_way = _first_nonempty(direction, ("board_context_way_id", "board_rank_way_id"), "") if isinstance(direction, Mapping) else ""
    if not board_way and isinstance(portfolio_audit, Mapping):
        board_way = portfolio_audit.get("selected_way_id_before_4g") or portfolio_audit.get("best_board_realistic_way_id") or ""
        rows_list = [r for r in list(portfolio_audit.get("way_audits", []) or []) if isinstance(r, Mapping)]
        if rows_list and not board_way:
            board_way = rows_list[0].get("way_id", "")
    selected_audit = _selected_way_audit(portfolio_audit, direction)
    if not selected_audit:
        selected_audit = _synthetic_selected_way_audit_from_runtime(game, player, direction, project, authority)
        if selected_audit:
            portfolio_audit = dict(portfolio_audit or {})
            portfolio_audit.setdefault("candidate_way_count", 1)
            portfolio_audit.setdefault("selected_way_board_rank", "?")

    # Dual Preferred|Board only when they diverge; same → short way line in summary
    if (
        preferred_way not in (None, "", "-")
        and board_way not in (None, "", "-")
        and str(preferred_way) != str(board_way)
    ):
        rows.append(_fit_text(f"Preferred {preferred_way} | Board#1 {board_way}", 62))

    if selected_audit:
        rows.extend(_portfolio_summary_rows(portfolio_audit, selected_audit, direction))
        # Show all targets when ≤4; only then "+ n more" for 5+
        new_rows = _portfolio_new_target_rows(selected_audit, max_rows=4)
        rows.append("New targets:" if new_rows else "New targets: none visible")
        rows.extend(new_rows)
        city_row = _portfolio_city_targets_row(selected_audit, max_targets=3)
        if city_row:
            rows.append(city_row)
        elif _safe_int(_portfolio_required_city_count(selected_audit, direction), 0) > 0:
            rows.append("Cities: none visible")
        next_line = _portfolio_next_step_line(direction, project, authority, selected_audit)
        if next_line:
            rows.append(next_line)
    else:
        rows.append("Portfolio: MISSING - no audit/runtime targets")

    # Active project only when a real project object exists (no "none visible" noise)
    if isinstance(project, Mapping) and project:
        first = _mapping(project.get("first_action")) or _mapping(authority.get("first_action"))
        active = _project_id(project, authority) or "-"
        sequence = _project_sequence_text(project, first)
        if sequence:
            rows.append(f"Active: {active} | {sequence}")
        else:
            target = _target_label(_first_nonempty(project, ("target_id", "active_target_id"), authority.get("active_target_id")))
            ptype = _first_nonempty(project, ("project_type", "type"), "")
            if ptype or target not in (None, "", "-"):
                rows.append(f"Active: {active} | {ptype or 'project'} {target}".strip())
        race = _project_race_text(project)
        if race:
            rows.append(f"Race: {race}")
        route = _project_route_text(project, first)
        if route and route not in rows:
            rows.append(route)

    if isinstance(authority, Mapping) and authority.get("forbidden_fallback_families") and _rows_remaining(y, line_h, panel, len(rows)) > 0:
        rows.append(f"Fallback: block {_join_values(authority.get('forbidden_fallback_families'), '-')}")
    return _draw_rows(rows, x, y, line_h, font, panel)

def _draw_tab_authority(
    authority: Mapping[str, Any],
    warnings: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    """AUTH owns hard project lock. Until wired, show n/a — not an error."""
    y = _draw_tab_header_warnings("AUTH", warnings, x, y, line_h, font, bold, panel)
    if not isinstance(authority, Mapping) or not authority:
        _blit(font, "Authority: not used in this build", x, y, COLORS["DGRAY"])
        y += line_h
        if y <= panel.bottom - line_h:
            _blit(font, "Hard project lock arrives with phase4g_project_authority", x, y, COLORS["DGRAY"])
            y += line_h
        return y

    first = _mapping(authority.get("first_action"))
    rows = [
        f"Authority: {'active ✓' if authority.get('active') else 'inactive'}",
        f"Owns: {authority.get('active_project_id') or '-'}",
        f"First: {_action_item_text(first) or '-'}",
        f"Exact lock: {_badge(bool(authority.get('exact_action_lock')))}",
        f"Affordable: {_badge(bool(authority.get('first_action_affordable_now')))}",
        f"Protected: {_compact_named_gain(authority.get('protected_resources_named') if isinstance(authority.get('protected_resources_named'), Mapping) else {}) or '-'}",
        f"Missing: {_compact_named_gain(authority.get('missing_resources_named') if isinstance(authority.get('missing_resources_named'), Mapping) else {}) or '-'}",
        f"Forbidden: {_join_values(authority.get('forbidden_fallback_families'), '-')}",
        f"Source: {authority.get('source') or '-'}",
    ]
    reason = str(authority.get("reason", "") or "")
    if reason:
        rows.append(f"Why: {_fit_text(reason, 52)}")
    return _draw_rows(rows, x, y, line_h, font, panel)


def _draw_tab_score(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    """WAYS (PR-E): selected-way header + per-target role/ETA/risk rows.

    Dropped Compare / Decision / Need / Cost clutter. PROJ still owns the full
    portfolio listing; WAYS focuses timing + risk for those same targets.
    """
    del choices  # legal actions stay on ACT/PLAN tabs
    y = _draw_tab_header_warnings("SCORE", warnings, x, y, line_h, font, bold, panel)

    rows: List[str] = []
    # Compact way selection header (1–2 lines)
    rows.extend(_way_decision_rows(portfolio_audit, direction, authority, max_rows=2))

    role_rows = _ways_target_role_rows(
        game, player, direction, portfolio_audit, project, authority
    )
    remaining = _rows_remaining(y, line_h, panel, len(rows))
    if role_rows and remaining > 0:
        rows.extend(role_rows[: max(1, remaining)])

    if not rows:
        rows.append("WAYS: no portfolio targets / audit visible")
    return _draw_rows(rows, x, y, line_h, font, panel)


def _way_decision_rows(
    portfolio_audit: Mapping[str, Any],
    direction: Mapping[str, Any],
    authority: Mapping[str, Any],
    *,
    max_rows: int = 4,
) -> List[str]:
    """WAYS owns selection/rank among candidates (not board turns — PROJ owns those)."""
    rows: List[str] = []
    pref = _way_id(direction) if isinstance(direction, Mapping) else None
    board_ctx = _first_nonempty(direction, ("board_context_way_id", "board_rank_way_id"), "") if isinstance(direction, Mapping) else ""
    if pref not in (None, "", "-") or board_ctx not in (None, "", "-"):
        if str(pref) != str(board_ctx) and board_ctx not in (None, "", "-"):
            rows.append(_fit_text(f"Preferred {pref} | Board#1 {board_ctx}", 62))
    if not isinstance(portfolio_audit, Mapping) or not portfolio_audit:
        state = str(direction.get("strategy_decision_state", "") or "") if isinstance(direction, Mapping) else ""
        if state:
            rows.append(f"Ways: {state}")
        return rows[:max_rows]

    state = str(portfolio_audit.get("way_decision_state", "") or "")
    if state == "AMBIGUOUS_WAY_TIE":
        rows.append("Ways: AMBIGUOUS - no tie-score")
        ties = [t for t in list(portfolio_audit.get("ambiguous_way_audits", []) or []) if isinstance(t, Mapping)]
        for item in ties[:max(1, max_rows - 1)]:
            wid = item.get("way_id", "-")
            feas = item.get("feasibility", "-")
            turns = _format_short_turns(item.get("realistic_expected_own_turns")) or "?t"
            targets = ",".join(_target_label(t) for t in list(item.get("selected_target_ids", []) or [])[:3])
            rows.append(_fit_text(f"= way {wid}: {feas} {turns} {targets}", 62))
        return rows[:max_rows]

    selected = _selected_way_audit(portfolio_audit, direction)
    if selected:
        wid = selected.get("way_id", portfolio_audit.get("selected_way_id_before_4g", _way_id(direction)))
        feas = selected.get("feasibility", "-")
        rank, count = _portfolio_board_rank(portfolio_audit, selected, direction)
        # Prefer preferred-way rank among board candidates (not always board#1)
        pref = _way_id(direction) if isinstance(direction, Mapping) else None
        if pref not in (None, "", "-") and str(pref) != str(wid):
            # Showing board row because preferred missing from audits — flag it
            rows.append(_fit_text(f"Ways: board-showing {wid} (preferred {pref})", 62))
        if rank not in (None, "") and count not in (None, ""):
            rows.append(f"Ways: selected {wid} | {feas} | rank {rank}/{count}")
        elif rank not in (None, ""):
            rows.append(f"Ways: selected {wid} | {feas} | rank {rank}")
        else:
            rows.append(f"Ways: selected {wid} | {feas}")
    if isinstance(authority, Mapping) and authority.get("ambiguous_way_choice"):
        rows.append("AUTH: switch blocked by ambiguity")
    return rows[:max_rows]

def _ways_target_role_rows(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
    *,
    max_targets: int = 5,
) -> List[str]:
    """S3/PR-E: two-line role rows per target (+ Pick + prio glossary).

    Line1: Role @54: useful | 4.8t | 40.8-37.6
    Line2:   prio=1.23 | risk med | P3 4.6t
    """
    selected_audit = _selected_way_audit(portfolio_audit, direction)
    if not selected_audit:
        try:
            cur = player
            if cur is None and game is not None:
                cur = game.get_current_player()
        except Exception:
            cur = player
        selected_audit = _synthetic_selected_way_audit_from_runtime(
            game, cur, direction, project, authority
        )
    if not selected_audit:
        return []

    targets = list(_portfolio_target_list(selected_audit, "new") or [])
    if not targets:
        raw = selected_audit.get("target_portfolio") if isinstance(selected_audit, Mapping) else None
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            targets = [dict(t) for t in raw if isinstance(t, Mapping)]
    if not targets:
        return ["Targets: none in portfolio"]

    active_id = _active_target_id_for_compare(project, authority, direction)
    rows: List[str] = []
    shown = 0
    for target in targets:
        if shown >= max(1, int(max_targets)):
            break
        if not isinstance(target, Mapping):
            continue
        tid = _target_id_from_mapping(target)
        label = _target_label(tid, direction=direction, player=player, target_row=target)
        role = _first_nonempty(
            target,
            ("portfolio_role", "project_priority_tier", "urgency"),
            "-",
        )
        if active_id not in (None, "") and _target_keys_equal(tid, active_id):
            label = f"{label}*"
        line1, line2 = _role_risk_lines(label, target, role)
        rows.append(_fit_text(line1, 62))
        if line2:
            rows.append(_fit_text(line2, 62))
        shown += 1

    pick = _ways_pick_line(targets, active_id)
    if pick:
        rows.append(_fit_text(pick, 62))

    if len(targets) > max_targets:
        rows.append(f"+ {len(targets) - max_targets} more in PROJ")

    # S3 prio glossary (footer)
    rows.append("Prio: higher better | vs X +d = score gap")

    return rows


def _ways_pick_line(targets: Sequence[Mapping[str, Any]], active_id: Any) -> str:
    """PR-F pick line: highest priority_score, with runner-up contrast when useful."""
    del active_id
    scored: List[Dict[str, Any]] = []
    for t in targets:
        if not isinstance(t, Mapping):
            continue
        tid = _target_id_from_mapping(t)
        try:
            eta = t.get("self_eta_own_turns")
            eta_f = float(eta) if eta is not None else None
        except Exception:
            eta_f = None
        try:
            delta = t.get("win_delta")
            delta_f = float(delta) if delta is not None else None
        except Exception:
            delta_f = None
        try:
            prio = t.get("priority_score")
            prio_f = float(prio) if prio is not None else None
        except Exception:
            prio_f = None
        risk = _target_risk_label(t) or "low"
        scored.append(
            {
                "id": tid,
                "label": _target_label(tid),
                "eta": eta_f,
                "delta": delta_f,
                "prio": prio_f,
                "risk": risk,
                "reason": str(t.get("priority_reason") or ""),
            }
        )
    if not scored:
        return ""

    with_prio = [s for s in scored if s["prio"] is not None]
    if len(with_prio) >= 1:
        ordered = sorted(
            with_prio,
            key=lambda s: (-float(s["prio"]), float(s["eta"] if s["eta"] is not None else 99), str(s["label"])),
        )
        best = ordered[0]
        bits = [f"Pick: {best['label']}"]
        if best["eta"] is not None:
            bits.append(f"{float(best['eta']):.1f}t")
        if best["risk"]:
            bits.append(str(best["risk"]))
        if best["delta"] is not None:
            bits.append(f"Δ{float(best['delta']):+.1f}t")
        bits.append(f"prio={float(best['prio']):.2f}")
        line = " | ".join(bits)
        if len(ordered) >= 2:
            second = ordered[1]
            gap = float(best["prio"]) - float(second["prio"])
            # S3: compact contrast (glossary explains +d)
            line += f" (vs {second['label']} {gap:+.2f})"
        return line

    # Fallback without priority_score: fastest low-risk vs best win_delta
    with_eta = [s for s in scored if s["eta"] is not None]
    if len(with_eta) < 2:
        return ""
    safe = [s for s in with_eta if s["risk"] in {"low", "safe", ""}]
    pool = safe if safe else with_eta
    fastest = min(pool, key=lambda s: (float(s["eta"]), str(s["label"])))
    with_delta = [s for s in with_eta if s["delta"] is not None]
    if with_delta:
        best_delta = max(with_delta, key=lambda s: (float(s["delta"]), -float(s["eta"] or 99)))
    else:
        best_delta = min(with_eta, key=lambda s: float(s["eta"]))
    if _target_keys_equal(fastest["id"], best_delta["id"]):
        bits = [f"Pick: {fastest['label']}"]
        if fastest["eta"] is not None:
            bits.append(f"{float(fastest['eta']):.1f}t")
        if fastest["risk"]:
            bits.append(fastest["risk"])
        return " | ".join(bits)
    a, b = fastest, best_delta
    a_bits = f"{a['label']} ({float(a['eta']):.1f}t, {a['risk'] or 'low'})"
    b_bits = f"{b['label']}"
    if b["delta"] is not None:
        b_bits += f" (Δ{float(b['delta']):+.1f}t, {b['risk'] or '?'})"
    elif b["eta"] is not None:
        b_bits += f" ({float(b['eta']):.1f}t, {b['risk'] or '?'})"
    return f"Pick: {a_bits} vs {b_bits}"


def _score_target_comparison_rows(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> List[str]:
    """Backward-compatible alias → PR-E role rows (no Compare/Need/Cost)."""
    return _ways_target_role_rows(
        game, player, direction, portfolio_audit, project, authority
    )


def _active_target_id_for_compare(project: Mapping[str, Any], authority: Mapping[str, Any], direction: Mapping[str, Any]) -> Any:
    for source in (authority, project, direction):
        if not isinstance(source, Mapping):
            continue
        value = _first_nonempty(
            source,
            (
                "active_target_id",
                "target_id",
                "project_target_id",
                "route_target_id",
                "supporting_action_future_settlement_target_id",
                "supporting_action_target_id",
            ),
            "",
        )
        if value not in (None, ""):
            return value
    pid = _project_id(project if isinstance(project, Mapping) else {}, authority if isinstance(authority, Mapping) else {})
    if pid:
        parts = str(pid).replace("@", "_").split("_")
        for part in reversed(parts):
            if str(part).isdigit():
                return int(part)
    return ""


def _target_key(value: Any) -> str:
    text = str(value or "").strip().replace("@", "")
    try:
        return str(int(float(text)))
    except Exception:
        return text.lower()


def _target_keys_equal(a: Any, b: Any) -> bool:
    return bool(_target_key(a)) and _target_key(a) == _target_key(b)


def _find_target_by_id(targets: Sequence[Mapping[str, Any]], target_id: Any) -> Dict[str, Any]:
    for target in targets:
        if isinstance(target, Mapping) and _target_keys_equal(_target_id_from_mapping(target), target_id):
            return dict(target)
    return {}


def _first_rival_target(targets: Sequence[Mapping[str, Any]], active_id: Any) -> Dict[str, Any]:
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        if _target_keys_equal(_target_id_from_mapping(target), active_id):
            continue
        return dict(target)
    return {}


def _target_compare_score(target: Mapping[str, Any], project: Mapping[str, Any]) -> Optional[float]:
    for source in (project, target):
        if not isinstance(source, Mapping):
            continue
        value = _first_nonempty(
            source,
            (
                "project_score",
                "priority_score",
                "selection_score",
                "target_priority_score",
                "target_score",
                "score",
                "resource_role_score",
            ),
            "",
        )
        if value in (None, ""):
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def _score_decision_line(sel_label: str, riv_label: str, sel_score: Optional[float], riv_score: Optional[float]) -> str:
    if sel_score is None or riv_score is None:
        return ""
    delta = sel_score - riv_score
    if abs(delta) < 0.05:
        return "Decision: raw scores tied"
    if delta > 0:
        return f"Decision: raw score favors {sel_label}"
    return f"Decision: AUTH selected {sel_label} below {riv_label}"


def _score_visible_compare_target_ids(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> List[Any]:
    selected_audit = _selected_way_audit(portfolio_audit, direction)
    if not selected_audit:
        selected_audit = _synthetic_selected_way_audit_from_runtime(game, player, direction, project, authority)
    if not selected_audit:
        return []
    targets = _portfolio_target_list(selected_audit, "new")
    if len(targets) < 2:
        return []
    active_id = _active_target_id_for_compare(project, authority, direction)
    selected = _find_target_by_id(targets, active_id) if active_id not in (None, "") else {}
    if not selected:
        selected = dict(targets[0])
        active_id = _target_id_from_mapping(selected)
    rival = _first_rival_target(targets, active_id)
    out: List[Any] = []
    if selected:
        out.append(_target_id_from_mapping(selected))
    if rival:
        out.append(_target_id_from_mapping(rival))
    return out


def _score_breakdown_target_id(direction: Mapping[str, Any], breakdown: Mapping[str, Any]) -> Any:
    for source in (breakdown, direction):
        if not isinstance(source, Mapping):
            continue
        value = _first_nonempty(
            source,
            (
                "target_id",
                "scored_target_id",
                "intersection_id",
                "supporting_action_future_settlement_target_id",
                "supporting_action_target_id",
                "future_settlement_target_id",
                "target",
            ),
            "",
        )
        if value not in (None, ""):
            return value
    return ""


def _score_breakdown_is_visible_target(breakdown_id: Any, visible_ids: Sequence[Any]) -> bool:
    if not visible_ids:
        return True
    if breakdown_id in (None, ""):
        return False
    return any(_target_keys_equal(breakdown_id, target_id) for target_id in visible_ids)


def _score_hidden_breakdown_row(breakdown_id: Any, visible_ids: Sequence[Any]) -> str:
    src = _target_label(breakdown_id) if breakdown_id not in (None, "") else "unknown"
    shown = "/".join(_target_label(v) for v in visible_ids if v not in (None, "")) or "visible targets"
    return _fit_text(f"Breakdown hidden: {src} not {shown}", 62)


def _append_score_breakdown_rows(
    rows: List[str],
    direction: Mapping[str, Any],
    breakdown: Mapping[str, Any],
    breakdown_id: Any,
    y: int,
    line_h: int,
    panel: pygame.Rect,
) -> None:
    label = _target_label(breakdown_id) if breakdown_id not in (None, "") else str(_strategy_target_text(None, direction) or "target")
    total = _format_signed_number(breakdown.get("total_score", direction.get("supporting_action_target_score", 0.0)))
    if not rows:
        rows.append(f"Breakdown {label}: total {total}")
    else:
        if _rows_remaining(y, line_h, panel, len(rows)) > 2:
            rows.append(f"Breakdown {label}: total {total}")

    parts = []
    for label_text, key in (("Pips", "pip_score"), ("Bot", "bottleneck_fit_score"), ("Need", "strategic_need_fit_score"), ("Port", "port_synergy_score")):
        if key in breakdown:
            parts.append(f"{label_text} {_format_signed_number(breakdown.get(key, 0.0))}")
    if parts and _rows_remaining(y, line_h, panel, len(rows)) > 2:
        rows.append(" | ".join(parts[:3]))
        if len(parts) > 3 and _rows_remaining(y, line_h, panel, len(rows)) > 2:
            rows.append(" | ".join(parts[3:]))

    penalty_parts = []
    for label_text, key in (("Route", "route_cost_penalty"), ("Race", "race_risk_penalty")):
        try:
            value = float(breakdown.get(key, 0.0) or 0.0)
        except Exception:
            value = 0.0
        if abs(value) > 0.001:
            penalty_parts.append(f"{label_text} -{_format_number(abs(value))}")
    if penalty_parts and _rows_remaining(y, line_h, panel, len(rows)) > 2:
        rows.append(" | ".join(penalty_parts))

    reasons = breakdown.get("reasons_compact", "") or "; ".join(str(v) for v in list(direction.get("supporting_action_target_score_reasons", []) or [])[:2])
    if reasons and _rows_remaining(y, line_h, panel, len(rows)) > 2:
        rows.append(f"Why {label}: {_fit_text(str(reasons), 48)}")


def _score_hard_bottleneck_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel = _score_hard_bottleneck_score(selected)
    riv = _score_hard_bottleneck_score(rival)
    if sel is None and riv is None:
        return ""
    left = f"{sel_label} {_format_signed_number(sel or 0.0)}"
    right = f"{riv_label} {_format_signed_number(riv or 0.0)}"
    return f"HB score: {left} | {right}"


def _score_hard_bottleneck_score(target: Mapping[str, Any]) -> Optional[float]:
    for key in ("hard_bottleneck_gain_score", "hard_bottleneck_score", "hard_bottleneck_gain"):
        if key in target:
            try:
                return float(target.get(key) or 0.0)
            except Exception:
                pass
    # Some diagnostics only expose a reason string such as 'hard bottleneck gain 500.0'.
    reasons = target.get("resource_role_reasons") if isinstance(target, Mapping) else None
    if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)):
        import re
        for reason in reasons:
            text = str(reason)
            if "hard" in text.lower() and "bottleneck" in text.lower():
                match = re.search(r"(-?\d+(?:\.\d+)?)", text)
                if match:
                    try:
                        return float(match.group(1))
                    except Exception:
                        pass
    return None


def _score_need_value(target: Mapping[str, Any]) -> Optional[float]:
    keys = ("strategic_need_fit_score", "hard_bottleneck_gain_score", "critical_gain_score", "resource_role_score")
    total = 0.0
    seen = False
    # Hard-bottleneck/critical/resource-role fields are target-level evidence
    # from ai_way_portfolio; add them to make the comparison explainable even
    # when the original full score breakdown was not attached to portfolio rows.
    for key in keys:
        if key in target:
            try:
                total += float(target.get(key) or 0.0)
                seen = True
            except Exception:
                pass
    return total if seen else None


def _score_need_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel_gain = _target_gain_text(selected) or "-"
    riv_gain = _target_gain_text(rival) or "-"
    sel_need = _score_need_value(selected)
    riv_need = _score_need_value(rival)
    if sel_need is not None and riv_need is not None:
        return f"Need: {sel_label} {sel_gain} { _format_number(sel_need) } vs {riv_label} {riv_gain} { _format_number(riv_need) }"
    return f"Need: {sel_label} {sel_gain} vs {riv_label} {riv_gain}"


def _target_own_turns_float(target: Mapping[str, Any]) -> Optional[float]:
    race = target.get("opponent_race") if isinstance(target.get("opponent_race"), Mapping) else {}
    for value in (
        target.get("my_turns_to_settle_target"),
        target.get("action_expected_own_turns"),
        target.get("expected_own_turns"),
        target.get("realistic_expected_own_turns"),
        race.get("my_turns_to_settle_target") if isinstance(race, Mapping) else None,
    ):
        try:
            if value not in (None, ""):
                return float(value)
        except Exception:
            pass
    return None


def _target_best_opp_turns_float(target: Mapping[str, Any]) -> Optional[float]:
    race = target.get("opponent_race") if isinstance(target.get("opponent_race"), Mapping) else {}
    racers: List[Mapping[str, Any]] = []
    for key in ("opponent_racers", "racers", "opponents"):
        value = target.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            value = race.get(key) if isinstance(race, Mapping) else None
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            racers = [r for r in list(value) if isinstance(r, Mapping)]
            if racers:
                break
    best: Optional[float] = None
    for racer in racers:
        for key in ("turns_to_settle_target", "opponent_turns_to_settle_target", "expected_own_turns", "turns"):
            try:
                value = racer.get(key)
                if value not in (None, ""):
                    turns = float(value)
                    best = turns if best is None else min(best, turns)
                    break
            except Exception:
                pass
    if best is not None:
        return best
    for key in ("opponent_turns_to_settle_target", "best_opponent_turns_to_settle_target"):
        try:
            value = race.get(key) if isinstance(race, Mapping) else target.get(key)
            if value not in (None, ""):
                return float(value)
        except Exception:
            pass
    return None


def _race_margin_text(target: Mapping[str, Any]) -> str:
    mine = _target_own_turns_float(target)
    opp = _target_best_opp_turns_float(target)
    if mine is None or opp is None:
        return ""
    return _format_signed_number(opp - mine)


def _score_race_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel_race = _target_racer_text(selected, max_racers=2)
    riv_race = _target_racer_text(rival, max_racers=2)
    sel_m = _race_margin_text(selected)
    riv_m = _race_margin_text(rival)
    left = f"{sel_label} me{_target_turns_text(selected) or '?'} {sel_race or 'noopp'}"
    right = f"{riv_label} me{_target_turns_text(rival) or '?'} {riv_race or 'noopp'}"
    if sel_m:
        left += f" Δ{sel_m}"
    if riv_m:
        right += f" Δ{riv_m}"
    return f"Race: {left} | {right}"


def _score_timing_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel_t = _target_own_turns_float(selected)
    riv_t = _target_own_turns_float(rival)
    if sel_t is None or riv_t is None:
        return ""
    diff = abs(sel_t - riv_t)
    if diff < 0.05:
        return f"Timing: tied at {_format_number(sel_t)}t"
    faster = sel_label if sel_t < riv_t else riv_label
    return f"Timing: {faster} faster by {_format_number(diff)}t"


def _score_cost_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel_cost = _target_road_cost_text(selected)
    riv_cost = _target_road_cost_text(rival)
    sel_roads = _target_road_cost_count(selected)
    riv_roads = _target_road_cost_count(rival)
    if sel_roads is not None and riv_roads is not None:
        if sel_roads == riv_roads:
            return f"Cost: both {sel_cost}"
        cheaper = sel_label if sel_roads < riv_roads else riv_label
        return f"Cost: {sel_label} {sel_cost} | {riv_label} {riv_cost} ({cheaper} cheaper)"
    return f"Cost: {sel_label} {sel_cost} | {riv_label} {riv_cost}"


def _target_road_cost_count(target: Mapping[str, Any]) -> Optional[int]:
    """Roads still to build toward this target, preferring concrete route lists.

    Some portfolio rows carry both a broad/distance estimate and a concrete
    remaining route.  The SCORE comparison should answer the player's question
    "what does it cost from here?", so a concrete route_roads_to_build list
    wins over distance_roads/road_count.
    """
    roads = _target_route_roads_to_build(target)
    if roads:
        return len(roads)
    for key in (
        "route_roads_remaining",
        "remaining_roads",
        "roads_remaining",
        "roads_to_build_count",
        "num_roads_to_build",
        "roads_needed",
        "distance_roads",
        "road_count",
    ):
        value = target.get(key) if isinstance(target, Mapping) else None
        if value not in (None, "", [], {}, ()):  # keep zero as valid
            return _safe_int(value, 0)
    return None


def _target_road_cost_text(target: Mapping[str, Any]) -> str:
    count = _target_road_cost_count(target)
    if count is None:
        return "?r"

    # Show when the broad portfolio distance disagrees with the concrete route.
    # This avoids hiding exactly the kind of issue noticed for @38.
    broad = None
    for key in ("distance_roads", "road_count"):
        value = target.get(key) if isinstance(target, Mapping) else None
        if value not in (None, "", [], {}, ()):  # keep zero as valid
            broad = _safe_int(value, count)
            break
    if broad is not None and broad != count:
        return f"{count}r(now)/{broad}r(path)"
    return f"{count}r"


def _target_route_roads_to_build(target: Mapping[str, Any]) -> List[Any]:
    if not isinstance(target, Mapping):
        return []
    for key in (
        "route_roads_to_build",
        "roads_to_build",
        "missing_route_roads",
        "remaining_route_roads",
        "supporting_action_frontier_route_roads_to_build",
    ):
        value = target.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
            roads = [v for v in list(value) if v not in (None, "", [])]
            if roads:
                return roads
    route = target.get("route")
    if isinstance(route, Mapping):
        for key in ("roads_to_build", "route_roads_to_build", "remaining_roads"):
            value = route.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
                roads = [v for v in list(value) if v not in (None, "", [])]
                if roads:
                    return roads
    return []


def _score_role_compare_lines(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any], project: Mapping[str, Any], authority: Mapping[str, Any]) -> List[str]:
    """Return role comparison as one row per intersection with risk/ETA when known.

    Example: Role @38: critical | P1 3t vs P2 2t | risk: high
    """
    del authority  # reserved; AUTH owns hard-lock narrative
    sel_role = _first_nonempty(project, ("project_priority_tier", "urgency"), _first_nonempty(selected, ("project_priority_tier", "urgency", "portfolio_role"), "-"))
    riv_role = _first_nonempty(rival, ("project_priority_tier", "urgency", "portfolio_role"), "-")
    return [
        _role_risk_line(sel_label, selected, sel_role),
        _role_risk_line(riv_label, rival, riv_role),
    ]


def _lowest_opp_eta_short(threats: Any) -> str:
    """S3 risk detail: lowest opp ETA only, e.g. 'P3 4.6t'."""
    rows = [t for t in list(threats or []) if isinstance(t, Mapping)]
    best = None
    best_eta = None
    for t in rows:
        raw = t.get("eta_own_turns")
        if raw is None:
            continue
        try:
            eta = float(raw)
        except Exception:
            continue
        if eta >= 9000:
            continue
        if best_eta is None or eta < best_eta:
            best_eta = eta
            pid = t.get("player_id")
            if pid is not None:
                best = f"P{pid}"
            else:
                col = str(t.get("color") or "").strip()
                best = col[:3] if col else "?"
    if best is None or best_eta is None:
        return ""
    return f"{best} {best_eta:.1f}t"


def _role_risk_lines(label: str, target: Mapping[str, Any], role: Any) -> Tuple[str, str]:
    """S3 two-line role row.

    Line1: Role @54: useful | 4.8t | 40.8-37.6
    Line2:   prio=x.xx | risk med | P3 4.6t   (prio/risk; opp ETA on med/high)
    """
    line1_parts = [f"Role {label}: {role or '-'}"]
    self_eta = target.get("self_eta_own_turns") if isinstance(target, Mapping) else None
    if self_eta is not None:
        try:
            line1_parts.append(f"{float(self_eta):.1f}t")
        except Exception:
            pass
    else:
        me = _target_turns_text(target)
        if me:
            line1_parts.append(f"me{me}")
    base_w = target.get("baseline_win_turns") if isinstance(target, Mapping) else None
    win_if = target.get("win_turns_if_target") if isinstance(target, Mapping) else None
    if base_w is not None and win_if is not None:
        try:
            # S3: use '-' not arrow for win-span density
            line1_parts.append(f"{float(base_w):.1f}-{float(win_if):.1f}")
        except Exception:
            pass

    line2_parts: List[str] = []
    prio = target.get("priority_score") if isinstance(target, Mapping) else None
    if prio is not None:
        try:
            line2_parts.append(f"prio={float(prio):.2f}")
        except Exception:
            pass
    risk = _target_risk_label(target)
    if risk:
        line2_parts.append(f"risk {risk}")
    threats = target.get("threat_opponents") if isinstance(target, Mapping) else None
    if threats and risk and risk not in {"low", "safe", ""}:
        opp = _lowest_opp_eta_short(threats)
        if opp:
            line2_parts.append(opp)
        else:
            try:
                from core.risk_assessment import format_threat_opponents_short

                threat_txt = format_threat_opponents_short(list(threats))
                if threat_txt:
                    line2_parts.append(threat_txt)
            except Exception:
                pass

    line1 = " | ".join(line1_parts)
    line2 = ("  " + " | ".join(line2_parts)) if line2_parts else ""
    return line1, line2


def _role_risk_line(label: str, target: Mapping[str, Any], role: Any) -> str:
    """Compat single-line (tests / callers); prefers S3 two-line join."""
    line1, line2 = _role_risk_lines(label, target, role)
    if line2:
        return f"{line1} | {line2.strip()}"
    return line1


def _target_risk_label(target: Mapping[str, Any]) -> str:
    if not isinstance(target, Mapping):
        return ""
    for key in ("race_risk", "risk_level", "action_risk_level"):
        value = str(target.get(key, "") or "").strip().lower()
        if value:
            if value == "medium":
                return "med"
            return value
    status = str(target.get("race_status", "") or "").strip().lower()
    if status in {"contested", "race", "hot", "critical"}:
        return "high"
    if status in {"safe", "uncontested", "clear"}:
        return "low"
    if status in {"watched", "medium", "med", "soft"}:
        return "med"
    if status:
        return status
    role = str(target.get("portfolio_role", "") or "").strip().lower()
    if "critical" in role or "must_race" in role:
        return "high"
    if "important" in role:
        return "med"
    if "safe" in role or "backup" in role:
        return "low"
    return ""


def _score_reason_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel_reasons = list(selected.get("resource_role_reasons", []) or []) if isinstance(selected.get("resource_role_reasons", []), Sequence) and not isinstance(selected.get("resource_role_reasons", []), (str, bytes)) else []
    riv_reasons = list(rival.get("resource_role_reasons", []) or []) if isinstance(rival.get("resource_role_reasons", []), Sequence) and not isinstance(rival.get("resource_role_reasons", []), (str, bytes)) else []
    if sel_reasons:
        return f"Why {sel_label}: {_fit_text(str(sel_reasons[0]), 48)}"
    if riv_reasons:
        return f"Why {riv_label}: {_fit_text(str(riv_reasons[0]), 48)}"
    return ""

def _draw_tab_plan(
    game: Any,
    report: Mapping[str, Any],
    best_action: Mapping[str, Any],
    turn_plan: Mapping[str, Any],
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    warnings: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    """PLAN owns immediate sequence / next step + Stage A hand-risk + T4 TwP strip."""
    y = _draw_tab_header_warnings("PLAN", warnings, x, y, line_h, font, bold, panel)
    risk_rows = _hand_risk_plan_rows(game, report)
    twp_rows = _twp_plan_rows(game, report)
    if not isinstance(turn_plan, Mapping) or not turn_plan:
        rows: List[str] = ["Plan: single-step (no multi-step object)"]
        next_line = _plan_next_from_direction(direction, best_action)
        if next_line:
            rows.append(next_line)
        roads = direction.get("roads_to_build") if isinstance(direction, Mapping) else None
        if roads:
            rows.append(f"Route: {roads}")
        order_rows = _required_target_order_rows(portfolio_audit, direction, max_rows=3)
        if order_rows:
            rows.extend(order_rows)
        rows.extend(_lr_suggestion_plan_rows(game, direction))
        rows.extend(_la_suggestion_plan_rows(game, direction))
        rows.extend(_specials_divert_plan_rows(game, direction))
        rows.extend(_package_quality_plan_rows(game, report))
        rows.extend(risk_rows)
        rows.extend(twp_rows)
        return _draw_rows(rows, x, y, line_h, font, panel)

    rows = [
        f"Plan: {turn_plan.get('plan_summary') or turn_plan.get('plan_type') or turn_plan.get('plan_status') or '-'}",
    ]
    steps = [s for s in list(turn_plan.get("steps", []) or []) if isinstance(s, Mapping)]
    for idx, step in enumerate(steps[:4], start=1):
        raw_label = _action_item_text(step) or str(step.get("action") or "-")
        rows.append(f"{idx}) {_fit_text(_compact_best_action_text(raw_label), 48)}")
    if not steps:
        next_line = _plan_next_from_direction(direction, best_action)
        if next_line:
            rows.append(next_line)

    order_rows = _required_target_order_rows(portfolio_audit, direction, max_rows=3)
    if order_rows:
        rows.extend(order_rows)

    stop = str(turn_plan.get("stop_reason", "") or "")
    if stop:
        rows.append(f"Stop: {_fit_text(stop, 52)}")
    # S-LR-E / S-LA-E: turn suggestion coach lines
    rows.extend(_lr_suggestion_plan_rows(game, direction))
    rows.extend(_la_suggestion_plan_rows(game, direction))
    # S5.5-C: divert dig-in when LA/LR way was abandoned this turn
    rows.extend(_specials_divert_plan_rows(game, direction))
    # T1-C: package-quality rank one-liner when TwP planned
    rows.extend(_package_quality_plan_rows(game, report))
    rows.extend(risk_rows)
    rows.extend(twp_rows)
    return _draw_rows(rows, x, y, line_h, font, panel)


def _package_quality_plan_rows(game: Any, report: Mapping[str, Any]) -> List[str]:
    """T1-C PLAN dig-in: ``TwP-PQ: 2O→1Wd (2:1 unlock) vs P1`` from last rank meta."""
    try:
        from core.player_trade import format_package_quality_dbg

        meta = None
        if isinstance(report, Mapping):
            raw = report.get("last_twp_package_rank") or report.get("twp_package_quality")
            if isinstance(raw, Mapping) and raw:
                meta = dict(raw)
        if meta is None and game is not None:
            raw = getattr(game, "last_twp_package_rank", None)
            if isinstance(raw, Mapping) and raw:
                meta = dict(raw)
        if not meta or not meta.get("chosen"):
            return []
        line = str(meta.get("dbg") or "") or format_package_quality_dbg(meta)
        if not line or line in ("TwP-PQ: n/a", "TwP-PQ: none"):
            return []
        return [_fit_text(line, 62)]
    except Exception:
        return []


def _specials_divert_plan_rows(game: Any, direction: Mapping[str, Any]) -> List[str]:
    """S5.5-C PLAN line when specials divert fired (or cached this turn)."""
    try:
        from core.strategy_specials_divert import format_specials_divert_dbg

        meta = None
        if isinstance(direction, Mapping):
            raw = direction.get("specials_divert")
            if isinstance(raw, Mapping) and raw.get("fired"):
                meta = dict(raw)
        if meta is None and game is not None:
            raw = getattr(game, "last_specials_divert", None)
            if isinstance(raw, Mapping) and raw.get("fired"):
                meta = dict(raw)
        if meta is None:
            player = _current_player(game)
            if player is not None:
                raw = getattr(player, "last_specials_divert", None)
                if isinstance(raw, Mapping) and raw.get("fired"):
                    meta = dict(raw)
        if not meta:
            return []
        line = str(meta.get("dbg") or "") or format_specials_divert_dbg(meta)
        if not line or line in ("Divert: n/a", "Divert: skip"):
            return []
        return [_fit_text(line, 62)]
    except Exception:
        return []


def _lr_suggestion_plan_rows(game: Any, direction: Mapping[str, Any]) -> List[str]:
    """S-LR-E PLAN lines from LR project turn suggestions."""
    try:
        from core.ai_lr_project import (
            build_lr_turn_suggestions,
            format_lr_suggestions_lines,
            get_stored_lr_project,
        )

        player = _current_player(game)
        if player is None:
            return []
        proj = get_stored_lr_project(player, game)
        if not proj and isinstance(direction, Mapping):
            raw = direction.get("lr_project")
            if isinstance(raw, Mapping) and raw.get("roads_to_build"):
                proj = dict(raw)
        if not proj:
            return []
        focus = None
        if isinstance(direction, Mapping):
            focus = direction.get("turn_focus")
        suggestions = build_lr_turn_suggestions(
            game, player, project=proj, focus=str(focus) if focus else None
        )
        return format_lr_suggestions_lines(suggestions, max_lines=2)
    except Exception:
        return []


def _la_suggestion_plan_rows(game: Any, direction: Mapping[str, Any]) -> List[str]:
    """S-LA-E PLAN lines from LA progress turn suggestions."""
    try:
        from core.ai_la_progress import (
            build_la_turn_suggestions,
            format_la_suggestions_lines,
            get_stored_la_progress,
        )

        player = _current_player(game)
        if player is None:
            return []
        prog = get_stored_la_progress(player, game)
        if not prog and isinstance(direction, Mapping):
            raw = direction.get("la_progress")
            if isinstance(raw, Mapping) and raw:
                prog = dict(raw)
        if not prog:
            return []
        focus = None
        if isinstance(direction, Mapping):
            focus = direction.get("turn_focus")
        suggestions = build_la_turn_suggestions(
            game, player, progress=prog, focus=str(focus) if focus else None
        )
        return format_la_suggestions_lines(suggestions, max_lines=2)
    except Exception:
        return []


def _hand_risk_plan_rows(game: Any, report: Mapping[str, Any]) -> List[str]:
    """Stage A hand-risk lines for PLAN (visibility only)."""
    profile: Mapping[str, Any] = {}
    if isinstance(report, Mapping):
        raw = report.get("hand_risk_profile")
        if isinstance(raw, Mapping) and raw:
            profile = raw
    if not profile and game is not None:
        raw = getattr(game, "current_hand_risk_profile", None)
        if isinstance(raw, Mapping) and raw:
            profile = raw
    if not profile and game is not None:
        try:
            from core.ai_hand_risk import get_hand_risk_profile

            player = _current_player(game)
            profile = get_hand_risk_profile(game, player)
        except Exception:
            profile = {}
    if not profile:
        return []
    try:
        from core.ai_hand_risk import format_hand_risk_detail_rows

        return format_hand_risk_detail_rows(profile, max_rows=3)
    except Exception:
        compact = profile.get("compact")
        return [str(compact)] if compact else []


def _twp_plan_rows(game: Any, report: Mapping[str, Any]) -> List[str]:
    """T4 TwP status lines for PLAN (S3: one status line; no duplicate Skip)."""
    snap: Mapping[str, Any] = {}
    if isinstance(report, Mapping):
        raw = report.get("twp_debug")
        if isinstance(raw, Mapping) and raw:
            snap = raw
    if not snap and game is not None:
        raw = getattr(game, "last_twp_debug", None)
        if isinstance(raw, Mapping) and raw:
            snap = raw
    if not snap and game is not None:
        try:
            from core.human_twp_policy import refresh_twp_debug

            snap = refresh_twp_debug(game)
        except Exception:
            snap = {}
    if not snap:
        return []
    try:
        from core.human_twp_policy import format_twp_debug_rows

        rows = format_twp_debug_rows(snap, max_rows=3)
    except Exception:
        line = snap.get("line")
        rows = [str(line)] if line else []
    # S3: collapse TwP + Skip duplicate — keep primary line only when no_mutual / skip noise
    if not rows:
        return []
    primary = str(rows[0] or "")
    low = primary.lower()
    skip_like = any(
        k in low
        for k in ("no_mutual", "none", "skip", "no mutual", "no offer")
    )
    if skip_like:
        # Single compact status; drop extra Skip: / Policy: clones of same story
        compact = primary
        if not compact.lower().startswith("twp"):
            compact = f"TwP: {compact}"
        # Prefer explicit no_mutual token if present in skip_reasons
        skips = list(snap.get("skip_reasons") or [])
        for s in skips:
            if "no_mutual" in str(s).lower():
                return ["TwP: no_mutual"]
        if "no_mutual" in low:
            return ["TwP: no_mutual"]
        return [_fit_text(compact, 56)]
    # Active offer / unlock: keep up to 2 short rows, drop bare "Skip:" twins of line
    out: List[str] = [primary]
    for r in rows[1:]:
        rt = str(r or "")
        if rt.lower().startswith("skip:"):
            # Only keep if it adds a new reason not already in primary
            body = rt.split(":", 1)[-1].strip().lower()
            if body and body not in low:
                out.append(_fit_text(rt, 56))
            continue
        out.append(_fit_text(rt, 56))
        if len(out) >= 2:
            break
    return out


def _short_support_label(support: Any) -> str:
    """S3 PLAN: short supporting_action_type labels."""
    text = str(support or "").strip().lower()
    mapping = {
        "new_settlement": "new_s",
        "next_settlement": "next_s",
        "build_settlement": "settle",
        "city_upgrade": "city",
        "build_city": "city",
        "buy_dcard": "dcard",
        "buy_development_card": "dcard",
        "development_card": "dcard",
        "dcard": "dcard",
        "road": "road",
        "build_road": "road",
    }
    if text in mapping:
        return mapping[text]
    if not text:
        return ""
    return text[:10]


def _short_plan_rec_text(rec: Any) -> str:
    """Compress recommendation for PLAN density."""
    text = str(rec or "").strip()
    if not text:
        return ""
    low = text.lower()
    # priority road toward @32 → prio to @32
    if "priority" in low and "toward" in low:
        at = text.find("@")
        if at >= 0:
            return "prio to " + text[at:].split()[0][:8]
    if low.startswith("road toward"):
        at = text.find("@")
        if at >= 0:
            return "road to " + text[at:].split()[0][:8]
    if low.startswith("race "):
        return text[:16]
    if low.startswith("settle "):
        return text[:14]
    return text[:28]


def _plan_next_from_direction(direction: Mapping[str, Any], best_action: Mapping[str, Any]) -> str:
    """Compact next step: short support | short rec (S3)."""
    support = direction.get("supporting_action_type") if isinstance(direction, Mapping) else None
    rec = direction.get("recommendation") if isinstance(direction, Mapping) else None
    if rec in (None, ""):
        rec = direction.get("supporting_action_description") if isinstance(direction, Mapping) else None
    tid = None
    if isinstance(direction, Mapping):
        tid = _first_nonempty(
            direction,
            (
                "recommendation_target_id",
                "supporting_action_future_settlement_target_id",
                "supporting_action_target_id",
            ),
            "",
        )
    bits: List[str] = []
    short_sup = _short_support_label(support)
    if short_sup:
        bits.append(short_sup)
    rec_text = _short_plan_rec_text(rec)
    if rec_text:
        if rec_text not in bits and (not short_sup or rec_text.lower() != short_sup.lower()):
            bits.append(rec_text)
    elif tid not in (None, ""):
        bits.append(f"@{_target_label(tid).lstrip('@')}")
    if bits:
        return "Next: " + " | ".join(bits)
    if isinstance(best_action, Mapping) and best_action:
        text = _action_item_text(best_action) or str(best_action.get("best_action_text") or best_action.get("action") or "")
        if text:
            return f"Next: {_compact_best_action_text(text)[:40]}"
    return ""




def _required_target_order_rows(portfolio_audit: Mapping[str, Any], direction: Mapping[str, Any], *, max_rows: int = 4) -> List[str]:
    """Rows for PLAN: required portfolio ordering.

    PF12 separates membership from order.  If @38 and @42 are both required,
    this row explains which one should be pursued first.  Probability / delay
    risk for completing the required portfolio is primary; single-claim ETA is
    used only inside an equal probability class.
    """
    selected = _selected_way_audit(portfolio_audit, direction)
    audit: Mapping[str, Any] = {}
    if isinstance(selected, Mapping):
        value = selected.get("required_target_order_audit")
        if isinstance(value, Mapping):
            audit = value
    if not audit and isinstance(portfolio_audit, Mapping):
        value = portfolio_audit.get("selected_way_required_target_order_audit")
        if isinstance(value, Mapping):
            audit = value
    if not audit:
        return []
    ordered_ids = list(audit.get("ordered_target_ids", []) or [])
    if not ordered_ids:
        return []

    order_text = " → ".join(_target_label(tid) for tid in ordered_ids[:5])
    rows: List[str] = [f"Req order: {order_text}"]
    tie = bool(audit.get("tie_break_used", False))
    policy = "prob first; ETA tie" if tie else "prob first; ETA not used"
    rows.append(f"Order rule: {policy}")

    ordered = [t for t in list(audit.get("ordered_targets", []) or []) if isinstance(t, Mapping)]
    for item in ordered[:max(0, max_rows - 2)]:
        tid = item.get("target_id", "-")
        prob = str(item.get("probability_band", "?") or "?")
        delay = str(item.get("delay_risk", "?") or "?")
        eta = item.get("single_claim_eta_reduction")
        eta_text = ""
        if eta not in (None, ""):
            try:
                eta_text = f" ETA-{float(eta):g}t"
            except Exception:
                eta_text = f" ETA-{eta}"
        rows.append(_fit_text(f"{_target_label(tid)} P{prob} delay {delay}{eta_text}", 62))
    hidden = max(0, len(ordered) - max(0, max_rows - 2))
    if hidden:
        rows.append(f"... +{hidden} required targets")
    return rows[:max_rows]

def _post_claim_projection_rows(portfolio_audit: Mapping[str, Any], direction: Mapping[str, Any], *, max_rows: int = 5) -> List[str]:
    """Rows for PLAN: ETA after each candidate intersection individually.

    PF11 intentionally displays single-target post-claim projections only.  It
    must not show @38+@42 or other multi-claim combinations, because the user
    wants each required settlement slot evaluated independently.
    """
    selected = _selected_way_audit(portfolio_audit, direction)
    projections: List[Mapping[str, Any]] = []
    if isinstance(selected, Mapping):
        raw = selected.get("single_target_post_claim_projections") or selected.get("post_claim_win_projections") or []
        projections = [p for p in list(raw or []) if isinstance(p, Mapping) and not bool(p.get("combinations_evaluated", False))]
    if not projections and isinstance(portfolio_audit, Mapping):
        raw = portfolio_audit.get("selected_way_single_target_post_claim_projections") or []
        projections = [p for p in list(raw or []) if isinstance(p, Mapping) and not bool(p.get("combinations_evaluated", False))]
    if not projections:
        return []

    rows: List[str] = ["Claim ETA: single targets only"]
    for proj in projections[:max(0, max_rows - 1)]:
        tid = proj.get("target_id", proj.get("claimed_target_id", "-"))
        turns = (
            _format_short_turns(proj.get("expected_turns_to_win_after_claim"))
            or _format_short_turns(proj.get("realistic_expected_own_turns_after_claim"))
            or "?t"
        )
        rem = proj.get("remaining_requirement_summary", {}) if isinstance(proj.get("remaining_requirement_summary", {}), Mapping) else {}
        new_req = _first_nonempty(rem, ("new_intersections_required",), proj.get("remaining_new_intersections_required", "?"))
        city_req = _first_nonempty(rem, ("cities_required",), proj.get("city_upgrade_count_required", "?"))
        remain_targets = list(proj.get("remaining_new_intersection_target_ids", []) or [])
        remain_text = ",".join(_target_label(t) for t in remain_targets[:3])
        suffix = f" | rem {remain_text}" if remain_text else ""
        rows.append(_fit_text(f"after {_target_label(tid)}: win {turns} | need N{new_req} C{city_req}{suffix}", 62))
    hidden = max(0, len(projections) - max(0, max_rows - 1))
    if hidden:
        rows.append(f"... +{hidden} single-target ETA")
    return rows[:max_rows]


# ──────────────────────────────────────────────────────────────────────────────
# Section drawing
# ──────────────────────────────────────────────────────────────────────────────


def _draw_scan_rows(
    game: Any,
    player: Any,
    report: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    choices_by_action = {str(row.get("action", "")): row for row in choices if isinstance(row, Mapping)}
    actionable_by_action = {
        str(row.get("action", "")): row
        for row in list(getattr(game, "current_actionable_choices", []) or [])
        if isinstance(row, Mapping) and bool(row.get("actionable", False))
    }

    scan = getattr(game, "current_viable_action_scan", None)
    flags: Dict[str, Any] = {}
    candidates_by_action: Dict[str, Any] = {}
    blockers_by_action: Dict[str, Any] = {}
    if isinstance(scan, Mapping):
        flags = dict(scan.get("action_flags", {}) or {})
        candidates_by_action = dict(scan.get("candidates", {}) or {})
        blockers_by_action = dict(scan.get("blockers", {}) or {})
    else:
        flags = dict(getattr(scan, "action_flags", {}) or {})
        candidates_by_action = dict(getattr(scan, "candidates", {}) or {})
        blockers_by_action = dict(getattr(scan, "blockers", {}) or {})

    for action, label in ACTION_ROWS:
        if y > panel.bottom - 72:
            return y

        choice = choices_by_action.get(action, {})
        choice_candidates = list(choice.get("candidates", []) or []) if isinstance(choice, Mapping) else []
        raw_candidates = list(candidates_by_action.get(action, []) or [])
        candidates = choice_candidates or raw_candidates
        blockers = list(choice.get("blockers", []) or blockers_by_action.get(action, []) or []) if isinstance(choice, Mapping) else list(blockers_by_action.get(action, []) or [])
        candidate_count = int(choice.get("candidate_count", len(candidates)) or len(candidates)) if isinstance(choice, Mapping) else len(candidates)

        canonical = _canonical_best_action(game)
        canonical_action = str(canonical.get("action", "") or "") if canonical else ""
        canonical_label = str(canonical.get("best_action_label", "") or "") if canonical else ""
        blocked_action = str(canonical.get("blocked_action", "") or "") if canonical else ""
        canonical_marks_actionable = _canonical_scan_row_is_best_action(canonical, action)

        strategy_locked = _is_strategy_locked_choice(choice, blockers)
        raw_viable = bool(
            (isinstance(choice, Mapping) and choice.get("scan_viable", False))
            or flags.get(action, False)
            or (strategy_locked and candidate_count > 0)
        )
        display_viable = raw_viable or bool(choice.get("viable", False)) if isinstance(choice, Mapping) else raw_viable
        # Phase 3.2: synthetic Best-Action bridge actions, especially TwB rescue
        # actions, may not be present in current_actionable_choices.  Still
        # mark the matching SCAN row as actionable so the panel clearly shows
        # which available action Best-Action will execute.
        if canonical_marks_actionable:
            display_viable = True

        is_actionable = bool(actionable_by_action.get(action))
        if isinstance(choice, Mapping):
            is_actionable = is_actionable or bool(choice.get("actionable", False))
        is_actionable = is_actionable or canonical_marks_actionable
        marker = "A" if is_actionable else ("Y" if display_viable else "N")
        row_color = COLORS["RED"] if is_actionable else (COLORS["GREEN"] if display_viable else COLORS["DGRAY"])
        left = f"{marker} {label:<6} {candidate_count:>2}"
        _blit(bold, left, x, y, row_color)

        if display_viable and strategy_locked:
            detail = "No strategic priority"
            detail_font = bold
            detail_color = COLORS["GREEN"]
        elif display_viable and canonical_action == action and canonical_label:
            detail = f"best {canonical_label}".strip()
            detail_font = font
            detail_color = COLORS["BLACK"]
        elif display_viable and bool(canonical.get("route_blocked")) and blocked_action == action:
            detail = "route target not legal"
            detail_font = bold
            detail_color = COLORS["DGRAY"]
        elif display_viable:
            detail = f"best {_best_label_for_action(game, player, action, candidates)}".strip()
            detail_font = font
            detail_color = COLORS["BLACK"]
        else:
            detail = _short_blocker(blockers) or (f"best {_best_label_for_action(game, player, action, candidates)}".strip())
            detail_font = font
            detail_color = COLORS["DGRAY"]

        if is_actionable and detail:
            detail_font = bold
            detail_color = COLORS["RED"]
        if detail:
            _blit(detail_font, _fit_text(detail, 38), x + 78, y, detail_color)
        y += line_h

    return y

def _draw_strategy_rows(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    needs: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    panel: pygame.Rect,
) -> int:
    """Draw STRATEGY in two rows to preserve panel height."""
    way = _way_id(direction)
    tags = _strategy_tags(direction)
    tag_text = " | ".join(tags) if tags else "-"
    _blit(font, _fit_text(f"Way: {way if way not in (None, '') else '-'} | {tag_text}", 64), x, y)
    y += line_h

    needs_text = _strategy_needs_text(direction, needs)
    target = _strategy_target_text(game, direction)
    risk = _strategy_risk_text(direction)
    second = f"Needs: {needs_text} | Target: {target if target else '-'}"
    if risk:
        second += f" | Risk: {risk}"
    _blit(font, _fit_text(second, 64), x, y)
    return y + line_h

def _draw_support_rows(
    game: Any,
    direction: Mapping[str, Any],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    panel: pygame.Rect,
) -> int:
    """Draw Phase-3 strategic support/candidate-pool diagnostics."""
    if not isinstance(direction, Mapping) or not direction:
        _blit(font, "Support: -", x, y, COLORS["DGRAY"])
        return y + line_h

    support = _strategy_support_summary(game, direction)
    _blit(font, _fit_text(support or "Support: -", 64), x, y)
    y += line_h

    if y > panel.bottom - 48:
        return y

    pool = _strategy_support_pool_text(direction)
    _blit(font, _fit_text(pool or "Pool: -", 64), x, y, COLORS["DGRAY"])
    y += line_h

    if y > panel.bottom - 42:
        return y

    route = _strategy_support_route_or_gain_text(direction)
    if route:
        _blit(font, _fit_text(route, 64), x, y, COLORS["DGRAY"])
        y += line_h
    return y



def _draw_score_rows(
    direction: Mapping[str, Any],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    panel: pygame.Rect,
) -> int:
    """Draw compact Phase-4A resource-scarcity target score diagnostics."""
    if not isinstance(direction, Mapping) or not direction:
        _blit(font, "not scored", x, y, COLORS["DGRAY"])
        return y + line_h

    breakdown = direction.get("supporting_action_target_score_breakdown", {})
    if not isinstance(breakdown, Mapping) or not breakdown:
        _blit(font, "not scored", x, y, COLORS["DGRAY"])
        return y + line_h

    compact = str(breakdown.get("score_compact", "") or "").strip()
    if not compact:
        total = _format_signed_number(breakdown.get("total_score", 0.0))
        bot = _format_signed_number(breakdown.get("bottleneck_fit_score", 0.0))
        route = _format_number(breakdown.get("route_cost_penalty", 0.0))
        compact = f"Tgt {total} | Bot {bot}"
        try:
            if float(breakdown.get("route_cost_penalty", 0.0) or 0.0) > 0:
                compact += f" | Route -{route}"
        except Exception:
            pass
    _blit(font, _fit_text(compact or "not scored", 64), x, y)
    y += line_h

    if y > panel.bottom - 44:
        return y

    reasons = breakdown.get("reasons_compact", "")
    if not reasons:
        reasons = "; ".join(str(v) for v in list(direction.get("supporting_action_target_score_reasons", []) or [])[:2])
    if reasons:
        _blit(font, _fit_text(str(reasons), 64), x, y, COLORS["DGRAY"])
        y += line_h
    return y


def _draw_bridge_rows(
    bridge: Mapping[str, Any],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    panel: pygame.Rect,
) -> int:
    """Draw Phase-2 bridge: strategic support vs immediate execution status."""
    if not isinstance(bridge, Mapping) or not bridge:
        _blit(font, "Pref: - | Fallback: legal", x, y, COLORS["DGRAY"])
        return y + line_h

    labels = list(bridge.get("preferred_action_labels", []) or [])
    if not labels:
        labels = [_short_action(a) for a in list(bridge.get("preferred_actions", []) or [])]
    pref = "+".join([str(v) for v in labels if str(v)]) or "-"
    status = str(bridge.get("status", "") or "-")
    if status.startswith("preferred_unavailable_resource"):
        status = "unaffordable; seek resources"
    elif status.startswith("preferred_unavailable"):
        status = "unavailable; legal fallback"
    elif status == "preferred_available":
        status = "available"
    elif status == "no_preferred_support":
        status = "no preferred support"

    _blit(font, _fit_text(f"Pref: {pref} | {status}", 64), x, y)
    y += line_h

    if y > panel.bottom - 48:
        return y

    fallback = str(bridge.get("fallback_policy", "") or "legal_fallback")
    if fallback == "resource_support":
        fallback_text = "Fallback: TwP/TwB, then legal"
    elif fallback == "preferred_available":
        fallback_text = "Fallback: not needed"
    else:
        fallback_text = f"Fallback: {fallback}"
    _blit(font, _fit_text(fallback_text, 64), x, y, COLORS["DGRAY"])
    return y + line_h


def _canonical_scan_row_is_best_action(canonical: Mapping[str, Any], action: str) -> bool:
    """Return True when a SCAN row is the frozen Best-Action action.

    Phase 3.2 uses this for synthetic bridge actions.  Some Best-Action items are
    not emitted as current_actionable_choices because they are composed late by
    Game, for example ``TwB 4 Wood -> 1 Ore; then Buy DCard``.  Those rows
    should still display as red/bold ``A`` in SCAN.  Wait/pass/blocked route
    items must not be shown as actionable.
    """
    if not isinstance(canonical, Mapping) or not action:
        return False
    if bool(canonical.get("route_blocked")):
        return False
    canonical_action = str(canonical.get("action", "") or "")
    if canonical_action != str(action or ""):
        return False
    if canonical_action in {"", "End turn", "Pass", "Roll dice"}:
        return False
    text = str(canonical.get("best_action_text", "") or canonical.get("label", "") or "").strip()
    if text.startswith(("Wait", "No ", "Roll", "Resolve")):
        return False
    return True


def _canonical_best_action(game: Any) -> Mapping[str, Any]:
    """Return Game's frozen Best-Action object, if available."""
    item = getattr(game, "current_best_action", None)
    if isinstance(item, Mapping) and item.get("action"):
        return dict(item)
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping):
        item = report.get("canonical_best_action")
        if isinstance(item, Mapping) and item.get("action"):
            return dict(item)
    return {}

def _draw_actionable_rows(
    game: Any,
    player: Any,
    choices: Sequence[Mapping[str, Any]],
    x: int,
    y: int,
    line_h: int,
    font: Any,
    bold: Any,
    panel: pygame.Rect,
) -> int:
    canonical_blocked = _canonical_best_action(game)
    if canonical_blocked and bool(canonical_blocked.get("route_blocked")):
        _blit(font, "None", x, y, COLORS["DGRAY"])
        return y + line_h

    actionable = [row for row in choices if isinstance(row, Mapping) and bool(row.get("actionable"))]
    if not actionable:
        _blit(font, "None", x, y, COLORS["DGRAY"])
        return y + line_h

    for idx, row in enumerate(actionable[:3], start=1):
        if y > panel.bottom - 36:
            break
        action = str(row.get("action", ""))
        candidates = list(row.get("candidates", []) or [])
        canonical = _canonical_best_action(game) if idx == 1 else {}
        if canonical and str(canonical.get("action", "") or "") == action:
            best = str(canonical.get("best_action_label", "") or "")
        else:
            best = _best_label_for_action(game, player, action, candidates)
        text = f"{idx}. {_short_action(action)} {best}".strip()
        # Actionable rows represent real choices now. Make them visually stand
        # out from informational scan rows: green + bold whenever ACTIONABLE is
        # not None.
        _blit(bold, _fit_text(text, 64), x, y, COLORS["GREEN"])
        y += line_h
    return y


# ──────────────────────────────────────────────────────────────────────────────
# Strategic-direction formatting
# ──────────────────────────────────────────────────────────────────────────────


def _strategy_direction(player: Any) -> Mapping[str, Any]:
    direction = getattr(player, "strategic_direction", None)
    if isinstance(direction, Mapping) and direction:
        return direction
    last_direction = getattr(player, "last_strategic_direction", None)
    if isinstance(last_direction, Mapping) and last_direction:
        return last_direction
    return {}


def _way_id(direction: Mapping[str, Any]) -> Any:
    if not isinstance(direction, Mapping):
        return "-"
    return direction.get("preferred_way_id", direction.get("way_id", "-"))


def _strategy_tags(direction: Mapping[str, Any]) -> List[str]:
    """Return compact Way tags for STR ownership.

    Canonical order (no DC here — PROJ owns remaining DC / NewS counts):
        LR | LA | n City | n Settle | n VP

    Never BA — always LA. Never bare "n DC" on STR.

    Settle comes from the way-table **Settlements** column (final settlement
    buildings in the mix), **not** New_Settlements_To_Build. Expansion packing
    (NewS) is owned by PROJ Need, so way 16 is exactly:

        Way: 16 | LA | 3 City | 2 VP

    Examples:
        Way: 16  | LA | 3 City | 2 VP
        Way: 102 | 4 City | 1 Settle | 1 VP
        Way: 133 | LA | 2 City | 2 Settle | 2 VP
        Way: 142 | LR | LA | 3 City
    """
    if not isinstance(direction, Mapping):
        return []

    # 1) Authoritative composition from the 142-way table (fixes missing LA/VP)
    way = _way_id(direction)
    comp = _way_composition(way)
    out: List[str] = []
    if comp:
        if comp.get("longest_road"):
            out.append("LR")
        if comp.get("largest_army") or comp.get("biggest_army"):
            out.append("LA")
        cities = int(comp.get("cities") or 0)
        # Settle = way-table settlements only (not NewS expansion count)
        settles = int(comp.get("settlements") or 0)
        remaining = direction.get("remaining", {}) if isinstance(direction.get("remaining"), Mapping) else {}
        if remaining:
            rem_c = _positive_from(remaining, ("cities", "city_upgrades"))
            if rem_c > 0:
                cities = rem_c
        if cities > 0:
            out.append(f"{cities} City")
        if settles > 0:
            out.append(f"{settles} Settle")
        vp = int(comp.get("victory_point_cards") or 0)
        if vp > 0:
            out.append(f"{vp} VP")
        return _sort_way_tags(out)[:6]

    # 2) Fallback: parse runtime tags / summary when way table is unavailable
    raw_tags = list(direction.get("tags", []) or [])
    summary = direction.get("strategy_summary", {}) if isinstance(direction.get("strategy_summary", {}), Mapping) else {}
    remaining = direction.get("remaining", {}) if isinstance(direction.get("remaining", {}), Mapping) else {}

    for raw in raw_tags:
        tag = _normalise_way_tag(raw)
        if tag and _tag_root(tag) != "DC":
            _add_or_replace_tag(out, tag)

    if _truthy(summary.get("largest_army")) or _positive_from(summary, ("largest_army",)) or _truthy(summary.get("biggest_army")):
        _add_or_replace_tag(out, "LA")
    if _truthy(summary.get("longest_road")):
        _add_or_replace_tag(out, "LR")
    for raw in raw_tags:
        lower = str(raw or "").lower()
        if "largest army" in lower or "biggest army" in lower:
            _add_or_replace_tag(out, "LA")
        if "longest road" in lower:
            _add_or_replace_tag(out, "LR")

    for label, keys in (
        ("City", ("cities", "city_upgrades", "cities_to_build", "remaining_city_upgrades", "remaining_cities_to_upgrade")),
        # Settle: final settlement buildings only — not new_settlements / NewS
        ("Settle", ("settlements",)),
        ("VP", ("victory_points", "vp_cards", "victory_point_cards", "remaining_vp_cards")),
    ):
        value = _positive_from(summary, keys)
        if value <= 0 and label != "Settle":
            value = _positive_from(remaining, keys)
        if value > 0:
            _add_or_replace_tag(out, f"{value} {label}")

    out = [t for t in out if _tag_root(t) != "DC"]
    return _sort_way_tags(out)[:6]


# Cached 142-way composition rows for STR / Need DC
_WAY_COMPOSITION_CACHE: Optional[Dict[int, Dict[str, Any]]] = None


def _way_composition(way_id: Any) -> Dict[str, Any]:
    """Return LA/LR/city/new/VP/listed-DC for one way_id from the 142-way table."""
    global _WAY_COMPOSITION_CACHE
    try:
        wid = int(way_id)
    except Exception:
        return {}
    if wid < 0:
        return {}
    if _WAY_COMPOSITION_CACHE is None:
        _WAY_COMPOSITION_CACHE = {}
        try:
            from core.strategy_timing import load_strategy_requirements

            for req in load_strategy_requirements() or []:
                try:
                    rid = int(getattr(req, "way_id", -1))
                except Exception:
                    continue
                if rid < 0:
                    continue
                # listed CSV DC is buried under raw / warnings; use raw if present
                listed = 0
                raw = getattr(req, "raw", None) or {}
                if isinstance(raw, Mapping):
                    for key in ("Development_Cards_To_Buy", "development_cards_to_buy", "listed_development_cards"):
                        if raw.get(key) not in (None, ""):
                            listed = _safe_int(raw.get(key), 0)
                            break
                # When load already replaced field with expected buys, recover listed via components
                if listed <= 0:
                    # Infer listed from expected if pure LA/VP formula matches reverse is hard;
                    # keep 0 and let joint estimator use composition only.
                    listed = 0
                _WAY_COMPOSITION_CACHE[rid] = {
                    "way_id": rid,
                    "largest_army": bool(getattr(req, "biggest_army", False)),
                    "biggest_army": bool(getattr(req, "biggest_army", False)),
                    "longest_road": bool(getattr(req, "longest_road", False)),
                    "cities": int(getattr(req, "city_upgrades", 0) or getattr(req, "cities", 0) or 0),
                    "new_settlements": int(getattr(req, "new_settlements_to_build", 0) or 0),
                    "settlements": int(getattr(req, "settlements", 0) or 0),
                    "victory_point_cards": int(getattr(req, "victory_point_cards", 0) or 0),
                    # Engine may store expected buys (16) in development_cards_to_buy
                    "expected_dc_buys": int(getattr(req, "development_cards_to_buy", 0) or 0),
                    "listed_dc_buys": listed,
                }
        except Exception:
            _WAY_COMPOSITION_CACHE = {}
    return dict(_WAY_COMPOSITION_CACHE.get(wid) or {})


def _joint_dc_buy_estimate(
    *,
    largest_army: bool = False,
    vp_cards: int = 0,
    listed_dc: int = 0,
) -> int:
    """Joint DC-buy estimate — same model as strategy ranking / timing.

    Delegates to ``strategy_timing.expected_development_card_buys`` so PROJ Need
    DC matches way ranking (LA + 2 VP → 10, not additive 16).
    """
    try:
        from core.strategy_timing import expected_development_card_buys

        return int(
            expected_development_card_buys(
                victory_point_cards=int(vp_cards or 0),
                largest_army=bool(largest_army),
                listed_development_cards=int(listed_dc or 0),
            )
        )
    except Exception:
        vp = max(0, int(vp_cards or 0))
        listed = max(0, int(listed_dc or 0))
        la = bool(largest_army)
        if la and vp >= 2:
            return max(listed, 10 + 4 * (vp - 2))
        if la and vp == 1:
            return max(listed, 8)
        if la:
            return max(listed, 6)
        if vp > 0:
            return max(listed, vp * 5)
        return listed


def _strategy_dc_count(
    direction: Mapping[str, Any],
    summary: Mapping[str, Any],
    remaining: Mapping[str, Any],
    raw_tags: Sequence[Any],
) -> int:
    """One DC figure for tag display (remaining > summary > tags)."""
    for source in (remaining, summary, direction if isinstance(direction, Mapping) else {}):
        if not isinstance(source, Mapping):
            continue
        value = _positive_from(
            source,
            (
                "development_cards",
                "development_cards_to_buy",
                "dev_cards_to_buy",
                "dcards_to_buy",
                "remaining_dev_cards_to_buy",
            ),
        )
        if value > 0:
            return int(value)
    for raw in raw_tags or []:
        text = str(raw or "").lower()
        if "dev" in text or "dc" in text:
            num = _first_int_in_text(str(raw))
            if num is not None and num > 0:
                return int(num)
    return 0


def _normalise_way_tag(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""

    # Drop explanatory bracket text such as "(6 DC)" or "(10 DC)".
    main = text.split("(", 1)[0].strip()
    lower = main.lower().replace("_", " ").replace("-", " ")
    lower = " ".join(lower.split())
    if not lower:
        return ""

    # Not Way tags; these are target/path details.
    if lower in {"port", "ports", "harbor", "harbour", "road", "roads"}:
        return ""
    if lower.startswith(("port ", "ports ", "road ", "roads ")):
        return ""

    if lower in {"la", "largest army", "largestarmy", "ba", "biggest army", "biggestarmy"}:
        return "LA"
    if lower in {"lr", "longest road", "longestroad"}:
        return "LR"

    words = lower.split()
    first = words[0] if words else lower
    second = words[1] if len(words) > 1 else ""

    # Accept both "3 City" and "City 3" styles, with singular display.
    if first.isdigit() and second:
        num = int(first)
        root = _word_to_way_root(second)
        if root:
            return f"{num} {root}"

    root = _word_to_way_root(first)
    if root:
        num = _first_int_in_text(main)
        return f"{num} {root}" if num is not None else root

    if "victory point" in lower:
        num = _first_int_in_text(main)
        return f"{num} VP" if num is not None else "VP"

    # Avoid noisy long free-text tags.
    if len(main) > 14:
        return ""
    return main

def _word_to_way_root(word: str) -> str:
    word = str(word or "").strip().lower()
    if word in {"city", "cities"}:
        return "City"
    if word in {"settle", "settles", "settlement", "settlements"}:
        return "Settle"
    if word in {"vp", "vps", "victory"}:
        return "VP"
    if word in {"dc", "dcs", "dcard", "dcards", "dev", "development"}:
        return "DC"
    return ""


def _tag_root(tag: str) -> str:
    text = str(tag or "").strip()
    if not text:
        return ""
    # "LA (6 DC)" → LA
    main = text.split("(", 1)[0].strip()
    parts = main.split()
    if not parts:
        return ""
    if parts[0].isdigit() and len(parts) > 1:
        return parts[1]
    return parts[0]


def _add_or_replace_tag(tags: List[str], tag: str) -> None:
    root = _tag_root(tag)
    if not root:
        return
    # LA and LR are unique objective tags. For numbered components, prefer the
    # newest/clearest count over a duplicated raw tag.
    for idx, existing in enumerate(list(tags)):
        if _tag_root(existing) == root:
            tags[idx] = tag
            return
    tags.append(tag)


def _sort_way_tags(tags: Sequence[str]) -> List[str]:
    # Ownership format: LR | LA | City | Settle | VP | DC
    priority = {"LR": 0, "LA": 1, "City": 2, "Settle": 3, "VP": 4, "DC": 5}
    return sorted(list(tags), key=lambda tag: (priority.get(_tag_root(tag), 99), list(tags).index(tag)))


def _is_strategy_locked_choice(choice: Any, blockers: Sequence[Any]) -> bool:
    if isinstance(choice, Mapping) and bool(choice.get("strategy_locked", False)):
        return True
    for blocker in blockers or []:
        text = str(blocker).lower()
        if "strategic lock" in text or "strategic priority" in text or "preferred support" in text:
            return True
    return False


def _strategy_needs_text(direction: Mapping[str, Any], needs: Sequence[Mapping[str, Any]]) -> str:
    immediate = [_short_action(str(n.get("action", ""))) for n in needs if isinstance(n, Mapping)]
    immediate = [x for x in immediate if x]

    if not immediate:
        support = _support_action_label(direction)
        if support:
            immediate = [support]

    if not immediate:
        return "None"

    immediate_unique = _unique_keep_order(immediate)
    later = _later_need_labels(direction, immediate_unique)
    text = " + ".join(immediate_unique)
    if later:
        text += " | Later: " + " + ".join(later)
    return text


def _later_need_labels(direction: Mapping[str, Any], immediate: Sequence[str]) -> List[str]:
    tags = _strategy_tags(direction)
    later: List[str] = []
    imm = set(immediate)

    # LA and VP usually imply later development-card buys unless DCard is already immediate.
    if (any(_tag_root(t) == "LA" for t in tags) or any(_tag_root(t) == "VP" for t in tags)) and "DCard" not in imm:
        later.append("DC")

    for tag in tags:
        root = _tag_root(tag)
        label = {
            "City": "City",
            "Settle": "Settle",
            "VP": "DC",
            "DC": "DC",
            "LA": "DC",
        }.get(root, "")
        if label and label not in imm and label not in later:
            later.append(label)

    return later[:2]


def _sticky_target_text(direction: Mapping[str, Any], player: Any = None) -> str:
    """S11–S13 sticky: ``Target: S@6 | C@42 | Buy DCard`` (never bare — when intent exists)."""
    if not isinstance(direction, Mapping) or not direction:
        return "Target: —"
    try:
        from core.strategy_target_format import format_sticky_target_line

        return format_sticky_target_line(direction, player=player)
    except Exception:
        pass
    # Fallback (pre-S-pack): single @id
    tid = _first_nonempty(
        direction,
        (
            "recommendation_target_id",
            "locked_rec_target_id",
            "settlement_target_id",
            "new_settlement_target_id",
            "target_id",
            "supporting_action_future_settlement_target_id",
            "supporting_action_target_id",
        ),
        "",
    )
    if tid in (None, "", "-"):
        pt = direction.get("project_target")
        if isinstance(pt, Mapping):
            tid = pt.get("target_id")
        elif pt is not None:
            tid = getattr(pt, "target_id", None)
    if tid in (None, "", "-"):
        line = direction.get("display_targets_line")
        if line:
            return f"Target: {line}"
        return "Target: —"
    try:
        return f"Target: @{int(float(tid))}"
    except Exception:
        label = str(tid).strip()
        if label.startswith("@") or label.startswith("S@") or label.startswith("C@"):
            return f"Target: {label}"
        return f"Target: @{label}" if label else "Target: —"


def _sticky_status_text(
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> str:
    """Sticky way row: Way id · board turns · frag · Auth:n/a (not tab lookalikes).

    Way id always follows STR (preferred / strategic_direction).
    Turns/frag prefer the preferred-way audit; if only board#1 is available,
    still show its timing but flag Pref≠Board so PROJ/WAYS do not look 'wrong'.
    """
    way = _way_id(direction) if isinstance(direction, Mapping) else "-"
    selected = _selected_way_audit(portfolio_audit, direction) if isinstance(portfolio_audit, Mapping) else {}
    board_way = ""
    if isinstance(direction, Mapping):
        board_way = _first_nonempty(direction, ("board_context_way_id", "board_rank_way_id"), "")
    if not board_way and isinstance(portfolio_audit, Mapping):
        board_way = portfolio_audit.get("best_board_realistic_way_id") or portfolio_audit.get("selected_way_id_before_4g") or ""
        rows = [r for r in list(portfolio_audit.get("way_audits", []) or []) if isinstance(r, Mapping)]
        if rows and not board_way:
            board_way = rows[0].get("way_id", "")

    # Prefer turns/frag from preferred-way row; fall back to selected (may be board#1)
    turn_source: Mapping[str, Any] = {}
    if isinstance(selected, Mapping) and selected:
        turn_source = selected
        sel_id = selected.get("way_id")
        if way not in (None, "", "-") and sel_id not in (None, "") and str(sel_id) != str(way):
            # Selected fell back to board#1 while STR keeps abstract preferred
            for row in list((portfolio_audit or {}).get("way_audits", []) or []):
                if isinstance(row, Mapping) and str(row.get("way_id")) == str(way):
                    turn_source = row
                    break

    turns = ""
    frag = ""
    if isinstance(turn_source, Mapping) and turn_source:
        turns = _format_short_turns(
            _first_nonempty(
                turn_source,
                ("realistic_expected_own_turns", "board_expected_turns", "portfolio_expected_own_turns"),
                "",
            )
        ) or ""
        frag = str(turn_source.get("fragility", "") or "").strip()
    if not turns and isinstance(direction, Mapping):
        turns = _format_short_turns(
            _first_nonempty(
                direction,
                (
                    "board_expected_turns",
                    "realistic_expected_turns",
                    "risk_adjusted_total_expected_own_turns",
                    "total_expected_own_turns",
                    "action_expected_own_turns",
                ),
                "",
            )
        ) or ""
        if not frag:
            frag = str(direction.get("fragility", "") or "").strip()

    parts: List[str] = [f"Way {way if way not in (None, '') else '-'}"]
    if turns:
        parts.append(str(turns))
    if frag and frag not in {"-", ""}:
        parts.append(f"frag {frag}")

    if isinstance(authority, Mapping) and authority and bool(authority.get("active")):
        parts.append("Auth:on")
    else:
        parts.append("Auth:n/a")

    if board_way not in (None, "", "-") and way not in (None, "", "-") and str(way) != str(board_way):
        parts.append(f"!Pref≠B#{board_way}")
    return " · ".join(parts)


def _direction_switched_way(direction: Mapping[str, Any]) -> bool:
    """True when planner marked a way switch this refresh."""
    if not isinstance(direction, Mapping) or not direction:
        return False
    if bool(direction.get("strategy_changed")) or bool(direction.get("override_applied")):
        return True
    for key in ("phase4g_would_switch_way", "would_switch_way", "strategy_would_switch"):
        if bool(direction.get(key)):
            return True
    from_way = direction.get("abstract_preferred_way_id") or direction.get("previous_preferred_way_id")
    to_way = direction.get("preferred_way_id") or direction.get("way_id")
    if from_way not in (None, "", "-") and to_way not in (None, "", "-") and str(from_way) != str(to_way):
        if bool(direction.get("override_applied")) or str(direction.get("preference_source", "")).startswith("4G"):
            return True
    return False


def _support_action_label(direction: Mapping[str, Any]) -> str:
    support = str(direction.get("supporting_action_type", "") or "").strip()
    if not support:
        return ""
    return {
        "city_upgrade": "City",
        "build_city": "City",
        "next_settlement": "Settle",
        "new_settlement": "Road",
        "build_settlement": "Settle",
        "road": "Road",
        "build_road": "Road",
        "buy_dcard": "DCard",
        "buy_development_card": "DCard",
        "development_card": "DCard",
        "dcard": "DCard",
    }.get(support, _short_action(support))



def _strategy_support_summary(game: Any, direction: Mapping[str, Any]) -> str:
    support_type = str(direction.get("supporting_action_type", "") or "")
    label = str(direction.get("supporting_action_label", "") or "")
    if support_type == "frontier_road":
        target = direction.get("supporting_action_future_settlement_target_id", direction.get("supporting_action_target_id"))
        road = direction.get("supporting_action_road_id")
        road_text = _format_road_id(road) if road not in (None, "") else "road"
        label = f"road→{target} {road_text}" if target not in (None, "") else f"road→future {road_text}"
    if not label:
        label = _strategy_target_text(game, direction)
    if not label:
        label = _support_action_label(direction) or "support"

    turns = direction.get("supporting_action_expected_own_turns", direction.get("action_expected_own_turns", ""))
    turn_text = _format_short_turns(turns)
    risk = _strategy_risk_text(direction)
    if support_type == "frontier_road":
        race = direction.get("supporting_action_opponent_race", {})
        if isinstance(race, Mapping):
            level = str(race.get("risk_level", "") or "")
            opp = race.get("opponent_id")
            if level:
                risk = f"Race {level[:1].upper()}" + (f":P{opp}" if opp not in (None, "") else "")
    parts = [f"Support: {label}"]
    if turn_text:
        parts.append(turn_text)
    if risk:
        parts.append(str(risk))
    return " | ".join(parts)


def _strategy_support_pool_text(direction: Mapping[str, Any]) -> str:
    pool = str(direction.get("strategy_preference_candidate_pool", direction.get("supporting_action_source", "")) or "")
    source = "all" if pool == "all_candidate_actions" else ("top" if pool == "best_actions" else (pool or "-"))
    rank = _safe_int(
        direction.get("strategy_preference_selected_action_rank_in_pool", direction.get("supporting_action_rank", 0)),
        0,
    )
    all_count = _safe_int(direction.get("strategy_preference_all_candidate_action_count", 0), 0)
    pool_count = _safe_int(direction.get("strategy_preference_candidate_action_count", 0), 0)
    display_count = _safe_int(direction.get("strategy_preference_display_action_count", direction.get("strategy_preference_top_n_display_count", 0)), 0)
    from_top = bool(direction.get("strategy_preference_selected_from_display_top_n", direction.get("supporting_action_selected_from_display_top_n", False)))

    bits = [f"Pool: {source}"]
    if pool_count:
        bits.append(f"rank {rank}/{pool_count}" if rank else f"{pool_count} actions")
    if all_count and all_count != pool_count:
        bits.append(f"all {all_count}")
    if display_count:
        bits.append(f"top {display_count}")
    if pool == "all_candidate_actions":
        bits.append("in top" if from_top else "outside top")
    return " | ".join(bits)


def _strategy_support_route_or_gain_text(direction: Mapping[str, Any]) -> str:
    roads = list(direction.get("supporting_action_frontier_route_roads_to_build", []) or direction.get("supporting_action_roads_to_build", []) or [])
    path = list(direction.get("supporting_action_path", []) or [])
    gain_named = direction.get("supporting_action_future_settlement_resource_gain_named", {}) or direction.get("supporting_action_resource_gain_named", {}) or {}
    if not isinstance(gain_named, Mapping):
        gain_named = {}

    gain = _compact_named_gain(gain_named)
    if roads:
        road_text = ",".join(_format_road_id(r) for r in roads[:3])
        if len(roads) > 3:
            road_text += ",..."
        if str(direction.get("supporting_action_type", "") or "") == "frontier_road":
            remaining = direction.get("supporting_action_frontier_remaining_roads_after_action")
            remain_text = f" | rem {remaining}r" if remaining not in (None, "") else ""
            text = f"Next: {_format_road_id(direction.get('supporting_action_road_id') or roads[0])}{remain_text}"
        else:
            text = f"Route: {road_text}"
        if gain:
            text += f" | +{gain}"
        return text
    if path:
        path_text = "->".join(str(x) for x in path[:4])
        if len(path) > 4:
            path_text += "->..."
        text = f"Path: {path_text}"
        if gain:
            text += f" | +{gain}"
        return text
    if gain:
        return f"Gain: +{gain}"
    payment = str(direction.get("supporting_action_payment_model", direction.get("payment_model", "")) or "")
    if payment:
        return f"Payment: {payment}"
    return ""


def _compact_named_gain(named: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for key in RESOURCE_NAMES:
        value = named.get(key)
        try:
            numeric = float(value)
        except Exception:
            numeric = 0.0
        if abs(numeric) <= 0.001:
            continue
        text = _format_number(numeric)
        short = {
            "Wheat": "Wh",
            "Ore": "O",
            "Wood": "Wd",
            "Brick": "B",
            "Sheep": "Sh",
        }.get(key, key[:2])
        parts.append(f"{text}{short}")
    return "/".join(parts[:5])


def _format_short_turns(value: Any) -> str:
    try:
        v = float(value)
    except Exception:
        return ""
    if v >= 9999:
        return "∞t"
    return f"{_format_number(v)}t"

def _strategy_target_text(game: Any, direction: Mapping[str, Any]) -> str:
    if not isinstance(direction, Mapping) or not direction:
        return ""
    # S11–S13: multi-target S@/C@ line when available
    try:
        from core.strategy_target_format import format_targets_line

        player = None
        try:
            player = game.get_current_player() if game is not None else None
        except Exception:
            player = None
        multi = format_targets_line(direction, player=player, empty="")
        if multi and multi != "—":
            return multi
    except Exception:
        pass
    support = str(direction.get("supporting_action_type", "") or "").strip()
    target = direction.get("supporting_action_target_id")

    if support:
        label = {
            "city_upgrade": "city_upgrade",
            "build_city": "city_upgrade",
            "next_settlement": "next_settle",
            "new_settlement": "new_settle",
            "build_settlement": "settle",
            "road": "road",
            "build_road": "road",
            "buy_dcard": "buy_dcard",
            "buy_development_card": "buy_dcard",
            "development_card": "buy_dcard",
            "dcard": "buy_dcard",
        }.get(support, support)
    else:
        label = "target"

    if label == "buy_dcard":
        return "Buy DCard"

    if target in (None, ""):
        # Road targets are sometimes stored only in roads_to_build.
        road = _first_road_from_direction(direction)
        if road:
            return f"road{_format_road_id(road)}"
        return label

    text = f"{label}@{target}"
    port = _target_port_suffix(game, target)
    if port:
        text += f" {port}"
    return text


def _first_road_from_direction(direction: Mapping[str, Any]) -> Any:
    for key in ("supporting_action_roads_to_build", "roads_to_build", "supporting_action_path"):
        values = direction.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
            first = values[0]
            if _road_key(first):
                return first
    return None


def _target_port_suffix(game: Any, target_id: Any) -> str:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return ""
    if inter is None:
        return ""
    has_port = bool(getattr(inter, "port_tf", False)) or str(getattr(inter, "portYN", "N")) == "Y"
    return "(port)" if has_port else ""


def _strategy_risk_text(direction: Mapping[str, Any]) -> str:
    for key in ("action_risk_level", "risk_level", "road_risk_level"):
        value = str(direction.get(key, "") or "").strip()
        if value:
            return value
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Data extraction
# ──────────────────────────────────────────────────────────────────────────────


def _current_player(game: Any) -> Any:
    getter = getattr(game, "get_current_player", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    turn = _safe_int(getattr(game, "turn", 0))
    for player in list(getattr(game, "players", []) or []):
        if _safe_int(getattr(player, "id", 0)) == turn:
            return player
    return None


def _current_player_report(game: Any, player: Any) -> Dict[str, Any]:
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping) and _same_player(report.get("player_id"), player):
        return dict(report)

    scan = getattr(game, "current_viable_action_scan", None)
    if isinstance(scan, Mapping) and _same_player(scan.get("player_id"), player):
        return dict(scan)

    return {
        "player_id": getattr(player, "id", None),
        "player_color": getattr(player, "color", ""),
        "round": getattr(game, "round", None),
        "turn": getattr(game, "turn", None),
        "phase": getattr(game, "phase", ""),
        "state": getattr(game, "state", ""),
        "dice_value": getattr(game, "dice_roll", 0),
    }


def _current_execution_bridge(game: Any, report: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(report, Mapping):
        value = report.get("execution_bridge")
        if isinstance(value, Mapping):
            return dict(value)
    value = getattr(game, "current_execution_bridge", None)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _current_player_choices(game: Any, player: Any) -> List[Mapping[str, Any]]:
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping) and _same_player(report.get("player_id"), player):
        values = report.get("buy_build_choices")
        if isinstance(values, list):
            return [dict(v) for v in values if isinstance(v, Mapping)]

    values = getattr(game, "current_execution_choices", []) or []
    if isinstance(values, list):
        return [dict(v) for v in values if isinstance(v, Mapping)]
    return []


def _current_player_needs(game: Any, player: Any) -> List[Mapping[str, Any]]:
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping) and _same_player(report.get("player_id"), player):
        values = report.get("strategic_needs")
        if isinstance(values, list):
            return [dict(v) for v in values if isinstance(v, Mapping)]

    values = getattr(game, "current_strategic_needs", []) or []
    if isinstance(values, list):
        return [dict(v) for v in values if isinstance(v, Mapping)]
    return []


def _hand_vector(player: Any) -> List[int]:
    method = getattr(player, "rcards_in_hand", None)
    if callable(method):
        try:
            values = method()
            # Some project versions return (hand_vector, trade_rates, trade_counts).
            if isinstance(values, (list, tuple)) and len(values) == 3 and isinstance(values[0], (list, tuple)):
                values = values[0]
            if isinstance(values, (list, tuple)) and len(values) >= 5:
                return [_safe_int(v) for v in list(values)[:5]]
        except Exception:
            pass

    cards = getattr(player, "rcards", {}) or {}
    out: List[int] = []
    for name in RESOURCE_NAMES:
        value = 0
        if isinstance(cards, Mapping):
            value = cards.get(name, cards.get(name.upper(), cards.get(name.lower(), 0)))
            if value == 0:
                for key, raw in cards.items():
                    key_name = str(getattr(key, "name", getattr(key, "value", key))).lower()
                    if key_name == name.lower():
                        value = raw
                        break
        out.append(_safe_int(value))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Best / target helpers
# ──────────────────────────────────────────────────────────────────────────────


def _best_action_or_wait(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> str:
    state = str(getattr(game, "state", "") or report.get("state", ""))
    forced = str(report.get("forced_action_mode", "") or "")
    if state == "AwaitingDiceRoll" or forced == "roll_dice":
        return "Roll dice first"
    if state in ROBBER_STATES or forced == "robber":
        return "Resolve robber / steal"

    canonical = _canonical_best_action(game)
    if canonical:
        text = str(canonical.get("best_action_text", "") or "").strip()
        if text:
            return text
        action = str(canonical.get("action", "") or "")
        best = str(canonical.get("best_action_label", "") or "")
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Build Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        return f"{verb} {best}".strip()

    actionable = [row for row in choices if isinstance(row, Mapping) and bool(row.get("actionable"))]
    if actionable:
        actionable.sort(key=lambda row: _safe_int(row.get("priority", 99)))
        first = actionable[0]
        action = str(first.get("action", ""))
        candidates = list(first.get("candidates", []) or [])
        best = _best_label_for_action(game, player, action, candidates)
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Build Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        return f"{verb} {best}".strip()

    target = _strategy_target_text(game, direction)
    if target:
        return f"Wait / Prio: {target}"
    return "No strategic buy/build action"



def _candidate_target_id(candidate: Mapping[str, Any]) -> Any:
    if not isinstance(candidate, Mapping):
        return None
    for key in ("target_id", "intersection_id", "location", "target", "id", "intersection"):
        if key in candidate:
            return candidate.get(key)
    return None


def _pips_label(pips: float) -> str:
    try:
        value = float(pips or 0)
    except Exception:
        value = 0.0
    if value <= 0:
        return ""
    text = _format_number(value)
    return f"({text} pips)"

def _best_label_for_action(game: Any, player: Any, action: str, candidates: Sequence[Any]) -> str:
    if action == BUY_DCARD:
        stack = ""
        if candidates and isinstance(candidates[0], Mapping):
            count = candidates[0].get("dcards_stack_count")
            stack = f"stack {count}" if count not in (None, "") else "buy"
        return stack or "buy"

    if action in {BUILD_CITY, BUILD_SETTLEMENT}:
        candidate = _best_intersection_candidate(game, candidates)
        if not candidate:
            return ""
        target = _candidate_target_id(candidate)
        pips = _intersection_pips(game, target)
        port = _port_label(game, target)
        parts = [f"{target}"]
        pips_text = _pips_label(pips)
        if pips_text:
            parts.append(pips_text)
        if port:
            parts.append(port)
        return " ".join(parts)

    if action == BUILD_ROAD:
        road = _best_road_candidate(player, candidates)
        if not road:
            return ""
        road_id = road.get("road_id")
        return _format_road_id(road_id)

    if action == TWB:
        if candidates and isinstance(candidates[0], Mapping):
            candidate = candidates[0]
            give = str(candidate.get("give_resource", "") or "")
            get = str(candidate.get("get_resource", "") or "")
            rate = candidate.get("rate", "")
            if give and get and rate not in (None, ""):
                return f"{rate} {give}->{get}"
            if give and get:
                return f"{give}->{get}"
        return "trade"

    return ""


def _best_intersection_candidate(game: Any, candidates: Sequence[Any]) -> Dict[str, Any]:
    valid = [dict(c) for c in candidates if isinstance(c, Mapping)]
    if not valid:
        return {}
    return max(valid, key=lambda c: (_intersection_pips(game, _candidate_target_id(c)), -_safe_int(_candidate_target_id(c) or 9999)))


def _best_road_candidate(player: Any, candidates: Sequence[Any]) -> Dict[str, Any]:
    valid = [dict(c) for c in candidates if isinstance(c, Mapping)]
    if not valid:
        return {}

    outlook = getattr(player, "outlook", None)
    paths = list(getattr(outlook, "new_settlement_paths", []) or [])
    candidate_by_road = {_road_key(c.get("road_id")): c for c in valid if _road_key(c.get("road_id"))}

    for path in paths:
        if not isinstance(path, Mapping):
            continue
        for road in list(path.get("roads_to_build", []) or []):
            key = _road_key(road)
            if key in candidate_by_road:
                return candidate_by_road[key]

    return valid[0]


def _intersection_pips(game: Any, target_id: Any) -> float:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return 0.0
    if inter is None:
        return 0.0

    for attr in ("all_tile_pips", "three_tile_pips"):
        values = getattr(inter, attr, None)
        if isinstance(values, (list, tuple)):
            try:
                return float(sum(float(v or 0) for v in values))
            except Exception:
                pass
    return 0.0


def _port_label(game: Any, target_id: Any) -> str:
    try:
        inter = game.board.intersections[int(target_id)]
    except Exception:
        return ""
    if inter is None:
        return ""
    if not bool(getattr(inter, "port_tf", False)) and str(getattr(inter, "portYN", "N")) != "Y":
        return ""
    port = str(getattr(inter, "port_type", "") or "").strip()
    return "" if port.lower() in {"", "blank"} else port.replace("Wool", "Sheep")



# ──────────────────────────────────────────────────────────────────────────────
# New tabbed-panel extraction helpers
# ──────────────────────────────────────────────────────────────────────────────





def _as_mapping_or_dict(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        try:
            data = as_dict()
            if isinstance(data, Mapping):
                return dict(data)
        except Exception:
            return None
    out: Dict[str, Any] = {}
    for key in (
        "way_id", "abstract_expected_turns", "realistic_expected_turns", "board_expected_turns",
        "best_case_turns", "fallback_case_turns", "feasibility", "fragility", "target_portfolio",
        "critical_race_targets", "branches", "recommendation", "recommendation_target_id",
        "rank_key", "needed_rcards_before", "needed_rcards_after", "requirements",
    ):
        if hasattr(value, key):
            try:
                out[key] = getattr(value, key)
            except Exception:
                pass
    return out or None


def _wrap_single_way_audit(value: Any, source: str) -> Optional[Dict[str, Any]]:
    row = _as_mapping_or_dict(value)
    if not row:
        return None
    if "realistic_expected_own_turns" not in row:
        row["realistic_expected_own_turns"] = row.get("board_expected_turns", row.get("realistic_expected_turns"))
    targets = row.get("target_portfolio") or []
    if targets and not row.get("selected_target_ids"):
        ids = []
        for t in targets:
            if isinstance(t, Mapping):
                ids.append(t.get("target_id"))
            else:
                ids.append(getattr(t, "target_id", None))
        row["selected_target_ids"] = [i for i in ids if i is not None]
    # normalize nested portfolio targets to dicts
    norm_targets = []
    for t in targets:
        if isinstance(t, Mapping):
            norm_targets.append(dict(t))
        else:
            td = _as_mapping_or_dict(t)
            if td:
                norm_targets.append(td)
    if norm_targets:
        row["target_portfolio"] = norm_targets
    return {
        "available": True,
        "selected_way_id_before_4g": row.get("way_id"),
        "candidate_way_count": 1,
        "way_audits": [row],
        "selected_way_audit": row,
        "selected_way_board_rank": 1,
        "__debug_source": source,
    }


def _wrap_way_audit_list(value: Any, source: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    items = list(value) if isinstance(value, (list, tuple)) else []
    rows: List[Dict[str, Any]] = []
    for item in items:
        wrapped = _wrap_single_way_audit(item, source)
        if wrapped and isinstance(wrapped.get("selected_way_audit"), Mapping):
            rows.append(dict(wrapped["selected_way_audit"]))
    if not rows:
        return None
    selected = rows[0]
    return {
        "available": True,
        "selected_way_id_before_4g": selected.get("way_id"),
        "candidate_way_count": len(rows),
        "way_audits": rows,
        "selected_way_audit": selected,
        "selected_way_board_rank": 1,
        "__debug_source": source,
    }


def _current_way_portfolio_audit(game: Any, report: Mapping[str, Any], direction: Mapping[str, Any], player: Any = None) -> Dict[str, Any]:
    """Return the current 4G way-portfolio audit from every visible runtime source.

    PF4 deliberately checks more than the happy path.  The audit is produced in
    action_planner.py under the by_player block and is later copied to
    Game.current_way_portfolio_audit.  During some transitions only one of those
    surfaces is populated, so the panel should look in all of them.
    """

    def _with_source(value: Any, source: str) -> Optional[Dict[str, Any]]:
        if isinstance(value, Mapping) and value:
            out = dict(value)
            out.setdefault("__debug_source", source)
            return out
        return None

    sources: List[Tuple[str, Any]] = []
    if isinstance(report, Mapping):
        sources.extend([
            ("scan.current_way_portfolio_audit", report.get("current_way_portfolio_audit")),
            ("scan.phase4g_way_portfolio_audit", report.get("phase4g_way_portfolio_audit")),
            ("scan.way_portfolio_audit", report.get("way_portfolio_audit")),
        ])
    sources.extend([
        ("game.current_way_portfolio_audit", getattr(game, "current_way_portfolio_audit", None)),
        ("game.last_way_portfolio_audit", getattr(game, "last_way_portfolio_audit", None)),
        # v035 Phase 4G surfaces (list first so candidate_way_count is correct)
        ("game.current_board_way_audits", _wrap_way_audit_list(getattr(game, "current_board_way_audits", None), "game.current_board_way_audits")),
        ("game.current_board_way_audit", _wrap_single_way_audit(getattr(game, "current_board_way_audit", None), "game.current_board_way_audit")),
    ])
    if isinstance(report, Mapping):
        sources.extend([
            ("report.board_way_audits", _wrap_way_audit_list(report.get("board_way_audits"), "report.board_way_audits")),
            ("report.board_way_audit", _wrap_single_way_audit(report.get("current_board_way_audit") or report.get("board_way_audit"), "report.board_way_audit")),
        ])
    if isinstance(direction, Mapping):
        sources.extend([
            ("direction.phase4g_way_portfolio_audit", direction.get("phase4g_way_portfolio_audit")),
            ("direction.current_way_portfolio_audit", direction.get("current_way_portfolio_audit")),
            ("direction.way_portfolio_audit", direction.get("way_portfolio_audit")),
        ])
        for key in ("selected_way_audit", "phase4g_selected_way_audit", "current_way_audit"):
            value = direction.get(key)
            if isinstance(value, Mapping) and value:
                sources.append((f"direction.{key}", {
                    "available": True,
                    "selected_way_id_before_4g": _way_id(direction),
                    "candidate_way_count": 1,
                    "way_audits": [dict(value)],
                    "selected_way_audit": dict(value),
                }))

    # Also inspect the original action-planner report.  This is the most useful
    # fallback when Game.current_way_portfolio_audit was not copied into the scan.
    action_report = getattr(game, "last_action_timing_report", None)
    if isinstance(action_report, Mapping):
        sources.extend([
            ("action_report.phase4g_way_portfolio_audit", action_report.get("phase4g_way_portfolio_audit")),
            ("action_report.current_way_portfolio_audit", action_report.get("current_way_portfolio_audit")),
            ("action_report.board_way_audits", _wrap_way_audit_list(action_report.get("board_way_audits"), "action_report.board_way_audits")),
        ])
        by_player = action_report.get("by_player", {}) if isinstance(action_report.get("by_player", {}), Mapping) else {}
        pid_values: List[str] = []
        if player is not None:
            pid_values.append(str(_safe_int(getattr(player, "id", None), -999999)))
            pid_values.append(str(getattr(player, "id", "")))
        if isinstance(report, Mapping) and report.get("player_id") not in (None, ""):
            pid_values.append(str(report.get("player_id")))
        for pid in [p for p in pid_values if p not in ("", "-999999")]:
            block = by_player.get(pid)
            if not isinstance(block, Mapping):
                continue
            sources.append((f"action_report.by_player[{pid}].phase4g_way_portfolio_audit", block.get("phase4g_way_portfolio_audit")))
            preferred = block.get("preferred_strategy", {}) if isinstance(block.get("preferred_strategy", {}), Mapping) else {}
            sources.append((f"action_report.by_player[{pid}].preferred.phase4g_way_portfolio_audit", preferred.get("phase4g_way_portfolio_audit")))

    for source, value in sources:
        out = _with_source(value, source)
        if out is not None:
            return out
    return {}


def _selected_way_audit(portfolio_audit: Mapping[str, Any], direction: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the selected way-audit row, with defensive fallbacks.

    This is the important fix: the previous implementation could fail to find
    the row whenever selected ids were absent/mismatched, even though the audit
    contained one or more way_audits with the desired portfolio.  For debugging,
    showing the best available concrete portfolio is better than hiding it.
    """
    if not isinstance(portfolio_audit, Mapping) or not portfolio_audit:
        return {}

    if isinstance(portfolio_audit.get("portfolio"), Mapping) and portfolio_audit.get("way_id") not in (None, ""):
        return dict(portfolio_audit)

    rows = [dict(row) for row in list(portfolio_audit.get("way_audits", []) or []) if isinstance(row, Mapping)]

    # Prefer preferred_way_id / way_id from direction first (keep-abstract case).
    # Do this BEFORE trusting selected_way_audit blobs — those often hold board#1 only.
    candidate_ids: List[Any] = []
    if isinstance(direction, Mapping):
        for key in ("preferred_way_id", "way_id"):
            value = direction.get(key)
            if value not in (None, "", "-"):
                candidate_ids.append(value)
    for source in (portfolio_audit, direction):
        if not isinstance(source, Mapping):
            continue
        for key in (
            "selected_way_id_before_4g",
            "selected_way_id",
            "preferred_way_id",
            "way_id",
            "phase4g_selected_way_id",
            "current_way_id",
        ):
            value = source.get(key)
            if value not in (None, "", "-"):
                candidate_ids.append(value)

    # Match preferred way in way_audits list first
    if rows:
        for value in candidate_ids:
            want_int = _safe_int(value, -999999)
            want_text = str(value)
            for row in rows:
                row_id = row.get("way_id", row.get("preferred_way_id", row.get("phase4g_way_id", "")))
                if str(row_id) == want_text or _safe_int(row_id, -999998) == want_int:
                    out = dict(row)
                    out.setdefault("debug_selected_fallback", "preferred_or_selected_way_id")
                    return out

    # Nested selected_* only if it matches preferred (or no preferred known)
    pref_want = candidate_ids[0] if candidate_ids else None
    for key in ("selected_way_audit", "selected_audit", "current_way_audit", "phase4g_selected_way_audit"):
        value = portfolio_audit.get(key)
        if not isinstance(value, Mapping) or not value:
            continue
        row_id = value.get("way_id", value.get("preferred_way_id", ""))
        if pref_want in (None, "", "-") or str(row_id) == str(pref_want) or _safe_int(row_id, -1) == _safe_int(pref_want, -2):
            return dict(value)

    if not rows:
        return {}

    # Explicit builder marker
    for row in rows:
        if bool(row.get("is_selected_way_before_4g")):
            return dict(row)

    # If the selected-way id is unavailable, prefer the board-realistic best row.
    best_id = portfolio_audit.get("best_board_realistic_way_id")
    if best_id not in (None, "", "-"):
        best_int = _safe_int(best_id, -999997)
        for row in rows:
            row_id = row.get("way_id", row.get("preferred_way_id", ""))
            if str(row_id) == str(best_id) or _safe_int(row_id, -999998) == best_int:
                out = dict(row)
                out.setdefault("debug_selected_fallback", "best_board_realistic_way")
                return out

    # Final debug fallback: show the first ranked audit instead of hiding the portfolio.
    out = dict(rows[0])
    out.setdefault("debug_selected_fallback", "first_ranked_way_audit")
    return out



def _synthetic_selected_way_audit_from_runtime(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> Dict[str, Any]:
    """Last-resort portfolio surface built from live runtime data.

    This is not strategic authority.  It only prevents the PROJ tab from
    collapsing to active-project-only when the formal audit was not attached to
    the scan.  Formal audit rows remain preferred whenever they exist.
    """
    if player is None:
        return {}
    new_targets = _runtime_new_settlement_targets(game, player, direction, project, authority, max_targets=8)
    city_targets = _runtime_city_targets(game, player, direction, max_targets=5)
    if not new_targets and not city_targets:
        return {}
    new_req = _required_from_direction_tags(direction, "Settle", default=len(new_targets) or 0)
    city_req = _required_from_direction_tags(direction, "City", default=len(city_targets) or 0)
    selected = {
        "way_id": _way_id(direction),
        "feasibility": "runtime",
        "fragility": "unknown",
        "debug_selected_fallback": "runtime_synthetic_from_outlook/project",
        "portfolio": {
            "bucket_schema": "debug_runtime_synthetic",
            "new_intersection_portfolio": {
                "bucket": "new_intersections",
                "selected_targets": new_targets,
                "target_count_required": int(new_req),
                "target_count_selected": len(new_targets),
                "enough_targets": len(new_targets) >= int(new_req or 0),
            },
            "city_upgrade_portfolio": {
                "bucket": "city_upgrades",
                "selected_targets": city_targets,
                "target_count_required": int(city_req),
                "target_count_selected": len(city_targets),
                "enough_targets": len(city_targets) >= int(city_req or 0),
            },
            "selected_targets": new_targets,
            "target_count_required": int(new_req),
            "target_count_selected": len(new_targets),
        },
        "recalculated_requirements": {
            "new_intersection_count_required": int(new_req),
            "new_intersection_count_selected": len(new_targets),
            "city_upgrade_count_required": int(city_req),
            "city_upgrade_count_selected": len(city_targets),
        },
    }
    return selected


def _runtime_new_settlement_targets(game: Any, player: Any, direction: Mapping[str, Any], project: Mapping[str, Any], authority: Mapping[str, Any], *, max_targets: int = 8) -> List[Mapping[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set = set()

    def add(row: Mapping[str, Any]) -> None:
        tid = _target_id_from_mapping(row)
        key = str(tid)
        if key in seen or key in {"", "-"}:
            return
        seen.add(key)
        rows.append(dict(row))

    active_target = _first_nonempty(project, ("target_id", "active_target_id"), authority.get("active_target_id")) if isinstance(project, Mapping) else authority.get("active_target_id")
    if active_target not in (None, "", "-"):
        route = _first_nonempty(project, ("route_roads_to_build", "roads_to_build"), []) if isinstance(project, Mapping) else []
        if not route and isinstance(authority, Mapping):
            first = _mapping(authority.get("first_action"))
            route = [first.get("road_id")] if first.get("road_id") not in (None, "") else []
        add({
            "target_id": active_target,
            "target_kind": _first_nonempty(project, ("project_type", "type"), "new_settlement") if isinstance(project, Mapping) else "new_settlement",
            "portfolio_role": _first_nonempty(project, ("project_priority_tier", "urgency"), "active" ) if isinstance(project, Mapping) else "active",
            "must_race": "race" in str(_first_nonempty(project, ("project_priority_tier", "urgency"), "") if isinstance(project, Mapping) else "").lower(),
            "route_roads_to_build": route,
            "roads_needed": len(list(route or [])),
            "opponent_race": project.get("opponent_race", {}) if isinstance(project, Mapping) else {},
            "resource_gain_named": project.get("resource_gain_named", {}) if isinstance(project, Mapping) else {},
        })

    outlook = getattr(player, "outlook", None)
    if outlook is not None:
        for raw in list(getattr(outlook, "next_settlement_plans", []) or []):
            if isinstance(raw, Mapping):
                row = dict(raw)
                row.setdefault("target_id", row.get("intersection_id", row.get("target_settlement_id")))
                row.setdefault("target_kind", "next_settlement")
                row.setdefault("roads_needed", 0)
                row.setdefault("portfolio_role", "safe")
                add(row)
        for raw in list(getattr(outlook, "new_settlement_paths", []) or []):
            if isinstance(raw, Mapping):
                row = dict(raw)
                row.setdefault("target_id", row.get("intersection_id", row.get("target_settlement_id")))
                row.setdefault("target_kind", "new_settlement")
                roads = row.get("roads_to_build", row.get("route_roads_to_build", [])) or []
                row.setdefault("route_roads_to_build", roads)
                row.setdefault("roads_needed", row.get("road_count", row.get("roads_remaining", len(list(roads or [])))))
                row.setdefault("portfolio_role", "frontier")
                add(row)
        for tid in list(getattr(outlook, "next_settlements", []) or []):
            add({"target_id": tid, "target_kind": "next_settlement", "roads_needed": 0, "portfolio_role": "safe"})

    return rows[:max_targets]


def _runtime_city_targets(game: Any, player: Any, direction: Mapping[str, Any], *, max_targets: int = 5) -> List[Mapping[str, Any]]:
    rows: List[Dict[str, Any]] = []
    cities = set(_safe_int(v, -999999) for v in list(getattr(player, "cities", []) or []))
    for sid in list(getattr(player, "settlements", []) or []):
        try:
            sid_int = int(sid)
        except Exception:
            continue
        if sid_int in cities:
            continue
        rows.append({"target_id": sid_int, "target_kind": "city_upgrade", "portfolio_role": "city_upgrade", "roads_needed": 0})
    return rows[:max_targets]


def _required_from_direction_tags(direction: Mapping[str, Any], root: str, default: int = 0) -> int:
    for tag in _strategy_tags(direction):
        parts = str(tag).split()
        if not parts:
            continue
        if parts[-1].lower().startswith(root.lower()):
            try:
                return int(parts[0])
            except Exception:
                return max(1, int(default or 0))
    # Check common structured fields as a fallback.
    summary = direction.get("strategy_summary", {}) if isinstance(direction.get("strategy_summary", {}), Mapping) else {}
    remaining = direction.get("remaining", {}) if isinstance(direction.get("remaining", {}), Mapping) else {}
    keys = ("cities", "city_upgrades", "remaining_city_upgrades") if root == "City" else ("settlements", "new_settlements", "remaining_new_settlements")
    for source in (summary, remaining, direction):
        value = _positive_from(source, keys) if isinstance(source, Mapping) else 0
        if value > 0:
            return int(value)
    return int(default or 0)


def _portfolio_required_city_count(selected_audit: Mapping[str, Any], direction: Mapping[str, Any]) -> int:
    req = selected_audit.get("recalculated_requirements", {}) if isinstance(selected_audit.get("recalculated_requirements", {}), Mapping) else {}
    value = _first_nonempty(req, ("city_upgrade_count_required",), "")
    if value not in (None, ""):
        return _safe_int(value, 0)
    return _required_from_direction_tags(direction, "City", 0)


def _vp_path_text(
    selected_audit: Mapping[str, Any],
    direction: Mapping[str, Any],
    req: Mapping[str, Any],
    way_req: Mapping[str, Any],
) -> str:
    """Compact VP composition note (Need New/City counts are builds, not VP)."""
    parts: List[str] = []
    rem = direction.get("remaining") if isinstance(direction, Mapping) and isinstance(direction.get("remaining"), Mapping) else {}
    cities = _safe_int(_first_nonempty(req, ("required_cities", "city_upgrade_count_required"), way_req.get("required_cities", rem.get("cities", 0))), 0)
    new_s = _safe_int(_first_nonempty(req, ("required_new_intersections", "new_intersection_count_required"), way_req.get("required_new_intersections", rem.get("new_settlements", 0))), 0)
    if cities > 0:
        parts.append(f"{cities} city")
    if new_s > 0:
        parts.append(f"{new_s} new")
    tags = " ".join(_strategy_tags(direction)).lower() if isinstance(direction, Mapping) else ""
    ba = bool(req.get("biggest_army")) or bool(selected_audit.get("biggest_army")) or ("largest army" in tags or "biggest army" in tags)
    lr = bool(req.get("longest_road")) or bool(selected_audit.get("longest_road")) or ("longest road" in tags)
    if isinstance(req, Mapping) and req.get("biggest_army") is False:
        ba = ba and ("army" in tags)
    # requirements may store flags under nested / bool from CSV via requirements dict
    if bool(req.get("biggest_army")) or bool((selected_audit.get("requirements") or {}).get("biggest_army") if isinstance(selected_audit.get("requirements"), Mapping) else False):
        ba = True
    if bool(req.get("longest_road")) or bool((selected_audit.get("requirements") or {}).get("longest_road") if isinstance(selected_audit.get("requirements"), Mapping) else False):
        lr = True
    if ba:
        parts.append("BA")
    if lr:
        parts.append("LR")
    vp_cards = _safe_int(_first_nonempty(req, ("victory_point_cards", "required_vp_cards", "vp_cards"), way_req.get("victory_point_cards", 0)), 0)
    if vp_cards <= 0 and isinstance(direction, Mapping):
        for tag in _strategy_tags(direction):
            tl = str(tag).lower()
            if "vp" in tl:
                try:
                    vp_cards = max(vp_cards, int(str(tag).split()[0]))
                except Exception:
                    pass
    if vp_cards > 0:
        parts.append(f"{vp_cards} VPc")
    dcards = _safe_int(_first_nonempty(req, ("required_dcards", "development_cards_to_buy"), way_req.get("development_cards", rem.get("development_cards", 0))), 0)
    if dcards > 0:
        parts.append(f"{dcards} dev")
    total_vp = _first_nonempty(req, ("total_victory_points", "total_vp"), way_req.get("total_victory_points", selected_audit.get("total_victory_points", "")))
    suffix = f" → target {total_vp} VP" if total_vp not in (None, "") else " (builds≠VP)"
    if not parts:
        return f"VP path: unknown{suffix}"
    return _fit_text("VP path: " + " + ".join(parts) + suffix, 62)


def _portfolio_summary_rows(portfolio_audit: Mapping[str, Any], selected_audit: Mapping[str, Any], direction: Mapping[str, Any]) -> List[str]:
    """PROJ summary: way · feas · turns · frag + Need Road|NewS|City|DC.

    Rank lives in WAYS. VP composition lives in STR tags.
    """
    del portfolio_audit  # rank intentionally owned by WAYS
    rows: List[str] = []
    way = _first_nonempty(selected_audit, ("way_id", "preferred_way_id"), _way_id(direction))
    feasibility = str(selected_audit.get("feasibility", "") or "-")
    turns = _format_short_turns(
        _first_nonempty(
            selected_audit,
            ("realistic_expected_own_turns", "board_expected_turns", "portfolio_expected_own_turns"),
            "",
        )
    )
    frag = str(selected_audit.get("fragility", "") or "-")
    head = f"Way {way if way not in (None, '') else '-'} · {feasibility}"
    if turns:
        head += f" · {turns}"
    if frag not in (None, "", "-"):
        head += f" · frag {frag}"
    rows.append(head)

    need_line = _portfolio_need_remaining_text(selected_audit, direction)
    if need_line:
        rows.append(need_line)
    return rows


def _portfolio_need_remaining_text(selected_audit: Mapping[str, Any], direction: Mapping[str, Any]) -> str:
    """Need: Road n | NewS n | City n | DC n (remaining counts)."""
    req = selected_audit.get("recalculated_requirements", {}) if isinstance(selected_audit.get("recalculated_requirements", {}), Mapping) else {}
    if not req and isinstance(selected_audit.get("requirements"), Mapping):
        req = dict(selected_audit.get("requirements") or {})
    way_req = selected_audit.get("way_requirements", {}) if isinstance(selected_audit.get("way_requirements", {}), Mapping) else {}
    if not way_req and isinstance(direction, Mapping) and isinstance(direction.get("way_requirements"), Mapping):
        way_req = dict(direction.get("way_requirements") or {})
    remaining = direction.get("remaining", {}) if isinstance(direction, Mapping) and isinstance(direction.get("remaining"), Mapping) else {}

    # Prefer concrete portfolio road total: direction.remaining.roads is often 0
    # even when targets still need roads (@38 1r + @42 2r → Road 3).
    roads = _portfolio_road_need_from_targets(selected_audit)
    if roads in (None, ""):
        roads = _first_nonempty(
            remaining,
            ("roads", "roads_to_build"),
            _first_nonempty(req, ("roads_to_build", "required_roads"), way_req.get("roads_to_build", "")),
        )

    news = _first_nonempty(
        remaining,
        ("new_settlements", "settlements"),
        _first_nonempty(
            req,
            ("new_intersection_count_required", "required_new_intersections"),
            way_req.get("required_new_intersections", way_req.get("new_settlements", "")),
        ),
    )
    cities = _first_nonempty(
        remaining,
        ("cities", "city_upgrades"),
        _first_nonempty(
            req,
            ("city_upgrade_count_required", "required_cities"),
            way_req.get("required_cities", way_req.get("cities", "")),
        ),
    )
    # DC: prefer joint composition estimate (LA+2VP≈10) over additive engine 16
    way = _first_nonempty(selected_audit, ("way_id", "preferred_way_id"), _way_id(direction) if isinstance(direction, Mapping) else "")
    comp = _way_composition(way)
    joint_dc = ""
    if comp:
        joint_dc = _joint_dc_buy_estimate(
            largest_army=bool(comp.get("largest_army") or comp.get("biggest_army")),
            vp_cards=int(comp.get("victory_point_cards") or 0),
            listed_dc=int(comp.get("listed_dc_buys") or 0),
        )
        # If player already bought some DCs, scale remaining from engine if lower
        engine_rem = _first_nonempty(
            remaining,
            ("development_cards", "dcards"),
            _first_nonempty(req, ("required_dcards", "development_cards_to_buy"), way_req.get("development_cards", "")),
        )
        if engine_rem not in (None, "") and _safe_int(engine_rem, 0) > 0:
            # Keep joint as the composition ceiling; if engine remaining is lower
            # (progress already made), show engine remaining.
            expected_full = int(comp.get("expected_dc_buys") or 0) or joint_dc
            if expected_full > 0 and _safe_int(engine_rem, 0) < expected_full:
                # Remaining progress fraction applied to joint estimate
                frac = _safe_int(engine_rem, 0) / float(expected_full)
                joint_dc = max(0, int(round(joint_dc * frac)))
    if joint_dc not in (None, "", 0):
        dcards = joint_dc
    else:
        dcards = _first_nonempty(
            remaining,
            ("development_cards", "dcards"),
            _first_nonempty(
                req,
                ("required_dcards", "development_cards_to_buy"),
                way_req.get("development_cards", way_req.get("development_cards_to_buy", "")),
            ),
        )
    return (
        f"Need: Road {roads if roads not in (None, '') else '-'} | "
        f"NewS {news if news not in (None, '') else '-'} | "
        f"City {cities if cities not in (None, '') else '-'} | "
        f"DC {dcards if dcards not in (None, '') else '-'}"
    )


def _portfolio_road_need_from_targets(selected_audit: Mapping[str, Any]) -> Any:
    total = 0
    seen = False
    for target in _portfolio_target_list(selected_audit, "new"):
        count = _target_road_cost_count(target)
        if count is None:
            for key in ("distance_roads", "roads_needed", "road_count"):
                if target.get(key) not in (None, ""):
                    count = _safe_int(target.get(key), 0)
                    break
        if count is not None:
            total += int(count)
            seen = True
    return total if seen else ""


def _portfolio_board_rank(
    portfolio_audit: Mapping[str, Any],
    selected_audit: Mapping[str, Any],
    direction: Mapping[str, Any],
) -> Tuple[Any, Any]:
    """Return (rank, candidate_count) for WAYS ownership."""
    way = _first_nonempty(selected_audit, ("way_id", "preferred_way_id"), _way_id(direction)) if isinstance(selected_audit, Mapping) else _way_id(direction)
    rank = _first_nonempty(portfolio_audit, ("selected_way_board_rank", "phase4g_selected_way_board_rank"), "") if isinstance(portfolio_audit, Mapping) else ""
    count = _first_nonempty(portfolio_audit, ("candidate_way_count", "way_count"), "") if isinstance(portfolio_audit, Mapping) else ""
    ways_list = [a for a in list((portfolio_audit or {}).get("way_audits", []) or []) if isinstance(a, Mapping)] if isinstance(portfolio_audit, Mapping) else []
    if ways_list:
        count = len(ways_list)
        for i, row in enumerate(ways_list, start=1):
            if _safe_int(row.get("way_id"), -1) == _safe_int(way, -2):
                rank = i
                break
        else:
            rank = rank if rank not in (None, "") else "?"
    return rank, count


def _portfolio_next_step_line(
    direction: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
    selected_audit: Mapping[str, Any],
) -> str:
    """Optional one-line Next pointer on PROJ (full sequence lives in PLAN)."""
    if isinstance(project, Mapping) and project:
        race = _project_race_text(project)
        first = _mapping(project.get("first_action")) or _mapping(authority.get("first_action") if isinstance(authority, Mapping) else {})
        route = _project_route_text(project, first)
        tid = _first_nonempty(project, ("target_id", "active_target_id"), "")
        if race or route or tid not in (None, ""):
            bits = []
            if race:
                bits.append(race)
            elif tid not in (None, ""):
                bits.append(f"@{_target_label(tid).lstrip('@')}")
            if route:
                bits.append(route.replace("Route: ", "") if str(route).startswith("Route:") else str(route))
            return "Next: " + " · ".join(str(b) for b in bits if b)
    if isinstance(direction, Mapping):
        support = direction.get("supporting_action_type")
        tid = _first_nonempty(
            direction,
            ("recommendation_target_id", "supporting_action_future_settlement_target_id", "supporting_action_target_id"),
            "",
        )
        roads = direction.get("roads_to_build")
        if support or tid not in (None, "") or roads:
            bits = []
            if support:
                bits.append(str(support))
            if tid not in (None, ""):
                bits.append(f"@{_target_label(tid).lstrip('@')}")
            if roads:
                bits.append(str(roads))
            return "Next: " + " · ".join(bits)
    # Fallback: first portfolio target
    targets = _portfolio_target_list(selected_audit, "new") if isinstance(selected_audit, Mapping) else []
    if targets:
        t0 = targets[0]
        role = _first_nonempty(t0, ("portfolio_role", "race_status"), "")
        return f"Next: {_portfolio_settlement_target_row(t0)}" if not role else f"Next: {role} {_target_label(_target_id_from_mapping(t0))}"
    return ""


def _portfolio_target_list(selected_audit: Mapping[str, Any], bucket: str) -> List[Mapping[str, Any]]:
    """Extract selected portfolio target rows across all known Phase-4G shapes."""
    if not isinstance(selected_audit, Mapping):
        return []
    portfolio = selected_audit.get("portfolio", {}) if isinstance(selected_audit.get("portfolio", {}), Mapping) else {}
    if bucket == "city":
        city_bucket = portfolio.get("city_upgrade_portfolio", {}) if isinstance(portfolio.get("city_upgrade_portfolio", {}), Mapping) else {}
        values = (
            city_bucket.get("selected_targets")
            or city_bucket.get("targets")
            or selected_audit.get("city_upgrade_targets")
            or selected_audit.get("city_targets")
            or portfolio.get("city_upgrade_targets")
            or portfolio.get("city_targets")
            or []
        )
    else:
        new_bucket = portfolio.get("new_intersection_portfolio", {}) if isinstance(portfolio.get("new_intersection_portfolio", {}), Mapping) else {}
        # v035 ai_way_portfolio: flat target_portfolio of new_settlement rows
        values = (
            new_bucket.get("selected_targets")
            or new_bucket.get("targets")
            or new_bucket.get("recommended_targets")
            or portfolio.get("selected_targets")
            or portfolio.get("new_intersection_targets")
            or selected_audit.get("selected_targets")
            or selected_audit.get("new_intersection_targets")
            or selected_audit.get("next_settlement_targets")
            or selected_audit.get("new_settlement_targets")
            or selected_audit.get("target_portfolio")
            or []
        )
    if isinstance(values, Mapping):
        values = list(values.values())
    return [dict(t) for t in list(values or []) if isinstance(t, Mapping)]


def _portfolio_new_target_rows(selected_audit: Mapping[str, Any], *, max_rows: int = 4) -> List[str]:
    """List new settlement targets. Show all when count ≤ max_rows (default 4)."""
    selected = _portfolio_target_list(selected_audit, "new")
    out: List[str] = []
    show = selected if len(selected) <= max_rows else selected[:max_rows]
    for target in show:
        out.append(_portfolio_settlement_target_row(target))
    hidden = max(0, len(selected) - len(show))
    if hidden:
        out.append(f"+ {hidden} more new targets")
    return out


def _portfolio_city_targets_row(selected_audit: Mapping[str, Any], *, max_targets: int = 3) -> str:
    selected = _portfolio_target_list(selected_audit, "city")
    if not selected:
        return ""
    parts: List[str] = []
    for target in selected[:max_targets]:
        tid = _target_label(_target_id_from_mapping(target))
        turns = _target_turns_text(target)
        score = _target_score_text(target)
        detail = turns or score
        parts.append(f"{tid} {detail}".strip())
    if len(selected) > max_targets:
        parts.append(f"+{len(selected) - max_targets}")
    return "Cities: " + " | ".join(parts)


def _portfolio_settlement_target_row(target: Mapping[str, Any]) -> str:
    tid = _target_label(_target_id_from_mapping(target))
    status = _race_status_code(target)
    roads = _target_road_cost_text(target)
    bits = [tid, status, roads]
    turns = _target_turns_text(target)
    if turns:
        bits.append(f"me{turns}")
    racers = _target_racer_text(target, max_racers=2)
    if racers:
        bits.append(racers)
    gain = _target_gain_text(target)
    if gain:
        bits.append(gain)
    return _fit_text(" ".join(bits), 58)


def _target_id_from_mapping(target: Mapping[str, Any]) -> Any:
    return _first_nonempty(target, ("target_id", "future_settlement_target_id", "intersection_id", "active_target_id"), "-")


def _race_status_code(value: Any) -> str:
    if isinstance(value, Mapping):
        target = value
        if bool(target.get("must_race")):
            return "MR"
        if bool(target.get("valuable_contested")):
            return "R"
        if bool(target.get("likely_lost")):
            return "LL"
        if bool(target.get("safe_can_wait")):
            return "S"
        value = _first_nonempty(target, ("race_status", "race_risk", "urgency", "portfolio_role"), "safe")
    text = str(value or "").strip().lower()
    if text in {"must_race", "must-race", "critical", "high", "contested_high"}:
        return "MR"
    if text in {"contested", "race", "medium", "med", "valuable_contested"}:
        return "R"
    if text in {"likely_lost", "lost", "blocked"}:
        return "LL"
    if text in {"safe_can_wait", "safe", "low", "city_bucket", "city_upgrade"}:
        return "S"
    return text[:3].upper() if text else "S"


def _target_turns_text(target: Mapping[str, Any]) -> str:
    race = target.get("opponent_race") if isinstance(target.get("opponent_race"), Mapping) else {}
    for value in (
        target.get("my_turns_to_settle_target"),
        target.get("action_expected_own_turns"),
        target.get("expected_own_turns"),
        target.get("realistic_expected_own_turns"),
        race.get("my_turns_to_settle_target") if isinstance(race, Mapping) else None,
    ):
        text = _format_short_turns(value)
        if text:
            return text
    return ""


def _target_racer_text(target: Mapping[str, Any], *, max_racers: int = 2) -> str:
    race = target.get("opponent_race") if isinstance(target.get("opponent_race"), Mapping) else {}
    racers: List[Mapping[str, Any]] = []
    for key in ("opponent_racers", "racers", "opponents"):
        value = target.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            value = race.get(key) if isinstance(race, Mapping) else None
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            racers = [r for r in list(value) if isinstance(r, Mapping)]
            if racers:
                break
    parts: List[str] = []
    for racer in racers[:max_racers]:
        pid = _first_nonempty(racer, ("player_id", "opponent_id", "id"), "?")
        turns = _format_short_turns(_first_nonempty(racer, ("turns_to_settle_target", "opponent_turns_to_settle_target", "expected_own_turns", "turns"), ""))
        parts.append(f"P{pid} {turns}".strip())
    if racers and len(racers) > max_racers:
        parts.append(f"+{len(racers) - max_racers}opp")
    if parts:
        return " ".join(parts)

    # Current core diagnostics may expose only the fastest opponent as a flat opponent_race dict.
    if isinstance(race, Mapping):
        pid = _first_nonempty(race, ("opponent_id", "best_opponent_id", "threat_player_id"), "")
        turns = _format_short_turns(_first_nonempty(race, ("opponent_turns_to_settle_target", "best_opponent_turns_to_settle_target"), ""))
        if pid not in (None, "") and turns:
            return f"P{pid} {turns}"
        if turns:
            return f"opp {turns}"
    return ""


def _target_score_text(target: Mapping[str, Any]) -> str:
    score = _first_nonempty(target, ("resource_role_score", "score", "target_score"), "")
    try:
        if score not in (None, ""):
            return _format_number(float(score))
    except Exception:
        pass
    return ""


def _target_gain_text(target: Mapping[str, Any]) -> str:
    gain = target.get("resource_gain_named") if isinstance(target.get("resource_gain_named"), Mapping) else {}
    text = _compact_named_gain(gain)
    if text:
        return "+" + text
    port = str(_first_nonempty(target, ("port_label", "target_port_label", "future_settlement_port_label"), "") or "")
    if port:
        return port.replace(" ", "")
    score = _target_score_text(target)
    return score


def _rows_remaining(y: int, line_h: int, panel: pygame.Rect, already_queued: int = 0) -> int:
    return max(0, int((panel.bottom - y) / max(1, line_h)) - int(already_queued))

def _project_authority(game: Any, report: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(report, Mapping):
        value = report.get("phase4g_project_authority")
        if isinstance(value, Mapping):
            return dict(value)
    value = getattr(game, "phase4g_project_authority", None)
    if isinstance(value, Mapping):
        return dict(value)
    audit = getattr(game, "current_way_portfolio_audit", None)
    if isinstance(audit, Mapping):
        value = audit.get("phase4g_project_authority")
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _current_ai_turn_plan(game: Any, report: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(report, Mapping):
        value = report.get("current_ai_turn_plan")
        if isinstance(value, Mapping):
            return dict(value)
    value = getattr(game, "current_ai_turn_plan", None)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _active_project_from_context(
    game: Any,
    report: Mapping[str, Any],
    authority: Mapping[str, Any],
    best_action: Mapping[str, Any],
    direction: Mapping[str, Any],
) -> Dict[str, Any]:
    if isinstance(authority, Mapping):
        project = authority.get("project")
        if isinstance(project, Mapping) and project:
            out = dict(project)
            out.setdefault("project_id", authority.get("active_project_id"))
            out.setdefault("target_id", authority.get("active_target_id"))
            out.setdefault("project_score", authority.get("project_score"))
            out.setdefault("project_priority_tier", authority.get("project_priority_tier"))
            return out
    for source in (best_action, report, getattr(game, "current_way_portfolio_audit", None), direction):
        if not isinstance(source, Mapping):
            continue
        for key in (
            "phase4g_board_project_activation",
            "phase4g_project_priority_override",
            "phase4g_active_project",
            "selected_way_active_project",
            "recommended_project",
        ):
            value = source.get(key)
            if isinstance(value, Mapping) and value:
                project = value.get("project") if isinstance(value.get("project"), Mapping) else value
                if isinstance(project, Mapping) and project:
                    return dict(project)
    return {}


def _best_action_display_text(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> str:
    """Return Best-Action text without dice/robber forced-flow instructions.

    Prefer continue-plan step 1 when present so sticky BA matches SCAN Plan.
    """
    del report  # reserved for future preview cross-check
    # Align sticky BA with SCAN planned sequence (same source of truth).
    try:
        plan_rows = _planned_sequence_rows(game)
        if plan_rows:
            label = str(plan_rows[0].get("label") or "").strip()
            if label:
                return _compact_best_action_text(label)
    except Exception:
        pass

    canonical = _canonical_best_action(game)
    if canonical:
        text = str(canonical.get("best_action_text", "") or "").strip()
        if text:
            return _compact_best_action_text(text)
        action = str(canonical.get("action", "") or "")
        best = str(canonical.get("best_action_label", "") or "")
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        if action and action not in {"Roll dice", "Resolve robber"}:
            return _compact_best_action_text(f"{verb} {best}".strip())

    # Do not fall back to Roll dice / robber copy here. That belongs to the
    # button panel.  Only show strategic/actionable state if available.
    actionable = [row for row in choices if isinstance(row, Mapping) and bool(row.get("actionable"))]
    if actionable:
        actionable.sort(key=lambda row: _safe_int(row.get("priority", 99)))
        first = actionable[0]
        action = str(first.get("action", ""))
        candidates = list(first.get("candidates", []) or [])
        best = _best_label_for_action(game, player, action, candidates)
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        return _compact_best_action_text(f"{verb} {best}".strip())

    target = _strategy_target_text(game, direction)
    if target:
        return _compact_best_action_text(str(target))
    return "—"


def _compact_best_action_text(text: str) -> str:
    """Normalize BA phrasing: 'Wait / Prio: road [27,38]' → 'Road [27, 38]'."""
    raw = str(text or "").strip()
    if not raw:
        return "—"
    lower = raw.lower()
    # Strip wait/prio wrappers
    for prefix in ("wait / prio:", "wait/prio:", "prio:", "wait:"):
        if lower.startswith(prefix):
            raw = raw[len(prefix):].strip()
            lower = raw.lower()
            break
    # Capitalize road/settle/city verbs for sticky density
    if lower.startswith("road "):
        raw = "Road " + raw[5:].strip()
    elif lower.startswith("build road"):
        raw = "Road " + raw[len("build road"):].strip()
    # Space after commas in road lists: [27,38] → [27, 38]
    raw = raw.replace(", ", ",").replace(",", ", ")
    return raw


def _collect_execution_debug_warnings(
    game: Any,
    player: Any,
    report: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    direction: Mapping[str, Any],
    authority: Mapping[str, Any],
    best_action: Mapping[str, Any],
    turn_plan: Mapping[str, Any],
    active_project: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []

    def add(tab: str, code: str, text: str) -> None:
        warnings.append({"tab": tab, "code": code, "text": text})

    if not choices and str(getattr(game, "state", "") or "") == "ActionSelection":
        add("SCAN", "EMPTY", "ActionSelection but no scan choices visible")

    if isinstance(direction, Mapping) and direction:
        for key in ("phase4g_would_switch_way", "would_switch_way", "strategy_would_switch"):
            if bool(direction.get(key, False)):
                add("STR", "SWITCH", "Selected way may no longer be board-best")
                break
    else:
        add("STR", "NONE", "No strategic_direction visible")

    selected_audit = _selected_way_audit(portfolio_audit, direction)
    if isinstance(direction, Mapping) and direction and not selected_audit:
        add("PROJ", "NOPORT", "No selected-way portfolio visible")
    elif isinstance(selected_audit, Mapping) and selected_audit:
        feasibility = str(selected_audit.get("feasibility", "") or "").lower()
        fragility = str(selected_audit.get("fragility", "") or "").lower()
        if feasibility == "unrealistic":
            add("PROJ", "UNREAL", "Selected portfolio is unrealistic")
        elif feasibility == "fragile" or fragility == "high":
            add("PROJ", "FRAG", "Selected portfolio is fragile")

    auth_active = bool(authority.get("active")) if isinstance(authority, Mapping) else False
    if auth_active:
        if not authority.get("active_project_id"):
            add("PROJ", "NOID", "Authority active but project id missing")
        if not authority.get("exact_action_lock"):
            add("AUTH", "LOCK", "Authority active but exact lock missing")
        if best_action and not _best_action_matches_authority(best_action, authority):
            add("AUTH", "BA", "Best-Action not visibly tied to authority")
    # Authority is optional until phase4g_project_authority is wired.
    # Missing authority is n/a, not a red AUTH! warning.

    if isinstance(active_project, Mapping) and active_project:
        first = _mapping(active_project.get("first_action"))
        if not first and not _mapping(authority.get("first_action")):
            add("PROJ", "NOFIRST", "Project has no first action visible")

    if _has_key(report, "execution_preview_matches_best_action") and not bool(report.get("execution_preview_matches_best_action")):
        add("PLAN", "PREVIEW", "Execution preview differs from Best-Action")
    if isinstance(turn_plan, Mapping) and turn_plan:
        if str(turn_plan.get("plan_status", "") or "") == "error":
            add("PLAN", "ERROR", "Turn-plan builder returned error")
        if _has_key(turn_plan, "first_step_matches_best_action") and not bool(turn_plan.get("first_step_matches_best_action")):
            add("PLAN", "FIRST", "Plan first step differs from Best-Action")

    if isinstance(portfolio_audit, Mapping) and portfolio_audit.get("way_decision_state") == "AMBIGUOUS_WAY_TIE":
        add("SCORE", "TIE", "Ways tied; no local score tie-break")
    if isinstance(authority, Mapping) and authority.get("ambiguous_way_choice"):
        add("AUTH", "AMBIG", "Authority blocked switch because way choice is ambiguous")

    return warnings


def _best_action_matches_authority(best_action: Mapping[str, Any], authority: Mapping[str, Any]) -> bool:
    if not isinstance(best_action, Mapping) or not isinstance(authority, Mapping):
        return False
    pid = str(authority.get("active_project_id") or "")
    target = str(authority.get("active_target_id") or "")
    if not pid and not target:
        return False

    candidates: List[Mapping[str, Any]] = [best_action]
    for key in ("phase4g_project_priority_override", "phase4g_board_project_activation", "followup_action", "then_plan_item"):
        value = best_action.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
            nested = value.get("project")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    for item in candidates:
        item_pid = str(item.get("project_id", item.get("active_project_id", item.get("followup_project_id", ""))) or "")
        if pid and item_pid == pid:
            return True
        for key in ("target_id", "active_target_id", "route_target_id", "project_target_id"):
            item_target = str(item.get(key, "") or "")
            if target and item_target == target:
                return True
    first = _mapping(authority.get("first_action"))
    if first:
        first_action = str(first.get("action", first.get("action_type", "")) or "")
        best_action = str(best_action.get("action", "") or "")
        if best_action == first_action:
            return True
        then_item = best_action.get("then_plan_item")
        if isinstance(then_item, Mapping) and str(then_item.get("action", "") or "") == first_action:
            return True
    return False


def _debug_tab_statuses(
    warnings: Sequence[Mapping[str, Any]],
    direction: Mapping[str, Any],
    authority: Mapping[str, Any],
    best_action: Mapping[str, Any],
    turn_plan: Mapping[str, Any],
    active_project: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
) -> Dict[str, str]:
    statuses: Dict[str, str] = {key: "✓" for key, _label in DEBUG_TABS}
    if not isinstance(direction, Mapping) or not direction:
        statuses["STR"] = "–"
    if (not isinstance(active_project, Mapping) or not active_project) and not _selected_way_audit(portfolio_audit, direction):
        statuses["PROJ"] = "–"
    if not isinstance(authority, Mapping) or not authority:
        # n/a until hard authority is wired — not an error badge
        statuses["AUTH"] = "–"
    if not isinstance(best_action, Mapping) or not best_action:
        statuses["PLAN"] = "–" if not turn_plan else statuses.get("PLAN", "✓")
    if not isinstance(turn_plan, Mapping) or not turn_plan:
        statuses["PLAN"] = "–"

    by_tab: Dict[str, int] = {}
    for warning in warnings:
        tab = str(warning.get("tab", "")).upper()
        if not tab:
            continue
        by_tab[tab] = by_tab.get(tab, 0) + 1
    for tab, count in by_tab.items():
        statuses[tab] = "!" if count == 1 else str(min(count, 9))
    return statuses


def _warning_strip_text(warnings: Sequence[Mapping[str, Any]]) -> str:
    if not warnings:
        return "WARN: none"
    codes = []
    for warning in warnings[:3]:
        tab = str(warning.get("tab", "") or "").upper()
        code = str(warning.get("code", "!") or "!")
        codes.append(f"{tab}.{code}" if tab else code)
    text = "WARN: " + " ".join(codes)
    if len(warnings) > 3:
        text += f" +{len(warnings) - 3}"
    return text


def _badge(ok: bool) -> str:
    return "✓" if bool(ok) else "!"


def _has_key(mapping: Mapping[str, Any], key: str) -> bool:
    return isinstance(mapping, Mapping) and key in mapping


def _plan_matches_best_action(report: Mapping[str, Any], turn_plan: Mapping[str, Any]) -> bool:
    if isinstance(report, Mapping) and "execution_preview_matches_best_action" in report:
        return bool(report.get("execution_preview_matches_best_action"))
    if isinstance(turn_plan, Mapping) and "first_step_matches_best_action" in turn_plan:
        return bool(turn_plan.get("first_step_matches_best_action"))
    return False


def _scan_parts(scan: Any) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    if isinstance(scan, Mapping):
        return (
            dict(scan.get("action_flags", {}) or {}),
            dict(scan.get("candidates", {}) or {}),
            dict(scan.get("blockers", {}) or {}),
        )
    return (
        dict(getattr(scan, "action_flags", {}) or {}),
        dict(getattr(scan, "candidates", {}) or {}),
        dict(getattr(scan, "blockers", {}) or {}),
    )


def _scan_candidate_total(scan: Any) -> int:
    _flags, candidates_by_action, _blockers = _scan_parts(scan)
    total = 0
    for values in candidates_by_action.values():
        try:
            total += len(list(values or []))
        except Exception:
            pass
    return total


def _scan_stale_label(game: Any, report: Mapping[str, Any]) -> str:
    if not isinstance(report, Mapping):
        return ""
    try:
        if report.get("round") not in (None, getattr(game, "round", None)) or report.get("turn") not in (None, getattr(game, "turn", None)):
            return "STALE"
    except Exception:
        return ""
    return ""


def _action_candidates(choice: Any, candidates_by_action: Mapping[str, Any], action: str) -> List[Any]:
    if isinstance(choice, Mapping):
        values = choice.get("candidates", []) or []
        if values:
            return list(values)
    return list(candidates_by_action.get(action, []) or [])


def _action_blockers(choice: Any, blockers_by_action: Mapping[str, Any], action: str) -> List[Any]:
    if isinstance(choice, Mapping):
        values = choice.get("blockers", []) or []
        if values:
            return list(values)
    return list(blockers_by_action.get(action, []) or [])


def _action_candidate_count(choice: Any, candidates: Sequence[Any]) -> int:
    if isinstance(choice, Mapping) and choice.get("candidate_count") not in (None, ""):
        return _safe_int(choice.get("candidate_count"), len(candidates))
    return len(list(candidates or []))


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_nonempty(mapping: Mapping[str, Any], keys: Sequence[str], default: Any = "") -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}, ()):  # keep zero as a valid value
            return value
    return default


def _join_values(values: Any, default: str = "-") -> str:
    if values in (None, "", [], {}, ()):  # type: ignore[comparison-overlap]
        return default
    if isinstance(values, Mapping):
        values = [f"{k}:{v}" for k, v in values.items() if v not in (None, "", 0)]
    elif isinstance(values, (list, tuple, set)):
        values = list(values)
    else:
        return str(values)
    out = [str(v) for v in values if str(v)]
    return "/".join(out[:4]) if out else default


def _strategy_resource_profile_text(direction: Mapping[str, Any]) -> str:
    for key in ("strategy_policy_primary_engine", "resource_engines_needed", "primary_engine", "required_resource_engine"):
        value = direction.get(key) if isinstance(direction, Mapping) else None
        text = _join_values(value, "")
        if text:
            return text
    # Fall back to resource-card requirement style fields when available.
    parts: List[str] = []
    for label, keys in (
        ("Wh", ("Wheat", "wheat", "required_wheat")),
        ("O", ("Ore", "ore", "required_ore")),
        ("Wd", ("Wood", "wood", "required_wood")),
        ("B", ("Brick", "brick", "required_brick")),
        ("Sh", ("Sheep", "sheep", "required_sheep")),
    ):
        for key in keys:
            if key in direction:
                value = _safe_int(direction.get(key), 0)
                if value:
                    parts.append(f"{label}{value}")
                break
    return " ".join(parts[:5])


def _strategy_turns_text(direction: Mapping[str, Any]) -> str:
    values = []
    for label, key in (("abstract", "abstract_expected_own_turns"), ("board", "portfolio_expected_own_turns"), ("final", "final_strategy_expected_own_turns")):
        value = direction.get(key) if isinstance(direction, Mapping) else None
        text = _format_short_turns(value)
        if text:
            values.append(f"{label} {text}")
    return " | ".join(values[:3])


def _strategy_switch_text(direction: Mapping[str, Any]) -> str:
    if not isinstance(direction, Mapping):
        return ""
    best = _first_nonempty(direction, ("phase4g_best_board_realistic_way_id", "best_board_realistic_way_id"), "")
    rank = _first_nonempty(direction, ("phase4g_selected_way_board_rank", "selected_way_board_rank"), "")
    would = any(bool(direction.get(key, False)) for key in ("phase4g_would_switch_way", "would_switch_way", "strategy_would_switch"))
    bits = []
    if best not in (None, ""):
        bits.append(f"best way {best}")
    if rank not in (None, ""):
        bits.append(f"rank {rank}")
    bits.append("yes" if would else "no")
    return " | ".join(bits)


def _project_id(project: Mapping[str, Any], authority: Mapping[str, Any]) -> str:
    if isinstance(authority, Mapping) and authority.get("active_project_id") not in (None, ""):
        return str(authority.get("active_project_id"))
    if isinstance(project, Mapping):
        value = project.get("project_id")
        if value not in (None, ""):
            return str(value)
        target = _first_nonempty(project, ("target_id", "active_target_id"), "")
        ptype = _first_nonempty(project, ("project_type",), "project")
        if target not in (None, ""):
            return f"{ptype}_{target}"
    return ""


def _target_label(value: Any, *, kind: Any = None, direction: Any = None, player: Any = None, target_row: Any = None) -> str:
    """S12: prefer S@id / C@id tokens for PROJ/WAYS."""
    if value in (None, ""):
        return "-"
    text = str(value)
    if text.startswith("S@") or text.startswith("C@") or text.startswith("["):
        return text
    if text.startswith("@") and kind is None:
        # Upgrade bare @N when kind known
        try:
            from core.strategy_target_format import format_proj_target_label

            bare = text[1:]
            return format_proj_target_label(
                bare, direction=direction if isinstance(direction, Mapping) else None,
                player=player, target_row=target_row,
            )
        except Exception:
            return text
    try:
        from core.strategy_target_format import format_proj_target_label

        return format_proj_target_label(
            value,
            direction=direction if isinstance(direction, Mapping) else None,
            player=player,
            target_row=target_row,
        )
    except Exception:
        pass
    return f"@{text}"


def _project_sequence_text(project: Mapping[str, Any], first: Mapping[str, Any]) -> str:
    seq = [s for s in list(project.get("sequence", []) or []) if isinstance(s, Mapping)] if isinstance(project, Mapping) else []
    if seq:
        parts = [_action_item_text(s) for s in seq[:3]]
        return " → ".join([p for p in parts if p])
    text = _action_item_text(first)
    return text


def _project_race_text(project: Mapping[str, Any]) -> str:
    if not isinstance(project, Mapping):
        return ""
    race = _first_nonempty(project, ("race_status", "urgency", "risk_level"), "")
    opp = _first_nonempty(project, ("opponent_id", "race_opponent_id", "threat_player_id"), "")
    margin = _first_nonempty(project, ("race_margin", "own_turn_margin", "turn_margin"), "")
    bits = []
    if race:
        bits.append(str(race))
    if opp not in (None, ""):
        bits.append(f"P{opp}")
    if margin not in (None, ""):
        bits.append(f"margin {margin}")
    return " | ".join(bits)


def _project_route_text(project: Mapping[str, Any], first: Mapping[str, Any]) -> str:
    if not isinstance(project, Mapping):
        return ""
    roads = []
    for key in ("route_roads_to_build", "roads_to_build", "supporting_action_frontier_route_roads_to_build"):
        values = project.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) and values:
            roads = list(values)
            break
    if not roads and isinstance(first, Mapping):
        road = first.get("road_id") or first.get("target_road_id")
        if road:
            roads = [road]
    if not roads:
        return ""
    road_text = ",".join(_format_road_id(r) for r in roads[:3] if _format_road_id(r))
    if len(roads) > 3:
        road_text += ",…"
    remaining = _first_nonempty(project, ("remaining_roads", "frontier_remaining_roads_after_action", "supporting_action_frontier_remaining_roads_after_action"), "")
    suffix = f" | remaining {remaining}r" if remaining not in (None, "") else ""
    return f"Route: {road_text}{suffix}" if road_text else ""


def _project_gain_text(project: Mapping[str, Any]) -> str:
    if not isinstance(project, Mapping):
        return ""
    for key in ("resource_gain_named", "future_settlement_resource_gain_named", "supporting_action_resource_gain_named"):
        value = project.get(key)
        if isinstance(value, Mapping):
            text = _compact_named_gain(value)
            if text:
                return "+" + text
    port = _first_nonempty(project, ("port_label", "port_type"), "")
    return f"port {port}" if port else ""


def _action_item_text(item: Mapping[str, Any]) -> str:
    if not isinstance(item, Mapping) or not item:
        return ""
    text = str(item.get("best_action_text", "") or item.get("label", "") or "").strip()
    if text:
        return text.replace("Build settlement", "Build Settle").replace("Build city", "Build City")
    action = str(item.get("action", item.get("action_type", "")) or "")
    if action == BUILD_ROAD:
        road = item.get("road_id") or item.get("target_id")
        return f"Build Road {_format_road_id(road)}".strip()
    if action in {BUILD_CITY, BUILD_SETTLEMENT}:
        target = item.get("target_id") or item.get("intersection_id")
        verb = "Build City" if action == BUILD_CITY else "Build Settle"
        return f"{verb} {target}".strip()
    if action == BUY_DCARD:
        return "Buy DCard"
    if action == TWB:
        give = str(item.get("give_resource", "") or "")
        get = str(item.get("get_resource", "") or "")
        return f"TwB {give}->{get}" if give and get else "TwB"
    return _short_action(action) if action else ""


def _score_top_candidate_rows(game: Any, player: Any, choices: Sequence[Mapping[str, Any]]) -> List[str]:
    scored: List[Tuple[float, str]] = []
    for row in choices:
        if not isinstance(row, Mapping):
            continue
        action = str(row.get("action", "") or "")
        for candidate in list(row.get("candidates", []) or []):
            if not isinstance(candidate, Mapping):
                continue
            score = candidate.get("target_score", candidate.get("score", None))
            try:
                fscore = float(score)
            except Exception:
                continue
            label = _best_label_for_action(game, player, action, [candidate]) or str(_candidate_target_id(candidate) or "")
            scored.append((fscore, f"{_short_action(action)} {label} { _format_signed_number(fscore) }"))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [text for _score, text in scored[:3]]


def _draw_rows(rows: Sequence[str], x: int, y: int, line_h: int, font: Any, panel: pygame.Rect) -> int:
    max_width = max(20, int(panel.right) - int(x) - 6)
    for row in rows:
        if y > panel.bottom - line_h:
            return y
        color = COLORS["DGRAY"] if str(row).endswith("-") else COLORS["BLACK"]
        _blit(font, _fit_text_pixels(font, str(row), max_width), x, y, color)
        y += line_h
    return y

# ──────────────────────────────────────────────────────────────────────────────
# Text/render helpers
# ──────────────────────────────────────────────────────────────────────────────


def _section_title(font: Any, text: str, x: int, y: int) -> None:
    _blit(font, text, x, y, COLORS["BLACK"])


def _blit(font: Any, text: str, x: int, y: int, color: Optional[Tuple[int, int, int]] = None) -> None:
    surface = font.render(str(text), True, color or COLORS["BLACK"])
    WIN.blit(surface, (int(x), int(y)))


def _blit_right(font: Any, text: str, right: int, y: int, color: Optional[Tuple[int, int, int]] = None) -> None:
    surface = font.render(str(text), True, color or COLORS["BLACK"])
    WIN.blit(surface, (int(right) - surface.get_width(), int(y)))


def _blit_center(font: Any, text: str, rect: pygame.Rect, color: Optional[Tuple[int, int, int]] = None) -> None:
    surface = font.render(str(text), True, color or COLORS["BLACK"])
    x = rect.x + max(0, (rect.width - surface.get_width()) // 2)
    y = rect.y + max(0, (rect.height - surface.get_height()) // 2)
    WIN.blit(surface, (int(x), int(y)))


def _update(panel: pygame.Rect) -> None:
    try:
        pygame.display.update(panel)
    except Exception:
        pygame.display.update()


def _short_action(action: str) -> str:
    return {
        BUILD_CITY: "City",
        BUILD_SETTLEMENT: "Settle",
        BUILD_ROAD: "Road",
        BUY_DCARD: "DCard",
        TWB: "TwB",
    }.get(str(action), str(action))


def _short_blocker(blockers: Sequence[Any]) -> str:
    if not blockers:
        return ""
    text = str(blockers[0])
    replacements = {
        "Missing resources:": "Missing",
        "No legal settlement target currently reachable": "no legal target",
        "No legal road target currently connected to player network": "no legal road",
        "Strategic lock: preferred support is Build city": "skip: preferred City",
        "Strategic lock: preferred support is Build settlement": "skip: preferred Settle",
        "Strategic lock: preferred support is Build road": "skip: preferred Road",
        "Strategic lock: preferred support is Buy development_card": "skip: preferred DCard",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return _fit_text(text, 38)


def _dice_text(game: Any, report: Mapping[str, Any]) -> str:
    value = getattr(game, "dice_roll", None)
    if value in (None, "", [], 0):
        value = report.get("dice_value", "-")
    if isinstance(value, (list, tuple)):
        try:
            return str(sum(int(v) for v in value))
        except Exception:
            return str(value)
    return str(value if value not in (None, "") else "-")


def _same_player(value: Any, player: Any) -> bool:
    return _safe_int(value) == _safe_int(getattr(player, "id", 0))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def _first_int_in_text(text: str) -> Optional[int]:
    digits = ""
    for ch in str(text):
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def _positive_from(mapping: Mapping[str, Any], keys: Iterable[str]) -> int:
    if not isinstance(mapping, Mapping):
        return 0
    for key in keys:
        value = _safe_int(mapping.get(key, 0))
        if value > 0:
            return value
    return 0


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _unique_keep_order(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out



def _format_signed_number(value: Any) -> str:
    try:
        f = float(value or 0.0)
    except Exception:
        f = 0.0
    sign = "+" if f >= 0 else "-"
    return f"{sign}{_format_number(abs(f))}"


def _format_number(value: float) -> str:
    if abs(value - int(value)) < 0.0001:
        return str(int(value))
    return f"{value:.1f}"


def _road_key(road_id: Any) -> Tuple[int, int]:
    try:
        a, b = list(road_id)[:2]
        return tuple(sorted((int(a), int(b))))  # type: ignore[return-value]
    except Exception:
        return ()


def _format_road_id(road_id: Any) -> str:
    key = _road_key(road_id)
    if not key:
        return ""
    return f"[{key[0]},{key[1]}]"


def _fit_text(text: str, max_chars: int = 58) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def _text_width(font: Any, text: str) -> int:
    try:
        return int(font.size(str(text))[0])
    except Exception:
        try:
            return int(font.render(str(text), True, COLORS["BLACK"]).get_width())
        except Exception:
            return len(str(text)) * 7


def _fit_text_pixels(font: Any, text: str, max_width: int) -> str:
    """Fit text to a pixel width so rows never draw outside the panel border."""
    text = str(text or "")
    if max_width <= 0 or _text_width(font, text) <= max_width:
        return text
    ellipsis = "…"
    if _text_width(font, ellipsis) > max_width:
        return ""
    lo, hi = 0, len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if _text_width(font, candidate) <= max_width:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ellipsis


__all__ = ["draw_execution_debug_panel", "handle_execution_debug_panel_click"]
