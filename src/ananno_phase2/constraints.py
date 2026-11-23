from __future__ import annotations

from dataclasses import dataclass

from .models import Pallet, Placement

EPS = 1e-9


def fits_bounds(item: Placement, pallet: Pallet) -> bool:
    return (
        item.point.x >= -EPS
        and item.point.y >= -EPS
        and item.point.z >= -EPS
        and item.x2 <= pallet.length + EPS
        and item.y2 <= pallet.width + EPS
        and item.z2 <= pallet.max_height + EPS
    )


def aabb_overlap(a: Placement, b: Placement) -> bool:
    return not (
        a.x2 <= b.point.x + EPS
        or b.x2 <= a.point.x + EPS
        or a.y2 <= b.point.y + EPS
        or b.y2 <= a.point.y + EPS
        or a.z2 <= b.point.z + EPS
        or b.z2 <= a.point.z + EPS
    )


def _rectangle_union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    if not rectangles:
        return 0.0
    xs = sorted({r[0] for r in rectangles} | {r[1] for r in rectangles})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right - left <= EPS:
            continue
        intervals = sorted((r[2], r[3]) for r in rectangles if r[0] < right - EPS and r[1] > left + EPS)
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start <= end + EPS:
                    end = max(end, next_end)
                else:
                    covered += end - start
                    start, end = next_start, next_end
            covered += end - start
        area += (right - left) * covered
    return area


def support_ratio(candidate: Placement, placed: list[Placement]) -> float:
    if candidate.point.z <= EPS:
        return 1.0
    rectangles = []
    for support in placed:
        if abs(support.z2 - candidate.point.z) > EPS:
            continue
        x1, x2 = max(candidate.point.x, support.point.x), min(candidate.x2, support.x2)
        y1, y2 = max(candidate.point.y, support.point.y), min(candidate.y2, support.y2)
        if x2 - x1 > EPS and y2 - y1 > EPS:
            rectangles.append((x1, x2, y1, y2))
    base_area = candidate.orientation.length * candidate.orientation.width
    return min(1.0, _rectangle_union_area(rectangles) / base_area)


@dataclass(frozen=True)
class Feasibility:
    feasible: bool
    reason: str = ""


@dataclass(frozen=True)
class ConstraintSet:
    min_support_ratio: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.min_support_ratio <= 1:
            raise ValueError("支撑率阈值必须位于 [0, 1]")

    def validate(self, candidate: Placement, placed: list[Placement], pallet: Pallet) -> Feasibility:
        if not fits_bounds(candidate, pallet):
            return Feasibility(False, "超出托盘边界")
        if any(aabb_overlap(candidate, other) for other in placed):
            return Feasibility(False, "与已放置箱体碰撞")
        ratio = support_ratio(candidate, placed)
        if ratio + EPS < self.min_support_ratio:
            return Feasibility(False, f"支撑率不足：{ratio:.3f} < {self.min_support_ratio:.3f}")
        return Feasibility(True)
