"""Paper Phase 1: homogeneous layers, same-height merging and stable blocks.

The paper leaves the precise residual-strip partition and center-line shift
unspecified. We test both disjoint partitions of the two residual strips, then
insert unused extent at the nearest unobstructed center cut. These deterministic
choices are recorded as implementation assumptions, not author-source code.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from math import floor, hypot
from typing import Callable

from .constraints import EPS
from .models import Box, Orientation, Pallet, Placement, Point3D
from .packer import check_cancelled
from .paper_config import PaperConfig
from .paper_constraints import PaperConstraintSet, type_key


@dataclass
class LayerBuildResult:
    placements: list[Placement]
    residuals: list[Box]
    pallet_count: int
    diagnostics: dict


@dataclass(frozen=True)
class _Cell:
    box: Box
    x: float
    y: float
    orientation: Orientation


@dataclass(frozen=True)
class _Layer:
    kind: str
    length: float
    width: float
    height: float
    cells: tuple[_Cell, ...]

    @property
    def area(self):
        return sum(c.orientation.length * c.orientation.width for c in self.cells)


def _hausdorff(a, b):
    """Symmetric Euclidean Hausdorff distance between finite XY vertex sets."""
    if not a or not b:
        return 0.0
    def directed(source, target):
        return max(min(hypot(x - u, y - v) for u, v in target) for x, y in source)
    return max(directed(a, b), directed(b, a))


class PaperLayerBuilder:
    def __init__(self, pallet: Pallet, config: PaperConfig,
                 cancelled: Callable[[], bool] | None = None,
                 log: Callable[[str], None] | None = None):
        self.pallet = pallet
        self.config = config
        self.cancelled = cancelled
        self.log = log
        self.constraints = PaperConstraintSet(pallet, config)

    def build(self, boxes: list[Box]) -> LayerBuildResult:
        check_cancelled(self.cancelled)
        if len({b.id for b in boxes}) != len(boxes):
            raise ValueError("箱体 id 不能重复")
        diagnostics = {
            "layers_generated": {"full": 0, "half": 0, "quarter": 0},
            "layers_placed": {"full": 0, "half": 0, "quarter": 0},
            "merged_quarters": 0, "merged_halves": 0,
            "layer_placements": [], "rejected_layers": 0,
            "phase1_box_count": 0, "placed_count": 0,
            "residual_count": len(boxes), "heterogeneous_bypass": False,
            "pattern_assumptions": [
                "Both disjoint residual-strip partitions are evaluated",
                "Unused extent is inserted at an unobstructed cut nearest the center line",
                "Layer placement validates local constraints then batch final COM",
            ],
        }
        groups = defaultdict(list)
        for box in boxes:
            groups[type_key(box)].append(box)
        if all(len(group) == 1 for group in groups.values()):
            diagnostics["heterogeneous_bypass"] = bool(boxes)
            check_cancelled(self.cancelled)
            return LayerBuildResult([], list(boxes), 0, diagnostics)
        layers = []
        for group in groups.values():
            check_cancelled(self.cancelled)
            remaining = list(group)
            if remaining[0].height > self.pallet.max_height + EPS:
                continue
            for kind, length, width, fill in self._layer_sizes():
                while remaining:
                    check_cancelled(self.cancelled)
                    # This also bounds pattern enumeration for tiny quantities.
                    if len(remaining) * remaining[0].length * remaining[0].width + EPS < fill * length * width:
                        break
                    cells = self._pattern(remaining, length, width)
                    occupied = sum(c.orientation.length * c.orientation.width for c in cells)
                    if not cells or occupied + EPS < fill * length * width:
                        break
                    layer = _Layer(kind, length, width, remaining[0].height, tuple(cells))
                    layers.append(layer)
                    diagnostics["layers_generated"][kind] += 1
                    remaining = remaining[len(cells):]
        layers = self._merge(layers, diagnostics)
        pallets: list[list[Placement]] = []
        placements = []
        for kind in ("full", "half", "quarter"):
            candidates = sorted((l for l in layers if l.kind == kind), key=self._layer_sort)
            for layer in candidates:
                check_cancelled(self.cancelled)
                accepted = None
                pallet_index = 0
                event = None
                # Existing fullest blocks are considered first. Within a block,
                # halves/quadrants are tried in ascending local height.
                pallet_order = sorted(range(len(pallets)),
                                      key=lambda i: (-max(p.z2 for p in pallets[i]), i))
                for pallet_index in pallet_order:
                    accepted, event = self._place_layer(layer, pallet_index, pallets[pallet_index], len(placements))
                    if accepted is not None:
                        break
                if accepted is None and len(pallets) < self.config.max_pallets:
                    pallet_index = len(pallets)
                    accepted, event = self._place_layer(layer, pallet_index, [], len(placements))
                    if accepted is not None:
                        pallets.append([])
                if accepted is None:
                    diagnostics["rejected_layers"] += 1
                    continue
                pallets[pallet_index].extend(accepted)
                placements.extend(accepted)
                diagnostics["layers_placed"][kind] += 1
                diagnostics["layer_placements"].append(event)
        packed_ids = {p.box.id for p in placements}
        residuals = [b for b in boxes if b.id not in packed_ids]
        diagnostics["placed_count"] = len(placements)
        diagnostics["phase1_box_count"] = len(placements)
        diagnostics["residual_count"] = len(residuals)
        if self.log:
            self.log(f"Phase 1: {len(placements)} boxes in layers, {len(residuals)} residual boxes")
        check_cancelled(self.cancelled)
        return LayerBuildResult(placements, residuals, len(pallets), diagnostics)

    def _layer_sizes(self):
        p, c = self.pallet, self.config
        return (("full", p.length, p.width, c.full_layer_fill),
                ("half", p.length / 2, p.width, c.half_layer_fill),
                ("quarter", p.length / 2, p.width / 2, c.quarter_layer_fill))

    @staticmethod
    def _layer_sort(layer):
        return (-layer.area, -sum(c.box.weight for c in layer.cells),
                len({type_key(c.box) for c in layer.cells}))

    def _pattern(self, boxes, length, width):
        sample = boxes[0]
        variants = []
        for orientation in sample.orientations():
            check_cancelled(self.cancelled)
            other = next((o for o in sample.orientations() if o.code != orientation.code), orientation)
            nx = floor((length + EPS) / orientation.length)
            ny = floor((width + EPS) / orientation.width)
            if nx == 0 or ny == 0:
                continue
            for vertical_first in (True, False):
                coordinates = []
                def grid(x, y, span_x, span_y, o):
                    cols = floor((span_x + EPS) / o.length)
                    rows = floor((span_y + EPS) / o.width)
                    for iy in range(min(rows, len(boxes))):
                        check_cancelled(self.cancelled)
                        for ix in range(min(cols, len(boxes) - len(coordinates))):
                            coordinates.append((x + ix * o.length, y + iy * o.width, o))
                        if len(coordinates) == len(boxes):
                            return
                grid(0, 0, length, width, orientation)
                used_x, used_y = nx * orientation.length, ny * orientation.width
                if vertical_first:
                    grid(used_x, 0, length - used_x, width, other)
                    grid(0, used_y, used_x, width - used_y, other)
                else:
                    grid(0, used_y, length, width - used_y, other)
                    grid(used_x, 0, length - used_x, used_y, other)
                variants.append([_Cell(boxes[i], x, y, o) for i, (x, y, o) in enumerate(coordinates)])
        if not variants:
            return []
        best = max(variants, key=lambda cells: (len(cells), sum(c.orientation.code == "Z0" for c in cells)))
        return self._center_gaps(best, length, width)

    @staticmethod
    def _center_gaps(cells, length, width):
        for axis, extent in (("x", length), ("y", width)):
            size = "length" if axis == "x" else "width"
            spans = [(getattr(c, axis), getattr(c, axis) + getattr(c.orientation, size)) for c in cells]
            occupied = max(high for _, high in spans)
            gap = extent - occupied
            if gap <= EPS:
                continue
            cuts = {v for span in spans for v in span if EPS < v < occupied - EPS}
            legal = [cut for cut in cuts if not any(low + EPS < cut < high - EPS for low, high in spans)]
            if not legal:
                continue
            cut = min(legal, key=lambda v: (abs(v + gap / 2 - extent / 2), v))
            cells = [replace(c, **{axis: getattr(c, axis) + gap})
                     if getattr(c, axis) >= cut - EPS else c for c in cells]
        return cells

    def _merge(self, layers, diagnostics):
        for source, target, axis, counter in (("quarter", "half", "y", "merged_quarters"),
                                               ("half", "full", "x", "merged_halves")):
            selected = sorted((l for l in layers if l.kind == source),
                              key=lambda l: (l.height, self._layer_sort(l)))
            layers = [l for l in layers if l.kind != source]
            while selected:
                check_cancelled(self.cancelled)
                first = selected.pop(0)
                partner = next((i for i, l in enumerate(selected) if abs(first.height - l.height) <= EPS), None)
                if partner is None:
                    layers.append(first)
                    continue
                second = selected.pop(partner)
                dx, dy = (first.length, 0) if axis == "x" else (0, first.width)
                cells = first.cells + tuple(replace(c, x=c.x + dx, y=c.y + dy) for c in second.cells)
                layers.append(_Layer(target, first.length * (2 if axis == "x" else 1),
                                     first.width * (2 if axis == "y" else 1), first.height, cells))
                diagnostics[counter] += 1
        return layers

    def _regions(self, layer, placed):
        count_x = 1 if layer.kind == "full" else 2
        count_y = 2 if layer.kind == "quarter" else 1
        regions = []
        for iy in range(count_y):
            for ix in range(count_x):
                x, y = ix * layer.length, iy * layer.width
                overlaps = [p for p in placed if p.point.x < x + layer.length - EPS and p.x2 > x + EPS
                            and p.point.y < y + layer.width - EPS and p.y2 > y + EPS]
                z = max((p.z2 for p in overlaps), default=0.0)
                regions.append((z, iy * count_x + ix, x, y))
        return sorted(regions)

    def _place_layer(self, layer, pallet_index, placed, start_order):
        for z, region_index, x, y in self._regions(layer, placed):
            check_cancelled(self.cancelled)
            if z + layer.height > self.pallet.max_height + EPS:
                continue
            supporting = [p for p in placed if abs(p.z2 - z) <= EPS
                          and p.point.x < x + layer.length - EPS and p.x2 > x + EPS
                          and p.point.y < y + layer.width - EPS and p.y2 > y + EPS]
            lower_vertices = {(px, py) for p in supporting
                              for px in (p.point.x, p.x2) for py in (p.point.y, p.y2)}
            feasible = []
            for mirror_x, mirror_y in ((False, False), (True, False), (False, True), (True, True)):
                check_cancelled(self.cancelled)
                pending = []
                for cell in layer.cells:
                    px = layer.length - cell.x - cell.orientation.length if mirror_x else cell.x
                    py = layer.width - cell.y - cell.orientation.width if mirror_y else cell.y
                    pending.append(Placement(cell.box, pallet_index, Point3D(x + px, y + py, z), cell.orientation, 0))
                accepted = []
                # Reflections can reverse the traversal. Greedily replay local
                # alignment dependencies so exported order is executable.
                while pending:
                    check_cancelled(self.cancelled)
                    found = next((i for i, candidate in enumerate(pending)
                                  if self.constraints.validate(candidate, placed + accepted).feasible), None)
                    if found is None:
                        break
                    accepted.append(replace(pending.pop(found), order=start_order + len(accepted) + 1))
                if pending or not self.constraints.validate_pallet(placed + accepted).feasible:
                    continue
                upper_vertices = {(px, py) for p in accepted
                                  for px in (p.point.x, p.x2) for py in (p.point.y, p.y2)}
                distance = _hausdorff(lower_vertices, upper_vertices)
                feasible.append((distance, accepted, mirror_x, mirror_y))
            if feasible:
                distance, accepted, mx, my = max(feasible, key=lambda variant: variant[0])
                return accepted, {"kind": layer.kind, "pallet_index": pallet_index,
                                  "region": region_index, "z": z, "mirror_x": mx,
                                  "mirror_y": my, "hausdorff_distance": distance,
                                  "feasible_mirror_count": len(feasible),
                                  "box_ids": [p.box.id for p in accepted]}
        return None, None
