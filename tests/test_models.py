import unittest

from ananno_phase2.models import Box, Pallet


class ModelTests(unittest.TestCase):
    def test_only_two_z_axis_orientations_preserve_height(self):
        box = Box("A", 2, 3, 4)
        self.assertEqual(
            [(o.code, o.length, o.width, o.height) for o in box.orientations()],
            [("Z0", 2, 3, 4), ("Z90", 3, 2, 4)],
        )

    def test_square_footprint_does_not_duplicate_orientation(self):
        self.assertEqual(len(Box("A", 2, 2, 4).orientations()), 1)

    def test_non_positive_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            Box("A", 0, 2, 3)
        with self.assertRaises(ValueError):
            Pallet(2, -1, 3)


if __name__ == "__main__":
    unittest.main()
