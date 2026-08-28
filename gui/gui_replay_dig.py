"""SE Dig (SE5+): probe hits, cat XOR filters, SE Dig panel.

Tabs (P0): STR, PLN1, PLN2, ACT, WHY1, MORE (WHY2 removed).
Loads fields from enriched dense ``mglog_cs.csv`` rows (no SE recompute).
PLN2: geo catalog + Show; PLN1: way-component shell (P5 fills content).
Product: ``docs/changes_PLAN_v2_coding.md``.
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
    SE_PLAN_FIELDS,
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

# P0: PLN1 (components) + PLN2 (geo catalog); WHY2 removed; Show on PLN2 only
TABS: Tuple[str, ...] = ("STR", "PLN1", "PLN2", "ACT", "WHY1", "MORE")

# Fixed field slots per tab (stable layout)
STR_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("Way sticky", "sticky_way_id"),
    ("Way id", "way_id"),  # omit in UI when == sticky
    ("Tags", "way_def_tags"),
    ("Given up", "_given_up"),
    ("Sticky", "_sticky_chip"),  # S62 / C62 combined
    ("Rec tgt", "rec_target_id"),
    # Dig §5: ETA-Table drawn as a block (see draw_str_eta_block) — markers only
    ("ETA-Table", "_eta_block"),
)

# Alias: old PLAN_FIELDS name → STR (legacy); PLN2 uses catalog helpers
PLAN_FIELDS = STR_FIELDS

ACT_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("BA label", "ba_label"),
    ("BA action", "ba_action"),
    ("BA target", "ba_target_id"),
    ("BA source", "ba_source"),
    ("BA roads", "ba_roads_fp"),
    ("Race BA", "_race_ba_note"),  # P2: risk M/H chase note
    ("Risk", "risk_level"),
    ("Sup type", "supporting_action_type"),
    ("Sup tgt", "supporting_target_id"),
    ("Sticky roads", "sticky_roads_fp"),
)

WHY1_FIELDS: Tuple[Tuple[str, str], ...] = (
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

WHY_FIELDS = WHY1_FIELDS  # alias

# PLN1 shell until P5 emits pln1_* CS fields
PLN1_PLACEHOLDER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("note", "_pln1_placeholder"),
)

# PLN2 geo catalog — table drawn by draw_pln2_table; placeholder if empty CS
PLN2_PLACEHOLDER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("note", "_plan_placeholder"),
)

# Back-compat aliases
PLAN_PLACEHOLDER_FIELDS = PLN2_PLACEHOLDER_FIELDS
WHY2_PLACEHOLDER_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("note", "_why2_removed"),
)


def normalize_dig_tab(tab: Any) -> str:
    """Map legacy PLAN/WHY2 names to P0 tabs."""
    t = str(tab or "STR").strip().upper()
    if t in ("PLAN", "PLN2"):
        return "PLN2"
    if t == "PLN1":
        return "PLN1"
    if t == "WHY2":
        return "PLN2"  # WHY2 removed — land on geo catalog
    if t in ("WHY", "WHY1"):
        return "WHY1"
    if t in TABS:
        return t
    return "STR"

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
    ("owned", "_owned"),  # WP1.3: LA/LR + DCards + S/C (no R=)
    ("way def", "way_def_tags"),
    ("VP-E", "unplayed_vp_cards"),
    ("rem VP", "remaining_vp_cards"),
    ("VP eff", "vp_effective"),
    ("plan asof", "plan_asof_rt"),
) + tuple((f"L2 {k}", k) for k in SE_L2_FIELDS) + tuple(
    (f"RA {k}", k) for k in SE_REASSESS_FIELDS
) + tuple((f"P {k}", k) for k in SE_PLAN_FIELDS if k not in ("plan_asof_rt", "plan_why2"))

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


def active_turn_player_id(
    rows: Sequence[Mapping[str, Any]], cursor: int
) -> Optional[int]:
    """Player whose **turn** it is at *cursor* (from latest turn_start at same R/T).

    ``resource_production`` rows use the **recipient** player_id, which is not
    the seat to show for Dig STR/PLN honesty.
    """
    if cursor < 0 or cursor >= len(rows):
        return None
    row = rows[cursor]
    st = seat_turn_of_row(row)
    if st is None:
        return _safe_int(row.get("player_id"))
    rnd, turn = st
    for i in range(cursor, -1, -1):
        r = rows[i]
        if seat_turn_of_row(r) != (rnd, turn):
            continue
        ev = str(r.get("event") or "").strip().lower()
        if ev == "turn_start":
            return _safe_int(r.get("player_id"))
    return _safe_int(row.get("player_id"))


_SE_DIG_TABS = frozenset({"STR", "PLN1", "PLN2", "ACT", "WHY1", "MORE"})


def se_display_row_for_cursor(
    rows: Sequence[Mapping[str, Any]],
    cursor: int,
    *,
    tab: str = "PLN2",
) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    """Row used for Dig SE tabs + optional banner note.

    For STR/PLN/ACT/… use the **active turn seat's** latest SE snapshot at or
    before *cursor* (not the event actor). Returns ``(display_row, note)``.
    """
    if cursor < 0 or cursor >= len(rows):
        return None, None
    base = rows[cursor]
    t = normalize_dig_tab(tab)
    if t not in _SE_DIG_TABS:
        return base, None
    aid = active_turn_player_id(rows, cursor)
    actor = _safe_int(base.get("player_id"))
    if aid is None:
        return base, None
    # Walk back for latest row of active seat ≤ cursor (dense carry lives there)
    src: Optional[Mapping[str, Any]] = None
    for i in range(cursor, -1, -1):
        if _safe_int(rows[i].get("player_id")) == int(aid):
            src = rows[i]
            break
    if src is None:
        note = f"No SE row yet for turn seat P{aid}"
        return base, note
    if actor is not None and int(actor) != int(aid):
        note = f"Turn seat P{aid} (event actor P{actor})"
    else:
        note = None
    # Overlay: keep timeline event meta from *base*, SE/PLN fields from *src*
    from core.batch.cs_se_snapshot import SE_FIELD_KEYS

    merged = dict(base)
    for k in SE_FIELD_KEYS:
        merged[k] = src.get(k, "")
    # Probe cats for dig honesty stay on event row; SE strategy from turn seat
    return merged, note


def field_raw(row: Mapping[str, Any], key: str) -> str:
    # Absolute way composition from 142 CSV (Dig-time; ignores stale CS residual)
    if key == "way_def_tags":
        try:
            from core.strategy_way_residual import (
                format_tags_join,
                load_way_requirement,
                way_def_tags,
            )

            wid = row.get("sticky_way_id") or row.get("way_id")
            strat = load_way_requirement(wid)
            tags = way_def_tags(strat) if strat is not None else []
            if tags:
                return format_tags_join(tags)
        except Exception:
            pass
        # Fall through to CS cell
    if key == "_pln1_placeholder":
        try:
            from core.strategy_pln1 import pln1_lines_for_dig

            lines = pln1_lines_for_dig(row)
            if lines:
                return " | ".join(f"{a}: {b}" for a, b in lines[:4])
        except Exception:
            pass
        return "PLN1 not sampled (L0 or PLAN_SNAPSHOT off)"
    if key == "_plan_placeholder":
        try:
            from core.strategy_plan_snapshot import plan_lines_for_dig

            lines = plan_lines_for_dig(row)
            if lines:
                return " | ".join(f"{a}: {b}" for a, b in lines[:3])
        except Exception:
            pass
        return "No PLN2 catalog snapshot"
    if key in ("_why2_placeholder", "_why2_removed"):
        return "WHY2 removed — see PLN1 Words + PLN2 Why"
    if key == "_la_lr":
        la = parse_se_cell(row.get("way_la", ""))
        lr = parse_se_cell(row.get("way_lr", ""))
        parts = []
        if la != "":
            parts.append(f"LA={la}")
        if lr != "":
            parts.append(f"LR={lr}")
        return " ".join(parts)
    if key == "_given_up":
        try:
            from core.strategy_plan_snapshot import _format_given_up

            return _format_given_up(row) or "—"
        except Exception:
            return "—"
    if key == "_sticky_chip":
        try:
            from core.strategy_plan_snapshot import _sticky_chip

            return _sticky_chip(row) or "—"
        except Exception:
            tid = parse_se_cell(row.get("sticky_target_id", ""))
            return tid or "—"
    # WP-J STR ETA-Table: Type | Old | New | △t (static model; rows/cursor filled in display)
    if key in ("_eta_hdr", "_eta_plan", "_eta_prev", "_eta_delta"):
        try:
            from core.strategy_plan_snapshot import format_str_eta_table_line

            return format_str_eta_table_line(key, row) or "—"
        except Exception:
            return "—"
    if key == "_eta_tgt":
        return ""  # removed from STR (refinements)
    if key == "_race_ba_note":
        # Dig-time note from CS risk + sticky roads / target
        risk_raw = str(parse_se_cell(row.get("risk_level", "")) or "").lower()
        try:
            from core.strategy_race_ba import _norm_risk, _risk_is_race

            risk = _norm_risk(risk_raw)
            if not _risk_is_race(risk):
                return "risk=L → current BA order"
        except Exception:
            risk = risk_raw
            if risk in ("", "low", "l", "safe"):
                return "risk=L → current BA order"
        roads = parse_se_cell(row.get("sticky_roads_fp", "") or row.get("ba_roads_fp", ""))
        tgt = parse_se_cell(row.get("sticky_target_id", "") or row.get("ba_target_id", ""))
        if roads and roads not in ("—", ""):
            return f"risk={risk or '?'} → chase key road ({roads})"
        if tgt and tgt not in ("—", ""):
            return f"risk={risk or '?'} → chase target {tgt}"
        src = parse_se_cell(row.get("ba_source", ""))
        if "race_ba" in src:
            return f"risk={risk or '?'} → race BA active"
        return f"risk={risk or '?'} → prefer race structure over DCard"
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
        # WP1.3: prefer owned_display (LA/LR/TFR/…); never emphasize R= piece count
        od = parse_se_cell(row.get("owned_display", ""))
        if od:
            return od
        parts = []
        for lab, k in (
            ("LA", "way_la"),  # fallback weak
            ("S", "settlements_owned"),
            ("C", "cities_owned"),
        ):
            v = parse_se_cell(row.get(k, ""))
            if v == "":
                continue
            if lab == "LA" and v in ("0", "false", "False"):
                continue
            if lab == "LA" and v in ("1", "true", "True"):
                # Prefer lr_flag/la_flag if present
                continue
            if lab in ("S", "C") and v not in ("", "0"):
                parts.append(f"{lab}={v}")
        # specials from flags
        for lab, k in (("LA", "la_flag"), ("LR", "lr_flag")):
            v = parse_se_cell(row.get(k, ""))
            if v in ("1", "true", "True"):
                parts.insert(0, lab)
        return " ".join(parts) if parts else "—"
    return parse_se_cell(row.get(key, ""))


def is_l2_refresh_row(row: Optional[Mapping[str, Any]]) -> bool:
    """WP0.5 / WP3: True when this CS/MGlog row is a full L2 / explore sample."""
    if not row:
        return False
    mode = str(row.get("refresh_mode") or "").strip().lower()
    if mode in ("l2", "explore", "force", "full"):
        return True
    detail = str(row.get("refresh_mode_detail") or "").strip().lower()
    if "l2" in detail or "explore" in detail:
        return True
    # WP3: primary explicit code present
    elc = parse_se_cell(row.get("explicit_l2_code", ""))
    if elc not in ("", "—", "0", "none", "null"):
        return True
    etr = parse_se_cell(row.get("explicit_trigger", ""))
    if etr and "explicit_142" in etr.lower():
        return True
    for k in ("l2_bucket", "l2_bucket_live", "l2_force_reason", "l2_gate"):
        v = parse_se_cell(row.get(k, ""))
        if v not in ("", "—", "0", "false", "none", "null"):
            # empty gate "l0" / "hand_only" is not L2
            vl = v.lower()
            if vl in ("l0", "hand_only", "hand", "skip", "skipped", "false", "0"):
                continue
            if k == "l2_gate" and vl in ("l0", "hand_only", "false", "0", "none"):
                continue
            return True
    return False


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
    value_row: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return display text, color, optional R/T ref for one field.

    WP0.3: R/T refs (``(*)`` / ``(**)``) available on step and jump nav.
    WP0.5: full L2 sample rows paint non-empty fields red on step nav.
    *value_row*: optional overlay (turn-seat SE snapshot) for Dig honesty.
    """
    if cursor < 0 or cursor >= len(rows):
        return {"text": "—", "color": COLOR_BLACK, "ref": None, "omitted": True}
    row = value_row if value_row is not None else rows[cursor]
    # Dig §5: ETA block is drawn by draw_str_eta_block (not label: value)
    if field_key in ("_eta_block", "_eta_hdr", "_eta_plan", "_eta_prev", "_eta_delta"):
        return {
            "text": "",
            "color": COLOR_BLACK,
            "ref": None,
            "change_index": None,
            "omitted": field_key == "_eta_block",
            "l2_row": is_l2_refresh_row(row),
        }
    # WP5 dynamic PLAN/WHY2 lines (not SE field history)
    dyn = dynamic_plan_text(row, field_key)
    if dyn is not None:
        return {
            "text": dyn if dyn else "—",
            "color": COLOR_BLACK,
            "ref": None,
            "change_index": None,
            "omitted": False,
            "l2_row": is_l2_refresh_row(row),
        }
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

    if field_key.startswith("_plan_dyn") or field_key.startswith("_why2_dyn"):
        chg_i = None
    else:
        chg_i = last_change_index(rows, field_key, cursor)
    st_cur = seat_turn_of_row(row)
    color = COLOR_BLACK
    ref = None
    l2_row = is_l2_refresh_row(row)

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
        # WP0.5: L2 explore sample → paint nearly all STR/ACT/WHY fields red
        if l2_row and not in_force_empty and not field_key.startswith("_plan") and not field_key.startswith("_why2"):
            color = COLOR_RED
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

    # WP0.3: also attach ref on step when change is older (already set above);
    # on jump, ref is set in the else branch. Placeholders have no R/T.
    if field_key in ("_plan_placeholder", "_why2_placeholder"):
        ref = None

    # Plan / Previous ETA body: black normally, red only when this row changed
    # (no green/blue wash from the trailing Dt token).
    if field_key in ("_eta_plan", "_eta_prev"):
        if last_nav == NAV_STEP and chg_i is not None and chg_i == cursor:
            color = COLOR_RED
        else:
            color = COLOR_BLACK

    # Dedicated Dt line only: green if ≤0 else red.
    if field_key == "_eta_delta" and not in_force_empty:
        try:
            from core.strategy_pln_words import dt_color_favourable

            parts = str(disp).split()
            if parts:
                tone = dt_color_favourable(parts[-1])
                if tone == "green":
                    color = COLORS.get("GREEN", (0, 160, 0))
                elif tone == "red":
                    color = COLOR_RED
        except Exception:
            pass

    return {
        "text": disp,
        "color": color,
        "ref": ref,
        "change_index": chg_i,
        "omitted": False,
        "l2_row": l2_row,
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
    tab: str = "STR"
    last_nav: str = NAV_JUMP
    message: str = ""
    show_plan: bool = False  # PLN2 Show circles from plan_show

    def normalized_tab(self) -> str:
        t = normalize_dig_tab(self.tab)
        if t != self.tab:
            self.tab = t
        return t

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
    """Tab strip on bottom row; Show sits **above MORE** (not beside it)."""
    n = len(TABS)
    pad, gap, h = 6, 4, 22
    y = panel.bottom - h - 6
    bw = max(40, (panel.width - 2 * pad - gap * (n - 1)) // n)
    x = panel.x + pad
    out: Dict[str, pygame.Rect] = {}
    for tab in TABS:
        out[tab] = pygame.Rect(x, y, bw, h)
        x += bw + gap
    # Show: extra PLAN control stacked above the MORE tab button
    more = out.get("MORE")
    if more is not None:
        out["SHOW"] = pygame.Rect(more.x, more.y - h - gap, more.width, h)
    else:
        out["SHOW"] = pygame.Rect(panel.right - pad - bw, y - h - gap, bw, h)
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


def _draw_show_btn(
    screen: pygame.Surface,
    rect: pygame.Rect,
    *,
    on: bool = False,
) -> None:
    """Show toggle: always enabled (green border), like stage3and4 Test button.

    Never uses tab ``selected``=gray. ON still keeps green border; label reflects state.
    """
    green = COLORS.get("GREEN", (0, 255, 0))
    black = COLORS.get("BLACK", (0, 0, 0))
    white = COLORS.get("WHITE", (255, 255, 255))
    lgray = COLORS.get("LGRAY", (200, 200, 200))
    pygame.draw.rect(screen, lgray, rect)
    pygame.draw.rect(screen, green, rect, 2)
    font = _font_small()
    # ON: black text (active); OFF: white on enabled chrome
    label = "Show*" if on else "Show"
    text = font.render(label, True, black if on else white)
    screen.blit(text, text.get_rect(center=rect.center))


def fields_for_tab(
    tab: str, row: Optional[Mapping[str, Any]] = None
) -> Tuple[Tuple[str, str], ...]:
    """Field slots for a tab. PLN1/PLN2 from CS snapshots."""
    t = normalize_dig_tab(tab)
    if t == "PLN1":
        try:
            from core.strategy_pln1 import pln1_lines_for_dig

            if row is not None:
                lines = pln1_lines_for_dig(row)
                return tuple((lab, f"_pln1_dyn:{i}") for i, (lab, _txt) in enumerate(lines))
        except Exception:
            pass
        return PLN1_PLACEHOLDER_FIELDS
    if t == "PLN2":
        try:
            from core.strategy_plan_snapshot import plan_lines_for_dig

            if row is not None:
                lines = plan_lines_for_dig(row)
                return tuple((lab, f"_plan_dyn:{i}") for i, (lab, _txt) in enumerate(lines))
        except Exception:
            pass
        return PLN2_PLACEHOLDER_FIELDS
    if t == "ACT":
        return ACT_FIELDS
    if t == "WHY1":
        return WHY1_FIELDS
    if t == "MORE":
        return MORE_FIELDS
    if t == "STR":
        try:
            from core.strategy_plan_snapshot import str_field_slots

            return tuple(str_field_slots(row))
        except Exception:
            return STR_FIELDS
    return STR_FIELDS


def dynamic_plan_text(row: Mapping[str, Any], key: str) -> Optional[str]:
    """Resolve synthetic PLN1/PLN2 field keys to display text."""
    if key.startswith("_plan_dyn:"):
        try:
            from core.strategy_plan_snapshot import plan_lines_for_dig

            idx = int(key.split(":", 1)[1])
            lines = plan_lines_for_dig(row)
            if 0 <= idx < len(lines):
                return str(lines[idx][1])
        except Exception:
            return None
        return None
    if key.startswith("_pln1_dyn:"):
        try:
            from core.strategy_pln1 import pln1_lines_for_dig

            idx = int(key.split(":", 1)[1])
            lines = pln1_lines_for_dig(row)
            if 0 <= idx < len(lines):
                return str(lines[idx][1])
        except Exception:
            return None
        return None
    return None


def is_ip_phase(row: Optional[Mapping[str, Any]]) -> bool:
    if not row:
        return False
    phase = str(row.get("phase") or "").lower()
    if "initial" in phase:
        return True
    ev = str(row.get("event") or "").lower()
    return ev.startswith("ip_")


def _fit_cell(font: Any, text: str, max_w: int) -> str:
    s = str(text or "")
    if font.size(s)[0] <= max_w:
        return s
    while s and font.size(s + "…")[0] > max_w:
        s = s[:-1]
    return s + "…" if s else ""


def _blit_eta_line_with_triangle_t(
    screen: pygame.Surface,
    font: Any,
    text: str,
    color: Tuple[int, int, int],
    *,
    x: int,
    y: int,
) -> None:
    """Blit ETA line; draw a real triangle+t where △t would tofu as □t."""
    # Prefer splitting on △t mark from format_str_eta_table_line
    mark = "△t"
    if mark not in text:
        # Legacy / missing glyph already replaced
        screen.blit(font.render(str(text)[:78], True, color), (x, y))
        return
    left, _, right = str(text).partition(mark)
    cx = x
    if left:
        surf = font.render(left, True, color)
        screen.blit(surf, (cx, y))
        cx += surf.get_width()
    # Upward triangle (Dig §5: triangle+t, not square tofu)
    tri_h = max(7, int(getattr(font, "get_height", lambda: 12)() * 0.55))
    tri_w = max(6, int(tri_h * 0.9))
    # baseline-ish vertical align
    top = y + max(1, (font.get_height() - tri_h) // 2)
    pygame.draw.polygon(
        screen,
        color,
        [
            (cx + tri_w // 2, top),
            (cx, top + tri_h),
            (cx + tri_w, top + tri_h),
        ],
    )
    cx += tri_w + 1
    screen.blit(font.render("t" + right, True, color), (cx, y))


def _blit_dt_value_with_tone_dot(
    screen: pygame.Surface,
    font: Any,
    text: str,
    *,
    x: int,
    y: int,
    max_w: int,
    tone: str = "",
) -> None:
    """Black △t/Dt number with a small green/red circle behind it (STR + PLN2)."""
    black = COLORS.get("BLACK", (0, 0, 0))
    green = COLORS.get("GREEN", (0, 160, 0))
    txt = _fit_cell(font, str(text or ""), max(8, int(max_w) - 2))
    surf = font.render(txt, True, black)
    tw, th = surf.get_width(), surf.get_height()
    # Dot sits behind the number (slightly larger than text height)
    radius = max(5, min(9, th // 2 + 2))
    cx = x + max(radius, tw // 2)
    cy = y + max(radius, th // 2)
    if tone == "green":
        pygame.draw.circle(screen, green, (cx, cy), radius)
    elif tone == "red":
        pygame.draw.circle(screen, COLOR_RED, (cx, cy), radius)
    # Center black text over the dot
    tx = cx - tw // 2
    ty = cy - th // 2
    screen.blit(surf, (tx, ty))


def draw_str_eta_block(
    screen: pygame.Surface,
    row: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    cursor: int,
    *,
    x: int,
    y: int,
    width: int,
    body_bottom: int,
    small: Any,
    bold: Any,
    last_nav: str = "",
) -> int:
    """Dig §5 STR ETA-Table — same Dig font + column layout style as PLN2."""
    black = COLORS.get("BLACK", (0, 0, 0))
    dgray = COLORS.get("DGRAY", (80, 80, 80))
    line_h = 14
    try:
        from core.strategy_plan_snapshot import str_eta_table_model
        from core.strategy_pln_words import dt_color_favourable
    except Exception as exc:
        screen.blit(small.render(f"ETA-Table error: {exc}"[:60], True, COLOR_RED), (x, y))
        return y + line_h

    if y + line_h <= body_bottom:
        screen.blit(bold.render("ETA-Table", True, black), (x, y))
        y += line_h

    # Match PLN1/PLN2 density: compact fixed-ish columns (don't stretch across panel).
    # PLN2 uses ~0.10–0.14 fractions over full width (~7 cols); 4 stretched cols look sparse.
    panel_usable = max(80, int(width) - 4)
    # Target ~PLN2 column pixel width (~48–56px for short numeric headers)
    col_w = [52, 56, 56, 52]
    table_w = sum(col_w)
    if table_w > panel_usable:
        scale = panel_usable / float(table_w)
        col_w = [max(28, int(w * scale)) for w in col_w]
        col_w[-1] = max(36, panel_usable - sum(col_w[:-1]))

    model = str_eta_table_model(row, rows=rows, cursor=cursor)
    table_rows: List[Tuple[Sequence[str], bool, Optional[str]]] = [
        (("Type", "Old", "New", "△t"), True, None),
        (
            (
                "Plan",
                _fmt_eta_cell(model.get("plan_old")),
                _fmt_eta_cell(model.get("plan_new")),
                _fmt_eta_dt_cell(model.get("plan_dt")),
            ),
            False,
            _fmt_eta_dt_cell(model.get("plan_dt")),
        ),
        (
            (
                "Prev",
                _fmt_eta_cell(model.get("prev_old")),
                _fmt_eta_cell(model.get("prev_new")),
                _fmt_eta_dt_cell(model.get("prev_dt")),
            ),
            False,
            _fmt_eta_dt_cell(model.get("prev_dt")),
        ),
    ]

    for cells, is_hdr, dt_for_color in table_rows:
        if y + line_h > body_bottom:
            break
        font = bold if is_hdr else small
        cx = x
        for i, cell in enumerate(cells):
            w = col_w[i] if i < len(col_w) else 40
            col = dgray if is_hdr else black
            cell_s = str(cell or "")
            if is_hdr and i == 3:
                _blit_eta_line_with_triangle_t(
                    screen, font, "△t", col, x=cx, y=y
                )
            elif not is_hdr and i == 3:
                tone = ""
                try:
                    tone = dt_color_favourable(dt_for_color) if dt_for_color is not None else ""
                except Exception:
                    tone = ""
                _blit_dt_value_with_tone_dot(
                    screen,
                    font,
                    cell_s,
                    x=cx,
                    y=y,
                    max_w=w,
                    tone=tone,
                )
            else:
                screen.blit(
                    font.render(_fit_cell(font, cell_s, w - 2), True, col),
                    (cx, y),
                )
            cx += w
        y += line_h
    return y


def _fmt_eta_cell(v: Any) -> str:
    try:
        from core.strategy_plan_snapshot import _fmt_eta_num

        return _fmt_eta_num(v)
    except Exception:
        return "—" if v is None else str(v)


def _fmt_eta_dt_cell(v: Any) -> str:
    try:
        from core.strategy_plan_snapshot import _fmt_eta_dt

        return _fmt_eta_dt(v)
    except Exception:
        return "—" if v is None else str(v)


def draw_pln1_panel(
    screen: pygame.Surface,
    row: Mapping[str, Any],
    *,
    x: int,
    y: int,
    width: int,
    body_bottom: int,
    small: Any,
    bold: Any,
) -> int:
    """V5-D: Way line + Comp/Tag/Need/Why/Target table. Returns next y."""
    black = COLORS.get("BLACK", (0, 0, 0))
    dgray = COLORS.get("DGRAY", (80, 80, 80))
    line_h = 14
    # Way absolute composition
    try:
        from core.strategy_pln1 import pln1_lines_for_dig

        for lab, txt in pln1_lines_for_dig(row):
            if lab != "Way":
                continue
            if y + line_h > body_bottom:
                return y
            screen.blit(bold.render(f"Way: {txt}", True, black), (x, y))
            y += line_h
            break
    except Exception:
        pass
    try:
        from core.strategy_pln1_table import pln1_component_table

        tbl = pln1_component_table(row)
    except Exception as exc:
        screen.blit(small.render(f"PLN1 table error: {exc}"[:60], True, COLOR_RED), (x, y))
        return y + line_h
    if tbl.get("empty"):
        return y
    fracs = (0.12, 0.12, 0.14, 0.22, 0.40)
    usable = max(80, int(width) - 4)
    col_w = [max(24, int(usable * f)) for f in fracs]
    col_w[-1] = max(40, usable - sum(col_w[:-1]))
    headers = tbl.get("headers") or ("Comp", "Tag", "Need", "Why", "Target")

    def _blit_row(
        cells: Sequence[str],
        yy: int,
        *,
        header: bool = False,
        row_red: bool = False,
    ):
        font = bold if header else small
        cx = x
        for i, cell in enumerate(cells):
            w = col_w[i] if i < len(col_w) else 40
            col = dgray if header else black
            # Dig §6: priority Buy/Build component row(s) entirely in red
            if row_red and not header:
                col = COLOR_RED
            txt = _fit_cell(font, str(cell), w - 2)
            screen.blit(font.render(txt, True, col), (cx, yy))
            cx += w

    if y + line_h <= body_bottom:
        _blit_row(list(headers), y, header=True)
        y += line_h
    # Dig §6: component rows only through R/DC — never Now/Also/Parked/New,
    # and never a prose banner below R/DC.
    for r in tbl.get("rows") or []:
        if y + line_h > body_bottom:
            break
        if r.get("spacer"):
            continue
        comp = str(r.get("comp") or "").strip()
        # Skip legacy Comp=New rows if any still appear in older table builders
        if not comp or comp.lower() == "new":
            continue
        cells = [
            comp,
            str(r.get("tag") or ""),
            str(r.get("need") or ""),
            str(r.get("why") or ""),
            str(r.get("target") or ""),
        ]
        # Dig §6: paint priority Buy/Build component row(s) red (not a banner)
        row_red = str(r.get("prio") or "").strip().lower() in ("1", "true", "yes")
        _blit_row(cells, y, row_red=row_red)
        y += line_h
    return y


def draw_pln2_table(
    screen: pygame.Surface,
    row: Mapping[str, Any],
    *,
    x: int,
    y: int,
    width: int,
    body_bottom: int,
    small: Any,
    bold: Any,
) -> int:
    """P4: draw PLN2 column table. Returns next y."""
    try:
        from core.strategy_plan_snapshot import pln2_table_for_dig

        tbl = pln2_table_for_dig(row)
    except Exception:
        screen.blit(
            small.render("PLN2 table error", True, COLOR_RED),
            (x, y),
        )
        return y + 14

    black = COLORS.get("BLACK", (0, 0, 0))
    dgray = COLORS.get("DGRAY", (80, 80, 80))
    line_h = 14

    if tbl.get("asof"):
        screen.blit(
            small.render(f"asof {tbl['asof']}", True, dgray),
            (x, y),
        )
        y += line_h

    if tbl.get("empty"):
        screen.blit(
            small.render(
                "No PLN2 catalog (L0 or PLAN_SNAPSHOT off)",
                True,
                dgray,
            ),
            (x, y),
        )
        return y + line_h

    # Column fractions of usable width (New slightly wider for S52*)
    fracs = (0.12, 0.14, 0.14, 0.10, 0.10, 0.12, 0.28)
    usable = max(80, int(width) - 4)
    col_w = [max(28, int(usable * f)) for f in fracs]
    # Fix rounding drift on last column
    col_w[-1] = max(40, usable - sum(col_w[:-1]))
    headers = tbl.get("headers") or ("New", "Tgt", "ETA", "Dist", "Risk", "△t", "Why")

    def _blit_row(cells: Sequence[str], yy: int, *, se: bool = False, header: bool = False):
        font = bold if header or se else small
        cx = x
        for i, cell in enumerate(cells):
            w = col_w[i] if i < len(col_w) else 40
            # SE pick: red on New (col 0) and Why (col 6)
            if se and i in (0, 6):
                col = COLOR_RED
            elif header:
                col = dgray
            else:
                col = black
            # Header △t: drawn triangle+t; value: black text + green/red dot behind
            cell_s = str(cell or "")
            if header and i == 5 and ("△" in cell_s or cell_s.strip() in ("△t", "Δt", "Dt")):
                _blit_eta_line_with_triangle_t(
                    screen, font, "△t", col, x=cx, y=yy
                )
            elif not header and i == 5:
                tone = ""
                try:
                    from core.strategy_pln_words import dt_color_favourable

                    tone = dt_color_favourable(cell_s, invert=False)
                except Exception:
                    tone = ""
                _blit_dt_value_with_tone_dot(
                    screen,
                    font,
                    cell_s,
                    x=cx,
                    y=yy,
                    max_w=w,
                    tone=tone,
                )
            else:
                txt = _fit_cell(font, cell_s, w - 2)
                screen.blit(font.render(txt, True, col), (cx, yy))
            cx += w

    if y + line_h <= body_bottom:
        _blit_row(list(headers), y, header=True)
        y += line_h

    for r in tbl.get("rows") or []:
        if y + line_h > body_bottom:
            break
        cells = [
            str(r.get("new") or ""),
            str(r.get("target") or "—"),
            str(r.get("eta") or "—"),
            str(r.get("dist") or "—"),
            str(r.get("risk") or "—"),
            str(r.get("delta") or "—"),
            str(r.get("why") or ""),
        ]
        # 9th overflow row: grey text listing omitted C/S
        if r.get("overflow") or str(r.get("kind") or "") == "OV":
            font = small
            cx = x
            label = "also"
            rest = str(r.get("why") or "")
            screen.blit(font.render(label, True, dgray), (cx, y))
            cx += col_w[0] if col_w else 40
            span = sum(col_w[1:]) if len(col_w) > 1 else max(40, int(width) - 50)
            screen.blit(
                font.render(_fit_cell(font, rest, span), True, dgray),
                (cx, y),
            )
        else:
            _blit_row(cells, y, se=bool(r.get("se_pick")))
        y += line_h
    return y


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

    raw_row = rows[cursor] if 0 <= cursor < len(rows) else None
    # Two button rows: Show above MORE (PLN2), then tab strip
    body_bottom = rect.bottom - 30 - 26
    line_h = 14
    cur_tab = dig.normalized_tab()
    # Dig honesty: STR/PLN/ACT follow **turn seat**, not RP recipient actor
    se_note: Optional[str] = None
    if raw_row is not None:
        row, se_note = se_display_row_for_cursor(rows, cursor, tab=cur_tab)
    else:
        row = None

    if dig.message and (not dig.hits or not dig.cat1 and not dig.cat2):
        msg = dig.message
        screen.blit(bold.render(msg[:70], True, COLOR_RED), (x, y))
        y += line_h + 4

    if se_note and row is not None and not is_ip_phase(raw_row or row):
        screen.blit(small.render(se_note, True, dgray), (x, y))
        y += line_h

    if row is not None and is_ip_phase(raw_row or row):
        screen.blit(
            small.render(
                "SE Dig data is available from Execution only (IP has no CS samples).",
                True,
                dgray,
            ),
            (x, y),
        )
    elif row is not None and cur_tab == "PLN2":
        # P4: columnar catalog (red New/Why on SE pick)
        draw_pln2_table(
            screen,
            row,
            x=x,
            y=y,
            width=rect.width - 16,
            body_bottom=body_bottom,
            small=small,
            bold=bold,
        )
    elif row is not None and cur_tab == "PLN1":
        y = draw_pln1_panel(
            screen,
            row,
            x=x,
            y=y,
            width=rect.width - 16,
            body_bottom=body_bottom,
            small=small,
            bold=bold,
        )
    elif row is not None:
        # Collect field displays + top 2 R/T refs
        refs: List[str] = []
        for label, key in fields_for_tab(cur_tab, row):
            if y + line_h > body_bottom:
                break
            # Dig §5: ETA-Table is a dedicated block (no "Plan: Plan …" duplication)
            if key == "_eta_block":
                y = draw_str_eta_block(
                    screen,
                    row,
                    rows,
                    cursor,
                    x=x,
                    y=y,
                    width=rect.width - 16,
                    body_bottom=body_bottom,
                    small=small,
                    bold=bold,
                    last_nav=str(dig.last_nav or ""),
                )
                continue
            info = display_field_at_cursor(
                rows, cursor, key, last_nav=dig.last_nav, value_row=row
            )
            text = info["text"]
            col = info["color"]
            ref = info.get("ref")
            star = ""
            # WP0.3: show (*) / (**) on step and jump nav
            if ref:
                if ref not in refs and len(refs) < 2:
                    refs.append(ref)
                if ref in refs:
                    star = " (*)" if refs.index(ref) == 0 else " (**)"
                else:
                    star = f" ({ref})"
            if str(label or "").strip():
                line = f"{label}: {text}{star}"
            else:
                line = f"{text}{star}"
            screen.blit(small.render(line[:78], True, col), (x, y))
            y += line_h
        if refs:
            foot = "  ".join(
                f"{'*' * (i + 1)} {refs[i]}" for i in range(len(refs))
            )
            screen.blit(small.render(foot, True, dgray), (x, body_bottom - line_h))

    # Tabs (bottom) + Show stacked above MORE (PLN2 only)
    tabs = tab_rects(rect)
    for tab, trect in tabs.items():
        if tab == "SHOW":
            if cur_tab == "PLN2":
                _draw_show_btn(screen, trect, on=bool(dig.show_plan))
            continue
        is_cur = tab == cur_tab
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
    """Returns action: dig_prev|dig_next|tab|show|focus|None."""
    for tab, r in tab_rects_map.items():
        if r.collidepoint(pos):
            if tab == "SHOW":
                # Show only clickable while PLN2 is active
                if dig.normalized_tab() != "PLN2":
                    return "show:hidden"
                dig.show_plan = not dig.show_plan
                return "show:on" if dig.show_plan else "show:off"
            # Current sub-panel button is disabled — ignore click
            cur = dig.normalized_tab()
            if tab == cur:
                return "tab:noop"
            dig.tab = normalize_dig_tab(tab)
            return f"tab:{dig.tab}"
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


def _player_for_row(game: Any, row: Mapping[str, Any]) -> Any:
    """Resolve Dig row seat on *game* (for map rebuild / live Show)."""
    if game is None or not row:
        return None
    try:
        pid = int(float(row.get("player_id")))
    except Exception:
        return None
    for p in list(getattr(game, "players", []) or []):
        if p is None:
            continue
        try:
            if int(getattr(p, "id", -1) or -1) == int(pid):
                return p
        except Exception:
            continue
    return None


def ensure_dig_row_reachability(game: Any, row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """WP-R5: rebuild reachability maps for the Dig-visible seat (incl. humans)."""
    if game is None or not row:
        return {"ok": False, "reason": "no_game_or_row"}
    player = _player_for_row(game, row)
    if player is None:
        return {"ok": False, "reason": "no_player"}
    try:
        from core.player_reachability import ensure_dig_seat_maps

        return ensure_dig_seat_maps(game, player)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def plan_show_circles_from_row(
    row: Optional[Mapping[str, Any]],
    *,
    board: Any = None,
    game: Any = None,
) -> List[Dict[str, Any]]:
    """Parse plan_show CS into circle descriptors (settle + opp only).

    Refinements v1 Q6: **no circles on occupied** intersections (already
    settled/citied on the replay board).

    WP-R5: when a live ``game`` is present, rebuild Dig-seat reachability maps
    and stamp ``map_dist`` / ``dist`` from maps onto settle circles (radius is
    still applied at draw via ``radius_for_show(..., path_distance=)``).
    Road overlays remain future — circles only.
    """
    if not row:
        return []
    # Dig scrub: freshen maps for this seat (AI + human)
    try:
        ensure_dig_row_reachability(game, row)
    except Exception:
        pass
    try:
        from core.strategy_plan_snapshot import parse_plan_show

        raw = parse_plan_show(row.get("plan_show"))
    except Exception:
        return []
    occupied: set = set()
    try:
        b = board or (getattr(game, "board", None) if game is not None else None)
        if b is not None:
            for inter in list(getattr(b, "intersections", None) or []):
                if inter is None:
                    continue
                if getattr(inter, "occupied_tf", False):
                    try:
                        occupied.add(int(getattr(inter, "id")))
                    except Exception:
                        pass
    except Exception:
        occupied = set()
    out: List[Dict[str, Any]] = []
    player = _player_for_row(game, row) if game is not None else None
    for c in raw:
        kind = str(c.get("kind") or "settle").lower()
        if kind in ("city", "road", "next_road", "tfr", "c"):
            continue
        if kind in ("settle", "s", "opp"):
            try:
                tid = int(c.get("id"))
            except Exception:
                tid = None
            if tid is not None and tid in occupied:
                continue
            entry = dict(c)
            if kind == "s":
                entry["kind"] = "settle"
            # Stamp map hop dist for settle circles when maps are fresh
            if (
                player is not None
                and tid is not None
                and str(entry.get("kind") or "").lower() in ("settle", "s")
            ):
                try:
                    from core.player_reachability import maps_are_fresh, sc_hop_distance

                    if maps_are_fresh(player):
                        hop = sc_hop_distance(player, int(tid))
                        if hop is not None:
                            entry["map_dist"] = int(hop)
                            if hop in (2, 3):
                                entry["dist"] = int(hop)
                except Exception:
                    pass
            out.append(entry)
    return out


def draw_plan_show_circles(
    screen: pygame.Surface,
    circles: Sequence[Mapping[str, Any]],
    *,
    positions: Optional[Mapping[Any, Any]] = None,
    player_colors: Optional[Mapping[Any, str]] = None,
    row_player_id: Optional[int] = None,
    row_player_color: Optional[str] = None,
) -> int:
    """Draw Show settlement/city circles (no roads).

    P1: radius from ``radius_for_show(turn_color, owner_color)`` matrix —
    **ignores** any baked radius in ``plan_show`` CS (stops same-color drift).
    WP-R5: optional ``path_distance`` (``map_dist`` / ``dist`` / ``roads_needed``)
    soft-modulates seat rings (d=3 → +2px). No road overlays yet.
    Own sites use turn-player color; ``opp`` rings when encoded (risk M/H).
    """
    if not circles:
        return 0
    try:
        from core.strategy_plan_snapshot import radius_for_show
    except Exception:
        def radius_for_show(  # type: ignore
            turn_color: Any, owner_color: Any, *, path_distance: Any = None
        ) -> int:
            return 5

    pos_map = positions
    color_lut = dict(player_colors or {})
    turn_color = str(row_player_color or "").strip()
    if not turn_color and row_player_id is not None:
        turn_color = str(
            color_lut.get(int(row_player_id))
            or color_lut.get(str(row_player_id))
            or ""
        )
    if pos_map is None:
        try:
            from gui.gui_constants import POSITIONS

            pos_map = POSITIONS.get("intersections") or {}
        except Exception:
            pos_map = {}
    try:
        from gui.gui_constants import COLORS as GUI_COLORS
    except Exception:
        GUI_COLORS = {
            "BLUE": (0, 0, 255),
            "RED": (255, 0, 0),
            "WHITE": (255, 255, 255),
            "ORANGE": (255, 165, 0),
            "BLACK": (0, 0, 0),
        }

    def _rgb(color_name: str) -> Tuple[int, int, int]:
        key = str(color_name or "").upper()
        rgb = GUI_COLORS.get(key)
        if rgb:
            return tuple(rgb)  # type: ignore[return-value]
        return GUI_COLORS.get("BLACK", (0, 0, 0))

    n = 0
    for c in circles:
        kind = str(c.get("kind") or "settle")
        # No roads in Show overlay
        if kind in ("road", "next_road", "tfr"):
            continue
        iid = c.get("id")
        if iid is None:
            continue
        try:
            center = pos_map.get(int(iid))
        except Exception:
            center = None
        if center is None:
            continue
        try:
            cx, cy = int(center[0]), int(center[1])
        except Exception:
            continue

        color_name = str(c.get("color") or "").strip()
        pid = c.get("player_id")
        if not color_name and pid is not None:
            try:
                color_name = str(
                    color_lut.get(int(pid)) or color_lut.get(str(pid)) or ""
                )
            except Exception:
                color_name = ""
        if kind != "opp" and not color_name:
            color_name = turn_color
        # P1: never trust CS baked radius — matrix (+ optional WP-R5 dist)
        path_d = (
            c.get("map_dist")
            if c.get("map_dist") is not None
            else c.get("dist")
            if c.get("dist") is not None
            else c.get("roads_needed")
        )
        rad = int(
            radius_for_show(
                turn_color, color_name or turn_color, path_distance=path_d
            )
        )
        rgb = _rgb(color_name or turn_color)
        try:
            pygame.draw.circle(screen, rgb, (cx, cy), rad, 2)
            if str(color_name or turn_color).lower() == "white":
                pygame.draw.circle(screen, (0, 0, 0), (cx, cy), rad, 1)
            n += 1
        except Exception:
            pass
    return n


__all__ = [
    "NAV_STEP",
    "NAV_JUMP",
    "TABS",
    "STR_FIELDS",
    "PLAN_FIELDS",
    "ACT_FIELDS",
    "WHY1_FIELDS",
    "WHY_FIELDS",
    "MORE_FIELDS",
    "PLN1_PLACEHOLDER_FIELDS",
    "PLN2_PLACEHOLDER_FIELDS",
    "PLAN_PLACEHOLDER_FIELDS",
    "DigUiState",
    "normalize_dig_tab",
    "parse_cat_list",
    "row_event_index",
    "find_row_index_by_event_index",
    "row_matches_cats",
    "build_hit_list",
    "display_field_at_cursor",
    "last_change_index",
    "is_l2_refresh_row",
    "fields_for_tab",
    "dynamic_plan_text",
    "plan_show_circles_from_row",
    "draw_plan_show_circles",
    "ensure_dig_row_reachability",
    "dig_panel_rect",
    "dig_nav_rects",
    "cat_field_rects",
    "tab_rects",
    "active_turn_player_id",
    "se_display_row_for_cursor",
    "draw_pln1_panel",
    "draw_pln2_table",
    "draw_se_dig_panel",
    "draw_dig_filters_and_nav",
    "handle_dig_key",
    "handle_dig_click",
    "dig_step",
    "mark_step_nav",
    "mark_jump_nav",
    "is_ip_phase",
]
