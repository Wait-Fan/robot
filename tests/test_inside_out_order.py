from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest

from ananno_phase2.models import Box, Pallet, Placement, Point3D
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2 import robot_approach as module
from ananno_phase2.robot_approach import ApproachConfig, executable_sequence


def item(name, x=0, y=0, z=0, order=1):
    box = Box(name, 1, 1, 1, 1, name)
    return Placement(box, 0, Point3D(x, y, z), box.orientations()[0], order)


class InsideOutOrderTests(unittest.TestCase):
    def test_top_approach_prioritizes_far_side_for_all_four_outside_sides(self):
        for side, points, expected in [
            ('-Y', [(0, 0), (0, 1), (0, 2)], ['c', 'b', 'a']),
            ('+Y', [(0, 0), (0, 1), (0, 2)], ['a', 'b', 'c']),
            ('-X', [(0, 0), (1, 0), (2, 0)], ['c', 'b', 'a']),
            ('+X', [(0, 0), (1, 0), (2, 0)], ['a', 'b', 'c']),
        ]:
            with self.subTest(side=side):
                items = [item(name, x=x, y=y, order=i+1) for i, (name, (x, y)) in enumerate(zip('abc', points))]
                ordered, audit = executable_sequence(items, Pallet(3, 3, 3), PaperConfig(),
                    ApproachConfig('+Z', outside_side=side))
                self.assertIsNotNone(ordered, audit)
                self.assertEqual([p.box.id for p in ordered], expected)

    def test_inside_out_with_multiple_allowed_approach_sides(self):
        ordered, audit = executable_sequence([item('near'), item('far', y=2, order=2), item('middle', y=1, order=3)],
            Pallet(3, 3, 2), PaperConfig(), ApproachConfig(open_directions=['+Z', '-Y'], outside_side='-Y'))
        self.assertTrue(audit['passed'], audit)
        self.assertEqual([p.box.id for p in ordered], ['far', 'middle', 'near'])

    def test_support_and_blocking_dependencies_override_preference(self):
        # Complete the deep column across layers before the near floor box.
        ordered, audit = executable_sequence([item('upper', y=1, z=1), item('base', y=1, order=2), item('near', order=3)],
            Pallet(2, 2, 3), PaperConfig(), ApproachConfig('+Z', outside_side='-Y'))
        self.assertIsNotNone(ordered, audit)
        self.assertEqual([p.box.id for p in ordered], ['base', 'upper', 'near'])
        # Approach from -Y needs the far box before the near one even if the preference uses +Y.
        ordered, audit = executable_sequence([item('near'), item('far', y=1, order=2)],
            Pallet(2, 2, 2), PaperConfig(), ApproachConfig('-Y', outside_side='+Y'))
        self.assertIsNone(ordered, audit)  # Conflicting strict order is rejected, not relaxed.

    def test_auto_reference_uses_pallet_frame_including_rotation(self):
        infer = getattr(module, 'outside_side_from_workcell', None)
        self.assertIsNotNone(infer, 'automatic workcell reference is missing')
        pallet = Pallet(2, 1, 2)
        self.assertEqual(infer(pallet, [[1, 0, 0, -1], [0, 1, 0, .4], [0, 0, 1, 0], [0, 0, 0, 1]]), '-Y')
        # World robot origin corresponds to pallet x=3,y=.5 after a 90-degree yaw.
        self.assertEqual(infer(pallet, [[0, -1, 0, .5], [1, 0, 0, -3], [0, 0, 1, 0], [0, 0, 0, 1]]), '+X')
        self.assertIsNone(infer(pallet, None))
        self.assertIsNone(infer(pallet, [[1, 0, 0, -1], [0, 1, 0, -.5], [0, 0, 1, 0], [0, 0, 0, 1]]))

    def test_auto_reference_converts_mm_dimensions_to_workcell_metres(self):
        matrix = [[0, -1, 0, .5], [1, 0, 0, -3], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.assertEqual(module.outside_side_from_workcell(Pallet(2000, 1000, 1400), matrix,
                                                         length_scale_to_m=.001), '+X')

    def test_no_reference_preserves_legacy_order(self):
        ordered, audit = executable_sequence([item('near'), item('middle', y=1, order=2), item('far', y=2, order=3)],
            Pallet(3, 3, 2), PaperConfig(), ApproachConfig('+Z'))
        self.assertEqual([p.box.id for p in ordered], ['near', 'middle', 'far'])

    def test_final_pipeline_records_and_uses_inside_out_sequence(self):
        from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
        cfg = replace(PaperConfig(), population_size=4, mu=4, lambda_=4, generations=1, max_stagnation=1)
        packer = RobotTwoPhasePacker(Pallet(3, 1, 1), cfg, ApproachConfig('+Z', outside_side='-X'))
        result = packer.pack([Box(name, 1, 1, 1, 1, 'A') for name in 'abc'])
        self.assertEqual([p.point.x for p in result.placements], [2, 1, 0])
        self.assertEqual(packer.robot_diagnostics['sequencing_policy']['outside_side'], '-X')

    def test_final_robot_verification_receives_reordered_sequence(self):
        from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
        class Verifier:
            config = {'robot_name': 'test'}
            def __init__(self): self.checked = []
            def verify(self, placements, *args, **kwargs):
                self.checked.append([p.point.x for p in placements])
                return {'passed': True, 'assumptions': []}
        verifier = Verifier()
        cfg = replace(PaperConfig(), population_size=4, mu=4, lambda_=4, generations=1, max_stagnation=1)
        packer = RobotTwoPhasePacker(Pallet(3, 1, 1), cfg, ApproachConfig('+Z', outside_side='-X'), verifier)
        packer.pack([Box(name, 1, 1, 1, 1, 'A') for name in 'abc'])
        self.assertEqual(verifier.checked[-1], [2, 1, 0])

    def test_motion_failure_cannot_override_strict_inside_out(self):
        from ananno_phase2.robot_pipeline import RobotTwoPhasePacker
        class Verifier:
            config = {'robot_name': 'test'}
            def verify(self, placements, *args, **kwargs):
                passed = not placements or placements[0].point.x == 0
                return {'passed': passed, 'status': 'verified' if passed else 'rejected',
                        'reason': 'test_sequence_path_restriction', 'assumptions': []}
        cfg = replace(PaperConfig(), population_size=4, mu=4, lambda_=4, generations=1, max_stagnation=1, max_pallets=1)
        packer = RobotTwoPhasePacker(Pallet(3, 1, 1), cfg, ApproachConfig('+Z', outside_side='-X'), Verifier())
        from ananno_phase2.paper_pipeline import NoPaperSolution
        with self.assertRaises(NoPaperSolution):
            packer.pack([Box(name, 1, 1, 1, 1, 'A') for name in 'abc'])


if __name__=='__main__':unittest.main()
