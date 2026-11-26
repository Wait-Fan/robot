import unittest
import numpy as np
from ananno_phase2.robot_execution_constraints import RobotExecutionConstraintSet
from ananno_phase2.models import Box,Pallet,Placement,Point3D

def box(name,x,y,l,w,h):
    b=Box(name,l,w,h,1,name);return Placement(b,0,Point3D(x,y,0),b.orientations()[0],1)

class ToolPlacementFilterTests(unittest.TestCase):
    def constraints(self):
        c=RobotExecutionConstraintSet(Pallet(2240,1440,720))
        c.tool_config={'grasp_alignment':'center','tool_definition':{'kind':'box_envelope','size_m':[.6,.8,.25]},
            'box_T_tcp_rotation':np.diag([1,-1,-1,1]).tolist(),'tcp_offset_from_box_top_m':[0,0,0], 'length_scale_to_m':.001}
        return c
    def test_tool_overlap_with_tall_neighbor_rejects_otherwise_clear_box(self):
        c=self.constraints();tall=box('tall',0,0,500,350,480);short=box('short',0,350,500,350,120)
        result=c.validate(short,[tall],check_pattern=False)
        self.assertFalse(result.feasible);self.assertIn('吸盘',result.reason)
    def test_z90_rotates_asymmetric_tool_footprint(self):
        from dataclasses import replace
        c=self.constraints();tall=box('tall',0,0,100,200,480);candidate=box('candidate',350,0,100,200,120)
        self.assertTrue(c.validate(candidate,[tall],check_pattern=False).feasible)
        rotated=replace(candidate,orientation=candidate.box.orientations()[1])
        self.assertFalse(c.validate(rotated,[tall],check_pattern=False).feasible)
    def test_nonzero_tcp_offset_moves_tool_in_box_frame(self):
        c=self.constraints();tall=box('tall',0,0,500,350,480);short=box('short',0,350,500,350,120)
        self.assertFalse(c.validate(short,[tall],check_pattern=False).feasible)
        c.tool_config['tcp_offset_from_box_top_m']=[0,.3,0]
        self.assertTrue(c.validate(short,[tall],check_pattern=False).feasible)
    def test_metre_input_has_same_physical_penetration_decision(self):
        c=self.constraints();c.pallet=Pallet(2.24,1.44,.72);c.tool_config['length_scale_to_m']=1.
        self.assertFalse(c.validate(box('short',0,.35,.5,.35,.12),[box('tall',0,0,.5,.35,.48)],check_pattern=False).feasible)

    def test_clearance_or_equal_box_tops_still_pass(self):
        c=self.constraints();short=box('short',0,350,500,350,120)
        self.assertTrue(c.validate(short,[box('equal',0,0,500,350,120)],check_pattern=False).feasible)
        self.assertTrue(c.validate(box('away',0,1000,500,350,120),[box('tall',0,0,500,350,480)],check_pattern=False).feasible)

if __name__=='__main__':unittest.main()
