"""SE Dig (SE5+): probe hits, cat XOR filters, SE Dig panel (PLAN/ACT/WHY/MORE).

Loads fields from enriched dense ``mglog_cs.csv`` rows (no SE recompute).
Product: ``docs/CS_mglog_se_dig_implementation_plan.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pygame

from core.batch.cs_mglog_codes import (
    COL_CS_CAT1,
    COL_CS_CAT2,
    COL_CS_TF,
    decode_code_list,
    decode_cs_tf,
    lists_intersect,
)
from core.batch.cs_se_snapshot import (
    DEL_TOKEN,
    SE_L2_FIELDS,
    SE_REASSESS_FIELDS,
    is_del_token,
    parse_se_cell,
)

try:
    from gui.gui_constants import (
        COLORS,
        EXECUTION_DEBUG_PANEL_RECT,
        Font,
        HUMAN_BUTTON_PANEL_RECT,
        LEFT_DICE_PANEL_RECT,
    )
except Exception:  # pragma: no cover
    COLORS = {
        "LGRAY": (200, 200, 200),
        "DGRAY": (80, 80, 80),
        "GRAY": (169, 169, 169),
        "BLACK": (0, 0, 0),
        "WHITE": (255, 255, 255),
        "GREEN": (0, 255, 0),
        "RED": (220, 40, 40),
        "BLUE": (40, 80, 200),
    }
    EXECUTION_DEBUG_PANEL_RECT = pygame.Rect(675, 220, 520, 280)
    HUMAN_BUTTON_PANEL_RECT = pygame.Rect(10, 265, 330, 255)
    LEFT_DICE_PANEL_RECT = pygame.Rect(15, 370, 175, 90)
    Font = None  # type: ignore

NAV_STEP = "step"  # < or >
NAV_JUMP = "jump"  # dig next, <<G, rounds, …

TABS: Tuple[str, ...] = ("PLAN", "ACT", "WHY", "MORE")

# Fixed field slots per tab (stable layout)
PLAN_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("Way sticky", "sticky_way_id"),
    ("Way id", "way_id"),
    ("Tags", "way_tags"),
    ("LA / LR", "_la_lr"),  # synthetic
    ("Sticky tgt", "sticky_target_id"),
    ("Tgt kind", "sticky_target_kind"),
    ("Rec tgt", "rec_target_id"),
    ("ETA plan", "turns"),
    ("ETA prev", "prev_turns"),
    ("ETA Δ", "delta_turns"),
    ("ETA tgt", "self_eta"),
)

ACT_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("BA label", "ba_label"),
    ("BA action", "ba_action"),
    ("BA target", "ba_target_id"),
    ("BA source", "ba_source"),
    ("BA roads", "ba_roads_fp"),
    ("Sup type", "supporting_action_type"),
    ("Sup tgt", "supporting_target_id"),
    ("Sticky roads", "sticky_roads_fp"),
)

WHY_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("reason", "reason"),
    ("sample", "sample_kind"),
    ("way cause", "way_switch_cause"),
    ("tgt cause", "target_switch_cause"),
    ("invalidate", "sticky_invalidate_reason"),
    ("achieve", "achieve_kind"),
    ("way_ch", "way_changed"),
    ("tgt_ch", "target_changed"),
    ("roads_ch", "roads_changed"),
    ("apply", "sticky_apply_action"),
    ("apply rsn", "sticky_apply_reason"),
    ("cs_cat1", COL_CS_CAT1),
    ("cs_cat2", COL_CS_CAT2),
)

MORE_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("abstract", "abstract_turns"),
    ("win_span", "win_span"),
    ("risk", "risk_level"),
    ("prio sc", "priority_score"),
    ("prio why", "priority_reason"),
    ("threat", "threat_summary"),
    ("prev way", "prev_sticky_way_id"),
    ("prev tgt", "prev_sticky_target_id"),
    ("prev kind", "prev_sticky_target_kind"),
    ("prev_way_id", "prev_way_id"),
    ("req C/S/R/DC", "_req"),
    ("owned S/C/R", "_owned"),
    ("VP eff", "vp_effective"),
) + tuple((f"L2 {k}", k) for k in SE_L2_FIELDS) + tuple(
    (f"RA {k}", k) for k in SE_REASSESS_FIELDS
)

COLOR_RED = (220, 40, 40)
COLOR_BLUE = (40, 90, 210)
COLOR_BLACK = (0, 0, 0)


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def parse_cat_list(raw: Any) -> List[int]:
    """Parse ``3,5`` / ``3;5`` / ``[3, 5]`` → sorted unique ints."""
    return decode_code_list(raw)


def row_event_index(row: Mapping[str, Any], fallback: int) -> int:
    ei = _safe_int(row.get("event_index"), None)
    return int(ei) if ei is not None else int(fallback)


def find_row_index_by_event_index(
    rows: Sequence[Mapping[str, Any]], event_index: int
) -> int:
    """Map enriched ``event_index`` → list index (prefer column match)."""
    target = int(event_index)
    for i, row in enumerate(rows):
        if row_event_index(row, i) == target:
            return i
    if 0 <= target < len(rows):
        return target
    return -1


def row_matches_cats(
    row: Mapping[str, Any],
    cat1: Sequence[int],
    cat2: Sequence[int],
) -> bool:
    """XOR families: use cat1 if non-empty else cat2 (never both)."""
    c1 = [int(x) for x in cat1]
    c2 = [int(x) for x in cat2]
    if c1 and c2:
        # Safety: prefer cat1 if both set
        c2 = []
    if c1:
        row_c = decode_code_list(row.get(COL_CS_CAT1))
        return lists_intersect(c1, row_c)
    if c2:
        row_c = decode_code_list(row.get(COL_CS_CAT2))
        return lists_intersect(c2, row_c)
    return False


def build_hit_list(
    rows: Sequence[Mapping[str, Any]],
    cat1: Sequence[int],
    cat2: Sequence[int],
) -> List[int]:
    """List indices into ``rows`` matching the active cat filter."""
    if not cat1 and not cat2:
        return []
    hits: List[int] = []
    for i, row in enumerate(rows):
        if row_matches_cats(row, cat1, cat2):
            hits.append(i)
    return hits


def seat_turn_of_row(row: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    r = _safe_int(row.get("round"))
    t = _safe_int(row.get("turn"))
    if r is None or t is None:
        return None
    return (int(r), int(t))


def field_raw(row: Mapping[str, Any], key: str) -> str:
    if key == "_la_lr":
        la = parse_se_cell(row.get("way_la", ""))
        lr = parse_se_cell(row.get("way_lr", ""))
        parts = []
        if la != "":
            parts.append(f"LA={la}")
        if lr != "":
            parts.append(f"LR={lr}")
        return " ".join(parts)
    if key == "_req":
        parts = []
        for lab, k in (
            ("C", "req_cities"),
            ("S", "req_settles"),
            ("R", "req_roads"),
            ("DC", "req_dcards"),
        ):
            v = parse_se_cell(row.get(k, ""))
            if v != "":
                parts.append(f"{lab}={v}")
        return " ".join(parts)
    if key == "_owned":
        parts = []
        for lab, k in (
            ("S", "settlements_owned"),
            ("C", "cities_owned"),
            ("R", "roads_owned"),
        ):
            v = parse_se_cell(row.get(k, ""))
            if v != "":
                parts.append(f"{lab}={v}")
        return " ".join(parts)
    return parse_se_cell(row.get(key, ""))


def last_change_index(
    rows: Sequence[Mapping[str, Any]],
    field_key: str,
    cursor: int,
    *,
    player_id: Optional[int] = None,
) -> Optional[int]:
    """Latest index ≤ cursor where field value differs from previous (same player).

    Treats ``__DEL__`` as a change. Synthetic ``_la_lr`` uses way_la/way_lr.
    """
    if cursor < 0 or cursor >= len(rows):
        return None
    keys = ("way_la", "way_lr") if field_key == "_la_lr" else (field_key,)

    def _val(i: int) -> str:
        row = rows[i]
        if field_key == "_la_lr":
            return field_raw(row, "_la_lr")
        return parse_se_cell(row.get(field_key, ""))

    def _pid(i: int) -> Optional[int]:
        return _safe_int(rows[i].get("player_id"))

    cur_pid = player_id
    if cur_pid is None:
        cur_pid = _pid(cursor)

    last_i: Optional[int] = None
    prev_v = ""
    for i in range(0, cursor + 1):
        if cur_pid is not None and _pid(i) not in (None, cur_pid):
            continue
        v = _val(i)
        # skip pure empty until first write
        if v == "" and prev_v == "" and last_i is None:
            continue
        if v != prev_v:
            last_i = i
            prev_v = "" if is_del_token(v) else v
            if is_del_token(v):
                prev_v = ""
    return last_i


def display_field_at_cursor(
    rows: Sequence[Mapping[str, Any]],
    cursor: int,
    field_key: str,
    *,
    last_nav: str,
) -> Dict[str, Any]:
    """Return display text, color, optional R/T ref for one field."""
    if cursor < 0 or cursor >= len(rows):
        return {"text": "—", "color": COLOR_BLACK, "ref": None, "omitted": True}
    row = rows[cursor]
    raw = field_raw(row, field_key)
    # For display of current in-force: __DEL__ on this row means cleared
    if is_del_token(raw):
        disp = "Deleted"
        in_force_empty = True
    elif raw == "":
        disp = "—"
        in_force_empty = True
    else:
        disp = raw
        in_force_empty = False

    chg_i = last_change_index(rows, field_key, cursor)
    st_cur = seat_turn_of_row(row)
    color = COLOR_BLACK
    ref = None

    if last_nav == NAV_STEP and chg_i is not None:
        if chg_i == cursor:
            color = COLOR_RED
            if is_del_token(field_raw(rows[chg_i], field_key)):
                disp = "Deleted"
        else:
            st_ch = seat_turn_of_row(rows[chg_i])
            if st_ch is not None and st_ch == st_cur:
                color = COLOR_BLUE
                if is_del_token(field_raw(rows[chg_i], field_key)) and in_force_empty:
                    disp = "Deleted"
            else:
                color = COLOR_BLACK
                if st_ch is not None:
                    ref = f"R{st_ch[0]}T{st_ch[1]}"
    else:
        # jump / default black — still show last-update R/T when useful
        if chg_i is not None and chg_i != cursor:
            st_ch = seat_turn_of_row(rows[chg_i])
            if st_ch is not None:
                ref = f"R{st_ch[0]}T{st_ch[1]}"
        if in_force_empty and not is_del_token(raw):
            disp = "—"
        elif is_del_token(raw) and last_nav != NAV_STEP:
            disp = "—"  # no Deleted on black

    return {
        "text": disp,
        "color": color,
        "ref": ref,
        "change_index": chg_i,
        "omitted": False,
    }


@dataclass
class DigUiState:
    enabled: bool = False
    cat1: List[int] = field(default_factory=list)
    cat2: List[int] = field(default_factory=list)
    cat1_text: str = ""
    cat2_text: str = ""
    focus: Optional[str] = None  # "cat1" | "cat2" | None
    hits: List[int] = field(default_factory=list)
    hit_i: int = -1
    tab: str = "PLAN"
    last_nav: str = NAV_JUMP
    message: str = ""

    def set_cat1_text(self, text: str) -> None:
        self.cat1_text = text
        self.cat2_text = ""
        self.cat2 = []
        self.cat1 = parse_cat_list(text)
        self.focus = "cat1"

    def set_cat2_text(self, text: str) -> None:
        self.cat2_text = text
        self.cat1_text = ""
        self.cat1 = []
        self.cat2 = parse_cat_list(text)
        self.focus = "cat2"

    def rebuild_hits(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not self.cat1 and not self.cat2:
            self.hits = []
            self.hit_i = -1
            self.message = "Specify cat1 or cat2"
            return
        self.hits = build_hit_list(rows, self.cat1, self.cat2)
        if not self.hits:
            self.hit_i = -1
            self.message = "No MGlog rows match the filter"
        else:
            self.message = ""
            if self.hit_i < 0 or self.hit_i >= len(self.hits):
                self.hit_i = 0

    def sync_hit_i_from_cursor(self, cursor: int) -> None:
        if cursor in self.hits:
            self.hit_i = self.hits.index(cursor)


def dig_panel_rect() -> pygame.Rect:
    """SE Dig / Data panel under Events — top lowered 5px to clear Events hint."""
    r = EXECUTION_DEBUG_PANEL_RECT.copy()
    # Lower upper border by 5 px (more gap under Events / scroll hint)
    r.y += 5
    r.height = max(140, r.height - 24 - 5)
    return r


def dig_nav_rects(panel: Optional[pygame.Rect] = None) -> Dict[str, pygame.Rect]:
    """Previous / Next dig buttons **below dice** (only bottom button row)."""
    p = panel or HUMAN_BUTTON_PANEL_RECT
    dice = LEFT_DICE_PANEL_RECT
    h = 30
    gap = 8
    # Sit under dice, above panel bottom — no overlap with top nav
    y = min(int(dice.bottom + 8), p.bottom - h - 8)
    y = max(y, int(dice.bottom + 4))
    bw = (p.width - 2 * 10 - gap) // 2
    x0 = p.x + 10
    return {
        "dig_prev": pygame.Rect(x0, y, bw, h),
        "dig_next": pygame.Rect(x0 + bw + gap, y, bw, h),
    }


def cat_field_rects(panel: Optional[pygame.Rect] = None) -> Dict[str, pygame.Rect]:
    """Cat1 / cat2 inputs between top nav row and dice."""
    p = panel or HUMAN_BUTTON_PANEL_RECT
    dice_top = LEFT_DICE_PANEL_RECT.y
    # Just above dice
    y = max(p.y + 48, dice_top - 32)
    h = 26
    gap = 6
    label_w = 40
    field_w = (p.width - 20 - 2 * label_w - gap) // 2
    x0 = p.x + 10
    return {
        "cat1_label": pygame.Rect(x0, y, label_w, h),
        "cat1": pygame.Rect(x0 + label_w, y, field_w, h),
        "cat2_label": pygame.Rect(x0 + label_w + field_w + gap, y, label_w, h),
        "cat2": pygame.Rect(x0 + 2 * label_w + field_w + gap, y, field_w, h),
    }


def tab_rects(panel: pygame.Rect) -> Dict[str, pygame.Rect]:
    n = len(TABS)
    pad, gap, h = 6, 4, 22
    y = panel.bottom - h - 6
    bw = max(40, (panel.width - 2 * pad - gap * (n - 1)) // n)
    x = panel.x + pad
    out: Dict[str, pygame.Rect] = {}
    for tab in TABS:
        out[tab] = pygame.Rect(x, y, bw, h)
        x += bw + gap
    return out


def _ensure_fonts() -> None:
    try:
        if Font is not None:
            Font.initialize_fonts()
    except Exception:
        pass


def _font_small():
    _ensure_fonts()
    try:
        return Font.SMALL.value["regular"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 10)


def _font_small_bold():
    _ensure_fonts()
    try:
        return Font.SMALL.value["bold"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 10, bold=True)


def _font_normal():
    _ensure_fonts()
    try:
        return Font.NORMAL.value["regular"]  # type: ignore[union-attr]
    except Exception:
        return pygame.font.SysFont("Comic Sans MS", 16)


def _draw_btn(
    screen: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    *,
    enabled: bool = True,
    selected: bool = False,
) -> None:
    """Tab/nav chrome. Selected tab is drawn **disabled** (current sub-panel)."""
    green = COLORS.get("GREEN", (0, 255, 0))
    gray = COLORS.get("GRAY", (169, 169, 169))
    white = COLORS.get("WHITE", (255, 255, 255))
    lgray = COLORS.get("LGRAY", (200, 200, 200))
    pygame.draw.rect(screen, lgray, rect)
    # Active sub-panel button is disabled (gray); others enabled (green/white)
    if selected:
        border = gray
        tc = gray
    elif enabled:
        border = green
        tc = white
    else:
        border = gray
        tc = gray
    pygame.draw.rect(screen, border, rect, 2)
    font = _font_small()
    text = font.render(label, True, tc)
    screen.blit(text, text.get_rect(center=rect.center))


def fields_for_tab(tab: str) -> Tuple[Tuple[str, str], ...]:
    t = str(tab or "PLAN").upper()
    if t == "ACT":
        return ACT_FIELDS
    if t == "WHY":
        return WHY_FIELDS
    if t == "MORE":
        return MORE_FIELDS
    return PLAN_FIELDS


def is_ip_phase(row: Optional[Mapping[str, Any]]) -> bool:
    if not row:
        return False
    phase = str(row.get("phase") or "").lower()
    if "initial" in phase:
        return True
    ev = str(row.get("event") or "").lower()
    return ev.startswith("ip_")


def draw_se_dig_panel(
    screen: pygame.Surface,
    dig: DigUiState,
    rows: Sequence[Mapping[str, Any]],
    cursor: int,
    *,
    panel: Optional[pygame.Rect] = None,
) -> Dict[str, pygame.Rect]:
    """Draw SE Dig panel; return tab rects."""
    rect = panel or dig_panel_rect()
    black = COLORS.get("BLACK", (0, 0, 0))
    lgray = COLORS.get("LGRAY", (210, 210, 210))
    dgray = COLORS.get("DGRAY", (80, 80, 80))
    pygame.draw.rect(screen, lgray, rect)
    pygame.draw.rect(screen, black, rect, 2)

    title_f = _font_normal()
    small = _font_small()
    bold = _font_small_bold()
    y = rect.y + 6
    x = rect.x + 8
    screen.blit(title_f.render("SE Dig", True, black), (x, y))
    y += 20

    # Hit chip
    if dig.hits:
        chip = f"hit {dig.hit_i + 1}/{len(dig.hits)}"
    else:
        chip = "hit —"
    filt = ""
    if dig.cat1:
        filt = f"cat1={','.join(str(c) for c in dig.cat1)}"
    elif dig.cat2:
        filt = f"cat2={','.join(str(c) for c in dig.cat2)}"
    screen.blit(small.render(f"{chip}  {filt}", True, dgray), (x + 90, y - 18))

    row = rows[cursor] if 0 <= cursor < len(rows) else None
    body_bottom = rect.bottom - 30
    line_h = 14

    if dig.message and (not dig.hits or not dig.cat1 and not dig.cat2):
        msg = dig.message
        screen.blit(bold.render(msg[:70], True, COLOR_RED), (x, y))
        y += line_h + 4

    if row is not None and is_ip_phase(row):
        screen.blit(
            small.render(
                "SE Dig data is available from Execution only (IP has no CS samples).",
                True,
                dgray,
            ),
            (x, y),
        )
    elif row is not None:
        # Collect field displays + top 2 R/T refs
        refs: List[str] = []
        for label, key in fields_for_tab(dig.tab):
            if y + line_h > body_bottom:
                break
            info = display_field_at_cursor(
                rows, cursor, key, last_nav=dig.last_nav
            )
            text = info["text"]
            col = info["color"]
            ref = info.get("ref")
            star = ""
            if ref and dig.last_nav != NAV_STEP:
                if ref not in refs and len(refs) < 2:
                    refs.append(ref)
                if ref in refs:
                    star = " (*)" if refs.index(ref) == 0 else " (**)"
                else:
                    star = f" ({ref})"
            line = f"{label}: {text}{star}"
            screen.blit(small.render(line[:78], True, col), (x, y))
            y += line_h
        if refs:
            foot = "  ".join(
                f"{'*' * (i + 1)} {refs[i]}" for i in range(len(refs))
            )
            screen.blit(small.render(foot, True, dgray), (x, body_bottom - line_h))

    # Tabs: current tab disabled (PLAN when on PLAN, etc.)
    tabs = tab_rects(rect)
    for tab, trect in tabs.items():
        is_cur = tab == dig.tab
        _draw_btn(
            screen,
            trect,
            tab,
            enabled=not is_cur,
            selected=is_cur,
        )
    return tabs


def draw_dig_filters_and_nav(
    screen: pygame.Surface,
    dig: DigUiState,
    *,
    can_prev: bool,
    can_next: bool,
) -> Dict[str, pygame.Rect]:
    """Cat fields + dig Prev/Next. Returns all interactive rects."""
    black = COLORS.get("BLACK", (0, 0, 0))
    white = COLORS.get("WHITE", (255, 255, 255))
    lgray = COLORS.get("LGRAY", (200, 200, 200))
    green = COLORS.get("GREEN", (0, 255, 0))
    gray = COLORS.get("GRAY", (169, 169, 169))
    small = _font_small()
    rects: Dict[str, pygame.Rect] = {}
    rects.update(cat_field_rects())
    rects.update(dig_nav_rects())

    # labels + fields
    screen.blit(small.render("cat1", True, black), rects["cat1_label"].topleft)
    screen.blit(small.render("cat2", True, black), rects["cat2_label"].topleft)
    for key, text in (("cat1", dig.cat1_text), ("cat2", dig.cat2_text)):
        r = rects[key]
        pygame.draw.rect(screen, white, r)
        # Focus = green border only (no "|" caret in the value)
        border = green if dig.focus == key else black
        pygame.draw.rect(screen, border, r, 2)
        shown = text.strip()
        screen.blit(small.render(shown[:28], True, black), (r.x + 4, r.y + 5))

    _draw_btn(screen, rects["dig_prev"], "Previous", enabled=can_prev)
    _draw_btn(screen, rects["dig_next"], "Next", enabled=can_next)
    return rects


def handle_dig_key(
    dig: DigUiState,
    event: Any,
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Handle KEYDOWN for cat fields. Returns True if consumed."""
    if dig.focus not in ("cat1", "cat2"):
        return False
    key = getattr(event, "key", None)
    uni = getattr(event, "unicode", "") or ""
    if key == pygame.K_BACKSPACE:
        if dig.focus == "cat1":
            dig.set_cat1_text(dig.cat1_text[:-1])
        else:
            dig.set_cat2_text(dig.cat2_text[:-1])
        dig.rebuild_hits(rows)
        return True
    if key == pygame.K_RETURN:
        dig.focus = None
        dig.rebuild_hits(rows)
        return True
    if key == pygame.K_ESCAPE:
        dig.focus = None
        return True
    if uni and (uni.isdigit() or uni in ",; "):
        if dig.focus == "cat1":
            dig.set_cat1_text(dig.cat1_text + uni)
        else:
            dig.set_cat2_text(dig.cat2_text + uni)
        dig.rebuild_hits(rows)
        return True
    return False


