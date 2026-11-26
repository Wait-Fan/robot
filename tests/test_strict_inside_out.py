import unittest
from dataclasses import replace
from ananno_phase2.models import Pallet
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.robot_approach import ApproachConfig,executable_sequence
from ananno_phase2.robot_pipeline import _validated_sequence
from tests.test_inside_out_order import item

class StrictInsideOutTests(unittest.TestCase):
    def test_cannot_skip_unaligned_far_box_to_place_near_box(self):
        ordered,audit=executable_sequence([item('near'),item('far',y=1.5,order=2)],Pallet(3,3,2),PaperConfig(),ApproachConfig('+Z',outside_side='-Y'))
        self.assertIsNone(ordered);self.assertFalse(audit['passed'])
        self.assertFalse(audit['sequencing_policy']['preference_only'])

    def test_alignment_is_layout_connected_without_forcing_near_first(self):
        items=[item('near'),item('far',y=1,order=2)]
        ordered,audit=executable_sequence(items,Pallet(3,3,2),PaperConfig(),ApproachConfig('+Z',outside_side='-Y'))
        self.assertTrue(audit['passed']);self.assertEqual([p.box.id for p in ordered],['far','near'])

    def test_motion_failure_never_falls_back_to_near_first(self):
        class V:
            def __init__(self):self.orders=[]
            def verify(self,placements,*a,**kw):
                self.orders.append([p.box.id for p in placements])
                return {'passed':placements[0].box.id=='near','status':'unverified','reason':'test_path'}
        v=V();items=[item('near'),item('far',y=2,order=2)]
        ordered,audit,_=_validated_sequence(items,Pallet(3,3,2),PaperConfig(),ApproachConfig('+Z',outside_side='-Y'),v)
        self.assertIsNone(ordered);self.assertEqual(v.orders,[['far','near']])

    def test_generated_layout_can_be_anchored_at_far_corner(self):
        from ananno_phase2.robot_approach import anchor_inside_out
        pallet=Pallet(3,3,2);source=[item('a'),item('b',y=1,order=2)]
        mirrored=anchor_inside_out(source,pallet,'-Y')
        self.assertEqual([p.point.y for p in mirrored],[2,1])
        ordered,audit=executable_sequence(mirrored,pallet,PaperConfig(),ApproachConfig('+Z',outside_side='-Y'))
        self.assertTrue(audit['passed']);self.assertEqual([p.box.id for p in ordered],['a','b'])

if __name__=='__main__':unittest.main()
