#!/usr/bin/env python3
"""CLI entry for headless all-AI Catan (Phase A single game / Phase B batch).

Uses the same core path as interactive Play / Continue, without a pygame
event loop. Operator flags live in ``core/constants.py``.

Console logging (``core.console``):
    -q / --quiet   → WARN
    (default)      → INFO
    -v / --verbose → DEBUG
    --trace        → TRACE

Examples
--------
    py -3.13 run_headless.py
    py -3.13 run_headless.py --max-round 5 --max-steps 200
    py -3.13 run_headless.py --games 10
    py -3.13 run_headless.py --games 5 --max-round 30 -q

    # Phase C2 matched-dice arms (WP-R6)
    py -3.13 run_headless.py --games 100 --batch-dir batch_runs/lib_ip2 --seed-base 1000
    py -3.13 run_headless.py --games 100 --batch-dir batch_runs/treat_p2 \\
        --dice-from-batch batch_runs/lib_ip2 --arm treat-p2
    py -3.13 run_headless.py --games 10 --explicit-recalc 2=1,2,3,[4,2]

    # Phase L LA soft-bias arms (matched dice vs product_244 / lib_ip2)
    py -3.13 run_headless.py --games 25 --batch-dir batch_runs/la_soft_early \\
        --dice-from-batch batch_runs/lib_ip2 --arm product --la-soft-bias early

Exit codes
----------
    0  single: won or max_round; batch: no stuck/error games
    1  stuck/error (single or any game in batch) or crash
    2  misconfiguration (e.g. human seats without --allow-human)
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

from core import console


def _load_constants():
    from core import constants as C

    return C


def _default_games(C: Any) -> int:
    try:
        return max(1, int(getattr(C, "GAMES_TO_PLAY", 1) or 1))
    except Exception:
        return 1


def _log_flags(C: Any, *, games: int) -> None:
    console.info("=== Headless run — operator flags ===")
    console.info(f"  HUMAN_PLAYER     = {getattr(C, 'HUMAN_PLAYER', None)}")
    console.info(f"  HP_ID            = {getattr(C, 'HP_ID', None)}")
    console.info(f"  NO_GUI_AT_ALL_TF = {getattr(C, 'NO_GUI_AT_ALL_TF', None)}")
    console.info(f"  GAME_MAX_ROUND   = {getattr(C, 'GAME_MAX_ROUND', None)}")
    console.info(f"  GAMES_TO_PLAY    = {getattr(C, 'GAMES_TO_PLAY', None)} (cli games={games})")
    console.info(f"  VICTORY          = {getattr(C, 'VICTORY', None)}")
    console.info(f"  LOAD_PLAYBOARD   = {getattr(C, 'LOAD_PLAYBOARD', None)}")
    console.info(f"  SAVED_PLAYBOARD  = {getattr(C, 'SAVED_PLAYBOARD', None)}")
    console.info(f"  LOAD_GAME        = {getattr(C, 'LOAD_GAME', None)}")
    console.info(f"  CHECK_MODE       = {getattr(C, 'CHECK_MODE', None)}")
    console.info(f"  NUM_PLAYERS      = {getattr(C, 'NUM_PLAYERS', None)}")
    console.info(f"  console level    = {console.level_name()}")
    console.info("====================================")


def _config_warnings(C: Any, *, allow_human: bool) -> List[str]:
    warnings: List[str] = []
    # NO_GUI_AT_ALL_TF must be True for run_headless (hard-checked in main).
    human = bool(getattr(C, "HUMAN_PLAYER", False))
    raw_ids = getattr(C, "HP_ID", None) or []
    if isinstance(raw_ids, (list, tuple, set)):
        ids = list(raw_ids)
    elif raw_ids in (None, ""):
        ids = []
    else:
        ids = [raw_ids]
    if human or ids:
        msg = (
            f"HUMAN_PLAYER={human} HP_ID={ids} — headless expects all-AI "
            "(human discard/TwP panels are not driven)."
        )
        if allow_human:
            warnings.append(msg + " Continuing because --allow-human was set.")
        else:
            warnings.append(msg)
    return warnings


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_headless",
        description=(
            "Run one or more headless all-AI Catan games (IP → Execution → terminal). "
            "Defaults come from core.constants; CLI overrides budgets and batch size."
        ),
    )
    p.add_argument(
        "--games",
        type=int,
        default=None,
        metavar="N",
        help="Number of games in this batch (default: constants.GAMES_TO_PLAY, usually 1)",
    )
    p.add_argument(
        "--sequence",
        type=int,
        default=1,
        help="Sequence number for a single game only (ignored when --games > 1)",
    )
    p.add_argument(
        "--max-round",
        type=int,
        default=None,
        metavar="N",
        help="Stop when round > N (default: constants.GAME_MAX_ROUND)",
    )
    p.add_argument(
        "--max-steps",
        type=int,
        default=None,
        metavar="N",
        help="Safety step budget per game. Default: derived from max-round",
    )
    p.add_argument(
        "--stuck-repeats",
        type=int,
        default=None,
        metavar="N",
        help="Identical-state iterations before status=stuck (default: runner default)",
    )
    p.add_argument(
        "--result-path",
        type=str,
        default=None,
        help="Single-game result.json path (ignored for multi-game batch layout)",
    )
    p.add_argument(
        "--batch-dir",
        type=str,
        default=None,
        help="Batch output directory (default: batch_runs/<timestamp>_batch/)",
    )
    p.add_argument(
        "--no-result-file",
        action="store_true",
        help="Do not write per-game result.json (batch_summary still written if multi)",
    )
    p.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the batch after first stuck/error game",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Console WARN: suppress INFO milestones (warnings/errors only)",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Console DEBUG: IP steps, roll tags, DCard dig-in, …",
    )
    p.add_argument(
        "--trace",
        action="store_true",
        help="Console TRACE: every continue tag (very chatty)",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default=None,
        metavar="LEVEL",
        help="Override console level: TRACE|DEBUG|INFO|WARN|ERROR (or numeric)",
    )
    p.add_argument(
        "--allow-human",
        action="store_true",
        help="Do not abort when HUMAN_PLAYER/HP_ID suggest a human seat",
    )
    p.add_argument(
        "--board-name",
        type=str,
        default="Base_Random",
        help="Board name passed to Game (default: Base_Random; LOAD_PLAYBOARD still applies)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Phase C2 WP-R1: master RNG seed for a single game, or the same seed "
            "for every game in a batch if --seed-base is not set"
        ),
    )
    p.add_argument(
        "--seed-base",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Phase C2 WP-R1: multi-game seeds — game i uses seed N+i-1 "
            "(overrides --seed for batch)"
        ),
    )
    p.add_argument(
        "--dice-from-batch",
        type=str,
        default=None,
        metavar="DIR",
        help=(
            "Phase C2 WP-R2/R6: replay ordered dice_rolls from DIR/g00N/result.json "
            "(same playboard + dice library; longer games extend with true rolls)"
        ),
    )
    p.add_argument(
        "--explicit-recalc",
        action="append",
        default=None,
        metavar="SEAT=SPEC",
        help=(
            "Phase C2 WP-R6: per-seat explicit_142_recalc. Repeatable. "
            "Examples: 2=1,2,3,[4,2]  |  2=dense  |  3=0  |  2=[1,[4,5]]. "
            "Presets: dense, vp, setback, every2, control. "
            "Overrides constants.EXPLICIT_142_RECALC_BY_SEAT for listed seats."
        ),
    )
    p.add_argument(
        "--arm",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Phase C2 WP-R6: named arm preset seat map. "
            "control | treat-p2 | treat-p3 | treat-all. "
            "Merged with --explicit-recalc (CLI seats win)."
        ),
    )
    p.add_argument(
        "--arm-name",
        type=str,
        default=None,
        metavar="LABEL",
        help="Phase C2 WP-R6: free-form arm label stored on batch_summary / result.json",
    )
    p.add_argument(
        "--la-soft-bias",
        type=str,
        default=None,
        metavar="MODE",
        help=(
            "Lab LA soft bias: off | early | mid | late. "
            "Boosts LA Victory-Way rank + tips knight BA when timing gate is open. "
            "Default: constants.LA_SOFT_BIAS_MODE (off)."
        ),
    )
    return p.parse_args(argv)


def _print_single_result(result: Dict[str, Any]) -> None:
    from core.batch.result import STATUS_ERROR, STATUS_STUCK

    status = str(result.get("status") or STATUS_ERROR)
    console.info("=== Headless result ===")
    console.info(f"  status           = {status}")
    console.info(f"  winner_id        = {result.get('winner_id')}")
    console.info(f"  rounds / turn    = {result.get('rounds')} / {result.get('turn')}")
    console.info(f"  steps            = {result.get('steps')}")
    console.info(f"  duration_s       = {result.get('duration_s')}")
    console.info(f"  vp_by_player     = {result.get('vp_by_player')}")
    console.info(f"  lr_holder_id     = {result.get('lr_holder_id')}")
    console.info(f"  la_holder_id     = {result.get('la_holder_id')}")
    console.info(f"  cs_log_path      = {result.get('cs_log_path')}")
    if result.get("result_path"):
        console.info(f"  result_path      = {result.get('result_path')}")
    if result.get("error"):
        if status in (STATUS_STUCK, STATUS_ERROR):
            console.error(f"  error            = {result.get('error')}")
        else:
            console.info(f"  error            = {result.get('error')}")
    console.info("=======================")


def _print_batch_summary(summary: Dict[str, Any]) -> None:
    console.info("=== Batch summary ===")
    console.info(f"  batch_id         = {summary.get('batch_id')}")
    console.info(
        f"  completed        = {summary.get('games_completed')}/"
        f"{summary.get('games_requested')}"
    )
    console.info(f"  status_counts    = {summary.get('status_counts')}")
    console.info(f"  wins_by_player   = {summary.get('wins_by_player')}")
    console.info(f"  duration_s_mean  = {summary.get('duration_s_mean')}")
    console.info(f"  duration_s_wall  = {summary.get('duration_s_wall')}")
    console.info(f"  rounds_mean      = {summary.get('rounds_mean')}")
    console.info(f"  steps_mean       = {summary.get('steps_mean')}")
    console.info(f"  batch_dir        = {summary.get('batch_dir')}")
    if summary.get("batch_summary_path"):
        console.info(f"  batch_summary    = {summary.get('batch_summary_path')}")
    if summary.get("arm_name") or summary.get("arm"):
        console.info(f"  arm_name         = {summary.get('arm_name')}")
        arm = summary.get("arm") if isinstance(summary.get("arm"), dict) else {}
        if arm.get("explicit_142_recalc_by_seat"):
            console.info(
                f"  explicit_recalc  = {arm.get('explicit_142_recalc_by_seat')}"
            )
        if summary.get("dice_from_batch") or arm.get("dice_from_batch"):
            console.info(
                f"  dice_from_batch  = "
                f"{summary.get('dice_from_batch') or arm.get('dice_from_batch')}"
            )
    if summary.get("way_reassess_log_path"):
        console.info(f"  way_reassess     = {summary.get('way_reassess_log_path')}")
    console.info("=====================")


def _exit_code_single(status: str) -> int:
    from core.batch.result import STATUS_ERROR, STATUS_MAX_ROUND, STATUS_STUCK, STATUS_WON

    if status in (STATUS_WON, STATUS_MAX_ROUND):
        return 0
    if status in (STATUS_STUCK, STATUS_ERROR):
        return 1
    return 1


def _exit_code_batch(summary: Dict[str, Any]) -> int:
    from core.batch.result import STATUS_ERROR, STATUS_STUCK

    counts = dict(summary.get("status_counts") or {})
    if int(counts.get(STATUS_ERROR, 0) or 0) > 0:
        return 1
    if int(counts.get(STATUS_STUCK, 0) or 0) > 0:
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    console.configure(
        level=args.log_level,
        quiet=bool(args.quiet),
        verbose=bool(args.verbose),
        trace=bool(args.trace),
        use_env=True,
    )

    try:
        C = _load_constants()
    except Exception as exc:
        console.error(f"could not import core.constants: {exc}")
        return 1

    games = int(args.games) if args.games is not None else _default_games(C)
    games = max(1, games)

    _log_flags(C, games=games)
    for w in _config_warnings(C, allow_human=bool(args.allow_human)):
        console.warn(w)

    # Headless needs mute + quiet digin. Operator owns constants.py —
    # do not silently force NO_GUI_AT_ALL_TF (leave False for main.py).
    if not bool(getattr(C, "NO_GUI_AT_ALL_TF", False)):
        console.error(
            "headless requires NO_GUI_AT_ALL_TF=True in core/constants.py "
            "(False → sounds + noisy digin prints). Set True for batch/lab; "
            "set False again before interactive main.py."
        )
        return 2

    human = bool(getattr(C, "HUMAN_PLAYER", False))
    raw_ids = getattr(C, "HP_ID", None) or []
    if isinstance(raw_ids, (list, tuple, set)):
        has_hp = bool(list(raw_ids))
    else:
        has_hp = raw_ids not in (None, "", [])
    if (human or has_hp) and not args.allow_human:
        console.error(
            "headless all-AI required. Set HUMAN_PLAYER=False and HP_ID=[] "
            "in core/constants.py, or pass --allow-human to override."
        )
        return 2

    from core.batch.result import STATUS_ERROR

    shared_kwargs: Dict[str, Any] = {
        "max_round": args.max_round,
        "max_steps": args.max_steps,
        "board_name": str(args.board_name or "Base_Random"),
    }
    if args.stuck_repeats is not None:
        shared_kwargs["stuck_repeats"] = int(args.stuck_repeats)

    # WP-R1 seeds
    seed = int(args.seed) if args.seed is not None else None
    seed_base = int(args.seed_base) if args.seed_base is not None else None
    if seed is not None or seed_base is not None:
        console.info(
            f"  seed / seed_base  = {seed} / {seed_base}"
        )
    dice_from_batch = str(args.dice_from_batch).strip() if args.dice_from_batch else None
    if dice_from_batch:
        console.info(f"  dice_from_batch  = {dice_from_batch}")

    # WP-R6: resolve experiment arm (explicit_142_recalc + metadata)
    arm_config: Dict[str, Any] = {}
    try:
        from core.batch.arm_config import resolve_arm_config

        tokens = list(args.explicit_recalc or [])
        arm_config = resolve_arm_config(
            arm=args.arm,
            explicit_recalc_tokens=tokens,
            dice_from_batch=dice_from_batch,
            seed=seed,
            seed_base=seed_base,
            arm_name=args.arm_name,
        )
        for err in arm_config.get("errors") or []:
            console.warn(f"arm config: {err}")
        if arm_config.get("arm_name") or tokens or args.arm:
            console.info(f"  arm_name         = {arm_config.get('arm_name')}")
            console.info(
                f"  explicit_recalc  = {arm_config.get('explicit_142_recalc_by_seat')}"
            )
            console.info(f"  arm_source       = {arm_config.get('source')}")
    except Exception as exc:
        console.warn(f"arm config failed: {exc}")
        arm_config = {}

    seat_map = arm_config.get("seat_map") if arm_config else None
    # Only pass seat map when CLI/arm actually set something (else constants apply)
    pass_seat_map = None
    if args.arm or args.explicit_recalc or args.arm_name:
        pass_seat_map = seat_map or arm_config.get("explicit_142_recalc_by_seat")
    arm_name = arm_config.get("arm_name") if arm_config else None
    la_soft_bias = str(args.la_soft_bias).strip() if args.la_soft_bias else None
    if la_soft_bias:
        console.info(f"  la_soft_bias     = {la_soft_bias}")

    # ── Phase B: multi-game ──────────────────────────────────────────
    if games > 1:
        from core.batch.game_manager import GameManager

        console.info(
            f"Starting GameManager (games={games}, "
            f"max_round={shared_kwargs['max_round']}, "
            f"max_steps={shared_kwargs['max_steps']}) …"
        )
        try:
            summary = GameManager(
                games=games,
                write_result_files=not bool(args.no_result_file),
                write_batch_summary_file=True,
                batch_dir=args.batch_dir,
                stop_on_error=bool(args.stop_on_error),
                seed=seed,
                seed_base=seed_base,
                dice_from_batch=dice_from_batch,
                explicit_142_recalc_by_seat=pass_seat_map,
                arm_name=arm_name,
                arm_config=arm_config,
                la_soft_bias=la_soft_bias,
                **shared_kwargs,
            ).run_batch()
        except Exception as exc:
            console.error(f"batch crashed: {exc}")
            import traceback

            console.debug(traceback.format_exc())
            return 1

        _print_batch_summary(summary)
        return _exit_code_batch(summary)

    # ── Phase A: single game ─────────────────────────────────────────
    from core.batch.headless_runner import HeadlessGameRunner

    # Single game: --seed-base with sequence → seed_base+seq-1; else --seed
    single_seed = seed
    if seed_base is not None:
        single_seed = int(seed_base) + int(args.sequence) - 1
    # Optional dice script from batch library for this sequence
    dice_rolls = None
    if dice_from_batch:
        try:
            from core.dice_script import load_dice_library_from_batch

            lib = load_dice_library_from_batch(dice_from_batch)
            info = (lib.get("scripts") or {}).get(int(args.sequence))
            if info and info.get("dice_rolls"):
                dice_rolls = list(info["dice_rolls"])
                if single_seed is None and info.get("seed") is not None:
                    single_seed = int(info["seed"])
                console.info(
                    f"  dice script       = {len(dice_rolls)} rolls "
                    f"(seq={args.sequence} from {dice_from_batch})"
                )
        except Exception as exc:
            console.warn(f"dice-from-batch failed: {exc}")
    runner_kwargs: Dict[str, Any] = {
        "sequence_number": int(args.sequence),
        "write_result_file": not bool(args.no_result_file),
        "result_path": args.result_path,
        "verbose": True,
        "seed": single_seed,
        "dice_rolls": dice_rolls,
        "explicit_142_recalc_by_seat": pass_seat_map,
        "arm_name": arm_name,
        "la_soft_bias": la_soft_bias,
        **shared_kwargs,
    }
    console.info(
        f"Starting HeadlessGameRunner "
        f"(sequence={runner_kwargs['sequence_number']}, "
        f"max_round={runner_kwargs['max_round']}, "
        f"max_steps={runner_kwargs['max_steps']}, "
        f"seed={single_seed}, arm={arm_name}) …"
    )
    try:
        result = HeadlessGameRunner(**runner_kwargs).run_one()
    except Exception as exc:
        console.error(f"runner crashed: {exc}")
        import traceback

        console.debug(traceback.format_exc())
        return 1

    _print_single_result(result)
    status = str(result.get("status") or STATUS_ERROR)
    return _exit_code_single(status)


if __name__ == "__main__":
    sys.exit(main())
