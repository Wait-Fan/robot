from __future__ import annotations

from .constraints import EPS
from .models import Pallet, Placement, Point3D


class ExtremePointGenerator:
    """简化 EP：为新箱体生成 +X、+Y、+Z 三个候选点。"""

    def initial_points(self) -> list[Point3D]:
        return [Point3D(0.0, 0.0, 0.0)]

    def update(
        self, points: list[Point3D], placement: Placement, placed: list[Placement], pallet: Pallet
    ) -> list[Point3D]:
        generated = [
            Point3D(placement.x2, placement.point.y, placement.point.z),
            Point3D(placement.point.x, placement.y2, placement.point.z),
            Point3D(placement.point.x, placement.point.y, placement.z2),
        ]
        unique = set(points + generated)

        def valid(point: Point3D) -> bool:
            if point.x < -EPS or point.y < -EPS or point.z < -EPS:
                return False
            if point.x >= pallet.length - EPS or point.y >= pallet.width - EPS or point.z >= pallet.max_height - EPS:
                return False
            for item in placed:
                if (
                    item.point.x - EPS <= point.x < item.x2 - EPS
                    and item.point.y - EPS <= point.y < item.y2 - EPS
                    and item.point.z - EPS <= point.z < item.z2 - EPS
                ):
                    return False
            return True

        return sorted((p for p in unique if valid(p)), key=lambda p: (p.z, p.y, p.x))
