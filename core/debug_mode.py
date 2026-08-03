"""CHECK_MODE gates for fair-play vs dig-in UI.

Core game state always keeps full truth; these helpers only decide what the
GUI may reveal.
"""

from __future__ import annotations

from typing import Any, Optional


def is_check_mode() -> bool:
    """Return True when full dig-in UI is enabled."""
    try:
        from core.constants import CHECK_MODE

        return bool(CHECK_MODE)
    except Exception:
        return False


def is_human_player(player: Any) -> bool:
    """Best-effort human seat check."""
    if player is None:
        return False
    try:
        if bool(getattr(player, "is_human", False)):
            return True
    except Exception:
        pass
    try:
        from core.constants import HP_ID, HUMAN_PLAYER

        if not HUMAN_PLAYER:
            return False
        pid = int(getattr(player, "id", 0) or 0)
        if isinstance(HP_ID, (list, tuple, set)):
            return pid in {int(x) for x in HP_ID}
        return pid == int(HP_ID)
    except Exception:
        return False


def player_id_is_human(game: Any, player_id: Any) -> bool:
    """True when the given player id is a human seat in this game."""
    try:
        pid = int(player_id or 0)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        for p in list(getattr(game, "players", None) or []):
            if p is None:
                continue
            try:
                if int(getattr(p, "id", 0) or 0) == pid:
                    return is_human_player(p)
            except Exception:
                continue
    except Exception:
        pass
    try:
        from core.constants import HP_ID, HUMAN_PLAYER

        if not HUMAN_PLAYER:
            return False
        if isinstance(HP_ID, (list, tuple, set)):
            return pid in {int(x) for x in HP_ID}
        return pid == int(HP_ID)
    except Exception:
        return False


def steal_involves_human(
    game: Any,
    *,
    thief_id: Optional[Any] = None,
    victim_id: Optional[Any] = None,
) -> bool:
    """True if human is thief or victim of this steal."""
    if is_check_mode():
        return True
    if thief_id is not None and player_id_is_human(game, thief_id):
        return True
    if victim_id is not None and player_id_is_human(game, victim_id):
        return True
    # Fallback: last_robber_steal_result on game
    try:
        result = getattr(game, "last_robber_steal_result", None) or {}
        if not isinstance(result, dict):
            return False
        t = result.get("player_id")
        v = result.get("opponent_id")
        if t is not None and player_id_is_human(game, t):
            return True
        if v is not None and player_id_is_human(game, v):
            return True
    except Exception:
        pass
    return False


def filter_event_feed_message(
    message: str,
    game: Any = None,
    *,
    player_id: Any = None,
) -> Optional[str]:
    """Return message for Events, or None to drop.

    CHECK_MODE False:
      - drop DBG: lines
      - anonymize steal resource name (option A)
      - anonymize opponent DCard *buy/draw* type (play messages keep type)
    """
    text = str(message or "")
    if is_check_mode():
        return text
    stripped = text.lstrip()
    if stripped.upper().startswith("DBG:") or stripped.startswith("DBG:"):
        return None
    import re

    # steals Ore from P2  →  steals a card from P2
    m = re.match(
        r"^(?P<pre>.*\bsteals\s+)(?P<res>.+?)(?P<post>\s+from\s+P\d+.*)$",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        res = str(m.group("res") or "").strip()
        if res and res.lower() not in {"a card", "card", "a resource", "resource"}:
            return f"{m.group('pre')}a card{m.group('post')}"

    # Opponent bought a DCard (knight) → bought a DCard
    # Keep human buys fully named; keep "plays Knight" etc. unchanged.
    is_human_actor = False
    if player_id is not None:
        is_human_actor = player_id_is_human(game, player_id)
    if not is_human_actor:
        m2 = re.match(
            r"^(?P<pre>.*\bbought a DCard)\s*\([^)]+\)\s*(?P<post>.*)$",
            text,
            flags=re.IGNORECASE,
        )
        if m2:
            return f"{m2.group('pre')}{m2.group('post')}".rstrip()
        # "bought a development card (knight)" style variants
        m3 = re.match(
            r"^(?P<pre>.*\bbought a development card)\s*\([^)]+\)\s*(?P<post>.*)$",
            text,
            flags=re.IGNORECASE,
        )
        if m3:
            return f"{m3.group('pre')}{m3.group('post')}".rstrip()

    return text


def should_show_opponent_rcard_breakdown(player: Any) -> bool:
    """Per-type Wh/O/Wd/B/Sh on scoreboard."""
    if is_check_mode():
        return True
    return is_human_player(player)


def should_show_steal_detail(game: Any, *, thief_id: Any = None, victim_id: Any = None) -> bool:
    """Steal row / steal contribution to red deltas."""
    if is_check_mode():
        return True
    return steal_involves_human(game, thief_id=thief_id, victim_id=victim_id)


def should_show_execution_debug() -> bool:
    return is_check_mode()


def should_show_full_dcard_triplets(player: Any = None) -> bool:
    """True → new/playable/played; False → played column only.

    Human always sees full triplets (own hand management). Opponents only when
    CHECK_MODE is True (dig-in).
    """
    if is_human_player(player):
        return True
    return is_check_mode()


def twp_counter_ai_hand_cap_enabled() -> bool:
    """When False, counter AI steppers use generic max (no hand leak)."""
    return is_check_mode()
