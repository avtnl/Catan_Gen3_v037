"""Endgame / Statistics aggregation (S7b–S7e).

Pure functions over ``game`` + ledger / deck state — no pygame.

S7b tables:
  - Overview (VP composition per player)
  - Dice histogram 2–12
  - RCards drawn (board production totals Wh…Sh)
  - DCards drawn (deck composition − remaining stack)

S7c tables:
  - Resource Stats per player (TRC In/Loss/Nett + source breakdowns)

S7d–e tables:
  - Activity per player (TrP, TrP&A, RC Use, RC Block, DC In, DC Played)
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Display order matches scoreboard / colonist short labels
RCARD_KEYS: Tuple[str, ...] = ("Wheat", "Ore", "Wood", "Brick", "Sheep")
RCARD_SHORT: Tuple[str, ...] = ("Wh", "O", "Wd", "B", "Sh")

DCARD_KEYS: Tuple[str, ...] = (
    "victory_point",
    "knight",
    "two_free_roads",
    "year_of_plenty",
    "monopoly",
)
DCARD_SHORT: Tuple[str, ...] = ("VP", "Knight", "TFR", "YOP", "Monopoly")

_DCARD_ALIASES = {
    "victory_point": "victory_point",
    "victorypoint": "victory_point",
    "vp": "victory_point",
    "vpoint": "victory_point",
    "knight": "knight",
    "two_free_roads": "two_free_roads",
    "twofreeroads": "two_free_roads",
    "tfr": "two_free_roads",
    "road_building": "two_free_roads",
    "year_of_plenty": "year_of_plenty",
    "yearofplenty": "year_of_plenty",
    "yop": "year_of_plenty",
    "monopoly": "monopoly",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _canonical_dcard_type(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(getattr(raw, "value", raw) or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return None
    return _DCARD_ALIASES.get(text, text if text in DCARD_KEYS else None)


def collect_overview_rows(game: Any, st: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Overview: TVP, S, C, DC, LA, LR per player (sorted by TVP desc)."""
    rows: List[Dict[str, Any]] = []
    players = list(getattr(game, "players", None) or []) if game is not None else []
    if players:
        try:
            from core.victory import vp_breakdown

            for p in players:
                if p is None:
                    continue
                br = dict(vp_breakdown(p))
                pid = br.get("player_id") or getattr(p, "id", None)
                winner = False
                try:
                    w = getattr(game, "winner", None)
                    winner = w is p or (
                        pid is not None
                        and int(pid) == int(getattr(w, "id", -1) or -1)
                    )
                except Exception:
                    winner = False
                rows.append(
                    {
                        "player_id": pid,
                        "color": str(getattr(p, "color", "") or ""),
                        "TVP": _safe_int(br.get("total")),
                        "S": _safe_int(br.get("settlements")),
                        "C": _safe_int(br.get("cities")),
                        "DC": _safe_int(br.get("vp_cards")),
                        "LA": _safe_int(br.get("largest_army")),
                        "LR": _safe_int(br.get("longest_road")),
                        "winner": bool(winner),
                    }
                )
            rows.sort(key=lambda r: (-int(r.get("TVP") or 0), int(r.get("player_id") or 0)))
            return rows
        except Exception:
            rows = []

    state = dict(st or {})
    if not state and game is not None:
        pgui = getattr(game, "post_game_ui", None)
        if isinstance(pgui, Mapping):
            state = dict(pgui)
    standings = list(state.get("standings") or [])
    if not standings and game is not None:
        wr = getattr(game, "win_result", None)
        if isinstance(wr, Mapping):
            standings = list(wr.get("standings") or [])
    winner_id = state.get("winner_id")
    if winner_id is None and game is not None:
        try:
            winner_id = getattr(getattr(game, "winner", None), "id", None)
        except Exception:
            winner_id = None
    for row in standings:
        if not isinstance(row, Mapping):
            continue
        br = dict(row.get("breakdown") or {})
        pid = row.get("player_id")
        rows.append(
            {
                "player_id": pid,
                "color": str(row.get("color") or ""),
                "TVP": _safe_int(row.get("total") or br.get("total")),
                "S": _safe_int(br.get("settlements")),
                "C": _safe_int(br.get("cities")),
                "DC": _safe_int(br.get("vp_cards")),
                "LA": _safe_int(br.get("largest_army")),
                "LR": _safe_int(br.get("longest_road")),
                "winner": pid is not None and int(pid) == int(winner_id if winner_id is not None else -1),
            }
        )
    return rows


