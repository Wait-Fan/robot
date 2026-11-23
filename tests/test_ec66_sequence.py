import json
import tempfile
import unittest
from types import SimpleNamespace
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'robot_runtime/site-packages'),str(ROOT/'src')]
import numpy as np
from ananno_phase2.ec66_model import EC66Model
from ananno_phase2.robot_offline import OfflineRobotVerifier
from ananno_phase2.models import Box,Pallet,Placement,Point3D
from ananno_phase2.robot_approach import ApproachConfig

def scene_config():
    urdf=ROOT/'robot_models/robot_ec66/urdf/robot.ec66.urdf';srdf=ROOT/'robot_models/robot_config/config/robot_ec66.srdf'
    robot=EC66Model(urdf,srdf)
    q=np.array([-1.1065326432909561,1.2716793411826595,-1.6921440574260396,-3.017512418154384,-.629099561655961,-.5090058597157823]);tcp=robot.fk(q);frame=np.eye(4)
    center_in_tcp=np.array([0.,-.085019,-.005])
    box_to_tcp=-tcp[:3,:3]@center_in_tcp
    frame[:3,3]=tcp[:3,3]-np.array([.005,.005,.005])-box_to_tcp+[.04,0,0]
    rotation=np.eye(4);rotation[:3,:3]=tcp[:3,:3]
    return {'urdf':str(urdf),'srdf':str(srdf),'length_scale_to_m':.001,
        'base_T_pallet':frame.tolist(),'pick_tcp_pose':tcp.tolist(),
        'box_T_tcp_rotation':rotation.tolist(),'tcp_offset_from_box_top_m':(box_to_tcp-np.array([0,0,.005])).tolist(),'initial_joints_rad':q.tolist(),
        'approach_distance_m':.002,'path_budget_seconds':3.,'calibration_status':'software_test_only'}

class SequenceTests(unittest.TestCase):
    def test_cartesian_edge_sampling_can_be_cancelled(self):
        verifier=OfflineRobotVerifier.__new__(OfflineRobotVerifier)
        verifier.path_seconds=2.;verifier.resolution=1e-12
        verifier.robot=SimpleNamespace(valid=lambda q:True,ik=lambda *a,**k:np.ones(6)*.001,fk=lambda q:np.eye(4))
        count=[0]
        def cancelled():count[0]+=1;return count[0]>3
        target=np.eye(4);target[2,3]=.01
        with self.assertRaises(InterruptedError):verifier._move(np.zeros(6),target,linear=True,cancelled=cancelled)
        self.assertLess(count[0],10)
    def test_fingerprint_covers_srdf_content(self):
        config=scene_config()
        with tempfile.TemporaryDirectory() as folder:
            srdf=Path(folder)/'robot.srdf';srdf.write_bytes(Path(config['srdf']).read_bytes());config['srdf']=str(srdf)
            path=Path(folder)/'scene.json';path.write_text(json.dumps(config),encoding='utf-8')
            first=OfflineRobotVerifier(path).model_fingerprint
            srdf.write_bytes(srdf.read_bytes()+b'\n')
            second=OfflineRobotVerifier(path).model_fingerprint
            self.assertNotEqual(first,second)
    def test_linear_move_rejects_invalid_start_even_if_next_sample_is_clear(self):
        config=scene_config()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(config),encoding='utf-8')
            verifier=OfflineRobotVerifier(path)
            verifier.robot.set_obstacles([{'id':'wall','size':[5,5,5],'pose':np.eye(4).tolist()}])
            trajectory,reason=verifier._move(config['initial_joints_rad'],np.array(config['pick_tcp_pose']),linear=True)
            self.assertIsNone(trajectory)
            self.assertEqual(reason,'motion_start_state_in_collision')
    def test_interleaved_input_does_not_forget_previous_pallet_boxes(self):
        config=scene_config()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(config),encoding='utf-8')
            verifier=OfflineRobotVerifier(path)
            a,b,c=[Box(name,10,10,10) for name in ['A','B','C']]
            sequence=[Placement(a,0,Point3D(0,0,0),a.orientations()[0],1),Placement(c,1,Point3D(0,0,0),c.orientations()[0],2),Placement(b,0,Point3D(15,0,0),b.orientations()[0],3)]
            audit=verifier.verify(sequence,Pallet(25,10,10),ApproachConfig())
            self.assertTrue(audit['passed'],(audit['reason'],audit['box_id']))
            self.assertEqual([s['box_id'] for s in audit['stages'] if s['operation']=='pick'],['A','B','C'])
    def test_two_boxes_keep_obstacles_and_previous_robot_state(self):
        config=scene_config()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(config),encoding='utf-8')
            verifier=OfflineRobotVerifier(path)
            a=Box('A',10,10,10);b=Box('B',10,10,10)
            placements=[Placement(a,0,Point3D(0,0,0),a.orientations()[0],1),Placement(b,0,Point3D(15,0,0),b.orientations()[0],2)]
            audit=verifier.verify(placements,Pallet(25,10,10),ApproachConfig())
            self.assertTrue(audit['passed'],(audit['reason'],audit['box_id']))
            self.assertEqual(len(audit['stages']),12)
            np.testing.assert_allclose(audit['stages'][6]['trajectory'][0]['positions'],audit['stages'][5]['trajectory'][-1]['positions'])
            self.assertEqual([o['id'] for o in verifier.robot.obstacles],['pallet','placed_A','placed_B'])
    def test_complete_one_box_and_unreachable_are_distinguished(self):
        config=scene_config()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(config),encoding='utf-8')
            verifier=OfflineRobotVerifier(path)
            box=Box('B',10,10,10);pallet=Pallet(10,10,10)
            placement=Placement(box,0,Point3D(0,0,0),box.orientations()[0],1)
            audit=verifier.verify([placement],pallet,ApproachConfig())
            self.assertTrue(audit['passed'],audit)
            self.assertEqual([s['operation'] for s in audit['stages']],['approach_pick','pick','lift','transfer','place','retreat'])
            self.assertFalse(audit['hardware_verified'])
            for s in audit['stages']:
                self.assertGreaterEqual(s['trajectory'][-1]['time_from_start'],0.)
            config['base_T_pallet'][0][3]+=10
            config['path_budget_seconds']=.1
            path.write_text(json.dumps(config),encoding='utf-8')
            bad=OfflineRobotVerifier(path).verify([placement],pallet,ApproachConfig())
            self.assertFalse(bad['passed'])
            self.assertEqual(bad['status'],'unverified')

if __name__=='__main__':unittest.main()
