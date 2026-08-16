"""Phase C2 WP-R7: matched control vs treat way-reassess report.

Match keys (in order):
  1. ``dice_hash`` from each game's result.json
  2. fallback: sequence_number when both batches share library layout

Primary metrics (per treated seat, plan §7):
  - unique_ways_used / way_switch_count
  - win rate, mean VP
  - way_reassess.jsonl: switched rate, eta_gain_if_switch distribution
  - first_way_fit_total (when present)

See docs/PhaseC2_way_reassess_experiment_plan.md.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

REPORT_SCHEMA = 1


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _mean(values: Sequence[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _median(values: Sequence[float]) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    return float(statistics.median(vals))


def _pct(n: int, d: int) -> Optional[float]:
    if d <= 0:
        return None
    return round(100.0 * float(n) / float(d), 2)


def _quantile(values: Sequence[float], q: float) -> Optional[float]:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    q = max(0.0, min(1.0, float(q)))
    idx = q * (len(vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    frac = idx - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_batch_arm_meta(batch_dir: Path) -> Dict[str, Any]:
    """Read arm block from batch_summary.json if present."""
    summary_path = Path(batch_dir) / "batch_summary.json"
    out: Dict[str, Any] = {
        "batch_dir": str(batch_dir),
        "batch_id": None,
        "arm_name": None,
        "explicit_142_recalc_by_seat": {},
        "dice_from_batch": None,
        "seed_base": None,
        "seed": None,
        "games_completed": None,
    }
    data = load_json(summary_path)
    if not isinstance(data, Mapping):
        return out
    out["batch_id"] = data.get("batch_id")
    out["arm_name"] = data.get("arm_name") or (data.get("arm") or {}).get("arm_name")
    arm = data.get("arm") if isinstance(data.get("arm"), Mapping) else {}
    out["explicit_142_recalc_by_seat"] = (
        arm.get("explicit_142_recalc_by_seat")
        or data.get("explicit_142_recalc_by_seat")
        or {}
    )
    out["dice_from_batch"] = data.get("dice_from_batch") or arm.get("dice_from_batch")
    out["seed_base"] = data.get("seed_base") if data.get("seed_base") is not None else arm.get("seed_base")
    out["seed"] = data.get("seed") if data.get("seed") is not None else arm.get("seed")
    out["games_completed"] = data.get("games_completed")
    return out


def infer_treated_seats(
    explicit_map: Optional[Mapping[Any, Any]] = None,
    *,
    default_if_empty: Optional[List[int]] = None,
) -> List[int]:
    """Seats with non-[0] explicit_142_recalc."""
    treated: List[int] = []
    for k, v in dict(explicit_map or {}).items():
        seat = _safe_int(k)
        if seat is None:
            continue
        raw = list(v) if isinstance(v, (list, tuple)) else [v]
        # treat as control if only 0 / empty
        codes = []
        for item in raw:
            if isinstance(item, (list, tuple)) and item:
                try:
                    codes.append(int(item[0]))
                except Exception:
                    pass
            else:
                try:
                    codes.append(int(item))
                except Exception:
                    pass
        if not codes or codes == [0] or all(c == 0 for c in codes):
            continue
        treated.append(int(seat))
    treated = sorted(set(treated))
    if not treated and default_if_empty:
        return list(default_if_empty)
    return treated


def load_batch_games(batch_dir: PathLike) -> Dict[str, Any]:
    """Load per-game result.json rows keyed for matching.

    Returns {ok, batch_dir, arm, games: [{seq, dice_hash, path, result, ...}], error}.
    """
    root = Path(batch_dir)
    out: Dict[str, Any] = {
        "ok": False,
        "batch_dir": str(root),
        "arm": {},
        "games": [],
        "error": "",
    }
    if not root.is_dir():
        out["error"] = f"batch dir not found: {root}"
        return out

    arm = load_batch_arm_meta(root)
    out["arm"] = arm
    games: List[Dict[str, Any]] = []

    for child in sorted(root.glob("g*/result.json")):
        res = load_json(child)
        if not isinstance(res, Mapping):
            continue
        seq = _safe_int(res.get("sequence_number"), None)
        if seq is None:
            # g001 → 1
            try:
                seq = int(child.parent.name.lstrip("g") or 0)
            except Exception:
                seq = None
        dice_hash = res.get("dice_hash")
        if dice_hash is not None:
            dice_hash = str(dice_hash)
        status = str(res.get("status") or "")
        winner = res.get("winner_id")
        vp = res.get("vp_by_player") if isinstance(res.get("vp_by_player"), Mapping) else {}
        ways_used = res.get("ways_used_by_seat") if isinstance(res.get("ways_used_by_seat"), Mapping) else {}
        unique_counts = (
            res.get("unique_ways_count_by_seat")
            if isinstance(res.get("unique_ways_count_by_seat"), Mapping)
            else {}
        )
        switch_counts = (
            res.get("way_switch_count_by_seat")
            if isinstance(res.get("way_switch_count_by_seat"), Mapping)
            else {}
        )
        fit = (
            res.get("first_way_fit_by_seat")
            if isinstance(res.get("first_way_fit_by_seat"), Mapping)
            else {}
        )
        explicit = (
            res.get("explicit_142_recalc_by_seat")
            if isinstance(res.get("explicit_142_recalc_by_seat"), Mapping)
            else arm.get("explicit_142_recalc_by_seat") or {}
        )
        games.append(
            {
                "sequence_number": seq,
                "game_id": str(res.get("game_id") or "") or None,
                "dice_hash": dice_hash,
                "seed": res.get("seed"),
                "status": status,
                "winner_id": winner,
                "vp_by_player": {str(k): _safe_float(v, 0.0) for k, v in dict(vp).items()},
                "ways_used_by_seat": {
                    str(k): list(v) if isinstance(v, list) else v
                    for k, v in dict(ways_used).items()
                },
                "unique_ways_count_by_seat": {
                    str(k): _safe_int(v, 0) or 0 for k, v in dict(unique_counts).items()
                },
                "way_switch_count_by_seat": {
                    str(k): _safe_int(v, 0) or 0 for k, v in dict(switch_counts).items()
                },
                "first_way_fit_by_seat": dict(fit),
                "explicit_142_recalc_by_seat": dict(explicit),
                "rounds": res.get("rounds"),
                "duration_s": res.get("duration_s"),
                "path": str(child),
                "arm_name": res.get("arm_name") or arm.get("arm_name"),
            }
        )

    out["games"] = games
    out["ok"] = bool(games)
    if not games:
        out["error"] = f"no g*/result.json under {root}"
    return out


def load_way_reassess_events(batch_dir: PathLike) -> List[Dict[str, Any]]:
    """Load batch_dir/way_reassess.jsonl rows (best-effort)."""
    root = Path(batch_dir)
    candidates = [
        root / "way_reassess.jsonl",
        root / "way_reassess.json",
    ]
    # also from summary path
    summary = load_json(root / "batch_summary.json")
    if isinstance(summary, Mapping) and summary.get("way_reassess_log_path"):
        candidates.insert(0, Path(str(summary["way_reassess_log_path"])))

    rows: List[Dict[str, Any]] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            from core.way_reassess_log import iter_way_reassess_rows

            rows = iter_way_reassess_rows(path)
            if rows:
                return rows
        except Exception:
            # fallback line parse
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            rows.append(obj)
                    except Exception:
                        continue
            except Exception:
                continue
        if rows:
            return rows
    return rows


def match_games(
    control_games: Sequence[Mapping[str, Any]],
    treat_games: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Pair games by dice_hash (preferred) else sequence_number."""
    ctrl_by_hash: Dict[str, Mapping[str, Any]] = {}
    ctrl_by_seq: Dict[int, Mapping[str, Any]] = {}
    for g in control_games:
        h = g.get("dice_hash")
        if h:
            ctrl_by_hash[str(h)] = g
        seq = _safe_int(g.get("sequence_number"), None)
        if seq is not None:
            ctrl_by_seq[int(seq)] = g

    pairs: List[Dict[str, Any]] = []
    unmatched_treat: List[Any] = []
    used_ctrl: set = set()

    for tg in treat_games:
        matched = None
        match_key = None
        match_how = None
        h = tg.get("dice_hash")
        if h and str(h) in ctrl_by_hash:
            matched = ctrl_by_hash[str(h)]
            match_key = str(h)
            match_how = "dice_hash"
        else:
            seq = _safe_int(tg.get("sequence_number"), None)
            if seq is not None and int(seq) in ctrl_by_seq:
                matched = ctrl_by_seq[int(seq)]
                match_key = str(seq)
                match_how = "sequence_number"
        if matched is None:
            unmatched_treat.append(tg.get("sequence_number") or tg.get("game_id"))
            continue
        uid = id(matched)
        if uid in used_ctrl and match_how == "sequence_number":
            # allow hash uniqueness; for seq still pair
            pass
        used_ctrl.add(uid)
        pairs.append(
            {
                "match_how": match_how,
                "match_key": match_key,
                "control": matched,
                "treat": tg,
            }
        )

    unmatched_ctrl = []
    paired_ctrl_ids = {id(p["control"]) for p in pairs}
    for g in control_games:
        if id(g) not in paired_ctrl_ids:
            unmatched_ctrl.append(g.get("sequence_number") or g.get("game_id"))

    return {
        "pairs": pairs,
        "n_pairs": len(pairs),
        "n_control": len(list(control_games)),
        "n_treat": len(list(treat_games)),
        "unmatched_treat": unmatched_treat,
        "unmatched_control": unmatched_ctrl,
        "match_how_counts": _count_by(pairs, "match_how"),
    }


