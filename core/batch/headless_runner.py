"""Headless single-game runner (Phase A WP3).

Drives one all-AI match from Initial Placement through Execution using the same
core APIs as interactive Play / Continue:

  - ``InitialPlacement.advance_turn`` (AI placements)
  - ``Game.ai_roll_to_preview``
  - ``Game.continue_ai_execution_turn``

No pygame event loop. Attach ``NullGui`` and respect ``NO_GUI_AT_ALL_TF``.
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from core.batch.null_gui import NullGui, is_gui_presentation_enabled
from core.batch.result import (
    STATUS_ERROR,
    STATUS_MAX_ROUND,
    STATUS_STUCK,
    STATUS_WON,
    build_and_write_result,
    build_result,
    default_result_path,
)
from core import console

# Default safety budgets when constants.GAME_MAX_ROUND is used for rounds.
_DEFAULT_MAX_STEPS_FACTOR = 80  # steps ≈ rounds * 4 seats * continues-per-seat
_DEFAULT_STUCK_REPEATS = 12
_PROGRESS_LOG_EVERY = 25


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _game_fingerprint(game: Any) -> Tuple[Any, ...]:
    """Compact state signature for stuck detection."""
    dice = getattr(game, "dice_roll", None)
    if isinstance(dice, (list, tuple)):
        dice_key = tuple(dice)
    else:
        dice_key = dice
    queue = getattr(game, "pending_discard_queue", None) or []
    try:
        qlen = len(list(queue))
    except Exception:
        qlen = -1
    ba = getattr(game, "current_best_action", None)
    ba_action = None
    if isinstance(ba, dict):
        ba_action = ba.get("action")
    return (
        str(getattr(game, "phase", "") or ""),
        _safe_int(getattr(game, "round", 0)),
        _safe_int(getattr(game, "turn", 0)),
        str(getattr(game, "state", "") or ""),
        dice_key,
        bool(getattr(game, "game_over", False)),
        qlen,
        str(ba_action or ""),
        str(getattr(game, "ai_execution_stage", "") or ""),
    )


def _needs_roll(game: Any) -> bool:
    if str(getattr(game, "phase", "") or "") != "Execution":
        return False
    if bool(getattr(game, "game_over", False)):
        return False
    state = str(getattr(game, "state", "") or "")
    if state == "AwaitingDiceRoll":
        return True
    try:
        if not game._dice_has_been_rolled_for_execution():
            return True
    except Exception:
        dice = getattr(game, "dice_roll", None)
        if dice in (None, 0, "", []):
            return True
    return False


def _try_discard_pump(game: Any) -> Dict[str, Any]:
    """Last-chance all-AI discard processing when Continue is blocked."""
    try:
        from core.game_7logic import process_discard_queue

        return dict(
            process_discard_queue(game, open_human_panel=False) or {}
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class HeadlessGameRunner:
    """Run one full (or capped) headless AI game to a terminal status."""

    def __init__(
        self,
        *,
        sequence_number: int = 1,
        max_round: Optional[int] = None,
        max_steps: Optional[int] = None,
        stuck_repeats: int = _DEFAULT_STUCK_REPEATS,
        progress_every: int = _PROGRESS_LOG_EVERY,
        write_result_file: bool = True,
        result_path: Optional[Union[str, Path]] = None,
        board_name: str = "Base_Random",
        verbose: bool = True,
        log_level: Optional[Union[str, int]] = None,
        batch_id: Optional[str] = None,
        cs_log_path: Optional[Union[str, Path]] = None,
        mglog_path: Optional[Union[str, Path]] = None,
        seed: Optional[int] = None,
        dice_rolls: Optional[Any] = None,
        explicit_142_recalc_by_seat: Optional[Any] = None,
        arm_name: Optional[str] = None,
        la_soft_bias: Optional[str] = None,
        sidestep_s142_drive: Optional[bool] = None,
        perf_mode: Optional[str] = None,
    ) -> None:
        self.sequence_number = int(sequence_number)
        self.max_round_override = max_round
        self.max_steps_override = max_steps
        self.stuck_repeats = max(3, int(stuck_repeats))
        self.progress_every = max(0, int(progress_every))
        self.write_result_file = bool(write_result_file)
        self.result_path = result_path
        self.board_name = str(board_name or "Base_Random")
        # Phase C WP-C4: batch isolation for CS log + row batch_id
        self.batch_id = str(batch_id).strip() if batch_id else None
        self.cs_log_path = str(cs_log_path) if cs_log_path else None
        # MGlog M7: per-game CSV (batch_dir/g00N/mglog.csv)
        self.mglog_path = str(mglog_path) if mglog_path else None
        # Phase C2 WP-R1: optional master RNG seed for this game
        try:
            self.seed = int(seed) if seed is not None else None
        except Exception:
            self.seed = None
        # Phase C2 WP-R2: optional ordered dice script for replay
        self.dice_rolls_script = dice_rolls
        # Phase C2 WP-R6: per-arm seat map override (after Game defaults)
        self.explicit_142_recalc_by_seat = explicit_142_recalc_by_seat
        self.arm_name = str(arm_name).strip() if arm_name else None
        # Lab LA soft bias: off | early | mid | late
        self.la_soft_bias = str(la_soft_bias).strip() if la_soft_bias else None
        self.sidestep_s142_drive = (
            bool(sidestep_s142_drive) if sidestep_s142_drive is not None else None
        )
        self.perf_mode = str(perf_mode).strip() if perf_mode else None
        # Backward-compatible: verbose=False ≈ quieter (WARN) if log_level unset
        # and process threshold was not already configured by CLI.
        self.verbose = bool(verbose)
        if log_level is not None:
            console.set_level(log_level)
        elif not self.verbose and console.get_level() <= console.INFO:
            # Only tighten if still at default-ish INFO; do not override TRACE/DEBUG
            console.set_level(console.WARN)

        self.game: Any = None
        self.steps: int = 0
        self.last_fingerprint: Optional[Tuple[Any, ...]] = None
        self.fingerprint_hits: int = 0

    def _log(self, msg: str, *, level: int = console.INFO) -> None:
        """Emit a runner message at ``level`` (default INFO)."""
        console.log(level, msg)

    def _resolved_mglog_path(self) -> Optional[str]:
        """Per-game mglog.csv path: explicit kw, else next to result.json."""
        if self.mglog_path:
            return str(self.mglog_path)
        if self.result_path:
            try:
                return str(Path(self.result_path).parent / "mglog.csv")
            except Exception:
                return None
        return None

    def _artifact_dir(self) -> Optional[Path]:
        """Per-game folder for mglog / result / playboard (batch g00N or single result parent)."""
        for raw in (self.mglog_path, self.result_path):
            if not raw:
                continue
            try:
                p = Path(raw)
                parent = p.parent if p.suffix else p
                if parent and str(parent) not in (".", ""):
                    return parent
            except Exception:
                continue
        return None

    def _playboard_dest_path(self) -> Optional[Path]:
        """Canonical re-play map path: ``Playboard_gNNN.txt`` under the game artifact dir.

        Must use a Playboard/PlayBoard prefix so ``Board.load_board`` accepts it.
        """
        adir = self._artifact_dir()
        if adir is None:
            return None
        seq = max(1, int(self.sequence_number or 1))
        return adir / f"Playboard_g{seq:03d}.txt"

    def _save_playboard_for_replay(self, game: Any) -> Optional[str]:
        """Write the actual map used this game next to mglog/result for MGlog re-play.

        Works for both random boards (``LOAD_PLAYBOARD=False``) and fixed
        ``SAVED_PLAYBOARD`` loads — re-exports current ``game.board`` so
        ``g00N/`` is self-contained. Returns absolute path or None.
        """
        dest = self._playboard_dest_path()
        if dest is None:
            return None
        board = getattr(game, "board", None)
        if board is None or not hasattr(board, "save_board"):
            return None
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            written = board.save_board(str(dest))
            path = Path(written or dest)
            if not path.is_file():
                # save_board may return relative path; prefer dest if written there
                if dest.is_file():
                    path = dest
                else:
                    return None
            try:
                resolved = str(path.resolve())
            except Exception:
                resolved = str(path)
            try:
                game.playboard_path = resolved
            except Exception:
                pass
            self._log(f"headless: playboard saved → {resolved}", level=console.INFO)
            return resolved
        except Exception as exc:
            self._log(
                f"headless: playboard save failed: {exc}",
                level=console.WARN,
            )
            return None

    def _resolve_max_round(self) -> int:
        if self.max_round_override is not None:
            return max(1, int(self.max_round_override))
        try:
            from core.constants import GAME_MAX_ROUND

            return max(1, int(GAME_MAX_ROUND or 50))
        except Exception:
            return 50

    def _resolve_max_steps(self, max_round: int) -> int:
        if self.max_steps_override is not None:
            return max(1, int(self.max_steps_override))
        # seats * continues * rounds, generous buffer
        return max(200, int(max_round) * 4 * _DEFAULT_MAX_STEPS_FACTOR)

    def _create_game(self) -> Any:
        from core.game import Game
        from core.initial_placement_phase_manager import InitialPlacement

        today = datetime.now().strftime("%Y%m%d_%H%M%S")
        game = Game(
            sequence_number=self.sequence_number,
            id_=today,
            phase="InitialPlacement",
            state="None",
            state_1="0",
            state_2="0",
            myplayers=None,
            board_name=self.board_name,
            seed=self.seed,
        )
        gui = NullGui(round_number=game.round, turn=game.turn, game=game)
        game.gui = gui
        game.ip = InitialPlacement(game)
        # WP-C4: stamp batch identity for CS rows + result.json
        if self.batch_id:
            try:
                game.batch_id = self.batch_id
            except Exception:
                pass
        if self.cs_log_path:
            try:
                game.cs_log_path = self.cs_log_path
            except Exception:
                pass
            try:
                from core.strategy_cs_log import set_cs_log_path

                set_cs_log_path(self.cs_log_path)
            except Exception:
                pass
        # MGlog M7: stamp path on Game for result.json pointer
        mg_path = self._resolved_mglog_path()
        if mg_path:
            try:
                game.mglog_path = str(mg_path)
            except Exception:
                pass
        # WP-R4: stamp way-reassess log path (process override from GameManager or default)
        try:
            from core.way_reassess_log import (
                get_way_reassess_log_path_override,
                way_reassess_log_path,
            )

            wr = get_way_reassess_log_path_override() or way_reassess_log_path()
            game.way_reassess_log_path = str(wr) if wr else None
        except Exception:
            pass
        # Phase L WP-L1: LA/LR god-view probe path
        try:
            from core.la_lr_probe_log import (
                get_la_lr_probe_log_path_override,
                la_lr_probe_log_path,
            )

            lp = get_la_lr_probe_log_path_override() or la_lr_probe_log_path()
            game.la_lr_probe_log_path = str(lp) if lp else None
        except Exception:
            pass
        # Lab LA soft bias timing mode (CLI overrides constants)
        try:
            from core.la_soft_bias import set_la_soft_bias_mode
            from core import constants as C

            mode = self.la_soft_bias
            if not mode:
                mode = getattr(C, "LA_SOFT_BIAS_MODE", "off")
            set_la_soft_bias_mode(game, mode)
        except Exception:
            pass
        if self.seed is not None:
            self._log(
                f"headless: game seed={self.seed} sequence={self.sequence_number}",
                level=console.DEBUG,
            )
        # Sidestep S142 drive arm (headless lab)
        try:
            drive = self.sidestep_s142_drive
            if drive is None and self.arm_name:
                if str(self.arm_name).lower().replace("_", "-") in (
                    "s142-drive",
                    "s142drive",
                ):
                    drive = True
            if drive:
                game.sidestep_s142_drive = True
                self._log("headless: SIDESTEP_S142_DRIVE on", level=console.INFO)
        except Exception:
            pass
        # Performance dig pack (lean vs full) — stamp game attrs
        try:
            if self.perf_mode:
                from core.batch.perf_mode import apply_perf_mode_to_game

                apply_perf_mode_to_game(game, self.perf_mode)
                self._log(
                    f"headless: perf_mode={self.perf_mode}",
                    level=console.INFO,
                )
        except Exception as exc:
            self._log(f"headless: perf_mode apply failed: {exc}", level=console.WARN)
        # WP-R6: override per-seat explicit_142_recalc (CLI / arm) after Game defaults
        if self.explicit_142_recalc_by_seat is not None:
            try:
                from core.batch.arm_config import apply_arm_to_players

                apply_arm_to_players(
                    getattr(game, "players", None) or [],
                    self.explicit_142_recalc_by_seat,
                    warn=False,
                )
                try:
                    game.explicit_142_recalc_by_seat = dict(
                        self.explicit_142_recalc_by_seat
                    )
                except Exception:
                    pass
                if self.arm_name:
                    try:
                        game.arm_name = self.arm_name
                    except Exception:
                        pass
                self._log(
                    f"headless: arm explicit_142_recalc seats="
                    f"{sorted(int(k) for k in dict(self.explicit_142_recalc_by_seat).keys())}"
                    f" arm={self.arm_name or '-'}",
                    level=console.INFO,
                )
            except Exception as exc:
                self._log(
                    f"headless: explicit_142_recalc apply failed: {exc}",
                    level=console.WARN,
                )
        # WP-R2: install dice script for replay (or constants file if enabled)
        try:
            n_script = 0
            if self.dice_rolls_script is not None:
                n_script = int(game.set_dice_script(self.dice_rolls_script) or 0)
            else:
                try:
                    from core.constants import DICEROLL_SET_TF, NAME_DR_FILE

                    if bool(DICEROLL_SET_TF) and NAME_DR_FILE:
                        from core.dice_script import load_dice_list_from_file

                        file_rolls = load_dice_list_from_file(NAME_DR_FILE)
                        if file_rolls:
                            n_script = int(game.set_dice_script(file_rolls) or 0)
                except Exception:
                    pass
            if n_script:
                self._log(
                    f"headless: dice script length={n_script} sequence={self.sequence_number}",
                    level=console.INFO,
                )
        except Exception:
            pass
        return game

    def _ensure_execution_ready(self, game: Any) -> None:
        if str(getattr(game, "phase", "") or "") != "Execution":
            return
        # Clear accidental game_over from legacy IP handoff if still present
        # without a winner.
        if bool(getattr(game, "game_over", False)) and getattr(game, "winner", None) is None:
            wr = getattr(game, "win_result", None)
            if not wr:
                game.game_over = False
        state = str(getattr(game, "state", "") or "")
        if state in ("", "None", "0") or state == "AwaitingDiceRoll":
            try:
                if getattr(game, "current_viable_action_scan", None) is None:
                    game.begin_execution_turn()
            except Exception:
                try:
                    game.begin_execution_turn()
                except Exception as exc:
                    self._log(
                        f"headless: begin_execution_turn failed: {exc}",
                        level=console.WARN,
                    )

    def _run_initial_placement(self, game: Any, max_steps: int) -> Optional[str]:
        """Run IP to completion. Returns error string or None."""
        ip = getattr(game, "ip", None)
        if ip is None:
            return "no_initial_placement_manager"
        try:
            ip.run()
        except Exception as exc:
            return f"ip.run failed: {exc}"

        ip_guard = 0
        max_ip_steps = max(20, 4 * 4 + 5)  # 4p * 2 placements + slack
        while str(getattr(game, "phase", "") or "") == "InitialPlacement":
            ip_guard += 1
            self.steps += 1
            if ip_guard > max_ip_steps or self.steps > max_steps:
                return "ip_stuck_or_step_budget"
            try:
                ip.advance_turn()
            except Exception as exc:
                return f"ip.advance_turn failed: {exc}"
            self._log(
                f"headless IP step={ip_guard} phase={game.phase} "
                f"R{getattr(game, 'round', '?')}T{getattr(game, 'turn', '?')}",
                level=console.DEBUG,
            )

        if str(getattr(game, "phase", "") or "") != "Execution":
            return f"expected Execution after IP, got {getattr(game, 'phase', None)!r}"
        self._ensure_execution_ready(game)
        return None

    def _check_terminals(
        self,
        game: Any,
        *,
        max_round: int,
        max_steps: int,
    ) -> Optional[Tuple[str, Optional[str]]]:
        """Return (status, error_note) if terminal, else None."""
        if bool(getattr(game, "game_over", False)):
            if getattr(game, "winner", None) is not None or getattr(game, "win_result", None):
                return STATUS_WON, None
            # game_over without winner — treat as won if win path set, else stuck
            return STATUS_WON, "game_over_without_explicit_winner"

        rnd = _safe_int(getattr(game, "round", 0))
        if rnd > max_round:
            return STATUS_MAX_ROUND, f"round {rnd} > max_round {max_round}"

        if self.steps >= max_steps:
            return STATUS_STUCK, f"max_steps {max_steps} exceeded"

        fp = _game_fingerprint(game)
        if fp == self.last_fingerprint:
            self.fingerprint_hits += 1
        else:
            self.last_fingerprint = fp
            self.fingerprint_hits = 1
        if self.fingerprint_hits >= self.stuck_repeats:
            return STATUS_STUCK, f"fingerprint repeated {self.fingerprint_hits}x: {fp}"

        return None

    def _execution_step(self, game: Any) -> str:
        """Perform one roll or continue (or discard pump). Returns action tag."""
        if _needs_roll(game):
            result = game.ai_roll_to_preview()
            ok = bool(result.get("ok")) if isinstance(result, dict) else False
            return f"roll ok={ok}"

        try:
            can_continue = bool(game._ai_continue_logic_available())
        except Exception:
            can_continue = False

        if can_continue:
            result = game.continue_ai_execution_turn()
            ok = bool(result.get("ok")) if isinstance(result, dict) else False
            adv = bool(result.get("advance_turn")) if isinstance(result, dict) else False
            act = ""
            if isinstance(result, dict):
                er = result.get("executed_result") or {}
                if isinstance(er, dict):
                    act = str(er.get("action") or "")
            return f"continue ok={ok} adv={adv} act={act}"

        # Continue blocked — try discard pump (all-AI)
        disc = _try_discard_pump(game)
        if disc.get("robber_ready") or disc.get("executed"):
            return f"discard_pump {disc.get('robber_ready')}"

        # Still blocked
        return "blocked"

    def run_one(self) -> Dict[str, Any]:
        """Run one game; return result dict (and optionally write result.json)."""
        t0 = time.perf_counter()
        self.steps = 0
        self.last_fingerprint = None
        self.fingerprint_hits = 0
        max_round = self._resolve_max_round()
        max_steps = self._resolve_max_steps(max_round)
        status = STATUS_ERROR
        error: Optional[str] = None
        game: Any = None
        prev_mglog_override: Optional[str] = None
        mg_path = self._resolved_mglog_path()

        try:
            # MGlog M7: isolate per-game CSV before any IP/execution mutations
            if mg_path:
                try:
                    from core import mglog as _mglog

                    prev_mglog_override = _mglog.begin_game_mglog(mg_path)
                except Exception:
                    prev_mglog_override = None

            # Soft check: presentation should be off for true headless
            if is_gui_presentation_enabled():
                self._log(
                    "headless: presentation still enabled after lab setup; "
                    "runner uses NullGui anyway.",
                    level=console.WARN,
                )

            game = self._create_game()
            self.game = game
            # Snapshot map into g00N (or result parent) for MGlog re-play
            pb_path = self._save_playboard_for_replay(game)
            self._log(
                f"headless: start sequence={self.sequence_number} "
                f"max_round={max_round} max_steps={max_steps} "
                f"gui={type(game.gui).__name__} log={console.level_name()}"
                + (f" mglog={mg_path}" if mg_path else "")
                + (f" playboard={pb_path}" if pb_path else "")
            )

            ip_err = self._run_initial_placement(game, max_steps=max_steps)
            if ip_err:
                status = STATUS_ERROR
                error = ip_err
                self._log(f"headless: IP failed — {ip_err}", level=console.ERROR)
            else:
                self._log(
                    f"headless: IP done → Execution "
                    f"R{game.round}T{game.turn} state={game.state}"
                )
                while True:
                    term = self._check_terminals(
                        game, max_round=max_round, max_steps=max_steps
                    )
                    if term is not None:
                        status, error = term
                        break

                    self.steps += 1
                    try:
                        tag = self._execution_step(game)
                    except Exception as exc:
                        status = STATUS_ERROR
                        error = f"execution_step failed: {exc}"
                        self._log(error, level=console.ERROR)
                        self._log(traceback.format_exc(), level=console.DEBUG)
                        break

                    if tag == "blocked":
                        # One more terminal check after discard failure
                        term = self._check_terminals(
                            game, max_round=max_round, max_steps=max_steps
                        )
                        if term is not None:
                            status, error = term
                            break
                        # Force stuck if still blocked
                        if self.fingerprint_hits >= max(3, self.stuck_repeats // 2):
                            status = STATUS_STUCK
                            error = (
                                f"continue_blocked state={getattr(game, 'state', None)} "
                                f"dice={getattr(game, 'dice_roll', None)}"
                            )
                            break

                    if self.progress_every and self.steps % self.progress_every == 0:
                        self._log(
                            f"headless: steps={self.steps} "
                            f"R{getattr(game, 'round', '?')}T{getattr(game, 'turn', '?')} "
                            f"state={getattr(game, 'state', '?')} {tag}"
                        )
                    elif tag.startswith("roll"):
                        self._log(
                            f"headless: steps={self.steps} "
                            f"R{getattr(game, 'round', '?')}T{getattr(game, 'turn', '?')} "
                            f"{tag}",
                            level=console.DEBUG,
                        )
                    else:
                        self._log(
                            f"headless: steps={self.steps} {tag}",
                            level=console.TRACE,
                        )

                    # Win can happen mid-continue
                    if bool(getattr(game, "game_over", False)):
                        status = STATUS_WON
                        error = None
                        break

        except Exception as exc:
            status = STATUS_ERROR
            error = f"run_one failed: {exc}"
            self._log(error, level=console.ERROR)
            self._log(traceback.format_exc(), level=console.DEBUG)

        duration_s = time.perf_counter() - t0
        finish_level = console.INFO
        if status in (STATUS_STUCK, STATUS_ERROR):
            finish_level = console.ERROR
        self._log(
            f"headless: finished status={status} steps={self.steps} "
            f"duration_s={duration_s:.2f} error={error}",
            level=finish_level,
        )

        try:
            kwargs = dict(
                status=status,
                steps=self.steps,
                duration_s=duration_s,
                error=error,
                sequence_number=self.sequence_number,
            )
            if self.write_result_file:
                path = self.result_path
                if path is None:
                    path = default_result_path(
                        sequence_number=self.sequence_number,
                        game_id=str(getattr(game, "id", "") or ""),
                    )
                result = build_and_write_result(game, path=path, **kwargs)
            else:
                result = build_result(game, **kwargs)
            # Always expose mglog / playboard pointers when known
            dirty = False
            if mg_path and not result.get("mglog_path"):
                try:
                    result["mglog_path"] = str(Path(mg_path).resolve())
                except Exception:
                    result["mglog_path"] = str(mg_path)
                dirty = True
            pb_from_game = None
            try:
                pb_from_game = getattr(game, "playboard_path", None) if game else None
            except Exception:
                pb_from_game = None
            if pb_from_game and not result.get("playboard_path"):
                try:
                    result["playboard_path"] = str(Path(str(pb_from_game)).resolve())
                except Exception:
                    result["playboard_path"] = str(pb_from_game)
                dirty = True
            if dirty and self.write_result_file and result.get("result_path"):
                try:
                    from core.batch.result import write_result

                    write_result(result["result_path"], result)
                except Exception:
                    pass
            return result
        finally:
            if mg_path:
                try:
                    from core import mglog as _mglog

                    _mglog.end_game_mglog(prev_mglog_override)
                except Exception:
                    pass


def run_one_headless_game(**kwargs: Any) -> Dict[str, Any]:
    """Module-level convenience wrapper."""
    return HeadlessGameRunner(**kwargs).run_one()