def handle_dig_click(
    dig: DigUiState,
    pos: Tuple[int, int],
    rects: Mapping[str, pygame.Rect],
    tab_rects_map: Mapping[str, pygame.Rect],
    rows: Sequence[Mapping[str, Any]],
    cursor: int,
) -> Optional[str]:
    """Returns action: dig_prev|dig_next|tab|focus|None."""
    for tab, r in tab_rects_map.items():
        if r.collidepoint(pos):
            # Current sub-panel button is disabled — ignore click
            if tab == dig.tab:
                return "tab:noop"
            dig.tab = tab
            return f"tab:{tab}"
    for key in ("cat1", "cat2"):
        r = rects.get(key)
        if r is not None and r.collidepoint(pos):
            dig.focus = key
            return f"focus:{key}"
    if rects.get("dig_prev") and rects["dig_prev"].collidepoint(pos):
        return "dig_prev"
    if rects.get("dig_next") and rects["dig_next"].collidepoint(pos):
        return "dig_next"
    # click outside clears focus
    dig.focus = None
    return None


def dig_step(dig: DigUiState, *, direction: int) -> Optional[int]:
    """Move hit_i by ±1; return new row index or None."""
    if not dig.hits:
        return None
    if dig.hit_i < 0:
        dig.hit_i = 0 if direction > 0 else len(dig.hits) - 1
    else:
        ni = dig.hit_i + int(direction)
        if ni < 0 or ni >= len(dig.hits):
            return None
        dig.hit_i = ni
    dig.last_nav = NAV_JUMP
    return dig.hits[dig.hit_i]


def mark_step_nav(dig: DigUiState) -> None:
    dig.last_nav = NAV_STEP


def mark_jump_nav(dig: DigUiState) -> None:
    dig.last_nav = NAV_JUMP


__all__ = [
    "NAV_STEP",
    "NAV_JUMP",
    "TABS",
    "DigUiState",
    "parse_cat_list",
    "row_event_index",
    "find_row_index_by_event_index",
    "row_matches_cats",
    "build_hit_list",
    "display_field_at_cursor",
    "last_change_index",
    "dig_panel_rect",
    "dig_nav_rects",
    "cat_field_rects",
    "draw_se_dig_panel",
    "draw_dig_filters_and_nav",
    "handle_dig_key",
    "handle_dig_click",
    "dig_step",
    "mark_step_nav",
    "mark_jump_nav",
    "is_ip_phase",
]
