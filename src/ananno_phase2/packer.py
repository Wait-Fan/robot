from __future__ import annotations

from typing import Callable

from .constraints import EPS, ConstraintSet
from .extreme_points import ExtremePointGenerator
from .models import Box, PackingResult, Pallet, Placement, UnplacedItem


class PackingCancelled(Exception):
    """用户协作停止，部分计算不应作为完成结果保存。"""


def check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise PackingCancelled("已停止装箱计算")


class FixedSequencePacker:
    def __init__(self, pallet: Pallet, min_support_ratio: float = 1.0):
        self.pallet = pallet
        self.constraints = ConstraintSet(min_support_ratio)
        self.generator = ExtremePointGenerator()

    def pack(self, boxes: list[Box], sequence: list[str] | None = None, *,
             progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> PackingResult:
        ids = [box.id for box in boxes]
        if len(ids) != len(set(ids)):
            raise ValueError("箱体 id 不能重复")
        order = ids if sequence is None else sequence
        if len(order) != len(set(order)):
            raise ValueError("装箱序列包含重复 id")
        if set(order) != set(ids):
            missing = set(ids) - set(order)
            unknown = set(order) - set(ids)
            raise ValueError(f"装箱序列与箱体不匹配；缺失={sorted(missing)}，未知={sorted(unknown)}")

        by_id = {box.id: box for box in boxes}
        pallets: list[dict[str, list]] = []
        placements: list[Placement] = []
        unplaced: list[UnplacedItem] = []
        check_cancelled(cancelled)
        if progress:
            progress(0, len(order))

        for order_index, box_id in enumerate(order, 1):
            check_cancelled(cancelled)
            box = by_id[box_id]
            if not any(
                o.length <= self.pallet.length + EPS
                and o.width <= self.pallet.width + EPS
                and o.height <= self.pallet.max_height + EPS
                for o in box.orientations()
            ):
                unplaced.append(UnplacedItem(box, "两个允许的 Z 轴姿态均无法装入空托盘"))
                if progress:
                    progress(order_index, len(order))
                continue

            accepted = None
            for pallet_index, state in enumerate(pallets):
                accepted = self._try_place(box, order_index, pallet_index, state, cancelled)
                if accepted:
                    break
            if accepted is None:
                state = {"placements": [], "points": self.generator.initial_points()}
                pallets.append(state)
                accepted = self._try_place(box, order_index, len(pallets) - 1, state, cancelled)
            if accepted is None:
                unplaced.append(UnplacedItem(box, "简化 EP 候选中没有满足约束的位置"))
            else:
                placements.append(accepted)
            if progress:
                progress(order_index, len(order))
        check_cancelled(cancelled)
        return PackingResult(placements, unplaced, self.pallet)

    def _try_place(self, box: Box, order: int, pallet_index: int, state: dict,
                   cancelled: Callable[[], bool] | None = None) -> Placement | None:
        for point in list(state["points"]):
            check_cancelled(cancelled)
            for orientation in box.orientations():
                candidate = Placement(box, pallet_index, point, orientation, order)
                if self.constraints.validate(candidate, state["placements"], self.pallet).feasible:
                    state["placements"].append(candidate)
                    remaining = [p for p in state["points"] if p != point]
                    state["points"] = self.generator.update(remaining, candidate, state["placements"], self.pallet)
                    return candidate
        return None
