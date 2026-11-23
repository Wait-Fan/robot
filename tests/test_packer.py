import unittest

from ananno_phase2.models import Box, Pallet
from ananno_phase2.packer import FixedSequencePacker


class PackerTests(unittest.TestCase):
    def test_rotates_when_only_z90_fits(self):
        result = FixedSequencePacker(Pallet(2, 3, 2)).pack([Box("A", 3, 2, 1)])
        self.assertEqual(result.placements[0].orientation.code, "Z90")

    def test_preserves_sequence_and_stacks_with_full_support(self):
        boxes = [Box("A", 2, 2, 1), Box("B", 2, 2, 1)]
        result = FixedSequencePacker(Pallet(2, 2, 2)).pack(boxes, ["B", "A"])
        self.assertEqual([p.box.id for p in result.placements], ["B", "A"])
        self.assertEqual(result.placements[1].point.z, 1)

    def test_opens_second_pallet_and_reports_oversized_once(self):
        result = FixedSequencePacker(Pallet(2, 2, 1)).pack([Box("A", 2, 2, 1), Box("B", 2, 2, 1)])
        self.assertEqual(result.pallet_count, 2)
        oversized = FixedSequencePacker(Pallet(2, 2, 2)).pack([Box("X", 99, 99, 99)])
        self.assertEqual(len(oversized.unplaced), 1)
        self.assertLessEqual(oversized.pallet_count, 1)

    def test_unknown_and_duplicate_sequence_ids_are_rejected(self):
        packer = FixedSequencePacker(Pallet(2, 2, 2))
        with self.assertRaises(ValueError):
            packer.pack([Box("A", 1, 1, 1)], ["B"])
        with self.assertRaises(ValueError):
            packer.pack([Box("A", 1, 1, 1)], ["A", "A"])

    def test_explicit_empty_sequence_is_rejected_for_nonempty_boxes(self):
        with self.assertRaises(ValueError):
            FixedSequencePacker(Pallet(2, 2, 2)).pack([Box("A", 1, 1, 1)], [])

    def test_oversized_precheck_uses_same_tolerance_as_bounds(self):
        result = FixedSequencePacker(Pallet(1, 1, 1)).pack([Box("A", 1.0000000005, 1, 1)])
        self.assertEqual(len(result.placements), 1)
        self.assertEqual(result.unplaced, [])


if __name__ == "__main__":
    unittest.main()
