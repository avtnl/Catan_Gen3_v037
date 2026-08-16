"""Phase C2 WP-R2: dice sequence helpers (record / replay / hash).

Replay uses an ordered list of (d1, d2) pairs — the same as ``game.dice_rolls``.
``dice_roll_history`` remains a histogram only and is not used for replay.

See docs/PhaseC2_way_reassess_experiment_plan.md §3.3.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

DicePair = Tuple[int, int]
PathLike = Union[str, Path]


def normalize_dice_pair(value: Any) -> Optional[DicePair]:
    """Return (d1, d2) with faces 1..6, or None if invalid."""
    try:
        if isinstance(value, Mapping):
            a = value.get("a", value.get(0, value.get("d1")))
            b = value.get("b", value.get(1, value.get("d2")))
            pair = (int(a), int(b))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            pair = (int(value[0]), int(value[1]))
        else:
            return None
        if not (1 <= pair[0] <= 6 and 1 <= pair[1] <= 6):
            return None
        return pair
    except Exception:
        return None


def normalize_dice_list(raw: Any) -> List[DicePair]:
    """Normalize a sequence of pairs; skip invalid entries."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[DicePair] = []
    for item in raw:
        pair = normalize_dice_pair(item)
        if pair is not None:
            out.append(pair)
    return out


def dice_hash(rolls: Sequence[Any], *, length: int = 12) -> Optional[str]:
    """Stable short hash of an ordered dice list (sha1 hex prefix)."""
    pairs = normalize_dice_list(rolls)
    if not pairs:
        return None
    payload = json.dumps(pairs, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    n = max(8, min(40, int(length or 12)))
    return digest[:n]


def dice_export_dict(rolls: Sequence[Any], *, seed: Any = None) -> Dict[str, Any]:
    """Payload fragment for result.json / dig-in."""
    pairs = normalize_dice_list(rolls)
    return {
        "dice_rolls": [list(p) for p in pairs],
        "dice_count": len(pairs),
        "dice_hash": dice_hash(pairs),
        "seed": seed if seed is not None and seed != "" else None,
    }


def load_dice_rolls_from_result(path: PathLike) -> Dict[str, Any]:
    """Load dice_rolls (+ seed) from a result.json. Returns {ok, dice_rolls, seed, error}."""
    p = Path(path)
    out: Dict[str, Any] = {"ok": False, "dice_rolls": [], "seed": None, "error": "", "path": str(p)}
    if not p.is_file():
        out["error"] = f"not found: {p}"
        return out
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        out["error"] = f"json: {exc}"
        return out
    if not isinstance(data, Mapping):
        out["error"] = "result is not an object"
        return out
    rolls = normalize_dice_list(data.get("dice_rolls"))
    seed = data.get("seed", data.get("game_seed"))
    try:
        seed = int(seed) if seed is not None and seed != "" else None
    except Exception:
        seed = None
    out["ok"] = True
    out["dice_rolls"] = rolls
    out["seed"] = seed
    out["game_id"] = data.get("game_id")
    out["sequence_number"] = data.get("sequence_number")
    return out


def load_dice_library_from_batch(batch_dir: PathLike) -> Dict[str, Any]:
    """Load ordered dice scripts for each game folder g001, g002, …

    Returns {ok, batch_dir, scripts: {sequence_number: {dice_rolls, seed, path}}, error}.
    """
    root = Path(batch_dir)
    result: Dict[str, Any] = {
        "ok": False,
        "batch_dir": str(root),
        "scripts": {},
        "error": "",
    }
    if not root.is_dir():
        result["error"] = f"batch dir not found: {root}"
        return result
    scripts: Dict[int, Dict[str, Any]] = {}
    for child in sorted(root.glob("g*/result.json")):
        loaded = load_dice_rolls_from_result(child)
        if not loaded.get("ok"):
            continue
        seq = loaded.get("sequence_number")
        try:
            seq_i = int(seq) if seq is not None else int(child.parent.name.lstrip("g") or 0)
        except Exception:
            continue
        if seq_i <= 0:
            continue
        scripts[seq_i] = {
            "dice_rolls": list(loaded.get("dice_rolls") or []),
            "seed": loaded.get("seed"),
            "path": str(child),
            "game_id": loaded.get("game_id"),
        }
    result["scripts"] = scripts
    result["ok"] = bool(scripts)
    if not scripts:
        result["error"] = "no g*/result.json with dice_rolls found"
    return result


def load_dice_list_from_file(path: PathLike) -> List[DicePair]:
    """Best-effort load of a dice list file (JSON array or line-based pairs).

    Used to integrate constants.DICEROLL_SET_TF / NAME_DR_FILE style scripts.
    """
    p = Path(path)
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    # JSON array
    try:
        data = json.loads(text)
        pairs = normalize_dice_list(data)
        if pairs:
            return pairs
    except Exception:
        pass
    # line formats: "3 4" / "3,4" / "3+4"
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in (",", "+", " ", "\t", ";"):
            if sep in line:
                parts = [x for x in line.replace("+", " ").replace(",", " ").replace(";", " ").split() if x]
                if len(parts) >= 2:
                    pair = normalize_dice_pair(parts[:2])
                    if pair:
                        pairs.append(pair)
                break
    return pairs


__all__ = [
    "DicePair",
    "normalize_dice_pair",
    "normalize_dice_list",
    "dice_hash",
    "dice_export_dict",
    "load_dice_rolls_from_result",
    "load_dice_library_from_batch",
    "load_dice_list_from_file",
]
