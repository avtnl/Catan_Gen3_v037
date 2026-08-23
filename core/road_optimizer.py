"""P3 stub: multi-path / LR road choice (not wired into Best-Action yet).

Operator body (`docs/placeholders.txt` / `docs/P3_optimizers_spec.md`):

  (a) Toward a settle target — prefer path that
        (i)  defends own build strategy toward the target,
        (ii) blocks opponent path expansion (also helps LR contests),
        (iii) increases own path length (LR).

  (b) Sole purpose LR — prefer road that
        (i)  connects independent clusters when that supports LR, or
        (ii) increases expansion capability while avoiding tips opponents
             can easily block.

Related live code (keep until wiring):
  - ``core.ai_road_planner`` — current strategic road allow / pick
  - ``core.strategy_min_road_cover`` — victory *count* of empty roads
  - ``core.strategy_race_ba`` — BA chase sticky race when risk M/H

WIRING_TODO (near future):
  When ≥2 legal paths to sticky settle (or LR-only candidate set), BA
  ``Build road`` should call ``rank_paths_to_target`` /
  ``rank_lr_only_roads`` and take the top edge. Dig PLN1 R-row should
  display that preferred path.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

WIRING_STATUS = "stub_unwired"
WIRING_TODO = (
    "Wire rank_* into Best-Action Build-road and Dig PLN1 R Target path "
    "when multiple legal routes exist (docs/P3_optimizers_spec.md)."
)

Edge = Tuple[int, int]


def _norm_edge(raw: Any) -> Optional[Edge]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            a, b = int(raw[0]), int(raw[1])
            return (min(a, b), max(a, b))
        except Exception:
            return None
    return None


def _path_edges(path: Any) -> List[Edge]:
    """Accept ``[[a,b],[b,c]]``, flat ``[a,b,c]``, or mapping with roads/path."""
    if isinstance(path, Mapping):
        raw = path.get("roads") or path.get("path") or path.get("edges") or path.get("route")
        return _path_edges(raw)
    if not isinstance(path, (list, tuple)) or not path:
        return []
    # list of edges
    if isinstance(path[0], (list, tuple)) and len(path[0]) >= 2:
        out: List[Edge] = []
        for e in path:
            ne = _norm_edge(e)
            if ne is not None:
                out.append(ne)
        return out
    # flat vertex chain a-b-c
    try:
        verts = [int(x) for x in path]
    except Exception:
        return []
    return [
        (min(verts[i], verts[i + 1]), max(verts[i], verts[i + 1]))
        for i in range(len(verts) - 1)
    ]


def rank_paths_to_target(
    game: Any,
    player: Any,
    target_id: Any,
    paths: Sequence[Any],
    *,
    threats: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Rank alternate empty-road paths to ``target_id``.

    Stub: preserves input order; attaches placeholder scores/reasons.
    Does **not** change Best-Action. Callers should ignore ranking until wired.
    """
    tid = None
    try:
        tid = int(target_id) if target_id is not None else None
    except Exception:
        tid = None

    ranked: List[Dict[str, Any]] = []
    for i, p in enumerate(list(paths or [])):
        edges = _path_edges(p)
        reason_tags = ["stub_preserve_order"]
        # Soft hints only (no real scoring yet)
        if threats:
            reason_tags.append("threats_present_unscored")
        ranked.append(
            {
                "rank": i,
                "target_id": tid,
                "path": [[a, b] for a, b in edges],
                "score": 0.0,
                "reasons": list(reason_tags),
                "mode": "toward_target",
            }
        )
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "mode": "toward_target",
        "target_id": tid,
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "note": "stub: order unchanged; politics scoring not implemented",
    }


def rank_lr_only_roads(
    game: Any,
    player: Any,
    candidates: Sequence[Any],
) -> Dict[str, Any]:
    """Rank roads whose sole purpose is Longest Road (no settle target).

    Stub: preserves candidate order.
    """
    ranked: List[Dict[str, Any]] = []
    for i, c in enumerate(list(candidates or [])):
        edge = _norm_edge(c if not isinstance(c, Mapping) else (c.get("road") or c.get("edge") or c.get("road_id")))
        if edge is None and isinstance(c, Mapping):
            edge = _norm_edge(c.get("path"))
        ranked.append(
            {
                "rank": i,
                "edge": [edge[0], edge[1]] if edge else None,
                "candidate": c,
                "score": 0.0,
                "reasons": ["stub_preserve_order", "lr_only"],
                "mode": "lr_only",
            }
        )
    return {
        "ok": True,
        "wired": False,
        "wiring_status": WIRING_STATUS,
        "wiring_todo": WIRING_TODO,
        "mode": "lr_only",
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "note": "stub: prefer cluster-connect / safe tips — not scored yet",
    }


def optimize_road_choice(
    game: Any,
    player: Any,
    *,
    target_id: Any = None,
    paths: Optional[Sequence[Any]] = None,
    lr_candidates: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Façade: target paths if given, else LR-only candidates."""
    if paths:
        return rank_paths_to_target(game, player, target_id, paths)
    return rank_lr_only_roads(game, player, list(lr_candidates or []))


__all__ = [
    "WIRING_STATUS",
    "WIRING_TODO",
    "rank_paths_to_target",
    "rank_lr_only_roads",
    "optimize_road_choice",
]
