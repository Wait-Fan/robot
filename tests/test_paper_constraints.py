import unittest
from dataclasses import replace

from ananno_phase2.models import Box,Pallet,Placement,Point3D
from ananno_phase2.paper_config import PaperConfig
from ananno_phase2.paper_constraints import PaperConstraintSet,item_compactness,support_details


def item(name,x,y,z,l,w,h,weight=1):
    box=Box(name,l,w,h,weight)
    return Placement(box,0,Point3D(x,y,z),box.orientations()[0],1)


class PaperConstraintTests(unittest.TestCase):
    def test_area_and_inset_corner_rules_are_combined(self):
        candidate=item("top",0,0,1,10,10,1)
        strips=[item("L",0,0,0,2,10,1),item("R",8,0,0,2,10,1)]
        self.assertEqual(support_details(candidate,strips,.01),(.4,4))
        constraints=PaperConstraintSet(Pallet(10,10,10),PaperConfig())
        self.assertTrue(constraints.validate(candidate,strips).feasible)
        middle=[item("M",3,0,0,4,10,1)]
        self.assertFalse(constraints.validate(candidate,middle,check_pattern=False).feasible)
        self.assertTrue(constraints.validate(candidate,[item("S",0,0,0,7.5,10,1)]).feasible)
        self.assertFalse(constraints.validate(candidate,[item("S",0,0,0,6,10,1)]).feasible)

    def test_final_mass_center_and_tipping(self):
        config=replace(PaperConfig(),pallet_weight=0,com_deviation_fraction=.1)
        constraints=PaperConstraintSet(Pallet(10,10,10),config)
        left=item("a",0,0,0,2,2,2,100)
        right=item("b",8,8,0,2,2,2,100)
        self.assertTrue(constraints.validate_pallet([left,right]).feasible)
        self.assertFalse(constraints.validate_pallet([left,replace(right,box=replace(right.box,weight=1))]).feasible)
        high=item("tower",4,4,0,2,2,10,1)
        dynamic=PaperConstraintSet(Pallet(10,10,10),replace(config,acceleration_x=20))
        self.assertFalse(dynamic.validate_pallet([high]).feasible)

    def test_vertex_alignment_and_face_contact_compactness(self):
        constraints=PaperConstraintSet(Pallet(10,10,10),PaperConfig())
        self.assertFalse(constraints.validate(item("floating-pattern",2,2,0,1,1,1),[]).feasible)
        a,b=item("a",0,0,0,1,1,1),item("b",1,0,0,1,1,1)
        self.assertTrue(constraints.validate(b,[a]).feasible)
        self.assertAlmostEqual(item_compactness(a,[a,b]),1/3)
        self.assertAlmostEqual(item_compactness(a,[a]),1/6)

    def test_config_rejects_non_finite(self):
        with self.assertRaises(ValueError): PaperConfig(pallet_weight=float("nan"))