def collect_dice_stats(game: Any) -> Dict[str, Any]:
    """Dice histogram for faces 2–12 + total rolls."""
    hist = [0] * 13
    raw = getattr(game, "dice_roll_history", None) if game is not None else None
    if isinstance(raw, (list, tuple)):
        for i in range(min(13, len(raw))):
            hist[i] = _safe_int(raw[i])
    total = sum(hist[2:13])
    if total <= 0 and game is not None:
        rolls = getattr(game, "dice_rolls", None)
        if isinstance(rolls, (list, tuple)):
            for pair in rolls:
                try:
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        s = int(pair[0]) + int(pair[1])
                    else:
                        s = int(pair)
                    if 2 <= s <= 12:
                        hist[s] += 1
                except Exception:
                    continue
            total = sum(hist[2:13])
    return {
        "total": int(total),
        "hist": list(hist),
        "by_face": {n: hist[n] for n in range(2, 13)},
    }


def _ledger_events(game: Any) -> List[Any]:
    if game is None:
        return []
    ledger = getattr(game, "turn_event_ledger", None)
    if ledger is None:
        return []
    events = getattr(ledger, "events", None)
    if isinstance(events, list):
        return list(events)
    return []


def _event_category(ev: Any) -> str:
    cat = getattr(ev, "category", None)
    if cat is None and isinstance(ev, Mapping):
        cat = ev.get("category")
    try:
        from core.turn_event_ledger import _canonical_category

        return str(_canonical_category(cat) or "")
    except Exception:
        return str(cat or "")


def _event_resource_delta(ev: Any) -> Dict[str, int]:
    raw = getattr(ev, "resource_delta", None)
    if raw is None and isinstance(ev, Mapping):
        raw = ev.get("resource_delta")
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, int] = {}
    try:
        from core.turn_event_ledger import _canonical_resource_name

        for k, v in raw.items():
            name = _canonical_resource_name(k)
            try:
                amt = int(v or 0)
            except Exception:
                amt = 0
            if amt:
                out[name] = out.get(name, 0) + amt
    except Exception:
        for k, v in raw.items():
            try:
                out[str(k)] = out.get(str(k), 0) + int(v or 0)
            except Exception:
                continue
    return out


def collect_rcards_drawn(game: Any) -> Dict[str, Any]:
    """Game-level RCards **produced by dice** (ledger ``resource_production`` positives).

    Does not include steal / trade / DCard gains — those belong in Resource Stats (S7c).
    """
    totals = {k: 0 for k in RCARD_KEYS}
    events = _ledger_events(game)
    event_count = 0
    for ev in events:
        if _event_category(ev) != "resource_production":
            continue
        event_count += 1
        for name, amt in _event_resource_delta(ev).items():
            if name in totals and amt > 0:
                totals[name] += int(amt)
    return {
        "by_resource": dict(totals),
        "short": {RCARD_SHORT[i]: totals[RCARD_KEYS[i]] for i in range(len(RCARD_KEYS))},
        "total": int(sum(totals.values())),
        "ledger_events_used": int(event_count),
        "source": "ledger_resource_production" if events else "no_ledger",
    }


def _count_stack_types(stack: Sequence[Any]) -> Counter:
    counts: Counter = Counter()
    for card in list(stack or []):
        key = _canonical_dcard_type(card)
        if key:
            counts[key] += 1
    return counts