def _count_by(rows: Sequence[Mapping[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "")
        out[k] = out.get(k, 0) + 1
    return out


def _seat_unique_ways(game: Mapping[str, Any], seat: int) -> int:
    key = str(seat)
    u = game.get("unique_ways_count_by_seat") or {}
    if key in u:
        return int(u.get(key) or 0)
    ways = (game.get("ways_used_by_seat") or {}).get(key) or []
    if isinstance(ways, list):
        return len(ways)
    return 0


def _seat_switch_count(game: Mapping[str, Any], seat: int) -> int:
    key = str(seat)
    s = game.get("way_switch_count_by_seat") or {}
    if key in s:
        return int(s.get(key) or 0)
    u = _seat_unique_ways(game, seat)
    return max(0, u - 1)


def _seat_vp(game: Mapping[str, Any], seat: int) -> Optional[float]:
    vp = game.get("vp_by_player") or {}
    return _safe_float(vp.get(str(seat)), None)


def _seat_won(game: Mapping[str, Any], seat: int) -> bool:
    return _safe_int(game.get("winner_id"), None) == int(seat)


def _seat_fit_total(game: Mapping[str, Any], seat: int) -> Optional[float]:
    fit = game.get("first_way_fit_by_seat") or {}
    bag = fit.get(str(seat))
    if isinstance(bag, Mapping):
        return _safe_float(bag.get("fit_total"), None)
    return None


def summarize_seat_side(
    games: Sequence[Mapping[str, Any]],
    seat: int,
) -> Dict[str, Any]:
    """Aggregate unique ways / switches / wins / VP / fit for one seat across games."""
    unique_list: List[float] = []
    switch_list: List[float] = []
    vp_list: List[float] = []
    fit_list: List[float] = []
    wins = 0
    n = 0
    ge2 = 0
    for g in games:
        n += 1
        u = _seat_unique_ways(g, seat)
        unique_list.append(float(u))
        if u >= 2:
            ge2 += 1
        switch_list.append(float(_seat_switch_count(g, seat)))
        vp = _seat_vp(g, seat)
        if vp is not None:
            vp_list.append(float(vp))
        if _seat_won(g, seat):
            wins += 1
        ft = _seat_fit_total(g, seat)
        if ft is not None:
            fit_list.append(float(ft))
    return {
        "seat": int(seat),
        "n_games": n,
        "unique_ways_mean": _mean(unique_list),
        "unique_ways_median": _median(unique_list),
        "unique_ways_ge2_frac": (ge2 / n) if n else None,
        "unique_ways_ge2_count": ge2,
        "way_switch_mean": _mean(switch_list),
        "way_switch_median": _median(switch_list),
        "win_rate": (wins / n) if n else None,
        "wins": wins,
        "vp_mean": _mean(vp_list),
        "first_way_fit_total_mean": _mean(fit_list),
        "first_way_fit_n": len(fit_list),
    }


def summarize_reassess_events(
    events: Sequence[Mapping[str, Any]],
    *,
    seat: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate way_reassess JSONL for optional seat filter."""
    rows = []
    for e in events or []:
        if not isinstance(e, Mapping):
            continue
        if seat is not None:
            pid = _safe_int(e.get("player_id"), None)
            if pid != int(seat):
                continue
        rows.append(e)
    n = len(rows)
    switched = sum(1 for r in rows if bool(r.get("switched")))
    gains: List[float] = []
    for r in rows:
        g = _safe_float(r.get("eta_gain_if_switch"), None)
        if g is None:
            el = _safe_float(r.get("eta_locked"), None)
            ea = _safe_float(r.get("eta_alt"), None)
            if el is not None and ea is not None:
                g = el - ea
        if g is not None:
            gains.append(float(g))
    triggers: Dict[str, int] = {}
    for r in rows:
        t = str(r.get("trigger") or "unknown")
        triggers[t] = triggers.get(t, 0) + 1
    return {
        "seat": seat,
        "n_events": n,
        "n_switched": switched,
        "switch_rate": (switched / n) if n else None,
        "eta_gain_mean": _mean(gains),
        "eta_gain_median": _median(gains),
        "eta_gain_p25": _quantile(gains, 0.25),
        "eta_gain_p75": _quantile(gains, 0.75),
        "eta_gain_n": len(gains),
        "triggers": dict(sorted(triggers.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def paired_seat_deltas(
    pairs: Sequence[Mapping[str, Any]],
    seat: int,
) -> Dict[str, Any]:
    """Control vs treat deltas on matched pairs for one seat."""
    d_unique: List[float] = []
    d_switch: List[float] = []
    d_vp: List[float] = []
    treat_ge2 = 0
    ctrl_ge2 = 0
    treat_wins = 0
    ctrl_wins = 0
    n = 0
    for p in pairs:
        c = p.get("control") or {}
        t = p.get("treat") or {}
        if not isinstance(c, Mapping) or not isinstance(t, Mapping):
            continue
        n += 1
        cu = _seat_unique_ways(c, seat)
        tu = _seat_unique_ways(t, seat)
        d_unique.append(float(tu - cu))
        if cu >= 2:
            ctrl_ge2 += 1
        if tu >= 2:
            treat_ge2 += 1
        d_switch.append(
            float(_seat_switch_count(t, seat) - _seat_switch_count(c, seat))
        )
        cv = _seat_vp(c, seat)
        tv = _seat_vp(t, seat)
        if cv is not None and tv is not None:
            d_vp.append(float(tv - cv))
        if _seat_won(c, seat):
            ctrl_wins += 1
        if _seat_won(t, seat):
            treat_wins += 1
    return {
        "seat": int(seat),
        "n_pairs": n,
        "delta_unique_ways_mean": _mean(d_unique),
        "delta_unique_ways_median": _median(d_unique),
        "delta_switch_mean": _mean(d_switch),
        "delta_vp_mean": _mean(d_vp),
        "control_unique_ge2_frac": (ctrl_ge2 / n) if n else None,
        "treat_unique_ge2_frac": (treat_ge2 / n) if n else None,
        "control_win_rate": (ctrl_wins / n) if n else None,
        "treat_win_rate": (treat_wins / n) if n else None,
        "explore_signal": (
            # plan success: treat unique ways median often ≥ 2
            True
            if n and (_median([_seat_unique_ways(p["treat"], seat) for p in pairs if isinstance(p.get("treat"), Mapping)]) or 0) >= 2
            else False
        ),
    }


def analyze_matched_batches(
    control_dir: PathLike,
    treat_dir: PathLike,
    *,
    treated_seats: Optional[Sequence[int]] = None,
    match_on: str = "auto",
) -> Dict[str, Any]:
    """Full matched control vs treat analysis report dict."""
    ctrl_load = load_batch_games(control_dir)
    treat_load = load_batch_games(treat_dir)
    report: Dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "kind": "way_reassess_matched",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ok": False,
        "error": "",
        "control": {
            "batch_dir": str(control_dir),
            "arm": ctrl_load.get("arm"),
            "n_games": len(ctrl_load.get("games") or []),
        },
        "treat": {
            "batch_dir": str(treat_dir),
            "arm": treat_load.get("arm"),
            "n_games": len(treat_load.get("games") or []),
        },
    }

    if not ctrl_load.get("ok"):
        report["error"] = f"control: {ctrl_load.get('error') or 'load failed'}"
        return report
    if not treat_load.get("ok"):
        report["error"] = f"treat: {treat_load.get('error') or 'load failed'}"
        return report

    # Infer treated seats from treat arm / results
    seats = list(treated_seats) if treated_seats else []
    if not seats:
        seats = infer_treated_seats(
            (treat_load.get("arm") or {}).get("explicit_142_recalc_by_seat")
        )
    if not seats:
        # from first treat game
        games = treat_load.get("games") or []
        if games:
            seats = infer_treated_seats(games[0].get("explicit_142_recalc_by_seat"))
    if not seats:
        seats = [2]  # plan pilot default

    match = match_games(ctrl_load["games"], treat_load["games"])
    if match_on == "dice_hash":
        match["pairs"] = [p for p in match["pairs"] if p.get("match_how") == "dice_hash"]
        match["n_pairs"] = len(match["pairs"])
    elif match_on == "sequence":
        match["pairs"] = [
            p for p in match["pairs"] if p.get("match_how") == "sequence_number"
        ]
        match["n_pairs"] = len(match["pairs"])

    report["match"] = {
        "n_pairs": match["n_pairs"],
        "n_control": match["n_control"],
        "n_treat": match["n_treat"],
        "match_how_counts": match["match_how_counts"],
        "unmatched_treat": match["unmatched_treat"][:20],
        "unmatched_control": match["unmatched_control"][:20],
        "unmatched_treat_n": len(match["unmatched_treat"]),
        "unmatched_control_n": len(match["unmatched_control"]),
    }
    report["treated_seats"] = list(seats)

    # Events
    ctrl_events = load_way_reassess_events(control_dir)
    treat_events = load_way_reassess_events(treat_dir)

    # Paired control/treat game lists
    paired_ctrl = [p["control"] for p in match["pairs"]]
    paired_treat = [p["treat"] for p in match["pairs"]]

    seats_report: Dict[str, Any] = {}
    for seat in seats:
        seats_report[str(seat)] = {
            "control_all": summarize_seat_side(ctrl_load["games"], seat),
            "treat_all": summarize_seat_side(treat_load["games"], seat),
            "control_matched": summarize_seat_side(paired_ctrl, seat),
            "treat_matched": summarize_seat_side(paired_treat, seat),
            "paired_deltas": paired_seat_deltas(match["pairs"], seat),
            "control_reassess": summarize_reassess_events(ctrl_events, seat=seat),
            "treat_reassess": summarize_reassess_events(treat_events, seat=seat),
        }

    report["seats"] = seats_report
    report["reassess_events"] = {
        "control_n": len(ctrl_events),
        "treat_n": len(treat_events),
        "control_all_seats": summarize_reassess_events(ctrl_events),
        "treat_all_seats": summarize_reassess_events(treat_events),
    }

    # Table-wide win rates (all seats)
    report["table"] = {
        "control_status_counts": _status_counts(ctrl_load["games"]),
        "treat_status_counts": _status_counts(treat_load["games"]),
        "control_rounds_mean": _mean(
            [_safe_float(g.get("rounds"), None) for g in ctrl_load["games"]]
        ),
        "treat_rounds_mean": _mean(
            [_safe_float(g.get("rounds"), None) for g in treat_load["games"]]
        ),
    }

    # Headline explore signal across treated seats
    signals = []
    for seat in seats:
        d = seats_report[str(seat)]["paired_deltas"]
        signals.append(bool(d.get("explore_signal")))
    report["headline"] = {
        "n_pairs": match["n_pairs"],
        "treated_seats": seats,
        "any_explore_signal": any(signals),
        "explore_signal_by_seat": {
            str(s): seats_report[str(s)]["paired_deltas"].get("explore_signal")
            for s in seats
        },
        "note": (
            "explore_signal=True when matched treat median unique_ways ≥ 2 "
            "for that seat (plan success signal)."
        ),
    }

    report["ok"] = True
    return report


def _status_counts(games: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for g in games:
        st = str(g.get("status") or "unknown")
        out[st] = out.get(st, 0) + 1
    return out


def format_console_summary(report: Mapping[str, Any]) -> str:
    """Human one-pager for CLI."""
    lines: List[str] = []
    lines.append("=== Way reassess matched report ===")
    if not report.get("ok"):
        lines.append(f"ERROR: {report.get('error')}")
        return "\n".join(lines)

    c = report.get("control") or {}
    t = report.get("treat") or {}
    m = report.get("match") or {}
    lines.append(f"control: {c.get('batch_dir')}  arm={((c.get('arm') or {}).get('arm_name'))}")
    lines.append(f"treat:   {t.get('batch_dir')}  arm={((t.get('arm') or {}).get('arm_name'))}")
    lines.append(
        f"matched pairs: {m.get('n_pairs')}  "
        f"(control games={m.get('n_control')}, treat games={m.get('n_treat')})  "
        f"how={m.get('match_how_counts')}"
    )
    if m.get("unmatched_treat_n") or m.get("unmatched_control_n"):
        lines.append(
            f"unmatched: treat={m.get('unmatched_treat_n')}  "
            f"control={m.get('unmatched_control_n')}"
        )

    h = report.get("headline") or {}
    lines.append(
        f"explore_signal (any treated seat, median unique≥2): {h.get('any_explore_signal')}"
    )

    seats = report.get("seats") or {}
    for seat_key, bag in seats.items():
        lines.append(f"-- seat {seat_key} --")
        cm = bag.get("control_matched") or {}
        tm = bag.get("treat_matched") or {}
        d = bag.get("paired_deltas") or {}
        lines.append(
            f"  unique_ways mean  C={_fmt(cm.get('unique_ways_mean'))}  "
            f"T={_fmt(tm.get('unique_ways_mean'))}  "
            f"Δ={_fmt(d.get('delta_unique_ways_mean'))}"
        )
        lines.append(
            f"  unique_ways med   C={_fmt(cm.get('unique_ways_median'))}  "
            f"T={_fmt(tm.get('unique_ways_median'))}"
        )
        lines.append(
            f"  unique≥2 frac     C={_fmt_pct(cm.get('unique_ways_ge2_frac'))}  "
            f"T={_fmt_pct(tm.get('unique_ways_ge2_frac'))}"
        )
        lines.append(
            f"  way_switch mean   C={_fmt(cm.get('way_switch_mean'))}  "
            f"T={_fmt(tm.get('way_switch_mean'))}  "
            f"Δ={_fmt(d.get('delta_switch_mean'))}"
        )
        lines.append(
            f"  win rate          C={_fmt_pct(cm.get('win_rate'))}  "
            f"T={_fmt_pct(tm.get('win_rate'))}"
        )
        lines.append(
            f"  VP mean           C={_fmt(cm.get('vp_mean'))}  "
            f"T={_fmt(tm.get('vp_mean'))}  "
            f"Δ={_fmt(d.get('delta_vp_mean'))}"
        )
        if cm.get("first_way_fit_total_mean") is not None or tm.get("first_way_fit_total_mean") is not None:
            lines.append(
                f"  first_way fit μ   C={_fmt(cm.get('first_way_fit_total_mean'))}  "
                f"T={_fmt(tm.get('first_way_fit_total_mean'))}"
            )
        cr = bag.get("control_reassess") or {}
        tr = bag.get("treat_reassess") or {}
        lines.append(
            f"  reassess events   C={cr.get('n_events')} (sw={_fmt_pct(cr.get('switch_rate'))})  "
            f"T={tr.get('n_events')} (sw={_fmt_pct(tr.get('switch_rate'))})"
        )
        if tr.get("eta_gain_mean") is not None:
            lines.append(
                f"  eta_gain (T)      mean={_fmt(tr.get('eta_gain_mean'))}  "
                f"med={_fmt(tr.get('eta_gain_median'))}  "
                f"p25={_fmt(tr.get('eta_gain_p25'))}  p75={_fmt(tr.get('eta_gain_p75'))}"
            )
        lines.append(f"  explore_signal    {d.get('explore_signal')}")

    re = report.get("reassess_events") or {}
    lines.append(
        f"reassess JSONL totals: control={re.get('control_n')}  treat={re.get('treat_n')}"
    )
    lines.append("===================================")
    return "\n".join(lines)


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.3f}"
    except Exception:
        return str(v)


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return f"{100.0 * float(v):.1f}%"
    except Exception:
        return str(v)


def write_report(path: PathLike, report: Mapping[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, ensure_ascii=False, default=str)
    out.write_text(text + "\n", encoding="utf-8")
    return out.resolve()


__all__ = [
    "load_batch_games",
    "load_way_reassess_events",
    "load_batch_arm_meta",
    "infer_treated_seats",
    "match_games",
    "summarize_seat_side",
    "summarize_reassess_events",
    "paired_seat_deltas",
    "analyze_matched_batches",
    "format_console_summary",
    "write_report",
]
