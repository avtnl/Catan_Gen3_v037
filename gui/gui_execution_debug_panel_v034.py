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
SCORE_SECTION_TITLE = "WAYS"
DEBUG_PANEL_BUILD = "PF12"  # visible fingerprint for required-target order: probability first, ETA tie-break

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
    - BEST NOW and cross-layer consistency are always visible at the top.
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
    line_h = 12
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

    report = _current_player_report(game, player)
    choices = _current_player_choices(game, player)
    needs = _current_player_needs(game, player)
    direction = _strategy_direction(player)
    bridge = _current_execution_bridge(game, report)
    authority = _project_authority(game, report)
    best_now = _canonical_best_now_action(game)
    turn_plan = _current_ai_turn_plan(game, report)
    portfolio_audit = _current_way_portfolio_audit(game, report, direction, player)
    active_project = _active_project_from_context(game, report, authority, best_now, direction)
    warnings = _collect_execution_debug_warnings(game, player, report, choices, direction, authority, best_now, turn_plan, active_project, portfolio_audit)
    tab_status = _debug_tab_statuses(warnings, direction, authority, best_now, turn_plan, active_project, portfolio_audit)

    warning_count = len(warnings)
    _blit_right(
        bold if warning_count else font,
        f"!{warning_count}" if warning_count else "OK",
        panel.right - 8,
        y + 3,
        COLORS["RED"] if warning_count else COLORS["GREEN"],
    )
    y += 20

    # Sticky BEST NOW contract area.  Keep this at three rows; details go in tabs.
    best_text = _best_now_display_text(game, player, direction, choices, report)
    _blit(bold if best_text and best_text != "—" else font, _fit_text(f"BN: {best_text or '—'}", 56), x, y,
          COLORS["DGRAY"] if not best_text or best_text == "—" else COLORS["BLACK"])
    y += line_h

    project_id = _project_id(active_project, authority)
    project_label = project_id or "—"
    auth_badge = _badge(bool(authority.get("active")))
    lock_badge = _badge(bool(authority.get("exact_action_lock"))) if authority else "–"
    plan_ok = _plan_matches_best_now(report, turn_plan)
    plan_badge = _badge(plan_ok) if turn_plan or _has_key(report, "execution_preview_matches_best_now") else "–"
    sticky = f"PRJ: {project_label} | AUTH {auth_badge} | LOCK {lock_badge} | PLAN {plan_badge}"
    _blit(font, _fit_text(sticky, 60), x, y, COLORS["BLACK"] if project_id else COLORS["DGRAY"])
    y += line_h

    warning_strip = _warning_strip_text(warnings)
    _blit(bold if warnings else font, _fit_text(warning_strip, 60), x, y,
          COLORS["RED"] if warnings else COLORS["DGRAY"])
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
            _draw_tab_plan(report, best_now, turn_plan, direction, portfolio_audit, warnings, x, y, line_h, font, bold, clip_panel)
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
DEFAULT_DEBUG_TAB = "AUTH"


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
    y = _draw_tab_header_warnings("SCAN", warnings, x, y, line_h, font, bold, panel)
    scan = getattr(game, "current_viable_action_scan", None)
    total_candidates = _scan_candidate_total(scan)
    stale = _scan_stale_label(game, report)
    header = f"Scan: choices {len(choices)}/{total_candidates}" if total_candidates else f"Scan: choices {len(choices)}"
    if stale:
        header += f" | {stale}"
    _blit(font, _fit_text(header, 60), x, y, COLORS["DGRAY"])
    y += line_h

    choices_by_action = {str(row.get("action", "")): row for row in choices if isinstance(row, Mapping)}
    actionable_by_action = {
        str(row.get("action", "")): row
        for row in list(getattr(game, "current_actionable_choices", []) or [])
        if isinstance(row, Mapping) and bool(row.get("actionable", False))
    }
    flags, candidates_by_action, blockers_by_action = _scan_parts(scan)
    canonical = _canonical_best_now_action(game)

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
        display_viable = bool(raw_viable or (isinstance(choice, Mapping) and choice.get("viable", False)) or canonical_marks_actionable)
        is_actionable = bool(actionable_by_action.get(action)) or canonical_marks_actionable
        if isinstance(choice, Mapping):
            is_actionable = is_actionable or bool(choice.get("actionable", False))

        marker = "A" if is_actionable else ("L" if strategy_locked and display_viable else ("Y" if display_viable else "N"))
        row_color = COLORS["RED"] if is_actionable else (COLORS["ORANGE"] if marker == "L" else (COLORS["GREEN"] if display_viable else COLORS["DGRAY"]))
        left = f"{marker} {label:<6} {candidate_count:>2}"
        _blit(bold, left, x, y, row_color)

        if display_viable and strategy_locked:
            detail = "locked by AUTH/strategy"
        elif display_viable and str(canonical.get("action", "") or "") == action and str(canonical.get("best_now_label", "") or ""):
            detail = f"best {canonical.get('best_now_label')}"
        elif display_viable:
            detail = f"best {_best_label_for_action(game, player, action, candidates)}".strip()
        else:
            detail = _short_blocker(blockers) or (f"best {_best_label_for_action(game, player, action, candidates)}".strip())
        if detail:
            _blit(bold if is_actionable else font, _fit_text(detail, 38), x + 78, y, row_color if is_actionable else COLORS["BLACK"] if display_viable else COLORS["DGRAY"])
        y += line_h

    if y <= panel.bottom - line_h:
        _blit(font, "A actionable | Y legal | L locked | N blocked", x, y, COLORS["DGRAY"])
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
    y = _draw_tab_header_warnings("STR", warnings, x, y, line_h, font, bold, panel)
    if not isinstance(direction, Mapping) or not direction:
        _blit(font, "Strategy: no current strategic_direction", x, y, COLORS["DGRAY"])
        return y + line_h

    way = _way_id(direction)
    tags = _strategy_tags(direction)
    rows = [
        f"Way: {way if way not in (None, '') else '-'} | {' | '.join(tags) if tags else '-'}",
        f"Family: {_first_nonempty(direction, ('strategy_policy_family', 'strategy_family', 'family'), '-')}",
        f"Weak: {_join_values(direction.get('strategy_policy_weak_engines'), '-')}",
        f"Pref: {_join_values(direction.get('strategy_policy_preferred_action_families'), '-')}",
        f"Need: {_strategy_needs_text(direction, needs)}",
    ]
    resource_profile = _strategy_resource_profile_text(direction)
    if resource_profile:
        rows.append(f"Resources: {resource_profile}")
    turns = _strategy_turns_text(direction)
    if turns:
        rows.append(f"Turns: {turns}")
    switch = _strategy_switch_text(direction)
    if switch:
        rows.append(f"Switch: {switch}")
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
    y = _draw_tab_header_warnings("PROJ", warnings, x, y, line_h, font, bold, panel)

    rows: List[str] = []
    selected_audit = _selected_way_audit(portfolio_audit, direction)
    if not selected_audit:
        selected_audit = _synthetic_selected_way_audit_from_runtime(game, player, direction, project, authority)
        if selected_audit:
            portfolio_audit = dict(portfolio_audit or {})
            portfolio_audit.setdefault("candidate_way_count", 1)
            portfolio_audit.setdefault("selected_way_board_rank", "?")
            portfolio_audit.setdefault("__debug_source", selected_audit.get("debug_selected_fallback", "runtime_synthetic"))
    if selected_audit:
        rows.extend(_portfolio_summary_rows(portfolio_audit, selected_audit, direction))
        source = str(portfolio_audit.get("__debug_source", "") or selected_audit.get("debug_selected_fallback", "") or "")
        if source:
            rows.append(f"Src: {_fit_text(source, 50)}")
        new_rows = _portfolio_new_target_rows(selected_audit, max_rows=3)
        rows.append("New targets:" if new_rows else "New targets: none visible")
        rows.extend(new_rows)
        city_row = _portfolio_city_targets_row(selected_audit, max_targets=3)
        if city_row:
            rows.append(city_row)
        elif _safe_int(_portfolio_required_city_count(selected_audit, direction), 0) > 0:
            rows.append("Cities: none visible")
    else:
        rows.append("Portfolio: MISSING - no audit/runtime targets")
        rows.append("Check: running PF4? audit not attached")

    if isinstance(project, Mapping) and project:
        first = _mapping(project.get("first_action")) or _mapping(authority.get("first_action"))
        active = _project_id(project, authority) or "-"
        sequence = _project_sequence_text(project, first)
        rows.append(f"Active: {active}" + (f" | {sequence}" if sequence else ""))
        if not sequence:
            target = _target_label(_first_nonempty(project, ("target_id", "active_target_id"), authority.get("active_target_id")))
            rows.append(f"Type: {_first_nonempty(project, ('project_type', 'type'), '-')} | target {target}")
        tier = _first_nonempty(project, ("project_priority_tier", "urgency"), "")
        score = _first_nonempty(project, ("project_score", "priority_score"), authority.get("project_score", ""))
        if tier or score not in (None, ""):
            rows.append(f"Tier: {tier or '-'} | score {score if score not in (None, '') else '-'}")
        race = _project_race_text(project)
        if race:
            rows.append(f"Race: {race}")
        route = _project_route_text(project, first)
        if route and route not in rows:
            rows.append(route)
    else:
        rows.append("Active: no active project visible")

    if authority.get("forbidden_fallback_families") and _rows_remaining(y, line_h, panel, len(rows)) > 0:
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
    y = _draw_tab_header_warnings("AUTH", warnings, x, y, line_h, font, bold, panel)
    if not isinstance(authority, Mapping) or not authority:
        _blit(font, "Authority: no object visible", x, y, COLORS["DGRAY"])
        return y + line_h

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
    # Tab key stays SCORE for compatibility with saved clicks, but the visible
    # label is WAYS.  Phase PF10 hides local score-breakdowns as authority and
    # surfaces explicit way/target ambiguity instead.
    y = _draw_tab_header_warnings("SCORE", warnings, x, y, line_h, font, bold, panel)

    rows: List[str] = []
    rows.extend(_way_decision_rows(portfolio_audit, direction, authority, max_rows=4))

    comparison_rows = _score_target_comparison_rows(game, player, direction, portfolio_audit, project, authority)
    if comparison_rows and _rows_remaining(y, line_h, panel, len(rows)) > 1:
        rows.extend(comparison_rows[:max(1, _rows_remaining(y, line_h, panel, len(rows)))])

    if isinstance(direction, Mapping) and direction.get("supporting_action_target_score_breakdown") and _rows_remaining(y, line_h, panel, len(rows)) > 0:
        rows.append("Legacy score hidden: no authority")

    if not rows:
        rows.append("WAYS: no 142-way audit visible")
    return _draw_rows(rows, x, y, line_h, font, panel)


