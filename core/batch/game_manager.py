"""Phase B: batch shell over ``HeadlessGameRunner`` (N games + summary).

Gen2 inspiration (shape only): cycles, win counters, duration history, batch done.
Gen3: no GUI manager screen; pure aggregation + JSON under ``batch_runs/``.

Does not own rules — only sequences ``run_one()`` and aggregates result dicts.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

from core import console
from core.batch.headless_runner import HeadlessGameRunner
from core.batch.result import (
    STATUS_ERROR,
    STATUS_MAX_ROUND,
    STATUS_STUCK,
    STATUS_WON,
    collect_operator_flags,
    write_result,
)

BATCH_SCHEMA_VERSION = 1

# Compact keys kept per game in batch_summary.json (full result still on disk).
_COMPACT_GAME_KEYS = (
    "sequence_number",
    "status",
    "winner_id",
    "rounds",
    "turn",
    "steps",
    "duration_s",
    "vp_by_player",
    "lr_holder_id",
    "la_holder_id",
    "game_id",
    "error",
    "result_path",
    "cs_log_path",  # WP-C4
    "mglog_path",  # MGlog M7
    "playboard_path",  # per-game map for MGlog re-play
    "batch_id",  # WP-C4
    "seed",  # WP-R1
    "dice_count",  # WP-R2
    "dice_hash",  # WP-R2
    "unique_ways_count_by_seat",  # WP-R4
    "way_switch_count_by_seat",  # WP-R4
    "first_way_fit_by_seat",  # WP-R5
    "arm_name",  # WP-R6
    "explicit_142_recalc_by_seat",  # WP-R6
    "la_soft_bias_mode",  # LA timing soft bias lab
    "la_giveup_fires_total",  # Phase L L6 live fires
    "lr_giveup_fires_total",
    "la_giveup_fires_by_seat",
    "lr_giveup_fires_by_seat",
    "salvage_t1_adopts_total",  # Phase L S7 salvage dig
    "salvage_t2_adopts_total",
    "salvage_adopts_total",
    "salvage_t1_adopts_by_seat",
    "salvage_t2_adopts_by_seat",
    "salvage_adopts_by_seat",
    "settles_deferred_scans",  # S5b G6
    "settles_dead_scans",
    "seats_ever_deferred_count",
    "seats_ever_dead_count",
)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def compact_game_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Strip a full per-game result to batch-summary row fields."""
    out: Dict[str, Any] = {}
    for key in _COMPACT_GAME_KEYS:
        if key in result:
            out[key] = result[key]
    return out


