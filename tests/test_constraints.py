import unittest

from ananno_phase2.constraints import aabb_overlap, fits_bounds, support_ratio
from ananno_phase2.models import Box, Orientation, Pallet, Placement, Point3D


def placed(name, x, y, z, length, width, height):
    box = Box(name, length, width, height)
    return Placement(box, 0, Point3D(x, y, z), Orientation("Z0", length, width, height), 1)


class ConstraintTests(unittest.TestCase):
    def test_exact_boundary_fits_but_overhang_does_not(self):
        pallet = Pallet(3, 2, 1)
        self.assertTrue(fits_bounds(placed("A", 0, 0, 0, 3, 2, 1), pallet))
        self.assertFalse(fits_bounds(placed("B", 0.0000001, 0, 0, 3, 2, 1), pallet))

    def test_face_contact_is_not_collision_but_volume_overlap_is(self):
        left = placed("A", 0, 0, 0, 2, 2, 2)
        self.assertFalse(aabb_overlap(left, placed("B", 2, 0, 0, 1, 2, 2)))
        self.assertTrue(aabb_overlap(left, placed("C", 1.9, 0, 0, 1, 2, 2)))

    def test_ground_and_union_support(self):
        self.assertEqual(support_ratio(placed("G", 0, 0, 0, 2, 2, 1), []), 1.0)
        candidate = placed("C", 0, 0, 1, 3, 2, 1)
        supports = [placed("A", 0, 0, 0, 2, 2, 1), placed("B", 1, 0, 0, 2, 2, 1)]
        self.assertAlmostEqual(support_ratio(candidate, supports), 1.0)
        half = placed("H", 0, 0, 1, 4, 2, 1)
        self.assertAlmostEqual(support_ratio(half, [supports[0]]), 0.5)


if __name__ == "__main__":
    unittest.main()
