from __future__ import annotations

from typing import Callable, Protocol

from .models import Box, PackingResult


class SequenceOptimizer(Protocol):
    def optimize(self, boxes: list[Box], evaluator: Callable[[list[str]], PackingResult]) -> list[str]: ...


class FixedSequenceOptimizer:
    def optimize(self, boxes: list[Box], evaluator: Callable[[list[str]], PackingResult]) -> list[str]:
        return [box.id for box in boxes]


class DeapSequenceOptimizer:
    """后续 DEAP GA 的稳定接口；当前阶段明确不伪装为完整论文 GA。"""

    def optimize(self, boxes: list[Box], evaluator: Callable[[list[str]], PackingResult]) -> list[str]:
        try:
            import deap  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("未安装可选依赖 DEAP；请运行 pip install -r requirements-ga.txt") from exc
        raise NotImplementedError("初版 GA 尚未启用；固定序列 EP 复现不受影响")
