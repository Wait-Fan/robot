import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'robot_runtime/site-packages'), str(ROOT/'src')]
import numpy as np
from ananno_phase2.ec66_model import EC66Model
from ananno_phase2.robot_rrt import rrt_connect

class ModelTests(unittest.TestCase):
    def setUp(self):
        self.robot = EC66Model(ROOT/'robot_models/robot_ec66/urdf/robot.ec66.urdf', ROOT/'robot_models/robot_config/config/robot_ec66.srdf')
    def test_joint_model_and_fk(self):
        self.assertEqual(len(self.robot.lower),6)
        pose=self.robot.fk([0]*6)
        self.assertEqual(pose.shape,(4,4))
        np.testing.assert_allclose(pose[3],[0,0,0,1])
        np.testing.assert_allclose(pose[:3,:3].T@pose[:3,:3],np.eye(3),atol=1e-6)
    def test_ik_round_trip(self):
        known=np.array([0.3,-0.2,0.6,-0.4,0.7,0.2])
        target=self.robot.fk(known)
        result=self.robot.ik(target,known+0.03,check_collision=False,iterations=250)
        self.assertIsNotNone(result)
        np.testing.assert_allclose(self.robot.fk(result),target,atol=0.002)
    def test_unreachable_ik_does_not_pass(self):
        target=np.eye(4);target[:3,3]=[100,100,100]
        self.assertIsNone(self.robot.ik(target,np.zeros(6),check_collision=False,iterations=30))
    def test_nonfinite_and_joint_limits(self):
        with self.assertRaises(ValueError):self.robot.fk([float('nan')]*6)
        self.assertFalse(self.robot.valid([999]*6))
    def test_obstacle_over_robot_is_detected(self):
        self.robot.set_obstacles([{'id':'wall','size':[5,5,5],'pose':np.eye(4).tolist()}])
        self.assertFalse(self.robot.valid([0]*6))
    def test_carried_box_tracks_tcp_pose(self):
        offset=np.eye(4);offset[:3,3]=[0,-.1,0]
        self.robot.attachment=([.01]*3,offset)
        q=np.array([.3,-.2,.6,-.4,.7,.2])
        self.robot.collisions(q)
        np.testing.assert_allclose(self.robot.data.geom_xpos[self.robot.held_id],(self.robot.fk(q)@offset)[:3,3],atol=1e-7)
    def test_flush_box_contact_is_allowed_but_overlap_is_rejected(self):
        a=self.robot.held_id
        pose=np.eye(4);pose[2,3]=-.01
        self.robot.set_obstacles([{'id':'support','size':[.01,.01,.02],'pose':pose}])
        a=self.robot.held_id;b=self.robot.world_geoms[0]
        self.robot.model.geom_size[a]=[.005]*3
        self.robot.data.mocap_pos[self.robot.held_mocap]=[0,0,.005]
        import mujoco
        mujoco.mj_kinematics(self.robot.model,self.robot.data)
        self.assertFalse(self.robot._box_overlap(a,b))
        self.robot.data.mocap_pos[self.robot.held_mocap]=[0,0,.004]
        mujoco.mj_kinematics(self.robot.model,self.robot.data)
        self.assertTrue(self.robot._box_overlap(a,b))

class RRTTests(unittest.TestCase):
    def test_route_around_wall(self):
        def valid(q):return not (abs(q[0])<.16 and q[1]<.6)
        result=rrt_connect([-0.8,0],[0.8,0],[-1,-1],[1,1],valid,seed=3,max_iterations=4000,step=.15,resolution=.025)
        self.assertIsNotNone(result)
        self.assertGreater(max(q[1] for q in result),.6)
        for a,b in zip(result,result[1:]):
            for t in np.linspace(0,1,30):self.assertTrue(valid((1-t)*np.array(a)+t*np.array(b)))
    def test_invalid_endpoint(self):
        self.assertIsNone(rrt_connect([0,0],[1,1],[-1,-1],[1,1],lambda q:False,max_iterations=10))

if __name__=='__main__':unittest.main()