def _way_decision_rows(
    portfolio_audit: Mapping[str, Any],
    direction: Mapping[str, Any],
    authority: Mapping[str, Any],
    *,
    max_rows: int = 4,
) -> List[str]:
    rows: List[str] = []
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
        turns = _format_short_turns(selected.get("realistic_expected_own_turns")) or "?t"
        rank = portfolio_audit.get("selected_way_board_rank", "-")
        rows.append(f"Ways: selected {wid} | {feas} | rank {rank}")
        rows.append(f"Turns: board {turns} | no score tie-break")
    if isinstance(authority, Mapping) and authority.get("ambiguous_way_choice"):
        rows.append("AUTH: switch blocked by ambiguity")
    return rows[:max_rows]

def _score_target_comparison_rows(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    portfolio_audit: Mapping[str, Any],
    project: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> List[str]:
    """Return compact selected-vs-rival rows for SCORE.

    WAYS compares the active settlement target with the next visible
    rival in the realistic portfolio.  PROJ shows the portfolio itself; this
    helper compares the active target against the best other new/next-settle
    target using the evidence already present in the Phase-4G audit.
    """
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
    if not rival:
        return []

    sel_label = _target_label(_target_id_from_mapping(selected))
    riv_label = _target_label(_target_id_from_mapping(rival))
    rows: List[str] = [f"Compare: {sel_label} vs {riv_label}"]
    rows.append("Decision: no local score tie-break")

    need_line = _score_need_compare_line(sel_label, selected, riv_label, rival)
    if need_line:
        rows.append(need_line)

    # Race detail is intentionally omitted here; PROJ owns racer visibility.
    timing_line = _score_timing_compare_line(sel_label, selected, riv_label, rival)
    if timing_line:
        rows.append(timing_line)

    cost_line = _score_cost_compare_line(sel_label, selected, riv_label, rival)
    if cost_line:
        rows.append(cost_line)

    role_lines = _score_role_compare_lines(sel_label, selected, riv_label, rival, project, authority)
    if role_lines:
        rows.extend(role_lines[:2])

    hb_line = _score_hard_bottleneck_compare_line(sel_label, selected, riv_label, rival)
    if hb_line:
        rows.append(hb_line)
    else:
        reason_line = _score_reason_compare_line(sel_label, selected, riv_label, rival)
        if reason_line:
            rows.append(reason_line)

    return [_fit_text(row, 62) for row in rows[:8]]


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
    """Return role comparison as one row per intersection.

    The earlier combined row could exceed the narrow panel width, especially
    when the selected role was must_race_critical and an authority reason was
    appended.  Keep SCORE readable: one compact row for the selected target,
    one compact row for the rival target.  AUTH/PROJ own the verbose authority
    reason.
    """
    sel_role = _first_nonempty(project, ("project_priority_tier", "urgency"), _first_nonempty(selected, ("project_priority_tier", "urgency", "portfolio_role"), "-"))
    riv_role = _first_nonempty(rival, ("project_priority_tier", "urgency", "portfolio_role"), "-")
    rows = [
        f"Role {sel_label}: {sel_role}",
        f"Role {riv_label}: {riv_role}",
    ]
    return rows


def _score_reason_compare_line(sel_label: str, selected: Mapping[str, Any], riv_label: str, rival: Mapping[str, Any]) -> str:
    sel_reasons = list(selected.get("resource_role_reasons", []) or []) if isinstance(selected.get("resource_role_reasons", []), Sequence) and not isinstance(selected.get("resource_role_reasons", []), (str, bytes)) else []
    riv_reasons = list(rival.get("resource_role_reasons", []) or []) if isinstance(rival.get("resource_role_reasons", []), Sequence) and not isinstance(rival.get("resource_role_reasons", []), (str, bytes)) else []
    if sel_reasons:
        return f"Why {sel_label}: {_fit_text(str(sel_reasons[0]), 48)}"
    if riv_reasons:
        return f"Why {riv_label}: {_fit_text(str(riv_reasons[0]), 48)}"
    return ""

def _draw_tab_plan(
    report: Mapping[str, Any],
    best_now: Mapping[str, Any],
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
    y = _draw_tab_header_warnings("PLAN", warnings, x, y, line_h, font, bold, panel)
    if not isinstance(turn_plan, Mapping) or not turn_plan:
        _blit(font, "Plan: no execution preview", x, y, COLORS["DGRAY"])
        return y + line_h

    rows = [
        f"Plan: {turn_plan.get('plan_summary') or turn_plan.get('plan_type') or turn_plan.get('plan_status') or '-'}",
    ]
    steps = [s for s in list(turn_plan.get("steps", []) or []) if isinstance(s, Mapping)]
    for idx, step in enumerate(steps[:4], start=1):
        rows.append(f"{idx} {_action_item_text(step) or str(step.get('action') or '-')}")
    rows.append(
        f"BN/Preview/Lock: "
        f"{_badge(bool(turn_plan.get('first_step_matches_best_now')))}"
        f"/{_badge(_plan_matches_best_now(report, turn_plan))}"
        f"/{_badge(bool(best_now.get('exact_followup_lock') or best_now.get('then_plan_item')))}"
    )

    order_rows = _required_target_order_rows(portfolio_audit, direction, max_rows=4)
    if order_rows:
        rows.extend(order_rows)

    claim_rows = _post_claim_projection_rows(portfolio_audit, direction, max_rows=4)
    if claim_rows:
        rows.extend(claim_rows)

    after = turn_plan.get("expected_resources_after_visible_sequence_named")
    if isinstance(after, Mapping):
        rows.append(f"After: {_compact_named_gain(after) or '-'}")
    stop = str(turn_plan.get("stop_reason", "") or "")
    if stop:
        rows.append(f"Stop: {_fit_text(stop, 52)}")
    return _draw_rows(rows, x, y, line_h, font, panel)




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

        canonical = _canonical_best_now_action(game)
        canonical_action = str(canonical.get("action", "") or "") if canonical else ""
        canonical_label = str(canonical.get("best_now_label", "") or "") if canonical else ""
        blocked_action = str(canonical.get("blocked_action", "") or "") if canonical else ""
        canonical_marks_actionable = _canonical_scan_row_is_best_action(canonical, action)

        strategy_locked = _is_strategy_locked_choice(choice, blockers)
        raw_viable = bool(
            (isinstance(choice, Mapping) and choice.get("scan_viable", False))
            or flags.get(action, False)
            or (strategy_locked and candidate_count > 0)
        )
        display_viable = raw_viable or bool(choice.get("viable", False)) if isinstance(choice, Mapping) else raw_viable
        # Phase 3.2: synthetic BEST NOW bridge actions, especially TwB rescue
        # actions, may not be present in current_actionable_choices.  Still
        # mark the matching SCAN row as actionable so the panel clearly shows
        # which available action BEST NOW will execute.
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
    """Return True when a SCAN row is the frozen BEST NOW action.

    Phase 3.2 uses this for synthetic bridge actions.  Some BEST NOW items are
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
    text = str(canonical.get("best_now_text", "") or canonical.get("label", "") or "").strip()
    if text.startswith(("Wait", "No ", "Roll", "Resolve")):
        return False
    return True


def _canonical_best_now_action(game: Any) -> Mapping[str, Any]:
    """Return Game's frozen BEST NOW object, if available."""
    item = getattr(game, "current_best_now_action", None)
    if isinstance(item, Mapping) and item.get("action"):
        return dict(item)
    report = getattr(game, "last_execution_scan_report", None)
    if isinstance(report, Mapping):
        item = report.get("canonical_best_now_action")
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
    canonical_blocked = _canonical_best_now_action(game)
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
        canonical = _canonical_best_now_action(game) if idx == 1 else {}
        if canonical and str(canonical.get("action", "") or "") == action:
            best = str(canonical.get("best_now_label", "") or "")
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
    """Return compact Way tags only.

    Tags describe the Way itself, not the route/board mechanics.  Therefore
    Port and Road are filtered out, while LR is kept because Longest Road is a
    victory objective.  LA/VP do not show the development-card count in
    brackets; those counts are confusing once the player is part-way there.
    """
    if not isinstance(direction, Mapping):
        return []

    raw_tags = list(direction.get("tags", []) or [])
    summary = direction.get("strategy_summary", {}) if isinstance(direction.get("strategy_summary", {}), Mapping) else {}
    remaining = direction.get("remaining", {}) if isinstance(direction.get("remaining", {}), Mapping) else {}

    out: List[str] = []
    for raw in raw_tags:
        tag = _normalise_way_tag(raw)
        if tag:
            _add_or_replace_tag(out, tag)

    # Some planner versions may not provide clean tags. Build conservative tags
    # from strategy_summary/remaining, but do not use Road or Port as strategy tags.
    if _truthy(summary.get("largest_army")) or _positive_from(summary, ("largest_army",)):
        _add_or_replace_tag(out, "LA")
    if _truthy(summary.get("longest_road")):
        _add_or_replace_tag(out, "LR")

    for label, keys in (
        ("City", ("cities", "city_upgrades", "cities_to_build", "remaining_city_upgrades", "remaining_cities_to_upgrade")),
        ("Settle", ("settlements", "new_settlements", "settlements_to_build", "remaining_new_settlements", "remaining_settlements_to_build")),
        ("VP", ("victory_points", "vp_cards", "victory_point_cards", "remaining_vp_cards")),
        ("DC", ("development_cards_to_buy", "dev_cards_to_buy", "dcards_to_buy", "remaining_dev_cards_to_buy")),
    ):
        value = _positive_from(summary, keys)
        if value <= 0:
            value = _positive_from(remaining, keys)
        if value > 0:
            # Do not add generic DC when the Way already explains the DC purpose
            # via LA or VP.
            if label == "DC" and ("LA" in out or any(_tag_root(t) == "VP" for t in out)):
                continue
            _add_or_replace_tag(out, f"{value} {label}")

    return _sort_way_tags(out)[:5]


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

    if lower in {"la", "largest army", "largestarmy"}:
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
    parts = str(tag or "").split()
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
    priority = {"LA": 0, "LR": 1, "City": 2, "Settle": 3, "VP": 4, "DC": 5}
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
    if (any(t == "LA" for t in tags) or any(t.startswith("VP ") for t in tags)) and "DCard" not in imm:
        later.append("DC")

    for tag in tags:
        root = tag.split()[0]
        label = {
            "City": "City",
            "Settle": "Settle",
            "VP": "DC",
            "DC": "DC",
        }.get(root, "")
        if label and label not in imm and label not in later:
            later.append(label)

    return later[:2]


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
        return "buy_dcard"

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


def _best_now_or_wait(
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

    canonical = _canonical_best_now_action(game)
    if canonical:
        text = str(canonical.get("best_now_text", "") or "").strip()
        if text:
            return text
        action = str(canonical.get("action", "") or "")
        best = str(canonical.get("best_now_label", "") or "")
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

    for key in ("selected_way_audit", "selected_audit", "current_way_audit", "phase4g_selected_way_audit"):
        value = portfolio_audit.get(key)
        if isinstance(value, Mapping) and value:
            return dict(value)

    rows = [dict(row) for row in list(portfolio_audit.get("way_audits", []) or []) if isinstance(row, Mapping)]
    if not rows:
        return {}

    # First trust an explicit marker from the portfolio builder.
    for row in rows:
        if bool(row.get("is_selected_way_before_4g")):
            return dict(row)

    candidate_ids: List[Any] = []
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
    if isinstance(direction, Mapping):
        way = _way_id(direction)
        if way not in (None, "", "-"):
            candidate_ids.append(way)

    candidate_ints = {_safe_int(value, -999999) for value in candidate_ids}
    candidate_texts = {str(value) for value in candidate_ids if value not in (None, "", "-")}
    for row in rows:
        row_id = row.get("way_id", row.get("preferred_way_id", row.get("phase4g_way_id", "")))
        if str(row_id) in candidate_texts or _safe_int(row_id, -999998) in candidate_ints:
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

def _portfolio_summary_rows(portfolio_audit: Mapping[str, Any], selected_audit: Mapping[str, Any], direction: Mapping[str, Any]) -> List[str]:
    rows: List[str] = []
    way = _first_nonempty(selected_audit, ("way_id", "preferred_way_id"), _way_id(direction))
    feasibility = str(selected_audit.get("feasibility", "") or "-")
    rank = _first_nonempty(portfolio_audit, ("selected_way_board_rank", "phase4g_selected_way_board_rank"), "")
    count = _first_nonempty(portfolio_audit, ("candidate_way_count", "way_count"), "")
    rank_text = f"rank {rank}/{count}" if rank not in (None, "") and count not in (None, "") else (f"rank {rank}" if rank not in (None, "") else "rank -")
    rows.append(f"Portfolio: way {way if way not in (None, '') else '-'} | {feasibility} | {rank_text}")

    req = selected_audit.get("recalculated_requirements", {}) if isinstance(selected_audit.get("recalculated_requirements", {}), Mapping) else {}
    way_req = selected_audit.get("way_requirements", {}) if isinstance(selected_audit.get("way_requirements", {}), Mapping) else {}
    portfolio = selected_audit.get("portfolio", {}) if isinstance(selected_audit.get("portfolio", {}), Mapping) else {}
    new_bucket = portfolio.get("new_intersection_portfolio", {}) if isinstance(portfolio.get("new_intersection_portfolio", {}), Mapping) else {}
    city_bucket = portfolio.get("city_upgrade_portfolio", {}) if isinstance(portfolio.get("city_upgrade_portfolio", {}), Mapping) else {}

    new_req = _first_nonempty(req, ("new_intersection_count_required",), _first_nonempty(new_bucket, ("target_count_required",), _first_nonempty(portfolio, ("target_count_required",), way_req.get("required_new_intersections", "-"))))
    new_sel = _first_nonempty(req, ("new_intersection_count_selected",), _first_nonempty(new_bucket, ("target_count_selected",), _first_nonempty(portfolio, ("target_count_selected",), len(_portfolio_target_list(selected_audit, "new")))))
    city_req = _first_nonempty(req, ("city_upgrade_count_required",), _first_nonempty(city_bucket, ("target_count_required",), way_req.get("required_cities", "-")))
    city_sel = _first_nonempty(req, ("city_upgrade_count_selected",), _first_nonempty(city_bucket, ("target_count_selected",), len(_portfolio_target_list(selected_audit, "city"))))
    total_sel = _safe_int(new_sel, 0) + _safe_int(city_sel, 0)
    total_req = _safe_int(new_req, 0) + _safe_int(city_req, 0)
    rows.append(f"Need: New {new_sel}/{new_req} | City {city_sel}/{city_req} | total {total_sel}/{total_req}")

    turns = _format_short_turns(_first_nonempty(selected_audit, ("realistic_expected_own_turns", "portfolio_expected_own_turns"), ""))
    frag = str(selected_audit.get("fragility", "") or "-")
    if turns:
        rows.append(f"Turns: board {turns} | frag {frag}")
    else:
        rows.append(f"Frag: {frag}")
    return rows


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
            or []
        )
    if isinstance(values, Mapping):
        values = list(values.values())
    return [dict(t) for t in list(values or []) if isinstance(t, Mapping)]


def _portfolio_new_target_rows(selected_audit: Mapping[str, Any], *, max_rows: int = 3) -> List[str]:
    selected = _portfolio_target_list(selected_audit, "new")
    out: List[str] = []
    for target in selected[:max_rows]:
        out.append(_portfolio_settlement_target_row(target))
    hidden = max(0, len(selected) - max_rows)
    if hidden:
        out.append(f"+{hidden} more new targets")
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
    best_now: Mapping[str, Any],
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
    for source in (best_now, report, getattr(game, "current_way_portfolio_audit", None), direction):
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


def _best_now_display_text(
    game: Any,
    player: Any,
    direction: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> str:
    """Return BEST NOW text without dice/robber forced-flow instructions."""
    canonical = _canonical_best_now_action(game)
    if canonical:
        text = str(canonical.get("best_now_text", "") or "").strip()
        if text:
            return text
        action = str(canonical.get("action", "") or "")
        best = str(canonical.get("best_now_label", "") or "")
        verb = {
            BUILD_CITY: "Build City",
            BUILD_SETTLEMENT: "Build Settle",
            BUILD_ROAD: "Build Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        if action and action not in {"Roll dice", "Resolve robber"}:
            return f"{verb} {best}".strip()

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
            BUILD_ROAD: "Build Road",
            BUY_DCARD: "Buy DCard",
        }.get(action, _short_action(action))
        return f"{verb} {best}".strip()

    target = _strategy_target_text(game, direction)
    if target:
        return f"Wait / Prio: {target}"
    return "—"


def _collect_execution_debug_warnings(
    game: Any,
    player: Any,
    report: Mapping[str, Any],
    choices: Sequence[Mapping[str, Any]],
    direction: Mapping[str, Any],
    authority: Mapping[str, Any],
    best_now: Mapping[str, Any],
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
        if best_now and not _best_now_matches_authority(best_now, authority):
            add("AUTH", "BN", "BEST NOW not visibly tied to authority")
    elif best_now and str(best_now.get("action", "") or "") not in {"", "End turn", "Pass"}:
        # Non-project actions can be legal.  Keep this as a soft warning because
        # the panel's purpose is to reveal when local action scoring is in charge.
        add("AUTH", "NOAUTH", "BEST NOW exists but authority is inactive")

    if isinstance(active_project, Mapping) and active_project:
        first = _mapping(active_project.get("first_action"))
        if not first and not _mapping(authority.get("first_action")):
            add("PROJ", "NOFIRST", "Project has no first action visible")

    if _has_key(report, "execution_preview_matches_best_now") and not bool(report.get("execution_preview_matches_best_now")):
        add("PLAN", "PREVIEW", "Execution preview differs from BEST NOW")
    if isinstance(turn_plan, Mapping) and turn_plan:
        if str(turn_plan.get("plan_status", "") or "") == "error":
            add("PLAN", "ERROR", "Turn-plan builder returned error")
        if _has_key(turn_plan, "first_step_matches_best_now") and not bool(turn_plan.get("first_step_matches_best_now")):
            add("PLAN", "FIRST", "Plan first step differs from BEST NOW")

    if isinstance(portfolio_audit, Mapping) and portfolio_audit.get("way_decision_state") == "AMBIGUOUS_WAY_TIE":
        add("SCORE", "TIE", "Ways tied; no local score tie-break")
    if isinstance(authority, Mapping) and authority.get("ambiguous_way_choice"):
        add("AUTH", "AMBIG", "Authority blocked switch because way choice is ambiguous")

    return warnings


def _best_now_matches_authority(best_now: Mapping[str, Any], authority: Mapping[str, Any]) -> bool:
    if not isinstance(best_now, Mapping) or not isinstance(authority, Mapping):
        return False
    pid = str(authority.get("active_project_id") or "")
    target = str(authority.get("active_target_id") or "")
    if not pid and not target:
        return False

    candidates: List[Mapping[str, Any]] = [best_now]
    for key in ("phase4g_project_priority_override", "phase4g_board_project_activation", "followup_action", "then_plan_item"):
        value = best_now.get(key)
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
        best_action = str(best_now.get("action", "") or "")
        if best_action == first_action:
            return True
        then_item = best_now.get("then_plan_item")
        if isinstance(then_item, Mapping) and str(then_item.get("action", "") or "") == first_action:
            return True
    return False


def _debug_tab_statuses(
    warnings: Sequence[Mapping[str, Any]],
    direction: Mapping[str, Any],
    authority: Mapping[str, Any],
    best_now: Mapping[str, Any],
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
        statuses["AUTH"] = "–"
    if not isinstance(best_now, Mapping) or not best_now:
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


def _plan_matches_best_now(report: Mapping[str, Any], turn_plan: Mapping[str, Any]) -> bool:
    if isinstance(report, Mapping) and "execution_preview_matches_best_now" in report:
        return bool(report.get("execution_preview_matches_best_now"))
    if isinstance(turn_plan, Mapping) and "first_step_matches_best_now" in turn_plan:
        return bool(turn_plan.get("first_step_matches_best_now"))
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


def _target_label(value: Any) -> str:
    if value in (None, ""):
        return "-"
    text = str(value)
    if text.startswith("@") or text.startswith("["):
        return text
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
    text = str(item.get("best_now_text", "") or item.get("label", "") or "").strip()
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
