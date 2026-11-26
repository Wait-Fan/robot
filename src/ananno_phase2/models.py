from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import math


def _positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0，实际为 {value}")


@dataclass(frozen=True, order=True)
class Point3D:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Orientation:
    code: str
    length: float
    width: float
    height: float


@dataclass(frozen=True)
class Box:
    id: str
    length: float
    width: float
    height: float
    weight: float = 0.0
    group: str = ""
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("箱体 id 不能为空")
        for name in ("length", "width", "height"):
            _positive(name, getattr(self, name))
        if self.weight < 0:
            raise ValueError("weight 不能为负数")

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    def orientations(self) -> tuple[Orientation, ...]:
        original = Orientation("Z0", self.length, self.width, self.height)
        if abs(self.length - self.width) <= 1e-9:
            return (original,)
        return (original, Orientation("Z90", self.width, self.length, self.height))


@dataclass(frozen=True)
class Pallet:
    length: float
    width: float
    max_height: float

    def __post_init__(self) -> None:
        for name in ("length", "width", "max_height"):
            _positive(name, getattr(self, name))

    @property
    def volume(self) -> float:
        return self.length * self.width * self.max_height

    def with_long_side_x(self) -> Pallet:
        """Explicit calculation-frame normalization; never rewrites saved placements."""
        if not all(math.isfinite(v) for v in (self.length,self.width,self.max_height)):
            raise ValueError('托盘尺寸必须是有限正数')
        return self if self.length>=self.width else Pallet(self.width,self.length,self.max_height)


@dataclass(frozen=True)
class Placement:
    box: Box
    pallet_index: int
    point: Point3D
    orientation: Orientation
    order: int

    @property
    def x2(self) -> float:
        return self.point.x + self.orientation.length

    @property
    def y2(self) -> float:
        return self.point.y + self.orientation.width

    @property
    def z2(self) -> float:
        return self.point.z + self.orientation.height


@dataclass(frozen=True)
class UnplacedItem:
    box: Box
    reason: str


@dataclass
class PackingResult:
    placements: list[Placement]
    unplaced: list[UnplacedItem]
    pallet: Pallet

    @property
    def pallet_count(self) -> int:
        return 0 if not self.placements else max(p.pallet_index for p in self.placements) + 1

    @property
    def utilization(self) -> float:
        if self.pallet_count == 0:
            return 0.0
        return sum(p.box.volume for p in self.placements) / (self.pallet_count * self.pallet.volume)