def collect_dcards_drawn(game: Any) -> Dict[str, Any]:
    """DCards drawn = full deck composition minus remaining ``dcards_stack``.

    Uses ``LIST_OF_DCARDS`` as the full bank composition (standard base game).
    """
    try:
        from core.constants import LIST_OF_DCARDS

        full_list = list(LIST_OF_DCARDS)
    except Exception:
        full_list = []

    full = Counter()
    for card in full_list:
        key = _canonical_dcard_type(card)
        if key:
            full[key] += 1
    # Ensure all known keys present
    for k in DCARD_KEYS:
        full.setdefault(k, 0)

    stack = getattr(game, "dcards_stack", None) if game is not None else None
    remaining = _count_stack_types(stack if isinstance(stack, (list, tuple)) else [])

    drawn = {k: max(0, int(full.get(k, 0)) - int(remaining.get(k, 0))) for k in DCARD_KEYS}
    return {
        "by_type": dict(drawn),
        "short": {DCARD_SHORT[i]: drawn[DCARD_KEYS[i]] for i in range(len(DCARD_KEYS))},
        "full_deck": {k: int(full.get(k, 0)) for k in DCARD_KEYS},
        "remaining_stack": {k: int(remaining.get(k, 0)) for k in DCARD_KEYS},
        "total_drawn": int(sum(drawn.values())),
        "stack_size": int(len(list(stack or [])) if isinstance(stack, (list, tuple)) else 0),
        "source": "list_of_dcards_minus_stack",
    }


def _event_player_id(ev: Any) -> Optional[int]:
    raw = getattr(ev, "player_id", None)
    if raw is None and isinstance(ev, Mapping):
        raw = ev.get("player_id")
    try:
        if raw is None or raw == "":
            return None
        return int(raw)
    except Exception:
        return None


def _sum_delta_cards(delta: Mapping[str, int]) -> Tuple[int, int]:
    """Return (positive_sum, abs_negative_sum) for resource cards (ignore Gold)."""
    pos = 0
    neg = 0
    for name, amt in dict(delta or {}).items():
        if str(name) == "Gold":
            continue
        try:
            n = int(amt or 0)
        except Exception:
            continue
        if n > 0:
            pos += n
        elif n < 0:
            neg += -n
    return pos, neg


def _empty_resource_bucket() -> Dict[str, int]:
    return {
        "TRC_In": 0,
        "TRC_Loss": 0,
        "TRC_Nett": 0,
        "in_DR": 0,  # production
        "in_Rob": 0,  # steal gained
        "in_DC": 0,  # dcard gained
        "in_Tr": 0,  # TwP + TwB gained
        "loss_DR7": 0,  # discard
        "loss_Rob": 0,  # steal lost
        "loss_DC": 0,  # dcard lost (e.g. monopoly victim)
        "loss_Tr": 0,  # TwP + TwB given
        "loss_Buy": 0,  # builds/buys (not shown as own column; in TRC_Loss)
    }


# Categories that never moved cards in hand (blocked production) — exclude from TRC totals.
_EXCLUDE_FROM_TRC_TOTALS = frozenset({"resource_production_robber"})


