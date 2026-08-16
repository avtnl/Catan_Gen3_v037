"""Annotate MGlog copies from CS (batch read-only).

**W2–W3 (legacy interest-only):** Policy B seat-turn stamp of ``cs_tf``/cats.

**SE2 (default batch path):** ``cs_mglog_se_v2`` **dense-only** under ``cs_annot/``:

* ``g00N/mglog_cs.csv`` (dense carry-forward; sparse retired after lab compare)
* SE columns + ``se_tf`` + probe ``cs_tf``/cats; ``se_update`` rows (policy a/b)

Does not modify original batch files.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from core.batch.cs_interest import (
    CSInterestEvent,
    INTEREST_SCHEMA,
    INTEREST_VERSION,
    classify_cs_path,
    merge_interest_by_seat_turn,
)
from core.batch.cs_mglog_codes import (
    ANNOT_EXTRA_COLUMNS,
    ANNOT_MGLOG_NAME,
    ANNOT_SCHEMA,
    ANNOT_SUBDIR_DEFAULT,
    ATTACH_POLICY,
    COL_CS_CAT1,
    COL_CS_CAT2,
    COL_CS_TF,
    MANIFEST_NAME,
    encode_code_list,
    encode_cs_tf,
)
from core.batch.cs_setback_analyzer import load_batch_game_ids
from core.batch.strategy_change_taxonomy import (
    SETBACK_THRESHOLD_DEFAULT,
    TARGET_THRASH_PER_ROUND_DEFAULT,
)

PathLike = Union[str, Path]

ANNOTATE_PROBE_VERSION = 1


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Path resolution ──────────────────────────────────────────────────────────


def resolve_cs_path_for_batch(batch_dir: PathLike) -> Optional[Path]:
    root = Path(batch_dir)
    for name in ("cs.jsonl", "cs.txt"):
        cand = root / name
        if cand.is_file():
            return cand.resolve()
    info = load_batch_game_ids(root)
    for p in info.get("cs_paths") or []:
        cp = Path(str(p))
        if cp.is_file():
            return cp.resolve()
    return None


def _game_folder_from_result_path(result_path: Path) -> str:
    """``.../g001/result.json`` → ``g001``."""
    parent = result_path.parent
    name = parent.name
    if name:
        return name
    return "game"


def discover_game_mglog_map(batch_dir: PathLike) -> Dict[str, Dict[str, Any]]:
    """Map CS ``game_id`` → {folder, mglog_path, result_path, sequence}.

    Prefer ``batch_summary.json`` games[]; also scan ``g*/result.json``.
    """
    root = Path(batch_dir)
    by_gid: Dict[str, Dict[str, Any]] = {}

    def _register(
        *,
        game_id: str,
        result_path: Optional[Path],
        mglog_hint: Optional[str] = None,
        sequence: Any = None,
    ) -> None:
        gid = str(game_id or "").strip()
        if not gid:
            return
        folder = None
        result_p = Path(result_path) if result_path else None
        if result_p is not None:
            folder = _game_folder_from_result_path(result_p)
        mglog: Optional[Path] = None
        if mglog_hint:
            hp = Path(str(mglog_hint))
            if hp.is_file():
                mglog = hp.resolve()
        if mglog is None and result_p is not None:
            cand = result_p.parent / "mglog.csv"
            if cand.is_file():
                mglog = cand.resolve()
        if mglog is None and folder:
            cand = root / folder / "mglog.csv"
            if cand.is_file():
                mglog = cand.resolve()
        entry = by_gid.get(gid) or {}
        if folder:
            entry["folder"] = folder
        if result_p is not None and result_p.is_file():
            entry["result_path"] = str(result_p.resolve())
        if mglog is not None:
            entry["mglog_path"] = str(mglog)
        if sequence is not None:
            entry["sequence_number"] = sequence
        entry["game_id"] = gid
        by_gid[gid] = entry

    summary_path = root / "batch_summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary, Mapping):
                for g in list(summary.get("games") or []):
                    if not isinstance(g, Mapping):
                        continue
                    rp = g.get("result_path")
                    result_p = Path(str(rp)) if rp else None
                    # also try compact relative g00N from sequence
                    if result_p is None:
                        seq = g.get("sequence_number")
                        if seq is not None:
                            try:
                                folder = f"g{int(seq):03d}"
                                cand = root / folder / "result.json"
                                if cand.is_file():
                                    result_p = cand
                            except Exception:
                                pass
                    _register(
                        game_id=str(g.get("game_id") or ""),
                        result_path=result_p,
                        mglog_hint=g.get("mglog_path"),
                        sequence=g.get("sequence_number"),
                    )
        except Exception:
            pass

    for child in sorted(root.glob("g*/result.json")):
        try:
            res = json.loads(child.read_text(encoding="utf-8"))
            if not isinstance(res, Mapping):
                continue
            _register(
                game_id=str(res.get("game_id") or ""),
                result_path=child,
                mglog_hint=res.get("mglog_path"),
                sequence=res.get("sequence_number"),
            )
        except Exception:
            continue

    return by_gid


# ── MGlog CSV I/O ────────────────────────────────────────────────────────────


def read_mglog_csv(path: PathLike) -> Dict[str, Any]:
    """Read MGlog CSV; preserve leading ``#`` preamble lines.

    Returns ``{ok, path, preamble, fieldnames, rows, error}``.
    """
    p = Path(path)
    out: Dict[str, Any] = {
        "ok": False,
        "path": str(p),
        "preamble": [],
        "fieldnames": [],
        "rows": [],
        "error": "",
    }
    if not p.is_file():
        out["error"] = f"mglog not found: {p}"
        return out
    try:
        with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
            preamble: List[str] = []
            # Peek lines until CSV header
            pos = f.tell()
            while True:
                pos = f.tell()
                line = f.readline()
                if not line:
                    break
                if line.lstrip().startswith("#"):
                    preamble.append(line.rstrip("\n"))
                    continue
                # header line — rewind to start of this line for DictReader
                f.seek(pos)
                break
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = [dict(r) for r in reader]
        out["ok"] = True
        out["preamble"] = preamble
        out["fieldnames"] = fieldnames
        out["rows"] = rows
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


def write_mglog_annotated(
    path: PathLike,
    *,
    preamble: Sequence[str],
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> Path:
    """Write annotated MGlog (creates parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Ensure extra columns at end
    cols = list(fieldnames)
    for c in ANNOT_EXTRA_COLUMNS:
        if c not in cols:
            cols.append(c)
    with p.open("w", encoding="utf-8", newline="") as f:
        for line in preamble:
            f.write(line.rstrip("\n") + "\n")
        # Annotation stamp (after original comments)
        f.write(
            f"# cs_annot schema={ANNOT_SCHEMA} attach={ATTACH_POLICY} "
            f"cols={','.join(ANNOT_EXTRA_COLUMNS)}\n"
        )
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            out_row = {k: row.get(k, "") for k in cols}
            w.writerow(out_row)
    return p.resolve()


# ── Policy B attach ──────────────────────────────────────────────────────────


def seat_turn_key(
    round_: Any, turn: Any, player_id: Any
) -> Optional[Tuple[int, int, int]]:
    r = _safe_int(round_)
    t = _safe_int(turn)
    p = _safe_int(player_id)
    if r is None or t is None or p is None:
        return None
    return (int(r), int(t), int(p))


def last_row_index_by_seat_turn(
    rows: Sequence[Mapping[str, Any]],
) -> Dict[Tuple[int, int, int], int]:
    """Policy B: last MGlog row index per (round, turn, player_id)."""
    last: Dict[Tuple[int, int, int], int] = {}
    for i, row in enumerate(rows):
        key = seat_turn_key(row.get("round"), row.get("turn"), row.get("player_id"))
        if key is not None:
            last[key] = i
    return last


def attach_interest_to_rows(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[CSInterestEvent],
    *,
    fieldnames: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Return new rows with cs_* columns; Policy B attach.

    ``events`` should already be seat-turn merged for this game (or will be
    applied with last-write union if duplicates remain).
    """
    base_fields = list(fieldnames or [])
    if not base_fields and rows:
        base_fields = list(rows[0].keys())
    for c in ANNOT_EXTRA_COLUMNS:
        if c not in base_fields:
            base_fields.append(c)

    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        nr = dict(row)
        nr[COL_CS_TF] = encode_cs_tf(False)
        nr[COL_CS_CAT1] = ""
        nr[COL_CS_CAT2] = ""
        out_rows.append(nr)

    last = last_row_index_by_seat_turn(out_rows)
    # Union codes if multiple events hit same seat-turn after merge
    stamp: Dict[Tuple[int, int, int], Dict[str, List[int]]] = {}
    attached = 0
    skipped_no_row = 0
    for ev in events:
        key = seat_turn_key(ev.round, ev.turn, ev.player_id)
        if key is None:
            skipped_no_row += 1
            continue
        if key not in last:
            skipped_no_row += 1
            continue
        slot = stamp.setdefault(key, {"cat1": [], "cat2": []})
        slot["cat1"].extend(ev.cat1)
        slot["cat2"].extend(ev.cat2)

    from core.batch.cs_mglog_codes import sorted_unique_codes

    for key, codes in stamp.items():
        idx = last[key]
        c1 = sorted_unique_codes(codes["cat1"])
        c2 = sorted_unique_codes(codes["cat2"])
        if not c1:
            continue
        out_rows[idx][COL_CS_TF] = encode_cs_tf(True)
        out_rows[idx][COL_CS_CAT1] = encode_code_list(c1)
        out_rows[idx][COL_CS_CAT2] = encode_code_list(c2)
        attached += 1

    return {
        "rows": out_rows,
        "fieldnames": base_fields,
        "rows_stamped": attached,
        "events_skipped_no_row": skipped_no_row,
        "interest_events_in": len(events),
        "seat_turns_stamped": attached,
    }


# ── Batch annotate ───────────────────────────────────────────────────────────


def annotate_single_mglog(
    mglog_path: PathLike,
    events: Sequence[CSInterestEvent],
    out_path: PathLike,
) -> Dict[str, Any]:
    """Annotate one MGlog file → ``out_path``. Original untouched."""
    loaded = read_mglog_csv(mglog_path)
    result: Dict[str, Any] = {
        "ok": False,
        "source_mglog": str(mglog_path),
        "out_path": str(out_path),
        "error": loaded.get("error") or "",
        "rows_total": 0,
        "rows_stamped": 0,
        "events_skipped_no_row": 0,
    }
    if not loaded.get("ok"):
        return result
    # Verify original not same as out (safety)
    src = Path(mglog_path).resolve()
    dst = Path(out_path).resolve()
    if src == dst:
        result["error"] = "refuse to overwrite source mglog (out_path == source)"
        return result

    attach = attach_interest_to_rows(
        loaded["rows"],
        events,
        fieldnames=loaded["fieldnames"],
    )
    write_mglog_annotated(
        dst,
        preamble=loaded["preamble"],
        fieldnames=attach["fieldnames"],
        rows=attach["rows"],
    )
    result["ok"] = True
    result["rows_total"] = len(attach["rows"])
    result["rows_stamped"] = attach["rows_stamped"]
    result["events_skipped_no_row"] = attach["events_skipped_no_row"]
    result["interest_events_in"] = attach["interest_events_in"]
    result["out_path"] = str(dst)
    return result


def annotate_batch_dir(
    batch_dir: PathLike,
    *,
    out_dir: Optional[PathLike] = None,
    cs_path: Optional[PathLike] = None,
    game_ids: Optional[Sequence[str]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
    legacy_interest_only: bool = False,
) -> Dict[str, Any]:
    """Annotate all games in a batch that have an MGlog.

    Default (**SE2**): dense ``g00N/mglog_cs.csv`` (``cs_mglog_se_v2``).
    Pass ``legacy_interest_only=True`` for W2–W3 interest-only Policy B cats.

    Originals under ``batch_dir`` are never written.
    Default ``out_dir`` = ``batch_dir / cs_annot``.
    """
    if not legacy_interest_only:
        return _annotate_batch_dir_se_v2(
            batch_dir,
            out_dir=out_dir,
            cs_path=cs_path,
            game_ids=game_ids,
            setback_threshold=setback_threshold,
            thrash_threshold=thrash_threshold,
        )

    root = Path(batch_dir).resolve()
    out_root = Path(out_dir).resolve() if out_dir else (root / ANNOT_SUBDIR_DEFAULT)
    summary: Dict[str, Any] = {
        "ok": False,
        "annot_schema": ANNOT_SCHEMA,
        "attach_policy": ATTACH_POLICY,
        "probe_version": ANNOTATE_PROBE_VERSION,
        "interest_schema": INTEREST_SCHEMA,
        "interest_version": INTEREST_VERSION,
        "batch_dir": str(root),
        "out_dir": str(out_root),
        "cs_path": None,
        "setback_threshold": float(setback_threshold),
        "thrash_threshold": int(thrash_threshold),
        "created_utc": _utc_now_iso(),
        "games_annotated": [],
        "games_skipped": [],
        "error": "",
        "n_interest_events": 0,
        "n_rows_stamped": 0,
    }

    if not root.is_dir():
        summary["error"] = f"batch dir not found: {root}"
        return summary

    cs = Path(cs_path).resolve() if cs_path else resolve_cs_path_for_batch(root)
    if cs is None or not cs.is_file():
        summary["error"] = "CS JSONL not found for batch"
        return summary
    summary["cs_path"] = str(cs)

    batch_info = load_batch_game_ids(root)
    summary["batch_id"] = batch_info.get("batch_id")

    classified = classify_cs_path(
        cs,
        game_ids=game_ids,
        setback_threshold=setback_threshold,
        thrash_threshold=thrash_threshold,
        merge_seat_turn=False,
    )
    if not classified.get("ok"):
        summary["error"] = classified.get("error") or "CS classify failed"
        return summary

    all_events: List[CSInterestEvent] = list(classified.get("events") or [])
    summary["n_interest_events"] = len(all_events)
    summary["cs_rows"] = classified.get("cs_rows")

    by_game: Dict[str, List[CSInterestEvent]] = defaultdict(list)
    for ev in all_events:
        by_game[str(ev.game_id)].append(ev)

    game_map = discover_game_mglog_map(root)
    all_gids = set(game_map.keys()) | set(by_game.keys())
    if game_ids:
        allow = {str(g) for g in game_ids}
        all_gids = {g for g in all_gids if g in allow}

    out_root.mkdir(parents=True, exist_ok=True)
    total_stamped = 0

    for gid in sorted(all_gids):
        meta = dict(game_map.get(gid) or {"game_id": gid})
        mglog = meta.get("mglog_path")
        folder = meta.get("folder") or _guess_folder_for_game(root, gid, meta)
        if not mglog or not Path(str(mglog)).is_file():
            summary["games_skipped"].append(
                {"game_id": gid, "reason": "no_mglog", "folder": folder}
            )
            continue
        if not folder:
            folder = f"game_{gid}"
        out_mg = out_root / str(folder) / ANNOT_MGLOG_NAME
        if Path(str(mglog)).resolve() == out_mg.resolve():
            summary["games_skipped"].append(
                {"game_id": gid, "reason": "out_equals_source", "folder": folder}
            )
            continue

        src_path = Path(str(mglog))
        src_stat = src_path.stat()
        src_mtime = src_stat.st_mtime_ns
        src_size = src_stat.st_size

        seat_events = merge_interest_by_seat_turn(by_game.get(gid) or [])
        ann = annotate_single_mglog(src_path, seat_events, out_mg)
        after = src_path.stat()
        if after.st_mtime_ns != src_mtime or after.st_size != src_size:
            summary["games_skipped"].append(
                {
                    "game_id": gid,
                    "reason": "source_mutated_unexpectedly",
                    "folder": folder,
                }
            )
        if not ann.get("ok"):
            summary["games_skipped"].append(
                {
                    "game_id": gid,
                    "reason": ann.get("error") or "annotate_failed",
                    "folder": folder,
                }
            )
            continue
        total_stamped += int(ann.get("rows_stamped") or 0)
        summary["games_annotated"].append(
            {
                "game_id": gid,
                "folder": folder,
                "source_mglog": str(src_path.resolve()),
                "out_path": ann.get("out_path"),
                "rows_total": ann.get("rows_total"),
                "rows_stamped": ann.get("rows_stamped"),
                "interest_events": len(seat_events),
                "events_skipped_no_row": ann.get("events_skipped_no_row"),
            }
        )

    summary["n_rows_stamped"] = total_stamped
    summary["n_games_annotated"] = len(summary["games_annotated"])
    summary["n_games_skipped"] = len(summary["games_skipped"])
    summary["ok"] = summary["n_games_annotated"] > 0 or (
        summary["n_interest_events"] >= 0 and not summary["error"]
    )
    if summary["n_games_annotated"] == 0 and any(
        s.get("reason") == "no_mglog" for s in summary["games_skipped"]
    ):
        summary["ok"] = True
        if not summary["error"]:
            summary["warning"] = "no games had mglog.csv to annotate"

    manifest_path = out_root / MANIFEST_NAME
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(summary)
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary["manifest_path"] = str(manifest_path.resolve())
    except Exception as exc:
        summary["error"] = (summary.get("error") or "") + f" manifest write: {exc}"
        summary["ok"] = False

    return summary


def _annotate_batch_dir_se_v2(
    batch_dir: PathLike,
    *,
    out_dir: Optional[PathLike] = None,
    cs_path: Optional[PathLike] = None,
    game_ids: Optional[Sequence[str]] = None,
    setback_threshold: float = SETBACK_THRESHOLD_DEFAULT,
    thrash_threshold: int = TARGET_THRASH_PER_ROUND_DEFAULT,
) -> Dict[str, Any]:
    """SE2: dense-only enriched MGlog per game."""
    from core.batch.cs_mglog_enrich_v2 import (
        ATTACH_POLICY_SE,
        CARRY_FORWARD,
        enrich_mglog_file_v2,
    )
    from core.batch.cs_se_snapshot import ANNOT_SCHEMA_SE
    from core.batch.cs_setback_analyzer import load_cs_jsonl

    root = Path(batch_dir).resolve()
    out_root = Path(out_dir).resolve() if out_dir else (root / ANNOT_SUBDIR_DEFAULT)
    summary: Dict[str, Any] = {
        "ok": False,
        "annot_schema": ANNOT_SCHEMA_SE,
        "attach_policy": ATTACH_POLICY_SE,
        "variants": ["dense"],
        "carry_forward": CARRY_FORWARD,
        "probe_version": ANNOTATE_PROBE_VERSION,
        "interest_schema": INTEREST_SCHEMA,
        "interest_version": INTEREST_VERSION,
        "batch_dir": str(root),
        "out_dir": str(out_root),
        "cs_path": None,
        "setback_threshold": float(setback_threshold),
        "thrash_threshold": int(thrash_threshold),
        "created_utc": _utc_now_iso(),
        "games_annotated": [],
        "games_skipped": [],
        "error": "",
        "n_interest_events": 0,
        "n_rows_total": 0,
        "n_se_updates": 0,
    }

    if not root.is_dir():
        summary["error"] = f"batch dir not found: {root}"
        return summary

    cs = Path(cs_path).resolve() if cs_path else resolve_cs_path_for_batch(root)
    if cs is None or not cs.is_file():
        summary["error"] = "CS JSONL not found for batch"
        return summary
    summary["cs_path"] = str(cs)

    batch_info = load_batch_game_ids(root)
    summary["batch_id"] = batch_info.get("batch_id")

    loaded = load_cs_jsonl(cs)
    if not loaded.get("ok"):
        summary["error"] = loaded.get("error") or "CS load failed"
        return summary
    all_cs = list(loaded.get("rows") or [])
    summary["cs_rows"] = len(all_cs)

    classified = classify_cs_path(
        cs,
        game_ids=game_ids,
        setback_threshold=setback_threshold,
        thrash_threshold=thrash_threshold,
        merge_seat_turn=False,
    )
    all_events: List[CSInterestEvent] = (
        list(classified.get("events") or []) if classified.get("ok") else []
    )
    summary["n_interest_events"] = len(all_events)

    cs_by_game: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in all_cs:
        gid = str(row.get("game_id") or "").strip() or "_nogame"
        if game_ids and gid not in {str(g) for g in game_ids}:
            continue
        cs_by_game[gid].append(row)

    ev_by_game: Dict[str, List[CSInterestEvent]] = defaultdict(list)
    for ev in all_events:
        ev_by_game[str(ev.game_id)].append(ev)

    game_map = discover_game_mglog_map(root)
    all_gids = set(game_map.keys()) | set(cs_by_game.keys())
    if game_ids:
        allow = {str(g) for g in game_ids}
        all_gids = {g for g in all_gids if g in allow}

    out_root.mkdir(parents=True, exist_ok=True)
    n_rows_total = 0
    n_se_updates = 0

    for gid in sorted(all_gids):
        meta = dict(game_map.get(gid) or {"game_id": gid})
        mglog = meta.get("mglog_path")
        folder = meta.get("folder") or _guess_folder_for_game(root, gid, meta)
        if not mglog or not Path(str(mglog)).is_file():
            summary["games_skipped"].append(
                {"game_id": gid, "reason": "no_mglog", "folder": folder}
            )
            continue
        if not folder:
            folder = f"game_{gid}"
        src_path = Path(str(mglog))
        game_out = out_root / str(folder)
        src_stat = src_path.stat()
        src_mtime = src_stat.st_mtime_ns
        src_size = src_stat.st_size

        ann = enrich_mglog_file_v2(
            src_path,
            cs_by_game.get(gid) or [],
            out_dir=game_out,
            interest_events=ev_by_game.get(gid) or [],
            setback_threshold=setback_threshold,
            thrash_threshold=thrash_threshold,
        )
        after = src_path.stat()
        if after.st_mtime_ns != src_mtime or after.st_size != src_size:
            summary["games_skipped"].append(
                {
                    "game_id": gid,
                    "reason": "source_mutated_unexpectedly",
                    "folder": folder,
                }
            )
        if not ann.get("ok"):
            summary["games_skipped"].append(
                {
                    "game_id": gid,
                    "reason": ann.get("error") or "enrich_failed",
                    "folder": folder,
                }
            )
            continue
        n_rows_total += int(ann.get("n_rows") or 0)
        n_se_updates += int(ann.get("n_se_updates") or 0)
        summary["games_annotated"].append(
            {
                "game_id": gid,
                "folder": folder,
                "source_mglog": str(src_path.resolve()),
                "out_path": ann.get("out_path") or ann.get("dense_path"),
                "dense_path": ann.get("dense_path"),
                "n_rows": ann.get("n_rows"),
                "n_se_updates": ann.get("n_se_updates"),
                "n_se_tf": ann.get("n_se_tf"),
                "n_cs_tf": ann.get("n_cs_tf"),
                "interest_events": len(ev_by_game.get(gid) or []),
            }
        )

    summary["n_rows_total"] = n_rows_total
    summary["n_se_updates"] = n_se_updates
    summary["n_games_annotated"] = len(summary["games_annotated"])
    summary["n_games_skipped"] = len(summary["games_skipped"])
    summary["ok"] = True
    if summary["n_games_annotated"] == 0 and any(
        s.get("reason") == "no_mglog" for s in summary["games_skipped"]
    ):
        summary["warning"] = "no games had mglog.csv to annotate"

    manifest_path = out_root / MANIFEST_NAME
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary["manifest_path"] = str(manifest_path.resolve())
    except Exception as exc:
        summary["error"] = (summary.get("error") or "") + f" manifest write: {exc}"
        summary["ok"] = False

    return summary


def _guess_folder_for_game(
    root: Path, game_id: str, meta: Mapping[str, Any]
) -> Optional[str]:
    if meta.get("folder"):
        return str(meta["folder"])
    rp = meta.get("result_path")
    if rp:
        return _game_folder_from_result_path(Path(str(rp)))
    # Scan result.json for matching game_id
    for child in root.glob("g*/result.json"):
        try:
            res = json.loads(child.read_text(encoding="utf-8"))
            if str(res.get("game_id") or "") == str(game_id):
                return child.parent.name
        except Exception:
            continue
    return None


__all__ = [
    "ANNOTATE_PROBE_VERSION",
    "resolve_cs_path_for_batch",
    "discover_game_mglog_map",
    "read_mglog_csv",
    "write_mglog_annotated",
    "seat_turn_key",
    "last_row_index_by_seat_turn",
    "attach_interest_to_rows",
    "annotate_single_mglog",
    "annotate_batch_dir",
]