def default_batch_dir(*, timestamp: Optional[str] = None) -> Path:
    """``batch_runs/<timestamp>_batch/`` under cwd."""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path.cwd() / "batch_runs" / f"{ts}_batch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_batch_summary(
    game_results: List[Mapping[str, Any]],
    *,
    games_requested: int,
    batch_dir: Optional[Union[str, Path]] = None,
    batch_id: str = "",
    duration_s_wall: Optional[float] = None,
    runner_defaults: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Aggregate per-game results into a batch summary dict (schema v1)."""
    status_counts = {
        STATUS_WON: 0,
        STATUS_MAX_ROUND: 0,
        STATUS_STUCK: 0,
        STATUS_ERROR: 0,
    }
    wins_by_player: Dict[str, int] = {}
    durations: List[float] = []
    rounds_list: List[float] = []
    steps_list: List[float] = []
    compact_games: List[Dict[str, Any]] = []
    result_paths: List[str] = []

    for raw in game_results:
        row = compact_game_result(raw)
        compact_games.append(row)
        st = str(raw.get("status") or STATUS_ERROR)
        if st in status_counts:
            status_counts[st] += 1
        else:
            status_counts[STATUS_ERROR] = status_counts.get(STATUS_ERROR, 0) + 1

        wid = raw.get("winner_id")
        if st == STATUS_WON and wid is not None:
            key = str(wid)
            wins_by_player[key] = wins_by_player.get(key, 0) + 1

        d = raw.get("duration_s")
        if d is not None:
            durations.append(_safe_float(d))
        r = raw.get("rounds")
        if r is not None:
            rounds_list.append(float(_safe_int(r)))
        s = raw.get("steps")
        if s is not None:
            steps_list.append(float(_safe_int(s)))

        rp = raw.get("result_path")
        if rp:
            result_paths.append(str(rp))

    # Ensure seats 1..NUM_PLAYERS appear in wins table
    try:
        from core.constants import NUM_PLAYERS

        n = max(1, int(NUM_PLAYERS or 4))
    except Exception:
        n = 4
    for pid in range(1, n + 1):
        wins_by_player.setdefault(str(pid), 0)

    # Phase L L6: aggregate live give-up fire counts across games
    la_fires_total = 0
    lr_fires_total = 0
    la_fires_by_seat: Dict[str, int] = {}
    lr_fires_by_seat: Dict[str, int] = {}
    games_with_la_fire = 0
    games_with_lr_fire = 0
    # Phase L S7: salvage adopt aggregates
    salvage_t1_total = 0
    salvage_t2_total = 0
    salvage_t1_by_seat: Dict[str, int] = {}
    salvage_t2_by_seat: Dict[str, int] = {}
    salvage_adopts_by_seat: Dict[str, int] = {}
    games_with_salvage_t1 = 0
    games_with_salvage_t2 = 0
    games_with_salvage = 0
    for raw in game_results:
        la_n = _safe_int(raw.get("la_giveup_fires_total"), 0)
        lr_n = _safe_int(raw.get("lr_giveup_fires_total"), 0)
        la_fires_total += la_n
        lr_fires_total += lr_n
        if la_n > 0:
            games_with_la_fire += 1
        if lr_n > 0:
            games_with_lr_fire += 1
        for seat, cnt in (raw.get("la_giveup_fires_by_seat") or {}).items():
            k = str(seat)
            la_fires_by_seat[k] = la_fires_by_seat.get(k, 0) + _safe_int(cnt, 0)
        for seat, cnt in (raw.get("lr_giveup_fires_by_seat") or {}).items():
            k = str(seat)
            lr_fires_by_seat[k] = lr_fires_by_seat.get(k, 0) + _safe_int(cnt, 0)

        t1_n = _safe_int(raw.get("salvage_t1_adopts_total"), 0)
        t2_n = _safe_int(raw.get("salvage_t2_adopts_total"), 0)
        ad_n = _safe_int(raw.get("salvage_adopts_total"), t1_n + t2_n)
        salvage_t1_total += t1_n
        salvage_t2_total += t2_n
        if t1_n > 0:
            games_with_salvage_t1 += 1
        if t2_n > 0:
            games_with_salvage_t2 += 1
        if ad_n > 0:
            games_with_salvage += 1
        for seat, cnt in (raw.get("salvage_t1_adopts_by_seat") or {}).items():
            k = str(seat)
            salvage_t1_by_seat[k] = salvage_t1_by_seat.get(k, 0) + _safe_int(cnt, 0)
        for seat, cnt in (raw.get("salvage_t2_adopts_by_seat") or {}).items():
            k = str(seat)
            salvage_t2_by_seat[k] = salvage_t2_by_seat.get(k, 0) + _safe_int(cnt, 0)
        for seat, cnt in (raw.get("salvage_adopts_by_seat") or {}).items():
            k = str(seat)
            salvage_adopts_by_seat[k] = salvage_adopts_by_seat.get(k, 0) + _safe_int(
                cnt, 0
            )

    # S7 dig rates (fire → salvage) for batch summary
    salvage_dig: Dict[str, Any] = {}
    try:
        from core.partial_way_salvage import dig_salvage_fire_switch_kpis

        salvage_dig = dig_salvage_fire_switch_kpis(game_results)
    except Exception:
        salvage_dig = {}

    completed = len(game_results)
    summary: Dict[str, Any] = {
        "schema": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id or "",
        "games_requested": int(games_requested),
        "games_completed": completed,
        "status_counts": status_counts,
        "wins_by_player": dict(sorted(wins_by_player.items(), key=lambda kv: int(kv[0]))),
        "duration_s_total": sum(durations) if durations else 0.0,
        "duration_s_mean": _mean(durations),
        "duration_s_wall": duration_s_wall,
        "rounds_mean": _mean(rounds_list),
        "steps_mean": _mean(steps_list),
        "la_giveup_fires_total": la_fires_total,
        "lr_giveup_fires_total": lr_fires_total,
        "la_giveup_fires_by_seat": dict(
            sorted(la_fires_by_seat.items(), key=lambda kv: kv[0])
        ),
        "lr_giveup_fires_by_seat": dict(
            sorted(lr_fires_by_seat.items(), key=lambda kv: kv[0])
        ),
        "games_with_la_giveup_fire": games_with_la_fire,
        "games_with_lr_giveup_fire": games_with_lr_fire,
        "salvage_t1_adopts_total": salvage_t1_total,
        "salvage_t2_adopts_total": salvage_t2_total,
        "salvage_adopts_total": salvage_t1_total + salvage_t2_total,
        "salvage_t1_adopts_by_seat": dict(
            sorted(salvage_t1_by_seat.items(), key=lambda kv: kv[0])
        ),
        "salvage_t2_adopts_by_seat": dict(
            sorted(salvage_t2_by_seat.items(), key=lambda kv: kv[0])
        ),
        "salvage_adopts_by_seat": dict(
            sorted(salvage_adopts_by_seat.items(), key=lambda kv: kv[0])
        ),
        "games_with_salvage_t1": games_with_salvage_t1,
        "games_with_salvage_t2": games_with_salvage_t2,
        "games_with_salvage_adopt": games_with_salvage,
        "salvage_dig": salvage_dig,
        "games": compact_games,
        "result_paths": result_paths,
        "batch_dir": str(batch_dir) if batch_dir else None,
        "flags": collect_operator_flags(),
        "runner_defaults": dict(runner_defaults or {}),
    }
    return summary


def write_batch_summary(
    path: Union[str, Path],
    summary: Mapping[str, Any],
    *,
    indent: int = 2,
) -> Path:
    """Write batch summary JSON; return resolved path."""
    out = Path(path)
    if out.suffix.lower() != ".json":
        out = out / "batch_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(summary), indent=indent, ensure_ascii=False, default=str)
    out.write_text(text + "\n", encoding="utf-8")
    return out.resolve()


class GameManager:
    """Run ``games`` headless matches and write a batch summary.

    Parameters mirror ``HeadlessGameRunner`` shared kwargs; each game gets
    ``sequence_number`` 1..N and its own ``result.json`` under the batch dir.
    """

    def __init__(
        self,
        games: int = 1,
        *,
        max_round: Optional[int] = None,
        max_steps: Optional[int] = None,
        stuck_repeats: Optional[int] = None,
        progress_every: Optional[int] = None,
        board_name: str = "Base_Random",
        write_result_files: bool = True,
        write_batch_summary_file: bool = True,
        batch_dir: Optional[Union[str, Path]] = None,
        runner_factory: Optional[Callable[..., HeadlessGameRunner]] = None,
        stop_on_error: bool = False,
        seed: Optional[int] = None,
        seed_base: Optional[int] = None,
        dice_from_batch: Optional[Union[str, Path]] = None,
        explicit_142_recalc_by_seat: Optional[Mapping[Any, Any]] = None,
        arm_name: Optional[str] = None,
        arm_config: Optional[Mapping[str, Any]] = None,
        la_soft_bias: Optional[str] = None,
    ) -> None:
        self.games = max(1, int(games))
        self.max_round = max_round
        self.max_steps = max_steps
        self.stuck_repeats = stuck_repeats
        self.progress_every = progress_every
        self.board_name = str(board_name or "Base_Random")
        self.write_result_files = bool(write_result_files)
        self.write_batch_summary_file = bool(write_batch_summary_file)
        self.batch_dir_override = Path(batch_dir) if batch_dir else None
        self.runner_factory = runner_factory or HeadlessGameRunner
        self.stop_on_error = bool(stop_on_error)
        # WP-R1: seed_base preferred for multi-game (game i → seed_base + i - 1)
        self.seed = int(seed) if seed is not None else None
        self.seed_base = int(seed_base) if seed_base is not None else None
        # WP-R2: replay dice from a prior batch's g00N/result.json
        self.dice_from_batch = Path(dice_from_batch) if dice_from_batch else None
        self._dice_library: Dict[int, Dict[str, Any]] = {}
        if self.dice_from_batch is not None:
            try:
                from core.dice_script import load_dice_library_from_batch

                lib = load_dice_library_from_batch(self.dice_from_batch)
                if lib.get("ok"):
                    self._dice_library = dict(lib.get("scripts") or {})
            except Exception:
                self._dice_library = {}

        # WP-R6: experiment arm (explicit_142_recalc seat map + metadata)
        self.arm_name = str(arm_name).strip() if arm_name else None
        self.arm_config: Dict[str, Any] = dict(arm_config or {})
        if explicit_142_recalc_by_seat is not None:
            self.explicit_142_recalc_by_seat = dict(explicit_142_recalc_by_seat)
        elif self.arm_config.get("seat_map") or self.arm_config.get(
            "explicit_142_recalc_by_seat"
        ):
            self.explicit_142_recalc_by_seat = dict(
                self.arm_config.get("seat_map")
                or self.arm_config.get("explicit_142_recalc_by_seat")
                or {}
            )
        else:
            self.explicit_142_recalc_by_seat = None
        if not self.arm_name and self.arm_config.get("arm_name"):
            self.arm_name = str(self.arm_config.get("arm_name") or "") or None
        self.la_soft_bias = str(la_soft_bias).strip() if la_soft_bias else None
        self.perf_mode = None
        try:
            pm = self.arm_config.get("perf_mode")
            if pm is not None and str(pm).strip() != "":
                self.perf_mode = str(pm).strip().lower()
        except Exception:
            self.perf_mode = None

        self.games_played: int = 0
        self.game_results: List[Dict[str, Any]] = []
        self.batch_dir: Optional[Path] = None
        self.batch_id: Optional[str] = None
        self.batch_cs_path: Optional[Path] = None
        self.last_summary: Optional[Dict[str, Any]] = None

    def _resolve_game_seed(self, sequence_number: int) -> Optional[int]:
        if self.seed_base is not None:
            return int(self.seed_base) + int(sequence_number) - 1
        if self.seed is not None:
            return int(self.seed)
        return None

    def _runner_kwargs(
        self,
        sequence_number: int,
        result_path: Optional[Path],
        *,
        batch_id: str,
        cs_log_path: Optional[Path],
        mglog_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        kw: Dict[str, Any] = {
            "sequence_number": int(sequence_number),
            "max_round": self.max_round,
            "max_steps": self.max_steps,
            "board_name": self.board_name,
            "write_result_file": self.write_result_files,
            "result_path": str(result_path) if result_path else None,
            # Process console level already set by CLI; do not force WARN.
            "verbose": True,
            # WP-C4
            "batch_id": batch_id,
            "cs_log_path": str(cs_log_path) if cs_log_path else None,
            # MGlog M7: batch_dir/g00N/mglog.csv
            "mglog_path": str(mglog_path) if mglog_path else None,
        }
        seed = self._resolve_game_seed(sequence_number)
        script_info = self._dice_library.get(int(sequence_number)) if self._dice_library else None
        if script_info and script_info.get("dice_rolls"):
            kw["dice_rolls"] = list(script_info["dice_rolls"])
            # Prefer library seed for matched residual RNG when seed_base not set
            if seed is None and script_info.get("seed") is not None:
                try:
                    seed = int(script_info["seed"])
                except Exception:
                    pass
        if seed is not None:
            kw["seed"] = int(seed)
        if self.stuck_repeats is not None:
            kw["stuck_repeats"] = int(self.stuck_repeats)
        if self.progress_every is not None:
            kw["progress_every"] = int(self.progress_every)
        # WP-R6: pass arm seat map to each game
        if self.explicit_142_recalc_by_seat is not None:
            kw["explicit_142_recalc_by_seat"] = dict(self.explicit_142_recalc_by_seat)
        if self.arm_name:
            kw["arm_name"] = self.arm_name
        if self.la_soft_bias:
            kw["la_soft_bias"] = self.la_soft_bias
        try:
            if self.arm_config.get("sidestep_s142_drive"):
                kw["sidestep_s142_drive"] = True
        except Exception:
            pass
        if self.perf_mode:
            kw["perf_mode"] = self.perf_mode
        return kw

    def run_batch(self) -> Dict[str, Any]:
        """Run all games; return batch summary (and write ``batch_summary.json``)."""
        t0 = time.perf_counter()
        batch_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.batch_dir_override is not None:
            self.batch_dir = Path(self.batch_dir_override)
            self.batch_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.batch_dir = default_batch_dir(timestamp=batch_ts)

        batch_id = f"batch_{batch_ts}_n{self.games}"
        self.batch_id = batch_id
        # WP-C4: one CS JSONL per batch (all games in this run append here)
        self.batch_cs_path = self.batch_dir / "cs.jsonl"
        # WP-R4: way reassess compare log for the whole batch
        self.batch_way_reassess_path = self.batch_dir / "way_reassess.jsonl"
        # Phase L WP-L1: LA/LR god-view probe
        self.batch_la_lr_probe_path = self.batch_dir / "la_lr_probe.jsonl"
        # L2 cap-miss shadow dig (Phase E)
        self.batch_l2_cap_miss_path = self.batch_dir / "l2_cap_miss.jsonl"
        try:
            self.batch_cs_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self.game_results = []
        self.games_played = 0

        # Point strategy CS writer at per-batch file for the whole run
        prev_cs_override = None
        try:
            from core.strategy_cs_log import set_cs_log_path

            prev_cs_override = set_cs_log_path(str(self.batch_cs_path))
        except Exception:
            prev_cs_override = None
        prev_wr_override = None
        try:
            from core.way_reassess_log import set_way_reassess_log_path

            prev_wr_override = set_way_reassess_log_path(
                str(self.batch_way_reassess_path)
            )
        except Exception:
            prev_wr_override = None
        prev_lalr_override = None
        try:
            from core.la_lr_probe_log import set_la_lr_probe_log_path

            prev_lalr_override = set_la_lr_probe_log_path(
                str(self.batch_la_lr_probe_path)
            )
        except Exception:
            prev_lalr_override = None
        prev_l2miss_override = None
        try:
            from core.l2_cap_miss import set_l2_cap_miss_log_path

            prev_l2miss_override = set_l2_cap_miss_log_path(
                str(self.batch_l2_cap_miss_path)
            )
        except Exception:
            prev_l2miss_override = None

        if self._dice_library:
            console.info(
                f"GameManager: dice library from {self.dice_from_batch} "
                f"({len(self._dice_library)} scripts)"
            )
        console.info(
            f"GameManager: start batch_id={batch_id} games={self.games} "
            f"dir={self.batch_dir} cs={self.batch_cs_path} "
            f"way_reassess={self.batch_way_reassess_path} "
            f"la_lr_probe={self.batch_la_lr_probe_path} "
            f"l2_cap_miss={self.batch_l2_cap_miss_path}"
        )

        try:
            for i in range(1, self.games + 1):
                game_dir = self.batch_dir / f"g{i:03d}"
                game_dir.mkdir(parents=True, exist_ok=True)
                result_path = game_dir / "result.json" if self.write_result_files else None
                try:
                    from core.mglog import batch_game_mglog_path

                    mglog_path = Path(batch_game_mglog_path(game_dir))
                except Exception:
                    mglog_path = game_dir / "mglog.csv"

                console.info(f"GameManager: === game {i}/{self.games} ===")
                kw = self._runner_kwargs(
                    i,
                    result_path,
                    batch_id=batch_id,
                    cs_log_path=self.batch_cs_path,
                    mglog_path=mglog_path,
                )
                try:
                    runner = self.runner_factory(**kw)
                    result = runner.run_one()
                except Exception as exc:
                    console.error(f"GameManager: game {i} crashed: {exc}")
                    result = {
                        "schema": 1,
                        "status": STATUS_ERROR,
                        "sequence_number": i,
                        "game_id": "",
                        "rounds": None,
                        "turn": None,
                        "winner_id": None,
                        "vp_by_player": {},
                        "lr_holder_id": None,
                        "la_holder_id": None,
                        "duration_s": None,
                        "steps": 0,
                        "flags": collect_operator_flags(),
                        "cs_log_path": str(self.batch_cs_path) if self.batch_cs_path else None,
                        "mglog_path": str(mglog_path.resolve()) if mglog_path else None,
                        "playboard_path": str((game_dir / f"Playboard_g{i:03d}.txt").resolve())
                        if (game_dir / f"Playboard_g{i:03d}.txt").is_file()
                        else None,
                        "batch_id": batch_id,
                        "seed": self._resolve_game_seed(i),
                        "error": f"runner crashed: {exc}",
                        "overview": [],
                        "result_path": str(result_path) if result_path else None,
                    }
                    if self.write_result_files and result_path is not None:
                        try:
                            write_result(result_path, result)
                            result["result_path"] = str(Path(result_path).resolve())
                        except Exception:
                            pass

                if not isinstance(result, dict):
                    result = {
                        "status": STATUS_ERROR,
                        "sequence_number": i,
                        "error": "run_one returned non-dict",
                    }

                # Ensure batch CS path / id on result even if runner is a stub
                if not result.get("cs_log_path") and self.batch_cs_path is not None:
                    result["cs_log_path"] = str(self.batch_cs_path.resolve())
                if not result.get("mglog_path") and mglog_path is not None:
                    try:
                        result["mglog_path"] = str(Path(mglog_path).resolve())
                    except Exception:
                        result["mglog_path"] = str(mglog_path)
                if (
                    not result.get("way_reassess_log_path")
                    and self.batch_way_reassess_path is not None
                ):
                    result["way_reassess_log_path"] = str(
                        self.batch_way_reassess_path.resolve()
                    )
                if (
                    not result.get("la_lr_probe_log_path")
                    and getattr(self, "batch_la_lr_probe_path", None) is not None
                ):
                    result["la_lr_probe_log_path"] = str(
                        self.batch_la_lr_probe_path.resolve()
                    )
                if not result.get("batch_id"):
                    result["batch_id"] = batch_id

                self.games_played += 1
                self.game_results.append(dict(result))
                st = str(result.get("status") or "?")
                console.info(
                    f"GameManager: game {i}/{self.games} done status={st} "
                    f"winner={result.get('winner_id')} rounds={result.get('rounds')} "
                    f"duration_s={result.get('duration_s')}"
                )

                if self.stop_on_error and st in (STATUS_ERROR, STATUS_STUCK):
                    console.warn(
                        f"GameManager: stop_on_error after game {i} status={st}"
                    )
                    break
        finally:
            # Restore previous CS path (or clear) so interactive / next batch is clean
            try:
                from core.strategy_cs_log import set_cs_log_path

                set_cs_log_path(prev_cs_override)
            except Exception:
                pass
            try:
                from core.way_reassess_log import set_way_reassess_log_path

                set_way_reassess_log_path(prev_wr_override)
            except Exception:
                pass
            try:
                from core.la_lr_probe_log import set_la_lr_probe_log_path

                set_la_lr_probe_log_path(prev_lalr_override)
            except Exception:
                pass
            try:
                from core.l2_cap_miss import set_l2_cap_miss_log_path

                set_l2_cap_miss_log_path(prev_l2miss_override)
            except Exception:
                pass

        wall = time.perf_counter() - t0
        shared = {
            "max_round": self.max_round,
            "max_steps": self.max_steps,
            "board_name": self.board_name,
            "stuck_repeats": self.stuck_repeats,
        }
        summary = build_batch_summary(
            self.game_results,
            games_requested=self.games,
            batch_dir=self.batch_dir,
            batch_id=batch_id,
            duration_s_wall=wall,
            runner_defaults=shared,
        )
        # WP-R6: arm metadata on batch summary
        try:
            from core.batch.arm_config import arm_metadata_for_export

            arm_export = arm_metadata_for_export(self.arm_config) if self.arm_config else {}
            if not arm_export:
                arm_export = {
                    "arm_name": self.arm_name,
                    "explicit_142_recalc_by_seat": (
                        {
                            str(k): list(v)
                            for k, v in (self.explicit_142_recalc_by_seat or {}).items()
                        }
                        if self.explicit_142_recalc_by_seat
                        else None
                    ),
                    "dice_from_batch": (
                        str(self.dice_from_batch) if self.dice_from_batch else None
                    ),
                    "seed": self.seed,
                    "seed_base": self.seed_base,
                }
            else:
                # keep live paths
                if self.dice_from_batch is not None:
                    arm_export["dice_from_batch"] = str(self.dice_from_batch)
                if self.seed is not None:
                    arm_export["seed"] = self.seed
                if self.seed_base is not None:
                    arm_export["seed_base"] = self.seed_base
                if self.arm_name:
                    arm_export["arm_name"] = self.arm_name
            if self.perf_mode and not arm_export.get("perf_mode"):
                arm_export["perf_mode"] = self.perf_mode
            summary["arm"] = arm_export
            summary["arm_name"] = arm_export.get("arm_name")
            summary["perf_mode"] = arm_export.get("perf_mode") or self.perf_mode
            summary["explicit_142_recalc_by_seat"] = arm_export.get(
                "explicit_142_recalc_by_seat"
            )
            summary["dice_from_batch"] = arm_export.get("dice_from_batch")
        except Exception:
            summary["arm"] = {
                "arm_name": self.arm_name,
                "dice_from_batch": (
                    str(self.dice_from_batch) if self.dice_from_batch else None
                ),
            }
        # Lab LA soft bias stamp (batch-level)
        try:
            mode = self.la_soft_bias or "off"
            summary["la_soft_bias_mode"] = str(mode).strip().lower() or "off"
            if isinstance(summary.get("arm"), dict):
                summary["arm"]["la_soft_bias_mode"] = summary["la_soft_bias_mode"]
        except Exception:
            summary.setdefault("la_soft_bias_mode", "off")
        if self.batch_cs_path is not None:
            try:
                summary["cs_log_path"] = str(self.batch_cs_path.resolve())
            except Exception:
                summary["cs_log_path"] = str(self.batch_cs_path)
        else:
            summary["cs_log_path"] = None
        if getattr(self, "batch_way_reassess_path", None) is not None:
            try:
                summary["way_reassess_log_path"] = str(
                    self.batch_way_reassess_path.resolve()
                )
            except Exception:
                summary["way_reassess_log_path"] = str(self.batch_way_reassess_path)
        else:
            summary["way_reassess_log_path"] = None
        if getattr(self, "batch_la_lr_probe_path", None) is not None:
            try:
                summary["la_lr_probe_log_path"] = str(
                    self.batch_la_lr_probe_path.resolve()
                )
            except Exception:
                summary["la_lr_probe_log_path"] = str(self.batch_la_lr_probe_path)
        else:
            summary["la_lr_probe_log_path"] = None
        summary["batch_summary_path"] = None
        if self.write_batch_summary_file and self.batch_dir is not None:
            path = write_batch_summary(self.batch_dir / "batch_summary.json", summary)
            summary["batch_summary_path"] = str(path)
            # Rewrite with path included
            write_batch_summary(path, summary)
            console.info(f"GameManager: batch_summary → {path}")
            if summary.get("cs_log_path"):
                console.info(f"GameManager: batch CS → {summary['cs_log_path']}")
            if summary.get("way_reassess_log_path"):
                console.info(
                    f"GameManager: way_reassess → {summary['way_reassess_log_path']}"
                )
            if summary.get("la_lr_probe_log_path"):
                console.info(
                    f"GameManager: la_lr_probe → {summary['la_lr_probe_log_path']}"
                )

        console.info(
            f"GameManager: finished completed={summary['games_completed']}/"
            f"{summary['games_requested']} wall_s={wall:.1f} "
            f"status_counts={summary['status_counts']} "
            f"wins={summary['wins_by_player']}"
        )
        self.last_summary = summary
        return summary


def run_batch(games: int = 1, **kwargs: Any) -> Dict[str, Any]:
    """Module-level convenience wrapper."""
    return GameManager(games=games, **kwargs).run_batch()
