"""WP1: board residual for Victory-Way tags / req_* / MORE owned.

Computes **definition** tags (142-way row) and **residual** tags/req counts from
live player progress (S/C upgrades, specials held, unplayed DCards/TFR).

Does not choose ways (board-fit filter is WP2). Pure helpers for CS + dig +
direction enrichment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RESOURCE_NAMES = ("Wheat", "Ore", "Wood", "Brick", "Sheep")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_way_id(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        w = int(float(value))
        return w if w > 0 else None
    except Exception:
        return None


def dcard_summary_rows(player: Any) -> List[List[Any]]:
    rows: List[List[Any]] = []
    try:
        for row in list(getattr(player, "dcard_summary", []) or []):
            if not row:
                continue
            r = list(row)
            while len(r) < 4:
                r.append(0)
            rows.append(r)
    except Exception:
        pass
    return rows


def dcard_unplayed(player: Any, card_type: str) -> int:
    """new + playable counts for one DCard type."""
    want = str(card_type or "").strip().lower()
    total = 0
    for row in dcard_summary_rows(player):
        name = str(row[0] or "").strip().lower()
        if name != want and name.replace(" ", "_") != want:
            continue
        total += max(0, _safe_int(row[1], 0)) + max(0, _safe_int(row[2], 0))
    if total > 0:
        return total
    # Fallback: development_cards list (playable/new not distinguished)
    try:
        for c in list(getattr(player, "development_cards", []) or []):
            if str(c or "").strip().lower() in (want, want.replace("_", " ")):
                total += 1
    except Exception:
        pass
    return total


def dcard_ever_count(player: Any) -> int:
    """All DCards ever obtained (new+playable+played across types)."""
    total = 0
    for row in dcard_summary_rows(player):
        total += (
            max(0, _safe_int(row[1], 0))
            + max(0, _safe_int(row[2], 0))
            + max(0, _safe_int(row[3], 0))
        )
    if total > 0:
        return total
    try:
        return max(0, len(list(getattr(player, "development_cards", []) or [])))
    except Exception:
        return 0


def unplayed_vp_cards(player: Any) -> int:
    return dcard_unplayed(player, "victory_point")


def unplayed_tfr(player: Any) -> int:
    n = dcard_unplayed(player, "two_free_roads")
    if n:
        return n
    return dcard_unplayed(player, "road_building")


def unplayed_knights(player: Any) -> int:
    return dcard_unplayed(player, "knight")


def holds_lr(player: Any) -> bool:
    return bool(
        getattr(player, "longest_route_tf", False)
        or getattr(player, "longest_road_tf", False)
    )


def holds_la(player: Any) -> bool:
    return bool(
        getattr(player, "largest_army_tf", False)
        or getattr(player, "biggest_army_tf", False)
    )


def army_size(player: Any) -> int:
    return max(0, _safe_int(getattr(player, "size_largest_army", 0), 0))


def settlement_city_counts(player: Any) -> Tuple[int, int]:
    try:
        cities = len(list(getattr(player, "cities", []) or []))
    except Exception:
        cities = 0
    try:
        settles = len(list(getattr(player, "settlements", []) or []))
    except Exception:
        settles = 0
    # Some states keep cities also listed as settlements — prefer pure S
    try:
        city_ids = {int(x) for x in list(getattr(player, "cities", []) or [])}
        settles = len(
            [
                int(x)
                for x in list(getattr(player, "settlements", []) or [])
                if int(x) not in city_ids
            ]
        )
    except Exception:
        pass
    return settles, cities


def load_way_requirement(way_id: Optional[int]) -> Any:
    wid = _safe_way_id(way_id)
    if wid is None:
        return None
    try:
        from core.strategy_timing import load_strategy_requirements

        for strategy in load_strategy_requirements() or []:
            if _safe_int(getattr(strategy, "way_id", -1), -1) == wid:
                return strategy
    except Exception:
        pass
    return None


def way_def_tags(strategy: Any) -> List[str]:
    """Absolute 142-way composition from CSV (definition, not residual).

    Uses ``Cities`` / ``Settlements`` / ``Victory_Point_Cards`` (+ LR/LA),
    **not** ``New_Settlements_To_Build``. Dig STR Tags show this list in v4
    form: ``LA · LR · n×C · n×S · n×VP``.
    """
    if strategy is None:
        return []
    need_lr = bool(getattr(strategy, "longest_road", False))
    need_la = bool(
        getattr(strategy, "biggest_army", False)
        or getattr(strategy, "largest_army", False)
    )
    # Prefer Cities/Settlements columns (table definition)
    c = _safe_int(getattr(strategy, "cities", None), -1)
    if c < 0:
        c = _safe_int(getattr(strategy, "city_upgrades", 0), 0)
    s = _safe_int(getattr(strategy, "settlements", None), -1)
    if s < 0:
        # Do not fall back to new_settlements_to_build for Dig Tags
        s = 0
    vp = _safe_int(getattr(strategy, "victory_point_cards", 0), 0)
    atoms: List[str] = []
    if need_la:
        atoms.append("LA")
    if need_lr:
        atoms.append("LR")
    bit = _format_nx(c, "C")
    if bit:
        atoms.append(bit)
    bit = _format_nx(s, "S")
    if bit:
        atoms.append(bit)
    bit = _format_nx(vp, "VP")
    if bit:
        atoms.append(bit)
    return atoms


def _format_count(n: int, singular: str, plural: str) -> str:
    """Legacy English phrase (``1 settlement`` / ``4 cities``)."""
    if n <= 0:
        return ""
    if n == 1:
        return f"1 {singular}"
    return f"{n} {plural}"


def _format_nx(n: int, letter: str) -> str:
    """v4 tag atom: ``4×C``, ``1×S``, ``1×VP``."""
    if n <= 0:
        return ""
    return f"{int(n)}×{letter}"


def format_residual_tags_v4(
    *,
    need_la: bool = False,
    need_lr: bool = False,
    req_cities: int = 0,
    req_settles: int = 0,
    rem_vp: int = 0,
    req_dcards: int = 0,
    sep: str = " · ",
) -> str:
    """Canonical residual tag string: LA → LR → C → S → VP (then optional DC)."""
    bits: List[str] = []
    if need_la:
        bits.append("LA")
    if need_lr:
        bits.append("LR")
    c = _format_nx(int(req_cities or 0), "C")
    if c:
        bits.append(c)
    s = _format_nx(int(req_settles or 0), "S")
    if s:
        bits.append(s)
    vp = _format_nx(int(rem_vp or 0), "VP")
    if vp:
        bits.append(vp)
    # DC only when not already explained by VP/LA path
    if int(req_dcards or 0) > 0 and int(rem_vp or 0) == 0 and not need_la:
        dc = _format_nx(int(req_dcards or 0), "DC")
        if dc:
            bits.append(dc)
    return sep.join(bits)


def compute_way_residual(
    way_id: Any,
    player: Any,
    *,
    preferred: Optional[Mapping[str, Any]] = None,
    board: Any = None,
) -> Dict[str, Any]:
    """Board residual for one way + player.

    Returns keys used by CS / dig:
      way_def_tags, way_tags (residual), req_cities/settles/roads/dcards,
      way_lr, way_la (table flags), need_lr, need_la (still pursuing),
      owned_display, remaining_vp_cards, tfr_credit_roads
    """
    preferred = preferred if isinstance(preferred, Mapping) else {}
    wid = _safe_way_id(way_id) or _safe_way_id(
        preferred.get("preferred_way_id") or preferred.get("way_id")
    )
    strategy = load_way_requirement(wid)
    settles, cities = settlement_city_counts(player)
    n_s, n_c = settles, cities
    total_buildings = n_s + n_c

    def_tags = way_def_tags(strategy)

    # Defaults from preferred.remaining when present
    rem_map = preferred.get("remaining") if isinstance(preferred.get("remaining"), Mapping) else {}

    req_cities = None
    req_settles = None
    req_roads = None
    req_dcards = None
    way_lr = bool(preferred.get("longest_road") or preferred.get("way_lr"))
    way_la = bool(
        preferred.get("largest_army")
        or preferred.get("biggest_army")
        or preferred.get("way_la")
    )
    table_vp = 0

    if strategy is not None:
        way_lr = bool(getattr(strategy, "longest_road", False))
        way_la = bool(
            getattr(strategy, "biggest_army", False)
            or getattr(strategy, "largest_army", False)
        )
        table_vp = _safe_int(getattr(strategy, "victory_point_cards", 0), 0)

    # Façade WP2: Player One residual + min-road cover (hand=no).
    # TFR credit applied via façade helper *after* preferred.remaining overrides.
    tfr_n = unplayed_tfr(player)
    tfr_credit = 2 * tfr_n
    try:
        from core.way_resource_need import apply_tfr_road_credit, way_resource_need

        game = None
        if isinstance(preferred, Mapping):
            game = preferred.get("_game")
        if game is None and board is not None:
            game = type("G", (), {"board": board, "players": [player]})()
        need_bag = way_resource_need(
            game,
            player,
            wid,
            consider_hand=False,
            use_min_road_cover=True,
            apply_tfr_credit=False,
            board=board,
        )
        req_cities = int(need_bag.req_cities)
        req_settles = int(need_bag.req_settles)
        req_roads = int(need_bag.req_roads)
        req_dcards = int(need_bag.req_dcards)
        way_lr = bool(need_bag.components.longest_road or way_lr)
        way_la = bool(need_bag.components.largest_army or way_la)
        if need_bag.components.victory_point_cards:
            table_vp = int(need_bag.components.victory_point_cards)
    except Exception:
        # Fall back to table absolute − crude board counts
        if strategy is not None:
            c_need = _safe_int(
                getattr(strategy, "cities", 0) or getattr(strategy, "city_upgrades", 0), 0
            )
            s_need = _safe_int(getattr(strategy, "settlements", 0), 0)
            target_build = max(
                _safe_int(getattr(strategy, "buildings", 0), 0),
                c_need + s_need,
            )
            req_cities = max(0, c_need - n_c)
            req_settles = max(0, target_build - total_buildings)
            req_roads = max(
                0,
                _safe_int(getattr(strategy, "roads_to_build", 0), 0)
                - len(list(getattr(player, "roads", []) or [])),
            )
            req_dcards = max(
                0,
                _safe_int(getattr(strategy, "development_cards_to_buy", 0), 0)
                - dcard_ever_count(player),
            )
        else:
            req_cities = 0
            req_settles = 0
            req_roads = 0
            req_dcards = 0

    # Prefer preferred.remaining overrides when explicit
    if rem_map:
        if rem_map.get("cities") is not None:
            req_cities = max(0, _safe_int(rem_map.get("cities"), req_cities or 0))
        if rem_map.get("new_settlements") is not None:
            req_settles = max(
                0, _safe_int(rem_map.get("new_settlements"), req_settles or 0)
            )
        if rem_map.get("roads") is not None:
            req_roads = max(0, _safe_int(rem_map.get("roads"), req_roads or 0))
        if rem_map.get("development_cards") is not None:
            req_dcards = max(
                0, _safe_int(rem_map.get("development_cards"), req_dcards or 0)
            )

    req_cities = max(0, _safe_int(req_cities, 0))
    req_settles = max(0, _safe_int(req_settles, 0))
    req_roads = max(0, _safe_int(req_roads, 0))
    req_dcards = max(0, _safe_int(req_dcards, 0))

    # WP2: TFR credit from façade helper (single formula) after overrides
    try:
        from core.way_resource_need import apply_tfr_road_credit as _tfr

        req_roads, tfr_meta = _tfr(req_roads, player, longest_road=bool(way_lr))
        tfr_credit = int(tfr_meta.get("tfr_credit_roads") or tfr_credit)
        tfr_n = int(tfr_meta.get("tfr_unplayed") or tfr_n)
    except Exception:
        if way_lr or req_roads > 0:
            req_roads = max(0, req_roads - tfr_credit)

    # VP cards residual
    held_vp = unplayed_vp_cards(player)
    rem_vp = max(0, table_vp - held_vp) if table_vp else 0
    # Prefer preferred if it already accounts for VP
    if preferred.get("remaining_vp_cards") is not None:
        rem_vp = max(0, _safe_int(preferred.get("remaining_vp_cards"), rem_vp))

    # LA residual DC (knights still needed to claim)
    need_la = bool(way_la and not holds_la(player))
    need_lr = bool(way_lr and not holds_lr(player))
    knights_banked = unplayed_knights(player)
    army = army_size(player)
    if need_la:
        # Claim bar 3 (or hold +1 over max opp — keep simple claim bar for residual)
        knights_needed = max(0, 3 - army)
        rem_knight_buys = max(0, knights_needed - knights_banked)
        try:
            from core.strategy_timing import (
                EXPECTED_DEV_CARD_BUYS_PER_KNIGHT,
                EXPECTED_DEV_CARD_BUYS_PER_VP_CARD,
                expected_development_card_buys,
            )

            knight_path = rem_knight_buys * int(EXPECTED_DEV_CARD_BUYS_PER_KNIGHT)
            # Statistical knight buys (2 per knight still needed)
            if rem_knight_buys and not knight_path:
                knight_path = rem_knight_buys * 2
            vp_path = 0
            if rem_vp > 0:
                vp_path = int(
                    expected_development_card_buys(
                        victory_point_cards=int(rem_vp),
                        largest_army=False,
                        listed_development_cards=0,
                    )
                )
            # WP-D: Dig/offline Need = min(knight path, VP path) when both apply
            # e.g. LA+2VP joint 10 → min(6, 10) = 6 while still chasing army
            paths = [p for p in (knight_path, vp_path) if p and p > 0]
            if paths:
                tightened = min(paths)
                if req_dcards > 0:
                    req_dcards = min(int(req_dcards), tightened)
                else:
                    req_dcards = tightened
            else:
                req_dcards = max(req_dcards, rem_knight_buys)
        except Exception:
            req_dcards = max(req_dcards, rem_knight_buys)
    else:
        rem_knight_buys = 0
        # LA already held: do not keep joint LA+VP CSV buy count (e.g. 10).
        # Re-estimate expected buys from remaining VP cards only (1 VP ≈ 5 buys).
        if rem_vp > 0:
            try:
                from core.strategy_timing import expected_development_card_buys

                vp_buys = int(
                    expected_development_card_buys(
                        victory_point_cards=int(rem_vp),
                        largest_army=False,
                        listed_development_cards=0,
                    )
                )
                # Prefer the tighter VP-only estimate over stale joint residual
                req_dcards = min(int(req_dcards or vp_buys), vp_buys) if req_dcards else vp_buys
            except Exception:
                req_dcards = min(int(req_dcards or rem_vp * 5), int(rem_vp) * 5)
        elif not need_la and rem_vp <= 0:
            # No LA chase and no VP left — drop leftover CSV DC mass
            req_dcards = min(int(req_dcards or 0), rem_knight_buys)

    # Residual tags (v4): LA → LR → n×C → n×S → n×VP
    # Order locked; dig STR/PLN1 share this list via ``way_tags``.
    tag_str = format_residual_tags_v4(
        need_la=need_la,
        need_lr=need_lr,
        req_cities=req_cities,
        req_settles=req_settles,
        rem_vp=rem_vp,
        req_dcards=req_dcards,
        sep=" · ",
    )
    res_tags: List[str] = [tag_str] if tag_str else []
    # Also keep atomic list for callers that join with ";"
    atomic: List[str] = []
    if need_la:
        atomic.append("LA")
    if need_lr:
        atomic.append("LR")
    for letter, n in (("C", req_cities), ("S", req_settles), ("VP", rem_vp)):
        bit = _format_nx(int(n or 0), letter)
        if bit:
            atomic.append(bit)
    if req_dcards > 0 and rem_vp == 0 and not need_la:
        bit = _format_nx(int(req_dcards or 0), "DC")
        if bit:
            atomic.append(bit)
    if atomic:
        res_tags = atomic

    # Owned display for MORE (no R=x piece count)
    owned_bits: List[str] = []
    if holds_la(player):
        owned_bits.append("LA")
    if holds_lr(player):
        owned_bits.append("LR")
    if unplayed_knights(player):
        owned_bits.append(f"K×{unplayed_knights(player)}")
    if tfr_n:
        owned_bits.append(f"TFR×{tfr_n}" if tfr_n > 1 else "TFR")
    yop = dcard_unplayed(player, "year_of_plenty")
    if yop:
        owned_bits.append(f"YOP×{yop}" if yop > 1 else "YOP")
    mono = dcard_unplayed(player, "monopoly")
    if mono:
        owned_bits.append(f"M×{mono}" if mono > 1 else "M")
    if held_vp:
        owned_bits.append(f"VP×{held_vp}" if held_vp > 1 else "VP")
    # Structure counts still useful without roads-as-R-in-owned
    if n_s:
        owned_bits.append(f"S={n_s}")
    if n_c:
        owned_bits.append(f"C={n_c}")

    return {
        "way_id": wid,
        "way_def_tags": def_tags,
        "way_tags": res_tags,
        "req_cities": req_cities,
        "req_settles": req_settles,
        "req_roads": req_roads,
        "req_dcards": req_dcards,
        "way_lr": way_lr,
        "way_la": way_la,
        "need_lr": need_lr,
        "need_la": need_la,
        "remaining_vp_cards": rem_vp,
        "tfr_credit_roads": tfr_credit,
        "tfr_unplayed": tfr_n,
        "owned_display": ";".join(owned_bits) if owned_bits else "",
        "settlements_owned": n_s,
        "cities_owned": n_c,
        "unplayed_vp": held_vp,
        "rem_knight_buys": rem_knight_buys,
    }


def format_tags_join(tags: Sequence[Any]) -> str:
    """Join residual tags for Dig/CS. Prefer middle-dot when already v4 atoms."""
    bits = [str(t) for t in tags if t not in (None, "")]
    if not bits:
        return ""
    # Single preformatted string
    if len(bits) == 1 and ("·" in bits[0] or "×" in bits[0]):
        return bits[0]
    if any("×" in b or b in ("LA", "LR") for b in bits):
        return " · ".join(bits)
    return ";".join(bits)


__all__ = [
    "compute_way_residual",
    "way_def_tags",
    "format_residual_tags_v4",
    "load_way_requirement",
    "unplayed_vp_cards",
    "unplayed_tfr",
    "unplayed_knights",
    "dcard_ever_count",
    "holds_la",
    "holds_lr",
    "format_tags_join",
]
