import unittest

from ananno_phase2.extreme_points import ExtremePointGenerator
from ananno_phase2.models import Box, Orientation, Pallet, Placement, Point3D


class ExtremePointTests(unittest.TestCase):
    def test_generates_filters_deduplicates_and_sorts_points(self):
        gen = ExtremePointGenerator()
        p = Placement(Box("A", 2, 3, 1), 0, Point3D(0, 0, 0), Orientation("Z0", 2, 3, 1), 1)
        points = gen.update([Point3D(0, 0, 0), Point3D(2, 0, 0)], p, [p], Pallet(4, 4, 3))
        self.assertEqual(points, [Point3D(2, 0, 0), Point3D(0, 3, 0), Point3D(0, 0, 1)])

    def test_filters_points_outside_pallet(self):
        gen = ExtremePointGenerator()
        p = Placement(Box("A", 2, 2, 1), 0, Point3D(0, 0, 0), Orientation("Z0", 2, 2, 1), 1)
        self.assertEqual(gen.update([], p, [p], Pallet(2, 2, 1)), [])


if __name__ == "__main__":
    unittest.main()
