#!/usr/bin/env python3
"""M-GUI: Catan re-play — playboard + MGlog, no Strategy-Engine.

Usage (from project root)::

  py -3.13 replay_catan_game.py --playboard "PlayBoard ….txt" --mglog path/mglog.csv
  py -3.13 replay_catan_game.py --game-dir batch_runs/exp/g001
  py -3.13 replay_catan_game.py --mglog path/mglog.csv --check-only

SE Dig (enriched dense MGlog)::

  py -3.13 replay_catan_game.py --playboard P.txt --dig \\
    --mglog-cs batch/cs_annot/g001/mglog_cs.csv --cat2 311,312

G2–G7 / R / F re-play chrome. SE Dig: ``docs/CS_mglog_se_dig_implementation_plan.md``.
Plan: ``docs/MGlog_replay_gui_plan.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _project_root() -> Path:
    """Repo root = directory containing this script (lives next to ``main.py``)."""
    return Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Re-play a Catan game from playboard + MGlog (no SE).",
    )
    p.add_argument("--playboard", type=str, default="", help="Playboard .txt path")
    p.add_argument("--mglog", type=str, default="", help="MGlog CSV path")
    p.add_argument(
        "--game-dir",
        type=str,
        default="",
        help="Batch game folder (g00N) with mglog.csv / result.json",
    )
    p.add_argument(
        "--result",
        type=str,
        default="",
        help="Optional result.json (may contain mglog_path)",
    )
    p.add_argument(
        "--check-only",
        action="store_true",
        help="Validate inputs + load session; print status and exit (no GUI)",
    )
    p.add_argument(
        "--start-at-end",
        action="store_true",
        help="After load, jump cursor to last event",
    )
    # SE Dig (SE5+)
    p.add_argument(
        "--dig",
        action="store_true",
        help="Enable SE Dig mode (probe hits + SE Dig panel). Use with --mglog-cs.",
    )
    p.add_argument(
        "--mglog-cs",
        type=str,
        default="",
        help="Enriched dense MGlog (cs_annot/g00N/mglog_cs.csv). Implies dig load path.",
    )
    p.add_argument(
        "--cat1",
        type=str,
        default="",
        help="Probe cat1 filter (XOR with cat2), e.g. 2,3",
    )
    p.add_argument(
        "--cat2",
        type=str,
        default="",
        help="Probe cat2 filter (XOR with cat1), e.g. 311,312",
    )
    return p


def resolve_paths(args: argparse.Namespace) -> Tuple[Optional[Path], Optional[Path], List[str]]:
    """Return (playboard, mglog, notes). Either path may be None if unresolved.

    Dig mode: ``--mglog-cs`` (or dig + game-dir/cs_annot) becomes the session MGlog.
    """
    notes: List[str] = []
    pb: Optional[Path] = Path(args.playboard) if args.playboard else None
    mg: Optional[Path] = Path(args.mglog) if args.mglog else None
    root = _project_root()

    # Prefer enriched file for dig
    if getattr(args, "mglog_cs", None):
        cs_mg = Path(args.mglog_cs)
        if cs_mg.is_file():
            mg = cs_mg
            notes.append(f"dig MGlog (enriched): {cs_mg}")
        else:
            notes.append(f"WARNING: --mglog-cs not found: {cs_mg}")

    if args.game_dir:
        gdir = Path(args.game_dir)
        if gdir.is_dir():
            # Dig: prefer cs_annot under batch parent
            if getattr(args, "dig", False) and mg is None:
                annot = gdir.parent / "cs_annot" / gdir.name / "mglog_cs.csv"
                if annot.is_file():
                    mg = annot
                    notes.append(f"dig MGlog from cs_annot: {annot}")
            cand = gdir / "mglog.csv"
            if cand.is_file() and mg is None:
                mg = cand
                notes.append(f"mglog from game-dir: {cand}")
            # Per-game map: Playboard_gNNN.txt or any Playboard*/PlayBoard* in folder
            if pb is None:
                preferred = sorted(gdir.glob("Playboard_g*.txt")) + sorted(
                    gdir.glob("PlayBoard_g*.txt")
                )
                if preferred:
                    pb = preferred[0]
                    notes.append(f"playboard from game-dir: {pb}")
                else:
                    others = (
                        sorted(gdir.glob("Playboard*.txt"))
                        + sorted(gdir.glob("PlayBoard*.txt"))
                        + sorted(gdir.glob("PlayBoard *.txt"))
                    )
                    if others:
                        pb = others[0]
                        notes.append(f"playboard from game-dir: {pb}")
            res = gdir / "result.json"
            if res.is_file():
                try:
                    data = json.loads(res.read_text(encoding="utf-8"))
                    if mg is None and data.get("mglog_path"):
                        mp = Path(data["mglog_path"])
                        if mp.is_file():
                            mg = mp
                            notes.append(f"mglog from result.json: {mp}")
                    if pb is None and data.get("playboard_path"):
                        pp = Path(data["playboard_path"])
                        if pp.is_file():
                            pb = pp
                            notes.append(f"playboard from result.json: {pp}")
                except Exception as exc:
                    notes.append(f"result.json read warning: {exc}")
        else:
            notes.append(f"game-dir not found: {gdir}")

    if args.result:
        try:
            data = json.loads(Path(args.result).read_text(encoding="utf-8"))
            if mg is None and data.get("mglog_path") and Path(data["mglog_path"]).is_file():
                mg = Path(data["mglog_path"])
                notes.append(f"mglog from --result: {mg}")
            if pb is None and data.get("playboard_path") and Path(data["playboard_path"]).is_file():
                pb = Path(data["playboard_path"])
                notes.append(f"playboard from --result: {pb}")
        except Exception as exc:
            notes.append(f"--result warning: {exc}")

    # Default playboard from constants (last resort)
    if pb is None:
        try:
            from core import constants as C

            name = str(getattr(C, "SAVED_PLAYBOARD", "") or "")
            if name:
                for cand in (root / name, Path(name)):
                    if cand.is_file():
                        pb = cand
                        notes.append(f"playboard from constants.SAVED_PLAYBOARD: {cand}")
                        break
        except Exception:
            pass

    return pb, mg, notes


def print_load_report(session: Any, notes: Optional[List[str]] = None) -> None:
    print("=== replay_catan_game ===")
    if notes:
        for n in notes:
            print(f"  note: {n}")
    print(f"  playboard = {session.playboard_path}")
    print(f"  mglog     = {session.mglog_path}")
    print(f"  load_ok   = {session.load_ok}")
    if session.input_validation.errors:
        for e in session.input_validation.errors:
            print(f"  ERROR: {e}")
    for e in session.load_errors:
        print(f"  ERROR: {e}")
    c = session.completeness
    print(f"  events    = {session.n_events}")
    print(f"  starts_ok = {c.starts_ok} ({c.start_reason})")
    print(f"  ends_ok   = {c.ends_ok} ({c.end_reason})")
    print(f"  complete  = {c.complete}")
    print(f"  banner    = {c.banner}")
    if session.load_ok and session.n_events:
        st = session.state
        print(
            f"  cursor    = {st.cursor}/{session.last_index}  "
            f"R{st.round}T{st.turn}  phase={st.phase}  "
            f"event={st.last_event}  game_over={st.game_over}"
        )


def run_check_only(session: Any, notes: List[str]) -> int:
    print_load_report(session, notes)
    if not session.input_validation.ok or not session.load_ok:
        return 2
    if not session.completeness.complete:
        return 1  # loaded but incomplete
    return 0


def _banner_color(complete: bool, starts_ok: bool) -> tuple:
    if complete:
        return (40, 120, 60)  # green-ish
    if starts_ok:
        return (160, 100, 20)  # amber
    return (160, 40, 40)  # red


def run_gui(session: Any, dig_cfg: Optional[Dict[str, Any]] = None) -> int:
    """Pygame re-play: G3–G7 + R2/R3 chrome (+ optional SE Dig).

    Mouse only for nav / GO / “?” / Events wheel (v1 Q1: no keyboard controls).
    Dig mode also accepts keyboard for cat1/cat2 text fields.
    Window close (QUIT) exits.
    """
    import pygame

    pygame.init()
    # Display first (importing WIN calls set_mode). Mixer must be (re)inited
    # *after* that on some Windows setups or Sound.play is a no-op/silent.
    from gui.gui_constants import WIN, COLORS, LEFT_DICE_PANEL_RECT, ensure_replay_audio

    dig_on = bool(dig_cfg and dig_cfg.get("enabled"))
    pygame.display.set_caption(
        "Catan re-play (MGlog) — SE Dig" if dig_on else "Catan re-play (MGlog) — R3 nav"
    )
    screen = WIN
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("segoeui", 16)
    font_sm = pygame.font.SysFont("consolas", 13)
    font_lg = pygame.font.SysFont("segoeui", 18)
    font_btn = pygame.font.SysFont("segoeui", 13)

    from core import mglog_replay as mrep
    from gui import gui_replay_nav as nav
    from gui import gui_replay_gameover as go
    from gui import gui_replay_events as evpanel
    from gui import gui_replay_fx as fx
    from gui.gui_replay_paint import create_painter
    from gui import gui_replay_dig as digmod

    # Mixer re-init after display (requires NO_GUI_AT_ALL_TF=False; checked in main).
    try:
        n_ok = int(ensure_replay_audio())
        if n_ok <= 0:
            print(
                "WARNING: re-play audio: 0 sounds loaded — Continue will be silent. "
                "Check assets/sounds under project root.",
                file=sys.stderr,
            )
        else:
            print(f"Audio: {n_ok} sounds loaded (Continue-only SFX)")
    except Exception as exc:
        print(f"WARNING: ensure_replay_audio failed: {exc}", file=sys.stderr)

    painter = create_painter(session)
    if not painter.ok:
        print(f"WARNING: painter: {painter.error}", file=sys.stderr)

    # Full-log stats (cached once)
    try:
        full_stats = go.load_full_stats(session)
    except Exception as exc:
        full_stats = {"meta": {"error": str(exc)}, "overview_rows": [], "activity_rows": []}
        print(f"WARNING: stats load: {exc}", file=sys.stderr)

    if session.n_events > 0:
        mrep.set_cursor(session, 0)

    # SE Dig state
    dig = digmod.DigUiState(enabled=dig_on)
    dig_rects: Dict[str, Any] = {}
    dig_tabs: Dict[str, Any] = {}
    if dig_on:
        cfg = dig_cfg or {}
        c1 = digmod.parse_cat_list(cfg.get("cat1") or "")
        c2 = digmod.parse_cat_list(cfg.get("cat2") or "")
        if c1 and c2:
            # XOR: cat1 wins if both passed
            c2 = []
        if c1:
            dig.set_cat1_text(",".join(str(x) for x in c1))
        elif c2:
            dig.set_cat2_text(",".join(str(x) for x in c2))
        dig.rebuild_hits(session.rows)
        if dig.hits:
            mrep.set_cursor(session, dig.hits[0], nav_kind="dig")
            dig.hit_i = 0
            digmod.mark_jump_nav(dig)

    running = True
    status_extra = ""
    hover_id: Optional[str] = None
    hover_go: Optional[str] = None
    nav_rects: Dict[str, Any] = {}
    go_rects: Dict[str, Any] = {}
    view = go.VIEW_PLAYBOARD
    last_save_msg = ""
    save_done = False  # permanent disable Save after one successful shot pair
    event_scroll = 0  # G7: older lines hidden above viewport
    # F6: dice faces shown in nav; only refresh when dice pair changes
    displayed_dice: Optional[Tuple[int, int]] = None

    def _state_dice_pair() -> Optional[Tuple[int, int]]:
        st = session.state
        d = getattr(st, "dice", None)
        if d is not None and len(d) >= 2:
            try:
                return (int(d[0]), int(d[1]))
            except Exception:
                return None
        return None

    def _refresh_displayed_dice(*, force: bool = False) -> None:
        """F6: update cached dice only when pair changes (or force on jumps)."""
        nonlocal displayed_dice
        pair = _state_dice_pair()
        if force or pair != displayed_dice:
            displayed_dice = pair

    def _do_nav(bid: str) -> None:
        nonlocal status_extra, event_scroll
        ok, msg = nav.apply_nav_click(session, bid, mrep)
        status_extra = "" if ok else msg
        event_scroll = 0
        if not ok:
            return
        # SE Dig colors: only row step < / > (previous / continue)
        if dig.enabled:
            if bid in ("continue", "previous"):
                digmod.mark_step_nav(dig)
            else:
                digmod.mark_jump_nav(dig)
            dig.sync_hit_i_from_cursor(session.cursor)
        # R6 / C1: Continue-only event sounds
        if bid == "continue":
            try:
                played, skey = fx.play_continue_sound(session)
                if skey and not played:
                    status_extra = (status_extra + " | " if status_extra else "") + (
                        f"audio miss: {skey}"
                    )
            except Exception as exc:
                status_extra = (status_extra + " | " if status_extra else "") + (
                    f"audio err: {exc}"
                )
        try:
            fx.sync_structure_fx_after_nav(
                painter.gui, session, getattr(painter, "board", None)
            )
        except Exception:
            pass
        # F6: only change dice faces when the pair changed (new dice_roll / jump)
        _refresh_displayed_dice(force=(bid != "continue"))
        try:
            fx.sync_dcard_header_play_fx_from_session(painter.gui, session)
        except Exception:
            pass

    def _do_dig_step(direction: int) -> None:
        nonlocal status_extra, event_scroll
        if not dig.enabled:
            return
        dig.rebuild_hits(session.rows)
        idx = digmod.dig_step(dig, direction=direction)
        if idx is None:
            status_extra = dig.message or "No more dig hits"
            return
        mrep.set_cursor(session, idx, nav_kind="dig")
        digmod.mark_jump_nav(dig)
        event_scroll = 0
        _refresh_displayed_dice(force=True)
        try:
            fx.sync_structure_fx_after_nav(
                painter.gui, session, getattr(painter, "board", None)
            )
            fx.sync_dcard_header_play_fx_from_session(painter.gui, session)
        except Exception:
            pass

    def _paint_chrome() -> None:
        """Nav + dice + Events + optional GO strip + bottom banner (F6–F10)."""
        nonlocal nav_rects, go_rects, event_scroll, view, dig_rects, dig_tabs
        st = session.state
        c = session.completeness
        cap = mrep.nav_capabilities(session)

        if view == go.VIEW_STATISTICS and not go.should_show_game_over_strip(
            st.game_over
        ):
            view = go.VIEW_PLAYBOARD

        on_stats = view == go.VIEW_STATISTICS and go.should_show_game_over_strip(
            st.game_over
        )

        # F9: hide nav button panel + dice on Statistics so stats have room
        if on_stats:
            nav_rects = {}
        else:
            nav_rects = nav.draw_nav_panel(screen, cap, hover_id=hover_id)
            # F6/F7: draw cached dice (live positions); init cache if empty
            if displayed_dice is None:
                _refresh_displayed_dice(force=True)
            nav.draw_dice(
                screen,
                displayed_dice,
                None if displayed_dice else st.dice_sum,
                rect=LEFT_DICE_PANEL_RECT,
            )
            # SE Dig: cat fields + dig Prev/Next (below dice band)
            if dig.enabled:
                can_prev = bool(dig.hits) and dig.hit_i > 0
                can_next = bool(dig.hits) and (
                    dig.hit_i < 0 or dig.hit_i < len(dig.hits) - 1
                )
                dig_rects = digmod.draw_dig_filters_and_nav(
                    screen, dig, can_prev=can_prev, can_next=can_next
                )

        # SE Dig panel (right mid — Execution Debug slot)
        dig_tabs = {}
        if dig.enabled and not on_stats:
            dig_tabs = digmod.draw_se_dig_panel(
                screen, dig, session.rows, st.cursor
            )

        # G7 / F10: Events strip (playboard only — free space on Statistics)
        if not on_stats:
            try:
                synth = mrep.synthesize_events_at_cursor(session)
                event_scroll = evpanel.draw_event_strip(
                    screen,
                    synth,
                    scroll=event_scroll,
                    cursor_index=st.cursor,
                )
            except Exception as exc:
                pane = evpanel.panel_rect()
                pygame.draw.rect(screen, COLORS.get("LGRAY", (200, 200, 200)), pane)
                screen.blit(
                    font_sm.render(f"Events error: {exc}"[:40], True, (180, 0, 0)),
                    (pane.x + 8, pane.y + 8),
                )

        # B2: Game Over strip only when game_over applied
        go_rects = {}
        if go.should_show_game_over_strip(st.game_over):
            wid = st.winner_id or full_stats.get("meta", {}).get("winner_id")
            wcolor = ""
            if wid is not None and int(wid) in st.players:
                wcolor = st.players[int(wid)].color
            fvp = ""
            for row in full_stats.get("overview_rows") or []:
                if row.get("winner"):
                    fvp = row.get("TVP", "")
                    break
            go_rects = go.draw_strip(
                screen,
                view=view,
                winner_id=int(wid) if wid is not None else None,
                winner_color=wcolor,
                final_vp=fvp,
                complete=c.complete,
                hover_id=hover_go,
                last_save_msg=last_save_msg,
                save_done=save_done,
            )

        # F10: banner — one row, completeness LEFT + cursor chip RIGHT (no overlap)
        if go.should_show_status_banner(view):
            brect = go.banner_rect(
                screen_w=screen.get_width(),
                screen_h=screen.get_height(),
            )
            line = c.banner
            if status_extra:
                line = f"{line}  |  {status_extra}"
            if cap.get("forward_blocked_incomplete_start"):
                line = f"{line}  |  Forward nav disabled (no R-2T1)."
            elif cap.get("forward_blocked_no_more_data") and not c.ends_ok:
                line = f"{line}  |  MGlog incomplete — no further data."
            chip = (
                f"cursor {st.cursor}/{session.last_index} "
                f"R{st.round}T{st.turn} {st.last_event}"
            )
            bg = _banner_color(c.complete, c.starts_ok)
            if cap.get("forward_blocked_incomplete_start") or (
                cap.get("forward_blocked_no_more_data") and not c.ends_ok
            ):
                bg = (140, 30, 30)
            elif status_extra and not c.complete:
                bg = (100, 60, 30)
            pygame.draw.rect(screen, bg, brect)
            pygame.draw.rect(screen, (20, 20, 20), brect, 1)
            chip_surf = font_sm.render(chip, True, (230, 230, 230))
            line_surf = font_sm.render(line, True, (255, 255, 255))
            # Right-align chip; left text clipped so it never runs into chip
            chip_x = brect.right - chip_surf.get_width() - 10
            max_line_w = max(40, chip_x - brect.x - 16)
            if line_surf.get_width() > max_line_w:
                raw = line
                while raw and font_sm.size(raw + "…")[0] > max_line_w:
                    raw = raw[:-1]
                line_surf = font_sm.render(raw + "…", True, (255, 255, 255))
            mid_y = brect.y + (brect.height - line_surf.get_height()) // 2
            screen.blit(line_surf, (brect.x + 10, mid_y))
            screen.blit(chip_surf, (chip_x, mid_y))

    def _paint_playboard_view() -> None:
        st = session.state
        try:
            painter.paint(st)  # includes update_round_turn (B8)
        except Exception as exc:
            screen.fill(COLORS.get("LGRAY", (200, 200, 200)))
            screen.blit(font.render(f"Paint error: {exc}", True, (180, 0, 0)), (20, 60))
        # R7: keep structure pulse in sync + draw one frame on top of board
        try:
            fx.apply_structure_animations(
                painter.gui, session, getattr(painter, "board", None)
            )
            fx.draw_structure_animation_frame(
                painter.gui, getattr(painter, "board", None)
            )
            # D4: header pulse frame (independent of board queue)
            if hasattr(painter.gui, "draw_dcard_header_play_pulse"):
                painter.gui.draw_dcard_header_play_pulse()
        except Exception:
            pass
        # P3: Show circles on PLN2 only (S d=2/3 + opp if risk M/H; P1 radii)
        try:
            if (
                dig.enabled
                and dig.show_plan
                and dig.normalized_tab() == "PLN2"
                and 0 <= st.cursor < len(session.rows)
            ):
                row = session.rows[st.cursor]
                circles = digmod.plan_show_circles_from_row(
                    row,
                    board=getattr(painter, "board", None),
                    game=getattr(painter, "game", None),
                )
                color_map = {}
                for pid, pl in (st.players or {}).items():
                    try:
                        color_map[int(pid)] = str(getattr(pl, "color", "") or "")
                    except Exception:
                        pass
                row_pid = None
                try:
                    row_pid = int(float(row.get("player_id")))
                except Exception:
                    row_pid = None
                row_color = color_map.get(row_pid) if row_pid is not None else None
                digmod.draw_plan_show_circles(
                    screen,
                    circles,
                    player_colors=color_map,
                    row_player_id=row_pid,
                    row_player_color=row_color,
                )
        except Exception:
            pass
        _paint_chrome()

    def _paint_statistics_view() -> None:
        # Only when game_over (GO strip). Completeness banner hidden (Q7).
        screen.fill(COLORS.get("LGRAY", (200, 200, 200)))
        go.draw_statistics(screen, full_stats)
        # B8: R/T top-left in seat color (no full board paint)
        try:
            from types import SimpleNamespace

            st = session.state
            pid = int(st.turn) if st.turn is not None else 1
            pl = st.players.get(pid) if st.players else None

            def _cur():
                return pl

            stub = SimpleNamespace(
                round=st.round,
                turn=st.turn,
                players=list(st.players.values()) if st.players else [],
                get_current_player=_cur,
            )
            painter.gui.update_round_turn(stub, special=False)
        except Exception:
            pass
        _paint_chrome()

    def _do_save() -> None:
        nonlocal last_save_msg, status_extra, view, save_done
        if save_done:
            return
        try:
            result = go.save_replay_shots(
                screen,
                session,
                paint_playboard=_paint_playboard_view,
                paint_statistics=_paint_statistics_view,
                cursor=session.cursor,
            )
            last_save_msg = f"Saved → {Path(result['out_dir']).name}/"
            status_extra = f"Saved playboard + statistics screenshots"
            save_done = True  # disable Save for the rest of this re-play session
            print(f"Save: {result.get('playboard_png')}")
            print(f"Save: {result.get('statistics_png')}")
            print(f"Save: {result.get('manifest')}")
        except Exception as exc:
            last_save_msg = "Save failed"
            status_extra = f"Save failed: {exc}"
            print(f"Save error: {exc}", file=sys.stderr)

    def _scroll_events(delta: int) -> None:
        """Positive delta shows older events; clamp against current history length."""
        nonlocal event_scroll
        if delta == 0:
            return
        n = max(0, int(session.state.cursor) + 1) if session.n_events else 0
        vis = evpanel.max_visible_lines()
        event_scroll = evpanel.clamp_scroll(event_scroll + int(delta), n, vis)

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and dig.enabled:
                if digmod.handle_dig_key(dig, event, session.rows):
                    continue
            elif event.type == pygame.MOUSEMOTION:
                hover_id = nav.hit_test(event.pos, nav_rects) if nav_rects else None
                hover_go = go.hit_test(event.pos, go_rects) if go_rects else None
            elif event.type == pygame.MOUSEWHEEL:
                # Playboard dig: wheel scrolls Events history (up = older)
                if view == go.VIEW_PLAYBOARD:
                    dy = int(getattr(event, "y", 0) or 0)
                    _scroll_events(dy)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # SE Dig chrome first
                if dig.enabled and view == go.VIEW_PLAYBOARD:
                    act = digmod.handle_dig_click(
                        dig,
                        event.pos,
                        dig_rects,
                        dig_tabs,
                        session.rows,
                        session.cursor,
                    )
                    if act == "dig_prev":
                        _do_dig_step(-1)
                        # WP-R5: freshen Dig-seat reachability after scrub
                        try:
                            if 0 <= session.cursor < len(session.rows):
                                digmod.ensure_dig_row_reachability(
                                    getattr(painter, "game", None),
                                    session.rows[session.cursor],
                                )
                        except Exception:
                            pass
                        continue
                    if act == "dig_next":
                        _do_dig_step(1)
                        try:
                            if 0 <= session.cursor < len(session.rows):
                                digmod.ensure_dig_row_reachability(
                                    getattr(painter, "game", None),
                                    session.rows[session.cursor],
                                )
                        except Exception:
                            pass
                        continue
                    if act and (
                        act.startswith("show:")
                        or act.startswith("tab:")
                        or act.startswith("focus:")
                        or act == "tab:noop"
                    ):
                        if act.startswith("show:") and dig.show_plan:
                            try:
                                if 0 <= session.cursor < len(session.rows):
                                    digmod.ensure_dig_row_reachability(
                                        getattr(painter, "game", None),
                                        session.rows[session.cursor],
                                    )
                            except Exception:
                                pass
                        continue
                # G6: “?” turn-detail buttons (playboard view only)
                if view == go.VIEW_PLAYBOARD:
                    try:
                        handled = bool(
                            painter.gui.handle_turn_detail_click(event.pos)
                        )
                    except Exception:
                        handled = False
                    if handled:
                        continue
                # GO strip only when visible (game_over); ignore disabled buttons
                gbid = (
                    go.hit_test(
                        event.pos,
                        go_rects,
                        view=view,
                        save_done=save_done,
                        enabled_only=True,
                    )
                    if go_rects
                    else None
                )
                if gbid == "statistics":
                    if go.should_show_game_over_strip(session.state.game_over):
                        view = go.VIEW_STATISTICS
                elif gbid == "playboard":
                    view = go.VIEW_PLAYBOARD
                elif gbid == "save":
                    if go.should_show_game_over_strip(session.state.game_over):
                        _do_save()
                else:
                    bid = nav.hit_test(event.pos, nav_rects) if nav_rects else None
                    if bid:
                        _do_nav(bid)
            # R3 / Q1: no keyboard nav except dig cat fields

        # Main content by view (stats only after game_over)
        if view == go.VIEW_STATISTICS and go.should_show_game_over_strip(
            session.state.game_over
        ):
            _paint_statistics_view()
        else:
            if view == go.VIEW_STATISTICS:
                view = go.VIEW_PLAYBOARD
            _paint_playboard_view()

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    args = build_parser().parse_args(argv)

    # Interactive re-play / dig GUI: operator owns NO_GUI_AT_ALL_TF.
    # False = GUI + sounds (this script). True = headless / run_headless only.
    # --check-only stays allowed under either flag (no window / no SFX).
    if not bool(getattr(args, "check_only", False)):
        try:
            from core.constants import NO_GUI_AT_ALL_TF

            if bool(NO_GUI_AT_ALL_TF):
                try:
                    from core import console

                    console.error(
                        "replay GUI requires NO_GUI_AT_ALL_TF=False in core/constants.py "
                        "(True is for run_headless only). Set False, then re-run."
                    )
                except Exception:
                    print(
                        "ERROR: replay GUI requires NO_GUI_AT_ALL_TF=False in "
                        "core/constants.py (True is for run_headless only).",
                        file=sys.stderr,
                    )
                return 2
        except Exception:
            pass

    pb, mg, notes = resolve_paths(args)

    # Early dual-missing message
    if pb is None and mg is None:
        print(
            "ERROR: Provide --playboard and --mglog (or --game-dir with mglog.csv "
            "and a playboard via --playboard / SAVED_PLAYBOARD).",
            file=sys.stderr,
        )
        return 2

    from core import mglog_replay as mrep

    # validate_inputs lists both failures even if one path is None
    iv = mrep.validate_inputs(pb, mg)
    if not iv.ok:
        print("ERROR: required inputs missing or unreadable:", file=sys.stderr)
        for e in iv.errors:
            print(f"  - {e}", file=sys.stderr)
        for n in notes:
            print(f"  note: {n}", file=sys.stderr)
        return 2

    assert pb is not None and mg is not None

    dig_enabled = bool(getattr(args, "dig", False))
    # XOR cat1/cat2 at CLI
    cat1_s = str(getattr(args, "cat1", "") or "").strip()
    cat2_s = str(getattr(args, "cat2", "") or "").strip()
    if cat1_s and cat2_s:
        print("NOTE: both --cat1 and --cat2 set; using --cat1 only (XOR).", file=sys.stderr)
        cat2_s = ""
    if dig_enabled:
        mg_s = str(mg).replace("\\", "/")
        if "mglog_cs" not in mg_s and "cs_annot" not in mg_s:
            print(
                "WARNING: dig mode without enriched mglog_cs.csv — "
                "pass --mglog-cs or --game-dir with cs_annot/…/mglog_cs.csv.",
                file=sys.stderr,
            )

    session = mrep.load_replay_session(pb, mg)
    if not session.load_ok:
        print_load_report(session, notes)
        return 2

    if args.start_at_end and session.n_events > 0 and session.completeness.starts_ok:
        mrep.set_cursor(session, session.last_index)
    elif session.n_events > 0:
        mrep.set_cursor(session, 0)

    if args.check_only:
        return run_check_only(session, notes)

    print_load_report(session, notes)
    dig_cfg = None
    if dig_enabled:
        dig_cfg = {"enabled": True, "cat1": cat1_s, "cat2": cat2_s}
        print(f"SE Dig ON  cat1={cat1_s or '—'}  cat2={cat2_s or '—'}")
    try:
        return run_gui(session, dig_cfg=dig_cfg)
    except Exception as exc:
        print(f"GUI error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
