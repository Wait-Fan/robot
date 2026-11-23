import unittest
from dataclasses import replace

from ananno_phase2.models import Box, Pallet
from ananno_phase2.packer import PackingCancelled
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_layers import PaperLayerBuilder


class PaperLayerTests(unittest.TestCase):
    def build(self, boxes, pallet=None, **config):
        return PaperLayerBuilder(pallet or Pallet(4, 4, 4),
                                 replace(PaperConfig(), **config)).build(boxes)

    def test_full_layers_stack_then_open_pallet_and_keep_global_order(self):
        boxes = [Box(str(i), 2, 2, 1, group="A") for i in range(12)]
        result = self.build(boxes, Pallet(4, 4, 2))
        self.assertEqual(result.pallet_count, 2)
        self.assertEqual(len(result.placements), 12)
        self.assertEqual(result.residuals, [])
        self.assertEqual([p.order for p in result.placements], list(range(1, 13)))
        self.assertEqual(sorted({(p.pallet_index, p.point.z) for p in result.placements}),
                         [(0, 0), (0, 1), (1, 0)])

    def test_residual_strip_uses_second_orientation_to_add_third_box(self):
        result = self.build([Box(str(i), 6, 4, 1) for i in range(3)],
                            Pallet(10, 10, 1), full_layer_fill=.7)
        self.assertEqual(len(result.placements), 3)
        self.assertEqual(sorted(p.orientation.code for p in result.placements),
                         ["Z0", "Z0", "Z90"])

    def test_orientation_tie_prefers_default_orientation(self):
        result = self.build([Box(str(i), 5, 2, 1) for i in range(10)],
                            Pallet(10, 10, 1))
        self.assertEqual(len(result.placements), 10)
        self.assertTrue(all(p.orientation.code == "Z0" for p in result.placements))

    def test_center_gap_shifting_reaches_both_pallet_edges(self):
        result = self.build([Box(str(i), 3, 3, 1) for i in range(9)],
                            Pallet(10, 10, 1), full_layer_fill=.8)
        self.assertEqual(len(result.placements), 9)
        self.assertEqual(max(p.x2 for p in result.placements), 10)
        self.assertEqual(max(p.y2 for p in result.placements), 10)
        self.assertEqual(min(p.point.x for p in result.placements), 0)
        self.assertEqual(min(p.point.y for p in result.placements), 0)

    def test_four_same_height_mixed_product_quarters_merge_to_one_full_layer(self):
        boxes = [Box(group, 2, 2, 1, group=group) for group in "ABCD"]
        boxes += [Box("tiny1", .1, .1, 1), Box("tiny2", .1, .1, 1)]
        result = self.build(boxes)
        self.assertEqual(len(result.placements), 4)
        self.assertEqual({p.point.z for p in result.placements}, {0})
        self.assertEqual(result.diagnostics["merged_quarters"], 2)
        self.assertEqual(result.diagnostics["merged_halves"], 1)
        self.assertEqual(result.diagnostics["layers_placed"]["full"], 1)

    def test_different_height_quarters_balance_lowest_regions(self):
        boxes = [Box("A", 2, 2, 1, group="A"),
                 Box("B", 2, 2, 2, group="B"),
                 Box("C", 2, 2, 3, group="C")]
        boxes += [Box("tiny1", .1, .1, 1), Box("tiny2", .1, .1, 1)]
        result = self.build(boxes)
        self.assertEqual(len(result.placements), 3)
        self.assertEqual({p.point.z for p in result.placements}, {0})
        self.assertEqual(len({(p.point.x, p.point.y) for p in result.placements}), 3)

    def test_layer_and_residual_ids_conserved_even_for_oversized_items(self):
        boxes = [Box(str(i), 2, 2, 1) for i in range(5)]
        boxes += [Box("tiny", .1, .1, 1), Box("too-high", 4, 4, 99)]
        result = self.build(boxes)
        packed = [p.box.id for p in result.placements]
        residual = [b.id for b in result.residuals]
        self.assertEqual(len(packed), 5)
        self.assertEqual(set(residual), {"tiny", "too-high"})
        self.assertEqual(sorted(packed + residual), sorted(b.id for b in boxes))

    def test_sparse_types_remain_residual_instead_of_creating_underfilled_layers(self):
        boxes = [Box("A", 1, 1, 1, group="A"), Box("B", 1, 1, 1, group="B")]
        result = self.build(boxes, Pallet(10, 10, 2))
        self.assertEqual(result.placements, [])
        self.assertEqual(result.residuals, boxes)
        self.assertEqual(result.pallet_count, 0)

    def test_quarter_fill_threshold_accepts_85_percent_and_rejects_84_percent(self):
        enough = [Box(str(i), 4.25, 5, 1) for i in range(2)]
        sparse = [Box(str(i), 4.2, 5, 1) for i in range(2)]
        accepted = self.build(enough, Pallet(10, 10, 2))
        rejected = self.build(sparse, Pallet(10, 10, 2))
        self.assertEqual(len(accepted.placements), 2)
        self.assertEqual(accepted.diagnostics["layers_generated"]["quarter"], 2)
        self.assertEqual(rejected.placements, [])
        self.assertEqual(rejected.residuals, sparse)

    def test_full_and_half_layers_require_90_percent_fill(self):
        enough = [Box(str(i), 4.5, 10, 1) for i in range(3)]
        sparse = [Box(str(i), 4.49, 10, 1) for i in range(3)]
        accepted = self.build(enough, Pallet(10, 10, 2))
        rejected = self.build(sparse, Pallet(10, 10, 2))
        self.assertEqual(len(accepted.placements), 3)
        self.assertEqual(accepted.diagnostics["layers_generated"]["full"], 1)
        self.assertEqual(accepted.diagnostics["layers_generated"]["half"], 1)
        self.assertEqual(rejected.placements, [])
        self.assertEqual(rejected.residuals, sparse)

    def test_unstable_quarter_is_residual_and_does_not_create_phantom_pallet(self):
        boxes = [Box("A", 2, 2, 1, weight=100),
                 Box("tiny1", .1, .1, 1), Box("tiny2", .1, .1, 1)]
        result = self.build(boxes, pallet_weight=0, com_deviation_fraction=.1)
        self.assertEqual(result.placements, [])
        self.assertEqual(result.residuals, boxes)
        self.assertEqual(result.pallet_count, 0)

    def test_duplicate_ids_rejected_and_cancellation_propagates(self):
        with self.assertRaises(ValueError):
            self.build([Box("same", 2, 2, 1), Box("same", 2, 2, 1)])
        with self.assertRaises(PackingCancelled):
            PaperLayerBuilder(Pallet(4, 4, 4), PaperConfig(),
                              cancelled=lambda: True).build([Box("A", 2, 2, 1)])

    def test_entirely_heterogeneous_order_bypasses_phase1(self):
        boxes = [Box(group, 2, 2, 1, group=group) for group in "ABCD"]
        result = self.build(boxes)
        self.assertEqual(result.placements, [])
        self.assertEqual(result.residuals, boxes)
        self.assertEqual(result.diagnostics["phase1_box_count"], 0)

    def test_full_balanced_layer_com_is_checked_as_batch_not_box_prefix(self):
        boxes = [Box(str(i), 2, 2, 1, weight=100) for i in range(4)]
        result = self.build(boxes, pallet_weight=0, com_deviation_fraction=.05)
        self.assertEqual(len(result.placements), 4)
        self.assertEqual(result.residuals, [])

    def test_mirror_interlock_maximizes_distance_among_feasible_variants(self):
        boxes = [Box(str(i), 6, 4, 1) for i in range(6)]
        result = self.build(boxes, Pallet(10, 10, 2), full_layer_fill=.7)
        self.assertEqual(len(result.placements), 6)
        second = result.diagnostics["layer_placements"][1]
        # On this hand-checkable pattern, X reflection has Hausdorff 2,
        # original has 0, and the two Y-reflected variants lack support.
        self.assertTrue(second["mirror_x"])
        self.assertFalse(second["mirror_y"])
        self.assertEqual(second["hausdorff_distance"], 2)
        self.assertEqual(second["feasible_mirror_count"], 2)


if __name__ == "__main__":
    unittest.main()
