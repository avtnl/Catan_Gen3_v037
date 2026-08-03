"""
Turn event ledger for Catan execution-phase bookkeeping.

The ledger is the source of truth for current-turn deltas and narrative events.
Legacy/player-facing turn_details_* vectors are kept as compatibility mirrors
for the scoreboard and older code paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional


RESOURCE_ORDER: List[str] = ["Wheat", "Ore", "Wood", "Brick", "Sheep", "Gold"]

CATEGORY_TO_LEGACY_ATTR: Dict[str, str] = {
    "resource_production": "turn_details_resource_production",
    "resource_production_robber": "turn_details_resource_production_robber",
    "buy": "turn_details_buy",
    "steal": "turn_details_steal",
    "discard": "turn_details_discard",
    "TwP": "turn_details_TwP",
    "twp": "turn_details_TwP",
    "TwB": "turn_details_TwB",
    "twb": "turn_details_TwB",
    "dcard": "turn_details_dcard",
}

DISPLAY_CATEGORY_ORDER: List[tuple[str, str]] = [
    ("RP", "resource_production"),
    ("RP Corr", "resource_production_robber"),
    ("Buy", "buy"),
    ("Steal", "steal"),
    ("Discard", "discard"),
    ("TwP", "TwP"),
    ("TwB", "TwB"),
    ("Dcard", "dcard"),
]


@dataclass
class TurnEvent:
    """One structured event emitted by a real game action."""

    index: int
    round_num: int
    turn: int
    player_id: Optional[int]
    event_type: str
    category: Optional[str] = None
    target_player_id: Optional[int] = None
    resource_delta: Dict[str, int] = field(default_factory=dict)
    public: bool = True
    source: str = ""
    reason: str = ""
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TurnEvent":
        resource_delta = data.get("resource_delta", {})
        if not isinstance(resource_delta, Mapping):
            resource_delta = {}
        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        return cls(
            index=int(data.get("index", 0) or 0),
            round_num=int(data.get("round_num", data.get("round", 0)) or 0),
            turn=int(data.get("turn", 0) or 0),
            player_id=_safe_int_or_none(data.get("player_id")),
            event_type=str(data.get("event_type", "event")),
            category=data.get("category"),
            target_player_id=_safe_int_or_none(data.get("target_player_id")),
            resource_delta={_canonical_resource_name(k): int(v or 0) for k, v in resource_delta.items()},
            public=bool(data.get("public", True)),
            source=str(data.get("source", "")),
            reason=str(data.get("reason", "")),
            message=str(data.get("message", "")),
            metadata=dict(metadata),
        )


class TurnEventLedger:
    """Collects structured events and produces turn-detail summaries."""

    def __init__(self, resource_order: Optional[Iterable[str]] = None) -> None:
        self.resource_order: List[str] = list(resource_order or RESOURCE_ORDER)
        self.events: List[TurnEvent] = []
        self.current_round: Optional[int] = None
        self.current_turn: Optional[int] = None
        self._next_index = 1

    def start_turn(self, round_num: int, turn: int) -> None:
        """Set the active turn. Historical events are retained."""
        self.current_round = int(round_num)
        self.current_turn = int(turn)

    def add_event(
        self,
        *,
        round_num: Optional[int] = None,
        turn: Optional[int] = None,
        player_id: Optional[int] = None,
        event_type: str,
        category: Optional[str] = None,
        target_player_id: Optional[int] = None,
        resource_delta: Optional[Mapping[Any, Any]] = None,
        public: bool = True,
        source: str = "",
        reason: str = "",
        message: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> TurnEvent:
        ev = TurnEvent(
            index=self._next_index,
            round_num=int(round_num if round_num is not None else (self.current_round or 0)),
            turn=int(turn if turn is not None else (self.current_turn or 0)),
            player_id=_safe_int_or_none(player_id),
            event_type=str(event_type or "event"),
            category=_canonical_category(category),
            target_player_id=_safe_int_or_none(target_player_id),
            resource_delta=_normalize_delta(resource_delta or {}),
            public=bool(public),
            source=str(source or ""),
            reason=str(reason or ""),
            message=str(message or ""),
            metadata=dict(metadata or {}),
        )
        self._next_index += 1
        self.events.append(ev)
        return ev

    def events_for_turn(
        self,
        round_num: Optional[int] = None,
        turn: Optional[int] = None,
    ) -> List[TurnEvent]:
        r = self.current_round if round_num is None else int(round_num)
        t = self.current_turn if turn is None else int(turn)
        return [ev for ev in self.events if ev.round_num == r and ev.turn == t]

    def resource_delta_vector(
        self,
        player_id: int,
        category: str,
        *,
        round_num: Optional[int] = None,
        turn: Optional[int] = None,
    ) -> List[int]:
        cat = _canonical_category(category)
        total: Dict[str, int] = {name: 0 for name in self.resource_order}
        for ev in self.events_for_turn(round_num, turn):
            if ev.player_id != int(player_id):
                continue
            if _canonical_category(ev.category) != cat:
                continue
            for name, amount in ev.resource_delta.items():
                cname = _canonical_resource_name(name)
                total[cname] = total.get(cname, 0) + int(amount or 0)
        return [int(total.get(name, 0)) for name in self.resource_order]

    def rows_for_player(
        self,
        player_id: int,
        *,
        round_num: Optional[int] = None,
        turn: Optional[int] = None,
    ) -> List[tuple[str, List[int]]]:
        rows: List[tuple[str, List[int]]] = []
        for label, category in DISPLAY_CATEGORY_ORDER:
            vec = self.resource_delta_vector(player_id, category, round_num=round_num, turn=turn)
            if any(int(x or 0) != 0 for x in vec):
                rows.append((label, vec))
        return rows

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_order": list(self.resource_order),
            "current_round": self.current_round,
            "current_turn": self.current_turn,
            "next_index": self._next_index,
            "events": [ev.to_dict() for ev in self.events],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TurnEventLedger":
        ledger = cls(resource_order=data.get("resource_order") or RESOURCE_ORDER)
        ledger.current_round = _safe_int_or_none(data.get("current_round"))
        ledger.current_turn = _safe_int_or_none(data.get("current_turn"))
        raw_events = data.get("events", [])
        if isinstance(raw_events, list):
            for item in raw_events:
                if isinstance(item, Mapping):
                    ledger.events.append(TurnEvent.from_dict(item))
        try:
            ledger._next_index = int(data.get("next_index", 0) or 0)
        except Exception:
            ledger._next_index = 0
        if ledger._next_index <= 0:
            ledger._next_index = max([ev.index for ev in ledger.events] or [0]) + 1
        return ledger


def _safe_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _canonical_category(category: Optional[str]) -> Optional[str]:
    if category is None:
        return None
    text = str(category).strip()
    aliases = {
        "rp": "resource_production",
        "resource_production": "resource_production",
        "resource production": "resource_production",
        "rp corr": "resource_production_robber",
        "rp_corr": "resource_production_robber",
        "resource_production_robber": "resource_production_robber",
        "robber": "resource_production_robber",
        "buy": "buy",
        "steal": "steal",
        "discard": "discard",
        "twp": "TwP",
        "TwP": "TwP",
        "twb": "TwB",
        "TwB": "TwB",
        "dcard": "dcard",
        "development_card": "dcard",
    }
    return aliases.get(text, aliases.get(text.lower(), text))


def _canonical_resource_name(resource: Any) -> str:
    value = getattr(resource, "value", None)
    if value is not None:
        resource = value
    name = getattr(resource, "name", None)
    if name is not None and not isinstance(resource, str):
        resource = name
    text = str(resource).strip()
    aliases = {
        "grain": "Wheat",
        "wheat": "Wheat",
        "ore": "Ore",
        "wood": "Wood",
        "lumber": "Wood",
        "brick": "Brick",
        "sheep": "Sheep",
        "wool": "Sheep",
        "gold": "Gold",
    }
    return aliases.get(text.lower(), text[:1].upper() + text[1:])


def _normalize_delta(raw: Mapping[Any, Any]) -> Dict[str, int]:
    delta: Dict[str, int] = {}
    for key, value in raw.items():
        name = _canonical_resource_name(key)
        try:
            amount = int(value or 0)
        except Exception:
            amount = 0
        if amount:
            delta[name] = delta.get(name, 0) + amount
    return delta
