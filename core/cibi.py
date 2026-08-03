"""BS-6: Catan Island Board Index (CIBI) — balance metrics + composite.

Source definitions: Player One, *What is a balanced Catan board?*
Local: docs/What is a balanced Catan board.docx
https://www.boardgameanalysis.com/what-is-a-balanced-catan-board/

Six raw imbalance scores (lower = more balanced), then:
  norm[i] = raw[i] / MAX_RAW[i]
  CIBI    = mean(norm)

Gen2 calc_cibi returned raw six only; Gen3 adds the composite headline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Empirical soft maxes from article 100M-run sequence figures (1.0*).
# Order matches Gen2 six-tuple.
CIBI_MAX_RAW: Tuple[float, ...] = (
    4536.0,  # type / resource mirror distribution
    100.0,  # resource clustering
    111.0,  # resource probability distribution
    30.0,  # number clustering
    234.0,  # probability mirror distribution
    379.0,  # harbor return balance
)

# Three cut-lines × two halves. Gen2 axis[1] had duplicate 59 — fixed here.
AXIS_HALVES: Tuple[Tuple[int, ...], ...] = (
    (
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
    ),
    (
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        59,
        60,
        61,
        62,
        63,
        64,
    ),
    (
        3,
        4,
        5,
        6,
        7,
        8,
        13,
        14,
        15,
        16,
        17,
        18,
        23,
        24,
        25,
        26,
        27,
        28,
        34,
        35,
        36,
        37,
        38,
        46,
        47,
        48,
        58,
    ),
    (
        9,
        19,
        20,
        21,
        29,
        30,
        31,
        32,
        33,
        39,
        40,
        41,
        42,
        43,
        44,
        49,
        50,
        51,
        52,
        53,
        54,
        59,
        60,
        61,
        62,
        63,
        64,
    ),
    (
        3,
        13,
        14,
        15,
        23,
        24,
        25,
        26,
        27,
        34,
        35,
        36,
        37,
        38,
        39,
        46,
        47,
        48,
        49,
        50,
        51,
        58,
        59,
        60,
        61,
        62,
        63,
    ),
    (
        4,
        5,
        6,
        7,
        8,
        9,
        16,
        17,
        18,
        19,
        20,
        21,
        28,
        29,
        30,
        31,
        32,
        33,
        40,
        41,
        42,
        43,
        44,
        52,
        53,
        54,
        64,
    ),
)

RESOURCE_TYPES: Tuple[str, ...] = (
    "Field",
    "Mountain",
    "Forest",
    "Hill",
    "Pasture",
)
RESOURCE_TYPE_SET = frozenset(RESOURCE_TYPES)

# Expected pip totals (article): 4*58/18 and 3*58/18
EXPECTED_PIPS: Tuple[float, ...] = (
    12.889,  # Field
    9.667,  # Mountain
    12.889,  # Forest
    9.667,  # Hill
    12.889,  # Pasture
)

COMPONENT_LABELS: Tuple[str, ...] = (
    "Type Distribution",
    "Resource Clustering",
    "Probability Distribution for Resources",
    "Number Clustering",
    "Probability Distribution",
    "Harbor Distribution",
)


@dataclass(frozen=True)
class CibiResult:
    type_distribution: float
    resource_clustering: float
    probability_resource_distribution: float
    number_clustering: float
    probability_distribution: float
    harbor_distribution: float
    norms: Tuple[float, float, float, float, float, float]
    cibi: float
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def as_raw_tuple(self) -> Tuple[float, float, float, float, float, float]:
        return (
            float(self.type_distribution),
            float(self.resource_clustering),
            float(self.probability_resource_distribution),
            float(self.number_clustering),
            float(self.probability_distribution),
            float(self.harbor_distribution),
        )

    def as_norm_tuple(self) -> Tuple[float, float, float, float, float, float]:
        return tuple(float(x) for x in self.norms)  # type: ignore[return-value]


def composite_cibi(
    raw: Sequence[float],
    max_raw: Sequence[float] = CIBI_MAX_RAW,
) -> Tuple[float, List[float]]:
    """Normalize raw scores and return (composite, norms). Does not clamp at 1.0."""
    norms: List[float] = []
    for r, m in zip(raw, max_raw):
        mf = float(m)
        norms.append(float(r) / mf if mf > 0 else 0.0)
    if not norms:
        return 0.0, []
    return sum(norms) / len(norms), norms


def _pips_from_value(value: Any) -> float:
    try:
        from core.board import pips_from_tile_value

        return float(pips_from_tile_value(int(value or 0)))
    except Exception:
        v = int(value or 0)
        if not (2 <= v <= 12) or v == 7:
            return 0.0
        return float(6 - abs(7 - v))


def refresh_board_metrics(board: Any) -> None:
    """Rebuild intersection aggregates and road.two_tiles from current tiles/ports."""
    if board is None:
        return
    try:
        if callable(getattr(board, "_add_intersections", None)):
            board._add_intersections()
    except Exception:
        pass
    try:
        if callable(getattr(board, "_add_three_tile_values", None)):
            board._add_three_tile_values()
    except Exception:
        pass
    try:
        if callable(getattr(board, "_add_two_tile_attributes", None)):
            board._add_two_tile_attributes()
    except Exception:
        pass


def _intersection_by_id(board: Any) -> Dict[int, Any]:
    out: Dict[int, Any] = {}
    inters = list(getattr(board, "intersections", []) or [])
    for i, inter in enumerate(inters):
        if inter is None:
            continue
        try:
            iid = int(getattr(inter, "id", i))
        except Exception:
            iid = i
        out[iid] = inter
    return out


def _type_counts(inter: Any) -> List[float]:
    raw = getattr(inter, "all_tile_types", None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 5:
        return [float(raw[i] or 0) for i in range(5)]
    # Fallback from type strings on three_tile_types
    counts = [0.0, 0.0, 0.0, 0.0, 0.0]
    types = list(getattr(inter, "three_tile_types", []) or [])
    for t in types:
        ty = str(t or "")
        if ty in RESOURCE_TYPES:
            counts[RESOURCE_TYPES.index(ty)] += 1.0
    return counts


def _pip_counts(inter: Any) -> List[float]:
    raw = getattr(inter, "all_tile_pips", None)
    if isinstance(raw, (list, tuple)) and len(raw) >= 5:
        return [float(raw[i] or 0) for i in range(5)]
    return [0.0, 0.0, 0.0, 0.0, 0.0]


def _score_type_distribution(by_id: Dict[int, Any]) -> float:
    score = 0.0
    for r in range(5):
        for c in range(3):
            left = 0.0
            right = 0.0
            for iid in AXIS_HALVES[2 * c]:
                inter = by_id.get(iid)
                if inter is not None:
                    left += _type_counts(inter)[r]
            for iid in AXIS_HALVES[2 * c + 1]:
                inter = by_id.get(iid)
                if inter is not None:
                    right += _type_counts(inter)[r]
            score += (left - right) ** 2
    return score


def _score_probability_mirror(by_id: Dict[int, Any]) -> float:
    score = 0.0
    for c in range(3):
        left = 0.0
        right = 0.0
        for iid in AXIS_HALVES[2 * c]:
            inter = by_id.get(iid)
            if inter is not None:
                left += sum(_pip_counts(inter))
        for iid in AXIS_HALVES[2 * c + 1]:
            inter = by_id.get(iid)
            if inter is not None:
                right += sum(_pip_counts(inter))
        score += (left - right) ** 2
    return score


def _is_resource_type(ty: str) -> bool:
    return str(ty or "") in RESOURCE_TYPE_SET


def _score_clustering(board: Any) -> Tuple[float, float]:
    res_c = 0.0
    num_c = 0.0
    for road in list(getattr(board, "roads", []) or []):
        if road is None:
            continue
        two = list(getattr(road, "two_tiles", []) or [])
        if len(two) != 2:
            continue
        t0, t1 = two[0], two[1]
        if not (isinstance(t0, (list, tuple)) and isinstance(t1, (list, tuple))):
            continue
        if len(t0) < 3 or len(t1) < 3:
            continue
        ty0, ty1 = str(t0[1] or ""), str(t1[1] or "")
        if _is_resource_type(ty0) and ty0 == ty1:
            res_c += 5.0
        try:
            v0 = int(t0[2] or 0)
            v1 = int(t1[2] or 0)
        except Exception:
            continue
        if v0 == v1 and 2 <= v0 <= 12 and v0 != 7:
            num_c += 5.0
    return res_c, num_c


def _score_resource_probability(board: Any) -> float:
    pip_sum = [0.0, 0.0, 0.0, 0.0, 0.0]
    for tile in list(getattr(board, "tiles", []) or []):
        if tile is None:
            continue
        ty = str(getattr(tile, "type", "") or "")
        if ty not in RESOURCE_TYPE_SET:
            continue
        idx = RESOURCE_TYPES.index(ty)
        pip_sum[idx] += _pips_from_value(getattr(tile, "value", 0))
    score = 0.0
    for i in range(5):
        score += (pip_sum[i] - EXPECTED_PIPS[i]) ** 2
    return score


def _normalize_port_type(port: str) -> str:
    p = str(port or "").strip()
    if not p or p.lower() in ("blank", "clear", "none", ""):
        return ""
    low = p.lower().replace(" ", "")
    # Aliases Grain/Wool (Gen2 / article) ↔ Wheat/Sheep (Gen3)
    if "grain" in low or "wheat" in low or "field" in low:
        return "2:1 Wheat"
    if "ore" in low or "mountain" in low:
        return "2:1 Ore"
    if "wood" in low or "lumber" in low or "forest" in low:
        return "2:1 Wood"
    if "brick" in low or "hill" in low:
        return "2:1 Brick"
    if "sheep" in low or "wool" in low or "pasture" in low:
        return "2:1 Sheep"
    if "3:1" in low or low in ("3/1", "three"):
        return "3:1"
    return p


def _port_double_index(port_norm: str) -> Optional[int]:
    mapping = {
        "2:1 Wheat": 0,
        "2:1 Ore": 1,
        "2:1 Wood": 2,
        "2:1 Brick": 3,
        "2:1 Sheep": 4,
    }
    return mapping.get(port_norm)


def _intersection_harbor_score(inter: Any) -> Optional[float]:
    if inter is None:
        return None
    port = _normalize_port_type(str(getattr(inter, "port_type", "") or ""))
    if not port:
        # port_tf alone is not enough without type
        return None
    pips = _pip_counts(inter)
    score = sum(pips)
    d_idx = _port_double_index(port)
    if d_idx is not None:
        score += pips[d_idx]
    return float(score)


def _score_harbor_distribution(board: Any, by_id: Dict[int, Any]) -> float:
    pairs = list(getattr(board, "INTERSECTIONS_ARE_PORT", None) or [])
    if not pairs:
        # Gen2-style fallback
        pairs = [[3, 4], [6, 7], [13, 24], [20, 21], [33, 44], [35, 46], [53, 54], [58, 59], [61, 62]]
    harbor_scores: List[float] = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            a_id, b_id = int(pair[0]), int(pair[1])
        except Exception:
            continue
        sa = _intersection_harbor_score(by_id.get(a_id))
        sb = _intersection_harbor_score(by_id.get(b_id))
        if sa is None and sb is None:
            continue  # empty harbor site — omit from variance
        if sa is None:
            harbor_scores.append(float(sb or 0.0))
        elif sb is None:
            harbor_scores.append(float(sa or 0.0))
        else:
            harbor_scores.append(max(sa, sb))
    if not harbor_scores:
        return 0.0
    avg = sum(harbor_scores) / len(harbor_scores)
    return sum((h - avg) ** 2 for h in harbor_scores)


def _board_notes(board: Any) -> Tuple[str, ...]:
    notes: List[str] = []
    try:
        land_ids = list(getattr(board, "LIST_OF_LAND_TILES", None) or [])
        blank = 0
        tiles = list(getattr(board, "tiles", []) or [])
        by_tid = {}
        for t in tiles:
            if t is not None:
                try:
                    by_tid[int(getattr(t, "id", -1))] = t
                except Exception:
                    pass
        for tid in land_ids:
            t = by_tid.get(int(tid))
            if t is None:
                blank += 1
                continue
            ty = str(getattr(t, "type", "") or "")
            if ty in ("Blank", "", "None"):
                blank += 1
        if blank:
            notes.append(f"partial board: {blank} blank land tile(s)")
    except Exception:
        pass
    return tuple(notes)


def compute_cibi(board: Any, *, refresh: bool = True) -> CibiResult:
    """Compute raw six metrics, norms, and composite CIBI for *board*."""
    if board is None:
        raise ValueError("compute_cibi: board is None")
    if refresh:
        refresh_board_metrics(board)
    by_id = _intersection_by_id(board)
    type_d = float(_score_type_distribution(by_id))
    res_c, num_c = _score_clustering(board)
    res_c = float(res_c)
    num_c = float(num_c)
    prob_res = float(_score_resource_probability(board))
    prob_m = float(_score_probability_mirror(by_id))
    harbor = float(_score_harbor_distribution(board, by_id))
    raw = (type_d, res_c, prob_res, num_c, prob_m, harbor)
    cibi, norms = composite_cibi(raw)
    return CibiResult(
        type_distribution=type_d,
        resource_clustering=res_c,
        probability_resource_distribution=prob_res,
        number_clustering=num_c,
        probability_distribution=prob_m,
        harbor_distribution=harbor,
        norms=(
            float(norms[0]),
            float(norms[1]),
            float(norms[2]),
            float(norms[3]),
            float(norms[4]),
            float(norms[5]),
        ),
        cibi=float(cibi),
        notes=_board_notes(board),
    )


def _fmt_raw(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.1f}"


def format_cibi_lines(result: CibiResult) -> List[str]:
    """Lines for Board Settings CIBI page (headline first; footnote last)."""
    lines: List[str] = [
        "Catan Island Board Index (CIBI)",
        f"CIBI Index:  {result.cibi:.3f}",
        "",
    ]
    raws = result.as_raw_tuple()
    norms = result.as_norm_tuple()
    for i, lab in enumerate(COMPONENT_LABELS):
        lines.append(f"{lab}: {norms[i]:.3f}  (raw {_fmt_raw(raws[i])})")
    for note in result.notes:
        lines.append(str(note))
    # Footnote at bottom (GUI draws this in small font)
    lines.append("Lower is better · random mean ≈ 0.24")
    return lines


__all__ = [
    "AXIS_HALVES",
    "CIBI_MAX_RAW",
    "COMPONENT_LABELS",
    "CibiResult",
    "composite_cibi",
    "compute_cibi",
    "format_cibi_lines",
    "refresh_board_metrics",
]