def collect_resource_rows(
    game: Any,
    *,
    overview_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    post_game_state: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """S7c: per-player Resource Stats from the full-game turn ledger.

    Columns (plan §4.3):
      TVP | TRC In | TRC Loss | TRC Nett | DR | Rob | DC | Tr | DR=7 | Rob | DC | TR

    Definitions:
      - TRC In / Loss: sum of positive / abs(negative) resource deltas for that
        player across ledger categories **except** ``resource_production_robber``
        (blocked income never entered the hand).
      - DR / Rob / DC / Tr (In): positives in production / steal / dcard / TwP+TwB.
      - DR=7 / Rob / DC / Tr (Loss): abs(negatives) in discard / steal / dcard / TwP+TwB.
      - Build costs (``buy``) count toward TRC Loss only (no separate column).
    """
    overview = list(overview_rows) if overview_rows is not None else collect_overview_rows(
        game, post_game_state
    )
    # Seed buckets for known players (stable order from overview)
    by_pid: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for row in overview:
        try:
            pid = int(row.get("player_id"))
        except Exception:
            continue
        if pid in by_pid:
            continue
        order.append(pid)
        bucket = _empty_resource_bucket()
        bucket["player_id"] = pid
        bucket["color"] = str(row.get("color") or "")
        bucket["TVP"] = _safe_int(row.get("TVP"))
        bucket["winner"] = bool(row.get("winner"))
        by_pid[pid] = bucket

    # Also include any player_id that only appears in ledger events
    events = _ledger_events(game)
    for ev in events:
        pid = _event_player_id(ev)
        if pid is None or pid in by_pid:
            continue
        order.append(pid)
        bucket = _empty_resource_bucket()
        bucket["player_id"] = pid
        bucket["color"] = ""
        bucket["TVP"] = 0
        bucket["winner"] = False
        by_pid[pid] = bucket

    for ev in events:
        pid = _event_player_id(ev)
        if pid is None or pid not in by_pid:
            continue
        cat = _event_category(ev)
        delta = _event_resource_delta(ev)
        pos, neg = _sum_delta_cards(delta)
        b = by_pid[pid]

        if cat not in _EXCLUDE_FROM_TRC_TOTALS:
            b["TRC_In"] += pos
            b["TRC_Loss"] += neg

        if cat == "resource_production":
            b["in_DR"] += pos
        elif cat == "steal":
            b["in_Rob"] += pos
            b["loss_Rob"] += neg
        elif cat == "dcard":
            b["in_DC"] += pos
            b["loss_DC"] += neg
        elif cat in ("TwP", "TwB"):
            b["in_Tr"] += pos
            b["loss_Tr"] += neg
        elif cat == "discard":
            b["loss_DR7"] += neg
        elif cat == "buy":
            b["loss_Buy"] += neg
        # resource_production_robber intentionally ignored for TRC + breakdowns

    rows: List[Dict[str, Any]] = []
    for pid in order:
        b = by_pid[pid]
        b["TRC_Nett"] = int(b["TRC_In"]) - int(b["TRC_Loss"])
        rows.append(dict(b))

    # Sort like overview: TVP desc, then player_id
    rows.sort(key=lambda r: (-int(r.get("TVP") or 0), int(r.get("player_id") or 0)))
    return rows


def bump_player_stat(player: Any, key: str, amount: int = 1) -> int:
    """Increment a lifetime Activity counter on ``player`` (S7e hooks)."""
    if player is None:
        return 0
    try:
        cur = int(getattr(player, key, 0) or 0)
    except Exception:
        cur = 0
    new = cur + int(amount or 0)
    try:
        setattr(player, key, new)
    except Exception:
        return cur
    return new


def count_dc_played(player: Any, *, include_vp: bool = False) -> int:
    """Played/revealed DCards from ``dcard_summary`` col3 (default excludes VP)."""
    total = 0
    try:
        for row in list(getattr(player, "dcard_summary", None) or []):
            if not row:
                continue
            name = str(row[0] or "").strip().lower()
            if not include_vp and name in ("victory_point", "victorypoint", "vp"):
                continue
            try:
                total += max(0, int(row[3] if len(row) > 3 else 0))
            except Exception:
                continue
    except Exception:
        return 0
    return int(total)


def _event_message(ev: Any) -> str:
    msg = getattr(ev, "message", None)
    if msg is None and isinstance(ev, Mapping):
        msg = ev.get("message")
    return str(msg or "")


def _event_type(ev: Any) -> str:
    t = getattr(ev, "event_type", None)
    if t is None and isinstance(ev, Mapping):
        t = ev.get("event_type")
    return str(t or "")


def _event_metadata(ev: Any) -> Dict[str, Any]:
    m = getattr(ev, "metadata", None)
    if m is None and isinstance(ev, Mapping):
        m = ev.get("metadata")
    return dict(m) if isinstance(m, Mapping) else {}


def collect_activity_rows(
    game: Any,
    *,
    overview_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    post_game_state: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """S7d–e Activity: TVP, TrP, TrP&A, RC Use, RC Block, DC In, DC Played.

    Prefer lifetime counters (S7e) when present; fill gaps from ledger / summary.
    """
    overview = list(overview_rows) if overview_rows is not None else collect_overview_rows(
        game, post_game_state
    )
    players_by_id: Dict[int, Any] = {}
    if game is not None:
        for p in list(getattr(game, "players", None) or []):
            if p is None:
                continue
            try:
                players_by_id[int(getattr(p, "id", 0) or 0)] = p
            except Exception:
                continue

    # Pre-aggregate ledger fallbacks per player
    ledger_use: Dict[int, int] = {}
    ledger_block: Dict[int, int] = {}
    ledger_trp_a: Dict[int, int] = {}
    ledger_dc_buy: Dict[int, int] = {}
    for ev in _ledger_events(game):
        pid = _event_player_id(ev)
        if pid is None:
            continue
        cat = _event_category(ev)
        pos, neg = _sum_delta_cards(_event_resource_delta(ev))
        if cat == "buy":
            ledger_use[pid] = ledger_use.get(pid, 0) + neg
        elif cat == "dcard":
            meta = _event_metadata(ev)
            msg = _event_message(ev).lower()
            # DCard *buy* cost (not monopoly/YOP swings)
            if meta.get("card_name") is not None or "bought" in msg:
                ledger_use[pid] = ledger_use.get(pid, 0) + neg
                if meta.get("card_name") is not None or "bought a development" in msg:
                    ledger_dc_buy[pid] = ledger_dc_buy.get(pid, 0) + 1
        elif cat == "resource_production_robber":
            ledger_block[pid] = ledger_block.get(pid, 0) + neg
        elif cat == "TwP":
            # One ledger event per participant per accepted deal
            et = _event_type(ev).lower()
            if "accept" in et or pos or neg:
                ledger_trp_a[pid] = ledger_trp_a.get(pid, 0) + 1

    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for row in overview:
        try:
            pid = int(row.get("player_id"))
        except Exception:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        p = players_by_id.get(pid)

        trp_c = None
        trp_a_c = None
        dc_in_c = None
        if p is not None:
            try:
                trp_c = int(getattr(p, "stats_twp_proposed", 0) or 0)
            except Exception:
                trp_c = 0
            try:
                trp_a_c = int(getattr(p, "stats_twp_accepted", 0) or 0)
            except Exception:
                trp_a_c = 0
            try:
                dc_in_c = int(getattr(p, "stats_dcards_bought", 0) or 0)
            except Exception:
                dc_in_c = 0

        # Prefer counters; fall back to ledger for accepted / dc bought
        trp = trp_c if trp_c is not None else 0
        trp_a = trp_a_c if (trp_a_c is not None and trp_a_c > 0) else int(ledger_trp_a.get(pid, 0))
        if trp_a_c is not None and trp_a_c > 0:
            trp_a = trp_a_c
        dc_in = dc_in_c if (dc_in_c is not None and dc_in_c > 0) else int(ledger_dc_buy.get(pid, 0))
        if dc_in_c is not None and dc_in_c > 0:
            dc_in = dc_in_c

        rows.append(
            {
                "player_id": pid,
                "color": str(row.get("color") or (getattr(p, "color", "") if p else "")),
                "TVP": _safe_int(row.get("TVP")),
                "winner": bool(row.get("winner")),
                "TrP": int(trp),
                "TrP_A": int(trp_a),
                "RC_Use": int(ledger_use.get(pid, 0)),
                "RC_Block": int(ledger_block.get(pid, 0)),
                "DC_In": int(dc_in),
                "DC_Played": int(count_dc_played(p) if p is not None else 0),
                "sources": {
                    "TrP": "counter",
                    "TrP_A": "counter" if (trp_a_c or 0) > 0 else "ledger",
                    "RC_Use": "ledger",
                    "RC_Block": "ledger",
                    "DC_In": "counter" if (dc_in_c or 0) > 0 else "ledger",
                    "DC_Played": "dcard_summary",
                },
            }
        )

    rows.sort(key=lambda r: (-int(r.get("TVP") or 0), int(r.get("player_id") or 0)))
    return rows


def collect_endgame_statistics(
    game: Any,
    *,
    post_game_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate S7a–S7e Statistics tables into one snapshot dict."""
    st = post_game_state
    if st is None and game is not None:
        pgui = getattr(game, "post_game_ui", None)
        if isinstance(pgui, Mapping):
            st = pgui
    overview = collect_overview_rows(game, st)
    dice = collect_dice_stats(game)
    rcards = collect_rcards_drawn(game)
    dcards = collect_dcards_drawn(game)
    resource_rows = collect_resource_rows(
        game, overview_rows=overview, post_game_state=st
    )
    activity_rows = collect_activity_rows(
        game, overview_rows=overview, post_game_state=st
    )
    events = _ledger_events(game)
    return {
        "overview_rows": overview,
        "activity_rows": activity_rows,
        "dice": dice,
        "rcards_drawn": rcards,
        "dcards_drawn": dcards,
        "resource_rows": resource_rows,
        "meta": {
            "s7b": True,
            "s7c": True,
            "s7d": True,
            "s7e": True,
            "ledger_event_count": len(events),
            "player_count": len(overview),
            "resource_source": "ledger" if events else "no_ledger",
        },
    }
